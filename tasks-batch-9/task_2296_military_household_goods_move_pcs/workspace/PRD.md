# Military Household Goods PCS Move API — Product Requirements Document

## 1. Introduction

When a service member receives permanent-change-of-station orders, the government becomes responsible for moving that household within a weight allowance the member did not choose and often does not understand. The allowance is a function of pay grade and dependent status; the pounds actually moved are discovered twice — first by a surveyor walking the rooms, later by a certified truck scale — and the difference between those two numbers is money the member may personally owe. Around that reconciliation sit a dozen other obligations: professional gear that must be documented before it can be excluded, weekly carrier capacity that must be rationed between routine and short-notice bookings, storage in transit that is authorized in days and priced in hundredweight, loss and damage claims whose payout basis depends entirely on how quickly the member filed, and personally procured moves whose reimbursement is the greater of an incentive percentage and a receipted expense total.

This document specifies the API that carries all of that. The system is, at its core, a **weight ledger**: one `EntitlementAuthorization` per set of orders, against which every shipment charges pounds, and from which every dollar of excess cost is derived. Because the charged weight of a single shipment can change three or four times over the life of a move — provisional survey estimate, certified actual weight, disputed weight, reweighed weight, verified professional-gear exclusions — the ledger is never incremented. It is recomputed from the current state of its contributing shipments on every event that touches it, and the recomputation is allowed to cascade: an amendment to the orders can reduce the allowance, which raises the excess cost due, which suspends the entitlement, which places every awarded shipment on hold. Implementers should read the cascade descriptions in §3 as mandatory, not illustrative.

The API is mounted under `/hhg`, is consumed by five distinct populations (relocating members, personal-property counselors, carrier coordinators, claims examiners and the program office), and is time-driven throughout: spread windows, counseling deadlines, storage day counts, claim filing windows and notification service levels all read a single server-side logical clock rather than wall-clock time. Every deadline in this specification is therefore deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. Acting Identity and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Exactly five roles are recognised, spelled here as they must appear in the header: `ServiceMember`, `MoveCounselor`, `TspCoordinator`, `ClaimsExaminer` and `ProgramAdmin`. If either header is absent, or if `X-User-Role` is any string outside that set of five, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the headers are well formed but the acting role does not appear in the authorised-role list published for the endpoint in §4, the request is rejected with `ERR_UNAUTHORIZED` (403).

The two roles that are backed by persisted entities bind `X-User-ID` to a stored record. When `X-User-Role` is `ServiceMember`, `X-User-ID` is the `id` of the acting `ServiceMember`; ownership checks on any resource that traces back to a `ServiceMember` compare the resource's chain of foreign keys against `X-User-ID`. When `X-User-Role` is `TspCoordinator`, `X-User-ID` is the `id` of the acting `MovingCompany`; a coordinator acts on behalf of the transportation service provider (TSP) whose identifier they present. The remaining three roles are opaque operator identifiers not tied to any persisted entity: when `X-User-Role` is `MoveCounselor`, `X-User-ID` is an opaque counselor identifier which the server records where a transition demands it (as `counselor_user_id` on a completed `CounselingSession`, `authorized_by_user_id` on an authorised entitlement, `verified_by_user_id` on a verified or rejected pro-gear declaration, and `approved_by_user_id` on an approved personally procured move packet) but never compares to any entity's `id`. When `X-User-Role` is `ClaimsExaminer`, `X-User-ID` is likewise opaque and is recorded as `reviewed_by_user_id` and `settled_by_user_id` on a claim. When `X-User-Role` is `ProgramAdmin`, `X-User-ID` is an opaque program-office identifier that the server may record on the actions it performs but never resolves to an entity.

Ownership is enforced separately from role membership. On every endpoint that a `ServiceMember` is permitted to call, the server resolves the target resource back to a `ServiceMember` identifier — a shipment through its order to `service_member_id`, a claim through its shipment and that shipment's order, a pro-gear declaration or PPM packet through its shipment, a counseling session or entitlement through its order — and rejects the request with `ERR_OWNERSHIP_REQUIRED` (403) when the resolved identifier is not the caller's `X-User-ID`. Counselors, coordinators, examiners and program administrators are not subject to this ownership check.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. `limit` sets the maximum number of records returned; when omitted it defaults to 10, the smallest accepted value is 1 and the largest accepted value is 100. `offset` sets how many records are skipped before the page begins; when omitted it defaults to 0 and it may not be negative. Both are echoed in the `meta` object of the envelope alongside `total_count` (the number of records matching the request before the page window is applied) and `has_more` (true when records remain beyond the current window).

Unless a specific endpoint states otherwise, every list is ordered by `created_at` ascending.

Reverse-lookup and collection endpoints also accept optional filters, each of which narrows the result set by exact match on the named field: `status`, `movement_status`, `weight_recon_status`, `move_type`, `market_code`, `is_short_notice`, `owner`, `sit_type`, `disposition`, `notification_type`, `order_id`, `entitlement_id`, `tsp_id` and `capacity_block_id`. Filters combine conjunctively, and an omitted filter imposes no restriction.

### 2.4. Common Resource Properties, Snapshots and the Logical Clock

Every persisted resource in this system — service members, orders, counseling sessions, entitlement authorizations, moving companies, capacity blocks, shipments, pro-gear declarations, storage authorizations, claims, claim items, PPM submissions and notification obligations alike — carries the same four server-managed properties:

- `id` (string): a server-minted UUID, with no type prefix of any kind.
- `created_at` (string): the ISO 8601 UTC instant at which the record was created, rendered with three fractional digits.
- `updated_at` (string): the ISO 8601 UTC instant of the most recent mutation of that record, in the same format.
- `version` (integer): a counter that starts at 1 on creation and increases by one on every mutation of the record.

There are no exceptions: no entity in this domain omits `updated_at` or `version`. Crucially, a mutation for these purposes includes a *derived* change made by a cascade. When a shipment's certified weight recomputes the owning entitlement's ledger fields, the entitlement itself has been mutated: its `updated_at` is refreshed and its `version` is incremented, even though no client addressed the entitlement directly. The same holds for a capacity block whose committed pools are re-summed, for a moving company whose performance score is recomputed, and for a shipment placed on hold by a suspension it did not cause.

All time-dependent behaviour reads a single server-side **logical clock** rather than the host's wall clock. Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to real time. An operational capability exists for test driving that accepts a `current_utc` instant and moves the clock to it, returning the new `current_utc`; setting the clock mutates no entity and fires no scheduled work. Every field described below as "stamped from the logical clock" — `booked_at`, `completed_at`, `filed_date`, `sent_at` and the instants used to evaluate deadlines — reads that clock.

Several fields are deliberate **snapshots** rather than live reads, and must not be re-derived from their source after capture. `dependents_count_at_issue` on a set of orders is copied from the member's `dependents_count` when the orders are issued, and thereafter only an amendment can change it. `rank_code_at_authorization` on an entitlement is copied from the member's `rank_code` when the entitlement is created. Allowance mathematics always reads the snapshot, never the live member record.

### 2.5. Peer Collections, Identifier Resolution and Rejection Precedence

The resource graph is flat: every entity is addressable as a peer collection beneath `/hhg`, and parenthood is expressed through foreign-key fields plus reverse-lookup sub-resource reads, never through identity-bearing nested paths. Where a path does contain more than one segment, identifiers are resolved strictly left to right, and the first unresolvable identifier determines the 404 that is returned: `ERR_SERVICE_MEMBER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_COUNSELING_SESSION_NOT_FOUND`, `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_TSP_NOT_FOUND`, `ERR_CAPACITY_BLOCK_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PRO_GEAR_DECLARATION_NOT_FOUND`, `ERR_SIT_AUTHORIZATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CLAIM_ITEM_NOT_FOUND`, `ERR_PPM_SUBMISSION_NOT_FOUND` or `ERR_NOTIFICATION_NOT_FOUND`.

Because most write endpoints carry several checks at once, the order in which failures surface is itself part of the contract. Checks are evaluated in the following sequence, and the first failing check produces the response; later checks never mask an earlier one:

1. Header presence and role legitimacy — `ERR_UNAUTHENTICATED`. Applies to every endpoint.
2. Role membership in the endpoint's authorised list — `ERR_UNAUTHORIZED`. Applies to every endpoint.
3. Request-body well-formedness — `ERR_INVALID_REQUEST` (400): unparseable body, an enum value outside the declared set, a negative weight, money or day figure, a missing required field, or a malformed array element (every `room_estimates` entry must carry `room_name` and `cube_feet`; every `trip_tickets` entry must carry `trip_number`, `full_lbs`, `empty_lbs`, `ticket_source` and `certified`). Applies to every write endpoint.
4. Path identifier resolution, left to right, yielding the corresponding not-found error above. Applies to every endpoint carrying a path parameter.
5. Foreign-key resolution for identifiers supplied in the body, checked in this declared field order — `service_member_id`, then `order_id`, then `entitlement_id`, then `tsp_id`, then `shipment_id`, then `superseded_shipment_id` — yielding `ERR_SERVICE_MEMBER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ENTITLEMENT_NOT_FOUND`, `ERR_TSP_NOT_FOUND` or `ERR_SHIPMENT_NOT_FOUND`. This guards order issuance, counseling-session booking, capacity-block publication, shipment booking, capacity award and award release.
6. Member ownership — `ERR_OWNERSHIP_REQUIRED`, on every endpoint a `ServiceMember` may call.
7. Claim segregation of duties — `ERR_SEGREGATION_OF_DUTIES`, on claim settlement only.
8. Waiver self-approval — `ERR_WAIVER_SELF_APPROVAL`, on excess-cost waiver creation only.
9. Order state — `ERR_INVALID_ORDER_STATE`, on order amendment only.
10. Counseling-session state — `ERR_INVALID_COUNSELING_STATE`, on session completion only.
11. Entitlement source state — `ERR_INVALID_ENTITLEMENT_STATE`, on entitlement authorization, resumption, excess-cost waiver creation and waiver revocation.
12. Shipment movement state — `ERR_INVALID_SHIPMENT_MOVEMENT_STATE`, on survey, pack, pickup, deliver, cancel and capacity award.
13. Shipment weight-reconciliation state — `ERR_INVALID_WEIGHT_RECON_STATE`, on recording the actual weight, disputing it, reweighing and reconciling.
14. Pro-gear declaration state — `ERR_INVALID_PRO_GEAR_STATE`, on verification, rejection and resubmission.
15. Storage-authorization state — `ERR_INVALID_SIT_STATE`, on storage authorization, extension and release.
16. Claim state — `ERR_INVALID_CLAIM_STATE`, on claim-item creation, submission, review, information request, information response, settlement, denial and individual item disposition.
17. PPM submission state — `ERR_INVALID_PPM_STATE`, on PPM approval.
18. Notification state — `ERR_INVALID_NOTIFICATION_STATE`, on notification dispatch.
19. Entitlement authorization gate — `ERR_ENTITLEMENT_NOT_AUTHORIZED`, on shipment booking, survey and pack.
20. Entitlement suspension gate — `ERR_ENTITLEMENT_SUSPENDED`, on shipment booking and capacity award.
21. Delivery precondition for claims — `ERR_SHIPMENT_NOT_DELIVERED`, on claim opening and claim submission.
22. Capacity award precondition for packing — `ERR_CAPACITY_BLOCK_NOT_ASSIGNED`, on pack.
23. Entitlement stale-version rejection — `ERR_STALE_ENTITLEMENT_VERSION`, on shipment booking.
24. Capacity-block stale-version rejection — `ERR_STALE_CAPACITY_BLOCK_VERSION`, on capacity award.
25. Provider standing — `ERR_TSP_NOT_ACTIVE`, on shipment booking and capacity award.
26. Market service — `ERR_MARKET_NOT_SERVED`, on shipment booking, capacity-block publication and capacity award.
27. Provider match between shipment and block — `ERR_SHIPMENT_TSP_MISMATCH`, on capacity award and award release.
28. Pro-gear documentation — `ERR_PRO_GEAR_DOCUMENTATION_REQUIRED`, on pro-gear verification.
29. Pro-gear cap — `ERR_PRO_GEAR_CAP_EXCEEDED`, on pro-gear verification.
30. Scale certification — `ERR_UNCERTIFIED_SCALE`, on recording the actual weight and on reweighing.
31. Loss-notice window — `ERR_LOSS_NOTICE_WINDOW_EXPIRED`, on claim opening.
32. Claim filing window — `ERR_CLAIM_FILING_WINDOW_EXPIRED`, on claim submission.
33. Weight-dispute window — `ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED`, on weight dispute.
34. Pickup inside the spread — `ERR_PICKUP_OUTSIDE_SPREAD`, on pickup.
35. Pack not too early — `ERR_PACK_BEFORE_SPREAD`, on pack.
36. Storage entry after pickup — `ERR_SIT_ENTRY_BEFORE_PICKUP`, on storage request.
37. Delivery after pickup — `ERR_DELIVERY_BEFORE_PICKUP`, on deliver.
38. Storage release after entry — `ERR_RELEASE_BEFORE_ENTRY`, on storage release.
39. Storage-period separation — `ERR_SIT_PERIOD_OVERLAP`, on storage request.
40. Capacity week separation — `ERR_CAPACITY_BLOCK_OVERLAP`, on capacity-block publication.
41. Storage day ceiling — `ERR_SIT_MAX_DAYS_EXCEEDED`, on storage authorization and extension.
42. At least one claim item — `ERR_CLAIM_ITEM_REQUIRED`, on claim submission.
43. No item still undecided — `ERR_CLAIM_ITEM_PENDING`, on claim settlement.
44. Non-empty survey — `ERR_SURVEY_ROOM_ESTIMATES_EMPTY`, on survey.
45. Information-request ceiling — `ERR_CLAIM_INFO_REQUEST_LIMIT`, on information request.
46. Amendment ceiling — `ERR_ORDER_AMENDMENT_LIMIT`, on order amendment.
47. Resubmission ceiling — `ERR_PRO_GEAR_RESUBMISSION_LIMIT`, on pro-gear resubmission.
48. Unique DoD identifier — `ERR_DUPLICATE_DOD_ID`, on member registration.
49. Unique order number — `ERR_DUPLICATE_ORDER_NUMBER`, on order issuance.
50. One entitlement per order — `ERR_DUPLICATE_ENTITLEMENT`, on session completion.
51. PPM method requirement — `ERR_PPM_METHOD_REQUIRED`, on PPM packet submission.
52. Weight-ticket completeness — `ERR_WEIGHT_TICKET_PAIR_INCOMPLETE`, on PPM packet submission and PPM approval.
53. Block accepting awards — `ERR_CAPACITY_BLOCK_NOT_OPEN`, on capacity award.
54. Weight basis present — `ERR_WEIGHT_BASIS_MISSING`, on capacity award.
55. Reserve protection — `ERR_SHORT_NOTICE_RESERVE_PROTECTED`, on capacity award.
56. Award existence — `ERR_AWARD_NOT_FOUND`, on award release.
57. Pool capacity — `ERR_CAPACITY_EXCEEDED`, on capacity award.
58. Nothing outstanding — `ERR_EXCESS_COST_UNPAID`, on weight reconciliation and entitlement resumption.
59. Waiver amount — `ERR_WAIVER_EXCEEDS_DUE`, on excess-cost waiver creation.
60. Something to revoke — `ERR_NO_WAIVER_TO_REVOKE`, on waiver revocation.

Two entries in that ladder deserve emphasis because they partition a single field's value space. The authorization gate rejects an entitlement that is still `DRAFT` or already `CLOSED`; the suspension gate rejects one that is `SUSPENDED`. The two are mutually exclusive by construction, so exactly one of `ERR_ENTITLEMENT_NOT_AUTHORIZED` and `ERR_ENTITLEMENT_SUSPENDED` can fire for any given entitlement.

### 2.6. Units, Precision and Rounding

Weights are always whole pounds. Where a weight derivation involves a fraction — converting cubic feet, applying a percentage uplift, halving an allowance — the result is rounded half up to a whole pound unless the rule explicitly says otherwise, and the two derivations that say otherwise (the local-move halving of an allowance and both capacity pool derivations) discard the fraction, that is, round down to the next lower whole pound.

Money is always carried to exactly two decimal places, and every monetary rounding in this specification is round half up. Where a formula rounds at more than one point, the rounding points are part of the formula and may not be collapsed into a single final rounding: rounding earlier or later than specified produces a different cent figure and is wrong. Percentages and rates (`short_notice_reserve_pct`, `effective_reserve_pct`, `fuel_surcharge_pct`, `depreciation_rate_pct_per_year`) preserve the precision at which they are defined or supplied and are not rounded to two decimals.

Freight pricing in this domain is quoted per **hundredweight** — per one hundred pounds. Wherever a rate is described as being per hundredweight, the pound figure is divided by one hundred without rounding before the rate is applied, so a shipment of 8,450 pounds contributes 84.5 hundredweight, not 84 or 85.

Day counts are whole days. Unless stated otherwise, the number of days between two instants is the count of complete 24-hour days between them, discarding any partial day.

### 2.7. Stale-Version Protection on Ledger and Capacity Writes

Two write operations consume a shared, mutable counter and therefore require the client to prove it has read the current state of the parent record before it writes.

Booking a shipment requires `expected_entitlement_version` in the request body. This field is not optional. Its value must equal the current `version` of the `EntitlementAuthorization` named by `entitlement_id`; if the entitlement's `version` has advanced since the client last read it, the booking is rejected with `ERR_STALE_ENTITLEMENT_VERSION` (HTTP 412). A member may legitimately hold several shipments against one entitlement, so nothing in the state machine blocks a second booking — the stale-version check is the mechanism that forces the client to re-read `charged_billable_weight_lbs` and `excess_cost_due_usd`, both of which move on every booking, before committing more weight to the ledger.

Awarding a shipment into a weekly capacity block requires `expected_capacity_block_version` in the request body, likewise non-optional. Its value must equal the current `version` of the `CapacityBlock` addressed in the path; a mismatch is rejected with `ERR_STALE_CAPACITY_BLOCK_VERSION` (HTTP 412). Multiple shipments may legitimately be awarded into the same week, so again no state precondition blocks the second award; the version check forces the coordinator to re-read `committed_general_lbs` and `committed_short_notice_lbs` before consuming more of the pool.

No other endpoint takes a version field, and no other endpoint performs a version comparison.

### 2.8. The Entitlement Weight Ledger and Its Invariants

The `EntitlementAuthorization` is the ledger of record for a move. Its charged figures are **recomputed, never incremented**. On every ledger-touching event — shipment booking, survey, recording the actual weight, reweighing, pro-gear verification, pro-gear rejection, shipment cancellation, PPM approval, order amendment, entitlement authorization, waiver creation and waiver revocation — the server re-derives `charged_billable_weight_lbs` and `pro_gear_excluded_total_lbs` from scratch by summing over the entitlement's contributing shipments, then re-derives `excess_weight_lbs`, `gross_excess_cost_usd` and `excess_cost_due_usd` from those sums.

The **ledger inclusion set** is fixed and referenced repeatedly below: a shipment contributes to its entitlement's charged figures when its `weight_recon_status` is `ESTIMATED`, `ACTUAL_RECORDED`, `DISPUTED` or `RECONCILED` **and** its `movement_status` is anything other than `CANCELLED`. A shipment whose `weight_recon_status` is still `PENDING` contributes nothing, and a `CANCELLED` shipment contributes nothing regardless of its weight status. Note that `DISPUTED` is inside the inclusion set: disputing a weight does not remove its pounds from the ledger. When the inclusion set is empty, `charged_billable_weight_lbs` is 0, `excess_weight_lbs` is 0 and `gross_excess_cost_usd` is 0.00.

Two invariants must hold after every ledger operation. First, the waiver invariant: `excess_cost_due_usd` plus `excess_cost_waived_usd` always equals `gross_excess_cost_usd`, which is why waiving cost never reduces the gross figure and revoking a waiver restores the amount due exactly. Second, the capacity conservation invariant: a block's `committed_lbs` always equals the sum of `billable_weight_lbs` over the shipments whose `capacity_block_id` names that block and whose `movement_status` is not `CANCELLED`.

### 2.9. Parallel Status Dimensions and Cascade Propagation

A `Shipment` carries two independent status dimensions that advance on their own schedules. `movement_status` tracks physical progress through the values `AWARDED`, `ON_HOLD`, `SURVEYED`, `PACKED`, `PICKED_UP`, `IN_SIT`, `DELIVERED` and `CANCELLED`. `weight_recon_status` tracks the reconciliation of weight through `PENDING`, `ESTIMATED`, `ACTUAL_RECORDED`, `DISPUTED` and `RECONCILED`. Neither dimension implies the other: a shipment can be `PICKED_UP` while still only `ESTIMATED`, and it can be `DELIVERED` while `DISPUTED`. A handful of operations move both dimensions at once, and those are called out explicitly in §3; every other operation moves exactly one.

Cascades in this system are declared, ordered and multi-level, and the server performs them synchronously as part of the triggering request. Two chains reach four levels deep and are the highest-value behaviours in the specification. The **ledger chain** runs: a shipment's billable weight changes → the owning entitlement's charged and excess figures are recomputed → if the amount due exceeds the suspension threshold and the entitlement is `AUTHORIZED`, it moves to `SUSPENDED` → every sibling shipment of that entitlement whose `movement_status` is `AWARDED` moves to `ON_HOLD`. The **performance chain** runs: a claim settles → the responsible provider's settled-claim counters and `performance_score` are recomputed → the provider's standing may drop from `ACTIVE` to `PROBATION` or to `SUSPENDED` → that provider's capacity blocks are restricted or closed accordingly. Every record touched at every level of a cascade has its `updated_at` refreshed and its `version` incremented, per §2.4.

### 2.10. Segregation of Duties and Self-Approval Bars

Two decisions in this system may not be taken by the person who set them up. A claim is settled by a `ClaimsExaminer` or `ProgramAdmin`, but never by the examiner whose `X-User-ID` was recorded as `reviewed_by_user_id` when the claim was taken under review; an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). This bar applies to settlement alone — paying money out is the act that requires a second pair of eyes — and not to denial, which the reviewing examiner may perform. Separately, an excess-cost waiver is granted by a `ProgramAdmin`, but never by the user whose `X-User-ID` was recorded as `authorized_by_user_id` on the entitlement being waived; that attempt is rejected with `ERR_WAIVER_SELF_APPROVAL` (403).

### 2.11. Notification Service Levels

Certain transitions create a **notification obligation** — a `Notification` record the program owes the member — rather than sending anything themselves. Each obligation records the `shipment_id` it belongs to, a `notification_type` set by the transition that created it, and `trigger_event_at`, the logical-clock instant of that transition. From the type the server selects `sla_hours`: three days (72 hours) for `PACK_DATE_CONFIRMED`, one day (24 hours) for both `PICKUP_CONFIRMED` and `SIT_ENTRY`, a full week (168 hours) for `WEIGHT_RECON_COMPLETE`, and five days (120 hours) for `CLAIM_ACK`. `due_by` is `trigger_event_at` advanced by `sla_hours` hours. An obligation begins life with `status` `PENDING`, with `channel`, `sent_at` null and `hours_late` 0.

## 3. Business Logic & Workflows

### 3.1. Service Members, Orders and the Amendment Cascade

A move begins with a member record. A `MoveCounselor` or `ProgramAdmin` registers a `ServiceMember` by supplying the member's ten-digit `dod_id` (exactly ten digits, and unique across all members — a repeat registration is refused with `ERR_DUPLICATE_DOD_ID`), the `full_name` as printed on orders (between 1 and 120 characters), the pay-grade `rank_code`, the uniformed-service `branch` and a notification `email`, which must contain an at-sign. `rank_code` must be one of `E1`, `E2`, `E3`, `E4`, `E5`, `E6`, `E7`, `E8`, `E9`, `W1`, `W2`, `W3`, `W4`, `W5`, `O1`, `O2`, `O3`, `O4`, `O5` or `O6`; `branch` must be one of `ARMY`, `NAVY`, `AIR_FORCE`, `MARINE_CORPS`, `SPACE_FORCE` or `COAST_GUARD`. Two household facts are optional at registration: `dependents_count`, which defaults to 0 and may not be negative or exceed 12, and `spouse_present`, which defaults to false and is what ultimately gates the spouse professional-gear allowance. The member's `active_shipment_count` starts at 0; the system maintains it as the count of that member's shipments whose `movement_status` is neither `DELIVERED` nor `CANCELLED`, incrementing it when a shipment is booked and decrementing it when one is cancelled.

Orders are issued against a member. The issuing counselor or administrator supplies `service_member_id`, the printed `order_number` (4 to 32 characters, unique across all orders — a collision yields `ERR_DUPLICATE_ORDER_NUMBER`), the `move_type`, the `issue_date`, the `report_no_later_than_date` by which the member must report to the gaining installation, the `origin_duty_station` being left and the `destination_duty_station` being joined, the `origin_market_code` of the losing installation, and the authorised `distance_miles`. `move_type` is one of `PCS_CONUS`, `PCS_OCONUS`, `SEPARATION`, `RETIREMENT` or `LOCAL`. The report date must fall strictly after the issue date. A market code is the three-letter form `MKT-` followed by exactly three uppercase letters, such as `MKT-ATL`. Mileage must be greater than zero and no more than 12,000. Dependent-restricted overseas tours are flagged at issuance with `is_dependent_restricted`, which defaults to false; when true, the entitlement is computed as though the member had no dependents even if dependents are on record. Issuance also snapshots the member's current `dependents_count` into `dependents_count_at_issue`, and sets `status` to `ISSUED`, `amendment_count` to 0 and `last_amendment_reason` to null.

Orders change. A counselor or administrator may amend a set of orders, moving `status` from `ISSUED` to `AMENDED` (or from `AMENDED` to `AMENDED` again, a self-loop). The request must carry an `amendment_reason`, and at least one of the three overrides — `dependents_count_override`, `report_no_later_than_date_override` or `move_type_override` — must be present; an amendment that changes nothing is not a valid request. Amendment is available only while the orders are `ISSUED` or `AMENDED`; once they are `CLOSED` the request is refused with `ERR_INVALID_ORDER_STATE`. At most three amendments are accepted per set of orders: the fourth attempt, made when `amendment_count` has already reached 3, is refused with `ERR_ORDER_AMENDMENT_LIMIT`. On acceptance, `amendment_count` increases by one and `last_amendment_reason` is set to the supplied reason; when `dependents_count_override` is present, `dependents_count_at_issue` is overwritten with that value.

An amendment is the entry point to the deepest cascade in the system, and each link is caused by the one before it. **First**, for the `EntitlementAuthorization` belonging to these orders whose `status` is `DRAFT`, `AUTHORIZED` or `SUSPENDED`, the server recomputes `dependent_status_effective`, `base_weight_allowance_lbs` and `total_billable_cap_lbs` under the allowance rules of §3.2 — an amendment that removes dependents or converts the move to a local move genuinely shrinks the allowance. **Second**, because the cap moved, the same entitlement's `excess_weight_lbs`, `gross_excess_cost_usd` and `excess_cost_due_usd` are recomputed under the excess-cost rules of §3.3. **Third**, if the recomputed `excess_cost_due_usd` now exceeds 2,500.00 US dollars and the entitlement is `AUTHORIZED`, the entitlement moves `AUTHORIZED → SUSPENDED` and its `suspension_reason` is set to `EXCESS_COST_UNPAID`. **Fourth**, every shipment charging that entitlement whose `movement_status` is `AWARDED` moves `AWARDED → ON_HOLD` with `hold_reason` set to `ENTITLEMENT_SUSPENDED`. A shipment already past `AWARDED` — surveyed, packed, picked up — is not disturbed by the hold.

The last state an order reaches is `CLOSED`, and no client ever requests it. When the entitlement derived from these orders reaches `CLOSED` (see §3.8), the orders bubble up from `ISSUED` or `AMENDED` to `CLOSED`, whereupon the weight ledger is frozen and any further amendment attempt draws `ERR_INVALID_ORDER_STATE`. `CLOSED` is terminal for a set of orders.

### 3.2. Counseling Appointments, Entitlement Authorization and the Weight Allowance

Before anything moves, the member is counseled. A counselor or administrator books a `CounselingSession` against orders by supplying `order_id`, the `session_type` — one of `SELF_SERVICE`, `VIRTUAL` or `IN_PERSON` — and the appointment instant `scheduled_at`. At booking, the server derives `counseling_deadline_at` as the orders' `report_no_later_than_date` less a two-week lead time of 14 days. A new session's `status` is `SCHEDULED`, with `counselor_user_id`, `completed_at` null, `entitlement_briefed` false and `is_late_counseling` false.

Completing the session is exclusive to a `MoveCounselor` and moves `status` from `SCHEDULED` to `COMPLETED`; attempting it on a session that is already `COMPLETED` draws `ERR_INVALID_COUNSELING_STATE`. The completing counselor must attest in the request body that `entitlement_briefed` is true — that the member was briefed on the entitlement and on personal liability for excess cost. Completion also requires that no `EntitlementAuthorization` yet exists for these orders; a second session attempting to create a second entitlement for the same orders is refused with `ERR_DUPLICATE_ENTITLEMENT`. On completion, `completed_at` is stamped from the logical clock, `counselor_user_id` is stamped from `X-User-ID`, and `is_late_counseling` is set true when `completed_at` falls strictly after `counseling_deadline_at` — completing exactly at the deadline is not late.

Completion is also what brings the entitlement into being. One `EntitlementAuthorization` is created in `status` `DRAFT`, carrying `order_id` copied from the session's orders and `counseling_session_id` naming the session that produced it, with `admin_weight_bump_lbs` initialised to 0, `rank_code_at_authorization` snapshotted from the member's `rank_code`, and the allowance fields computed as follows.

The allowance rests on two derived facts. `dependent_status_effective` is `WITH_DEPENDENTS` when the orders' `dependents_count_at_issue` is at least 1 **and** `is_dependent_restricted` is false; in every other case — no dependents on the orders, or a dependent-restricted tour — it is `WITHOUT_DEPENDENTS`. The member's `rank_code_at_authorization` then selects a pay-grade tier: grades `E1` through `E4` share one tier; `E5`, `E6`, `E7`, `E8` and `E9` each form their own; `W1` and `O1` share a tier, as do `W2` with `O2`, `W3` with `O3`, `W4` with `O4`, and `W5` with `O5`; `O6` stands alone. Each tier publishes two allowances in pounds, the first for a move without dependents and the second for a move with them: the `E1`–`E4` tier allows 5,000 or 8,000; `E5` allows 7,000 or 9,000; `E6` allows 8,000 or 11,000; `E7` allows 11,000 or 13,000; `E8` allows 12,000 or 14,000; `E9` allows 13,000 or 15,000; the `W1`/`O1` tier allows 10,000 or 12,000; `W2`/`O2` allows 12,500 or 13,500; `W3`/`O3` allows 13,000 or 14,500; `W4`/`O4` allows 14,000 or 17,000; `W5`/`O5` allows 16,000 or 17,500; and `O6` allows 18,000 either way.

The `move_type` modifier is applied to the table figure **after** the lookup, and only one modifier can apply. If the move is `LOCAL`, the table figure is halved and any fraction of a pound is discarded, that is, rounded down to a whole pound. Otherwise, if the move is a `SEPARATION` or a `RETIREMENT`, the figure is capped at 13,000 pounds — the lesser of the table figure and 13,000 is taken. A `PCS_CONUS` or `PCS_OCONUS` move leaves the table figure untouched. The result is `base_weight_allowance_lbs`.

Two professional-gear allowances are set alongside it. `pro_gear_member_allowance_lbs` is always 2,000 pounds. `pro_gear_spouse_allowance_lbs` is 500 pounds when `dependent_status_effective` is `WITH_DEPENDENTS` **and** the member's `spouse_present` is true, and 0 pounds otherwise. Finally `total_billable_cap_lbs` — the figure the ledger actually measures against — is `base_weight_allowance_lbs` plus `admin_weight_bump_lbs`.

Authorizing the entitlement moves it `DRAFT → AUTHORIZED` and is available to a counselor or administrator; attempting it on an entitlement that is not `DRAFT` draws `ERR_INVALID_ENTITLEMENT_STATE`. The request may carry `admin_weight_bump_lbs`, an administrative allowance increase that must be at least 0 and no more than 2,000 pounds and defaults to 0 when omitted. The supplied bump is stored, `total_billable_cap_lbs` is recomputed with it, the excess figures are recomputed against the new cap, and `authorized_by_user_id` is stamped from `X-User-ID` — the identifier that later bars this same user from waiving the entitlement's excess cost.

### 3.3. Excess Weight Cost, Waivers, Suspension and Resumption

Excess cost is derived in five ordered steps, and the order matters because two of the steps select a rate from a figure produced by an earlier step.

**Step one** rolls up the ledger. `charged_billable_weight_lbs` is the sum of `billable_weight_lbs` over the entitlement's contributing shipments — the inclusion set defined in §2.8 — and `pro_gear_excluded_total_lbs` is the sum of `pro_gear_excluded_lbs` over that same set. Both are order-insensitive sums; what matters is the state filter.

**Step two** takes excess pounds: `excess_weight_lbs` is the charged weight less `total_billable_cap_lbs`, or zero if the charged weight does not exceed the cap.

**Step three** selects the transportation rate, and it keys on the **ratio** of overage rather than the pound count. Divide `excess_weight_lbs` by `total_billable_cap_lbs` and keep the quotient unrounded; this figure is surfaced on the ledger read as `excess_pct_over`. When the ratio is at most one tenth, the rate is 62.50 US dollars per hundredweight; when it is greater than one tenth but at most one quarter, the rate is 78.00; beyond one quarter it is 94.50. The selected rate is surfaced as `excess_rate_per_cwt`.

**Step four** prices the overage and then the paperwork. The gross transportation charge is `excess_weight_lbs` expressed in hundredweight, multiplied by the selected rate, rounded half up to cents. The administrative fee, surfaced as `admin_fee_usd`, is zero when that transportation charge is below 500.00 US dollars, and otherwise six percent of the transportation charge rounded half up to cents — note that the fee is keyed on the transportation charge alone, never on any figure that already includes the fee. `gross_excess_cost_usd` is the transportation charge plus the administrative fee, rounded half up to cents.

**Step five** applies the waiver ledger. `excess_cost_due_usd` is `gross_excess_cost_usd` less `excess_cost_waived_usd`, rounded half up to cents and floored at zero. `excess_cost_waived_usd` itself defaults to 0.00 and can never exceed `gross_excess_cost_usd`.

Waivers are exclusive to the program office. A `ProgramAdmin` waives excess cost by supplying a `waived_amount_usd` and a `waiver_reason`; the amount may not exceed the `excess_cost_due_usd` currently outstanding, and a larger request is refused with `ERR_WAIVER_EXCEEDS_DUE`. Acceptance increases `excess_cost_waived_usd` by the waived amount, records the reason in `waiver_reason`, and reduces `excess_cost_due_usd` by the same amount; `gross_excess_cost_usd` is deliberately left untouched, preserving the invariant of §2.8. Waivers are only entertained while the entitlement is `AUTHORIZED` or `SUSPENDED`; otherwise `ERR_INVALID_ENTITLEMENT_STATE` applies.

Revocation is the compensating action, also exclusive to the program office. Supplying a `revocation_reason` resets `excess_cost_waived_usd` to 0.00 and restores `excess_cost_due_usd` to the full `gross_excess_cost_usd`. Revocation requires that something has in fact been waived: when `excess_cost_waived_usd` is already zero, the request is refused with `ERR_NO_WAIVER_TO_REVOKE`. Because revocation can push the amount due back above the threshold, it can re-suspend the entitlement and place awarded shipments back on hold, exactly as an amendment can.

Suspension itself is never requested by a client. Whenever a ledger recompute — from recording an actual weight, from a reweigh, from a pro-gear verification or rejection, from an order amendment, from a shipment booking, from a waiver revocation — leaves `excess_cost_due_usd` strictly greater than 2,500.00 US dollars while the entitlement is `AUTHORIZED`, the entitlement moves `AUTHORIZED → SUSPENDED`, `suspension_reason` is set to `EXCESS_COST_UNPAID`, and every shipment of that entitlement sitting at `AWARDED` moves to `ON_HOLD` with `hold_reason` `ENTITLEMENT_SUSPENDED`. While suspended, the ledger takes no new commitments: booking another shipment or awarding capacity is refused with `ERR_ENTITLEMENT_SUSPENDED`.

Resumption reverses it. A counselor or administrator may return a `SUSPENDED` entitlement to `AUTHORIZED`, optionally recording a `resume_note`. Two conditions apply: the entitlement must currently be `SUSPENDED` (otherwise `ERR_INVALID_ENTITLEMENT_STATE`), and `excess_cost_due_usd` must be exactly zero (otherwise `ERR_EXCESS_COST_UNPAID`) — in practice a waiver covering the full outstanding amount is how that zero is reached. On resumption, `suspension_reason` is cleared to null and every shipment of the entitlement whose `movement_status` is `ON_HOLD` moves `ON_HOLD → AWARDED` with `hold_reason` cleared to null. The cycle `AUTHORIZED → SUSPENDED → AUTHORIZED` may repeat any number of times.

For transparency, the entitlement exposes a computed ledger read that returns, alongside `entitlement_id`, the whole derivation: `total_billable_cap_lbs`, `charged_billable_weight_lbs`, `pro_gear_excluded_total_lbs`, `excess_weight_lbs`, `excess_pct_over`, `excess_rate_per_cwt`, `admin_fee_usd`, `gross_excess_cost_usd`, `excess_cost_waived_usd`, `excess_cost_due_usd` and `contributing_shipment_count`, the number of shipments currently inside the inclusion set.

### 3.4. Transportation Providers, Markets and Weekly Capacity

Providers are onboarded by the program office alone. A `MovingCompany` is created with its legal `name`, its `scac_code` — exactly four uppercase letters, unique across all providers — and a non-empty `markets` array of market codes it is qualified to serve, each in the `MKT-` plus three uppercase letters form. A new provider starts with `settled_claim_count` 0, `claim_settlement_total_usd` 0.00, `performance_score` 100.00 and `status` `ACTIVE`. Provider standing is one of `ACTIVE`, `PROBATION` or `SUSPENDED`; a `SUSPENDED` provider takes no new work, so booking a shipment with that provider or awarding capacity to one of its blocks is refused with `ERR_TSP_NOT_ACTIVE`, while `PROBATION` remains eligible.

Weekly capacity is published as `CapacityBlock` records by a `TspCoordinator` or the program office. A block names its `tsp_id` and `market_code`, a `week_start_date` that must be a Monday at midnight UTC, and a `total_capacity_lbs` greater than zero, and it may carry a `short_notice_reserve_pct` between 0 and 0.5 inclusive, which defaults to 0.15. The server derives `week_end_date` as `week_start_date` advanced by seven days; the week is the half-open interval that includes its start instant and excludes its end instant. Two blocks for the same `tsp_id` and `market_code` may not cover overlapping weeks — because the interval is half-open, a block starting exactly on another's `week_end_date` is perfectly legal, while any genuine overlap is refused with `ERR_CAPACITY_BLOCK_OVERLAP`. The block's `market_code` must also be one the owning provider serves; otherwise `ERR_MARKET_NOT_SERVED` applies.

A block is either inside or outside the peak moving season. `peak_season` is true when `week_start_date` falls on or between the fifteenth of May and the thirtieth of September of its own calendar year, both dates inclusive. From that flag the reserve is derived: `effective_reserve_pct` is the greater of the block's `short_notice_reserve_pct` and a peak floor of 0.25 when `peak_season` is true, and simply `short_notice_reserve_pct` otherwise. The pools follow: `general_pool_lbs` is `total_capacity_lbs` multiplied by one minus `effective_reserve_pct`, with the fraction discarded — rounded down to a whole pound — and `short_notice_pool_lbs` is whatever remains, that is, `total_capacity_lbs` less `general_pool_lbs`. A fresh block has `committed_general_lbs`, `committed_short_notice_lbs` and `committed_lbs` all at 0, and `status` `OPEN` — except that a block published by a provider already on `PROBATION` opens as `RESTRICTED`.

Awarding capacity consumes a pool. The award request names the `shipment_id` and carries `expected_capacity_block_version` per §2.7. Several referential conditions are checked: the shipment's `tsp_id` must equal the block's `tsp_id`, or the award is refused with `ERR_SHIPMENT_TSP_MISMATCH`; the shipment's `origin_market_code` must appear in the provider's `markets` and must equal the block's `market_code`, or `ERR_MARKET_NOT_SERVED` applies; the shipment's `movement_status` must be `AWARDED` or `SURVEYED`, since capacity is booked either side of the pre-move survey but never once the goods are packed, and any other movement state draws `ERR_INVALID_SHIPMENT_MOVEMENT_STATE`; and the shipment must already have a weight of record, meaning its `billable_basis` is not `NONE`, or the award is refused with `ERR_WEIGHT_BASIS_MISSING`. A block that is `CLOSED` accepts nothing, and a block that is `RESTRICTED` accepts only a short-notice shipment; anything else draws `ERR_CAPACITY_BLOCK_NOT_OPEN`.

The allocation itself is a waterfall, and short-notice shipments are privileged. Let the pounds being awarded be the shipment's `billable_weight_lbs`. For a shipment whose `is_short_notice` is true, the whole block is available: the pounds are compared with `total_capacity_lbs` less `committed_lbs`, and the award is refused with `ERR_CAPACITY_EXCEEDED` only when the pounds strictly exceed that remainder — an award that exactly fills the block is accepted. On acceptance the pounds are added to `committed_short_notice_lbs`. For a shipment whose `is_short_notice` is false, only the general pool is available: the pounds are compared with `general_pool_lbs` less `committed_general_lbs`, and when the pounds strictly exceed that general remainder the award fails — with `ERR_SHORT_NOTICE_RESERVE_PROTECTED` when the pounds would nevertheless have fitted inside `total_capacity_lbs` less `committed_lbs`, meaning the only way to accommodate them would be to eat into the short-notice reserve, and with `ERR_CAPACITY_EXCEEDED` when they would not have fitted even then. On acceptance the pounds are added to `committed_general_lbs`. In both branches `committed_lbs` is then re-derived as `committed_general_lbs` plus `committed_short_notice_lbs`, and the shipment's `capacity_block_id` is set to the block.

After every award, every award release and every shipment cancellation, the block's `status` is re-derived in this order. It becomes `CLOSED` when `committed_lbs` has reached or passed `total_capacity_lbs`, or when the owning provider is `SUSPENDED`. Failing that, it becomes `RESTRICTED` when `committed_lbs` has reached or passed ninety percent of `total_capacity_lbs` — the threshold being ninety percent of the total with the fraction discarded — or when the owning provider is on `PROBATION`. Otherwise it is `OPEN`. The consequences are visible in the state transitions: `OPEN → RESTRICTED` closes the door on general-pool awards while still admitting short-notice ones, `RESTRICTED → CLOSED` closes it on everything, and the reverse transitions `CLOSED → RESTRICTED` and `RESTRICTED → OPEN` reopen short-notice and then general awards as pounds are returned.

Releasing an award is the compensating action, available to a coordinator or the program office. The request names the `shipment_id` and a `release_reason`. The shipment must actually hold an award on that block — otherwise `ERR_AWARD_NOT_FOUND` — and its `tsp_id` must still match the block's, or `ERR_SHIPMENT_TSP_MISMATCH` applies. Release clears the shipment's `capacity_block_id` to null and subtracts its `billable_weight_lbs` from the very same pool counter that received it, then re-derives `committed_lbs` and the block `status`.

### 3.5. Booking a Shipment: Short Notice, Peak Season and the Spread Window

A shipment is booked by a counselor or the program office against orders and an entitlement. The body supplies `order_id`, `entitlement_id`, the assigned `tsp_id`, a TSP-visible `shipment_code` (4 to 24 characters, unique across all shipments), the `shipment_method`, the `origin_market_code`, the member's `requested_pack_date`, `requested_pickup_date` and `requested_delivery_date`, and the `expected_entitlement_version` of §2.7. When the shipment replaces a cancelled one, the body also carries `superseded_shipment_id` naming that cancelled predecessor; original shipments leave it null. `shipment_method` is one of `HHG` for household goods, `UB` for unaccompanied baggage, `NTS` for non-temporary storage or `PPM` for a personally procured move. The requested pickup date must be on or after the requested pack date, and the requested delivery date must be strictly after the requested pickup date.

Booking is gated on the ledger and the provider. The entitlement must be neither `DRAFT` nor `CLOSED` — a ledger never authorized, or already closed, takes no shipment work, and the attempt draws `ERR_ENTITLEMENT_NOT_AUTHORIZED`; a `SUSPENDED` ledger draws `ERR_ENTITLEMENT_SUSPENDED`. The provider must not be `SUSPENDED`, and the shipment's `origin_market_code` must be in that provider's `markets`, on pain of `ERR_TSP_NOT_ACTIVE` and `ERR_MARKET_NOT_SERVED` respectively.

On acceptance the shipment is stamped and its windows derived. `booked_at` is taken from the logical clock. The number of whole days from `booked_at` to `requested_pickup_date` is computed by discarding any partial day, and `is_short_notice` is true when that count is strictly fewer than five days. Independently, `peak_season` is true when `requested_pickup_date` falls on or between the fifteenth of May and the thirtieth of September, both inclusive. Where both flags are true, **short notice takes precedence**: a short-notice booking receives a spread of zero days before and two days after the requested pickup date; failing that, a peak-season booking receives two days before and seven days after; and an ordinary booking receives one day before and four days after. `spread_start_date` is `requested_pickup_date` moved back by the before-days and `spread_end_date` is `requested_pickup_date` moved forward by the after-days, the latter being an inclusive endpoint.

Transit time is derived at the same moment. `transit_days_allowed` is the mileage-based figure — the orders' `distance_miles` divided by 300 miles per transit day and rounded **up** to a whole day — plus two extra days when `peak_season` is true, with the whole result then raised to a floor of five days if it came out lower. `required_delivery_by` remains null until pickup, at which point it becomes the `actual_pickup_date` advanced by `transit_days_allowed` days.

A new shipment enters the world with `movement_status` `AWARDED`, `weight_recon_status` `PENDING`, `capacity_block_id` null, `billable_weight_lbs` 0, `billable_basis` `NONE`, `pro_gear_excluded_lbs` 0, `reweigh_required` false, and `survey_date`, `estimate_method`, `room_estimates`, `estimated_gross_lbs`, `actual_gross_lbs`, `actual_tare_lbs`, `net_actual_lbs`, `weigh_date`, `pack_date`, `actual_pickup_date`, `delivery_date`, `hold_reason` and `cancel_reason` all null or zero as their types dictate. Booking increments the member's `active_shipment_count`, bumps the entitlement's `version`, and triggers a ledger recompute — which changes no pounds, since a `PENDING` shipment is outside the inclusion set, but does move the entitlement's `version` and is precisely why the next booking needs a fresh `expected_entitlement_version`. Shipments that supersede a given cancelled shipment can be listed by following the self-reference in reverse.

### 3.6. Pre-Move Survey, Professional Gear and the Billable Weight Basis

The pre-move survey is the coordinator's exclusive act and it advances both status dimensions at once: `movement_status` moves `AWARDED → SURVEYED` and, in parallel, `weight_recon_status` moves `PENDING → ESTIMATED`. It is available only while the shipment is `AWARDED` with `weight_recon_status` `PENDING` and the owning entitlement is `AUTHORIZED`; wrong movement state draws `ERR_INVALID_SHIPMENT_MOVEMENT_STATE`, and an entitlement that is `DRAFT` or `CLOSED` draws `ERR_ENTITLEMENT_NOT_AUTHORIZED`. A survey may be performed once only per shipment; no previously stored survey data is ever reused.

The request carries an `estimate_method`, either `CUBE_X7` or `INVENTORY_TABLE`, and a `room_estimates` array whose entries each pair a `room_name` with a `cube_feet` figure greater than zero. An empty array is refused with `ERR_SURVEY_ROOM_ESTIMATES_EMPTY`. Conversion from cube to pounds is where the rounding order bites, and it is pinned: **each room line is converted and rounded first, then the lines are summed, then the uplift is applied.** For every entry, in the order the array was submitted, multiply its `cube_feet` by seven pounds per cubic foot and round half up to a whole pound. Sum those per-room pounds to obtain the raw survey weight. Then, only when `estimate_method` is `CUBE_X7`, compute an accessorial uplift of five percent of that raw sum, rounded half up to a whole pound; for `INVENTORY_TABLE` the uplift is zero. `estimated_gross_lbs` is the raw sum plus the uplift. Summing the cube figures first and multiplying once produces a different integer and is not the specified result.

Professional gear is declared separately, and it is the only weight that can be excluded from what the ledger charges. A member or counselor files a `ProGearDeclaration` against a shipment with the `owner` — `MEMBER` or `SPOUSE` — an `item_description`, a `claimed_weight_lbs` greater than zero and no greater than 2,500, and a `documentation_type` of `ITEMIZED_INVENTORY`, `EMPLOYER_LETTER`, `ORDERS_EXTRACT` or `NONE`. A new declaration is `SUBMITTED` with `verified_weight_lbs` 0, `verified_by_user_id` and `rejection_reason` null and `resubmission_count` 0, and contributes nothing to any weight until it is verified.

Verification belongs exclusively to the `MoveCounselor` and branches on one comparison. The request supplies `verified_weight_lbs`. When the verified figure equals `claimed_weight_lbs`, the declaration moves `SUBMITTED → VERIFIED`; when it is greater than zero but strictly less than the claimed figure, it moves `SUBMITTED → PARTIALLY_VERIFIED`. Both branches are otherwise identical: both require the declaration to be `SUBMITTED` (else `ERR_INVALID_PRO_GEAR_STATE`), both require `documentation_type` to be anything other than `NONE` (else `ERR_PRO_GEAR_DOCUMENTATION_REQUIRED`), and both require that the verified figure not exceed `claimed_weight_lbs` and that the running total of verified weight for that shipment and that owner, this declaration included, stay within the owner's allowance — 2,000 pounds for `MEMBER`, and the entitlement's `pro_gear_spouse_allowance_lbs` for `SPOUSE`, which is 500 pounds only where a spouse is present on a with-dependents move and 0 otherwise. A breach of either bound is refused with `ERR_PRO_GEAR_CAP_EXCEEDED`. Both branches store `verified_weight_lbs` and stamp `verified_by_user_id` from `X-User-ID`, both recompute the shipment's `pro_gear_excluded_lbs` and `billable_weight_lbs` under whatever basis is currently in force, and both then recompute the owning entitlement's `charged_billable_weight_lbs`, `pro_gear_excluded_total_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and `excess_cost_due_usd`. The only difference between them is the number of pounds that lands.

Rejection is the counselor's other exclusive option. It moves `SUBMITTED → REJECTED`, stores the supplied `rejection_reason` and stamps `verified_by_user_id`, leaves `verified_weight_lbs` at 0, and still recomputes the shipment's `pro_gear_excluded_lbs` and `billable_weight_lbs` and the entitlement ledger — the declaration simply contributes nothing. A member may then resubmit with a better `claimed_weight_lbs` and `documentation_type`, which moves the declaration `REJECTED → SUBMITTED`, replaces both values, increments `resubmission_count` and clears `rejection_reason` to null. This revision loop is bounded: with `resubmission_count` already at 2, a further attempt is refused with `ERR_PRO_GEAR_RESUBMISSION_LIMIT`. `VERIFIED` and `PARTIALLY_VERIFIED` are terminal for a declaration.

Billable weight itself is derived in two steps and exists in two variants. **Step one** computes the exclusion. Sum `verified_weight_lbs` across the shipment's declarations with `owner` `MEMBER` whose `status` is `VERIFIED` or `PARTIALLY_VERIFIED`, and cap that sum at `pro_gear_member_allowance_lbs`; do the same for `SPOUSE`, capping at `pro_gear_spouse_allowance_lbs`; `pro_gear_excluded_lbs` is the sum of the two capped amounts. Declarations that are `SUBMITTED` or `REJECTED` contribute zero. **Step two** selects the basis from `weight_recon_status`. Where the status is `ESTIMATED`, the **provisional estimated** variant applies: `billable_weight_lbs` is `estimated_gross_lbs` less `pro_gear_excluded_lbs`, floored at zero, and `billable_basis` is set to `ESTIMATED`. Where the status is `ACTUAL_RECORDED`, `DISPUTED` or `RECONCILED`, the **final actual** variant applies: `net_actual_lbs` is `actual_gross_lbs` less `actual_tare_lbs`, and `billable_weight_lbs` is `net_actual_lbs` less `pro_gear_excluded_lbs`, floored at zero, with `billable_basis` set to `ACTUAL`. In any other case `billable_weight_lbs` is 0 and `billable_basis` is `NONE`. The two variants charge genuinely different pound counts for the same household — the survey figure is cube-derived, the actual figure is scale-derived — and the final actual figure **replaces** the provisional one rather than adding to it, which is exactly why the entitlement ledger is recomputed from the inclusion set instead of being incremented. Alongside the actual basis, `reweigh_required` is set true when `net_actual_lbs` strictly exceeds `estimated_gross_lbs` multiplied by 1.10, that is, when the scale came in more than ten percent above the survey.

### 3.7. Packing, Pickup, Storage in Transit, Delivery and Cancellation

Packing is a coordinator action that moves `movement_status` `SURVEYED → PACKED`. Three conditions guard it: the shipment must be `SURVEYED`, the owning entitlement must be `AUTHORIZED`, and the shipment must already hold a weekly capacity slot — a null `capacity_block_id` is refused with `ERR_CAPACITY_BLOCK_NOT_ASSIGNED`. The request supplies `pack_date`, which may be no earlier than one day before `spread_start_date`; an earlier date is refused with `ERR_PACK_BEFORE_SPREAD`. On acceptance `pack_date` is stored and one notification obligation of type `PACK_DATE_CONFIRMED` is created for the shipment in `status` `PENDING`, with `trigger_event_at` taken from the logical clock.

Pickup follows and moves `movement_status` `PACKED → PICKED_UP`. The coordinator supplies `actual_pickup_date`, which must fall inside the closed spread window — on or after `spread_start_date` and on or before `spread_end_date`. A date outside those bounds is refused with `ERR_PICKUP_OUTSIDE_SPREAD`. On acceptance `actual_pickup_date` is stored, `required_delivery_by` is fixed at that date advanced by `transit_days_allowed` days, and one `PENDING` notification obligation of type `PICKUP_CONFIRMED` is created.

Goods in transit may be warehoused. A coordinator or counselor requests storage against a picked-up shipment with a `sit_type` of `ORIGIN` or `DESTINATION`, an `entry_date` giving the first, inclusive day of storage, and a `requested_days` count greater than zero and no greater than 90. The entry date may not precede the shipment's `actual_pickup_date`, on pain of `ERR_SIT_ENTRY_BEFORE_PICKUP`. Storage periods of the same shipment must also stay apart: treating a requested period as the inclusive day range from `entry_date` through `entry_date` plus `requested_days`, that range may neither overlap nor so much as touch the range of any existing storage authorization of the same shipment that has not been released — a mandatory one-day gap is required between consecutive periods, and a violation is refused with `ERR_SIT_PERIOD_OVERLAP`. A new request is `REQUESTED` with `authorized_days` 0, `extension_days` 0, `total_authorized_days` 0, `release_date` null, and every cost figure at 0.00.

Authorizing storage is a counselor or program-office action that moves the authorization `REQUESTED → AUTHORIZED` and, in the same breath, the shipment `PICKED_UP → IN_SIT`. It requires the authorization to be `REQUESTED` (else `ERR_INVALID_SIT_STATE`) and the shipment to be `PICKED_UP`. The request supplies `authorized_days`, which must be greater than zero and no greater than 90; `total_authorized_days` is then `authorized_days` plus `extension_days`. One `PENDING` notification obligation of type `SIT_ENTRY` is created. Storage may be extended in place — a self-loop that keeps the authorization `AUTHORIZED` — by supplying additional `extension_days` and an `extension_reason`; the additional days accumulate into the stored `extension_days` and `total_authorized_days` is recomputed. The ceiling is absolute: an authorization or extension that would carry `authorized_days` plus `extension_days` above 90 days is refused with `ERR_SIT_MAX_DAYS_EXCEEDED`.

Release is the coordinator's exclusive act. It moves the authorization `AUTHORIZED → RELEASED` and the shipment `IN_SIT → PICKED_UP`, so a shipment may cycle in and out of storage more than once; the shipment only returns to `PICKED_UP` when no other storage authorization of that shipment remains `AUTHORIZED` after this release. The supplied `release_date` must not precede `entry_date`, on pain of `ERR_RELEASE_BEFORE_ENTRY`, and the authorization must be `AUTHORIZED`.

Release also prices the stay, in four pinned steps. First, `days_used` is the count of whole days from `entry_date` to `release_date`, discarding any partial day, but never fewer than one day — a same-day stay still bills a day. `excess_days` is `days_used` less `total_authorized_days`, floored at zero. The tiered day split follows: the first-tier days are `days_used` capped at 30, and the extra days are `days_used` less 30, floored at zero. The shipment's current `billable_weight_lbs` — whatever basis is in force at release time — is expressed in hundredweight without rounding. **Step one** computes three charges, each rounded half up to cents: a handling charge of 68.40 US dollars per hundredweight; a first-tier storage charge of 1.05 US dollars per hundredweight per day for the first-tier days; and an extended storage charge of 1.62 US dollars per hundredweight per day for the extra days. **Step two** sets `sit_base_cost_usd` to the sum of those three, rounded half up to cents. **Step three** selects `fuel_surcharge_pct` from `sit_base_cost_usd` — and from the base figure only, never from a figure that already contains the surcharge, since that definition would be circular: the rate is 0.045 when the base is below 1,000.00 US dollars, 0.062 when the base is below 5,000.00, and 0.071 when the base is 5,000.00 or more — and sets `fuel_surcharge_usd` to the base multiplied by that rate, rounded half up to cents. **Step four** sets `sit_total_cost_usd` to `sit_base_cost_usd` plus `fuel_surcharge_usd`, rounded half up to cents. Finally `member_liability_usd` is 0.00 when `excess_days` is zero, and otherwise the share of `sit_total_cost_usd` attributable to the excess days — the total multiplied by `excess_days` and divided by `days_used`, rounded half up to cents.

Delivery is the coordinator's closing act on the movement dimension, moving `PICKED_UP → DELIVERED`. It requires the shipment to be `PICKED_UP`, the `weight_recon_status` to be `ACTUAL_RECORDED`, `DISPUTED` or `RECONCILED` — goods cannot be delivered against a bare survey estimate — and the supplied `delivery_date` to be no earlier than `actual_pickup_date`, on pain of `ERR_DELIVERY_BEFORE_PICKUP`. `delivery_date` is stored, and it is the anchor from which both loss-and-damage windows are measured. `DELIVERED` is terminal for the movement dimension.

Cancellation is available to the member, a counselor or the program office, and only before the goods are gone: `movement_status` may be `AWARDED`, `ON_HOLD`, `SURVEYED` or `PACKED`, and any other movement state draws `ERR_INVALID_SHIPMENT_MOVEMENT_STATE`. The supplied `cancel_reason` is stored and `movement_status` becomes `CANCELLED`, which is terminal. Cancellation then unwinds three levels. **First**, the owning entitlement's `charged_billable_weight_lbs`, `pro_gear_excluded_total_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and `excess_cost_due_usd` are recomputed with this shipment now outside the inclusion set. **Second**, because those pounds have also left the capacity sums, if `capacity_block_id` is not null that block's `committed_general_lbs`, `committed_short_notice_lbs` and `committed_lbs` are recomputed. **Third**, that block re-derives its `status`: `RESTRICTED → OPEN` when `committed_lbs` has fallen below ninety percent of `total_capacity_lbs` and the owning provider is `ACTIVE`, and `CLOSED → RESTRICTED` when `committed_lbs` has fallen below `total_capacity_lbs`. Cancellation also decrements the member's `active_shipment_count`. A replacement shipment may then be booked naming the cancelled one as its `superseded_shipment_id`.

Notification obligations are dispatched, not sent automatically. A counselor, coordinator or program administrator dispatches a `PENDING` obligation by supplying the `channel` used — `EMAIL`, `SMS` or `PORTAL`. An obligation already `SENT` or `LATE` cannot be dispatched again and draws `ERR_INVALID_NOTIFICATION_STATE`. Dispatch stamps `sent_at` from the logical clock, stores the channel, and branches on a boundary: when the clock reads at or before `due_by` the obligation moves `PENDING → SENT` and `hours_late` stays 0.00; when the clock reads strictly after `due_by` it moves `PENDING → LATE` and `hours_late` is the elapsed time from `due_by` to `sent_at` expressed in hours and rounded half up to two decimal places. Dispatching exactly at `due_by` yields `SENT`; one second later yields `LATE`. Both `SENT` and `LATE` are terminal.

### 3.8. Certified Weights, Disputes, Reconciliation and Closure

The weight of record arrives from a truck scale, and recording it is a coordinator action that moves `weight_recon_status` `ESTIMATED → ACTUAL_RECORDED`. The request supplies `actual_gross_lbs` (the loaded-scale figure, greater than zero), `actual_tare_lbs` (the empty-scale figure, at least zero and strictly less than the gross figure), the `weigh_date`, and `scale_certified`, which must be true — an uncertified weight of record is refused with `ERR_UNCERTIFIED_SCALE`. The shipment's `weight_recon_status` must be `ESTIMATED`, or `ERR_INVALID_WEIGHT_RECON_STATE` applies, and its `movement_status` must be one of `SURVEYED`, `PACKED`, `PICKED_UP` or `IN_SIT` — the scale can be read at any point between survey and storage.

Recording the actual weight stores the two scale figures and the `weigh_date`, recomputes `net_actual_lbs` and `reweigh_required`, and then runs the deepest ledger cascade in the system. **First**, `billable_weight_lbs` is recomputed under the final actual variant and `billable_basis` becomes `ACTUAL`. **Second**, because the shipment's charge changed, the owning entitlement's `charged_billable_weight_lbs`, `excess_weight_lbs`, `gross_excess_cost_usd` and `excess_cost_due_usd` are recomputed. **Third**, if the recomputed `excess_cost_due_usd` now strictly exceeds 2,500.00 US dollars while the entitlement is `AUTHORIZED`, the entitlement moves `AUTHORIZED → SUSPENDED` with `suspension_reason` `EXCESS_COST_UNPAID`. **Fourth**, every sibling shipment sharing that `entitlement_id` whose `movement_status` is `AWARDED` moves `AWARDED → ON_HOLD` with `hold_reason` `ENTITLEMENT_SUSPENDED` — a heavy scale reading on one shipment can therefore freeze a member's other, untouched shipments. Recording the weight also creates one `PENDING` notification obligation of type `WEIGHT_RECON_COMPLETE`.

Members may contest the weight of record. Disputing moves `weight_recon_status` `ACTUAL_RECORDED → DISPUTED` and is available to the member (as the disputing party) and to a counselor acting on their behalf, with a `dispute_reason` in the body. Two conditions apply: the status must be `ACTUAL_RECORDED`, and the logical clock must be no later than `weigh_date` advanced by 45 days — a dispute raised beyond that six-and-a-half-week window is refused with `ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED`. A dispute forces `reweigh_required` to true and changes no ledger figure whatsoever: `DISPUTED` sits inside the inclusion set, so the disputed pounds continue to be charged while the matter is resolved.

Reweighing resolves it. A coordinator supplies a fresh `actual_gross_lbs`, `actual_tare_lbs`, `weigh_date` and `scale_certified` (again necessarily true), moving `weight_recon_status` `DISPUTED → ACTUAL_RECORDED`. The new figures **replace** the old ones, `net_actual_lbs` is recomputed, `billable_weight_lbs` is recomputed under the final actual variant, and the owning entitlement's ledger fields are recomputed — which may move the entitlement `AUTHORIZED → SUSPENDED` if the new weight pushes the amount due above the threshold, or may leave it `AUTHORIZED`. The cycle `ACTUAL_RECORDED → DISPUTED → ACTUAL_RECORDED` may repeat.

Reconciliation freezes a shipment's contribution and is a counselor or program-office action moving `weight_recon_status` `ACTUAL_RECORDED → RECONCILED`, the terminal state of the weight dimension. It may carry an optional `reconcile_note`. Three conditions apply: the weight status must be `ACTUAL_RECORDED` (else `ERR_INVALID_WEIGHT_RECON_STATE`), the shipment must already be `DELIVERED` on its movement dimension, and the owning entitlement's `excess_cost_due_usd` must be exactly zero — reconciling with money outstanding is refused with `ERR_EXCESS_COST_UNPAID`.

Reconciliation is also where a move ends. When, after this reconciliation, every shipment charging the entitlement is either `RECONCILED` or `CANCELLED`, at least one non-cancelled shipment exists, and `excess_cost_due_usd` is zero, the entitlement bubbles up `AUTHORIZED → CLOSED`. A `CLOSED` entitlement accepts no further shipments — an attempt draws `ERR_ENTITLEMENT_NOT_AUTHORIZED` — and its closure in turn bubbles the owning orders from `ISSUED` or `AMENDED` to `CLOSED`, after which no amendment is accepted and `ERR_INVALID_ORDER_STATE` is returned. `CLOSED` is terminal for both the entitlement and the orders.

### 3.9. Personally Procured Moves

A member who moves their own household submits a packet against a shipment whose `shipment_method` is `PPM`; against any other method the submission is refused with `ERR_PPM_METHOD_REQUIRED`. The packet carries a non-empty `trip_tickets` array whose entries each pair a `trip_number` (unique within the array) with a `full_lbs` figure, an `empty_lbs` figure, a `ticket_source` and a `certified` flag. Every ticket must be certified, must name a non-empty source, and must show a `full_lbs` strictly greater than its `empty_lbs`; any ticket failing that is refused with `ERR_WEIGHT_TICKET_PAIR_INCOMPLETE`, both at submission and again at approval. The packet may also carry `documented_expenses_usd` (receipted moving costs, at least zero, defaulting to 0.00), `advance_paid_usd` (an operating allowance already disbursed, at least zero, defaulting to 0.00) and an `elected_basis` of `AUTO`, `INCENTIVE_BASIS` or `ACTUAL_EXPENSE_BASIS`, defaulting to `AUTO`. A new packet is `SUBMITTED`, with `moved_weight_lbs` computed from the ticket pairs, `applied_basis` `UNDETERMINED` and every money figure at 0.00.

Approval is a counselor or program-office act moving the packet `SUBMITTED → APPROVED`, the terminal state; a packet that is not `SUBMITTED` draws `ERR_INVALID_PPM_STATE`, and the shipment must already be `DELIVERED`. The request may carry an `approval_note`. Approval stamps `approved_by_user_id` from `X-User-ID` and computes the reimbursement in five steps.

**Step one** establishes the weight. Processing the tickets in ascending `trip_number` order, each trip's net weight is its `full_lbs` less its `empty_lbs`; a net weight of zero or less is refused with `ERR_WEIGHT_TICKET_PAIR_INCOMPLETE`. `moved_weight_lbs` is the sum of those net weights.

**Step two** finds the entitlement room left for this shipment, excluding this shipment's own charge. Sum `billable_weight_lbs` over every **other** shipment of the same entitlement that is inside the inclusion set of §2.8; subtract that sum from `total_billable_cap_lbs` and floor the result at zero. `allowable_weight_lbs` is the lesser of `moved_weight_lbs` and that remaining room.

**Step three** prices the move as the government would have. `gcc_usd`, the government constructed cost, is `allowable_weight_lbs` expressed in hundredweight, multiplied by a rate made of a base of 42.75 US dollars per hundredweight plus 3.85 US dollars per hundredweight for each hundred miles of the orders' `distance_miles`, with the product rounded half up to cents. From it, `incentive_usd` is 95 percent of `gcc_usd`, rounded half up to cents. The competing expense figure is the lesser of `documented_expenses_usd` and `gcc_usd` — receipts are reimbursed up to, but never beyond, the full constructed cost.

**Step four** selects the basis. When `elected_basis` is `AUTO`, the server applies the greater-of rule: `applied_basis` becomes `INCENTIVE_BASIS` when the incentive figure is greater than or equal to the expense figure, and `ACTUAL_EXPENSE_BASIS` when the expense figure is strictly greater — a tie goes to the incentive. When the member elected a specific basis, that election is honoured as `applied_basis`. `reimbursement_usd` is the incentive figure under `INCENTIVE_BASIS` and the expense figure under `ACTUAL_EXPENSE_BASIS`, so the same packet yields a materially different payable depending on which variant applies.

**Step five** settles against the advance. `net_payable_usd` is `reimbursement_usd` less `advance_paid_usd`, rounded half up to cents and floored at zero; `debt_owed_usd` is `advance_paid_usd` less `reimbursement_usd`, likewise rounded and floored at zero — so exactly one of the two is non-zero, and their difference always equals the reimbursement less the advance. `taxable_amount_usd` is, under `INCENTIVE_BASIS`, `reimbursement_usd` less `documented_expenses_usd`, rounded half up to cents and floored at zero, because incentive payments beyond documented cost are taxable income; under `ACTUAL_EXPENSE_BASIS` it is 0.00.

Approval also lands the PPM weight on the ledger. The shipment's `billable_weight_lbs` is set to `allowable_weight_lbs`, its `billable_basis` to `ACTUAL`, and its `weight_recon_status` moves `ESTIMATED → ACTUAL_RECORDED`; the owning entitlement's `charged_billable_weight_lbs` therefore rises by the allowable weight, and its excess figures are recomputed accordingly.

### 3.10. Loss and Damage Claims, Settlement and Provider Performance

Damage is discovered at destination, so a claim can only be opened against a shipment whose `movement_status` is `DELIVERED`; anything earlier is refused with `ERR_SHIPMENT_NOT_DELIVERED`. A member or counselor opens a `LossDamageClaim` with a `claim_type` of `LOSS`, `DAMAGE` or `BOTH`, the `notice_date` on which the member notified the provider, and an `incident_description`. The notice date must fall no later than 180 days — roughly six months — after the shipment's `delivery_date`; later notice is refused with `ERR_LOSS_NOTICE_WINDOW_EXPIRED`. A new claim is `DRAFT`, with `settlement_basis` `UNDETERMINED`, `filed_date` and `filing_window_days` null, `claimed_total_usd` 0.00, `settlement_total_usd` 0.00, `item_count` 0, `info_request_count` 0 and `reviewed_by_user_id`, `settled_by_user_id` and `denial_reason` all null.

Items are added while the claim is still `DRAFT`, each item recording the `claim_id` of the claim it belongs to. Each `ClaimItem` carries an `item_description`, the `inventory_item_number` from the packing inventory, a `category` of `ELECTRONICS`, `FURNITURE`, `APPLIANCE`, `CLOTHING` or `OTHER`, a `replacement_cost_usd` greater than zero at two decimal places, an `age_years` figure between 0 and 60 given to one decimal place, and optionally `high_value_inventory_documented`, which defaults to false and records whether the item appears on the high-value inventory sheet. On creation, `depreciation_rate_pct_per_year` is set from the category — one tenth per year for `ELECTRONICS`, one twentieth for `FURNITURE`, seven hundredths for `APPLIANCE`, one fifth for `CLOTHING` and six hundredths for `OTHER` — `disposition` starts at `PENDING` with `adjudication_note` null and `item_settlement_usd` 0.00, and the parent claim's `item_count` and `claimed_total_usd` are recomputed, the latter being the sum of `replacement_cost_usd` across the claim's items.

Filing the claim moves it `DRAFT → SUBMITTED` and fixes the money rules for everything that follows; an optional `filing_note` may accompany it. The shipment must be `DELIVERED`, the claim must hold at least one item (an empty claim is refused with `ERR_CLAIM_ITEM_REQUIRED`), the notice window above must still be satisfied, and the logical clock must be no later than 730 days — two years — after the shipment's `delivery_date`, a later filing being refused with `ERR_CLAIM_FILING_WINDOW_EXPIRED`. On filing, `filed_date` is stamped from the logical clock and `filing_window_days` is set to the count of whole days between `delivery_date` and `filed_date`. From that count the `settlement_basis` follows: at most 270 days — filing within nine months of delivery, boundary inclusive — earns `FULL_REPLACEMENT_VALUE`; more than 270 days but at most 730 earns `DEPRECIATED_VALUE`. `claimed_total_usd` is recomputed, and one `PENDING` notification obligation of type `CLAIM_ACK` is created.

Adjudication is the examiner's work. Taking a claim under review moves it `SUBMITTED → UNDER_REVIEW`, may carry a `review_note`, and stamps `reviewed_by_user_id` from `X-User-ID` — the stamp that later bars this examiner from settling or denying the same claim. From `UNDER_REVIEW`, the examiner may request further information with an `info_request_note`, moving the claim `UNDER_REVIEW → INFO_REQUESTED` and incrementing `info_request_count`; the member answers with a `response_note`, moving it `INFO_REQUESTED → UNDER_REVIEW` with no counter change. That cycle is bounded at three requests: a fourth attempt, made with `info_request_count` already at 3, is refused with `ERR_CLAIM_INFO_REQUEST_LIMIT`. Individual items are decided separately: an examiner sets an item's `disposition` to `ALLOWED` or `DENIED` with an optional `adjudication_note`, and may only do so while the parent claim is `UNDER_REVIEW`.

Two disjoint outcomes leave `UNDER_REVIEW`. **Denial** moves the claim `UNDER_REVIEW → DENIED`, stores the supplied `denial_reason`, leaves `settlement_total_usd` at 0.00, and — importantly — touches no provider performance figure at all: denied claims never affect a provider's score. **Settlement** moves the claim `UNDER_REVIEW → SETTLED`, may carry a `settlement_note`, requires that no item of the claim is still `PENDING` (otherwise `ERR_CLAIM_ITEM_PENDING`), requires the acting `X-User-ID` to differ from `reviewed_by_user_id`, and stamps `settled_by_user_id`. Both `SETTLED` and `DENIED` are terminal.

Settlement values the claim item by item, and the rounding order is pinned: **round each item to cents, then sum, then apply the per-claim cap.** Processing the claim's items in ascending `created_at` order, an item whose `disposition` is `DENIED` settles at 0.00 and is skipped, though it still counts in `item_count`. For an allowed item, the effective cost starts as its `replacement_cost_usd`, but an item whose `replacement_cost_usd` is 5,000.00 US dollars or more and whose `high_value_inventory_documented` is false has its effective cost capped at 5,000.00 — undocumented high-value goods are not paid above the threshold. Under `FULL_REPLACEMENT_VALUE`, `item_settlement_usd` is that effective cost rounded half up to cents, with no reduction for age. Under `DEPRECIATED_VALUE`, a residual factor is computed as one less the item's `depreciation_rate_pct_per_year` multiplied by its `age_years`, with a floor of 0.20 so that no item ever settles below a fifth of its effective cost, and `item_settlement_usd` is the effective cost multiplied by that factor, rounded half up to cents. Identical items therefore settle strictly higher under `FULL_REPLACEMENT_VALUE` than under `DEPRECIATED_VALUE` whenever `age_years` is greater than zero. `settlement_total_usd` is the sum of the per-item settlements, rounded half up to cents, and then capped at 100,000.00 US dollars per claim.

Settlement is the trigger of the four-level performance cascade. **First**, the per-item and total settlement figures above are computed. **Second**, because money has been paid on this provider's account, the `MovingCompany` owning the claim's shipment has its `settled_claim_count` incremented, its `claim_settlement_total_usd` increased by `settlement_total_usd`, and its `performance_score` recomputed: starting from 100.00, deduct 5.00 points for each settled claim counted against the provider, deduct a further point for every 500.00 US dollars of cumulative settlement, round half up to two decimals, and floor the result at 0.00. Only `SETTLED` claims enter that computation; `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `INFO_REQUESTED` and `DENIED` claims never do. **Third**, standing is re-derived from the score immediately: below 50.00 the provider becomes `SUSPENDED`; at or above 50.00 but below 70.00 it becomes `PROBATION`; otherwise it stays `ACTIVE`. A single heavy settlement may therefore take a provider `ACTIVE → PROBATION`, or `PROBATION → SUSPENDED`, or drop it straight from `ACTIVE → SUSPENDED` in one step. **Fourth**, the provider's weekly capacity follows its standing: when the provider lands on `PROBATION`, every capacity block of that provider whose `status` is `OPEN` moves `OPEN → RESTRICTED`; when the provider lands on `SUSPENDED`, every block of that provider whose `status` is `OPEN` or `RESTRICTED` moves to `CLOSED`.

## 4. Endpoint Definitions

Operations that bring a new resource into existence return `201 Created`. Operations that modify an existing resource — including every state transition, every compensating action and the logical-clock capability — return `200 OK`. Read operations return `200 OK`. Every response, successful or not, is wrapped in the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/hhg/service-members` | Register a service member eligible for a household goods move | MoveCounselor, ProgramAdmin |
| GET | `/hhg/service-members/{id}` | Read one service member | ServiceMember, MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/service-members/{id}/orders` | List the PCS orders issued to a member | ServiceMember, MoveCounselor, ClaimsExaminer, ProgramAdmin |
| POST | `/hhg/orders` | Issue PCS orders for a member | MoveCounselor, ProgramAdmin |
| GET | `/hhg/orders/{id}` | Read one PCS order | ServiceMember, MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| POST | `/hhg/orders/{id}/amend` | Amend issued orders (dependents, report date or move type) | MoveCounselor, ProgramAdmin |
| GET | `/hhg/orders/{id}/counseling-sessions` | List counseling sessions of an order | ServiceMember, MoveCounselor, ProgramAdmin |
| GET | `/hhg/orders/{id}/entitlements` | List entitlement authorizations of an order | ServiceMember, MoveCounselor, ProgramAdmin |
| GET | `/hhg/orders/{id}/shipments` | List shipments of an order | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/counseling-sessions` | Book a counseling appointment against orders | MoveCounselor, ProgramAdmin |
| GET | `/hhg/counseling-sessions/{id}` | Read one counseling session | ServiceMember, MoveCounselor, ProgramAdmin |
| POST | `/hhg/counseling-sessions/{id}/complete` | Complete counseling and create the draft entitlement | MoveCounselor |
| GET | `/hhg/counseling-sessions/{id}/entitlements` | List entitlements created by this session | ServiceMember, MoveCounselor, ProgramAdmin |
| GET | `/hhg/entitlements/{id}` | Read one entitlement authorization with its ledger fields | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/entitlements/{id}/authorize` | Authorize the entitlement, optionally adding an administrative weight bump | MoveCounselor, ProgramAdmin |
| POST | `/hhg/entitlements/{id}/excess-cost-waivers` | Waive part or all of the excess-weight cost due | ProgramAdmin |
| POST | `/hhg/entitlements/{id}/revoke-waiver` | Revoke every excess-cost waiver, restoring the amount due | ProgramAdmin |
| POST | `/hhg/entitlements/{id}/resume` | Return a suspended entitlement to authorized and release held shipments | MoveCounselor, ProgramAdmin |
| GET | `/hhg/entitlements/{id}/shipments` | List shipments charging this entitlement | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| GET | `/hhg/entitlements/{id}/weight-ledger` | Computed read of the weight and excess-cost ledger with the rate tier applied | ServiceMember, MoveCounselor, ProgramAdmin |
| POST | `/hhg/tsps` | Onboard a transportation service provider with the markets it serves | ProgramAdmin |
| GET | `/hhg/tsps/{id}` | Read one transportation service provider | MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/tsps/{id}/capacity-blocks` | List a provider's weekly capacity blocks | MoveCounselor, TspCoordinator, ProgramAdmin |
| GET | `/hhg/tsps/{id}/shipments` | List shipments assigned to a provider | MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/capacity-blocks` | Publish a weekly capacity block for a provider and market | TspCoordinator, ProgramAdmin |
| GET | `/hhg/capacity-blocks/{id}` | Read one capacity block including both committed pools | MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/capacity-blocks/{id}/awards` | Award a shipment into this week's capacity | TspCoordinator, ProgramAdmin |
| POST | `/hhg/capacity-blocks/{id}/release-award` | Release a shipment's award, returning its pounds to the pool it consumed | TspCoordinator, ProgramAdmin |
| GET | `/hhg/capacity-blocks/{id}/shipments` | List shipments awarded to a block | MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/shipments` | Book a shipment against an authorized entitlement | MoveCounselor, ProgramAdmin |
| GET | `/hhg/shipments` | Paginated, filterable shipment list | MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/shipments/{id}` | Read one shipment with both status dimensions and every weight field | ServiceMember, MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/shipments/{id}/superseding-shipments` | List shipments that supersede this one | MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/shipments/{id}/survey` | Record the pre-move survey and set the provisional billable weight | TspCoordinator |
| POST | `/hhg/shipments/{id}/pack` | Confirm the packing date | TspCoordinator |
| POST | `/hhg/shipments/{id}/pickup` | Record pickup inside the spread window | TspCoordinator |
| POST | `/hhg/shipments/{id}/record-actual-weight` | Record the certified scale weights | TspCoordinator |
| POST | `/hhg/shipments/{id}/dispute-weight` | Dispute the weight of record inside the 45-day window | ServiceMember, MoveCounselor |
| POST | `/hhg/shipments/{id}/reweigh` | Replace the weight of record after a dispute | TspCoordinator |
| POST | `/hhg/shipments/{id}/reconcile-weight` | Freeze the shipment's weight ledger after delivery | MoveCounselor, ProgramAdmin |
| POST | `/hhg/shipments/{id}/deliver` | Record delivery at destination | TspCoordinator |
| POST | `/hhg/shipments/{id}/cancel` | Cancel a shipment before pickup | ServiceMember, MoveCounselor, ProgramAdmin |
| POST | `/hhg/shipments/{id}/pro-gear-declarations` | Declare professional gear for weight exclusion | ServiceMember, MoveCounselor |
| GET | `/hhg/shipments/{id}/pro-gear-declarations` | List a shipment's pro-gear declarations | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| GET | `/hhg/pro-gear-declarations/{id}` | Read one pro-gear declaration | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/pro-gear-declarations/{id}/verify` | Verify declared professional gear in full or in part | MoveCounselor |
| POST | `/hhg/pro-gear-declarations/{id}/reject` | Reject a pro-gear declaration for want of documentation | MoveCounselor |
| POST | `/hhg/pro-gear-declarations/{id}/resubmit` | Resubmit a rejected declaration with better documentation | ServiceMember, MoveCounselor |
| POST | `/hhg/shipments/{id}/sit-authorizations` | Request storage in transit for a picked-up shipment | TspCoordinator, MoveCounselor |
| GET | `/hhg/shipments/{id}/sit-authorizations` | List a shipment's storage authorizations | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| GET | `/hhg/sit-authorizations/{id}` | Read one storage authorization including its cost breakdown | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/sit-authorizations/{id}/authorize` | Authorize storage in transit and move the shipment into storage | MoveCounselor, ProgramAdmin |
| POST | `/hhg/sit-authorizations/{id}/extend` | Extend an authorized storage period | MoveCounselor, ProgramAdmin |
| POST | `/hhg/sit-authorizations/{id}/release` | Release goods from storage and price the stay | TspCoordinator |
| POST | `/hhg/shipments/{id}/claims` | Open a loss or damage claim on a delivered shipment | ServiceMember, MoveCounselor |
| GET | `/hhg/shipments/{id}/claims` | List a shipment's claims | ServiceMember, MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/claims/{id}` | Read one loss or damage claim | ServiceMember, MoveCounselor, ClaimsExaminer, ProgramAdmin |
| POST | `/hhg/claims/{id}/claim-items` | Add an item to a draft claim | ServiceMember, MoveCounselor |
| GET | `/hhg/claims/{id}/claim-items` | List a claim's items | ServiceMember, MoveCounselor, ClaimsExaminer, ProgramAdmin |
| GET | `/hhg/claim-items/{id}` | Read one claim item including its settlement figure | ServiceMember, MoveCounselor, ClaimsExaminer, ProgramAdmin |
| POST | `/hhg/claims/{id}/submit` | File the claim, fixing the settlement basis | ServiceMember, MoveCounselor |
| POST | `/hhg/claims/{id}/review` | Take the claim under review | ClaimsExaminer |
| POST | `/hhg/claims/{id}/request-info` | Request further information from the member | ClaimsExaminer |
| POST | `/hhg/claims/{id}/provide-info` | Answer an information request, returning the claim to review | ServiceMember, MoveCounselor |
| POST | `/hhg/claim-items/{id}/disposition` | Allow or deny an individual claim item | ClaimsExaminer |
| POST | `/hhg/claims/{id}/settle` | Settle the claim on the basis fixed at filing | ClaimsExaminer, ProgramAdmin |
| POST | `/hhg/claims/{id}/deny` | Deny the claim in full | ClaimsExaminer |
| POST | `/hhg/shipments/{id}/ppm-submissions` | Submit a personally procured move packet with certified weight tickets | ServiceMember, MoveCounselor |
| GET | `/hhg/shipments/{id}/ppm-submissions` | List a shipment's PPM submissions | ServiceMember, MoveCounselor, ProgramAdmin |
| GET | `/hhg/ppm-submissions/{id}` | Read one PPM submission with its reimbursement breakdown | ServiceMember, MoveCounselor, ProgramAdmin |
| POST | `/hhg/ppm-submissions/{id}/approve` | Approve the PPM packet and compute the reimbursement | MoveCounselor, ProgramAdmin |
| GET | `/hhg/shipments/{id}/notifications` | List a shipment's notification obligations | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| GET | `/hhg/notifications/{id}` | Read one notification obligation with its service-level deadline | ServiceMember, MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/hhg/notifications/{id}/dispatch` | Dispatch a pending notification obligation | MoveCounselor, TspCoordinator, ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ServiceMember, MoveCounselor, TspCoordinator, ClaimsExaminer, ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SERVICE_MEMBER_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_COUNSELING_SESSION_NOT_FOUND` | 404 |
| `ERR_ENTITLEMENT_NOT_FOUND` | 404 |
| `ERR_TSP_NOT_FOUND` | 404 |
| `ERR_CAPACITY_BLOCK_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_PRO_GEAR_DECLARATION_NOT_FOUND` | 404 |
| `ERR_SIT_AUTHORIZATION_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_CLAIM_ITEM_NOT_FOUND` | 404 |
| `ERR_PPM_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_WAIVER_SELF_APPROVAL` | 403 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_INVALID_COUNSELING_STATE` | 409 |
| `ERR_INVALID_ENTITLEMENT_STATE` | 409 |
| `ERR_INVALID_SHIPMENT_MOVEMENT_STATE` | 409 |
| `ERR_INVALID_WEIGHT_RECON_STATE` | 409 |
| `ERR_INVALID_PRO_GEAR_STATE` | 409 |
| `ERR_INVALID_SIT_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_INVALID_PPM_STATE` | 409 |
| `ERR_INVALID_NOTIFICATION_STATE` | 409 |
| `ERR_ENTITLEMENT_NOT_AUTHORIZED` | 409 |
| `ERR_ENTITLEMENT_SUSPENDED` | 409 |
| `ERR_SHIPMENT_NOT_DELIVERED` | 409 |
| `ERR_CAPACITY_BLOCK_NOT_ASSIGNED` | 409 |
| `ERR_STALE_ENTITLEMENT_VERSION` | 412 |
| `ERR_STALE_CAPACITY_BLOCK_VERSION` | 412 |
| `ERR_TSP_NOT_ACTIVE` | 409 |
| `ERR_MARKET_NOT_SERVED` | 409 |
| `ERR_SHIPMENT_TSP_MISMATCH` | 409 |
| `ERR_PRO_GEAR_DOCUMENTATION_REQUIRED` | 422 |
| `ERR_PRO_GEAR_CAP_EXCEEDED` | 422 |
| `ERR_UNCERTIFIED_SCALE` | 422 |
| `ERR_LOSS_NOTICE_WINDOW_EXPIRED` | 422 |
| `ERR_CLAIM_FILING_WINDOW_EXPIRED` | 422 |
| `ERR_WEIGHT_DISPUTE_WINDOW_EXPIRED` | 422 |
| `ERR_PICKUP_OUTSIDE_SPREAD` | 422 |
| `ERR_PACK_BEFORE_SPREAD` | 422 |
| `ERR_SIT_ENTRY_BEFORE_PICKUP` | 422 |
| `ERR_DELIVERY_BEFORE_PICKUP` | 422 |
| `ERR_RELEASE_BEFORE_ENTRY` | 422 |
| `ERR_SIT_PERIOD_OVERLAP` | 409 |
| `ERR_CAPACITY_BLOCK_OVERLAP` | 409 |
| `ERR_SIT_MAX_DAYS_EXCEEDED` | 422 |
| `ERR_CLAIM_ITEM_REQUIRED` | 422 |
| `ERR_CLAIM_ITEM_PENDING` | 409 |
| `ERR_SURVEY_ROOM_ESTIMATES_EMPTY` | 422 |
| `ERR_CLAIM_INFO_REQUEST_LIMIT` | 409 |
| `ERR_ORDER_AMENDMENT_LIMIT` | 409 |
| `ERR_PRO_GEAR_RESUBMISSION_LIMIT` | 409 |
| `ERR_DUPLICATE_DOD_ID` | 409 |
| `ERR_DUPLICATE_ORDER_NUMBER` | 409 |
| `ERR_DUPLICATE_ENTITLEMENT` | 409 |
| `ERR_PPM_METHOD_REQUIRED` | 422 |
| `ERR_WEIGHT_TICKET_PAIR_INCOMPLETE` | 422 |
| `ERR_CAPACITY_BLOCK_NOT_OPEN` | 409 |
| `ERR_WEIGHT_BASIS_MISSING` | 409 |
| `ERR_SHORT_NOTICE_RESERVE_PROTECTED` | 409 |
| `ERR_AWARD_NOT_FOUND` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_EXCESS_COST_UNPAID` | 409 |
| `ERR_WAIVER_EXCEEDS_DUE` | 422 |
| `ERR_NO_WAIVER_TO_REVOKE` | 409 |

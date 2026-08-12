# Senior Move Management API — Product Requirements Document

## 1. Introduction

Moving an eighty-year-old out of a four-bedroom house she has lived in for forty years is not a logistics problem with a sentimental veneer; it is a family negotiation with a truck attached. A senior move manager runs the assessment, draws the furniture placement plan for the destination suite, sorts a lifetime of possessions into keep, donate, sell and haul-away, books the crew, coordinates the junk hauler and the consignment house, and then unpacks the essentials before nightfall so the client sleeps in a made bed. Every one of those steps is watched by adult children in three time zones, at least one of whom holds power of attorney and at least one of whom will object — usually to the disposal of the dining table.

This document specifies the API behind that practice. It is a workflow-orchestration system with a pricing engine bolted to its side, and the two halves interact everywhere. Two structurally different billing pipelines — **HOURLY**, which bills measured crew-hours against role rates, and **PACKAGE**, which bills a fixed tier price with an included-hours allowance — share a single validation ladder that branches only where the pipelines genuinely differ. The sort plan has a freeze point that converts a fully reversible disposition mesh into an irreversible one. The family hold is an independent state dimension layered over the same inventory item, so an item can be simultaneously designated `SELL` and frozen by a dispute. Consignment settlement is deliberately non-monotone: proceeds credited when a lot settles are reversed when it is returned, a returned lot can still incur a disposal fee, and the reversal can push a milestone that was already `COMPLETE` back into `REOPENED`.

Three design commitments run through the whole surface and are worth stating up front. First, every mutating request walks one global, ordered sequence of gates, and the first gate that fails determines the error the caller sees — so a request that is both over capacity and in the wrong state always reports the state error, never the capacity one. Second, every derived quantity is reconciled at the moment its inputs change, not lazily at read time; a room's headroom, an engagement's keep volume, an invoice's balance are all maintained eagerly. Third, time is a server-controlled logical quantity, never the wall clock, so freeze windows, insurance expiries and service-level deadlines are exactly reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to every endpoint carries the header `X-User-Role`. Requests acting on behalf of a specific person or organisation additionally carry `X-User-ID`. A request with no `X-User-Role` header, or with an empty one, is rejected with `ERR_MISSING_AUTH_HEADER` (HTTP 401). A request whose `X-User-Role` is not one of the eight role names below is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). A request whose role is entity-backed but which carries no `X-User-ID` is rejected with `ERR_MISSING_USER_ID` (HTTP 401). A syntactically valid, authenticated request whose role does not appear in the target endpoint's authorised-role list is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The eight roles are `PLATFORM_ADMIN`, `MOVE_MANAGER`, `BILLING_ADMIN`, `CREW_LEAD`, `VENDOR`, `CLIENT`, `FAMILY_MEMBER` and `POWER_OF_ATTORNEY`.

Three of them are operator roles whose identity is opaque. When `X-User-Role` is `PLATFORM_ADMIN`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator maintains the reference data — the crew roster, the vendor directory and the logical clock — and the server never compares that identifier to any entity's `id`. When `X-User-Role` is `MOVE_MANAGER`, `X-User-ID` is likewise an opaque operator identifier for the senior move manager who owns the engagement end to end; the server may record it (for example as `created_by_role` on a ledger line, which stores the acting `X-User-Role` rather than the identifier) but does not compare it to any entity's `id`. When `X-User-Role` is `BILLING_ADMIN`, `X-User-ID` is again an opaque back-office operator identifier not tied to any persisted entity; `BILLING_ADMIN` is the only role that can move an invoice through its lifecycle.

The other five are entity-backed. When `X-User-Role` is `CREW_LEAD`, `X-User-ID` is the `id` of the acting `CrewMember`; ownership checks compare it to the crew member behind a non-terminal crew assignment on the engagement's move-day plan. When `X-User-Role` is `VENDOR`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a vendor compare that resource's vendor foreign key to `X-User-ID`. When `X-User-Role` is `CLIENT`, `X-User-ID` is the `id` of the acting `Client`; ownership checks compare the engagement's client foreign key to `X-User-ID`. When `X-User-Role` is `FAMILY_MEMBER`, `X-User-ID` is the `id` of the acting `PortalParty`; ownership checks compare a portal-seat foreign key on the subject resource to `X-User-ID`. When `X-User-Role` is `POWER_OF_ATTORNEY`, `X-User-ID` is likewise the `id` of the acting `PortalParty`, and that party must additionally hold a live delegated authority as described in §2.9. An entity-backed actor whose `X-User-ID` does not match the resource it claims to own is rejected with `ERR_ACTOR_NOT_OWNER` (HTTP 403).

Authority is delegated, not inherent: a `CLIENT` approves dispositions and placement plans directly and needs no authority record, whereas a `POWER_OF_ATTORNEY` may approve only while an authority record is `ACTIVE`, in scope, and within its monetary ceiling. A `FAMILY_MEMBER` may raise, escalate and withdraw disputes and may dispute an invoice, but may never approve a disposition.

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

### 2.3. Pagination

Every endpoint that returns an array accepts two optional query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0; there is no upper bound on it. A `limit` outside the range 1 to 100 inclusive, a non-integer `limit`, a negative `offset` or a non-integer `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

For list responses the `meta` object carries `limit`, `offset`, `total_count` and `has_more`. `total_count` is the number of records matching the supplied filters before the window is applied, and `has_more` is true when records remain beyond the current window.

The default ordering for every list endpoint is `created_at` ascending, with one deliberate exception: the milestone list is ordered by `sequence_index` ascending, so the first element of the returned array is the `ASSESSMENT` milestone and the sixth is `CLOSE_OUT`. Filters offered by a list endpoint combine conjunctively — supplying two filters returns only records matching both.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id`, a UUID string with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Almost every resource additionally carries `updated_at`, in the same format, refreshed on every mutation that touches the record, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on each mutation of that record.

`InvoiceLine` is the single exception. A ledger line is immutable once written: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`. Nothing edits or deletes a posted line except the invoice recall path, which removes the coordination-fee line it had itself appended.

Where a mutation response returns a resource, the returned representation reflects the state after every side effect and every version increment that the request caused. A client that reads an entity and immediately uses the `version` it just observed in an optimistic-concurrency field must therefore succeed.

### 2.5. The Logical Clock

The server keeps a logical clock, and every temporal decision in this system — freeze windows, milestone due dates, insurance validity, service-level deadlines, authority effective windows, consignment listing windows — is evaluated against it rather than against wall-clock time. Before any clock is set, the logical clock reads exactly `2026-05-01T00:00:00.000Z`, and it never falls back to real time. An administrative test-driving capability sets it to a supplied instant, taking a body field `to_iso8601` and answering with an object carrying `current_utc`. Only `PLATFORM_ADMIN` and `MOVE_MANAGER` may drive the clock.

Timestamps that the server stamps from the logical clock are rendered in the same ISO 8601 UTC form with three fractional digits as any other timestamp; an instant supplied by a client and later echoed back is the same instant, not a re-derived wall-clock value.

### 2.6. The Twelve Ordered Write Gates

Every mutating endpoint — that is, every non-GET endpoint except `POST /_clock/set_current_utc`, `POST /clients`, `POST /crew-members` and `POST /vendors`, which have no engagement context — passes through twelve gates in this exact order, and the first gate that fails determines the returned `error_id`. Gate ordering is normative. Read endpoints pass gates 1 and 2 only: a GET authenticates, checks the role, validates its pagination parameters and returns the gate-2 404 for an unresolvable id, but never evaluates gates 3 through 12.

1. **Envelope, authentication and body shape.** Authentication headers present, `X-User-Role` a declared role, `X-User-ID` present when the role is entity-backed, the role permitted for the endpoint, then request-body shape and enum membership. Ladder rungs 1 through 7.
2. **Path and foreign-key existence.** Every id in the path resolves, validated left to right, and then every foreign key in the body resolves, in the declared rung order. Ladder rungs 8 through 21.
3. **Engagement lifecycle.** The owning engagement's `status` must not be `CLOSED` or `CANCELLED`; `ON_HOLD` blocks every mutation except resuming and cancelling the engagement. Ladder rungs 22 through 24.
4. **Actor authority.** Entity-backed ownership, then party-to-engagement membership, then the delegated-authority checks: `ACTIVE` status, scope, high-value scope escalation, monetary ceiling. Ladder rungs 25 through 30.
5. **Timeline phase.** The engagement's derived `phase` must permit the operation; a milestone whose predecessor is not `COMPLETE` cannot be completed, and one with a `COMPLETE` successor cannot be reopened. Ladder rungs 31 through 34.
6. **Move-day freeze.** Once the logical clock reaches the move-day plan's `freeze_at_utc`, the crew roster, the inventory dispositions and the sort plan are locked; only freezing, starting, completing, rescheduling and crew check-in, check-out and no-show remain writable. Ladder rungs 35 through 38.
7. **Disposition lock and family hold.** An item whose `disposition_locked` is true cannot be re-designated; an item with an open dispute cannot be re-designated, appraised, staged or consigned; an item already in a lot cannot leave `SELL`. Ladder rungs 39 through 42.
8. **Vendor eligibility.** The `service_kind` must match the `vendor_type`, the vendor's certificate of insurance must not expire before the service date, and the vendor's per-day capacity must not be exceeded. Ladder rungs 43 through 45.
9. **Billing finalisation.** Once the engagement's invoice reaches `FINALIZED`, no endpoint may add or reverse an invoice line, and no consignment settlement, disposal fee or vendor payout may post. Ladder rungs 46 and 47.
10. **State-machine preconditions.** The target entity's own originating state, its transition preconditions, and its capped-retry counters. Ladder rungs 48 through 63.
11. **Optimistic concurrency.** The supplied expected parent version must equal the parent's current `version`. Ladder rungs 64 through 66.
12. **Business capacity and arithmetic.** Pipeline consistency, space-fit feasibility, consignment minimums, crew minimums and monetary bounds. These run last, which is why a request that is both over capacity and in the wrong state always reports the state error.

### 2.7. The Global Validation Ladder

There is exactly one priority ladder in this system, seventy-three rungs long, and every mutating endpoint walks it from rung 1 upward and returns the error of the **first** rung it fails. Rungs that apply to only one billing pipeline say so; the ladder itself is shared. The rung numbers map onto the gates of §2.6.

**Gate 1 — envelope, authentication and body shape.**

1. `X-User-Role` is present and non-empty. Otherwise `ERR_MISSING_AUTH_HEADER`, HTTP 401. Applies to every endpoint.
2. `X-User-Role` is one of the eight declared roles. Otherwise `ERR_UNKNOWN_ROLE`, HTTP 401. Applies to every endpoint.
3. `X-User-ID` is present whenever the acting role is entity-backed — that is `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `CREW_LEAD` or `VENDOR`. Otherwise `ERR_MISSING_USER_ID`, HTTP 401. Applies to every endpoint.
4. The acting role appears in the endpoint's declared role list. Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403. Applies to every endpoint.
5. Every required input field of the endpoint is present and of its declared type, and the numeric fields the domain requires to be positive are greater than zero: `quoted_cents`, `list_price_cents`, `gross_sale_price_cents`, `amount_cents` on a charge line, `truck_capacity_cft`, `truck_count`, `footprint_linear_inches`, `volume_cft`, `nominal_linear_inches` and `nominal_volume_cft`. Otherwise `ERR_VALIDATION`, HTTP 400. Applies to every endpoint.
6. Every enum-typed input field carries a declared member of that enum. This applies to `billing_mode`, `home_tier`, `package_tier`, `party_type`, `authority_scope`, `unit_type`, `room_type`, `category`, `appraisal_source`, `disposition`, `target_handling_state`, `entry_kind`, `crew_role`, `vendor_type`, `service_kind`, `line_type`, `priority`, `severity`, `resolution` and `milestone_key`, and to no other field. Otherwise `ERR_INVALID_ENUM`, HTTP 400. No other field routes to this error.
7. On list endpoints, `limit` is an integer from 1 to 100 inclusive and `offset` is an integer greater than or equal to zero. Otherwise `ERR_VALIDATION`, HTTP 400. Applies to every GET endpoint returning an array.

**Gate 2 — existence, path ids first and then body foreign keys.**

8. The engagement id in the path, or `engagement_id` in the body, resolves to an engagement. Otherwise `ERR_ENGAGEMENT_NOT_FOUND`, HTTP 404. Applies to every endpoint carrying an engagement id.
9. `client_id` in the body resolves to a client. Otherwise `ERR_CLIENT_NOT_FOUND`, HTTP 404. Applies to `POST /engagements`, `POST /portal-parties` and `GET /clients/{id}`.
10. Every party id field in path or body resolves to a portal party: `holder_party_id`, `approved_by_party_id`, `raised_by_party_id`, `resolved_by_party_id`, `signed_off_by_party_id`, `completed_by_party_id` and `acting_party_id`. Otherwise `ERR_PARTY_NOT_FOUND`, HTTP 404. Applies to every endpoint carrying a party id.
11. The authority record id in the path resolves. Otherwise `ERR_AUTHORITY_NOT_FOUND`, HTTP 404. Applies to the `/authority-records/{id}` endpoints.
12. The residence id in the path, or `destination_residence_id` in the body, resolves. Otherwise `ERR_RESIDENCE_NOT_FOUND`, HTTP 404. Applies to the `/destination-residences/{id}` endpoints and `POST /destination-rooms`.
13. The room id in the path, or `assigned_room_id` in the body, resolves. Otherwise `ERR_ROOM_NOT_FOUND`, HTTP 404. Applies to the `/destination-rooms/{id}` endpoints and `POST /inventory-items/{id}/designate`.
14. The inventory item id in the path, `inventory_item_id` in the body, or every member of `item_ids`, resolves. Otherwise `ERR_ITEM_NOT_FOUND`, HTTP 404. Applies to the `/inventory-items/{id}` endpoints, `POST /family-holds` and `POST /consignment-lots`.
15. The family hold id in the path resolves. Otherwise `ERR_HOLD_NOT_FOUND`, HTTP 404. Applies to the `/family-holds/{id}` endpoints.
16. The sort plan or move-day plan id in the path, or `move_day_plan_id` in the body, resolves. Otherwise `ERR_PLAN_NOT_FOUND`, HTTP 404. Applies to the `/sort-plans/{id}` and `/move-day-plans/{id}` endpoints and `POST /crew-assignments`.
17. `crew_member_id`, `crew_assignment_id`, `replaces_assignment_id` and the crew or time-entry id in the path all resolve. Otherwise `ERR_CREW_RECORD_NOT_FOUND`, HTTP 404. Applies to the `/crew-members/{id}`, `/crew-assignments/{id}` and `/time-entries/{id}` endpoints, `POST /crew-assignments` and `POST /time-entries`.
18. `vendor_id` in the body and the vendor or vendor-assignment id in the path resolve. Otherwise `ERR_VENDOR_RECORD_NOT_FOUND`, HTTP 404. Applies to the `/vendors/{id}` and `/vendor-assignments/{id}` endpoints, `POST /vendor-assignments` and `POST /consignment-lots`.
19. The consignment lot id in the path, or `source_consignment_lot_id` in the body, resolves. Otherwise `ERR_LOT_NOT_FOUND`, HTTP 404. Applies to the `/consignment-lots/{id}` endpoints and `POST /invoice-lines`.
20. The invoice or invoice-line id in the path, or `invoice_id` in the body, resolves. Otherwise `ERR_INVOICE_NOT_FOUND`, HTTP 404. Applies to the `/invoices/{id}` and `/invoice-lines/{id}` endpoints and `POST /invoice-lines`.
21. The milestone, unpack-session or punch-list id in the path, or `unpack_session_id` in the body, resolves. Otherwise `ERR_TIMELINE_RECORD_NOT_FOUND`, HTTP 404. Applies to the `/milestones/{id}`, `/unpack-sessions/{id}` and `/punch-list-items/{id}` endpoints, `POST /punch-list-items` and `POST /inventory-items/{id}/advance-handling`.

**Gate 3 — engagement lifecycle.**

22. The owning engagement's `status` is not `CLOSED`. Otherwise `ERR_ENGAGEMENT_CLOSED`, HTTP 409. Applies to every mutating endpoint under an engagement.
23. The owning engagement's `status` is not `CANCELLED`. Otherwise `ERR_ENGAGEMENT_CANCELLED`, HTTP 409. Applies to every mutating endpoint under an engagement.
24. The owning engagement's `status` is not `ON_HOLD`, except for `POST /engagements/{id}/resume` and `POST /engagements/{id}/cancel`. Otherwise `ERR_ENGAGEMENT_ON_HOLD`, HTTP 409. Applies to every mutating endpoint under an engagement other than those two.

**Gate 4 — actor authority.**

25. Entity-backed ownership holds: a `CLIENT` actor's `X-User-ID` equals the engagement's client id, a `FAMILY_MEMBER` or `POWER_OF_ATTORNEY` actor's `X-User-ID` equals the id of a portal party on the engagement, a `VENDOR` actor's `X-User-ID` equals the vendor id on the vendor assignment or on the consignment lot, and a `CREW_LEAD` actor's `X-User-ID` equals the id of a crew member holding a non-terminal crew assignment on the engagement's move-day plan. Otherwise `ERR_ACTOR_NOT_OWNER`, HTTP 403. Applies to every endpoint whose role list contains an entity-backed role.
26. Every supplied party id belongs to the same engagement as the subject resource. Otherwise `ERR_PARTY_ENGAGEMENT_MISMATCH`, HTTP 422. Applies to every endpoint carrying a party id.
27. A `POWER_OF_ATTORNEY` actor holds at least one authority record whose `holder_party_id` is the acting party and whose `status` is `ACTIVE`. Otherwise `ERR_NO_ACTIVE_AUTHORITY`, HTTP 403. Applies to seven endpoints: `POST /sort-plans/{id}/approve`, `POST /sort-plans/{id}/reject`, `POST /inventory-items/{id}/designate`, `POST /family-holds/{id}/resolve`, `POST /destination-residences/{id}/approve-placement`, `POST /vendor-assignments/{id}/sign-off` and `POST /invoices/{id}/dispute`.
28. That active record's `authority_scope` covers the operation family: `FULL` or `DISPOSITION_ONLY` for disposition, sort-plan and placement approvals, `FULL` or `BILLING_ONLY` for invoice disputes and vendor sign-off. Otherwise `ERR_AUTHORITY_SCOPE_INSUFFICIENT`, HTTP 403. Applies to the same seven endpoints as rung 27.
29. When the subject item's `appraised_value_cents` is at or above the high-value threshold of 250000 cents, the acting `authority_scope` must be exactly `FULL`; `DISPOSITION_ONLY` is not enough. Otherwise `ERR_HIGH_VALUE_AUTHORITY_REQUIRED`, HTTP 403. Applies to `POST /inventory-items/{id}/designate` and `POST /family-holds/{id}/resolve`.
30. The acting party's `active_authority_ceiling_cents` is greater than or equal to the subject value, which is the item's `appraised_value_cents` for a single-item approval and the maximum `appraised_value_cents` among the engagement's non-`KEEP` items for a sort-plan approval. The boundary is inclusive: a ceiling exactly equal to the subject value permits the approval. Otherwise `ERR_AUTHORITY_CEILING_EXCEEDED`, HTTP 403. Applies to the same seven endpoints as rung 27.

**Gate 5 — timeline phase.**

31. The engagement's `phase` permits the operation: cataloguing an item and designating one require phase `ASSESSMENT` or `SORT_PLAN`; move-day plan creation requires phase `PACK` or `MOVE_DAY`; unpack-session and punch-list creation require phase `SETTLE_IN` or `CLOSE_OUT`. Otherwise `ERR_PHASE_NOT_PERMITTED`, HTTP 409. Applies to `POST /inventory-items`, `POST /inventory-items/{id}/designate`, `POST /move-day-plans`, `POST /unpack-sessions` and `POST /punch-list-items`.
32. A milestone can be completed only when the milestone whose `sequence_index` is one lower on the same engagement is `COMPLETE`. Otherwise `ERR_PREDECESSOR_MILESTONE_INCOMPLETE`, HTTP 409. Applies to `POST /milestones/{id}/complete`.
33. A milestone can be reopened only when no milestone of the same engagement with a higher `sequence_index` is `COMPLETE`. Otherwise `ERR_SUCCESSOR_MILESTONE_COMPLETE`, HTTP 409. Applies to `POST /milestones/{id}/reopen`.
34. Close-out requires the `CLOSE_OUT` milestone to be `COMPLETE`, no punch-list item in status `OPEN` or `REOPENED`, and `billing_hold` false on the engagement. Otherwise `ERR_CLOSE_OUT_BLOCKED`, HTTP 409. Applies to `POST /engagements/{id}/close-out`.

**Gate 6 — the move-day freeze window.**

35. Once the logical clock is at or after the move-day plan's `freeze_at_utc`, the crew roster is locked: no crew assignment may be created, confirmed or re-crewed. Otherwise `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409. Applies to `POST /crew-assignments`, `POST /crew-assignments/{id}/confirm` and `POST /move-day-plans/{id}/recrew`.
36. Once the logical clock is at or after that same instant, no inventory item may be designated or appraised. Otherwise `ERR_FREEZE_WINDOW_ENTERED`, HTTP 409. Applies to `POST /inventory-items/{id}/designate` and `POST /inventory-items/{id}/appraise`.
37. A sort plan in status `FROZEN` can never be reopened, regardless of its `reopen_count`. Otherwise `ERR_SORT_PLAN_FROZEN`, HTTP 409. Applies to `POST /sort-plans/{id}/reopen`.
38. Freezing the move-day plan requires the logical clock to be at or after `freeze_at_utc`; the boundary instant itself is inside the window. Otherwise `ERR_FREEZE_WINDOW_NOT_ENTERED`, HTTP 409. Applies to `POST /move-day-plans/{id}/freeze`.

**Gate 7 — disposition lock and family hold.**

39. The item's `disposition_locked` is false. Otherwise `ERR_DISPOSITION_LOCKED`, HTTP 409. Applies to `POST /inventory-items/{id}/designate`.
40. The item's `hold_state` is `NONE`, that is no dispute on the item is `OPEN` or `ESCALATED`. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409. Applies to `POST /inventory-items/{id}/designate`.
41. The item's `hold_state` is `NONE` for appraisal, for staging and for consignment membership. Otherwise `ERR_ITEM_UNDER_FAMILY_HOLD`, HTTP 409. Applies to `POST /inventory-items/{id}/appraise`, `POST /inventory-items/{id}/advance-handling` when the target is `STAGED_FOR_PICKUP`, and `POST /consignment-lots`.
42. An item whose `consignment_lot_id` is not null cannot be designated to anything other than `SELL`. Otherwise `ERR_ITEM_ALREADY_CONSIGNED`, HTTP 409. Applies to `POST /inventory-items/{id}/designate`.

**Gate 8 — vendor eligibility.**

43. `service_kind` matches the vendor's `vendor_type` under the pinned map: `HAUL_AWAY` to `JUNK_HAUL`, `CONSIGNMENT_PICKUP` to `CONSIGNMENT`, `APPRAISAL` to `APPRAISAL`, `CLEANING` to `CLEANING`, `SHREDDING` to `SHREDDING`. Otherwise `ERR_VENDOR_TYPE_MISMATCH`, HTTP 422. Applies to `POST /vendor-assignments` and `POST /consignment-lots`.
44. The vendor's `coi_expires_on` is not earlier than the assignment's `service_date`; a certificate expiring exactly on the service date is valid. Otherwise `ERR_VENDOR_COI_EXPIRED`, HTTP 422. Applies to `POST /vendor-assignments/{id}/schedule`.
45. The vendor's count of assignments on that same `service_date` whose status is `SCHEDULED`, `COI_BLOCKED`, `PERFORMED`, `SIGNED_OFF` or `PAID` is strictly less than its `daily_capacity`. Otherwise `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`, HTTP 409. Applies to `POST /vendor-assignments/{id}/schedule`.

**Gate 9 — billing finalisation.**

46. The engagement's invoice is not `FINALIZED` when a ledger line would be appended. Otherwise `ERR_INVOICE_FINALIZED`, HTTP 409. Applies to `POST /invoice-lines`, `POST /invoices/{id}/record-payment`, `POST /invoices/{id}/dispute` and `POST /invoices/{id}/recall`.
47. The engagement's invoice is not `FINALIZED` when a consignment settlement, reversal, disposal fee or vendor payout would post. Otherwise `ERR_BILLING_CLOSED`, HTTP 409. Applies to `POST /consignment-lots/{id}/settle`, `POST /consignment-lots/{id}/return-to-client`, `POST /consignment-lots/{id}/haul-away`, `POST /vendor-assignments/{id}/pay` and `POST /vendor-assignments/{id}/perform`.

**Gate 10 — state-machine preconditions and capped retries.**

48. The subject entity's current state is in the triggered transition's declared originating set. Otherwise `ERR_INVALID_STATE`, HTTP 409. Applies to every action endpoint that drives a state machine.
49. The subject entity is not already in one of its machine's terminal states. Otherwise `ERR_ALREADY_TERMINAL`, HTTP 409. Applies to every action endpoint that drives a state machine.
50. `ended_at_utc` is strictly after `started_at_utc` on a time entry, and the check-out `at_utc` is strictly after `checked_in_at_utc`. Otherwise `ERR_INVALID_TIME_RANGE`, HTTP 422. Applies to `POST /time-entries` and `POST /crew-assignments/{id}/check-out`.
51. `gross_sale_price_cents` is greater than zero and the lot has at least one member item. Otherwise `ERR_INVALID_SALE_PRICE`, HTTP 422. Applies to `POST /consignment-lots/{id}/record-sale`.
52. At submit time no inventory item of the engagement is `UNDECIDED`; at approve time the plan's `undecided_count_at_submit` is zero. Otherwise `ERR_UNDECIDED_ITEMS_REMAIN`, HTTP 422. Applies to `POST /sort-plans/{id}/submit` and `POST /sort-plans/{id}/approve`.
53. The engagement has at least one inventory item before a sort plan may be submitted. Otherwise `ERR_NO_INVENTORY`, HTTP 422. Applies to `POST /sort-plans/{id}/submit`.
54. A lot that has already been credited cannot be settled a second time. Otherwise `ERR_LOT_ALREADY_CREDITED`, HTTP 409. Applies to `POST /consignment-lots/{id}/settle`.
55. A lot may be declared unsold only once the logical clock date is at least thirty days after `listed_on`. Otherwise `ERR_UNSOLD_WINDOW_NOT_ELAPSED`, HTTP 409. Applies to `POST /consignment-lots/{id}/declare-unsold`.
56. A `STANDARD` unpack session may start only when every `ESSENTIALS` session of the same engagement created earlier is `COMPLETED`. Otherwise `ERR_ESSENTIALS_SESSION_PENDING`, HTTP 409. Applies to `POST /unpack-sessions/{id}/start`.
57. An authority record's `effective_to_utc` is strictly after its `effective_from_utc` at creation; activation requires the clock to be at or after `effective_from_utc` and strictly before `effective_to_utc`; reinstatement requires the clock to be strictly before `effective_to_utc`. Otherwise `ERR_AUTHORITY_WINDOW_INVALID`, HTTP 409. Applies to `POST /authority-records`, `POST /authority-records/{id}/activate` and `POST /authority-records/{id}/reinstate`.
58. The sort plan's `reopen_count` is strictly less than 2. Otherwise `ERR_SORT_PLAN_REOPEN_LIMIT`, HTTP 409. Applies to `POST /sort-plans/{id}/reopen`.
59. The move-day plan's `reschedule_count` is strictly less than 1, and `new_start_utc` is strictly after the current logical clock. Otherwise `ERR_RESCHEDULE_LIMIT`, HTTP 409. Applies to `POST /move-day-plans/{id}/reschedule`.
60. The lot's `markdown_round` is strictly less than 2. Otherwise `ERR_MARKDOWN_ROUNDS_EXHAUSTED`, HTTP 409. Applies to `POST /consignment-lots/{id}/mark-down`.
61. The milestone's `reopen_count` is below 2, the unpack session's `reopen_count` is below 2, and the punch-list item's `reopen_count` is below 3. Otherwise `ERR_REOPEN_LIMIT`, HTTP 409. Applies to `POST /milestones/{id}/reopen` and `POST /punch-list-items/{id}/reopen`. This rung names three counters while guarding two endpoints; where a punch-list reopen would cascade into an unpack session that has itself exhausted its reopen budget while the punch item still has budget of its own, this specification does not determine whether the rung rejects the request.
62. The invoice's `recall_count` is below 2 and its `dispute_count` is below 2. Otherwise `ERR_INVOICE_ACTION_LIMIT`, HTTP 409. Applies to `POST /invoices/{id}/recall` and `POST /invoices/{id}/dispute`.
63. A family hold's `escalation_count` and `remand_count` are each strictly below 2, and an authority record's `suspend_count` is strictly below 2. Otherwise `ERR_HOLD_ESCALATION_LIMIT`, HTTP 409. Applies to `POST /family-holds/{id}/escalate`, `POST /family-holds/{id}/remand` and `POST /authority-records/{id}/suspend`.

**Gate 11 — optimistic concurrency.**

64. `expected_engagement_version` equals the engagement's `version`. Otherwise `ERR_STALE_ENGAGEMENT_VERSION`, HTTP 412. Applies to `POST /sort-plans`.
65. `expected_move_day_plan_version` equals the move-day plan's `version`. Otherwise `ERR_STALE_MOVE_DAY_PLAN_VERSION`, HTTP 412. Applies to `POST /crew-assignments`.
66. `expected_invoice_version` equals the invoice's `version`. Otherwise `ERR_STALE_INVOICE_VERSION`, HTTP 412. Applies to `POST /invoice-lines`.

**Gate 12 — business capacity and arithmetic.**

67. `package_tier` is present and non-null when `billing_mode` is `PACKAGE`, and absent or null when `billing_mode` is `HOURLY`. This is the single rung at which the two pipelines diverge at creation time. Otherwise `ERR_PACKAGE_TIER_REQUIRED`, HTTP 422. Applies to `POST /engagements` and `PATCH /engagements/{id}`.
68. The target room's prospective `KEEP` linear load, including the item being designated, is less than or equal to its `effective_capacity_linear_inches`. The boundary is inclusive. Otherwise `ERR_ROOM_CAPACITY_EXCEEDED`, HTTP 422. Applies to `POST /inventory-items/{id}/designate` with disposition `KEEP`.
69. The target room's prospective `KEEP` volume load is less than or equal to its `nominal_volume_cft` multiplied by the room volume safety factor of 0.90. Evaluated only after rung 68 has passed. Otherwise `ERR_ROOM_VOLUME_EXCEEDED`, HTTP 422. Applies to `POST /inventory-items/{id}/designate` with disposition `KEEP`.
70. An item designated `SELL` has `appraised_value_cents` greater than or equal to 15000 cents. The boundary is inclusive. Otherwise `ERR_ITEM_BELOW_CONSIGN_MINIMUM`, HTTP 422. Applies to `POST /inventory-items/{id}/designate` with disposition `SELL`.
71. The move-day plan's `crew_confirmed_count` is greater than or equal to its `crew_min_required` at start. Otherwise `ERR_CREW_MINIMUM_NOT_MET`, HTTP 422. Applies to `POST /move-day-plans/{id}/start`.
72. At least one of the plan's non-terminal assignments belongs to a crew member whose `crew_role` is `LEAD`, at start. Otherwise `ERR_CREW_LEAD_REQUIRED`, HTTP 422. Applies to `POST /move-day-plans/{id}/start`.
73. The invoice's `balance_due_cents` is less than or equal to zero at finalisation. Otherwise `ERR_BALANCE_OUTSTANDING`, HTTP 409. Applies to `POST /invoices/{id}/finalize`.

### 2.8. Precision, Rounding and Monetary Discipline

All money is carried as integer cents. All rounding, everywhere in this system, is round-half-up. Where a formula produces several monetary components, the specification always states whether the components are rounded individually and then combined, or combined and then rounded once; the two orders give different cents on many inputs and the stated order is normative.

Hours are carried to two decimal places except for the raw length of a single time interval, which is held to four decimal places and truncated rather than rounded. Room dimensions, loads, headroom and volumes are carried to two decimal places. Trip counts and crew counts are integers. Dates that are calendar dates rather than instants — a certificate expiry, a service date, a listing date, a milestone due date, a payment date — are carried as `YYYY-MM-DD` strings and compared as dates, not as instants.

### 2.9. Delegated Authority as a Cross-Cutting Constraint

A `POWER_OF_ATTORNEY` never acts on inherent standing. Every approval that role performs is checked against the authority records it holds: at least one must be `ACTIVE`, its `authority_scope` must cover the operation family, and — for a single-item approval — its `approval_ceiling_cents` must reach the item's `appraised_value_cents`. The subject value for a sort-plan approval is not one item but the largest `appraised_value_cents` among the engagement's items whose disposition is anything other than `KEEP`, so a single valuable heirloom heading for consignment can block approval of the whole plan. Where several active records exist, the highest `approval_ceiling_cents` among them is the one used; `active_authority_ceiling_cents` on the portal seat is exactly that maximum, and reads 0 when no record of that seat is `ACTIVE`. Items valued at or above 250000 cents demand a scope of exactly `FULL`, so a `DISPOSITION_ONLY` delegate with a generous ceiling still cannot move the piano.

### 2.10. Optimistic Concurrency on Parent Versions

Three write endpoints supersede or materially reshape state their caller must have observed first, and each demands the parent's version as a non-optional body field.

Creating a sort plan legitimately supersedes the engagement's prior `DRAFT` or `REJECTED` plan, so a create whose view of the engagement is stale must be rejected rather than silently replacing a plan the caller never saw. `POST /sort-plans` therefore requires `expected_engagement_version` carrying the client's last observed `version` of the target `Engagement`. If it does not equal the engagement's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).

Creating a crew assignment can supersede a `NO_SHOW` slot and therefore changes the plan's `crew_confirmed_count` and possibly its status. `POST /crew-assignments` requires `expected_move_day_plan_version` carrying the client's last observed `version` of the target `MoveDayPlan`; a value that does not equal the plan's current `version` is rejected with `ERR_STALE_MOVE_DAY_PLAN_VERSION` (HTTP 412).

A manual adjustment line is written against a specific observed ledger state, and settlement, reversal, vendor pass-through and labour cascades all append lines and advance `Invoice.version`. `POST /invoice-lines` requires `expected_invoice_version` carrying the client's last observed `version` of the target `Invoice`; a value that does not equal the invoice's current `version` is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412).

No other endpoint takes a version field, and none may be rejected for a version mismatch.

### 2.11. Conservation Invariants

Four quantities in this system must survive a forward action followed by its compensating action completely unchanged. They are stated here because they are the sharpest statements of correctness the domain has.

**Consignment credit conservation.** An invoice's `credits_cents` always equals the sum of `amount_cents` over its lines whose `line_type` is `CONSIGNMENT_CREDIT` or `CONSIGNMENT_REVERSAL`. For every lot that has been both credited and reversed, the negative credit and the positive reversal sum to exactly zero. Settling a lot and then returning it to the client must therefore leave `credits_cents` at exactly its pre-settle value and `total_cents` at exactly its pre-settle value, with two ledger lines remaining on the invoice. Drift here means the reversal recomputed the net proceeds instead of mirroring the amount actually credited.

**Vendor payout conservation.** For every vendor assignment in status `PERFORMED`, `SIGNED_OFF` or `PAID`, `paid_cents` plus the outstanding holdback — that is `holdback_cents` when `holdback_released` is false, and zero once it is true — always equals `quoted_cents`. Sign-off moves money from the holdback bucket to the paid bucket; it never creates or destroys any.

**Inventory volume conservation.** An engagement's `total_inventory_volume_cft` always equals the sum of `volume_cft` over every one of its items regardless of disposition, and no designation ever changes it. `keep_volume_cft` plus `haul_volume_cft` is always less than or equal to `total_inventory_volume_cft`. Re-designating an item moves volume between the keep and haul buckets; a designation round trip must return both buckets to their exact pre-trip values.

**Labour ledger conservation.** An engagement's `billing_hours_total` always equals the sum of `applied_hours` over the crew assignments of its move-day plan whose status is `COMPLETED`, and every assignment's `billing_hours` is recomputed only from its own time entries whose `voided` is false. Adding a time entry and then voiding it must return the assignment's `billing_hours`, the assignment's `labor_cents` and the engagement's `billing_hours_total` to their exact pre-add values. Because the billing view rounds the sum rather than the parts, an implementation that subtracts a rounded part will drift here.

### 2.12. Derived Fields, Cascades and Nested Path Resolution

Derived fields are reconciled eagerly. When an item's disposition changes, the affected rooms' loads and headroom, and the engagement's keep and haul volumes, are recomputed inside the same request. When a crew assignment's hours change, the assignment's money and the engagement's labour rollups are recomputed inside the same request. When a ledger line is appended, the invoice's aggregates are recomputed inside the same request. A read never triggers a recomputation that a write should already have performed, with the single exception of the engagement summary, which is defined as a computed projection.

Cascades propagate across entities and the specification states each hop explicitly. A cascade performed by the system is not a user request and is therefore not itself subject to the ladder: this is why hauling a lot away can force its member items to `HAUL_AWAY` even when their `disposition_locked` is true. Where a cascade increments a parent's `version`, that increment is stated at the transition that causes it.

Path parameters are resolved strictly left to right. For a nested path, the outer id is resolved and its 404 returned before the inner id is examined, and only once every path id resolves are body foreign keys checked in the rung order of gate 2. A resource whose parent id in the path does not own it is treated as unresolvable at the level where the mismatch appears.

## 3. Business Logic & Workflows

### 3.1. Opening an Engagement: the Client, the Ledger and the Timeline Skeleton

A senior move manager begins by registering the client. A client record carries a `full_name`, a `phone`, and optionally an `email`, which is null when not supplied. It also carries `engagement_count`, a computed tally of every engagement row pointing at that client regardless of status, which begins at 0 and rises by 1 each time an engagement is opened for that client.

Opening the engagement itself is the single most consequential write in the system, because it lays down the timeline, the ledger and the pricing pipeline in one stroke. The move manager supplies the `client_id`, the `billing_mode`, the `home_tier` describing the origin residence, the `scheduled_move_start_utc`, the one-way `mileage_miles` between origin and destination, the `origin_stairs_flights` count, the `origin_long_carry_feet` distance from the origin door to where the truck can park, and — only under the package pipeline — a `package_tier`. The `billing_mode` is either `HOURLY` or `PACKAGE`. Both `home_tier` and `package_tier` are drawn from `STUDIO`, `ONE_BED`, `TWO_BED` and `HOUSE`, but they are independent choices: the home tier describes the house being emptied and drives crew minimums and the volume heuristic, while the package tier is the product the family bought. Supplying a package tier under the hourly pipeline, or omitting it under the package pipeline, is rejected with `ERR_PACKAGE_TIER_REQUIRED`.

Six things happen on that create. Six milestone rows are laid down with `sequence_index` 1 through 6 and `milestone_key` values `ASSESSMENT`, `SORT_PLAN`, `PACK`, `MOVE_DAY`, `SETTLE_IN` and `CLOSE_OUT` in that order, each with its own `due_on` date. The `ASSESSMENT` milestone is set `IN_PROGRESS`, so the engagement's derived `phase` reads `ASSESSMENT` from the first moment. Exactly one invoice is created for the engagement, in status `DRAFT`, and there is never a second one. Under the package pipeline a `PACKAGE_BASE` ledger line is appended immediately, priced from the package tier alone: 185000 cents for `STUDIO`, 265000 for `ONE_BED`, 395000 for `TWO_BED` and 620000 for `HOUSE`. The engagement's `move_freeze_at_utc` is computed as its `scheduled_move_start_utc` less seventy-two hours. And the client's `engagement_count` rises by one.

Milestone due dates are projections off the move date. Each key has a fixed day offset applied to the calendar date of `scheduled_move_start_utc` in UTC: assessment is due thirty-five days before the move, the sort plan twenty-one days before, packing three days before, move day on the day itself, settle-in seven days after, and close-out twenty-one days after. When the move manager later adjusts the engagement — the adjustable inputs are `scheduled_move_start_utc`, `mileage_miles`, `origin_stairs_flights`, `origin_long_carry_feet` and `package_tier` — every milestone's `due_on` is recomputed from the new move date, `move_freeze_at_utc` is recomputed, and the engagement's `version` rises by one.

The engagement's `status` is its lifecycle axis and starts at `ACTIVE`. Placing it `ON_HOLD` requires a `reason`, which is stored as `hold_reason`; `hold_count` rises by one and never falls, recording how often the engagement has been paused, and `version` rises by one. Resuming clears `hold_reason` back to null and raises `version` by one. The cycle between `ACTIVE` and `ON_HOLD` is unbounded. While the engagement is `ON_HOLD`, every mutating endpoint in its subtree is refused with `ERR_ENGAGEMENT_ON_HOLD` except resuming and cancelling.

Cancellation is permitted from `ACTIVE` — but only when the engagement's move-day plan, if one exists, is not `IN_PROGRESS` — and from `ON_HOLD`, where no such precondition applies. It records `cancel_reason` and runs the same cascade in both cases: every vendor assignment of the engagement in status `REQUESTED`, `ACCEPTED`, `SCHEDULED` or `COI_BLOCKED` moves to `CANCELLED`, and every unpack session still `SCHEDULED` moves to `COMPLETED` with its `items_unpacked_count` unchanged. The engagement's `version` rises by one. `CLOSED` and `CANCELLED` are both terminal.

Closing out is the other exit and is discussed in full in §3.11; it requires the `CLOSE_OUT` milestone `COMPLETE`, no punch-list item still `OPEN` or `REOPENED`, and `billing_hold` false, and it stamps `closed_at_utc` from the logical clock.

An engagement carries a substantial derived surface, all of it maintained eagerly: `accrued_labor_cents` and `billing_hours_total` roll up the completed crew assignments; `inventory_item_count` and `total_inventory_volume_cft` roll up the catalogue; `keep_volume_cft` and `haul_volume_cft` roll up the two dispositions that matter to logistics; `consignment_credit_cents` sums the credit and reversal ledger lines; and `billing_hold` is true exactly when the invoice's `balance_due_cents` is greater than zero while the invoice is `ISSUED` or `DISPUTED`. Engagements can be listed and filtered by `client_id`, by `status` and by `phase`.

A computed summary read is offered alongside the plain engagement read. It reports `engagement_id`, the derived `phase`, the `billing_mode`, `accrued_labor_cents`, `billing_hours_total`, a `volume_estimate_variant` and its `volume_estimate_cft`, a `projected_total_cents`, an `open_hold_count`, a `progress_pct` and a `next_unpack_session_id`. The volume estimate has two variants and the switch between them is the catalogue itself: while `inventory_item_count` is 0 the assessment heuristic applies, multiplying a per-tier room count — 2 rooms for `STUDIO`, 3 for `ONE_BED`, 5 for `TWO_BED` and 8 for `HOUSE` — by 180 cubic feet per room, which can be wildly wrong for a heavy downsizer; from the first catalogued item onward the inventory rollup applies, summing `volume_cft` across every item of the engagement regardless of disposition or handling state, which is exactly what `total_inventory_volume_cft` stores. `projected_total_cents` is pinned as the value the invoice's `total_cents` *would* take if the invoice were issued at this instant: the current subtotal plus the travel, stairs and long-carry surcharges, plus the coordination fee computed from that pre-fee subtotal, plus credits. `open_hold_count` counts the family holds in status `OPEN` or `ESCALATED`. `progress_pct` is a weighted score over milestones whose status is exactly `COMPLETE` — 10 for assessment, 25 for the sort plan, 15 for packing, 30 for move day, 15 for settle-in and 5 for close-out, six weights summing to exactly 100 — with `REOPENED` and `IN_PROGRESS` milestones contributing nothing. `next_unpack_session_id` is the selector winner described in §3.9, or null when no session is eligible.

### 3.2. The Family Portal and Delegated Authority

The family portal is a set of seats on an engagement. Each seat records the `engagement_id` it belongs to, a `party_type` drawn from `CLIENT`, `FAMILY_MEMBER`, `POA` and `MOVE_MANAGER_STAFF`, a `display_name` shown in the portal and an `email` used to log in. A seat of type `CLIENT` also carries the `client_id` it represents; for every other seat type that field is null. Seats can be listed and filtered by `engagement_id`, by `client_id` and by `party_type`.

Two fields on the seat are computed rather than supplied. `can_approve_dispositions` is true exactly when at least one authority record names that seat as its `holder_party_id`, is in status `ACTIVE`, and carries an `authority_scope` of `FULL` or `DISPOSITION_ONLY`, evaluated against the current logical clock; it is initialised false when the seat is created. `active_authority_ceiling_cents` is the maximum `approval_ceiling_cents` across that seat's records in status `ACTIVE`, and reads 0 when none of them is `ACTIVE`.

An authority record is the delegation instrument itself. It names the `engagement_id`, the `holder_party_id` receiving the delegation, the `authority_scope` — one of `FULL`, `DISPOSITION_ONLY` and `BILLING_ONLY` — and an effective window bounded by `effective_from_utc` and `effective_to_utc`, which must be strictly after the start. The `approval_ceiling_cents` may be supplied and otherwise defaults to 100000 cents. A record is born `PENDING`.

Activation moves `PENDING` to `ACTIVE` and is permitted only when the logical clock is at or after `effective_from_utc` and strictly before `effective_to_utc`; a clock outside that window yields `ERR_AUTHORITY_WINDOW_INVALID`. Activation recomputes the holder seat's `can_approve_dispositions` and `active_authority_ceiling_cents`. Suspension moves `ACTIVE` to `SUSPENDED`, records the supplied reason in `revoked_reason`, raises `suspend_count` by one, and recomputes the holder's `can_approve_dispositions` to false when no other record of that seat remains `ACTIVE`. Reinstatement moves `SUSPENDED` back to `ACTIVE`, requires the clock to be strictly before `effective_to_utc`, and recomputes the holder's derived approval fields; the suspend-and-reinstate cycle is capped at two suspensions, and a third attempt is refused with `ERR_HOLD_ESCALATION_LIMIT`. Revocation is irreversible and is reachable from `PENDING`, `ACTIVE` and `SUSPENDED`; it records `revoked_reason`, and from `ACTIVE` it also recomputes the holder's `can_approve_dispositions` to false when no other record of that seat remains `ACTIVE`. Both `REVOKED` and `EXPIRED` are terminal. Expiry is not a user action at all: the ops-run checkpoint moves any record in `PENDING`, `ACTIVE` or `SUSPENDED` to `EXPIRED` once the logical clock has reached `effective_to_utc`, and recomputes the holder's `can_approve_dispositions` to false when no other record of that seat remains `ACTIVE`. Only the move manager may activate, suspend or reinstate; revocation may also be performed by the client. Authority records can be listed and filtered by `engagement_id`, by `holder_party_id` and by `status`.

### 3.3. The Destination Residence and Its Room Capacity

Every engagement has a destination — an apartment, a cottage, an assisted-living suite or a memory-care room. The residence record carries the `engagement_id`, a human `name`, a `unit_type` from `APARTMENT`, `COTTAGE`, `ASSISTED_LIVING_SUITE` and `MEMORY_CARE_ROOM`, and an `address_line`. Residences can be listed and filtered by `engagement_id`, by `approved_by_party_id` and by `placement_status`.

The furniture placement plan for that residence is a small cycle with large consequences. `placement_status` starts `DRAFT`. Proposing the plan moves it to `PROPOSED` and requires the residence's `room_count` to be at least 1; it recomputes every child room's capacity under the provisional variant. Approval moves `PROPOSED` to `APPROVED`, may be performed by the client, by a power of attorney or by the move manager, requires the supplied `approved_by_party_id` to resolve to a seat on the same engagement, and — when the actor is a power of attorney — requires that seat's `can_approve_dispositions` to be true. Approval stamps `approved_by_party_id` and `approved_at_utc`, recomputes every child room's `effective_capacity_linear_inches` under the approved variant, which admits the room's `approved_addendum_linear_inches`, and refreshes each room's `headroom_linear_inches` against its current keep load.

Revision is where the cycle closes, and it has two legs. From `PROPOSED` it returns the plan to `DRAFT` and recomputes child room capacities under the provisional variant; nothing else changes. From `APPROVED` it returns the plan to `DRAFT` only when no item assigned to a room of this residence has reached `DELIVERED` or `UNPACKED`; it raises `placement_revision` by one, clears both `approved_by_party_id` and `approved_at_utc` to null, and drops every child room's `effective_capacity_linear_inches` back to the provisional variant, which excludes the addendum. Both legs take a `reason`. `placement_revision` starts at 1 and counts only revisions out of `APPROVED`; the residence also carries `room_count` and `total_effective_capacity_linear_inches`, the latter summing `effective_capacity_linear_inches` across its rooms. The placement axis has no terminal state — a residence can cycle through approval and revision indefinitely.

A room belongs to a residence through its `destination_residence_id` and carries a `room_type` from `LIVING`, `BEDROOM`, `KITCHEN`, `DINING`, `STORAGE` and `BATH`, a `nominal_linear_inches` wall run, a `nominal_volume_cft`, and an optional `approved_addendum_linear_inches` defaulting to 0. Rooms can be listed and filtered by `destination_residence_id` and by `room_type`.

Room capacity is state-dependent, and this is the mechanism that makes an approved placement plan worth chasing. While the parent residence is `DRAFT` or `PROPOSED`, the provisional variant applies: `effective_capacity_linear_inches` is the room's `nominal_linear_inches` multiplied by a derate of 0.80, rounded half-up to two decimal places, and the addendum is ignored completely. Once the parent is `APPROVED`, the approved variant applies: the nominal run is taken at full value — a factor of 1.00 — and the `approved_addendum_linear_inches` is added on top, again rounded half-up to two decimal places. The same room therefore admits a materially different item set before and after approval, and with a generous addendum its capacity can more than double. Capacity is recomputed when a room is created, on every placement transition, and on every designation that touches the room.

Two load figures and one headroom figure are maintained per room, all rounded half-up to two decimal places. `keep_load_linear_inches` sums `footprint_linear_inches` over the items assigned to that room whose disposition is `KEEP`. `keep_load_volume_cft` sums `volume_cft` over the same set. `headroom_linear_inches` is the room's `effective_capacity_linear_inches` less its `keep_load_linear_inches`. Items assigned to the room whose disposition is anything other than `KEEP` — `DONATE`, `SELL`, `HAUL_AWAY` or `UNDECIDED` — contribute nothing to either load, but they still count in `assigned_item_count`, which tallies every item pointing at the room whatever its disposition.

Headroom is explicitly permitted to persist negative. When an approved plan is revised back to `DRAFT`, capacity shrinks under an already-placed keep load, and the specification does not evict items or refuse the revision on that ground; it refuses only *new* designations into a room that no longer fits them.

### 3.4. Cataloguing the Household, Appraisal and the Disposition Mesh

Cataloguing is the assessment work made concrete. Each item records the `engagement_id` it belongs to, a short `label`, a `category` drawn from `FURNITURE`, `ARTWORK`, `JEWELRY`, `APPLIANCE`, `LINENS`, `DOCUMENTS` and `MISC`, the `footprint_linear_inches` of wall run it consumes when placed, and its `volume_cft`. An `appraised_value_cents` may be given and defaults to 0, alongside an `appraisal_source` of `NONE`, `SELF_REPORTED` or `APPRAISED`, defaulting to `NONE`. Cataloguing an item raises the engagement's `inventory_item_count` and `total_inventory_volume_cft` and raises the engagement's `version` by one. Items can be listed and filtered by `engagement_id`, by `assigned_room_id`, by `consignment_lot_id`, by `unpack_session_id`, by `disposition` and by `handling_state`.

Two independent state axes live on the same item, and this is deliberate. The **disposition** axis records what the family decided; the **handling** axis records where the object physically is. A third, derived axis — `hold_state` — records whether a family member has frozen the object mid-argument, and reads `HELD` when at least one hold on the item is `OPEN` or `ESCALATED` and `NONE` otherwise.

The disposition axis starts at `UNDECIDED` and admits `KEEP`, `DONATE`, `SELL` and `HAUL_AWAY`. Before the sort plan is approved it is a fully reversible mesh: any of the five values may move to any other, provided `disposition_locked` is false and `hold_state` is `NONE`. Designating an item takes the target `disposition`, optionally an `assigned_room_id`, and optionally an `acting_party_id` identifying the portal seat on whose authority the change is made. It is open to the move manager, to the client and to a power of attorney.

The individual legs differ in what they demand and what they touch. Moving to `KEEP` requires an `assigned_room_id`, and the room's post-assignment keep load must fit; it sets `assigned_room_id`, recomputes that room's `keep_load_linear_inches`, `keep_load_volume_cft` and `headroom_linear_inches`, and recomputes the engagement's `keep_volume_cft`. Moving to `DONATE` recomputes the item's `donation_receipt_cents` under the variant selected by its `appraisal_source`. Moving to `SELL` additionally requires `appraised_value_cents` of at least 15000 cents — exactly 15000 is consignable, one cent less is not, and the request is then refused with `ERR_ITEM_BELOW_CONSIGN_MINIMUM` — and it clears `assigned_room_id` to null. Moving to `HAUL_AWAY` recomputes the engagement's `haul_volume_cft`; no vendor assignment is created here, and the junk-haul order is raised only by the sort-plan approval cascade described in §3.6.

The reverse legs are equally specified. Going from `KEEP` to `DONATE` clears `assigned_room_id` to null, recomputes the vacated room's `keep_load_linear_inches` and `headroom_linear_inches`, raises the item's `redesignation_count` by one, and recomputes the engagement's `keep_volume_cft`. Going from `DONATE` back to `KEEP` requires a supplied `assigned_room_id` that passes the space-fit test, sets it, recomputes the room's load and headroom, sets `donation_receipt_cents` back to 0, and raises `redesignation_count` by one. Going from `SELL` to `HAUL_AWAY` is reserved to the move manager and additionally requires the item's `consignment_lot_id` to be null; it recomputes `haul_volume_cft` and raises `redesignation_count` by one. An item already attached to a lot may not be designated to anything other than `SELL`, and the attempt is refused with `ERR_ITEM_ALREADY_CONSIGNED`. Moving an item from one room to another while it stays `KEEP` is a real transition, not a no-op: it recomputes both the vacated and the target room's load and headroom and raises `redesignation_count` by one. `redesignation_count` counts successful disposition changes after the first designation and never decreases; the disposition axis itself has no terminal state.

Whether an item fits its target room is two tests, evaluated in a pinned order. The linear test comes first: the room's current `keep_load_linear_inches`, excluding this item if it is already in the room, plus the item's `footprint_linear_inches`, must be less than or equal to the room's `effective_capacity_linear_inches`. A prospective load exactly equal to capacity fits. Only when the linear test passes is the volume test evaluated: the room's `keep_load_volume_cft` excluding this item, plus the item's `volume_cft`, must be less than or equal to the room's `nominal_volume_cft` multiplied by a safety factor of 0.90 and rounded half-up to two decimal places. The linear failure reports `ERR_ROOM_CAPACITY_EXCEEDED` and wins over the volume failure, which reports `ERR_ROOM_VOLUME_EXCEEDED`.

Appraisal is a separate act from designation. It records an `appraised_value_cents` and its `appraisal_source`, and where the item's disposition is `DONATE` it recomputes the deductible receipt. That receipt has two variants keyed on provenance: a self-reported value is discounted to 0.30 of the stated amount, while a professionally appraised value is taken at 0.85 — so the same object can be worth nearly three times as much on the receipt depending only on who valued it. The product is rounded half-up to whole cents and then capped at 500000 cents; the rounding happens before the cap, never after. An `appraisal_source` of `NONE` yields a raw value of zero. Items whose disposition is anything other than `DONATE` report `donation_receipt_cents` of 0.

The handling axis starts at `AT_ORIGIN` and forks. Branch A carries the keepers: `PACKED`, then `LOADED`, then `DELIVERED`, then `UNPACKED`. Branch B carries everything leaving the household: `STAGED_FOR_PICKUP`, then `REMOVED`. Both `UNPACKED` and `REMOVED` are terminal. Advancing the axis takes a `target_handling_state` and, for the unpack step only, an `unpack_session_id`; the move manager and the crew lead may drive it.

Each step has its own precondition. `AT_ORIGIN` to `PACKED` requires the item's disposition to be `KEEP` and the engagement's sort plan to be `APPROVED` or `FROZEN`. `PACKED` to `LOADED` requires the move-day plan to be `IN_PROGRESS`. `LOADED` to `DELIVERED` requires the move-day plan to be `IN_PROGRESS` or `COMPLETED` and the item's `assigned_room_id` to be non-null. `DELIVERED` to `UNPACKED` requires the supplied unpack session to belong to the same engagement and to be `IN_PROGRESS`; it sets the item's `unpack_session_id` and raises that session's `items_unpacked_count`. On the other branch, `AT_ORIGIN` to `STAGED_FOR_PICKUP` requires the disposition to be `DONATE`, `SELL` or `HAUL_AWAY`, the sort plan to be `APPROVED` or `FROZEN`, and `hold_state` to be `NONE`. `STAGED_FOR_PICKUP` to `REMOVED` requires at least one vendor assignment on the engagement whose `service_kind` matches the item's disposition family to be `PERFORMED`, `SIGNED_OFF` or `PAID`, and it recomputes the engagement's `haul_volume_cft` when the disposition is `HAUL_AWAY`. The first three steps of branch A and the first step of branch B stamp `updated_at` and nothing else.

### 3.5. Family Disputes and the Hold Axis

A family hold is how a daughter in Denver stops the dining table being sold. It names the disputed `inventory_item_id`, the `raised_by_party_id` who objects, and a `reason` explaining the objection. It is born `OPEN`, and creating it immediately sets the subject item's `hold_state` to `HELD`, which blocks re-designation, appraisal, staging and consignment membership for as long as the dispute is live. The move manager, the client, a family member and a power of attorney may all raise one. Holds can be listed and filtered by `inventory_item_id`, by `raised_by_party_id`, by `resolved_by_party_id` and by `status`.

Escalation moves an `OPEN` hold to `ESCALATED`, takes a `note`, raises `escalation_count` by one, and leaves the item `HELD`; the move manager and a family member may escalate. Remand sends an `ESCALATED` hold back to `OPEN`, takes a `note`, raises `remand_count` by one, and is reserved to the move manager. The two counters are capped independently at two apiece, so the escalate-and-remand cycle can run at most twice in each direction before `ERR_HOLD_ESCALATION_LIMIT` shuts it down.

Resolution takes a `resolution` and a `resolved_by_party_id`, and may be performed by the move manager, the client or a power of attorney. Resolving in favour of the family — the `KEEP` resolution — is reachable from either `OPEN` or `ESCALATED`; it stamps `resolved_by_party_id` and `resolution_note`, forces the item's disposition to `KEEP` while leaving its `assigned_room_id` exactly as it was, and recomputes the item's `hold_state` to `NONE` when no other hold on that item remains `OPEN` or `ESCALATED`. Where a power of attorney performs the resolution and the item's `appraised_value_cents` exceeds the high-value threshold, the delegated-authority checks of §2.9 apply in full. Resolving the other way — the `RELEASE` resolution — is likewise reachable from `OPEN` or `ESCALATED`; it stamps `resolved_by_party_id` and `resolution_note` and recomputes `hold_state` to `NONE` under the same condition, but leaves the disposition untouched, so the table goes to the consignment house after all. Withdrawal is the raiser's own exit, available only from `OPEN`, open to the move manager and to a family member, and when the actor is a family member the `X-User-ID` must equal the hold's `raised_by_party_id`; it recomputes `hold_state` to `NONE` when no other hold on the item remains `OPEN` or `ESCALATED`. `RESOLVED_KEEP`, `RESOLVED_RELEASE` and `WITHDRAWN` are all terminal.

### 3.6. The Sort Plan and the Freeze Point

The sort plan is the document the family signs off, and approving it is the moment the reversible mesh of §3.4 becomes irreversible. Creating a plan names the `engagement_id`, carries `expected_engagement_version` under the optimistic-concurrency rule of §2.10, and may carry `notes` from the move manager. It supersedes the engagement's prior `DRAFT` or `REJECTED` plan, is born `DRAFT`, and raises the engagement's `version` by one. Plans can be listed and filtered by `engagement_id`, by `approved_by_party_id` and by `status`.

Submitting the plan requires it to be `DRAFT`, requires the engagement to have at least one catalogued item — otherwise `ERR_NO_INVENTORY` — and requires that no item of the engagement is under a live hold. On success it snapshots `undecided_count_at_submit`, the count of the engagement's items whose disposition was `UNDECIDED` at that instant. Approval then demands that snapshot to read zero; a plan submitted with undecided items can never be approved, and both the submit-time and approve-time failures report `ERR_UNDECIDED_ITEMS_REMAIN`.

Approval is open to the move manager, the client and a power of attorney, and takes an `approved_by_party_id`. Where the actor is a power of attorney, that seat's `can_approve_dispositions` must be true and its `active_authority_ceiling_cents` must reach the highest `appraised_value_cents` among the engagement's non-`KEEP` items. Approval then runs a four-hop cascade. First, every item of the engagement whose disposition is not `UNDECIDED` has `disposition_locked` set to true, and the plan's `locked_item_count` is refreshed to the number of the engagement's items now locked. Second, for every newly locked item whose disposition is `HAUL_AWAY`, the engagement's `haul_volume_cft` is recomputed. Third, when that recomputed haul volume reaches 250 cubic feet and no haul-away vendor assignment already exists for the engagement, one is auto-created in status `REQUESTED` against the first vendor whose `vendor_type` is `JUNK_HAUL` ordered by `created_at` ascending, with `service_kind` of `HAUL_AWAY`, a `quoted_cents` of 45000 and a `service_date` equal to the UTC calendar date of the engagement's `scheduled_move_start_utc`; where no junk-haul vendor exists at all, no assignment is created and the approval still succeeds. Fourth, the `SORT_PLAN` milestone moves from `IN_PROGRESS` to `COMPLETE`, which starts the `PACK` milestone and therefore moves the engagement's `phase` to `PACK`.

Rejection is the other outlet from `SUBMITTED`. It takes a non-empty `reason`, which is stored as `rejected_reason`, and is open to the same three roles as approval. From `REJECTED` the move manager may reopen the plan back to `DRAFT`: this raises `reopen_count` by one and clears `rejected_reason` to null, closing the first cycle.

The second cycle is the consequential one. From `APPROVED` the move manager may also reopen back to `DRAFT`, but only when the engagement's move-day plan, if one exists, is not `FROZEN`, `IN_PROGRESS` or `COMPLETED`. That reopen raises `reopen_count` by one, sets `disposition_locked` back to false on every item of the engagement — restoring the reversible mesh in full — and moves the `SORT_PLAN` milestone from `COMPLETE` back to `REOPENED`, which pulls the engagement's `phase` back to `SORT_PLAN`. Both reopen legs take a `reason` and both are capped at two reopens; the third attempt is refused with `ERR_SORT_PLAN_REOPEN_LIMIT`.

`FROZEN` is the plan's terminal state and is never reached by a user action. It is cascaded in when the move-day plan is frozen, it stamps `frozen_at_utc` from the logical clock, and from there no reopen is possible regardless of how much `reopen_count` budget remains; the attempt is refused with `ERR_SORT_PLAN_FROZEN`.

### 3.7. Move Day: the Roster, the Hours and the Six-Hop Completion Cascade

The move-day plan is created against an `engagement_id` with a `scheduled_start_utc`, a `truck_capacity_cft` describing one truck's usable cargo volume and a `truck_count`. Two figures are derived at once. `freeze_at_utc` is the scheduled start less seventy-two hours; the freeze window is entered when the clock is **at or after** that instant, so the boundary instant itself is already inside the window. `crew_min_required` is read from the engagement's `home_tier` and never from its `package_tier`: two crew for a `STUDIO`, three for `ONE_BED`, four for `TWO_BED` and six for a `HOUSE`. The plan is born `DRAFT` and can be listed and filtered by `engagement_id` and by `status`.

Crew members are platform reference data, not engagement data. Each carries a `full_name`, a `crew_role` from `LEAD`, `ORGANIZER`, `PACKER` and `DRIVER`, and an `hourly_rate_cents`; when the rate is omitted it falls back to the role's standard rate — 9500 cents an hour for a lead, 8200 for an organiser, 6800 for a packer and 7400 for a driver. Each member also carries `assignment_count`, the tally of crew assignments naming that member in any status.

Staffing the plan creates a crew assignment naming the `move_day_plan_id`, the `crew_member_id` and `expected_move_day_plan_version`, and optionally a `replaces_assignment_id` pointing at the `NO_SHOW` slot it fills. Creating one raises the plan's `version` by one, transitions the replaced assignment from `NO_SHOW` to `REPLACED`, and raises the crew member's `assignment_count`. Assignments are born `ASSIGNED` and can be listed and filtered by `move_day_plan_id`, by `crew_member_id`, by `replaces_assignment_id` and by `status`.

Confirming an assignment moves it from `ASSIGNED` to `CONFIRMED` and is permitted only while the parent plan is `DRAFT` or `CREWED`. It recomputes the plan's `crew_confirmed_count` — the number of the plan's assignments in status `CONFIRMED`, `CHECKED_IN` or `COMPLETED` — and then bubbles upward: when that count has reached `crew_min_required` and at least one of the confirmed assignments belongs to a crew member whose `crew_role` is `LEAD`, the plan itself transitions from `DRAFT` to `CREWED`, which recomputes `planned_trip_count` from the engagement's `keep_volume_cft`. The move manager confirms the plan from `CREWED` to `CONFIRMED`, which requires the engagement's sort plan to be `APPROVED` and recomputes `planned_trip_count` again.

From `CONFIRMED` the roster can still be reopened. Re-crewing takes a `reason`, requires the logical clock to be strictly before `freeze_at_utc`, returns the plan to `DRAFT` and reverts every `CONFIRMED` assignment on it to `ASSIGNED`, recomputing `crew_confirmed_count` to zero. Once the clock reaches `freeze_at_utc`, re-crewing, creating an assignment and confirming an assignment are all refused with `ERR_FREEZE_WINDOW_ENTERED`, and so are designation and appraisal of any inventory item.

Freezing is the move manager's declaration that the plan is final. It is permitted from `CONFIRMED` only once the clock is at or after `freeze_at_utc` — attempting it earlier is refused with `ERR_FREEZE_WINDOW_NOT_ENTERED` — and it cascades twice: the engagement's sort plan moves from `APPROVED` to `FROZEN`, and the `PACK` milestone moves from `IN_PROGRESS` to `COMPLETE`, starting the `MOVE_DAY` milestone. Starting move day moves the plan from `FROZEN` to `IN_PROGRESS`, requires the clock to be at or after `scheduled_start_utc`, requires `crew_confirmed_count` to have reached `crew_min_required` — otherwise `ERR_CREW_MINIMUM_NOT_MET` — and requires at least one lead on the plan's non-terminal roster — otherwise `ERR_CREW_LEAD_REQUIRED`. It stamps `started_at_utc`. Both the move manager and a crew lead may start and complete move day.

Rescheduling is the escape hatch and is reachable from `CONFIRMED` and from `FROZEN`. It takes a `new_start_utc`, which must be strictly after the current logical clock, and a `reason`. It raises `reschedule_count` by one, sets `scheduled_start_utc` to the new instant and recomputes `freeze_at_utc` from it, and shifts every vendor assignment of the engagement in status `ACCEPTED`, `SCHEDULED` or `COI_BLOCKED` whose `service_date` equalled the pre-reschedule start date onto the new start date — which is precisely how a vendor's certificate of insurance can end up expiring before its own service date. From the frozen leg there is one further pinned outcome: a sort plan already `FROZEN` does **not** return to `APPROVED`, because `FROZEN` is terminal. `RESCHEDULED` is never observable as a resting state; in the same request the plan returns to `DRAFT`, reverting every `CONFIRMED` assignment on it to `ASSIGNED`. Only one reschedule is permitted per plan; a second attempt, or a `new_start_utc` that is not strictly after the clock, is refused with `ERR_RESCHEDULE_LIMIT`.

On the ground, a crew member is clocked in with an `at_utc` that must be at or after the plan's `started_at_utc`, moving the assignment from `CONFIRMED` to `CHECKED_IN` while the plan is `IN_PROGRESS`, and stamping `checked_in_at_utc`. Clocking out takes an `at_utc` strictly after `checked_in_at_utc` — otherwise `ERR_INVALID_TIME_RANGE` — stamps `checked_out_at_utc`, creates a time entry of kind `LABOR` spanning the two instants, and recomputes the assignment's `portal_hours`, `billing_hours`, `applied_hours`, `overtime_hours` and `labor_cents`, then the engagement's `accrued_labor_cents` and `billing_hours_total`. A member who never turns up is marked with a `note` stored as `no_show_note`; that is reachable from `ASSIGNED` and from `CONFIRMED`, and from `CONFIRMED` it recomputes `crew_confirmed_count` downward, which may drop the plan below its crew minimum. `COMPLETED` and `REPLACED` are the terminal states of the assignment axis.

Time entries are the raw material of every hour figure. Each names its `crew_assignment_id`, an `entry_kind` of `LABOR`, `TRAVEL` or `BREAK`, a `started_at_utc` and an `ended_at_utc` that must be strictly after it. Entries may be added only while the parent assignment is `CHECKED_IN` or `COMPLETED`; on a `COMPLETED` assignment every hour and money rollup is recomputed in place. Each entry carries a `raw_hours`, the exact interval length in hours held to four decimal places by truncation, and a `rounded_hours`, that raw figure divided by a quarter-hour increment, rounded half-up to a whole number of increments and multiplied back, giving a value at two decimal places. Voiding an entry takes a `reason`, stored as `void_reason`, sets `voided` to true, and recomputes the assignment's hours and money from the remaining non-voided entries; a voided entry is excluded from every rollup thereafter. Entries can be listed and filtered by `crew_assignment_id` and by `entry_kind`.

Hours exist in two representations, and the divergence between them is intentional. Both draw on the same eligible set: the assignment's entries whose `voided` is false and whose `entry_kind` is `LABOR` or `TRAVEL`; break entries are computed the same way as any other but are excluded from both representations. The portal view, stored as `portal_hours` and shown to the family, rounds each entry to the quarter hour first and then sums the rounded parts, with the total rounded half-up to two decimal places. The billing view, stored as `billing_hours` and used for every monetary computation, sums the raw hours first and then rounds that single total to the quarter hour. Both are order-insensitive sums. The two figures diverge whenever the per-entry rounding residues accumulate, and the divergence can by itself push the assignment across the overtime threshold — which is why the invoicing order is pinned to the billing view.

From `billing_hours` the money follows in three fixed steps. `applied_hours` applies the minimum call-out floor, and this is the first place the two pipelines part company: under `HOURLY` it is the greater of `billing_hours` and three hours, while under `PACKAGE` there is no floor at all and `applied_hours` simply equals `billing_hours`. Then `overtime_hours` is whatever part of `applied_hours` exceeds eight hours, and zero when it does not; the boundary is strict, so `applied_hours` of exactly 8.00 yields `overtime_hours` of 0.00. The remainder is the regular portion. Finally `labor_cents` is the regular hours multiplied by the crew member's `hourly_rate_cents` and rounded half-up to whole cents, plus the overtime hours multiplied by that same rate and by an overtime multiplier of 1.5 and rounded half-up to whole cents. The two components are rounded separately and then added; they are never summed as fractional amounts and rounded once.

The engagement's rollups take only `COMPLETED` assignments: `accrued_labor_cents` sums their `labor_cents`, and `billing_hours_total` sums their `applied_hours` rounded half-up to two decimal places. Assignments in `ASSIGNED`, `CONFIRMED`, `CHECKED_IN`, `NO_SHOW` or `REPLACED` contribute nothing.

Completing move day is the deepest cascade in the system, and every hop is caused by the hop before it rather than by the original request. It requires the plan to be `IN_PROGRESS` and every assignment on it to be `COMPLETED`, `NO_SHOW`, `REPLACED` or `CHECKED_IN` — no assignment may still be `ASSIGNED` or `CONFIRMED` — and it takes the `actual_loaded_volume_cft` the crew measured. First, every assignment still `CHECKED_IN` transitions to `COMPLETED`, its `checked_out_at_utc` set to the current logical clock and a `LABOR` time entry created spanning its `checked_in_at_utc` to that instant. Second, each such completion recomputes that assignment's `portal_hours`, `billing_hours`, `applied_hours`, `overtime_hours` and `labor_cents` from its non-voided entries. Third, the engagement's `accrued_labor_cents` and `billing_hours_total` are recomputed from those assignments. Fourth, the engagement's `DRAFT` invoice receives the pipeline labour line: an `HOURLY_LABOR` line under the hourly pipeline, or an `OVERAGE_LABOR` line under the package pipeline when `billing_hours_total` exceeds the tier allowance. Fifth, the invoice's `subtotal_cents`, `coordination_fee_cents`, `total_cents` and `balance_due_cents` are recomputed and the invoice's `version` rises by one. Sixth, the `MOVE_DAY` milestone moves from `IN_PROGRESS` to `COMPLETE`, which starts the `SETTLE_IN` milestone and therefore moves the engagement's `phase` to `SETTLE_IN`. Alongside the cascade the supplied `actual_loaded_volume_cft` is stored and `actual_trip_count` is computed under the actual variant. `COMPLETED` is the plan's terminal state.

Trip counting is one formula with two inputs. The combined capacity is `truck_capacity_cft` multiplied by `truck_count`. The number of full trips is the volume divided by that combined capacity, taken as a whole number rounded down. The remainder is the volume less the full trips multiplied by the combined capacity, and one extra trip is added only when that remainder is **strictly greater** than fifteen percent of the combined capacity — a remainder of exactly fifteen percent is absorbed into the last trip and adds nothing. Where the volume is greater than zero but the count so far came out at zero, the count is set to one. The planned variant, stored in `planned_trip_count`, is computed when the plan reaches `CREWED` and again at `CONFIRMED`, and uses the engagement's `keep_volume_cft`, that is only the items designated `KEEP`. The actual variant, stored in `actual_trip_count`, is computed at completion and uses `actual_loaded_volume_cft`, which includes packing-material displacement and therefore usually exceeds the keep volume. `actual_trip_count` is null until completion.

### 3.8. Vendors, Consignment and the Non-Monotone Settlement

A vendor is platform reference data registered by the platform administrator: a `name`, a `vendor_type` from `JUNK_HAUL`, `CONSIGNMENT`, `APPRAISAL`, `CLEANING` and `SHREDDING`, a `coi_expires_on` certificate-of-insurance expiry date in `YYYY-MM-DD` form, an optional `daily_capacity` defaulting to 3, and an optional `holdback_pct` defaulting to 0.10 — the fraction of each quote withheld until the client signs off. Two figures are maintained on the vendor: `coi_renewal_count`, which rises by one on each renewal and never falls, and `blocked_assignment_count`, the number of that vendor's assignments currently sitting in `COI_BLOCKED`.

Ordering work from a vendor names the `engagement_id`, the `vendor_id`, the `service_kind` from `HAUL_AWAY`, `CONSIGNMENT_PICKUP`, `APPRAISAL`, `CLEANING` and `SHREDDING`, the `service_date` and the agreed `quoted_cents`. The service kind must match the vendor's type under a strict one-to-one map — haul-away work to a junk hauler, consignment pickup to a consignment house, appraisal to an appraiser, cleaning to a cleaner and shredding to a shredder — and a mismatch is refused with `ERR_VENDOR_TYPE_MISMATCH`. Orders are born `REQUESTED` and can be listed and filtered by `engagement_id`, by `vendor_id`, by `signed_off_by_party_id`, by `status` and by `service_date`.

The vendor accepts its own order — the acting `X-User-ID` must equal the assignment's `vendor_id` — moving it from `REQUESTED` to `ACCEPTED` and computing `holdback_cents` as the `quoted_cents` multiplied by the vendor's `holdback_pct` at accept time, rounded half-up to whole cents. The move manager then schedules it, moving `ACCEPTED` to `SCHEDULED` past two eligibility checks. The certificate check compares two calendar dates, not instants: the vendor's `coi_expires_on` must not be earlier than the assignment's `service_date`, so a certificate expiring exactly *on* the service date is still valid, and a failure reports `ERR_VENDOR_COI_EXPIRED`. The capacity check counts the vendor's assignments on that same calendar date whose status is `SCHEDULED`, `COI_BLOCKED`, `PERFORMED`, `SIGNED_OFF` or `PAID` and requires that count to be strictly below `daily_capacity`; orders still `REQUESTED` or `ACCEPTED`, and cancelled ones, consume no capacity. Capacity is whole-day granular, so two assignments on the same date collide once the ceiling is reached regardless of the hour, and the failure reports `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED`.

A certificate can lapse *after* scheduling, either because the clock advanced past a renewal boundary or because the service date was pushed beyond the certificate by a reschedule. The ops-run checkpoint sweeps that up: a `SCHEDULED` assignment whose vendor's `coi_expires_on` is now earlier than its `service_date` moves to `COI_BLOCKED` and raises the vendor's `blocked_assignment_count`. Renewing the certificate takes a new `coi_expires_on`, raises `coi_renewal_count`, and cascades in the other direction: every `COI_BLOCKED` assignment whose `service_date` the renewed date now covers returns to `SCHEDULED`, lowering `blocked_assignment_count`. The platform administrator and the vendor itself may renew.

Performance is recorded with a `performed_at_utc` that must be at or after midnight UTC on the `service_date`, and may be recorded by the vendor or by the move manager. It stamps `performed_at_utc`, sets `paid_cents` to the interim payout — the `quoted_cents` less the `holdback_cents` — and appends a `VENDOR_PASSTHROUGH` ledger line for the full `quoted_cents` to the engagement's invoice, recomputing the invoice totals. Sign-off follows: the move manager, the client or a power of attorney supplies a `signed_off_by_party_id` that must resolve to a seat on the same engagement, `holdback_released` becomes true and `paid_cents` becomes the final payout, the full `quoted_cents`. Billing then marks the subcontract `PAID`, which requires the engagement's invoice not to be `FINALIZED`. Cancellation is reachable from `REQUESTED`, `ACCEPTED`, `SCHEDULED` and `COI_BLOCKED`, takes a `reason` stored as `cancel_reason`, and is open to the move manager and the vendor; cancelling from `SCHEDULED` additionally frees the slot it held on the vendor's day. `PAID` and `CANCELLED` are terminal.

Consignment begins by gathering items into a lot. The lot names the `engagement_id`, the consignment house's `vendor_id`, the asking `list_price_cents`, the `listed_on` date from which the unsold window is measured, and the `item_ids` of the members. Creating it sets `consignment_lot_id` on each member item, computes `item_count` from those members, and computes `current_price_cents`. Lots are born `LISTED` and can be listed and filtered by `engagement_id`, by `vendor_id` and by `status`.

Markdowns run twice at most and are always taken off the **original** list price rather than compounded off the previous price. The first markdown moves `LISTED` to `MARKED_DOWN` and raises `markdown_round` to 1, setting `current_price_cents` to the `list_price_cents` less twenty percent, rounded half-up to whole cents. The second is a self-loop on `MARKED_DOWN` that raises `markdown_round` to 2 and sets `current_price_cents` to the `list_price_cents` less thirty-five percent, rounded the same way. At `markdown_round` 0 no discount applies at all. A third attempt is refused with `ERR_MARKDOWN_ROUNDS_EXHAUSTED`. Both the move manager and the vendor may mark down.

Recording a sale is reachable from `LISTED` and from `MARKED_DOWN`, takes a `gross_sale_price_cents` greater than zero and a `sold_on` date not earlier than `listed_on`, and requires the lot to have at least one member item; a violation reports `ERR_INVALID_SALE_PRICE`. It stamps `gross_sale_price_cents` and `sold_on` and computes three figures in a pinned order. The commission is a banded **average** rate applied to the whole gross, not a marginal one: a gross of at most 50000 cents pays fifty percent, a gross above that but at most 250000 cents pays forty percent, and anything above 250000 pays thirty percent — so a lot selling for exactly 50000 pays half, while one selling for 50001 pays forty percent of the whole. The result is rounded half-up to whole cents. The `fees_cents` figure is a flat pickup charge of 7500 cents plus a photography charge of 1200 cents per member item, that photography component capped at 12000 cents; the item count used is the number of items pointing at the lot at the moment of sale. `net_proceeds_cents` is then the gross less `commission_cents` less `fees_cents`, floored at zero; the commission and the fees are each rounded to whole cents **before** the subtraction, never rounded once at the end.

Settlement is what turns proceeds into a credit. It is reachable from `SOLD` only, requires `credited` to be false and the engagement's invoice not to be `FINALIZED`, and may be performed by the move manager or by billing. It appends a `CONSIGNMENT_CREDIT` ledger line whose `amount_cents` is the negation of `net_proceeds_cents` with `source_consignment_lot_id` set to the lot, then recomputes the invoice's `credits_cents`, `total_cents` and `balance_due_cents` and raises the invoice's `version` by one, then refreshes the engagement's `consignment_credit_cents`, and finally sets `credited` to true. A second settle on the same lot is refused with `ERR_LOT_ALREADY_CREDITED`.

The credit figure itself is defined in two variants. The final variant, the one actually posted, is `net_proceeds_cents` — gross less commission less fees — and it is the amount any later reversal must mirror exactly. A provisional variant, named `credit_preview_cents`, is defined as the `gross_sale_price_cents` less the `commission_cents` while the lot is `SOLD` but not yet `SETTLED`; because it omits the fees it always overstates what the client will actually receive. This provisional figure is described as a preview visible when reading a single lot, but the lot entity declares no field to carry it and the single-lot read returns the bare lot record; the specification therefore does not determine a response key under which the preview is exposed, and the only pinned monetary outcome of settlement is the final variant, `credit_posted_cents`, equal to `net_proceeds_cents`.

Declaring a lot unsold is reachable from `LISTED` and from `MARKED_DOWN` and requires the logical clock's date to be at least thirty days after `listed_on`; an earlier attempt is refused with `ERR_UNSOLD_WINDOW_NOT_ELAPSED`. The move manager and the vendor may both declare.

Returning a lot to the client is where the ledger becomes non-monotone, and it behaves differently depending on where the lot has been. The return is reachable from `SOLD`, from `SETTLED` and from `UNSOLD`, takes a `reason`, and is reserved to the move manager; from `SETTLED` and from `SOLD` it additionally requires the engagement's invoice not to be `FINALIZED`. Returning a lot that was settled runs four hops: a `CONSIGNMENT_REVERSAL` ledger line whose `amount_cents` is the positive `net_proceeds_cents` is appended and `reversed` is set to true; the invoice's `credits_cents`, `total_cents` and `balance_due_cents` are recomputed and its `version` rises by one; the engagement's `billing_hold` is recomputed, becoming true when the recomputed `balance_due_cents` is greater than zero while the invoice is `ISSUED` or `DISPUTED`; and because a live `billing_hold` blocks close-out, a `CLOSE_OUT` milestone that was already `COMPLETE` moves to `REOPENED`. On that same leg the member items keep their `SELL` disposition: the compound side effect of clearing `consignment_lot_id` to null and forcing the disposition to `KEEP` is explicitly **not** performed. Whether the settled-lot return nonetheless clears `consignment_lot_id` on its own — as the unsold-lot return explicitly does — is not determined by this specification; the pinned outcomes on this leg are that the disposition is not forced to `KEEP` and that the items remain `SELL`. Returning a lot that was sold but never credited is structurally different despite using the same operation: no ledger line is written because nothing was credited, and `reversed` stays false. Returning a lot that was declared unsold clears `consignment_lot_id` to null on each member item.

Hauling the lot away is the last exit and is reachable from `UNSOLD` and from `RETURNED`; from `UNSOLD` it requires the engagement's invoice not to be `FINALIZED`, and the returned leg behaves identically in every respect. The lot's `disposal_fee_cents` reads 0 until the lot is hauled; at haul time it becomes the total `volume_cft` of the lot's member items multiplied by 145 cents per cubic foot, rounded half-up to whole cents, and then floored at a minimum of 9500 cents — the rounding happens before the floor is applied. A `DISPOSAL_FEE` ledger line is appended and the invoice totals recompute. Each member item's disposition changes to `HAUL_AWAY` and its handling state to `REMOVED` **even when `disposition_locked` is true**, because a system cascade is not a re-designation request. `HAULED` is the lot's only terminal state; `RETURNED` is not terminal precisely because a returned lot can still be hauled.

The separate threshold of 250 cubic feet mentioned in §3.6 governs only whether a junk-haul order is auto-created from the engagement's `haul_volume_cft`; it plays no part in the disposal fee formula, and the auto-created order carries a quote of 45000 cents.

### 3.9. Settle-In: Unpack Sessions and the Punch List

Settle-in is the part the client actually experiences. An unpack session names the `engagement_id`, a `scheduled_start_utc` and a `priority` of either `ESSENTIALS` or `STANDARD`. Sessions are born `SCHEDULED` and carry `items_unpacked_count`, the number of items pointing at that session whose handling state is `UNPACKED`, plus a `started_at_utc` and a `reopen_count`. They can be listed and filtered by `engagement_id`, by `status` and by `priority`.

Starting a session is reachable from `SCHEDULED` and from `REOPENED`, is open to the move manager and the crew lead, and requires the engagement's move-day plan to be `COMPLETED`. Where the session's `priority` is `STANDARD`, every `ESSENTIALS` session of the same engagement created earlier must already be `COMPLETED`; otherwise the start is refused with `ERR_ESSENTIALS_SESSION_PENDING`. Starting stamps `started_at_utc`, and on the reopened leg it stamps it afresh from the current logical clock. Completing the session is reachable from `IN_PROGRESS` and recomputes `items_unpacked_count`. A session moves from `COMPLETED` back to `REOPENED` only as a cascade from a punch-list reopen that names it, and that cascade is capped at two reopens. The unpack axis has no terminal state at all, so a session can cycle through completion and reopening within that cap.

Which session comes next is a deterministic selector, reported as `next_unpack_session_id` on the engagement summary and used by the start precondition. The candidate pool is the engagement's sessions in status `SCHEDULED` or `REOPENED`; sessions that are `IN_PROGRESS` or `COMPLETED` are excluded. Candidates are ranked with essentials before standard, and within a priority by `scheduled_start_utc` ascending; ties are broken by `created_at` ascending, never by `id`. The first candidate under that ordering wins, and when the pool is empty the summary reports `next_unpack_session_id` as null.

A punch-list item is a defect found during settle-in. It names the `engagement_id`, a `description` of what is wrong, a `severity` of `CRITICAL`, `MAJOR` or `MINOR`, and optionally the `unpack_session_id` that surfaced it — null when the defect was raised outside any session. The move manager, the crew lead, the client, a family member and a power of attorney may all raise one. Each severity carries its own service-level window measured from the item's `created_at`: a critical defect is due within twenty-four hours, a major one within seventy-two hours and a minor one within one hundred and sixty-eight hours, and that instant is stored as `due_at_utc`. `breached_sla` is true exactly when the current logical clock is strictly after `due_at_utc` while the item's status is `OPEN` or `REOPENED`. Items can be listed and filtered by `engagement_id`, by `unpack_session_id`, by `status` and by `severity`.

A defect is born `OPEN`. Resolving it moves it to `RESOLVED` and is reachable from `OPEN` and from `REOPENED`; it is open to the move manager and the crew lead, requires a non-empty `resolution_note`, and — on the leg out of `OPEN` — recomputes `breached_sla`. Reopening a `RESOLVED` defect takes a `reason`, is open to the move manager, the client, a family member and a power of attorney, and is capped at three reopens; a fourth attempt is refused with `ERR_REOPEN_LIMIT`. The reopen raises `reopen_count` by one and cascades twice: where the item names an `unpack_session_id` and that session is `COMPLETED`, the session moves to `REOPENED`; and where the engagement's `CLOSE_OUT` milestone is `COMPLETE`, it moves to `REOPENED` too, pulling the engagement's `phase` back to `CLOSE_OUT`. The punch axis likewise has no terminal state.

### 3.10. Milestones, Phase, Lateness and the Ops-Run Checkpoint

The six milestones laid down at engagement creation are the engagement's timeline, and they carry two independent axes. Each milestone names its `engagement_id`, its `milestone_key`, its `sequence_index` from 1 to 6 in timeline order, a `completed_by_party_id` credited with completion and null until then, a `due_on` date, a `completed_at_utc`, a `reopen_count`, a progress `status` and a lateness `overdue_status`. Milestones can be listed and filtered by `engagement_id`, by `completed_by_party_id`, by `milestone_key`, by `status` and by `overdue_status`.

On the progress axis, a milestone starts `PENDING` and is moved to `IN_PROGRESS` by the system — the first one at engagement creation, and each of the others when its predecessor completes — which recomputes the engagement's `phase` to that milestone's key. Completing a milestone is the move manager's act, takes a `completed_by_party_id`, and is reachable from `IN_PROGRESS` and from `REOPENED`. It requires the milestone one `sequence_index` lower on the same engagement to be `COMPLETE` where such a milestone exists, otherwise `ERR_PREDECESSOR_MILESTONE_INCOMPLETE`. Two keys carry extra conditions: completing `MOVE_DAY` requires the engagement's move-day plan to be `COMPLETED`, and completing `CLOSE_OUT` requires the engagement's `billing_hold` to be false and no punch-list item to be `OPEN` or `REOPENED`. Completion stamps `completed_at_utc` and `completed_by_party_id`, moves the lateness axis from `OVERDUE` to `RECOVERED` where it was late and otherwise leaves it `ON_TIME`, and starts the successor milestone, recomputing `phase`.

Reopening a completed milestone takes a `reason`, is reachable only from `COMPLETE`, is capped at two reopens, and additionally requires that no milestone of the same engagement with a higher `sequence_index` is `COMPLETE` — otherwise `ERR_SUCCESSOR_MILESTONE_COMPLETE`. It raises `reopen_count` by one, clears `completed_at_utc` back to null, moves the lateness axis from `RECOVERED` back to `OVERDUE` (never to `ON_TIME`), and recomputes `phase` back to this milestone's key. The same transition is also driven by the system, cascaded from a consignment reversal or from a punch-list reopen. `REOPENED` never rests: in the same request the milestone returns to `IN_PROGRESS`, recomputing `phase` again. The progress axis has no terminal state.

The lateness axis is separate and latching. It starts `ON_TIME`. The ops-run checkpoint moves it to `OVERDUE` when the milestone's status is `PENDING`, `IN_PROGRESS` or `REOPENED` and the logical clock's date is **strictly after** `due_on` — a clock date exactly equal to `due_on` is not overdue — and it walks the engagement's milestones in `sequence_index` ascending order, skipping `COMPLETE` ones. Once latched, no ops-run and no due-date change ever moves it back to `ON_TIME`. Completing a milestone that is `OVERDUE` moves it to `RECOVERED`; reopening one that is `RECOVERED` moves it back to `OVERDUE`. `OVERDUE` and `RECOVERED` therefore alternate with completion and reopening, and `ON_TIME` is unreachable once left.

The engagement's `phase` is derived, never assigned. It is the `milestone_key` of the open milestone with the lowest `sequence_index`, where "open" means status `PENDING`, `IN_PROGRESS` or `REOPENED`; when no milestone is open at all, the phase reads `DONE`. Re-entry is well defined: reopening milestone four pulls the phase back to that milestone's key even when milestones five and six were never started.

The ops-run checkpoint is the system's periodic sweep, available to the move manager and the platform administrator, and it does exactly three things in one request: it latches milestone lateness as described above, it expires authority records whose `effective_to_utc` the clock has reached, and it moves `SCHEDULED` vendor assignments whose certificate now expires before their service date into `COI_BLOCKED`. It answers with the `engagement_id`, a `milestones_flagged_overdue` count, an `authorities_expired` count, a `vendor_assignments_blocked` count and the new `ops_run_seq`. Each run raises the engagement's `ops_run_seq` by one — a monotone counter that never decreases — and raises the engagement's `version` by one.

### 3.11. Billing: the Ledger, the Invoice Lifecycle and Close-Out

Every engagement has exactly one invoice, created with it in status `DRAFT`, and every charge and credit the engagement ever incurs lands on it as an immutable ledger line. A line names its `invoice_id`, a `line_type`, a signed `amount_cents` where charges are positive and credits negative, and a human `memo`; lines produced by a consignment credit or reversal also name their `source_consignment_lot_id`, which is null for every other kind. Each line records `created_by_role`, the `X-User-Role` of the actor whose request produced it, or `SYSTEM` for lines produced by a cascade. The twelve line kinds are `PACKAGE_BASE`, `HOURLY_LABOR`, `OVERAGE_LABOR`, `TRAVEL_SURCHARGE`, `STAIRS_SURCHARGE`, `LONG_CARRY_SURCHARGE`, `VENDOR_PASSTHROUGH`, `DISPOSAL_FEE`, `CONSIGNMENT_CREDIT`, `CONSIGNMENT_REVERSAL`, `COORDINATION_FEE` and `MANUAL_ADJUSTMENT`. Billing may append a manual adjustment directly, supplying `expected_invoice_version` under the optimistic-concurrency rule of §2.10; that append raises the invoice's `version` by one and recomputes `subtotal_cents`, `credits_cents`, `total_cents` and `balance_due_cents`. Lines can be listed and filtered by `invoice_id`, by `source_consignment_lot_id` and by `line_type`; invoices can be listed and filtered by `engagement_id` and by `status`, and since an engagement has exactly one invoice a filtered read returns an array of length one.

The labour line the move-day cascade appends is chosen by the engagement's `billing_mode`, and the two pipelines produce structurally different ledgers from identical crew hours. Under `HOURLY` exactly one `HOURLY_LABOR` line is appended, and its `amount_cents` is the engagement's `accrued_labor_cents` — crew hours times role rates, with the minimum call-out floor and the overtime multiplier already baked in by §3.7, and with no base line and no included allowance anywhere in the picture. Under `PACKAGE` the fixed tier price was already billed at engagement creation, and only the hours beyond the tier's allowance are billed, at a different rate and with no minimum call-out floor: the allowance is 18 hours for `STUDIO`, 26 for `ONE_BED`, 40 for `TWO_BED` and 64 for `HOUSE`, the overage is the engagement's `billing_hours_total` less that allowance, floored at zero, and the charge is that overage multiplied by 8900 cents per hour and rounded half-up to whole cents. The boundary is strict in an unusual way: a `billing_hours_total` exactly equal to the allowance produces **no** `OVERAGE_LABOR` line at all, not a line of amount zero, and an `OVERAGE_LABOR` line is appended only when the computed overage charge is greater than zero. `billing_hours_total` here is the figure that already reflects the billing-view rounding order of §3.7.

Two aggregates partition the ledger. `subtotal_cents` sums `amount_cents` over every line whose `line_type` is **not** `COORDINATION_FEE`, `CONSIGNMENT_CREDIT` or `CONSIGNMENT_REVERSAL`. `credits_cents` sums `amount_cents` over exactly those consignment lines, where credit lines are negative and reversal lines positive. Both sums are order-insensitive.

Issuing the invoice is billing's act, is reachable from `DRAFT`, and requires the engagement's `MOVE_DAY` milestone to be `COMPLETE`. It appends the three site surcharges and then the coordination fee, and recomputes `subtotal_cents`, `coordination_fee_cents`, `credits_cents`, `total_cents` and `balance_due_cents` in that pinned order, stamping `issued_at_utc`.

The travel surcharge is marginal, not average. The first fifteen miles of the engagement's `mileage_miles` are free. The miles from there up to forty are charged at 317 cents each — that is, the lesser of the mileage and forty, less fifteen, floored at zero. Every mile beyond forty is charged at 486 cents — the mileage less forty, floored at zero. Each band is rounded half-up to whole cents separately and the two results are then added.

The stairs surcharge charges only the flights past the first: the engagement's `origin_stairs_flights` less one, floored at zero. Each billable flight costs 2500 cents *per crew member*, multiplied by the move-day plan's `crew_confirmed_count` at issue time, or by zero when the engagement has no plan.

The long-carry surcharge charges in blocks. The first seventy-five feet of `origin_long_carry_feet` are free; the excess beyond that, floored at zero, is divided by twenty-five and rounded **up** to a whole number of blocks, each block costing 1800 cents. Exactly seventy-five feet therefore yields nothing, while seventy-six feet yields one full block.

Under the package pipeline a deposit schedule is derived from the contracted amount — the package base charge plus the travel, stairs and long-carry surcharges. Thirty percent of that contracted amount, rounded half-up to whole cents, falls due at signing; forty percent, rounded the same way, falls due at pack start; and the close-out instalment is the contracted amount less those two, so the last bucket absorbs the rounding remainder and the three buckets always sum exactly to the contracted amount. The close-out instalment is a residual, never an independent percentage. The schedule surfaces through the engagement summary as part of `projected_total_cents`.

The coordination fee looks circular and is not, because its evaluation order is pinned. First `subtotal_cents` is computed from the lines, excluding any coordination-fee line already present. Second the tier is keyed on that pre-fee `subtotal_cents`, never on `total_cents`: a subtotal of at most 300000 cents takes a cap of 18000, a subtotal above that but at most 800000 takes a cap of 42000, and anything above 800000 takes a cap of 75000. Third the fee is six percent of the subtotal, rounded half-up to whole cents, capped at the tier's cap. Fourth `total_cents` is the subtotal plus the fee plus `credits_cents`, so credits are applied **after** the fee and never influence the tier. Because the caps are flat, the fee is not monotone across the tier-two boundary: a subtotal of 800000 pays 42000 while a subtotal of 800001 pays 48000. `balance_due_cents` is `total_cents` less `payments_cents`, and may be negative when the client has overpaid.

Recording a payment supplies an `amount_cents` and a `paid_on` date; it recomputes `payments_cents`, then `balance_due_cents`, then the engagement's `billing_hold`, and raises the invoice's `version` by one.

Three cycles hang off `ISSUED`. Billing may recall the invoice to `DRAFT` with a `reason`, but only while `payments_cents` is exactly zero and `recall_count` is below two; the recall raises `recall_count` and removes the `COORDINATION_FEE` line that issuing had appended. The client, a power of attorney or a family member may dispute it, supplying a `reason` stored as `dispute_reason` and a `raised_by_party_id` that must resolve to a seat on the engagement; the dispute raises `dispute_count` and is capped at two, with the recall and dispute caps both reported through `ERR_INVOICE_ACTION_LIMIT`. Billing then resolves the dispute with a `resolution`, returning the invoice to `ISSUED` and clearing `dispute_reason` to null.

Finalisation is terminal. It is reachable from `ISSUED`, requires `balance_due_cents` to be less than or equal to zero — otherwise `ERR_BALANCE_OUTSTANDING` — and requires that no consignment lot of the engagement sits in `SOLD` or `SETTLED` with `credited` true and `reversed` false pending a return. It stamps `finalized_at_utc`, and from that instant the ninth gate is closed for the whole engagement: no ledger line may be appended, no payment recorded, no dispute raised, no recall taken, and no consignment settlement, reversal, disposal fee or vendor payout may post.

Closing out the engagement is the move manager's final act and takes a `signed_off_by_party_id`. It requires the engagement to be `ACTIVE`, the `CLOSE_OUT` milestone to be `COMPLETE`, no punch-list item to be `OPEN` or `REOPENED`, and `billing_hold` to be false; a failure on any of those reports `ERR_CLOSE_OUT_BLOCKED`. On success it stamps `closed_at_utc` from the logical clock, releases the remaining holdback on every vendor assignment of the engagement in status `SIGNED_OFF` by setting `holdback_released` to true and `paid_cents` to the full `quoted_cents`, and cascades the invoice from `ISSUED` to `FINALIZED` — where the invoice is already `FINALIZED` that cascade is a no-op and close-out still succeeds. The engagement's `version` rises by one and its `status` becomes `CLOSED`.

## 4. Endpoint Definitions

The API is mounted at the root. Endpoints that bring a new resource into existence answer 201 Created; every other successful call answers 200 OK, including the action endpoints that drive a state machine and the computed reads. Every successful mutation returns the affected resource in `data` unless the endpoint's own description says otherwise. The table below is a directory only: request payloads, response side effects and the conditions under which each call is refused are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Sets the server's logical clock. Before any call to this endpoint the logical clock reads exactly 2026-05-01T00:00:00.000Z and never falls back to real wall-clock time. | `PLATFORM_ADMIN`, `MOVE_MANAGER` |
| POST | `/clients` | Registers a senior client. | `MOVE_MANAGER` |
| GET | `/clients/{id}` | Reads one client. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT` |
| POST | `/engagements` | Opens a move engagement for a client and lays down its timeline and ledger. | `MOVE_MANAGER` |
| GET | `/engagements` | Lists engagements with filters. | `MOVE_MANAGER`, `BILLING_ADMIN`, `PLATFORM_ADMIN`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/engagements/{id}` | Reads one engagement including its derived phase, rollups and version. | `MOVE_MANAGER`, `BILLING_ADMIN`, `PLATFORM_ADMIN`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `CREW_LEAD` |
| PATCH | `/engagements/{id}` | Adjusts schedule, surcharge inputs or package tier. | `MOVE_MANAGER` |
| POST | `/engagements/{id}/hold` | Places the engagement ON_HOLD. | `MOVE_MANAGER` |
| POST | `/engagements/{id}/resume` | Returns an ON_HOLD engagement to ACTIVE. | `MOVE_MANAGER` |
| POST | `/engagements/{id}/cancel` | Cancels the engagement and its open vendor work. | `MOVE_MANAGER` |
| POST | `/engagements/{id}/close-out` | Closes the engagement, releases remaining vendor holdbacks and finalises the invoice. | `MOVE_MANAGER` |
| POST | `/engagements/{id}/ops-run` | Ops-run checkpoint: latches milestone overdue status, expires authority records past their window, and moves SCHEDULED vendor assignments whose COI now expires before their service date into COI_BLOCKED. | `MOVE_MANAGER`, `PLATFORM_ADMIN` |
| GET | `/engagements/{id}/summary` | Computed read of the engagement's derived state. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/portal-parties` | Adds a seat to the family portal. | `MOVE_MANAGER` |
| GET | `/portal-parties` | Lists portal parties. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/portal-parties/{id}` | Reads one portal party including its derived approval capability. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/authority-records` | Records a delegated authority for a portal party. | `MOVE_MANAGER` |
| GET | `/authority-records` | Lists authority records. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| GET | `/authority-records/{id}` | Reads one authority record. | `MOVE_MANAGER`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/authority-records/{id}/activate` | Activates a pending authority. | `MOVE_MANAGER` |
| POST | `/authority-records/{id}/suspend` | Suspends an active authority. | `MOVE_MANAGER` |
| POST | `/authority-records/{id}/reinstate` | Returns a suspended authority to ACTIVE. | `MOVE_MANAGER` |
| POST | `/authority-records/{id}/revoke` | Revokes an authority irreversibly. | `MOVE_MANAGER`, `CLIENT` |
| POST | `/destination-residences` | Registers the destination residence for an engagement. | `MOVE_MANAGER` |
| GET | `/destination-residences` | Lists destination residences. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/destination-residences/{id}` | Reads one destination residence. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/destination-residences/{id}/propose-placement` | Moves the furniture placement plan to PROPOSED. | `MOVE_MANAGER` |
| POST | `/destination-residences/{id}/approve-placement` | Approves the placement plan, unlocking full room capacity plus addenda. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/destination-residences/{id}/revise-placement` | Sends the placement plan back to DRAFT from PROPOSED or APPROVED. | `MOVE_MANAGER` |
| POST | `/destination-rooms` | Adds a room to a destination residence. | `MOVE_MANAGER` |
| GET | `/destination-rooms` | Lists rooms. Default ordering is created_at ascending. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/destination-rooms/{id}` | Reads one room including its capacity, load and headroom. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/inventory-items` | Catalogues one household item. | `MOVE_MANAGER` |
| GET | `/inventory-items` | Lists inventory items with filters. Default ordering is created_at ascending. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `CREW_LEAD` |
| GET | `/inventory-items/{id}` | Reads one inventory item. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `CREW_LEAD` |
| POST | `/inventory-items/{id}/designate` | Sets or changes the sort disposition, optionally placing the item in a destination room. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/inventory-items/{id}/appraise` | Records a value and its provenance, selecting the donation receipt variant. | `MOVE_MANAGER` |
| POST | `/inventory-items/{id}/advance-handling` | Advances the physical handling axis along the KEEP branch or the disposal branch. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/family-holds` | Raises a family dispute hold on an item, blocking its re-designation. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/family-holds` | Lists family holds. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/family-holds/{id}` | Reads one family hold. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/family-holds/{id}/escalate` | Escalates an open hold to the move manager. | `MOVE_MANAGER`, `FAMILY_MEMBER` |
| POST | `/family-holds/{id}/remand` | Sends an escalated hold back to the family for discussion. | `MOVE_MANAGER` |
| POST | `/family-holds/{id}/resolve` | Resolves a hold either by forcing the item to KEEP or by releasing it. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/family-holds/{id}/withdraw` | The raising party withdraws its own hold. | `MOVE_MANAGER`, `FAMILY_MEMBER` |
| POST | `/sort-plans` | Creates a sort plan, superseding the engagement's prior DRAFT or REJECTED plan. | `MOVE_MANAGER` |
| GET | `/sort-plans` | Lists sort plans. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/sort-plans/{id}` | Reads one sort plan. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/sort-plans/{id}/submit` | Submits the sort plan for family approval. | `MOVE_MANAGER` |
| POST | `/sort-plans/{id}/approve` | Approves the sort plan; this is the disposition freeze point. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/sort-plans/{id}/reject` | Rejects a submitted sort plan. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/sort-plans/{id}/reopen` | Reopens a rejected or approved plan back to DRAFT, unlocking dispositions. | `MOVE_MANAGER` |
| POST | `/move-day-plans` | Creates the move-day plan for an engagement. | `MOVE_MANAGER` |
| GET | `/move-day-plans` | Lists move-day plans. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/move-day-plans/{id}` | Reads one move-day plan including its version, trip counts and crew rollups. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/move-day-plans/{id}/confirm` | Confirms a fully crewed plan. | `MOVE_MANAGER` |
| POST | `/move-day-plans/{id}/recrew` | Returns a confirmed plan to DRAFT for roster changes. | `MOVE_MANAGER` |
| POST | `/move-day-plans/{id}/freeze` | Enters the move-day freeze window and freezes the sort plan. | `MOVE_MANAGER` |
| POST | `/move-day-plans/{id}/start` | Starts move day. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/move-day-plans/{id}/complete` | Completes move day and runs the six-hop labour and billing cascade. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/move-day-plans/{id}/reschedule` | Reschedules move day, shifting dependent vendor service dates. | `MOVE_MANAGER` |
| POST | `/crew-members` | Registers a crew member with a role rate. | `PLATFORM_ADMIN` |
| GET | `/crew-members/{id}` | Reads one crew member. | `PLATFORM_ADMIN`, `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/crew-assignments` | Assigns a crew member to a move-day plan, optionally replacing a NO_SHOW slot. | `MOVE_MANAGER` |
| GET | `/crew-assignments` | Lists crew assignments. Default ordering is created_at ascending. | `MOVE_MANAGER`, `CREW_LEAD`, `BILLING_ADMIN` |
| GET | `/crew-assignments/{id}` | Reads one crew assignment including both hour variants. | `MOVE_MANAGER`, `CREW_LEAD`, `BILLING_ADMIN` |
| POST | `/crew-assignments/{id}/confirm` | Crew member confirms the assignment; may bubble the plan up to CREWED. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/crew-assignments/{id}/check-in` | Clocks the crew member in. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/crew-assignments/{id}/check-out` | Clocks the crew member out, creating the LABOR time entry and rolling up hours and money. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/crew-assignments/{id}/no-show` | Marks the assignment a no-show. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/time-entries` | Adds a labour, travel or break interval to a crew assignment. Permitted only while the parent CrewAssignment is CHECKED_IN or COMPLETED; on a COMPLETED assignment every hour and money rollup is recomputed in place. | `MOVE_MANAGER`, `CREW_LEAD` |
| GET | `/time-entries` | Lists time entries. Default ordering is created_at ascending. | `MOVE_MANAGER`, `CREW_LEAD`, `BILLING_ADMIN` |
| GET | `/time-entries/{id}` | Reads one time entry including both hour representations. | `MOVE_MANAGER`, `CREW_LEAD`, `BILLING_ADMIN` |
| POST | `/time-entries/{id}/void` | Voids a time entry and reverses its contribution to every rollup. | `MOVE_MANAGER`, `BILLING_ADMIN` |
| POST | `/vendors` | Registers a subcontract vendor with its COI, capacity and holdback. | `PLATFORM_ADMIN` |
| GET | `/vendors/{id}` | Reads one vendor. | `PLATFORM_ADMIN`, `MOVE_MANAGER`, `VENDOR`, `BILLING_ADMIN` |
| POST | `/vendors/{id}/renew-coi` | Renews the vendor's certificate of insurance and unblocks its COI_BLOCKED assignments. | `PLATFORM_ADMIN`, `VENDOR` |
| POST | `/vendor-assignments` | Orders a service from a vendor for an engagement. | `MOVE_MANAGER` |
| GET | `/vendor-assignments` | Lists vendor assignments. | `MOVE_MANAGER`, `VENDOR`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| GET | `/vendor-assignments/{id}` | Reads one vendor assignment. | `MOVE_MANAGER`, `VENDOR`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/vendor-assignments/{id}/accept` | Vendor accepts the order and the holdback is computed. | `VENDOR` |
| POST | `/vendor-assignments/{id}/schedule` | Schedules the accepted order against the vendor's COI and daily capacity. | `MOVE_MANAGER` |
| POST | `/vendor-assignments/{id}/perform` | Vendor records performance; the interim payout posts and a pass-through invoice line is appended. | `VENDOR`, `MOVE_MANAGER` |
| POST | `/vendor-assignments/{id}/sign-off` | Client side signs off completion, releasing the holdback. | `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/vendor-assignments/{id}/pay` | Billing marks the subcontract paid. | `BILLING_ADMIN` |
| POST | `/vendor-assignments/{id}/cancel` | Cancels a vendor order before performance. | `MOVE_MANAGER`, `VENDOR` |
| POST | `/consignment-lots` | Consigns a set of SELL items to a consignment vendor. | `MOVE_MANAGER` |
| GET | `/consignment-lots` | Lists consignment lots. | `MOVE_MANAGER`, `VENDOR`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| GET | `/consignment-lots/{id}` | Reads one lot including its settlement arithmetic. | `MOVE_MANAGER`, `VENDOR`, `BILLING_ADMIN`, `CLIENT`, `POWER_OF_ATTORNEY` |
| POST | `/consignment-lots/{id}/mark-down` | Applies the next markdown round off the ORIGINAL list price. | `MOVE_MANAGER`, `VENDOR` |
| POST | `/consignment-lots/{id}/record-sale` | Records a sale and computes commission, fees and net proceeds. | `VENDOR`, `MOVE_MANAGER` |
| POST | `/consignment-lots/{id}/settle` | Credits the net proceeds against the client invoice. | `MOVE_MANAGER`, `BILLING_ADMIN` |
| POST | `/consignment-lots/{id}/declare-unsold` | Declares the lot unsold once the listing window has elapsed. | `MOVE_MANAGER`, `VENDOR` |
| POST | `/consignment-lots/{id}/return-to-client` | Returns the lot to the client, reversing any credit already posted. | `MOVE_MANAGER` |
| POST | `/consignment-lots/{id}/haul-away` | Hauls an unsold or returned lot away and charges the disposal fee. | `MOVE_MANAGER` |
| GET | `/invoices` | Lists invoices. Default ordering is created_at ascending; an engagement has exactly one invoice, so a filtered read returns an array of length 1. | `BILLING_ADMIN`, `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY`, `FAMILY_MEMBER` |
| GET | `/invoices/{id}` | Reads one invoice including every computed aggregate and its version. | `BILLING_ADMIN`, `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY`, `FAMILY_MEMBER` |
| POST | `/invoices/{id}/issue` | Issues the invoice, computing surcharges and the coordination fee in the pinned order. | `BILLING_ADMIN` |
| POST | `/invoices/{id}/recall` | Recalls an issued invoice to DRAFT. | `BILLING_ADMIN` |
| POST | `/invoices/{id}/dispute` | The client side disputes the issued invoice. | `CLIENT`, `POWER_OF_ATTORNEY`, `FAMILY_MEMBER` |
| POST | `/invoices/{id}/resolve-dispute` | Billing resolves the dispute and returns the invoice to ISSUED. | `BILLING_ADMIN` |
| POST | `/invoices/{id}/finalize` | Finalises the invoice; gate 9 closes for the whole engagement. | `BILLING_ADMIN` |
| POST | `/invoices/{id}/record-payment` | Records a client payment against the invoice. | `BILLING_ADMIN` |
| POST | `/invoice-lines` | Appends a manual adjustment line to a DRAFT or ISSUED invoice under optimistic concurrency. | `BILLING_ADMIN` |
| GET | `/invoice-lines` | Lists ledger lines. Default ordering is created_at ascending. | `BILLING_ADMIN`, `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| GET | `/invoice-lines/{id}` | Reads one immutable ledger line. | `BILLING_ADMIN`, `MOVE_MANAGER`, `CLIENT`, `POWER_OF_ATTORNEY` |
| GET | `/milestones` | Lists the engagement's timeline milestones. Default ordering is sequence_index ascending, so index 0 is ASSESSMENT and index 5 is CLOSE_OUT. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `BILLING_ADMIN` |
| GET | `/milestones/{id}` | Reads one milestone including both its progress and lateness axes. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY`, `BILLING_ADMIN` |
| POST | `/milestones/{id}/complete` | Completes a milestone and starts its successor. | `MOVE_MANAGER` |
| POST | `/milestones/{id}/reopen` | Reopens a completed milestone, moving the phase backwards. | `MOVE_MANAGER` |
| POST | `/unpack-sessions` | Schedules a settle-in unpack session. | `MOVE_MANAGER` |
| GET | `/unpack-sessions` | Lists unpack sessions. Default ordering is created_at ascending. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/unpack-sessions/{id}` | Reads one unpack session. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/unpack-sessions/{id}/start` | Starts a scheduled or reopened session, honouring the essentials-first rule. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/unpack-sessions/{id}/complete` | Completes the session. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/punch-list-items` | Raises a settle-in defect with an SLA window. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/punch-list-items` | Lists punch-list items. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| GET | `/punch-list-items/{id}` | Reads one punch-list item. | `MOVE_MANAGER`, `CREW_LEAD`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |
| POST | `/punch-list-items/{id}/resolve` | Resolves the defect. | `MOVE_MANAGER`, `CREW_LEAD` |
| POST | `/punch-list-items/{id}/reopen` | Reopens a resolved defect, reopening its unpack session and the close-out milestone. | `MOVE_MANAGER`, `CLIENT`, `FAMILY_MEMBER`, `POWER_OF_ATTORNEY` |

## 5. Error Code Catalogue

Every error response carries one of the following identifiers in `data.error_id` together with the HTTP status shown. The condition that triggers each one is stated in the narrative of §2 and §3, most of them at the ladder rung that owns them.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_AUTH_HEADER` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_MISSING_USER_ID` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 |
| `ERR_CLIENT_NOT_FOUND` | 404 |
| `ERR_PARTY_NOT_FOUND` | 404 |
| `ERR_AUTHORITY_NOT_FOUND` | 404 |
| `ERR_RESIDENCE_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_ITEM_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_CREW_RECORD_NOT_FOUND` | 404 |
| `ERR_VENDOR_RECORD_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_TIMELINE_RECORD_NOT_FOUND` | 404 |
| `ERR_ENGAGEMENT_CLOSED` | 409 |
| `ERR_ENGAGEMENT_CANCELLED` | 409 |
| `ERR_ENGAGEMENT_ON_HOLD` | 409 |
| `ERR_ACTOR_NOT_OWNER` | 403 |
| `ERR_PARTY_ENGAGEMENT_MISMATCH` | 422 |
| `ERR_NO_ACTIVE_AUTHORITY` | 403 |
| `ERR_AUTHORITY_SCOPE_INSUFFICIENT` | 403 |
| `ERR_HIGH_VALUE_AUTHORITY_REQUIRED` | 403 |
| `ERR_AUTHORITY_CEILING_EXCEEDED` | 403 |
| `ERR_PHASE_NOT_PERMITTED` | 409 |
| `ERR_PREDECESSOR_MILESTONE_INCOMPLETE` | 409 |
| `ERR_SUCCESSOR_MILESTONE_COMPLETE` | 409 |
| `ERR_CLOSE_OUT_BLOCKED` | 409 |
| `ERR_FREEZE_WINDOW_ENTERED` | 409 |
| `ERR_SORT_PLAN_FROZEN` | 409 |
| `ERR_FREEZE_WINDOW_NOT_ENTERED` | 409 |
| `ERR_DISPOSITION_LOCKED` | 409 |
| `ERR_ITEM_UNDER_FAMILY_HOLD` | 409 |
| `ERR_ITEM_ALREADY_CONSIGNED` | 409 |
| `ERR_VENDOR_TYPE_MISMATCH` | 422 |
| `ERR_VENDOR_COI_EXPIRED` | 422 |
| `ERR_VENDOR_DAILY_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVOICE_FINALIZED` | 409 |
| `ERR_BILLING_CLOSED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_INVALID_SALE_PRICE` | 422 |
| `ERR_UNDECIDED_ITEMS_REMAIN` | 422 |
| `ERR_NO_INVENTORY` | 422 |
| `ERR_LOT_ALREADY_CREDITED` | 409 |
| `ERR_UNSOLD_WINDOW_NOT_ELAPSED` | 409 |
| `ERR_ESSENTIALS_SESSION_PENDING` | 409 |
| `ERR_AUTHORITY_WINDOW_INVALID` | 409 |
| `ERR_SORT_PLAN_REOPEN_LIMIT` | 409 |
| `ERR_RESCHEDULE_LIMIT` | 409 |
| `ERR_MARKDOWN_ROUNDS_EXHAUSTED` | 409 |
| `ERR_REOPEN_LIMIT` | 409 |
| `ERR_INVOICE_ACTION_LIMIT` | 409 |
| `ERR_HOLD_ESCALATION_LIMIT` | 409 |
| `ERR_STALE_ENGAGEMENT_VERSION` | 412 |
| `ERR_STALE_MOVE_DAY_PLAN_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_PACKAGE_TIER_REQUIRED` | 422 |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 422 |
| `ERR_ROOM_VOLUME_EXCEEDED` | 422 |
| `ERR_ITEM_BELOW_CONSIGN_MINIMUM` | 422 |
| `ERR_CREW_MINIMUM_NOT_MET` | 422 |
| `ERR_CREW_LEAD_REQUIRED` | 422 |
| `ERR_BALANCE_OUTSTANDING` | 409 |

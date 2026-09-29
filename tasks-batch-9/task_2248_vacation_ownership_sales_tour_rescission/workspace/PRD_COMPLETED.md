# Vacation Ownership Sales Tour & Rescission API — Product Requirements Document

## 1. Introduction

Timeshare and vacation-ownership selling is one of the most heavily regulated retail motions in the hospitality industry. A single sale touches marketing channels that hand out incentive gifts to attract prospects, a physical sales gallery with finite tour capacity, a licensed representative working a rotation, a recorded presentation that must include statutory disclosures and must exclude prohibited claims, a purchase agreement with a jurisdiction-specific statutory cancellation window, an escrow balance, a lender, a county recorder, and — when the purchaser changes their mind inside the window — a refund obligation that in some states cannot be reduced by so much as a single cent. Today these steps live in disconnected spreadsheets and channel-specific tools, which is exactly why cancellation exposure is discovered weeks after it accrues and why unlicensed claims surface only in regulator complaints.

This API is the system of record for that entire motion. It governs tour generation and qualification, gallery capacity and representative rotation, presentation compliance scoring, purchase-agreement execution and financing, statutory rescission administration with full-refund settlement, contract funding and instrument recording, and the back-end analytics that force a representative into compliance retraining when their cancellation rate or prohibited-claim history breaches policy. Every entity is a peer top-level collection; there is no single owning aggregate root, and consequently no shared URL prefix. Two append-only event collections — recorded disclosure acknowledgments and prohibited-claim findings — are additionally readable as sub-resource projections of the presentation they belong to.

Two design commitments run through the whole specification and should be read as non-negotiable. First, **compliance gates are hard gates**: a presentation that has not been cleared cannot produce an agreement, an agreement whose rescission window is still running cannot be funded, and an officer who accused a presentation cannot then absolve it. Second, **money is conserved exactly**: escrow collected at execution equals the amount disbursed on rescission plus the amount lawfully retained, with no rounding drift anywhere in between.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint. Where a rule here appears again inside a §3 workflow narrative, the two statements are reinforcing, never competing.

### 2.1. User Identity and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity they act in. If either header is absent or blank, or if `X-User-Role` is not one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well formed but the named role is not authorised for the target operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are non-overlapping duty holders:

- `MarketingManager` — owns tour generation: channels, incentive-gift configuration, prospect intake, and the tour schedule.
- `GalleryManager` — owns gallery capacity, the representative roster and rotation, and performs tour check-in.
- `SalesRepresentative` — conducts the presentation, records disclosure acknowledgments, executes purchase agreements, and submits financing applications, but only for their own tours.
- `ComplianceOfficer` — files prohibited-claim findings, issues review decisions, and administers compliance retraining.
- `ContractAdministrator` — underwrites financing, funds contracts, records and delivers closing documents, and administers rescission intake, adjudication and refunds.
- `PlatformAdmin` — operates the logical clock and the rescission sweep epoch, and holds no business write authority at all. That restriction is deliberate: the operator who can move time forward must not also be able to move contracts forward.

Identity binding differs by role, and the difference is load-bearing. When `X-User-Role` is `SalesRepresentative`, `X-User-ID` is the `id` of the acting `SalesRepresentative` record; ownership checks on any resource that references a representative compare the resource's representative reference to `X-User-ID` — specifically a booking's `assigned_rep_id`, a presentation's `rep_id`, and an agreement's `rep_id`. A mismatch is rejected with `ERR_REPRESENTATIVE_MISMATCH` (HTTP 403).

When `X-User-Role` is `MarketingManager`, `GalleryManager`, `ComplianceOfficer`, `ContractAdministrator` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow demands an audit trail — as `reported_by_user_id` on a prohibited-claim finding, `reviewed_by_user_id` on a presentation, `decided_by_user_id` on a financing application, `intake_user_id` and `adjudicated_by_user_id` on a rescission request, and `issued_by_user_id` on a refund disbursement — but it is never compared against any entity's `id`. It is, however, compared against *other recorded operator identifiers* for the two segregation-of-duties prohibitions described in §2.11.

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

### 2.3. Pagination and List Ordering

List endpoints accept two query parameters. `limit` caps the number of records returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` skips a number of leading records and defaults to 0; its minimum accepted value is 0. A `limit` outside the range of 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint says otherwise, every list is sorted by `created_at` in ascending order; because the logical clock only moves when an operator moves it, many records legitimately share a `created_at`, and every remaining tie — in a list, in a pinned cascade ordering, or in the rotation chain — is broken last by the order in which the records were created within the process. List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object, where `total_count` counts every record matching the supplied filters before pagination is applied and `has_more` is true exactly when records matching the filters remain beyond the current page.

### 2.4. Resource Identity, Timestamps and Versioning

Ordinary resources — tour channels, sales galleries, sales representatives, prospects, tour bookings, sales presentations, purchase agreements, financing applications, rescission requests, refund disbursements, closing packages and compliance retraining assignments — carry four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix and no embedded semantics; the rotation tie-break chain described in §3.5 deliberately never consults it.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, fixed when the record is first written.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the record, including mutations caused by a cascade the client did not request directly.
- `version` (integer): an integer that starts at 1 and increments by one on every mutation of the record. It is the value clients echo back through the stale-version guards of §2.8.

The two append-only event collections are the exception. A recorded disclosure acknowledgment and a prohibited-claim finding each carry only `id` and `created_at`. Neither has an `updated_at` field and neither has a `version` field, because neither is ever modified after it is appended.

### 2.5. The Logical Clock

The system never reads wall-clock time for business decisions. It maintains a logical clock that reads exactly `2026-08-01T00:00:00Z` until it is first set, and every instant the server stamps — `checked_in_at`, `started_at`, `acknowledged_at`, `detected_at`, `executed_at`, `received_at`, `adjudicated_at`, `decided_at`, `funded_at`, `recorded_at`, `documents_delivered_at`, `settled_at`, `assigned_at`, `closed_at`, `last_assigned_at` — is taken from it.

A `PlatformAdmin` moves the clock by supplying a `to_iso8601` instant. The clock may only advance: a requested value earlier than the current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422). Setting the clock to a value equal to the current value is permitted. The response reports `current_utc` (the clock after the call) and `previous_utc` (the clock before it), and no entity state changes as a result.

### 2.6. Numeric Precision and Rounding Discipline

Three families of numbers live in this system, and each has its own discipline.

**Money** is always expressed in whole cents as an integer. Wherever a monetary result is derived from a rate, the result is rounded to a whole cent using round-half-up. Rounding boundaries are pinned per calculation and are *not* interchangeable: the equity trade-in credit rounds each of its four components to a whole cent before summing them, while the financing amortisation applies exactly one rounding at the very end of its expression. Those pinned orders are restated where each calculation is described, and they are observable in the outputs.

**Rates** derived from counts — a channel's `historical_no_show_rate` and a representative's `cancellation_rate` — are stored to four decimal places using round-half-up. Where the denominator would be zero, the rate is set to `0.0000` by an explicit empty-set branch; a division is never attempted.

**Points** — the tour qualification score and the presentation compliance score — are whole integers. The one place a rate feeds a point total is the tour no-show penalty, which is rounded to a whole point using round-half-up before it is subtracted.

The `max_ltv_rate` published by the underwriting tiers is a rate, not money, and is stored exactly as the tier declares it.

### 2.7. Jurisdictional Rescission Rules and the Business-Day Calendar

The statutory cancellation window is a function of the state of sale. Each agreement's `state_code` selects one row of the following fixed rule table, and that row's values are frozen onto the agreement at execution as `statutory_rescission_days`, `anchor_mode` and `refund_policy`:

| `state_code` | `statutory_rescission_days` | `anchor_mode` | Business-day roll | `refund_policy` |
| --- | --- | --- | --- | --- |
| `FL` | 10 | `LATER_OF_EXECUTION_OR_POS` | yes | `STATUTORY_FULL` |
| `NV` | 5 | `EXECUTION` | no | `STATUTORY_FULL` |
| `CA` | 7 | `LATER_OF_EXECUTION_OR_POS` | yes | `STATUTORY_FULL` |
| `TX` | 6 | `EXECUTION` | no | `CONTRACTUAL_NET_OF_GIFT` |
| `HI` | 7 | `POS_DELIVERY` | yes | `CONTRACTUAL_NET_OF_GIFT` |

The deadline is computed once, at execution, and is thereafter only re-read — never recomputed. The anchor instant, recorded as `rescission_anchor_utc`, is chosen by `anchor_mode`: under `EXECUTION` it is the agreement's `executed_at`; under `POS_DELIVERY` it is the agreement's `pos_delivered_at`; under `LATER_OF_EXECUTION_OR_POS` it is whichever of those two instants is later. The UTC calendar date of the anchor is then advanced by the jurisdiction's number of calendar days. For jurisdictions whose row permits rolling, the resulting date is advanced one day at a time for as long as it falls on a Saturday, falls on a Sunday, or matches a date in the federal-holiday calendar below, and `business_day_rolled` is set to true if at least one such advance occurred; for jurisdictions whose row does not permit rolling, no advance happens and `business_day_rolled` stays false. `rescission_deadline_utc` is that final date at `23:59:59.999Z`.

The consequence is that the same pair of instants produces three different windows. Anchoring on execution ignores a public offering statement delivered days earlier; anchoring on delivery *shortens* the window when the statement went out before signing; anchoring on the later of the two *lengthens* the window when the statement went out after signing.

The federal-holiday calendar is fixed: 2026-07-03, 2026-09-07, 2026-11-26, 2026-12-25, 2027-01-01, 2028-07-04, 2028-09-04, 2028-11-23, 2028-12-25, 2029-01-01, 2029-07-04, 2029-09-03, 2029-11-22, 2029-12-25.

### 2.8. Stale-Version Guards on Dependent Writes

Three creation operations attach a new record to a parent whose state the client must have observed first. Each of them takes a non-optional version field naming the parent version the client last read, and each rejects a mismatch against the parent's current `version`.

- Submitting a financing application (`POST /financing-applications`) requires `expected_agreement_version` to equal the target `PurchaseAgreement`'s current `version`. A mismatch is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412). Product semantics deliberately allow a newer application to supersede a prior one, so no state precondition blocks a second sequential submission; the stale-version guard is the only thing that stops a writer from superseding an approval it never saw. A successful submission itself increments the agreement's `version` by one.
- Filing a prohibited-claim finding (`POST /prohibited-claim-findings`) requires `expected_presentation_version` to equal the target `SalesPresentation`'s current `version`. A mismatch is rejected with `ERR_STALE_PRESENTATION_VERSION` (HTTP 412). Multiple findings on one presentation are legitimate, so no state precondition blocks a second sequential append; the guard is what stops an officer from scoring a presentation whose `compliance_score` already moved beneath them. A successful append increments the presentation's `version` by one.
- Assigning compliance retraining (`POST /retraining-assignments`) requires `expected_representative_version` to equal the target `SalesRepresentative`'s current `version`. A mismatch is rejected with `ERR_STALE_REPRESENTATIVE_VERSION` (HTTP 412). Assignments with distinct trigger reasons may coexist on one representative, so the reason-uniqueness rule does not block a second sequential create; the guard is what stops an officer from assigning against a representative whose strike count or status already changed. A successful create increments the representative's `version` by one.

No other endpoint accepts a version field, and no other endpoint performs a version comparison.

### 2.9. Validation Precedence and Path Resolution

Requests are validated in a single fixed precedence, and the *first* failing check determines the response. Where several checks could fire on one request, the earlier one always wins — a mid-flight compliance problem must not be masked by a later fiscal problem, and vice versa. The order is:

1. Header presence and role recognition — `ERR_UNAUTHENTICATED` (401), on every endpoint.
2. Role authorisation for the target operation — `ERR_UNAUTHORIZED` (403), on every endpoint.
3. Request shape: every required field present, types correct, enum members legal, numeric ranges honoured, `limit` within 1 to 100, `offset` at least 0, and every datetime field a valid ISO 8601 UTC instant — `ERR_INVALID_REQUEST` (400), on every endpoint. An `APPROVE` financing decision on an application whose `applicant_fico` is below 620 is also classified here. The fields that carry no explicit bound in their own workflow narrative are bounded here: a booking `reason` (on `reschedule-requests` and on `cancel`) is a string of 1 to 300 characters; `funding_reference`, `recording_reference`, `recording_jurisdiction` and `settlement_reference` are each strings of 1 to 120 characters; `collected_amount_cents` and `modules_completed` must each be at least 0; and every `expected_*_version` guard field must be an integer of at least 1.
4. Existence of path-parameter resources, validated strictly left to right, yielding HTTP 404 with the code for the *first* identifier in the path that does not resolve: `ERR_CHANNEL_NOT_FOUND`, `ERR_GALLERY_NOT_FOUND`, `ERR_REPRESENTATIVE_NOT_FOUND`, `ERR_PROSPECT_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PRESENTATION_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_FINANCING_APPLICATION_NOT_FOUND`, `ERR_RESCISSION_REQUEST_NOT_FOUND`, `ERR_REFUND_DISBURSEMENT_NOT_FOUND`, `ERR_CLOSING_PACKAGE_NOT_FOUND` or `ERR_RETRAINING_ASSIGNMENT_NOT_FOUND`. Every addressable resource is targeted by a single `{id}` path parameter; the two sub-resource projections resolve the presentation `{id}` before listing their children.
5. Existence of foreign keys supplied in a request body, validated in this declaration order and yielding HTTP 404 for the first one that does not resolve: `channel_id` yields `ERR_CHANNEL_NOT_FOUND`, `prospect_id` yields `ERR_PROSPECT_NOT_FOUND`, `gallery_id` yields `ERR_GALLERY_NOT_FOUND`, `booking_id` yields `ERR_BOOKING_NOT_FOUND`, `presentation_id` yields `ERR_PRESENTATION_NOT_FOUND`, `agreement_id` yields `ERR_AGREEMENT_NOT_FOUND`, `traded_in_agreement_id` also yields `ERR_AGREEMENT_NOT_FOUND`, `rescission_request_id` yields `ERR_RESCISSION_REQUEST_NOT_FOUND`, and `rep_id` yields `ERR_REPRESENTATIVE_NOT_FOUND`.
6. Representative ownership for the entity-backed role — `ERR_REPRESENTATIVE_MISMATCH` (403). This guards exactly five operations: `POST /sales-presentations`, `POST /disclosure-acknowledgments`, `POST /sales-presentations/{id}/complete`, `POST /purchase-agreements` and `POST /financing-applications`.
7. The stale-version guards of §2.8 — `ERR_STALE_AGREEMENT_VERSION`, `ERR_STALE_PRESENTATION_VERSION` or `ERR_STALE_REPRESENTATIVE_VERSION` (412) — on exactly `POST /financing-applications`, `POST /prohibited-claim-findings` and `POST /retraining-assignments`.
8. The target resource is in a state from which the requested transition exists — `ERR_INVALID_BOOKING_STATE`, `ERR_INVALID_PRESENTATION_STATE`, `ERR_INVALID_AGREEMENT_STATE`, `ERR_INVALID_FINANCING_STATE`, `ERR_INVALID_RESCISSION_REQUEST_STATE`, `ERR_INVALID_CLOSING_PACKAGE_STATE` or `ERR_INVALID_RETRAINING_STATE` (409), on every action endpoint.
9. Funding is refused while the statutory window has not expired — `ERR_RESCISSION_PERIOD_ACTIVE` (409), on `POST /purchase-agreements/{id}/fund`.
10. Rescission work is refused once the contract has been funded — `ERR_AGREEMENT_ALREADY_FUNDED` (409), on both `POST /rescission-requests` and `POST /rescission-requests/{id}/adjudicate`.
11. A refund disbursement already exists for the rescission request — `ERR_REFUND_ALREADY_ISSUED` (409), on `POST /refund-disbursements`.
12. Retraining reason uniqueness — `ERR_RETRAINING_ALREADY_ACTIVE` (409), on `POST /retraining-assignments`.
13. The booking's channel must be `ACTIVE` — `ERR_CHANNEL_SUSPENDED` (409). This guards three operations: `POST /tour-bookings`, `POST /tour-bookings/{id}/check-in` and `POST /tour-bookings/{id}/reschedule`.
14. The booking's gallery must be `OPEN`, with both `RESTRICTED` and `CLOSED` refusing — `ERR_GALLERY_NOT_OPEN` (409). This guards the same three operations: `POST /tour-bookings`, `POST /tour-bookings/{id}/check-in` and `POST /tour-bookings/{id}/reschedule`.
15. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES` (403). This guards two operations: `POST /sales-presentations/{id}/review` and `POST /refund-disbursements`.
16. Disclosure completeness — `ERR_DISCLOSURES_INCOMPLETE` (422). This guards two operations: `POST /sales-presentations/{id}/complete` and `POST /purchase-agreements`.
17. Presentation clearance — `ERR_PRESENTATION_NOT_CLEARED` (422). This guards two operations: `POST /purchase-agreements` (the presentation's `review_status` must be `CLEARED`) and `POST /sales-presentations/{id}/review` (a manual clear decision has its own score and severity floor).
18. Public offering statement delivery window — `ERR_POS_NOT_DELIVERED` (422), on `POST /purchase-agreements`.
19. Trade-in ownership match — `ERR_TRADE_IN_OWNER_MISMATCH` (422), on `POST /purchase-agreements`.
20. Trade-in eligibility of the surrendered agreement — `ERR_TRADE_IN_NOT_ELIGIBLE` (409), on `POST /purchase-agreements`. Note that ownership is checked before eligibility.
21. Minimum booking lead time — `ERR_TOUR_SLOT_IN_PAST` (422). This guards two operations: `POST /tour-bookings` and `POST /tour-bookings/{id}/reschedule`.
22. Clock monotonicity — `ERR_CLOCK_NOT_MONOTONIC` (422), on `POST /_clock/set_current_utc`.
23. Channel code uniqueness — `ERR_CHANNEL_CODE_TAKEN` (409), on `POST /tour-channels`.
24. Rotation position uniqueness within a gallery — `ERR_ROTATION_POSITION_TAKEN` (409), on `POST /sales-representatives`.
25. One presentation per booking — `ERR_PRESENTATION_ALREADY_EXISTS` (409), on `POST /sales-presentations`.
26. One acknowledgment per disclosure code per presentation — `ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED` (409), on `POST /disclosure-acknowledgments`.
27. One agreement per presentation — `ERR_AGREEMENT_ALREADY_EXISTS` (409), on `POST /purchase-agreements`.
28. Reschedule cycle cap — `ERR_RESCHEDULE_LIMIT_EXCEEDED` (409), on `POST /tour-bookings/{id}/reschedule-requests`.
29. Gallery concurrent-capacity overlap — `ERR_GALLERY_CAPACITY_EXCEEDED` (409). This guards two operations: `POST /tour-bookings` and `POST /tour-bookings/{id}/reschedule`.
30. A non-empty representative candidate pool — `ERR_NO_ELIGIBLE_REPRESENTATIVE` (409), on `POST /tour-bookings/{id}/check-in`.
31. The channel's three hard minimum criteria — `ERR_PROSPECT_BELOW_MINIMUM_CRITERIA` (422), on `POST /tour-bookings`.
32. The channel's minimum qualification score — `ERR_PROSPECT_NOT_QUALIFIED` (422), on `POST /tour-bookings`. Hard criteria are therefore always evaluated before the scored threshold.
33. Retraining module shortfall on a completing close — `ERR_MODULE_COUNT_SHORTFALL` (422), on `POST /retraining-assignments/{id}/close`.
34. Down-payment sufficiency — `ERR_DOWN_PAYMENT_INSUFFICIENT` (422), on `POST /purchase-agreements`.
35. An approved financing application exists for a financed agreement — `ERR_FINANCING_NOT_APPROVED` (409), on `POST /purchase-agreements/{id}/fund`.
36. The approved amount covers the financed amount — `ERR_FINANCING_AMOUNT_SHORTFALL` (422), on `POST /purchase-agreements/{id}/fund`.
37. The collected amount equals the financed amount exactly — `ERR_FUNDING_AMOUNT_MISMATCH` (422), on `POST /purchase-agreements/{id}/fund`.

### 2.10. Cascades, Derived Counters and Posture Re-Derivation

Several operations mutate more than the resource named in the request, and the secondary mutations are part of the contract, not an implementation detail. Every entity touched by a cascade has its `updated_at` refreshed and its `version` incremented, exactly as if it had been the direct target. A recomputation that lands on the value already stored is not a mutation, however: when a derived counter, a posture, a rate or any other field is recomputed to exactly what it already held, that record's `updated_at` and `version` are left untouched — which is why an idempotent request such as closing an already-`CLOSED` gallery, or reinstating an already-`ACTIVE` channel whose counters are already 0, succeeds without advancing any version. Cascades are always applied immediately and synchronously within the triggering request; there is no deferred reconciliation anywhere in this system.

Two counters are derived by full recomputation rather than by incremental adjustment, which is what makes their compensating behaviour exact. A gallery's `booked_slot_count` is recomputed as the number of bookings at that gallery whose `status` is `SCHEDULED`, `RESCHEDULE_PENDING`, `CHECKED_IN` or `TOURED`; bookings in `NO_SHOW` and `CANCELLED` are excluded. A channel's `gift_liability_cents` is recomputed as the sum of `gift_value_cents` over that channel's bookings that have `gift_issued` set to true and whose `status` is `CHECKED_IN` or `TOURED`; bookings in `CANCELLED`, `NO_SHOW`, `SCHEDULED` and `RESCHEDULE_PENDING` contribute nothing.

A gallery's posture is likewise derived, not stored by hand. A gallery's `available_rep_count` is the number of representatives whose `gallery_id` names that gallery and whose `status` is `ACTIVE` or `ON_TOUR`. Whenever `available_rep_count` changes, the posture is re-derived: an `OPEN` gallery whose count has reached 0 becomes `RESTRICTED`, and a `RESTRICTED` gallery whose count has reached at least 1 becomes `OPEN`. A `CLOSED` gallery is never re-derived by this rule — only an explicit posture request lifts it, and even then the result is re-derived from the count.

Where an operation cascades across a *set* of sibling records, the processing order is pinned so that observable side effects are deterministic. Bookings cancelled by a channel suspension are processed in `created_at` ascending order; financing applications superseded by a newer submission, or cancelled by an agreement void, are processed in `created_at` ascending order; agreements swept into an expired rescission status are processed in `executed_at` ascending order, with `created_at` ascending as the tie-break.

### 2.11. Segregation of Duties

Two same-person prohibitions are enforced on `X-User-ID`, and both return `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

A `ComplianceOfficer` who filed any prohibited-claim finding against a presentation may not then issue a review decision on that presentation — the comparison is between the acting `X-User-ID` and the `reported_by_user_id` of every finding on that presentation, and the prohibition applies to both a clearing and a flagging decision. Separately, the `ContractAdministrator` who adjudicated a rescission request may not issue the refund disbursement for it — the comparison is between the acting `X-User-ID` and the request's `adjudicated_by_user_id`.

## 3. Business Logic & Workflows

### 3.1. Tour Generation Channels and No-Show Probation

Every tour begins with a channel. A `MarketingManager` registers one by supplying a `name` of 1 to 120 characters, a `channel_code`, an `incentive_gift_value_cents` amount, and the three hard qualification minimums plus a scored floor: `min_age`, `min_household_income_cents` and `min_qualification_score`. The channel classification `channel_code` is one of `OFF_PROPERTY_CONTACT`, `IN_HOUSE_REFERRAL`, `MINI_VAC_PACKAGE`, `TELEMARKETING` or `OWNER_UPGRADE`, and it must be globally unique — a second channel claiming a code already in use is rejected with `ERR_CHANNEL_CODE_TAKEN`. The gift value is a cents amount from 0 through 100000 inclusive, `min_age` runs from 18 through 99 inclusive, `min_household_income_cents` must be at least 0, and `min_qualification_score` runs from 0 through 100 inclusive. An optional `requires_married_household` flag defaults to false; when it is set, only married households may be booked on the channel.

A freshly registered channel opens in `status` `ACTIVE` with `booked_count`, `toured_count`, `no_show_count` and `gift_liability_cents` all at 0, and `historical_no_show_rate` at `0.0000` — the latter arriving through the empty-denominator branch rather than through any division.

The no-show rate is the channel's reputation metric, and its arithmetic is deliberately narrow. Its denominator is the sum of `toured_count` and `no_show_count`; bookings sitting in `SCHEDULED`, `RESCHEDULE_PENDING`, `CHECKED_IN` or `CANCELLED` contribute to neither counter and therefore to neither side of the ratio. When the denominator is 0 the rate is `0.0000`. Otherwise the rate is `no_show_count` divided by that denominator, rounded half-up to four decimal places. It is recomputed on exactly three occasions: when a booking is marked a no-show, when a presentation completes and moves its booking to `TOURED`, and when a suspended channel is reinstated.

Probation is what gives the metric teeth. Immediately after a no-show pushes `no_show_count` up and the rate is recomputed, the system checks three conditions together: `booked_count` has reached at least 4, the recomputed `historical_no_show_rate` has reached at least `0.5000`, and the channel is currently `ACTIVE`. When all three hold, the channel moves `ACTIVE → SUSPENDED`. Note that the sample gate reads `booked_count`, the lifetime count of bookings ever created against the channel, which is never decremented — not the rate's denominator.

Suspension is not a quiet flag. Every booking on the suspended channel whose `status` is `SCHEDULED` or `RESCHEDULE_PENDING` is transitioned to `CANCELLED` with `cancel_reason` set to the literal string `CHANNEL_SUSPENDED`, processed in `created_at` ascending order; then, for every gallery touched by those cancellations, `booked_slot_count` is recomputed. A suspended channel refuses new bookings, refuses check-in, and refuses a reschedule commit, each with `ERR_CHANNEL_SUSPENDED`.

Reinstating a channel is the `MarketingManager`'s probation reset. It moves `SUSPENDED → ACTIVE` — the endpoint carries no state gate at all, so it is also accepted on a channel that is already `ACTIVE`, where it simply re-zeroes the same counters — resets `toured_count` and `no_show_count` to 0, and recomputes `historical_no_show_rate` to `0.0000` through the empty-denominator branch. `booked_count` is deliberately *not* reset, so the sample gate stays armed and a channel that misbehaves again re-suspends as soon as its post-reinstatement rate reaches the threshold. Bookings already cancelled by the suspension are not revived.

Alongside the raw record, the channel exposes a computed no-show summary read that echoes `channel_id`, the channel `status`, `booked_count`, `toured_count`, `no_show_count`, the `denominator` actually used for the ratio, `historical_no_show_rate`, the outstanding `gift_liability_cents`, and a `suspend_threshold_met` boolean that is true exactly when `booked_count` has reached at least 4 and the rate has reached at least `0.5000`. That read is available to a `MarketingManager`, a `GalleryManager`, a `ComplianceOfficer` and a `PlatformAdmin`.

### 3.2. Galleries, the Representative Roster and Derived Posture

A `GalleryManager` creates a sales gallery with a `name` of 1 to 120 characters, a `site_code` of 3 to 8 characters that must carry no lower-case letter — a value that does not equal its own upper-casing is rejected with `ERR_INVALID_REQUEST`, while digits and punctuation pass — and that is expected to be unique across galleries although the server enforces no uniqueness check on it, a `concurrent_tour_capacity` from 1 through 20 inclusive, a `presentation_minutes` length from 30 through 480 inclusive, and an optional `buffer_minutes` turnaround from 0 through 120 inclusive that defaults to 0. The presentation length is what defines every booking's end instant at that gallery; the buffer is a turnaround allowance appended to the *end* of each interval in the capacity test.

A new gallery opens in `status` `OPEN` with `booked_slot_count` and `available_rep_count` both at 0. It is worth being explicit that a brand-new gallery is `OPEN` despite having no representatives: posture is re-derived when `available_rep_count` changes, and at creation it has not changed from anything.

A `GalleryManager` may also set the posture directly by supplying a `status` of either `OPEN` or `CLOSED`. Requesting `CLOSED` from either `OPEN` or `RESTRICTED` closes the gallery, and closing cancels nothing — existing bookings keep their intervals and keep occupying slots. Requesting `OPEN` re-derives rather than obeys, and it does so from every current posture alike — `CLOSED`, `RESTRICTED` or `OPEN`: with at least one available representative the gallery lands on `OPEN`, and with no available representatives it lands on `RESTRICTED`. Requesting `CLOSED` on a gallery that is already `CLOSED` is likewise accepted and changes nothing. Both `RESTRICTED` and `CLOSED` refuse booking creation, check-in and reschedule commits with `ERR_GALLERY_NOT_OPEN`.

Representatives are added to a gallery's rotation by a `GalleryManager`, who supplies the `gallery_id` of the hosting gallery, a `full_name` of 1 to 120 characters, a `license_number` of 4 to 32 characters that is expected to be globally unique although the server enforces no uniqueness check on it, and a `rotation_position` ordinal from 1 through 99 inclusive that must be unique within that gallery — a collision is rejected with `ERR_ROTATION_POSITION_TAKEN`. A new representative starts in `status` `ACTIVE`, with `tours_taken_count`, `executed_agreement_count`, `rescinded_agreement_count` and `compliance_strike_count` at 0, `cancellation_rate` at `0.0000`, and `last_assigned_at` null until their first check-in assignment. Adding a representative changes `available_rep_count`, which re-derives the gallery's posture, so a `RESTRICTED` gallery returns to `OPEN` the moment its roster is repopulated.

A representative's `status` moves through four values and the machine is cyclic. Winning a rotation assignment at check-in takes them `ACTIVE → ON_TOUR`, stamping `last_assigned_at`. Completing the presentation, or cancelling the booking they were checked in for, returns them `ON_TOUR → ACTIVE`, with the tour counter incrementing on the completion path only. A cancellation-rate breach cascade, or the start of an assigned retraining, takes them `ACTIVE → RETRAINING`. A second compliance strike takes them to `SUSPENDED` from `ACTIVE`, from `ON_TOUR` (leaving the in-flight presentation open) or from `RETRAINING`. A completed retraining returns them to `ACTIVE` from either `RETRAINING` or `SUSPENDED`. Every one of these movements recomputes `available_rep_count` on their gallery and re-derives its posture, because `RETRAINING` and `SUSPENDED` representatives are not available inventory while `ACTIVE` and `ON_TOUR` ones are.

Representatives can be listed with optional `gallery_id` and `status` filters alongside `limit` and `offset`.

### 3.3. Prospect Households and Tour Qualification Scoring

A `MarketingManager` registers a prospect household with a `household_name` of 1 to 120 characters, a `primary_age` from 18 through 99 inclusive, a `household_income_cents` figure of at least 0, and a `marital_status` of either `MARRIED` or `SINGLE`. The household also carries a computed `is_existing_owner` flag, which starts false and becomes true as soon as at least one purchase agreement naming that household has a `fulfillment_status` of `FUNDED`, `RECORDED`, `DOCS_DELIVERED` or `TRADED_IN`. A household may hold any number of bookings over time; no uniqueness rule constrains that.

Qualification is evaluated once, when the booking is created, and both of its outputs are frozen onto the booking at that instant. It runs in two phases.

The first phase is three hard minimums, all of which must pass before any scoring happens. The prospect's `primary_age` must not be below the channel's `min_age`; the prospect's `household_income_cents` must not be below the channel's `min_household_income_cents`; and if the channel's `requires_married_household` flag is set, the prospect's `marital_status` must be `MARRIED`. Any of those three failing rejects the booking with `ERR_PROSPECT_BELOW_MINIMUM_CRITERIA`.

The second phase awards five independent point buckets. Income is tiered: a household income of at least 15000000 cents (150,000 dollars) earns 45 points, at least 10000000 cents earns 35, at least 7500000 cents earns 25, at least 5000000 cents earns 15, and anything below that earns 0. A `primary_age` at or above the channel's `min_age` earns 25 points, which every prospect that survived phase one necessarily does. A `marital_status` of `MARRIED` earns 20 points. An `is_existing_owner` household earns 25 points. And an affinity bonus of 20 points is granted when the channel's `channel_code` is either `IN_HOUSE_REFERRAL` or `OWNER_UPGRADE`.

The order of the final two steps is pinned and is directly observable in the stored score. The five buckets are summed, then the sum is **capped at 100 first**, and only then is the no-show penalty subtracted. The penalty is the channel's `historical_no_show_rate` multiplied by a weight of 30, rounded half-up to a whole point, and it is stored as `qualification_penalty_points`. The final `qualification_score` is the capped total minus that penalty, floored at 0 so it can never go negative. To see why the order matters: buckets totalling 110 points (45 income, 25 age, 20 married, 20 affinity) against a channel whose rate is `1.0000` yield a score of 70, because 110 is capped to 100 before 30 is removed; the rejected penalise-then-cap order would have produced 80. The channel's rate is read as of the instant *before* the new booking is persisted, so a booking never influences its own penalty.

If the resulting `qualification_score` is below the channel's `min_qualification_score`, the booking is rejected with `ERR_PROSPECT_NOT_QUALIFIED`. Neither `qualification_score` nor `qualification_penalty_points` is ever recomputed afterwards, including across a reschedule.

### 3.4. Booking the Tour: Slots, Reschedules and Cancellations

A `MarketingManager` schedules a tour by naming the `channel_id` that produced the lead, the `prospect_id` of the household, the `gallery_id` hosting the tour, and a `scheduled_start_utc` instant. The booking's `scheduled_end_utc` is derived as the start plus the gallery's `presentation_minutes`, and the booking opens in `status` `SCHEDULED` with `assigned_rep_id`, `reschedule_reason`, `cancel_reason` and `checked_in_at` all null, `gift_issued` false, `gift_value_cents` 0 and `reschedule_count` 0.

Booking is gated on lead time, channel posture, gallery posture and capacity. The requested start must be at least 60 minutes — one full hour — after the logical clock, otherwise the request is rejected with `ERR_TOUR_SLOT_IN_PAST`. The channel must be `ACTIVE` and the gallery must be `OPEN`.

Capacity is the interesting geometry. The candidate interval runs from the requested start to that start plus the gallery's `presentation_minutes`. The occupying set is every booking at the same gallery whose `status` is `SCHEDULED`, `RESCHEDULE_PENDING`, `CHECKED_IN` or `TOURED`, excluding the booking currently being rescheduled when this test runs during a reschedule; bookings in `NO_SHOW` and `CANCELLED` never occupy anything. An occupying booking overlaps the candidate when *both* of two comparisons hold, each of them strict: the occupying booking's start is earlier than the candidate's end plus the gallery's `buffer_minutes`, and the candidate's start is earlier than the occupying booking's `scheduled_end_utc` plus the same `buffer_minutes`. Because both comparisons are strict, adjacency is legal at exactly the instant where the candidate's start equals the occupying end plus the buffer. With a 120-minute presentation and a 30-minute buffer, an existing interval from 09:00 to 11:00 leaves 11:30 available and refuses 11:29. If the number of overlapping occupying bookings has reached the gallery's `concurrent_tour_capacity`, the request is rejected with `ERR_GALLERY_CAPACITY_EXCEEDED`.

A successful booking increments the channel's `booked_count` by one — a lifetime counter that is never decremented, not even when the booking is later cancelled — and recomputes the gallery's `booked_slot_count`.

Rescheduling is a two-leg cycle, and the interval is held throughout so the slot is not lost to another prospect. The first leg takes the booking `SCHEDULED → RESCHEDULE_PENDING` and records the supplied `reason` as `reschedule_reason`; it requires `reschedule_count` to be strictly below 2, otherwise it is rejected with `ERR_RESCHEDULE_LIMIT_EXCEEDED`. The gallery's `booked_slot_count` is unchanged by this leg, since `RESCHEDULE_PENDING` remains an occupying status; the booking's own `updated_at` is refreshed and its `version` incremented. The second leg takes the booking `RESCHEDULE_PENDING → SCHEDULED` by committing a `new_scheduled_start_utc`. That leg re-checks everything the original booking checked — gallery `OPEN`, channel `ACTIVE`, the 60-minute lead time, and the capacity overlap test against the new interval with this booking itself excluded from the occupying set — then replaces `scheduled_start_utc`, recomputes `scheduled_end_utc` from the gallery's presentation length, and increments `reschedule_count` by one. The frozen qualification figures are not touched. The cycle `SCHEDULED → RESCHEDULE_PENDING → SCHEDULED` may therefore run at most twice.

Cancellation is reachable from three states and always records the supplied `reason` as `cancel_reason`. From `SCHEDULED` and from `RESCHEDULE_PENDING` it simply recomputes the gallery's `booked_slot_count`, compensating exactly for the occupancy taken at creation. From `CHECKED_IN` it is permitted only while no presentation exists for the booking; once a presentation record has been opened, the attempt is rejected with `ERR_INVALID_BOOKING_STATE`. A cancellation from `CHECKED_IN` additionally returns the assigned representative `ON_TOUR → ACTIVE` — one who has meanwhile been moved to `SUSPENDED` or `RETRAINING` is left exactly where they are — and recomputes the channel's `gift_liability_cents`, which reverses the check-in accrual exactly because `CANCELLED` is not an accruing status. The pair of check-in followed by cancel therefore leaves both `gift_liability_cents` and `booked_slot_count` at their pre-check-in values.

Marking a no-show is available only from `SCHEDULED`, and only once the logical clock has reached or passed the booking's `scheduled_start_utc`; an early attempt is rejected with `ERR_INVALID_BOOKING_STATE`. The transition `SCHEDULED → NO_SHOW` then drives a five-step chain: the channel's `no_show_count` rises by one; that forces the channel's `historical_no_show_rate` to be recomputed; that recomputation may trip the channel's suspension gate described in §3.1; a suspension cancels the channel's remaining `SCHEDULED` and `RESCHEDULE_PENDING` bookings in `created_at` ascending order with `cancel_reason` `CHANNEL_SUSPENDED`; and each gallery touched by those cancellations has its `booked_slot_count` recomputed. Independently of the chain, this booking's own gallery has its `booked_slot_count` recomputed, because `NO_SHOW` is not an occupying status.

Bookings can be listed with optional `channel_id`, `prospect_id`, `gallery_id`, `assigned_rep_id` and `status` filters alongside `limit` and `offset`.

### 3.5. Check-In, Rotation Assignment and Incentive Gifts

Check-in is the `GalleryManager`'s act, and it is where a representative is bound to a tour. It requires the booking to be `SCHEDULED`, the gallery to be `OPEN`, and the channel to be `ACTIVE`. Its single body field is `issue_incentive_gift`, a boolean recording whether the prospect walked away with the channel's gift.

The rotation picks a representative deterministically. The candidate pool is every representative whose `gallery_id` names the booking's gallery, whose `status` is exactly `ACTIVE` — `ON_TOUR`, `RETRAINING` and `SUSPENDED` representatives are all excluded — and who survives a calendar-exclusivity test. Candidates are then ordered by `tours_taken_count` ascending, with `rotation_position` ascending as the first tie-break and `created_at` ascending as the second; the randomly minted `id` is never consulted at any level of that chain. The first row after ordering wins. If the pool is empty, check-in is rejected with `ERR_NO_ELIGIBLE_REPRESENTATIVE`.

Calendar exclusivity is a capacity-of-one test with a symmetric reset gap, and its geometry differs deliberately from the gallery capacity test. For each presentation already on the candidate's calendar — every presentation whose `rep_id` names that representative, with no status filter whatsoever, so open, cleared and flagged presentations all occupy time — the busy interval runs from that presentation's `window_start_utc` to its `window_end_utc`. The candidate collides with that busy interval when *both* comparisons hold, each of them non-strict: the booking's start is at or before the busy end plus a 15-minute reset gap, and the busy start is at or before the booking's end plus the same 15-minute gap. Because the comparisons are non-strict, touching endpoints do collide. An existing presentation window from 09:30 to 11:30 makes a candidate starting at 11:45 ineligible, since 11:45 is exactly the busy end plus 15 minutes, while a candidate starting at 11:46 remains eligible. The same pair of intervals passes the gallery capacity test whenever `concurrent_tour_capacity` is at least 2 — one geometry is half-open with an end-only buffer, the other is closed with a symmetric gap, and conflating them produces wrong assignments.

On success the booking moves `SCHEDULED → CHECKED_IN`, `assigned_rep_id` is set to the winner, `checked_in_at` is stamped from the logical clock, and the winner moves `ACTIVE → ON_TOUR` with `last_assigned_at` stamped. The gallery's `available_rep_count` does not change, because an `ON_TOUR` representative still counts as available inventory.

When `issue_incentive_gift` is true, `gift_issued` is set to true, `gift_value_cents` is copied from the channel's `incentive_gift_value_cents` as of that instant, and the channel's `gift_liability_cents` is recomputed. When it is false, `gift_issued` stays false and `gift_value_cents` stays 0, and the channel's liability is untouched. That copied value is what a refund waterfall later reaches for in the jurisdictions that permit gift recapture.

### 3.6. Presentation Compliance: Disclosures, Prohibited Claims and Review

The presentation record is the compliance artefact of the whole system, and it carries two state dimensions that advance on entirely different triggers. `disclosure_status` moves only on acknowledgment appends and is monotone. `review_status` moves on findings and on review decisions and is cyclic. Neither dimension constrains the other's values.

A `SalesRepresentative` opens the record for their own checked-in tour by naming the `booking_id` and supplying a `recorded_ack_reference` of 4 to 64 characters, an external pointer to the audio or video recording that captures the prospect's spoken acknowledgments. The acting `X-User-ID` must be the booking's `assigned_rep_id`, and the booking must be `CHECKED_IN`. At most one presentation may exist per booking; a second attempt is rejected with `ERR_PRESENTATION_ALREADY_EXISTS`. On creation the record copies `rep_id` from the booking's `assigned_rep_id` and copies `window_start_utc` and `window_end_utc` from the booking's interval — those two instants are what make the representative's calendar enforceable — and stamps `started_at` from the logical clock. It opens with `required_disclosure_count` fixed at 3, `disclosure_ack_count` at 0, `disclosure_status` `PENDING`, `review_status` `UNREVIEWED`, `prohibited_claim_points` at 0, `flag_count` at 0, `reviewed_by_user_id` null, and `compliance_score` at 70 — which is 100 less 0 claim points less 30 points of disclosure gap.

Acknowledgments are appended by the same representative, each naming its `presentation_id`, the `disclosure_code` that was read, an `acknowledged_by_prospect` boolean, and a `recording_timestamp_offset_seconds` offset of at least 0 into the recording. The four legal codes are `RESCISSION_RIGHTS`, `PUBLIC_OFFERING_STATEMENT_DELIVERY`, `NOT_AN_INVESTMENT` and `MAINTENANCE_FEE_ESCALATION`, and each code may be appended at most once per presentation — a repeat is rejected with `ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED`. Each append stamps `acknowledged_at` from the logical clock and computes a `counts_toward_required` flag, which is true only when the code is one of the three *required* disclosures — `RESCISSION_RIGHTS`, `PUBLIC_OFFERING_STATEMENT_DELIVERY` and `NOT_AN_INVESTMENT` — and `acknowledged_by_prospect` is true. `MAINTENANCE_FEE_ESCALATION` is recorded for the audit trail but never counts, and an append with `acknowledged_by_prospect` false records a read-but-not-acknowledged event that also never counts.

After each append, `disclosure_ack_count` is recomputed as the number of *distinct* required codes acknowledged with `acknowledged_by_prospect` true, and the presentation's `compliance_score` is recomputed. The dimension advances `PENDING → PARTIAL` whenever the count is above 0 but still below `required_disclosure_count`, and `PARTIAL → COMPLETE` on the append that raises the count to 3. Appends are accepted while `disclosure_status` is `PENDING` or `PARTIAL`; once it has reached `COMPLETE`, a further append is rejected with `ERR_INVALID_PRESENTATION_STATE`.

The compliance score is a single expression: 100, less the presentation's `prohibited_claim_points`, less 10 points for each required disclosure still unacknowledged (that is, ten times the difference between `required_disclosure_count` and `disclosure_ack_count`), floored at 0. The `prohibited_claim_points` total is itself the sum of `penalty_points` over every prohibited-claim finding on the presentation, where `penalty_points` is derived from the finding's `severity`: a `MINOR` finding costs 5 points, a `MAJOR` finding costs 15, and an `EGREGIOUS` finding costs 40. The score is auto-flagged when either of two conditions holds: the score has fallen below 70, or any finding on the presentation carries `severity` `EGREGIOUS`. The floor is inclusive on the passing side — a fully disclosed presentation carrying exactly two `MAJOR` findings scores 70 and is *not* auto-flagged, while a third `MINOR` finding drops it to 65 and flags it.

A `ComplianceOfficer` files a finding by naming the `presentation_id`, the `claim_code` detected, its `severity`, and the `expected_presentation_version` guard of §2.8. The four legal claim codes are `GUARANTEED_RESALE`, `GUARANTEED_APPRECIATION`, `RENTAL_INCOME_PROMISE` and `UNLIMITED_AVAILABILITY`. The append records `reported_by_user_id` as the acting `X-User-ID` and stamps `detected_at`, recomputes the presentation's `prohibited_claim_points` and `compliance_score`, and increments the presentation's `version` by one.

When the auto-flag condition holds after the append, `review_status` moves to `FLAGGED` — from `UNREVIEWED` or from `CLEARED`, since a previously cleared presentation can be re-flagged when new findings land — and `flag_count` rises by one. Entering `FLAGGED` then drives a three-step cascade that reaches well beyond the presentation. First, the representative's `compliance_strike_count` rises by one. Second, when that strike count has reached 2, the representative moves to `SUSPENDED` *and* a compliance retraining assignment is created for them with `trigger_reason` `PROHIBITED_CLAIM_POINTS`, `status` `ASSIGNED`, `required_module_count` 4, and `strike_count_at_assignment` snapshotting the representative's strike count. Third, the gallery's `available_rep_count` is recomputed, and if it has fallen to 0 while the gallery is `OPEN`, the gallery becomes `RESTRICTED`. Every entry into `FLAGGED` counts a fresh strike, so a clear-then-re-flag sequence accumulates two.

Review is the manual decision, and its `decision` field takes either `CLEAR` or `FLAG`. Both decisions are subject to the segregation rule of §2.11 and both stamp `reviewed_by_user_id` with the acting `X-User-ID`. A `CLEAR` decision — reachable from `UNREVIEWED` and from `FLAGGED`, closing the review loop in both directions — additionally requires that the presentation's `compliance_score` has reached at least 70 and that no finding on it carries `severity` `EGREGIOUS`; failing either condition rejects the decision with `ERR_PRESENTATION_NOT_CLEARED`. Clearing a presentation does *not* decrement the representative's `compliance_strike_count`; strikes are reset only by a completed retraining. A `FLAG` decision is reachable from `UNREVIEWED` only — requested against a `CLEARED` or an already-`FLAGGED` presentation it is rejected with `ERR_INVALID_PRESENTATION_STATE` — and from there it raises `flag_count` by one and runs the same three-step strike cascade as the auto-flag path, identically and in full.

Completing the presentation is the representative's closing act and it is what marks the tour as toured. It requires the booking to be `CHECKED_IN`, requires `review_status` to be anything other than `UNREVIEWED` — otherwise `ERR_INVALID_PRESENTATION_STATE` — and requires `disclosure_status` to be `COMPLETE`, otherwise `ERR_DISCLOSURES_INCOMPLETE`. On this endpoint those two gates are evaluated in exactly that order, following the precedence of §2.9, so a presentation that is at once unreviewed *and* short of its required disclosures reports `ERR_INVALID_PRESENTATION_STATE`. A `FLAGGED` presentation may therefore still complete its tour; only agreement execution insists on `CLEARED`. Completion advances the booking `CHECKED_IN → TOURED`, returns the representative `ON_TOUR → ACTIVE` — one who has meanwhile been suspended stays `SUSPENDED`, though the tour counter rises either way — and raises their `tours_taken_count` by one, raises the channel's `toured_count` by one and recomputes the channel's `historical_no_show_rate`. The gallery's `booked_slot_count` is unchanged, because `TOURED` remains an occupying status for the day. No field on the presentation record itself moves, so its `version` does not advance, and it is that presentation — not the booking — that the response returns.

Presentations can be listed with optional `booking_id` and `rep_id` filters. The two event collections are additionally readable as projections of their presentation: the acknowledgment projection accepts an optional `disclosure_code` filter and the finding projection an optional `severity` filter, both alongside `limit` and `offset`. On those two endpoints `limit` and `offset` are validated first, the presentation `{id}` is resolved next, and the optional enum filter is validated last, so an illegal filter value against a presentation that does not exist reports `ERR_PRESENTATION_NOT_FOUND`.

### 3.7. Agreement Execution: Trade-In Equity, Contract Financials and the Rescission Window

Executing a purchase agreement is the single densest operation in the system. A `SalesRepresentative` executes against their own cleared presentation by naming the `presentation_id`, the `product_type` conveyed, the `state_code` of sale, a `purchase_price_cents` gross price of at least 100000, a `down_payment_cents` amount of at least 0, and the `pos_delivered_at` instant at which the public offering statement reached the purchaser. An optional `traded_in_agreement_id` names a prior agreement being surrendered under the equity trade-in programme; it is null for new-owner sales. The `product_type` is either `DEEDED_INTEREST` or `RIGHT_TO_USE`, and the `state_code` is one of `FL`, `NV`, `CA`, `TX` or `HI`.

The compliance gates come first. The presentation's `disclosure_status` must be `COMPLETE`, otherwise `ERR_DISCLOSURES_INCOMPLETE`; its `review_status` must be `CLEARED`, otherwise `ERR_PRESENTATION_NOT_CLEARED`. At most one agreement may exist per presentation, and a second attempt is rejected with `ERR_AGREEMENT_ALREADY_EXISTS`. The agreement copies `prospect_id` from the presentation's booking and `rep_id` from the presentation, and stamps `executed_at` from the logical clock.

The public offering statement must have been delivered inside a bounded window around signing: `pos_delivered_at` must be no earlier than 30 days before `executed_at` and no later than 3 days after `executed_at`. A delivery instant outside that window is rejected with `ERR_POS_NOT_DELIVERED`.

When a prior agreement is surrendered, two referential gates apply in order. The surrendered agreement's `prospect_id` must equal the new agreement's `prospect_id`, otherwise `ERR_TRADE_IN_OWNER_MISMATCH`; and the surrendered agreement must sit in `fulfillment_status` `DOCS_DELIVERED` with `rescission_status` `EXPIRED`, otherwise `ERR_TRADE_IN_NOT_ELIGIBLE`.

The equity credit is a four-component waterfall over the *prior* agreement's price, and its rounding order is pinned. The hold period, `years_held`, is the elapsed time from the prior agreement's `funded_at` through the current logical clock, taken in seconds and divided by 31,536,000 — that is, 365 days of 86400 seconds each — then rounded half-up to four decimal places before any component consumes it. Each of the four components is then rounded to a whole cent, half-up, *individually*, and only the rounded components are summed; summing first and rounding once is explicitly rejected and produces different money. The first component is the prior price multiplied by an equity recognition rate of 0.55. The second is the negative of the prior price multiplied by an annual depreciation rate of 0.075 and by `years_held`. The third is the prior price multiplied by a loyalty rate of 0.025 and by `years_held` or 10, whichever is smaller — loyalty stops accruing after a decade. The fourth is a flat transfer fee of 49900 cents, taken as a negative amount. `trade_in_equity_credit_cents` is the sum of those four rounded components, floored at 0. Concretely, a prior price of 2450000 cents held for 2.2466 years produces components of 1347500, negative 412813, 137604 and negative 49900, for a credit of 1022391 — whereas summing before rounding would have produced 1022392. When `traded_in_agreement_id` is null, `trade_in_equity_credit_cents` is 0.

Contract financials then run in six pinned steps, and the pinning matters because the document stamp *looks* circular — it is a fee inside the financed amount that is derived from the financed amount.

1. `total_due_cents` is the `purchase_price_cents` less `trade_in_equity_credit_cents`, floored at 0.
2. The required down payment is tiered on that total: a `total_due_cents` of at least 5000000 requires 12 percent, at least 2000000 requires 10 percent, and anything below that requires 8 percent. `down_payment_required_cents` is the total multiplied by the applicable rate, rounded half-up to a whole cent. If the submitted `down_payment_cents` is below that requirement, the execution is rejected with `ERR_DOWN_PAYMENT_INSUFFICIENT`.
3. `base_financed_cents` is `total_due_cents` less `down_payment_cents`, floored at 0.
4. When `base_financed_cents` is 0, both `doc_stamp_cents` and `closing_cost_fee_cents` are 0. Otherwise `doc_stamp_cents` is `base_financed_cents` multiplied by a documentary stamp rate of 0.0035, rounded half-up to a whole cent, and `closing_cost_fee_cents` is a flat 129900 cents plus that stamp. The stamp is assessed on `base_financed_cents` and never on `financed_amount_cents`.
5. `financed_amount_cents` is 0 when `base_financed_cents` is 0, and otherwise is `base_financed_cents` plus `closing_cost_fee_cents`.
6. `escrow_collected_cents` is set equal to `down_payment_cents` and is never changed again for the life of the agreement.

The all-cash boundary is worth stating on its own: when `down_payment_cents` equals `total_due_cents`, `base_financed_cents` is driven to 0, which zeroes *both* the flat closing fee and the document stamp, so `financed_amount_cents` is 0 rather than the bare flat fee.

Two further money fields start at 0 and are written later in the lifecycle: `total_collected_cents`, which stays 0 until funding, and `retained_cents`, which stays 0 until a refund disbursement settles.

The agreement's rescission window is frozen at this moment from the jurisdiction table of §2.7, populating `anchor_mode`, `statutory_rescission_days`, `rescission_anchor_utc`, `rescission_deadline_utc`, `business_day_rolled` and `refund_policy`. The agreement opens with `rescission_status` `OPEN` and `fulfillment_status` `AWAITING_FUNDING`, with `funded_at` and `funding_reference` null. Execution also raises the representative's `executed_agreement_count` by one and recomputes their `cancellation_rate`. If a prior agreement was surrendered, it moves `DOCS_DELIVERED → TRADED_IN`, which is terminal for it.

A dedicated computed read explains the window without recomputing it, echoing `agreement_id`, `state_code`, `anchor_mode`, the `anchor_utc` instant that was selected, `statutory_days`, `business_day_rolled`, `rescission_deadline_utc`, the current `rescission_status`, the current `clock_now`, and an `is_open_now` boolean that is true exactly when `rescission_status` is `OPEN` and the logical clock is at or before the deadline.

Agreements can be listed with optional `presentation_id`, `prospect_id`, `rep_id`, `traded_in_agreement_id`, `rescission_status` and `fulfillment_status` filters alongside `limit` and `offset`. Note that both state dimensions filter independently, because they genuinely are independent.

### 3.8. Financing, Underwriting, Funding and Closing

A `SalesRepresentative` submits a financing application for their own executed agreement by naming the `agreement_id`, a `requested_amount_cents` of at least 1, an `applicant_fico` score from 300 through 850 inclusive, a `term_months` amortisation of exactly 60, 120 or 180, and the `expected_agreement_version` guard of §2.8. The application opens in `status` `SUBMITTED` with every underwriting field null: `apr_bps`, `max_ltv_rate`, `ltv_cap_cents`, `approved_amount_cents`, `monthly_payment_cents`, `decided_at` and `decided_by_user_id`. Submission supersedes: every prior application on the same agreement sitting in `SUBMITTED` or `APPROVED` moves to `WITHDRAWN`, processed in `created_at` ascending order, with its computed underwriting fields left exactly as they were. Superseding an `APPROVED` application additionally requires the agreement to still be in `fulfillment_status` `AWAITING_FUNDING`, otherwise the submission is rejected with `ERR_INVALID_AGREEMENT_STATE`. A successful submission increments the agreement's `version`.

A `ContractAdministrator` records the underwriting decision by supplying a `decision` of either `APPROVE` or `DECLINE`. An `APPROVE` decision is unavailable when `applicant_fico` is below 620 — that request is rejected with `ERR_INVALID_REQUEST`, and because §2.9 files that refusal as a shape failure it is reached before any state gate, so a sub-620 `APPROVE` on an application that has already been decided still reports `ERR_INVALID_REQUEST`. The application must be `SUBMITTED`, otherwise the request is rejected with `ERR_INVALID_FINANCING_STATE`. An `APPROVE` decision is also refused when the agreement's `rescission_status` is `RESCINDED`, which yields `ERR_INVALID_AGREEMENT_STATE`; a `DECLINE` is unaffected by that condition. Both branches stamp `decided_at` from the logical clock and `decided_by_user_id` with the acting `X-User-ID`, and the two branches diverge sharply in everything else.

The `SUBMITTED → APPROVED` branch prices the loan from a FICO tier: a score of at least 740 sets `apr_bps` to 1099 and `max_ltv_rate` to 0.95; at least 680 sets 1399 and 0.90; at least 620 sets 1699 and 0.80. `ltv_cap_cents` is the sum of the agreement's `total_due_cents` and `closing_cost_fee_cents`, multiplied by `max_ltv_rate`, rounded half-up to a whole cent. `approved_amount_cents` is the smaller of `requested_amount_cents` and `ltv_cap_cents`. The monthly payment is a standard amortisation: the monthly rate is `apr_bps` divided by 10000 and then divided by 12, held as an exact rational value with no intermediate rounding; `monthly_payment_cents` is `approved_amount_cents` multiplied by that monthly rate, divided by the quantity obtained by subtracting from one the value of one plus the monthly rate raised to the power of the negative of `term_months`, with a single half-up rounding to a whole cent applied once to that final quotient. A worked figure: a `total_due_cents` of 3200000 with `closing_cost_fee_cents` of 139980, a score of 760, a requested amount of 3019980 and a 120-month term gives an `ltv_cap_cents` of 3172981, an `approved_amount_cents` of 3019980 and a `monthly_payment_cents` of 41583; the identical request at a score of 700 gives an `ltv_cap_cents` of 3005982 and an `approved_amount_cents` of 3005982, which falls short of a `financed_amount_cents` of 3019980.

The `SUBMITTED → DECLINED` branch populates nothing at all: `apr_bps`, `max_ltv_rate`, `ltv_cap_cents`, `approved_amount_cents` and `monthly_payment_cents` all remain null. Applications can be listed with optional `agreement_id` and `status` filters.

Funding is a `ContractAdministrator` act, and it is fenced by the rescission window. It supplies a `funding_reference` and a `collected_amount_cents`, and it requires five conditions, evaluated in the precedence of §2.9. The `fulfillment_status` must be `AWAITING_FUNDING`, otherwise `ERR_INVALID_AGREEMENT_STATE`; that gate is reached first, so a contract that has already been funded or voided reports it even when the rescission dimension would refuse too. The agreement's `rescission_status` must then be `EXPIRED`, otherwise `ERR_RESCISSION_PERIOD_ACTIVE` — a contract inside its statutory window can never be funded. When the agreement's `financed_amount_cents` is above 0, an `APPROVED` financing application must exist for it, otherwise `ERR_FINANCING_NOT_APPROVED`; and when such an application exists, its `approved_amount_cents` must be at least the agreement's `financed_amount_cents`, otherwise `ERR_FINANCING_AMOUNT_SHORTFALL`. Finally, `collected_amount_cents` must equal `financed_amount_cents` exactly — which means 0 for an all-cash agreement — otherwise `ERR_FUNDING_AMOUNT_MISMATCH`.

Funding advances `fulfillment_status` `AWAITING_FUNDING → FUNDED`, stamps `funded_at` from the logical clock, records the `funding_reference`, and sets `total_collected_cents` to `escrow_collected_cents` plus `collected_amount_cents`. It also creates the closing package for the agreement in `status` `AWAITING_RECORDING`, deriving `instrument_type` as `DEED` when the agreement's `product_type` is `DEEDED_INTEREST` and as `RTU_CERTIFICATE` when it is `RIGHT_TO_USE`, with `recording_jurisdiction`, `recording_reference`, `recorded_at`, `delivery_method` and `documents_delivered_at` all null. Because the package is created by cascade rather than by client request, the closing-package list — filterable by `agreement_id` and `status` — is the only channel through which a client discovers its identifier. Funding finally flips the purchaser's `is_existing_owner` flag to true, which is what makes owner-upgrade channels and their affinity bonus meaningful on the next tour.

Closing runs in two steps, and each bubbles the parent agreement's fulfillment dimension up from the child package's state. Recording supplies a `recording_reference` and a `recording_jurisdiction`; it requires the package to be `AWAITING_RECORDING`, otherwise `ERR_INVALID_CLOSING_PACKAGE_STATE`, and then the agreement to be `FUNDED`, otherwise `ERR_INVALID_AGREEMENT_STATE`; it moves the package `AWAITING_RECORDING → RECORDED`, stamps `recorded_at`, and re-derives the agreement `FUNDED → RECORDED`. Delivery supplies a `delivery_method` of `COURIER`, `ELECTRONIC_PORTAL` or `CERTIFIED_MAIL`; it requires the package to be `RECORDED` and gates on nothing else, moves the package `RECORDED → DELIVERED`, stamps `documents_delivered_at`, and re-derives the agreement `RECORDED → DOCS_DELIVERED`, which is terminal for the fulfillment dimension and is also the only state from which the interest can later be surrendered in a trade-in. Both steps return the closing package, not the agreement, as the response resource.

Expiry of the rescission dimension is a separate, sweep-driven epoch rather than a per-request derivation. A `PlatformAdmin` advances it, and every agreement whose `rescission_status` is `OPEN` and whose `rescission_deadline_utc` lies strictly behind the logical clock moves `OPEN → EXPIRED`. Agreements are processed in `executed_at` ascending order with `created_at` ascending as the tie-break, `fulfillment_status` is never touched by the sweep, and the response reports `swept_count`, the list of `expired_agreement_ids`, and the `clock_now` the sweep ran at. An agreement exactly at its deadline instant is not swept, because the comparison is strict.

### 3.9. Cancellation Intake, Refund Settlement, and Representative Rescission Analysis

Rescission intake is deliberately generous about what counts as notice, and deliberately unforgiving about when the contract has moved on. A `ContractAdministrator` records a written cancellation notice by naming the `agreement_id` and the `delivery_method` by which it arrived — `HAND_DELIVERED`, `CERTIFIED_MAIL` or `EMAIL` — with an optional `postmark_utc` instant that is meaningful only for certified mail. Intake requires the agreement's `fulfillment_status` to still be `AWAITING_FUNDING`; every other value — `FUNDED`, `RECORDED`, `DOCS_DELIVERED`, `TRADED_IN` and `VOIDED` alike — refuses intake with `ERR_AGREEMENT_ALREADY_FUNDED`. The request opens in `status` `RECEIVED`, stamping `received_at` from the logical clock and `intake_user_id` with the acting `X-User-ID`, and its timeliness determination is frozen on the spot.

That determination has two variants and the server, not the client, picks between them. When `delivery_method` is `CERTIFIED_MAIL` *and* `postmark_utc` is supplied, `timeliness_basis` is `POSTMARK` and `effective_utc` is the `postmark_utc` instant — timeliness is judged on the mailing, so a notice received after the deadline is still valid when it was mailed inside the window. In every other case — hand delivery, email, or certified mail with no postmark — `timeliness_basis` is `RECEIPT` and `effective_utc` is the `received_at` intake instant, so identical calendar facts adjudicate the other way. `is_timely` is then true when `effective_utc` is at or before the agreement's frozen `rescission_deadline_utc`; equality counts as timely.

Adjudication takes no body at all. It requires the request to be `RECEIVED`, otherwise `ERR_INVALID_RESCISSION_REQUEST_STATE`, and again requires the agreement to be in `AWAITING_FUNDING`, otherwise `ERR_AGREEMENT_ALREADY_FUNDED`. Both branches stamp `adjudicated_at` and `adjudicated_by_user_id`, and the server selects the branch purely from the frozen `is_timely` value.

The timely branch takes the request `RECEIVED → VALIDATED` and voids the contract through a four-step chain plus one fan-out. First, the agreement's `rescission_status` moves to `RESCINDED` — from `OPEN` in the ordinary case, and also from `EXPIRED` when a notice postmarked inside the window is adjudicated after the sweep already expired the agreement — and its `fulfillment_status` moves `AWAITING_FUNDING → VOIDED`. Second, the selling representative's `rescinded_agreement_count` rises by one and their `cancellation_rate` is recomputed. Third, when that recomputed analysis shows at least 2 in-window executed agreements and a rate that has reached at least `0.5000`, a compliance retraining assignment is created for the representative with `trigger_reason` `CANCELLATION_RATE_BREACH`, `status` `ASSIGNED`, `required_module_count` 4 and `cancellation_rate_at_assignment` snapshotting the recomputed rate, and the representative moves to `RETRAINING` — but only from `ACTIVE`: one already `ON_TOUR`, `RETRAINING` or `SUSPENDED` keeps the status they hold. Fourth, the gallery's `available_rep_count` is recomputed and an `OPEN` gallery that has fallen to 0 becomes `RESTRICTED`. Separately from that chain, every financing application on the voided agreement sitting in `SUBMITTED` or `APPROVED` moves to `CANCELLED`, processed in `created_at` ascending order. Rescinding from `EXPIRED` still insists the agreement be unfunded, otherwise `ERR_AGREEMENT_ALREADY_FUNDED`.

The untimely branch takes the request `RECEIVED → REJECTED_LATE` and does nothing else. The agreement is not touched at all: neither state dimension moves, no representative counter changes, no retraining is assigned, and no gallery posture is re-derived. The entire four-step chain and its fan-out are skipped.

Refund disbursement is where the money actually leaves, and it is the second segregation-of-duties boundary. A `ContractAdministrator` — one who did not adjudicate the request — creates the disbursement by naming the `rescission_request_id` and a `method` of `ACH`, `CHECK` or `CARD_REVERSAL`. The request must be `VALIDATED`, otherwise `ERR_INVALID_RESCISSION_REQUEST_STATE`, and only one disbursement may exist per request, with a second attempt rejected as `ERR_REFUND_ALREADY_ISSUED`. Creation copies `refund_policy_applied` from the agreement's `refund_policy`, sets `base_refund_cents` to the agreement's `escrow_collected_cents` — immutable since execution, so the snapshot cannot drift — opens in `status` `PENDING`, and stamps `issued_by_user_id` with the acting `X-User-ID`, leaving `settlement_reference` and `settled_at` null.

The settlement arithmetic then forks on the policy the jurisdiction imposed. Under `STATUTORY_FULL` nothing whatsoever may be withheld: `gift_recapture_cents` is 0, `doc_fee_retained_cents` is 0, and `disbursed_amount_cents` equals the whole escrow balance. Under `CONTRACTUAL_NET_OF_GIFT` an ordered two-bucket waterfall runs over that balance, and the order is pinned. Gift recapture is taken first and is the smaller of two figures: the `gift_value_cents` recorded on the tour booking behind the agreement — reached through the agreement's presentation and that presentation's booking — and the escrow balance multiplied by a recapture cap rate of 0.05, rounded half-up to a whole cent. The document preparation fee is taken second and is the smaller of 19900 cents and whatever escrow remains after the recapture. `disbursed_amount_cents` is the escrow balance less the recapture less the retained fee. To make the fork concrete: an escrow of 320000 cents with a recorded gift value of 12500 disburses the full 320000 under `STATUTORY_FULL`, and under `CONTRACTUAL_NET_OF_GIFT` recaptures 12500, retains 19900, and disburses 287600.

Settling the disbursement closes the cancellation. It supplies a `settlement_reference`, requires the disbursement to be `PENDING` — a second settle attempt is rejected with `ERR_INVALID_RESCISSION_REQUEST_STATE`, the code this endpoint reuses for the disbursement dimension — moves the disbursement `PENDING → ISSUED`, stamps `settled_at`, advances the rescission request `VALIDATED → REFUNDED`, and writes the agreement's `retained_cents` as `gift_recapture_cents` plus `doc_fee_retained_cents`. Escrow conservation holds exactly at that point: the agreement's `escrow_collected_cents` equals the `disbursed_amount_cents` plus the agreement's `retained_cents`, with no rounding remainder anywhere. Rescission requests can be listed by `agreement_id` and `status`; disbursements by `rescission_request_id` and `status`.

Representative rescission analysis is the rolling metric that decides retraining, and its window and filters are precise. The window is the closed interval running from 90 days before the logical clock through the logical clock itself, with both endpoints inclusive, and membership is decided on an agreement's `executed_at`. The denominator, `executed_count`, counts every agreement in that window whose `rep_id` names the representative, with *no* status filter at all — agreements in `fulfillment_status` `VOIDED`, `FUNDED`, `RECORDED`, `DOCS_DELIVERED` and `TRADED_IN` all count. The numerator, `rescinded_count`, narrows that same set to agreements whose `rescission_status` is `RESCINDED`. `cancellation_rate` is `0.0000` when the denominator is 0, and otherwise the numerator divided by the denominator, rounded half-up to four decimal places. Retraining is required when the denominator has reached at least 2 *and* the rate has reached at least `0.5000`. Both guards are inclusive, which is exactly why 1 rescission out of exactly 2 in-window agreements — a rate of `0.5000` on a sample of 2 — does trigger retraining, while 1 out of 1 — a rate of `1.0000` on a sample of 1 — does not. The computed analysis read echoes `representative_id`, `window_start_utc`, `window_end_utc`, `executed_count`, `rescinded_count`, `cancellation_rate`, the `min_sample` of 2, and the `retraining_required` verdict, and it is available only to a `GalleryManager`, a `ComplianceOfficer` and a `PlatformAdmin`.

Retraining itself is a cyclic remediation loop administered by a `ComplianceOfficer`. Assignments arrive two ways: created by the strike cascade or the cancellation-rate cascade, in which case the system sets `trigger_reason` itself; or assigned manually, in which case the officer names the `rep_id`, the `trigger_reason`, the `required_module_count`, and the `expected_representative_version` guard of §2.8. The three reasons are `CANCELLATION_RATE_BREACH`, `PROHIBITED_CLAIM_POINTS` and `DISCLOSURE_GAP`; `required_module_count` runs from 1 through 10 inclusive and defaults to 4, which is also the module count every cascade-created assignment uses. At most one assignment per representative per reason may sit in `ASSIGNED` or `IN_PROGRESS` at a time, and a duplicate is rejected with `ERR_RETRAINING_ALREADY_ACTIVE` — assignments with *different* reasons coexist freely. That guard runs on the manual create only; the strike cascade and the cancellation-rate cascade append their assignment unconditionally and may therefore leave two active assignments sharing one reason. A new assignment opens in `status` `ASSIGNED` with `cycle_index` 1, `modules_completed` 0, `assigned_at` stamped from the logical clock, `started_at` and `closed_at` null, `strike_count_at_assignment` snapshotting the representative's current `compliance_strike_count`, and `cancellation_rate_at_assignment` snapshotting their current `cancellation_rate` when the reason is `CANCELLATION_RATE_BREACH` and null for the other two reasons.

Starting an assignment moves it `ASSIGNED → IN_PROGRESS`, stamps `started_at`, and takes an `ACTIVE` representative to `RETRAINING`; a representative already `SUSPENDED` stays `SUSPENDED` while retraining. Either way the gallery's `available_rep_count` is recomputed and its posture re-derived.

Closing an assignment supplies an `outcome` of `COMPLETE` or `FAIL` together with the `modules_completed` figure, and requires the assignment to be `IN_PROGRESS`. A `COMPLETE` close requires `modules_completed` to be at least `required_module_count`, otherwise it is rejected with `ERR_MODULE_COUNT_SHORTFALL`. On success it stamps `closed_at`, records the module count, moves the assignment `IN_PROGRESS → COMPLETED`, and then runs a three-step restoration: the representative's `compliance_strike_count` is reset to 0 — the only mechanism in the system that resets strikes; the representative returns to `ACTIVE`, but only when no other assignment for them still sits in `ASSIGNED` or `IN_PROGRESS`; and the gallery's `available_rep_count` is recomputed, so a `RESTRICTED` gallery whose count has reached at least 1 returns to `OPEN`. A `FAIL` close also stamps `closed_at` and records `modules_completed`, but moves the assignment `IN_PROGRESS → FAILED`, leaves the representative wherever they are — `RETRAINING` or `SUSPENDED` — and preserves their strike count untouched. `FAILED` is not terminal.

Reassignment closes the loop `ASSIGNED → IN_PROGRESS → FAILED → ASSIGNED`. It is available only from `FAILED` and only while `cycle_index` is strictly below 3; a fourth cycle is refused with `ERR_INVALID_RETRAINING_STATE`. It raises `cycle_index` by one, re-stamps `assigned_at` from the logical clock, resets `modules_completed` to 0, and resets both `started_at` and `closed_at` to null. Only `COMPLETED` is terminal for an assignment. Because cascade-created assignments are never returned to the triggering client, the assignment list — filterable by `rep_id`, `trigger_reason` and `status` — is the only channel through which they are discovered.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource, advance a state machine, or return a computed projection return `200 OK`. There is no single URL prefix in this API: every collection is mounted at the top level, because no entity owns the others. Entries marked "Any role" are open to all six roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tour-channels` | Register a tour-generation channel with its incentive gift value and minimum qualification criteria | MarketingManager |
| POST | `/tour-channels/{id}/reinstate` | Lift a no-show suspension and reset the channel's probation baseline | MarketingManager |
| GET | `/tour-channels/{id}` | Read a tour-generation channel | Any role |
| GET | `/tour-channels/{id}/no-show-summary` | Computed read of the channel's no-show aggregation and outstanding gift liability | MarketingManager, GalleryManager, ComplianceOfficer, PlatformAdmin |
| POST | `/sales-galleries` | Create a sales gallery with its concurrent capacity, presentation length and turnaround buffer | GalleryManager |
| POST | `/sales-galleries/{id}/set-status` | Open or close a gallery; an open request re-derives the posture | GalleryManager |
| GET | `/sales-galleries/{id}` | Read a sales gallery with its derived posture and counters | Any role |
| POST | `/sales-representatives` | Add a sales representative to a gallery's assignment rotation | GalleryManager |
| GET | `/sales-representatives/{id}` | Read a sales representative, including the version needed for the retraining guard | Any role |
| GET | `/sales-representatives` | List sales representatives, optionally filtered by gallery or status | Any role |
| GET | `/sales-representatives/{id}/rescission-analysis` | Computed read of the 90-day cancellation-rate analysis for one representative | GalleryManager, ComplianceOfficer, PlatformAdmin |
| POST | `/prospects` | Register a prospect household for tour generation | MarketingManager |
| GET | `/prospects/{id}` | Read a prospect household including the existing-owner flag | Any role |
| POST | `/tour-bookings` | Schedule a tour, running qualification evaluation and the gallery capacity overlap check | MarketingManager |
| POST | `/tour-bookings/{id}/reschedule-requests` | Open a reschedule cycle on a scheduled tour, holding the interval | MarketingManager |
| POST | `/tour-bookings/{id}/reschedule` | Close a reschedule cycle by committing a new interval | MarketingManager |
| POST | `/tour-bookings/{id}/check-in` | Check a prospect in, assign a representative by rotation and optionally issue the gift | GalleryManager |
| POST | `/tour-bookings/{id}/no-show` | Record a no-show, driving the channel no-show rate cascade | MarketingManager |
| POST | `/tour-bookings/{id}/cancel` | Cancel a tour, compensating slot and gift-liability accruals | MarketingManager |
| GET | `/tour-bookings/{id}` | Read a tour booking | Any role |
| GET | `/tour-bookings` | List tour bookings by channel, prospect, gallery, assigned representative or status | Any role |
| POST | `/sales-presentations` | Open a presentation record for a checked-in tour with its recording reference | SalesRepresentative |
| POST | `/disclosure-acknowledgments` | Append a recorded prospect acknowledgment of a required disclosure | SalesRepresentative |
| POST | `/prohibited-claim-findings` | File a prohibited-claim finding; may auto-flag the presentation and strike the representative | ComplianceOfficer |
| POST | `/sales-presentations/{id}/review` | Record the compliance review decision, subject to segregation of duties | ComplianceOfficer |
| POST | `/sales-presentations/{id}/complete` | Close the presentation and mark the tour as toured, releasing the representative | SalesRepresentative |
| GET | `/sales-presentations/{id}` | Read a presentation with both state dimensions and the version needed for the finding guard | Any role |
| GET | `/sales-presentations` | List sales presentations filtered by booking or representative | Any role |
| GET | `/sales-presentations/{id}/disclosure-acknowledgments` | List the recorded disclosure acknowledgments appended to a presentation | Any role |
| GET | `/sales-presentations/{id}/prohibited-claim-findings` | List the prohibited-claim findings filed against a presentation | Any role |
| POST | `/purchase-agreements` | Execute an agreement against a cleared presentation, optionally surrendering a prior agreement | SalesRepresentative |
| POST | `/purchase-agreements/{id}/fund` | Fund a contract once the rescission period has expired; creates the closing package | ContractAdministrator |
| GET | `/purchase-agreements/{id}` | Read an agreement with both dimensions, all financial outputs and the version needed for the financing guard | Any role |
| GET | `/purchase-agreements` | List agreements by presentation, prospect, representative, surrendered trade-in or either state dimension | Any role |
| GET | `/purchase-agreements/{id}/rescission-window` | Computed read of the statutory window, naming the anchor variant that produced the deadline | Any role |
| POST | `/financing-applications` | Submit a financing application; supersedes any prior application on that agreement | SalesRepresentative |
| POST | `/financing-applications/{id}/decision` | Record the underwriting decision, pricing the loan on approval only | ContractAdministrator |
| GET | `/financing-applications/{id}` | Read a financing application | Any role |
| GET | `/financing-applications` | List financing applications filtered by agreement or status | Any role |
| POST | `/rescission-requests` | Take in a written cancellation notice and freeze its timeliness basis | ContractAdministrator |
| POST | `/rescission-requests/{id}/adjudicate` | Adjudicate a cancellation notice; the server selects the branch from timeliness | ContractAdministrator |
| GET | `/rescission-requests/{id}` | Read a rescission request with its frozen timeliness determination | Any role |
| GET | `/rescission-requests` | List rescission requests filtered by agreement or status | Any role |
| POST | `/refund-disbursements` | Create the refund disbursement for a validated cancellation under the jurisdiction's policy | ContractAdministrator |
| POST | `/refund-disbursements/{id}/settle` | Settle the refund, closing the cancellation and pinning the retained amount | ContractAdministrator |
| GET | `/refund-disbursements/{id}` | Read a refund disbursement | Any role |
| GET | `/refund-disbursements` | List refund disbursements filtered by rescission request or status | Any role |
| POST | `/closing-packages/{id}/record` | Record the deed or right-to-use instrument, bubbling the agreement to recorded | ContractAdministrator |
| POST | `/closing-packages/{id}/deliver` | Deliver the closing document package, bubbling the agreement to documents delivered | ContractAdministrator |
| GET | `/closing-packages/{id}` | Read a closing package | Any role |
| GET | `/closing-packages` | List closing packages by agreement or status; the discovery channel for cascade-created packages | Any role |
| POST | `/retraining-assignments` | Manually assign compliance retraining to a representative | ComplianceOfficer |
| POST | `/retraining-assignments/{id}/start` | Begin a retraining assignment, moving the representative out of the rotation | ComplianceOfficer |
| POST | `/retraining-assignments/{id}/close` | Close a retraining assignment as complete or failed | ComplianceOfficer |
| POST | `/retraining-assignments/{id}/reassign` | Re-open a failed retraining assignment for another cycle | ComplianceOfficer |
| GET | `/retraining-assignments/{id}` | Read a retraining assignment | Any role |
| GET | `/retraining-assignments` | List assignments by representative, reason or status; the discovery channel for cascade-created assignments | Any role |
| POST | `/_clock/set_current_utc` | Set the server's logical clock forward | PlatformAdmin |
| POST | `/_ops/rescission-sweep` | Advance the rescission epoch, expiring every open agreement past its deadline | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CHANNEL_NOT_FOUND` | 404 Not Found |
| `ERR_GALLERY_NOT_FOUND` | 404 Not Found |
| `ERR_REPRESENTATIVE_NOT_FOUND` | 404 Not Found |
| `ERR_PROSPECT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_PRESENTATION_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FINANCING_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_RESCISSION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_REFUND_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSING_PACKAGE_NOT_FOUND` | 404 Not Found |
| `ERR_RETRAINING_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPRESENTATIVE_MISMATCH` | 403 Forbidden |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PRESENTATION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_REPRESENTATIVE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_BOOKING_STATE` | 409 Conflict |
| `ERR_INVALID_PRESENTATION_STATE` | 409 Conflict |
| `ERR_INVALID_AGREEMENT_STATE` | 409 Conflict |
| `ERR_INVALID_FINANCING_STATE` | 409 Conflict |
| `ERR_INVALID_RESCISSION_REQUEST_STATE` | 409 Conflict |
| `ERR_INVALID_CLOSING_PACKAGE_STATE` | 409 Conflict |
| `ERR_INVALID_RETRAINING_STATE` | 409 Conflict |
| `ERR_RESCISSION_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_ALREADY_FUNDED` | 409 Conflict |
| `ERR_REFUND_ALREADY_ISSUED` | 409 Conflict |
| `ERR_RETRAINING_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_CHANNEL_SUSPENDED` | 409 Conflict |
| `ERR_GALLERY_NOT_OPEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DISCLOSURES_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_PRESENTATION_NOT_CLEARED` | 422 Unprocessable Entity |
| `ERR_POS_NOT_DELIVERED` | 422 Unprocessable Entity |
| `ERR_TRADE_IN_OWNER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TRADE_IN_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_TOUR_SLOT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_CLOCK_NOT_MONOTONIC` | 422 Unprocessable Entity |
| `ERR_CHANNEL_CODE_TAKEN` | 409 Conflict |
| `ERR_ROTATION_POSITION_TAKEN` | 409 Conflict |
| `ERR_PRESENTATION_ALREADY_EXISTS` | 409 Conflict |
| `ERR_DISCLOSURE_ALREADY_ACKNOWLEDGED` | 409 Conflict |
| `ERR_AGREEMENT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_RESCHEDULE_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_GALLERY_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_REPRESENTATIVE` | 409 Conflict |
| `ERR_PROSPECT_BELOW_MINIMUM_CRITERIA` | 422 Unprocessable Entity |
| `ERR_PROSPECT_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_MODULE_COUNT_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_DOWN_PAYMENT_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_FINANCING_NOT_APPROVED` | 409 Conflict |
| `ERR_FINANCING_AMOUNT_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_FUNDING_AMOUNT_MISMATCH` | 422 Unprocessable Entity |

# Rental Reimbursement & Loss-of-Use Management API — Product Requirements Document

## 1. Introduction

When a policyholder's vehicle is disabled by a covered loss, the insurer owes them mobility. That obligation is discharged in one of two ways: a rental car, booked with a partner agency and billed directly to the insurer within the policy's daily limit and duration cap, or a loss-of-use allowance paid to a claimant who made do with a non-owned vehicle instead. Between promise and payment lies a long chain of operational risk — repair timelines slip, customers keep cars longer than the repair justifies, partners bill for unauthorized days or upgraded vehicle classes, and money committed against one reservation must be released or re-committed as the claim evolves. This document specifies the API for the insurer's rental management desk, the system of record that carries a claim through that entire chain.

The desk is built around deliberate friction. Coverage verification, repair tracking, reservation authorization, extension adjudication, invoice audit, and recovery collection each belong to a different desk function, and the roles that decide money are segregated from the roles that release it. Three financial ledgers ride on every claim — an open rental reserve, an authorized-day tally, and a recovery balance — and every monetary rule in this document is expressed in integer cents against those ledgers. Because every date-driven decision (activation windows, delay justifications, overstay assessments) must be reproducible under audit, the server evaluates all "current date" reasoning against a controllable logical clock rather than the wall clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly eight roles: `Customer`, `RentalDeskAgent`, `ClaimsAdjuster`, `SettlementApprover`, `RepairShop`, `RentalPartner`, `RecoverySpecialist`, and `SystemAdmin`. A caller whose role is not on an endpoint's authorized list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `PolicyHolder`; ownership checks on any resource that resolves to a policy holder — a claim, and anything filed under that claim — compare the claim's `policyholder_id` to `X-User-ID`. When `X-User-Role` is `RepairShop`, `X-User-ID` is the `id` of the acting `RepairShop`, and ownership checks compare a repair order's `shop_id` to `X-User-ID`. When `X-User-Role` is `RentalPartner`, `X-User-ID` is the `id` of the acting `RentalPartner`, and ownership checks compare a reservation's or invoice's `rental_partner_id` to `X-User-ID`. For the remaining roles — `RentalDeskAgent`, `ClaimsAdjuster`, `SettlementApprover`, `RecoverySpecialist`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Calendar-Day Arithmetic

All "current date" reasoning in the system reads a server-side logical clock, never the wall clock. Before any call is made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. A `SystemAdmin` advances it through an admin-only test-driving capability that sets the clock to a supplied `to_iso8601` instant; the capability mutates no entity.

Every date-stamped field reads this logical clock: `reported_at` on repair milestones, `actual_pickup_date` and `actual_return_date` on reservations, `actual_completion_date` on repair orders, and `sent_at` on communication log entries. Every comparison of a business date against "today" — pickup-date validation, activation windows — likewise reads this clock.

All date fields are ISO 8601 calendar dates in `YYYY-MM-DD` form. Rental day counting uses half-open calendar intervals: the pickup day counts, the return day does not, and the day count of an interval is the number of calendar days from its start date up to but not including its end date. An interval whose start equals its end therefore contains zero days. Consumed rental time follows the same rule, counted from `actual_pickup_date` up to but not including `actual_return_date`. Loss-of-use periods are the single exception: they are closed intervals on which both the first and the last day count, so a period from Monday through Friday is five days, not four.

### 2.5. Common Resource Properties and Monetary Precision

Primary resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every modification of the resource. `version` is a system-managed integer that increments by one with every modification, and it anchors the optimistic-concurrency rules of §2.10.

Three record types are deliberately append-only and carry a reduced property set: a repair milestone, a class change record, and a communication log entry each expose `id` and `created_at` only. Both `updated_at` and `version` are absent from these three resources, because they are never modified after being persisted.

All monetary values — limits, rates, reserves, charges, taxes, fees, payouts, and recovery amounts — are represented as integer cents. All day counts are integer days. The only rounding the system performs is round half up to a whole cent, and it is applied per calendar day before any summation wherever tax enters a calculation (see §3.8); summing charges first and rounding the tax once is a different algorithm and is explicitly not permitted.

### 2.6. Claim Financial Ledgers: Reserve, Duration Cap, and Recovery Balance

Every claim carries three derived ledgers that the server maintains continuously.

The `rental_reserve_cents` ledger is the claim's open rental exposure. It is initialized when the claim is opened to the `coverage_daily_limit_cents` multiplied by the `coverage_duration_cap_days` — the most the claim could ever owe under the rental benefit. Thereafter the reserve is reconciled to equal that initial product, minus the sum of `estimated_charge_cents` over the claim's reservations in `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` status, minus the sum of `audited_payable_cents` over the claim's `SETTLED` invoices. Two conservation invariants follow. First, authorizing a reservation and then cancelling it leaves the reserve unchanged: authorization debits the estimate, and cancellation of an `AUTHORIZED` reservation credits the same estimate back in full. Second, recording a vehicle return moves the reservation out of the estimate term entirely, and settling an invoice moves that same exposure into the settled term — the money is never double-counted or lost, only reclassified.

The `authorized_days_total` ledger sums `authorized_days` over the claim's reservations in `AUTHORIZED`, `ACTIVE`, `EXTENSION_REVIEW`, or `RETURNED` status. It is the yardstick for the duration cap: the total may never exceed the claim's `coverage_duration_cap_days`.

The `recovery_balance_cents` ledger sums `outstanding_amount_cents` over the claim's recovery cases in `OPEN` or `PARTIAL_RECOVERY` status. A claim cannot settle while this balance is non-zero. Every recovery case obeys its own conservation invariant at all times: `assessed_amount_cents` always equals the sum of `recovered_amount_cents`, `waived_amount_cents`, and `outstanding_amount_cents` — equivalently, the outstanding amount is the assessed amount minus what has been recovered and what has been waived.

### 2.7. Validation Order and Error Precedence

Every request is validated against a fixed precedence ladder, and the first failing rung determines the error response; later rungs are not consulted once an earlier one has failed.

The ladder begins with the authentication rungs: header presence and shape (rung 1, `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization against the endpoint's role list (rung 2, `ERR_INSUFFICIENT_PERMISSIONS`). Next come the existence rungs: identifiers carried in the URL path are validated left to right (rung 3), and identifiers referenced in the request body — such as `claim_id`, `rental_partner_id`, `repair_order_id`, `reservation_id`, `milestone_id`, or `policyholder_id` — are validated for existence immediately after (rung 4). Immediately after the existence rungs, and in any case before any business-category rule, the request's shape is validated: a missing required field, a type mismatch, an invalid enum value, a decision-specific required field that is absent (a `denial_reason` on a denial, a `new_estimated_completion_date` on a delay report), or an amount outside its permitted range fails with `ERR_INVALID_REQUEST` (HTTP 400).

Only then do the guarded rungs run, in this order: entity-backed ownership (rung 5, `ERR_NOT_RESOURCE_OWNER`); the claim-open gate requiring `overall_status` to be `OPEN` for any mutation under the claim (rung 6, `ERR_CLAIM_NOT_OPEN`), whose sole exception is claim closure, which requires `SETTLED` and fails with `ERR_CLAIM_NOT_SETTLED`; the coverage-verified gate on reservation booking (rung 7, `ERR_COVERAGE_NOT_VERIFIED`); the target entity's transition-level state preconditions (rung 8, the state-error family — `ERR_VERIFICATION_ALREADY_DECIDED`, `ERR_RESERVATION_INVALID_STATE`, `ERR_REPAIR_ORDER_INVALID_STATE`, `ERR_EXTENSION_INVALID_STATE`, `ERR_INVOICE_INVALID_STATE`, `ERR_LOU_INVALID_STATE`, `ERR_RECOVERY_INVALID_STATE`, `ERR_PENDING_EXTENSION_EXISTS`, `ERR_RESERVATION_CLOSE_BLOCKED`, `ERR_CLAIM_SETTLE_BLOCKED`, `ERR_CLAIM_NOT_SETTLED`); optimistic concurrency (rung 9, `ERR_STALE_VERSION`); temporal rules (rung 10 — `ERR_PICKUP_DATE_IN_PAST`, `ERR_INVALID_PERIOD`, `ERR_ACTIVATION_BEFORE_PICKUP_DATE`, `ERR_INVALID_DELAY`); referential consistency (rung 11 — `ERR_PARTNER_SUSPENDED`, `ERR_REPAIR_ORDER_MISMATCH`, `ERR_REPAIR_ORDER_INVALID_STATE`, `ERR_EXTENSION_INVALID_STATE`, `ERR_LOU_NOT_ELIGIBLE`); business constraints such as uniqueness, interval overlap, fleet capacity, extension justification, and documentation requirements (rung 12); and finally fiscal headroom (rung 13 — `ERR_DURATION_CAP_EXHAUSTED`, `ERR_INSUFFICIENT_RESERVE`).

Two precedence pairs are pinned explicitly because they are easy to get wrong: a state-precondition failure (rung 8) is always reported before a fiscal failure (rung 13), and a temporal failure (rung 10) is always reported before a referential one (rung 11). Note also that the two fiscal errors carry different HTTP statuses: `ERR_DURATION_CAP_EXHAUSTED` is HTTP 409, while `ERR_INSUFFICIENT_RESERVE` is HTTP 402.

### 2.8. Nested Resource Retrieval and Referential Existence

For any endpoint whose URL path contains resource identifiers, the system validates existence sequentially, left to right, and the first identifier that does not resolve to an existing resource produces its type-specific `404 Not Found` error; later path segments are never examined. A request for the verifications of a non-existent claim, for example, fails with `ERR_CLAIM_NOT_FOUND` before any verification lookup is attempted. Each resource type has its own not-found error: `ERR_POLICYHOLDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_COVERAGE_VERIFICATION_NOT_FOUND`, `ERR_REPAIR_SHOP_NOT_FOUND`, `ERR_RENTAL_PARTNER_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_EXTENSION_REQUEST_NOT_FOUND`, `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and `ERR_RECOVERY_CASE_NOT_FOUND`. The same codes apply when a body-referenced identifier does not exist — creating a reservation against a missing repair order fails with `ERR_REPAIR_ORDER_NOT_FOUND`, and creating an extension request against a missing milestone fails with `ERR_MILESTONE_NOT_FOUND`.

### 2.9. Ownership and Segregation of Duties

Three roles are entity-backed, and ownership is enforced on their mutating operations. A `RepairShop` caller may act only on repair orders it owns — starting repairs, completing repairs, and reporting milestones all require the order's `shop_id` to equal the caller's `X-User-ID`. A `RentalPartner` caller may act only on reservations it owns — recording pickup, recording return, and submitting direct-bill invoices all require the reservation's `rental_partner_id` to equal the caller's `X-User-ID`. A `Customer` caller may act only on claims they own — submitting a loss-of-use claim and attaching documentation both require the claim's `policyholder_id` to equal the caller's `X-User-ID`. Every ownership failure is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

Two desks are deliberately segregated. The `ClaimsAdjuster` opens claims, verifies coverage, approves repair estimates, decides extensions and loss-of-use claims, and audits invoices — but can never release money. The `SettlementApprover` settles invoices, pays approved loss-of-use claims, and settles and closes claims — but can never verify coverage or audit an invoice. A workflow that requires both a decision and a disbursement therefore always requires two distinct operators.

### 2.10. Optimistic Concurrency Control

Two write operations mutate shared state in ways that make a stale client view dangerous, and both are protected by optimistic concurrency control.

Creating a coverage verification supersedes any pending verification on the claim, so the creation request must carry `expected_claim_version`, the claim `version` the client last observed. If that value no longer matches the claim's current `version` — because another writer has since created or decided a verification, advancing the claim's version — the create is rejected as stale with `ERR_STALE_VERSION` (HTTP 412), preventing the client from superseding a decision it never observed.

Creating an extension request supersedes any submitted request on the reservation and flips the reservation into review, so the creation request must carry `expected_reservation_version`, the reservation `version` the client last observed. A mismatch with the reservation's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from pushing a reservation it has not re-read into review.

Booking a reservation likewise carries `expected_claim_version` — the claim version the desk agent last read — anchoring the booking to the claim state the desk observed; a mismatch with the claim's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named in this section do not take a version field.

### 2.11. Automated State Cascades and Hierarchical Consistency

The server keeps parent and child state aligned without requiring explicit client calls on every resource. Certain transitions fire automatically when their criteria become true: a claim's rental track advances from `COVERAGE_VERIFIED` to `RENTAL_ACTIVE` the moment its first reservation reaches `ACTIVE`, and from `RENTAL_ACTIVE` to `RENTAL_CLOSED` once every reservation on the claim is terminal (`CLOSED` or `CANCELLED`), provided at least one reservation exists. Supersession is likewise automatic: creating a new coverage verification on a claim moves any still-`PENDING` verification on that claim to `SUPERSEDED`, and creating a new extension request on a reservation moves any still-`SUBMITTED` request on that reservation to `SUPERSEDED`.

Claim-level bookkeeping follows a uniform rule. Each of these operations increments the claim's `version` by one and refreshes its `updated_at`: verification creation and decision, reservation booking, authorization, and cancellation, the delay-milestone cascade, extension approval, class changes, loss-of-use submission, documentation, approval, denial, and payment, invoice dispute and settlement, recovery payments and waivers, and claim settlement and closure themselves. The claim's `version` therefore also serves as a coarse change detector for anything happening under the claim; the conditional exceptions — pickup recording, vehicle return without an overstay, reservation closure that does not complete the claim's rental activity, and extension denial — are called out where each workflow is defined in §3.

## 3. Business Logic & Workflows

### 3.1. Desk Bootstrap: Policyholders, Repair Shops, and Rental Partner Rate Cards

Before any claim can be serviced, a `SystemAdmin` populates the three directories the desk depends on. Registering a policy holder records the `full_name`, the `policy_number`, and a `contact_email`. The policy number is unique across all policy holders; a duplicate registration is rejected with `ERR_DUPLICATE_POLICY_NUMBER`. Registering a repair shop records the `shop_name` and a `shop_code` that is likewise unique across all repair shops, with duplicates rejected as `ERR_DUPLICATE_SHOP_CODE`.

Rental partners carry the most elaborate registration. A `SystemAdmin` registers each partner with a `partner_name` and a unique `partner_code` (duplicates fail with `ERR_DUPLICATE_PARTNER_CODE`), a three-tier rate card — `economy_rate_cents`, `standard_rate_cents`, and `premium_rate_cents`, each of which must be greater than zero — and a three-tier fleet capacity: `economy_capacity`, `standard_capacity`, and `premium_capacity`, the number of vehicles of each class the partner can rent out per calendar day, none of which may be negative. A newly registered partner starts with `status` set to `ACTIVE`.

Partners can be taken offline. Suspending a partner moves its `status` to `SUSPENDED`, which blocks the creation of any new reservation with that partner — the booking fails with `ERR_PARTNER_SUSPENDED` — while leaving existing reservations entirely unaffected; a partner with cars on the road continues to activate, receive, and invoice them. Reactivation returns the partner to `ACTIVE`.

### 3.2. Claims Intake and Coverage Verification

A `ClaimsAdjuster` opens a claim by naming the claimant and the policy's rental-benefit terms. The creation payload carries the `policyholder_id` (which must reference an existing policy holder, else `ERR_POLICYHOLDER_NOT_FOUND`), the `incident_date` of the covered loss, the `coverage_daily_limit_cents` — the most the insurer will pay per authorized rental day — the `coverage_duration_cap_days` that bounds total authorized days across the whole claim, and the `loss_of_use_per_diem_cents` used later by the standard per-diem payout variant. On creation the claim's `rental_reserve_cents` is initialized to the daily limit multiplied by the duration cap, `authorized_days_total` and `recovery_balance_cents` start at zero, and the claim opens with three independent status dimensions: `rental_track_status` begins `OPEN`, `loss_of_use_track_status` begins `NONE`, and `overall_status` begins `OPEN`. The two track dimensions evolve independently under the `overall_status` gate; the only terminal state of a claim is `overall_status` reaching `CLOSED`.

Coverage is established through a verification workflow. The adjuster creates a verification against a claim by supplying the `claim_id`; the request is the OCC-guarded create of §2.10. The new record starts `PENDING`, and its creation automatically moves any still-pending earlier verification on the same claim to `SUPERSEDED` — at most one verification per claim is ever awaiting decision. A claim's verifications can be listed to audit this chain.

Deciding a verification requires the adjuster to supply a `decision` of `VERIFIED` or `DENIED` together with the two eligibility flags, `rental_eligible` and `loss_of_use_eligible`. Only a `PENDING` verification can be decided; deciding an already-decided record fails with `ERR_VERIFICATION_ALREADY_DECIDED`. Two shape rules attach to the decision itself: a `VERIFIED` decision must mark at least one of the two benefits eligible — verifying coverage while denying both benefits is rejected with `ERR_INVALID_REQUEST` — and a `DENIED` decision must carry a `denial_reason`, whose absence is likewise `ERR_INVALID_REQUEST`. The decision propagates to the claim's rental track along two symmetric branches: a `VERIFIED` decision with `rental_eligible` true moves `rental_track_status` from `OPEN` to `COVERAGE_VERIFIED`, while a `DENIED` decision — or a `VERIFIED` decision on which `rental_eligible` is false, which happens when only the loss-of-use benefit was confirmed — moves it to `COVERAGE_DENIED`.

### 3.3. Repair Orders and the Milestone Delay Cascade

Repairs enter the system when a `RepairShop` creates a repair order against a claim. The shop supplies the `claim_id`, the current `estimated_completion_date`, and a `labor_hours_estimate` that must be greater than zero; the order's `shop_id` is recorded automatically from the caller's `X-User-ID`, not from the payload. A new order starts in `ESTIMATE_SUBMITTED` status, and a shop can list its own orders through the repair-order collection, which accepts an optional `shop_id` filter.

The order then walks a linear chain. Estimate approval by a `ClaimsAdjuster` moves `ESTIMATE_SUBMITTED` to `APPROVED`; approving an order in any other state fails with `ERR_REPAIR_ORDER_INVALID_STATE`. Starting the work is the owning shop's action and moves `APPROVED` to `IN_PROGRESS`; a shop that does not own the order is turned away with `ERR_NOT_RESOURCE_OWNER`, and starting a non-`APPROVED` order is `ERR_REPAIR_ORDER_INVALID_STATE`. Completing the work, again by the owning shop only, moves `IN_PROGRESS` to `COMPLETED` and stamps `actual_completion_date` from the logical clock — until then it is null. Completion also refreshes the overstay projection: for every reservation on this order currently in `ACTIVE` or `EXTENSION_REVIEW`, the system recomputes the projected `unnecessary_days`, though no recovery case is opened until the vehicle is actually returned.

While an order is `IN_PROGRESS`, the owning shop reports progress through milestones. Each milestone carries a `milestone_type` of `REPAIR_STARTED`, `PARTS_DELAYED`, `DELAY_REPORTED`, or `REPAIR_COMPLETED`, an optional free-text `note`, and a system-stamped `reported_at` taken from the logical clock. Reporting a milestone on an order that is not `IN_PROGRESS` fails with `ERR_REPAIR_ORDER_INVALID_STATE`, and a shop reporting on another shop's order fails with `ERR_NOT_RESOURCE_OWNER`. Milestones are append-only and can be listed under their repair order.

A `DELAY_REPORTED` milestone is special: it asserts that the repair will finish later than currently estimated, so it must carry a `new_estimated_completion_date` — omitting it is `ERR_INVALID_REQUEST` — and that date must be strictly later than the order's current `estimated_completion_date`, else the report is rejected with `ERR_INVALID_DELAY`. Accepting a delay report fires a three-hop cascade. First, the repair order's `estimated_completion_date` is advanced to the reported date and the order's `version` increments. Second, the reservation whose `repair_order_id` is this order and whose status is `ACTIVE` is flipped to `EXTENSION_REVIEW`, with its `version` incremented — the desk is told, in effect, that the authorized window no longer matches the repair reality. Third, a customer communication is auto-created on the claim with template `EXPECTATION_SET`, channel `EMAIL`, and a system-generated `body_summary`, so the claimant hears about the slipped timeline from the desk rather than from the rental counter. The cascade closes by incrementing the claim's `version`.

### 3.4. Booking and Authorizing a Rental Reservation

With coverage verified and a repair order on file, a `RentalDeskAgent` books the rental. The booking payload names the `claim_id`, the `rental_partner_id`, and the `repair_order_id` whose repair this rental substitutes for, selects a `vehicle_class` of `ECONOMY`, `STANDARD`, or `PREMIUM`, and fixes the rental window with a `pickup_date` and an `authorized_return_date`. The request is anchored to the claim state the desk observed via `expected_claim_version` (§2.10). Booking is heavily guarded. The claim must be `OPEN` (`ERR_CLAIM_NOT_OPEN`) and its rental track must be `COVERAGE_VERIFIED` — booking on an unverified or denied claim fails with `ERR_COVERAGE_NOT_VERIFIED`. The partner must be `ACTIVE`, the repair order must belong to the same claim as the reservation — a cross-claim reference fails with `ERR_REPAIR_ORDER_MISMATCH` — and the order must be `APPROVED` or `IN_PROGRESS`, never a bare submitted estimate or a finished repair (`ERR_REPAIR_ORDER_INVALID_STATE`). The `pickup_date` must not be strictly before the logical clock's current date (`ERR_PICKUP_DATE_IN_PAST`), and the `authorized_return_date` must be strictly later than the `pickup_date` (`ERR_INVALID_PERIOD`). The new half-open window must not overlap any existing reservation on the same claim in `DRAFT`, `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` status — overlaps fail with `ERR_RESERVATION_PERIOD_OVERLAP`, though back-to-back bookings, where the new pickup date equals the earlier reservation's authorized return date, are permitted. Finally, booking is one side of the loss-of-use conflict rule of §3.7: a reservation whose window shares a calendar day with an existing loss-of-use period on the same claim is rejected with `ERR_LOU_PERIOD_CONFLICT`.

Creation freezes the commercial terms onto the reservation. The partner's three class rates are copied into an immutable `rate_card_snapshot` at booking time — later rate-card edits at the partner never reach an existing reservation — and the applicable `daily_rate_cents` is read off that snapshot for the booked `vehicle_class`. The system then derives `authorized_days` as the half-open day count of the authorized window and the provisional `estimated_charge_cents` as exactly `authorized_days` times the applicable `daily_rate_cents`. This provisional estimate is deliberately uncapped by the coverage daily limit and excludes tax entirely: it is the desk's forward-looking authorization exposure, not the audit figure, and it diverges from the audited charge whenever the booked rate exceeds the limit or any tax is later billed. The reservation lands in `DRAFT` status, with `actual_pickup_date`, `actual_return_date`, and `consumed_days` all null, `unnecessary_days` zero, and `audited_charge_cents` — the running total of settled invoice amounts — starting at zero. Reservations can be listed per claim, and the global reservation collection accepts optional `rental_partner_id` and `repair_order_id` filters.

Authorization is the desk's second, separable decision, and it is where the fiscal gates bite. Authorizing a reservation that is not in `DRAFT` fails with `ERR_RESERVATION_INVALID_STATE`. The provisional `estimated_charge_cents` must not exceed the claim's current `rental_reserve_cents`, else the authorization is refused with `ERR_INSUFFICIENT_RESERVE` (HTTP 402). The claim's `authorized_days_total`, computed with this reservation included, must not exceed the `coverage_duration_cap_days`, else `ERR_DURATION_CAP_EXHAUSTED` (HTTP 409). And the partner's fleet must physically support the booking: for every calendar day of the authorized window, the number of that partner's reservations occupying that day in the same vehicle class and currently in `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` must remain strictly below the partner's capacity for that class, else `ERR_FLEET_CAPACITY_EXCEEDED`. On success the reservation moves `DRAFT` to `AUTHORIZED`, the estimated charge is debited from the claim's reserve per the reconciliation rule of §2.6, and the claim's `version` increments.

Pickup is recorded by the owning rental partner. Activation requires the reservation to be `AUTHORIZED` (`ERR_RESERVATION_INVALID_STATE` otherwise), requires the caller to own the reservation (`ERR_NOT_RESOURCE_OWNER`), and requires the logical clock's date to be on or after the `pickup_date` — early activation fails with `ERR_ACTIVATION_BEFORE_PICKUP_DATE`. The reservation moves to `ACTIVE` and `actual_pickup_date` is stamped from the clock. When this is the claim's first reservation to reach `ACTIVE`, the claim's rental track automatically advances from `COVERAGE_VERIFIED` to `RENTAL_ACTIVE` with a claim version increment; activations beyond the first touch no claim state.

A booking can be abandoned while it is still young. Cancelling is a `RentalDeskAgent` action available from `DRAFT` or `AUTHORIZED` only — any other state is `ERR_RESERVATION_INVALID_STATE` — and it lands the reservation in the terminal `CANCELLED` state. Cancellation of an `AUTHORIZED` reservation performs a full compensating release, crediting the entire `estimated_charge_cents` back to the claim's reserve; this is what makes the authorize-then-cancel sequence reserve-neutral under the conservation invariant of §2.6. Either way the claim's `version` increments.

### 3.5. Extensions and Mid-Rental Class Changes

When a repair slips, the rental window must move with it. A `RentalDeskAgent` requests additional days by creating an extension request naming the `reservation_id`, the `milestone_id` that justifies the slip, and the `requested_additional_days`, which must be at least one; the request carries the OCC field `expected_reservation_version` described in §2.10. The milestone must exist (`ERR_MILESTONE_NOT_FOUND`) and must be a `DELAY_REPORTED` milestone belonging to the reservation's own repair order — citing a milestone of the wrong type or from a different order fails with `ERR_EXTENSION_INVALID_STATE`. The reservation must be `ACTIVE` or already under review: creating the request flips an `ACTIVE` reservation to `EXTENSION_REVIEW` (a reservation already in `EXTENSION_REVIEW` stays there) and increments the reservation's `version`, while requesting an extension on a terminal reservation fails with `ERR_RESERVATION_INVALID_STATE`. If the claim has no duration-cap headroom left — authorized days already total the cap — creation is refused with `ERR_DURATION_CAP_EXHAUSTED`. Any earlier still-`SUBMITTED` request on the same reservation is automatically moved to `SUPERSEDED`, so at most one request per reservation is ever awaiting a decision. The new request starts `SUBMITTED`, its `granted_days` null until an approval fills it in. Extension requests can be listed per reservation, and the global collection accepts an optional `milestone_id` filter.

Approval is the adjuster's call, and the day grant is computed in a pinned evaluation order using only pre-grant values. First, the claim's authorized-day total is summed over reservations in `AUTHORIZED`, `ACTIVE`, `EXTENSION_REVIEW`, or `RETURNED`; the difference between the `coverage_duration_cap_days` and that total is the cap headroom, and a headroom of zero rejects the approval with `ERR_DURATION_CAP_EXHAUSTED`. Second, the justified need is computed: take the milestone's new estimated completion date, extend it by one calendar day of completion grace, and count the calendar days from the reservation's current, pre-grant `authorized_return_date` to that extended date, flooring the result at zero. Because the grant itself moves the authorized return date, this input is deliberately evaluated with the pre-grant value and never re-evaluated afterwards. When the count is zero — the milestone's new estimate plus the grace day does not reach beyond the current authorized window — the approval fails with `ERR_EXTENSION_NOT_JUSTIFIED`. Third, `granted_days` is the smallest of the requested additional days, the cap headroom, and the justified need, and the approval requires the reservation to be in `EXTENSION_REVIEW` (`ERR_RESERVATION_INVALID_STATE` otherwise), the request itself to be `SUBMITTED` (`ERR_EXTENSION_INVALID_STATE` otherwise), and the repair order to be `IN_PROGRESS` (`ERR_REPAIR_ORDER_INVALID_STATE` otherwise). Two further fiscal and physical guards complete the check: the grant's cost — `granted_days` times the reservation's current `daily_rate_cents` — must not exceed the claim's current `rental_reserve_cents` (`ERR_INSUFFICIENT_RESERVE`), and the partner's per-day fleet capacity is re-checked for the added days under the same rule used at authorization (`ERR_FLEET_CAPACITY_EXCEEDED`).

An approved grant is applied exactly once: the `authorized_return_date` moves later by `granted_days`, `authorized_days` grows by the same amount, the provisional `estimated_charge_cents` grows by `granted_days` times the `daily_rate_cents`, and the claim's `rental_reserve_cents` falls by that same cost, with the claim's `version` incrementing. The reservation returns to `ACTIVE` with its `version` incremented, the request lands in `APPROVED`, and a customer communication with template `EXTENSION_UPDATE` is logged on the claim. Denial is the symmetric branch, gated by the same two state preconditions — the request must be `SUBMITTED` (`ERR_EXTENSION_INVALID_STATE` otherwise) and the reservation must be in `EXTENSION_REVIEW` (`ERR_RESERVATION_INVALID_STATE` otherwise). The adjuster may attach an optional `decision_reason`, the request lands in `DENIED`, the reservation returns to `ACTIVE` with its `version` incremented but its window unchanged, and the same `EXTENSION_UPDATE` communication goes out — but unlike an approval, a denial does not advance the claim's `version`.

A separate adjustment covers the vehicle itself. When no comparable car is available or the customer demands a different class, a `RentalDeskAgent` records a class change naming the `reservation_id`, the `to_class`, the `effective_date` from which the new rate applies, and an optional `upgrade_waiver` flag that defaults to false. The reservation must be `AUTHORIZED`, `ACTIVE`, or `EXTENSION_REVIEW` (`ERR_RESERVATION_INVALID_STATE` otherwise), the `to_class` must differ from the current `vehicle_class` (`ERR_INVALID_REQUEST` otherwise), and the `effective_date` must fall inside the authorized window — on or after the `pickup_date` and strictly before the `authorized_return_date` — else `ERR_INVALID_PERIOD`. The record is append-only, captures the `from_class` the reservation had before the change, and can be listed under its reservation.

The cost split between insurer and customer is computed from the immutable rate snapshot. The remaining rental length is the half-open day count from the `effective_date` to the `authorized_return_date` — the effective day itself is already billed at the new rate. Let the old and new rates be read from the `rate_card_snapshot`. On a downgrade — the new rate at or below the old — the insurer always benefits and the customer owes nothing: both `per_day_customer_cents` and `customer_responsibility_cents` are zero, and the `insurer_delta_cents` is negative, equal in magnitude to the per-day rate reduction multiplied by the remaining days. On an upgrade, the insurer's per-day share is the amount by which the capped new rate exceeds the capped old rate — each rate capped at the claim's `coverage_daily_limit_cents` before the comparison, and the difference floored at zero — while the customer's per-day share depends on the waiver: a waived upgrade (for example, when no comparable vehicle was available) sets `per_day_customer_cents` to zero, and an unwaived upgrade sets it to the amount by which the new rate exceeds the greater of the coverage daily limit and the old rate, floored at zero. Multiplying each per-day figure by the remaining days yields `customer_responsibility_cents` and `insurer_delta_cents`. The change then applies: the reservation's `vehicle_class` becomes the `to_class`, `daily_rate_cents` is re-read from the snapshot for the new class, the provisional estimate absorbs the insurer delta, and the claim's reserve is reduced by the insurer delta — a negative delta credits the reserve. Both the reservation's and the claim's `version` increment.

### 3.6. Vehicle Return and Unnecessary-Day Assessment

The rental ends where it began, at the partner's counter. Recording the return is the owning partner's action (`ERR_NOT_RESOURCE_OWNER` for anyone else) and is allowed from `ACTIVE` or `EXTENSION_REVIEW` — returning a `DRAFT`, `AUTHORIZED`, or terminal reservation fails with `ERR_RESERVATION_INVALID_STATE`. A return is also refused while any extension request on the reservation is still `SUBMITTED`, surfacing `ERR_PENDING_EXTENSION_EXISTS`; the desk must decide the pending extension first. On success the reservation moves to `RETURNED`, `actual_return_date` is stamped from the logical clock, `consumed_days` is computed as the half-open day count from `actual_pickup_date` to `actual_return_date`, and the reservation leaves the reserve's estimate term — its provisional charge is released from the `rental_reserve_cents` reconciliation of §2.6.

Return is also the moment of truth for unnecessary rental days. If the reservation's repair order is not `COMPLETED`, there is nothing to recover: `unnecessary_days` is zero and no recovery case is created. Otherwise the system extends the order's `actual_completion_date` by one calendar day of return grace — the claimant is entitled to keep the car through the day after repairs finish — and counts the days from that grace boundary to the actual return date, floored at zero; that count is the reservation's `unnecessary_days`. When the count is positive, a recovery case is opened automatically with `source` `RETURN_OVERSTAY`, its `claim_id` and `reservation_id` copied from the reservation, its `unnecessary_days` set to the computed count, and its `assessed_amount_cents` set to the unnecessary days multiplied by the reservation's current `daily_rate_cents`. The case starts `OPEN` with `recovered_amount_cents` and `waived_amount_cents` at zero and `outstanding_amount_cents` equal to the assessed amount, the claim's `recovery_balance_cents` rises by the assessed amount, and the claim's `version` increments. When the count is zero, return touches no claim state at all.

Closing the reservation is the desk's final tidy-up and is gated on everything downstream being resolved. Closure by a `RentalDeskAgent` requires the reservation to be `RETURNED` (`ERR_RESERVATION_INVALID_STATE` otherwise), every invoice on the reservation to be `SETTLED`, and every recovery case on the reservation to be `CLOSED` or `WAIVED` (or none to exist) — either shortfall blocks the close with `ERR_RESERVATION_CLOSE_BLOCKED`. A successful close lands the reservation in the terminal `CLOSED` state, and when every reservation on the claim is now terminal (`CLOSED` or `CANCELLED`) and at least one reservation exists, the claim's rental track automatically advances from `RENTAL_ACTIVE` to `RENTAL_CLOSED` with a claim version increment.

### 3.7. Loss-of-Use Claims for Non-Owned Vehicles

A claimant who forgoes the rental and uses a non-owned vehicle instead files for loss of use. Submission is a `Customer` action on a claim the caller owns (`ERR_NOT_RESOURCE_OWNER`), carrying the `claim_id`, a `vehicle_description` of the substitute vehicle, the `period_start` and `period_end` of the usage, the documented `claimed_amount_cents` (which must be greater than zero), and a `payout_method` of either `STANDARD_PER_DIEM` or `COMPARABLE_VEHICLE`. Unlike the rental track's half-open windows, the loss-of-use period is a closed interval counting both endpoint days, so the `period_end` need only be on or after the `period_start` — an inverted period is `ERR_INVALID_PERIOD`.

Two eligibility gates protect the track. First, the claim's latest non-`SUPERSEDED` verification must be `VERIFIED` with `loss_of_use_eligible` true; otherwise submission fails with `ERR_LOU_NOT_ELIGIBLE` and the claim's track stays `NONE`. Second, the loss-of-use conflict rule forbids double-dipping between the two benefits: a loss-of-use period conflicts with any reservation on the same claim in `DRAFT`, `AUTHORIZED`, `ACTIVE`, `EXTENSION_REVIEW`, or `RETURNED` whenever the closed loss-of-use interval shares at least one calendar day with the reservation's window treated as closed on both ends (pickup day through return day inclusive). The check runs on whichever record is created later — booking a reservation over an existing loss-of-use period fails with `ERR_LOU_PERIOD_CONFLICT` just as submitting a loss-of-use claim over an existing reservation does. A successful submission lands the claim's loss-of-use track in `LOU_SUBMITTED` — and the claim's `version` increments — with `documentation_provided` false and `payout_cents` still null.

Documentation is the claimant's follow-up: attaching cost documentation moves a `SUBMITTED` loss-of-use claim to `DOCUMENTED`, sets `documentation_provided` to true, and advances the claim's track to `LOU_DOCUMENTED`. Attaching to a claim in any other state is rejected with `ERR_LOU_INVALID_STATE`.

The adjuster then decides. Approval is possible from either `SUBMITTED` or `DOCUMENTED`, but a `COMPARABLE_VEHICLE` payout requires `documentation_provided` to be true — approving one without documentation fails with `ERR_DOCUMENTATION_REQUIRED`. The payout computation first derives the reasonable length of the period as its closed-interval day count, counting both the first and last day, then caps the billable length at the claim's `coverage_duration_cap_days`. Under the `STANDARD_PER_DIEM` variant, the `payout_cents` is simply the claim's `loss_of_use_per_diem_cents` multiplied by the billable days, ignoring the claimed amount entirely. Under the `COMPARABLE_VEHICLE` variant, the `payout_cents` is the lesser of the documented `claimed_amount_cents` and the `coverage_daily_limit_cents` multiplied by the billable days — the actual documented cost capped by the daily limit. Approval records the `payout_cents`, lands the loss-of-use claim in `APPROVED`, advances the claim's track to `LOU_APPROVED`, and increments the claim's `version`. Denial is open from the same two states, accepts an optional `decision_reason`, lands the claim in `DENIED`, and moves the track to `LOU_DENIED`. Operating on a loss-of-use claim that has already reached a terminal or downstream state — approving an `APPROVED` or `PAID` claim, or denying a terminal one — is `ERR_LOU_INVALID_STATE`.

Payment is where segregation of duties bites: the adjuster who approved the claim cannot pay it. Paying is a `SettlementApprover` action on an `APPROVED` loss-of-use claim (any other state is `ERR_LOU_INVALID_STATE`), and it requires the claim's `overall_status` to still be `OPEN` (`ERR_CLAIM_NOT_OPEN`). Payment lands the record in `PAID` and moves the claim's track to `LOU_PAID`.

### 3.8. Direct-Bill Invoicing, Audit, and Settlement

Rental partners bill the insurer directly. Submitting an invoice is the owning partner's action: the payload names the `reservation_id`, the partner's own `invoice_number`, the billed `period_start` and `period_end`, the billed `daily_rate_cents` (which must be greater than zero), and the billed `tax_cents` and `fees_cents` (neither of which may be negative). The invoice's `rental_partner_id` is recorded from the caller's `X-User-ID`, and the caller must own the reservation the invoice bills against (`ERR_NOT_RESOURCE_OWNER`). The reservation must be `ACTIVE`, `EXTENSION_REVIEW`, or `RETURNED` — billing a `DRAFT` or `AUTHORIZED` reservation fails with `ERR_RESERVATION_INVALID_STATE` — the billed period must be half-open with the end strictly later than the start (`ERR_INVALID_PERIOD`), and the invoice number must be unique among that partner's invoices (`ERR_DUPLICATE_INVOICE_NUMBER`). At ingestion the submitted `total_cents` is computed as the billed period's day count times the billed `daily_rate_cents`, plus the `tax_cents`, plus the `fees_cents`. Invoices can be listed per reservation, and the global invoice collection accepts an optional `rental_partner_id` filter.

Every invoice forks automatically at ingestion; there is no human in the loop for the fork itself. An invoice is auto-adjudicated to `AUTO_APPROVED` if and only if all five criteria hold: the billed period lies entirely within the reservation's authorized window from `pickup_date` to `authorized_return_date`; the billed `daily_rate_cents` equals the reservation's currently applicable rate; no class change record exists on the reservation; the billed `fees_cents` do not exceed the documentation-fee cap of 2,500 cents — a twenty-five-dollar allowance; and the billed `tax_cents` equals exactly the sum over the billed period's days of each day's tax, where a day's tax is the lesser of the billed rate and the claim's `coverage_daily_limit_cents`, multiplied by an 8 percent tax rate, rounded half up to a whole cent per day before summation. Any criterion failing routes the invoice to `MANUAL_REVIEW` instead, and the system computes its `unauthorized_days`. An auto-approved invoice is priced immediately: its `audited_payable_cents` is set at ingestion to the audited final amount, which for an invoice passing all five criteria equals the submitted total. A manually routed invoice keeps `audited_payable_cents` null until an adjuster prices it.

The audited final amount follows a fixed chronological algorithm. The payable window begins at the later of the billed period start and the reservation's `pickup_date`, and ends at the earlier of the billed period end and the `authorized_return_date`. The invoice's `unauthorized_days` is the billed period's total day count minus the window's day count, never below zero. Each calendar day inside the window is then priced in chronological order: the day's rate is read from the immutable `rate_card_snapshot` for the vehicle class in effect on that day — a class change with a given `effective_date` applies to every day on or after that date until the next change takes over — the day's charge is the lesser of that rate and the claim's `coverage_daily_limit_cents`, and the day's tax is that charge multiplied by 8 percent, rounded half up to a whole cent immediately, before any summation. The allowed fees are the lesser of the billed `fees_cents` and the 2,500-cent documentation-fee cap. The `audited_payable_cents` is the sum over all window days of each day's charge plus its tax, plus the allowed fees. The rounding order is pinned: summing all day charges first and rounding the tax once at the end produces different cents and is explicitly not the algorithm — per-day rounding wins.

A `ClaimsAdjuster` resolves a `MANUAL_REVIEW` invoice through an audit decision; auditing an invoice in any other state fails with `ERR_INVOICE_INVALID_STATE`, which is also what a second, sequential audit decision hits, since the first decision has already moved the invoice out of `MANUAL_REVIEW` — no version field is involved here. Three decisions exist, and each has equal weight in the workflow. `APPROVE_AS_SUBMITTED` accepts the partner's figures wholesale: `audited_payable_cents` becomes the submitted `total_cents` and the invoice moves to `AUTO_APPROVED`. `ADJUST_TO_AUTHORIZED` prices the invoice by the audited final algorithm above — clipping days to the authorized window, capping each day at the coverage limit, applying per-day tax rounding, and capping fees — and likewise moves the invoice to `AUTO_APPROVED`. `DISPUTE_UNNECESSARY_DAYS` instead moves the invoice to `DISPUTED` and opens a recovery case on the spot: the case's `source` is `INVOICE_DISPUTE`, its `unnecessary_days` is the invoice's `unauthorized_days`, and its `assessed_amount_cents` is those days multiplied by the lesser of the invoice's billed `daily_rate_cents` and the claim's `coverage_daily_limit_cents`. The dispute also raises the claim's `recovery_balance_cents` by the assessed amount, increments the claim's `version`, and auto-logs a customer communication with template `RECOVERY_NOTICE`. Every audit decision increments the invoice's `version`.

Settlement converts audited paper into ledger fact. Settling is a `SettlementApprover` action, and the claim must still be `OPEN` (`ERR_CLAIM_NOT_OPEN`). An invoice settles from `AUTO_APPROVED` directly; a `DISPUTED` invoice settles only after the recovery case its dispute created has been resolved — `CLOSED` or `WAIVED` — and settling one whose case is still open fails with `ERR_INVOICE_INVALID_STATE`, as does attempting to settle a `SUBMITTED` or `MANUAL_REVIEW` invoice that has no audited amount at all. On settlement the claim's `rental_reserve_cents` is debited by the `audited_payable_cents` — the reserve's estimate term shrinks as the settled-actuals term grows, per §2.6 — the reservation's `audited_charge_cents` accumulates the same amount with its `version` incrementing, the claim's `version` increments, and the invoice lands in its terminal `SETTLED` state.

### 3.9. Recovery Desk Operations and Final Claim Settlement

Recovery cases are the system's memory of money owed back. Whether born from a return overstay or an invoice dispute, each case tracks its `source`, the `unnecessary_days` being recovered, the `assessed_amount_cents`, and three amounts that obey the conservation invariant of §2.6: `recovered_amount_cents` and `waived_amount_cents` start at zero, and `outstanding_amount_cents` starts equal to the assessed amount. The collection lives under the claim and can also be listed globally with an optional `reservation_id` filter. Only a `RecoverySpecialist` may work a case.

Collection is granular. Recording a payment requires an `amount_cents` of at least one and no more than the current outstanding amount — anything outside that range is `ERR_INVALID_REQUEST` — and any collection action on a `CLOSED` or `WAIVED` case is `ERR_RECOVERY_INVALID_STATE`. A payment smaller than the outstanding amount moves the case from `OPEN` to `PARTIAL_RECOVERY`; a payment exactly equal to the outstanding amount closes it. Either way, `recovered_amount_cents` grows by the payment, the outstanding amount is recomputed under the invariant, the claim's `recovery_balance_cents` falls by the payment, and the claim's `version` increments. Where recovery is not worth the candle, the specialist may instead waive the case from `OPEN` or `PARTIAL_RECOVERY`: the `waived_amount_cents` is set to the then-outstanding amount, the outstanding amount goes to zero, the claim's recovery balance falls by the waived amount with a version increment, and the case lands in `WAIVED`. Both `CLOSED` and `WAIVED` are terminal.

The desk's last cross-cutting obligation is customer communication. Beyond the automated `EXPECTATION_SET`, `EXTENSION_UPDATE`, and `RECOVERY_NOTICE` entries fired by the delay cascade, extension decisions, and invoice disputes, a `RentalDeskAgent` may log a communication against a claim at any time, supplying the `claim_id`, a `channel` of `EMAIL`, `SMS`, or `PHONE`, a `template` — the full set being `COVERAGE_EXPLAINED`, `EXPECTATION_SET`, `EXTENSION_UPDATE`, `RETURN_REMINDER`, and `RECOVERY_NOTICE` — and a `body_summary`. Each entry is stamped with `sent_at` from the logical clock, is append-only, and is listed under its claim; `COVERAGE_EXPLAINED` and `RETURN_REMINDER` exist precisely for these desk-initiated touches.

A claim settles when nothing under it is still moving. Settlement is a `SettlementApprover` action requiring `overall_status` to be `OPEN`, and three conditions must all hold, with any shortfall rejected as `ERR_CLAIM_SETTLE_BLOCKED`: every reservation on the claim must be terminal — `CLOSED` or `CANCELLED` — or none may exist; every loss-of-use claim must be terminal — `PAID` or `DENIED` — or none may exist; and the claim's `recovery_balance_cents` must be exactly zero, meaning every recovery case has been collected in full or waived. Settlement moves `overall_status` to `SETTLED`. Closing is the final act, again a `SettlementApprover` action, and it alone among claim mutations requires the claim to be `SETTLED` rather than `OPEN` — closing an unsettled claim fails with `ERR_CLAIM_NOT_SETTLED`. A successful close moves `overall_status` to its terminal `CLOSED` state, after which no mutation under the claim is possible.

## 4. Endpoint Definitions

Endpoints that create a new resource — registering a policyholder, shop, or partner, opening a claim, creating a verification, repair order, milestone, reservation, extension request, class change record, loss-of-use claim, invoice, or communication entry — return `201 Created`. Endpoints that modify an existing resource, including all lifecycle transitions, decisions, settlements, payments, and the clock capability, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock to a supplied instant | SystemAdmin |
| POST | `/policyholders` | Register a policy holder | SystemAdmin |
| GET | `/policyholders/{id}` | Get a policy holder | Any |
| GET | `/policyholders/{id}/claims` | List the claims of a policy holder | Any |
| POST | `/repair-shops` | Register a repair shop | SystemAdmin |
| GET | `/repair-shops/{id}` | Get a repair shop | Any |
| POST | `/rental-partners` | Register a rental partner with rate card and fleet capacities | SystemAdmin |
| GET | `/rental-partners/{id}` | Get a rental partner | Any |
| POST | `/rental-partners/{id}/suspend` | Suspend a partner (blocks new reservations; existing ones unaffected) | SystemAdmin |
| POST | `/rental-partners/{id}/reactivate` | Reactivate a suspended partner | SystemAdmin |
| POST | `/claims` | Open a claim with its rental-benefit terms | ClaimsAdjuster |
| GET | `/claims/{id}` | Get a claim, including derived ledgers | Any |
| POST | `/claims/{id}/settle` | Settle a claim once all children are terminal and recovery is zero | SettlementApprover |
| POST | `/claims/{id}/close` | Close a settled claim | SettlementApprover |
| GET | `/claims/{id}/coverage-verifications` | List the coverage verifications of a claim | Any |
| GET | `/claims/{id}/repair-orders` | List the repair orders of a claim | Any |
| GET | `/claims/{id}/rental-reservations` | List the reservations of a claim | Any |
| GET | `/claims/{id}/loss-of-use-claims` | List the loss-of-use claims of a claim | Any |
| GET | `/claims/{id}/recovery-cases` | List the recovery cases of a claim | Any |
| GET | `/claims/{id}/communication-logs` | List the communication log entries of a claim | Any |
| POST | `/coverage-verifications` | Create a pending verification, superseding any pending one on the claim | ClaimsAdjuster |
| POST | `/coverage-verifications/{id}/decide` | Decide a pending verification | ClaimsAdjuster |
| POST | `/repair-orders` | Create a repair order under the calling shop | RepairShop |
| GET | `/repair-orders` | List repair orders, optionally filtered by shop | Any |
| GET | `/repair-orders/{id}` | Get a repair order | Any |
| POST | `/repair-orders/{id}/approve` | Approve the estimate | ClaimsAdjuster |
| POST | `/repair-orders/{id}/start` | Start repairs (owning shop only) | RepairShop |
| POST | `/repair-orders/{id}/complete` | Complete repairs, stamping completion from the logical clock | RepairShop |
| POST | `/repair-orders/{id}/milestones` | Report a repair milestone | RepairShop |
| GET | `/repair-orders/{id}/milestones` | List the milestones of a repair order | Any |
| POST | `/rental-reservations` | Book a direct-billed reservation | RentalDeskAgent |
| GET | `/rental-reservations` | List reservations, optionally filtered by partner or repair order | Any |
| GET | `/rental-reservations/{id}` | Get a reservation | Any |
| POST | `/rental-reservations/{id}/authorize` | Authorize a draft reservation against reserve, cap, and fleet | RentalDeskAgent |
| POST | `/rental-reservations/{id}/activate` | Record vehicle pickup (owning partner only) | RentalPartner |
| POST | `/rental-reservations/{id}/return` | Record vehicle return and run unnecessary-day assessment (owning partner only) | RentalPartner |
| POST | `/rental-reservations/{id}/close` | Close a returned reservation once invoices and recoveries are resolved | RentalDeskAgent |
| POST | `/rental-reservations/{id}/cancel` | Cancel a draft or authorized reservation | RentalDeskAgent |
| GET | `/rental-reservations/{id}/extension-requests` | List the extension requests of a reservation | Any |
| GET | `/rental-reservations/{id}/class-changes` | List the class change records of a reservation | Any |
| GET | `/rental-reservations/{id}/invoices` | List the invoices of a reservation | Any |
| POST | `/extension-requests` | Request additional rental days tied to a delay milestone | RentalDeskAgent |
| GET | `/extension-requests` | List extension requests, optionally filtered by milestone | Any |
| GET | `/extension-requests/{id}` | Get an extension request | Any |
| POST | `/extension-requests/{id}/approve` | Approve an extension and apply the day grant | ClaimsAdjuster |
| POST | `/extension-requests/{id}/deny` | Deny an extension, returning the reservation to active | ClaimsAdjuster |
| POST | `/class-changes` | Record a downgrade or upgrade and its cost responsibility split | RentalDeskAgent |
| POST | `/loss-of-use-claims` | Submit a loss-of-use claim for a non-owned vehicle (claimant only) | Customer |
| GET | `/loss-of-use-claims/{id}` | Get a loss-of-use claim | Any |
| POST | `/loss-of-use-claims/{id}/attach-documentation` | Attach cost documentation (claimant only) | Customer |
| POST | `/loss-of-use-claims/{id}/approve` | Approve and compute the payout per the selected variant | ClaimsAdjuster |
| POST | `/loss-of-use-claims/{id}/deny` | Deny a loss-of-use claim | ClaimsAdjuster |
| POST | `/loss-of-use-claims/{id}/pay` | Pay an approved loss-of-use claim | SettlementApprover |
| POST | `/invoices` | Submit a direct-bill invoice (owning partner only) | RentalPartner |
| GET | `/invoices` | List invoices, optionally filtered by partner | Any |
| GET | `/invoices/{id}` | Get an invoice | Any |
| POST | `/invoices/{id}/audit-decision` | Audit a manual-review invoice; dispute opens a recovery case | ClaimsAdjuster |
| POST | `/invoices/{id}/settle` | Settle an approved or resolved-dispute invoice | SettlementApprover |
| GET | `/recovery-cases` | List recovery cases, optionally filtered by reservation | Any |
| GET | `/recovery-cases/{id}` | Get a recovery case | Any |
| POST | `/recovery-cases/{id}/record-payment` | Record a customer recovery payment | RecoverySpecialist |
| POST | `/recovery-cases/{id}/waive` | Waive the outstanding balance of a recovery case | RecoverySpecialist |
| POST | `/communication-logs` | Log a customer communication | RentalDeskAgent |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are defined where each rule lives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PICKUP_DATE_IN_PAST` | 400 Bad Request |
| `ERR_INVALID_PERIOD` | 400 Bad Request |
| `ERR_ACTIVATION_BEFORE_PICKUP_DATE` | 400 Bad Request |
| `ERR_INVALID_DELAY` | 400 Bad Request |
| `ERR_INSUFFICIENT_RESERVE` | 402 Payment Required |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_POLICYHOLDER_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_COVERAGE_VERIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_REPAIR_SHOP_NOT_FOUND` | 404 Not Found |
| `ERR_RENTAL_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_REPAIR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_EXTENSION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_LOSS_OF_USE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_RECOVERY_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_OPEN` | 409 Conflict |
| `ERR_COVERAGE_NOT_VERIFIED` | 409 Conflict |
| `ERR_VERIFICATION_ALREADY_DECIDED` | 409 Conflict |
| `ERR_RESERVATION_INVALID_STATE` | 409 Conflict |
| `ERR_REPAIR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_EXTENSION_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_LOU_INVALID_STATE` | 409 Conflict |
| `ERR_RECOVERY_INVALID_STATE` | 409 Conflict |
| `ERR_PARTNER_SUSPENDED` | 409 Conflict |
| `ERR_REPAIR_ORDER_MISMATCH` | 409 Conflict |
| `ERR_LOU_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_DOCUMENTATION_REQUIRED` | 409 Conflict |
| `ERR_RESERVATION_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_LOU_PERIOD_CONFLICT` | 409 Conflict |
| `ERR_FLEET_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EXTENSION_NOT_JUSTIFIED` | 409 Conflict |
| `ERR_DURATION_CAP_EXHAUSTED` | 409 Conflict |
| `ERR_PENDING_EXTENSION_EXISTS` | 409 Conflict |
| `ERR_RESERVATION_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_CLAIM_SETTLE_BLOCKED` | 409 Conflict |
| `ERR_CLAIM_NOT_SETTLED` | 409 Conflict |
| `ERR_DUPLICATE_POLICY_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_SHOP_CODE` | 409 Conflict |
| `ERR_DUPLICATE_PARTNER_CODE` | 409 Conflict |
| `ERR_DUPLICATE_INVOICE_NUMBER` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

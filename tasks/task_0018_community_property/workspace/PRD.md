# Community Property Management API — Product Requirements Document

## 1. Introduction

A residential community concentrates an unusual number of intersecting concerns under a single operational roof: legal ownership records, household composition, repair workflows, monthly fee collection, shared-amenity reservations, owners-committee governance, and parking allocation. Today these functions live in disconnected spreadsheets and ad-hoc messaging groups — when a fee falls into delinquency, the voting roster does not know; when a tenant moves out, the access-control system keeps issuing entry permissions; when a reservation is damaged, the deposit is forfeited but the spillover charge is forgotten. This API replaces the patchwork with one coherent backend in which every state change emits the right cascade.

The system serves four distinct human roles — property-management staff who run day-to-day operations, owners who hold rights over their properties, maintenance technicians dispatched to repairs, and the committee chair who governs collective decision-making — and integrates with three external systems (the payment channel, the access-control gates, and an instant-messaging notification fabric). Design priorities are, in order: financial correctness (every yuan accounted for and auditable), governance integrity (votes counted exactly once against a frozen eligible roster), and operational throughput (manager actions should not be delayed by recomputation). Internal "test-driving" capabilities — an explicit clock advance and a synthetic event emitter — are first-class endpoints so that time-sensitive auto-transitions (overdue bills, dunning escalation, reservation no-shows, work-order auto-confirmation) can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every inbound request must carry two headers: `X-User-ID`, the caller's stable identifier, and `X-User-Role`, the caller's role. If either header is missing or empty the request is rejected with `ERR_AUTH_MISSING` (HTTP 401). If `X-User-Role` is present but is not one of the four declared role names, the request is rejected with `ERR_AUTH_INVALID_ROLE` (HTTP 401). If the role is valid but is not authorized for the target endpoint, or the role-bound ownership check fails, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Exactly four role names are recognized, each spelled exactly: `PropertyManager`, `Owner`, `MaintenanceStaff`, and `CommitteeChair`.

When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner` entity; ownership checks on any resource that references an `Owner` (a work order whose `reporter_owner_id` does not match, a reservation whose `owner_id` does not match, a parking application or vote whose `owner_id` does not match) compare the resource's foreign-key field to `X-User-ID` and reject mismatches with `ERR_FORBIDDEN`. When `X-User-Role` is `PropertyManager`, `MaintenanceStaff`, or `CommitteeChair`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `assigned_staff_id` on a `WorkOrder` after dispatch, or as `actor_id` on an `AuditEntry`) but does not compare it to any entity's `id`. For `MaintenanceStaff` specifically, once a work order has been dispatched the server enforces that the operator acting on subsequent transitions is the one whose opaque id was recorded as `assigned_staff_id`; this is an equality check between `X-User-ID` and the previously recorded value, not an entity-table lookup.

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

List endpoints accept two query parameters, `limit` and `offset`, both optional. The default `limit` is 10; the minimum is 1 and the maximum is 100. The default `offset` is 0. Results are always sorted by `created_at` in ascending order (and where `created_at` is not present on the entity, by `id` in ascending order as the secondary tiebreaker for repeatable pagination). The response `meta` block includes `limit`, `offset`, `total_count` (the total number of records matching the filter set ignoring pagination), and `has_more` (a boolean indicating whether further pages remain).

### 2.4. Common Resource Properties and Versioning

Every entity carries a server-minted `id` that is a UUID rendered without any type prefix and a `created_at` timestamp recorded as ISO 8601 UTC with three fractional digits. Most entities additionally carry an `updated_at` timestamp (also ISO 8601 UTC with three fractional digits), refreshed on every successful mutation, and a `version` integer that starts at 1 on creation and increments by exactly one with every successful mutation. Three entities are exceptions to this rule and carry only `id` and `created_at`, with neither `updated_at` nor `version`: `PaymentRecord` (a write-once ledger entry), `Vote` (an immutable ballot once cast), `AccessLog` (a gate-event ingest record), and `AuditEntry` (a write-once audit row). For all other entities the `version` field appears on every read.

`PATCH` operations may include a `version` field in the request body to invoke optimistic concurrency control: when present, the server compares the supplied `version` to the entity's current `version` and rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409) on mismatch. When the client omits `version`, the OCC check is skipped and the write proceeds against whatever the current state happens to be.

### 2.5. Nested-Resource Path Resolution

Path parameters are resolved left-to-right. For an endpoint such as a work-order transition addressed by its `id`, the server first checks that the work order exists; only after that check passes does it examine body fields and state preconditions. Any path segment that fails to resolve to an existing entity yields `ERR_NOT_FOUND` (HTTP 404). Body fields that name foreign-key references — `property_id`, `owner_id`, `facility_id`, `rule_id`, `bill_id`, `allocated_space_id` — are checked next; any reference to a non-existent entity yields `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.6. Validation Priority Ordering

When multiple validation classes apply to a single request, they are evaluated in a fixed order so that the returned `error_id` is predictable. Authentication checks come first: `ERR_AUTH_MISSING` precedes `ERR_AUTH_INVALID_ROLE`, which precedes `ERR_FORBIDDEN`. Existence checks come next: path-parameter resolution returning `ERR_NOT_FOUND` precedes body-foreign-key resolution returning `ERR_REFERENCE_NOT_FOUND`. State-machine preconditions returning `ERR_INVALID_STATE` are evaluated next, before any business-rule check. After state checks, business-referential rules (such as voter eligibility and vote uniqueness) are evaluated, then business-temporal rules (slot alignment, slot in past, voting-window coherence, voting-closed), then business-safety (delinquency block) and business-constraint rules (parking quota, parking kind, parking space taken, payment uniqueness, rule-code uniqueness, property uniqueness), and finally business-fiscal rules (payment amount sanity, satisfaction-score range). Within the same category the lower-priority-number rule fires first; this ordering matters most where two checks could plausibly fail on the same request, because tests assert the specific `error_id`.

### 2.7. Hierarchical Consistency, Cascades, and Audit

Every successful mutation refreshes the entity's `updated_at` and increments its `version` by one. Some transitions ripple beyond the directly-mutated row: a resident's move-in or move-out recomputes the parent property's `occupancy_status` to `VACANT`, `OWNER_OCCUPIED`, or `TENANT_OCCUPIED` according to the active resident roster (see §3 for the precedence rule); a fee bill becoming overdue or being waived recomputes the relevant owner's `voting_status` (to `INELIGIBLE_DELINQUENT` or back to `ELIGIBLE`); a parking-application approval flips the chosen `ParkingSpace.status` from `AVAILABLE` to `ALLOCATED` and a termination flips it back to `AVAILABLE`. Every such cascade increments the `version` of each affected entity and refreshes its `updated_at`.

Four classes of mutation additionally append an `AuditEntry` row capturing the `subject_kind` (`FEE_BILL`, `FEE_BILLING_RULE`, `PROPOSAL`, or `VOTE`), the `subject_id`, the `action` string (for example `RATE_CHANGED`, `BILL_WAIVED`, `PROPOSAL_OPENED`, `PROPOSAL_TALLIED_PASSED`, `PROPOSAL_TALLIED_FAILED`, `PROPOSAL_PUBLISHED`, `PROPOSAL_CANCELLED`, `VOTE_CAST`, `RULE_CREATED`), the `actor_role` and `actor_id` taken from the request headers, and `before` / `after` snapshots of the relevant fields. Audit rows are write-once.

### 2.8. Money, Rounding, and Precision

Every monetary calculation in the system rounds to two decimal places using banker-free half-up rounding (a half-cent always rounds up). Rates may be stored to four decimal places, but every emitted amount — `principal_amount`, `late_fee_amount`, `total_due`, `paid_amount`, `monthly_fee`, `damage_deposit`, `damage_amount`, `deposit_held` — is fixed at two decimals on persistence and on read. Where a calculation involves an intermediate factor (a discount multiplier, a proration ratio, a daily-rate accrual), the per-line rounding rule is explicit in §3: the formula rounds the base first, then applies the next factor, then rounds again. This pinning is intentional — sum-then-round and round-each-step diverge by one cent in edge cases, and tests assert the specific cent.

### 2.9. Concurrency Outcomes

Five concurrency contracts hold across the system. When two owners simultaneously book the same facility slot at full capacity, at most `capacity_per_slot` reservations are admitted per `(facility_id, slot_start_at)` pair; the loser is rejected with `ERR_FACILITY_SLOT_FULL` (HTTP 409). When two parking applications race to claim the same `ParkingSpace`, exactly one approval succeeds and the loser receives `ERR_PARKING_SPACE_TAKEN` (HTTP 409); serialization is first-writer-wins on the parking space's status flip from `AVAILABLE` to `ALLOCATED`. When the same owner casts two votes for the same proposal on the same property simultaneously, exactly one row persists per `(proposal_id, property_id)` and the duplicate is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409). When two payments arrive concurrently bearing the same `external_txn_id` on the same `channel`, exactly one `PaymentRecord` persists and the duplicate is rejected with `ERR_DUPLICATE_PAYMENT` (HTTP 409); the `(channel, external_txn_id)` pair is the idempotency key. When a tally and a cancel race against the same proposal after `voting_ends_at` has passed, only tally is admitted and the cancel is rejected with `ERR_INVALID_STATE` (HTTP 409) — the cancel transition out of `OPEN` requires `now()` strictly less than `voting_ends_at`.

### 2.10. External-System Synchronization

Three classes of external interactions are mediated through events. Successful payment reconciliation, parking-application approval, parking-application termination, and proposal publication each emit a synthetic outbound event consumed by the payment, access-control, and IM systems respectively. Inbound gate events from the access-control system are ingested via the access-log endpoint and resolved against parking allocations at the moment of the event; an internal events-emit capability replays such events for testing. The clock-advance capability advances the system's logical clock to a supplied `to` instant and runs every auto-transition due at or before the new instant in chronological order.

## 3. Business Logic & Workflows

### 3.1. Owners, Properties, and the Resident Lifecycle

A community is built bottom-up: a `PropertyManager` operator first registers an `Owner` by submitting `full_name`, `id_card_no`, `household_register_no`, and `phone`; the new owner starts with `voting_status` set to `ELIGIBLE`. The `id_card_no` must be unique across the community — duplicates are rejected. The `household_register_no` is captured because it is the unit of voting eligibility under per-household tallying.

A `Property` is then registered against an existing owner by submitting `building_no`, `unit_no`, `area_sqm`, `owner_id`, and an optional `parking_quota` (which defaults to 1 if omitted). The `(building_no, unit_no)` pair must be unique within the community — re-registering an already-registered unit is rejected with `ERR_DUPLICATE_PROPERTY`. The `area_sqm` must be strictly greater than zero, recorded with up to two decimal places, because it later drives both per-square-meter billing and per-area voting weight. New properties start with `occupancy_status` of `VACANT`.

Residents bind to a property under one of two `relation_kind` values: `FAMILY` (for owner family members) or `TENANT` (for renters). Registration captures `property_id`, `full_name`, `id_card_no`, `relation_kind`, `phone`, and — only when `relation_kind` is `TENANT` — a `lease_end_at` timestamp; `lease_end_at` is required for tenants and ignored for family. New residents start in `lifecycle_status` `PENDING_MOVE_IN`. The combination of `id_card_no`, `property_id`, and `relation_kind` is unique. Move-in and move-out are then driven by manager actions: a move-in transition advances `lifecycle_status` from `PENDING_MOVE_IN` to `RESIDING`, sets `move_in_at` to the current time, and recomputes the parent property's `occupancy_status` using a precedence rule — if any resident currently in `RESIDING` is a tenant the property becomes `TENANT_OCCUPIED`; otherwise if any owner or family resident is in `RESIDING` the property becomes `OWNER_OCCUPIED`; otherwise `VACANT`. For tenants the move-in additionally requires that `lease_end_at` be strictly later than `now()`. A move-out transition advances `lifecycle_status` from `RESIDING` to `MOVED_OUT`, sets `move_out_at` to the current time, recomputes `occupancy_status` again, and re-evaluates the owner's `voting_status` — an owner whose situation previously left them with `voting_status` of `INELIGIBLE_NO_PROPERTY` may be re-classified to `ELIGIBLE`. Attempting to move in a tenant while the relevant owner has any `FeeBill` in `OVERDUE` is rejected with `ERR_OWNER_DELINQUENT`.

### 3.2. The Repair Work-Order Pipeline

A `WorkOrder` is filed by an `Owner` against one of their own properties, capturing `property_id`, `category` (one of `PLUMBING`, `ELECTRICAL`, `STRUCTURAL`, `LANDSCAPING`, `SECURITY`, `OTHER`), a free-form `location_tag` such as the kitchen sink or the lobby ceiling, and an optional list of `photo_urls` (defaulting to an empty list). The reporter's id is recorded as `reporter_owner_id` and the order opens in `status` `SUBMITTED`.

Before the order is dispatched the reporter may withdraw it, transitioning `status` from `SUBMITTED` to `CANCELLED`; the cancel is permitted only when `X-User-ID` matches `reporter_owner_id`. While the order is still in `SUBMITTED`, a `PropertyManager` operator can dispatch it to maintenance: the dispatch body carries `assigned_staff_id` (the opaque id of the `MaintenanceStaff` operator who will receive the work), and on success the order's `assigned_staff_id` is set and `status` advances `SUBMITTED → DISPATCHED`. From `DISPATCHED`, only the named `MaintenanceStaff` may act — the server checks `X-User-ID` against the order's recorded `assigned_staff_id` for both the start and reject transitions. Starting work advances `DISPATCHED → IN_PROGRESS`; rejecting work requires the body to include `rejection_reason` and advances `DISPATCHED → REJECTED` (a terminal state).

Once `IN_PROGRESS`, the assigned maintenance operator marks the order resolved, advancing `IN_PROGRESS → RESOLVED`; this transition stamps `resolved_at` to the current time and sets `confirm_deadline_at` to seventy-two hours after `resolved_at`. From `RESOLVED` three paths are possible. The reporter may close the loop by confirming with a `satisfaction_score` between 1 and 5 inclusive — the body must contain `satisfaction_score`, the server stores it on the order, and `status` advances `RESOLVED → CONFIRMED`; a `satisfaction_score` outside the range is rejected with `ERR_RATING_OUT_OF_RANGE`. Alternatively, while `now()` is still strictly less than `confirm_deadline_at`, the reporter may reopen the order — this clears `assigned_staff_id`, `resolved_at`, and `confirm_deadline_at`, advances `RESOLVED → SUBMITTED`, and increments `WorkOrder.version` to mark the revision cycle. Finally, when the clock advances past `confirm_deadline_at` and the order is still in `RESOLVED`, the system auto-confirms: the order's `satisfaction_score` is set to a baseline value of 5 and `status` advances `RESOLVED → CONFIRMED`. `CONFIRMED`, `REJECTED`, and `CANCELLED` are terminal states; tests will assert that subsequent transition attempts return `ERR_INVALID_STATE`.

### 3.3. Fee Billing Rules and Periodic Issuance

A `FeeBillingRule` defines how a property is charged. A `PropertyManager` creates a rule by submitting a `rule_code` (which must be unique across all currently-`ACTIVE` rules — a duplicate yields `ERR_DUPLICATE_RULE_CODE`), a `kind` of either `PER_SQM_MONTHLY` (rate expressed as yuan per square meter per month) or `FIXED_AMOUNT_MONTHLY` (rate expressed as a flat monthly yuan amount), and a `rate` greater than or equal to zero (with up to four decimal places permitted on the rate itself). Two further configuration knobs default sensibly but may be overridden at creation: `late_fee_daily_rate` is the daily late-fee fraction of principal, bounded between 0 and 0.01 inclusive and defaulting to 0.0005, while `late_fee_cap_pct` is the maximum cumulative late-fee fraction of principal, bounded between 0 and 1 inclusive and defaulting to 0.30 (in plain words: late fees can never grow beyond thirty percent of the bill's principal). New rules open in `rule_status` `ACTIVE`; only `ACTIVE` rules generate bills, while a rule in `rule_status` `ARCHIVED` is retained for historical reference but does not contribute to issuance. Rate adjustments are made through a partial update accepting `rate`, `late_fee_daily_rate`, `late_fee_cap_pct`, and an optional `version` for optimistic concurrency; every successful update appends an `AuditEntry` with `subject_kind` of `FEE_BILLING_RULE` and `action` of `RATE_CHANGED`, capturing the before-and-after snapshot.

Bill issuance for a billing period is a manager-driven batch operation accepting `period_year` and `period_month` and producing a list of fresh `FeeBill` rows — one per `(property, active rule)` combination matching the period. Each new bill captures `property_id`, `rule_id`, `period_year`, `period_month`, computes its `principal_amount` via the principal calculation described in §3.4, sets `due_date` to fourteen days after the last day of the issuance month (in plain words: a fourteen-day grace period after month end), and opens with `status` of `OPEN`, `paid_amount` of 0, `late_fee_amount` of 0, `total_due` equal to `principal_amount`, and `dunning_stage` of `NONE`.

### 3.4. Computing the Bill Principal

The principal amount on a fee bill is computed at issuance time and pinned into `principal_amount` so that subsequent rate changes do not retroactively rewrite history. The computation has two variants depending on the billing rule's `kind`. Under the `PER_SQM_MONTHLY` variant, the base figure is the rule's `rate` multiplied by the property's `area_sqm`, with that product rounded half-up to two decimal places before any further factor is applied. Under the `FIXED_AMOUNT_MONTHLY` variant, the base figure is simply the rule's `rate` rounded half-up to two decimal places.

A discount tier is then applied on top of the rounded base. If — and only if — the same owner has had twelve consecutive months of `PAID` bills immediately preceding this billing period, a discount of five percent is applied; otherwise the discount fraction is zero. The discount lookback window is fixed at twelve months and the discount fraction is fixed at five percent. The principal is then the rounded base multiplied by one minus the discount fraction, with the product rounded half-up again to two decimal places. The two-step rounding is deliberate: the per-line rounding pinned into the formula yields different cents in edge cases compared to a single sum-then-round pass, and the spec is the per-line variant.

A second variant of the principal calculation governs the first-month bill that follows the approval of a `FIXED` parking allocation mid-month. In that case the principal is the parking space's `monthly_fee` multiplied by the proration ratio (the number of days remaining in the current month divided by the number of days in that month), with the product rounded half-up to two decimal places. The number of days remaining in the month is computed as the number of days in the month minus the day-of-month of `started_at` plus one — meaning the `started_at` day itself counts as a full day of allocation. The twelve-month consecutive-payment discount does not apply to parking fees.

### 3.5. Late-Fee Accrual, Overdue Transitions, and Dunning

Each clock advance examines every fee bill currently in `OPEN` or `OVERDUE` and refreshes its late-fee position. The number of days overdue is the floor of the elapsed days between `due_date` and the relevant evaluation instant, but never less than zero. The relevant evaluation instant is itself the smaller of the current time and the `payment_freeze_at` instant — the latter being the timestamp of the first reconciled payment that brings `paid_amount` up to or above `total_due`. Until that fully-reconciling payment lands, the days-overdue counter accrues against the present moment; once the bill reaches `PAID` or `WAIVED`, the counter is frozen at the freeze instant and the late fee never moves again.

The raw late charge is then the bill's `principal_amount` multiplied by the rule's `late_fee_daily_rate` multiplied by the days-overdue count, rounded half-up to two decimal places. A cap is computed in parallel as the principal multiplied by the rule's `late_fee_cap_pct`, also rounded half-up to two decimal places. The bill's `late_fee_amount` is the smaller of the raw charge and the cap, and `total_due` is the sum of `principal_amount` and `late_fee_amount` rounded half-up to two decimal places. While the bill is in `OPEN`, `OVERDUE`, or `PARTIALLY_PAID`, this recomputation also runs on every read. Once the bill is `PAID` or `WAIVED` the frozen variant of the formula applies and the read is a pure load.

When the clock advances past `due_date` while the bill is still `OPEN` and `paid_amount` remains below `total_due`, the bill transitions `OPEN → OVERDUE`. That transition triggers the late-fee recompute described above, sets `dunning_stage` to `REMINDED` if it was previously `NONE`, and recomputes the relevant owner's `voting_status` — any owner with at least one fee bill in `OVERDUE` against any of their properties is set to `INELIGIBLE_DELINQUENT`. Subsequent clock advances continue to escalate dunning while the bill remains `OVERDUE`: once the current time exceeds `due_date` plus thirty days and the current `dunning_stage` is `REMINDED`, the stage advances to `ESCALATED`; once the current time exceeds `due_date` plus sixty days and the stage is `ESCALATED`, it advances to `LEGAL_NOTICE`. These dunning advances do not change the bill's `status` — they are self-loops on `OVERDUE` that mutate `dunning_stage` only. A manager waiver is also possible from any non-terminal status: it requires a `reason` in the body, advances `status` to `WAIVED`, appends an `AuditEntry` with `action` `BILL_WAIVED`, and recomputes the affected owner's `voting_status` (which may flip back to `ELIGIBLE` if no other bills are overdue).

### 3.6. Payments and Reconciliation

Payments arrive via the payment endpoint and persist as `PaymentRecord` rows carrying `bill_id`, `channel` (one of `WECHAT`, `ALIPAY`, `BANK_TRANSFER`, `CASH`), `external_txn_id`, `amount`, and `paid_at` (the timestamp from the upstream payment provider). The `(channel, external_txn_id)` pair is the idempotency key — two payments bearing the same pair are rejected with `ERR_DUPLICATE_PAYMENT`. The `amount` must be strictly greater than zero and no greater than ten times the bill's current `total_due` as a sanity bound; payments outside that range are rejected with `ERR_PAYMENT_AMOUNT_INVALID`. New records start with `reconciliation_status` of `PENDING` and advance to `RECONCILED` once they have been credited to the bill (the alternative `DISPUTED` state is reserved for downstream dispute workflows).

Reconciling a payment updates the bill's `paid_amount` and drives the bill's `status` per the following rules. While the bill is in `OPEN` and the cumulative `paid_amount` is strictly between zero and `total_due`, the bill transitions `OPEN → PARTIALLY_PAID` (only if `now()` is at or before `due_date` — partial payments arriving after the due date are recognized but the bill remains `OVERDUE`). While the bill is in `OVERDUE` and the cumulative `paid_amount` is strictly between zero and `total_due`, the bill transitions `OVERDUE → PARTIALLY_PAID` and the late-fee figure is recomputed at the reconciliation timestamp. Once `paid_amount` is at or above `total_due`, the bill advances to `PAID` from whichever non-terminal state it currently occupies — `OPEN → PAID`, `OVERDUE → PAID`, or `PARTIALLY_PAID → PAID`. The `PAID` transition freezes `late_fee_amount` at its current value, resets `dunning_stage` to `NONE`, and recomputes the relevant owner's `voting_status` (which may flip back to `ELIGIBLE` if no other bills are overdue). Every reconciliation also emits an outbound IM event so that the owner is notified.

### 3.7. Facility Reservations and Deposit Settlement

A `Facility` is created by a `PropertyManager` with `facility_type` (one of `CLUBHOUSE`, `GYM`, `MEETING_ROOM`), a `name` (unique within the community), `slot_minutes` (the length of one bookable slot, restricted to one of 30, 60, 120, 180, or 240), and three optional knobs that default sensibly: `capacity_per_slot` (the number of simultaneous reservations per slot, at least 1, defaulting to 1), `cancellation_window_hours` (defaulting to 24), and `damage_deposit` (defaulting to 0).

An `Owner` books a slot by submitting `facility_id`, `slot_start_at`, and `slot_end_at`. The slot length must equal the facility's `slot_minutes` exactly, and `slot_start_at` must be aligned to the facility's slot grid (zero-base — meaning a 60-minute slot must start on the hour, a 120-minute slot every two hours from midnight, and so on); a misaligned slot or a length mismatch is rejected with `ERR_SLOT_MISALIGNED`. The `slot_start_at` must be strictly later than `now()` — a past slot is rejected with `ERR_SLOT_IN_PAST`. The number of currently non-terminal reservations on the same facility for the same `slot_start_at` must remain at or below `capacity_per_slot`; an attempt that would push the count past the cap is rejected with `ERR_FACILITY_SLOT_FULL`. An owner with at least one fee bill in `OVERDUE` is blocked from booking with `ERR_OWNER_DELINQUENT`. On successful booking the reservation opens in `status` `BOOKED`, and `deposit_held` is initialized to the facility's `damage_deposit`.

The reservation's onward path branches by outcome. Check-in is performed by the booking owner once `slot_start_at` has arrived but `slot_end_at` has not yet passed — the server requires `slot_start_at` at or before `now()` and `now()` strictly less than `slot_end_at` — and advances `BOOKED → CHECKED_IN`. A cancel by the booking owner from `BOOKED` always succeeds (provided `slot_start_at` has not yet passed in business sense), advances `BOOKED → CANCELLED`, sets `cancellation_at` to the current time, and settles the deposit per the cancellation rule below. If the clock advances past `slot_end_at` while the reservation is still in `BOOKED`, the system auto-transitions `BOOKED → NO_SHOW` and forfeits the entire `deposit_held`. From `CHECKED_IN`, a `PropertyManager` close action is permitted only once `slot_end_at` has been reached (`now() >= slot_end_at`), and branches on a `damage_amount` body parameter: when `damage_amount` is omitted or equal to zero the reservation transitions `CHECKED_IN → COMPLETED`; when `damage_amount` is strictly greater than zero the reservation transitions `CHECKED_IN → DAMAGED`.

Deposit settlement at closure follows a waterfall. For a cancellation made at or before the cutoff `slot_start_at` minus `cancellation_window_hours` (in plain words: cancellations made at least the configured window of hours before the slot starts), the full `deposit_held` is refunded and nothing is forfeited. For a cancellation made after that cutoff, fifty percent of `deposit_held` is refunded — `deposit_held` is replaced by `round(deposit_held * 0.5, 2)` using half-up rounding, the same amount is recorded as forfeited, and the difference between the original and the refunded portion is the forfeited share. For a `NO_SHOW` outcome the entire `deposit_held` is forfeited and the held figure is then set to zero. For a `COMPLETED` outcome the full `deposit_held` is refunded. For a `DAMAGED` outcome the deposit absorbs damages up to its value: the forfeited amount is the smaller of `deposit_held` and `damage_amount`, the refunded amount is `deposit_held` minus that absorbed amount (rounded half-up to two decimal places), and if `damage_amount` is strictly greater than `deposit_held` the spillover (the difference between `damage_amount` and `deposit_held`, rounded half-up to two decimals) becomes a fresh fee bill of `kind` `FIXED_AMOUNT_MONTHLY` whose `principal_amount` is the spillover figure and whose `due_date` is fourteen days from the moment of closure. The audited invariant is that the originally-held deposit equals the sum of the refund and the forfeit; the spillover is a separate bill, not a deposit allocation.

### 3.8. Owners-Committee Proposals and Voting

A `CommitteeChair` drafts a `Proposal` with a `title`, a `voting_method` (either `PER_HOUSEHOLD` or `PER_AREA`), an optional `pass_threshold_pct` (between 0.5 and 1.0 inclusive, defaulting to 0.6667), and a voting window expressed as `voting_starts_at` (the inclusive open instant) and `voting_ends_at` (the exclusive close instant). New proposals open in `status` `DRAFT`. The chair then opens voting, advancing `status` `DRAFT → OPEN`; this transition requires `voting_starts_at` to be strictly earlier than `voting_ends_at` and `voting_ends_at` to be strictly later than `now()` — a malformed window is rejected with `ERR_VOTING_WINDOW_INVALID`.

Opening a proposal freezes the eligible voter list. The eligible list is the set of `Owner` rows whose `voting_status` is `ELIGIBLE` at the open instant; later changes to anyone's `voting_status` (such as a delinquency that develops mid-vote, or a new owner registered after open) do not retroactively change the list. The proposal's `eligible_weight_total` is computed by summing the per-property weight across the eligible voter list and frozen at this moment. Under the `PER_HOUSEHOLD` variant of the tally calculation, each property contributes weight 1.0 regardless of its area; under the `PER_AREA` variant, each property contributes weight equal to its `area_sqm`, and `eligible_weight_total` is therefore the total area across eligible properties.

Owners cast votes by submitting `property_id` and `choice` (one of `YES`, `NO`, `ABSTAIN`). A vote requires the proposal to be `OPEN` and `now()` to be at or after `voting_starts_at` and strictly before `voting_ends_at`; votes outside that window are rejected with `ERR_VOTING_CLOSED`. The voter must have been on the frozen eligible list — a brand-new owner registered after open or a delinquent owner whose status flipped before open cannot vote, and is rejected with `ERR_VOTER_NOT_ELIGIBLE`. Exactly one vote is allowed per `(proposal_id, property_id)` pair; a duplicate is rejected with `ERR_DUPLICATE_VOTE`. On cast, the server records `voter_owner_id`, `property_id`, and `choice`, freezes the per-property `weight` at the current voting-method's rate (`1.0` for `PER_HOUSEHOLD`, the property's `area_sqm` for `PER_AREA`), updates the proposal's running `yes_weight` or `no_weight`, and appends an `AuditEntry` with `subject_kind` of `VOTE` and `action` of `VOTE_CAST`.

After `voting_ends_at` has passed the chair tallies. The chair-driven tally requires the proposal to be `OPEN` and `now()` to be at or after `voting_ends_at`. The tally aggregates `yes_weight` as the sum of the `weight` of every vote whose `choice` is `YES`, and `no_weight` as the sum of the `weight` of every vote whose `choice` is `NO`; `ABSTAIN` votes count toward turnout but do not contribute to either total. The pass test compares the ratio of `yes_weight` to the frozen `eligible_weight_total` — denominator is the frozen eligible total, never the sum of cast votes — against `pass_threshold_pct`: if the ratio is greater than or equal to the threshold the proposal transitions `OPEN → TALLIED_PASSED`; otherwise it transitions `OPEN → TALLIED_FAILED`. A non-vote contributes nothing to the numerator and is therefore equivalent to a NO in effect on outcome. The publish action accepts a proposal in either `TALLIED_PASSED` or `TALLIED_FAILED` and advances to `PUBLISHED`, sets `published_at` to the current time, appends an `AuditEntry` with `action` `PROPOSAL_PUBLISHED`, and emits an outbound IM event for community-wide notification. The chair may also cancel a proposal: cancellation from `DRAFT` is unconditional; cancellation from `OPEN` requires `now()` to be strictly less than `voting_ends_at` (after the close instant the cancel competes with tally and is rejected with `ERR_INVALID_STATE`) and appends an `AuditEntry` with `action` `PROPOSAL_CANCELLED`. `PUBLISHED` and `CANCELLED` are terminal.

### 3.9. Parking Allocation, Plate Binding, and Gate Events

A `ParkingSpace` is registered by a `PropertyManager` with a `space_no` (unique within the community), a `kind` of `FIXED`, `TEMPORARY`, or `VISITOR`, and a `monthly_fee` (only meaningful for `FIXED` spaces; defaulting to zero and ignored for `TEMPORARY` and `VISITOR`). New spaces open in `status` `AVAILABLE`; the parking space's `status` may also take the values `RESERVED` (held for an in-progress allocation), `ALLOCATED` (currently bound to an approved application), and `UNAVAILABLE` (taken out of service for maintenance or other operational reasons). An `Owner` then submits a `ParkingApplication` carrying `property_id`, `requested_kind` (one of `FIXED`, `TEMPORARY`, `VISITOR`), and `license_plate`; the application opens in `status` `PENDING`. Owners with any fee bill in `OVERDUE` are blocked from filing parking applications with `ERR_OWNER_DELINQUENT`.

A `PropertyManager` resolves a `PENDING` application either by rejecting it (the body must include a `rejection_reason`, advancing `PENDING → REJECTED`) or by approving it (the body must include `allocated_space_id`, the chosen `ParkingSpace.id`, advancing `PENDING → APPROVED`). Approval is gated by four business checks evaluated in order: the chosen parking space must exist and have `status` of `AVAILABLE` at approval time (otherwise `ERR_PARKING_SPACE_TAKEN`); the parking space's `kind` must match the application's `requested_kind` (otherwise `ERR_PARKING_KIND_MISMATCH`); when `requested_kind` is `FIXED`, the count of currently-`APPROVED` `FIXED` applications already bound to the same property must be strictly less than the property's `parking_quota` (otherwise `ERR_PARKING_QUOTA_EXCEEDED`); and the requesting owner must not be in `voting_status` `INELIGIBLE_DELINQUENT` (otherwise `ERR_FORBIDDEN` — fixed allocations are blocked while delinquent). On successful approval the application's `allocated_space_id` is set, `started_at` is set to the current time, and the parking space's `status` flips from `AVAILABLE` to `ALLOCATED`. When the approved `requested_kind` is `FIXED`, a first-month prorated fee bill is scheduled per the parking variant of the principal calculation in §3.4 — `principal_amount` becomes the parking space's `monthly_fee` multiplied by the days-remaining-in-month over days-in-month ratio, rounded half-up to two decimal places. Approval also emits an outbound access-control sync event so that the gate system learns the new plate-to-space binding.

A `PropertyManager` may terminate an `APPROVED` allocation, advancing `APPROVED → TERMINATED`; on termination the parking space's `status` flips back to `AVAILABLE` and an outbound access-control sync event is emitted. Outstanding parking fee bills in `OPEN` or `OVERDUE` are not auto-waived on termination — the operator must waive them explicitly through the bill-waiver workflow.

Gate events arrive through the access-log ingestion endpoint with `license_plate`, `direction` (one of `ENTRY` or `EXIT`), and `occurred_at` (the timestamp from the access-control system). On ingest the server resolves `parking_space_id` by looking up the active parking allocation whose `license_plate` matches the captured plate and whose `started_at` is at or before `occurred_at`; if a `FIXED` or `TEMPORARY` allocation is found the `classification` is set to `BOUND` and the resolved space id is recorded. If no plate-bound allocation matches but a `VISITOR` space is allocated to a parking application that authorizes the plate, the `classification` is `VISITOR_OK`. Otherwise `parking_space_id` is null and the `classification` is `UNAUTHORIZED`.

### 3.10. The Logical Clock, Auto-Transitions, and the Audit Trail

Time-driven transitions in the system are deterministic and ordered: a clock-advance capability accepts a `to` instant in the body and runs every auto-transition due at or before the new clock value, in chronological order. Four classes of auto-transitions are evaluated on every advance: a `FeeBill` whose `now() > due_date` and whose `paid_amount < total_due` advances `OPEN → OVERDUE` and accrues late-fees per §3.5; a `FeeBill` already in `OVERDUE` whose dunning stage is due to escalate progresses to the next dunning level; a `WorkOrder` in `RESOLVED` whose `now() >= confirm_deadline_at` auto-confirms with a baseline `satisfaction_score` of 5; and a `Reservation` in `BOOKED` whose `now() >= slot_end_at` auto-transitions to `NO_SHOW` and forfeits its `deposit_held`. A separate synthetic events-emit capability accepting a `source` and a `payload` is provided for replaying external events (payment-channel webhooks, access-control gate events, and IM acknowledgements) so that integration testing can reach the same code paths as natural inbound traffic.

Audit trails are queried through the audit-entries listing capability with optional `subject_kind` and `subject_id` filters in addition to standard pagination; an audit query is permitted to `PropertyManager` and `CommitteeChair` operators. Every audit row records `subject_kind`, `subject_id`, `action`, `actor_role`, `actor_id`, and `before` and `after` snapshots, in addition to the standard `id` and `created_at`. The actions logged include rule creation (`RULE_CREATED`), rate changes (`RATE_CHANGED`), bill waivers (`BILL_WAIVED`), proposal lifecycle events (`PROPOSAL_OPENED`, `PROPOSAL_TALLIED_PASSED`, `PROPOSAL_TALLIED_FAILED`, `PROPOSAL_PUBLISHED`, `PROPOSAL_CANCELLED`), and votes (`VOTE_CAST`).

## 4. Endpoint Definitions

All endpoints below are mounted under `/communities`. New-resource creation endpoints respond with HTTP 201; in-place transitions and updates respond with HTTP 200; the synthetic events-emit capability responds with HTTP 202 to indicate asynchronous acceptance. Successful response bodies follow the §2.2 envelope and, except where noted in §3, return the created or updated resource in `data`. Error responses follow the §2.2 error envelope.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /communities/owners | Register a new owner. | PropertyManager |
| GET | /communities/owners | List owners with optional filters. | PropertyManager, CommitteeChair |
| GET | /communities/owners/{id} | Get one owner. | PropertyManager, CommitteeChair, Owner |
| POST | /communities/properties | Register a property and bind owner. | PropertyManager |
| GET | /communities/properties/{id} | Get one property. | PropertyManager, Owner |
| POST | /communities/residents | Register a resident (FAMILY or TENANT). | PropertyManager |
| POST | /communities/residents/{id}/move-in | Mark resident as moved in. | PropertyManager |
| POST | /communities/residents/{id}/move-out | Mark resident as moved out. | PropertyManager |
| POST | /communities/work-orders | Owner submits a repair work order. | Owner |
| POST | /communities/work-orders/{id}/dispatch | Dispatch to maintenance staff. | PropertyManager |
| POST | /communities/work-orders/{id}/start | Maintenance begins work. | MaintenanceStaff |
| POST | /communities/work-orders/{id}/reject | Maintenance rejects assignment. | MaintenanceStaff |
| POST | /communities/work-orders/{id}/resolve | Maintenance marks work resolved. | MaintenanceStaff |
| POST | /communities/work-orders/{id}/confirm | Owner confirms with satisfaction rating. | Owner |
| POST | /communities/work-orders/{id}/reopen | Owner reopens within confirm window. | Owner |
| POST | /communities/work-orders/{id}/cancel | Owner cancels before dispatch. | Owner |
| POST | /communities/fee-billing-rules | Create active billing rule. | PropertyManager |
| PATCH | /communities/fee-billing-rules/{id} | Update rate or late-fee configuration. | PropertyManager |
| POST | /communities/fee-bills/issue | Issue bills for a (year, month) period. | PropertyManager |
| GET | /communities/fee-bills/{id} | Get bill including refreshed total_due. | PropertyManager, Owner |
| GET | /communities/fee-bills | List bills with filters. | PropertyManager, Owner |
| POST | /communities/fee-bills/{id}/waive | Waive a bill. | PropertyManager |
| POST | /communities/payments | Record a payment from external channel. | PropertyManager, Owner |
| POST | /communities/facilities | Create a facility. | PropertyManager |
| POST | /communities/reservations | Owner books a slot. | Owner |
| POST | /communities/reservations/{id}/check-in | Owner checks in at slot start. | Owner |
| POST | /communities/reservations/{id}/cancel | Owner cancels. | Owner |
| POST | /communities/reservations/{id}/close | Manager closes after slot end. | PropertyManager |
| POST | /communities/proposals | Submit a proposal in DRAFT. | CommitteeChair |
| POST | /communities/proposals/{id}/open | Open voting; freeze eligible voter list. | CommitteeChair |
| POST | /communities/proposals/{id}/votes | Cast a vote on an open proposal. | Owner |
| POST | /communities/proposals/{id}/tally | Tally votes after voting_ends_at. | CommitteeChair |
| POST | /communities/proposals/{id}/publish | Publish result. | CommitteeChair |
| POST | /communities/proposals/{id}/cancel | Cancel a proposal before voting_ends_at. | CommitteeChair |
| GET | /communities/proposals/{id} | Get proposal with current tally state. | PropertyManager, CommitteeChair, Owner |
| POST | /communities/parking-spaces | Register a parking space. | PropertyManager |
| POST | /communities/parking-applications | Owner applies for parking. | Owner |
| POST | /communities/parking-applications/{id}/approve | Approve and allocate a parking space. | PropertyManager |
| POST | /communities/parking-applications/{id}/reject | Reject a pending application. | PropertyManager |
| POST | /communities/parking-applications/{id}/terminate | Terminate an active allocation. | PropertyManager |
| POST | /communities/access-logs | Ingest entry/exit gate event. | PropertyManager |
| GET | /communities/audit-entries | List audit entries with filters. | PropertyManager, CommitteeChair |
| POST | /communities/_clock/advance | Advance system clock and run auto-transitions. | PropertyManager |
| POST | /communities/_events/emit | Emit a synthetic external event. | PropertyManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VOTER_NOT_ELIGIBLE | 403 |
| ERR_DUPLICATE_VOTE | 409 |
| ERR_VOTING_CLOSED | 409 |
| ERR_VOTING_WINDOW_INVALID | 422 |
| ERR_SLOT_MISALIGNED | 422 |
| ERR_SLOT_IN_PAST | 422 |
| ERR_FACILITY_SLOT_FULL | 409 |
| ERR_OWNER_DELINQUENT | 403 |
| ERR_PARKING_QUOTA_EXCEEDED | 422 |
| ERR_PARKING_KIND_MISMATCH | 422 |
| ERR_PARKING_SPACE_TAKEN | 409 |
| ERR_DUPLICATE_PAYMENT | 409 |
| ERR_PAYMENT_AMOUNT_INVALID | 422 |
| ERR_RATING_OUT_OF_RANGE | 422 |
| ERR_DUPLICATE_RULE_CODE | 409 |
| ERR_DUPLICATE_PROPERTY | 409 |
| ERR_VERSION_CONFLICT | 409 |

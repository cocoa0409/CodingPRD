# Grain Drying & Conditioning API — Product Requirements Document

## 1. Introduction

Every harvest, the same crisis plays out at the country elevator: trucks arrive faster than the dryer can run, every grower believes their lot is the most urgent, and every bushel that crosses the scale carries two numbers that will be argued about later — the moisture going in and the weight coming out. The elevator's exposures are concrete. Wet grain above the dryer's safe intake limit can damage equipment or product. Formula-estimated shrink rarely matches the certified scale-out weight, and the delta becomes a dispute. Gas burned per run is a real cost that must be passed through fairly. Growers who abandon dried grain in the bin leave the elevator holding title questions, not just inventory.

This document specifies the Grain Drying & Conditioning API, mounted under `/grain-drying`, which governs that entire operation: scale intake and moisture certification with grower-disputable results, versioned drying-charge tariffs, a queue-ticket system that allocates finite daily dryer throughput across service classes with harvest-peak preemption, dryer runs with metered or estimated energy pass-through, weight reconciliation between provisional estimates and certified weights, post-drying storage with accrual and default-driven title transfer, blending of two dried lots to a contract moisture, damage claims with independent adjustment, and billing built on a prepaid ledger with invoice receivables. The system's consistency model is immediate: every mutation is visible in its own response, and all derived fields are recomputed synchronously as part of the operation that triggers them.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and cross-cutting policies that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The API recognizes exactly five roles: `Grower`, `IntakeTechnician`, `DryerOperator`, `ClaimsAdjuster`, and `ElevatorManager`. A request with missing or malformed headers is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

What `X-User-ID` means depends on the role. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a customer — a grain lot, queue ticket, damage claim, storage agreement, invoice, or payment — compare the resource's customer reference to `X-User-ID`, and a grower touching another account's resource is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). The customer reference of a grain lot is its `customer_id`; of a queue ticket, moisture test, dryer run, or damage claim, its lot's `customer_id`; of a blend order, its high-moisture lot's `customer_id`; of a storage agreement, its `owner_id`; of an invoice, its `customer_id`; of a payment, its invoice's `customer_id`. Growers therefore read and act only on their own account's resources, even on endpoints where the role itself is authorized.

When `X-User-Role` is `IntakeTechnician`, `DryerOperator`, `ClaimsAdjuster`, or `ElevatorManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires attribution — for example as `tested_by_user_id` and `certified_by_user_id` on a moisture test, `operator_user_id` on a dryer run, `reviewed_by_user_id` and `assessed_by_user_id` on a damage claim, or `created_by_user_id` and `approved_by_user_id` on a blend order — but it never compares these operator identifiers to any entity's `id`. Segregation-of-duties rules compare operator identifiers to each other, never to customers (§2.8).

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

Requests that match no defined route yield `ERR_NOT_FOUND` (HTTP 404), a defined path called with an unsupported method yields `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure yields `ERR_INTERNAL` (HTTP 500); all three use the same error envelope.

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items before returning the page and defaults to 0. Out-of-range values are clamped, not rejected: a `limit` below 1 is raised to 1, a `limit` above 100 is lowered to 100, and a negative `offset` is raised to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Calendar Dates

The service keeps its own logical clock rather than trusting wall-clock time, so that harvest scenarios can be replayed deterministically. Before any adjustment, the clock starts at 2026-08-01T00:00:00Z. An ElevatorManager-only test-driving capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc` reading. Instants supplied without a timezone offset are read as UTC, and instants the API records — scheduled run windows among them — are stored normalized to UTC ISO 8601 with three fractional digits.

Everything the API calls "now" is drawn from this clock: a moisture test's `certified_at`, an invoice's `issued_at`, a run's `actual_start` and `actual_end`, and the "current date" used in ticket-window checks and storage accrual. Calendar-date fields such as `window_date`, `effective_from`, `effective_to`, `period_start`, and `period_end` use the YYYY-MM-DD form and are compared against the logical clock's current date. Advancing the clock past a PENDING queue ticket's `window_date` expires the ticket — its status becomes EXPIRED with no further effect.

### 2.5. Common Resource Properties

Every resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was created. Every resource except Payment additionally carries `updated_at`, an ISO 8601 UTC timestamp refreshed on any change to the resource, and `version`, a system-managed integer that increments by one on every mutation. Payment records are immutable ledger entries and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. An update call that changes nothing — a PATCH whose body names no revisable field, or whose revisable fields are null — still refreshes `updated_at` and advances `version`.

Mutations include system-driven cascades and derived-field recomputation, not just direct client writes: when completing a dryer run rewrites a lot's weights and status, when a claim payment moves an invoice's due, or when a storage default clears a lot's owner, each affected resource's `updated_at` refreshes and its `version` advances. Once a resource reaches a terminal state, further transition attempts on it are rejected with `ERR_ALREADY_TERMINAL` (HTTP 409).

### 2.6. Weigh-Station Units and Numerical Precision

Weights are integer pounds. Moisture percentages, foreign-material percentages, rates per bushel, and therm readings are numbers, carried at the precision each rule in §3 states. All money is integer cents.

Three precision conventions hold wherever a calculation appears in §3. First, the rounding method is always round half up, applied only where a rule names it — multi-step calculations keep full precision in their intermediate values and never round early. Second, where a rule fixes a value to two decimal places (a shrink percentage, a bushel figure, a blend moisture), that rounding happens exactly once, at the named step. Third, where a minimum floor exists (the drying charge's minimum, the storage minimum-days floor), the floor is applied last, after all other arithmetic and rounding.

Bushel figures come from per-commodity pounds-per-bushel constants, given where each calculation uses them in §3: 56 pounds per bushel for CORN and 60 pounds per bushel for both SOYBEAN and WHEAT.

### 2.7. Optimistic Concurrency Control and Version Pins

Two write operations require the caller to declare what version of a parent resource they last observed, and a third pins a tariff version. No other endpoint takes a version field.

Creating a moisture test requires the request to carry `expected_grain_lot_version`, the client's last observed `version` of the target grain lot. If the lot's current version does not equal the declared value, the create is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). This captures the case where another writer has just created or certified a test for the same lot — legitimately moving the lot's governing-moisture baseline forward — so the current writer's view of the lot is stale. Note that creating a moisture test itself increments the lot's version by one, so two tests opened against the same observed version cannot both succeed.

Posting a payment against an invoice requires `expected_invoice_version`, the client's last observed `version` of that invoice. A mismatch with the invoice's current version is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412). Payments legitimately stack against the same invoice; the check prevents a client from applying cash against an `amount_due_cents` it has not observed. Posting a payment increments the invoice's version by one.

Issuing an invoice observes a tariff rather than the invoice itself: the request carries `pinned_schedule_version`, which must equal the current version of the charge schedule the draft was composed against. A mismatch is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 409 — not 412). Revising a schedule's rates bumps that schedule's version, which is exactly what breaks outstanding issue pins.

### 2.8. Segregation of Duties

Three workflows forbid the same operator from occupying two chairs, and each violation is an HTTP 403:

- Damage claims: the operator who reviews, assesses, or denies a claim must differ from the operator who filed it, and the assessor must additionally differ from the dryer operator who ran the implicated run. Violations are rejected with `ERR_CLAIM_SO_DUTY_VIOLATION`.
- Moisture disputes: when a lot's current certified test stands DISPUTED, the technician who certifies the retest must differ from the technician who certified the disputed test. Violations are rejected with `ERR_RETEST_SO_DUTY_VIOLATION`.
- Blend orders: the manager who approves a blend order must differ from the manager who created it. Violations are rejected with `ERR_BLEND_APPROVER_CONFLICT`.

### 2.9. Reference Resolution and the Order of Validation

Requests are validated in a fixed order, and a failure at an earlier gate masks every later one — a request never reports a business-rule violation it would also have failed on authentication. The order is:

1. Header authentication — missing or malformed `X-User-Role` / `X-User-ID` yields `ERR_UNAUTHENTICATED`.
2. Role authorization — a role not listed for the endpoint yields `ERR_UNAUTHORIZED_ROLE`.
3. Reference existence — path identifiers resolve first, in left-to-right order as they appear in the URL, then foreign-key identifiers in the request body, resolved in the order the endpoint's workflow narrative in §3 names them (for a dryer run, for example: `unit_id`, then `lot_id`, then `queue_ticket_id`). Each unresolvable reference yields its own 404: `ERR_CUSTOMER_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_TEST_NOT_FOUND`, `ERR_SCHEDULE_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_BLEND_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, or `ERR_PAYMENT_NOT_FOUND`. A payment posted under a nonexistent invoice identifier, for example, fails with `ERR_INVOICE_NOT_FOUND` before the body is examined.
4. Grower ownership — a grower scoped to a resource of another account yields `ERR_FORBIDDEN_OWNERSHIP`. Because ownership is read from the resolved resource, this gate necessarily follows reference existence: a grower naming another account's existing lot is forbidden, while a nonexistent identifier yields its 404 regardless of the caller's role.
5. Request shape — required fields present, types valid, enum values legal, `gross_weight_lbs` greater than `tare_weight_lbs` with `tare_weight_lbs` positive, monetary amounts positive, `sample_moisture_pct` strictly between 0 and 60, and a lot's `target_moisture_pct` between 10.0 and 20.0 inclusive. Violations yield `ERR_INVALID_REQUEST` (HTTP 400).
6. State permission — the target resource must be in a state permitting the operation; terminal resources reject further transitions (`ERR_ALREADY_TERMINAL`), a lot on DAMAGE_HOLD blocks load-out, ticket operations, and blending (`ERR_LOT_ON_DAMAGE_HOLD`), payments land only on ISSUED invoices (`ERR_INVOICE_NOT_ISSUED`), close and default apply only to ACTIVE agreements (`ERR_AGREEMENT_NOT_ACTIVE`), and a lot may carry no second non-terminal storage agreement (`ERR_DUPLICATE_ACTIVE_AGREEMENT`). Other state mismatches yield `ERR_INVALID_STATE` (all HTTP 409).
7. Version checks — the two OCC comparisons and the invoice-issue schedule pin from §2.7 (`ERR_STALE_LOT_VERSION`, `ERR_STALE_INVOICE_VERSION`, `ERR_STALE_SCHEDULE_VERSION`).
8. Segregation of duties (§2.8).
9. Dryer safety — the 26.0-percent intake-moisture limit (`ERR_MOISTURE_EXCEEDS_DRYER_LIMIT`).
10. Structural constraints — run-window overlap including cooldown (`ERR_RUN_OVERLAP`), tariff-window overlap (`ERR_SCHEDULE_WINDOW_OVERLAP`), ticket window and bushel-count validity (`ERR_TICKET_WINDOW_INVALID`), blend-target position (`ERR_TARGET_MOISTURE_INVALID`), blend commodity and ownership alignment (`ERR_BLEND_COMMODITY_MISMATCH`, `ERR_BLEND_OWNERSHIP_MISMATCH`), blend quantity feasibility (`ERR_INSUFFICIENT_BLEND_GRAIN`), meter-reading sanity (`ERR_METER_READING_INVALID`), claim-to-run consistency (`ERR_CLAIM_RUN_MISMATCH`), and payment reversibility (`ERR_PAYMENT_NOT_REVERSIBLE`).
11. Capacity and time-window rules — daily class and total capacity (`ERR_CAPACITY_EXCEEDED`), preemption eligibility (`ERR_PREEMPTION_NOT_ALLOWED`), and claims filed after delivery (`ERR_CLAIM_AFTER_DELIVERY`).
12. Fiscal gates — suspension (`ERR_CUSTOMER_SUSPENDED`), credit headroom (`ERR_CREDIT_LIMIT_EXCEEDED`), payment size (`ERR_PAYMENT_EXCEEDS_DUE`), and billable content (`ERR_NO_BILLABLE_ACTIVITY`).

Two consequences of the pinned order are worth stating plainly. A stale-version rejection is only reached once the request is well-formed, the references exist, and the target's state permits the write. And at queue-ticket confirmation, a capacity breach surfaces as `ERR_CAPACITY_EXCEEDED` before credit standing is ever examined.

## 3. Business Logic & Workflows

### 3.1. Grower Accounts, Prepaid Credit, and Receivables Standing

An `ElevatorManager` opens a grower account with a `name` and a `credit_limit_cents`, the maximum receivables exposure the elevator will carry for that grower. Two optional fields complete the account: an opening `prepaid_balance_cents` (the grower's credit on account, defaulting to 0) and a `priority_class` — `STANDARD` by default, or `PRIORITY_CONTRACT` for growers whose contracts buy queue protection (§3.4). `name` must be a non-empty string, and `credit_limit_cents` and a supplied `prepaid_balance_cents` must be non-negative integers — zero is permitted; the same constraints apply on update. Every account begins with `account_status` `ACTIVE`. A manager may later revise the credit limit, the suspension flag (`ACTIVE` or `SUSPENDED`), or the priority class; each revision bumps the account's version. A `SUSPENDED` account cannot book new dryer time and cannot have pending bookings confirmed: both attempts are rejected with `ERR_CUSTOMER_SUSPENDED` (HTTP 422).

The prepaid ledger is deliberately narrow. After the opening balance at creation, `prepaid_balance_cents` is mutated by exactly three events: a damage-claim settlement crediting the account (§3.8), a payment drawing against it (§3.9), and a reversal refunding a prior draw (§3.9). Nothing else touches it.

Credit standing is evaluated where risk is taken on. Confirming a queue ticket estimates the drying charge for the ticket's lot and requires that this estimate plus the account's outstanding dues across ISSUED invoices stay within `credit_limit_cents`; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). When no tariff window covers the booked date, the estimate is treated as zero for this check (§3.4).

A computed statement gives each account's receivables position at a glance: `customer_id`, `outstanding_due_cents` (the sum of `amount_due_cents` across the account's ISSUED invoices), the current `prepaid_balance_cents`, and `issued_invoice_count`. Growers may read their own account record and statement; managers may list all accounts, filtering the list by `account_status`.

### 3.2. Intake at the Scale: Lots, Moisture Tests, and the Provisional Baseline

An `IntakeTechnician` receives grain at the scale by creating a grain lot. The payload names the delivering account (`customer_id`), the `commodity` — one of `CORN`, `SOYBEAN`, or `WHEAT` — the two scale weights `gross_weight_lbs` (truck plus grain) and `tare_weight_lbs` (empty truck), and the contractual dry-down `target_moisture_pct`, which must be at least 10.0 and at most 20.0. Intake grading may supply `foreign_material_pct`, defaulting to 0.0; foreign material above the tariff threshold triggers a drying-charge surcharge (§3.3), and foreign material above 8.0 percent marks a pre-existing condition in liability assessment (§3.8). The system derives `wet_net_weight_lbs` as the gross weight minus the tare weight. A supplied `foreign_material_pct` must be a non-negative number. Until the workflows that set them run, the lot's moisture readings, `certified_test_id`, provisional figures, and final-weight and variance figures read null. A new lot's `status` is `RECEIVED`, its `ownership` is `GROWER_HELD`, and its `current_owner_id` equals the `customer_id`. The lot list filters by `customer_id`, `current_owner_id`, `certified_test_id`, `status`, and `commodity`.

Moisture is established through tests. An `IntakeTechnician` creates a moisture test with `lot_id`, the measured `sample_moisture_pct` (strictly greater than 0 and strictly less than 60), and the OCC field `expected_grain_lot_version` described in §2.7; the `method` defaults to `PROBE` and may instead be `OVEN_REFERENCE`, and `supersedes_test_id` may name a declared retest target when a dispute is being resolved. A new test is `PRELIMINARY`, stamped with the creating technician's id in `tested_by_user_id`, and — per §2.7 — its creation advances the lot's version by one. The test list filters by `lot_id`, `supersedes_test_id`, and `status`.

Certification is what makes a test govern the lot. An `IntakeTechnician` certifies a `PRELIMINARY` test while its lot is `RECEIVED` or `TESTED`; against any other lot state the attempt is rejected with `ERR_INVALID_STATE`. The first certification moves the lot `RECEIVED` → `TESTED`; certifying a newer `PRELIMINARY` test for a lot already baseline-certified is a recertification, `TESTED` → `TESTED`. In both cases the same cascade runs: any prior `CERTIFIED` or `DISPUTED` test of the same lot becomes `SUPERSEDED`; the lot's `intake_moisture_pct` and `current_moisture_pct` take the new test's `sample_moisture_pct`; the lot's `certified_test_id` points at the newly certified test; the test records `certified_by_user_id` and a logical-clock `certified_at`; the lot's provisional baseline is recomputed as below; and the lot's version increments. When the lot's current certified test stands `DISPUTED`, the certifying technician must differ from the one who certified that disputed test — `ERR_RETEST_SO_DUTY_VIOLATION` (§2.8). A `SUPERSEDED` test is terminal.

The provisional baseline is the elevator's pre-drying estimate of what the lot will yield. The water-shrink percentage is the lot's intake moisture minus its target moisture, divided by one hundred minus the target moisture, the quotient multiplied by one hundred. The `provisional_shrink_pct` is that water shrink plus a handling allowance of half a percentage point, kept at full precision. The `provisional_dry_weight_lbs` is the wet net weight multiplied by one minus the provisional shrink percentage divided by one hundred, rounded half up to whole pounds. These figures are recomputed at every certification, and they stand until a dryer run completes and certified scale weights replace them (§3.5) — the gap between the two is where most grower arguments live.

A grower who distrusts the governing number may dispute it: the lot's current owner — `X-User-ID` equal to the lot's `current_owner_id` — moves a `CERTIFIED` test to `DISPUTED`. Disputing changes nothing on the lot itself; resolution comes from a fresh `PRELIMINARY` test (typically created with `supersedes_test_id` naming the disputed one) whose certification supersedes the disputed test and rebaselines the lot, subject to the retest segregation rule above.

### 3.3. Tariff Windows and the Drying Charge

An `ElevatorManager` publishes drying-charge schedules, one commodity per window. Each schedule names its `commodity` and an inclusive date window from `effective_from` through `effective_to`; windows for the same commodity must not overlap under closed-interval semantics — two windows sharing even a single boundary day overlap — and a colliding window is rejected with `ERR_SCHEDULE_WINDOW_OVERLAP` (HTTP 409). An `effective_from` after `effective_to` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The three drying rates, the two energy rates, and `min_charge_cents` must be non-negative integers, and `fm_threshold_pct`, `fm_surcharge_pct`, `energy_t1_limit_therms`, `est_therms_per_hour`, and `est_point_factor` must be non-negative numbers — zero is permitted throughout; violations yield `ERR_INVALID_REQUEST`. The schedule's drying side carries `t1_max_moisture_pct` and `t2_max_moisture_pct`, the inclusive upper edges of the first two moisture brackets, and three rates: `rate_t1_cents_per_pt_bu`, `rate_t2_cents_per_pt_bu`, and `rate_t3_cents_per_pt_bu`, each in cents per point of moisture removed per bushel. Its foreign-material policy is `fm_threshold_pct` with the multiplier `fm_surcharge_pct` (a value of 0.10 meaning a ten-percent uplift), and its floor is `min_charge_cents`. The energy side — `energy_t1_limit_therms`, `energy_t1_rate_cents_per_therm`, `energy_t2_rate_cents_per_therm`, `est_therms_per_hour`, and `est_point_factor` — is consumed by the run-completion pass-through in §3.5. The schedule list filters by `commodity`.

A manager may revise an existing window's three drying rates, its `min_charge_cents`, and its two energy rates. Every such revision bumps the schedule's version, and per §2.7 breaks the issue pins of any drafts composed against the earlier version.

The drying charge itself is computed in three places — the charge-preview read, the ticket-confirm credit estimate, and invoice composition (§3.9) — and the arithmetic is identical in all of them. Bushels are the lot's `wet_net_weight_lbs` divided by the commodity's pounds per bushel — 56 for CORN, 60 for SOYBEAN, 60 for WHEAT — carried at full precision with no rounding. Points removed are the lot's `intake_moisture_pct` minus its `target_moisture_pct`, floored at zero. The bracket rate is `rate_t1_cents_per_pt_bu` when the intake is at most `t1_max_moisture_pct`, `rate_t2_cents_per_pt_bu` when the intake exceeds the first edge but is at most `t2_max_moisture_pct`, and `rate_t3_cents_per_pt_bu` when the intake exceeds the second edge — bracket edges are inclusive downward. The bracket subtotal is bushels times points removed times the bracket rate. When the lot's `foreign_material_pct` is strictly greater than the schedule's `fm_threshold_pct`, the subtotal is multiplied by one plus `fm_surcharge_pct`. The charge is the resulting amount rounded half up to whole cents, then raised to `min_charge_cents` if it falls below — the floor applies last.

A lot's charge-preview read returns the computed figures once the lot carries a certified moisture baseline — against a lot without one the read is rejected with `ERR_INVALID_STATE` (HTTP 409): `lot_id`, the governing window's `schedule_id`, plus `bushels`, `points_removed`, `rate_cents_per_pt_bu`, `fm_surcharge_applied`, and `drying_charge_cents`. When no window of the lot's commodity covers the relevant service date — which is the logical clock's current date — the preview is rejected with `ERR_SCHEDULE_NOT_FOUND` (HTTP 404); the same missing window at ticket confirmation leaves the credit estimate at zero rather than failing the confirm.

### 3.4. Booking Throughput: Queue Tickets, Class Caps, and Harvest-Peak Preemption

Before anything can be booked, an `ElevatorManager` registers the hardware. Each dryer unit carries a `unit_code` label (for example, DRYER-1; uniqueness is not enforced), a `daily_capacity_bushels` ceiling on total bookable bushels per calendar day across all classes, a `standard_class_cap_bushels` ceiling on the daily commitment to `STANDARD`-class tickets, an informational nameplate `throughput_bu_per_hour`, and the `cooldown_minutes` of mandatory idle time between runs, which §3.5's scheduling conflict check treats as occupied time. `daily_capacity_bushels` must be a positive integer; `standard_class_cap_bushels`, `throughput_bu_per_hour`, and `cooldown_minutes` must be non-negative integers (`ERR_INVALID_REQUEST`).

Booking itself is open to a `Grower` acting on their own account's lots and to an `ElevatorManager`. The booking payload names the `lot_id`, the `unit_id`, the `window_date` the bushels are committed against, and the `requested_bushels` to reserve. The date must not be in the past and the bushel count must be positive; violations are rejected with `ERR_TICKET_WINDOW_INVALID` (HTTP 422). The lot must be `RECEIVED` or `TESTED` — creation does not require the lot to be `TESTED`; confirmation does. Booking dryer time for a lot whose dry-down target already meets or exceeds its certified intake moisture — nothing to dry — is rejected with `ERR_TARGET_MOISTURE_INVALID` (HTTP 422), and a suspended account books nothing at all (`ERR_CUSTOMER_SUSPENDED`). A new ticket is `PENDING`; its `priority_class` is copied from the customer's at creation and never changes, and its `preemption_count` starts at zero. The ticket list filters by `lot_id`, `unit_id`, `window_date`, and `status`.

Confirmation, performed by an `ElevatorManager`, is where a booking becomes committed capacity, and its gates are evaluated in the §2.9 order. The ticket must be `PENDING` and its lot `TESTED` — anything else is `ERR_INVALID_STATE` (a lot on `DAMAGE_HOLD` fails with `ERR_LOT_ON_DAMAGE_HOLD`, per §2.9). The `window_date` must still be the current date or later, or `ERR_TICKET_WINDOW_INVALID`. The lot's `intake_moisture_pct` must be at most 26.0 percent — the dryer safety limit — or `ERR_MOISTURE_EXCEEDS_DRYER_LIMIT` (HTTP 422). Capacity must be available, below. The account must be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED`) and within credit headroom (`ERR_CREDIT_LIMIT_EXCEEDED`): the §3.3 drying-charge estimate for the lot — taken as zero when no tariff window covers the ticket's `window_date` — plus the account's outstanding dues across ISSUED invoices must not exceed `credit_limit_cents`. A confirmed ticket moves `PENDING` → `CONFIRMED`, moves its lot `TESTED` → `QUEUED`, and adds its `requested_bushels` to the committed capacity of that unit on that date.

Capacity accounting runs per unit per calendar day. Committed bushels are the sum of `requested_bushels` over the unit-date's `CONFIRMED` tickets; a ticket `CONSUMED` by an executing run still occupies its day, while `PENDING`, `PREEMPTED`, `CANCELLED`, and `EXPIRED` tickets hold nothing. A `STANDARD` ticket may confirm only if the committed `STANDARD` total plus its request stays at or below `standard_class_cap_bushels` — equality at the cap is allowed — and the all-class committed total plus its request stays at or below `daily_capacity_bushels`. `PRIORITY_CONTRACT` tickets bypass the standard cap but still count toward the daily total. A breach of either ceiling is `ERR_CAPACITY_EXCEEDED` (HTTP 422). The per-day position is readable as a capacity calendar: given a `date`, it returns the `unit_id`, the `date`, the unit's `daily_capacity_bushels`, `standard_committed_bushels`, `total_committed_bushels`, and the derived `standard_remaining_bushels` and `total_remaining_bushels`. A missing or malformed `date` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Harvest-peak preemption lets an `ElevatorManager` clear space for contract grain. Only a `CONFIRMED` ticket of `STANDARD` class may be preempted; any other non-terminal target is rejected with `ERR_PREEMPTION_NOT_ALLOWED` (HTTP 422), while a terminal ticket follows §2.5 (`ERR_ALREADY_TERMINAL`). Preemption moves the ticket `CONFIRMED` → `PREEMPTED`, releases its committed capacity, returns its lot `QUEUED` → `TESTED`, and increments the ticket's `preemption_count`. A preempted ticket is not dead: while its `preemption_count` is below two, a `Grower` (own tickets) or `ElevatorManager` may requeue it, `PREEMPTED` → `PENDING`, after which it must be confirmed anew with every gate re-evaluated. A twice-preempted ticket can no longer requeue — the attempt is `ERR_INVALID_STATE`.

Cancellation is symmetric for a `Grower` (own tickets) and an `ElevatorManager`, but its consequences depend on the ticket's state. Cancelling a `PENDING` ticket moves it to `CANCELLED` with no further effect — nothing was committed. Cancelling a `CONFIRMED` ticket releases its committed capacity and returns the lot `QUEUED` → `TESTED`. `CANCELLED` and `EXPIRED` are terminal. Two system transitions complete the machine: a ticket becomes `CONSUMED` when a dryer run referencing it starts, and returns from `CONSUMED` to `CONFIRMED` as compensation if that run aborts (§3.5).

### 3.5. The Dryer Run: Scheduling, Firing, Completion, and the Energy Pass-Through

A `DryerOperator` schedules a run by naming the physical `unit_id`, the `lot_id` to be dried, the `queue_ticket_id` whose booked capacity backs the run, and the planned window `scheduled_start` to `scheduled_end`; the planned end must fall after the planned start, or `ERR_INVALID_REQUEST` (HTTP 400). Scheduled windows are half-open — a run occupying its window does not conflict with another beginning exactly when it ends — and the unit's `cooldown_minutes` idle gap is treated as occupied time around each run, so a new window that collides with another non-cancelled run on the same unit, cooldown buffer included, is rejected with `ERR_RUN_OVERLAP` (HTTP 409). Scheduling also enforces the dryer safety limit against the lot's certified intake: above 26.0 percent, `ERR_MOISTURE_EXCEEDS_DRYER_LIMIT`. The named ticket is never cross-checked against the run's lot or unit — scheduling and starting validate the ticket's own state and window only. A new run is `SCHEDULED`; the run list filters by `lot_id`, `unit_id`, `queue_ticket_id`, and `status`. A `SCHEDULED` run may simply be cancelled — `SCHEDULED` → `CANCELLED`, terminal.

Starting a run is the operator's declaration that grain is moving. The run must be `SCHEDULED`, its lot must stand `QUEUED`, and its ticket must be `CONFIRMED` with a `window_date` equal to the calendar date of the run's `scheduled_start`; state mismatches are `ERR_INVALID_STATE`. No other run may be `IN_PROGRESS` on the same unit. The operator supplies the opening `meter_start_therms` gas reading; the run records `actual_start` from the logical clock and `operator_user_id` from `X-User-ID` (the segregation-of-duties rules in §3.8 rely on this attribution). Starting cascades outward: the backing ticket moves `CONFIRMED` → `CONSUMED`, and the lot moves `QUEUED` → `DRYING`.

Completion is the richest event in the system. The operator supplies the certified `scale_out_weight_lbs` of the dried grain and the measured `discharge_moisture_pct` — a positive integer and a non-negative number respectively, or `ERR_INVALID_REQUEST` (HTTP 400) — and supplies energy data in one of two variants. By default — `energy_estimated` false — the operator supplies the closing `meter_end_therms`, which must be strictly greater than `meter_start_therms` or the completion is rejected with `ERR_METER_READING_INVALID` (HTTP 422); the run's `fuel_therms` is then the meter delta. When `energy_estimated` is true — the meter-failure provision, under which `meter_end_therms` is optional and, if supplied, recorded but unused — fuel is derived instead: the run's duration in hours (`actual_end` minus `actual_start`, in seconds, divided by 3600), multiplied by the schedule's `est_therms_per_hour` burn rate, multiplied by one plus `est_point_factor` times the points removed, where points removed are the lot's `intake_moisture_pct` minus the run's `discharge_moisture_pct`. The estimated variant performs no intermediate rounding, and the two variants legitimately produce different charges for the same run parameters. Either way, the pass-through prices marginally against the schedule whose window covers the completion date — the logical clock's current date at completion: therms up to `energy_t1_limit_therms` bill at `energy_t1_rate_cents_per_therm`, and any therms beyond the breakpoint bill at `energy_t2_rate_cents_per_therm`; the sum, rounded half up to whole cents, becomes the run's `energy_charge_cents`. When no window covers the completion date, the pass-through computes nothing: `energy_charge_cents` is 0, and `fuel_therms` is the meter delta for the metered variant, 0.0 for the estimated variant. The run stamps `actual_end` from the logical clock and becomes `COMPLETED`.

Completion also reconciles the lot's weights against the provisional baseline. The lot's `final_dry_weight_lbs` takes the run's `scale_out_weight_lbs`; its `final_shrink_pct` is the wet net weight minus the final dry weight, divided by the wet net weight, the quotient multiplied by one hundred and rounded half up to two decimal places; and its `shrink_variance_lbs` is `provisional_dry_weight_lbs` minus `final_dry_weight_lbs` — a positive variance means the formula over-estimated the dry weight. The lot's `current_moisture_pct` becomes the run's discharge reading.

Where the lot goes next depends on storage. With no `RESERVED` storage agreement for the lot, completion moves it `DRYING` → `DRIED` and increments its version. With exactly one `RESERVED` agreement for the lot, a three-link cascade fires: the run's completion first applies the same weight reconciliation to the lot; the lot reaching dried-weight state then activates the agreement, moving it `RESERVED` → `ACTIVE` with `baseline_bushels` fixed from the just-completed final weight and `start_date` set to the completion date; and that activation moves the lot to `STORED`, its version advancing.

An `IN_PROGRESS` run that cannot finish may be aborted — `IN_PROGRESS` → `ABORTED`, terminal. Abortion is a compensation pair: the consumed ticket returns `CONSUMED` → `CONFIRMED` so its capacity is committed again, and the lot returns `DRYING` → `QUEUED`, ready to be rescheduled.

### 3.6. Storage, Title, and Load-Out

Dried grain does not have to leave. An `ElevatorManager` creates a storage agreement for a lot, optionally setting `daily_rate_cents_per_bu` (default 0.15 cents per bushel per day) and `min_days` (a minimum billable-days floor, default 7) — a supplied `daily_rate_cents_per_bu` must be a non-negative number and `min_days` a non-negative integer (`ERR_INVALID_REQUEST`); the agreement's `owner_id` is copied from the lot's `current_owner_id` at creation. A lot may never carry two live agreements — creating one while another stands `RESERVED` or `ACTIVE` for the same lot is rejected with `ERR_DUPLICATE_ACTIVE_AGREEMENT` (HTTP 409). Creation is otherwise gated by the lot's state: a terminal lot (`LOADED_OUT` or `BLENDED_OUT`) yields `ERR_ALREADY_TERMINAL`, and a lot on `DAMAGE_HOLD` or already `STORED` yields `ERR_INVALID_STATE`; lots in every other state accept an agreement.

The agreement's birth state depends on the lot. When the lot is already `DRIED`, the agreement is born `ACTIVE`: `baseline_bushels` is fixed as the lot's `final_dry_weight_lbs` divided by the commodity's pounds per bushel (56 for CORN, 60 for SOYBEAN, 60 for WHEAT), rounded half up to two decimal places; `start_date` is the current date; accrual begins at zero — and the lot moves `DRIED` → `STORED`, its version incrementing. Otherwise the agreement waits in `RESERVED` until the lot's dryer run completes, when the §3.5 cascade activates it: the baseline is fixed from the completing lot's `final_dry_weight_lbs` in the same way, and `start_date` is the completion date.

Accrual is chronological and half-open. `accrued_days` counts the days from `start_date` up to but not including `closed_date` — or up to but not including the current date while the agreement is still open. `accrued_storage_cents` is `baseline_bushels` multiplied by `daily_rate_cents_per_bu`, multiplied by the larger of `min_days` and `accrued_days`, rounded half up to whole cents; the figure finalizes when the agreement closes. While an agreement is `ACTIVE`, both accrual figures are recomputed live against the logical clock on every read; a `DEFAULTED` agreement instead keeps its last stored figures — the zeros stamped at activation — because default never finalizes accrual. The agreement list filters by `lot_id`, `owner_id`, and `status`.

Closing is a manager's action on an `ACTIVE` agreement — against any other state, `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409). Closing sets `closed_date` to the current date, finalizes `accrued_days` and `accrued_storage_cents` with the minimum-days floor, moves the agreement to `CLOSED` (terminal), and releases the lot `STORED` → `DRIED`, its version incrementing. Storage is billed once: on the first invoice whose period covers the agreement's `closed_date`; agreements still `ACTIVE` are never billed (§3.9).

Default is the elevator's remedy when a grower abandons stored grain. Declaring default — again only against an `ACTIVE` agreement, else `ERR_AGREEMENT_NOT_ACTIVE` — moves the agreement `ACTIVE` → `DEFAULTED` and transfers title: the lot's `ownership` becomes `ELEVATOR_HELD`, its `current_owner_id` is cleared to null, and its version increments, while the lot itself remains `STORED`.

Grain leaves the elevator through load-out, performed by an `IntakeTechnician`. A lot may load out only from `DRIED` with no `RESERVED` or `ACTIVE` agreement attached; success moves it `DRIED` → `LOADED_OUT`, terminal, its version incrementing. A lot on `DAMAGE_HOLD` is refused with `ERR_LOT_ON_DAMAGE_HOLD`, and other ineligible states fail the state gate.

### 3.7. Blending to a Contract Moisture

Two dried lots of the same commodity can be married into one lot at a contract moisture. An `ElevatorManager` drafts a blend order naming the wetter source in `high_moisture_lot_id`, the drier source in `low_moisture_lot_id`, and a `target_moisture_pct` that must lie strictly between the two sources' `current_moisture_pct` readings — a target outside that open interval is `ERR_TARGET_MOISTURE_INVALID` (HTTP 422). Both sources must stand `DRIED`, share one commodity (`ERR_BLEND_COMMODITY_MISMATCH`, HTTP 422), and share one current owner (`ERR_BLEND_OWNERSHIP_MISMATCH`, HTTP 422).

At creation the order computes how much of the drier lot the blend requires, by the Pearson square. The raw low-side quantity is the high lot's `final_dry_weight_lbs` multiplied by the gap between the high source's moisture and the target, divided by the gap between the target and the low source's moisture. The order's `required_low_lot_lbs` is that quotient rounded up to whole pounds — rounding up, never nearest, so the finished blend cannot land wetter than the contract target. The order begins `DRAFT`, stamped with `created_by_user_id`. The order list filters by `high_moisture_lot_id`, `low_moisture_lot_id`, `result_lot_id`, and `status`.

Approval enforces the §2.8 segregation rule: a manager whose id differs from `created_by_user_id` moves the order `DRAFT` → `APPROVED`, recorded in `approved_by_user_id`; the creator approving their own order is `ERR_BLEND_APPROVER_CONFLICT` (HTTP 403).

Execution re-verifies everything against the live lots. The order must be `APPROVED`; both sources must still stand `DRIED` (otherwise `ERR_INVALID_STATE` — a source that has been loaded out, re-claimed, or stored into an active agreement cannot blend); and `required_low_lot_lbs` must not exceed the low source's available `final_dry_weight_lbs`, or `ERR_INSUFFICIENT_BLEND_GRAIN` (HTTP 422). A successful execution consumes both sources — each moves `DRIED` → `BLENDED_OUT`, terminal, version incrementing — and mints a result grain lot: the sources' commodity, customer, and owner; `status` `DRIED`; and weights and moisture from the blend arithmetic. The result lot's `gross_weight_lbs` equals the result weight with `tare_weight_lbs` 0, its `foreign_material_pct` is 0.0, its `target_moisture_pct` is the order's target, its `ownership` is `GROWER_HELD`, and its certification, provisional, and final-shrink fields are null. The order's `result_weight_lbs` is the high source's `final_dry_weight_lbs` plus `required_low_lot_lbs`, and the result lot takes that figure as both its `wet_net_weight_lbs` and its `final_dry_weight_lbs`. The order's `result_moisture_pct` is the weight-mean moisture — the high source's final weight times its moisture plus the required low pounds times the low source's moisture, all divided by the result weight, rounded half up to two decimal places — and the result lot adopts it as both `intake_moisture_pct` and `current_moisture_pct`. The order records the new lot in `result_lot_id` and becomes `EXECUTED`, terminal.

A `DRAFT` or `APPROVED` order may be cancelled to `CANCELLED`, terminal, with no effect on the source lots.

### 3.8. Damage Claims: Holds, Assessment, and Settlement

When drying goes wrong, the grower's remedy is a damage claim — and the elevator's protection is that the lot freezes while the claim is worked. The owning grower files with the `lot_id`, the `dryer_run_id` alleged to have caused the damage, a `damage_type` of `HEAT_DAMAGE`, `STRESS_CRACKING`, `MOLD_CONTAMINATION`, or `EXCESS_SHRINK`, and a positive `claimed_amount_cents`. The named run must actually reference the claimed lot, or `ERR_CLAIM_RUN_MISMATCH` (HTTP 422). Filing is gated by the lot's state with a deliberate split in the error mapping: a lot already `LOADED_OUT` or `BLENDED_OUT` is past the point of claims and is rejected with `ERR_CLAIM_AFTER_DELIVERY` (HTTP 422), while a lot in any other state — `DAMAGE_HOLD`, `RECEIVED`, `TESTED`, `QUEUED`, `DRYING`, or `STORED` — fails the ordinary state gate with `ERR_INVALID_STATE` (HTTP 409). A successful filing records the filer in `filed_by_user_id` — equal to the lot's `current_owner_id` at filing — and moves the lot `DRIED` → `DAMAGE_HOLD`, its version incrementing. While the hold stands, the lot cannot load out, book or confirm dryer time, or participate in a blend; those operations are rejected with `ERR_LOT_ON_DAMAGE_HOLD`. The claim list filters by `lot_id`, `dryer_run_id`, and `status`.

Review and assessment are segregated from both the grower and the dryer. A `ClaimsAdjuster` opens review on a `FILED` claim — or on an `APPEALED` one, per the appeal loop below — moving it to `UNDER_REVIEW` and stamping `reviewed_by_user_id`; the reviewer must differ from the filer, or `ERR_CLAIM_SO_DUTY_VIOLATION` (HTTP 403). Assessment, again by a `ClaimsAdjuster`, requires the claim `UNDER_REVIEW` and the referenced run `COMPLETED` (else `ERR_INVALID_STATE`), and the assessor must differ from both the filer and the run's `operator_user_id` — the operator who ran the dryer never prices their own alleged damage (`ERR_CLAIM_SO_DUTY_VIOLATION`).

Assessment prices the claim and stores three computed fields on it. First, `lot_value_cents`: the lot's final bushels — `final_dry_weight_lbs` divided by the commodity's pounds per bushel, rounded half up to two decimal places — multiplied by the commodity's benchmark price (450 cents per bushel for CORN, 1050 for SOYBEAN, 620 for WHEAT), the product rounded half up to whole cents. Second, `fault_multiplier`, a ladder evaluated in this pinned order: 0.25 when the loss is attributable to a pre-existing condition — the lot's intake moisture above 26.0 percent or its foreign material above 8.0 percent; otherwise 1.5 when the run finished out of specification — the absolute gap between the run's `discharge_moisture_pct` and the lot's `target_moisture_pct` exceeding half a percentage point; otherwise 1.0 for an in-spec run. Third, `assessed_liability_cents`: take `claimed_amount_cents` less a deductible of 2500 cents, floored at zero, multiply by the fault multiplier, and round half up to whole cents; separately compute the liability cap as forty percent of `lot_value_cents`, rounded half up to whole cents; the assessment is the lesser of the two rounded figures. The assessor is stamped in `assessed_by_user_id` and the claim moves `UNDER_REVIEW` → `ASSESSED`.

Three exits release the hold. Denial by an adjuster other than the filer moves `UNDER_REVIEW` → `DENIED` and returns the lot `DAMAGE_HOLD` → `DRIED`; the filer may then appeal, `DENIED` → `APPEALED`, an action open only to the operator in `filed_by_user_id`, and an appealed claim returns to `UNDER_REVIEW` through a fresh review — again by an adjuster other than the filer. Withdrawal by the filer is possible from `FILED` or from `UNDER_REVIEW`, moves the claim to `WITHDRAWN` (terminal), and returns the lot `DAMAGE_HOLD` → `DRIED`. Appeal and withdrawal alike are rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403) when the caller is not the operator in `filed_by_user_id`.

Payment, an `ElevatorManager` action on an `ASSESSED` claim, is a three-link settlement cascade. First, the customer's `prepaid_balance_cents` grows by `assessed_liability_cents`. Second, that prepaid increase auto-applies as a waterfall across the customer's ISSUED invoices, oldest `issued_at` first with ties broken by `created_at`: each invoice in turn absorbs the lesser of the remaining prepaid balance and its own `amount_due_cents`, and the walk stops when the prepaid credit is exhausted or no ISSUED invoice remains. Third, every invoice whose due reaches zero in the waterfall moves `ISSUED` → `PAID`. If the lot is still on hold, payment releases it `DAMAGE_HOLD` → `DRIED`; on the appeal path the lot was already released at denial, so nothing further moves. `PAID` is terminal for the claim. An `assessed_liability_cents` of zero credits nothing and runs no waterfall; the claim still becomes `PAID` and the hold still releases.

### 3.9. Billing: Invoice Composition, Issue, Payment, and Reversal

Billing begins when an `ElevatorManager` composes a draft invoice for a `customer_id` over an inclusive period `period_start` through `period_end` (a `period_start` after `period_end` is rejected with `ERR_INVALID_REQUEST`, HTTP 400). Composition walks the account's activity and builds `lines`, each line an object with a `line_type` of `DRYING`, `ENERGY`, or `STORAGE`, a `ref_id` pointing at the source record, a `description`, and an `amount_cents`. `DRYING` lines come one per distinct lot of the customer having at least one `COMPLETED` run whose completion date falls inside the period, priced by the §3.3 drying charge under the schedule whose window covers the lot's earliest in-period completion date — a lot whose completion date no window covers contributes no DRYING line. `ENERGY` lines come one per `COMPLETED` run of the customer's lots completed inside the period, at the run's `energy_charge_cents`. `STORAGE` lines come one per storage agreement of the customer's lots whose `closed_date` falls inside the period, at the agreement's `accrued_storage_cents` — so a closed agreement bills exactly once, on the first invoice whose period covers its close, and `ACTIVE` agreements never bill; a `STORAGE` line emitted only on a `VOID` invoice does not count, so voiding that invoice makes the agreement billable again. `ABORTED` and `CANCELLED` runs are excluded everywhere, and no lot of another customer ever contributes. Rounding order is pinned: every line rounds to whole cents within its own calculation, and the invoice's `total_cents` is the plain integer sum of the rounded line amounts — never a single rounding of unrounded amounts. Lines are emitted grouped by type — all `DRYING` lines first in lot creation order, then `ENERGY` lines lot by lot with runs ordered by completion time, then `STORAGE` lines lot by lot with agreements ordered by close date — and their descriptions read `Drying charge for lot {lot_id}`, `Energy pass-through for run {run_id}`, and `Storage accrual for agreement {agreement_id}`. A composition that produces zero lines is rejected outright with `ERR_NO_BILLABLE_ACTIVITY` (HTTP 422). The new invoice stands `DRAFT`; the invoice list filters by `customer_id`, `schedule_id`, and `status`.

Issuing pins the tariff. The governing schedule is the one that priced the draft's first `DRYING` line; a draft composed without any `DRYING` line has no governing schedule — its issue accepts any pin and records `schedule_id` null. The invoice carries `pinned_schedule_version`, null while `DRAFT` and set to the supplied pin at issue. The issuer supplies `pinned_schedule_version`, the version of the governing charge schedule observed when the draft was composed; per §2.7, a mismatch against the schedule's current version is rejected with `ERR_STALE_SCHEDULE_VERSION` (HTTP 409) — which is how a mid-cycle tariff revision forces drafts to be re-read before they can go out. A successful issue records the schedule in `schedule_id`, stamps `issued_at` from the logical clock, sets `amount_due_cents` equal to `total_cents`, increments the invoice's version, and moves it `DRAFT` → `ISSUED`.

Voiding has two shapes. A `DRAFT` invoice voids freely. An `ISSUED` invoice voids only while nothing has been applied against it — `amount_due_cents` still equal to `total_cents`; once an unreversed payment exists, the attempt is `ERR_INVALID_STATE`. `VOID` is terminal.

Payments settle ISSUED invoices, and only ISSUED invoices: against a `DRAFT` invoice the attempt is `ERR_INVOICE_NOT_ISSUED` (HTTP 409), and a fully paid invoice has nothing due, so any positive cash amount exceeds the remainder and is rejected with `ERR_PAYMENT_EXCEEDS_DUE`. A `Grower` pays their own invoices; an `ElevatorManager` may post against any. The request carries `amount_cents` and the OCC field `expected_invoice_version` (§2.7). The prepaid ledger draws first: the draw is the lesser of the account's `prepaid_balance_cents` and the invoice's `amount_due_cents`, and the cash `amount_cents` may not exceed the due remaining after that draw — `ERR_PAYMENT_EXCEEDS_DUE` (HTTP 422). The resulting Payment records `invoice_id`, the `direction` `APPLICATION`, the prepaid portion in `applied_from_prepaid_cents`, and the cash portion in `applied_from_cash_cents`. It also records `amount_cents`, the cash amount, and a null `reversal_of_payment_id`. The invoice's due falls by draw plus cash, the account's prepaid balance falls by the draw, the invoice's version increments, and a due of zero moves the invoice `ISSUED` → `PAID`. The payments of one invoice are listable from the invoice, and a cross-invoice payment list filters by `invoice_id` and `reversal_of_payment_id`.

`PAID` is not irreversible. An `ElevatorManager` may reverse a payment, which mints a compensating Payment whose `direction` is `REVERSAL` and whose `reversal_of_payment_id` names the original record. The reversal copies the original's `amount_cents`, `applied_from_prepaid_cents`, and `applied_from_cash_cents`. Only a not-yet-reversed `APPLICATION` may be reversed — reversing a `REVERSAL`, or an `APPLICATION` already reversed, is `ERR_PAYMENT_NOT_REVERSIBLE` (HTTP 409). Reversal restores the invoice's `amount_due_cents` by the original prepaid plus cash portions, refunds the prepaid portion to the account's `prepaid_balance_cents` (the cash portion is refunded externally, outside this ledger), and reopens the invoice `PAID` → `ISSUED` when the restored due is positive.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: accounts, grain lots, moisture tests, charge schedules, dryer units, queue tickets, dryer runs, blend orders, damage claims, storage agreements, invoices, and — because each mints a new Payment record — payment applications and payment reversals. Operations that act on an existing resource without creating one return `200 OK`: updates, state transitions, and all action endpoints. The full request and response semantics of every operation are defined by the workflows in §3; this table is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/grain-drying/customers` | Create a grower account | ElevatorManager |
| GET | `/grain-drying/customers` | List customers | ElevatorManager |
| GET | `/grain-drying/customers/{id}` | Get one customer | ElevatorManager, Grower |
| PATCH | `/grain-drying/customers/{id}` | Update credit limit, suspension, priority class | ElevatorManager |
| GET | `/grain-drying/customers/{id}/statement` | Computed receivables position | ElevatorManager, Grower |
| POST | `/grain-drying/grain-lots` | Receive a lot at the scale | IntakeTechnician |
| GET | `/grain-drying/grain-lots` | List lots with filters | ElevatorManager, Grower, IntakeTechnician, DryerOperator, ClaimsAdjuster |
| GET | `/grain-drying/grain-lots/{id}` | Get one lot | ElevatorManager, Grower, IntakeTechnician, DryerOperator, ClaimsAdjuster |
| POST | `/grain-drying/grain-lots/{id}/load-out` | Load a DRIED lot out of the elevator | IntakeTechnician |
| GET | `/grain-drying/grain-lots/{id}/charge-preview` | Computed drying-charge preview per governing schedule | ElevatorManager, Grower, IntakeTechnician |
| POST | `/grain-drying/moisture-tests` | Create a moisture test for a lot (OCC on lot version) | IntakeTechnician |
| GET | `/grain-drying/moisture-tests` | List moisture tests | ElevatorManager, Grower, IntakeTechnician, DryerOperator, ClaimsAdjuster |
| GET | `/grain-drying/moisture-tests/{id}` | Get one moisture test | ElevatorManager, Grower, IntakeTechnician, DryerOperator, ClaimsAdjuster |
| POST | `/grain-drying/moisture-tests/{id}/certify` | Certify a PRELIMINARY test; supersedes the lot's prior test and recomputes the lot baseline | IntakeTechnician |
| POST | `/grain-drying/moisture-tests/{id}/dispute` | Owning grower disputes a CERTIFIED test | Grower |
| POST | `/grain-drying/charge-schedules` | Create a versioned tariff window for one commodity | ElevatorManager |
| GET | `/grain-drying/charge-schedules` | List charge schedules | ElevatorManager, Grower, IntakeTechnician |
| GET | `/grain-drying/charge-schedules/{id}` | Get one charge schedule | ElevatorManager, Grower, IntakeTechnician |
| PATCH | `/grain-drying/charge-schedules/{id}` | Revise rates (bumps version; breaks invoice-issue pins) | ElevatorManager |
| POST | `/grain-drying/dryer-units` | Register a dryer unit and its capacity policy | ElevatorManager |
| GET | `/grain-drying/dryer-units/{id}` | Get one dryer unit | ElevatorManager, Grower, IntakeTechnician, DryerOperator, ClaimsAdjuster |
| GET | `/grain-drying/dryer-units/{id}/capacity-calendar` | Computed committed vs capacity for one date | ElevatorManager, Grower, DryerOperator |
| POST | `/grain-drying/queue-tickets` | Book dryer throughput for a lot on a date | Grower, ElevatorManager |
| GET | `/grain-drying/queue-tickets` | List queue tickets | ElevatorManager, Grower, DryerOperator |
| GET | `/grain-drying/queue-tickets/{id}` | Get one queue ticket | ElevatorManager, Grower, DryerOperator |
| POST | `/grain-drying/queue-tickets/{id}/confirm` | Confirm a PENDING ticket (capacity, safety, and fiscal gates) | ElevatorManager |
| POST | `/grain-drying/queue-tickets/{id}/cancel` | Cancel a PENDING or CONFIRMED ticket; CONFIRMED cancellation releases capacity and reverts the lot | Grower, ElevatorManager |
| POST | `/grain-drying/queue-tickets/{id}/preempt` | Harvest-peak preemption of a CONFIRMED STANDARD ticket | ElevatorManager |
| POST | `/grain-drying/queue-tickets/{id}/requeue` | Return a PREEMPTED ticket to PENDING (fewer than two preemptions) | Grower, ElevatorManager |
| POST | `/grain-drying/dryer-runs` | Schedule a run on a unit (overlap including cooldown rejected) | DryerOperator |
| GET | `/grain-drying/dryer-runs` | List dryer runs | ElevatorManager, Grower, DryerOperator |
| GET | `/grain-drying/dryer-runs/{id}` | Get one dryer run | ElevatorManager, Grower, DryerOperator |
| POST | `/grain-drying/dryer-runs/{id}/start` | Start a scheduled run | DryerOperator |
| POST | `/grain-drying/dryer-runs/{id}/complete` | Complete a run with certified scale-out weight and discharge moisture; metered or estimated energy | DryerOperator |
| POST | `/grain-drying/dryer-runs/{id}/abort` | Abort an in-progress run (compensates ticket and lot) | DryerOperator |
| POST | `/grain-drying/dryer-runs/{id}/cancel` | Cancel a scheduled run | DryerOperator |
| POST | `/grain-drying/blend-orders` | Create a blend order over two DRIED lots of the same commodity and owner | ElevatorManager |
| GET | `/grain-drying/blend-orders` | List blend orders | ElevatorManager, Grower |
| GET | `/grain-drying/blend-orders/{id}` | Get one blend order | ElevatorManager, Grower |
| POST | `/grain-drying/blend-orders/{id}/approve` | Approve a DRAFT blend order (approver must differ from creator) | ElevatorManager |
| POST | `/grain-drying/blend-orders/{id}/execute` | Execute an APPROVED blend: consumes sources, mints result lot | ElevatorManager |
| POST | `/grain-drying/blend-orders/{id}/cancel` | Cancel a DRAFT or APPROVED blend order | ElevatorManager |
| POST | `/grain-drying/damage-claims` | File a drying-damage claim (puts the lot on DAMAGE_HOLD) | Grower |
| GET | `/grain-drying/damage-claims` | List damage claims | ElevatorManager, Grower, ClaimsAdjuster |
| GET | `/grain-drying/damage-claims/{id}` | Get one damage claim | ElevatorManager, Grower, ClaimsAdjuster |
| POST | `/grain-drying/damage-claims/{id}/review` | Open review on a FILED or APPEALED claim | ClaimsAdjuster |
| POST | `/grain-drying/damage-claims/{id}/assess` | Assess liability (segregated from filer and run operator) | ClaimsAdjuster |
| POST | `/grain-drying/damage-claims/{id}/deny` | Deny a claim under review | ClaimsAdjuster |
| POST | `/grain-drying/damage-claims/{id}/appeal` | Grower appeals a DENIED claim | Grower |
| POST | `/grain-drying/damage-claims/{id}/withdraw` | Grower withdraws a FILED or UNDER_REVIEW claim | Grower |
| POST | `/grain-drying/damage-claims/{id}/pay` | Pay an ASSESSED claim: credit prepaid ledger, auto-apply waterfall, release lot | ElevatorManager |
| POST | `/grain-drying/storage-agreements` | Create a storage agreement; ACTIVE immediately if lot DRIED, else RESERVED until drying completes | ElevatorManager |
| GET | `/grain-drying/storage-agreements` | List storage agreements | ElevatorManager, Grower |
| GET | `/grain-drying/storage-agreements/{id}` | Get one storage agreement | ElevatorManager, Grower |
| POST | `/grain-drying/storage-agreements/{id}/close` | Close an ACTIVE agreement; finalize accrual with min-days floor; release lot to DRIED | ElevatorManager |
| POST | `/grain-drying/storage-agreements/{id}/declare-default` | Declare storage default: title transfers to the elevator | ElevatorManager |
| POST | `/grain-drying/invoices` | Compose a DRAFT invoice for a customer and period (per-line rounding, then sum) | ElevatorManager |
| GET | `/grain-drying/invoices` | List invoices | ElevatorManager, Grower |
| GET | `/grain-drying/invoices/{id}` | Get one invoice | ElevatorManager, Grower |
| POST | `/grain-drying/invoices/{id}/issue` | Issue a DRAFT invoice, pinning the tariff schedule version | ElevatorManager |
| POST | `/grain-drying/invoices/{id}/void` | Void a DRAFT or fully-unpaid ISSUED invoice | ElevatorManager |
| POST | `/grain-drying/invoices/{id}/payments` | Apply a payment (prepaid drawn first, then cash; OCC on invoice version) | Grower, ElevatorManager |
| GET | `/grain-drying/invoices/{id}/payments` | List payments and reversals of one invoice | ElevatorManager, Grower |
| GET | `/grain-drying/payments` | List payments across invoices | ElevatorManager, Grower |
| GET | `/grain-drying/payments/{id}` | Get one payment | ElevatorManager, Grower |
| POST | `/grain-drying/payments/{id}/reverse` | Reverse an APPLICATION payment (compensating record; restores amount due and prepaid draw) | ElevatorManager |
| POST | `/grain-drying/_clock/set_current_utc` | Set the logical clock (test-driving); advancing past a PENDING ticket's window date expires it | ElevatorManager |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows and principles that raise them (§2 and §3); this catalogue is the identifier-to-status summary.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_CLAIM_SO_DUTY_VIOLATION` | 403 Forbidden |
| `ERR_RETEST_SO_DUTY_VIOLATION` | 403 Forbidden |
| `ERR_BLEND_APPROVER_CONFLICT` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_SCHEDULE_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_BLEND_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_PAYMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_LOT_ON_DAMAGE_HOLD` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_AGREEMENT` | 409 Conflict |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SCHEDULE_VERSION` | 409 Conflict |
| `ERR_MOISTURE_EXCEEDS_DRYER_LIMIT` | 422 Unprocessable Entity |
| `ERR_TARGET_MOISTURE_INVALID` | 422 Unprocessable Entity |
| `ERR_TICKET_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PREEMPTION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_RUN_OVERLAP` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BLEND_COMMODITY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BLEND_OWNERSHIP_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_BLEND_GRAIN` | 422 Unprocessable Entity |
| `ERR_METER_READING_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_AFTER_DELIVERY` | 422 Unprocessable Entity |
| `ERR_CLAIM_RUN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_SUSPENDED` | 422 Unprocessable Entity |
| `ERR_PAYMENT_EXCEEDS_DUE` | 422 Unprocessable Entity |
| `ERR_NO_BILLABLE_ACTIVITY` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_REVERSIBLE` | 409 Conflict |

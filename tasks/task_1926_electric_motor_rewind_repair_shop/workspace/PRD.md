# Motor Rewind Shop API — Product Requirements Document

## 1. Introduction

An EASA-accredited electric motor rewind and repair service center runs on a disciplined paper trail: every failed motor that comes through the door is tested, diagnosed, quoted, rewound, balanced, and final-tested, and every one of those steps produces a record that the next step depends on. This document specifies the Motor Rewind Shop API, the system of record for that trail. It covers the full lifecycle of a repair — incoming test and failure diagnosis, the rewind-versus-replace economics quote presented to the customer, the accredited coil data record captured during the rewind, the balance and vibration measurements that gate release, and the invoice that follows the repaired unit back to the customer.

Around that core workflow the API manages the commercial relationships that make a modern service center sticky: rush and emergency pricing premiums, a customer spare-motor pool with slot contracts and overdue loan charges, and a warranty program on rewound windings that adjudicates claims into free re-rewinds or prorated account credits. Because quoting, testing, winding, and money movement are deliberately separated across five operator roles plus the customer, the specification pays particular attention to segregation of duties, optimistic concurrency on the two write paths where stale views cause real financial damage, and a logical server clock that drives every expiry, overdue flip, and warranty window in the system.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request with either header missing, or with a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Six roles exist, spelled exactly as follows. `ShopAdmin` is the shop owner or administrator: it alone configures the service center and drives the test clock, and it has read access to everything. `ServiceManager` runs the front office — customer and motor registration, release, delivery, close and scrap decisions, invoice voids, payment recording, pool contracts and loans, and warranty adjudication. `Technician` is the test technician responsible for intake, incoming/core-loss/final test records, and diagnosis. `WindingTechnician` is the rewind specialist who starts the rewind and records coil data. `Estimator` issues, sends, and revises quotes. `Customer` is the customer account, accepting or declining quotes, filing warranty claims, and reading its own records.

The identity carried by `X-User-ID` depends on the role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer; ownership checks on any resource that references a Customer compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `ShopAdmin`, `ServiceManager`, `Technician`, `WindingTechnician`, or `Estimator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `recorded_by` on a test record or coil data record, or as `reviewed_by` on a warranty claim — but it never compares it to any entity's `id`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Lazy Transitions

All timestamps in the system — quote issue and expiry, invoice due dates, pool loan grace windows, warranty filing windows, motor age at quote time — are read from a single server-side logical clock, never from wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `ShopAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; the clock never falls back to wall-clock time afterward.

Several state changes are lazy: they are not pushed by a scheduler but are re-evaluated the next time the affected resource is read or acted upon. A quote whose `expires_at` has been reached transitions to `EXPIRED` on any access or acceptance attempt. An `OPEN` invoice whose `due_at` has passed with a positive balance flips to `OVERDUE` on read or payment. A pool loan whose `due_at` is set and has passed flips from `OUT` to `OVERDUE` on read. A customer's `standing` is recomputed lazily whenever the customer record is read. After the clock is advanced, these lazy transitions re-evaluate on the next read of each affected resource.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that increments with every modification; it anchors optimistic concurrency control where that applies.

Two record types are deliberately thinner. A TestRecord and a CoilDataRecord are immutable once written: each carries only `id` and `created_at` from the common set — both `updated_at` and `version` are absent from these two resources. Any mutation of a work order, including automatic cascades such as the rework loop or a quote issuance side effect, refreshes the work order's `updated_at` and increments its `version`.

### 2.6. Money, Rates, and Rounding Discipline

All monetary amounts in the system are integer cents — never floating-point dollars — and all percentage or rate fields are carried as decimal fractions, so a `rush_premium_pct` of 0.35 means a thirty-five percent uplift. Wherever a calculation produces a fractional cent, the result is rounded half-up to whole integer cents. Two rounding disciplines are pinned and must not be confused: the shop-supplies surcharge rounds half-up exactly once, after its tier split, while the invoice total is assembled by computing and rounding each line item to integer cents first and only then summing — the server never sums unrounded amounts and rounds at the end. Verdict percentages such as the core-loss ratio are compared exactly, using decimal division with no pre-rounding of the ratio, and vibration readings are compared as decimals to one decimal place against the applicable limit.

### 2.7. Reading the Shop: Nested Retrieval, Flat Aliases, and Filtering

Nested resource paths are validated strictly left to right. When a path chains identifiers — shop, then work order, then a child record beneath it — the server confirms each identifier exists and belongs to the declared parent chain before looking at the next, and the first identifier that does not resolve yields `ERR_NOT_FOUND` (HTTP 404) without evaluating the rest of the path.

Alongside the nested reads, the API offers flat read-only aliases that mirror the nested list and detail endpoints for convenience and reverse foreign-key reachability. Every flat list supports `limit` and `offset`, scoping by `shop_id` where the entity is shop-rooted, and filtering by every foreign key the entity declares. Concretely: the flat customer list filters by `shop_id` and `standing`; the flat motor list by `shop_id`, `owner_customer_id`, `supersedes_motor_id`, `custody`, and `is_pool_spare`; the flat work-order list by `shop_id`, `customer_id`, `motor_id`, `active_quote_id`, `status`, and `priority`; the flat test-record list by `work_order_id` and `kind`; the flat quote list by `work_order_id` and `status`; the flat coil-data list by `work_order_id`; the flat pool-contract list by `shop_id`, `customer_id`, and `status`; the flat pool-loan list by `contract_id`, `work_order_id`, `spare_motor_id`, and `status`; the flat invoice list by `work_order_id`, `customer_id`, and `status`; and the flat warranty-claim list by `work_order_id`, `customer_id`, `status`, and `resolution_work_order_id`. Lazy transitions described in §2.4 apply on these aliases exactly as on their nested counterparts.

### 2.8. Motor Custody Tracking

Every motor carries a `custody` value that answers the question "where is this unit right now?" A motor registered for a customer starts `WITH_CUSTOMER`, moves to `IN_SHOP` when a work order intake captures it, and returns to `WITH_CUSTOMER` when that work order is delivered, declined, or scrapped. A shop-maintained pool spare starts `IN_POOL`, moves to `ON_LOAN` at loan checkout, and returns to `IN_POOL` when the loan is returned. Custody changes are always side effects of workflow events — never direct edits — and a warranty free-rewind resolution pulls the motor back to `IN_SHOP` for the resolution intake.

### 2.9. Segregation of Duties on the Shop Floor

Three hand-offs in the process are segregated, and each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The winding technician who records the coil data record may not be the same `X-User-ID` that recorded the incoming test on that work order. The technician who records the final test may not be the same `X-User-ID` that recorded the coil data. And a warranty claim may not be approved by the same `X-User-ID` that filed it when the filer was a `ServiceManager` acting on the customer's behalf — a claim filed by the customer directly carries no such restriction.

### 2.10. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control, and both guard the work order. Issuing a quote against a work order requires the request to carry `expected_work_order_version`, the client's last observed `version` of that work order; if the work order's version has advanced since — for instance because another estimator has just issued a quote, which legitimately sets `active_quote_id` and bumps the version — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412). Delivering a work order likewise requires `expected_work_order_version` matching the work order's current `version`; if the version has advanced since the delivering manager last read it — for instance because a warranty-driven resolution order or an invoice void bumped it — the delivery is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field of any kind.

### 2.11. Validation Ordering

Every request is checked against a fixed, globally ordered sequence, and a request fails with the error attached to the first check it violates. The order is: first the presence and validity of the user-context headers; then role authorization for the target endpoint; then existence and parent-chain ownership of every path identifier, validated left to right; then resolution of foreign keys carried in the request body, such as the `motor_id` and `customer_id` on work-order intake or the `work_order_id` and `spare_motor_id` on pool checkout, rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 422); then whether the target entity sits in a valid from-state for the requested transition, rejected with `ERR_INVALID_STATE` (HTTP 409). Only after those five come the domain business checks in their pinned order: quote expiry before the customer-standing check on quote acceptance; segregation of duties; uniqueness constraints; the release gates; pool checkout availability; the warranty window before the warranty covered-mode check; and field-level input shape — non-positive hours, negative amounts, unrecognized enumeration values, rejected with `ERR_INVALID_INPUT` (HTTP 400) — evaluated last of all, so a request that trips both a business gate and an input-shape rule reports the business error.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Service Center, Customers, and Motors

A `ShopAdmin` brings a service center online by creating its shop profile. The profile captures a display `shop_name` and the center's `easa_accreditation_id`, which must consist of the literal prefix `EASA-` followed by four to six digits. It also pins every commercial parameter the downstream workflows rely on: the four hourly labor rates in cents — `labor_rate_small_cents`, `labor_rate_medium_cents`, `labor_rate_large_cents`, and `labor_rate_xlarge_cents` — the `rush_premium_pct` uplift applied to expedited work, the `replace_threshold_pct` that drives the rewind-versus-replace recommendation (0.65 is a typical setting), the two shop-supplies rates `supplies_low_pct` and `supplies_high_pct`, the standard `warranty_months` window on rewound windings (twelve months is typical), and the pool economics `pool_slot_monthly_cents`, `pool_loan_daily_cents`, and `pool_loan_grace_days`. The shop's `currency` accepts only `USD` and defaults to it when omitted. A newly created shop starts at `version` 1. Every role may read the shop profile.

A `ServiceManager` builds the customer book. Registering a customer requires only a `company_name`; the new record starts with `account_credit_cents` at zero and `standing` at `GOOD`. The shop-scoped customer list can be filtered by `standing`, and reading a single customer recomputes their standing lazily before answering.

Motor registration is likewise a `ServiceManager` duty. The registrar supplies the `owner_customer_id` of the owning customer, the manufacturer `serial_number` (unique within the shop — a duplicate is rejected with `ERR_DUPLICATE_ACTIVE`), the nameplate `rated_kw` (which must be positive), the IEC `frame_mm` size (a positive integer that drives both the labor-rate tier and the vibration limit at final test), the nameplate `voltage_v`, and the `manufacture_year` from which the motor's age is derived at quote time. Two optional fields round out registration: `is_pool_spare`, defaulting to false, marks the unit as a shop-maintained pool spare, in which case `owner_customer_id` is left null — it is nullable only for pool spares — and the motor's custody starts at `IN_POOL` rather than `WITH_CUSTOMER`; and `supersedes_motor_id` links a replacement motor record back to the scrapped unit it supersedes, a self-referential chain that preserves the service history across generations. The shop-scoped motor list filters by `owner_customer_id`, `custody`, and `is_pool_spare`.

### 3.2. Intake, Incoming Test, and Diagnosis

When a failed unit arrives, a `Technician` intakes a work order with a payload naming the `customer_id` and the `motor_id`; either reference failing to resolve is rejected with `ERR_REFERENCE_NOT_FOUND`. An optional `priority` of `STANDARD`, `RUSH`, or `EMERGENCY` may be supplied, defaulting to `STANDARD`. Intake requires the motor's custody to be `WITH_CUSTOMER`; on success the motor's custody flips to `IN_SHOP`, the work order opens in `INTAKE` status, and its `invoice_total_cents` initializes to zero. The work-order list filters by `customer_id`, `status`, and `priority`.

The first diagnostic act is the incoming test, and it presupposes the motor's custody is `IN_SHOP`, which intake has already established. The technician records a test record with `kind` set to `INCOMING`, an `insulation_megohms` reading (which must be positive), and optional free-text `notes`. The server stamps the record with the caller's `X-User-ID` as `recorded_by`, computes the record's `verdict` of `PASS` or `FAIL` per its kind against the motor's nameplate, and advances the work order from `INTAKE` to `INCOMING_TEST` whether the incoming verdict computes to `PASS` or `FAIL` — the incoming measurement informs but never blocks. A core-loss test may also be recorded, with `kind` set to `CORE_LOSS` and a positive `measured_watts` reading; recording one never changes the work order's status. The core-loss verdict compares the measured watts against the motor's rated watts — its nameplate `rated_kw` multiplied by one thousand: the record passes when the measured watts are at or below five percent of the rated watts and fails above, with exact decimal division and no pre-rounding of the ratio, so a measured loss of exactly five percent is a `PASS`. Both verdicts matter downstream: a failed core-loss record pins the quote's failure-risk percentage, and any core-loss record must pass before the order can be released. Test records for a work order can be listed with a `kind` filter; `measured_watts` is required exactly when the kind is `CORE_LOSS`, and `insulation_megohms` is required for `INCOMING` and `FINAL` records.

Diagnosis converts measurements into a plan. A `Technician` records the diagnosis with a payload carrying `failure_diagnosis`, an estimated `rewind_hours` (positive), `materials_cents` (zero or more), and `replacement_cost_cents` — the quoted price of a brand-new replacement motor, which must be positive. At least one `INCOMING` test record must exist for the work order before diagnosis is accepted. These four fields stay null on the work order until the moment diagnosis lands, at which point the status moves from `INCOMING_TEST` to `DIAGNOSED`. Violations of the input shape — non-positive `rewind_hours` or `replacement_cost_cents`, negative `materials_cents` — surface as `ERR_INVALID_INPUT`. As a plausibility cross-check only, the shop's estimating rule of thumb is six hours plus 0.08 hours per nameplate kilowatt of `rated_kw`, rounded half-up to whole hours; the figure is advisory, never enforced, and the authoritative `rewind_hours` is always the value entered at diagnosis.

Not every intake becomes a repair. While a work order sits in `INTAKE`, `INCOMING_TEST`, `DIAGNOSED`, `QUOTED`, or `AWAITING_APPROVAL`, a `ServiceManager` may scrap it: the status becomes the terminal `SCRAPPED`, the motor's custody returns to `WITH_CUSTOMER`, and any quote still in `ISSUED` state is moved to `SUPERSEDED`.

### 3.3. Quoting and the Rewind-Versus-Replace Decision

With a diagnosis on file, an `Estimator` issues a quote. The issuance payload carries exactly one field, `expected_work_order_version`, enforcing the optimistic-concurrency rule of §2.10: a stale view of the work order is rejected with `ERR_STALE_VERSION` (HTTP 412). Only one live quote may exist per work order — attempting to issue while another quote for the same order is still `ISSUED` is rejected with `ERR_DUPLICATE_ACTIVE` (HTTP 409). On success the work order moves from `DIAGNOSED` to `QUOTED` — or simply stays `QUOTED` on a re-issue after a revise — its `version` increments by one, and its `active_quote_id` is set to the new quote, which is computed and moved from `DRAFT` to `ISSUED` in a single step with `issued_at` stamped at the current instant and `expires_at` set thirty days later.

The quote prices the rewind in a fixed sequence. First, the hourly labor rate is selected from the motor's `frame_mm`: `labor_rate_small_cents` when the frame is at or below 200 millimetres, `labor_rate_medium_cents` when it is above 200 and at or below 355, `labor_rate_large_cents` when it is above 355 and at or below 560, and `labor_rate_xlarge_cents` when it is above 560. The rewind labor charge `rewind_labor_cents` is the work order's `rewind_hours` multiplied by the selected rate, exact in integer cents. The materials line `rewind_materials_cents` carries over the `materials_cents` figure recorded at diagnosis, frozen at issue time.

Next, the shop-supplies surcharge `shop_supplies_cents` applies marginal tiering to the sum of labor and materials. When that sum is at or below $1,000.00 (100000 cents), the surcharge is the entire sum multiplied by the shop's `supplies_low_pct`. When the sum exceeds $1,000.00, the surcharge is the first $1,000.00 multiplied by `supplies_low_pct` plus only the excess above $1,000.00 multiplied by `supplies_high_pct` — the higher marginal rate never touches the first tier. The surcharge is rounded half-up to integer cents exactly once, after the tier split.

Rush pricing then consults the work order's `priority`. A `STANDARD` job pays nothing: `rush_premium_cents` is zero. A `RUSH` job pays the subtotal — labor plus materials plus supplies, after the supplies rounding — multiplied by the shop's `rush_premium_pct`, rounded half-up. An `EMERGENCY` job pays half again as much: the same subtotal multiplied by `rush_premium_pct` and then by 1.5, rounded half-up. The as-quoted rewind price `rewind_total_cents` is the sum of the labor, materials, supplies, and rush lines.

In parallel, the quote derives the failure-risk percentage `risk_pct` from the motor's age and test history. Age in years is the logical clock's current year minus the motor's `manufacture_year`. If any core-loss test record on this work order carries a `FAIL` verdict, `risk_pct` is pinned at 0.35 regardless of age — the core-loss failure dominates the age tiers. Otherwise, an age of fifteen years or more yields 0.25, an age of eight years or more but under fifteen yields 0.15, and anything younger yields 0.08. The risk charge `risk_cost_cents` is `rewind_total_cents` multiplied by `risk_pct`, rounded half-up to integer cents, and the risk-adjusted total `tco_total_cents` is `rewind_total_cents` plus `risk_cost_cents`.

Every quote computes both decision variants and exposes them side by side. The replacement threshold in cents is the shop's `replace_threshold_pct` multiplied by the work order's `replacement_cost_cents`, rounded half-up. The reference variant `AS_QUOTED` would recommend `REWIND` whenever the raw `rewind_total_cents` sits at or below that threshold. The stored `recommendation`, however, is always the conservative total-cost-of-ownership decision: `REWIND` when `tco_total_cents` is at or below the threshold, `REPLACE` otherwise, and the quote's `variant` field is pinned to `TCO_ADJUSTED` to record which basis produced it. Identical inputs can disagree across the two readings — a rewind that looks economic as-quoted can flip to `REPLACE` once failure risk is priced in — and it is always the risk-adjusted answer that the quote stores.

Issuance does not by itself ask the customer for a decision. The estimator sends the quote, which requires the quote to be `ISSUED` and to be the work order's current `active_quote_id`, and moves the work order from `QUOTED` to `AWAITING_APPROVAL`. From there three paths exist. The customer accepts: the quote must still be `ISSUED` and unexpired — acceptance at or after `expires_at` first auto-transitions the quote to `EXPIRED` and is then rejected with `ERR_QUOTE_EXPIRED` (HTTP 409) — and the customer's `standing` must not be `HOLD`, checked after the expiry check, with a `HOLD` rejected as `ERR_CUSTOMER_ON_HOLD` (HTTP 402). Acceptance moves the quote to `ACCEPTED` and the work order to `APPROVED`. The customer declines: the quote moves to `DECLINED`, the work order to the terminal `DECLINED`, and the motor's custody returns to `WITH_CUSTOMER`. Or the estimator revises: the quote moves to `SUPERSEDED`, the work order's `active_quote_id` is cleared, and the work order drops back from `AWAITING_APPROVAL` to `QUOTED`, ready for a fresh issuance — the revise loop can cycle as many times as negotiation requires. Quote expiry itself is lazy, per §2.4: any access or acceptance attempt at or after `expires_at` moves an `ISSUED` quote to `EXPIRED`, clears `active_quote_id`, and returns a waiting work order from `AWAITING_APPROVAL` to `QUOTED`. All four of `ACCEPTED`, `DECLINED`, `SUPERSEDED`, and `EXPIRED` are terminal states for a quote; `ISSUED` is the only state from which a quote can still move, and `DRAFT` exists only transiently inside issuance. The quotes under a work order can be listed with a `status` filter, and reading a single quote applies the lazy expiry before answering.

### 3.4. Rewind Execution: Coil Data, Balancing, and Final Test

Once the work order reaches `APPROVED`, a `WindingTechnician` begins the rewind, moving the status to `IN_REWIND`. One sanity precondition guards the hand-off: no pool loan against this work order may be sitting `OUT` while its spare motor is still `IN_POOL` — loan checkout precedes the rewind start or follows delivery, never lands mid-rewind — and a violation is rejected as an invalid state with `ERR_INVALID_STATE`.

The rewind's accredited paper trail is the coil data record. The winding technician submits a complete payload — `wire_gauge_awg`, `turns_per_coil` (positive), `coils_per_phase` (positive), the `connection` of `WYE` or `DELTA`, and the measured `winding_resistance_ohms` — and the server pins the shop's current EASA form revision (for example, `EASA-AR100-2024`) into the record's `easa_form_version` at creation and stamps `recorded_by` with the caller's `X-User-ID`. An incomplete payload is rejected with `ERR_INVALID_INPUT`. The segregation rule of §2.9 applies: the coil data recorder may not be the technician who recorded this order's incoming test, on pain of `ERR_SEGREGATION_OF_DUTIES`. A completed record moves the work order from `IN_REWIND` to `BALANCING`. The record is immutable once written, and because the rework loop can cycle, a work order accumulates zero-to-many coil data records over its life, listed oldest first.

Balancing is followed by the final test. A `Technician` records a test record with `kind` set to `FINAL`, a `vibration_mm_s` reading (zero or more), and the required `insulation_megohms`. The work order must be in `BALANCING`, and the second segregation rule of §2.9 forbids the final-test recorder from being the coil data's `recorded_by`. The verdict comes from the vibration limit for the motor's frame: 2.8 mm/s when `frame_mm` is at or below 315, 3.5 mm/s above 315 and at or below 630, and 4.5 mm/s above 630. A reading at or below the applicable limit is a `PASS`; anything strictly above is a `FAIL`. The status moves to `FINAL_TEST` regardless of the verdict.

What happens next depends on that verdict. A `FAIL` on the latest final test triggers an automatic rework loop: the system returns the work order from `FINAL_TEST` to `IN_REWIND`, the version bump on the work order serves as the rework counter, and a fresh coil data record is required before the order can pass through `BALANCING` again. A `PASS` leaves the order in `FINAL_TEST`, eligible for release.

### 3.5. Release, Invoicing, and Payment

Release is the financial point of no return, owned by a `ServiceManager`. Two gates guard it, and a violation of either is rejected with `ERR_FINAL_TEST_NOT_PASS` (HTTP 409): the latest final test record's verdict must be `PASS`, and if any core-loss test record exists for the order its verdict must also be `PASS`. A successful release computes the invoice total, creates the invoice in `OPEN` status, and moves the work order from `FINAL_TEST` to `READY_FOR_PICKUP`.

The invoice total is assembled line by line. Every job carries an incoming-test fee of $75.00 (7500 cents). A core-loss test fee of $120.00 (12000 cents) is added when a core-loss test record exists for the order. A balancing fee of $95.00 (9500 cents) is added when the order has reached `BALANCING` at least once. The four quote lines from the accepted quote — `rewind_labor_cents`, `rewind_materials_cents`, `shop_supplies_cents`, and `rush_premium_cents` — follow, and a final-test fee of $85.00 (8500 cents) closes the bill. Each line is computed and rounded to integer cents first; `invoice_total_cents` is the sum of the rounded lines, never a sum-then-round. When the work order is flagged `no_charge` — as every warranty free-rewind resolution order is — the invoice total is forced to zero regardless of the lines.

The invoice itself snapshots the order's economics at issuance: `total_cents` equals the work order's `invoice_total_cents` at that moment, `amount_paid_cents` starts at zero, `balance_due_cents` is the total minus the amount paid, `issued_at` is stamped at release, `due_at` falls thirty days after issuance on net-30 terms, and the invoice carries a denormalized `customer_id` from the work order for ledger queries. Invoices for a work order are listed beneath it, and any read or payment applies the lazy overdue flip per §2.4: an `OPEN` invoice past its `due_at` with a positive balance becomes `OVERDUE`, and the customer's standing is recomputed. An invoice reaches `PAID` automatically the moment its `balance_due_cents` reaches zero, whether from `OPEN` or `OVERDUE`, and that transition also recomputes standing. A `ServiceManager` may void an invoice only while its `amount_paid_cents` is still zero — any applied payment blocks the void with `ERR_INVOICE_HAS_PAYMENTS` (HTTP 409) — and a void moves the invoice from `OPEN` to `VOID` and recomputes the customer's standing. `PAID` and `VOID` are the invoice's terminal states; `OVERDUE` can still return to `PAID`.

Delivery closes the physical loop. A `ServiceManager` delivers a `READY_FOR_PICKUP` order; the invoice only needs to be in `OPEN` or `PAID` status — payment is not a gate on delivery. The request must carry `expected_work_order_version` per §2.10, with a stale view rejected as `ERR_STALE_VERSION` (HTTP 412). On success the work order's `version` increments by one, `delivered_at` is stamped, the motor's custody returns to `WITH_CUSTOMER`, the status becomes `DELIVERED`, and every pool loan still `OUT` against the order has its `due_at` recomputed as `delivered_at` plus the shop's `pool_loan_grace_days` — any loan already past that recomputed due date flips immediately to `OVERDUE`.

After delivery, a `ServiceManager` closes the order. Close is blocked with `ERR_CLAIMS_OPEN` (HTTP 409) while any warranty claim on the order sits in `FILED`, `UNDER_REVIEW`, or `APPROVED`, or while any pool loan for the order has yet to be returned. A successful close stamps `closed_at` and moves the order to the terminal `CLOSED`. The system also closes a delivered order automatically once the logical clock reaches the `warranty_months` anniversary of its `delivered_at` with no open warranty claim.

Payments arrive through the `ServiceManager` recording a `payment_cents` amount against the customer. The allocation is a waterfall across the customer's `OPEN` and `OVERDUE` invoices, oldest first by `issued_at` ascending with ties broken by `created_at` ascending — never by identifier. Each invoice in turn absorbs the smaller of the remaining payment and its own `balance_due_cents`, growing `amount_paid_cents` and shrinking `balance_due_cents` by the applied amount, and an invoice whose balance reaches zero flips automatically to `PAID`. Any unapplied remainder lands in the customer's `account_credit_cents`. The response enumerates the allocation as an `applied` list of `invoice_id` and `applied_cents` pairs, plus any `credit_added_cents`. Standing is recomputed after every payment.

A customer's `standing` is a derived credit signal computed from their ledger. It is `HOLD` when any of their invoices is more than thirty days past its `due_at` — exactly thirty days past due is not enough. Short of that, it is `WATCH` when any invoice is past due, or when any pool loan attached to the customer through their spare-pool contracts is `OVERDUE`; overdue loans can only ever contribute `WATCH`, never `HOLD`. Otherwise the customer is in `GOOD` standing.

### 3.6. The Customer Spare-Motor Pool

Downtime-averse customers contract for guaranteed spares. A `ServiceManager` creates a spare-pool contract with a `customer_id` and a `slot_count` of at least one; only one `ACTIVE` contract may exist per customer per shop, and a conflicting create is rejected with `ERR_DUPLICATE_ACTIVE`. The contract's `activated_on` is stamped with the server date at creation, the status opens at `ACTIVE`, and the first month's fee `first_month_fee_cents` is prorated: the full monthly fee is `slot_count` multiplied by the shop's `pool_slot_monthly_cents`, and the first month charges the fraction of the calendar month remaining — counting the activation day itself, so the remaining days are the days in the month of `activated_on` minus the day of the month of `activated_on` plus one, over the days in that month — rounded half-up to whole cents. The contract list filters by `customer_id` and `status`.

Contracts have a simple lifecycle. A `ServiceManager` may suspend an `ACTIVE` contract — blocked while any loan under it is `OUT` or `OVERDUE`, rejected as `ERR_INVALID_STATE` — resume a `SUSPENDED` contract back to `ACTIVE`, or terminate a contract from either `ACTIVE` or `SUSPENDED` into the terminal `TERMINATED`, where termination from `ACTIVE` carries the same no-open-loans precondition and termination from `SUSPENDED` is unconditional.

Checking out a spare is a `ServiceManager` action with a payload of `work_order_id` and `spare_motor_id`, each of which must resolve or the checkout fails with `ERR_REFERENCE_NOT_FOUND`. Four availability gates then apply, all rejected with `ERR_POOL_UNAVAILABLE` (HTTP 409): the contract must be `ACTIVE`; the number of loans under the contract currently `OUT` or `OVERDUE` must be fewer than the contract's `slot_count`; the spare motor must be a pool spare sitting `IN_POOL`; and the spare's `rated_kw` must fall within twenty percent of the unit under repair's rating, inclusive — no less than 80 percent and no more than 120 percent of it. A successful checkout stamps `checked_out_at`, leaves `due_at` null until the linked repair is delivered, flips the spare's custody from `IN_POOL` to `ON_LOAN`, and records the loan under its contract via `contract_id` with an initial status of `OUT` and `overdue_days` and `overdue_charge_cents` both at zero. The loan list filters by `status`, and reads apply the lazy overdue flip from §2.4, recomputing the customer's standing when a loan turns `OVERDUE`.

Return closes the loop. A `ServiceManager` records the return: `returned_at` is stamped, the spare's custody moves back to `IN_POOL`, and the loan's status becomes the terminal `RETURNED`. Overdue arithmetic is recomputed at return (and lazily on reads of an `OVERDUE` loan): `overdue_days` is the number of whole days between `due_at` and the return time — or the current time for a loan still out — floored to whole days and never below zero, and it is zero whenever `due_at` is null; `overdue_charge_cents` is `overdue_days` multiplied by the shop's `pool_loan_daily_cents`. When the charge comes out positive, a surcharge invoice is issued to the customer on top of the return.

### 3.7. Warranty Claims and Remedies

Every rewound winding carries the shop's `warranty_months` promise, measured from the work order's `delivered_at`. A claim may be filed on a delivered work order by the `Customer` or by a `ServiceManager` on the customer's behalf, with a `failure_mode` of `WINDING_SHORT`, `GROUND_FAULT`, `BEARING_FAILURE`, `OVERLOAD`, `INGRESS`, `MISAPPLICATION`, or `UNAUTHORIZED_REPAIR`. Filing stamps `filed_at` with the server timestamp, computes `months_elapsed` as the whole months between `delivered_at` and `filed_at` floored, denormalizes the `customer_id` onto the claim, and opens it in `FILED` status. The claim list filters by `status`.

Adjudication belongs to the `ServiceManager`. Starting review moves a claim from `FILED` to `UNDER_REVIEW` and stamps `reviewed_by` with the reviewer's `X-User-ID`. Denial needs no further ceremony and moves the claim to the terminal `DENIED`. Approval requires a `remedy` of `FREE_REWIND` or `PRORATED_CREDIT` in the payload and passes through three gates. First, per the segregation rule of §2.9, the approver may not be the same `X-User-ID` that filed the claim when the filer was a `ServiceManager` acting for the customer, on pain of `ERR_SEGREGATION_OF_DUTIES`. Second, the claim must still be in window: `months_elapsed` strictly less than the shop's `warranty_months` — a claim whose elapsed months equal the warranty window is already out of it and is rejected with `ERR_WARRANTY_OUT_OF_WINDOW` (HTTP 422). Third, the failure mode must be covered: `WINDING_SHORT`, `GROUND_FAULT`, and `BEARING_FAILURE` are the covered set, while `OVERLOAD`, `INGRESS`, `MISAPPLICATION`, and `UNAUTHORIZED_REPAIR` are exclusions rejected with `ERR_WARRANTY_EXCLUDED_MODE` (HTTP 422).

The two remedies diverge at approval. A `PRORATED_CREDIT` computes `credit_cents` as the work order's `invoice_total_cents` multiplied by the remaining covered months — `warranty_months` minus `months_elapsed`, never below zero — and divided by `warranty_months`, rounded half-up to integer cents. The boundary is pinned: when `months_elapsed` equals `warranty_months` the credit is zero and the claim is out of window entirely, and when `months_elapsed` is one month short of `warranty_months` the claim yields the minimum non-zero credit. The credit posts immediately into the customer's `account_credit_cents`, and the claim moves straight to `RESOLVED` on posting. A `FREE_REWIND` instead creates a brand-new work order for the same motor and customer with `priority` forced to `STANDARD` and `no_charge` set — guaranteeing its invoice totals zero at release — records it as the claim's `resolution_work_order_id`, and pulls the motor's custody back to `IN_SHOP` for the resolution intake. The claim then waits in `APPROVED` until the resolution work order reaches `DELIVERED`, at which point the system moves the claim to `RESOLVED`. Both `DENIED` and `RESOLVED` are terminal, and an open claim — anything in `FILED`, `UNDER_REVIEW`, or `APPROVED` — blocks closing the original work order with `ERR_CLAIMS_OPEN` until it resolves.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Request payloads, computed fields, and side effects are specified in the narratives of §2 and §3; the table below is the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shops` | Create a shop (service center configuration) | ShopAdmin |
| GET | `/shops/{shopId}` | Get a shop | All roles |
| POST | `/shops/{shopId}/customers` | Register a customer | ServiceManager |
| GET | `/shops/{shopId}/customers` | List customers (filter: `standing`) | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/{shopId}/customers/{customerId}` | Get a customer (recomputes standing lazily) | All roles |
| POST | `/shops/{shopId}/motors` | Register a motor (customer unit or pool spare) | ServiceManager |
| GET | `/shops/{shopId}/motors` | List motors (filters: `owner_customer_id`, `custody`, `is_pool_spare`) | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/{shopId}/motors/{motorId}` | Get a motor | All roles |
| POST | `/shops/{shopId}/work-orders` | Intake a work order (captures motor into shop) | Technician |
| GET | `/shops/{shopId}/work-orders` | List work orders (filters: `customer_id`, `status`, `priority`) | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/{shopId}/work-orders/{woId}` | Get a work order | All roles |
| POST | `/shops/{shopId}/work-orders/{woId}/tests` | Record a test (INCOMING / CORE_LOSS / FINAL); verdict computed server-side | Technician |
| GET | `/shops/{shopId}/work-orders/{woId}/tests` | List test records for a work order (filter: `kind`) | All roles |
| POST | `/shops/{shopId}/work-orders/{woId}/diagnose` | Record failure diagnosis and estimate inputs | Technician |
| POST | `/shops/{shopId}/work-orders/{woId}/scrap` | Scrap a pre-approval work order | ServiceManager |
| POST | `/shops/{shopId}/work-orders/{woId}/quotes` | Compute and issue a quote (both variants side-by-side) | Estimator |
| GET | `/shops/{shopId}/work-orders/{woId}/quotes` | List quotes for a work order (filter: `status`) | All roles |
| GET | `/shops/{shopId}/work-orders/{woId}/quotes/{quoteId}` | Get a quote (lazy expiry applied) | All roles |
| POST | `/shops/{shopId}/work-orders/{woId}/quotes/{quoteId}/send` | Send an issued quote to the customer | Estimator |
| POST | `/shops/{shopId}/work-orders/{woId}/quotes/{quoteId}/accept` | Customer accepts a quote | Customer |
| POST | `/shops/{shopId}/work-orders/{woId}/quotes/{quoteId}/decline` | Customer declines a quote | Customer |
| POST | `/shops/{shopId}/work-orders/{woId}/quotes/{quoteId}/revise` | Estimator supersedes the live quote | Estimator |
| POST | `/shops/{shopId}/work-orders/{woId}/start-rewind` | Begin the rewind | WindingTechnician |
| POST | `/shops/{shopId}/work-orders/{woId}/coil-data` | Record the EASA coil data record (immutable) | WindingTechnician |
| GET | `/shops/{shopId}/work-orders/{woId}/coil-data` | List coil data records for a work order | All roles |
| POST | `/shops/{shopId}/work-orders/{woId}/release` | Release for pickup; issues the invoice | ServiceManager |
| POST | `/shops/{shopId}/work-orders/{woId}/deliver` | Deliver the repaired unit | ServiceManager |
| POST | `/shops/{shopId}/work-orders/{woId}/close` | Close a delivered work order | ServiceManager |
| GET | `/shops/{shopId}/work-orders/{woId}/invoices` | List invoices for a work order (lazy overdue applied) | ShopAdmin, Estimator, ServiceManager, Customer |
| GET | `/shops/{shopId}/invoices/{invoiceId}` | Get an invoice (lazy overdue applied) | ShopAdmin, Estimator, ServiceManager, Customer |
| POST | `/shops/{shopId}/invoices/{invoiceId}/void` | Void an unpaid invoice | ServiceManager |
| POST | `/shops/{shopId}/customers/{customerId}/payments` | Record a customer payment; waterfall allocation across open invoices | ServiceManager |
| POST | `/shops/{shopId}/pool-contracts` | Create a spare-pool contract | ServiceManager |
| GET | `/shops/{shopId}/pool-contracts` | List pool contracts (filters: `customer_id`, `status`) | ShopAdmin, Estimator, ServiceManager |
| GET | `/shops/{shopId}/pool-contracts/{contractId}` | Get a pool contract | ShopAdmin, Estimator, ServiceManager, Customer |
| POST | `/shops/{shopId}/pool-contracts/{contractId}/suspend` | Suspend a pool contract | ServiceManager |
| POST | `/shops/{shopId}/pool-contracts/{contractId}/resume` | Resume a suspended contract | ServiceManager |
| POST | `/shops/{shopId}/pool-contracts/{contractId}/terminate` | Terminate a pool contract | ServiceManager |
| POST | `/shops/{shopId}/pool-contracts/{contractId}/loans` | Check out a pool spare against a work order | ServiceManager |
| GET | `/shops/{shopId}/pool-contracts/{contractId}/loans` | List loans under a contract (filter: `status`) | ShopAdmin, Estimator, ServiceManager, Customer |
| POST | `/shops/{shopId}/pool-contracts/{contractId}/loans/{loanId}/return` | Return a pool spare | ServiceManager |
| POST | `/shops/{shopId}/work-orders/{woId}/warranty-claims` | File a warranty claim on a delivered work order | Customer, ServiceManager |
| GET | `/shops/{shopId}/work-orders/{woId}/warranty-claims` | List warranty claims for a work order (filter: `status`) | ShopAdmin, Technician, Estimator, ServiceManager, Customer |
| GET | `/shops/{shopId}/warranty-claims/{claimId}` | Get a warranty claim | ShopAdmin, Technician, Estimator, ServiceManager, Customer |
| POST | `/shops/{shopId}/warranty-claims/{claimId}/start-review` | Move claim to UNDER_REVIEW | ServiceManager |
| POST | `/shops/{shopId}/warranty-claims/{claimId}/approve` | Approve a claim with a remedy | ServiceManager |
| POST | `/shops/{shopId}/warranty-claims/{claimId}/deny` | Deny a claim | ServiceManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ShopAdmin |
| GET | `/shops/customers/{customerId}` | Flat alias: get a customer by id | All roles |
| GET | `/shops/customers` | Flat alias: list/filter customers | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/motors/{motorId}` | Flat alias: get a motor by id | All roles |
| GET | `/shops/motors` | Flat alias: list/filter motors | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/work-orders/{woId}` | Flat alias: get a work order by id | All roles |
| GET | `/shops/work-orders` | Flat alias: list/filter work orders | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/test-records/{testRecordId}` | Flat alias: get a test record by id | All roles |
| GET | `/shops/test-records` | Flat alias: list/filter test records | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/quotes/{quoteId}` | Flat alias: get a quote by id (lazy expiry applied) | All roles |
| GET | `/shops/quotes` | Flat alias: list/filter quotes | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/coil-data-records/{coilDataRecordId}` | Flat alias: get a coil data record by id | All roles |
| GET | `/shops/coil-data-records` | Flat alias: list/filter coil data records | ShopAdmin, Technician, WindingTechnician, Estimator, ServiceManager |
| GET | `/shops/pool-contracts-flat/{contractId}` | Flat alias: get a pool contract by id | ShopAdmin, Estimator, ServiceManager, Customer |
| GET | `/shops/pool-contracts-flat` | Flat alias: list/filter pool contracts | ShopAdmin, Estimator, ServiceManager |
| GET | `/shops/pool-loans/{loanId}` | Flat alias: get a pool loan by id (lazy overdue applied) | ShopAdmin, Estimator, ServiceManager, Customer |
| GET | `/shops/pool-loans` | Flat alias: list/filter pool loans | ShopAdmin, Estimator, ServiceManager |
| GET | `/shops/invoices-flat/{invoiceId}` | Flat alias: get an invoice by id (lazy overdue applied) | ShopAdmin, Estimator, ServiceManager, Customer |
| GET | `/shops/invoices-flat` | Flat alias: list/filter invoices | ShopAdmin, Estimator, ServiceManager |
| GET | `/shops/warranty-claims-flat/{claimId}` | Flat alias: get a warranty claim by id | ShopAdmin, Technician, Estimator, ServiceManager, Customer |
| GET | `/shops/warranty-claims-flat` | Flat alias: list/filter warranty claims | ShopAdmin, Technician, Estimator, ServiceManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this table is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_INPUT` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_CUSTOMER_ON_HOLD` | 402 Payment Required |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_ACTIVE` | 409 Conflict |
| `ERR_FINAL_TEST_NOT_PASS` | 409 Conflict |
| `ERR_POOL_UNAVAILABLE` | 409 Conflict |
| `ERR_WARRANTY_OUT_OF_WINDOW` | 422 Unprocessable Entity |
| `ERR_WARRANTY_EXCLUDED_MODE` | 422 Unprocessable Entity |
| `ERR_INVOICE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_CLAIMS_OPEN` | 409 Conflict |

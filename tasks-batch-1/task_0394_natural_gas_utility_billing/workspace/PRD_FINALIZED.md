# Natural Gas Utility Billing API — Product Requirements Document

## 1. Introduction

This document specifies the back-office service that a regulated natural-gas distribution utility uses to run its customer book end to end: setting meters, capturing register reads, converting raw register movement into therms of energy, pricing each billing cycle, collecting payments, and managing the regulated lifecycle of service (shutoff, disconnection, reconnection, and account finalization). The system blends a **pricing engine** — where a cyclic bill is assembled from a fixed customer charge, a delivery (distribution) charge, and a monthly purchased-gas (PGA) commodity charge — with a **compliance and field-operations** layer, where emergency leak/odor tickets, the winter shutoff moratorium, security deposits, and a low-income assistance program all impose hard gates on what the utility may do to an account.

Two billing modes coexist. Under ordinary **actual-cost billing**, a customer pays the full computed cyclic charge each month. Under **budget (levelized) billing**, the customer instead pays a flat monthly installment, while the utility quietly accrues the true cyclic cost so that an annual **true-up** can settle the difference. The service must keep both views consistent: a levelized installment is what the customer is billed today, but the accrued actual cost is what eventually determines whether the customer underpaid or overpaid across the plan year.

Because field crews, billing clerks, and customers all act on the same accounts — sometimes against a stale view of an account's balance or version — the system enforces optimistic concurrency on the account aggregate, strict register-monotonicity on meters, and an explicit safety-first ordering on every operation that could de-energize a premise. The remainder of this document defines the global contracts (Section 2), the business workflows where most of the domain rules live (Section 3), the endpoint surface (Section 4), and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the caller's role. If `X-User-Role` is missing or does not name one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four roles are spelled exactly `BillingAdmin`, `CustomerService`, `FieldTech`, and `Account`.

- A `BillingAdmin` owns rate and PGA configuration, bill creation/issuance/voiding, budget enrollment and annual true-up, deposit refunds, credit expiry, meter-read voiding, account finalization, and the test-driving clock and on-time-count controls.
- A `CustomerService` operator owns account opening, the shutoff and cancel-shutoff actions, deposit creation/collection/waiver, low-income intake and approval/denial, payments, and the cancellation of service orders and tickets.
- A `FieldTech` owns field operations: meter removal, posting reads, service-order dispatch and completion, and the emergency-ticket dispatch, make-safe, and resolve actions.
- An `Account` is the customer self-service role: it may read its own account and child collections, submit its own low-income application, post its own payment, and open an emergency ticket.

Three of these roles — `BillingAdmin`, `CustomerService`, and `FieldTech` — have an **opaque** identity: when one of them is the caller, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but never compares it to any entity's `id`. The `Account` role is **entity-backed**: when `X-User-Role` is `Account`, `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an account compare that resource's `account_id` to `X-User-ID`; an `Account` principal acting on a resource whose `account_id` is not its own is rejected with `ERR_FORBIDDEN`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1, and a maximum of 100; a requested limit above the maximum is capped to 100. The `offset` defaults to 0 and counts the number of leading items skipped. List results are ordered by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of matching records ignoring pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Most resources also carry three common system fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 on creation and increments by one on every mutation of that resource. `created_at` is fixed at creation; `updated_at` is refreshed on every mutation alongside the `version` bump.

Three resource kinds are append-only event records and therefore carry only `id` and `created_at` — they have no `updated_at` and no `version`: a **MeterRead** (a captured register reading), a **Payment** (a posted remittance), and the singleton **Clock**. Even though a MeterRead can be voided and a Payment can be reversed, those status changes do not introduce an `updated_at` or `version` on those records.

### 2.5. Nested Resource Addressing

Many resources are addressed beneath their owning account — meters, bills, payments, budget plans, deposits, and low-income credits all live under an account path, and meter reads live under a meter. When a request names a chain of resources, the server validates the chain left to right and returns `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path or body that does not resolve — the account before the meter, the meter before the read, the account before the bill, and so on. A child that exists but does not belong to the named parent is treated as not found in that context.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and transmitted as integer **cents**; the system never carries fractional cents. Wherever a calculation must collapse a non-integer intermediate to cents — multiplying therms by a per-therm rate, applying a percentage discount, or dividing a projected annual total into installments — the result is rounded **half up** (a value at the midpoint rounds away from zero to the next whole cent). Therm quantities are the one non-money quantity that carries a fraction: consumed therms are rounded **half up to one decimal place**. Raw register movement in CCF is not rounded.

The order in which rounding is applied matters and is fixed per calculation in Section 3; in particular, the commodity charge multiplies an unrounded therm quantity by the effective per-therm commodity rate and rounds the cents result exactly once at the end, rather than rounding any intermediate product.

### 2.7. Optimistic Concurrency on the Account Aggregate

Two write operations mutate an account against a client's prior view of that account and are therefore guarded by optimistic concurrency control on `Account.version`. Each such request must carry `expected_account_version`, a non-optional integer carrying the client's last observed `version` of the target account.

The first guarded operation is **issuing a bill**: the issue request must carry `expected_account_version` equal to the target account's current `version`. If another writer has advanced the account's version since the client last read it — for example, another bill was issued, or a shutoff or reconnect completed, each of which bumps `Account.version` — the issue is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), preventing the writer from issuing against a balance it has not observed. The second guarded operation is **creating a budget plan**: the enrollment request must likewise carry `expected_account_version` equal to the account's current `version`, and an older value (meaning an intervening enrollment or billing mutation has advanced the account) is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412). No other endpoint takes a version field.

### 2.8. The Logical Clock

The service runs against a logical clock rather than wall-clock time, so that due dates, past-due computation, payment timeliness, and the seasonal moratorium can be driven deterministically. The clock exposes `current_utc`, the logical "now" used for all of those computations, and `heating_season_active`, an operator-set boolean asserting that the regulator's cold-weather window is currently in force. A `BillingAdmin` may advance the clock and toggle the heating-season flag. When `current_utc` is unset by the operator it begins at `2026-01-01T00:00:00.000Z` and `heating_season_active` begins false. Reads of an account recompute its balance-derived fields against the clock's present value. A companion test-driving capability lets a `BillingAdmin` set a named account's `consecutive_ontime_payments` directly to a supplied `count`, so that the deposit-waive and deposit-refund thresholds can be reached without simulating a full year of billing cycles.

### 2.9. Safety-First and Moratorium Gates

Certain operations that would de-energize or endanger a premise are gated by two cross-cutting protections evaluated before the operation proceeds. The **emergency safety hold** blocks any account-shutoff progress while a live hazard exists, and the **winter moratorium** blocks disconnection during the regulated cold-weather window. Both gates and their precise trigger conditions are described in the workflows of Section 3, and both surface as 409 conflicts (`ERR_EMERGENCY_HOLD` and `ERR_WINTER_MORATORIUM`) rather than silently succeeding.

### 2.10. Validation Order

When several conditions could reject the same request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication is checked first: a missing or invalid role yields `ERR_UNAUTHENTICATED` (401). Authorization is next: a recognized but unpermitted role — including an `Account` principal reaching outside its own account — yields `ERR_FORBIDDEN` (403). Existence is third: every referenced resource id, validated left to right across the path and body, must resolve or the request yields `ERR_NOT_FOUND` (404). Request well-formedness is fourth: required body fields must be present and well-typed, enums must be valid, and integers constrained to be non-negative (or strictly positive) must respect those bounds, else `ERR_INVALID_REQUEST` (400). Uniqueness constraints are fifth, yielding `ERR_DUPLICATE` (409). Billing-period and budget-period overlap checks follow uniqueness. The target-state check for a transition then yields `ERR_INVALID_STATE` (409) when the resource is not in a state from which the requested transition is defined. The remaining business gates — emergency hold, winter moratorium, register rollback, referential billing prerequisites, optimistic-concurrency, and reconnect prerequisites — are evaluated after the state check, in that relative order. In practice this means a safety hold or moratorium surfaces ahead of a register-rollback or stale-version rejection on the same request.

## 3. Business Logic & Workflows

### 3.1. Pricing Configuration: Rate Schedules and Monthly PGA

Before any account can exist, a `BillingAdmin` configures the pricing reference data. A **rate schedule** is created with a unique `code` (for example `RES-1`, unique across all rate schedules, a duplicate rejected with `ERR_DUPLICATE`), a `customer_class` of either `RESIDENTIAL` or `COMMERCIAL`, a `fixed_customer_charge_cents` (the flat monthly basic-service charge, which must be at least 0), and a `distribution_rate_cents_per_therm` (the per-therm delivery charge in integer cents, at least 0, possibly 0). Two optional inputs round out the schedule: `btu_factor`, the therm-conversion factor equal to the gas heating value in BTU per cubic foot divided by one hundred thousand, which defaults to 1.025 and must lie between 0.9 and 1.2 inclusive; and `minimum_bill_cents`, a floor applied to total current charges before credits, which defaults to 0 and must be at least 0. Each schedule carries a system-managed `active` flag that defaults to true and governs whether the schedule may be assigned to new accounts.

A **PGA schedule** captures the monthly purchased-gas commodity rate. It is created with an `effective_month` in `YYYY-MM` form, a `customer_class` (`RESIDENTIAL` or `COMMERCIAL`), and a `commodity_rate_cents_per_therm` (the purchased-gas rate in integer cents per therm, at least 0). An optional `supplier_refund_cents_per_therm` (defaulting to 0, at least 0) records a per-therm credit netting back over-collection from the supplier. The combination of `customer_class` and `effective_month` must be unique; a second PGA row for the same class and month is rejected with `ERR_DUPLICATE`. When a bill is priced, the **effective** commodity rate is the `commodity_rate_cents_per_therm` reduced by `supplier_refund_cents_per_therm`, floored at 0 (the refund never drives the effective rate negative).

### 3.2. Opening an Account and Setting a Meter

A `CustomerService` operator opens an account by supplying a `rate_schedule_id` and a `holder_name`. At creation the account copies its `customer_class` from the assigned rate schedule, comes up with `service_status` of `ACTIVE`, and starts every money-derived field — `balance_cents`, `past_due_cents`, `deposit_held_cents` — at 0. Several other system fields begin at their defaults: `low_income_status` is `NONE`, `low_income_tier` is `NONE`, `budget_enrolled` is false, and `consecutive_ontime_payments` is 0. The account's `shutoff_eligible` flag is computed on read (see Section 3.9).

A premise meter is then registered under the account with a unique `serial_no` (a duplicate serial rejected with `ERR_DUPLICATE`), an optional `uom` register unit that is `CCF` or `THERM` and defaults to `CCF`, and an optional `install_index` register reading at set time (the baseline), defaulting to 0 and required to be at least 0. The meter is created with `account_id` linking it to its account and `status` of `PENDING_SET`. Its `last_index` tracks the most recent reading index from a non-voided read, falling back to the `install_index` when no such read exists. A newly registered meter does not energize service by itself; a separate `METER_SET` service order must be created, dispatched, and completed to bring the meter into service. When the meter-set order is completed, the meter advances from `PENDING_SET` to `SET`, its `install_index` is overwritten with the order's captured completion index, and the meter's `version` is bumped. A meter-set completion is rejected if the captured index would run the register backward relative to the recorded install baseline (see Section 3.4).

A `FieldTech` may retire a meter, driving it to the terminal `REMOVED` status and bumping its `version`. A meter in `LOCKED` status may be removed unconditionally. A meter in `SET` status may be removed only when no `DRAFT` bill references an unconsumed read on that meter; an attempt to remove a `SET` meter while such a draft is outstanding is rejected with `ERR_VALIDATION_PENDING_BILLS`.

### 3.3. Service Orders and the Field Lifecycle

Field work is scheduled through **service orders**. A service order is created with an `account_id`, an `order_type` of `METER_SET`, `SHUTOFF`, or `RECONNECT`, an optional `premise_meter_id` (the meter the order acts on, required in practice for `METER_SET`, `SHUTOFF`, and `RECONNECT` work), and an optional `scheduled_date`. It begins in `SCHEDULED`. A `FieldTech` dispatches a scheduled order, advancing it `SCHEDULED → DISPATCHED`; a dispatch attempted before the order's `scheduled_date` has been reached relative to the clock is rejected with `ERR_ORDER_NOT_DUE`. A dispatched order is then completed, advancing `DISPATCHED → COMPLETED`, and completion is what drives the matching account or meter transition described elsewhere in this section. A service order may also be cancelled by a `CustomerService` operator from either `SCHEDULED` or `DISPATCHED`, moving it to `CANCELLED`.

Completion carries an optional `completed_index`, the register index captured in the field. For both `METER_SET` and `SHUTOFF` completions the `completed_index` is required; omitting it is rejected with `ERR_MISSING_COMPLETION_INDEX`. For a `METER_SET` completion the captured `completed_index` must be at least the meter's recorded `install_index`, and a lower value is rejected with `ERR_INDEX_ROLLBACK`. A `SHUTOFF` completion additionally posts a final actual read from the captured index (see Section 3.10), and is subject to the winter-moratorium and emergency-hold gates of Section 3.9.

### 3.4. Posting Reads and Converting Register Movement to Therms

A `FieldTech` or `BillingAdmin` posts a meter read against a meter. The read body supplies a `reading_index` (the register index at read time, at least 0), an optional `read_date` (the ISO 8601 date the read was taken, defaulting to the clock when omitted), and an optional `read_type` of `ACTUAL` or `ESTIMATED` that defaults to `ACTUAL`. The system stamps the read with `premise_meter_id`, copies the meter's `account_id` onto the read, sets `status` to `POSTED`, and leaves `bill_id` null until an issued bill consumes the read. A read may later be voided by a `BillingAdmin`, setting its `status` to `VOID`; voided reads are excluded from all consumption math.

Consumption is computed against the immediately prior reading. The **prior index** is the `reading_index` of the most recent non-voided read on the same meter whose `read_date` is strictly earlier than this read's `read_date`; when there is no earlier read, the prior index is the meter's `install_index`. Ordering among reads uses `read_date` ascending, breaking ties by `created_at` ascending. The **raw register delta** is this read's `reading_index` minus the prior index; if that delta is negative the read is rejected with `ERR_INDEX_ROLLBACK`, because a register cannot run backward. The delta is recorded as `ccf_consumed` (the raw register movement, in the register's own units, whether the meter reads in CCF or in therms). The energy quantity `therms_consumed` then depends on the meter's `uom`: for a `CCF` meter, `therms_consumed` is the raw delta multiplied by the rate schedule's `btu_factor`; for a `THERM` meter, the register already reads in therms, so `therms_consumed` is the raw delta directly. In both cases `therms_consumed` is rounded half up to one decimal place.

### 3.5. Drafting and Issuing a Cyclic Bill

A `BillingAdmin` drafts a bill under an account for a `service_month` (`YYYY-MM`), naming the closing read via `to_read_id` and optionally the opening read via `from_read_id`; a rebill additionally names `corrects_bill_id`, the prior bill it supersedes (otherwise null). A draft bill comes up in `DRAFT` with `budget_billed_cents` defaulting to 0 and `paid_cents` defaulting to 0. At draft time two collisions are checked: at most one non-corrected bill may exist per `(account_id, service_month)`, a duplicate rejected with `ERR_DUPLICATE`; and the new bill's read-date window must not overlap an existing bill's window on the same meter, as described in Section 3.6.

Issuing a draft bill advances it `DRAFT → ISSUED` and is where the cyclic charge is assembled. Issuance is guarded by the account optimistic-concurrency rule of Section 2.7 (the request carries `expected_account_version`, and a mismatch yields `ERR_STALE_ACCOUNT_VERSION`). Before charges are computed, two referential preconditions are checked: a PGA schedule must exist for the bill's `(customer_class, service_month)` pairing, absent which the issue is rejected with `ERR_PGA_NOT_FOUND`; and the closing read named by `to_read_id` must be a `POSTED` `ACTUAL` or `ESTIMATED` read that is newer than the opening read, absent which the issue is rejected with `ERR_READ_REQUIRED`.

The charge build proceeds in a pinned order. First, `therms_billed` is the closing read's `therms_consumed`, less any therms already billed by a prior non-corrected bill on the same meter window; for an ordinary single-cycle bill this equals the closing read's `therms_consumed`. Second, the commodity charge: the effective per-therm PGA rate (the month's `commodity_rate_cents_per_therm` minus its `supplier_refund_cents_per_therm`, floored at 0) is computed first, then multiplied by `therms_billed`, and that single product is rounded half up to whole cents to give `commodity_charge_cents` — the rounding happens once, at the end, not on any intermediate. Third, `distribution_charge_cents` is `therms_billed` multiplied by the rate schedule's `distribution_rate_cents_per_therm`, rounded half up to cents, and `fixed_charge_cents` is simply the rate schedule's `fixed_customer_charge_cents`. Fourth, the gross is the sum of `commodity_charge_cents`, `distribution_charge_cents`, and `fixed_charge_cents`, then raised to the rate schedule's `minimum_bill_cents` if the sum falls below that floor. Fifth, the low-income credit for this cycle (Section 3.8) is computed into `low_income_credit_cents` and subtracted from the gross, with the net floored at 0 to yield `amount_due_cents`.

On a successful issue the system stamps `due_date` as the clock's present date plus the payment term of twenty-one days, sets the closing read's `bill_id` and marks the reads in the window consumed, and bumps `Account.version` by one. The two billing modes diverge only in what the customer is actually charged this cycle, captured in `budget_billed_cents`: when the account is **not** budget-enrolled at issue time, `budget_billed_cents` equals `amount_due_cents` and the customer pays the full computed cyclic amount; when the account **is** budget-enrolled (an `ACTIVE` budget plan exists) at issue time, `budget_billed_cents` is instead the plan's flat `monthly_installment_cents`, while `amount_due_cents` is still computed and accrued for the year-end true-up. In the budget case, issuance also accrues onto the plan: the plan's `accrued_actual_cents` grows by this bill's `amount_due_cents` and its `accrued_budget_cents` grows by this bill's `budget_billed_cents`.

A draft bill may instead be voided by a `BillingAdmin`, moving it `DRAFT → VOID`; voiding clears the closing read's `bill_id` and releases the reads in the window so they can be billed again.

### 3.6. Rebills and Period Overlap

A correction is modeled as a new bill that references `corrects_bill_id`. The superseded bill must be an `ISSUED` bill in the same `service_month`; when the rebill is issued, the original bill moves `ISSUED → CORRECTED`, and only the rebill's recomputed charges are reflected in the account balance going forward. A rebill is exempt from the overlap check against the specific bill it corrects.

The billing-period overlap rule guards against double-billing a stretch of register movement. A new bill's read-date window runs from the opening read's `read_date` to the closing read's `read_date` and is treated as a **closed interval**: two windows that merely touch at an endpoint are considered to overlap. If the new window overlaps any existing non-void, non-corrected bill window on the **same meter**, the create is rejected with `ERR_BILLING_PERIOD_OVERLAP` — except for the window of the very bill a rebill is correcting, which is exempt.

### 3.7. Budget (Levelized) Billing and Annual True-Up

Enrollment in budget billing is performed by a `BillingAdmin` or `CustomerService` operator and creates a budget plan against the account. The request supplies an `anchor_month` (the first service month the installment applies to, `YYYY-MM`), a `projected_annual_cents` estimate of the twelve-month total (at least 0), and `expected_account_version` for the optimistic-concurrency check of Section 2.7 (a mismatch rejected with `ERR_STALE_ACCOUNT_VERSION`). The plan's flat `monthly_installment_cents` is set at enrollment to `projected_annual_cents` divided by twelve, rounded half up to whole cents. A new plan begins `ACTIVE` with `accrued_actual_cents` and `accrued_budget_cents` at 0 and `trueup_balance_cents` at 0; creating it sets `Account.budget_enrolled` to true and bumps `Account.version`.

A plan covers a twelve-month window. The coverage window runs from `anchor_month` and spans twelve months as a **half-open interval**: a plan whose `anchor_month` is exactly the month at which a prior plan's window ends does **not** collide, but any genuine overlap with an existing `ACTIVE` plan window on the same account is rejected with `ERR_BUDGET_PERIOD_OVERLAP`.

The annual **true-up** is run by a `BillingAdmin` and advances the plan `ACTIVE → TRUED_UP`. It requires that at least one bill has been issued under the plan; if none has, it is rejected with `ERR_NO_BILLS_TO_TRUE_UP`. At true-up, `trueup_balance_cents` is set to the plan's `accrued_actual_cents` minus its `accrued_budget_cents`, where those accruals sum, respectively, the `amount_due_cents` and the `budget_billed_cents` of the bills issued under the plan whose status is `ISSUED` or `PAID` (corrected and voided bills excluded) for service months at or after the plan's `anchor_month`, ordered by `service_month` ascending then `created_at` ascending. The difference is exact and needs no rounding. When the balance is positive the customer underpaid across the year and a debit true-up bill for that residual is created as a new `DRAFT` bill; when the balance is negative the customer overpaid and a credit bill (a negative net) is created as a new `DRAFT` bill to reduce the balance; when the balance is exactly 0 no residual bill is created. True-up also clears `Account.budget_enrolled` to false. A plan may alternatively be cancelled by a `CustomerService` operator, moving it `ACTIVE → CANCELLED` and likewise clearing `Account.budget_enrolled` to false.

### 3.8. Low-Income Assistance: Eligibility and Per-Cycle Credit

A customer applies for assistance through a low-income credit application, which a `CustomerService` operator or the `Account` principal itself submits. The application carries a `household_size` (at least 1) and an `annual_income_cents` (at least 0), and is created in `SUBMITTED` with its eligibility `tier` computed at submission. Eligibility compares reported income to a household-adjusted federal poverty line: the poverty line is a base of 1,509,000 cents (fifteen thousand and ninety dollars for a household of one) plus 532,000 cents (five thousand three hundred twenty dollars) for each additional household member beyond the first. The income-to-poverty ratio is the reported `annual_income_cents` divided by that poverty line. If the ratio is at or below 1.00 the application is `TIER_1` (deepest need); otherwise if the ratio is at or below 1.50 it is `TIER_2` (moderate need); otherwise the tier is `NONE`. Both boundaries are inclusive.

A `CustomerService` operator approves the application, advancing it `SUBMITTED → APPROVED`, but approval is rejected with `ERR_NOT_ELIGIBLE` when the computed tier is `NONE`. Approval cascades onto the account: `low_income_status` becomes `ENROLLED` and `low_income_tier` becomes the approved credit's tier. An application may instead be denied by a `CustomerService` operator, moving it `SUBMITTED → DENIED`. An `APPROVED` credit may later be expired by a `BillingAdmin`, moving it `APPROVED → EXPIRED`; if no other approved credit remains on the account, expiry resets the account's `low_income_status` to `NONE` and `low_income_tier` to `NONE`.

While an account is enrolled, each issued bill earns a per-cycle credit folded into `low_income_credit_cents`. The credit applies only to the sum of `commodity_charge_cents` and `distribution_charge_cents` — never to the fixed customer charge. For a `TIER_1` account the discount is twenty percent of that creditable base, capped at 4,000 cents per month; for a `TIER_2` account the discount is ten percent of the creditable base, capped at 2,500 cents per month; for any other tier the credit is 0. The discounted amount is computed as the creditable base multiplied by the tier percentage, rounded half up to whole cents, and then the lesser of that rounded amount and the tier's monthly cap is taken (the cap is applied after rounding).

### 3.9. Delinquency, Shutoff, and the Winter Moratorium

An account's receivable position drives the regulated shutoff path. `balance_cents` is the sum of `amount_due_cents` across issued bills minus the sum of `amount_cents` across posted payments (positive means owed by the customer). `past_due_cents` is the sum of `amount_due_cents` over issued bills whose `due_date` is strictly before the clock's current date and which are not fully paid. An account becomes **shutoff-eligible** when its `past_due_cents` is at least the shutoff threshold of 7,500 cents (seventy-five dollars) **and** the winter moratorium is not in effect; `shutoff_eligible` is recomputed whenever the account is read.

The **winter moratorium** is in effect when both conditions hold: the calendar month of the clock's `current_utc` is one of the protected months — November, December, January, February, or March — **and** the clock's `heating_season_active` flag is true. Either condition alone does not establish the moratorium; both must hold together.

A `CustomerService` operator issues a shutoff notice, advancing the account `ACTIVE → SHUTOFF_PENDING`. The notice is permitted only when the account is shutoff-eligible — meaning `past_due_cents` is at least 7,500 cents and the moratorium is not in effect — and is otherwise rejected with `ERR_NOT_SHUTOFF_ELIGIBLE`. Two further gates apply: if a live hazard exists, that is, any emergency ticket in `OPEN`, `DISPATCHED`, or `MADE_SAFE` status on any of the account's meters, the notice is rejected with `ERR_EMERGENCY_HOLD`; and if the winter moratorium is in effect, the notice is rejected with `ERR_WINTER_MORATORIUM`. A successful notice bumps `Account.version` and auto-creates a `SHUTOFF` service order in `SCHEDULED` against the account's set meter. The notice can be withdrawn by a `CustomerService` operator with a cancel-shutoff action, moving the account `SHUTOFF_PENDING → ACTIVE`, bumping `Account.version`, and cancelling any scheduled or dispatched `SHUTOFF` service order for the account.

Disconnection itself happens when a `FieldTech` completes the `SHUTOFF` service order, advancing the account `SHUTOFF_PENDING → DISCONNECTED`. That completion is again gated: it is rejected with `ERR_WINTER_MORATORIUM` if the moratorium is in effect at completion time, and with `ERR_EMERGENCY_HOLD` if a live hazard ticket exists on the account's meters. On success the account becomes `DISCONNECTED`, the meter moves to `LOCKED`, `Account.version` is bumped, and a final actual read is posted from the order's captured completion index. Taken together, the emergency safety hold blocks two operations — the shutoff notice and the `SHUTOFF` order completion — and the winter moratorium blocks those same two operations.

### 3.10. Reconnection, Finalization, and the Cascades That Close an Account

Reconnection restores a disconnected account. A `RECONNECT` service order is created and dispatched, and when a `FieldTech` completes it the account advances `DISCONNECTED → ACTIVE`. Three preconditions guard the completion: a `RECONNECT` service order must exist and be `DISPATCHED`; the account's `past_due_cents` must be exactly 0, else the reconnect is rejected with `ERR_RECONNECT_BALANCE_DUE`; and a deposit whose `reason` is `RECONNECT` must be in `HELD` or `WAIVED` status, else the reconnect is rejected with `ERR_RECONNECT_DEPOSIT_REQUIRED`. On success the account returns to `ACTIVE`, the meter returns to `SET`, `Account.version` is bumped, and `consecutive_ontime_payments` is reset to 0.

Finalization closes out a disconnected account. A `BillingAdmin` issues the final bill, moving the account `DISCONNECTED → FINALED` (a terminal status) and bumping `Account.version`. Finalization cascades across the account's open instruments: any `HELD` deposit is applied against the balance and any remainder is refunded, and any `ACTIVE` budget plan is trued up. The deposit's own lifecycle reflects this — a held deposit applied at finalization moves to `APPLIED` against `balance_cents`.

### 3.11. Security Deposits

A deposit requirement is created by a `CustomerService` operator with a `reason` of `NEW_SERVICE`, `RECONNECT`, or `DELINQUENCY`; its required `amount_cents` is computed at creation. The required amount is 0 — and the deposit is therefore created already `WAIVED` rather than `REQUIRED` — when either the account is enrolled in low-income assistance (`low_income_status` is `ENROLLED`, making the customer deposit-exempt) or the account has accumulated at least twelve consecutive on-time payments (good-payment history waives the deposit). Otherwise the base is 15,000 cents for a `RESIDENTIAL` account and 40,000 cents for a `COMMERCIAL` account; and when the `reason` is `DELINQUENCY`, that base is multiplied by 1.5 and rounded half up to whole cents.

A required deposit is collected by a `CustomerService` operator, moving it `REQUIRED → HELD` and recomputing the account's `deposit_held_cents` (the sum of held deposit amounts net of refunded and applied amounts). A collect attempt on a deposit whose amount is 0 is rejected with `ERR_DEPOSIT_WAIVED_NOT_PAYABLE`. A required deposit may instead be waived by a `CustomerService` operator, moving it `REQUIRED → WAIVED`. A held deposit is refunded by a `BillingAdmin`, moving it `HELD → REFUNDED` and recomputing `deposit_held_cents`, but the refund is permitted only once the account has at least twelve consecutive on-time payments; an earlier attempt is rejected with `ERR_DEPOSIT_REFUND_NOT_DUE`. As noted in Section 3.10, a held deposit on a finalized account is applied rather than refunded.

### 3.12. Payments and On-Time Standing

A payment is posted by a `CustomerService` operator or by the `Account` principal itself, allocated to a specific bill named by `bill_id`, with an `amount_cents` strictly greater than 0 and an optional `posted_date` (defaulting to the clock). The payment is recorded with `status` of `POSTED` and copies the account onto its `account_id`. A payment is considered **on-time** when its `posted_date` is on or before the target bill's `due_date` — paying on the due date itself counts as on-time — and this is recorded on the payment's `on_time` flag.

When the cumulative `POSTED` payment amount allocated to a bill reaches the amount the customer owes for that bill, the bill advances `ISSUED → PAID`; the threshold is `amount_due_cents` for an ordinary bill and `budget_billed_cents` for a budget bill. The bill's `paid_cents` tracks the sum of posted payments allocated to it. When a bill reaches `PAID`, the account's `consecutive_ontime_payments` is incremented by one if the last allocating payment was on-time, and reset to 0 if it was late. A payment may be reversed, moving it from `POSTED` to `REVERSED`.

### 3.13. Emergency Tickets and the Safety Lifecycle

An emergency ticket is opened by a `CustomerService` operator, a `FieldTech`, or the `Account` principal, naming the `premise_meter_id` where the hazard is, a `kind` of `ODOR`, `LEAK`, or `CARBON_MONOXIDE`, an optional `account_id`, and an optional `reported_indoors` flag (defaulting to false). The ticket opens in `OPEN`, and its severity and field-response target are derived from the kind and indoor flag. An indoor leak, and any carbon-monoxide report, is `GRADE_1` with a sixty-minute response target; an outdoor leak or an indoor odor is `GRADE_2` with a two-hundred-forty-minute target; an outdoor odor is `GRADE_3` with a one-thousand-four-hundred-forty-minute (twenty-four-hour) target. The computed `severity` and `response_due_minutes` are stamped on the ticket, and the `gas_locked` flag begins false.

A `FieldTech` works the ticket through its lifecycle: dispatching it `OPEN → DISPATCHED`, marking it `DISPATCHED → MADE_SAFE`, and resolving it `MADE_SAFE → RESOLVED`. When a `GRADE_1` ticket is made safe, the technician locks the meter: the ticket's `gas_locked` flag is set true and the associated meter's `status` is driven to `LOCKED`. A ticket may be cancelled as a false alarm by a `CustomerService` operator from either `OPEN` or `DISPATCHED`, moving it to `CANCELLED`. As long as a ticket on the account's meters sits in `OPEN`, `DISPATCHED`, or `MADE_SAFE`, the account's shutoff path is held per Section 3.9; resolving or cancelling the ticket clears that hold.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201 with the created resource in `data`. State-transition and other mutation endpoints return HTTP 200 with the updated resource. Read endpoints return HTTP 200. Errors follow the envelope of Section 2.2 with the status codes listed in Section 5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set` | Set the logical clock and heating-season flag | BillingAdmin |
| GET | `/_clock` | Read the current clock | BillingAdmin, CustomerService, FieldTech |
| POST | `/_inject/account-ontime-count` | Test-driving: set an account's consecutive on-time payment count | BillingAdmin |
| POST | `/rate-schedules` | Create a rate schedule | BillingAdmin |
| GET | `/rate-schedules/{id}` | Get a rate schedule | BillingAdmin, CustomerService |
| POST | `/pga-schedules` | Create a monthly PGA commodity rate | BillingAdmin |
| GET | `/pga-schedules/{id}` | Get a PGA schedule | BillingAdmin, CustomerService |
| POST | `/accounts` | Open a new account | CustomerService |
| GET | `/accounts` | List accounts, optionally filtered by rate schedule | BillingAdmin, CustomerService |
| GET | `/accounts/{id}` | Get an account with recomputed balances | BillingAdmin, CustomerService, FieldTech, Account |
| POST | `/accounts/{id}/shutoff-notice` | Begin shutoff; auto-creates a SHUTOFF service order | CustomerService |
| POST | `/accounts/{id}/cancel-shutoff` | Cancel a pending shutoff | CustomerService |
| POST | `/accounts/{id}/final-bill` | Finalize a disconnected account | BillingAdmin |
| POST | `/accounts/{id}/meters` | Register a premise meter | CustomerService, FieldTech |
| GET | `/accounts/{id}/meters` | List meters for an account | BillingAdmin, CustomerService, FieldTech, Account |
| GET | `/meters/{id}` | Get a premise meter | BillingAdmin, CustomerService, FieldTech, Account |
| POST | `/meters/{id}/remove` | Remove a meter | FieldTech |
| POST | `/meters/{id}/reads` | Post a meter read | FieldTech, BillingAdmin |
| GET | `/meter-reads` | List meter reads, filtered by meter/account/bill | BillingAdmin, CustomerService, FieldTech, Account |
| GET | `/meter-reads/{id}` | Get a single meter read | BillingAdmin, CustomerService, FieldTech, Account |
| POST | `/meters/{id}/reads/{read_id}/void` | Void a read | BillingAdmin |
| POST | `/accounts/{id}/bills` | Create a DRAFT bill (or a rebill) | BillingAdmin |
| GET | `/bills` | List bills, filtered by account/read/correction | BillingAdmin, CustomerService, Account |
| GET | `/bills/{id}` | Get a bill with computed charges | BillingAdmin, CustomerService, Account |
| POST | `/accounts/{id}/bills/{bill_id}/issue` | Issue a DRAFT bill (OCC on account version) | BillingAdmin |
| POST | `/accounts/{id}/bills/{bill_id}/void` | Void a DRAFT bill | BillingAdmin |
| POST | `/accounts/{id}/payments` | Post a payment allocated to a bill | CustomerService, Account |
| GET | `/payments` | List payments, filtered by account/bill | BillingAdmin, CustomerService, Account |
| GET | `/payments/{id}` | Get a single payment | BillingAdmin, CustomerService, Account |
| POST | `/accounts/{id}/budget-plans` | Enroll in budget billing (OCC on account version) | BillingAdmin, CustomerService |
| GET | `/accounts/{id}/budget-plans` | List budget plans for an account | BillingAdmin, CustomerService, Account |
| POST | `/accounts/{id}/budget-plans/{plan_id}/true-up` | Run the annual true-up | BillingAdmin |
| POST | `/accounts/{id}/budget-plans/{plan_id}/cancel` | Cancel a budget plan | CustomerService |
| POST | `/accounts/{id}/deposits` | Create a deposit requirement | CustomerService |
| GET | `/accounts/{id}/deposits` | List deposits for an account | BillingAdmin, CustomerService, Account |
| POST | `/accounts/{id}/deposits/{deposit_id}/collect` | Collect a required deposit | CustomerService |
| POST | `/accounts/{id}/deposits/{deposit_id}/waive` | Waive a required deposit | CustomerService |
| POST | `/accounts/{id}/deposits/{deposit_id}/refund` | Refund a held deposit | BillingAdmin |
| POST | `/accounts/{id}/low-income-credits` | Submit a low-income application | CustomerService, Account |
| GET | `/accounts/{id}/low-income-credits` | List credits for an account | BillingAdmin, CustomerService, Account |
| POST | `/accounts/{id}/low-income-credits/{credit_id}/approve` | Approve an application | CustomerService |
| POST | `/accounts/{id}/low-income-credits/{credit_id}/deny` | Deny an application | CustomerService |
| POST | `/accounts/{id}/low-income-credits/{credit_id}/expire` | Expire an approved credit | BillingAdmin |
| POST | `/service-orders` | Create a service order | CustomerService, FieldTech |
| GET | `/service-orders/{id}` | Get a service order | BillingAdmin, CustomerService, FieldTech, Account |
| GET | `/service-orders` | List service orders, filtered by account/meter | BillingAdmin, CustomerService, FieldTech, Account |
| POST | `/service-orders/{id}/dispatch` | Dispatch a scheduled order | FieldTech |
| POST | `/service-orders/{id}/complete` | Complete a dispatched order | FieldTech |
| POST | `/service-orders/{id}/cancel` | Cancel a service order | CustomerService |
| POST | `/tickets` | Open an emergency ticket | CustomerService, FieldTech, Account |
| GET | `/tickets/{id}` | Get an emergency ticket | BillingAdmin, CustomerService, FieldTech, Account |
| GET | `/tickets` | List emergency tickets, optionally filtered | BillingAdmin, CustomerService, FieldTech, Account |
| POST | `/tickets/{id}/dispatch` | Dispatch a ticket | FieldTech |
| POST | `/tickets/{id}/make-safe` | Mark a hazard made safe (GRADE_1 locks the meter) | FieldTech |
| POST | `/tickets/{id}/resolve` | Resolve a ticket | FieldTech |
| POST | `/tickets/{id}/cancel` | Cancel a ticket / false alarm | CustomerService |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE | 409 |
| ERR_INVALID_STATE | 409 |
| ERR_NOT_SHUTOFF_ELIGIBLE | 409 |
| ERR_EMERGENCY_HOLD | 409 |
| ERR_WINTER_MORATORIUM | 409 |
| ERR_INDEX_ROLLBACK | 409 |
| ERR_PGA_NOT_FOUND | 409 |
| ERR_READ_REQUIRED | 409 |
| ERR_MISSING_COMPLETION_INDEX | 400 |
| ERR_STALE_ACCOUNT_VERSION | 412 |
| ERR_ORDER_NOT_DUE | 409 |
| ERR_RECONNECT_BALANCE_DUE | 409 |
| ERR_RECONNECT_DEPOSIT_REQUIRED | 409 |
| ERR_DEPOSIT_WAIVED_NOT_PAYABLE | 409 |
| ERR_DEPOSIT_REFUND_NOT_DUE | 409 |
| ERR_NOT_ELIGIBLE | 409 |
| ERR_NO_BILLS_TO_TRUE_UP | 409 |
| ERR_VALIDATION_PENDING_BILLS | 409 |
| ERR_BILLING_PERIOD_OVERLAP | 409 |
| ERR_BUDGET_PERIOD_OVERLAP | 409 |

# Electric Utility Billing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Electric Utility Billing API, the system of record a regulated electric utility uses to turn raw meter telemetry into money owed and money collected. Modern advanced metering infrastructure (AMI) emits a continuous stream of hourly interval reads; the billing engine must aggregate those reads over a billing period, price them through an inclining-block tiered rate structure weighted by time-of-use periods, layer on a demand charge for peak load, and reconcile rooftop-solar exports against consumption through net-metering credits that roll forward month over month. On top of the pricing engine sits a ledger that tracks each account's balance as bills are issued, payments waterfall across oldest-due bills, LIHEAP and crisis assistance grants are consumed, and budget-billing plans smooth a customer's monthly outlay into a levelized installment that is later trued up against actual cost.

The system also governs the collections lifecycle that the utility is legally and operationally bound to follow. An account carries two independent status dimensions — one describing whether electric service is flowing and one describing the customer's financial standing — and the interplay between them drives the disconnect-for-nonpayment and reconnect-after-payment workflows, including the assistance shield that protects vulnerable customers from disconnection. Because issuing a bill and truing up a budget plan both move money against a shared account balance, the API enforces optimistic concurrency on those operations so that two operators acting on a stale snapshot cannot double-apply ledger effects. The remainder of this document defines the global contract every endpoint obeys, the cross-cutting principles that hold across the domain, and the detailed business workflows the engine implements.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. The system recognizes exactly four roles: `BillingOperator`, `FieldDispatcher`, `AssistanceCaseworker`, and `Customer`. If either header is missing, or if `X-User-Role` names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation under the role matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE`.

Three of the four roles carry an opaque identity. When `X-User-Role` is `BillingOperator`, `FieldDispatcher`, or `AssistanceCaseworker`, the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`. The `Customer` role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Account`, and ownership checks on any resource that references an `Account` compare that resource's `account_id` to `X-User-ID`. A `Customer` reads only their own account, bills, payments, meters, meter reads, budget plans, and assistance grants, and submits payments against their own account.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Unless an endpoint states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Resource Identity

Most resources in the system carry a standard set of system-managed fields. Every resource is assigned an `id`, a server-minted UUID with no type prefix. Each resource records a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, captured when the resource is first created. Tariffs, accounts, meters, bills, payments, service orders, budget plans, and assistance grants additionally carry an `updated_at` timestamp — likewise ISO 8601 UTC with three fractional digits, refreshed on every mutation — and a `version`, an integer that starts at its initial value and increments by one on each mutation of the resource.

Two resources are deliberately leaner. A `MeterRead` and the `SystemClock` carry only `id` and `created_at`; they expose neither `updated_at` nor `version`, because an imported AMI interval read is immutable once accepted and the clock is a singleton control surface. Wherever this document refers to a resource's version being incremented or its `updated_at` being refreshed, that applies only to resources that carry those fields.

### 2.5. Nested Resource Retrieval and Path Validation

The entity model is flat: the `Account` is the hub, and meters, meter reads, bills, payments, service orders, budget plans, and assistance grants all reference it (or, in the case of a meter read, reference a meter) by foreign key. Children are therefore not nested in URL paths; they are discovered through filtered list endpoints — for example, the meters of an account are retrieved by listing meters filtered by `account_id`, and the reads of a meter by listing meter reads filtered by `meter_id`. When a request does carry a path identifier, the server validates every path-referenced resource left-to-right and rejects the first one that does not exist with `ERR_NOT_FOUND`. When a creation request's body carries a foreign key — such as `account_id`, `meter_id`, or `tariff_id` — that references a resource which does not exist, the request is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All monetary values in the system are integer cents; there are no fractional-cent fields in any response body. Energy, demand, and credit components computed from real-valued kWh and kW quantities are converted to whole cents using the round-half-up rule. The energy charge is rounded exactly once, after the time-of-use-weighted sum is fully accumulated across all periods — never per period. The demand charge and the export credit are each rounded independently using the same round-half-up rule. Ledger aggregation operations that combine already-whole-cent counters — budget true-up reconciliation and the payment waterfall — are exact integer arithmetic and perform no rounding.

### 2.7. The Account Ledger and Net-Metering Credit Bank

Each account maintains a running `balance_cents`: a net amount owed, equal to the sum of issued bills' `total_due_cents` less the sum of applied payment amounts less applied assistance, where a positive value means the customer owes money and a negative value is a credit on the account. Issuing a bill increases `balance_cents` by that bill's `total_due_cents`; voiding an issued bill decreases it by the same amount; a payment reduces `balance_cents` by the full payment amount; and a budget true-up or cancel adjusts `balance_cents` by the plan's reconciled delta. The account opens with a `balance_cents` of 0 and may go negative when a customer overpays.

Separately, each account holds a `net_metering_credit_balance_cents`, a carried-forward bank of net-metering credit that rolls month to month. This credit bank is funded by customer exports priced at the tariff's net-metering rate and is drawn down when a bill applies credit; it never reduces a bill below that bill's fixed-charge-plus-demand-charge floor, so only the energy portion of a bill is ever offset by credit. The account also surfaces `oldest_unpaid_bill_due_date`, the due date of the oldest issued, not-fully-paid bill (null when there is none), which drives the arrears-age threshold described in Section 2.8; and `budget_plan_id`, a denormalized convenience pointer to the account's currently `ACTIVE` budget plan (null when there is none), set when a plan is enrolled and cleared when a plan is trued up or cancelled. The authoritative account-to-plan link is the budget plan's own `account_id`; clients discover an account's plans by listing budget plans filtered by `account_id`.

### 2.8. The Two Status Dimensions and Arrears Aging

An account carries two status dimensions that evolve independently and never collapse into a single field. The `service_status` dimension describes whether power is flowing and cycles through `ACTIVE`, `DISCONNECT_PENDING`, `DISCONNECTED`, and `RECONNECT_PENDING`. The `financial_status` dimension describes the customer's standing and moves among `CURRENT`, `DELINQUENT`, and `IN_ARREARS`. A newly opened account begins `ACTIVE` on the service dimension and `CURRENT` on the financial dimension.

Financial standing is recomputed from arrears age, measured against the simulated wall clock. The clock is a single `SystemClock` resource whose `current_utc` value is the authoritative "now" for all due-date comparisons. The arrears age of an account is derived from `oldest_unpaid_bill_due_date`, which is the earliest `due_date` among the account's bills in `ISSUED` or `PARTIALLY_PAID` status (bills that are `PAID` or `VOID` are excluded), with ties broken by earliest `created_at` rather than by `id`. When no such bill exists, `oldest_unpaid_bill_due_date` is null and the account is `CURRENT`. Otherwise the system computes the number of whole days past due as the floor of the difference between `current_utc` and `oldest_unpaid_bill_due_date` expressed in days. If that count is at least forty-five days, the account becomes `IN_ARREARS`; if it is greater than zero but fewer than forty-five days, the account becomes `DELINQUENT`; and if it is zero or negative, the account is `CURRENT`. The forty-five-day boundary is inclusive: an account exactly forty-five days past due is `IN_ARREARS`. This arrears evaluation runs in two situations — immediately after a payment waterfall, where it reads the post-allocation set of unpaid bills so that a clearing payment can return the account to `CURRENT` in a single step; and whenever the system clock is advanced, where the same unpaid set is re-aged against the later `current_utc`, so an account can cross into `IN_ARREARS` purely from the passage of time. Any account whose `financial_status` changes as a result of a clock advance has its `version` incremented.

### 2.9. Hierarchical Consistency and Cascade Semantics

Several operations mutate more than one resource at once, and every cascade is part of the contract. The account's `version` is the serialization point for the ledger: issuing a bill, voiding a bill, raising a disconnect notice, requesting a reconnect, completing or cancelling a service order, truing up or cancelling a budget plan, and a clock-driven financial-status change each increment `Account.version` by one and refresh the account's `updated_at`. Service-order completion advances the account's service dimension; cancelling a still-scheduled disconnect order reverts the account out of `DISCONNECT_PENDING`; a payment that clears arrears can cascade-cancel a scheduled disconnect order. These linked effects are spelled out in the workflow narratives of Section 3, and each one independently mutates the affected resource's `updated_at` and `version` where those fields exist.

### 2.10. Optimistic Concurrency Control on Ledger Writes

Two operations move money against the shared account balance using a snapshot the client read earlier, and both are guarded by optimistic concurrency control keyed on the account's `version`. Bill issuance requires the request body to carry `expected_account_version` holding the client's last observed `version` of the target bill's account. If that value does not match the account's current `version` — because some other writer has advanced the account since the client read it — issuance is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412. Because issuance debits the net-metering credit bank and increases the account balance, a stale issuance carrying an out-of-date account version would double-apply against a balance another issuance already moved, which this check prevents.

Budget true-up carries the same guard. Truing up a budget plan requires `expected_account_version` to match the current `version` of the plan's account; a mismatch is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412. A stale version here means a bill was issued (changing the plan's accumulated actual cost) after the client's read, so the catch-up would be computed against a superseded snapshot. These are the only two operations that take a version field; no other endpoint accepts or checks `expected_account_version`.

## 3. Business Logic & Workflows

### 3.1. Defining the Rate Structure

Everything the engine prices flows from a **Tariff**, the rate book a `BillingOperator` authors. A tariff is created with a unique `code` (no two tariffs may share a code), a human-readable `name`, a `fixed_charge_cents` flat monthly customer charge applied once per bill, and the parameters of the energy rate: `tier_breakpoints_kwh`, an ascending list of kWh breakpoints between inclining blocks, and `tier_rates_cents_per_kwh`, the per-kWh energy rate in cents for each block. N breakpoints define N+1 tiers, so the rate array must hold exactly one more element than the breakpoint array. The tariff also carries `tou_multipliers`, a map keyed by exactly the three time-of-use periods `ON_PEAK`, `MID_PEAK`, and `OFF_PEAK`, each mapping to a positive multiplier applied to the tier-priced energy in that period; a `demand_charge_cents_per_kw` charge in cents per kW of billed peak demand; and a `net_metering_credit_cents_per_kwh` credit in cents granted per kWh of net export. A tariff begins life in `DRAFT` status.

A tariff's shape is validated both at creation and at activation. The rate array must be exactly one longer than the breakpoint array; the breakpoints must be strictly ascending with each value greater than zero; the rates must be strictly ascending so that each successive block is priced higher than the last (this is what makes the blocks incline); and the three TOU multipliers must satisfy `ON_PEAK` at least `MID_PEAK` and `MID_PEAK` at least `OFF_PEAK`, with every multiplier greater than zero. A tariff whose shape violates any of these is rejected with `ERR_INVALID_TARIFF_SHAPE`. The `fixed_charge_cents`, `demand_charge_cents_per_kw`, and `net_metering_credit_cents_per_kwh` values must each be at least zero; a negative value among these is rejected with `ERR_VALIDATION_RANGE`.

Activating a tariff moves it `DRAFT → ACTIVE` and re-runs the same shape validation; only an `ACTIVE` tariff may price new bills or back a new account. Retiring a tariff moves it `ACTIVE → RETIRED`; accounts already priced under a retired tariff keep the snapshot they were billed against, but issuing a new bill under a retired tariff is rejected with `ERR_TARIFF_NOT_ACTIVE`. Activation requires the tariff to currently be in `DRAFT` and retirement requires it to currently be in `ACTIVE`; attempting either transition from any other state is rejected with `ERR_INVALID_STATE`. `RETIRED` is terminal.

### 3.2. Opening Accounts, Meters, and Importing AMI Reads

A `BillingOperator` opens an **Account** by supplying a `tariff_id` and a `holder_name`. The referenced tariff must be in `ACTIVE` status at assignment; assigning an account to a tariff that is not `ACTIVE` is rejected with `ERR_TARIFF_NOT_ACTIVE`. A new account starts with `service_status` of `ACTIVE`, `financial_status` of `CURRENT`, a `balance_cents` of 0, a `net_metering_credit_balance_cents` of 0, a null `oldest_unpaid_bill_due_date`, and a null `budget_plan_id`. Accounts may be listed and filtered by `tariff_id`, by `service_status`, and by `financial_status`.

Onto an account a `BillingOperator` registers one or more **Meters**, each created with an `account_id`, a `serial` that is unique across all meters, and an optional `meter_type` that is either `CONSUMPTION_ONLY` or `BIDIRECTIONAL`, defaulting to `BIDIRECTIONAL`. A meter's `meter_type` governs which read channels are expected, and a meter begins in `ACTIVE` status (the alternative lifecycle state being `REMOVED`). Meters are listed and filtered by `account_id` and by `status`.

AMI telemetry enters the system as **MeterRead** records imported by a `BillingOperator`, one per hourly interval. A read is posted with a `meter_id`, an `interval_start` and `interval_end` that bound the interval, an `import_kwh` quantity delivered grid-to-customer, and an optional `export_kwh` quantity exported customer-to-grid. Each interval must be exactly one hour long: `interval_end` must equal `interval_start` plus sixty minutes, and a read whose interval is not exactly sixty minutes is rejected with `ERR_INVALID_INTERVAL`. The same error rejects any read carrying a positive `export_kwh` on a meter whose `meter_type` is `CONSUMPTION_ONLY`, since a consumption-only meter cannot export. Both `import_kwh` and `export_kwh` must be at least zero; a negative value is rejected with `ERR_VALIDATION_RANGE`. A new read's interval must not duplicate or overlap an existing read for the same meter; an overlapping read is rejected with `ERR_READ_OVERLAP`.

On import, the system derives two read fields. It computes `tou_period` from the hour-of-day of `interval_start` in UTC under a fixed schedule: hours sixteen through twenty (that is, 16:00 up to but not including 21:00) are `ON_PEAK`; hours seven through fifteen and hours twenty-one through twenty-two (07:00 up to 16:00, and 21:00 up to 23:00) are `MID_PEAK`; and hours twenty-three through six (23:00 up to 07:00 the next morning) are `OFF_PEAK`. It also computes `avg_demand_kw` as the interval's `import_kwh` divided by one hour — numerically equal to `import_kwh`, since each interval spans exactly one hour. Meter reads are listed and filtered by `meter_id`.

### 3.3. Creating and Pricing a Bill

A **Bill** is born when a `BillingOperator` creates a draft for an account over a billing period, supplying the `account_id`, the `period_start` and `period_end` that bound the period, and the `due_date` by which payment is owed. The period must be non-empty — `period_end` must be strictly after `period_start` — and the half-open window `[period_start, period_end)` must not overlap any existing non-void bill for the same account; a zero-or-negative period or an overlapping period is rejected with `ERR_BILL_PERIOD_OVERLAP`. A freshly created bill is in `DRAFT` status and all its computed money fields — `total_import_kwh`, `total_export_kwh`, `billed_peak_demand_kw`, `energy_charge_cents`, `demand_charge_cents`, `net_metering_credit_applied_cents`, `assistance_applied_cents`, `total_due_cents`, `amount_paid_cents`, `actual_cost_cents`, and the `is_budget_billed` flag — sit at their zero or false defaults until the bill is issued.

Issuing a bill is the heart of the engine. A `BillingOperator` issues a `DRAFT` bill, which transitions it `DRAFT → ISSUED`, snapshots the account's current tariff onto the bill's `tariff_id`, and runs the full pricing calculation described below. Issuance requires the bill to be in `DRAFT` (otherwise `ERR_INVALID_STATE`), requires the account's tariff to be `ACTIVE` (otherwise `ERR_TARIFF_NOT_ACTIVE`), and requires `expected_account_version` to match the account's current `version` (otherwise `ERR_STALE_ACCOUNT_VERSION` at HTTP 412, as described in Section 2.10).

The pricing calculation runs over the **billed reads** — every meter read belonging to one of the account's meters whose `interval_start` falls within the half-open window `[period_start, period_end)`. It proceeds in a fixed sequence:

First, the engine aggregates. The bill's `total_import_kwh` is the sum of `import_kwh` over the billed reads, and `total_export_kwh` is the sum of `export_kwh` over them. The `billed_peak_demand_kw` is the maximum `avg_demand_kw` among only those billed reads whose `tou_period` is `ON_PEAK`; if there are no `ON_PEAK` reads in the period, `billed_peak_demand_kw` is zero.

Second, the engine prices the total imported energy through the inclining blocks. Walking the tiers from the lowest, it fills each block up to its breakpoint width — the first block spans from zero up to the first breakpoint, each subsequent block spans from the previous breakpoint to the next, and the final block extends without upper bound — placing as much of the remaining imported energy as fits into each block and pricing that block's energy at that block's per-kWh rate. The block-priced costs accumulate into a tiered energy subtotal in cents, and the walk stops once all imported energy has been allocated.

Third, the engine applies time-of-use weighting to that tiered subtotal. For each of the three periods, it computes that period's share of total imported energy as the sum of `import_kwh` over billed reads in that period divided by `total_import_kwh` (a share of zero when there is no imported energy at all), multiplies the tiered subtotal by that share and by the period's multiplier from `tou_multipliers`, and sums the three weighted contributions. The final `energy_charge_cents` is this TOU-weighted sum rounded half-up to whole cents exactly once, after the three contributions have been summed — not rounded per period.

Fourth, the engine computes the `demand_charge_cents` as `billed_peak_demand_kw` multiplied by the tariff's `demand_charge_cents_per_kw`, rounded half-up to whole cents independently.

Fifth, it forms the gross charge before credits as the tariff's `fixed_charge_cents` plus `energy_charge_cents` plus `demand_charge_cents`.

Sixth, it settles net-metering credit. The export credit earned this period is `total_export_kwh` multiplied by the tariff's `net_metering_credit_cents_per_kwh`, rounded half-up to whole cents. The credit pool available to this bill is the account's carried `net_metering_credit_balance_cents` plus that export credit. Credit may offset only the energy portion of the bill: the floor below which a bill may never fall is the `fixed_charge_cents` plus the `demand_charge_cents`, so the maximum creditable amount is the greater of zero and the gross charge minus that floor. The `net_metering_credit_applied_cents` is the smaller of the credit pool and that maximum creditable amount, and whatever remains of the pool after applying credit becomes the carryover that rolls forward — that is, the account's `net_metering_credit_balance_cents` is debited by `net_metering_credit_applied_cents` at issuance, leaving the unused remainder banked for next month.

Seventh, it applies assistance after net-metering credit. The pre-assistance amount is the gross charge minus `net_metering_credit_applied_cents`. If the account has assistance available, the `assistance_applied_cents` is the smaller of the grant's `remaining_cents` and that pre-assistance amount; with no grant it is zero.

Eighth, it finalizes. The `actual_cost_cents` — the cost that would be due absent any budget plan — is the greater of zero and the pre-assistance amount minus `assistance_applied_cents`. When the account has an `ACTIVE` budget plan at issuance, the bill is flagged `is_budget_billed` true and its `total_due_cents` is set to the plan's levelized installment rather than the real cost (the levelizing mechanics are in Section 3.7); otherwise `is_budget_billed` is false and `total_due_cents` equals `actual_cost_cents`.

Beyond running pricing, issuance commits the ledger effects: it debits the account's `net_metering_credit_balance_cents` by `net_metering_credit_applied_cents`, increases the account's `balance_cents` by `total_due_cents`, accumulates the budget-plan counters when the bill is budget-billed, and increments `Account.version` by one. The bill returns 200 OK on issuance.

### 3.4. Voiding a Bill and Reversing Its Ledger Effects

An issued bill that has not yet received any payment can be voided by a `BillingOperator`, transitioning it `ISSUED → VOID`. Voiding is permitted only when the bill is in `ISSUED` status with `amount_paid_cents` equal to zero; a void attempt against a bill in any other state, or one that already carries payment, is rejected with `ERR_INVALID_STATE`. A void unwinds every ledger effect the issuance applied: it decreases the account's `balance_cents` by the bill's `total_due_cents`, refunds `net_metering_credit_applied_cents` back into the account's `net_metering_credit_balance_cents`, and refunds `assistance_applied_cents` back into the source assistance grant's `remaining_cents` (un-exhausting the grant if it had been fully consumed). When the voided bill was budget-billed, the plan's accumulated counters are decremented by that bill's contribution. The void increments `Account.version` by one. `VOID` is terminal for a bill.

### 3.5. Payments, the Waterfall, and Reversals

A **Payment** is posted by either a `Customer` or a `BillingOperator` against an account, supplying the `account_id`, an `amount_cents`, and an optional `method` of `ACH`, `CARD`, or `CASH` (defaulting to `ACH`). The amount must be strictly greater than zero; a non-positive amount is rejected with `ERR_INVALID_PAYMENT`. A new payment is `POSTED` and records an ordered list of `allocations`, each entry pairing a `bill_id` with the `applied_cents` placed against that bill.

Allocation follows an oldest-due-first waterfall. The candidate bills are the account's bills in `ISSUED` or `PARTIALLY_PAID` status, ordered by `due_date` ascending and, where due dates tie, by `created_at` ascending (never by `id`). Walking that order, the system computes each bill's outstanding amount as its `total_due_cents` minus its current `amount_paid_cents`, applies the smaller of the remaining payment and that outstanding amount, records the allocation when the applied amount is positive, raises the bill's `amount_paid_cents` by the applied amount, and reduces the remaining payment accordingly — stopping when the payment is fully consumed. Independently of how allocations land, the account's `balance_cents` is reduced by the full payment amount, so an overpayment that exceeds every unpaid bill drives the balance negative into a credit.

Each bill the allocation touches recomputes its `status` from its resulting `amount_paid_cents`: a bill whose `amount_paid_cents` is at least its `total_due_cents` becomes `PAID`; a bill whose `amount_paid_cents` is greater than zero but below its `total_due_cents` becomes `PARTIALLY_PAID`. After allocation, the account re-ages its arrears (Section 2.8) against the post-allocation set of unpaid bills. When that recomputation leaves no `ISSUED` or `PARTIALLY_PAID` bill past due, the account's `financial_status` returns to `CURRENT` from either `DELINQUENT` or `IN_ARREARS`. If the payment clears arrears while a scheduled disconnect order is still outstanding — that is, while the account is `DISCONNECT_PENDING` — the system additionally returns the account's `service_status` to `ACTIVE` and cancels that scheduled disconnect order, moving it to `CANCELLED`. Each such financial- or service-status change increments `Account.version`.

A `BillingOperator` may reverse a payment, which must currently be `POSTED`; reversing a payment that is not `POSTED` (already `REVERSED`) is rejected with `ERR_INVALID_PAYMENT`. Reversal moves the payment `POSTED → REVERSED`, recomputes `amount_paid_cents` on each bill the reversed payment had touched from only the remaining posted allocations, and recomputes each affected bill's `status` from its new `amount_paid_cents`. Depending on the resulting `amount_paid_cents`, a bill may drop from `PAID` to `PARTIALLY_PAID`, from `PAID` to `ISSUED`, or from `PARTIALLY_PAID` to `ISSUED`. The account's `financial_status` is then recomputed in light of the now-larger unpaid balance.

### 3.6. Collections: Disconnect and Reconnect

When an account falls far enough behind, a `BillingOperator` raises a **disconnect notice**, the entry point of the nonpayment collections workflow. Raising a notice advances the account's `service_status` from `ACTIVE` to `DISCONNECT_PENDING` and creates a `SCHEDULED` **ServiceOrder** of `order_type` `DISCONNECT` with `reason` `NONPAY`, returning that service order with a 201. The notice is gated by three conditions evaluated in priority order. First, an account shielded by assistance may not be disconnected: if the account has an assistance grant that is `PLEDGED` or `APPLIED`, the notice is rejected with `ERR_ASSISTANCE_SHIELD`. Second, the notice requires the account to be `IN_ARREARS`; an account that is not `IN_ARREARS` is rejected with `ERR_NOT_IN_ARREARS`. Third, the service dimension must currently be `ACTIVE` for the transition to be defined; a notice against an account not in service-status `ACTIVE` is rejected with `ERR_INVALID_STATE`. Raising the notice increments `Account.version`.

A **ServiceOrder** references its `account_id`, carries an `order_type` of either `DISCONNECT` or `RECONNECT`, a `status` of `SCHEDULED`, `COMPLETED`, or `CANCELLED`, and a `reason` of `NONPAY`, `CUSTOMER_REQUEST`, or `RESTORE_AFTER_PAYMENT` (defaulting to `NONPAY`). Field crews are represented by the `FieldDispatcher` role, which completes a scheduled order. Completing a `DISCONNECT` order while the account is `DISCONNECT_PENDING` moves the order `SCHEDULED → COMPLETED` and advances the account's service dimension `DISCONNECT_PENDING → DISCONNECTED`. Completion requires the order to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and requires the order's `order_type` to match the account's pending service dimension — `DISCONNECT` against `DISCONNECT_PENDING`, `RECONNECT` against `RECONNECT_PENDING` — with a mismatch rejected by `ERR_ORDER_ACCOUNT_MISMATCH`. Each completion increments `Account.version`. Service orders are listed and filtered by `account_id`, by `status`, and by `order_type`.

Once a disconnected customer has settled enough to fall below the arrears threshold, a `BillingOperator` raises a **reconnect request**, which advances the account `DISCONNECTED → RECONNECT_PENDING` and creates a `SCHEDULED` `RECONNECT` ServiceOrder with `reason` `RESTORE_AFTER_PAYMENT`, returning it with a 201. A reconnect request requires the account's service dimension to be `DISCONNECTED` (otherwise `ERR_INVALID_STATE`) and requires `financial_status` to be either `CURRENT` or `DELINQUENT` — that is, no longer `IN_ARREARS`; a request while the account is still `IN_ARREARS` is rejected with `ERR_ARREARS_NOT_CLEARED`. The request increments `Account.version`. A `FieldDispatcher` then completes the `RECONNECT` order, moving it `SCHEDULED → COMPLETED` and returning the account's service dimension `RECONNECT_PENDING → ACTIVE`, again incrementing `Account.version`.

A scheduled service order may also be cancelled, by either a `BillingOperator` or a `FieldDispatcher`. Cancellation requires the order to be `SCHEDULED` (otherwise `ERR_INVALID_STATE`) and moves it `SCHEDULED → CANCELLED`. When the cancelled order is a `DISCONNECT` and the account is still `DISCONNECT_PENDING`, cancelling it reverts the account's service dimension back to `ACTIVE`. Cancellation increments `Account.version`. This same disconnect-cancel-and-revert is what the payment waterfall triggers automatically when a clearing payment lifts an account out of arrears while a disconnect order is still scheduled, as described in Section 3.5.

### 3.7. Budget Billing: Levelizing and True-Up

A customer who prefers a predictable monthly bill is enrolled by a `BillingOperator` in a **BudgetBillingPlan**, created with the `account_id` and a `levelized_amount_cents` — the fixed installment charged on each bill while the plan is `ACTIVE`. The levelized amount must be strictly greater than zero; a non-positive value is rejected with `ERR_VALIDATION_RANGE`. An account may hold at most one `ACTIVE` plan at a time; enrolling a second while one is already active is rejected with `ERR_BUDGET_PLAN_EXISTS`. Enrollment sets the plan `ACTIVE` and populates the account's `budget_plan_id` pointer.

While the plan is `ACTIVE`, each bill issued for the account is levelized: as Section 3.3 describes, the bill's `total_due_cents` is set to the plan's `levelized_amount_cents` regardless of that month's real cost, while the bill's `actual_cost_cents` still holds the true computed amount. Each such bill accumulates the plan's two running counters — `accumulated_actual_cents`, the running sum of the budget-billed bills' `actual_cost_cents`, and `accumulated_levelized_cents`, the running sum of the levelized installments charged — maintained in bill-issuance chronological order. These counters are what a void decrements when a budget-billed bill is reversed.

Settling the plan reconciles the smoothed installments against reality. A true-up, run by a `BillingOperator`, requires the plan to be `ACTIVE` (otherwise `ERR_INVALID_STATE`) and requires `expected_account_version` to match the account's current `version` (otherwise `ERR_STALE_ACCOUNT_VERSION` at HTTP 412, per Section 2.10). True-up computes the plan's `true_up_balance_cents` as `accumulated_actual_cents` minus `accumulated_levelized_cents` — a positive figure means the customer underpaid through the levelized stream and owes a catch-up, while a negative figure means they overpaid and receive a credit — and adjusts the account's `balance_cents` by that delta. The reconciliation is exact integer cents with no rounding, since both counters are already whole cents. True-up then moves the plan `ACTIVE → TRUED_UP`, clears the account's `budget_plan_id`, and increments `Account.version`. Cancelling a plan settles it the same way: it requires the plan to be `ACTIVE` (otherwise `ERR_INVALID_STATE`), computes the same `true_up_balance_cents` and adjusts `balance_cents` by it, moves the plan `ACTIVE → CANCELLED`, clears `budget_plan_id`, and increments `Account.version`. Both `TRUED_UP` and `CANCELLED` are terminal. Budget plans are listed and filtered by `account_id` and by `status`.

### 3.8. Assistance Grants and the Disconnect Shield

An **AssistanceGrant** is pledged to an account by an `AssistanceCaseworker`, created with the `account_id`, a `pledged_cents` total, and an optional `program` of `LIHEAP` or `EMERGENCY_CRISIS` (defaulting to `LIHEAP`). The pledged amount must be strictly greater than zero; a non-positive value is rejected with `ERR_VALIDATION_RANGE`. A new grant is `PLEDGED` and its `remaining_cents` starts equal to `pledged_cents`, drawing down as bills consume it through the assistance step of pricing in Section 3.3.

The grant's lifecycle tracks consumption. When a bill first consumes part of a grant — leaving its `remaining_cents` above zero but below `pledged_cents` — the grant moves `PLEDGED → APPLIED`. When a bill consumes the last of the remaining balance so that `remaining_cents` reaches zero, the grant moves to `EXHAUSTED`: from `APPLIED` if it had been partially consumed before, or directly `PLEDGED → EXHAUSTED` when a single bill consumes the entire grant in one step. Should a bill that consumed assistance later be voided, the refund flows back into the grant's `remaining_cents`, and an `EXHAUSTED` grant returns to `APPLIED` (or to `PLEDGED` when the refund restores `remaining_cents` all the way to `pledged_cents`). An `AssistanceCaseworker` may cancel a grant only while it is still `PLEDGED` with nothing yet consumed, moving it `PLEDGED → CANCELLED`; both `EXHAUSTED` and `CANCELLED` are terminal. Assistance grants are listed and filtered by `account_id` and by `status`.

Beyond reducing bills, an active grant shields the account from disconnection: as Section 3.6 notes, a `PLEDGED` or `APPLIED` grant blocks a disconnect notice with `ERR_ASSISTANCE_SHIELD`, evaluated ahead of the arrears and state checks on that operation.

### 3.9. Advancing the Clock and Re-aging Accounts

The simulated clock is the system's notion of "now." A `BillingOperator` advances it by setting `current_utc`, which both records the new time on the singleton clock and triggers a system-wide arrears recompute: every account's `financial_status` is re-evaluated against the new `current_utc` per the arrears-age rules of Section 2.8. Through this recompute an account can move `CURRENT → DELINQUENT`, `DELINQUENT → IN_ARREARS`, or — purely from time passing without payment — straight across these standings as its oldest unpaid bill ages past the forty-five-day boundary. Any account whose `financial_status` changes during the recompute has its `version` incremented. The current clock value is readable by every role.

### 3.10. Validation Ordering Across Operations

When several checks guard a single operation, they are evaluated in a fixed priority so that the same failing request always yields the same error. Authentication comes first: a missing or unknown `X-User-Role` or missing `X-User-ID` yields `ERR_UNAUTHENTICATED` before anything else. Authorization comes next: a known role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Then existence is checked — every path-referenced resource left-to-right, yielding `ERR_NOT_FOUND` for the first missing one, followed by request-body foreign keys yielding `ERR_FK_NOT_FOUND`. Structural validation of the request body follows: a missing required field, a wrong type, or an invalid enum member yields `ERR_INVALID_REQUEST`. Domain-shape and range checks then apply where relevant — tariff shape (`ERR_INVALID_TARIFF_SHAPE`), interval shape (`ERR_INVALID_INTERVAL`), and numeric range (`ERR_VALIDATION_RANGE`). Referential business rules such as the active-tariff requirement (`ERR_TARIFF_NOT_ACTIVE`) precede state-machine checks. State validity (`ERR_INVALID_STATE`) confirms the target is in a state from which the requested transition is defined, and applies to every action endpoint — issue, void, complete, cancel, true-up, disconnect-notice, reconnect-request, activate, retire, and reverse. The remaining domain guards — order/account match, the assistance shield, the arrears gate on disconnect and on reconnect, the single-active-plan rule, bill-period and read-interval overlap, the payment-validity rule, and finally the optimistic-concurrency version check — each fire for their own operations as described in their respective workflows above. For the disconnect notice specifically, the assistance shield (`ERR_ASSISTANCE_SHIELD`) is evaluated before the arrears requirement (`ERR_NOT_IN_ARREARS`), which is evaluated before the service-state check (`ERR_INVALID_STATE`), so a shielded account always surfaces the shield rather than masking it behind a later check.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code; this includes creating tariffs, accounts, meters, meter reads, bills, payments, budget plans, and assistance grants, as well as raising a disconnect notice or a reconnect request (each of which creates a new service order). Operations that modify an existing resource — activating, retiring, issuing, voiding, completing, cancelling, truing-up, reversing, and setting the clock — return a `200 OK` status code. List and read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tariffs` | Create a DRAFT tariff with tier/TOU/demand/net-metering structure | BillingOperator |
| POST | `/tariffs/{id}/activate` | Activate a DRAFT tariff so accounts may be priced under it | BillingOperator |
| POST | `/tariffs/{id}/retire` | Retire an ACTIVE tariff; new bill issuance under it is rejected | BillingOperator |
| GET | `/tariffs/{id}` | Read one tariff | BillingOperator, Customer, AssistanceCaseworker, FieldDispatcher |
| GET | `/tariffs` | List tariffs (paginated, filterable by status) | BillingOperator, Customer, AssistanceCaseworker, FieldDispatcher |
| POST | `/accounts` | Open an account against an ACTIVE tariff | BillingOperator |
| GET | `/accounts/{id}` | Read one account with computed balances and both status dimensions | BillingOperator, Customer, AssistanceCaseworker, FieldDispatcher |
| GET | `/accounts` | List accounts (filterable by tariff and status dimensions) | BillingOperator, AssistanceCaseworker |
| POST | `/accounts/{id}/disconnect-notice` | Raise a nonpay disconnect; creates a SCHEDULED DISCONNECT order | BillingOperator |
| POST | `/accounts/{id}/reconnect-request` | Request reconnection; creates a SCHEDULED RECONNECT order | BillingOperator |
| POST | `/meters` | Register a meter on an account | BillingOperator |
| GET | `/meters/{id}` | Read one meter | BillingOperator, Customer, FieldDispatcher |
| GET | `/meters` | List meters, filterable by account_id and status | BillingOperator, Customer, FieldDispatcher |
| POST | `/meter-reads` | Import one AMI interval read; computes tou_period and avg_demand_kw | BillingOperator |
| GET | `/meter-reads/{id}` | Read one AMI interval read | BillingOperator, Customer |
| GET | `/meter-reads` | List meter reads, filterable by meter_id | BillingOperator, Customer |
| POST | `/bills` | Create a DRAFT bill for an account over a billing period | BillingOperator |
| POST | `/bills/{id}/issue` | Price and issue a bill; runs pricing; OCC on account | BillingOperator |
| POST | `/bills/{id}/void` | Void an ISSUED, unpaid bill; reverses all ledger effects | BillingOperator |
| GET | `/bills/{id}` | Read one bill with all computed charge lines | BillingOperator, Customer, AssistanceCaseworker |
| GET | `/bills` | List bills, filterable by account_id, tariff_id, and status | BillingOperator, Customer, AssistanceCaseworker |
| POST | `/payments` | Post a payment; waterfall-allocates across oldest-due-first bills | Customer, BillingOperator |
| POST | `/payments/{id}/reverse` | Reverse a POSTED payment; un-applies allocations, recomputes bills | BillingOperator |
| GET | `/payments/{id}` | Read one payment with its allocations | BillingOperator, Customer |
| GET | `/payments` | List payments, filterable by account_id and status | BillingOperator, Customer |
| GET | `/service-orders/{id}` | Read one service order | BillingOperator, FieldDispatcher |
| GET | `/service-orders` | List service orders, filterable by account_id, status, order_type | BillingOperator, FieldDispatcher |
| POST | `/service-orders/{id}/complete` | Field-complete a service order; advances service_status | FieldDispatcher |
| POST | `/service-orders/{id}/cancel` | Cancel a SCHEDULED order; may revert pending service_status | BillingOperator, FieldDispatcher |
| POST | `/budget-plans` | Enroll an account in levelized budget billing | BillingOperator |
| POST | `/budget-plans/{id}/true-up` | Settle a budget plan: reconcile actual vs levelized; OCC on account | BillingOperator |
| POST | `/budget-plans/{id}/cancel` | Cancel a budget plan; settles the accrued true-up | BillingOperator |
| GET | `/budget-plans/{id}` | Read one budget plan with accumulated counters | BillingOperator, Customer |
| GET | `/budget-plans` | List budget plans, filterable by account_id and status | BillingOperator, Customer |
| POST | `/assistance-grants` | Pledge LIHEAP/crisis assistance to an account | AssistanceCaseworker |
| POST | `/assistance-grants/{id}/cancel` | Cancel an unused (PLEDGED) assistance grant | AssistanceCaseworker |
| GET | `/assistance-grants/{id}` | Read one assistance grant | BillingOperator, AssistanceCaseworker, Customer |
| GET | `/assistance-grants` | List assistance grants, filterable by account_id and status | BillingOperator, AssistanceCaseworker, Customer |
| POST | `/_clock/set_current_utc` | Set the simulated clock; triggers system-wide arrears recompute | BillingOperator |
| GET | `/_clock` | Read the current simulated clock | BillingOperator, Customer, AssistanceCaseworker, FieldDispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_TARIFF_SHAPE` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_TARIFF_NOT_ACTIVE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ORDER_ACCOUNT_MISMATCH` | 409 |
| `ERR_ASSISTANCE_SHIELD` | 409 |
| `ERR_NOT_IN_ARREARS` | 409 |
| `ERR_ARREARS_NOT_CLEARED` | 409 |
| `ERR_BUDGET_PLAN_EXISTS` | 409 |
| `ERR_BILL_PERIOD_OVERLAP` | 409 |
| `ERR_READ_OVERLAP` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_INVALID_PAYMENT` | 409 |
| `ERR_VALIDATION_RANGE` | 422 |

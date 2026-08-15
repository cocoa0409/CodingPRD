# Relocation Benefits API — Product Requirements Document

## 1. Introduction

Corporate mobility programs sit at the intersection of employee experience and financial control. When a company relocates an employee, it commits to a bundle of benefits — moving household goods, temporary housing, travel, incidental reimbursements, and sometimes protection against a loss on the sale of the employee's home — each governed by a policy tier derived from the employee's level, the scope of the move, and whether the employee owns or rents a home. Administering that bundle by hand invites inconsistent spending, missed tax obligations on taxable reimbursements, and awkward clawback conversations when an employee departs shortly after an expensive move.

The Relocation Benefits API is the administrative backbone for such a program. It resolves each new relocation case to its governing policy tier, orchestrates household-goods vendors from survey through estimate approval to final invoice payment, books temporary housing and travel against tier caps, adjudicates expense claims with a tax gross-up computed at payment time, administers loss-on-sale assistance, and governs exception requests that raise individual caps through an approval-and-appeal chain. Every financial event posts to a per-case cost ledger that separates committed funds from disbursed funds and released commitments, and every early departure triggers a prorated repayment agreement with an installment schedule, delinquency detection, and cure mechanics. Five cooperating roles share the workload, and a server-side logical clock — never the wall clock — drives every timestamp, rolling window, and delinquency decision so that program behavior is deterministic and auditable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, structural contracts, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that arrives without both headers, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401).

The system recognizes five roles. An `Employee` is the relocating employee, who submits expense claims, books services, rates movers, signs repayment agreements, and files exceptions for their own cases. A `MobilityCoordinator` is the corporate mobility program administrator, managing employees, policy tiers, vendors, cases, bookings, surveys, estimates, and home sales. A `Vendor` is a household-goods vendor user who submits estimates, marks deliveries, and submits invoices on their own assignments. A `FinanceSpecialist` is a finance and payroll operator who approves, rejects, and pays claims, settles vendor invoices and home-sale benefits, and administers repayment agreements. A `ProgramManager` is a senior mobility program manager who decides exception requests.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting Employee; ownership checks on any resource reached through a relocation case compare the case's `employee_id` to `X-User-ID`. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting Vendor; ownership checks on a move assignment compare the assignment's `vendor_id` to `X-User-ID`. When `X-User-Role` is `MobilityCoordinator`, `FinanceSpecialist`, or `ProgramManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

Access to every operation is restricted by role as enumerated in §4. An attempt to act outside one's designated role — including failing an entity-backed ownership check — is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system — employees, policy tiers, vendors, relocation cases, move assignments, service bookings, expense claims, home-sale transactions, repayment agreements, and exception requests — carries the same set of system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven automatically by cascades or by the system itself.

A child mutation that moves money on the parent's cost ledger — committing, paying, or releasing funds — is also a mutation of the parent case: it refreshes the case's `updated_at` and increments the case `version` by one, in addition to incrementing the child's own `version`.

Fields that record an event or a later-supplied value are null until the corresponding action populates them: `authorized_at`, `termination_date`, `survey_at`, `estimated_cents`, `final_invoice_cents`, `rating`, `rated_at`, `reject_reason`, `paid_at`, `sale_price_cents`, `loss_basis_used`, `gross_loss_cents`, `capped_benefit_cents`, `signed_at`, `next_due_date`, and `decision_note`.

### 2.5. The Logical Clock

A single server-side logical clock governs every timestamp the system stamps and every time window it evaluates. At startup, before any call, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. A `MobilityCoordinator` may set the clock through `POST /_clock/set_current_utc`, supplying the target instant as `to_iso8601` in ISO 8601 UTC. Case authorization timestamps, employment termination dates, claim payment times, rating timestamps, agreement signature dates, the trailing twelve-month vendor rating window, and repayment delinquency evaluation all read this clock and no other.

### 2.6. The Case Cost Ledger

Every relocation case carries a three-column cost ledger maintained entirely by the system. `total_committed_cents` tracks funds promised but not yet disbursed: the `estimated_cents` of the case's move assignments in `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED`, plus the `total_cents` of its service bookings in `CONFIRMED`, plus the `amount_cents` of its expense claims in `APPROVED`. `total_paid_cents` tracks funds actually disbursed: the `final_invoice_cents` of `PAID` assignments, the `total_cents` of `COMPLETED` bookings, the `total_payment_cents` of `PAID` claims, and the `capped_benefit_cents` of `SETTLED` home-sale transactions. `total_released_cents` accumulates commitments later withdrawn: amounts freed when a `CONFIRMED` booking is cancelled or when an assignment in `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED` is cancelled. All three totals initialize to zero when the case is created and are integer cents.

The ledger obeys a strict conservation pattern. Approving or confirming moves an amount into the committed column; completing, paying, or settling moves that amount out of committed and the final amount into paid; cancelling moves the held amount out of committed and into released. Across a confirm-then-cancel pair on the same booking, the paid column never changes, the committed column rises and then falls by the same amount, and the released column gains that amount only at the cancellation. Cancelled children contribute to the ledger exclusively through released amounts.

### 2.7. Policy Tiers, Effective Caps, and Exception Increases

Each policy tier fixes a budgetary cap per benefit component: `hhg_cap_cents` for household goods, `temp_housing_cap_cents` for temporary housing, `travel_cap_cents` for travel, `misc_cap_cents` for miscellaneous expense claims, and `loss_on_sale_cap_cents` for the loss-on-sale benefit. On any given case, the **effective cap** for a component is the policy cap plus the sum of `requested_cap_increase_cents` over that case's `APPROVED` exception requests naming that component. The **remaining headroom** is the effective cap minus the amounts the case is already holding against that component: approved-but-unpaid vendor estimates hold household-goods funds, confirmed-but-uncompleted bookings hold housing or travel funds by `kind`, and approved-but-unpaid claims hold miscellaneous funds.

A creation or approval that would push a component past its remaining headroom is rejected with `ERR_CAP_EXCEEDED` (HTTP 409). This guard fires at four points: booking creation, claim submission, claim approval, and estimate approval. Temporary housing additionally enforces a stay-length ceiling from the policy's `temp_housing_max_nights`: a booking whose computed stay exceeds the ceiling is rejected with `ERR_NIGHTS_LIMIT_EXCEEDED` (HTTP 409), while a stay of exactly the ceiling length is permitted. The loss-on-sale cap is not held incrementally; it is evaluated once, at the moment the sale is recorded, directly against the computed benefit.

### 2.8. Monetary Precision, Rounding, and Calendar Arithmetic

All monetary quantities are integer cents. The cost ledger, the loss-on-sale benefit, and temporary-housing charges involve only integer arithmetic and require no rounding. Where division occurs, the rounding rule is pinned: the tax gross-up rounds each bracket portion half up to a whole cent before the portions are summed; the prorated repayment total rounds half up to a whole cent; regular repayment installments are rounded down to a whole cent with the final installment absorbing the remainder; vendor average ratings are rounded half up to exactly two decimal places. Monetary values are represented in API responses as numbers, and rating averages carry two decimal places.

One calendar rule recurs across the product. The number of whole calendar months between an earlier date and a later date is twelve times the difference in calendar years plus the difference in calendar months, reduced by one when the later date's day-of-month is earlier than the earlier date's day-of-month. This counting rule drives both the proration of repayment obligations at early departure and the delinquency threshold for installment payments.

### 2.9. Optimistic Concurrency Control

Three write operations mutate the case ledger against budgetary caps and therefore guard against stale views of the case: `POST /expense-claims/{id}/approve`, `POST /move-assignments/{id}/approve-estimate`, and `POST /exception-requests/{id}/approve`. Each of these requests must carry `expected_case_version` in its body, holding the `version` of the parent relocation case the client last observed. If the supplied value does not match the case's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated — the client was necessarily reasoning over an outdated view of the case's remaining headroom. No other endpoint accepts a version field.

### 2.10. Validation Order and Nested Resource Resolution

Every request passes through a fixed, ordered validation cascade, and the first failing check determines the response — later checks are not evaluated. The order is:

1. **Authentication**: the `X-User-ID` and `X-User-Role` headers are present and the role is one of the five declared roles (`ERR_UNAUTHENTICATED`).
2. **Endpoint role authorization**: the acting role is listed for the endpoint (`ERR_FORBIDDEN`).
3. **Request shape**: required fields are present, enum values are in range, a rating is an integer from 1 to 5, monetary amounts are positive integers, and claim line items are non-empty (`ERR_INVALID_REQUEST`, HTTP 400).
4. **Existence**: path identifiers and body foreign keys such as `employee_id`, `case_id`, and `vendor_id` resolve to existing resources, validated left to right (`ERR_NOT_FOUND`, HTTP 404). For a nested path — a collection scoped under a case — the case identifier in the path is validated before anything belonging to the child collection.
5. **Ownership**: an `Employee` caller may act only on resources whose case's `employee_id` equals their `X-User-ID`, and a `Vendor` caller only on assignments whose `vendor_id` equals their `X-User-ID` (`ERR_FORBIDDEN`).
6. **State validity**: the target resource is in a legal source state for the requested transition (`ERR_INVALID_STATE`, HTTP 409); a transition attempted from a terminal state is rejected distinctly with `ERR_ALREADY_TERMINAL` (HTTP 409). Terminal states are `CLOSED`, `CLOSED_EARLY`, and `CANCELLED` for cases; `PAID` and `CANCELLED` for assignments; `COMPLETED` and `CANCELLED` for bookings; `PAID` for claims; `SETTLED` for home-sale transactions; `SETTLED` for repayment agreements as far as client-driven actions are concerned; and `APPROVED` for exception requests, with a `REJECTED` exception request admitting only the appeal transition.
7. **Optimistic concurrency**: on the three guarded writes of §2.9, `expected_case_version` must match the case's current `version` (`ERR_STALE_VERSION`).
8. **Referential compatibility**: the case is `IN_PROGRESS` for child creation and child actions (`ERR_CASE_NOT_OPEN`); the vendor is `ACTIVE` for assignment creation and survey scheduling (`ERR_VENDOR_SUSPENDED`); the employee is `ACTIVE` for case creation and authorization (`ERR_EMPLOYEE_NOT_ACTIVE`) and `TERMINATED` for early case termination (`ERR_EMPLOYEE_NOT_TERMINATED`); a governing policy resolves at case creation (`ERR_POLICY_NOT_FOUND`, HTTP 422); and the policy permits home-sale assistance when a home-sale program is opened (`ERR_HOME_SALE_NOT_ELIGIBLE`).
9. **Temporal rules**: a supplied end date falls after the start date (`ERR_INVALID_DATES`, HTTP 422); a temporary-housing stay does not overlap another live housing booking on the same case (`ERR_HOUSING_OVERLAP`); and a vendor's surveys respect the two-hour buffer (`ERR_SURVEY_CONFLICT`).
10. **Uniqueness and count limits**: one policy tier per tier key, one home-sale transaction per case, and one repayment agreement per case (`ERR_DUPLICATE_RESOURCE`); at most one appeal per exception request (`ERR_APPEAL_LIMIT_REACHED`); and a repayment payment no larger than the outstanding balance (`ERR_PAYMENT_EXCEEDS_BALANCE`, HTTP 422).
11. **Fiscal caps**: component headroom checks (`ERR_CAP_EXCEEDED`) and the temporary-housing stay ceiling (`ERR_NIGHTS_LIMIT_EXCEEDED`).

Because of this ordering, an unauthenticated request fails before its payload is examined, a wrong-role call fails before existence is probed, and a stale-version rejection on a guarded write surfaces before any cap arithmetic runs.

## 3. Business Logic & Workflows

### 3.1. Enrolling Employees and Defining Policy Tiers

A `MobilityCoordinator` enrolls each relocating employee with a `full_name`, a `job_level` of `ASSOCIATE`, `MANAGER`, `DIRECTOR`, or `EXECUTIVE`, and a `home_ownership` of `HOMEOWNER` or `RENTER`. New employees begin with `employment_status` set to `ACTIVE`. When employment ends, the coordinator terminates the record: `employment_status` flips to `TERMINATED`, `termination_date` is stamped from the logical clock, and the employee's `version` increments. Termination is a one-way street, and it is the trigger for the early-departure machinery of §3.8.

Policy tiers are the financial backbone of the program, and the coordinator authors them one at a time. A tier is keyed by the triple of `job_level`, `move_scope` (`DOMESTIC` or `INTERNATIONAL`), and `home_ownership`; the triple is unique, so an attempt to create a second tier with an existing key is rejected with `ERR_DUPLICATE_RESOURCE`. Beyond the caps enumerated in §2.7, a tier carries `temp_housing_max_nights` bounding any single housing stay, and `home_sale_eligible`, which gates whether cases under the tier may open the home-sale program at all — tiers that deny the program conventionally set `loss_on_sale_cap_cents` to zero. The tier's `repayment_window_months` plays a double role: it is the number of post-move service months the employee owes the company, and it becomes the installment count if a repayment agreement is ever created. Tax handling is selected per tier through `gross_up_method`: `FLAT_SUPPLEMENTAL` applies the single `flat_gross_up_rate` to every taxable claim, while `MARGINAL_AGGREGATE` brackets each claim against the case's taxable payment history using `marginal_bracket_threshold_cents`, `marginal_rate_low`, and `marginal_rate_high`. Finally, `loss_basis` — `APPRAISED` or `PURCHASE_PRICE` — selects how a loss on the employee's home sale is measured.

### 3.2. Opening the Relocation Case

A relocation begins when a `MobilityCoordinator` opens a case with the relocating `employee_id`, the `move_scope`, the `origin_city`, the `destination_city`, and the `expected_move_date`. Policy resolution is automatic at creation: the system searches all policy tiers for the one whose `job_level` matches the employee's level, whose `move_scope` matches the requested scope, and whose `home_ownership` matches the employee's ownership status. When no tier matches, creation is rejected with `ERR_POLICY_NOT_FOUND` (HTTP 422). Because the tier key is unique, at most one tier can match; should the data ever admit several, the tier created earliest — by `created_at` ascending — governs, a determinism fallback rather than an expected path. The resolved tier's `id` is stored on the case as `policy_id`, the case enters `DRAFT`, and its three ledger totals initialize to zero.

Only an `ACTIVE` employee may be put into motion: case creation, and later the authorization step, are both rejected with `ERR_EMPLOYEE_NOT_ACTIVE` when the employee has already been terminated. Authorization by a coordinator moves the case `DRAFT` → `AUTHORIZED` and stamps `authorized_at` from the logical clock — the anchor from which the required service window is later measured. Starting the move advances the case `AUTHORIZED` → `IN_PROGRESS`. Only an `IN_PROGRESS` case accepts child work — vendor assignments, bookings, claims, the home-sale program, and exception requests are all created against open cases, and child actions generally require the case to remain `IN_PROGRESS`; violations surface as `ERR_CASE_NOT_OPEN`. A case still in `AUTHORIZED` may also be cancelled outright, and because no children can exist before work starts, that cancellation touches nothing beyond the case itself. The complete case state enumeration is `DRAFT`, `AUTHORIZED`, `IN_PROGRESS`, `CLOSED`, `CLOSED_EARLY`, and `CANCELLED`, the last three being terminal. The case collection is listed with optional `employee_id`, `policy_id`, and `status` filters alongside the standard pagination parameters.

### 3.3. Household Goods: Vendors, Surveys, Estimates, and Payment

Household-goods vendors are registered by a `MobilityCoordinator` with a `name` and the list of `service_regions` they cover; new vendors begin `ACTIVE`. Suspending a vendor flips its `status` to `SUSPENDED`, which blocks two things — creating new assignments for that vendor and scheduling new surveys — both rejected with `ERR_VENDOR_SUSPENDED`. In-flight assignments of a suspended vendor are unaffected and may run to completion.

Assigning a vendor to a case takes the `case_id` and `vendor_id`; the case must be `IN_PROGRESS` and the vendor `ACTIVE`. The new assignment begins `REQUESTED`. Survey scheduling by a coordinator advances the assignment `REQUESTED` → `SURVEY_SCHEDULED` and records the proposed instant in `survey_at`. The case must still be `IN_PROGRESS` and the vendor still `ACTIVE`, and the vendor must not already hold another assignment in `SURVEY_SCHEDULED` whose survey time falls less than two hours before or after the requested one — a conflict is rejected with `ERR_SURVEY_CONFLICT`, while surveys exactly two hours apart are permitted.

From there the vendor itself drives the commercial cycle. The owning vendor — the caller whose `X-User-ID` equals the assignment's `vendor_id` — submits `estimated_cents`, moving the assignment `SURVEY_SCHEDULED` → `ESTIMATE_SUBMITTED`. Estimate approval by a coordinator is a guarded write: the request must carry `expected_case_version` matching the case's current `version`, with a stale value rejected as `ERR_STALE_VERSION`; per the global evaluation order that staleness check fires before the case-open check (`ERR_CASE_NOT_OPEN`) and before the fiscal check, which requires the estimate to fit within the case's remaining household-goods headroom (`ERR_CAP_EXCEEDED` when it does not). Approval commits `estimated_cents` into the case's committed column and increments both the assignment's and the case's `version`. A coordinator may instead reject the estimate, returning the assignment `ESTIMATE_SUBMITTED` → `REQUESTED` and clearing both `survey_at` and `estimated_cents` — the assignment must then be scheduled and estimated anew.

Once the estimate stands approved, the owning vendor marks the goods delivered (`ESTIMATE_APPROVED` → `DELIVERED`) and later submits the final invoice (`DELIVERED` → `INVOICED`), recording `final_invoice_cents`. A `FinanceSpecialist` closes the loop by marking the assignment paid (`INVOICED` → `PAID`): the committed estimate leaves `total_committed_cents`, the invoiced amount enters `total_paid_cents`, the vendor's `completed_moves` grows by one, and both resources' versions increment. The full assignment state enumeration is `REQUESTED`, `SURVEY_SCHEDULED`, `ESTIMATE_SUBMITTED`, `ESTIMATE_APPROVED`, `DELIVERED`, `INVOICED`, `PAID`, and `CANCELLED`, with `PAID` and `CANCELLED` terminal.

Employee satisfaction closes the loop on vendor quality. Once an assignment is `PAID`, the relocating employee may record a `rating` — an integer from 1 to 5 — exactly once; a rating outside that range is rejected with `ERR_INVALID_REQUEST`, while rating an assignment that is not yet paid or already rated is rejected with `ERR_INVALID_STATE`. The rating's `rated_at` is stamped from the logical clock, and the assignment's `version` increments. Vendor performance aggregates derive from these ratings and are recomputed whenever a rating lands and whenever a vendor is read: `rating_sum` and `rating_count` cover all of the vendor's rated assignments; `avg_rating_lifetime` is that sum divided by that count, rounded half up to two decimal places, and is null while the vendor has no ratings; `avg_rating_rolling_12m` applies the same quotient restricted to assignments whose `rated_at` falls within the twelve months preceding the logical clock, the window boundary inclusive, and is null when nothing was rated inside the window. Because old ratings age out of the rolling window, identical rating histories can yield different rolling averages as time advances. The assignment collection is listed with optional `case_id`, `vendor_id`, and `status` filters.

### 3.4. Temporary Housing and Travel Bookings

Temporary housing and travel are booked against an `IN_PROGRESS` case by the relocating employee or by a coordinator. The booking carries `case_id`, a `kind` of `TEMP_HOUSING` or `TRAVEL`, a `start_date`, an `amount_cents`, and — for housing — an `end_date`. Semantics split by kind: for `TEMP_HOUSING`, `amount_cents` is the nightly rate and `end_date` is required; for `TRAVEL`, `amount_cents` is the total ticket cost and an omitted `end_date` defaults to the `start_date`. A supplied end date that does not fall after the start date is rejected with `ERR_INVALID_DATES` (HTTP 422).

Two quantities are derived at creation. A housing stay is treated as a half-open interval — the check-in day counts, the check-out day does not — and `nights` is the count of whole days between the two dates; a stay shorter than one night is rejected with `ERR_INVALID_DATES`. The booking's `total_cents` is `nights` multiplied by the nightly rate for housing, and simply `amount_cents` for travel, which always carries zero `nights`. The stay may not exceed the policy's `temp_housing_max_nights`: a stay of exactly that many nights is allowed, while one night more is rejected with `ERR_NIGHTS_LIMIT_EXCEEDED`. Nor may the half-open stay interval overlap any other non-`CANCELLED` housing booking of the same case — intervals that merely touch at a boundary are permitted, but a true overlap is rejected with `ERR_HOUSING_OVERLAP`. Finally, creation checks the booking's `total_cents` against the remaining headroom of its component — housing against the `TEMP_HOUSING` cap anchored on `temp_housing_cap_cents`, travel against the `TRAVEL` cap anchored on `travel_cap_cents` — and rejects overflow with `ERR_CAP_EXCEEDED`.

Bookings are born `HELD` and hold no funds in that state. Confirmation by a coordinator (`HELD` → `CONFIRMED`) requires the case still `IN_PROGRESS` and commits `total_cents` to the case ledger's committed column, incrementing both the case and booking versions. Either the owning employee or a coordinator may cancel a booking: cancelling a `HELD` booking touches only the booking's own `version`, while cancelling a `CONFIRMED` one releases its commitment — `total_committed_cents` falls and `total_released_cents` rises by the same `total_cents`, with both versions incrementing. Completion (`CONFIRMED` → `COMPLETED`, by a coordinator) converts the commitment into spend: the committed column falls by `total_cents` and `total_paid_cents` rises by the same amount. The booking states are `HELD`, `CONFIRMED`, `COMPLETED`, and `CANCELLED`, the last two terminal. A case's bookings are listed with optional `kind` and `status` filters.

### 3.5. Expense Claims and the Tax Gross-Up

Employees submit expense claims against their own `IN_PROGRESS` case, providing the `case_id`, a `category` of `MEALS`, `LODGING`, `TRANSPORT`, or `MISC`, a `payment_method` of `REIMBURSEMENT` or `DIRECT_BILL`, and itemized `lines`, each line carrying a `description` and an `amount_cents`. The lines array must be non-empty and every line amount a positive integer, or submission fails with `ERR_INVALID_REQUEST`. The claim's `amount_cents` is computed as the sum of its line amounts, and its `taxable` flag is derived rather than supplied: a claim is taxable exactly when its payment method is `REIMBURSEMENT`. Submission also checks the claim amount against the case's remaining miscellaneous headroom — the effective `MISC` cap anchored on the policy's `misc_cap_cents` — and rejects overflow with `ERR_CAP_EXCEEDED`. New claims enter `SUBMITTED`.

A `FinanceSpecialist` approves a claim (`SUBMITTED` → `APPROVED`) through a guarded write carrying `expected_case_version`. Following the global evaluation order, a stale version is rejected with `ERR_STALE_VERSION` first, then the case-open check (`ERR_CASE_NOT_OPEN`), then the cap arithmetic, which re-verifies the amount against the remaining miscellaneous headroom and rejects overflow with `ERR_CAP_EXCEEDED`. Approval commits `amount_cents` into the case's committed column and increments both the claim's and the case's `version`. Rejection (`SUBMITTED` → `REJECTED`) records the supplied `reject_reason`. The owning employee may resubmit a rejected claim (`REJECTED` → `SUBMITTED`); when replacement `lines` are supplied they supplant the old ones and `amount_cents` is recomputed, and in every resubmission `reject_reason` is cleared. A claim may bounce between submission and rejection any number of times.

Payment (`APPROVED` → `PAID`, by a `FinanceSpecialist`) is where the tax gross-up runs, and only taxable claims earn one — a `DIRECT_BILL` claim's `gross_up_cents` is zero. The gross-up principle is that tax is levied on the gross payment, so each grossed-up portion equals its net portion multiplied by the applicable rate and divided by one minus that rate. Under a `FLAT_SUPPLEMENTAL` policy, the gross-up is the claim's net `amount_cents` multiplied by `flat_gross_up_rate` and divided by one minus that rate, rounded half up to a whole cent; the case's payment history plays no part. Under `MARGINAL_AGGREGATE`, the case's `cumulative_taxable_paid_cents` — the running total of the case's already-paid taxable claim amounts, accumulated in `paid_at` order — is set against the policy's `marginal_bracket_threshold_cents`. The portion of the new claim that still fits under the bracket is the smaller of the net amount and the threshold minus the cumulative total, floored at zero; whatever remains of the net amount sits above the bracket. The below-bracket portion is grossed up at `marginal_rate_low` and the above-bracket portion at `marginal_rate_high`, each rounded half up to a whole cent on its own, and the two rounded results are summed into `gross_up_cents`. Two identical claims can therefore gross up differently depending on the order in which they are paid.

At payment, the claim's `total_payment_cents` is stamped as `amount_cents` plus `gross_up_cents`, and `paid_at` is stamped from the logical clock. The ledger then moves `amount_cents` out of the committed column and adds `total_payment_cents` to `total_paid_cents`; for taxable claims the case's `cumulative_taxable_paid_cents` additionally grows by `amount_cents`. Both the claim's and the case's versions increment. A case's claims are listed with an optional `status` filter.

### 3.6. Home Sale Assistance and the Loss-on-Sale Benefit

Where the governing policy tier allows it, a `MobilityCoordinator` may open the home-sale assistance program for an `IN_PROGRESS` case. The gate is twofold: a tier whose `home_sale_eligible` flag is false rejects the attempt with `ERR_HOME_SALE_NOT_ELIGIBLE`, and because each case admits exactly one home-sale transaction, a second program for the same case is rejected with `ERR_DUPLICATE_RESOURCE`. Creation records the `case_id`, an independent `appraised_value_cents`, the `original_purchase_price_cents` the employee paid, and the `list_price_cents`; the transaction begins `LISTED`.

Recording the sale — a coordinator action that requires the case still `IN_PROGRESS` — supplies the actual `sale_price_cents` and moves the transaction `LISTED` → `SOLD`. At that moment the system copies the policy's `loss_basis` into the transaction's `loss_basis_used` and computes the benefit. Under an `APPRAISED` basis, `gross_loss_cents` is the larger of zero and the appraised value minus the sale price; under `PURCHASE_PRICE`, it is the larger of zero and the original purchase price minus the sale price. Identical sale data can therefore yield different gross losses under the two bases. The payable benefit, `capped_benefit_cents`, is the smaller of the gross loss and the effective loss-on-sale cap — the policy's `loss_on_sale_cap_cents` plus the approved `LOSS_ON_SALE` exception increases for the case. Until the sale is recorded, both `gross_loss_cents` and `capped_benefit_cents` are null.

Settlement (`SOLD` → `SETTLED`, by a `FinanceSpecialist`) pays `capped_benefit_cents` straight into the case's `total_paid_cents` — notably without the amount ever passing through the committed column — and increments both the transaction's and the case's `version`. `SETTLED` is terminal. A case's home-sale collection returns at most one element.

### 3.7. Cap Exceptions and the Appeal Cycle

When a tier cap proves insufficient for a legitimate need, the relocating employee or a coordinator files an exception request naming the `case_id`, the `component` whose cap should rise — `HHG`, `TEMP_HOUSING`, `TRAVEL`, `MISC`, or `LOSS_ON_SALE` — an additive `requested_cap_increase_cents`, and a `justification`. Requests are born `PENDING` with an `appeal_count` of zero, and filing one requires an `IN_PROGRESS` case.

A `ProgramManager` decides each request. Approval (`PENDING` → `APPROVED`) is a guarded write carrying `expected_case_version`: a stale value is rejected with `ERR_STALE_VERSION` before the case-open check (`ERR_CASE_NOT_OPEN`) is examined, and on success the component's effective cap rises by the requested increase, with an optional `decision_note` recorded alongside. Because the effective cap derives from the sum of approved increases per case and component, an approved exception immediately widens headroom for subsequent bookings, claims, estimate approvals, and loss-on-sale computations, and both the request's and the case's `version` increment on approval. Rejection (`PENDING` → `REJECTED`) records the supplied `decision_note`.

A rejected request is not necessarily dead: the owning employee or a coordinator may appeal it back to `PENDING` exactly once. The appeal increments `appeal_count` and clears the prior `decision_note`; attempting a second appeal on an already-appealed request is rejected with `ERR_APPEAL_LIMIT_REACHED`. `APPROVED` is terminal — a decided approval cannot be re-opened — while `REJECTED` admits only the appeal path. A case's exception requests are listed with an optional `status` filter.

### 3.8. Cancellation, Early Departure, Repayment, and Final Closure

Ending a relocation takes three shapes. The simplest is cancellation from `AUTHORIZED`: no children can exist yet, so nothing beyond the case changes. Cancelling an `IN_PROGRESS` case is heavier and cascades. Every non-terminal assignment — any in `REQUESTED`, `SURVEY_SCHEDULED`, `ESTIMATE_SUBMITTED`, `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED` — becomes `CANCELLED`, and every booking in `HELD` or `CONFIRMED` becomes `CANCELLED`. Expense claims and home-sale transactions are deliberately left untouched by the cascade. Each cancelled assignment that held an approved estimate — those in `ESTIMATE_APPROVED`, `DELIVERED`, or `INVOICED` — and each cancelled `CONFIRMED` booking releases its held commitment: `total_committed_cents` falls and `total_released_cents` rises by the held amount, and every such release increments the case `version` alongside the cancelled child's own `version`. Assignments cancelled before estimate approval and bookings cancelled from `HELD` hold no funds and release nothing. The cancelling transition itself increments the case `version` once more, and the ledger is recomputed to its final shape.

Early departure begins with employment termination and ends with a prorated clawback. Once the employee's record shows `TERMINATED` — attempting the transition while the employee is still `ACTIVE` is rejected with `ERR_EMPLOYEE_NOT_TERMINATED` — a coordinator moves the case `IN_PROGRESS` → `CLOSED_EARLY`. The same child-cancellation and fund-release cascade fires, the paid column stands final, and the system assesses a repayment obligation. The employee's required service end is the case's `authorized_at` plus the policy's `repayment_window_months` calendar months. The months remaining are the whole calendar months between the employee's `termination_date` and that required end, counted per the calendar rule of §2.8 and clamped so the count never falls below zero. When nothing remains, no repayment agreement is created. Otherwise the system creates a `RepaymentAgreement` in `DRAFT` — one per case at most — stamped with the case's `id` as its `case_id` and a `total_owed_cents` equal to the case's `total_paid_cents` at closure multiplied by the months remaining and divided by `repayment_window_months`, rounded half up to a whole cent. The schedule divides that obligation into `installments_count` equal to `repayment_window_months`: the regular `installment_cents` is the total owed divided by the installment count, rounded down to a whole cent, and `final_installment_cents` is whatever remains after all but one regular installment are accounted for. The rounding-down happens first and the final installment absorbs the remainder — that order is pinned, since summing rounded installments first would yield a different tail.

The agreement activates when the owning employee signs it (`DRAFT` → `ACTIVE`): `signed_at` is stamped from the logical clock and `next_due_date` falls exactly one calendar month later. A `FinanceSpecialist` records payments of `amount_cents` against an `ACTIVE` or `DEFAULTED` agreement — a `DRAFT` agreement is not yet payable (`ERR_INVALID_STATE`) and a `SETTLED` one is terminal (`ERR_ALREADY_TERMINAL`). A payment larger than the outstanding `balance_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422), while a payment exactly equal to the balance is accepted and settles the agreement. Each recorded payment raises `paid_to_date_cents` and recomputes `balance_cents` as `total_owed_cents` minus `paid_to_date_cents`. When a payment brings the balance to zero the agreement settles itself; when a payment against a `DEFAULTED` agreement raises `paid_to_date_cents` to at least the arrears threshold without zeroing the balance, the agreement cures itself back to `ACTIVE`.

The arrears threshold compares cumulative payments against the installments that should have landed by now: the whole calendar months elapsed from `signed_at` to the logical clock, capped at one less than `installments_count`, multiplied by `installment_cents`. A `FinanceSpecialist` may mark an `ACTIVE` agreement `DEFAULTED` only when the logical clock has passed `next_due_date` and `paid_to_date_cents` stands below that threshold. Payments can also be reversed as a compensating action: `paid_to_date_cents` falls by the reversed amount — a reversal that would drive it below zero is rejected with `ERR_INVALID_REQUEST` — the balance is recomputed, and a `SETTLED` agreement whose balance reopens returns automatically to `ACTIVE`.

Final closure is gated on the state of everything the case owns. Closing directly from `IN_PROGRESS` requires that no assignment of the case remains in a non-terminal state, that no booking is `HELD` or `CONFIRMED`, that no claim is `SUBMITTED` or `APPROVED`, that no home-sale transaction is `LISTED` or `SOLD`, and that no repayment agreement exists in any state other than `SETTLED`. Closing from `CLOSED_EARLY` is gated purely on the repayment obligation: an agreement in `DRAFT`, `ACTIVE`, or `DEFAULTED` blocks closure. Either violation is rejected with `ERR_INVALID_STATE`, and any transition attempted on an already-terminal case, assignment, booking, claim, home sale, agreement, or decided exception request is rejected with `ERR_ALREADY_TERMINAL`. A case's repayment agreements are listed as a collection of at most one element.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource — including every state transition and data-stamping action — return `200 OK`, as do all reads. The table below is a navigational summary only; the request payloads, derived fields, side effects, and rejection conditions of each operation are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employees` | Create an employee | MobilityCoordinator |
| GET | `/employees/{id}` | Get an employee | All roles |
| POST | `/employees/{id}/terminate` | Terminate employment; stamps `termination_date` from the logical clock | MobilityCoordinator |
| POST | `/policies` | Create a policy tier; unique per job level, move scope, and home ownership | MobilityCoordinator |
| GET | `/policies/{id}` | Get a policy tier | All roles |
| POST | `/vendors` | Register a household-goods vendor | MobilityCoordinator |
| GET | `/vendors/{id}` | Get a vendor including computed rating aggregates | All roles |
| POST | `/vendors/{id}/suspend` | Suspend a vendor; blocks new assignments and survey scheduling | MobilityCoordinator |
| POST | `/relocation-cases` | Open a relocation case; policy tier auto-resolved | MobilityCoordinator |
| GET | `/relocation-cases` | List cases with optional filters | All roles |
| GET | `/relocation-cases/{id}` | Get a case including computed ledger totals | All roles |
| POST | `/relocation-cases/{id}/authorize` | Move a case `DRAFT` → `AUTHORIZED` | MobilityCoordinator |
| POST | `/relocation-cases/{id}/start` | Move a case `AUTHORIZED` → `IN_PROGRESS` | MobilityCoordinator |
| POST | `/relocation-cases/{id}/cancel` | Cancel an `AUTHORIZED` or `IN_PROGRESS` case; cascades child cancellations and fund release | MobilityCoordinator |
| POST | `/relocation-cases/{id}/terminate-early` | Move `IN_PROGRESS` → `CLOSED_EARLY`; cascade plus repayment assessment | MobilityCoordinator |
| POST | `/relocation-cases/{id}/close` | Close an `IN_PROGRESS` or `CLOSED_EARLY` case when all gates pass | MobilityCoordinator |
| POST | `/move-assignments` | Assign a household-goods vendor to a case | MobilityCoordinator |
| GET | `/move-assignments` | List move assignments with optional filters | All roles |
| GET | `/move-assignments/{id}` | Get a move assignment | All roles |
| POST | `/move-assignments/{id}/schedule-survey` | Move `REQUESTED` → `SURVEY_SCHEDULED`; two-hour vendor survey buffer enforced | MobilityCoordinator |
| POST | `/move-assignments/{id}/submit-estimate` | Move `SURVEY_SCHEDULED` → `ESTIMATE_SUBMITTED` (owning vendor only) | Vendor |
| POST | `/move-assignments/{id}/approve-estimate` | Move `ESTIMATE_SUBMITTED` → `ESTIMATE_APPROVED`; commits the estimate to the case ledger; OCC on the case version | MobilityCoordinator |
| POST | `/move-assignments/{id}/reject-estimate` | Move `ESTIMATE_SUBMITTED` → `REQUESTED`; clears survey and estimate for a re-survey cycle | MobilityCoordinator |
| POST | `/move-assignments/{id}/mark-delivered` | Move `ESTIMATE_APPROVED` → `DELIVERED` (owning vendor only) | Vendor |
| POST | `/move-assignments/{id}/submit-invoice` | Move `DELIVERED` → `INVOICED` (owning vendor only) | Vendor |
| POST | `/move-assignments/{id}/mark-paid` | Move `INVOICED` → `PAID`; settles committed estimate into paid at the invoiced amount | FinanceSpecialist |
| POST | `/move-assignments/{id}/rate` | Record the employee satisfaction rating for a paid move (owning employee only) | Employee |
| POST | `/service-bookings` | Book temporary housing or travel against a case | Employee, MobilityCoordinator |
| GET | `/service-bookings/{id}` | Get a service booking | All roles |
| GET | `/relocation-cases/{id}/service-bookings` | List a case's service bookings | All roles |
| POST | `/service-bookings/{id}/confirm` | Move `HELD` → `CONFIRMED`; commits the booking total to the case ledger | MobilityCoordinator |
| POST | `/service-bookings/{id}/cancel` | Move `HELD` or `CONFIRMED` → `CANCELLED`; releases committed funds when confirmed | Employee, MobilityCoordinator |
| POST | `/service-bookings/{id}/complete` | Move `CONFIRMED` → `COMPLETED`; converts the commitment into spend | MobilityCoordinator |
| POST | `/expense-claims` | Submit an expense claim (owning employee only) | Employee |
| GET | `/expense-claims/{id}` | Get an expense claim including gross-up fields | All roles |
| GET | `/relocation-cases/{id}/expense-claims` | List a case's expense claims | All roles |
| POST | `/expense-claims/{id}/approve` | Move `SUBMITTED` → `APPROVED`; commits the amount to the case ledger; OCC on the case version | FinanceSpecialist |
| POST | `/expense-claims/{id}/reject` | Move `SUBMITTED` → `REJECTED` with a reason | FinanceSpecialist |
| POST | `/expense-claims/{id}/resubmit` | Move `REJECTED` → `SUBMITTED` (owning employee only); optional replacement lines | Employee |
| POST | `/expense-claims/{id}/pay` | Move `APPROVED` → `PAID`; runs the tax gross-up and moves committed funds into paid | FinanceSpecialist |
| POST | `/home-sales` | Open the home-sale assistance program for a case (one per case) | MobilityCoordinator |
| GET | `/home-sales/{id}` | Get a home-sale transaction including computed loss and benefit | All roles |
| GET | `/relocation-cases/{id}/home-sales` | List a case's home-sale transactions (zero or one element) | All roles |
| POST | `/home-sales/{id}/record-sale` | Move `LISTED` → `SOLD`; computes gross loss and capped benefit under the policy's loss basis | MobilityCoordinator |
| POST | `/home-sales/{id}/settle` | Move `SOLD` → `SETTLED`; pays the capped benefit into the case ledger | FinanceSpecialist |
| GET | `/repayment-agreements/{id}` | Get a repayment agreement including schedule and balance | All roles |
| GET | `/relocation-cases/{id}/repayment-agreements` | List a case's repayment agreements (zero or one element) | All roles |
| POST | `/repayment-agreements/{id}/sign` | Move `DRAFT` → `ACTIVE` (owning employee only); sets signature date and first due date | Employee |
| POST | `/repayment-agreements/{id}/payments` | Record a payment against an `ACTIVE` or `DEFAULTED` agreement; auto-settles and auto-cures | FinanceSpecialist |
| POST | `/repayment-agreements/{id}/reverse-payment` | Reverse a previously recorded payment; may reopen a settled agreement | FinanceSpecialist |
| POST | `/repayment-agreements/{id}/mark-default` | Move `ACTIVE` → `DEFAULTED` when the due date has passed and installments are missed | FinanceSpecialist |
| POST | `/exception-requests` | Request a cap exception for one benefit component | Employee, MobilityCoordinator |
| GET | `/exception-requests/{id}` | Get an exception request | All roles |
| GET | `/relocation-cases/{id}/exception-requests` | List a case's exception requests | All roles |
| POST | `/exception-requests/{id}/approve` | Move `PENDING` → `APPROVED`; raises the component's effective cap; OCC on the case version | ProgramManager |
| POST | `/exception-requests/{id}/reject` | Move `PENDING` → `REJECTED` with a note | ProgramManager |
| POST | `/exception-requests/{id}/appeal` | Move `REJECTED` → `PENDING` once per request | Employee, MobilityCoordinator |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO 8601 UTC) | MobilityCoordinator |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions under which each error is raised are specified in §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POLICY_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_EMPLOYEE_NOT_ACTIVE` | 409 Conflict |
| `ERR_EMPLOYEE_NOT_TERMINATED` | 409 Conflict |
| `ERR_VENDOR_SUSPENDED` | 409 Conflict |
| `ERR_CASE_NOT_OPEN` | 409 Conflict |
| `ERR_INVALID_DATES` | 422 Unprocessable Entity |
| `ERR_HOUSING_OVERLAP` | 409 Conflict |
| `ERR_SURVEY_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_CAP_EXCEEDED` | 409 Conflict |
| `ERR_NIGHTS_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HOME_SALE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 Unprocessable Entity |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |

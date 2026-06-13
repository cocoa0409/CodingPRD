# Cobra Administration API — Product Requirements Document

## 1. Introduction

When an employee loses employer-sponsored group health coverage, federal continuation-coverage rules give the affected individual a tightly choreographed series of deadlines: the employer must report the triggering event, the administrator must mail an election notice, the individual has a fixed window to elect, and once elected, premiums must be billed and paid on a monthly cadence with statutory grace periods. The Cobra Administration API exists to model this entire choreography deterministically — every deadline, every premium calculation, every termination trigger, and every certificate of creditable coverage — so that a third-party administrator can run the program without ambiguity about who may act, when a window opens or closes, and exactly how much is owed.

The system is built around segregation of duties. The employer (acting as plan sponsor) reports who lost coverage and why; the administrator drives the regulatory timeline (notices, elections-adjacent adjudication, extensions, early termination, subsidies); a billing operator handles money in and money out; and the covered individual elects and self-pays on their own record only. Because nearly every consequence in this domain is time-driven — an election window expiring, an initial premium going unpaid past its grace, coverage running to its statutory end — the API exposes a simulated clock and an explicit sweep operation so that the passage of time and its cascading effects are reproducible rather than dependent on wall-clock execution.

This document specifies the resource model, the lifecycle state machines, the premium and subsidy arithmetic, the validation order, and the full endpoint and error contract. The structural envelope (Section 2) is fixed and precise; the business logic (Section 3) is where the domain's interlocking rules live and must be read as a whole.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles, spelled precisely as follows: `PlanAdministrator`, `PlanSponsor`, `BillingAgent`, `QualifiedBeneficiary`, and `System`. When a well-identified caller invokes an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles map to identity as follows. When `X-User-Role` is `PlanAdministrator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds for `PlanSponsor`: its `X-User-ID` is an opaque operator identifier with no entity backing. `BillingAgent` is likewise opaque — its `X-User-ID` is an operator identifier that the server does not match against any stored record. The `System` role is also opaque; it represents the automation actor for clock-driven sweeps and is not directly callable by an external client — its effects are produced as side effects of the administrator-invoked tick capability. By contrast, when `X-User-Role` is `QualifiedBeneficiary`, `X-User-ID` is the `id` of the acting `QualifiedBeneficiary`; ownership checks on any resource that references a `QualifiedBeneficiary` compare the resource's `beneficiary_id` foreign key to `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order; because the simulated clock can stamp identical `created_at` values, ties are broken by the order in which the resources were created (insertion order), so equally-timestamped resources still appear oldest-first.

Paginated and non-paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most top-level resources — group health plans, qualified beneficiaries, qualifying events, election notices, COBRA enrollments, premium accounts, premium invoices, payments, and subsidy grants — carry a standard set of system-managed fields:

- **`id`**: a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at`**: an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`**: an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation of the resource.
- **`version`**: a system-managed integer that begins at its initial value and increments by one on every mutation of the resource. It supports optimistic concurrency control (Section 2.8).

The HIPAA certificate is the one exception. It is an immutable record minted at the moment coverage ends, so it carries only `id` and `created_at`; it has no `updated_at` and no `version` field, because it is never modified after issuance.

A key consequence of the `updated_at`/`version` contract is that derived fields count as mutations. When a payment recomputes an account's ledger totals, or when a cascade flips a beneficiary's status, the affected resource's `updated_at` is refreshed and its `version` is incremented, exactly as if a client had edited it directly.

### 2.5. Time, Clocks, and Scheduled Sweeps

This domain is governed by deadlines, so the system maintains a single global simulated clock that supplies "now" for every domain timestamp the server stamps — including `created_at`/`updated_at` on resources, `reported_at` on an event, `notice_sent_date` on a notice, `elected_at` on an enrollment, and `received_date` on a payment — and for every deadline comparison. The response envelope's `meta.api_request_timestamp` is the sole exception: it is stamped from the real wall clock at the moment of the response and is independent of the simulated clock. An administrator may set this clock to a supplied instant for deterministic testing; the capability accepts a single `now_iso8601` value and returns the clock's current value as a `data` object carrying a single `now_iso8601` field holding that instant in ISO 8601 form, with HTTP 200.

Time does not advance on its own. Deadline-driven consequences — an election notice expiring past its `election_deadline`, an enrollment terminating for nonpayment past its initial or recurring grace, an enrollment running to its `scheduled_end_date` — are realized only when an administrator invokes the per-plan sweep capability. The sweep examines every notice and enrollment under the plan, compares each relevant deadline against the current clock, and applies the corresponding terminal transitions and cascades described in Section 3; it responds with HTTP 200 and returns the swept plan resource itself in `data` (not the set of affected resources). Between sweeps, resources retain whatever state they last reached; the clock may move forward via the clock-setting capability without any state changes until the sweep is run.

### 2.6. Monetary Values, Premium Rounding, and Ledger Conservation

All monetary amounts in this system are integers denominated in whole cents — premiums, invoice amounts, payments, subsidies, refunds, and account ledger totals alike. Wherever a calculation produces a fractional cent (applying an administrative load, prorating a partial first month, applying a subsidy percentage, or computing a shortfall allowance), the result is rounded to the nearest whole cent using the round-half-up method: a value whose fractional part is exactly one-half rounds up to the next whole cent.

Each premium account maintains a conserved ledger. Four accumulators are recomputed from their underlying records rather than mutated in place: `amount_invoiced_cents` is the sum of `amount_due_cents` across all of the account's invoices that are not in the `VOID` state; `amount_paid_cents` is the sum of `amount_cents` across all of the account's payments in the `POSTED` state; `amount_subsidized_cents` is the sum of `subsidy_applied_cents` across all non-`VOID` invoices; and `amount_refunded_cents` is the total credit refunded back out to the beneficiary. From these, the account's `credit_balance_cents` is computed as `amount_paid_cents` plus `amount_subsidized_cents`, minus `amount_invoiced_cents`, minus `amount_refunded_cents`, and this balance must never fall below zero. This conservation identity (paid plus subsidized, less invoiced, less refunded) is the invariant that every billing operation preserves.

### 2.7. Referential Integrity and Resource Ownership

Resources in this domain are flat peers linked by foreign-key fields rather than by deeply nested URLs. For any request, the server validates the path resource and any foreign-key-referenced resources from left to right, rejecting with `ERR_NOT_FOUND` the first identifier in the chain that does not resolve to an existing resource. Only the plan owns nested collections reachable by URL (its beneficiaries); every other cross-link — an event's `plan_id` and `beneficiary_id`, a notice's `event_id`, an enrollment's `notice_id`, an account's `enrollment_id`, an invoice's `account_id`, a payment's `account_id`, a subsidy's `enrollment_id`, a certificate's `beneficiary_id` and `enrollment_id` — is followed by id or surfaced through a filterable list, never by URL nesting.

Beyond existence, a `QualifiedBeneficiary` may act only on its own records. When a caller with role `QualifiedBeneficiary` elects on a notice or posts a payment to an account, the server compares the targeted record's `beneficiary_id` to `X-User-ID`; if they differ, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

### 2.8. Optimistic Concurrency Control on the Premium Account

Refunding credit from a premium account is guarded by optimistic concurrency control. A refund request must carry `expected_account_version`, a non-optional field whose value is the client's last observed `version` of the target `PremiumAccount`. If `expected_account_version` does not equal the account's current `version` — because a prior payment or a prior refund has already advanced the account since the client last read it, so the refund the client computed against its stale view no longer reflects the available credit — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint takes a version field; only the refund operation participates in this check.

### 2.9. Validation Order

When several checks could fail on a single write, they are evaluated in a fixed priority order so that the returned error is deterministic. The order is: first, header well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role permission for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); third, existence of the path and foreign-key resources, left to right (`ERR_NOT_FOUND`); fourth, resource ownership for a `QualifiedBeneficiary` acting on its own notice or account (`ERR_NOT_RESOURCE_OWNER`); fifth, request-body shape — enum members must be recognized values, monetary amounts must be greater than zero, any `coverage_month` must be a well-formed `YYYY-MM` string, and required fields must be present (`ERR_INVALID_REQUEST`); and sixth, the target resource being in a state that permits the requested transition (`ERR_INVALID_STATE`). Only after all of these pass does the system evaluate the operation-specific business rules described in Section 3 (eligibility, window, fiscal, and concurrency checks). Authentication precedes authorization, authorization precedes existence, existence precedes ownership, ownership precedes body validity, and body validity precedes state — a check earlier in this order always masks one later in it.

## 3. Business Logic & Workflows

### 3.1. Plans, Beneficiaries, and the Configuration Root

Everything begins with a group health plan, created by a `PlanAdministrator`. A plan is registered with a `name` and an `applicable_premium_cents` — the full monthly cost of the coverage combining the employee and employer share, which is the base on which COBRA premiums are computed and must be greater than zero. The plan also carries the timing and pricing knobs that drive the rest of the program, each of which may be supplied at creation or left to its default. The administrative load applied to the applicable premium for ordinary coverage months is `standard_admin_fee_pct`, defaulting to 0.02 (two percent) and constrained to the range from zero through 0.02 inclusive. The heavier load applied during disability-extension months is `disability_admin_fee_pct`, defaulting to 0.50 (fifty percent, i.e. a 150-percent premium) and constrained to the range from zero through 0.50 inclusive. The number of days the sponsor has to report an employer-side qualifying event is `employer_notice_days`, defaulting to 30. The number of days the administrator has to send the election notice after an event is recorded is `election_notice_days`, defaulting to 14. The length of the election window is `election_window_days`, defaulting to 60. The grace period for the very first premium is `initial_premium_grace_days`, defaulting to 45, and the grace period for each recurring monthly premium is `recurring_premium_grace_days`, defaulting to 30. Finally, `insignificant_shortfall_floor_cents` is the floor of the insignificant-shortfall allowance, defaulting to 5000 (fifty dollars). A newly created plan has `status` of `ACTIVE`; the only other plan status is `TERMINATED`.

Against a plan, a `PlanAdministrator` or a `PlanSponsor` registers a qualified beneficiary by supplying the `plan_id` it belongs to, the `full_name`, the `relationship` (one of `EMPLOYEE`, `SPOUSE`, or `DEPENDENT`), and the `original_coverage_start` date on which the individual's active pre-COBRA coverage began. A beneficiary's `status` starts at `ACTIVE_EMPLOYEE_COVERAGE` and walks through `COBRA_ELIGIBLE`, then `COBRA_ENROLLED`, and ultimately `COVERAGE_ENDED` as the lifecycle in the following subsections plays out; these four are the only beneficiary statuses. A plan's beneficiaries can be listed through the plan's nested beneficiary collection, which is how a sponsor or billing operator reaches the people covered under a plan.

### 3.2. Recording a Qualifying Event

A qualifying event is the trigger that starts a COBRA timeline. Either a `PlanSponsor` (the employer of record) or a `PlanAdministrator` records one against a beneficiary by supplying the `plan_id`, the `beneficiary_id`, the `event_type`, the `event_date` on which the event occurred, and the `coverage_loss_date` — the first date the beneficiary loses active coverage, which anchors the election window. The recognized event types are `TERMINATION`, `REDUCTION_OF_HOURS`, `DIVORCE`, `DEATH_OF_EMPLOYEE`, `MEDICARE_ENTITLEMENT`, and `DEPENDENT_AGE_OUT`.

On creation the event lands in `status` `RECORDED`, its `reported_at` is stamped with the current clock, and the system computes the base maximum COBRA duration into `max_coverage_months`: a `TERMINATION` or a `REDUCTION_OF_HOURS` yields 18 months, while a `DIVORCE`, a `DEATH_OF_EMPLOYEE`, a `MEDICARE_ENTITLEMENT`, or a `DEPENDENT_AGE_OUT` yields 36 months. For employer-side events the system also computes an `employer_notice_deadline` equal to the `event_date` plus the plan's `employer_notice_days`; the employer-side event types are exactly `TERMINATION`, `REDUCTION_OF_HOURS`, `DEATH_OF_EMPLOYEE`, and `MEDICARE_ENTITLEMENT`, and this deadline is null for the two non-employer-side types, `DIVORCE` and `DEPENDENT_AGE_OUT`. The boolean `late_reported` is set to true when the event was recorded after that deadline — that is, when `reported_at` is later than `employer_notice_deadline` for an employer-side event — and remains false otherwise. An event's full lifecycle status runs over `RECORDED`, `NOTICE_SENT`, `ELECTED`, `LAPSED`, and `VOID`.

Before any notice goes out, an administrator may void a recorded event. Voiding is permitted only while the event is `RECORDED`; attempting it from any other status is rejected with `ERR_INVALID_STATE`. A successful void moves the event to `VOID` with no further cascade.

### 3.3. Issuing the Election Notice

Once an event is recorded, a `PlanAdministrator` issues the election notice that opens the beneficiary's election window. Issuing a notice is permitted only when the event is in `RECORDED` status; otherwise the request fails with `ERR_INVALID_STATE`. It also requires that the beneficiary still be eligible: the beneficiary's `status` must be `ACTIVE_EMPLOYEE_COVERAGE`, so that an already-enrolled or already-ended beneficiary cannot receive a fresh notice on the same active coverage. A beneficiary who is not in `ACTIVE_EMPLOYEE_COVERAGE` causes the request to be rejected with `ERR_BENEFICIARY_NOT_ELIGIBLE`.

Issuing the notice advances the event from `RECORDED` to `NOTICE_SENT` and produces a chain of effects. A new election notice is created carrying the originating `event_id` and the `beneficiary_id`, its `notice_sent_date` stamped with the current clock, and its `status` set to `OUTSTANDING` (the other notice statuses being `ELECTED` and `EXPIRED`). The window's start, recorded as `election_window_anchor`, is the later of the event's `coverage_loss_date` and the `notice_sent_date`. The `election_deadline` is that anchor plus the plan's `election_window_days`. As a cross-entity cascade, the beneficiary's `status` bubbles from `ACTIVE_EMPLOYEE_COVERAGE` to `COBRA_ELIGIBLE`, and the event's `version` is incremented by one (with its `updated_at` refreshed). This is a depth-two cascade: a single send-notice action both creates the election notice and mutates the beneficiary's status.

### 3.4. Election Within the Window

The covered individual elects COBRA on their own outstanding notice; this is the one action reserved to the `QualifiedBeneficiary` role, who may act only on a notice whose `beneficiary_id` equals `X-User-ID`. Election is permitted only while the notice is `OUTSTANDING` — an already-elected or expired notice is rejected with `ERR_INVALID_STATE`. It is also bounded in time: the current clock must be on or before the notice's `election_deadline`. An election attempted after the deadline (clock strictly later than `election_deadline`) is rejected with `ERR_ELECTION_WINDOW_CLOSED`.

A valid election sets off the deepest cascade in the system. The notice moves to `ELECTED` and the originating event also moves to `ELECTED`. A COBRA enrollment is created: it records the `notice_id` it sprang from, copies down the `beneficiary_id` and `event_id`, stamps `elected_at` with the current clock, and computes its dates. The enrollment's `coverage_start_date` is set equal to the event's `coverage_loss_date`, because COBRA coverage is retroactive to the day active coverage was lost. Its `base_max_months` is copied from the event's `max_coverage_months` (18 or 36). The `extension_months` field starts at 0, the `disability_extension` flag starts false, `actual_end_date` starts null, and `termination_reason` starts null. The `scheduled_end_date` — the last day of coverage — is computed as the `coverage_start_date` advanced by the sum of `base_max_months` and `extension_months` months, then stepped back by one day. The enrollment's `status` opens at `PENDING_INITIAL_PREMIUM`; the only other enrollment statuses are `ACTIVE` and `TERMINATED`.

The same election simultaneously creates the premium account for that enrollment — one account per enrollment. The account records its `enrollment_id` and `beneficiary_id`, computes its `monthly_premium_cents` as the round-half-up of the plan's `applicable_premium_cents` multiplied by one plus `standard_admin_fee_pct` (this is the per-month gross premium for non-disability months), and sets its `initial_premium_due_date` to the enrollment's `elected_at` plus the plan's `initial_premium_grace_days`. The account's accumulators — `amount_invoiced_cents`, `amount_paid_cents`, `amount_subsidized_cents`, `amount_refunded_cents`, and `credit_balance_cents` — all begin at 0, and its `paid_through_date` begins null because no month has yet been satisfied. As a further cascade, the beneficiary's `status` advances from `COBRA_ELIGIBLE` to `COBRA_ENROLLED`, and the event's `version` is incremented by one. This is a depth-three cascade: the election mutates the notice, the notice's election creates the enrollment, and the enrollment's creation itself creates the premium account. The election endpoint responds with HTTP 201 and returns the newly created COBRA enrollment resource in `data` (not the notice or the premium account).

If, instead, the window closes with the notice still `OUTSTANDING`, the lapse is realized by the clock sweep rather than by any client action. When the administrator runs the sweep and the current clock is strictly past a notice's `election_deadline` while the notice is still `OUTSTANDING`, the sweep moves the notice to `EXPIRED`, moves the originating event to `LAPSED`, and bubbles the beneficiary's `status` to `COVERAGE_ENDED`. The states `ELECTED`, `LAPSED`, and `VOID` are the terminal stops for a qualifying event; `ELECTED` and `EXPIRED` are terminal for a notice.

### 3.5. Premium Invoicing

With an enrollment in place, a `BillingAgent` or a `PlanAdministrator` generates monthly premium invoices against the account. An invoice is created by naming the `account_id`, the `coverage_month` it charges for (a `YYYY-MM` string), and optionally a `proration_mode`. The system derives the invoice's `coverage_month_index`, the one-based position of that month relative to the enrollment's `coverage_start_date` month, where the start month is index 1.

The `coverage_month` must fall within the enrollment's coverage interval — from the coverage-start month through the `scheduled_end_date` month — and an invoice for a month outside that interval is rejected with `ERR_INVALID_COVERAGE_MONTH`. The same error guards proration: `proration_mode` is one of `FULL_MONTH` (the default) or `DAILY_PRORATED`, and only the first coverage month may be `DAILY_PRORATED`; requesting daily proration for any month other than month 1 is also rejected with `ERR_INVALID_COVERAGE_MONTH`. An account may hold only one invoice per coverage month; a second invoice for an already-invoiced month is rejected with `ERR_DUPLICATE_INVOICE`.

Each invoice computes its `gross_premium_cents` as the round-half-up of the plan's `applicable_premium_cents` multiplied by one plus a fee percentage. That fee percentage is `standard_admin_fee_pct` for ordinary months, but for a disability-extended enrollment it becomes `disability_admin_fee_pct` for the months whose `coverage_month_index` falls in the inclusive range from 19 through 29 — the 150-percent disability tier. Ordinary months — index 1 through 18 (or 1 through 36 for a 36-month event), and any month of a non-extended enrollment — apply the standard load, charging 102 percent of the applicable premium; the disability-extension months 19 through 29 of a disability-extended enrollment apply the heavier load, charging 150 percent.

From the gross premium the system computes `amount_due_cents`. For a `FULL_MONTH` invoice the amount due equals the gross premium, charging the entire month even though COBRA coverage may have begun mid-month — the standard administrator convention. For the `DAILY_PRORATED` first month, the system counts the calendar days in the coverage-start month, then counts the days covered as the days-in-month minus the day-of-month of `coverage_start_date` plus one (i.e. from the start date through month end inclusive), and sets the amount due to the round-half-up of the gross premium multiplied by the days covered, divided by the days in the month. The invoice then computes its `subsidy_applied_cents` (Section 3.7) and its `beneficiary_owed_cents` as `amount_due_cents` minus `subsidy_applied_cents`. A new invoice opens with `status` `OPEN`; the other invoice statuses are `PAID` and `VOID`. Creating an invoice recomputes the account's `amount_invoiced_cents` and `amount_subsidized_cents`.

### 3.6. Posting Payments and Satisfying Months

Payments flow against an account from either a `BillingAgent` or the `QualifiedBeneficiary` who owns the account. A payment names the `account_id`, the `amount_cents` tendered (which must be greater than zero), and the `target_coverage_month` it is applied toward — the earliest open coverage month being paid. Posting is permitted only while the enrollment is in `PENDING_INITIAL_PREMIUM` or `ACTIVE`; against any other enrollment state the payment is rejected with `ERR_INVALID_STATE`. The targeted month must already have an `OPEN` invoice on the account, or the payment is rejected with `ERR_NO_OPEN_INVOICE`.

When a payment posts it is recorded with `status` `POSTED` (the alternative being `REFUNDED`) and `received_date` stamped with the current clock. The system then evaluates `deemed_full_payment`, which captures the regulatory "insignificant shortfall" rule: a small underpayment is treated as paying the month in full. To decide this, the system computes an allowance equal to the larger of the plan's `insignificant_shortfall_floor_cents` and the round-half-up of ten percent of the targeted invoice's `beneficiary_owed_cents`. It then sums all `POSTED` payments targeting that same coverage month on the account to get the amount already paid, and takes the shortfall as the invoice's `beneficiary_owed_cents` minus that already-paid total. The payment is deemed a full payment when the shortfall is at most the allowance — a shortfall exactly equal to the allowance still counts as fully paid. If the targeted invoice is now fully satisfied (the payments-plus-subsidy meet or exceed the amount owed) or is deemed full, the invoice moves to `PAID`.

Every posted payment recomputes the account's `amount_paid_cents`, `credit_balance_cents`, and `paid_through_date`. The paid-through date is the central ledger reconciliation: walking coverage months in ascending `coverage_month_index` from month 1, a month counts as satisfied when the sum of its `POSTED` payments plus the invoice's `subsidy_applied_cents` meets or exceeds the invoice's `beneficiary_owed_cents`, or when the latest payment for that month is a deemed-full payment. The system advances through the longest unbroken run of satisfied months starting at month 1 and sets `paid_through_date` to the last calendar day of the last month in that run; if month 1 is not satisfied, `paid_through_date` is null. A gap stops the run even when a later month is independently satisfied.

The first payment that satisfies coverage month 1 carries special weight. If the enrollment is still `PENDING_INITIAL_PREMIUM` and a payment satisfies month 1 (payment-plus-subsidy meeting the month-1 amount owed, or a shortfall within the allowance) with `received_date` on or before the account's `initial_premium_due_date` — where the gating `received_date` is that of the latest (most recently received, ties broken by creation order) `POSTED` month-1 payment — the enrollment bubbles from `PENDING_INITIAL_PREMIUM` to `ACTIVE` and the account's `paid_through_date` is recomputed to the last day of month 1. This is the moment COBRA coverage vests.

### 3.7. Subsidies and Their Chronological Application

A `PlanAdministrator` may grant a premium subsidy over a span of coverage months. A subsidy grant names the `enrollment_id`, a `subsidy_pct` (the fraction of each covered month's premium paid by the subsidy — greater than zero and at most 1.00, typically 0.65 for a partial subsidy or 1.00 for a full one), a `start_month`, and an `end_month`, both `YYYY-MM`. The range must satisfy `start_month` on or before `end_month` and must fall within the enrollment's coverage interval; a reversed or out-of-interval range is rejected with `ERR_INVALID_SUBSIDY_RANGE`. A new grant opens with `status` `ACTIVE` (the only other status being `REVOKED`).

Subsidies apply chronologically, never by stacking. For a given invoice's `coverage_month`, the system orders the enrollment's `ACTIVE` grants by `start_month` ascending and then by `created_at` ascending, and selects the first grant in that order whose inclusive `start_month`-through-`end_month` range contains the month. If a grant matches, the invoice's `subsidy_applied_cents` is the round-half-up of its `amount_due_cents` multiplied by that grant's `subsidy_pct`; if none matches, the subsidy applied is 0. Either way, `beneficiary_owed_cents` is `amount_due_cents` minus the subsidy applied. When two `ACTIVE` grants overlap the same month, the earliest by `start_month` then `created_at` wins and the later overlapping grant is ignored for that month. `REVOKED` grants are never considered. Granting a subsidy recomputes the subsidy and the beneficiary-owed amount on the `OPEN` invoices that fall within its range.

When an administrator revokes a grant, it moves to `REVOKED` and the system recomputes subsidy on future invoices only — those whose `coverage_month` is later than the current clock's month — reassigning each to the next matching `ACTIVE` grant in chronological order, or to 0 if none remains. Invoices that are already `PAID` keep their applied subsidy, a chronological lock that prevents retroactively clawing back coverage that has already been settled.

### 3.8. The Disability Extension

A `PlanAdministrator` may extend an eligible 18-month enrollment to 29 months on the strength of a Social Security disability determination, by supplying the `determination_date`. Three conditions must all hold. First, the determination must fall within the first 60 days of coverage — `determination_date` on or after the `coverage_start_date` and on or before the `coverage_start_date` plus 60 days. Second, the current clock must be on or before the enrollment's `scheduled_end_date` (the original 18-month end), so the extension cannot be applied after the original coverage has already run out. A determination outside the first-60-days window, or an application made after the 18-month scheduled end, is rejected with `ERR_DISABILITY_WINDOW_INVALID`. Third, the extension applies only to a base 18-month enrollment — one whose `base_max_months` is 18; a 36-month enrollment cannot extend, and an attempt to extend it is rejected with `ERR_EXTENSION_NOT_APPLICABLE`.

On success, `extension_months` is set to 11, `disability_extension` becomes true, and `scheduled_end_date` is recomputed as the `coverage_start_date` advanced by 29 months and stepped back by one day. From that point on, the invoices for months 19 through 29 bill at the disability premium tier described in Section 3.5.

### 3.9. Early Termination

A `PlanAdministrator` may end an active enrollment early, before it would otherwise run to term, by supplying a `reason`. Early termination is permitted only while the enrollment is `ACTIVE`; from any other state the request is rejected with `ERR_INVALID_STATE`. The `reason` must be one of `OTHER_GROUP_COVERAGE`, `MEDICARE_ENTITLEMENT`, or `PLAN_TERMINATED`; any other reason is rejected with `ERR_INVALID_TERMINATION_REASON`.

A valid early termination moves the enrollment from `ACTIVE` to `TERMINATED`, records the supplied `reason` into `termination_reason`, and sets `actual_end_date` to the current clock (the end of the current paid period). It then voids every `OPEN` invoice whose `coverage_month` is after the month of `actual_end_date`, bubbles the beneficiary's `status` to `COVERAGE_ENDED`, and creates a HIPAA certificate covering the interval from `coverage_start_date` through `actual_end_date`. If — and only if — the `reason` is `PLAN_TERMINATED`, the cascade also flips the owning plan's `status` to `TERMINATED`.

### 3.10. Clock-Driven Terminations and Certificates

Most terminations are not requested by a client at all; they are realized when the administrator runs the per-plan sweep and the clock has crossed a deadline. The sweep applies four distinct outcomes.

First, an enrollment still in `PENDING_INITIAL_PREMIUM` whose `initial_premium_due_date` the clock has passed, with coverage month 1 not fully satisfied, is terminated for nonpayment before any coverage vested. The enrollment moves to `TERMINATED` with `termination_reason` `NONPAYMENT`, and its `actual_end_date` is set to the `coverage_start_date` minus one day — signaling that no coverage ever vested. All `OPEN` invoices on the account are voided and the beneficiary's `status` becomes `COVERAGE_ENDED`. Because no month was ever paid, no HIPAA certificate is issued in this case (the creditable-month count would be zero).

Second, an `ACTIVE` enrollment whose earliest unsatisfied month has passed its recurring grace — that is, the first-of-month due date plus the plan's `recurring_premium_grace_days`, with the month still not fully satisfied — is terminated for nonpayment, but with coverage that did vest. The enrollment moves to `TERMINATED` with `termination_reason` `NONPAYMENT`, and `actual_end_date` is set to the account's `paid_through_date`, so coverage retroactively ends at the last fully paid month. The sweep voids every `OPEN` invoice whose `coverage_month` is after `paid_through_date`, bubbles the beneficiary's `status` to `COVERAGE_ENDED`, and creates a HIPAA certificate spanning `coverage_start_date` through `actual_end_date`. This is a depth-three cascade: the tick terminates the enrollment, the termination voids each trailing invoice, and the same termination creates the certificate.

Third, an `ACTIVE` enrollment whose `scheduled_end_date` the clock has passed runs to term. It moves to `TERMINATED` with `termination_reason` `RUN_TO_TERM` and `actual_end_date` equal to the `scheduled_end_date`, the beneficiary's `status` becomes `COVERAGE_ENDED`, and a HIPAA certificate is created spanning `coverage_start_date` through `scheduled_end_date`.

Fourth, as already noted in Section 3.4, an `OUTSTANDING` notice whose `election_deadline` the clock has passed expires, lapsing its event and ending the beneficiary's coverage.

Whenever a certificate is minted — by early termination, recurring-grace nonpayment, or run-to-term — it certifies the creditable coverage. It records the `beneficiary_id` and the `enrollment_id`, sets `coverage_from` to the enrollment's `coverage_start_date` and `coverage_through` to its `actual_end_date`, copies the producing `termination_reason` into `issued_reason` (one of `RUN_TO_TERM`, `NONPAYMENT`, `OTHER_GROUP_COVERAGE`, `MEDICARE_ENTITLEMENT`, or `PLAN_TERMINATED`), and computes `creditable_months` as the count of whole COBRA coverage months between the endpoints inclusive: the through-year minus the from-year, multiplied by twelve, plus the through-month minus the from-month, plus one. If the end date precedes the start date — the nonpayment-before-vesting case — the count would be zero, which is exactly why no certificate is issued there. Certificates are retrievable by beneficiary and by enrollment.

### 3.11. Refunds

When an account carries a positive `credit_balance_cents` — because payments plus subsidies have exceeded what was invoiced — a `BillingAgent` may refund credit back to the beneficiary by supplying a `refund_amount_cents` and the `expected_account_version` described in Section 2.8. A refund requires a positive credit balance; against a zero balance it is rejected with `ERR_NO_CREDIT_BALANCE`. The `refund_amount_cents` must not exceed the account's current `credit_balance_cents`, or the request is rejected with `ERR_REFUND_EXCEEDS_CREDIT`. And the `expected_account_version` must match the account's current `version`, or the request is rejected with `ERR_STALE_VERSION`.

A successful refund adds the refunded amount into `amount_refunded_cents` and recomputes `credit_balance_cents`, preserving the conservation identity of Section 2.6 (paid plus subsidized, less invoiced, less refunded). The account's `version` is incremented by one. The refund is a compensating ledger movement: it removes credit that conservation would otherwise leave stranded on the account, without disturbing the invoiced or paid history.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code. Operations that modify an existing resource, run a sweep, set the clock, or return data without minting a new resource return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a group health plan (config root) | PlanAdministrator |
| GET | `/plans/{id}` | Get a plan | PlanAdministrator, PlanSponsor, BillingAgent, QualifiedBeneficiary |
| GET | `/plans/{id}/beneficiaries` | List beneficiaries under a plan | PlanAdministrator, PlanSponsor, BillingAgent |
| POST | `/plans/{id}/tick` | Run clock-driven sweeps for the plan | PlanAdministrator |
| POST | `/_clock/set` | Set the simulated current UTC time | PlanAdministrator |
| POST | `/beneficiaries` | Register a qualified beneficiary on a plan | PlanAdministrator, PlanSponsor |
| GET | `/beneficiaries/{id}` | Get a beneficiary | PlanAdministrator, PlanSponsor, BillingAgent, QualifiedBeneficiary |
| GET | `/beneficiaries/{id}/certificates` | List HIPAA certificates for a beneficiary | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| POST | `/events` | Record a qualifying event for a beneficiary | PlanSponsor, PlanAdministrator |
| GET | `/events/{id}` | Get a qualifying event | PlanAdministrator, PlanSponsor, BillingAgent, QualifiedBeneficiary |
| GET | `/events` | List qualifying events (filter by `plan_id` or `beneficiary_id`) | PlanAdministrator, PlanSponsor, BillingAgent |
| POST | `/events/{id}/send-notice` | Issue the election notice for an event | PlanAdministrator |
| POST | `/events/{id}/void` | Void a recorded event before any notice is sent | PlanAdministrator |
| GET | `/notices/{id}` | Get an election notice | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/notices` | List election notices (filter by `event_id` or `beneficiary_id`) | PlanAdministrator, BillingAgent |
| POST | `/notices/{id}/elect` | Elect COBRA within the election window | QualifiedBeneficiary |
| GET | `/enrollments/{id}` | Get a COBRA enrollment | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/enrollments` | List enrollments (filter by `beneficiary_id`, `notice_id`, or `event_id`) | PlanAdministrator, BillingAgent |
| GET | `/enrollments/{id}/certificates` | List HIPAA certificates for an enrollment | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| POST | `/enrollments/{id}/apply-disability-extension` | Apply an SSA disability extension (18 → 29 months) | PlanAdministrator |
| POST | `/enrollments/{id}/terminate-early` | Terminate coverage early for a permitted reason | PlanAdministrator |
| POST | `/enrollments/{id}/subsidies` | Grant a premium subsidy over a month range | PlanAdministrator |
| POST | `/subsidies/{id}/revoke` | Revoke a subsidy grant | PlanAdministrator |
| GET | `/subsidies/{id}` | Get a subsidy grant | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/subsidies` | List subsidy grants (filter by `enrollment_id`) | PlanAdministrator, BillingAgent |
| GET | `/accounts/{id}` | Get a premium account (ledger summary) | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/accounts` | List premium accounts (filter by `enrollment_id` or `beneficiary_id`) | PlanAdministrator, BillingAgent |
| POST | `/accounts/{id}/invoices` | Generate a monthly premium invoice | BillingAgent, PlanAdministrator |
| GET | `/invoices/{id}` | Get a premium invoice | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/invoices` | List premium invoices (filter by `account_id`) | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| POST | `/accounts/{id}/payments` | Post a premium payment toward a coverage month | BillingAgent, QualifiedBeneficiary |
| GET | `/payments/{id}` | Get a payment | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| GET | `/payments` | List payments (filter by `account_id`) | PlanAdministrator, BillingAgent, QualifiedBeneficiary |
| POST | `/accounts/{id}/refund` | Refund credit balance back to the beneficiary (OCC-guarded) | BillingAgent |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_BENEFICIARY_NOT_ELIGIBLE` | 409 |
| `ERR_ELECTION_WINDOW_CLOSED` | 409 |
| `ERR_DISABILITY_WINDOW_INVALID` | 409 |
| `ERR_EXTENSION_NOT_APPLICABLE` | 409 |
| `ERR_INVALID_TERMINATION_REASON` | 409 |
| `ERR_INVALID_COVERAGE_MONTH` | 409 |
| `ERR_DUPLICATE_INVOICE` | 409 |
| `ERR_NO_OPEN_INVOICE` | 409 |
| `ERR_INVALID_SUBSIDY_RANGE` | 409 |
| `ERR_REFUND_EXCEEDS_CREDIT` | 409 |
| `ERR_NO_CREDIT_BALANCE` | 409 |
| `ERR_STALE_VERSION` | 412 |

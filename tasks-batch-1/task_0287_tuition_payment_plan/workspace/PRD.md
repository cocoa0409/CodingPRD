# Tuition Payment Plan API — Product Requirements Document

## 1. Introduction

Higher-education finance offices live and die by the integrity of a ledger. When a student finances a term's tuition across several installments, every charge, every dollar of financial aid, every payment, and every late fee must reconcile cleanly against a single conserved principal — and a discrepancy of even one cent erodes trust in the whole system. The Tuition Payment Plan API exists to make that reconciliation deterministic. It governs the full arc of a financed term: a registrar posts tuition charges and aid against a student's enrollment, activates a payment plan that snapshots its fee terms and lays down an installment schedule, and from that point forward the system services payments, sweeps overdue installments into delinquency, assesses tiered late fees, places and clears holds, and — should the student leave mid-term — prorates a refund according to the institution's chosen withdrawal policy.

Two operational realities shape the design. First, the system is a pricing engine as much as a ledger: the same withdrawal can retain a different fraction of charges depending on whether an institution prorates by elapsed days or by fixed schedule brackets, and late fees climb through day-based tiers. Second, balances are *derived*, not stored by hand — a single charge reversal or aid cancellation must cascade a re-spread across the remaining scheduled installments without ever disturbing what has already been paid. Because those cascades silently advance an enrollment's version, the API treats concurrent edits as a first-class hazard and rejects writes made against a stale snapshot. All monetary amounts are denominated in integer cents, and all date arithmetic reads an institution-scoped logical clock rather than wall-clock time, so that test-driving a term forward in time is both possible and exact.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API. The business-process narratives in Section 3 build on these foundations.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly three roles, spelled precisely as follows: `Registrar`, `Bursar`, and `Student`.

A `Registrar` is the institution operator. This role manages terms, students, plan templates, enrollments, charges, aid, delinquency sweeps, holds, and withdrawals. When `X-User-Role` is `Registrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. A `Bursar` is the cashiering operator, responsible for creating payments and for settling or failing them, plus read access across the ledger. When `X-User-Role` is `Bursar`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity's `id`. A `Student` is a self-service payer who views their own enrollments and ledger and who initiates payments such as down payments and installment payments. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a `Student` compare the resource's foreign-key field to `X-User-ID`.

Creating and settling payments is shared: a payment may be created by either a `Bursar` or a `Student`, while settling and failing a payment are reserved for the `Bursar`. All read (GET) endpoints are available to all three roles.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip from the start of the result set and defaults to 0.

Unless an endpoint states otherwise, every list is sorted by the `created_at` timestamp in ascending order. Each list response includes the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Institutional Scoping and the Logical Clock

Every resource in this system lives inside exactly one `Institution`, and the `Institution` is the root of the hierarchy. An `Institution` carries a `name`, a `currency` (an ISO currency code, defaulting to `USD`, with all amounts denominated in cents), and a `refund_policy` that selects which withdrawal-proration variant the institution uses — either `DATE_BASED` (the default) or `SCHEDULE_BASED`. It also holds a `clock_utc`, an institution-scoped current UTC timestamp. This logical clock is the *only* source of "now" for every date comparison the system performs — installment due-date checks, enrollment-window checks, delinquency sweeps, and withdrawal proration all read `clock_utc` and never the server's wall clock. The clock is advanced exclusively through the test-driving capability described in Section 3, which sets it to a supplied instant; on institution creation it begins at the Unix epoch until set.

When an endpoint path names a chain of resources, the system validates each path identifier left-to-right against the institution that scopes it. The first identifier in the path that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`, before any deeper identifier or business rule is evaluated. A reference to a resource that does not exist within the institution always yields `ERR_NOT_FOUND`.

### 2.5. Common Resource Properties and Versioning

Every resource exposes a system-managed `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits recording when the resource was first created. All entities in this system additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and a `version`, an integer that begins at its initial value and increments by one on every mutation of the resource. The `version` underpins optimistic concurrency control, described in Section 2.7.

A derived-field recomputation counts as a mutation. When the system recalculates an enrollment's balances — because a charge was posted or reversed, aid applied or cancelled, an installment paid, or a late fee assessed or waived — that recomputation refreshes the enrollment's `updated_at` and increments its `version`, even though no field was supplied by a client on that call.

### 2.6. Monetary Precision and Rounding

All monetary values are integers denominated in cents; there are no fractional-cent amounts anywhere in the system. Wherever a calculation produces a non-integer intermediate — a percentage of a charge, a fraction of net principal, a prorated retained amount — the result is converted to whole cents using the **round half up** convention (a value exactly halfway between two integers rounds up to the larger). The ordering of rounding within a multi-step calculation is significant and is specified with each calculation in Section 3; in particular, the down payment is rounded to whole cents *before* the financed remainder is split, never after.

### 2.7. Optimistic Concurrency Control

Two enrollment operations are guarded against lost updates because both depend on a financial snapshot that background recomputations can silently invalidate. Activating an enrollment requires the request to carry `expected_enrollment_version`, an integer that must equal the target enrollment's current `version`. If another writer has advanced the enrollment's version since the client last read it — for example, a charge reversal or an aid application that cascaded a balance recompute and bumped the version between the client's read and the activate call — the client's snapshot of the financed principal is stale and the schedule it expects no longer matches; the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). Withdrawing an enrollment likewise requires `expected_enrollment_version` to match the enrollment's current `version`; if a settled installment payment or a charge reversal has since bumped the version, the `paid_principal_cents` the client assumed when computing the expected refund is stale, and the withdrawal is rejected with `ERR_STALE_VERSION` (HTTP 412). These are the only two endpoints that accept a version field. No other endpoint takes `expected_enrollment_version`, and none performs a version check.

### 2.8. Status Codes and Resource Lifecycle Consistency

Creating a brand-new resource returns HTTP 201; every other successful mutation — state transitions, settlements, recomputations — returns HTTP 200. State-machine mutations cascade across the hierarchy: when a child resource changes in a way that affects a parent's derived totals or eligibility, the parent is recomputed in the same operation, with its `updated_at` and `version` advanced accordingly. The detailed cascade rules — how an installment reaching `PAID` may bubble an enrollment to `COMPLETED`, how a withdrawal cancels remaining installments and releases holds, how curing delinquency clears a hold — are specified alongside the workflows in Section 3.

### 2.9. The Conserved-Principal Ledger Principle

The financial heart of the system is a single conserved quantity per enrollment: the net tuition principal owed after aid. An enrollment derives `gross_charges_cents` as the sum of `amount_cents` over its charges in `POSTED` status, `total_aid_cents` as the sum of `amount_cents` over its aid records in `APPLIED` status, and `net_after_aid_cents` as the greater of zero and `gross_charges_cents` minus `total_aid_cents`. From the moment of activation, that net principal is split into a `down_payment_cents` collected up front and a `financed_principal_cents` spread across installments, and the installment schedule always sums exactly to the financed principal. Whenever charges or aid change while the plan is active, the difference is re-spread across the still-open installments so the ledger remains internally consistent: the still-owed financed amount, the paid principal, and the scheduled installments always reconcile. The exact re-spread mechanics are given in Section 3.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Institution, Its Terms, and Its Plan Templates

Before any student can be financed, a `Registrar` establishes the institution's scaffolding. Creating an `Institution` supplies its `name` and optionally its `currency` and `refund_policy`; the institution's logical clock starts at the epoch and is moved forward only through the admin-only test-driving capability, which accepts a `to_iso8601` instant and sets `clock_utc` to it (this capability does not itself run any delinquency sweep). 

An `AcademicTerm` belongs to an institution and is created with an `institution_id`, a `code` (a term code such as `FALL2026`, which must be unique among that institution's terms whose `status` is `OPEN` or `LOCKED`), and four dates: `term_start` (the first, inclusive day of the term), `term_end` (the last, inclusive day), `enroll_open`, and `enroll_close`. The term's length in days, `term_total_days`, is the whole number of days from `term_start` to `term_end` computed as the floor of their difference in days plus one, and it must be at least 1; if `term_end` precedes `term_start` so that this length would be below 1, or more generally if the windows are malformed, creation is rejected with `ERR_INVALID_TERM_WINDOW`. The enrollment window must also be well-formed: `enroll_open` must be at or before `enroll_close`, and `enroll_close` must be at or before `term_end`; a violation of that ordering is the same `ERR_INVALID_TERM_WINDOW`. A term begins in `OPEN` status, which accepts new enrollment activations. A `Registrar` may lock a term, moving it `OPEN → LOCKED`; the lock requires the term to currently be `OPEN` (otherwise `ERR_INVALID_STATE`) and blocks creation of new enrollment activations against it while existing enrollments continue to be serviced. A locked term may then be closed, moving it `LOCKED → CLOSED`; closing requires the term to currently be `LOCKED` (otherwise `ERR_INVALID_STATE`) and additionally requires that no enrollment on the term is in `PENDING` or `ACTIVE` status while still carrying a positive `scheduled_balance_cents` — if any serviced enrollment retains an open scheduled balance, the close is rejected with `ERR_TERM_HAS_OPEN_BALANCES`. `CLOSED` is terminal.

A `PlanTemplate` also belongs to an institution and captures the fee terms a future enrollment will adopt. It is created with an `institution_id`, a `name` (a label such as `4-PAY`), an `installment_count` — the number of financed installments, which must be an integer of at least 1 and at most 12 — a `down_payment_pct` — the fraction of net-after-aid collected up front, which must be at least 0 and at most 0.5 — and a `plan_fee_cents`, a flat non-refundable enrollment fee collected at activation, which must be at least 0. If `installment_count` falls outside one through twelve, or `down_payment_pct` falls outside zero through one-half, the template is rejected with `ERR_INVALID_PLAN_TEMPLATE`. Two optional terms round out a template: `late_fee_grace_days`, the number of days after an installment's due date before it may become overdue and accrue a late fee (defaulting to 3 and required to be at least 0), and `autopay_required`, a flag (defaulting to false) that, when true, forces every enrollment on the template to activate with autopay turned on. A template starts in `ACTIVE` status. A `Registrar` may retire a template, moving it `ACTIVE → RETIRED`; retiring requires the template to currently be `ACTIVE` (otherwise `ERR_INVALID_STATE`). A `RETIRED` template can no longer back a new enrollment activation, which is rejected with `ERR_TEMPLATE_RETIRED`, though fee snapshots already taken onto previously-activated enrollments are unaffected.

### 3.2. Registering Students and Building a Pending Enrollment

A `Student` record belongs to an institution and is created with an `institution_id`, an `external_ref` (the registrar's student identifier, unique per institution), a `full_name`, and an `email`. Each student also carries a computed `has_active_hold` flag, false at creation, which is true exactly when the student has any hold in `ACTIVE` status. That flag gates registrar-side and student-side write actions on the student's enrollments, as detailed below.

A `Registrar` opens a financing relationship by creating an `Enrollment`, which belongs to a `Student` and is created with a `student_id`, a `term_id` naming the `AcademicTerm` it finances, a `plan_template_id` naming the `PlanTemplate` whose fee terms it will adopt, and an optional `autopay_enabled` flag (defaulting to false) declaring whether installments are to be auto-charged on their due dates. A freshly created enrollment is in `PENDING` status and has no installments yet — it is merely a container awaiting the charges, aid, and activation that turn it into a serviced plan.

An enrollment exposes a rich set of computed ledger fields that are meaningless until activation but are always present on the resource: `installment_count`, `down_payment_pct`, and `plan_fee_cents` (snapshots taken from the template at activation), `gross_charges_cents`, `total_aid_cents`, `net_after_aid_cents`, `down_payment_cents`, `financed_principal_cents`, `scheduled_balance_cents`, `paid_principal_cents`, `late_fee_balance_cents`, and `delinquent_installment_count`. Reading an enrollment returns all of these together with its `version`, which clients capture for the optimistic-concurrency checks on activation and withdrawal.

### 3.3. Posting Charges and Applying Aid

Tuition and fees enter an enrollment as charges. A `Registrar` posts a `Charge` against an enrollment by supplying its `enrollment_id`, a `kind` of `TUITION`, `FEE`, or `HOUSING` (an informational category), and an `amount_cents` that must be strictly greater than zero — a non-positive amount is rejected with `ERR_INVALID_AMOUNT`. A new charge is in `POSTED` status, and posting it recomputes the enrollment's `gross_charges_cents` and `net_after_aid_cents`. A `Registrar` may reverse a posted charge, moving it `POSTED → REVERSED`; reversal requires the charge to currently be `POSTED` (otherwise `ERR_INVALID_STATE`) and requires the parent enrollment to be in `PENDING` or `ACTIVE` status (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`). A `POSTED` charge contributes to `gross_charges_cents`; once `REVERSED` it is excluded, and the reversal recomputes `gross_charges_cents` and `net_after_aid_cents`.

Financial aid offsets charges symmetrically. A `Registrar` applies a `FinancialAid` record against an enrollment by supplying its `enrollment_id`, a `source` of `GRANT`, `SCHOLARSHIP`, or `LOAN` (informational), and an `amount_cents` that must be strictly greater than zero, again rejected with `ERR_INVALID_AMOUNT` if not. A new aid record is in `APPLIED` status and reduces `net_after_aid_cents`; applying it recomputes `total_aid_cents` and `net_after_aid_cents`. A `Registrar` may cancel an applied aid record, moving it `APPLIED → CANCELLED`; cancellation requires the aid to currently be `APPLIED` (otherwise `ERR_INVALID_STATE`) and the parent enrollment to be in `PENDING` or `ACTIVE` status (otherwise `ERR_ENROLLMENT_NOT_ACTIVE`). An `APPLIED` aid record reduces `net_after_aid`; once `CANCELLED` it is excluded, and the cancellation recomputes `total_aid_cents` and `net_after_aid_cents`.

While the enrollment is still `PENDING`, these charge and aid mutations simply re-derive the net principal and wait. Once the enrollment is `ACTIVE`, however, each charge or aid change also re-spreads the resulting delta across the open installments, as Section 3.5 describes.

### 3.4. Activating an Enrollment and Laying Down the Schedule

Activation is the pivotal event that converts a `PENDING` enrollment into a serviced plan. A `Registrar` activates an enrollment, transitioning it `PENDING → ACTIVE`. The request must carry `expected_enrollment_version` matching the enrollment's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Activation is guarded by a sequence of preconditions, each tied to its own error. The enrollment must currently be `PENDING`, or the attempt is rejected with `ERR_INVALID_STATE`. The financing term must be `OPEN`; if the `AcademicTerm` is not `OPEN`, activation is rejected with `ERR_TERM_NOT_OPEN`. The institution's logical clock must fall within the inclusive enrollment window, at or after `enroll_open` and at or before `enroll_close`; outside that window, activation is rejected with `ERR_OUTSIDE_ENROLL_WINDOW`. The referenced plan template must be `ACTIVE`, or the attempt is rejected with `ERR_TEMPLATE_RETIRED`. The student must not be on hold — `has_active_hold` must be false — or the attempt is rejected with `ERR_STUDENT_ON_HOLD`. The enrollment must have something to finance: `gross_charges_cents` must be strictly greater than zero, or the attempt is rejected with `ERR_NO_CHARGES_TO_FINANCE`. And if the plan template's `autopay_required` is true, the enrollment's `autopay_enabled` must be true, or the attempt is rejected with `ERR_AUTOPAY_REQUIRED`.

When these checks pass, activation does several things in one atomic step. It snapshots `installment_count`, `down_payment_pct`, and `plan_fee_cents` from the plan template onto the enrollment. It then runs the **installment schedule** calculation to compute the down payment and the financed split and to lay down the installment rows, recomputes `net_after_aid_cents` and `scheduled_balance_cents`, and increments the enrollment's `version` by one.

The installment schedule is computed as follows, all in whole cents. First, the net principal is the greater of zero and `gross_charges_cents` minus `total_aid_cents`. The `down_payment_cents` is that net principal multiplied by `down_payment_pct`, rounded half up to whole cents — and this rounding happens *first*, before any flooring of the financed split; once computed at activation, `down_payment_cents` is immutable. The `financed_principal_cents` is the net principal minus the down payment. Let the snapshot `installment_count` be the number of installments. The per-installment base amount is the financed principal divided by the installment count, rounded down to a whole number (floored). The remainder is the financed principal minus the base times the installment count, a value at least zero and strictly less than the installment count. The installments are created with a 1-based `sequence_index`, and each installment's `amount_cents` is the base plus one additional cent for every installment whose sequence position is less than or equal to the remainder — that is, the leftover cents are distributed one each onto the *earliest* installments by sequence order. By construction the installment amounts sum to exactly the financed principal. The cadence in days between due dates is `term_total_days` divided by the installment count plus one, rounded down to a whole number; each installment's `due_date` is `term_start` plus its sequence position multiplied by that cadence in days. Only charges in `POSTED` status and aid in `APPLIED` status as of activation time feed this calculation.

Each created `Installment` belongs to the enrollment, carries its `enrollment_id`, its `sequence_index`, its `due_date`, its `amount_cents`, a `paid_amount_cents` that begins at 0, and a `status` of `SCHEDULED`. It accumulates `paid_amount_cents` as settled payments are applied to it, as Section 3.6 describes.

### 3.5. Re-Spreading the Balance When Charges or Aid Change

The system never recollects the down payment on a mid-term adjustment; instead it re-spreads the *change* in financed principal across the installments that are still open. The two recalculation engines — one driven by the charge ledger, one by the aid ledger — share the same arithmetic but differ in the sign of the change they introduce, and both run only while the enrollment is `ACTIVE`.

Consider first a charge change. Posting a new charge against an active enrollment raises the net principal, a positive delta; reversing a posted charge lowers it, a negative delta. The delta in financed principal is the new `net_after_aid` minus the old `net_after_aid`. The installments eligible to absorb the delta are exactly those still in `SCHEDULED` status, taken in ascending `sequence_index` order; installments already `PAID` or already `OVERDUE` are frozen at their current `amount_cents` and never touched. If there are no scheduled installments left to absorb the change, the operation is rejected with `ERR_NO_SCHEDULED_INSTALLMENTS`. For a non-negative delta, the system computes a base as the delta divided by the count of scheduled installments rounded down, and a remainder as the delta minus the base times that count; it then adds the base to every scheduled installment and one extra cent to each of the earliest installments up to the remainder — leftover cents land on the *earliest* scheduled installments. For a negative delta, the system takes the magnitude of the credit and walks the scheduled installments from the *latest* sequence index backward, reducing each installment's `amount_cents` by as much of the remaining credit as that installment holds (never below zero), and stopping once the credit is exhausted — reductions come off the *latest* installments first. After the re-spread, `scheduled_balance_cents` is recomputed as the sum of `amount_cents` over the scheduled installments plus the sum over any overdue installments.

Aid changes drive the same engine with the opposite directional meaning. Because aid reduces what is owed, *applying* aid is a negative delta to the financed principal (it reduces owed, so the credit comes off the latest installments backward), while *cancelling* aid is a positive delta (it increases owed, spread base-plus-remainder onto the earliest scheduled installments). The signed delta is again the new `net_after_aid` minus the old `net_after_aid`, the eligible set is again only the `SCHEDULED` installments in ascending `sequence_index`, and the same `ERR_NO_SCHEDULED_INSTALLMENTS` guards the case where no scheduled installment remains to receive the adjustment. The conserved-quantity adjustment for a given magnitude of aid is exactly opposite in direction to the same-magnitude charge.

### 3.6. Collecting Payments and Driving Installments to Paid

Payments flow against an enrollment's ledger. A `Bursar` or a `Student` creates a `Payment` by supplying its `enrollment_id`, a `purpose` of `DOWN_PAYMENT`, `INSTALLMENT`, or `AUTOPAY`, an `amount_cents` that must be strictly greater than zero (otherwise `ERR_INVALID_AMOUNT`), and — for an installment or autopay payment — an `installment_id` naming the target installment; the `installment_id` is omitted when the purpose is `DOWN_PAYMENT`. A `DOWN_PAYMENT` payment settles the activation down payment due; an `INSTALLMENT` or `AUTOPAY` payment settles one named installment. A newly created payment is in `PENDING` status and changes no balances until it is settled.

A `Bursar` settles a pending payment, moving it `PENDING → SETTLED`, or fails it, moving it `PENDING → FAILED`. Both transitions require the payment to currently be `PENDING`, otherwise `ERR_INVALID_STATE`. Settling additionally requires the parent enrollment to be `ACTIVE`, otherwise `ERR_ENROLLMENT_NOT_ACTIVE`. When the purpose is `DOWN_PAYMENT`, settling requires that the down payment has not already been collected; a second down-payment settlement is rejected with `ERR_DOWN_PAYMENT_ALREADY_PAID`. When the purpose is `INSTALLMENT` or `AUTOPAY`, settling requires the targeted installment to be in `SCHEDULED` or `OVERDUE` status; settling against an installment in any other status is rejected with `ERR_INSTALLMENT_NOT_PAYABLE`. Settling a `DOWN_PAYMENT` marks the down payment collected and adds `down_payment_cents` to `paid_principal_cents`. Settling an `INSTALLMENT` or `AUTOPAY` payment adds the payment's `amount_cents` to the target installment's `paid_amount_cents`; if the cumulative `paid_amount_cents` then reaches or exceeds the installment's `amount_cents`, the installment is driven to `PAID`. Failing a payment makes no ledger change; note that a failed autopay attempt for an installment already past its grace window may later be swept into `OVERDUE` by a delinquency run.

An installment reaches `PAID` from either `SCHEDULED` or `OVERDUE` when its cumulative `paid_amount_cents` is at least its `amount_cents`. Reaching `PAID` recomputes the enrollment's `scheduled_balance_cents` and `paid_principal_cents`. The `scheduled_balance_cents` is the sum of `amount_cents` over installments in `SCHEDULED` or `OVERDUE` status — the still-owed financed amount — and `paid_principal_cents` is the sum of `amount_cents` over `PAID` installments plus the `down_payment_cents` once it has been collected. When an `OVERDUE` installment reaches `PAID`, the enrollment's `delinquent_installment_count` is decremented and the delinquency evaluation re-runs (potentially releasing a hold, as Section 3.8 covers). Whenever the last open installment is paid so that every installment is `PAID` and the down payment has been collected, the system automatically bubbles the enrollment `ACTIVE → COMPLETED`; on completion `scheduled_balance_cents` is zero, and if the student has an `ACTIVE` hold whose `enrollment_id` is this enrollment, that hold is released (`ACTIVE → RELEASED`) and `has_active_hold` is recomputed.

### 3.7. Delinquency Sweeps and Tiered Late Fees

Overdue detection is driven by the logical clock and triggered by a `Registrar` running a delinquency sweep on an enrollment (the same effect can occur on a clock advance handled by the system). The sweep walks the enrollment's installments and moves any still-unpaid one whose due date plus grace has passed into `OVERDUE`. Precisely, a `SCHEDULED` installment becomes `OVERDUE` when the whole-day value of `clock_utc` is strictly greater than the whole-day value of its `due_date` plus the template's `late_fee_grace_days`, and its `paid_amount_cents` is still less than its `amount_cents`. Each installment swept `SCHEDULED → OVERDUE` runs the late-fee assessment, increments the enrollment's `delinquent_installment_count`, and runs the delinquency evaluation that may raise a hold.

The **late fee assessment** computes a `LateFee` for the newly-overdue installment. The overdue amount is the installment's `amount_cents` minus its `paid_amount_cents`. The `days_late` recorded on the fee is the whole-day value of `clock_utc` minus the whole-day value of the `due_date`. The fee's percentage tier is chosen by `days_late`: if `days_late` is less than 1 the fee is zero; if `days_late` is at least 1 and less than 10 the rate is 2 percent; if `days_late` is at least 10 and less than 30 the rate is 4 percent; and if `days_late` is at least 30 the rate is 6 percent. The percentage term is the overdue amount times the chosen rate, rounded half up to whole cents. The candidate fee is then the larger of a flat floor of 2,500 cents and that percentage term. That candidate is clamped into a band: at least the minimum of 2,500 cents and at most the maximum of 7,500 cents (the lower clamp coincides with the flat floor, the upper clamp caps any single fee). Finally a per-enrollment aggregate cap applies: the running `late_fee_balance_cents` may never exceed a total of 30,000 cents across the enrollment, so the remaining cap headroom is 30,000 cents minus the current `late_fee_balance_cents`, and the assessed fee is the larger of zero and the smaller of the clamped fee and that remaining headroom — meaning the cap can reduce a fee, even to zero, once the enrollment has accumulated 30,000 cents of late fees. A created `LateFee` belongs to the enrollment, carries its `enrollment_id`, the `installment_id` of the overdue installment that triggered it, the `days_late`, the computed `amount_cents`, and a `status` of `ASSESSED`. An `ASSESSED` fee adds to `late_fee_balance_cents`.

A `Registrar` may waive an assessed late fee, moving it `ASSESSED → WAIVED`; the waive requires the fee to currently be `ASSESSED`, otherwise `ERR_INVALID_STATE`. Waiving recomputes `late_fee_balance_cents` as the sum of `amount_cents` over the enrollment's fees still in `ASSESSED` status, so the waived fee is removed from the balance exactly as a compensating reversal.

### 3.8. Holds: Raising and Clearing Delinquency Blocks

Whenever delinquency changes — an installment going overdue, an overdue installment being paid, or an enrollment being withdrawn — the system runs a **delinquency evaluation** against two thresholds. The count of overdue installments is the enrollment's `delinquent_installment_count`. The total overdue amount is the sum, over installments in `OVERDUE` status, of each installment's `amount_cents` minus its `paid_amount_cents`. Delinquency is considered tripped when the overdue count is at least 3, or the total overdue amount is at least 150,000 cents — either threshold suffices. If delinquency is tripped and the enrollment has no `ACTIVE` hold, the system creates a `Hold` in `ACTIVE` status and sets the student's `has_active_hold` to true. The hold's `reason` is `DELINQUENCY_COUNT` when the count threshold is met and `DELINQUENCY_AMOUNT` otherwise. Conversely, if delinquency is no longer tripped and an `ACTIVE` hold for the enrollment exists, the system releases that hold (`ACTIVE → RELEASED`) and recomputes `has_active_hold`.

A `Hold` belongs to a `Student`, carries its `student_id`, the `enrollment_id` of the delinquent enrollment that raised it, its `reason`, and its `status`. While `ACTIVE`, a hold sets `has_active_hold` on the student; once `RELEASED`, it no longer does, and `has_active_hold` is recomputed from any remaining active holds. A `Registrar` may manually release a hold, moving it `ACTIVE → RELEASED`; the manual release requires the hold to currently be `ACTIVE`, otherwise `ERR_INVALID_STATE`, and is permitted only when delinquency has actually been cured — that is, only when the `delinquent_installment_count` is below 3 and the total overdue amount is below 150,000 cents. A manual release attempted while either threshold is still met is rejected with `ERR_DELINQUENCY_UNRESOLVED`. Releasing recomputes `has_active_hold` from the student's remaining active holds. An active hold on a student gates write actions on that student's enrollments: with `has_active_hold` true, an attempt to activate an enrollment or to post a charge for that student is rejected with `ERR_STUDENT_ON_HOLD`.

### 3.9. Withdrawal and Refund Proration

When a student leaves mid-term, a `Registrar` withdraws the enrollment, transitioning it `ACTIVE → WITHDRAWN`. The request must carry `expected_enrollment_version` matching the enrollment's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Withdrawal requires the enrollment to currently be `ACTIVE`, otherwise `ERR_INVALID_STATE`. The request also supplies an `effective_date`, the date the withdrawal takes effect.

Withdrawal creates a `Withdrawal` record and runs the **refund proration** to settle accounts. The proration first establishes how far into the term the withdrawal lands. The effective date is clamped to the inclusive range from `term_start` to `term_end`, and `days_elapsed` is the whole number of days from `term_start` to that clamped date, computed as the floor of their difference in days plus one. The fraction of the term elapsed is `days_elapsed` divided by `term_total_days`. The institution's `refund_policy`, copied onto the withdrawal as `variant_used`, selects how much of gross charges the institution retains. Under the `DATE_BASED` variant, the retained charges are a continuous day-proportional fraction: `gross_charges_cents` multiplied by `days_elapsed` divided by `term_total_days`, rounded half up to whole cents. Under the `SCHEDULE_BASED` variant, the retained charges are a step function of `days_elapsed`: the institution retains 0 percent when `days_elapsed` is at most 7, 25 percent when `days_elapsed` is at least 8 and at most 21, 50 percent when `days_elapsed` is at least 22 and at most 42, and 100 percent when `days_elapsed` is greater than 42; the retained amount is `gross_charges_cents` multiplied by that bracket percentage, rounded half up to whole cents. For the same inputs, the two variants generally yield different retained amounts. The result is recorded as `retained_charges_cents`.

The settlement common to both variants then computes two figures. The `net_owed_after_withdrawal_cents` is the greater of zero and `retained_charges_cents` minus `total_aid_cents` minus `paid_principal_cents` — what the student still owes after retained charges are offset by aid and by what has already been paid. The `refund_to_student_cents` is the greater of zero and `paid_principal_cents` minus the greater of zero and (`retained_charges_cents` minus `total_aid_cents`) — the cash returned to the student when prior payments exceed the aid-offset retained charges. These satisfy a cash invariant: `paid_principal_cents` equals `refund_to_student_cents` plus the smaller of `paid_principal_cents` and the greater of zero and (`retained_charges_cents` minus `total_aid_cents`).

Withdrawal then cascades through three hops in one operation. First, every installment on the enrollment still in `SCHEDULED` or `OVERDUE` status is cancelled, in the sense that those amounts no longer count toward the scheduled balance — the `WITHDRAWN` parent removes them from `scheduled_balance_cents`. Second, any cancelled installment that was `OVERDUE` and still carried an `ASSESSED` late fee leaves that late fee `ASSESSED`: late fees survive withdrawal and remain owed. Third, the enrollment's `delinquent_installment_count` is recomputed to zero, and because that falls below the delinquency thresholds, any `ACTIVE` hold for this enrollment is released (`ACTIVE → RELEASED`) and the student's `has_active_hold` is recomputed. Finally, the withdrawal increments the enrollment's `version` by one. The resulting `Withdrawal` carries its `enrollment_id`, the `effective_date`, the `variant_used`, the `retained_charges_cents`, the `net_owed_after_withdrawal_cents`, and the `refund_to_student_cents`. `WITHDRAWN` is terminal for the enrollment, as is `COMPLETED`.

### 3.10. Validation Ordering Across Endpoints

Across all endpoints the system evaluates checks in a fixed priority order so that the most fundamental failures surface first and a deeper rule never masks a shallower one. User-context header validity is checked first; a missing or malformed `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Role authorization is checked next; a role not permitted for the endpoint yields `ERR_FORBIDDEN_FOR_ROLE`. Then path resource existence is checked left-to-right within the institution, yielding `ERR_NOT_FOUND` for the first missing identifier. Then request-body well-formedness is checked on create endpoints — amounts strictly positive, enum members valid, plan-template integer and fraction in range — yielding `ERR_INVALID_REQUEST` (and the amount-specific `ERR_INVALID_AMOUNT`, term-window `ERR_INVALID_TERM_WINDOW`, and template `ERR_INVALID_PLAN_TEMPLATE` for those specific malformations). Then, on state-transition endpoints, the target resource's state is checked, yielding `ERR_INVALID_STATE` when the transition is not allowed from the current state. The remaining business rules are then evaluated.

Two endpoints layer several business rules whose relative order matters. On enrollment activation, after the generic checks above, the student-hold check comes before the term/window checks: an active hold yields `ERR_STUDENT_ON_HOLD`, and only then are the temporal checks evaluated, where a non-`OPEN` term yields `ERR_TERM_NOT_OPEN` and is itself ahead of the enrollment-window check that yields `ERR_OUTSIDE_ENROLL_WINDOW`; the autopay-required check (`ERR_AUTOPAY_REQUIRED`) and the charges-to-finance check (`ERR_NO_CHARGES_TO_FINANCE`) follow, and the optimistic-concurrency check on `expected_enrollment_version` (`ERR_STALE_VERSION`) is the version guard on the transition. On payment settlement, the down-payment-already-collected check (`ERR_DOWN_PAYMENT_ALREADY_PAID`) precedes the installment-payability check (`ERR_INSTALLMENT_NOT_PAYABLE`). Term closing applies its open-balance check (`ERR_TERM_HAS_OPEN_BALANCES`) after confirming the term is `LOCKED`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. State transitions and other modifications to existing resources — activation, withdrawal, settlement, reversal, cancellation, locking, closing, retiring, waiving, releasing, clock-setting, and delinquency sweeps — return a `200 OK` status code. The request and response payloads, side effects, and business preconditions for each endpoint are specified in the Section 3 narratives; the table below lists only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/institutions` | Create an institution | Registrar |
| GET | `/institutions/{institutionId}` | Get an institution | Registrar, Bursar, Student |
| POST | `/institutions/{institutionId}/_clock/set_current_utc` | Set the institution clock to a UTC instant (test-driving) | Registrar |
| POST | `/institutions/terms` | Create an academic term | Registrar |
| GET | `/institutions/terms/{termId}` | Get a term | Registrar, Bursar, Student |
| GET | `/institutions/terms` | List terms | Registrar, Bursar, Student |
| POST | `/institutions/terms/{termId}/lock` | Lock a term against new enrollments | Registrar |
| POST | `/institutions/terms/{termId}/close` | Close a term | Registrar |
| POST | `/institutions/students` | Create a student | Registrar |
| GET | `/institutions/students/{studentId}` | Get a student | Registrar, Bursar, Student |
| GET | `/institutions/students` | List students | Registrar, Bursar, Student |
| POST | `/institutions/plan-templates` | Create a plan template | Registrar |
| GET | `/institutions/plan-templates/{planTemplateId}` | Get a plan template | Registrar, Bursar, Student |
| GET | `/institutions/plan-templates` | List plan templates | Registrar, Bursar, Student |
| POST | `/institutions/plan-templates/{planTemplateId}/retire` | Retire a plan template | Registrar |
| POST | `/institutions/enrollments` | Create a pending enrollment | Registrar |
| GET | `/institutions/enrollments/{enrollmentId}` | Get an enrollment | Registrar, Bursar, Student |
| GET | `/institutions/enrollments` | List enrollments | Registrar, Bursar, Student |
| POST | `/institutions/enrollments/{enrollmentId}/activate` | Activate an enrollment | Registrar |
| POST | `/institutions/enrollments/{enrollmentId}/withdraw` | Withdraw an enrollment | Registrar |
| POST | `/institutions/enrollments/{enrollmentId}/run-delinquency` | Sweep delinquency on an enrollment | Registrar |
| GET | `/institutions/installments/{installmentId}` | Get an installment | Registrar, Bursar, Student |
| GET | `/institutions/installments` | List installments | Registrar, Bursar, Student |
| POST | `/institutions/charges` | Post a charge against an enrollment | Registrar |
| GET | `/institutions/charges/{chargeId}` | Get a charge | Registrar, Bursar, Student |
| GET | `/institutions/charges` | List charges | Registrar, Bursar, Student |
| POST | `/institutions/charges/{chargeId}/reverse` | Reverse a posted charge | Registrar |
| POST | `/institutions/aids` | Apply financial aid to an enrollment | Registrar |
| GET | `/institutions/aids/{aidId}` | Get an aid record | Registrar, Bursar, Student |
| GET | `/institutions/aids` | List aid records | Registrar, Bursar, Student |
| POST | `/institutions/aids/{aidId}/cancel` | Cancel an applied aid | Registrar |
| POST | `/institutions/payments` | Create a pending payment | Bursar, Student |
| GET | `/institutions/payments/{paymentId}` | Get a payment | Registrar, Bursar, Student |
| GET | `/institutions/payments` | List payments | Registrar, Bursar, Student |
| POST | `/institutions/payments/{paymentId}/settle` | Settle a pending payment | Bursar |
| POST | `/institutions/payments/{paymentId}/fail` | Fail a pending payment | Bursar |
| GET | `/institutions/late-fees/{lateFeeId}` | Get a late fee | Registrar, Bursar, Student |
| GET | `/institutions/late-fees` | List late fees | Registrar, Bursar, Student |
| POST | `/institutions/late-fees/{lateFeeId}/waive` | Waive an assessed late fee | Registrar |
| GET | `/institutions/holds/{holdId}` | Get a hold | Registrar, Bursar, Student |
| GET | `/institutions/holds` | List holds | Registrar, Bursar, Student |
| POST | `/institutions/holds/{holdId}/release` | Release a hold | Registrar |
| GET | `/institutions/withdrawals/{withdrawalId}` | Get a withdrawal | Registrar, Bursar, Student |
| GET | `/institutions/withdrawals` | List withdrawals | Registrar, Bursar, Student |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_AMOUNT` | 400 |
| `ERR_INVALID_TERM_WINDOW` | 400 |
| `ERR_INVALID_PLAN_TEMPLATE` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERM_NOT_OPEN` | 409 |
| `ERR_OUTSIDE_ENROLL_WINDOW` | 409 |
| `ERR_TEMPLATE_RETIRED` | 409 |
| `ERR_STUDENT_ON_HOLD` | 409 |
| `ERR_NO_CHARGES_TO_FINANCE` | 409 |
| `ERR_AUTOPAY_REQUIRED` | 409 |
| `ERR_ENROLLMENT_NOT_ACTIVE` | 409 |
| `ERR_DOWN_PAYMENT_ALREADY_PAID` | 409 |
| `ERR_INSTALLMENT_NOT_PAYABLE` | 409 |
| `ERR_NO_SCHEDULED_INSTALLMENTS` | 409 |
| `ERR_DELINQUENCY_UNRESOLVED` | 409 |
| `ERR_TERM_HAS_OPEN_BALANCES` | 409 |
| `ERR_STALE_VERSION` | 412 |

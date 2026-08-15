# Payroll Garnishment Wage Orders API — Product Requirements Document

## 1. Introduction

Employers operate under a legal obligation that most payroll teams experience as pure risk: when a court, a child-support agency, or a federal or state agency serves a wage withholding order, the employer must begin deducting the correct amount from the correct paycheck, notify the employee within a statutory window, answer the issuing authority before its deadline, and remit the withheld funds on time — all while never withholding more than state law allows from an employee's disposable earnings. Errors in either direction carry consequences: under-withholding exposes the employer to the employee's debt, and over-withholding exposes it to wage claims.

This document specifies an API for managing that obligation end to end. The system records employers and their payroll calendars, maintains per-state withholding rules, receives garnishment orders from issuing authorities, walks each order through a legal pipeline from receipt to satisfaction or termination, and — at the moment a payroll run is paid — executes a priority-ordered withholding waterfall that respects protected income floors, per-order-type caps, proration for mid-period effective dates, and a child-support non-compete rule against creditor orders. Withheld funds are swept into per-authority remittances with computed due dates, confirmed under segregation of duties, corrected through append-only refunds, and preserved in a hash-chained audit trail that a read-only compliance role can independently verify.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's capacity. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly four roles, spelled as follows: `employer_payroll_admin`, `payroll_specialist`, `payroll_manager`, and `compliance_auditor`. Attempting an operation outside one's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

An `employer_payroll_admin` is the employer-level administrator: it configures employers, state rules, and issuing authorities, and it alone owns the logical clock. A `payroll_specialist` runs day-to-day operations — order intake, validation, notification, activation, payroll runs, pay statements, and remittance creation. A `payroll_manager` handles the legally sensitive half of the lifecycle: employee terminations, court answers, suspensions and resumptions, order terminations, refunds, and remittance confirmation or cancellation. A `compliance_auditor` is strictly read-only and exists to inspect records and verify the audit chain. Employee creation is the one write shared across two roles: both an `employer_payroll_admin` and a `payroll_specialist` may perform it. Read access is otherwise broad — every retrieval endpoint is available to all four roles, with a single exception: the employer-scoped audit-log listing is restricted to `employer_payroll_admin`, `payroll_manager`, and `compliance_auditor`.

None of the four roles ties `X-User-ID` to a persisted entity. When `X-User-Role` is `employer_payroll_admin`, `payroll_specialist`, `payroll_manager`, or `compliance_auditor`, `X-User-ID` is an opaque operator identifier; the server records it on audit entries as the actor (see §2.11) and compares it for segregation-of-duties enforcement (see §2.10), but it is never matched against any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of returned items: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400); out-of-range values are not rejected but clamped — a `limit` below 1 is treated as 1 and above 100 as 100, and a negative `offset` is treated as 0. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, with `has_more` true exactly when `offset` plus the number of returned items is less than `total_count`.

Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order.

### 2.4. The Logical Clock

Legal deadlines in this domain cannot be left to wall-clock time. The system therefore maintains a single logical clock, and every timestamp that drives a deadline or an ordering decision — an order's `received_at`, an event's `created_logical_at`, a notification's `notification_sent_at`, a remittance's `confirmed_at`, and every due-date comparison — reads from that clock. At server startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`; it must never fall back to wall-clock time. An `employer_payroll_admin` may advance the logical clock through a test-driving capability that accepts a `to_iso8601` instant; the supplied instant is accepted verbatim, with no monotonicity check — the clock may be moved backward as well as forward — and the response echoes the server's own reading of the new `current_utc`.

### 2.5. Common Resource Properties

Primary resources — employers, employees, payroll runs, pay statements, issuing authorities, garnishment orders, and remittances — share a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, stamped from the logical clock (§2.4).
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource, likewise stamped from the logical clock.
- `version` (integer): a system-managed counter that starts at 1 at creation and increments on every modification, and serves as the basis for optimistic concurrency control (§2.7).

Three entities are deliberately leaner. A `StateRule` is administered configuration, immutable after creation; a `WithholdingEvent` is an append-only ledger entry; an `AuditLogEntry` is an append-only audit record. These three carry only `id` and `created_at` — both `updated_at` and `version` are absent from them.

### 2.6. Money, Precision, and Rounding

All monetary amounts are represented as integer cents — never floating-point dollars. Wherever a calculation produces a fractional cent, the result is rounded half-up to a whole cent. Intermediate multiplications are carried at full precision, and each award line in the withholding waterfall is rounded exactly once, at the end of its own computation (§3.6). The protected-income period floor is likewise rounded half-up to whole cents before it is subtracted from disposable earnings. Date-valued deadlines (an answer due date, a remittance due date) are computed at date granularity; the notification deadline is a datetime.

### 2.7. Optimistic Concurrency Control

Four write operations are guarded by optimistic concurrency control against a parent entity's `version`, and each names its expectation field explicitly:

- Creating an employee requires `expected_employer_version`, carrying the caller's last-observed `version` of the employer. If the employer's current `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Receiving a garnishment order against an employee requires `expected_employee_version`, carrying the caller's last-observed `version` of that employee. Because order intake and order termination both mutate the employee record through a cascade, a client whose view of the employee's order set is stale would make duplicate-priority and duplicate-order decisions on outdated data; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a payroll run requires `expected_employer_version`. The caller's period-window decision — a `period_start` placed strictly after the latest run's `period_end` — was computed from its view of the employer's run history, so a stale view is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Paying a payroll run requires `expected_employer_version`. A prior paid run or a configuration change to the employer (its remittance timing or fee policy) advances the employer's `version`; paying against a stale view risks double-withholding across runs or applying a superseded fee policy, so the pay request is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these four accepts a version field.

### 2.8. Aggregate Hierarchy and Cascading Mutation

The resource topology is a hybrid. An employer roots a tree of employees, payroll runs (and their pay statements), and audit entries; each employee roots its garnishment orders, and each order roots its withholding events. Issuing authorities stand alone as top-level records, and remittances hang beneath authorities while also referencing the employer and the payroll run they settle — a deliberate cross-aggregate link.

Several mutations cascade upward, and every cascade completes atomically inside the triggering request. The employer's `version` is incremented by four events: a configuration update to the employer itself, the creation of an employee beneath it, the payment of one of its payroll runs, and the voiding of one of its payroll runs. The employee's `version` is incremented when a garnishment order is received against it and when one of its orders is terminated (§3.4). Any mutation — including these cascades — refreshes the affected resource's `updated_at`. Orders also carry a denormalized `employer_id` so that employer-scoped filtering does not require walking the employee link, and every withholding event and pay statement likewise records its own `employer_id`.

### 2.9. Nested Resource Retrieval and Validation Order

Requests that target nested resources are validated left to right along the path: the system confirms each identifier exists and belongs to its declared parent chain before examining the next, and the first unknown or out-of-scope identifier rejects the request with `ERR_NOT_FOUND` (HTTP 404). Syntactically malformed payloads — a missing required field, an unrecognized enum value, an unparseable date, or a value violating a field-level constraint such as a non-negativity rule — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unrecognized fields in a request body are ignored. Payload validation runs after the path identifiers have been resolved and before any state or business check. Identifiers carried in the request body (an `employer_id`, an `issuing_authority_id`, an `employee_id`, a `payroll_run_id`) are checked for existence and scope only after any state-legality check, leading the business-rule block, and the first unknown or out-of-scope one rejects with `ERR_NOT_FOUND` (HTTP 404).

When several checks could reject the same request, they fire in a fixed, system-wide order. Authentication comes first, then role authorization, then existence and parent-chain scoping of the path identifiers, then — for remittance confirmation — the segregation-of-duties comparison of §2.10, then state legality: a transition attempted from an illegal state is rejected with `ERR_INVALID_STATE` (HTTP 409), and a terminal-state resource accepts no further transitions, with two exceptions — a `SATISFIED` order may still be terminated (§3.4), and refunds (§3.8) change no `processing_status` and so may target an order in any state. Only then do the business rules engage, and they too are ordered: period-window and pay-calendar temporal checks first, then intake referential checks (authority, case-number pattern, state rule), then duplicate-order safety, then the stale-version rejection of §2.7, then fiscal amount checks (empty runs, deduction bounds), then terminated-employee ineligibility, then refund limits, then the posted-event void guard, then the duplicate-remittance guard, then remittance emptiness, and finally remittable-event availability. A stale employer version on a run payment therefore surfaces as `ERR_STALE_VERSION` rather than being masked by a later deduction-bounds failure, and an unknown employee id surfaces as `ERR_NOT_FOUND` before any state or business rule is consulted.

### 2.10. Segregation of Duties

The role model enforces a deliberate split between the operator who moves money out of paychecks and the operator who vouches for its delivery. A `payroll_specialist` pays runs and creates remittances, but only a `payroll_manager` may confirm or cancel those remittances, file answers, suspend or terminate orders, or issue refunds. The split is enforced down to the individual: the `X-User-ID` that paid a payroll run may not confirm that run's remittances — the confirmer's `X-User-ID` must differ, and a violation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The `compliance_auditor` holds no write capability at all, and employer-level configuration remains the exclusive province of the `employer_payroll_admin`.

### 2.11. The Append-Only Audit Chain

Every mutation in the system appends an `AuditLogEntry`, scoped to an employer. Each entry records the mutated resource's `entity_type` and `entity_id`, an `action` label naming the operation (for example `order.validate` or `run.pay`), the actor's `actor_role` — the `X-User-Role` of the caller, or `SYSTEM` for automatic transitions — and the actor's `actor_id` — the `X-User-ID`, or the literal `system` for automatic work. The entry's `payload_hash` is the SHA-256 hex digest, rendered in lowercase, of the canonical JSON payload — the key-sorted, compact-separator JSON rendering of the entry's `action`, `entity_type`, `entity_id`, `actor_role`, `actor_id`, and a `details` object carrying action-specific context.

Entries are hash-chained per employer. Each entry stores a `prev_hash`: the `entry_hash` of the previous audit entry for that employer, or the literal `GENESIS` for the employer's first entry. The `entry_hash` itself is the lowercase SHA-256 hex digest of the entry's `prev_hash`, its `payload_hash`, and its `created_at`, joined with `|` separators. Entries are immutable — no endpoint updates or deletes them — so any tampering breaks the chain. The audit listing is ordered by `created_at` ascending, with a monotonic sequence disambiguating entries that share a timestamp. A caller may pass the `verify` query flag on the employer-scoped audit listing — the case-insensitive values `true`, `1`, and `yes` count as set — to have the server recompute every `entry_hash` and re-walk every `prev_hash` link; the chain is valid only if every recomputed hash matches its stored value and every link points at its predecessor, and a mismatch is rejected with `ERR_AUDIT_CHAIN_BROKEN` (HTTP 409). When verification is requested and the chain holds, the listing's `meta` carries `chain_valid: true`. The employer-scoped listing filters by `entity_type` and `entity_id`; the global audit listing filters by `employer_id`, `entity_type`, and `entity_id`.

## 3. Business Logic & Workflows

### 3.1. Employer Enrollment and Payroll Configuration

Everything begins when an `employer_payroll_admin` enrolls an employer. The enrollment payload carries the employer's `legal_name` and its `fein`, the federal employer identification number, which must be unique across all employers — a duplicate `fein` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The admin also pins two policies that will shape settlement and net pay. The `remittance_timing` policy — one of `SAME_DAY`, `NEXT_BUSINESS_DAY`, or `THREE_BUSINESS_DAYS` — declares how quickly withheld funds must reach agencies after a pay date. The `administrative_fee_policy` — `NONE` or `PER_ORDER` — declares whether the employer charges a processing fee; under `PER_ORDER`, the `admin_fee_cents` value (an integer number of cents, defaulting to 0 when omitted; a negative value is rejected with `ERR_INVALID_REQUEST`, HTTP 400) is charged per order that received a positive award per paid run (§3.6). Enrollment also records the employer's `payroll_calendar`, an object describing the seed semi-monthly period through three dates: `period_start` and `period_end`, both inclusive, and the `pay_date` on which net pay is disbursed.

Configuration is not frozen at enrollment. An admin may later update `remittance_timing`, `administrative_fee_policy`, or `admin_fee_cents`; each such update increments the employer's `version` and appends an audit entry (action `employer.update`), and the increment, the `updated_at` refresh, and the audit entry apply to every update call, even one whose payload changes none of the three fields. One caveat follows from §3.7: a remittance's due date is computed from the timing policy in force at the remittance's creation, so a later configuration change never moves an existing remittance's deadline.

Two bodies of reference data must exist before orders can flow. First, an admin registers each issuing authority with a `name`, an `authority_type` of `COURT`, `CHILD_SUPPORT_AGENCY`, `FEDERAL_AGENCY`, or `STATE_AGENCY`, the `state_code` of its jurisdiction, and an `accepted_case_number_pattern` — a regular expression against which every order's case number is checked at intake; a pattern that does not compile as a regular expression is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Second, an admin creates a `StateRule` per state, keyed by a unique `state_code`. A state rule carries `caps`, an object mapping each order type to the maximum fraction of disposable earnings that may be withheld from it (California-style defaults illustrate the shape: 0.50 for `CHILD_SUPPORT`, 0.65 for `FEDERAL_TAX_LEVY`, 0.15 for `STUDENT_LOAN`, and 0.25 for `CREDITOR`, with actual values varying by state). It also carries the `min_wage_multiplier` used to build the protected weekly floor, an `hourly_floor_cents` used by hourly-test states such as Texas, and a `fee_deductible_from_wages` flag declaring whether the employer's administrative fee may come out of the employee's net pay. All four fields are required: `caps` must carry a numeric, non-negative fraction for each of the four order types, `min_wage_multiplier` must be a non-negative number, `hourly_floor_cents` a non-negative integer, and `fee_deductible_from_wages` a boolean; a violation is rejected with `ERR_INVALID_REQUEST` (HTTP 400). State rules are immutable once created, and because the `state_code` key is unique, a second create for an existing state is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.2. Employee Rosters and Separation

With an employer enrolled, an `employer_payroll_admin` or a `payroll_specialist` builds the roster. Creating an employee takes the owning `employer_id`, the employee's `full_name`, the `work_state_code` whose state rule will govern that employee's withholding caps, a `pay_frequency` of `WEEKLY`, `BIWEEKLY`, `SEMIMONTHLY`, or `MONTHLY` used to normalize the federal minimum-wage floor to the pay period, an `hourly_rate_cents` — a required, non-negative integer at creation (a missing or negative value is rejected with `ERR_INVALID_REQUEST`, HTTP 400) that is consulted only for employees whose `work_state_code` is `TX` and ignored for everyone else — and, because this create is OCC-guarded per §2.7, an `expected_employer_version`. Employee creation cascades: the employer's `version` increments, and an audit entry (action `employee.create`) is appended. Employees are retrievable individually, per employer, or through a filtered listing accepting `employer_id`.

Separation is a `payroll_manager` act. Terminating an employee sets the employee's `termination_date`, which is immutable once written; a second termination attempt is rejected with `ERR_INVALID_STATE` (HTTP 409). Termination does not, by itself, terminate the employee's garnishment orders — each order requires its own explicit termination — but a set `termination_date` immediately bars three operations against that employee: receiving a new order, activating an order, and adding a pay statement for the employee to a run. All three are rejected with `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` (HTTP 409). Once a terminated employee's remaining orders have all reached terminal states, no further payroll run may include that employee, and the guard is enforced at statement creation.

### 3.3. Order Intake and Issuing-Authority Validation

A garnishment order enters the system when a `payroll_specialist` receives it against an employee. The intake payload names the `issuing_authority_id`, the `case_number` printed on the order, an `order_type` of `CHILD_SUPPORT`, `FEDERAL_TAX_LEVY`, `STUDENT_LOAN`, or `CREDITOR`, an `amount_model` of `PERCENT_OF_DISPOSABLE`, `FIXED_AMOUNT_PER_PERIOD`, or `LUMP_SUM_BALANCE`, an `amount_value`, the `total_balance_cents` ordered — a positive integer that stands as the conserved total the employer will ever collect — the `effective_date` from which withholding begins, and the OCC field `expected_employee_version`. The meaning of `amount_value` depends on the model: for `PERCENT_OF_DISPOSABLE` it is a percentage expressed in basis points (2500 means 25 percent); for `FIXED_AMOUNT_PER_PERIOD` it is a number of cents to withhold each period; for `LUMP_SUM_BALANCE` it is ignored. In all models `amount_value` remains a required, non-negative integer, and a non-positive `total_balance_cents` is likewise rejected — both with `ERR_INVALID_REQUEST` (HTTP 400).

Receipt stamps the order's `received_at` from the logical clock, sets its `processing_status` to `RECEIVED` and its `remit_posture` to `REMITTING`, and fixes two deadlines. The `answer_due_date` is ten business days after the receipt date, counting only Monday through Friday. The `notification_due_at` is seven calendar days after `received_at`. Intake also cascades: the employee's `version` increments, and an audit entry (action `order.receive`) is appended.

Three checks guard intake. The order's `case_number` must match the issuing authority's `accepted_case_number_pattern`, else the intake is rejected with `ERR_CASE_NUMBER_PATTERN` (HTTP 422). A `StateRule` must exist for the employee's `work_state_code`, else the rejection is `ERR_STATE_RULE_MISSING` (HTTP 422). And no other order on the same employee may already share the same `order_type` and `case_number` in a non-terminal state — a duplicate is rejected with `ERR_DUPLICATE_ACTIVE_ORDER` (HTTP 409). A terminated employee cannot receive orders at all (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE`), and the duplicate rule applies not only here but also at validation and at termination time.

From `RECEIVED`, the specialist either validates or rejects the order. Validation re-examines the legal fit: the employee must not be terminated (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE`, HTTP 409), the state rule must still exist, the duplicate-order check runs again, and — re-checked here — the authority's type must be compatible with the order's type. Compatibility is exact: a `CHILD_SUPPORT` order must come from a `CHILD_SUPPORT_AGENCY`; a `FEDERAL_TAX_LEVY` must come from a `FEDERAL_AGENCY`; a `CREDITOR` order must come from a `COURT`; a `STUDENT_LOAN` order may come from either a `FEDERAL_AGENCY` or a `STATE_AGENCY`. Any incompatibility is rejected with `ERR_AUTHORITY_MISMATCH` (HTTP 422); a successful validation moves the order from `RECEIVED` to `VALIDATED` and appends an audit entry (action `order.validate`). Rejection instead takes a `reason` and moves the order from `RECEIVED` to the terminal `REJECTED` state, closing its `remit_posture` to `CLOSED` in the same act and appending an audit entry (action `order.reject`).

Orders are retrievable individually, per employee, per authority, or through a filtered listing accepting `employee_id`, `employer_id`, `issuing_authority_id`, and `processing_status`.

### 3.4. Notification, Activation, and the Working Life of an Order

A validated order next owes its employee a notification. When the `payroll_specialist` records that notification, the order moves from `VALIDATED` to `EMPLOYEE_NOTIFIED`, its `notification_sent_at` is stamped from the logical clock, and an audit entry (action `order.notify`) is appended. If `notification_sent_at` falls after the `notification_due_at` computed at intake, the notification is late — late notification is legal, but the lateness is recorded on the order as a `notification_late` boolean (null until the notification is sent).

Activation turns notification into withholding power. The specialist activates an order only from `EMPLOYEE_NOTIFIED`, only while `notification_sent_at` is set, and only while the employee remains unterminated (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE` otherwise); the order arrives at `ACTIVE` and an audit entry (action `order.activate`) is appended. The order's `processing_status` now walks the legal pipeline — `RECEIVED`, `VALIDATED`, `EMPLOYEE_NOTIFIED`, `ACTIVE`, `ANSWER_FILED`, `SUSPENDED`, and the terminal `SATISFIED`, `TERMINATED`, and `REJECTED` — while its `remit_posture` runs as an independent parallel dimension through `REMITTING`, `HELD`, and `CLOSED`. The two interact at exactly one point: withholding may post for an order only while its `remit_posture` is `REMITTING`, and terminal states always carry a `CLOSED` posture.

Three manager-driven acts shape an active order's working life. First, answering the court: a `payroll_manager` files an answer carrying an `answer_type` and an `answer_date`; only `ACCEPTED` is accepted — any other `answer_type` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — and an `ACCEPTED` filing moves the order from `ACTIVE` to `ANSWER_FILED`, records the `answer_type` and `answer_date` on the order, and appends an audit entry (action `order.answer`). An answer filed on or before the `answer_due_date` is recorded with an `answer_timeliness` of `ON_TIME`; a later answer is recorded as `LATE` — late answers are legal but flagged through this field. An `ANSWER_FILED` order withholds exactly as an `ACTIVE` one does, there is no explicit un-answer, and the only way back to `ACTIVE` is suspension followed by resumption. Second, suspension: a manager may suspend an order from `ACTIVE` — an `ANSWER_FILED` order is treated as `ACTIVE` for this check — supplying a `hold_reason` of `DISPUTED` or `REFUND_PENDING`. Suspension moves the order to `SUSPENDED`, flips its `remit_posture` to `HELD` with the supplied reason recorded, and appends an audit entry (action `order.suspend`). An order tolerates at most three suspensions over its life; a fourth attempt is rejected with `ERR_SUSPEND_LIMIT_EXCEEDED` (HTTP 409). Third, resumption: a manager resumes a `SUSPENDED` order — provided the employee is not terminated (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE`, HTTP 409) — returning it to `ACTIVE`, restoring its `remit_posture` to `REMITTING`, clearing its `hold_reason`, and leaving the suspension count untouched, since only suspension increments it. Resumption also makes any of the order's still-unassigned withholding events eligible for the next remittance sweep, and it appends an audit entry (action `order.resume`).

Termination closes an order by hand. A `payroll_manager` terminates an order from `ACTIVE`, `ANSWER_FILED`, or `SUSPENDED`, supplying a `termination_reason`; the order lands in `TERMINATED` with its `remit_posture` closed and its `hold_reason` cleared, and an audit entry (action `order.terminate`) is appended. Termination is refused with `ERR_DUPLICATE_ACTIVE_ORDER` when a later order on the same employee already shares the terminated order's `order_type` and `case_number` in a non-terminal state — the newer order, not the older, now carries the obligation. A `SATISFIED` order may also be terminated as a purely administrative close. Termination frees the order's share of the withholding pool from the next waterfall onward; an already-`OPEN` run is unaffected unless it is voided and re-run.

### 3.5. Payroll Runs and Pay Statements

A `payroll_specialist` opens a payroll run by supplying the `employer_id`, the inclusive `period_start` and `period_end` dates, the `pay_date` on which net pay will be disbursed — the date from which remittance deadlines will later be computed — and the OCC field `expected_employer_version`. The run window must be internally sound and externally disjoint: `period_end` on or after `period_start`, and `period_start` strictly after the `period_end` of the employer's latest non-voided run, so that consecutive windows neither overlap nor even abut. A violation is rejected with `ERR_PERIOD_OVERLAP` (HTTP 409). A new run is born `OPEN`, and its creation appends an audit entry (action `run.create`). Runs may be listed per employer or through a filtered listing accepting `employer_id` and `status`.

Statements accumulate inside an `OPEN` run, one per employee per run — a second statement for the same employee in the same run is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — each created by a specialist whose payload carries the `employee_id`, the `gross_earnings_cents` for the period (a positive integer), the `mandatory_deductions_cents` covering taxes and other legally mandated deductions, and — conditionally — `hours_worked`. The deduction bounds are strict: `mandatory_deductions_cents` must be non-negative and strictly less than `gross_earnings_cents`, else the create is rejected with `ERR_INVALID_DEDUCTIONS` (HTTP 422), and a non-positive `gross_earnings_cents` is rejected with the same error. The hours rule is state-conditional: for an employee whose `work_state_code` is `TX`, `hours_worked` is required and must be greater than zero, because the Texas hourly floor test consumes it; for every other state the field is ignored by the computation (a supplied value is stored and echoed back unchanged), and a missing or non-positive Texas hours value is rejected with `ERR_PERIOD_OVERLAP`. A statement may not be created for a terminated employee (`ERR_EMPLOYEE_TERMINATED_INELIGIBLE`). At creation the statement computes its `disposable_earnings_cents` as `gross_earnings_cents` minus `mandatory_deductions_cents`, records its `payroll_run_id` and denormalized `employer_id`, initializes `total_withheld_cents` and `total_admin_fee_cents` to 0, `net_pay_cents` to the disposable earnings, and `computation_breakdown` to an empty list, and appends an audit entry (action `statement.create`). Statements can be listed per run, per statement the events posted against it, or through a filtered listing accepting `payroll_run_id`, `employer_id`, and `employee_id`.

A run that should never have been opened can be voided, but only while `OPEN` and only while no statement in it has posted a withholding event; a run carrying posted events is rejected with `ERR_RUN_HAS_POSTED_EVENTS` (HTTP 409). Voiding moves the run to the terminal `VOIDED` state, leaves its statements in place but inert, increments the employer's `version`, and appends an audit entry (action `run.void`).

### 3.6. Paying a Run: The Withholding Waterfall

Payment is the fiscal heart of the system. A `payroll_specialist` pays an `OPEN` run, carrying `expected_employer_version` per §2.7; a run with no statements at all is rejected with `ERR_RUN_EMPTY` (HTTP 422). Payment executes the withholding waterfall independently for every statement in the run, posts one `WITHHOLD` withholding event per awarded order — idempotently, at most one event per pairing of `pay_statement_id` and `garnishment_order_id` — finalizes each statement, moves the run to the terminal `PAID` state, increments the employer's `version`, and appends one audit entry per statement (action `run.pay`). Remittances are deliberately not created as part of payment; settlement is the separate explicit step of §3.7, and lateness for `PENDING` remittances of other runs is judged at their own confirm time, never here.

The waterfall's first question is who participates. An order on the statement's employee joins the allocation when its `processing_status` is `RECEIVED`, `VALIDATED`, `EMPLOYEE_NOTIFIED`, `ACTIVE`, or `ANSWER_FILED`, when its `remit_posture` is `REMITTING`, and when its `effective_date` falls on or before the run's `period_end`. Note the deliberate asymmetry: orders still early in the pipeline may have withholding posted, but only events of `ACTIVE` and `ANSWER_FILED` orders ever become assignable to a remittance; everyone else's events wait unassigned until the order reaches `ACTIVE`.

The computation then proceeds in six steps.

First, disposable earnings. The statement's `disposable_earnings_cents` is its `gross_earnings_cents` minus its `mandatory_deductions_cents`; given the deduction bounds of §3.5, this is always at least one cent.

Second, the protected floor. For an employee whose `work_state_code` is anything other than `TX`, the weekly floor is the state's `min_wage_multiplier` times 725 cents — the federal minimum hourly wage — times forty hours, and the period floor is that weekly floor scaled by the employee's `pay_frequency`: a factor of 1 for `WEEKLY`, 2 for `BIWEEKLY`, 2.1667 for `SEMIMONTHLY`, and 4.3333 for `MONTHLY`, with the resulting period floor rounded half-up to whole cents. For a Texas employee the period floor is instead the statement's `hours_worked` times the state's `hourly_floor_cents`, rounded half-up to cents, and neither the federal multiplier nor the pay frequency plays any role. The withholding pool is disposable earnings minus the period floor, or zero when the floor meets or exceeds disposable earnings.

Third, priority. Orders rank by class — every `CHILD_SUPPORT` order before every `FEDERAL_TAX_LEVY` order, which precede `STUDENT_LOAN`, which precedes `CREDITOR` — and within a class by the earliest `received_at`, with ties broken by the earlier `effective_date`, then the earlier `created_at`, and finally the order in which the records were created; the record `id` is never consulted as a tie-break.

Fourth, proration. An order whose `effective_date` falls strictly inside the period is prorated: the numerator is the count of days from the later of the `effective_date` and the `period_start` through the `period_end`, inclusive, and the denominator is the total count of days in the period, inclusive; the ratio is applied at full precision before any rounding. An order effective on or before the `period_start` uses a factor of one — no proration.

Fifth, the award pass. Walking the priority order, each order's raw demand depends on its `amount_model`: a `PERCENT_OF_DISPOSABLE` order demands disposable earnings times its `amount_value` basis points — that is, `amount_value` divided by ten thousand — times the proration factor, rounded half-up to a whole cent once; a `FIXED_AMOUNT_PER_PERIOD` order demands its `amount_value` cents times the proration factor, rounded half-up once; a `LUMP_SUM_BALANCE` order demands its full `remaining_balance_cents`, unprorated. The state's `caps` impose a per-order ceiling of disposable earnings times the cap fraction for the order's type, rounded half-up to cents. The award is the smallest of four quantities: the raw demand, the state cap, the pool still remaining, and the order's `remaining_balance_cents`. One non-compete rule overrides the mechanics: if any `CHILD_SUPPORT` order received a positive award in this pass, every `CREDITOR` order is skipped outright with an award of zero and a basis of `BLOCKED_BY_SUPPORT`. A positive award posts a `WITHHOLD` event and shrinks the remaining pool by the awarded amount; a zero award contributes a line to the statement's `computation_breakdown` but posts no event, taking its basis from the first binding constraint — `CAPPED_BY_POOL` when the pool is exhausted, else `CAPPED_BY_STATE` when the state cap allows nothing, else `PRORATED` or `FULL` when the demand itself rounds to zero, else `CAPPED_BY_BALANCE` when no balance remains. When an award equals the order's remaining balance before the award, the order is satisfied on the spot: its `processing_status` becomes `SATISFIED`, its `remit_posture` closes, its final event carries the basis `FINAL_PARTIAL`, sibling orders on the same employee absorb the freed pool within the same waterfall pass without any re-run, and an audit entry (action `order.satisfy`) is appended. Every posted event's `computation_proof` captures the allocation context at posting time — `disposable_earnings_cents`, `pool_cents`, `cap_fraction`, `cap_cents`, `floor_cents`, the order's `rank` (its 1-based position in the priority order), and the `basis` of the award, one of `FULL`, `PRORATED` when the effective date fell inside the period, `CAPPED_BY_STATE`, `CAPPED_BY_POOL`, `CAPPED_BY_BALANCE`, `FINAL_PARTIAL` when the award closed the balance, or `BLOCKED_BY_SUPPORT` for the creditor non-compete; when several bounds coincide for a positive award, the basis is the first match in the order `FINAL_PARTIAL`, `FULL`/`PRORATED`, `CAPPED_BY_STATE`, `CAPPED_BY_POOL`, `CAPPED_BY_BALANCE`. Each order's `withheld_cents` accumulates its posted withholding, and its `remaining_balance_cents` is always the conserved ledger: `total_balance_cents` minus `withheld_cents` plus `refunded_cents`.

Sixth, and always last, the employer's administrative fee — it is computed after every award and never reduces any award. Under a `NONE` policy there is no fee. Under `PER_ORDER`, the statement's `total_admin_fee_cents` is the employer's `admin_fee_cents` multiplied by the count of orders that received positive awards on that statement. When the state's `fee_deductible_from_wages` is true, the fee comes out of the employee: net pay is disposable earnings minus total withheld minus the fee, and if the full fee would push net pay below zero the fee is clipped to disposable earnings minus total withheld, leaving net pay at exactly zero. When `fee_deductible_from_wages` is false, the fee is recorded on the statement but borne by the employer, and net pay is simply disposable earnings minus total withheld. The statement's `net_pay_cents`, `total_withheld_cents` (the sum of its withholding events, refunds excluded), and `total_admin_fee_cents` are finalized here, and its `computation_breakdown` is a list that preserves the per-order allocation trace — one entry per order the award pass considered, each entry carrying `order_id`, `awarded_cents`, `basis`, and `note` together with the statement-level allocation context captured during the pass (`disposable_earnings_cents`, `floor_cents`, and `pool_cents`). Two invariants hold at the end of every pass: total withheld never exceeds the pool, and net pay never falls below the period floor whenever the floor itself is below disposable earnings — with one exception: when the state makes the administrative fee employee-borne, the fee is deducted on top of withholding and may push net pay below the floor, so only non-negative net pay is guaranteed in that case.

### 3.7. Remitting to Agencies

Withheld money reaches agencies through remittances, created explicitly by a `payroll_specialist` who names the `employer_id`, the `authority_id`, and the `payroll_run_id` to settle. Creation sweeps up every still-unassigned `WITHHOLD` event posted against that run for orders of that authority whose `processing_status` is `ACTIVE` or `ANSWER_FILED`; the remittance's `amount_due_cents` is the sum of the swept events, and the swept event ids are recorded in its `member_event_ids` in chronological order. A sweep that finds nothing is rejected with `ERR_NO_REMITTABLE_EVENTS` (HTTP 409), and because there is at most one remittance per authority per run, a second create for the same pairing of `authority_id` and `payroll_run_id` is rejected with `ERR_DUPLICATE_REMITTANCE` (HTTP 409). Creation appends an audit entry (action `remittance.create`), and the new remittance is `PENDING`.

The due date is fixed at creation. The employer's `remittance_timing` contributes an offset — zero days for `SAME_DAY`, one business day for `NEXT_BUSINESS_DAY`, three business days for `THREE_BUSINESS_DAYS` — and the `due_date` is the run's `pay_date` advanced by that many business days, skipping Saturdays and Sundays with no holiday calendar. The `SAME_DAY` variant pins the due date to the `pay_date` itself, whatever weekday it lands on. Both inputs — the `pay_date` stored on the run and the timing policy read from the employer — are evaluated at creation, so a later configuration change never retroactively moves an existing remittance's deadline.

Confirmation belongs to the `payroll_manager`, under the segregation-of-duties rule of §2.10: the confirmer's `X-User-ID` must differ from the `X-User-ID` that paid the run. Confirming a `PENDING` remittance on or before its `due_date` lands it in `CONFIRMED`; confirming after the `due_date` lands it in `LATE_CONFIRMED` instead, with the lateness recorded. Either way `confirmed_at` is stamped from the logical clock and an audit entry (action `remittance.confirm`) is appended. Confirmation requires something to actually pay: a remittance whose member events have all been refunded down to an effective total of zero is rejected with `ERR_REMITTANCE_EMPTY` (HTTP 409). Cancellation also belongs to the manager and applies to a `PENDING` remittance whose every member withholding event carries a compensating refund; it moves the remittance to `CANCELLED` and appends an audit entry (action `remittance.cancel`). A cancellation attempted on a non-`PENDING` remittance, or on one whose member events are not fully refunded, is rejected with `ERR_INVALID_STATE` (HTTP 409). The same cancellation can also arrive without any manager act, as a posture-driven consequence of §3.8: when a refund targeting an event already swept into a `PENDING` remittance drains that remittance's effective total to zero, the remittance cancels itself. Remittances are retrievable per authority, per employer, or through a filtered listing accepting `employer_id`, `authority_id`, `payroll_run_id`, and `status`.

### 3.8. Corrections and Employee Refunds

Over-withholding is corrected, never edited away. A `payroll_manager` issues a refund against an order, supplying a positive `refund_amount_cents`, a mandatory `reason`, and the `payroll_run_id` the correction is tagged to. A refund may target an order in any `processing_status`, including a terminal one; the named run must exist and belong to the order's employer, else the refund is rejected with `ERR_NOT_FOUND` (HTTP 404). The amount may not exceed the order's net withheld — its `withheld_cents` minus its already-returned `refunded_cents` — and the order must have withheld something at all; either violation, like a non-positive `refund_amount_cents`, is rejected with `ERR_REFUND_EXCEEDS_WITHHELD` (HTTP 422).

A refund appends a `REFUND` event to the order's log, its `amount_cents` recorded as a negative value and its `pay_statement_id` and `computation_proof` left null, because the event log is append-only: a `WithholdingEvent` is never updated and never carries a `version`. The response carries the appended `REFUND` event. The refund adds to the order's `refunded_cents` and recomputes its `remaining_balance_cents` per the conserved ledger of §3.6, and an audit entry (action `order.refund`) is appended. Two consequences deserve emphasis. If the refunded `WITHHOLD` event had already been swept into a `PENDING` remittance, that remittance's `amount_due_cents` is recomputed as the swept withhold total minus the refunds posted against its member orders for that run, floored at zero, and if the effective total reaches zero the remittance auto-cancels to `CANCELLED` — the posture-driven path of §3.7 — with a `SYSTEM`-actor audit entry (action `remittance.cancel`). And if the order was already `SATISFIED`, the refund restores the conserved balance ledger but does not reopen the order: `SATISFIED` is terminal and stays so even when the refund pushes `remaining_balance_cents` back above zero. All events — withholdings and refunds alike — are retrievable per order, per run, per statement, or through a filtered listing accepting `garnishment_order_id`, `employer_id`, `payroll_run_id`, `pay_statement_id`, and `event_type`, with each event's `created_logical_at` recording when the logical clock stamped it.

## 4. Endpoint Definitions

Operations that create a new primary resource — an employer, a state rule, an issuing authority, an employee, a garnishment order, a payroll run, a pay statement, or a remittance — return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or append to a resource's records (including refunds, which append an event to an order's log) return a `200 OK` status code. The request and response shapes of each endpoint are governed by the narratives of §3 together with the envelope contract of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | employer_payroll_admin |
| POST | `/employers` | Create an employer | employer_payroll_admin |
| GET | `/employers/{employerId}` | Get an employer | All roles |
| PATCH | `/employers/{employerId}` | Update employer configuration (timing, fee policy, fee amount) | employer_payroll_admin |
| POST | `/state-rules` | Create a state rule (immutable after creation) | employer_payroll_admin |
| GET | `/state-rules/{stateCode}` | Get a state rule by state code | All roles |
| POST | `/authorities` | Create an issuing authority | employer_payroll_admin |
| GET | `/authorities/{authorityId}` | Get an issuing authority | All roles |
| GET | `/authorities/{authorityId}/remittances` | List remittances for an authority | All roles |
| GET | `/authorities/{authorityId}/orders` | List garnishment orders issued by an authority | All roles |
| GET | `/orders` | Filtered list of garnishment orders | All roles |
| GET | `/events` | Filtered list of withholding events | All roles |
| GET | `/statements` | Filtered list of pay statements | All roles |
| GET | `/employees` | Filtered list of employees | All roles |
| GET | `/payroll-runs` | Filtered list of payroll runs | All roles |
| GET | `/events/{eventId}` | Get a single withholding event | All roles |
| GET | `/remittances` | Filtered list of remittances | All roles |
| GET | `/audit-log/{entryId}` | Get a single audit log entry | All roles |
| GET | `/audit-log` | Filtered list of audit log entries | All roles |
| GET | `/statements/{statementId}/events` | List withholding events posted against a statement | All roles |
| POST | `/employees` | Create an employee under an employer | employer_payroll_admin, payroll_specialist |
| GET | `/employees/{employeeId}` | Get an employee | All roles |
| GET | `/employers/{employerId}/employees` | List employees of an employer | All roles |
| GET | `/employees/{employeeId}/orders` | List garnishment orders for an employee | All roles |
| POST | `/employees/{employeeId}/terminate` | Set an employee's termination date (immutable) | payroll_manager |
| POST | `/employees/{employeeId}/orders` | Receive a garnishment order (intake) | payroll_specialist |
| GET | `/orders/{orderId}` | Get a garnishment order | All roles |
| POST | `/orders/{orderId}/validate` | Validate issuing-authority compatibility and state-rule existence | payroll_specialist |
| POST | `/orders/{orderId}/reject` | Reject an order at intake | payroll_specialist |
| POST | `/orders/{orderId}/notify` | Record employee notification | payroll_specialist |
| POST | `/orders/{orderId}/activate` | Activate an order for withholding | payroll_specialist |
| POST | `/orders/{orderId}/suspend` | Suspend withholding (cyclic, limited) | payroll_manager |
| POST | `/orders/{orderId}/resume` | Resume a suspended order | payroll_manager |
| POST | `/orders/{orderId}/answer` | File an answer/response to the court | payroll_manager |
| POST | `/orders/{orderId}/terminate` | Terminate an order | payroll_manager |
| POST | `/orders/{orderId}/refund` | Refund an over-withheld amount to the employee | payroll_manager |
| GET | `/orders/{orderId}/events` | List withholding events for an order (chronological) | All roles |
| POST | `/payroll-runs` | Create a payroll run | payroll_specialist |
| GET | `/payroll-runs/{runId}` | Get a payroll run | All roles |
| GET | `/employers/{employerId}/payroll-runs` | List payroll runs for an employer | All roles |
| POST | `/payroll-runs/{runId}/statements` | Add a pay statement to an OPEN run | payroll_specialist |
| GET | `/payroll-runs/{runId}/statements` | List statements of a run | All roles |
| GET | `/statements/{statementId}` | Get a pay statement (with computation breakdown) | All roles |
| POST | `/payroll-runs/{runId}/pay` | Pay the run: execute the waterfall, post events, finalize statements | payroll_specialist |
| POST | `/payroll-runs/{runId}/void` | Void an OPEN run with no posted events | payroll_specialist |
| GET | `/payroll-runs/{runId}/events` | List withholding events posted by a run | All roles |
| POST | `/remittances` | Create a remittance by sweeping unassigned withhold events | payroll_specialist |
| GET | `/remittances/{remittanceId}` | Get a remittance | All roles |
| GET | `/employers/{employerId}/remittances` | List remittances for an employer (filterable) | All roles |
| POST | `/remittances/{remittanceId}/confirm` | Confirm payment sent to the agency (late if past due) | payroll_manager |
| POST | `/remittances/{remittanceId}/cancel` | Cancel a PENDING remittance whose member events are all refunded | payroll_manager |
| GET | `/employers/{employerId}/audit-log` | List audit log entries (supports chain verification) | employer_payroll_admin, payroll_manager, compliance_auditor |

## 5. Error Code Catalogue

The trigger conditions for each error live in the narratives of §2 and §3; this catalogue is only the index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_CASE_NUMBER_PATTERN` | 422 |
| `ERR_STATE_RULE_MISSING` | 422 |
| `ERR_AUTHORITY_MISMATCH` | 422 |
| `ERR_DUPLICATE_ACTIVE_ORDER` | 409 |
| `ERR_EMPLOYEE_TERMINATED_INELIGIBLE` | 409 |
| `ERR_PERIOD_OVERLAP` | 409 |
| `ERR_INVALID_DEDUCTIONS` | 422 |
| `ERR_RUN_EMPTY` | 422 |
| `ERR_RUN_HAS_POSTED_EVENTS` | 409 |
| `ERR_REFUND_EXCEEDS_WITHHELD` | 422 |
| `ERR_SUSPEND_LIMIT_EXCEEDED` | 409 |
| `ERR_REMITTANCE_EMPTY` | 409 |
| `ERR_NO_REMITTABLE_EVENTS` | 409 |
| `ERR_DUPLICATE_REMITTANCE` | 409 |
| `ERR_AUDIT_CHAIN_BROKEN` | 409 |

# Return of Title IV Funds and Withdrawal Processing API — Product Requirements Document

## 1. Introduction

When a student who receives federal Title IV financial aid withdraws from a payment period, the institution is legally obligated to determine how much of that aid was actually "earned" by the portion of the period the student completed, and to return the unearned portion to the federal programs within a strict regulatory window. This Return of Title IV Funds (R2T4) process is one of the most error-prone calculations a university financial aid office performs: the withdrawal date itself depends on whether the withdrawal was official or unofficial and on whether the institution takes attendance; the earned percentage is capped by statute once a student crosses sixty percent of the period; the return responsibility is split between the school and the student under a waterfall that includes a grant-protection allowance; and, when the student earned more than was ever disbursed, the school owes a post-withdrawal disbursement rather than a return — grants automatically, loans only with the student's explicit acceptance. Alongside the federal calculation, the institution's own refund policy (tiered or pro rata) interacts with the student's account, potentially creating a balance that must be communicated to the student.

This document specifies an API, mounted under `/r2t4`, that gives the registrar's office, the financial aid office, and the bursar's office a shared, auditable system of record for the entire R2T4 lifecycle. It covers academic term and break calendars, enrollment and account ledgers, aid awards and their disbursements, withdrawal case initiation and calculation, return obligations with deadline tracking, post-withdrawal disbursement offers, and the correction and rescission pathways that keep the record honest when inputs change. All deadline behavior is driven by a controllable logical clock so that the 45-day return window, the 14-day offer response window, and the 30-day offer-creation flag can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `SystemAdmin`, `RegistrarClerk`, `FinancialAidOfficer`, `BursarClerk`, and `Student`. A request missing either header, or carrying a role value outside this declared set, is rejected with an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Access to specific operations is further restricted by role: an attempt to perform an action outside the caller's designated role is rejected with an `ERR_FORBIDDEN_FOR_ROLE` error.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student`; ownership checks on any resource that references a `Student` compare the resource's student reference to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `SystemAdmin`, `RegistrarClerk`, `FinancialAidOfficer`, or `BursarClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `calculated_by_user_id` on a withdrawal case or as `recorded_by_user_id` on a return obligation) but does not compare it to any entity's `id`.

Role responsibilities at a glance: a `RegistrarClerk` owns terms, breaks, students, enrollments, withdrawal initiation and rescission, and enrollment completion. A `FinancialAidOfficer` owns awards, disbursements, and the calculation and recalculation of withdrawal cases. A `BursarClerk` records return payments and student account payments. A `Student` acts only on their own records — accepting their own loan awards, responding to their own post-withdrawal offers, paying toward their own account, and initiating only an official withdrawal of their own enrollment. A `SystemAdmin` is the platform operator who drives the logical clock used by deadline sweeps. Read access to individual resources and lists is available to every role.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Audit Fields

Every primary resource in the system — terms, students, enrollments, awards, disbursements, withdrawal cases, return obligations, and post-withdrawal offers — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource, including modifications caused by cascades originating from another resource.

Two resource kinds are deliberately leaner. A scheduled break and a student account entry are immutable records once created: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent from them. Because account entries are never edited, corrections to the ledger always take the form of new compensating entries rather than mutations of existing rows (see §2.6).

### 2.5. The Logical Clock and Regulatory Deadline Sweeps

All date- and deadline-sensitive behavior in the system — disbursement dates, offer timestamps, overdue detection, expiration, and term-completion eligibility — is evaluated against a logical clock maintained by the server, never against the wall clock. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it advances only when an operator explicitly moves it.

An admin-only test-driving capability, available exclusively to the `SystemAdmin` role, sets the logical clock to a supplied `to_iso8601` instant. The supplied value must be greater than or equal to the current logical time; a request that would move the clock backward is rejected with `ERR_INVALID_FIELD`, and the clock never falls back to wall-clock time on its own. A successful set returns the new logical time as `current_utc`.

Setting the clock runs a deadline sweep across the whole system. Every return obligation still `PENDING` whose `due_date` is strictly earlier than the new current date transitions to `OVERDUE`; on the `due_date` itself the obligation remains `PENDING`, because the deadline is inclusive. Every post-withdrawal offer still `SENT` whose `response_deadline` is strictly earlier than the new current date transitions to `EXPIRED`; on the deadline date itself the offer remains `SENT` and may still be accepted. After the sweep, every withdrawal case touched by these transitions re-runs its automatic closure evaluation (see §3.7).

### 2.6. The Append-Only Student Account Ledger

Each enrollment's financial position is expressed as an append-only ledger of account entries. Every entry carries an `entry_type`, a signed `amount_cents`, a `source_ref` identifying the originating artifact, and a `posted_at` logical timestamp. The six entry types and their sign conventions are fixed: `CHARGE` and `R2T4_CHARGEBACK` entries are positive (they increase what the student owes); `REFUND_CREDIT`, `AID_CREDIT`, and `PAYMENT` entries are negative; and a `REVERSAL` entry carries the negation of the amount of the entry it reverses, recorded through its `reversal_of_entry_id` reference, which is set only on `REVERSAL` entries and is null on all others. The `source_ref` holds the id of the originating disbursement, obligation, or case, and is empty for `CHARGE` and `PAYMENT` entries.

The enrollment's `balance_cents` is always a derived figure: the sum of the signed `amount_cents` over every account entry of the enrollment, where a positive value means the student owes the school. Any posting of a new entry triggers an immediate recomputation of `balance_cents`. Whenever a recomputation happens while a linked withdrawal case is `CALCULATED` and the resulting balance is greater than zero, the enrollment's `balance_notification_sent` flag is set to true and `balance_notified_at` is stamped with the current logical time, recording that a balance-due notification has been emitted; both fields are reset by a rescission (see §3.7). Entries are never updated or deleted; a mistake is corrected by posting a `REVERSAL` entry that negates the original.

### 2.7. Cents, Percentages, and Rounding Discipline

All monetary amounts in the system are integer counts of cents — charges, awards, disbursements, obligations, offers, ledger entries, and balances alike. Whenever a calculation produces a fractional cent, the result is rounded half-up to a whole cent at the step the specification designates; multi-award calculations round each award first and sum afterward (see §3.5).

Percentages derived from day counts — most importantly the share of the payment period a withdrawing student completed — are carried at three decimal places, rounded half-up. Day counts themselves are whole calendar days. These precision rules are part of the regulatory contract of the system: two implementations that round at different steps will disagree on obligation amounts, so the rounding order is pinned wherever a formula appears in §3.

### 2.8. Optimistic Concurrency on Withdrawal Cases

Recalculating a withdrawal case is the one write operation guarded by optimistic concurrency control. A recalculation request must carry `expected_withdrawal_case_version`, a non-optional field holding the `version` of the withdrawal case as the client last observed it. If that value does not match the case's current `version` — because another writer has advanced the case since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a calculation it has not observed. No other endpoint accepts a version field; operations not named here perform no such check.

### 2.9. Validation Order and Nested Resource Retrieval

When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the earliest applicable failure rather than an arbitrary one:

1. **Header context** — `X-User-ID` and `X-User-Role` are present and the role is one of the declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). Applies to every endpoint.
2. **Role authorization** — the role is listed for the endpoint; otherwise `ERR_FORBIDDEN_FOR_ROLE` (403). This includes the rule that a `Student` may initiate only an `OFFICIAL` withdrawal.
3. **Request-body well-formedness** — required fields are present, enum members are valid, types are correct, an end date is strictly after its start date, and amounts are positive where required; violations yield `ERR_INVALID_REQUEST` (400) or `ERR_INVALID_FIELD` (422).
4. **Resource existence** — path and body resource identifiers are validated left to right; the first identifier that does not correspond to an existing resource yields `ERR_NOT_FOUND` (404). For a nested path such as a break under a term, the term's existence is confirmed before the break is even considered, so a request under a non-existent parent reports the parent as missing.
5. **Student ownership** — for student-scoped operations (withdraw, award acceptance, offer response, payment), `X-User-ID` must equal the owning enrollment's `student_id`; otherwise `ERR_OWNERSHIP_MISMATCH` (403).
6. **State validity** — the target resource is in a state that permits the transition: an enrollment `ENROLLED` or `WITHDRAWN` as appropriate, a case `OPEN` or `CALCULATED`, an obligation `PENDING` or `OVERDUE`, an offer `SENT`, an award `OFFERED`, a disbursement `SCHEDULED`. Violations surface as `ERR_INVALID_STATE`, `ERR_ENROLLMENT_ALREADY_WITHDRAWN`, `ERR_ENROLLMENT_NOT_WITHDRAWN`, `ERR_OBLIGATION_ALREADY_RETURNED`, or `ERR_OFFER_NOT_RESPONDABLE` (all 409).
7. **Stale-version check** — on recalculation, `expected_withdrawal_case_version` must equal the case's current `version`; otherwise `ERR_STALE_VERSION` (412).
8. **Temporal rules** — supplied dates lie within the payment period, completion is not attempted before the term has ended, and the clock never moves backward; violations yield `ERR_DATE_OUT_OF_PERIOD` (422), `ERR_TERM_NOT_ENDED` (409), or `ERR_INVALID_FIELD` (422).
9. **Cross-entity state guards** — an award must be `ACCEPTED` before funds are released, no `OPEN` or `CALCULATED` case may exist when disbursing manually, no `RETURNED` obligation or `ACCEPTED` offer may exist when recalculating or rescinding, and no `DISBURSED` rows may exist when cancelling an award; violations yield `ERR_AWARD_NOT_ACCEPTED`, `ERR_DISBURSEMENT_BLOCKED_BY_CASE`, `ERR_RETURN_ALREADY_COMPLETED`, `ERR_OFFER_ALREADY_ACCEPTED`, or `ERR_AWARD_HAS_DISBURSEMENTS` (all 409).
10. **Calendar constraints** — term date intervals must not overlap, breaks must lie inside their term and must not overlap one another, and an `UNOFFICIAL` withdrawal on an attendance-taking term must supply its attendance date; violations yield `ERR_TERM_OVERLAP` (409), `ERR_BREAK_OUTSIDE_TERM` (422), `ERR_BREAK_OVERLAP` (409), or `ERR_ATTENDANCE_DATE_REQUIRED` (422).
11. **Segregation of duties** — a `FinancialAidOfficer` may not record the school-party return of a case they themselves calculated; otherwise `ERR_SEGREGATION_OF_DUTIES` (403).
12. **Fiscal exactness** — a recorded return must equal the obligation amount exactly, and scheduled plus disbursed disbursements must not exceed the award amount; violations yield `ERR_RETURN_AMOUNT_MISMATCH` (422) or `ERR_DISBURSEMENT_EXCEEDS_AWARD` (422).

Because this ordering is fixed, a request that fails on several grounds always reports the same one: for example, recording a return against an obligation that is already `RETURNED` surfaces `ERR_OBLIGATION_ALREADY_RETURNED` even when the supplied amount is also wrong, because the state check (priority 6) precedes fiscal exactness (priority 12).

## 3. Business Logic & Workflows

### 3.1. Structuring the Payment Period: Terms and Scheduled Breaks

Everything in the R2T4 process is anchored to the academic term, which serves as the payment period. A `RegistrarClerk` creates a term by supplying a `name` (a label such as "Fall 2026"), a `start_date`, and an `end_date`, both ISO calendar dates; the end date must fall strictly after the start date, or the request is rejected with `ERR_INVALID_FIELD`. Two further inputs shape later calculations. The `attendance_taking_required` flag, which defaults to false when omitted, records whether the institution takes attendance for the period — a fact that decides how unofficial withdrawal dates are determined (see §3.4). The `refund_method` selects the institutional refund variant and must be either `TIERED` or `PRO_RATA`, defaulting to `TIERED`; a `TIERED` term consults its `refund_schedule`, an ordered list of tiers each pairing a `through_day` with a `refund_pct`, which defaults — when not supplied — to a full refund through day 7, a 0.75 refund through day 14, and a 0.5 refund through day 28.

Terms occupy exclusive calendar territory. A new term whose closed date interval intersects any existing term's closed interval is rejected with `ERR_TERM_OVERLAP`; two terms that merely touch — one ending on the day before the other begins — are permitted. Upon creation the server derives three day-count figures. The `calendar_days` of a term are the count of calendar days from `start_date` through `end_date` inclusive. The `deductible_break_days` figure starts at zero and is recomputed as breaks are registered. The `total_days` of the term are its `calendar_days` minus its `deductible_break_days`, and this value becomes the denominator of the percentage-of-period-completed calculation performed at withdrawal time.

Scheduled breaks — holidays and recesses of the term — are registered under the term by a `RegistrarClerk` supplying the break's `start_date` and `end_date`; the end must not precede the start, and both dates must lie inside the parent term, or the request fails with `ERR_BREAK_OUTSIDE_TERM`. A break whose closed interval intersects another break of the same term is rejected with `ERR_BREAK_OVERLAP`; adjacency, by contrast, is not an overlap and instead causes the breaks to merge for deduction purposes. Each break exposes a computed `length_days`, the count of days from its start through its end inclusive, and its `term_id` ties it back to the parent term. Breaks are immutable once created.

Whether break days reduce the period's day count follows a grouping algorithm run at term creation and again at every break creation. All of the term's breaks are sorted by `start_date` ascending, ties broken by `created_at` ascending, and then swept greedily: a break merges into the current group when its start date falls no later than one calendar day after the group's current end, so breaks separated by adjacent calendar days fuse into one group; otherwise the group closes and a new one begins. A group's span is the count of days from its earliest start through its latest end inclusive, and the group is deductible when that span reaches at least 5 consecutive days. The term's `deductible_break_days` is the sum of spans over the deductible groups, and its `total_days` is recomputed accordingly. For reporting, the group's earliest break (by start date, then creation time) carries the group's entire span as its `deductible_days`; every other break in a deductible group carries zero, as does every break in a non-deductible group. Adding a break is a mutation of the parent term: it recomputes these figures and increments the term's `version`.

### 3.2. Students, Enrollments, and Account Charges

Before any aid can be packaged, a `RegistrarClerk` registers the student with an `external_ref` (the student information system's reference), a `full_name`, and a notification `email`.

Enrolling the student into a term is likewise a registrar action: the request names the target `term_id` and the `institutional_charges_cents` — the gross institutional charges for the period, zero or more. Creation immediately posts the first ledger entry, a `CHARGE` entry for the full `institutional_charges_cents`, so the new enrollment's `balance_cents` equals the charges and its `status` begins as `ENROLLED`. The enrollment record also exposes `current_withdrawal_case_id`, which points at the withdrawal case currently in `OPEN` or `CALCULATED` for the enrollment and is null whenever no such case exists, along with the notification fields `balance_notification_sent` and `balance_notified_at` described in §2.6. The enrollment list supports optional filters by `student_id`, `term_id`, and `status`.

Money received from the student enters the ledger through a payment: a `BursarClerk`, or the student themselves acting on their own enrollment, submits an `amount_cents`, and the server posts a `PAYMENT` entry for the negated amount and recomputes the balance. A `Student` attempting to pay toward an enrollment that is not theirs is rejected with `ERR_OWNERSHIP_MISMATCH`.

When the period ends, a `RegistrarClerk` marks the enrollment completed. Completion is permitted only from `ENROLLED` — any other status yields `ERR_INVALID_STATE` — and only once the current logical date is strictly later than the term's `end_date`, or the request fails with `ERR_TERM_NOT_ENDED`. Completion cancels every disbursement still `SCHEDULED` across the enrollment's awards, increments the enrollment's `version`, and lands the enrollment in `COMPLETED`, its terminal state.

### 3.3. Packaging Aid: Awards and Disbursements

A `FinancialAidOfficer` packages aid by creating awards against an enrollment, each naming a `program` — one of `PELL_GRANT`, `SUBSIDIZED_LOAN`, `UNSUBSIDIZED_LOAN`, or `PLUS_LOAN` — and an `amount_cents` that must be positive. A Pell grant begins life already `ACCEPTED`, reflecting that no student acceptance is required; every loan begins `OFFERED`. The award's `is_grant` flag is derived and reads true exactly when the program is `PELL_GRANT`. Two running totals are maintained on each award: `disbursed_amount_cents`, the sum of its `DISBURSED` disbursements, and `scheduled_amount_cents`, the sum of its `SCHEDULED` ones.

Accepting a loan is the student's own action on their own award, permitted only while the award is `OFFERED` (otherwise `ERR_INVALID_STATE`) and only when the caller's identity matches the owning enrollment's `student_id` (otherwise `ERR_OWNERSHIP_MISMATCH`); acceptance moves the award from `OFFERED` to `ACCEPTED` and increments its `version`. Cancellation runs the other way: a `FinancialAidOfficer` may cancel an award from either `OFFERED` or `ACCEPTED`, but only while the award has no `DISBURSED` disbursements — an award with disbursed funds cannot be cancelled and the attempt fails with `ERR_AWARD_HAS_DISBURSEMENTS`. Cancelling an award moves all of its `SCHEDULED` disbursements to `CANCELLED` (each departing amount leaving `scheduled_amount_cents`) and lands the award in its terminal `CANCELLED` state.

Scheduling a disbursement against an award is a financial aid office action carrying an `amount_cents`. The award must be `OFFERED` or `ACCEPTED` — a `CANCELLED` award rejects the attempt with `ERR_INVALID_STATE` — and the cumulative total of already scheduled plus already disbursed amounts plus the new amount must not exceed the award's `amount_cents`, or the request fails with `ERR_DISBURSEMENT_EXCEEDS_AWARD`. A successfully scheduled disbursement begins in `SCHEDULED` status and increases the award's `scheduled_amount_cents` by its amount.

Releasing a scheduled disbursement converts it from `SCHEDULED` to `DISBURSED`. The release is rejected with `ERR_INVALID_STATE` when the disbursement is not `SCHEDULED`, with `ERR_AWARD_NOT_ACCEPTED` when the parent award is not `ACCEPTED`, and with `ERR_DISBURSEMENT_BLOCKED_BY_CASE` whenever the enrollment has a withdrawal case in `OPEN` or `CALCULATED` — once a withdrawal is in flight, funds may reach the student only through the post-withdrawal disbursement machinery of §3.5, and the system-created disbursements produced by that machinery bypass this gate. A successful release stamps `disbursed_on` with the current logical date, adds the amount to the award's `disbursed_amount_cents` while subtracting it from `scheduled_amount_cents`, posts an `AID_CREDIT` ledger entry for the negated amount whose `source_ref` is the disbursement's id, and recomputes the enrollment's balance. Each disbursement record also carries an `award_id` identifying its parent award and a `pwd_offer_id`, which stays null unless the disbursement was created by a post-withdrawal offer acceptance. The disbursement list supports optional filters by `award_id`, `pwd_offer_id`, and `status`.

### 3.4. Withdrawing: Date Determination and the Withdrawal Case

A withdrawal begins when a `RegistrarClerk` — or the student themselves — initiates it against an `ENROLLED` enrollment with a payload naming the `withdrawal_type`, either `OFFICIAL` or `UNOFFICIAL`. Acting on an enrollment already `WITHDRAWN` is rejected with `ERR_ENROLLMENT_ALREADY_WITHDRAWN`, and on a `COMPLETED` one with `ERR_INVALID_STATE`. Two restrictions apply to the student pathway: the caller's identity must match the enrollment's `student_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and a student may report only an official withdrawal — an `UNOFFICIAL` request from a `Student` is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The payload's date requirements depend on the variant. An `OFFICIAL` withdrawal must carry a `notification_date` — the date the student began the official withdrawal process — and its absence is rejected with `ERR_INVALID_REQUEST`. An `UNOFFICIAL` withdrawal on a term whose `attendance_taking_required` is true must carry a `last_attendance_date`, the documented last date of attendance, and its absence is rejected with `ERR_ATTENDANCE_DATE_REQUIRED`. Every supplied date must lie inside the period from the term's `start_date` through its `end_date` inclusive; a date outside that range is rejected with `ERR_DATE_OUT_OF_PERIOD`.

From these inputs the server determines the two governing dates of the case. For an official withdrawal, the `withdrawal_date` is the supplied `notification_date`, and the `determination_date` equals it. For an unofficial withdrawal on an attendance-taking term, the `withdrawal_date` is the supplied `last_attendance_date`, while the `determination_date` is the logical date on which the withdrawal request is processed. For an unofficial withdrawal on a term that does not take attendance, the statute's midpoint rule applies: the midpoint day is computed by adding one to the term's `total_days`, halving the result, and rounding down to a whole number, and the `withdrawal_date` is the calendar date of that day of the period, counting the term's start date as day one — so a 105-day period yields day 53 and a 100-day period yields day 50; the `determination_date` is again the logical processing date.

With the dates fixed, the server computes the student's progress through the period. The `completed_days` are the count of calendar days from the term's start through the `withdrawal_date` inclusive, minus any deductible break-group days falling inside that same range. Dividing `completed_days` by the term's `total_days` and rounding half-up to three decimal places yields the case's `percentage_completed`. The earned share follows the statutory cap: when `percentage_completed` exceeds 0.600, the student is treated as having earned one hundred percent of their aid and `earned_pct` reads 1.000; otherwise `earned_pct` equals `percentage_completed`. The boundary is inclusive of the cap's threshold — a completion of exactly 0.600 earns exactly 60.0 percent, and the full-earning rule engages only at 0.601 and beyond.

Initiating the withdrawal creates the `WithdrawalCase` in `OPEN` status, stamped with the enrollment's `enrollment_id`, the determined dates, a `total_days` snapshot frozen from the term at withdrawal time, and the computed `completed_days` and `percentage_completed`. The financial snapshot amounts — `aid_disbursable_cents`, `aid_disbursed_cents`, `aid_earned_cents`, and `aid_unearned_cents` — remain null until the case is calculated. In the same action the enrollment moves from `ENROLLED` to `WITHDRAWN`, its `current_withdrawal_case_id` is set to the new case, and the enrollment's `version` increments. An enrollment carries at most one withdrawal case in `OPEN`, `CALCULATED`, or `CLOSED`; a successor case may be opened only after the prior one has reached `CANCELLED`.

### 3.5. Running the R2T4 Calculation

The heart of the workflow is the calculation, performed by a `FinancialAidOfficer` against a case in `OPEN` status — invoking it on a case in any other status is rejected with `ERR_INVALID_STATE`. Calculation evaluates only the enrollment's eligible awards, meaning those in `ACCEPTED` status; awards still `OFFERED` or already `CANCELLED` are excluded from the disbursable base entirely.

For each eligible award the server first forms the award's disbursable amount: its `disbursed_amount_cents` plus its `scheduled_amount_cents`, capturing everything that has been or was planned to be paid. Each award's earned amount is then the award's disbursable amount multiplied by the case's `earned_pct`, rounded half-up to whole cents — and this rounding happens per award, before any summation. The case's `aid_earned_cents` is the sum of those individually rounded per-award earned amounts, `aid_disbursable_cents` is the sum of the per-award disbursable amounts, `aid_disbursed_cents` is the sum of `disbursed_amount_cents` over the eligible awards, and `aid_unearned_cents` is `aid_disbursable_cents` minus `aid_earned_cents`. The round-then-sum order is pinned: two awards of 100001 cents each at an earned share of 0.505 yield 50501 plus 50501, an `aid_earned_cents` of 101002 — summing first and rounding the aggregate, which would yield 101001, is the rejected alternative. As part of the same action, every disbursement still `SCHEDULED` across the enrollment's awards is cancelled, since no further scheduled payments may occur.

When the earned amount falls short of what was disbursed, the case takes the return path, and `return_amount_cents` is the disbursed amount minus the earned amount. The unearned percentage — one minus `earned_pct`, itself rounded half-up to three decimal places — drives the split of responsibility. The school's share, `school_return_cents`, is the smaller of two figures: the enrollment's gross `institutional_charges_cents` multiplied by the unearned percentage and rounded half-up to whole cents, or the full `return_amount_cents`. The student share is what remains of `return_amount_cents` after the school's share. Within the student share, the grant portion is bounded by the grant unearned-disbursed total — the sum over the accepted grant awards of the positive part of each award's disbursed amount minus its earned amount — and the student grant base is the smaller of the student share and that grant total. The student's actual grant obligation, `student_grant_return_cents`, is half of that base rounded half-up to whole cents, reflecting the fifty-percent grant protection allowance; the remainder of the student share becomes `student_loan_deferred_cents`, an informational figure routed to normal loan repayment for which no obligation is ever created.

Obligations materialize only where money is actually owed: a school-party obligation is created when `school_return_cents` is greater than zero, and a student-party obligation when `student_grant_return_cents` is greater than zero — obligations with an amount of zero are never created. Each obligation records its `withdrawal_case_id`, its `party` (`SCHOOL` or `STUDENT`), its `amount_cents`, and a `due_date` exactly 45 calendar days after the case's `determination_date`, and both begin `PENDING`. Creation order is fixed: the school row is created before the student row, and since the obligations list returns rows ordered by `created_at` ascending, the school obligation — when present — is always the first element. Every school-party obligation also posts an `R2T4_CHARGEBACK` ledger entry for its amount, positive, with `source_ref` set to the obligation's id, charging the school's return back to the student's account.

When the earned amount exceeds what was disbursed, the case instead takes the post-withdrawal disbursement path and no return obligations are created, since nothing was over-paid; `return_amount_cents` reads zero on this path. For each eligible award, the award's post-withdrawal amount is the positive part of its earned amount minus its disbursed amount. Grant post-withdrawal amounts are credited automatically: the server creates an already-`DISBURSED` disbursement for the amount, stamped with the current logical date, and posts the corresponding `AID_CREDIT` entry. Loan post-withdrawal amounts may not be disbursed without consent, so each becomes a `PostWithdrawalOffer` in `SENT` status against the award. The case records the totals as `pwd_grant_cents` (the sum of grant post-withdrawal amounts) and `pwd_loan_cents` (the sum of loan post-withdrawal amounts). Offers are created in ascending order of their awards' `created_at`, and the offers list returns them in that same creation order.

Independent of which path is taken, the institutional refund is computed against the enrollment's `institutional_charges_cents` according to the term's `refund_method`. Under `TIERED`, the server walks the term's `refund_schedule` and selects the first tier whose `through_day` is at least the case's `completed_days`; that tier's `refund_pct` applies, and when `completed_days` exceeds every tier's `through_day` the refund percentage is zero — the same withdrawal day therefore yields a step-function refund. Under `PRO_RATA`, the refund percentage is one minus the case's `percentage_completed` — the rounded three-decimal figure, not `earned_pct`, so the sixty-percent earned cap has no effect on refunds. For contrast, day 11 of a 110-day term with 400000 cents of charges yields a refund of 300000 cents under the default tiered schedule but 360000 cents pro rata. The refund amount is the charges multiplied by the refund percentage, rounded half-up to whole cents, and when it is greater than zero the server posts a `REFUND_CREDIT` ledger entry for the negated amount.

Calculation closes by recomputing the enrollment's `balance_cents` from the ledger; when the balance is positive, the notification fields `balance_notification_sent` and `balance_notified_at` are set as described in §2.6. The case records `calculated_by_user_id` — the `X-User-ID` of the officer who ran the calculation, which later drives segregation of duties — and `calculated_at`, the logical timestamp of the calculation; the case's `version` increments by one, the case lands in `CALCULATED`, and the automatic closure evaluation of §3.7 runs immediately.

### 3.6. Return Obligations and Post-Withdrawal Offers

A return obligation begins `PENDING` and ages under the logical clock: when a clock sweep finds the current date strictly past the obligation's `due_date`, the obligation transitions from `PENDING` to `OVERDUE`, while on the due date itself it remains `PENDING` — the 45-day deadline is inclusive.

Recording a return is shared between the `BursarClerk` and the `FinancialAidOfficer`, and is permitted from either `PENDING` or `OVERDUE` — a late return is accepted and recorded all the same. The request carries an `amount_cents` and may optionally carry a `returned_on` date. The supplied amount must equal the obligation's `amount_cents` exactly; any difference is rejected with `ERR_RETURN_AMOUNT_MISMATCH`. Recording against an obligation already `RETURNED` fails with `ERR_OBLIGATION_ALREADY_RETURNED`, and against a `VOIDED` one with `ERR_INVALID_STATE`. One segregation-of-duties guard applies: a `FinancialAidOfficer` whose `X-User-ID` equals the case's `calculated_by_user_id` may not record the `SCHOOL`-party return of that case — the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` — while a `BursarClerk` is never barred, and student-party returns carry no such restriction. A successful recording stamps `returned_at` with the current logical time, stores the amount as `returned_amount_cents`, notes the actor in `recorded_by_user_id`, moves the obligation to `RETURNED`, and triggers the case's automatic closure evaluation.

Post-withdrawal offers begin `SENT` when calculation creates them. Each offer carries its `withdrawal_case_id`, the `award_id` of the loan award it would disburse against, the offered `amount_cents`, and an `offered_at` logical timestamp set at creation. The student's response window, `response_deadline`, is the calendar date of `offered_at` plus 14 days, and acceptance remains allowed on the deadline date itself — the window is inclusive, with expiration occurring only once the current date passes the deadline, at which point a clock sweep moves the offer from `SENT` to `EXPIRED`. A compliance flag, `late_offer`, reads true when the offer's creation date falls more than 30 calendar days after the case's `determination_date`, marking a violation of the 30-day offer rule. The offers list supports optional filters by `award_id`, `withdrawal_case_id`, and `status`.

Responding to an offer is the student's own action: the caller's identity must match the owning enrollment's `student_id` (otherwise `ERR_OWNERSHIP_MISMATCH`), and the offer must still be `SENT` — an offer in any other status is rejected with `ERR_OFFER_NOT_RESPONDABLE`. Acceptance stamps `responded_at`, moves the offer to `ACCEPTED`, and immediately disburses the funds: a new disbursement is created already `DISBURSED` for the offer's `amount_cents`, tied to the offer's `award_id`, carrying the offer's id in its `pwd_offer_id`, and stamped with the current logical date; that disbursement posts its `AID_CREDIT` ledger entry and increases the award's `disbursed_amount_cents`. The enrollment's balance is then recomputed with notification evaluation, and the case's automatic closure evaluation runs. Declining simply stamps `responded_at`, moves the offer to `DECLINED`, and runs the same closure evaluation. Both pathways end in terminal offer states, as do the sweep-driven `EXPIRED` transition and the `VOIDED` transition produced by the recalculation and rescission cascades of §3.7.

### 3.7. Corrections, Rescission, and Case Closure

Recalculation is the controlled way to correct a calculated case. A `FinancialAidOfficer` may recalculate only a case in `CALCULATED` status (otherwise `ERR_INVALID_STATE`), and the request must carry `expected_withdrawal_case_version` per the optimistic concurrency rule of §2.8 — a value that no longer matches the case's current `version` is rejected with `ERR_STALE_VERSION`. Two further guards protect completed business: recalculation is rejected with `ERR_RETURN_ALREADY_COMPLETED` when any obligation of the case is already `RETURNED`, and with `ERR_OFFER_ALREADY_ACCEPTED` when any offer of the case is already `ACCEPTED`, because money that has actually moved can no longer be recomputed away.

The recalculation payload may carry corrections to `notification_date`, `last_attendance_date`, or `withdrawal_type`, which are revalidated exactly as at withdrawal time — dates outside the payment period are rejected with `ERR_DATE_OUT_OF_PERIOD`, and switching a case to `UNOFFICIAL` on an attendance-taking term without supplying `last_attendance_date` is rejected with `ERR_ATTENDANCE_DATE_REQUIRED`. From the corrected inputs the server recomputes the `withdrawal_date`, `completed_days`, `percentage_completed`, and `earned_pct`. It then compensates the old calculation before applying the new one: every obligation still `PENDING` or `OVERDUE` is voided, every offer still `SENT` is voided, and `REVERSAL` ledger entries are posted negating each of the case's `REFUND_CREDIT` and `R2T4_CHARGEBACK` entries. The full calculation cascade of §3.5 then re-runs — fresh snapshots, new obligations with their chargebacks or new post-withdrawal activity, a fresh refund, a balance recomputation with notification evaluation — and the case's `calculated_by_user_id` is updated to the acting officer while its `version` increments. Because the pipeline is deterministic, recalculating with identical inputs reproduces identical amounts: the aid conservation invariant holds across the loop.

Rescission is the registrar's compensating action for a withdrawal that should not stand. It requires the enrollment to be `WITHDRAWN` — any other status yields `ERR_ENROLLMENT_NOT_WITHDRAWN` — and the linked case to be `OPEN` or `CALCULATED`; a case that already reached `CLOSED` rejects the rescission with `ERR_INVALID_STATE`. The same completed-business guards as recalculation apply: a `RETURNED` obligation blocks with `ERR_RETURN_ALREADY_COMPLETED`, and an `ACCEPTED` offer blocks with `ERR_OFFER_ALREADY_ACCEPTED`. When the case was still `OPEN`, no financial artifacts existed and the enrollment simply reverts. When the case was `CALCULATED`, the rescission runs the full compensation cascade: the case moves to `CANCELLED`, every `PENDING` or `OVERDUE` obligation is voided, every `SENT` offer is voided, `REVERSAL` entries negate each of the case's `REFUND_CREDIT` and `R2T4_CHARGEBACK` entries, and the enrollment's balance is recomputed. In both variants the enrollment returns from `WITHDRAWN` to `ENROLLED`, its `balance_notification_sent` flag is reset to false and `balance_notified_at` cleared to null, `current_withdrawal_case_id` is cleared, and the enrollment's `version` increments.

Case closure itself is automatic. After every mutation that touches a `CALCULATED` case, its obligations, its offers, or the enrollment's balance, the server evaluates three conditions: every return obligation of the case is terminal (`RETURNED` or `VOIDED`); every post-withdrawal offer of the case is terminal (`ACCEPTED`, `DECLINED`, `EXPIRED`, or `VOIDED`); and the enrollment's `balance_cents` is not positive or its `balance_notification_sent` flag is set. When all three hold, the case transitions from `CALCULATED` to `CLOSED`, clearing the enrollment's `current_withdrawal_case_id` and incrementing the case's `version`. `CLOSED` and `CANCELLED` are the terminal states of a withdrawal case, and both the deadline sweep of §2.5 and every respond or record action re-run this evaluation. Throughout the lifecycle, officers and auditors can list withdrawal cases filtered by `enrollment_id` and `status`, review a case's obligations and offers through its nested lists, and inspect the append-only ledger filtered by `enrollment_id`, `entry_type`, or `reversal_of_entry_id`.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (e.g., a term, a student, an award) or add new, distinct resources to a collection (e.g., a break to a term, an enrollment to a student, a disbursement to an award, a payment entry, a withdrawal case) return a `201 Created` status code. Operations that modify an existing resource in place — accepting or cancelling an award, releasing a disbursement, rescinding or completing an enrollment, calculating or recalculating a case, recording a return, responding to an offer, or setting the clock — return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/r2t4/terms` | Create an academic term (payment period) | RegistrarClerk |
| GET    | `/r2t4/terms` | List terms (paginated) | Any |
| GET    | `/r2t4/terms/{id}` | Get a term | Any |
| POST   | `/r2t4/terms/{id}/breaks` | Add a scheduled break; recomputes merged deductible groups and term day counts | RegistrarClerk |
| GET    | `/r2t4/terms/{id}/breaks` | List breaks of a term | Any |
| POST   | `/r2t4/students` | Register a student | RegistrarClerk |
| GET    | `/r2t4/students/{id}` | Get a student | Any |
| POST   | `/r2t4/students/{id}/enrollments` | Enroll a student in a term; posts the CHARGE account entry | RegistrarClerk |
| GET    | `/r2t4/enrollments` | List enrollments (paginated; filterable by student, term, status) | Any |
| GET    | `/r2t4/enrollments/{id}` | Get an enrollment with computed balance and notification flags | Any |
| POST   | `/r2t4/enrollments/{id}/withdraw` | Withdraw the student (official or unofficial); creates the withdrawal case in OPEN | RegistrarClerk, Student |
| POST   | `/r2t4/enrollments/{id}/rescind-withdrawal` | Rescind the withdrawal; cancels the case and reverses its financial artifacts | RegistrarClerk |
| POST   | `/r2t4/enrollments/{id}/complete` | Mark enrollment completed after term end; cancels remaining SCHEDULED disbursements | RegistrarClerk |
| POST   | `/r2t4/enrollments/{id}/payments` | Record a student payment toward the account balance | BursarClerk, Student |
| GET    | `/r2t4/enrollments/{id}/awards` | List awards of an enrollment | Any |
| GET    | `/r2t4/enrollments/{id}/account-entries` | List ledger entries of an enrollment (append-only) | Any |
| POST   | `/r2t4/enrollments/{id}/awards` | Create an aid award (PELL_GRANT starts ACCEPTED; loans start OFFERED) | FinancialAidOfficer |
| GET    | `/r2t4/awards/{id}` | Get an award | Any |
| POST   | `/r2t4/awards/{id}/accept` | Student accepts a loan award | Student |
| POST   | `/r2t4/awards/{id}/cancel` | Cancel an award with no disbursed funds | FinancialAidOfficer |
| POST   | `/r2t4/awards/{id}/disbursements` | Schedule a disbursement against an award | FinancialAidOfficer |
| GET    | `/r2t4/disbursements` | List disbursements (paginated; filterable by award, offer, status) | Any |
| GET    | `/r2t4/disbursements/{id}` | Get a disbursement | Any |
| POST   | `/r2t4/disbursements/{id}/disburse` | Release a SCHEDULED disbursement; blocked while a withdrawal case is active | FinancialAidOfficer |
| GET    | `/r2t4/withdrawal-cases` | List withdrawal cases (paginated; filterable by enrollment, status) | Any |
| GET    | `/r2t4/withdrawal-cases/{id}` | Get a withdrawal case with all R2T4 snapshot fields | Any |
| POST   | `/r2t4/withdrawal-cases/{id}/calculate` | Run the R2T4 calculation: snapshots, obligations, chargeback, PWD, refund, balance, notification, auto-close | FinancialAidOfficer |
| POST   | `/r2t4/withdrawal-cases/{id}/recalculate` | Correct case inputs and re-run the calculation; OCC-guarded; voids and regenerates outstanding artifacts | FinancialAidOfficer |
| GET    | `/r2t4/withdrawal-cases/{id}/obligations` | List return obligations of a case | Any |
| GET    | `/r2t4/withdrawal-cases/{id}/offers` | List post-withdrawal disbursement offers of a case | Any |
| POST   | `/r2t4/return-obligations/{id}/record-return` | Record that a return obligation was paid in full (late payment from OVERDUE allowed) | BursarClerk, FinancialAidOfficer |
| GET    | `/r2t4/post-withdrawal-offers` | List PWD offers (paginated; filterable by award, case, status) | Any |
| GET    | `/r2t4/post-withdrawal-offers/{id}` | Get a PWD offer | Any |
| POST   | `/r2t4/post-withdrawal-offers/{id}/accept` | Student accepts a loan PWD offer within the response window; disburses the funds | Student |
| POST   | `/r2t4/post-withdrawal-offers/{id}/decline` | Student declines a loan PWD offer | Student |
| GET    | `/r2t4/account-entries` | List ledger entries (paginated; filterable by enrollment, entry type, reversed entry) | Any |
| GET    | `/r2t4/account-entries/{id}` | Get a ledger entry | Any |
| POST   | `/r2t4/_clock/set_current_utc` | Set the logical clock (ISO 8601); runs the deadline sweep and case auto-close evaluations | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FIELD` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ENROLLMENT_ALREADY_WITHDRAWN` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_WITHDRAWN` | 409 Conflict |
| `ERR_TERM_NOT_ENDED` | 409 Conflict |
| `ERR_DATE_OUT_OF_PERIOD` | 422 Unprocessable Entity |
| `ERR_ATTENDANCE_DATE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_TERM_OVERLAP` | 409 Conflict |
| `ERR_BREAK_OUTSIDE_TERM` | 422 Unprocessable Entity |
| `ERR_BREAK_OVERLAP` | 409 Conflict |
| `ERR_AWARD_NOT_ACCEPTED` | 409 Conflict |
| `ERR_AWARD_HAS_DISBURSEMENTS` | 409 Conflict |
| `ERR_DISBURSEMENT_BLOCKED_BY_CASE` | 409 Conflict |
| `ERR_DISBURSEMENT_EXCEEDS_AWARD` | 422 Unprocessable Entity |
| `ERR_OBLIGATION_ALREADY_RETURNED` | 409 Conflict |
| `ERR_RETURN_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RETURN_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_OFFER_NOT_RESPONDABLE` | 409 Conflict |
| `ERR_OFFER_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

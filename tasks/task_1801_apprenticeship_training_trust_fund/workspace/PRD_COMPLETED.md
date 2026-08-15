# Apprenticeship Training Trust Fund API — Product Requirements Document

## 1. Introduction

Joint apprenticeship and training committees operate trust funds that sit at the intersection of labor relations, vocational education, and fiduciary accounting. Signatory employers owe the fund a negotiated training contribution for every hour their apprentices work; in return the fund registers apprentices with the state or federal agency, tracks their on-the-job hours and related classroom instruction, advances them through collectively bargained wage steps, schedules and pays instructors, and spends its budget under committee governance. When an employer falls behind on remittances, the fund's ability to enter into new financial commitments must freeze until the delinquency is cured.

This API is the administrative backbone for that operation. It covers the full apprentice lifecycle from applicant through indenture to journeyman certification, the monthly contribution reporting and remittance cycle with its audit-flag and resubmission path, class scheduling with instructor and facility conflict protection, instructor payroll with scheduled-versus-actual pay bases, and a two-stage spending pipeline in which committee-approved funding allocations encumber and then pay for equipment purchases. Two principles run through everything: every cent is traceable through the fund's ledger counters, and no operator may approve a financial commitment they themselves proposed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles: `TrustAdmin` (the JATC administrative staff), `EmployerRep` (a signatory employer's representative), `CommitteeMember` (a joint committee approver), and `Instructor` (a class instructor). A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); an empty or whitespace-only `X-User-ID` counts as missing. A request whose authenticated role is not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `EmployerRep`, `X-User-ID` is the `id` of the acting Employer; ownership checks on contribution reports compare the report's `employer_id` to `X-User-ID` — at report creation, before any report exists, the payload's `employer_id` is compared instead — and acting on another employer's report, including opening one for it, is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `Instructor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, but it must equal the `instructor_user_id` string recorded on the class for which a pay claim is filed; a mismatch at claim-filing time is likewise rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `TrustAdmin` or `CommitteeMember`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it (for example as `proposed_by_user_id`, `requested_by_user_id`, `approved_by_user_id`, or `decided_by_user_id`) but never compares it to any entity's `id`. Those recorded identities still matter: they anchor the segregation-of-duties comparisons between users described in §2.8.

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

All error API responses (4xx and 5xx status codes) follow this standard envelope format:

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
- Three further error identifiers sit outside the business catalogue of §5 but use the same envelope: a request to an undefined route is rejected with `ERR_NOT_FOUND` (HTTP 404), a defined route with an unsupported method with `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server fault with `ERR_INTERNAL` (HTTP 500).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside 1 through 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order, with ties broken by `id` in ascending order.

The `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items on the returned page is still below `total_count`.

### 2.4. Common Resource Properties

All nine primary resources — trust funds, employers, apprentices, contribution reports, training classes, class enrollments, instructor pay claims, funding allocations, and equipment purchases — carry the same set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, equal to `created_at` at creation and refreshed on any change to the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments with every modification to the resource.

The last rule includes modifications the server applies to an entity as a cascade side effect of an operation on a different resource: when a remittance posts, an allocation is approved or closed, a claim is paid, or a purchase is executed, the trust fund's own `version` advances and its `updated_at` refreshes, because its ledger counters changed. An operations run that changes any of the fund's derived values, and any later re-derivation that finds the fund's stored counters stale (§2.6), likewise advance the fund's `version` and refresh its `updated_at`.

### 2.5. Money, Minutes, and Rounding Conventions

All monetary amounts in this system — contribution dues, wage rates, instructor pay, allocation amounts, purchase amounts, and every ledger counter — are integers of cents. No decimal dollar values appear anywhere in the API. Whenever a computation produces a fraction of a cent, the result is rounded half-up to the nearest whole cent; the same round-half-up convention applies whenever a minute computation produces a fractional minute. Hour accumulations reported for apprentices may be fractional and are kept as numbers. Class schedules live on a logical timeline of integer minutes, so window boundaries are always integers. Comparisons against instants, such as due dates, resolve to whole seconds.

### 2.6. The Trust Ledger

Each trust fund maintains four computed counters that together form its ledger. `contributions_received_cents` is the sum of `contribution_due_cents` across all PAID contribution reports of all the fund's employers. `disbursed_cents` is the sum of `payable_cents` across all PAID instructor pay claims plus the sum of `amount_cents` across all PURCHASED equipment purchases. `allocated_remaining_cents` is the sum of `remaining_cents` across all ACTIVE funding allocations. `available_cents` is what is left for new commitments: contributions received minus disbursements minus the remaining balances of active allocations. These counters are recomputed eagerly, inside the same request as the event that changed them — a remittance posting, an allocation approval or closure, a claim payment, or a purchase execution — never asynchronously. Two events are deliberate exceptions: approving an equipment purchase and cancelling an approved purchase change the allocation's `remaining_cents` — and therefore the fund's true `allocated_remaining_cents` and `available_cents` — but recompute only the allocation inside their own request, leaving the fund's stored counters untouched and its `version` unadvanced. The stored counters are re-derived on every fund read and on every fund-touching operation, and a re-derivation that finds them stale persists the corrected values, advancing `version` by one and refreshing `updated_at` at that moment.

Two subsidiary ledgers follow the same eager-recompute rule. An employer's `outstanding_cents` is the sum of `contribution_due_cents` over that employer's reports in `SUBMITTED`, `FLAGGED`, or `DELINQUENT` status; DRAFT reports contribute nothing because their due is still null, a report swept from DRAFT to DELINQUENT by an operations run keeps that null due and likewise contributes zero, and PAID reports are excluded. A funding allocation's `encumbered_cents` is the sum of `amount_cents` over its APPROVED purchases, its `spent_cents` is the sum over its PURCHASED purchases, and its `remaining_cents` is the allocated `amount_cents` minus the encumbered and spent portions.

### 2.7. Delinquency and the Fund's Compliance Posture

A fund's `posture` is a derived value, never set directly. It reads `COMPLIANCE_HOLD` whenever the fund's `delinquent_employer_count` — the number of its employers currently in `DELINQUENT` status — is at least one, and `OPERATING` when that count is zero. The posture moves from `OPERATING` to `COMPLIANCE_HOLD` the moment the count rises from zero, and returns to `OPERATING` when the count falls back to zero, whether the cure came through a remittance or through an operations run.

While the posture is `COMPLIANCE_HOLD`, exactly three approval operations are refused with `ERR_FUND_ON_COMPLIANCE_HOLD` (HTTP 409): approval of a funding allocation, approval of an equipment purchase, and approval of an instructor pay claim. The hold is deliberately narrow. It never blocks money coming in — report creation, submission, resubmission, and remittance all proceed — and it never blocks fulfillment of commitments already made, so paying an approved claim, executing an approved purchase, or closing an active allocation all remain available. Non-financial operations are untouched.

### 2.8. Segregation of Duties in Committee Approvals

No operator may approve a financial commitment they themselves set in motion. Approving a funding allocation requires the approver's `X-User-ID` to differ from the allocation's `proposed_by_user_id`; approving an equipment purchase requires the decider's `X-User-ID` to differ from the purchase's `requested_by_user_id`. A violation of either rule is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403). These are the only two operations with a proposer/requester relationship to police: pay-claim approval has no such anchor and is gated by fund posture alone.

### 2.9. Optimistic Concurrency Control on the Fund

Exactly one operation is guarded by optimistic concurrency control: the approval of a funding allocation. Its request body must carry `expected_trust_fund_version`, a non-optional integer field (any other type is `ERR_INVALID_REQUEST`) holding the fund `version` the client last observed. If that value does not equal the trust fund's current `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412). The rule exists because an allocation approval debits the fund's shared available pool: an approval grounded in a superseded `available_cents` reading must not proceed, so the client re-reads the fund and retries with the version it actually observes. The fund's version advances by exactly one on each of five events — a remittance posting, an allocation approval, an allocation closure, a claim payment, and a purchase execution. Two further moments advance it by one as well: an operations run that changes any of the fund's derived values, and the deferred re-derivation of §2.6 when it finds the stored counters stale after a purchase approval or cancellation. No other endpoint accepts a version field.

### 2.10. Validation Order and Resource Existence

When several checks could reject the same request, the server evaluates them in a fixed order, and a request failing several checks surfaces the error from the earliest tier. First, the identity headers are validated: presence of `X-User-ID` and `X-User-Role` and a recognized role. Second, role authorization: the role must be permitted on the endpoint. Third, resource ownership, which applies to exactly five operations — report creation, report submission, report resubmission, report remittance, and pay-claim creation. Ownership is a property of the targeted resource, so that resource's own existence is resolved first and its 404 outranks `ERR_NOT_RESOURCE_OWNER`; once the target resolves, ownership precedes every remaining check. Fourth, existence: every resource id appearing in the path or the request body must resolve, validated left to right, so the first unresolvable id determines the error — an unknown fund yields `ERR_FUND_NOT_FOUND`, an unknown employer `ERR_EMPLOYER_NOT_FOUND`, an unknown apprentice `ERR_APPRENTICE_NOT_FOUND`, an unknown report `ERR_REPORT_NOT_FOUND`, an unknown class `ERR_CLASS_NOT_FOUND`, an unknown enrollment `ERR_ENROLLMENT_NOT_FOUND`, an unknown claim `ERR_CLAIM_NOT_FOUND`, an unknown allocation `ERR_ALLOCATION_NOT_FOUND`, and an unknown purchase `ERR_PURCHASE_NOT_FOUND` (all HTTP 404). Two refinements pin the interleaving of existence with the surrounding tiers: when identifiers travel in the request body — on every creation operation — the body is parsed, the presence of all required fields is established, and each identifier is type-checked before any identifier's existence is resolved, so a malformed body, a missing field, or a non-string identifier surfaces `ERR_INVALID_REQUEST` ahead of any 404; when the targeted resource is named in the path, its existence is resolved before the request body is even parsed. Fifth, request shape: required fields present (a JSON null counts as absent) with correct types — identifiers and string fields must be JSON strings, integer fields JSON integers, and booleans are never accepted where an integer or number is required — a non-empty line set, period validity, class-window validity, and registration-outcome validity. The request body itself must be a JSON object: a malformed or non-object body is `ERR_INVALID_REQUEST`, while an absent body is treated as an empty object. Endpoints that take no request body never parse it, so even malformed JSON in the body of such a call is ignored. Sixth, state preconditions for the requested transition, including the fund-version match on allocation approval. On report resubmission and remittance the state precondition is evaluated before the body is even parsed, so a wrong-state report surfaces `ERR_REPORT_NOT_RESUBMITTABLE` or `ERR_REPORT_NOT_PAYABLE` regardless of the body; flagging parses the body first but checks the state before validating the optional reason's type. On report submission and resubmission the line-level checks run only after the state precondition, in two passes: first each line's shape, its apprentice's existence, and its employer match, then every line's hour eligibility. Seventh, compliance and safety gates: registration requirements, fund posture, segregation of duties, and certification prerequisites. Eighth, uniqueness, capacity, and scheduling: duplicate periods, duplicate enrollments, duplicate claims, class capacity, instructor and facility conflicts, attendee-list integrity, the overtime cap, and hour-eligibility of report lines. Ninth and last, the fiscal checks: tender-equals-due, allocation-fits-fund, and purchase-fits-allocation.

### 2.11. The Logical Clock

All time-dependent rules in the system — due-date computation, reporting-period validation, and the delinquency sweep — evaluate against a logical clock, never against wall-clock time. Before it has ever been adjusted, the logical clock reads exactly 2026-08-01T00:00:00Z. A TrustAdmin-only test-driving capability sets the clock to a supplied `to_iso8601` instant; once set, the clock holds that reading until it is set again. Setting the clock returns 200 with a `data` object carrying the new reading as `current_utc`, rendered as an ISO 8601 UTC timestamp with three fractional digits; a missing, non-string, or unparseable `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. The logical clock governs only the time-dependent rules — record-keeping timestamps (`created_at`, `updated_at`, `remitted_at`, `paid_at`) are stamped from wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Fund and Its Signatory Employers

A `TrustAdmin` establishes a trust fund by supplying its `name`. The new fund begins life with `posture` `OPERATING`, all four ledger counters at zero, and a `delinquent_employer_count` of zero.

Employers are onboarded onto the fund with a payload carrying the `trust_fund_id` they are signatory to, their `legal_name`, and their `agreement_rate_cents_per_hour` — the negotiated hourly training contribution, expressed in cents as a non-negative integer (else `ERR_INVALID_REQUEST`). A newly created employer starts `ACTIVE` with `outstanding_cents` at zero. The agreement rate is mutable: a `TrustAdmin` may update it later — to another non-negative integer, else `ERR_INVALID_REQUEST` — and the new rate applies to every due computation performed after the change. An update request carrying no `agreement_rate_cents_per_hour`, or a null one, changes nothing and returns the employer unchanged; an accepted update advances the employer's `version` and refreshes `updated_at` even when the new rate equals the old. Rates are never retroactive — a draft report keeps the provisional estimate computed at its creation, and a submitted report keeps the authoritative due computed at its submission. The employer roster can be listed with optional `trust_fund_id` and `status` filters.

### 3.2. Apprentice Intake and Agency Registration

Registering an apprentice applicant takes `trust_fund_id`, `employer_id` (the employing sponsor for hour reporting), `full_name`, `trade` (a trade code such as INSIDE_WIREMAN), and `journeyman_base_rate_cents`, the full journeyman hourly wage from which all step wages derive. The base rate must be a non-negative integer of cents (else `ERR_INVALID_REQUEST`), and the employer named by `employer_id` is not required to be signatory to the fund named by `trust_fund_id` — no cross-check is performed. A new apprentice begins with `program_status` `APPLICANT`, `registration_status` `UNFILED`, `registration_agency` null, both accumulators (`ojt_hours_accumulated`, `rti_credits_accumulated`) at zero, `current_wage_step` 1, and a `current_wage_rate_cents` of fifty percent of the journeyman base rate, rounded half-up to a whole cent.

The apprentice carries two independent status dimensions that interact at defined points. The program dimension runs `APPLICANT` → `INDENTURED`, with `SUSPENDED`, `COMPLETED`, and `CANCELLED` as further states; the registration dimension runs `UNFILED` → `SUBMITTED` → `REGISTERED`, `REJECTED`, or `REVOKED`, and ends at `DEREGISTERED`.

Filing the registration is a `TrustAdmin` action whose payload names the `agency` — `STATE` or `FEDERAL`; any other value is rejected with `ERR_INVALID_REQUEST`. A filing is accepted while the registration reads `UNFILED`, `REJECTED`, or `REVOKED`, so a rejected or revoked registration can be re-filed; it moves the registration to `SUBMITTED` and sets `registration_agency` from the payload. Filing while the program is `COMPLETED` or `CANCELLED` is rejected with `ERR_INVALID_STATE`, as is a filing attempted while the registration already reads `SUBMITTED` or `REGISTERED`.

Recording the agency's decision is the companion action. Its `outcome` must be one of `REGISTERED`, `REJECTED`, or `REVOKED` — anything else is rejected with `ERR_INVALID_REGISTRATION_OUTCOME` — and an optional `agency_note` may accompany it. The recording is accepted only in the two from-states the registration machine allows: an outcome of `REGISTERED` or `REJECTED` while the registration reads `SUBMITTED`, and an outcome of `REVOKED` while it reads `REGISTERED`; a recording attempted in any other registration state is rejected with `ERR_REGISTRATION_NOT_SUBMITTED`. Each outcome carries its own consequence. Recording `REGISTERED` moves the registration to `REGISTERED` and, if the program dimension happens to be `SUSPENDED`, reinstates the apprentice to `INDENTURED`. Recording `REJECTED` moves the registration to `REJECTED` with no program effect. Recording `REVOKED` moves the registration to `REVOKED` and, if the apprentice is currently `INDENTURED`, automatically suspends the program to `SUSPENDED` — the apprentice stops accumulating creditable standing until a later `REGISTERED` recording reinstates them.

Indenture moves an `APPLICANT` to `INDENTURED` and is the gate to hour reporting and class enrollment. It requires the registration dimension to read `REGISTERED`; otherwise the request is rejected with `ERR_REGISTRATION_REQUIRED` (HTTP 409). Indenturing an apprentice whose program is in any state other than `APPLICANT` is a generic invalid-state rejection. The apprentice roster supports optional `trust_fund_id`, `employer_id`, `program_status`, and `registration_status` filters.

### 3.3. Monthly Contribution Reporting, Audit, and Remittance

The monthly cycle begins when an `EmployerRep` opens a contribution report with `employer_id`, `period_year`, `period_month`, and a `lines` array. The representative may act only for their own employer: `X-User-ID` must equal the employer's `id`, else `ERR_NOT_RESOURCE_OWNER`. Each line carries an `apprentice_id` and the `ojt_hours` that apprentice worked. Creation validates only that `lines` is a non-empty array; every other line rule — field types, non-negative numeric hours, at most one line per apprentice, apprentice existence, employer match, and hour eligibility — is enforced at submission and resubmission instead, so a draft may hold lines that submission would later reject (though a line whose `ojt_hours` is missing or non-numeric cannot be priced at all and fails creation with `ERR_INTERNAL`). Both period fields must be integers: a non-integer `period_year` is `ERR_INVALID_REQUEST`, while a `period_month` that is not an integer within 1 through 12 is `ERR_INVALID_PERIOD`. The period must already have begun — a period whose first day lies after the current logical time is rejected, also as `ERR_INVALID_PERIOD`. Only one report may exist per employer per period in any status at all; a second report for the same employer and period is rejected with `ERR_DUPLICATE_REPORT_PERIOD`.

A created report lands in `DRAFT` with two computed values. Its `due_date` falls on the fifteenth day of the month immediately following the reporting period at 00:00:00 UTC — a December period rolls into January 15 of the following year. Its `provisional_due_cents` estimates what will be owed, computed from the reported lines at the employer's agreement rate at that moment. The authoritative `contribution_due_cents` stays null for as long as the report remains a draft.

Both the provisional and the final due share one pinned recipe: for each line, multiply that line's `ojt_hours` by the applicable hourly rate and round the product half-up to a whole cent; then sum those per-line amounts. Rounding each line before summing is mandatory — the alternative order (sum all hours, multiply by the rate, round once) yields different cents for fractional hours and must not be used.

Submitting moves the report `DRAFT` → `SUBMITTED`. The caller must own the report — an `EmployerRep` whose `X-User-ID` differs from the report's `employer_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. The stored line set must be non-empty, each line's `ojt_hours` must be a non-negative number, and no apprentice may appear on two lines (all `ERR_INVALID_REQUEST`); a line naming an unknown apprentice is rejected with `ERR_APPRENTICE_NOT_FOUND` (HTTP 404), every line's apprentice must belong to this employer (else `ERR_LINE_EMPLOYER_MISMATCH`, HTTP 400), and every line's apprentice must be in `INDENTURED` or `SUSPENDED` program status (else `ERR_APPRENTICE_NOT_HOUR_ELIGIBLE`, HTTP 400). Submitting a report that is not in `DRAFT` is a generic invalid-state rejection. On acceptance, the final `contribution_due_cents` is computed at the employer's current agreement rate — so a rate change between creation and submission makes the final due diverge from the provisional one for identical lines — each line's hours are added to its apprentice's `ojt_hours_accumulated` with the wage step and rate recomputed (§3.6), and the employer's `outstanding_cents` is recomputed.

A `TrustAdmin` performing an audit may flag a `SUBMITTED` report, moving it to `FLAGGED`; flagging a report in any other status is rejected with `ERR_REPORT_NOT_FLAGGABLE`. The optional `reason` supplied with the flag — a string when present, else `ERR_INVALID_REQUEST` — is recorded into `flag_reason`, which stays null until the report is flagged and is cleared again only by resubmission, so a report swept to `DELINQUENT` while flagged keeps its `flag_reason`. Payment is blocked while a report is flagged.

Resubmission is the employer's cure for a flagged report: it moves `FLAGGED` → `SUBMITTED` with a replacement `lines` array, and any report not in `FLAGGED` is refused with `ERR_REPORT_NOT_RESUBMITTABLE`. Ownership is enforced exactly as at submission, and the replacement lines must satisfy the same line rules. Each old line's hours are debited from its apprentice and each new line's hours credited, with wage steps and rates recomputed in both directions — a downward correction can lower an apprentice's step. The due is recomputed at the employer's current rate, `outstanding_cents` is recomputed, and `flag_reason` is cleared.

Remittance settles a report: `SUBMITTED` or `DELINQUENT` → `PAID`, with any other source state rejected as `ERR_REPORT_NOT_PAYABLE`. Ownership is enforced again, and the `amount_tendered_cents` must be an integer (else `ERR_INVALID_REQUEST`) and must equal the `contribution_due_cents` exactly — neither partial payment nor overpayment is accepted; a mismatch is rejected with `ERR_REMITTANCE_AMOUNT_MISMATCH` (HTTP 400). An accepted remittance stamps `remitted_at`, drops the employer's `outstanding_cents` by the paid amount, adds the paid amount to the fund's `contributions_received_cents` with `available_cents` recomputed and the fund's `version` advanced by one, and then runs the cure cascade: if the employer has no remaining `DELINQUENT` reports it returns `DELINQUENT` → `ACTIVE`, and if that cure drops the fund's `delinquent_employer_count` to zero the fund's `posture` clears `COMPLIANCE_HOLD` → `OPERATING`.

Delinquency itself is never declared by a user; it is discovered by the fund's operations run, a `TrustAdmin` capability. The run examines every report of the fund still in `DRAFT`, `SUBMITTED`, or `FLAGGED`, processed in ascending `due_date` order with ties broken by creation timestamp, earliest first, and moves to `DELINQUENT` each report whose due date is strictly earlier than the current logical time — a report exactly at its due instant is still timely. It then re-derives each employer's status: `DELINQUENT` when the employer has at least one `DELINQUENT` report, `ACTIVE` otherwise. An employer flipping `ACTIVE` → `DELINQUENT` that raises the fund's delinquent count from zero to one pulls the posture into `COMPLIANCE_HOLD`. Finally the run recomputes the count and the posture and returns the fund. When the run changes any of the fund's derived values the fund's `version` advances by one and its `updated_at` refreshes; a run that changes nothing leaves both untouched. The report ledger can be listed with optional `employer_id`, `status`, `period_year`, and `period_month` filters — the two period filters must be integer-valued, else `ERR_INVALID_REQUEST`.

### 3.4. Training Classes: Scheduling, Enrollment, and Completion

A `TrustAdmin` schedules a class by supplying `trust_fund_id`, `course_code` (such as CN-101), `instructor_user_id`, `instructor_name`, `instructor_rate_cents_per_hour` (the pay-rate snapshot for this class — a non-negative integer of cents, else `ERR_INVALID_REQUEST`), `facility` (such as SHOP-A), `rti_credit_value` (at least 1 — the related-instruction credits each attended completion awards), `capacity` (at least 1), `start_minute` (at least 0), and `end_minute`. The window must be strictly positive: an `end_minute` that does not exceed `start_minute` is rejected with `ERR_INVALID_CLASS_WINDOW`. A new class begins `SCHEDULED` with `enrolled_count` zero.

Two scheduling guards run at creation, both scoped to classes of the same fund and both considering only classes still in `SCHEDULED` status — completed or cancelled classes never block anything:

- Instructor turnover. Two classes taught by the same `instructor_user_id` conflict unless a turnover buffer separates them: a conflict exists when the new class's `start_minute` is strictly earlier than the existing class's `end_minute` plus 30 minutes and the existing class's `start_minute` is strictly earlier than the new class's `end_minute` plus 30 minutes. A gap of exactly 30 minutes between the classes is permitted. A violation is rejected with `ERR_INSTRUCTOR_SCHEDULE_CONFLICT`.
- Facility double-booking. Two classes booked into the same `facility` conflict when the new class's `start_minute` is strictly earlier than the existing class's `end_minute` and the existing class's `start_minute` is strictly earlier than the new class's `end_minute`. The intervals are half-open, so back-to-back classes — one ending at exactly the minute the other begins — do not conflict. A violation is rejected with `ERR_FACILITY_SCHEDULE_CONFLICT`.

Existing classes are considered in their creation order, and for each class the instructor-turnover check fires before the facility check, so when several conflicts exist the error is determined by the earliest-created conflicting class, an instructor conflict winning the tie on the same class.

Enrollment is a `TrustAdmin` action taking `class_id` and `apprentice_id`. The class's own status is not inspected — an apprentice may be enrolled into a completed or cancelled class — and neither the apprentice's fund nor employer is cross-checked against the class's fund. The apprentice must be `INDENTURED` — applicants and suspended apprentices cannot enroll, and the attempt is rejected with `ERR_APPRENTICE_NOT_INDENTURED` — and the registration dimension must read `REGISTERED`, else `ERR_REGISTRATION_REQUIRED`. At most one `ENROLLED` enrollment may exist per apprentice per class; a duplicate is rejected with `ERR_DUPLICATE_ENROLLMENT`. A class is full when its `enrolled_count` has reached its `capacity`, and enrolling into a full class fails with `ERR_CLASS_FULL`. A created enrollment begins `ENROLLED`, and the class's `enrolled_count` rises by one.

Dropping an enrollment moves `ENROLLED` → `DROPPED`; any other source status is rejected with `ERR_ENROLLMENT_NOT_OPEN`. The class's `enrolled_count` falls by one. Because a drop happens before any credit is awarded, it triggers no wage recomputation.

Completing a class moves it `SCHEDULED` → `COMPLETED` — any other source status is rejected with `ERR_CLASS_NOT_SCHEDULED` — and takes the `attended_enrollment_ids` list; anything other than an array of strings is `ERR_INVALID_REQUEST`, and listing the same id twice is harmless. Every id in that list must reference an `ENROLLED` enrollment belonging to this class; an unknown id, an id from another class, or an id whose enrollment is not `ENROLLED` is rejected with `ERR_INVALID_ATTENDEE_LIST` (HTTP 400). Each attended enrollment becomes `CREDITED`: the class's `rti_credit_value` is added to that apprentice's `rti_credits_accumulated`, and the apprentice's wage step and rate are recomputed. Every `ENROLLED` enrollment not present in the list becomes `NO_SHOW` and earns nothing. The class's `enrolled_count` recomputes to zero.

Cancelling a class also requires `SCHEDULED` (else `ERR_CLASS_NOT_SCHEDULED`) and is refused while any pay claim for the class sits in `SUBMITTED` or `APPROVED` — the attempt is rejected with `ERR_INVALID_STATE`. A cancelled class drops all of its `ENROLLED` enrollments to `DROPPED` and recomputes the count. Classes may be listed with optional `trust_fund_id`, `instructor_user_id`, `facility`, and `status` filters; enrollments with `class_id`, `apprentice_id`, and `status`.

### 3.5. Instructor Pay Claims and Payroll Disbursement

Once a class has completed, its instructor files a pay claim carrying `class_id`, a `pay_basis` of `SCHEDULED` or `ACTUAL` (any other value is `ERR_INVALID_REQUEST`), and — when the basis is `ACTUAL` — the declared `actual_minutes`; omitting `actual_minutes` on an `ACTUAL` claim is rejected with `ERR_INVALID_REQUEST`. On an `ACTUAL` claim `actual_minutes` must be a non-negative integer; on a `SCHEDULED` claim a supplied `actual_minutes` must be an integer and is recorded on the claim without affecting the payable, and `actual_minutes` reads null when not supplied. The caller's `X-User-ID` must equal the class's `instructor_user_id`, else `ERR_NOT_RESOURCE_OWNER`. The class must be `COMPLETED`; filing against a class in any other status is rejected with `ERR_INVALID_STATE`. At most one open claim — one in `SUBMITTED` or `APPROVED` — may exist per class; a second open claim is rejected with `ERR_DUPLICATE_CLAIM`. At creation the claim copies the class's `instructor_user_id` onto itself, computes `payable_cents` immediately, stores it, and lands in `SUBMITTED`.

The payable amount has two variants sharing one shape. The class's scheduled window length in minutes is its `end_minute` minus its `start_minute`. A `SCHEDULED`-basis claim pays the published window regardless of time actually taught: the class's `instructor_rate_cents_per_hour` multiplied by the window length, divided by sixty, rounded half-up to whole cents. An `ACTUAL`-basis claim substitutes the declared `actual_minutes` for the window length in the same computation, diverging from the scheduled figure whenever the declared minutes differ. The declared minutes are capped at the window length multiplied by one and a quarter, rounded half-up to a whole minute; a claim whose `actual_minutes` exceeds that cap is rejected with `ERR_OVERTIME_CAP_EXCEEDED` (HTTP 422).

Committee review moves the claim out of `SUBMITTED`. Approval sets the claim `APPROVED` and stamps `approved_by_user_id` with the approver's identity; rejection sets it `REJECTED`. Either action attempted on a claim not in `SUBMITTED` is rejected with `ERR_CLAIM_NOT_APPROVABLE`. Approval is one of the three posture-gated operations in the system: while the fund reads `COMPLIANCE_HOLD`, claim approval fails with `ERR_FUND_ON_COMPLIANCE_HOLD`. Rejection is not gated — a committee may always decline to pay. The `approved_by_user_id` field is null until the claim is approved.

Disbursement is the fund fulfilling a commitment it already made. A `TrustAdmin` pays an `APPROVED` claim; any other source status is rejected with `ERR_CLAIM_NOT_PAYABLE`. Payment adds the claim's `payable_cents` to the fund's `disbursed_cents`, recomputes `available_cents`, advances the fund's `version` by one, stamps `paid_at` (null until this moment), and moves the claim to `PAID`, its terminal state alongside `REJECTED`. Because payment fulfills an existing commitment, it is not posture-gated. Claims can be listed with optional `class_id`, `instructor_user_id`, and `status` filters.

### 3.6. Wage Progression and Step Determination

An apprentice's pay advances through five wage steps. Step 1 always holds — it is the base every apprentice starts from. Step 2 requires at least 2,000 accumulated on-the-job hours and at least 144 related-instruction credits; step 3 requires at least 4,000 hours and at least 288 credits; step 4 requires at least 6,000 hours and at least 432 credits; step 5 requires at least 8,000 hours and at least 576 credits. The `current_wage_step` is the highest step for which both gates — hours and credits — hold. The `current_wage_rate_cents` is the apprentice's `journeyman_base_rate_cents` multiplied by the step's percentage of the journeyman rate — fifty percent at step 1, sixty at step 2, seventy at step 3, eighty at step 4, and ninety at step 5 — rounded half-up to a whole cent. The determination draws only on the apprentice's own accumulated fields; no other apprentice's progress enters the computation.

Recomputation fires at four moments: when the apprentice is created, when a contribution report is submitted, when a flagged report is resubmitted, and when class completion credits land. Dropping an enrollment does not trigger a recomputation — nothing was awarded, so nothing is taken back. The recompute is bidirectional: a resubmission that lowers an apprentice's hours can lower the step and the rate, just as new hours or credits can raise them.

### 3.7. Funding Allocations and Equipment Procurement

Spending begins when a `TrustAdmin` proposes a funding allocation with `trust_fund_id`, a `category` of `INSTRUCTION`, `EQUIPMENT`, or `ADMIN` (any other category is `ERR_INVALID_REQUEST`), the `fiscal_year` (an integer), and an `amount_cents` of at least 1. The proposal lands in `PROPOSED` with `proposed_by_user_id` stamped from the caller's identity; its `encumbered_cents` and `spent_cents` read zero and its `remaining_cents` equals the full amount.

Committee approval is the most heavily guarded operation in the system, and its checks fire in the validation order of §2.10. The allocation must be `PROPOSED` (else `ERR_ALLOCATION_NOT_ACTIVABLE`). The request must carry `expected_trust_fund_version` equal to the fund's current `version` — a client reading the fund after another writer has advanced it must re-read and retry, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The fund must be `OPERATING` (else `ERR_FUND_ON_COMPLIANCE_HOLD`). The approver's `X-User-ID` must differ from the allocation's `proposed_by_user_id` (else `ERR_SELF_APPROVAL_FORBIDDEN`, HTTP 403). And the `amount_cents` must not exceed the fund's `available_cents` (else `ERR_INSUFFICIENT_FUND_AVAILABLE`, HTTP 402). An approved allocation becomes `ACTIVE`: the fund's `allocated_remaining_cents` grows by the allocation amount, `available_cents` is recomputed, the fund's `version` advances by exactly one, and `approved_by_user_id` — null until now — is stamped. Rejection simply moves `PROPOSED` → `REJECTED`, guarded by state and role alone.

Against an `ACTIVE` allocation — purchase requests against an allocation in any other status are rejected with `ERR_ALLOCATION_NOT_ACTIVE` — a `TrustAdmin` requests an equipment purchase with `allocation_id`, a `description`, and an `amount_cents` of at least 1. The request lands `REQUESTED` with `requested_by_user_id` stamped.

Committee review of a purchase requires it to be `REQUESTED` (else `ERR_PURCHASE_NOT_REQUESTED`). Approval additionally requires an `OPERATING` fund (else `ERR_FUND_ON_COMPLIANCE_HOLD`), a deciding identity different from `requested_by_user_id` (else `ERR_SELF_APPROVAL_FORBIDDEN`), the allocation still `ACTIVE` at decision time (else `ERR_INVALID_STATE`), and an `amount_cents` that fits inside the allocation's `remaining_cents` (else `ERR_INSUFFICIENT_ALLOCATION_REMAINING`, HTTP 402). Approval stamps `decided_by_user_id` — null until the purchase is decided — and encumbers the allocation: `encumbered_cents` grows by the purchase amount and `remaining_cents` is recomputed. Denial moves `REQUESTED` → `DENIED` and stamps `decided_by_user_id`; it takes no further input — a supplied `reason` is neither required nor recorded — and denial is not posture-gated.

A `TrustAdmin` may cancel a purchase from either `REQUESTED` or `APPROVED`; cancelling from any other status is a generic invalid-state rejection. Cancelling an approved purchase releases its encumbrance — `encumbered_cents` falls by the purchase amount and `remaining_cents` is recomputed — while cancelling a still-requested purchase touches no ledger at all. Executing an approved purchase requires the `APPROVED` status (else `ERR_PURCHASE_NOT_APPROVED`) and converts encumbrance into spend: `encumbered_cents` falls by the amount, `spent_cents` rises by it, `remaining_cents` is recomputed, the fund's `disbursed_cents` grows by the amount, `available_cents` is recomputed, the fund's `version` advances by one, and the purchase lands in `PURCHASED`. `DENIED`, `CANCELLED`, and `PURCHASED` are all terminal.

Closing returns an allocation's unspent balance to the fund. Only an `ACTIVE` allocation can be closed — anything else is a generic invalid-state rejection — and the closure is refused while any purchase on the allocation remains `REQUESTED` or `APPROVED`, surfacing `ERR_INVALID_STATE`. On closure the fund's `allocated_remaining_cents` falls by the allocation's `remaining_cents`, `available_cents` is recomputed, the fund's `version` advances by one, and the allocation becomes `CLOSED`, terminal alongside `REJECTED`. Allocations may be listed with optional `trust_fund_id`, `category`, and `status` filters; purchases with `allocation_id` and `status`.

### 3.8. Journeyman Certification and Program Exit

Certification is the program's successful exit: an `INDENTURED` apprentice becomes `COMPLETED`. Three prerequisites are enforced together, and any shortfall is rejected with `ERR_CERTIFICATION_REQUIREMENTS_NOT_MET` (HTTP 409): the apprentice's `ojt_hours_accumulated` must be at least 8,000, the `rti_credits_accumulated` must be at least 576, and the registration dimension must read `REGISTERED`. Certifying an apprentice whose program is in any state other than `INDENTURED` is a generic invalid-state rejection. On success the system reports the completion to the agency by moving the registration to `DEREGISTERED`.

Cancellation is the administrative exit, available from `APPLICANT`, `INDENTURED`, or `SUSPENDED`; from either terminal program state it is a generic invalid-state rejection. A cancellation cleans up everything the apprentice still holds open: if the registration reads `SUBMITTED` or `REGISTERED` it moves to `DEREGISTERED` (a registration still `UNFILED`, `REJECTED`, or `REVOKED` is left untouched), and every `ENROLLED` enrollment of the apprentice moves to `DROPPED` with each owning class's `enrolled_count` recomputed.

`COMPLETED` and `CANCELLED` are terminal for the program dimension, and `DEREGISTERED` is terminal for the registration dimension. The suspension and reinstatement interplay described in §3.2 — revocation suspending an indentured apprentice, a later registration reinstating them — is the only way the program dimension moves backward, and it is always driven by the agency-facing registration events rather than by a direct program action.

## 4. Endpoint Definitions

Operations that create a new resource — a trust fund, employer, apprentice, contribution report, training class, enrollment, pay claim, funding allocation, or equipment purchase — return `201 Created`. All other operations, including state transitions, updates, reads, and the logical-clock adjustment, return `200 OK`. The request and response shapes of every operation are defined by the workflows in §3 and the envelope in §2.2; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to a supplied instant | TrustAdmin |
| POST | `/trust-funds` | Create a trust fund | TrustAdmin |
| GET | `/trust-funds/{id}` | Get a trust fund with computed ledger fields | All roles |
| POST | `/trust-funds/{id}/run-ops` | Ops run: delinquency sweep, employer status and posture recompute | TrustAdmin |
| POST | `/employers` | Create a signatory employer | TrustAdmin |
| GET | `/employers/{id}` | Get an employer | All roles |
| GET | `/employers` | List employers with optional filters | All roles |
| PATCH | `/employers/{id}` | Update the employer's agreement rate (affects future computations) | TrustAdmin |
| POST | `/apprentices` | Register an apprentice applicant | TrustAdmin |
| GET | `/apprentices/{id}` | Get an apprentice | All roles |
| GET | `/apprentices` | List apprentices with optional filters | All roles |
| POST | `/apprentices/{id}/indenture` | Indenture an APPLICANT whose registration is REGISTERED | TrustAdmin |
| POST | `/apprentices/{id}/cancel` | Cancel an apprentice in any non-terminal program state | TrustAdmin |
| POST | `/apprentices/{id}/certify-journeyman` | Journeyman upgrade certification | TrustAdmin |
| POST | `/apprentices/{id}/submit-registration` | Submit or re-file the apprentice's registration to the agency | TrustAdmin |
| POST | `/apprentices/{id}/record-registration-decision` | Record the agency's decision on a registration | TrustAdmin |
| POST | `/contribution-reports` | Create a DRAFT monthly hours/contribution report | EmployerRep |
| GET | `/contribution-reports/{id}` | Get a contribution report | All roles |
| GET | `/contribution-reports` | List contribution reports with optional filters | All roles |
| POST | `/contribution-reports/{id}/submit` | Submit a DRAFT report: compute final due, credit OJT hours | EmployerRep |
| POST | `/contribution-reports/{id}/flag` | Audit-flag a SUBMITTED report, blocking payment | TrustAdmin |
| POST | `/contribution-reports/{id}/resubmit` | Resubmit a FLAGGED report with replacement lines | EmployerRep |
| POST | `/contribution-reports/{id}/remit` | Pay a SUBMITTED or DELINQUENT report; amount must equal the due exactly | EmployerRep |
| POST | `/classes` | Schedule a class (instructor and facility conflict checks apply) | TrustAdmin |
| GET | `/classes/{id}` | Get a class | All roles |
| GET | `/classes` | List classes with optional filters | All roles |
| POST | `/classes/{id}/complete` | Complete a class, crediting attended enrollments | TrustAdmin |
| POST | `/classes/{id}/cancel` | Cancel a scheduled class | TrustAdmin |
| POST | `/enrollments` | Enroll an apprentice in a class | TrustAdmin |
| GET | `/enrollments/{id}` | Get an enrollment | All roles |
| GET | `/enrollments` | List enrollments with optional filters | All roles |
| POST | `/enrollments/{id}/drop` | Drop an ENROLLED enrollment | TrustAdmin |
| POST | `/pay-claims` | Instructor files a pay claim for a completed class they taught | Instructor |
| GET | `/pay-claims/{id}` | Get a pay claim | All roles |
| GET | `/pay-claims` | List pay claims with optional filters | All roles |
| POST | `/pay-claims/{id}/approve` | Committee approves a SUBMITTED claim (posture gate applies) | CommitteeMember |
| POST | `/pay-claims/{id}/reject` | Committee rejects a SUBMITTED claim | CommitteeMember |
| POST | `/pay-claims/{id}/pay` | Pay an APPROVED claim from the fund | TrustAdmin |
| POST | `/funding-allocations` | Propose a funding allocation | TrustAdmin |
| GET | `/funding-allocations/{id}` | Get a funding allocation | All roles |
| GET | `/funding-allocations` | List funding allocations with optional filters | All roles |
| POST | `/funding-allocations/{id}/approve` | Committee approves a PROPOSED allocation (OCC, SoD, posture, fiscal gates) | CommitteeMember |
| POST | `/funding-allocations/{id}/reject` | Committee rejects a PROPOSED allocation | CommitteeMember |
| POST | `/funding-allocations/{id}/close` | Close an ACTIVE allocation, releasing its remaining balance | TrustAdmin |
| POST | `/equipment-purchases` | Request an equipment purchase against an ACTIVE allocation | TrustAdmin |
| GET | `/equipment-purchases/{id}` | Get an equipment purchase | All roles |
| GET | `/equipment-purchases` | List equipment purchases with optional filters | All roles |
| POST | `/equipment-purchases/{id}/approve` | Committee approves a REQUESTED purchase (SoD, posture; encumbers allocation) | CommitteeMember |
| POST | `/equipment-purchases/{id}/deny` | Committee denies a REQUESTED purchase | CommitteeMember |
| POST | `/equipment-purchases/{id}/cancel` | Cancel a REQUESTED or APPROVED purchase, releasing any encumbrance | TrustAdmin |
| POST | `/equipment-purchases/{id}/mark-purchased` | Mark an APPROVED purchase as executed: allocation spends, fund disburses | TrustAdmin |

## 5. Error Code Catalogue

The trigger condition for each error is defined in the workflows of §2 and §3; this table is an identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_FUND_NOT_FOUND` | 404 Not Found |
| `ERR_EMPLOYER_NOT_FOUND` | 404 Not Found |
| `ERR_APPRENTICE_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CLASS_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_PURCHASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PERIOD` | 400 Bad Request |
| `ERR_INVALID_CLASS_WINDOW` | 400 Bad Request |
| `ERR_INVALID_REGISTRATION_OUTCOME` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_APPRENTICE_NOT_INDENTURED` | 409 Conflict |
| `ERR_REGISTRATION_REQUIRED` | 409 Conflict |
| `ERR_REGISTRATION_NOT_SUBMITTED` | 409 Conflict |
| `ERR_REPORT_NOT_FLAGGABLE` | 409 Conflict |
| `ERR_REPORT_NOT_RESUBMITTABLE` | 409 Conflict |
| `ERR_REPORT_NOT_PAYABLE` | 409 Conflict |
| `ERR_CLASS_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ENROLLMENT_NOT_OPEN` | 409 Conflict |
| `ERR_CLAIM_NOT_APPROVABLE` | 409 Conflict |
| `ERR_CLAIM_NOT_PAYABLE` | 409 Conflict |
| `ERR_ALLOCATION_NOT_ACTIVABLE` | 409 Conflict |
| `ERR_ALLOCATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_PURCHASE_NOT_REQUESTED` | 409 Conflict |
| `ERR_PURCHASE_NOT_APPROVED` | 409 Conflict |
| `ERR_FUND_ON_COMPLIANCE_HOLD` | 409 Conflict |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_CERTIFICATION_REQUIREMENTS_NOT_MET` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM` | 409 Conflict |
| `ERR_CLASS_FULL` | 409 Conflict |
| `ERR_INSTRUCTOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_FACILITY_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_INVALID_ATTENDEE_LIST` | 400 Bad Request |
| `ERR_OVERTIME_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_APPRENTICE_NOT_HOUR_ELIGIBLE` | 400 Bad Request |
| `ERR_LINE_EMPLOYER_MISMATCH` | 400 Bad Request |
| `ERR_REMITTANCE_AMOUNT_MISMATCH` | 400 Bad Request |
| `ERR_INSUFFICIENT_FUND_AVAILABLE` | 402 Payment Required |
| `ERR_INSUFFICIENT_ALLOCATION_REMAINING` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_METHOD_NOT_ALLOWED` | 405 Method Not Allowed |
| `ERR_INTERNAL` | 500 Internal Server Error |

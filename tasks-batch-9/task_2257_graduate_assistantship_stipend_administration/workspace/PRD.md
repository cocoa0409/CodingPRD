# Graduate Assistantship Stipend Administration API — Product Requirements Document

## 1. Introduction

A graduate school pays its students through instruments that answer to three different masters at once. The academic side classifies an appointment as teaching, research or administrative work and expects a supervisor, a percentage effort and a defensible workload. The payroll side expects a pay-period calendar, a prorated gross amount per period and a lock that freezes the calendar before money moves. The sponsored-programs side expects every cent to be traceable to a grant, a departmental budget or a fellowship, with encumbrances that never quietly exceed what a sponsor authorised. Today these three views are reconciled by hand at the end of every term, and the reconciliation regularly discovers that a student was over-appointed, that a tuition remission was charged to a source that never permitted it, or that a non-renewal notice went out after the contractual deadline had already passed.

This document specifies the API that replaces that manual reconciliation. The service owns academic terms and their payroll calendars, the stipend and remission policy tables that govern each term, graduate students and their academic standing, departmental and sponsored funding sources, assistantship appointments with their cost-shared funding plans, the disbursements those appointments generate, the renewal reviews that decide whether an appointment continues, and the tax assessments that impute income when a tuition benefit exceeds the statutory exemption. Every one of those objects is a peer collection addressed by its own identifier; relationships are expressed by explicit reference fields carried in request payloads rather than by nesting resources inside one another.

Two design commitments run through the whole specification and should be read as load-bearing rather than incidental. First, **an appointment advances along two independent axes** — an approval axis and a disbursement axis — because a stipend can be frozen for a compliance reason without unwinding an approved academic appointment, and an approval can be withdrawn without erasing the payments already made. Second, **money is conserved at every step**: for any funding source, the amount a sponsor authorised always equals the sum of what is still available, what is encumbered, and what has been spent, and no operation in this API may break that identity even transiently.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every collection and every operation. Where §3 tells a business story, this section fixes the contract.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which that user acts. If either header is absent, or if `X-User-Role` is not one of the five declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not authorised for the addressed operation, the rejection is `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The five roles are `GradSchoolAdmin`, `DepartmentAdmin`, `GrantAccountant`, `FacultySupervisor`, and `StudentUser`.

A `GradSchoolAdmin` is the graduate school's central office. It owns term, calendar and policy configuration, student registration, appointment return, approval and activation, payroll scheduling and disbursement, appointment termination, effort-cap overrides, and the whole of tuition-benefit taxation. A `DepartmentAdmin` is the departmental appointment administrator: it drafts appointments and funding plans, submits them for review, and opens renewal reviews, but it cannot approve its own work. A `GrantAccountant` is the sponsored-programs accountant: it owns the funding-source lifecycle, commits an appointment's funding plan against its sources, and releases encumbrances. A `FacultySupervisor` records academic progress and certifies satisfactory academic progress for a renewal review, but may never issue the notice for a review it certified. A `StudentUser` is the appointee.

Four of those five roles carry an **opaque** identity. When `X-User-Role` is `GradSchoolAdmin`, `DepartmentAdmin`, `GrantAccountant`, or `FacultySupervisor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any row's `id`. It is, however, recorded wherever the specification says so — as `submitted_by_user_id` and `approved_by_user_id` on an appointment, as `cap_override_by_user_id` on a graduate student, and as `certified_by_user_id` and `issued_by_user_id` on a renewal decision — and the recorded values are later compared against a subsequent actor's `X-User-ID` to enforce segregation of duties. The `supervisor_user_id` field carried on an appointment is likewise an opaque identifier, supplied as input, naming the supervising `FacultySupervisor`.

`StudentUser` is the one **entity-backed** role. When `X-User-Role` is `StudentUser`, `X-User-ID` is the `id` of the acting `GraduateStudent`; ownership checks on any resource that references a `GraduateStudent` compare the resource's `student_id` to `X-User-ID`. A `StudentUser` reading a single student record, listing appointments, listing tax assessments, or acknowledging a renewal notice must be addressing its own records; addressing another student's is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). For a renewal notice the comparison runs through the notice's appointment: the appointment's `student_id` must equal `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of rows returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of rows to skip; it defaults to 0 and its minimum accepted value is 0. A `limit` outside the range 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, alongside `api_request_id` and `api_request_timestamp`.

Unless a specific list says otherwise, rows are returned sorted by `created_at` ascending. Three lists override that default because a domain ordering is more useful than creation order: a term's pay-period calendar is ordered by `sequence_no` ascending; funding allocations are ordered by `plan_sequence` ascending and then by `created_at` ascending; and stipend disbursements are ordered by the `sequence_no` of the pay period each one pays, ascending.

### 2.4. Term Gating and the Calendar Cascade

The `AcademicTerm` is the outermost frame of the system, and its `status` gates what may happen inside it. A term begins in `PLANNING`, becomes `OPEN` for appointment activity, then `PAYROLL_LOCKED` when the payroll calendar is frozen, and finally `CLOSED`, which is terminal. Almost every appointment-side mutation requires the governing term to be exactly `OPEN`; a mutation attempted against a term in any other state is rejected with `ERR_TERM_NOT_OPEN` (HTTP 409). Two configuration operations are deliberately looser or stricter than that: declaring a stipend policy is accepted while the term is either `PLANNING` or `OPEN`, and appending a pay period is accepted only while the term is `PLANNING`. Where an operation needs the term to be in a state other than `OPEN` — terminating an appointment, for example, which is permitted while the term is either `OPEN` or `PAYROLL_LOCKED` — a state mismatch surfaces as `ERR_INVALID_TERM_STATE` (HTTP 409).

State changes propagate downward, and the server performs those propagations itself without any client request against the affected child. When a term is locked, every pay period of that term still in `OPEN` moves to `LOCKED`. When a term is closed, every pay period of that term still in `LOCKED` moves to `CLOSED`, and a conditional appointment cascade fires; that cascade in turn moves funding allocations, and the allocation moves in turn recompute funding-source balances. The full chain is spelled out in §3.9, but the principle to internalise here is that a single client call can legitimately mutate rows in four different collections.

Every mutation — whether client-driven or server-driven inside a cascade — refreshes the mutated row's `updated_at` to the current logical-clock instant and increments its `version` by exactly one. This applies to derived fields as much as to input fields: when an appointment's submission recomputes a student's `total_effort_pct`, that recomputation is a mutation of the `GraduateStudent` row and increments the student's `version`. It also applies to a funding source whose `committed_amount_cents`, `expended_amount_cents` and `available_amount_cents` are recomputed as a consequence of an allocation moving state.

### 2.5. Record Identity, Audit Fields and Term Sub-Resource Reads

Every resource in this API — academic terms, departments, stipend policies, pay periods, graduate students, funding sources, appointments, funding allocations, stipend disbursements, renewal decisions and tax assessments alike — carries the same four system-managed properties:

- `id` (string): a server-minted UUID. It carries no type prefix of any kind.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits, recording the logical-clock instant at which the row was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the row.
- `version` (integer): an integer that starts at 1 on creation and increments by one on every mutation, including mutations performed by a server-driven cascade.

No entity in this system is exempt from `updated_at` or `version`; all eleven collections carry both.

Two reads are addressed as sub-resources of a term rather than as top-level collections, because they exist so that a client holding only a term identifier can discover the term's configuration: the term's stipend policies and the term's pay-period calendar. For any path containing more than one identifier segment, the server resolves segments strictly left to right and rejects on the first segment that names no row. A request for the pay-period calendar of a non-existent term therefore returns `ERR_TERM_NOT_FOUND` (HTTP 404) before any filter or pagination parameter is examined. The same left-to-right discipline applies to every path-addressed operation: the addressed row's existence is established before its state is inspected, and its state is inspected before any business rule is evaluated.

### 2.6. Cents, Rounding and the Two Rounding Disciplines

All monetary amounts in this system are integers denominated in cents. There are no fractional cents anywhere in a stored value, in a request payload or in a response body. A field name ending in `_cents` is always an integer.

Two distinct rounding disciplines are used, and confusing them produces wrong answers that are only a cent or two off — which is exactly why the discipline is pinned per calculation rather than left global.

**Round half up to a whole cent** is used wherever a single amount is derived from a rate, a proportion or a duration: a pay period's prorated gross, a gross tuition remission, a funded remission, an insurance subsidy, and an imputed withholding amount are each rounded half up. Where several such amounts are later summed — the term's total stipend, for instance — each component is rounded to a whole cent first and the rounded components are then added. The sum is never taken in unrounded form and rounded at the end.

**Truncate toward zero, then assign the whole remainder** is used wherever one amount is split across several funding allocations. Each allocation's share is computed and truncated toward zero to a whole cent; the shortfall between the basis and the sum of the truncated shares is then handed in its entirety to the first allocation in a pinned ordering. That ordering is `share_pct` descending, and where two allocations declare the same `share_pct`, `plan_sequence` ascending. Rounding each line half up and summing is explicitly not the algorithm used, because it does not guarantee that the assigned amounts add back to the basis exactly.

Non-monetary rounding appears in exactly one place: weekly hours are carried to one decimal place, rounded half up.

Every threshold and cap comparison in this specification is inclusive on the boundary unless the text says otherwise. A value exactly equal to a cap passes the cap check; a value exactly equal to a minimum satisfies the minimum; a band whose lower bound is stated as "at least" admits the boundary value.

### 2.7. Funding Conservation and the Encumbrance Ledger

A funding source's money is described by four integers: `authorized_amount_cents`, which the sponsor or the department fixed and which the system never changes; and three derived amounts, `committed_amount_cents`, `expended_amount_cents` and `available_amount_cents`. The conservation identity that must hold at all times is that `authorized_amount_cents` equals `available_amount_cents` plus `committed_amount_cents` plus `expended_amount_cents`.

The three derived amounts are recomputed from scratch — never adjusted by a delta — whenever any funding allocation charged to the source changes status, whenever a disbursement is paid or reversed, and whenever a term closes. The recomputation is a pure aggregation over the allocations charged to that source, and no rounding occurs inside it because every input is already a whole number of cents:

- `committed_amount_cents` is the sum, over the source's allocations whose `status` is `COMMITTED`, of that allocation's `allocated_stipend_cents` plus its `allocated_remission_cents` minus its `disbursed_amount_cents`.
- `expended_amount_cents` is the sum of `disbursed_amount_cents` over the source's allocations whose `status` is `COMMITTED`, plus the sum of `allocated_stipend_cents` plus `allocated_remission_cents` over the source's allocations whose `status` is `EXPENDED`.
- `available_amount_cents` is `authorized_amount_cents` minus `committed_amount_cents` minus `expended_amount_cents`.

Allocations in `PROPOSED` never encumber anything: a drafted funding plan has no fiscal effect until it is committed. Allocations in `RELEASED` contribute nothing either, because releasing an allocation zeroes both `allocated_stipend_cents` and `allocated_remission_cents` as part of the release itself.

The `COMMITTED` state is the branch point of the whole ledger, and the two branches out of it have deliberately different fiscal meanings. On the `COMMITTED → RELEASED` branch, money returns to `available_amount_cents`: the allocated amounts are zeroed, so the source's committed total drops and its available total rises by the same amount. On the `COMMITTED → EXPENDED` branch, money does not return to available: the allocation's `disbursed_amount_cents` is raised to `allocated_stipend_cents` plus `allocated_remission_cents`, so the source's committed total drops and its expended total rises by the same amount while `available_amount_cents` is unchanged. Both branches preserve the conservation identity; only one of them frees budget for reuse.

### 2.8. Stale-Read Protection on Funding Plans and Tax Assessments

Two write operations carry an optimistic-concurrency check, because both of them legitimately supersede data the client may not have observed.

Replacing an appointment's funding plan requires the request to carry `expected_appointment_version`, a non-optional field holding the `version` of the `Appointment` as the client last read it. If that value does not equal the appointment's current `version`, the replacement is rejected with `ERR_STALE_APPOINTMENT_VERSION` (HTTP 412). The check exists because a funding-plan replacement supersedes the entire previous allocation set: without it, a replace built on a stale read would silently discard allocations the client never saw. A successful replacement increments the appointment's `version` by one, so a second replacement must re-read the appointment first.

Creating a tuition-benefit tax assessment requires the request to carry `expected_student_version`, a non-optional field holding the `version` of the `GraduateStudent` as the client last read it. If that value does not equal the student's current `version`, the creation is rejected with `ERR_STALE_STUDENT_VERSION` (HTTP 412). The check exists because a new assessment supersedes the prior provisional assessment for the same student-and-term pair, and because the student's remission-derived aggregates move whenever an appointment is submitted, terminated or finalized — a stale view would assess the wrong benefit. A successful creation increments the student's `version` by one.

No other operation in this API accepts a version field, and no other operation performs a version comparison. Endpoints not named in this subsection take no `expected_*_version` input.

### 2.9. Workload Caps, Effort Aggregation and Segregation of Duties

Percentage effort is the currency of workload in this system, and it converts to hours at a fixed rate: a full-time week is 40 hours, so 100 percent effort is 40 hours per week and any `effort_pct` maps to that fraction of 40 hours, carried to one decimal place and rounded half up. A student registered with the default configuration may hold an aggregate of at most 75 percent effort across appointments whose date windows overlap; that default is what `effort_cap_pct` is initialised to.

Raising a student's `effort_cap_pct` is an exceptional act, and it is deliberately expensive. A `GradSchoolAdmin` raising the cap must supply both the new ceiling and a written justification, and the server records the acting `X-User-ID` on the student row. From that moment the recorded user is barred from approving any appointment for that student: an approval attempted by the same user who raised the cap is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The rationale is that the person who authorised the exception must not also be the person who consumes it.

A second, structurally identical separation governs renewal reviews. The user who certifies satisfactory academic progress on a review may not be the user who issues that review's notice; an issuance attempted by the certifying user is rejected with the same `ERR_SEGREGATION_OF_DUTIES`. These are the only two segregation-of-duties rules in the system, and both compare a stored user identifier against the current request's `X-User-ID`.

International students carry a third, sharper restriction. A student flagged as international may work at most 20.0 hours per week in total during a term whose `session_type` is `IN_SESSION`, counting both assistantship hours and any non-assistantship university employment. A total of exactly 20.0 hours passes; anything above it is rejected with `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED` (HTTP 422). The restriction does not apply during a term whose `session_type` is `BREAK`, and it does not apply to domestic students.

### 2.10. Validation Ordering and the Logical Clock

When several checks could reject the same request, the order in which they are evaluated is fixed system-wide, because the error a client receives must be deterministic. The server evaluates, in this exact sequence, stopping at the first failure:

1. **Authentication** — `X-User-Role` and `X-User-ID` are present and `X-User-Role` is a declared role, else `ERR_UNAUTHENTICATED` (401).
2. **Authorisation** — the authenticated role appears in the addressed operation's role list, else `ERR_ROLE_NOT_PERMITTED` (403).
3. **Student ownership** — when the acting role is `StudentUser`, `X-User-ID` equals the `student_id` of the addressed resource, else `ERR_NOT_RESOURCE_OWNER` (403). This applies to reading one student, listing appointments with a `student_id` filter, listing tax assessments with a `student_id` filter, and acknowledging a renewal notice.
4. **Path existence** — every identifier segment in the path resolves, left to right, to an existing row. The error is the one belonging to the addressed collection: `ERR_TERM_NOT_FOUND`, `ERR_DEPARTMENT_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_RENEWAL_DECISION_NOT_FOUND`, or `ERR_ASSESSMENT_NOT_FOUND`, each with HTTP 404.
5. **Body reference existence** — reference fields in the request body resolve to existing rows, checked in this declaration order: `term_id`, `department_id`, `student_id`, `funding_source_id`, `appointment_id`, `renewed_from_appointment_id`. Each yields its collection's 404 error.
6. **Request shape** — required fields present, enum values within their declared sets, dates formatted as ISO 8601 calendar dates, `effort_pct` within 1 through 100, `share_pct` within 0.01 through 100.00 with at most two decimal places, an `allocations` array holding between 1 and 5 elements, `limit` within 1 through 100, `offset` at least 0, `end_date` on or after `start_date`, and `period_end_exclusive` strictly after `period_start`. Any failure is `ERR_INVALID_REQUEST` (422).
7. **Appointment version match** — `expected_appointment_version` equals the appointment's `version`, else `ERR_STALE_APPOINTMENT_VERSION` (412).
8. **Student version match** — `expected_student_version` equals the student's `version`, else `ERR_STALE_STUDENT_VERSION` (412).
9. **Uniqueness** — `term_code` is unique across academic terms (`ERR_DUPLICATE_TERM_CODE`), `student_number` across graduate students (`ERR_DUPLICATE_STUDENT_NUMBER`), `source_code` across funding sources (`ERR_DUPLICATE_FUNDING_SOURCE_CODE`), one stipend policy per combination of `term_id`, `assistantship_type` and `degree_level` (`ERR_DUPLICATE_STIPEND_POLICY`), and one pay period per combination of `term_id` and `sequence_no` (`ERR_DUPLICATE_PAY_PERIOD_SEQUENCE`). All are HTTP 409.
10. **Addressed-resource state** — the addressed row is in a state that permits the requested transition, else the state error for that collection: `ERR_INVALID_TERM_STATE`, `ERR_INVALID_APPOINTMENT_STATE`, `ERR_INVALID_ALLOCATION_STATE`, `ERR_INVALID_DISBURSEMENT_STATE`, `ERR_INVALID_RENEWAL_STATE`, or `ERR_INVALID_ASSESSMENT_STATE`, each HTTP 409.
11. **Governing term open** — the governing term's `status` is `OPEN`, else `ERR_TERM_NOT_OPEN` (409). This guards declaring a stipend policy (which also accepts a `PLANNING` term), replacing a funding plan, and appointment submission, return, funding verification, approval, activation and payroll scheduling.
12. **Funding source active** — every funding source referenced by an allocation being committed has `status` equal to `ACTIVE`, else `ERR_FUNDING_SOURCE_NOT_ACTIVE` (409).
13. **Pay period locked** — the disbursement's pay period has `status` equal to `LOCKED`, else `ERR_PAY_PERIOD_NOT_LOCKED` (409).
14. **International hour limit** — `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED` (422), as described in §2.9.
15. **Satisfactory academic progress** — `ERR_SAP_NOT_SATISFACTORY` (422), guarding appointment approval and renewal certification.
16. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403), guarding renewal notice issuance and appointment approval.
17. **Aggregate effort cap** — `ERR_OVER_APPOINTMENT` (422).
18. **Dual-role conflict** — `ERR_DUAL_ROLE_CONFLICT` (409).
19. **Term calendar completeness** — `ERR_TERM_CALENDAR_INCOMPLETE` (422), guarding term opening.
20. **Unresolved appointments** — `ERR_UNRESOLVED_APPOINTMENTS` (409), guarding payroll locking.
21. **Unsettled disbursements and assessments** — `ERR_UNSETTLED_DISBURSEMENTS` (409), guarding term closing.
22. **Appointment window inside the term** — `ERR_APPOINTMENT_DATES_OUTSIDE_TERM` (422), guarding appointment creation.
23. **Pay period overlap** — `ERR_PAY_PERIOD_OVERLAP` (409), guarding pay-period creation.
24. **Funding budget window coverage** — `ERR_FUNDING_PERIOD_MISMATCH` (422).
25. **Renewal window open** — `ERR_RENEWAL_WINDOW_NOT_OPEN` (422), guarding renewal-review creation.
26. **Notice deadline** — `ERR_NOTICE_DEADLINE_PASSED` (422), guarding notice issuance.
27. **Funding plan present** — `ERR_FUNDING_ALLOCATION_MISSING` (422).
28. **Shares total** — `ERR_ALLOCATION_SHARES_INVALID` (422).
29. **Cost-share composition** — `ERR_COST_SHARE_SOURCE_INVALID` (422).
30. **Stipend policy present** — `ERR_STIPEND_POLICY_MISSING` (422), guarding both appointment creation and appointment submission.
31. **Fellowship service conflict** — `ERR_FELLOWSHIP_SERVICE_CONFLICT` (422).
32. **Renewal review uniqueness** — `ERR_RENEWAL_DECISION_EXISTS` (409).
33. **Assessment already final** — `ERR_ASSESSMENT_ALREADY_FINAL` (409).
34. **Stipend minimum** — `ERR_STIPEND_BELOW_MINIMUM` (422).
35. **Grant effort cap** — `ERR_GRANT_EFFORT_CAP_EXCEEDED` (422).
36. **Funding sufficiency** — `ERR_FUNDING_INSUFFICIENT` (422), guarding funding verification.
37. **Allocation not yet disbursed** — `ERR_ALLOCATION_PARTIALLY_DISBURSED` (409), guarding allocation release.
38. **Allocation not locked by approval** — `ERR_ALLOCATION_LOCKED_BY_APPROVAL` (409), guarding allocation release.
39. **Source has no commitments** — `ERR_FUNDING_SOURCE_HAS_COMMITMENTS` (409), guarding source closure.
40. **Assessment delta present** — `ERR_NO_ASSESSMENT_DELTA` (409), guarding amendment.

Because so much of this domain is date-driven — remission deadlines, renewal windows, notice deadlines — the server does not read wall-clock time. It maintains a **logical clock** whose value at startup is exactly `2026-08-01T00:00:00Z`, and which never falls back to real time. An administrative test-driving capability repositions that clock: it accepts a single field, `to_iso8601`, and answers with the resulting instant as `current_utc`. Repositioning the clock mutates no entity; it only changes what "now" means for every subsequent request. Wherever this document says "the current logical-clock instant" or "the current logical-clock date", it means that value.

## 3. Business Logic & Workflows

### 3.1. Building the Term Frame: Terms, Pay Periods and Stipend Policies

Configuration begins with an `AcademicTerm`, created by a `GradSchoolAdmin` in the `PLANNING` state. The creating payload names the term with a human-readable `term_code` of 1 to 32 characters that must be unique across all terms, fixes the term's inclusive calendar boundaries as `term_start` and `term_end` (the latter on or after the former), declares the `tax_calendar_year` between 2000 and 2100 whose tuition-benefit exemption this term will consume, and states two enumerated behaviours. The `session_type` is either `IN_SESSION`, meaning an instructional session during which international hour restrictions bite, or `BREAK`, meaning a between-terms period during which they do not. The `proration_method` is either `CALENDAR_DAY` or `WORKDAY`, and it decides which of the two proration variants the term's payroll uses. Finally, `remission_drop_deadline` is a calendar date that must fall on or between `term_start` and `term_end`; it is the date on or after which a terminated appointment keeps its tuition remission rather than forfeiting it. A newly created term has `pay_period_count` of 0 and both `locked_at` and `closed_at` null.

Into a `PLANNING` term a `GradSchoolAdmin` appends the payroll calendar one period at a time. A `PayPeriod` names its `term_id`, carries a `sequence_no` between 1 and 24 that must be unique within the term, and defines its coverage in half-open form: `period_start` is the first date covered and `period_end_exclusive` is the first date **not** covered, so `period_end_exclusive` must be strictly after `period_start`. The `pay_date` on which the period's stipend is disbursed must fall on or after `period_end_exclusive`. Two counts are derived at creation and stored: `calendar_day_count`, the number of whole days from `period_start` up to but excluding `period_end_exclusive`, and `workday_count`, the number of Monday-through-Friday dates in that same half-open range. A new period must not overlap an existing period of the same term; overlap is judged under half-open semantics, so the request is rejected with `ERR_PAY_PERIOD_OVERLAP` when the new period's `period_start` falls before an existing period's `period_end_exclusive` **and** that existing period's `period_start` falls before the new period's `period_end_exclusive`. Exact adjacency — a new period starting on the very date an existing period stops covering — is explicitly allowed. Each accepted period recomputes the term's `pay_period_count`, which is simply the number of pay periods whose `term_id` is that term. A period is born `OPEN` and later moves to `LOCKED` and then `CLOSED` with its term.

The money rules for a term live in its `StipendPolicy` rows, and there is exactly one policy per combination of `term_id`, `assistantship_type` and `degree_level`. The `assistantship_type` is `TEACHING`, `RESEARCH` or `ADMINISTRATIVE`; the `degree_level` is `MASTERS` or `DOCTORAL`. A policy declares `min_fte_monthly_stipend_cents`, the minimum full-time-equivalent monthly stipend of at least 1 cent; `per_credit_tuition_cents`, the tuition charge per enrolled credit hour of at least 1 cent; `max_remission_cents_per_term`, a hard ceiling of at least 1 cent on the tuition remission any single appointment may draw in the term; and `term_insurance_premium_cents`, the full term health-insurance premium before subsidy, which may be zero. Three further settings have defaults and may be omitted: `insurance_min_effort_pct`, the minimum appointment effort percentage for insurance eligibility, defaults to 50 and must lie between 1 and 100; `min_insurance_duration_days`, the minimum inclusive appointment duration in days for insurance eligibility, defaults to 90 and must be at least 1; and `tuition_tax_exempt_cap_cents`, the per-calendar-year tuition-benefit amount shielded from imputed income, defaults to 525000 — five thousand two hundred fifty dollars — and may be zero or more. All policies belonging to one term must declare the same `tuition_tax_exempt_cap_cents`, because the taxation calculation reads that cap from the term rather than from a particular policy.

Opening a term is the act of declaring the frame complete, and it moves the term `PLANNING → OPEN`. It requires the term to be in `PLANNING`, and it requires the calendar and the policy table each to be non-empty: at least one pay period and at least one stipend policy must reference the term, or the request is rejected with `ERR_TERM_CALENDAR_INCOMPLETE`. On success the term's `status` becomes `OPEN` and `pay_period_count` is recomputed. Any of the five operational roles may read a term afterwards, including its computed `pay_period_count`, and may discover its configuration through the two term-scoped reads: the stipend-policy list, which accepts optional `assistantship_type`, `degree_level`, `limit` and `offset` filters, and the pay-period list, which accepts optional `status`, `limit` and `offset` filters.

### 3.2. Departments, Students and Academic Standing

A `Department` is the appointing unit. It is created with a short `code` of 1 to 16 characters — which, unlike a term code, need not be unique — and a display `name`. It also carries `non_renewal_notice_days`, the number of days before an appointment's `end_date` by which a non-renewal notice must be issued; it defaults to 60 and must lie between 1 and 180. That single number is what turns a department's local practice into an enforceable contractual deadline later in the renewal workflow.

A `GraduateStudent` is registered with a registrar `student_number` unique across all students, a `full_name`, a `degree_level` of `MASTERS` or `DOCTORAL`, the boolean `is_international` flag that marks a non-immigrant visa holder subject to hour restrictions, and a `cumulative_gpa` between 0.00 and 4.00 carried to two decimal places. Three inputs are optional: `visa_type`, one of `F1`, `J1` or `NONE` and defaulting to `NONE`; `enrolled_credit_hours` between 0 and 24 and defaulting to 0, which is read at appointment submission time to size the tuition remission; and `external_weekly_hours` between 0.0 and 40.0 to one decimal place and defaulting to 0, which counts non-assistantship university employment against the international hour ceiling.

Registration also establishes the student's system-managed standing. The `sap_status` — satisfactory academic progress — starts at `SATISFACTORY` and may later be `PROBATION` or `UNSATISFACTORY`. The `effort_cap_pct` starts at 75 and may be between 1 and 100 thereafter; it is raised only through the effort-cap override capability, and `cap_override_by_user_id` and `cap_override_justification` both start null. Four aggregates start at 0: `total_effort_pct`, the aggregate percentage effort over the student's counted appointments; `assigned_hours_per_week`, that aggregate expressed in weekly hours; `tuition_benefit_ytd_cents`, the sum of `benefit_cents` over the student's `FINAL` tax assessments in the current `tax_calendar_year`; and `taxable_tuition_benefit_ytd_cents`, the corresponding sum of `taxable_cents`.

Recording academic progress is shared between a `FacultySupervisor` and a `GradSchoolAdmin`, and the payload is entirely optional-field: any combination of `sap_status`, `cumulative_gpa`, `enrolled_credit_hours` and `external_weekly_hours` may be patched. The patched fields are written and the student's `version` is incremented. The consequential part is what happens when `sap_status` becomes either `PROBATION` or `UNSATISFACTORY`: every renewal review belonging to an appointment of that student and currently sitting in `SAP_CERTIFIED` is forced back to `DRAFT`, its `sap_certified` flag reset to false, its `certified_by_user_id` and `certified_at` cleared, and its `revision_count` increased by one. A downgrade in standing therefore invalidates a certification that has not yet produced a notice, and the review must be certified again from scratch.

The effort-cap override is a `GradSchoolAdmin` capability that raises a single student's ceiling. It takes `approved_max_effort_pct`, which becomes the student's new `effort_cap_pct`, and `justification`, which is stored as `cap_override_justification`; the acting `X-User-ID` is stored as `cap_override_by_user_id` and the student's `version` is incremented. As §2.9 states, the recorded user is thereafter barred from approving that student's appointments.

Reading a student returns the effort and tuition-benefit aggregates alongside the input fields, and is available to all five roles — with a `StudentUser` restricted to its own row.

### 3.3. Funding Sources and the Encumbrance Ledger

A `FundingSource` is an account against which appointment costs may be charged. Either a `GrantAccountant` or a `GradSchoolAdmin` may create one, naming the administering department through `department_id`, giving the account a `source_code` that must be unique across all sources, and a `source_type` of `GRANT`, `DEPARTMENTAL_BUDGET` or `FELLOWSHIP`. The payload fixes `authorized_amount_cents` of at least 1 cent, an inclusive budget window from `budget_period_start` to `budget_period_end` where the end is on or after the start, and the boolean `allows_tuition_remission` deciding whether tuition remission may be charged to the source at all. Three optional inputs complete the picture: `sponsor_code`, an external sponsor identifier that defaults to null and stays null for internal budgets; `grant_effort_cap_pct`, the maximum effort percentage a single appointment may draw from the source, defaulting to 100, constrained to 1 through 100, and enforced only when `source_type` is `GRANT`; and `auto_reinstate_threshold_cents`, defaulting to 0 and at least 0, which is the `available_amount_cents` level at or above which an over-commitment suspension clears itself. A new source is `ACTIVE`, has `committed_amount_cents` and `expended_amount_cents` of 0, `available_amount_cents` equal to `authorized_amount_cents`, and `suspension_reason` null.

A `GrantAccountant` may suspend an `ACTIVE` source, supplying a `reason` that is stored as `suspension_reason` and must be `SPONSOR_HOLD`, `OVERCOMMITMENT` or `AUDIT`. Suspension moves the source `ACTIVE → SUSPENDED` and blocks new commitments; it deliberately leaves existing `COMMITTED` allocations untouched, because a sponsor hold is not a clawback. Reinstatement moves a `SUSPENDED` source back to `ACTIVE` and clears `suspension_reason` to null. There is also a server-driven path back to `ACTIVE`: whenever an allocation release raises a source's `available_amount_cents`, a source that is `SUSPENDED` with `suspension_reason` of exactly `OVERCOMMITMENT` and whose `available_amount_cents` has reached or passed its `auto_reinstate_threshold_cents` returns to `ACTIVE` with `suspension_reason` cleared, with no client request against the source. Only over-commitment suspensions clear themselves this way; a `SPONSOR_HOLD` or `AUDIT` suspension requires the explicit reinstatement call regardless of how much budget frees up.

Closing a source is permitted from either `ACTIVE` or `SUSPENDED` and moves it to the terminal `CLOSED` with `suspension_reason` cleared, but only when `committed_amount_cents` is exactly 0; a source still carrying encumbrances is rejected with `ERR_FUNDING_SOURCE_HAS_COMMITMENTS`. Sources may be read individually, showing the balance triple, or listed with optional `department_id`, `source_type`, `status`, `limit` and `offset` filters.

### 3.4. Drafting an Appointment and Its Cost-Shared Funding Plan

A `DepartmentAdmin` creates an `Appointment` in `DRAFT`. The payload names the appointee through `student_id`, the appointing unit through `department_id`, and the paying term through `term_id`; classifies the work through `assistantship_type` as `TEACHING`, `RESEARCH` or `ADMINISTRATIVE`; states `effort_pct` between 1 and 100; fixes the inclusive appointment window as `start_date` and `end_date`, the latter on or after the former; states the contracted `monthly_stipend_cents` of at least 1 cent at the stated effort; and names the supervising faculty member through `supervisor_user_id`. An optional `renewed_from_appointment_id` names the predecessor appointment this one renews and is null for a first appointment; that self-reference is what makes a renewal chain traceable and what the successor-cancellation cascade later walks.

Creation enforces two rules of its own. The appointment window must sit inside the term: the term's `term_start` must be on or before `start_date`, and `end_date` must be on or before the term's `term_end`, or the request is rejected with `ERR_APPOINTMENT_DATES_OUTSIDE_TERM`. And a governing policy must exist — the single stipend policy whose `term_id`, `assistantship_type` and `degree_level` equal the appointment's `term_id`, the appointment's `assistantship_type`, and the referenced student's `degree_level` — or the request is rejected with `ERR_STIPEND_POLICY_MISSING`.

With those satisfied, creation derives the appointment's **effort profile** immediately. The `weekly_hours` field is `effort_pct` divided by 100, multiplied by the 40 hours of a full-time week, rounded half up to one decimal place. The `duration_days` field is the count of whole days from `start_date` to `end_date` counting both endpoints — the difference in days plus one. The boolean `insurance_eligible` is true only when both conditions hold: `effort_pct` is at least the policy's `insurance_min_effort_pct`, and `duration_days` is at least the policy's `min_insurance_duration_days`; otherwise it is false. And `tuition_remission_pct` is selected from `effort_pct` by band: 0 when `effort_pct` is below 25; 50 when `effort_pct` is at least 25 and below 50; 75 when `effort_pct` is at least 50 and below 75; and 100 when `effort_pct` is at least 75. A newly drafted appointment sits at `lifecycle_status` of `DRAFT` and `payroll_status` of `NOT_SCHEDULED`, has `renewal_eligible` true, has `submitted_by_user_id`, `approved_by_user_id`, `return_reason`, `pay_suspension_reason`, `termination_reason` and `termination_date` all null, and leaves every cents-valued computed field at 0 until submission: `projected_pay_period_count`, `total_stipend_cents`, `tuition_remission_cents`, `insurance_subsidy_cents`, `employee_premium_cents` and `net_term_stipend_cents`.

The **funding plan** is authored separately, by either a `DepartmentAdmin` or a `GrantAccountant`, and it is always replaced wholesale rather than edited. The payload carries `allocations`, an array of 1 to 5 objects each holding a `funding_source_id`, a `share_pct` between 0.01 and 100.00 with at most two decimal places, and an optional `is_cost_share` boolean defaulting to false that marks the institution's cost-share contribution. It also carries `expected_appointment_version`, the optimistic-concurrency field described in §2.8. Replacement is accepted only while the appointment's `lifecycle_status` is `DRAFT`, `RETURNED` or `SUBMITTED`, and only while the governing term is `OPEN`.

Replacement proceeds in two movements. First, every existing `FundingAllocation` of the appointment whose `status` is `PROPOSED` or `COMMITTED` moves to the terminal `RELEASED` with `release_reason` set to `PLAN_SUPERSEDED` and both `allocated_stipend_cents` and `allocated_remission_cents` zeroed. Second, one new `FundingAllocation` row is created per element of `allocations`, each in `PROPOSED`, each carrying the appointment's identifier as `appointment_id`, the element's `funding_source_id`, `share_pct` and `is_cost_share`, and each stamped with `plan_sequence` equal to its 1-based index in the submitted array. That `plan_sequence` is not decoration: it is the pinned tie-break key that makes every subsequent per-allocation split deterministic when two allocations declare the same `share_pct`. New rows have `allocated_stipend_cents`, `allocated_remission_cents` and `disbursed_amount_cents` all 0 and `release_reason` null. Every funding source touched by either movement has its balances recomputed, and the appointment's `version` is incremented by one.

Allocations are read individually — showing both allocated and disbursed amounts — or listed with optional `appointment_id`, `funding_source_id`, `status`, `limit` and `offset` filters. That list is the only discovery channel for allocation rows the server created or moved inside a cascade, which is why it exists as a top-level read.

### 3.5. Submission: The Compliance, Workload and Fiscal Battery

Submission is where the system earns its keep. A `DepartmentAdmin` submits an appointment, advancing it `DRAFT → SUBMITTED`, and the same operation advances a returned appointment `RETURNED → SUBMITTED` under an identical battery of checks and with identical side effects — the review loop is a cycle, and re-submission is not a weaker path than first submission. Submission is accepted from either `DRAFT` or `RETURNED` and from no other state.

The checks run in the global order of §2.10, which means the client sees them in this sequence. The governing term must be `OPEN` (`ERR_TERM_NOT_OPEN`). Then the **international hour ceiling**: when the student is international and the term's `session_type` is `IN_SESSION`, the student's `assigned_hours_per_week` computed with this appointment included, plus the student's `external_weekly_hours`, must not exceed 20.0 hours; exactly 20.0 passes, more is `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED`. Then the **aggregate effort cap**: the student's `total_effort_pct` computed with this appointment included must not exceed the student's `effort_cap_pct`, with a value exactly equal to the cap passing and anything above rejected as `ERR_OVER_APPOINTMENT`. Then the **dual-role conflict**: taking the set of `assistantship_type` values over this appointment together with the student's counted appointments whose inclusive date windows intersect this one, that set must not contain both `TEACHING` and `ADMINISTRATIVE`; if it does, the submission is rejected with `ERR_DUAL_ROLE_CONFLICT`. A student may hold a teaching and a research appointment simultaneously, or an administrative and a research appointment, but not teaching and administrative at once.

The effort figures those two checks read come from a single aggregation. The **counted lifecycle states** are `SUBMITTED`, `FUNDING_VERIFIED`, `APPROVED`, `ACTIVE` and `NON_RENEWAL_PENDING`; appointments in `DRAFT`, `RETURNED`, `COMPLETED`, `TERMINATED` and `CANCELLED` are excluded from every effort figure. For the appointment under evaluation, the reference window is its own inclusive `start_date` through `end_date`. The overlapping set is every other appointment of the same student — excluding the candidate itself — that is in a counted state and whose `start_date` falls on or before the candidate's `end_date` while its `end_date` falls on or after the candidate's `start_date`; both ends of that intersection test are inclusive, so two appointments that merely touch on a single day do overlap. The aggregate `total_effort_pct` is the candidate's `effort_pct` plus the sum of `effort_pct` over that overlapping set. The `assigned_hours_per_week` figure is that aggregate divided by 100, multiplied by 40, rounded half up to one decimal place. The value persisted on the student row uses the same expression with the candidate dropped, taking its reference window from the most recently mutated counted appointment; when the student holds no counted appointment at all, the persisted aggregate is 0.

The funding plan is then examined. The appointment must have at least one allocation in `PROPOSED`; an empty plan is `ERR_FUNDING_ALLOCATION_MISSING`. The sum of `share_pct` over those `PROPOSED` allocations must equal exactly 100.00; anything else is `ERR_ALLOCATION_SHARES_INVALID`. **Cost-share composition** is checked next, in two halves that are equally binding: every allocation whose `is_cost_share` is true must reference a source whose `source_type` is `DEPARTMENTAL_BUDGET`, and a plan containing any cost-share allocation must also contain at least one allocation whose `is_cost_share` is false. A plan that is entirely cost share, or one that charges a cost-share line to a grant or fellowship, is rejected with `ERR_COST_SHARE_SOURCE_INVALID`. The governing stipend policy must still resolve (`ERR_STIPEND_POLICY_MISSING`). No allocation may reference a source whose `source_type` is `FELLOWSHIP` when the appointment's `assistantship_type` is `TEACHING`, because a fellowship may not purchase instructional service; violating that is `ERR_FELLOWSHIP_SERVICE_CONFLICT`. And every referenced source's budget window must cover the whole appointment window: the source's `budget_period_start` on or before the appointment's `start_date`, and the appointment's `end_date` on or before the source's `budget_period_end`, or `ERR_FUNDING_PERIOD_MISMATCH`.

Two fiscal checks close the battery. The **stipend minimum** compares the appointment's full-time-equivalent monthly rate against policy: take `monthly_stipend_cents`, multiply by 100, divide by `effort_pct`, round the result half up to a whole cent, and require it to be at least the policy's `min_fte_monthly_stipend_cents`; a value exactly equal to the minimum passes, below it is `ERR_STIPEND_BELOW_MINIMUM`. The **grant effort cap** applies to each allocation whose source has `source_type` of `GRANT`: the effort that allocation draws from the grant is `effort_pct` multiplied by that allocation's `share_pct` divided by 100, and it must not exceed the source's `grant_effort_cap_pct`; exactly equal passes, above is `ERR_GRANT_EFFORT_CAP_EXCEEDED`.

Once the battery passes, the appointment's `lifecycle_status` becomes `SUBMITTED`, `submitted_by_user_id` records the acting `X-User-ID`, and `return_reason` is cleared to null. Four calculations then run, in this order, and together they populate every money field on the appointment and on its allocations.

**First, the pay schedule is projected.** The appointment's inclusive window is treated as half-open by taking the day after `end_date` as the exclusive upper bound. Every pay period of the appointment's term is then walked in `sequence_no` ascending order, regardless of that period's own `status`. For each period, the overlap start is the later of the period's `period_start` and the appointment's `start_date`, and the overlap end is the earlier of the period's `period_end_exclusive` and the day after the appointment's `end_date`; if the overlap end falls on or before the overlap start, the period is skipped entirely and contributes nothing. For a period that is not skipped, two counts are taken according to the term's `proration_method`. Under `CALENDAR_DAY`, the covered count is the whole days from the overlap start up to but excluding the overlap end, and the period count is the whole days from `period_start` up to but excluding `period_end_exclusive`. Under `WORKDAY`, both counts instead tally only Monday-through-Friday dates in those same half-open ranges — which is why a weekend-heavy partial window pays a different amount under the two methods for otherwise identical inputs. That period's gross is `monthly_stipend_cents` multiplied by the covered count, divided by the period count, rounded half up to a whole cent. The appointment's `projected_pay_period_count` is the number of periods not skipped, and its `total_stipend_cents` is the sum of the per-period gross amounts — each rounded to a whole cent before the addition, never summed unrounded and rounded once at the end.

**Second, the tuition-remission entitlement is derived,** in a step order that is pinned: band, then credit cap, then gross, then funding-eligible share, then policy ceiling. The band percentage is the appointment's `tuition_remission_pct`. The remitted credit count is the smaller of the student's `enrolled_credit_hours` and the degree ceiling, which is 9 credits for a `MASTERS` student and 12 credits for a `DOCTORAL` student. The gross remission is the remitted credit count multiplied by the policy's `per_credit_tuition_cents`, multiplied by the band percentage, divided by 100, rounded half up to a whole cent. The **remission-eligible share** is the sum of `share_pct` over the appointment's allocations whose `status` is `PROPOSED` or `COMMITTED` and whose funding source has `allows_tuition_remission` true; allocations in `RELEASED` or `EXPENDED` are excluded from this and from every other figure in this calculation. The funded remission is the gross remission multiplied by that eligible share, divided by 100, rounded half up. Finally, `tuition_remission_cents` is the smaller of the funded remission and the policy's `max_remission_cents_per_term`.

That entitlement is then split across the eligible allocations only, using the truncate-then-remainder discipline of §2.6. The eligible allocations are ordered by `share_pct` descending and then by `plan_sequence` ascending. Each one's `allocated_remission_cents` is `tuition_remission_cents` multiplied by that allocation's `share_pct`, divided by the remission-eligible share, truncated toward zero to a whole cent. The difference between `tuition_remission_cents` and the sum of those truncated amounts is handed in its entirety to the first allocation in that ordering. Every allocation that is not remission-eligible gets `allocated_remission_cents` of 0. When the remission-eligible share is 0 — no allocation points at a source that permits remission — `tuition_remission_cents` is 0 and no split runs at all.

**Third, the stipend itself is split across sources.** The basis is the appointment's `total_stipend_cents`. The allocations whose `status` is `PROPOSED` or `COMMITTED` are ordered by `share_pct` descending and then `plan_sequence` ascending. Each one's `allocated_stipend_cents` is the basis multiplied by its `share_pct`, divided by 100, truncated toward zero to a whole cent. The remainder — the basis minus the sum of the truncated amounts, which is at least zero and strictly less than the number of allocations in the ordering — is handed in its entirety to the first allocation in that ordering. The invariant is that the assigned amounts add back to the basis exactly. Rounding each line half up and summing is explicitly not used here, because it can break that conservation.

**Fourth, insurance and the net stipend are computed,** in six steps that each run exactly once and in this order. The gross term stipend is the appointment's `total_stipend_cents`. The premium is the policy's `term_insurance_premium_cents` when `insurance_eligible` is true, and 0 when it is false. The subsidy tier is selected from that **pre-offset gross**: 90 percent when the gross is below twelve thousand dollars (1200000 cents); 75 percent when the gross is at least 1200000 cents and below eighteen thousand dollars (1800000 cents); and 50 percent when the gross is at least 1800000 cents. Then `insurance_subsidy_cents` is the premium multiplied by the tier percentage, divided by 100, rounded half up to a whole cent; `employee_premium_cents` is the premium minus that subsidy; and `net_term_stipend_cents` is the gross term stipend minus `employee_premium_cents`. The tier is keyed on the gross from the first step and never on the net produced by the last, because keying it on the net would select a lower tier whenever the gross sits just above a breakpoint.

Submission finally recomputes the student's `total_effort_pct` and `assigned_hours_per_week` and increments the student's `version`, because the student now carries effort it did not carry a moment ago.

### 3.6. Funding Verification, Approval and Activation

A `GrantAccountant` verifies funding, advancing the appointment `SUBMITTED → FUNDING_VERIFIED`. The appointment must be in `SUBMITTED` and the term must be `OPEN`. Every funding source referenced by one of the appointment's allocations must have `status` of exactly `ACTIVE`; a suspended or closed source is `ERR_FUNDING_SOURCE_NOT_ACTIVE`. And each referenced source must be able to bear the charge: taking that source's `available_amount_cents` and subtracting the sum, over this appointment's allocations charged to that source, of `allocated_stipend_cents` plus `allocated_remission_cents`, the result must be at least 0; a negative result is `ERR_FUNDING_INSUFFICIENT`. On success, every allocation of the appointment in `PROPOSED` moves to `COMMITTED`, and each affected source's `committed_amount_cents` and `available_amount_cents` are recomputed.

Approval by a `GradSchoolAdmin` advances the appointment `FUNDING_VERIFIED → APPROVED`. It requires `FUNDING_VERIFIED`, requires the term to be `OPEN`, requires the student's `sap_status` to be exactly `SATISFACTORY` — anything else is `ERR_SAP_NOT_SATISFACTORY` — and requires the acting `X-User-ID` to differ from the student's `cap_override_by_user_id`, the segregation-of-duties rule of §2.9 whose violation is `ERR_SEGREGATION_OF_DUTIES`. On success `approved_by_user_id` records the acting user. Activation, also a `GradSchoolAdmin` act, then advances `APPROVED → ACTIVE` against an `OPEN` term and changes nothing else.

Returning an appointment for revision is the reverse gear, and a `GradSchoolAdmin` may pull it from either `SUBMITTED` or `FUNDING_VERIFIED`, advancing the appointment to `RETURNED` against an `OPEN` term. The payload carries `return_reason`, which is stored. Because a return may be unwinding a verified plan, every allocation of the appointment whose `status` is `COMMITTED` moves to `RELEASED` with `release_reason` set to `APPOINTMENT_RETURNED` and both `allocated_stipend_cents` and `allocated_remission_cents` zeroed; each affected source then has its balances recomputed. The student's `total_effort_pct` is recomputed and the student's `version` incremented, since a `RETURNED` appointment is no longer a counted appointment. A returned appointment re-enters `SUBMITTED` through the same submission path, so the review loop can run any number of times.

A `GrantAccountant` may also release a single committed allocation directly, moving it `COMMITTED → RELEASED` with the supplied `release_reason`. Release requires the allocation to be in `COMMITTED` — otherwise `ERR_INVALID_ALLOCATION_STATE` — requires its `disbursed_amount_cents` to be exactly 0, since money already paid cannot be released (`ERR_ALLOCATION_PARTIALLY_DISBURSED`), and requires the funded appointment's `lifecycle_status` to be neither `APPROVED` nor `ACTIVE`, because an approved or active appointment's funding is locked (`ERR_ALLOCATION_LOCKED_BY_APPROVAL`). On success both allocated amounts are zeroed, the source's `committed_amount_cents` and `available_amount_cents` are recomputed, and a source that is `SUSPENDED` for `OVERCOMMITMENT` and has now reached its `auto_reinstate_threshold_cents` returns to `ACTIVE`. One further cascade fires: if the funded appointment's `lifecycle_status` was `FUNDING_VERIFIED`, it reverts to `RETURNED` with `return_reason` set to `FUNDING_RELEASED`, because an appointment cannot remain funding-verified once its funding has gone.

Appointments are read individually — returning both state axes and every computed money field — and listed with optional `student_id`, `department_id`, `term_id`, `renewed_from_appointment_id`, `lifecycle_status`, `payroll_status`, `limit` and `offset` filters. A `StudentUser` may use those reads only for its own rows.

### 3.7. The Payroll Axis: Scheduling, Payment, Suspension and Reversal

The disbursement axis moves independently of the approval axis, and `payroll_status` starts at `NOT_SCHEDULED`. A `GradSchoolAdmin` schedules payroll, advancing `NOT_SCHEDULED → SCHEDULED`; the appointment's `payroll_status` must be `NOT_SCHEDULED`, its `lifecycle_status` must be exactly `ACTIVE` — otherwise `ERR_INVALID_APPOINTMENT_STATE` — and the term must be `OPEN`.

Scheduling materialises the money. One `StipendDisbursement` row is created for each pay period of the term that intersects the appointment's window, using exactly the interval walk and the proration variant described in §3.5. Each row records its `appointment_id` and `pay_period_id`, snapshots the term's `proration_method` into `proration_method_applied` as either `CALENDAR_DAY` or `WORKDAY`, stores the period's overlap count as `covered_units` and the period's own count as `period_units`, and stores the prorated `gross_amount_cents`. Each row also stores an `allocation_split` array holding the per-source breakdown of its own `gross_amount_cents`: one element per allocation in the pinned ordering, each element carrying `funding_allocation_id` — the identifier of a `FundingAllocation` row belonging to the same appointment — the allocation's `plan_sequence`, and the `amount_cents` charged to it. That per-period split uses the same truncate-then-remainder algorithm as the plan-level split, with the period's `gross_amount_cents` as the basis instead of the appointment's `total_stipend_cents`. Each new row is `SCHEDULED` with `paid_at`, `voided_at`, `reversed_at` and `reversal_reason` all null. Because the projection at submission and the materialisation here walk the same periods with the same arithmetic, the created rows' gross amounts add up to the `total_stipend_cents` projected at submission.

Paying a disbursement is a `GradSchoolAdmin` act that moves it `SCHEDULED → PAID` and stamps `paid_at` with the current logical-clock instant. The disbursement must be `SCHEDULED` (`ERR_INVALID_DISBURSEMENT_STATE`), its pay period's `status` must be exactly `LOCKED` — an `OPEN` or already-`CLOSED` period yields `ERR_PAY_PERIOD_NOT_LOCKED` — and the appointment's `payroll_status` must be `SCHEDULED` or `PARTIALLY_DISBURSED`, else `ERR_INVALID_APPOINTMENT_STATE`. Payment moves money along the ledger: for each element of `allocation_split`, the named allocation's `disbursed_amount_cents` is increased by that element's `amount_cents`, and the corresponding source's `committed_amount_cents` falls while its `expended_amount_cents` rises by that same amount. Payment then advances the appointment's payroll axis: `payroll_status` becomes `PARTIALLY_DISBURSED` when at least one sibling disbursement of the same appointment remains `SCHEDULED` after this payment, and `FULLY_DISBURSED` when none does. Those are the `SCHEDULED → PARTIALLY_DISBURSED` and `PARTIALLY_DISBURSED → FULLY_DISBURSED` moves on the payroll axis, and `FULLY_DISBURSED` is terminal.

Reversing a paid disbursement moves it `PAID → REVERSED` and stamps `reversed_at`, storing the supplied `reversal_reason`. Reversal requires the disbursement to be `PAID` and requires the term not to be `CLOSED`, else `ERR_INVALID_TERM_STATE`. It undoes the ledger movement exactly: for each element of `allocation_split`, the named allocation's `disbursed_amount_cents` is decreased by that element's `amount_cents`, and the source's `expended_amount_cents` falls while its `committed_amount_cents` rises by the same amount — so `authorized_amount_cents` still equals available plus committed plus expended. The appointment's `payroll_status` is then recomputed: `PARTIALLY_DISBURSED` when at least one sibling disbursement of the appointment is still `PAID`, and `SCHEDULED` when none is.

Suspending pay is the axis-separation rule made concrete. A `GradSchoolAdmin` may move `payroll_status` from either `SCHEDULED` or `PARTIALLY_DISBURSED` to `PAY_SUSPENDED`, supplying `pay_suspension_reason`, which is stored. The appointment's `lifecycle_status` must be `ACTIVE` or `NON_RENEWAL_PENDING`, else `ERR_INVALID_APPOINTMENT_STATE` — and, critically, `lifecycle_status` is **not** modified by the suspension. A stipend can be frozen while the academic appointment continues. Resuming pay moves the appointment out of `PAY_SUSPENDED` and clears `pay_suspension_reason` to null, and it branches on paid history with equal precision in both directions: when the appointment has no disbursement in `PAID`, `payroll_status` returns to `SCHEDULED`; when it has at least one disbursement in `PAID`, `payroll_status` returns to `PARTIALLY_DISBURSED`.

Disbursements are read individually — including the per-source `allocation_split` — and listed with optional `appointment_id`, `pay_period_id`, `status`, `limit` and `offset` filters.

### 3.8. Termination, Renewal Reviews and the Non-Renewal Cascade

Termination is the largest single cascade in the system, and it is worth reading as a chain in which each step is caused by an earlier one. A `GradSchoolAdmin` terminates an appointment whose `lifecycle_status` is `APPROVED`, `ACTIVE` or `NON_RENEWAL_PENDING`, while the term is either `OPEN` or `PAYROLL_LOCKED` — a term in any other state yields `ERR_INVALID_TERM_STATE`. The payload supplies `termination_reason`.

The first step sets `lifecycle_status` to the terminal `TERMINATED`, stores `termination_reason`, sets `termination_date` to the current logical-clock date, and sets `payroll_status` to the terminal `PAY_VOIDED` — that last move being the `SCHEDULED → PAY_VOIDED` or `PARTIALLY_DISBURSED → PAY_VOIDED` transition on the payroll axis, permitted from any payroll state other than `PAY_VOIDED` itself. Caused by that, every disbursement of the appointment still in `SCHEDULED` moves to the terminal `VOIDED` with `voided_at` stamped at the current logical-clock instant; the row's `gross_amount_cents` is deliberately retained for audit rather than zeroed. Caused by the voiding, every allocation of the appointment has its `allocated_stipend_cents` recomputed as the sum of that allocation's split amounts across the appointment's disbursements whose `status` is `PAID` — which is 0 when none was ever paid. Separately, and caused by the first step, the remission is re-derived on a deadline test: when `termination_date` falls before the term's `remission_drop_deadline`, `tuition_remission_cents` is set to 0, and when it falls on or after that deadline the entitlement is left unchanged; either way each allocation's `allocated_remission_cents` is re-split using the remission split algorithm of §3.5. Caused by those two recomputations together, every allocation still in `COMMITTED` whose `allocated_stipend_cents` plus `allocated_remission_cents` has fallen to 0 moves to `RELEASED` with `release_reason` set to `APPOINTMENT_TERMINATED`. Caused by those releases, each affected source's `committed_amount_cents` and `available_amount_cents` are recomputed. Caused by those balance changes, every source that is `SUSPENDED` with `suspension_reason` of `OVERCOMMITMENT` and whose `available_amount_cents` has reached or passed its `auto_reinstate_threshold_cents` returns to `ACTIVE` with `suspension_reason` cleared. Finally, caused by the first step, the student's `total_effort_pct` and `assigned_hours_per_week` are recomputed and the student's `version` incremented; and caused by the remission re-derivation, the student's `tuition_benefit_ytd_cents` is recomputed as well.

Renewal is the other way an appointment ends, and it runs through a `RenewalDecision`. A `DepartmentAdmin` opens a review by naming the expiring `appointment_id`. Creation computes two dates from the appointment and its department: `renewal_window_open_date` is the appointment's `end_date` minus 120 days, and `notice_deadline_date` is the appointment's `end_date` minus the appointing department's `non_renewal_notice_days` days. Both are plain calendar-date subtractions on whole days. Creation is permitted only once the window has opened — the current logical-clock date must fall on or after `renewal_window_open_date`, and an earlier attempt is `ERR_RENEWAL_WINDOW_NOT_OPEN`. At most one review per appointment may exist in any state other than `ACKNOWLEDGED`; a second is `ERR_RENEWAL_DECISION_EXISTS`. A new review is `DRAFT` with `decision` of `PENDING`, `sap_certified` false, `revision_count` 0, and `certified_by_user_id`, `certified_at`, `issued_by_user_id`, `notice_sent_date` and `acknowledged_at` all null.

Certifying satisfactory academic progress advances the review `DRAFT → SAP_CERTIFIED`, and either a `FacultySupervisor` or a `GradSchoolAdmin` may do it. The review must be in `DRAFT`, the student's `sap_status` must be exactly `SATISFACTORY`, and the student's `cumulative_gpa` must be at least 3.00; either standing failure is `ERR_SAP_NOT_SATISFACTORY`. On success `sap_certified` becomes true, `certified_by_user_id` records the acting `X-User-ID`, and `certified_at` is stamped with the current logical-clock instant. As §3.2 describes, a later progress downgrade drives the review back `SAP_CERTIFIED → DRAFT`, clearing the certification and increasing `revision_count`; the review can then be certified again, and the pair of transitions forms a revision cycle whose loop count `revision_count` reports.

Issuing the notice advances `SAP_CERTIFIED → NOTICE_ISSUED` and is shared between a `DepartmentAdmin` and a `GradSchoolAdmin`. The payload carries `decision`, which must be either `RENEW` or `NON_RENEW`. The review must be in `SAP_CERTIFIED`; the acting `X-User-ID` must differ from the review's `certified_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; when the `decision` is `NON_RENEW` the current logical-clock date must fall on or before `notice_deadline_date`, and a later date is `ERR_NOTICE_DEADLINE_PASSED`; and the target appointment's `lifecycle_status` must be exactly `ACTIVE`, else `ERR_INVALID_APPOINTMENT_STATE`. On success the review's `decision` is recorded, `issued_by_user_id` records the acting user, and `notice_sent_date` is set to the current logical-clock date.

The two decision branches then diverge sharply, and both are binding. When the `decision` is `RENEW`, the appointment's `renewal_eligible` stays true and no appointment state changes at all. When the `decision` is `NON_RENEW`, the appointment advances `ACTIVE → NON_RENEWAL_PENDING` and its `renewal_eligible` becomes false; caused by that, every appointment whose `renewed_from_appointment_id` names this appointment and whose `lifecycle_status` is `DRAFT`, `SUBMITTED`, `RETURNED` or `FUNDING_VERIFIED` moves to the terminal `CANCELLED`; caused by each successor entering `CANCELLED`, that successor's allocations in `PROPOSED` or `COMMITTED` move to `RELEASED` with `release_reason` set to `PREDECESSOR_NON_RENEWED` and both `allocated_stipend_cents` and `allocated_remission_cents` zeroed; caused by each such release, the affected sources' `committed_amount_cents` and `available_amount_cents` are recomputed; and caused by each successor leaving a counted state, the student's `total_effort_pct` is recomputed and the student's `version` incremented. A pipeline of next-year appointments built on an appointment that is not renewed therefore collapses in one call, and the budget it had encumbered returns to available.

The student closes the loop. A `StudentUser` acknowledges an issued notice, advancing the review `NOTICE_ISSUED → ACKNOWLEDGED`, which is terminal, and stamping `acknowledged_at` with the current logical-clock instant. The review must be in `NOTICE_ISSUED`, and the acting `X-User-ID` must equal the appointment's `student_id`, else `ERR_NOT_RESOURCE_OWNER`. Reviews are read individually or listed with optional `appointment_id`, `status`, `decision`, `limit` and `offset` filters, available to a `GradSchoolAdmin`, a `DepartmentAdmin`, a `FacultySupervisor` and — for its own rows — a `StudentUser`.

### 3.9. Tuition-Benefit Taxation and Closing the Term

A tuition remission is a benefit, and above a statutory annual threshold it is imputed income. A `GradSchoolAdmin` creates a `TaxAssessment` for a student-and-term pair, naming `student_id` and `term_id` and carrying the `expected_student_version` field of §2.8. The assessment copies the term's `tax_calendar_year` at creation, is born `PROVISIONAL` with `variant_applied` of `TERM_PROVISIONAL` and `amendment_reason` null, and increments the student's `version` by one. Any earlier assessment for the same pair that is still `PROVISIONAL` moves to the terminal `SUPERSEDED`. Creation is refused outright when an assessment for that pair is already `FINAL` or `AMENDED`: that is `ERR_ASSESSMENT_ALREADY_FINAL`.

The benefit under assessment is the sum of `tuition_remission_cents` over the student's appointments in the assessed term whose `lifecycle_status` is one of `APPROVED`, `ACTIVE`, `NON_RENEWAL_PENDING`, `COMPLETED` or `TERMINATED`. Appointments in `DRAFT`, `SUBMITTED`, `RETURNED`, `FUNDING_VERIFIED` or `CANCELLED` contribute nothing — an appointment that has not been approved has not yet conferred a benefit. That sum is stored as `benefit_cents`. The exemption cap is the `tuition_tax_exempt_cap_cents` declared by the assessed term's stipend policies, which all agree on that value.

The two calculation variants differ only in how the cap is applied, and the difference is the point of the design. Under **`TERM_PROVISIONAL`**, the cap is applied to the term in isolation: `exempt_cents` is the smaller of `benefit_cents` and the cap, and `taxable_cents` is `benefit_cents` minus `exempt_cents`. Two terms each conferring 400000 cents of benefit therefore both report `taxable_cents` of 0 while provisional, because neither term alone reaches the 525000-cent cap. Under **`CALENDAR_YEAR_FINAL`**, the cap is applied to the calendar-year running total, and only the unused remainder shields this term. The prior finals are the student's other assessments with the same `tax_calendar_year` whose `status` is `FINAL`, excluding the row being computed. The year benefit is this row's `benefit_cents` plus the sum of `benefit_cents` over those prior finals. The year exemption is the smaller of that year benefit and the cap. The remaining cap is the larger of zero and the year exemption minus the sum of `exempt_cents` over those prior finals. This row's `exempt_cents` is then the smaller of its own `benefit_cents` and that remaining cap — clamped so it can never exceed the term's own benefit — and `taxable_cents` is `benefit_cents` minus `exempt_cents`, and therefore never negative. The same pair of 400000-cent terms now reports `taxable_cents` of 275000 on the second term once both are final, which is precisely the divergence from the provisional variant. Two invariants hold: `benefit_cents` always equals `exempt_cents` plus `taxable_cents`, and the sum of `exempt_cents` over a student's `FINAL` assessments within one `tax_calendar_year` never exceeds the cap.

Whichever variant ran, `imputed_withholding_cents` is `taxable_cents` multiplied by an imputed withholding rate of 0.2200 — twenty-two percent — rounded half up to a whole cent. Cap comparisons are inclusive: a year total exactly equal to the cap is fully exempt.

Finalizing an assessment advances it `PROVISIONAL → FINAL`, and the same operation advances an amended assessment `AMENDED → FINAL`. From `PROVISIONAL`, finalization additionally requires that no appointment of that student in that term is still in `DRAFT`, `SUBMITTED`, `RETURNED` or `FUNDING_VERIFIED`, else `ERR_INVALID_APPOINTMENT_STATE` — the year's benefit cannot be fixed while an appointment that would change it is still in flight. Finalization recomputes `benefit_cents`, `exempt_cents`, `taxable_cents` and `imputed_withholding_cents` under the `CALENDAR_YEAR_FINAL` variant, sets `status` to `FINAL` and `variant_applied` to `CALENDAR_YEAR_FINAL`, and then recomputes the student's `tuition_benefit_ytd_cents` and `taxable_tuition_benefit_ytd_cents` and increments the student's `version`.

Amending a finalized assessment advances it `FINAL → AMENDED` and carries `amendment_reason`, which is stored. It requires the assessment to be `FINAL`, and it requires the recomputation under `CALENDAR_YEAR_FINAL` to yield a `benefit_cents` different from the stored value; when nothing has actually changed the amendment is refused with `ERR_NO_ASSESSMENT_DELTA`. On success all four money fields are recomputed, `status` becomes `AMENDED`, and the student's `tuition_benefit_ytd_cents` and `taxable_tuition_benefit_ytd_cents` are recomputed with the student's `version` incremented. Because finalization accepts an `AMENDED` assessment, the correction cycle `FINAL → AMENDED → FINAL` may run repeatedly, and each pass re-derives the year-to-date exemption remainder from the student's other finals.

Two administrative acts close out the term. Locking payroll advances the term `OPEN → PAYROLL_LOCKED`; it requires the term to be `OPEN` and requires that no appointment of the term is still in `FUNDING_VERIFIED`, else `ERR_UNRESOLVED_APPOINTMENTS`. Appointments still sitting in `SUBMITTED` are permitted to remain — they simply cannot be verified while the term is locked. Locking sets `locked_at` to the current logical-clock instant and moves every pay period of the term still `OPEN` to `LOCKED`, which is exactly what makes disbursement payment possible.

Closing advances the term `PAYROLL_LOCKED → CLOSED`, which is terminal. It requires the term to be `PAYROLL_LOCKED`, requires every disbursement belonging to one of the term's pay periods to be in `PAID`, `VOIDED` or `REVERSED`, and requires every tax assessment of the term to be in `FINAL` or `SUPERSEDED`; a still-`SCHEDULED` disbursement or a non-final assessment is `ERR_UNSETTLED_DISBURSEMENTS`. On success `closed_at` is stamped, every pay period of the term still `LOCKED` moves to `CLOSED`, and a conditional cascade runs: every appointment of the term whose `lifecycle_status` is `ACTIVE` or `NON_RENEWAL_PENDING` and whose `end_date` falls on or before the term's `term_end` moves to the terminal `COMPLETED` — those are the `ACTIVE → COMPLETED` and `NON_RENEWAL_PENDING → COMPLETED` transitions, and an appointment whose window extends past `term_end` is left as it is. Caused by each appointment entering `COMPLETED`, its allocations in `COMMITTED` move to the terminal `EXPENDED` and each such allocation's `disbursed_amount_cents` is raised to its `allocated_stipend_cents` plus its `allocated_remission_cents`. Caused by each allocation entering `EXPENDED`, that allocation's source has its `committed_amount_cents`, `expended_amount_cents` and `available_amount_cents` recomputed — the committed total falling and the expended total rising by the same amount, with available untouched, as §2.7 requires of this branch.

## 4. Endpoint Definitions

Operations that bring a new row into existence — an academic term, a department, a stipend policy, a pay period, a student, a funding source, an appointment, a renewal review, a tax assessment — return `201 Created`. Every other operation, including all state transitions, all cascading actions and all reads, returns `200 OK`. All paths are absolute and mounted at the service root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/academic-terms` | Create an academic term in PLANNING | GradSchoolAdmin |
| GET | `/academic-terms/{id}` | Read one academic term including its computed pay_period_count | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor |
| POST | `/academic-terms/{id}/open` | Open the term for appointment activity | GradSchoolAdmin |
| POST | `/academic-terms/{id}/lock-payroll` | Freeze the payroll calendar and lock every OPEN pay period | GradSchoolAdmin |
| POST | `/academic-terms/{id}/close` | Close the term, completing appointments and expending their commitments | GradSchoolAdmin |
| GET | `/academic-terms/{id}/stipend-policies` | List the stipend policies governing the term | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor |
| GET | `/academic-terms/{id}/pay-periods` | List the term's pay-period calendar ordered by sequence_no ascending | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor |
| POST | `/departments` | Create an appointing department | GradSchoolAdmin |
| GET | `/departments/{id}` | Read one department | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor |
| POST | `/stipend-policies` | Declare the stipend, remission, insurance and tax policy for one term, assistantship type and degree level | GradSchoolAdmin |
| POST | `/pay-periods` | Append a half-open pay period to a term's payroll calendar | GradSchoolAdmin |
| POST | `/students` | Register a graduate student | GradSchoolAdmin |
| GET | `/students/{id}` | Read one student including effort and tuition-benefit aggregates | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor, StudentUser |
| PATCH | `/students/{id}/academic-progress` | Record academic progress; a non-SATISFACTORY standing revokes pending renewal certifications | FacultySupervisor, GradSchoolAdmin |
| POST | `/students/{id}/effort-cap-override` | Raise a student's aggregate effort cap and record the approving user | GradSchoolAdmin |
| POST | `/funding-sources` | Create a grant, departmental budget or fellowship account | GrantAccountant, GradSchoolAdmin |
| GET | `/funding-sources/{id}` | Read one funding source including its balance triple | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| GET | `/funding-sources` | List funding sources, filterable by administering department, type and status | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| POST | `/funding-sources/{id}/suspend` | Suspend a source so it accepts no new commitments | GrantAccountant |
| POST | `/funding-sources/{id}/reinstate` | Manually clear a suspension | GrantAccountant |
| POST | `/funding-sources/{id}/close` | Close out a source; requires zero outstanding commitments | GrantAccountant |
| POST | `/appointments` | Create a DRAFT appointment; computes the effort profile, remission band and insurance eligibility | DepartmentAdmin |
| GET | `/appointments/{id}` | Read one appointment with both state axes and all computed money fields | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor, StudentUser |
| GET | `/appointments` | List appointments filterable by student, department, term, predecessor and either state axis | GradSchoolAdmin, DepartmentAdmin, GrantAccountant, FacultySupervisor, StudentUser |
| PUT | `/appointments/{id}/funding-plan` | Replace the appointment's whole funding plan with a new cost-shared allocation set | DepartmentAdmin, GrantAccountant |
| POST | `/appointments/{id}/submit` | Submit for funding review; runs the full compliance, workload, cost-share and stipend-minimum battery and computes every money field | DepartmentAdmin |
| POST | `/appointments/{id}/return` | Return a submitted or funding-verified appointment for revision, releasing committed allocations | GradSchoolAdmin |
| POST | `/appointments/{id}/verify-funding` | Commit the appointment's funding plan against its sources | GrantAccountant |
| POST | `/appointments/{id}/approve` | Approve a funding-verified appointment | GradSchoolAdmin |
| POST | `/appointments/{id}/activate` | Activate an approved appointment | GradSchoolAdmin |
| POST | `/appointments/{id}/schedule-payroll` | Materialise the appointment's pay-period disbursements using the term's proration method | GradSchoolAdmin |
| POST | `/appointments/{id}/terminate` | Terminate an appointment; voids scheduled pay, re-derives remission and unwinds encumbrances | GradSchoolAdmin |
| POST | `/appointments/{id}/suspend-pay` | Suspend disbursements without touching the approval axis | GradSchoolAdmin |
| POST | `/appointments/{id}/resume-pay` | Resume disbursements according to paid history | GradSchoolAdmin |
| GET | `/funding-allocations/{id}` | Read one funding allocation including its allocated and disbursed amounts | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| GET | `/funding-allocations` | List funding allocations filterable by appointment, source and status, ordered by plan_sequence then created_at ascending | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| POST | `/funding-allocations/{id}/release` | Release a committed, never-disbursed allocation back to its source | GrantAccountant |
| GET | `/stipend-disbursements/{id}` | Read one disbursement including its per-source allocation split | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| GET | `/stipend-disbursements` | List disbursements filterable by appointment, pay period and status, ordered by pay-period sequence_no ascending | GradSchoolAdmin, DepartmentAdmin, GrantAccountant |
| POST | `/stipend-disbursements/{id}/pay` | Pay a scheduled disbursement out of a locked pay period | GradSchoolAdmin |
| POST | `/stipend-disbursements/{id}/reverse` | Reverse a paid disbursement, returning the money to encumbrance | GradSchoolAdmin |
| POST | `/renewal-decisions` | Open a renewal review; computes the renewal window and non-renewal notice deadline | DepartmentAdmin |
| GET | `/renewal-decisions/{id}` | Read one renewal review | GradSchoolAdmin, DepartmentAdmin, FacultySupervisor, StudentUser |
| GET | `/renewal-decisions` | List renewal reviews filterable by appointment, status and decision | GradSchoolAdmin, DepartmentAdmin, FacultySupervisor, StudentUser |
| POST | `/renewal-decisions/{id}/certify-progress` | Certify satisfactory academic progress for the review | FacultySupervisor, GradSchoolAdmin |
| POST | `/renewal-decisions/{id}/issue-notice` | Issue the renewal or non-renewal notice; the certifying user may not issue | DepartmentAdmin, GradSchoolAdmin |
| POST | `/renewal-decisions/{id}/acknowledge` | Student acknowledgement of the issued notice | StudentUser |
| POST | `/tax-assessments` | Create a provisional tuition-benefit tax assessment for a student and term | GradSchoolAdmin |
| GET | `/tax-assessments/{id}` | Read one tax assessment | GradSchoolAdmin, DepartmentAdmin, StudentUser |
| GET | `/tax-assessments` | List tax assessments filterable by student, term, calendar year and status | GradSchoolAdmin, DepartmentAdmin, StudentUser |
| POST | `/tax-assessments/{id}/finalize` | Finalize the assessment using the calendar-year exemption remainder | GradSchoolAdmin |
| POST | `/tax-assessments/{id}/amend` | Amend a finalized assessment after the underlying remission changed | GradSchoolAdmin |
| POST | `/_clock/set_current_utc` | Reposition the server's logical clock; mutates no entity | GradSchoolAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TERM_NOT_FOUND` | 404 Not Found |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_FUNDING_SOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RENEWAL_DECISION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_APPOINTMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_STUDENT_VERSION` | 412 Precondition Failed |
| `ERR_DUPLICATE_TERM_CODE` | 409 Conflict |
| `ERR_DUPLICATE_STUDENT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_FUNDING_SOURCE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_STIPEND_POLICY` | 409 Conflict |
| `ERR_DUPLICATE_PAY_PERIOD_SEQUENCE` | 409 Conflict |
| `ERR_INVALID_TERM_STATE` | 409 Conflict |
| `ERR_INVALID_APPOINTMENT_STATE` | 409 Conflict |
| `ERR_INVALID_ALLOCATION_STATE` | 409 Conflict |
| `ERR_INVALID_DISBURSEMENT_STATE` | 409 Conflict |
| `ERR_INVALID_RENEWAL_STATE` | 409 Conflict |
| `ERR_INVALID_ASSESSMENT_STATE` | 409 Conflict |
| `ERR_TERM_NOT_OPEN` | 409 Conflict |
| `ERR_FUNDING_SOURCE_NOT_ACTIVE` | 409 Conflict |
| `ERR_PAY_PERIOD_NOT_LOCKED` | 409 Conflict |
| `ERR_INTERNATIONAL_HOUR_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SAP_NOT_SATISFACTORY` | 422 Unprocessable Entity |
| `ERR_OVER_APPOINTMENT` | 422 Unprocessable Entity |
| `ERR_DUAL_ROLE_CONFLICT` | 409 Conflict |
| `ERR_TERM_CALENDAR_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_UNRESOLVED_APPOINTMENTS` | 409 Conflict |
| `ERR_UNSETTLED_DISBURSEMENTS` | 409 Conflict |
| `ERR_APPOINTMENT_DATES_OUTSIDE_TERM` | 422 Unprocessable Entity |
| `ERR_PAY_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_FUNDING_PERIOD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 422 Unprocessable Entity |
| `ERR_NOTICE_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_FUNDING_ALLOCATION_MISSING` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_SHARES_INVALID` | 422 Unprocessable Entity |
| `ERR_COST_SHARE_SOURCE_INVALID` | 422 Unprocessable Entity |
| `ERR_STIPEND_POLICY_MISSING` | 422 Unprocessable Entity |
| `ERR_FELLOWSHIP_SERVICE_CONFLICT` | 422 Unprocessable Entity |
| `ERR_RENEWAL_DECISION_EXISTS` | 409 Conflict |
| `ERR_ASSESSMENT_ALREADY_FINAL` | 409 Conflict |
| `ERR_STIPEND_BELOW_MINIMUM` | 422 Unprocessable Entity |
| `ERR_GRANT_EFFORT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FUNDING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_ALLOCATION_PARTIALLY_DISBURSED` | 409 Conflict |
| `ERR_ALLOCATION_LOCKED_BY_APPROVAL` | 409 Conflict |
| `ERR_FUNDING_SOURCE_HAS_COMMITMENTS` | 409 Conflict |
| `ERR_NO_ASSESSMENT_DELTA` | 409 Conflict |

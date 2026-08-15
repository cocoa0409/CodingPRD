# Degree Audit & Graduation Certification API — Product Requirements Document

## 1. Introduction

Every term, a university registrar's office answers the same deceptively simple question for thousands of students: *what still stands between this student and their degree?* The answer is rarely simple. Program requirements shift from one catalog year to the next, so two students in the same major can legitimately be held to different rules. Exceptions — a substituted course here, a waived credit requirement there — arrive through email threads and committee minutes and are easily lost. And the costliest discoveries happen at the worst possible moment: a missing requirement or a miscomputed grade point average surfacing during final certification, weeks before commencement, after the student has already been told to order a gown.

This document specifies the Degree Audit & Graduation Certification API, the system of record for that entire pipeline. It governs how program requirements are encoded as catalog-year-versioned curricula, how enrollment grading deterministically derives credits and grade point averages, and how degree audits are run — including what-if analyses for students weighing a major change and conditional projections for students in their final term. Audit exceptions move through a two-step advisor-and-registrar approval chain with strict segregation of duties. On top of that foundation the system manages the graduation application itself: filing deadlines enforced against a logical clock, financial-hold gating, conditional clearance that resolves automatically as last-term grades post, Latin honors computed at conferral, and diploma production with a correction and re-issue path. Throughout, derived state is never allowed to drift — every grade event and every exception decision immediately recomputes the audits and flags that depend on it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly four roles, spelled precisely as follows: `Student`, `Advisor`, `RegistrarStaff`, and `SystemAdmin`. Any attempt to invoke an operation outside the caller's role is rejected with `ERR_FORBIDDEN` (HTTP 403).

The meaning of `X-User-ID` depends on the role presented. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting Student; ownership checks on any resource that belongs to a student compare the resource's owning-student reference to `X-User-ID`, and a Student touching another student's record is rejected with `ERR_FORBIDDEN`. When `X-User-Role` is `Advisor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it as `requested_by_user_id` when the advisor files an audit exception, and later compares it for segregation of duties at decision time. When `X-User-Role` is `RegistrarStaff`, `X-User-ID` is likewise an opaque operator identifier that is never compared to any entity's `id`. When `X-User-Role` is `SystemAdmin`, `X-User-ID` is an opaque identifier used solely to operate the logical clock capability described in §2.5.

Two cross-cutting permission rules apply above and beyond the per-endpoint role grants in §4. First, the audit kinds `FINAL` and `CONDITIONAL` are restricted to `RegistrarStaff`; a `Student` or `Advisor` requesting either kind is rejected with `ERR_FORBIDDEN`. Second, every `Student` interaction — reads included — is scoped to that student's own records under the ownership rule above.

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

Endpoints that return lists of resources accept the query parameters `limit` and `offset`. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it must lie between 1 and 100 inclusive. The `offset` parameter states how many items to skip and defaults to 0; negative offsets are not allowed. A `limit` outside the permitted range or a negative `offset` is rejected with `ERR_INVALID_PAGINATION_PARAMETERS` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in the system — programs, requirement groups, honors policies, courses, students, enrollments, program declarations, degree audits, exceptions, graduation applications, and diplomas — carries the same set of system-managed properties:

- **`id` (string):** a server-minted UUID that uniquely identifies the resource. The identifier carries no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource, including mutations caused by system-driven cascades rather than direct client writes.
- **`version` (integer):** a system-managed integer that increments by one on every mutation of the resource. It is the basis for optimistic concurrency control (§2.10) and also moves when a recompute cascade changes a derived field such as a declaration's satisfied flag.

No resource in this system omits `updated_at` or `version`; the convention is uniform so that every state change is observable and every entity is individually addressable.

### 2.5. The Logical Clock

Time-dependent rules — the application filing deadline and the conferral timestamp — never read the server's wall clock. Instead, all of them read a server-held **logical clock**. Before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time on its own.

An admin-only, test-driving capability lets a `SystemAdmin` set the logical clock to a supplied `to_iso8601` instant; the response reports the resulting `current_utc`. This is the only way time advances in the system, which keeps deadline-sensitive behavior fully deterministic in every environment.

### 2.6. Nested Resource Retrieval and Resource Existence

The API enforces strict, hierarchical validation for every request that targets a nested resource. When a path contains multiple identifiers — a program followed by a requirement group collection, a student followed by an enrollment collection, a declaration followed by its audits, exceptions, or applications — the system validates the existence of each identifier sequentially, from left to right, and rejects the request with a `404 Not Found` for the *first* identifier that does not resolve to an existing resource. A request aimed at a declaration beneath a non-existent student therefore fails on the student before the declaration is ever examined. Each resource family has its own not-found identifier: `ERR_PROGRAM_NOT_FOUND`, `ERR_REQUIREMENT_GROUP_NOT_FOUND`, `ERR_COURSE_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_ENROLLMENT_NOT_FOUND`, `ERR_STUDENT_PROGRAM_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, and `ERR_DIPLOMA_NOT_FOUND`.

After the path identifiers resolve, identifiers referenced inside the request body — `program_id`, `course_id`, `requirement_group_id`, `enrollment_id`, and `target_program_id` — must each resolve to an existing resource; an unresolvable body reference is rejected with the corresponding not-found identifier (for example, an unknown `requirement_group_id` yields `ERR_REQUIREMENT_GROUP_NOT_FOUND`).

### 2.7. Request Gatekeeping Order

When several checks could reject the same request, the system evaluates them in a fixed order so that the rejection a client receives is deterministic. A request that would fail multiple checks always surfaces the earliest applicable one. The order is:

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization.** The role must be permitted on the endpoint, including the `FINAL`/`CONDITIONAL` audit restriction and the `Student` ownership rule (`ERR_FORBIDDEN`).
3. **Path existence.** Path identifiers resolve left-to-right (the `ERR_*_NOT_FOUND` family).
4. **Body reference existence.** Body-referenced identifiers resolve (the same `ERR_*_NOT_FOUND` family).
5. **From-state validity.** The target resource must be in a state that allows the requested transition (`ERR_PROGRAM_INVALID_STATE`, `ERR_ENROLLMENT_INVALID_STATE`, `ERR_STUDENT_PROGRAM_NOT_ACTIVE`, `ERR_WAIVER_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`, `ERR_DIPLOMA_INVALID_STATE`).
6. **Optimistic concurrency.** Where a version field is required, it must match the parent's current `version` (`ERR_STALE_VERSION`).
7. **Segregation of duties.** An advisor may not decide an exception they themselves requested (`ERR_SELF_APPROVAL_FORBIDDEN`).
8. **Uniqueness and range overlap.** Unique identifiers must stay unique, catalog ranges and policy ranges must not overlap, one live application per declaration, no duplicate active enrollments (`ERR_UNIQUE_CONSTRAINT_VIOLATION`, `ERR_CATALOG_RANGE_OVERLAP`, `ERR_POLICY_RANGE_OVERLAP`, `ERR_ACTIVE_APPLICATION_EXISTS`, `ERR_DUPLICATE_ENROLLMENT`).
9. **Filing window.** The graduation filing deadline must not have passed (`ERR_FILING_DEADLINE_PASSED`).
10. **Referenced-entity state.** Referenced resources must be in the states the workflow demands — program active, catalog year in range, enrollment completed, final audit present and satisfied, in-progress enrollments present, honors policy covering (`ERR_PROGRAM_RETIRED`, `ERR_CATALOG_YEAR_OUT_OF_RANGE`, `ERR_ENROLLMENT_NOT_COMPLETED`, `ERR_FINAL_AUDIT_REQUIRED`, `ERR_AUDIT_NOT_SATISFIED`, `ERR_NO_IN_PROGRESS_ENROLLMENTS`, `ERR_HONORS_POLICY_MISSING`).
11. **Financial standing.** The student's `financial_hold` must be clear where the workflow requires it (`ERR_FINANCIAL_HOLD`).

Independent of this ordering, a structurally malformed payload — a missing required field, an invalid enum member, or a payload that mismatches the requested kind, such as a what-if audit without its target or a waiver without its amount — is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.8. Catalog-Year Versioning and Policy Effective Dating

Programs are versioned by catalog year. Each version of a program claims a **half-open** range of catalog years: the version covers every catalog year from `catalog_year_start` inclusive up to, but not including, `catalog_year_end`, and the end must be strictly greater than the start. Two versions sharing the same `program_code` may not claim overlapping ranges; adjacency is explicitly allowed, so one version's `catalog_year_end` may equal the next version's `catalog_year_start` without conflict. An overlapping claim is rejected with `ERR_CATALOG_RANGE_OVERLAP` (HTTP 409).

Honors policies use the opposite interval convention. A policy covers the **closed, inclusive** range from `effective_first_year` through `effective_last_year`, and the last year must be greater than or equal to the first. Two policies of the same program may not overlap, and because the interval is closed, a shared boundary year *is* an overlap: a policy ending in 2024 collides with one beginning in 2024. A colliding policy is rejected with `ERR_POLICY_RANGE_OVERLAP` (HTTP 409).

### 2.9. Academic Precision and Rounding

Grade arithmetic is exact until the final rounding step. Per-enrollment `grade_points` are the product of `credits_attempted` and the letter grade's value, exact to two decimal places, with no per-enrollment rounding applied.

Grade point averages follow a pinned rounding order. A GPA is the sum of `grade_points` over the GPA-bearing input set divided by the sum of `credits_attempted` over the same set, computed over the full input set and rounded **exactly once at the end** to three decimal places using round-half-up. The tempting alternative — rounding each term's GPA to three decimals first and then averaging the terms — is wrong and produces different values. When the denominator is zero because the student has no GPA-bearing enrollments, the GPA is reported as 0.000.

Credit quantities (`credits`, `credits_attempted`, `credits_earned`, applied credits, outstanding credits) are exact numbers; all credit comparisons are at-least-or-equal tests on exact values. Latin-honors thresholds are compared against the already-rounded three-decimal GPA, and the comparison is inclusive — a GPA exactly equal to a threshold earns that threshold's tier.

### 2.10. Optimistic Concurrency Control

Exactly one write operation in the system carries optimistic concurrency control: running a degree audit against a program declaration. The request must include `expected_student_program_version`, carrying the `version` of the declaration as the client last observed it. If the declaration's current `version` no longer matches, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

The rule exists because audit creation is destructive to prior results: a new audit supersedes the previous `CURRENT` audit of the same kind, and the act of creation itself advances the declaration's `version`. A client holding a stale view — because another writer has since run an audit, or because an exception approval cascade flipped `latest_audit_satisfied` and bumped the version — must re-read the declaration before running a new audit rather than overwrite state it has not observed. No other endpoint in the system accepts or requires a version field.

### 2.11. Derived State and the Recompute Cascade

Nothing derived is ever left stale. Grade events (an enrollment created with a grade, a grade posting, a grade change) and exception decisions (approval, revocation) fire a deterministic recompute chain: first the enrollment's own credit fields are recomputed, then the owning student's aggregate credits and GPAs, then every `CURRENT` degree audit of each `ACTIVE` declaration of that student, then the declaration's `latest_audit_satisfied` flag, and finally any conditionally cleared graduation application awaiting its contingency resolution. Each hop that actually changes a resource refreshes that resource's `updated_at` and increments its `version`.

Only `CURRENT` audits are ever recomputed. A `SUPERSEDED` audit is immutable history, and a `WHAT_IF` audit is a point-in-time snapshot that enrollment and exception mutations never touch. Revocation of an approved exception compensates the approval exactly: the recompute runs with the exception removed, and group credits and outstanding credits return to their pre-approval values.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Programs, Requirement Groups, and Honors Policies

`RegistrarStaff` authors the curriculum. Each program version is created with a `program_code` shared across all versions of the same program (for example, BS-CS), a display `name`, a `degree_type` of `ASSOCIATE`, `BACHELOR`, or `MASTER`, the degree-wide minimums `min_total_credits` and `min_gpa`, and the half-open catalog range `catalog_year_start` / `catalog_year_end` described in §2.8. A range whose end is not strictly greater than its start is rejected with `ERR_INVALID_REQUEST`, and an overlapping claim with `ERR_CATALOG_RANGE_OVERLAP`. A new version starts `ACTIVE`.

Retirement is one-way and narrow in effect. A `RegistrarStaff` operator retires a program version, moving it from `ACTIVE` to `RETIRED`; attempting the transition on a version that is not `ACTIVE` is rejected with `ERR_PROGRAM_INVALID_STATE`. Retirement closes the door only to new commitments: existing declarations under the retired version remain fully auditable to completion, while new declarations — and what-if analyses that name the retired version as their target — are refused with `ERR_PROGRAM_RETIRED`.

Within a program version, `RegistrarStaff` defines **requirement groups**, the units against which audits allocate credit. Each group carries a `group_code` unique within the program (CORE and ELEC are typical), the `required_credits` that must be allocated to it, a `min_grade` of `A`, `B`, `C`, or `D` setting the minimum letter grade an enrollment must have earned to count toward the group, and `eligible_course_codes`, the array of course codes eligible for the group. A program version may carry any number of groups — including none.

`RegistrarStaff` also records the program's Latin-honors policy. A policy states its `honors_gpa_basis` — `INSTITUTIONAL` or `CUMULATIVE`, selecting which GPA the thresholds compare against — the three thresholds `cum_threshold`, `magna_threshold`, and `summa_threshold`, and the closed effective interval `effective_first_year` through `effective_last_year` governed by §2.8; an interval whose last year precedes its first is `ERR_INVALID_REQUEST`, and a colliding interval is `ERR_POLICY_RANGE_OVERLAP`. A policy may optionally set `residency_min_credits`, the minimum institutional earned credits a student must hold to be eligible for any Latin honors; when omitted, the residency minimum is 30 credits.

### 3.2. The Academic Record: Courses, Students, and Enrollments

Before any student can be evaluated, the registrar registers the course catalog and the student body. `RegistrarStaff` creates each course with a unique `course_code` (for example, CS101), a `title`, and the `credits` the course carries; a duplicate course code is rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`. Students are likewise created by `RegistrarStaff` with a unique `student_number` (duplicates meet the same `ERR_UNIQUE_CONSTRAINT_VIOLATION`), a `legal_name` that serves as the default source for the diploma name, and an optional `financial_hold` flag that defaults to false. A student's `status` begins `ACTIVE` and becomes `GRADUATED` upon the first degree conferral.

Four derived measures are maintained on every student and recomputed after every grade event. `total_earned_credits` sums `credits_earned` over all of the student's `COMPLETED` enrollments, institutional and transfer alike. `institutional_earned_credits` applies the same sum restricted to enrollments whose `is_transfer` is false. `institutional_gpa` is the credit-weighted GPA over non-transfer GPA-bearing enrollments, while `cumulative_gpa` spans all GPA-bearing enrollments including transfer work; identical underlying data yields different values under the two bases whenever transfer grades differ from the institutional average. Both GPAs follow the pinned rounding of §2.9 and report 0.000 when no GPA-bearing enrollment exists. An enrollment is **GPA-bearing** when it is `COMPLETED` with a grade of `A` through `F`; a `W` is excluded from GPA entirely, contributing neither grade points nor credits attempted to the denominator.

Enrollment recording sits with `RegistrarStaff`. The payload names the `course_id` and the academic `term` (for example, 2025-FA), optionally flags `is_transfer` (default false) for credit recorded from another institution, and optionally supplies a `grade`. When a grade is supplied at creation the enrollment starts directly in `COMPLETED` — the transfer and retroactive-recording path — and otherwise it starts `IN_PROGRESS` with a null grade. At creation, `credits_attempted` snapshots the course's `credits`. A second enrollment for the same student, course, and term is rejected with `ERR_DUPLICATE_ENROLLMENT` while a sibling exists in `IN_PROGRESS` or `COMPLETED`; a `WITHDRAWN` sibling does not block re-enrollment. For advising review, the enrollment list can be filtered by `student_id`, `course_id`, `status`, and `term`, and each enrollment response identifies its owner through `student_id`.

Letter grades carry fixed values: `A` is worth 4.00, `B` 3.00, `C` 2.00, `D` 1.00, and `F` 0.00; `W` carries no value at all. An enrollment's `credits_earned` equals the course's credits when the enrollment is `COMPLETED` with a grade of `A` through `D`, and is zero in every other case — an `F` earns nothing, and a withdrawal earns nothing. Its `grade_points` are `credits_attempted` multiplied by the grade's value for grades `A` through `F`; a `W` records zero grade points and, as noted, keeps the enrollment out of every GPA denominator.

Grading happens in two operations, both restricted to `RegistrarStaff`. **Posting a grade** resolves an in-progress enrollment: a grade of `A` through `F` moves it from `IN_PROGRESS` to `COMPLETED`, while a `W` moves it from `IN_PROGRESS` to `WITHDRAWN`. Posting against an enrollment that is not `IN_PROGRESS` is rejected with `ERR_ENROLLMENT_INVALID_STATE`, and a grade outside the six letters is `ERR_INVALID_REQUEST`. **Changing a grade** is the correction path, invoked with a `new_grade` and a `reason`, and is permitted only on enrollments that are `COMPLETED` or `WITHDRAWN` — anything else meets `ERR_ENROLLMENT_INVALID_STATE`. A letter grade on a `COMPLETED` enrollment keeps it `COMPLETED` with corrected figures; a `W` on a `COMPLETED` enrollment performs a retroactive withdrawal to `WITHDRAWN`, removing previously earned credits from every derived field; and a letter grade on a `WITHDRAWN` enrollment reverses the withdrawal back to `COMPLETED`, restoring the credits.

Every grade event — creation with a grade, a posting, or a change — fires the full recompute cascade of §2.11: the student's four derived measures refresh, every `CURRENT` audit of each `ACTIVE` declaration of that student is recomputed, each declaration's `latest_audit_satisfied` refreshes from its `CURRENT` `FINAL` audit, and a conditionally cleared application awaiting resolution may settle automatically as described in §3.6.

### 3.3. Declaring a Program of Study

A student declares a major by creating a program declaration: the owning `Student` — or `RegistrarStaff` on the student's behalf — supplies the `program_id` of the intended program version and the `catalog_year` that will govern the declaration. Two referenced-state checks guard the creation. The named program version must be `ACTIVE`; declaring against a `RETIRED` version is rejected with `ERR_PROGRAM_RETIRED`. And the `catalog_year` must fall within the version's half-open range — at least `catalog_year_start` and strictly less than `catalog_year_end` — or the declaration is rejected with `ERR_CATALOG_YEAR_OUT_OF_RANGE`. A new declaration starts `ACTIVE` with `latest_audit_satisfied` false. Declaration lists can be reviewed filtered by `student_id`, `program_id`, and `status`.

Withdrawal ends a declaration's active life. The owning `Student` or `RegistrarStaff` withdraws it, moving `ACTIVE` → `WITHDRAWN`; attempting the transition from any other state is rejected with `ERR_STUDENT_PROGRAM_NOT_ACTIVE`. The only route to `COMPLETED` is conferral of the degree (§3.7). Once a declaration is `WITHDRAWN` or `COMPLETED` it is closed to new work: running an audit against it, filing an exception on it, creating a graduation application for it, or attempting to withdraw it again are all rejected with `ERR_STUDENT_PROGRAM_NOT_ACTIVE`.

### 3.4. Degree Audits: Standard, What-If, Conditional, and Final

The degree audit is the system's central computation, and it comes in four kinds selected by `audit_kind`. A `STANDARD` audit reports progress against the declared program. A `WHAT_IF` audit evaluates a *different* program as-if the student were changing majors, and therefore requires `target_program_id` naming the hypothetical program — omitting it is `ERR_INVALID_REQUEST`; the what-if target must itself be `ACTIVE` (else `ERR_PROGRAM_RETIRED`) and must cover the declaration's `catalog_year` within its own half-open catalog range (else `ERR_CATALOG_YEAR_OUT_OF_RANGE`). A `CONDITIONAL` audit projects in-progress work at full credit to support conditional clearance, and a `FINAL` audit is the certification audit of record that gates the graduation review. The `FINAL` and `CONDITIONAL` kinds may be run by `RegistrarStaff` only. For `STANDARD` and `FINAL` runs the audit evaluates the declaration's own program, and `target_program_id` simply equals the declared program.

Running an audit is the one optimistic-concurrency-protected write in the system: the request must carry `expected_student_program_version` matching the declaration's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (§2.10). A successful run creates the audit in `CURRENT` status and supersedes the prior `CURRENT` audit of the same kind on that declaration — for `WHAT_IF`, the same kind *and* the same `target_program_id` — moving the predecessor to `SUPERSEDED`. Creation itself increments the declaration's `version` by one. Each audit records `catalog_year_used`, the declaration's governing catalog year, and `gpa_at_audit`, a snapshot of the student's `institutional_gpa` at audit time — completed work only, even for a `CONDITIONAL` run. Audit history can be reviewed filtered by `audit_kind`, `status`, and `target_program_id`.

The progress totals work as follows. `total_credits_applied` sums `credits_earned` over the student's `COMPLETED` enrollments, institutional and transfer combined. A `CONDITIONAL` audit additionally projects every `IN_PROGRESS` enrollment at its course's full `credits`, adds that projected sum into `total_credits_applied`, and reports the projected amount as `in_progress_credits_counted`; every other kind reports zero there and gives in-progress work no weight whatsoever — so identical records can satisfy under `CONDITIONAL` and fall short under `STANDARD`. `outstanding_credits` is the shortfall of `total_credits_applied` below the target program's `min_total_credits`, floored at zero when the applied credits meet or exceed the minimum.

Group satisfaction is a deterministic waterfall. For each requirement group of the target program, the **effective requirement** is the group's `required_credits` reduced by the sum of `credit_waiver_amount` across `APPROVED` `WAIVER` exceptions on that group, never below zero. An enrollment is eligible for a group when it is `COMPLETED`, its grade is one of `A` through `D`, the grade's value (A=4, B=3, C=2, D=1) is at least the value of the group's `min_grade`, and either the enrollment's course code appears in the group's `eligible_course_codes` or an `APPROVED` `SUBSTITUTION` exception maps that enrollment into the group. In a `CONDITIONAL` audit only, `IN_PROGRESS` enrollments are additionally treated as eligible, projected at full course credits with the minimum-grade test bypassed — they are assumed passed. A single enrollment may feed at most one group. Eligible enrollments are processed oldest first by `created_at`, with ties broken by course code ascending and then by `term` ascending; each enrollment is allocated to the eligible group with the largest remaining deficit — effective requirement minus credits already allocated — with ties broken by `group_code` ascending; and when no eligible group still has a deficit, the enrollment counts only toward `total_credits_applied`. A group is satisfied when its allocated credits reach its effective requirement. The audit's `groups_result` reports one object per group containing `requirement_group_id`, `group_code`, `credits_applied`, `effective_required_credits`, and `satisfied`.

The audit's verdict, `overall_satisfied`, requires three conjuncts: every group of the target program satisfied, `total_credits_applied` at least the program's `min_total_credits`, and `gpa_at_audit` at least the program's `min_gpa`. A program with no requirement groups satisfies the group conjunct vacuously. After a `FINAL` audit is created or recomputed, the declaration's `latest_audit_satisfied` takes the audit's `overall_satisfied`, and the declaration's `version` increments whenever that flag changes; `WHAT_IF` audits never touch the flag. Recomputation follows §2.11: enrollment mutations and exception approvals or revocations recompute the `CURRENT` audits of kind `STANDARD`, `CONDITIONAL`, and `FINAL` on the student's `ACTIVE` declarations, while `SUPERSEDED` audits and all `WHAT_IF` snapshots are left exactly as computed.

### 3.5. Audit Exceptions: The Substitution and Waiver Approval Chain

When the standard rules do not fit a student's situation, the system supports formal audit exceptions. An `Advisor` — or the owning `Student` — files an exception against a declaration, naming the `requirement_group_id` it applies to and the `kind`: `SUBSTITUTION` maps a specific enrollment into the group, while `WAIVER` reduces the group's required credits. A substitution must name its `enrollment_id`; a waiver must state its `credit_waiver_amount`; a substitution without `enrollment_id` or a waiver without `credit_waiver_amount` is rejected with `ERR_INVALID_REQUEST`. An optional free-text `reason` may accompany the request. The system stamps the exception with `requested_by_role` — `STUDENT` or `ADVISOR`, copied from the requester's role header — and `requested_by_user_id`, copied from `X-User-ID`, and the exception starts life `SUBMITTED`. Each exception identifies its target declaration via `student_program_id`, and the exception review queue can be filtered by `student_program_id`, `requirement_group_id`, `enrollment_id`, `status`, and `requested_by_user_id`.

The first decision step belongs to an `Advisor`, who submits a `decision`: `APPROVE` moves the exception from `SUBMITTED` to `ADVISOR_APPROVED`, while `DENY` moves it to `DENIED` and records the supplied `decision_reason`. The guards fire in gatekeeping order. First the state check — anything other than `SUBMITTED` is rejected with `ERR_WAIVER_INVALID_STATE`. Then segregation of duties: when the original `requested_by_role` was `ADVISOR` and the deciding `X-User-ID` equals the recorded `requested_by_user_id`, the decision is refused with `ERR_SELF_APPROVAL_FORBIDDEN`, so an advisor can never adjudicate a request they filed themselves. Finally, for a `SUBSTITUTION`, the referenced enrollment must be `COMPLETED`; a substitution built on unfinished coursework is rejected with `ERR_ENROLLMENT_NOT_COMPLETED`.

The second and final step belongs to `RegistrarStaff`, acting on an `ADVISOR_APPROVED` exception with a `decision`: `APPROVE` moves it to `APPROVED`, and `DENY` moves it to `DENIED` with the `decision_reason` recorded. The state check again comes first (`ERR_WAIVER_INVALID_STATE` from any other state), and the completed-enrollment requirement is re-examined for substitutions (`ERR_ENROLLMENT_NOT_COMPLETED`) because grading may have moved on between the two steps. Approval takes effect immediately: the `CURRENT` audits of the declaration are recomputed with the exception applied — substituted enrollments flow into their new group, waived amounts shrink the group's effective requirement — and `latest_audit_satisfied` refreshes from the `CURRENT` `FINAL` audit, incrementing the declaration's `version` when the flag changes.

A denied exception is not dead. An `Advisor` or the owning `Student` may resubmit it, which moves `DENIED` back to `SUBMITTED` and may optionally change the `enrollment_id`, `credit_waiver_amount`, or `reason`; resubmission from any other state meets `ERR_WAIVER_INVALID_STATE`. Crucially, resubmission preserves the *original* `requested_by_role` and `requested_by_user_id`, so the segregation-of-duties anchor survives the rewrite — whoever resubmits does not become the requester of record.

Approval is likewise reversible. `RegistrarStaff` may revoke an `APPROVED` exception, supplying a `reason` that is recorded as the exception's `decision_reason`; the exception moves from `APPROVED` to its terminal state `REVOKED`. Revocation recomputes the `CURRENT` audits with the exception removed, compensating the approval exactly — group credits and `outstanding_credits` return to their pre-approval values — and refreshes `latest_audit_satisfied` from the `CURRENT` `FINAL` audit.

### 3.6. Graduation Applications and the Certification Review

When the finish line is in sight, the owning `Student` opens a graduation application on a declaration, supplying the `expected_term` of graduation (for example, 2026-SP) and the `expected_conferral_date` as an ISO calendar date, and optionally a `diploma_name` to print instead of the legal name. The application starts in `DRAFT`. A declaration's applications can be listed and filtered by `status`.

Submission is the student's formal filing and carries four guards, evaluated in gatekeeping order. The application must be `DRAFT` — submission from any other state is `ERR_APPLICATION_INVALID_STATE`. There must be no other live application for the same declaration: a sibling in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, `CLEARED`, or `CONDITIONALLY_CLEARED` blocks the filing with `ERR_ACTIVE_APPLICATION_EXISTS`, while terminal `DENIED` and `DEGREE_CONFERRED` applications do not. The filing window must still be open: the logical clock must read on or before the date thirty days before the `expected_conferral_date`, and a later filing is rejected with `ERR_FILING_DEADLINE_PASSED`. Finally the student's `financial_hold` must be false, else the filing stops with `ERR_FINANCIAL_HOLD`. A clean submission moves `DRAFT` → `SUBMITTED`.

Review begins when `RegistrarStaff` takes the application from `SUBMITTED` to `UNDER_REVIEW`. Two preconditions apply, in order: a `CURRENT` `FINAL` audit must exist for the declaration — beginning review without one is rejected with `ERR_FINAL_AUDIT_REQUIRED` — and the financial hold is re-examined, with a held student refused via `ERR_FINANCIAL_HOLD`.

The certification decision rests with `RegistrarStaff`, who submits a `decision` with an optional `decision_reason` from the `UNDER_REVIEW` state (any other state meets `ERR_APPLICATION_INVALID_STATE`). Three outcomes exist. `CLEARED` certifies the degree and requires the `CURRENT` `FINAL` audit's `overall_satisfied` to be true; an unsatisfied audit blocks clearance with `ERR_AUDIT_NOT_SATISFIED`. `CONDITIONALLY_CLEARED` is the final-term contingency path for students whose coursework is still in flight, and requires at least one `IN_PROGRESS` enrollment; without one the decision is rejected with `ERR_NO_IN_PROGRESS_ENROLLMENTS`. `DENIED` ends the application terminally, recording the `decision_reason`.

A conditionally cleared application then resolves itself as grading finishes — no further human action is required. When an enrollment mutation (a grade posting or a grade change, including a withdrawal) leaves the student with zero `IN_PROGRESS` enrollments, the recomputed `CURRENT` `FINAL` audit decides the outcome as the terminal hop of the recompute cascade: if `overall_satisfied` is true the application moves `CONDITIONALLY_CLEARED` → `CLEARED`; if it is false the application moves `CONDITIONALLY_CLEARED` → `DENIED` with `decision_reason` set to `CONTINGENCY_FAILED`. A withdrawal resolves the contingency too, and it drives the negative branch whenever the withdrawn enrollment's credits were required for satisfaction.

### 3.7. Conferral, Latin Honors, and Diploma Production

Conferral is the act of record. `RegistrarStaff` confers a `CLEARED` application, moving it to `DEGREE_CONFERRED`; from any other state the attempt is `ERR_APPLICATION_INVALID_STATE`. Before the degree can post, an honors policy of the declaration's program whose closed effective interval contains the declaration's `catalog_year` must exist; its absence stops conferral with `ERR_HONORS_POLICY_MISSING`.

Honors are computed at the moment of conferral. The residency gate comes first: the student's `institutional_earned_credits` must be at least the policy's `residency_min_credits` — 30 unless the policy says otherwise — and a student short of the residency minimum receives the designation `NONE` regardless of grades. The basis GPA is then selected by the policy's `honors_gpa_basis`: `institutional_gpa` under `INSTITUTIONAL`, `cumulative_gpa` under `CUMULATIVE`, so the same student can earn a designation under one basis and `NONE` under the other when transfer work pulls the averages apart. The designation is `SUMMA_CUM_LAUDE` when the basis reaches `summa_threshold`, otherwise `MAGNA_CUM_LAUDE` when it reaches `magna_threshold`, otherwise `CUM_LAUDE` when it reaches `cum_threshold`, otherwise `NONE`; a basis exactly equal to a threshold earns that tier. The result is recorded as the application's `honors_designation`, and `conferred_at` is stamped from the logical clock.

Conferral cascades outward. The declaration moves from `ACTIVE` to `COMPLETED`. The student's `status` becomes `GRADUATED`. And a diploma is created in `PENDING` status whose `printed_name` is the application's `diploma_name` — or the student's `legal_name` when no diploma name was supplied — whose `conferral_date` is the application's `expected_conferral_date`, whose `honors_designation` copies the freshly computed designation, and whose `reissue_of_diploma_id` is null because it is the original.

Diploma production is then a small workflow of its own, operated by `RegistrarStaff`. Issuing moves `PENDING` → `ISSUED`. Revocation — the correction path — moves either `PENDING` or `ISSUED` → `REVOKED` and records the supplied `revocation_reason`; `REVOKED` is terminal, and any issue or revoke attempted from a state that does not allow it is rejected with `ERR_DIPLOMA_INVALID_STATE`. Diplomas can be reviewed filtered by `application_id`, `status`, and `reissue_of_diploma_id`.

Reissue produces the corrected diploma. `RegistrarStaff` reissues against a `DEGREE_CONFERRED` application whose latest diploma — the most recent by `created_at` — is `REVOKED`; if the application is not conferred or its latest diploma is anything other than `REVOKED`, the reissue is rejected with `ERR_DIPLOMA_INVALID_STATE`. The request carries a required `reason` and may carry corrected `printed_name` and/or `conferral_date` values; any value left unsupplied falls back to the same default the original used — the application's `diploma_name` or, failing that, the student's `legal_name`, and the application's `expected_conferral_date`. The new diploma starts `PENDING`, points its `reissue_of_diploma_id` at the revoked predecessor, and — unlike the original creation — has its `honors_designation` **recomputed from the student's current GPAs** under the same honors rule, so post-conferral grade corrections flow through to the corrected diploma.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource — a program, requirement group, honors policy, course, student, enrollment, declaration, audit, exception, application, or reissued diploma — return `201 Created`. Endpoints that modify an existing resource or drive a state transition return `200 OK`. Readers should reconstruct each operation's full request and response contract from the narratives in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | SystemAdmin |
| POST | `/programs` | Create a program catalog-year version | RegistrarStaff |
| GET | `/programs/{id}` | Get one program | RegistrarStaff, Advisor, Student |
| POST | `/programs/{id}/retire` | Retire a program version (blocks new declarations only) | RegistrarStaff |
| POST | `/programs/{id}/requirement-groups` | Create a requirement group under the program | RegistrarStaff |
| GET | `/programs/{id}/requirement-groups` | List requirement groups of a program | RegistrarStaff, Advisor, Student |
| POST | `/programs/{id}/honors-policies` | Create an honors policy for the program | RegistrarStaff |
| GET | `/programs/{id}/honors-policies` | List honors policies of a program | RegistrarStaff, Advisor, Student |
| GET | `/programs/{id}/student-programs` | List declarations of this program | RegistrarStaff, Advisor |
| GET | `/programs/{id}/audits` | List degree audits whose target is this program | RegistrarStaff, Advisor |
| POST | `/courses` | Create a course | RegistrarStaff |
| POST | `/students` | Create a student | RegistrarStaff |
| GET | `/students/{id}` | Get one student with computed credits and GPAs | RegistrarStaff, Advisor, Student |
| POST | `/students/{id}/enrollments` | Create an enrollment (graded or in-progress) | RegistrarStaff |
| GET | `/enrollments` | List enrollments with filters | RegistrarStaff, Advisor, Student |
| GET | `/enrollments/{id}` | Get one enrollment | RegistrarStaff, Advisor, Student |
| POST | `/enrollments/{id}/post-grade` | Post a grade on an in-progress enrollment | RegistrarStaff |
| POST | `/enrollments/{id}/grade-changes` | Correct the grade of a completed or withdrawn enrollment | RegistrarStaff |
| POST | `/students/{id}/programs` | Declare a major (create a program declaration) | RegistrarStaff, Student |
| GET | `/student-programs` | List program declarations with filters | RegistrarStaff, Advisor, Student |
| GET | `/student-programs/{id}` | Get one program declaration | RegistrarStaff, Advisor, Student |
| POST | `/student-programs/{id}/withdraw` | Withdraw an active declaration | RegistrarStaff, Student |
| POST | `/student-programs/{id}/audits` | Run a degree audit of a given kind (supersedes prior same-kind audit) | RegistrarStaff, Advisor, Student |
| GET | `/student-programs/{id}/audits` | List audits of a declaration | RegistrarStaff, Advisor, Student |
| POST | `/student-programs/{id}/waivers` | File a substitution or waiver exception | Advisor, Student |
| GET | `/substitution-waivers` | List exceptions with filters | RegistrarStaff, Advisor |
| GET | `/substitution-waivers/{id}` | Get one exception | RegistrarStaff, Advisor, Student |
| POST | `/substitution-waivers/{id}/advisor-decision` | Advisor step of the exception approval chain | Advisor |
| POST | `/substitution-waivers/{id}/registrar-decision` | Registrar step of the exception approval chain | RegistrarStaff |
| POST | `/substitution-waivers/{id}/resubmit` | Resubmit a denied exception | Advisor, Student |
| POST | `/substitution-waivers/{id}/revoke` | Revoke an approved exception | RegistrarStaff |
| POST | `/student-programs/{id}/applications` | Create a graduation application (draft) | Student |
| GET | `/student-programs/{id}/applications` | List applications of a declaration | RegistrarStaff, Advisor, Student |
| GET | `/applications/{id}` | Get one graduation application | RegistrarStaff, Advisor, Student |
| POST | `/applications/{id}/submit` | Submit a draft application | Student |
| POST | `/applications/{id}/begin-review` | Begin registrar review of a submitted application | RegistrarStaff |
| POST | `/applications/{id}/decide` | Decide an application under review (clear, conditionally clear, or deny) | RegistrarStaff |
| POST | `/applications/{id}/confer` | Confer the degree on a cleared application | RegistrarStaff |
| GET | `/diplomas` | List diplomas with filters | RegistrarStaff, Advisor, Student |
| GET | `/diplomas/{id}` | Get one diploma | RegistrarStaff, Advisor, Student |
| POST | `/diplomas/{id}/issue` | Issue a pending diploma | RegistrarStaff |
| POST | `/diplomas/{id}/revoke` | Revoke a pending or issued diploma | RegistrarStaff |
| POST | `/applications/{id}/diplomas/reissue` | Create a corrected diploma for a conferred application whose latest diploma is revoked | RegistrarStaff |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue enumerates only the identifier and its HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_PAGINATION_PARAMETERS` | 400 Bad Request |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_FINANCIAL_HOLD` | 402 Payment Required |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_REQUIREMENT_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_WAIVER_NOT_FOUND` | 404 Not Found |
| `ERR_APPLICATION_NOT_FOUND` | 404 Not Found |
| `ERR_DIPLOMA_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_INVALID_STATE` | 409 Conflict |
| `ERR_PROGRAM_RETIRED` | 409 Conflict |
| `ERR_ENROLLMENT_INVALID_STATE` | 409 Conflict |
| `ERR_STUDENT_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_WAIVER_INVALID_STATE` | 409 Conflict |
| `ERR_APPLICATION_INVALID_STATE` | 409 Conflict |
| `ERR_DIPLOMA_INVALID_STATE` | 409 Conflict |
| `ERR_UNIQUE_CONSTRAINT_VIOLATION` | 409 Conflict |
| `ERR_CATALOG_RANGE_OVERLAP` | 409 Conflict |
| `ERR_POLICY_RANGE_OVERLAP` | 409 Conflict |
| `ERR_ACTIVE_APPLICATION_EXISTS` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_FINAL_AUDIT_REQUIRED` | 409 Conflict |
| `ERR_AUDIT_NOT_SATISFIED` | 409 Conflict |
| `ERR_NO_IN_PROGRESS_ENROLLMENTS` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FILING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CATALOG_YEAR_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_ENROLLMENT_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_HONORS_POLICY_MISSING` | 422 Unprocessable Entity |

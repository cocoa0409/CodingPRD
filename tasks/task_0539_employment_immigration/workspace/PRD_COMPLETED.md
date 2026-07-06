# Employment-Immigration API — Product Requirements Document

## 1. Introduction

This document specifies the Employment-Immigration API, a compliance-and-orchestration backend that carries an employer's foreign-worker sponsorship from a prevailing-wage determination all the way through green-card adjudication. A single case touches four distinct regulators — the sponsoring employer's agent, a Department of Labor wage-and-certification analyst, a USCIS adjudicator, and a public-access-file compliance auditor — and each of them owns a narrow, non-overlapping set of actions. The system exists so that these parties can operate against one shared, auditable record without any of them silently performing another's exclusive step.

The domain is unusually rich in time-window arithmetic and cross-document dependencies. Recruitment must run for a minimum span before a mandatory quiet period, a labor condition application must be certified before an H-1B petition can be submitted against it, a cap registration must be selected in a fiscal-year lottery before a petition can proceed, and a green-card petition inherits its queue position from an underlying labor certification. Because a single upstream event — superseding a wage determination, withdrawing a certified application, denying a labor case — can invalidate work that depends on it, the API models these knock-on effects explicitly as cascades rather than leaving them to the client. All monetary amounts are held in integer cents, and a logical (test-driven) clock governs every window so that time-sensitive behavior is fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across every endpoint: authentication, response shape, pagination, common resource fields, monetary precision, concurrency control, cascade consistency, referential resolution, and validation ordering.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `EmployerAgent`, `DOLAnalyst`, `USCISOfficer`, and `ComplianceAuditor`.

`EmployerAgent` is an **entity-backed** role: when `X-User-Role` is `EmployerAgent`, `X-User-ID` is the `id` of the acting `Employer`. Ownership checks on any resource that references an `Employer` compare the resource's `employer_id` to `X-User-ID`; an `EmployerAgent` may only create, transition, or otherwise mutate resources whose `employer_id` equals its own employer id, and an attempt to act on another employer's resource is rejected with `ERR_UNAUTHORIZED`. The one exception is employer registration itself, where no prior resource is being owned.

The remaining three roles are **opaque** operator identities. When `X-User-Role` is `DOLAnalyst`, `USCISOfficer`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. `DOLAnalyst` issues prevailing-wage determinations and adjudicates PERM and LCA cases; `USCISOfficer` runs the cap lottery, issues RFEs, and adjudicates petitions; `ComplianceAuditor` runs public-access-file audits. Every `GET` endpoint and the logical-clock control endpoint are available to all four roles.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A `limit` below 1 or above 100 is not rejected but silently clamped into the `[1, 100]` range, and a negative `offset` is clamped to 0; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION` (400). The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list responses are sorted by `created_at` in ascending order, with any ties on `created_at` broken by ascending order of creation (the server's insertion order).

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources — `Employer`, `PrevailingWageDetermination`, `PermCase`, `RecruitmentStep`, `LCA`, `Beneficiary`, `CapProgram`, `H1BRegistration`, `H1BPetition`, and `I140Petition` — carry a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation. `version` is an integer that begins at 1 on creation and increments by one on every mutation; it is the value used for optimistic concurrency control. Whenever a computed field (for example an employer's running wage obligation, or a beneficiary's derived status) changes as a side effect, that counts as a mutation of the affected resource and refreshes its `updated_at` and increments its `version`.

All ten primary entities in this system carry `updated_at` and `version`; none of them omit these fields.

Time is governed by a **logical clock**, not the wall clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it stays at that value and never falls back to real time. An operator of any role may set the clock by supplying a `to_iso8601` instant; the response returns the new `current_utc`. Advancing the clock is not merely bookkeeping: setting it re-evaluates every time-based expiry described in this document (prevailing-wage and labor-condition validity ends, and RFE response deadlines), applying the corresponding transitions and cascades before returning.

Every business date field that the server itself computes from the logical clock — a PERM case's `recruitment_start`, `recruitment_end`, `quiet_period_end`, `filed_date`, and `priority_date`; an H-1B petition's `rfe_issued_date`, `rfe_due_date`, and `rfe_response_date`; an I-140 petition's `filed_date` and `priority_date`; the clock endpoint's returned `current_utc`; and any derived field that copies one of these values — is serialized in the **same canonical form as the clock itself**: a whole-second instant carries **no** fractional digits (as in the startup value `2026-05-01T00:00:00Z`), and only a sub-second instant falls back to three fractional digits. This is distinct from the system-audit timestamps `created_at`, `updated_at`, and `api_request_timestamp`, which always carry three fractional digits (§2.2, §2.4 above) — of these three, `created_at` and `updated_at` are stamped from the logical clock, whereas `api_request_timestamp` is stamped from the server's real wall-clock time — and from client-supplied dates (such as validity windows, recruitment-step windows, and employment windows, and any derived field that copies one of those), which are echoed back verbatim exactly as submitted.

### 2.5. Monetary Amounts, Wage Units, and Rounding

Every monetary amount in the system is an integer number of cents; there are no fractional cents and no floating-point money. Wage figures such as an OES survey wage, an employer survey wage, an offered wage, a prevailing wage, a required wage, an aggregate wage obligation, and USCIS filing fees are all stored and returned as integer cents.

Only one calculation performs division and therefore requires rounding: the aggregate wage obligation prorates each worksite's annual wage by a weekly-hours fraction. That proration is rounded **half up** to a whole number of cents, and the rounding is applied **per worksite area before the amounts are summed** — never once at the end on the grand total. All other calculations (required wage, filing fee, seat accounting, employer wage obligation) are exact integer arithmetic with no rounding.

### 2.6. Optimistic Concurrency on Prevailing-Wage Issuance

Issuing a prevailing-wage determination — the transition that moves it from `PENDING` to `ISSUED` — is guarded by optimistic concurrency against its parent `Employer`. The issuance request must carry a non-optional `expected_employer_version` field holding the `version` of the parent `Employer` that the client last observed. If `expected_employer_version` does not equal the parent `Employer`'s current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated.

This guard exists because issuance both supersedes any prior issued determination for the same employer, occupation, and area, and increments the employer's `version`. A client that last read the employer before some other issuance advanced that `version` is working from a stale view and would otherwise overwrite an issuance it never saw; the version check forces it to re-read first. No other endpoint takes a version field, and none other than prevailing-wage issuance performs an OCC check.

### 2.7. Cascading Consistency Across Immigration Aggregates

Because immigration documents depend on one another, several actions have effects that reach beyond the resource named in the request. The system applies these cascades automatically and immediately; the client never issues the secondary calls. Each cascaded resource is genuinely mutated, so its `updated_at` and `version` advance just as a direct edit would.

Three cascade families exist, and each is described in full where its workflow lives in Section 3:

- **Wage-determination supersession.** When a determination is superseded, every dependent PERM case that is still in an early stage is reverted to `DRAFT`, and every active recruitment step under such a case is voided.
- **Labor-certification withdrawal.** Withdrawing a certified labor condition application both reverses its contribution to the employer's wage obligation and denies every H-1B petition that was built on it and had not yet been adjudicated.
- **Labor-case denial.** Denying a PERM case denies every not-yet-adjudicated green-card petition that inherited from it.

In addition, approving, denying, or expiring an H-1B petition, and approving or denying a green-card petition, each recompute the affected beneficiary's derived status fields. The precise trigger states and the exact set of children touched by each cascade are specified in Section 3; this subsection only establishes that such propagation is the server's responsibility and that it mutates every resource it touches.

### 2.8. Referential Integrity and Left-to-Right Resolution

Every request that names a resource by a path `{id}` or references another resource through a foreign-key field in its body must resolve those references before any business rule runs. Resolution is performed left to right: the path `{id}` is checked first, then each foreign-key body field in the order it appears. The first identifier that does not resolve to an existing resource causes an immediate `ERR_NOT_FOUND` (HTTP 404); later references are not examined once the first missing one is found. For example, creating an H-1B petition resolves its `employer_id`, `lca_id`, `beneficiary_id`, and `registration_id` in turn, and a missing `lca_id` is reported before the system looks at `beneficiary_id`.

Foreign keys never appear as schema declarations to the caller; they are supplied as fields in request bodies (`employer_id`, `pwd_id`, `perm_case_id`, `lca_id`, `beneficiary_id`, `registration_id`) and are validated as described above.

### 2.9. Validation Order and Precedence

When more than one rule could reject a request, the checks run in a fixed priority order, and the first failure determines the returned error. This ordering matters: a later, more specific rejection must never mask an earlier, more general one. The order is:

1. **Authentication** — headers present and `X-User-Role` known; otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization** — the acting role is permitted for the operation, and an `EmployerAgent` owns the target employer's resources; otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. **Existence** — the path `{id}` and every foreign key resolve, left to right; otherwise `ERR_NOT_FOUND` (404).
4. **Body well-formedness** — required fields present, enums valid, numbers in range, and the field-level rules of §2.5/§3 satisfied; otherwise `ERR_VALIDATION` (400). Applies to every `POST` and `PATCH`.
5. **Registration uniqueness** — no duplicate cap registration; otherwise `ERR_DUPLICATE_REGISTRATION` (409). Applies to cap-registration creation only.
6. **Optimistic concurrency** — `expected_employer_version` matches; otherwise `ERR_STALE_VERSION` (412). Applies to prevailing-wage issuance only.
7. **State legality** — the requested transition is defined from the resource's current state; otherwise `ERR_INVALID_STATE` (409). Applies to every state-changing action (transitions, running the lottery, issuing/responding to an RFE, and running a PAF audit).
8. **Cross-entity referential gates** — the referenced upstream document is in the required state (409 family: `ERR_PWD_NOT_ISSUED`, `ERR_LCA_NOT_CERTIFIED`, `ERR_REGISTRATION_NOT_SELECTED`, `ERR_PERM_NOT_CERTIFIED`, `ERR_WORKSITE_NOT_COVERED`, `ERR_REGISTRATION_HAS_PETITION`).
9. **Temporal gates** — logical-clock window rules (422 family: `ERR_RECRUITMENT_TOO_SHORT`, `ERR_QUIET_PERIOD_NOT_ELAPSED`, `ERR_PERM_VALIDITY_EXPIRED`, `ERR_RFE_EXPIRED`).
10. **Recruitment structural completeness** — the required mix of active steps exists; otherwise `ERR_RECRUITMENT_INCOMPLETE` (422). Applies to entering the quiet period.
11. **Recruitment-step overlap** — `ERR_RECRUITMENT_STEP_OVERLAP` (409). Applies to recruitment-step creation.
12. **Employment-interval overlap** — `ERR_EMPLOYMENT_OVERLAP` (409). Applies to approving an H-1B petition.
13. **Wage floor** — the offered wage meets the prevailing wage; otherwise `ERR_WAGE_BELOW_PREVAILING` (422). Applies to starting PERM recruitment and to certifying a labor condition application.

A concrete consequence of this ordering: when an employer tries to enter the quiet period too early **and** with an incomplete recruitment record, the too-short temporal failure (`ERR_RECRUITMENT_TOO_SHORT`, priority 9) is reported before the incompleteness failure (`ERR_RECRUITMENT_INCOMPLETE`, priority 10).

## 3. Business Logic & Workflows

### 3.1. Employers and the Running Wage Obligation

An `EmployerAgent` bootstraps a sponsorship by registering an `Employer`, supplying the employer's `fein` (its Federal Employer Identification Number, nominally nine digits but accepted and stored as any non-empty string, with no digit-count validation), its `legal_name`, and its `employee_count` — the US full-time-equivalent headcount, which must be at least 1 and which later drives H-1B fee tiers. The agent may also set `h1b_dependent`, a boolean flag that defaults to false and later drives one of the larger filing-fee add-ons. On registration the employer's `total_wage_obligation_cents` starts at 0 and its `version` starts at 1. Because this is the only creation that has no pre-existing owner, `X-User-ID` need not match anything on this call; from then on, that same id is the employer whose resources this agent may touch.

`total_wage_obligation_cents` is a running ledger of the wage the employer is on the hook for. It is defined as the sum of `required_wage_cents` over exactly those of the employer's labor condition applications whose `status` is `CERTIFIED`. It moves only through certification and withdrawal: certifying an application adds that application's locked `required_wage_cents`, and withdrawing a certified application subtracts the same amount. The invariant is that at any moment `total_wage_obligation_cents` equals the summed `required_wage_cents` of the employer's currently-`CERTIFIED` applications.

### 3.2. Prevailing-Wage Determinations

Before recruiting, an `EmployerAgent` requests a `PrevailingWageDetermination` for a position. The request carries the `employer_id`, the occupation `soc_code` (an SOC/O*NET code such as 15-1252), the `job_title`, the `area_code` for the geographic worksite, the `wage_level` (one of `LEVEL_I`, `LEVEL_II`, `LEVEL_III`, or `LEVEL_IV`), a `wage_source` of either `OES` or `EMPLOYER_SURVEY`, the `oes_wage_cents` (the OES annual survey wage for this occupation, level, and area, which may not be negative), and the validity window `validity_start` through `validity_end`. When `wage_source` is `EMPLOYER_SURVEY`, the request must also carry `survey_wage_cents`, the employer-provided annual survey wage; omitting it in that case is an `ERR_VALIDATION` (400). `survey_wage_cents` defaults to null and is otherwise unused when the source is `OES`. As with every dated resource, `validity_end` must be strictly after `validity_start`. A freshly created determination is in `PENDING`.

Only a `DOLAnalyst` may issue a determination, advancing it from `PENDING` to `ISSUED`. Issuance is allowed only from `PENDING` (otherwise `ERR_INVALID_STATE`), requires the `expected_employer_version` concurrency check of §2.6 (a mismatch yields `ERR_STALE_VERSION`, 412), and — when the source is `EMPLOYER_SURVEY` — requires that `survey_wage_cents` be present (otherwise `ERR_VALIDATION`). On issuance the system stamps `prevailing_wage_cents`: it is set equal to `oes_wage_cents` when `wage_source` is `OES`, and equal to `survey_wage_cents` when `wage_source` is `EMPLOYER_SURVEY`. Issuance then supersedes competition: any other determination for the same combination of `employer_id`, `soc_code`, and `area_code` that is currently `ISSUED` transitions from `ISSUED` to `SUPERSEDED`. Finally, issuance increments the parent `Employer`'s `version` by one.

Supersession is a system-driven transition; it is never requested through the API, and neither is expiry. Expiry happens on its own when the logical clock advances past a determination's `validity_end`, moving an `ISSUED` determination to `EXPIRED`. Both `SUPERSEDED` and `EXPIRED` are terminal, and a `DOLAnalyst` who tries to name either of them as a target is rejected with `ERR_INVALID_STATE`.

When a determination is superseded, the effect ripples to PERM cases built on it. Every `PermCase` whose `pwd_id` points at the now-superseded determination and whose `status` is `RECRUITING` or `QUIET_PERIOD` is reverted to `DRAFT`; a case already in `DRAFT` is left untouched, with no state change and no `version` increment. The recruitment consequences of that revert are detailed in §3.3.

Determinations can be listed and filtered by `employer_id` or by `status`.

### 3.3. PERM Labor Certification: Recruitment, Quiet Period, Filing, and the Audit Cycle

A `PermCase` is the labor-certification file. An `EmployerAgent` creates one in `DRAFT` by supplying the `employer_id`, the `pwd_id` of the governing determination, the certified `job_title`, and the `offered_wage_cents` — the annual wage the employer commits to pay, which may not be negative.

Recruitment begins when the agent moves the case from `DRAFT` to `RECRUITING`. This is permitted only from `DRAFT`, and only when the referenced determination is `ISSUED` (otherwise `ERR_PWD_NOT_ISSUED`) and the case's `offered_wage_cents` is at least the determination's `prevailing_wage_cents` (otherwise `ERR_WAGE_BELOW_PREVAILING`). On success the system stamps `recruitment_start` to the current logical clock.

While recruiting, the agent records `RecruitmentStep` entries against the case, each referencing its `perm_case_id`, a `step_type` — one of `JOB_ORDER`, `NEWSPAPER_AD`, `PROFESSIONAL_JOURNAL`, `EMPLOYER_WEBSITE`, or `JOB_FAIR` — and the activity window `start_date` through `end_date`, where `end_date` must be on or after `start_date`. A new step is created `ACTIVE`. Two `ACTIVE` steps of the *same* `step_type` on one case may not overlap in time, and here the interval is **closed** on both ends — the span runs inclusively from `start_date` through `end_date`, so two same-type steps that merely touch at an endpoint (one ends exactly where the next begins) still conflict and the create is rejected with `ERR_RECRUITMENT_STEP_OVERLAP` (409). Different step types never conflict with one another.

The agent then moves the case from `RECRUITING` to `QUIET_PERIOD`. This is permitted only from `RECRUITING`, and enforces two gates. First, recruitment must have run long enough: the span from `recruitment_start` to the current clock must be at least 30 days, or the request is rejected with `ERR_RECRUITMENT_TOO_SHORT`. Second, the recruitment record must be structurally complete: there must exist at least one `ACTIVE` step of `step_type` `JOB_ORDER` and at least two `ACTIVE` steps of `step_type` `NEWSPAPER_AD`, or the request is rejected with `ERR_RECRUITMENT_INCOMPLETE`. Per §2.9 the too-short check precedes the completeness check. On success the system stamps `recruitment_end` to the current clock and computes `quiet_period_end` as `recruitment_end` plus 30 days — the earliest instant at which filing becomes permissible.

Filing moves the case from `QUIET_PERIOD` to `FILED`, and is permitted only from `QUIET_PERIOD`. Two temporal gates apply. The quiet period must have fully elapsed: the current clock must be at or after `quiet_period_end`, otherwise `ERR_QUIET_PERIOD_NOT_ELAPSED`. And the overall PERM window must not have lapsed: the current clock must be at or before `recruitment_start` plus 180 days, otherwise `ERR_PERM_VALIDITY_EXPIRED`. On success the system stamps `filed_date` to the current clock and sets `priority_date` equal to `filed_date`; this priority date is the queue position a later PERM-based green-card petition inherits.

After filing, the Department of Labor may select the case for audit. A `DOLAnalyst` moves it from `FILED` to `AUDIT` (permitted only from `FILED`). The employer answers the audit, and an `EmployerAgent` moves it back from `AUDIT` to `FILED` (permitted only from `AUDIT`). This `FILED` ⇄ `AUDIT` loop may repeat. A `DOLAnalyst` reaches a terminal outcome by certifying the case to `CERTIFIED` — defined **only** from `FILED`, so an `AUDIT`-state case must first be moved back to `FILED` before it can be certified — or by denying it to `DENIED`, which is defined from either `FILED` or `AUDIT`. Denial from `FILED` or from `AUDIT` cascades downstream: every `I140Petition` whose `perm_case_id` points at this case and whose `status` is `DRAFT` or `SUBMITTED` is transitioned to `DENIED`.

Reverting to draft is the other side of supersession. When the case's governing determination is superseded (see §3.2), the case is thrown back to `DRAFT`. If it was `RECRUITING`, every `ACTIVE` `RecruitmentStep` on the case is voided (moved from `ACTIVE` to `VOID`) and `recruitment_start` is cleared. If it was in `QUIET_PERIOD`, the same steps are voided and all three of `recruitment_start`, `recruitment_end`, and `quiet_period_end` are cleared, since the whole recruitment record is now stale. `CERTIFIED` and `DENIED` are terminal. Recruitment steps can be listed and filtered by `perm_case_id` or `status`; PERM cases can be listed and filtered by `employer_id`, `pwd_id`, or `status`.

### 3.4. Labor Condition Applications and the Public-Access File

An `LCA` (Labor Condition Application) is the wage-and-worksite attestation that underlies an H-1B petition. An `EmployerAgent` creates one in `DRAFT`, supplying the `employer_id`, the `soc_code`, the list of `worksite_areas` (at least one area code), an `area_wage_map` giving the annual prevailing wage in cents for every area listed in `worksite_areas`, the `offered_wage_cents`, the `prevailing_wage_cents` for the primary worksite (the first entry of `worksite_areas`), an optional `hours_per_week` that defaults to 40 and must fall between 1 and 40 inclusive, and the validity window `validity_start` through `validity_end`, where `validity_end` must be strictly after `validity_start`. The body must also supply the four public-access-file document flags — `has_wage_rate`, `has_prevailing_wage_doc`, `has_notice_of_filing`, and `has_actual_wage_memo` — each a boolean defaulting to false. If the `area_wage_map` fails to cover every entry in `worksite_areas`, the create is rejected with `ERR_VALIDATION`. A new application's `paf_status` starts at `OPEN`.

The application exposes two computed money fields. `required_wage_cents` is the greater of `prevailing_wage_cents` and `offered_wage_cents`. While the application is in `DRAFT` this figure is **provisional**: it is recomputed on every read from the application's current `prevailing_wage_cents`, so editing that field before certification changes it. At the moment of certification the value is **locked** using the `prevailing_wage_cents` then in effect, and later edits cannot change a locked value. (Consequently, if `prevailing_wage_cents` is raised between draft and certification while `offered_wage_cents` stays constant, the provisional figure seen in draft and the final locked figure can differ.) `aggregate_wage_obligation_cents` prorates worksite wages by hours: iterating over `worksite_areas` in list order, each area's entry in `area_wage_map` is multiplied by `hours_per_week`, divided by 40, and rounded half up to whole cents; those per-area rounded amounts are then summed. The rounding is per area, before summing — never applied once to the total.

A `DRAFT` application may be edited by its `EmployerAgent` to correct `prevailing_wage_cents`, `offered_wage_cents`, `area_wage_map`, `hours_per_week`, or any of the four PAF flags. Editing recomputes the provisional `required_wage_cents` and the `aggregate_wage_obligation_cents`. Edits are permitted only while the status is `DRAFT`; an edit attempt on a non-draft application is rejected with `ERR_INVALID_STATE`.

Only a `DOLAnalyst` may certify, moving the application from `DRAFT` to `CERTIFIED`. Certification is defined only from `DRAFT`, and requires that `offered_wage_cents` be at least `prevailing_wage_cents` (otherwise `ERR_WAGE_BELOW_PREVAILING`). On certification the system locks `required_wage_cents` to the greater of `prevailing_wage_cents` and `offered_wage_cents` as of that instant, and adds that locked amount to the employer's `total_wage_obligation_cents`.

The employer's agent may later withdraw a certified application, moving it from `CERTIFIED` to `WITHDRAWN` (defined only from `CERTIFIED`). Withdrawal both subtracts the application's locked `required_wage_cents` back out of the employer's `total_wage_obligation_cents` and cascades to petitions: every `H1BPetition` whose `lca_id` points at this application and whose `status` is `DRAFT`, `SUBMITTED`, or `RFE_ISSUED` is transitioned to `DENIED`. Separately, expiry is system-driven: when the logical clock advances past a certified application's `validity_end`, it moves from `CERTIFIED` to `EXPIRED`. Both `WITHDRAWN` and `EXPIRED` are terminal.

Public-access-file compliance is audited by a `ComplianceAuditor`, the only role permitted to run a PAF audit on an application. The audit recomputes `paf_completeness_score` from the four document flags: each of `has_wage_rate`, `has_prevailing_wage_doc`, `has_notice_of_filing`, and `has_actual_wage_memo` that is true contributes 25 points, for a score between 0 and 100. The audit then sets `paf_status` to `COMPLETE` when the score is exactly 100, and to `DEFICIENT` otherwise. Applications can be listed and filtered by `employer_id` or `status`.

### 3.5. Cap Registration and the Deterministic Lottery

Each H-1B fiscal year is represented by a `CapProgram`, created by a `USCISOfficer` with a `fiscal_year` (unique across programs; creating a second program for a `fiscal_year` that already has one is rejected with `ERR_VALIDATION`) and a `selection_quota` — the total number of cap seats, which may not be negative. On creation `selected_count` starts at 0, `available_seats` equals the `selection_quota`, and `lottery_run` is false. The seat accounting obeys the invariant `available_seats` + `selected_count` = `selection_quota` at all times; `selected_count` is defined as the number of registrations for this `fiscal_year` whose `status` is `SELECTED`, and `available_seats` is `selection_quota` minus `selected_count`.

An `EmployerAgent` enters the lottery by creating an `H1BRegistration` with the `employer_id`, the `beneficiary_id`, and the `fiscal_year`, which must match an existing program (otherwise the request is rejected with `ERR_VALIDATION`). Registrations are unique per employer, beneficiary, and fiscal year: a second registration sharing the same `employer_id`, `beneficiary_id`, and `fiscal_year` as an existing one is rejected with `ERR_DUPLICATE_REGISTRATION` (409). A new registration is `SUBMITTED`.

The lottery itself is run by a `USCISOfficer` and, despite the name, is fully deterministic rather than random. It gathers every registration whose `fiscal_year` matches the program and whose `status` is `SUBMITTED`, sorts those candidates by `created_at` ascending (and only `created_at`, never `id`, as the tie-break), and walks them in that order: each candidate whose position is below the number of available seats is moved from `SUBMITTED` to `SELECTED`, and the rest are moved from `SUBMITTED` to `NOT_SELECTED`. Because no seats have yet been taken when the lottery runs, the number of available seats at that point equals `selection_quota`. Each selection increments `selected_count` by one and decrements `available_seats` by one. After the walk, `lottery_run` is set to true. If no candidates qualify, nothing is selected and `available_seats` remains equal to `selection_quota`.

A selected registration can be withdrawn by its `EmployerAgent`, moving it from `SELECTED` to `WITHDRAWN` (defined only from `SELECTED`). Withdrawal is blocked while any `H1BPetition` references the registration: if a petition names this registration, the request is rejected with `ERR_REGISTRATION_HAS_PETITION`. A successful withdrawal is compensating — it decrements the program's `selected_count` by one and increments `available_seats` by one, returning the seat to the pool. `NOT_SELECTED` and `WITHDRAWN` are terminal. Registrations can be listed and filtered by `employer_id`, `beneficiary_id`, `fiscal_year`, or `status`; a program can be fetched to read its live `selected_count` and `available_seats`.

### 3.6. H-1B Petitions: Filing Fee, Submission, the RFE Cycle, and Adjudication

A `Beneficiary` — the foreign worker — is registered by an `EmployerAgent` with a `full_name` and a `passport_number` (a non-empty string that is stored as supplied; the server does not enforce passport-number uniqueness). A beneficiary carries three derived fields, all recomputed by the system rather than supplied. `status_valid_until` is the maximum `employment_end` across the beneficiary's `APPROVED` H-1B petitions, or null when there are none. `current_status_code` is `NONE` when the beneficiary has no `APPROVED` H-1B petition; otherwise it is `H1B_ACTIVE` when the logical clock is strictly before `status_valid_until`, and `H1B_EXPIRED` when the clock is at or after `status_valid_until`. `priority_date` on the beneficiary is the earliest `priority_date` across the beneficiary's `APPROVED` green-card petitions (with `created_at` ascending as the tie-break), or null when there are none.

An `EmployerAgent` creates an `H1BPetition` in `DRAFT`, supplying the `employer_id`, the `lca_id`, the `beneficiary_id`, the `registration_id`, the `worksite_area` (the intended area of employment), and the employment window `employment_start` through `employment_end`, where `employment_end` must be strictly after `employment_start`. The agent may set `is_amended`, a boolean defaulting to false that waives certain fees. At creation the system computes `filing_fee_cents` and initializes `rfe_status` to `NONE`.

The **filing fee** is assembled in a fixed order from the employer referenced by `employer_id` and this petition's `is_amended` flag. Start from a base fee of 46000 cents. If the petition is *not* amended, add the fraud-prevention fee of 50000 cents; then add the ACWIA training fee, which is 75000 cents when the employer's `employee_count` is at most 25 and 150000 cents when it exceeds 25; and then, only when the employer's `employee_count` is greater than 50 *and* its `h1b_dependent` flag is true, add the Public Law 114-113 fee of 400000 cents. An amended petition skips all three add-ons and pays only the 46000-cent base. The resulting total is stored as `filing_fee_cents`.

Filing the petition moves it from `DRAFT` to `SUBMITTED`, performed by an `EmployerAgent` and defined only from `DRAFT`. Submission enforces three cross-entity gates: the referenced application must be `CERTIFIED` (otherwise `ERR_LCA_NOT_CERTIFIED`), the referenced registration must be `SELECTED` (otherwise `ERR_REGISTRATION_NOT_SELECTED`), and the `worksite_area` must be one of the application's `worksite_areas` (otherwise `ERR_WORKSITE_NOT_COVERED`).

A `USCISOfficer` may issue a Request for Evidence on a submitted petition, moving it from `SUBMITTED` to `RFE_ISSUED` (defined only from `SUBMITTED`). Issuing an RFE sets `rfe_status` to `ISSUED`, stamps `rfe_issued_date` to the current clock, and computes `rfe_due_date` as `rfe_issued_date` plus 87 days. The employer answers by moving the petition back from `RFE_ISSUED` to `SUBMITTED`, permitted only from `RFE_ISSUED` and only while the current clock is at or before `rfe_due_date` (otherwise `ERR_RFE_EXPIRED`); a successful response sets `rfe_status` to `RESPONDED` and stamps `rfe_response_date` to the current clock. This `SUBMITTED` ⇄ `RFE_ISSUED` loop may repeat. Separately, an unanswered RFE is enforced by the clock: when the logical clock advances past `rfe_due_date` while the petition is still `RFE_ISSUED`, the system denies it, moving it from `RFE_ISSUED` to `DENIED`.

Adjudication is the `USCISOfficer`'s: from `SUBMITTED`, the officer approves the petition to `APPROVED` or denies it to `DENIED`, each defined only from `SUBMITTED`. Approval enforces a beneficiary-level non-overlap rule: no other `APPROVED` petition for the *same* `beneficiary_id` and `worksite_area` may have an employment interval overlapping `[employment_start, employment_end)`. That interval is **half-open**, so two petitions that merely abut — one ending exactly when the next begins — do not conflict, whereas any genuine overlap is rejected with `ERR_EMPLOYMENT_OVERLAP` (409). A successful approval recomputes the beneficiary's `current_status_code` and `status_valid_until`. Denial from `SUBMITTED` likewise recomputes those beneficiary fields (so the beneficiary loses `H1B_ACTIVE` if this petition was its source). A petition denied while `RFE_ISSUED` — whether by the RFE deadline lapsing or by the underlying application being withdrawn — also recomputes those fields; a petition that is denied while still `DRAFT` as part of an application-withdrawal cascade has no such effect. `APPROVED` and `DENIED` are terminal. Petitions can be listed and filtered by `employer_id`, `lca_id`, `beneficiary_id`, `registration_id`, or `status`, and a fetched petition exposes its `filing_fee_cents`, `rfe_status`, and `rfe_due_date`.

### 3.7. I-140 Immigrant Petitions and Priority Dates

The green-card stage is the `I140Petition`. An `EmployerAgent` creates one in `DRAFT`, supplying the `employer_id`, the `beneficiary_id`, the `category` (one of `EB1`, `EB2`, or `EB3`), and an optional `perm_case_id`. The `perm_case_id` is null for a self-petition that carries no underlying labor certification.

Submission moves the petition from `DRAFT` to `SUBMITTED`, performed by an `EmployerAgent` and defined only from `DRAFT`. When `perm_case_id` is not null, the referenced PERM case must be `CERTIFIED`, otherwise the submission is rejected with `ERR_PERM_NOT_CERTIFIED`. On submission the system stamps `filed_date` to the current clock and sets the petition's `priority_date` according to its lineage. A **PERM-based** petition — one that has a non-null `perm_case_id` and whose `category` is `EB2` or `EB3` — inherits the underlying PERM case's `priority_date`, which is the earlier labor-certification filing date and therefore a better queue position. A **self-petition** — one whose `category` is `EB1`, or one with no `perm_case_id` — instead uses this petition's own `filed_date`. (For otherwise identical filing timestamps the two rules diverge whenever the PERM was filed before the I-140.)

A `USCISOfficer` adjudicates from `SUBMITTED`, approving to `APPROVED` or denying to `DENIED`, each defined only from `SUBMITTED`. Approval recomputes the beneficiary's aggregate `priority_date` (the earliest across the beneficiary's approved green-card petitions). Denial from `SUBMITTED` likewise recomputes that beneficiary field. As noted in §3.3, a green-card petition can also be denied as a cascade when its underlying PERM case is denied: a petition denied from `DRAFT` by that cascade needs no beneficiary recompute, while one caught while `SUBMITTED` triggers the same `priority_date` recompute. `APPROVED` and `DENIED` are terminal. These petitions can be listed and filtered by `employer_id`, `perm_case_id`, `beneficiary_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all `/transitions` actions, edits, the PAF audit, running the lottery, and setting the clock — return `200 OK`. Each `/transitions` request names its intended target state in a `to_status` field, and the server resolves it against the state machine described in Section 3 (rejecting an undefined transition with `ERR_INVALID_STATE`). Every non-`GET` action requires the acting role listed below; every `GET` is available to all four roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/employers` | Register a sponsoring employer | EmployerAgent |
| GET | `/employers/{id}` | Fetch an employer | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/prevailing-wage-determinations` | Submit a prevailing-wage determination request (PENDING) | EmployerAgent |
| GET | `/prevailing-wage-determinations/{id}` | Fetch a determination | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/prevailing-wage-determinations` | List determinations (filter by employer_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/prevailing-wage-determinations/{id}/transitions` | Issue a determination (OCC + supersede) | DOLAnalyst |
| POST | `/perm-cases` | Create a PERM labor-certification case (DRAFT) | EmployerAgent |
| GET | `/perm-cases/{id}` | Fetch a PERM case | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/perm-cases` | List PERM cases (filter by employer_id, pwd_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/perm-cases/{id}/transitions` | Drive recruitment / quiet period / filing / audit / certify / deny | EmployerAgent, DOLAnalyst |
| POST | `/recruitment-steps` | Record a recruitment activity (ACTIVE) | EmployerAgent |
| GET | `/recruitment-steps/{id}` | Fetch a recruitment step | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/recruitment-steps` | List recruitment steps (filter by perm_case_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/lcas` | Create a Labor Condition Application (DRAFT) | EmployerAgent |
| GET | `/lcas/{id}` | Fetch an application | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/lcas` | List applications (filter by employer_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| PATCH | `/lcas/{id}` | Edit a DRAFT application; recompute provisional wages | EmployerAgent |
| POST | `/lcas/{id}/transitions` | Certify (DOL) or withdraw (Employer) an application | EmployerAgent, DOLAnalyst |
| POST | `/lcas/{id}/audit-paf` | Audit the public-access file | ComplianceAuditor |
| POST | `/beneficiaries` | Register a beneficiary | EmployerAgent |
| GET | `/beneficiaries/{id}` | Fetch a beneficiary | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/cap-programs` | Create the H-1B cap program for a fiscal year | USCISOfficer |
| GET | `/cap-programs/{id}` | Fetch a cap program | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/cap-programs/{id}/run-lottery` | Run the deterministic cap lottery | USCISOfficer |
| POST | `/h1b-registrations` | Register a beneficiary for the lottery (SUBMITTED) | EmployerAgent |
| GET | `/h1b-registrations/{id}` | Fetch a registration | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/h1b-registrations` | List registrations (filter by employer_id, beneficiary_id, fiscal_year, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/h1b-registrations/{id}/transitions` | Withdraw a selected registration | EmployerAgent |
| POST | `/h1b-petitions` | Create an H-1B petition (DRAFT); compute filing fee | EmployerAgent |
| GET | `/h1b-petitions/{id}` | Fetch a petition | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/h1b-petitions` | List petitions (filter by employer_id, lca_id, beneficiary_id, registration_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/h1b-petitions/{id}/transitions` | Submit / RFE / respond / approve / deny | EmployerAgent, USCISOfficer |
| POST | `/i140-petitions` | Create an I-140 immigrant petition (DRAFT) | EmployerAgent |
| GET | `/i140-petitions/{id}` | Fetch an I-140 petition | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| GET | `/i140-petitions` | List I-140 petitions (filter by employer_id, perm_case_id, beneficiary_id, status) | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |
| POST | `/i140-petitions/{id}/transitions` | Submit / approve / deny | EmployerAgent, USCISOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock; evaluate due expiries | EmployerAgent, DOLAnalyst, USCISOfficer, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_DUPLICATE_REGISTRATION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PWD_NOT_ISSUED` | 409 |
| `ERR_LCA_NOT_CERTIFIED` | 409 |
| `ERR_REGISTRATION_NOT_SELECTED` | 409 |
| `ERR_PERM_NOT_CERTIFIED` | 409 |
| `ERR_WORKSITE_NOT_COVERED` | 409 |
| `ERR_REGISTRATION_HAS_PETITION` | 409 |
| `ERR_RECRUITMENT_TOO_SHORT` | 422 |
| `ERR_QUIET_PERIOD_NOT_ELAPSED` | 422 |
| `ERR_PERM_VALIDITY_EXPIRED` | 422 |
| `ERR_RFE_EXPIRED` | 422 |
| `ERR_RECRUITMENT_INCOMPLETE` | 422 |
| `ERR_RECRUITMENT_STEP_OVERLAP` | 409 |
| `ERR_EMPLOYMENT_OVERLAP` | 409 |
| `ERR_WAGE_BELOW_PREVAILING` | 422 |

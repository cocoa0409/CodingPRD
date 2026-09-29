# Job Classification & Exemption Audit API — Product Requirements Document

## 1. Introduction

Wage-and-hour misclassification is the most expensive quiet liability an employer carries. A job title that reads like management, a salary that looked comfortably above the threshold when it was set five years ago, a duty inventory that nobody has revisited since the role was written — any one of these can turn a routine payroll practice into a multi-year back-wage claim. Human resources compliance teams therefore run periodic classification audits: they inventory every job description, they test the description against what the incumbent and the manager actually say happens, they re-run the exemption tests against both the federal baseline and the jurisdiction the employee actually works in, and then they decide what to fix, how fast, and how much to pay.

This document specifies the API that carries that engagement end to end. The service manages an audit engagement's job-family tree and job-description inventory; it captures manager and incumbent interviews and reconciles their accounts into a validated picture of actual duties; it evaluates the executive, administrative, professional, computer and outside-sales exemption tests under two jurisdictional legs simultaneously; it scores misclassification risk by job family and ranks families for remediation; it converts pay structures, drives the overtime-eligibility conversation with affected employees, estimates back-wage exposure under two competing valuation methods, and records voluntary-correction decisions inside a delegated monetary authority. It also reviews engaged vendors for independent-contractor status under whichever test the engagement's jurisdiction applies, and it re-opens completed work when a salary, duty, reporting or jurisdiction change invalidates an earlier finding.

Two design commitments shape almost every rule below. First, **every finding is reversible**: a determination can be rescinded, a pay conversion can be reverted, and an estimate can be superseded — and in each case the derived counters and rollups the original action moved must be restored exactly, never approximated. Second, **no single person both authors and blesses a finding**: the analyst who writes an exemption analysis may not review it, and the operator who proposes a correction may not decide it.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold across the entire API. Where a rule below is enforced against a specific workflow, §3 tells the business story; this section fixes the mechanics.

### 2.1. User and Role-Based Access Control

Every request to the API — reads included — must carry two headers. `X-User-ID` identifies the acting operator and `X-User-Role` declares the capacity in which that operator is acting. If either header is absent or present but empty, the request fails immediately with `ERR_MISSING_USER_CONTEXT` (HTTP 400). If `X-User-Role` is not one of the seven declared role names, or is a valid role that is not authorized for the endpoint being called, the request fails with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

Seven roles exist, spelled exactly as follows:

- `ProgramAdmin` — owns the engagement skeleton: jurisdiction rules, the engagement itself, its stage, the job-family tree and the job-description inventory. `ProgramAdmin` also owns the logical-clock capability described in §2.5.
- `ComplianceAnalyst` — performs fieldwork: documents duties, books and runs manager and incumbent interviews, authors exemption analyses, screens contractors and logs job changes.
- `ClassificationReviewer` — the independent reviewer: returns or determines analyses authored by someone else, voids unreliable interviews, and finalizes contractor reviews.
- `CompensationManager` — designs and executes the pay-structure conversion and quantifies back-wage exposure.
- `EmployeeRelationsLead` — runs the overtime-eligibility communication and the employee-relations plan for each reclassification case.
- `LegalCounsel` — decides voluntary-correction posture within a delegated monetary authority, and may also propose a correction.
- `Auditor` — a read-only external reviewer of the whole engagement.

All seven roles are authorized for every read endpoint. Write authority is otherwise partitioned: `ProgramAdmin` alone registers jurisdiction rules, opens engagements, drives engagement stage, and creates job families and positions; `ComplianceAnalyst` alone records duty statements, books interviews, completes and attests them, opens and submits exemption analyses, opens contractor reviews and records job-change triggers; `ClassificationReviewer` alone returns and determines analyses, voids interviews and finalizes contractor reviews; `CompensationManager` alone opens reclassification cases, performs and reverts pay conversion and creates back-wage estimates; `EmployeeRelationsLead` alone drives the communication dimension of a case; and `LegalCounsel` alone decides a proposed correction. Proposing a voluntary correction is shared between `CompensationManager` and `LegalCounsel`.

**Identity semantics.** All seven roles are operational identities rather than persisted entities. When `X-User-Role` is `ProgramAdmin`, `ComplianceAnalyst`, `ClassificationReviewer`, `CompensationManager`, `EmployeeRelationsLead`, `LegalCounsel` or `Auditor`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server does record it where the domain demands an audit trail — as `analyst_user_id` and `reviewer_user_id` on an exemption analysis, and as `proposed_by_user_id` and `approver_user_id` on a voluntary correction — and it compares those recorded opaque values against the acting `X-User-ID` to enforce segregation of duties (§2.10). No ownership check anywhere in this API compares `X-User-ID` to an entity's `id`.

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

Every list endpoint accepts two optional query parameters. `limit` caps the number of rows returned; it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` is the number of rows to skip before the window begins; it defaults to 0.

Every list endpoint returns its rows ordered by `created_at` ascending. No list endpoint anywhere in this API orders by `id`, and no calculation, tie-break or selector in the domain reads `id` either; wherever a fallback ordering is needed it is `created_at` ascending.

List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` is the number of rows matching the collection before the pagination window is applied and `has_more` states whether any rows remain beyond it.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource the API mints carries an `id` that is a server-generated UUID with no type prefix, and a `created_at` that is an ISO 8601 UTC timestamp with three fractional digits (for example `2026-08-01T00:00:00.000Z`).

Most resources additionally carry `updated_at` — an ISO 8601 UTC timestamp, same format, refreshed on every mutation — and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that row. Recomputing a derived field counts as a mutation: when an interview attestation rewrites a position's validated duty percentage, that position's `updated_at` is refreshed and its `version` is incremented, even though no client sent a request naming the position.

Two entities are exceptions and carry only `id` and `created_at`, with **both** `updated_at` and `version` absent from their representations:

- A **jurisdiction rule** (`StateRule`) is configuration. It is immutable once created and keyed by `state_code`.
- A **job change trigger** (`JobChangeTrigger`) is an append-only event log row. It is never mutated after creation.

### 2.5. The Logical Clock

Every date and datetime comparison in this domain — notice lead time, interviewer calendar overlap, reclassification-window separation, and the timestamps the server stamps onto resources — reads a single server-side logical clock rather than wall-clock time. Before any operator sets it, the logical clock reads `2026-08-01T00:00:00Z`. A `ProgramAdmin` may move the clock by supplying a `current_utc` instant; every subsequent comparison reads the new value. Moving the clock has no other effect: it does not recompute a single derived field and does not re-evaluate any already-recorded finding.

Where a rule is expressed in **calendar days** — the notice lead time, the reclassification-window buffer — the comparison is between calendar dates, computed as the number of whole days from the logical clock's date to the target date.

### 2.6. Jurisdiction Resolution and the Federal Baseline

Classification rules vary by jurisdiction, and the API models that variation as a registry of jurisdiction rules keyed by a two-letter uppercase `state_code`. Each registered jurisdiction declares its weekly salary floor in whole cents as `min_weekly_salary_cents`, its highly-compensated-employee annual floor as `hce_annual_cents` (default 0), which duties floor it applies via `duties_test_variant` (one of `FEDERAL`, `QUANTITATIVE_50PCT` or `STRICT_ENUM`), three recognition flags — `computer_exemption_recognized`, `outside_sales_recognized` and `hce_shortcut_recognized`, each defaulting to `true` — the independent-contractor test it applies via `ic_test` (one of `ABC`, `ECONOMIC_REALITY` or `COMMON_LAW`), a `liquidated_damages_multiplier` between 0.0 and 3.0 inclusive that defaults to 1.0, a `reclass_notice_days` minimum notice lead time that defaults to 14 and may not be negative, and an optional `back_wage_lookback_weeks_override` expressed in weeks that defaults to null and, when supplied, must be at least 1. Both `min_weekly_salary_cents` and `hce_annual_cents` must be zero or greater.

**Resolution rule.** A position's jurisdiction is its `work_state_code`; a contractor review's jurisdiction is its `engagement_state_code`. In both cases the code is resolved against the registry by exact match on `state_code`. Resolution failure is not an error: when no jurisdiction rule is registered for the code, the **federal-only baseline** applies. Under the federal-only baseline a position is evaluated as though the state weekly floor equalled the federal floor, the state highly-compensated annual floor were 0, the duties variant were `FEDERAL`, all three recognition flags were `true`, the liquidated-damages multiplier were **0.0** (not the 1.0 default that a registered jurisdiction would carry), and there were no statutory lookback override. A contractor review with no registered jurisdiction is tested under `ECONOMIC_REALITY`.

The federal constants that anchor every evaluation are fixed: the federal weekly salary floor is 84,400 cents ($844.00 per week); the federal highly-compensated-employee annual floor is 13,200,000 cents ($132,000 per year); the federal primary-duty floor is 50.0 percent; the abbreviated highly-compensated duties floor is 20.0 percent; the computer-employee hourly floor is 2,763 cents ($27.63 per hour); a manager must corroborate supervision of at least 2 employees to satisfy the executive gate; and annual-to-hourly conversion uses a 2,080-hour divisor.

### 2.7. Rejection Precedence

When a request violates more than one rule, exactly one error is returned, and which one is not a matter of implementation convenience. The checks below are evaluated **strictly in this order**; the first rule that is violated determines the response, and no later rule runs.

1. **User context.** `X-User-Role` and `X-User-ID` are both present and non-empty, else `ERR_MISSING_USER_CONTEXT` (400).
2. **Role authorization.** `X-User-Role` is one of the seven declared roles and is authorized for the target endpoint, else `ERR_ROLE_NOT_PERMITTED` (403).
3. **Path existence.** Every resource named by a path parameter exists, validated left to right. The rejection carries the not-found code of the first path segment that fails to resolve: `ERR_AUDIT_PROJECT_NOT_FOUND`, `ERR_JOB_FAMILY_NOT_FOUND`, `ERR_POSITION_NOT_FOUND`, `ERR_INTERVIEW_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, `ERR_RECLASS_CASE_NOT_FOUND`, `ERR_CORRECTION_NOT_FOUND` or `ERR_CONTRACTOR_REVIEW_NOT_FOUND` (all 404).
4. **Request shape.** On every creating or acting endpoint, the body conforms to the endpoint's input schema: required fields present, types correct, enum values inside the declared set, numeric values inside the declared range, `scheduled_end_at` strictly later than `scheduled_start_at`, `effective_end_date` on or after `effective_date`, `effective_date` not in the past relative to the logical clock, and the field that the supplied `trigger_type` requires actually present. Any failure yields `ERR_INVALID_REQUEST` (400).
5. **Foreign-key existence.** Every entity referenced by a foreign-key field in the body exists, else the matching 404 — `ERR_AUDIT_PROJECT_NOT_FOUND` for `audit_project_id`, `ERR_JOB_FAMILY_NOT_FOUND` for `job_family_id` or `parent_family_id`, `ERR_POSITION_NOT_FOUND` for `position_id`, `ERR_RECLASS_CASE_NOT_FOUND` for `reclassification_case_id`. This applies to the creation of job families, positions, duty statements, interviews, exemption analyses, reclassification cases, back-wage estimates, voluntary corrections, contractor reviews and job-change triggers.
6. **Engagement posture.** The engagement's `remediation_posture` permits the requested write, else `ERR_PROJECT_POSTURE_FROZEN` or `ERR_POSTURE_RESTRICTED_FAMILY` (both 409). This applies to exactly three creates: job families, positions and contractor reviews. See §2.12.
7. **Engagement stage.** The engagement is in the stage the operation requires, and, on the stage endpoint, the requested `target_status` is a declared transition from the current status whose preconditions hold. Failures yield `ERR_PROJECT_STAGE_INVALID`, `ERR_PROJECT_STAGE_PRECONDITION_UNMET` or `ERR_PROJECT_NOT_READY_TO_CLOSE` (all 409). This applies to the stage endpoint, to booking an interview, and to completing an interview.
8. **Declared transition.** The target entity's current state has a declared transition for this trigger — including the outcome-matching guard on determination and on contractor finalization, and the requirement that an interview have been completed before it can be attested. Failures yield `ERR_INVALID_STATE_TRANSITION`, `ERR_INTERVIEW_NOT_STARTED`, `ERR_RECLASS_ALREADY_CONVERTED` or `ERR_CASE_ALREADY_COMPLETED` (all 409). This applies to interview completion, attestation and voiding; analysis submission, return and determination; case pay-conversion, revert-pay-conversion and communication; correction decision; and contractor finalization.
9. **Stale parent version.** The supplied `expected_position_version` or `expected_reclassification_case_version` equals the parent's current `version`, else `ERR_STALE_POSITION_VERSION` or `ERR_STALE_CASE_VERSION` (both 412). See §2.9.
10. **Segregation of duties.** The acting `X-User-ID` differs from `analyst_user_id` when returning or determining an analysis, and from `proposed_by_user_id` when deciding a correction, else `ERR_SEGREGATION_OF_DUTIES` (403).
11. **Duties corroborated.** The position's `duties_validation_status` is not `PENDING` when an analysis is submitted, else `ERR_DUTIES_NOT_CORROBORATED` (409).
12. **Cross-entity prerequisites for pay conversion.** The position is `MISCLASSIFIED`, and an `APPROVED` voluntary correction exists when the case's exposure reaches the mandatory-correction threshold, else `ERR_POSITION_NOT_MISCLASSIFIED` or `ERR_VOLUNTARY_CORRECTION_REQUIRED` (both 409).
13. **Uniqueness and allocation.** `ERR_DUPLICATE_CODE`, `ERR_DUPLICATE_INTERVIEW_RESPONDENT`, `ERR_DUTY_TIME_OVERALLOCATED` or `ERR_IC_TEST_INPUTS_MISSING` (all 409), on jurisdiction-rule, job-family, position, duty-statement, interview and contractor-review creation. The specific constraints are: a jurisdiction `state_code` is globally unique; a `code` is unique among the job families of one `audit_project_id`; a `job_code` is unique among the positions of one `job_family_id`; at most one non-`VOIDED` interview exists per position and `respondent_type`; the sum of `claimed_time_pct` across a position's duty statements may not exceed 100; and the independent-contractor inputs the applicable test requires are all supplied.
14. **Interviewer availability.** `ERR_INTERVIEWER_DOUBLE_BOOKED` (409) on interview booking.
15. **Reclassification-window separation.** `ERR_RECLASS_WINDOW_CONFLICT` (409) on case creation.
16. **Reclassification wave capacity.** `ERR_RECLASS_WAVE_CAPACITY_EXCEEDED` (409) on case creation.
17. **Notice lead time.** `ERR_NOTICE_WINDOW_TOO_SHORT` (409) on the communication endpoint.
18. **Approval authority.** `ERR_APPROVAL_AUTHORITY_EXCEEDED` (409) on a correction decision.
19. **Correction funding.** `ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE` (409) on a correction decision.

Two consequences of this ordering are worth calling out because they are easy to get backwards. Because the declared-transition check sits at rank 8 and segregation of duties at rank 10, an analyst who tries to return their own analysis while it is still in `DRAFT` receives `ERR_INVALID_STATE_TRANSITION`, not `ERR_SEGREGATION_OF_DUTIES` — the same actor gets the segregation error only once the analysis is genuinely in a returnable state. And because the duties-corroboration check sits at rank 11, submitting an analysis that is not in `DRAFT` or `RETURNED` yields `ERR_INVALID_STATE_TRANSITION` even when the position's duties are also uncorroborated.

### 2.8. Derived-Field Recomputation and Cascade Integrity

A large fraction of this API's surface is derived. Positions derive their validated duty picture from interviews and duty statements; job families derive a risk score from their positions; the engagement derives a posture and four monetary or headcount rollups from everything beneath it. None of these values is client-writable, and none of them is computed lazily at read time — every write that can move a derived value recomputes it immediately, in the same request, before the response is produced.

Recomputation is **transitive and ordered**. A change to a position's validated duty percentage, validated weekly hours, annual salary, work state or classification status recomputes that position's derived fields first, then its job family's risk figures, then the engagement's posture and rollups. Each row touched along the way is a real mutation of that row: its `updated_at` is refreshed and its `version` is incremented by one. A single interview attestation therefore increments the `version` of the interview, the position, the job family and the engagement.

Reversal is symmetric with application. Rescinding a determination, reverting a pay conversion and superseding an estimate each restore precisely the derived values their forward counterpart moved — the family's misclassified count, the engagement's misclassified headcount, the engagement's converted payroll delta. Conserved quantities are maintained by exact addition and subtraction of the same figure that was originally applied, never by re-deriving an approximation.

### 2.9. Stale-Read Protection on Analysis and Estimate Creation

Two creations in this API are protected by optimistic concurrency control, because in both cases the domain deliberately permits a second row to stand alongside the first, so nothing in the state machine would otherwise catch a client acting on a view of the world that has already moved.

**Opening an exemption analysis** requires `expected_position_version` in the request body. It is not optional. The value must equal the target position's current `version`. If the position's `version` has advanced since the client last read it — because a duty statement was added, an interview was attested, or an earlier analysis was opened against the same position — the create is rejected with `ERR_STALE_POSITION_VERSION` and HTTP 412. The product permits a newer analysis to coexist with prior rounds, so the stale version is the only signal that the analyst's view of the duties, salary and jurisdiction inputs is no longer the view the analysis would actually be evaluated against.

**Creating a back-wage estimate** requires `expected_reclassification_case_version` in the request body. It is likewise not optional and must equal the target case's current `version`. A new estimate legitimately supersedes the prior `ACTIVE` one, so a second sequential create would otherwise simply succeed; a mismatch is rejected with `ERR_STALE_CASE_VERSION` and HTTP 412, signalling that the case's exposure inputs moved after the client read them.

No other endpoint in this API takes a version field, and no other endpoint performs a version check. In particular the stage endpoint, all four analysis lifecycle actions, both pay-conversion actions, the communication endpoint, the correction decision, contractor finalization and job-change-trigger creation are all unversioned.

### 2.10. Segregation of Duties

Two operations enforce a four-eyes rule by comparing the acting `X-User-ID` against an opaque identifier recorded earlier on the resource.

An exemption analysis records `analyst_user_id` from the `X-User-ID` of the `ComplianceAnalyst` who created it. A `ClassificationReviewer` whose `X-User-ID` equals that recorded `analyst_user_id` may neither return the analysis nor determine it; either attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). The reviewer who successfully returns or determines an analysis is recorded on it as `reviewer_user_id`.

A voluntary correction records `proposed_by_user_id` from the `X-User-ID` of whoever proposed it. A `LegalCounsel` whose `X-User-ID` equals that value may not decide it — approval and rejection alike are rejected with `ERR_SEGREGATION_OF_DUTIES`. The deciding operator is recorded as `approver_user_id`.

### 2.11. Numbers, Rounding and Pinned Evaluation Order

All money in this system is integer cents. All percentages are decimal numbers. Two rounding conventions are used and must be applied exactly:

- **Round half up to a whole number**: the nearest integer, with a value ending in exactly one half going away from zero.
- **Round half up to one decimal place**: the nearest tenth, with a value ending in exactly five hundredths going away from zero. This convention is used only for `primary_duty_pct`.
- **Floor**: the largest integer that is not greater than the value. This is used for the weekly-salary and hourly-rate conversions, which are truncations, not roundings.

Boundary comparisons are inclusive at the floor unless stated otherwise. A weekly salary exactly equal to the applicable salary floor passes the salary leg. A one-decimal duty percentage of exactly 50.0 passes a 50.0 floor while 49.9 fails it. A risk score of exactly 75 is `CRITICAL`. An independent-contractor common-law score of exactly 20 is `CONTRACTOR` while 19 is `INDETERMINATE`, and exactly 11 is `EMPLOYEE` while 12 is `INDETERMINATE`. The single exclusive boundary in the domain is the interview corroboration spread, where a spread of exactly 15.0 percentage points is still corroborated and 15.1 is conflicted.

Two calculations have a **pinned evaluation order** that materially changes the answer, and neither may be reorganized:

- Back-wage exposure rounds the per-workweek overtime figure to whole cents **before** multiplying by the lookback weeks and the incumbent count. Computing an unrounded weekly figure, multiplying it out, and rounding once at the end is forbidden and yields a different, incorrect total.
- Pay-structure conversion solves the hourly rate from the unrounded annual salary, rounds that rate to whole cents, and only then recomputes the projected annual cost **from the rounded rate**. Because the projected cost consumes the rounded rate, the cost delta is generally non-zero even for the cost-neutral method. Iterating to drive the delta to zero is forbidden.

### 2.12. Engagement Posture as a Write Gate

Every engagement exposes a computed `remediation_posture` with three values — `OPEN`, `RESTRICTED` and `FROZEN` — that acts as a safety gate over inventory growth. It is recomputed on every transition that changes a position's classification status, a job family's risk tier, or a contractor review's status, and it is evaluated top-down with the strictest test short-circuiting first:

1. If **any** job family of the engagement has `risk_tier` equal to `CRITICAL` **and** an `open_misclassified_count` of at least 1, the posture is `FROZEN`.
2. Otherwise, if **any** position of the engagement has `classification_status` equal to `MISCLASSIFIED`, **or** any contractor review of the engagement has reached `FINALIZED_EMPLOYEE`, the posture is `RESTRICTED`.
3. Otherwise the posture is `OPEN`.

A `FROZEN` posture blocks all three inventory creates — job families, positions and contractor reviews — with `ERR_PROJECT_POSTURE_FROZEN`. A `RESTRICTED` posture is narrower: it blocks only the creation of a position into a job family whose `risk_tier` is `HIGH` or `CRITICAL`, with `ERR_POSTURE_RESTRICTED_FAMILY`. Under `RESTRICTED` a new job family may still be created, a contractor review may still be opened, and a position may still be added to a `LOW` or `MEDIUM` family.

## 3. Business Logic & Workflows

### 3.1. Opening the Engagement and Inventorying the Job-Family Tree

A classification audit begins when a `ProgramAdmin` opens an engagement with a `name` and the `fiscal_year` under audit, which must be an integer between 2000 and 2100 inclusive. The engagement also carries a `lookback_policy` that fixes how far back exposure is measured; it defaults to `STANDARD_2Y` and may instead be set to `WILLFUL_3Y` when the facts suggest a willful violation. An engagement moves through four statuses in its lifetime — `PLANNING`, `FIELDWORK`, `REMEDIATION` and `CLOSED`, the last of which is terminal — and the rules governing movement between them are set out in §3.9. A freshly opened engagement sits in `PLANNING` status with `remediation_posture` initialized to `OPEN` and every rollup counter initialized to 0 — `open_misclassified_headcount`, `total_back_wage_exposure_cents`, `converted_annual_payroll_delta_cents` and `committed_correction_cents`.

Inside the engagement, work is organized as a tree of **job families**. Creating one requires the `audit_project_id` of the engagement it belongs to, a display `name`, and a `code` that must be unique among that engagement's families; a duplicate `code` is rejected with `ERR_DUPLICATE_CODE`. A family may optionally name a `parent_family_id`, which points at another job family and defaults to null. The tree is genuinely self-referential, but scoring is emphatically **not** inherited: a family never absorbs the positions, the headcount or the score of a family whose `parent_family_id` points at it, and a child family is always scored independently of its parent.

A new family starts with `risk_score` 0, `risk_tier` `LOW`, `risk_variant` `EVIDENCE_WEIGHTED`, `family_headcount` 0, `open_misclassified_count` 0 and `remediation_priority_rank` null. The `remediation_priority_rank` stays null until the engagement enters its remediation stage, which is described in §3.9.

### 3.2. Job Descriptions and Duty Documentation

A **position** is one published job description together with the population that holds it. A `ProgramAdmin` adds a position to the inventory under a `job_family_id`, with a `title`, a `job_code` unique within that family (a collision is `ERR_DUPLICATE_CODE`), the `current_fls_status` as it is actually administered on payroll (`EXEMPT` or `NONEXEMPT`), the `claimed_exemption_test` the employer currently relies on (`EXECUTIVE`, `ADMINISTRATIVE`, `PROFESSIONAL`, `COMPUTER`, `OUTSIDE_SALES` or `NONE`), the `annual_salary_cents` of base compensation which must be strictly greater than zero, the `salary_basis` (`SALARY`, `HOURLY`, `FEE` or `COMMISSION`), the two-letter uppercase `work_state_code` that resolves the jurisdiction, an `incumbent_count` of at least 1, and the employer-reported `avg_weekly_hours` between 0 and 168 inclusive. Two optional booleans complete the picture and both default to `false`: `requires_advanced_degree`, meaning the job requires a prolonged course of specialized intellectual instruction, and `works_primarily_offsite`, meaning the incumbent customarily works away from the employer's place of business.

Creating a position immediately derives `weekly_salary_cents` as the annual salary divided by 52 and truncated to a whole cent, sets `self_reported_exempt_pct` (which is 0 while the position has no duty statements), sets `primary_duty_pct` and `validated_weekly_hours`, puts `duties_validation_status` at `PENDING`, and sets `overtime_eligible`, which is true exactly when `current_fls_status` is `NONEXEMPT`. It also recomputes the owning family's risk score, tier, variant and headcount, and the engagement's posture, incrementing the `version` of both the family and the engagement. A position enters the inventory with `classification_status` `UNREVIEWED`.

A `ComplianceAnalyst` then documents what the job description claims the incumbent does, one **duty statement** at a time. Each duty line names its `position_id`, a short `duty_code`, a narrative `description`, the employer-claimed `claimed_time_pct` share of work time between 0 and 100 inclusive, and `is_exempt_duty`, which says whether the employer classifies that duty as exempt work. Each line also carries a `discretion_level` of `NONE`, `ROUTINE` or `INDEPENDENT_JUDGMENT`, defaulting to `NONE`; that field is what the administrative exemption gate reads. The claimed shares are an allocation of one person's time, so their sum across a position may never exceed 100 — a duty line that would push the total above 100 is rejected with `ERR_DUTY_TIME_OVERALLOCATED`.

Adding a duty line recomputes the position's `self_reported_exempt_pct`, which is the sum of `claimed_time_pct` over that position's duty statements whose `is_exempt_duty` is true. While `duties_validation_status` is still `PENDING`, that self-reported figure is also what `primary_duty_pct` reflects, rounded half up to one decimal place. Adding a duty line also recomputes the family's risk score and tier, and increments the `version` of both the position and the family.

### 3.3. Duties Validation Through Manager and Incumbent Interviews

A job description is a claim, not evidence. The audit corroborates it by interviewing two people per position: the manager and the incumbent. A `ComplianceAnalyst` books an interview against a `position_id` with a `respondent_type` of either `MANAGER` or `INCUMBENT`, an opaque `respondent_ref` naming the interviewee, the `interviewer_user_id` whose calendar is the contended resource, and a booking window of `scheduled_start_at` inclusive to `scheduled_end_at` exclusive, where the end must be strictly later than the start. Booking is only permitted while the engagement is in `FIELDWORK`; attempting it in any other stage is `ERR_PROJECT_STAGE_INVALID`. At most one non-`VOIDED` interview may exist for a given position and `respondent_type` at a time, so a second live manager interview on the same position is `ERR_DUPLICATE_INTERVIEW_RESPONDENT`.

The interviewer's calendar is a hard resource. The requested half-open window from `scheduled_start_at` up to but not including `scheduled_end_at` must not intersect the window of any other interview held by the same `interviewer_user_id` whose `status` is `SCHEDULED`, `COMPLETED` or `ATTESTED` — and that check spans **all** engagements, not just the current one. There is zero buffer: two windows that merely share an endpoint, where one ends exactly when the next begins, are back-to-back and permitted. A genuine intersection is `ERR_INTERVIEWER_DOUBLE_BOOKED`. Voided interviews release their window, so a voided booking frees the slot for a later one.

An interview is created in `SCHEDULED` status. Completing it — which is also gated on the engagement being in `FIELDWORK`, again `ERR_PROJECT_STAGE_INVALID` — advances the interview `SCHEDULED → COMPLETED` and records the respondent's own account: `reported_exempt_duty_pct` between 0 and 100 inclusive, `reported_weekly_hours` between 0 and 168 inclusive, `supervises_headcount` of zero or more, and the boolean `has_hire_fire_influence`. The logical clock at that moment is stamped onto `completed_at`, and the interview's `version` is incremented. Attesting the interview advances it `COMPLETED → ATTESTED` and stamps `attested_at` from the logical clock. Attesting an interview that has never been completed — one whose `completed_at` is still null — is `ERR_INTERVIEW_NOT_STARTED`.

**Attestation is where corroboration happens.** Only interviews whose `status` is `ATTESTED` feed the calculation; `SCHEDULED`, `COMPLETED` and `VOIDED` accounts are all excluded. The system looks for exactly two of them on the position: the attested `MANAGER` account and the attested `INCUMBENT` account.

When either of those two is missing, the position's `duties_validation_status` is `PENDING`. In that state `primary_duty_pct` is the position's `self_reported_exempt_pct` rounded half up to one decimal place, `validated_weekly_hours` falls back to the employer-reported `avg_weekly_hours`, `corroborated_supervises_headcount` is 0, and `corroborated_hire_fire_influence` is `false`. (The self-reported figure itself is the `self_reported_exempt_pct_override` when that field is not null, and otherwise the sum of exempt-duty claimed shares described in §3.2.)

When both attested accounts exist, the audit compares them. The **spread** is the absolute difference between the manager's `reported_exempt_duty_pct` and the incumbent's. If the spread is greater than 15.0 percentage points, the two accounts do not agree: `duties_validation_status` becomes `CONFLICTED` and the audit takes the conservative view, setting `primary_duty_pct` to the **lower** of the two reported percentages, rounded half up to one decimal place. If the spread is 15.0 points or less, `duties_validation_status` becomes `CORROBORATED` and `primary_duty_pct` becomes a weighted blend of the two accounts, giving the manager a 40 percent weight and the incumbent a 60 percent weight: multiply the manager's reported percentage by 40 and the incumbent's by 60, add the two products, divide the sum by 100, and round the result half up to one decimal place. The incumbent carries the heavier weight because the incumbent is the one doing the work.

In both the conflicted and the corroborated case the remaining three validated fields are derived identically from the two attested accounts: `validated_weekly_hours` is the **greater** of the two `reported_weekly_hours` values, `corroborated_supervises_headcount` is the **lesser** of the two `supervises_headcount` values, and `corroborated_hire_fire_influence` is true only when **both** respondents reported `has_hire_fire_influence` as true.

Attestation then propagates: it recomputes the family's `risk_score`, `risk_tier`, `risk_variant` and `family_headcount`, and the engagement's `remediation_posture`, incrementing the `version` of the interview, the position, the family and the engagement.

A `ClassificationReviewer` may **void** an interview whose account is unreliable, supplying a `void_reason`. Voiding is permitted from `SCHEDULED`, from `COMPLETED` and from `ATTESTED` alike, and `VOIDED` is terminal. All three voids record the `void_reason` and increment the interview's `version`. A `SCHEDULED → VOIDED` void additionally frees the interviewer's calendar window for later bookings and touches nothing else. A `COMPLETED → VOIDED` void additionally recomputes the position's `duties_validation_status` and its dependent derived fields, incrementing the position's `version`. An `ATTESTED → VOIDED` void additionally recomputes the position's `duties_validation_status` — which returns to `PENDING` whenever fewer than two attested interviews remain — along with `primary_duty_pct`, `validated_weekly_hours`, `corroborated_supervises_headcount` and `corroborated_hire_fire_influence`, then recomputes the family's `risk_score`, `risk_tier` and `risk_variant`, incrementing the `version` of the interview, the position and the family.

### 3.4. Exemption Analysis Under the Five White-Collar Tests

With duties validated, a `ComplianceAnalyst` opens an **exemption analysis** against a `position_id`, naming the `applied_test` to be evaluated — `EXECUTIVE`, `ADMINISTRATIVE`, `PROFESSIONAL`, `COMPUTER` or `OUTSIDE_SALES`. The applied test may deliberately differ from the position's `claimed_exemption_test`; part of the audit's job is to test an alternative theory. The create also requires `expected_position_version` as described in §2.9. Opening an analysis records `analyst_user_id` from the acting `X-User-ID`, leaves `reviewer_user_id` null, sets `revision_round` to 0, and increments the position's `version` by one — which means a client holding a position version must re-read the position before opening a second analysis against it.

An analysis is created in `DRAFT` and carries nothing evaluated yet. **Submission** is what evaluates it, advancing `DRAFT → SUBMITTED`. Submission is refused while the position's `duties_validation_status` is `PENDING`, with `ERR_DUTIES_NOT_CORROBORATED`; the audit will not stake a determination on an uncorroborated duty picture. On submission the analysis snapshots the position's current figures onto itself as `weekly_salary_cents_snapshot` and `primary_duty_pct_snapshot`, and then evaluates both jurisdictional legs, writing `applicable_salary_floor_cents`, `applicable_duty_floor_pct`, `salary_threshold_source`, `federal_pass`, `state_pass`, `hce_shortcut_applied` and `outcome`, and incrementing its own `version`.

**Resolving the floors.** The position's jurisdiction is resolved as described in §2.6. The `applicable_salary_floor_cents` is the greater of the federal weekly floor of 84,400 cents and the jurisdiction's `min_weekly_salary_cents`. The `applicable_duty_floor_pct` is 60.0 percent when the jurisdiction's `duties_test_variant` is `STRICT_ENUM`, and 50.0 percent for both the `FEDERAL` and the `QUANTITATIVE_50PCT` variants. The `salary_threshold_source` records `STATE` when the jurisdiction's weekly floor **strictly exceeds** the federal floor, and `FEDERAL` otherwise — so a state floor that merely equals the federal floor is reported as `FEDERAL`.

Two conversions of the salary are also needed. The weekly salary is the position's `annual_salary_cents` divided by 52 and truncated to a whole cent. The hourly rate is the `annual_salary_cents` divided by 2,080 and truncated to a whole cent. The highly-compensated floor for the position is the greater of the federal annual floor of 13,200,000 cents and the jurisdiction's `hce_annual_cents`.

**The duties gate.** Each applied test has a qualitative gate that the position must satisfy in addition to any percentage floor:

- `EXECUTIVE` requires a `corroborated_supervises_headcount` of at least 2 **and** a `corroborated_hire_fire_influence` of true.
- `ADMINISTRATIVE` requires at least one duty statement on the position that is both marked `is_exempt_duty` and carries a `discretion_level` of `INDEPENDENT_JUDGMENT`.
- `PROFESSIONAL` requires `requires_advanced_degree` to be true.
- `COMPUTER` has no qualitative gate; it is satisfied unconditionally.
- `OUTSIDE_SALES` nominally asks whether `works_primarily_offsite` is true, but the outside-sales duties leg passes unconditionally (see below), so this gate is never actually consulted and `works_primarily_offsite` does not by itself change an outside-sales outcome.

**The salary leg**, evaluated against a given floor in cents, resolves as follows. For `OUTSIDE_SALES` the salary leg simply passes — outside salespeople are not subject to a salary floor at all. Otherwise, when the position's `salary_basis` is anything other than `HOURLY`, the leg passes exactly when the weekly salary is greater than or equal to the given floor. When the `salary_basis` **is** `HOURLY`, the leg passes only for the `COMPUTER` test and only when the hourly rate is at least the computer-employee hourly floor of 2,763 cents; for every other applied test an hourly-paid position fails the salary leg outright, whatever the floor.

**The duties leg**, evaluated against a given duty floor percentage, likewise passes unconditionally for `OUTSIDE_SALES`. For every other applied test it passes exactly when the position's `primary_duty_pct` is greater than or equal to the given floor **and** the applied test's qualitative gate is satisfied.

**Jurisdictional recognition** matters for two of the five tests. For `COMPUTER` the jurisdiction must have `computer_exemption_recognized` true; for `OUTSIDE_SALES` it must have `outside_sales_recognized` true; for the other three tests recognition is never in question.

**The highly-compensated shortcut** lets a very well-paid employee clear an abbreviated duties test. A position is eligible for it when all four of the following hold: `annual_salary_cents` is at least the highly-compensated floor resolved above; the weekly salary is at least the federal weekly floor of 84,400 cents; `primary_duty_pct` is at least 20.0 percent; and the `applied_test` is one of `EXECUTIVE`, `ADMINISTRATIVE` or `PROFESSIONAL`. The shortcut is never available to `COMPUTER` or `OUTSIDE_SALES` analyses.

**The two legs are always both computed, and they can disagree.** The `federal_pass` leg is true when the salary leg passes against the federal weekly floor of 84,400 cents and the duties leg passes against the federal duty floor of 50.0 percent — or, failing that, when the position is eligible for the highly-compensated shortcut. The federal leg ignores the jurisdiction's recognition flags entirely and honours the shortcut unconditionally. The `state_pass` leg is true when three things hold together: the jurisdiction recognizes the applied test; the salary leg passes against `applicable_salary_floor_cents`; and either the duties leg passes against `applicable_duty_floor_pct`, or the position is eligible for the shortcut **and** the jurisdiction has `hce_shortcut_recognized` true. Because the state leg adds a recognition requirement, a higher salary floor, a possibly higher duty floor, and a jurisdictional veto over the shortcut, a position can pass federally and still fail on the state leg. The `hce_shortcut_applied` flag is true exactly when the position is eligible for the shortcut and the ordinary federal duties leg — against the 50.0 percent federal floor — does **not** pass; that is, when the shortcut is what actually carried the analysis rather than merely being available.

The `outcome` follows from all of that. It is `INDETERMINATE` whenever the position's `duties_validation_status` is `PENDING`; otherwise it is `EXEMPT` when both `federal_pass` and `state_pass` are true, and `NONEXEMPT` in every other case. A position in a jurisdiction with no registered rule is evaluated on the federal baseline alone, in which case the two legs necessarily agree.

Registering a new jurisdiction rule has **no** retroactive effect: already-evaluated analyses are not re-evaluated, and their recorded floors and passes stand until the analysis is resubmitted.

### 3.5. Independent Review, Determination and Rescission

A submitted analysis awaits a `ClassificationReviewer` who is not its author. Two dispositions are available from `SUBMITTED`.

**Return** sends the analysis back for revision, advancing `SUBMITTED → RETURNED`, recording `reviewer_user_id` and the reviewer's `return_reason`, and incrementing the analysis `version`. The analyst then resubmits, advancing `RETURNED → SUBMITTED`; this is a genuine loop with no bound on how many times it may be traversed. Each resubmission increments `revision_round` by one — that counter is the observable measure of how many revision rounds an analysis has been through — and re-snapshots and re-evaluates the position's current figures from scratch, so a resubmission after a salary or duty change reaches a different answer than the first submission did. Resubmission is subject to the same corroboration precondition: a position back at `PENDING` cannot be resubmitted, and the attempt is `ERR_DUTIES_NOT_CORROBORATED`.

**Determination** records the reviewer's finding, and the target state is chosen by the analysis, not by the client. An analysis whose `outcome` is `EXEMPT` advances `SUBMITTED → EXEMPT_CONFIRMED`; an analysis whose `outcome` is `NONEXEMPT` advances `SUBMITTED → NONEXEMPT_DETERMINED`. An analysis whose `outcome` is `INDETERMINATE` cannot be determined at all and the attempt is `ERR_INVALID_STATE_TRANSITION`. Both determinations record `reviewer_user_id` and both increment the `version` of the analysis, the position, the family and the engagement.

The cascades differ. Confirming an exemption sets the position's `classification_status` from `UNREVIEWED` to `VALIDATED_EXEMPT` and recomputes the family's `risk_score`, `risk_tier`, `family_headcount` and `open_misclassified_count` along with the engagement's `remediation_posture` and `open_misclassified_headcount`. Determining nonexemption branches on how the position is actually being paid: when the position's `current_fls_status` is `EXEMPT` the finding contradicts payroll practice and `classification_status` becomes `MISCLASSIFIED`; when `current_fls_status` is already `NONEXEMPT` the finding merely confirms practice and `classification_status` becomes `CONFIRMED_NONEXEMPT`. The `MISCLASSIFIED` branch increments the family's `open_misclassified_count`, adds the position's `incumbent_count` to the engagement's `open_misclassified_headcount`, and brings the misclassification risk contribution into the family's score. The `CONFIRMED_NONEXEMPT` branch instead removes the position from the family's risk population entirely, which changes `family_headcount`: the employee is already being paid as nonexempt, so the finding is confirmatory, carries no exposure and needs no remediation. Both branches recompute the engagement's `remediation_posture`.

**Rescission** reverses a determination that should not have been made. A `ClassificationReviewer` other than the author may return an analysis that has already been determined, advancing `EXEMPT_CONFIRMED → RETURNED` or `NONEXEMPT_DETERMINED → RETURNED`, recording `reviewer_user_id` and `return_reason`. Rescission is blocked once money and payroll have moved: if any reclassification case on the position has `pay_conversion_status` equal to `CONVERTED`, the rescission is rejected with `ERR_RECLASS_ALREADY_CONVERTED`. Rescinding from `EXEMPT_CONFIRMED` reverts the position's `classification_status` to `UNREVIEWED` and recomputes the family and engagement derived fields. Rescinding from `NONEXEMPT_DETERMINED` reverts `classification_status` to `UNREVIEWED`, decrements the family's `open_misclassified_count`, recomputes the family's `risk_score` and `risk_tier`, subtracts the position's `incumbent_count` from the engagement's `open_misclassified_headcount`, and recomputes the engagement's `remediation_posture` and `total_back_wage_exposure_cents`. Both rescissions increment the `version` of the analysis, the position, the family and the engagement. A rescinded analysis is back in `RETURNED` and may be resubmitted like any other returned analysis.

A position's `classification_status` is never set by a direct request on the position — every one of its edges is a consequence of some other entity's transition. The complete set of edges is `UNREVIEWED → VALIDATED_EXEMPT`, `UNREVIEWED → MISCLASSIFIED`, `UNREVIEWED → CONFIRMED_NONEXEMPT`, `MISCLASSIFIED → RECLASSIFIED` (on pay conversion), `RECLASSIFIED → MISCLASSIFIED` (on revert), and the three returns to `UNREVIEWED` from `VALIDATED_EXEMPT`, `MISCLASSIFIED` and `CONFIRMED_NONEXEMPT`. Returning from `CONFIRMED_NONEXEMPT` to `UNREVIEWED` puts the position back into the family's risk population.

### 3.6. Misclassification Risk Scoring and Remediation Prioritization

Every job family carries a headcount-weighted misclassification `risk_score` between 0 and 100, a `risk_tier` banding of it, and a `risk_variant` recording which algorithm produced it. The score is recomputed whenever a position's `primary_duty_pct`, `validated_weekly_hours`, `annual_salary_cents`, `work_state_code` or `classification_status` changes, and on position creation.

**The risk population** of a family is the positions whose `job_family_id` is that family and whose `classification_status` is neither `CONFIRMED_NONEXEMPT` nor `RECLASSIFIED` — the first because a confirmatory finding leaves no remaining risk, the second because the position has already been remediated. Positions of child families are never included. The family's `family_headcount` is the sum of `incumbent_count` over that population, while `open_misclassified_count` counts the family's positions whose `classification_status` is `MISCLASSIFIED`.

An empty family short-circuits: when `family_headcount` is 0, `risk_variant` is `EVIDENCE_WEIGHTED`, `risk_score` is 0 and `risk_tier` is `LOW`, with no division performed and no uncertainty premium added.

Otherwise each position in the population earns four risk components, using that position's own `applicable_salary_floor_cents` and `applicable_duty_floor_pct` resolved exactly as in §3.4:

- **Duty risk.** Take the position's `primary_duty_pct` less its applicable duty floor as a margin in percentage points. Multiply that margin by 2, subtract the product from 40, and round the result half up to a whole number. Then clamp the result into the range 0 to 40 inclusive — a margin large enough to drive the figure below 0 scores 0, and a negative margin large enough to drive it above 40 scores 40. A position sitting exactly on its duty floor therefore scores 40.
- **Salary risk.** Take the position's annual salary divided by 52 and truncated to a whole cent. Compute a comfort threshold as the applicable salary floor multiplied by 1.15 and rounded half up to a whole cent. The component is 0 when the weekly figure is at or above that comfort threshold, 15 when it is below the comfort threshold but at or above the applicable salary floor itself, and 30 when it is below the applicable salary floor.
- **Hours risk.** Take the position's `validated_weekly_hours` less the standard 40-hour workweek, treating any negative result as 0, multiply by 2, round half up to a whole number, and cap the component at 20.
- **Status risk.** 25 points when the position's `classification_status` is `MISCLASSIFIED`, and 0 otherwise.

The four components are added and the per-position total is capped at 100.

**Variant selection and roll-up.** If at least one position in the population still has `duties_validation_status` equal to `PENDING`, the family's `risk_variant` is `SCREENING`; if every position in the population has a `duties_validation_status` of `CORROBORATED` or `CONFLICTED`, the variant is `EVIDENCE_WEIGHTED`. The `SCREENING` variant adds an uncertainty premium of 12 points, because unvalidated duties understate real risk; the `EVIDENCE_WEIGHTED` variant adds nothing. So the identical set of positions scores 12 points higher under `SCREENING` than under `EVIDENCE_WEIGHTED`.

The roll-up itself is a **headcount-weighted mean, not a plain mean**: multiply each position's capped risk total by that position's `incumbent_count`, sum those products across the population, and divide by `family_headcount`. Add the premium to that mean, round the sum half up to a whole number, and cap the result at 100 to produce `risk_score`.

The `risk_tier` bands the score with inclusive lower edges: `CRITICAL` at 75 or above, `HIGH` at 55 or above, `MEDIUM` at 30 or above, and `LOW` below 30.

### 3.7. Reclassification: Pay Structure Conversion and Employee Communication

A misclassified position is remediated through a **reclassification case**, opened by a `CompensationManager` against a `position_id`. The case declares the window it governs as a closed interval from `effective_date`, the first day the new pay structure applies, through `effective_end_date`, the last day of the window, where the end date must be on or after the start date and the start date may not be in the past relative to the logical clock. Both are ISO dates. The case also fixes its `conversion_method` up front, either `SALARY_DIV_2080` or `COST_NEUTRAL_WITH_OT`. A new case is created with `exposure_cents` 0 and `case_status` `OPEN`.

Two scheduling constraints guard case creation. First, reclassification windows on the **same position** must not crowd each other: the requested closed interval must be separated from the closed interval of every existing case on that position by strictly more than the reclassification-window buffer, which is 7 calendar days (`RECLASS_WINDOW_BUFFER_DAYS` is 7). A window that overlaps, abuts, or comes within 7 days of an existing one is rejected with `ERR_RECLASS_WINDOW_CONFLICT`. Second, an organization can only absorb so much change at once within a single job family: at most 3 cases whose `pay_conversion_status` is `PENDING` or `CONVERTED` may have intersecting windows inside one job family (`MAX_CONCURRENT_RECLASS_PER_FAMILY` is 3). A fourth intersecting unreverted case is rejected with `ERR_RECLASS_WAVE_CAPACITY_EXCEEDED`. Reverted cases do not count against the wave.

**A case advances along two independent dimensions on the same row.** `pay_conversion_status` moves through `PENDING`, `CONVERTED` and `REVERTED`; `communication_status` moves through `NOT_STARTED`, `NOTICE_SENT`, `ESCALATED` and `ACKNOWLEDGED`. Neither dimension gates the other's transitions. The computed `case_status` is their conjunction: it is `COMPLETED` exactly when `pay_conversion_status` is `CONVERTED` **and** `communication_status` is `ACKNOWLEDGED`, and `OPEN` in every other combination.

**Pay conversion** is the `CompensationManager`'s act of rewriting the pay structure, advancing the pay dimension `PENDING → CONVERTED` (and, after a revert, `REVERTED → CONVERTED` again). Two preconditions guard it. The position must currently be `MISCLASSIFIED`, else `ERR_POSITION_NOT_MISCLASSIFIED`. And when the case's `exposure_cents` has reached the mandatory-correction threshold of 5,000,000 cents ($50,000), an `APPROVED` voluntary correction must already exist for that case, else `ERR_VOLUNTARY_CORRECTION_REQUIRED`; below that threshold no correction is required.

The conversion reads the `expected_weekly_hours` supplied on the call, a number between 0 and 168 inclusive, and records it on the case. Nothing else is read: the position's `annual_salary_cents` and that hours assumption are the entire input set. In particular `validated_weekly_hours` is deliberately **not** used, because the conversion is a forward-looking pay design rather than a historical measurement. Let the overtime hours be the `expected_weekly_hours` less 40, treating any negative result as 0.

The rate is then solved in a pinned order. Under `SALARY_DIV_2080`, `converted_hourly_rate_cents` is the annual salary divided by 2,080 and rounded half up to a whole cent, with no regard for overtime at all. Under `COST_NEUTRAL_WITH_OT`, first form a denominator of hours as 40 plus one and a half times the overtime hours, then divide the annual salary by 52 times that denominator and round the quotient half up to a whole cent — the rate is discounted by the overtime premium so that the projected cost lands within one rounding step of the old salary.

Whichever method produced it, the **rounded** rate is then used to recompute the cost: `projected_annual_cost_cents` is 52 multiplied by the sum of 40 times the rounded rate plus the overtime hours times one and a half times the rounded rate, the whole product rounded half up to a whole cent. Finally `cost_delta_cents` is `projected_annual_cost_cents` less the position's `annual_salary_cents`. Because the projected cost consumes the already-rounded rate, the delta is generally non-zero even under `COST_NEUTRAL_WITH_OT`, where it may land slightly negative; under `SALARY_DIV_2080` it is positive whenever `expected_weekly_hours` exceeds 40.

Conversion cascades widely. It sets the position's `current_fls_status` to `NONEXEMPT`, which makes `overtime_eligible` true, and moves its `classification_status` from `MISCLASSIFIED` to `RECLASSIFIED`, which drops the position out of the family's risk population and decrements the family's `open_misclassified_count`. It adds `cost_delta_cents` to the engagement's `converted_annual_payroll_delta_cents`. It recomputes the family's `open_misclassified_count`, `risk_score` and `risk_tier` and the engagement's `remediation_posture` and `open_misclassified_headcount`. And it increments the `version` of the case, the position, the family and the engagement.

**Reverting a conversion** advances the pay dimension `CONVERTED → REVERTED` and is refused once the employee has acknowledged: if the case's `communication_status` is `ACKNOWLEDGED`, the revert is rejected with `ERR_CASE_ALREADY_COMPLETED`. A revert clears `converted_hourly_rate_cents`, `projected_annual_cost_cents` and `cost_delta_cents` back to null, subtracts the previous `cost_delta_cents` from the engagement's `converted_annual_payroll_delta_cents` — the same figure that was added, exactly reversed — sets the position's `current_fls_status` back to `EXEMPT`, which makes `overtime_eligible` false, moves `classification_status` from `RECLASSIFIED` back to `MISCLASSIFIED`, restores the family's `open_misclassified_count` and the engagement's misclassified headcount, recomputes the family and engagement derived figures, and increments the `version` of the case, the position, the family and the engagement. A subsequent `REVERTED → CONVERTED` conversion recomputes everything against the newly supplied `expected_weekly_hours` and re-adds the new `cost_delta_cents` to the engagement rollup.

**The employee-relations dimension** is driven separately by an `EmployeeRelationsLead`, who selects one of three actions with the `action` field: `SEND_NOTICE`, `ACKNOWLEDGE` or `ESCALATE`.

Sending a notice advances `NOT_STARTED → NOTICE_SENT`, and also re-sends from `ESCALATED → NOTICE_SENT`. Both edges are gated on lead time: the number of calendar days from the logical clock's date to the case's `effective_date` must be at least the jurisdiction's `reclass_notice_days` for the position's `work_state_code`, else `ERR_NOTICE_WINDOW_TOO_SHORT`. An employee must not learn that their pay structure is changing the day before it changes. The first send records `notice_channel` from the request body and stamps `notice_sent_at` from the logical clock. A re-send from `ESCALATED` clears `escalation_reason` back to null and refreshes `notice_sent_at`.

Acknowledging advances `NOTICE_SENT → ACKNOWLEDGED` and also `ESCALATED → ACKNOWLEDGED`, with no precondition on either edge. Both stamp `acknowledged_at` from the logical clock and record `acknowledged_by_ref`, the opaque reference to the acknowledging employee, and both recompute `case_status` to `COMPLETED` when `pay_conversion_status` is already `CONVERTED`. The edge out of `ESCALATED` additionally clears `escalation_reason`. `ACKNOWLEDGED` is terminal on the communication dimension.

Escalating advances `NOTICE_SENT → ESCALATED` with no precondition, recording the `escalation_reason` supplied on the call. Every communication transition increments the case's `version` by one.

### 3.8. Back-Wage Exposure and Voluntary Correction Decisions

**Quantifying exposure.** A `CompensationManager` attaches a **back-wage estimate** to a case by naming its `reclassification_case_id`, the valuation `method` — `HALF_TIME` or `FULL_RATE` — and the `expected_reclassification_case_version` described in §2.9. Only one estimate is ever live per case: creating a new one sets the previous `ACTIVE` estimate's `status` to `SUPERSEDED`, and only the `ACTIVE` estimate contributes to the case's `exposure_cents` and to the engagement rollup. A case with no estimate has `exposure_cents` of 0.

The estimate first resolves how far back exposure reaches. The engagement's `lookback_policy` supplies a policy figure of 104 weeks — two years of workweeks — under `STANDARD_2Y`, or 156 weeks — three years — under `WILLFUL_3Y`. The estimate's `lookback_weeks` is the greater of that policy figure and the jurisdiction's `back_wage_lookback_weeks_override`, where a null override or an unregistered jurisdiction contributes 0 and therefore never shortens the policy figure.

Next it resolves the overtime hours. The weekly salary is the position's `annual_salary_cents` divided by 52 and truncated to a whole cent. The estimate's `weekly_ot_hours` is the position's `validated_weekly_hours` less the standard 40-hour workweek, with any negative result treated as 0.

The two methods then value those overtime hours differently, and the difference is substantial. Under `FULL_RATE` the salary is held to cover 40 hours only, so the regular rate is the weekly salary divided by 40, and `week_ot_cents` is the overtime hours multiplied by that regular rate multiplied by one and a half, rounded half up to whole cents. Under `HALF_TIME` — the fluctuating-workweek theory — the salary is held to have already covered straight time for every hour worked, so the regular rate is the weekly salary divided by the position's `validated_weekly_hours`, and `week_ot_cents` is the overtime hours multiplied by that regular rate multiplied by one half, rounded half up to whole cents. For identical inputs `HALF_TIME` yields a strictly smaller exposure than `FULL_RATE` whenever `validated_weekly_hours` exceeds 40, which is exactly why the choice of `method` is a decision the audit records rather than a detail.

The rounding order here is pinned and consequential: `week_ot_cents` is rounded to whole cents **before** any multiplication. Then `gross_exposure_cents` is `week_ot_cents` multiplied by `lookback_weeks` multiplied by the position's `incumbent_count`. The `liquidated_damages_cents` is `gross_exposure_cents` multiplied by the jurisdiction's `liquidated_damages_multiplier` and rounded half up to whole cents; a position in an unregistered jurisdiction carries a multiplier of 0.0 and therefore no liquidated damages at all. Finally `total_exposure_cents` is `gross_exposure_cents` plus `liquidated_damages_cents`.

Creating an estimate refreshes the case's `exposure_cents` and the engagement's `total_back_wage_exposure_cents`, and increments the case's `version` by one.

**The engagement rollups.** Four figures on the engagement are pure integer summation with no rounding anywhere. The `total_back_wage_exposure_cents` sums `total_exposure_cents` over back-wage estimates whose `status` is `ACTIVE` and whose case's position belongs to this engagement **and** whose case's position has a `classification_status` of `MISCLASSIFIED` or `RECLASSIFIED` — so rescinding a determination back to `UNREVIEWED` drops that exposure out of the rollup without deleting the estimate. The `converted_annual_payroll_delta_cents` sums `cost_delta_cents` over the engagement's reclassification cases whose `pay_conversion_status` is `CONVERTED`. The `committed_correction_cents` sums `approved_amount_cents` over the engagement's voluntary corrections whose `status` is `APPROVED`. The `open_misclassified_headcount` sums `incumbent_count` over the engagement's positions whose `classification_status` is `MISCLASSIFIED`. All four are refreshed on estimate creation, on any change to a position's `classification_status`, and on any voluntary-correction decision.

**Deciding whether to self-correct.** Either a `CompensationManager` or a `LegalCounsel` may propose a **voluntary correction** against a `reclassification_case_id`, choosing a `decision` posture of `SELF_CORRECT_FULL`, `SELF_CORRECT_PARTIAL`, `DEFER` or `AGENCY_SUPERVISED` and a `proposed_amount_cents` of zero or more that the proposer recommends paying. The proposal is created in `PROPOSED` status and records `proposed_by_user_id` from the acting `X-User-ID`.

A `LegalCounsel` then decides it, selecting `APPROVE` or `REJECT` with the `disposition` field, and may not be the same operator who proposed it. Approval advances `PROPOSED → APPROVED`, records the authorized `approved_amount_cents` (zero or more) and the `approver_user_id`, and adds the approved amount to the engagement's `committed_correction_cents`, incrementing the `version` of both the correction and the engagement. Two fiscal guards apply, in this order: the approved amount may not exceed the delegated authority cap of 25,000,000 cents ($250,000), else `ERR_APPROVAL_AUTHORITY_EXCEEDED`; and a `SELF_CORRECT_FULL` posture must actually be funded, meaning the approved amount must be at least the case's `exposure_cents`, else `ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE`. The funding guard applies only to the `SELF_CORRECT_FULL` posture; a partial, deferred or agency-supervised correction may be approved for any amount inside the authority cap.

Rejection advances `PROPOSED → REJECTED`, records the `rejection_reason` and the `approver_user_id`, increments only the correction's `version`, and moves no money into the engagement rollup. Both `APPROVED` and `REJECTED` are terminal.

### 3.9. Independent-Contractor Review, Job-Change Triggers and Engagement Closure

**Screening engaged vendors.** Misclassification is not only an exempt-versus-nonexempt question, so a `ComplianceAnalyst` also opens an **independent-contractor review** under an `audit_project_id`, naming the `vendor_name` and the `engagement_state_code` whose registered `ic_test` selects which test applies. The whole classification is computed at create time; the finalize step later only asserts the answer.

Which inputs are required depends entirely on the selected test, and the review must supply exactly the set that test needs — a mismatch is `ERR_IC_TEST_INPUTS_MISSING`. Under the `ABC` test the review supplies three booleans: `free_from_control` for prong A, `outside_usual_course` for prong B, and `independent_trade` for prong C. All three prongs are required; the `outcome` is `CONTRACTOR` only when all three are true, and `EMPLOYEE` otherwise, with `ic_score` left null. The `ABC` test admits no `INDETERMINATE` result at all.

Under the `ECONOMIC_REALITY` test — which is also the default whenever the `engagement_state_code` matches no registered jurisdiction — the review supplies `economic_reality_factors`, an object of six booleans: `control_by_worker`, `opportunity_for_profit_or_loss`, `worker_investment`, `relationship_is_project_based`, `skill_and_initiative` and `not_integral_to_business`. The `ic_score` is the count of those six that are true, so it ranges from 0 through 6. The `outcome` is `CONTRACTOR` when the score is 5 or more, `EMPLOYEE` when it is 2 or less, and `INDETERMINATE` at 3 or 4.

Under the `COMMON_LAW` test the review supplies three integer factor scores, each between 0 and 5 inclusive: `behavioral_control_score`, `financial_control_score` and `relationship_score`. The `ic_score` weights them unequally — the behavioral score is multiplied by 3, the financial score by 2, and the relationship score by 1, and the three products are added — so it ranges from 0 through 30. The `outcome` is `CONTRACTOR` when the score is 20 or more, `EMPLOYEE` when it is 11 or less, and `INDETERMINATE` between 12 and 19 inclusive.

Whichever test applied is recorded on the review as `applied_ic_test`. A review is created in `DRAFT` status. A `ClassificationReviewer` finalizes it into the one terminal state that matches the computed `outcome`: `DRAFT → FINALIZED_CONTRACTOR` when the outcome is `CONTRACTOR`, `DRAFT → FINALIZED_EMPLOYEE` when it is `EMPLOYEE`, and `DRAFT → FINALIZED_INDETERMINATE` when it is `INDETERMINATE`. Finalizing into a branch that does not match the computed outcome is `ERR_INVALID_STATE_TRANSITION`. All three branches increment the review's `version` by one. Only the `FINALIZED_EMPLOYEE` branch touches anything outside the review: it raises the engagement's `remediation_posture` to at least `RESTRICTED` and increments the engagement's `version`. The `FINALIZED_CONTRACTOR` and `FINALIZED_INDETERMINATE` branches leave the engagement's posture and version untouched.

**Ongoing job changes.** Jobs do not hold still while an audit runs, so a `ComplianceAnalyst` records each material change against a `position_id` as an append-only **job change trigger** with a `trigger_type` of `SALARY_CHANGE`, `DUTIES_CHANGE`, `REPORTING_CHANGE`, `STATE_CHANGE` or `FLSA_THRESHOLD_UPDATE`. Each type requires exactly one payload field: `new_annual_salary_cents` (strictly greater than zero) for `SALARY_CHANGE`, `new_exempt_duty_pct` (between 0 and 100 inclusive) for `DUTIES_CHANGE`, `new_supervises_headcount` (zero or more) for `REPORTING_CHANGE`, and a two-letter uppercase `new_work_state_code` for `STATE_CHANGE`; `FLSA_THRESHOLD_UPDATE` requires none of them. A missing required field for the declared type is `ERR_INVALID_REQUEST`.

The trigger computes two fields at create time: the boolean `requires_reanalysis` and a `reason_code` explaining the decision. Not every change matters, and the test is different for each type:

- `SALARY_CHANGE` matters only when it moves the position **across** the applicable weekly salary floor. Resolve the position's current floor as the greater of the federal weekly floor of 84,400 cents and its jurisdiction's `min_weekly_salary_cents`. Compare whether the old weekly salary — the current `annual_salary_cents` divided by 52 and truncated — sits at or above that floor with whether the new weekly salary — `new_annual_salary_cents` divided by 52 and truncated — sits at or above the same floor. Re-analysis is required exactly when those two answers differ, with `reason_code` `SALARY_CROSSED_THRESHOLD`. A raise or cut entirely on one side of the floor changes nothing.
- `DUTIES_CHANGE` matters when the absolute difference between `new_exempt_duty_pct` and the position's current `primary_duty_pct` is **at least** 10.0 percentage points, compared at one decimal place. A delta of exactly 10.0 does require re-analysis. The `reason_code` is `DUTY_DELTA_EXCEEDED`.
- `REPORTING_CHANGE` matters only for a position whose `claimed_exemption_test` is `EXECUTIVE` and whose `new_supervises_headcount` drops **below** 2. The `reason_code` is `EXEC_SUPERVISION_LOST`.
- `STATE_CHANGE` matters when the move changes either applicable floor. Compute the old and new salary floors as the greater of the federal weekly floor and each jurisdiction's `min_weekly_salary_cents`, and the old and new duty floors as 60.0 percent where that jurisdiction's `duties_test_variant` is `STRICT_ENUM` and 50.0 percent otherwise, with an unregistered jurisdiction contributing the federal figures in both cases. Re-analysis is required when the salary floors differ **or** the duty floors differ. The `reason_code` is `JURISDICTION_FLOOR_CHANGED`.
- `FLSA_THRESHOLD_UPDATE` always requires re-analysis, with `reason_code` `THRESHOLD_UPDATE_MANDATED`.

Whenever none of the above is satisfied, `requires_reanalysis` is false and the `reason_code` is `NO_REANALYSIS_REQUIRED`. **The trigger row is still created and recorded, but no attribute is written onto the position and no cascade runs at all.**

When `requires_reanalysis` is true, a deep cascade runs in this order. First the changed attribute is written onto the position: `SALARY_CHANGE` writes `new_annual_salary_cents` into `annual_salary_cents`; `DUTIES_CHANGE` writes `new_exempt_duty_pct` into `self_reported_exempt_pct_override`, which from then on replaces the duty-statement-derived figure as the position's `self_reported_exempt_pct`; `STATE_CHANGE` writes `new_work_state_code` into `work_state_code`; and `REPORTING_CHANGE` and `FLSA_THRESHOLD_UPDATE` write no attribute at all. Second, **every** exemption analysis of the position whose `status` is not already `SUPERSEDED` transitions to `SUPERSEDED`, incrementing each analysis's `version` — that means `DRAFT`, `SUBMITTED`, `RETURNED`, `EXEMPT_CONFIRMED` and `NONEXEMPT_DETERMINED` analyses alike, and `SUPERSEDED` is terminal. Superseding an `EXEMPT_CONFIRMED` analysis reverts the position's `classification_status` to `UNREVIEWED`; superseding a `NONEXEMPT_DETERMINED` analysis reverts `classification_status` to `UNREVIEWED`, decrements the family's `open_misclassified_count`, recomputes `risk_score` and `risk_tier`, and recomputes the engagement's `open_misclassified_headcount` and `remediation_posture`. Third, the position's `classification_status` is set to `UNREVIEWED` regardless. Fourth — and **only** for `DUTIES_CHANGE` — every `ATTESTED` interview of the position transitions to `VOIDED` with a `void_reason` of `CHANGE_TRIGGER_DUTIES`, which necessarily forces `duties_validation_status` back to `PENDING`. Fifth, the duties corroboration, the family risk score and the engagement posture are recomputed in that order. The trigger increments the `version` of the position, the family and the engagement.

Because a re-analysis-forcing trigger returns a position to `UNREVIEWED`, it can re-open fieldwork on an engagement that had already moved on to remediation.

**Engagement stages and closure.** A `ProgramAdmin` drives the engagement through its stages by supplying a `target_status`, and each requested edge must be a declared transition from the current status with its preconditions satisfied.

`PLANNING → FIELDWORK` requires that at least one job family already exist under the engagement. Fieldwork is the only stage in which interviews may be booked or completed.

`FIELDWORK → REMEDIATION` requires that **every** position under the engagement has a `classification_status` other than `UNREVIEWED`; if any position is still unreviewed the transition is `ERR_PROJECT_STAGE_PRECONDITION_UNMET`. Entering remediation assigns a 1-based `remediation_priority_rank` to every job family of the engagement, ordered by `risk_score` descending, then by `family_headcount` descending, then by `created_at` ascending as the final tie-break.

`REMEDIATION → FIELDWORK` is the cycle edge back, and it requires the opposite condition: at least one position under the engagement must have a `classification_status` of `UNREVIEWED`, else `ERR_PROJECT_STAGE_PRECONDITION_UNMET`. Rewinding clears `remediation_priority_rank` back to null on every family of the engagement.

`REMEDIATION → CLOSED` requires four conditions to hold together, and any failure is `ERR_PROJECT_NOT_READY_TO_CLOSE`: no position under the engagement may still be `MISCLASSIFIED`; every reclassification case under the engagement must have a `case_status` of `COMPLETED`; every voluntary correction under the engagement must be either `APPROVED` or `REJECTED`; and no contractor review under the engagement may still be in `DRAFT`. `CLOSED` is the engagement's terminal status.

Every one of the four stage transitions increments the engagement's `version` by one. Requesting a `target_status` that is not a declared transition from the current status is `ERR_PROJECT_STAGE_INVALID`.

## 4. Endpoint Definitions

Operations that mint a new resource return `201 Created`. Operations that modify an existing resource — including every state-machine action and the logical-clock capability — return `200 OK`. Read operations return `200 OK`. Every path parameter is written `{id}` and refers to the resource named by the collection segment immediately before it. Every list endpoint accepts the `limit` and `offset` query parameters of §2.3 and returns rows ordered by `created_at` ascending. "Any" in the authorized-role column means all seven roles of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock, which every date and datetime comparison in the domain reads | ProgramAdmin |
| POST | `/state-rules` | Register a jurisdiction's exemption variation: salary floors, duties-test variant, recognition flags, contractor test, liquidated-damages multiplier, notice lead time and statutory lookback | ProgramAdmin |
| GET | `/state-rules` | List registered jurisdiction rules | Any |
| POST | `/audit-projects` | Open a classification audit engagement in PLANNING | ProgramAdmin |
| GET | `/audit-projects/{id}` | Get one audit engagement including its derived posture and rollups | Any |
| POST | `/audit-projects/{id}/status` | Advance or rewind the engagement stage; `target_status` selects FIELDWORK, REMEDIATION or CLOSED | ProgramAdmin |
| GET | `/audit-projects/{id}/job-families` | List the job families inventoried under this engagement | Any |
| GET | `/audit-projects/{id}/contractor-reviews` | List the independent-contractor reviews under this engagement | Any |
| POST | `/job-families` | Create a job family under an engagement, optionally beneath a parent family | ProgramAdmin |
| GET | `/job-families/{id}` | Get one job family with its current risk score, tier, variant and remediation rank | Any |
| GET | `/job-families/{id}/child-families` | List the families whose parent is this family | Any |
| GET | `/job-families/{id}/positions` | List the positions inventoried in this family | Any |
| POST | `/positions` | Add a job description to the inventory in UNREVIEWED classification status | ProgramAdmin |
| GET | `/positions/{id}` | Get one position with every derived duty, salary and classification field | Any |
| GET | `/positions/{id}/duty-statements` | List the duty statements of this position | Any |
| GET | `/positions/{id}/interviews` | List the manager and incumbent interviews of this position | Any |
| GET | `/positions/{id}/exemption-analyses` | List the exemption analyses of this position across all revision rounds | Any |
| GET | `/positions/{id}/reclassification-cases` | List the reclassification cases of this position | Any |
| GET | `/positions/{id}/job-change-triggers` | List the append-only job change events recorded against this position | Any |
| POST | `/duty-statements` | Add a duty line to a job description | ComplianceAnalyst |
| POST | `/interviews` | Book a duties-validation interview with a manager or an incumbent in SCHEDULED status | ComplianceAnalyst |
| GET | `/interviews/{id}` | Get one interview with its reported figures and lifecycle timestamps | Any |
| POST | `/interviews/{id}/complete` | Record the respondent's account of duties, hours, supervision and hire/fire influence | ComplianceAnalyst |
| POST | `/interviews/{id}/attest` | Attest the completed interview, feeding it into the duties corroboration calculation | ComplianceAnalyst |
| POST | `/interviews/{id}/void` | Void an interview, releasing the interviewer's window and withdrawing the account from corroboration | ClassificationReviewer |
| POST | `/exemption-analyses` | Open a DRAFT exemption analysis for one of the five white-collar tests | ComplianceAnalyst |
| GET | `/exemption-analyses/{id}` | Get one exemption analysis with both jurisdictional legs and the resulting outcome | Any |
| POST | `/exemption-analyses/{id}/submit` | Submit the analysis for review, snapshotting the position inputs and evaluating the federal and state legs | ComplianceAnalyst |
| POST | `/exemption-analyses/{id}/return` | Return a submitted analysis to the analyst, or rescind a determination already made | ClassificationReviewer |
| POST | `/exemption-analyses/{id}/determine` | Record the reviewer's determination; the target state is chosen by the analysis outcome | ClassificationReviewer |
| POST | `/reclassification-cases` | Open a reclassification window for a position, pay dimension PENDING and communication dimension NOT_STARTED | CompensationManager |
| GET | `/reclassification-cases/{id}` | Get one reclassification case with both state dimensions, the conversion figures and the current exposure | Any |
| POST | `/reclassification-cases/{id}/pay-conversion` | Convert the position's pay structure using the case's conversion method and the supplied hours assumption | CompensationManager |
| POST | `/reclassification-cases/{id}/revert-pay-conversion` | Reverse a completed pay conversion, restoring the exempt pay structure and removing the delta from the engagement rollup | CompensationManager |
| POST | `/reclassification-cases/{id}/communication` | Drive the employee-relations dimension; `action` selects SEND_NOTICE, ACKNOWLEDGE or ESCALATE | EmployeeRelationsLead |
| GET | `/reclassification-cases/{id}/back-wage-estimates` | List the back-wage estimates of this case including superseded ones | Any |
| GET | `/reclassification-cases/{id}/voluntary-corrections` | List the voluntary correction proposals of this case | Any |
| POST | `/back-wage-estimates` | Estimate back-wage exposure for a case under the half-time or full-rate method | CompensationManager |
| POST | `/voluntary-corrections` | Propose a voluntary correction posture and amount for a case | CompensationManager, LegalCounsel |
| POST | `/voluntary-corrections/{id}/decision` | Approve or reject a proposed correction; `disposition` selects APPROVE or REJECT | LegalCounsel |
| POST | `/contractor-reviews` | Open a DRAFT independent-contractor review; the applicable test is selected from the engagement state and the outcome is computed at create | ComplianceAnalyst |
| POST | `/contractor-reviews/{id}/finalize` | Finalize the review into the terminal state matching its computed outcome | ClassificationReviewer |
| POST | `/job-change-triggers` | Record an ongoing job change against a position and evaluate whether it forces re-analysis | ComplianceAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ROLE_NOT_PERMITTED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AUDIT_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_FAMILY_NOT_FOUND` | 404 Not Found |
| `ERR_POSITION_NOT_FOUND` | 404 Not Found |
| `ERR_INTERVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYSIS_NOT_FOUND` | 404 Not Found |
| `ERR_RECLASS_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CORRECTION_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACTOR_REVIEW_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_INTERVIEW_RESPONDENT` | 409 Conflict |
| `ERR_DUTY_TIME_OVERALLOCATED` | 409 Conflict |
| `ERR_IC_TEST_INPUTS_MISSING` | 409 Conflict |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_INTERVIEW_NOT_STARTED` | 409 Conflict |
| `ERR_PROJECT_STAGE_INVALID` | 409 Conflict |
| `ERR_PROJECT_STAGE_PRECONDITION_UNMET` | 409 Conflict |
| `ERR_PROJECT_NOT_READY_TO_CLOSE` | 409 Conflict |
| `ERR_PROJECT_POSTURE_FROZEN` | 409 Conflict |
| `ERR_POSTURE_RESTRICTED_FAMILY` | 409 Conflict |
| `ERR_DUTIES_NOT_CORROBORATED` | 409 Conflict |
| `ERR_INTERVIEWER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_RECLASS_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_RECLASS_WAVE_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_POSITION_NOT_MISCLASSIFIED` | 409 Conflict |
| `ERR_VOLUNTARY_CORRECTION_REQUIRED` | 409 Conflict |
| `ERR_RECLASS_ALREADY_CONVERTED` | 409 Conflict |
| `ERR_CASE_ALREADY_COMPLETED` | 409 Conflict |
| `ERR_NOTICE_WINDOW_TOO_SHORT` | 409 Conflict |
| `ERR_APPROVAL_AUTHORITY_EXCEEDED` | 409 Conflict |
| `ERR_CORRECTION_AMOUNT_BELOW_EXPOSURE` | 409 Conflict |
| `ERR_STALE_POSITION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CASE_VERSION` | 412 Precondition Failed |

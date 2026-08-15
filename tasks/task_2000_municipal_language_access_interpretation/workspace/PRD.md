# Municipal Language Access & Interpretation Coordination API — Product Requirements Document

## 1. Introduction

A city's language access office sits between two hard obligations: residents with limited English proficiency must be able to reach every municipal service, and the money to deliver that access is finite, split across vendor contracts and departmental budgets that someone has to watch line by line. This document specifies the API through which the office coordinates the work — measuring language need service area by service area, routing vital documents through a translation and quality-review pipeline, dispatching phone, video, and in-person interpreters on demand, policing signage and notice obligations, and converting resident complaints into scored, remediated outcomes.

The API manages nine resource types: departments, language assessments, vital documents, translation jobs, interpreters, interpretation requests, complaints, vendor contracts, and annual language access plans. It operates under a segregation-of-duties role model in which the person who records a complaint may not adjudicate it and the translator who produces a document may not review it. Two ledger families (per-contract commitment accounting and per-department budget accounting), two chronological scoring models (department compliance and interpreter quality), and a constraint-driven dispatch selector together decide, in real time, who may spend, who may work, and which obligations are falling behind.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelope contracts, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` to identify the acting user and `X-User-Role` to name their operational capacity. The declared roles are `LanguageAccessCoordinator`, `DepartmentLiaison`, `Interpreter`, `QualityReviewer`, and `ComplianceOfficer`. A request missing either header, or carrying a role value outside this set, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Beyond authentication, each operation restricts which roles may invoke it, and some operations add an ownership scope; violations are rejected with `ERR_FORBIDDEN_ROLE`.

What `X-User-ID` means depends on the role. When `X-User-Role` is `DepartmentLiaison`, `X-User-ID` is the `id` of the `Department` the liaison represents: ownership checks on any resource that references a department compare the resource's `department_id` field to `X-User-ID`, and a liaison acting on another department's resources is refused. When `X-User-Role` is `Interpreter` or `QualityReviewer`, `X-User-ID` is the `id` of the acting `Interpreter` record — it must resolve to an existing interpreter (otherwise `ERR_INTERPRETER_NOT_FOUND`) — and assignment-scoped operations compare it against the translation job's `translator_id` or the interpretation request's `interpreter_id`. When `X-User-Role` is `LanguageAccessCoordinator` or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity: the server records it on audit stamps such as `created_by_user_id`, `reviewed_by_user_id`, `recorded_by_user_id`, and `adjudicated_by_user_id`, but never compares it to an entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0.

Unless otherwise specified, list endpoints return resources sorted by `created_at` in ascending order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints also accept optional equality filters named for the resource's own fields — across the API these are `department_id`, `plan_year`, `status`, `document_id`, `vendor_contract_id`, `translator_id`, `reviewer_id`, `superseded_by_job_id`, `interpreter_id`, `interpretation_request_id`, `language_code`, `modality`, and `tier` — alongside `limit` and `offset`.

### 2.4. Common Resource Properties

Every one of the nine resource types in this API carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every accepted mutation of the resource.
- `version` (integer): a system-managed counter that increments by one on every accepted mutation — including mutations driven by cascades originating on other resources, so a department's `version` advances when a complaint cascade rewrites its signage or when settled work moves its spend balance.

### 2.5. The Logical Clock

All time-dependent rules in this API — confidentiality currency, scheduling lead time, past-start rejection, remediation windows, monthly minute tallies, and after-hours determination — read a server-side logical clock and never fall back to wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `LanguageAccessCoordinator` may move it by posting `to_iso8601` to `/_clock/set_current_utc`; the response echoes the new logical time as `current_utc`.

### 2.6. Money, Rates, and Rounding

Monetary amounts are integer cents end to end: budgets, ceilings, rate cards, commitments, and costs are all stored and returned as whole cents, and no fractional-cent values ever appear in the API. Multi-step prices round half up at pinned steps only — interpretation pricing rounds after the tier-multiplier step and again after the after-hours step, while translation pricing rounds after the revision-surcharge step and again after the rush step. Flat provisional estimates are exact products with no rounding applied.

Population and encounter shares are carried at four decimal places, rounded half up, and every threshold comparison consumes the rounded share rather than the raw quotient. Compliance scores and quality ratings are integer points.

### 2.7. Optimistic Concurrency Control

Exactly one operation in the API participates in optimistic concurrency control: the department profile/budget update. Such a request must carry `expected_department_version`, a non-optional field holding the department `version` the client last observed. A client's view goes stale whenever any accepted write has advanced the department's `version` in between — another profile update, or a cascaded mutation touching `spent_cents`, `compliance_score`, or `signage_status`. When `expected_department_version` no longer matches the department's current `version`, the update is rejected with `ERR_STALE_VERSION` (HTTP 412) so the client cannot overwrite state it has not observed. Endpoints not named here take no version field at all.

### 2.8. Existence Checks and Reference Resolution

The API's resources are peers: there are no nested collection URLs, and relationships travel through identifier fields carried in request bodies. When a request must resolve references, path identifiers are validated first in left-to-right order, and only then are body references — `department_id`, `document_id`, `vendor_contract_id`, `translator_id`, and `interpretation_request_id` — resolved. Each unresolvable reference produces the not-found identifier for its own resource type: `ERR_DEPARTMENT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_JOB_NOT_FOUND`, `ERR_INTERPRETER_NOT_FOUND`, `ERR_REQUEST_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, or `ERR_PLAN_NOT_FOUND`. Callers in entity-backed roles are resolved at the same stage: an `Interpreter` or `QualityReviewer` whose `X-User-ID` matches no interpreter record fails with `ERR_INTERPRETER_NOT_FOUND`.

### 2.9. Commitment Accounting and Spending Gates

Every vendor contract maintains a two-pocket ledger. Provisional commitments — translation jobs still in flight and interpretation requests assigned but not yet delivered — accumulate in `committed_cents`; settled, irrevocable spend accumulates in `spent_cents`; and `available_cents` is what remains under the `ceiling_cents` after both. The invariant is strict: the existing commitments plus the settled spend plus any prospective new commitment must never exceed the ceiling, with an exact fit permitted. Commitments release back when their underlying work is cancelled, and settle into spend when the work is approved or completed.

A parallel gate guards the public-money side. Each department's `annual_budget_cents` is drawn down by settled interpretation and translation costs, and the dispatch workflow will not commit an interpreter whose estimated price exceeds the department's `remaining_cents`. Both fiscal gates are deliberately the last checks in the validation cascade (§2.10), so a request that fails for money has already passed every safety, qualification, and temporal check.

### 2.10. Validation Ordering

Incoming writes are checked against an ordered cascade, and an earlier failure masks every later check. The stages, in evaluation order:

1. **User context.** The `X-User-ID` and `X-User-Role` headers are present and the role is a declared role, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role and ownership.** The role is permitted for the operation and any ownership scope holds — a liaison's `X-User-ID` must equal the `department_id` being acted on, an interpreter may submit or complete only their own assignments, and only a `ComplianceOfficer` may pass an interpreter `status` change — else `ERR_FORBIDDEN_ROLE`.
3. **Request shape.** Required fields are present, types match, enum values are valid, and numeric ranges hold (counts at least zero; populations, encounter totals, word counts, and minute declarations strictly positive; `period_start` earlier than `period_end`); computed or system fields supplied as input are refused — all as `ERR_VALIDATION`.
4. **Existence.** Path identifiers resolve left to right, then body foreign keys resolve, and entity-backed callers resolve their `X-User-ID` to an interpreter record, else the matching not-found identifier from §2.8.
5. **State.** The target entity sits in a valid from-state for the requested transition (`ERR_INVALID_TRANSITION`); a new translation job additionally requires an `ACTIVE` document (`ERR_DOCUMENT_RETIRED`) and an `ACTIVE` contract (`ERR_CONTRACT_NOT_ACTIVE`).
6. **Compliance and safety gates, in this order.** Department `posture` must not be `NONCOMPLIANT` for new jobs or requests (`ERR_DEPARTMENT_NONCOMPLIANT`); an interpreter being assigned must be `ACTIVE` (`ERR_INTERPRETER_SUSPENDED`); their confidentiality must be current (`ERR_CONFIDENTIALITY_NOT_CURRENT`); translator and reviewer tiers must suffice (`ERR_TRANSLATOR_TIER_INSUFFICIENT`, `ERR_REVIEWER_TIER_INSUFFICIENT`); segregation of duties must hold (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); a `COURT` setting must be in person (`ERR_SETTING_REQUIRES_IN_PERSON`); and plan publication must have full certified-assessment coverage (`ERR_MISSING_CERTIFIED_ASSESSMENTS`).
7. **Temporal rules.** A `scheduled_start` in the past is `ERR_SCHEDULE_IN_PAST`; an in-person session with under two hours of lead is `ERR_LEAD_TIME_INSUFFICIENT`; an overlapping assessment window is `ERR_ASSESSMENT_PERIOD_OVERLAP`.
8. **Uniqueness.** A second `DRAFT` or `PUBLISHED` plan for the same `plan_year` is `ERR_PLAN_YEAR_CONFLICT`.
9. **Fiscal gates, checked last.** A new job's provisional commitment must fit under the contract ceiling, equality allowed (`ERR_CONTRACT_CEILING_EXCEEDED`); a request's estimated cost must fit within the department's `remaining_cents`, equality allowed (`ERR_DEPARTMENT_BUDGET_EXCEEDED`); and a department budget update may not set `annual_budget_cents` below the already-recorded `spent_cents` (`ERR_VALIDATION`).

## 3. Business Logic & Workflows

### 3.1. Departments, Budgets, and Compliance Posture

A `LanguageAccessCoordinator` onboards a department with its display `name`, the `service_area_code` it operates in, and an `annual_budget_cents` allocation for language services; `signage_status` may be supplied at creation and otherwise defaults to `CURRENT` (the recognized values are `CURRENT`, `DEFICIENT`, and `MISSING`). New departments begin with `spent_cents` at zero, a `compliance_score` of 1000 points, and a `posture` of `GOOD_STANDING`.

Spend is never entered by hand. A department's `spent_cents` accumulates the `final_cost_cents` of its `COMPLETED` interpretation requests plus the `final_cost_cents` of `APPROVED` translation jobs run against documents it owns, and it decreases when a substantiated complaint claws a request's cost back. `remaining_cents` is the read-only difference between `annual_budget_cents` and `spent_cents`, and it is the balance the dispatch workflow checks before committing an interpreter. Profile updates — a new `name`, `service_area_code`, `annual_budget_cents`, or `signage_status` — are Coordinator-only and guarded by the optimistic-concurrency rule of §2.7; the budget may never be lowered below the already-recorded `spent_cents`, a violation reported as `ERR_VALIDATION`.

The `compliance_score` is a chronological replay, not a running counter. Three event kinds feed it: a complaint adjudicated `SUBSTANTIATED` costs the department 150 points, timed at the complaint's `adjudicated_at`; an interpretation request that lands `UNFULFILLED` costs 50 points, timed at the request's `created_at`; and closing a `SUBSTANTIATED` complaint on time restores 100 points, timed at the complaint's `closed_at`. Recomputation sorts every event by its event timestamp in ascending order, breaking ties by the source record's own `created_at` (earliest first), starts the score at 1000, and applies each delta in turn with the running total clamped so it never falls below 0 or rises above 1000. The final score then derives `posture`: at least 800 is `GOOD_STANDING`, 600 through 799 is `WATCH`, and below 600 is `NONCOMPLIANT`. A `NONCOMPLIANT` department is barred from commissioning new translation jobs and from creating interpretation requests — both attempts fail with `ERR_DEPARTMENT_NONCOMPLIANT` — until remediation restores its standing.

### 3.2. Assessing Language Need and Publishing the Annual Plan

Before a plan cycle begins, each department's `DepartmentLiaison` files assessments describing the languages spoken in its service area. The creation payload names the owning `department_id` — which must be the liaison's own department, or the call fails with `ERR_FORBIDDEN_ROLE` — the `language_code` (an ISO 639 code such as "es"), the `plan_year` the assessment feeds, the coverage window `period_start` and `period_end`, and four counts: `lep_speaker_count` (limited-English-proficient speakers, zero or more), `service_area_population` (strictly positive), `encounter_count` (department encounters in this language during the window, zero or more), and `total_encounters` (all department encounters in the window, strictly positive). The window is half-open, running from `period_start` up to but not including `period_end`, and `period_start` must be strictly earlier than `period_end`. Two assessments for the same department and language may not have overlapping windows — abutting windows, where one ends exactly as the next begins, are permitted — and a violation is rejected with `ERR_ASSESSMENT_PERIOD_OVERLAP`.

Two shares are computed and stored on every new assessment, each rounded half up to four decimal places: `lep_share` is `lep_speaker_count` divided by `service_area_population`, and `encounter_share` is `encounter_count` divided by `total_encounters`. Threshold comparisons consume the rounded shares. From them come two booleans that may legitimately disagree on the same record: `threshold_language_safe` is true when the language's rounded share of the population is at least five percent or when at least 1,000 limited-English-proficient speakers live in the service area, and it drives the vital-document translation mandate; `priority_language` is true when the language's rounded share of encounters is at least five percent, and it drives prioritization inside the annual plan. New assessments land in `DRAFT` with `created_by_user_id` stamped from the caller's header.

Certification belongs to a `ComplianceOfficer`, who reviews a `DRAFT` assessment with a `decision` of `CERTIFY` or `REJECT`. Either path stamps `reviewed_by_user_id` from the caller; `REJECT` additionally requires a `rejection_note` in the payload (its absence is `ERR_VALIDATION`) and records the note on the assessment. Reviewing anything not in `DRAFT` is refused with `ERR_INVALID_TRANSITION`, and both `CERTIFIED` and `REJECTED` are terminal.

The annual plan itself is a Coordinator artifact: a draft `LanguageAccessPlan` carries a `plan_year` and an optional `summary`, and at most one plan per `plan_year` may exist among the `DRAFT` and `PUBLISHED` states — a conflicting creation fails with `ERR_PLAN_YEAR_CONFLICT`. Publication is gated on evidence: every department must hold at least one assessment whose `plan_year` matches the plan's `plan_year` by value (it is a year match, not a record reference) and whose status is `CERTIFIED`; otherwise publication fails with `ERR_MISSING_CERTIFIED_ASSESSMENTS`. A successful publication stamps `published_at` from the logical clock and moves the previously `PUBLISHED` plan, if any, to `SUPERSEDED`, which is terminal.

### 3.3. Vendor Contracts and the Rate Card

All vendor work bills against a contract. The Coordinator creates one with a `vendor_name`, a strictly positive `ceiling_cents`, and a rate card: `phone_per_minute_cents`, `video_per_minute_cents`, and `in_person_per_minute_cents` for session work, `translation_per_word_cents` for document work, and a flat `in_person_travel_flat_cents` fee added to in-person sessions — each rate zero or more. A contract begins in `DRAFT` with `committed_cents` and `spent_cents` at zero and becomes billable only when the Coordinator activates it, moving `DRAFT` → `ACTIVE`; activation from any other state is `ERR_INVALID_TRANSITION`.

Contract accounting is derivational, per the ledger principles of §2.9. `committed_cents` is the sum of `provisional_cost_cents` over the contract's translation jobs in `QUEUED`, `IN_TRANSLATION`, or `QUALITY_REVIEW`, plus the `estimated_cost_cents` of `ASSIGNED` interpretation requests whose interpreter bills to this contract. `spent_cents` is the sum of `final_cost_cents` over the contract's `APPROVED` jobs and its `COMPLETED` requests, excluding any request whose cost was clawed back through a refund. `available_cents` is the ceiling minus both pockets. A new commitment is admitted only while existing commitments plus settled spend plus the prospective amount still fit under the ceiling — an exact fit is allowed — so job creation that would overflow fails with `ERR_CONTRACT_CEILING_EXCEEDED`, while at dispatch an over-committed candidate is simply dropped from the eligible pool.

Exhaustion is automatic rather than declared: whenever `spent_cents` recomputes to at least ninety percent of `ceiling_cents`, the contract moves `ACTIVE` → `EXHAUSTED`. The transition immediately cancels every `QUEUED` translation job billed to the contract and releases each one's provisional commitment. `EXHAUSTED` is terminal and blocks all new commitments — new jobs are refused because the contract is not `ACTIVE`, and dispatch candidates billing to it are ineligible — but work already in flight, jobs in `IN_TRANSLATION` or `QUALITY_REVIEW` and `ASSIGNED` requests, still completes and adds to spend.

### 3.4. Vital Documents and the Translation Pipeline

The Coordinator registers each vital document with its owning `department_id`, a `title`, a `document_type` of `FORM`, `NOTICE`, `GUIDE`, or `POLICY`, and optionally a `base_language` that defaults to "en". Documents are born `ACTIVE` with an empty `translated_language_codes` list, and that list is thereafter maintained derivatively: the sorted, de-duplicated set of target languages from the document's `APPROVED` translation jobs, excluding any job that has since been `SUPERSEDED`.

Queuing a translation job takes the `document_id`, the `vendor_contract_id` to bill against, the `target_language_code`, a strictly positive estimated `word_count`, and an optional `rush` flag that defaults to false. Creation refuses a `RETIRED` document with `ERR_DOCUMENT_RETIRED`, a contract not in `ACTIVE` status with `ERR_CONTRACT_NOT_ACTIVE`, and a document-owning department in `NONCOMPLIANT` posture with `ERR_DEPARTMENT_NONCOMPLIANT`. The provisional price — `word_count` multiplied by the contract's `translation_per_word_cents` — is computed and stored as `provisional_cost_cents` and committed against the ceiling at creation, subject to the §3.3 ceiling gate (`ERR_CONTRACT_CEILING_EXCEEDED`). The job lands in `QUEUED`.

Assignment moves the job `QUEUED` → `IN_TRANSLATION` at the Coordinator's hand, naming a `translator_id` in the payload. The checks run in a fixed order: the job must be `QUEUED` (else `ERR_INVALID_TRANSITION`); the translator must reference an existing interpreter (`ERR_INTERPRETER_NOT_FOUND`); that interpreter must be `ACTIVE` (`ERR_INTERPRETER_SUSPENDED`); their confidentiality must be current, meaning `confidentiality_signed_at` is set to an instant no earlier than 365 days before the current logical time (`ERR_CONFIDENTIALITY_NOT_CURRENT`); the `target_language_code` must appear among the interpreter's `language_codes` (`ERR_VALIDATION`); and the interpreter's `tier` must be `REGISTERED` or `CERTIFIED` (`ERR_TRANSLATOR_TIER_INSUFFICIENT`). Success writes the translator onto the job.

Only the assigned translator may submit finished work — a caller whose identity differs from the job's `translator_id` is refused with `ERR_FORBIDDEN_ROLE` — declaring a strictly positive `submitted_word_count` (`ERR_VALIDATION` otherwise), which moves the job `IN_TRANSLATION` → `QUALITY_REVIEW`.

Review is performed by a `QualityReviewer` whose identity must resolve to an existing interpreter record (`ERR_INTERPRETER_NOT_FOUND`) holding the `CERTIFIED` tier (`ERR_REVIEWER_TIER_INSUFFICIENT`) and differing from the job's translator (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`); these reviewer preconditions apply identically to both review outcomes. A `decision` of `APPROVE` moves the job to `APPROVED`, stamps `reviewer_id` from the caller, and prices the job for settlement from four inputs — `submitted_word_count`, `revision_count`, `rush`, and the contract's per-word rate. The base is the submitted word count multiplied by the rate. A revision surcharge percentage is then taken as the lesser of ten percent per completed revision cycle and a hard cap of thirty percent; the surcharge amount — base times that percentage, rounded half up to whole cents — is added to the base. When `rush` is true the surcharged amount is multiplied by 1.25 and rounded half up again; otherwise the surcharged amount stands. The result, null until this moment, is stored as `final_cost_cents`. Settlement then moves money: the contract's `committed_cents` drops by the provisional amount while its `spent_cents` rises by the final, and the document-owning department's `spent_cents` absorbs the final as well. If the contract's spend thereby reaches at least ninety percent of its ceiling, contract exhaustion fires with its `QUEUED`-job cancellation cascade. Finally, any previously `APPROVED` job for the same document and target language becomes `SUPERSEDED` with its `superseded_by_job_id` pointing at the newly approved job, and the document's `translated_language_codes` is recomputed. A `decision` of `REQUEST_REVISION` instead loops the job `QUALITY_REVIEW` → `IN_TRANSLATION`, incrementing `revision_count` — zero when the job is first queued — by one while leaving the translator assignment unchanged.

Cancellation — invoked explicitly by the Coordinator or driven by system cascades such as document retirement and contract exhaustion — is permitted from `QUEUED`, `IN_TRANSLATION`, or `QUALITY_REVIEW`; from any other state it fails with `ERR_INVALID_TRANSITION`. Every such cancellation releases the job's provisional commitment from the contract's `committed_cents`. Retiring a document is a Coordinator action valid only from `ACTIVE` (else `ERR_INVALID_TRANSITION`) that lands the document in `RETIRED` and cascades exactly such a cancellation through every one of its jobs still in `QUEUED`, `IN_TRANSLATION`, or `QUALITY_REVIEW`, releasing each provisional commitment in turn.

### 3.5. The Interpreter Roster: Qualifications, Confidentiality, and Standing

The Coordinator adds an interpreter to the roster with a `full_name`, the `language_codes` they cover, the `modalities` they serve (any subset of `PHONE`, `VIDEO`, and `IN_PERSON`), a `tier` of `PROVISIONAL`, `REGISTERED`, or `CERTIFIED`, and the `vendor_contract_id` their work bills against. New interpreters arrive `ACTIVE` with a `quality_rating` of 1000, no confidentiality signature (`confidentiality_signed_at` null), and zero minutes banked for the current month.

Roster maintenance splits along role lines. The Coordinator may update the qualification fields — `full_name`, `language_codes`, `modalities`, `tier` — and may record a confidentiality signature: passing `confidentiality_signed` as true stamps `confidentiality_signed_at` with the current logical time, and true is the only accepted value (anything else is `ERR_VALIDATION`). A signature remains current for 365 days from its timestamp. Only a `ComplianceOfficer` may touch an interpreter's `status`; a Coordinator attempting it is refused with `ERR_FORBIDDEN_ROLE`.

Quality is recomputed by chronological replay, mirroring the department score. Completed sessions earn the interpreter 5 points each, timed at the request's `completed_at`; a substantiated complaint linked to one of the interpreter's requests costs 200 points, timed at the complaint's `adjudicated_at`. Recomputation sorts those events by their timestamps in ascending order, breaks ties by the source record's `created_at`, starts at 1000, and clamps each running step to the 0-to-1000 band. Whenever a recomputation lands below 600 on an `ACTIVE` interpreter, the system suspends them automatically — `ACTIVE` → `SUSPENDED` — and every `ASSIGNED` request they hold is cancelled, each cancellation releasing its `estimated_cost_cents` commitment from the interpreter's contract. A `ComplianceOfficer` may also suspend an `ACTIVE` interpreter by hand; a manual suspension changes only the status and does not cancel assigned work. Reinstatement — `SUSPENDED` → `ACTIVE`, again ComplianceOfficer-only — resets the `quality_rating` to a probationary floor of 600. Either manual transition attempted from the wrong state fails with `ERR_INVALID_TRANSITION`.

`minutes_current_month` sums the `actual_minutes` of the interpreter's `COMPLETED`, non-refunded requests whose `completed_at` falls inside the calendar month (UTC) of the current logical clock. It is the dispatch selector's first ranking key, favoring the least-loaded eligible interpreter.

### 3.6. On-Demand Interpretation: Dispatch, Delivery, and Settlement

A `DepartmentLiaison` requests an interpreter with the owning `department_id` (which must be the liaison's own department, else `ERR_FORBIDDEN_ROLE`), the `language_code`, the `modality` (`PHONE`, `VIDEO`, or `IN_PERSON`), the `encounter_setting` (`GENERAL`, `MEDICAL`, or `COURT`), and a strictly positive planned `scheduled_duration_minutes`. `scheduled_start` is optional for phone and video sessions, defaulting to the current logical time, and required for in-person sessions. No session may begin in the past relative to the logical clock (`ERR_SCHEDULE_IN_PAST`), and an in-person session needs at least two hours of lead time (`ERR_LEAD_TIME_INSUFFICIENT`). Court work must be face to face: a `COURT` setting paired with any modality other than `IN_PERSON` is rejected with `ERR_SETTING_REQUIRES_IN_PERSON`. And per §3.1, a `NONCOMPLIANT` department's request is refused with `ERR_DEPARTMENT_NONCOMPLIANT` before dispatch is ever attempted.

Creation synchronously runs the dispatch selector. The eligible pool contains every interpreter who meets all of the following: `ACTIVE` status; a confidentiality signature stamped no earlier than 365 days before the current logical time; coverage of the requested language; service of the requested modality; the tier rule — `CERTIFIED` for `COURT` or `MEDICAL` settings, any tier for `GENERAL`; freedom from buffered in-person conflicts, meaning that when the request is `IN_PERSON`, none of the candidate's `ASSIGNED` in-person sessions may interleave — a conflict exists when the new session's start is earlier than an existing session's end plus a thirty-minute buffer while that existing session's start minus thirty minutes is earlier than the new session's end, with a session's end defined as its `scheduled_start` plus its `scheduled_duration_minutes`; and a billing contract in `ACTIVE` status whose `available_cents` covers the session's estimated price computed against that contract's rate card and the candidate's own tier. Eligible candidates are ranked by `minutes_current_month` ascending, then `created_at` ascending, then `full_name` ascending, and the first-ranked candidate is selected. The department must then be able to afford the selection: `remaining_cents` at least equal to the estimate, an exact fit allowed, failing which the creation is rejected with `ERR_DEPARTMENT_BUDGET_EXCEEDED`.

Pricing follows a pinned five-step order in both its variants, and the rounding positions are part of the contract. First, the session length is rounded up to the next whole multiple of six minutes, and the billable minutes are the greater of that rounded length and the modality minimum — fifteen minutes for `PHONE`, fifteen for `VIDEO`, sixty for `IN_PERSON`. Second, the base is those billable minutes multiplied by the per-minute rate for the session's modality taken from the selected interpreter's contract rate card. Third, the base is multiplied by the tier multiplier — 0.85 for `PROVISIONAL`, 1.0 for `REGISTERED`, 1.15 for `CERTIFIED` — and the product is rounded half up to whole cents. Fourth, when the session is after-hours — its `scheduled_start` falls at a UTC hour earlier than 8 or at 18 or later, business hours running from 08:00 up to but not including 18:00 UTC — the tiered amount is multiplied by 1.5 and rounded half up again; within business hours the tiered amount stands. Fifth, the flat `in_person_travel_flat_cents` travel fee is added when the modality is `IN_PERSON`. The estimated variant runs these five steps over `scheduled_duration_minutes` at dispatch; the final variant runs them over `actual_minutes` at completion, so identical bookings price differently whenever a session runs long or short. After-hours is judged from `scheduled_start` in both variants.

When the pool is non-empty the request is born `ASSIGNED`: `interpreter_id` is set to the selection and `estimated_cost_cents` is computed and committed to the interpreter's contract. When the pool is empty the request is instead born `UNFULFILLED` — still a successful creation, returning the new record with `interpreter_id` and `estimated_cost_cents` null — and a 50-point compliance event is recorded against the department, timed at the request's `created_at`. `NEW` exists only transiently inside the creation call; `UNFULFILLED`, `COMPLETED`, and `CANCELLED` are the terminal states.

Completion belongs to the assigned interpreter alone — any other caller is refused with `ERR_FORBIDDEN_ROLE` — and requires a strictly positive `actual_minutes` (`ERR_VALIDATION` otherwise). The request becomes `COMPLETED`; `completed_at` is stamped from the logical clock; `final_cost_cents` is computed by the final variant and stored, having been null until now; the contract releases the estimate from `committed_cents` and adds the final to `spent_cents`; the department's `spent_cents` absorbs the final as well; and the interpreter's quality ledger gains its 5-point completion event, which the monthly-minutes derivation picks up from `actual_minutes`. Cancellation of an `ASSIGNED` request — by the liaison of the owning department (any other department is `ERR_FORBIDDEN_ROLE`), by the Coordinator, or by system cascade from an interpreter suspension — releases the estimated commitment from the contract; a request in any state other than `ASSIGNED` rejects the attempt with `ERR_INVALID_TRANSITION`.

### 3.7. Complaint Intake, Adjudication, and Remediation

Complaints enter through the liaison of the affected department — again scoped to their own department — or through a `ComplianceOfficer` staffing the intake desk. Intake records the `department_id`, an optional `interpretation_request_id` linking the complaint to a specific session, a `category` of `NO_INTERPRETER_AVAILABLE`, `POOR_QUALITY`, `CONFIDENTIALITY_BREACH`, `NOTICE_MISSING`, or `OTHER`, and a free-text `description`. The complaint lands in `RECEIVED` with `recorded_by_user_id` stamped from the caller.

Adjudication is ComplianceOfficer-only, and segregation of duties forbids the officer who recorded the complaint from adjudicating it: a caller whose identity matches `recorded_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`. Anything not in `RECEIVED` fails with `ERR_INVALID_TRANSITION`. The payload's `outcome` is `SUBSTANTIATED` or `DISMISSED`. Dismissal stamps `adjudicated_by_user_id` and `adjudicated_at` and terminates the complaint with no further effect. Substantiation stamps the same two fields, fixes a remediation deadline — `remediation_due_at` set thirty days after adjudication — and records an optional `remedy` of `NONE` or `REFUND`, where `REFUND` is accepted only when the complaint links to a request that is `COMPLETED` (otherwise `ERR_VALIDATION`).

Substantiation then cascades through the system. The department's compliance ledger takes a 150-point penalty event timed at `adjudicated_at`. A complaint in the `NOTICE_MISSING` category flips the department's `signage_status` to `DEFICIENT`. A linked session costs its interpreter a 200-point rating event timed at `adjudicated_at`, and if that recomputation drops an `ACTIVE` interpreter below 600, the auto-suspension of §3.5 fires with its request-cancellation cascade. A `REFUND` remedy subtracts the linked request's `final_cost_cents` from both the department's `spent_cents` and the billing contract's `spent_cents`, sets the request's `refund_clawed_back` flag (false on every request until this moment), and removes its minutes from the interpreter's monthly tally.

Closing a `SUBSTANTIATED` complaint requires a `resolution_note` (its absence is `ERR_VALIDATION`) and stamps `closed_at` from the logical clock, landing the complaint in `RESOLVED`. A close timed on or before `remediation_due_at` restores 100 compliance points at `closed_at`; a late close restores nothing. `RESOLVED` and `DISMISSED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created` — this includes interpretation-request creation whether the request lands `ASSIGNED` or `UNFULFILLED`. Operations that modify an existing resource return `200 OK`, as does the logical-clock setter. The table below summarizes the HTTP contract only; request fields, side effects, and guard conditions are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | LanguageAccessCoordinator |
| POST | `/departments` | Create a department | LanguageAccessCoordinator |
| GET | `/departments` | List departments (paginated) | All roles |
| GET | `/departments/{id}` | Get one department | All roles |
| PATCH | `/departments/{id}` | Update department profile, budget, or signage; OCC-guarded | LanguageAccessCoordinator |
| POST | `/language-assessments` | Create a language need assessment | DepartmentLiaison |
| GET | `/language-assessments` | List assessments with filters | All roles |
| GET | `/language-assessments/{id}` | Get one assessment | All roles |
| POST | `/language-assessments/{id}/review` | Certify or reject a DRAFT assessment | ComplianceOfficer |
| POST | `/vital-documents` | Register a vital document | LanguageAccessCoordinator |
| GET | `/vital-documents` | List vital documents | All roles |
| GET | `/vital-documents/{id}` | Get one vital document | All roles |
| POST | `/vital-documents/{id}/retire` | Retire a document; cancels its non-terminal jobs and releases their commitments | LanguageAccessCoordinator |
| POST | `/translation-jobs` | Queue a translation job; computes and commits the provisional cost | LanguageAccessCoordinator |
| GET | `/translation-jobs` | List translation jobs with filters | All roles |
| GET | `/translation-jobs/{id}` | Get one translation job | All roles |
| POST | `/translation-jobs/{id}/assign` | Assign a translator (QUEUED → IN_TRANSLATION) | LanguageAccessCoordinator |
| POST | `/translation-jobs/{id}/submit-translation` | Assigned translator submits work (IN_TRANSLATION → QUALITY_REVIEW) | Interpreter |
| POST | `/translation-jobs/{id}/review` | Quality review: approve and settle, or request a revision | QualityReviewer |
| POST | `/translation-jobs/{id}/cancel` | Cancel a non-terminal job; releases the provisional commitment | LanguageAccessCoordinator |
| POST | `/interpreters` | Add an interpreter to the roster | LanguageAccessCoordinator |
| GET | `/interpreters` | List interpreters with filters | All roles |
| GET | `/interpreters/{id}` | Get one interpreter | All roles |
| PATCH | `/interpreters/{id}` | Update qualifications or status; record a confidentiality signature | LanguageAccessCoordinator, ComplianceOfficer |
| POST | `/interpretation-requests` | Create an on-demand request; synchronously runs the dispatch selector | DepartmentLiaison |
| GET | `/interpretation-requests` | List interpretation requests with filters | All roles |
| GET | `/interpretation-requests/{id}` | Get one interpretation request | All roles |
| POST | `/interpretation-requests/{id}/complete` | Assigned interpreter completes the session with actual minutes | Interpreter |
| POST | `/interpretation-requests/{id}/cancel` | Cancel an ASSIGNED request; releases the commitment | DepartmentLiaison, LanguageAccessCoordinator |
| POST | `/complaints` | Intake a language-access complaint | DepartmentLiaison, ComplianceOfficer |
| GET | `/complaints` | List complaints with filters | All roles |
| GET | `/complaints/{id}` | Get one complaint | All roles |
| POST | `/complaints/{id}/adjudicate` | Substantiate or dismiss a RECEIVED complaint | ComplianceOfficer |
| POST | `/complaints/{id}/close` | Close a SUBSTANTIATED complaint | ComplianceOfficer |
| POST | `/vendor-contracts` | Create a vendor contract with its rate card | LanguageAccessCoordinator |
| GET | `/vendor-contracts/{id}` | Get one vendor contract | All roles |
| POST | `/vendor-contracts/{id}/activate` | Activate a DRAFT contract | LanguageAccessCoordinator |
| POST | `/language-access-plans` | Create a draft annual language access plan | LanguageAccessCoordinator |
| GET | `/language-access-plans/{id}` | Get one plan | All roles |
| POST | `/language-access-plans/{id}/publish` | Publish a plan; supersedes the previously published plan | LanguageAccessCoordinator |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_DEPARTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_JOB_NOT_FOUND` | 404 Not Found |
| `ERR_INTERPRETER_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DOCUMENT_RETIRED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_DEPARTMENT_NONCOMPLIANT` | 409 Conflict |
| `ERR_PLAN_YEAR_CONFLICT` | 409 Conflict |
| `ERR_MISSING_CERTIFIED_ASSESSMENTS` | 409 Conflict |
| `ERR_INTERPRETER_SUSPENDED` | 409 Conflict |
| `ERR_ASSESSMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CONFIDENTIALITY_NOT_CURRENT` | 409 Conflict |
| `ERR_SETTING_REQUIRES_IN_PERSON` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_TRANSLATOR_TIER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_REVIEWER_TIER_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_LEAD_TIME_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CONTRACT_CEILING_EXCEEDED` | 402 Payment Required |
| `ERR_DEPARTMENT_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

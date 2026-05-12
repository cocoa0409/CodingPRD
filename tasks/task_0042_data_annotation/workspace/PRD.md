# Data Annotation Crowdsourcing API — Product Requirements Document

## 1. Introduction

Modern machine-learning teams depend on labelled corpora produced by distributed annotator workforces, and the operational complexity of such workforces — from defining what "correct" means to paying piece-rate wages without paying for rejected work — has historically been absorbed by ad-hoc spreadsheets and manual reconciliation. This document specifies a crowdsourcing platform that consolidates the full lifecycle of an annotation project: defining the task, splitting raw data into uniformly sized work packages, routing those packages to qualified annotators, inspecting the result, paying for the result, and resolving disputes. The system supports six annotation modalities — image classification, bounding boxes, semantic segmentation, keypoint marking, text named-entity recognition, and audio transcription — and treats each modality uniformly under a single pricing, quality, and arbitration model.

The platform is built around three peer roles. A `ProjectManager` configures projects, registers annotators, and runs payroll. A `QAReviewer` inspects submitted work and routes it to approval, rework, or arbitration. An `Annotator` is a crowdsourced contributor identified by an `AnnotatorProfile` who claims packages, submits labels, and — when sufficiently senior — acts as arbiter. The platform's discriminating mechanics are tier-aware quality inspection (low-tier annotators get full inspection, high-tier annotators get sampled inspection augmented by golden samples), pass-rate-driven bonuses and penalties, and a withholding settlement model that prevents paying out wages that may be reversed by a pending appeal.

The downstream contract surface — payment, instant-messaging, and storage — is reached only through queued events, so this API is the single source of truth for annotation state, and its tests assert that every state-bearing transition emits the expected event and audit-log row at the moment the transition commits.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, an opaque or entity-bound identifier for the actor, and `X-User-Role`, a string drawn from the role enumeration defined below. A request missing either header — or carrying an empty value for either — is rejected with `ERR_MISSING_AUTH_HEADERS`. A request whose `X-User-Role` is not authorised to perform the requested operation per the §4 endpoint table is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The role enumeration consists of exactly three names, each spelled as shown:

- `ProjectManager` — owns project lifecycle, package splitting and dispatch, annotator registration, appeal arbiter assignment, and payroll. When `X-User-Role` is `ProjectManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it in audit-log rows (the `actor_id` field on `AuditLog`) but does not compare it to any entity's `id`.
- `QAReviewer` — drives the quality-inspection lifecycle: starting inspections and finalising them with `PASS` or `FAIL`. When `X-User-Role` is `QAReviewer`, `X-User-ID` is likewise an opaque operator identifier, recorded in audit logs but not compared to any entity's `id`.
- `Annotator` — a crowdsourced contributor backed by an `AnnotatorProfile`. When `X-User-Role` is `Annotator`, `X-User-ID` is the `id` of the acting `AnnotatorProfile`; ownership checks on any resource that references an `AnnotatorProfile` (for example, the `assigned_annotator_id` of a `TaskPackage`, the `annotator_id` on an `Appeal`, or the `arbiter_id` on an `Appeal`) compare the resource's foreign-key field to `X-User-ID`. An `Annotator` may also be the acting arbiter when their tier is `EXPERT`; the arbiter check still resolves through `X-User-ID`.

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. The default `limit` is 10; the minimum is 1; the maximum is 100. The default `offset` is 0; the minimum is 0; there is no upper bound. Any request whose `limit` falls outside the closed interval from 1 to 100, or whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`.

List endpoints sort their results by `created_at` ascending. The pagination block on the `meta` of a list response carries exactly four fields — `limit`, `offset`, `total_count` (the total number of records matching the filter, ignoring `limit` and `offset`), and `has_more` (true when `offset + limit < total_count`).

### 2.4. Identifiers, Timestamps, and Common Resource Properties

Every resource the API mints carries an `id` that is a server-allocated UUID expressed without any type prefix. Clients must never supply an `id`; any `id` provided in a request body is ignored.

Most resources additionally carry three system-managed fields. The `created_at` timestamp is set when the resource is first persisted and never changes thereafter. The `updated_at` timestamp is set to the same value as `created_at` at creation and is refreshed to the current server time on every mutation that the server commits to that resource. The `version` is an integer that begins at 1 on creation and is incremented by exactly 1 on every mutation that the server commits to that resource. All three fields appear on `AnnotationProject`, `TaskPackage`, `AnnotatorProfile`, `QualityInspection`, `Appeal`, and `PayrollPeriod`.

Five resources are deliberately leaner. `GoldenSample`, `AnnotationSubmission`, `SalaryLedgerEntry`, `AuditLog`, and `ExternalEvent` carry only `id` and `created_at`; for these five resources the `updated_at` and `version` fields are absent because they are immutable once written — a `GoldenSample` is replaced rather than edited, an `AnnotationSubmission` is rewritten by submitting again, a `SalaryLedgerEntry` is offset by booking a compensating entry, and audit-log and external-event rows are append-only.

All timestamps emitted by the API — `created_at`, `updated_at`, `claimed_at`, `deadline_at`, `last_evaluated_at`, `opens_at`, `closes_at`, and the `meta.api_request_timestamp` — use the same ISO 8601 UTC format with three fractional digits.

### 2.5. Optimistic Concurrency Control

Mutating endpoints that accept a `version` field (see §4 — currently the project `PATCH`) treat that field as optional. When a request body omits `version` or sends an explicit JSON null, the server skips the version check and proceeds with the update. When a request body supplies a `version` value, the server compares it against the current `version` of the target resource; if the two do not match, the request is rejected with `ERR_VERSION_CONFLICT` and no mutation is applied. On a successful mutation the resource's `version` increments by 1 and `updated_at` is refreshed to the current server time.

### 2.6. Numeric Precision and Rounding

All currency-bearing fields on `SalaryLedgerEntry` are recorded in integer cents. Every monetary calculation that is composed of multiplications by floating-point multipliers — piece-rate amounts, bonus amounts, penalty amounts, taxes — is reduced to an integer cents value by the round-half-up rounding rule, in which a fractional cent of exactly 0.5 always rounds upward in magnitude. The pinned rounding step for piece rate is per item: each item's per-item rate is rounded to integer cents first, and the package's gross amount is the rounded per-item value multiplied by the item count. The bonus and penalty entries multiply the gross by the bonus or penalty rate and round once.

All quality-related rates — `pass_rate` on `QualityInspection`, `rolling_pass_rate`, `lifetime_pass_rate`, and `golden_hit_rate` on `AnnotatorProfile`, and the consistency score persisted on a package — are stored at four decimal places using the same round-half-up rule.

Sample sizes are integers; the senior and expert sampling rules round upward to the next whole item.

### 2.7. Hierarchical Consistency, Cascades, and Audit

Many operations on this platform mutate more than one resource. When a `TaskPackage` transitions out of `INSPECTING`, the side effects span the package itself, the inspecting annotator's `AnnotatorProfile` counters, possibly the `AnnotatorProfile.status`, the `SalaryLedgerEntry` table, and the `ExternalEvent` queue. When an appeal is upheld, the side effects cross both the originating `QualityInspection` row and the `SalaryLedgerEntry` rows that were booked from it. The principles below govern every such cascade.

- Every server-committed mutation refreshes `updated_at` and increments `version` on the directly mutated resource. When a parent resource's state changes because of a child mutation (for example, when a forced re-allocation changes a `TaskPackage` because its annotator was suspended), the `version` and `updated_at` on each independently mutated resource each move once per commit.
- Every state transition that touches a `TaskPackage` writes one `AuditLog` row of `event_type` equal to `STATUS_CHANGE`, with `subject_kind` set to `TASK_PACKAGE`, `subject_id` set to the package id, `from_value` set to the prior state name and `to_value` set to the new state name. Every `SalaryLedgerEntry` insertion that materially adjusts an annotator's running balance — including the `TAX` entries written at settlement and the `ADJUSTMENT_UPHELD` and `ADJUSTMENT_REJECTED` entries written by appeal decisions — writes one `AuditLog` row with `event_type` equal to `SALARY_ADJUSTMENT`, `subject_kind` equal to `SALARY`, `subject_id` equal to the ledger entry id, `from_value` recording the prior signed amount string (or null for creation), and `to_value` recording the new signed amount string. For audit-log rows produced by the system itself (for example, the timeout reclamation triggered by clock advance), `actor_id` and `actor_role` are both the literal string `"system"`.
- External events are queued synchronously on the triggering transition. The `ExternalEvent` row is written with `dispatch_status` equal to `PENDING` inside the same commit that performs the state transition, with `target_system` and `event_type` set as documented per transition and `payload_ref_id` set to the id of the entity that produced the event. A separate test-driving capability flips queued events to `DISPATCHED` so that tests can observe the transition.

### 2.8. Path Hierarchy and Existence Checks

The path of every nested resource is validated left-to-right: a request to `/annotation-projects/{projectId}/task-packages/{packageId}/inspections/{inspectionId}/finalize` validates the project id first and rejects with `ERR_PROJECT_NOT_FOUND` if it does not resolve, then the package id (rejecting with `ERR_PACKAGE_NOT_FOUND`), then the inspection id (rejecting with `ERR_INSPECTION_NOT_FOUND`). Project, annotator, appeal, payroll-period, and golden-sample existence likewise produce `ERR_PROJECT_NOT_FOUND`, `ERR_ANNOTATOR_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_PERIOD_NOT_FOUND`, and `ERR_GOLDEN_NOT_FOUND` respectively. Existence (priority 3) is evaluated after authentication (priority 1) and authorization (priority 2) but before any state, business, or constraint check.

### 2.9. Validation Priority Ordering

The global validation pipeline is strictly ordered, and the first failing rule is the rule that determines the rejection. Authentication is checked first — missing headers yield `ERR_MISSING_AUTH_HEADERS`. Authorization is second — a role mismatch yields `ERR_INSUFFICIENT_PERMISSIONS`. Path-resolution existence is third. Project lifecycle state (`ERR_PROJECT_NOT_OPEN`, `ERR_PROJECT_NOT_DRAFT`, `ERR_PROJECT_NOT_CLOSED`) is fourth. Target-resource state (`ERR_PACKAGE_STATE_INVALID`, `ERR_INSPECTION_STATE_INVALID`, `ERR_APPEAL_STATE_INVALID`, `ERR_PERIOD_STATE_INVALID`) is fifth. Annotator suspension is sixth — the rejection code is `ERR_ANNOTATOR_SUSPENDED`. Tier sufficiency is seventh — the rejection code is `ERR_TIER_INSUFFICIENT`. Distribution-mode permission is eighth — the rejection codes are `ERR_GRAB_NOT_ALLOWED` and `ERR_DISPATCH_NOT_ALLOWED`. Submission ownership is ninth — the rejection code is `ERR_NOT_PACKAGE_OWNER`. Submission deadline is tenth — `ERR_PACKAGE_TIMED_OUT`. Label-count match is eleventh — `ERR_LABEL_COUNT_MISMATCH`. The remaining business and parameter checks (golden-count minimum, task-package-count minimum, arbiter-not-owner, period-not-due, settle re-inspection guard, parameter ranges, defect-range, period overlap, claim-already-taken, pagination range, and version conflict) are evaluated in the priority order above. A failure earlier in the list always masks a failure later in the list.

### 2.10. Quality, Pricing, and Tier Thresholds

The quality, pricing, and tier system is anchored on a small catalogue of constants whose names recur throughout §3:

- The minimum number of golden samples required before a project can be opened is 5 (the `GoldenSample` count threshold).
- The proportion of items in any package that are golden samples is 5 percent, taken as a floor — a package of 19 items therefore receives no golden samples.
- The maximum permissible defect rate before an inspection fails is 10 percent of the inspected sample.
- The maximum number of completed rework rounds before a third failure escalates to arbitration is 2.
- The bonus band is a 5-percentage-point margin above the project's pass-rate target; the penalty band is a 10-percentage-point margin below it.
- The bonus rate applied to the gross piece-rate amount is 10 percent; the penalty rate is 20 percent. The flat penalty for arbitration rejection is 200 cents. The flat penalty for a rejected appeal is 100 cents.
- Promotion to `SENIOR` requires a rolling pass rate at or above 0.85, a golden-hit rate at or above 0.85, and at least 20 lifetime submitted packages. Promotion to `EXPERT` requires a rolling pass rate at or above 0.95, a golden-hit rate at or above 0.95, and at least 50 lifetime submitted packages.
- Suspension is automatic when the rolling pass rate falls below 0.70 or the golden-hit rate falls below 0.60.
- The rolling-pass-rate window is the most recent 20 submitted packages.
- The repeated-dispute pattern threshold is 3 rejected appeals over the trailing 20 packages.

## 3. Business Logic & Workflows

### 3.1. Project Definition and the Path to OPEN

A `ProjectManager` initiates a project by creating an `AnnotationProject`, supplying its `project_name`, the `task_type` from the enumeration `CLASSIFICATION`, `BBOX`, `SEGMENTATION`, `KEYPOINT`, `TEXT_NER`, or `AUDIO_TRANSCRIPTION`, the `difficulty` from `EASY`, `MEDIUM`, or `HARD`, the `guideline_doc_url` pointing to the annotation-guideline document, a non-empty array `sample_preview_urls` of preview URLs, the `package_size` of items per `TaskPackage` (an integer between 10 and 500 inclusive), the `distribution_mode` from `GRAB`, `DISPATCH`, or `HYBRID`, the `unit_price_cents` base unit price per item at `EASY` difficulty, and the `pass_rate_target` (greater than zero and at most 1) used for bonus and penalty computation. An optional `timeout_seconds` controls the per-package deadline; when omitted it defaults to 86400 seconds (24 hours), and when supplied it must be at least 60 seconds. A request that violates any of these ranges is rejected with `ERR_INVALID_PARAMETER`. The newly created project enters `DRAFT` status with `golden_sample_count` set to zero.

While in `DRAFT`, a project's editable fields — `guideline_doc_url`, `sample_preview_urls`, `unit_price_cents`, `pass_rate_target`, `timeout_seconds`, `package_size`, and `distribution_mode` — may be updated through the project edit operation, which requires the `version` field for the optimistic-concurrency check described in §2.5. Any edit attempt outside `DRAFT` is rejected with `ERR_PROJECT_NOT_DRAFT`.

A project's data set is divided into work packages by the splitting capability, which accepts a `total_item_count` and creates the ceiling of `total_item_count` divided by `package_size` `TaskPackage` rows numbered by `batch_no` from 1 upward. Each new package's `item_count` equals the project's `package_size`, except the last batch which carries the remainder. Splitting is allowed in either `DRAFT` or `OPEN`, and every newly created package starts in `POOL` status with no `assigned_annotator_id`, no `claimed_at`, no `deadline_at`, and `rework_round` equal to zero.

Golden samples are added one at a time to the project, each with its `payload_url` and an `expected_label` payload that the inspector treats as ground truth, recorded against the owning project's `project_id`; each insertion increments `project.golden_sample_count` and queues a `STORAGE` event of `event_type` `golden_sample.uploaded`.

Opening the project — transitioning `status` from `DRAFT` to `OPEN` — is the gate at which the project's preconditions are enforced. The `guideline_doc_url` must be non-empty (else `ERR_GUIDELINE_REQUIRED`); the `sample_preview_urls` must contain at least one entry (else `ERR_SAMPLE_PREVIEW_REQUIRED`); the count of `GoldenSample` rows attached to the project must be at least 5 (else `ERR_GOLDEN_SAMPLES_INSUFFICIENT`); and at least one `TaskPackage` must already exist for the project (else `ERR_NO_TASK_PACKAGES`). When the transition commits, every `TaskPackage` on the project has its `tier_required` initialised — `EASY` projects mark their packages as requiring `JUNIOR`, `MEDIUM` projects as requiring `SENIOR`, and `HARD` projects as requiring `EXPERT`. The transition queues a `STORAGE` event of `event_type` `project.opened` carrying the project id.

### 3.2. Annotator Onboarding and Tiering

A `ProjectManager` registers a new annotator by supplying a `display_name`, an array `domain_tags` of skill tags (for example `["medical", "automotive"]`), and an entry-test result `entry_test_score` between 0 and 100 inclusive. The newly created `AnnotatorProfile` enters `ACTIVE` status. Its starting `tier` is derived from the entry-test score: a score of 95 or higher mints an `EXPERT`, a score of 80 or higher (but below 95) mints a `SENIOR`, and any lower score mints a `JUNIOR`. To prevent the suspension cascade from auto-firing on a brand-new annotator who has never been seen, `lifetime_pass_rate`, `rolling_pass_rate`, and `golden_hit_rate` all start at 1.0 and `last_evaluated_at` is null until the first re-evaluation runs.

Tier rank is a strict three-step ordering: `JUNIOR` is rank 1, `SENIOR` is rank 2, `EXPERT` is rank 3. An annotator may take a package only when their tier rank is at least the package's required tier rank — a `SENIOR` may take a package marked `JUNIOR` or `SENIOR` but not `EXPERT`, and an `EXPERT` may take any package. Failures of this comparison are rejected with `ERR_TIER_INSUFFICIENT`.

Tier is recomputed by the re-evaluation operation, which is invoked explicitly by a `ProjectManager` and implicitly after every quality-inspection finalise. The recomputed tier is the highest tier whose conditions are satisfied. The annotator becomes `EXPERT` when the rolling pass rate is at least 0.95 and the golden-hit rate is at least 0.95 and the lifetime submitted-package count is at least 50. The annotator becomes `SENIOR` when the rolling pass rate is at least 0.85 and the golden-hit rate is at least 0.85 and the lifetime submitted-package count is at least 20. Otherwise the annotator is `JUNIOR`. All four comparisons use the inclusive at-least relation, so values exactly on a threshold qualify; an annotator with a rolling pass rate of exactly 0.85, a golden-hit rate of exactly 0.85, and exactly 20 submitted packages is `SENIOR`. Demotion is the converse — a metric drop that breaks the band of the current tier moves the annotator to the highest band whose conditions still hold, cascading down to `JUNIOR` if necessary. Each re-evaluation refreshes `last_evaluated_at` to the current server time.

A suspension overlay rides above the tier ladder. If at any point the rolling pass rate is below 0.70 or the golden-hit rate is below 0.60, the annotator is suspended: `tier` is forced to `JUNIOR`, `status` transitions from `ACTIVE` to `SUSPENDED`, every `TaskPackage` whose `assigned_annotator_id` is this annotator and whose status is either `IN_PROGRESS` or `REWORK_PENDING` is reverted to `POOL` (its `assigned_annotator_id`, `claimed_at`, and `deadline_at` are all set to null), and an `IM` event of `event_type` `annotator.suspended` is queued. Reinstatement by a `ProjectManager` puts the annotator back into `ACTIVE`; the underlying counters are not reset, so a further metric breach can re-suspend the same annotator.

The rolling and lifetime pass-rate computation has two variants. The default — what suspension and tier recomputation read — is the chronological running aggregator: on each inspection finalise, the submitted counter increments by 1 in commit order, and the approved counter increments by 1 if the outcome resolves to `APPROVED` (including via an upheld appeal), and the rates are computed from the running counters. The forward-looking variant scans every `QualityInspection` row for the annotator and treats the latest appeal decision per inspection as the truth, so an upheld appeal that overrides an earlier `FAIL` is reflected immediately in the projected rates. The forward-looking variant is exposed only through the projected-pass-rate read and is the only place where it is honoured; an appeal that is upheld after a tier recomputation has already booked the failure does not retroactively change the chronological rate but is visible in the projected-pass-rate view immediately. `lifetime_pass_rate` is updated only when a package reaches `APPROVED`. The window for `rolling_pass_rate` is the most recent 20 submitted packages. Both rates are stored at four decimal places with round-half-up.

The golden-hit rate divides the total of every submission's `golden_correct` by the total of every submission's `golden_total` across all submissions ever made by the annotator. When the cumulative `golden_total` is zero — for example because every package the annotator has ever submitted had fewer items than the threshold below which no golden samples are inserted — the rate is presumed to be 1.0; this is the deliberate empty-set boundary that prevents brand-new annotators from being suspended on no evidence. The rate is stored at four decimal places with round-half-up.

### 3.3. Distribution: Claiming and Dispatching

How a `POOL` package leaves the pool is controlled by the project's `distribution_mode`. A `GRAB` project allows an `Annotator` to self-claim. A `DISPATCH` project requires a `ProjectManager` to push a package to a specific annotator. A `HYBRID` project allows both. A claim attempt against a project whose mode is `DISPATCH` is rejected with `ERR_GRAB_NOT_ALLOWED`; a dispatch attempt against a project whose mode is `GRAB` is rejected with `ERR_DISPATCH_NOT_ALLOWED`.

Both forms drive the same `POOL → IN_PROGRESS` transition. The project must be in `OPEN` status (else `ERR_PROJECT_NOT_OPEN`). The acting annotator — for a claim, the `AnnotatorProfile` whose id matches `X-User-ID`; for a dispatch, the annotator whose id is supplied as `annotator_id` in the request body — must be in `ACTIVE` status (else `ERR_ANNOTATOR_SUSPENDED`) and must have a tier rank at least equal to the package's `tier_required` rank (else `ERR_TIER_INSUFFICIENT`). The package itself must currently have a null `assigned_annotator_id`; if a competing writer has already filled it, the request is rejected with `ERR_PACKAGE_ALREADY_TAKEN`.

When the transition commits, the package's `assigned_annotator_id` is set to the acting (or dispatched) annotator's id, `claimed_at` is set to the current server time, and `deadline_at` is set to `claimed_at` plus the project's `timeout_seconds`. Golden samples are inserted into the package by drawing the floor of `item_count` multiplied by 0.05 entries from the project's `GoldenSample` pool; the number drawn is recorded as `golden_inserted_count` on the package. When `item_count` is below 20, this product floors to zero and the package contributes nothing to its annotator's `golden_hit_rate`.

When two annotators race to claim the same `POOL` package simultaneously, the platform's serialisation guarantee is first-writer-wins on `assigned_annotator_id`: at most one writer becomes the assignee, and the loser's request aborts with `ERR_PACKAGE_ALREADY_TAKEN` and HTTP status 409. The same code applies to a dispatch that loses to an in-flight claim, or vice versa. There is also a serialisation interaction with re-evaluation: if a re-evaluation auto-suspends the same annotator who is mid-claim on a different package, the order of writes on `AnnotatorProfile.status` is what decides which side wins — if the claim handler reads a post-write `SUSPENDED` status it rejects with `ERR_ANNOTATOR_SUSPENDED`, and otherwise the claim commits before the suspension cascade runs.

### 3.4. Submission, Inspection, and Outcome

The acting `Annotator` advances the package from `IN_PROGRESS` to `SUBMITTED` by submitting `labels`, an array of per-item label payloads. Three preconditions guard submission: the acting annotator must be `package.assigned_annotator_id` (else `ERR_NOT_PACKAGE_OWNER`), the length of `labels` must equal `package.item_count` (else `ERR_LABEL_COUNT_MISMATCH`), and the current server time must be strictly less than `deadline_at` (else `ERR_PACKAGE_TIMED_OUT`). When the submission commits, an `AnnotationSubmission` row is created carrying `package_id`, `annotator_id`, `rework_round` (matching the package's current `rework_round` at submit time), the supplied `labels`, and computed `golden_correct` and `golden_total` counts where `golden_correct` is the number of items labelled identically to the matching `GoldenSample.expected_label` and `golden_total` matches the package's `golden_inserted_count` at submission time. When two or more submissions exist on the same package across rework rounds, the consistency score is computed and persisted on the package as a derived helper field exposed at read time.

A `QAReviewer` advances the package from `SUBMITTED` to `INSPECTING` by starting the inspection. This commits a new `QualityInspection` row whose `package_id` references the package, whose `submission_id` references the most recent `AnnotationSubmission`, whose `inspector_id` is recorded as the operator id, and whose `sample_size` is computed by the tier rule below. A `JUNIOR` annotator's submission receives full inspection — `sample_size` equals `item_count`. A `SENIOR` annotator's submission is sampled at 30 percent — `sample_size` is the ceiling of 0.30 multiplied by `item_count`. An `EXPERT` annotator's submission is sampled at 10 percent — `sample_size` is the ceiling of 0.10 multiplied by `item_count`. A 10-item `EASY` package submitted by an `EXPERT` therefore samples 1 item (the ceiling of 1.0).

The inspection is finalised with two body fields: `outcome` (either `PASS` or `FAIL`) and `defects_found` (the number of items the inspector marked wrong). The `defects_found` value must be between 0 and `sample_size` inclusive; out-of-range values are rejected with `ERR_DEFECTS_OUT_OF_RANGE`. The `pass_rate` field on the `QualityInspection` is computed at finalise time as 1 minus `defects_found` divided by `sample_size`, rounded to four decimal places with round-half-up. The package's destination state depends on the resulting defect ratio and on rework history.

When `defects_found` divided by `sample_size` is at most 0.10, the inspection's `outcome` resolves to `PASS` and the package transitions from `INSPECTING` to `APPROVED`. The annotator's `submitted_count` and `approved_count` both increment by 1. A piece-rate `SalaryLedgerEntry` is created (kind `PIECE_RATE`, `settlement_state` `WITHHELD`, signed `gross_amount_cents` computed by §3.6's piece-rate calculation). A bonus or penalty entry is created when applicable (kind `BONUS` with positive amount, or kind `PENALTY` with negative amount), again with `settlement_state` `WITHHELD`. An `IM` event of `event_type` `package.approved` and a `STORAGE` event of `event_type` `package.approved` are queued. An audit-log row of `event_type` `STATUS_CHANGE` records the transition.

When `defects_found` divided by `sample_size` exceeds 0.10, the path forks on rework history. If the package's `rework_round` plus 1 is at most 2 (the maximum), the package transitions from `INSPECTING` to `REWORK_PENDING`: `rework_round` increments by 1 (this `INSPECTING` evaluation counts as a completed round), the annotator's `submitted_count` increments by 1 but `approved_count` does not, and a `STATUS_CHANGE` audit row is written. If `rework_round` plus 1 would exceed 2, the package transitions from `INSPECTING` to `ARBITRATING` instead: the just-finalised inspection's `outcome` is overwritten to `DISPUTED` to record the override, and an expert arbiter is selected by the rule in §3.8.

A package that has reached `REWORK_PENDING` returns to `IN_PROGRESS` either through rework-claim by the original owner, which resets `claimed_at` and `deadline_at` for a fresh attempt, or — if that owner has been suspended — through rework-dispatch by a `ProjectManager`, which empties `assigned_annotator_id` and pushes the package back to `POOL` for re-grab. Rework-claim requires the acting annotator to match the original `assigned_annotator_id`. Both operations are guarded by the standard annotator-suspension rule: a suspended annotator cannot claim or rework-claim, and the rejection code is `ERR_ANNOTATOR_SUSPENDED`.

### 3.5. Timeouts and the Logical Clock

Every claimed package carries a hard deadline. When the system's logical clock advances past `deadline_at` while the package is still `IN_PROGRESS`, the package automatically reverts to `POOL`: `assigned_annotator_id`, `claimed_at`, and `deadline_at` are all set to null, and the annotator's `lifetime_pass_rate` and `rolling_pass_rate` are NOT changed because no submission exists for that round. The reclamation is driven by an admin-only test-driving capability that advances the logical clock to a supplied `to` instant; on that advance, every `TaskPackage` whose status is `IN_PROGRESS` and whose `deadline_at` is at or before the new now is reverted in this fashion.

A second test-driving capability flushes queued external events: it sets `dispatch_status` from `PENDING` to `DISPATCHED` for every queued `ExternalEvent`. These two capabilities are restricted to `ProjectManager`.

### 3.6. Pricing, Bonuses, and Penalties

Piece-rate compensation runs on every transition to `APPROVED` — whether reached directly from `INSPECTING`, from `ARBITRATING` by an upholding arbiter decision, or from a rejected package promoted by an upheld appeal. The computation reads four inputs: the project's `unit_price_cents` as the base unit price, the package's `item_count`, the project's `difficulty`, and the annotator's current `tier`. A difficulty multiplier is applied — 1.00 at `EASY`, 1.50 at `MEDIUM`, 2.00 at `HARD`. A tier multiplier is applied — 0.80 at `JUNIOR`, 1.00 at `SENIOR`, 1.20 at `EXPERT`. The per-item rate before rounding is the base unit price multiplied by the difficulty multiplier multiplied by the tier multiplier. The rounding order is pinned: each item's rate is rounded to integer cents first using round-half-up, and the package's `gross_amount_cents` is the rounded per-item value multiplied by `item_count`. This pinning is deliberate — two identical inputs always produce the same ledger amount — and it differs from the alternative of summing first and rounding once at the end.

Immediately after the `PIECE_RATE` entry is written, a bonus-or-penalty evaluation runs. The package's pass rate — 1 minus `defects_found` divided by `sample_size` — is compared against the project's `pass_rate_target`. When the package pass rate is at or above the target plus 0.05 (the bonus band), a `SalaryLedgerEntry` of kind `BONUS` is written with `gross_amount_cents` equal to the round-half-up of the gross piece-rate amount multiplied by 0.10; the comparison is inclusive, so a package pass rate exactly equal to the target plus 0.05 triggers the bonus. When the package pass rate is at or below the target minus 0.10 (the penalty band), a `SalaryLedgerEntry` of kind `PENALTY` is written with `gross_amount_cents` equal to the negative of the round-half-up of the gross piece-rate amount multiplied by 0.20. Otherwise no bonus or penalty entry is written. Both `BONUS` and `PENALTY` entries enter `WITHHELD` settlement state alongside the originating `PIECE_RATE` entry.

When an arbiter rejects a package — moving it from `ARBITRATING` to `REJECTED` — the annotator receives no piece-rate credit and is debited a flat 200 cents in a `PENALTY` entry. When an arbiter upholds an appeal that reverses a rejected outcome, the platform inserts an `ADJUSTMENT_UPHELD` entry whose magnitude exactly offsets the original penalty entries booked from the disputed inspection, so that for that inspection the sum of the penalty debits and the upholding adjustment credits is zero. The package status is promoted from `REJECTED` to `APPROVED` if applicable, and the piece-rate entry that the rejected outcome had withheld is created with `settlement_state` `WITHHELD`. When an arbiter rejects an appeal as unfounded, the appellant is debited a flat 100 cents in an `ADJUSTMENT_REJECTED` entry; if that annotator has accumulated 3 or more rejected appeals over the trailing 20 packages, the suspension cascade fires and the annotator is moved to `SUSPENDED` via the standard suspension transition.

### 3.7. Multi-Round Quality, Consistency, and Low-Score Isolation

When a package has accumulated two or more `AnnotationSubmission` rows across rework rounds, the platform computes a pairwise consistency score between the two annotators' label arrays of equal length. The function chosen depends on `task_type`. For `CLASSIFICATION` and `TEXT_NER`, the score is Cohen's kappa: the observed agreement (the count of items where the two arrays agree, divided by the array length) minus the expected agreement (the sum across classes of the product of the two annotators' marginal class probabilities), the difference divided by 1 minus the expected agreement, with the result floored at 0 so a negative kappa is rendered as 0. For `BBOX`, `SEGMENTATION`, and `KEYPOINT`, the score is the mean across items of the intersection-over-union of the two boxes (intersection area divided by union area, or 1 when both boxes are empty). For `AUDIO_TRANSCRIPTION`, the score is the F1 of token-level matches, where precision is true positives divided by true positives plus false positives, recall is true positives divided by true positives plus false negatives, and F1 is the harmonic mean. The score is rounded to four decimal places with round-half-up.

A consistency score below 0.50 is treated as low-consistency isolation: the package is forced into `ARBITRATING` regardless of the inspection's defect ratio, and the arbiter selection rule below is invoked.

### 3.8. Arbitration: Selection, Decision, and Appeals

When arbitration is required — either by the rework cap being exceeded, by a low consistency score, or by an annotator filing an appeal — the platform selects an arbiter under a deterministic rule. The candidate set is every `AnnotatorProfile` whose `tier` is `EXPERT` and whose `status` is `ACTIVE`, excluding the package owner (the annotator whose id equals `package.assigned_annotator_id`); when the trigger is an appeal, the appeal's own `annotator_id` is also excluded. The candidates are ranked descending first on `golden_hit_rate` and second on `rolling_pass_rate`; ties are broken deterministically by ascending lexicographic order on `AnnotatorProfile.id`. When the candidate set is empty, the operation that triggered the selection is rejected with `ERR_NO_ELIGIBLE_ARBITER`.

An arbiter resolves an arbitrating package with a `decision` of either `APPROVE` or `REJECT`. Only an annotator whose tier is `EXPERT` and who is not the package owner may arbitrate; a violation of either rule is rejected with `ERR_ARBITER_IS_OWNER`. An `APPROVE` advances the package from `ARBITRATING` to `APPROVED` (so the annotator's `submitted_count` and `approved_count` each increment by 1, the piece-rate entry is created exactly as for the direct `INSPECTING → APPROVED` path, and an `IM` event of `event_type` `package.approved` is queued). A `REJECT` advances the package to `REJECTED`, increments `submitted_count` only, books a `PENALTY` of -200 cents, and queues an `IM` event of `event_type` `package.rejected`.

The appeal workflow runs in parallel. A submitting annotator opens an `Appeal` against a finalised inspection by referencing the `inspection_id` and supplying a free-text `reason`; the appeal enters `SUBMITTED`. A `ProjectManager` advances it to `UNDER_REVIEW` by assigning an arbiter — the arbiter selection rule above runs and writes the chosen `arbiter_id`. The assigned arbiter — an annotator whose id equals `appeal.arbiter_id` (else `ERR_NOT_ASSIGNED_ARBITER`) — decides the appeal as `UPHOLD` or `REJECT`. An upheld appeal sets the originating `QualityInspection.outcome` to `DISPUTED` to record the override, inserts an `ADJUSTMENT_UPHELD` entry whose magnitude offsets the penalty entries booked from that inspection (the global invariant: for that inspection, the sum of penalty debits and the matching upholding-adjustment credits is zero), promotes a `REJECTED` package to `APPROVED` where applicable, books the previously withheld piece-rate entry in `WITHHELD` settlement state, queues an `IM` event of `event_type` `appeal.upheld`, and writes a `SALARY_ADJUSTMENT` audit row. A rejected appeal books the flat 100-cent unfounded-appeal penalty in an `ADJUSTMENT_REJECTED` entry, fires the repeated-dispute suspension cascade if the running threshold of 3 rejections in the trailing 20 packages is met, queues an `IM` event of `event_type` `appeal.rejected`, and writes a `SALARY_ADJUSTMENT` audit row.

The serialisation between an in-flight inspection finalise and a freshly submitted appeal is first-writer-wins on the `QualityInspection.outcome` field. If the appeal `SUBMITTED` row is created before the inspection finalises, the inspection finalise is rejected with `ERR_INSPECTION_LOCKED_BY_APPEAL`. Otherwise the inspection commits first and a subsequent appeal create on the now-terminal inspection is itself rejected as state-invalid.

### 3.9. Project Closure and Archival

A `ProjectManager` closes a project — moving `status` from `OPEN` to `CLOSED` — only when no `TaskPackage` on the project is in `IN_PROGRESS`, `SUBMITTED`, `INSPECTING`, `REWORK_PENDING`, or `ARBITRATING`. A close attempt with any such package outstanding is rejected with `ERR_PACKAGES_STILL_OPEN`. Any `POOL` packages remaining at close time are auto-cancelled by being excluded from listings; no salary effect is produced for cancelled-pool packages. A `CLOSED` project may be archived only after every `SalaryLedgerEntry` referencing one of its packages is in `RELEASED` settlement state; an archive attempt that finds any entry still `WITHHELD` is rejected with `ERR_SALARY_NOT_FINALIZED`. The archive transition queues a `STORAGE` event of `event_type` `project.archived`. `ARCHIVED` is the project's terminal state.

### 3.10. Payroll, Withholding, Tax, and Settlement

A payroll period is created with a `cycle_label` (such as "2026-05"), an inclusive start `opens_at`, an exclusive end `closes_at` strictly after `opens_at`, and a flat `tax_rate` between 0 and 1 inclusive. Two periods on the same calendar may not overlap under half-open semantics — periods overlap if and only if the first's `opens_at` is strictly before the second's `closes_at` and the second's `opens_at` is strictly before the first's `closes_at`. A creation request that overlaps an existing period is rejected with `ERR_PERIOD_OVERLAP`. A new period enters `OPEN`.

A `ProjectManager` locks the period — moving `status` from `OPEN` to `LOCKED` — when the current server time has reached or passed `closes_at`; an early lock is rejected with `ERR_PERIOD_NOT_DUE`. On lock, every `SalaryLedgerEntry` whose triggering package's `APPROVED` transition timestamp falls in the half-open interval beginning at `opens_at` and ending strictly before `closes_at` is stamped with this period's id in `payroll_period_id`. Entries that were `WITHHELD` remain `WITHHELD` — locking does not release.

The settle operation is the gate at which withholding is enforced. The period must be in `LOCKED` (else `ERR_PERIOD_STATE_INVALID`); and crucially, no package referenced by any `SalaryLedgerEntry` of this period may be in `INSPECTING`, `REWORK_PENDING`, or `ARBITRATING` (else `ERR_REINSPECTION_PENDING`). The latter is the withholding-for-re-inspection rule — wages stay frozen as long as any cross-cutting quality dispute is still alive.

When settle commits, every `SalaryLedgerEntry` of the period transitions from `WITHHELD` to `RELEASED`, and a per-annotator `TAX` entry is inserted. The tax computation has a pinned evaluation order. For each annotator with at least one entry in this period, the gross total in cents is the sum of `gross_amount_cents` over all entries whose `kind` is in the set `PIECE_RATE`, `BONUS`, `PENALTY`, `ADJUSTMENT_UPHELD`, `ADJUSTMENT_REJECTED`. The tax basis is the maximum of zero and the gross total — tax is never negative. The tax in cents is the round-half-up of the tax basis multiplied by the period's `tax_rate`. The net total in cents is the gross total minus the tax. A `SalaryLedgerEntry` of kind `TAX` is then written with `gross_amount_cents` equal to the negative of the tax. `WITHHOLD` and `RELEASE` entries are accounting markers only — their `gross_amount_cents` is zero and the `settlement_state` field is the truth that drives whether an entry has been released. For any package whose ledger lifetime contains both a penalty and a subsequent upholding adjustment that fully reverses it, the sum across that package's penalty and upholding-adjustment entries is zero, and the `TAX` entry is recomputed against the post-reversal gross total.

The settle transition queues a `PAYMENT` event of `event_type` `payroll.settled` carrying the period id, and a `SALARY_ADJUSTMENT` audit row is written for each `TAX` entry generated. `PayrollPeriod` then enters its terminal state `SETTLED`.

A read-only ledger listing endpoint surfaces the entries for a period; an annotator may filter to a single annotator with the optional `annotator_id` query parameter, while a `ProjectManager` can list across the whole period.

### 3.11. Audit, External Events, and Read-Only Visibility

`AuditLog` and `ExternalEvent` are two append-only logs that record what happened. Each `AuditLog` row carries `actor_id` and `actor_role` (the originating `X-User-ID` and `X-User-Role`, or the literal string `"system"` for system-driven transitions like timeout reclamation), a `subject_kind` of either `TASK_PACKAGE` or `SALARY`, the `subject_id` of the package or ledger entry concerned, an `event_type` of either `STATUS_CHANGE` or `SALARY_ADJUSTMENT`, a `from_value` carrying the prior status string or amount string (null for creation events), and a `to_value` carrying the new status string or amount string. Each `ExternalEvent` row carries a `target_system` (`PAYMENT`, `IM`, or `STORAGE`), an `event_type` (a string like `payroll.settled`, `package.approved`, `package.rejected`, `appeal.upheld`, `appeal.rejected`, `annotator.suspended`, `project.opened`, `project.archived`, or `golden_sample.uploaded`), the `payload_ref_id` of the entity that produced it, and a `dispatch_status` of either `PENDING` or `DISPATCHED`. Both logs are listable by a `ProjectManager`; the audit log accepts `subject_kind` and `subject_id` as filters, and the external-event log accepts `target_system` as a filter.

Listing endpoints throughout the system accept the standard `limit` and `offset` pagination parameters. The annotator listing accepts optional `tier` and `status` filters; the project listing and the per-project package listing accept an optional `status` filter; the payroll-period listing accepts an optional `status` filter.

## 4. Endpoint Definitions

All operations follow the standard envelope of §2.2. Resource-creation operations return HTTP 201 — currently project creation, golden-sample addition, package splitting, annotator registration, payroll-period creation, and appeal submission. All other mutations and reads return HTTP 200. Failures use the codes in §5 and the priority pipeline of §2.9.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST | /annotation-projects | Create a new annotation project in DRAFT | ProjectManager |
| GET | /annotation-projects | List annotation projects | ProjectManager, QAReviewer, Annotator |
| GET | /annotation-projects/{projectId} | Read a project | ProjectManager, QAReviewer, Annotator |
| PATCH | /annotation-projects/{projectId} | Update editable fields while DRAFT (requires version) | ProjectManager |
| POST | /annotation-projects/{projectId}/golden-samples | Add a golden sample to the project | ProjectManager |
| GET | /annotation-projects/{projectId}/golden-samples | List golden samples | ProjectManager, QAReviewer |
| POST | /annotation-projects/{projectId}/task-packages/split | Split the dataset into TaskPackages of project.package_size | ProjectManager |
| POST | /annotation-projects/{projectId}/open | Open the project for claim/dispatch | ProjectManager |
| POST | /annotation-projects/{projectId}/close | Close the project | ProjectManager |
| POST | /annotation-projects/{projectId}/archive | Archive a closed project | ProjectManager |
| GET | /annotation-projects/{projectId}/task-packages | List TaskPackages for a project | ProjectManager, QAReviewer, Annotator |
| GET | /task-packages/{packageId} | Read a TaskPackage | ProjectManager, QAReviewer, Annotator |
| POST | /task-packages/{packageId}/claim | Annotator claims a POOL package (GRAB or HYBRID mode) | Annotator |
| POST | /task-packages/{packageId}/dispatch | ProjectManager dispatches a POOL package to a specific annotator | ProjectManager |
| POST | /task-packages/{packageId}/submit | Annotator submits labels for an IN_PROGRESS package | Annotator |
| POST | /task-packages/{packageId}/start-inspection | Move a SUBMITTED package into INSPECTING | QAReviewer |
| POST | /task-packages/{packageId}/inspections/{inspectionId}/finalize | Finalize a QualityInspection with PASS or FAIL | QAReviewer |
| POST | /task-packages/{packageId}/rework-claim | Original owner reclaims a REWORK_PENDING package | Annotator |
| POST | /task-packages/{packageId}/rework-dispatch | ProjectManager pushes the package back to POOL | ProjectManager |
| POST | /task-packages/{packageId}/arbitrate | Expert arbiter records a final decision on an ARBITRATING package | Annotator |
| POST | /task-packages/{packageId}/appeals | Submit an appeal on a finalized inspection | Annotator |
| GET | /appeals/{appealId} | Read an appeal | ProjectManager, QAReviewer, Annotator |
| POST | /appeals/{appealId}/assign-arbiter | Assign an EXPERT-tier arbiter to the appeal | ProjectManager |
| POST | /appeals/{appealId}/decide | Expert arbiter decides UPHOLD or REJECT | Annotator |
| POST | /annotators | Register a new AnnotatorProfile | ProjectManager |
| GET | /annotators | List annotators | ProjectManager, QAReviewer |
| GET | /annotators/{annotatorId} | Read an annotator | ProjectManager, QAReviewer, Annotator |
| POST | /annotators/{annotatorId}/re-evaluate | Re-run tier_recompute and apply demotion/suspension | ProjectManager |
| POST | /annotators/{annotatorId}/reinstate | Move SUSPENDED → ACTIVE | ProjectManager |
| GET | /annotators/{annotatorId}/projected-pass-rate | Read forward-looking projected pass rate | ProjectManager, QAReviewer, Annotator |
| POST | /payroll-periods | Open a new payroll period | ProjectManager |
| GET | /payroll-periods | List payroll periods | ProjectManager |
| POST | /payroll-periods/{periodId}/lock | Lock the period and stamp candidate ledger entries | ProjectManager |
| POST | /payroll-periods/{periodId}/settle | Settle the period | ProjectManager |
| GET | /payroll-periods/{periodId}/ledger-entries | List SalaryLedgerEntry rows for a payroll period | ProjectManager, Annotator |
| GET | /audit-logs | List audit logs | ProjectManager |
| GET | /external-events | List queued external events | ProjectManager |
| POST | /_clock/advance | Advance the system clock to a specific ISO 8601 instant | ProjectManager |
| POST | /_events/dispatch-pending | Mark all PENDING ExternalEvent rows as DISPATCHED | ProjectManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_MISSING_AUTH_HEADERS | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_PROJECT_NOT_FOUND | 404 |
| ERR_PACKAGE_NOT_FOUND | 404 |
| ERR_ANNOTATOR_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_APPEAL_NOT_FOUND | 404 |
| ERR_PERIOD_NOT_FOUND | 404 |
| ERR_GOLDEN_NOT_FOUND | 404 |
| ERR_PROJECT_NOT_OPEN | 409 |
| ERR_PROJECT_NOT_DRAFT | 409 |
| ERR_PROJECT_NOT_CLOSED | 409 |
| ERR_PACKAGE_STATE_INVALID | 409 |
| ERR_INSPECTION_STATE_INVALID | 409 |
| ERR_APPEAL_STATE_INVALID | 409 |
| ERR_PERIOD_STATE_INVALID | 409 |
| ERR_PACKAGE_ALREADY_TAKEN | 409 |
| ERR_INSPECTION_LOCKED_BY_APPEAL | 409 |
| ERR_PACKAGES_STILL_OPEN | 409 |
| ERR_SALARY_NOT_FINALIZED | 409 |
| ERR_GUIDELINE_REQUIRED | 409 |
| ERR_SAMPLE_PREVIEW_REQUIRED | 409 |
| ERR_GOLDEN_SAMPLES_INSUFFICIENT | 409 |
| ERR_NO_TASK_PACKAGES | 409 |
| ERR_TIER_INSUFFICIENT | 403 |
| ERR_GRAB_NOT_ALLOWED | 409 |
| ERR_DISPATCH_NOT_ALLOWED | 409 |
| ERR_ANNOTATOR_SUSPENDED | 403 |
| ERR_NOT_PACKAGE_OWNER | 403 |
| ERR_LABEL_COUNT_MISMATCH | 400 |
| ERR_PACKAGE_TIMED_OUT | 409 |
| ERR_ARBITER_IS_OWNER | 403 |
| ERR_NOT_ASSIGNED_ARBITER | 403 |
| ERR_NO_ELIGIBLE_ARBITER | 409 |
| ERR_PERIOD_NOT_DUE | 409 |
| ERR_REINSPECTION_PENDING | 409 |
| ERR_PERIOD_OVERLAP | 409 |
| ERR_INVALID_PARAMETER | 400 |
| ERR_DEFECTS_OUT_OF_RANGE | 400 |
| ERR_INVALID_PAGINATION | 400 |
| ERR_VERSION_CONFLICT | 409 |

# HEDIS Quality Measures API — Product Requirements Document

## 1. Introduction

Every year, health plan quality departments live and die by the HEDIS reporting cycle: measure specifications must be loaded for the measurement year, the eligible population identified, hybrid samples drawn, medical charts chased from provider offices, abstracted by certified staff, over-read for inter-rater reliability, supplemented with administrative evidence, and finally certified and submitted before a hard regulatory deadline. Each of these steps is today coordinated across spreadsheets, shared drives, and institutional memory — a process that is slow, error-prone, and nearly impossible to defend during an NCQA audit.

This document specifies a single REST API, mounted under the `/hedis` path prefix, that runs the entire quality-measure abstraction pipeline for a health plan's quality department. The platform covers measure specification load and eligible population identification, administrative versus hybrid sampling, medical record chart chase and retrieval, abstraction with over-read validation, supplemental data source acceptance with an audit registry, rate calculation against a submission deadline, gap-list generation for provider outreach, and audit review culminating in measure certification. It enforces the compliance posture the domain demands: segregation of duties between abstractors and over-readers and between run submitters and certifiers, optimistic concurrency on the resources that serialize multi-step work, deterministic sampling and matching algorithms, and a server-side logical clock so that deadline behavior is reproducible rather than hostage to wall-clock time.

The audience is the engineering team building this platform. Business rules are stated as product behavior; where a rule has audit or regulatory weight (rate formulas, IRR tiering, deadline semantics), the prose pins the exact procedure an implementation must follow.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

Seven roles exist, spelled exactly as follows: `QualityAdmin`, `QualityAnalyst`, `Abstractor`, `OverReader`, `ProviderRelations`, `Auditor`, and `QualityDirector`. All seven roles use an **opaque** identity model. When `X-User-Role` is `QualityAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any resource's `id`. The same holds individually for `QualityAnalyst`, `Abstractor`, `OverReader`, `ProviderRelations`, `Auditor`, and `QualityDirector`: in each case `X-User-ID` is an opaque operator identifier. The server may record it — for example as `abstractor_user_id` on an Abstraction, `reviewer_user_id` on an OverReadReview, `submitted_by_user_id` or `certified_by_user_id` on a MeasureRun, or `auditor_user_id` on an AuditEngagement — and it uses those recorded values for ownership and segregation-of-duties comparisons (§2.8), but it never resolves `X-User-ID` against any entity's primary key.

Broadly, `QualityAdmin` owns reference data (the logical clock, seasons, specification loads, members, enrollment, providers); `QualityAnalyst` runs the operational pipeline (runs, population, sampling, chases, rates, submission, supplemental data); `Abstractor` creates and edits its own abstractions; `OverReader` records over-read reviews; `ProviderRelations` works the gap list; `Auditor` runs engagements and files or resolves findings; and `QualityDirector` certifies submitted runs. Read endpoints are shared broadly across all seven roles, with two exceptions: the per-run gap-item list is not available to `Abstractor` or `OverReader`, and the per-engagement findings list, the engagement detail, and the per-run and per-season engagement lists are restricted to `QualityAdmin`, `QualityAnalyst`, `Auditor`, and `QualityDirector`. Section 4 states the authorized roles for every endpoint.

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

### 2.3. Pagination and Result Ordering

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10; an unparsable value falls back to 10, and out-of-range values are clamped — never rejected — to a minimum of 1 and a maximum of 100. The `offset` parameter defaults to 0; an unparsable or negative value is clamped to 0. Paginated responses report `limit`, `offset`, `total_count`, and `has_more` in the `meta` object, where `has_more` is true exactly when `offset` plus the number of returned items is less than `total_count`.

Unless a business-key ordering applies, list results are ordered by `created_at` ascending — that is, in mint order. Where the minted order follows a business key, that order is used instead: population entries and chart chases list in `member_ref` ascending order. Several list endpoints accept filters as query parameters: `status` on the season's specification list, the season's engagement list, the run's supplemental batch list, the run's gap-item list, the sample's chart-chase list, and the engagement's findings list; `season_id`, `spec_id`, and `reporting_status` on the run list; `is_sampled` and `admin_compliant` on the run's population-entry list; `provider_ref` and `member_ref` on the run's gap-item list; `disposition` on a batch's record list; and `severity` on an engagement's findings list.

### 2.4. Resource Identity and Common Fields

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix. Most resources additionally carry `created_at` and `updated_at` — ISO 8601 UTC timestamps with three fractional digits — and a `version` field, an integer that increments by exactly 1 on every mutation of that resource, including mutations caused by another resource's state transition cascading into it. Three bookkeeping mutations are exempt from the version rule: the over-read selector's flagging of `requires_overread` (§3.5) moves only the abstraction's `updated_at`; the incremental recomputation of a run's numerator counters and its entries' `sample_compliant` flags (§3.7) changes neither timestamps nor versions; and the `record_count` intake bump on a supplemental batch (§3.6) moves only the batch's `updated_at`.

Three resource types are deliberately lighter. A MemberEnrollmentSegment, an OverReadReview, and a SupplementalRecord each carry only `id` and `created_at`; both `updated_at` and `version` are absent on these three types, and no operation may expose or require them there.

Consistency is immediate: when a single request mutates several resources (a primary mutation plus its cascades), every one of those mutations is visible in the same request's response and in any subsequent read.

### 2.5. The Logical Clock and Season Deadlines

The server maintains a logical clock rather than consulting wall-clock time. At startup the clock reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `QualityAdmin`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and the response reports the resulting `current_utc`. Deadline checks, engagement-window checks, enrollment-window arithmetic, and abstraction `submitted_at` stamps all read this logical clock.

Advancing the clock has one system-wide side effect: any season in `OPEN` status whose `submission_deadline` is strictly earlier than the new clock instant auto-transitions to `SUBMISSION_CLOSED`, with the season's `version` incremented by 1. Run submissions, by contrast, are accepted at or before the deadline instant — a submission whose logical-clock time equals the season's `submission_deadline` exactly is still on time.

### 2.6. Optimistic Concurrency Control

Two write operations are serialized through optimistic concurrency control, and only those two carry a version field in their request body; no other endpoint takes a version field as input.

Loading a measure specification into a season requires the request to carry `expected_season_version`, the season `version` the client last observed. If the season's current `version` has advanced since — for example because another specification was loaded into the same season in the meantime, or the season was opened — the load is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the season before writing. Spec loads are serialized per season so that same-code supersession stays linear.

Recomputing a run's rates requires the request to carry `expected_measure_run_version`, the run `version` the client last observed. If the run's current `version` has advanced since — because population was identified, an exclusion was applied, a supplemental batch was accepted, or any other run mutation landed — the recompute is rejected with `ERR_STALE_VERSION` (HTTP 412). A rate computed from a stale view would silently miss population or evidence mutations the client has not seen.

### 2.7. Numeric Precision, Rates, and Rounding

All rates on a MeasureRun — `admin_rate`, `hybrid_rate`, and `final_rate` — and the sample's `irr_ratio` are reported to 4 decimal places, rounded half-up. Each remains null until the first computation that can produce it: rates stay null until the first rate computation, and `irr_ratio` stays null until an IRR evaluation finds at least one latest-round over-read.

The provider gap-burden read uses a different precision discipline: each per-measure line is rounded half-up to 2 decimal places first, and only then are the rounded lines summed into the burden score. The per-line-then-sum order is pinned; computing the raw sum and rounding once at the end is the rejected alternative. Tier thresholds in inter-rater reliability use inclusive boundaries: a ratio of exactly 0.95 passes, and a ratio of exactly 0.90 maps to the middle over-read fraction.

### 2.8. Segregation of Duties and Row Ownership

Three identity-based guards protect the quality pipeline, all evaluated as comparisons against `X-User-ID`. First, an over-read review may never be recorded by the abstractor who produced the abstraction: the reviewer's `X-User-ID` must differ from the abstraction's `abstractor_user_id`, and a violation is rejected with `ERR_SOD_SELF_OVERREAD`. Second, a run may never be certified by the analyst who submitted it: the certifier's `X-User-ID` must differ from the run's `submitted_by_user_id`, and a violation is rejected with `ERR_SOD_SUBMITTER_CERTIFY`. Third, abstractions are author-owned rows: editing a draft's `result`, submitting, and retracting an abstraction all require `X-User-ID` to equal the abstraction's `abstractor_user_id`, and a violation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

### 2.9. Validation Pipeline and Priority Order

Every request is validated against the following checks in a fixed priority order; when several checks would fail, the earliest one determines the response and masks the rest.

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Applies to all endpoints.
2. **Role authorization.** The role in `X-User-Role` must be listed for the endpoint, else `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). Applies to all endpoints; role authorization precedes body-shape validation on every endpoint, so an unauthorized role surfaces even when the body is also malformed.
3. **Body shape.** Required fields must be present and non-null, enum values must lie within their declared sets, and on enrollment segments `span_start` must be on or before `span_end`; violations return `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints. The same error also covers a missing `final_result` on a disagreeing over-read.
4. **Existence.** Path-template identifiers and body-supplied foreign keys — `season_id`, `spec_id`, `run_id`, `member_id`, `sample_id`, `chase_id`, `abstraction_id`, `batch_id`, `engagement_id` — must resolve, validated left-to-right along the path and payload, else `ERR_NOT_FOUND` (HTTP 404). Immediately after, on member registration only, a provided `attributed_provider_ref` must resolve to an existing provider's `provider_ref`, else `ERR_PROVIDER_NOT_FOUND` (HTTP 404).
5. **Optimistic concurrency.** The `expected_season_version` or `expected_measure_run_version` check of §2.6, else `ERR_STALE_VERSION` (HTTP 412).
6. **Target state machine.** The target resource's own state machine must allow the transition — covering chase, abstraction, batch, sample, engagement, finding, and gap from-state checks — else `ERR_INVALID_STATE` (HTTP 409). On run submission specifically, the requirement that the run be in `RATE_COMPUTED` is evaluated at this point and surfaces as `ERR_RUN_NOT_SUBMITTABLE` (HTTP 409) — before the season-state and deadline checks below. The abstraction row-ownership checks of §2.8, though they surface as `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403), are evaluated immediately after this band's from-state check — so editing, submitting, or retracting an abstraction in a non-conforming state yields `ERR_INVALID_STATE` even for a non-author caller.
7. **Cross-entity state guards.** Guards that read a related resource's state: submission requires the season `OPEN`; population identification requires the pinned specification `ACTIVE`; chase mutations require the owning sample `DRAWN`; abstraction creation requires the chase `RECEIVED`; hybrid rate computation requires the sample `FINALIZED`; record creation requires the batch `RECEIVED`; beginning an audit review requires the run `SUBMITTED` with `audit_status` in `UNAUDITED` or `AUDIT_FAILED`. Every one of these returns `ERR_INVALID_STATE` (HTTP 409) — with one named exception: submission against a season that is not `OPEN` returns `ERR_SEASON_NOT_OPEN` (HTTP 409).
8. **Segregation of duties.** The over-read self-review check returns `ERR_SOD_SELF_OVERREAD` (HTTP 403) and the submitter-certifier check returns `ERR_SOD_SUBMITTER_CERTIFY` (HTTP 403); on supplemental batch acceptance, the source-approval check also lives in this band and returns `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE` (HTTP 422).
9. **Business temporal.** Submission past the deadline returns `ERR_SUBMISSION_DEADLINE_PASSED` (HTTP 422) — evaluated after the run-state and season-state checks; beginning a review outside the engagement window returns `ERR_OUTSIDE_ENGAGEMENT_WINDOW` (HTTP 422); an engagement created with `window_end` not strictly after `window_start` returns `ERR_ENGAGEMENT_WINDOW_INVALID` (HTTP 422).
10. **Business constraints and uniqueness.** Duplicate measure code within a season (`ERR_DUPLICATE_MEASURE_CODE`), duplicate `member_ref` (`ERR_DUPLICATE_MEMBER_REF`), duplicate `provider_ref` (`ERR_DUPLICATE_PROVIDER_REF`), a second sample for one run (`ERR_SAMPLE_ALREADY_EXISTS`), a second non-terminal abstraction for one chase (`ERR_DUPLICATE_ABSTRACTION`), overlapping enrollment segments (`ERR_ENROLLMENT_OVERLAP`), overlapping auditor windows (`ERR_AUDITOR_WINDOW_OVERLAP`) — all HTTP 409; drawing a sample on a non-hybrid run (`ERR_METHOD_NOT_HYBRID`, HTTP 422); excluding a population entry once the hybrid run's sample exists (`ERR_EXCLUSION_NOT_ALLOWED`, HTTP 422).
11. **Denominator referential integrity.** On supplemental batch acceptance, every record must reference a member of the run's non-excluded population, else `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR` (HTTP 422) — checked strictly after the source-approval check of band 8.
12. **Fiscal and completeness gates.** Sample pool below the floor (`ERR_SAMPLE_BELOW_FLOOR`), rate computation with an empty denominator (`ERR_DENOMINATOR_ZERO`), finalization with chases in flight (`ERR_CHASES_IN_FLIGHT`), finalization with unabstracted received charts (`ERR_UNABSTRACTED_CHARTS`), finalization with outstanding over-reads (`ERR_OVERREADS_OUTSTANDING`), finalization without a passing IRR (`ERR_IRR_NOT_PASSED`), certification of an uncertifiable run (`ERR_RUN_NOT_CERTIFIABLE`) — all HTTP 422; and, on record creation, an identical record already present in the same batch (`ERR_DUPLICATE_SERVICE_DATE`, HTTP 409).

The ordering is observable behavior. A stale run version surfaces before a state-machine violation on the same request; a submission from a non-`RATE_COMPUTED` run surfaces `ERR_RUN_NOT_SUBMITTABLE` even when the season is also closed; a batch from an unapproved source surfaces `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE` even when its records also reference strangers to the denominator.

### 2.10. Reverse Reachability and Nested Retrieval

All resources are top-level under `/hedis`; parent-child links live in request bodies and on the child rows, never in deeply nested write paths. Reads, however, offer sub-resource listings for reverse reachability: a season exposes its specifications and its audit engagements; a run exposes its sample (zero or one element), population entries, supplemental batches, gap items, and audit engagements; a member exposes enrollment segments; a sample exposes chart chases; a chase exposes abstractions; an abstraction exposes over-read reviews; a batch exposes records; an engagement exposes findings. These listings follow §2.3's pagination and ordering rules and accept the filters enumerated there.

Where a URL contains path parameters, each identifier is resolved in left-to-right order, and the first identifier that fails to resolve yields `ERR_NOT_FOUND` without evaluating the remainder of the request.

## 3. Business Logic & Workflows

### 3.1. Season Administration and Measure Specification Management

A reporting cycle begins when a `QualityAdmin` creates a measurement season with its `measurement_year` (the HEDIS year, such as 2025, against which service dates and enrollment windows are evaluated), its `submission_deadline` (the instant at or before which run submissions are accepted), an informational `admin_data_cutoff` for administrative data refresh, and the season's `approved_supplemental_sources` — the audit registry of acceptable supplemental source types, drawn from `LAB_FEED`, `IMMUNIZATION_REGISTRY`, `PHARMACY`, and `EHR`. All four fields are required at creation, and `approved_supplemental_sources` must be a list whose every element is one of those four source types. A new season starts in `DRAFT` status with `certified_run_count` at zero.

Opening the season transitions it from `DRAFT` to `OPEN`; the transition is only legal from `DRAFT` and otherwise fails with `ERR_INVALID_STATE`. Closing submissions transitions `OPEN` to the terminal `SUBMISSION_CLOSED`, either on explicit request by a `QualityAdmin` or automatically when the logical clock is advanced past the season's `submission_deadline` while the season is `OPEN` (§2.5). Both transitions increment the season's `version` by 1.

Measure specifications are loaded into a season by a `QualityAdmin`. The load payload carries the target `season_id`, the `hedis_measure_code` (such as BCS), a `version_label` (such as 2025.1), the `collection_method` (`ADMINISTRATIVE` or `HYBRID`), the population criteria `age_min` and `age_max` (inclusive whole-year bounds at the anchor date), `continuous_enrollment_months`, and the `anchor_date` anchoring both age evaluation and the end of the enrollment window. Optional fields carry defaults: `hybrid_policy` defaults to `SAMPLE_ONLY` (the alternative, `ADMIN_SUPPLEMENTED`, selects a different rate variant and is meaningful only for `HYBRID` measures), `matching_policy` defaults to `EXACT` (the alternative being `TOLERANT`), `sample_size_floor` defaults to 411 (the NCQA-style minimum hybrid sample), `gender_requirement` defaults to `ANY` (with `F` and `M` as the restrictive alternatives), `allowable_gap_days` defaults to 45, and `reporting_weight` defaults to 1.0. The load must also carry `expected_season_version` under the optimistic-concurrency rule of §2.6, because the load itself increments the season's `version` by 1 — a client holding a stale season view is rejected with `ERR_STALE_VERSION`. The season is resolved and this version check is applied before the specification's remaining field values are validated, so a stale season view surfaces `ERR_STALE_VERSION` even when another field is also invalid; a non-integer `expected_season_version` is `ERR_INVALID_REQUEST`. A measure code may be loaded only once per season: a duplicate pairing of `season_id` and `hedis_measure_code` is rejected with `ERR_DUPLICATE_MEASURE_CODE`. A freshly loaded specification sits in `LOADED` status.

Activation moves a specification from `LOADED` to `ACTIVE`. Beyond the from-state check, activation carries a cross-entity guard: the specification's season must be in `DRAFT` or `OPEN`; activating into a closed season fails with `ERR_INVALID_STATE`. Retirement moves a specification to the terminal `RETIRED` state from either `LOADED` or `ACTIVE`, with an asymmetry worth noting: retiring from `ACTIVE` is blocked while any run pinned to that specification still has `reporting_status` in `POPULATION_PENDING`, `POPULATED`, `RATE_COMPUTED`, or `SUBMITTED` (a run that has reached `CERTIFIED` or `CERTIFICATION_FAILED` no longer blocks), whereas retiring from `LOADED` has no such guard. Both retirement paths fail with `ERR_INVALID_STATE` when their precondition is unmet, and every specification transition increments the specification's `version` by 1.

### 3.2. Member, Enrollment, and Provider Reference Data

A `QualityAdmin` registers each plan member with a business identifier `member_ref`, a `birth_date`, and a `gender` of `F` or `M`; `member_ref` is unique across members, and a duplicate registration is rejected with `ERR_DUPLICATE_MEMBER_REF`. Optionally the registration carries `attributed_provider_ref`, a denormalized attribution used later for chart-chase routing and gap outreach; when provided it must resolve to an existing provider's `provider_ref`, else `ERR_PROVIDER_NOT_FOUND`.

Enrollment history is recorded as segments. Creating a segment supplies `member_id`, `span_start`, and `span_end`, describing a **closed** interval — both endpoints are inclusive days of enrollment — and `span_end` before `span_start` is rejected as `ERR_INVALID_REQUEST`. Two segments of the same member may not overlap: because the intervals are closed, a new segment whose `span_start` falls on or before an existing segment's `span_end` while its `span_end` falls on or after that segment's `span_start` is rejected with `ERR_ENROLLMENT_OVERLAP` — and touching endpoints do count as overlap, so a segment starting exactly on the day another ends collides. Recall from §2.4 that enrollment segments carry only `id` and `created_at`.

Providers are registered with a unique `provider_ref` (duplicates rejected with `ERR_DUPLICATE_PROVIDER_REF`), a display `name`, and an optional `specialty`. Each provider carries a derived `open_gap_count`, starting at zero: it counts that provider's gap items in `OPEN` or `OUTREACH_DONE` status and is reconciled automatically whenever a gap item is created, manually closed, or auto-closed by arriving evidence (§3.7).

### 3.3. Measure Runs and Eligible Population Identification

A `QualityAnalyst` creates a measure run by supplying `season_id` and `spec_id`. Creation pins the specification: the run copies the spec's `version_label` into `spec_version_label` and its `collection_method` onto the run, so later specification version changes never reach an existing run. A new run starts with `reporting_status` `POPULATION_PENDING` and `audit_status` `UNAUDITED`. These two statuses are independent dimensions: the reporting dimension walks `POPULATION_PENDING` → `POPULATED` → `RATE_COMPUTED` → `SUBMITTED` → `CERTIFIED`, with `SUBMITTED` → `CERTIFICATION_FAILED` → `POPULATED` as the reopen cycle, while the audit dimension walks `UNAUDITED` → `IN_REVIEW` → `AUDIT_PASSED` or `AUDIT_FAILED`, with `AUDIT_FAILED` → `IN_REVIEW` permitting re-review.

Identifying the eligible population advances the run from `POPULATION_PENDING` to `POPULATED` and is the heart of HEDIS denominator construction. Two preconditions guard it: the run must still be `POPULATION_PENDING`, and — a version-pinning revalidation — the run's pinned specification must still be `ACTIVE`; either failure is `ERR_INVALID_STATE`. The evaluation window ends at the specification's `anchor_date`, taking the date part only, and begins `continuous_enrollment_months` calendar months before that end date plus one day — month arithmetic clamps the day-of-month to the target month's last day when the anchor's day exceeds it. Members are examined one by one in `member_ref` ascending order (never by internal id). A member is skipped when the specification's `gender_requirement` is not `ANY` and the member's `gender` differs from it. Age is computed as whole years between `birth_date` and `anchor_date`, and a member is skipped when that age is below `age_min` or above `age_max` — both bounds inclusive. The survivor's enrollment segments are sorted by `span_start` ascending with `span_end` ascending as tie-break, merged as closed intervals — intervals that overlap or merely touch, one ending the day before the next begins, merge into one — and the merged union is clipped to the evaluation window. Uncovered day-ranges strictly inside the clipped window are the member's enrollment gaps; a member is eligible exactly when there is at most one such gap and each gap's length is no more than `allowable_gap_days` days, where gap length is measured in whole days counting both the first and last uncovered day. One `PopulationEntry` is minted per eligible member, stamped with the run's `run_id` and the member's `member_ref`, and initialized with `is_excluded` false, `is_sampled` false, `admin_compliant` false, and `sample_compliant` false. The run's `denominator_count` is set to the number of minted entries, and the run's `version` increments.

Before any sample is drawn, a `QualityAnalyst` may apply a valid exclusion to a denominator entry — a member who became ineligible, for instance. The request carries a `reason`; excluding an already-excluded entry fails with `ERR_INVALID_STATE`. On success the entry's `is_excluded` flips to true and `exclusion_reason` records the supplied text, the run's `exclusion_count` increments by 1 and its `denominator_count` decrements by 1, and both the entry's and the run's `version` increment. Exclusion is available on `ADMINISTRATIVE` runs and on `HYBRID` runs only before their sample exists; once a hybrid run's sample has been drawn, the exclusion attempt is rejected with `ERR_EXCLUSION_NOT_ALLOWED`.

### 3.4. Hybrid Sampling and Chart Chase Operations

A hybrid measure's chart review begins with the sample draw. A `QualityAnalyst` draws the sample by supplying the `run_id`. Three gates precede the draw: the run's `collection_method` must be `HYBRID` — drawing on an administrative run is rejected with `ERR_METHOD_NOT_HYBRID`; at most one sample may exist per run — a second draw is rejected with `ERR_SAMPLE_ALREADY_EXISTS`; and the eligible pool — the run's population entries with `is_excluded` false — must number at least the specification's `sample_size_floor`, else `ERR_SAMPLE_BELOW_FLOOR`.

The draw itself is deterministic. The pool is sorted by `member_ref` ascending (the business key is unique, so no further tie-break is needed and internal ids are never consulted). The `drawn_size` is the smaller of the specification's `sample_size_floor` and the pool size, and the `draw_step` is the pool size divided by `drawn_size` as a real number. Walking a zero-based counter from 0 up to `drawn_size` minus 1, the draw selects the pool entry at the index given by the exact floor of the counter times `draw_step`. Each selected entry's `is_sampled` flips to true, and one chart chase is minted per selected entry: status `REQUESTED`, `chase_round` 1, the chase's `member_ref` taken from the entry, and its `provider_ref` taken from the member's `attributed_provider_ref` — null when the member is unattributed. The new sample starts in `DRAWN` status with `irr_state` `PENDING`, a null `irr_ratio`, `remediation_count` zero, and `required_overread_fraction` at its base of 0.10 — one abstraction in ten, rounded up, will be flagged for over-read.

Chase work is the operational grind of retrieval. Marking a chart received moves the chase from `REQUESTED` to `RECEIVED`. Rejecting an unreadable chart moves `RECEIVED` to `REJECTED_UNREADABLE`. Withdrawing a pending request moves `REQUESTED` to `WITHDRAWN`. Re-chasing returns a chase to `REQUESTED` from either `REJECTED_UNREADABLE` or `WITHDRAWN`, incrementing `chase_round` by exactly 1 on every re-chase — the round counter is the audit trail of retrieval attempts. Every one of these analyst-driven chase mutations requires the owning sample to still be `DRAWN` and otherwise fails with `ERR_INVALID_STATE`; each also increments the chase's `version` by 1. Two further chase transitions are not analyst-driven at all: a chase in `RECEIVED` moves to `ABSTRACTED` as a side effect of the first submission of its abstraction, and a chase in `ABSTRACTED` returns to `RECEIVED` as compensation when that submitting abstraction is retracted (§3.5).

A sampled member sometimes turns out to be invalid for the measure — deceased, for example. Marking a chase excluded moves it from `REQUESTED`, `RECEIVED`, or `REJECTED_UNREADABLE` into the terminal `EXCLUDED_VALID` state; the request carries a `reason`. The guard requires the owning sample still `DRAWN` and that no abstraction yet exists for the chase; violations are `ERR_INVALID_STATE`. Each valid exclusion increments the run's `sample_exclusion_count` by 1, which directly shrinks the hybrid denominator at rate time (§3.7), and increments the chase's `version`.

### 3.5. Abstraction, Over-Read Review, and Inter-Rater Reliability

Once a chart is in hand, an `Abstractor` creates an abstraction by supplying the `chase_id` and a `result` of `HIT`, `MISS`, or `NOT_ABSTRACTABLE`. The chase must be `RECEIVED` — abstracting a chart that has not arrived is `ERR_INVALID_STATE` — and at most one non-terminal abstraction may exist per chase; because `CONFIRMED` and `OVERREAD_PASSED` are the abstraction's terminal states, a second concurrent draft on the same chase is rejected with `ERR_DUPLICATE_ABSTRACTION`. Creation records the author's `X-User-ID` as `abstractor_user_id` and starts the abstraction in `DRAFT`. While in `DRAFT` — and only there — the author may correct the `result` through the abstraction edit capability; edits by anyone other than the author, like submits and retracts by anyone other than the author, are rejected with `ERR_INSUFFICIENT_PERMISSIONS`, and each edit increments the abstraction's `version`.

Submitting an abstraction moves `DRAFT` to `SUBMITTED`. The submission stamps `submitted_at` with the current logical-clock time — this timestamp is the selector's sort key — and, on the first submit only, moves the chase from `RECEIVED` to `ABSTRACTED` as a side effect. Resubmission out of `REMEDIATION` follows the same path with two additions: `resubmission_count` increments by 1, and `submitted_at` is refreshed to the current logical-clock time. Every submit, from either state, runs the over-read selector top-up and recomputes the run's `sample_numerator_count`.

The over-read selector is deterministic. Among the sample's abstractions currently in `SUBMITTED`, ordered by `submitted_at` ascending with `created_at` ascending as tie-break, it flags `requires_overread` true in that order until the number flagged among the submitted set reaches at least the ceiling of `required_overread_fraction` times the number of submitted abstractions. The top-up re-runs on every submit, on every over-read outcome, and whenever an abstraction leaves `SUBMITTED`, because each of those events changes either the flagged set or the multiplier's base. The selector never clears a flag once set, and flagging an abstraction moves its `updated_at` without incrementing its `version` (§2.4).

An `OverReader` records a review by supplying the `abstraction_id`, an `outcome` of `AGREE` or `DISAGREE`, and — required exactly when the outcome is `DISAGREE` — a `final_result` of `HIT` or `MISS` carrying the reviewer's corrected determination; a disagreeing review without `final_result` is `ERR_INVALID_REQUEST`, and a `final_result` supplied with `AGREE` is validated against the same set but not recorded — the review's `final_result` stays null unless the outcome is `DISAGREE`. The reviewed abstraction must be `SUBMITTED` with `requires_overread` true, else `ERR_INVALID_STATE`, and the reviewer may not be the abstraction's author, else `ERR_SOD_SELF_OVERREAD` (§2.8). At most one review exists per abstraction per submission round — the pair of `abstraction_id` and `resubmission_count` identifies a round — and this uniqueness needs no dedicated check: the first review always moves the abstraction out of `SUBMITTED`, so a second attempt against the same round fails the state guard with `ERR_INVALID_STATE`. The review records the reviewer's `X-User-ID` as `reviewer_user_id`, and per §2.4 the review row carries only `id` and `created_at`.

The two outcomes diverge sharply. An `AGREE` moves the abstraction from `SUBMITTED` to `OVERREAD_PASSED`, recomputes the run's `sample_numerator_count`, and re-runs the selector top-up — an abstraction just left the submitted set, so the earliest unflagged submitted abstractions are flagged until the quota is met again. A `DISAGREE` moves the abstraction from `SUBMITTED` to `REMEDIATION` and fires a three-link cascade: first the sample's `remediation_count` increments by 1; second, when that count reaches 2, the sample's `required_overread_fraction` is set to 1.0 immediately — a hard override applied at once, not deferred to the next IRR evaluation; third, the selector top-up re-runs immediately under the new fraction, flagging still-submitted abstractions in `submitted_at` then `created_at` order. The run's `sample_numerator_count` is recomputed as well, and each transition increments the abstraction's `version`.

Retraction compensates submission. From `SUBMITTED`, the author may retract back to `DRAFT` only while no over-read review exists for the current submission round — once reviewed, the remediation path is mandatory — and the retraction moves the chase from `ABSTRACTED` back to `RECEIVED` and recomputes the run's `sample_numerator_count` with the retracted abstraction removed from the counted set. From `REMEDIATION`, retraction also returns to `DRAFT` but behaves differently: `resubmission_count` increments by 1 because leaving remediation advances the submission round and thereby unlocks a fresh over-read, and the chase stays `ABSTRACTED` — the chart remains in hand during remediation.

Inter-rater reliability is evaluated on demand by a `QualityAnalyst`. For each abstraction of the sample, only the over-read review of its latest submission round counts — abstractions in any status contribute their latest review. Agreements are the latest reviews with `outcome` `AGREE`; the `irr_ratio` is agreements divided by the total number of latest-round reviews, rounded half-up to 4 decimal places, and remains null while no latest-round review exists. The required over-read fraction is then re-tiered top-down: if the sample's `remediation_count` has reached 2, the fraction is 1.0 regardless of ratio; otherwise, if `irr_ratio` is null, the fraction is left unchanged; otherwise a ratio of at least 0.95 sets the fraction to 0.10, a ratio of at least 0.90 but below 0.95 sets it to 0.25, and anything below 0.90 sets it to 1.0. The `irr_state` becomes `PASSED` exactly when `irr_ratio` is non-null and at least 0.95 — the boundary is inclusive — and `FAILED` when it is non-null and below 0.95; a null ratio leaves the state `PENDING`, and a `FAILED` sample may re-evaluate to `PASSED` after remediation improves agreement. The evaluation concludes by re-running the selector top-up under the resulting fraction, and the sample's `version` increments.

Finalization is the sample's quality gate, moving it from `DRAWN` to `FINALIZED`, and it enforces four checks in narrative order of the workflow they guard. No chase of the sample may be in `REQUESTED` or `REJECTED_UNREADABLE` — charts still in flight block with `ERR_CHASES_IN_FLIGHT`. Every chase in `RECEIVED` must have an abstraction in `SUBMITTED`, `CONFIRMED`, or `OVERREAD_PASSED` — a received but unabstracted chart blocks with `ERR_UNABSTRACTED_CHARTS`. No abstraction in `SUBMITTED` with `requires_overread` true may lack an over-read of its current submission round — outstanding reviews block with `ERR_OVERREADS_OUTSTANDING`. And whenever any abstraction carries `requires_overread` true, the sample's `irr_state` must be `PASSED`, else `ERR_IRR_NOT_PASSED`. On success, every `SUBMITTED` abstraction with `requires_overread` false auto-transitions to `CONFIRMED` in bulk, the run's `sample_numerator_count` is recomputed, and the sample's `version` increments. The sample's terminal state is `LOCKED`, reached only as a side effect of run submission (§3.8), and a certification reopen returns `LOCKED` to `FINALIZED` — both system transitions increment the sample's `version`.

One derived flag ties the sample back to the denominator: a population entry's `sample_compliant` is recomputed on every counter pass, set or cleared to reflect whether the sampled member's chase currently holds an abstraction with `result` `HIT` in `SUBMITTED`, `CONFIRMED`, or `OVERREAD_PASSED`. The flag is read by the hybrid rate variant described in §3.7.

### 3.6. Supplemental Data: Batches, Screening, and Acceptance

Supplemental evidence arrives in batches. A `QualityAnalyst` creates a batch by supplying the `run_id` it may feed and a `source_type` of `LAB_FEED`, `IMMUNIZATION_REGISTRY`, `PHARMACY`, or `EHR`; the batch starts in `RECEIVED` status with `record_count` and `accepted_record_count` both zero.

Records are added to a batch while — and only while — it is `RECEIVED`; adding to a screened or settled batch is `ERR_INVALID_STATE`. Each record carries `batch_id`, the source-supplied `member_ref`, the `service_date`, and an `evidence_code` such as MAMMO or A1C. One request-level uniqueness rule applies at intake: a record identical in `member_ref`, `service_date`, and `evidence_code` to one already present in the same batch is rejected outright with `ERR_DUPLICATE_SERVICE_DATE`. A new record starts with `disposition` `PENDING` and increments the batch's `record_count` by 1; per §2.4 the record row itself carries only `id` and `created_at`.

Screening moves the batch from `RECEIVED` to `SCREENED` and adjudicates every record. The batch's `matching_policy_used` is copied at screen time from the run's pinned specification — screening always reflects the spec version the run pinned, never a later spec edit. Records are processed in `created_at` ascending order, and each record passes through three checks in sequence. First, member matching: under the `EXACT` variant the record's `member_ref` must string-equal some member's `member_ref` exactly as supplied — case, whitespace, and zero-padding differences all reject — while under the `TOLERANT` variant both sides are normalized by trimming surrounding whitespace and uppercasing, and when the normalized result is entirely digits its leading zeros are stripped, an empty remainder counting as the single character "0"; a record matching no member takes disposition `REJECTED_UNKNOWN_MEMBER`. Second, the service window: the record's `service_date`, at whole-day granularity, must fall within the calendar year of the season's `measurement_year` — from January 1 through December 31 of that year, both inclusive — else the record takes `REJECTED_OUT_OF_WINDOW`. Third, duplication: a record whose normalized triple of `member_ref`, the date part of `service_date`, and `evidence_code` equals that of a record earlier in this batch's processing order, or of a record already `ACCEPTED` in another accepted batch of the same run, takes `REJECTED_DUPLICATE`; cross-batch duplicates surface only here as per-record dispositions, never as request failures. A record surviving all three checks takes disposition `ACCEPTED`. The batch's `accepted_record_count` is set to the number of accepted records, and the batch's `version` increments. The variant choice is material: with formatting noise in the source references, identical record payloads yield a strictly larger `accepted_record_count` under `TOLERANT` than under `EXACT`.

Acceptance moves a screened batch to `ACCEPTED` and is where evidence enters the numerator. Three preconditions apply in this order: the batch must be `SCREENED` (else `ERR_INVALID_STATE`); the batch's `source_type` must appear in the season's `approved_supplemental_sources` registry (else `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE`); and every record of the batch must reference a `member_ref` present among the run's non-excluded population entries (else `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR`), the comparison made under the batch's `matching_policy_used` — exact string equality under `EXACT`, normalized comparison under `TOLERANT` — with the source-approval check evaluated strictly before the per-record denominator check, per §2.9. Acceptance is also forbidden once the run's `reporting_status` has reached `SUBMITTED`, `CERTIFIED`, or `CERTIFICATION_FAILED`, surfacing as `ERR_INVALID_STATE`; this run-state gate is evaluated after the source-approval and per-record denominator checks above. On success a three-link cascade fires: each `ACCEPTED` record flips its matching population entry's `admin_compliant` to true, matched under the same `matching_policy_used`; each entry so flipped auto-closes that member's gap item in `OPEN` or `OUTREACH_DONE` status, moving it to `CLOSED_COMPLIANT` with `closure_source` `AUTO_EVIDENCE`; and the affected providers' `open_gap_count` is reconciled downward for each auto-closed gap. The run's `admin_numerator_count` and `sample_numerator_count` are then recomputed per the rate rules of §3.7, and the batch's `version` increments.

Rejection moves a screened batch to `REJECTED`. It carries no numerator or gap effects at all — only the batch's `version` increments — and `REJECTED` is terminal alongside `ACCEPTED`.

### 3.7. Rate Determination, Gap Lists, and Provider Outreach

Computing the rate moves a run from `POPULATED` to `RATE_COMPUTED`. Four guards apply: the run must be `POPULATED` (else `ERR_INVALID_STATE`); the request must carry `expected_measure_run_version` matching the run's current `version` (else `ERR_STALE_VERSION`, per §2.6; a non-integer value is `ERR_INVALID_REQUEST`); a `HYBRID` run's sample must be `FINALIZED` (a cross-entity guard, else `ERR_INVALID_STATE`); and `denominator_count` must exceed zero (else `ERR_DENOMINATOR_ZERO`).

The rate math itself is pinned as follows. The counted abstraction states are `SUBMITTED`, `CONFIRMED`, and `OVERREAD_PASSED`. The `admin_numerator_count` is the number of non-excluded population entries with `admin_compliant` true, and the `admin_rate` is that count divided by `denominator_count`, rounded half-up to 4 decimal places. For `HYBRID` runs, each sampled entry is evaluated for a sample hit: a hit exists when the chase of this run's sample whose `member_ref` matches the entry's carries an abstraction with `result` `HIT` in one of the counted states. Under the `SAMPLE_ONLY` variant a sampled entry counts toward the numerator only on a sample hit — administrative evidence is ignored; under the `ADMIN_SUPPLEMENTED` variant an entry counts on a sample hit or on `admin_compliant` true, so with identical evidence the numerator is at least as large as under `SAMPLE_ONLY` whenever any sampled member is administratively compliant without an abstraction hit. The `sample_numerator_count` is the number of sampled entries so counted. The hybrid denominator is the sample's `drawn_size` minus the run's `sample_exclusion_count`, and the `hybrid_rate` is `sample_numerator_count` divided by that denominator, rounded half-up to 4 decimal places. The `final_rate` is the `admin_rate` for `ADMINISTRATIVE` runs and the `hybrid_rate` for `HYBRID` runs. All three rates stay null until the first computation. The numerator counters are not computed only at this checkpoint: `admin_numerator_count` and `sample_numerator_count` are recomputed incrementally whenever abstractions are submitted or retracted, over-read outcomes land, the sample finalizes, or a supplemental batch is accepted, so the run's counters always reflect current evidence; the rate fields themselves change only when the rate computation runs.

The same computation regenerates the run's gap list. All of the run's existing gap items in `OPEN` or `OUTREACH_DONE` are deleted, and one new `OPEN` gap item is minted per non-excluded population entry that is not compliant under the run's collection method — compliance here meaning: for `ADMINISTRATIVE` runs, `admin_compliant`; for `HYBRID` runs, a non-sampled entry is compliant on `admin_compliant`, while a sampled entry is compliant on `sample_compliant` alone under `SAMPLE_ONLY`, or on `sample_compliant` or `admin_compliant` under `ADMIN_SUPPLEMENTED` — each stamped with the run's `run_id`, the member's `member_ref`, the attributed `provider_ref` (null when the member is unattributed), and `gap_reason` `NO_EVIDENCE_OF_SERVICE`, meaning the member sits in the denominator with no compliant evidence under the run's method. Providers' `open_gap_count` values are reconciled for every affected `provider_ref`, and the run's `version` increments.

Provider outreach works the list. A `ProviderRelations` coordinator marks outreach done, moving a gap from `OPEN` to `OUTREACH_DONE`. Closing is possible from `OUTREACH_DONE` with an `outcome` of `CLOSED_COMPLIANT` or `CLOSED_NONCOMPLIANT`; both manual closures set `closure_source` to `MANUAL` and decrement the referenced provider's `open_gap_count` by 1, and each transition increments the gap item's `version`. Recall from §3.6 that arriving supplemental evidence closes `OPEN` and `OUTREACH_DONE` gaps automatically into `CLOSED_COMPLIANT` with `closure_source` `AUTO_EVIDENCE`, likewise decrementing the provider's count — so `closure_source`, null until closure, always records whether a human or the evidence pipeline closed the gap. A provider's `open_gap_count` at any moment is exactly that provider's gap items in `OPEN` or `OUTREACH_DONE`.

For outreach planning, a computed read reports a provider's gap burden for a season, selected by the `season_id` query parameter — an unresolvable `season_id` is `ERR_NOT_FOUND`. For every measure run of that season whose pinned specification is not `RETIRED` — regardless of the run's `reporting_status` — the read counts that run's gap items matching the provider's `provider_ref` in `OPEN` or `OUTREACH_DONE`; each run contributes a line equal to that open-gap count times the specification's `reporting_weight`, with the line rounded half-up to 2 decimal places before any summation. The response's `burden_score` is the sum of those rounded lines, its `open_gap_count` is the unweighted total of open gaps across those runs, and its `per_measure_lines` is the number of runs contributing at least one open gap. The per-line-then-sum order is deliberate (§2.7): rounding only the final sum is the rejected alternative.

### 3.8. Submission, Audit Review, and Measure Certification

Submission moves a run from `RATE_COMPUTED` to `SUBMITTED` and is the deadline-critical step of the cycle. Three preconditions apply in a pinned order: the run must be `RATE_COMPUTED`, else `ERR_RUN_NOT_SUBMITTABLE` — this check is evaluated before the season-state and deadline checks; the run's season must be `OPEN`, else `ERR_SEASON_NOT_OPEN`; and the logical clock's current instant must be at or before the season's `submission_deadline`, else `ERR_SUBMISSION_DEADLINE_PASSED` — evaluated after the run-state and season-state checks. On success the run records the caller as `submitted_by_user_id`, a `HYBRID` run's sample moves from `FINALIZED` to the terminal `LOCKED` (incrementing the sample's `version`), and the run's `version` increments.

Audit engagements are scheduled by an `Auditor` supplying `season_id`, `measure_run_id`, `auditor_user_id`, `window_start`, and `window_end`. The window is **half-open**: it includes `window_start` and excludes `window_end`, and creating an engagement whose `window_end` is not strictly after `window_start` is rejected with `ERR_ENGAGEMENT_WINDOW_INVALID`. One auditor may not hold overlapping engagements: a new window is rejected with `ERR_AUDITOR_WINDOW_OVERLAP` when its start falls strictly before an existing engagement's end while its end falls strictly after that engagement's start — and because the intervals are half-open, adjacent windows where one engagement's end equals the next's start do not overlap and are permitted. A new engagement starts in `SCHEDULED` status with a null `outcome`.

Beginning the review moves the engagement from `SCHEDULED` to `IN_REVIEW`. The logical clock must currently sit inside the half-open window — at or after `window_start` and strictly before `window_end` — else `ERR_OUTSIDE_ENGAGEMENT_WINDOW`. Two cross-entity guards join it: the engagement's run must be `SUBMITTED`, and the run's `audit_status` must be `UNAUDITED` or `AUDIT_FAILED` — the latter admitting re-review after a failed audit; violations surface as `ERR_INVALID_STATE`. Beginning the review moves the run's `audit_status` to `IN_REVIEW` and increments the engagement's `version`.

Completing the review moves the engagement from `IN_REVIEW` to the terminal `COMPLETED` with an `outcome` of `PASS` or `FAIL`, recorded on the engagement. A `PASS` moves the run's `audit_status` to `AUDIT_PASSED`. A `FAIL` moves it to `AUDIT_FAILED` and additionally auto-mints an audit finding with `severity` `CRITICAL`, status `OPEN`, and the summary text "AUDIT_OUTCOME_FAIL", linked to this engagement. Either completion increments the engagement's `version`.

Beyond the automatic one, an `Auditor` files findings on an engagement by supplying `engagement_id`, a `severity` of `CRITICAL`, `MAJOR`, or `MINOR`, and a free-text `summary`; no engagement-state precondition applies to filing. Findings start `OPEN` and are resolved by moving them to the terminal `RESOLVED`, incrementing the finding's `version`. Findings attach to a run indirectly, through their engagement's `measure_run_id` — and that indirection is what gates certification.

Certification is the director's decision. A `QualityDirector` certifies a run by supplying a `decision` of `CERTIFIED` or `FAILED`. Both branches share two preconditions: the run must be `SUBMITTED` (else `ERR_INVALID_STATE`), and segregation of duties must hold — the director's `X-User-ID` must differ from the run's `submitted_by_user_id`, else `ERR_SOD_SUBMITTER_CERTIFY` (§2.8). The `CERTIFIED` branch adds two further requirements, both surfacing as `ERR_RUN_NOT_CERTIFIABLE`: the run's `audit_status` must be `AUDIT_PASSED`, and no audit finding with `severity` `CRITICAL` and status `OPEN` may be linked to the run through any engagement's `measure_run_id`. A successful certification records the director as `certified_by_user_id` and fires a two-link cascade: the season's `certified_run_count` increments by 1, and the moment that counter equals the total number of measure runs of the season, the season auto-transitions from `OPEN` to `SUBMISSION_CLOSED`. The run's `version` increments, and `CERTIFIED` is the run's terminal state. The `FAILED` branch instead moves the run to `CERTIFICATION_FAILED`, incrementing its `version`, with no season-side effects.

A failed certification is not the end of the road. Reopening moves the run from `CERTIFICATION_FAILED` back to `POPULATED`: the audit dimension resets, `audit_status` returning to `UNAUDITED`; a `HYBRID` run's sample returns from `LOCKED` to `FINALIZED`, restoring the pre-submission sample posture; and the run's `version` increments. From `POPULATED` the run can be recomputed, resubmitted, re-audited, and certified anew.

## 4. Endpoint Definitions

All endpoints live under the `/hedis` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`; actions that modify an existing resource and all reads return HTTP 200. Every state-changing request increments the target resource's `version` by 1, together with any cascaded increments described in §3 and exempting the bookkeeping mutations noted in §2.4. Error responses follow §2.2's error envelope with the codes catalogued in §5. Requests to undefined paths, and requests using an undefined method on a defined path, return `ERR_NOT_FOUND` (404).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/hedis/_clock/set_current_utc` | Set the server's logical clock; auto-closes `OPEN` seasons whose deadline the new instant passes | QualityAdmin |
| POST | `/hedis/seasons` | Create a measurement season | QualityAdmin |
| GET | `/hedis/seasons/{seasonId}` | Get a season | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/seasons/{seasonId}/open` | Open a season (`DRAFT` → `OPEN`) | QualityAdmin |
| POST | `/hedis/seasons/{seasonId}/close-submission` | Manually close submissions (`OPEN` → `SUBMISSION_CLOSED`) | QualityAdmin |
| GET | `/hedis/seasons/{id}/measure-specifications` | List specifications of a season | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/seasons/{id}/audit-engagements` | List audit engagements of a season | QualityAdmin, QualityAnalyst, Auditor, QualityDirector |
| POST | `/hedis/measure-specifications` | Load a measure specification version into a season (OCC on season version) | QualityAdmin |
| GET | `/hedis/measure-specifications/{specId}` | Get a specification | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/measure-specifications/{specId}/activate` | Activate a specification (`LOADED` → `ACTIVE`) | QualityAdmin |
| POST | `/hedis/measure-specifications/{specId}/retire` | Retire a specification (`LOADED` or `ACTIVE` → `RETIRED`) | QualityAdmin |
| POST | `/hedis/members` | Register a member | QualityAdmin |
| GET | `/hedis/members/{memberId}` | Get a member | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/members/{id}/enrollment-segments` | List enrollment segments of a member | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/enrollment-segments` | Add a closed-interval enrollment segment to a member | QualityAdmin |
| POST | `/hedis/providers` | Register a provider | QualityAdmin |
| GET | `/hedis/providers/{providerId}` | Get a provider | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/providers/{providerId}/gap-burden` | Computed provider gap-burden score for a season (per-line rounding, then sum) | QualityAdmin, QualityAnalyst, ProviderRelations, QualityDirector |
| POST | `/hedis/measure-runs` | Create a measure run; pins the specification version | QualityAnalyst |
| GET | `/hedis/measure-runs/{runId}` | Get a run | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/measure-runs` | List runs, filterable by season, specification, and reporting status | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/measure-runs/{runId}/identify-population` | Run eligible population identification; mints population entries | QualityAnalyst |
| POST | `/hedis/measure-runs/{runId}/compute-rate` | Compute admin/hybrid/final rates and regenerate the gap list (OCC on run version) | QualityAnalyst |
| POST | `/hedis/measure-runs/{runId}/submit` | Submit the run for audit (`RATE_COMPUTED` → `SUBMITTED`) | QualityAnalyst |
| POST | `/hedis/measure-runs/{runId}/certify` | Director certification decision (`SUBMITTED` → `CERTIFIED` or `CERTIFICATION_FAILED`) | QualityDirector |
| POST | `/hedis/measure-runs/{runId}/reopen` | Reopen a failed certification (`CERTIFICATION_FAILED` → `POPULATED`) | QualityAnalyst |
| GET | `/hedis/measure-runs/{id}/samples` | List samples of a run (zero or one element) | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/measure-runs/{id}/population-entries` | List population entries of a run | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/measure-runs/{id}/supplemental-batches` | List supplemental batches of a run | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/measure-runs/{id}/gap-items` | List gap items of a run (provider outreach list) | QualityAdmin, QualityAnalyst, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/measure-runs/{id}/audit-engagements` | List audit engagements of a run | QualityAdmin, QualityAnalyst, Auditor, QualityDirector |
| POST | `/hedis/population-entries/{entryId}/exclude` | Apply a pre-draw valid exclusion to a denominator entry | QualityAnalyst |
| POST | `/hedis/samples` | Draw the systematic hybrid sample for a run; auto-mints one chart chase per sampled member | QualityAnalyst |
| GET | `/hedis/samples/{sampleId}` | Get a sample | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/samples/{sampleId}/finalize` | Finalize the sample (`DRAWN` → `FINALIZED`) after chase and IRR gates | QualityAnalyst |
| POST | `/hedis/samples/{sampleId}/evaluate-irr` | Compute `irr_ratio`, set `irr_state`, re-tier `required_overread_fraction`, run selector top-up | QualityAnalyst |
| GET | `/hedis/samples/{id}/chart-chases` | List chart chases of a sample | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| GET | `/hedis/chart-chases/{chaseId}` | Get a chart chase | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/chart-chases/{chaseId}/receive` | Mark chart received (`REQUESTED` → `RECEIVED`) | QualityAnalyst |
| POST | `/hedis/chart-chases/{chaseId}/reject-unreadable` | Reject a received chart as unreadable (`RECEIVED` → `REJECTED_UNREADABLE`) | QualityAnalyst |
| POST | `/hedis/chart-chases/{chaseId}/rechase` | Re-chase (`REJECTED_UNREADABLE` or `WITHDRAWN` → `REQUESTED`; `chase_round` increments) | QualityAnalyst |
| POST | `/hedis/chart-chases/{chaseId}/withdraw` | Withdraw a pending chase (`REQUESTED` → `WITHDRAWN`) | QualityAnalyst |
| POST | `/hedis/chart-chases/{chaseId}/mark-excluded` | Record a valid sample exclusion, reducing the hybrid denominator | QualityAnalyst |
| GET | `/hedis/chart-chases/{id}/abstractions` | List abstractions of a chase | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/abstractions` | Create an abstraction on a `RECEIVED` chase; author recorded from the caller | Abstractor |
| GET | `/hedis/abstractions/{abstractionId}` | Get an abstraction | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| PUT | `/hedis/abstractions/{abstractionId}` | Edit `result` while `DRAFT` (remediation correction; author only) | Abstractor |
| POST | `/hedis/abstractions/{abstractionId}/submit` | Submit an abstraction (`DRAFT` or `REMEDIATION` → `SUBMITTED`) | Abstractor |
| POST | `/hedis/abstractions/{abstractionId}/retract` | Retract an abstraction (`SUBMITTED` or `REMEDIATION` → `DRAFT`) | Abstractor |
| GET | `/hedis/abstractions/{id}/over-reads` | List over-read reviews of an abstraction | QualityAdmin, QualityAnalyst, Abstractor, OverReader, Auditor, QualityDirector |
| POST | `/hedis/over-reads` | Record an over-read review (`AGREE` or `DISAGREE`) | OverReader |
| POST | `/hedis/supplemental-batches` | Create a supplemental data batch for a run | QualityAnalyst |
| GET | `/hedis/supplemental-batches/{batchId}` | Get a batch | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/supplemental-batches/{batchId}/screen` | Screen records: member matching per variant, measurement-year window, duplicates (`RECEIVED` → `SCREENED`) | QualityAnalyst |
| POST | `/hedis/supplemental-batches/{batchId}/accept` | Accept a screened batch; applies numerator and gap cascades (`SCREENED` → `ACCEPTED`) | QualityAnalyst |
| POST | `/hedis/supplemental-batches/{batchId}/reject` | Reject a screened batch (`SCREENED` → `REJECTED`); no numerator effects | QualityAnalyst |
| GET | `/hedis/supplemental-batches/{id}/records` | List records of a batch | QualityAdmin, QualityAnalyst, Abstractor, OverReader, ProviderRelations, Auditor, QualityDirector |
| POST | `/hedis/supplemental-records` | Add a record to a batch (batch must be `RECEIVED`) | QualityAnalyst |
| POST | `/hedis/gap-items/{gapId}/mark-outreach-done` | Provider outreach completed (`OPEN` → `OUTREACH_DONE`) | ProviderRelations |
| POST | `/hedis/gap-items/{gapId}/close` | Close a gap after outreach (`OUTREACH_DONE` → `CLOSED_COMPLIANT` or `CLOSED_NONCOMPLIANT`) | ProviderRelations |
| POST | `/hedis/audit-engagements` | Schedule an audit engagement; half-open window overlap check per auditor | Auditor |
| GET | `/hedis/audit-engagements/{engagementId}` | Get an engagement | QualityAdmin, QualityAnalyst, Auditor, QualityDirector |
| POST | `/hedis/audit-engagements/{engagementId}/begin-review` | Begin review inside the engagement window (`SCHEDULED` → `IN_REVIEW`) | Auditor |
| POST | `/hedis/audit-engagements/{engagementId}/complete` | Complete with `PASS` or `FAIL` (`IN_REVIEW` → `COMPLETED`; `FAIL` auto-mints a `CRITICAL` finding) | Auditor |
| GET | `/hedis/audit-engagements/{id}/findings` | List findings of an engagement | QualityAdmin, QualityAnalyst, Auditor, QualityDirector |
| POST | `/hedis/audit-findings` | File a finding on an engagement | Auditor |
| POST | `/hedis/audit-findings/{findingId}/resolve` | Resolve a finding (`OPEN` → `RESOLVED`) | Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them (§2 and §3); this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RUN_NOT_SUBMITTABLE` | 409 |
| `ERR_SEASON_NOT_OPEN` | 409 |
| `ERR_SOD_SELF_OVERREAD` | 403 |
| `ERR_SOD_SUBMITTER_CERTIFY` | 403 |
| `ERR_SUBMISSION_DEADLINE_PASSED` | 422 |
| `ERR_OUTSIDE_ENGAGEMENT_WINDOW` | 422 |
| `ERR_ENGAGEMENT_WINDOW_INVALID` | 422 |
| `ERR_UNAPPROVED_SUPPLEMENTAL_SOURCE` | 422 |
| `ERR_RECORD_MEMBER_NOT_IN_DENOMINATOR` | 422 |
| `ERR_DUPLICATE_MEASURE_CODE` | 409 |
| `ERR_DUPLICATE_MEMBER_REF` | 409 |
| `ERR_DUPLICATE_PROVIDER_REF` | 409 |
| `ERR_SAMPLE_ALREADY_EXISTS` | 409 |
| `ERR_DUPLICATE_ABSTRACTION` | 409 |
| `ERR_ENROLLMENT_OVERLAP` | 409 |
| `ERR_AUDITOR_WINDOW_OVERLAP` | 409 |
| `ERR_METHOD_NOT_HYBRID` | 422 |
| `ERR_EXCLUSION_NOT_ALLOWED` | 422 |
| `ERR_SAMPLE_BELOW_FLOOR` | 422 |
| `ERR_DENOMINATOR_ZERO` | 422 |
| `ERR_CHASES_IN_FLIGHT` | 422 |
| `ERR_UNABSTRACTED_CHARTS` | 422 |
| `ERR_OVERREADS_OUTSTANDING` | 422 |
| `ERR_IRR_NOT_PASSED` | 422 |
| `ERR_RUN_NOT_CERTIFIABLE` | 422 |
| `ERR_DUPLICATE_SERVICE_DATE` | 409 |

# Multi-Tiered System of Supports API — Product Requirements Document

## 1. Introduction

School districts operating a Multi-Tiered System of Supports (MTSS/RTI) run a continuous, evidence-driven cycle. Every student is universally screened during fall, winter, and spring windows; students whose scores fall below benchmark cut points are matched to targeted interventions; delivery is tracked for session fidelity; progress probes feed formal responsiveness decision rules; and standing teams meet on a regular cadence to ratify tier movement. When a student remains unresponsive at the most intensive tier beyond a district-defined number of weeks, the pipeline must trigger a referral to special-education evaluation, after which strict consent and evaluation timelines apply. Coordinating all of this across schools — with finite interventionist minutes, mandated decision rules, and outcome accountability by student subgroup — is precisely the problem this API solves.

This document specifies that API end to end. It covers district and school setup, the intervention catalog and interventionist staffing, screening windows and benchmark cut points, tier movement proposals and their ratification at team meetings, intervention plans with progress monitoring, the special-education referral lifecycle, and district outcome reporting by student subgroup. The resource model is a strict hierarchy: districts contain schools; schools contain students, screening windows, cut points, interventionists, and team meetings; students contain intervention plans, tier movements, and referrals; plans contain progress probes and intervention sessions. Responsibility is divided along an approval chain — coordinators run the screening infrastructure, team leads chair meetings and ratify tier decisions, interventionists deliver services and log data, and the special-education director drives the post-referral process.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes seven operational roles. `PlatformAdmin` is the platform operator; it creates districts and schools and operates the test clock. `DistrictCoordinator` is the district-level MTSS coordinator; it owns screening windows, benchmark cut points, and the intervention catalog. `SchoolRegistrar` is the school-level enrollment and staffing administrator. `Teacher` is the classroom teacher who administers screeners and proposes tier movements. `InterventionistRole` delivers interventions and logs sessions and probes. `TeamLead` is the MTSS team chair; it convenes meetings, ratifies movements, and ends plans. `SpEdDirector` is the special-education director who drives the referral lifecycle after it begins. An eighth name, `Any`, is a marker role used in this document to indicate that read-only endpoints accept any authenticated role. Access to every operation is restricted by role, and an attempt to act outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

When `X-User-Role` is `InterventionistRole`, `X-User-ID` is the `id` of the acting `Interventionist`; ownership checks on any resource that references an interventionist — for example, a plan's `interventionist_id` — compare the resource's foreign-key field to `X-User-ID`. Concretely, when a caller acting as `InterventionistRole` performs a plan-scoped write — recording a progress probe, recording an intervention session, pausing a plan, or resuming a plan — the targeted plan's `interventionist_id` must equal the caller's `X-User-ID`; a mismatch is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). When `X-User-Role` is any of `PlatformAdmin`, `DistrictCoordinator`, `SchoolRegistrar`, `Teacher`, `TeamLead`, `SpEdDirector`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Hierarchical Addressing and Nested Resource Validation

Every resource in the system hangs off a district. For any endpoint whose path contains multiple resource identifiers, existence is validated in a strict left-to-right order: `districtId` first, then `schoolId`, then the next-level identifier (`studentId`, `meetingId`, or `windowId`), and finally the leaf identifier (`planId`, `probeId`, or `referralId`). The request is rejected immediately with the 404 error corresponding to the first identifier that does not resolve — `ERR_DISTRICT_NOT_FOUND`, `ERR_SCHOOL_NOT_FOUND`, `ERR_STUDENT_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_MOVEMENT_NOT_FOUND`, `ERR_MEETING_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, or `ERR_INTERVENTIONIST_NOT_FOUND` — before any state or business rule is consulted. A request targeting a plan under a non-existent student therefore reports `ERR_STUDENT_NOT_FOUND` without ever looking for the plan.

Child resources carry system-assigned references to their parents. Schools and catalog entries record their owning `district_id`; windows, cut points, students, interventionists, and team meetings record their `school_id`; screening scores record both their `window_id` and the `student_id` they measure; plans record their `student_id`; probes and sessions record their `plan_id`; tier movements and referrals record their `student_id`.

Alongside the nested paths, every entity can be fetched through a flat two-segment read alias keyed by its bare identifier: a school as `/schools/{schoolId}`, a window as `/screening-windows/{windowId}`, a cut point as `/benchmark-cut-points/{cutpointId}`, a student as `/students/{studentId}`, a score as `/screening-scores/{scoreId}`, a catalog entry as `/intervention-catalog/{entryId}`, an interventionist as `/interventionists/{interventionistId}`, a plan as `/plans/{planId}`, a probe as `/probes/{probeId}`, a session as `/sessions/{sessionId}`, a movement as `/tier-movements/{movementId}`, a meeting as `/team-meetings/{meetingId}`, or a referral as `/sped-referrals/{referralId}`. Flat collection helpers likewise list children directly beneath a parent collection using a generic `{id}` placeholder — for example `/schools/{id}/students` or `/plans/{id}/probes`. These aliases return the same resource bodies as their nested counterparts and accept the same pagination parameters. Because the error catalogue defines no dedicated not-found identifier for the append-only or immutable leaf resources, an unresolvable identifier on the flat read alias for a benchmark cut point, a screening score, a progress probe, or an intervention session is rejected with `ERR_INVALID_REQUEST` carrying HTTP status 404 for this case rather than its usual 400; every other flat alias reports the resource's own dedicated `ERR_*_NOT_FOUND` (HTTP 404).

### 2.5. The Validation Pipeline

Incoming requests are checked in a fixed order, and an earlier failure always masks a later one. The authentication context comes first: missing or malformed headers produce `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Authorization comes second: a well-authenticated caller whose role is not permitted for the operation receives `ERR_INSUFFICIENT_PERMISSIONS`. Third is path existence, validated left-to-right as described in §2.4. Fourth is the validation of identifiers carried in the request body: when a plan is created, the referenced `catalog_entry_id` must exist within the request's district (otherwise `ERR_CATALOG_NOT_FOUND`, HTTP 404) and the `interventionist_id` must exist within the request's school (otherwise `ERR_INTERVENTIONIST_NOT_FOUND`, HTTP 404). Fifth are state preconditions: the target resource must be in the state the operation requires — the window `CLOSED` for scoring, the plan `ACTIVE` for probes, sessions, and exits, the meeting `CONVENED` for ratification, and so on — with violations rejected as `ERR_INVALID_STATE` (HTTP 409).

Only after all five of those stages pass do business rules run, and they too have a fixed order: the window-open rule for score recording (`ERR_WINDOW_NOT_OPEN`), then the cut-point lookup (`ERR_CUT_POINT_NOT_DEFINED`), then plan-to-catalog matching (`ERR_CATALOG_MISMATCH`), then tier-movement evidence (`ERR_TIER_MOVE_NOT_INDICATED`, `ERR_TIER_SKIP_NOT_ALLOWED`, or `ERR_INVALID_TIER_MOVE`), then the referral precondition (`ERR_SPED_REFERRAL_PRECONDITION`), then interventionist capacity (`ERR_CAPACITY_EXCEEDED`), and finally probe cadence (`ERR_PROBE_NOT_DUE`). The ordering has observable consequences: a score submitted to a window that is not open reports `ERR_WINDOW_NOT_OPEN` even if no matching cut point exists, and a probe submitted for a plan that is not `ACTIVE` surfaces `ERR_INVALID_STATE` rather than `ERR_PROBE_NOT_DUE`, because state checks precede business checks. Independently of this pipeline, a request body that is missing a required field, carries a value of the wrong type, or uses an enum value outside its defined range is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Common Resource Properties

All primary resources — districts, schools, screening windows, students, catalog entries, interventionists, plans, tier movements, team meetings, and referrals — share a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-08-01T09:15:00.123Z`) recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp, refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that increments with every modification to the resource; it backs optimistic concurrency control (§2.9).

Resources that are immutable or append-only after creation carry only `id` and `created_at`; both `updated_at` and `version` are absent from them. This applies to benchmark cut points (immutable reference data — a correction creates a new cut point rather than editing the old one), to screening scores (append-only — a correction supersedes the old row with a new one), to progress probes (append-only measurements), and to intervention sessions.

Mutations include derived-field changes. When a computed value such as a student's `current_tier`, an interventionist's `committed_minutes_per_week`, or a plan's `fidelity_pct` changes, the owning resource's `updated_at` refreshes and, for entities that carry it, its `version` increments.

### 2.7. The Logical Clock

The server keeps a logical clock rather than consulting wall-clock time. The default at server startup is 2026-08-01T00:00:00Z; the clock MUST NOT fall back to wall-clock time before the clock endpoint is called. A `PlatformAdmin` may move the clock through the admin-only test-driving capability `POST /_clock/set_current_utc`, supplying a `to_iso8601` instant; the response body returns the new `current_utc`.

The logical clock drives every time-based behavior in the system. A `SCHEDULED` screening window transitions to `OPEN` automatically when the clock reaches its `opens_on` date, and an `OPEN` window transitions to `CLOSED` automatically once the clock passes its `closes_on` date. Time-gated business rules — the window-open check for score recording and the probe cadence check — also evaluate against the logical clock.

### 2.8. The Interventionist Capacity Ledger

Each interventionist carries a `committed_minutes_per_week` ledger, initialized to zero when the interventionist is rostered, that tracks the weekly demand of their non-terminal plan assignments. Starting a plan adds the plan's `weekly_minute_cost` to the ledger; resuming a paused plan adds it again. Pausing a plan subtracts it, and so does every form of plan termination — a team-lead exit, a cancellation of a previously active plan, a ratification cascade that ends the plan, and the referral cascade.

The capacity check itself is inclusive. A proposed plan is acceptable when the interventionist's current `committed_minutes_per_week` plus the plan's `weekly_minute_cost` does not exceed the interventionist's `weekly_minute_capacity`; a proposal that lands exactly on capacity is accepted. A proposal whose total would exceed capacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422). The check runs when a plan is created and again when a paused plan is resumed, because other plans may have consumed the headroom in the interim.

### 2.9. Optimistic Concurrency Control

Several write endpoints carry an optimistic-concurrency field, and where present it is a non-optional input. Starting an intervention plan requires `expected_student_version`, capturing the client's last observed `version` of the student. Proposing a tier movement likewise requires `expected_student_version`. Pausing, resuming, exiting, or cancelling a plan requires `expected_plan_version`, the client's last observed `version` of the plan. Ratifying a tier movement at a team meeting requires `expected_student_version`. Whenever the supplied value does not match the corresponding entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Within the validation pipeline of §2.5, the version check runs after path and body-reference existence resolution and before state preconditions and business rules, so a request that would fail both a version check and a state or business check reports `ERR_STALE_VERSION`. Endpoints not listed above do not take a version field.

Two cases deserve emphasis. A ratification request must carry an `expected_student_version` matching the student's current `version`: if another writer has advanced the student's version since the client last read it — for example, by ratifying a different movement for the same student, which rewrites `current_tier` and bumps the student's `version` — the ratification is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a student record it has not observed. Likewise, a plan-exit request must carry an `expected_plan_version` matching the plan's current `version`: if a ratification cascade has already moved the plan to `EXIT_MOVED`, advancing the plan's `version`, the exit is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.10. Numeric Precision and Rounding

Every percentage and projected score in the system is an integer, and each calculation pins its own rounding rule. Fidelity percentages truncate toward zero — once when each week's figure is computed and once more when the weekly figures are averaged (§3.6). The aimline projection rounds half-up to a whole score (§3.6). The subgroup outcome index subtracts its small-cohort penalty first, then truncates toward zero, and finally floors at zero (§3.9). Percentile ranks used by the opt-in percentile-norm classification variant truncate toward zero to integer percentiles (§3.3). Slope comparisons behind the responsiveness decision are exact rational comparisons with no rounding at all (§3.6).

## 3. Business Logic & Workflows

### 3.1. Laying the Groundwork: Districts, Schools, Rosters, and the Intervention Catalog

A `PlatformAdmin` begins by creating the district. The district record carries a `name` and an `academic_year` label such as "2025-2026", plus two policy knobs with district-wide reach. The `sped_referral_min_weeks` setting — defaulting to 12 when omitted — fixes the minimum number of consecutive unresponsive weeks a student must accumulate at the most intensive tier before a special-education referral is permitted. The `fidelity_threshold_pct` setting — defaulting to 80 — expresses the minimum acceptable intervention fidelity, as a percent, for a plan's delivery to count as delivered. Schools are then created under the district with a `name` and a served grade range from `grade_span_low` (where 0 denotes kindergarten) through `grade_span_high`.

Student rosters are maintained by a `DistrictCoordinator` or a `SchoolRegistrar`. Enrolling a student records the `full_name`, the `grade_level` (0 for kindergarten through 12), and optionally a set of `subgroup_codes` used for outcome reporting — each an element of `ELL`, `FRL`, `IEP`, `BLACK`, `HISPANIC`, `WHITE`, `ASIAN`, or `MULTI`, defaulting to an empty list when omitted. Every newly enrolled student starts with `current_tier` set to `TIER_1` and `weeks_at_tier3_unresponsive` set to 0. The student list endpoint accepts optional `current_tier` and `grade_level` filters alongside pagination.

The intervention catalog is the district's menu of evidence-based programs, maintained by the `DistrictCoordinator`. Each entry records a `title` (for example, "Read Naturally"), a `subject` of `READING` or `MATH`, a `tier_target` of `TIER_2` or `TIER_3`, the served grade range from `grade_min` to `grade_max`, the `session_minutes` length of one delivered session, the expected `sessions_per_week` used in fidelity calculations, and a `probe_frequency` of `WEEKLY` or `BIWEEKLY` that governs how often progress probes come due. Entries are created with `is_active` defaulting to true, and only active entries are eligible for matching to new plans. The catalog list endpoint supports `subject`, `tier_target`, and `is_active` filters.

### 3.2. Staffing and Caseload Capacity

Interventionists are rostered at a school by a `DistrictCoordinator` or a `SchoolRegistrar`, recording a `full_name`, a `weekly_minute_capacity` of total minutes per week available for direct service, and the `subjects` they can serve — a subset of `READING` and `MATH`. A newly rostered interventionist's `committed_minutes_per_week` starts at 0 and thereafter follows the capacity ledger described in §2.8.

Capacity is the gatekeeper of plan activation. When a plan is proposed against an interventionist, the system adds the plan's weekly demand to the interventionist's current commitments and compares the total against `weekly_minute_capacity`; the boundary is inclusive, so a proposal that consumes the final available minute succeeds. Anything beyond capacity is refused with `ERR_CAPACITY_EXCEEDED`. The same re-check runs when a paused plan resumes, since the interventionist's ledger may have filled during the pause.

### 3.3. Universal Screening: Windows, Cut Points, and Risk Bands

Screening happens inside windows that a `DistrictCoordinator` schedules per school. A window is defined by its `window_kind` — `FALL`, `WINTER`, or `SPRING` — and inclusive `opens_on` and `closes_on` dates. Its lifecycle runs `SCHEDULED` to `OPEN` to `CLOSED` to `SCORED`: the system opens the window automatically when the logical clock reaches `opens_on`, closes it automatically once the clock passes `closes_on`, and a coordinator may also close a window manually ahead of schedule. The window's `screened_student_count` reflects how many score records it contains. The window list supports a `status` filter.

Before any scoring can occur, the school needs benchmark cut points. A cut point is defined for a combination of `window_kind`, `grade_level` (0 for kindergarten through 12), and `subject`, and carries two thresholds: `tier2_max_score`, at or below which a student becomes a Tier 2 candidate, and `tier3_max_score`, at or below which a student becomes a Tier 3 candidate. The `tier3_max_score` must be strictly less than the `tier2_max_score`; a definition that violates this is rejected with `ERR_INVALID_CUT_POINT` (HTTP 400). Cut points are immutable reference data — changing a threshold means defining a new cut point — and the cut-point list can be filtered by `window_kind`, `grade_level`, and `subject`.

With a window open, a `DistrictCoordinator` or a `Teacher` records screening scores by submitting the `student_id`, the `subject`, and the `raw_score`. Two guards apply, in this order. Recording is only allowed while the window's `status` is `OPEN` and the logical clock falls within the inclusive `opens_on` to `closes_on` range; otherwise the submission is rejected with `ERR_WINDOW_NOT_OPEN` (HTTP 409). Then a benchmark cut point matching the school, the window's `window_kind`, the student's `grade_level`, and the score's `subject` must exist; if none does, the submission is rejected with `ERR_CUT_POINT_NOT_DEFINED` (HTTP 422). Because score rows are append-only, correcting a miskeyed score means recording a superseding row rather than editing. The score list supports `student_id` and `subject` filters.

Every recorded score is immediately classified into a `risk_band` of `TIER_1`, `TIER_2`, or `TIER_3` by comparison against the matching cut point. Under the default cut-score rule, a `raw_score` at or below the cut point's `tier3_max_score` bands as `TIER_3`; otherwise a `raw_score` at or below the `tier2_max_score` bands as `TIER_2`; anything higher bands as `TIER_1`. A district may alternatively opt into percentile norms through the `use_percentile_norms` flag, which is not enabled by default. Under that variant, all raw scores in the same school, window kind, grade, and subject cohort are ranked — ties broken by `created_at` ascending — and each score's percentile is its rank divided by one more than the cohort size, multiplied by 100, and truncated toward zero to an integer percentile. Scores in the bottom ten percent band as `TIER_3`, scores above the tenth percentile and at or below the twenty-fifth percentile band as `TIER_2`, and the remainder band as `TIER_1`. The two variants consume identical inputs and can disagree on the same data; the cut-score variant is what the API returns and persists.

Once a window is `CLOSED`, a `DistrictCoordinator` scores it. Scoring requires the window to be `CLOSED` — attempting it in any other state is rejected with `ERR_INVALID_STATE` — and requires that every score in the window already carries a computed `risk_band`, which always holds because classification happens at record time. Scoring has a far-reaching side effect: for each student at the school whose latest `risk_band` is `TIER_2` or `TIER_3` and whose `current_tier` is still `TIER_1`, the system automatically creates a tier movement in `PROPOSED` status, from `TIER_1` to the band indicated by the screening. The window itself then settles into `SCORED`, its terminal state.

### 3.4. Tier Movement Proposals and Evidence Rules

A `Teacher`, a `TeamLead`, or a `DistrictCoordinator` may propose a tier movement for a student by supplying the target `to_tier`, a free-text `rationale`, and an `expected_student_version` carrying the client's last observed `version` of the student. The proposal captures `from_tier` from the student's `current_tier` at proposal time, starts life in `PROPOSED` status with `decided_at_meeting_id` still null, and supersedes any earlier proposals: every existing `PROPOSED` movement for the same student transitions to `SUPERSEDED` when the new one is created. Writing the proposal increments the student's `version` by one. The movement list accepts a `status` filter.

Eligibility to move depends on which tier the student currently occupies, and the evidence bar differs by direction. Throughout, "the latest screening band" means the most recently recorded `risk_band` across all of the student's scores, in any subject, within the school's most recently `SCORED` window.

For a student at `TIER_1`, screening evidence is the only admissible basis. When the latest screening band is `TIER_2` or `TIER_3`, the proposed `to_tier` must equal that band exactly — a student whose latest band is `TIER_2` may not be proposed straight to `TIER_3`, skipping a level of support. When no at-risk band exists in the most recently scored window, the proposal is rejected with `ERR_TIER_MOVE_NOT_INDICATED` (HTTP 422).

For a student at `TIER_2`, stepping down to `TIER_1` requires plan-outcome evidence: the student's latest probe decision must be `RESPONSIVE` and the plan must have accumulated at least four probes — the same bar a responsive plan exit must clear. Intensifying to `TIER_3` requires either a latest screening band of `TIER_3`, or a run in which the four most recent probes are all `NON_RESPONSIVE` while an `ACTIVE` plan is in place. Any other target tier from `TIER_2` is rejected with `ERR_INVALID_TIER_MOVE` (HTTP 422).

For a student at `TIER_3`, a direct drop to `TIER_1` is rejected with `ERR_TIER_SKIP_NOT_ALLOWED` (HTTP 422) — step-down must pass through `TIER_2`. Moving to `TIER_2` requires the latest `slope_decision` to be `RESPONSIVE` and the student's `weeks_at_tier3_unresponsive` to be below the district's `sped_referral_min_weeks`; once that counter reaches the district minimum, the student belongs in the referral pipeline rather than a simple step-down. Any other target tier from `TIER_3` is rejected with `ERR_INVALID_TIER_MOVE`.

Regardless of the student's current tier, proposing a move to the tier the student already occupies is incoherent and is rejected with `ERR_INVALID_TIER_MOVE`.

Two derived fields on the student record evolve on independent triggers and are worth keeping distinct. The `current_tier` changes only when a tier movement is ratified. The `weeks_at_tier3_unresponsive` counter changes only as probe decisions land — or when a move to `TIER_1` clears it. Both live on the same student row, and both kinds of update advance the student's `version`.

### 3.5. Activating an Intervention Plan

A `TeamLead` or a `DistrictCoordinator` starts an intervention plan for a student by submitting the chosen `catalog_entry_id`, the delivering `interventionist_id`, and an `expected_student_version`. The referenced catalog entry must exist within the district and the referenced interventionist within the school, per the body-reference stage of the validation pipeline.

Matching rules then decide whether the pairing is admissible, and a failure on any of them is rejected with `ERR_CATALOG_MISMATCH` (HTTP 422): the catalog entry's `is_active` flag must be true; the entry's `subject` must be among the interventionist's `subjects`; the student's `grade_level` must fall within the entry's `grade_min` to `grade_max` range, inclusive; and the entry's `tier_target` must equal the student's `current_tier`. Because catalog entries only ever target `TIER_2` or `TIER_3`, plans exist only at those tiers. The capacity check of §2.8 runs after matching, per the pipeline order.

Activation pins several values onto the plan. The `tier_at_start` copies the student's `current_tier` at that moment. The `started_on` records the activation date. The `weekly_minute_cost` is computed as the entry's `session_minutes` multiplied by its `sessions_per_week` and frozen on the plan, so later catalog edits never rewrite the history of running plans. The first `probe_due_on` is set to the activation date plus seven days for a `WEEKLY` probe frequency or fourteen days for `BIWEEKLY`. The plan's `fidelity_pct` begins at 100, and its `status` begins at `ACTIVE`. Activation also adds the `weekly_minute_cost` to the interventionist's `committed_minutes_per_week` and increments the student's `version` by one. The plan list accepts a `status` filter.

### 3.6. Delivery Fidelity and Progress Monitoring

While a plan runs, the delivering `InterventionistRole` records each scheduled session with its `scheduled_on` date, its scheduled `minutes`, and its `outcome` — one of `DELIVERED`, `STUDENT_ABSENT`, `STAFF_ABSENT`, or `CANCELLED`. The scheduled `minutes` must equal the catalog entry's `session_minutes` as pinned at plan activation. Sessions may only be recorded while the plan is `ACTIVE`; attempts against a plan in any other state fail state validation with `ERR_INVALID_STATE`. The session list supports an `outcome` filter.

Every recorded session recomputes the plan's `fidelity_pct`, and the rounding order is load-bearing. All of the plan's sessions are taken in `scheduled_on` ascending order with `created_at` ascending as the tie-break and grouped by ISO week. For each week, a weekly fidelity figure is computed as the count of that week's sessions whose `outcome` is `DELIVERED`, multiplied by one hundred, divided by the number of sessions scheduled that week, and truncated down to a whole percent. The plan's `fidelity_pct` is then the sum of those weekly figures divided by the number of weeks that had at least one scheduled session, again truncated down to a whole percent. This per-week-then-average order loses fractions differently than a single division of total delivered sessions by total scheduled sessions, and the latter computation must not be substituted. The value never drops below 0 and never exceeds 100.

Progress probes are recorded by an `InterventionistRole` or a `Teacher` with the `administered_on` date and the probe `score`. Cadence is enforced: a probe may only be recorded while the plan is `ACTIVE` and when the current date is on or after the plan's `probe_due_on`; an early probe is rejected with `ERR_PROBE_NOT_DUE` (HTTP 422). Each recorded probe advances `probe_due_on` by one probe interval — seven days for a `WEEKLY` frequency, fourteen for `BIWEEKLY`.

Two computed fields land on every new probe. The `aimline_score` projects where the student should be: the baseline is the student's first screening `raw_score` in the plan's subject within the school's most recently `SCORED` window at plan start, and the goal is the `tier2_max_score` of the cut point matching the student's grade, the plan's subject, and the current window kind. The expected value at the k-th probe — the first probe is k equal to 1 — is the baseline plus the gap between goal and baseline, scaled by k divided by the total probe count, rounded half-up to a whole number. The total probe count is eight for a `WEEKLY` probe frequency and four for `BIWEEKLY`.

The `slope_decision` then judges responsiveness over a trailing window of up to four probes, including the new one — all of them when fewer than four exist — ordered by `administered_on` ascending with `created_at` ascending as the tie-break. Under the default slope rule, a least-squares regression slope is fitted over the window's probe scores, using each probe's position in the window — zero for the oldest, counting up to k minus one for the newest — as the x-coordinate, and a second least-squares slope is fitted over the same window's `aimline_score` values. The decision is `RESPONSIVE` when the score slope is greater than or equal to the aimline slope, and `NON_RESPONSIVE` otherwise; the comparison is an exact rational comparison with no rounding. Some districts use an alternative endpoint rule, under which the decision is `RESPONSIVE` when the latest probe's `score` is at least its `aimline_score` and `NON_RESPONSIVE` otherwise. Both rules consume identical trailing-window data and can disagree — a student on a rising trajectory whose newest probe still sits below the aimline is `RESPONSIVE` under the slope rule but `NON_RESPONSIVE` under the endpoint rule. The slope variant is what the API persists.

Probe decisions move the student's unresponsiveness counter. When the plan's `tier_at_start` is `TIER_3` and the new decision is `NON_RESPONSIVE`, the student's `weeks_at_tier3_unresponsive` increments by one; any `RESPONSIVE` decision resets it to zero. The counter thus tracks consecutive weekly probes at `TIER_3` judged non-responsive, and it also resets when the student moves tiers. When the counter reaches the district's `sped_referral_min_weeks` and no open referral exists for the student, the system acts on its own: it creates a special-education referral in `PENDING_CONSENT` status and cascades the plan to `EXIT_SPED_REFERRAL`, releasing the plan's committed minutes. The referral flow of §3.9 takes over from there.

### 3.7. Team Meetings and the Ratification Cascade

Tier decisions are ratified at team meetings, which a `TeamLead` schedules with a `scheduled_on` date. A meeting's lifecycle runs `SCHEDULED` to `CONVENED` to `MINUTED`. Convening a scheduled meeting opens it for business; the meeting list accepts a `status` filter.

Ratification is the pivotal act. At a `CONVENED` meeting, the `TeamLead` ratifies a movement by naming its `movement_id` and supplying an `expected_student_version`. Three preconditions guard the act, and their failure is rejected as `ERR_INVALID_STATE` (HTTP 409): the meeting must be `CONVENED`, the movement must still be `PROPOSED`, and no other `PROPOSED` movement for the same student may have been created later than this one — a later proposal supersedes earlier ones, so only the freshest proposal for a student is ever ratifiable. Independently, if the student's `version` has advanced past the supplied `expected_student_version`, the ratification is rejected with `ERR_STALE_VERSION` (HTTP 412) as described in §2.9.

A successful ratification sets off a chain of effects. The movement transitions to `RATIFIED` and its `decided_at_meeting_id` is set to the meeting that decided it. The student's `current_tier` becomes the movement's `to_tier`, and when that target is `TIER_1` the student's `weeks_at_tier3_unresponsive` resets to zero. Any `ACTIVE` plan whose `tier_at_start` no longer matches the student's new tier cascades to `EXIT_MOVED`, releasing its `weekly_minute_cost` from the interventionist's `committed_minutes_per_week`. Every other `PROPOSED` movement for the same student transitions to `SUPERSEDED`. The meeting's `minuted_movement_count` — initialized at 0 when the meeting is scheduled — increments by one, and the student's `version` increments by one.

The `TeamLead` may instead reject a proposed movement at a `CONVENED` meeting by naming its `movement_id`; a rejected movement transitions to `REJECTED` and carries no further effects. Once every movement proposed for students of the meeting's school has been resolved one way or the other — no `PROPOSED` movement remains for any student of that school — the `TeamLead` marks the meeting `MINUTED`, closing it; attempting to minute a meeting while any such proposal is still pending is rejected with `ERR_INVALID_STATE`.

### 3.8. Plan Endings: Pause, Resume, Exit, and Cancellation

Plans do not always run to a natural conclusion, and each way of ending one has its own gate. All of these operations target a specific plan and carry `expected_plan_version`; a mismatch with the plan's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), per §2.9.

Pausing is the reversible hold. An `InterventionistRole` or a `TeamLead` may pause a plan, but only while the student's `current_tier` still equals the plan's `tier_at_start` — a student whose tier has moved no longer fits the plan's premise. Pausing transitions the plan from `ACTIVE` to `PAUSED`, subtracts its `weekly_minute_cost` from the interventionist's `committed_minutes_per_week`, and increments the plan's `version` by one. Resuming reverses it: the same two roles may return a `PAUSED` plan to `ACTIVE`, subject to a fresh capacity check against the interventionist's ledger (`ERR_CAPACITY_EXCEEDED` if the headroom is gone), after which the minutes are re-committed and the plan's `version` increments again.

Exiting is the `TeamLead`'s prerogative and is steered by the `exit_kind` supplied in the request. An exit to `EXIT_RESPONSIVE` requires the student's latest `slope_decision` to be `RESPONSIVE` and the plan to have accumulated at least four probes; it releases the plan's committed minutes and automatically creates a tier movement in `PROPOSED` status stepping the student one level down — from `tier_at_start` to `TIER_1` when the plan started at `TIER_2`, or to `TIER_2` when it started at `TIER_3`. An exit to `EXIT_NO_PROGRESS` requires the latest four probes all to be `NON_RESPONSIVE` and the student's `weeks_at_tier3_unresponsive` to remain below the district's `sped_referral_min_weeks`; a student at or above that threshold must go through the referral flow instead. Both exit kinds release the plan's minutes from the interventionist's ledger and increment the plan's `version` by one, and an exit whose evidence preconditions are not met is rejected with `ERR_INVALID_STATE`. Requests against a plan that is not `ACTIVE` fail state validation the same way.

Cancellation abandons a plan without outcome. A `TeamLead` may cancel an `ACTIVE` plan only while no progress probe exists on it yet; the cancellation releases its committed minutes. A `PAUSED` plan may be cancelled without that restriction, and because its minutes were already released at pause time, no further ledger adjustment occurs. Either way the plan lands in `CANCELLED` and its `version` increments by one. The terminal states of a plan are `EXIT_RESPONSIVE`, `EXIT_MOVED`, `EXIT_SPED_REFERRAL`, `EXIT_NO_PROGRESS`, and `CANCELLED`; of these, `EXIT_MOVED` and `EXIT_SPED_REFERRAL` are reached only by the system cascades described in §3.7 and §3.6, never by direct request.

### 3.9. Special Education Referral and District Outcome Reporting

A referral to special-education evaluation opens when a student has exhausted the tiered model's evidence runway. A `TeamLead` or a `SpEdDirector` may open one manually; the preconditions are that the student's `current_tier` is `TIER_3`, that `weeks_at_tier3_unresponsive` has reached the district's `sped_referral_min_weeks`, and that no other open referral — one in `PENDING_CONSENT`, `CONSENTED`, or `EVAL_IN_PROGRESS` — exists for the student. A request failing any of these is rejected with `ERR_SPED_REFERRAL_PRECONDITION` (HTTP 422). The system can also open a referral on its own when a probe pushes the counter to the district minimum, as described in §3.6. Either way, creation records the student's current `ACTIVE` plan as the `triggered_plan_id`, cascades that plan to `EXIT_SPED_REFERRAL` with its committed minutes released, and sets the referral's `status` to `PENDING_CONSENT` with `consent_received_on` still null. The referral list supports a `status` filter.

From there, the `SpEdDirector` drives the lifecycle. Recording parent consent with a `consent_received_on` date moves the referral from `PENDING_CONSENT` to `CONSENTED` and sets `evaluation_due_on` to sixty calendar days after the consent date. Starting the evaluation moves it to `EVAL_IN_PROGRESS`. Determination then resolves the referral to `ELIGIBLE` or `NOT_ELIGIBLE` according to the submitted `outcome`; when the outcome is eligibility, the code `IEP` is appended to the student's `subgroup_codes` if absent — notably, this does not remove the student from the MTSS tier system, and the student can be dual-served. A referral may also be withdrawn, transitioning to `WITHDRAWN`, from either `PENDING_CONSENT` or `CONSENTED`. The terminal states are `ELIGIBLE`, `NOT_ELIGIBLE`, and `WITHDRAWN`.

Finally, the district can read its results back through the outcome report, which takes a `window_id` and computes, on read, a per-subgroup outcome index. For each subgroup code in `ELL`, `FRL`, `IEP`, `BLACK`, `HISPANIC`, `WHITE`, `ASIAN`, and `MULTI`, the cohort is every student in the district whose `subgroup_codes` contain that code. The at-risk subset is those cohort members whose latest `risk_band` in the target window is `TIER_2` or `TIER_3`. The moved-up subset is the at-risk members whose `current_tier` today is strictly lower-risk than their band — a `TIER_2` band now standing at `TIER_1`, or a `TIER_3` band now standing at `TIER_1` or `TIER_2`. The raw index is the moved-up count multiplied by one hundred and divided by the at-risk count, with the denominator pinned at a minimum of one so that an empty at-risk cohort yields zero rather than an undefined value. A small-cohort penalty then applies: when the subgroup's total district enrollment is fewer than thirty students, five points are subtracted from the raw index before any rounding. The published index is the adjusted value truncated down to a whole number, floored at zero — penalty first, truncation second, floor last. The report returns an object mapping each subgroup code to its integer index.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code with the created resource in the `data` field. Operations that read or modify an existing resource — including the action operations that drive state transitions — return a `200 OK` status code with the resource (or, for the outcome report and clock endpoints, the computed object) in the `data` field. Readers should reconstruct each endpoint's full request and response contract from the narratives in §3; the table below is an index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/districts` | Create a district | PlatformAdmin |
| GET | `/districts` | List districts | Any |
| GET | `/districts/{districtId}` | Get a district | Any |
| GET | `/districts/{districtId}/schools` | List schools in a district | Any |
| POST | `/districts/{districtId}/schools` | Create a school | PlatformAdmin |
| GET | `/districts/{districtId}/schools/{schoolId}` | Get a school | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/screening-windows` | Create a screening window | DistrictCoordinator |
| GET | `/districts/{districtId}/schools/{schoolId}/screening-windows` | List screening windows for a school | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/screening-windows/{windowId}` | Get a screening window | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/screening-windows/{windowId}/close` | Manually close a window before its closes_on | DistrictCoordinator |
| POST | `/districts/{districtId}/schools/{schoolId}/screening-windows/{windowId}/score` | Score a closed window; computes risk bands and auto-proposes tier movements | DistrictCoordinator |
| POST | `/districts/{districtId}/schools/{schoolId}/benchmark-cut-points` | Define a cut point | DistrictCoordinator |
| GET | `/districts/{districtId}/schools/{schoolId}/benchmark-cut-points` | List cut points | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students` | Enroll a student | DistrictCoordinator, SchoolRegistrar |
| GET | `/districts/{districtId}/schools/{schoolId}/students` | List students | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}` | Get a student | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/screening-windows/{windowId}/scores` | Record a screening score | DistrictCoordinator, Teacher |
| GET | `/districts/{districtId}/schools/{schoolId}/screening-windows/{windowId}/scores` | List scores in a window | Any |
| POST | `/districts/{districtId}/intervention-catalog` | Add an intervention catalog entry | DistrictCoordinator |
| GET | `/districts/{districtId}/intervention-catalog` | List catalog entries | Any |
| GET | `/districts/{districtId}/intervention-catalog/{entryId}` | Get a catalog entry | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/interventionists` | Add an interventionist | DistrictCoordinator, SchoolRegistrar |
| GET | `/districts/{districtId}/schools/{schoolId}/interventionists` | List interventionists | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/interventionists/{interventionistId}` | Get an interventionist | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans` | Start an intervention plan | TeamLead, DistrictCoordinator |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans` | List plans for a student | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}` | Get a plan | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/pause` | Pause an active plan | InterventionistRole, TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/resume` | Resume a paused plan | InterventionistRole, TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/exit` | Exit a plan (responsive or no-progress) | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/cancel` | Cancel a plan (only when no probes yet, or when paused) | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/probes` | Record a progress probe | InterventionistRole, Teacher |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/probes` | List probes for a plan | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/sessions` | Record a scheduled/delivered session | InterventionistRole |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/plans/{planId}/sessions` | List sessions for a plan | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/tier-movements` | Propose a tier movement | Teacher, TeamLead, DistrictCoordinator |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/tier-movements` | List tier movements for a student | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/tier-movements/{movementId}` | Get a tier movement | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/team-meetings` | Schedule a team meeting | TeamLead |
| GET | `/districts/{districtId}/schools/{schoolId}/team-meetings` | List team meetings | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/team-meetings/{meetingId}` | Get a team meeting | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/team-meetings/{meetingId}/convene` | Convene a scheduled meeting | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/team-meetings/{meetingId}/ratify` | Ratify a proposed tier movement at this meeting | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/team-meetings/{meetingId}/reject` | Reject a proposed tier movement | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/team-meetings/{meetingId}/minute` | Mark a meeting as minuted (closes it) | TeamLead |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals` | Open a special-education referral | TeamLead, SpEdDirector |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals` | List referrals for a student | Any |
| GET | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}` | Get a referral | Any |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}/record-consent` | Record parent consent | SpEdDirector |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}/start-evaluation` | Begin the evaluation | SpEdDirector |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}/determine` | Determine eligibility | SpEdDirector |
| POST | `/districts/{districtId}/schools/{schoolId}/students/{studentId}/sped-referrals/{referralId}/withdraw` | Withdraw a referral | SpEdDirector |
| GET | `/districts/{districtId}/outcome-report` | Compute the per-subgroup outcome index for a window | Any |
| GET | `/schools/{schoolId}` | Flat read alias for School | Any |
| GET | `/screening-windows/{windowId}` | Flat read alias for ScreeningWindow | Any |
| GET | `/benchmark-cut-points/{cutpointId}` | Flat read alias for BenchmarkCutPoint | Any |
| GET | `/students/{studentId}` | Flat read alias for Student | Any |
| GET | `/screening-scores/{scoreId}` | Flat read alias for ScreeningScore | Any |
| GET | `/intervention-catalog/{entryId}` | Flat read alias for InterventionCatalogEntry | Any |
| GET | `/interventionists/{interventionistId}` | Flat read alias for Interventionist | Any |
| GET | `/plans/{planId}` | Flat read alias for StudentPlan | Any |
| GET | `/probes/{probeId}` | Flat read alias for ProgressProbe | Any |
| GET | `/sessions/{sessionId}` | Flat read alias for InterventionSession | Any |
| GET | `/tier-movements/{movementId}` | Flat read alias for TierMovement | Any |
| GET | `/team-meetings/{meetingId}` | Flat read alias for TeamMeeting | Any |
| GET | `/sped-referrals/{referralId}` | Flat read alias for SpedReferral | Any |
| GET | `/districts/{id}/schools` | Flat list of schools under a district | Any |
| GET | `/districts/{id}/intervention-catalog` | Flat list of catalog entries under a district | Any |
| GET | `/schools/{id}/screening-windows` | Flat list of windows under a school | Any |
| GET | `/schools/{id}/benchmark-cut-points` | Flat list of cut points under a school | Any |
| GET | `/schools/{id}/students` | Flat list of students under a school | Any |
| GET | `/schools/{id}/interventionists` | Flat list of interventionists under a school | Any |
| GET | `/schools/{id}/team-meetings` | Flat list of team meetings under a school | Any |
| GET | `/screening-windows/{id}/scores` | Flat list of scores under a window | Any |
| GET | `/students/{id}/scores` | Flat list of scores for a student | Any |
| GET | `/students/{id}/plans` | Flat list of plans for a student | Any |
| GET | `/students/{id}/tier-movements` | Flat list of tier movements for a student | Any |
| GET | `/students/{id}/sped-referrals` | Flat list of sped referrals for a student | Any |
| GET | `/intervention-catalog/{id}/plans` | Flat list of plans using a catalog entry | Any |
| GET | `/interventionists/{id}/plans` | Flat list of plans served by an interventionist | Any |
| GET | `/plans/{id}/probes` | Flat list of probes under a plan | Any |
| GET | `/plans/{id}/sessions` | Flat list of sessions under a plan | Any |
| GET | `/plans/{id}/sped-referrals` | Flat list of referrals triggered by a plan | Any |
| GET | `/team-meetings/{id}/tier-movements` | Flat list of movements decided at a meeting | Any |
| POST | `/_clock/set_current_utc` | Set the logical clock (default at startup is 2026-08-01T00:00:00Z; never falls back to wall-clock before being called) | PlatformAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions for each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_DISTRICT_NOT_FOUND` | 404 Not Found |
| `ERR_SCHOOL_NOT_FOUND` | 404 Not Found |
| `ERR_STUDENT_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_MOVEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_MEETING_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_CATALOG_NOT_FOUND` | 404 Not Found |
| `ERR_INTERVENTIONIST_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_CUT_POINT_NOT_DEFINED` | 422 Unprocessable Entity |
| `ERR_INVALID_CUT_POINT` | 400 Bad Request |
| `ERR_CATALOG_MISMATCH` | 422 Unprocessable Entity |
| `ERR_TIER_MOVE_NOT_INDICATED` | 422 Unprocessable Entity |
| `ERR_TIER_SKIP_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_INVALID_TIER_MOVE` | 422 Unprocessable Entity |
| `ERR_SPED_REFERRAL_PRECONDITION` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROBE_NOT_DUE` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |

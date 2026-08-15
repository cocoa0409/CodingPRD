# Shelf-Life & Sensory Panel Testing API — Product Requirements Document

## 1. Introduction

Food and beverage manufacturers stake label claims — "best within 90 days", "new high-barrier film extends freshness by 25%" — on evidence that is expensive to produce and easy to get wrong. A sensory testing laboratory must choreograph real-time and accelerated shelf-life studies, recruit and qualify trained panelists, pull and track physical sample units from temperature-controlled chambers, run attribute-scoring sessions with statistical rigor, correlate microbial and chemical endpoints against sensory failure, and ultimately issue a client-facing report whose date-code recommendation and marketing claims can withstand scrutiny. This document specifies the Shelf-Life & Sensory Panel Testing API, the system of record for that entire operation.

The API serves two study designs — real-time storage and accelerated Q10 projection — and treats the laboratory's prepaid retainer hours, chamber occupancy, panel quorum sizing, and segregation-of-duties review chain as first-class concerns rather than afterthoughts. All business resources are mounted under the `/sensory-lab` prefix, with a single administrative capability for driving the server's logical clock mounted separately. The intended audience is the engineering team building the service: every behavioral rule below is normative.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes seven distinct roles: `LabDirector`, `SensoryScientist`, `PanelCoordinator`, `Panelist`, `LabAnalyst`, `QAOfficer`, and `Client`. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Access to specific operations is restricted by role as enumerated in §4; an authenticated user attempting an operation outside their role, or violating an entity-backed ownership rule, is rejected with `ERR_FORBIDDEN_ROLE`.

The meaning of `X-User-ID` depends on the role presented:

- When `X-User-Role` is `Panelist`, `X-User-ID` is the `id` of the acting `Panelist` record; ownership checks on any resource that references a `Panelist` — in particular an assignment's `panelist_id` — compare that foreign-key field to `X-User-ID`.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `ClientAccount`; ownership checks compare the study's `client_id` on the relevant report chain to `X-User-ID`.
- When `X-User-Role` is `LabDirector`, `SensoryScientist`, `PanelCoordinator`, `LabAnalyst`, or `QAOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `author_user_id` on a `StudyReport` at creation or as `verified_by` on a `ClaimSubstantiation` at verification — but does not compare it to any entity's `id`. Segregation-of-duties checks compare these recorded opaque identifiers against the acting `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties on the timestamp broken by insertion (creation) order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of returned items is still below `total_count`.

List endpoints accept additional filter parameters specific to their resource — for example `tier` on the client list, `client_id` and `status` on the study list, `study_id` on the arm list, `study_id` and `status` on the time-point list, `study_id`/`arm_id`/`chamber_id`/`time_point_id`/`session_id`/`status`/`unit_purpose` on the sample-unit list, `status` on the panelist list, `study_id`/`time_point_id`/`arm_id`/`status`/`makeup_of_id` on the session list, `session_id`/`panelist_id`/`status` on the assignment list, `assignment_id` on the score list, `study_id`/`arm_id`/`time_point_id`/`test_type` on the lab-result list, `study_id`/`arm_id`/`status` on the recommendation list, `study_id`/`status`/`pinned_recommendation_id` on the report list, and `report_id`/`verdict` on the claim list.

### 2.4. The Logical Clock and Study-Day Reckoning

Every time-dependent rule in the system reads a single server-held logical clock — never wall-clock time. Before any operator has set it, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `LabDirector` may advance the clock through an administrative capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`; the capability sets the clock to exactly the supplied instant, whether forward or backward, and this is the only way time moves — the clock never falls back to wall-clock time on its own. Here and wherever the API accepts an ISO 8601 timestamp, a value without an explicit offset is read as UTC.

A study's **current study day** is derived from this clock: the number of whole days elapsed since the study's `actual_start_utc`, computed by taking the elapsed seconds between the logical clock and `actual_start_utc`, dividing by 86,400, and rounding down to a whole number. The pull window of §3.3 and the schedule-extension rule of §3.2 both speak in terms of the current study day.

### 2.5. Common Resource Properties and Immutable Event Records

All primary resources — client accounts, studies, arms, sampling time points, chambers, sample units, panelists, evaluation sessions, panel assignments, date-code recommendations, study reports, and claim substantiations — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-08-01T09:15:00.123Z`) read from the logical clock of §2.4 and recorded at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed from the same logical clock upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 at creation and increments by exactly 1 with every modification to the resource, including cascaded mutations and state transitions, and that anchors optimistic concurrency control as described in §2.7.

Two resources are deliberately different. An `AttributeScore` and a `LabTestResult` are immutable event records: each carries only `id` and `created_at`, and both `updated_at` and `version` are absent — once recorded, a score or a lab result is never edited; corrections happen through new observations and the recomputation cascades described in §3.5 and §3.6.

### 2.6. Validation Order and Error Precedence

Every request is validated against an ordered ladder of checks, and the first rung that fails determines the error returned. The ladder is:

1. **Authentication context.** Both headers present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (401). Applies to every endpoint.
2. **Role authorization.** The role is listed for the endpoint, else `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint. Entity-backed ownership rules — a panelist scoring only their own assignment, a client requesting changes only on their own study's report, author-only report submission and claim attachment — are evaluated as soon as the resource they anchor on has been resolved under rung 3, and therefore after that resource's existence check and before any state gate on it: an unknown anchoring identifier yields `ERR_NOT_FOUND`, never `ERR_FORBIDDEN_ROLE`.
3. **Existence.** Path identifiers and body foreign-key references are resolved left to right; the first reference that does not exist yields `ERR_NOT_FOUND` (404).
4. **Optimistic concurrency.** On the two OCC-guarded writes of §2.7, `expected_study_version` must match the study's current `version`, else `ERR_STALE_STUDY_VERSION` (412). This check sits after existence and before state evaluation.
5. **State-machine gates.** The target resource's state must permit the requested transition, else the applicable one of `ERR_INVALID_STUDY_STATE`, `ERR_INVALID_SESSION_STATE`, `ERR_INVALID_TIME_POINT_STATE`, `ERR_INVALID_PANELIST_STATE`, `ERR_INVALID_ASSIGNMENT_STATE`, `ERR_INVALID_SAMPLE_STATE`, `ERR_INVALID_REPORT_STATE`, `ERR_RECO_NOT_PROPOSED`, `ERR_SESSION_UNDER_QUORUM`, or `ERR_CLAIM_ALREADY_VERIFIED` (all 409).
6. **Data integrity and segregation of duties.** A lab result's `measured_value` must lie within its method's valid measurement range (else `ERR_MEASUREMENT_OUT_OF_RANGE`, 422); an attribute `score` must lie within the fifteen-point scale (else `ERR_SCORE_OUT_OF_RANGE`, 422); a `QAOfficer` acting on a report or its claims must not be the report's author (else `ERR_SEGREGATION_OF_DUTIES`, which returns 403 rather than 422). These checks guard lab-result recording, score submission, QA approval and rejection, and claim verification.
7. **Uniqueness and cardinality.** Duplicate emails, a second control arm, a repeated packaging variant or sampling day within a study, a second live session for the same arm and time point, a repeated attribute score on one assignment, or an over-full session roster are rejected with the applicable one of `ERR_EMAIL_NOT_UNIQUE`, `ERR_CONTROL_ARM_EXISTS`, `ERR_DUPLICATE_ARM_VARIANT`, `ERR_DUPLICATE_TIME_POINT_DAY`, `ERR_SESSION_EXISTS`, `ERR_SCORE_ALREADY_SUBMITTED`, or `ERR_SESSION_FULL` (all 409).
8. **Clock-relative temporal windows.** Pulls outside their day window yield `ERR_PULL_WINDOW_VIOLATION` (409); opening a session outside its window yields `ERR_OUTSIDE_SESSION_WINDOW` (409). A session created with an end that is not strictly after its start is instead a malformed request, `ERR_INVALID_REQUEST` (400); within session planning this malformed-window check fires after the rung-9 belonging checks, and within makeup scheduling after the source-session state gate, per the pinned orders of §3.5.
9. **Cross-entity referential coherence.** Arms, time points, chambers, recommendations, reports, and claims must belong to the study chain implied by the request, else the applicable one of `ERR_ARM_STUDY_MISMATCH`, `ERR_TIME_POINT_STUDY_MISMATCH`, `ERR_CHAMBER_TEMP_MISMATCH`, or `ERR_REPORT_STUDY_MISMATCH` (all 422), or `ERR_PANELIST_DOUBLE_BOOKED` (which returns 409 rather than 422). These checks guard pulls, lab-result recording, assignment creation, makeup scheduling, claim verification, and recommendation attachment.
10. **Fiscal sufficiency.** At study activation only, the client's retainer balance is checked last — after the study-state gate — and shortfalls are rejected with `ERR_INSUFFICIENT_RETAINER_HOURS` (402).

Checks this ladder does not name — required-field presence, field types, and enum membership, all `ERR_INVALID_REQUEST` (400) — are evaluated at the point each endpoint encounters them rather than as ladder rungs; where an endpoint's prose pins an order among them relative to the ladder (as §3.5 does for session planning and §3.6 for lab-result recording), that order governs.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control on the parent study, and both name the same field.

Updating a study's design fields — `PUT /sensory-lab/studies/{id}` — requires the request to carry `expected_study_version` holding the study's `version` as the client last observed it. Because every mutation of the study — any field update, any transition, any cascade that touches the study — advances `Study.version` by 1, an `expected_study_version` that no longer matches the study's current `version` means the client's design view is stale, and the update is rejected with `ERR_STALE_STUDY_VERSION` (HTTP 412). On this endpoint the study itself is resolved first; a request then missing `expected_study_version`, or carrying a non-integer value, is rejected with `ERR_INVALID_REQUEST` (400) before the version comparison runs.

Proposing a date-code recommendation — `POST /sensory-lab/date-code-recommendations` — is guarded identically: the creation request must carry `expected_study_version` matching the target study's current `version`. Here the field's presence and integer type are validated before any reference is resolved — a missing or non-integer value is `ERR_INVALID_REQUEST` (400) — and the version comparison runs after existence and before the study-state gate, per §2.6. Recommendation creation legitimately supersedes the arm's prior `PROPOSED` recommendation, so a second creator holding a stale study version must be refused with `ERR_STALE_STUDY_VERSION` (HTTP 412) rather than silently superseding on old data. No other endpoint accepts a version field; requests to all other operations are processed without an OCC check.

### 2.8. Numeric Precision and Rounding Conventions

Different quantities carry different, deliberately chosen precisions, and the rounding method is always **round half up** unless stated otherwise:

- Attribute means (including `overall_mean`), both panelist consistency indexes, the consumed-hours grand total, and claim-percentage figures are expressed at **2 decimal places**, rounded half up.
- Real-time-equivalent failure days (`computed_failure_day_equiv`, `earliest_failure_day_equiv`) are expressed at **3 decimal places**, rounded half up.
- The micro–sensory correlation `coefficient` is expressed at **4 decimal places**, rounded half up.
- Session room time at settlement is quantized **per session** by rounding the duration up to the next quarter-hour before any cross-session summation, per the pinned order of §3.7.
- Date-code day counts are **whole days** produced by rounding down at each step of the recommendation formula.
- Session quorum sizes are whole panelists produced by rounding the raw power computation up and only then applying the clamp bounds.
- The significance threshold `significance_delta` is computed at full internal precision and is not rounded before use; the rounded `overall_mean` values are what enter the comparisons.

### 2.9. Chamber Occupancy Accounting

Each storage chamber's `reserved_units` is a derived counter with a strict invariant: at all times it equals the number of sample units whose `chamber_id` names that chamber and whose status is either `STORED` or `CHECKED_OUT`. Because both of those statuses count, moving a unit between them — checking a unit out for a session and later returning it — is occupancy-neutral. Only transitions that leave the counted set change occupancy: consuming, discarding, expiry by the retain sweep, and the abort cascade each decrement `reserved_units` by one per affected unit, while a pull increments it by the pulled quantity. Pull legality is decided against this counter: a pull is lawful whenever the chamber's `reserved_units` plus the requested `quantity` is less than or equal to `capacity_units` — filling a chamber exactly to capacity is allowed — and is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED` otherwise.

## 3. Business Logic & Workflows

### 3.1. Client Accounts and Retainer Funding

Every engagement begins with a `LabDirector` registering a **client account** under a company `name` and a `contact_email`. The email must be well-formed — a malformed address is `ERR_INVALID_REQUEST` — and unique across all clients, with duplicates rejected as `ERR_EMAIL_NOT_UNIQUE`. The account's service `tier` is either `STANDARD` or `PREMIUM`, defaulting to `STANDARD` when omitted. New accounts start with a `retainer_hours_balance` of zero prepaid laboratory hours and an `active_study_count` of zero; the latter tracks how many of the client's studies are currently in `SCHEDULED`, `IN_PROGRESS`, `ANALYSIS`, or `REPORTING` status.

Retainer hours are the laboratory's fiscal lifeblood. A `LabDirector` tops up an account by supplying `hours`, which must be greater than zero — a non-positive top-up is `ERR_INVALID_REQUEST` — and the amount is added to `retainer_hours_balance`. Hours leave the balance only through study activation and are returned or settled when studies abort or complete, as detailed in §3.2 and §3.7.

### 3.2. Designing and Approving a Study

A `SensoryScientist` frames a new **study** by naming the owning client via `client_id` and the product under test via `product_name`, declaring the `study_type` as `REAL_TIME` or `ACCELERATED`, and fixing the experimental design: the chamber temperature `storage_temp_c`, the claimed `target_shelf_life_days`, an integer number of days, the `sensory_fail_threshold` at or below which an `OVERALL` attribute mean marks the sensory endpoint as tripped, the `min_detectable_difference` that drives session power sizing and significance screening, and the `planned_start_utc`. Two fields carry defaults: `reference_temp_c`, the ambient control temperature used by Q10 projection, defaults to 20; and `q10_factor` defaults to 2.0. An `ACCELERATED` study is only well-formed when its `q10_factor` is strictly greater than 1.0 and its `storage_temp_c` exceeds its `reference_temp_c`; otherwise creation fails with `ERR_INVALID_REQUEST`. A new study is born in `DRAFT` with `reserved_hours_escrow` at zero, `consumed_hours` at zero, `earliest_failure_day_equiv` null — nothing has tripped yet — and `actual_start_utc` null until activation.

While a study remains in `DRAFT`, the scientist may revise its design fields — `product_name`, `storage_temp_c`, `reference_temp_c`, `q10_factor`, `target_shelf_life_days`, `sensory_fail_threshold`, `min_detectable_difference`, and `planned_start_utc` — through the OCC-guarded update of §2.7, which increments `Study.version` by 1 on success; every such update re-validates the `ACCELERATED` well-formedness rule against the merged field values and fails with `ERR_INVALID_REQUEST` when the result would violate it. Once the study has left `DRAFT`, design updates are refused with `ERR_INVALID_STUDY_STATE`.

Design work also means defining the study's structure, and both kinds of structure are only editable in early states. **Packaging arms** are added with a `packaging_variant` of `STANDARD_FILM`, `HIGH_BARRIER`, `MAP`, or `VACUUM`, plus an optional `is_control` flag defaulting to false. Arms may only be created while the study is in `DRAFT` (else `ERR_INVALID_STUDY_STATE`); the same variant may not appear twice within one study (`ERR_DUPLICATE_ARM_VARIANT`); and at most one arm per study may be flagged as the control — a second control arm is rejected with `ERR_CONTROL_ARM_EXISTS`. Each arm carries a `computed_failure_day_equiv`, the earliest tripped endpoint day for that arm in real-time-equivalent days, which stays null until something trips. **Sampling time points** are added with a `day_index` — an integer study day of the pull, zero or greater — unique within the study (else `ERR_DUPLICATE_TIME_POINT_DAY`). Time points may be created while the study is in `DRAFT`; after a study has been reopened into fieldwork, additional time points are also accepted, but only when the new `day_index` is strictly greater than the current study day as defined in §2.4, and any attempt outside those two situations is `ERR_INVALID_STUDY_STATE`. Every time point begins `PENDING`.

With arms and a schedule in place, the scientist submits the design for review, moving the study `DRAFT → DESIGN_REVIEW`. Submission enforces its four checks in order: the study must currently be `DRAFT` (else `ERR_INVALID_STUDY_STATE`); at least one arm must exist (else `ERR_NO_ARMS_DEFINED`); exactly one arm must be flagged `is_control` (else `ERR_NO_CONTROL_ARM`); and at least one sampling time point must exist (else `ERR_NO_TIME_POINTS`). A `LabDirector` then adjudicates: approving moves the study `DESIGN_REVIEW → SCHEDULED`, while rejecting returns it `DESIGN_REVIEW → DRAFT` for rework. Each of these study transitions increments `Study.version` by 1 and refreshes `updated_at`.

Activation — the `SCHEDULED → IN_PROGRESS` transition driven by a `SensoryScientist` — is where the retainer escrow attaches. The reserved hours required are a base of 10 hours, plus 2 hours per sampling time point, plus 4 hours per study arm. The fiscal check is evaluated last, after the state gate: if the client's `retainer_hours_balance` falls short of the reserved hours required, activation is rejected with `ERR_INSUFFICIENT_RETAINER_HOURS`. On success the study captures `actual_start_utc` from the logical clock, the reserved amount is debited from the client's `retainer_hours_balance` and parked in the study's `reserved_hours_escrow`, and the client's `active_study_count` increases by 1.

Fieldwork ends when the scientist closes it, moving `IN_PROGRESS → ANALYSIS`. Closure requires that every sampling time point of the study rests in `EVALUATED`, `CLOSED`, or `SKIPPED` — any straggler in `PENDING` or `PULLED` draws `ERR_OPEN_TIME_POINTS_REMAIN` — and that every evaluation session of the study is `ANALYZED` or `CANCELLED`, else `ERR_SESSIONS_STILL_OPEN`. Analysis is not one-way: a scientist may reopen fieldwork, moving `ANALYSIS → IN_PROGRESS`, which is precisely what licenses the extended-schedule time-point creation described above, and the `IN_PROGRESS → ANALYSIS → IN_PROGRESS` loop may repeat as often as the science demands. From `ANALYSIS`, the study advances to `REPORTING` automatically once every arm holds an accepted date-code recommendation (§3.7), and from `REPORTING` it completes automatically when its report is released (§3.7).

A `LabDirector` may abort a study from `DRAFT`, `DESIGN_REVIEW`, `SCHEDULED`, or `IN_PROGRESS`, moving it into the terminal `ABORTED` status; from any other status the attempt is `ERR_INVALID_STUDY_STATE`. Abortion is fully compensating: the entire `reserved_hours_escrow` is credited back to the client's `retainer_hours_balance` and the escrow zeroed (no consumption is charged); when the study was in `SCHEDULED` or `IN_PROGRESS`, the client's `active_study_count` decreases by 1; all of the study's evaluation sessions in `PLANNED` or `OPEN` are cancelled and their assignments in `ASSIGNED` are excused; all of the study's sample units in `STORED` or `CHECKED_OUT` are discarded with chamber occupancy recomputed per §2.9; and every date-code recommendation of the study in `PROPOSED` or `ACCEPTED` is superseded, which in turn flags any pinned reports exactly as the supersession cascade of §3.7 describes.

### 3.3. Chambers, Sample Pulls, and Unit Custody

Physical custody starts with the chambers. A `LabDirector` registers each **storage chamber** under a unique `chamber_code` (duplicates are `ERR_INVALID_REQUEST`), a holding temperature `temp_c`, and a `capacity_units` ceiling — the maximum number of concurrently stored sample units, which must be a positive integer. The chamber's `reserved_units` counter begins at zero and thereafter obeys the occupancy invariant of §2.9.

Pulling samples is the act that turns a schedule into inventory. A `SensoryScientist` pulls against a sampling time point by supplying the `chamber_id` to draw from, the `arm_id` being provisioned, the `quantity` of units to create — which must be a positive whole number (an integer-valued numeric is accepted), else `ERR_INVALID_REQUEST` — and a `unit_purpose` of `EVALUATION` or `RETAIN`. The pull's guard conditions are evaluated in this order: the time point must be in `PENDING` or `PULLED` status (else `ERR_INVALID_TIME_POINT_STATE`); the study must be `IN_PROGRESS` (else `ERR_INVALID_STUDY_STATE`); the current study day of §2.4 must be at least the time point's `day_index` and no more than two days past it — both boundaries inclusive — (else `ERR_PULL_WINDOW_VIOLATION`); the chamber's `temp_c` must equal the study's `storage_temp_c` (else `ERR_CHAMBER_TEMP_MISMATCH`); the chamber must have room under the occupancy rule of §2.9, equality permitted (else `ERR_CHAMBER_CAPACITY_EXCEEDED`); and the named arm must belong to the same study as the time point (else `ERR_ARM_STUDY_MISMATCH`). A successful pull creates `quantity` **sample units**, each stamped with the `study_id`, `arm_id`, `chamber_id`, and `time_point_id` from context, the `unit_purpose` from input, and an initial status of `STORED`; the chamber's `reserved_units` increases by `quantity`; and the time point moves `PENDING → PULLED` — a no-op when it is already `PULLED`, so further pulls for other arms against the same time point remain legal. The pull responds `201 Created` with the updated time point as its `data` (not the created units).

Each sample unit thereafter lives a small custody lifecycle. A `PanelCoordinator` checks out a `STORED` unit, moving it `STORED → CHECKED_OUT`; for a unit whose `unit_purpose` is `EVALUATION` the request must carry a `session_id` naming an evaluation session of the same study in `PLANNED` or `OPEN` status — omitting it or naming an ineligible session is `ERR_INVALID_SESSION_STATE` — while a `RETAIN` unit may be checked out without a session. Whenever a `session_id` is supplied, for either purpose, it is validated the same way — an unknown, foreign-study, or ineligible session is `ERR_INVALID_SESSION_STATE`, never `ERR_NOT_FOUND` — and recorded as the checkout target. The unit's `session_id` records the checkout target and stays null while the unit is `STORED`. Returning a unit moves it `CHECKED_OUT → STORED` and clears `session_id`; this loop may repeat freely and is occupancy-neutral per §2.9. Consuming a unit moves it `CHECKED_OUT → CONSUMED`, clears `session_id`, and decrements the chamber's `reserved_units` by 1. A `LabDirector` may discard a unit from either `STORED` or `CHECKED_OUT`, moving it to `DISCARDED` with `session_id` cleared and `reserved_units` decremented by 1. Any checkout, return, consume, or discard attempted from a status that does not permit it is `ERR_INVALID_SAMPLE_STATE`.

Retain units exist for post-study verification. When a study completes (§3.7), every unit of the study whose `unit_purpose` is `RETAIN` and whose status is `STORED` or `CHECKED_OUT` receives a `retention_until_utc` equal to the completion instant plus 90 days; before that moment the field is null. A `LabDirector` may then run the **retain sweep**, an administrative capability that expires every `RETAIN` unit currently in `STORED` status whose `retention_until_utc` is set and falls strictly before the logical clock — a `RETAIN` unit still `CHECKED_OUT` past its deadline is left untouched — moving each such unit `STORED → EXPIRED` and decrementing its chamber's `reserved_units` by 1 per unit; the sweep reports how many units expired via `expired_count` and their identifiers via `expired_unit_ids`, listed in creation order.

A time point's own lifecycle closes out around the pulls. Once every session planned against it has resolved, the point may be closed — `EVALUATED → CLOSED`, permitted only from `EVALUATED` (else `ERR_INVALID_TIME_POINT_STATE`). Alternatively a scientist may skip a point from `PENDING` or `PULLED` while the study is `IN_PROGRESS` (any other combination is `ERR_INVALID_TIME_POINT_STATE` or `ERR_INVALID_STUDY_STATE`). Skipping a `PULLED` point abandons inventory already drawn: its sample units whose `unit_purpose` is `EVALUATION` and whose status is `STORED` or `CHECKED_OUT` are discarded with chamber occupancy recomputed, while its `RETAIN` units are preserved untouched for the retention window. The `PULLED → EVALUATED` step itself is never taken by hand; it happens automatically on analysis, per §3.5.

### 3.4. Panelist Recruitment, Qualification, and Discipline

The sensory panel is staffed through a gated pipeline. A `PanelCoordinator` registers each candidate with a `full_name`, a unique `email` (duplicates are `ERR_EMAIL_NOT_UNIQUE`), and the `qualified_attributes` the candidate may eventually score — a subset of the six attributes `APPEARANCE`, `AROMA`, `FLAVOR`, `TEXTURE`, `OFF_FLAVOR`, and `OVERALL`. A new panelist starts in `APPLIED` with `training_sessions_completed` at 0, `consecutive_no_shows` at 0, `screening_acuity_score` null until screening is recorded, and both consistency indexes null until sessions supply evidence.

Screening is the first gate. Recording a screening supplies an `acuity_score` between 0 and 100 inclusive — outside that range is `ERR_INVALID_REQUEST` — and is only legal from `APPLIED` (else `ERR_INVALID_PANELIST_STATE`). The score is stored verbatim as `screening_acuity_score`, and it decides the branch: a score of at least 80 — 80 itself qualifies — advances the panelist `APPLIED → TRAINING`, while anything below 80 routes them to `SCREENED_OUT`, a terminal state. Training is counted, not tested: each recorded training session increments `training_sessions_completed` by 1, is only legal from `TRAINING`, and the moment the counter reaches 3 the same request flips the panelist `TRAINING → QUALIFIED`.

Two quality signals ride on every panelist's record, both recomputed by the session machinery of §3.5 and both surfaced when a panelist is read. The `consistency_index_provisional` is recomputed whenever a session containing that panelist's scores locks; it considers sessions in `LOCKED` or `ANALYZED` status and measures each scored attribute cell against the plain session cell mean — a reference mean that **includes** the panelist's own score. The `consistency_index_final` is recomputed when such a session is analyzed; it considers `ANALYZED` sessions only and measures each cell against a **leave-one-out** panel mean that excludes the panelist's own score. For each variant the penalty is the mean, over the in-scope cells the panelist scored, of the absolute difference between the panelist's score and that cell's reference mean; the index itself is 100 minus 20 times the penalty, floored at zero so it never goes negative, and rounded half-up to 2 decimal places. Identical raw scores therefore yield different indexes — a cell scored 8 by this panelist and 6 by each of four others penalizes 1.6 points provisionally (index 68.00) but 2.0 points under leave-one-out (index 60.00). Under leave-one-out, a cell in which no other `SUBMITTED` panelist scored that attribute yields no reference mean and contributes no penalty; each variant stays null until the panelist has at least one in-scope cell with a usable reference mean.

Qualified panelists may step away and return. Deactivation moves `QUALIFIED → INACTIVE`. Reactivation branches on the final consistency evidence: when `consistency_index_final` is null or at least 60, the panelist returns `INACTIVE → QUALIFIED` directly; when it is below 60, the return is remedial — `INACTIVE → TRAINING` with `training_sessions_completed` reset to 0 so the full three-session course must be repeated. Both reactivation branches are only legal from `INACTIVE`.

Reliability is enforced automatically. When a panelist's `consecutive_no_shows` reaches 3 — driven by the no-show marking of §3.5 — a panelist in `QUALIFIED` is suspended by the system, moving `QUALIFIED → SUSPENDED`, and every other assignment that panelist holds in `ASSIGNED` on a session in `PLANNED` or `OPEN` is excused in the same stroke. Recording the sixth distinct attribute score on an assignment resets the panelist's `consecutive_no_shows` to 0 (§3.5), whether or not the assignment itself flips to `SUBMITTED`. The way back from suspension is remedial assignment by a `PanelCoordinator`: `SUSPENDED → TRAINING`, with both `training_sessions_completed` and `consecutive_no_shows` reset to 0.

### 3.5. Evaluation Sessions, Assignments, and Scoring

Sensory evidence is gathered in **evaluation sessions**, each planned by a `PanelCoordinator` for exactly one arm at exactly one time point of a study. Planning requires the study to be `SCHEDULED` or `IN_PROGRESS` (else `ERR_INVALID_STUDY_STATE`); the named `arm_id` and `time_point_id` must belong to the named `study_id` (else `ERR_ARM_STUDY_MISMATCH` or `ERR_TIME_POINT_STUDY_MISMATCH`); the supplied `scheduled_end_utc` must be strictly later than `scheduled_start_utc` (else `ERR_INVALID_REQUEST`); and no other session that is not `CANCELLED` may already exist for the same `(time_point_id, arm_id)` pairing (else `ERR_SESSION_EXISTS`). The session window is a half-open interval: it begins at `scheduled_start_utc` and runs up to — but for scheduling-conflict purposes does not include — `scheduled_end_utc`.

Every new session is sized by a statistical power computation whose evaluation order is pinned. First, the variance figure: the sample variance — denominator one less than the count — of all `OVERALL` attribute scores belonging to this study's sessions in `ANALYZED` status; when the study has no `ANALYZED` session yet, the variance defaults to 2.25. Second, the detectable difference is the study's `min_detectable_difference`. Third, the raw panel size is two times the square of the sum of 1.96 and 0.84, multiplied by that variance, and divided by the square of the detectable difference. Fourth and last, the raw size is rounded up to a whole number and only then clamped: below 4 it rises to 4, above 12 it falls to 12. The result is frozen on the session as `required_panelist_count` at creation; sessions analyzed later never retroactively resize existing sessions. A session begins in `PLANNED`, with `overall_mean` unset, `significance_delta` null, and `sensory_failed` false.

Rosters are built assignment by assignment. Creating a **panel assignment** for a `session_id` and `panelist_id` requires the session to be `PLANNED` or `OPEN` (else `ERR_INVALID_SESSION_STATE`) and the panelist to be `QUALIFIED` (else `ERR_PANELIST_NOT_QUALIFIED`). Scheduling conflicts are judged on half-open window intersection: the panelist must not already hold an assignment in `ASSIGNED` or `SUBMITTED` on another session whose window strictly intersects the new one, while back-to-back sessions — one ending exactly when the other begins — are permitted; violations are `ERR_PANELIST_DOUBLE_BOOKED`. The roster has headroom of exactly two over quorum: the session's active count — assignments in `ASSIGNED` plus those in `SUBMITTED` — must be below `required_panelist_count` plus 2, so a count that already equals that ceiling is rejected with `ERR_SESSION_FULL`. Finally, the same panelist may not hold two assignments on the same session at all (`ERR_INVALID_REQUEST`). Evaluation follows the ladder of §2.6: the roster-headroom check (rung 7) precedes the scheduling-conflict check (rung 9), and the same-session duplicate check comes last.

Opening a session — `PLANNED → OPEN`, driven by a `PanelCoordinator` — requires the study to be `IN_PROGRESS` (else `ERR_INVALID_STUDY_STATE`), requires at least one sample unit to exist for the session's `time_point_id` and `arm_id` (else `ERR_NO_PULLED_SAMPLES`), and is clock-gated: the logical clock must read no earlier than thirty minutes before `scheduled_start_utc` and no later than `scheduled_end_utc`, both boundaries inclusive, else `ERR_OUTSIDE_SESSION_WINDOW`. Once open, panelists score.

Scoring is ownership-bound. Each **attribute score** submission names an `assignment_id`, an `attribute`, and a `score`; an `attribute` outside the six defined attributes is `ERR_INVALID_REQUEST` (400), as is omitting `score`; the assignment's `panelist_id` must equal the acting `X-User-ID` (else `ERR_FORBIDDEN_ROLE`), the session must be `OPEN` (else `ERR_INVALID_SESSION_STATE`), the `score` must be an integer from 1 to 15 inclusive on the fifteen-point scale (else `ERR_SCORE_OUT_OF_RANGE`), the `(assignment_id, attribute)` pair must not already have a score (else `ERR_SCORE_ALREADY_SUBMITTED`), and the `attribute` must appear in the panelist's `qualified_attributes` (else `ERR_PANELIST_NOT_QUALIFIED`). The assignment completes itself: the moment the sixth distinct attribute score is recorded — covering all six attributes — an assignment still `ASSIGNED` flips `ASSIGNED → SUBMITTED` automatically (one already `NO_SHOW` or `EXCUSED` keeps its status, since scoring is gated on the session being `OPEN`, not on the assignment's status) and the panelist's `consecutive_no_shows` resets to 0 in either case.

Attendance failures carry their own bookkeeping. A `PanelCoordinator` may mark an assignment no-show only while it is `ASSIGNED` (else `ERR_INVALID_ASSIGNMENT_STATE`) and only while its session is `OPEN` (else `ERR_INVALID_SESSION_STATE`); the mark moves it `ASSIGNED → NO_SHOW`, increments the panelist's `consecutive_no_shows` by 1, and — when the counter thereby reaches at least 3 and the panelist is `QUALIFIED` — fires the suspension cascade of §3.4. Excusing an assignment, by contrast, moves `ASSIGNED → EXCUSED` without penalty and also arrives by cascade when a session is cancelled, a study is aborted, or a panelist is suspended.

Two exits close a session short of analysis. Cancellation — permitted from `PLANNED` or `OPEN` (else `ERR_INVALID_SESSION_STATE`) — moves the session to `CANCELLED` and excuses every one of its assignments still in `ASSIGNED`, while assignments already `SUBMITTED` are preserved as records. A cancelled session is not revived; instead, scheduling a makeup **creates a new session** in `PLANNED` that copies the source's `study_id`, `time_point_id`, and `arm_id`, records the lineage in `makeup_of_id` pointing at the source session (null on any session not born as a makeup), and receives a freshly computed `required_panelist_count`. The source must be `CANCELLED` (else `ERR_INVALID_SESSION_STATE`) and stays `CANCELLED`; because the uniqueness rule of session creation counts only sessions that are not `CANCELLED`, the cancelled source does not block its own makeup, though a live sibling for the same pairing still would (`ERR_SESSION_EXISTS`).

Locking a session is the analytical hinge of the whole system, and it is gated on quorum: the session must be `OPEN`, and the count of its `SUBMITTED` assignments must be at least `required_panelist_count` — equality satisfies quorum — else `ERR_SESSION_UNDER_QUORUM`. The `OPEN → LOCKED` transition then performs, in one stroke:

- The session's `overall_mean` is computed as the mean of the `OVERALL` scores across its `SUBMITTED` assignments only — assignments in `ASSIGNED`, `NO_SHOW`, or `EXCUSED` never enter any mean — rounded half-up to 2 decimal places.
- Significance is screened against the control: the control session is the non-`CANCELLED` session for the same time point whose arm is flagged `is_control`. When that control session is `LOCKED` or `ANALYZED`, `significance_delta` is computed at full precision as 1.96 times the panel standard deviation of 1.5 times the square root of the sum of the reciprocals of the two sessions' `SUBMITTED` counts; the difference between this session's `overall_mean` and the control's `overall_mean` is significant when its absolute value is at least `significance_delta`. When the control session is not yet `LOCKED` or `ANALYZED`, `significance_delta` stays null and the difference is treated as not significant.
- `sensory_failed` is set to true exactly when the session's `overall_mean` is at or below the study's `sensory_fail_threshold` — the at-or-below comparison is inclusive, so a mean exactly equal to the threshold satisfies that leg — **and** the difference from control is significant; otherwise `sensory_failed` is false.
- The `consistency_index_provisional` of §3.4 is recomputed for every panelist holding a `SUBMITTED` assignment in this session.
- When the newly evaluated failure moves the arm's earliest endpoint earlier, the failure-day cascade of §3.6 runs: the arm's `computed_failure_day_equiv` is recomputed, the study's `earliest_failure_day_equiv` follows, and any of the arm's recommendations in `PROPOSED` or `ACCEPTED` are superseded with the report-flagging consequences of §3.7.

Analysis is the final step. A `SensoryScientist` analyzes a `LOCKED` session (any other status is `ERR_INVALID_SESSION_STATE`), moving it `LOCKED → ANALYZED`; this recomputes the `consistency_index_final` of §3.4 for every panelist with a `SUBMITTED` assignment in the session, and it bubbles the time point upward: when every session of the time point that is not `CANCELLED` has reached `ANALYZED`, with at least one having done so, the time point itself moves `PULLED → EVALUATED`.

### 3.6. Laboratory Results and Failure-Day Projection

Instrumental evidence arrives through a `LabAnalyst`. Recording a **lab test result** names the `study_id`, `arm_id`, and `time_point_id` it belongs to, the `test_type` — one of `APC`, `YEAST_MOLD`, `LACTIC`, `PEROXIDE_VALUE`, `PH`, or `WATER_ACTIVITY` — and the `measured_value` in the test type's canonical unit. The study must be `IN_PROGRESS`, `ANALYSIS`, or `REPORTING` (else `ERR_INVALID_STUDY_STATE`). The measurement-range check is evaluated before the referential checks: `APC` accepts values from 0 to 12 inclusive, `YEAST_MOLD` and `LACTIC` from 0 to 10 inclusive, `PEROXIDE_VALUE` from 0 to 500 inclusive, `PH` from 0 to 14 inclusive, and `WATER_ACTIVITY` from 0 to 1 inclusive; anything outside is `ERR_MEASUREMENT_OUT_OF_RANGE`. Then the arm and time point must belong to the named study (else `ERR_ARM_STUDY_MISMATCH` or `ERR_TIME_POINT_STUDY_MISMATCH`).

Each recorded result is immediately judged against the laboratory's endpoint limits, all of them inclusive at-or-above thresholds: a result is `tripped` — the flag defaults to false — when an `APC` value is at least 6.0, a `YEAST_MOLD` value at least 5.0, a `LACTIC` value at least 7.0, a `PEROXIDE_VALUE` at least 20.0, a `PH` at least 8.0, or a `WATER_ACTIVITY` at least 0.95.

Tripped observations — lab results with `tripped` true and sessions with `sensory_failed` true in `LOCKED` or `ANALYZED` status — feed the failure-day projection that drives date coding. Each tripped observation is mapped through its time point's `day_index` and projected into real-time-equivalent days using the Q10 acceleration factor: the factor is the study's `q10_factor` raised to the power of one tenth of the difference between `storage_temp_c` and `reference_temp_c`, and the observation's equivalent days are its `day_index` multiplied by that factor, rounded half-up to 3 decimal places. The two study designs diverge exactly here. Under `REAL_TIME`, where storage and reference temperatures coincide, the factor is 1 and the equivalent days are simply the observed chronological day as-is. Under `ACCELERATED`, where the storage temperature exceeds the reference and the factor exceeds 1, the same observed `day_index` projects to a larger real-time-equivalent day, so identical raw schedules yield different failure days — and ultimately different date codes — across the two designs. The arm's `computed_failure_day_equiv` is the minimum equivalent-days value over all of its tripped observations, or null when none has tripped; the study's `earliest_failure_day_equiv` is the minimum across its arms, null when every arm is null.

Recording a tripped lab result runs the same cascade as a session lock that flips failure earlier: the arm's `computed_failure_day_equiv` is recomputed, the study's `earliest_failure_day_equiv` is recomputed, any recommendations of that arm in `PROPOSED` or `ACCEPTED` are superseded whenever the failure day changed, and reports pinned to a superseded recommendation are flagged or reverted per §3.7.

For evidence correlation, a computed read answers the question of whether an instrumental track and the sensory track move together. The correlation read — available to `SensoryScientist`, `LabDirector`, and `QAOfficer` — takes an `arm_id`, a `test_type`, and an `attribute` as query parameters (a missing parameter, or a `test_type` or `attribute` outside the defined enumerations, is `ERR_INVALID_REQUEST`; an unknown `arm_id` is `ERR_NOT_FOUND`), and forms pairs across the arm's time points wherever both sides exist: the x-value is the `measured_value` of the requested `test_type` at that time point — the earliest-recorded result when several exist — and the y-value is the `ANALYZED` session's `overall_mean` at that time point — the most recently created `ANALYZED` session when several exist, as an analyzed makeup may produce. Pairs are formed only from records of the named study, so an arm of another study simply contributes no pairs. Fewer than three such pairs is `ERR_INSUFFICIENT_CORRELATION_PAIRS`. The coefficient is the Pearson product-moment correlation over the paired deviations — the sum of the products of each series' deviations from its own mean, divided by the square root of the product of the two sums of squared deviations, or 0.0 when that denominator is zero — rounded half-up to 4 decimal places, and the response carries the `coefficient`, the `pair_count`, and the echoed `arm_id`, `test_type`, and `attribute`.

### 3.7. Date Codes, Client Reports, and Claim Substantiation

Analysis converges on a **date-code recommendation** per arm. A `SensoryScientist` proposes one against a `study_id` and `arm_id` while the study is `ANALYSIS` or `REPORTING` (else `ERR_INVALID_STUDY_STATE`), with the arm belonging to the study (else `ERR_ARM_STUDY_MISMATCH`), and the request is OCC-guarded by `expected_study_version` per §2.7. The recommendation's day count is computed as follows: the base is the arm's `computed_failure_day_equiv` when one exists, otherwise the study's `target_shelf_life_days`; the base is then reduced by the twenty-percent safety factor — that is, multiplied by 0.8 — and the product rounded down to a whole number of safety days; the rounding increment is 7 days when those safety days are below 90 and 30 days otherwise; and `computed_days` is the safety days divided by the increment, rounded down, multiplied back by the increment. The recommendation's `basis` records which leg supplied the base: `ENDPOINT_MIN` when the arm had a computed failure day, `TARGET_FALLBACK` otherwise. Creation succeeds into `PROPOSED`, supersedes any existing `PROPOSED` recommendation for the same arm — with the report-flagging consequences below — and increments the study's `version` by 1.

A recommendation in `PROPOSED` may be accepted or rejected by a `SensoryScientist`; acting on one that is not `PROPOSED` is `ERR_RECO_NOT_PROPOSED`. Rejection moves it to `REJECTED`, terminal. Acceptance moves it to `ACCEPTED` and is additionally gated on the study being in `ANALYSIS` or `REPORTING` (else `ERR_INVALID_STUDY_STATE`); when the acceptance leaves every arm of the study holding at least one `ACCEPTED` recommendation and the study is still in `ANALYSIS`, the study advances automatically `ANALYSIS → REPORTING`. Two system events supersede a recommendation into `SUPERSEDED`: a new `PROPOSED` recommendation arriving for the same arm supersedes only the arm's existing `PROPOSED` recommendations — an `ACCEPTED` recommendation survives a later proposal — while the arm's `computed_failure_day_equiv` changing after a later endpoint trip supersedes the arm's recommendations from either `PROPOSED` or `ACCEPTED`; study abortion supersedes them as well, per §3.2. Every supersession flags the reports pinned to that recommendation: a pinned report in `DRAFT` or `INTERNAL_REVIEW` gets `requires_revision` set true, while one in `CLIENT_REVIEW` is sent back to `DRAFT` with `requires_revision` true and `revision_count` incremented by 1.

The **study report** is the client-facing artifact. A `SensoryScientist` drafts one with a `study_id` and `title` while the study is in `ANALYSIS` or `REPORTING` (otherwise `ERR_INVALID_STUDY_STATE`); the draft is born in `DRAFT` with `author_user_id` captured from the acting `X-User-ID`, `pinned_recommendation_id` null, `snapshot_days` null, `requires_revision` false, and `revision_count` at 0. While drafting, the author — and only the author, else `ERR_FORBIDDEN_ROLE` — attaches a recommendation by `recommendation_id`; attachment requires the report to be `DRAFT` (else `ERR_INVALID_REPORT_STATE`), the recommendation to be `ACCEPTED` (else `ERR_RECO_NOT_PROPOSED`), and the recommendation's study to match the report's study (else `ERR_REPORT_STUDY_MISMATCH`). Attaching also clears `requires_revision` back to false, which is how a supersession-flagged draft is rehabilitated around a fresher recommendation.

Submitting moves the report `DRAFT → INTERNAL_REVIEW` and is the author's act alone (else `ERR_FORBIDDEN_ROLE`); it requires the report to be `DRAFT` (else `ERR_INVALID_REPORT_STATE`), requires a pinned recommendation that is `ACCEPTED` (else `ERR_NO_ACCEPTED_RECOMMENDATION`), and requires `requires_revision` to be false (else `ERR_REPORT_REQUIRES_REVISION`). At submission the report snapshots the pinned recommendation's `computed_days` into `snapshot_days`, version-pinning the number under review regardless of what later trips do to the underlying recommendation.

Quality review is deliberately segregated. A `QAOfficer` approves a report `INTERNAL_REVIEW → CLIENT_REVIEW` or rejects it outright `INTERNAL_REVIEW → REJECTED`, and in both cases the acting `QAOfficer`'s `X-User-ID` must differ from the report's `author_user_id` — an officer may never approve or reject a report they authored, else `ERR_SEGREGATION_OF_DUTIES`. Approval additionally requires `requires_revision` to be false (else `ERR_REPORT_REQUIRES_REVISION`). A softer path, the QA return, sends `INTERNAL_REVIEW → DRAFT` and increments `revision_count` by 1; any status other than `INTERNAL_REVIEW` on these three review actions is `ERR_INVALID_REPORT_STATE`.

The client then speaks. A `Client` may request changes on a report in `CLIENT_REVIEW` — only when the acting `X-User-ID` equals the study's `client_id` (else `ERR_FORBIDDEN_ROLE`) — which returns it `CLIENT_REVIEW → DRAFT`, clears `requires_revision` to false, and increments `revision_count` by 1. Release is the laboratory's final word: a `LabDirector` releases a report from `CLIENT_REVIEW` (else `ERR_INVALID_REPORT_STATE`), requiring `requires_revision` false (else `ERR_REPORT_REQUIRES_REVISION`), requiring every claim substantiation of the report to hold a `verdict` of `SUPPORTED` (else `ERR_UNVERIFIED_CLAIMS`), and requiring the study to be `REPORTING` (else `ERR_INVALID_STUDY_STATE`). Release moves the report to `RELEASED` and completes the study `REPORTING → COMPLETED` in the same stroke, which triggers the closing trio: every `RETAIN` sample unit of the study in `STORED` or `CHECKED_OUT` receives its `retention_until_utc` of the current logical clock plus 90 days; the retainer settles (below); and the client's `active_study_count` decreases by 1.

Settlement converts the escrow into a final bill. The study's `consumed_hours` is the sum of two ledgers, with rounding order pinned. Session room time is charged per `ANALYZED` session and **rounded per session first**: each session's duration in minutes is divided by 15 and rounded up to a whole number of quarter-hour quanta, then multiplied by 0.25 hours, and the session's charge adds half an hour — 0.5 — per `SUBMITTED` assignment. Laboratory time is charged per recorded lab test result by test type: 1.5 hours for `APC`, 2.0 hours for `YEAST_MOLD`, 2.0 hours for `LACTIC`, 1.0 hour for `PEROXIDE_VALUE`, 0.5 hours for `PH`, and 0.5 hours for `WATER_ACTIVITY`. The grand total — all session charges plus all test charges — is rounded half-up to 2 decimal places, and that figure is `consumed_hours`. The pinned order matters: summing raw durations before quantizing yields a different, wrong total — two sessions of 25 and 35 minutes with 4 submitted assignments apiece must bill 0.50 + 2.00 + 0.75 + 2.00 = 5.25 hours, not the 5.00 a sum-first order would produce. Settlement then credits the client's `retainer_hours_balance` with the difference between the `reserved_hours_escrow` and `consumed_hours`, and zeroes the escrow; when consumption exceeded the reserve the difference is negative and the balance is debited accordingly — a balance may go negative. Abortion, by contrast, refunds the escrow in full with no consumption charged, per §3.2.

Marketing **claims** ride on the report but are verified independently. The report's author — only the author, else `ERR_FORBIDDEN_ROLE` — attaches a claim to a `DRAFT` report (else `ERR_INVALID_REPORT_STATE`) by supplying the `report_id`, a `claim_type` of `SHELF_LIFE_DAYS` or `PACKAGING_SUPERIORITY`, free-text `claim_text`, and a `claimed_value` — a number of days for `SHELF_LIFE_DAYS`, or a percentage where 25 means 25% for `PACKAGING_SUPERIORITY`; the latter type also requires an `arm_id` naming the variant arm (omitting it is `ERR_INVALID_REQUEST`). An `arm_id` supplied on creation, for either claim type, must reference an existing arm (else `ERR_NOT_FOUND`); whether it names a non-control arm of the report's study is judged only at verification. Every claim begins with its `verdict` as `PENDING` and `verified_by` null.

Verification belongs to a `QAOfficer` who is not the report's author — acting otherwise is `ERR_SEGREGATION_OF_DUTIES` — and only a claim whose `verdict` is still `PENDING` may be verified, else `ERR_CLAIM_ALREADY_VERIFIED`; verification is not gated on the report's own status. The officer supplies their chosen `verdict`, and the system computes the evidence outcome independently; the chosen verdict must equal the evidence outcome exactly, else `ERR_CLAIM_EVIDENCE_MISMATCH`, and on success `verified_by` records the acting `X-User-ID`. The evidence rules per claim type are:

- For `SHELF_LIFE_DAYS`, the evidence looks at the report's pinned recommendation, which must exist and be `ACCEPTED`: the outcome is `SUPPORTED` exactly when `claimed_value` is less than or equal to the pinned recommendation's `computed_days`, and `NOT_SUPPORTED` otherwise. `INSUFFICIENT_DATA` is never the evidence outcome for this type.
- For `PACKAGING_SUPERIORITY`, the claim's `arm_id` must name a non-control arm of the same study as the report (else `ERR_REPORT_STUDY_MISMATCH`). The evidence looks up the most recently created `ACCEPTED` recommendation of the study's control arm and that of the named arm; when either is missing the outcome is `INSUFFICIENT_DATA`. Otherwise the actual percentage improvement is the named arm's `computed_days` minus the control arm's `computed_days`, divided by the control arm's `computed_days`, multiplied by 100, and rounded half-up to 2 decimal places; the outcome is `SUPPORTED` exactly when that actual percentage is at least `claimed_value`, and `NOT_SUPPORTED` otherwise.

## 4. Endpoint Definitions

Operations that create new resources — clients, studies, arms, time points, chambers, panelists, sessions (including makeups), assignments, scores, lab results, recommendations, reports, claims, retainer top-ups, and sample pulls — return `201 Created`. Operations that modify an existing resource or drive a state transition, all single-resource reads and list reads, the correlation read, the retain sweep, and the clock capability return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the server's logical clock | LabDirector |
| POST | `/sensory-lab/clients` | Create a client account | LabDirector |
| GET | `/sensory-lab/clients` | List clients | Any |
| GET | `/sensory-lab/clients/{id}` | Get a client | Any |
| POST | `/sensory-lab/clients/{id}/retainer-topups` | Add prepaid lab hours to a client's balance | LabDirector |
| POST | `/sensory-lab/studies` | Create a shelf-life study in DRAFT | SensoryScientist |
| GET | `/sensory-lab/studies` | List studies | Any |
| GET | `/sensory-lab/studies/{id}` | Get a study | Any |
| PUT | `/sensory-lab/studies/{id}` | Update study design fields (DRAFT only, OCC-guarded) | SensoryScientist |
| POST | `/sensory-lab/studies/{id}/submit-design` | Submit a study design for review | SensoryScientist |
| POST | `/sensory-lab/studies/{id}/approve-design` | Approve a study design | LabDirector |
| POST | `/sensory-lab/studies/{id}/reject-design` | Return a study design to DRAFT | LabDirector |
| POST | `/sensory-lab/studies/{id}/activate` | Activate a study and reserve retainer hours | SensoryScientist |
| POST | `/sensory-lab/studies/{id}/close-fieldwork` | Close fieldwork and enter analysis | SensoryScientist |
| POST | `/sensory-lab/studies/{id}/reopen-fieldwork` | Reopen fieldwork from analysis | SensoryScientist |
| POST | `/sensory-lab/studies/{id}/abort` | Abort a study with full compensation | LabDirector |
| GET | `/sensory-lab/studies/{id}/correlation` | Pearson correlation between a lab test type and sensory means | SensoryScientist, LabDirector, QAOfficer |
| POST | `/sensory-lab/study-arms` | Add a packaging arm to a DRAFT study | SensoryScientist |
| GET | `/sensory-lab/study-arms` | List study arms | Any |
| GET | `/sensory-lab/study-arms/{id}` | Get a study arm | Any |
| POST | `/sensory-lab/sampling-time-points` | Add a sampling day to the schedule | SensoryScientist |
| GET | `/sensory-lab/sampling-time-points` | List sampling time points | Any |
| GET | `/sensory-lab/sampling-time-points/{id}` | Get a sampling time point | Any |
| POST | `/sensory-lab/sampling-time-points/{id}/pull` | Pull sample units for one arm from a chamber | SensoryScientist |
| POST | `/sensory-lab/sampling-time-points/{id}/close` | Close an evaluated time point | SensoryScientist |
| POST | `/sensory-lab/sampling-time-points/{id}/skip` | Skip a time point | SensoryScientist |
| POST | `/sensory-lab/chambers` | Register a storage chamber | LabDirector |
| GET | `/sensory-lab/chambers` | List chambers | Any |
| GET | `/sensory-lab/chambers/{id}` | Get a chamber (includes computed occupancy) | Any |
| GET | `/sensory-lab/sample-units` | List and filter sample units | Any |
| GET | `/sensory-lab/sample-units/{id}` | Get a sample unit | Any |
| POST | `/sensory-lab/sample-units/{id}/checkout` | Check a sample unit out for a session | PanelCoordinator |
| POST | `/sensory-lab/sample-units/{id}/return` | Return a checked-out unit to storage | PanelCoordinator |
| POST | `/sensory-lab/sample-units/{id}/consume` | Consume a checked-out unit | PanelCoordinator |
| POST | `/sensory-lab/sample-units/{id}/discard` | Discard a stored or checked-out unit | LabDirector |
| POST | `/sensory-lab/retain-sweeps` | Expire RETAIN units past their retention deadline | LabDirector |
| POST | `/sensory-lab/panelists` | Register a panelist | PanelCoordinator |
| GET | `/sensory-lab/panelists` | List panelists | Any |
| GET | `/sensory-lab/panelists/{id}` | Get a panelist (includes both consistency indexes) | Any |
| POST | `/sensory-lab/panelists/{id}/record-screening` | Record a screening acuity score | PanelCoordinator |
| POST | `/sensory-lab/panelists/{id}/record-training` | Record a completed training session | PanelCoordinator |
| POST | `/sensory-lab/panelists/{id}/deactivate` | Deactivate a qualified panelist | PanelCoordinator |
| POST | `/sensory-lab/panelists/{id}/reactivate` | Reactivate an inactive panelist | PanelCoordinator |
| POST | `/sensory-lab/panelists/{id}/assign-remedial` | Route a suspended panelist to remedial training | PanelCoordinator |
| POST | `/sensory-lab/evaluation-sessions` | Plan a sensory session for one arm at one time point | PanelCoordinator |
| GET | `/sensory-lab/evaluation-sessions` | List evaluation sessions | Any |
| GET | `/sensory-lab/evaluation-sessions/{id}` | Get an evaluation session | Any |
| POST | `/sensory-lab/evaluation-sessions/{id}/open` | Open a planned session | PanelCoordinator |
| POST | `/sensory-lab/evaluation-sessions/{id}/lock` | Lock a session and run the evaluation cascade | PanelCoordinator |
| POST | `/sensory-lab/evaluation-sessions/{id}/analyze` | Analyze a locked session | SensoryScientist |
| POST | `/sensory-lab/evaluation-sessions/{id}/cancel` | Cancel a planned or open session | PanelCoordinator |
| POST | `/sensory-lab/evaluation-sessions/{id}/schedule-makeup` | Create a successor session for a cancelled one | PanelCoordinator |
| POST | `/sensory-lab/panel-assignments` | Assign a panelist to a session | PanelCoordinator |
| GET | `/sensory-lab/panel-assignments` | List panel assignments | Any |
| GET | `/sensory-lab/panel-assignments/{id}` | Get a panel assignment | Any |
| POST | `/sensory-lab/panel-assignments/{id}/mark-no-show` | Mark an assignment as a no-show | PanelCoordinator |
| POST | `/sensory-lab/panel-assignments/{id}/excuse` | Excuse an assignment without penalty | PanelCoordinator |
| POST | `/sensory-lab/attribute-scores` | Submit one attribute score | Panelist |
| GET | `/sensory-lab/attribute-scores` | List attribute scores | Any |
| GET | `/sensory-lab/attribute-scores/{id}` | Get an attribute score | Any |
| POST | `/sensory-lab/lab-test-results` | Record a microbial or chemical result | LabAnalyst |
| GET | `/sensory-lab/lab-test-results` | List lab test results | Any |
| GET | `/sensory-lab/lab-test-results/{id}` | Get a lab test result | Any |
| POST | `/sensory-lab/date-code-recommendations` | Propose a date-code recommendation for one arm (OCC-guarded) | SensoryScientist |
| GET | `/sensory-lab/date-code-recommendations` | List date-code recommendations | Any |
| GET | `/sensory-lab/date-code-recommendations/{id}` | Get a date-code recommendation | Any |
| POST | `/sensory-lab/date-code-recommendations/{id}/accept` | Accept a proposed recommendation | SensoryScientist |
| POST | `/sensory-lab/date-code-recommendations/{id}/reject` | Reject a proposed recommendation | SensoryScientist |
| POST | `/sensory-lab/study-reports` | Draft a report for a study | SensoryScientist |
| GET | `/sensory-lab/study-reports` | List study reports | Any |
| GET | `/sensory-lab/study-reports/{id}` | Get a study report | Any |
| POST | `/sensory-lab/study-reports/{id}/attach-recommendation` | Pin an accepted recommendation to a draft report | SensoryScientist |
| POST | `/sensory-lab/study-reports/{id}/submit` | Submit a draft report to internal review | SensoryScientist |
| POST | `/sensory-lab/study-reports/{id}/qa-approve` | QA-approve a report to client review | QAOfficer |
| POST | `/sensory-lab/study-reports/{id}/qa-return` | Return a report to draft for rework | QAOfficer |
| POST | `/sensory-lab/study-reports/{id}/qa-reject` | Reject a report outright | QAOfficer |
| POST | `/sensory-lab/study-reports/{id}/request-changes` | Request changes on a report in client review | Client |
| POST | `/sensory-lab/study-reports/{id}/release` | Release a report and complete the study | LabDirector |
| POST | `/sensory-lab/claims` | Attach a marketing claim to a draft report | SensoryScientist |
| GET | `/sensory-lab/claims` | List claims | Any |
| GET | `/sensory-lab/claims/{id}` | Get a claim | Any |
| POST | `/sensory-lab/claims/{id}/verify` | Verify a pending claim against computed evidence | QAOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_STUDY_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STUDY_STATE` | 409 |
| `ERR_NO_ARMS_DEFINED` | 409 |
| `ERR_NO_CONTROL_ARM` | 409 |
| `ERR_NO_TIME_POINTS` | 409 |
| `ERR_OPEN_TIME_POINTS_REMAIN` | 409 |
| `ERR_SESSIONS_STILL_OPEN` | 409 |
| `ERR_INSUFFICIENT_RETAINER_HOURS` | 402 |
| `ERR_CONTROL_ARM_EXISTS` | 409 |
| `ERR_DUPLICATE_ARM_VARIANT` | 409 |
| `ERR_DUPLICATE_TIME_POINT_DAY` | 409 |
| `ERR_INVALID_TIME_POINT_STATE` | 409 |
| `ERR_PULL_WINDOW_VIOLATION` | 409 |
| `ERR_CHAMBER_TEMP_MISMATCH` | 422 |
| `ERR_CHAMBER_CAPACITY_EXCEEDED` | 409 |
| `ERR_INVALID_SAMPLE_STATE` | 409 |
| `ERR_INVALID_PANELIST_STATE` | 409 |
| `ERR_EMAIL_NOT_UNIQUE` | 409 |
| `ERR_PANELIST_NOT_QUALIFIED` | 409 |
| `ERR_INVALID_SESSION_STATE` | 409 |
| `ERR_NO_PULLED_SAMPLES` | 409 |
| `ERR_OUTSIDE_SESSION_WINDOW` | 409 |
| `ERR_SESSION_UNDER_QUORUM` | 409 |
| `ERR_SESSION_EXISTS` | 409 |
| `ERR_PANELIST_DOUBLE_BOOKED` | 409 |
| `ERR_SESSION_FULL` | 409 |
| `ERR_INVALID_ASSIGNMENT_STATE` | 409 |
| `ERR_SCORE_ALREADY_SUBMITTED` | 409 |
| `ERR_SCORE_OUT_OF_RANGE` | 422 |
| `ERR_MEASUREMENT_OUT_OF_RANGE` | 422 |
| `ERR_ARM_STUDY_MISMATCH` | 422 |
| `ERR_TIME_POINT_STUDY_MISMATCH` | 422 |
| `ERR_INSUFFICIENT_CORRELATION_PAIRS` | 422 |
| `ERR_RECO_NOT_PROPOSED` | 409 |
| `ERR_INVALID_REPORT_STATE` | 409 |
| `ERR_NO_ACCEPTED_RECOMMENDATION` | 409 |
| `ERR_REPORT_REQUIRES_REVISION` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_UNVERIFIED_CLAIMS` | 409 |
| `ERR_CLAIM_ALREADY_VERIFIED` | 409 |
| `ERR_CLAIM_EVIDENCE_MISMATCH` | 422 |
| `ERR_REPORT_STUDY_MISMATCH` | 422 |

# Construction Schedule & Delay Claim Analysis API — Product Requirements Document

## 1. Introduction

Construction disputes are won or lost on the quality of the contemporaneous schedule record. When a project slips, the parties argue — often months later, and from incomplete files — over who caused which delay, whether written notice was lodged on time, who owned the float a delay consumed, and how much of the resulting overrun is compensable. This document specifies the Construction Schedule & Delay Claim Analysis API, the system of record a construction scheduling consultant uses to develop a baseline CPM schedule with full activity logic, capture monthly actual progress and the resulting critical-path shift, run time impact analyses for change events, apportion concurrent delay under the contract's float-ownership rule, administer extension-of-time requests and owner responses, track acceleration directives and their cost recovery, and quantify liquidated damages exposure.

The API models the schedule as a versioned directed graph of activities and logic ties, recomputing early and late dates, total float, and the projected finish on every schedule submission and every approved progress update. Claims are modeled as explicit multi-party workflows: the contractor's scheduler files notices, analyses, and requests; the owner's representative reviews and determines them; an independent claims consultant adjudicates time impact analyses. Notice timeliness, float ownership, and the liquidated damages cap are contract-level doctrine applied uniformly by the system, so that every determination is reproducible from contemporaneous records rather than reconstructed after the fact.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. Unless stated otherwise, every resource is mounted beneath the `/construction-projects` path prefix.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. The system recognizes five operational roles. A `ContractorScheduler` builds and updates CPM schedules, files notices, time impact analyses, and extension-of-time requests, and acknowledges acceleration directives. A `ProjectControlsEngineer` creates projects, activates them, and reviews and accepts or rejects schedule versions and progress updates. An `OwnerRepresentative` reviews extension-of-time requests, issues acceleration directives, assesses liquidated damages, and declares substantial completion. A `ClaimsConsultant` is an independent scheduler who accepts or rejects time impact analyses. A `SystemAdmin` operates the test-driving endpoints. A sixth designation, `Any`, appears throughout this document as a shorthand meaning that every authenticated role may call read-only endpoints.

For each of the five operational roles — `ContractorScheduler`, `ProjectControlsEngineer`, `OwnerRepresentative`, `ClaimsConsultant`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it (for example, as `submitted_by_contractor_user_id` on a progress update) but it never compares the value to any entity's `id`.

A request with missing or malformed identity headers is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). These two checks are the first validations evaluated on every request, in this order.

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

### 2.3. Pagination, Sorting, and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100; out-of-range values are clamped, not rejected — a `limit` below 1 is treated as 1 and a `limit` above 100 as 100. The `offset` parameter specifies the number of items to skip and defaults to 0; a negative `offset` is treated as 0. A non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order; because the logical clock only advances when explicitly set, ties on an identical timestamp are broken by insertion order (earliest created first).

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

List endpoints additionally support resource-specific filters as query parameters: schedule versions by `kind` and `status`; activities by `is_critical` (parsed case-insensitively, with `true`/`1`/`yes` meaning true and `false`/`0`/`no` meaning false; any other value is rejected with `ERR_INVALID_REQUEST`); delay events by `status` and `causation`; progress updates, extension-of-time requests, acceleration directives, and liquidated damages assessments by `status`. Alongside the nested collection paths, the API also exposes flat, cross-project list views for foreign-key reverse reachability: schedule versions filterable by `project_id` or `supersedes_version_id`; activities by `schedule_version_id`; relationships by `schedule_version_id`, `predecessor_activity_id`, or `successor_activity_id`; progress updates by `schedule_version_id`; progress entries by `progress_update_id` or `activity_id`; delay events by `project_id` or `fragnet_inserted_into_version_id`; extension-of-time requests by `project_id` or `delay_event_id`; and acceleration directives and liquidated damages assessments by `project_id`.

### 2.4. The Server Logical Clock

The server keeps its own logical clock rather than reading wall time. At startup the clock reads 2026-05-01T00:00:00Z, and it never falls back to the real wall clock afterwards — it advances only when explicitly set. A `SystemAdmin` may set the logical clock through a test-driving capability that accepts a `to_iso8601` instant and answers with a 200 status.

The logical clock is the single timestamp source for every "now" the system needs: notice submissions stamp `notice_submitted_at` from it, directive issuance stamps `issued_at` from it, the substantial-completion auto-assessment compares assessment period ends against it, and the retrospective time-slice analysis treats it as "today".

### 2.5. Common Resource Properties

All primary resources — projects, schedule versions, activities, progress updates, delay events, extension-of-time requests, acceleration directives, and liquidated damages assessments — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments with every modification to the resource, used for optimistic concurrency control where §2.9 applies.

Two sub-resources are deliberately lighter: an activity relationship and a progress entry carry only `id` and `created_at`. Both `updated_at` and `version` are absent on them, since neither is ever mutated after creation.

### 2.6. Nested Paths, Existence Checks, and Validation Order

The API enforces strict hierarchical validation for every request that targets a nested resource. When a path contains several identifiers — a project, then a schedule version, then an activity, and so on — the system validates existence sequentially from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request aimed at an activity under a non-existent schedule version therefore fails on the version before the activity is ever consulted.

Beyond existence, validations fire in a fixed global order rather than an arbitrary one. The identity-header check comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role authorization (`ERR_INSUFFICIENT_PERMISSIONS`), then left-to-right path existence (`ERR_NOT_FOUND`), then payload-shape validation — a missing required field or a value of the wrong type fails generically with `ERR_INVALID_REQUEST` (HTTP 400) at this point — then the state-machine precondition of the targeted transition (`ERR_INVALID_STATE`, HTTP 409). Business rules follow, and where several of them guard one operation their relative order is defined. When a logic tie is created, the cycle check on the augmented graph (`ERR_CYCLE_DETECTED`) is evaluated before the same-version membership check (`ERR_ACTIVITY_NOT_IN_VERSION`). When a schedule version is accepted, the state check is followed by the baseline rules — for a `BASELINE`, that no other accepted baseline exists (`ERR_BASELINE_ALREADY_ACCEPTED`); for an `UPDATE`, that an accepted baseline exists (`ERR_BASELINE_NOT_ACCEPTED`) — and only then by the stale-version check (`ERR_STALE_VERSION`), so a stale project version surfaces only after the state and baseline preconditions have passed. When an extension-of-time request is drafted or submitted, the linked event's analysis acceptance (`ERR_TIA_NOT_ACCEPTED`) is verified before the entitlement ceiling (`ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT`), which in turn precedes the compensable-cost rule (`ERR_NON_COMPENSABLE_COST`). On every endpoint that carries an optimistic-concurrency field, the stale-version check is the last rule evaluated. Malformed payloads — a missing required field, a value of the wrong type — fail generically with `ERR_INVALID_REQUEST` (HTTP 400) at the payload-shape step above. A request using an unsupported HTTP method on an otherwise routed path fails with `ERR_INVALID_REQUEST` (HTTP 405), and a request to an unrouted path fails with `ERR_NOT_FOUND` (HTTP 404).

### 2.7. Hierarchical Consistency and Cross-Schedule Cascades

Determinations in this domain ripple outward: a single approval can move the contractual completion date, which in turn changes exposure figures calculated elsewhere. The system performs these reconciliations automatically at the moment the triggering transition occurs, without requiring a separate client call, and every such reconciliation mutates the affected resource — refreshing its `updated_at` and, where the resource carries one, incrementing its `version`.

Four cascades are central. Accepting a schedule version advances the owning project's `version` by one and recomputes the analysis figures of any delay event whose fragnet was inserted into that version. Approving a progress update rewrites the activities it reports on and can spawn a draft liquidated damages assessment when the schedule overruns. Approving or partially approving an extension-of-time request shifts the project's completion date, advances the project `version`, and flips overlapping draft assessments to an offset state. Declaring substantial completion automatically assesses any due draft assessment. Each cascade is described in full within the workflow that triggers it (see §3).

### 2.8. Calendar-Day Arithmetic and Monetary Precision

All schedule quantities — original and remaining durations, lags, total float, prolongation figures, apportioned days, days to recover, and culpable days — are integer calendar days, and every date difference the system computes is expressed in whole calendar days. Reported `percent_complete` values range from 0 to 100 inclusive.

All monetary amounts are represented as integer numbers of cents: the daily liquidated damages rate, the aggregate damages cap, acceleration cost figures, awards, and assessed amounts. The single non-integer monetary computation in the system is the measured-mile acceleration recovery, whose result is rounded half up to two decimal places.

### 2.9. Optimistic Concurrency Control on the Project

Three write operations carry optimistic concurrency control against the owning project: accepting a schedule version, approving an extension-of-time request in full, and partially approving an extension-of-time request. Each requires a non-optional `expected_project_version` field in the request payload, carrying the project `version` the client last observed. If the supplied value does not match the project's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412).

This guards two concrete hazards. Acceptance of a schedule version mutates the project's `current_completion_date` and advances its `version`, so a client acting on a superseded snapshot would otherwise accept against project state it has never observed. Likewise, an extension-of-time approval itself moves `current_completion_date`; two back-to-back approvals issued from the same stale snapshot would double-shift the contractual date. Endpoints not named in this section do not take a version field.

### 2.10. Contract Doctrine: Float Ownership, Notice Windows, and the Damages Cap

Three project-level settings shape every downstream determination, and each is fixed at project creation, with defaults applied when omitted.

The `float_ownership_policy` determines who absorbs float consumption when delays overlap. Under `CONTRACTOR_OWNS` — the default — the contractor absorbs float consumption and compensable days are computed against the raw prolongation. Under `OWNER_OWNS`, the owner absorbs float first, so compensable days begin only after float is exhausted. Under `SHARED_FIRST_COME`, the party whose event became critical first absorbs the float.

The `notice_window_days` setting — 21 calendar days when not supplied — is the window from a delay event's first day of impact within which written notice must be lodged. Late notice forfeits the time component of the claim for `OWNER_CAUSED` and `THIRD_PARTY` events, while the cost component may still be evaluated; the notice step itself never fails for lateness.

The `liquidated_damages_daily_rate_cents` and `ld_cap_cents` settings define the per-calendar-day damages rate and the aggregate damages cap. No assessment may push the project's total assessed damages beyond that cap.

## 3. Business Logic & Workflows

### 3.1. Project Inception and the Road to Activation

A `ProjectControlsEngineer` opens a new engagement by creating the **ConstructionProject** record: a human-readable `project_name`, the notice-to-proceed `contract_start_date`, the contractual substantial-completion `contract_completion_date`, the stipulated `liquidated_damages_daily_rate_cents`, and the aggregate `ld_cap_cents`. The contract's `float_ownership_policy` and `notice_window_days` may be supplied at creation; when omitted they default to `CONTRACTOR_OWNS` and twenty-one days respectively, per §2.10.

A new project begins in `PRECONSTRUCTION`. Its derived `current_completion_date` — the date against which all drift, entitlement, and damages arithmetic is performed — starts equal to `contract_completion_date`. Thereafter the `current_completion_date` is the contractual completion date plus the sum of every approved extension-of-time duration, and it is recomputed on each extension approval.

Activation is the transition from `PRECONSTRUCTION` to `ACTIVE`. It normally fires on its own: when the project's first baseline schedule is accepted, the activation chain runs automatically (see §3.3). A `ProjectControlsEngineer` may also activate a project manually — a rare path — which requires the project to still be in `PRECONSTRUCTION` (`ERR_INVALID_STATE` otherwise) and an accepted baseline schedule to already exist (`ERR_BASELINE_NOT_ACCEPTED` otherwise); either path sets `current_completion_date` to `contract_completion_date`. From `ACTIVE` the project later proceeds to `SUBSTANTIALLY_COMPLETE` and finally to the terminal `CLOSED` state, transitions covered in §3.8.

### 3.2. Building the CPM Schedule: Versions, Activities, and Logic Ties

Schedule content is versioned. A `ContractorScheduler` creates a **ScheduleVersion** inside a project by supplying its `kind` — `BASELINE` or `UPDATE` — and a `data_date`: the schedule origin for a baseline, or the cutoff date up to which actuals are reported for an update. An update may also name a `supersedes_version_id`, the prior update it replaces; a baseline never carries one. Supplying `supersedes_version_id` on a `BASELINE`, or supplying one that does not resolve to an existing `UPDATE` version of the same project, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Each version is numbered by a `revision_number` scoped per project and kind: at creation it is assigned one plus the count of that project's existing versions of the same kind (so the first version of a kind starts at 1), and every version begins life in `DRAFT`. The system also tracks `total_activities`, the count of activities the version contains.

Within a draft version the scheduler adds **Activity** records: the contractor's `activity_code` (unique within its schedule version, e.g. "A1010"), a scope `description`, and the planned `original_duration_days`, which must be at least one day. The `remaining_duration_days` may be supplied but defaults to the original duration when omitted, and it must lie between zero and the original duration inclusive. A duration that violates either bound fails payload-shape validation with `ERR_INVALID_REQUEST` (HTTP 400). Activities may be added only while the version is in `DRAFT` (`ERR_INVALID_STATE` otherwise), and the `activity_code` uniqueness rule is enforced — after the draft-state check — as a business rule that also fails with `ERR_INVALID_REQUEST` (HTTP 400). The `percent_complete` starts at 0. The `actual_start` and `actual_finish` are nullable and are stamped from progress reporting later, while six computed fields — `early_start`, `early_finish`, `late_start`, `late_finish`, `total_float_days`, and `is_critical` — remain unset until the schedule is computed at submission.

Logic between activities is captured as an **ActivityRelationship**: a `predecessor_activity_id`, a `successor_activity_id`, a `relationship_type`, and an optional signed `lag_days` that defaults to zero. Relationships may be added only while the version is in `DRAFT` (`ERR_INVALID_STATE` otherwise). Four tie types are recognized — finish-to-start (`FS`), start-to-start (`SS`), finish-to-finish (`FF`), and start-to-finish (`SF`); any other value is rejected with `ERR_INVALID_RELATIONSHIP_TYPE`. A relationship whose predecessor and successor are the same activity is rejected with `ERR_SELF_RELATIONSHIP`, and both ends must belong to the same schedule version (`ERR_ACTIVITY_NOT_IN_VERSION`). Because the activities and their ties form a directed acyclic graph, every inserted tie is cycle-checked against the augmented network, and a tie that would close a cycle is rejected with `ERR_CYCLE_DETECTED`; these business rules fire in the order relationship-type validity, then self-relationship, then the cycle check, then membership — per §2.6 the cycle check fires before the membership check.

### 3.3. Submitting, Reviewing, and Accepting a Schedule Version

Submission by the `ContractorScheduler` moves a version from `DRAFT` to `SUBMITTED` and triggers the full schedule computation. A version may be submitted only from `DRAFT` (`ERR_INVALID_STATE`), must contain at least one activity (`ERR_EMPTY_SCHEDULE`), and its network must be acyclic (`ERR_CYCLE_DETECTED`).

The computation is a forward-and-backward critical path pass over a topological ordering of the activities. In the forward pass, each incoming tie contributes a candidate early start for the successor: a finish-to-start tie contributes the predecessor's `early_finish` plus the lag; a start-to-start tie contributes the predecessor's `early_start` plus the lag; a finish-to-finish tie contributes the predecessor's `early_finish` plus the lag minus the successor's remaining duration; and a start-to-finish tie contributes the predecessor's `early_start` plus the lag minus the successor's remaining duration. An activity's `early_start` is the largest of its candidates, or the version's `data_date` when it has no predecessors, and its `early_finish` is its `early_start` plus its `remaining_duration_days` — an activity reported fully complete has zero remaining duration and therefore finishes at its early start. In the backward pass, each outgoing tie contributes a candidate late finish for the predecessor: a finish-to-start tie contributes the successor's `late_start` minus the lag; a start-to-start tie contributes the successor's `late_start` minus the lag plus the predecessor's remaining duration; a finish-to-finish tie contributes the successor's `late_finish` minus the lag; and a start-to-finish tie contributes the successor's `late_finish` minus the lag plus the predecessor's remaining duration. An activity's `late_finish` is the smallest of its candidates, or — when it has no successors — the project horizon, defined as the maximum `early_finish` among the terminal activities. Its `late_start` is its `late_finish` minus its `remaining_duration_days`. Finally, `total_float_days` is the `late_finish` minus the `early_finish` in whole calendar days, and a zero float marks an activity as critical.

Critical path identification then runs under the project's active variant. The default `LONGEST_PATH` variant — used when no external completion constraint exists — treats every activity whose `total_float_days` is zero as critical. The `LEAST_FLOAT_PATH` variant applies when the contract imposes an externally constrained finish earlier than the computed horizon: it takes the minimum `total_float_days` across all activities and treats every activity sitting at that minimum as critical, which can yield a different critical set and a different count. No operation in this API records such an external completion constraint, so the `LONGEST_PATH` variant is always the active one. The pass stamps `is_critical` on each activity and aggregates `critical_path_activity_count` and `projected_finish_date` — the maximum early finish over the terminal activities — onto the version. When the submitted version is an `UPDATE`, its drift against the project's `current_completion_date` is evaluated at this point, but the project record itself is deliberately left untouched; the project is mutated only upon acceptance.

Acceptance is the `ProjectControlsEngineer`'s determination and moves the version from `SUBMITTED` to `ACCEPTED`. Its preconditions fire in the order given in §2.6: the version must be `SUBMITTED` (`ERR_INVALID_STATE`); a `BASELINE` acceptance requires that no other accepted baseline exist for the project (`ERR_BASELINE_ALREADY_ACCEPTED` — exactly one accepted baseline is ever permitted per project), while an `UPDATE` acceptance requires that an accepted baseline already exist (`ERR_BASELINE_NOT_ACCEPTED`); and the payload's `expected_project_version` must match the project's current `version` (`ERR_STALE_VERSION`, per §2.9). Acceptance has wide-reaching effects. Accepting a `BASELINE` while the project is still in `PRECONSTRUCTION` fires the activation chain of §3.1. Accepting an `UPDATE` supersedes the previously accepted update — the prior version remains `ACCEPTED` in the historical record, but only the latest is treated as current — and the project's `current_completion_date` is recomputed per §3.1 as the `contract_completion_date` plus the sum of `approved_days` over the project's `APPROVED` and `PARTIALLY_APPROVED` extension-of-time requests. Either acceptance advances the project `version` by exactly one. Finally, the acceptance bubbles outward: every delay event whose `fragnet_inserted_into_version_id` names this version and which currently stands in `TIA_SUBMITTED` or `TIA_ACCEPTED` has both of its time-impact prolongation figures recomputed (the apportioned-day figures are not re-derived by this cascade); events in other states are left untouched.

Rejection by the `ProjectControlsEngineer` moves the version from `SUBMITTED` to `REJECTED` and clears every computed date and float field on its activities, so that a later resubmission recomputes from a clean slate. The contractor may then bring the version back from `REJECTED` to `DRAFT` for rework, which increments `revision_number` by one.

### 3.4. Monthly Progress Reporting and Critical-Path Drift

Actual progress is filed against an `UPDATE` schedule version as a **ProgressUpdate**. The `ContractorScheduler` creates one by supplying the `reporting_period_end` — the month-end cutoff — and an opaque `submitted_by_contractor_user_id`; the update begins in `DRAFT`. Filing against a version whose `kind` is not `UPDATE` fails payload validation with `ERR_INVALID_REQUEST` (HTTP 400); the parent version need not be accepted at creation time — acceptance is required only at submission. Progress itself is recorded one activity at a time as a **ProgressEntry** within the update, each naming an `activity_id` and carrying the reported `percent_complete` and `remaining_duration_days`, plus `actual_start` and `actual_finish` where applicable. A `percent_complete` outside 0..100 or a negative `remaining_duration_days` fails payload validation with `ERR_INVALID_REQUEST` (HTTP 400); entries may be recorded only while the update is in `DRAFT` (`ERR_INVALID_STATE` otherwise); and the entry's `activity_id` must already reference an activity belonging to the parent schedule version at creation time (`ERR_ACTIVITY_NOT_IN_VERSION`), a rule re-verified at submission.

Four progress invariants are enforced when an entry is recorded, and a violation of any of them is rejected with `ERR_INVALID_PROGRESS`: a reported `actual_finish` may not precede its `actual_start`; `percent_complete` must be exactly 100 if and only if `remaining_duration_days` is zero; an `actual_start` is required once `percent_complete` rises above zero; and an `actual_finish` is required exactly when `percent_complete` reaches 100. On the activity itself, `actual_start` is stamped the first time progress reports the activity above zero percent, and `actual_finish` is stamped when it reaches one hundred.

Submitting the update moves it from `DRAFT` to `SUBMITTED`; the parent schedule version must be an accepted `UPDATE` (`ERR_SCHEDULE_NOT_ACCEPTED`) and every entry must reference an activity belonging to that parent version (`ERR_ACTIVITY_NOT_IN_VERSION`). Approval is the `ProjectControlsEngineer`'s call and is where reported reality is folded into the schedule: each entry's `percent_complete`, `remaining_duration_days`, `actual_start`, and `actual_finish` are written onto its activity, the forward-and-backward pass and critical path identification are re-run on the parent version, and `projected_finish_date` is recomputed. If the new projected finish crosses beyond the project's `current_completion_date`, the system automatically creates a draft (`PROPOSED`) liquidated damages assessment spanning the overrun window — its `assessment_period_start` is the project's `current_completion_date` and its `assessment_period_end` the recomputed `projected_finish_date` — the exposure cascade of §3.8. A rejected update moves to `REJECTED`, and the contractor may return it from `REJECTED` to `DRAFT` for rework.

### 3.5. Delay Events: Notice, Time Impact Analysis, and Concurrent Delay

When a change or delay event occurs, the `ContractorScheduler` records a **DelayEvent** on the project with a short `title`, a `causation` of `OWNER_CAUSED`, `CONTRACTOR_CAUSED`, `THIRD_PARTY`, or `FORCE_MAJEURE`, the `event_start_date` marking the first day of impact, and an `event_end_date` for the last day — left null while the impact is ongoing. An event whose end precedes its start is inconsistent and is rejected with `ERR_NOTICE_DATA_INVALID`. The scheduler may also attach the analysis scaffolding up front: `fragnet_activity_ids`, the activity fragments to be inserted into the accepted update schedule (an optional list of strings, defaulting to empty), and `fragnet_inserted_into_version_id`, the update version against which the analysis will be computed. Neither reference is validated at creation; both are validated only when the time impact analysis is submitted. The event begins in `DRAFT`.

Written notice moves the event from `DRAFT` to `NOTICED`. The transition stamps `notice_submitted_at` from the server's logical clock and evaluates `notice_within_window`: notice is within the window when it is lodged no earlier than the `event_start_date` and no later than that date plus the project's `notice_window_days` — equivalently, when the elapsed calendar days from event start to notice do not exceed the window. Late notice never fails the step; instead, when notice is late for an `OWNER_CAUSED` or `THIRD_PARTY` event, the time component of the claim is flagged as forfeit while the cost component may still be evaluated.

The time impact analysis submission moves the event from `NOTICED` to `TIA_SUBMITTED`. It requires the `fragnet_inserted_into_version_id` to name an accepted `UPDATE` schedule (`ERR_SCHEDULE_NOT_ACCEPTED`) and the `fragnet_activity_ids` to be non-empty, with every referenced activity belonging to that version (`ERR_ACTIVITY_NOT_IN_VERSION`). The system then runs the analysis in both variants. The prospective variant, `FRAGNET_INSERTION`, measures the fragnet's insertion differentially: since the fragnet activities already belong to the target version's network, the system re-runs the forward-and-backward pass on the network with the fragnet activities — and every tie touching them — removed, and records `tia_prolongation_days_prospective` as the target version's projected finish minus the reduced network's projected finish, in whole calendar days and never less than zero; when the fragnet accounts for every activity of the version, the reduced network's projected finish is taken as the version's `data_date`. The retrospective variant, `TIME_SLICE_WINDOWS`, is forensic in intent — it answers what the fragnet's causal chain has already cost against the as-built record — but the system keeps no per-window as-built delay-attribution record, so the retrospective total is evaluated on the same network and `tia_prolongation_days_retrospective` is recorded equal to the prospective figure.

Concurrent-delay apportionment then runs as a waterfall over the prospective prolongation. Concurrency is measured as whole-calendar-day window overlap: the event's window runs from its `event_start_date` through its `event_end_date` — or through the server's logical now while no end date is recorded — and the contractor-caused (respectively owner-caused) concurrent days are the sum, over every other delay event recorded on the same project in any state, of the whole-day overlap between the two windows, counting only other events whose causation is `CONTRACTOR_CAUSED` (respectively `OWNER_CAUSED`). The contractor-caused concurrent days are allocated first to `apportioned_non_excusable_days` — never less than zero — and what remains of the prolongation is the residual (which may be negative, in which case the compensable and excusable-non-compensable figures floor at zero). The residual is then distributed by causation and notice. For an `OWNER_CAUSED` event with timely notice, `apportioned_compensable_days` receives the lesser of the residual and the owner-caused concurrent days — or the whole residual when there is no overlapping owner-caused delay — and `apportioned_excusable_non_compensable_days` receives whatever remains. For a `FORCE_MAJEURE` event, and for an `OWNER_CAUSED` event whose notice was late, nothing is compensable and the entire residual is excusable but non-compensable. For `CONTRACTOR_CAUSED` and `THIRD_PARTY` events, neither compensable nor excusable-non-compensable days are awarded, and the entire prospective prolongation is non-excusable. Last, the project's float-ownership doctrine of §2.10 adjusts the outcome: under `OWNER_OWNS` the owner absorbs float consumption first, reducing compensable days by the float consumed during the window before the owner's concurrent delay became critical; under `CONTRACTOR_OWNS` no such adjustment is made; under `SHARED_FIRST_COME` the party whose event became critical first absorbs the float. Because the system records no per-window float-consumption quantity, this doctrinal adjustment reduces compensable days by zero under all three policies, leaving the waterfall figures unchanged.

Adjudication of the analysis belongs to the `ClaimsConsultant`. Acceptance moves the event to the terminal `TIA_ACCEPTED` state; when the event is `OWNER_CAUSED` and its notice was within the window, acceptance establishes eligibility for a compensable extension of time. Rejection moves it to `TIA_REJECTED`, from which the contractor may resubmit: the event returns from `TIA_REJECTED` to `NOTICED` and its `tia_prolongation_days_prospective`, `tia_prolongation_days_retrospective`, and all three apportioned-day fields are cleared, to be recomputed on the next analysis submission.

### 3.6. Extension of Time Requests and the Owner's Determination

An accepted analysis becomes a claim when the `ContractorScheduler` drafts a **TimeExtensionRequest** naming the `delay_event_id` and stating the `requested_days` and, optionally, a `cost_recovery_cents` figure for the prolongation cost sought — which may attach only to the compensable portion. A `requested_days` below one, or a negative `cost_recovery_cents` (which defaults to zero when omitted), fails payload validation with `ERR_INVALID_REQUEST` (HTTP 400). Three rules guard the draft, in the order given in §2.6: the referenced delay event must be in `TIA_ACCEPTED` (`ERR_TIA_NOT_ACCEPTED`); the `requested_days` — always at least one — may not exceed the sum of the event's `apportioned_compensable_days` and `apportioned_excusable_non_compensable_days` (`ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT`); and a request carrying a positive `cost_recovery_cents` is permitted only when the event's `apportioned_compensable_days` is positive (`ERR_NON_COMPENSABLE_COST`). The request begins in `DRAFT` with a `submission_round` of 1. The analysis-acceptance and entitlement rules are re-verified when the draft is submitted, moving it from `DRAFT` to `SUBMITTED`.

The owner's review is opened by the `OwnerRepresentative`, moving the request from `SUBMITTED` to `UNDER_REVIEW`, and it ends in one of three determinations, each of which requires the request to stand in `UNDER_REVIEW` (`ERR_INVALID_STATE` otherwise). The approval payloads — full and partial alike — must carry `expected_project_version`, `approved_days`, and `awarded_cost_cents`; a missing field fails payload validation with `ERR_INVALID_REQUEST` (HTTP 400). Full approval requires the payload's `approved_days` to equal the `requested_days` exactly (`ERR_APPROVED_DAYS_MISMATCH`) and, where the request carries a compensable cost, the `awarded_cost_cents` to equal the `cost_recovery_cents` sought (`ERR_AWARD_MISMATCH`); when the request carries no compensable cost the supplied `awarded_cost_cents` is recorded as given. The payload's `expected_project_version` must match the project's current `version` (`ERR_STALE_VERSION`, §2.9). Approval moves the request to `APPROVED`, adds the `approved_days` to the project's `current_completion_date`, and advances the project `version` by one. The date shift cascades: any `PROPOSED` liquidated damages assessment whose assessment period overlaps the interval from the old current completion date up to — but not including — the new one transitions to `OFFSET_BY_EOT`. Partial approval follows the same mechanics for the approved portion only and requires the `approved_days` to be greater than zero and strictly less than the `requested_days` (`ERR_INVALID_PARTIAL_DAYS`), landing the request in `PARTIALLY_APPROVED`; the award-match rule does not apply to partial approval — the supplied `awarded_cost_cents` is recorded as given — and it likewise shifts the completion date by the approved days, advances the project `version`, and offsets the overlapping assessments. The `approved_days` — the owner's determination, never more than was requested — and the `awarded_cost_cents` awarded on approval are recorded on the request itself. Outright denial moves the request to `DENIED`.

Denial is not necessarily final. The contractor may appeal, which returns the request from `DENIED` to `SUBMITTED` and increments the `submission_round`. Appeals are capped: an appeal is allowed only while the `submission_round` is below 3, and an appeal attempted when the round has reached 3 is rejected with `ERR_APPEAL_LIMIT_REACHED`.

### 3.7. Acceleration Directives and Cost Recovery

An owner who needs time back issues an **AccelerationDirective**. The `OwnerRepresentative` supplies the owner's `directive_reference` and the `directed_completion_date` now being demanded; the directive is born in `ISSUED` with `issued_at` stamped from the logical clock. Acknowledgement by the `ContractorScheduler` moves it to `ACKNOWLEDGED` and freezes the reference point: the `baseline_completion_date` is snapshotted from the project's `current_completion_date` at that moment, and the `days_to_recover` is computed as the calendar days from the directed date to that baseline — a positive value meaning acceleration is genuinely being demanded. Beginning the accelerated work moves the directive to `PERFORMING`.

Completion is reported by the contractor with both cost figures populated — the documented `actual_cost_cents` (overtime, premium freight, and the like) and the `measured_mile_cost_cents` derived from a measured-mile productivity analysis; a completion report missing either is rejected with `ERR_COST_DATA_MISSING`. At completion the `ACTUAL_COST` variant — the default — is always selected: `ACTUAL_COST` recovers the documented actual amount regardless of the measured-mile analysis, while under the `MEASURED_MILE` doctrine the recovery would be a fraction of the measured-mile figure proportional to lost productivity, with baseline productivity the unimpacted installed quantities divided by the unimpacted hours, impacted productivity the total installed quantities divided by the total hours worked within the acceleration window, the loss factor the shortfall of impacted below baseline productivity expressed as a fraction of baseline productivity, never less than zero, and the recovery the `measured_mile_cost_cents` multiplied by that loss factor, rounded half up to two decimal places. The system does not compute the measured-mile formula at completion: completion writes `ACTUAL_COST` onto the directive's `recovery_variant` and sets `recovered_cost_cents` to the documented `actual_cost_cents`, and the `MEASURED_MILE` variant may reach the record only through a negotiated resolution that carries an explicitly agreed recovered amount. A positive recovery is credited to the contractor — billing itself lies outside this system.

Where the parties disagree, the contractor may move a `PERFORMING` directive to `DISPUTED`. The owner then opens negotiation, moving it from `DISPUTED` to `UNDER_NEGOTIATION`, and resolution requires a payload specifying both the `recovery_variant` and the agreed `recovered_cost_cents` (`ERR_COST_DATA_MISSING` if either is absent; a `recovery_variant` other than `ACTUAL_COST` or `MEASURED_MILE` fails payload validation with `ERR_INVALID_REQUEST`), with the recovered amount taken from the payload. Resolution lands the directive in `RESOLVED`; `COMPLETED` and `RESOLVED` are the directive's two terminal states.

### 3.8. Liquidated Damages, Substantial Completion, and Project Closeout

Exposure to liquidated damages is tracked through the **LiquidatedDamagesAssessment**. The `OwnerRepresentative` drafts one by giving the `assessment_period_start` — the first day for which damages are sought — and the inclusive `assessment_period_end`; the system also creates a draft assessment automatically when an approved progress update pushes the projected finish beyond the current completion date (§3.4). Either way the assessment begins in `PROPOSED` with its exposure already quantified. The `culpable_days` count the calendar days from the later of the period start and the project's `current_completion_date` through the earlier of the period end and the projected finish — or the actual substantial-completion date once declared — computed as a plain whole-day date difference (end minus start, with no inclusive extra day), and are never negative. The projected finish for this purpose is that of the project's most recently accepted `UPDATE` schedule, falling back to the most recently accepted `BASELINE`'s projected finish when no accepted update exists, and to the `current_completion_date` itself when neither exists. The `gross_ld_cents` are the `culpable_days` multiplied by the project's `liquidated_damages_daily_rate_cents`.

Assessment converts a draft to `ASSESSED`. It requires at least one culpable day (`ERR_NO_CULPABLE_DELAY`) and applies the aggregate cap: the exposure figures (`culpable_days` and `gross_ld_cents`) are recomputed at the moment of assessment, the `prior_assessed_total_cents` are the sum of `assessed_ld_cents` across the project's other assessments in `ASSESSED`, `UPHELD`, or `REDUCED` state, and the `assessed_ld_cents` are set to the lesser of the gross amount and the remaining cap — the `ld_cap_cents` minus the prior total, never below zero. Because the assessed amount is by construction the lesser of the two, no assessment can push the project's total beyond the cap, and `ERR_LD_CAP_EXCEEDED` is therefore never raised. Alternatively, the owner may waive a draft outright, moving it to the terminal `WAIVED` state with `assessed_ld_cents` set to zero, and the system itself moves a draft to `OFFSET_BY_EOT` — likewise zeroing the assessed amount — when an extension-of-time approval shifts the current completion date across its assessment period (§3.6).

An assessed amount may be appealed by the `ContractorScheduler`, moving the assessment from `ASSESSED` to `APPEALED`, and the owner's answer takes one of three forms: upholding moves it to `UPHELD` unchanged; reduction moves it to `REDUCED` and sets the `assessed_ld_cents` to the payload's `reduced_ld_cents`, which must be strictly less than the currently assessed amount (`ERR_REDUCTION_NOT_SMALLER`); reversal moves it to `REVERSED` and zeroes the assessed amount. All three outcomes are terminal.

Substantial completion is declared by the `OwnerRepresentative` on an `ACTIVE` project and is permitted only when every activity in the latest — most recently accepted — accepted `UPDATE` schedule has reached one hundred percent completion (`ERR_ACTIVITIES_INCOMPLETE`); when no accepted `UPDATE` schedule exists the condition is vacuously satisfied. Declaration moves the project from `ACTIVE` to `SUBSTANTIALLY_COMPLETE` and forces the damages ledger to settle: every `PROPOSED` assessment whose `assessment_period_end` falls on or after the declaration date transitions automatically to `ASSESSED`, applying the same cap computation as a manual assessment but without the minimum-culpable-day precondition, so an automatically settled assessment may record zero `assessed_ld_cents`.

Closing is the final act. A project in `SUBSTANTIALLY_COMPLETE` may move to the terminal `CLOSED` state only when every open exposure has been resolved: all extension-of-time requests must stand in `APPROVED`, `PARTIALLY_APPROVED`, or `DENIED` (`ERR_CLAIMS_OPEN`); all acceleration directives in `COMPLETED` or `RESOLVED` (`ERR_ACCELERATION_OPEN`); and all liquidated damages assessments in `ASSESSED`, `WAIVED`, `OFFSET_BY_EOT`, `UPHELD`, `REDUCED`, or `REVERSED` (`ERR_LD_OPEN`).

## 4. Endpoint Definitions

Operations that create a new resource — a project, a schedule version, an activity, a relationship, a progress update or progress entry, a delay event, an extension-of-time request, an acceleration directive, or a damages assessment — return a `201 Created` status code. Operations that act on an existing resource — every state transition, review action, and the logical-clock capability — return a `200 OK` status code. The request and response payloads behind each operation are defined by the workflows of §3; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the server's logical clock (startup default 2026-05-01T00:00:00Z; never falls back to wall time) | SystemAdmin |
| POST | `/construction-projects` | Create a new construction project | ProjectControlsEngineer |
| GET | `/construction-projects` | List construction projects | Any |
| GET | `/construction-projects/{pid}` | Get a project | Any |
| POST | `/construction-projects/{pid}/activate` | Manually activate a project (rare; normally auto-activates on baseline acceptance) | ProjectControlsEngineer |
| POST | `/construction-projects/{pid}/declare-substantial-completion` | Declare substantial completion | OwnerRepresentative |
| POST | `/construction-projects/{pid}/close` | Close a project | OwnerRepresentative |
| POST | `/construction-projects/{pid}/schedule-versions` | Create a schedule version (BASELINE or UPDATE) | ContractorScheduler |
| GET | `/construction-projects/{pid}/schedule-versions` | List schedule versions for a project | Any |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}` | Get a schedule version | Any |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/submit` | Submit a draft schedule for review; runs CPM | ContractorScheduler |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/accept` | Accept a submitted schedule (OCC on project version) | ProjectControlsEngineer |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/reject` | Reject a submitted schedule | ProjectControlsEngineer |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/revise` | Bring a rejected schedule back to draft for rework | ContractorScheduler |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/activities` | Add an activity to a draft schedule | ContractorScheduler |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/activities` | List activities in a schedule version | Any |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/activities/{aid}` | Get an activity | Any |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/relationships` | Add a logic tie between two activities (cycle-checked) | ContractorScheduler |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/relationships` | List relationships in a schedule version | Any |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates` | Create a progress update against an UPDATE schedule version | ContractorScheduler |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates` | List progress updates | Any |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}` | Get a progress update | Any |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/entries` | Add a per-activity progress entry | ContractorScheduler |
| GET | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/entries` | List entries of a progress update | Any |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/submit` | Submit progress update | ContractorScheduler |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/approve` | Approve progress update (applies actuals, recomputes CPM, may spawn an LD assessment) | ProjectControlsEngineer |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/reject` | Reject progress update | ProjectControlsEngineer |
| POST | `/construction-projects/{pid}/schedule-versions/{vid}/progress-updates/{puid}/revise` | Revise rejected progress update back to draft | ContractorScheduler |
| POST | `/construction-projects/{pid}/delay-events` | Record a delay / change event | ContractorScheduler |
| GET | `/construction-projects/{pid}/delay-events` | List delay events | Any |
| GET | `/construction-projects/{pid}/delay-events/{did}` | Get a delay event | Any |
| POST | `/construction-projects/{pid}/delay-events/{did}/notice` | Submit written notice for a delay event | ContractorScheduler |
| POST | `/construction-projects/{pid}/delay-events/{did}/tia/submit` | Submit time impact analysis | ContractorScheduler |
| POST | `/construction-projects/{pid}/delay-events/{did}/tia/accept` | Accept TIA | ClaimsConsultant |
| POST | `/construction-projects/{pid}/delay-events/{did}/tia/reject` | Reject TIA | ClaimsConsultant |
| POST | `/construction-projects/{pid}/delay-events/{did}/resubmit` | Resubmit rejected TIA back to noticed | ContractorScheduler |
| POST | `/construction-projects/{pid}/eot-requests` | Draft an EOT request against a TIA-accepted delay event | ContractorScheduler |
| GET | `/construction-projects/{pid}/eot-requests` | List EOT requests | Any |
| GET | `/construction-projects/{pid}/eot-requests/{eid}` | Get an EOT request | Any |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/submit` | Submit an EOT | ContractorScheduler |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/begin-review` | Owner begins review | OwnerRepresentative |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/approve` | Approve an EOT in full (OCC on project version) | OwnerRepresentative |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/partial-approve` | Approve an EOT in part | OwnerRepresentative |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/deny` | Deny an EOT | OwnerRepresentative |
| POST | `/construction-projects/{pid}/eot-requests/{eid}/appeal` | Appeal a denied EOT | ContractorScheduler |
| POST | `/construction-projects/{pid}/acceleration-directives` | Owner issues an acceleration directive | OwnerRepresentative |
| GET | `/construction-projects/{pid}/acceleration-directives` | List acceleration directives | Any |
| GET | `/construction-projects/{pid}/acceleration-directives/{aid}` | Get an acceleration directive | Any |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/acknowledge` | Contractor acknowledges directive | ContractorScheduler |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/begin-performance` | Contractor begins acceleration performance | ContractorScheduler |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/complete` | Contractor reports acceleration complete with cost data | ContractorScheduler |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/dispute` | Contractor disputes directive | ContractorScheduler |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/negotiate` | Open negotiation | OwnerRepresentative |
| POST | `/construction-projects/{pid}/acceleration-directives/{aid}/resolve` | Resolve a disputed directive | OwnerRepresentative |
| POST | `/construction-projects/{pid}/ld-assessments` | Draft an LD assessment (the system may also create one automatically on progress-update approval if the schedule overruns) | OwnerRepresentative |
| GET | `/construction-projects/{pid}/ld-assessments` | List LD assessments | Any |
| GET | `/construction-projects/{pid}/ld-assessments/{lid}` | Get an LD assessment | Any |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/assess` | Convert proposed to assessed, applying the LD cap | OwnerRepresentative |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/waive` | Waive a proposed LD assessment | OwnerRepresentative |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/appeal` | Contractor appeals an assessed LD | ContractorScheduler |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/uphold` | Owner upholds LD on appeal | OwnerRepresentative |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/reduce` | Owner reduces LD on appeal | OwnerRepresentative |
| POST | `/construction-projects/{pid}/ld-assessments/{lid}/reverse` | Owner reverses LD on appeal | OwnerRepresentative |
| GET | `/construction-projects/schedule-versions/{vid}` | Flat alias for getting a schedule version by id | Any |
| GET | `/construction-projects/activities/{aid}` | Flat alias for getting an activity by id | Any |
| GET | `/construction-projects/relationships/{rid}` | Flat alias for getting a relationship by id | Any |
| GET | `/construction-projects/progress-updates/{puid}` | Flat alias for getting a progress update by id | Any |
| GET | `/construction-projects/progress-entries/{peid}` | Flat alias for getting a progress entry by id | Any |
| GET | `/construction-projects/delay-events/{did}` | Flat alias for getting a delay event by id | Any |
| GET | `/construction-projects/eot-requests/{eid}` | Flat alias for getting an EOT request by id | Any |
| GET | `/construction-projects/acceleration-directives/{aid}` | Flat alias for getting an acceleration directive by id | Any |
| GET | `/construction-projects/ld-assessments/{lid}` | Flat alias for getting an LD assessment by id | Any |
| GET | `/construction-projects/schedule-versions` | Filtered list of schedule versions across all projects (FK reverse-reachability) | Any |
| GET | `/construction-projects/activities` | Filtered list of activities across all schedule versions (FK reverse-reachability) | Any |
| GET | `/construction-projects/relationships` | Filtered list of activity relationships (FK reverse-reachability) | Any |
| GET | `/construction-projects/progress-updates` | Filtered list of progress updates (FK reverse-reachability) | Any |
| GET | `/construction-projects/progress-entries` | Filtered list of progress entries (FK reverse-reachability) | Any |
| GET | `/construction-projects/delay-events` | Filtered list of delay events across all projects (FK reverse-reachability) | Any |
| GET | `/construction-projects/eot-requests` | Filtered list of EOT requests (FK reverse-reachability) | Any |
| GET | `/construction-projects/acceleration-directives` | Filtered list of acceleration directives (FK reverse-reachability) | Any |
| GET | `/construction-projects/ld-assessments` | Filtered list of LD assessments (FK reverse-reachability) | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the workflow narratives of §2 and §3; this catalogue is a summary reference only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_DETECTED` | 422 Unprocessable Entity |
| `ERR_SELF_RELATIONSHIP` | 422 Unprocessable Entity |
| `ERR_ACTIVITY_NOT_IN_VERSION` | 422 Unprocessable Entity |
| `ERR_INVALID_RELATIONSHIP_TYPE` | 422 Unprocessable Entity |
| `ERR_EMPTY_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_INVALID_PROGRESS` | 422 Unprocessable Entity |
| `ERR_SCHEDULE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_BASELINE_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_BASELINE_NOT_ACCEPTED` | 409 Conflict |
| `ERR_TIA_NOT_ACCEPTED` | 409 Conflict |
| `ERR_REQUESTED_DAYS_EXCEED_ENTITLEMENT` | 422 Unprocessable Entity |
| `ERR_NON_COMPENSABLE_COST` | 422 Unprocessable Entity |
| `ERR_APPROVED_DAYS_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_PARTIAL_DAYS` | 422 Unprocessable Entity |
| `ERR_AWARD_MISMATCH` | 422 Unprocessable Entity |
| `ERR_APPEAL_LIMIT_REACHED` | 409 Conflict |
| `ERR_LD_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NO_CULPABLE_DELAY` | 422 Unprocessable Entity |
| `ERR_REDUCTION_NOT_SMALLER` | 422 Unprocessable Entity |
| `ERR_NOTICE_DATA_INVALID` | 422 Unprocessable Entity |
| `ERR_COST_DATA_MISSING` | 422 Unprocessable Entity |
| `ERR_ACTIVITIES_INCOMPLETE` | 409 Conflict |
| `ERR_CLAIMS_OPEN` | 409 Conflict |
| `ERR_ACCELERATION_OPEN` | 409 Conflict |
| `ERR_LD_OPEN` | 409 Conflict |

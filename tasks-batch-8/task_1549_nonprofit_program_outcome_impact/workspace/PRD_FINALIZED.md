# Nonprofit Program Outcome & Impact API — Product Requirements Document

## 1. Introduction

Evaluation teams at nonprofit organizations live under a double burden. On one side, funders increasingly demand credible, audit-grade evidence that programs move the outcomes they claim to move; on the other, the data behind that evidence is collected by field staff on the ground, under consent obligations that can lapse or be revoked at any moment, across program cycles that span staffing changes, instrument revisions, and external vendor engagements. When the chain from raw observation to funder report is held together by spreadsheets and goodwill, a single consent revocation or one uncertified collector can quietly invalidate an entire reporting period.

This document specifies the Nonprofit Program Outcome & Impact API, a system that makes that chain explicit and enforceable. It governs the full evaluation loop: drafting logic models and the indicators that measure them, versioning data-collection instruments and certifying the collectors who use them, enrolling participants and managing their consent, recording and reviewing field observations, auditing data quality, and generating gated, snapshot-pinned reports for funders — with vendor access scoped to contractual windows and a continuous-improvement loop that routes evaluation findings back into program change. The specification is written for the engineers who will implement it; every rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint and every entity in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If `X-User-Role` is present but does not match one of the declared role names, the request is rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). The recognized roles are `ProgramDirector`, `EvaluationLead`, `FieldCollector`, `DataSteward`, `PrivacyOfficer`, `FunderViewer`, and `VendorAnalyst`.

Each endpoint declares the roles permitted to call it. A recognized role that is not on an endpoint's list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). On top of endpoint-level authorization, two roles carry record-level scoping, and a scope violation is rejected with `ERR_SCOPE_DENIED` (HTTP 403): a `FunderViewer` may only touch reports belonging to their own funder, and a `VendorAnalyst` may only touch resources inside an active engagement's window and scope.

Role identity works as follows. When `X-User-Role` is `ProgramDirector`, `EvaluationLead`, `FieldCollector`, `DataSteward`, or `PrivacyOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `collected_by_id` on an `Observation` recorded by a `FieldCollector`, as `opened_by_id` on a `DataQualityAudit` opened by a `DataSteward`, as `staff_user_id` on a `TrainingCertification` naming the collector being certified, or as the creator identity captured when an `ImprovementAction` is proposed — but it never compares these identifiers to any entity's `id`. When `X-User-Role` is `FunderViewer`, `X-User-ID` is the `id` of the acting `Funder`; ownership checks on a `Report` compare the report's `funder_id` field to `X-User-ID`. When `X-User-Role` is `VendorAnalyst`, `X-User-ID` is the `id` of the acting `VendorEngagement`; access checks compare that engagement's status, access window, and scope against the target resource.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

The `meta` object of a list response always carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Version Counter

Every entity in this system — programs, funders, logic models, indicators, cycles, participants, consent records, instruments, certifications, observations, milestones, audits, findings, reports, vendor engagements, and improvement actions — carries the same four system-managed properties:

- **`id`** (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on any change to the resource.
- **`version`** (integer): a mutation counter that increments by exactly one on every modification of the resource, including every state transition.

Every state transition described in §3 therefore bumps the transitioning entity's `version` by one and refreshes its `updated_at`, even where the prose does not repeat this. Where one operation also mutates *other* entities — a superseded logic model, a withdrawn participant's observations, a recomputed cycle aggregate — those cross-entity effects are stated explicitly at the workflow that causes them, and each affected entity's `version` and `updated_at` advance per the same rule.

### 2.5. The Logical Clock and Lazy Expiry

All time-dependent logic in the system — enrollment windows, milestone due dates, consent and certification expiry, vendor access windows, observation lateness — is evaluated against a single server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. A `ProgramDirector`-only administrative capability sets the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`; before any such call, the clock continues to read the startup default.

Two entity families use **lazy expiry**. A `ConsentRecord` in `GRANTED` status whose `expires_at` is on or before the current logical time is treated as `EXPIRED` the next time any consent check or read touches it: its status flips to `EXPIRED`, its `version` increments, and the owning participant's `consent_status` is recomputed. A `TrainingCertification` in `CERTIFIED` status whose `expires_at` is on or before the current logical time likewise flips to `EXPIRED` at the next certification check or read. After the clock is advanced, these re-evaluations happen on the next read or check of the affected records.

### 2.6. Calendar Windows: Closed Cycles, Half-Open Access

Three different time-window semantics coexist in this system, and the difference between them is contractual.

**Program cycles** occupy a *closed* interval from `cycle_start` through `cycle_end`, inclusive of both endpoints. When a new cycle is created, its interval must not intersect the interval of any other cycle of the same program — and because the intervals are closed, two cycles that merely share a boundary instant **do** intersect and are rejected with `ERR_CYCLE_WINDOW_OVERLAP` (HTTP 409). Cycle creation also requires `enrollment_start` to be on or before `enrollment_end` and `cycle_start` to be on or before `cycle_end`; violations of these ordering constraints are rejected with the same `ERR_CYCLE_WINDOW_OVERLAP`.

**Vendor engagements** occupy a *half-open* interval that begins at `access_start` and runs up to — but does not include — `access_end`. Two engagements whose windows merely touch (one's `access_end` equal to the other's `access_start`) do **not** overlap.

**Enrollment windows** and **milestone due dates** use inclusive boundaries: enrollment is permitted at any instant from `enrollment_start` through `enrollment_end` inclusive, and a milestone becomes evaluable the moment the current time reaches its `due_date`.

### 2.7. Measurement Precision and Rounding

Every computed quantity in the system — attainment percentages, data completeness, data-quality scores, the overall impact index, and all snapshot copies of them — is produced at exactly 2 decimal places using the round-half-up method. Where a calculation is specified as a sequence of steps, each step that is stated to round does so before the next step consumes its result; rounding is never deferred to the end of a multi-step computation. Raw input numbers supplied by clients (such as `baseline_value`, `target_value`, `weight`, `value`, and `milestone_target`) are stored at the precision they were supplied.

### 2.8. Optimistic Concurrency Control

Exactly two write operations in the system carry an optimistic-concurrency contract; no other endpoint accepts a version field.

Creating a report under a cycle requires the request to carry `expected_program_cycle_version`, holding the `version` of the parent `ProgramCycle` the client last observed. If the cycle's current `version` differs — because the client is working from a read that no longer reflects the cycle — the creation is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). A new report legitimately supersedes an existing `DRAFT` or `GENERATED` report for the same cycle-funder-type triple, so a writer holding a stale cycle version must re-read the cycle before creating a replacement.

Approving a logic model requires the request to carry `expected_program_version`, holding the `version` of the parent `Program` the client last observed. A mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Approval supersedes the program's currently `APPROVED` model, so a writer holding a stale program version would otherwise supersede a model it never saw.

### 2.9. Validation Order and Segregation of Duties

When several validation rules guard the same endpoint, they are evaluated in a fixed order, and an earlier failure masks all later ones. The order is: presence of the two authentication headers (`ERR_MISSING_AUTH_HEADERS`); the role name being recognized (`ERR_UNKNOWN_ROLE`); the role being authorized for the endpoint (`ERR_UNAUTHORIZED_ROLE`); record-level role scoping for `FunderViewer` and `VendorAnalyst` callers (`ERR_SCOPE_DENIED`); existence of every path identifier, validated left to right (`ERR_NOT_FOUND`); request-body well-formedness — required fields present, types correct, enum values within their declared sets (`ERR_INVALID_REQUEST`); the target entity being in a state from which the requested transition or child creation is defined (`ERR_INVALID_STATE`); the domain business rules specific to the operation, in the order stated at that operation in §3; and, last of all, the stale-version checks of §2.8.

Two body-handling conventions apply everywhere. Unknown fields and system-managed fields supplied in a request body are ignored, not rejected. And a validation that fails at any step produces exactly the error paired with that step — later checks are not consulted.

**Segregation of duties** is a cross-cutting business rule with a single error code, `ERR_SEGREGATION_OF_DUTY` (HTTP 422), guarding four operations: a `DataSteward` cannot validate an observation whose `collected_by_id` equals their own `X-User-ID`; a `DataSteward` cannot waive a finding that references such a self-collected observation; a `DataSteward` cannot remediate a finding that references such a self-collected observation; and a `ProgramDirector` cannot approve an `ImprovementAction` they themselves created.

### 2.10. Nested Resource Retrieval

Requests that target nested resources are validated strictly left to right along the path. The server resolves each identifier in order and responds with `ERR_NOT_FOUND` (HTTP 404) for the *first* identifier that does not resolve to an existing resource, without consulting later identifiers. A request for a participant under a nonexistent cycle therefore fails on the cycle before the participant is ever examined, and creation endpoints apply the same parent-first discipline before any business rule runs.

## 3. Business Logic & Workflows

### 3.1. Programs, Funders, and the Administrative Backbone

Everything in the system hangs off a **Program**. A `ProgramDirector` creates one by supplying a human-readable `name` and a `code`; the code must be unique across all programs, and a duplicate is rejected with `ERR_DUPLICATE_CODE` (HTTP 409). A new program begins in `DRAFT` status, with `current_logic_model_id` unset — no measurement framework is attached until a logic model wins approval — and with `current_consent_form_version` set to 1, the first edition of the program's consent form.

The program lifecycle is a small state machine. Activation moves `DRAFT → ACTIVE`. Suspension moves `ACTIVE → SUSPENDED`, and resuming moves `SUSPENDED → ACTIVE`. Archival is permitted from either `ACTIVE` or `SUSPENDED`, but only after every program cycle of that program has itself reached `ARCHIVED`; a program whose cycles are still live cannot be archived. Any lifecycle call against a program in the wrong state is rejected with `ERR_INVALID_STATE` (HTTP 409).

Funders are simpler. A `ProgramDirector` registers a **Funder** with a `name` and a globally unique `code` (again `ERR_DUPLICATE_CODE` on collision). A funder starts `ACTIVE`; deactivation moves `ACTIVE → INACTIVE` and reactivation moves `INACTIVE → ACTIVE`. An `INACTIVE` funder cannot receive new reports — creating a report addressed to one is rejected with `ERR_FUNDER_INACTIVE` (HTTP 422) — while reports already in flight remain readable.

Both catalogs are listable: the programs list accepts optional `status` and `current_logic_model_id` filters, and the funders list accepts an optional `status` filter.

### 3.2. Logic Models and the Measurement Framework

An `EvaluationLead` drafts a program's measurement framework as a **LogicModel** — the narrative theory of change covering inputs, activities, outputs, outcomes, and impact. Creation takes a `title` and an optional `description` (empty by default). Each model receives a per-program monotonic `version_no`: one greater than the highest `version_no` among that program's existing models. A new model is `DRAFT`, and `approved_at` stays unset until approval.

Indicators are the measurable vertices of the model. An `EvaluationLead` creates them only while the parent model is `DRAFT` — attempts under a model in any other state are rejected with `ERR_INVALID_STATE`. Every indicator records which model it belongs to in its `logic_model_id`, and it is this linkage that the pinned-model checks in §3.6 and §3.8 compare against the cycle's `pinned_logic_model_id`. Each indicator carries: a `code` unique within its logic model (`ERR_DUPLICATE_CODE` on a clash); a `level` of `OUTPUT`, `OUTCOME`, or `IMPACT`; a `unit` of `COUNT`, `PERCENT`, or `SCORE`; a `direction` of `HIGHER_IS_BETTER` or `LOWER_IS_BETTER`; a `baseline_value` against which attainment is measured; a `target_value` (which may equal the baseline — the zero-guard rule below governs that case); a `weight` that defaults to 1.0 and must be greater than zero; and a `measurement_frequency` of `PER_EVENT`, `MONTHLY`, or `END_OF_CYCLE`. New indicators are `DRAFT`. While the parent model remains `DRAFT`, an `EvaluationLead` may patch any of these input fields; once the model leaves `DRAFT`, indicator edits are rejected with `ERR_INVALID_STATE`.

The approval workflow runs `DRAFT → SUBMITTED → APPROVED`, with a rejection loop. Submission requires the model to contain at least one indicator — an empty model cannot be submitted (`ERR_INVALID_STATE`). Rejection moves `SUBMITTED → REJECTED` and accepts an optional `reason`; revision moves `REJECTED → DRAFT`, reopening the model and its indicators for editing.

Approval is the consequential step, and it is guarded by the optimistic-concurrency rule of §2.8: the request must carry `expected_program_version`, and a mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). When approval succeeds, several things happen as one atomic act. The previously `APPROVED` model of the same program, if any, transitions `APPROVED → SUPERSEDED`. Every `ACTIVE` indicator of that superseded model transitions to `RETIRED`. Every `DRAFT` indicator of the newly approved model transitions to `ACTIVE`. The program's `current_logic_model_id` is set to the newly approved model, the model's `approved_at` is stamped, and the program's own `version` advances by one in addition to the version increments on the two models and their indicators. At most one model per program is ever `APPROVED` at a time. Separately, an `EvaluationLead` may retire any `ACTIVE` indicator outright (`ACTIVE → RETIRED`), for instance when a measure is dropped mid-program; `RETIRED` is terminal.

**Attainment** is the fundamental computed read over indicator data, exposed as a per-indicator, per-cycle query taking `program_cycle_id` and an optional `variant` — `PROVISIONAL` or `FINAL`, defaulting to `FINAL` — and returning `aggregated_value`, `attainment_pct`, `band`, and `observation_count`. The input set is the observations recorded against this indicator whose participant belongs to the given cycle and is not `WITHDRAWN`, restricted by review status according to the variant: `PROVISIONAL` admits `PENDING` and `VALIDATED` observations (it exists for mid-cycle monitoring), while `FINAL` admits only `VALIDATED` observations (it is the default, and the variant consumed by milestone evaluation and the impact index). `FLAGGED` and `EXCLUDED` observations are never included in either variant.

The computation follows a pinned order. First, the aggregated value is the arithmetic mean of `value` across the input set, rounded half-up to two decimal places. Second, the zero-guard: if `target_value` equals `baseline_value`, attainment is exactly 100.00 when the direction condition holds — for `HIGHER_IS_BETTER`, the aggregated value is at least the target; for `LOWER_IS_BETTER`, it is at most the target — and exactly 0.00 otherwise. Third, when target and baseline differ: for `HIGHER_IS_BETTER`, the attainment percentage is one hundred times the amount by which the aggregated value exceeds the baseline, divided by the amount by which the target exceeds the baseline; for `LOWER_IS_BETTER`, it is one hundred times the amount by which the baseline exceeds the aggregated value, divided by the amount by which the baseline exceeds the target. Fourth, the result is clamped to a floor of 0 and a ceiling of 150. Fifth, it is rounded half-up to two decimal places. When the variant's input set is empty, `aggregated_value`, `attainment_pct`, and `band` are null and `observation_count` is zero.

Every surfaced attainment percentage carries an **attainment band**: `GREEN` when the percentage is 90.00 or higher, `YELLOW` when it is 70.00 or higher but below 90.00, and `RED` below 70.00. Boundaries are inclusive at the lower edge — exactly 90.00 is `GREEN`, exactly 70.00 is `YELLOW`.

### 3.3. Instruments and Collector Certification

Data-collection instruments are versioned questionnaires and protocols. An `EvaluationLead` creates one under a program with a `code` and a `title`; the first instrument bearing a given code within a program receives `instrument_version` 1, and new instruments start `DRAFT`. When the instrument needs revision, a new-revision action on it creates a successor — a fresh `DRAFT` instrument under the same program and `code`, with `instrument_version` one greater than the instrument it was spun from.

Publishing moves an instrument `DRAFT → PUBLISHED` and triggers a hand-off: the predecessor revision — the instrument with the same program and `code` whose `instrument_version` is exactly one less — if currently `PUBLISHED`, transitions to `RETIRED`, and every certification pinned to that predecessor that is still `CERTIFIED` transitions to `STALE`. Retiring a `PUBLISHED` instrument directly (`PUBLISHED → RETIRED`, terminal) likewise stales every `CERTIFIED` certification pinned to it. In short, collectors are never left silently certified on a superseded or withdrawn instrument.

Certification itself is how a collector earns the right to record data with an instrument. An `EvaluationLead` creates a **TrainingCertification** supplying `staff_user_id` — the opaque `X-User-ID` the collector presents at request time, not a link to any persisted user entity — the `instrument_id` of a published instrument, and an `expires_at` instant. At creation the certification pins `certified_instrument_version` to the instrument's current `instrument_version`, stamps `certified_at`, and starts in `CERTIFIED` status.

From there a certification can be suspended (`CERTIFIED → SUSPENDED`) and later reinstated (`SUSPENDED → CERTIFIED`) — but reinstatement only succeeds while the pinned version still matches the instrument's current `instrument_version`; once the instrument has advanced past the pinned version, reinstatement is rejected with `ERR_CERTIFICATION_STALE` (HTTP 422). Two system transitions complete the lifecycle: a certification goes `CERTIFIED → STALE` when the instrument's version advances beyond the pinned version or the instrument is retired, and it goes `CERTIFIED → EXPIRED` by lazy expiry per §2.5. Both `STALE` and `EXPIRED` are terminal. The certifications list supports `staff_user_id`, `instrument_id`, and `status` filters.

### 3.4. Program Cycles and Participant Enrollment

A **ProgramCycle** is one delivery period of a program — the unit against which data is collected, audited, and reported. A `ProgramDirector` creates a cycle with a `label` (for example, `2026-FALL`), the enrollment window (`enrollment_start`, `enrollment_end`), the cycle window (`cycle_start`, `cycle_end`), and a `reporting_due_date` that records the funder reporting deadline for informational purposes. The closed-interval overlap and ordering rules of §2.6 apply at creation (`ERR_CYCLE_WINDOW_OVERLAP`). New cycles are `SETUP`, and the computed aggregates `active_participant_count`, `total_observation_count`, `validated_observation_count`, `data_completeness_pct`, and `latest_dq_score` start at zero or null.

The cycle lifecycle is the spine of the whole system. Opening enrollment moves `SETUP → ENROLLING` and requires the owning program to be `ACTIVE`. If enrollment was opened prematurely, reverting moves `ENROLLING → SETUP`, but only while the cycle still has zero participants. Activation moves `ENROLLING → ACTIVE` and performs the system's central act of **version pinning**: the cycle's `pinned_logic_model_id` is set to the program's `current_logic_model_id`, and `consent_form_version_snapshot` captures the program's `current_consent_form_version` at that instant. Both pins are immutable thereafter, so a later logic-model approval or consent-form change cannot retroactively redefine what an in-flight cycle was measuring or which consent edition it was operating under. Activation requires the program to be `ACTIVE` and to have an approved logic model; without one, the request is rejected with `ERR_INVALID_STATE`.

When field collection ends, closing data moves `ACTIVE → DATA_CLOSED`, and every participant still `ACTIVE` hops to `COMPLETED` — the cycle's `active_participant_count` is recomputed and becomes zero. If late corrections are needed, reopening moves `DATA_CLOSED → ACTIVE` and compensates exactly: every participant in `COMPLETED` returns to `ACTIVE` and the count is recomputed again. Review begins with `DATA_CLOSED → UNDER_REVIEW`. Marking the cycle reported (`UNDER_REVIEW → REPORTED`) is allowed only when no report of the cycle sits in `DRAFT`, `GENERATED`, `DELIVERED`, or `RETURNED` — every report must have reached a terminal or superseded state first. Finally, `REPORTED → ARCHIVED` closes the cycle for good. Every transition into or out of the wrong state is `ERR_INVALID_STATE`.

Participants join during enrollment. A `ProgramDirector` enrolls a participant by supplying an `external_ref` — a pseudonymous code that must be unique within the cycle (`ERR_DUPLICATE_CODE` on collision). The cycle must be `ENROLLING` or `ACTIVE` (otherwise `ERR_INVALID_STATE`), and the current logical time must fall within the enrollment window, inclusive of both `enrollment_start` and `enrollment_end`; outside the window the enrollment is rejected with `ERR_ENROLLMENT_WINDOW_CLOSED` (HTTP 422). A new participant is `ENROLLED`, with `enrolled_at` stamped by the server.

A participant becomes `ACTIVE` only through consent (see §3.5). From `ACTIVE`, a `ProgramDirector` may exit the participant (`ACTIVE → EXITED`), recording the supplied `reason` as `exit_reason`. Re-enrollment moves `EXITED → ACTIVE` and requires the participant's `consent_status` to be `CURRENT` — a participant whose consent has lapsed cannot be re-admitted without fresh consent. `WITHDRAWN` is terminal and is reachable only through the consent-revocation cascade of §3.5.

The cycle's aggregate fields deserve precise definition, because dashboards, audits, and the reporting gate all read them. `active_participant_count` is the number of participants currently `ACTIVE`, maintained on every participant transition. `total_observation_count` counts the cycle's observations whose `review_status` is anything other than `EXCLUDED`. `validated_observation_count` counts those in `VALIDATED`. `latest_dq_score` is the standard-variant data-quality score of the most recent audit, refreshed when an audit opens, when a finding is waived or remediated, and when an audit closes; it is null until the cycle's first audit.

`data_completeness_pct` measures coverage of the measurement plan. The eligible participants are those in `ACTIVE`, `COMPLETED`, or `EXITED` status; the active indicators are those of the cycle's pinned logic model in `ACTIVE` status. If either set is empty, `data_completeness_pct` is null. Otherwise, for each eligible participant, count the distinct active indicators for which that participant has at least one observation in `PENDING` or `VALIDATED` review status; the completeness percentage is one hundred times the sum of these per-participant counts, divided by the product of the eligible-participant count and the active-indicator count, rounded half-up to two decimal places. It is recomputed on every observation creation, validation, or exclusion, and on every participant status transition.

Cycles are reachable two ways: the per-program list, and a cross-program list that accepts `program_id`, `pinned_logic_model_id`, and `status` filters. The participants-of-a-cycle list accepts a `status` filter.

### 3.5. Consent, Privacy, and the Withdrawal Cascade

Consent is managed exclusively by the `PrivacyOfficer`, who is deliberately barred from reading observation data — the role sees programs, cycles, participants, consents, funders, logic models, and indicators, but never field measurements.

Granting consent creates a **ConsentRecord** from `form_version`, a `scope` of `FULL` or `AGGREGATE_ONLY`, and an `expires_at` instant; the server stamps `granted_at`. The presented `form_version` must equal the program's `current_consent_form_version` — consent captured on a stale form edition is rejected with `ERR_STALE_CONSENT_FORM` (HTTP 422). At most one record per participant may be `GRANTED` at a time: a new grant supersedes any prior `GRANTED` record for the same participant, flipping it to `SUPERSEDED` and recomputing the participant's `consent_status`.

A grant also unlocks the participant lifecycle: an `ENROLLED` participant whose new consent is current — its `form_version` matches the program's `current_consent_form_version` and its `expires_at` lies strictly in the future — transitions `ENROLLED → ACTIVE` automatically, and the cycle's `active_participant_count` is recomputed.

The participant's `consent_status` is derived, never set directly. It is `CURRENT` when the participant's latest `GRANTED` consent is unexpired and its `form_version` equals the program's current consent form version. It is `EXPIRED` when a consent was granted but has since time-expired or form-expired. It is `NONE` otherwise — never granted, superseded without replacement, or revoked. Lazy expiry per §2.5 flips a `GRANTED` record whose `expires_at` has passed to `EXPIRED` at the next check or read, with `consent_status` recomputed in the same breath.

Revocation is the privacy system's heavy hammer. When the `PrivacyOfficer` revokes a `GRANTED` record (`GRANTED → REVOKED`, stamping `revoked_at`) and the participant holds no other `GRANTED` consent, the participant — whether `ENROLLED`, `ACTIVE`, or `EXITED` — is withdrawn: status `WITHDRAWN`, `consent_status` recomputed to `NONE`. The cascade continues into the data plane: every observation of that participant in `PENDING`, `VALIDATED`, or `FLAGGED` review status transitions to `EXCLUDED` with `exclusion_reason` set to `CONSENT_REVOKED`. And it finishes in the aggregates: the cycle's observation counters, `data_completeness_pct`, and `active_participant_count` are recomputed, and if an audit exists for the cycle its data-quality fields are recomputed as well. One revocation can therefore move numbers all the way up to a pending report's gate — which is precisely the intended behavior.

The program-level **consent-form bump** is the forward-looking counterpart. When the legal team issues a new consent edition, a `PrivacyOfficer` advances the program's `current_consent_form_version` by one. Every `GRANTED` consent of every participant in every cycle of the program whose `form_version` now trails the new value transitions `GRANTED → SUPERSEDED`, and each affected participant's `consent_status` is recomputed (typically landing on `EXPIRED` until fresh consent is captured). A cycle activated before the bump keeps its own `consent_form_version_snapshot` as the audit-trail record of which edition it started under. A participant's consent history is listable with an optional `status` filter.

### 3.6. Field Data Collection and Steward Review

A `FieldCollector` records an **Observation** against a participant with a payload naming the `indicator_id` measured, the `instrument_id` used, the measured `value`, and `collected_at` — the moment the data was gathered in the field, which may legitimately precede the recording instant (late-arriving data). At record time the server pins `instrument_version` to the instrument's current version, stamps `recorded_at` from the logical clock, captures `collected_by_id` as the acting collector's `X-User-ID` (the segregation-of-duties anchor used later), and computes `is_late`: true exactly when `recorded_at` falls after the owning cycle's `cycle_end`. The observation starts in `PENDING` review status, and its creation recomputes the cycle's `total_observation_count` and `data_completeness_pct`.

Recording is the most heavily guarded write in the system. After the generic checks of §2.9 (authentication, authorization, scoping, path existence, body well-formedness), the domain checks fire **in exactly this order**, each failure masking all later ones. First, the owning cycle must be `ACTIVE` — observations are child mutations permitted only during live collection — else `ERR_INVALID_STATE` (HTTP 409). Second, consent: the participant must not be `WITHDRAWN` and their `consent_status` must be `CURRENT` — a granted consent whose `expires_at` has passed or whose `form_version` trails the program's current edition fails — else `ERR_CONSENT_NOT_CURRENT` (HTTP 422). Third, the instrument must be `PUBLISHED`, else `ERR_INSTRUMENT_NOT_PUBLISHED` (HTTP 422). Fourth, the indicator must be `ACTIVE` and belong to the cycle's pinned logic model, else `ERR_INDICATOR_NOT_IN_MODEL` (HTTP 422). Fifth, a `TrainingCertification` must exist pairing the acting collector's `X-User-ID` (as `staff_user_id`) with the instrument, else `ERR_CERTIFICATION_MISSING` (HTTP 422). Sixth, that certification's `certified_instrument_version` must equal the instrument's current `instrument_version` and the certification must not be `STALE`, else `ERR_CERTIFICATION_STALE` (HTTP 422). Seventh and last, the certification must be in `CERTIFIED` status with `expires_at` strictly in the future — a suspended, expired, or past-due certification fails — else `ERR_CERTIFICATION_EXPIRED` (HTTP 422).

Review is the `DataSteward`'s desk. Validation moves an observation from `PENDING` or `FLAGGED` to `VALIDATED`; the steward performing it must not be the collector who recorded it — when the steward's `X-User-ID` equals the observation's `collected_by_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 422). Each validation recomputes the cycle's `validated_observation_count` and `total_observation_count`, refreshes `data_completeness_pct`, and — when an open or most-recent audit exists for the cycle — recomputes the audit's data-quality fields and the cycle's `latest_dq_score`. Flagging moves `PENDING → FLAGGED` and records the steward's `reason`; a flagged observation remains inside every denominator, so cycle counters and completeness are deliberately unchanged by a flag. Exclusion moves an observation from `PENDING`, `VALIDATED`, or `FLAGGED` to `EXCLUDED` (terminal), recording the supplied `reason` as `exclusion_reason` — or `CONSENT_REVOKED` when the consent cascade of §3.5 drove the exclusion — and recomputing counters, completeness, and any audit-linked quality fields.

Observations are listable per cycle and per participant (each with a `review_status` filter), per instrument (also `review_status`), and through a global list accepting `participant_id`, `indicator_id`, `instrument_id`, and `review_status` filters.

### 3.7. Data Quality Audits and Findings

When a cycle's data is closed (or under review), a `DataSteward` opens a **DataQualityAudit** — the compliance heart of the system. Opening requires the cycle to be `DATA_CLOSED` or `UNDER_REVIEW` (otherwise `ERR_INVALID_STATE`), and at most one audit per cycle may be `OPEN` at a time: a second open attempt is rejected with `ERR_AUDIT_ALREADY_OPEN` (HTTP 409). At open, the server records `opened_by_id` as the steward's `X-User-ID`, snapshots `completeness_pct` from the cycle's `data_completeness_pct` (a null completeness is snapshotted as 0.00), snapshots `validated_pct` as the standard-variant validated percentage, computes the audit's `dq_score`, and refreshes the cycle's `latest_dq_score`.

The **data-quality score** combines completeness, validation coverage, consent currency, and open findings, in a pinned evaluation order. First, the mutation that triggered the recompute — audit open, a finding recorded, a finding resolved, an observation validated or excluded, or audit close — is applied. Second, three components are computed from the post-mutation state: **C** is the cycle's `data_completeness_pct`, or 0.00 when it is null; **V** is one hundred times `validated_observation_count` divided by `total_observation_count`, rounded half-up to two decimals, or 0.00 when the total is zero; **K** is one hundred times the number of the cycle's participants whose `consent_status` is `CURRENT`, divided by the number of its participants not in `WITHDRAWN`, rounded half-up to two decimals, or 0.00 when there are none. Third, **F** counts the findings in `OPEN` status belonging to any audit of this cycle, regardless of those audits' own status. Fourth, the raw score is one-half of C, plus three-tenths of V, plus one-fifth of K, minus 4.00 for each open finding. Fifth, the result is clamped to the range from 0 to 100. Sixth, it is rounded half-up to two decimal places and written to the audit's `dq_score` and the cycle's `latest_dq_score`. This **STANDARD** variant drives audits, the reporting gate, and report snapshots. A **STRICT** variant, surfaced on the cycle dashboard as `dq_score_strict`, differs only in V: observations flagged `is_late` are dropped from both the numerator and the denominator of the validation-coverage component, while C and K are computed exactly as in the standard variant.

Findings are the audit's line items. A `DataSteward` records one under an `OPEN` audit (otherwise `ERR_INVALID_STATE`), supplying a `finding_type` of `MISSING_DATA`, `OUTLIER`, `UNCERTIFIED_COLLECTOR`, `CONSENT_LAPSE`, or `LATE_DATA`; the `participant_id` the finding concerns; optionally the `indicator_id` it concerns; optionally the `observation_id` it concerns (null for `MISSING_DATA` findings, which by definition have no observation); and an optional free-text `description`. Recording a finding recomputes the audit's `open_finding_count` and its `dq_score` — each new open finding drags the score down by the per-finding penalty — and the cycle's `latest_dq_score` follows.

Resolution comes in two flavors. Waiving a finding (`OPEN → WAIVED`) takes a `reason`; remediating one (`OPEN → REMEDIATED`) takes a `note`; either text is recorded as the finding's `resolution_note`. Both actions require the finding to be `OPEN` under an audit that is itself still `OPEN` — attempting either on a finding of a closed audit, or on a finding already resolved, is rejected with `ERR_INVALID_STATE`. When the finding references an observation, segregation of duties applies to both actions: the acting steward's `X-User-ID` must differ from that observation's `collected_by_id`, else `ERR_SEGREGATION_OF_DUTY`. Each resolution recomputes `open_finding_count` and the quality fields — the penalty lifts as findings leave `OPEN`.

Closing an audit (`OPEN → CLOSED`) requires every finding to be resolved: with any finding still `OPEN` (`open_finding_count` above zero), the close is rejected with `ERR_INVALID_STATE`. Closing stamps `closed_at`, recomputes `dq_score` one final time, and copies it to the cycle's `latest_dq_score`. Audits of a cycle are listable with a `status` filter; findings are listable per audit (`status`, `finding_type`), per participant (`status`), and globally with `audit_id`, `observation_id`, `participant_id`, `indicator_id`, and `status` filters.

### 3.8. Milestones, Dashboards, and Funder Reporting

**Milestones** are scheduled checkpoints that convert the measurement framework into pass/fail accountability. An `EvaluationLead` defines one against a cycle in `ACTIVE`, `DATA_CLOSED`, or `UNDER_REVIEW` status (any other cycle state is `ERR_INVALID_STATE`), supplying the `indicator_id` to evaluate, a `due_date`, and a `milestone_target`. The indicator must be `ACTIVE` and belong to the cycle's pinned logic model — otherwise the definition is rejected with `ERR_INDICATOR_NOT_IN_MODEL` (HTTP 422). New milestones are `PENDING`.

Evaluation is a batch action driven by a `ProgramDirector`. Every `PENDING` milestone of the cycle whose `due_date` is on or before the current logical time — an inclusive boundary — is evaluated against the FINAL variant of attainment for its indicator in this cycle: the aggregated value is the mean of the indicator's `VALIDATED` observations from non-withdrawn participants of the cycle, rounded half-up to two decimal places before any comparison. If that aggregated value does not exist (no `VALIDATED` observations), the milestone becomes `MISSED`. Otherwise the direction governs the comparison: for `HIGHER_IS_BETTER`, the milestone becomes `MET` when the aggregated value is at least `milestone_target`; for `LOWER_IS_BETTER`, when it is at most `milestone_target`; failing the comparison means `MISSED`. Each evaluated milestone stamps `evaluated_at`. Milestones whose `due_date` lies in the future remain `PENDING`, are untouched, and are not counted in the batch tallies; the response reports `evaluated_count`, `met_count`, and `missed_count`. Milestones are listable per cycle and per indicator, each with a `status` filter.

The **cycle dashboard** is a computed read returning four numbers: `overall_impact_index`, `data_completeness_pct`, `dq_score_standard`, and `dq_score_strict`. The completeness and the two data-quality variants are computed exactly as specified in §3.4 and §3.7. The **overall impact index** aggregates attainment across the pinned model. The eligible indicators are those of the cycle's pinned logic model in `ACTIVE` status that have at least one `VALIDATED` observation in the cycle. If no indicator is eligible, or the eligible indicators' `weight` values sum to zero, the index is null. Otherwise: for each eligible indicator, take its FINAL-variant attainment percentage, multiply it by the indicator's `weight`, and round that product half-up to two decimal places *before* summing — per-term rounding is pinned, since summing exact products and rounding once would produce a different number. The index is the sum of those rounded products divided by the sum of the eligible indicators' weights (renormalized over the eligible set only), with the quotient rounded half-up to two decimal places.

**Reports** package a cycle for a specific audience. An `EvaluationLead` creates one under a cycle with a `funder_id`, a `report_type` of `FUNDER_STANDARD`, `FUNDER_CUSTOM`, or `INTERNAL_DASHBOARD`, and — per §2.8 — `expected_program_cycle_version`; a mismatch with the cycle's current `version` is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). The cycle must be `UNDER_REVIEW` or `REPORTED` (otherwise `ERR_INVALID_STATE`), and the funder must be `ACTIVE` (`ERR_FUNDER_INACTIVE`). Creation also enforces replacement semantics: any existing report of the same cycle, funder, and type in `DRAFT` or `GENERATED` status transitions to `SUPERSEDED`, and the cycle's `version` advances by one. New reports start `DRAFT`.

Generation (`DRAFT → GENERATED`) is where the quality gate bites. For `FUNDER_STANDARD` and `FUNDER_CUSTOM` reports, the cycle's `latest_dq_score` must be present and at least 80.00; when it is null or lower, generation is rejected with `ERR_DQ_GATE_NOT_MET` (HTTP 422). `INTERNAL_DASHBOARD` reports are exempt from the gate. On generation the report pins three snapshots at that instant: `snapshot_overall_impact_index` from the final-variant impact index, `snapshot_data_completeness_pct` from the cycle, and `snapshot_dq_score` from `latest_dq_score` — and stamps `generated_at`. Delivery (`GENERATED → DELIVERED`) stamps `delivered_at`.

The funder then judges. Acceptance (`DELIVERED → ACCEPTED`, terminal) and return (`DELIVERED → RETURNED`, carrying a `reason`) are `FunderViewer` operations restricted to the funder of record: the acting `X-User-ID` must equal the report's `funder_id`, and any attempt on another funder's report is `ERR_SCOPE_DENIED` (HTTP 403). The same scoping governs reads — a `FunderViewer` fetching a single report sees it only if it belongs to their funder, and the report list is forcibly restricted to reports whose `funder_id` equals the caller's `X-User-ID`. A returned report enters the rework loop: regeneration (`RETURNED → GENERATED`) recomputes and re-pins all three snapshot fields at the new instant — the underlying data may have changed during rework — re-stamps `generated_at`, and re-applies the data-quality gate for the two funder report types. Reports are listable per cycle and globally; the global list accepts `funder_id`, `program_cycle_id`, and `status` filters.

### 3.9. Vendor Engagements and the Continuous Improvement Loop

External evaluation vendors are admitted through a **VendorEngagement**. A `ProgramDirector` proposes one with the `vendor_name`, a `scope_program_cycle_ids` array naming the cycles the vendor may access, an access window (`access_start`, `access_end`), and a contractual `deliverable_due` date. Per §2.6 the window is half-open, and a conflict exists only when the new engagement's window *overlaps* — touching does not count — the window of another engagement of the same program in `PROPOSED` or `ACTIVE` status whose scope shares at least one cycle with the new scope; a conflict is rejected with `ERR_ENGAGEMENT_WINDOW_OVERLAP` (HTTP 409). A new engagement is `PROPOSED`.

Activation (`PROPOSED → ACTIVE`) requires the owning program to be `ACTIVE`. Once active, the vendor's analyst users — `VendorAnalyst` callers whose `X-User-ID` is the engagement's `id` — may read their own engagement and, only while the engagement remains `ACTIVE` and the current logical time lies within the access window from `access_start` up to but not including `access_end`, may read the in-scope cycles and those cycles' observations. Any vendor read or write outside the engagement, its window, its `ACTIVE` status, or its scope is rejected with `ERR_SCOPE_DENIED`. The vendor submits its deliverable with a `note` while the engagement is `ACTIVE` and inside the window; the server stamps `deliverable_received_at`. Completion (`ACTIVE → COMPLETED`) requires that the deliverable has in fact been received — without `deliverable_received_at` set, completion is rejected with `ERR_INVALID_STATE`. An engagement that sours can be terminated from either `PROPOSED` or `ACTIVE` (`→ TERMINATED`). Engagements of a program are listable with a `status` filter.

The improvement loop closes the system back on itself. An `EvaluationLead` proposes an **ImprovementAction** under a program with a `title`, an optional `description` of what will change, and optional provenance: `audit_finding_id` when the action answers a specific audit finding, `report_id` when it answers a returned report. The proposing user's `X-User-ID` is recorded at creation for the segregation-of-duties check that follows. Approval (`PROPOSED → APPROVED`) is a `ProgramDirector` call, but the proposer cannot approve their own action — when the approver's `X-User-ID` equals the recorded creator's, the approval is rejected with `ERR_SEGREGATION_OF_DUTY`. Execution then runs `APPROVED → IN_PROGRESS → IMPLEMENTED` under the `EvaluationLead`. Verification is again the `ProgramDirector`'s call and takes an `outcome`: `EFFECTIVE` moves the action `IMPLEMENTED → VERIFIED_EFFECTIVE` (terminal), while `INEFFECTIVE` moves it `IMPLEMENTED → VERIFIED_INEFFECTIVE`; either way `effectiveness_reviewed_at` is stamped. An ineffective verdict is not a dead end — reopening moves `VERIFIED_INEFFECTIVE → PROPOSED`, returning the action to the front of the loop for a redesigned attempt. Improvement actions are listable per program (with a `status` filter) and globally with `program_id`, `audit_finding_id`, `report_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, modify, or transition an existing resource — including all lifecycle actions, the milestone-evaluation batch, and the clock-setting capability — return `200 OK`. The table below is a navigational summary only: request payloads, response bodies, preconditions, and side effects are defined by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramDirector |
| POST | `/programs` | Create a program | ProgramDirector |
| GET | `/programs` | List programs | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| GET | `/programs/{id}` | Get one program | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| POST | `/programs/{id}/activate` | Activate a program | ProgramDirector |
| POST | `/programs/{id}/suspend` | Suspend a program | ProgramDirector |
| POST | `/programs/{id}/resume` | Resume a suspended program | ProgramDirector |
| POST | `/programs/{id}/archive` | Archive a program whose cycles are all archived | ProgramDirector |
| POST | `/programs/{id}/consent-form-bump` | Advance the program's consent form version | PrivacyOfficer |
| POST | `/funders` | Create a funder | ProgramDirector |
| GET | `/funders` | List funders | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer |
| GET | `/funders/{id}` | Get one funder | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer |
| POST | `/funders/{id}/deactivate` | Deactivate a funder | ProgramDirector |
| POST | `/funders/{id}/reactivate` | Reactivate a funder | ProgramDirector |
| POST | `/programs/{id}/logic-models` | Create a draft logic model | EvaluationLead |
| GET | `/programs/{id}/logic-models` | List logic models of a program | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer |
| GET | `/logic-models/{id}` | Get one logic model | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer |
| POST | `/logic-models/{id}/submit` | Submit a draft model for approval | EvaluationLead |
| POST | `/logic-models/{id}/approve` | Approve a submitted model under OCC on the program | EvaluationLead |
| POST | `/logic-models/{id}/reject` | Reject a submitted model | EvaluationLead |
| POST | `/logic-models/{id}/revise` | Return a rejected model to draft | EvaluationLead |
| GET | `/logic-models/{id}/indicators` | List indicators of a logic model | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| POST | `/logic-models/{id}/indicators` | Create an indicator under a draft model | EvaluationLead |
| GET | `/indicators/{id}` | Get one indicator | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| PATCH | `/indicators/{id}` | Update an indicator while its model is draft | EvaluationLead |
| POST | `/indicators/{id}/retire` | Retire an active indicator | EvaluationLead |
| GET | `/indicators/{id}/attainment` | Computed attainment read for an indicator within a cycle | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| POST | `/programs/{id}/cycles` | Create a program cycle | ProgramDirector |
| GET | `/programs/{id}/cycles` | List cycles of a program | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| GET | `/cycles` | List cycles across programs | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| GET | `/cycles/{id}` | Get one cycle | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector, VendorAnalyst |
| POST | `/cycles/{id}/open-enrollment` | Open enrollment on a cycle | ProgramDirector |
| POST | `/cycles/{id}/revert-setup` | Revert a cycle to setup | ProgramDirector |
| POST | `/cycles/{id}/activate` | Activate a cycle and pin its logic model and consent form snapshot | ProgramDirector |
| POST | `/cycles/{id}/close-data` | Close data collection on a cycle | ProgramDirector |
| POST | `/cycles/{id}/reopen-data` | Reopen data collection on a cycle | ProgramDirector |
| POST | `/cycles/{id}/begin-review` | Begin review on a data-closed cycle | ProgramDirector |
| POST | `/cycles/{id}/mark-reported` | Mark a cycle reported | ProgramDirector |
| POST | `/cycles/{id}/archive` | Archive a reported cycle | ProgramDirector |
| POST | `/cycles/{id}/evaluate-milestones` | Evaluate due pending milestones of a cycle | ProgramDirector |
| GET | `/cycles/{id}/participants` | List participants of a cycle | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| GET | `/cycles/{id}/observations` | List observations of a cycle | ProgramDirector, EvaluationLead, DataSteward, FieldCollector, VendorAnalyst |
| GET | `/cycles/{id}/milestones` | List milestones of a cycle | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| GET | `/cycles/{id}/audits` | List audits of a cycle | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/cycles/{id}/reports` | List reports of a cycle | ProgramDirector, EvaluationLead, DataSteward, FunderViewer |
| GET | `/cycles/{id}/dashboard` | Computed cycle dashboard read | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/cycles/{id}/participants` | Enroll a participant in a cycle | ProgramDirector |
| GET | `/participants/{id}` | Get one participant | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer, FieldCollector |
| POST | `/participants/{id}/exit` | Exit an active participant | ProgramDirector |
| POST | `/participants/{id}/re-enroll` | Re-enroll an exited participant | ProgramDirector |
| GET | `/participants/{id}/consents` | List consent records of a participant | ProgramDirector, EvaluationLead, DataSteward, PrivacyOfficer |
| GET | `/participants/{id}/observations` | List observations of a participant | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| GET | `/participants/{id}/findings` | List findings about a participant | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/participants/{id}/consents` | Grant consent to a participant | PrivacyOfficer |
| POST | `/consents/{id}/revoke` | Revoke a granted consent | PrivacyOfficer |
| POST | `/programs/{id}/instruments` | Create a draft instrument | EvaluationLead |
| GET | `/programs/{id}/instruments` | List instruments of a program | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| GET | `/instruments/{id}` | Get one instrument | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| POST | `/instruments/{id}/publish` | Publish a draft instrument | EvaluationLead |
| POST | `/instruments/{id}/new-revision` | Create a successor draft revision of an instrument | EvaluationLead |
| POST | `/instruments/{id}/retire` | Retire a published instrument | EvaluationLead |
| GET | `/instruments/{id}/observations` | List observations recorded with an instrument | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| POST | `/certifications` | Certify a collector on an instrument | EvaluationLead |
| GET | `/certifications` | List certifications | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/certifications/{id}` | Get one certification | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/certifications/{id}/suspend` | Suspend a certification | EvaluationLead |
| POST | `/certifications/{id}/reinstate` | Reinstate a suspended certification | EvaluationLead |
| POST | `/participants/{id}/observations` | Record an observation for a participant | FieldCollector |
| GET | `/observations/{id}` | Get one observation | ProgramDirector, EvaluationLead, DataSteward, FieldCollector, VendorAnalyst |
| GET | `/observations` | List observations | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| POST | `/observations/{id}/validate` | Validate a pending or flagged observation | DataSteward |
| POST | `/observations/{id}/flag` | Flag a pending observation | DataSteward |
| POST | `/observations/{id}/exclude` | Exclude an observation | DataSteward |
| POST | `/cycles/{id}/milestones` | Define a milestone on a cycle | EvaluationLead |
| GET | `/milestones/{id}` | Get one milestone | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| GET | `/indicators/{id}/milestones` | List milestones referencing an indicator | ProgramDirector, EvaluationLead, DataSteward, FieldCollector |
| POST | `/cycles/{id}/audits` | Open a data-quality audit on a cycle | DataSteward |
| GET | `/audits/{id}` | Get one audit | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/audits/{id}/close` | Close an audit with no open findings | DataSteward |
| GET | `/audits/{id}/findings` | List findings of an audit | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/audits/{id}/findings` | Record a finding under an open audit | DataSteward |
| GET | `/findings/{id}` | Get one finding | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/findings` | List findings | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/findings/{id}/waive` | Waive an open finding | DataSteward |
| POST | `/findings/{id}/remediate` | Remediate an open finding | DataSteward |
| POST | `/cycles/{id}/reports` | Create a report under OCC on the cycle | EvaluationLead |
| GET | `/reports/{id}` | Get one report | ProgramDirector, EvaluationLead, DataSteward, FunderViewer |
| GET | `/reports` | List reports | ProgramDirector, EvaluationLead, DataSteward, FunderViewer |
| POST | `/reports/{id}/generate` | Generate a draft report, pinning snapshots | EvaluationLead |
| POST | `/reports/{id}/deliver` | Deliver a generated report | EvaluationLead |
| POST | `/reports/{id}/accept` | Accept a delivered report | FunderViewer |
| POST | `/reports/{id}/return` | Return a delivered report for rework | FunderViewer |
| POST | `/reports/{id}/regenerate` | Regenerate a returned report | EvaluationLead |
| POST | `/programs/{id}/vendor-engagements` | Propose a vendor engagement | ProgramDirector |
| GET | `/programs/{id}/vendor-engagements` | List engagements of a program | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/vendor-engagements/{id}` | Get one engagement | ProgramDirector, EvaluationLead, DataSteward, VendorAnalyst |
| POST | `/vendor-engagements/{id}/activate` | Activate a proposed engagement | ProgramDirector |
| POST | `/vendor-engagements/{id}/complete` | Complete an active engagement | ProgramDirector |
| POST | `/vendor-engagements/{id}/terminate` | Terminate an engagement | ProgramDirector |
| POST | `/vendor-engagements/{id}/submit-deliverable` | Submit the vendor deliverable | VendorAnalyst |
| POST | `/programs/{id}/improvement-actions` | Propose an improvement action | EvaluationLead |
| GET | `/programs/{id}/improvement-actions` | List improvement actions of a program | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/improvement-actions/{id}` | Get one improvement action | ProgramDirector, EvaluationLead, DataSteward |
| GET | `/improvement-actions` | List improvement actions | ProgramDirector, EvaluationLead, DataSteward |
| POST | `/improvement-actions/{id}/approve` | Approve a proposed improvement action | ProgramDirector |
| POST | `/improvement-actions/{id}/start` | Start an approved improvement action | EvaluationLead |
| POST | `/improvement-actions/{id}/implement` | Mark an in-progress action implemented | EvaluationLead |
| POST | `/improvement-actions/{id}/verify` | Verify an implemented action's effectiveness | ProgramDirector |
| POST | `/improvement-actions/{id}/reopen` | Reopen an ineffective action | EvaluationLead |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status code. The conditions under which each error is raised are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADERS` | 401 |
| `ERR_UNKNOWN_ROLE` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SCOPE_DENIED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONSENT_NOT_CURRENT` | 422 |
| `ERR_STALE_CONSENT_FORM` | 422 |
| `ERR_INSTRUMENT_NOT_PUBLISHED` | 422 |
| `ERR_INDICATOR_NOT_IN_MODEL` | 422 |
| `ERR_CERTIFICATION_MISSING` | 422 |
| `ERR_CERTIFICATION_STALE` | 422 |
| `ERR_CERTIFICATION_EXPIRED` | 422 |
| `ERR_ENROLLMENT_WINDOW_CLOSED` | 422 |
| `ERR_CYCLE_WINDOW_OVERLAP` | 409 |
| `ERR_ENGAGEMENT_WINDOW_OVERLAP` | 409 |
| `ERR_DUPLICATE_CODE` | 409 |
| `ERR_AUDIT_ALREADY_OPEN` | 409 |
| `ERR_SEGREGATION_OF_DUTY` | 422 |
| `ERR_DQ_GATE_NOT_MET` | 422 |
| `ERR_FUNDER_INACTIVE` | 422 |
| `ERR_STALE_CYCLE_VERSION` | 412 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |

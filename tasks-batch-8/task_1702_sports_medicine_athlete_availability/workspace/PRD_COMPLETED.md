# Sports Medicine & Athlete Availability API — Product Requirements Document

## 1. Introduction

Professional and collegiate sports organizations operate under a dual mandate: maximize athlete availability for competition while minimizing the medical and legal risks of premature return to play. Athletic trainers, team physicians, performance staff, and billing coordinators each handle a fragment of this workflow — injury intake, treatment planning, return-to-play progression, workload monitoring, insurance submission, and compliance reporting — yet no shared system currently reconciles these fragments into a single auditable record. The consequences are tangible: a coach sees a designation without knowing whether a concussion protocol is active, a billing clerk submits a claim against a stale policy accumulator, or a physician signs clearance while relying on a three-day-old evaluation.

This document specifies a Sports Medicine & Athlete Availability Tracking API designed to eliminate those gaps. The system models the full clinical-to-competitive arc: injury intake with immutable diagnosis snapshots, daily participation designations that feed an automatic availability tier, a staged return-to-participation (RTP) protocol with deterministic readiness gates and regression handling, workload ingestion with acute-to-chronic workload ratio (ACWR) load flags, insurance claim adjudication with deductible and out-of-pocket tracking, and confidentiality-grant-mediated availability reporting for coaching and front-office audiences.

The API is authoritative for clinical state and enforces segregation of duties: the staff member who requests a clearance may not decide it, and the evaluator who recorded the latest status entry may not clear the athlete. Optimistic concurrency controls protect multi-step medical and financial workflows from silent overwrites, and a logical clock decouples temporal rules (policy years, clearance expiry, regression lookbacks) from wall-clock time for reproducible testing and audit.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or if `X-User-Role` does not match one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). If the role is valid but not permitted for the requested endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The declared roles, with exact spelling, are:

- `TeamAdmin` — team operations administrator; owns team creation, diagnosis-code registration, athlete roster actions, and the logical clock.
- `MedicalStaff` — athletic trainers; owns injury intake, treatment plans, daily status entries, RTP protocols, clearance requests, and disclosure grants.
- `TeamPhysician` — team physician; sole authority for clearance decisions, segregated from the requester and from the recording evaluator.
- `PerformanceStaff` — performance and load-management staff; owns workload session ingestion.
- `BillingStaff` — insurance and billing staff; owns policies and the claims lifecycle.
- `CoachingStaff` — coaching staff; consumes redacted availability reporting only.

All six roles use an **opaque** identity model: `X-User-ID` is not tied to any persisted entity. The server may record it on audit fields (for example, as `reported_by_user_id` on an `InjuryCase` or `decided_by_user_id` on a `ClearanceAuthorization`), but it never compares `X-User-ID` to an entity's `id` for ownership checks.

Role-based field masking applies to the `Athlete` resource: `CoachingStaff` sees only `id`, `team_id`, `full_name`, `position`, `roster_status`, `availability_tier`, `created_at`, `updated_at`, and `version`; `acute_chronic_workload_ratio` and `load_flag` are masked from this audience.

The logical clock is advanced by the administrative endpoint with a `to_iso8601` parameter; the supplied timestamp is written verbatim to every team's `current_utc`. Any parseable ISO 8601 timestamp is accepted — the clock may be set to an earlier or later value — and the endpoint returns HTTP 200 with a data object containing the echoed `current_utc`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to `10`, must be at least `1`, and may not exceed `100`. `offset` defaults to `0` and must not be negative. A non-integer `limit` or `offset`, or a value outside these bounds, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Results are sorted by `created_at` ascending. The response `meta` block includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every entity carries an `id` as a server-minted UUID with no type prefix. All entities except `DiagnosisCode`, `DailyStatusEntry`, `RTPStageAdvance`, `WorkloadSession`, and `AvailabilityReport` also carry `created_at` and `updated_at` as ISO 8601 UTC timestamps with three fractional digits, plus a `version` integer that increments by `1` on every mutation. The five exception entities are immutable or append-only: `DiagnosisCode` carries only `id` and `created_at`; `DailyStatusEntry`, `RTPStageAdvance`, `WorkloadSession`, and `AvailabilityReport` likewise carry only `id` and `created_at`, and none of these five expose `updated_at` or `version`. Date-valued request fields accept either a `YYYY-MM-DD` calendar date or a full ISO 8601 timestamp; the supplied string is stored and echoed verbatim, while all date comparisons use the calendar-date portion.

The system maintains a logical clock, `current_utc`, initialized to exactly `2026-08-01T00:00:00Z`; every team's `current_utc` echoes the current clock value, so a team created after the clock has been set inherits the then-current value. The clock never falls back to wall-clock time; it advances only through the administrative clock endpoint. All date comparisons — policy years, grant windows, clearance freshness, future-date rejection, regression lookbacks — are evaluated against this logical clock.

### 2.5. Validation Priority and Error Precedence

Incoming requests are evaluated against a fixed priority ladder. Authentication context (header presence and role validity) is checked first. Authorization against the RBAC matrix follows. Existence of path resources and body foreign-key references is evaluated next. Where an optimistic-concurrency rule applies, the expected-version check is performed immediately after existence and before any business rule. Generic from-state legality is evaluated next, followed by segregation-of-duties checks, evaluation freshness, the RTP readiness gate, clearance re-request freshness, aggregate preconditions, the appeal budget, field-level constraints, claim integrity, temporal window checks, supersede-target validity, future-date rejection, policy activity, and finally uniqueness constraints. A higher-priority failure masks all lower-priority failures for the same request. Field-level constraint failures — missing or malformed required fields, invalid enum values, and out-of-range numbers — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.6. Optimistic Concurrency Control

Three write endpoints require an explicit expected-version field to guard against stale-view overwrites. A request to create a clearance request on an RTP protocol must carry `expected_protocol_version` matching the protocol's current `version`. A request to append a stage advance to an RTP protocol must carry `expected_protocol_version` matching the protocol's current `version`. A request to submit a claim must carry `expected_policy_version` matching the referenced insurance policy's current `version`. A missing or non-integer expected-version field is rejected with `ERR_INVALID_REQUEST` (HTTP 400); an integer value that does not match the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not consult a version field; unknown or unexpected request body fields are ignored rather than rejected across the API.

### 2.7. Precision, Rounding, and Monetary Representation

All monetary amounts are represented as integer cents. The claim adjudication calculation applies rounding at exactly one step: the patient-coinsurance step rounds half-up to zero decimal places. The acute-to-chronic workload ratio is computed to three decimal places with round-half-up, and the load-flag threshold comparison uses that three-decimal rounded value. The injury-rate trend metric is rounded half-up to two decimal places. Whole-day arithmetic is used for all date differences.

### 2.8. Team Scoping and Cross-Reference Integrity

Every resource that references an `athlete_id`, `injury_case_id`, `insurance_policy_id`, or other team-scoped foreign key must resolve within the same team scope as the path or parent resource. A body foreign-key reference that is missing, or that points to an entity belonging to a different team, is rejected with `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a missing path resource.

## 3. Business Logic & Workflows

### 3.1. Team Configuration and Roster Administration

A `TeamAdmin` establishes the organization by creating a team with a `name`, a `sport` drawn from `FOOTBALL`, `BASKETBALL`, `SOCCER`, `HOCKEY`, or `BASEBALL`, and a season window defined by `season_start_date` and `season_end_date`. The season end date must be strictly later than the season start date. Two optional configuration knobs govern downstream behavior: `hipaa_mode`, defaulting to `STRICT`, which suppresses designation, body-region, and diagnosis detail for non-medical audiences regardless of grant scope; and `acwr_variant`, defaulting to `ROLLING`, which selects the authoritative ACWR calculation for that team.

Athletes are enrolled into a team with `team_id`, `full_name`, `position` (a free-form string), and `enrollment_date`; `enrollment_date` is not validated against the season window or the logical clock. At enrollment the athlete's `roster_status` is `ACTIVE`, `availability_tier` is `FULL`, `load_flag` is `NONE`, and `acute_chronic_workload_ratio` is `null`. A `TeamAdmin` may deactivate an `ACTIVE` athlete, transitioning `roster_status` to `INACTIVE`, or reactivate an `INACTIVE` athlete (any other `roster_status` is rejected with `ERR_ATHLETE_NOT_INACTIVE`), which transitions `roster_status` back to `ACTIVE` and triggers a recomputation of `availability_tier`. Releasing an athlete requires that the athlete be `ACTIVE` and that no `InjuryCase` for the athlete remains in `OPEN`, `REHAB`, `RTP`, or `LONG_TERM`; if either condition fails the request is rejected with `ERR_ATHLETE_NOT_ACTIVE` or `ERR_OPEN_CASES_EXIST` respectively. On release, all `ACTIVE` disclosure grants for the athlete are revoked, and the athlete's `version` increments.

### 3.2. Injury Intake and the Daily Status Log

`MedicalStaff` open an injury case by supplying `athlete_id`, `diagnosis_code_id`, `occurred_on`, `surface`, and `mechanism`. The occurrence date must not be later than the current logical date; a future date is rejected with `ERR_FUTURE_DATE_NOT_ALLOWED`. The referenced diagnosis code contributes two immutable snapshots at intake: `severity_class_snapshot` and `is_concussion_snapshot`, copied from the code's `severity_class` and `is_concussion` fields so that later edits to the diagnosis code do not retroactively alter the case. The case's `status` begins at `OPEN`, `reported_by_user_id` records the acting `X-User-ID`, and `team_id` is denormalized from the athlete. Opening a case forces the athlete's `availability_tier` to at least `LIMITED` — an `OPEN` case can never report `FULL` — and increments the athlete's `version`. Intake imposes no roster-status precondition; a case may be opened for an athlete in any `roster_status`.

The diagnosis code registry is seeded by `TeamAdmin` with a unique `code` (a duplicate `code` is rejected with `ERR_INVALID_REQUEST`), a `body_region` drawn from `HEAD_NECK`, `SHOULDER`, `ARM`, `HAND`, `TRUNK`, `HIP`, `KNEE`, `LOWER_LEG`, `ANKLE_FOOT`, or `SYSTEMIC`, a `severity_class` of `MINOR`, `MODERATE`, or `SEVERE`, and an `is_concussion` flag. Injury `surface` is one of `GRASS`, `TURF`, `COURT`, `ICE`, or `TRAINING_ROOM`; `mechanism` is one of `CONTACT`, `NON_CONTACT`, `OVERUSE`, or `UNKNOWN`.

Daily participation designations are recorded as immutable `DailyStatusEntry` events. Each entry carries `injury_case_id`, `entry_date`, `designation` (one of `OUT`, `LIMITED`, `MODIFIED`, `FULL`), `symptom_free`, `functional_test_score` (0–100), optional `notes`, and `recorded_by_user_id`. An entry may reference a prior entry via `supersedes_entry_id` to correct the record for the same case and date; the supersede target must be an `is_current` entry for the same `(injury_case_id, entry_date)`, otherwise the request is rejected with `ERR_INVALID_SUPERSEDE_TARGET`. When a superseding entry is created, the new entry's `is_current` becomes `true` and the old entry's `is_current` becomes `false`. More generally, recording any entry flips every prior entry for the same `(injury_case_id, entry_date)` to `is_current` false — whether or not `supersedes_entry_id` was supplied — so exactly one current entry exists per case and date. Only `is_current` entries feed derivations. Recording a daily entry triggers recomputation of the athlete's `availability_tier` and increments the athlete's `version`. For concussion cases, if the new latest `is_current` entry has `symptom_free` set to `false` while the RTP protocol is `IN_PROGRESS`, the protocol automatically transitions to `SUSPENDED_CONCUSSION`; conversely, if the protocol is `SUSPENDED_CONCUSSION` and the new latest entry has `symptom_free` set to `true`, the protocol returns to `IN_PROGRESS`.

### 3.3. Treatment Planning and Rehabilitation Milestones

A treatment plan is created against an injury case with `injury_case_id`, `title`, `planned_sessions_per_week` (1–14), and `estimated_duration_weeks` (1–52). The plan's `status` begins at `DRAFT`, and `athlete_id` is denormalized from the case. A `DRAFT` plan may be activated only when the parent case is in `OPEN`, `REHAB`, `LONG_TERM`, or `RTP`; activation against a case in any other state is rejected with `ERR_INVALID_STATE`. An `ACTIVE` plan may be suspended, which records the request body `reason` (a required non-empty string, otherwise `ERR_INVALID_REQUEST`) into `suspension_reason`, and a `SUSPENDED` plan may be resumed, which clears `suspension_reason`. Completion is allowed from either `ACTIVE` or `SUSPENDED`; any other state is rejected with `ERR_PLAN_NOT_COMPLETABLE`. The specific state mismatches map to `ERR_PLAN_NOT_DRAFT`, `ERR_PLAN_NOT_ACTIVE`, and `ERR_PLAN_NOT_SUSPENDED` respectively.

Starting rehabilitation transitions the case from `OPEN` to `REHAB`. The transition requires the case to be `OPEN` (otherwise `ERR_CASE_NOT_OPEN`) and at least one `is_current` daily status entry to exist for the case (otherwise `ERR_NO_STATUS_ENTRY`). The case may instead be marked `LONG_TERM` via `mark-long-term` only from `REHAB` (otherwise `ERR_CASE_NOT_IN_REHAB`) and only when the latest `is_current` designation is `OUT`; any other designation — or the absence of any current entry — is rejected with `ERR_DESIGNATION_NOT_OUT`. A `LONG_TERM` case may be resumed back to `REHAB` via `resume-rehab`; if the case is not `LONG_TERM` the request is rejected with `ERR_CASE_NOT_LONG_TERM`. Every transition among `OPEN`, `REHAB`, and `LONG_TERM` recomputes `availability_tier` and increments the athlete's `version`.

### 3.4. Return-to-Participation Protocol and Stage Gates

Creating an RTP protocol is the mechanism that advances a case from `REHAB` to `RTP`. The request carries `injury_case_id` and `total_stages` (3–7). The case must be in `REHAB` (otherwise `ERR_CASE_NOT_IN_REHAB`), no protocol may already exist for the case (otherwise `ERR_RTP_ALREADY_EXISTS`), and at least one `ACTIVE` treatment plan must exist for the case (otherwise `ERR_NO_ACTIVE_TREATMENT_PLAN`). On creation the protocol's `status` is `NOT_STARTED`, `current_stage_index` is `0`, and `current_stage_entered_on` is set to the current logical date.

Advancing a stage is a `MedicalStaff` action that requires `expected_protocol_version` in the request body. The protocol must be in `NOT_STARTED`, `IN_PROGRESS`, or `REGRESSED`; attempts from `SUSPENDED_CONCUSSION`, `AWAITING_CLEARANCE`, or `CLEARED` are rejected with `ERR_PROTOCOL_NOT_ADVANCEABLE`. Before any mutation, the readiness gate is evaluated. Days in stage is the whole-day difference between the current logical date and `current_stage_entered_on`. The minimum days required for the stage is the base of `2` days, plus `2` additional days if the case's `severity_class_snapshot` is `SEVERE`, plus `1` additional day if the case's `is_concussion_snapshot` is true. A regression is in window if any `RTPStageAdvance` with `kind` equal to `REGRESSION` has a `created_at` date in the inclusive window from `14` days before the current logical date through the current logical date itself. The latest entry is the `is_current` daily status entry with the maximum `entry_date` for the case. The gate passes only when days in stage is at least the minimum, the latest entry exists and has `symptom_free` true, the latest entry's `functional_test_score` is at least `80`, no regression is in window, and the latest entry's `entry_date` is not earlier than `current_stage_entered_on`. For concussion cases there is an independent hard floor: days in stage must be at least `3`, and this check is evaluated first; a breach yields `ERR_CONCUSSION_MIN_DAYS`, while any other failed conjunct yields `ERR_READINESS_NOT_MET`.

On a successful advance, `current_stage_index` increments by `1`, `current_stage_entered_on` is set to the current logical date, the protocol's `version` increments, and an `RTPStageAdvance` row is appended with `kind` set to `ADVANCE`, `from_stage_index` and `to_stage_index` recording the transition, `advanced_by_user_id` capturing the acting user, and `readiness_snapshot` containing the gate-time values of `days_in_stage`, `symptom_free`, `functional_test_score`, and `regression_in_window`. If the new `current_stage_index` equals `total_stages - 1`, the protocol transitions to `AWAITING_CLEARANCE` instead of `IN_PROGRESS`. When an advance moves the protocol out of `REGRESSED`, the parent case transitions from `REHAB` back to `RTP`, the athlete's `availability_tier` is recomputed, and the athlete's `version` increments.

Regressing a stage moves the protocol from `IN_PROGRESS` or `AWAITING_CLEARANCE` to `REGRESSED`. The action requires the protocol to be in one of those two states (otherwise `ERR_PROTOCOL_NOT_REGRESSABLE`), `current_stage_index` to be greater than `0` (otherwise `ERR_CANNOT_REGRESS_BELOW_ZERO`), and a string `reason` in the request body (otherwise `ERR_INVALID_REQUEST`); the `reason` is not persisted. On regress, `current_stage_index` decrements by `1`, `current_stage_entered_on` is set to the current logical date, `regression_count` increments by `1`, the protocol's `version` increments, and an `RTPStageAdvance` row is appended with `kind` set to `REGRESSION` and `readiness_snapshot` set to `null`. The parent injury case automatically transitions from `RTP` back to `REHAB`, any `PENDING` clearance authorization on the protocol transitions to `EXPIRED`, the athlete's `availability_tier` is recomputed, and the athlete's `version` increments.

### 3.5. Clearance Authorization and Segregation of Duties

When a protocol reaches `AWAITING_CLEARANCE`, a `MedicalStaff` member may request a clearance authorization by supplying `expected_protocol_version` and optional `request_notes`. At most one `PENDING` clearance may exist per protocol; a duplicate is rejected with `ERR_CLEARANCE_ALREADY_PENDING`. The protocol must be `AWAITING_CLEARANCE` (otherwise `ERR_PROTOCOL_NOT_AWAITING_CLEARANCE`). The request creates a `ClearanceAuthorization` with `status` set to `PENDING`, `requested_by_user_id` recording the requester, `requested_at` set to the current logical timestamp, `rtp_protocol_id` bound from the path, and `injury_case_id` and `athlete_id` denormalized from the protocol. Creating the request increments the protocol's `version`.

If a prior clearance was `RETURNED_FOR_REVIEW`, a re-request may be submitted. The re-request path requires a daily status entry with `entry_date` equal to the current logical date and `is_current` true; absence of such an entry is rejected with `ERR_NO_FRESH_STATUS_ENTRY`. When the replacement request is created, the prior `RETURNED_FOR_REVIEW` row transitions to `EXPIRED`.

Decision authority rests exclusively with `TeamPhysician`. The decision action accepts `decision` — one of `GRANTED` or `RETURNED_FOR_REVIEW`; any other value is rejected with `ERR_INVALID_REQUEST` — and optional `decision_notes`. The clearance must be `PENDING` (otherwise `ERR_CLEARANCE_NOT_PENDING`). Segregation of duties is enforced: the decider's `X-User-ID` must differ from the requester's `requested_by_user_id` (otherwise `ERR_SOD_SELF_CLEARANCE`, HTTP 403), and the decider must differ from the recorder of the latest `is_current` daily status entry on the case (otherwise `ERR_SOD_EVALUATOR_CLEARANCE`, HTTP 403).

A `GRANTED` decision additionally requires the protocol to be `AWAITING_CLEARANCE` (otherwise `ERR_PROTOCOL_NOT_AWAITING_CLEARANCE`) and evaluation freshness: the difference between the current logical timestamp and the `created_at` of the latest `is_current` daily status entry must not exceed `72` hours; a stale evaluation — including the case where no `is_current` entry exists — is rejected with `ERR_STALE_EVALUATION`. On grant, `decision` is set to `GRANTED`, `decided_by_user_id` and `decided_at` are recorded, and `expires_at` is set to `decided_at` plus `72` hours. The protocol transitions from `AWAITING_CLEARANCE` to `CLEARED`, the injury case transitions from `RTP` to `CLEARED` with `cleared_on` set to the current logical date, the athlete's `availability_tier` is recomputed, and the athlete's `version` increments. A `RETURNED_FOR_REVIEW` decision sets `decision`, `decided_by_user_id`, and `decided_at` but leaves the protocol state unchanged.

Closing a case requires it to be `CLEARED` (otherwise `ERR_CASE_NOT_CLEARED`), with no treatment plan in `ACTIVE` or `SUSPENDED` (otherwise `ERR_PLAN_STILL_ACTIVE`) and no claim in `DRAFT`, `SUBMITTED`, or `APPEALED` (otherwise `ERR_CLAIMS_OPEN`). On close, `closed_on` is set to the current logical date, `days_lost` is computed as the whole-day difference between `closed_on` and `occurred_on`, the athlete's `availability_tier` is recomputed, and the athlete's `version` increments.

### 3.6. Workload Ingestion, ACWR, and Load Flags

`PerformanceStaff` ingest workload sessions by supplying `athlete_id`, `session_date`, `session_type`, `surface`, `duration_minutes` (0–600), and `rpe` (0–10). The session date must not be later than the current logical date (otherwise `ERR_FUTURE_DATE_NOT_ALLOWED`). Ingestion imposes no roster-status precondition on the athlete. The session's `session_load` is computed as `duration_minutes` multiplied by `rpe`. A session counts as exposure when `session_type` is `PRACTICE`, `GAME`, or `CONDITIONING` and `duration_minutes` is at least `10`; `REHAB_SESSION` is excluded from exposure denominators and ACWR windows. For ACWR windows and the 8-session minimum, a qualifying session is any ingested session whose `session_type` is not `REHAB_SESSION`; the 10-minute `duration_minutes` floor applies only to `counts_as_exposure`, not to ACWR. On ingest, `team_id` is denormalized from the athlete, `ingested_by_user_id` is recorded, the athlete's `acute_chronic_workload_ratio` and `load_flag` are recomputed, the availability-tier load overlay is applied, and the athlete's `version` increments.

The authoritative ACWR variant is selected by the team's `acwr_variant`. For `ROLLING`, the acute load is the sum of `session_load` for qualifying sessions with `session_date` in the inclusive window from `today - 6` to `today`, where `today` is the current logical date. The chronic load is the sum of `session_load` for qualifying sessions in the inclusive window from `today - 27` to `today`, divided by `4`. The ratio is the acute load divided by the chronic load, rounded half-up to three decimal places; if the chronic load is zero the ratio is `null`. The ratio is also `null` when fewer than `8` qualifying sessions exist in the chronic window. For `EWMA`, the daily load is the sum of `session_load` for qualifying sessions on each date. The acute value is the exponentially weighted sum over the `7`-day window with lambda `0.2` (decay factor `0.8` raised to the power of days before today), divided by the sum of the weights. The chronic value is the same weighted sum over the `28`-day window, divided by the sum of the weights. Missing days contribute zero load. The ratio and null rules are identical to `ROLLING`.

The load flag is derived from the three-decimal rounded ratio. If the ratio is `null`, `load_flag` is `NONE`. If the ratio is at least `1.500`, `load_flag` is `SPIKE`. If the ratio is at least `1.300` but less than `1.500`, `load_flag` is `ELEVATED`. Otherwise `load_flag` is `NONE`. The boundary is inclusive at both thresholds: a rounded ratio of exactly `1.500` yields `SPIKE`, while `1.499` yields `ELEVATED`.

### 3.7. Availability Tier Derivation and Load Overlay

The athlete's `availability_tier` is recomputed eagerly on every triggering mutation: injury-case status changes, daily-status creation or supersede, clearance grant, RTP regression, athlete reactivation, or workload ingest. The derivation considers only the athlete's injury cases with `status` in `OPEN`, `REHAB`, `RTP`, or `LONG_TERM`; `CLEARED` and `CLOSED` cases are excluded. For each candidate case, the effective designation is the `designation` of the `is_current` daily status entry whose `entry_date` equals the current logical date; if none exists for today, the designation of the `is_current` entry with the maximum `entry_date`; if no entries exist at all, the default is `OUT`.

Three case-state overrides apply. An `OPEN` case forces the contribution to at least `LIMITED` — never `FULL`. A `LONG_TERM` case forces `OUT` regardless of designation. An `RTP` case whose protocol is `AWAITING_CLEARANCE` forces the contribution to at most `LIMITED`. The athlete's tier is the most restrictive contribution across all candidate cases, with severity order `OUT` more restrictive than `LIMITED`, which is more restrictive than `MODIFIED`, which is more restrictive than `FULL`. If no candidate cases exist, the tier is `FULL`.

A load overlay is applied last: if the athlete's `load_flag` is `SPIKE` and the derived tier is `FULL`, the tier is downgraded to `MODIFIED`. `SPIKE` never modifies `LIMITED` or `OUT`.

### 3.8. Insurance Policy and Claims Lifecycle

`BillingStaff` create insurance policies for an athlete with `athlete_id`, `payer_name`, `policy_number`, `deductible_cents` (non-negative), `coinsurance_pct` (0–100), `oop_max_cents` (non-negative), `policy_year_start`, and `policy_year_end`. The policy year end must be strictly later than the start, and `oop_max_cents` must be at least `deductible_cents`. The pair `(athlete_id, policy_number)` must be unique among non-`CANCELLED` policies; a duplicate is rejected with `ERR_DUPLICATE_POLICY_NUMBER`. At creation the policy's `status` is `ACTIVE`, `deductible_met_cents` is `0`, and `oop_accrued_cents` is `0`.

A policy may be cancelled only when it is `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`) and no claim referencing it is in `SUBMITTED` or `APPEALED` (otherwise `ERR_POLICY_CLAIMS_IN_FLIGHT`). Cancellation transitions the policy to `CANCELLED` and increments its `version`.

Claims are created in `DRAFT` against an injury case and a policy, carrying `billed_amount_cents` (greater than `0`), `line_items` (an array of 1–50 objects each with a non-empty string `cpt_code`, a positive integer `charge_cents`, and a valid `service_date`), and optionally `supersedes_claim_id` referencing a `VOID` claim of the same injury case; an invalid supersede target is rejected with `ERR_INVALID_SUPERSEDE_TARGET`. The policy must belong to the same athlete as the case; a policy of a different athlete is rejected with `ERR_NOT_FOUND` (HTTP 404), indistinguishable from a missing policy. The claim's `athlete_id` is denormalized from the case.

Submitting a claim requires it to be `DRAFT` (otherwise `ERR_CLAIM_NOT_DRAFT`), the referenced policy to be `ACTIVE` (otherwise `ERR_POLICY_NOT_ACTIVE`), every `service_date` in `line_items` to lie within the inclusive window from `policy_year_start` to `policy_year_end` (otherwise `ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR`), and the sum of `charge_cents` across `line_items` to equal `billed_amount_cents` (otherwise `ERR_LINE_ITEM_SUM_MISMATCH`). The request must carry `expected_policy_version`; a mismatch is rejected with `ERR_STALE_VERSION`. On submission, `submitted_at` is set to the current logical timestamp and the policy's `version` increments.

Adjudication may be run against a claim in `SUBMITTED` or `APPEALED` (otherwise `ERR_CLAIM_NOT_SUBMITTABLE_STATE`). The calculation proceeds in a pinned order. The allowed amount is the full `billed_amount_cents`. The remaining deductible is the greater of zero or `deductible_cents` minus `deductible_met_cents`. The deductible applied is the smaller of the allowed amount and the remaining deductible. The after-deductible amount is the allowed amount minus the deductible applied. The patient coinsurance is the after-deductible amount multiplied by `100` minus `coinsurance_pct`, divided by `100`, rounded half-up to zero decimal places; this rounding is applied per claim, never per line item. The patient responsibility before the cap is the deductible applied plus the patient coinsurance. The remaining out-of-pocket is the greater of zero or `oop_max_cents` minus `oop_accrued_cents`. The patient responsibility is the smaller of the pre-cap amount and the remaining out-of-pocket. The payer paid is the allowed amount minus the patient responsibility. The credited deductible is the smaller of the deductible applied and the patient responsibility.

`adjudicated_at` is recorded on every adjudication, including denials. On a non-denial adjudication, `payer_paid_cents`, `patient_resp_cents`, and `deductible_applied_cents` are set on the claim, the policy's `deductible_met_cents` increases by the credited deductible amount, `oop_accrued_cents` increases by `patient_resp_cents`, the policy's `version` increments, and if `oop_accrued_cents` reaches or exceeds `oop_max_cents` the policy transitions from `ACTIVE` to `EXHAUSTED`. The claim passes through `ADJUDICATED` and immediately transitions to `PAID`. `deny`, when present, must be a boolean (otherwise `ERR_INVALID_REQUEST`). If the adjudication request carries `deny` set to `true`, the claim instead passes through `ADJUDICATED` and transitions to `DENIED` with `payer_paid_cents`, `patient_resp_cents`, and `deductible_applied_cents` all set to `0`, and policy accumulators are unchanged.

A denied claim may be appealed with a required string `appeal_reason` (missing or non-string is rejected with `ERR_INVALID_REQUEST`; the reason is not persisted), transitioning to `APPEALED` and incrementing `appeals_count`, provided the claim is `DENIED` (otherwise `ERR_CLAIM_NOT_DENIED`) and `appeals_count` is less than `3` (otherwise `ERR_MAX_APPEALS_REACHED`). An appealed claim may be re-adjudicated; the same calculation runs against the current policy accumulators, which may have been advanced by other claims between denial and appeal, so identical billed amounts can split differently. A draft claim may be voided, transitioning to `VOID`; any other state is rejected with `ERR_CLAIM_NOT_VOIDABLE`.

### 3.9. Confidentiality, Disclosure Grants, and Availability Reporting

`MedicalStaff` create disclosure grants to permit non-medical staff to view scoped athlete fields. A grant carries `athlete_id`, `grantee_role` (`COACHING` or `FRONT_OFFICE`), `scope` (`TIER_ONLY`, `GENERAL`, or `FULL`), and a window defined by `effective_from` and `effective_to` (end strictly later than start, compared by calendar date). Each bound denotes an instant — a date-only value denotes 00:00:00Z at the start of that date — and both window membership and lazy expiration compare the current logical timestamp against these instants. At creation the grant's `status` is `ACTIVE`. A grant may be revoked only when `ACTIVE` (otherwise `ERR_GRANT_NOT_ACTIVE`), transitioning to `REVOKED`. Expiration is applied lazily: on any grant evaluation path, if the current logical timestamp is later than `effective_to`, the grant's `status` is treated as `EXPIRED`.

An availability report is generated for a team and an `audience` (`COACHING`, `FRONT_OFFICE`, or `MEDICAL`; any other audience value is rejected with `ERR_AUDIENCE_INVALID`, and a missing `audience` is rejected with `ERR_INVALID_REQUEST`). The report's `report_date` is the current logical date, `generated_by_user_id` records the requester, and `generated_for_role` records the audience. The `rows` array contains one object per athlete of the team — regardless of `roster_status` — with `athlete_id`, `availability_tier`, and optionally `designation`, `body_region`, and `diagnosis_detail`. The optional fields describe the athlete's driving case: the candidate case (per §3.7) contributing the most restrictive tier, ties broken by earliest `created_at`. `designation` is that case's effective designation, and `body_region` and `diagnosis_detail` are the `body_region` and `code` of that case's diagnosis code. When the athlete has no candidate case, visible optional fields are present with `null` values; non-visible fields are omitted from the row entirely. For a `MEDICAL` audience all fields are always visible. For `COACHING` and `FRONT_OFFICE` audiences, visibility is determined by grant selection: among the athlete's grants with `grantee_role` matching the audience, `status` `ACTIVE` after lazy expiration re-evaluation, and the current logical timestamp within the inclusive window from `effective_from` to `effective_to`, the grant with the highest scope rank is selected, where `FULL` outranks `GENERAL`, which outranks `TIER_ONLY`; ties are broken by `created_at` ascending. `GENERAL` scope adds `designation` and `body_region`; `FULL` scope adds `diagnosis_detail`. When the team's `hipaa_mode` is `STRICT` — rather than `STANDARD` — the override is applied last: `diagnosis_detail` is never exposed to non-medical audiences, and `GENERAL` scope is downgraded to `TIER_ONLY`, suppressing `designation` and `body_region`. Report `rows` are sorted by `availability_tier` severity rank (`OUT` first, then `LIMITED`, then `MODIFIED`, then `FULL`), then `position` ascending, then athlete `created_at` ascending.

Re-reading an existing availability report (by id or via the list endpoint) recomputes the entire `rows` array — tiers, driving-case fields, and the redaction filter — against current athlete state, grants, and the logical clock, so a report that was generated under a broad grant may return fewer fields after revocation or expiration.

### 3.10. Injury Trend Analytics

Injury rates are computed per group of `position` crossed with `surface` over a caller-supplied inclusive window from `from_date` to `to_date`; both are required query parameters, and a missing or unparseable value is rejected with `ERR_INVALID_REQUEST`. Exposures are the count of workload sessions with `counts_as_exposure` true, `session_date` within the window, the athlete's `position` matching the group position, the session's `surface` matching the group surface, and `session_date` not earlier than the athlete's `enrollment_date`. Injuries are the count of injury cases with `occurred_on` within the window, the athlete's `position` matching the group position, the case's `surface` matching the group surface, and excluding cases that were `CLOSED` with `closed_on` earlier than `from_date`. The rate is the number of injuries multiplied by `1000`, divided by the number of exposures, rounded half-up to two decimal places. Groups are formed from the cartesian product of positions present on athletes whose `roster_status` is not `RELEASED` and all surface enum values. Groups with zero exposures are omitted from the response entirely. The response data is an object with a single `groups` array; each group carries `position`, `surface`, `exposures`, `injuries`, and `rate_per_1000`, and groups are ordered by `position` ascending, then `surface` in enum declaration order (`GRASS`, `TURF`, `COURT`, `ICE`, `TRAINING_ROOM`).

## 4. Endpoint Definitions

New resource creation returns HTTP 201; modifications and actions return HTTP 200. All endpoints enforce the validation priority ladder described in §2.5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|-------------------|
| POST | `/sports-med/_clock/set_current_utc` | Set the logical clock for all teams | `TeamAdmin` |
| POST | `/sports-med/teams` | Create a team | `TeamAdmin` |
| GET | `/sports-med/teams` | List teams | `TeamAdmin`, `MedicalStaff`, `TeamPhysician`, `PerformanceStaff`, `BillingStaff`, `CoachingStaff` |
| GET | `/sports-med/teams/{teamId}` | Get a team | `TeamAdmin`, `MedicalStaff`, `TeamPhysician`, `PerformanceStaff`, `BillingStaff`, `CoachingStaff` |
| POST | `/sports-med/diagnosis-codes` | Register a diagnosis code | `TeamAdmin` |
| GET | `/sports-med/diagnosis-codes` | List diagnosis codes | `TeamAdmin`, `MedicalStaff`, `TeamPhysician` |
| GET | `/sports-med/diagnosis-codes/{codeId}` | Get a diagnosis code | `TeamAdmin`, `MedicalStaff`, `TeamPhysician` |
| POST | `/sports-med/athletes` | Enroll an athlete | `TeamAdmin` |
| GET | `/sports-med/athletes` | List athletes (filterable by `team_id`, `roster_status`, `position`) | `TeamAdmin`, `MedicalStaff`, `TeamPhysician`, `PerformanceStaff`, `BillingStaff`, `CoachingStaff` |
| GET | `/sports-med/athletes/{athleteId}` | Get an athlete | `TeamAdmin`, `MedicalStaff`, `TeamPhysician`, `PerformanceStaff`, `BillingStaff`, `CoachingStaff` |
| POST | `/sports-med/athletes/{athleteId}/deactivate` | Deactivate an athlete | `TeamAdmin` |
| POST | `/sports-med/athletes/{athleteId}/reactivate` | Reactivate an athlete | `TeamAdmin` |
| POST | `/sports-med/athletes/{athleteId}/release` | Release an athlete | `TeamAdmin` |
| POST | `/sports-med/injury-cases` | Injury intake | `MedicalStaff` |
| GET | `/sports-med/injury-cases` | List injury cases (filterable by `athlete_id`, `team_id`, `diagnosis_code_id`, `status`) | `MedicalStaff`, `TeamPhysician`, `BillingStaff`, `TeamAdmin` |
| GET | `/sports-med/injury-cases/{caseId}` | Get an injury case | `MedicalStaff`, `TeamPhysician`, `BillingStaff`, `TeamAdmin` |
| POST | `/sports-med/injury-cases/{caseId}/start-rehab` | OPEN to REHAB | `MedicalStaff` |
| POST | `/sports-med/injury-cases/{caseId}/mark-long-term` | REHAB to LONG_TERM | `MedicalStaff` |
| POST | `/sports-med/injury-cases/{caseId}/resume-rehab` | LONG_TERM to REHAB | `MedicalStaff` |
| POST | `/sports-med/injury-cases/{caseId}/close` | CLEARED to CLOSED | `MedicalStaff` |
| POST | `/sports-med/treatment-plans` | Create a treatment plan | `MedicalStaff` |
| GET | `/sports-med/treatment-plans` | List treatment plans (filterable by `injury_case_id`, `athlete_id`, `status`) | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/treatment-plans/{planId}` | Get a treatment plan | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| POST | `/sports-med/treatment-plans/{planId}/activate` | DRAFT to ACTIVE | `MedicalStaff` |
| POST | `/sports-med/treatment-plans/{planId}/suspend` | ACTIVE to SUSPENDED | `MedicalStaff` |
| POST | `/sports-med/treatment-plans/{planId}/resume` | SUSPENDED to ACTIVE | `MedicalStaff` |
| POST | `/sports-med/treatment-plans/{planId}/complete` | ACTIVE or SUSPENDED to COMPLETED | `MedicalStaff` |
| POST | `/sports-med/daily-status-entries` | Record a daily designation | `MedicalStaff` |
| GET | `/sports-med/daily-status-entries` | List daily status entries (filterable by `injury_case_id`, `athlete_id`, `entry_date`, `is_current` — only the value `true` selects current entries, any other value selects non-current — and `supersedes_entry_id`) | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/daily-status-entries/{entryId}` | Get a daily status entry | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| POST | `/sports-med/rtp-protocols` | Create RTP protocol; case REHAB to RTP | `MedicalStaff` |
| GET | `/sports-med/rtp-protocols` | List RTP protocols (filterable by `injury_case_id`, `athlete_id`, `status`) | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/rtp-protocols/{protocolId}` | Get an RTP protocol | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| POST | `/sports-med/rtp-protocols/{protocolId}/advances` | Advance one stage (OCC on protocol version) | `MedicalStaff` |
| GET | `/sports-med/rtp-protocols/{protocolId}/advances` | List stage advances of a protocol | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/rtp-stage-advances` | List stage advances across protocols (filterable by `rtp_protocol_id`, `kind`) | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/rtp-stage-advances/{advanceId}` | Get a single stage advance | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| POST | `/sports-med/rtp-protocols/{protocolId}/regress` | Regress one stage; cascades to case and clearances | `MedicalStaff` |
| POST | `/sports-med/rtp-protocols/{protocolId}/clearances` | Request clearance (OCC on protocol version) | `MedicalStaff` |
| GET | `/sports-med/clearances` | List clearances (filterable by `rtp_protocol_id`, `injury_case_id`, `athlete_id`, `status`) | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| GET | `/sports-med/clearances/{clearanceId}` | Get a clearance | `MedicalStaff`, `TeamPhysician`, `TeamAdmin` |
| POST | `/sports-med/clearances/{clearanceId}/decide` | Physician decision on clearance | `TeamPhysician` |
| POST | `/sports-med/workload-sessions` | Ingest a workload session record | `PerformanceStaff` |
| GET | `/sports-med/workload-sessions` | List workload sessions (filterable by `athlete_id`, `team_id`, `session_type`, and inclusive `from_date`/`to_date`; unparseable date filters are ignored) | `PerformanceStaff`, `MedicalStaff`, `TeamAdmin` |
| GET | `/sports-med/workload-sessions/{sessionId}` | Get a workload session | `PerformanceStaff`, `MedicalStaff`, `TeamAdmin` |
| POST | `/sports-med/insurance-policies` | Create an insurance policy | `BillingStaff` |
| GET | `/sports-med/insurance-policies` | List policies (filterable by `athlete_id`, `status`) | `BillingStaff`, `TeamAdmin` |
| GET | `/sports-med/insurance-policies/{policyId}` | Get a policy | `BillingStaff`, `TeamAdmin` |
| POST | `/sports-med/insurance-policies/{policyId}/cancel` | Cancel a policy | `BillingStaff` |
| POST | `/sports-med/claims` | Create a claim (may supersede a VOID claim) | `BillingStaff` |
| GET | `/sports-med/claims` | List claims (filterable by `injury_case_id`, `athlete_id`, `insurance_policy_id`, `status`, `supersedes_claim_id`) | `BillingStaff`, `TeamAdmin` |
| GET | `/sports-med/claims/{claimId}` | Get a claim | `BillingStaff`, `TeamAdmin` |
| POST | `/sports-med/claims/{claimId}/submit` | Submit a claim (OCC on policy version) | `BillingStaff` |
| POST | `/sports-med/claims/{claimId}/adjudicate` | Adjudicate a claim (initial or after appeal) | `BillingStaff` |
| POST | `/sports-med/claims/{claimId}/appeal` | Appeal a denied claim | `BillingStaff` |
| POST | `/sports-med/claims/{claimId}/void` | Void a draft claim | `BillingStaff` |
| POST | `/sports-med/disclosure-grants` | Create a disclosure grant | `MedicalStaff` |
| GET | `/sports-med/disclosure-grants` | List disclosure grants (filterable by `athlete_id`, `status`, `grantee_role`) | `MedicalStaff`, `TeamAdmin` |
| GET | `/sports-med/disclosure-grants/{grantId}` | Get a disclosure grant | `MedicalStaff`, `TeamAdmin` |
| POST | `/sports-med/disclosure-grants/{grantId}/revoke` | Revoke a grant | `MedicalStaff` |
| POST | `/sports-med/availability-reports` | Generate an availability snapshot for an audience | `CoachingStaff`, `MedicalStaff`, `TeamAdmin` |
| GET | `/sports-med/availability-reports` | List availability reports (filterable by `team_id`) | `CoachingStaff`, `MedicalStaff`, `TeamAdmin` |
| GET | `/sports-med/availability-reports/{reportId}` | Get an availability report (redaction re-evaluated at read time) | `CoachingStaff`, `MedicalStaff`, `TeamAdmin` |
| GET | `/sports-med/teams/{teamId}/analytics/injury-rates` | Injury rate per 1000 exposures by position x surface | `MedicalStaff`, `TeamAdmin`, `PerformanceStaff` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|-----------------|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CASE_NOT_OPEN` | 409 |
| `ERR_NO_STATUS_ENTRY` | 409 |
| `ERR_CASE_NOT_IN_REHAB` | 409 |
| `ERR_RTP_ALREADY_EXISTS` | 409 |
| `ERR_NO_ACTIVE_TREATMENT_PLAN` | 409 |
| `ERR_CASE_NOT_CLEARED` | 409 |
| `ERR_PLAN_STILL_ACTIVE` | 409 |
| `ERR_CLAIMS_OPEN` | 409 |
| `ERR_DESIGNATION_NOT_OUT` | 409 |
| `ERR_CASE_NOT_LONG_TERM` | 409 |
| `ERR_PLAN_NOT_DRAFT` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_PLAN_NOT_SUSPENDED` | 409 |
| `ERR_PLAN_NOT_COMPLETABLE` | 409 |
| `ERR_PROTOCOL_NOT_ADVANCEABLE` | 409 |
| `ERR_READINESS_NOT_MET` | 409 |
| `ERR_CONCUSSION_MIN_DAYS` | 409 |
| `ERR_PROTOCOL_NOT_REGRESSABLE` | 409 |
| `ERR_CANNOT_REGRESS_BELOW_ZERO` | 409 |
| `ERR_PROTOCOL_NOT_AWAITING_CLEARANCE` | 409 |
| `ERR_CLEARANCE_NOT_PENDING` | 409 |
| `ERR_CLEARANCE_ALREADY_PENDING` | 409 |
| `ERR_SOD_SELF_CLEARANCE` | 403 |
| `ERR_SOD_EVALUATOR_CLEARANCE` | 403 |
| `ERR_STALE_EVALUATION` | 409 |
| `ERR_NO_FRESH_STATUS_ENTRY` | 409 |
| `ERR_CLAIM_NOT_DRAFT` | 409 |
| `ERR_CLAIM_NOT_SUBMITTABLE_STATE` | 409 |
| `ERR_CLAIM_NOT_DENIED` | 409 |
| `ERR_CLAIM_NOT_VOIDABLE` | 409 |
| `ERR_MAX_APPEALS_REACHED` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_POLICY_CLAIMS_IN_FLIGHT` | 409 |
| `ERR_SERVICE_DATE_OUT_OF_POLICY_YEAR` | 422 |
| `ERR_LINE_ITEM_SUM_MISMATCH` | 422 |
| `ERR_INVALID_SUPERSEDE_TARGET` | 422 |
| `ERR_FUTURE_DATE_NOT_ALLOWED` | 422 |
| `ERR_DUPLICATE_POLICY_NUMBER` | 409 |
| `ERR_ATHLETE_NOT_ACTIVE` | 409 |
| `ERR_ATHLETE_NOT_INACTIVE` | 409 |
| `ERR_OPEN_CASES_EXIST` | 409 |
| `ERR_GRANT_NOT_ACTIVE` | 409 |
| `ERR_AUDIENCE_INVALID` | 400 |

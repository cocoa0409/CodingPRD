# Industrial Vacuum & Hydroblasting Services API — Product Requirements Document

## 1. Introduction

Industrial vacuum and hydroblasting contractors operate under some of the least forgiving commercial conditions in field services: high-pressure water jets inside confined spaces, hazardous waste that must be characterized, manifested and reconciled against disposal-facility capacity, and standby time that customers dispute line by line. This API is the operating backbone for such a contractor. It governs the full engagement lifecycle — from the commercial rate agreement signed with a customer site, through job scoping, hazard analysis, permit coordination, crew and equipment assignment, field execution, waste shipment and disposal reconciliation, to downtime billing, invoicing and final payment.

Two design commitments shape everything that follows. First, safety is an independent, first-class dimension of every job: a job advances through its execution lifecycle only while its parallel safety dimension permits it, and a single serious incident can halt work and suspend every active permit in one atomic step. Second, money is deterministic: invoices are produced by a pricing engine that supports both unit-rate and time-and-materials commercial models, all amounts are computed in integer cents with a pinned rounding order, and approval workflows enforce segregation of duties so that no operator approves their own submission. Even time is deterministic — the platform runs on a logical clock so that permit windows, rest periods, grace allowances and expiry sweeps are fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the platform-wide contract. All endpoints are mounted under the `/v1` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their role. Seven roles are recognized: `PlatformAdmin`, `AccountManager`, `ProjectManager`, `FieldSupervisor`, `SafetyManager`, `ComplianceOfficer`, and `EnvironmentalApprover`. A request whose `X-User-Role` is missing or does not name one of these roles, or whose `X-User-ID` is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

For all seven roles — `PlatformAdmin`, `AccountManager`, `ProjectManager`, `FieldSupervisor`, `SafetyManager`, `ComplianceOfficer`, and `EnvironmentalApprover` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands attribution — as `submitted_by` and `approved_by` on a hazard analysis revision, and as `submitted_by` on a waste profile — but it never compares `X-User-ID` to any resource's `id`.

Role charters in brief. `PlatformAdmin` is the platform operator and owns the logical clock plus the fleet, crew and facility registries. `AccountManager` owns the commercial relationship: sites, rate schedules, and invoice issuance, adjustment and voiding. `ProjectManager` runs the job lifecycle end to end — scheduling, crewing, manifests, containment verification, invoice generation and the daily close. `FieldSupervisor` is the field lead: drafting hazard analyses and permits, logging containment and downtime, reporting incidents. `SafetyManager` is the HSE authority: hazard-analysis approval and rejection, permit suspension and revocation, stop-work and resume-work, incident review and closure. `ComplianceOfficer` handles environmental compliance drafting — waste profiles and manifest voiding. `EnvironmentalApprover` is the independent approver for waste profiles, deliberately segregated from the `ComplianceOfficer` who submits them.

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

List endpoints accept two optional query parameters. `limit` controls the page size: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` controls how many items are skipped before the page begins and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Change Tracking

Every resource in the platform — all fifteen types, from sites and jobs to invoices and incident reports — carries the same four system-managed properties:

- `id`: a server-minted UUID with no type prefix.
- `created_at`: an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at`: an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version`: an integer that increments by one on every mutation of the resource.

Cascading transitions count as mutations on every resource they touch: when one operation advances several resources at once — a job cancellation that also revokes permits, voids manifests and closes downtime, for example — each affected resource is mutated independently, refreshing its own `updated_at` and incrementing its own `version`. Consistency is immediate rather than eventual: derived values such as a job's accrued standby total or a facility's reserved tonnage are recomputed inside the triggering write, never deferred to a later pass. Invoice line items are sub-objects of their invoice, addressed by a `line_id`, not independent resources carrying UUIDs.

### 2.5. The Logical Clock and the Daily-Close Checkpoint

Time inside the platform is read from a logical clock, never from wall-clock time. Before it has ever been set, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time thereafter. A `PlatformAdmin` advances it through an administrative test-driving capability that accepts a `to_iso8601` instant and reports the resulting `current_utc`. Advancing the clock mutates no entities by itself; the clock reading feeds permit validity checks, downtime timestamps, and the two time-driven sweeps.

Those sweeps run only through the per-site daily-close checkpoint, executed by a `ProjectManager`. The checkpoint expires every permit belonging to the site's jobs that is still `ISSUED`, `ACTIVE` or `SUSPENDED` and whose `valid_until` is earlier than the current clock reading, moving each such permit to `EXPIRED`; and it cancels every assignment of the site's jobs that is still `SCHEDULED` and whose `window_start` lies more than 24 hours in the past, moving each to `CANCELLED`. The checkpoint's response lists the affected identifiers as `expired_permit_ids` and `cancelled_assignment_ids`.

### 2.6. Money, Measurement and Rounding Discipline

All monetary amounts are integer cents, and all rates are carried in integer cents per unit. Whenever a computed amount lands on a fraction of a cent, it is rounded half up to the nearest whole cent. Invoice construction pins the rounding order: each line's `amount_cents` is rounded half up to whole cents first, and the invoice `subtotal_cents` is then the exact integer sum of the already-rounded line amounts. The alternative order — summing exact fractional amounts and rounding once at the end — is forbidden, because the two orders diverge whenever two or more lines carry a fractional half cent. Consider two overtime lines of 1.0 hour each at a labor rate of 12995 cents with a multiplier of 1.5: rounding per line first yields 19493 + 19493 = 38986 cents, while rounding only at the end would wrongly yield 38985.

Other measured quantities carry their own fixed precision. Tonnages such as `estimated_tons` and `reserved_tons` are rounded half up to two decimal places. Variance percentages such as `variance_pct` are rounded half up to two decimal places. A containment record's `capture_ratio` is rounded half up to four decimal places. An assignment's `window_hours` is expressed in hours with two decimal places. Downtime durations are whole minutes, and each downtime event is rounded exactly once, at the moment its billed amount is computed.

### 2.7. Optimistic Concurrency Control

Two writes in the platform are guarded by optimistic concurrency control on a parent entity's `version`:

- **Rate-schedule activation** requires the request to carry `expected_site_version`, the client-observed `version` of the owning site. If the site's current `version` has advanced beyond what the client last read, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). The guard exists because activation legitimately supersedes the site's currently `ACTIVE` schedule: a client holding a stale site version must re-read before activating a different schedule.
- **Hazard-analysis approval** requires the request to carry `expected_job_version`, the client-observed `version` of the owning job. A mismatch with the job's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), because approval supersedes the job's currently `APPROVED` revision and a stale reader may be approving against an outdated job state.

No endpoint other than these two accepts a version field.

### 2.8. Validation Order

Every request passes through a fixed validation pipeline, and the first failing check determines the error returned:

1. **Authentication** — `X-User-Role` names a declared role and `X-User-ID` is present, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role is listed among the endpoint's permitted roles, else `ERR_FORBIDDEN`.
3. **Request shape** — required fields are present, types are valid, enum membership is valid, numeric ranges are valid (quantities greater than zero where required), and an assignment carries exactly the foreign key matching its `resource_kind` — `equipment_unit_id` if and only if the kind is `EQUIPMENT`, `operator_id` if and only if it is `OPERATOR`, the other forbidden — else `ERR_INVALID_REQUEST`.
4. **Existence** — path identifiers and body foreign keys reference existing resources, validated left to right, else `ERR_NOT_FOUND`.
5. **Concurrency** — on the two guarded writes named in §2.7, the expected parent version equals the parent's current `version`, else `ERR_STALE_VERSION`.
6. **State legality** — the target entity is in a from-state that permits the requested transition, and terminal states accept no further transitions, else `ERR_INVALID_STATE`.
7. **Business gates**, evaluated in a fixed relative order: the safety-posture gate (`ERR_JOB_STOPPED`) before hazard-analysis presence (`ERR_JHA_NOT_APPROVED`) before pressure-plan completeness (`ERR_JHA_PRESSURE_PLAN_REQUIRED`) before confined-space permit presence (`ERR_PERMIT_NOT_ACTIVE`) before permit–JHA agreement (`ERR_PERMIT_JHA_MISMATCH`) before equipment pressure rating (`ERR_PRESSURE_RATING_INSUFFICIENT`) before operator certification (`ERR_OPERATOR_NOT_CERTIFIED`) before segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) before containment verification (`ERR_CONTAINMENT_DEFICIENT`) before space occupancy (`ERR_PERMIT_SPACE_OCCUPIED`) before window validity (`ERR_INVALID_WINDOW`) before equipment overlap (`ERR_RESOURCE_SCHEDULE_CONFLICT`) before operator rest (`ERR_OPERATOR_REST_PERIOD`) before permit validity window (`ERR_PERMIT_WINDOW_INVALID`) before the referential gates (`ERR_NO_ACTIVE_RATE_SCHEDULE`, `ERR_WASTE_PROFILE_NOT_APPROVED`, `ERR_MANIFEST_UNRECONCILED`, `ERR_DOWNTIME_OPEN`, `ERR_NO_ASSIGNMENTS`, `ERR_NO_CONFIRMED_CREW`, `ERR_JOB_HAS_COMMITTED_WASTE`, `ERR_INVOICE_NOT_PAID`), and finally the fiscal gates (`ERR_SITE_CREDIT_HOLD`, then `ERR_FACILITY_CAPACITY_EXCEEDED`).

The business conditions that trip each gate are described beside the workflows that enforce them in §3.

### 2.9. Disposal Capacity as a Reserved Ledger

Each disposal facility tracks `reserved_tons` — the sum of `estimated_tons` over manifests currently `ISSUED` whose waste profile names that facility — and a derived `posture`: `FULL` once `reserved_tons` reaches or exceeds `total_capacity_tons`, otherwise `AVAILABLE`. Reservation is a ledger, not a snapshot. Issuing a manifest adds its estimated tonnage; receiving it, voiding it while `ISSUED`, or suspending its waste profile (which voids its `ISSUED` manifests) each release the reservation; and every release recomputes the facility's `posture` immediately — a `FULL` facility returns to `AVAILABLE` the moment `reserved_tons` drops below `total_capacity_tons`. A newly registered facility starts with `reserved_tons` at zero and `posture` `AVAILABLE`.

## 3. Business Logic & Workflows

### 3.1. Commercial Onboarding: Sites and Rate Schedules

An `AccountManager` opens a customer relationship by creating a site with a `name` and, optionally, a `credit_status`. When omitted, `credit_status` defaults to `GOOD_STANDING`; the alternative, `CREDIT_HOLD`, acts as a fiscal gate that later blocks the start of field work (§3.4). A new site's `active_rate_schedule_id` stays empty until the first schedule activation. The sites list can be filtered by `credit_status` or `active_rate_schedule_id`, and an `AccountManager` can later update a site's `credit_status` directly, each such update incrementing the site's `version` by one.

Commercial terms live on rate schedules, which an `AccountManager` authors in `DRAFT` against a `site_id` with a human-readable `label` and a full rate card: `vacuum_per_gallon_cents` and `hydroblast_per_foot_cents` price measured output under the unit-rate model; `labor_rate_cents_per_hour` and `equipment_rate_cents_per_hour` are the blended hourly rates under the time-and-materials model; `standby_rate_cents_per_hour` prices billable downtime; `overtime_multiplier` defaults to 1.5 when omitted; and `minimum_invoice_cents` sets a floor on the unit-rate work total — it must be zero or positive, and a value of zero disables the floor entirely.

Activation is the only way a schedule takes effect, and it is one of the platform's two concurrency-guarded writes (§2.7): the caller presents `expected_site_version`. On success the owning site's `active_rate_schedule_id` is set to the newly activated schedule, whichever schedule of that site was previously `ACTIVE` moves to `SUPERSEDED`, and the site's `version` increments by one. A schedule's `status` therefore walks `DRAFT` → `ACTIVE` → `SUPERSEDED`, and `SUPERSEDED` is terminal. `ACTIVE` schedules are immutable — amending commercial terms means authoring and activating a new schedule. The schedules list can be filtered by `site_id` and `status`.

### 3.2. Job Intake, Fleet Registry and Crew Assignment

A `ProjectManager` creates a job against a `site_id`, declaring the `job_type` (`VACUUM`, `HYDROBLAST` or `COMBINED`), the commercial `pricing_mode` (`UNIT_RATE` or `TIME_AND_MATERIALS`) that selects the invoice variant at billing time, a scope `description`, and an optional bid estimate `estimated_gallons` that defaults to zero. Creation pins the site's currently active schedule into the job's `pinned_rate_schedule_id`; when the site has no active schedule the create is rejected with `ERR_NO_ACTIVE_RATE_SCHEDULE`. Because all later billing — unit rates, hourly rates, the standby rate, the overtime multiplier, the minimum charge — reads the pinned schedule, a mid-flight schedule amendment at the site never reprices an existing job. New jobs open with `execution_status` `QUOTED`, `safety_status` `CLEAR`, and `standby_accrued_cents` at zero. The jobs list can be filtered by `site_id`, `execution_status` and `pinned_rate_schedule_id`.

Before a job can be scheduled, someone must staff it. A `PlatformAdmin` maintains the two registries. Equipment units are registered with a fleet `unit_code`, a `unit_type` (`VAC_TRUCK`, `HYDROBLASTER` or `COMBO`), a `max_pressure_psi` rating that later gates hydroblast work, and an informational `tank_capacity_gal`. Operators are registered with a `full_name`, an informational `employee_ref`, the `hazwoper_expires_on` certification expiry date in YYYY-MM-DD form, and the `hydroblast_certified` qualification flag. The equipment list can be filtered by `unit_type`.

With the registries in place, a `ProjectManager` builds the crew through assignments. Each assignment names a `job_id`, a `resource_kind` — `EQUIPMENT` or `OPERATOR` — exactly the one matching foreign key (`equipment_unit_id` for equipment, `operator_id` for operators; supplying the wrong key, or both, is an `ERR_INVALID_REQUEST`), and a window from `window_start` to `window_end`. The window must be positive — an end at or before the start is rejected with `ERR_INVALID_WINDOW` — and the platform derives `window_hours` from it as the elapsed time in hours to two decimal places. Assignments can only be added while the job is `QUOTED`, `SCHEDULED` or `MOBILIZED`; a job in any later execution state rejects them with `ERR_INVALID_STATE`. Three further checks protect the assignment book:

- An operator's `hazwoper_expires_on` must cover the full assignment window; a certification expiring mid-window is rejected with `ERR_OPERATOR_NOT_CERTIFIED`.
- Equipment windows never overlap: for the same unit, no other `SCHEDULED` or `CONFIRMED` assignment may intersect the new one. Intervals are half-open, so one assignment ending exactly when another begins is allowed; a genuine overlap is rejected with `ERR_RESOURCE_SCHEDULE_CONFLICT`.
- Operators are protected by a ten-hour rest buffer: the new window must end at least ten hours before, or start at least ten hours after, every other `SCHEDULED` or `CONFIRMED` assignment of the same operator — a gap of exactly ten hours is allowed — otherwise the create fails with `ERR_OPERATOR_REST_PERIOD`.

New assignments start `SCHEDULED`. Confirming one moves `SCHEDULED` → `CONFIRMED`; releasing a confirmed assignment moves `CONFIRMED` → `RELEASED`, which is terminal; cancelling from either `SCHEDULED` or `CONFIRMED` lands in `CANCELLED`, also terminal. The daily-close checkpoint (§2.5) cancels `SCHEDULED` assignments whose window start passed more than a day ago, and a job cancellation cascades into assignments as described in §3.7. The assignments list answers reverse lookups by `job_id`, `equipment_unit_id`, `operator_id` and `status`.

Two early job transitions depend on this book. Scheduling — `QUOTED` → `SCHEDULED` — requires at least one assignment still `SCHEDULED` or `CONFIRMED`, failing with `ERR_NO_ASSIGNMENTS` otherwise. Mobilizing — `SCHEDULED` → `MOBILIZED` — tightens the requirement to at least one `CONFIRMED` assignment, failing with `ERR_NO_CONFIRMED_CREW`. Both transitions are performed by a `ProjectManager`, and each increments the job's `version` by one.

### 3.3. Hazard Analysis and Permit Coordination

Every job's safety case begins with a job hazard analysis. A `FieldSupervisor` authors a revision against a `job_id` — the job must not be `CANCELLED` or `CLOSED`, and an attempt against a job in either terminal state is rejected with `ERR_INVALID_STATE` — declaring whether the work involves a `confined_space`, listing the identified `hazards` (each entry one of `CONFINED_SPACE`, `HIGH_PRESSURE_WATER`, `CHEMICAL_EXPOSURE`, `SLIP_TRIP`, `ERGONOMIC` or `OTHER`), and, where the job is `HYDROBLAST` or `COMBINED`, the pressure and water plan: `max_operating_pressure_psi`, `planned_water_flow_gpm` and the `water_source` (`SITE_POTABLE`, `SITE_NONPOTABLE` or `TRUCKED_IN`). Each revision receives a `revision_number` one higher than the job's existing maximum, starting at one, and enters as `DRAFT`. The revision list can be filtered by `job_id` and `status`.

Submitting moves a revision `DRAFT` → `SUBMITTED` and stamps `submitted_by` with the caller's `X-User-ID`. For `HYDROBLAST` and `COMBINED` jobs the submission must carry all three pressure-plan fields, or it is rejected with `ERR_JHA_PRESSURE_PLAN_REQUIRED`; a `VACUUM` job carries no such requirement.

Approval belongs to a `SafetyManager` and is the platform's second concurrency-guarded write: the request must carry `expected_job_version` matching the job's current `version`, and this stale-version check is evaluated before any business gate — a stale read is rejected with `ERR_STALE_VERSION` (HTTP 412). Next, segregation of duties forbids the submitter from approving their own revision: an approver whose `X-User-ID` equals the revision's `submitted_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful approval stamps `approved_by`, moves the revision to `APPROVED`, atomically supersedes any other `APPROVED` revision of the same job — there is at most one approved revision per job at any time — and increments the job's `version` by one. Rejection (`SUBMITTED` → `REJECTED`) is likewise segregated: the rejecting `SafetyManager` must differ from `submitted_by`, under the same `ERR_SEGREGATION_OF_DUTIES` code. A rejected revision is not dead: revising it returns `REJECTED` → `DRAFT`, where its pressure and water plan can be corrected before resubmission — plans otherwise evolve only by authoring a new revision.

Permits are the field-level authorization layer. A `FieldSupervisor` creates one against a `job_id` with a `permit_type` (`CONFINED_SPACE`, `HOT_WORK` or `LINE_BREAK`), the physical `space_id` it governs, and a validity window from `valid_from` to `valid_until`; an end at or before the start is rejected with `ERR_INVALID_WINDOW`. Permits can only be raised while the job is `SCHEDULED`, `MOBILIZED` or `IN_PROGRESS` — against a job in any other execution state the create is rejected with `ERR_INVALID_STATE` — and they enter as `ISSUED`.

Activation — `ISSUED` → `ACTIVE`, or `SUSPENDED` → `ACTIVE` when restoring a suspended permit — is guarded by four checks in order: the job's safety dimension must be `CLEAR` (`ERR_JOB_STOPPED`); for a `CONFINED_SPACE` permit, the job's latest `APPROVED` hazard analysis must declare `confined_space` true (`ERR_PERMIT_JHA_MISMATCH`); no other permit of the same job and `space_id` may already be `ACTIVE` (`ERR_PERMIT_SPACE_OCCUPIED`); and the logical clock must read within the inclusive window from `valid_from` to `valid_until` (`ERR_PERMIT_WINDOW_INVALID`). From `ACTIVE`, a `SafetyManager` may suspend (`ACTIVE` → `SUSPENDED`) and a `FieldSupervisor` may close (`ACTIVE` → `CLOSED`); revocation (`ISSUED`, `ACTIVE` or `SUSPENDED` → `REVOKED`) belongs to a `SafetyManager` and also arrives automatically through a job cancellation. Permits still `ISSUED`, `ACTIVE` or `SUSPENDED` past their `valid_until` are swept to `EXPIRED` by the daily-close checkpoint. `CLOSED`, `REVOKED` and `EXPIRED` are terminal. Resuming work never re-activates suspended permits — each must be activated explicitly, passing the four activation checks again. The permits list can be filtered by `job_id` and `status`.

### 3.4. Field Execution: Start Gates, Containment, Incidents and Safety Stops

A job carries two independent status dimensions. `execution_status` walks the commercial-operational lifecycle `QUOTED` → `SCHEDULED` → `MOBILIZED` → `IN_PROGRESS` → `FIELD_COMPLETE` → `INVOICED` → `CLOSED`, with `CANCELLED` as the alternate terminal; `safety_status` moves only between `CLEAR` and `STOP_WORK`. The dimensions interact at exactly defined gates — most sharply at the start of field work.

Starting work (`MOBILIZED` → `IN_PROGRESS`, by a `ProjectManager`) evaluates six gates in order:

1. The safety dimension must be `CLEAR`, else `ERR_JOB_STOPPED`.
2. An `APPROVED` hazard analysis revision must exist for the job, else `ERR_JHA_NOT_APPROVED`.
3. When that approved analysis declares `confined_space` true, an `ACTIVE` permit of type `CONFINED_SPACE` must exist for the job, else `ERR_PERMIT_NOT_ACTIVE`.
4. For `HYDROBLAST` and `COMBINED` jobs, every equipment assignment in `SCHEDULED`, `CONFIRMED` or `RELEASED` whose unit is hydroblast-capable (`HYDROBLASTER` or `COMBO`) must carry a `max_pressure_psi` of at least the approved analysis's `max_operating_pressure_psi` — and at least one such hydroblast-capable assignment must exist — else `ERR_PRESSURE_RATING_INSUFFICIENT`.
5. For those same job types, every operator assignment in `SCHEDULED`, `CONFIRMED` or `RELEASED` must reference an operator whose `hydroblast_certified` flag is true, else `ERR_OPERATOR_NOT_CERTIFIED`.
6. The site's `credit_status` must be `GOOD_STANDING`, else `ERR_SITE_CREDIT_HOLD`.

A successful start increments the job's `version` by one.

While work runs, a `FieldSupervisor` logs decontamination and wash-water containment against the `IN_PROGRESS` job — logging against a job in any other execution state is rejected with `ERR_INVALID_STATE` — recording `water_used_gallons` (which must be greater than zero) and `water_captured_gallons` (zero or more). Each record takes the next per-job `sequence` — the highest existing sequence plus one, so "latest" always means the highest `sequence` — computes its `capture_ratio` as captured gallons divided by used gallons, rounded half up to four decimal places, and enters as `LOGGED`. Verification, by a `ProjectManager`, is a single call with two outcomes decided by the computed ratio: a `capture_ratio` of at least 0.9500 moves the record to `VERIFIED` — exactly 0.9500 passes — while anything below lands in `DEFICIENT`. Both outcomes are terminal. Containment records list by `job_id`.

Completing field work (`IN_PROGRESS` → `FIELD_COMPLETE`) closes the execution phase. The payload carries the measured quantities `gallons_removed` and `feet_cleaned`, which are stored on the job as the billing basis for unit-rate invoicing. Three gates guard the transition: the safety dimension must be `CLEAR` (`ERR_JOB_STOPPED`); no downtime event may still be `OPEN` (`ERR_DOWNTIME_OPEN`); and the job's latest containment record must be `VERIFIED` — when no records exist, or the latest is still `LOGGED` or has been found `DEFICIENT`, the attempt fails with `ERR_CONTAINMENT_DEFICIENT`. The transition increments the job's `version` by one.

Incidents and near-misses are reported by a `FieldSupervisor` while the job is `MOBILIZED`, `IN_PROGRESS` or `FIELD_COMPLETE` — a report against a job in any other execution state is rejected with `ERR_INVALID_STATE` — with a `severity` (`NEAR_MISS`, `MINOR`, `SERIOUS` or `MAJOR`), a short `title` and a narrative `description`; the report enters as `REPORTED`. Reporting a `SERIOUS` or `MAJOR` incident while the job's safety dimension is `CLEAR` immediately moves the job to `STOP_WORK` and suspends every `ACTIVE` permit on the job — the same cascade as an explicit stop. A `SafetyManager` then walks the report `REPORTED` → `UNDER_REVIEW` → `CLOSED`; closing requires the caller to record the OSHA recordability determination `osha_recordable` and a `corrective_action`, and a close missing either is rejected with `ERR_INVALID_REQUEST`. Incidents list by `job_id` and `status`.

An explicit stop-work, also by a `SafetyManager`, is legal from execution states `SCHEDULED`, `MOBILIZED`, `IN_PROGRESS` and `FIELD_COMPLETE` — any other execution state is rejected with `ERR_INVALID_STATE` — and moves `safety_status` from `CLEAR` to `STOP_WORK` while cascading every `ACTIVE` permit on the job to `SUSPENDED`. Resuming (`STOP_WORK` → `CLEAR`) requires that every incident report on the job is `CLOSED` (`ERR_INVALID_STATE` otherwise) and that an `APPROVED` hazard analysis still exists (`ERR_JHA_NOT_APPROVED`). Suspended permits stay suspended after the resume; each is re-activated explicitly under §3.3's four checks. Both transitions increment the job's `version` by one.

### 3.5. Standby Time and Downtime Billing

Standby is billed through downtime events. A `FieldSupervisor` opens one on an `IN_PROGRESS` job — opening an event against a job in any other execution state is rejected with `ERR_INVALID_STATE` — by naming the `job_id` and the `cause` — `CUSTOMER_DELAY`, `WEATHER`, `REGULATORY_HOLD`, `SAFETY_STOP` or `CONTRACTOR_FAULT`. The event stamps `started_at` from the logical clock, derives its `closure_day` as the UTC date of `started_at` in YYYY-MM-DD form (the grouping key for the daily cap), and sits `OPEN` until closed. Events list by `job_id`, `invoice_id` and `status`.

Closing an event — explicitly by a `FieldSupervisor`, or automatically when the job is cancelled — stamps `ended_at` from the clock and runs the billing computation against the job's pinned rate schedule. `duration_minutes` is the elapsed whole minutes between `started_at` and `ended_at`. `grace_minutes_applied` depends only on the cause: thirty minutes for `CUSTOMER_DELAY`, sixty minutes for `WEATHER`, and zero for `REGULATORY_HOLD`, `SAFETY_STOP` and `CONTRACTOR_FAULT`. A `CONTRACTOR_FAULT` event never bills — its `billable_minutes` is always zero. For every other cause, the raw billable time is the duration minus the grace, floored at zero (a duration exactly equal to the grace bills exactly zero minutes), and then the daily cap applies: sum the `billable_minutes` of the job's other `CLOSED` or `BILLED` events sharing the same `closure_day`, and bill only what fits within the room remaining toward the 480-minute daily ceiling — eight hours — never less than zero. `billed_blocks` counts the billable minutes in fifteen-minute blocks, any partial block rounding up to a whole block, and `billed_amount_cents` is the number of blocks multiplied by one quarter of the pinned schedule's `standby_rate_cents_per_hour`, rounded half up to whole cents — the event's single rounding.

The job's `standby_accrued_cents` is the running total of all of this: the sum of `billed_amount_cents` over the job's events in `CLOSED` or `BILLED`, recomputed immediately whenever an event closes or reverts, and again when an invoice is generated. Two system-driven transitions connect downtime to billing. Invoice generation sweeps each `CLOSED` event whose `billable_minutes` is greater than zero into `BILLED`, stamping its `invoice_id` with the new invoice. Voiding an invoice reverts exactly those events `BILLED` → `CLOSED`, clearing `invoice_id`, so the standby can be re-billed on the corrected invoice.

### 3.6. Waste Characterization, Manifests and Facility Reconciliation

Disposal capacity is contracted per site through waste profiles. A `ComplianceOfficer` drafts a profile naming the generator `site_id`, the contracted `facility_id`, a `waste_code`, the `hazard_class` (`NON_HAZ`, `HAZ` or `SPECIAL`), the characterized `density_lbs_per_gal` used for gallon–ton conversion, the contracted `disposal_rate_per_ton_cents`, and the `variance_basis` — `VOLUME` or `WEIGHT` — that selects how receipt variance is measured. The destination facilities themselves are registered by a `PlatformAdmin` with a `name`, an `epa_id` and a `total_capacity_tons`; they begin with `reserved_tons` at zero and `posture` `AVAILABLE`, and §2.9's reservation ledger keeps both current thereafter.

The profile's approval chain enforces segregation of duties: the `ComplianceOfficer` submits (`DRAFT` → `SUBMITTED`, stamping `submitted_by` with the caller's `X-User-ID`), and an `EnvironmentalApprover` approves (`SUBMITTED` → `APPROVED`) — an approver whose `X-User-ID` equals `submitted_by` is rejected with `ERR_SEGREGATION_OF_DUTIES`. An `APPROVED` profile can be suspended by an `EnvironmentalApprover`, and suspension cascades in three linked steps: every manifest referencing the profile in `DRAFT` or `ISSUED` is voided; each `ISSUED` manifest so voided releases its facility reservation, subtracting its `estimated_tons` from the facility's `reserved_tons`; and each release recomputes the facility's `posture`. Reinstating moves `SUSPENDED` → `APPROVED` but does not restore the voided manifests. Profiles list by `site_id`, `facility_id` and `status`.

Manifests track each shipment. A `ProjectManager` creates one against a `job_id` — the job must be `IN_PROGRESS` or `FIELD_COMPLETE`, and any other execution state is rejected with `ERR_INVALID_STATE` — naming the `waste_profile_id` (which supplies characterization, pricing and the destination facility) and the shipped `estimated_gallons` from the truck gauge; the manifest enters as `DRAFT`. Issuing (`DRAFT` → `ISSUED`) requires the profile to be `APPROVED` (`ERR_WASTE_PROFILE_NOT_APPROVED` otherwise) and computes `estimated_tons` as the shipped gallons multiplied by the profile's `density_lbs_per_gal` and divided by 2000, rounded half up to two decimal places. The facility must have room: the manifest's `estimated_tons` added to the facility's `reserved_tons` may not exceed `total_capacity_tons` — exactly reaching capacity is allowed — else the issue is rejected with `ERR_FACILITY_CAPACITY_EXCEEDED`. On success the reservation is added and the facility's `posture` recomputed.

Departure moves `ISSUED` → `IN_TRANSIT`. Receipt is where the variance branch lives: the caller reports the facility scale weight as `received_tons`, and the platform computes `variance_pct` according to the profile's `variance_basis`. Under `WEIGHT`, the shipped estimate is converted to tons the same way as at issue — gallons times density divided by 2000, rounded half up to two decimal places — and the variance is the difference between `received_tons` and that shipped estimate, divided by the shipped estimate, expressed as a percentage rounded half up to two decimal places. Under `VOLUME`, the received weight is converted to gallons instead — `received_tons` times 2000 divided by the density, rounded half up to one decimal place — and the variance is the difference between that received-gallons figure and `estimated_gallons`, divided by `estimated_gallons`, again expressed as a percentage rounded half up to two decimal places. The two bases round in a different order and can produce different percentages for identical weights and measures. An absolute `variance_pct` greater than 10.00 percent — in either direction — routes the manifest to `EXCEPTION`; a variance at or below 10.00 percent, equality included, routes it to `RECEIVED`. Whichever branch is taken, the facility reservation is released and the `posture` recomputed.

Reconciliation locks the billable quantity. From `RECEIVED`, reconciling sets `billed_tons` to `received_tons`. From `EXCEPTION`, resolving requires a `resolution_note` — a missing note is rejected with `ERR_INVALID_REQUEST` — and sets `billed_tons` to `adjusted_tons` when the caller provides one, otherwise to `received_tons`. Both paths then compute `disposal_charge_cents` as `billed_tons` multiplied by the profile's `disposal_rate_per_ton_cents`, rounded half up to whole cents. A `ComplianceOfficer` may void a manifest while it is `DRAFT` or `ISSUED`; voiding an `ISSUED` manifest releases its reservation and recomputes the facility's `posture`. `RECONCILED` and `VOIDED` are terminal. Manifests list by `job_id`, `waste_profile_id` and `status`.

### 3.7. Invoicing, Adjustment and Job Closure

Invoice generation (`FIELD_COMPLETE` → `INVOICED`, by a `ProjectManager`) is the pricing engine's moment. Uniqueness is structural: generation is the only way an invoice comes into existence, it is legal only from `FIELD_COMPLETE`, and a job sitting in `INVOICED` blocks re-entry until its invoice is voided — which reverts the job first, as described below. Two gates guard generation: every manifest of the job must be `RECONCILED` or `VOIDED` (`ERR_MANIFEST_UNRECONCILED` otherwise), and every downtime event must be `CLOSED` or `BILLED` (`ERR_DOWNTIME_OPEN` otherwise). The new invoice enters as `DRAFT`, takes an `invoice_number` of the form INV-<job creation sequence>-<regeneration count> — the regeneration count distinguishing a corrected invoice from the one it replaces — snapshots the job's `pricing_mode` into `pricing_mode_snapshot`, and builds its `lines`. The generation increments the job's `version` by one.

Line construction depends on the pricing variant. Under `UNIT_RATE`, measured outputs are billed: a `VACUUM` line for `VACUUM` and `COMBINED` jobs bills `gallons_removed` at the pinned schedule's `vacuum_per_gallon_cents`, and a `HYDRO` line for `HYDROBLAST` and `COMBINED` jobs bills `feet_cleaned` at `hydroblast_per_foot_cents`. Quantities are whole numbers and rates are integer cents, so these line amounts are exact and need no rounding. When the work lines sum below the schedule's `minimum_invoice_cents` — and the minimum is not zero — an `ADJUSTMENT` line with `origin` `AUTO_MINIMUM` and `discountable` false is appended for exactly the shortfall, bringing the work total up to the floor. Under `UNIT_RATE`, no labor or equipment window lines appear at all.

Under `TIME_AND_MATERIALS`, crew windows are billed instead, and the measured gallons and feet never appear as lines. The engine walks the job's assignments in `CONFIRMED` or `RELEASED` status — `SCHEDULED` and `CANCELLED` are excluded — in creation order. An operator assignment bills a `LABOR_REG` line at the lesser of eight hours and the assignment's `window_hours`, multiplied by `labor_rate_cents_per_hour` and rounded half up; when the window exceeds eight hours, a `LABOR_OT` line bills the excess hours multiplied by the labor rate and by `overtime_multiplier`, rounded half up — no overtime line appears for a window of eight hours or less. An equipment assignment bills an `EQUIPMENT` line at its `window_hours` multiplied by `equipment_rate_cents_per_hour`, rounded half up.

Both variants then append the same two trailing groups. First, one `STANDBY` line per downtime event in `CLOSED` or `BILLED` whose `billable_minutes` is greater than zero, in creation order, each at the event's `billed_amount_cents`, which is already whole cents. Second, one `DISPOSAL` line per `RECONCILED` manifest, in creation order, each at the manifest's `disposal_charge_cents` and never discountable. Every line object carries a `line_id` of the form L<n> assigned one-based in append order, plus `kind`, `description`, `quantity`, `unit`, `rate_cents`, `amount_cents`, `discountable`, `voided` (false at generation) and `origin` (`SYSTEM` for generated lines, `AUTO_MINIMUM` for the floor adjustment). The discountable kinds are `VACUUM`, `HYDRO`, `LABOR_REG`, `LABOR_OT`, `EQUIPMENT` and `STANDBY`; `DISPOSAL` and `ADJUSTMENT` are never discountable.

Totals follow a pinned evaluation order. `subtotal_cents` is the sum of `amount_cents` over all non-voided lines. The discountable subtotal sums only non-voided lines whose `discountable` flag is true. The volume-discount tier is selected on that pre-discount discountable subtotal: at least two million cents earns 7 percent; at least five hundred thousand cents earns 3 percent — a discountable subtotal of exactly five hundred thousand cents qualifies; anything below earns nothing. `discount_cents` is the discountable subtotal multiplied by the tier percentage, rounded half up. `environmental_fee_cents` is two percent of the remainder after subtracting `discount_cents` from `subtotal_cents`, rounded half up. `total_cents` is `subtotal_cents` minus `discount_cents` plus `environmental_fee_cents`. Keying the tier on the post-discount remainder is forbidden: a discountable subtotal of exactly five hundred thousand cents, when it constitutes the entire subtotal, must produce a `total_cents` of 494700, where the post-discount reading would wrongly produce 510000. Per §2.6, every line is rounded before any summation.

Invoice lifecycle and adjustment sit with the `AccountManager`. Issuing moves `DRAFT` → `ISSUED`; marking paid moves `ISSUED` → `PAID`; voiding from either `DRAFT` or `ISSUED` lands in `VOID`, and `PAID` and `VOID` are terminal. Voiding cascades in two links: the owning job reverts `INVOICED` → `FIELD_COMPLETE`, and every downtime event that was swept `BILLED` through this invoice reverts to `CLOSED` with its `invoice_id` cleared — reopening standby billing so a corrected invoice can be generated. While an invoice is `DRAFT`, an `AccountManager` may append a corrective line by supplying a `description` and an `amount_cents`; the new line takes the next `line_id` in sequence, is an `ADJUSTMENT` kind with `origin` `MANUAL` and `discountable` false, and the invoice's `subtotal_cents`, `environmental_fee_cents` and `total_cents` recompute while the discount base is unchanged, since adjustments are not discountable. Voiding a single line of a `DRAFT` invoice sets that line's `voided` flag true and recomputes the totals — including the discount itself whenever the voided line was a discountable one, per the pinned totals rule above. Invoices list by `job_id` and `status`.

Closure and cancellation end the job. Closing (`INVOICED` → `CLOSED`, by a `ProjectManager`) requires the job's non-`VOID` invoice to be `PAID`, failing with `ERR_INVOICE_NOT_PAID` otherwise. Cancelling is available from `QUOTED`, `SCHEDULED`, `MOBILIZED`, `IN_PROGRESS` and `FIELD_COMPLETE` — never from `INVOICED`, `CLOSED` or `CANCELLED` — and is blocked while any manifest of the job is `IN_TRANSIT`, `RECEIVED` or `RECONCILED`, rejected with `ERR_JOB_HAS_COMMITTED_WASTE`. A cancellation cascades: assignments in `SCHEDULED` or `CONFIRMED` move to `CANCELLED`; permits in `ISSUED`, `ACTIVE` or `SUSPENDED` move to `REVOKED`; manifests in `DRAFT` or `ISSUED` move to `VOIDED`, and each `ISSUED` void releases its facility reservation with the `posture` recomputed; and every `OPEN` downtime event closes with `ended_at` stamped at the cancellation's clock reading and the normal billing computation of §3.5 applied. Both transitions increment the job's `version` by one, and `CLOSED` and `CANCELLED` are the terminal execution states.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. The table below is a summary only — request payloads, response bodies and side effects are defined by the workflows in §3 and the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/sites` | Create a customer site | AccountManager |
| GET | `/v1/sites` | List sites (paginated) | All roles |
| GET | `/v1/sites/{siteId}` | Get a site | All roles |
| PATCH | `/v1/sites/{siteId}` | Update site credit status | AccountManager |
| POST | `/v1/rate-schedules` | Create a rate schedule (DRAFT) for a site | AccountManager |
| GET | `/v1/rate-schedules` | List rate schedules | All roles |
| GET | `/v1/rate-schedules/{scheduleId}` | Get a rate schedule | All roles |
| POST | `/v1/rate-schedules/{scheduleId}/activate` | Activate a DRAFT schedule; supersedes the site's current ACTIVE schedule (OCC on the site version) | AccountManager |
| POST | `/v1/jobs` | Create a job; pins the site's ACTIVE rate schedule | ProjectManager |
| GET | `/v1/jobs` | List jobs | All roles |
| GET | `/v1/jobs/{jobId}` | Get a job | All roles |
| POST | `/v1/jobs/{jobId}/schedule` | QUOTED → SCHEDULED (requires a non-cancelled assignment) | ProjectManager |
| POST | `/v1/jobs/{jobId}/mobilize` | SCHEDULED → MOBILIZED (requires a CONFIRMED assignment) | ProjectManager |
| POST | `/v1/jobs/{jobId}/start-work` | MOBILIZED → IN_PROGRESS (JHA approved, confined-space permit, pressure rating, crew certifications, credit gate) | ProjectManager |
| POST | `/v1/jobs/{jobId}/complete-field-work` | IN_PROGRESS → FIELD_COMPLETE; records measured quantities | ProjectManager |
| POST | `/v1/jobs/{jobId}/cancel` | Cancel a non-terminal, non-INVOICED job; cascades to assignments, permits, manifests, downtime | ProjectManager |
| POST | `/v1/jobs/{jobId}/stop-work` | safety_status CLEAR → STOP_WORK; suspends ACTIVE permits | SafetyManager |
| POST | `/v1/jobs/{jobId}/resume-work` | safety_status STOP_WORK → CLEAR (all incidents CLOSED, JHA still APPROVED) | SafetyManager |
| POST | `/v1/jobs/{jobId}/close` | INVOICED → CLOSED (invoice must be PAID) | ProjectManager |
| POST | `/v1/jobs/{jobId}/generate-invoice` | FIELD_COMPLETE → INVOICED; builds the DRAFT invoice per pricing_mode | ProjectManager |
| POST | `/v1/jhas` | Create a JHA revision for a job (next revision number; job must not be CANCELLED/CLOSED) | FieldSupervisor |
| GET | `/v1/jhas` | List JHAs | All roles |
| GET | `/v1/jhas/{jhaId}` | Get a JHA | All roles |
| POST | `/v1/jhas/{jhaId}/submit` | DRAFT → SUBMITTED (pressure/water plan required for HYDROBLAST/COMBINED) | FieldSupervisor |
| POST | `/v1/jhas/{jhaId}/approve` | SUBMITTED → APPROVED; supersedes prior APPROVED revision (OCC on the job version; approver differs from submitter) | SafetyManager |
| POST | `/v1/jhas/{jhaId}/reject` | SUBMITTED → REJECTED (rejector differs from submitter) | SafetyManager |
| POST | `/v1/jhas/{jhaId}/revise` | REJECTED → DRAFT (revision cycle) | FieldSupervisor |
| POST | `/v1/permits` | Create a permit (ISSUED); job must be SCHEDULED, MOBILIZED or IN_PROGRESS | FieldSupervisor |
| GET | `/v1/permits` | List permits | All roles |
| GET | `/v1/permits/{permitId}` | Get a permit | All roles |
| POST | `/v1/permits/{permitId}/activate` | ISSUED or SUSPENDED → ACTIVE (safety clear, JHA match, one ACTIVE per space, within validity window) | FieldSupervisor |
| POST | `/v1/permits/{permitId}/suspend` | ACTIVE → SUSPENDED | SafetyManager |
| POST | `/v1/permits/{permitId}/close` | ACTIVE → CLOSED | FieldSupervisor |
| POST | `/v1/permits/{permitId}/revoke` | ISSUED, ACTIVE or SUSPENDED → REVOKED | SafetyManager |
| POST | `/v1/equipment-units` | Register an equipment unit | PlatformAdmin |
| GET | `/v1/equipment-units` | List equipment units | All roles |
| GET | `/v1/equipment-units/{unitId}` | Get an equipment unit | All roles |
| POST | `/v1/operators` | Register an operator | PlatformAdmin |
| GET | `/v1/operators` | List operators | All roles |
| GET | `/v1/operators/{operatorId}` | Get an operator | All roles |
| POST | `/v1/assignments` | Assign equipment or an operator to a job window; overlap, rest and certification checks | ProjectManager |
| GET | `/v1/assignments` | List assignments (reverse lookup by job, equipment or operator) | All roles |
| GET | `/v1/assignments/{assignmentId}` | Get an assignment | All roles |
| POST | `/v1/assignments/{assignmentId}/confirm` | SCHEDULED → CONFIRMED | ProjectManager |
| POST | `/v1/assignments/{assignmentId}/release` | CONFIRMED → RELEASED | ProjectManager |
| POST | `/v1/assignments/{assignmentId}/cancel` | SCHEDULED or CONFIRMED → CANCELLED | ProjectManager |
| POST | `/v1/waste-profiles` | Create a waste characterization profile (DRAFT) | ComplianceOfficer |
| GET | `/v1/waste-profiles` | List waste profiles (reverse lookup by site and facility) | All roles |
| GET | `/v1/waste-profiles/{profileId}` | Get a waste profile | All roles |
| POST | `/v1/waste-profiles/{profileId}/submit` | DRAFT → SUBMITTED (records submitter) | ComplianceOfficer |
| POST | `/v1/waste-profiles/{profileId}/approve` | SUBMITTED → APPROVED (approver differs from submitter) | EnvironmentalApprover |
| POST | `/v1/waste-profiles/{profileId}/suspend` | APPROVED → SUSPENDED; voids DRAFT/ISSUED manifests and releases facility reservations | EnvironmentalApprover |
| POST | `/v1/waste-profiles/{profileId}/reinstate` | SUSPENDED → APPROVED (does not restore voided manifests) | EnvironmentalApprover |
| POST | `/v1/disposal-facilities` | Register a disposal facility | PlatformAdmin |
| GET | `/v1/disposal-facilities` | List disposal facilities | All roles |
| GET | `/v1/disposal-facilities/{facilityId}` | Get a disposal facility | All roles |
| POST | `/v1/manifests` | Create a disposal manifest (DRAFT); job must be IN_PROGRESS or FIELD_COMPLETE | ProjectManager |
| GET | `/v1/manifests` | List manifests (reverse lookup by job and waste profile) | All roles |
| GET | `/v1/manifests/{manifestId}` | Get a manifest | All roles |
| POST | `/v1/manifests/{manifestId}/issue` | DRAFT → ISSUED; computes estimated tons; reserves facility capacity | ProjectManager |
| POST | `/v1/manifests/{manifestId}/depart` | ISSUED → IN_TRANSIT | ProjectManager |
| POST | `/v1/manifests/{manifestId}/receive` | IN_TRANSIT → RECEIVED (variance at or below 10.00) or → EXCEPTION (above 10.00); releases reservation | ProjectManager |
| POST | `/v1/manifests/{manifestId}/reconcile` | RECEIVED → RECONCILED; locks billed tons and the disposal charge | ProjectManager |
| POST | `/v1/manifests/{manifestId}/resolve-exception` | EXCEPTION → RECONCILED with resolution note and optional adjusted quantity | ProjectManager |
| POST | `/v1/manifests/{manifestId}/void` | DRAFT or ISSUED → VOIDED; an ISSUED void releases the reservation | ComplianceOfficer |
| POST | `/v1/containment-records` | Log decontamination/wash-water containment for an IN_PROGRESS job; computes capture ratio and per-job sequence | FieldSupervisor |
| GET | `/v1/containment-records` | List containment records (reverse lookup by job) | All roles |
| GET | `/v1/containment-records/{recordId}` | Get a containment record | All roles |
| POST | `/v1/containment-records/{recordId}/verify` | LOGGED → VERIFIED when the capture ratio is at least 0.9500, else → DEFICIENT | ProjectManager |
| POST | `/v1/downtime-events` | Open a downtime/standby event on an IN_PROGRESS job | FieldSupervisor |
| GET | `/v1/downtime-events` | List downtime events (reverse lookup by job and invoice) | All roles |
| GET | `/v1/downtime-events/{eventId}` | Get a downtime event | All roles |
| POST | `/v1/downtime-events/{eventId}/close` | OPEN → CLOSED; computes duration, grace, billable minutes, blocks and amount | FieldSupervisor |
| GET | `/v1/invoices` | List invoices (reverse lookup by job) | All roles |
| GET | `/v1/invoices/{invoiceId}` | Get an invoice | All roles |
| POST | `/v1/invoices/{invoiceId}/issue` | DRAFT → ISSUED | AccountManager |
| POST | `/v1/invoices/{invoiceId}/mark-paid` | ISSUED → PAID | AccountManager |
| POST | `/v1/invoices/{invoiceId}/void` | DRAFT or ISSUED → VOID; reverts the job INVOICED → FIELD_COMPLETE and un-bills its downtime | AccountManager |
| POST | `/v1/invoices/{invoiceId}/lines` | Append a corrective ADJUSTMENT line (not discountable, origin MANUAL) to a DRAFT invoice; totals recompute | AccountManager |
| POST | `/v1/invoices/{invoiceId}/lines/{lineId}/void` | Void one line of a DRAFT invoice; totals recompute | AccountManager |
| POST | `/v1/incidents` | Report an incident or near-miss on a job that is MOBILIZED, IN_PROGRESS or FIELD_COMPLETE; SERIOUS/MAJOR drives the job to STOP_WORK and suspends ACTIVE permits | FieldSupervisor |
| GET | `/v1/incidents` | List incidents (reverse lookup by job) | All roles |
| GET | `/v1/incidents/{incidentId}` | Get an incident | All roles |
| POST | `/v1/incidents/{incidentId}/start-review` | REPORTED → UNDER_REVIEW | SafetyManager |
| POST | `/v1/incidents/{incidentId}/close` | UNDER_REVIEW → CLOSED with the OSHA recordability determination | SafetyManager |
| POST | `/v1/sites/{siteId}/daily-close` | Operations checkpoint for a site: sweeps expired permits and stale SCHEDULED assignments | ProjectManager |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 beside the workflows that enforce them.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_JOB_STOPPED` | 409 Conflict |
| `ERR_JHA_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_JHA_PRESSURE_PLAN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PERMIT_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_PERMIT_JHA_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRESSURE_RATING_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_OPERATOR_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_CONTAINMENT_DEFICIENT` | 422 Unprocessable Entity |
| `ERR_PERMIT_SPACE_OCCUPIED` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_RESOURCE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_OPERATOR_REST_PERIOD` | 409 Conflict |
| `ERR_PERMIT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_RATE_SCHEDULE` | 422 Unprocessable Entity |
| `ERR_WASTE_PROFILE_NOT_APPROVED` | 422 Unprocessable Entity |
| `ERR_MANIFEST_UNRECONCILED` | 422 Unprocessable Entity |
| `ERR_DOWNTIME_OPEN` | 422 Unprocessable Entity |
| `ERR_NO_ASSIGNMENTS` | 422 Unprocessable Entity |
| `ERR_NO_CONFIRMED_CREW` | 422 Unprocessable Entity |
| `ERR_JOB_HAS_COMMITTED_WASTE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAID` | 422 Unprocessable Entity |
| `ERR_SITE_CREDIT_HOLD` | 422 Unprocessable Entity |
| `ERR_FACILITY_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |

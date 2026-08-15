# High-Voltage Cable Testing and Fault Location API — Product Requirements Document

## 1. Introduction

Electric utilities and industrial network operators depend on underground high-voltage cable circuits whose insulation health cannot be observed directly; it must be inferred from diagnostic campaigns executed inside tightly coordinated customer outage windows. This document specifies the API of a cable diagnostics contractor that manages the full campaign lifecycle: registering circuits and their electrical reference data, requesting and approving outage windows, planning and budgeting diagnostic test jobs, enforcing isolation and grounding safety, executing very-low-frequency and partial-discharge test series, pinpointing faults from time-domain reflectometry traces, coordinating excavation and splice repair, accepting repairs through re-testing, and trending circuit health to drive replacement planning.

Three disciplines shape every workflow in this system. The first is temporal discipline: a server-side logical clock — never the wall clock — arbitrates every window, deadline, buffer, and curing period, and every interval in the domain carries explicit inclusivity rules that decide whether boundary instants are permitted. The second is safety and accountability: isolation permits enforce a two-person rule across issuance, grounding verification, and release; mobile test equipment must be provably on site before any series energizes; and a circuit's own status is a pure reflection of what its windows, permits, series, and jobs are doing. The third is fiscal discipline: every test job carries a customer-approved budget, committed costs accumulate as excavation and splice work is ordered, and invoices apply markup line by line. All endpoints described here are mounted under the `/cable-diagnostics` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the operator's role. A request missing either header, or presenting a role name the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role must be among the roles allowed for the specific endpoint; otherwise the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

Eight roles are declared, with the following exact spellings and responsibilities:

- `SystemAdmin` — the contractor platform operator; registers cable circuits and mobile test units, and drives the logical clock.
- `NetworkPlanner` — the customer-side outage planner; owns outage windows and test jobs, performs customer acceptance of test series and repair splices, and adopts health assessments.
- `TestSupervisor` — the field test lead; starts, suspends, resumes, and completes jobs, creates and energizes test series, evaluates and invalidates them, and raises and reopens fault records.
- `FieldTechnician` — operates the test set under supervision; appends test readings and nothing else.
- `SafetyOfficer` — issues, independently verifies, and releases isolation and grounding permits; the two-person rule is enforced through `X-User-ID` comparisons.
- `FaultCrewLead` — the repair contractor lead; pinpoints faults, runs excavations, and builds splices through curing.
- `DispatchCoordinator` — the fleet dispatcher; reserves, confirms, activates, releases, and cancels equipment assignments, and manages unit maintenance.
- `AssetEngineer` — asset analytics; computes and reviews health assessments and reads trends and invoices.

For every one of these eight roles — `SystemAdmin`, `NetworkPlanner`, `TestSupervisor`, `FieldTechnician`, `SafetyOfficer`, `FaultCrewLead`, `DispatchCoordinator`, and `AssetEngineer` — the value of `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it where a workflow captures an actor (for example, as `issued_by_user_id`, `grounding_verified_by_user_id`, or `released_by_user_id` on an isolation permit, or as `recorded_by_user_id` on a test reading), but it never compares `X-User-ID` against any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; like every server-emitted timestamp, it reads the logical clock of §2.4, never the wall clock.
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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10 when omitted, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and must not be negative. A `limit` or `offset` that is not an integer, or that violates these bounds, is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` counts the filtered result set. Unless a query parameter says otherwise, list results are sorted by `created_at` in ascending order, with ties — common under the logical clock — broken by creation order.

### 2.4. The Logical Clock and Interval Semantics

All temporal decisions in the system are made against a server-side logical clock. On server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time at any point afterwards. The clock advances only when a `SystemAdmin` exercises the test-driving capability that sets it to a supplied `to_iso8601` instant; the supplied instant is unconstrained — it may precede the clock's current value, in which case the clock moves backward — and the capability responds with the clock's new value as `current_utc`. Window eligibility, curing maturity, dig-window containment, trailing-twenty-four-month fault counts, and equipment on-site checks all read this clock.

Timestamp representation is uniform across the API. Every timestamp a client supplies — the outage-window bounds `window_start` and `window_end`, the closure instant `restored_at`, the dig bounds `dig_start` and `dig_end`, the assignment interval `mobilize_at` and `demobilize_at`, and the clock-setting `to_iso8601` — is parsed as an ISO 8601 instant and converted to UTC — an input carrying no explicit offset is read as UTC, and a lowercase `z` suffix is accepted — and every timestamp the server returns, these client-supplied values included, is rendered in the same canonical form as `api_request_timestamp` and `created_at`: UTC ISO 8601 with a `Z` suffix and exactly three fractional digits, with any finer sub-millisecond precision truncated rather than rounded. Client input is therefore never echoed verbatim — a `window_start` sent as `2026-08-10T12:00:00Z` comes back as `2026-08-10T12:00:00.000Z` — and every interval comparison in this document applies to the parsed instants, never to the raw request strings.

Interval endpoints in this domain are deliberate about their edges. An outage window is a half-open interval: `window_start` is inclusive, `window_end` is exclusive, and `window_end` must be strictly later than `window_start`. A dig interval behaves differently for containment than for clock gating: containment treats both `dig_start` and `dig_end` as inclusive, while the check that permits digging to begin is half-open — digging may start at `dig_start` itself but not at `dig_end`. An equipment assignment interval requires `demobilize_at` to be strictly later than `mobilize_at`; assignment activation is permitted from `mobilize_at` onwards with no upper bound, while the on-site check used at energize time treats both `mobilize_at` and `demobilize_at` as inclusive. Wherever a boundary rule exists in this document it is stated in words; boundary equality is allowed exactly where the text says so and nowhere else.

### 2.5. Resource Identity and Common Properties

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits, assigned at creation. All resources except test readings additionally carry `updated_at`, refreshed to the current logical-clock timestamp on every mutation, and `version`, an integer that starts at 1 at creation — where `updated_at` initially equals `created_at` — and increments by one on every mutation of the resource.

Test readings are the single exception, and the exception is explicit: a test reading is an append-only log entry and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from test readings; a reading, once appended, is never modified.

### 2.6. Optimistic Concurrency Control

Exactly two write operations in this API are guarded by optimistic concurrency control, and both reject with the same error. First, creating a health assessment requires the request to carry `expected_circuit_version`, holding the client last observed `version` of the target circuit; if the circuit's current `version` has advanced beyond what the client observed — including advancement caused by an earlier health-assessment creation, which itself bumps the circuit's version — the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). Second, rescheduling a test job requires the request to carry `expected_test_job_version`, holding the client's last observed `version` of the job; a mismatch with the job's current `version` is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field; requests to any other endpoint must not be rejected for want of one.

### 2.7. Validation Pipeline and Error Precedence

Every request passes through a fixed validation pipeline, and a failure at an earlier stage is always reported in preference to a failure at any later stage. The stages, in order, are:

1. **Authentication** — both headers present and the role recognized, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is listed for the endpoint, else `ERR_FORBIDDEN`.
3. **Request shape** — required body fields present, enum members valid, numeric ranges respected: `length_m` a positive integer, `ground_count` at least one, `window_end` strictly after `window_start`, `dig_end` strictly after `dig_start`, `demobilize_at` strictly after `mobilize_at`, `installation_year` between 1950 and 2026 inclusive, `calibrated_velocity_factor` either null or between 0.45 and 0.60 inclusive, `trace_time_us` greater than zero, `applied_voltage_kv` greater than zero, `cost_cents` greater than zero, `approved_budget_cents` greater than zero, `max_test_voltage_kv` greater than zero, `step_index` a non-negative integer; method-conditional reading fields (`tan_delta_e3` required for the VLF methods and forbidden for `PD_MAPPING`; `pd_level_pc` required for `VLF_WITH_PD` and `PD_MAPPING` and forbidden for `VLF_TAN_DELTA`) — these evaluate against the target series' method, so on the reading endpoint they fire only after the series path identifier has resolved; and `retest_of_fault_id` required exactly when `is_retest` is true and forbidden otherwise. Body fields beyond those an endpoint names are ignored. Any violation yields `ERR_INVALID_REQUEST` (HTTP 400).
4. **Existence** — path identifiers are resolved first, validated left to right along the URL, and then body foreign-key references in their declared input order; the first missing reference yields `ERR_NOT_FOUND` (HTTP 404).
5. **Concurrency** — where §2.6 applies, the expected-version field must match the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
6. **State legality** — the target entity must be in an allowed from-state for the requested transition, else `ERR_INVALID_STATE` (HTTP 409). This stage covers, among others: the circuit must be `IN_SERVICE` or `OUTAGE_PENDING` at window approval; the window must be `APPROVED` at job creation and reschedule; the job must be `PLANNED` or `IN_PROGRESS` at permit creation; a retest series may be created only while its linked fault is `REPAIRED`; a fault must be `PINPOINTED`, `EXCAVATING`, or `REPAIRING` at excavation creation; the excavation must be `IN_PROGRESS` at splice creation; the fault must be `EXCAVATING` when splicing starts; the unit must not be `MAINTENANCE` and the job must be `PLANNED` or `IN_PROGRESS` at assignment creation.
7. **Business rules** — evaluated in the following declared order, each with its own error: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`); grounding verification before energize (`ERR_GROUNDING_NOT_VERIFIED`); permit release before job completion (`ERR_PERMIT_NOT_RELEASED`); window start not in the past (`ERR_WINDOW_IN_PAST`); window overlap (`ERR_WINDOW_OVERLAP`); clock alignment with the required active interval (`ERR_WINDOW_NOT_ACTIVE`); dig containment inside the outage (`ERR_DIG_OUTSIDE_OUTAGE`); curing maturity (`ERR_CURING_INCOMPLETE`); corridor containment (`ERR_CORRIDOR_VIOLATION`); dig-window overlap (`ERR_DIG_WINDOW_OVERLAP`); the four-hour unit buffer (`ERR_UNIT_OVERLAP_BUFFER`); unit capability and voltage coverage (`ERR_UNIT_CAPABILITY_MISMATCH`); open assignments blocking maintenance (`ERR_UNIT_HAS_ASSIGNMENTS`); series method membership (`ERR_METHOD_NOT_REQUESTED`); test-voltage tolerance (`ERR_VOLTAGE_MISMATCH`); reading presence at evaluation (`ERR_NO_READINGS`); step completeness at evaluation (`ERR_STEP_INCOMPLETE`); step index range (`ERR_STEP_OUT_OF_RANGE`); step uniqueness (`ERR_DUPLICATE_STEP`); the manual-fault verdict precondition (`ERR_VERDICT_NOT_FAIL`); one fault per series (`ERR_FAULT_ALREADY_RECORDED`); one open permit per job (`ERR_PERMIT_EXISTS`); one open splice per fault (`ERR_SPLICE_EXISTS`); one open excavation per fault (`ERR_EXCAVATION_EXISTS`); one open job per circuit (`ERR_CIRCUIT_BUSY`); equipment on site at energize (`ERR_NO_EQUIPMENT_ON_SITE`); circuit reference uniqueness (`ERR_DUPLICATE_CIRCUIT_REF`); cross-reference consistency (`ERR_CROSS_REFERENCE_MISMATCH`); splice-curing precondition for backfill (`ERR_SPLICE_NOT_CURING`); qualifying re-test for splice acceptance (`ERR_RETEST_REQUIRED`); and finally budget sufficiency (`ERR_BUDGET_EXCEEDED`). A budget failure is therefore reported only after every other applicable check has passed, and a stale-version failure is always reported before any state or business failure on the two concurrency-guarded writes.

Where several of these checks guard the same endpoint, their relative order is stated alongside the workflow in §3. One consequence worth noting: because step-range checking (stage ordering places `ERR_STEP_OUT_OF_RANGE` ahead of `ERR_DUPLICATE_STEP`) precedes duplicate detection, appending a reading whose `step_index` is beyond the series' `step_count` is always answered with `ERR_STEP_OUT_OF_RANGE` even if that index were somehow already occupied.

### 2.8. Precision, Rounding, and Electrical Reference Constants

Every rounding in the system is round half up — a value exactly on the midpoint rounds away from zero. The granularities are fixed per quantity: tan-delta values (expressed in units of one-thousandth) are rounded to one decimal place before any comparison; distances and corridor bounds are rounded to one-tenth of a metre; equipment hours are rounded to one-tenth of an hour; health scores and the penalty aggregate are rounded to one decimal place; all money is carried and rounded to integer cents.

Two electrical reference tables are shared by several workflows. The phase-to-ground reference voltage U0 depends on the circuit's `voltage_class`: 8.7 kV for `KV_15`, 14.4 kV for `KV_25`, 20.3 kV for `KV_35`, and 39.8 kV for `KV_69`. The standard time-domain-reflectometry velocity factor likewise depends on the class: 0.52 for `KV_15`, 0.52 for `KV_25`, 0.52 for `KV_35`, and 0.53 for `KV_69`. A circuit may carry a site-specific override in `calibrated_velocity_factor`; when that field is null, the standard table value is used wherever a calibrated value would have applied.

### 2.9. Segregation of Duties for Safety-Critical Steps

Two-person integrity on the isolation permit is a hard rule, not a convention. The operator who verifies grounding must be a different `X-User-ID` than the operator who issued the permit, and the operator who releases the permit must be a different `X-User-ID` than the operator who verified grounding. Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422). The permit records each actor as it moves: `issued_by_user_id` at issuance, `grounding_verified_by_user_id` at verification, and `released_by_user_id` at release, and the comparisons are made against those recorded identities.

### 2.10. Fiscal Guardrails: Budgets, Committed Costs, and Markups

Every test job is created with a customer-approved spend cap in `approved_budget_cents`. The planning step computes an estimate and refuses to plan a job whose estimate exceeds the cap; later, every excavation order and every repair splice is checked against the same cap before it may be created, with the job's already-committed costs counted in. The running total of committed spend lives on the job as `committed_cost_cents`: it is the sum of `cost_cents` over all of the job's non-cancelled excavation orders plus all repair splices — of any status, including rejected ones — belonging to the job's faults. Creating an excavation order or a splice adds its `cost_cents`; cancelling an excavation order subtracts its `cost_cents`; a rejected splice's cost remains committed, because the work was performed. Any check failure in this area is reported as `ERR_BUDGET_EXCEEDED` (HTTP 422). Invoicing applies a markup line by line — never to a pre-summed subtotal — and the full invoice composition is described with the job workflow in §3.3.

## 3. Business Logic & Workflows

### 3.1. Circuit Registration and Reference Data

A `SystemAdmin` registers each cable circuit with a contractor-side `circuit_ref`, a `voltage_class`, the circuit's `length_m` in metres, its `installation_year`, and optionally a site-calibrated `calibrated_velocity_factor`. The `circuit_ref` must be unique across all registered circuits; a duplicate is rejected with `ERR_DUPLICATE_CIRCUIT_REF`. The `voltage_class` must be one of `KV_15`, `KV_25`, `KV_35`, or `KV_69`, and that single choice selects both the U0 reference voltage and the standard velocity factor from the tables in §2.8. The optional `calibrated_velocity_factor`, when present, must lie between 0.45 and 0.60 inclusive; it exists because buried cable occasionally propagates measurably slower or faster than the class standard, and fault pinpointing (§3.7) can be asked to use it.

A newly registered circuit begins in `IN_SERVICE` status with every counter at zero: `unresolved_fault_count`, `resolved_fault_count_24m`, `approved_outage_minutes_total`, and `splice_count` all start at 0, while `current_health_index` and `current_health_band` remain null until the first health assessment is adopted, and `replacement_recommended` starts false. From then on the circuit's status is never set directly; it is a pure reflection of child activity through the cyclic chain `IN_SERVICE` → `OUTAGE_PENDING` → `DE_ENERGIZED` → `GROUNDED` → `UNDER_TEST` → `TEST_COMPLETE` → `RESTORING` → `IN_SERVICE`, driven by window approval, permit issuance, grounding verification, series energization, job evaluation, permit release, and window closure respectively — the individual hops are narrated in §3.2 through §3.6. The trailing counter `resolved_fault_count_24m` counts the circuit's faults that reached `CLOSED_VERIFIED` with a `closed_at` lying within the trailing twenty-four months of the logical clock — a `closed_at` falling exactly twenty-four months before the clock still counts — and it is recomputed whenever a fault closes or reopens.

### 3.2. Outage Windows: Request, Approval, and Restoration

Work on a de-energized circuit begins when a `NetworkPlanner` requests an outage window for a circuit, supplying `circuit_id`, a `kind` of `PLANNED_DIAGNOSTIC`, `EMERGENCY_FAULT`, or `REPAIR_RESTORE`, and the half-open bounds `window_start` and `window_end`. The new window lands in `REQUESTED` and its `duration_minutes` is computed immediately as the whole minutes between the two bounds; `restored_at` remains null until closure, `estimated_charge_cents` starts at zero and is populated only at approval, and `overrun_minutes` and `overrun_charge_cents` remain at zero until the actual overrun is known. Two temporal guards apply at request time, in this order: the window's start must not precede the logical clock — a past-start window is rejected with `ERR_WINDOW_IN_PAST` — and the half-open interval must not overlap any existing window of the same circuit that is still in `REQUESTED`, `APPROVED`, or `ACTIVE` status, with pure adjacency (one window's start equal to another's end) explicitly permitted; an offending overlap is rejected with `ERR_WINDOW_OVERLAP`.

Approval is the `NetworkPlanner`'s second step and is allowed only while the circuit is `IN_SERVICE` or `OUTAGE_PENDING` — approval against any other circuit status fails with `ERR_INVALID_STATE`. An approved window moves to `APPROVED` and has three immediate consequences. Its `duration_minutes` is added to the circuit's `approved_outage_minutes_total`. A provisional exposure figure is stored in the window's `estimated_charge_cents`, computed with the estimate variant of the overrun charge: the estimated overrun is ten percent of `duration_minutes` rounded up to a whole minute, and that estimate is then priced with the tiered formula below. And the circuit itself transitions `IN_SERVICE` → `OUTAGE_PENDING`, refreshing the circuit's `updated_at` and `version`.

The overrun charge, used both provisionally at approval and definitively at closure, works as follows. A grace period of fifteen minutes applies: only overrun minutes beyond the grace are chargeable, so an overrun of fifteen minutes or less costs nothing. Chargeable minutes are then priced marginally across three tiers — the first sixty chargeable minutes at 400 cents per minute, the next one hundred twenty chargeable minutes at 650 cents per minute, and any chargeable minutes beyond one hundred eighty at 900 cents per minute. Windows of kind `EMERGENCY_FAULT` carry a multiplier of 1.25 applied inside every tier; all other kinds use a multiplier of 1.0. The rounding order is pinned: each tier's segment charge — its tier minutes multiplied by its rate multiplied by the multiplier — is rounded half-up to whole cents on its own, and the total charge is the sum of the three already-rounded segments.

Activation requires the logical clock to satisfy the window's half-open bounds — at or after `window_start` and strictly before `window_end` — or the attempt is rejected with `ERR_WINDOW_NOT_ACTIVE`; a successful activation moves the window from `APPROVED` to `ACTIVE`. Closure is the restoration act: the window must be `ACTIVE` (else `ERR_INVALID_STATE`), and only then is the `NetworkPlanner`-supplied `restored_at` compared against `window_start` — a `restored_at` preceding `window_start` is a plain `ERR_INVALID_REQUEST`, so a closure attempt on a non-`ACTIVE` window reports `ERR_INVALID_STATE` even when its `restored_at` also precedes `window_start`. A successful closure moves the window from `ACTIVE` to `CLOSED`. At closure the system stores `restored_at`, computes `overrun_minutes` as zero when restoration happened at or before `window_end` and otherwise as the overshoot beyond `window_end` converted to whole minutes with any partial minute rounded up, and prices the actual overrun into `overrun_charge_cents` using the same tiered formula with the recorded overrun rather than the estimate. The window's `duration_minutes` is subtracted from the circuit's `approved_outage_minutes_total`, and then a three-hop cascade fires. Hop one touches the circuit: if the circuit is `RESTORING` it returns `RESTORING` → `IN_SERVICE`; otherwise, if it is `OUTAGE_PENDING` and no other window of the circuit remains in `APPROVED` or `ACTIVE`, it returns `OUTAGE_PENDING` → `IN_SERVICE`. Hop two touches the fleet: every equipment assignment belonging to this circuit's jobs that is `CONFIRMED` or `ACTIVE` is moved to `RELEASED`. Hop three settles the hours: each released assignment subtracts its stored `duration_hours` from its unit's `committed_hours`, and a mobile unit left with no remaining assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` transitions `ASSIGNED` → `AVAILABLE`.

Cancellation is available from `REQUESTED` — a plain transition to `CANCELLED` with no side effects — and from `APPROVED`, where it is refused with `ERR_INVALID_STATE` if any non-terminal test job still references the window. Cancelling an `APPROVED` window subtracts its `duration_minutes` from the circuit's `approved_outage_minutes_total` and, when no other window of the circuit remains in `APPROVED` or `ACTIVE`, returns the circuit `OUTAGE_PENDING` → `IN_SERVICE`.

### 3.3. Planning and Steering a Test Job

A `NetworkPlanner` creates a diagnostics job by naming `circuit_id` and `outage_window_id`, listing the `requested_methods` as a non-empty list whose entries are drawn from `VLF_TAN_DELTA`, `VLF_WITH_PD`, and `PD_MAPPING` — duplicate entries are accepted, and each listed entry is charged its own method fee at planning — setting the customer-approved `approved_budget_cents`, and optionally setting `use_temperature_correction` (default false). Creation is gated by four business checks, evaluated after the request-shape, existence, and window-state checks: the referenced window must be `APPROVED` (else `ERR_INVALID_STATE`); the open-splice existence rule is also enforced at job creation — a fault of this circuit with a splice still in `PLANNED`, `SPLICING`, `CURING`, or `COMPLETED` blocks it with `ERR_SPLICE_EXISTS`; the circuit must not already carry a non-terminal test job (else `ERR_CIRCUIT_BUSY`); and the window must actually belong to the circuit named in the body, a mismatch surfacing as `ERR_CROSS_REFERENCE_MISMATCH` (HTTP 422). The checks fire in that order — window state, splice existence, circuit busyness, then cross-reference consistency — so a planner who picked a window of the wrong circuit and also has a busy circuit learns about the busyness first. A created job starts in `DRAFT` with `estimate_cents` still null and `committed_cost_cents` at zero.

Planning converts intent into a priced commitment. The estimate is built from a subtotal of 180,000 cents callout plus 125 cents per metre of the circuit's `length_m` — that per-metre product rounded half-up to whole cents — plus a fee per requested method: 95,000 cents for `VLF_TAN_DELTA`, 145,000 cents for `VLF_WITH_PD`, and 120,000 cents for `PD_MAPPING`. The complexity surcharge is then keyed strictly on this pre-surcharge subtotal: a subtotal strictly greater than 400,000 cents makes the job COMPLEX and carries a twelve percent surcharge; anything else, including a subtotal of exactly 400,000 cents, is STANDARD with a six percent surcharge. The estimate stored into `estimate_cents` is the subtotal multiplied by one plus the applicable rate, rounded half-up to whole cents. If that estimate exceeds `approved_budget_cents`, planning is rejected with `ERR_BUDGET_EXCEEDED` and the job stays in `DRAFT`; otherwise the estimate is stored and the job moves to `PLANNED`.

Rescheduling moves a `PLANNED` job to a different window. The request carries the replacement `outage_window_id` together with the OCC field `expected_test_job_version` described in §2.6, and the checks fire in a fixed order: the stale-version rejection (`ERR_STALE_VERSION`) first, then the replacement window's `APPROVED` state (`ERR_INVALID_STATE`), then the open-splice existence rule (`ERR_SPLICE_EXISTS`), and finally same-circuit consistency between the replacement window and the job's circuit (`ERR_CROSS_REFERENCE_MISMATCH`). A successful reschedule replaces the job's `outage_window_id` outright — supersede semantics, with no history kept on the job — and increments the job's `version` by one.

Fieldwork is the `TestSupervisor`'s domain. Starting a job requires its outage window to be `ACTIVE`, else `ERR_WINDOW_NOT_ACTIVE`, and moves the job `PLANNED` → `IN_PROGRESS`. Suspension moves `IN_PROGRESS` → `SUSPENDED` with no preconditions, and resumption returns `SUSPENDED` → `IN_PROGRESS` under the same active-window requirement. Resumption also re-evaluates the automatic EVALUATION gate described next, so a job resumed while every one of its series is already terminal and every one of its faults already `CLOSED_VERIFIED` lands directly in `EVALUATION`. The job's most important transition is one nobody invokes: the moment at least one test series exists for the job, every series of the job sits in a terminal state (`ACCEPTED` or `INVALID`), and every fault of the job is `CLOSED_VERIFIED`, the job moves itself `IN_PROGRESS` → `EVALUATION`, and the circuit follows `UNDER_TEST` → `TEST_COMPLETE`. Completion of an `EVALUATION` job is gated on the job's isolation permit having reached `RELEASED` — completing earlier is rejected with `ERR_PERMIT_NOT_RELEASED` — and lands the job in `COMPLETED`. Either a `NetworkPlanner` or a `TestSupervisor` may abort a job while it is `DRAFT` or `PLANNED`; abortion lands the job in `ABORTED` and cancels every equipment assignment of the job still in `RESERVED` or `CONFIRMED`, subtracting each cancelled assignment's `duration_hours` from its unit's `committed_hours`.

The job's invoice is computed on read, never stored, and returns four figures: `estimate_cents`, `excavation_total_cents`, `splice_total_cents`, and `invoice_total_cents`. Each billable excavation line is the excavation's `cost_cents` marked up by 8.5 percent and rounded half-up to whole cents, summed over the job's non-cancelled excavation orders; each billable splice line is computed the same way over all splices of the job's faults regardless of splice status. The invoice total is the stored estimate plus the sum of the excavation lines plus the sum of the splice lines; for a job that was never planned, `estimate_cents` is null and contributes zero to the total. The rounding order is pinned per line: markup is applied and rounded on each line individually and only then summed — summing costs first and marking up afterwards yields different cents, so on lines of 100,040 and 200,040 cents the specified order produces 325,586 cents of marked-up work where the forbidden order would produce 325,587.

### 3.4. Isolation, Grounding, and Permit Release

Before anything may be energized, a `SafetyOfficer` drafts an isolation permit for a job that is `PLANNED` or `IN_PROGRESS` — drafting against any other job state fails with `ERR_INVALID_STATE` — supplying `test_job_id`, the switching and isolation `isolation_points` (at least one entry), and the `ground_count` of applied safety grounds (at least one). At most one permit that has not reached `RELEASED` may exist per job, and that uniqueness check runs after the job-state check; a second open permit is rejected with `ERR_PERMIT_EXISTS`. The draft permit starts in `DRAFT`.

Issuance moves the permit `DRAFT` → `ISSUED`, captures the acting officer into `issued_by_user_id`, and pulls the circuit `OUTAGE_PENDING` → `DE_ENERGIZED`. Grounding verification is an independent act: the verifying `X-User-ID` must differ from `issued_by_user_id`, and a same-person attempt is rejected with `ERR_SEGREGATION_OF_DUTIES`; a successful verification moves the permit `ISSUED` → `GROUNDING_VERIFIED`, records `grounding_verified_by_user_id`, and advances the circuit `DE_ENERGIZED` → `GROUNDED`. Release comes at the end of testing and is doubly gated: the job must already be in `EVALUATION` — checked first, with `ERR_INVALID_STATE` if not — and the releasing officer must differ from the grounding verifier, with a same-person attempt rejected as `ERR_SEGREGATION_OF_DUTIES`. Release moves the permit `GROUNDING_VERIFIED` → `RELEASED`, records `released_by_user_id`, and moves the circuit `TEST_COMPLETE` → `RESTORING`, leaving the final return to `IN_SERVICE` to the window closure described in §3.2.

### 3.5. Fleet Scheduling and Equipment Commitments

A `SystemAdmin` registers each mobile test unit with a fleet-unique `unit_code` — a duplicate code is a plain request failure, `ERR_INVALID_REQUEST` — a non-empty `capabilities` subset drawn from `VLF`, `PD`, and `TDR`, and the unit's output ceiling `max_test_voltage_kv`. New units start `AVAILABLE` with `committed_hours` at 0.0.

Reserving a unit for a job is the `DispatchCoordinator`'s act, supplying `mobile_unit_id`, `test_job_id`, and the assignment interval `mobilize_at` to `demobilize_at`. The reservation is gated by three business checks in a fixed order after the request-shape, existence, and state checks: the unit must not be in `MAINTENANCE` and the job must be `PLANNED` or `IN_PROGRESS` (both are `ERR_INVALID_STATE` failures); then the four-hour buffer rule — the new interval conflicts with any non-terminal assignment of the same unit unless a gap of at least four hours separates them in the applicable direction, meaning the new `mobilize_at` is at least four hours after the existing assignment's `demobilize_at` or the existing assignment's `mobilize_at` is at least four hours after the new `demobilize_at`, with a gap of exactly four hours permitted and anything tighter rejected as `ERR_UNIT_OVERLAP_BUFFER`; then capability coverage, where `VLF_TAN_DELTA` requires the `VLF` capability, `VLF_WITH_PD` requires both `VLF` and `PD`, and `PD_MAPPING` requires `PD`, and additionally the unit's `max_test_voltage_kv` must reach at least one and a half times the U0 of the job circuit's voltage class, with any shortfall rejected as `ERR_UNIT_CAPABILITY_MISMATCH`. A created assignment lands in `RESERVED`; its `duration_hours` is computed as the span from `mobilize_at` to `demobilize_at`, converted from seconds to hours and rounded half-up to one decimal place; that same amount is added to the unit's `committed_hours`; and the unit transitions `AVAILABLE` → `ASSIGNED`.

The assignment lifecycle then runs `RESERVED` → `CONFIRMED` → `ACTIVE` → `RELEASED`, with cancellation available from `RESERVED` or `CONFIRMED`. Confirmation has no preconditions. Activation requires the logical clock to have reached `mobilize_at` — nothing more, there is no upper bound — and an early activation is rejected with `ERR_WINDOW_NOT_ACTIVE`. Release is the normal end of an `ACTIVE` assignment, and also happens to `CONFIRMED` assignments by system cascade when the outage window closes (§3.2). Cancellation ends `RESERVED` or `CONFIRMED` assignments, whether by the dispatcher directly or by cascade when a job is aborted. Every release and every cancellation subtracts exactly the assignment's stored `duration_hours` from the unit's `committed_hours` — the same value that was added at reservation, so repeated cycles cannot drift — and whenever a unit's last assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` leaves that set, the unit returns `ASSIGNED` → `AVAILABLE`. The unit's `committed_hours` at any moment is the sum of `duration_hours` over its assignments still in `RESERVED`, `CONFIRMED`, or `ACTIVE`, rounded half-up to one-tenth of an hour.

Maintenance is reserved for idle units: sending a unit to maintenance while it still holds an assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` is rejected with `ERR_UNIT_HAS_ASSIGNMENTS` — this open-assignments check fires before the unit-state check, so an `ASSIGNED` unit, which always holds open assignments, is answered with `ERR_UNIT_HAS_ASSIGNMENTS` rather than `ERR_INVALID_STATE` — and a maintained unit moves `AVAILABLE` → `MAINTENANCE` until the dispatcher returns it to service, `MAINTENANCE` → `AVAILABLE`.

### 3.6. Test Series Execution, Readings, and Verdicts

A `TestSupervisor` creates a test series on a job that is `IN_PROGRESS` — creation against any other job state is `ERR_INVALID_STATE` — supplying `test_job_id`, the `method`, the intended `test_voltage_kv`, and, for acceptance re-tests, `is_retest` (which defaults to false) set to true together with `retest_of_fault_id`. The state-stage gates fire first: besides the job being `IN_PROGRESS`, a re-test may only be created while its linked fault is `REPAIRED` (a violation is likewise `ERR_INVALID_STATE`), and creating it moves that fault `REPAIRED` → `RETESTING`. The remaining checks then apply in order: the `method` must be a member of the job's `requested_methods` (else `ERR_METHOD_NOT_REQUESTED`); and for the two VLF methods the `test_voltage_kv` must lie within five percent — in either direction, boundaries included — of one and a half times the U0 of the circuit's voltage class, with violations rejected as `ERR_VOLTAGE_MISMATCH` (HTTP 422). The new series starts in `SETUP`, and its `step_count` is derived from the method: three steps for `VLF_TAN_DELTA` and `VLF_WITH_PD`, where steps 0, 1, and 2 correspond to applied levels of one-half, one times, and one-and-a-half times U0, and a single step for `PD_MAPPING`. Both verdict fields — `verdict_as_tested`, `verdict_temperature_corrected`, and with them the official `verdict` — and both maxima remain null until evaluation. Sheath integrity testing is not supported anywhere in the system; no method value exists for it.

Energizing a `SETUP` series is allowed only when three gates pass in sequence: the job must be `IN_PROGRESS`; the job's isolation permit must have reached `GROUNDING_VERIFIED` (else `ERR_GROUNDING_NOT_VERIFIED`); and there must exist an equipment assignment for the job in `CONFIRMED` or `ACTIVE` whose interval brackets the logical clock — `mobilize_at` at or before now and `demobilize_at` at or after now (else `ERR_NO_EQUIPMENT_ON_SITE`). Energizing moves the series `SETUP` → `ENERGIZING` and the circuit `GROUNDED` → `UNDER_TEST`.

A `FieldTechnician` then appends readings, one per call, each carrying `step_index`, `applied_voltage_kv`, and `ambient_temp_c`, plus the method-conditional measurement fields: `tan_delta_e3` is required for the VLF methods and forbidden for `PD_MAPPING`; `pd_level_pc` is required for `VLF_WITH_PD` and `PD_MAPPING` and forbidden for `VLF_TAN_DELTA`; `pd_location_m` is optional and meaningful for `PD_MAPPING` only — it is nevertheless accepted and stored on any method's readings, never required nor forbidden, and used in no computation, and measurement fields not supplied are stored and returned as null. Appending is legal only while the series is `ENERGIZING` or `LOGGING`; against any other series state it fails with `ERR_INVALID_STATE`. The `step_index` is zero-based, must be below the series' `step_count` (else `ERR_STEP_OUT_OF_RANGE`, HTTP 422), and must not repeat a step already recorded for the series (else `ERR_DUPLICATE_STEP`) — and as §2.7 notes, the range check fires before the duplicate check. The appending operator is recorded as `recorded_by_user_id`. The very first reading appended to a series moves it `ENERGIZING` → `LOGGING`; the reading log is append-only thereafter.

Evaluation by the `TestSupervisor` — invocable from `ENERGIZING` or `LOGGING` — requires at least one reading (else `ERR_NO_READINGS` — which always fires for a series still in `ENERGIZING`, since the first reading would already have moved it to `LOGGING`) and then requires every step from 0 through `step_count` minus one to have a reading (else `ERR_STEP_INCOMPLETE`), in that order. Evaluation computes two independent verdict bases and stores both. For the as-tested basis, each reading's `tan_delta_e3` is first rounded half-up to one decimal place and the rounded raw values are compared. For the temperature-corrected basis, each reading's raw tan-delta is multiplied by a correction factor — one plus one-hundredth of the difference between 20 and the reading's `ambient_temp_c` in degrees Celsius, clamped so the factor never falls below 0.9 and never exceeds 1.1 — and the product is rounded half-up to one decimal place before any comparison; identical raw data can therefore flip outcomes between the two bases, as when a reading of 88.0 taken at 35 degrees Celsius corrects to 79.2. Both bases then apply the same threshold logic. The tan-delta part, which applies to `VLF_TAN_DELTA` and `VLF_WITH_PD`: the part verdict is `FAIL` when the maximum rounded tan-delta across the series' readings reaches or exceeds 80.0; otherwise `FAIL` when the difference between the step-2 and step-0 rounded values reaches or exceeds 12.0 (the tip-up check); otherwise `PASS` when the maximum rounded value is strictly below 5.0; otherwise `MONITOR`. The partial-discharge part, which applies to `VLF_WITH_PD` and `PD_MAPPING`: `FAIL` when the maximum `pd_level_pc` reaches or exceeds 2,000 picocoulombs; otherwise `MONITOR` when it reaches or exceeds 500; otherwise `PASS`. The basis verdict is the worst of the part verdicts that apply to the method, where `PASS` is better than `MONITOR` and `MONITOR` is better than `FAIL`. The official `verdict` of the series is the temperature-corrected basis when the job's `use_temperature_correction` is true and the as-tested basis otherwise, and `verdict_as_tested` and `verdict_temperature_corrected` remain available for inspection regardless. Evaluation also stores `max_tan_delta_e3` — the maximum rounded tan-delta across readings, null for `PD_MAPPING` — and `max_pd_pc` — the maximum PD level across readings, null for `VLF_TAN_DELTA` — and moves the series to `EVALUATED`. When the official verdict is `FAIL`, the system immediately creates a fault record in `SUSPECTED` for the series and increments the circuit's `unresolved_fault_count` by one.

Customer acceptance of an `EVALUATED` series is the `NetworkPlanner`'s act and moves it to `ACCEPTED`; when the accepted series is a passing re-test, nothing further happens to the fault at this point — splice acceptance in §3.8 is the separate gate that closes it. Invalidation by the `TestSupervisor`, carrying a free-text `reason`, moves an `EVALUATED` series to `INVALID`, and when the invalidated series was a re-test, its linked fault falls back `RETESTING` → `REPAIRED`.

### 3.7. Fault Records and Pinpointing

Fault records arise in exactly two ways. The automatic path fires at evaluation when the official verdict is FAIL, as described above. The manual path lets a `TestSupervisor` raise a fault from a series by naming `test_series_id` — an engineering-judgement escalation permitted only when the series' verdict is `MONITOR`: a `PASS` series cannot raise a fault (`ERR_VERDICT_NOT_FAIL`), and a `FAIL` series already produced its fault automatically. Only one fault may ever exist for a given series (else `ERR_FAULT_ALREADY_RECORDED`), and the verdict precondition is checked before the uniqueness check. Either way, the new fault starts `SUSPECTED`, inherits its `test_job_id` from the originating series, and increments the circuit's `unresolved_fault_count` by one.

Pinpointing is the `FaultCrewLead`'s craft and is available from `SUSPECTED` — and, for warranty work, from `REOPENED`, where it recomputes everything. Until a fault's first pinpoint, its `pinpoint_method`, `trace_time_us`, `velocity_factor_used`, `pinpointed_distance_m`, `alternate_distance_m`, `corridor_start_m`, and `corridor_end_m` are all null. The pinpoint request carries the TDR `trace_time_us` time-of-flight in microseconds, the `pinpoint_method` (`PULSE_ECHO` or `ARC_REFLECTION`), and an optional `use_calibrated_velocity` flag. The one-way distance to the fault is the velocity factor multiplied by the propagation speed of 300 metres per microsecond multiplied by the trace time, divided by two, rounded half-up to one-tenth of a metre. Two velocity factors are always in play: the standard factor from the §2.8 class table, and the calibrated factor — the circuit's `calibrated_velocity_factor` when that field is non-null, falling back to the standard factor when it is null. The selected factor is the calibrated one when `use_calibrated_velocity` is true and the standard one otherwise; `velocity_factor_used` records which factor was actually applied, `pinpointed_distance_m` holds the selected-variant distance, and `alternate_distance_m` holds the distance under the other variant — the two genuinely differ, so on a `KV_15` circuit a twenty-microsecond trace yields 1,560.0 metres at the standard factor against 1,500.0 metres at a calibrated factor of 0.50. The dig corridor is then built symmetrically: its half-width is the larger of 5.0 metres and ten percent of the pinpointed distance rounded half-up to one-tenth of a metre, and `corridor_start_m` and `corridor_end_m` are the pinpointed distance minus and plus that half-width respectively, each rounded half-up to one-tenth of a metre after the subtraction or addition. Pinpointing moves the fault to `PINPOINTED`.

From there the fault's progress is driven entirely by its children: the linked excavation starting moves it `PINPOINTED` → `EXCAVATING`; the splice starting moves it `EXCAVATING` → `REPAIRING`; the splice finishing curing moves it `REPAIRING` → `REPAIRED`; the creation of a re-test series naming it moves it `REPAIRED` → `RETESTING`; invalidation of that re-test returns it `RETESTING` → `REPAIRED`; and acceptance of the splice moves it `RETESTING` → `CLOSED_VERIFIED`. Closure is a rich event: `closed_at` is set to the logical clock, the circuit's `unresolved_fault_count` is decremented by one, `resolved_fault_count_24m` is recomputed, the circuit's `splice_count` is incremented by one, and if the job's evaluation gates are now satisfied — every series terminal and every fault closed — the job moves `IN_PROGRESS` → `EVALUATION` as described in §3.3. A `TestSupervisor` may also reopen a `CLOSED_VERIFIED` fault when a warranty failure appears; reopening clears `closed_at` to null, increments `unresolved_fault_count` by one, recomputes `resolved_fault_count_24m`, and lands the fault in `REOPENED`, from which the pinpoint-excavate-repair-retest loop runs again.

### 3.8. Excavation, Splice Repair, and Customer Acceptance

Once a fault is pinpointed, a `FaultCrewLead` raises an excavation order with `fault_record_id`, the dig centreline `target_location_m`, the dig interval `dig_start` to `dig_end`, the municipal `permit_ref`, and the contractor's `cost_cents`. Creation runs a six-deep gauntlet after the request-shape and existence checks, in this exact order: the fault must be `PINPOINTED`, `EXCAVATING`, or `REPAIRING` (else `ERR_INVALID_STATE`); the dig interval must be contained in the outage window of the fault's job with both edges inclusive — `dig_start` at or after `window_start` and `dig_end` at or before `window_end` (else `ERR_DIG_OUTSIDE_OUTAGE`); the `target_location_m` — compared exactly as supplied, with no rounding applied to it — must lie within the fault's corridor from `corridor_start_m` to `corridor_end_m`, inclusive of both bounds (else `ERR_CORRIDOR_VIOLATION`); the dig interval must not overlap, on half-open comparison, the dig interval of any other non-cancelled excavation of the same fault (else `ERR_DIG_WINDOW_OVERLAP`); no excavation order that has not been cancelled may already exist for the fault (else `ERR_EXCAVATION_EXISTS`); and the budget check — `estimate_cents` plus `committed_cost_cents` plus the new `cost_cents` must not exceed `approved_budget_cents` (else `ERR_BUDGET_EXCEEDED`). A created order starts in `DRAFT` and immediately adds its `cost_cents` to the job's `committed_cost_cents`.

The order's lifecycle then runs through municipal and field steps. Marking the municipal permit granted moves `DRAFT` → `PERMITTED`. Starting the dig requires the logical clock inside the dig interval on half-open terms — at or after `dig_start` and strictly before `dig_end` — and simultaneously requires the job's outage window to be `ACTIVE`, with either failure rejected as `ERR_WINDOW_NOT_ACTIVE`; starting moves the order `PERMITTED` → `IN_PROGRESS` and the fault `PINPOINTED` → `EXCAVATING`. Backfilling is permitted only once a repair splice referencing this excavation exists in `CURING` or `COMPLETED` status (else `ERR_SPLICE_NOT_CURING`) and moves the order `IN_PROGRESS` → `BACKFILLED`. Cancellation is available from `DRAFT` or `PERMITTED`, lands the order in `CANCELLED`, and subtracts its `cost_cents` from the job's `committed_cost_cents`.

The splice itself is created against an `IN_PROGRESS` excavation — any other excavation state is `ERR_INVALID_STATE` — with `fault_record_id`, `excavation_order_id`, a `splice_type` of `HEAT_SHRINK`, `COLD_SHRINK`, or `PREMOLDED`, and its `cost_cents`. After the state check, creation is gated by the open-splice uniqueness rule — no splice of this fault may already exist in `PLANNED`, `SPLICING`, `CURING`, or `COMPLETED` (else `ERR_SPLICE_EXISTS`) — then by cross-reference consistency, where the referenced excavation's `fault_record_id` must equal the splice's own `fault_record_id` (else `ERR_CROSS_REFERENCE_MISMATCH`, HTTP 422), and finally by the same budget formula used for excavations (`ERR_BUDGET_EXCEEDED`). A created splice starts in `PLANNED` and adds its `cost_cents` to the job's committed total.

Splice work proceeds `PLANNED` → `SPLICING` → `CURING` → `COMPLETED`. Starting the splice requires the fault to be `EXCAVATING` (else `ERR_INVALID_STATE`) and moves the fault `EXCAVATING` → `REPAIRING`. Beginning the cure stamps `cure_started_at` with the logical clock. Finishing the cure is allowed only once at least twenty-four hours have elapsed since `cure_started_at` — finishing at exactly the twenty-four-hour mark is permitted — and an early attempt is rejected with `ERR_CURING_INCOMPLETE`; finishing stamps `completed_at` and moves the fault `REPAIRING` → `REPAIRED`, which is the state that unlocks re-test series creation in §3.6.

Customer acceptance of the repair is the `NetworkPlanner`'s final gate and requires a qualifying re-test: a test series whose `retest_of_fault_id` names the splice's fault, whose status is `ACCEPTED`, whose official verdict is `PASS`, and whose `created_at` is strictly after the splice's `completed_at` — a re-test created at the same instant does not qualify, and the absence of a qualifying re-test rejects acceptance with `ERR_RETEST_REQUIRED`. Acceptance moves the splice `COMPLETED` → `ACCEPTED` and the fault `RETESTING` → `CLOSED_VERIFIED`, firing the full closure cascade of §3.7. Rejection — the workmanship remedy — moves the splice `COMPLETED` → `REJECTED` and reopens the fault from `REPAIRED` or `RETESTING` into `REOPENED`, while the splice's `cost_cents` remains committed to the job.

### 3.9. Health Assessment, Trending, and Replacement Planning

An `AssetEngineer` computes a health assessment for a circuit by naming `circuit_id`, a `basis` of `FORMAL` or `PROVISIONAL`, and the OCC field `expected_circuit_version` (§2.6). The basis selects which of the circuit's jobs' series feed the score: `FORMAL` counts only series in `ACCEPTED`, while `PROVISIONAL` counts series in `EVALUATED` or `ACCEPTED`, so identical raw data can score lower on the provisional basis — 96.2 formally against 75.2 provisionally, for instance, when a tan-delta reading of 50.0 sits in a still-unevaluated-by-the-customer series. The score aggregates four penalties into `penalty_components`, an object holding `td_pen`, `pd_pen`, `fault_pen`, and `age_pen`. The tan-delta penalty takes the maximum of `max_tan_delta_e3` over the included series — series whose value is null are simply excluded, and if none qualify the metric is treated as empty — and maps it: below 5.0 to 0 points; at least 5.0 but below 20 to 20 points; at least 20 but below 80 to 60 points; 80 or above to 100 points; an empty set contributes 0. The partial-discharge penalty does the same over `max_pd_pc`: below 100 to 0; at least 100 but below 500 to 25; at least 500 but below 2,000 to 55; 2,000 or above to 100; an empty set contributes 0. The fault penalty is the lesser of 100 and twenty-five times the circuit's `unresolved_fault_count` plus ten times its `resolved_fault_count_24m`. The age penalty uses the calendar year of the logical clock minus `installation_year`: circuits at most twenty-five years old incur nothing, each further year adds five points, and the total is capped at 100. The aggregate penalty is thirty-five percent of the tan-delta penalty plus thirty percent of the partial-discharge penalty plus twenty percent of the fault penalty plus fifteen percent of the age penalty, summed at full precision and rounded half-up to one decimal place exactly once — per-component rounding is never applied. The `health_index_score` is then one hundred minus that penalty, rounded half-up to one decimal place, with higher scores meaning healthier cable. The `band` is `GOOD` for a score of eighty or above, `FAIR` for sixty or above but below eighty, `POOR` for forty or above but below sixty, and `CRITICAL` below forty; the `recommended_action` is band-mapped — `GOOD` to `NONE`, `FAIR` to `MONITOR`, `POOR` to `PLAN_REPLACEMENT`, and `CRITICAL` to `URGENT_REPLACEMENT`.

Creation itself is a lifecycle event: the new assessment lands in `COMPUTED`, any existing assessment of the same circuit in `COMPUTED`, `REVIEWED`, or `ADOPTED` is moved to `SUPERSEDED` with the new assessment's `supersedes_id` recording which assessment it replaced — null when there was none — and the circuit's `version` is incremented by one, which is precisely why the creation is concurrency-guarded. Engineering review by an `AssetEngineer` moves `COMPUTED` → `REVIEWED`. Adoption by the `NetworkPlanner` moves `REVIEWED` → `ADOPTED` and writes the assessment onto the circuit: `current_health_index` takes the score, `current_health_band` takes the band, and `replacement_recommended` is recomputed as true exactly when the band is `CRITICAL`, or when the band is `POOR` and the circuit's `unresolved_fault_count` is at least two. The same recommendation flag is also refreshed whenever the fault counts change, so a circuit with a `POOR` band can flip to recommended on the strength of new faults alone. When a still-later assessment supersedes an adopted one, the circuit simply keeps its last adopted values until the next adoption lands. For replacement planning, a `NetworkPlanner` or `AssetEngineer` can read the circuit's trend: its adopted assessments ordered oldest to newest as `points`, together with the `circuit_id` and the current `replacement_recommended` flag.

## 4. Endpoint Definitions

All endpoints are mounted under `/cable-diagnostics`. Endpoints that create a new resource respond with HTTP 201; reads, lifecycle actions, and computed views respond with HTTP 200. Request payloads, preconditions, and side effects are defined by the narratives of §2 and §3; this table is a locator and role reference only. The list filters named in the table match exactly, and a filter value that matches nothing simply yields an empty page rather than an error; the `replacement_recommended` circuit filter accepts `true` or `false` case-insensitively and is ignored for any other value. "All roles" means all eight roles enumerated in §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /cable-diagnostics/_clock/set_current_utc | Set the logical clock to the supplied `to_iso8601`; returns `current_utc` | SystemAdmin |
| POST | /cable-diagnostics/circuits | Register a cable circuit | SystemAdmin |
| GET | /cable-diagnostics/circuits/{id} | Get a circuit | All roles |
| GET | /cable-diagnostics/circuits | List circuits; filters `status`, `voltage_class`, `replacement_recommended`, plus `limit`, `offset` | All roles |
| GET | /cable-diagnostics/circuits/{id}/outage-windows | Windows of a circuit | All roles |
| GET | /cable-diagnostics/circuits/{id}/test-jobs | Jobs of a circuit | All roles |
| GET | /cable-diagnostics/circuits/{id}/health-assessments | Assessments of a circuit, all statuses including `SUPERSEDED` | All roles |
| GET | /cable-diagnostics/circuits/{id}/trend | Replacement-planning trend: adopted assessments oldest to newest plus current recommendation | NetworkPlanner, AssetEngineer |
| POST | /cable-diagnostics/outage-windows | Request an outage window | NetworkPlanner |
| GET | /cable-diagnostics/outage-windows/{id} | Get a window | All roles |
| GET | /cable-diagnostics/outage-windows | List windows; filters `circuit_id`, `status`, plus `limit`, `offset` | All roles |
| GET | /cable-diagnostics/outage-windows/{id}/test-jobs | Jobs referencing a window | All roles |
| POST | /cable-diagnostics/outage-windows/{id}/approve | Approve a requested window | NetworkPlanner |
| POST | /cable-diagnostics/outage-windows/{id}/activate | Activate an approved window; clock must be inside | NetworkPlanner |
| POST | /cable-diagnostics/outage-windows/{id}/close | Close an active window with `restored_at`; computes overrun and fires the restore cascade | NetworkPlanner |
| POST | /cable-diagnostics/outage-windows/{id}/cancel | Cancel a `REQUESTED` or `APPROVED` window | NetworkPlanner |
| POST | /cable-diagnostics/test-jobs | Create a diagnostics job on an `APPROVED` window | NetworkPlanner |
| GET | /cable-diagnostics/test-jobs/{id} | Get a job | All roles |
| GET | /cable-diagnostics/test-jobs | List jobs; filters `circuit_id`, `outage_window_id`, `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/test-jobs/{id}/plan | Plan a draft job: computes the estimate and enforces the budget cap | NetworkPlanner |
| POST | /cable-diagnostics/test-jobs/{id}/reschedule | Move a `PLANNED` job to another `APPROVED` window of the same circuit (OCC-guarded supersede) | NetworkPlanner |
| POST | /cable-diagnostics/test-jobs/{id}/start | Start fieldwork; window must be `ACTIVE` | TestSupervisor |
| POST | /cable-diagnostics/test-jobs/{id}/suspend | Suspend an in-progress job | TestSupervisor |
| POST | /cable-diagnostics/test-jobs/{id}/resume | Resume a suspended job; window must still be `ACTIVE` | TestSupervisor |
| POST | /cable-diagnostics/test-jobs/{id}/complete | Complete a job in `EVALUATION`; permit must be `RELEASED` | TestSupervisor |
| POST | /cable-diagnostics/test-jobs/{id}/abort | Abort a `DRAFT` or `PLANNED` job; cancels open assignments | NetworkPlanner, TestSupervisor |
| GET | /cable-diagnostics/test-jobs/{id}/invoice | Computed invoice: estimate plus per-line marked-up excavation and splice costs | NetworkPlanner, AssetEngineer |
| GET | /cable-diagnostics/test-jobs/{id}/isolation-permits | Permits of a job | All roles |
| GET | /cable-diagnostics/test-jobs/{id}/test-series | Series of a job | All roles |
| GET | /cable-diagnostics/test-jobs/{id}/faults | Faults of a job | All roles |
| GET | /cable-diagnostics/test-jobs/{id}/equipment-assignments | Assignments of a job | All roles |
| POST | /cable-diagnostics/isolation-permits | Draft an isolation/grounding permit for a `PLANNED` or `IN_PROGRESS` job | SafetyOfficer |
| GET | /cable-diagnostics/isolation-permits/{id} | Get a permit | All roles |
| GET | /cable-diagnostics/isolation-permits | List permits; filters `test_job_id`, `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/isolation-permits/{id}/issue | Issue the permit; records the issuer | SafetyOfficer |
| POST | /cable-diagnostics/isolation-permits/{id}/verify-grounding | Independent grounding verification; verifier must differ from issuer | SafetyOfficer |
| POST | /cable-diagnostics/isolation-permits/{id}/release | Release the permit after job `EVALUATION`; releaser must differ from verifier | SafetyOfficer |
| POST | /cable-diagnostics/test-series | Create a test series on an `IN_PROGRESS` job (voltage tolerance and re-test gating) | TestSupervisor |
| GET | /cable-diagnostics/test-series/{id} | Get a series | All roles |
| GET | /cable-diagnostics/test-series | List series; filters `test_job_id`, `status`, `method`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/test-series/{id}/energize | Energize a `SETUP` series (grounding and equipment gates) | TestSupervisor |
| POST | /cable-diagnostics/test-series/{id}/readings | Append one reading; per-step unique, method-conditional fields | FieldTechnician |
| GET | /cable-diagnostics/test-series/{id}/readings | Readings of a series; append-only log | All roles |
| GET | /cable-diagnostics/test-series/{id}/faults | Fault raised from a series (zero or one) | All roles |
| POST | /cable-diagnostics/test-series/{id}/evaluate | Evaluate a series: computes both verdict bases; FAIL auto-creates a fault | TestSupervisor |
| POST | /cable-diagnostics/test-series/{id}/accept | Customer acceptance of an `EVALUATED` series | NetworkPlanner |
| POST | /cable-diagnostics/test-series/{id}/invalidate | Invalidate an `EVALUATED` series; body carries `reason` | TestSupervisor |
| POST | /cable-diagnostics/faults | Manually raise a fault from a `MONITOR`-verdict series | TestSupervisor |
| GET | /cable-diagnostics/faults/{id} | Get a fault | All roles |
| GET | /cable-diagnostics/faults | List faults; filters `test_job_id`, `test_series_id`, `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/faults/{id}/pinpoint | Pinpoint a `SUSPECTED` or `REOPENED` fault from a TDR trace; computes both distance variants and the corridor | FaultCrewLead |
| POST | /cable-diagnostics/faults/{id}/reopen | Reopen a `CLOSED_VERIFIED` fault (warranty failure) | TestSupervisor |
| GET | /cable-diagnostics/faults/{id}/test-series | Re-test series linked to a fault | All roles |
| GET | /cable-diagnostics/faults/{id}/excavation-orders | Excavations of a fault | All roles |
| GET | /cable-diagnostics/faults/{id}/repair-splices | Splices of a fault | All roles |
| POST | /cable-diagnostics/excavation-orders | Create an excavation for a pinpointed fault (corridor, outage containment, dig overlap, budget) | FaultCrewLead |
| GET | /cable-diagnostics/excavation-orders/{id} | Get an excavation | All roles |
| GET | /cable-diagnostics/excavation-orders | List excavations; filters `fault_record_id`, `status`, plus `limit`, `offset` | All roles |
| GET | /cable-diagnostics/excavation-orders/{id}/repair-splices | Splices referencing an excavation | All roles |
| POST | /cable-diagnostics/excavation-orders/{id}/permit | Mark the municipal permit granted | FaultCrewLead |
| POST | /cable-diagnostics/excavation-orders/{id}/start | Start digging; clock inside the dig window and job window `ACTIVE` | FaultCrewLead |
| POST | /cable-diagnostics/excavation-orders/{id}/backfill | Backfill; requires a splice in `CURING` or `COMPLETED` | FaultCrewLead |
| POST | /cable-diagnostics/excavation-orders/{id}/cancel | Cancel a `DRAFT` or `PERMITTED` excavation; cost is decommitted | FaultCrewLead |
| POST | /cable-diagnostics/repair-splices | Create a splice on an `IN_PROGRESS` excavation (cross-reference and budget gates) | FaultCrewLead |
| GET | /cable-diagnostics/repair-splices/{id} | Get a splice | All roles |
| GET | /cable-diagnostics/repair-splices | List splices; filters `fault_record_id`, `excavation_order_id`, `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/repair-splices/{id}/start | Start splicing; fault must be `EXCAVATING` | FaultCrewLead |
| POST | /cable-diagnostics/repair-splices/{id}/cure | Begin curing; stamps `cure_started_at` | FaultCrewLead |
| POST | /cable-diagnostics/repair-splices/{id}/finish-curing | Finish curing after at least 24 hours | FaultCrewLead |
| POST | /cable-diagnostics/repair-splices/{id}/accept | Customer acceptance after a qualifying passing re-test | NetworkPlanner |
| POST | /cable-diagnostics/repair-splices/{id}/reject | Customer rejection; the fault reopens | NetworkPlanner |
| POST | /cable-diagnostics/mobile-units | Register a mobile test unit | SystemAdmin |
| GET | /cable-diagnostics/mobile-units/{id} | Get a unit | All roles |
| GET | /cable-diagnostics/mobile-units | List units; filters `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/mobile-units/{id}/maintenance | Send an idle unit to maintenance | DispatchCoordinator |
| POST | /cable-diagnostics/mobile-units/{id}/return-to-service | Return a unit from maintenance | DispatchCoordinator |
| GET | /cable-diagnostics/mobile-units/{id}/equipment-assignments | Assignments of a unit | All roles |
| POST | /cable-diagnostics/equipment-assignments | Reserve a unit for a job (capability and four-hour buffer rules) | DispatchCoordinator |
| GET | /cable-diagnostics/equipment-assignments/{id} | Get an assignment | All roles |
| GET | /cable-diagnostics/equipment-assignments | List assignments; filters `mobile_unit_id`, `test_job_id`, `status`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/equipment-assignments/{id}/confirm | Confirm a reservation | DispatchCoordinator |
| POST | /cable-diagnostics/equipment-assignments/{id}/activate | Activate once `mobilize_at` is reached | DispatchCoordinator |
| POST | /cable-diagnostics/equipment-assignments/{id}/release | Release an `ACTIVE` assignment; frees committed hours | DispatchCoordinator |
| POST | /cable-diagnostics/equipment-assignments/{id}/cancel | Cancel a `RESERVED` or `CONFIRMED` assignment | DispatchCoordinator |
| POST | /cable-diagnostics/health-assessments | Compute a health assessment (OCC-guarded create-with-supersede) | AssetEngineer |
| GET | /cable-diagnostics/health-assessments/{id} | Get an assessment | All roles |
| GET | /cable-diagnostics/health-assessments | List assessments; filters `circuit_id`, `supersedes_id`, `status`, `basis`, plus `limit`, `offset` | All roles |
| POST | /cable-diagnostics/health-assessments/{id}/review | Engineering review of a `COMPUTED` assessment | AssetEngineer |
| POST | /cable-diagnostics/health-assessments/{id}/adopt | Customer adopts a `REVIEWED` assessment; updates circuit health fields | NetworkPlanner |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is a locator of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 422 |
| ERR_GROUNDING_NOT_VERIFIED | 409 |
| ERR_PERMIT_NOT_RELEASED | 409 |
| ERR_WINDOW_IN_PAST | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_WINDOW_NOT_ACTIVE | 409 |
| ERR_DIG_OUTSIDE_OUTAGE | 409 |
| ERR_CURING_INCOMPLETE | 409 |
| ERR_CORRIDOR_VIOLATION | 409 |
| ERR_DIG_WINDOW_OVERLAP | 409 |
| ERR_UNIT_OVERLAP_BUFFER | 409 |
| ERR_UNIT_CAPABILITY_MISMATCH | 409 |
| ERR_UNIT_HAS_ASSIGNMENTS | 409 |
| ERR_VOLTAGE_MISMATCH | 422 |
| ERR_NO_READINGS | 409 |
| ERR_STEP_INCOMPLETE | 409 |
| ERR_STEP_OUT_OF_RANGE | 422 |
| ERR_DUPLICATE_STEP | 409 |
| ERR_VERDICT_NOT_FAIL | 409 |
| ERR_FAULT_ALREADY_RECORDED | 409 |
| ERR_PERMIT_EXISTS | 409 |
| ERR_SPLICE_EXISTS | 409 |
| ERR_EXCAVATION_EXISTS | 409 |
| ERR_CIRCUIT_BUSY | 409 |
| ERR_NO_EQUIPMENT_ON_SITE | 409 |
| ERR_DUPLICATE_CIRCUIT_REF | 409 |
| ERR_CROSS_REFERENCE_MISMATCH | 422 |
| ERR_SPLICE_NOT_CURING | 409 |
| ERR_RETEST_REQUIRED | 409 |
| ERR_METHOD_NOT_REQUESTED | 409 |
| ERR_BUDGET_EXCEEDED | 422 |

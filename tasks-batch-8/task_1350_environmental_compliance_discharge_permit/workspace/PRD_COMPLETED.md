# Environmental Compliance and Discharge Permit (NPDES) API — Product Requirements Document

## 1. Introduction

Facilities that discharge wastewater or stormwater under a National Pollutant Discharge Elimination System (NPDES) permit operate inside a tight regulatory frame: every outfall carries numeric effluent limits, every sampled parameter carries a monitoring frequency, every exceedance starts a statutory notification clock measured in hours, and every monitoring period closes with a Discharge Monitoring Report that an agency can accept or send back. Missing any one of these obligations — a skipped sample, a late phone call to the regulator, an incomplete report — converts a routine compliance program into an enforcement action with daily-accruing penalties.

This document specifies an API that manages that entire lifecycle end to end. It governs the establishment of permits, outfalls and effluent limits; the scheduling of sampling events and the chain of custody that carries each sample from the field to the laboratory; the recording and independent validation of analytical results; the detection of effluent-limit exceedances and the 24-hour oral / 120-hour written notification duties they trigger; the generation, certification and agency review of discharge monitoring reports; stormwater pollution prevention plans and their inspection-driven corrective actions; permit renewal with successor-permit supersession; and consent orders with penalty accrual and a payment ledger.

Two design commitments shape everything that follows. First, the system runs on a logical clock rather than the wall clock, so that time-driven obligations — permit expiry, missed samples, overdue notifications, penalty accrual — are deterministic and replayable. Second, every mutation in the system, whether made by an operator or by the clock itself, is appended to a hash-chained audit log, because the audience for this data ultimately includes enforcement attorneys. All endpoints are mounted under the `/npdes` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract-level structures and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The declared role must be one of the eight roles the system recognizes: `EnvironmentalManager`, `FieldSampler`, `LabAnalyst`, `LabValidator`, `ComplianceOfficer`, `FacilityInspector`, `Regulator`, and `SystemAdmin`. A request missing either header, carrying an empty or whitespace-only `X-User-ID`, or naming a role outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not authorized for the target operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For each of the eight roles — `EnvironmentalManager`, `FieldSampler`, `LabAnalyst`, `LabValidator`, `ComplianceOfficer`, `FacilityInspector`, `Regulator`, and `SystemAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on the resources the caller mutates (for example as `collected_by_user_id` on a sampling event, `analyzed_by_user_id` on a lab result, or `prepared_by_user_id` on a report), and the segregation-of-duties checks described in §2.11 compare it, but no ownership check ever compares it to an entity's `id`.

In addition, `Any` is a pseudo-role: any authenticated caller holding one of the eight roles above may use every read (GET) endpoint in the system.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A `limit` or `offset` that is not an integer, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. (The custody-chain listing is the documented exception: it is ordered by `sequence_index`, as described in §3.2.)

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Resource Identity and Common Fields

Every primary resource — Permit, Outfall, EffluentLimit, SamplingEvent, LabResult, Exceedance, DischargeMonitoringReport, StormwaterPlan, Inspection, CorrectiveAction, RenewalApplication and ConsentOrder — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by cascade side effects originating on another resource.

Three resources are append-only ledger or record lines and deliberately carry a smaller common set: a ChainOfCustodyRecord, a PenaltyPayment and an AuditLogEntry each carry `id` and `created_at` only — `updated_at` and `version` are absent on these three, because they are never mutated after creation.

Whenever a mutation touches a resource — including an automatic transition driven by the clock sweep or by a cascade from a parent — that resource's `updated_at` is refreshed and, where present, its `version` is incremented.

### 2.5. The Logical Clock and Scheduled Sweeps

The system does not consult the wall clock. All time-dependent behavior reads a server-held logical clock whose value at startup is exactly `2026-08-01T00:00:00Z`. Operators advance the clock through a `SystemAdmin`-only capability that sets the current logical instant to a supplied `to_iso8601` value. The clock is monotonic: the supplied instant must be strictly after the current logical clock, otherwise the request is rejected with `ERR_CLOCK_REGRESSION` (HTTP 400). The response reports the new `current_utc` and a `transitions_applied` count. The count tallies only the primary time-based transitions listed below — one for each permit moved to `EXPIRED`, one for each sampling event moved to `MISSED`, and one for each exceedance notification transition to `ORAL_OVERDUE` or `WRITTEN_OVERDUE`; the cascade side effects of an expiring permit (its outfall deactivations and sampling-event cancellations, §2.9) are applied but are not included in `transitions_applied`.

Advancing the clock runs a sweep that applies every time-based transition whose condition has become true:

- An `ACTIVE` permit whose `expiration_date` has been reached or passed transitions to `EXPIRED`, with the cascade described in §3.1.
- A sampling event still `SCHEDULED` whose collection window has fully elapsed transitions to `MISSED`.
- An exceedance in `PENDING_ORAL` whose oral-notification deadline has passed transitions to `ORAL_OVERDUE`; one in `ORAL_NOTIFIED` whose written-report deadline has passed transitions to `WRITTEN_OVERDUE`. The precise boundary semantics of these deadlines are defined in §3.4.

Each sweep-applied transition appends its own audit entry with the actor recorded as `system`, so the audit chain (§2.10) replays deterministically from the logical clock.

### 2.6. Numeric Precision, Rounding and Measurement Conventions

All rounding in the system uses the round-half-up method, and every calculated quantity declares its precision at the point of use:

- Percentages of exceedance (`percent_over`) are rounded half-up to 2 decimal places.
- Average concentrations on report lines are rounded half-up to 3 decimal places.
- Pollutant loading is rounded twice in a pinned order — each per-sample load is rounded half-up to 3 decimal places first, then the period total is rounded half-up to 2 decimal places (§3.5).
- Monitoring completeness ratios are rounded half-up to 4 decimal places.
- Monetary amounts are integer cents; intermediate products that must be folded into an integer-cent amount are rounded half-up to whole cents.
- Instants are compared at one-second granularity; deadline checks in this system are strict — being exactly at a deadline is never "past" it.
- Calculated decimal quantities are rendered in JSON as integers when their value is a whole number, and as ordinary JSON numbers otherwise.

Effluent concentrations are expressed in the `unit` declared by the governing limit: `MG_L` (milligrams per litre), `SU` (standard pH units), or `MPN_100ML` (most probable number per 100 millilitres). Flows are recorded in million gallons per day. The conversion from concentration and flow to mass loading uses 3.785 kilograms per milligram-per-litre per million-gallons-per-day.

### 2.7. Optimistic Concurrency Control

Three write operations carry a mandatory optimistic-concurrency guard, because each of them mutates a parent aggregate whose state the client must have observed:

- Creating an effluent limit requires the request to carry `expected_outfall_version`, set to the `version` of the parent outfall as the client last observed it. Every successful limit creation increments that outfall's `version`, so a request bearing an older observed version is acting on a stale view of the outfall's limit set — for example, unaware that a newer `ACTIVE` limit has already superseded the one it intends to supersede — and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Activating a stormwater plan requires the request to carry `expected_permit_version`, set to the `version` of the parent permit as last observed. Activation supersedes the permit's currently `ACTIVE` plan and increments the permit's `version`; a caller whose observed version predates the most recent activation is superseding a plan it never saw, and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Approving a renewal application likewise requires `expected_permit_version` matching the subject permit's current `version`. Approval supersedes the permit and increments its `version`; an approval carrying an older observed version reflects a stale view of the permit's renewal state and is rejected with `ERR_STALE_VERSION` (HTTP 412).

These version fields are non-optional on the three operations named and must be supplied as integers — a missing or non-integer value is `ERR_INVALID_REQUEST` (HTTP 400). No other endpoint accepts a version field.

### 2.8. Validation Order and Resource Existence

Every request is validated against a fixed ladder of checks, applied in this order so that earlier, more fundamental failures surface before later ones:

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers must be present and the role declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization** — the caller's role must be permitted on the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Existence** — every resource identifier appearing in the request path is resolved, left to right. The first identifier that does not resolve yields the corresponding 404: the resource-specific `ERR_PERMIT_NOT_FOUND`, `ERR_OUTFALL_NOT_FOUND`, `ERR_LIMIT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_RESULT_NOT_FOUND`, `ERR_EXCEEDANCE_NOT_FOUND`, `ERR_DMR_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_CORRECTIVE_ACTION_NOT_FOUND`, `ERR_RENEWAL_NOT_FOUND` or `ERR_CONSENT_ORDER_NOT_FOUND` where the path names such a resource, or the generic `ERR_NOT_FOUND` otherwise.
4. **Input shape** — required fields present, enum membership respected, and numeric ranges honored: `limit_value`, `method_detection_limit`, `flow_mgd` and `amount_cents` must each be strictly greater than zero; `reported_value`, `daily_accrual_cents`, `avoided_cost_cents` and `actual_cost_cents` must each be zero or more; `effective_to` must be strictly after `effective_from` when present; `period_end` must not be before `period_start`; `expiration_date` must be strictly after `effective_date`; `base_penalty_cents` must not exceed `statutory_cap_cents`; and a rejecting agency review must carry non-empty `deficiency_notes`. Violations are `ERR_INVALID_REQUEST` (HTTP 400).
5. **Optimistic concurrency** — on the three guarded operations of §2.7, the expected version must match (`ERR_STALE_VERSION`).
6. **State-machine guards** — each transition's source-state preconditions (HTTP 409 errors throughout §3).
7. **Safety rules** — segregation of duties (`ERR_SEGREGATION_OF_DUTIES`), custody-position gates (`ERR_CUSTODY_NOT_ANALYZED`, `ERR_SAMPLE_NOT_IN_LAB`).
8. **Temporal rules** — holding time (`ERR_HOLDING_TIME_EXCEEDED`), collection window (`ERR_COLLECTION_WINDOW_CLOSED`), inspection spacing (`ERR_INSPECTION_TOO_SOON`), renewal window (`ERR_RENEWAL_WINDOW_CLOSED`).
9. **Domain constraints** — limit range overlap (`ERR_LIMIT_RANGE_OVERLAP`), uniqueness (`ERR_DUPLICATE_PERMIT_NUMBER`, `ERR_DUPLICATE_OUTFALL_NUMBER`), the one-open-renewal rule (`ERR_RENEWAL_ALREADY_PENDING`), cross-entity activation gates (`ERR_PERMIT_NOT_ACTIVE`, `ERR_OUTFALL_INACTIVE`, `ERR_NO_ACTIVE_LIMIT`) and the report-certification gates (`ERR_DMR_MONITORING_INCOMPLETE`, `ERR_DMR_EXCEEDANCES_UNRESOLVED`).
10. **Referential consistency** — `ERR_PARAMETER_MISMATCH`, `ERR_UNIT_MISMATCH`, `ERR_LIMIT_SUPERSEDE_MISMATCH`.
11. **Fiscal bounds** — `ERR_PAYMENT_AMOUNT_INVALID`, `ERR_REFUND_EXCEEDS_PAID`.
12. **Clock monotonicity** — `ERR_CLOCK_REGRESSION`.

Because this API's resources are peers joined by references rather than deeply nested paths, the left-to-right existence rule in step 3 applies wherever more than one identifier appears — for example, when listing the custody chain of a sampling event or the payment ledger of a consent order, the parent identifier is resolved first. Identifiers carried in the payload rather than the path (`permit_id`, `outfall_id`, `sampling_event_id`, `plan_id` or `exceedance_id` on the creation endpoints) resolve the same way, yielding the corresponding resource-specific 404. A request body that is not a JSON object is `ERR_INVALID_REQUEST`, and payload fields an operation does not consume are ignored. Two-run operations that read a small transition payload — result rejection and resubmission, agency review, renewal info-request and denial, order appeal, inspection completion, and corrective-action completion and reopening — evaluate the state-machine guard (and, for rejection, the segregation rule) before the payload's required-field checks, deviating from the ladder's strict ordering for that pairing only.

### 2.9. Cascading State Consistency and the Compliance Posture

Parent resources propagate shutdown to their children, and child activity bubbles back up into a permit-level compliance picture.

Downward cascades. When a permit leaves service — through expiry, termination, or supersession by a renewal — every one of its `ACTIVE` outfalls transitions to `INACTIVE`, and every sampling event of those outfalls still in `SCHEDULED` transitions to `CANCELLED`. Deactivating a single outfall applies the same cancellation to its own scheduled events.

Upward rollup. Each permit continuously carries two computed counters and a derived posture:

- `open_corrective_action_count` counts the corrective actions reachable through the permit's outfalls, exceedances and inspections whose status is `OPEN`, `IN_PROGRESS`, `COMPLETED` or `REOPENED` — an action leaves the open set only when it is verified, and re-enters it if reopened.
- `open_exceedance_count` counts the exceedances on the permit's outfalls whose `notification_status` is anything other than `CLOSED`.
- `compliance_posture` is derived: it is `ENFORCEMENT` whenever any consent order linked to the permit through an exceedance stands in `ISSUED`, `UNDER_APPEAL` or `FINAL`; otherwise `UNDER_CORRECTIVE_ACTION` whenever the open corrective action count is above zero; otherwise `GOOD_STANDING`. A new permit starts at `GOOD_STANDING` with both counters at zero.

These recomputations refresh the permit's `updated_at` and increment its `version` in the sense of §2.4 only when a recomputed value actually changes; a recomputation that leaves both counters and the posture unchanged does not touch the permit.

### 2.10. The Append-Only Audit Chain

Every mutating operation — and every transition applied by the clock sweep — appends an AuditLogEntry recording `entity_type` (the entity name of the mutated resource, a label rather than a foreign key), `entity_id`, an `action` label (for example `PERMIT_ISSUED`, `RESULT_VALIDATED`, `LIMIT_SUPERSEDED`), `actor_user_id` and `actor_role` (the literal string `system` for clock-sweep transitions), and `occurred_at` taken from the logical clock.

The entries form a hash chain. Each entry stores `prev_entry_hash`, the SHA-256 hex of the previous entry — the very first entry uses sixty-four zero characters as its genesis — and `entry_hash`, computed as the lowercase SHA-256 hex of the pipe-joined concatenation of `prev_entry_hash`, `entity_type`, `entity_id`, `action`, `actor_user_id`, `actor_role` and the ISO 8601 rendering of `occurred_at`. Entries are append-only and totally ordered by insertion, which follows mutation order; because `occurred_at` comes from the logical clock, replaying the same request sequence always rebuilds the same chain. The chain is listable and filterable by `entity_type` and `entity_id`.

### 2.11. Segregation of Duties

Three hand-offs in the system must be performed by two different people; in each case the second actor's `X-User-ID` must differ from the recorded identifier of the first, or the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):

- A lab result may not be validated or rejected by the analyst who recorded (or last resubmitted) it — the validator's identifier must differ from `analyzed_by_user_id`.
- A discharge monitoring report may not be certified by the officer who prepared it — the certifier's identifier must differ from `prepared_by_user_id`.
- A corrective action may not be verified by the person who marked it complete — the verifier's identifier must differ from `resolved_by_user_id`.

These checks sit at rung 7 of the validation ladder in §2.8: they are evaluated after the state-machine guard of the same operation and before any temporal or domain-constraint rule.

## 3. Business Logic & Workflows

### 3.1. Establishing the Permit: Outfalls and Effluent Limits

An `EnvironmentalManager` opens a new permit by supplying its `permit_number`, `facility_name`, `receiving_water_body`, `effective_date` and `expiration_date`. The permit number must be globally unique across all permits — a duplicate is rejected with `ERR_DUPLICATE_PERMIT_NUMBER` — and the expiration must be strictly after the effective date, else `ERR_INVALID_REQUEST`. A new permit stands in `DRAFT`, with `superseded_by_permit_id` null, both compliance counters at zero and `compliance_posture` at `GOOD_STANDING`, and a `PERMIT_CREATED` audit entry is appended. Permits can be listed filtered by `status` or `superseded_by_permit_id`.

Beneath the permit, the same role registers outfalls with a payload carrying `permit_id`, an `outfall_number` that must be unique within that permit (`ERR_DUPLICATE_OUTFALL_NUMBER`), and an optional `description` that may be null. Outfalls may be added while the permit is `DRAFT` or `ACTIVE`; against any other permit status the creation fails with `ERR_PERMIT_NOT_ACTIVE`. Every outfall begins life `ACTIVE`, with an `OUTFALL_CREATED` audit entry. Outfalls can be listed filtered by `permit_id` or `status`.

The permit becomes operative through issuance, which enforces four preconditions, evaluated in this order: the permit must be in `DRAFT` (`ERR_PERMIT_NOT_IN_DRAFT`); the logical clock must sit at or after `effective_date` and strictly before `expiration_date` (`ERR_PERMIT_NOT_ISSUABLE`); at least one `ACTIVE` outfall must exist for the permit (`ERR_PERMIT_NO_OUTFALL`); and every `ACTIVE` outfall of the permit must hold at least one `ACTIVE` effluent limit (`ERR_OUTFALL_NO_ACTIVE_LIMIT`). Issuance moves the permit `DRAFT → ACTIVE`, increments its `version` and appends a `PERMIT_ISSUED` audit entry.

Effluent limits are where the permit's teeth live. An `EnvironmentalManager` creates one against an outfall by supplying `outfall_id`, `parameter_code` (one of `BOD5`, `TSS`, `PH`, `AMMONIA_N`, `COPPER`, `FECAL_COLIFORM`), `limit_type` (`DAILY_MAX` or `MONTHLY_AVG`), `limit_value` (strictly greater than zero), `unit` (`MG_L`, `SU` or `MPN_100ML`), `monitoring_frequency` (`WEEKLY` or `MONTHLY`, which drives the required sample counts of §3.5), and `effective_from`. The `effective_to` bound is optional: when present it must be strictly after `effective_from`; when null the limit is open-ended. `average_method` — `ARITHMETIC` (the default) or `FLOW_WEIGHTED` — selects how monthly-average concentrations are computed on reports, and is only meaningful for `MONTHLY_AVG` evaluation. Limits can be listed filtered by `outfall_id`, `supersedes_limit_id` or `status`.

Limit creation is guarded, after input-shape checks and the outfall-version guard of §2.7, by a range-overlap rule and a supersede-consistency rule. A limit's effective range is half-open: it covers instants at or after `effective_from` and strictly before `effective_to`. No other `ACTIVE` limit with the same outfall, parameter and limit type may have a range intersecting the new one — with one deliberate exception: the limit named by `supersedes_limit_id` is excluded from the overlap check because it flips to `SUPERSEDED` atomically with the new creation. Adjacency is not an overlap: a new limit whose `effective_from` is exactly an existing limit's `effective_to` is allowed. A violation is rejected with `ERR_LIMIT_RANGE_OVERLAP`. When `supersedes_limit_id` is supplied it must reference an `ACTIVE` limit of the same outfall, the same `parameter_code` and the same `limit_type`; otherwise creation fails with `ERR_LIMIT_SUPERSEDE_MISMATCH`. The outfall itself must be `ACTIVE` (`ERR_OUTFALL_INACTIVE`). Every successful creation increments the outfall's `version` by one and appends `LIMIT_CREATED`, plus `LIMIT_SUPERSEDED` when a predecessor was flipped.

A successor limit can later be rescinded as a compensating action: rescinding requires the limit to be `ACTIVE` (`ERR_LIMIT_NOT_ACTIVE`) and to have itself been created with a non-null `supersedes_limit_id` (`ERR_LIMIT_NOT_A_SUCCESSOR`). Rescission moves the successor from `ACTIVE` to `RESCINDED` and restores its named predecessor `SUPERSEDED → ACTIVE`, increments the outfall's `version`, and appends both `LIMIT_RESCINDED` and `LIMIT_RESTORED` audit entries.

Outfalls can be taken out of service and brought back. Deactivation requires the outfall `ACTIVE` (`ERR_OUTFALL_INACTIVE`), moves it to `INACTIVE`, cancels every one of its sampling events still in `SCHEDULED`, increments its `version` and appends `OUTFALL_DEACTIVATED`. Reactivation requires the outfall `INACTIVE` (`ERR_OUTFALL_NOT_INACTIVE`) and its parent permit `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`), returns it to `ACTIVE` and appends `OUTFALL_REACTIVATED`.

Permit shutdown takes three forms, all sharing the downward cascade of §2.9. Termination, performed by an `EnvironmentalManager`, requires the permit `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`), moves it `ACTIVE → TERMINATED`, deactivates its `ACTIVE` outfalls, cancels their still-`SCHEDULED` sampling events, increments the permit's `version` and appends `PERMIT_TERMINATED`. Expiry is the sweep's work: when the logical clock reaches or passes `expiration_date` on an `ACTIVE` permit, the permit transitions `ACTIVE → EXPIRED` with the same outfall and sampling-event cascade and a `PERMIT_EXPIRED` audit entry recorded against the `system` actor. Supersession through a renewal approval — which can strike either an `ACTIVE` or an already `EXPIRED` permit — is described in §3.7; `SUPERSEDED` and `TERMINATED` are terminal.

### 3.2. Sampling Schedules, Collection and Chain of Custody

A `FieldSampler` schedules a sampling event with a payload containing `outfall_id`, `parameter_code`, the planned collection instant `scheduled_for`, and optionally `collection_window_hours` — the symmetric window around the planned instant, defaulting to 24 hours and accepted as an integer between 1 and 168 hours inclusive. Scheduling is gated, in ladder order, by three cross-entity checks: the permit reached through the outfall must be `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`); the outfall itself must be `ACTIVE` (`ERR_OUTFALL_INACTIVE`); and an `ACTIVE` effluent limit for that outfall and parameter must exist whose effective range covers `scheduled_for` (`ERR_NO_ACTIVE_LIMIT`). A new event starts with `schedule_status` `SCHEDULED` and `custody_status` `NOT_SEALED`, with `collected_at` and `collected_by_user_id` null, and a `SAMPLE_SCHEDULED` audit entry is appended. Events can be listed filtered by `outfall_id` or `schedule_status`.

A sampling event carries two independent state dimensions from this point on. The schedule dimension runs `SCHEDULED → COLLECTED → CLOSED`, with `MISSED` and `CANCELLED` as terminal drop-offs; the custody dimension begins only at collection and runs `SEALED → IN_TRANSIT → LAB_RECEIVED → ANALYZED`.

Collection is the pivotal act. A `FieldSampler` collects under three checks applied in ladder order (§2.8): the event's schedule status must be `SCHEDULED` (`ERR_SAMPLE_NOT_SCHEDULED`); the logical clock must sit inside the collection window — at or after `scheduled_for` minus `collection_window_hours` and at or before `scheduled_for` plus `collection_window_hours`, with attempts outside that inclusive window rejected with `ERR_COLLECTION_WINDOW_CLOSED` (HTTP 422); and the parent outfall must remain `ACTIVE` (`ERR_OUTFALL_INACTIVE`). A successful collection stamps `collected_at` with the logical clock and `collected_by_user_id` with the caller, moves the schedule dimension `SCHEDULED → COLLECTED`, moves custody `NOT_SEALED → SEALED`, automatically appends a `SEAL` chain-of-custody record as `sequence_index` 1, increments the event's `version` and appends a `SAMPLE_COLLECTED` audit entry.

Two ways out exist for an event that is never collected. A `FieldSampler` may cancel an event whose schedule status is `SCHEDULED` (`ERR_SAMPLE_NOT_SCHEDULED`), moving it to `CANCELLED` with a `SAMPLE_CANCELLED` audit entry; permit- and outfall-level cascades (§3.1) force the same transition. Alternatively, if the clock sweeps past the end of the collection window while the event is still `SCHEDULED`, the sweep moves it to `MISSED` and appends `SAMPLE_MISSED` as the `system` actor. Finally, when every lab result recorded against a collected sample has reached `VALIDATED` and none remains `SUBMITTED` or `REJECTED`, the event closes automatically: `COLLECTED → CLOSED`, with `SAMPLE_CLOSED` appended by the `system` actor (see §3.3).

After collection, custody advances through explicit chain-of-custody records appended by a `FieldSampler` or a `LabAnalyst`. Each append carries `event_type`, the physical instant `event_at`, and an optional `note`; `from_party` and `to_party` identify the releasing and receiving parties and are required for `TRANSFER` and `RECEIVE_LAB` but may be null for `SEAL` and `ANALYSIS_START`. The custody machine admits exactly one event type per position: a `TRANSFER` is accepted only from `SEALED` and moves custody to `IN_TRANSIT`; a `RECEIVE_LAB` is accepted only from `IN_TRANSIT` and moves custody to `LAB_RECEIVED`; an `ANALYSIS_START` is accepted only from `LAB_RECEIVED` and moves custody to `ANALYZED`. Any other pairing of event type to current custody position is rejected with `ERR_CUSTODY_OUT_OF_ORDER`. Each accepted append is assigned the next `sequence_index` — a monotonic, one-based index within the sampling event — records the caller as `recorded_by_user_id`, increments the sampling event's `version` and appends a `CUSTODY_APPENDED` audit entry. The full chain for a sample is listable, returned in `sequence_index` order; per §2.4, these records carry `id` and `created_at` but neither `updated_at` nor `version`.

### 3.3. Laboratory Results and Independent Data Validation

Once a sample is physically in the laboratory, a `LabAnalyst` records an analytical result against it. The payload contains `sampling_event_id`, `parameter_code`, `reported_value` (zero or greater), `unit`, `method_detection_limit` (strictly greater than zero), the measured `flow_mgd` at sampling time (strictly greater than zero, in million gallons per day), the analysis instant `analyzed_at`, and an optional `qualifier` — `NONE` (the default), `BELOW_MDL`, or `ESTIMATED`. Recording requires the sample's custody position to be `LAB_RECEIVED` or `ANALYZED` (`ERR_SAMPLE_NOT_IN_LAB`), and then two referential checks: the result's `parameter_code` must equal the sampling event's parameter (`ERR_PARAMETER_MISMATCH`), and its `unit` must equal the unit of the governing `ACTIVE` `DAILY_MAX` limit for the sample's outfall and parameter whose effective range covers the sample's `collected_at` — the same limit the validation step below uses for exceedance detection — when such a limit exists (`ERR_UNIT_MISMATCH`); when none exists, the unit is not cross-checked. A recorded result starts at `SUBMITTED` with `analyzed_by_user_id` set to the caller, `validated_by_user_id`, `validated_at`, `rejection_reason`, `exceeds_limit` and `exceedance_id` all null, and a `RESULT_RECORDED` audit entry. Results can be listed filtered by `sampling_event_id`, `exceedance_id` or `validation_status`.

Validation is performed by a `LabValidator` and enforces its four gates in this order: the result must be `SUBMITTED` (`ERR_RESULT_NOT_SUBMITTED`); the validator must not be the analyst who recorded it — the caller's `X-User-ID` must differ from `analyzed_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); the sample's custody must have reached `ANALYZED` (`ERR_CUSTODY_NOT_ANALYZED`); and the analysis must respect the parameter's holding time. Holding time is the elapsed time from the sample's `collected_at` to the result's `analyzed_at`, and it must not exceed the parameter's allowance: 2 hours for `PH`, 8 hours for `FECAL_COLIFORM`, 48 hours for `BOD5`, 168 hours (seven days) for `TSS`, 672 hours (twenty-eight days) for `AMMONIA_N`, and 4320 hours (one hundred eighty days) for `COPPER`. An analysis landing exactly at its allowance is valid; anything beyond it is rejected with `ERR_HOLDING_TIME_EXCEEDED` (HTTP 422).

A successful validation stamps `validated_by_user_id` with the caller and `validated_at` with the logical clock, moves the result `SUBMITTED → VALIDATED`, and runs exceedance detection. The comparison value is the result's `reported_value`, except that a result carrying the `BELOW_MDL` qualifier compares at its `method_detection_limit` instead. The governing limit is the `ACTIVE` `DAILY_MAX` effluent limit for the sample's outfall and the result's parameter whose half-open effective range covers the sample's `collected_at`. If no such governing limit exists, `exceeds_limit` is set to false and nothing further happens. If one exists and the comparison value is strictly greater than its `limit_value` — equality is not an exceedance — `exceeds_limit` is set to true and the detection cascade of §3.4 fires, linking the result to a new exceedance through `exceedance_id`. Otherwise `exceeds_limit` is false. Validation then increments the result's `version`, appends `RESULT_VALIDATED`, and — when this validation leaves every result of the sample `VALIDATED` with none `SUBMITTED` or `REJECTED` — closes the sample itself, moving its schedule status from `COLLECTED` to `CLOSED`.

Rejection is the validator's other instrument: from `SUBMITTED` (`ERR_RESULT_NOT_SUBMITTED`), under the same segregation rule against `analyzed_by_user_id`, the validator supplies a `reason` which is recorded as `rejection_reason`, and the result moves `SUBMITTED → REJECTED` with a `RESULT_REJECTED` audit entry.

Rejection is not terminal. A `LabAnalyst` may resubmit a `REJECTED` result (`ERR_RESULT_NOT_REJECTED`), optionally carrying corrected `reported_value`, `qualifier` and `analyzed_at`. Resubmission returns the result to `SUBMITTED`, replaces `analyzed_by_user_id` with the resubmitting caller — so the segregation rule is evaluated against the new analyst on the next validation — clears `rejection_reason` to null, increments the `version` and appends `RESULT_RESUBMITTED`. The validation loop can cycle as many times as the laboratory's quality process requires.

### 3.4. Exceedances and the Regulatory Notification Clock

When validation detects a breach (§3.3), an Exceedance is created as the first link of a three-link cascade. The exceedance snapshots the evidence: `lab_result_id` and `effluent_limit_id` identify the result and the governing limit; `outfall_id` is denormalized onto the exceedance for query convenience; `parameter_code` is copied from the result; `reported_value` snapshots the comparison value used at detection (the detection limit itself when the result was `BELOW_MDL`); and `limit_value` snapshots the limit at detection. `percent_over` expresses the magnitude of the breach: the comparison value minus the limit value, divided by the limit value, multiplied by one hundred, rounded half-up to two decimal places. `detected_at` is the result's `validated_at`. Two statutory deadlines are computed from it: `oral_notification_due_at` exactly 24 hours after detection, and `written_report_due_at` exactly 120 hours (five days) after detection. The new exceedance stands with `notification_status` at `PENDING_ORAL` and `enforcement_status` at `NONE` — two independent state dimensions — with `oral_notified_at` and `written_filed_at` null.

The creation appends an `EXCEEDANCE_DETECTED` audit entry. The second cascade link fires immediately: every exceedance auto-creates a CorrectiveAction with `source_type` `EXCEEDANCE`, `exceedance_id` set, severity always `MAJOR`, status `OPEN` and an auto-generated narrative `description`, appends `CA_CREATED`, and stores its identifier in the exceedance's `corrective_action_id`; both entries record the validating `LabValidator` as their actor. The third link bubbles up: the corrective action's creation increments the parent permit's `open_corrective_action_count` by one and recomputes its `compliance_posture` — a permit in `GOOD_STANDING` drops to `UNDER_CORRECTIVE_ACTION` — while the permit's `open_exceedance_count` is also recomputed. Exceedances can be listed filtered by `outfall_id`, `lab_result_id`, `effluent_limit_id`, `corrective_action_id` or `notification_status`.

The notification dimension is a clock race the compliance office must win twice. A `ComplianceOfficer` records the oral notification while the exceedance is in `PENDING_ORAL` or `ORAL_OVERDUE` — from any other status the call is rejected with `ERR_INVALID_NOTIFICATION_STATE` — moving it to `ORAL_NOTIFIED` and stamping `oral_notified_at` with the logical clock, with an `EXCEEDANCE_ORAL_NOTIFIED` audit entry. If the clock sweeps strictly past `oral_notification_due_at` while the exceedance still waits in `PENDING_ORAL`, the sweep moves it to `ORAL_OVERDUE` (`EXCEEDANCE_ORAL_OVERDUE`, recorded against `system`); a late oral notification is still permitted from `ORAL_OVERDUE`, and the overdue sojourn remains visible in the audit chain. The same pattern repeats for the written report: filing by a `ComplianceOfficer` — which carries a `report_summary` — is accepted from `ORAL_NOTIFIED` or `WRITTEN_OVERDUE` (`ERR_INVALID_NOTIFICATION_STATE` otherwise), moves the exceedance to `WRITTEN_FILED` and stamps `written_filed_at` (`EXCEEDANCE_WRITTEN_FILED`); and a clock strictly past `written_report_due_at` while in `ORAL_NOTIFIED` produces `WRITTEN_OVERDUE` (`EXCEEDANCE_WRITTEN_OVERDUE`). Both deadlines share one boundary rule: an act performed at exactly the due instant is timely — only a clock strictly later than the due instant triggers the overdue transition.

Closure is the notification dimension's terminal state. A `ComplianceOfficer` closes an exceedance only from `WRITTEN_FILED` (`ERR_INVALID_NOTIFICATION_STATE` otherwise), and only when the corrective action linked through `corrective_action_id` stands in `VERIFIED` or `CLOSED` (`ERR_EXCEEDANCE_NOT_CLOSABLE`). Closing moves the exceedance to `CLOSED`, recomputes the permit's `open_exceedance_count` and `compliance_posture`, and appends `EXCEEDANCE_CLOSED`.

The enforcement dimension evolves independently of notifications. Proposing a consent order (§3.8) moves the linked exceedance `NONE → ORDER_ISSUED` and recomputes the permit's posture, which may become `ENFORCEMENT`; when that order is eventually satisfied, enforcement moves `ORDER_ISSUED → RESOLVED` and the posture is recomputed again. `RESOLVED` is terminal for the enforcement dimension, as `CLOSED` is for notifications.

### 3.5. Discharge Monitoring Reports

Each monitoring period closes with a Discharge Monitoring Report. A `ComplianceOfficer` generates one by supplying `outfall_id`, `period_start` and `period_end`; the period is inclusive at both ends and `period_end` must not precede `period_start` (`ERR_INVALID_REQUEST`). The report's `due_date` is exactly 15 days after `period_end`; `prepared_by_user_id` records the creating officer; the report stands in `DRAFT` and a `DMR_CREATED` audit entry is appended. Generation computes the whole monitoring picture in one pass. DMRs can be listed filtered by `outfall_id` or `status`.

The completeness arithmetic works as follows. The period's length in days counts every calendar day from `period_start` through `period_end` inclusive. For each parameter holding an `ACTIVE` effluent limit for this outfall whose effective range intersects the period — a limit intersects when its `effective_from` falls at or before `period_end` and its `effective_to` is null or strictly after `period_start` — the required count depends on that limit's `monitoring_frequency`: a `WEEKLY` limit requires the period's day count divided by seven and rounded up to a whole number of samples; a `MONTHLY` limit requires one sample per calendar month the period touches. Each `ACTIVE` limit drives its own requirement — a parameter holding both an intersecting `DAILY_MAX` and an intersecting `MONTHLY_AVG` limit contributes both — and `required_sample_count` is the sum of these per-limit requirements. `total_validated_results` counts the `VALIDATED` lab results — `SUBMITTED` and `REJECTED` results never count — whose sampling event belongs to this outfall and whose `collected_at` falls inside the period inclusive. `monitoring_completeness_ratio` is the total divided by the required count, rounded half-up to four decimal places, and is exactly 0 when nothing is required. The ratio falls into three tiers: at least 1.0 is COMPLETE; at least 0.5 but below 1.0 is DEFICIENT, in which certification is still permitted; below 0.5 is INCOMPLETE and blocks certification.

The report's `summary_lines` carry one object per such parameter, ordered by `parameter_code` ascending, each with `parameter_code`, `sample_count`, `avg_concentration`, `max_concentration`, `total_loading_kg` and an `exceeds_limit` flag. `sample_count` is the number of validated results contributing to the line — zero when there are none, in which case `avg_concentration` and `max_concentration` are null and `total_loading_kg` is 0. The average follows the parameter's `MONTHLY_AVG` limit's `average_method` when the parameter holds one, and otherwise its remaining limit's `average_method`: under `ARITHMETIC` it is the plain mean of the comparison values (each result's `reported_value`, or its `method_detection_limit` when `BELOW_MDL`), rounded half-up to three decimal places; under `FLOW_WEIGHTED` each comparison value is multiplied by its result's `flow_mgd`, the products are summed and divided by the sum of the flows, and the quotient is rounded half-up to three decimal places — identical inputs produce a different average whenever flows are non-uniform (two results of 1.0 at 4.0 MGD and 3.0 at 1.0 MGD give an arithmetic average of 2.000 but a flow-weighted average of 1.400). Contributing results are considered in order of `collected_at` ascending, ties broken by creation order. `max_concentration` is the largest comparison value in the line. `total_loading_kg` converts concentration and flow to mass with a pinned rounding order: first each contributing result's per-sample load — its comparison value times its `flow_mgd` times 3.785 — is rounded half-up to three decimal places; then those rounded per-sample loads are summed and the total is rounded half-up to two decimal places. Rounding only once after summing raw loads is forbidden, because it diverges on boundary data: per-sample loads of 0.122634 and 0.1222555 round to 0.123 and 0.122 respectively, summing to a pinned total of 0.25, whereas rounding the raw sum of 0.2448895 once would yield 0.24. A line's `exceeds_limit` flag is true when either the parameter holds an `ACTIVE` `MONTHLY_AVG` limit and the line's average strictly exceeds that limit's value, or the parameter holds an `ACTIVE` `DAILY_MAX` limit and the line's maximum strictly exceeds that limit's value.

`is_late` is the report's lateness flag: it is true when the report has not been submitted and the logical clock is past `due_date`, or when its `submitted_at` ended up later than `due_date`. The flag is evaluated at generation, re-evaluated against the logical clock on every read, and recomputed at submission.

Certification, submission and agency review form the report's gauntlet. Certification by a `ComplianceOfficer` enforces four gates in order: the report must be in `DRAFT` (`ERR_DMR_NOT_DRAFT`); the certifier must differ from `prepared_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); the `monitoring_completeness_ratio` — recomputed at certification time from the currently `VALIDATED` results, together with `required_sample_count` and `total_validated_results`, while the stored `summary_lines` are left untouched — must be at least 0.5 (`ERR_DMR_MONITORING_INCOMPLETE`, HTTP 422); and every exceedance of this outfall detected within the period must be at least orally notified — its `notification_status` one of `ORAL_NOTIFIED`, `WRITTEN_OVERDUE`, `WRITTEN_FILED` or `CLOSED` (`ERR_DMR_EXCEEDANCES_UNRESOLVED`). Certification records `certified_by_user_id`, moves the report `DRAFT → CERTIFIED` and appends `DMR_CERTIFIED`. Submission requires `CERTIFIED` (`ERR_DMR_NOT_CERTIFIED`) and tightens the exceedance gate: every period exceedance must now have its written report filed, standing in `WRITTEN_FILED` or `CLOSED` (`ERR_DMR_EXCEEDANCES_UNRESOLVED`). Submission stamps `submitted_at` with the logical clock, recomputes `is_late`, moves the report `CERTIFIED → SUBMITTED` and appends `DMR_SUBMITTED`.

Agency review belongs to the `Regulator` and requires the report `SUBMITTED` (`ERR_DMR_NOT_SUBMITTED`). A `decision` of `ACCEPTED` moves the report to `ACCEPTED`, its terminal state (`DMR_ACCEPTED`). A `decision` of `REJECTED` requires a non-empty `deficiency_notes` payload field (`ERR_INVALID_REQUEST` otherwise); the notes are recorded on the report and it moves to `REJECTED` (`DMR_REJECTED`). A rejected report is not dead: a `ComplianceOfficer` may return it from `REJECTED` to `DRAFT` (`ERR_DMR_NOT_REJECTED` from any other status), which clears `certified_by_user_id` to null, leaves `submitted_at` and `deficiency_notes` unchanged, and recomputes the counts, the ratio and the `summary_lines` from the currently `VALIDATED` results — so corrections validated since the first attempt flow into the next cycle (`DMR_REVISED`).

### 3.6. Stormwater Plans, Inspections and Corrective Actions

A `FacilityInspector` owns the stormwater pollution prevention plan. Authoring one takes `permit_id`, a `plan_title`, a free-form `version_label` such as rev-2026-A, and `inspection_frequency_days`, the required routine-inspection cadence in days, accepted from 1 to 365 inclusive. A new plan stands in `DRAFT`, with a `PLAN_CREATED` audit entry. Plans can be listed filtered by `permit_id` or `status`.

Activation publishes the plan: it requires the plan in `DRAFT` (`ERR_PLAN_NOT_DRAFT`), the parent permit `ACTIVE` (`ERR_PERMIT_NOT_ACTIVE`), and the permit-version guard of §2.7. Activation moves the plan `DRAFT → ACTIVE`, and because a permit operates under exactly one active plan, any other plan of the same permit currently `ACTIVE` flips to `SUPERSEDED` with a `PLAN_SUPERSEDED` audit entry recorded against the `system` actor; the permit's own `version` increments, and `PLAN_ACTIVATED` is appended. Supersession is terminal for the older plan.

Inspections are scheduled against a plan with `plan_id` and a `scheduled_for` instant; the scheduling inspector is recorded as `inspector_user_id`, the inspection starts `SCHEDULED`, and `INSPECTION_SCHEDULED` is appended. A spacing rule protects inspection independence: no other inspection of the same plan that is not `CANCELLED` may be scheduled strictly less than 7 days away from the new one — a gap of exactly 7 days is allowed. Violations are rejected with `ERR_INSPECTION_TOO_SOON`. Inspections can be listed filtered by `plan_id` or `status`, and an inspection may be cancelled while `SCHEDULED` (`ERR_INSPECTION_NOT_SCHEDULED`), moving it to `CANCELLED` with `INSPECTION_CANCELLED`.

Completing an inspection is where findings become obligations. Completion requires the inspection `SCHEDULED` (`ERR_INSPECTION_NOT_SCHEDULED`) and its parent plan `ACTIVE` (`ERR_PLAN_NOT_ACTIVE`). The payload carries `findings`: a list — an empty list is explicitly allowed — of objects each with a `description` and a `severity` of `CRITICAL`, `MAJOR` or `MINOR`. Completion stamps `completed_at` with the logical clock, moves the inspection `SCHEDULED → COMPLETED`, and then, for each finding, creates a CorrectiveAction with `source_type` `INSPECTION`, `inspection_id` set, the finding's description and severity, and status `OPEN`; each such creation increments the parent permit's `open_corrective_action_count` and recomputes its posture, so a permit with no other enforcement pressure moves `GOOD_STANDING → UNDER_CORRECTIVE_ACTION` on the first finding. `INSPECTION_COMPLETED` is appended.

Every corrective action — inspection-sourced or exceedance-sourced — gets its deadline from its severity at creation: `deadline_at` is `created_at` plus 7 days for `CRITICAL`, plus 30 days for `MAJOR`, plus 90 days for `MINOR`. An action's `is_overdue` flag is true whenever it sits in `OPEN`, `IN_PROGRESS` or `REOPENED` and the logical clock is strictly past the deadline; sitting exactly at the deadline is not overdue. Corrective actions can be listed filtered by `inspection_id`, `exceedance_id` or `status`.

The work cycle is a six-state loop. A `FacilityInspector` starts work from `OPEN` or `REOPENED` — from any other status the request fails with `ERR_CORRECTIVE_ACTION_INVALID_STATE` — moving the action to `IN_PROGRESS` (`CA_STARTED`, or `CA_RESTARTED` after a reopen). Completion, also by a `FacilityInspector`, requires `IN_PROGRESS` (`ERR_CORRECTIVE_ACTION_INVALID_STATE`) and declares the remediation cost: the payload's `actual_cost_cents` (zero or more) is recorded, `resolved_at` is stamped with the clock, `resolved_by_user_id` is set to the caller, and the action moves `IN_PROGRESS → COMPLETED` (`CA_COMPLETED`). Verification belongs to the `Regulator`: from `COMPLETED` (`ERR_CORRECTIVE_ACTION_INVALID_STATE`), and only when the verifier's `X-User-ID` differs from `resolved_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), the action moves to `VERIFIED`, records `verified_by_user_id`, leaves the permit's open set — the permit's `open_corrective_action_count` is recomputed and its posture may revert from `UNDER_CORRECTIVE_ACTION` back to `GOOD_STANDING` — and appends `CA_VERIFIED`. From `VERIFIED` a `FacilityInspector` closes the action into its terminal `CLOSED` state (`CA_CLOSED`). A `Regulator` may instead reopen a `VERIFIED` action, supplying a `reason`: the action returns to `REOPENED`, `verified_by_user_id`, `resolved_at`, `resolved_by_user_id` and `actual_cost_cents` are all cleared to null, the action re-enters the permit's open set with count and posture recomputed, and `CA_REOPENED` is appended. Reopen-from-`VERIFIED` and close-from-`VERIFIED` are the only two exits from that state; any other attempted transition from a disallowed status is `ERR_CORRECTIVE_ACTION_INVALID_STATE`.

### 3.7. Permit Renewal and Successor Permits

Permits expire; renewals keep facilities legal. An `EnvironmentalManager` submits a renewal application with `permit_id` and a `proposed_expiration_date`. Submission is only possible inside the renewal window — the logical clock must sit at or after the instant 180 days before the permit's `expiration_date` and strictly before the expiration itself, otherwise `ERR_RENEWAL_WINDOW_CLOSED` — and a permit may carry at most one open application, that is one in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED` (`ERR_RENEWAL_ALREADY_PENDING`). A submitted application records `submitted_at` from the logical clock, starts in `SUBMITTED`, and appends `RENEWAL_SUBMITTED`; applications can be listed filtered by `permit_id`, `status` or `resulting_permit_id`.

Review is the `Regulator`'s desk. Starting review moves the application `SUBMITTED → UNDER_REVIEW` (`ERR_RENEWAL_NOT_SUBMITTED`; `RENEWAL_UNDER_REVIEW`). When the agency needs more from the facility, requesting information moves `UNDER_REVIEW → INFO_REQUESTED` (`ERR_RENEWAL_NOT_UNDER_REVIEW`) and records the supplied `info_request_note` on the application (`RENEWAL_INFO_REQUESTED`); resuming review returns `INFO_REQUESTED → UNDER_REVIEW` (`ERR_RENEWAL_NOT_INFO_REQUESTED`; `RENEWAL_REVIEW_RESUMED`). The request-resume pair can cycle as needed.

Approval is the heaviest transaction in the system. It requires the application `UNDER_REVIEW` (`ERR_RENEWAL_NOT_UNDER_REVIEW`) and the permit-version guard of §2.7, and its payload carries `expected_permit_version` alongside the successor's identity: `new_permit_number`, `new_effective_date` and `new_expiration_date`. The successor identity is validated only for shape — `new_permit_number` a non-empty string and `new_expiration_date` strictly after `new_effective_date` (`ERR_INVALID_REQUEST`); the duplicate-permit-number uniqueness rule of §3.1 is not applied to it. Approval then executes a four-link cascade: first, a successor Permit is created in `ACTIVE` status from those three values, inheriting `facility_name` and `receiving_water_body` from the old permit, and its identifier is recorded as the application's `resulting_permit_id`; second, the old permit moves to `SUPERSEDED` with its `superseded_by_permit_id` pointing at the successor and its `version` incremented — approval imposes no status precondition on the old permit beyond the version guard, so it may still stand `ACTIVE` or have already lapsed to `EXPIRED`; third, every outfall of the old permit still `ACTIVE` moves to `INACTIVE`; fourth, every sampling event of those outfalls still `SCHEDULED` moves to `CANCELLED`. Each hop appends its own audit entry — `RENEWAL_APPROVED`, `PERMIT_SUPERSEDED`, `OUTFALL_DEACTIVATED` and `SAMPLE_CANCELLED`, the latter three recorded against the `system` actor — so the supesession chain is fully reconstructible from the log. Denial is the simpler exit: from `UNDER_REVIEW` (`ERR_RENEWAL_NOT_UNDER_REVIEW`), the `Regulator` supplies a `reason` which is recorded as `decision_reason`, and the application moves to `DENIED` (`RENEWAL_DENIED`). `APPROVED` and `DENIED` are both terminal.

### 3.8. Consent Orders, Penalty Accrual and the Payment Ledger

When an exceedance ripens into enforcement, a `Regulator` proposes a consent order against it. The payload names the `exceedance_id`, an `assessment_variant` of `PER_DAY` or `ECONOMIC_BENEFIT`, a `base_penalty_cents` that must be strictly positive and no greater than `statutory_cap_cents`, and the `statutory_cap_cents` itself (strictly positive). Two variant-specific inputs complete the picture: `daily_accrual_cents` (zero or more) is the stipulated per-day penalty for the `PER_DAY` variant and is ignored for `ECONOMIC_BENEFIT`, while `avoided_cost_cents` (zero or more) and `gravity_factor` (strictly greater than zero) serve the `ECONOMIC_BENEFIT` variant and are ignored for `PER_DAY`. All three are optional: when supplied they are validated and stored regardless of variant; when omitted they are stored as null and contribute zero to the computation. A new order stands in `PROPOSED`, with `issued_at`, `finalized_at`, `cure_date` and `final_amount_cents` null and its payment counters at zero. The act of proposing already has teeth: the linked exceedance's enforcement dimension moves `NONE → ORDER_ISSUED`, and the permit's `compliance_posture` is recomputed — per §2.9, a consent order standing in `ISSUED`, `UNDER_APPEAL` or `FINAL` forces the posture to `ENFORCEMENT`. `ORDER_PROPOSED` is appended. Orders can be listed filtered by `exceedance_id` or `status`, and a single order's computed amounts are recomputed every time it is read.

Issuance by a `Regulator` requires `PROPOSED` (`ERR_CONSENT_ORDER_INVALID_STATE`), stamps `issued_at` with the logical clock, moves the order `PROPOSED → ISSUED` and starts the accrual clock: the violation date is the calendar date, in UTC, of the linked exceedance's `detected_at`. `ORDER_ISSUED` is appended. The facility's answer is an appeal by an `EnvironmentalManager`, whose payload must carry `appeal_grounds` (the grounds are not persisted on the order): from `ISSUED` (`ERR_CONSENT_ORDER_INVALID_STATE`) the order moves to `UNDER_APPEAL`, and accrual continues through the appeal without pause (`ORDER_APPEALED`).

Penalty accrual runs on whole days. `accrued_days` counts the whole days from the violation date to the end date, and is never less than one; the end date is the `cure_date` once the order is `FINAL` or `SATISFIED`, and the current logical clock date while it is not. Under the `PER_DAY` variant the gross assessment is the base penalty plus the daily accrual multiplied by the accrued days. Under the `ECONOMIC_BENEFIT` variant the accrued days are divided by thirty and rounded up to a whole number of months, and the gross is the base penalty plus the avoided cost multiplied by the month count and by the gravity factor, with that product rounded half-up to whole cents. Either way, the gross is capped at the statutory cap. The two variants diverge on identical data: a base of 1000000 cents assessed over 10 days yields 1500000 cents under `PER_DAY` at 50000 per day, but 4000000 cents under `ECONOMIC_BENEFIT` with an avoided cost of 2000000, one month and a gravity factor of 1.5. `provisional_amount_cents` is this capped gross computed against the current clock date; because finalization fixes the end date at the cure date, the provisional and final amounts diverge whenever the clock is read before cure — both are exposed fields.

Finalization by a `Regulator` — allowed from `ISSUED` or `UNDER_APPEAL` (`ERR_CONSENT_ORDER_INVALID_STATE`), the latter being the appeal-upheld path with identical effects — stamps `finalized_at`, resolves the `cure_date`, and fixes the money. The cure date is the `resolved_at` of the linked exceedance's corrective action when that action stands `VERIFIED` at finalize time, and is `finalized_at` itself otherwise. `final_amount_cents` is then computed in a pinned three-step order: first, the capped gross assessment at the cure date is computed exactly as above — this figure never depends on the mitigation credit; second, the mitigation credit is determined as the smaller of one quarter of that capped gross (rounded half-up to whole cents) and the verified corrective cost, where the verified corrective cost is the exceedance's corrective action's `actual_cost_cents` if that action stands `VERIFIED` or `CLOSED` at finalize time and zero otherwise; third, the final amount is the capped gross minus the credit, never below zero. `outstanding_cents` is set to the final amount, and `ORDER_FINAL` is appended.

Payment against the order is a `ComplianceOfficer` duty and an append-only ledger. Posting requires the order `FINAL` (`ERR_CONSENT_ORDER_NOT_PAYABLE`); each line carries a `direction` of `PAYMENT` or `REFUND` and an `amount_cents` strictly greater than zero. A `PAYMENT` may not exceed the order's current `outstanding_cents` (`ERR_PAYMENT_AMOUNT_INVALID`, HTTP 422); a `REFUND` may not exceed the net amount actually collected, that is `paid_cents` minus `refunded_cents` (`ERR_REFUND_EXCEEDS_PAID`, HTTP 422). Every accepted line records `consent_order_id` tying it to its order, is stamped `posted_at` from the logical clock, stands in `POSTED`, is never mutated afterward, and appends a `PAYMENT_POSTED` audit entry; per §2.4 it carries `id` and `created_at` only. The order's derived totals track the ledger: `paid_cents` is the sum of `POSTED` lines in the `PAYMENT` direction, `refunded_cents` the sum in the `REFUND` direction, and `outstanding_cents` is the final amount minus the net of payments over refunds — zero until the order is `FINAL`. The ledger is listable per order.

Satisfaction is automatic: when a posting drives `outstanding_cents` to exactly zero, the order moves `FINAL → SATISFIED`, the linked exceedance's enforcement dimension moves `ORDER_ISSUED → RESOLVED`, the permit's `compliance_posture` is recomputed — with no other live enforcement and no open corrective actions, it can finally return to `GOOD_STANDING` — and `ORDER_SATISFIED` is appended against the `system` actor. `SATISFIED` is terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`; all read endpoints return `200 OK`. Request payloads, preconditions and side effects for each operation are specified in §2 and §3; this table is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/npdes/permits` | Create a permit in `DRAFT` | EnvironmentalManager |
| GET | `/npdes/permits` | List permits | Any |
| GET | `/npdes/permits/{id}` | Get one permit, including computed posture and counters | Any |
| POST | `/npdes/permits/{id}/issue` | Issue a `DRAFT` permit, moving it to `ACTIVE` | EnvironmentalManager |
| POST | `/npdes/permits/{id}/terminate` | Terminate an `ACTIVE` permit, cascading to outfalls and samples | EnvironmentalManager |
| POST | `/npdes/outfalls` | Create an outfall under a permit (permit must be `DRAFT` or `ACTIVE`) | EnvironmentalManager |
| GET | `/npdes/outfalls` | List outfalls | Any |
| GET | `/npdes/outfalls/{id}` | Get one outfall | Any |
| POST | `/npdes/outfalls/{id}/deactivate` | Deactivate an outfall; its `SCHEDULED` samples are cancelled | EnvironmentalManager |
| POST | `/npdes/outfalls/{id}/reactivate` | Reactivate an outfall while its permit is `ACTIVE` | EnvironmentalManager |
| POST | `/npdes/effluent-limits` | Create an effluent limit, optionally superseding an existing `ACTIVE` one; requires `expected_outfall_version` | EnvironmentalManager |
| GET | `/npdes/effluent-limits` | List effluent limits | Any |
| GET | `/npdes/effluent-limits/{id}` | Get one effluent limit | Any |
| POST | `/npdes/effluent-limits/{id}/rescind` | Rescind a successor limit; its superseded predecessor returns to `ACTIVE` | EnvironmentalManager |
| POST | `/npdes/sampling-events` | Schedule a sampling event (permit `ACTIVE`, outfall `ACTIVE`, covering `ACTIVE` limit required) | FieldSampler |
| GET | `/npdes/sampling-events` | List sampling events | Any |
| GET | `/npdes/sampling-events/{id}` | Get one sampling event, both state dimensions | Any |
| POST | `/npdes/sampling-events/{id}/collect` | Collect within the window; seals custody and auto-appends the `SEAL` record | FieldSampler |
| POST | `/npdes/sampling-events/{id}/cancel` | Cancel a scheduled sampling event | FieldSampler |
| POST | `/npdes/sampling-events/{id}/custody-events` | Append a chain-of-custody event (`TRANSFER`/`RECEIVE_LAB`/`ANALYSIS_START`), advancing the custody dimension | FieldSampler, LabAnalyst |
| GET | `/npdes/sampling-events/{id}/custody-events` | List the sample's custody chain, ordered by `sequence_index` | Any |
| POST | `/npdes/lab-results` | Record an analytical result (custody must be `LAB_RECEIVED` or `ANALYZED`) | LabAnalyst |
| GET | `/npdes/lab-results` | List lab results | Any |
| GET | `/npdes/lab-results/{id}` | Get one lab result | Any |
| POST | `/npdes/lab-results/{id}/validate` | Validate a result (validator differs from analyst); triggers exceedance detection | LabValidator |
| POST | `/npdes/lab-results/{id}/reject` | Reject a result with a reason (segregation applies) | LabValidator |
| POST | `/npdes/lab-results/{id}/resubmit` | Resubmit a rejected result with corrections | LabAnalyst |
| GET | `/npdes/exceedances` | List exceedances | Any |
| GET | `/npdes/exceedances/{id}` | Get one exceedance, both state dimensions and deadlines | Any |
| POST | `/npdes/exceedances/{id}/notify` | Record the 24-hour oral notification (late notification allowed from `ORAL_OVERDUE`) | ComplianceOfficer |
| POST | `/npdes/exceedances/{id}/file-report` | File the 5-day written report | ComplianceOfficer |
| POST | `/npdes/exceedances/{id}/close` | Close an exceedance whose corrective action is verified | ComplianceOfficer |
| POST | `/npdes/dmrs` | Generate a Discharge Monitoring Report for an outfall and period (computes counts, ratio and summary lines) | ComplianceOfficer |
| GET | `/npdes/dmrs` | List DMRs | Any |
| GET | `/npdes/dmrs/{id}` | Get one DMR | Any |
| POST | `/npdes/dmrs/{id}/certify` | Certify a `DRAFT` DMR (certifier differs from preparer; completeness and exceedance gates) | ComplianceOfficer |
| POST | `/npdes/dmrs/{id}/submit` | Submit a `CERTIFIED` DMR (all period exceedances must be `WRITTEN_FILED` or `CLOSED`) | ComplianceOfficer |
| POST | `/npdes/dmrs/{id}/agency-review` | Agency decision on a `SUBMITTED` DMR (`ACCEPTED`, or `REJECTED` with deficiency notes) | Regulator |
| POST | `/npdes/dmrs/{id}/revise` | Return a `REJECTED` DMR to `DRAFT`; recomputes the summary from current `VALIDATED` results | ComplianceOfficer |
| POST | `/npdes/swppp-plans` | Create a stormwater pollution prevention plan in `DRAFT` | FacilityInspector |
| GET | `/npdes/swppp-plans` | List SWPPP plans | Any |
| GET | `/npdes/swppp-plans/{id}` | Get one SWPPP plan | Any |
| POST | `/npdes/swppp-plans/{id}/activate` | Activate a plan, superseding the permit's currently `ACTIVE` plan; requires `expected_permit_version` | FacilityInspector |
| POST | `/npdes/inspections` | Schedule an inspection (7-day minimum spacing per plan) | FacilityInspector |
| GET | `/npdes/inspections` | List inspections | Any |
| GET | `/npdes/inspections/{id}` | Get one inspection | Any |
| POST | `/npdes/inspections/{id}/complete` | Complete an inspection with findings; each finding spawns an `OPEN` corrective action | FacilityInspector |
| POST | `/npdes/inspections/{id}/cancel` | Cancel a scheduled inspection | FacilityInspector |
| GET | `/npdes/corrective-actions` | List corrective actions | Any |
| GET | `/npdes/corrective-actions/{id}` | Get one corrective action | Any |
| POST | `/npdes/corrective-actions/{id}/start` | Start work from `OPEN` or `REOPENED` | FacilityInspector |
| POST | `/npdes/corrective-actions/{id}/complete` | Mark work complete, declaring the actual remediation cost | FacilityInspector |
| POST | `/npdes/corrective-actions/{id}/verify` | Regulator verifies completed work (verifier differs from resolver) | Regulator |
| POST | `/npdes/corrective-actions/{id}/reopen` | Regulator reopens a verified action, returning it to the open set | Regulator |
| POST | `/npdes/corrective-actions/{id}/close` | Close a verified corrective action (terminal) | FacilityInspector |
| POST | `/npdes/renewal-applications` | Submit a renewal application (180-day pre-expiration window; one open application per permit) | EnvironmentalManager |
| GET | `/npdes/renewal-applications` | List renewal applications | Any |
| GET | `/npdes/renewal-applications/{id}` | Get one renewal application | Any |
| POST | `/npdes/renewal-applications/{id}/start-review` | Agency starts review | Regulator |
| POST | `/npdes/renewal-applications/{id}/request-info` | Agency requests additional information | Regulator |
| POST | `/npdes/renewal-applications/{id}/resume-review` | Agency resumes review after information received | Regulator |
| POST | `/npdes/renewal-applications/{id}/approve` | Approve renewal: creates the successor permit and cascades supersession; requires `expected_permit_version` | Regulator |
| POST | `/npdes/renewal-applications/{id}/deny` | Deny a renewal application | Regulator |
| POST | `/npdes/consent-orders` | Propose a consent order against an exceedance (sets enforcement `ORDER_ISSUED`) | Regulator |
| GET | `/npdes/consent-orders` | List consent orders | Any |
| GET | `/npdes/consent-orders/{id}` | Get one consent order; provisional and final amounts recomputed at read | Any |
| POST | `/npdes/consent-orders/{id}/issue` | Issue the order; accrual starts from the violation date | Regulator |
| POST | `/npdes/consent-orders/{id}/appeal` | Facility appeals the order (accrual continues) | EnvironmentalManager |
| POST | `/npdes/consent-orders/{id}/finalize` | Finalize the assessment: resolves the cure date, applies the mitigation credit, fixes the final amount | Regulator |
| POST | `/npdes/consent-orders/{id}/payments` | Post a payment or refund against a `FINAL` order; outstanding of exactly zero auto-satisfies the order | ComplianceOfficer |
| GET | `/npdes/consent-orders/{id}/payments` | List the payment ledger of a consent order | Any |
| GET | `/npdes/audit-entries` | List audit log entries (append-only hash chain), filterable by entity | Any |
| POST | `/npdes/_clock/set_current_utc` | Advance the test-driving logical clock; runs the sweep of time-based transitions | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_OUTFALL_NOT_FOUND` | 404 Not Found |
| `ERR_LIMIT_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_RESULT_NOT_FOUND` | 404 Not Found |
| `ERR_EXCEEDANCE_NOT_FOUND` | 404 Not Found |
| `ERR_DMR_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_CORRECTIVE_ACTION_NOT_FOUND` | 404 Not Found |
| `ERR_RENEWAL_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PARAMETER_MISMATCH` | 400 Bad Request |
| `ERR_UNIT_MISMATCH` | 400 Bad Request |
| `ERR_LIMIT_SUPERSEDE_MISMATCH` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PERMIT_NOT_IN_DRAFT` | 409 Conflict |
| `ERR_PERMIT_NOT_ISSUABLE` | 409 Conflict |
| `ERR_PERMIT_NO_OUTFALL` | 409 Conflict |
| `ERR_OUTFALL_NO_ACTIVE_LIMIT` | 409 Conflict |
| `ERR_PERMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTFALL_INACTIVE` | 409 Conflict |
| `ERR_OUTFALL_NOT_INACTIVE` | 409 Conflict |
| `ERR_LIMIT_NOT_ACTIVE` | 409 Conflict |
| `ERR_LIMIT_NOT_A_SUCCESSOR` | 409 Conflict |
| `ERR_LIMIT_RANGE_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_PERMIT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_OUTFALL_NUMBER` | 409 Conflict |
| `ERR_NO_ACTIVE_LIMIT` | 409 Conflict |
| `ERR_SAMPLE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_COLLECTION_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_CUSTODY_OUT_OF_ORDER` | 409 Conflict |
| `ERR_SAMPLE_NOT_IN_LAB` | 409 Conflict |
| `ERR_CUSTODY_NOT_ANALYZED` | 409 Conflict |
| `ERR_RESULT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RESULT_NOT_REJECTED` | 409 Conflict |
| `ERR_HOLDING_TIME_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_NOTIFICATION_STATE` | 409 Conflict |
| `ERR_EXCEEDANCE_NOT_CLOSABLE` | 409 Conflict |
| `ERR_DMR_NOT_DRAFT` | 409 Conflict |
| `ERR_DMR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_DMR_NOT_SUBMITTED` | 409 Conflict |
| `ERR_DMR_NOT_REJECTED` | 409 Conflict |
| `ERR_DMR_MONITORING_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DMR_EXCEEDANCES_UNRESOLVED` | 409 Conflict |
| `ERR_PLAN_NOT_DRAFT` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_INSPECTION_NOT_SCHEDULED` | 409 Conflict |
| `ERR_INSPECTION_TOO_SOON` | 409 Conflict |
| `ERR_CORRECTIVE_ACTION_INVALID_STATE` | 409 Conflict |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_RENEWAL_ALREADY_PENDING` | 409 Conflict |
| `ERR_RENEWAL_NOT_SUBMITTED` | 409 Conflict |
| `ERR_RENEWAL_NOT_UNDER_REVIEW` | 409 Conflict |
| `ERR_RENEWAL_NOT_INFO_REQUESTED` | 409 Conflict |
| `ERR_CONSENT_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_CONSENT_ORDER_NOT_PAYABLE` | 409 Conflict |
| `ERR_PAYMENT_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_REFUND_EXCEEDS_PAID` | 422 Unprocessable Entity |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |

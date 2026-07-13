# Air Quality Permit & Emissions Inventory API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Air Quality Permit and Emissions Inventory API, a regulatory system that mediates the relationship between industrial facilities and the air-quality agency that oversees them. The platform tracks a facility from its first registration, through the registration of individual emitting units, the determination of which permitting regime applies to it, the issuance and renewal of its permits, the continuous and periodic monitoring of its emissions, the annual reporting and fee assessment of its emissions inventory, and the full enforcement lifecycle that follows a limit breach, a late report, a public complaint, or a failed inspection.

The central design tension the API resolves is that a facility's regulatory posture is never a single fact recorded in one place: it is the emergent product of the units it operates, the permits it holds, the exceedance events open against it, and the enforcement actions pending against it. A source that is shut down changes the facility's applicability track; a stack test that fails opens an exceedance and pushes the facility into deviation; a penalty assessed against the facility suspends its operating units and revokes its issued permit. The system is therefore built around immediate, cascading consistency: every write that touches one of these dimensions reconciles the others in the same transaction. This document describes the entities, the state machines that govern their transitions, the calculations that derive fees and penalties, and the validation rules that protect the whole.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that every endpoint honours.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request that omits `X-User-Role` or presents a value that is not one of the recognized roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes five roles: `FacilityOperator`, `PermitReviewer`, `Inspector`, `EnforcementOfficer`, and `Anonymous`. When a recognized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `FacilityOperator`, `X-User-ID` is the `id` of the acting `Facility`; ownership checks on any facility-owned resource compare that resource's `facility_id` (directly, or by walking from a child resource up to its owning facility) against `X-User-ID`. When a `FacilityOperator` attempts an operator-owned write on a resource whose facility is not the one named by `X-User-ID`, the request is rejected with `ERR_NOT_FACILITY_OWNER` (HTTP 403); this ownership guard applies to source registration, inventory submission and amendment, permit submission, exceedance reporting, and penalty payment. When `X-User-Role` is `PermitReviewer`, `Inspector`, or `EnforcementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `Anonymous`, `X-User-ID` is likewise an opaque, unauthenticated public identifier tied to no entity; this role exists only to file public complaints and to record public comments.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order, with ties (resources sharing the same `created_at` under the logical clock) broken by the order in which the resources were created. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

All primary resources carry a set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, drawn from the logical clock (§2.6) and fixed at creation. `updated_at` is an ISO 8601 UTC timestamp, likewise drawn from the logical clock, refreshed on every mutation of the resource, and `version` is an integer that starts at 1 on creation and increments by one on every mutation. All entities in this system carry the full set — `id`, `created_at`, `updated_at`, and `version`. Whenever a derived field on a resource changes — a facility's `potential_to_emit_tpy`, `compliance_status`, `open_exceedance_count`, or `fee_balance_cents`, a source's `lifecycle_status` or `monitoring_status`, an inventory's computed totals and fees — that change is itself a mutation that refreshes `updated_at` and increments `version`. In particular, registering an emission source and certifying an emissions inventory each advance the owning facility's `version` by exactly one; these are the two writes protected by optimistic concurrency control (see §2.9).

### 2.5. Nested Resource Retrieval and Path Validation

Many endpoints address a resource nested beneath a parent — a facility's sources, a permit's public notices, a source's stack tests or CEM blocks or exceedances, a complaint's inspections. For any such request, the system validates the path identifiers left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource, before evaluating any deeper identifier or any business rule. Existence of every path-referenced and body-referenced resource is confirmed before state or business checks run.

### 2.6. The Logical Clock and Temporal Windows

All deadline, comment-window, test-window, inspection-window, and variance-window rules are evaluated against a server-controlled logical clock, never against wall-clock time. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and it holds that value until it is explicitly advanced. An administrative test-driving capability, available to every authenticated role, sets the clock to a supplied `to_iso8601` instant; advancing the clock is what causes comment windows to close, report deadlines to lapse, and stack-test windows to become conductable. Timestamps recorded by the system — a permit's `issued_at`, an inventory's `certified_at`, an exceedance's `reported_at`, a stack test's conduct time — are drawn from this logical clock at the moment of the transition.

Two conventions govern interval fields. A public-notice comment window runs from an inclusive `comment_open_at` to an exclusive `comment_close_at`. A stack-test window runs from an inclusive `scheduled_start` to an inclusive `scheduled_end`. An inspection window is half-open, from an inclusive `scheduled_start` to an exclusive `scheduled_end`. A variance window runs from an inclusive `variance_start` to an exclusive `variance_end`.

### 2.7. Compliance Posture and Cascading Consistency

A facility's `compliance_status` is a derived posture that gates its child operations, and the system keeps it reconciled at all times. It begins `COMPLIANT`. It becomes `DEVIATION` when at least one exceedance event on the facility's sources is `OPEN` or `REPORTED_LATE`. It becomes `ENFORCEMENT` when an enforcement action on the facility is `INITIATED` or, after payment, has lifted a suspension. It becomes `SUSPENDED` when a penalty is assessed against the facility. When more than one of these conditions holds simultaneously, the most severe posture prevails, in descending precedence `SUSPENDED` (a penalty is assessed), then `ENFORCEMENT` (an enforcement action is `INITIATED` or `PAID`), then `DEVIATION` (an open or late-reported exceedance), then `COMPLIANT`. The facility also maintains `open_exceedance_count`, the number of its sources' exceedance events currently in `OPEN` or `REPORTED_LATE`.

Cascades propagate in a single transaction. When a penalty is assessed, the facility moves to `SUSPENDED`, every one of its emission sources whose `lifecycle_status` is `OPERATING` moves to `SUSPENDED`, and any `ISSUED` permit on the facility moves to `REVOKED`. When that penalty is later paid, the facility moves from `SUSPENDED` to `ENFORCEMENT` and every source whose `lifecycle_status` is `SUSPENDED` returns to `OPERATING`. Each entity a cascade touches is independently mutated, refreshing its `updated_at` and incrementing its `version`. Whenever an exceedance is reported or resolved, or an enforcement action is dismissed, paid, or closed, the facility's `open_exceedance_count` and `compliance_status` are recomputed toward `COMPLIANT` when no other open exceedance or pending enforcement remains.

### 2.8. Emissions Fees, Penalties, and Monetary Precision

Emissions fees, assessed penalties, and the facility fee ledger are all held as integer cents. The facility's `fee_balance_cents` is a running ledger whose invariant is that it always equals the sum of `assessed_fee_cents` over the facility's `CERTIFIED` inventories: certifying an inventory increases the balance by that inventory's assessed fee, and amending a certified inventory reverses exactly that debit. Tonnage figures are held to their stated precision — line-item `reported_tons` at three decimal places, an inventory's `total_emissions_tons` at two decimal places, a source's potential-to-emit values at three decimal places — and every rounding operation uses the round-half-up convention. Concentration and rate comparisons are exact numeric comparisons. The specific formulas, tier boundaries, and constants are given in the workflow narratives of §3.

### 2.9. Optimistic Concurrency Control

Two writes are guarded against acting on a stale view of a facility, because both read and mutate facility-level derived state. Registering an emission source recomputes the facility's potential-to-emit and may flip its applicability track; certifying an emissions inventory debits the facility's fee ledger and reads its compliance posture. Each of these two requests must carry `expected_facility_version`, a non-optional field carrying the client's last observed `version` of the target `Facility`. If `expected_facility_version` does not equal the facility's current `version` — because another source registration already moved the potential-to-emit, another certification already debited the ledger, or a cascade already changed the compliance posture since the client last read the facility — the request is rejected with `ERR_STALE_FACILITY_VERSION` (HTTP 412), so the operator re-reads the facility before proceeding. No other endpoint takes a version field.

### 2.10. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed priority order, and the first failing condition determines the returned error. The order is: (1) authentication — `X-User-Role` present and recognized, else `ERR_UNAUTHENTICATED` (401); (2) role authorization for the operation, else `ERR_FORBIDDEN_ROLE` (403); (3) facility ownership for operator-owned writes, else `ERR_NOT_FACILITY_OWNER` (403); (4) existence of all referenced resources, else `ERR_NOT_FOUND` (404); (5) the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE` (409); (6) the cross-entity facility-not-suspended gate where it applies, else `ERR_FACILITY_SUSPENDED` (409); (7) the notice-closed precondition for permit issuance, else `ERR_NOTICE_NOT_CLOSED` (409); (8) the unresolved-exceedance gate for certification, else `ERR_UNRESOLVED_EXCEEDANCE` (409); (9) public-notice window overlap, else `ERR_NOTICE_WINDOW_OVERLAP` (409); (10) stack-test window conflict, else `ERR_STACK_TEST_CONFLICT` (409); (11) inspection window overlap, else `ERR_INSPECTION_OVERLAP` (409); (12) permit-track match on submit, else `ERR_PERMIT_TRACK_MISMATCH` (422); (13) interval validity, else `ERR_INVALID_INTERVAL` (422); (14) unique reporting year per facility, else `ERR_DUPLICATE_INVENTORY_YEAR` (409); (15) the at-least-one-line-item gate for inventory submission, else `ERR_NO_LINE_ITEMS` (409); (16) the open-comment-window gate for public comments, else `ERR_COMMENT_WINDOW_CLOSED` (409); (17) the optimistic-concurrency version match, else `ERR_STALE_FACILITY_VERSION` (412); and finally (18) request-body well-formedness — required fields present, enum values valid, numbers within range — else `ERR_INVALID_REQUEST` (400).

## 3. Business Logic & Workflows

### 3.1. Facility Registration and Title V Applicability

A `FacilityOperator` establishes a **Facility** by supplying its legal `name` (which must be non-empty), its `operator_name`, and its `county` of record. A freshly registered facility starts with `permit_track` equal to `UNPERMITTED`, a `potential_to_emit_tpy` of 0, a `compliance_status` of `COMPLIANT`, an `open_exceedance_count` of 0, and a `fee_balance_cents` of 0. The facility is the aggregate root: sources, permits, inventories, complaints, inspections, and enforcement actions all reference it by `facility_id`, and reads expose the facility's computed potential-to-emit, applicability track, compliance posture, and fee balance. Facilities may be listed and filtered by `county` and by `compliance_status`.

The operator then registers each emitting unit as an **EmissionSource** under the facility, supplying `facility_id`, the `source_type` (one of `BOILER`, `GENERATOR`, `FLARE`, `PROCESS_VENT`, or `STORAGE_TANK`), and its `pollutant` (one of `NOX`, `SO2`, `CO`, `PM`, or `VOC`). Two rate parameters drive the potential-to-emit: `max_hourly_rate_lbs`, the maximum uncontrolled emission rate in pounds per hour (which must be greater than zero), and `operating_hours_per_year`, the permitted annual operating hours (an integer from 1 to 8760 inclusive). Registration also carries `expected_facility_version` for the concurrency guard described in §2.9. Upon registration, the source's uncontrolled potential to emit, `uncontrolled_pte_tpy`, is the maximum hourly rate in pounds multiplied by the annual operating hours, divided by 2,000 pounds per ton, rounded half-up to three decimal places. The controlled figure, `controlled_pte_tpy`, is the uncontrolled potential multiplied by one minus the `control_efficiency`, again rounded half-up to three decimal places (see §3.4 for the role of `control_efficiency` and `permit_limit_ppm`).

Registering or shutting down a source recomputes the facility's `potential_to_emit_tpy` as the sum of `uncontrolled_pte_tpy` over all of the facility's sources whose `lifecycle_status` is not `SHUTDOWN`, rounded half-up to three decimal places — the uncontrolled, worst-case figure is used for applicability, ignoring control efficiency entirely. The facility's `permit_track` is then re-derived from that total: it is `TITLE_V` when the potential-to-emit is at least 100 tons per year (a value of exactly 100.000 tons per year is Title V), `PERMIT_BY_RULE` when the potential-to-emit is greater than zero but below 100 tons per year, and `UNPERMITTED` when it is exactly zero. Registering a source increments the facility's `version` by one.

### 3.2. Source Lifecycle and Shutdown

An emission source advances along two independent dimensions. Its operational dimension, `lifecycle_status`, starts at `REGISTERED`. A `PermitReviewer` marks a registered source `PERMITTED` (this same advance also happens automatically for Title V facilities at permit issuance, described in §3.3), permitted only while the source is `REGISTERED`. The `FacilityOperator` moves a `PERMITTED` source to `OPERATING`, which is allowed only while the source is `PERMITTED` and only while the facility's `compliance_status` is not `SUSPENDED` — a suspended facility blocks this start with `ERR_FACILITY_SUSPENDED`. The operator may permanently shut a source down from any of `PERMITTED`, `OPERATING`, or `SUSPENDED`, moving it to the terminal `SHUTDOWN` state; shutting down recomputes the facility's `potential_to_emit_tpy` over the remaining non-`SHUTDOWN` sources — equivalently reducing it by exactly the shut-down source's `uncontrolled_pte_tpy` — and re-derives `permit_track`. A source may also be driven to `SUSPENDED` from `OPERATING` and back to `OPERATING` from `SUSPENDED` only by the facility-level penalty and payment cascades of §2.7, never by direct request. Any transition attempted from a state that does not permit it is rejected with `ERR_INVALID_STATE`.

The monitoring dimension, `monitoring_status`, evolves separately and starts at `UNMONITORED`. It becomes `STACK_TESTED` when a stack test on the source passes, and it becomes `CEM_ACTIVE` when the first continuous-emissions data block is accepted for the source. These two monitoring outcomes are independent of the operational lifecycle and of each other.

### 3.3. The Permitting Workflow

A `FacilityOperator` opens a **Permit** for a facility by supplying `facility_id` and the requested `permit_type` (`PERMIT_BY_RULE` or `TITLE_V`); the permit begins in `DRAFT` with a `renewal_count` of 0 and a null `issued_at`. The operator submits the draft, which is allowed only while the permit is `DRAFT` and only when the requested `permit_type` matches the facility's current `permit_track` — submitting a `TITLE_V` permit is permitted only when the facility's track is `TITLE_V`; a mismatch is rejected with `ERR_PERMIT_TRACK_MISMATCH`. Submission moves the permit `DRAFT → SUBMITTED`.

A `PermitReviewer` drives the remainder of the review. Beginning review moves the permit `SUBMITTED → UNDER_REVIEW`. From `UNDER_REVIEW` the reviewer may return the application for revision, moving it back `UNDER_REVIEW → DRAFT` (the revision loop), or open the public comment period, moving it `UNDER_REVIEW → PUBLIC_NOTICE`; opening the comment period requires that a public notice already exist for this permit — when several notices exist for the permit, the most recently created one is the linked notice throughout the workflow (including at issuance) — with its `comment_open_at` and `comment_close_at` set, and it sets that linked notice's `status` to `OPEN` (reopening it even if it was `CLOSED`). Issuing the permit moves it `PUBLIC_NOTICE → ISSUED` and is allowed only while the permit is `PUBLIC_NOTICE` and only when the linked public notice's `status` is `CLOSED`; issuing against a notice that is not yet closed is rejected with `ERR_NOTICE_NOT_CLOSED`. Issuance sets `issued_at` to the current logical clock, and — when the facility's `permit_track` is `TITLE_V` — advances every one of the facility's sources whose `lifecycle_status` is `REGISTERED` to `PERMITTED`.

An issued permit can cycle through renewal: the `FacilityOperator` starts a renewal, moving it `ISSUED → RENEWAL_PENDING`, and a `PermitReviewer` completes it, moving it `RENEWAL_PENDING → ISSUED`, incrementing `renewal_count` by one and refreshing `issued_at`. An issued permit is also revoked — moved to the terminal `REVOKED` state — as a cascade when an enforcement action on the facility reaches `PENALTY_ASSESSED`; a revoked permit is terminal and cannot be renewed. Any of these transitions attempted out of turn is rejected with `ERR_INVALID_STATE`.

The **PublicNotice** itself is created by a `PermitReviewer` with `permit_id`, `comment_open_at`, and `comment_close_at`; it starts `OPEN` with a `comment_count` of 0. The proposed comment window must not overlap any other notice on permits of the same facility, treating the windows as closed intervals; an overlap is rejected with `ERR_NOTICE_WINDOW_OVERLAP`, and a window whose `comment_close_at` is not strictly after its `comment_open_at` is rejected with `ERR_INVALID_INTERVAL`. Members of the public act through the `Anonymous` role: a public comment supplies its `comment_text` and increments the notice's `comment_count` by one, but is accepted only while the notice's `status` is `OPEN` and the logical clock is strictly before `comment_close_at`; otherwise it is rejected with `ERR_COMMENT_WINDOW_CLOSED`. A recorded comment returns `201 Created`, with the updated notice as its `data`, even though it modifies the existing notice rather than creating a stand-alone resource. After the window has elapsed, the `PermitReviewer` closes the notice, moving its `status` from `OPEN` to `CLOSED`, which is the precondition that unlocks issuance.

### 3.4. Stack Testing and Continuous Emissions Monitoring

Two monitoring mechanisms feed the compliance picture, and both belong to the `Inspector`. When a source is registered, the operator also supplies its `control_efficiency` — the fractional removal efficiency of its control device, defaulting to 0 for an uncontrolled unit and constrained to be at least 0 and strictly below 1 — and its `permit_limit_ppm`, the permitted concentration limit (which must be greater than zero) against which continuous monitoring is judged.

An `Inspector` schedules a **StackTest** on a source with `source_id`, an inclusive `scheduled_start`, and an inclusive `scheduled_end`; the test begins `SCHEDULED`. The proposed window must not overlap, and must be at least 7 days apart from, any other stack test on the same source, treating the windows as closed intervals with a seven-day buffer between them; a conflict is rejected with `ERR_STACK_TEST_CONFLICT`, and a window whose `scheduled_end` is before its `scheduled_start` is rejected with `ERR_INVALID_INTERVAL`. The inspector conducts the test only while it is `SCHEDULED` and only once the logical clock has reached `scheduled_start`, supplying the `measured_rate_lbs` observed on site; conducting moves the test `SCHEDULED → CONDUCTED` and stores the measured rate. The system then resolves the outcome immediately: if the measured rate is less than or equal to the source's `max_hourly_rate_lbs`, the test moves `CONDUCTED → PASSED` and the source's `monitoring_status` becomes `STACK_TESTED`. If instead the measured rate is greater than the source's `max_hourly_rate_lbs`, the test moves `CONDUCTED → FAILED` and the system opens an exceedance event of type `EXCEEDANCE` in `OPEN` status on that source, with its `magnitude_pct` set to the measured rate minus the maximum rate, divided by the maximum rate, multiplied by 100, rounded half-up to two decimal places — which in turn pushes the facility into `DEVIATION` as described in §3.5.

Continuous monitoring is recorded as a **CEMDataBlock**, supplied by an `Inspector` with `period_start`, an exclusive `period_end`, and the block's `avg_concentration_ppm` (which must be at least zero). Accepting a block computes `is_exceedance` as true if and only if the block's `avg_concentration_ppm` is strictly greater than the source's `permit_limit_ppm` — equality is not an exceedance — and the first accepted block for a source sets its `monitoring_status` to `CEM_ACTIVE`.

### 3.5. Exceedances and Deviation Reporting

An **ExceedanceEvent** records either a limit breach or an operational non-conformance. An `Inspector` may file one directly with `source_id`, an `event_type` of `EXCEEDANCE` or `DEVIATION`, the `detected_at` instant, and an optional `magnitude_pct` (defaulting to 0, and never negative), which drives the severity tier used in penalty calculation. Filing an exceedance, like a stack-test failure, starts it in `OPEN` with a null `reported_at`, increases the facility's `open_exceedance_count` by one, and moves the facility's `compliance_status` to `DEVIATION`.

The `FacilityOperator` reports an open exceedance, and the outcome forks on a 72-hour deadline measured from `detected_at`. Both branches require the event to be `OPEN` and both set `reported_at` to the current logical clock. If the logical clock is at or before 72 hours past `detected_at`, the event moves `OPEN → REPORTED`, the facility's `open_exceedance_count` decreases by one, and if that count reaches zero and no enforcement is pending the facility's compliance posture is recomputed toward `COMPLIANT`. If instead the logical clock is later than 72 hours past `detected_at`, the event moves `OPEN → REPORTED_LATE`, and the system opens an enforcement action against the facility with `origin` `LATE_EXCEEDANCE`, `action_type` `NOTICE_OF_VIOLATION`, and `status` `INITIATED`, driving the facility's `compliance_status` to `ENFORCEMENT`. Reporting an event not in `OPEN` is rejected with `ERR_INVALID_STATE`.

An `Inspector` resolves a reported event, moving it to the terminal `RESOLVED` state and recomputing the facility's `open_exceedance_count` and compliance posture. A `REPORTED` event may be resolved directly. A `REPORTED_LATE` event may be resolved only once its linked enforcement action has reached `DISMISSED`, `CLOSED`, or `PAID`; until then the resolve is rejected with `ERR_INVALID_STATE`.

### 3.6. Complaints and Inspections

Members of the public act through the `Anonymous` role to file a **Complaint** against a facility, supplying `facility_id`, a non-empty `description`, and a `severity` of `LOW`, `MEDIUM`, or `HIGH`; the complaint starts in `RECEIVED`. An `Inspector` may dismiss a received complaint without inspection, moving it `RECEIVED → DISMISSED`. Complaints may be listed for a facility and filtered by `status`.

An `Inspector` schedules an **Inspection** with `facility_id`, an inclusive `scheduled_start`, an exclusive `scheduled_end`, and an optional `complaint_id` — which is null for a routine, non-complaint-driven inspection. The inspection window must not overlap any other inspection on the same facility, but back-to-back adjacency is allowed because the window is half-open; an overlap is rejected with `ERR_INSPECTION_OVERLAP`, and a window whose `scheduled_end` is before its `scheduled_start` is rejected with `ERR_INVALID_INTERVAL`. Scheduling an inspection that carries a `complaint_id` moves that complaint `RECEIVED → INSPECTION_SCHEDULED`; if the referenced complaint is not in `RECEIVED`, the inspection is still scheduled but the complaint is left unchanged. The inspection itself starts `SCHEDULED` with an `outcome` of `PENDING`.

Completing an inspection requires it to be `SCHEDULED` and an `outcome` of `PASS` or `FAIL` to be supplied; completion moves the inspection `SCHEDULED → COMPLETED` and records the outcome. If the inspection was linked to a complaint, that complaint moves `INSPECTION_SCHEDULED → CLOSED`. If the recorded outcome is `FAIL`, the system opens an enforcement action against the facility with `origin` `INSPECTION_FAIL`, `action_type` `NOTICE_OF_VIOLATION`, and `status` `INITIATED`, and drives the facility's `compliance_status` to `ENFORCEMENT`.

### 3.7. Enforcement, Penalties, and Variances

An `EnforcementOfficer` opens an **EnforcementAction** against a facility with `facility_id`, an `action_type` of `NOTICE_OF_VIOLATION`, `VARIANCE`, or `PENALTY`, and an optional `origin` of `MANUAL` (the default), `LATE_EXCEEDANCE`, or `INSPECTION_FAIL`; a variance also carries its `variance_start` and `variance_end`. The action starts `INITIATED` with a `penalty_cents` of 0. Enforcement actions may be listed for a facility and filtered by `status`. From `INITIATED` the officer chooses one of three branches. Actions may be listed and read by any authenticated role.

Assessing a penalty is allowed only while the action is `INITIATED` and only when its `action_type` is `NOTICE_OF_VIOLATION` or `PENALTY`; it computes `penalty_cents` and cascades. The penalty starts from a severity tier: the tier is 1 by default, becomes 2 when the governing exceedance's `magnitude_pct` is greater than 10, and becomes 3 when that magnitude is greater than 50. For an action whose `origin` is `LATE_EXCEEDANCE`, the governing exceedance is the facility's latest `OPEN` or `REPORTED_LATE` exceedance ordered by `detected_at` ascending with `created_at` ascending as the tie-break, and the number of whole days late is the floor of the difference between its `reported_at` and its `detected_at` divided by 24 hours; for any other origin, the number of days late is zero and the tier defaults to 1. The penalty is 250,000 cents multiplied by the severity tier, plus 50,000 cents for each whole day late, and is then capped at 2,500,000 cents. Assessing the penalty moves the action `INITIATED → PENALTY_ASSESSED`, drives the facility to `SUSPENDED`, suspends every `OPERATING` source, and revokes every `ISSUED` permit, exactly as described in §2.7.

Granting a variance is allowed only while the action is `INITIATED`, only when its `action_type` is `VARIANCE`, and only when `variance_start` and `variance_end` are supplied with `variance_start` strictly before `variance_end` (an invalid window is rejected with `ERR_INVALID_INTERVAL`); it moves the action `INITIATED → VARIANCE_GRANTED` and recomputes the facility's compliance posture for the relief. Dismissing an action is allowed only while it is `INITIATED`, moving it to the terminal `DISMISSED` state and recomputing the facility's posture. A `FacilityOperator` pays an assessed penalty, which is allowed only while the action is `PENALTY_ASSESSED`; payment moves the action `PENALTY_ASSESSED → PAID`, returns the facility from `SUSPENDED` to `ENFORCEMENT`, and returns every `SUSPENDED` source to `OPERATING`. Finally the `EnforcementOfficer` closes a paid action, moving it `PAID → CLOSED` and recomputing the facility's posture toward `COMPLIANT` when no other open enforcement or exceedance remains. Any of these transitions attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.8. The Annual Emissions Inventory and Fee Assessment

A `FacilityOperator` opens an **EmissionsInventory** for a facility-year with `facility_id`, the `reporting_year` (an integer from 2000 to 2100), and the statutory `due_at` deadline; the inventory starts in `DRAFT` with zeroed totals and fees and a null `certified_at`. The reporting year must be unique per facility; a second inventory for the same facility and `reporting_year` is rejected with `ERR_DUPLICATE_INVENTORY_YEAR`. The operator populates the inventory with **InventoryLineItem** rows, each supplying `inventory_id`, the `source_id` it attributes emissions to, a `method` of `ESTIMATED`, `STACK_TEST`, or `CEM`, and the `reported_tons` for that source-year (at least zero, stored to three decimal places). Inventories may be listed for a facility and filtered by `reporting_year`, and line items may be listed and filtered by `inventory_id` and by `source_id`.

Submitting an inventory requires it to be `DRAFT` and to have at least one line item — a submit with zero line items is rejected with `ERR_NO_LINE_ITEMS`. Submission moves the inventory `DRAFT → SUBMITTED` and recomputes both `total_emissions_tons` and the provisional `estimated_fee_cents`. The total emissions are the sum of every line item's `reported_tons` for the inventory, summed first and only then rounded half-up to two decimal places — the individual line items are never rounded to two decimals before summing. A `PermitReviewer` may reject a submitted inventory, returning it `SUBMITTED → DRAFT` for correction.

The fee is a marginal tiered charge on the total emissions tonnage. The first 25 tons are charged at 4,500 cents per ton; the next 75 tons — the portion above 25 tons and up to 100 tons — at 4,000 cents per ton; and every ton above 100 tons at 3,500 cents per ton. That gross charge is rounded half-up to whole cents and then raised, if necessary, to a floor of 50,000 cents. Next, if the resulting amount is below 100,000 cents, a small-emitter discount reduces it to 90% of its value (a 10% reduction), rounded half-up to whole cents. The provisional `estimated_fee_cents` computed at submission stops here. The final `assessed_fee_cents`, computed at certification, applies one further step in this order: if the inventory's `certified_at` is at or after its `due_at`, a 15% late surcharge is applied, multiplying the amount by 1.15 and rounding half-up to whole cents.

Certifying an inventory is performed by a `PermitReviewer` and carries `expected_facility_version` for the concurrency guard of §2.9. It is allowed only while the inventory is `SUBMITTED`, only while the facility's `compliance_status` is not `SUSPENDED` (otherwise `ERR_FACILITY_SUSPENDED`), and only when no emission source referenced by the inventory's line items has an `OPEN` or `REPORTED_LATE` exceedance event (otherwise `ERR_UNRESOLVED_EXCEEDANCE`). Certification moves the inventory `SUBMITTED → CERTIFIED`, computes `assessed_fee_cents` including the late surcharge when applicable, sets `certified_at` to the current logical clock, increases the facility's `fee_balance_cents` by the assessed fee, and increments the facility's `version` by one. Should the facility later need to correct a certified inventory, the `FacilityOperator` amends it, which is allowed only while the inventory is `CERTIFIED` and the facility is not `SUSPENDED`; amendment moves the inventory `CERTIFIED → AMENDED`, decreases the facility's `fee_balance_cents` by exactly that inventory's `assessed_fee_cents` — reversing the certify debit and restoring the ledger invariant — and resets the inventory's `assessed_fee_cents` to 0.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource, including state transitions and clock control, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Register a facility | FacilityOperator |
| GET | `/facilities/{id}` | Fetch a facility | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities` | List facilities | PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/sources` | Register an emission source | FacilityOperator |
| GET | `/sources/{id}` | Fetch a source | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/sources` | List a facility's sources | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/sources/{id}/permit` | Mark a source PERMITTED | PermitReviewer |
| POST | `/sources/{id}/start-operating` | Move a permitted source into OPERATING | FacilityOperator |
| POST | `/sources/{id}/shutdown` | Permanently shut down a source | FacilityOperator |
| POST | `/sources/{id}/cem-data` | Submit a CEM data block | Inspector |
| GET | `/sources/{id}/cem-data` | List CEM blocks for a source | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/sources/{id}/exceedances` | List exceedances for a source | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/permits` | Create a draft permit | FacilityOperator |
| GET | `/permits/{id}` | Fetch a permit | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/permits` | List a facility's permits | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/permits/{id}/submit` | Submit a draft permit | FacilityOperator |
| POST | `/permits/{id}/begin-review` | Begin review | PermitReviewer |
| POST | `/permits/{id}/return-for-revision` | Return permit to DRAFT | PermitReviewer |
| POST | `/permits/{id}/open-public-notice` | Open the public comment period | PermitReviewer |
| POST | `/permits/{id}/issue` | Issue the permit | PermitReviewer |
| POST | `/permits/{id}/start-renewal` | Begin a renewal cycle | FacilityOperator |
| POST | `/permits/{id}/complete-renewal` | Complete a renewal cycle | PermitReviewer |
| POST | `/public-notices` | Create a public notice window | PermitReviewer |
| GET | `/public-notices/{id}` | Fetch a public notice | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/permits/{id}/public-notices` | List a permit's notices | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/public-notices/{id}/comment` | Record a public comment | Anonymous |
| POST | `/public-notices/{id}/close` | Close the comment window | PermitReviewer |
| POST | `/inventories` | Create a draft annual inventory | FacilityOperator |
| GET | `/inventories/{id}` | Fetch an inventory | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/inventories` | List a facility's inventories | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/line-items` | Add a line item to a draft inventory | FacilityOperator |
| GET | `/line-items/{id}` | Fetch a line item | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/line-items` | List/filter line items | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/inventories/{id}/submit` | Submit an inventory | FacilityOperator |
| POST | `/inventories/{id}/reject` | Return a submitted inventory to DRAFT | PermitReviewer |
| POST | `/inventories/{id}/certify` | Certify an inventory | PermitReviewer |
| POST | `/inventories/{id}/amend` | Amend a certified inventory | FacilityOperator |
| POST | `/stack-tests` | Schedule a stack test | Inspector |
| GET | `/stack-tests/{id}` | Fetch a stack test | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/sources/{id}/stack-tests` | List a source's stack tests | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/stack-tests/{id}/conduct` | Record test results | Inspector |
| POST | `/exceedances` | File an exceedance/deviation | Inspector |
| GET | `/exceedances/{id}` | Fetch an exceedance | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/exceedances/{id}/report` | Report an exceedance | FacilityOperator |
| POST | `/exceedances/{id}/resolve` | Resolve a reported exceedance | Inspector |
| POST | `/complaints` | File a public complaint | Anonymous |
| GET | `/complaints/{id}` | Fetch a complaint | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/complaints` | List a facility's complaints | PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/complaints/{id}/dismiss` | Dismiss a complaint | Inspector |
| POST | `/inspections` | Schedule an inspection | Inspector |
| GET | `/inspections/{id}` | Fetch an inspection | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/inspections` | List a facility's inspections | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/complaints/{id}/inspections` | List inspections for a complaint | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/inspections/{id}/complete` | Complete an inspection | Inspector |
| POST | `/enforcement-actions` | Open an enforcement action / variance | EnforcementOfficer |
| GET | `/enforcement-actions/{id}` | Fetch an enforcement action | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| GET | `/facilities/{id}/enforcement-actions` | List a facility's enforcement actions | FacilityOperator, PermitReviewer, Inspector, EnforcementOfficer |
| POST | `/enforcement-actions/{id}/assess-penalty` | Assess a penalty | EnforcementOfficer |
| POST | `/enforcement-actions/{id}/grant-variance` | Grant a variance relief window | EnforcementOfficer |
| POST | `/enforcement-actions/{id}/dismiss` | Dismiss an enforcement action | EnforcementOfficer |
| POST | `/enforcement-actions/{id}/pay` | Pay an assessed penalty | FacilityOperator |
| POST | `/enforcement-actions/{id}/close` | Close a paid enforcement action | EnforcementOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PermitReviewer, Inspector, EnforcementOfficer, FacilityOperator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FACILITY_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FACILITY_SUSPENDED` | 409 |
| `ERR_NOTICE_NOT_CLOSED` | 409 |
| `ERR_UNRESOLVED_EXCEEDANCE` | 409 |
| `ERR_NOTICE_WINDOW_OVERLAP` | 409 |
| `ERR_STACK_TEST_CONFLICT` | 409 |
| `ERR_INSPECTION_OVERLAP` | 409 |
| `ERR_PERMIT_TRACK_MISMATCH` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_STALE_FACILITY_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_COMMENT_WINDOW_CLOSED` | 409 |
| `ERR_NO_LINE_ITEMS` | 409 |
| `ERR_DUPLICATE_INVENTORY_YEAR` | 409 |

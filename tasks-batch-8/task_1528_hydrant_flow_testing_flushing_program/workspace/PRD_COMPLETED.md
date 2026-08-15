# Hydrant Flow Testing API — Product Requirements Document

## 1. Introduction

Municipal water utilities live and die by the reliability of their distribution network, and the humble fire hydrant is where that reliability becomes visible to the public. A hydrant that cannot deliver its required fire flow is a liability; a hydrant that goes out of service without the fire department knowing is a regulatory exposure; a flushing program that cannot demonstrate disciplined coverage drags down the utility's ISO rating and raises insurance premiums for every property in the service area. Yet many utilities still coordinate this work through spreadsheets, paper tags, and radio calls — a pattern that collapses the moment an auditor asks which hydrants were inspected within their cycle, or which out-of-service tags were acknowledged by the fire marshal within the agreed notification window.

This document specifies the Hydrant Flow Testing & Flushing Program API, a system of record for seasonal water-distribution operations. The API tracks the full operational loop: the inventory of municipal and privately owned hydrants organized into pressure zones and seasonal programs; the inspection cycle with supervisor verification and segregation of duties; scheduled fire-flow tests whose pressure readings feed a hydraulic formula that classifies each hydrant against its required fire flow; unidirectional flushing sequences executed step-by-step against valve operations with a strict dechlorination protocol at completion; discolored-water complaint intake that automatically clusters into targeted flushing responses; out-of-service tagging with a fire-department notification handshake and escalation when acknowledgements are late; repair work orders with part reservations, tiered pricing, and budget caps; and the periodic ISO rating snapshot that converts all of this operational evidence into a single weighted score for the rating bureau.

Two design tensions shape the specification. First, the system enforces a strict segregation of duties between the field crew who perform work and the supervisors who verify it — no operator may verify their own inspection, review their own flow test, or approve their own work order. Second, because hydrants sit at the center of several concurrent workflows, the API uses optimistic concurrency control on the hydrant itself so that an inspection can never be opened against a stale view of the asset. A logical clock, administratively settable for test-driving, governs every temporal rule in the system — inspection due tiers, flow-test windows, notification escalation, complaint clustering, and ISO lookback periods all read from the same clock, which is initialized to exactly 2026-08-01T00:00:00Z before any administrative call and never falls back to wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400); a header containing only whitespace is treated as empty. Once headers are present, the role value must appear in the endpoint's authorized role list; a role outside the list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled as follows:

- `ProgramAdmin` — utility program administrator; owns configuration, programs, inventory, the parts catalog, ISO documentation, and the operational sweep.
- `FieldOperator` — distribution field crew; performs inspections, flow tests, flushing, tagging, complaint intake, and work-order drafting.
- `UtilitySupervisor` — supervisor; verifies inspections, reviews flow tests, approves work orders, closes complaints.
- `FireDeptLiaison` — fire department contact; acknowledges out-of-service notifications.
- `PrivateOwnerRep` — private hydrant owner's representative; may record inspection evidence only for privately owned hydrants.

For `ProgramAdmin`, `FieldOperator`, `UtilitySupervisor`, and `FireDeptLiaison`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `performed_by_user_id` on an `Inspection`, `recorded_by_user_id` on a `FlowTest`, `verified_by_user_id` on an `Inspection`, `reviewed_by_user_id` on a `FlowTest`, `acknowledged_by_user_id` on a `HydrantOutage`, `created_by_user_id` on a `RepairWorkOrder`, or `approved_by_user_id` on a `RepairWorkOrder` — but it does not compare the header to any entity's `id` for ownership. When `X-User-Role` is `PrivateOwnerRep`, `X-User-ID` is the `id` of the acting `PrivateOwner`; ownership checks on any resource that references a `PrivateOwner` compare the resource's foreign-key field to `X-User-ID`. This is the mechanism by which a private owner's representative is scoped to their own hydrants when recording inspection evidence.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is rendered from the logical clock (§2.8) on both success and error envelopes.
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

All list endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; out-of-range values are clamped rather than rejected (a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, a negative `offset` becomes 0), while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. `offset` defaults to 0. The response `meta` object for a list call includes `limit`, `offset`, `total_count`, and `has_more`, with `has_more` true exactly when `offset` plus the number of returned items is less than `total_count`. List results are sorted by `created_at` ascending unless otherwise noted, with ties broken by creation order.

### 2.4. Common Resource Properties

Every persisted entity in the system carries a server-minted `id` (a UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits), an `updated_at` timestamp refreshed on every mutation, and a `version` integer that starts at 1 on creation and increments on every mutation of that entity. The `version` field is the backbone of optimistic concurrency control (§2.6). Every entity described in §3 — `FlushingProgram`, `PressureZone`, `PrivateOwner`, `Hydrant`, `Inspection`, `FlowTest`, `FlushSequence`, `WaterQualityComplaint`, `HydrantOutage`, `RepairWorkOrder`, `Part`, and `ISOSnapshot` — carries the full common set; there are no reduced-property entities in this domain.

### 2.5. Precision, Rounding, and Monetary Representation

All monetary amounts are integer cents — `unit_price_cents`, `budget_cap_cents`, `quoted_subtotal_cents`, `quoted_discount_cents`, `quoted_fee_cents`, `quoted_total_cents`, `actual_total_cents`. Where a calculation produces a fractional cent, it rounds half up to a whole cent.

Pressure and flow quantities use mixed precision, and the rounding point within each pipeline is normative. Pitot flow (`pitot_flow_gpm`) is stored at 2 decimal places, rounded half up. Available fire flow at the 20-psi reference (`flow_at_20psi_gpm`) is stored as a whole number of gallons per minute, rounded half up — and the intermediate quantity that feeds that rounding must be the *unrounded* pitot flow, not the stored two-decimal value. Flushed volumes are rounded half up to whole gallons per executed step before any summation. Chlorine mass is divided by a per-tablet neutralization capacity and the result is taken as a ceiling to a whole number of tablets. ISO scores are rounded half up to 1 decimal place.

### 2.6. Optimistic Concurrency Control

Two write endpoints in the system require an explicit expected-version field naming the client's last observed `version` of a parent entity, and reject the request when the parent's current `version` has moved past it.

Creating an inspection requires the request to carry `expected_hydrant_version`, matching the target hydrant's current `version`. If another writer has advanced the hydrant's version since the client last read it — a new inspection, a flow-test result, an outage cascade, a tier recompute — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from opening an inspection against a stale view of the asset.

Approving a work order requires the request to carry `expected_work_order_version`, matching the work order's current `version`. If another writer has advanced the work order's version since the approver last read it — for example by adding a part line after the approver reviewed the order — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so an approval never rests on a stale view of the line set.

Endpoints not listed above do not take a version field.

### 2.7. Seasonal Programs and Their Lifecycle Gates

A `FlushingProgram` represents one seasonal campaign — a `program_year` paired with a `season` of either `SPRING` or `FALL`. The pair `(program_year, season)` is unique across the system; a duplicate create is rejected with `ERR_PROGRAM_ALREADY_EXISTS`. A program begins life in `OPEN` status and may later be closed by a `ProgramAdmin`, moving it to `CLOSED`. Closing is a gate, not a cascade: no child states are mutated when a program closes, but tagging a hydrant out of service — the one operation that requires the program to be `OPEN` — is rejected with `ERR_PROGRAM_NOT_OPEN` once the program has closed. Closing itself also requires the program to be `OPEN`: closing an already-`CLOSED` program is rejected with `ERR_PROGRAM_NOT_OPEN`.

A program carries two maintained counters. `hydrants_out_of_service_count` tracks how many of the program's hydrants are currently `OUT_OF_SERVICE`; it is incremented when an outage is created and decremented when the outage closes. `unacknowledged_notification_count` tracks how many `ACTIVE` outages on the program's hydrants still have a fire-department notification in `PENDING` status; it is incremented when an outage is created and decremented when the fire department acknowledges. Both counters start at zero when the program is created, and the second counter is a hard gate on ISO publication (§3.8).

### 2.8. The Logical Clock

A single logical clock governs every temporal rule in the system: inspection due tiers, flow-test scheduling windows, complaint cluster windows, notification acknowledgement deadlines, and ISO lookback periods all read from it. Before any administrative call, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `ProgramAdmin` may advance the clock to a supplied `to_iso8601` instant through the test-driving endpoint listed in §4; any valid ISO 8601 instant is accepted, with no requirement that it fall after the current reading. The response returns the new `current_utc`, echoing the submitted `to_iso8601` string verbatim.

### 2.9. Nested Resources and Existence Checks

Path resource identifiers are validated left to right: a path of the form `/programs/{id}/iso-snapshots` first confirms the program exists before considering the snapshot. Each missing resource yields its own specific error — `ERR_PROGRAM_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_PRIVATE_OWNER_NOT_FOUND`, `ERR_HYDRANT_NOT_FOUND`, `ERR_INSPECTION_NOT_FOUND`, `ERR_FLOW_TEST_NOT_FOUND`, `ERR_FLUSH_SEQUENCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_ISO_SNAPSHOT_NOT_FOUND`. Foreign-key references in request bodies — `hydrant_id`, `program_id`, `zone_id`, `private_owner_id`, `part_id`, `flush_sequence_id` — must reference existing resources and yield the corresponding not-found error when they do not.

### 2.10. Request Body Schema Discipline

Endpoints with a request body enforce strict schema validation: the body must be a JSON object (a non-object or unparseable body is rejected), required fields must be present, types must be valid, enum values must come from the declared set, and unknown fields are rejected. Endpoints declared with no request-body fields reject any non-empty JSON object body under the same unknown-field rule. Cross-field structural rules are enforced at this layer: `window_end` must be strictly after `window_start` on any windowed resource, a part-line `qty` must be greater than zero, and `private_owner_id` is conditionally required — it must be present when `ownership` is `PRIVATE` and must be absent when `ownership` is `MUNICIPAL` — though this one conditional rule is evaluated immediately after role membership rather than at the schema layer (§2.11). Any violation at this layer yields `ERR_INVALID_REQUEST` (HTTP 400).

### 2.11. Validation Priority Ordering

When multiple validations apply to a single request, they are evaluated in a fixed priority order so that the surfaced error is deterministic. The order is:

1. Header presence (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Body schema (`ERR_INVALID_REQUEST`) — required fields, types, enums, unknown fields, and the cross-field structural rules other than the conditional-required `private_owner_id` rule.
3. Role membership in the endpoint's authorized list (`ERR_FORBIDDEN_ROLE`); the conditional-required `private_owner_id` rule on hydrant creation is evaluated immediately after this layer, surfacing `ERR_INVALID_REQUEST`.
4. Resource existence, left to right across path then body (the `ERR_*_NOT_FOUND` family).
5. Ownership scope on inspection record (`ERR_HYDRANT_OWNERSHIP_MISMATCH`) — evaluated once the target inspection's existence has been confirmed.
6. Segregation of duties (`ERR_SEGREGATION_OF_DUTIES`).
7. Optimistic concurrency (`ERR_STALE_VERSION`).
8. State preconditions — the entity-specific `ERR_*_NOT_*` family at HTTP 409.
9. Physical and safety validity (`ERR_PRESSURE_READING_INVALID`, `ERR_DECHLORINATION_LIMIT_EXCEEDED`).
10. Business constraints (uniqueness, program match, step ordering, steps completeness, open work orders, ISO publish gates).
11. Temporal constraints (flow-test window overlap, results outside the window, zone cooldown).
12. Referential link integrity (`ERR_LINK_HYDRANT_MISMATCH`, `ERR_LINKED_SEQUENCE_NOT_COMPLETED`).
13. Fiscal checks on work-order approval — part availability first (`ERR_INSUFFICIENT_PART_QUANTITY`), then budget cap (`ERR_WORK_ORDER_BUDGET_EXCEEDED`).

The practical consequence is that a request can fail at exactly one layer, and the first layer in this order that fails determines the error. A work-order approval that fails both segregation of duties and a stale version surfaces `ERR_SEGREGATION_OF_DUTIES`; a flow-test result submission that is both outside its window and has physically invalid pressures surfaces the state-layer or temporal-layer error before the pressure check.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Season: Programs, Zones, Owners, and the Hydrant Inventory

A new season begins when a `ProgramAdmin` creates a `FlushingProgram` with a `program_year` and a `season` of `SPRING` or `FALL`. The pair must be unique; a duplicate is rejected with `ERR_PROGRAM_ALREADY_EXISTS`. The new program starts in `OPEN` status with both computed counters at zero. In parallel, the administrator registers the `PressureZone`s the season will operate in — each zone has a `name` and an optional `cooldown_minutes`, defaulting to 60 minutes, which is the minimum gap between the windows of any two non-terminal flush sequences in that zone — and any `PrivateOwner`s whose hydrants will participate, each with a `name` and a `contact_email`.

Hydrant registration is the act that ties these together. A `ProgramAdmin` creates a `Hydrant` by supplying a globally unique `hydrant_number` (a duplicate is rejected with `ERR_HYDRANT_NUMBER_NOT_UNIQUE`), the `program_id` of the owning seasonal program, the `zone_id` of the pressure zone the hydrant sits in, the `ownership` classification (`MUNICIPAL` or `PRIVATE`), the `required_fire_flow_gpm` for the hydrant's location, and optionally the `outlet_diameter_in` (default 2.5 inches) and `discharge_coefficient` (default 0.9) used later by the pitot flow formula. When `ownership` is `PRIVATE`, the payload must include `private_owner_id` referencing a registered `PrivateOwner`; when `ownership` is `MUNICIPAL`, `private_owner_id` must be absent. A violation of this conditional-required rule is rejected with `ERR_INVALID_REQUEST`.

A newly registered hydrant starts with `status` of `IN_SERVICE`, `inspection_tier` of `CURRENT`, `targeted_flush_pending` false, `active_outage_id` and `latest_inspection_id` and `last_verified_inspection_date` all unset, and both computed fire-flow fields — `provisional_fire_flow_gpm` and `approved_fire_flow_gpm` — null. The hydrant list endpoint supports filtering by `program_id`, `zone_id`, `private_owner_id`, `status`, `active_outage_id`, and `latest_inspection_id`, plus pagination.

A hydrant that will never again be part of the network can be decommissioned by a `ProgramAdmin`, moving it from `IN_SERVICE` to `DECOMMISSIONED`. Decommissioning requires the hydrant to be `IN_SERVICE`; the request is rejected with `ERR_HYDRANT_NOT_IN_SERVICE` otherwise. A decommissioned hydrant is excluded from ISO snapshot scope.

### 3.2. The Inspection Cycle: Record, Verify, and the Repair Loop

Every hydrant carries an inspection cycle — twelve months for `MUNICIPAL` hydrants, six months for `PRIVATE` hydrants — and the system derives each hydrant's `inspection_tier` continuously as the logical clock moves. Opening an inspection is a `FieldOperator` action: the request supplies the `hydrant_id`, the planned `scheduled_date`, and critically an `expected_hydrant_version` carrying the operator's last observed `version` of the hydrant. If the hydrant's version has advanced past that value — because a flow result landed, an outage cascade fired, or another inspection was opened — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), so the inspection is never opened against a stale view of the asset. A successful create starts the inspection in `SCHEDULED` status and writes the new inspection's id into the hydrant's `latest_inspection_id`, incrementing the hydrant's `version` by one. The inspection list endpoint supports filtering by `hydrant_id` and `status`.

Recording field findings is ownership-scoped. When the inspection's hydrant is `MUNICIPAL`, only a `FieldOperator` may record; when the hydrant is `PRIVATE`, only a `PrivateOwnerRep` whose `X-User-ID` equals the hydrant's `private_owner_id` may record. A mismatch is rejected with `ERR_HYDRANT_OWNERSHIP_MISMATCH`. The record payload supplies `performed_date`, `defects_found`, and an optional `condition_notes` (default empty). The inspection must be in `SCHEDULED` or `REJECTED` status to be recorded — anything else yields `ERR_INSPECTION_NOT_RECORDABLE`. Recording moves the inspection to `PENDING_VERIFICATION` and stores `performed_by_user_id` from `X-User-ID`. Because `REJECTED` is a recordable state, the same endpoint serves as the resubmission loop after a supervisor rejection: the new `performed_date`, `defects_found`, and `condition_notes` overwrite the prior values (an omitted `condition_notes` resets to empty).

Verification belongs to a `UtilitySupervisor`, who supplies a `decision`. The inspection must be `PENDING_VERIFICATION`; otherwise the request is rejected with `ERR_INSPECTION_NOT_PENDING_VERIFICATION`. Segregation of duties is enforced here: the supervisor's `X-User-ID` must differ from the inspection's `performed_by_user_id`, and a self-verification is rejected with `ERR_SEGREGATION_OF_DUTIES`. When the decision is `VERIFY`, the inspection moves to `VERIFIED`, its `result` is set to `PASS` when `defects_found` is false and to `FAIL` when defects were found, `verified_by_user_id` is recorded, the hydrant's `last_verified_inspection_date` is set to the inspection's `performed_date`, the hydrant's `version` increments by one for that baseline update (and by one more when the tier recomputation changes the tier), and the hydrant's `inspection_tier` is recomputed from the new baseline. When the decision is `REJECT`, the inspection moves to `REJECTED`, `verified_by_user_id` is recorded, and `result` remains `NONE`.

The failure branch of verification is the entry point to the repair workflow: when an inspection verifies with `result` `FAIL`, the system automatically creates a `RepairWorkOrder` in `DRAFT` status whose `hydrant_id` is the failed inspection's hydrant, whose `source_inspection_id` is the failed inspection's id, whose `created_by_user_id` is the literal string `system`, and whose `description` reads "Auto-generated from failed inspection". A supervisor can therefore never silently drop a failed inspection — a draft work order always exists to be picked up.

### 3.3. Fire-Flow Testing: Windows, Pressure Physics, and the Retest Loop

A `FieldOperator` schedules a `FlowTest` for a hydrant by supplying the `hydrant_id`, a `window_start`, and a `window_end`. The window is a half-open interval — a test whose `window_end` equals another scheduled test's `window_start` does not overlap it. The new window must not overlap any other `SCHEDULED` flow test on the same hydrant under half-open arithmetic; touching endpoints are allowed, and any true overlap is rejected with `ERR_FLOW_TEST_WINDOW_OVERLAP`. A new flow test starts in `SCHEDULED` status with `classification` of `NONE` and both computed flow fields null. The flow-test list endpoint supports filtering by `hydrant_id` and `status`.

Submitting results is the heart of the workflow. The test must be `SCHEDULED` (otherwise `ERR_FLOW_TEST_NOT_SCHEDULED`). The logical clock must fall within the scheduled window, both bounds inclusive — a submission at exactly `window_start` or exactly `window_end` is accepted; before `window_start` yields `ERR_FLOW_TEST_WINDOW_NOT_STARTED`, after `window_end` yields `ERR_FLOW_TEST_WINDOW_EXPIRED`. The pressure readings themselves must satisfy a physical validity gate evaluated before any arithmetic: `static_psi` must be strictly greater than `residual_psi`, and `residual_psi` must be strictly greater than 20; a violation is rejected with `ERR_PRESSURE_READING_INVALID` (HTTP 422).

Once the gate passes, the system computes the pitot flow. The pitot flow in gallons per minute is the constant 29.83 multiplied by the hydrant's `discharge_coefficient`, multiplied by the hydrant's `outlet_diameter_in` raised to the second power, multiplied by the square root of `pitot_psi`. The stored `pitot_flow_gpm` is this value rounded half up to 2 decimal places.

The available fire flow at the 20-psi reference residual is computed next, and the evaluation order is pinned. First compute the pitot flow as an unrounded value using the formula above. Then compute the unrounded Q20 by multiplying the unrounded pitot flow by the quantity: the ratio of `static_psi` minus 20 to `static_psi` minus `residual_psi`, that ratio raised to the power 0.54. Then `flow_at_20psi_gpm` is the unrounded Q20 rounded half up to a whole number of gallons per minute. Rounding happens exactly once at the end of this pipeline; an implementation that rounds pitot flow first and feeds the rounded value into Q20 is non-conformant. The test's `classification` is then set to `PASS` when `flow_at_20psi_gpm` is at least the hydrant's `required_fire_flow_gpm`, and to `FAIL` otherwise. The submission also records `recorded_by_user_id` from `X-User-ID`, moves the test to `RESULTS_SUBMITTED`, and writes the new `flow_at_20psi_gpm` into the hydrant's `provisional_fire_flow_gpm`, incrementing the hydrant's `version`.

Review is a `UtilitySupervisor` action gated by segregation of duties: the reviewer's `X-User-ID` must differ from `recorded_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The test must be `RESULTS_SUBMITTED` (else `ERR_FLOW_TEST_NOT_SUBMITTED`). On `APPROVE`, the test moves to `APPROVED`, `reviewed_by_user_id` is recorded, and the hydrant's `approved_fire_flow_gpm` is updated to this test's `flow_at_20psi_gpm` with the hydrant's version incremented. On `REJECT`, the test moves to `REJECTED`, `reviewed_by_user_id` is recorded, and the hydrant's `provisional_fire_flow_gpm` is recomputed from the hydrant's remaining `RESULTS_SUBMITTED` or `APPROVED` tests — taking the most recent by results submission time, with ties broken by `created_at` ascending and any remaining ties by creation order — and set to null when no qualifying test remains, again incrementing the hydrant's version.

This is the operational meaning of the two fire-flow fields. `provisional_fire_flow_gpm` is the field reading that operations consult: it considers tests in either `RESULTS_SUBMITTED` or `APPROVED` and picks the most recent. `approved_fire_flow_gpm` is the regulatory reading that ISO scoring consults: it considers only `APPROVED` tests, so identical underlying data yields a different — and possibly null — value whenever the latest test has not yet been reviewed. Both are null until the first qualifying test exists.

Two loops keep the schedule honest. A test in `REJECTED` or `MISSED` can be rescheduled by a `FieldOperator` supplying a new `window_start` and `window_end`; anything other than `REJECTED` or `MISSED` is rejected with `ERR_FLOW_TEST_NOT_RESCHEDULABLE`, and the new window must not overlap the hydrant's other `SCHEDULED` tests under the same half-open rule (`ERR_FLOW_TEST_WINDOW_OVERLAP`). A successful reschedule moves the test back to `SCHEDULED` with the new window; any previously submitted readings, computed flows, and classification are retained until new results are submitted. A test still in `SCHEDULED` can be cancelled outright by a `FieldOperator` — any other status yields `ERR_FLOW_TEST_NOT_SCHEDULED` — which moves it to `CANCELLED` with `cancel_reason` of `OPERATOR_CANCEL`. The terminal states of a flow test are `APPROVED` and `CANCELLED`; `REJECTED` and `MISSED` are not terminal, because the retest loop returns them to `SCHEDULED`.

### 3.4. Unidirectional Flushing: Step Execution and the Dechlorination Protocol

A unidirectional flushing sequence plans a series of valve operations against a target hydrant. A `FieldOperator` creates a `FlushSequence` by supplying the `program_id`, the `zone_id`, the `hydrant_id` of the flush target, the planned `window_start` and `window_end`, and an ordered list of `steps`. Each step is a structure with `step_index`, `valve_tag`, an `action` of `OPEN` or `CLOSE`, a `status` of `PENDING` or `EXECUTED`, and once executed, `executed_at`, `executed_by_user_id`, `flow_gpm`, and `duration_minutes`. At creation every step must be `PENDING` — a step submitted with `status` `EXECUTED`, or carrying fields outside this structure, is rejected with `ERR_INVALID_REQUEST` — and the steps list may be empty. The `step_index` values must be unique and dense starting from 1, and steps are stored and returned in ascending `step_index` order. The sequence's `program_id` must equal the target hydrant's own `program_id`; a mismatch is rejected with `ERR_PROGRAM_MISMATCH` (HTTP 422). The new sequence starts in `PLANNED` status with `origin` of `SCHEDULED_PROGRAM`. The flush-sequence list endpoint supports filtering by `program_id`, `zone_id`, `hydrant_id`, and `status`.

The zone cooldown enforces spacing between sequences. The gap between the new sequence's window and any other `PLANNED` or `IN_PROGRESS` sequence in the same zone must be at least the zone's `cooldown_minutes`; adjacency closer than that buffer — even by a minute — is rejected with `ERR_SEQUENCE_ZONE_COOLDOWN`. Terminal sequences (`COMPLETED` or `ABORTED`) do not participate in the cooldown check.

Starting a sequence is a `FieldOperator` action that records the `source_chlorine_residual_mg_L` measured at the source — this value becomes the dosing basis for dechlorination at completion. The sequence must be `PLANNED` (else `ERR_SEQUENCE_NOT_PLANNED`) and the target hydrant must be `IN_SERVICE` (else `ERR_HYDRANT_NOT_IN_SERVICE`). Starting moves the sequence to `IN_PROGRESS`.

Executing steps is a strict in-order protocol. Each call to execute a step supplies a `step_index`, the measured `flow_gpm`, and the measured `duration_minutes`. The sequence must be `IN_PROGRESS` (else `ERR_SEQUENCE_NOT_IN_PROGRESS`); the addressed step must exist and be `PENDING`; and every step with a smaller `step_index` must already be `EXECUTED`. A violation of either step condition is rejected with `ERR_STEP_OUT_OF_SEQUENCE`. A successful execution marks the step `EXECUTED` with `executed_at` set to the current logical clock and `executed_by_user_id` set from `X-User-ID`.

Completion is gated by two checks evaluated in a specific order. The safety check is evaluated first: the supplied `final_discharge_residual_mg_L` must be at most 0.1 mg/L — the dechlorination limit — and a reading above that limit is rejected with `ERR_DECHLORINATION_LIMIT_EXCEEDED` (HTTP 422). Only after the safety gate passes does the structural check apply: every step must be `EXECUTED`, else `ERR_STEPS_INCOMPLETE`. Because safety outranks structure, a completion attempt that both exceeds the chlorine limit and has unfinished steps surfaces the chlorine error.

A successful completion computes two derived quantities in a pinned order. The total flushed volume comes first: for each executed step, the step volume is the step's `flow_gpm` multiplied by its `duration_minutes`, rounded half up to a whole number of gallons; `total_flushed_gallons` is the sum of those per-step rounded volumes. The rounding order is normative — round each step first, then sum; summing first and rounding once at the end yields a different total and is forbidden. The dechlorination dose follows, and it consumes the already-rounded `total_flushed_gallons`: the chlorine mass in milligrams is `total_flushed_gallons` multiplied by 3.785 (liters per gallon) multiplied by `source_chlorine_residual_mg_L`; `dechlorination_tablets_required` is the ceiling of that mass divided by 8500 milligrams per tablet. Completion also fires two cascades: every `WaterQualityComplaint` whose `flush_sequence_id` is this sequence and whose status is `LINKED` moves to `RESOLVED`, and the target hydrant's `targeted_flush_pending` is cleared to false with the hydrant's version incremented.

Abortion is the compensating path. A `FieldOperator` may abort a sequence in `IN_PROGRESS` (else `ERR_SEQUENCE_NOT_IN_PROGRESS`). Abortion moves the sequence to `ABORTED` and runs compensation: every complaint whose `flush_sequence_id` is this sequence reverts to `OPEN` with its `flush_sequence_id` cleared, and the hydrant's `targeted_flush_pending` is cleared to false with the hydrant's version incremented.

### 3.5. Discolored-Water Complaints and the Auto-Flush Cluster

Complaint intake is a `FieldOperator` action: the payload supplies the `hydrant_id`, a `category` of `DISCOLORED_WATER`, `ODOR`, `TASTE`, or `PRESSURE`, and an optional `description` (default empty). A new complaint starts in `OPEN` status with `flush_sequence_id` unset.

The interesting behavior is the cluster rule, evaluated after inserting each new complaint. Count the complaints on the same hydrant whose `category` is `DISCOLORED_WATER`, whose `status` is either `OPEN` or `LINKED`, and whose `created_at` falls within the rolling 72-hour window ending at the current logical clock — both bounds inclusive. If that count reaches at least three, and the hydrant is `IN_SERVICE`, and no `FlushSequence` already exists for this hydrant with `origin` `COMPLAINT_AUTO` and `status` `PLANNED` or `IN_PROGRESS`, then the system auto-creates a targeted sequence. The auto-created sequence has `origin` `COMPLAINT_AUTO`, takes `program_id`, `zone_id`, and `hydrant_id` from the hydrant, starts in `PLANNED` status, has `window_start` set 24 hours after the current logical clock and `window_end` set 28 hours after (a four-hour window), and is initialized with a single step: `step_index` 1, `valve_tag` `MAIN`, `action` `OPEN`, `status` `PENDING`. Every complaint counted in the cluster is moved to `LINKED` with its `flush_sequence_id` pointing at the new sequence, and the hydrant's `targeted_flush_pending` is set to true. The boundary is pinned: the third qualifying complaint triggers the auto-creation; the second does not. When any of the cluster conditions fails — fewer than three complaints, hydrant out of service, or a targeted sequence already in flight — the new complaint stays `OPEN` and nothing else changes.

Complaints can also be linked by hand. A `FieldOperator` links an `OPEN` complaint to a target sequence by supplying the `flush_sequence_id`. The complaint must be `OPEN` (else `ERR_COMPLAINT_NOT_LINKABLE`), the target sequence must be `PLANNED` (else `ERR_SEQUENCE_NOT_PLANNED`), and the sequence's `hydrant_id` must equal the complaint's `hydrant_id` (else `ERR_LINK_HYDRANT_MISMATCH`, HTTP 422). A successful link moves the complaint to `LINKED` and sets `flush_sequence_id`.

Resolution happens in two ways. The automatic path fires when a linked sequence completes: every `LINKED` complaint pointing at that sequence moves to `RESOLVED` (§3.4). The manual path is a `UtilitySupervisor` closing the complaint with an `outcome`. A manual close with `outcome` `RESOLVED` requires the complaint to be `LINKED` and its linked sequence to be `COMPLETED`; a premature close is rejected with `ERR_LINKED_SEQUENCE_NOT_COMPLETED`, while a `RESOLVED` close on an already-terminal complaint is rejected with `ERR_COMPLAINT_NOT_CLOSABLE`. A manual close with `outcome` `DISMISSED` is only valid from `OPEN`; attempting to dismiss from `LINKED` or from any terminal state is rejected with `ERR_COMPLAINT_NOT_CLOSABLE`. The compensation path returns a `LINKED` complaint to `OPEN` with `flush_sequence_id` cleared when its sequence aborts (§3.4). The complaint list endpoint supports filtering by `hydrant_id`, `flush_sequence_id`, and `status`.

### 3.6. Out-of-Service Tagging and the Fire-Department Handshake

When a hydrant cannot serve — a valve failure, a leak, physical damage, or any other cause — a `FieldOperator` tags it out of service by creating a `HydrantOutage` with the `hydrant_id`, a `reason` of `VALVE_FAILURE`, `LEAK`, `DAMAGE`, or `OTHER`, and an optional `expected_return_date`. The hydrant must be `IN_SERVICE` (else `ERR_HYDRANT_NOT_IN_SERVICE`) and its program must be `OPEN` (else `ERR_PROGRAM_NOT_OPEN`).

Outage creation fires a three-hop cascade. The new outage starts in `ACTIVE` status with `notification_status` `PENDING`, `notified_at` set to the current logical clock, `ack_deadline` computed as `notified_at` plus 2 hours, and `escalated` false. The hydrant's `status` moves to `OUT_OF_SERVICE`, its `active_outage_id` is set to the new outage's id, and its `version` increments. The owning program's `hydrants_out_of_service_count` increments by one and its `unacknowledged_notification_count` increments by one. And every `SCHEDULED` flow test on this hydrant is cancelled to `CANCELLED` with `cancel_reason` of `OUTAGE_AUTO_CANCEL` — tests already in `RESULTS_SUBMITTED` or beyond are untouched.

The fire department's acknowledgement is a self-contained handshake on the outage. A `FireDeptLiaison` acknowledges the notification; the outage's `notification_status` must be `PENDING`, else the acknowledgement is rejected with `ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED`. A successful acknowledgement moves `notification_status` to `ACKNOWLEDGED`, records `acknowledged_at` from the logical clock and `acknowledged_by_user_id` from `X-User-ID`, and decrements the program's `unacknowledged_notification_count` by one. Acknowledgement does not change the outage's `status`, which remains `ACTIVE`.

Returning the hydrant to service closes the outage. A `FieldOperator` closes the hydrant's `ACTIVE` outage; the outage must be `ACTIVE` (else `ERR_OUTAGE_NOT_ACTIVE`), its `notification_status` must be `ACKNOWLEDGED` (else `ERR_NOTIFICATION_NOT_ACKNOWLEDGED`), and no `RepairWorkOrder` may exist for the hydrant in `DRAFT`, `SUBMITTED`, or `APPROVED` status (else `ERR_OPEN_WORK_ORDERS_EXIST`). This last gate is the operational rule that a hydrant cannot come back online while repair work is still in flight. A successful close sets the outage's `status` to `CLOSED`, records `closed_at`, moves the hydrant back to `IN_SERVICE` with `active_outage_id` cleared and its version incremented, and decrements the program's `hydrants_out_of_service_count` by one. The outage list endpoint supports filtering by `hydrant_id` and `status`.

### 3.7. Repair Work Orders: Part Reservations, Tiered Pricing, and Budget Caps

A repair work order tracks parts and labor against a hydrant. A `FieldOperator` creates one with the `hydrant_id`, a `description`, and an optional `budget_cap_cents` — null means uncapped and skips the budget check at approval. The new order starts in `DRAFT` with `created_by_user_id` from `X-User-ID`, `source_inspection_id` null (orders auto-created from a failed inspection carry that inspection's id instead — §3.2), and the quoted and actual totals all null. The work-order list endpoint supports filtering by `hydrant_id`, `source_inspection_id`, and `status`.

While the order is `DRAFT`, a `FieldOperator` can append to its `part_lines` by supplying a `part_id` and a `qty` greater than zero. The appended line starts in `PENDING` status with `unit_price_cents` null — pricing is only snapshot at approval. Each append increments the work order's `version` by one. The line-edit gate is the order's status: anything other than `DRAFT` yields `ERR_WORK_ORDER_NOT_DRAFT`. Submitting the order moves it from `DRAFT` to `SUBMITTED`; a submit on a non-draft order is rejected with `ERR_WORK_ORDER_NOT_DRAFT`.

Approval is the heavyweight transition and is performed by a `UtilitySupervisor`. The request must carry `expected_work_order_version` matching the order's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), so an approval never rests on a stale view of the line set — for example after another writer appended a part line. The supervisor's `X-User-ID` must differ from the order's `created_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. The order must be `SUBMITTED` (else `ERR_WORK_ORDER_NOT_SUBMITTED`). Then the fiscal checks, in order: for every part line, the referenced part's `available_qty` must be at least the line's `qty` (else `ERR_INSUFFICIENT_PART_QUANTITY`, HTTP 422); and if `budget_cap_cents` is non-null, the computed `quoted_total_cents` must be at most the cap (else `ERR_WORK_ORDER_BUDGET_EXCEEDED`, HTTP 422). Part availability is checked before the budget cap.

The quoted pricing is computed in a pinned evaluation order. Each line's amount is its `qty` multiplied by its unit price in integer cents, with no rounding. The subtotal is the sum of those line amounts. The discount percentage is tiered by subtotal: 10 percent when the subtotal is at least 100000 cents, otherwise 5 percent when the subtotal is at least 20000 cents, otherwise 0 — and the boundaries are inclusive, so a subtotal of exactly 20000 cents earns 5 percent and exactly 100000 cents earns 10 percent. The discount is the subtotal multiplied by that percentage, rounded half up to a whole cent. The discounted amount is the subtotal minus the discount. The handling fee is 1500 cents when the discounted amount is strictly less than 25000 cents and zero otherwise — a discounted amount of exactly 25000 cents carries no fee. The quoted total is the discounted amount plus the fee. At approval, each part line's `unit_price_cents` is snapshot from the part's current `unit_price_cents` and stored on the line, the four quoted totals — `quoted_subtotal_cents`, `quoted_discount_cents`, `quoted_fee_cents`, `quoted_total_cents` — are written, every line's `status` moves to `RESERVED`, each affected part's `available_qty` is recomputed, the order's `version` increments, and `approved_by_user_id` is recorded.

Rejection is the revision loop: a `UtilitySupervisor` rejects a `SUBMITTED` order (else `ERR_WORK_ORDER_NOT_SUBMITTED`) with a `rejection_reason` that is stored into `last_rejection_reason`, moving the order back to `DRAFT` where its lines become editable again.

Completion is a `FieldOperator` action on an `APPROVED` order (else `ERR_WORK_ORDER_NOT_APPROVED`). Each part line's `status` moves to `CONSUMED`, each referenced part's `on_hand_qty` is decremented by the line's `qty`, and each affected part's `available_qty` is recomputed. The order's `actual_total_cents` is computed by the same pricing pipeline as the quoted variant, but with each line's unit price taken as the *current* `Part.unit_price_cents` at completion time — so a restock that changed a price between approve and complete yields a different actual total even when the quantities are identical.

Cancellation is available from `DRAFT`, `SUBMITTED`, or `APPROVED` (else `ERR_WORK_ORDER_NOT_CANCELLABLE`). From `DRAFT` or `SUBMITTED` the cancel is a plain status change. From `APPROVED` it is a compensation: each part line's `status` moves to `RELEASED` and each affected part's `available_qty` is recomputed, while `on_hand_qty` is left untouched — only completion consumes physical stock.

The part catalog underpins all of this. A `ProgramAdmin` creates a `Part` with a globally unique `sku` (duplicates rejected with `ERR_PART_SKU_NOT_UNIQUE`), a `name`, the current `unit_price_cents`, and the physical `on_hand_qty` (which must be non-negative; a negative value is rejected with `ERR_INVALID_REQUEST`); the part's `available_qty` is initialized to `on_hand_qty`. Restocking is a `ProgramAdmin` action that supplies an `add_qty`, which must be greater than zero (else `ERR_INVALID_REQUEST`), and optionally a `new_unit_price_cents`; restocking increments `on_hand_qty` by `add_qty` and replaces `unit_price_cents` when a new price is provided. A part's `available_qty` is derived continuously as its `on_hand_qty` minus the sum of `qty` over every part line in `RESERVED` status across all work orders that reference the part. The reservation invariant is that an approve followed by a cancel-from-approved leaves `available_qty` identical to its value before the pair — the reserve and release exactly offset.

### 3.8. ISO Snapshots: Weighted Coverage and Publication Gates

An `ISOSnapshot` converts a program's operational evidence into a score for the rating bureau. A `ProgramAdmin` creates a draft snapshot for a program by supplying a `weighting_profile` of `MUNICIPAL_ONLY` or `ALL_HYDRANTS_HALF_PRIVATE`; the `program_id` comes from the path. The new snapshot starts in `DRAFT` with all four metric fields — `total_hydrants_in_scope`, `flow_coverage_pct`, `inspection_compliance_pct`, and `iso_points` — null until publish. The ISO snapshot list endpoint supports filtering by `program_id` and `status`.

Publication is gated by three preconditions evaluated on the snapshot's program. The snapshot must be `DRAFT` (else `ERR_SNAPSHOT_NOT_DRAFT`). The program must have at least one hydrant not in `DECOMMISSIONED` status (else `ERR_NO_HYDRANTS_IN_SCOPE`, HTTP 422). And the program's `unacknowledged_notification_count` must be zero — publication is blocked while any fire-department notification is still pending (else `ERR_UNACKNOWLEDGED_NOTIFICATIONS`). The scope of the metrics is the program's hydrants with `status` other than `DECOMMISSIONED`.

The scoring is weighted per hydrant. Under `MUNICIPAL_ONLY`, a `MUNICIPAL` hydrant carries weight 1.0 and a `PRIVATE` hydrant is excluded entirely from both numerator and denominator. Under `ALL_HYDRANTS_HALF_PRIVATE`, a `MUNICIPAL` hydrant carries weight 1.0 and a `PRIVATE` hydrant carries weight 0.5. Identical program data yields different scores under the two profiles.

Two coverage fractions feed the score. A hydrant is flow-current when it has at least one `APPROVED` flow test whose review time falls within the 60-month lookback window ending at the publish-time logical clock — both bounds inclusive. A hydrant is inspection-current when its `last_verified_inspection_date` falls within that hydrant's own cycle — 12 months for `MUNICIPAL`, 6 months for `PRIVATE` — ending at the publish-time logical clock, again with both bounds inclusive. The flow coverage is the sum of weights over flow-current hydrants divided by the sum of weights over all in-scope hydrants; the inspection compliance is the same ratio using inspection-current. `flow_coverage_pct` is the flow coverage multiplied by 100 and rounded half up to 1 decimal place; `inspection_compliance_pct` follows the same rule. The composite `iso_points` is 100 multiplied by the quantity: 0.6 times the flow coverage plus 0.4 times the inspection compliance, rounded half up to 1 decimal place. `total_hydrants_in_scope` is the sum of the weights; when that sum is zero (for example `MUNICIPAL_ONLY` over an all-private program), both coverage fractions are treated as zero and `iso_points` publishes as 0.0.

A successful publish pins these metrics onto the snapshot, records `published_at` from the logical clock, moves the snapshot to `PUBLISHED`, and supersedes any other `PUBLISHED` snapshot for the same program — the prior snapshot moves to `SUPERSEDED` automatically. A snapshot can therefore never have two published siblings at the same time, and the superseded trail preserves the historical record.

### 3.9. The Sweep: Tiers, Missed Windows, and Escalations

The ops-run checkpoint is a `ProgramAdmin` capability that advances a program's housekeeping in one call, and it is the engine behind three otherwise-passive rules.

First, the sweep recomputes `inspection_tier` for every hydrant of the program. The tier derives from the hydrant's cycle — 12 months for `MUNICIPAL`, 6 months for `PRIVATE` — and a baseline that is the hydrant's `last_verified_inspection_date` when one exists and the hydrant's `created_at` when no inspection has yet verified. The due date is the baseline plus the cycle length in months. Compared against the logical clock, the tier is `CURRENT` when the clock is before the due date minus 30 days; `DUE_SOON` when the clock is at or after the due date minus 30 days but before the due date; `OVERDUE` when the clock is at or after the due date but before the due date plus 90 days; and `CRITICAL` when the clock is at or after the due date plus 90 days. The boundaries are pinned: a clock reading exactly equal to the due date yields `OVERDUE`; exactly the due date minus 30 days yields `DUE_SOON`; exactly the due date plus 90 days yields `CRITICAL`. The same recomputation also runs for a single hydrant after each successful inspection verification, driven by the new `last_verified_inspection_date`.

Second, the sweep expires stale flow tests: every `SCHEDULED` flow test on a hydrant of the swept program whose `window_end` is before the current logical clock moves to `MISSED`.

Third, the sweep escalates overdue notifications: every `ACTIVE` outage on a hydrant of the swept program whose `notification_status` is still `PENDING` and whose `ack_deadline` has passed (the current logical clock is after the deadline) has its `escalated` flag set to true. Escalation is applied at most once — an outage whose `escalated` flag is already true is not modified again. Escalation is a marker for operational follow-up; it does not change `notification_status`.

The sweep response reports `missed_flow_tests`, `escalated_outages`, and `tier_recomputed_hydrants` — the three counts an operations lead reviews after each run. `missed_flow_tests` counts the tests moved to `MISSED` in this run and `escalated_outages` counts the outages newly flagged in this run, while `tier_recomputed_hydrants` counts every hydrant of the program that was re-evaluated — all of them, including `DECOMMISSIONED` hydrants and hydrants whose tier did not change. A hydrant's `version` increments only when its tier actually changes; an unchanged tier leaves the hydrant untouched.

## 4. Endpoint Definitions

New resources are returned with HTTP 201; modifications, actions, and reads return HTTP 200. All responses use the envelope defined in §2.2, and all errors use the error envelope from the same section.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/programs` | Create a seasonal flushing program | ProgramAdmin |
| GET | `/programs/{id}` | Get a program including computed counters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/programs/{id}/close` | Close a program (gates new operational records) | ProgramAdmin |
| POST | `/programs/{id}/sweep` | Recompute inspection tiers, expire stale flow tests to MISSED, escalate overdue notifications | ProgramAdmin |
| POST | `/zones` | Create a pressure zone | ProgramAdmin |
| POST | `/private-owners` | Register a private hydrant owner | ProgramAdmin |
| POST | `/hydrants` | Register a hydrant in the inventory | ProgramAdmin |
| GET | `/hydrants` | List hydrants with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/hydrants/{id}` | Get a hydrant | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/hydrants/{id}/decommission` | Decommission an in-service hydrant | ProgramAdmin |
| POST | `/inspections` | Open an inspection for a hydrant (OCC on hydrant version) | FieldOperator |
| GET | `/inspections` | List inspections with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/inspections/{id}` | Get an inspection | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/inspections/{id}/record` | Record field findings (municipal) or owner evidence (private) | FieldOperator, PrivateOwnerRep |
| POST | `/inspections/{id}/verify` | Verify or reject recorded findings; FAIL auto-creates a draft work order | UtilitySupervisor |
| POST | `/flow-tests` | Schedule a fire-flow test | FieldOperator |
| GET | `/flow-tests` | List flow tests with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/flow-tests/{id}` | Get a flow test | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/flow-tests/{id}/results` | Record pressure readings; computes pitot flow, flow at 20 psi, classification | FieldOperator |
| POST | `/flow-tests/{id}/review` | Approve or reject submitted results | UtilitySupervisor |
| POST | `/flow-tests/{id}/reschedule` | Reschedule a REJECTED or MISSED test | FieldOperator |
| POST | `/flow-tests/{id}/cancel` | Cancel a scheduled test | FieldOperator |
| POST | `/flush-sequences` | Plan a unidirectional flushing sequence | FieldOperator |
| GET | `/flush-sequences` | List flush sequences with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/flush-sequences/{id}` | Get a flush sequence | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/flush-sequences/{id}/start` | Begin execution; records source chlorine residual | FieldOperator |
| POST | `/flush-sequences/{id}/execute-step` | Execute the next valve operation step in order | FieldOperator |
| POST | `/flush-sequences/{id}/complete` | Complete the sequence; computes flushed volume and dechlorination dose; resolves linked complaints | FieldOperator |
| POST | `/flush-sequences/{id}/abort` | Abort an in-progress sequence; linked complaints revert to OPEN | FieldOperator |
| POST | `/complaints` | Log a water-quality complaint; DISCOLORED_WATER clusters may auto-create a targeted flush sequence | FieldOperator |
| GET | `/complaints` | List complaints with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/complaints/{id}` | Get a complaint | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/complaints/{id}/link` | Manually link an open complaint to a planned sequence for the same hydrant | FieldOperator |
| POST | `/complaints/{id}/close` | Resolve or dismiss a complaint | UtilitySupervisor |
| POST | `/outages` | Tag a hydrant out of service; dispatches fire-department notification and cascades | FieldOperator |
| GET | `/outages` | List outages with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/outages/{id}` | Get an outage | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/outages/{id}/acknowledge-notification` | Fire department acknowledges the out-of-service notification | FireDeptLiaison |
| POST | `/outages/{id}/close` | Return the hydrant to service | FieldOperator |
| POST | `/work-orders` | Create a draft repair work order | FieldOperator |
| GET | `/work-orders` | List work orders with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/work-orders/{id}` | Get a work order | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/work-orders/{id}/part-lines` | Add a part line to a draft work order | FieldOperator |
| POST | `/work-orders/{id}/submit` | Submit a draft work order for approval | FieldOperator |
| POST | `/work-orders/{id}/approve` | Approve a submitted work order (OCC; reserves parts; computes quoted totals) | UtilitySupervisor |
| POST | `/work-orders/{id}/reject` | Reject a submitted work order back to draft | UtilitySupervisor |
| POST | `/work-orders/{id}/complete` | Complete an approved work order; consumes parts; computes actual totals at current prices | FieldOperator |
| POST | `/work-orders/{id}/cancel` | Cancel a non-terminal work order; releases reservations when approved | FieldOperator |
| POST | `/parts` | Create a catalog part | ProgramAdmin |
| GET | `/parts` | List parts | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/parts/{id}` | Get a part including computed available_qty | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/parts/{id}/restock` | Add stock and optionally update the unit price | ProgramAdmin |
| POST | `/programs/{id}/iso-snapshots` | Create a draft ISO rating snapshot for a program | ProgramAdmin |
| GET | `/iso-snapshots` | List ISO snapshots with filters | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| GET | `/iso-snapshots/{id}` | Get an ISO snapshot | ProgramAdmin, FieldOperator, UtilitySupervisor, FireDeptLiaison, PrivateOwnerRep |
| POST | `/iso-snapshots/{id}/publish` | Publish a snapshot; pins metrics and supersedes the previously published snapshot | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_HYDRANT_OWNERSHIP_MISMATCH | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_PROGRAM_NOT_FOUND | 404 |
| ERR_ZONE_NOT_FOUND | 404 |
| ERR_PRIVATE_OWNER_NOT_FOUND | 404 |
| ERR_HYDRANT_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_FLOW_TEST_NOT_FOUND | 404 |
| ERR_FLUSH_SEQUENCE_NOT_FOUND | 404 |
| ERR_COMPLAINT_NOT_FOUND | 404 |
| ERR_OUTAGE_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_PART_NOT_FOUND | 404 |
| ERR_ISO_SNAPSHOT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_PROGRAM_NOT_OPEN | 409 |
| ERR_HYDRANT_NOT_IN_SERVICE | 409 |
| ERR_INSPECTION_NOT_RECORDABLE | 409 |
| ERR_INSPECTION_NOT_PENDING_VERIFICATION | 409 |
| ERR_FLOW_TEST_NOT_SCHEDULED | 409 |
| ERR_FLOW_TEST_NOT_SUBMITTED | 409 |
| ERR_FLOW_TEST_NOT_RESCHEDULABLE | 409 |
| ERR_SEQUENCE_NOT_PLANNED | 409 |
| ERR_SEQUENCE_NOT_IN_PROGRESS | 409 |
| ERR_COMPLAINT_NOT_LINKABLE | 409 |
| ERR_COMPLAINT_NOT_CLOSABLE | 409 |
| ERR_OUTAGE_NOT_ACTIVE | 409 |
| ERR_NOTIFICATION_ALREADY_ACKNOWLEDGED | 409 |
| ERR_NOTIFICATION_NOT_ACKNOWLEDGED | 409 |
| ERR_WORK_ORDER_NOT_DRAFT | 409 |
| ERR_WORK_ORDER_NOT_SUBMITTED | 409 |
| ERR_WORK_ORDER_NOT_APPROVED | 409 |
| ERR_WORK_ORDER_NOT_CANCELLABLE | 409 |
| ERR_SNAPSHOT_NOT_DRAFT | 409 |
| ERR_PRESSURE_READING_INVALID | 422 |
| ERR_DECHLORINATION_LIMIT_EXCEEDED | 422 |
| ERR_HYDRANT_NUMBER_NOT_UNIQUE | 409 |
| ERR_PROGRAM_ALREADY_EXISTS | 409 |
| ERR_PART_SKU_NOT_UNIQUE | 409 |
| ERR_PROGRAM_MISMATCH | 422 |
| ERR_STEP_OUT_OF_SEQUENCE | 409 |
| ERR_STEPS_INCOMPLETE | 409 |
| ERR_OPEN_WORK_ORDERS_EXIST | 409 |
| ERR_UNACKNOWLEDGED_NOTIFICATIONS | 409 |
| ERR_NO_HYDRANTS_IN_SCOPE | 422 |
| ERR_FLOW_TEST_WINDOW_OVERLAP | 409 |
| ERR_FLOW_TEST_WINDOW_NOT_STARTED | 409 |
| ERR_FLOW_TEST_WINDOW_EXPIRED | 409 |
| ERR_SEQUENCE_ZONE_COOLDOWN | 409 |
| ERR_LINK_HYDRANT_MISMATCH | 422 |
| ERR_LINKED_SEQUENCE_NOT_COMPLETED | 409 |
| ERR_INSUFFICIENT_PART_QUANTITY | 422 |
| ERR_WORK_ORDER_BUDGET_EXCEEDED | 422 |

# Gas Emergency Response API — Product Requirements Document

## 1. Introduction

Gas utilities live and die by their response to odor calls. A single mishandled report of mercaptan smell inside a school, a hissing service line in a public space, or a caller complaining of headaches can escalate from a routine dispatch to a catastrophic incident — and regulators audit every minute between the call and the first boot on the ground. This document specifies the Gas Emergency Response & Odor Call Dispatch API, the operational backbone for a utility's emergency organization: it captures incoming emergency calls, classifies and deduplicates them against a normalized address key, runs the regulatory response-time clock with pause accounting, coordinates field technicians under real capacity and shift constraints, governs premise entry and gas shutoff under strict authorization rules, and produces the dual-variant compliance snapshots that regulators accept or reject.

The system serves five distinct operator populations — platform administrators, call-takers, first responders, operations supervisors, and external regulators — whose powers are deliberately segregated so that, for example, the supervisor who drafts a responsibility determination can never be the one who finalizes it. All server-side time derives from a single logical clock, making response-time arithmetic deterministic and auditable. What follows is the complete behavioral contract: global specifications first, then the business workflows, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All business resources are mounted under the `/gas-ops` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is simply not permitted on the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly five roles, spelled as follows: `SystemAdmin`, `Dispatcher`, `FieldTechnician`, `Supervisor`, and `Regulator`.

A `SystemAdmin` is the platform operator: it creates service territories, registers field technicians and repair crews, declares technician shifts (a capability shared with `Supervisor`), and is the only role allowed to advance the logical clock. A `Dispatcher` is the call-taker: it intakes emergency calls (shared with `Supervisor`), triages and reclassifies incidents, creates dispatch assignments, opens and closes response-clock pauses, and records consent-based premise entry authorizations. A `FieldTechnician` is the first responder: it arrives at and clears its own assignments, records atmospheric readings and make-safe actions, completes make-safe, requests shutoff orders, executes and restores authorized shutoffs, and moves an incident's entry status. A `Supervisor` is the operations authority: it holds every dispatcher capability and additionally authorizes or declines shutoffs, preempts or cancels assignments, closes and merges incidents, drafts and finalizes responsibility determinations, manages repair work orders end to end, generates and submits regulatory reports, drafts and issues public notifications, and records forced or warranted entry authorizations. A `Regulator` is an external overseer with read-only access limited in scope, plus the exclusive ability to accept or reject submitted reports.

The identity semantics of `X-User-ID` differ by role. When `X-User-Role` is `FieldTechnician`, `X-User-ID` is the `id` of the acting `FieldTechnician` record; ownership checks on any resource that references a technician — most importantly a dispatch assignment's `technician_id` — compare that foreign key to `X-User-ID`. When `X-User-Role` is `SystemAdmin`, `Dispatcher`, `Supervisor`, or `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it as an actor stamp — for example `recorded_by_user_id` on a premise entry authorization, `requested_by_user_id` and `authorized_by_user_id` on a shutoff order, or `drafted_by_user_id` and `finalized_by_user_id` on a responsibility determination — but it never compares such stamps to any entity's `id`, except where a segregation-of-duties rule explicitly compares two stamps to each other.

Two read-scoping rules restrict what certain roles can see, and both are enforced as permission failures rather than silent filtering failures of existence. A `Regulator` may read only incidents in `CLOSED` or `MERGED` lifecycle status and only regulatory reports that are not in `DRAFT`; any other access is rejected with `ERR_REGULATOR_SCOPE_RESTRICTED` (HTTP 403), and a `Regulator` never performs writes other than accepting or rejecting a submitted report. A `FieldTechnician` may read or annotate only incidents on which it holds — or previously held — a dispatch assignment, and may act only on its own assignments; violations are rejected with `ERR_NOT_ASSIGNED_TO_INCIDENT` (HTTP 403). Separately, a segregation-of-duties rule forbids the supervisor who drafted a responsibility determination from finalizing it; violations are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; when omitted it defaults to 10, and it must lie between a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every timestamp the server stamps — creation times, call receipt times, dispatch and arrival times, pause boundaries, report generation times, and the evaluation of shift windows — reads a single logical clock rather than wall-clock time. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never advances on its own and never falls back to wall-clock time. It moves only when a `SystemAdmin` invokes the clock-advance capability at `/_clock/set_current_utc` with a `to_iso8601` instant; the response reports the new logical time as `current_utc`. After any advance, all computed time-dependent fields — a technician's `on_shift` flag, every incident's elapsed-second fields, and every breach verdict — evaluate against the new logical time on the next read.

### 2.5. Common Resource Properties

Primary resources carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. The `version` is a system-managed integer that increments with every mutation, including mutations caused by cascading side effects from operations on other resources, and it underpins optimistic concurrency control.

Five entity kinds are deliberately lighter: a technician shift, an emergency call, an atmospheric reading, a make-safe action, and a premise entry authorization each carry `id` and `created_at` only — both `updated_at` and `version` are absent from them, because they are immutable records once created.

### 2.6. Validation Order and Nested Path Resolution

The server evaluates every request against a fixed validation cascade, and the ordering matters because an earlier failure masks all later ones. The cascade runs in this order:

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be a declared one (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role permission.** The role must be permitted on the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`).
3. **Path existence.** Every resource identifier in the URL path must exist, validated left to right (`ERR_TERRITORY_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_CREW_NOT_FOUND`, `ERR_CALL_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_PAUSE_NOT_FOUND`, `ERR_SHUTOFF_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`).
4. **Scoping and segregation of duties.** Regulator read scope (`ERR_REGULATOR_SCOPE_RESTRICTED`), technician assignment scope (`ERR_NOT_ASSIGNED_TO_INCIDENT`), and the determination drafter-versus-finalizer rule (`ERR_SEGREGATION_OF_DUTIES`).
5. **Request shape.** Required fields present, enum values within their declared domains, and numeric ranges respected — `pct_lel` between 0.0 and 100.0 inclusive, `co_ppm` at least 0, a line's `discount_pct` at least 0 and strictly below 1 — plus the rule that an end instant must be strictly after its start instant on every time range (`ERR_INVALID_REQUEST`, `ERR_INVALID_TIME_RANGE`).
6. **State legality.** The target resource must be in a legal from-state for the requested transition (`ERR_INVALID_STATE`, `ERR_INCIDENT_NOT_TRIAGED`, `ERR_INCIDENT_NOT_ACTIVE`, `ERR_DETERMINATION_NOT_DRAFT`, `ERR_REPORT_NOT_DRAFT`, `ERR_NOTIFICATION_NOT_DRAFT`, `ERR_NOTIFICATION_NOT_ISSUED`, `ERR_DISPATCH_NOT_PREEMPTABLE`, `ERR_OPEN_PAUSE_EXISTS`).
7. **Safety gates.** The atmospheric-reading requirement, the evacuation-action requirement, and the premise-entry requirement (`ERR_ATMOSPHERIC_READING_REQUIRED`, `ERR_MAKE_SAFE_NOT_COMPLETED`, `ERR_ENTRY_NOT_AUTHORIZED`).
8. **Temporal and availability constraints.** Shift, territory, and capacity checks on dispatch (`ERR_TECHNICIAN_OFF_SHIFT`, `ERR_TECHNICIAN_TERRITORY_MISMATCH`, `ERR_TECHNICIAN_CAPACITY_REACHED`, `ERR_NO_AVAILABLE_TECHNICIAN`), shift-window overlap (`ERR_SHIFT_OVERLAP`), and the crew travel buffer (`ERR_TRAVEL_BUFFER_VIOLATION`).
9. **Cross-entity referential gates.** Final-determination requirements, open dispatches, open shutoffs, and merge-target validity (`ERR_DETERMINATION_REQUIRED`, `ERR_OPEN_DISPATCHES_EXIST`, `ERR_OPEN_SHUTOFF_ORDER`, `ERR_MERGE_TARGET_INVALID`).
10. **Fiscal constraint.** The repair budget reservation check (`ERR_REPAIR_BUDGET_EXCEEDED`).

Within step 3, the left-to-right rule is strict: on a nested path such as a territory's incidents or an incident's shutoff orders, the server first confirms the territory, then the technician, crew, or incident, then the child resource, and the response carries the not-found error of the *first* identifier that does not resolve. A request for a pause under a non-existent incident therefore fails with `ERR_INCIDENT_NOT_FOUND`, never with `ERR_PAUSE_NOT_FOUND`.

### 2.7. Response-Clock Accounting and Breach Classification

Every incident carries a response clock that measures how long the utility took to arrive, and the same arithmetic feeds both the incident's live fields and regulatory reporting. The clock measures **response segments**: a segment begins at `response_clock_started_at` and ends at `first_arrival_at` once a first arrival has been recorded in that segment, or at the current logical time while no arrival has happened yet. All computed values use whole seconds with no rounding.

Three figures derive from the segment. The `raw_elapsed_seconds` is the number of seconds from `response_clock_started_at` to the segment end, ignoring pauses entirely. The `pause_total_seconds` is the sum of the durations of the incident's response-clock pauses belonging to the current segment, where each pause's duration is measured from its `started_at` (inclusive) to its `ended_at` (exclusive) as a half-open interval; a pause that is still open contributes from its `started_at` to the current logical time, evaluated at read time. The `adjusted_elapsed_seconds` is the raw elapsed minus the pause total, floored at zero so it can never go negative. Pauses from earlier segments are never re-counted: when an incident reopens, the closed segment's adjusted elapsed is archived into `prior_segment_adjusted_seconds`, the pause total restarts from zero, and only pauses created at or after the new segment start participate.

An incident's SLA threshold is dynamic. Its `threshold_minutes` is the owning territory's threshold for the incident's *current* priority — `p1_threshold_minutes` for `P1`, `p2_threshold_minutes` for `P2`, `p3_threshold_minutes` for `P3`, `p4_threshold_minutes` for `P4` — so a reclassification immediately changes the yardstick. The breach comparison converts the threshold to seconds by multiplying by sixty and is **strictly greater**: the incident is in breach only when the elapsed figure exceeds the threshold in seconds, and an elapsed figure exactly equal to the threshold is compliant. The `breach_class` field reports `NONE` when there is no breach, `RESPONDED_LATE` when the incident is in breach and a first arrival has been recorded, and `NO_RESPONSE` when the incident is in breach with no arrival yet. Breach verdicts, and the incident's `adjusted_elapsed_seconds` field, always use the pause-subtracted variant; the raw variant, which ignores pauses, exists for the incident's `raw_elapsed_seconds` field and for the raw compliance counts in regulatory reports. A dispatch assignment's `sla_threshold_minutes` is merely a snapshot of the incident's threshold taken at dispatch time for informational purposes — breach verdicts never consult it.

### 2.8. Optimistic Concurrency Control

Two write operations require the client to prove it acted on a current view of the incident, and both carry the same mechanism. A priority reclassification request must include `expected_incident_version` holding the incident `version` the client last observed, and a request to draft a responsibility determination must likewise include `expected_incident_version`. The field is non-optional on both operations. If the supplied value does not match the incident's current `version` — meaning the incident has been mutated since the client last read it, whether by triage, automatic escalation, a make-safe completion, or any other version-advancing effect — the request is rejected with `ERR_STALE_INCIDENT_VERSION` (HTTP 412). This prevents a reclassification from silently superseding an assessment the client never saw, and prevents a determination from being drafted on a stale incident snapshot. No other endpoint accepts a version field.

### 2.9. Repair Budget Reservation Ledger

Each territory tracks a running reservation of repair funds in `repair_reserved_cents`, which starts at zero when the territory is created and is capped by the territory's `repair_budget_cap_cents`. The reserved figure counts the `current_estimate_cents` of every repair work order in the territory whose status is `SCHEDULED`, `IN_PROGRESS`, or `ON_HOLD`; work orders in `OPEN` hold no reservation at all. Scheduling a work order adds its `current_estimate_cents` to the reservation, and the schedule is refused with `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 402) when the reservation plus that estimate would exceed the cap. Completing a work order releases the reservation made at schedule time by subtracting its `provisional_estimate_cents`, while cancelling a `SCHEDULED` or `ON_HOLD` work order subtracts its `current_estimate_cents`; cancelling an `OPEN` work order changes nothing.

### 2.10. Monetary Values, Scores, and Precision

All monetary amounts are integer cents — territory budget caps and reservations, technician and crew hourly rates, work-order estimates and final costs — and every monetary rounding is **round half up to a whole cent**, applied at each pinned step of a calculation rather than once at the end. An incident's severity score is an integer produced by rounding a weighted sum half up. Regulatory compliance rates are decimal fractions expressed to four decimal places, rounded half up, and are null when their denominator is zero. Elapsed-time figures are whole seconds with no rounding. Atmospheric input precision is fixed as well: `pct_lel` carries one decimal place within the range 0.0 to 100.0 inclusive, and `co_ppm` is a non-negative number.

## 3. Business Logic & Workflows

### 3.1. Territories, Technicians, Shifts, and Repair Crews

Everything begins with the service territory. A `SystemAdmin` creates a territory by supplying its display `name`, the four SLA response thresholds `p1_threshold_minutes`, `p2_threshold_minutes`, `p3_threshold_minutes`, and `p4_threshold_minutes`, the `recurrence_window_hours` that governs how soon a repeat call at the same address reopens a closed incident, and the `repair_budget_cap_cents` that bounds outstanding repair reservations. The territory's `repair_reserved_cents` is computed by the reservation ledger and starts at zero.

Field technicians are registered with a `full_name`, a unique `badge_number`, a `home_territory_id` anchoring them to their territory, and an `hourly_rate_cents` labor rate. The `is_active` flag defaults to true; an inactive technician cannot be dispatched. Three computed figures describe a technician's live load: `active_assignment_count` tallies their assignments currently in `EN_ROUTE` or `ON_SCENE`, `weighted_load` sums an urgency weight over those active assignments — 4 for an incident currently at `P1`, 3 for `P2`, 2 for `P3`, 1 for `P4` — and `last_cleared_at` records the `cleared_at` of their most recently cleared assignment, remaining null until they clear one. The technician list can be filtered by `home_territory_id`, and a technician's dispatch history can be filtered by assignment `status`; their recorded readings and make-safe actions are likewise listable.

A technician's `on_shift` flag is computed against the logical clock: it is true exactly when the current logical time falls inside at least one of the technician's declared shift windows. A `SystemAdmin` or `Supervisor` declares a shift with `shift_start` and `shift_end`, which form a half-open interval — the start is inclusive and the end exclusive. An end that is not strictly after its start is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 400). Two shifts of the same technician may not overlap; an overlapping declaration is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409), while adjacency — one shift's `shift_end` exactly equal to another's `shift_start` — is allowed.

Repair crews are registered with a unique `crew_code`, the `territory_id` they operate in, and an `hourly_rate_cents` billing rate. Their `is_active` flag defaults to true, and an inactive crew cannot be scheduled. The crew roster can be filtered by `territory_id`, and each crew's scheduled work orders can be listed and filtered by `status`.

### 3.2. Emergency Call Intake: Classification, Deduplication, and Recurrence

A `Dispatcher` or `Supervisor` intakes an odor or emergency call by recording the `caller_name` and `caller_phone`, the `address_line` and `city` of the reported location, the `territory_id` covering that address, and the `location_context` — one of `INSIDE_STRUCTURE`, `OUTSIDE_STRUCTURE`, `METER_AREA`, `PUBLIC_SPACE`, or `UNKNOWN`. Three booleans capture what the caller reports: `odor_reported` for gas odor, `symptoms_reported` for illness symptoms, and `hissing_reported` for a hissing sound. The `occupancy_type` is optional and defaults to `SINGLE_FAMILY`; the full domain is `SINGLE_FAMILY`, `MULTI_FAMILY`, `PUBLIC_ASSEMBLY`, `SCHOOL`, and `HOSPITAL`. The server stamps `received_at` from the logical clock at intake.

From these inputs the server derives the call's `implied_priority`. Any call with `symptoms_reported` true implies `P1`. Otherwise, a call with `odor_reported` true and `location_context` of `INSIDE_STRUCTURE` implies `P2`; a call with `odor_reported` true in any other context implies `P3`; and a call with no odor and no symptoms implies `P4`.

Intake then resolves the call against existing incidents using a normalized address key. The `normalized_address` is built by trimming whitespace from the `address_line` and uppercasing it, doing the same to the `city`, and concatenating those two with the `territory_id`, joined by pipe characters. The call's `classification` and its `is_duplicate` flag fall out of this match:

- **PRIMARY** — no live match and no recurrence match. A new gas incident is created in lifecycle status `NEW`, its `priority` initialized to the call's `implied_priority`, its `territory_id` and `occupancy_type` copied from the call, and its `response_clock_started_at` set to the call's logical receipt time. A new incident starts with `linked_call_count` 1, `reopen_count` 0, `severity_score` 0, `entry_status` `NOT_REQUIRED`, `first_arrival_at` null, `prior_segment_adjusted_seconds` 0, `pause_total_seconds` 0, `awaiting_dispatch` false, `evacuation_required` false, `make_safe_completed` false, `leak_confirmed` false, `gas_flow_stopped` false, `customer_referral_required` false, `auto_notification_created` false, `responsibility` null, and `closed_at` null. If the implied priority is `P1`, the automatic notification rule fires at creation (see §3.8).
- **DUPLICATE** — the same normalized address already has a non-terminal incident. The call is linked to that incident, `is_duplicate` is true, and the incident's `linked_call_count` increases by one. If the new call's `implied_priority` is strictly higher than the incident's current priority, the incident auto-escalates: its `priority` is raised — automatic escalation never lowers priority — its `threshold_minutes` recomputed, its `breach_class` re-evaluated, its `severity_score` recomputed, and its `version` incremented; reaching `P1` through escalation fires the same automatic notification rule. Any covering draft or rejected regulatory report is marked stale.
- **RECURRENCE** — the same normalized address matches an incident whose most recent closure falls within the territory's recurrence window, measured as the half-open interval from `closed_at` inclusive to `closed_at` plus `recurrence_window_hours` exclusive. That incident transitions `CLOSED → REOPENED`: `reopen_count` and `linked_call_count` each increase by one, the closed segment's adjusted elapsed time is archived into `prior_segment_adjusted_seconds`, `response_clock_started_at` resets to the recurrence call's `received_at`, `first_arrival_at` returns to null, `pause_total_seconds` resets to zero, `breach_class` recomputes to `NONE`, `make_safe_completed` flips back to false, and `entry_status` returns to `NOT_REQUIRED`; the incident `version` increments and covering draft or rejected reports are marked stale. A call landing exactly at the window's end instant does not reopen — it spawns a brand-new `PRIMARY` incident instead.

Emergency calls can be listed with `incident_id` and `territory_id` filters and fetched individually; an unknown call identifier yields `ERR_CALL_NOT_FOUND`. The call record exposes its `incident_id` linkage, its computed `implied_priority`, and its `classification`.

### 3.3. Triage, Priority Reclassification, and Merging Duplicates

Triage is the first human judgment on an incident. A `Dispatcher` or `Supervisor` confirms or sets the priority by submitting a `priority` value, optionally annotated with `classification_notes`. Triage is legal only while the incident's `lifecycle_status` is `NEW` or `REOPENED` — otherwise the request fails with `ERR_INCIDENT_NOT_ACTIVE` (HTTP 409) — and it moves the incident to `TRIAGED`. The submitted `priority` replaces the current one, the incident `version` increments, and two cascades fire: whenever the triaged priority is `P1` the automatic notification rule engages (§3.8), and every covering regulatory report still in `DRAFT` or `REJECTED` is flagged as needing regeneration.

An incident's full lifecycle runs `NEW → TRIAGED → DISPATCHED → ON_SCENE → MAKE_SAFE_IN_PROGRESS → MONITORING → CLOSED`, with the recurrence cycle `CLOSED → REOPENED → TRIAGED` layered on top and `MERGED` as the terminal absorbing state for consolidated duplicates. The moves from `TRIAGED` to `DISPATCHED`, from `DISPATCHED` to `ON_SCENE`, and from `ON_SCENE` to `MAKE_SAFE_IN_PROGRESS` are automatic consequences of operational events described in §3.4 and §3.5; no operator invokes them directly.

After triage, the priority can be deliberately reclassified while the incident is in `TRIAGED`, `DISPATCHED`, `ON_SCENE`, `MAKE_SAFE_IN_PROGRESS`, or `MONITORING`. The reclassification request carries the `new_priority`, a free-text `reason`, and — because this is one of the two optimistic-concurrency-guarded writes — the `expected_incident_version` described in §2.8; a version that no longer matches the incident's current `version` is rejected with `ERR_STALE_INCIDENT_VERSION` (HTTP 412). A successful reclassification sets the `priority`, recomputes `threshold_minutes` from the territory's table for the new priority, re-evaluates `breach_class`, fires the automatic notification rule if the incident has reached `P1`, marks covering draft or rejected reports stale, and increments the incident `version`.

When two live incidents turn out to be the same event, a `Supervisor` merges them. The merge action is addressed to the incident that will survive — the target — and its payload names the `source_incident_id` to be absorbed. The source must be in `NEW`, `TRIAGED`, or `DISPATCHED` lifecycle status; any other source state is rejected with `ERR_INVALID_STATE` (HTTP 409). The target must exist, must not be `MERGED` or `CLOSED`, must be a different incident than the source, and must share the source's `normalized_address`; any violation is rejected with `ERR_MERGE_TARGET_INVALID` (HTTP 409). A source in `DISPATCHED` carries one extra gate: none of its assignments may still be `EN_ROUTE` or `ON_SCENE`, or the merge fails with `ERR_OPEN_DISPATCHES_EXIST` (HTTP 409). On merge, every emergency call of the source is re-linked to the target and the target's `linked_call_count` grows by the source's count; the target's `priority` becomes the higher of the two incidents' priorities (`P1` being the highest), and if that raised the target's priority its breach verdict is re-evaluated and the automatic notification rule applies; the source closes out as `MERGED`, which is terminal, and both incidents' `version` values increment.

### 3.4. Dispatch, Arrival, Preemption, and Response-Clock Pauses

Dispatch puts a technician behind an incident. A `Dispatcher` or `Supervisor` creates the assignment against an incident that must currently be `TRIAGED` — dispatching an incident in any other lifecycle state is rejected with `ERR_INCIDENT_NOT_TRIAGED` (HTTP 409). The request may name a `technician_id` and may carry free-text `notes` for the assignment record.

When the request names a technician explicitly, three availability gates apply: the technician must be on shift at the current logical time, or the dispatch fails with `ERR_TECHNICIAN_OFF_SHIFT` (HTTP 409); the technician's `home_territory_id` must match the incident's territory, or it fails with `ERR_TECHNICIAN_TERRITORY_MISMATCH` (HTTP 409); and the technician's `active_assignment_count` must be below the two-assignment ceiling, or it fails with `ERR_TECHNICIAN_CAPACITY_REACHED` (HTTP 409).

When `technician_id` is omitted, a deterministic selector runs. The eligible pool contains technicians who are active, on shift, homed in the incident's territory, and holding fewer than two active assignments. The selection freezes every candidate-relevant incident's current priority first, computes each candidate's `weighted_load` from those frozen priorities, and only then ranks — because the assignment created by this request mutates counts that the *next* request will observe. Ranking is by `weighted_load` ascending, then by `last_cleared_at` ascending with technicians who have never cleared (null) ordered first, then by technician `created_at` ascending; the first-ranked technician wins. An empty pool is rejected with `ERR_NO_AVAILABLE_TECHNICIAN` (HTTP 409).

A created assignment starts in `EN_ROUTE` with `dispatched_at` stamped from the logical clock, and its `sla_threshold_minutes` snapshots the incident's threshold at that instant for informational purposes. Creation cascades: the incident automatically transitions `TRIAGED → DISPATCHED`, its `awaiting_dispatch` flag clears to false, its `version` increments, and the technician's `active_assignment_count` increases by one with `weighted_load` recomputed. An assignment's lifecycle runs `EN_ROUTE → ON_SCENE → CLEARED`, with `PREEMPTED` and `CANCELLED` as additional terminal outcomes reachable only from `EN_ROUTE`.

Arrival and clearing belong to the assigned technician alone. The arrival action requires the assignment to be `EN_ROUTE` (otherwise `ERR_INVALID_STATE`) and requires `X-User-ID` to equal the assignment's `technician_id` (otherwise `ERR_NOT_ASSIGNED_TO_INCIDENT`, HTTP 403). It stamps `arrived_at` and increments the assignment `version`. When this arrival is the incident's first arrival in the current response segment, the incident cascade fires automatically: the incident moves `DISPATCHED → ON_SCENE`, `first_arrival_at` is set to the arrival's logical time and the response clock stops for the segment, any still-open response-clock pause is auto-closed with its `ended_at` set to the arrival time, and `breach_class` is recomputed — a breach with an arrival recorded is `RESPONDED_LATE`. The clear action likewise requires an `ON_SCENE` assignment owned by the caller; it stamps `cleared_at`, decrements the technician's `active_assignment_count`, sets `last_cleared_at` to the clearing time, and recomputes `weighted_load`.

A `Supervisor` may cancel an `EN_ROUTE` assignment by supplying a `reason`; cancelling is illegal from any other state (`ERR_INVALID_STATE`). Cancellation decrements the technician's `active_assignment_count`, recomputes `weighted_load`, and — when the incident has no remaining active assignment — sets the incident's `awaiting_dispatch` flag to true.

Preemption is the sharper instrument. A `Supervisor` preempts an `EN_ROUTE` assignment — an `ON_SCENE` assignment cannot be preempted and attempting it yields `ERR_DISPATCH_NOT_PREEMPTABLE` (HTTP 409) — by naming a `target_incident_id` and a `reason`, which is recorded on the preempted assignment as `preempt_reason`. The target incident must exist, must be in `TRIAGED` or `DISPATCHED`, and must carry a priority strictly higher than the source incident's current priority (`P1` highest); otherwise the request fails with `ERR_INVALID_STATE`. Preemption is an atomic re-pointing: the old assignment becomes `PREEMPTED` and the technician's count decrements, while a brand-new assignment is auto-created on the target for the same technician, starting `EN_ROUTE` with `dispatched_at` stamped now and the count incrementing back — the technician's `active_assignment_count` is net unchanged. The response body carries this newly created assignment. If the source incident is left with no active assignment, its `awaiting_dispatch` flag sets to true; if the target was `TRIAGED`, it automatically advances to `DISPATCHED`.

While an incident waits for arrival, a `Dispatcher` or `Supervisor` may open a response-clock pause with a `reason` of `CUSTOMER_NOT_HOME` or `ACCESS_BLOCKED`. Opening a pause requires the incident's lifecycle to be `TRIAGED` or `DISPATCHED`, requires that no arrival has been recorded yet, and requires that no other pause is currently open; violation of any of these yields `ERR_OPEN_PAUSE_EXISTS` (HTTP 409). The pause's `started_at` is stamped at creation, it begins life `OPEN`, and from that instant it participates in the adjusted-elapsed arithmetic of §2.7. Ending the pause — legal only while it is `OPEN`, otherwise `ERR_INVALID_STATE` — stamps `ended_at` from the logical clock, flips it to `CLOSED`, and recomputes the incident's `pause_total_seconds` and `breach_class`. A pause's `duration_seconds` reads as `ended_at` minus `started_at` once closed, and as the current logical time minus `started_at` while still open.

### 3.5. On-Scene Operations: Atmospheric Readings, Make-Safe, and Premise Entry

Once on scene, the assigned technician records atmospheric readings. Recording a reading — and likewise recording a make-safe action — requires the incident to be in one of the on-scene stages, `ON_SCENE` or `MAKE_SAFE_IN_PROGRESS`; against an incident in any other lifecycle state the write is rejected with `ERR_INCIDENT_NOT_ACTIVE` (HTTP 409). Each reading captures `pct_lel` — the percent of the lower explosive limit, between 0.0 and 100.0 with one decimal — `co_ppm` — carbon monoxide in parts per million, never negative — and a `reading_context` of `INSIDE`, `OUTSIDE`, or `CONFINED_SPACE`. The recording technician is stamped onto the reading as `technician_id` from the acting `X-User-ID`, which must belong to a technician holding an active assignment on the incident or the write fails with `ERR_NOT_ASSIGNED_TO_INCIDENT`; `taken_at` is stamped from the logical clock. Every new reading recomputes the incident's `severity_score` and `evacuation_required` flag, engages the severity-based automatic notification rule, and marks covering draft or rejected regulatory reports stale.

The severity score weighs four factors and clamps the result into the inclusive range zero to one hundred. Let the incident's maximum `pct_lel` over all of its readings — zero when no readings exist — determine the LEL factor: 1.0 when that maximum is at least 10.0, 0.5 when it is at least 5.0 but below 10.0, 0.2 when it is above 0 but below 5.0, and 0.0 when there is no positive reading. The maximum `co_ppm` over all readings — again zero when none exist — determines the CO factor: 1.0 when it reaches at least 70 parts per million, 0.5 when it reaches at least 35 but below 70, and 0.0 otherwise. The occupancy factor is 1.0 for `PUBLIC_ASSEMBLY`, `SCHOOL`, and `HOSPITAL` occupancies, 0.6 for `MULTI_FAMILY`, and 0.3 for `SINGLE_FAMILY`. The symptom factor is 1.0 when any linked emergency call — primary, duplicate, or recurrence — has `symptoms_reported` true, and 0.0 otherwise. The score is forty times the LEL factor, plus twenty-five times the CO factor, plus twenty times the occupancy factor, plus fifteen times the symptom factor, rounded half up to an integer and clamped so it never falls below zero nor exceeds one hundred. The score is a stored incident field rather than a live read-time derivation of the formula: a new incident keeps the 0 assigned at creation (§3.2) until a recompute event rewrites it, and every read of the incident reports the stored value. The only recompute events are the recording of a new atmospheric reading and a duplicate-call escalation that raises the incident's priority (§3.2); any other change to the formula's inputs — a non-escalating duplicate call, a recurrence that reopens the incident, a triage, a reclassification, a merge that re-links calls, or a closure — leaves the stored score unchanged. Separately, the `evacuation_required` flag is true exactly when any reading on the incident has `pct_lel` of at least 10.0 — the same ten-percent threshold that drives the top LEL factor.

The technician also records make-safe actions, each with an `action_type` of `VENTILATE`, `SHUT_APPLIANCE_VALVE`, `EVACUATE`, `SECURE_AREA`, or `OTHER`, plus free-text `notes`; `performed_at` is stamped from the logical clock and the acting technician recorded as `technician_id`. The very first make-safe action on an incident automatically moves it from `ON_SCENE` to `MAKE_SAFE_IN_PROGRESS`.

Completing make-safe is the technician's declaration that the scene is controlled. The completion request carries a `leak_confirmed` boolean, may set `no_make_safe_required` to true when the situation warranted no physical intervention, and may note a `leak_location_guess` for the downstream responsibility work. The incident must be in `ON_SCENE` or `MAKE_SAFE_IN_PROGRESS` — anything else is `ERR_INCIDENT_NOT_ACTIVE` — and two safety gates stand in front of completion. First, when any linked call reported odor and the incident has no atmospheric reading at all, completion is rejected with `ERR_ATMOSPHERIC_READING_REQUIRED` (HTTP 422); this reading requirement applies even when `no_make_safe_required` is true. Second, when `evacuation_required` is true and no make-safe action with `action_type` `EVACUATE` exists, completion is rejected with `ERR_MAKE_SAFE_NOT_COMPLETED` (HTTP 422). A completion submitted with `no_make_safe_required` true takes the incident directly from `ON_SCENE` to `MONITORING` under the same preconditions; otherwise the move is `MAKE_SAFE_IN_PROGRESS → MONITORING`. Either way, completion sets `make_safe_completed` to true, stores the submitted `leak_confirmed`, increments the incident `version`, and marks covering draft or rejected reports stale.

Premise entry runs on a second, parallel state dimension that never disturbs the lifecycle dimension except where explicitly stated. Every incident's `entry_status` starts at `NOT_REQUIRED` and may traverse `AWAITING_AUTHORIZATION`, `AUTHORIZED`, `FORCED`, and `REFUSED`. A `FieldTechnician` or `Supervisor` moves the dimension by submitting a `to_status`: submitting `AWAITING_AUTHORIZATION` is legal from `NOT_REQUIRED` or `REFUSED` — but only while the incident's lifecycle is `ON_SCENE`, `MAKE_SAFE_IN_PROGRESS`, or `MONITORING`, else `ERR_INCIDENT_NOT_ACTIVE` — and submitting `REFUSED` is legal from `AWAITING_AUTHORIZATION`. The transitions into `AUTHORIZED` and `FORCED` never happen through `to_status`; they happen only by recording a premise entry authorization. Such a record names an authorization `method` and the `authorized_by_name` of the consenting person or warrant; the server stamps the recorder's opaque `X-User-ID` as `recorded_by_user_id`. A `CUSTOMER_CONSENT` method may be recorded by a `Dispatcher` or `Supervisor` and moves the dimension `AWAITING_AUTHORIZATION → AUTHORIZED`; `EMERGENCY_FORCED` and `WARRANT` methods are restricted to a `Supervisor` and move it `AWAITING_AUTHORIZATION → FORCED`. Recording an authorization while the dimension is not `AWAITING_AUTHORIZATION` fails with `ERR_INVALID_STATE`. Every one of these entry-dimension moves increments the incident `version`. When the incident eventually closes, its `entry_status` returns to `NOT_REQUIRED` automatically — including the explicit `AUTHORIZED → NOT_REQUIRED` transition — and a reopen likewise resets it.

Closing an incident is a `Supervisor` act reserved for the `MONITORING` stage, and it is the most heavily gated transition in the system. The closure request may carry optional `notes`. Five gates stand in front of it: the incident's lifecycle must be `MONITORING`, otherwise `ERR_INCIDENT_NOT_ACTIVE`; `make_safe_completed` must be true, otherwise `ERR_MAKE_SAFE_NOT_COMPLETED` (HTTP 422); when `leak_confirmed` is true a `FINAL` responsibility determination must exist for the incident, otherwise `ERR_DETERMINATION_REQUIRED` (HTTP 422); no dispatch assignment may remain `EN_ROUTE` or `ON_SCENE`, otherwise `ERR_OPEN_DISPATCHES_EXIST` (HTTP 409); and no shutoff order may stand in `REQUESTED` or `AUTHORIZED`, otherwise `ERR_OPEN_SHUTOFF_ORDER` (HTTP 409). A successful close moves the incident to `CLOSED`, stamps `closed_at` from the logical clock, returns `entry_status` to `NOT_REQUIRED`, increments the incident `version`, and marks covering draft or rejected regulatory reports stale.

### 3.6. Gas Shutoff and Restoration

A shutoff order physically stops gas flow and travels its own lifecycle: `REQUESTED → AUTHORIZED → EXECUTED → RESTORED`, with `DECLINED` as the alternate terminal refusal. A `FieldTechnician` or `Supervisor` requests an order with a `scope` of `METER`, `APPLIANCE`, or `SERVICE_LINE`, an `entry_required` flag indicating whether execution needs premise entry, and a free-text `reason`; the order is born `REQUESTED` with the requester's opaque identifier stamped as `requested_by_user_id`.

Only a `Supervisor` disposes of a request. Authorization requires the order to be `REQUESTED` (otherwise `ERR_INVALID_STATE`) and stamps the authorizer's `X-User-ID` into `authorized_by_user_id`, moving the order to `AUTHORIZED`. Declining — optionally annotated with a `reason` — moves a `REQUESTED` order to `DECLINED`, terminal.

Execution belongs to a `FieldTechnician` holding an active assignment on the incident; anyone else is refused with `ERR_NOT_ASSIGNED_TO_INCIDENT`, and an order not in `AUTHORIZED` is refused with `ERR_INVALID_STATE`. When the order's `entry_required` flag is true, one more gate applies: the incident's `entry_status` must be `AUTHORIZED` or `FORCED`, or execution is rejected with `ERR_ENTRY_NOT_AUTHORIZED` (HTTP 422). Successful execution stamps `executed_at` from the logical clock, records the executing technician's identity in `executed_by_technician_id`, and recomputes the incident's `gas_flow_stopped` — which is true exactly when any of the incident's shutoff orders stands in `EXECUTED` or `RESTORED`. A meter-scope execution under evacuation conditions is also a media event: when the order's `scope` is `METER`, the incident's `evacuation_required` is true, and no automatic notification has yet been created for the incident, the server auto-creates a draft public notification of origin `AUTO_SEVERITY` on the `MEDIA` channel and sets the incident's `auto_notification_created` flag (§3.8). Restoration follows the same technician-assignment guard, requires the order to be `EXECUTED`, and stamps `restored_at` as the order reaches `RESTORED`, terminal.

### 3.7. Responsibility Determination and Repair Work Orders

When gas flowed, someone must answer for which side of the meter the leak sits on. A `Supervisor` drafts a responsibility determination with a `responsibility` of `INSIDE_CUSTOMER`, `OUTSIDE_COMPANY`, or `SHARED`, an evidentiary `basis` of `METER_LOCATION`, `BARHOLE_SURVEY`, `CUSTOMER_APPLIANCE_TRACE`, or `EXCAVATION`, and optional `notes`. Because this is the second optimistic-concurrency-guarded write, the request must carry `expected_incident_version` matching the incident's current `version`, or it is rejected with `ERR_STALE_INCIDENT_VERSION` (HTTP 412) — a determination drafted before, say, a make-safe completion changed `leak_confirmed` is not a valid basis for the record. The draft is born in `DRAFT` status with the drafter's opaque identifier stamped as `drafted_by_user_id`, and its creation increments the incident `version`.

Finalization is where segregation of duties bites. A `Supervisor` finalizes a determination that must currently be `DRAFT` — otherwise `ERR_DETERMINATION_NOT_DRAFT` (HTTP 409) — and the finalizer's `X-User-ID` must differ from `drafted_by_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Finalization stamps `finalized_at` and `finalized_by_user_id`, and the incident's `responsibility` recomputes to the newly final value, having been null while no `FINAL` determination existed. Any other determination for the same incident that was `FINAL` automatically becomes `SUPERSEDED`, terminal. The downstream consequences split on the verdict: when the determination is `INSIDE_CUSTOMER`, the incident's `customer_referral_required` flag sets to true and no company work order results; when it is `OUTSIDE_COMPANY` or `SHARED`, the server auto-creates a repair work order with `origin` `AUTO_DETERMINATION` in status `OPEN`, priced from the provisional matrix below, and — because `OPEN` work orders hold no reservation — no budget moves yet. Finalization also increments the incident `version` and marks covering draft or rejected reports stale. When the determination resolves to `INSIDE_CUSTOMER`, the earlier `leak_location_guess` hints and `basis` notes are what the customer referral is built from.

Every repair work order carries two estimates. The `provisional_estimate_cents` is fixed at creation from a matrix keyed by the responsibility in force at creation time and the incident's current priority. For `OUTSIDE_COMPANY` the figures are 150,000 cents at `P1`, 90,000 at `P2`, 45,000 at `P3`, and 20,000 at `P4`. For `INSIDE_CUSTOMER` every priority prices at zero — a customer-side referral carries no company cost. For `SHARED` the figures are 75,000, 45,000, 22,500, and 10,000 cents across `P1` to `P4`. When no `FINAL` determination exists at creation, the undetermined row applies: a flat 60,000 cents regardless of priority. The `current_estimate_cents` mirrors the provisional estimate throughout the order's working life and becomes the `final_cost_cents` once the order completes; it is this current figure that the territory reservation ledger of §2.9 counts.

A `Supervisor` may also create a work order manually — such an order is born `OPEN` with `origin` `MANUAL` and its provisional estimate drawn from the same matrix, the undetermined row applying when no final determination exists — but manual creation is permitted only on an incident whose `leak_confirmed` flag is true.

Scheduling pins the order to a crew and a window. The schedule request names a `crew_id` and a window from `window_start` to `window_end`, which are stored on the order as `scheduled_window_start` and `scheduled_window_end`. The gates, in addition to the order being `OPEN` (otherwise `ERR_INVALID_STATE`): the window end must be strictly after its start (`ERR_INVALID_TIME_RANGE`, HTTP 400); a `FINAL` responsibility determination must exist for the incident (`ERR_DETERMINATION_REQUIRED`, HTTP 422); the crew must exist, be active, and operate in the incident's own territory — a crew whose `territory_id` differs from the incident's is rejected with `ERR_INVALID_STATE` — and the window must respect the crew's travel buffer and the territory's budget. The travel buffer demands a gap of at least thirty minutes between the new window and the window of every other non-cancelled work order on the same crew: the new `window_start` must fall at or after an existing window's end plus thirty minutes, or the new `window_end` must fall at or before the existing window's start minus thirty minutes, and any closer approach is rejected with `ERR_TRAVEL_BUFFER_VIOLATION` (HTTP 409). The budget gate refuses the schedule with `ERR_REPAIR_BUDGET_EXCEEDED` (HTTP 402) when the territory's `repair_reserved_cents` plus the order's `current_estimate_cents` would exceed `repair_budget_cap_cents`. A successful schedule moves the order `OPEN → SCHEDULED`, stores the crew and window, increments the order `version`, and adds the current estimate to the territory reservation.

From `SCHEDULED` the supervisor starts the work (`SCHEDULED → IN_PROGRESS`), may hold it (`IN_PROGRESS → ON_HOLD`) with an optional `reason`, and may resume it (`ON_HOLD → IN_PROGRESS`); each of these requires exactly the from-state named, failing otherwise with `ERR_INVALID_STATE`.

Completion is where the money settles. The completion request carries the `lines` of parts used — each line a `description`, a `quantity`, a `unit_price_cents`, and a `discount_pct` — and the `labor_minutes` actually worked. The order must be `IN_PROGRESS` (otherwise `ERR_INVALID_STATE`), the `lines` array must be non-empty, and `labor_minutes` must be at least zero, with shape violations rejected as `ERR_INVALID_REQUEST` (HTTP 400). The final cost is computed in a pinned order that never sums unrounded values. First, each parts line is priced on its own: the line's `quantity` times its `unit_price_cents` times one minus its `discount_pct`, rounded half up to a whole cent; the parts total is the sum of those per-line rounded amounts. Second, labor is quantized to the quarter hour: `labor_billed_minutes` is `labor_minutes` rounded up to the next multiple of fifteen, with an exact multiple billed as itself — fifteen minutes bills as fifteen. Third, the labor charge is `labor_billed_minutes` divided by sixty and multiplied by the assigned crew's `hourly_rate_cents`, rounded half up to a whole cent. The `final_cost_cents` is the parts total plus the labor charge. Completion then sets `current_estimate_cents` to the final cost, releases the schedule-time reservation by subtracting the `provisional_estimate_cents` from the territory's `repair_reserved_cents`, stamps `completed_at` from the logical clock, and moves the order to `COMPLETED`, terminal.

Cancellation is available from `OPEN`, `SCHEDULED`, or `ON_HOLD` — any other state fails with `ERR_INVALID_STATE` — and records the supplied `reason` on the order as `cancel_reason`. Cancelling an `OPEN` order moves no money, since it never held a reservation; cancelling from `SCHEDULED` or `ON_HOLD` subtracts the order's `current_estimate_cents` from the territory reservation. `CANCELLED` is terminal.

### 3.8. Regulatory Reporting and Public Notification

Regulatory oversight closes the loop. A `Supervisor` generates a response-time compliance report for a territory by naming the `territory_id` and a reporting period from `period_start` to `period_end`; the period is half-open — start inclusive, end exclusive — and an end not strictly after its start is rejected with `ERR_INVALID_TIME_RANGE`. The report is born in `DRAFT`, its `generated_at` stamped from the logical clock, its `needs_regeneration` flag false, and its `regeneration_count` zero, with all snapshot figures computed at generation.

The snapshot computation follows a pinned order. First, every candidate incident has its pauses, adjusted elapsed, and raw elapsed recomputed as of the generation instant. Second, each candidate's breach verdict is evaluated against the threshold for its *current* priority. Third, the counts and rates aggregate. The candidate set is the territory's incidents whose `response_clock_started_at` falls inside the period, excluding `MERGED` incidents; the `incident_count` is the size of that set. An incident counts as determined when its outcome is known at generation time: either its `first_arrival_at` is set, or its adjusted elapsed already exceeds its threshold in seconds. For eligibility purposes, a pause still open at generation time is computed as if it ended at the generation timestamp — an incident whose only route to being determined runs through such a virtual close is not determined until it actually arrives or crosses the threshold under that accounting. The `determined_count` tallies determined incidents and the `pending_count` is the remainder. The two compliance variants then diverge on the determined set, both applying the compliant-when-not-strictly-greater boundary of §2.7: `compliant_count_adjusted` counts determined incidents whose adjusted elapsed is at most the threshold in seconds, while `compliant_count_raw` counts those whose raw elapsed — pauses ignored — is at most the threshold. The `compliance_rate_adjusted` and `compliance_rate_raw` are the corresponding counts divided by `determined_count`, each expressed to four decimal places rounded half up, and each null when `determined_count` is zero. A `stats` object preserves the per-priority audit detail, breaking each of `P1` through `P4` into its own `total`, `determined`, `compliant_raw`, and `compliant_adjusted` figures.

A draft report is a living snapshot only until it is submitted. Whenever a covered incident changes — triage, reclassification, duplicate-call escalation, a new atmospheric reading, make-safe completion, closure, reopening, or determination finalization — or a new incident appears in the period, every covering report still in `DRAFT` or `REJECTED` has its `needs_regeneration` flag set to true. Reports in `SUBMITTED` or `ACCEPTED` are frozen and never acquire the flag. Submission requires the report to be `DRAFT` and its `needs_regeneration` to be false; a stale draft must be regenerated first, and submitting one is rejected with `ERR_REPORT_NOT_DRAFT` (HTTP 409) carrying a stale-detail message, as is submitting a report that is not in draft at all. Successful submission stamps `submitted_at` and freezes the snapshot.

The `Regulator` then disposes of the submission: acceptance requires `SUBMITTED` (otherwise `ERR_INVALID_STATE`) and moves the report to `ACCEPTED`, terminal; rejection likewise requires `SUBMITTED`, moves the report to `REJECTED`, and stores the supplied `reason` as the report's `reject_reason`. A `Supervisor` regenerates a report in `DRAFT` or `REJECTED` — any other state fails with `ERR_INVALID_STATE` — which recomputes every count and rate at the current logical time, re-stamps `generated_at`, clears `needs_regeneration` to false, increments `regeneration_count`, and returns a `REJECTED` report to `DRAFT`. Regulators listing or reading reports see only those past draft — `SUBMITTED`, `ACCEPTED`, or `REJECTED` — under the scope rule of §2.1, and the report list supports `territory_id` and `status` filters.

Public notification is the system's voice. A `Supervisor` drafts a notification on an incident with a `channel` of `MEDIA`, `PUBLIC_ALERT`, or `AGENCY_NOTICE`, a `headline`, and a `body`; the draft is born in `DRAFT` status with `origin` `MANUAL`. Two automatic origins exist alongside it. The `AUTO_PRIORITY` rule fires whenever an incident's priority reaches `P1` — at primary-call creation, at triage, at reclassification, at duplicate-call escalation, or through a merge — provided the incident's `auto_notification_created` flag is still false; it creates a draft notification on the `PUBLIC_ALERT` channel and sets the flag. The `AUTO_SEVERITY` rule fires when a recomputed `severity_score` reaches at least 80, and likewise when a meter-scope shutoff is executed under evacuation conditions as described in §3.6 — the latter on the `MEDIA` channel — again only while the flag is false. The flag enforces idempotence across both rules: at most one automatic notification ever exists per incident. Issuing requires a `DRAFT` notification — otherwise `ERR_NOTIFICATION_NOT_DRAFT` (HTTP 409) — stamps `issued_at`, and moves it to `ISSUED`. Retracting requires `ISSUED` — otherwise `ERR_NOTIFICATION_NOT_ISSUED` (HTTP 409) — accepts an optional `reason`, stamps `retracted_at`, and moves it to `RETRACTED`, terminal. Discarding requires `DRAFT` and moves the notification to `DISCARDED`, terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions, regenerations, and the clock advance — return `200 OK`. Request payloads, computed fields, and side effects are specified in §2 and §3; this table is the addressing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock to a supplied instant | SystemAdmin |
| POST | `/gas-ops/territories` | Create a service territory with SLA thresholds and budget cap | SystemAdmin |
| GET | `/gas-ops/territories` | List territories | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/territories/{territoryId}` | Get a territory | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/territories/{id}/incidents` | List incidents of a territory (Regulator sees only CLOSED/MERGED) | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/technicians` | Register a field technician | SystemAdmin |
| GET | `/gas-ops/technicians` | List technicians | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/technicians/{technicianId}` | Get a technician with computed shift and load fields | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/technicians/{id}/shifts` | Declare a half-open shift window for a technician | SystemAdmin, Supervisor |
| GET | `/gas-ops/technicians/{id}/shifts` | List shifts of a technician | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/technicians/{id}/dispatches` | List dispatch assignments of a technician | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/technicians/{id}/atmospheric-readings` | List readings recorded by a technician | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/technicians/{id}/make-safe-actions` | List make-safe actions recorded by a technician | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/repair-crews` | Register a repair crew | SystemAdmin |
| GET | `/gas-ops/repair-crews` | List repair crews | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/repair-crews/{crewId}` | Get a repair crew | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/repair-crews/{id}/repair-work-orders` | List work orders scheduled to a crew | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/emergency-calls` | Intake an odor/emergency call with dedup and recurrence classification | Dispatcher, Supervisor |
| GET | `/gas-ops/emergency-calls` | List emergency calls | SystemAdmin, Dispatcher, Supervisor |
| GET | `/gas-ops/emergency-calls/{callId}` | Get an emergency call | SystemAdmin, Dispatcher, Supervisor |
| GET | `/gas-ops/incidents` | List incidents (Regulator: CLOSED/MERGED only; FieldTechnician: assignment-scoped) | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/incidents/{incidentId}` | Get an incident with all computed clock, severity, and breach fields | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/incidents/{incidentId}/triage` | Confirm/set priority; NEW or REOPENED to TRIAGED | Dispatcher, Supervisor |
| POST | `/gas-ops/incidents/{incidentId}/reclassify-priority` | Reclassify priority of an active incident; OCC-guarded | Dispatcher, Supervisor |
| POST | `/gas-ops/incidents/{incidentId}/close` | Close an incident in MONITORING after all gates pass | Supervisor |
| POST | `/gas-ops/incidents/{incidentId}/merge-duplicate` | Merge the body-named source incident into this (target) incident | Supervisor |
| POST | `/gas-ops/incidents/{incidentId}/entry-status` | Move entry status among NOT_REQUIRED, AWAITING_AUTHORIZATION, REFUSED | FieldTechnician, Supervisor |
| POST | `/gas-ops/incidents/{id}/response-clock-pauses` | Open a response-clock pause on the incident | Dispatcher, Supervisor |
| POST | `/gas-ops/response-clock-pauses/{pauseId}/end` | Close an open response-clock pause | Dispatcher, Supervisor |
| GET | `/gas-ops/incidents/{id}/response-clock-pauses` | List pauses of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/incidents/{id}/dispatches` | Dispatch a technician; deterministic selector when technician omitted | Dispatcher, Supervisor |
| GET | `/gas-ops/incidents/{id}/dispatches` | List assignments of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/dispatches/{dispatchId}` | Get a dispatch assignment | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/dispatches/{dispatchId}/arrive` | Assigned technician marks arrival; first arrival stops the clock | FieldTechnician |
| POST | `/gas-ops/dispatches/{dispatchId}/clear` | Assigned technician clears the scene | FieldTechnician |
| POST | `/gas-ops/dispatches/{dispatchId}/cancel` | Cancel an EN_ROUTE assignment | Supervisor |
| POST | `/gas-ops/dispatches/{dispatchId}/preempt` | Preempt an EN_ROUTE assignment to a strictly-higher-priority incident | Supervisor |
| POST | `/gas-ops/incidents/{id}/atmospheric-readings` | Record an atmospheric reading on the incident | FieldTechnician |
| GET | `/gas-ops/incidents/{id}/atmospheric-readings` | List readings of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/incidents/{id}/make-safe-actions` | Record a make-safe action; first action advances the lifecycle | FieldTechnician |
| GET | `/gas-ops/incidents/{id}/make-safe-actions` | List make-safe actions of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/incidents/{incidentId}/make-safe/complete` | Complete make-safe; incident moves to MONITORING | FieldTechnician |
| POST | `/gas-ops/incidents/{id}/premise-entry-authorizations` | Record an entry authorization; consent or forced/warranted | Dispatcher, Supervisor |
| GET | `/gas-ops/incidents/{id}/premise-entry-authorizations` | List entry authorizations of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/incidents/{id}/shutoff-orders` | Request a gas shutoff order | FieldTechnician, Supervisor |
| GET | `/gas-ops/incidents/{id}/shutoff-orders` | List shutoff orders of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/shutoff-orders/{shutoffId}` | Get a shutoff order | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/shutoff-orders/{shutoffId}/authorize` | Authorize a REQUESTED shutoff | Supervisor |
| POST | `/gas-ops/shutoff-orders/{shutoffId}/decline` | Decline a REQUESTED shutoff | Supervisor |
| POST | `/gas-ops/shutoff-orders/{shutoffId}/execute` | Execute an AUTHORIZED shutoff (entry gate applies) | FieldTechnician |
| POST | `/gas-ops/shutoff-orders/{shutoffId}/restore` | Restore gas after an EXECUTED shutoff | FieldTechnician |
| POST | `/gas-ops/incidents/{id}/responsibility-determinations` | Draft a responsibility determination; OCC-guarded | Supervisor |
| GET | `/gas-ops/incidents/{id}/responsibility-determinations` | List determinations of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/responsibility-determinations/{determinationId}` | Get a determination | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/responsibility-determinations/{determinationId}/finalize` | Finalize a DRAFT determination (segregation of duties) | Supervisor |
| POST | `/gas-ops/incidents/{id}/repair-work-orders` | Manually create a work order on a leak-confirmed incident | Supervisor |
| GET | `/gas-ops/incidents/{id}/repair-work-orders` | List work orders of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/repair-work-orders/{workOrderId}` | Get a work order | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/schedule` | Schedule an OPEN work order to a crew window | Supervisor |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/start` | Start a SCHEDULED work order | Supervisor |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/hold` | Hold an IN_PROGRESS work order | Supervisor |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/resume` | Resume an ON_HOLD work order | Supervisor |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/complete` | Complete an IN_PROGRESS work order with parts lines and labor | Supervisor |
| POST | `/gas-ops/repair-work-orders/{workOrderId}/cancel` | Cancel an OPEN, SCHEDULED, or ON_HOLD work order | Supervisor |
| POST | `/gas-ops/regulatory-reports` | Generate a DRAFT response-time compliance snapshot | Supervisor |
| GET | `/gas-ops/regulatory-reports` | List reports (Regulator sees only non-DRAFT) | SystemAdmin, Dispatcher, Supervisor, Regulator |
| GET | `/gas-ops/regulatory-reports/{reportId}` | Get a report (Regulator cannot read DRAFT) | SystemAdmin, Dispatcher, Supervisor, Regulator |
| POST | `/gas-ops/regulatory-reports/{reportId}/submit` | Submit a DRAFT report, freezing the snapshot | Supervisor |
| POST | `/gas-ops/regulatory-reports/{reportId}/accept` | Regulator accepts a SUBMITTED report | Regulator |
| POST | `/gas-ops/regulatory-reports/{reportId}/reject` | Regulator rejects a SUBMITTED report | Regulator |
| POST | `/gas-ops/regulatory-reports/{reportId}/regenerate` | Recompute a DRAFT or REJECTED report snapshot | Supervisor |
| POST | `/gas-ops/incidents/{id}/public-notifications` | Draft a media/public-safety notification | Supervisor |
| GET | `/gas-ops/incidents/{id}/public-notifications` | List notifications of an incident | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| GET | `/gas-ops/public-notifications/{notificationId}` | Get a notification | SystemAdmin, Dispatcher, FieldTechnician, Supervisor, Regulator |
| POST | `/gas-ops/public-notifications/{notificationId}/issue` | Issue a DRAFT notification | Supervisor |
| POST | `/gas-ops/public-notifications/{notificationId}/retract` | Retract an ISSUED notification | Supervisor |
| POST | `/gas-ops/public-notifications/{notificationId}/discard` | Discard a DRAFT notification | Supervisor |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_TIME_RANGE` | 400 Bad Request |
| `ERR_REPAIR_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_REGULATOR_SCOPE_RESTRICTED` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_TO_INCIDENT` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TERRITORY_NOT_FOUND` | 404 Not Found |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 Not Found |
| `ERR_CREW_NOT_FOUND` | 404 Not Found |
| `ERR_CALL_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPATCH_NOT_FOUND` | 404 Not Found |
| `ERR_PAUSE_NOT_FOUND` | 404 Not Found |
| `ERR_SHUTOFF_NOT_FOUND` | 404 Not Found |
| `ERR_DETERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_INCIDENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INCIDENT_NOT_TRIAGED` | 409 Conflict |
| `ERR_INCIDENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_PAUSE_EXISTS` | 409 Conflict |
| `ERR_NO_AVAILABLE_TECHNICIAN` | 409 Conflict |
| `ERR_TECHNICIAN_OFF_SHIFT` | 409 Conflict |
| `ERR_TECHNICIAN_TERRITORY_MISMATCH` | 409 Conflict |
| `ERR_TECHNICIAN_CAPACITY_REACHED` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_TRAVEL_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_DISPATCH_NOT_PREEMPTABLE` | 409 Conflict |
| `ERR_MERGE_TARGET_INVALID` | 409 Conflict |
| `ERR_OPEN_DISPATCHES_EXIST` | 409 Conflict |
| `ERR_OPEN_SHUTOFF_ORDER` | 409 Conflict |
| `ERR_DETERMINATION_NOT_DRAFT` | 409 Conflict |
| `ERR_REPORT_NOT_DRAFT` | 409 Conflict |
| `ERR_NOTIFICATION_NOT_DRAFT` | 409 Conflict |
| `ERR_NOTIFICATION_NOT_ISSUED` | 409 Conflict |
| `ERR_ATMOSPHERIC_READING_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MAKE_SAFE_NOT_COMPLETED` | 422 Unprocessable Entity |
| `ERR_ENTRY_NOT_AUTHORIZED` | 422 Unprocessable Entity |
| `ERR_DETERMINATION_REQUIRED` | 422 Unprocessable Entity |

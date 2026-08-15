# Environmental Services Room Turnover API — Product Requirements Document

## 1. Introduction

Every discharged hospital bed is a capacity asset sitting idle until Environmental Services turns it over. While a bed waits dirty, admissions queue in the emergency department, transfer requests stall, and placement coordinators make phone calls instead of decisions. At the same time, not all cleans are equal: an isolation room after a C. difficile discharge demands a different protocol, different chemicals, and a different verification standard than a routine turnover, and an outbreak on a unit can force an entire fleet of in-flight work orders to escalate mid-shift.

This document specifies the Environmental Services Room Turnover API, the system of record for that turnover loop. It governs the discharge-to-ready pipeline — discharge notification, clean-request queuing and prioritization against live placement demand, technician assignment and pull-based dispatch, chemical reservation and consumption through an append-only supply ledger, independent quality verification by ATP swab or fluorescent marker, and bed-ready notification back to patient flow. Around that core loop it wraps the department's control surfaces: clean time standards pinned per request, staff shift and productivity accounting, outbreak-driven protocol escalation, maintenance windows that take beds out of service under an aggregate capacity cap, and a periodic ops-run that sweeps for SLA breaches, expires stale demands and notifications, and records turnaround analytics per unit.

All server-side time in this system is deterministic. Rather than reading wall time, every timestamp the server stamps is drawn from a logical clock that operators can advance explicitly, making turnaround-time measurement, SLA evaluation, and window arithmetic fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity; a request where either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes seven roles: `EVSAdministrator`, `EVSDispatcher`, `EVSTechnician`, `QualityAuditor`, `BedPlacementCoordinator`, `InfectionPreventionist`, and `Any`. Access to each operation is restricted to the roles listed for it in §4; a call made with a role outside that list is rejected with `ERR_INSUFFICIENT_PERMISSIONS`. `Any` denotes shared read access: every read endpoint is authorized for `Any`, meaning any recognized role may read.

Two roles are entity-backed. When `X-User-Role` is `EVSTechnician`, `X-User-ID` is the `id` of the acting `StaffMember`, and ownership checks on any resource that references a `StaffMember` compare the resource's foreign-key field to `X-User-ID`; the identified staff member's `capabilities` must include `CLEAN`, otherwise the call is rejected with `ERR_ROLE_CAPABILITY_MISMATCH`. When `X-User-Role` is `QualityAuditor`, `X-User-ID` is likewise the `id` of the acting `StaffMember`, whose `capabilities` must include `AUDIT`, again enforced with `ERR_ROLE_CAPABILITY_MISMATCH`. For both entity-backed roles, an `X-User-ID` that does not correspond to an existing staff member is rejected with `ERR_STAFF_NOT_FOUND`.

The remaining roles are opaque. When `X-User-Role` is `EVSAdministrator`, `EVSDispatcher`, `BedPlacementCoordinator`, `InfectionPreventionist`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The server maintains a logical clock that is the single source of time for the entire system. At startup the logical time is exactly `2026-08-01T00:00:00Z`, and the clock never falls back to wall time. Every server-stamped datetime — `created_at`, `started_at`, `completed_at`, `verified_at`, `sent_at`, maintenance window stamps, the base instants from which `sla_due_at` is derived, and ops-run window boundaries — reads this logical clock, and every time-derived computation (waiting minutes, turnaround minutes, shift seconds, breach checks, expiry checks) evaluates against it. Every datetime the server emits — whether server-stamped, derived (such as `sla_due_at` or `planned_end_at`), or echoed from client input (such as `needed_by` or a supplied `planned_start_at`) — is rendered as ISO 8601 in UTC with exactly three fractional digits; the clock endpoint's `current_utc` follows the same rule, so the startup clock reports `2026-08-01T00:00:00.000Z`.

An administrator-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. The clock is monotonic: the supplied instant must be at or after the current logical time, and an attempt to move it backward is rejected with `ERR_CLOCK_REGRESSION`. Advancing the clock mutates no other entity; sweeps that react to the passage of time happen only through the ops-run described in §3.9.

### 2.5. Common Resource Properties and Resource Addressing

All primary resources — units, beds, placement demands, clean requests, staff members, quality audits, supply items, outbreak events, bed-ready notifications, maintenance windows, and clean standards — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits, recording when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp recording the last modification; it is refreshed on every change to the resource.
- **`version` (integer):** A system-managed integer that increments by 1 with every mutation of the resource, including mutations driven by cascades rather than by a direct client call on that resource.

Two resources are append-only exceptions. A `SupplyLedgerEntry` and a `TurnaroundSnapshot` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, neither has any update endpoint, and neither is ever modified after creation.

Every resource is addressed through path identifiers — `unit_id`, `bed_id`, `request_id`, `staff_id`, `audit_id`, `item_id`, `event_id`, `notification_id`, `demand_id`, `window_id`, `snapshot_id`, and `entry_id` — with clean standards addressed directly by their `clean_type` value. When an endpoint path contains a resource identifier, the system validates existence before any business rule executes. Where identifiers chain (for example, a snapshot listed under a `unit_id`), validation proceeds left to right, and the request is rejected with the 404 error corresponding to the first identifier that does not resolve: `ERR_UNIT_NOT_FOUND`, `ERR_BED_NOT_FOUND`, `ERR_CLEAN_REQUEST_NOT_FOUND`, `ERR_PLACEMENT_DEMAND_NOT_FOUND`, `ERR_STAFF_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`, `ERR_OUTBREAK_NOT_FOUND`, `ERR_NOTIFICATION_NOT_FOUND`, `ERR_STANDARD_NOT_FOUND`, `ERR_WINDOW_NOT_FOUND`, or `ERR_SNAPSHOT_NOT_FOUND`. Identifiers carried in the request body — such as `staff_id`, `clean_request_id`, `bed_id`, `unit_id`, or item ids — are validated after the path identifiers.

### 2.6. Cascading State Alignment

Beds, clean requests, placement demands, and bed-ready notifications form a tightly coupled cluster, and the system keeps them aligned without waiting for client calls on each one. When a clean request starts, completes, or is audited, the linked bed transitions automatically — a bed never needs a direct status write. When a ready bed is soiled, retracted into maintenance, or its match expires, the cascade travels three levels deep: bed to notification to demand. Conversely, when an audit is voided, a compensation cascade runs in reverse and restores both the request and the bed to their pre-failure states. Each entity touched by a cascade is independently mutated: its `updated_at` refreshes and, for entities that carry one, its `version` increments. In-flight work is generally protected from retroactive change — pinned time standards and recorded ledgers do not move under later edits — with one deliberate exception: outbreak activation re-pins a defined subset of queued and assigned work, as described in §3.8.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, and each requires a dedicated expected-version field naming the client's last observed `version` of the target resource. Endpoints not listed here do not take a version field.

Reassigning a clean request requires `expected_clean_request_version` matching the request's current `version`. Reassignment is legitimate at any time while the request remains `ASSIGNED`, so a second reassignment carries no state signal that a first one already happened; if another writer has advanced the request's version since the client last read it, the reassign is rejected with `ERR_STALE_REQUEST_VERSION` (HTTP 412), preventing the client from overwriting an assignment it has not observed.

Recounting a supply item requires `expected_supply_item_version` matching the item's current `version`. A recount asserts that the physical count reflects the item's state at the version the client observed; restocks, consumptions, and earlier recounts all advance that version, so a recount submitted against a superseded version is rejected with `ERR_STALE_SUPPLY_VERSION` (HTTP 412) even though the same recount with a fresh version would succeed.

Updating a clean standard requires `expected_standard_version` matching the standard row's current `version`. Because an update is a supersede-style write whose values in-flight requests may already have pinned against, an update carrying an older version is rejected with `ERR_STALE_STANDARD_VERSION` (HTTP 412) so an operator editing from a stale read does not silently clobber a newer standard.

### 2.8. Numeric Precision and Rounding

All arithmetic in the system uses decimal math, never binary floating point. Scores and credit amounts — `priority_score`, `productivity_score`, `verified_credit_total`, and per-clean credits — are carried to exactly 2 decimal places using round-half-up. Durations behave differently: elapsed-time measurements such as turnaround minutes, waiting minutes, and actual cleaning minutes are whole minutes obtained by rounding the underlying second counts down, while time standards are whole minutes obtained by rounding half up (so a raw standard of 67.5 minutes becomes 68). Supply quantities are integer units throughout. Where a calculation feeds another, the rounding order matters and is pinned per rule: productivity credits are rounded per clean to 2 decimal places before they are summed, never summed raw and rounded once.

### 2.9. The Append-Only Supply Ledger

Chemical and supply stock is ledger-derived, never directly written. A supply item's `on_hand_quantity` is, at all times, the sum of the `quantity_delta` values across every ledger entry recorded for that item; its `reserved_quantity` is the sum of per-line bill-of-materials quantities over clean requests that currently hold a reservation (`supply_reserved` true) and consume that item. Every movement of stock is a `SupplyLedgerEntry` carrying the `supply_item_id`, an `entry_type` of `RESTOCK`, `CONSUME`, or `RECOUNT_ADJUSTMENT`, a signed `quantity_delta` — positive for restocks, negative for consumptions, and signed either way for recount adjustments — and an optional operator `note`. Consumption entries also record the `clean_request_id` they served; other entry types leave it null. Because the ledger is the truth, restocks, recounts, and clean-driven consumption all manifest as new entries, and an item's `stock_status` reads `LOW` whenever its `on_hand_quantity` has fallen to or below its `reorder_threshold`, and `STOCKED` otherwise.

### 2.10. Validation Order and State-Check Precedence

Every request passes through a fixed validation cascade, and the order is part of the contract. First, the presence of the `X-User-ID` and `X-User-Role` headers is enforced (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, request shape: required fields must be present, types must be valid, enum values must be in range, a maintenance window's `end_at` must be strictly after its `start_at` (`ERR_INVALID_WINDOW`), audit method and method-specific fields must be consistent (`ERR_AUDIT_METHOD_FIELD_MISMATCH`), and clock submissions must be monotonic (`ERR_CLOCK_REGRESSION`); any other malformed body is rejected with `ERR_INVALID_REQUEST`. Shape errors beat authorization — a malformed body is rejected before role checks run. Third, the role must be listed for the endpoint (`ERR_INSUFFICIENT_PERMISSIONS`), and for the entity-backed roles the identified staff member must hold the matching capability (`ERR_ROLE_CAPABILITY_MISMATCH`). Fourth, path identifiers must resolve left to right, followed by body foreign keys (the 404 family of §2.5). Fifth, ownership: a technician may start or complete only a request assigned to their own `X-User-ID` (`ERR_NOT_ASSIGNED_TECHNICIAN`), and the clock and break endpoints require the caller's `X-User-ID` to equal the path `staff_id` (`ERR_STAFF_IDENTITY_MISMATCH`). Sixth, optimistic-concurrency fields must match current versions (the 412 family of §2.7).

Only then do state and business rules run. State validity comes first, and within it a terminal-state rejection always precedes a wrong-state rejection: a clean request that has reached `VERIFIED` or `CANCELLED` answers `ERR_REQUEST_ALREADY_TERMINAL` to any further transition attempt, never a wrong-state error, while a request that is merely in the wrong non-terminal state answers the corresponding not-in-state error. After state checks, the infection-control gates evaluate in a fixed sequence — certification coverage first (`ERR_STAFF_CERTIFICATION_MISMATCH`), then STAT-tier eligibility (`ERR_STAFF_NOT_STAT_ELIGIBLE`), then the second-set-of-hands rule for recleans (`ERR_RECLEAN_SAME_TECHNICIAN`), then segregation between auditor and cleaner (`ERR_AUDITOR_IS_CLEANER`). The temporal double-booking check (`ERR_STAFF_DOUBLE_BOOKED`) follows, then the referential rule that a bed may carry at most one open clean request (`ERR_OPEN_REQUEST_EXISTS`), and finally the business constraints: supply availability (`ERR_INSUFFICIENT_SUPPLY`), unit maintenance capacity (`ERR_CAPACITY_EXCEEDED`), clean-standard uniqueness (`ERR_DUPLICATE_STANDARD`), and the one-active-outbreak-per-unit rule (`ERR_OUTBREAK_ALREADY_ACTIVE`).

## 3. Business Logic & Workflows

### 3.1. Facility Configuration: Units, Beds, Standards, and Supplies

Before any cleaning can happen, an `EVSAdministrator` builds the facility model. A **unit** is created with a facility-unique `unit_code` and a human-readable `display_name`. Each unit carries an `outbreak_posture`, which starts at `NORMAL` and reads `OUTBREAK` exactly while the unit has at least one outbreak event in `ACTIVE` status — it is recomputed whenever an outbreak is activated or lifted, never set directly. Each unit also carries an `ops_run_index`, a monotonic ops-run epoch that starts at 0 and increments by 1 on each ops-run executed for the unit; the epoch matters because audit voids are bounded by it (§3.6). Units can be listed and read by anyone.

**Beds** are registered under a unit by supplying the `unit_id`, a `bed_code` label such as `4W-12A`, and a `bed_kind` of `STANDARD`, `ISOLATION`, or `ICU`. A new bed starts its life in `VACANT_DIRTY` status; its `last_discharge_at` stays null until its first discharge and its `last_ready_at` until its first verified clean, and both turnaround metrics remain null until that first readiness event. The bed registry can be listed with optional filters on `unit_id`, `bed_status`, and `bed_kind`.

**Clean standards** define the time and verification bar for each clean type. There is exactly one standard row per `clean_type` — `ROUTINE`, `ISOLATION`, or `TERMINAL` — and creating a second row for a type that already has one is rejected with `ERR_DUPLICATE_STANDARD`. Each row carries `base_minutes` (the base time standard, which must be greater than zero), `outbreak_multiplier_bps` (the outbreak multiplier in basis points, where 10000 means a 1.0x multiplier and values below 10000 are rejected), and `atp_rlu_threshold` (the ATP pass threshold for the type, which must be greater than zero). Updating a standard is an OCC-guarded supersede write per §2.7; in-flight requests keep their pinned values, and the new row governs only future pins and the `current_estimate_minutes` computation.

**Supply items** are registered with an `item_code` — one of `DISINFECTANT`, `PPE_PACK`, `CLOTH`, or `SEALANT`, unique across the facility — a `display_name`, an opening `initial_on_hand`, and a `reorder_threshold` that must be zero or greater. Registration writes a `RESTOCK` ledger entry for the opening quantity, so on-hand stock is ledger-derived from the first moment (§2.9). Restocking adds a further `RESTOCK` entry for the supplied `quantity`; a physical recount asserts a `counted_on_hand` and, guarded by `expected_supply_item_version` per §2.7, writes a `RECOUNT_ADJUSTMENT` entry whose delta is the counted value minus the current `on_hand_quantity` — a delta that may legitimately be zero, in which case the entry is still written. Both operations recompute `stock_status` and increment the item's `version`. Ledger entries can be listed and filtered by `supply_item_id` or `clean_request_id`, and fetched individually.

### 3.2. Placement Demand and Queue Prioritization

Patient flow enters the system as **placement demands**. A `BedPlacementCoordinator` creates a demand with the `unit_id` needing a bed, a `required_bed_kind` of `STANDARD`, `ISOLATION`, or `ICU`, an `urgency_tier` of `STAT`, `URGENT`, or `STANDARD`, and a `needed_by` instant marking the latest acceptable placement time. A new demand is `OPEN`; its `matched_bed_id` stays null unless it becomes `MATCHED`, and its `fulfilled_at` stays null unless the matched bed is admitted. Demands can be listed filtered by `unit_id`, `status`, `matched_bed_id`, or `required_bed_kind`.

A demand's `priority_score` is recomputed on every read, at every ops-run, on the demand's own creation, regrade, or cancellation, and whenever a bed of the matching kind in the unit enters or leaves `READY`, because bed scarcity feeds the score. The score combines three parts. First, an urgency base: 1000 for `STAT`, 500 for `URGENT`, 100 for `STANDARD`. Second, a waiting component: 2 points per whole minute waited since creation, with partial minutes discarded and negative waits impossible, counting at most the first 120 minutes — two hours — of waiting. Third, a scarcity bonus of 50 points, applied exactly when the unit currently has no `READY` bed of the `required_bed_kind`. The total is rounded to two decimal places, half up.

Placement demand in turn drives the cleaning queue. For any clean request, the **contributing demands** are the `OPEN` demands in the same unit whose `required_bed_kind` equals the bed's `bed_kind`. The request's `priority_tier` is the highest urgency tier among contributing demands — `STAT` outranks `URGENT`, which outranks `STANDARD` — and falls back to `STANDARD` when no demand contributes. Its `priority_score` is the sum of a tier base — 10000 for `STAT`, 5000 for `URGENT`, 0 for `STANDARD` — plus the highest `priority_score` among the contributing demands (zero when there are none), plus a breach boost of 2500 once the request's `sla_breached` flag is true; the sum is rounded to two decimal places, half up. Any placement-demand event in the unit — create, regrade, cancel, expiry, match, or fulfill — as well as ops-runs and breach marking recomputes the tier and score of the matching queued requests, so the queue reprices itself as demand shifts.

Queue ordering, wherever the system must pick a request, is fixed: `priority_tier` rank descending, then `priority_score` descending, then `sla_due_at` ascending, then `created_at` ascending. No random or identifier-based tie-break appears anywhere in the ordering; the final tie-break is creation time.

A coordinator may **regrade** an `OPEN` demand, supplying a new `urgency_tier`; the demand's score recomputes and every `QUEUED` clean request on a matching-kind bed in the unit recomputes its tier and score in sympathy. Regrading anything but an `OPEN` demand is rejected with `ERR_DEMAND_NOT_OPEN`. A demand may also be **cancelled** from `OPEN` or `MATCHED`; cancelling a demand in any other state is likewise `ERR_DEMAND_NOT_OPEN`. Cancelling a `MATCHED` demand retracts its still-`SENT` bed-ready notification, and the bed it pointed to remains `READY`, now unmatched. An `OPEN` demand whose `needed_by` falls strictly before the current clock is expired by the next ops-run; at exact equality with the clock the demand stays `OPEN`.

### 3.3. From Discharge to a Queued Clean

The dominant entry point for cleaning work is the **discharge notification**. When a `BedPlacementCoordinator` discharges a bed, the bed must currently be `OCCUPIED` — otherwise the call is rejected with `ERR_BED_NOT_OCCUPIED`. The discharge stamps `last_discharge_at` with the current clock, moves the bed `OCCUPIED → VACANT_DIRTY`, and auto-creates a clean request for it. The request's `clean_type` comes from the discharge payload's `clean_type` when one is given; otherwise it defaults to `ISOLATION` for an `ISOLATION` bed and to `ROUTINE` otherwise. One override beats even an explicit input: when the unit's `outbreak_posture` is `OUTBREAK` and the bed is an `ISOLATION` bed, the new request is forced to `TERMINAL`, implementing the enhanced cleaning protocol automatically.

A dispatcher may also create a clean request manually, supplying a `bed_id` and a `clean_type`. Manual creation requires the bed to be `VACANT_DIRTY` (`ERR_BED_NOT_DIRTY` otherwise) and requires that the bed carry no other open request — a request in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, `PENDING_QA`, or `NEEDS_RECLEAN` status on the same bed rejects both manual creation and the discharge auto-create with `ERR_OPEN_REQUEST_EXISTS`. Every request creation, manual or automatic, also requires that a clean standard row exists for the chosen `clean_type`; creating a request for a type with no standard fails with `ERR_STANDARD_NOT_FOUND`. On the manual-creation and discharge paths this existence check runs before the bed-state and open-request checks, so a missing standard row answers `ERR_STANDARD_NOT_FOUND` ahead of `ERR_BED_NOT_DIRTY`, `ERR_BED_NOT_OCCUPIED`, or `ERR_OPEN_REQUEST_EXISTS`.

At creation the request **pins its time standard**, and the pin is frozen for the life of the request with exactly one exception (the outbreak upgrade of §3.8). The pinned `sla_target_minutes` is the effective time standard evaluated at that moment: the `base_minutes` of the clean type's standard row, multiplied by the row's `outbreak_multiplier_bps` divided by 10000 when the unit's posture is `OUTBREAK` at evaluation time, and taken unmultiplied otherwise; the raw value is rounded half-up to whole minutes. If the request's `priority_tier` is `STAT`, the target is then capped — it becomes the lesser of the rounded value and 45 minutes. The pin also snapshots the inputs that produced it: `pinned_base_minutes`, `pinned_outbreak_multiplier_bps`, and `pinned_with_outbreak` recording whether the outbreak multiplier applied. From the pin, `sla_due_at` is the request's `created_at` plus `sla_target_minutes`, and it is recomputed only if the target is ever re-pinned. Separately, every read of a request exposes `current_estimate_minutes`: the same formula evaluated against the clean type's *current* standard row and the unit's *current* posture, so the estimate diverges from the pin whenever a standard was edited or an outbreak was activated or lifted after pinning.

A new request is `QUEUED`, with `assigned_staff_id` null, `reclean_count` at 0, `supply_reserved` false, and `sla_breached` false. The request denormalizes a `unit_id` copied from its bed at creation so the queue can be filtered per unit; the queue listing also filters by `bed_id`, `status`, `assigned_staff_id`, and `priority_tier`. The `sla_breached` flag is set to true at an ops-run when the clock has moved strictly past `sla_due_at` while the request is `QUEUED`, `ASSIGNED`, or `IN_PROGRESS`; once true it stays true, and breach marking reprices the request through the boost of §3.2 without changing its demand-derived tier.

### 3.4. Staff Shifts, Assignment, and Pull-Based Dispatch

The workforce is a registry of **staff members**, each created by an administrator with a facility-unique `employee_code`, a `display_name`, a non-empty `capabilities` list drawn from `CLEAN` and `AUDIT`, and an optional `certifications` list drawn from `ISO_CERT` and `TERMINAL_CERT` that defaults to empty. `CLEAN` is required to act as an `EVSTechnician` and `AUDIT` to act as a `QualityAuditor` (§2.1); among certifications, `ISO_CERT` is required to take an `ISOLATION` clean, `TERMINAL_CERT` for a `TERMINAL` clean, and `ROUTINE` cleans require none. A new staff member is `OFF_SHIFT` with all counters zeroed, and the registry can be listed filtered by `shift_status`.

Shift management is strictly self-service: clocking in, clocking out, and starting or ending a break all require the caller's `X-User-ID` to equal the path `staff_id`, with any mismatch rejected as `ERR_STAFF_IDENTITY_MISMATCH`. Clocking in requires `OFF_SHIFT` (a second clock-in is `ERR_STAFF_ALREADY_ON_SHIFT`) and stamps `last_clock_in_at`. Starting a break requires `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`) and is refused while the staff member holds an `IN_PROGRESS` clean (`ERR_STAFF_HAS_ACTIVE_CLEANS`); it closes the current on-shift span by adding its whole seconds — from `last_clock_in_at` to now — into `shift_seconds_today` and stamps `break_started_at`. Ending a break requires `ON_BREAK` (`ERR_STAFF_NOT_ON_BREAK`), clears `break_started_at`, and restamps `last_clock_in_at` so a fresh on-shift span opens. Clocking out from `ON_SHIFT` or `ON_BREAK` is refused while the staff member holds any `ASSIGNED` or `IN_PROGRESS` clean (`ERR_STAFF_HAS_ACTIVE_CLEANS`); clocking out from `ON_SHIFT` adds the closing span's seconds to `shift_seconds_today`, while break spans never accrue. Open spans are not counted until they close, so `shift_seconds_today` moves only at break-start, break-end, and clock-out boundaries. Both clock-out and the verification events of §3.6 recompute the staff member's productivity, and a productivity breakdown endpoint exposes `productivity_score`, `verified_credit_total`, `qa_fail_count`, `shift_seconds_today`, `stat_eligible`, and `completed_clean_count` to any reader.

**Assignment** is the dispatcher's core act and moves a request from `QUEUED` — or from `NEEDS_RECLEAN`, for a reclean — to `ASSIGNED`. The dispatcher supplies a `staff_id` and may optionally supply a `planned_start_at`; when omitted, the planned window starts at the assignment-time clock. The planned window runs from `planned_start_at` for the request's pinned `sla_target_minutes`, and the derived `planned_end_at` marks its end. A battery of checks guards the transition, applied in the order of §2.10: a terminal request answers `ERR_REQUEST_ALREADY_TERMINAL`, a request in any other non-terminal state answers `ERR_REQUEST_NOT_QUEUED`; the staff member's certifications must cover the request's `clean_type` (`ERR_STAFF_CERTIFICATION_MISMATCH`); a `STAT`-tier request may go only to a staff member whose `stat_eligible` is true (`ERR_STAFF_NOT_STAT_ELIGIBLE`); and the planned window must satisfy the buffer rule below against every other `ASSIGNED` or `IN_PROGRESS` window already on that staff member (`ERR_STAFF_DOUBLE_BOOKED`). For a reclean assignment there is one more gate: the second-set-of-hands rule requires the new `staff_id` to differ from the request's `last_completed_by_staff_id`, so the technician whose work failed QA never picks up their own reclean (`ERR_RECLEAN_SAME_TECHNICIAN`). A successful assignment stamps `assigned_staff_id`, sets the planned window, raises the staff member's derived `active_clean_count` — the count of their requests in `ASSIGNED` or `IN_PROGRESS` — by one, and increments the request's `version`.

The **buffer rule** keeps a technician's commitments separated. Two planned windows on the same staff member conflict unless at least ten full minutes separate them in one direction or the other: the new window must start no earlier than ten minutes after the existing window ends, or the existing window must start no earlier than ten minutes after the new window ends. Exactly ten minutes of gap is permitted and does not conflict. The check is symmetric and considers every other `ASSIGNED` or `IN_PROGRESS` window on the staff member.

Three corrective operations keep the queue fluid. **Unassigning** returns an `ASSIGNED` request to `QUEUED`, clearing `assigned_staff_id` and the planned window, dropping the staff member's active count by one in compensation, and incrementing the request's `version`; anything not `ASSIGNED` is rejected (`ERR_REQUEST_NOT_ASSIGNED`, or `ERR_REQUEST_ALREADY_TERMINAL` when terminal). **Reassigning** swaps one `ASSIGNED` request to a different staff member; it is the OCC-guarded write of §2.7 requiring `expected_clean_request_version`, re-runs the certification, STAT-eligibility, and buffer checks for the new staff member, replaces the planned window, moves the active count from the old technician to the new one, and increments the request's `version`. **Cancelling** from `QUEUED` or `ASSIGNED` moves the request to `CANCELLED`, clearing any assignment and its active-count contribution; cancelling from `IN_PROGRESS` is the abort path of §3.5.

A technician may also **pull** work instead of waiting for dispatch. Pulling assigns the highest-ranked eligible `QUEUED` request to the pulling technician. The puller must be `ON_SHIFT`, and this is verified before selection runs (`ERR_STAFF_NOT_ON_SHIFT`). Eligibility then filters the queue: the request's `clean_type` must be covered by the puller's certifications, a `STAT`-tier request is invisible to a puller whose `stat_eligible` is false, and the window that would begin at the current clock and run for the request's `sla_target_minutes` must satisfy the ten-minute buffer rule against the puller's other `ASSIGNED` or `IN_PROGRESS` windows. The eligible pool is ranked by the queue ordering of §3.2 — tier rank descending, score descending, `sla_due_at` ascending, `created_at` ascending — and the top request becomes `ASSIGNED` to the puller with `planned_start_at` set to now. When no request is eligible, the pull is rejected with `ERR_QUEUE_EMPTY`.

### 3.5. Executing the Clean: Supplies and Bed Movement

The assigned technician — and only that technician — drives execution; a start or complete attempted by anyone else is rejected with `ERR_NOT_ASSIGNED_TECHNICIAN`.

**Starting** a clean requires the request to be `ASSIGNED` (`ERR_REQUEST_ALREADY_TERMINAL` when terminal, `ERR_REQUEST_NOT_ASSIGNED` otherwise) and the technician to be `ON_SHIFT` (`ERR_STAFF_NOT_ON_SHIFT`). Starting also reserves chemicals, and this is where the bill of materials bites. A full `ROUTINE` clean consumes 2 units of `DISINFECTANT` and 4 of `CLOTH`; a full `ISOLATION` clean consumes 4 of `DISINFECTANT`, 2 of `PPE_PACK`, and 6 of `CLOTH`; a full `TERMINAL` clean consumes 6 of `DISINFECTANT`, 3 of `PPE_PACK`, 8 of `CLOTH`, and 1 of `SEALANT`. When the request is in a reclean cycle — that is, it is being started with a `reclean_count` greater than zero — every line is halved, each line rounded half-up to a whole unit, so a `TERMINAL` reclean reserves 3, 2, 4, and 1 across its four lines. Availability is checked per line: the item's `on_hand_quantity` minus its `reserved_quantity` must be at least the line quantity. Every line must pass; the first failing line rejects the start with `ERR_INSUFFICIENT_SUPPLY`, naming the item. On success the request stamps `started_at` with the current clock, stamps `first_started_at` as well when it has never been set — recleans never overwrite the first start — sets `supply_reserved` true, raises each bill-of-materials item's `reserved_quantity` by its line quantity, and moves the bed `VACANT_DIRTY → CLEAN_IN_PROGRESS`.

**Completing** a clean requires `IN_PROGRESS` (`ERR_REQUEST_NOT_IN_PROGRESS` otherwise, terminal requests again answering `ERR_REQUEST_ALREADY_TERMINAL`) and moves the request to `PENDING_QA`. Completion stamps `completed_at`, copies the acting technician into `last_completed_by_staff_id` — the field that later drives both segregation of duties and the reclean second-set-of-hands rule — and settles the supply reservation: `supply_reserved` flips to false, and for each bill-of-materials line the item's `reserved_quantity` drops by the line quantity while its `on_hand_quantity` drops by the same amount, each drop materialized as a `CONSUME` ledger entry carrying the request's `clean_request_id`; `stock_status` then recomputes per item. The assignment dissolves — `assigned_staff_id` clears and the technician's active count drops by one — and the bed moves `CLEAN_IN_PROGRESS → AWAITING_VERIFICATION`.

Cancelling a started clean is the abort path. A dispatcher cancelling an `IN_PROGRESS` request releases the reservation without consuming anything: `supply_reserved` flips to false and each reserved quantity drops, but `on_hand_quantity` is untouched and no ledger entries are written, since nothing was used. The technician's assignment clears, the active count drops, and the bed falls back `CLEAN_IN_PROGRESS → VACANT_DIRTY`.

### 3.6. Quality Verification and the Reclean Loop

No clean becomes ready on the technician's word alone. A `QualityAuditor` submits a **quality audit** against a request in `PENDING_QA` (`ERR_REQUEST_NOT_PENDING_QA` otherwise), providing the `clean_request_id`, an `audit_method` of `ATP_SWAB` or `FLUORESCENT_MARKER`, and the method's measurement. The two methods carry strict field discipline: an `ATP_SWAB` audit must carry an integer `rlu_reading` and must not carry `marker_fraction_removed`, while a `FLUORESCENT_MARKER` audit must carry `marker_fraction_removed` — a fraction between 0 and 1 inclusive — and must not carry `rlu_reading`. Any mismatch between method and fields is rejected with `ERR_AUDIT_METHOD_FIELD_MISMATCH`. Segregation of duties is enforced at the gate: the audit's `auditor_id` is taken from the acting auditor's `X-User-ID`, and if it equals the request's `last_completed_by_staff_id` the submission is rejected with `ERR_AUDITOR_IS_CLEANER` — no one may verify their own work.

The audit's `result` is computed, never supplied. The threshold comes from the standard row for the request's *current* `clean_type`, so a request upgraded to `TERMINAL` by an outbreak is audited against the `TERMINAL` threshold. For `ATP_SWAB`, `threshold_used` is that row's `atp_rlu_threshold`, and the result is `PASS` exactly when the `rlu_reading` is less than or equal to it — a reading precisely at the threshold passes. For `FLUORESCENT_MARKER`, `threshold_used` is 0.85, and the result is `PASS` exactly when the `marker_fraction_removed` is greater than or equal to 0.85 — again, exactly at the boundary passes. Note the two methods compare in opposite directions. The audit record keeps the `threshold_used` alongside the result, starts life with `audit_status` `SUBMITTED`, and captures the unit's current `ops_run_index` into `created_ops_run_index`; audit history can be listed filtered by `clean_request_id`, `auditor_id`, or `result`.

A **PASS** cascade closes the loop. The request moves `PENDING_QA → VERIFIED` and stamps `verified_at`. The completing technician is credited: `completed_clean_count` rises by one, `verified_credit_total` absorbs the per-clean credit described below, and both `productivity_score` and `stat_eligible` recompute. The bed moves `AWAITING_VERIFICATION → READY`, stamps `last_ready_at`, computes both turnaround metrics, and triggers the placement matching of §3.7.

A **FAIL** cascade opens a reclean loop instead. The request moves `PENDING_QA → NEEDS_RECLEAN` and its `reclean_count` rises by one; the completing technician's `qa_fail_count` rises by one with productivity and `stat_eligible` recomputed; and the bed falls back `AWAITING_VERIFICATION → VACANT_DIRTY`. The same request — not a new one — is then reassigned through the dispatcher path of §3.4 under the second-set-of-hands rule, and its next start moves the bed to `CLEAN_IN_PROGRESS` again, at the halved consumption of §3.5.

Because audits are evidence, a FAIL can be retracted only through a narrow compensating action. An `InfectionPreventionist` may **void** an audit while three conditions all hold: the audit is still `SUBMITTED` (`ERR_AUDIT_NOT_SUBMITTED` otherwise), its result is `FAIL` and the linked request is still sitting in `NEEDS_RECLEAN` (`ERR_AUDIT_NOT_VOIDABLE` otherwise), and the audit's `created_ops_run_index` still equals the unit's current `ops_run_index` — meaning no ops-run has closed since submission (`ERR_AUDIT_VOID_WINDOW_CLOSED` once one has). A void runs the compensation cascade: the request moves `NEEDS_RECLEAN → PENDING_QA`, the bed moves `VACANT_DIRTY → AWAITING_VERIFICATION`, and the completing technician's `qa_fail_count` drops by one with productivity recomputed. The audit itself becomes `VOIDED`, terminal.

Productivity accounting rewards verified throughput against standard time. For each `VERIFIED` request a technician completed, the actual minutes are the whole minutes — rounded down — from `started_at` to `completed_at`, never less than one. The efficiency factor is the request's pinned `sla_target_minutes` divided by those actual minutes, clamped so it never falls below 0.50 and never exceeds 1.50. The per-clean credit is the base credit for the request's `clean_type` — 1.00 for `ROUTINE`, 1.50 for `ISOLATION`, 2.00 for `TERMINAL` — multiplied by the clamped factor, and it is rounded to two decimal places half-up **per clean, before summation**; `verified_credit_total` is the sum of those rounded credits. Rounding order is observable: three cleans at a raw credit of 1.125 each total 3.39 (three times 1.13), not the 3.38 that summing raw and rounding once would give. The `productivity_score` itself is 0.00 while `shift_seconds_today` is zero; otherwise it is one hundred times `verified_credit_total` divided by the shift hours — `shift_seconds_today` divided by 3600 — minus a penalty of 5.00 points per `qa_fail_count`, the whole thing rounded once to two decimal places half-up and never allowed below zero. Finally, `stat_eligible` holds when the technician has no verified cleans yet (`completed_clean_count` is zero) or when `productivity_score` has reached at least 80.00 — the gate that §3.4's STAT assignments consult.

### 3.7. Bed Readiness, Placement Matching, and Notifications

The moment a bed enters `READY`, the system tries to put it to work. The **bed-ready match selector** considers the `OPEN` placement demands in the bed's unit whose `required_bed_kind` equals the bed's `bed_kind`, ranks them by `priority_score` descending with `created_at` ascending as the tie-break, and matches the top demand: the demand becomes `MATCHED` with `matched_bed_id` pointing at the bed, and a **bed-ready notification** is born in `SENT` status, linking the `bed_id` and `demand_id` and stamping `sent_at` with the readiness clock. When no demand is eligible the bed simply stays `READY`, unmatched — an empty pool is not an error and creates no notification. Notifications can be listed filtered by `bed_id`, `demand_id`, or `status`.

Two turnaround metrics are computed on the same readiness event. `tat_total_minutes` is the guest-flow figure: whole minutes, rounded down, from the bed's `last_discharge_at` — or from the bed's own `created_at` when it was never discharged — to `last_ready_at`. `tat_clean_minutes` is the EVS execution figure: whole minutes, rounded down, from the verifying request's `first_started_at` to its `verified_at`. Both derive from the same lifecycle events, so they must differ numerically whenever the request waited in queue before starting.

From `SENT`, a notification has three exits. A coordinator may **acknowledge** it — only a `SENT` notification can be acknowledged (`ERR_NOTIFICATION_NOT_SENT` otherwise) — stamping `acknowledged_at`. It is **retracted** when its bed leaves `READY` without an admit or when its matched demand is cancelled: on retraction the matched demand returns to `OPEN` with `matched_bed_id` cleared — except on the demand-cancel path, where the demand goes `CANCELLED` instead. And it **expires** at an ops-run once the clock has moved strictly more than 60 minutes past `sent_at`; at exact equality it stays `SENT`. Expiry moves the matched demand back to `OPEN` with `matched_bed_id` cleared, and the bed remains `READY`, eligible for the same ops-run's rematch pass (§3.9). The match-unmatch loop is indefinite: a demand can cycle `OPEN → MATCHED → OPEN` any number of times before it fulfills, expires, or is cancelled.

**Admission** closes the loop from the bed side. Admitting requires the bed to be `READY` (`ERR_BED_NOT_READY` otherwise) and moves it `READY → OCCUPIED`. When a demand is `MATCHED` to the bed, admission fulfills it — the demand becomes `FULFILLED` with `fulfilled_at` stamped — and its notification, if still `SENT`, is auto-acknowledged with `acknowledged_at` stamped.

A ready bed can also be **marked soiled** before the patient ever arrives. Marking soiled likewise requires `READY` (`ERR_BED_NOT_READY`) and moves the bed `READY → VACANT_DIRTY`, then fires the depth-three retraction cascade: any notification for the bed in `SENT` or `ACKNOWLEDGED` status becomes `RETRACTED`; the demand it served, if `MATCHED`, returns to `OPEN` with `matched_bed_id` cleared and its `priority_score` recomputed; and a fresh `ROUTINE` clean request is auto-created for the bed, pinning its standard at creation per §3.3. The `ROUTINE` standard's existence is verified before the `READY` state check runs, so a mark-soiled attempt on a non-`READY` bed still answers `ERR_STANDARD_NOT_FOUND` when no `ROUTINE` standard row exists.

### 3.8. Outbreak Response and Enhanced Cleaning

Infection events are managed as **outbreak events**. An `InfectionPreventionist` declares one with the affected `unit_id`, a `pathogen_class` of `C_DIFF`, `MRSA`, `NOROVIRUS`, or `OTHER`, and an optional free-text `declared_reason`; a new event is `DECLARED` and can be listed filtered by `unit_id` or `status`. A declared event that should never have been filed can be **cancelled** while still `DECLARED`; any other state rejects both cancellation and activation with `ERR_OUTBREAK_INVALID_STATE`.

**Activation** is the operation with teeth. It requires `DECLARED` status and requires that no other event for the same unit is already `ACTIVE` (`ERR_OUTBREAK_ALREADY_ACTIVE`). Activation stamps `activated_at`, flips the unit's `outbreak_posture` to `OUTBREAK` — a mutation that increments the unit's `version` — and then upgrades in-flight work: every clean request in the unit that is still `QUEUED` or `ASSIGNED`, sits on an `ISOLATION` bed, and is not already `TERMINAL` has its `clean_type` rewritten to `TERMINAL` and its standard re-pinned with the outbreak posture applied — `pinned_base_minutes` and `pinned_outbreak_multiplier_bps` are recaptured from the `TERMINAL` standard row and `pinned_with_outbreak` becomes true — with `sla_target_minutes` and `sla_due_at` recomputed from the new pin (the due time is again `created_at` plus the new target), `planned_end_at` recomputed for the assigned ones, and each touched request's `version` incremented. Requests already underway — started, pending QA, or awaiting reclean — are deliberately not touched; neither are requests on non-isolation beds.

**Lifting** an `ACTIVE` outbreak stamps `lifted_at`, moves the event to `LIFTED`, and recomputes the unit's posture: `OUTBREAK` if another event for the unit is still `ACTIVE`, `NORMAL` otherwise, again incrementing the unit's `version`. Lifting is explicitly non-retroactive — in-flight requests keep their pinned standards and due times exactly as computed, and only future creations and future pins observe the returned `NORMAL` posture. Version-pinning, not the calendar, decides which protocol a request obeys.

### 3.9. Maintenance Windows, Ops-Runs, and Turnaround Analytics

Beds leave service through **maintenance windows**, created by an administrator with a `bed_id`, a `start_at`, an `end_at` that must be strictly later (`ERR_INVALID_WINDOW` otherwise), and an optional free-text `reason`. Windows interpret their interval as half-open — the bed is out from `start_at` up to but not including `end_at`, so two windows that merely touch at a boundary instant do not overlap — and a new window starts `SCHEDULED`. Windows can be listed filtered by `bed_id` or `status`, and a scheduled window can be **cancelled**; activation, closure, and cancellation each require the matching state — `SCHEDULED` for activate and cancel, `ACTIVE` for close — with violations answered `ERR_WINDOW_INVALID_STATE`.

Maintenance is capped in aggregate so a unit never goes dark. The cap for a unit is one fifth of its bed count rounded down, but never less than one. Both at creation and again at activation, the system checks the new window against that cap by sampling a specific set of instants: the new window's own `start_at`, plus the `start_at` of every existing `SCHEDULED` or `ACTIVE` window that overlaps it. If at any sampled instant the number of overlapping existing windows plus the new window would exceed the cap, the operation is rejected with `ERR_CAPACITY_EXCEEDED`. Sampling start instants suffices because overlap counts change only at interval endpoints, and any endpoint that matters is another window's start. Note the deliberate contrast with §3.4's staff rule: maintenance allows pairwise overlap up to the aggregate cap, while technician windows tolerate zero overlap and demand a ten-minute buffer.

**Activating** a window takes the bed out of service. Beyond state, activation requires the bed to be `VACANT_DIRTY` or `READY` (`ERR_BED_NOT_AVAILABLE_FOR_MAINTENANCE` otherwise) and requires no open clean request on the bed — any request in `QUEUED`, `ASSIGNED`, `IN_PROGRESS`, `PENDING_QA`, or `NEEDS_RECLEAN` rejects the activation with `ERR_OPEN_REQUEST_EXISTS`. The bed moves to `OUT_OF_SERVICE`; when it had been `READY` and matched, the same retraction cascade as mark-soiled fires — notification `RETRACTED`, demand back to `OPEN` — minus the fresh clean request. **Closing** an active window returns the bed `OUT_OF_SERVICE → VACANT_DIRTY` and auto-creates a `ROUTINE` clean request for it, since maintenance dirties the room.

The **ops-run** is the unit's periodic checkpoint, executed by an administrator and returning the snapshot it creates. A single run performs four passes in order. First, the SLA breach sweep: every request in the unit sitting in `QUEUED`, `ASSIGNED`, or `IN_PROGRESS` whose `sla_due_at` is strictly before the current clock has `sla_breached` set true — idempotently, and never at exact equality — repricing it through the breach boost while leaving its demand-derived tier alone. Second, demand expiry: `OPEN` demands whose `needed_by` is strictly before the clock move to `EXPIRED`. Third, notification expiry: `SENT` notifications more than 60 minutes old move to `EXPIRED`, reopening their demands per §3.7. Fourth, a rematch pass: every `READY` bed holding no `SENT` or `ACKNOWLEDGED` notification re-runs the bed-ready match selector.

Each run then writes a **turnaround snapshot** for the window it just closed. The window runs from the previous snapshot's `window_end` — or from the unit's `created_at` on the very first run — inclusive, up to the run's clock time, exclusive; the snapshot records those bounds as `window_start` and `window_end`, along with the unit's `ops_run_index` value *before* this run incremented it. Over the set of the unit's requests whose `verified_at` falls inside the window, the snapshot records `verified_count`, the `sla_breach_count` of set members whose `verified_at` came after their `sla_due_at`, and four percentile fields: `tat_total_p50_minutes`, `tat_total_p90_minutes`, `tat_clean_p50_minutes`, and `tat_clean_p90_minutes`. Percentiles use the nearest-rank method on the ascending-sorted series — the value at position ceiling of p hundredths times the set size, counting from one — with no interpolation; when the window's set is empty all four percentile fields are null and both counts are zero. Completing the run increments the unit's `ops_run_index` by one (and with it the unit's `version`), which is also what closes the audit-void window of §3.6 for anything submitted during the epoch that just ended. Snapshots are reachable per unit and individually by `snapshot_id`.

## 4. Endpoint Definitions

Operations that create a new resource — a unit, bed, maintenance window, clean request, staff member, quality audit, supply item, outbreak event, placement demand, clean standard, or an ops-run's snapshot — return `201 Created`. Operations that modify an existing resource, including all state transitions, clock operations, and the standard-superseding PUT, return `200 OK`. All endpoints are mounted under the paths below; list endpoints additionally accept the `limit` and `offset` query parameters of §2.3 together with any resource-specific filters described in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock | EVSAdministrator |
| POST | `/evs/units` | Create a hospital unit | EVSAdministrator |
| GET | `/evs/units` | List units | Any |
| GET | `/evs/units/{unit_id}` | Get a unit | Any |
| POST | `/evs/units/{unit_id}/ops-runs` | Run the unit's ops checkpoint: SLA breach sweep, demand and notification expiry, rematch pass, snapshot creation | EVSAdministrator |
| GET | `/evs/units/{unit_id}/turnaround-snapshots` | List a unit's turnaround snapshots | Any |
| GET | `/evs/turnaround-snapshots/{snapshot_id}` | Get a snapshot | Any |
| POST | `/evs/beds` | Register a bed | EVSAdministrator |
| GET | `/evs/beds` | List beds (filterable) | Any |
| GET | `/evs/beds/{bed_id}` | Get a bed | Any |
| POST | `/evs/beds/{bed_id}/discharge` | Discharge notification: an OCCUPIED bed becomes VACANT_DIRTY and a clean request is auto-created | BedPlacementCoordinator |
| POST | `/evs/beds/{bed_id}/admit` | Admit a patient to a READY bed | BedPlacementCoordinator |
| POST | `/evs/beds/{bed_id}/mark-soiled` | Retract readiness of a soiled READY bed, re-open its matched demand, and queue a fresh ROUTINE clean | BedPlacementCoordinator |
| POST | `/evs/maintenance-windows` | Schedule a maintenance window for a bed (aggregate capacity cap applies) | EVSAdministrator |
| GET | `/evs/maintenance-windows` | List maintenance windows (filterable) | Any |
| GET | `/evs/maintenance-windows/{window_id}` | Get a maintenance window | Any |
| POST | `/evs/maintenance-windows/{window_id}/activate` | Activate a scheduled window: the bed goes OUT_OF_SERVICE | EVSAdministrator |
| POST | `/evs/maintenance-windows/{window_id}/close` | Close an active window: the bed returns to VACANT_DIRTY and a ROUTINE clean is auto-created | EVSAdministrator |
| POST | `/evs/maintenance-windows/{window_id}/cancel` | Cancel a scheduled window | EVSAdministrator |
| POST | `/evs/clean-requests` | Manually create a clean request for a VACANT_DIRTY bed | EVSDispatcher |
| GET | `/evs/clean-requests` | List clean requests (filterable) | Any |
| GET | `/evs/clean-requests/{request_id}` | Get a clean request | Any |
| POST | `/evs/clean-requests/{request_id}/assign` | Assign a QUEUED or NEEDS_RECLEAN request to a staff member | EVSDispatcher |
| POST | `/evs/clean-requests/{request_id}/reassign` | Reassign an ASSIGNED request to a different staff member (OCC-guarded) | EVSDispatcher |
| POST | `/evs/clean-requests/{request_id}/unassign` | Return an ASSIGNED request to the queue | EVSDispatcher |
| POST | `/evs/clean-requests/{request_id}/start` | Assigned technician starts cleaning (reserves chemicals, bed to CLEAN_IN_PROGRESS) | EVSTechnician |
| POST | `/evs/clean-requests/{request_id}/complete` | Assigned technician completes cleaning (consumes chemicals, bed to AWAITING_VERIFICATION) | EVSTechnician |
| POST | `/evs/clean-requests/{request_id}/cancel` | Cancel a QUEUED, ASSIGNED, or IN_PROGRESS request (IN_PROGRESS releases the reservation without consuming) | EVSDispatcher |
| POST | `/evs/clean-requests/pull` | Pull-based dispatch: assigns the highest-ranked eligible QUEUED request to the pulling technician | EVSTechnician |
| POST | `/evs/staff` | Register a staff member | EVSAdministrator |
| GET | `/evs/staff` | List staff (filterable) | Any |
| GET | `/evs/staff/{staff_id}` | Get a staff member | Any |
| GET | `/evs/staff/{staff_id}/productivity` | Computed productivity breakdown for a staff member | Any |
| POST | `/evs/staff/{staff_id}/clock-in` | Clock in (self only) | EVSTechnician, QualityAuditor |
| POST | `/evs/staff/{staff_id}/clock-out` | Clock out (self only; blocked while cleans are assigned or in progress) | EVSTechnician, QualityAuditor |
| POST | `/evs/staff/{staff_id}/break-start` | Start a break (self only; blocked while a clean is IN_PROGRESS) | EVSTechnician, QualityAuditor |
| POST | `/evs/staff/{staff_id}/break-end` | End a break (self only) | EVSTechnician, QualityAuditor |
| POST | `/evs/quality-audits` | Submit a quality audit (ATP swab or fluorescent marker) for a PENDING_QA request | QualityAuditor |
| GET | `/evs/quality-audits` | List quality audits (filterable) | Any |
| GET | `/evs/quality-audits/{audit_id}` | Get a quality audit | Any |
| POST | `/evs/quality-audits/{audit_id}/void` | Void a FAIL audit within its ops-run window (compensating action) | InfectionPreventionist |
| POST | `/evs/supply-items` | Register a supply item with opening stock | EVSAdministrator |
| GET | `/evs/supply-items` | List supply items | Any |
| GET | `/evs/supply-items/{item_id}` | Get a supply item | Any |
| POST | `/evs/supply-items/{item_id}/restock` | Restock a supply item | EVSAdministrator |
| POST | `/evs/supply-items/{item_id}/recount` | Physical recount via a RECOUNT_ADJUSTMENT ledger entry (OCC-guarded) | EVSAdministrator |
| GET | `/evs/supply-ledger-entries` | List supply ledger entries (filterable) | Any |
| GET | `/evs/supply-ledger-entries/{entry_id}` | Get a ledger entry | Any |
| POST | `/evs/outbreak-events` | Declare an outbreak event for a unit | InfectionPreventionist |
| GET | `/evs/outbreak-events` | List outbreak events (filterable) | Any |
| GET | `/evs/outbreak-events/{event_id}` | Get an outbreak event | Any |
| POST | `/evs/outbreak-events/{event_id}/activate` | Activate an outbreak: unit posture escalates and in-flight isolation-bed cleans upgrade to TERMINAL | InfectionPreventionist |
| POST | `/evs/outbreak-events/{event_id}/lift` | Lift an active outbreak: posture recomputed; in-flight pins unchanged | InfectionPreventionist |
| POST | `/evs/outbreak-events/{event_id}/cancel` | Cancel a declared (not yet activated) outbreak | InfectionPreventionist |
| GET | `/evs/bed-ready-notifications` | List bed-ready notifications (filterable) | Any |
| GET | `/evs/bed-ready-notifications/{notification_id}` | Get a bed-ready notification | Any |
| POST | `/evs/bed-ready-notifications/{notification_id}/acknowledge` | Acknowledge a SENT notification | BedPlacementCoordinator |
| POST | `/evs/placement-demands` | Create a placement demand (bed request from admission/transfer) | BedPlacementCoordinator |
| GET | `/evs/placement-demands` | List placement demands (filterable) | Any |
| GET | `/evs/placement-demands/{demand_id}` | Get a placement demand | Any |
| POST | `/evs/placement-demands/{demand_id}/cancel` | Cancel an OPEN or MATCHED demand (a MATCHED cancel retracts the notification) | BedPlacementCoordinator |
| POST | `/evs/placement-demands/{demand_id}/regrade` | Change a demand's urgency tier (recomputes its score and matching-kind queue priorities) | BedPlacementCoordinator |
| POST | `/evs/clean-standards` | Create the standard row for a clean type (one per type) | EVSAdministrator |
| GET | `/evs/clean-standards` | List clean standards | Any |
| GET | `/evs/clean-standards/{clean_type}` | Get the standard for a clean type | Any |
| PUT | `/evs/clean-standards/{clean_type}` | Update a clean standard (OCC-guarded; in-flight requests keep their pinned values) | EVSAdministrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 400 Bad Request |
| `ERR_AUDIT_METHOD_FIELD_MISMATCH` | 400 Bad Request |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_ROLE_CAPABILITY_MISMATCH` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_TECHNICIAN` | 403 Forbidden |
| `ERR_STAFF_IDENTITY_MISMATCH` | 403 Forbidden |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_BED_NOT_FOUND` | 404 Not Found |
| `ERR_CLEAN_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_PLACEMENT_DEMAND_NOT_FOUND` | 404 Not Found |
| `ERR_STAFF_NOT_FOUND` | 404 Not Found |
| `ERR_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLY_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_OUTBREAK_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_STANDARD_NOT_FOUND` | 404 Not Found |
| `ERR_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_SNAPSHOT_NOT_FOUND` | 404 Not Found |
| `ERR_REQUEST_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_REQUEST_NOT_QUEUED` | 409 Conflict |
| `ERR_REQUEST_NOT_ASSIGNED` | 409 Conflict |
| `ERR_REQUEST_NOT_IN_PROGRESS` | 409 Conflict |
| `ERR_REQUEST_NOT_PENDING_QA` | 409 Conflict |
| `ERR_BED_NOT_OCCUPIED` | 409 Conflict |
| `ERR_BED_NOT_READY` | 409 Conflict |
| `ERR_BED_NOT_DIRTY` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE_FOR_MAINTENANCE` | 409 Conflict |
| `ERR_STAFF_NOT_ON_SHIFT` | 409 Conflict |
| `ERR_STAFF_NOT_ON_BREAK` | 409 Conflict |
| `ERR_STAFF_ALREADY_ON_SHIFT` | 409 Conflict |
| `ERR_STAFF_HAS_ACTIVE_CLEANS` | 409 Conflict |
| `ERR_DEMAND_NOT_OPEN` | 409 Conflict |
| `ERR_NOTIFICATION_NOT_SENT` | 409 Conflict |
| `ERR_OUTBREAK_INVALID_STATE` | 409 Conflict |
| `ERR_WINDOW_INVALID_STATE` | 409 Conflict |
| `ERR_AUDIT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_AUDIT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_AUDIT_VOID_WINDOW_CLOSED` | 409 Conflict |
| `ERR_STAFF_CERTIFICATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STAFF_NOT_STAT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_RECLEAN_SAME_TECHNICIAN` | 422 Unprocessable Entity |
| `ERR_AUDITOR_IS_CLEANER` | 422 Unprocessable Entity |
| `ERR_STAFF_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_OPEN_REQUEST_EXISTS` | 409 Conflict |
| `ERR_INSUFFICIENT_SUPPLY` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STANDARD` | 409 Conflict |
| `ERR_OUTBREAK_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_QUEUE_EMPTY` | 409 Conflict |
| `ERR_STALE_REQUEST_VERSION` | 412 Precondition Failed |
| `ERR_STALE_SUPPLY_VERSION` | 412 Precondition Failed |
| `ERR_STALE_STANDARD_VERSION` | 412 Precondition Failed |

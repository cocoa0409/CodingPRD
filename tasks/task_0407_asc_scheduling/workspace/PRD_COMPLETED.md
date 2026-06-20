# ASC Scheduling API — Product Requirements Document

## 1. Introduction

An ambulatory surgery center (ASC) runs an unforgiving choreography: a finite set of operating rooms must absorb dozens of cases per day, each case must clear a pre-operative gauntlet before it is allowed near an incision, and every minute of room time is both a clinical resource and a billable quantity. This document specifies the API for an ASC scheduling and settlement platform that coordinates surgeon block time, OR and recovery-bay capacity, anesthesia coverage, implant and supply reservation, pre-op clearance, and the reconciliation of estimated case cost against the cost actually incurred — culminating in a payment amount derived from the CMS ASC payment list.

The platform serves four operational roles whose responsibilities do not overlap: a scheduling function that owns the calendar (days, blocks, bookings, cancellations), a pre-op nursing function that owns clearance and the History & Physical (H&P) window, an OR-management function that owns physical resources and the intra-operative progression of a case from incision through recovery to completion, and a billing function that owns the CMS procedure catalog and the cost-and-payment ledger. Two themes recur throughout the rules that follow. First, **time is modeled deterministically**: the system never reads the wall clock — every staleness and window calculation reads a facility-scoped logical clock that advances only when explicitly told to. Second, **capacity is conserved**: block minutes, supply reservations, and day utilization are accounting quantities that must balance after every booking, cancellation, completion, and cascade. A reader implementing this API should treat the conservation invariants as load-bearing, not advisory.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque string identifying the individual user, and `X-User-Role`, naming the user's role. If either header is missing, or if `X-User-Role` does not name a role the system recognizes, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes exactly four roles, spelled `Scheduler`, `PreOpNurse`, `ORManager`, and `BillingAnalyst`. A `Scheduler` owns facilities, surgeons, patients, surgical days, surgeon blocks, the booking and rescheduling and cancellation of cases, and the locking and reopening of days. A `PreOpNurse` owns the clearance lifecycle — recording clearance checks, resetting clearance, and clearing a case — and the H&P window. An `ORManager` owns operating rooms, recovery bays, anesthesiologists, supply items, the intra-operative progression of a case (start, move-to-recovery, complete), implant settlement, and the closing of a day. A `BillingAnalyst` owns the CMS procedure catalog and the cost-and-payment reporting surfaces, and is read-only on every operational entity. All four roles may call every list and read endpoint. Creating a patient is shared by `Scheduler` and `PreOpNurse`; advancing the facility clock is shared by `Scheduler` and `ORManager`; the anesthesia coverage-load report is shared by `Scheduler`, `ORManager`, and `BillingAnalyst`.

All four roles use an **opaque** identity model. For each of `Scheduler`, `PreOpNurse`, `ORManager`, and `BillingAnalyst`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any entity's `id`. The server may, however, record it — for example, when a `PreOpNurse` records a clearance check, the acting user's `X-User-ID` is written to the check's `recorded_by` field. No ownership check anywhere in the system compares a resource's foreign key to `X-User-ID`; access is governed entirely by role.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; a value outside that range is a malformed request. The `offset` parameter defaults to 0 and counts records to skip from the start of the result set. Every list response is sorted by `created_at` in ascending order — that is, the oldest record first — unless a specific workflow narrative states a different ordering for an internal computation. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the count of records matching the filter before pagination is applied and `has_more` is true exactly when records remain beyond the current page.

### 2.4. Common Resource Properties and the Versioned Mutation Model

Every resource is identified by a server-minted `id`, a UUID carrying no type prefix. Most resources additionally carry three lifecycle fields. The `created_at` timestamp records when the resource was first persisted, and `updated_at` records the moment of its most recent mutation; both are ISO 8601 UTC timestamps with three fractional digits. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every mutation of the resource. These four fields — `id`, `created_at`, `updated_at`, `version` — are present on facilities, operating rooms, recovery bays, anesthesiologists, surgeons, procedures, supply items, surgical days, surgeon blocks, surgical cases, patients, and case implants.

There is one deliberate exception. A `ClearanceCheck` is an **append-only event record**, not a mutable resource: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version`. Clearance checks are never edited or deleted after they are written; the clearance lifecycle advances by appending new checks, not by mutating old ones.

### 2.5. Nested Identifier Resolution and Foreign-Key Existence

Although most resources are addressed as flat collections, several action endpoints embed one or more identifiers in the URL path (for example, an implant addressed beneath its case). Path identifiers are resolved left to right, and the first one that does not resolve to an existing resource produces that resource's not-found error — `ERR_FACILITY_NOT_FOUND`, `ERR_OPERATING_ROOM_NOT_FOUND`, `ERR_RECOVERY_BAY_NOT_FOUND`, `ERR_ANESTHESIOLOGIST_NOT_FOUND`, `ERR_SURGEON_NOT_FOUND`, `ERR_PROCEDURE_NOT_FOUND`, `ERR_SUPPLY_ITEM_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_SURGICAL_DAY_NOT_FOUND`, `ERR_SURGEON_BLOCK_NOT_FOUND`, `ERR_SURGICAL_CASE_NOT_FOUND`, `ERR_CASE_IMPLANT_NOT_FOUND`, or `ERR_CLEARANCE_CHECK_NOT_FOUND` — each at HTTP 404. After path identifiers resolve, any foreign-key identifier supplied in a request body must reference a resource that exists and belongs to the same facility; a dangling body reference produces the same family of not-found errors at HTTP 404.

Relationships are carried as foreign-key fields on the body and resolved through filtered list endpoints rather than nested URLs. Every operational entity carries a `facility_id` tying it to its facility. An operating room, recovery bay, anesthesiologist, surgeon, procedure, supply item, surgical day, surgeon block, surgical case, and patient each carries `facility_id`. A `SurgeonBlock` additionally carries `surgical_day_id`, `surgeon_id`, and `operating_room_id`. A `SurgicalCase` carries `surgical_day_id`, `surgeon_block_id`, `patient_id`, `procedure_id`, `operating_room_id`, `anesthesiologist_id`, and `recovery_bay_id`. A `CaseImplant` carries `surgical_case_id` and `supply_item_id`. A `ClearanceCheck` carries `surgical_case_id`.

### 2.6. Validation Order and the Precedence of Checks

When a single request could fail several ways, the checks are evaluated in a fixed precedence so that the returned error is deterministic. The order is: first, that `X-User-ID` and `X-User-Role` are present and name a known role (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, that the role is permitted for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); third, that every identifier in the URL path resolves (the not-found family at 404); fourth, that every foreign-key identifier in the body resolves within the same facility (the not-found family at 404); fifth, that the body is well-formed — required fields present and correctly typed, enum values within their permitted set, minute quantities positive, an NPI exactly 10 digits, a CPT code exactly 5 characters (`ERR_INVALID_REQUEST`, HTTP 400); sixth, that facility-scoped uniqueness holds (`ERR_DUPLICATE_KEY`, HTTP 409); seventh, the optimistic-concurrency version check on any endpoint that requires it (`ERR_STALE_BLOCK_VERSION`, HTTP 412); and eighth, the state-machine guard that the target resource is in a state from which the requested transition is legal (the state-conflict family at HTTP 409). Only after all eight tiers pass does the remaining domain logic — temporal conflicts, capacity, safety, fiscal rules, clearance preconditions — execute. The optimistic-concurrency check is positioned deliberately: it runs after existence has been confirmed but before any state or business rule below it, so a stale version is reported before, for example, a capacity rejection.

### 2.7. The Deterministic Facility Clock

Every window and staleness computation in the system reads a facility-scoped logical clock rather than the host's wall clock. Each `Facility` carries a `current_utc` instant, initialized at creation to `1970-01-01T00:00:00.000Z`. This clock advances only when a `Scheduler` or `ORManager` explicitly advances it to a supplied absolute UTC instant, expressed as the `to_iso8601` field. The supplied instant must be greater than or equal to the clock's prior value — an attempt to move the clock backward is rejected as `ERR_INVALID_REQUEST`. Any rule that speaks of "now," of an H&P being stale, or of a block becoming releasable a certain number of hours before its service date, is measured against `current_utc`, never against real elapsed time.

### 2.8. Optimistic Concurrency on Block Booking

Booking a case consumes minutes from a finite pool on a parent `SurgeonBlock`, and the platform protects that pool with optimistic concurrency control rather than locking. The book-a-case-into-a-block operation requires a non-optional `expected_block_version` field carrying the `version` of the target `SurgeonBlock` that the client last observed. Before any booking logic runs, the server compares `expected_block_version` to the block's current `version`. If they do not match — because another writer has committed minutes into that same block and thereby advanced its `version` since the client last read it — the booking is rejected with `ERR_STALE_BLOCK_VERSION` (HTTP 412). This prevents a client from booking against a stale view of the block's remaining minutes: the client must re-read the block, observe the new `version` and `committed_minutes`, and retry with the fresh value. No other endpoint takes a version field; only block booking is OCC-guarded.

### 2.9. Monetary Precision and Conservation Invariants

All monetary quantities are integer cents — there are no fractional cents anywhere in the system. Wherever a cost is built from line items (implant lines, for instance), each line is computed and **rounded half-up to a whole cent individually, and only then are the rounded line amounts summed**; the system never sums raw products and rounds once at the end. Utilization and coverage-load percentages are rounded half-up to one decimal place.

Two accounting quantities must remain balanced at all times. The first is **block-minute conservation**: a block's `committed_minutes` always equals the sum of the `scheduled_minutes` of the non-cancelled cases booked into it, so every booking adds the booked case's minutes and every cancellation or cascade-cancel subtracts them. The second is **supply-reservation conservation**: a supply item's `reserved_qty` always equals the sum of `planned_qty` across the case implants that are currently in `RESERVED` status, so reserving adds and releasing or consuming subtracts. These invariants are not recomputed lazily on read; each mutating operation that touches them must leave them balanced.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Facility and Its Resources

A `Scheduler` brings a facility into existence by supplying its `name`, optionally overriding three operational defaults: the `turnover_minutes` cleaning buffer (default 25, and never negative), the `hp_validity_days` H&P validity window (default 30), and the `utilization_target_pct` prime-time utilization target (default 75, on a scale of 0 to 100). At creation the facility's `current_utc` is initialized to the Unix epoch as described above.

Physical resources hang off the facility. An `ORManager` creates an operating room with a `facility_id` and a human `room_label`, and may set its prime-time window: `prime_time_start_min` (default 420, i.e. 07:00 expressed as minutes from midnight) and `prime_time_end_min` (default 960, i.e. 16:00), where the close must be strictly greater than the open. A new room begins with `status` of `AVAILABLE`. Recovery bays are likewise created by an `ORManager` with a `facility_id` and a `bay_label`; each carries a `phase2_capable` flag (default true) indicating whether it can host Phase II recovery, and starts `AVAILABLE`. Both rooms and bays toggle between `AVAILABLE` and `OFFLINE` via a status operation that accepts the desired `status`; an `OFFLINE` room refuses new case assignment and an `OFFLINE` bay refuses new recovery assignment.

Anesthesiologists are created by an `ORManager` with a `facility_id` and `full_name`, a `credential` of `MD`, `DO`, or `CRNA` (default `MD`), and an `active` flag (default true); an inactive anesthesiologist cannot be assigned to new cases. Surgeons are created by a `Scheduler` with a `facility_id`, `full_name`, and a 10-digit `npi`; an `active` flag defaults to true, and a `Scheduler` may later toggle `active`. An inactive surgeon can neither own new blocks nor have cases booked against them. A `BillingAnalyst` owns the procedure catalog: each `Procedure` carries a `facility_id`, a 5-character `cpt_code`, a `description`, a positive `scheduled_minutes` (the planned wheels-in-to-wheels-out duration), a `requires_phase2` flag (default false), an `anesthesia_class` of `LOCAL`, `MAC`, `REGIONAL`, or `GENERAL` (default `MAC`), a `cms_payment_indicator` of `COVERED_ASC`, `DEVICE_INTENSIVE`, `OFFICE_BASED`, or `EXCLUDED`, a non-negative `cms_base_rate_cents`, and a `device_offset_pct` (0 to 100, default 0) that matters only for device-intensive grouping. Patients are created by either a `Scheduler` or a `PreOpNurse` with a `facility_id`, an `mrn`, a `full_name`, and a `date_of_birth`. Within a single facility, the following must each be unique, and a collision is rejected as `ERR_DUPLICATE_KEY`: a surgeon's `npi`, a procedure's `cpt_code`, a patient's `mrn`, a supply item's `sku`, and a surgical day's `service_date`.

### 3.2. Supply and Device Inventory

An `ORManager` registers a supply line as a `SupplyItem` with a `facility_id`, a `sku`, a `description`, a non-negative `unit_cost_cents`, an `is_device` flag (default false) marking it as a billable implantable device, and an opening `on_hand_qty` (default 0). Each item also exposes a computed `reserved_qty`, which begins at 0 and tracks how many units are currently spoken for. The **available** quantity of an item is its `on_hand_qty` minus its `reserved_qty`; `reserved_qty` is precisely the sum of `planned_qty` over every case implant currently in `RESERVED` status. Reserving stock does not reduce `on_hand_qty` — only consuming it at case completion does. An `ORManager` may replenish stock by restocking, which adds a positive `delta_qty` to `on_hand_qty`.

### 3.3. The Surgical Day Posture

Scheduling is organized around a `SurgicalDay`, created by a `Scheduler` with a `facility_id` and a calendar `service_date` in `YYYY-MM-DD` form. A day exposes a computed `booked_minutes` (the sum of `scheduled_minutes` over its non-cancelled cases), a computed `utilization_pct`, and a `posture` that begins `OPEN`. The posture is the gate that sequences the whole day, and it moves only through three explicit transitions driven by a `Scheduler` or `ORManager`.

A `Scheduler` locks a day, advancing posture `OPEN → LOCKED`. Locking requires that the day is currently `OPEN` (otherwise `ERR_DAY_NOT_OPEN`) and that at least one non-cancelled case already exists on the day (otherwise `ERR_DAY_EMPTY`). Once `LOCKED`, ordinary bookings are refused and only add-on cases may be booked, but cases may now begin entering the OR. A `Scheduler` may reverse a lock, advancing posture `LOCKED → OPEN`, provided the day is currently `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED`) and no case on the day has yet reached `IN_OR`, `IN_RECOVERY`, or `COMPLETED` (otherwise `ERR_DAY_HAS_ACTIVE_CASES`). Finally, an `ORManager` closes a day, advancing posture `LOCKED → CLOSED`, which requires the day to be `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED`) and every non-cancelled case on it to have reached `COMPLETED` (otherwise `ERR_DAY_HAS_UNFINISHED_CASES`). Closing freezes `utilization_pct` permanently — no later event recomputes it. A `CLOSED` day is terminal and rejects any further mutation with `ERR_DAY_CLOSED`. The three postures partition behavior cleanly: `OPEN` permits ordinary (non-add-on) bookings and forbids any case from being in the OR or beyond; `LOCKED` permits cases to be started and permits only add-on bookings; `CLOSED` is terminal with frozen utilization and no bookings.

### 3.4. Surgeon Blocks and the Booking Contract

A `Scheduler` opens a `SurgeonBlock` against a day by supplying the `surgical_day_id`, the `surgeon_id` who owns the block, the `operating_room_id` the block occupies, a `start_min` and `end_min` expressed as minutes from midnight (with `end_min` strictly greater than `start_min`), and optionally a `release_threshold_hours` (default 48). The block's `facility_id` is inherited from its day. The interval is half-open: the block covers `[start_min, end_min)`. On creation the block computes its `allocated_minutes` as `end_min` minus `start_min` — the finite pool of minutes cases may consume — sets `committed_minutes` to 0, and enters `status` `HELD`. A block's `release_threshold_hours` records how many hours before the service date an unused block becomes auto-releasable.

A block advances through `HELD → CONFIRMED → RELEASED`, and may also go `HELD → RELEASED` directly. A `Scheduler` confirms a block, advancing `HELD → CONFIRMED`, only when the block is currently `HELD` (otherwise `ERR_BLOCK_NOT_HELD`), the owning surgeon is active (otherwise `ERR_SURGEON_INACTIVE`), and the owning day is not `CLOSED` (otherwise `ERR_DAY_CLOSED`); confirmation increments the block's `version` by 1. Both `HELD` and `CONFIRMED` blocks accept bookings; a `RELEASED` block accepts neither bookings nor confirmation, and an attempt to use a released block is `ERR_BLOCK_RELEASED`.

Booking a case into a block — the central scheduling act — is performed by a `Scheduler` and is the operation guarded by optimistic concurrency. The request carries the `expected_block_version`, a `patient_id`, a `procedure_id`, a `start_min` (the case's wheels-in time), and optionally an `anesthesiologist_id`, a `recovery_bay_id`, and an `is_add_on` flag (default false). A successful booking creates a `SurgicalCase` whose `case_status` is `SCHEDULED` and whose `clearance_status` is `PENDING_CLEARANCE`. The case inherits its `scheduled_minutes` from the chosen procedure, computes `end_min` as `start_min` plus `scheduled_minutes` (again a half-open `[start_min, end_min)` footprint), inherits its `operating_room_id` from the block, and inherits its `surgical_day_id` and `facility_id` accordingly. Booking adds the case's `scheduled_minutes` to the block's `committed_minutes`, recomputes the owning day's `booked_minutes` and `utilization_pct`, computes the case's `estimated_cost_cents`, and increments the block's `version` by 1.

The booking request must clear a sequence of guards, each with its own rejection. After the version check described in §2.8, the system enforces: the chosen procedure's `cms_payment_indicator` must not be `EXCLUDED` (`ERR_PROCEDURE_EXCLUDED`); the block's surgeon must be active and the procedure must belong to the same facility as the block (`ERR_SURGEON_INACTIVE`); for a non-add-on case, the case footprint `[start_min, end_min)` must lie entirely within the block's own `[start_min, end_min)` window (`ERR_CASE_OUTSIDE_BLOCK_WINDOW`); the OR time-conflict rule and the anesthesia time-conflict rule described in §3.5 must hold; if an `anesthesiologist_id` is supplied at booking, the CRNA-general rule of §3.6 must hold; if a `recovery_bay_id` is supplied at booking, the Phase II rule of §3.6 must hold; for a non-add-on case the block's finite minute pool must not be exceeded (§3.7); and the day-posture booking rule must hold (§3.7). A booking against a released block, naturally, is barred because the block cannot accept it.

A `Scheduler` releases a block, advancing it to `RELEASED` from either `HELD` or `CONFIRMED`. Release requires that the block is currently `HELD` or `CONFIRMED` (otherwise `ERR_BLOCK_NOT_RELEASABLE`) and that the owning day is not `CLOSED` (otherwise `ERR_DAY_CLOSED`). Release is also refused if any case in the block has already reached `IN_OR`, `IN_RECOVERY`, or `COMPLETED` (`ERR_BLOCK_HAS_ACTIVE_CASES`) — an in-flight or finished case is never force-cancelled. When release does proceed it triggers a two-level cascade. At the first level, every non-cancelled case in the block whose `case_status` is `SCHEDULED` is force-cancelled to `CANCELLED`, processed in ascending order of `start_min` and then `created_at`. At the second level, each such forced cancellation releases that case's `RESERVED` implants (each moving to `RELEASED` and decrementing its supply item's `reserved_qty` by the implant's `planned_qty`) and subtracts the cancelled case's `scheduled_minutes` from the block's `committed_minutes`, after which the owning day's `booked_minutes` and `utilization_pct` are recomputed. Release increments the block's `version` by 1.

### 3.5. Temporal Adjacency: OR Turnover and Anesthesia Conflicts

Two cases sharing a physical operating room on the same day must not collide, and a mandatory cleaning interval sits between them. When a non-add-on case is booked (or when a case is rescheduled), the system checks the case's footprint `[start_min, end_min)` against every other non-cancelled case in the **same operating room on the same day**. Turnover time is appended after each case, so two cases are compatible only when the later case's `start_min` is at least the earlier case's `end_min` plus the facility's `turnover_minutes`. Adjacency exactly at `end_min` plus `turnover_minutes` is permitted — that boundary is compatible, not a conflict — and anything tighter is rejected with `ERR_OR_TIME_CONFLICT`.

Anesthesia coverage has a separate, stricter-in-overlap but buffer-free rule. A single anesthesiologist cannot be in two places at once, so when a case is booked with an anesthesiologist assigned, or when an anesthesiologist is assigned to a case, the system checks the case footprint against every other non-cancelled case assigned to the **same anesthesiologist on the same day**. No turnover buffer applies here — back-to-back anesthesia coverage is fine — so two such cases conflict precisely when one case starts before the other ends and that other also starts before the first ends; in plain terms, their `[start_min, end_min)` intervals overlap at all. An overlap is rejected with `ERR_ANESTHESIA_TIME_CONFLICT`. A `Scheduler` may move a `SCHEDULED` case to a new `start_min` within its block by rescheduling; rescheduling recomputes the case's `end_min`, re-runs both the OR turnover check and the anesthesia overlap check, and recomputes the owning day's `utilization_pct`.

### 3.6. Anesthesia and Recovery Assignment Safety

An `ORManager` assigns or reassigns the anesthesiologist on a case by supplying an `anesthesiologist_id`, and assigns or reassigns the recovery destination by supplying a `recovery_bay_id`. Assigning an anesthesiologist who is not active is rejected with `ERR_ANESTHESIOLOGIST_INACTIVE`. A clinical credentialing rule applies to both the assign-anesthesia path and the booking path: a `CRNA`-credential anesthesiologist may not solo-cover a case whose procedure carries an `anesthesia_class` of `GENERAL`, and such an assignment is rejected with `ERR_CRNA_CANNOT_COVER_GENERAL`. The anesthesia time-conflict rule of §3.5 also applies whenever an anesthesiologist is assigned.

Recovery assignment carries its own safety gate, applied both at assignment and when supplied during booking: if the case's procedure has `requires_phase2` set, the chosen recovery bay must be `phase2_capable`, and a non-capable bay is rejected with `ERR_RECOVERY_PHASE2_REQUIRED`.

### 3.7. Block-Minute Capacity, Add-Ons, and Day-Posture Gating

A block's minutes are finite. For a non-add-on case, the booking is permitted only when the block's current `committed_minutes` plus the procedure's `scheduled_minutes` does not exceed the block's `allocated_minutes`. The boundary is inclusive: committed-plus-scheduled landing exactly on `allocated_minutes` is allowed, and a single minute beyond it is rejected with `ERR_BLOCK_CAPACITY_EXCEEDED`.

Add-on cases are the controlled exception. An add-on (a booking with `is_add_on` set to true) is permitted only while the day's `posture` is `LOCKED`; an add-on skips the block-minute capacity check entirely, but it pays an add-on cost surcharge described in §3.9. A non-add-on booking, conversely, is rejected whenever the day's `posture` is `LOCKED` or `CLOSED`, with `ERR_DAY_LOCKED`. In short: an `OPEN` day takes ordinary bookings, a `LOCKED` day takes only add-ons, and a `CLOSED` day takes nothing.

### 3.8. Pre-Op Clearance and the H&P Window

A case's clearance is an independent state dimension that evolves separately from its scheduling progression. A newly booked case starts at `clearance_status` `PENDING_CLEARANCE`, and clearance must reach `CLEARED` before the case can ever enter the OR. The clearance lifecycle is owned entirely by the `PreOpNurse`.

A `PreOpNurse` records a clearance check by supplying a `check_type` of `HP_REVIEW`, `LABS`, `ANESTHESIA_ASSESSMENT`, or `CARDIAC_CONSULT`, and an `outcome` of `PASS`, `FAIL`, or `DEFER`. Each recorded check is appended as a `ClearanceCheck` row whose `recorded_by` captures the acting nurse's `X-User-ID`. A check with `outcome` of `FAIL` drives the case clearance `PENDING_CLEARANCE → ON_HOLD`; recording a check requires the clearance to currently be `PENDING_CLEARANCE` (otherwise `ERR_CLEARANCE_NOT_PENDING`). A `DEFER` outcome leaves clearance at `PENDING_CLEARANCE` but acts as an open question: it blocks clearing until a later `PASS` of the same `check_type` supersedes it. When a case is on hold, a `PreOpNurse` reworks it by resetting clearance `ON_HOLD → PENDING_CLEARANCE`, which requires the clearance to be `ON_HOLD` (otherwise `ERR_CLEARANCE_NOT_ON_HOLD`); this is the cyclic rework edge, and a failed check can be re-worked and re-submitted as many times as needed.

Clearing a case advances `PENDING_CLEARANCE → CLEARED` and is the most heavily guarded clearance step. It requires, first, that the clearance is currently `PENDING_CLEARANCE` (otherwise `ERR_CLEARANCE_NOT_PENDING`). Second, the History & Physical must be on file and fresh: the clear request may carry an `hp_signed_at` timestamp recording when the H&P was signed, and the H&P is fresh when the number of days from `hp_signed_at` to midnight UTC of the case's `service_date` is at most the facility's `hp_validity_days` — the boundary is inclusive, so exactly `hp_validity_days` is still fresh while `hp_validity_days` plus one day is stale, and a stale or missing H&P is rejected with `ERR_HP_WINDOW_EXPIRED`. Third, at least one clearance check of `check_type` `HP_REVIEW` with `outcome` `PASS` must exist (otherwise `ERR_HP_REVIEW_MISSING`). Fourth, there must be no unresolved `DEFER`: if any clearance check on the case carries `outcome` `DEFER` recorded after the most recent clearance reset (or after the case's creation, if there has been no reset) that has not been superseded by a later `PASS` of the same `check_type`, clearing is rejected with `ERR_OPEN_FAILED_CHECK`. These four checks together gate the `CLEARED` state.

### 3.9. Estimated Case Cost at Booking

At booking, and again whenever an implant is attached to or released from the case while its `case_status` is still `SCHEDULED`, the system computes the case's `estimated_cost_cents` from its planned inputs. The estimate is the sum of four parts, all in integer cents. The labor part is the procedure's `scheduled_minutes` multiplied by the OR minute rate of 1,200 cents per scheduled minute (twelve dollars a minute). The anesthesia part is a flat base keyed to the procedure's `anesthesia_class`: zero cents for `LOCAL`, 18,000 cents for `MAC`, 32,000 cents for `REGIONAL`, and 55,000 cents for `GENERAL`. The implant part sums only the case implants currently in `RESERVED` status — released and consumed lines are excluded — and for each such line multiplies the supply item's `unit_cost_cents` by the implant's `planned_qty`, rounds that product half-up to a whole cent, and only then adds the rounded lines together; the estimate uses `planned_qty`, never `consumed_qty`. The fourth part is an add-on surcharge of 40,000 cents (four hundred dollars), added only when the case's `is_add_on` is true and zero otherwise. The estimate is the sum of labor, anesthesia, the per-line-rounded implant total, and the add-on surcharge.

An `ORManager` attaches an implant to a case by supplying a `supply_item_id` and a positive `planned_qty`; the attach is permitted only when the supply item's available quantity (its `on_hand_qty` minus `reserved_qty`) is at least `planned_qty`, and otherwise rejected with `ERR_SUPPLY_INSUFFICIENT`. A successful attach creates a `CaseImplant` in `RESERVED` status, adds `planned_qty` to the supply item's `reserved_qty`, and — if the case is still `SCHEDULED` — recomputes the case's `estimated_cost_cents`. An `ORManager` may record an implant's `consumed_qty` ahead of completion; the recorded value must lie between 0 and the implant's `planned_qty` inclusive, and a value outside that range is `ERR_CONSUMED_QTY_INVALID`. An `ORManager` may also release a still-`RESERVED` implant, advancing it `RESERVED → RELEASED`; release requires the implant to be `RESERVED` (otherwise `ERR_IMPLANT_NOT_RESERVED`), decrements the supply item's `reserved_qty` by `planned_qty`, and recomputes the case's `estimated_cost_cents` if the case is still `SCHEDULED`. (Because a completed case has all of its implants in `CONSUMED` status, the same precondition already prevents releasing an implant on a completed case.)

### 3.10. Cancelling a Scheduled Case

A `Scheduler` cancels a case, advancing `case_status` `SCHEDULED → CANCELLED`. Cancellation is permitted only for a `SCHEDULED` case (otherwise `ERR_CASE_NOT_CANCELLABLE`). A cancellation is a compensating operation that must restore the conservation invariants: it subtracts the cancelled case's `scheduled_minutes` from its block's `committed_minutes`, moves every `RESERVED` implant on the case to `RELEASED` and decrements each affected supply item's `reserved_qty` by that implant's `planned_qty`, and recomputes the owning day's `booked_minutes` and `utilization_pct`. The same compensating effects are exactly what the block-release cascade reuses when it force-cancels scheduled cases.

### 3.11. The Intra-Operative Progression and Settlement

The scheduling dimension of a case advances `SCHEDULED → IN_OR → IN_RECOVERY → COMPLETED`, driven by the `ORManager`. Starting a case into the OR is the convergence point of both state dimensions and the day posture. Starting requires that the case is `SCHEDULED` (otherwise `ERR_CASE_NOT_SCHEDULED`), that the case's `clearance_status` is `CLEARED` (otherwise `ERR_CASE_NOT_CLEARED` — the cross-dimension guard), that the assigned operating room's `status` is `AVAILABLE` (otherwise `ERR_OR_OFFLINE`), that an `anesthesiologist_id` is set and that anesthesiologist is active (otherwise `ERR_ANESTHESIA_NOT_ASSIGNED`), and that the owning day's `posture` is `LOCKED` (otherwise `ERR_DAY_NOT_LOCKED` — a day must be locked before any case enters the OR). A successful start advances the case to `IN_OR`.

Moving a case to recovery advances `IN_OR → IN_RECOVERY` and requires the case to be `IN_OR` (otherwise `ERR_CASE_NOT_IN_OR`) and a `recovery_bay_id` to be set on a bay whose `status` is `AVAILABLE` (otherwise `ERR_RECOVERY_NOT_ASSIGNED`).

Completing a case advances `IN_RECOVERY → COMPLETED` and is where the case settles. It requires the case to be `IN_RECOVERY` (otherwise `ERR_CASE_NOT_IN_RECOVERY`), an `actual_minutes` value that is supplied and positive (otherwise `ERR_ACTUAL_MINUTES_REQUIRED`), and every still-`RESERVED` `CaseImplant` on the case to already have its `consumed_qty` recorded (otherwise `ERR_IMPLANT_NOT_SETTLED`; implants already in `RELEASED` or `CONSUMED` status are not subject to this check). On completion the system performs a cascade: each `RESERVED` implant on the case advances `RESERVED → CONSUMED`, decrementing its supply item's `reserved_qty` by the implant's `planned_qty` and its `on_hand_qty` by the implant's `consumed_qty` (a consume requires the implant to have been `RESERVED`, otherwise `ERR_IMPLANT_NOT_RESERVED`, and the recorded `consumed_qty` to lie between 0 and `planned_qty` inclusive, otherwise `ERR_CONSUMED_QTY_INVALID`). It then computes the case's `actual_cost_cents` and its `cms_payment_cents`, and recomputes the owning day's `utilization_pct` using actual minutes for completed cases. Until a case is completed, both `actual_cost_cents` and `cms_payment_cents` are null.

### 3.12. Actual Case Cost and the Over-Run Penalty

The actual cost settled at completion mirrors the estimate but uses recorded inputs and adds one element the estimate never carries. The labor part is the case's `actual_minutes` multiplied by the same OR minute rate of 1,200 cents per minute. The anesthesia part is the same flat base keyed to `anesthesia_class` (zero for `LOCAL`, 18,000 for `MAC`, 32,000 for `REGIONAL`, 55,000 for `GENERAL`). The implant part now sums only the case implants in `CONSUMED` status — reserved and released lines are excluded — multiplying each supply item's `unit_cost_cents` by that implant's `consumed_qty`, rounding each line half-up to a whole cent, and summing the rounded lines; it uses `consumed_qty`, never `planned_qty`. The add-on surcharge of 40,000 cents is again added only when `is_add_on` is true.

The new element is an over-run penalty. First compute the over-run minutes as the case's `actual_minutes` minus the procedure's `scheduled_minutes`, floored at zero (so a case that ran at or under its scheduled time has no over-run). The penalty is then charged by **marginal banding** across three bands, each minute charged at its own band's rate rather than at a single blended rate. The first band covers over-run minutes 1 through 15 at 800 cents per minute. The second band covers over-run minutes 16 through 45 — that is, the minutes above 15 up to a cumulative 45 — at 1,500 cents per minute. The third band covers every over-run minute beyond 45 at 3,000 cents per minute. Concretely, the count of band-one minutes is the lesser of the over-run and 15; the count of band-two minutes is the over-run reduced by 15 (floored at zero) but capped at 30 (the width from 15 to 45); and the count of band-three minutes is the over-run reduced by 45 (floored at zero). The penalty is the band-one minute count times 800 cents, plus the band-two minute count times 1,500 cents, plus the band-three minute count times 3,000 cents. The boundaries are exact: minute 15 falls in band one, and minute 16 begins band two. The case's `actual_cost_cents` is the sum of the labor part, the anesthesia part, the per-line-rounded consumed-implant total, the add-on surcharge, and this over-run penalty. Because the actual variant uses recorded minutes and consumed quantities and adds the over-run penalty, it diverges from the estimate whenever `actual_minutes` differs from `scheduled_minutes` or `consumed_qty` differs from `planned_qty`.

### 3.13. ASC Payment Grouping

At completion the system also computes the case's `cms_payment_cents` from the CMS ASC payment list, in four mandatory steps that must be evaluated in order — the order is non-commutative because later steps consume the result of earlier ones.

Step one establishes the base as the procedure's `cms_base_rate_cents`. Step two applies a device offset, but only when the procedure's `cms_payment_indicator` is `DEVICE_INTENSIVE`; for every other indicator the grouped amount is simply the base. For a device-intensive procedure, first sum the device cost across the case's `CONSUMED` implants whose supply item has `is_device` set — for each such line, multiply the supply item's `unit_cost_cents` by the implant's `consumed_qty`, round half-up to a whole cent, and sum the rounded lines. Then compute a percentage offset as the base multiplied by the procedure's `device_offset_pct` divided by 100, rounded half-up to a whole cent. The applied device offset is the **lesser** of that percentage offset and the actual summed device cost, and the grouped amount is the base plus that device offset. Step three applies a multiple-procedure reduction: if this completing case is the second or later non-cancelled completed case for the **same patient on the same `service_date`** — where ordering among the patient's same-day completed cases is by `start_min` ascending and then `created_at` ascending — the grouped amount (already including any device offset from step two) is reduced by 50 percent, that is, multiplied by one-half and rounded half-up to a whole cent; the first such case for the patient that day takes no reduction. Step four enforces an office-based floor: when the procedure's `cms_payment_indicator` is `OFFICE_BASED`, if the grouped amount is below 9,000 cents it is raised to that 9,000-cent floor. The result of these steps, in order, is the case's `cms_payment_cents`.

### 3.14. Day Utilization and Anesthesia Coverage Load

The day's `utilization_pct` is recomputed on every booking, cancellation, completion, and block release, except on a `CLOSED` day, where it is frozen. Utilization is a percentage of prime-time minutes used against prime-time minutes available. The denominator is the prime-time capacity: summing, over each distinct operating room that hosted at least one non-cancelled case on the day, that room's `prime_time_end_min` minus its `prime_time_start_min`. The numerator is the used minutes: for each non-cancelled case, the overlap between the case's footprint `[start_min, end_min)` and its room's prime-time window `[prime_time_start_min, prime_time_end_min)` — using the case's `actual_minutes` for a `COMPLETED` case and its `scheduled_minutes` otherwise. Because the overlap is computed on half-open intervals, a case ending exactly at `prime_time_end_min` contributes nothing for that boundary minute. When the prime-time capacity is zero, `utilization_pct` is zero; otherwise it is 100 times the used minutes divided by the prime-time capacity, rounded half-up to one decimal place. A day is flagged as under-utilized when its `utilization_pct` is below the facility's `utilization_target_pct`, and over-utilized when its `utilization_pct` is at least 100.0.

The platform also reports an anesthesiologist's coverage load for a `service_date` (supplied as a required query parameter; a missing `service_date` is rejected as `ERR_INVALID_REQUEST`), in a projected (default) and an actual variant selected by a `basis` query parameter whose permitted values are exactly `PROJECTED` (the default when `basis` is omitted) and `ACTUAL` (any other value is `ERR_INVALID_REQUEST`). The report returns the anesthesiologist's identifier as `anesthesiologist_id`, the `service_date`, the `basis` used (echoed as the resolved value `PROJECTED` or `ACTUAL`), the total minutes as an integer field named `minutes`, and a `coverage_load_pct`; this report is not a versioned resource and carries none of the common lifecycle fields. Both variants consider the cases assigned to that anesthesiologist on the given date whose `case_status` is anything other than `CANCELLED`. The projected variant sums each such case's planned `scheduled_minutes`. The actual variant instead walks the same cases in chronological order — `start_min` ascending, then `created_at` ascending — and, for each, uses `actual_minutes` if the case is `COMPLETED` and `scheduled_minutes` otherwise; a not-yet-completed case thus contributes its planned footprint as a placeholder. In both variants the coverage load percentage is 100 multiplied by the summed minutes, divided by the solo-coverage cap of 480 minutes (eight prime-time hours), rounded half-up to one decimal place. The two variants diverge whenever a completed case ran over or under its scheduled time.

## 4. Endpoint Definitions

All endpoints are mounted under `/asc`. Creating a new resource returns HTTP 201; reads, list operations, and state-changing actions on an existing resource return HTTP 200. Request and response payloads, including which body fields each action requires and the side effects it triggers, are specified in the §3 narratives above; the table below summarizes only the HTTP surface.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /asc/facilities | Create an ASC facility | Scheduler |
| GET | /asc/facilities/{facilityId} | Get a facility | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/facilities/{facilityId}/clock | Advance the deterministic facility clock | Scheduler, ORManager |
| POST | /asc/operating-rooms | Create an operating room | ORManager |
| GET | /asc/operating-rooms | List operating rooms | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/operating-rooms/{orId} | Get an operating room | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/operating-rooms/{orId}/status | Toggle OR status AVAILABLE/OFFLINE | ORManager |
| POST | /asc/recovery-bays | Create a recovery bay | ORManager |
| GET | /asc/recovery-bays | List recovery bays | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/recovery-bays/{bayId} | Get a recovery bay | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/recovery-bays/{bayId}/status | Toggle recovery bay status AVAILABLE/OFFLINE | ORManager |
| POST | /asc/anesthesiologists | Create an anesthesiologist | ORManager |
| GET | /asc/anesthesiologists | List anesthesiologists | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/anesthesiologists/{anesthId} | Get an anesthesiologist | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/anesthesiologists/{anesthId}/coverage-load | Projected or actual anesthesia coverage load | Scheduler, ORManager, BillingAnalyst |
| POST | /asc/surgeons | Create a surgeon | Scheduler |
| GET | /asc/surgeons | List surgeons | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/surgeons/{surgeonId} | Get a surgeon | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| PATCH | /asc/surgeons/{surgeonId} | Update surgeon active flag | Scheduler |
| POST | /asc/procedures | Create a procedure (CMS ASC list entry) | BillingAnalyst |
| GET | /asc/procedures | List procedures | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/procedures/{procedureId} | Get a procedure | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/supply-items | Create a supply/device item | ORManager |
| GET | /asc/supply-items | List supply items | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/supply-items/{itemId} | Get a supply item | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/supply-items/{itemId}/restock | Increase on-hand quantity | ORManager |
| POST | /asc/patients | Create a patient | Scheduler, PreOpNurse |
| GET | /asc/patients | List patients | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/patients/{patientId} | Get a patient | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/surgical-days | Create a surgical day | Scheduler |
| GET | /asc/surgical-days | List surgical days | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/surgical-days/{dayId} | Get a surgical day | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/surgical-days/{dayId}/lock | Lock the day | Scheduler |
| POST | /asc/surgical-days/{dayId}/reopen | Reopen the day | Scheduler |
| POST | /asc/surgical-days/{dayId}/close | Close the day | ORManager |
| POST | /asc/surgeon-blocks | Open a surgeon block | Scheduler |
| GET | /asc/surgeon-blocks | List surgeon blocks | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/surgeon-blocks/{blockId} | Get a surgeon block | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/surgeon-blocks/{blockId}/confirm | Confirm a block | Scheduler |
| POST | /asc/surgeon-blocks/{blockId}/release | Release a block (cascades) | Scheduler |
| POST | /asc/surgeon-blocks/{blockId}/cases | Book a surgical case into the block (OCC-guarded) | Scheduler |
| GET | /asc/surgical-cases | List surgical cases | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/surgical-cases/{caseId} | Get a surgical case | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| PATCH | /asc/surgical-cases/{caseId}/reschedule | Move a scheduled case to a new start time | Scheduler |
| POST | /asc/surgical-cases/{caseId}/assign-anesthesia | Assign or reassign an anesthesiologist | ORManager |
| POST | /asc/surgical-cases/{caseId}/assign-recovery | Assign or reassign a recovery bay | ORManager |
| POST | /asc/surgical-cases/{caseId}/clearance-checks | Record a pre-op clearance check | PreOpNurse |
| GET | /asc/clearance-checks | List clearance checks | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/clearance-checks/{checkId} | Get a clearance check | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| POST | /asc/surgical-cases/{caseId}/clearance-reset | Reset clearance to pending | PreOpNurse |
| POST | /asc/surgical-cases/{caseId}/clear | Mark clearance cleared (enforces H&P window) | PreOpNurse |
| POST | /asc/surgical-cases/{caseId}/start | Start the case into the OR | ORManager |
| POST | /asc/surgical-cases/{caseId}/to-recovery | Move case to recovery | ORManager |
| POST | /asc/surgical-cases/{caseId}/complete | Complete the case and settle cost/payment | ORManager |
| POST | /asc/surgical-cases/{caseId}/cancel | Cancel a scheduled case (compensating) | Scheduler |
| POST | /asc/surgical-cases/{caseId}/implants | Attach an implant/supply to a case | ORManager |
| PATCH | /asc/case-implants/{implantId} | Record consumed quantity on an implant | ORManager |
| POST | /asc/surgical-cases/{caseId}/implants/{implantId}/release | Release a reserved implant | ORManager |
| GET | /asc/case-implants | List case implants | Scheduler, PreOpNurse, ORManager, BillingAnalyst |
| GET | /asc/case-implants/{implantId} | Get a case implant | Scheduler, PreOpNurse, ORManager, BillingAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INSUFFICIENT_PERMISSIONS | 403 |
| ERR_FACILITY_NOT_FOUND | 404 |
| ERR_OPERATING_ROOM_NOT_FOUND | 404 |
| ERR_RECOVERY_BAY_NOT_FOUND | 404 |
| ERR_ANESTHESIOLOGIST_NOT_FOUND | 404 |
| ERR_SURGEON_NOT_FOUND | 404 |
| ERR_PROCEDURE_NOT_FOUND | 404 |
| ERR_SUPPLY_ITEM_NOT_FOUND | 404 |
| ERR_PATIENT_NOT_FOUND | 404 |
| ERR_SURGICAL_DAY_NOT_FOUND | 404 |
| ERR_SURGEON_BLOCK_NOT_FOUND | 404 |
| ERR_SURGICAL_CASE_NOT_FOUND | 404 |
| ERR_CASE_IMPLANT_NOT_FOUND | 404 |
| ERR_CLEARANCE_CHECK_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_DUPLICATE_KEY | 409 |
| ERR_STALE_BLOCK_VERSION | 412 |
| ERR_BLOCK_NOT_HELD | 409 |
| ERR_BLOCK_NOT_RELEASABLE | 409 |
| ERR_BLOCK_RELEASED | 409 |
| ERR_BLOCK_HAS_ACTIVE_CASES | 409 |
| ERR_DAY_NOT_OPEN | 409 |
| ERR_DAY_NOT_LOCKED | 409 |
| ERR_DAY_LOCKED | 409 |
| ERR_DAY_CLOSED | 409 |
| ERR_DAY_EMPTY | 409 |
| ERR_DAY_HAS_ACTIVE_CASES | 409 |
| ERR_DAY_HAS_UNFINISHED_CASES | 409 |
| ERR_CASE_NOT_SCHEDULED | 409 |
| ERR_CASE_NOT_IN_OR | 409 |
| ERR_CASE_NOT_IN_RECOVERY | 409 |
| ERR_CASE_NOT_CANCELLABLE | 409 |
| ERR_CASE_NOT_CLEARED | 409 |
| ERR_CLEARANCE_NOT_PENDING | 409 |
| ERR_CLEARANCE_NOT_ON_HOLD | 409 |
| ERR_HP_REVIEW_MISSING | 409 |
| ERR_OPEN_FAILED_CHECK | 409 |
| ERR_HP_WINDOW_EXPIRED | 409 |
| ERR_OR_OFFLINE | 409 |
| ERR_RECOVERY_NOT_ASSIGNED | 409 |
| ERR_ANESTHESIA_NOT_ASSIGNED | 409 |
| ERR_ANESTHESIOLOGIST_INACTIVE | 409 |
| ERR_CRNA_CANNOT_COVER_GENERAL | 409 |
| ERR_RECOVERY_PHASE2_REQUIRED | 409 |
| ERR_PROCEDURE_EXCLUDED | 409 |
| ERR_SURGEON_INACTIVE | 409 |
| ERR_CASE_OUTSIDE_BLOCK_WINDOW | 409 |
| ERR_OR_TIME_CONFLICT | 409 |
| ERR_ANESTHESIA_TIME_CONFLICT | 409 |
| ERR_BLOCK_CAPACITY_EXCEEDED | 409 |
| ERR_SUPPLY_INSUFFICIENT | 409 |
| ERR_ACTUAL_MINUTES_REQUIRED | 400 |
| ERR_IMPLANT_NOT_SETTLED | 409 |
| ERR_IMPLANT_NOT_RESERVED | 409 |
| ERR_CONSUMED_QTY_INVALID | 409 |

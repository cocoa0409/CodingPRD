# EV Battery Swap API — Product Requirements Document

## 1. Introduction

Electric-vehicle battery swap stations promise a refuelling experience that takes minutes rather than hours, but the operational reality is far harder than rolling a fresh pack onto a forklift. Each station holds a finite inventory of expensive, ageing assets — every battery has its own state of charge, its own state of health, its own cycle history, and its own warranty and recall record. Drivers arrive on reservation or unannounced, expect a compatible pack on demand, and tolerate neither surprise pricing nor surprise unavailability. Station operators in turn must orchestrate a swap that touches at least two batteries (the one removed from the vehicle and the one installed), one charging slot, one vehicle, one billing record, and frequently a downstream dispatch order to rebalance inventory across the network.

This document specifies the API of the EV Battery Swap platform — the system of record behind a fleet of stations that registers batteries and vehicles, books and fulfils swap reservations, runs the physical swap workflow in audited phases, performs state-of-health (SOH) assessment at the end of every charge cycle, grades retired batteries into a cascade-utilisation lifecycle, settles billing with time-of-use pass-through and subscription deductions, and synchronises with external payment, mapping, grid, and manufacturer-warranty systems through emitted events. The platform exposes a deterministic, idempotent REST surface to three peer roles — `Member`, `StationOperator`, and `PlatformAdmin` — and is engineered so that fairness across reservations, conservation of subscription credits, and the auditability of every status change are first-class invariants rather than after-the-fact reports. All endpoints documented here are mounted under the system path prefix `/swap-stations`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is missing the server rejects the request with `ERR_AUTH_REQUIRED` and HTTP 401. If `X-User-Role` is not one of the three recognised values — `Member`, `StationOperator`, `PlatformAdmin` — the request is rejected with `ERR_FORBIDDEN` and HTTP 403; the same error is returned when an authenticated caller addresses an endpoint not authorised for their role.

The three roles bind to identity as follows. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; any ownership filter (the "own only" scope on listings of reservations and billing records, and the self-only scope on member detail) compares the relevant foreign-key field on the target resource — `member_id` on a reservation or a billing record, the `id` of the member itself on member detail — to `X-User-ID`. When `X-User-Role` is `StationOperator`, `X-User-ID` is the `id` of the acting `Station`; operations the operator performs (check-in, inspect, uninstall, install, complete, abort, start-charging, finish-charging, report-fault, clear-fault) are scoped to resources whose `station_id` equals `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `actor_id` on `AuditLog` whenever an admin-triggered transition emits an audit row) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; the default `offset` is 0 and it must be at least 0. A value outside these ranges is rejected with `ERR_INVALID_PAGINATION` and HTTP 422. List results are sorted by `created_at` ascending unless an endpoint description states otherwise. The `meta` block of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when the sum of `offset` and the returned page size is strictly less than `total_count`.

### 2.4. Common Resource Properties and Audit Identity

Every persisted resource is keyed by an `id` that is a server-minted UUID — the `id` contains no type prefix and is generated by the platform, never supplied by the client. Resources that the system tracks mutably also carry three system-managed fields: `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, and `version` is an integer that starts at 1 on creation and increments by exactly one on every mutation that changes the resource. The following entities carry the full set of common fields (`id`, `created_at`, `updated_at`, `version`): `Station`, `Battery`, `ChargingSlot`, `Vehicle`, `Member`, `Reservation`, `SwapEvent`, `BillingRecord`, and `DispatchOrder`. The following entities are reference data or append-only records and therefore carry only `id` and `created_at` — `updated_at` and `version` are absent: `BatteryModel`, `VehicleModel`, `CompatibilityRule`, `SOHAssessment`, and `AuditLog`.

Every status or phase transition that touches a `Battery`, a `SwapEvent`, a `DispatchOrder`, a `Reservation`, or that records a recall application produces a row in `AuditLog`. The audit row captures the `event_type` (one of `BATTERY_STATUS_CHANGE`, `SWAP_PHASE_CHANGE`, `DISPATCH_CHANGE`, `RECALL_APPLIED`, `RESERVATION_CHANGE`), the affected `entity_type` and `entity_id`, the prior value as `from_value` (null when first set) and the new value as `to_value`, the `actor_role` and `actor_id` that triggered it, and the timestamp `occurred_at` taken from the server clock at the moment of the change.

### 2.5. Hierarchical Consistency and Side-Effect Cascades

Cross-entity side effects fan out from the entity that owns the transition. When a `Battery` leaves `IDLE` to enter `CHARGING`, the host `ChargingSlot` flips from `EMPTY` to `OCCUPIED` and its `battery_id` is set to that battery's `id`, the host `Station` decrements `idle_battery_count` by one and increments `charging_battery_count` by one, and an `AuditLog` row records the change. When that same battery returns from `CHARGING` back to `IDLE`, the slot is released to `EMPTY` with its `battery_id` cleared to null, the station decrements `charging_battery_count` by one and increments `idle_battery_count` by one, and a corresponding audit row is appended. Whenever any of these cascades alters a resource that carries `version`, that resource's `version` is incremented by one and its `updated_at` is refreshed to the server clock; nothing in this specification ever bumps `version` without a corresponding state or content change. Cascades initiated by one endpoint complete inside that endpoint's transactional boundary — by the time the response is returned, every dependent count, every dependent foreign key, every dependent timestamp has already been updated.

### 2.6. Nested Resource Retrieval and Path Validation

Whenever a URL contains more than one identifier segment — for example a charging-slot listing scoped to a station, or a SOH-assessment listing scoped to a battery — the path is validated from left to right. The outermost resource is resolved first; if it does not exist the response is `ERR_NOT_FOUND` with HTTP 404 and the inner segments are not consulted. Only after the outer resource is confirmed does the server resolve the inner segment, returning the same `ERR_NOT_FOUND` if the inner resource is absent or does not belong to the resolved outer.

### 2.7. Precision, Rounding, and Monetary Conservation

All monetary amounts on the platform are stored and transmitted as integer cents. Whenever a calculation produces a real-valued intermediate that must be persisted as cents, the value is rounded half-up to a whole cent before being summed into a larger total — the rounding is applied per component, not once at the very end. SOH percentages are likewise rounded half-up to two decimal places before being compared against any threshold, and the degradation slope computed by the curve fit is rounded half-up to four decimal places. No amount stored on a `BillingRecord` is ever negative: `amount_due_cents` is floored at zero, and `refund_cents` cannot exceed `amount_due_cents`.

### 2.8. Optimistic Concurrency Control

Mutating endpoints that update a resource carrying `version` accept an optional `version` field in the request body. When a caller supplies `version`, the server compares it against the resource's current `version`; if the two differ the request is rejected with `ERR_VERSION_CONFLICT` and HTTP 409. When `version` is omitted, the concurrency check is skipped and the mutation proceeds against the latest copy. A successful mutation always increments `version` by one regardless of whether the caller supplied it.

### 2.9. Compatibility, Recall, and Safety Gating

Two safety predicates pervade the workflow. The first is **compatibility**: a vehicle of model `V` can only accept a battery of model `B` if a `CompatibilityRule` exists whose `vehicle_model_code` equals `V` and whose `battery_model_code` equals `B`, **and** in which both `connector_match` and `bms_handshake_supported` are true. Failure of either flag, or absence of the rule entirely, produces `ERR_INCOMPATIBLE_MODEL` and HTTP 422 at reservation creation and at install time. The second is **recall**: a `Battery` whose `recall_flag` is true is permanently barred from re-entering service. Any attempt to start charging it, to install it into a vehicle, or to clear its fault is rejected with `ERR_BATTERY_RECALLED` and HTTP 409. Applying a manufacturer recall to a battery that has already transitioned to `IN_USE` is also rejected with `ERR_BATTERY_RECALLED` — the recall pathway only acts on batteries currently in `IDLE` or `CHARGING`.

### 2.10. Concurrency Serialisation Points

The platform serialises four categories of race:

1. Two reservations that attempt to soft-hold the same compatible `IDLE` battery at overlapping time windows on the same station are resolved first-writer-wins on `held_battery_id`. The loser receives `ERR_NO_COMPATIBLE_BATTERY` and HTTP 409, because by the time it evaluates eligibility the only compatible idle battery has already been pinned to the earlier reservation.
2. Two operators that attempt to install different `IDLE` batteries into the same vehicle simultaneously are serialised on the `SwapEvent` phase transition from `UNINSTALLED` to `INSTALLED`. Exactly one install transitions; the loser receives `ERR_INVALID_STATE` and HTTP 409.
3. A manufacturer recall and an active install racing on the same battery are serialised first-writer-wins. If the install lands first, the battery is already `IN_USE` and the recall is rejected with `ERR_BATTERY_RECALLED` and HTTP 409. If the recall lands first, `recall_flag` becomes true and the install is rejected with `ERR_BATTERY_RECALLED` and HTTP 409.
4. Two dispatch orders that try to move the same `IDLE` battery are serialised on `Battery.status`. The first transitions the battery to `IN_TRANSIT`; the second receives `ERR_BATTERY_NOT_IDLE` and HTTP 409.
5. On a `PENDING` billing record, a payment and an admin mark-failed racing each other are serialised on `payment_status`. Exactly one terminal outcome wins; the other is rejected with `ERR_INVALID_STATE` and HTTP 409.

### 2.11. Validation Priority Order

When more than one validation could apply to a request, the platform evaluates them in a fixed priority order so that the returned `error_id` is deterministic. The header presence check fires first (highest priority), and if it passes the role-membership check runs next; together these short-circuit any business logic. Once authentication is settled, path-resource existence is validated left-to-right. Only after a resource resolves does the platform evaluate state preconditions — first whether the target `Battery.status` is a valid `from` state for the requested transition, then whether the target `SwapEvent.phase` is. After state, recall safety is checked before model compatibility, which in turn precedes the temporal validations attached to reservation creation. Within reservation creation the temporal checks themselves fire in a fixed order: slot-length first, then "not in the immediate past", then per-member overlap, then station-capacity, then the search for at least one eligible battery, and finally the member-block check. Refund-bounds validation, dispatch source-vs-destination identity, dispatch readiness on the source battery, pagination bounds, and the optimistic-concurrency `version` check each guard their own endpoints and are evaluated after the auth/existence/state stack above. Whenever two checks would reject the same request, the one with the smaller priority number is the one whose `error_id` is returned. Beyond the priority-ordered business validations above, two generic errors round out the catalogue: any attempt to create a resource whose unique fields collide with an existing row — a duplicate `serial_number` on a battery, a duplicate `phone` on a member, a duplicate model `code`, or a duplicate `vin` — is rejected with `ERR_DUPLICATE_RESOURCE` and HTTP 409, and any request that is missing a required field or supplies a structurally malformed value (where no more specific business error applies) is rejected with `ERR_INVALID_INPUT` and HTTP 422.

## 3. Business Logic & Workflows

### 3.1. The Station, Its Slots, and Its Reference Data

A `PlatformAdmin` opens the platform by registering a `Station`. A station carries a human-readable `name`, geographic `latitude` and `longitude` in decimal degrees (latitude between -90.0 and 90.0 inclusive, longitude between -180.0 and 180.0 inclusive), and `total_slots`, the number of charging bays physically installed on site. A station must have at least one slot and at most sixty-four. Its operational `status` is computed by the platform — it begins life as `OPEN`, can be reduced to `RESTRICTED`, or taken down entirely to `OFFLINE`. Two counters, `idle_battery_count` and `charging_battery_count`, mirror live inventory at the station and are kept in lock-step with battery transitions; both default to zero on registration.

Slots are added to a station one at a time. Each `ChargingSlot` belongs to one station via its `station_id` foreign key, carries a `slot_number` unique within that station (at least one and not exceeding the station's `total_slots`), and a `tou_zone` that classifies the bay's electricity meter into `PEAK`, `SHOULDER`, or `OFF_PEAK`; the zone defaults to `SHOULDER` when the operator does not supply one. A slot's `status` is `EMPTY` on creation, becomes `OCCUPIED` when a battery is parked in it, and may be administratively flipped to `OUT_OF_SERVICE`; the slot's `battery_id` is null whenever it is `EMPTY` and references the parked battery whenever it is `OCCUPIED`.

Members and vehicles are likewise registered through dedicated administrative endpoints before any swap can occur. A `Member` record carries a `name` and a unique contact `phone`; subscription state may be seeded at creation through the optional `subscription_tier` (one of `NONE`, `BASIC`, `PREMIUM`, defaulting to `NONE`) and `subscription_swaps_remaining` (defaulting to zero). A `Vehicle` is registered with a unique `vin` (between eleven and seventeen characters), the `vehicle_model_code` of the model it conforms to, the `owner_member_id` of the member who owns it, and optionally an initial `installed_battery_id` for vehicles that arrive on the platform with a pack already fitted. When a station operator searches inventory through the batteries listing, the optional query filter `vehicle_model_compatible` restricts the result to batteries whose model has a satisfying `CompatibilityRule` with the supplied vehicle-model code (both `connector_match` and `bms_handshake_supported` true).

The platform's reference data — `BatteryModel`, `VehicleModel`, and the `CompatibilityRule` between them — is the gate through which every swap must pass. A `BatteryModel` is identified by its manufacturer `code` (unique, length between two and thirty-two characters), and carries `rated_capacity_kwh` in kilowatt-hours, `nominal_voltage` in volts (both strictly greater than zero), the `manufacturer` name, and an `ev_soh_floor_pct` — the SOH percent below which a battery of this model is no longer fit for EV use and must be retired. `ev_soh_floor_pct` is strictly greater than zero, strictly less than one hundred, and defaults to 80.0 when the admin omits it. A `VehicleModel` carries its own `code`, a marketing `name`, and two voltages — `pack_voltage_min` (at least zero) and `pack_voltage_max` (strictly greater than `pack_voltage_min`). A `CompatibilityRule` joins the two by their codes (`vehicle_model_code`, `battery_model_code`) and asserts whether `connector_match` and `bms_handshake_supported`; both flags default to true when omitted at creation. Compatibility, for the purposes of every gating decision elsewhere in this document, means the rule exists and both flags are true.

### 3.2. Battery Onboarding, the Charge Cycle, and Cascading Side Effects

A battery enters the platform when a `PlatformAdmin` registers it: the request carries a `serial_number` (globally unique, between six and sixty-four characters), the `battery_model_code` it belongs to, the `station_id` where it is being installed, its `warranty_expires_at` end-date, and optional initial values for `soc_pct` and `soh_pct` (both defaulting to 100.0 and 0.0 respectively if not supplied — the SOC defaulting to 0.0, the SOH to 100.0). The new battery starts at `status` `IDLE`, `cycle_count` zero, `cascade_stage` `NONE`, `recall_flag` false, and `soh_grade` `A`. The station's `idle_battery_count` is incremented by one as a direct side effect of registration.

A `StationOperator` moves an `IDLE` battery into a charging bay by referencing the target slot through its `charging_slot_id` in the request body. Three preconditions guard the move: the battery must currently be in `IDLE`, the slot must be `EMPTY` with its `battery_id` null, and the battery's `recall_flag` must be false. When the move succeeds, the battery flips from `IDLE` to `CHARGING`, the slot becomes `OCCUPIED` and binds to the battery's `id`, the station's `idle_battery_count` decreases by one and `charging_battery_count` rises by one, and an audit row records the `IDLE`-to-`CHARGING` change. Violating the recall predicate returns `ERR_BATTERY_RECALLED`; violating either status predicate returns `ERR_INVALID_STATE`.

Finishing a charge cycle is where the cascade chain begins. The operator submits the final `soc_pct` along with the three SOH measurement inputs — `capacity_test_kwh`, `internal_resistance_mohm`, and `avg_temperature_c`. The battery's `status` must be `CHARGING`, and the submitted `soc_pct` must be at least 95, marking the charge as complete; otherwise `ERR_INVALID_STATE`. The platform then performs three calculations and a possibly-branching transition. First, the battery's `cycle_count` is incremented by one and its `soc_pct` overwritten with the value just submitted. Second, a fresh `SOHAssessment` row is inserted, with `cycle_count_at_assessment` reading the post-increment cycle count — this is the value used by the curve fit and the cascade grader, and is intentionally the count that includes the cycle just completed. Third, the new `soh_pct` is computed from the assessment (see §3.6), the new `soh_grade` derived from it, and a degradation slope fitted across the most recent assessments for this battery.

The branch then resolves. If the new `soh_grade` is `RETIRED_EV`, the platform auto-transitions the battery from `CHARGING` straight to `RETIRED` rather than back to `IDLE`: the host slot flips to `EMPTY` with `battery_id` cleared, the station's `charging_battery_count` decreases by one (and `idle_battery_count` is not incremented because the battery did not return to inventory), an audit row records `CHARGING`-to-`RETIRED`, and the cascade-grading calculation runs on the newly retired battery to populate `cascade_stage`. If instead the new `soh_grade` is `A`, `B`, or `C`, the battery returns from `CHARGING` to `IDLE` in the ordinary way: the slot flips to `EMPTY`, the station decrements `charging_battery_count` and increments `idle_battery_count`, and the audit row records `CHARGING`-to-`IDLE`.

Outside the charging path, two operator endpoints handle abnormal conditions. Reporting a fault accepts an optional `reason` string and is valid when the battery's `status` is in `IDLE` or `CHARGING`; the battery transitions to `FAULT`, and the host station's inventory counter is adjusted accordingly — `idle_battery_count` decrements if the battery was `IDLE`, or `charging_battery_count` decrements and the slot is released to `EMPTY` if the battery was `CHARGING`. A fault is cleared by an operator only when the battery is currently `FAULT` and `recall_flag` is false: the battery returns to `IDLE` and the station's `idle_battery_count` increases by one. A fault clear on a recalled battery is rejected with `ERR_BATTERY_RECALLED`.

### 3.3. The Reservation Lifecycle: From Hold to No-Show to Walk-In

A reservation is a soft-hold contract between a `Member` and a `Station` for a specific quarter-hour. Creation accepts a `member_id`, the `vehicle_id` the member intends to swap, the target `station_id`, and the two timestamps `slot_start_at` and `slot_end_at`. Five business validations are run in sequence on every reservation request. The slot must be exactly fifteen minutes long: `slot_end_at` must equal `slot_start_at` plus fifteen minutes, otherwise `ERR_INVALID_TIME_SLOT` and HTTP 422. The slot must not be in the immediate past — `slot_start_at` must fall at least five minutes after the current server time, otherwise `ERR_INVALID_TIME_SLOT`. The slot must not overlap, in a half-open `[slot_start_at, slot_end_at)` sense, any other `BOOKED` reservation already held by the same member; two reservations that meet exactly at a boundary instant do not overlap, but any strictly-interior overlap returns `ERR_RESERVATION_OVERLAP_MEMBER` and HTTP 409. The station must have capacity at the requested instant: count every existing `BOOKED` reservation at this station whose interval **strictly overlaps** the new slot — touching at the boundary is permitted here too, with explicitly different interval semantics than the same-member overlap check — and reject with `ERR_STATION_CAPACITY_FULL` and HTTP 409 if including this new request would push the strict-overlap count above `total_slots`. Finally the member must not be currently blocked: `reservation_blocked_until` must be null or already in the past, otherwise `ERR_MEMBER_BLOCKED` and HTTP 403.

Past those five gates, the system attempts to soft-hold a compatible idle battery. The eligibility filter selects batteries whose `status` is `IDLE`, whose `station_id` equals the reservation's `station_id`, for which a `CompatibilityRule` exists with the vehicle's `vehicle_model_code` and the battery's `battery_model_code` and with both `connector_match` and `bms_handshake_supported` true, whose `recall_flag` is false, and that are not already held by another `BOOKED` reservation. The eligible set is then ranked by `soh_pct` in descending order, then by `cycle_count` in ascending order, then by `created_at` in ascending order, with a final deterministic tie-break on `id` in ascending order. If the set is empty after eligibility filtering, the reservation is rejected with `ERR_NO_COMPATIBLE_BATTERY` and HTTP 409 — and this is exactly the error returned to the second of two concurrent reservations that race for the single remaining compatible idle battery. If the set is non-empty, the highest-ranked battery is selected and the reservation's `held_battery_id` is pinned to that battery's `id`; the battery itself remains in `IDLE` status — the hold is purely advisory until check-in. The reservation's `status` defaults to `BOOKED`, its `queue_position` is left null because it is a scheduled reservation, and the member's `reservation_blocked_until` is unaffected.

Cancellation of a `BOOKED` reservation by either the owning member or a station operator releases the soft hold — `held_battery_id` is cleared to null and the battery remains `IDLE` — and is only accepted at least five minutes before `slot_start_at`. Inside the five-minute window cancellation is no longer permitted and is rejected as an invalid state transition. A reservation that ages past its `slot_end_at` without being checked in is swept to `NO_SHOW`: an admin-only sweep endpoint scans every `BOOKED` reservation, transitions each one whose `slot_end_at` has elapsed to `NO_SHOW`, releases its `held_battery_id` to null, and recomputes the member's `no_show_count_30d` as the count of `NO_SHOW` reservations belonging to that member with `created_at` (or `slot_end_at`) in the last thirty days. If the recomputed count reaches three or more, the member's `reservation_blocked_until` is set to the current server time plus seventy-two hours — a cascade chain that begins at the sweep and ends with the member temporarily unable to book again.

A walk-in is the operator-driven alternative to a scheduled reservation. The operator submits only `member_id`, `vehicle_id`, and `station_id` — there are no client-supplied timestamps. The platform computes `queue_position` as one plus the count of `BOOKED` and `CHECKED_IN` walk-in reservations already at the station, derives `slot_start_at` as the current server time plus five minutes multiplied by `queue_position` (so the first walk-in slots five minutes from now, the second ten, the third fifteen, and so on), and pins `slot_end_at` to `slot_start_at` plus fifteen minutes. The same eligibility filter and ranking used for scheduled reservations select the held battery; the same `ERR_NO_COMPATIBLE_BATTERY` is returned when none is available.

### 3.4. The Swap Workflow: Six Phases, Two Batteries, One Vehicle

Check-in marks the physical arrival of the vehicle. The station operator confirms the reservation's identity. The transition is permitted when the reservation's `status` is `BOOKED`, the current server time lies inside the half-open window `[slot_start_at, slot_end_at)`, the `held_battery_id` references a battery that is still `IDLE`, and the compatibility rule between the vehicle and the held battery is still satisfied. The reservation moves to `CHECKED_IN`, a fresh `SwapEvent` is created with `phase` set to `CHECKED_IN`, its `outgoing_battery_id` initialised to the vehicle's currently `installed_battery_id`, its `reservation_id` linking it back to the originating reservation, and `vehicle_id` and `station_id` denormalised from the reservation. The platform then computes the provisional billing total — see §3.7 — and stores it in `provisional_total_cents`.

Inspection happens next. The operator records the measured `outgoing_soc_pct` of the battery currently in the vehicle (between 0 and 100 inclusive). The `SwapEvent.phase` must be `CHECKED_IN`; the platform writes `outgoing_soc_pct` onto the swap event and advances `phase` to `INSPECTED`.

Uninstall removes the outgoing battery from the vehicle. The swap event must currently be at `phase` `INSPECTED`. The outgoing battery — whose `status` was `IN_USE` — transitions to `IDLE`, has its `soc_pct` set from the swap event's recorded `outgoing_soc_pct`, and has its `station_id` set to the swap station. The vehicle's `installed_battery_id` is cleared to null, the station's `idle_battery_count` is incremented by one, and the `SwapEvent.phase` advances to `UNINSTALLED`.

Install puts the held battery into the vehicle. The operator submits `verify` set to true, asserting that the BMS handshake passed on the physical equipment. The `SwapEvent.phase` must be `UNINSTALLED`, the reservation's `held_battery_id` must still reference a battery in `IDLE` status, and the recall and compatibility predicates must still hold against the held battery. The held battery transitions from `IDLE` to `IN_USE`, the vehicle's `installed_battery_id` is set to the held battery's `id`, the swap event's `incoming_battery_id` is set to the same id and `incoming_soc_pct` is snapshotted from the battery's current `soc_pct` at this moment (the value that will drive the final billing), the station's `idle_battery_count` decreases by one, and `phase` advances to `INSTALLED`.

Complete is the terminal forward transition. The swap event must be in `INSTALLED`. The platform computes the final billing total — see §3.7 — and writes it to `final_total_cents`, sets `phase` to `COMPLETED`, sets `completed_at` to the current server time, creates the corresponding `BillingRecord` linked back via `swap_event_id`, bubbles the reservation up from `CHECKED_IN` to `FULFILLED`, and emits a `SWAP_COMPLETED` event into the platform's outbound queue for the payment system. If at this moment the member's `subscription_swaps_remaining` is strictly greater than zero, the platform decrements it by one and applies the configured per-tier deduction to the billing record's `subscription_deduction_cents`; if the counter is zero the deduction is zero regardless of subscription tier. An audit row records the `INSTALLED`-to-`COMPLETED` phase change.

Abort is the compensating path. An operator may abort while the swap event is in `CHECKED_IN`, `INSPECTED`, or `UNINSTALLED`. The swap event transitions to `ABORTED`, the reservation transitions from `CHECKED_IN` to `CANCELLED`, and the soft hold on `held_battery_id` is released. If the abort lands while `phase` was already `UNINSTALLED` — meaning the outgoing battery has already been removed — the platform performs the compensating physical action: the outgoing battery is re-installed into the vehicle, transitioning from `IDLE` back to `IN_USE`, the vehicle's `installed_battery_id` is restored to the outgoing battery's `id`, and the station's `idle_battery_count` is decremented by one to undo the increment from the uninstall step. This compensation preserves the conserved quantity that "every vehicle that arrived with a battery installed leaves with a battery installed".

### 3.5. SOH Assessment, Grading, and the Cascade Tail

State-of-health computation is the platform's most arithmetic-heavy operation and is invoked exactly once per finish-charging request. Each fresh `SOHAssessment` row holds the inputs (`capacity_test_kwh`, `internal_resistance_mohm`, `avg_temperature_c`, and the post-increment `cycle_count_at_assessment` read from the battery), the computed `degradation_slope`, and the two outputs `soh_pct_out` and `soh_grade_out` — the same values that are mirrored onto the battery itself as `soh_pct` and `soh_grade`.

The platform computes the assessment in four named contributions and then composes them. The **capacity factor** is the ratio of `capacity_test_kwh` to the battery model's `rated_capacity_kwh`, multiplied by one hundred to express it as a percentage. The **resistance penalty** is zero unless `internal_resistance_mohm` strictly exceeds fifty milliohms; if it does, the excess milliohms above fifty are multiplied by 0.10 percentage points per milliohm. The **temperature penalty** is zero when `avg_temperature_c` lies within the inclusive range from ten to thirty-five degrees Celsius; if the average is strictly above thirty-five, the excess degrees above thirty-five are multiplied by 0.05 percentage points per degree; if the average is strictly below ten, the shortfall in degrees below ten is multiplied by the same 0.05 per degree. The **cycle penalty** is zero unless `cycle_count_at_assessment` strictly exceeds five hundred; if it does, the excess cycles above five hundred are multiplied by 0.005 percentage points per cycle. The new `soh_pct` is then the capacity factor minus the resistance penalty, minus the temperature penalty, minus the cycle penalty. The result is clamped to the closed interval from zero to one hundred and rounded half-up to two decimal places before being persisted to the battery and to the assessment row.

Grading consumes the rounded `soh_pct`. A value of at least 90.0 grades the battery `A`; otherwise, a value at least the battery model's `ev_soh_floor_pct` (which defaults to 80.0) grades `B`; otherwise, a value at least 70.0 grades `C`; otherwise the grade is `RETIRED_EV`. The boundaries are inclusive on the upper grade — exactly `ev_soh_floor_pct` is `B`, not `C`, and exactly 70.0 is `C`, not `RETIRED_EV` — and the comparisons run on the same rounded two-decimal value that was just persisted. When the grade is `RETIRED_EV`, the auto-transition from `CHARGING` to `RETIRED` runs (see §3.2) and the cascade grader runs immediately to populate `cascade_stage`.

The **degradation curve fit** runs on every assessment after `soh_pct_out` is set. The platform reads up to the five most recent `SOHAssessment` rows for this battery ordered by `created_at` ascending — including the row just inserted — and treats them as a series. If fewer than two points are available the slope is zero. Otherwise the slope is the simple linear-regression slope of `soh_pct_out` against `cycle_count_at_assessment`: for each row let x be its `cycle_count_at_assessment` and y its `soh_pct_out`; the slope is the sum over the window of (x minus the mean of x) multiplied by (y minus the mean of y), divided by the sum over the window of (x minus the mean of x) squared. The result is rounded half-up to four decimal places and stored as `degradation_slope` on the new assessment row.

Cascade grading runs in two situations: automatically, as the closing step of an auto-retire from `RETIRED_EV`; and explicitly, when a platform administrator calls the grade-cascade capability against a `RETIRED` battery whose `cascade_stage` is still `NONE`. The rules are sequential. If `recall_flag` is true, `cascade_stage` is set to `END_OF_LIFE` and secondary use is forbidden. Otherwise, if `cycle_count` is strictly less than one thousand five hundred, the stage is `ENERGY_STORAGE`; otherwise if `cycle_count` is strictly less than two thousand five hundred, the stage is `LOW_SPEED_VEHICLE`; otherwise the stage is `END_OF_LIFE`. The boundaries are exact: a battery with `cycle_count` equal to exactly one thousand five hundred is graded `LOW_SPEED_VEHICLE`, and one with `cycle_count` equal to exactly two thousand five hundred is graded `END_OF_LIFE`. Only a battery whose `status` is `RETIRED` and whose `cascade_stage` is `END_OF_LIFE` can be moved on to `RECYCLED` by an administrator; the recycle action transitions the battery to `RECYCLED`, clears its `station_id` to null, and emits a `RECYCLE_HANDOVER` event for the manufacturer-warranty system. Attempts to recycle a battery whose `cascade_stage` is anything other than `END_OF_LIFE` are rejected with `ERR_INVALID_STATE`.

### 3.6. Cross-Station Dispatch and Manufacturer Recall

Inventory imbalance across stations is corrected by dispatching batteries between sites. A `PlatformAdmin` creates a `DispatchOrder` referencing `source_station_id`, `dest_station_id`, and the specific `battery_id` to be moved. The source and destination must differ; submitting the same station for both fields is rejected with `ERR_INVALID_DISPATCH`. The battery must be `IDLE` at the source station for the order to begin transit; otherwise `ERR_BATTERY_NOT_IDLE` is returned. The order's `status` defaults to `REQUESTED`.

Beginning transit advances the order from `REQUESTED` to `IN_TRANSIT`. The battery transitions from `IDLE` to `IN_TRANSIT`, its `station_id` is cleared to null while in flight, the source station's `idle_battery_count` decreases by one, and the order's `dispatched_at` is set to the server time. Delivery advances the order from `IN_TRANSIT` to `DELIVERED`: the battery returns to `IDLE`, its `station_id` is set to `dest_station_id`, the destination station's `idle_battery_count` increases by one, and the order's `delivered_at` is set. A `REQUESTED` order may also be cancelled while still in that state; cancellation simply moves the order to `CANCELLED` and leaves the battery untouched.

Manufacturer recalls hit the platform through the recalls endpoint, which accepts a `battery_model_code` together with a list `serial_numbers` of affected serials. For each matching battery currently in `IDLE` or `CHARGING`, the platform sets `recall_flag` to true, transitions the battery to `RETIRED`, sets `cascade_stage` directly to `END_OF_LIFE` (recalls bypass secondary use entirely), releases any host slot to `EMPTY` and decrements `charging_battery_count` if the battery was `CHARGING`, decrements `idle_battery_count` if it was `IDLE`, and writes a `RECALL_APPLIED` audit row. A recall targeting a battery already in `IN_USE` cannot succeed — the install pathway wins the race and the recall is rejected with `ERR_BATTERY_RECALLED`.

### 3.7. Billing: Provisional, Final, Subscriptions, and Refunds

Billing is computed in integer cents from end to end and is invoked in two variants. The **provisional** variant runs at check-in, when the platform must give the member a preview before the swap actually happens. Its inputs are: the per-swap base fee of five hundred cents; the held battery's current `soc_pct` at check-in (used as the provisional incoming SOC); the swap event's `outgoing_soc_pct` (the member-supplied measurement at inspection, defaulting to the previously stored value at check-in if inspection has not yet occurred); the held battery's model's `rated_capacity_kwh`; and the time-of-use rate for the `tou_zone` of the slot that battery came from. The **final** variant runs at swap-complete, takes the swap event's snapshotted `incoming_soc_pct` (the value pinned at install time) in place of the held battery's current SOC, and writes `BillingRecord.amount_due_cents`. Both variants share the same arithmetic skeleton; only the choice of incoming-SOC input differs.

The arithmetic proceeds as follows. The per-swap base component, `per_swap_base_cents`, is the constant five hundred cents. The **SOC delta** is the incoming SOC minus the outgoing SOC, floored at zero — if the incoming SOC is less than or equal to the outgoing SOC, no energy was delivered and the delta is zero. The **energy delivered**, in kilowatt-hours, is the SOC delta divided by one hundred and then multiplied by the battery model's `rated_capacity_kwh`. The **time-of-use rate** in cents per kilowatt-hour is forty for `PEAK`, twenty-five for `SHOULDER`, and fifteen for `OFF_PEAK`. The **SOC-difference component**, `soc_diff_cents`, is the energy delivered multiplied by the time-of-use rate multiplied by the markup factor 1.20, with the product rounded half-up to a whole cent. The **time-of-use pass-through component**, `tou_pass_through_cents`, is the energy delivered multiplied by the time-of-use rate at a flat 1.00 multiplier — pure electricity cost, no markup — again rounded half-up to a whole cent. The **subtotal** is the sum, in this exact order, of `per_swap_base_cents` plus `soc_diff_cents` plus `tou_pass_through_cents`. The **subscription deduction**, `subscription_deduction_cents`, depends on `subscription_tier`: zero cents for `NONE`, five hundred cents for `BASIC`, and one thousand five hundred cents for `PREMIUM` — and it is applied only when the member's `subscription_swaps_remaining` is strictly greater than zero at the moment of computation; when the counter is zero, the deduction is zero regardless of tier. The **amount due**, `amount_due_cents`, is the subtotal minus the subscription deduction, floored at zero so that the final amount is never negative. All component rounding is half-up to whole cents and is performed per component before summation; the deduction is the last subtraction.

A billing record is created at swap-complete with `payment_status` defaulting to `PENDING`. The member can pay it, moving `payment_status` from `PENDING` to `PAID` and emitting a `PAYMENT_OK` event; or the platform may mark it failed (admin-only, system-initiated path), moving `payment_status` from `PENDING` to `FAILED`. A paid record can be refunded by an administrator: the request carries `refund_cents`, which must be strictly greater than zero and at most equal to `amount_due_cents`; out-of-bounds values are rejected with `ERR_REFUND_EXCEEDS_PAID`. A successful refund writes the supplied amount to `refund_cents` and sets `payment_status` to `REFUNDED`. If the refund is a full refund — `refund_cents` equals `amount_due_cents` — and a `subscription_deduction_cents` was applied at swap-complete, the platform restores the member's `subscription_swaps_remaining` by adding one to it; partial refunds do not restore the credit. This compensating action conserves total subscription credits across the round trip of "swap completed → swap fully refunded".

### 3.8. The Audit Trail and Test-Only Capabilities

Every status change on a `Battery`, `Reservation`, `SwapEvent`, or `DispatchOrder`, every recall application, and every phase transition on a swap event produces an `AuditLog` row. The catalogue of `event_type` values is fixed: `BATTERY_STATUS_CHANGE`, `SWAP_PHASE_CHANGE`, `DISPATCH_CHANGE`, `RECALL_APPLIED`, and `RESERVATION_CHANGE`. Admin listings of the audit log accept filters on `entity_type`, `entity_id`, and `event_type`, alongside pagination.

Two administrative test-only capabilities support deterministic exercise of time-dependent behaviour. A clock-advance capability accepts `to_iso` and moves the platform's logical clock forward to that instant — every subsequent comparison against "now" uses the advanced value. A no-show sweep capability iterates every `BOOKED` reservation whose `slot_end_at` has elapsed and applies the no-show cascade described in §3.3 (transition to `NO_SHOW`, release `held_battery_id`, recompute `no_show_count_30d`, and, when the count reaches three, set `reservation_blocked_until` to seventy-two hours from now). Both capabilities are admin-only.

## 4. Endpoint Definitions

The platform exposes the following endpoints, all rooted under the `/swap-stations` mount. Endpoints that create a new resource return HTTP 201 with the new resource in `data`; endpoints that read or modify an existing resource return HTTP 200. Authorisation is enforced from the role list in the final column — when more than one role is listed, each role may invoke the endpoint subject to the ownership scoping described in §2.1. The request body, query parameters, and full set of side effects for each endpoint are documented in §3 — readers must reconstruct them from the workflow prose rather than from this table.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /stations | Register a station | PlatformAdmin |
| GET | /stations | List stations with pagination and optional status filter | PlatformAdmin, StationOperator, Member |
| GET | /stations/{id} | Get station detail with idle/charging counts | PlatformAdmin, StationOperator, Member |
| POST | /stations/{id}/charging-slots | Add a charging slot to a station | PlatformAdmin |
| GET | /stations/{id}/charging-slots | List charging slots at a station | PlatformAdmin, StationOperator |
| POST | /battery-models | Register a battery model | PlatformAdmin |
| POST | /vehicle-models | Register a vehicle model | PlatformAdmin |
| POST | /compatibility-rules | Declare compatibility between a vehicle model and battery model | PlatformAdmin |
| GET | /compatibility-rules | Query compatibility rules (filter by vehicle_model_code) | PlatformAdmin, StationOperator, Member |
| POST | /batteries | Register a battery on a station (status starts IDLE) | PlatformAdmin |
| GET | /batteries | List batteries with filters | PlatformAdmin, StationOperator |
| GET | /batteries/{id} | Battery detail including soh, cycle_count, cascade_stage | PlatformAdmin, StationOperator, Member |
| POST | /batteries/{id}/start-charging | Move IDLE battery into a CHARGING slot | StationOperator |
| POST | /batteries/{id}/finish-charging | Complete charge cycle; runs SOH assessment and may auto-retire | StationOperator |
| POST | /batteries/{id}/report-fault | Mark battery FAULT | StationOperator |
| POST | /batteries/{id}/clear-fault | Return FAULT battery to IDLE | StationOperator |
| POST | /batteries/{id}/grade-cascade | Assign cascade_stage to a RETIRED battery | PlatformAdmin |
| POST | /batteries/{id}/recycle | Move RETIRED battery (END_OF_LIFE cascade) to RECYCLED | PlatformAdmin |
| GET | /batteries/{id}/soh-assessments | List SOH assessments for a battery | PlatformAdmin, StationOperator |
| POST | /vehicles | Register a vehicle | Member, PlatformAdmin |
| GET | /vehicles/{id} | Vehicle detail | Member, PlatformAdmin, StationOperator |
| POST | /members | Register a member | PlatformAdmin |
| GET | /members/{id} | Member detail including no_show_count_30d and reservation_blocked_until | Member, PlatformAdmin |
| POST | /reservations | Create a reservation; soft-holds an IDLE compatible battery | Member, StationOperator |
| GET | /reservations | List reservations with filters | Member, StationOperator, PlatformAdmin |
| GET | /reservations/{id} | Reservation detail | Member, StationOperator, PlatformAdmin |
| POST | /reservations/{id}/check-in | Vehicle has arrived; reservation -> CHECKED_IN and SwapEvent created | StationOperator |
| POST | /reservations/{id}/cancel | Cancel a BOOKED reservation; soft-release held battery | Member, StationOperator |
| POST | /reservations/walk-in | Create a walk-in reservation immediately (queue-aware) | StationOperator |
| GET | /swap-events/{id} | Get swap event detail | StationOperator, PlatformAdmin, Member |
| POST | /swap-events/{id}/inspect | Record pre-swap inspection (outgoing SOC) | StationOperator |
| POST | /swap-events/{id}/uninstall | Remove outgoing battery from vehicle; place into station inventory | StationOperator |
| POST | /swap-events/{id}/install | Install incoming battery into vehicle; verify BMS handshake | StationOperator |
| POST | /swap-events/{id}/complete | Finalize swap and create BillingRecord | StationOperator |
| POST | /swap-events/{id}/abort | Abort an in-progress swap (compensating action) | StationOperator |
| POST | /dispatch-orders | Create a cross-station dispatch order | PlatformAdmin |
| POST | /dispatch-orders/{id}/dispatch | Begin transit (battery -> IN_TRANSIT) | PlatformAdmin |
| POST | /dispatch-orders/{id}/deliver | Arrival at destination (battery -> IDLE at dest_station) | PlatformAdmin |
| POST | /dispatch-orders/{id}/cancel | Cancel a REQUESTED dispatch | PlatformAdmin |
| POST | /recalls | Manufacturer recall affecting specific serial numbers | PlatformAdmin |
| GET | /billing-records | List billing records | Member, PlatformAdmin |
| GET | /billing-records/{id} | Billing record detail | Member, PlatformAdmin |
| POST | /billing-records/{id}/pay | Mark billing as PAID (mock payment-system event) | Member |
| POST | /billing-records/{id}/mark-failed | Mark billing as FAILED (system-only) | PlatformAdmin |
| POST | /billing-records/{id}/refund | Refund a PAID billing record | PlatformAdmin |
| GET | /audit-logs | List audit logs | PlatformAdmin |
| POST | /_clock/advance | Test-only: advance the server clock | PlatformAdmin |
| POST | /_sweep/no-show | Test-only: run the no-show sweep that flips BOOKED -> NO_SHOW for expired reservations | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_BATTERY_RECALLED | 409 |
| ERR_INCOMPATIBLE_MODEL | 422 |
| ERR_INVALID_TIME_SLOT | 422 |
| ERR_RESERVATION_OVERLAP_MEMBER | 409 |
| ERR_STATION_CAPACITY_FULL | 409 |
| ERR_NO_COMPATIBLE_BATTERY | 409 |
| ERR_MEMBER_BLOCKED | 403 |
| ERR_REFUND_EXCEEDS_PAID | 422 |
| ERR_BATTERY_NOT_IDLE | 409 |
| ERR_INVALID_DISPATCH | 422 |
| ERR_INVALID_PAGINATION | 422 |
| ERR_DUPLICATE_RESOURCE | 409 |
| ERR_INVALID_INPUT | 422 |

# Warming & Cooling Center Operations API — Product Requirements Document

## 1. Introduction

When a heat dome settles over a county or a polar air mass drives overnight temperatures below safe levels, municipalities open warming and cooling centers — often with only a few hours of lead time. The operating picture is deliberately chaotic: a network of borrowed facilities with different bed counts, kennel space and storage; a roster of staff and volunteers whose credentials vary; guests who must be admitted with minimal barriers, sometimes arriving with pets and everything they own; vans shuttling unsheltered residents from outreach encounters; donated meals that must stretch across an uncertain census; and, eventually, an orderly stand-down with a defensible after-action record. Today this is coordinated over phone trees and spreadsheets, and the failure modes are exactly the ones an Emergency Operations Center cannot afford: a site opened without overnight lead coverage, a guest turned away while beds sit reserved for a van that never arrived, a reporter closing out their own incident.

This document specifies the API for a warming & cooling center operations platform that replaces that improvisation with deterministic state and capacity accounting. The platform models an activation **Episode** from surveillance through stand-down to closure; drives activation decisions from a sustained weather-breach trigger evaluated over an append-only stream of readings; maintains per-facility quota pools for beds, pet kennel slots, belonging lockers and vehicle seats; supports minimal-barrier guest intake, reservation-by-transport, transfers and no-show expiry; tracks donations, meal stock and meal services; escalates medical and behavioral incidents under segregation of duties; and closes every episode with a pinned, approvable after-action report. All endpoints are mounted under `/api`. The intended readership is the engineering team implementing the service; every rule below is a contract, and the narrative sections are written so that the complete behavior can be reconstructed from this document alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or presenting a role that is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- `EOCManager` — the emergency operations center manager; owns the episode lifecycle (creation, weather-reading intake, trigger evaluation, activation, extension, deactivation, ops sweeps), the site registry, the staff roster, the after-action workflow, and the logical clock.
- `SiteLead` — the activation floor manager; opens and closes sites, plans and confirms shifts, receives donations, runs meal services, and handles `BEHAVIORAL` incidents.
- `IntakeStaff` — the front-desk intake worker; registers guests and runs the stay lifecycle (walk-in intake, check-in, check-out, transfer).
- `OutreachWorker` — field outreach to unsheltered residents; requests transport dispatches and may cancel them.
- `MedicalResponder` — the medical escalation authority; triages, escalates and resolves `MEDICAL` incidents.
- `TransportCoordinator` — the fleet dispatcher; registers vehicles and assigns and arrives dispatches, and may also cancel them.

All six roles may use every read (GET) endpoint. Incident reporting is shared by `SiteLead`, `IntakeStaff`, `OutreachWorker` and `MedicalResponder`; `EOCManager` and `TransportCoordinator` do not report incidents. For incident escalation and resolution the caller's role must additionally match the incident's `kind` — a `MEDICAL` incident is handled only by a `MedicalResponder`, a `BEHAVIORAL` incident only by a `SiteLead` — and a role that mismatches the kind is rejected with `ERR_FORBIDDEN` even though that role may appear on the endpoint's authorized list.

Identity semantics differ by role. When `X-User-Role` is `SiteLead`, `IntakeStaff`, `OutreachWorker` or `MedicalResponder`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership and segregation checks on any resource that references a `StaffMember` (for example, the shift-confirmation check against `staff_member_id`) compare the resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `EOCManager` or `TransportCoordinator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `activated_by_user_id` on the episode, `submitted_by_user_id` or `approved_by_user_id` on the after-action report) but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; it is taken from the wall clock, not from the logical clock of §2.4.
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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. A `limit` that is not an integer or falls outside 1–100, or an `offset` that is not an integer or is negative, is rejected with `ERR_VALIDATION`. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count` and `has_more`, where `has_more` is true exactly when `offset` plus the size of the returned page is still below `total_count`. List results are sorted by `created_at` ascending unless a more specific ordering rule applies — the one exception is an episode's weather-reading listing, which returns readings ordered by `observed_at` ascending with `created_at` ascending as the tie-break. Because the logical clock can stamp many resources with the same `created_at`, any residual tie on an ordering key breaks by insertion order.

### 2.4. The Logical Clock and Time Semantics

All time in the platform flows from a single logical clock. On startup the logical clock is set to exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. An `EOCManager`-only test-driving capability replaces the logical clock with a caller-supplied `to_iso8601` instant and answers with the resulting `current_utc`. Every system-stamped timestamp in this document — `created_at`, `updated_at`, `activated_at`, `deactivated_at`, `opened_at`, `checked_in_at`, `checked_out_at`, `arrived_at` — reads the logical clock at the moment of the mutation, and every time-based rule (no-show grace, shift completion, overnight windows, midnight crossings) is evaluated against the logical clock rather than any wall clock.

Time-window fields throughout the API are half-open intervals: the start instant is inclusive and the end instant is exclusive. A shift that ends at exactly 02:00 and another that starts at exactly 02:00 therefore do not overlap — touching endpoints never intersect.

### 2.5. Resource Identity, Timestamps and Versioning

Every resource carries an `id` that is a server-minted UUID with no type prefix. Resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and an integer `version` that starts at 1 at creation. The `version` increments by one on every mutation of the resource, and `updated_at` refreshes on the same occasions; pure status transitions count as mutations and advance both.

One entity is deliberately exempt: a weather reading is an append-only event log entry carrying only `id` and `created_at`. It has no `updated_at`, no `version`, and no update or delete endpoint — once appended, a reading is immutable.

### 2.6. Capacity Pools and Bed Conservation

Each site activation maintains a live quota picture computed from its stays. `occupied_beds` counts the activation's stays in `CHECKED_IN`; `reserved_beds` counts those in `RESERVED`; `beds_free` is `beds_effective` minus `occupied_beds` minus `reserved_beds`. The bed-conservation invariant — `beds_effective` always equals `occupied_beds` plus `reserved_beds` plus `beds_free` — holds at all times. `beds_effective` itself is pinned the first time the activation opens: it takes the designated `capacity_override` when one was supplied, otherwise the site's `bed_capacity` at that moment, and a later amendment of the site's registry capacity does not retro-change an already-pinned value. Until that first successful open, `beds_effective` — and therefore `beds_free` — is null.

The pet and locker pools, by contrast, always read the site's live registry values. `pet_slots_free` is the site's `pet_capacity` minus the sum of `pet_slots_used` over the activation's stays in `RESERVED` or `CHECKED_IN`; `lockers_free` is the site's `locker_capacity` minus the sum of `lockers_used` over the same two statuses. Stays in `CHECKED_OUT`, `NO_SHOW`, `CANCELLED` or `TRANSFERRED_OUT` hold nothing. Usage is pinned at intake and never drifts with later guest-profile edits: `pet_slots_used` is the guest's `pet_count` at the intake moment, and `lockers_used` is the guest's `bag_count` divided by two and rounded up — one locker shelters two bags, and an odd bag still claims a whole locker.

Consistency is immediate: every computed field described in this document recomputes within the same request that mutates any of its inputs, so a read issued after a mutation never observes a stale pool, coverage figure or stock level.

### 2.7. Numeric Precision, Rounding and Threshold Inclusivity

Durations are whole minutes: datetime arithmetic is exact to the second and then floored to whole minutes. Bed-night counts and supply units are integers. Two computations round up to the next whole unit — the per-stay locker pin (bags divided by two, ceiling) and the per-service meal plan (attendance times the period buffer, ceiling) — and each rounds its own line individually before any cross-line total is taken. The weather trigger's breach thresholds are inclusive on both modes: a reading equal to the threshold is a breach. Wherever this document says "at least" or "at most", the boundary value satisfies the condition.

### 2.8. Optimistic Concurrency Control

Two write endpoints are guarded by optimistic concurrency control, and each takes a mandatory version field naming the client's last-observed `version` of the parent entity:

- `POST /api/episodes/{episode_id}/extensions` requires `expected_episode_version`, compared against the episode's current `version`.
- `PATCH /api/sites/{site_id}` requires `expected_site_version`, compared against the site's current `version`.

Within the guard, the version field is first validated for presence and integer type — a missing or non-integer value fails with `ERR_VALIDATION` — and both this validation and the staleness comparison run before the endpoint's state guards and remaining payload checks. When the supplied value does not match the entity's current `version` — because another writer has advanced the version since the client last read the entity — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This is a deterministic stale-version check: extensions are otherwise always legal while an episode is `ACTIVE`, and site capacity edits are otherwise always legal, so without the guard a second sequential write carrying an outdated read would silently overwrite a decision the client never observed. Endpoints not listed above take no version field.

### 2.9. Validation Order and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed order and reports the first failure. Authentication comes first: missing or invalid headers yield `ERR_UNAUTHENTICATED`. Authorization is second: a role outside the endpoint's role list yields `ERR_FORBIDDEN`; the incident kind-matching role check of §2.1 also yields `ERR_FORBIDDEN`, and it is applied once the incident's existence has been established and before the incident's state guard. Existence is third: path identifiers are validated left to right, a nested child must belong to its path parent, and body-referenced identifiers (such as `site_id`, `guest_id`, `staff_member_id`, `vehicle_id`, `target_site_activation_id` and every element of `guest_ids`) must exist, with any failure yielding `ERR_NOT_FOUND`. Fourth are the optimistic-concurrency checks of §2.8, yielding `ERR_STALE_VERSION`. Fifth are state guards, evaluated parents-first — episode before site activation before stay or dispatch — yielding the transition-specific codes (`ERR_INVALID_STATE`, `ERR_EPISODE_NOT_ACTIVE`, `ERR_SITE_NOT_OPEN`, `ERR_TRIGGER_NOT_MET`, `ERR_DISPATCH_NOT_ARRIVED`, and `ERR_VALIDATION` for a pinned bed capacity below one at open); a malformed payload — a missing required field, an unknown enum value, a type mismatch — also fails with `ERR_VALIDATION` (HTTP 400). Sixth are safety gates: an active guest medical hold and a missing shift skill. Seventh are uniqueness and segregation constraints: one active stay per guest per episode, one after-action report per episode, the three segregated pairs, staff shift overlap, vehicle window conflicts, same-episode transfer, the designated-site requirement at activation, and the incident/site gates on report submission. Eighth is temporal shape: windows whose end is not strictly after their start. Ninth and last are the capacity pools, always checked in the pinned order beds, then pets, then lockers.

## 3. Business Logic & Workflows

### 3.1. Weather Surveillance and the Activation Trigger

An activation episode begins in surveillance. An `EOCManager` creates it by supplying a `mode` of `WARMING` or `COOLING`, a `threshold_f` breach threshold in Fahrenheit, a `sustained_hours_required` of at least one hour, and a planned `scheduled_end_at`. The `mode` selects which metric is watched: a warming episode breaches on air temperature, a cooling episode on heat index. A new episode stands in `STANDBY` with `trigger_met` false, `breach_run_minutes` zero, `extension_count` zero and `ops_run_index` zero.

Weather surveillance feeds the episode as an append-only log. Each appended reading records `observed_at` (when the observation was taken), `temp_f`, `heat_index_f` and an optional `source` of `NWS` or `MANUAL`, defaulting to `MANUAL` when omitted; the reading's `episode_id` ties it to the owning episode. Readings may arrive out of order — the evaluation sort normalizes them — and every append immediately recomputes the breach evaluation described below, refreshing `trigger_met` and `breach_run_minutes`. Readings may be appended in any episode state; the breach recompute, whether triggered by an append or by a read of the episode, never advances the episode's `version` or `updated_at`.

The breach-run evaluation walks all of the episode's readings ordered by `observed_at` ascending, tie-broken by `created_at` ascending, regardless of `source`. A reading qualifies as a breach when, on a `COOLING` episode, its `heat_index_f` is at least `threshold_f`, or, on a `WARMING` episode, its `temp_f` is at most `threshold_f`; both comparisons are inclusive. The walk maintains a single current run. A non-breach reading resets the run to empty. A breach reading encountered while no run is live starts a new run anchored at its own `observed_at`. A breach reading whose gap from the previous breach reading's `observed_at` is at most fifteen minutes extends the live run to its own `observed_at` — a gap of exactly fifteen minutes keeps the run alive, while sixteen minutes breaks it. A breach reading arriving after a larger gap abandons the old run and starts a fresh one at its own instant; abandoned runs are forgotten. When the walk ends with no live run, `breach_run_minutes` is zero and `trigger_met` is false. Otherwise `breach_run_minutes` is the live run's length in minutes from its first breach reading to its last, and `trigger_met` is true exactly when that length reaches `sustained_hours_required` multiplied by sixty minutes — a run of exactly the required duration qualifies.

Trigger evaluation by an `EOCManager` recomputes the breach run first and then decides the transition. From `STANDBY` with `trigger_met` true the episode advances to `ACTIVATING`. From `ACTIVATING` with `trigger_met` false it stands back down to `STANDBY`, mutating no other entity — this surveillance cycle may repeat indefinitely as fronts stall and rebuild. From `DEACTIVATING` with the trigger newly re-met, the episode re-surges to `ACTIVE` — keeping the `deactivated_at` stamp of the drain it recovers from — and each of its site activations sitting in `DRAINING` returns to `OPEN` in `created_at` ascending order, intake re-enables there, stays already cancelled are not resurrected, and closed activations stay closed. Evaluation attempted while the episode is `ACTIVE`, `DEACTIVATED` or `CLOSED` is rejected with `ERR_INVALID_STATE`.

Formal activation moves the episode from `ACTIVATING` to `ACTIVE`. It is refused with `ERR_TRIGGER_NOT_MET` when `trigger_met` is false at activation time, and with `ERR_NO_SITES_DESIGNATED` when the episode has no site activation in `OPENING` or `OPEN`. The first successful activation stamps `activated_at` from the logical clock and captures the caller's identity in `activated_by_user_id`; reactivations after a drain keep those original stamps. The captured activator matters later — it is the identity the after-action approver must differ from.

### 3.2. Site Registry, Designation and the Opening Gates

Facilities live in a site registry maintained by the `EOCManager`. Registering a site records its `name`, `address` and three non-negative capacities: `bed_capacity` guest beds, `pet_capacity` kennel slots and `locker_capacity` belonging bins. Capacity amendments are made through the OCC-guarded amendment endpoint (§2.8) and never retro-change a bed cap already pinned by an opened activation — they move only the live registry values that future opens and the pet and locker pools read. A PATCH that passes the OCC guard advances the site's `version` and `updated_at` even when no supplied field changes a value.

While an episode is in `STANDBY`, `ACTIVATING` or `ACTIVE`, the `EOCManager` designates a facility for it by creating a site activation carrying the `site_id` and an optional non-negative `capacity_override` for an episode-specific bed cap; designation in any other episode state is rejected with `ERR_INVALID_STATE`. A new site activation stands in `OPENING`: known to the network, not yet admitting anyone. The site-activation listing can be filtered by `episode_id`, `site_id` and `status`.

Opening the floor is a `SiteLead` action guarded by five checks, evaluated in this order. The episode must be `ACTIVE`, else `ERR_EPISODE_NOT_ACTIVE`. The activation must still stand in `OPENING`, else `ERR_INVALID_STATE`. The bed capacity about to be pinned must be at least one, else `ERR_VALIDATION` — this check runs before the two coverage checks. The overnight coverage gap must be fully closed — `overnight_coverage_gap_minutes` exactly zero — else `ERR_OVERNIGHT_COVERAGE_GAP`; this check is evaluated before the lead-coverage check. A confirmed site-lead shift must fully contain tonight's overnight window — `lead_coverage_ok` true — else `ERR_LEAD_COVERAGE_MISSING`. On the first successful open, `beds_effective` is pinned — to `capacity_override` when one was designated, otherwise to the site's `bed_capacity` at that moment — and `opened_at` is stamped from the logical clock. The pinned value is frozen against later registry amendments.

A `DRAINING` activation returns to `OPEN` only through the episode-level re-surge described in §3.1; there is no direct reopen action.

Closing is a `SiteLead` action available from `OPENING` or `DRAINING`, and only when no stay of the activation remains in `RESERVED` or `CHECKED_IN` — otherwise the close is rejected with `ERR_STAYS_STILL_ACTIVE`. A successful close moves the activation to `CLOSED` and cancels every one of its shifts still `PLANNED` or `CONFIRMED`. When the episode is `DEACTIVATING` and this close removes the last non-closed activation, the episode itself settles to `DEACTIVATED` immediately, without waiting for an ops sweep.

### 3.3. Roster Management, Shifts and Overnight Coverage

The staff roster is maintained by the `EOCManager`. Each `StaffMember` carries a display `full_name`, a `skills` array drawn from `INTAKE`, `MEDICAL`, `OUTREACH`, `SITE_LEAD` and `DRIVER`, and an `active` flag that defaults to true; an inactive member cannot be assigned new shifts. The roster listing can be filtered by `active`; the filter accepts only the case-insensitive values `true` and `false` — anything else is rejected with `ERR_VALIDATION`.

Shift planning is a `SiteLead` action available while the activation is `OPENING` or `OPEN` — planning elsewhere is rejected with `ERR_INVALID_STATE`. A planned shift names the `staff_member_id`, a `role_on_shift` of `INTAKE`, `MEDICAL`, `OUTREACH`, `SITE_LEAD` or `GENERAL`, and a half-open window from `start_at` (inclusive) to `end_at` (exclusive); an `end_at` that is not strictly after `start_at` is rejected with `ERR_INVALID_WINDOW`. A new shift stands in `PLANNED`.

Confirmation is the gate that makes a shift count toward coverage. The shift's activation must still stand in `OPENING` or `OPEN` and the shift itself in `PLANNED`, else `ERR_INVALID_STATE`; then four checks run in this order. The staff member must be `active`, else `ERR_INVALID_STATE`. A `role_on_shift` other than `GENERAL` must appear in the staff member's `skills`, else `ERR_SKILL_MISMATCH`. The caller's `X-User-ID` must differ from the shift's `staff_member_id` — nobody confirms their own shift — else `ERR_SEGREGATION_OF_DUTIES`. And no other `CONFIRMED` shift of the same staff member may intersect this one's half-open window — shifts whose endpoints merely touch do not intersect — else `ERR_SHIFT_OVERLAP`. A `SiteLead` may cancel a shift from either `PLANNED` or `CONFIRMED`; cancelling a confirmed shift reopens whatever coverage it carried. The shift listing filters by `site_activation_id`, `staff_member_id` and `status`.

Tonight's overnight window is the half-open interval from 22:00 on the current logical-clock day to 06:00 the following day — 480 minutes. Coverage math considers only `CONFIRMED` shifts of the activation; `PLANNED`, `CANCELLED` and `COMPLETED` shifts contribute nothing. Each confirmed shift's window is intersected with the overnight window, the non-empty pieces are merged as half-open intervals — overlapping or merely touching pieces merge seamlessly — and `overnight_coverage_gap_minutes` is 480 minus the total covered minutes. `lead_coverage_ok` is true exactly when some `CONFIRMED` shift with `role_on_shift` `SITE_LEAD` fully contains the window, meaning its `start_at` is at or before 22:00 and its `end_at` is at or after 06:00 the next day. Both figures recompute on every shift create, confirm or cancel, on the activation's open, and during the ops sweep; shift completion itself happens only in the sweep (§3.8).

### 3.4. Guest Registration and the Stay Lifecycle

Guest registration is minimal-barrier by design: an `IntakeStaff` registers a guest with an `alias` and nothing more is ever required — no legal name, no identification. Optional profile fields default sensibly: `has_pets` false, `pet_count` zero (non-negative, and it must be zero whenever `has_pets` is false, while `has_pets` true with a zero `pet_count` is permitted), `bag_count` zero (non-negative), and `medical_flag` false for a self-declared vulnerability. A guest's `medical_hold_active` starts false and is thereafter computed from the incident workflow (§3.7).

Walk-in intake creates a stay directly in `CHECKED_IN`. The activation must be `OPEN`, else `ERR_SITE_NOT_OPEN`. The guest must carry no active medical hold, else `ERR_GUEST_MEDICAL_HOLD`. The guest must not already hold a stay in the same episode in `RESERVED` or `CHECKED_IN`, else `ERR_GUEST_ALREADY_HAS_ACTIVE_STAY`. Capacity is then checked in a pinned order — beds, then pets, then lockers: at least one free bed, else `ERR_NO_BED_AVAILABLE`; the guest's `pet_count` within `pet_slots_free`, else `ERR_PET_CAPACITY_EXCEEDED`; and the guest's locker demand — `bag_count` divided by two and rounded up — within `lockers_free`, else `ERR_LOCKER_CAPACITY_EXCEEDED`. Successful intake stamps `checked_in_at` from the logical clock, pins `pet_slots_used` to the guest's `pet_count` and `lockers_used` to the rounded locker demand at that moment, and debits all three pools. A walk-in's `transport_dispatch_id` is null and its `transfer_sequence` is zero; stays born of transport reservations (§3.5) instead begin in `RESERVED` with the dispatch linkage set.

Check-in moves a `RESERVED` stay to `CHECKED_IN`. The linked dispatch must have arrived, else `ERR_DISPATCH_NOT_ARRIVED`, and the medical-hold gate applies again. The transition stamps `checked_in_at` and moves the stay's bed accounting from reserved to occupied. Check-out moves a `CHECKED_IN` stay to `CHECKED_OUT`, stamps `checked_out_at`, computes the final bed-night figure, and releases the bed, pet and locker usage back to the pools.

Transfer moves a checked-in guest between activations of the same episode. The request names a `target_site_activation_id`. The checks run in this order: the source stay must be `CHECKED_IN`, else `ERR_INVALID_STATE`; the target must be `OPEN`, else `ERR_SITE_NOT_OPEN`; the medical-hold gate applies; the target must belong to the same episode as the source, else `ERR_CROSS_EPISODE_TRANSFER`; and the target's capacity is checked in the same pinned order — at least one free bed, `pet_slots_free` at least the stay's pinned `pet_slots_used`, and `lockers_free` at least the pinned `lockers_used`. A successful transfer moves the source stay to `TRANSFERRED_OUT` with `checked_out_at` stamped and its final bed nights computed, releases the source pools, and creates a successor stay at the target already in `CHECKED_IN`, carrying the same `guest_id`, the same pinned `pet_slots_used` and `lockers_used`, a null `transport_dispatch_id`, a `transfer_sequence` one higher than the source's, and a fresh `checked_in_at`; the response carries the newly created successor stay.

Bed nights come in two variants, both counting 00:00:00Z midnight boundaries. The final variant, `bed_nights_final`, counts the midnight instants that are strictly after `checked_in_at` and at or before `checked_out_at`; it is computed the moment a stay leaves `CHECKED_IN` — by check-out, by behavioral ejection, or by transfer — and it remains null while the stay is still checked in, as it does for reserved stays that never reach check-in. The provisional variant, `bed_nights_provisional`, is live on every read: it counts the midnight boundaries from `checked_in_at` up to the logical-clock now and adds one extra night for the in-progress night while the stay is still `CHECKED_IN`, so the provisional figure is always at least the final figure for the same stay; a stay that never reached check-in reports `bed_nights_provisional` zero. The stays listing can be filtered by `site_activation_id`, `guest_id`, `transport_dispatch_id` and `status`.

A reserved stay can also end without the guest ever arriving: the episode's deactivation cascade cancels it (§3.8), a dispatch cancellation cancels it (§3.5), or the ops sweep expires it to `NO_SHOW` once the pickup has waited out its grace period (§3.8). Every one of those paths releases its bed, pet and locker usage.

### 3.5. Outreach Transport and Dispatch Reservations

The fleet is registered by the `TransportCoordinator`. Each vehicle carries a call-sign `label`, a passenger `seats` count of at least one, and a `turnaround_minutes` buffer — defaulting to thirty minutes and never negative — that must be honored around every dispatch window assigned to it.

An `OutreachWorker` requests a transport dispatch by naming the destination `site_activation_id`, the riders as a `guest_ids` array of at least one guest — the rider count is the array's length — a half-open pickup window from `pickup_window_start` (inclusive) to `pickup_window_end` (exclusive) — an end not strictly after the start is rejected with `ERR_INVALID_WINDOW` — and an optional `has_pets` flag defaulting to false. The destination activation must be `OPEN`, else `ERR_SITE_NOT_OPEN`. A new dispatch stands in `REQUESTED` with `reserved_bed_count` zero and `vehicle_id` still null, and the caller's identity is captured in `requested_by_user_id`.

Assignment is a `TransportCoordinator` action supplying the `vehicle_id`, and it is the reservation gate. The checks run in this order: the destination must still be `OPEN`, else `ERR_SITE_NOT_OPEN`; the dispatch must still stand in `REQUESTED`, else `ERR_INVALID_STATE`; no rider may already hold a stay in this episode in `RESERVED` or `CHECKED_IN`, else `ERR_GUEST_ALREADY_HAS_ACTIVE_STAY`; the vehicle must have no window conflict — if it is already assigned to another dispatch still in `ASSIGNED` whose pickup window, expanded by `turnaround_minutes` on both sides, intersects the new window, the assignment is rejected with `ERR_VEHICLE_WINDOW_CONFLICT`; and the vehicle's `seats` must be at least the rider count, else `ERR_VEHICLE_TOO_SMALL`. Finally the destination's capacity must absorb the whole party, all-or-nothing, checked in the pinned order: free beds at least the rider count, else `ERR_INSUFFICIENT_BEDS_FOR_DISPATCH`; when `has_pets` is set, the riders' combined `pet_count` within `pet_slots_free`, else `ERR_PET_CAPACITY_EXCEEDED`; and the riders' combined locker demand — each guest's `bag_count` divided by two and rounded up, summed — within `lockers_free`, else `ERR_LOCKER_CAPACITY_EXCEEDED`. On success the dispatch moves from `REQUESTED` to `ASSIGNED`, `vehicle_id` is set, `reserved_bed_count` becomes the rider count, and one `RESERVED` stay per rider is created at the destination with intake-style pinned `pet_slots_used` and `lockers_used` and the stay's `transport_dispatch_id` pointing back at the dispatch.

Arrival moves an `ASSIGNED` dispatch to `ARRIVED`: `arrived_at` is stamped from the logical clock, the vehicle's window occupation ends, and the reserved stays become eligible for check-in. Arrival is the terminal success state; it also starts the no-show clock — a reserved stay whose guest never checks in is expired by the ops sweep once the logical clock reaches sixty minutes past the dispatch's `arrived_at` (§3.8).

Cancellation is available to both the `OutreachWorker` and the `TransportCoordinator`. Cancelling a still-`REQUESTED` dispatch has no further effect. Cancelling an `ASSIGNED` dispatch cancels every linked stay still in `RESERVED` — releasing its bed, pet and locker usage — drops `reserved_bed_count` to zero, and ends the vehicle's window occupation just as arrival does. The dispatch listing filters by `site_activation_id`, `vehicle_id` and `status`.

### 3.6. Donations, Meal Stock and Meal Services

Partner provisioning is tracked per activation; donations and meal services are recorded, received, planned and served regardless of the activation's status — none of these endpoints gates on it. A `SiteLead` records a donation pledge with the `partner_name`, a `category` of `MEAL`, `WATER`, `BEDDING`, `HYGIENE` or `PET_SUPPLIES`, and a `quantity` of at least one — for the `MEAL` category one unit is one meal. A pledge stands in `PLEDGED` until the same role confirms receipt, moving it to `RECEIVED`. The donation listing filters by `status` and `category`.

Two stock figures are computed from the `MEAL` pipeline. `meal_stock_on_hand` is the sum of `quantity` over the activation's `RECEIVED` meal donations minus the `served_count` totals of its `SERVED` meal services — the physical stock that serving is gated against. `meal_stock_projected` adds the `quantity` of meal donations still in `PLEDGED` to the on-hand figure, giving planners a forward view that is never below the on-hand value for the same data. Both recompute on every donation pledge or receipt and on every meal service.

Meal services are planned per period. Creating one names a `service_date` — stored and returned exactly as supplied, merely normalized to UTC, with its time component carrying no meaning — and a `meal_period` of `BREAKFAST`, `LUNCH` or `DINNER`, and pins `planned_meals` at the creation moment: the attendance snapshot is `occupied_beds` plus `reserved_beds` at that instant, multiplied by the period buffer — 1.10 for breakfast, 1.15 for lunch, 1.25 for dinner — and rounded up to a whole meal. Each service rounds its own plan individually; any daily or site total is the sum of those per-service rounded values, and rounding the sum of unrounded values instead is not permitted, because it yields a different number.

Serving moves a service from `PLANNED` to `SERVED`. The `SiteLead` reports the non-negative `served_count`, which may not exceed the activation's `meal_stock_on_hand` — otherwise the serve is rejected with `ERR_INSUFFICIENT_MEAL_STOCK` — and a successful serve reduces `meal_stock_on_hand` by exactly `served_count`. The meal-service listing filters by `status`.

### 3.7. Incident Escalation and Guest Safety Holds

Incidents are reported from the floor. A `SiteLead`, `IntakeStaff`, `OutreachWorker` or `MedicalResponder` reports an incident with the `site_activation_id` where it occurred, an optional involved `guest_id`, a `kind` of `MEDICAL` or `BEHAVIORAL`, and a `severity` of 1, 2 or 3. The reporter's identity is captured in `reporter_user_id`, and the incident stands in `REPORTED`. Reporting, escalation and resolution are not gated on the activation's or the episode's status. The `kind` selects the resolver role for the incident's whole lifecycle: `MEDICAL` incidents are escalated and resolved only by a `MedicalResponder`, `BEHAVIORAL` incidents only by a `SiteLead`, and the wrong role is rejected with `ERR_FORBIDDEN`.

Escalation moves an incident from `REPORTED` to `ESCALATED`, with effects that diverge by kind. Escalating a `MEDICAL` incident with a linked guest sets that guest's `medical_hold_active` to true. Escalating a `BEHAVIORAL` incident of severity 3, when the linked guest currently has a `CHECKED_IN` stay at that activation, ejects the guest: the stay moves to `CHECKED_OUT` with `checked_out_at` stamped, its final bed nights computed, and its bed, pet and locker usage released, exactly as a normal check-out. A `BEHAVIORAL` incident of severity 1 or 2 touches no stay.

Resolution moves an incident from `REPORTED` or `ESCALATED` to `RESOLVED`. The resolver must differ from the reporter — the caller's `X-User-ID` may not equal `reporter_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and resolution captures the resolver in `resolved_by_user_id` together with a free-text `resolution_note`. Resolving an escalated `MEDICAL` incident recomputes the guest's hold: `medical_hold_active` falls back to false when no other escalated-and-unresolved `MEDICAL` incident remains for that guest. While a hold is active it blocks three operations — walk-in intake, reservation check-in and transfer — each rejected with `ERR_GUEST_MEDICAL_HOLD`. The incident listing filters by `site_activation_id`, `guest_id`, `status` and `kind`.

### 3.8. Extensions, Deactivation, Ops Sweeps and After-Action Closure

Weather that outlasts the forecast is handled by extension. While the episode is `ACTIVE` — an extension in any other state is rejected with `ERR_EPISODE_NOT_ACTIVE` — an `EOCManager` supplies a `new_scheduled_end_at` that must be strictly later than the current `scheduled_end_at`, else `ERR_INVALID_WINDOW`, together with the OCC guard `expected_episode_version` (§2.8), whose mismatch is rejected with `ERR_STALE_VERSION`. A successful extension replaces `scheduled_end_at`, increments `extension_count` by one, and advances the episode's `version` by one.

Deactivation begins the drain. An `EOCManager` action moves the episode from `ACTIVE` to `DEACTIVATING`, stamps `deactivated_at` from the logical clock, and fires a three-level cascade. At the first level, each of the episode's site activations in `OPEN` moves to `DRAINING`, processed in `created_at` ascending order, while each activation still in `OPENING` moves directly to `CLOSED` with its own close side effects. At the second level, every activation that just drained cancels each of its stays still in `RESERVED` — again in `created_at` ascending order — releasing bed, pet and locker usage; guests already `CHECKED_IN` are not disturbed by the drain. At the third level, each of those cancelled stays that was born of a transport reservation decrements its linked dispatch's `reserved_bed_count` by one, and when that decrement drops the count to zero on a dispatch still `ASSIGNED`, the dispatch itself moves to `CANCELLED`. Should the trigger re-qualify mid-drain, the re-surge of §3.1 returns the episode to `ACTIVE` and its drained activations to `OPEN`; the cancelled reservations stay cancelled.

The ops sweep is the `EOCManager`'s checkpoint capability over a single episode; it may be run in any episode state. Each run increments the episode's `ops_run_index` by one, advances the episode's `version` by one, and executes three steps in a pinned order. First, every `CONFIRMED` shift of the episode whose `end_at` has been reached by the logical clock moves to `COMPLETED`, processed in `created_at` ascending order, recomputing coverage as it goes. Second, every `RESERVED` stay of the episode whose linked dispatch has `ARRIVED` and for which the logical clock has reached sixty minutes past the dispatch's `arrived_at` moves to `NO_SHOW` in `created_at` ascending order, each releasing its bed, pet and locker usage and decrementing its dispatch's `reserved_bed_count`. Third, if the episode is `DEACTIVATING` and every one of its site activations is `CLOSED`, the episode settles to `DEACTIVATED`. The same settling also happens immediately, outside any sweep, at the moment the last non-closed activation closes (§3.2).

The after-action report closes the loop. An `EOCManager` creates it while the episode is `DEACTIVATING` or `DEACTIVATED` — drafting during the drain is deliberate — and creation in any other episode state is rejected with `ERR_INVALID_STATE`; each episode has at most one report, a duplicate creation likewise rejected with `ERR_INVALID_STATE`. At creation the report stands in `DRAFT` and its aggregates are pinned once and for all: `total_unique_guests` counts the distinct `guest_id` values across all of the episode's stays regardless of status; `total_bed_nights` sums `bed_nights_final` across all of the episode's stays, using the final variant only, with a stay whose final figure is still null contributing zero; `meals_served` sums `served_count` across the episode's `SERVED` meal services; `incidents_by_severity` is a map over the keys `"1"`, `"2"` and `"3"` counting every incident of the episode whatever its status; and `transports_arrived` counts the episode's dispatches in `ARRIVED`.

Submission moves the report from `DRAFT` to `SUBMITTED` and is gated on a clean ledger: every incident of the episode must be `RESOLVED`, else `ERR_OPEN_INCIDENTS_REMAIN`, and every site activation must be `CLOSED`, else `ERR_SITES_NOT_CLOSED`. The submitter is captured in `submitted_by_user_id`. Approval moves the report from `SUBMITTED` to `APPROVED` under the final segregation of duties: the approver's `X-User-ID` must differ from the episode's `activated_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Approval stamps `approved_by_user_id` and, as its terminal side effect, closes the episode itself from `DEACTIVATED` to `CLOSED`.

## 4. Endpoint Definitions

Creation of a new resource answers 201 on success; actions and modifications on an existing resource answer 200. All reads answer 200. Failures answer with the status codes catalogued in §5 under the envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/episodes` | Create an activation episode in `STANDBY` | EOCManager |
| GET | `/api/episodes/{episode_id}` | Get one episode | All roles |
| POST | `/api/episodes/{id}/weather-readings` | Append an immutable weather reading; recomputes the breach evaluation | EOCManager |
| GET | `/api/episodes/{id}/weather-readings` | List an episode's readings, `observed_at` ascending with `created_at` tie-break | All roles |
| POST | `/api/episodes/{episode_id}/evaluate` | Evaluate the trigger now and apply the resulting surveillance transition | EOCManager |
| POST | `/api/episodes/{episode_id}/activate` | Move `ACTIVATING` to `ACTIVE` | EOCManager |
| POST | `/api/episodes/{episode_id}/extensions` | Extend `scheduled_end_at` while `ACTIVE` (OCC-guarded) | EOCManager |
| POST | `/api/episodes/{episode_id}/deactivate` | Move `ACTIVE` to `DEACTIVATING` with the full cascade | EOCManager |
| POST | `/api/episodes/{episode_id}/run-ops` | Run the ops checkpoint sweep for the episode | EOCManager |
| POST | `/api/sites` | Register a facility | EOCManager |
| GET | `/api/sites/{site_id}` | Get one site | All roles |
| PATCH | `/api/sites/{site_id}` | Amend site registry fields and capacities (OCC-guarded) | EOCManager |
| POST | `/api/episodes/{episode_id}/site-activations` | Designate a site for the episode; created in `OPENING` | EOCManager |
| GET | `/api/site-activations` | List site activations with filters | All roles |
| GET | `/api/site-activations/{site_activation_id}` | Get one site activation including computed capacity, coverage and stock fields | All roles |
| POST | `/api/site-activations/{site_activation_id}/open` | Move `OPENING` to `OPEN`; pins `beds_effective` | SiteLead |
| POST | `/api/site-activations/{site_activation_id}/close` | Move `OPENING` or `DRAINING` to `CLOSED` | SiteLead |
| POST | `/api/staff-members` | Add a roster member | EOCManager |
| GET | `/api/staff-members` | List the roster | All roles |
| POST | `/api/site-activations/{site_activation_id}/shifts` | Plan a shift in `PLANNED` | SiteLead |
| GET | `/api/shifts` | List shifts with filters | All roles |
| GET | `/api/shifts/{shift_id}` | Get one shift | All roles |
| POST | `/api/shifts/{shift_id}/confirm` | Move `PLANNED` to `CONFIRMED` under the confirmation gates | SiteLead |
| POST | `/api/shifts/{shift_id}/cancel` | Move `PLANNED` or `CONFIRMED` to `CANCELLED` | SiteLead |
| POST | `/api/guests` | Register a guest (minimal barriers) | IntakeStaff |
| GET | `/api/guests/{guest_id}` | Get one guest | All roles |
| POST | `/api/site-activations/{site_activation_id}/stays` | Walk-in intake; creates a stay directly in `CHECKED_IN` | IntakeStaff |
| GET | `/api/stays` | List stays with filters | All roles |
| GET | `/api/stays/{stay_id}` | Get one stay with live `bed_nights_provisional` | All roles |
| POST | `/api/stays/{stay_id}/check-in` | Move `RESERVED` to `CHECKED_IN` | IntakeStaff |
| POST | `/api/stays/{stay_id}/check-out` | Move `CHECKED_IN` to `CHECKED_OUT` | IntakeStaff |
| POST | `/api/stays/{stay_id}/transfer` | Transfer a checked-in guest to another activation of the same episode | IntakeStaff |
| POST | `/api/vehicles` | Register a vehicle | TransportCoordinator |
| GET | `/api/vehicles` | List vehicles | All roles |
| POST | `/api/transport-dispatches` | Request a transport dispatch in `REQUESTED` | OutreachWorker |
| GET | `/api/transport-dispatches` | List dispatches with filters | All roles |
| GET | `/api/transport-dispatches/{dispatch_id}` | Get one dispatch | All roles |
| POST | `/api/transport-dispatches/{dispatch_id}/assign` | Move `REQUESTED` to `ASSIGNED`; reserves beds via `RESERVED` stays | TransportCoordinator |
| POST | `/api/transport-dispatches/{dispatch_id}/arrive` | Move `ASSIGNED` to `ARRIVED` | TransportCoordinator |
| POST | `/api/transport-dispatches/{dispatch_id}/cancel` | Move `REQUESTED` or `ASSIGNED` to `CANCELLED` | OutreachWorker, TransportCoordinator |
| POST | `/api/site-activations/{id}/donations` | Record a partner donation pledge in `PLEDGED` | SiteLead |
| GET | `/api/site-activations/{id}/donations` | List an activation's donations | All roles |
| POST | `/api/donations/{donation_id}/receive` | Move `PLEDGED` to `RECEIVED` | SiteLead |
| POST | `/api/site-activations/{id}/meal-services` | Plan a meal service; pins `planned_meals` | SiteLead |
| GET | `/api/site-activations/{id}/meal-services` | List an activation's meal services | All roles |
| POST | `/api/meal-services/{meal_service_id}/serve` | Move `PLANNED` to `SERVED`; consumes meal stock | SiteLead |
| POST | `/api/incidents` | Report an incident in `REPORTED` | SiteLead, IntakeStaff, OutreachWorker, MedicalResponder |
| GET | `/api/incidents` | List incidents with filters | All roles |
| GET | `/api/incidents/{incident_id}` | Get one incident | All roles |
| POST | `/api/incidents/{incident_id}/escalate` | Move `REPORTED` to `ESCALATED`; role keyed by `kind` | MedicalResponder, SiteLead |
| POST | `/api/incidents/{incident_id}/resolve` | Move `REPORTED` or `ESCALATED` to `RESOLVED` | MedicalResponder, SiteLead |
| POST | `/api/episodes/{id}/after-action-reports` | Create the episode's after-action report in `DRAFT`; aggregates pinned | EOCManager |
| GET | `/api/episodes/{id}/after-action-reports` | List an episode's after-action reports | All roles |
| POST | `/api/after-action-reports/{aar_id}/submit` | Move `DRAFT` to `SUBMITTED` | EOCManager |
| POST | `/api/after-action-reports/{aar_id}/approve` | Move `SUBMITTED` to `APPROVED`; closes the episode | EOCManager |
| POST | `/api/_clock/set_current_utc` | Set the logical clock to a supplied instant | EOCManager |

"All roles" means every declared role of §2.1: `EOCManager`, `SiteLead`, `IntakeStaff`, `OutreachWorker`, `MedicalResponder` and `TransportCoordinator`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TRIGGER_NOT_MET` | 409 |
| `ERR_EPISODE_NOT_ACTIVE` | 409 |
| `ERR_NO_SITES_DESIGNATED` | 409 |
| `ERR_SITE_NOT_OPEN` | 409 |
| `ERR_GUEST_MEDICAL_HOLD` | 409 |
| `ERR_SKILL_MISMATCH` | 409 |
| `ERR_GUEST_ALREADY_HAS_ACTIVE_STAY` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 409 |
| `ERR_SHIFT_OVERLAP` | 409 |
| `ERR_VEHICLE_WINDOW_CONFLICT` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_OVERNIGHT_COVERAGE_GAP` | 409 |
| `ERR_LEAD_COVERAGE_MISSING` | 409 |
| `ERR_NO_BED_AVAILABLE` | 409 |
| `ERR_PET_CAPACITY_EXCEEDED` | 409 |
| `ERR_LOCKER_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_BEDS_FOR_DISPATCH` | 409 |
| `ERR_VEHICLE_TOO_SMALL` | 409 |
| `ERR_INSUFFICIENT_MEAL_STOCK` | 409 |
| `ERR_OPEN_INCIDENTS_REMAIN` | 409 |
| `ERR_SITES_NOT_CLOSED` | 409 |
| `ERR_STAYS_STILL_ACTIVE` | 409 |
| `ERR_DISPATCH_NOT_ARRIVED` | 409 |
| `ERR_CROSS_EPISODE_TRANSFER` | 409 |

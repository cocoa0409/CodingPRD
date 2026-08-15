# Fireworks Display Ops API — Product Requirements Document

## 1. Introduction

A licensed pyrotechnics operator running a public fireworks display operates under one of the most heavily regulated workflows in live entertainment: ATF licensing, fire-authority permitting, on-site security perimeters, weather-driven go/no-go decisions, explosive inventory accountability from magazine to muzzle, misfire handling, and post-show site clearance all have to line up before a single shell leaves the tube. Today, this coordination lives in phone calls, paper manifests, and email threads between operators, certified crew, and the local fire marshal — a fragile arrangement when the legal exposure is this high.

This document specifies the Fireworks Display Ops API, a REST service that manages the full lifecycle of a professional display: registering operators and their certified crew, filing permit applications backed by a site plan with a computed fallout radius, tracking explosive product from storage magazine through checkout, firing, and return, recording weather observations and the resulting go/no-go decision, staffing perimeter security posts, logging and disposing of misfires, sweeping the fallout area after the show, and closing out incidents and fees. The API is mounted under `/pyro`.

The system serves four distinct actor types with deliberate segregation of duties: the `SystemAdmin` who onboards and disciplines operators, the `Operator` who owns the show, the `FireMarshal` who reviews and gates the show, and the `CrewMember` who performs ground work. Every business rule below — licensing windows, certification coverage, magazine capacity, guard spacing, wind limits, dud-rate auto-halts — exists because the corresponding real-world failure mode is a regulatory citation, an injury, or a lost explosives license.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role string is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but not permitted on the endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). The four declared roles are spelled exactly `SystemAdmin`, `Operator`, `FireMarshal`, and `CrewMember`.

Identity semantics differ per role:

- When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Operator`; ownership checks on any resource that references an `Operator` compare the resource's foreign-key field to `X-User-ID`. A display's `operator_id`, a magazine's `operator_id`, a batch reached through its magazine's `operator_id`, and any child of a display are all checked this way; a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).
- When `X-User-Role` is `CrewMember`, `X-User-ID` is the `id` of the acting `CrewMember`. Crew do not own aggregates; instead, when a crew member records a reading or report against a display, the server verifies that the crew member belongs to the display's operator — a cross-scope mismatch surfaces as `ERR_SCOPE_MISMATCH` (HTTP 422) at a later validation tier, not as an ownership failure.
- When `X-User-Role` is `FireMarshal`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition requires attribution — for example, `reviewed_by_user_id` on a permit decision, `standby_confirmed_by` on standby confirmation, `verified_by_user_id` on a sweep verification, or `closed_by_user_id` on an incident closure — but never compares it to any entity's `id`.
- When `X-User-Role` is `SystemAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity.

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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more`. Every list is sorted by `created_at` ascending — oldest records first — and this ordering is deterministic; it is never keyed on `id`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource carries an `id` minted by the server as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry `updated_at` (same timestamp format, refreshed on every mutation) and a `version` integer that increments on every mutation of that resource. Two entity types are exempt from the `updated_at`/`version` pair: `InventoryMovement` and `WeatherReading` are append-only records and carry only `id` and `created_at` — both `updated_at` and `version` are absent on those two resources.

Time itself is a controlled dependency. The server maintains a logical clock whose startup value is exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time. An administrative capability exists to advance the logical clock to a supplied `to_iso8601` instant; doing so recomputes every clock-derived posture in the system, most notably the `posture` of every `Magazine`.

### 2.5. Licensing, Certification, and Inspection Windows

Three independent temporal windows gate operations across the platform, all evaluated against the logical clock.

An `Operator` is registered with `legal_name`, `atf_license_number` (unique across operators), a `license_class` of either `DISPLAY_1_3G` or `PROXIMATE_1_4G`, and a license window running from `license_valid_from` through `license_expires_at`. The window is inclusive at both ends: a show whose `scheduled_start_at` equals `license_expires_at` exactly is still covered. A show whose start falls outside the window is rejected with `ERR_LICENSE_EXPIRED`. The operator's `status` begins as `ACTIVE` and may move to `SUSPENDED`, at which point `suspended_reason` records the reason; while `ACTIVE`, `suspended_reason` is null. Any action attempted by a `SUSPENDED` operator is rejected with `ERR_OPERATOR_SUSPENDED`.

A `CrewMember` carries `full_name`, a `cert_level` of `TRAINEE`, `SHOOTER`, or `LEAD_OPERATOR`, a `cert_expires_at` timestamp, and a `hazmat_endorsed` flag that defaults to false when not supplied. Certification must not already be expired at registration — a `cert_expires_at` at or before the current clock is rejected with `ERR_CERT_NOT_VALID` — and at the readiness gate, at least one crew member of the operator must hold `cert_level` `LEAD_OPERATOR` with a certification that remains valid through the show's `scheduled_start_at`, otherwise the same `ERR_CERT_NOT_VALID` fires.

A `Magazine` is registered with `name`, `atf_magazine_permit`, a `magazine_type` of `INDOOR` or `OUTDOOR`, a `capacity_new_lbs` net-explosive-weight capacity expressed with two decimal places, and an `inspection_due_at` deadline. Its `posture` is derived, never stored directly: `ACTIVE` while the clock is at or before `inspection_due_at`, flipping to `LAPSED` the instant the clock passes it. Receiving new product into a `LAPSED` magazine is rejected with `ERR_MAGAZINE_LAPSED`.

### 2.6. Precision, Rounding, and Monetary Conventions

All monetary amounts are integer cents; fee line items are each rounded half-up to whole cents before being summed. Net explosive weights are carried at two decimal places with round-half-up. Wind speeds are carried at one decimal place, and comparisons against wind limits are made at that precision. Distances derived from shell diameters are integer feet, with fractional-inch products rounded half-up to the nearest foot. Quantities of product are integer units throughout. Timestamp comparisons are made at second precision.

### 2.7. Optimistic Concurrency Control

Two write operations on a display are guarded against stale client views: creating a site plan on a display, and recording the go/no-go weather decision on a display. Both requests must carry `expected_display_event_version`, a non-optional field holding the `version` of the `DisplayEvent` the client last observed. If the event's current `version` has advanced past that value — because any authorized write has mutated the event in the meantime — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). For site-plan creation this prevents a client from superseding a plan it never saw; for the go/no-go decision it guarantees the GO is issued against the exact event state the shooter reviewed. No other endpoint takes a version field.

### 2.8. Validation Ordering

Every request is screened by an ordered ladder of checks; the first failing tier determines the response. Authentication comes first — missing or unknown headers yield `ERR_UNAUTHENTICATED` — followed by role permissioning, which yields `ERR_FORBIDDEN_ROLE`. Request-schema validation runs third: required fields present (including the conditional transport-manifest fields whenever a movement's `movement_type` is `CHECK_OUT`), types and enum members valid, quantities and diameters greater than zero, `scheduled_end_at` strictly after `scheduled_start_at`, the scheduled start in the future, and no undeclared payload fields; failures here return `ERR_VALIDATION`, or `ERR_INVALID_QUANTITY` when a movement quantity or count is not positive. Fourth, existence: path identifiers are resolved left-to-right and body-referenced identifiers (`site_plan_id`, `product_batch_id`, `display_event_id`) must exist, otherwise `ERR_NOT_FOUND`. Fifth, entity-backed ownership for `Operator` callers, failing as `ERR_FORBIDDEN_OWNERSHIP`. Sixth, the optimistic-concurrency comparison, failing as `ERR_STALE_VERSION`. Seventh, state-machine preconditions — the transition must be listed for the entity's current state (`ERR_INVALID_STATE`), the operator must be `ACTIVE` (`ERR_OPERATOR_SUSPENDED`), magazine `posture` must be `ACTIVE` for intake (`ERR_MAGAZINE_LAPSED`), the event's permit must be approved before product moves (`ERR_PERMIT_NOT_APPROVED`), and no second non-terminal application may exist (`ERR_DUPLICATE_APPLICATION`). Within this seventh tier, on permit-application creation specifically, the duplicate-application check is evaluated before the generic event-state check — so filing a second application while the event sits in `SUBMITTED` returns `ERR_DUPLICATE_APPLICATION`, not `ERR_INVALID_STATE`. Eighth, safety and compliance gates: quarantined stock (`ERR_BATCH_QUARANTINED`), fallout geometry (`ERR_FALLOUT_EXCEEDS_BOUNDARY`), weather limits (`ERR_WEATHER_NO_GO`), and segregation of duties (`ERR_SOD_VIOLATION`). Ninth, cross-scope references, failing as `ERR_SCOPE_MISMATCH`. Tenth, temporal rules: license containment (`ERR_LICENSE_EXPIRED`), certification validity (`ERR_CERT_NOT_VALID`), weather freshness (`ERR_WEATHER_STALE`), misfire soak completion (`ERR_SOAK_INCOMPLETE`), decision-window containment (`ERR_SHOW_WINDOW_NOT_OPEN`), and venue booking buffers (`ERR_VENUE_CONFLICT`). Eleventh and last, capacity, aggregate, and reconciliation constraints: magazine capacity (`ERR_MAGAZINE_CAPACITY_EXCEEDED`), movement availability (`ERR_INSUFFICIENT_PRODUCT`), readiness aggregates (`ERR_SECURITY_NOT_SECURED`, `ERR_NO_PRODUCT_ON_SITE`), sweep reconciliation (`ERR_SWEEP_RECONCILE_FAILED`), and manifest compliance (`ERR_MANIFEST_NOT_COMPLIANT`).

### 2.9. Nested Resource Retrieval and Aggregate Consistency

Nested paths are validated left-to-right: each path segment's identifier must resolve before the next is examined, and the first unresolvable identifier produces `ERR_NOT_FOUND`. When a mutation cascades across entities — a cancellation releasing security posts, withdrawing applications, and returning product, or an operator suspension cancelling a whole portfolio of shows — every affected entity's `updated_at` is refreshed and its `version` incremented as part of the same operation, and derived fields (`dud_count`, `fired_count`, `current_new_lbs`, batch statuses) are recomputed immediately; consistency is immediate, never deferred.

## 3. Business Logic & Workflows

### 3.1. Onboarding Operators, Crew, and Storage Infrastructure

A `SystemAdmin` registers each pyrotechnics operator by supplying the operator's `legal_name`, `atf_license_number`, `license_class`, and the license validity window `license_valid_from` through `license_expires_at`. New operators begin in `ACTIVE` status with `version` 1. Suspension is the platform's discipline lever: a `SystemAdmin` may suspend an `ACTIVE` operator, supplying a `reason` that is recorded as the operator's `suspended_reason`. Suspension is the root of a three-level cascade — every one of that operator's `DisplayEvent` records still in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `STANDBY_CONFIRMED`, or `READY` is moved to `CANCELLED` with `cancellation_reason` set to `OPERATOR_SUSPENDED`, and the full per-event cancellation cascade described in §3.7 fires for each one: security posts release, non-terminal permit applications withdraw, auto-generated return movements bring net checked-out product home, and each affected magazine's `current_new_lbs` is recomputed.

An operator builds its workforce by registering crew under itself; the path operator must equal the caller's `X-User-ID`. Each crew registration supplies `full_name`, `cert_level`, and `cert_expires_at`, with `hazmat_endorsed` optional and defaulting to false. Certification must not already be expired at registration time. An operator's crew roster can be listed with an optional `cert_level` filter.

Storage infrastructure is registered per operator as well. A magazine registration supplies `name`, `atf_magazine_permit`, `magazine_type`, `capacity_new_lbs`, and `inspection_due_at`; the magazine starts with `current_new_lbs` at zero and `posture` `ACTIVE`. The magazine list accepts an optional `operator_id` filter.

### 3.2. Booking a Display and Filing the Site Plan

An operator opens a new show by creating a display event with `venue_id`, `venue_name`, `scheduled_start_at`, `scheduled_end_at`, and `declared_max_shell_diameter_in` — the declared diameter of the largest aerial shell intended, which must be greater than zero. The scheduled end must be strictly after the scheduled start, and the scheduled start must lie strictly in the future. The event's `operator_id` is set from the authenticated operator, never from the payload. The new event begins in `DRAFT` with `weather_decision` `PENDING`, `dud_count` and `fired_count` at zero, and `cancellation_reason`, `termination_reason`, `standby_confirmed_at`, `standby_confirmed_by`, `show_completed_at`, `closed_at`, `final_fallout_radius_ft`, and `final_standby_fee_cents` all null.

Two booking-time guards run here. The operator's license window must contain `scheduled_start_at` inclusively, else `ERR_LICENSE_EXPIRED`. And the venue itself is protected by a booking buffer: if another non-terminal event at the same `venue_id` overlaps this event's window, creation is rejected with `ERR_VENUE_CONFLICT`. For this comparison every event's window — the new event's and each existing event's alike — is extended by its own 120-minute trailing buffer beyond its `scheduled_end_at`, and overlap requires a positive shared span: windows that merely touch at a single instant, such as a start exactly at the other window's buffered end, do not conflict. The displays list accepts optional `operator_id` and `status` filters.

With the event drafted, the operator files a site plan carrying `diagram_ref`, `launch_area_width_ft` and `launch_area_length_ft` (both greater than zero), `spectator_boundary_ft`, `spectator_arc_center_deg` (a compass bearing from 0 to 359 giving the direction of the spectator area's center from the launch point), and `nearest_structure_ft`. At creation the server computes the plan's `required_spectator_distance_ft` as 70 feet per inch of the parent event's `declared_max_shell_diameter_in`, rounded half-up to integer feet — a declared 6-inch shell therefore demands 420 feet. Both `spectator_boundary_ft` and `nearest_structure_ft` must be at least this required distance, otherwise creation is rejected with `ERR_FALLOUT_EXCEEDS_BOUNDARY`. Filing a site plan supersedes whatever plan was previously `CURRENT` for the event, moving it to `SUPERSEDED`, and increments the event's `version` by one; because superseding discards the prior plan, this write is OCC-guarded and must carry `expected_display_event_version` matching the event's current `version`, failing as `ERR_STALE_VERSION` (HTTP 412) when the client has not observed the latest event state. A site plan's `display_event_id` is bound from the path.

### 3.3. The Permit Review Loop

A permit application moves the event from preparation into regulatory review. To submit, the operator names the `site_plan_id` under review and the requested `standby_engines` count, which must be at least 1. Submission requires the event to be in `DRAFT`, at least one `CURRENT` site plan to exist (none at all yields `ERR_INVALID_STATE`), no other application of the same event to be sitting in `SUBMITTED` or `INFO_REQUESTED` (a duplicate yields `ERR_DUPLICATE_APPLICATION`, and as noted in §2.8 this check fires ahead of the generic state check on this endpoint), and the license window to cover the show date. The referenced site plan must belong to this event, failing as `ERR_SCOPE_MISMATCH` otherwise.

On submission, the application is created in `SUBMITTED` status, the referenced plan's `version` is pinned onto the application as `site_plan_version`, and the event transitions `DRAFT → SUBMITTED` with its `version` incremented by one. Two provisional figures are computed at this moment. `planned_hours` is the length of the scheduled window rounded up to whole hours — the number of seconds between `scheduled_start_at` and `scheduled_end_at`, divided by 3600, ceiling applied. `provisional_standby_fee_cents` is then the base standby fee of 25000 cents, plus 14500 cents for each planned hour, plus a 30000-cent surcharge for each requested standby engine. Applications can be listed per display, or globally with optional `site_plan_id`, `display_event_id`, and `status` filters.

Review belongs to the `FireMarshal`, who acts on a `SUBMITTED` application in one of three ways. Approval moves the application to `APPROVED`, records the marshal's `X-User-ID` as `reviewed_by_user_id` along with an optional `decision_note`, and drives the event `SUBMITTED → APPROVED`. Denial requires a `decision_note`, records the same attribution, moves the application to `DENIED`, and drives the event `SUBMITTED → DENIED` — terminal for the event. Requesting revisions also requires a `decision_note`, moves the application to `INFO_REQUESTED`, and drives the event `SUBMITTED → REVISION_REQUESTED`. Each of these three decisions increments the event's `version` by one.

The revision loop is cyclic: after a revision request, the operator may resubmit with a fresh `site_plan_id` that must reference a `CURRENT` plan of the same event (violations surface as `ERR_SCOPE_MISMATCH` or `ERR_INVALID_STATE` depending on whether the plan is foreign or merely superseded). Resubmission moves the application `INFO_REQUESTED → SUBMITTED`, re-pins `site_plan_id` and `site_plan_version`, increments `revision_count` by one, and returns the event `REVISION_REQUESTED → SUBMITTED`. An application still in `SUBMITTED` or `INFO_REQUESTED` when its event is cancelled is moved to `WITHDRAWN` by the system.

### 3.4. Inventory: Magazines, Batches, and Movements

Product enters the system as batches received into a specific magazine; the batch's `magazine_id` is bound from the path of the receiving magazine. A batch registration names `product_name`, `un_number` (the UN dangerous-goods number, e.g. UN0335), `shell_diameter_in` (greater than zero), `quantity_units` (greater than zero), `new_per_unit_lbs` (net explosive weight per unit, greater than zero, two decimal places), and `lot_number`. Two intake gates apply: the magazine's `posture` must be `ACTIVE`, and the intake must not push the magazine over capacity — the magazine's `current_new_lbs` plus the incoming `quantity_units` times `new_per_unit_lbs` must be less than or equal to `capacity_new_lbs`, with an exact fit allowed; overflow is rejected with `ERR_MAGAZINE_CAPACITY_EXCEEDED`. A fresh batch begins in `IN_MAGAZINE` with `qty_at_magazine` equal to `quantity_units`, `qty_at_show` and `qty_expended` at zero, and `quantity_remaining` equal to `quantity_units`.

Every magazine's `current_new_lbs` is a derived figure: the sum over all its batches — including `QUARANTINED` ones, since quarantined stock still physically occupies the magazine — of each batch's `qty_at_magazine` multiplied by its `new_per_unit_lbs`, rounded half-up to two decimal places. The figure is recomputed at batch creation and on every movement affecting a batch stored there. Mass conservation is an invariant: a checkout of some quantity followed by a return of the same quantity leaves `current_new_lbs` bit-identical to its value before the checkout. Batch lists per magazine accept an optional `status` filter.

Movements drive product through the show. Recording a movement on a batch supplies `movement_type` — one of `CHECK_OUT`, `RETURN`, or `EXPEND` — plus `quantity` (greater than zero, else `ERR_INVALID_QUANTITY`) and the `display_event_id` the movement serves. The batch's operator must match the event's operator, failing as `ERR_SCOPE_MISMATCH`; the event's permit must already be approved, failing as `ERR_PERMIT_NOT_APPROVED`; and a batch in `QUARANTINED` rejects every subsequent movement with `ERR_BATCH_QUARANTINED`. Each movement records `recorded_by_user_id` from the caller's `X-User-ID`, and `auto_generated` is false except on cascade-created returns.

Transport-manifest compliance applies to checkouts: `driver_name`, `vehicle_placard`, and `cdl_hazmat_endorsed` are required exactly when `movement_type` is `CHECK_OUT`, and `cdl_hazmat_endorsed` must be true — a false value is rejected with `ERR_MANIFEST_NOT_COMPLIANT`.

Quantities move between three buckets per batch. A `CHECK_OUT` of q units requires q not to exceed the batch's `qty_at_magazine`, then subtracts q from `qty_at_magazine` and adds q to `qty_at_show`. A `RETURN` of q requires q not to exceed the batch's `qty_at_show` attributed to the named event, then subtracts q from `qty_at_show` and adds q back to `qty_at_magazine`. An `EXPEND` of q likewise requires q not to exceed the batch's `qty_at_show` for that event, then subtracts q from `qty_at_show` and adds q to `qty_expended`. Availability shortfalls on any of the three are rejected with `ERR_INSUFFICIENT_PRODUCT`. After every movement, `quantity_remaining` is `quantity_units` minus `qty_expended`, and unit accountability holds at all times: `quantity_units` always equals the sum of `qty_at_magazine`, `qty_at_show`, and `qty_expended`. The batch's status is then recomputed — `DEPLETED` when `quantity_remaining` reaches zero, otherwise `CHECKED_OUT` while any units remain at shows, otherwise `IN_MAGAZINE` — unless the batch is `QUARANTINED`, which nothing overrides. An `EXPEND` movement additionally grows the parent event's `fired_count` by the expended quantity, and a `RETURN` movement triggers the auto-close evaluation described in §3.7.

Checkout carries one more gate, the allocation fallout check, and its evaluation order is pinned because allocation and gating are mutually dependent. The server first forms the candidate maximum diameter: the larger of the greatest `shell_diameter_in` among batches currently holding net `qty_at_show` above zero for this event (zero if none) and the candidate batch's own `shell_diameter_in`. It then computes the candidate required distance as 70 feet per inch of that maximum, rounded half-up to integer feet. If that candidate distance exceeds the `CURRENT` site plan's `spectator_boundary_ft`, the movement is rejected with `ERR_FALLOUT_EXCEEDS_BOUNDARY`; otherwise the movement is recorded and the batch's `qty_at_show` increases — which may raise the gate for the next allocation.

Either an `Operator` or a `FireMarshal` may quarantine a batch in `IN_MAGAZINE` or `CHECKED_OUT`, supplying a `reason`; quarantine is terminal at `QUARANTINED` and blocks all further movements on the batch. Movements are listable per batch, or per display with an optional `movement_type` filter; misfires tied to a batch are likewise listable per batch.

### 3.5. Perimeter Security and Show-Day Readiness

Spectator safety on the ground is organized as security posts around the fallout area. The operator creates each post on the display with a `post_label` unique within the event, an `arc_degrees` coverage between 1 and 360, and a `radius_ft` that must be at least the `CURRENT` site plan's `required_spectator_distance_ft`. The post's `required_guards` is computed at creation: take the arc length in feet — two times pi times `radius_ft`, scaled by the fraction `arc_degrees` over 360, using pi to full double precision with no intermediate rounding — divide by the 100-foot guard-spacing constant, round up, and floor the result at a minimum of one guard. New posts begin `UNSTAFFED` with `assigned_guards` zero. Post lists accept an optional `status` filter.

Staffing proceeds one guard at a time: each assignment call supplies `guard_name` and `guard_company` and increments `assigned_guards` by one, allowed while the post is `UNSTAFFED` or `STAFFED`. The first assignment moves the post `UNSTAFFED → STAFFED`, and the moment `assigned_guards` reaches `required_guards` — inclusive equality secures — the post auto-transitions to `SECURED`. Posts are released by the system, moving `UNSTAFFED`, `STAFFED`, or `SECURED` to `RELEASED`, when the event is cancelled or when a sweep is verified.

Readiness is the operator's declaration that the show can proceed, moving the event `STANDBY_CONFIRMED → READY`. Three aggregate gates must all pass: at least one security post exists and every post of the event is `SECURED`, otherwise `ERR_SECURITY_NOT_SECURED`; at least one of the operator's crew holds `LEAD_OPERATOR` certification valid through `scheduled_start_at`, otherwise `ERR_CERT_NOT_VALID`; and net checked-out product for the event — total `CHECK_OUT` minus total `RETURN` — is greater than zero, otherwise `ERR_NO_PRODUCT_ON_SITE`.

Before readiness, however, the fire authority must confirm its standby. Once the event is `APPROVED`, a `FireMarshal` confirms fire-watch standby by reporting `standby_engines_on_site` and an optional `note`. Segregation of duties applies: the confirming marshal's `X-User-ID` must differ from the `reviewed_by_user_id` on the approved application, else `ERR_SOD_VIOLATION`. The engine count on site must equal the application's `standby_engines`, else `ERR_VALIDATION`. Success stamps `standby_confirmed_at` with the clock and `standby_confirmed_by` with the marshal's id, moves the event `APPROVED → STANDBY_CONFIRMED`, and increments its `version`.

### 3.6. Weather and the Go/No-Go Decision

Crews log weather throughout setup: any non-terminal event state accepts a new reading carrying `wind_speed_mph` and `gust_mph` (each at least zero, one decimal place), `wind_direction_deg` (the compass direction the wind comes from, 0 to 359), a `precipitation` flag, and a `source` of `ON_SITE_ANEMOMETER` or `NWS`. The recorder's `X-User-ID` lands on `recorded_by_user_id`, and a crew recorder must belong to the event's operator on pain of `ERR_SCOPE_MISMATCH`.

The go/no-go decision is the show's point of no return, issued by the operator with a `decision` of `GO` or `NO_GO`, and OCC-guarded by `expected_display_event_version`. The decision is only accepted while the event is `READY`, and only inside the decision window: the clock must be at or after 60 minutes before `scheduled_start_at` and at or before `scheduled_end_at` — both bounds inclusive — otherwise `ERR_SHOW_WINDOW_NOT_OPEN`. A usable weather reading must exist and be fresh: if no reading exists, or the latest reading by `created_at` is older than 30 minutes ago, the decision is rejected with `ERR_WEATHER_STALE` — exactly 30 minutes old is still fresh, as the comparison is inclusive. The GO limits themselves are strict: a `GO` fails with `ERR_WEATHER_NO_GO` when the latest reading's `wind_speed_mph` reaches 20.0 mph or more, its `gust_mph` reaches 25.0 mph or more, or `precipitation` is true.

A successful `GO` also re-derives the fallout geometry from what is actually on site. The final base radius is 70 feet per inch of the greatest `shell_diameter_in` among batches with net `qty_at_show` above zero for the event at decision time — note this can differ from the declared diameter that drove the provisional site-plan figure whenever allocated stock differs from the declaration. Wind then adjusts that base. The downwind bearing is the latest reading's `wind_direction_deg` plus 180 degrees, wrapped into the compass circle. The angular separation delta is the smallest angle, between 0 and 180 degrees, between the `CURRENT` plan's `spectator_arc_center_deg` and that downwind bearing. When the sustained wind is below the 8-mph drift threshold, no adjustment applies. Otherwise a drift factor is formed as one plus five-hundredths per mph of wind above the threshold — that is, 1 + (wind minus 8) × 0.05 — capped at 1.5, with no intermediate rounding of the factor. When delta is at most 45 degrees the full factor applies; when delta is greater than 45 but at most 135 degrees, half the excess applies — one plus half of (factor minus one); beyond 135 degrees the wind blows away from spectators and the base stands. The result is rounded half-up to integer feet and stored as the event's `final_fallout_radius_ft`, and it must not exceed the `CURRENT` plan's `spectator_boundary_ft`, else the decision is rejected with `ERR_FALLOUT_EXCEEDS_BOUNDARY`. Success sets `weather_decision` to `GO` and moves the event `READY → IN_PROGRESS`, incrementing its `version`.

A `NO_GO` decision — or an outright cancellation — moves the event to `CANCELLED`. On the `NO_GO` path, `weather_decision` becomes `NO_GO` and `cancellation_reason` becomes `WEATHER_NO_GO`; a manual cancel while the event is in `DRAFT`, `SUBMITTED`, `REVISION_REQUESTED`, `APPROVED`, `STANDBY_CONFIRMED`, or `READY` accepts an optional `reason` and sets `cancellation_reason` to `OPERATOR`. Either way the cancellation cascade of §3.7 fires.

### 3.7. Firing, Misfires, and the Cancellation Cascade

While `IN_PROGRESS`, product is expended by recording `EXPEND` movements against the relevant batches. Each misfire or dud is logged against the event by a crew member or the operator, naming the `product_batch_id` the dud shell came from, a `shell_description`, and optionally a `location_note`. The logger's `X-User-ID` is stored as `logged_by_crew_id`, and the record starts in `LOGGED`. Logging sets `soak_until` to 15 minutes after creation — disposal is allowed at or after that instant, inclusive — increments the event's `dud_count` by one, and increments the event's `version`.

Misfires feed the dud-rate auto-halt. On each new misfire the halt threshold is computed as the larger of an absolute floor of 2 duds and the event's `fired_count` — evaluated before this misfire, since misfires never change `fired_count` — multiplied by the 5-percent dud-rate limit and rounded up. If the resulting `dud_count` has reached the threshold and the event is `IN_PROGRESS`, the system halts the show automatically: the event moves `IN_PROGRESS → SHOW_COMPLETE` with `termination_reason` set to `DUD_HALT`. The operator may instead end firing deliberately, moving `IN_PROGRESS → SHOW_COMPLETE` with `termination_reason` `COMPLETED` and `show_completed_at` stamped with the clock.

Disposal of a dud is permitted once the event has reached `SHOW_COMPLETE` or `SWEEP_VERIFIED` (earlier attempts fail with `ERR_INVALID_STATE`), the record is still `LOGGED`, and the clock has reached `soak_until` — earlier is `ERR_SOAK_INCOMPLETE`. Disposal records the `disposal_method` — `SOAK_CRUSH`, `BURN_PIT`, or `RETURN_TO_SUPPLIER` — stamps `disposed_at`, moves the record `LOGGED → DISPOSED`, and unblocks the sweep-creation reconciliation gate for that misfire. Misfire lists per display accept an optional `status` filter.

The cancellation cascade — shared by manual cancellation, weather `NO_GO`, and operator suspension — runs the same steps regardless of trigger. Every security post of the event in `UNSTAFFED`, `STAFFED`, or `SECURED` moves to `RELEASED`. Every non-terminal permit application of the event moves to `WITHDRAWN`. For every batch with `qty_at_show` above zero attributed to this event, the system writes a `RETURN` movement marked `auto_generated` true with `recorded_by_user_id` set to `system`, bringing the remaining on-site quantity home, and each affected magazine's `current_new_lbs` is recomputed per return. The event's `version` increments by one.

### 3.8. Sweeps, Incidents, and Show Close-Out

After the show, the fallout area must be swept before the event can close. A `CrewMember` records a sweep with a `sweep_type` of `NIGHT_SWEEP` or `DAWN_RECHECK`, an `area_clear` flag, and optional `notes`. The crew member's `X-User-ID` lands on `swept_by_crew_id`, and the record begins with `verdict` `PENDING`. Reconciliation gates sweep creation: if any misfire of the event is still `LOGGED`, the sweep is rejected with `ERR_SWEEP_RECONCILE_FAILED` — every dud must be disposed first. Sweep lists are available per display.

Verification belongs to the `FireMarshal`, who submits a `verdict` of `VERIFIED` or `REJECTED` with an optional `note`. A rejection leaves the event in `SHOW_COMPLETE` and permits a fresh sweep to be recorded — the re-sweep loop. A verification against a `PENDING` sweep stamps `verified_by_user_id`, moves the sweep to `VERIFIED`, releases every security post still in `UNSTAFFED`, `STAFFED`, or `SECURED`, drives the event `SHOW_COMPLETE → SWEEP_VERIFIED` with a version increment, and triggers the auto-close evaluation.

Incidents may be filed at any point by an operator, crew member, or fire marshal, supplying `incident_type` (`INJURY`, `FIRE`, `PROPERTY_DAMAGE`, `DUD_OFFSITE`, or `CROWD_BREACH`), `severity` (`MINOR`, `SERIOUS`, or `CRITICAL`), and a free-text `description`. The reporter's `X-User-ID` and `X-User-Role` are captured as `reported_by_user_id` and `reported_by_role`, and the report begins in `FILED`. Closure is a `FireMarshal` action carrying a `resolution_note`; segregation of duties forbids the same user id from closing a report they filed, surfacing as `ERR_SOD_VIOLATION`. Closure stamps `closed_by_user_id`, moves the report `FILED → CLOSED`, and triggers auto-close evaluation on the parent event. Incident lists accept an optional `status` filter.

The event closes itself. After every sweep verification, every incident closure, and every `RETURN` movement, the system evaluates whether the `SWEEP_VERIFIED` event may move to `CLOSED`: no incident report of the event may remain `FILED`, and net checked-out product for the event — total `CHECK_OUT` minus total `RETURN` minus total `EXPEND` — must be exactly zero. When both hold, `closed_at` is stamped and the final standby fee is computed and stored as `final_standby_fee_cents`. The final fee differs deliberately from the provisional estimate: the elapsed standby time is the number of minutes between `standby_confirmed_at` and `closed_at`, rounded up to whole minutes; the hours line item is those elapsed minutes multiplied by the 14500-cent hourly rate and divided by 60, rounded half-up to whole cents; and the total is the 25000-cent base fee plus that hours line plus the 30000-cent surcharge per standby engine from the approved application, summing integer line items. Rounding elapsed time up to whole hours before multiplying is expressly forbidden — it produces a different, larger fee. Because actual standby elapsed time rarely matches the planned window, the final fee will differ from `provisional_standby_fee_cents` even when the schedule data is identical. `CLOSED`, `DENIED`, and `CANCELLED` are the terminal states of a display.

## 4. Endpoint Definitions

Resource creation returns HTTP 201; all other successful operations — reads, state transitions, and mutations of existing resources — return HTTP 200. Error responses use the status codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /pyro/_clock/set_current_utc | Advance the test-driving logical clock to a supplied instant; recomputes clock-derived postures | SystemAdmin |
| POST | /pyro/operators | Register a licensed pyrotechnics operator | SystemAdmin |
| GET | /pyro/operators/{id} | Get an operator | SystemAdmin, Operator |
| POST | /pyro/operators/{id}/suspend | Suspend an operator; cascades cancellation across its non-terminal displays | SystemAdmin |
| POST | /pyro/operators/{id}/crew-members | Register a certified crew member under an operator | Operator |
| GET | /pyro/operators/{id}/crew-members | List an operator's crew | Operator, SystemAdmin |
| POST | /pyro/displays | Create a display event in DRAFT | Operator |
| GET | /pyro/displays/{id} | Get a display event | Operator, FireMarshal, CrewMember, SystemAdmin |
| GET | /pyro/displays | List display events | Operator, FireMarshal, SystemAdmin |
| POST | /pyro/displays/{id}/standby-confirm | FireMarshal confirms fire-watch standby on site | FireMarshal |
| POST | /pyro/displays/{id}/ready | Operator declares the show ready; enforces security/crew/product gates | Operator |
| POST | /pyro/displays/{id}/go-no-go | Weather go/no-go decision (OCC-guarded); GO enters IN_PROGRESS, NO_GO cancels | Operator |
| POST | /pyro/displays/{id}/complete-show | Mark firing complete | Operator |
| POST | /pyro/displays/{id}/cancel | Operator cancels a non-terminal, pre-show event | Operator |
| POST | /pyro/displays/{id}/site-plans | Create a site plan; supersedes the prior CURRENT plan (OCC-guarded) | Operator |
| GET | /pyro/displays/{id}/site-plans | List site plans of a display | Operator, FireMarshal |
| POST | /pyro/displays/{id}/permit-applications | Submit a permit application; transitions the event to SUBMITTED | Operator |
| GET | /pyro/displays/{id}/permit-applications | List permit applications of a display | Operator, FireMarshal |
| GET | /pyro/permit-applications/{id} | Get a permit application | Operator, FireMarshal |
| GET | /pyro/permit-applications | List permit applications | Operator, FireMarshal |
| POST | /pyro/permit-applications/{id}/approve | FireMarshal approves the application | FireMarshal |
| POST | /pyro/permit-applications/{id}/deny | FireMarshal denies the application (terminal for the event) | FireMarshal |
| POST | /pyro/permit-applications/{id}/request-info | FireMarshal requests revisions | FireMarshal |
| POST | /pyro/permit-applications/{id}/resubmit | Operator resubmits after revisions | Operator |
| POST | /pyro/magazines | Register a storage magazine | Operator |
| GET | /pyro/magazines/{id} | Get a magazine, including derived posture and current mass | Operator |
| GET | /pyro/magazines | List magazines | Operator |
| POST | /pyro/magazines/{id}/batches | Receive a product batch into a magazine (capacity and posture gated) | Operator |
| GET | /pyro/magazines/{id}/batches | List batches in a magazine | Operator |
| GET | /pyro/batches/{id} | Get a product batch | Operator |
| POST | /pyro/batches/{id}/quarantine | Quarantine a batch (terminal); all movements blocked | Operator, FireMarshal |
| POST | /pyro/batches/{id}/movements | Record a CHECK_OUT, RETURN, or EXPEND movement | Operator |
| GET | /pyro/batches/{id}/movements | List movements of a batch | Operator |
| GET | /pyro/displays/{id}/movements | List movements serving a display | Operator, FireMarshal |
| POST | /pyro/displays/{id}/weather-readings | Append a weather reading; allowed on any non-terminal event state | CrewMember, Operator |
| GET | /pyro/displays/{id}/weather-readings | List weather readings of a display | Operator, CrewMember, FireMarshal |
| POST | /pyro/displays/{id}/security-posts | Create a perimeter security post | Operator |
| GET | /pyro/displays/{id}/security-posts | List security posts of a display | Operator, FireMarshal |
| POST | /pyro/security-posts/{id}/assign | Assign one guard; auto-secures at the required count | Operator |
| POST | /pyro/displays/{id}/misfires | Log a misfire or dud during the show | CrewMember, Operator |
| GET | /pyro/displays/{id}/misfires | List misfire records of a display | Operator, FireMarshal, CrewMember |
| GET | /pyro/batches/{id}/misfires | List misfire records tied to a batch | Operator, FireMarshal |
| POST | /pyro/misfires/{id}/dispose | Dispose of a soaked dud | Operator |
| POST | /pyro/displays/{id}/sweeps | Record a post-show sweep | CrewMember |
| GET | /pyro/displays/{id}/sweeps | List sweeps of a display | Operator, FireMarshal, CrewMember |
| POST | /pyro/sweeps/{id}/verify | FireMarshal verifies or rejects a sweep | FireMarshal |
| POST | /pyro/displays/{id}/incidents | File an incident report | Operator, CrewMember, FireMarshal |
| GET | /pyro/displays/{id}/incidents | List incident reports of a display | Operator, FireMarshal, CrewMember |
| POST | /pyro/incidents/{id}/close | FireMarshal closes an incident | FireMarshal |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_SOD_VIOLATION | 403 |
| ERR_VALIDATION | 400 |
| ERR_INVALID_QUANTITY | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_OPERATOR_SUSPENDED | 409 |
| ERR_MAGAZINE_LAPSED | 409 |
| ERR_PERMIT_NOT_APPROVED | 409 |
| ERR_DUPLICATE_APPLICATION | 409 |
| ERR_BATCH_QUARANTINED | 409 |
| ERR_LICENSE_EXPIRED | 409 |
| ERR_CERT_NOT_VALID | 409 |
| ERR_WEATHER_STALE | 409 |
| ERR_SOAK_INCOMPLETE | 409 |
| ERR_SHOW_WINDOW_NOT_OPEN | 409 |
| ERR_VENUE_CONFLICT | 409 |
| ERR_INSUFFICIENT_PRODUCT | 409 |
| ERR_SECURITY_NOT_SECURED | 409 |
| ERR_NO_PRODUCT_ON_SITE | 409 |
| ERR_FALLOUT_EXCEEDS_BOUNDARY | 422 |
| ERR_WEATHER_NO_GO | 422 |
| ERR_SCOPE_MISMATCH | 422 |
| ERR_MAGAZINE_CAPACITY_EXCEEDED | 422 |
| ERR_SWEEP_RECONCILE_FAILED | 422 |
| ERR_MANIFEST_NOT_COMPLIANT | 422 |

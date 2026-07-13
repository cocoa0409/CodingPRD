# Drayage & Container Trucking API — Product Requirements Document

## 1. Introduction

Drayage is the short-haul trucking that moves containers between marine and rail terminals, warehouses, and empty-return depots. It sits at the seam between the ocean carrier's clock and the road carrier's operation, and that seam is where money is made or lost: a container left past its last free day accrues terminal demurrage, a chassis held past its allotted free days accrues equipment per-diem, and an overweight box that reaches the gate without a permit turns a routine move into a compliance incident. This document specifies a REST API that a drayage operator uses to run that business end to end — from registering the shared pools of chassis and drivers, through booking and appointing containers, dispatching legs, weighing loads, and finally reconciling every accrued charge onto a single invoice.

The system is organized around a small number of peer, top-level resources rather than a deep ownership tree. Terminals, chassis, and drivers are shared pools that no single booking owns; bookings reference them by foreign key, and legs draw a driver and (for pickups) an appointment from those pools. Two independent accrual ledgers run in parallel — demurrage, which is a property of the terminal and the booking, and per-diem, which is a property of the chassis — each with its own baseline, its own rate, and its own moment of finalization. Because timing drives every charge, the server keeps a single **logical clock** that all date-sensitive rules read from; the clock is advanced explicitly through an administrative endpoint so that demurrage, per-diem, and appointment-expiry behavior are fully deterministic and reproducible.

Three operational roles collaborate over this workflow. A dispatcher runs the physical operation, a biller reconciles the money, and a driver acts only on the legs assigned to them. The sections that follow define the global contract (response shape, authentication, pagination, precision, concurrency), then the detailed business logic and its deliberately interlocking side effects, then the endpoint and error-code catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The system recognizes exactly three roles: `Dispatcher`, `Driver`, and `Biller`. When a syntactically valid, known role attempts an operation it is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `Dispatcher` role owns all operational data — terminals, chassis, drivers, bookings, chassis assignment and release, appointments, legs, weigh tickets, permits, and the logical clock. The `Biller` role owns billing — invoice generation, issuance, and the management of accessorial charge lines. The `Driver` role has no exclusive write operations; a driver may only complete legs that belong to them. Completing a leg is shared between a `Dispatcher` and the owning `Driver`. All read (GET) operations are available to all three roles.

Identity binds to resources differently by role. When `X-User-Role` is `Dispatcher`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Biller`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Driver`; any ownership check on a leg compares the leg's `driver_id` foreign key to `X-User-ID`. Specifically, when a driver completes a leg, the leg's `driver_id` must equal `X-User-ID`; otherwise the request is rejected with `ERR_LEG_NOT_OWNED` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter bounds the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits set at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at its initial value of 1 and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7.

There is one deliberate exception. A `WeighTicket` is an immutable record: it carries only `id` and `created_at`. It has neither an `updated_at` field nor a `version` field, because once recorded it is never modified. Every other resource — `Terminal`, `Chassis`, `Driver`, `Booking`, `Appointment`, `Leg`, `Permit`, `Invoice`, and `AccessorialCharge` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

All time-sensitive behavior reads from a single server **logical clock**, not the wall clock. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to wall-clock time. An administrative capability lets a dispatcher move the clock to a supplied instant, provided as the `to_iso8601` field; the setter returns HTTP 200 with an empty data object (`{}`) rather than any clock resource. Every demurrage calculation, per-diem calculation, appointment-expiry check, and last-free-day comparison uses the clock's current value.

### 2.5. Monetary Amounts, Day Counting, and Rounding

All monetary amounts are integer cents. Where a calculation multiplies a cents amount by a percentage, the result is rounded to whole cents using the round-half-up method, and the rounding is applied at each point the calculation specifies rather than only once at the end. The specific rounding points are called out with each formula in §3 — most notably, the demurrage per-day charge is rounded before it is multiplied by the day count, and the invoice's volume discount and fuel surcharge are each rounded independently.

Day counts for demurrage and per-diem are computed over UTC calendar dates, not elapsed hours. For any two instants, the number of whole days between them is the difference between their UTC calendar dates. Demurrage counts each calendar date strictly after the container's last free day; per-diem counts the calendar dates a chassis has been out, less its free-day allowance. Both day counts are floored at zero — a basis on or before the reference date yields zero days, never a negative amount.

### 2.6. Request Validation Order and Error Semantics

When more than one rule could reject a request, the checks are evaluated in a fixed priority order and the first failure is the one returned. The canonical order is:

1. **Authentication** — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named in the path and every foreign key in the body is resolved left to right; the first unresolved reference returns the matching not-found error (404). These are `ERR_TERMINAL_NOT_FOUND`, `ERR_CHASSIS_NOT_FOUND`, `ERR_DRIVER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_LEG_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_WEIGH_TICKET_NOT_FOUND`, and `ERR_ACCESSORIAL_NOT_FOUND`.
4. **Body well-formedness** — on any write, required fields are present, enum fields hold legal values, integer amounts are at least zero, and any supplied `window_start` is strictly before its `window_end`. A pickup leg must supply an `appointment_id`, a street-turn leg must supply a `linked_export_booking_id`, and a chassis assignment must supply `expected_booking_version`. Any violation returns `ERR_VALIDATION` (400).
5. **Leg ownership** — a driver completing a leg must own it, else `ERR_LEG_NOT_OWNED` (403).
6. **State validity** — the target resource is in a legal state for the requested transition, else `ERR_INVALID_STATE` (409).
7. **Permit gate** — an overweight booking may not dispatch its pickup without an approved permit, else `ERR_PERMIT_REQUIRED` (422).
8. **Referenced-entity state** — a referenced entity is in the state the operation requires: an assignment target chassis must be available (`ERR_CHASSIS_UNAVAILABLE`), a pickup dispatch requires its booking's chassis to be assigned (`ERR_CHASSIS_NOT_ASSIGNED`), the linked appointment must be booked (`ERR_APPOINTMENT_NOT_BOOKED`), and the assigned driver must be active (`ERR_DRIVER_INACTIVE`) — all 409.
9. **Appointment temporal** — the logical clock is before the linked appointment's `window_end`, else `ERR_APPOINTMENT_EXPIRED` (422).
10. **Appointment slot capacity** — the requested appointment window does not exceed the terminal's slot capacity, else `ERR_APPOINTMENT_SLOT_FULL` (409).
11. **Driver availability** — the requested leg does not collide with the driver's other legs within the turnaround buffer, else `ERR_DRIVER_UNAVAILABLE` (409).
12. **Invoiceability** — the booking is invoiceable and the parent invoice is editable, else `ERR_NOT_INVOICEABLE` (409).
13. **Optimistic concurrency** — for a chassis assignment, `expected_booking_version` matches the booking's current `version`, else `ERR_STALE_BOOKING_VERSION` (412).

The ordering has consequences worth naming. For a chassis assignment, the booking's own state is checked (priority 6) before the target chassis's availability (priority 8), and both are checked before the optimistic-concurrency comparison (priority 13) — a stale-version rejection is the last thing considered. For a pickup dispatch, the booking's state (priority 6) is checked, then the permit gate (priority 7), then the chassis/appointment/driver referential states (priority 8), and only then the appointment-expiry check (priority 9).

### 2.7. Optimistic Concurrency Control for Chassis Assignment

Assigning a chassis to a booking is the one write in this system guarded by optimistic concurrency control. The assignment request must carry `expected_booking_version`, which is the client's last observed `version` of the target `Booking`. Before the assignment is applied, the server compares `expected_booking_version` against the booking's current `version`. If they do not match — because some earlier write has advanced the booking's `version` since the client last read it, for example a prior assignment that already set or superseded the chassis — the request is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412), preventing the client from overwriting an assignment it never observed. This same guard applies to the very first assignment out of the `CONFIRMED` state and to every subsequent supersede on an already-assigned booking. No other endpoint takes a version field; only chassis assignment is version-checked.

### 2.8. Cascading State Propagation

Several operations mutate more than one resource, and the secondary effects are as much a part of the contract as the primary transition. Whenever any field of a resource changes as part of an operation — including a system-driven change the client did not directly request — that resource's `updated_at` is refreshed and its `version` is incremented by one (except `WeighTicket`, which is immutable and never mutated after creation).

The most important cascade is the empty-return chain. Completing a return leg releases the chassis, which finalizes per-diem on that chassis, which in turn stamps and empties the owning booking — three linked transitions that fire from a single request. Cancellation propagates the other way: canceling a booking cancels each of its non-terminal legs, and a canceled pickup leg that had taken its chassis out releases that chassis back to the pool. These chains are specified in full where the workflows that trigger them are described in §3.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Terminals, the Chassis Pool, and Drivers

Before any container moves, a dispatcher populates the shared pools. A **terminal** is registered with a `name`, a `code` (its firms/terminal code), a `demurrage_daily_rate_cents` (the base demurrage rate charged per calendar day past the last free day, before the port fee, and never negative), and an optional `slot_capacity_per_window`, which is the maximum number of booked appointments allowed to overlap the same window at that terminal and defaults to 1 when omitted (and must be at least 1).

A **chassis** enters the pool with a `chassis_number`, a `pool_scac` (the pool owner's code), a `per_diem_rate_cents` (the daily rate charged for each day the chassis is held past its free days, never negative), and an optional `free_days`, the number of free days out before per-diem begins to accrue, which defaults to 4 and must be at least zero. A newly registered chassis starts with `status` `AVAILABLE`. Its `assigned_out_at` (the instant it went out on a pickup) and `returned_at` (the instant it came back) are both null until those events occur. Its `per_diem_provisional_cents` and `per_diem_final_cents` are both zero at registration; the provisional figure is recomputed at read time whenever the chassis is `OUT` (described in §3.7), and the final figure is set at empty return.

A **driver** is registered with a `name`, a `license_number`, and a `status` that may be set to either `ACTIVE` or `INACTIVE` at creation and defaults to `ACTIVE`. Only an `ACTIVE` driver may be dispatched; an attempt to dispatch a leg whose assigned driver is `INACTIVE` is rejected with `ERR_DRIVER_INACTIVE`.

### 3.2. The Booking Lifecycle: Draft and Confirmation

A **booking** represents one container move. A dispatcher creates it with a `container_number`, a `direction` of either `IMPORT` or `EXPORT`, an `origin_terminal_id` referencing the pickup/return terminal, a `last_free_day` (an ISO 8601 UTC instant), a `linehaul_base_cents` (the base trucking rate for the move, never negative), and an optional `container_size` of `D20`, `D40`, or `HC40` that defaults to `D40`. A new booking begins in `DRAFT`.

Several booking fields are system-managed and start empty: `chassis_id` is null until a chassis is assigned; `gross_weight_lbs` is null until the container is weighed; `requires_permit` starts false and becomes true once any overweight weigh ticket exists; `scheduled_pickup_at` is null until the first pickup appointment; and `actual_pickup_at` is null until the pickup leg is dispatched. The computed accrual fields `demurrage_estimate_cents`, `demurrage_actual_cents`, and `per_diem_final_cents` all start at zero and are populated at the moments described below.

Confirming a booking advances it from `DRAFT` to `CONFIRMED`; the booking must be in `DRAFT` for this, and the transition increments the booking's `version`. A booking may be canceled from any non-terminal state (`DRAFT`, `CONFIRMED`, `CHASSIS_ASSIGNED`, `APPOINTED`, `DISPATCHED`, or `DELIVERED`), moving it to `CANCELED`; the two terminal states are `EMPTY_RETURNED` and `CANCELED`, and an already-terminal booking cannot be canceled again. The cancellation cascade is described in §3.8.

### 3.3. Chassis Assignment, Supersede, and Release

Assigning a chassis is how a `CONFIRMED` booking becomes `CHASSIS_ASSIGNED`. The dispatcher supplies the `chassis_id` to attach and the `expected_booking_version` for the concurrency check described in §2.7. The target chassis must currently be `AVAILABLE`; if it is not, the request is rejected with `ERR_CHASSIS_UNAVAILABLE`. On success, the booking's `chassis_id` is set to the target chassis, that chassis moves from `AVAILABLE` to `ASSIGNED`, and the booking's `version` increments.

The same operation also serves as a supersede while the booking is already `CHASSIS_ASSIGNED`: it stays in `CHASSIS_ASSIGNED` but swaps chassis. In that case the previously assigned chassis is released from `ASSIGNED` back to `AVAILABLE`, the booking's `chassis_id` is repointed to the new chassis, the new chassis moves from `AVAILABLE` to `ASSIGNED`, and the booking's `version` increments. Both the first assignment and every supersede require `expected_booking_version` to match the booking's current `version`, and both require the incoming chassis to be `AVAILABLE`.

Releasing a chassis is the compensating action while the booking is `CHASSIS_ASSIGNED`, returning it to `CONFIRMED`. This is only permitted while the assigned chassis is still `ASSIGNED` and has not yet gone `OUT`. On release, the assigned chassis moves from `ASSIGNED` back to `AVAILABLE`, the booking's `chassis_id` is cleared, and the booking's `version` increments. Each assignment, supersede, and release also increments the affected chassis's own `version`.

### 3.4. Terminal Appointments and the Demurrage Estimate

An **appointment** reserves a window at a terminal for a booking. It is created with a `booking_id`, a `terminal_id`, a `purpose` of either `PICKUP` or `RETURN`, and a `window_start` and `window_end` where the start is strictly before the end. Appointment windows are treated as half-open intervals `[window_start, window_end)`. A new appointment starts in `BOOKED`; its two terminal states are `USED` and `CANCELED`.

Terminal capacity is enforced at booking time. The system counts the `BOOKED` appointments at that terminal whose half-open window intersects the requested half-open window; if that count is already at or above the terminal's `slot_capacity_per_window`, the request is rejected with `ERR_APPOINTMENT_SLOT_FULL`. Because the intervals are half-open, two windows that merely touch at an endpoint — one ending exactly where the next begins — do not intersect and do not compete for the same slot.

When a pickup appointment is booked for a booking that is currently `CHASSIS_ASSIGNED`, the booking advances to `APPOINTED`. At that moment the booking's `scheduled_pickup_at` is set to the appointment's `window_start`, and the forward-looking **demurrage estimate** is computed and locked into `demurrage_estimate_cents`. The estimate is calculated as follows: take the origin terminal's `demurrage_daily_rate_cents`, multiply it by one plus the port fee percentage of 0.075 (that is, by 1.075), and round that per-day charge half-up to whole cents. Then count the number of whole UTC calendar days strictly after the booking's `last_free_day` up to and including the date of `scheduled_pickup_at` — concretely, the UTC calendar date of `scheduled_pickup_at` minus the UTC calendar date of `last_free_day`, floored at zero. Multiply the already-rounded per-day charge by that integer day count to get `demurrage_estimate_cents`. The rounding is applied to the per-day charge only, before multiplying by the day count; the multiplication of the whole-cent per-day charge by the integer day count is exact. This locked estimate is never recomputed on re-appointment.

Canceling the current pickup appointment reverts the booking from `APPOINTED` back to `CHASSIS_ASSIGNED`, forming a re-appointment loop. Cancellation is only allowed when no non-terminal pickup leg references the appointment. On cancellation the appointment moves from `BOOKED` to `CANCELED`, the booking's `scheduled_pickup_at` is cleared, and the booking's `version` increments; the previously locked `demurrage_estimate_cents` is retained as the original projection. A return-purpose appointment cancellation moves the appointment to `CANCELED` without altering booking status.

### 3.5. Weigh Tickets, Overweight, and Permits

Any time a container is scaled, a dispatcher records a **weigh ticket** with a `booking_id` and the measured `gross_weight_lbs` (never negative). The ticket's `weighed_at` is stamped to the current logical clock, and the ticket computes `is_overweight`: the load is overweight when its `gross_weight_lbs` is strictly greater than the legal limit of 80000 pounds — so 80000 is legal and 80001 is over. Recording a ticket sets the booking's `gross_weight_lbs` to the weighed value, and once any overweight ticket exists for the booking, the booking's `requires_permit` becomes true. A weigh ticket is immutable once written.

When a booking requires a permit, an overweight/oversize **permit** must be requested and approved before the pickup can be dispatched. A permit is requested with a `booking_id`, a `permit_number`, and a `max_gross_weight_lbs` (the maximum gross weight it authorizes, never negative), and it starts in `REQUESTED`. Approving it advances it to `APPROVED`; approval requires the permit to currently be `REQUESTED` and increments the permit's `version`. If a booking's `requires_permit` is true and no `APPROVED` permit exists for it, dispatching its pickup leg is rejected with `ERR_PERMIT_REQUIRED`.

### 3.6. Dispatch: Legs, Driver Availability, and Actual Demurrage

A **leg** is a planned move. A dispatcher creates it with a `booking_id`, a `driver_id`, a `leg_type` of `PICKUP`, `RETURN`, or `STREET_TURN`, and a `window_start` and `window_end` where the start is strictly before the end. A pickup leg must also supply an `appointment_id` linking it to a booked pickup appointment; a street-turn leg must supply a `linked_export_booking_id` naming the export booking that will receive the reused empty and chassis; for a return leg the `appointment_id` is optional. Legs treat their planned window as a closed interval `[window_start, window_end]`. A new leg starts in `PLANNED`, with terminal states `COMPLETED` and `CANCELED`.

At creation the leg is checked against the driver's existing commitments. For the requested driver, if any non-terminal leg's closed window, extended on both sides by a fixed turnaround buffer of `DRIVER_TURNAROUND_BUFFER_MIN` (60) minutes, overlaps the requested window, the create is rejected with `ERR_DRIVER_UNAVAILABLE`. The buffer models the time a driver needs between moves, so two legs that would be legal back-to-back without the buffer still collide if they fall inside it.

**Dispatching** a leg advances it from `PLANNED` to `DISPATCHED`. For a pickup leg this is the pivotal operation and drives the booking from `APPOINTED` to `DISPATCHED`. Several gates apply, in the priority order of §2.6: the booking's `chassis_id` must be set and that chassis must be `ASSIGNED` (else `ERR_CHASSIS_NOT_ASSIGNED`); the linked appointment must be `BOOKED` (else `ERR_APPOINTMENT_NOT_BOOKED`); the assigned driver must be `ACTIVE` (else `ERR_DRIVER_INACTIVE`); if the booking requires a permit, an `APPROVED` permit must exist (else `ERR_PERMIT_REQUIRED`); and the logical clock must be strictly before the linked appointment's `window_end` — at or after that instant the appointment has expired and dispatch is rejected with `ERR_APPOINTMENT_EXPIRED`. A return or street-turn leg carries none of these gates: dispatching it advances the leg from `PLANNED` to `DISPATCHED` after verifying only that the leg is `PLANNED` and the assigned driver is `ACTIVE` (else `ERR_DRIVER_INACTIVE`), with no chassis, appointment, permit, or expiry checks and no change to the booking's status.

On a successful pickup dispatch, five things happen together: the leg moves from `PLANNED` to `DISPATCHED`; the linked appointment moves from `BOOKED` to `USED`; the assigned chassis moves from `ASSIGNED` to `OUT` and its `assigned_out_at` is set to the current clock; the booking's `actual_pickup_at` is set to the current clock; and the booking's **actual demurrage** is computed into `demurrage_actual_cents`. The actual demurrage uses the identical formula and pinned rounding order as the estimate — the terminal's `demurrage_daily_rate_cents` times 1.075, rounded half-up to a whole-cent per-day charge, multiplied by the whole UTC calendar days strictly after `last_free_day` — but its basis is `actual_pickup_at` (the logical clock at dispatch) rather than `scheduled_pickup_at`. That is, the day count is the UTC calendar date of `actual_pickup_at` minus the UTC calendar date of `last_free_day`, floored at zero. This whole pickup dispatch increments the booking's `version`, and it also increments the leg's and the chassis's `version`.

### 3.7. Completion: POD, Empty Return, Street Turn, and Per-Diem

Completing a leg advances it from `DISPATCHED` to `COMPLETED`, and the effect diverges by `leg_type`. Completion may be performed by a dispatcher or by the owning driver, and each completion increments the leg's `version`.

**Pickup completion** captures proof of delivery. It requires the leg to be `DISPATCHED` and of `leg_type` `PICKUP`, and it advances the owning booking from `DISPATCHED` to `DELIVERED`, incrementing the booking's `version`.

**Return completion** is the empty-return that closes the move. It requires the leg to be of `leg_type` `RETURN`, the owning booking to be `DELIVERED`, and the assigned chassis to be `OUT`. Completing it triggers the empty-return chain in full: the assigned chassis moves from `OUT` to `AVAILABLE`, its `returned_at` is set to the current clock, and its **final per-diem** is computed into `per_diem_final_cents`; that in turn stamps the owning booking's `per_diem_final_cents` from the chassis's finalized figure and advances the booking from `DELIVERED` to `EMPTY_RETURNED`. The per-diem calculation counts the whole UTC calendar days a chassis has been out — the UTC calendar date of the basis minus the UTC calendar date of `assigned_out_at`, floored at zero — then subtracts the chassis's `free_days`, flooring that result at zero as well, and multiplies the remaining chargeable days by the chassis's `per_diem_rate_cents`. For the final figure the basis is the chassis's `returned_at`. While a chassis is `OUT`, reading it computes `per_diem_provisional_cents` on the fly using the same formula with the current logical clock as the basis; the provisional figure is zero whenever the chassis is not `OUT`, and the final figure stays zero until the chassis returns.

**Street-turn completion** reuses the empty container and chassis directly on an export booking instead of returning them to the terminal. It requires the leg to be of `leg_type` `STREET_TURN`, the owning (import) booking to be `DELIVERED`, and the `linked_export_booking_id` to refer to an `EXPORT` booking currently in `CONFIRMED`. On completion the import booking advances from `DELIVERED` to `EMPTY_RETURNED` without the chassis ever being returned to the terminal; the chassis stays `OUT` and is reassigned to the export booking — the export booking's `chassis_id` is set to this chassis and the export booking advances from `CONFIRMED` to `CHASSIS_ASSIGNED`. The import booking's `per_diem_final_cents` is stamped from the chassis's `per_diem_final_cents` computed as of the current clock, and per-diem continues to accrue thereafter under the export booking, since the chassis was never released.

Canceling a leg (whether requested directly or driven by a booking cancellation) moves it from `PLANNED` or `DISPATCHED` to `CANCELED`. If that leg had taken its chassis `OUT` on a pickup dispatch and the chassis is still `OUT`, canceling the leg releases the chassis from `OUT` back to `AVAILABLE`, sets its `returned_at` to the current clock, and finalizes its per-diem — the same release-and-finalize the empty return performs.

### 3.8. Cancellation Cascades

Canceling a booking is a single request with a fan-out. The booking moves to `CANCELED`, and every non-terminal leg of that booking is canceled as well; each such leg then runs its own cancellation side-effects. In practice this means a booking that has already dispatched its pickup — so its chassis is `OUT` — will, on cancellation, cancel that pickup leg, which releases the chassis from `OUT` back to `AVAILABLE`, stamps the chassis's `returned_at`, and finalizes the chassis's per-diem. The booking's `version` increments as part of the cancellation. This is the second cascade direction referenced in §2.8: booking to leg to chassis.

### 3.9. Billing: Invoices and Accessorials

Billing is the biller's domain. An **invoice** is generated for a booking and computes every line item at generation time. Generation is only allowed when the booking's `status` is `DELIVERED` or `EMPTY_RETURNED` and no invoice already exists for that booking; otherwise the request is rejected with `ERR_NOT_INVOICEABLE`. A new invoice starts in `DRAFT`, with the sole other state being `ISSUED`.

At generation the invoice snapshots and derives its line items in this pinned order — discount, then fuel, then sum, then floor. First, `linehaul_base_cents` on the invoice is snapshotted from the booking's `linehaul_base_cents`. Next, `effective_linehaul_cents` is derived: if the booking's `linehaul_base_cents` is at least the volume threshold of 100000 cents, the effective linehaul is the base multiplied by one minus the volume discount of 0.10 (that is, by 0.90), rounded half-up to whole cents; otherwise the effective linehaul equals the base unchanged. Then `fuel_surcharge_cents` is the effective linehaul multiplied by the fuel percentage of 0.22, rounded half-up to whole cents independently of the discount rounding. The `accessorials_total_cents` is the sum of `amount_cents` over the invoice's `ACTIVE` accessorial charges. The `demurrage_cents` is snapshotted from the booking's `demurrage_actual_cents`, and `per_diem_cents` is snapshotted from the booking's `per_diem_final_cents` (which is zero unless the booking has reached `EMPTY_RETURNED`). The subtotal is the sum of `effective_linehaul_cents`, `fuel_surcharge_cents`, `accessorials_total_cents`, `demurrage_cents`, and `per_diem_cents`. Finally, `total_charge_cents` is the greater of that subtotal and the minimum charge of 50000 cents.

While an invoice is `DRAFT`, a biller may add **accessorial charge** lines, each with a `kind` of `CHASSIS_RENTAL`, `PRE_PULL`, `STORAGE`, `HAZMAT`, or `REEFER` and an `amount_cents` (never negative). A new accessorial line's `invoice_id` is taken from the path, and it starts `ACTIVE`. A biller may void an `ACTIVE` line, identified by its `accessorial_id` in the path, moving it to `VOIDED`. Adding a line and voiding a line each recompute the parent invoice's `accessorials_total_cents` and `total_charge_cents` using the same aggregation and floor described above, and each increments the affected line's `version`. Adding or voiding is only permitted while the parent invoice is `DRAFT`; attempting either on a non-`DRAFT` invoice is rejected with `ERR_NOT_INVOICEABLE`. Issuing an invoice advances it from `DRAFT` to `ISSUED`, freezes its accessorials so none can be added or voided afterward, and increments the invoice's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including state-transition actions and the logical-clock setter, return `200 OK`. All read operations return `200 OK`. The request body, response body, and side effects of each endpoint are described in the workflow narratives of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Dispatcher |
| POST | `/terminals` | Register a terminal | Dispatcher |
| GET | `/terminals/{id}` | Get a terminal | Dispatcher, Biller, Driver |
| POST | `/chassis` | Register a chassis into the pool | Dispatcher |
| GET | `/chassis/{id}` | Get a chassis (provisional per-diem at read time) | Dispatcher, Biller, Driver |
| POST | `/drivers` | Register a driver | Dispatcher |
| GET | `/drivers/{id}` | Get a driver | Dispatcher, Biller, Driver |
| POST | `/bookings` | Create a container booking | Dispatcher |
| GET | `/bookings/{id}` | Get a booking with derived accrual fields | Dispatcher, Biller, Driver |
| GET | `/bookings` | List bookings | Dispatcher, Biller, Driver |
| POST | `/bookings/{id}/confirm` | Confirm a booking | Dispatcher |
| POST | `/bookings/{id}/assign-chassis` | Assign or supersede the chassis (OCC-guarded) | Dispatcher |
| POST | `/bookings/{id}/release-chassis` | Release the assigned chassis before pickup | Dispatcher |
| POST | `/bookings/{id}/cancel` | Cancel a booking (cascades) | Dispatcher |
| POST | `/weigh-tickets` | Record a scale weigh ticket | Dispatcher |
| GET | `/weigh-tickets/{id}` | Get a weigh ticket | Dispatcher, Biller, Driver |
| GET | `/weigh-tickets` | List weigh tickets | Dispatcher, Biller, Driver |
| POST | `/appointments` | Book a terminal appointment window | Dispatcher |
| GET | `/appointments/{id}` | Get an appointment | Dispatcher, Biller, Driver |
| GET | `/appointments` | List appointments | Dispatcher, Biller, Driver |
| POST | `/appointments/{id}/cancel` | Cancel an appointment | Dispatcher |
| POST | `/legs` | Create a dispatch leg | Dispatcher |
| GET | `/legs/{id}` | Get a leg | Dispatcher, Biller, Driver |
| GET | `/legs` | List legs | Dispatcher, Biller, Driver |
| POST | `/legs/{id}/dispatch` | Dispatch a leg | Dispatcher |
| POST | `/legs/{id}/complete` | Complete a leg (POD / empty return / street turn) | Dispatcher, Driver |
| POST | `/legs/{id}/cancel` | Cancel a leg | Dispatcher |
| POST | `/permits` | Request an overweight permit | Dispatcher |
| GET | `/permits/{id}` | Get a permit | Dispatcher, Biller, Driver |
| GET | `/permits` | List permits | Dispatcher, Biller, Driver |
| POST | `/permits/{id}/approve` | Approve a permit | Dispatcher |
| POST | `/invoices` | Generate an invoice for a booking | Biller |
| GET | `/invoices/{id}` | Get an invoice | Dispatcher, Biller, Driver |
| GET | `/invoices` | List invoices | Dispatcher, Biller, Driver |
| POST | `/invoices/{id}/issue` | Issue (freeze) an invoice | Biller |
| POST | `/invoices/{id}/accessorials` | Add an accessorial charge to a DRAFT invoice | Biller |
| GET | `/invoices/{id}/accessorials` | List accessorial charges of an invoice | Dispatcher, Biller, Driver |
| POST | `/invoices/{id}/accessorials/{accessorial_id}/void` | Void an accessorial charge | Biller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_LEG_NOT_OWNED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_TERMINAL_NOT_FOUND` | 404 |
| `ERR_CHASSIS_NOT_FOUND` | 404 |
| `ERR_DRIVER_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_LEG_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_WEIGH_TICKET_NOT_FOUND` | 404 |
| `ERR_ACCESSORIAL_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PERMIT_REQUIRED` | 422 |
| `ERR_CHASSIS_UNAVAILABLE` | 409 |
| `ERR_CHASSIS_NOT_ASSIGNED` | 409 |
| `ERR_APPOINTMENT_NOT_BOOKED` | 409 |
| `ERR_DRIVER_INACTIVE` | 409 |
| `ERR_APPOINTMENT_EXPIRED` | 422 |
| `ERR_APPOINTMENT_SLOT_FULL` | 409 |
| `ERR_DRIVER_UNAVAILABLE` | 409 |
| `ERR_NOT_INVOICEABLE` | 409 |
| `ERR_STALE_BOOKING_VERSION` | 412 |

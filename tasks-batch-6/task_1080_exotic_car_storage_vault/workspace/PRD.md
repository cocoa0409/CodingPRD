# Exotic Car Storage Vault API — Product Requirements Document

## 1. Introduction

Collectors of exotic and seasonal automobiles need more than a parking space; they need a climate-controlled vault that treats each vehicle as a high-value asset under continuous custody. This document specifies the backend API for such a facility. The platform manages the full custody chain: intake and condition documentation of each vehicle, assignment of storage units seasonally reserved over date windows, climate and battery-tender monitoring, concierge in-and-out and detailing services, event delivery by contracted transporters, insurance-certificate tracking, a membership program with tiered pricing, a promotion-driven waitlist, and the billing engine that ties it all together.

The system serves four distinct operator perspectives. Members book storage for the cars they own, request services, and settle their invoices. Vault managers run the facility floor: they open units, create and terminate agreements, approve work, and revoke insurance certificates. Concierge technicians perform the physical work — starting engines, detailing, recording battery readings, and driving cars to events. Billing administrators generate and issue invoices, record payments, and keep each member's billing health current. Because money, physical occupancy, and safety guarantees are all in play simultaneously, the specification is deliberate about ordering of checks, cascading side effects when one entity changes another, and the concurrency controls that keep two operators from booking the same unit against a stale view of its schedule.

A note on time: the platform runs on a **logical clock** rather than wall-clock time so that seasonal windows, offer deadlines, and billing due dates can be exercised deterministically. All deadline, expiry, window-coverage, and proration rules read this logical clock. Its startup default is `2026-05-01T00:00:00Z`, and until it is explicitly advanced it reads exactly that value and never falls back to the host's wall clock.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling principal, and `X-User-Role`, naming the role under which the call is made. If either header is missing, or if `X-User-Role` is not one of the four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly `Member`, `VaultManager`, `ConciergeTech`, and `BillingAdmin`.

- **`Member`** is an entity-backed role: when `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member` record. Ownership checks on any resource that references a member compare that resource's owning member to `X-User-ID`. A member may act only on their own vehicles, agreements, certificates of insurance, waitlist entries, service and delivery requests, and invoices; an attempt to act on a resource owned by another member is rejected with `ERR_UNAUTHORIZED`. Ownership of a vehicle is determined by its `member_id`; ownership of an agreement, waitlist entry, or invoice by its `member_id`; ownership of a delivery job by the `member_id` of the referenced vehicle's owner; ownership of a service order by the member on its parent agreement; ownership of a certificate of insurance by the owner of its `vehicle_id`.
- **`VaultManager`** is an opaque role: when `X-User-Role` is `VaultManager`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`.
- **`ConciergeTech`** is likewise opaque: `X-User-ID` is a technician identifier the server does not match against any entity `id`.
- **`BillingAdmin`** is likewise opaque: `X-User-ID` is a billing-operator identifier not matched against any entity `id`.

The precise set of operations each role may invoke is given per-endpoint in §4. Read (GET) endpoints are available to all four roles.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; a requested `limit` above 100 is clamped to 100. `offset` defaults to 0 and has a minimum of 0. Results are always returned sorted by `created_at` in ascending order (oldest first). The `meta` block of a list response carries `limit`, `offset`, `total_count` (the total number of matching records before the page window is applied), and `has_more` (true when records remain beyond the current page).

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Resources that can be mutated after creation additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 and increments by 1 on each mutation. All entities in this system are mutable and therefore carry all four common properties.

Timestamps supplied by clients — coverage windows, occupancy windows, delivery windows, billing periods, and the clock-set value — are ISO 8601 UTC strings. Wherever a rule speaks of "now," "the current time," a deadline, an expiry, or whether a window "covers" the present, it means the value of the logical clock described in §1, never the host wall clock.

### 2.5. Optimistic Concurrency on Unit Bookings

Creating a storage agreement reserves a seasonal booking window on a specific storage unit, and the platform guards that reservation with optimistic concurrency control. The create-agreement request must include `expected_unit_version` carrying the client's last observed `version` of the target storage unit. If that value does not equal the unit's current `version` — for example because another agreement has since recorded its own non-overlapping booking window on the same unit and thereby advanced the unit's `version` — the create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412). This prevents a writer from committing an agreement against a booking schedule it has not actually observed. No other endpoint takes a version field.

### 2.6. Monetary Precision, Rounding, and Tax Assembly

All money is stored and returned in whole integer cents. Wherever a monetary formula produces a fractional cent, the result is rounded half up to the nearest whole cent (a value ending in exactly one-half cent rounds away from zero). Counts (such as facility unit tallies and days stored) are plain integers.

Invoice tax assembly follows a **pinned rounding order**: tax is computed **per line** and then summed. For each line item, the line's tax is the line amount multiplied by the tax rate, rounded half up to whole cents; the invoice `tax_cents` is the sum of these per-line rounded tax figures. This is deliberately **not** the tax rate applied once to the invoice subtotal — at fractional-cent lines the two approaches diverge, and only the per-line-then-sum result is correct.

### 2.7. Facility Occupancy Accounting and State Propagation

A facility continuously reports how its units are distributed across statuses. Whenever any storage unit under a facility changes status — on unit creation, on a waitlist offer reserving it, on move-in occupying it, on release back to available, or on a service-status change — the facility's four counters are recomputed from scratch: `units_available`, `units_reserved`, `units_occupied`, and `units_out_of_service` each equal the number of units under that facility currently in the corresponding status. These four counters always sum to the total number of storage units under the facility; that conservation identity must hold after every operation.

Many operations in this system mutate more than one entity. Whenever a mutation changes an entity, that entity's `updated_at` is refreshed and its `version` is incremented by 1. Cascades are spelled out in the workflow narratives of §3; the governing principle is that the primary transition and every secondary effect it triggers are applied together as one logical operation, and each touched entity has its own `version` bumped.

### 2.8. Resource Resolution and Validation Ordering

Requests are validated in a fixed priority order, and the first failing check determines the error returned. The order is:

1. **Authentication** — headers present and role known, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** — the role may perform this operation, and an entity-backed `Member` owns the resource it acts on, else `ERR_UNAUTHORIZED` (403).
3. **Existence** — every resource named in the path, then every foreign key in the body, must exist; path parameters are resolved left to right. A missing resource yields `ERR_NOT_FOUND` (404).
4. **Request validity** — required body fields present and well-typed, and every enum value within its allowed set, else `ERR_INVALID_REQUEST` (422).
5. **Uniqueness** — else `ERR_DUPLICATE` (409), as detailed below.
6. **State validity** — the target resource is in a legal state for the requested transition, else `ERR_INVALID_STATE` (409).
7. **Cross-entity state** — a required state on a related entity holds, else `ERR_CROSS_ENTITY_STATE` (409).

Beyond this generic spine, individual operations layer domain checks (temporal overlaps, insurance, coverage, fiscal, capacity, and concurrency) whose relative ordering is described where those operations appear in §3. For nested read paths such as a facility's units or a member's vehicles, the parent in the path is resolved before the child collection is filtered; a non-existent parent yields `ERR_NOT_FOUND`.

### 2.9. Membership Tiers and the Fiscal Gate

Each member belongs to one of four membership tiers — `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM` — which drives their storage discount, and carries an independent billing-health dimension — `CURRENT`, `PAST_DUE`, or `SUSPENDED` — tracked in `billing_status`. The two dimensions are orthogonal: tier governs pricing, billing status governs whether the member may incur new charges. A member whose `billing_status` is `SUSPENDED` is blocked from all chargeable operations — creating a storage agreement, requesting a service order, and creating a delivery job — with `ERR_MEMBER_SUSPENDED` (HTTP 402). The tiers, their discount rates, billing-health transitions, and the money invariants are detailed in §3.9.

## 3. Business Logic & Workflows

### 3.1. Facilities, Storage Units, and Seasonal Bookings

A vault manager opens the system by creating a **facility**, supplying its `name` and its `total_units` — the capacity ceiling representing how many physical storage units the building holds. At creation the four occupancy counters (`units_available`, `units_reserved`, `units_occupied`, `units_out_of_service`) are all initialized to zero and grow as units are added.

Units are added one at a time under a facility. Each **storage unit** records the `facility_id` it belongs to, a `unit_code` (a human-readable label that must be unique among the units of that facility — a collision is rejected with `ERR_DUPLICATE`), a `unit_class`, and a `monthly_rate_cents` base storage rate that must be zero or greater. The `unit_class` is one of `STANDARD`, `CLIMATE`, or `SHOWCASE`; from it the system derives the boolean `climate_controlled`, which is true when the class is `CLIMATE` or `SHOWCASE` and false for `STANDARD`. A newly created unit starts with `status` `AVAILABLE`, and the facility counters are recomputed. Creating a unit is refused with `ERR_FACILITY_UNIT_LIMIT` (409) when the facility already holds `total_units` units — the count of a facility's units may never exceed its ceiling.

The unit `status` — `AVAILABLE`, `RESERVED`, `OCCUPIED`, or `OUT_OF_SERVICE` — tracks **current physical occupancy only**, not future bookings. This is the crucial distinction of this domain: units are seasonally interval-booked. When an agreement is created it records a booking window on the unit and bumps the unit's `version`, but it does **not** change the unit's `status`. `RESERVED` is used exclusively to hold a unit for a waitlist offer. A unit becomes `OCCUPIED` only at move-in and returns to `AVAILABLE` only at termination.

A vault manager can take an idle unit out of service or restore it by supplying an `in_service` flag. When `in_service` is false, a unit in `AVAILABLE` transitions to `OUT_OF_SERVICE`; when `in_service` is true, a unit in `OUT_OF_SERVICE` transitions back to `AVAILABLE`, and that restoration re-runs waitlist promotion on the unit (see §3.7). A service-status change from any other starting status is an illegal transition and is rejected with `ERR_INVALID_STATE`. Either way the facility counters are recomputed.

Facilities and units are readable individually, and a facility's units can be listed; that listing accepts an optional `status` filter to narrow the returned units to a single occupancy status.

### 3.2. Members, Vehicles, Intake, and Certificates of Insurance

A member is registered with a `full_name`, an `email` (unique across all members — a duplicate is rejected with `ERR_DUPLICATE`), and an optional `membership_tier`; when the tier is omitted the member defaults to `BRONZE`. Registration sets `billing_status` to `CURRENT`. The member's computed money fields — `charged_cents`, `paid_cents`, `held_cents`, and `account_balance_cents` — all begin at zero and are maintained as described in §3.9, and `tier_discount_pct` is derived from the tier (see §3.9). Either a vault manager or a billing administrator may register a member. A member record can be read to expose those computed balances, and a member's vehicles and waitlist entries can each be listed.

A **vehicle** is added under an owning member. Its payload carries `member_id` (the owner), `make`, `model`, `model_year`, `vin` (the vehicle identification number, unique across all vehicles — a duplicate raises `ERR_DUPLICATE`), `fuel_type`, and `declared_value_cents` (the owner-declared value, zero or greater, which later governs insurance-coverage adequacy). The `fuel_type` is one of `ICE`, `HYBRID`, or `EV`. A newly added vehicle starts with `condition_status` `INTAKE_PENDING` and `insurance_status` `NONE`. A member may add vehicles for themselves; a vault manager may also add vehicles.

The `condition_status` — `INTAKE_PENDING`, `DOCUMENTED`, or `DAMAGE_HOLD` — reflects intake and damage state. Intake is completed by passing an `INTAKE` inspection, which advances the vehicle from `INTAKE_PENDING` to `DOCUMENTED` (see §3.8); a vehicle must be `DOCUMENTED` before it can move into storage. A failed inspection drives the vehicle into `DAMAGE_HOLD`, which blocks service starts and move-in until a later intake inspection passes.

The `insurance_status` — `NONE`, `ACTIVE`, or `LAPSED` — is computed from the vehicle's certificates of insurance. It is `ACTIVE` exactly when the vehicle has a certificate in `ACTIVE` status whose coverage window covers the logical clock; it is `LAPSED` when the vehicle once had such a certificate that is now `EXPIRED` or `REVOKED` and has no other active covering certificate; otherwise it is `NONE`.

A **certificate of insurance** (COI) is attached to a vehicle with a `policy_number`, a `carrier`, a `coverage_amount_cents` (zero or greater), an `effective_at` marking the inclusive start of the coverage window, and an `expiry_at` marking the exclusive end. A certificate starts in `status` `ACTIVE`; attaching it recomputes the vehicle's `insurance_status`, which becomes `ACTIVE` if the certificate's window covers the current logical clock (that is, the clock is at or after `effective_at` and strictly before `expiry_at`). A member may attach a certificate to their own vehicle, as may a vault manager. A vehicle's certificates and inspections can each be listed.

Certificates leave `ACTIVE` in two ways. A vault manager may **revoke** a certificate, moving it from `ACTIVE` to `REVOKED`; revoking a certificate in any other status is rejected with `ERR_INVALID_STATE`. Alternatively, a certificate expires by the passage of time: refreshing a vehicle's insurance moves every `ACTIVE` certificate whose `expiry_at` is at or before the logical clock to `EXPIRED`. Both paths then recompute the vehicle's `insurance_status`, and both carry the same two-link cascade: when the recomputation leaves the vehicle without any active covering certificate, its `insurance_status` becomes `LAPSED`, and that lapse in turn auto-cancels every delivery job for that vehicle that is still in `SCHEDULED` status, moving each to `CANCELLED` and releasing the transporter window it held (see §3.6). Refreshing insurance is available to a vault manager or a concierge technician.

### 3.3. The Storage Agreement Lifecycle

A **storage agreement** is the contract that binds a member, one of their vehicles, and a storage unit over a season. A vault manager creates it, supplying `member_id`, `vehicle_id`, `unit_id`, `move_in_at` (the inclusive occupancy start), `planned_move_out_at` (the exclusive planned end, used for overlap detection), and `expected_unit_version` for the concurrency guard of §2.5. On creation the agreement's `monthly_rate_cents` is computed and snapshotted from the storage-fee formula (see §3.9), its `status` is `PENDING`, its `actual_move_out_at` and `days_stored` are left null until it closes, and the chosen booking window `[move_in_at, planned_move_out_at)` is recorded on the unit. Recording that window increments the unit's `version` by 1 but leaves the unit's `status` unchanged — the reservation is a schedule entry, not physical occupancy.

Several checks guard agreement creation, layered on top of the generic spine of §2.8. Because creating an agreement is a chargeable operation, a member whose `billing_status` is `SUSPENDED` is blocked with `ERR_MEMBER_SUSPENDED`. The proposed window `[move_in_at, planned_move_out_at)` is treated as a half-open interval and must not overlap the window of any non-terminal agreement already on that same unit; an overlap is rejected with `ERR_UNIT_OVERLAP` (409). Two windows that merely touch at an endpoint — one ending exactly when the next begins — do not overlap and are both allowed. Finally the optimistic-concurrency check of §2.5 compares `expected_unit_version` against the unit's current `version`, rejecting a mismatch with `ERR_STALE_UNIT_VERSION` (412).

An agreement moves through its life on the `status` field: `PENDING`, `IN_STORAGE`, `CHECKED_OUT`, `CLOSED`, or `CANCELLED`. A vault manager activates a `PENDING` agreement by **moving the vehicle in**, transitioning `PENDING → IN_STORAGE`. Move-in requires that the agreement is `PENDING`, that the assigned unit's `status` is `AVAILABLE` or `RESERVED` — not currently `OCCUPIED` by another agreement, else `ERR_UNIT_NOT_AVAILABLE` (409) — and that the vehicle's `condition_status` is `DOCUMENTED`, else the cross-entity precondition fails with `ERR_CROSS_ENTITY_STATE` (409). On success the assigned unit transitions from `AVAILABLE` or `RESERVED` to `OCCUPIED`, and the facility counters are recomputed.

Once in storage, the vehicle cycles in and out. **Checking out** advances the agreement `IN_STORAGE → CHECKED_OUT` and represents the car physically leaving while the unit stays `OCCUPIED`, held for its return; **checking in** advances `CHECKED_OUT → IN_STORAGE`. Either transition may be performed by the owning member or by a concierge technician. Check-out is blocked with `ERR_AGREEMENT_HAS_ACTIVE_SERVICE` (409) while any service order on the agreement is `IN_PROGRESS` or `ON_HOLD`. Attempting either transition from the wrong status is an `ERR_INVALID_STATE`.

A vault manager **terminates** an agreement to close it out, transitioning from either `IN_STORAGE` or `CHECKED_OUT` to `CLOSED`. Termination is blocked with `ERR_AGREEMENT_HAS_ACTIVE_SERVICE` while any service order on the agreement is `IN_PROGRESS` or `ON_HOLD`. On success `actual_move_out_at` is set to the logical clock and `days_stored` is computed as the whole number of days from `move_in_at` to `actual_move_out_at`, rounded down (floored) to a whole day; this figure feeds final proration. Termination then runs a three-link cascade: first, every `ACTIVE` monitoring subscription on the agreement is moved to `CANCELLED`; second, the assigned unit is released from `OCCUPIED` back to `AVAILABLE` (its `version` bumped and facility counters recomputed); and third, that unit becoming available runs waitlist promotion, offering the unit to the top-ranked eligible waiting entry if one exists (see §3.7).

A `PENDING` agreement that never activated can instead be **cancelled** by the owning member or a vault manager, transitioning `PENDING → CANCELLED`; this releases the booking window held on the unit and increments the unit's `version` by 1. Cancelling from any status other than `PENDING` is an `ERR_INVALID_STATE`. Agreements are readable individually and listable with optional `member_id`, `vehicle_id`, `unit_id`, and `status` filters.

### 3.4. Climate Monitoring and Battery Tending

A stored car under a long seasonal agreement is kept healthy by a **monitoring subscription**. A concierge technician or a vault manager adds one to an agreement, supplying `monitor_type` — one of `BATTERY_TENDER`, `CLIMATE`, or `BOTH` — and a `monthly_fee_cents` add-on charge (zero or greater). The subscription's `status` starts `ACTIVE`; its `last_battery_voltage` is null until the first reading is recorded, and its `low_battery_alert` flag starts false.

A concierge technician records a battery-tender reading by supplying a `battery_voltage` value. Recording sets `last_battery_voltage` to that value and recomputes `low_battery_alert`, which becomes true when the most recent reading is below the minimum healthy battery voltage of 12.4 volts and false when the reading is at or above that threshold. Monitoring subscriptions on an agreement can be listed.

A subscription's only non-manual exit is a cascade: when the parent agreement is terminated, every subscription on it that is still `ACTIVE` is moved to `CANCELLED`, at which point it stops accruing monitoring fees and no longer appears on subsequent invoices.

### 3.5. Service Orders

While a car is in storage, work is performed through **service orders**. A member (on their own agreement) or a vault manager requests one, supplying the `agreement_id`, the `service_type` — one of `DETAIL`, `START_ENGINE`, `CHECKOUT`, `CHECKIN`, or `FUEL` — and an `estimated_labor_hours` quote (zero or greater). A new order starts in `status` `REQUESTED`, and its `parts_cents` defaults to 0. Its `estimated_cost_cents` and `final_cost_cents` are computed later and are null until then; `scheduled_at` is likewise set later.

A vault manager dispositions a requested order by approving or rejecting it. **Approval** advances `REQUESTED → APPROVED`, requires that the parent agreement's `status` is `IN_STORAGE` or `CHECKED_OUT`, records the supplied `scheduled_at` service time, computes the provisional `estimated_cost_cents` (see §3.9), and recomputes the member's held funds by adding that estimate. **Rejection** advances `REQUESTED → REJECTED` and has no financial effect. Approving or rejecting an order that is not `REQUESTED` is an `ERR_INVALID_STATE`; approving when the parent agreement is in neither storage state fails the cross-entity precondition with `ERR_CROSS_ENTITY_STATE`.

A concierge technician **starts** work, advancing an order from `APPROVED` to `IN_PROGRESS`. The same start action also resumes a paused order, advancing `ON_HOLD → IN_PROGRESS`. Starting requires that the parent agreement's `status` is `IN_STORAGE` — work cannot begin while the vehicle is `CHECKED_OUT`, and a violation is a cross-entity failure with `ERR_CROSS_ENTITY_STATE` — and that the vehicle's `condition_status` is not `DAMAGE_HOLD`. A technician may **hold** work in progress, advancing `IN_PROGRESS → ON_HOLD`; a held order still counts toward the member's held funds. Starting from a status that is neither `APPROVED` nor `ON_HOLD`, or holding an order that is not `IN_PROGRESS`, is an `ERR_INVALID_STATE`.

A technician **completes** an order from `IN_PROGRESS`, supplying `actual_labor_hours` (required at completion) and optionally `parts_cents`. Completion advances `IN_PROGRESS → COMPLETED`, computes the `final_cost_cents` from the final formula variant (which uses actual hours and adds parts — see §3.9), recomputes the member's held funds by removing this order's estimate, and makes a `SERVICE` line for `final_cost_cents` eligible for the member's next invoice. If `actual_labor_hours` is absent the request is rejected as invalid.

An order that has not begun real work may be **cancelled** by the owning member or a vault manager from `REQUESTED`, `APPROVED`, or `ON_HOLD`, moving it to `CANCELLED`. If the order was `APPROVED` or `ON_HOLD` at the time (that is, its estimate was being held), cancellation recomputes the member's held funds by removing that estimate; this compensating release leaves the member's `account_balance_cents` unchanged. Cancelling from any other status is an `ERR_INVALID_STATE`. Service orders can be read individually and listed per agreement.

### 3.6. Event Delivery and Transport Scheduling

Members send their cars to shows and events via **delivery jobs** executed by **transporters**. A vault manager registers a transporter with a `name` and an optional `buffer_minutes` — the idle buffer for travel and cleanup required between that transporter's back-to-back jobs, defaulting to 60 minutes and never negative. A transporter starts in `status` `ACTIVE`.

A member (for their own vehicle) or a vault manager schedules a delivery, supplying `vehicle_id`, `transporter_id`, an `event_name`, a `pickup_at`, and a `dropoff_at`. The job's occupied interval on the transporter runs from `pickup_at` to `dropoff_at` as a closed interval, extended by `buffer_minutes` after `dropoff_at`. A new job starts in `status` `SCHEDULED` and reserves that window.

Delivery creation enforces three domain guards beyond the generic spine, in addition to the fiscal gate (a `SUSPENDED` member is blocked with `ERR_MEMBER_SUSPENDED`, since scheduling a delivery is chargeable). First, the requested window must not conflict with another job on the same transporter: the closed interval `[pickup_at, dropoff_at]` plus the trailing `buffer_minutes` must not overlap any existing job's occupied window on that transporter, else `ERR_TRANSPORTER_CONFLICT` (409). Second, the vehicle's `insurance_status` must be `ACTIVE`, else `ERR_INSURANCE_LAPSED` (409). Third, the coverage on the vehicle's active certificate must be adequate: its `coverage_amount_cents` must be greater than or equal to the vehicle's `declared_value_cents`, else `ERR_COVERAGE_INSUFFICIENT` (409).

A concierge technician **dispatches** a scheduled job, advancing `SCHEDULED → OUT_FOR_EVENT`; dispatch re-checks that the vehicle's `insurance_status` is still `ACTIVE`, rejecting with `ERR_INSURANCE_LAPSED` if the coverage has since lapsed. The technician later **returns** the vehicle, advancing `OUT_FOR_EVENT → RETURNED` and releasing the transporter's window for that interval. A job may be **cancelled** by the owning member or a vault manager from either `SCHEDULED` or `OUT_FOR_EVENT`, moving it to `CANCELLED` and releasing the transporter window. Beyond these manual paths, the system itself cancels a `SCHEDULED` job when the vehicle's insurance lapses, as part of the certificate cascade of §3.2. Dispatching, returning, or cancelling from an incompatible status is an `ERR_INVALID_STATE`. Delivery jobs are readable individually and listable with optional `vehicle_id`, `transporter_id`, and `status` filters; transporters are readable individually.

### 3.7. The Waitlist and Unit Promotion

When no unit of a desired class is free, a member joins a **waitlist**. The join payload carries `member_id`, `facility_id`, and `desired_unit_class` (one of `STANDARD`, `CLIMATE`, or `SHOWCASE`). A join is permitted only when the facility currently has zero `AVAILABLE` units of that class — if an available unit of the desired class already exists, the join is rejected with `ERR_UNITS_AVAILABLE` (409) because the member should simply take that unit. A new entry starts in `status` `WAITING`, with `offered_unit_id` and `offer_expires_at` both null. Only a member may join the waitlist, and only a member may later claim an offer.

Whenever a storage unit becomes `AVAILABLE` — through agreement termination, cancellation of a pending agreement, expiry of a prior offer, or restoration of an out-of-service unit — the system runs **waitlist promotion** against that unit. The candidate set is every entry in `WAITING` status whose `facility_id` matches the unit's facility and whose `desired_unit_class` matches the unit's `unit_class`. Candidates are ranked by membership tier first, highest tier first, using the ranking `PLATINUM` above `GOLD` above `SILVER` above `BRONZE`; ties between two candidates of the same tier are broken by earlier `created_at` first. The single top-ranked candidate is selected and promoted. If the candidate set is empty, no offer is made and the unit simply stays `AVAILABLE`.

Promotion transitions the selected entry `WAITING → OFFERED`: its `offered_unit_id` is set to the released unit, the unit itself transitions `AVAILABLE → RESERVED` (its `version` bumped and facility counters recomputed), and `offer_expires_at` is set to 48 hours after the moment of the offer (the logical clock plus the offer time-to-live).

A member **claims** an offered unit, advancing the entry `OFFERED → CLAIMED`, provided the logical clock is strictly before `offer_expires_at`; a claim at or after the deadline is rejected with `ERR_OFFER_EXPIRED` (409). A claimed entry entitles the member to a storage agreement on the reserved unit, which stays `RESERVED` to them. An offer that is never claimed lapses: refreshing an offer moves an `OFFERED` entry whose `offer_expires_at` is at or before the logical clock to `EXPIRED`, returns the held unit `RESERVED → AVAILABLE`, and re-runs promotion so the next-ranked waiting entry can be offered. A member or vault manager may **cancel** an entry from `WAITING` or `OFFERED`, moving it to `CANCELLED`; if it was `OFFERED`, the held unit is returned `RESERVED → AVAILABLE` and promotion is re-run. Claiming, cancelling, or refreshing an entry that is not in a compatible status is an `ERR_INVALID_STATE`. Waitlist entries are readable individually and listable with optional `member_id`, `facility_id`, `offered_unit_id`, and `status` filters.

### 3.8. Inspections

An **inspection** documents a vehicle's condition at defined moments. A concierge technician or a vault manager schedules one for a vehicle, supplying `vehicle_id` and `inspection_type` — one of `INTAKE`, `PERIODIC`, or `CHECKOUT`. It starts in `status` `SCHEDULED`.

A scheduled inspection is closed by passing or failing it; both actions accept an optional `damage_noted` boolean (defaulting to false) and optional free-text `findings` (defaulting to empty). **Passing** advances `SCHEDULED → PASSED`; when the inspection's type is `INTAKE`, passing also advances the vehicle's `condition_status` from `INTAKE_PENDING` to `DOCUMENTED`, completing intake. **Failing** advances `SCHEDULED → FAILED` and drives the vehicle's `condition_status` to `DAMAGE_HOLD`, which blocks service starts and move-in until a subsequent intake inspection passes. Passing or failing an inspection that is not `SCHEDULED` is an `ERR_INVALID_STATE`. A vehicle's inspections can be listed.

### 3.9. Membership Pricing, Billing, and Account Balance

**Tier discounts.** A member's `tier_discount_pct` is derived directly from `membership_tier`: `BRONZE` yields no discount (0.00), `SILVER` yields 5 percent (0.05), `GOLD` yields 10 percent (0.10), and `PLATINUM` yields 20 percent (0.20).

**Storage monthly fee (snapshot at agreement creation).** When an agreement is created, its `monthly_rate_cents` is computed and frozen as follows. Start from the unit's base `monthly_rate_cents`. Add a climate surcharge that depends on the unit's class: a `CLIMATE` unit adds 5,000 cents, a `SHOWCASE` unit adds 12,000 cents, and a `STANDARD` unit adds nothing. Call this sum the gross rate. Multiply the gross rate by the member's `tier_discount_pct` to get the raw discount, then cap the discount at a maximum of 20,000 cents — the applied discount is the smaller of the raw discount and 20,000 cents. Subtract the applied (capped) discount from the gross rate and round the result half up to whole cents; that is the snapshot `monthly_rate_cents`.

**Storage proration (STORAGE line at invoice generation).** Each invoice's storage line is built in one of two variants, selected by the invoice's `proration_mode`. Under `FULL_MONTH` — the recurring bill while the agreement is still `IN_STORAGE` or `CHECKED_OUT` — the storage line is simply the agreement's snapshot `monthly_rate_cents`, the whole monthly rate regardless of days. Under `PRORATED` — the final bill after the agreement has closed and `days_stored` is known — the storage line is the snapshot monthly rate multiplied by the number of days stored capped at 30 (that is, the smaller of `days_stored` and 30), divided by 30, rounded half up to whole cents. In both variants the constant month length used for proration is 30 days.

**Service order cost (dual-variant).** A service order's cost is computed from a per-type base charge plus labor, priced at a labor rate of 12,000 cents per hour. The base charge by `service_type` is: `DETAIL` 15,000 cents, `START_ENGINE` 3,000 cents, `CHECKOUT` 5,000 cents, `CHECKIN` 5,000 cents, and `FUEL` 4,000 cents. At approval, the provisional `estimated_cost_cents` is the base charge plus `estimated_labor_hours` multiplied by 12,000 cents per hour, rounded half up to whole cents — parts are excluded. At completion, the final `final_cost_cents` is the base charge plus `actual_labor_hours` multiplied by 12,000 cents per hour, plus `parts_cents`, rounded half up to whole cents.

**Invoice assembly (round-per-line then sum).** Generating an invoice for a member and agreement over a billing period gathers up to four kinds of line items into `line_items`, each an object with a `kind` and an `amount_cents`, and each amount is a whole-cent figure. The `STORAGE` kind contributes one line from the proration rule above. The `MONITORING` kind contributes one combined line equal to the sum of `monthly_fee_cents` across the agreement's `ACTIVE` monitoring subscriptions, rounded to whole cents. The `SERVICE` kind contributes one line per `COMPLETED` service order on the agreement not yet invoiced, each equal to that order's `final_cost_cents`. The `DELIVERY` kind contributes one line per `RETURNED` delivery job for the agreement's vehicle not yet invoiced, each a flat 25,000 cents. The `subtotal_cents` is the sum of all line amounts. The `tax_cents` is computed per line — each line's amount multiplied by the tax rate of 8 percent (0.08) and rounded half up to whole cents — and then those per-line tax figures are summed; this is deliberately not the tax rate applied to the subtotal. The `total_cents` is `subtotal_cents` plus `tax_cents`. A generated invoice starts in `status` `DRAFT`, with `proration_mode` defaulting to `FULL_MONTH` when omitted, and carries the supplied `period_start_at`, `period_end_at`, `member_id`, and `agreement_id`.

**Invoice lifecycle and account balance.** A billing administrator **issues** a `DRAFT` invoice, advancing `DRAFT → ISSUED`; issuing sets `due_at` to 15 days after the issue moment (the logical clock plus the invoice due window) and recomputes the member's `charged_cents`. Paying an `ISSUED` invoice — by the owning member or a billing administrator — advances `ISSUED → PAID`, records a payment of `total_cents`, and recomputes the member's `paid_cents` so that `account_balance_cents` falls by `total_cents`. A billing administrator **voids** an invoice from `DRAFT` or `ISSUED`, moving it to `VOID`; if it was `ISSUED`, voiding recomputes `charged_cents` to restore the member's pre-issue balance. A billing administrator may also **record a payment** directly against a member's account by supplying an `amount_cents`, which recomputes `paid_cents` and `account_balance_cents`.

The member's money fields are maintained as running aggregates. `charged_cents` is the sum of `total_cents` over the member's invoices in `ISSUED` or `PAID` status. `paid_cents` is the sum of `amount_cents` over the member's recorded payments. `held_cents` is the sum of `estimated_cost_cents` over the member's service orders currently in `APPROVED`, `IN_PROGRESS`, or `ON_HOLD` status. `account_balance_cents` is `charged_cents` minus `paid_cents` — the outstanding money the member owes. Two compensating invariants hold: approving a service order and then cancelling it restores `held_cents` and leaves `account_balance_cents` unchanged, and issuing an invoice and then voiding it restores `charged_cents` to its pre-issue value.

**Billing health.** A billing administrator refreshes a member's billing health, recomputing `billing_status` against the logical clock. A member who is `CURRENT` moves to `PAST_DUE` when they have an `ISSUED` invoice whose `due_at` is at or before the clock and which remains unpaid. A member who is `PAST_DUE` moves to `SUSPENDED` when a past-due unpaid `ISSUED` invoice remains and its `due_at` plus a 30-day grace period is at or before the clock. From either `PAST_DUE` or `SUSPENDED`, a member returns to `CURRENT` when no `ISSUED` invoice is past due. As covered in §2.9, a `SUSPENDED` member is blocked from chargeable operations with `ERR_MEMBER_SUSPENDED`. Invoices are readable individually and listable with optional `member_id`, `agreement_id`, and `status` filters.

**The logical clock.** A vault manager or billing administrator advances the server's logical clock by supplying a `to_iso8601` target instant. The clock drives every window-coverage, expiry, deadline, and proration computation in the system.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`; all other successful operations — reads, state transitions, and other modifications — return HTTP 200 with the affected resource (or an empty object where noted). The complete request and response semantics for each endpoint are described in the §3 workflow narratives; this table gives only the HTTP surface and authorization.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/facilities` | Create a vault facility | VaultManager |
| GET | `/facilities/{id}` | Get a facility with live unit counters | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/facilities/{id}/units` | List units at a facility | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/facilities/{id}/units` | Create a storage unit under a facility | VaultManager |
| GET | `/units/{id}` | Get a storage unit | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/units/{id}/set-service-status` | Take a unit out of service or restore it | VaultManager |
| POST | `/members` | Register a member | VaultManager, BillingAdmin |
| GET | `/members/{id}` | Get a member with computed balance fields | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/members/{id}/vehicles` | List a member's vehicles | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/members/{id}/waitlist` | List a member's waitlist entries | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/members/{id}/record-payment` | Record a payment against the member's account | BillingAdmin |
| POST | `/members/{id}/refresh-billing` | Recompute billing status from issued invoices vs the clock | BillingAdmin |
| POST | `/vehicles` | Add a vehicle for a member | Member, VaultManager |
| GET | `/vehicles/{id}` | Get a vehicle | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/vehicles/{id}/coi` | List a vehicle's certificates of insurance | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/vehicles/{id}/inspections` | List a vehicle's inspections | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/vehicles/{id}/refresh-insurance` | Expire lapsed COIs and recompute insurance status | VaultManager, ConciergeTech |
| POST | `/vehicles/{id}/coi` | Attach a certificate of insurance to a vehicle | Member, VaultManager |
| POST | `/coi/{id}/revoke` | Revoke a certificate of insurance | VaultManager |
| POST | `/storage-agreements` | Create a storage agreement, reserving a unit window | VaultManager |
| GET | `/storage-agreements/{id}` | Get a storage agreement | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/storage-agreements` | List/filter storage agreements | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/storage-agreements/{id}/move-in` | Activate an agreement; occupy the unit | VaultManager |
| POST | `/storage-agreements/{id}/check-out` | Check the vehicle out for use | Member, ConciergeTech |
| POST | `/storage-agreements/{id}/check-in` | Return the vehicle to storage | Member, ConciergeTech |
| POST | `/storage-agreements/{id}/terminate` | Close an agreement; release unit and cascade | VaultManager |
| POST | `/storage-agreements/{id}/cancel` | Cancel a pending agreement | Member, VaultManager |
| POST | `/storage-agreements/{id}/monitoring` | Add a monitoring / battery-tender subscription | ConciergeTech, VaultManager |
| GET | `/storage-agreements/{id}/monitoring` | List monitoring subscriptions on an agreement | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/monitoring/{id}/record-reading` | Record a battery-tender voltage reading | ConciergeTech |
| POST | `/service-orders` | Request a service on an agreement | Member, VaultManager |
| GET | `/storage-agreements/{id}/service-orders` | List service orders on an agreement | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/service-orders/{id}` | Get a service order | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/service-orders/{id}/approve` | Approve and schedule a service order | VaultManager |
| POST | `/service-orders/{id}/reject` | Reject a requested service order | VaultManager |
| POST | `/service-orders/{id}/start` | Begin work (also resumes a held order) | ConciergeTech |
| POST | `/service-orders/{id}/hold` | Pause work in progress | ConciergeTech |
| POST | `/service-orders/{id}/complete` | Complete work; compute final cost | ConciergeTech |
| POST | `/service-orders/{id}/cancel` | Cancel a non-started or held service order | Member, VaultManager |
| POST | `/transporters` | Create a transporter resource | VaultManager |
| GET | `/transporters/{id}` | Get a transporter | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/delivery-jobs` | Schedule an event delivery | Member, VaultManager |
| GET | `/delivery-jobs/{id}` | Get a delivery job | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/delivery-jobs` | List/filter delivery jobs | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/delivery-jobs/{id}/dispatch` | Send the vehicle out to the event | ConciergeTech |
| POST | `/delivery-jobs/{id}/return` | Return the vehicle to the vault | ConciergeTech |
| POST | `/delivery-jobs/{id}/cancel` | Cancel a delivery job | Member, VaultManager |
| POST | `/waitlist` | Join the waitlist for a unit class at a facility | Member |
| GET | `/waitlist/{id}` | Get a waitlist entry | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/waitlist` | List/filter waitlist entries | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/waitlist/{id}/claim` | Claim an offered unit before the offer expires | Member |
| POST | `/waitlist/{id}/cancel` | Leave the waitlist | Member, VaultManager |
| POST | `/waitlist/{id}/refresh-offer` | Expire an offered entry whose window has passed | VaultManager |
| POST | `/inspections` | Schedule an inspection for a vehicle | ConciergeTech, VaultManager |
| GET | `/inspections/{id}` | Get an inspection | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/inspections/{id}/pass` | Pass an inspection | ConciergeTech, VaultManager |
| POST | `/inspections/{id}/fail` | Fail an inspection | ConciergeTech, VaultManager |
| POST | `/invoices/generate` | Generate a draft invoice for a member and agreement | BillingAdmin |
| GET | `/invoices/{id}` | Get an invoice | Member, VaultManager, ConciergeTech, BillingAdmin |
| GET | `/invoices` | List/filter invoices | Member, VaultManager, ConciergeTech, BillingAdmin |
| POST | `/invoices/{id}/issue` | Issue a draft invoice | BillingAdmin |
| POST | `/invoices/{id}/pay` | Pay an issued invoice | Member, BillingAdmin |
| POST | `/invoices/{id}/void` | Void a draft or issued invoice | BillingAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (UTC) | VaultManager, BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE` | 409 |
| `ERR_FACILITY_UNIT_LIMIT` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_AGREEMENT_HAS_ACTIVE_SERVICE` | 409 |
| `ERR_UNIT_OVERLAP` | 409 |
| `ERR_TRANSPORTER_CONFLICT` | 409 |
| `ERR_INSURANCE_LAPSED` | 409 |
| `ERR_COVERAGE_INSUFFICIENT` | 409 |
| `ERR_MEMBER_SUSPENDED` | 402 |
| `ERR_UNITS_AVAILABLE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_STALE_UNIT_VERSION` | 412 |

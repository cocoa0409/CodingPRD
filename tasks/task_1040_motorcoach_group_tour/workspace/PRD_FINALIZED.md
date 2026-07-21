# Motorcoach Group Tour API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Motorcoach & Group-Tour Operator API, the operational backbone for a company that sells and runs multi-day escorted coach tours. A tour operator juggles several inventories at once — the seats on a coach, the drivers and tour directors who staff a trip, the room blocks held with partner hotels, and the passengers themselves — while every dated departure moves through its own commercial and operational lifecycle. Getting any one of these out of step with the others causes real money to be lost: an overbooked coach, a driver rostered past federal hours-of-service limits, a hotel block that was never released, or a settlement that double-counts an unredeemed meal voucher.

The API brings all of these concerns under one consistent contract. It governs the catalog of tour products, the fleet of coaches and the roster of drivers and guides, the dated departures that instantiate a tour, the bookings and passengers that fill them, the payments and deposit schedule that fund them, the meal vouchers issued to travelers, and the cancellation, insurance, and final settlement rules that close the books. The emphasis throughout is on **conservation and consistency**: confirmed seat counts, committed room counts, resource assignments, and financial ledgers must always reconcile, whether a trip fills up, empties out through cancellations, departs, or is scrapped entirely.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and contracts that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting operator, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED`. When a caller is authenticated but their role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `OpsManager`, `SalesAgent`, `Finance`, and `Auditor`. An `OpsManager` owns the catalog, the fleet, the departure lifecycle, resource assignment, hotel blocks, and the logical clock. A `SalesAgent` owns reservations — bookings, passengers, payments, the booking lifecycle, and voucher redemption. A `Finance` operator holds the segregated authority to settle a departure. An `Auditor` has read-only oversight. Every role may call every read (GET) endpoint.

For all four roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it in an audit sense, but it does not compare `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching the caller's identifier against a stored foreign key. Authorization is purely role-based.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list results are ordered by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Payment Ledger

Nearly every resource in the system — tour products, coaches, drivers, guides, departures, hotel blocks, bookings, passengers, and vouchers — carries a common set of system-managed fields. Each has an `id`, a server-minted UUID with no type prefix. Each has a `created_at` timestamp (ISO 8601 UTC, three fractional digits) recording when it was first created, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that starts at its initial value and increments by one on every mutation. The `version` field is what optimistic concurrency control is built on (see §2.6).

`Payment` records are the sole exception. A payment is an append-only ledger entry: once written it is never modified. A `Payment` therefore carries only an `id` and a `created_at` — it has neither an `updated_at` nor a `version` field. Payments capture the flow of money against a booking and are the source of truth from which a booking's payment position is derived.

### 2.5. Monetary Precision and Rounding

All monetary quantities are stored and returned as integer counts of whole cents. Wherever a calculation multiplies a cent amount by a rate — a service-fee rate, an insurance-premium rate, a cancellation-penalty percentage, or an occupancy multiplier — the result is rounded to a whole cent using the **round half up** convention (a fractional cent of exactly one half rounds away from zero, upward). Each rule below states precisely which quantity is rounded and at which step, because the order of rounding and multiplication is significant and is fixed. Pure integer sums (for example, summing crew day-rates or room-night costs) are exact and involve no rounding.

### 2.6. Optimistic Concurrency Control for Resource Assignment

Assigning or reassigning a coach, driver, or guide to a departure is guarded by optimistic concurrency control on the departure. The assignment request must carry an `expected_departure_version` field holding the `version` of the target departure that the client last observed. If that value does not match the departure's current `version` at the moment the request is processed, the assignment is rejected with `ERR_STALE_DEPARTURE_VERSION` and HTTP status 412.

This guard exists because reassignment legitimately supersedes a previously assigned resource: an assign request replaces whatever coach, driver, or guide was previously held, releasing the prior one. A client acting on a stale view of the departure could therefore silently overwrite an assignment made by someone else since it last read the departure. Rejecting on the version mismatch forces the client to re-read the departure and act on current state. Only the assignment operation takes a version field; no other endpoint requires one.

### 2.7. Cascading Consistency and Automatic Resource Release

Many operations mutate more than one resource. The system performs every dependent effect as part of the triggering operation, so that seat counts, room commitments, resource availability, and financial ledgers are never left inconsistent. Whenever a resource is mutated — including when the server changes it automatically as a downstream effect — its `updated_at` is refreshed and its `version` is incremented.

Two derived counts are maintained automatically on each affected departure and hotel block. A departure's `confirmed_pax` is always the sum of `pax_count` over the bookings on that departure whose `reservation_status` is `CONFIRMED` or `TRAVELED`. A hotel block's `rooms_committed` is always the sum of `rooms_requested` over the bookings on that departure whose `reservation_status` is `CONFIRMED` or `TRAVELED`. These are recomputed whenever a booking is confirmed or cancelled and whenever a departure is cancelled, so that a forward action and its later compensating action leave the totals unchanged. Coaches, drivers, and guides are returned to the pool (their `status` set back to `AVAILABLE`) whenever the departure that held them is settled or cancelled, or when a reassignment supersedes them.

### 2.8. Nested Resource Retrieval and Validation Precedence

Some endpoints address a resource nested beneath another in the URL. The server validates path identifiers strictly left to right: the outermost identifier is resolved first, and the first identifier that does not correspond to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any inner identifier or referenced foreign key is examined. Referenced foreign-key identifiers carried in a request body are likewise checked for existence, and a reference to a nonexistent resource yields `ERR_NOT_FOUND`.

Across the whole API, validations are applied in a fixed priority order, and the first failing check determines the error returned. Authentication is checked first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then request-body well-formedness — required fields present, enum values valid, amounts positive (`ERR_VALIDATION`) — then existence of path and referenced identifiers (`ERR_NOT_FOUND`). Only after these universal checks pass does the system evaluate state and business rules, whose relative ordering is described alongside each workflow in §3. Where a mutating operation targets a departure, a departure already in a terminal state (`CANCELLED` or `SETTLED`) is rejected with `ERR_DEPARTURE_TERMINAL` ahead of the operation-specific business rules; this applies to departure publish, assign, depart, cancel, and settle, and to hotel-block confirm.

### 2.9. The Logical Service Clock

The system runs on a logical clock rather than real wall-clock time. Before any client sets it, the clock reads `2026-07-01T00:00:00Z`. An `OpsManager` may advance the clock by supplying a `to_iso8601` instant, and the response reports the new value as `current_utc`. The logical clock governs every time-dependent rule: it is the "today" against which cancellation penalty tiers are measured, and it is the instant stamped as a voucher's `redeemed_at` when a voucher is redeemed. Tests and operators drive time forward exclusively through this capability.

### 2.10. Fleet and Crew Scheduling Safeguards

Assigning crew and equipment to a departure is subject to safety and non-conflict rules that protect against double-booking and regulatory violations. A coach, driver, or guide may only be assigned when it is currently `AVAILABLE`; assignment sets its `status` to `ASSIGNED`. These rules are evaluated in priority order after the departure's terminal-state check.

For a **driver**, the system first enforces federal hours-of-service limits: no single itinerary day may schedule more than ten planned driving hours. If any itinerary day's `planned_drive_hours` exceeds ten, the assignment is rejected with `ERR_DOT_HOURS_EXCEEDED`. The driver must also be free of scheduling conflicts: a driver may not be assigned if any other non-`CANCELLED` departure that holds the same driver has dates that overlap this departure's date span, treating both the first and last service dates as inclusive; a conflict yields `ERR_DRIVER_OVERLAP`.

For a **coach**, the conflict rule additionally honors a turnaround buffer to allow the vehicle to be repositioned and serviced between trips. The coach's occupied window — its inclusive first-through-last service dates — is padded by a fixed turnaround buffer of one (1) whole day on each side before checking for a date overlap against any other non-`CANCELLED` departure that holds the same coach. Concretely, if one departure's occupied window ends on day D, another departure holding the same coach may not begin until day D+2 or later; a start on D+1 (only one day's gap) still conflicts. If the padded windows overlap, the assignment is rejected with `ERR_COACH_OVERLAP`.

For a **guide**, the overlap test is half-open: a guide's occupancy runs from the `start_date` inclusive up to but not including the `end_date`. Two departures whose spans meet exactly end-to-start do not conflict for a guide. Any genuine half-open overlap with another non-`CANCELLED` departure holding the same guide is rejected with `ERR_GUIDE_OVERLAP`.

## 3. Business Logic & Workflows

### 3.1. Catalog, Fleet, and Departure Setup

An `OpsManager` builds the operator's catalog and fleet before any selling can begin. A **tour product** is a reusable catalog template created with a `name`, a `duration_days` count (which must be at least 1), and a `base_price_per_person_cents` list price (which must be zero or greater, expressed in cents before any occupancy adjustment). A tour product also carries a `deposit_per_person_cents`, the non-refundable per-person deposit due at confirmation; if the creator omits it, it defaults to 20000 cents, and it must be zero or greater.

The fleet consists of three independently rostered resource types. A **coach** is created with a fleet `code`, a `seat_capacity` (at least 1 seat), and a `day_rate_cents` operating cost; its `status` begins at `AVAILABLE`. A **driver** is created with a `name`, a `license_no` (the CDL license number), and a `day_rate_cents`, and likewise begins `AVAILABLE`. A **guide** — the tour director or escort — is created with a `name` and a `day_rate_cents`, and begins `AVAILABLE`. Each of the three resource types cycles between `AVAILABLE` and `ASSIGNED` as departures claim and release it.

A **departure** is a dated instance of a tour product, created by referencing the parent template through its `tour_product_id` and supplying a `name` (the departure label), a `start_date` and `end_date` as inclusive `YYYY-MM-DD` service dates, a `guaranteed_min_pax` (at least 1) that is the minimum confirmed passenger count needed to guarantee the trip, and an `itinerary_days` array. Each entry in `itinerary_days` describes one day of the trip as a `day_index`, a `service_date`, a `from_city`, a `to_city`, and the `planned_drive_hours` for that leg; this array is what the driver hours-of-service check reads. A new departure begins in `PLANNING` status, with `confirmed_pax` of 0, `occupancy_band` of `SMALL`, and its `coach_id`, `driver_id`, `guide_id`, `settlement_net_cents`, and other computed fields unset (null) until the relevant events occur.

### 3.2. The Departure Lifecycle and Guarantee Cycle

A departure moves through `PLANNING`, `OPEN`, `GUARANTEED`, `DEPARTED`, and finally `SETTLED`, with `CANCELLED` as an alternate terminal outcome; `SETTLED` and `CANCELLED` are terminal. Publishing a departure advances it from `PLANNING` to `OPEN` and requires that it have at least one entry in its `itinerary_days`; once `OPEN`, bookings against it may be confirmed. Only an `OpsManager` may publish.

The transition between `OPEN` and `GUARANTEED` is a cycle driven entirely by the system as bookings confirm and cancel. When a booking is confirmed and the departure's resulting `confirmed_pax` reaches or exceeds its `guaranteed_min_pax`, the departure automatically advances from `OPEN` to `GUARANTEED` with no field reset. Conversely, when a cancellation drops `confirmed_pax` back below `guaranteed_min_pax`, a `GUARANTEED` departure reverts to `OPEN`. This cycle may repeat any number of times.

Departing a trip advances it from `GUARANTEED` to `DEPARTED` and is performed by an `OpsManager`. Because departure is only reachable from `GUARANTEED`, the trip is already known to meet its guaranteed minimum. The precondition checked at this step is that a coach, driver, and guide are all assigned — that `coach_id`, `driver_id`, and `guide_id` are all set; if any is missing the request is rejected with `ERR_DEPARTURE_NOT_ASSIGNED`. Upon departing, every booking still in `CONFIRMED` transitions to `TRAVELED`, the departure's `occupancy_band` is recomputed from its actual `confirmed_pax`, and each traveled booking has its `final_per_person_cents` pinned from that actual band (see §3.5 for the band-to-price mapping).

Settlement advances a departure from `DEPARTED` to `SETTLED` and is the segregated responsibility of a `Finance` operator; it requires the departure to be in `DEPARTED`. Settling pins the departure's `settlement_net_cents` to the final settlement result and releases the assigned coach, driver, and guide back to `AVAILABLE` (see §3.9 for the settlement figures).

### 3.3. Assigning Coaches, Drivers, and Guides

An `OpsManager` staffs a departure by assigning a coach, driver, or guide to it. The request names which resource type is being placed through a `resource_kind` value and supplies the corresponding identifier — a `coach_id`, `driver_id`, or `guide_id`. Because assignment is guarded by optimistic concurrency control, the request also carries `expected_departure_version` (see §2.6); a mismatch against the departure's current `version` is rejected with `ERR_STALE_DEPARTURE_VERSION` at HTTP 412. The safeguards on hours-of-service and on coach, driver, and guide date conflicts described in §2.10 are enforced here in that priority order, after the departure terminal-state check and before the version check is finalized.

A successful assignment sets the departure's `coach_id`, `driver_id`, or `guide_id` as appropriate, moves the chosen resource's `status` to `ASSIGNED`, and increments the departure's `version` by one. When an assignment supersedes a previously held resource of the same kind, that prior resource is released back to `AVAILABLE`. This reassignment-supersedes behavior is exactly why the stale-version guard matters.

### 3.4. Hotel Blocks and Room Commitment

A departure's lodging is arranged through **hotel blocks**, each created by an `OpsManager` against a departure via its `departure_id`. A block records a `hotel_name`, a `city`, a `room_count` (the number of rooms held, zero or greater), a `nights` count of room-nights per room (at least 1), and a `rate_per_room_night_cents` negotiated nightly rate. A new block begins with `status` of `HELD` and `rooms_committed` of 0.

A block's `rooms_committed` tracks how many rooms the confirmed parties on the departure need: it equals the sum of `rooms_requested` across the departure's bookings whose `reservation_status` is `CONFIRMED` or `TRAVELED`. From that, the block's `block_cost_cents` is `rooms_committed` multiplied by `nights` multiplied by `rate_per_room_night_cents`. While a block is `HELD`, this cost tracks the committed rooms; confirming a block freezes `block_cost_cents` at its value at confirmation time.

A block transitions `HELD` to `CONFIRMED` when an `OpsManager` confirms it, provided the parent departure is not `CANCELLED` or `SETTLED` (otherwise `ERR_INVALID_STATE`). A block may be released from either `HELD` or `CONFIRMED` to the terminal `RELEASED` state, which returns the rooms to the hotel; once released, its rooms no longer count toward commitment. Only `CONFIRMED` blocks contribute their `block_cost_cents` to a departure's settlement.

### 3.5. Bookings: Quoting, Pricing, and Charges

A `SalesAgent` creates a **booking** against a departure by supplying its `departure_id`, a `lead_name` for the party lead or agency contact, a `pax_count` of passengers (at least 1), a `rooms_requested` count (zero or greater), and an optional `insurance_opt_in` flag that defaults to false. A new booking begins with `reservation_status` of `DRAFT` and `payment_status` of `UNPAID`. At creation the system computes and locks the booking's pricing, described below, and the several computed money fields all start from these figures.

Per-person pricing depends on the departure's **occupancy band**, which reflects how full the trip is. The band is `SMALL` when the passenger count is fewer than 6, `STANDARD` when it is 6 through 11 inclusive, and `LARGE` when it is 12 or more. Each band carries a multiplier applied to the tour product's `base_price_per_person_cents`: `SMALL` multiplies by 1.20, `STANDARD` by 1.00, and `LARGE` by 0.90. The per-person price is the base price times the band's multiplier, rounded half up to whole cents.

At booking creation the band is chosen on a forward-looking basis: it is derived from the **projected** passenger count, which is the departure's current `confirmed_pax` plus this booking's own `pax_count`. The resulting per-person price is locked into the booking's `quoted_per_person_cents`. The booking's `final_per_person_cents` remains null until the departure departs, at which point it is re-derived from the departure's actual `confirmed_pax` band and pinned (see §3.2).

From the quoted per-person price, the remaining charges are computed at creation. The `base_subtotal_cents` is `quoted_per_person_cents` multiplied by `pax_count`. The service fee is computed per person and then scaled: the per-person fee is `quoted_per_person_cents` multiplied by the service-fee rate of 0.0725, rounded half up to whole cents, and the booking's `service_fee_cents` is that rounded per-person fee multiplied by `pax_count` — the rounding happens on the per-person fee only, before multiplying by the passenger count, not on the subtotal. The `insurance_premium_cents` is charged only when `insurance_opt_in` is true, in which case it is `base_subtotal_cents` multiplied by the insurance-premium rate of 0.06, rounded half up to whole cents; when insurance is not opted in it is 0. The `booking_total_cents` is the sum of `base_subtotal_cents`, `service_fee_cents`, and `insurance_premium_cents`. The `deposit_due_cents` is the tour product's `deposit_per_person_cents` multiplied by `pax_count`.

The remaining money fields track the payment position: `amount_paid_cents` is the sum of all `DEPOSIT` and `BALANCE` payments on the booking, `amount_refunded_cents` is the sum of all `REFUND` payments, and `penalty_charged_cents` and `cancel_reason` remain null until the booking is cancelled.

### 3.6. Payments and the Deposit Schedule

Money is recorded against a booking through **payment** records, created by a `SalesAgent`. A payment names its `booking_id`, its `kind`, a positive `amount_cents`, and an optional free-text `method` tender note. The `kind` is `DEPOSIT`, `BALANCE`, or `REFUND`; only the system creates `REFUND` payments, as a side effect of a cancellation — a client may record only `DEPOSIT` or `BALANCE` payments. Each recorded payment recomputes the booking's `amount_paid_cents` and re-derives its `payment_status`.

The `payment_status` is a second, independent dimension of a booking that runs `UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, and the terminal `REFUNDED`. A booking becomes `DEPOSIT_PAID` once its `amount_paid_cents` reaches or exceeds its `deposit_due_cents` while still remaining below its `booking_total_cents`. It becomes `PAID_IN_FULL` once `amount_paid_cents` reaches or exceeds `booking_total_cents` — whether that happens through a balance payment on top of a deposit, or through a single payment that covers the full total at once. When a cancellation issues a refund, the booking's `payment_status` moves to `REFUNDED` from whatever paid state it held.

### 3.7. Passengers, Confirmation, Seats, Rooming, and Vouchers

Passengers are added to a booking one at a time by a `SalesAgent`, each created with its `booking_id`, a `full_name` for the manifest, an optional `is_lead` flag (default false) marking the party lead, and an optional `roommate_passenger_id` that pairs this passenger with another for the rooming list — left null for a single. A passenger's `seat_no` and `room_no` are unset until the booking is confirmed.

Confirming a booking advances its `reservation_status` from `DRAFT` to `CONFIRMED` and is where the heavy consistency work happens. A `SalesAgent` performs it, and the checks run in the following priority order. First, the booking must be in its valid `DRAFT` from-state and must not already be terminal — a booking already `CANCELLED` or `TRAVELED` is rejected with `ERR_BOOKING_TERMINAL`. The departure must be `OPEN` or `GUARANTEED`; if it is in any other status the confirm is rejected with `ERR_DEPARTURE_NOT_OPEN`. Then the business constraints are evaluated: if a coach is assigned, the departure's `confirmed_pax` plus this booking's `pax_count` must not exceed that coach's `seat_capacity`, or the confirm is rejected with `ERR_COACH_CAPACITY_EXCEEDED`; the number of passengers actually attached to the booking must equal its `pax_count`, or it is rejected with `ERR_PASSENGER_COUNT_MISMATCH`; and for each hotel block, the block's `rooms_committed` plus this booking's `rooms_requested` must not exceed the block's `room_count`, or it is rejected with `ERR_HOTEL_BLOCK_INSUFFICIENT`. Finally, the deposit must be paid — the booking's `payment_status` must be `DEPOSIT_PAID` or `PAID_IN_FULL`, otherwise the confirm is rejected with `ERR_DEPOSIT_UNPAID`.

When all checks pass, confirmation assigns each passenger the lowest free seat numbers in ascending order as their `seat_no`, assigns a `room_no` according to the rooms requested, and issues exactly one `MEAL` **voucher** per passenger. Each issued voucher records the `booking_id` and `passenger_id` it belongs to, a `kind` of `MEAL`, a `face_value_cents` of 2500 at issuance, a `status` of `ISSUED`, and a null `redeemed_at`. Confirmation then adds this booking's `pax_count` to the departure's `confirmed_pax` and recomputes the `occupancy_band`, adds this booking's `rooms_requested` to the affected hotel block's `rooms_committed` and recomputes its cost, and — if the resulting `confirmed_pax` now reaches or exceeds `guaranteed_min_pax` — advances the departure from `OPEN` to `GUARANTEED`.

### 3.8. Cancellations, Penalties, and Refunds

A booking may be cancelled by a `SalesAgent`, and what happens depends on whether it was ever confirmed. In all cases the cancel captures an optional `reason`, stored on the booking as `cancel_reason`.

Cancelling a booking that is still in `DRAFT` — never confirmed — incurs no penalty. If any money was paid, a `REFUND` payment for the full `amount_paid_cents` is recorded and the `payment_status` moves to `REFUNDED`; the booking's `reservation_status` becomes `CANCELLED`.

Cancelling a `CONFIRMED` booking is permitted only while the departure is not yet `DEPARTED` or `SETTLED` (otherwise `ERR_INVALID_STATE`), and it charges a cancellation penalty. The penalty tier is set by how many whole days lie between the logical clock's current date and the departure's `start_date`: 60 or more days out charges 10 percent, 30 up to but not including 60 days charges 25 percent, 15 up to but not including 30 days charges 50 percent, and fewer than 15 days charges 100 percent. The base penalty is the booking's `base_subtotal_cents` multiplied by that percentage, rounded half up to whole cents. The deposit is always retained: the non-refundable floor equals the booking's `deposit_due_cents`. When the party purchased insurance (`insurance_opt_in` is true), the insurance waives any penalty above the deposit, so `penalty_charged_cents` is set to just the deposit amount; otherwise `penalty_charged_cents` is the greater of the computed base penalty and the deposit floor. The refund issued is the `amount_paid_cents` minus `penalty_charged_cents`, floored at zero so it is never negative, recorded as a `REFUND` payment; the `payment_status` moves to `REFUNDED`.

Cancelling a confirmed booking also unwinds its operational footprint: every passenger on the booking has its `seat_no` and `room_no` cleared, the departure's `confirmed_pax` is reduced by the booking's `pax_count`, the affected hotel block's `rooms_committed` is reduced by the booking's `rooms_requested`, and every `ISSUED` voucher on the booking is set to `VOIDED`. The booking's `reservation_status` becomes `CANCELLED`. If this reduction drops `confirmed_pax` below `guaranteed_min_pax`, the departure reverts from `GUARANTEED` to `OPEN`.

An `OpsManager` may cancel an entire departure while it is `OPEN` or `GUARANTEED`, moving it to the terminal `CANCELLED` state with a full cascade. Every non-terminal booking on the departure is cancelled as an operator cancellation with no penalty. Each such cancelled booking has its `ISSUED` vouchers set to `VOIDED` and receives a `REFUND` payment for its full `amount_paid_cents`, with its `payment_status` moving to `REFUNDED`. Every passenger's `seat_no` and `room_no` is cleared, the departure's confirmed-passenger and each block's committed-room counts are recomputed, and the assigned coach, driver, and guide are released back to `AVAILABLE`.

### 3.9. Departure, Manifest, Redemption, and Settlement

The escort **manifest** for a departure is a computed view returning the `departure_id`, the current `confirmed_pax`, and arrays of `passengers`, `rooming`, and `vouchers` — everything an escort needs to run the trip, drawn from the confirmed bookings, their seat and room assignments, and their issued vouchers.

Each passenger's meal voucher is redeemed by a `SalesAgent` while the trip runs. Redemption is permitted only when the voucher is currently `ISSUED`; redeeming a voucher in any other status is rejected with `ERR_VOUCHER_NOT_ISSUED`. A successful redemption moves the voucher from `ISSUED` to `REDEEMED` and stamps its `redeemed_at` with the current logical-clock instant. A voucher's `face_value_cents` enters the final settlement cost only if it was actually redeemed; a voucher that was voided is excluded from settlement cost.

The **settlement** view computes a departure's financial result and is available both provisionally (before settling) and as pinned figures (after). It returns the `departure_id`, the `variant` in effect, and the `revenue_cents`, `cost_cents`, and `net_cents`. The net is revenue minus the sum of crew cost, hotel cost, and voucher cost. Crew cost is exact: it is the tour product's `duration_days` multiplied by each assigned resource's day rate — the coach's `day_rate_cents`, the driver's `day_rate_cents`, and the guide's `day_rate_cents` — summed together. Hotel cost is the sum of `block_cost_cents` across only the hotel blocks whose `status` is `CONFIRMED`.

Revenue and voucher cost differ by variant. The **provisional** variant applies when settlement is viewed while the departure is `OPEN` or `GUARANTEED`: revenue is the sum of `booking_total_cents` over bookings whose `reservation_status` is `CONFIRMED`, and voucher cost estimates that every `ISSUED` voucher will be redeemed, summing the face value of all issued vouchers at 2500 cents each. The **final** variant is computed when a `Finance` operator settles the departure (`DEPARTED` to `SETTLED`): revenue is the sum over bookings whose `reservation_status` is `TRAVELED` of `final_per_person_cents` multiplied by `pax_count`, plus that booking's `service_fee_cents`, plus its `insurance_premium_cents`; and voucher cost counts only vouchers that were actually `REDEEMED`, summing their face value. Before a departure can be settled, no `TRAVELED` booking may have an outstanding balance: every traveled booking's `amount_paid_cents` must be at least its `booking_total_cents`, or the settle is rejected with `ERR_BALANCE_UNPAID`. The computed final net is pinned onto the departure as its `settlement_net_cents`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status. Operations that modify an existing resource, drive a state transition, or return a computed view return a `200 OK` status. All request and response payloads follow the envelope of §2.2; the detailed inputs, computed outputs, and side effects for each endpoint are described in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/tour-products` | Create a tour product | OpsManager |
| POST | `/api/coaches` | Create a coach | OpsManager |
| GET | `/api/coaches/{coach_id}` | Get a coach | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/drivers` | Create a driver | OpsManager |
| GET | `/api/drivers/{driver_id}` | Get a driver | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/guides` | Create a guide | OpsManager |
| POST | `/api/departures` | Create a departure | OpsManager |
| GET | `/api/departures/{departure_id}` | Get a departure | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/departures` | List departures (filterable) | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/departures/{departure_id}/publish` | Publish a departure (PLANNING to OPEN) | OpsManager |
| POST | `/api/departures/{departure_id}/assign` | Assign or reassign coach/driver/guide | OpsManager |
| POST | `/api/departures/{departure_id}/depart` | Depart (GUARANTEED to DEPARTED) | OpsManager |
| POST | `/api/departures/{departure_id}/cancel` | Cancel a departure (cascade) | OpsManager |
| POST | `/api/departures/{departure_id}/settle` | Settle (DEPARTED to SETTLED) | Finance |
| GET | `/api/departures/{departure_id}/manifest` | Computed escort manifest | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/departures/{departure_id}/settlement` | Computed settlement (provisional/final) | OpsManager, Finance, Auditor |
| POST | `/api/hotel-blocks` | Create a hotel block | OpsManager |
| GET | `/api/hotel-blocks/{hotel_block_id}` | Get a hotel block | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/hotel-blocks` | List hotel blocks | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/hotel-blocks/{hotel_block_id}/confirm` | Confirm a hotel block (HELD to CONFIRMED) | OpsManager |
| POST | `/api/hotel-blocks/{hotel_block_id}/release` | Release a hotel block | OpsManager |
| POST | `/api/bookings` | Create a booking (DRAFT) | SalesAgent |
| GET | `/api/bookings/{booking_id}` | Get a booking | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/bookings` | List bookings | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/bookings/{booking_id}/confirm` | Confirm a booking (DRAFT to CONFIRMED) | SalesAgent |
| POST | `/api/bookings/{booking_id}/cancel` | Cancel a booking | SalesAgent |
| POST | `/api/passengers` | Add a passenger to a booking | SalesAgent |
| GET | `/api/passengers/{passenger_id}` | Get a passenger | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/passengers` | List passengers | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/payments` | Record a deposit or balance payment | SalesAgent |
| GET | `/api/payments/{payment_id}` | Get a payment | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/payments` | List payments | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/vouchers/{voucher_id}` | Get a voucher | OpsManager, SalesAgent, Finance, Auditor |
| GET | `/api/vouchers` | List vouchers | OpsManager, SalesAgent, Finance, Auditor |
| POST | `/api/vouchers/{voucher_id}/redeem` | Redeem a voucher (ISSUED to REDEEMED) | SalesAgent |
| POST | `/_clock/set_current_utc` | Set the logical service clock | OpsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_DEPARTURE_TERMINAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPARTURE_NOT_OPEN` | 409 |
| `ERR_BOOKING_TERMINAL` | 409 |
| `ERR_DOT_HOURS_EXCEEDED` | 409 |
| `ERR_COACH_OVERLAP` | 409 |
| `ERR_DRIVER_OVERLAP` | 409 |
| `ERR_GUIDE_OVERLAP` | 409 |
| `ERR_COACH_CAPACITY_EXCEEDED` | 409 |
| `ERR_PASSENGER_COUNT_MISMATCH` | 409 |
| `ERR_HOTEL_BLOCK_INSUFFICIENT` | 409 |
| `ERR_DEPARTURE_NOT_ASSIGNED` | 409 |
| `ERR_DEPOSIT_UNPAID` | 402 |
| `ERR_BALANCE_UNPAID` | 402 |
| `ERR_VOUCHER_NOT_ISSUED` | 409 |
| `ERR_STALE_DEPARTURE_VERSION` | 412 |

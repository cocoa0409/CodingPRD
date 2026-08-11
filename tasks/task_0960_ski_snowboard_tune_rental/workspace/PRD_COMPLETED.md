# Ski & Snowboard Tune & Rental Shop API — Product Requirements Document

## 1. Introduction

A mountain-town ski and snowboard shop lives or dies by a single finite asset: its fleet. Every pair of skis, every board, every boot on the wall can be pulled in four directions at once — a weekend rental reservation, a season-long junior lease, a paying demo day, or an outright sale — and each of those commitments interacts with a workshop that tunes, waxes, and repairs the same equipment on a clock of its own. This document specifies the API for running that shop end to end: rental fitment and reservation, the tune/wax/edge service pipeline, the junior season-lease program, demo-day credits and upgrade purchases, damage assessment with deposit capture, slope-side pickup logistics, workshop turnaround and rush capacity, and fleet inventory control.

The system's design centers on two ideas. First, the equipment pool is a competed-for resource: reservations queue for units, a selector policy assigns eligible units automatically, and occupancy is tracked as date windows with mandatory turnaround gaps. Second, money and reputation flow through cascades: a single damage invoice can capture a deposit, recompute a customer's standing, and suspend that customer's active season leases in one motion. All of these effects are immediate — every side effect is visible in the triggering request's response and in any read that follows it.

All shop resources live under a single flat URL space mounted at `/shop`; a separate administrative capability controls the server's logical clock, which is the only notion of "now" the system ever uses.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles: `Customer`, `FrontDesk`, `Technician`, and `Manager`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not in the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED`.

The roles behave as follows. A `Customer` rents gear, owns tune tickets for their own equipment, holds demo credits, buys equipment, and disputes damage invoices — but may only ever touch their own resources. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`. This ownership chain runs through `customer_id` on reservations, tune tickets, purchase orders, and demo credits, and reaches pickup bookings and damage assessments indirectly through the reservation they reference. A customer acting on a resource owned by a different customer is rejected with `ERR_FORBIDDEN_OWNERSHIP`. On list endpoints a `Customer` caller is not rejected; the result set is instead scoped to that customer's own resources (reservations, reservation items, tune tickets, demo credits, purchase orders, damage assessments, and pickup bookings), with all resources owned by others filtered out. When `X-User-Role` is `FrontDesk`, `Technician`, or `Manager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. `FrontDesk` staff run the counter — registering customers, driving the rental lifecycle, invoicing damage, and recording demo days. `Technician` staff run the workshop — quoting and working tune tickets, inspecting returned units, and creating damage assessments. `Manager` is a hierarchical override role: a superset of everything `FrontDesk` and `Technician` can do, plus exclusive control over fleet creation and retirement, pickup windows, shop-day capacity declarations, dispute resolution, lease reinstatement, and the logical clock.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip and defaults to 0. A non-numeric `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`; numeric values outside the allowed range are clamped into it rather than rejected (a `limit` below 1 becomes 1 and above 100 becomes 100, and a negative `offset` becomes 0).

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

Paginated list responses carry four fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — customers, equipment items, reservations, reservation items, tune tickets, season leases, demo credits, purchase orders, damage assessments, pickup windows, pickup bookings, and shop-day capacity rows — carries the same four system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix. The `id` is an identity value only; it is never used for ranking, ordering, or tie-breaking anywhere in the system.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 at creation and increments by exactly 1 on every mutation. Any mutation — including a side effect cascading in from another resource — updates `updated_at` and bumps `version` on the mutated resource.

### 2.5. The Shop's Logical Clock

The server maintains a logical clock, and every time-dependent rule in this document — age calculations, overdue detection, demo-credit expiry, pickup-window closure, turnaround promises, day counts — reads that logical clock, never wall-clock time. At server startup, before any clock-setting call has been made, the logical clock reads exactly `2026-05-01T00:00:00Z`.

A manager-only administrative capability sets the logical clock to a supplied `to_iso8601` instant and reports the resulting time as `current_utc`. Advancing the clock is not a passive act: each set triggers a sweep of the clock-driven system transitions. Reservations still out past their last rental day flip to overdue, demo credits whose validity has lapsed expire, pickup windows whose end has passed close and strand their remaining bookings as no-shows. These same clock-driven transitions are also evaluated lazily on read, so a resource read after time has passed reflects the transition even without an explicit sweep.

### 2.6. Money, Cents, and the Rounding Discipline

All monetary values in the system are integer cents — prices, rates, deposits, charges, credits, and totals are never fractional. Whenever a computation produces a fractional cent, the result is rounded to the nearest whole cent using round-half-up.

Two rounding disciplines are pinned and must not be reordered. In rental pricing, each reservation line is rounded to whole cents first, and only then are the rounded lines summed into a reservation total — never the reverse. In tune-ticket quoting, both price multipliers are applied to the subtotal first, and the single round-half-up happens only after both multipliers have been applied. The DIN fitment calculation uses its own precision: values are rounded to the nearest 0.25 step, ties rounding half up, after clamping.

### 2.7. Fleet Occupancy: Date Windows and the One-Day Gap

A unit of equipment cannot be in two places at once, and the system tracks this through occupancy windows. Every rental commitment on a unit occupies a closed date interval — both the first and last rental day belong to the window. Between any two windows on the same unit there must be at least one full calendar day that belongs to neither window: the first day of a new rental window must fall at least two calendar dates after the last day of any existing window on that unit. A request that would collide with an existing window, or leave no free day between windows, is rejected with `ERR_EQUIPMENT_OCCUPANCY_CONFLICT`.

Fleet units also carry a lifecycle status — `AVAILABLE`, `RESERVED`, `OUT`, `AWAITING_INSPECTION`, `IN_SERVICE`, `RETIRED`, `LOST`, or `SOLD` — and only certain statuses are rentable. Only units in `AVAILABLE` or `RESERVED` status may be newly committed to a customer, and a `RESERVED` unit may be taken only through the forced-assignment path of §3.3, where its existing occupancy windows still apply. A unit that is `OUT`, `IN_SERVICE`, `AWAITING_INSPECTION`, `RETIRED`, `LOST`, or `SOLD` cannot be newly committed to a customer; attempts to force such a unit into a rental or lease are rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`. `RETIRED`, `LOST`, and `SOLD` are terminal: a unit in one of those states never leaves it.

### 2.8. The Deposit Waterfall and Its Conservation Invariant

Every confirmed rental reservation holds a deposit, and that deposit flows through the system as a waterfall with a strict conservation law. The hold placed at confirmation is `deposit_authorized_cents`. As damage invoices arrive, portions of the hold are captured into `deposit_captured_cents`. At close or cancellation, the remainder is released into `deposit_released_cents`, set so that the invariant `deposit_authorized_cents` equals `deposit_captured_cents` plus `deposit_released_cents` always holds once the reservation is closed or cancelled.

Captures are allocated in a fixed order: when multiple damage assessments against one reservation are invoiced, they draw from the hold in the order the assessments were created, earliest first. Each invoice captures the smaller of its own charge and whatever portion of the authorized hold has not yet been captured. The unsettled remainder of a charge — the part the deposit could not cover — becomes an amount the customer must pay directly.

The deposit picture exists in two variants. A return-time estimate treats still-draft damage assessments as planned deductions, giving staff a provisional view of what the deposit will cover. The final settlement at close time captures only assessments that have actually been invoiced (or moved past invoicing) and releases everything else.

### 2.9. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only those two.

Approving a tune-ticket quote requires the request to carry `expected_tune_ticket_version`, holding the ticket `version` the customer last observed. If the ticket's current `version` has advanced since then — for example because a technician re-quoted the ticket, which itself bumps the version — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), so a customer can never approve a quote they have not actually seen.

Swapping the leased unit on a junior season lease requires the request to carry `expected_season_lease_version`, holding the lease `version` the client last observed. A mismatch with the lease's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a swap from binding to a superseded lease state. On both guarded writes, a request that omits the expected-version field entirely is rejected with `ERR_INVALID_REQUEST` rather than `ERR_STALE_VERSION`.

No other endpoint accepts or requires a version field; on all other writes the request is processed without an OCC check, and conflicting states are caught by state preconditions instead.

### 2.10. Request Validation Precedence

When a request violates several rules at once, the error it receives is deterministic, because validations run in a fixed precedence ladder. Authentication comes first: missing or malformed identity headers produce `ERR_UNAUTHENTICATED` before anything else is examined. Role authorization follows, yielding `ERR_UNAUTHORIZED`. Customer-ownership scoping is third, yielding `ERR_FORBIDDEN_OWNERSHIP`. Fourth, every identifier in the path and every foreign-key identifier in the body is resolved for existence, strictly left to right along the path first, producing `ERR_NOT_FOUND` for the first identifier that does not correspond to an existing resource. Fifth, on the two OCC-guarded writes, the expected-version check runs and yields `ERR_STALE_VERSION`. Sixth, the target resource's state is checked against the requested transition — including terminal-state lockdown — yielding `ERR_INVALID_STATE`. Only after all six gates pass do the temporal and business rules of §3 apply, in the relative order stated with each workflow. Where several business rules guard the same operation, §3 states their evaluation order explicitly; text order in those passages is normative.

### 2.11. Hierarchical Consistency and Cascading Change

The system's entities are peers in a flat space, joined by references rather than containment, but change still propagates. A single operation routinely mutates more than one resource: confirming a reservation freezes its quote, invoicing a damage assessment moves deposit money and recomputes a customer's standing, and a standing change can in turn suspend season leases. Every such cascade is atomic with the triggering request — all side effects are applied and visible in the response and in subsequent reads — and every resource touched by a cascade has its own `updated_at` refreshed and `version` incremented. The server may also transition resources on its own when criteria are met: reservations go overdue, credits expire, windows close, and leases suspend without any client request addressed at those specific resources.

## 3. Business Logic & Workflows

### 3.1. Customer Profiles and Account Standing

A `FrontDesk` or `Manager` operator registers each customer with their `full_name`, a unique `email`, and the physical profile that drives binding fitment: `date_of_birth`, `height_cm`, `weight_kg`, `boot_sole_mm` (boot sole length in millimeters), and `skier_type`, one of `TYPE_1` (cautious), `TYPE_2` (moderate), or `TYPE_3` (aggressive). Every customer starts in `GOOD_STANDING` with a `late_return_count` of zero. Registering an `email` already on file is rejected with `ERR_INVALID_REQUEST`.

The customer's `standing` is a computed, three-tier judgment — `GOOD_STANDING`, `WATCH`, or `BARRED` — recomputed whenever the underlying facts change: when a damage invoice is issued, paid, or resolved, and when a reservation comes back late. The rule is a strict ladder. If any unpaid invoiced damage assessment against the customer's reservations has severity `TOTAL_LOSS`, the customer is `BARRED`. Otherwise, if any unpaid invoiced assessment exists at all, or the customer's `late_return_count` has reached three — exactly three late returns is enough, the boundary is inclusive — the customer is `WATCH`. Otherwise the customer is in `GOOD_STANDING`. Only assessments currently in `INVOICED` status count as unpaid for this ladder; a `DISPUTED` assessment does not depress standing unless a resolution returns it to `INVOICED`. Entering `BARRED` has teeth beyond the label: every active junior season lease held by that customer is suspended in the same motion, as detailed in §3.6.

### 3.2. Building and Maintaining the Fleet

A `Manager` adds each unit to the fleet with its `gear_type` — `SKI`, `SNOWBOARD`, `BOOT`, or `POLES` — a human-readable `size_label`, a `tier` of `STANDARD`, `PERFORMANCE`, `DEMO`, or `JUNIOR`, the binding's supported DIN range `din_min` through `din_max`, the `purchase_price_cents` paid at retail, and the `base_daily_rate_cents` the unit rents for per day; both cent-denominated fields must be positive integers, with violations rejected as `ERR_INVALID_REQUEST`. New units enter as `AVAILABLE` with `accrued_rental_days` at zero. The fleet list can be filtered by `status`, `gear_type`, and `tier`.

Units circulate. A rental assignment moves a unit from `AVAILABLE` to `RESERVED`; handing the gear out moves it from `RESERVED` to `OUT`. When gear comes back — at rental return or season-lease close — the unit moves from `OUT` to `AWAITING_INSPECTION`, and its `accrued_rental_days` grows by the actual days it was out (or, at lease close, by the lease days elapsed). A `Technician` then records an inspection `outcome`: a verdict of `PASS` returns the unit to `AVAILABLE`, while `NEEDS_TUNE` or `DAMAGED` sends it to `IN_SERVICE`. Once the workshop finishes, a service-completion action by a `Technician` or `Manager` brings the unit from `IN_SERVICE` back to `AVAILABLE`.

Three exits remove a unit permanently. A `Manager` may retire a unit, moving it from `AVAILABLE` to `RETIRED`, but only while no assigned reservation line still references it; a unit in any other status, or one still referenced by an `ASSIGNED` reservation line, is rejected with `ERR_INVALID_STATE`. A fulfilled purchase moves a unit from `RESERVED` to `SOLD`. And a damage invoice declaring `TOTAL_LOSS` moves a unit from `AWAITING_INSPECTION` to `LOST`, pulling it out of the rentable fleet for good.

### 3.3. Booking a Rental: Reservations, Fitment, and the Assignment Selector

A rental begins when a `Customer`, `FrontDesk`, or `Manager` actor creates a reservation for a `customer_id`, with a `start_date` (the first rental day, inclusive), an `end_date` (the last planned rental day, also inclusive), and a `pickup_method` of `SHOP` or `SLOPE_SIDE`. The end date must not precede the start date — a reservation whose `end_date` falls before its `start_date` is rejected with `ERR_DATE_RANGE_INVALID`, and this date-window check is evaluated ahead of the generic field-shape checks on the same request. A new reservation carries two independent status axes that evolve in parallel: `fulfillment_status`, starting at `DRAFT`, and `payment_status`, starting at `UNPAID`. Its `quoted_total_cents`, `deposit_minimum_cents`, `deposit_authorized_cents`, `deposit_captured_cents`, and `deposit_released_cents` all start at zero, and `final_total_cents` remains unset until the gear comes back.

With the reservation open, the renter adds requested gear lines — but only while the reservation's fulfillment is `DRAFT` or `CONFIRMED`; adding a line to a reservation in any other state is rejected with `ERR_INVALID_STATE`. Each line names a `gear_type_requested` and a `tier_requested` — the same four gear types and four tiers the fleet uses — and enters as `QUEUED`, with its `equipment_item_id`, `daily_rate_cents`, `din_setting`, and `assigned_at` all unset. Adding a line is a mutation of the reservation itself: the reservation's `version` increments. The system computes `planned_days` for each line as the inclusive day count of the parent reservation's window — the difference between `end_date` and `start_date` plus one.

Assignment is where fitment physics meets inventory. When a `FrontDesk` or `Manager` operator triggers assignment of a queued line — permitted only while the parent reservation is `DRAFT` or `CONFIRMED` — the system computes a fitment DIN for the reservation's customer. The computation starts from a base of 0.5, adds 0.06 per kilogram of the customer's `weight_kg` and 0.005 per centimeter of `height_cm`, then applies a skier-type adjustment: minus 0.5 for `TYPE_1`, no adjustment for `TYPE_2`, plus 0.75 for `TYPE_3`. An age adjustment follows, measured in full years between the customer's `date_of_birth` and the logical clock date: minus 0.75 for a child younger than 10, no adjustment from 10 through 49 inclusive, and minus 0.5 for a skier of 50 or older. Finally, a boot-sole term adds 0.01 for every millimeter the customer's `boot_sole_mm` sits above the 285 mm reference length — or subtracts the same rate when the sole is shorter. The raw figure is clamped to the inclusive band from 0.75 to 12.0 and then rounded to the nearest quarter-step with ties rounding half up. A unit is eligible for the line only when its `gear_type` and `tier` match the request, the computed DIN falls within the unit's `din_min`-to-`din_max` range inclusive on both ends, and the reservation's date window does not collide with the unit's existing occupancy under the one-free-day rule of §2.7.

By default a selector policy picks from the eligible pool: the oldest-created eligible `AVAILABLE` unit wins — and since `id` values are identity-only, "oldest-created" is always decided by `created_at`. If the eligible pool is empty, the request still succeeds but the line simply stays `QUEUED`, waiting for future promotion. Alternatively, the operator may force a specific unit by supplying `preferred_equipment_item_id`, in which case the full battery of eligibility checks is enforced against that unit directly, in this order: a unit whose `gear_type` or `tier` does not match the request is rejected with `ERR_INVALID_REQUEST`; a unit whose DIN range does not cover the customer's computed fitment DIN is rejected with `ERR_DIN_MISMATCH`; a unit in a non-rentable status is rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`; and a date-window collision is rejected with `ERR_EQUIPMENT_OCCUPANCY_CONFLICT`.

A successful assignment moves the line from `QUEUED` to `ASSIGNED` and the unit from `AVAILABLE` to `RESERVED`, stamping three snapshots onto the line: `daily_rate_cents` copied from the unit's `base_daily_rate_cents` at that moment, the computed `din_setting`, and `assigned_at` taken from the logical clock. The reservation's `quoted_total_cents` is then recomputed as a forward-looking provisional quote: for each assigned line, the planned day count is multiplied by the snapshotted daily rate and discounted — ten percent off once the rental runs at least seven days, twenty percent off at fourteen days or more, no discount below seven — and each line is rounded half-up to whole cents before the lines are summed. The reservation list can be filtered by `customer_id`, `fulfillment_status`, and `payment_status`; the reservation-item list by `reservation_id`, `equipment_item_id`, and `status`.

Releasing a line — again only while the parent reservation is `DRAFT` or `CONFIRMED` — moves the line from `ASSIGNED` to `RELEASED` and, when no other assigned window keeps it committed, frees the unit from `RESERVED` back to `AVAILABLE`. Release is contagious in a useful way: the moment a unit comes free, the system runs waitlist promotion, scanning `QUEUED` lines system-wide in oldest-created order — considering only lines whose parent reservation is still `DRAFT` or `CONFIRMED` — and assigning the first line for which the freed unit passes the full eligibility battery (gear type, tier, DIN range, and the §2.7 occupancy rule) to the freed unit, which flips right back to `RESERVED` with fresh rate, DIN, and timestamp snapshots and triggers its own parent reservation's quote recompute.

### 3.4. From Confirm to Close: The Rental Money Cycle

Confirmation converts a draft into a commitment. A reservation in `DRAFT` fulfillment may be confirmed by the customer or staff once at least one line is `ASSIGNED` — attempting to confirm with no assigned line is rejected with `ERR_ITEMS_UNASSIGNED` — and once the caller supplies a `deposit_authorized_cents` hold. The hold must meet the floor: `deposit_minimum_cents` is computed as twenty percent of the current `quoted_total_cents`, rounded half-up, and a hold below that floor is rejected with `ERR_DEPOSIT_BELOW_MINIMUM`. Where both guards would fail, the assigned-line check runs before the deposit-floor check. The boundary is inclusive — a hold exactly equal to the minimum is accepted. Confirmation moves fulfillment from `DRAFT` to `CONFIRMED` and payment from `UNPAID` to `AUTHORIZED`, freezes the quote as the confirmed figure, and increments the reservation's `version`. Queued lines are allowed to survive confirmation; they do not block it.

Cancellation unwinds a reservation still in `DRAFT` or `CONFIRMED`. Fulfillment becomes `CANCELLED`; if payment had been `AUTHORIZED` it becomes `VOIDED`. Every assigned line is released and each freed unit returns to `AVAILABLE`; lines still `QUEUED` are moved to `RELEASED` as well — and each such release itself triggers waitlist promotion, so a cancellation can transitively assign waiting lines onto the freed units. The deposit waterfall settles per §2.8: `deposit_released_cents` is set so the authorized hold equals captured plus released.

Handing out the gear is a `FrontDesk` action on a `CONFIRMED` reservation, and here queued lines do block: if any line remains `QUEUED` the pickup is rejected with `ERR_ITEMS_UNASSIGNED`. A clean pickup moves fulfillment from `CONFIRMED` to `ACTIVE` (payment stays `AUTHORIZED`) and flips every assigned unit from `RESERVED` to `OUT`. From there the calendar takes over: when the logical clock moves past the reservation's `end_date` while fulfillment is still `ACTIVE` — whether noticed by the clock sweep or on read — the reservation slides into `OVERDUE`, with payment untouched.

Return settles the bill. A `FrontDesk` return action on an `ACTIVE` or `OVERDUE` reservation moves fulfillment to `RETURNED` and payment to `CAPTURED`, sends every unit from `OUT` to `AWAITING_INSPECTION`, moves each assigned line to a `RETURNED` line status, and computes the final charge per line using the chronological variant of the rental calculation. Each line's `actual_days` counts inclusively from `start_date` through the return date read from the logical clock. The planned days — `regular_days` being the smaller of actual and planned — are charged at the snapshotted daily rate with the same duration discount as the quote, rounded half-up per line. Any overrun becomes `late_days` — the excess of actual over planned days, never below zero — and is charged punitively at one and a half times the daily rate, rounded half-up per line, with no discount. The line's `line_final_cents` is the sum of its rounded regular and late portions, and the reservation's `final_total_cents` is the sum of all line finals. Return also updates the customer: each returned unit's `accrued_rental_days` grows by its actual days out (clamped so the increment never falls below zero), and if any line came back with `late_days` above zero the customer's `late_return_count` increments by one — once per reservation, not per line — followed immediately by the standing recomputation of §3.1.

Closing is the last step, and it waits for the workshop. A reservation in `RETURNED` fulfillment may be closed only when none of its units remains `OUT` or `AWAITING_INSPECTION`; attempting to close while a unit still awaits inspection is rejected with `ERR_ITEMS_PENDING_INSPECTION`. Closing moves fulfillment to `CLOSED` and payment from `CAPTURED` to `SETTLED`, and settles the deposit waterfall: every still-unclaimed portion of the hold is released so that authorized equals captured plus released. Both `CLOSED` and `CANCELLED` are terminal for fulfillment; `SETTLED` and `VOIDED` are terminal for payment.

### 3.5. The Tuning Workshop: Tickets, Quotes, and Daily Capacity

The workshop runs on tune tickets. Anyone — customer, counter staff, technician, or manager — may intake a ticket for a `customer_id`, naming either a fleet unit via `equipment_item_id` or the customer's own gear via a free-text `own_gear_description`. Exactly one of those two must be present; a ticket with both or neither is rejected with `ERR_INVALID_REQUEST`, as is any ticket whose `services` array is empty or whose amounts fail the general positivity rules. The `services` array names any non-empty combination of `WAX`, `EDGE_TUNE`, `BASE_GRIND`, and `BINDING_ADJUST`. Each service carries a fixed labor budget — forty-five minutes for a wax, sixty for an edge tune, ninety for a base grind, thirty for a binding adjustment — and the ticket's `labor_minutes` is their sum. A ticket may be flagged `rush`, promising twenty-four-hour turnaround instead of the standard forty-eight: the computed `promised_at` is exactly twenty-four hours after creation for rush tickets and forty-eight hours after for standard ones. The ticket list can be filtered by `customer_id`, `equipment_item_id`, and `status`.

Workshop capacity is declared day by day. A `Manager` creates a shop-day capacity row for a `service_date` — unique across all such rows, with a duplicate date rejected as `ERR_CAPACITY_EXISTS` — declaring the day's `base_labor_minutes` pool and a `rush_reserved_minutes` pool carved out of it, where the rush pool may not exceed the base pool; both pools must be non-negative, and a declaration violating either rule is rejected with `ERR_INVALID_REQUEST`. Consumption is tracked separately: `booked_minutes` accumulates standard labor as tickets start (and re-accumulates on rework), while `rush_booked_minutes` accumulates rush labor at ticket creation.

Capacity gates ticket intake, and the gates are checked in a fixed order. First, a capacity row must exist for the calendar date of the ticket's creation; intaking a ticket on an undeclared day is rejected with `ERR_CAPACITY_MISSING`. Second, for a rush ticket, the day's rush pool must have room: the sum of already-booked rush minutes and the new ticket's `labor_minutes` must not exceed `rush_reserved_minutes`, or the intake is rejected with `ERR_RUSH_CAPACITY_EXCEEDED`. An exact fit — booked plus new exactly equal to the reserved pool — is allowed. A successful rush intake immediately consumes the pool, adding the ticket's `labor_minutes` to `rush_booked_minutes`. Cancelling a ticket while it is still in `INTAKE` or `QUOTED` moves it to `CANCELLED` and returns those rush minutes to the pool.

Quoting is a technician's job. The quote calculation starts from fixed service prices — 2500 cents for a wax, 3000 for an edge tune, 4500 for a base grind, 2000 for a binding adjustment — sums them, adds any `parts_surcharge_cents` the technician sets, and then applies two multipliers in a pinned order: first a rush multiplier of 1.5 when the ticket is a rush job (1.0 otherwise), then a junior multiplier of 0.8 when the ticket's customer holds a season lease in `ACTIVE` or `SUSPENDED` status at quote time (1.0 otherwise). The result is rounded half-up to whole cents, only after both multipliers, and stored as `quoted_price_cents`; when the junior multiplier applied, the ticket's `junior_discount_applied` flag is set true. Quoting moves the ticket from `INTAKE` to `QUOTED`. A technician may also re-quote a ticket that is already `QUOTED` — supplying a revised `parts_surcharge_cents` — which keeps the ticket in `QUOTED`, recomputes the price, and increments the ticket's `version`, thereby invalidating any approval the customer was about to give against the old quote.

Approval belongs to the customer (or a `Manager` acting on their behalf) and is one of the system's two OCC-guarded writes, per §2.9: the request must carry `expected_tune_ticket_version` matching the ticket's current `version`, and a stale version is rejected with `ERR_STALE_VERSION`. Approval moves the ticket from `QUOTED` to `APPROVED` and itself increments the `version`.

Starting work is capacity-gated again: a technician may start an `APPROVED` ticket only when the capacity row for the ticket's creation date has room in its standard pool — booked standard minutes plus the ticket's `labor_minutes` must not exceed `base_labor_minutes`, or the start is rejected with `ERR_CAPACITY_FULL`. A successful start consumes the minutes, adds `labor_minutes` to `booked_minutes`, and moves the ticket to `IN_PROGRESS`. Completing the work moves it to `QUALITY_CHECK`.

Quality control decides the ending. A QC pass moves the ticket to `READY` and fixes the money: `final_price_cents` is set equal to `quoted_price_cents` — rework is never billed. A QC fail loops the ticket back to `IN_PROGRESS` for rework, under two guards evaluated in order: first the day's standard capacity is re-verified exactly as at start (rework consumes the pool a second time, adding `labor_minutes` to `booked_minutes` again, and a full pool yields `ERR_CAPACITY_FULL`), and then the rework counter is consulted — a ticket whose `rework_count` has already reached two may not fail QC again and is rejected with `ERR_REWORK_LIMIT_EXCEEDED`. Each rework increments `rework_count` by one. Once `READY`, the customer collects the gear and the ticket reaches `PICKED_UP`, terminal alongside `CANCELLED`.

### 3.6. Junior Season Leases: Activation, Growth Swaps, and Buyout

The season-lease program lets a junior skier or rider keep one package all winter. A `FrontDesk` or `Manager` operator creates a lease naming the `junior_customer_id`, an adult `guardian_customer_id`, the `season_start_date` and `season_end_date`, a `package_tier` of `JUNIOR_SKI` or `JUNIOR_BOARD`, and a refundable `deposit_cents`. Three creation-time rules apply in order after the generic date-range check (a season whose end does not fall after its start is rejected with `ERR_DATE_RANGE_INVALID`): the junior must be at most twelve full years old at the season start — a child who turns thirteen on or before `season_start_date` is ineligible and rejected with `ERR_JUNIOR_AGE_EXCEEDED`; and the guardian must be a different person from the junior and at least eighteen at the season start, or creation fails with `ERR_GUARDIAN_INVALID`. A new lease is `DRAFT`, with `equipment_item_id` unset, `swap_count` at zero, and `activated_at` empty. The lease list can be filtered by `junior_customer_id`, `guardian_customer_id`, `equipment_item_id`, and `status`.

Activation assigns the season's unit. The named unit must be `AVAILABLE`, of tier `JUNIOR`, and of the gear type matching the package — `JUNIOR_SKI` leases take `SKI` units, `JUNIOR_BOARD` leases take `SNOWBOARD` units. A unit failing the tier-or-gear match is rejected with `ERR_NOT_JUNIOR_TIER`; a unit not in rentable status is rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`. Activation re-verifies the junior's age at the season start, exactly as at creation, before it proceeds. On success the lease moves from `DRAFT` to `ACTIVE`, `activated_at` is stamped from the logical clock, and the unit moves from `AVAILABLE` to `OUT` for the season.

Kids grow, so the program allows mid-season growth swaps — at most two per lease. A swap names a `new_equipment_item_id` meeting the same junior-tier and gear-match rules, and is the system's second OCC-guarded write: the request must carry `expected_season_lease_version` equal to the lease's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` per §2.9. The swap limit is enforced after the version and state gates: a lease whose `swap_count` has reached two rejects further swaps with `ERR_SWAP_LIMIT_EXCEEDED`. A successful swap sends the old unit from `OUT` straight to `IN_SERVICE` — it goes to the workshop before any return to the fleet — moves the new unit from `AVAILABLE` to `OUT`, increments `swap_count`, and bumps the lease's `version`.

Leases answer to account standing. When the standing recomputation of §3.1 lands a junior customer in `BARRED`, every `ACTIVE` lease of that customer is suspended to `SUSPENDED` in the same cascade, and a suspended lease cannot be swapped — the state gate rejects the attempt with `ERR_INVALID_STATE`. Once the customer's standing recovers above `BARRED`, a `Manager` may reinstate the lease, moving it from `SUSPENDED` back to `ACTIVE`; reinstatement while the junior is still `BARRED` is refused with `ERR_INVALID_STATE`.

Closing the lease — from either `ACTIVE` or `SUSPENDED` — performs the end-of-season settlement. The unit moves from `OUT` to `AWAITING_INSPECTION`, its `accrued_rental_days` grows by the lease days elapsed, the `deposit_cents` is released in full, and two buyout valuations are computed and stored side by side. Both start from the unit's `purchase_price_cents` and a season length measured as the number of days between `season_start_date` and `season_end_date`; elapsed time is the number of days from the activation date to the close date, clamped so it never falls below zero nor exceeds the season length. The straight-line figure, `buyout_price_straight_line_cents`, depreciates the unit by half of its value spread across the season: the retained-value factor is one minus one-half times the fraction of the season elapsed, floored at forty percent, and the price is the purchase price times that factor, rounded half-up. The usage-weighted figure, `buyout_price_usage_cents`, ignores season length entirely and depreciates one percent of purchase price per day the unit was actually out on the lease, again floored at forty percent retained and rounded half-up. The two figures diverge on virtually every real lease, and both are stored so the family can be offered either basis. Closing moves the lease to `SETTLED`, its terminal state.

### 3.7. Demo Days and Purchase Upgrades

A demo day converts a rental fee into purchase intent. A `FrontDesk` or `Manager` operator records a demo credit for a `customer_id` against a specific unit, with the `demo_date` the fee was paid and the `fee_paid_cents` amount, which must be positive. Only `DEMO`-tier units qualify; recording a demo day against any other tier is rejected with `ERR_NOT_DEMO_TIER`. One hundred percent of the fee becomes credit: `credit_cents` equals `fee_paid_cents`. The credit is born `ACTIVE` and expires ninety days after the demo date — `expires_at` is set to midnight UTC on the day ninety days out. When the logical clock reaches that instant, the credit flips to `EXPIRED`, whether noticed by the clock sweep or on read. The credit list can be filtered by `customer_id`, `equipment_item_id`, and `status`.

Buying gear runs through purchase orders. A customer or staff member creates an order naming the `customer_id` and the `equipment_item_id` being bought, optionally with a `demo_credit_id` to apply. The unit must be `AVAILABLE`; creating the order moves it to `RESERVED`. Pricing follows the demo-and-upgrade rule. The `list_price_cents` is three quarters of the unit's `purchase_price_cents`, rounded half-up, for a `DEMO`-tier unit, and the full purchase price for any other tier. Eligible credits are the customer's `ACTIVE` demo credits that have not yet expired, considered oldest first. The total credit is capped at thirty percent of the list price, rounded half-up: `credit_applied_cents` is the smaller of the summed eligible credits and that cap, and `amount_due_cents` is the list price minus the applied credit. When the caller names a specific `demo_credit_id`, that credit alone is applied toward the order (subject to the same thirty-percent cap) rather than the full eligible pool, and it must be among the eligible set — the expiry check runs first, so a credit whose validity has lapsed is rejected with `ERR_DEMO_CREDIT_EXPIRED`, and a credit that belongs to another customer or is not `ACTIVE` is rejected with `ERR_DEMO_CREDIT_NOT_REDEEMABLE`. The order list can be filtered by `customer_id`, `equipment_item_id`, `demo_credit_id`, and `status`.

The order then walks a short path. Paying moves it from `PENDING` to `PAID` and redeems every demo credit applied to the order, flipping each from `ACTIVE` to `REDEEMED`. Fulfillment — a `FrontDesk` handover — moves a `PAID` order to `FULFILLED` and the unit from `RESERVED` to `SOLD`. Cancelling is possible only while the order is still `PENDING`: the order becomes `CANCELLED`, the unit returns from `RESERVED` to `AVAILABLE` — triggering the same waitlist promotion as a released rental line (§3.3) — and any credits referenced are left untouched — cancellation never redeems or consumes them.

### 3.8. Damage Assessments and the Standing Cascade

When gear comes back hurt, a `Technician` creates a damage assessment naming the `reservation_id` and the hurt `equipment_item_id`, a `severity` of `COSMETIC`, `MINOR`, `MAJOR`, or `TOTAL_LOSS`, and optional free-text `notes`. The reservation must be in `RETURNED` fulfillment — not yet `CLOSED` — and the unit must have genuinely been an item of that reservation, in any line status including already-`RETURNED` lines; a unit that was never on the reservation is rejected with `ERR_ITEM_NOT_IN_RESERVATION`. The assessment list can be filtered by `reservation_id`, `equipment_item_id`, and `status`.

The charge is computed at creation. Each severity maps to a percentage of the unit's `purchase_price_cents`: ten percent for `COSMETIC`, twenty-five for `MINOR`, fifty for `MAJOR`, and the full price for `TOTAL_LOSS`. But the unit's age caps the exposure: the depreciation factor starts at full value and sheds two percent for every complete thirty-day block in the unit's `accrued_rental_days`, never falling below a thirty-percent floor. The depreciated value is the purchase price times that factor, rounded half-up. The final `charge_cents` is the smaller of the severity percentage of the purchase price and the depreciated value, rounded half-up — so a heavily depreciated unit's `TOTAL_LOSS` costs noticeably less than its sticker price. A new assessment is `DRAFT`, with `deposit_captured_cents` at zero and `remainder_due_cents` initialized to the full `charge_cents`.

Invoicing is where the assessment bites, and it fires a four-link cascade, all atomic with the request. Invoicing requires the parent reservation still in `RETURNED` fulfillment; once the reservation is `CLOSED` the state gate rejects the invoice with `ERR_INVALID_STATE`. Link one moves money: the invoice captures from the reservation's deposit hold the smaller of the charge and the as-yet-uncaptured portion of the authorized hold — assessments against one reservation capturing in creation order, earliest first — adds that amount to the reservation's `deposit_captured_cents`, records it as the assessment's own `deposit_captured_cents`, and sets the assessment's `remainder_due_cents` to whatever of the charge the deposit could not cover. Link two recomputes the renter's standing per §3.1, because a new unpaid invoiced assessment — above all an unpaid `TOTAL_LOSS` — can push the customer to `WATCH` or `BARRED`. Link three is the consequence: if standing lands on `BARRED`, every `ACTIVE` season lease of that customer suspends immediately. The fan-out link handles the unit: an invoice at severity `TOTAL_LOSS` flips the unit from `AWAITING_INSPECTION` to `LOST`. The assessment itself moves from `DRAFT` to `INVOICED`.

Settlement and dispute close the loop. The customer pays the remainder, moving the assessment from `INVOICED` to `PAID` and triggering a standing recompute — clearing the last unpaid invoice can lift a customer back out of `BARRED`. Alternatively the customer disputes, moving the assessment from `INVOICED` to `DISPUTED`. Disputes are resolved by a `Manager` supplying a `resolution`: `UPHELD` sends the assessment back to `INVOICED`, replacing `charge_cents` with an `adjusted_charge_cents` when one is provided and adjusting the reservation's captured deposit by the resulting delta; `WAIVED` moves the assessment to `WAIVED`, returns this assessment's captured amount to the reservation's deposit — reducing `deposit_captured_cents` by exactly what this assessment captured — and recomputes standing. `PAID` and `WAIVED` are terminal.

### 3.9. Slope-Side Pickup Logistics

For guests who want gear delivered to the lifts, the shop runs a van on scheduled windows. A `Manager` opens a pickup window by declaring its `service_date`, `start_time` and `end_time` in 24-hour `HH:MM` form, a `location_label` naming the slope-side spot, and a `van_capacity` — the maximum number of bookings the van can serve, which must be positive. The end must fall strictly after the start or creation fails with `ERR_DATE_RANGE_INVALID`. Windows are half-open intervals: the start instant belongs to the window, the end instant does not. Within the same location and date, two windows may touch — one ending exactly when another begins — but any strict overlap is rejected with `ERR_WINDOW_OVERLAP`. A window's `booked_count` starts at zero, and its `posture` is derived rather than stored by hand: `CLOSED` once the logical clock reaches the window's end, `FULL` when the count of live bookings has reached `van_capacity` — an exact fit fills the window — and otherwise `OPEN`. The window list can be filtered by `service_date`, `location_label`, and `posture`.

Booking a reservation into a window is allowed for customers and staff, and three checks guard it in order. The window's end must still be in the future relative to the logical clock — booking into an expired window is rejected with `ERR_WINDOW_EXPIRED`. The window must have room — a `FULL` window rejects further bookings with `ERR_WINDOW_FULL`. And the reservation named by `reservation_id` must be in `CONFIRMED` fulfillment, or the booking is rejected with `ERR_RESERVATION_NOT_CONFIRMED`. A successful booking enters as `BOOKED` and increments the window's `booked_count`, which may itself tip the posture from `OPEN` to `FULL`. The booking list can be filtered by `pickup_window_id`, `reservation_id`, and `status`.

Bookings resolve in three ways. A `FrontDesk` operator marks the slope-side handoff done, moving the booking from `BOOKED` to `COMPLETED` — but only while the window has not yet closed. The customer may cancel, moving the booking to `CANCELLED` under the same not-closed constraint, which decrements the window's `booked_count` and can drop a `FULL` window back to `OPEN`. Both resolution paths are gated on the window not being closed; a completion or cancellation attempted against a closed window is rejected with `ERR_INVALID_STATE`. And when the logical clock reaches a window's end, the window closes and every booking still `BOOKED` at that moment is swept to `NO_SHOW`, with the closed window's `booked_count` reset to zero.

## 4. Endpoint Definitions

Endpoints that create a new stand-alone resource return `201 Created`; endpoints that modify an existing resource or drive a state transition return `200 OK`. All resources live under the `/shop` prefix, except the logical-clock administration endpoint.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shop/customers` | Register a customer profile | FrontDesk, Manager |
| GET | `/shop/customers/{id}` | Fetch one customer | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/equipment-items` | Add a unit to the fleet | Manager |
| GET | `/shop/equipment-items/{id}` | Fetch one unit | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/equipment-items` | List/filter fleet units | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/equipment-items/{id}/retire` | Retire an AVAILABLE unit | Manager |
| POST | `/shop/equipment-items/{id}/inspect` | Post-return inspection verdict | Technician, Manager |
| POST | `/shop/equipment-items/{id}/service-complete` | Return a serviced unit to the fleet | Technician, Manager |
| POST | `/shop/reservations` | Create a rental reservation (DRAFT/UNPAID) | Customer, FrontDesk, Manager |
| GET | `/shop/reservations/{id}` | Fetch one reservation | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/reservations` | List/filter reservations | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/reservations/{id}/items` | Add a requested gear line (QUEUED) | Customer, FrontDesk, Manager |
| GET | `/shop/reservation-items/{id}` | Fetch one reservation item | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/reservation-items` | List/filter reservation items | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/reservation-items/{id}/assign` | Assign a unit via selector or preferred unit | FrontDesk, Manager |
| POST | `/shop/reservation-items/{id}/release` | Release an assignment back to the pool | FrontDesk, Manager |
| POST | `/shop/reservations/{id}/confirm` | Confirm with deposit hold | Customer, FrontDesk, Manager |
| POST | `/shop/reservations/{id}/cancel` | Cancel a DRAFT/CONFIRMED reservation | Customer, FrontDesk, Manager |
| POST | `/shop/reservations/{id}/pickup` | Hand out the gear | FrontDesk, Manager |
| POST | `/shop/reservations/{id}/return` | Take back all gear and settle the final charge | FrontDesk, Manager |
| POST | `/shop/reservations/{id}/close` | Close after inspection; settle the deposit waterfall | FrontDesk, Manager |
| POST | `/shop/tune-tickets` | Intake a tune/wax/edge service ticket | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/tune-tickets/{id}` | Fetch one ticket | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/tune-tickets` | List/filter tickets | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/tune-tickets/{id}/quote` | Compute or recompute the quote | Technician, Manager |
| POST | `/shop/tune-tickets/{id}/approve` | Customer approves the observed quote (OCC) | Customer, Manager |
| POST | `/shop/tune-tickets/{id}/start` | Technician starts work; consumes standard capacity | Technician, Manager |
| POST | `/shop/tune-tickets/{id}/complete` | Work done, enters QC | Technician, Manager |
| POST | `/shop/tune-tickets/{id}/qc-pass` | QC pass; finalize price | Technician, Manager |
| POST | `/shop/tune-tickets/{id}/qc-fail` | QC fail; rework loop (max 2) | Technician, Manager |
| POST | `/shop/tune-tickets/{id}/pickup` | Customer collects the gear | Customer, FrontDesk, Manager |
| POST | `/shop/tune-tickets/{id}/cancel` | Cancel from INTAKE/QUOTED; returns rush minutes | Customer, FrontDesk, Manager |
| POST | `/shop/season-leases` | Create a junior season lease (DRAFT) | FrontDesk, Manager |
| GET | `/shop/season-leases/{id}` | Fetch one lease | FrontDesk, Technician, Manager |
| GET | `/shop/season-leases` | List/filter leases | FrontDesk, Technician, Manager |
| POST | `/shop/season-leases/{id}/activate` | Assign the initial junior unit for the season | FrontDesk, Manager |
| POST | `/shop/season-leases/{id}/swap` | Mid-season growth swap (OCC; max 2) | FrontDesk, Manager |
| POST | `/shop/season-leases/{id}/close` | End-of-season return and settlement | FrontDesk, Manager |
| POST | `/shop/season-leases/{id}/reinstate` | Lift a standing-driven suspension | Manager |
| POST | `/shop/demo-credits` | Record a paid demo day (credit accrues) | FrontDesk, Manager |
| GET | `/shop/demo-credits/{id}` | Fetch one demo credit | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/demo-credits` | List/filter demo credits | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/purchase-orders` | Buy a unit with demo & upgrade pricing | Customer, FrontDesk, Manager |
| GET | `/shop/purchase-orders/{id}` | Fetch one purchase order | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/purchase-orders` | List/filter purchase orders | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/purchase-orders/{id}/pay` | Pay the order; redeem applied credits | Customer, FrontDesk, Manager |
| POST | `/shop/purchase-orders/{id}/fulfill` | Hand over the sold unit | FrontDesk, Manager |
| POST | `/shop/purchase-orders/{id}/cancel` | Cancel an unpaid order; free the unit | Customer, FrontDesk, Manager |
| POST | `/shop/damage-assessments` | Assess damage on a returned item | Technician, Manager |
| GET | `/shop/damage-assessments/{id}` | Fetch one assessment | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/damage-assessments` | List/filter assessments | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/damage-assessments/{id}/invoice` | Invoice: capture from deposit; cascades to standing and leases | FrontDesk, Manager |
| POST | `/shop/damage-assessments/{id}/pay` | Customer pays the remainder | Customer, FrontDesk, Manager |
| POST | `/shop/damage-assessments/{id}/dispute` | Customer disputes the invoice | Customer, Manager |
| POST | `/shop/damage-assessments/{id}/resolve` | Manager resolves a dispute | Manager |
| POST | `/shop/pickup-windows` | Open a slope-side pickup window | Manager |
| GET | `/shop/pickup-windows/{id}` | Fetch one window | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/pickup-windows` | List/filter windows | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/pickup-bookings` | Book a confirmed reservation into a window | Customer, FrontDesk, Manager |
| GET | `/shop/pickup-bookings/{id}` | Fetch one booking | Customer, FrontDesk, Technician, Manager |
| GET | `/shop/pickup-bookings` | List/filter bookings | Customer, FrontDesk, Technician, Manager |
| POST | `/shop/pickup-bookings/{id}/cancel` | Cancel a booking; frees capacity | Customer, FrontDesk, Manager |
| POST | `/shop/pickup-bookings/{id}/complete` | Mark the slope-side handoff done | FrontDesk, Manager |
| POST | `/shop/shop-day-capacity` | Declare technician labor pools for a day | Manager |
| GET | `/shop/shop-day-capacity/{id}` | Fetch one capacity row | FrontDesk, Technician, Manager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock; triggers clock-driven sweeps | Manager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DATE_RANGE_INVALID` | 422 |
| `ERR_WINDOW_EXPIRED` | 422 |
| `ERR_DEMO_CREDIT_EXPIRED` | 422 |
| `ERR_DIN_MISMATCH` | 422 |
| `ERR_EQUIPMENT_NOT_AVAILABLE` | 409 |
| `ERR_EQUIPMENT_OCCUPANCY_CONFLICT` | 409 |
| `ERR_WINDOW_OVERLAP` | 409 |
| `ERR_WINDOW_FULL` | 409 |
| `ERR_CAPACITY_MISSING` | 422 |
| `ERR_RUSH_CAPACITY_EXCEEDED` | 409 |
| `ERR_CAPACITY_FULL` | 409 |
| `ERR_CAPACITY_EXISTS` | 409 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 |
| `ERR_SWAP_LIMIT_EXCEEDED` | 409 |
| `ERR_JUNIOR_AGE_EXCEEDED` | 422 |
| `ERR_GUARDIAN_INVALID` | 422 |
| `ERR_NOT_JUNIOR_TIER` | 422 |
| `ERR_NOT_DEMO_TIER` | 422 |
| `ERR_RESERVATION_NOT_CONFIRMED` | 409 |
| `ERR_ITEMS_UNASSIGNED` | 409 |
| `ERR_ITEMS_PENDING_INSPECTION` | 409 |
| `ERR_ITEM_NOT_IN_RESERVATION` | 422 |
| `ERR_DEMO_CREDIT_NOT_REDEEMABLE` | 409 |
| `ERR_DEPOSIT_BELOW_MINIMUM` | 422 |

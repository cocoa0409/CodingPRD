# Snowmobile / Powersport Rental & Guided Tour API — Product Requirements Document

## 1. Introduction

Backcountry powersport operations live or die by the careful choreography of a finite fleet against the weather. A guided snowmobile outfitter owns a limited stable of sleds, a roster of certified guides, and a closet of safety gear, and must allocate all three across overlapping tour windows while never compromising rider safety or running afoul of trail conditions that can change in minutes. This API exists to be the system of record for that choreography: it tracks unit and gear inventory by capability class, schedules guided tour departures along named trails, takes rider reservations against those departures, enforces the liability, age, and training gates that protect both rider and operator, and reconciles the financial picture from an estimated quote at booking to a final settlement at return.

The platform treats four concerns as first-class. **Allocation** governs how a scarce pool of sleds, gear items, and guides is competed for across departures whose time windows may overlap. **Temporal windowing** governs reservation intervals on a unit and the closure windows that a dispatcher may impose on a trail when conditions deteriorate. **Cascading consistency** ensures that closing a trail tears down its scheduled departures, which in turn unwinds their reservations and refunds held deposits, all atomically within the triggering request. Finally, **dual-variant billing** distinguishes the forward-looking estimate quoted when a rider confirms from the backward-looking settlement computed when the sled comes home with its actual fuel level, lateness, damage, and any lost gear folded in. The sections that follow specify these rules precisely enough that two independent implementations would behave identically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than member self-registration must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the capacity in which they are acting. A request that omits either header, or carries a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly five roles, spelled precisely as follows: `Anonymous`, `Member`, `Guide`, `DispatchOperator`, and `PlatformAdmin`.

`Anonymous` is the unauthenticated caller. The only thing an `Anonymous` caller may do is self-register a new member; that single endpoint is the lone exception to the authentication requirement.

`Member` is a rider. When `X-User-Role` is `Member`, the `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a member compare that resource's member foreign key to `X-User-ID`. Concretely, a `Member` may only act on a reservation whose `member_id` equals their `X-User-ID`. When an entity-backed `Member` attempts to confirm, cancel, or otherwise act on a reservation they do not own, the request is rejected with `ERR_OWNERSHIP_REQUIRED`.

`Guide` leads departures. When `X-User-Role` is `Guide`, the `X-User-ID` is the `id` of the acting `Guide`; ownership checks compare the relevant assignment's guide foreign key to `X-User-ID`. A `Guide` may only depart or complete a tour to which they are actually assigned; acting on a departure they do not lead is rejected with `ERR_OWNERSHIP_REQUIRED`.

`DispatchOperator` is operations staff. When `X-User-Role` is `DispatchOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same is true of `PlatformAdmin`, the operator/superuser role used for configuration, broad read access, and test-driving the logical clock: when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque identifier the server does not match against any entity. The full operation-to-role mapping appears in the endpoint table of §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order — that is, by `created_at` from oldest to newest.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Identity

Most resources in this system are full first-class records and carry a standard set of server-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at the instant the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource. The `version` is an integer that begins at 1 on creation and increments by one on every mutation; it underpins the optimistic concurrency mechanism described in §2.6.

Two entities are deliberately lightweight audit records rather than mutable resources: a `GuideAssignment` and a `ClosureEvent` each carry only an `id` and a `created_at`. Neither one carries an `updated_at` and neither carries a `version`; their state is not concurrency-controlled and they are not independently versioned. Every other entity — `Member`, `Guide`, `Trail`, `Unit`, `GearItem`, `TourDeparture`, `Reservation`, and `Settlement` — carries the full `id`, `created_at`, `updated_at`, and `version` quartet.

### 2.5. Inventory, Closure, and Hierarchical Consistency

The system holds itself to immediate, atomic consistency: when one operation triggers a cascade, every downstream effect resolves before the triggering request returns. Whenever a mutation changes a versioned resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is true both for direct edits and for changes the server makes on a resource's behalf during a cascade. A reservation that is swept into `CANCELLED` because its departure was cancelled, for example, has its own `updated_at` and `version` advanced as part of the same request.

The deepest cascade in the system begins at a trail closure and runs three hops deep: closing a trail cancels each of its still-open departures, each cancelled departure unwinds its live reservations, and each unwound reservation releases its unit, releases its gear, and refunds any held deposit. The precise rules for each hop are spelled out in §3, but the governing principle is that all of it happens inside the single request that closed the trail, with every affected resource's `version` and `updated_at` advanced accordingly.

### 2.6. Optimistic Concurrency on Departure Confirmation

Confirming a reservation onto a departure is the one operation guarded by optimistic concurrency control. The confirm request must carry `expected_tour_departure_version`, a non-optional field whose value is the client's last observed `version` of the target `TourDeparture`. Before the confirm proceeds, the server compares that value against the departure's current `version`. If another writer has advanced the departure's version since the client last read it — most commonly because a different rider has already confirmed onto the same departure, which legitimately bumps `rider_count` and the departure's `version` — then the client's view of the remaining capacity is stale and the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). This rejection is framed entirely in terms of stale versions, not request timing: it fires whenever the supplied version does not equal the live version, regardless of how the two requests were spaced. No other endpoint in the system takes a version field; confirmation is the sole bearer of the OCC contract.

### 2.7. Capability Classes and Ordering

Three of the system's entities are ranked on a shared capability ladder with the fixed ordering `TRAIL` below `UTILITY` below `MOUNTAIN`. A `Unit` declares its `unit_class`, a `Guide` declares the highest class it is certified to lead in `max_class`, a `Trail` declares the minimum class it permits in `required_class`, and a `TourDeparture` declares the minimum guide class it needs in `required_guide_class`. Wherever the rules speak of a class being "high enough," they mean the comparison runs along this ladder: a sled satisfies a trail when its `unit_class` rank is greater than or equal to the trail's `required_class` rank, and a guide satisfies a departure when its `max_class` rank is greater than or equal to the departure's `required_guide_class` rank.

### 2.8. Monetary Values, Precision, and Rounding

All monetary amounts are stored and exchanged as integer counts of whole cents; there are no fractional-cent values anywhere in the system. Where a calculation produces a non-integer intermediate — a percentage discount, a per-liter fuel charge — the result is rounded to the nearest whole cent using the round-half-up convention, meaning a value exactly halfway between two cents rounds up to the larger. The specific point at which rounding is applied matters and is pinned per calculation in §3; implementers must round at exactly the stated step, not earlier and not later.

### 2.9. The Logical Clock

Every time-dependent rule in the system — rider age at a departure, waiver validity, late-return minutes, whether a departure may yet be boarded — is evaluated against a single logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-04-01T00:00:00Z`, and before any clock-setting call it stays at that default and never falls back to real time. A `PlatformAdmin` may advance or reset the clock to any absolute ISO 8601 UTC instant supplied as `to_iso8601`. Setting the clock also re-evaluates waiver expiry across members, as described in §3.

### 2.10. Nested Resource Retrieval and Existence Ordering

The URL space is a flat set of collections — members, guides, trails, units, gear items, tour departures, reservations, settlements — with reverse-reachability list endpoints hanging off a parent identifier (for instance, the reservations belonging to a member or the departures running on a trail). When a request names resources in its path or body, the server validates their existence left to right in the natural reference order — member, trail, unit, gear, departure, reservation — and the first identifier that does not resolve to an existing record causes the request to fail with `ERR_NOT_FOUND` before any later identifier or business rule is examined.

## 3. Business Logic & Workflows

### 3.1. Members: Registration, Waivers, Age, and Training

A rider enters the system by self-registering, which is the only action available to an `Anonymous` caller. Registration supplies the rider's `full_name`, a contact `email`, and a `date_of_birth` given as an ISO 8601 calendar date in `YYYY-MM-DD` form, and may optionally supply a `membership_tier` and a `membership_expires_at` instant. The `email` must be unique among members on a case-insensitive basis; a collision is rejected with `ERR_DUPLICATE`. The `membership_tier` is one of `NONE`, `SEASON`, or `PREMIER` and defaults to `NONE` when omitted, while `membership_expires_at` is an ISO 8601 UTC instant marking when paid benefits lapse and defaults to null (it is always null for a `NONE` member). A freshly registered member begins with `waiver_status` of `UNSIGNED`, a null `waiver_signed_at`, `training_level` of `NONE`, a `deposit_hold_cents` of 0, and a `lifetime_damage_strikes` count of 0.

The liability waiver follows its own small lifecycle across three states: `UNSIGNED`, `SIGNED`, and `EXPIRED`. A member signs their waiver from either the `UNSIGNED` or the `EXPIRED` state, moving in both cases to `SIGNED`. Signing is permitted only when the member is at least 18 years old at the signing instant (their age derived from `date_of_birth` against the logical clock now), or when the request explicitly supplies `guardian_ack` set to true; a minor signing without guardian acknowledgement cannot advance. On a successful signing the server stamps `waiver_signed_at` with the current clock instant. A waiver does not stay valid forever: when the clock now is later than `waiver_signed_at` plus the waiver validity window of 365 days, the waiver lapses from `SIGNED` to `EXPIRED` and its `waiver_signed_at` stamp is cleared. This lapse is re-evaluated whenever the logical clock is set, and may also be forced on demand through a dispatcher-or-admin re-evaluation capability that moves a stale `SIGNED` waiver to `EXPIRED` and clears the stamp; if the waiver is still within its window the re-evaluation leaves it untouched.

Training competency advances linearly through `NONE`, then `BASIC`, then `ADVANCED`, with `ADVANCED` being terminal. A `DispatchOperator` advances a member by submitting the target `level`. The move from `NONE` to `BASIC` requires the request `level` to be `BASIC` and requires the member's `waiver_status` to already be `SIGNED`. The move from `BASIC` to `ADVANCED` requires the request `level` to be `ADVANCED`. The significance of `ADVANCED` is that it is the prerequisite for riding any `MOUNTAIN`-class sled, enforced at confirmation time as described in §3.5.

### 3.2. Fleet, Gear, Guides, and Trails

The dispatcher and platform admin stock the operation's inventory. A `Unit` — a single sled — is created with a `vin_tag` asset tag that must be unique among units (a duplicate is rejected with `ERR_DUPLICATE`), a `unit_class` drawn from the capability ladder, a `daily_rate_cents` base rental rate per departure-day that must be zero or greater, a `deposit_cents` security-deposit amount that must be zero or greater, and a `tank_capacity_liters` fuel-tank capacity that must be strictly greater than zero. A new unit starts `AVAILABLE` and its `status` moves through `RESERVED`, `OUT`, and `MAINTENANCE` over its life. A dispatcher may take an `AVAILABLE` unit into `MAINTENANCE` directly; this is only permitted while the unit is `AVAILABLE`, with no active reservation hold against it. The same maintenance capability returns a unit from `MAINTENANCE` back to `AVAILABLE` when the request carries `return_to_service` set to true.

A `GearItem` is a helmet or a suit, created with a `kind` of either `HELMET` or `SUIT`, a free-form `size_code` label, and a `replacement_cost_cents` amount (zero or greater) charged if the item is lost. A gear item's `status` moves through `AVAILABLE`, `ASSIGNED`, `OUT`, and the terminal `RETIRED` state; the lifecycle transitions are all side effects of reservation actions, detailed in §3.4 and §3.6.

A `Guide` is created with a `full_name` and a `max_class` on the capability ladder, and begins with a `status` of `AVAILABLE`, toggling to `OFF_DUTY` while leading. A `Trail` is created with a `name`, a `required_class` minimum sled class, and a `max_riders` cap that must be at least 1, and begins with a `condition` of `OPEN`. Trail condition is one of `OPEN`, `CAUTION`, or `CLOSED`, and its transitions are the subject of §3.7.

### 3.3. Scheduling Departures and Staffing Guides

A `DispatchOperator` schedules a `TourDeparture` on a trail by supplying the `trail_id` of the route, the `starts_at` and `ends_at` instants of the window (with `starts_at` strictly before `ends_at`), the `required_guide_class` the departure demands, and a `capacity_riders` cap that must be at least 1. The `starts_at` instant doubles as the booking-cutoff anchor for the departure. A new departure begins with a `status` of `SCHEDULED` and `rider_count` and `guide_count` both at 0, and that `status` progresses through `LOCKED`, `DEPARTED`, and `COMPLETED`, or off to the terminal `CANCELLED`. The effective rider capacity of a departure is never larger than the trail allows: it is the smaller of the departure's own `capacity_riders` and the trail's `max_riders`.

Staffing a departure means assigning guides to it. A `DispatchOperator` assigns a guide by submitting the `guide_id`; this is allowed only when the guide's `max_class` rank is at least the departure's `required_guide_class` rank, failing which the assignment is rejected with `ERR_GUIDE_CLASS_TOO_LOW`. A guide also may not be assigned to a departure whose window overlaps a departure they are already actively assigned to: if the guide has any other active assignment whose departure window, taken as the half-open interval from `starts_at` up to but not including `ends_at`, overlaps this departure's window, the assignment is rejected with `ERR_GUIDE_DOUBLE_BOOKED`. A successful assignment creates a `GuideAssignment` linking the `tour_departure_id` and the `guide_id` with its `active` flag set to true, moves the guide from `AVAILABLE` to `OFF_DUTY`, and increments the departure's `guide_count` by one. Unassigning a guide reverses this: the matching `GuideAssignment` has its `active` flag set to false, the departure's `guide_count` is decremented but never driven below zero, and the guide returns from `OFF_DUTY` to `AVAILABLE` provided they hold no other active assignment.

The number of guides a departure needs scales with its riders. When `rider_count` is zero, no guides are required. Otherwise the required-guide count is at least one, and beyond that one guide is needed for each started group of six riders — formally, the required count is the larger of one and the rider count divided by six and rounded up to the next whole number. The ratio of six riders per guide is the governing breakpoint, and the requirement is recomputed as riders confirm and as guides are assigned.

A departure is locked by a `DispatchOperator` to freeze its roster ahead of the tour. Locking moves the departure from `SCHEDULED` to `LOCKED` and is gated by three conditions. First, the departure's trail must not be `CLOSED`; locking against a closed trail is rejected with `ERR_TRAIL_CLOSED`. Second, the departure must already carry at least one confirmed rider, and its `guide_count` must meet or exceed the required-guide count derived from the ratio above; a lock that has too few guides for its riders, or that has no riders at all, is rejected with `ERR_GUIDE_RATIO_UNMET`. Once a departure is `LOCKED`, no further reservation may be created or confirmed onto it. An attempt to drive the lock transition from any state other than `SCHEDULED` is rejected with `ERR_INVALID_STATE`.

### 3.4. Reservations: Booking and Confirmation

A reservation pairs a rider, a departure, a sled, and optionally gear. A `Member` (acting on their own behalf) or a `DispatchOperator` creates one by supplying the `member_id` of the rider, the `tour_departure_id` of the departure, the `unit_id` of the sled, and optionally a `helmet_gear_id` and a `suit_gear_id`; both gear fields default to null when omitted. The helmet slot must reference a `GearItem` whose `kind` is `HELMET`, and the suit slot must reference one whose `kind` is `SUIT`; a slot/kind mismatch is rejected with `ERR_GEAR_KIND_MISMATCH`. Creation produces a reservation in `reservation_status` `PENDING` and `settlement_status` `NONE`, with no holds yet placed on any inventory; its computed `estimated_total_cents`, `deposit_hold_cents`, `checked_out_at`, `returned_at`, and `fuel_return_fraction` all begin empty or zero.

A reservation carries two independent status dimensions that advance separately. The lifecycle dimension, `reservation_status`, runs through `PENDING`, `CONFIRMED`, `CHECKED_OUT`, `RETURNED`, `CANCELLED`, and `NO_SHOW`. The billing dimension, `settlement_status`, runs through `NONE`, `HELD`, `SETTLED`, and `REFUNDED`. The two never collapse into one: a reservation may be `CHECKED_OUT` on the lifecycle axis while still `HELD` on the billing axis, and the settlement axis advances only as a side effect of lifecycle transitions, never by direct request.

Confirmation is the gateway from intent to commitment, and it is the most heavily guarded operation in the system. A `Member` or `DispatchOperator` confirms a `PENDING` reservation, supplying `expected_tour_departure_version` as described in §2.6. On success the reservation moves from `PENDING` to `CONFIRMED`; its `settlement_status` advances from `NONE` to `HELD`; the chosen unit moves from `AVAILABLE` to `RESERVED` and the chosen gear from `AVAILABLE` to `ASSIGNED`; the deposit hold is computed and placed (§3.8); the estimated quote is computed (§3.5); the departure's `rider_count` is incremented by one and its `version` is incremented by one; and the member's `deposit_hold_cents` is recomputed. The member's `deposit_hold_cents` is at all times the sum of the active security-deposit holds across that member's reservations currently in the `HELD` billing state, recomputed every time a hold is placed or released.

The checks at confirmation are evaluated in a fixed priority order, so that an earlier failure masks a later one and tests always see the first applicable rejection. The general request gates run first: authentication (`ERR_UNAUTHENTICATED`), role authorization (`ERR_UNAUTHORIZED`), ownership for an entity-backed `Member` (`ERR_OWNERSHIP_REQUIRED`), existence of every referenced resource (`ERR_NOT_FOUND`), and well-formedness of the body including correct types, enums, and ranges (`ERR_INVALID_REQUEST`). Next comes the state gate: the reservation must actually be in a state from which confirmation is defined, namely `PENDING`, or the request fails with `ERR_INVALID_STATE`. Then the confirmation-specific business gates fire in this exact sequence: the departure must still be open, then the waiver must be signed, then the rider must be old enough, then training must suffice for the unit class, then the unit must be capable for the trail, then the unit must not be double-booked, then the gear must not be double-booked, then there must be capacity remaining, and finally the optimistic-concurrency version must match. The precise meaning of each of these gates is given in §3.5, and the capacity and version gates in §3.6 and §2.6.

### 3.5. Confirmation Safety Gates and the Estimated Quote

The confirmation safety gates protect rider and operator, and each maps to a specific rejection. The departure-open gate requires the `TourDeparture` to still be `SCHEDULED` — not `LOCKED`, `DEPARTED`, `CANCELLED`, or `COMPLETED` — because a locked or departed tour no longer accepts riders; a confirm against a non-`SCHEDULED` departure is rejected with `ERR_DEPARTURE_NOT_OPEN`. The waiver gate requires the member's `waiver_status` to be `SIGNED`; otherwise the confirm is rejected with `ERR_WAIVER_NOT_SIGNED`. The age gate requires the member's age, computed at the departure's `starts_at` instant, to be at least the minimum riding age of 16 years; a younger rider is rejected with `ERR_RIDER_UNDERAGE`. The training gate applies only to mountain sleds: if the chosen unit's `unit_class` is `MOUNTAIN`, the member's `training_level` must be `ADVANCED`, failing which the confirm is rejected with `ERR_TRAINING_REQUIRED`. The class gate requires the unit's `unit_class` rank to be at least the trail's `required_class` rank — the sled must be capable of the route — and a sled that ranks below the trail is rejected with `ERR_UNIT_CLASS_TOO_LOW`.

Two temporal double-booking gates then protect the shared inventory. The unit gate rejects the confirm with `ERR_UNIT_DOUBLE_BOOKED` if the chosen unit has any other reservation in `CONFIRMED` or `CHECKED_OUT` whose departure window, taken as the half-open interval from `starts_at` up to but not including `ends_at`, overlaps this departure's window. The gear gate rejects the confirm with `ERR_GEAR_DOUBLE_BOOKED` if either chosen gear item has any other reservation in `CONFIRMED` or `CHECKED_OUT` whose window overlaps this one — but gear is checked against a closed interval that runs from `starts_at` to `ends_at` inclusive, padded by a turnaround buffer of 60 minutes on each side to allow for cleaning and drying between riders. The wider, inclusive, buffered window for gear is intentional and differs from the narrower half-open window used for units.

When all gates pass, the system computes the estimated quote and writes it to `estimated_total_cents`. The quote is forward-looking and assumes a full-tank return, so it folds in no fuel, late, or damage charges. First the system determines the number of departure-days as the span from the departure's `starts_at` to its `ends_at`, rounded up to a whole number of days, with a floor of one day so that any departure costs at least a single day. The rental base is the unit's `daily_rate_cents` multiplied by that day count. The tour base is a flat fee keyed by the trail's `required_class`: 4000 cents for a `TRAIL`-class route, 6000 cents for a `UTILITY`-class route, and 9000 cents for a `MOUNTAIN`-class route. The gear surcharge is a flat 1525 cents for each assigned gear slot — that is, 1525 cents multiplied by the number of gear ids present on the reservation, so zero, one, or two slots. The gross is the sum of the rental base, the tour base, and the gear surcharge.

A membership discount then applies, but only when the member's benefits are active at the confirmation instant. Benefits are active exactly when the `membership_tier` is `SEASON` or `PREMIER` and, additionally, either `membership_expires_at` is null or `membership_expires_at` is strictly later than the logical clock now. When active, the discount percentage is 10 percent for a `SEASON` member and 20 percent for a `PREMIER` member; a `NONE` member, or any member whose benefits have lapsed, takes a zero discount. The rounding order here is pinned and order-sensitive: the discount is computed once against the combined gross — gross multiplied by the discount percentage, rounded half-up to whole cents a single time — and that one rounded discount is then subtracted from the gross. Discounting each line separately and rounding each before summing is incorrect and may differ by a cent. Because the estimate assumes a full tank, the estimated fuel component is zero, so the `estimated_total_cents` is simply the gross minus the rounded discount.

### 3.6. Capacity, Concurrency, and the Departure Lifecycle

The capacity gate at confirmation requires that the departure's `rider_count` be strictly less than its effective capacity — the smaller of `capacity_riders` and the trail's `max_riders` — before another rider may be added; a departure already at its effective cap rejects the confirm with `ERR_DEPARTURE_FULL`. The departure's `rider_count` itself is the count of that departure's reservations in `CONFIRMED`, `CHECKED_OUT`, or `RETURNED`; it is incremented when a reservation confirms and decremented when a confirmed reservation cancels or is marked a no-show.

After capacity comes the optimistic-concurrency check. As detailed in §2.6, the supplied `expected_tour_departure_version` must equal the departure's current `version`, or the confirm is rejected with `ERR_STALE_VERSION`. Because each successful confirm increments that `version`, a client holding a version captured before another rider confirmed will be turned away here, protecting it from booking against capacity it can no longer see.

Once a departure is locked, the tour itself proceeds. A `Guide` assigned to the departure departs it, moving it from `LOCKED` to `DEPARTED`. Departure is gated on the trail not being `CLOSED` (else `ERR_TRAIL_CLOSED`) and on the clock now having reached the departure's `starts_at`. Departing triggers a two-pronged cascade across the departure's reservations: every reservation still `CONFIRMED` is checked out — moved to `CHECKED_OUT`, its `checked_out_at` stamped with the clock now, its unit moved from `RESERVED` to `OUT`, and its assigned gear moved from `ASSIGNED` to `OUT` — while every reservation still `PENDING` at departure time is cancelled, releasing its unit, gear, and deposit. A `Guide` may also check out a single `CONFIRMED` reservation individually, moving it to `CHECKED_OUT` with the same unit, gear, and stamp side effects, provided the departure is `LOCKED` or `DEPARTED` and the clock now has reached `starts_at`.

A `Guide` completes a departure, moving it from `DEPARTED` to `COMPLETED`, only once every reservation that was checked out on it has been resolved — that is, each such reservation is either `RETURNED` or marked `NO_SHOW`. Completion releases the departure's staffing: every active `GuideAssignment` has its `active` flag set to false, the departure's `guide_count` is reset to zero, and each affected guide returns from `OFF_DUTY` to `AVAILABLE` if they hold no other active assignment.

A `DispatchOperator` may cancel a departure that is still `SCHEDULED` or `LOCKED`, moving it to the terminal `CANCELLED`. Cancellation cascades to its reservations: every reservation on it that is `PENDING` or `CONFIRMED` is moved to `CANCELLED`, its unit released from `RESERVED` back to `AVAILABLE`, its gear released from `ASSIGNED` back to `AVAILABLE`, and — if that reservation's `settlement_status` is `HELD` — the deposit is fully refunded by moving its billing state from `HELD` to `REFUNDED` and returning the entire `deposit_hold_cents`. The cancellation also zeroes the departure's `guide_count` and deactivates its guide assignments. This same departure-cancellation cascade is what fires when a trail closure tears down a scheduled or locked departure.

### 3.7. Trail Conditions and the Closure Cascade

A `DispatchOperator` changes a trail's condition by posting a closure carrying the `new_condition` to move to and a free-text `reason`. Every such posting records a `ClosureEvent` capturing the `trail_id`, the `new_condition`, the `reason`, and a `cancelled_departure_count`. Moving a trail among `OPEN` and `CAUTION` in either direction is purely advisory and cancels nothing: those transitions record a `ClosureEvent` whose `cancelled_departure_count` is zero, and the trail's `condition` is updated to the new value. Reopening a `CLOSED` trail back to `OPEN` likewise records a zero-count `ClosureEvent`.

Closing a trail — moving its `condition` to `CLOSED` from either `OPEN` or `CAUTION` — is the consequential case and is the top of the system's deepest cascade. When a trail closes, every departure on that trail whose status is `SCHEDULED` or `LOCKED` is cancelled: each such departure runs the full departure-cancellation cascade of §3.6, which in turn unwinds that departure's `PENDING` and `CONFIRMED` reservations, releasing their units and gear and refunding any `HELD` deposits. The number of departures cancelled this way is counted into the `ClosureEvent`'s `cancelled_departure_count`. A `CLOSED` condition gates the lock and depart transitions of a departure but does not by itself prevent new departures from being scheduled on the trail; it is the lock and depart operations that consult trail condition and reject with `ERR_TRAIL_CLOSED`.

### 3.8. The Deposit Hold and Membership Waiver

The deposit hold placed at confirmation is normally equal to the chosen unit's `deposit_cents`. There is one exception, the premier waiver: a member whose `membership_tier` is `PREMIER`, whose benefits are active at confirmation (by the same active test used for the discount in §3.5), and whose `lifetime_damage_strikes` count is exactly zero has the deposit waived to zero, carrying the deposit risk personally. Any member who is not premier, or whose benefits have lapsed, or who carries at least one damage strike, holds the full `deposit_cents`. The resulting amount is written to the reservation's `deposit_hold_cents` and folded into the member's recomputed total hold. The `lifetime_damage_strikes` count is the number of this member's settlements that recorded a positive damage charge, and it is what disqualifies a premier member from the deposit waiver after a single damaging trip.

### 3.9. Return, Settlement, No-Show, and Cancellation

A `DispatchOperator` returns a `CHECKED_OUT` reservation, which is the moment the financial picture is finalized. The return body must include a `fuel_return_fraction` — the fuel level at return as a fraction from 0 to 1 inclusive, where 1.0 is a full tank — and may include an operator-entered `damage_assessed_cents` (defaulting to zero) and a `lost_gear_ids` list flagging gear items that did not come back. A return missing a valid `fuel_return_fraction` in the range from 0 to 1 is rejected with `ERR_FUEL_FRACTION_REQUIRED`. On return the reservation moves from `CHECKED_OUT` to `RETURNED`, its `returned_at` is stamped with the clock now, its unit returns from `OUT` to `AVAILABLE`, and its gear returns from `OUT` to `AVAILABLE` — except any gear flagged in `lost_gear_ids`, which is permanently retired from `OUT` to `RETIRED`. A single `Settlement` is created for the reservation, the billing state advances from `HELD` to `SETTLED`, and — if the operator recorded a positive `damage_assessed_cents` — the member's `lifetime_damage_strikes` is incremented by one. At most one settlement may exist per reservation; a second return attempt against an already-settled reservation is rejected with `ERR_DUPLICATE`. The member's `deposit_hold_cents` is recomputed once the hold is consumed.

The settlement aggregates five charge lines against the held deposit. The `reservation_id` ties the settlement to its reservation. The `rental_charge_cents` line is carried over verbatim from the reservation's `estimated_total_cents`; it is not recomputed against actual return time, because lateness is billed separately. The `fuel_charge_cents` line bills a fuel shortfall: there is no charge when the returned fuel fraction is at or above the full-tank threshold of 0.95, so a shortfall is billed only when `fuel_return_fraction` is strictly below 0.95. When it is below, the shortfall in liters is the difference between 0.95 and the returned fraction, multiplied by the unit's `tank_capacity_liters`, and the charge is that liter shortfall multiplied by the fuel price of 180 cents per liter, rounded half-up to whole cents. The `late_charge_cents` line bills lateness measured from the departure's scheduled `ends_at` to the reservation's `returned_at`: the late minutes are that span in minutes, floored at zero. Lateness within the grace window of 30 minutes inclusive is free, so the charge is zero whenever the late minutes are 30 or fewer. Beyond grace, the billable minutes are the late minutes minus the 30-minute grace, the number of late blocks is those billable minutes divided by the 60-minute block length and rounded up so that any started block bills in full, and the late charge is that block count multiplied by 2500 cents per block.

The `damage_assessed_cents` line is the operator's entry. The `gear_loss_cents` line is the sum of the `replacement_cost_cents` of every gear item flagged lost at settlement. The total charges are the sum of the rental, fuel, late, damage, and gear-loss lines. These are settled against the deposit in a fixed waterfall bucket order — rental first, then fuel, then late, then damage, then gear loss — and the deposit consumed, `deposit_applied_cents`, is the smaller of the held `deposit_hold_cents` and the total charges. The amount returned to the member, `refund_cents`, is the held deposit minus the deposit applied. The amount charged beyond the deposit, `net_charge_cents`, is the total charges minus the held deposit, but never less than zero. All five charge lines and the three derived amounts are recorded on the `Settlement`.

A no-show takes a different settlement path. A `DispatchOperator` marks a `CONFIRMED` reservation as `NO_SHOW` when the departure is `LOCKED` or `DEPARTED` and the rider failed to appear. This releases the unit from `RESERVED` to `AVAILABLE` and the gear from `ASSIGNED` to `AVAILABLE`, and decrements the departure's `rider_count` by one. A `Settlement` is created in which the `rental_charge_cents` is a flat no-show fee of 5000 cents and the `fuel_charge_cents`, `late_charge_cents`, `damage_assessed_cents`, and `gear_loss_cents` lines are all zero. The no-show fee does not consume the deposit: the `deposit_applied_cents` is zero, the full held deposit is returned as `refund_cents`, and the `net_charge_cents` equals the 5000-cent fee. The billing state advances from `HELD` to `SETTLED`.

Cancellation lets a rider or dispatcher back out before the tour runs. A `PENDING` reservation may always be cancelled, which releases any held unit back to `AVAILABLE` and any assigned gear back to `AVAILABLE`. A `CONFIRMED` reservation may be cancelled only while its departure has not yet `DEPARTED`; cancelling a confirmed reservation releases its unit from `RESERVED` to `AVAILABLE`, releases its gear from `ASSIGNED` to `AVAILABLE`, decrements the departure's `rider_count` by one, moves its billing state from `HELD` to `REFUNDED` with the full `deposit_hold_cents` refunded, and recomputes the member's total hold. Attempting any of these transitions from a state in which it is not defined is rejected with `ERR_INVALID_STATE`. For the entity-backed `Member` role, the ownership gate of §2.1 applies before any of these business rules: a member may only confirm or cancel a reservation whose `member_id` matches their identity, and a guide may only depart or complete a departure they are assigned to lead, on pain of `ERR_OWNERSHIP_REQUIRED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource — registering a member, creating a guide, trail, unit, gear item, or departure, posting a closure event, assigning a guide, or creating a reservation — return `201 Created`. Operations that modify an existing resource, including the lifecycle and settlement transitions, the maintenance toggle, and all read operations, return `200 OK`. The clock-setting endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/members/register` | Self-register a new member | Anonymous |
| GET | `/members/{id}` | Fetch a member | Member, DispatchOperator, PlatformAdmin |
| POST | `/members/{id}/sign-waiver` | Sign the liability waiver | Member |
| POST | `/members/{id}/expire-waiver` | Re-evaluate and possibly expire a waiver | DispatchOperator, PlatformAdmin |
| POST | `/members/{id}/complete-training` | Advance training level | DispatchOperator |
| GET | `/members/{id}/reservations` | List a member's reservations | Member, DispatchOperator, PlatformAdmin |
| POST | `/guides` | Create a guide | DispatchOperator, PlatformAdmin |
| GET | `/guides/{id}` | Fetch a guide | Guide, DispatchOperator, PlatformAdmin |
| GET | `/guides/{id}/assignments` | List a guide's assignments | Guide, DispatchOperator, PlatformAdmin |
| POST | `/trails` | Create a trail | DispatchOperator, PlatformAdmin |
| GET | `/trails/{id}` | Fetch a trail | Member, Guide, DispatchOperator, PlatformAdmin |
| POST | `/trails/{id}/closure` | Change trail condition (cascades on CLOSED) | DispatchOperator |
| GET | `/trails/{id}/closures` | List a trail's closure events | DispatchOperator, PlatformAdmin |
| GET | `/trails/{id}/tour-departures` | List departures on a trail | Member, Guide, DispatchOperator, PlatformAdmin |
| POST | `/units` | Create a sled unit | DispatchOperator, PlatformAdmin |
| GET | `/units/{id}` | Fetch a unit | Member, DispatchOperator, PlatformAdmin |
| POST | `/units/{id}/maintenance` | Toggle unit maintenance | DispatchOperator |
| POST | `/gear-items` | Create a gear item | DispatchOperator, PlatformAdmin |
| GET | `/gear-items/{id}` | Fetch a gear item | DispatchOperator, PlatformAdmin |
| POST | `/tour-departures` | Schedule a departure | DispatchOperator |
| GET | `/tour-departures/{id}` | Fetch a departure | Member, Guide, DispatchOperator, PlatformAdmin |
| GET | `/tour-departures/{id}/reservations` | List a departure's reservations | Guide, DispatchOperator, PlatformAdmin |
| GET | `/tour-departures/{id}/guide-assignments` | List a departure's guide assignments | Guide, DispatchOperator, PlatformAdmin |
| POST | `/tour-departures/{id}/assign-guide` | Assign a guide to a departure | DispatchOperator |
| POST | `/tour-departures/{id}/unassign-guide` | Remove a guide from a departure | DispatchOperator |
| POST | `/tour-departures/{id}/lock` | Lock a departure | DispatchOperator |
| POST | `/tour-departures/{id}/depart` | Start the tour | Guide |
| POST | `/tour-departures/{id}/complete` | Complete the tour | Guide |
| POST | `/tour-departures/{id}/cancel` | Cancel a departure (cascades) | DispatchOperator |
| POST | `/reservations` | Create a pending reservation | Member, DispatchOperator |
| GET | `/reservations/{id}` | Fetch a reservation | Member, DispatchOperator, PlatformAdmin |
| GET | `/reservations` | List/filter reservations | DispatchOperator, PlatformAdmin |
| POST | `/reservations/{id}/confirm` | Confirm a reservation | Member, DispatchOperator |
| POST | `/reservations/{id}/check-out` | Check out a reservation | Guide, DispatchOperator |
| POST | `/reservations/{id}/return` | Return and settle a reservation | DispatchOperator |
| POST | `/reservations/{id}/no-show` | Mark a reservation a no-show | DispatchOperator |
| POST | `/reservations/{id}/cancel` | Cancel a reservation | Member, DispatchOperator |
| GET | `/settlements/{id}` | Fetch a settlement | Member, DispatchOperator, PlatformAdmin |
| GET | `/reservations/{id}/settlement` | Fetch a reservation's settlement | Member, DispatchOperator, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_REQUIRED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_DEPARTURE_NOT_OPEN` | 409 |
| `ERR_WAIVER_NOT_SIGNED` | 409 |
| `ERR_RIDER_UNDERAGE` | 409 |
| `ERR_TRAINING_REQUIRED` | 409 |
| `ERR_UNIT_CLASS_TOO_LOW` | 409 |
| `ERR_UNIT_DOUBLE_BOOKED` | 409 |
| `ERR_GEAR_DOUBLE_BOOKED` | 409 |
| `ERR_GUIDE_DOUBLE_BOOKED` | 409 |
| `ERR_GUIDE_CLASS_TOO_LOW` | 409 |
| `ERR_GUIDE_RATIO_UNMET` | 409 |
| `ERR_TRAIL_CLOSED` | 409 |
| `ERR_DEPARTURE_FULL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_DUPLICATE` | 409 |
| `ERR_GEAR_KIND_MISMATCH` | 422 |
| `ERR_FUEL_FRACTION_REQUIRED` | 422 |

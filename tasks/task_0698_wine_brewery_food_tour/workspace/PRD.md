# Wine Brewery Food Tour API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Wine, Brewery & Food Tour Operator API, the back-office and guest-facing platform that runs a tasting-tour business end to end. The operator publishes a catalogue of themed tours, schedules individual departures on a fleet of vans, assembles each departure's itinerary from a sequence of partner-venue stops, and sells seats to guests who must clear age and waiver checks before they ride. The platform must reconcile two competing pressures at once: a finite, contended seat pool on every van that bookings race to consume, and a layered pricing engine that discounts per-person fares by group size while still owing gratuity to staff and commission to the wineries, breweries, and restaurants that host each tasting.

Three forces make the domain unusually demanding. First, seats are a scarce resource: reservations must never oversell a van, and because several agents may be selling against the same departure, the platform relies on optimistic concurrency to reject reservations made against a stale view of remaining capacity. Second, the money is double-sided — guests are charged tiered fares plus gratuity and add-ons, while partner venues are owed commission that is estimated when a departure is confirmed and re-settled, on real attendance, when it completes. Third, real-world disruption — weather, mechanical failure, no-shows — forces cascading cancellations that must unwind bookings, refunds, and venue holds atomically. Every figure in the system is an integer count of cents, and a logical clock (not wall-clock time) governs every time-sensitive decision so the business can be tested deterministically.

The remainder of this document defines the global contracts that all endpoints share (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the canonical error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request that mutates state, and every read that is not part of the public catalogue, must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they act. When either header is missing on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The platform recognizes five roles, spelled exactly as follows: `Operator`, `Guide`, `PartnerVenue`, `Guest`, and `Anonymous`. An `Operator` is tour-operator staff who build the catalogue, schedule departures, manage stops and venue requests, cancel for weather or operational reasons, drive the logical clock, and run identity verification. A `Guide` is the on-the-day staffer who departs and completes the trip and checks guests in. A `PartnerVenue` is a winery, brewery, or restaurant acting on its own venue confirmations. A `Guest` registers, signs a waiver, books, pays, and cancels. `Anonymous` denotes an unauthenticated public reader, permitted only on the catalogue read endpoints whose authorized roles include `Anonymous`; any mutating call presented with no headers fails with `ERR_UNAUTHENTICATED`.

Two of these roles are tied to a persisted entity, and two are not. When `X-User-Role` is `PartnerVenue`, `X-User-ID` is the `id` of the acting `PartnerVenue`; ownership checks on any resource that references a `PartnerVenue` compare the resource's venue foreign key to `X-User-ID`. When `X-User-Role` is `Guest`, `X-User-ID` is the `id` of the acting `Guest`. By contrast, when `X-User-Role` is `Operator`, `Guide`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range of 1 through 100 inclusive, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every primary resource — tour products, add-ons, vehicles, partner venues, pickup points, departures, stops, venue confirmations, guests, and bookings — carries a system-managed set of fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that starts at its initial value on creation and increments by one on every mutation of the resource; it is the basis for the optimistic concurrency control described in Section 2.7.

Whenever a derived figure on a resource changes — for example a departure's `seats_taken` or `expected_headcount` shifting as bookings are reserved or released, or a stop's commission being recomputed — that change is a mutation that refreshes `updated_at` and increments the owning resource's `version`. All ten primary resources in this system carry the full complement of `id`, `created_at`, `updated_at`, and `version`.

### 2.5. The Logical Clock

The platform never reads wall-clock time for business decisions. Instead it maintains a single logical clock used for every time comparison — refund lead-time tiers, the earliest moment a departure may depart, and the earliest moment it may complete. On server startup the logical clock reads exactly `2026-03-01T00:00:00Z` and stays at that value until it is explicitly moved; before any set call it never falls back to wall-clock time. An administrative test-driving capability lets an `Operator` move the clock forward or backward to a supplied instant, provided as the `to_iso8601` field in the request body. All hours-before-departure arithmetic and all "not before" temporal guards evaluate against the clock's current reading.

### 2.6. Monetary Values, Precision, and Rounding

Every monetary field in the system — list prices, add-on charges, charter fees, tasting costs, subtotals, gratuity, totals, amounts paid, refunds, and commissions — is stored and returned as an integer count of cents. Wherever a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Where a calculation pins an evaluation order (for example, rounding a per-person fare before multiplying by the party size), that order is part of the contract and is described with the relevant workflow in Section 3; implementers must not reorder rounding and multiplication, because doing so changes the cent-level result.

### 2.7. Optimistic Concurrency Control on Seat Reservation

The seat pool of a departure is a shared, finite resource that several sellers may consume against at once, so reserving seats is guarded by optimistic concurrency on the departure. A request to reserve a draft booking's seats must carry `expected_departure_version`, a non-optional field whose value is the `version` of the target departure that the client last observed. The server compares `expected_departure_version` against the departure's current `version`. If another writer has reserved or released seats since the client read the departure — thereby advancing the departure's `version` — the client's view of remaining capacity is stale, and the reservation is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a seller from committing seats against a capacity figure it never actually observed. The seat-reservation endpoint is the only write in the system that takes a version field; no other endpoint accepts or requires one.

### 2.8. Cascades, Hierarchical Consistency, and Atomicity

Several operations mutate more than one resource in a single atomic request, and the platform guarantees that all of a cascade's effects land together or not at all. When a departure is cancelled, its bookings, their refunds and payment states, and its venue confirmations are all resolved within the same request; when a booking is reserved or released, the parent departure's seat counters and `version` move in lockstep with the booking's own transition. The specific cascade chains — which bookings are touched, how refunds are computed on each path, and which venue confirmations are released — are detailed in Section 3 alongside the workflows that trigger them. In every cascade, each resource that is mutated has its `updated_at` refreshed and its `version` incremented independently.

### 2.9. Resource Lookup and Validation Ordering

When a request names a resource by an identifier in its URL path, that resource's existence is checked first; if it does not exist, the request is rejected with `ERR_NOT_FOUND`. When a request body carries foreign keys — for example `departure_id`, `lead_guest_id`, `pickup_point_id`, `add_on_id`, `vehicle_id`, `tour_product_id`, `partner_venue_id`, or `stop_id` — each referenced resource must exist, and a dangling reference is rejected with `ERR_FK_NOT_FOUND`.

The platform evaluates request validity in a fixed precedence so that the same failing request always yields the same error. Authentication is checked first: a missing header pair yields `ERR_UNAUTHENTICATED`. Role authorization is next: a role not permitted for the operation yields `ERR_FORBIDDEN_ROLE`. Then path-id existence is confirmed (`ERR_NOT_FOUND`), followed by body foreign-key existence (`ERR_FK_NOT_FOUND`). Next the body is checked for being well-formed with required fields of the correct type (`ERR_INVALID_REQUEST`), then enum fields are checked against their declared value sets (`ERR_INVALID_ENUM`), then numeric fields are checked against their permitted ranges (`ERR_VALUE_OUT_OF_RANGE`). Only after all of these structural checks pass does the platform evaluate state-machine and business rules. This ordering means, for instance, that a malformed body on a non-existent resource surfaces as `ERR_NOT_FOUND` (the earlier check) rather than `ERR_INVALID_REQUEST`.

### 2.10. Enumerations

The following enumerated value sets are fixed and must be stored and returned exactly as written. A `theme` on a tour product is one of `WINE`, `BREWERY`, `FOOD`, or `MIXED`. A partner venue's `kind` is one of `WINERY`, `BREWERY`, or `RESTAURANT`. A tour product's `status` is `DRAFT`, `PUBLISHED`, or `RETIRED`. An add-on's `status` is `ACTIVE`. A vehicle's `status` is `AVAILABLE` or `OUT_OF_SERVICE`. A partner venue's `status` is `ACTIVE` or `SUSPENDED`. A pickup point's `status` is `ACTIVE`. A departure's `status` is `SCHEDULED`, `CONFIRMED`, `DEPARTED`, `COMPLETED`, `CANCELLED_WEATHER`, or `CANCELLED_OPS`. A stop's `status` is `PLANNED` or `VISITED`. A venue confirmation's `status` is `REQUESTED`, `CONFIRMED`, `CHANGES_REQUESTED`, `DECLINED`, or `RELEASED`. A booking's lifecycle `status` is `DRAFT`, `RESERVED`, `PAID`, `CHECKED_IN`, `COMPLETED`, or `CANCELLED`, and its independent `payment_status` is `UNPAID`, `CAPTURED`, or `REFUNDED`. Whenever an enum input field is submitted with a value outside its declared set, the request is rejected with `ERR_INVALID_ENUM`; status fields are set only by the system and are never accepted as client input on creation.

## 3. Business Logic & Workflows

### 3.1. Building the Catalogue: Tour Products and Add-Ons

The catalogue is the operator's responsibility. An `Operator` creates a **tour product** by supplying a `name` (its catalogue name, such as "Napa Cellar Crawl"), a `theme`, and a `base_price_per_person_cents` — the list fare per guest before any group discount, which must be greater than zero. Three further inputs are optional. The `gratuity_pct` is the default gratuity rate applied to seats and add-ons; it defaults to 0.18 and must lie between 0.0 and 0.30 inclusive. The `charter_fee_cents` is a flat surcharge added once when a departure of this product is run as a private charter; it defaults to 0 and may not be negative. The `min_guest_age` is the minimum guest age for booking and defaults to 21, the common floor for tasting tours. A newly created product begins in `DRAFT`.

A product moves through a short lifecycle. Publishing a `DRAFT` product advances its `status` to `PUBLISHED`; this requires only that the product currently be in `DRAFT`, and it increments the product's `version`. Retiring a `PUBLISHED` product advances it to `RETIRED`, but only if no departure of this product is currently in `SCHEDULED`, `CONFIRMED`, or `DEPARTED` status; if any such live departure exists, the retire is rejected with `ERR_PRODUCT_HAS_ACTIVE_DEPARTURES`. A successful retire increments the product's `version`. `RETIRED` is terminal.

Add-ons enrich a product. An `Operator` creates an **add-on** by naming the `tour_product_id` it is offered on, a `name` (for instance "Cheese Pairing Flight"), and a `price_per_person_cents` — the per-guest charge, which may not be negative and is never discounted. An add-on is created directly in `ACTIVE` status. A single add-on may optionally be attached to a booking and then applies to every guest in that party.

### 3.2. Fleet, Pickup Points, and Partner Venues

Vans, collection points, and tasting partners are the supporting cast that departures draw on. An `Operator` registers a **vehicle** with a `label` (its plate or fleet label) and a `seat_capacity`, which must be greater than zero; the vehicle is created `AVAILABLE`. The operator may later set a vehicle's status to `AVAILABLE` or `OUT_OF_SERVICE`, a mutation that increments the vehicle's `version`. A vehicle's seat capacity is significant because it becomes the fixed size of a departure's seat pool at scheduling time.

A **pickup point** is registered with a `name` (such as "Downtown Transit Hub") and an `address`, and is created `ACTIVE`. Every booking names the pickup point where its party is collected.

A **partner venue** is a winery, brewery, or restaurant that hosts a tasting. An `Operator` creates one with a `name`, a `kind`, a `commission_pct` (the share of tasting revenue the operator owes the venue, which must lie between 0.0 and 0.50 inclusive), and a `tasting_cost_per_guest_cents` (the per-guest tasting cost at the venue, which may not be negative). A partner venue is created `ACTIVE` and may later be set to `ACTIVE` or `SUSPENDED`, a status change that increments the venue's `version`. Both `commission_pct` and `tasting_cost_per_guest_cents` feed the commission arithmetic described in Section 3.7.

### 3.3. Scheduling a Departure and Its Itinerary

A **departure** is a single run of a product on a particular van at a particular time. An `Operator` schedules one by supplying the `tour_product_id` it runs, the `vehicle_id` of the assigned van, a `depart_at` instant and a `return_at` instant (both ISO 8601 UTC, with `return_at` required to be strictly later than `depart_at`), and an optional `is_private_charter` flag that defaults to false. A private charter means the whole van is sold to a single booking. On creation the departure enters `SCHEDULED`; its `seat_capacity` is copied from the assigned vehicle's seat capacity and becomes the fixed seat pool; `seats_taken` starts at 0; and `expected_headcount` starts at 0. Throughout its life the departure reports `seats_taken` as the sum of `party_size` over its bookings in `RESERVED`, `PAID`, or `CHECKED_IN`, and `expected_headcount` as the forward-looking sum of `party_size` over its bookings in `RESERVED` or `PAID`. A free-text `cancel_reason` is recorded only if and when the departure is cancelled.

An itinerary is built from **stops**. An `Operator` adds a stop to a `SCHEDULED` departure by naming its `departure_id`, the `partner_venue_id` of the venue visited, a `sequence` (a one-based ordering position within that departure's itinerary), and a `dwell_minutes` value (the planned minutes at the stop, which must be greater than zero). The `sequence` must be unique within its departure; an attempt to reuse a sequence number already present on that departure is rejected with `ERR_DUPLICATE_STOP_SEQUENCE`. A new stop is created in `PLANNED` status with both its `estimated_commission_cents` and `settled_commission_cents` initialized to 0; these two figures remain 0 until the departure is confirmed and completed respectively, as described in Section 3.7. A stop moves from `PLANNED` to `VISITED` when its departure completes.

### 3.4. Venue Sign-Off: The Confirmation Loop

Before a departure may run, each of its stops must be signed off by the host venue. An `Operator` opens a **venue confirmation** against a stop by naming the `stop_id` and a `requested_headcount` — the headcount the operator asks the venue to hold. On creation the confirmation enters `REQUESTED`, its `revision_count` is initialized to 0, and its `partner_venue_id` is copied from the stop's venue so that ownership of the confirmation can be checked. A `decline_note` is recorded only when the venue pushes back.

From `REQUESTED`, the host venue has three moves, each permitted only to the `PartnerVenue` whose `id` matches the confirmation's `partner_venue_id`; an attempt by any other principal is rejected with `ERR_NOT_RESOURCE_OWNER`. The venue may confirm, advancing the confirmation `REQUESTED → CONFIRMED`; the underlying stop stays `PLANNED` but is now venue-confirmed, which is what makes its departure eligible to be confirmed. The venue may request changes, advancing `REQUESTED → CHANGES_REQUESTED` and recording the supplied `decline_note`. Or the venue may decline, advancing `REQUESTED → DECLINED` and recording the supplied `decline_note`. Each of these three transitions increments the confirmation's `version`.

When a confirmation sits in `CHANGES_REQUESTED`, the loop can cycle. The `Operator` resubmits it with a revised `requested_headcount`, advancing `CHANGES_REQUESTED → REQUESTED`, updating the held headcount from the body, and incrementing `revision_count` by one as a cycle counter. A resubmit is permitted only while the confirmation's `revision_count` is less than 3; once three revisions have been spent, a further resubmit is rejected with `ERR_REVISION_LIMIT_REACHED`. The venue may also decline directly from `CHANGES_REQUESTED`, advancing `CHANGES_REQUESTED → DECLINED`. Every resubmit and every decline-from-changes increments the confirmation's `version`. `DECLINED` and `RELEASED` are both terminal; a confirmation reaches `RELEASED` only as a system side effect when its departure is cancelled (Section 3.8).

### 3.5. Registering Guests and Clearing Them to Ride

Anyone permitted to register a guest does so by supplying a `full_name` and a `birth_date` (an ISO 8601 date used for age verification). A new guest starts with `age_verified` false and `waiver_signed` false. Two events clear a guest. A synthetic identity-and-OCR verification event marks a guest's `age_verified` true and increments the guest's `version`; in this benchmark no real document is uploaded, and the event simply names the `guest_id` to clear. Separately, signing the liability waiver sets the guest's `waiver_signed` true and increments the guest's `version`. These two flags gate payment and check-in, as described in Section 3.6.

### 3.6. The Booking Lifecycle and the Seat Pool

A **booking** is a guest's claim on seats. A booking is created by naming the `departure_id` being booked, the `lead_guest_id` (the lead and paying guest), the `pickup_point_id` where the party is collected, a `party_size` (the number of seats requested, which must be greater than zero), and optionally a single `add_on_id` applied to every guest in the party. On creation the booking enters `DRAFT` with `payment_status` of `UNPAID`, and its price is quoted immediately: `subtotal_cents`, `gratuity_cents`, and `total_cents` are computed as described in Section 3.7, while `amount_paid_cents` and `refund_cents` both start at 0.

**Reserving seats.** A booking advances `DRAFT → RESERVED` when its seats are reserved, which is the moment the booking consumes the departure's seat pool. Several preconditions guard this step, and the price quote is recomputed at this point. The departure must be in `SCHEDULED`; reserving against a departure in any other state is rejected with `ERR_DEPARTURE_NOT_BOOKABLE`. The lead guest must satisfy the product's `min_guest_age`: the guest's age, computed from `birth_date` against the logical clock at reserve time, must be at least `min_guest_age`, and an underage lead guest is rejected with `ERR_UNDERAGE_GUEST`. The departure must have room: the sum of its current `seats_taken` plus this booking's `party_size` must not exceed the departure's `seat_capacity`, and a reservation that would overflow the pool is rejected with `ERR_SEAT_CAPACITY_EXCEEDED`. If the departure is a private charter, the booking must take the whole van — its `party_size` must equal the departure's `seat_capacity` — and it must be the only non-terminal booking on that departure; a charter booking that does not take every seat, or that is not the sole booking, is rejected with `ERR_CHARTER_WHOLE_VAN_REQUIRED`. The reserve request must also carry `expected_departure_version` matching the departure's current `version`, failing which it is rejected per Section 2.7. When all preconditions hold, the reservation adds `party_size` to the departure's `seats_taken` and adds the same amount to its `expected_headcount`, increments the departure's `version`, and increments the booking's `version`.

These reserve-time checks are evaluated in a definite order so that the reported error is deterministic. The platform first confirms the departure is in `SCHEDULED` (`ERR_DEPARTURE_NOT_BOOKABLE`); then verifies the lead guest meets the minimum age (`ERR_UNDERAGE_GUEST`); then, for a private charter, that the whole-van rule holds (`ERR_CHARTER_WHOLE_VAN_REQUIRED`); then that the seat pool has room (`ERR_SEAT_CAPACITY_EXCEEDED`); and finally that the supplied departure version is current (`ERR_STALE_VERSION`). This ordering ensures, for example, that a reservation against a non-`SCHEDULED` departure surfaces as `ERR_DEPARTURE_NOT_BOOKABLE` rather than as a capacity or version error.

**Paying.** A `RESERVED` booking advances `RESERVED → PAID` when payment is captured. Payment requires that the booking's `payment_status` be `UNPAID`, and it requires that the lead guest be fully cleared — both `age_verified` and `waiver_signed` must be true — failing which the payment is rejected with `ERR_GUEST_NOT_CLEARED`. Capturing payment sets the `payment_status` to `CAPTURED`, sets `amount_paid_cents` equal to `total_cents`, and increments the booking's `version`.

**Checking in.** A `PAID` booking advances `PAID → CHECKED_IN` when the `Guide` checks the party in on the day. Check-in requires that the departure be in `DEPARTED`; checking in against a departure in any other state is rejected with `ERR_INVALID_STATE`. It also requires the lead guest's `age_verified` to be true, failing which it is rejected with `ERR_GUEST_NOT_CLEARED`. A successful check-in increments the booking's `version`.

**Completion.** A `CHECKED_IN` booking advances to `COMPLETED` automatically when its departure completes (Section 3.8); this system transition increments the booking's `version`. `COMPLETED` and `CANCELLED` are the two terminal booking states.

**Cancelling.** A booking may be cancelled from `DRAFT`, `RESERVED`, or `PAID`, always advancing it to `CANCELLED` and incrementing its `version`. Cancelling a `DRAFT` booking has no seat or money effect, since the booking never consumed the pool. Cancelling a `RESERVED` booking returns its seats: the departure's `seats_taken` and `expected_headcount` are each reduced by the booking's `party_size`, and the departure's `version` is incremented. Cancelling a `PAID` booking does the same seat restoration and additionally computes a refund: `refund_cents` is set by the lead-time refund rule of Section 3.7 over the booking's `amount_paid_cents`, measured against the departure's `depart_at`; if that refund is greater than 0 and the `payment_status` is `CAPTURED`, the `payment_status` advances to `REFUNDED`. Cancelling a `PAID` booking therefore increments both the departure's `version` (seats released) and the booking's `version`.

### 3.7. Pricing, Gratuity, Refunds, and Commission

Four calculations govern the money in this system. All of them work in integer cents and round half up.

**The price quote.** When a booking is created, and again when its seats are reserved, the platform quotes its price from a single booking together with its departure, the departure's tour product, and the optional add-on; there is no cross-booking aggregation. First a group-size discount is selected on the per-person base fare only — neither add-ons nor the charter fee are ever discounted. The discount tier is chosen by `party_size` against descending thresholds: a party of at least 12 takes 15 percent off, a party of at least 8 but fewer than 12 takes 10 percent off, a party of at least 4 but fewer than 8 takes 5 percent off, and a party of fewer than 4 takes no discount. The discounted per-person fare is computed by multiplying `base_price_per_person_cents` by one minus the selected tier rate and rounding that per-person figure half up to whole cents first; the seats total is then that rounded per-person fare multiplied by `party_size`. This round-then-multiply order is part of the contract and must not be reversed. The add-on total is the add-on's `price_per_person_cents` multiplied by `party_size` when an add-on is attached, and 0 otherwise. The charter component is the tour product's `charter_fee_cents` when the departure is a private charter, and 0 otherwise. The booking's `subtotal_cents` is the sum of the seats total, the add-on total, and the charter component.

**Gratuity.** Gratuity is computed on a base that deliberately excludes the charter fee. After the subtotal is known, the gratuity base is the seats total plus the add-on total — the charter component is not part of it. The booking's `gratuity_cents` is that gratuity base multiplied by the tour product's `gratuity_pct`, rounded half up to whole cents. The booking's `total_cents` is then `subtotal_cents` plus `gratuity_cents`; this fixed evaluation order — subtotal first, then the gratuity base, then gratuity, then total — makes the total well defined even though gratuity and total appear mutually dependent at first glance. The product's `gratuity_pct` itself can never exceed 0.30, the ceiling enforced when the product is created.

**Partner commission.** Each stop owes its host venue a commission on tasting revenue, computed per stop as the headcount multiplied by the venue's `tasting_cost_per_guest_cents` multiplied by the venue's `commission_pct`, rounded half up to whole cents. The same stop yields two different commission figures depending on which headcount feeds the formula. The **estimated** variant runs when a departure is confirmed (`SCHEDULED → CONFIRMED`): its headcount is the forward-looking sum of `party_size` over the departure's bookings in `RESERVED` or `PAID`, and it is written to each stop's `estimated_commission_cents`. The **settled** variant runs when a departure completes (`DEPARTED → COMPLETED`): its headcount is the sum of `party_size` over only the departure's `CHECKED_IN` bookings — actual attendance, with no-shows excluded — and it is written to each stop's `settled_commission_cents`. Because no-shows drop out of the settled headcount, the settled commission is always less than or equal to the estimated commission for the same stop.

**Cancellation refund.** When a refund is due — on cancelling a `PAID` booking, on the cascade of an operationally cancelled departure, or on the no-show auto-cancel that happens at depart — the refund percentage is chosen by lead time, measured as the number of hours between the logical clock's current reading and the departure's `depart_at`. If the cancellation is on a weather path, the refund percentage is 100 percent regardless of lead time. Otherwise, if the lead time is at least 168 hours (seven days), the refund is 100 percent; if it is at least 48 hours but less than 168 hours, the refund is 50 percent; and if it is less than 48 hours, the refund is 0 percent. These boundaries are inclusive on the lower edge — exactly 48 hours out yields 50 percent, while 47 hours out yields 0 percent. The refund amount is the booking's `amount_paid_cents` multiplied by the selected percentage, rounded half up to whole cents, and recorded as `refund_cents`.

### 3.8. Running a Departure: Confirm, Depart, Complete, and Cancel

A departure moves through an operational arc, and several of its transitions fan out into cascades.

**Confirming.** An `Operator` confirms a `SCHEDULED` departure, advancing it `SCHEDULED → CONFIRMED`. Three preconditions are checked. Every stop of the departure must have a venue confirmation in `CONFIRMED` status, failing which the confirm is rejected with `ERR_VENUE_NOT_CONFIRMED`. The assigned vehicle must be `AVAILABLE`, failing which the confirm is rejected with `ERR_VEHICLE_UNAVAILABLE`. And the departure must have at least one expected guest — its `expected_headcount` must be at least 1, meaning at least one booking is `RESERVED` or `PAID` — failing which the confirm is rejected with `ERR_NO_BOOKINGS`. On success, each stop's `estimated_commission_cents` is recomputed using the estimated commission variant over the expected headcount, and the departure's `version` is incremented.

**Departing.** A `Guide` departs a `CONFIRMED` departure, advancing it `CONFIRMED → DEPARTED`, but only once the logical clock has reached or passed `depart_at`; an attempt before then is rejected with `ERR_TOO_EARLY_TO_DEPART`. Departing triggers a no-show cleanup: every booking still in `RESERVED` whose `payment_status` is not `CAPTURED` is automatically cancelled and its seats released, and for each such auto-cancelled booking a `refund_cents` is computed by the lead-time refund rule (which, inside 48 hours, yields 0 percent). The departure's `version` is incremented.

**Completing.** A `Guide` completes a `DEPARTED` departure, advancing it `DEPARTED → COMPLETED`, but only once the logical clock has reached or passed `return_at`; an attempt before then is rejected with `ERR_TOO_EARLY_TO_COMPLETE`. Completion recomputes each stop's `settled_commission_cents` using the settled commission variant over the `CHECKED_IN` headcount, moves each stop from `PLANNED` to `VISITED`, advances every `CHECKED_IN` booking to `COMPLETED`, and increments the departure's `version`. `COMPLETED`, `CANCELLED_WEATHER`, and `CANCELLED_OPS` are the three terminal departure states.

**Cancelling for weather.** An `Operator` may cancel a departure for weather from either `SCHEDULED` or `CONFIRMED`, advancing it to `CANCELLED_WEATHER` and recording the supplied `cancel_reason`. This is the weather-override path: every non-terminal booking is moved to `CANCELLED` with `refund_cents` set to 100 percent of its `amount_paid_cents`, and each such booking whose `payment_status` was `CAPTURED` advances to `REFUNDED`. In the same atomic request, every stop's `CONFIRMED` venue confirmation is moved to `RELEASED`. The departure's `version` is incremented.

**Cancelling for operations.** An `Operator` may likewise cancel a departure for operational reasons from either `SCHEDULED` or `CONFIRMED`, advancing it to `CANCELLED_OPS` and recording the supplied `cancel_reason`. This path differs from the weather path in one respect: refunds are not a flat 100 percent but follow the lead-time refund rule against `depart_at`. Every non-terminal booking is moved to `CANCELLED` with `refund_cents` computed by that tiered rule; each cancelled booking whose refund is greater than 0 and whose `payment_status` was `CAPTURED` advances to `REFUNDED`. As on the weather path, every stop's `CONFIRMED` venue confirmation is moved to `RELEASED`, and the departure's `version` is incremented.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state-transition actions and the test-driving capabilities — return a `200 OK` status code. The seat-reservation action returns `200 OK` even though it advances a booking, because it modifies an existing draft booking rather than creating a new resource.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | Operator |
| POST | `/_verify/age` | Mark a guest age-verified (synthetic ID/OCR event) | Operator, Guide |
| POST | `/tour-products` | Create a tour catalogue product (DRAFT) | Operator |
| GET | `/tour-products` | List tour products (paginated) | Operator, Guide, PartnerVenue, Guest, Anonymous |
| GET | `/tour-products/{id}` | Get a tour product | Operator, Guide, PartnerVenue, Guest, Anonymous |
| POST | `/tour-products/{id}/publish` | Publish a DRAFT product | Operator |
| POST | `/tour-products/{id}/retire` | Retire a PUBLISHED product | Operator |
| POST | `/add-ons` | Create an add-on for a tour product | Operator |
| GET | `/add-ons` | List add-ons; filter by tour product | Operator, Guest, Anonymous |
| GET | `/add-ons/{id}` | Get an add-on | Operator, Guest, Anonymous |
| POST | `/vehicles` | Register a van | Operator |
| GET | `/vehicles/{id}` | Get a vehicle | Operator, Guide |
| POST | `/vehicles/{id}/set-status` | Set a vehicle AVAILABLE or OUT_OF_SERVICE | Operator |
| POST | `/partner-venues` | Create a partner venue | Operator |
| GET | `/partner-venues/{id}` | Get a partner venue | Operator, PartnerVenue, Anonymous |
| POST | `/partner-venues/{id}/set-status` | Set a partner venue ACTIVE or SUSPENDED | Operator |
| POST | `/pickup-points` | Create a pickup point | Operator |
| GET | `/pickup-points/{id}` | Get a pickup point | Operator, Guest, Anonymous |
| POST | `/guests` | Register a guest | Operator, Guest |
| GET | `/guests/{id}` | Get a guest | Operator, Guide, Guest |
| POST | `/guests/{id}/sign-waiver` | Sign the liability waiver for a guest | Operator, Guest |
| POST | `/departures` | Schedule a departure for a product on a van | Operator |
| GET | `/departures` | List departures; filter by product, vehicle, or status | Operator, Guide, Guest, Anonymous |
| GET | `/departures/{id}` | Get a departure | Operator, Guide, Guest, Anonymous |
| POST | `/departures/{id}/confirm` | Confirm a SCHEDULED departure | Operator |
| POST | `/departures/{id}/depart` | Mark a CONFIRMED departure DEPARTED | Guide |
| POST | `/departures/{id}/complete` | Mark a DEPARTED departure COMPLETED | Guide |
| POST | `/departures/{id}/cancel-weather` | Cancel a departure for weather (full refunds) | Operator |
| POST | `/departures/{id}/cancel-ops` | Cancel a departure for operational reasons (tiered refunds) | Operator |
| POST | `/stops` | Add an itinerary stop to a SCHEDULED departure | Operator |
| GET | `/stops` | List stops; filter by departure or partner venue | Operator, Guide, PartnerVenue, Anonymous |
| GET | `/stops/{id}` | Get a stop | Operator, Guide, PartnerVenue, Anonymous |
| POST | `/venue-confirmations` | Request a partner venue to confirm a stop's hold | Operator |
| GET | `/venue-confirmations` | List venue confirmations; filter by stop or partner venue | Operator, PartnerVenue |
| GET | `/venue-confirmations/{id}` | Get a venue confirmation | Operator, PartnerVenue |
| POST | `/venue-confirmations/{id}/confirm` | Venue confirms the stop | PartnerVenue |
| POST | `/venue-confirmations/{id}/request-changes` | Venue asks for changes (cycle back) | PartnerVenue |
| POST | `/venue-confirmations/{id}/resubmit` | Operator resubmits an updated request | Operator |
| POST | `/venue-confirmations/{id}/decline` | Venue declines the stop | PartnerVenue |
| POST | `/bookings` | Create a DRAFT booking; quote computed immediately | Operator, Guest |
| GET | `/bookings` | List bookings; filter by departure, guest, pickup, or add-on | Operator, Guide, Guest |
| GET | `/bookings/{id}` | Get a booking | Operator, Guide, Guest |
| POST | `/bookings/{id}/reserve` | Reserve seats (consumes the seat pool; OCC on departure version) | Operator, Guest |
| POST | `/bookings/{id}/pay` | Capture payment for a RESERVED booking | Operator, Guest |
| POST | `/bookings/{id}/check-in` | Check a PAID booking in on a DEPARTED departure | Guide |
| POST | `/bookings/{id}/cancel` | Cancel a booking (refund + seat release per state) | Operator, Guest |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_VALUE_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_STOP_SEQUENCE` | 409 Conflict |
| `ERR_UNDERAGE_GUEST` | 422 Unprocessable Entity |
| `ERR_GUEST_NOT_CLEARED` | 409 Conflict |
| `ERR_TOO_EARLY_TO_DEPART` | 409 Conflict |
| `ERR_TOO_EARLY_TO_COMPLETE` | 409 Conflict |
| `ERR_VENUE_NOT_CONFIRMED` | 409 Conflict |
| `ERR_VEHICLE_UNAVAILABLE` | 409 Conflict |
| `ERR_NO_BOOKINGS` | 409 Conflict |
| `ERR_CHARTER_WHOLE_VAN_REQUIRED` | 409 Conflict |
| `ERR_DEPARTURE_NOT_BOOKABLE` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_PRODUCT_HAS_ACTIVE_DEPARTURES` | 409 Conflict |
| `ERR_SEAT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

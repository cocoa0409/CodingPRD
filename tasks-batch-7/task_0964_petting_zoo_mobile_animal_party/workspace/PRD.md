# Petting-Zoo & Mobile-Animal Party API — Product Requirements Document

## 1. Introduction

Running a mobile petting-zoo business is an exercise in regulated logistics. Animals must be healthy, rested, and certified; venues must be inspected for water access, surface safety, and capacity; many jurisdictions demand exhibition permits filed weeks in advance; health codes mandate handwash stations; guardians must sign liability waivers for every child; and the whole operation is hostage to the weather forecast. Today these checks live in spreadsheets, phone calls, and a coordinator's memory — a system that fails quietly until a health inspector or an insurance adjuster asks questions.

This document specifies an operations API for such a business, mounted under `/petting-zoo`. It covers the full commercial lifecycle: customers register venues and liability insurance, coordinators build bookings from a roster of animals and a pool of certified handlers, permits move through a segregated submission-and-decision pipeline, quotes are priced provisionally and then re-priced at invoice time from what actually happened on site, and every dollar that moves — payments, refunds, forfeits, penalties, and final charges — is recorded in an immutable booking ledger. Temporal rules (lead times, rest windows, forecast freshness) are evaluated against a controllable logical clock so the platform's behavior is deterministic and testable. The audience is the engineering team building this service; every behavioral rule below is normative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the endpoint — or that violates entity-backed ownership — is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles exist, spelled exactly as follows:

- **Anonymous** — an unauthenticated caller. `X-User-ID` is an opaque identifier not tied to any persisted entity; the server does not compare it to any resource's `id`. Anonymous callers may do exactly one thing: register as a customer.
- **Customer** — the booking owner. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` (venues, bookings, insurance certificates, and their children) compare the resource's foreign-key field to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`. A customer manages its own venues, insurance certificates, bookings, payments, waiver signatures, and add-on requests, and may read its own resources.
- **Coordinator** — operations staff. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id` on a `Permit` at submit time) but does not compare it to any entity's `id`. Coordinators quote bookings, manage rosters and staffing, decide add-on requests, file and submit permits, record weather assessments, place and release weather holds, and drive the event-day transitions.
- **Veterinarian** — files animal health records and drives the quarantine cycle. `X-User-ID` is an opaque identifier, recorded nowhere and compared to nothing.
- **ComplianceOfficer** — the regulatory reviewer. `X-User-ID` is an opaque operator identifier; the server records it as `decided_by_user_id` on decided permits but never compares it to an entity `id`. A compliance officer decides permits and verifies insurance certificates — and, by segregation of duties, may not decide a permit submitted under the same operator id.
- **Operator** — the platform operator. `X-User-ID` is an opaque identifier. Operators manage the animal roster, the handler roster, retirements, and the logical clock.

One authorization rule deserves emphasis because it is enforced at the role layer, before any business logic: cancellation reasons are role-bound. A `Customer` actor may cancel only with `reason` `CUSTOMER`; a `Coordinator` actor may cancel only with `reason` `WEATHER` or `COMPLIANCE`. Any other pairing is rejected with `ERR_FORBIDDEN`.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can always tell whether additional pages exist.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id`, a server-minted UUID with no type prefix. Resources also carry `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set once at creation. Most entities additionally carry `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation — and `version`, an integer that starts at 1 and increments by exactly 1 on every mutation of that resource.

Three entities are deliberately lighter because they are immutable records: `HealthRecord`, `WeatherAssessment`, and `LedgerEntry` carry only `id` and `created_at`. Both `updated_at` and `version` are absent from them — they are written once and never modified.

Booking mutations deserve a note: whenever the rules below say a booking's version increments, `updated_at` refreshes in the same write. Child-entity changes that invalidate a booking's quote (roster changes, add-on attachment or approval, rescheduling) always increment the parent booking's `version` as part of their side effects, and those increments are what the optimistic-concurrency rules in §2.6 observe.

### 2.5. Money, Precision, and Rounding

All monetary values are integer cents in fields suffixed `_cents` — fees, subtotals, discounts, surcharges, deposits, payments, refunds, penalties. No fractional cents ever persist. Wherever a computation produces a fraction, the result is rounded half up at that pinned rounding point: a value whose fractional part is exactly one half rounds away from zero, never toward it. Different calculations pin their rounding points differently (per line, per step, or only after a multiplier), and those pinning decisions are part of the business rules in §3 — computing the same quantity in a different order and rounding once at the end is forbidden when the rule says otherwise. Non-monetary computed scores (the compliance score) are integers, and durations and counts are integer minutes or whole units.

### 2.6. Optimistic Concurrency Control on Bookings

Two write endpoints take a mandatory optimistic-concurrency field, `expected_booking_version`, carrying the `version` of the parent `Booking` as the client last observed it:

- **Rescheduling a booking.** The request must carry `expected_booking_version` equal to the booking's current `version`. If another writer has advanced the booking's version since the client last read it — by rescheduling, re-quoting, or any other mutation — the client's schedule view is stale, and the reschedule is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412).
- **Attaching an add-on request to a booking.** Attaching an add-on supersedes the booking's current quote, so the request must likewise carry `expected_booking_version` matching the booking's current `version`. A mismatch means the client is pricing against a roster it has not observed, and the attach is rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412).

No other endpoint accepts a version field. All other mutation ordering is handled by the state machines and validation pipeline, not by client-supplied versions.

### 2.7. Nested Paths and Existence Validation

Several resources are addressed as children of others — an attachment under a booking, a permit under its own top-level path, and so on. When a URL contains multiple path parameters, the server validates them left to right in path order: the parent segment is resolved first, and only if it exists is the child segment resolved. A URL such as one carrying both `{id}` (the booking) and the child identifier `bookingAnimalId` therefore reports a missing booking before it ever looks at the attachment. The same discipline applies to `staffAssignmentId` under a booking's staff assignments and `addOnRequestId` under a booking's add-ons. Child resources created under a booking — roster attachments, staff assignments, add-on requests, permits, the waiver, weather assessments, and ledger entries — carry a system-populated `booking_id` taken from the path, never from the request body; likewise a health record's `animal_id` and an insurance certificate's `customer_id` come from the path that addresses them.

Each resource type has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_ANIMAL_NOT_FOUND`, `ERR_HANDLER_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_ADDON_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, and `ERR_ASSIGNMENT_NOT_FOUND`, all HTTP 404.

### 2.8. The Logical Clock

All temporal rules — lead times, freshness windows, rest buffers, cancellation tiers, expiry comparisons — evaluate against the server's logical clock, never against wall-clock time directly. At startup the logical clock reads exactly 2026-05-01T00:00:00Z, and before any operator intervention it continues to read that default; it never silently falls back to wall-clock time. An `Operator` may advance the clock through a test-driving capability that accepts a `to_iso8601` instant and responds with the resulting `current_utc`. Every rule in §3 phrased as "now" means this logical clock.

### 2.9. Validation Pipeline and Gate Ordering

Requests are validated in a fixed pipeline, and earlier failures mask later ones:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is declared; failures are `ERR_UNAUTHENTICATED`.
2. **Authorization** — the role is permitted for the endpoint, entity-backed ownership holds for `Customer` callers, and the cancel-reason role binding holds; failures are `ERR_FORBIDDEN`.
3. **Request shape** — required body fields are present, enum values are valid, types are correct, an event's `end_time` falls strictly after its `start_time`, and ranged inputs (such as a temperament tier between 1 and 3, or a precipitation probability between 0 and 100) are in range; failures are `ERR_INVALID_REQUEST`.
4. **Existence** — referenced path and body resources exist, validated left to right as in §2.7; failures are the resource-specific 404 errors.
5. **State validity** — the target resource is in a valid from-state for the requested transition, including the rule that terminal states accept no further transitions; failures are `ERR_INVALID_STATE`.
6. **Optimistic concurrency** — on the two endpoints of §2.6, `expected_booking_version` matches the booking's current `version`; failures are `ERR_STALE_BOOKING_VERSION`.
7. **Business rules** — the domain gates of §3, evaluated in the per-endpoint orders stated there.

Within an endpoint, when §3 enumerates several business checks, the enumeration order is the evaluation order, so the first failing check is the one the caller sees.

### 2.10. The Booking Ledger

Money never moves implicitly. Every monetary event on a booking is an append-only `LedgerEntry` carrying an `entry_type` — one of `PAYMENT`, `REFUND`, `FORFEIT`, `PENALTY`, or `CHARGE` — an unsigned `amount_cents` whose direction is implied by the entry type, and a human-readable `description` memo. Ledger entries are immutable records (§2.4): they carry no `updated_at` and no `version`. A booking's `total_paid_cents` is always the sum of its `PAYMENT` entries and is recomputed whenever a payment is recorded. The ledger is the source of truth a customer or auditor reads to reconstruct what was charged, paid, refunded, forfeited, or penalized.

## 3. Business Logic & Workflows

### 3.1. Customers, Venues, and Liability Insurance

Everything begins with registration. An `Anonymous` caller registers a customer by supplying an `email` — unique across all customers — a `full_name`, and a `customer_type` of `PRIVATE`, `SCHOOL`, or `LIBRARY`. The customer type matters downstream: institutional customers (`SCHOOL` and `LIBRARY`) receive discounted pricing and face stricter insurance minimums. Customers, coordinators, compliance officers, and operators can all fetch a customer record, and a customer or coordinator can list the venues a customer owns.

A `Customer` registers each event site as a venue owned by the acting customer — the venue's `customer_id` is taken from the `X-User-ID` header at creation, never from the request body. The registration captures the site's `name` and `address`, its `venue_type` (`INDOOR`, `OUTDOOR`, or `MIXED`), whether it has `water_access` for animal care, its `surface_type` (`GRASS`, `PAVEMENT`, or `INDOOR_FLOOR`), its `travel_zone` dispatch band (`ZONE_A`, `ZONE_B`, or `ZONE_C`), the one-way `distance_miles` from the operator's base, the `max_guest_capacity` the site may host, and two jurisdictional flags: `requires_animal_permit` and `requires_handwash_stations`. Every one of these fields feeds a later rule — the zone and distance drive the travel fee, the surface type can inflate it, the capacity caps bookings, and the two flags drive the permit and handwash gates. Customers, coordinators, and operators can fetch a venue.

Liability insurance follows the same customer-owned pattern. A `Customer` submits an insurance certificate under its own customer record with the `provider` name, a `policy_number`, the `coverage_amount_cents` of liability coverage, and an `expires_at` coverage expiry; the certificate enters as `SUBMITTED`. A `ComplianceOfficer` then verifies it, supplying a `decision` of `VERIFIED` or `REJECTED` — both terminal states with no further transitions. Customers, compliance officers, and operators can list a customer's certificates. Verification alone is not enough for a booking to proceed: at confirmation time the rules of §3.6 demand a `VERIFIED` certificate whose coverage meets the booking-type minimum and whose `expires_at` extends strictly past the event's end.

### 3.2. The Animal Roster and the Veterinary Health Cycle

An `Operator` builds the roster one animal at a time, supplying the animal's `name`, its `species` (`GOAT`, `SHEEP`, `PONY`, `RABBIT`, `CHICKEN`, or `REPTILE`), its `weight_class` (`SMALL`, `MEDIUM`, or `LARGE`, which drives both trailer load and compliance load), a `temperament_tier` from 1 (skittish) to 3 (calmest) — tier-3 animals earn a compliance bonus — and the `base_event_fee_cents` charged per event before any weekend multiplier. An animal's `rest_buffer_hours` defaults to 4 when not supplied: that many hours are blocked before and after each confirmed event window for that animal. New animals enter as `AVAILABLE`. Coordinators, operators, and veterinarians can browse the roster — the list accepts optional `species`, `weight_class`, and `status` filters alongside `limit` and `offset` — fetch a single animal, list an animal's health records, and (coordinators and operators) list the booking attachments of an animal.

Health oversight belongs to the `Veterinarian`, who files a health record for an animal with the `exam_date`, a `result` of `PASS` or `FAIL`, a `valid_until` certification horizon (ignored when the result is `FAIL`), and optional free-text `notes` defaulting to an empty string. Each animal also carries a derived `current_health_cert_expires_at`: the latest `valid_until` across all of its `PASS` records, or null when no `PASS` record exists.

A `PASS` result recomputes `current_health_cert_expires_at`. For an `AVAILABLE` animal nothing else changes; for a `QUARANTINE` animal the pass also returns it to `AVAILABLE`. A `FAIL` result is far more consequential — it fires a three-link quarantine cascade:

- **Link 1:** the animal itself moves from `AVAILABLE` to `QUARANTINE`.
- **Link 2:** every booking attachment of this animal whose status is `PROPOSED` or `CONFIRMED`, on any parent booking that is not in a terminal state (`INVOICED` or any of the cancelled states), is removed with `removal_reason` `QUARANTINE`. Each affected booking has its `quote_fresh` flag cleared to false and its `version` incremented, so clients holding those bookings observe the mutation.
- **Link 3:** if such a parent booking was `CONFIRMED` and its remaining count of `CONFIRMED` roster attachments is now zero, the booking itself is cancelled for compliance — it moves to `CANCELLED_COMPLIANCE` with the full compliance refund variant of §3.7 (a `FORFEIT` entry of everything paid, a `PENALTY` entry, `payment_status` `FORFEITED`) and the shared cancel cascade. A single vet record can thus unwind an entire confirmed event.

Retirement is an operator action with two flavors. Retiring an `AVAILABLE` animal runs the same attachment-removal cascade as quarantine but with `removal_reason` `RETIRED` — and, crucially, no booking auto-cancellation: confirmed bookings keep operating with their remaining animals. Retiring a `QUARANTINE` animal has no cascade at all. `RETIRED` is terminal; a retired animal accepts no further transitions.

### 3.3. Handlers, Certifications, and Daily Capacity

Staff enter the system when an `Operator` adds a handler with a `name` and a `certifications` array drawn from `REPTILE_CERTIFIED`, `PONY_RIDE_CERTIFIED`, and `FIRST_AID`. New handlers are `ACTIVE`. Each handler carries a derived `scheduled_minutes_total`: the sum of event durations, in minutes, over all of that handler's staff assignments currently in `ASSIGNED` status. The total starts at 0 and is recomputed on every assign, every release, and every completion cascade — assignments that reach `RELEASED` or `COMPLETED` no longer count. Coordinators and operators can list handlers (with an optional `status` filter plus `limit` and `offset`), fetch one handler including its `scheduled_minutes_total`, and list a handler's assignments.

Assigning a handler to a booking is a coordinator action that takes a `handler_id` and a `role` of `LEAD` or `ASSISTANT` and creates the assignment in `ASSIGNED` status, incrementing the handler's `scheduled_minutes_total` by the booking's event duration. Two capacity guards protect the handler's day, and a violation of either is rejected with `ERR_HANDLER_OVERBOOKED` (HTTP 409). The guards consider every existing `ASSIGNED` assignment of the candidate handler whose parent booking is non-terminal and shares the new booking's calendar date in UTC:

- **Strict overlap:** no existing assignment's event window may strictly overlap the new window — that is, the existing window starts before the new window ends and the new window starts before the existing window ends. Windows that merely touch at an endpoint (one ends exactly when the other begins) are allowed.
- **Aggregate capacity:** the sum of the existing event durations plus the new event's duration must not exceed 480 minutes — an eight-hour working day. Exactly 480 minutes in total is allowed; 481 is not.

Releasing an assignment manually is allowed only while the parent booking is in `DRAFT`, `QUOTED`, `CONFIRMED`, or `WEATHER_HOLD`; against any other booking state the release fails with `ERR_INVALID_STATE`. A manual release sets `release_reason` to `MANUAL` and recomputes the handler's `scheduled_minutes_total`, decrementing it by the released booking's event duration. Releases also arrive from the booking cancel cascade of §3.7 with `release_reason` `BOOKING_CANCELLED`. Finally, when a booking completes, each of its still-`ASSIGNED` assignments moves to `COMPLETED` and the handler totals are recomputed again. `RELEASED` and `COMPLETED` are both terminal for an assignment.

### 3.4. Building a Booking: Draft, Roster, Add-Ons, and the Provisional Quote

A `Customer` creates a booking by naming the `venue_id`, the event window `start_time` and `end_time` (both ISO 8601 UTC, end strictly after start), the expected `guest_count`, the expected `child_guest_count` — which equals the number of waiver signatures the event will require — the `booking_type` (`PRIVATE_PARTY`, `SCHOOL_PROGRAM`, or `LIBRARY_PROGRAM`), and the `planned_handwash_stations` the customer intends to deploy. Three checks guard creation: the start must fall strictly after now (`ERR_EVENT_IN_PAST`), at least 48 hours after now (`ERR_EVENT_TOO_SOON`), and the guest count must not exceed the venue's `max_guest_capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`). A new booking enters as `DRAFT` with `payment_status` `UNPAID`, `quote_fresh` false, and `total_paid_cents` zero. Creating the booking also auto-creates its waiver, described in §3.6. Customers, coordinators, operators, and compliance officers can list bookings — with optional `customer_id`, `venue_id`, `status`, and `payment_status` filters plus pagination — and fetch a single booking with all of its computed quote fields.

With a draft in hand, a `Coordinator` assembles the roster. Attaching an animal takes an `animal_id` and a `role` of `PETTING_ZOO`, `PONY_RIDE`, or `REPTILE_SHOW`, creating the attachment as `PROPOSED`; attaching an animal already on the booking in `PROPOSED` or `CONFIRMED` status is rejected with `ERR_ANIMAL_ALREADY_ON_BOOKING` (HTTP 409). Every roster mutation clears the booking's `quote_fresh` to false and increments the booking's `version`.

Confirming a roster attachment — moving it from `PROPOSED` to `CONFIRMED` — runs four checks in order. First, the parent booking must be in `DRAFT` or `QUOTED` (`ERR_INVALID_STATE`). Second, the animal must be `AVAILABLE`; anything else means `ERR_ANIMAL_QUARANTINED`. Third, the animal's `current_health_cert_expires_at` must be non-null and fall strictly after the booking's `end_time` — an animal without a health certificate valid beyond the event end is rejected with `ERR_HEALTH_CERT_EXPIRED`. Fourth, the animal's buffered rest window must not collide with its other commitments: each of the animal's other `CONFIRMED` attachments on non-terminal bookings occupies a buffered half-open interval stretching from `rest_buffer_hours` before that event's start to `rest_buffer_hours` before that event's end is mirrored after it — that is, the interval opens `rest_buffer_hours` before the event start and closes `rest_buffer_hours` after the event end, including the opening instant and excluding the closing one. The new booking's buffered interval conflicts with an existing one when the existing interval opens before the new interval closes and the new interval opens before the existing interval closes; buffered endpoints that merely touch do not conflict. A collision is rejected with `ERR_ANIMAL_SCHEDULE_CONFLICT` (HTTP 409). A successful confirm again clears the booking's `quote_fresh` and bumps its `version`.

Attachments come off in three ways. A coordinator may remove one manually: a `PROPOSED` attachment may always be removed, while a `CONFIRMED` attachment may be manually removed only while the parent booking is in `DRAFT` or `QUOTED` (`ERR_INVALID_STATE` otherwise); either way `removal_reason` records `MANUAL`. Quarantine and retirement cascades remove attachments with reasons `QUARANTINE` and `RETIRED`, and the booking cancel cascade removes them with `BOOKING_CANCELLED`. Every removal clears the parent booking's `quote_fresh` and increments its `version`. `REMOVED` is terminal.

Add-ons follow a parallel track, but the customer initiates them. A `Customer` requests an add-on with an `addon_type` of `PONY_RIDE` or `REPTILE_SHOW`, a `duration_minutes`, and the OCC field `expected_booking_version` per §2.6. A booking may not hold two requests of the same `addon_type` in `REQUESTED` or `APPROVED` status — a duplicate is rejected with `ERR_ADDON_ALREADY_REQUESTED` (HTTP 409). A fresh request enters as `REQUESTED`, and its attachment clears the booking's `quote_fresh` and increments the booking's `version`. A `Coordinator` then decides the request with a `decision`. Approval is gated: a `REPTILE_SHOW` may be approved only when at least one `ASSIGNED` staff assignment on the booking belongs to a handler whose `certifications` include `REPTILE_CERTIFIED` (`ERR_NO_CERTIFIED_HANDLER` otherwise), and a `PONY_RIDE` may be approved only when the venue's `venue_type` is `OUTDOOR` or `MIXED` (`ERR_ADDON_VENUE_INCOMPATIBLE` otherwise — ponies do not perform indoors). Approval moves the request to `APPROVED` and clears the booking's `quote_fresh`. Denial moves it to `DENIED` and records the coordinator's `denial_reason`. `DENIED` is terminal; `REQUESTED` and `APPROVED` requests can still be swept to `REMOVED` by the booking cancel cascade.

Once the roster and add-ons reflect the plan, a `Coordinator` asks for a quote. Quoting is allowed from `DRAFT` (moving the booking to `QUOTED`) and from `QUOTED` itself (a re-quote with identical recomputation), and it stamps every computed quote field on the booking: `animal_subtotal_cents`, `addon_subtotal_cents`, `discount_cents`, `surcharge_cents`, `travel_fee_cents`, `guest_surcharge_cents`, `quoted_total_cents`, `deposit_amount_cents`, `required_handwash_stations`, `required_staff_count`, and `compliance_screening_score`. It also sets `quote_fresh` to true and increments the booking's `version`. The pricing evaluation order is pinned and must be followed exactly:

1. **Animal lines.** For each in-scope attachment, the line is the animal's `base_event_fee_cents`; when the event's calendar date (taken from `start_time` in UTC) falls on a Saturday or Sunday, the line is instead the base fee multiplied by 1.15, rounded half up to whole cents. The rounding is per line, and only then are the lines summed into `animal_subtotal_cents` — the pinned order is round-per-line-then-sum, and summing first and rounding once is forbidden because it yields different cents. For example, three animals at 3343 cents each on a weekend produce three lines of 3844 cents each (3343 times 1.15 is 3844.45, which rounds half up to 3844) for a subtotal of 11532, whereas summing first would give 10029 times 1.15, which rounds to 11533 — a different, forbidden answer.
2. **Add-on lines.** `addon_subtotal_cents` is the sum of add-on fees over in-scope requests. A `PONY_RIDE` costs a flat 12000 cents when `duration_minutes` is at most 60; beyond that it costs 12000 plus 200 cents for each minute past 60. A `REPTILE_SHOW` costs a flat 15000 cents when `duration_minutes` is at most 45; beyond that it costs 15000 plus 250 cents for each minute past 45.
3. **Subtotal.** The subtotal is `animal_subtotal_cents` plus `addon_subtotal_cents`. Travel and guest surcharges are never part of it.
4. **Institutional discount.** For `SCHOOL_PROGRAM` and `LIBRARY_PROGRAM` bookings, `discount_cents` is 15 percent of the subtotal, rounded half up; for `PRIVATE_PARTY` it is 0. The discount is computed first, from the raw subtotal.
5. **Liability surcharge.** `surcharge_cents` is 3 percent of the subtotal minus the discount, rounded half up — computed second, from the discounted amount. The order is pinned precisely because it looks circular: reversing it (surcharge on the raw subtotal, discount on the surcharged amount) is forbidden. On a subtotal of 29000 the pinned order yields a discount of 4350 and a surcharge of 740; the reversed order would yield 870 and 4481 and a different final total.
6. **Travel and setup fee.** The venue's `travel_zone` sets a base fee and an included mileage: `ZONE_A` is 5000 cents with 25 miles included, `ZONE_B` is 9000 cents with 50 miles included, and `ZONE_C` is 14000 cents with 100 miles included. Overage miles are the amount by which `distance_miles` exceeds the included mileage, floored at zero, and each overage mile costs 85 cents. Trailer count is the in-scope animal count divided by 6, rounded up, with a minimum of one trailer, and each trailer adds 3000 cents. The raw fee is the zone base plus the mileage overage plus the trailer fees; when the venue's `surface_type` is `PAVEMENT`, the raw fee is multiplied by 1.25 and rounded half up — the only rounding point in this calculation — and on any other surface the raw fee stands as-is.
7. **Guest tier surcharge.** `guest_surcharge_cents` tiers on the in-scope guest count: 20 guests or fewer pay nothing; 21 through 50 pay 1500 cents; 51 through 100 pay 3500 cents; more than 100 pay 6000 cents. Tier boundaries are inclusive at the lower edge — 21 guests belongs to the 1500-cent tier.
8. **Total.** `quoted_total_cents` is the subtotal minus the discount plus the surcharge plus the travel fee plus the guest surcharge.

The provisional quote counts `PROPOSED` and `CONFIRMED` attachments, `REQUESTED` and `APPROVED` add-ons, and the booked `guest_count` for the guest tier. The final invoice of §3.8 re-runs the identical eight steps with a stricter input set, so the same nominal booking can price differently at the end. Quoting also derives the deposit: `deposit_amount_cents` is 30 percent of `quoted_total_cents`, rounded half up — a quoted total of 34375 cents yields a deposit of 10313 cents, because half-cent cases round up.

Three more requirements are computed alongside the quote. **Handwash stations:** `required_handwash_stations` is zero when the venue's `requires_handwash_stations` flag is false, and otherwise the guest count divided by 20 rounded up — exactly divisible counts need exactly that many stations, so 40 guests require 2 stations and 41 require 3 — plus one additional station whenever any in-scope add-on is a `REPTILE_SHOW`. **Staffing:** petting-zoo attachments drive handler slots — the count of in-scope attachments with `role` `PETTING_ZOO`, divided by 4 and rounded up, with a minimum of one slot — plus one extra slot when any in-scope add-on is a `PONY_RIDE` and one more when any in-scope add-on is a `REPTILE_SHOW`; `required_staff_count` is then the larger of those handler slots and the `child_guest_count` divided by 8 rounded up. **Compliance screening:** `compliance_screening_score` starts at 100 and subtracts 15 per in-scope `LARGE` animal, 10 per `MEDIUM`, and 5 per `SMALL`; subtracts 10 when the venue is `INDOOR`; subtracts 8 when the venue lacks `water_access`; subtracts 5 for each handwash station by which the requirement exceeds the `planned_handwash_stations` (never below zero); subtracts 1 point for every full block of 10 guests beyond the first 30 in scope; and adds back 2 points per in-scope animal with `temperament_tier` 3, with that bonus capped at 10 points. The result is clamped to the range 0 through 100. The screening variant uses the planned world: `PROPOSED` and `CONFIRMED` animals, planned stations, and the booked guest count — including computing the station requirement from that same guest count.

### 3.5. Permits and Regulatory Segregation of Duties

Many bookings cannot legally proceed without paperwork. A `Coordinator` creates a permit application under a booking with a `permit_type` of `ANIMAL_EXHIBITION`, `HEALTH_DEPT`, or `FIRE_SAFETY`, plus a `jurisdiction` label; the application starts in `DRAFT`. Customers, coordinators, and compliance officers can list a booking's permits.

Submitting a permit moves it from `DRAFT` to `SUBMITTED` and records the submitter's `X-User-ID` as `submitted_by_user_id`. The filing system demands lead time: submission is allowed only when the event's `start_time` is at least 336 hours — fourteen full days — after now; filing later is rejected with `ERR_PERMIT_LEAD_TIME`. The same lead-time rule governs resubmission.

Decision belongs to a different desk. A `ComplianceOfficer` decides a `SUBMITTED` permit with a `decision` of `ISSUED` or `DENIED`, and the server records the decider's `X-User-ID` as `decided_by_user_id`. Segregation of duties is enforced mechanically: the decider's `X-User-ID` must differ from the permit's `submitted_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTY` (HTTP 403). Issuance is terminal — `ISSUED` accepts no further transitions. Denial records a `denial_reason` and feeds a re-application loop: a `DENIED` permit may be submitted again (subject to the same 336-hour lead time), which clears its `denial_reason` back to null and refreshes `submitted_by_user_id`, cycling `DENIED` back to `SUBMITTED` and onward to a fresh decision.

### 3.6. Payments, Waivers, and the Confirmation Gate

Money flows in through customer payments. A `Customer` records a payment against its booking with an `amount_cents` and a payment `method`. Payments are accepted only while the booking is in `QUOTED`, `CONFIRMED`, or `WEATHER_HOLD`, and a payment that would push `total_paid_cents` above the current `quoted_total_cents` is rejected — both failures surface as `ERR_OVERPAYMENT`. Each accepted payment appends a `PAYMENT` ledger entry, recomputes `total_paid_cents`, and advances `payment_status`: from `UNPAID` to `DEPOSIT_PAID` on the first payment, and on to `PAID_IN_FULL` once the paid total reaches the quoted total.

The waiver rides alongside the booking from birth. Creating a booking auto-creates exactly one waiver whose `required_signatures` equals the booking's `child_guest_count` and whose `signed_count` starts at 0; the waiver's `status` is derived from those two numbers — `PENDING` when nothing is signed, `PARTIAL` when some but not all required signatures are in, and `COMPLETE` when the counts meet. A booking with zero required signatures is therefore born with a `COMPLETE` waiver. A `Customer` records guardian signatures in batches by supplying a `count`; the batch may not push `signed_count` beyond `required_signatures` — an overflowing batch is rejected with `ERR_WAIVER_SIGNATURE_OVERFLOW` — and after each accepted batch the status is re-derived. Fetching a booking's waiver returns an array of zero or one element.

Confirmation is the customer's signature on the whole plan, moving a `QUOTED` booking to `CONFIRMED`. Nine business gates stand in the way, evaluated in this order:

1. The booking's `compliance_screening_score` must be at least 60 (`ERR_COMPLIANCE_SCORE_TOO_LOW`).
2. `planned_handwash_stations` must meet or exceed `required_handwash_stations` (`ERR_HANDWASH_STATIONS_INSUFFICIENT`).
3. Every required permit type must have an `ISSUED` permit on the booking: an `ANIMAL_EXHIBITION` permit whenever the venue's `requires_animal_permit` flag is set, plus a `HEALTH_DEPT` permit whenever the `booking_type` is `SCHOOL_PROGRAM` or `LIBRARY_PROGRAM` (`ERR_PERMIT_NOT_ISSUED`).
4. At least one roster attachment must be `CONFIRMED` (`ERR_NO_ANIMALS_CONFIRMED`).
5. The `guest_count` must not exceed the venue's `max_guest_capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`).
6. The `start_time` must still be at least 48 hours after now (`ERR_EVENT_TOO_SOON`).
7. The quote must be fresh — `quote_fresh` true, meaning no roster, add-on, or schedule mutation since the last quote (`ERR_QUOTE_STALE`, HTTP 409).
8. The customer must hold a `VERIFIED` insurance certificate with `coverage_amount_cents` of at least 500000 cents for a `PRIVATE_PARTY` or at least 1000000 cents for a `SCHOOL_PROGRAM` or `LIBRARY_PROGRAM`, and with `expires_at` falling strictly after the booking's `end_time` (`ERR_INSURANCE_NOT_VERIFIED`).
9. `total_paid_cents` must meet or exceed `deposit_amount_cents` (`ERR_DEPOSIT_INSUFFICIENT`).

A successful confirmation increments the booking's `version`. Confirmation is where the quote stops being a proposal: from here the booking is operationally real, and the remaining gates — dispatch, setup, completion — execute against it.

### 3.7. Weather, Rescheduling, and Cancellation

Weather is tracked as data before it is allowed to change plans. A `Coordinator` records a weather assessment for a booking with the `assessed_at` reading time, the `forecast_temp_f` in Fahrenheit, the `forecast_precip_pct` precipitation probability between 0 and 100, the sustained `wind_mph`, and a `verdict` of `PROCEED`, `HOLD_RECOMMENDED`, or `MANDATORY_HOLD`. Assessments are immutable records; customers and coordinators can list them.

When a forecast turns dangerous, a coordinator places a `CONFIRMED` booking on weather hold, supplying a `weather_assessment_id` that must reference an assessment of this booking. Two checks justify the hold: the assessment's `assessed_at` must be no older than 24 hours before now (`ERR_ASSESSMENT_STALE`), and its `verdict` must be `MANDATORY_HOLD` — a mere recommendation is not enough (`ERR_WEATHER_HOLD_NOT_JUSTIFIED`). The hold moves the booking to `WEATHER_HOLD` and increments its `version`. Releasing the hold needs no justification at all: a coordinator may return a `WEATHER_HOLD` booking to `CONFIRMED` unconditionally, again incrementing the version. The two transitions form a cycle a booking can traverse repeatedly as forecasts evolve.

Plans also move for non-weather reasons. Rescheduling replaces the event window with a `new_start_time` and `new_end_time`, and it is the second OCC endpoint of §2.6 — the request must carry `expected_booking_version` matching the booking's current `version` or be rejected with `ERR_STALE_BOOKING_VERSION` (HTTP 412). A `Customer` reschedules a `CONFIRMED` booking; a `Coordinator` reschedules one sitting in `WEATHER_HOLD`. In both cases the new start must fall strictly after now (`ERR_EVENT_IN_PAST`) and at least 48 hours after now (`ERR_EVENT_TOO_SOON`), and the animal buffered-window and handler capacity checks of §3.2 and §3.3 are re-run against the new window for every `CONFIRMED` roster attachment and every `ASSIGNED` staff assignment, surfacing `ERR_ANIMAL_SCHEDULE_CONFLICT` or `ERR_HANDLER_OVERBOOKED` as applicable. A successful reschedule replaces `start_time` and `end_time`, clears `quote_fresh` to false — the schedule changed, so the quote no longer reflects the plan — and increments the booking's `version`.

Cancellation is three different products wearing one coat, bound to roles as §2.1 describes. A `Customer` cancels with `reason` `CUSTOMER` from `DRAFT`, `QUOTED`, `CONFIRMED`, or `WEATHER_HOLD`. A `Coordinator` cancels with `reason` `WEATHER` from `CONFIRMED` or `WEATHER_HOLD`, or with `reason` `COMPLIANCE` from `CONFIRMED`. Any attempt from another state is `ERR_INVALID_STATE`, and the terminal states — `INVOICED`, `CANCELLED_CUSTOMER`, `CANCELLED_WEATHER`, `CANCELLED_COMPLIANCE` — accept no transitions at all. Every cancellation runs the same cascade and a reason-specific refund waterfall.

The **refund waterfall** allocates what the customer has paid. For a customer cancellation, tiers are based on the exact fractional hours between now and the event's `start_time`, with boundaries inclusive at the lower edge of each tier: 168 hours or more before start refunds everything paid; at least 72 but fewer than 168 hours refunds 75 percent of `total_paid_cents`, rounded half up (exactly 72.0 hours falls in this tier); at least 24 but fewer than 72 hours refunds 50 percent, rounded half up; fewer than 24 hours refunds nothing. A weather cancellation refunds everything paid minus 2500 cents for each of the booking's permits in `SUBMITTED` or `ISSUED` status — non-recoverable filing fees — floored at zero. A compliance cancellation refunds nothing at all and additionally appends a `PENALTY` ledger entry of 20 percent of `quoted_total_cents`, rounded half up. In all variants the unrefunded remainder, when nonzero, is appended as a `FORFEIT` entry, and refunds are appended as `REFUND` entries. When the booking was never paid (`total_paid_cents` is zero), no ledger entries are created for any variant and `payment_status` stays `UNPAID`. Otherwise `payment_status` becomes `REFUND_FULL` when the refund equals the amount paid, `REFUND_PARTIAL` when the refund is positive but smaller, and `FORFEITED` when nothing is refunded.

The **cancel cascade** then unwinds the operational plan. Every `ASSIGNED` staff assignment moves to `RELEASED` with `release_reason` `BOOKING_CANCELLED`, and each release recomputes the affected handler's `scheduled_minutes_total`. Every `PROPOSED` or `CONFIRMED` roster attachment moves to `REMOVED` with `removal_reason` `BOOKING_CANCELLED`. Every `REQUESTED` or `APPROVED` add-on request moves to `REMOVED`. The booking's `quote_fresh` clears to false and its `version` increments. One more path reaches the same destination: the quarantine cascade of §3.2 can drive a `CONFIRMED` booking into `CANCELLED_COMPLIANCE` with no human cancel call at all, when the last confirmed animal is stripped from it — a depth-three chain from a single vet record to ledger entries.

### 3.8. Event Day: Dispatch, Setup, Completion, and Final Invoicing

Event day begins with dispatch, the coordinator action that moves a `CONFIRMED` booking to `EN_ROUTE`. Three gates guard it, in this order: the waiver must be `COMPLETE` (`ERR_WAIVER_INCOMPLETE`); the count of `ASSIGNED` staff assignments must meet or exceed `required_staff_count` (`ERR_STAFF_RATIO_NOT_MET`); and `total_paid_cents` must meet or exceed `quoted_total_cents` — the event never rolls with an open balance (`ERR_BALANCE_UNPAID`). Arrival on site is acknowledged by moving the booking from `EN_ROUTE` to `ON_SITE_SETUP`; it carries no preconditions.

Opening the event to guests moves the booking from `ON_SITE_SETUP` to `IN_PROGRESS` and is the moment of truth for sanitation: the coordinator reports the `actual_handwash_stations` deployed — recorded on the booking, where it was previously null — and that count must meet or exceed `required_handwash_stations` or the opening is rejected with `ERR_HANDWASH_STATIONS_INSUFFICIENT`.

Closing the event moves the booking from `IN_PROGRESS` to `COMPLETED`. The coordinator reports the `actual_attendance_count`, recorded where it was previously null. Completion recomputes the compliance score in its audited variant into `compliance_audited_score` (null until now): the same weighted formula as §3.4, but fed by the actual world — only `CONFIRMED`, non-removed roster animals, the deployed station count instead of the planned one, and actual attendance instead of booked guests, including recomputing the station requirement from actual attendance. Because inputs differ, the audited score can diverge from the screening score for the same booking. Completion also sweeps every still-`ASSIGNED` staff assignment to `COMPLETED` and recomputes each handler's `scheduled_minutes_total`, since completed assignments no longer count against their day.

The last transition finalizes the money. Finalizing the invoice moves a `COMPLETED` booking to `INVOICED` — terminal — and re-runs the pinned eight-step pricing of §3.4 in its final variant: only `CONFIRMED` non-removed attachments count, only `APPROVED` add-ons count, and the guest tier uses `actual_attendance_count` instead of the booked count. The result is stored as `final_total_cents`, null until this moment, and appended to the ledger as a `CHARGE` entry of that amount. Settlement then reconciles against what was paid: if `total_paid_cents` exceeds `final_total_cents`, the difference is appended as a `REFUND` entry and `payment_status` becomes `REFUND_PARTIAL`; if the two are exactly equal, `payment_status` becomes `PAID_IN_FULL`. The booking's `version` increments. From that point on, the story of the event is readable end to end in the ledger — customers, coordinators, and operators can list a booking's ledger entries — and in the computed fields the booking carries.

## 4. Endpoint Definitions

All endpoints live under the `/petting-zoo` mount. Status code rules are uniform: creating a new resource returns 201; modifications, state transitions, and reads return 200 — including the delete-style release and removal actions, which return the transitioned resource. Request and response shapes for each endpoint are defined by the workflows in §3; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /petting-zoo/customers | Register a customer | Anonymous |
| GET | /petting-zoo/customers/{id} | Fetch one customer | Customer, Coordinator, ComplianceOfficer, Operator |
| GET | /petting-zoo/customers/{id}/venues | List venues owned by the customer | Customer, Coordinator |
| POST | /petting-zoo/customers/{id}/insurance-certificates | Submit a liability insurance certificate | Customer |
| GET | /petting-zoo/customers/{id}/insurance-certificates | List the customer's insurance certificates | Customer, ComplianceOfficer, Operator |
| POST | /petting-zoo/insurance-certificates/{id}/verify | Verify or reject a submitted certificate | ComplianceOfficer |
| POST | /petting-zoo/venues | Register an event venue (owned by the acting customer) | Customer |
| GET | /petting-zoo/venues/{id} | Fetch one venue | Customer, Coordinator, Operator |
| POST | /petting-zoo/animals | Add an animal to the roster | Operator |
| GET | /petting-zoo/animals | List animals with filters and pagination | Coordinator, Operator, Veterinarian |
| GET | /petting-zoo/animals/{id} | Fetch one animal | Coordinator, Operator, Veterinarian |
| POST | /petting-zoo/animals/{id}/retire | Retire an animal (removal cascade with reason RETIRED) | Operator |
| POST | /petting-zoo/animals/{id}/health-records | File a veterinary health record; FAIL triggers the quarantine cascade | Veterinarian |
| GET | /petting-zoo/animals/{id}/health-records | List an animal's health records | Veterinarian, Coordinator, Operator |
| GET | /petting-zoo/animals/{id}/booking-animals | List booking attachments for an animal | Coordinator, Operator |
| POST | /petting-zoo/handlers | Add a staff handler | Operator |
| GET | /petting-zoo/handlers | List handlers | Coordinator, Operator |
| GET | /petting-zoo/handlers/{id} | Fetch one handler (includes `scheduled_minutes_total`) | Coordinator, Operator |
| GET | /petting-zoo/handlers/{id}/staff-assignments | List a handler's assignments | Coordinator, Operator |
| POST | /petting-zoo/bookings | Create a booking (DRAFT); auto-creates its waiver | Customer |
| GET | /petting-zoo/bookings | List bookings with filters and pagination | Customer, Coordinator, Operator, ComplianceOfficer |
| GET | /petting-zoo/bookings/{id} | Fetch one booking with all computed quote fields | Customer, Coordinator, Operator, ComplianceOfficer |
| POST | /petting-zoo/bookings/{id}/quote | Compute or recompute the provisional quote (DRAFT or QUOTED) | Coordinator |
| POST | /petting-zoo/bookings/{id}/payments | Record a customer payment toward the booking | Customer |
| POST | /petting-zoo/bookings/{id}/confirm | Confirm a quoted booking (full compliance gate) | Customer |
| POST | /petting-zoo/bookings/{id}/reschedule | Move the event window (OCC on booking version) | Customer, Coordinator |
| POST | /petting-zoo/bookings/{id}/cancel | Cancel a booking; reason CUSTOMER (Customer) or WEATHER/COMPLIANCE (Coordinator) | Customer, Coordinator |
| POST | /petting-zoo/bookings/{id}/weather-hold | Place a CONFIRMED booking on weather hold using a fresh MANDATORY_HOLD assessment | Coordinator |
| POST | /petting-zoo/bookings/{id}/release-weather-hold | Release a weather hold back to CONFIRMED | Coordinator |
| POST | /petting-zoo/bookings/{id}/dispatch | Dispatch crew and trailer (CONFIRMED to EN_ROUTE) | Coordinator |
| POST | /petting-zoo/bookings/{id}/arrive | Mark crew arrived; setup begins (EN_ROUTE to ON_SITE_SETUP) | Coordinator |
| POST | /petting-zoo/bookings/{id}/start-event | Open the event to guests after the setup compliance check | Coordinator |
| POST | /petting-zoo/bookings/{id}/complete | Close the event; audited compliance recomputed; staff completed | Coordinator |
| POST | /petting-zoo/bookings/{id}/finalize-invoice | Finalize pricing (final variant), issue CHARGE, refund overpayment | Coordinator |
| POST | /petting-zoo/bookings/{id}/animals | Attach a roster animal to the booking (PROPOSED) | Coordinator |
| POST | /petting-zoo/bookings/{id}/animals/{bookingAnimalId}/confirm | Confirm an attached animal (health, quarantine, rest-window gates) | Coordinator |
| DELETE | /petting-zoo/bookings/{id}/animals/{bookingAnimalId} | Manually remove an attached animal | Coordinator |
| GET | /petting-zoo/bookings/{id}/animals | List animals attached to a booking | Customer, Coordinator, Operator |
| POST | /petting-zoo/bookings/{id}/staff-assignments | Assign a handler to the booking | Coordinator |
| DELETE | /petting-zoo/bookings/{id}/staff-assignments/{staffAssignmentId} | Release a handler assignment | Coordinator |
| GET | /petting-zoo/bookings/{id}/staff-assignments | List staff assigned to a booking | Customer, Coordinator, Operator |
| POST | /petting-zoo/bookings/{id}/add-ons | Request an add-on (pony ride / reptile show); OCC on booking version | Customer |
| POST | /petting-zoo/bookings/{id}/add-ons/{addOnRequestId}/decide | Approve or deny an add-on request | Coordinator |
| GET | /petting-zoo/bookings/{id}/add-ons | List add-on requests for a booking | Customer, Coordinator |
| POST | /petting-zoo/bookings/{id}/permits | Create a permit application (DRAFT) for the booking | Coordinator |
| POST | /petting-zoo/permits/{id}/submit | Submit (or resubmit after denial) a permit application | Coordinator |
| POST | /petting-zoo/permits/{id}/decide | Issue or deny a submitted permit (segregation of duties enforced) | ComplianceOfficer |
| GET | /petting-zoo/bookings/{id}/permits | List permits for a booking | Customer, Coordinator, ComplianceOfficer |
| POST | /petting-zoo/bookings/{id}/waiver-signatures | Record guardian waiver signatures | Customer |
| GET | /petting-zoo/bookings/{id}/waivers | Fetch the booking's waiver (array of 0 or 1) | Customer, Coordinator |
| POST | /petting-zoo/bookings/{id}/weather-assessments | Record a weather assessment for the event window | Coordinator |
| GET | /petting-zoo/bookings/{id}/weather-assessments | List weather assessments for a booking | Customer, Coordinator |
| GET | /petting-zoo/bookings/{id}/ledger-entries | List the booking's payment/refund/forfeit/penalty/charge ledger | Customer, Coordinator, Operator |
| POST | /petting-zoo/_clock/set_current_utc | Test-driving endpoint: set the server's logical clock (startup default 2026-05-01T00:00:00Z) | Operator |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_CUSTOMER_NOT_FOUND | 404 |
| ERR_VENUE_NOT_FOUND | 404 |
| ERR_ANIMAL_NOT_FOUND | 404 |
| ERR_HANDLER_NOT_FOUND | 404 |
| ERR_BOOKING_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_ADDON_NOT_FOUND | 404 |
| ERR_CERTIFICATE_NOT_FOUND | 404 |
| ERR_ASSIGNMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_BOOKING_VERSION | 412 |
| ERR_COMPLIANCE_SCORE_TOO_LOW | 422 |
| ERR_HANDWASH_STATIONS_INSUFFICIENT | 422 |
| ERR_PERMIT_NOT_ISSUED | 422 |
| ERR_ANIMAL_QUARANTINED | 422 |
| ERR_HEALTH_CERT_EXPIRED | 422 |
| ERR_WAIVER_INCOMPLETE | 422 |
| ERR_NO_ANIMALS_CONFIRMED | 422 |
| ERR_VENUE_CAPACITY_EXCEEDED | 422 |
| ERR_ANIMAL_SCHEDULE_CONFLICT | 409 |
| ERR_HANDLER_OVERBOOKED | 409 |
| ERR_STAFF_RATIO_NOT_MET | 422 |
| ERR_NO_CERTIFIED_HANDLER | 422 |
| ERR_ADDON_VENUE_INCOMPATIBLE | 422 |
| ERR_WAIVER_SIGNATURE_OVERFLOW | 422 |
| ERR_EVENT_IN_PAST | 422 |
| ERR_EVENT_TOO_SOON | 422 |
| ERR_PERMIT_LEAD_TIME | 422 |
| ERR_ASSESSMENT_STALE | 422 |
| ERR_WEATHER_HOLD_NOT_JUSTIFIED | 422 |
| ERR_QUOTE_STALE | 409 |
| ERR_INSURANCE_NOT_VERIFIED | 422 |
| ERR_ADDON_ALREADY_REQUESTED | 409 |
| ERR_ANIMAL_ALREADY_ON_BOOKING | 409 |
| ERR_SEGREGATION_OF_DUTY | 403 |
| ERR_DEPOSIT_INSUFFICIENT | 422 |
| ERR_BALANCE_UNPAID | 422 |
| ERR_OVERPAYMENT | 422 |

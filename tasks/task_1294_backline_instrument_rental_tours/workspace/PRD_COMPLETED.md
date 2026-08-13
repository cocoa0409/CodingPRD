# Backline Tour Rental API — Product Requirements Document

## 1. Introduction

Touring artists rarely travel with their own backline. The amplifiers, drum kits, keyboards, guitars, and PA stacks that fill a stage are rented city by city, and the company supplying them lives or dies on timing: the right physical unit must be staged at the right venue on the right date, packed in the right flight case, loaded on the right truck — and it must come back in one piece, or somebody pays. Between shows, that same company juggles per-artist deposits and insurance policies, maintenance windows per unit, damage claims per rental, and phone calls to partner vendors when the house pool runs dry in a city the tour cannot skip.

This document specifies the API through which such a backline rental company runs that operation end to end. It covers the gear catalog and the physical fleet built beneath it; artist accounts with their deposit ledgers and risk scores; tours, their stops, and the rider lines that demand specific models on specific dates; the sourcing decision that reserves a physical unit — or routes the demand to a partner vendor — inside a half-open rental window; the cartage legs that move units and flight cases between cities with tracked weight and technician labor; the inspection, damage, and maintenance discipline that keeps the fleet serviceable; and the settlement arithmetic that closes every reservation, stop, and tour. All resources are mounted under the `/backline` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Every request must carry `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly five roles: `OpsManager`, `TourManager`, `LogisticsCoordinator`, `WarehouseTech`, and `PartnerVendorRep`. A request with missing or malformed headers, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not permitted to perform the target operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `OpsManager`, `TourManager`, `LogisticsCoordinator`, or `WarehouseTech`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example, as `filed_by_user_id` on a damage claim, where it anchors segregation of duties — but it does not compare the header value to any entity's `id`. When `X-User-Role` is `PartnerVendorRep`, `X-User-ID` is the `id` of the acting `PartnerVendor`; ownership checks on any resource that references a partner vendor compare the resource's `partner_vendor_id` field to `X-User-ID`, which is how a vendor representative is confined to the cross-rental requests addressed to their own company. In practice that confinement takes three forms: the accept, reject, and fulfill actions reject a foreign representative with `ERR_VENDOR_NOT_ELIGIBLE`; the cross-rental request list is filtered to the acting representative's own vendor; and fetching a single cross-rental request by id is not ownership-restricted.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer value, a `limit` outside 1–100, or a negative `offset` fails with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order, breaking ties on `id`.

Paginated list responses carry the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` + `limit` is still below `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this system — artists, tours, stops, rider lines, catalog models, physical units, reservations, shipments and their lines, flight cases, partner vendors, cross-rental requests, maintenance tickets, and damage claims — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments on every mutation of the resource.

A mutation is anything that changes the stored representation — explicit client writes, cascading state transitions, and reconciliations of derived fields such as counters, aggregates, and balances all update `updated_at` and increment `version` on every resource they touch, including resources the client did not name directly. All server-emitted timestamps — the envelope's `api_request_timestamp` and every `created_at`/`updated_at` — are stamped from the logical clock of §2.5, never from wall-clock time.

### 2.5. The Logical Clock, Dates, and Rental Windows

The server keeps a logical clock rather than trusting wall-clock time. An `OpsManager` may advance or set it through an administrative capability that accepts a `to_iso8601` timestamp and reports the resulting `current_utc`. Before any such call, the clock defaults to exactly 2026-08-01T00:00:00Z, and it must never silently fall back to wall-clock time.

Date fields such as tour start and end dates, venue dates, ship dates, and reservation start and end dates are date-granularity values pinned to UTC midnight; `load_in_ts` is the exception and carries a full timestamp. Tours, stops, and shipments echo their date fields back exactly as the client supplied them, and a shipment's `ship_date` is recorded as supplied without being parsed; a reservation's `start_date` and `end_date`, by contrast, are stored and returned normalized to their UTC-midnight ISO 8601 rendering. All rental-window arithmetic treats a window as a half-open interval: the start date is included, the end date is excluded, and two windows that merely touch — one ending exactly when the other begins — do not overlap.

### 2.6. Money in Cents: Precision and Rounding

All monetary amounts in this API are integer cents, represented as plain numbers in request and response bodies. Whenever a calculation produces a fractional cent, the result is rounded half-up to whole cents.

Two rounding disciplines coexist and must not be conflated. Rental fee figures — both the provisional quote and the chronological settlement — round each component (cartage, insurance, late-day rate) half-up to whole cents individually and then sum the rounded components. The deposit hold, by contrast, sums its tiered components first and rounds half-up exactly once at the end. Partner-vendor commission is rounded half-up once. Damage charges are always whole cents and require no rounding.

### 2.7. The Artist Deposit Ledger

Every artist carries a running deposit balance, `deposit_credit_cents`, which starts at zero. Cashier-style top-ups posted by an `OpsManager` or `TourManager` increase the balance by a supplied `amount_cents`. When a reservation is sourced, a hold computed from the sourced model's replacement value is blocked on the artist: the amount is recorded on the reservation as `deposit_held_cents` and debited from the artist's balance in the same operation. Cancelling a sourced reservation credits its hold back to the balance; settling a reservation releases its hold diminished by any paid damage charges attached to that reservation. In both cases the reservation's `deposit_held_cents` field is zeroed once the hold is released.

Artists whose `deposit_waived` flag is set compute a hold of zero on every reservation, regardless of gear value. The ledger is never allowed to dip below zero: if an artist's balance — after accounting for the deposits currently held across that artist's reservations — cannot cover a new hold, the operation that would create the hold is rejected with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402). The same fiscal gate is re-evaluated in aggregate at tour activation.

### 2.8. Gear Serviceability Gates

Two counters govern whether a physical unit may be rented. `condition_score` runs from 0 to 100, starts at 100 on a newly registered unit, and is decremented by damage assessments. `rental_days_since_service` starts at 0 and accumulates the rental days of each completed reservation until a completed maintenance visit resets it. A unit may only be sourced when its condition score is at least 40 and its service-day count is below 30. At check-in, a stricter projection applies: when the days of the returning reservation would bring the accumulated count to 30 or more — exactly 30 included — the unit is routed to maintenance rather than back to the available pool, and the same routing applies whenever the condition score has fallen below 40 (a score of exactly 40 passes).

A third derived flag, `flight_case_required`, is read off the catalog model's weight class: it is true for `HEAVY` and `OVERSIZE` models and false for `HAND_CARRY` and `STANDARD` ones. Units requiring a case cannot be loaded onto a truck without one.

### 2.9. Cascades and Hierarchical Consistency

State changes propagate. Cancelling a tour reaches down through its stops, their rider lines, and the reservations sourced for those lines, releasing any physical units the cascade unties. Mutations also propagate upward: adding a stop to a tour adjusts the tour's `stop_count` and bumps the tour's own `version`; every rider-line mutation on a stop advances that stop's `rider_revision`; booking, loading, or cancelling a shipment line recomputes the parent leg's `booked_weight_kg` and `tech_labor_minutes`. Each resource touched by such a cascade or reconciliation — named in the request or not — observes the versioning contract of §2.4.

Derived fields are always reconciled eagerly, at the moment the underlying event occurs, never lazily at read time. The server may therefore transition or adjust resources without an explicit client request on that specific resource whenever a cascade rule or a gate fires.

### 2.10. Optimistic Concurrency Control

Three write operations are guarded against stale client reads. Each requires a non-optional input field carrying the version the client last observed on the entity the guard is pinned to, and each rejects a mismatched value with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here take no version field at all.

- Activating a tour requires `expected_tour_version` matching the tour's current `version`. The version may have advanced because another writer added a stop or toggled the artist's deposit terms, changing the activation precondition basis — the stop count and the deposit gate — since the client last read the tour.
- Approving a rider-line substitution requires `expected_tour_stop_rider_revision` matching the parent stop's current `rider_revision`. That revision advances by one on rider-line creation, sourcing, cross-rental fulfillment, and substitution proposal and rejection, and by two on substitution approval — once for the swap's reservation creation and once for the line landing `APPROVED` — while marking a line fulfilled, marking it shorted, cancelling it, and cascade cancellations of lines do not advance it; a stale approval could otherwise bless a substitution whose sibling lines have since changed underneath it.
- Settling a reservation requires `expected_reservation_version` matching the reservation's current `version`. The version advances when a damage claim is filed against the reservation or when check-in adjusts the unit, so a stale settle would compute the final fee against an obsolete inspection basis.

### 2.11. Nested Path Resolution and Validation Order

When an endpoint path contains multiple resource identifiers, existence is validated left to right — a tour before its stop, a stop before its rider line — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource.

Beyond path resolution, every request walks a fixed sequence of gates, and the first gate that fails determines the error returned:

1. Authentication — missing or malformed `X-User-Role` or `X-User-ID` headers, or an undeclared role value, fail with `ERR_UNAUTHENTICATED` (HTTP 401).
2. Authorization — a role not permitted for the endpoint per the access matrix fails with `ERR_UNAUTHORIZED` (HTTP 403).
3. Existence — path-templated resources fail left to right with `ERR_NOT_FOUND` (HTTP 404).
4. State legality — a target whose current state does not permit the requested transition fails with `ERR_INVALID_STATE` (HTTP 409).
5. Stale versions — on the three guarded writes of §2.10, a mismatched expected version fails with `ERR_STALE_VERSION` (HTTP 412).
6. Segregation of duties — on damage assessment only, an assessor who originally filed the claim fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).
7. Unit serviceability — sourcing a unit below the condition or service-day floors fails with `ERR_UNIT_NOT_SERVICEABLE` (HTTP 422).
8. Availability — a window overlap or transit-buffer collision with no eligible vendor fallback fails with `ERR_GEAR_UNAVAILABLE` (HTTP 409).
9. Window sanity — a venue date outside the tour window, a load-in that misses the evening cutoff, or a reservation whose start does not precede its end fails with `ERR_INVALID_WINDOW` (HTTP 422).
10. Substitution allowlist — a substitute model absent from the requested model's declared list fails with `ERR_SUBSTITUTION_NOT_ALLOWED` (HTTP 422).
11. Capacity — a load that would push a leg's booked weight above its capacity fails with `ERR_CAPACITY_EXCEEDED` (HTTP 422).
12. Flight cases — a unit requiring a case without an available, adequately sized one fails with `ERR_FLIGHT_CASE_REQUIRED` (HTTP 422).
13. Vendor eligibility — a vendor that is not approved, does not cover the city, or a representative of a different vendor fails with `ERR_VENDOR_NOT_ELIGIBLE` (HTTP 422).
14. Deposit headroom — an artist balance that cannot cover the hold fails with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402).
15. Insurance — activation without a policy reference on a non-waived artist fails with `ERR_INSURANCE_REQUIRED` (HTTP 422).
16. Request shape — missing required fields, wrongly typed values, enum values outside their declared sets, quantities below one, or unparseable dates fail with `ERR_INVALID_REQUEST` (HTTP 400). This gate is deliberately last: a request that violates both a business rule and a shape constraint surfaces the business error. In practice a handler consults its request body only after the existence and state-legality gates have passed, so those business errors always precede any field-shape error; among the remaining gates, a field-presence or type error surfaces the moment the handler first reads that field, which can precede business gates that depend on other fields.

Where several of these gates guard the same operation, they fire in the order above — so, for example, sourcing validates its start-before-end window sanity as soon as the window is parsed, before candidate selection, then evaluates the serviceability floor before the availability window, and deposit headroom after all three; tour activation evaluates the deposit aggregate before the insurance requirement; and shipment loading evaluates weight capacity before flight-case adequacy.

## 3. Business Logic & Workflows

### 3.1. Artist Onboarding, Deposit Top-Ups, and Risk

An `OpsManager` registers an artist with a `legal_name` — the contracting name used on paperwork — and optionally a commercial `tier` of `STANDARD`, `PREMIUM`, or `PLATINUM` (defaulting to `STANDARD` when omitted) and a `deposit_waived` flag (defaulting to false). Deposit waiver is the customary privilege of `PLATINUM` accounts: when the flag is true, every required deposit computes to zero. The same two fields remain mutable after registration, and updating either bumps the artist's `version`; a PATCH that names neither field changes nothing and does not bump the version. The artist roster can be listed with a `tier` filter.

New artists start with a `deposit_credit_cents` balance of zero and a `risk_score` of zero. Because damage deposits are prepaid in the real world, an `OpsManager` or `TourManager` can post a deposit top-up carrying an `amount_cents`, which increases the balance by exactly that amount and bumps the artist's `version`; `amount_cents` is a required integer and no sign constraint is enforced, so a negative amount reduces the balance. Fetching an artist always exposes the current balance alongside the computed `risk_score`.

The risk score condenses the artist's damage history into an integer from 0 to 100. It is recomputed from scratch — never adjusted incrementally — each time one of the artist's claims is assessed and again when one is marked paid, and it draws on every claim attached to the artist's reservations whose status is `ASSESSED`, `CHARGED`, `DISPUTED`, or `PAID` and whose assessment falls within the trailing 365 days. Each qualifying claim contributes a severity weight — 2 for `COSMETIC`, 5 for `MINOR`, 12 for `MAJOR`, and 30 for `TOTAL_LOSS` — and that weight is doubled when the assessment is no more than 90 days old; assessments between 91 and 365 days old contribute their weight undoubled. The raw total is capped at 100. The score matters downstream because it gates the insurance surcharge in both the quote and the settlement, as §3.3 and §3.9 describe.

### 3.2. Building the Tour: Stops, Riders, and Activation

A `TourManager` opens a tour by naming the headlining artist via `artist_id` — an unknown artist fails with `ERR_NOT_FOUND` (HTTP 404) — giving the tour a display `name`, and bounding it with a `start_date` and an `end_date` that must fall on or after the start, with an earlier end date failing with `ERR_INVALID_WINDOW` (HTTP 422). An `insurance_policy_id` — the external policy reference — may be supplied at creation or left for later. A new tour is `DRAFT` with a `stop_count` of zero, and both of its fee projections, `projected_rental_fee_cents` and `final_settlement_cents`, start at zero.

Stops give the tour its geography. Adding one records the `city_code` — an IATA-style code such as LAX, NYC, or NASH — the `venue_date` of the show, and the `load_in_ts` timestamp. The venue date must lie within the tour's start and end dates inclusive, and the load-in must fall strictly before the 20:00 cutoff on the venue date; violating either constraint is rejected with `ERR_INVALID_WINDOW` (HTTP 422). Each stop is born `PLANNED`. Because the stop list feeds the activation gate, adding a stop also bumps the parent tour's `version` and reconciles `stop_count`, which the server keeps aligned as stops are added or removed; `stop_count` counts every stop ever added to the tour — cancelled stops included — so cancelling a stop changes neither `stop_count` nor the tour's `version`. A `TourManager` may cancel a stop while it is still `PLANNED`; the cancellation cascades to the stop's rider lines in `REQUESTED`, `SOURCED`, `SUBSTITUTION_PENDING`, or `APPROVED` — each moves to `CANCELLED` — and to reservations sourced for the stop in `DRAFT` or `SOURCED`, which are cancelled with their units released from `RESERVED` back to `AVAILABLE`. The stop's own `version` increments on the transition.

Rider lines express what the artist demands on a given night. Creating one under a stop supplies the `gear_model_id` of the requested model — an unknown model, or an unknown `substitution_of_line_id`, fails with `ERR_NOT_FOUND` (HTTP 404) — and a `quantity` of at least one — a request with a quantity below one, a missing field, or a mistyped value fails shape validation with `ERR_INVALID_REQUEST` — and optionally a `substitution_of_line_id` paired with a free-text `substitution_reason` when the new line explicitly replaces an earlier one. Every rider line records its owning stop as `tour_stop_id`. A fresh line is `REQUESTED`, and its creation advances the parent stop's `rider_revision` — which starts at zero on a new stop — and bumps the stop's `version`; the later line mutations that advance the revision are exactly the ones enumerated in §2.10. The revision counter is the coordination point that substitution approvals synchronize against, as §3.4 details. Rider lines can be listed per stop or across the whole operation, with the cross-stop listing filterable by `gear_model_id`, `fulfilled_by_reservation_id`, `substitution_of_line_id`, or `status`.

Activation is the tour's point of no return and belongs to the `TourManager`. The request must carry `expected_tour_version` per §2.10, and the preconditions are evaluated in a fixed order — the `DRAFT` state check, then the presence and match of `expected_tour_version`, then the requirement of at least one stop in `PLANNED`, and then two fiscal gates: first the deposit aggregate — the holds across the artist's sourced reservations must fit within the artist's deposit balance, failing with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402) — and then the insurance requirement, which demands a non-null `insurance_policy_id` whenever the artist's `deposit_waived` is false, failing with `ERR_INSURANCE_REQUIRED` (HTTP 422). A successful activation moves the tour to `ACTIVE`, increments its `version`, and recomputes `projected_rental_fee_cents` as the forward-looking quote total across the tour's `DRAFT` and `SOURCED` reservation lines. Because a not-yet-fulfilled cross-rental reservation carries no quote (its `quoted_fee_cents` is null), this recompute cannot absorb one: activating while such a reservation exists on the tour fails with `ERR_INVALID_REQUEST` (HTTP 400), and since the status flip happens before the recompute, the tour is left `ACTIVE` with its `version` advanced despite the error response. Tours can be listed filtered by `artist_id` or `status`.

### 3.3. Sourcing Gear: The Availability Window and the Quote

The catalog separates models from physical units. An `OpsManager` registers a model with a catalog-unique `sku` (a collision is rejected with `ERR_DUPLICATE`, HTTP 409), a `category` of `GUITAR`, `BASS`, `DRUMS`, `KEYS`, `AMP`, `PA`, or `BACKLINE_MISC`, a non-negative `daily_rate_cents`, a strictly positive `replacement_value_cents` that caps damage claims and drives the deposit tiers, a `weight_class` of `HAND_CARRY`, `STANDARD`, `HEAVY`, or `OVERSIZE`, and an ordered `substitute_model_ids` array in which earlier entries are the preferred substitutes; when the array is omitted it defaults to empty, meaning the model accepts no substitutes at all. Models are listed with an optional `category` filter.

Physical units sit beneath a model: registering one takes the `gear_model_id`, a fleet-unique `serial_number` (also guarded by `ERR_DUPLICATE`), and the `home_city_code` of the depot where the unit is based. A unit begins `AVAILABLE` with a `condition_score` of 100, zero `rental_days_since_service`, and a null `active_reservation_id`. The fleet listing filters by `gear_model_id`, `home_city_code`, `status`, or `active_reservation_id`, and a computed availability read answers, for a queried `start_date` and `end_date` — both query parameters are required, and a missing one fails with `ERR_INVALID_REQUEST` (HTTP 400) — whether the unit is free: an `available` flag plus the `conflicting_reservation_ids` that stand in the way. The read is purely conflict-based; the unit's own status and condition are not consulted.

Sourcing is the act that turns a `REQUESTED` rider line into a reserved physical unit, and it belongs to the `LogisticsCoordinator`. The parent stop must still be `PLANNED`, and the payload fixes the commercial window: `origin_city_code` where the gear is handed over, `dest_city_code` where it comes back, and `start_date` and `end_date` bounding the rental. The end date must fall strictly after the start date, or the request fails with `ERR_INVALID_WINDOW`. Candidate selection then runs as constraint propagation over the fleet: a candidate must belong to the requested model and not be out of service — only units in `MAINTENANCE`, `QUARANTINED`, or `RETIRED` are excluded at this step; a unit already committed to another reservation stays in the pool, and it is the conflict clause below that excludes it — carry a `condition_score` of at least 40 and a `rental_days_since_service` below 30 — a candidate that cannot meet those floors is reported as `ERR_UNIT_NOT_SERVICEABLE` (HTTP 422) — and have no conflicting reservation, where a conflict is any reservation in `SOURCED`, `DISPATCHED`, or `DELIVERED` whose half-open window overlaps the requested one (windows that merely touch, an existing reservation ending exactly when the requested one begins, do not conflict — so the same physical unit may be sourced for back-to-back adjacent windows). A unit whose `home_city_code` differs from the stop's city needs a one-day transit buffer, so its effective window begins one day earlier than requested. Surviving candidates are ranked by preference: units based in the stop's own city first, then fewest rental days since service, then earliest `created_at`; ties break on creation time, never on identifier.

A successful source creates the reservation — recording the owning `tour_id` and `rider_line_id`, with the chosen `gear_unit_id` assigned — and drives it from `DRAFT` straight to `SOURCED`; the rider line moves to `SOURCED` with its `fulfilled_by_reservation_id` pointing at the new reservation, the unit flips from `AVAILABLE` to `RESERVED` with its `active_reservation_id` set, and the stop's `rider_revision` advances. The reservation also carries the window's `origin_city_code`, `dest_city_code`, `start_date`, and `end_date`, a `settled_fee_cents` that stays null until settlement, and an `is_cross_rental` flag, and the source call returns the reservation object with 200 OK on both the in-house and the cross-rental path. Two money figures are computed in the same breath. The provisional `quoted_fee_cents` is forward-looking: the rental length is the whole-day count of the half-open window, minimum one day; the base is that count times the model's `daily_rate_cents` (or the vendor's daily rate for a cross-rental); cartage applies a zone multiplier over the origin–destination pair — 1.00 when both cities are the same, which yields zero cartage; 1.10 when both fall inside one region, the regions being the West Coast set of LAX, SFO, SEA, and PDX, the Northeast set of NYC, BOS, PHI, and DC, and the Mid-South set of NASH, ATL, and MEM; and 1.25 for any cross-region pair — and the cartage component is the base times the multiplier's excess over one, rounded half-up to whole cents; insurance is eight percent of the base, rounded half-up to whole cents, charged only when the artist's `risk_score` at quote time is 50 or higher, the threshold being inclusive. The quote is the sum of base, cartage, and insurance, with each component rounded to whole cents before summing — never after.

The deposit hold, stored as `deposit_held_cents`, follows the tiered rule of §2.7 against the model's `replacement_value_cents`: twenty percent of the first 200,000 cents of replacement value — the first two thousand dollars — plus fifteen percent of the next 300,000 cents (the band from two thousand to five thousand dollars), plus ten percent of any value beyond 500,000 cents. The tiered sum is rounded half-up to whole cents exactly once at the end, a deliberate contrast with the quote's per-component rounding. A replacement value of exactly 200,000 cents therefore holds 40,000 cents, and exactly 500,000 cents holds 85,000 cents. A waived artist holds zero. The hold is debited from the artist's balance at sourcing; when the balance cannot cover it, the source fails with `ERR_DEPOSIT_INSUFFICIENT`. Reservations may be listed filtered by `tour_id`, `gear_unit_id`, `rider_line_id`, or `status`.

### 3.4. Substitutions and Shortages

When the reserved unit will not do — a artist preference change, a quiet downgrade — the `LogisticsCoordinator` proposes a substitution against a `SOURCED` line, supplying a `substitute_gear_model_id` and a `substitution_reason`, both required, with an unknown substitute model failing with `ERR_NOT_FOUND` (HTTP 404). Two checks guard the proposal in the order fixed by §2.11: the availability selector — run over the linked reservation's existing window and the stop's city — must yield a candidate of the substitute model, with a collision surfacing as `ERR_GEAR_UNAVAILABLE`, and the substitute must appear in the originally requested model's `substitute_model_ids`, with an unlisted model surfacing as `ERR_SUBSTITUTION_NOT_ALLOWED` (HTTP 422). A clean proposal moves the line to `SUBSTITUTION_PENDING` and advances the stop's `rider_revision`.

Approval belongs to the `TourManager` and is OCC-guarded: the request must carry `expected_tour_stop_rider_revision` matching the stop's current `rider_revision`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Approval is a swap executed as a paired cancel-and-create. The old reservation transitions from `SOURCED` to `CANCELLED`; its unit is released from `RESERVED` back to `AVAILABLE`; and its held deposit is credited back to the artist. A new reservation is created against a unit of the substitute model, that unit moves from `AVAILABLE` to `RESERVED`, and a fresh quote and hold are computed and debited — the net deposit delta between the released hold and the new hold being what the artist's ledger ultimately reconciles. The create half re-runs the availability and deposit gates at approval time, and a failure there (`ERR_GEAR_UNAVAILABLE` or `ERR_DEPOSIT_INSUFFICIENT`) leaves the old reservation's cancellation and compensation in effect with the line still `SUBSTITUTION_PENDING`. The line lands in `APPROVED` with its `version` incremented, its `gear_model_id` is rewritten to the substitute model — so later settlement prices off the substitute — and the swap advances the stop's `rider_revision` twice per §2.10. Rejection, also a `TourManager` call, loops the line from `SUBSTITUTION_PENDING` back to `SOURCED` and advances the stop's `rider_revision`; the cycle from `SOURCED` through `SUBSTITUTION_PENDING` and back to `SOURCED` is permitted and may repeat.

Once gear is physically on site, a `WarehouseTech` marks the line fulfilled: from either `SOURCED` or `APPROVED`, provided the linked reservation has reached `DELIVERED`, the line moves to `FULFILLED`.

When nothing can cover the demand — the availability selector, run over the stop's single `venue_date` day, returns an empty candidate set and no approved partner vendor covers the stop's city — the `LogisticsCoordinator` marks the line `SHORTED` directly from `REQUESTED`; if a candidate does exist or an approved vendor does cover the city, the call fails state legality with `ERR_INVALID_STATE` (HTTP 409). Shorting grants the tour a credit against its forward-looking projection: the requested model's `daily_rate_cents` multiplied by the line's `quantity` for a single stop day is subtracted from `projected_rental_fee_cents`, with the result floored at zero.

A `TourManager` may cancel a rider line from any of `REQUESTED`, `SOURCED`, `SUBSTITUTION_PENDING`, or `APPROVED`. When a linked reservation exists in `DRAFT` or `SOURCED`, the cancellation takes the reservation down with it and releases its unit — `RESERVED` back to `AVAILABLE` — with the held deposit credited back to the artist.

### 3.5. Cartage: Shipments, Flight Cases, and Load Planning

Gear moves between cities on cartage legs. A `LogisticsCoordinator` creates a leg with the owning `tour_id`, the `from_city_code` and `to_city_code`, the planned `ship_date`, and a strictly positive `capacity_kg`; the owning tour must exist, but its status is not consulted. A leg is born `PLANNED` with `booked_weight_kg` and `tech_labor_minutes` at zero; the shipment listing filters by `tour_id` or `status`.

Booking a unit onto the leg creates a shipment line recording the parent `shipment_id`, the `gear_unit_id`, a non-negative declared `weight_kg` including the case, and non-negative `labor_minutes` for the technicians loading and unloading it — both required — and booking is accepted whatever the leg's current status; a `flight_case_id` accompanies the line whenever the unit requires a case. Two constraints are enforced both at booking and again at loading, in the §2.11 order: capacity first — the leg's booked weight may reach but never exceed `capacity_kg`, and a line that would push it over is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422) — and case adequacy second, where a unit whose `flight_case_required` is true must name an `AVAILABLE` case whose `size_class` is adequate for the unit's weight class, failing with `ERR_FLIGHT_CASE_REQUIRED` (HTTP 422). Adequacy follows the size ladder `SMALL` < `MEDIUM` < `LARGE` < `TRUNK`: a `HEAVY` unit needs at least a `LARGE` case and an `OVERSIZE` unit needs a `TRUNK`; a `flight_case_id` named for a unit that does not require one is recorded on the line but never validated or flipped to `ASSIGNED`. Both aggregates reconcile on every line mutation: `booked_weight_kg` sums the `weight_kg` of non-cancelled lines, and `tech_labor_minutes` sums their `labor_minutes`.

Cases are first-class inventory. An `OpsManager` registers one with a painted-on `case_code` (unique, with collisions rejected as `ERR_DUPLICATE`), a `size_class` of `SMALL`, `MEDIUM`, `LARGE`, or `TRUNK`, and a `home_city_code`; a case starts `AVAILABLE`. The case registry filters by `home_city_code` or `status`, and per-unit and per-case reads list the shipment lines each is booked onto.

Loading is choreographed. The coordinator opens the leg with a transition from `PLANNED` to `LOADING`; then a `WarehouseTech` loads each `BOOKED` line, which re-checks capacity and case adequacy, flips the assigned case from `AVAILABLE` to `ASSIGNED`, recomputes the leg's aggregates, and lands the line in `LOADED`. Departure — `LOADING` to `IN_TRANSIT` — requires every line to be `LOADED` or `CANCELLED` and re-validates that booked weight stays within capacity; it moves each loaded line's unit from `OUT_ON_RENTAL` to `IN_TRANSIT` and each assigned case from `ASSIGNED` to `IN_TRANSIT`. Arrival — `IN_TRANSIT` to `DELIVERED` — moves every non-cancelled line to `DELIVERED`, returns each unit from `IN_TRANSIT` to `OUT_ON_RENTAL`, and releases each case from `IN_TRANSIT` back to `AVAILABLE` with its `home_city_code` rewritten to the leg's destination city. A delivered leg is eventually closed, `DELIVERED` to `CLOSED`. Cancellation is possible from `PLANNED` or `LOADING` so long as no line has reached `LOADED`: each `BOOKED` line is cancelled, each assigned case is released back to `AVAILABLE`, and the aggregates reconcile. A single line can also be cancelled from `BOOKED` on its own, which recomputes the leg's booked weight.

Cases need upkeep too: a `WarehouseTech` sends an `AVAILABLE` case to maintenance and returns it to service when done. An `OpsManager` retires an `AVAILABLE` case only when no shipment line in `BOOKED` or `LOADED` references it.

### 3.6. On the Ground: Dispatch, Check-In, and the Maintenance Gate

With the tour `ACTIVE`, the `LogisticsCoordinator` dispatches a `SOURCED` reservation — the tour must have at least one leg in `PLANNED` or `LOADING` bound for the reservation's `dest_city_code` — moving it to `DISPATCHED` and flipping the reserved unit from `RESERVED` to `OUT_ON_RENTAL`. Cross-rental reservations skip the unit flip because they hold no in-house unit. Arrival at the venue is recorded as `DISPATCHED` to `DELIVERED`.

The stop itself advances in step. Staging — `PLANNED` to `GEAR_STAGED`, a `LogisticsCoordinator` action — demands an `ACTIVE` parent tour, every rider line of the stop resolved to `SOURCED`, `APPROVED`, `FULFILLED`, or `CANCELLED` with nothing left in `REQUESTED` or `SUBSTITUTION_PENDING`, and at least one delivered cartage leg of the same tour bound for the stop's `city_code`. Declaring the show ready — `GEAR_STAGED` to `SHOW_READY`, a `WarehouseTech` action — requires every rider line to be `FULFILLED` or `CANCELLED`. Load-out, also a `WarehouseTech` action, moves the stop from `SHOW_READY` to `LOADED_OUT` and sweeps every `DELIVERED` reservation feeding the stop into `RETURNED`, running the check-in cascade on each affected unit.

Check-in is where the fleet pays its wear bill. Whether triggered by load-out — which stamps each swept reservation's check-in with the logical clock's current time — or recorded directly by a `WarehouseTech` with a required `checked_in_at` timestamp, the transition from `DELIVERED` to `RETURNED` runs the maintenance gate on the unit: the gate projects the unit's `rental_days_since_service` plus the days of the returning reservation, and when that projection reaches 30 — exactly 30 included — or the unit's `condition_score` has fallen below 40, the unit moves from `OUT_ON_RENTAL` (or `IN_TRANSIT`, if a claim or a leg left it there) to `MAINTENANCE` instead of back to the pool, and a maintenance ticket is opened with `opened_reason` `SCHEDULED_CYCLE` when the day threshold tripped or `CONDITION_THRESHOLD` when the condition did — when both trip, the day threshold wins and the reason is `SCHEDULED_CYCLE`. The forced routing clears the unit's `active_reservation_id` but does not add the reservation's days to `rental_days_since_service`, and if the unit is in any status other than `OUT_ON_RENTAL` or `IN_TRANSIT` the reservation still lands `RETURNED` with the unit left untouched. A clean return moves the unit from `OUT_ON_RENTAL` to `AVAILABLE`, adds the reservation's rental days to its `rental_days_since_service`, and clears its `active_reservation_id`.

Tickets may also be opened manually by a `WarehouseTech` or an `OpsManager` with a `gear_unit_id` and an `opened_reason` of `SCHEDULED_CYCLE`, `DAMAGE_REPAIR`, `CONDITION_THRESHOLD`, or `POST_FLIGHT_INSPECTION`; opening one against an `AVAILABLE` unit pulls it into `MAINTENANCE`. The ticket's `opened_at` stamps the moment it enters `OPEN`. From there a `WarehouseTech` starts work — `OPEN` to `IN_PROGRESS` — parks it waiting for parts — `IN_PROGRESS` to `AWAITING_PARTS` — and resumes it, with the loop between `IN_PROGRESS` and `AWAITING_PARTS` permitted to repeat. Completion — `IN_PROGRESS` to `COMPLETED` — requires the technician to supply the actual `service_cost_cents` (non-negative) and a `condition_delta` between 0 and 100: the unit's `condition_score` climbs by the delta, capped so it never exceeds 100, its `rental_days_since_service` resets to zero, its `active_reservation_id` clears, the unit returns from `MAINTENANCE` to `AVAILABLE`, and the ticket's `closed_at` is stamped. An `OpsManager` may cancel a ticket from `OPEN` or `AWAITING_PARTS`, moving it to `CANCELLED` and likewise stamping `closed_at`. Tickets are listed with `gear_unit_id` or `status` filters.

Retirement is the fleet's exit door: an `OpsManager` retires a unit from `AVAILABLE` to `RETIRED`, permitted only while no reservation in `DRAFT`, `SOURCED`, `DISPATCHED`, or `DELIVERED` references it.

### 3.7. Damage Claims and Segregation of Duties

Inspection closes the loop on a returned rental. A `WarehouseTech` inspecting a `RETURNED` reservation reports `damage_present`; when damage is found, the same request atomically files a damage claim — carrying the `assessed_severity` bucket of `COSMETIC`, `MINOR`, `MAJOR`, or `TOTAL_LOSS` and the assessor's non-negative `repair_estimate_cents`, both required whenever `damage_present` is true, the estimate being ignored for `TOTAL_LOSS` since that bucket charges replacement value — and the reservation moves to `INSPECTED` while the damaged unit is quarantined: `OUT_ON_RENTAL`, `IN_TRANSIT`, or `AVAILABLE` to `QUARANTINED`. The claim is born `FILED` with its `filed_by_user_id` stamped from the inspecting technician's `X-User-ID`; that stamp is the segregation-of-duties anchor. The claim also records the reservation's `gear_unit_id` (null for cross-rentals) alongside its `reservation_line_id`, and an `assessed_at_dt` field — null at filing, stamped with the logical-clock time at assessment — that anchors the recency windows of §3.1.

Assessment is an `OpsManager` act, and the filer may not assess their own claim: when the acting user's `X-User-ID` matches the claim's `filed_by_user_id`, the assessment is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Assessment moves the claim from `FILED` to `ASSESSED` and does three things at once: the unit's `condition_score` drops by severity — 5 points for `COSMETIC`, 15 for `MINOR`, 35 for `MAJOR`, and 100 for `TOTAL_LOSS` — never below zero; the artist's `risk_score` is recomputed per §3.1; and for `MAJOR` or `TOTAL_LOSS` damage the `QUARANTINED` unit moves on to `MAINTENANCE` with a `DAMAGE_REPAIR` ticket opened against it.

Charging turns assessment into money, and the actor depends on the path: from `ASSESSED`, a `TourManager` charges the claim; from `DISPUTED`, only an `OpsManager` may charge it — and the dispute changes nothing about the formula. The `charge_cents` figure is the repair estimate for ordinary severities, or the model's full `replacement_value_cents` for `TOTAL_LOSS`. The charge draws first against the linked reservation's `deposit_held_cents`; only the portion strictly exceeding the hold is billed directly as an overage, so a charge exactly equal to the hold leaves no overage at all.

A `TourManager` disputes an `ASSESSED` claim, moving it to `DISPUTED`; an `OpsManager` waives a claim from either `ASSESSED` or `DISPUTED`, moving it to `WAIVED`. Once charged, a `TourManager` marks the claim `PAID`, which records cash receipt — the paid amount itself is deducted from the artist's deposit balance when the reservation settles, as §3.9 describes. Claims can be listed filtered by `reservation_line_id`, `gear_unit_id`, or `status`.

### 3.8. Partner Vendors and the Cross-Rental Path

The house pool does not always cover a city, so the company keeps partner vendors on file. An `OpsManager` onboards one with a `name`, the array of `city_codes` the vendor can supply, and a `commission_bps` rate in basis points — 100 basis points equal one percent — between 0 and 3,000. Vendors onboard as `PENDING` and are approved to `APPROVED`; suspension moves an `APPROVED` vendor to `SUSPENDED` and cancels every cross-rental request of that vendor still sitting in `REQUESTED` or `ACCEPTED`; reinstatement from `SUSPENDED` back to `APPROVED` is permitted and the cycle may repeat.

Cross-rental enters the sourcing flow in two ways. A `LogisticsCoordinator` may source a line with `use_cross_rental` set and a `partner_vendor_id` plus the vendor's daily rate `vendor_rate_cents_per_day` attached — both required, with an unknown vendor failing with `ERR_NOT_FOUND` (HTTP 404) — : this creates the reservation in `DRAFT` — holding no in-house unit, with no quote or deposit hold computed yet — opens a cross-rental request in `REQUESTED` against it carrying the named vendor, the line's model, and the rate, and leaves the rider line `REQUESTED`. Alternatively, the coordinator may open a cross-rental request directly against a reservation that could not be sourced in-house, naming the `reservation_line_id`, the `partner_vendor_id`, the `gear_model_id` sought, and the rate; the reservation's current state is not checked when the request is opened. Either way, the vendor must be `APPROVED` and its `city_codes` must cover the stop's city, or the request fails with `ERR_VENDOR_NOT_ELIGIBLE` (HTTP 422). The reservation behind a cross-rental is created holding no in-house unit.

Negotiation belongs to the vendor's representative, and ownership is enforced through the identity rule of §2.1: only a `PartnerVendorRep` whose `X-User-ID` matches the request's `partner_vendor_id` may act, with a rep of a different vendor rejected as `ERR_VENDOR_NOT_ELIGIBLE`, and the vendor itself must still be `APPROVED`. Acceptance moves the request from `REQUESTED` to `ACCEPTED`; rejection ends it at `REJECTED`. Fulfillment — `ACCEPTED` to `FULFILLED` — marks the linked reservation's `is_cross_rental` flag true (it is false on every ordinary in-house reservation) and drives the reservation from `DRAFT` to `SOURCED` without consuming an in-house unit; the provisional quote is computed at this moment under the §3.3 rule with the vendor's daily rate as the base, the deposit hold is still computed under the tiered rule of §2.7 — including its `deposit_waived` clause, so a waived artist's hold is zero — and blocked against the artist's balance, failing with `ERR_DEPOSIT_INSUFFICIENT` (HTTP 402) when the balance cannot cover it, and the linked rider line moves from `REQUESTED` to `SOURCED` with its `fulfilled_by_reservation_id` set, advancing the stop's `rider_revision`. Once the linked reservation itself has settled — a settle attempted before that fails state legality with `ERR_INVALID_STATE` (HTTP 409) — an `OpsManager` settles the cross-rental — `FULFILLED` to `SETTLED` — which computes the `commission_cents` owed by the vendor: the vendor's revenue for the window — the `vendor_rate_cents_per_day` times the reservation's day count — multiplied by the vendor's `commission_bps` current at settle time and divided by ten thousand, rounded half-up to whole cents; a zero rate yields zero commission and a 3,000-basis-point rate yields thirty percent. The coordinator may also cancel a request from `REQUESTED` or `ACCEPTED`, moving it to `CANCELLED`; cancelling a request — directly or through vendor suspension — leaves the linked reservation untouched. The request board filters by `reservation_line_id`, `partner_vendor_id`, `gear_model_id`, or `status`, and vendors are listed with a `status` filter.

### 3.9. Settlement and Tour Completion

Settlement converts a returned, inspected rental into final money, moving the reservation from `INSPECTED` to `SETTLED`. A `TourManager` performs it with `expected_reservation_version` in hand per §2.10 — a stale value fails with `ERR_STALE_VERSION` — and no damage claim on the reservation may still sit in `FILED`, `ASSESSED`, or `DISPUTED`, or the transition fails state legality with `ERR_INVALID_STATE` (HTTP 409). The chronological settlement stored in `settled_fee_cents` keeps the quote's base, day count, and cartage rules and diverges in three ways. Lateness is priced from reality: each started 24-hour block between the `end_date` and the actual `checked_in_at` adds one day billed at one-and-a-half times the daily base rate, with that inflated day rate rounded half-up to whole cents once and then multiplied by the block count — an on-time return adds nothing. Insurance is evaluated against the artist's `risk_score` at settle time rather than quote time, so whenever the score has crossed the inclusive threshold of 50 in either direction between the two moments, quote and settlement differ for otherwise identical inputs. And if the rider line was ever marked `SHORTED`, a credit equal to the entire base is subtracted. The total — base plus cartage plus insurance plus late fees minus the shortage credit — is floored at zero so a net credit never produces a negative charge. Settlement then releases the reservation's `deposit_held_cents` back to the artist's balance, diminished by any `PAID` damage `charge_cents` on that reservation.

Stops close behind their reservations: a `TourManager` settles a `LOADED_OUT` stop once every reservation feeding it is `SETTLED` or `CANCELLED`, moving it to `SETTLED`.

Completing the tour is the final act and belongs to the `TourManager`. Every stop must be `SETTLED` or `CANCELLED`, every reservation must be `SETTLED` or `CANCELLED`, and no damage claim attached to the tour's reservation lines may remain in `FILED`, `ASSESSED`, or `DISPUTED`. Completion moves the tour from `ACTIVE` to `COMPLETED`, computes `final_settlement_cents` as the chronological settlement total across the tour's delivered and returned lines net of credits, and releases any unforfeited artist deposit through the deposit-hold reconciliation of §2.7.

Cancellation unwinds a tour from either side of activation, and the actor depends on where the tour stands. From `DRAFT`, a `TourManager` cancels: every `PLANNED` stop moves to `CANCELLED`, every rider line of those stops in `REQUESTED`, `SOURCED`, `SUBSTITUTION_PENDING`, or `APPROVED` moves to `CANCELLED`, and every reservation still in `DRAFT` or `SOURCED` moves to `CANCELLED` — each `SOURCED` reservation released with the standard compensation, its unit returned from `RESERVED` to `AVAILABLE` with `active_reservation_id` cleared and its held deposit credited back to the artist. From `ACTIVE`, only an `OpsManager` may cancel, and only while no reservation of the tour is `DISPATCHED` or `DELIVERED`: every non-terminal stop is cancelled, and each `SOURCED` reservation is cancelled with the standard compensation — its unit released from `RESERVED` to `AVAILABLE` with `active_reservation_id` cleared and its held deposit credited back. Unit release under an active-tour cancellation re-runs the maintenance gate per released unit, so a unit already at 30 or more rental days since service enters `MAINTENANCE` with a ticket opened rather than returning to the pool. Both paths increment the tour's `version`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource — an artist, a tour, a stop, a rider line, a catalog model, a unit, a shipment or a line booked onto it, a flight case, a vendor, a cross-rental request, or a maintenance ticket — return `201 Created`. Operations that modify an existing resource or drive a state transition — including every action endpoint below — return `200 OK`. Readers should refer back to §3 for the request payloads, preconditions, and side effects behind each row.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/backline/_clock/set_current_utc` | Set the server's logical clock | OpsManager |
| POST | `/backline/artists` | Register an artist | OpsManager |
| POST | `/backline/artists/{id}/deposit-topups` | Post a deposit top-up to the artist's balance | OpsManager, TourManager |
| GET | `/backline/artists/{id}` | Fetch an artist with computed deposit balance and risk score | OpsManager, TourManager, LogisticsCoordinator |
| GET | `/backline/artists` | List artists, optionally filtered by tier | OpsManager, TourManager, LogisticsCoordinator |
| PATCH | `/backline/artists/{id}` | Update an artist's tier or deposit waiver | OpsManager |
| POST | `/backline/tours` | Create a tour in DRAFT | TourManager |
| GET | `/backline/tours/{id}` | Fetch a tour | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/tours` | List tours, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/tours/{id}/activate` | Activate a DRAFT tour (OCC-guarded) | TourManager |
| POST | `/backline/tours/{id}/complete` | Complete an ACTIVE tour and compute final settlement | TourManager |
| POST | `/backline/tours/{id}/cancel` | Cancel a tour with cascade | TourManager, OpsManager |
| POST | `/backline/tours/{id}/stops` | Add a stop to a tour | TourManager |
| GET | `/backline/tours/{id}/stops` | List a tour's stops | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/tour-stops/{id}` | Fetch one stop | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/tour-stops/{id}/stage` | Move a stop from PLANNED to GEAR_STAGED | LogisticsCoordinator |
| POST | `/backline/tour-stops/{id}/show-ready` | Move a stop from GEAR_STAGED to SHOW_READY | WarehouseTech |
| POST | `/backline/tour-stops/{id}/load-out` | Move a stop from SHOW_READY to LOADED_OUT, returning all delivered reservations | WarehouseTech |
| POST | `/backline/tour-stops/{id}/settle` | Move a stop from LOADED_OUT to SETTLED | TourManager |
| POST | `/backline/tour-stops/{id}/cancel` | Cancel a PLANNED stop with cascade | TourManager |
| POST | `/backline/tour-stops/{id}/rider-lines` | Add a rider line to a stop | TourManager |
| GET | `/backline/tour-stops/{id}/rider-lines` | List a stop's rider lines | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/rider-lines` | List rider lines across stops, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/rider-lines/{id}` | Fetch one rider line | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/rider-lines/{id}/source` | Source the line: pick a unit and create a SOURCED reservation, or open the cross-rental path with a DRAFT reservation | LogisticsCoordinator |
| POST | `/backline/rider-lines/{id}/propose-substitution` | Move a SOURCED line to SUBSTITUTION_PENDING | LogisticsCoordinator |
| POST | `/backline/rider-lines/{id}/approve-substitution` | Approve a substitution (OCC-guarded on the stop's rider revision) | TourManager |
| POST | `/backline/rider-lines/{id}/reject-substitution` | Reject a substitution, returning the line to SOURCED | TourManager |
| POST | `/backline/rider-lines/{id}/mark-fulfilled` | Mark a SOURCED or APPROVED line FULFILLED after delivery | WarehouseTech |
| POST | `/backline/rider-lines/{id}/mark-shorted` | Mark a REQUESTED line SHORTED when nothing can cover it | LogisticsCoordinator |
| POST | `/backline/rider-lines/{id}/cancel` | Cancel a non-terminal rider line | TourManager |
| POST | `/backline/gear-models` | Create a catalog model | OpsManager |
| GET | `/backline/gear-models/{id}` | Fetch a model | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/gear-models` | List models, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/gear-units` | Register a physical unit | OpsManager |
| GET | `/backline/gear-units/{id}` | Fetch a unit including computed condition fields | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/gear-units` | List units, filterable by model, city, and status | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/gear-units/{id}/shipment-lines` | List shipment lines booking this unit | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/gear-units/{id}/retire` | Move an AVAILABLE unit to RETIRED | OpsManager |
| GET | `/backline/gear-units/{id}/availability` | Computed availability windows for a queried range | OpsManager, TourManager, LogisticsCoordinator |
| GET | `/backline/reservation-lines/{id}` | Fetch a reservation | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/reservation-lines` | List reservations, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/reservation-lines/{id}/dispatch` | Move a SOURCED reservation to DISPATCHED | LogisticsCoordinator |
| POST | `/backline/reservation-lines/{id}/mark-delivered` | Move a DISPATCHED reservation to DELIVERED | LogisticsCoordinator |
| POST | `/backline/reservation-lines/{id}/check-in` | Move a DELIVERED reservation to RETURNED with the maintenance-gate cascade | WarehouseTech |
| POST | `/backline/reservation-lines/{id}/inspect` | Move a RETURNED reservation to INSPECTED, optionally filing a damage claim atomically | WarehouseTech |
| POST | `/backline/reservation-lines/{id}/settle` | Move an INSPECTED reservation to SETTLED (OCC-guarded) | TourManager |
| POST | `/backline/reservation-lines/{id}/cancel` | Cancel a DRAFT or SOURCED reservation with compensation | TourManager |
| POST | `/backline/shipments` | Create a cartage leg | LogisticsCoordinator |
| GET | `/backline/shipments/{id}` | Fetch a shipment including booked weight and tech labor | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/shipments` | List shipments, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/shipments/{id}/lines` | Book a unit onto a shipment | LogisticsCoordinator |
| GET | `/backline/shipments/{id}/lines` | List a shipment's lines | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/shipments/{id}/begin-loading` | Move a shipment from PLANNED to LOADING | LogisticsCoordinator |
| POST | `/backline/shipment-lines/{id}/load` | Load a BOOKED line with capacity and flight-case checks | WarehouseTech |
| POST | `/backline/shipment-lines/{id}/cancel` | Cancel a BOOKED line | LogisticsCoordinator |
| POST | `/backline/shipments/{id}/depart` | Move a shipment from LOADING to IN_TRANSIT | LogisticsCoordinator |
| POST | `/backline/shipments/{id}/mark-delivered` | Move a shipment from IN_TRANSIT to DELIVERED | LogisticsCoordinator |
| POST | `/backline/shipments/{id}/close` | Move a shipment from DELIVERED to CLOSED | LogisticsCoordinator |
| POST | `/backline/shipments/{id}/cancel` | Cancel a PLANNED or LOADING shipment with line cascade | LogisticsCoordinator |
| POST | `/backline/flight-cases` | Register a flight case | OpsManager |
| GET | `/backline/flight-cases/{id}` | Fetch a case | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/flight-cases` | List cases, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/flight-cases/{id}/shipment-lines` | List shipment lines this case is assigned to | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/flight-cases/{id}/send-to-maintenance` | Move an AVAILABLE case to MAINTENANCE | WarehouseTech |
| POST | `/backline/flight-cases/{id}/return-to-service` | Return a MAINTENANCE case to AVAILABLE | WarehouseTech |
| POST | `/backline/flight-cases/{id}/retire` | Retire an AVAILABLE case with no open shipment lines | OpsManager |
| POST | `/backline/partner-vendors` | Onboard a vendor in PENDING | OpsManager |
| GET | `/backline/partner-vendors/{id}` | Fetch a vendor | OpsManager, TourManager, LogisticsCoordinator |
| GET | `/backline/partner-vendors` | List vendors, filterable | OpsManager, TourManager, LogisticsCoordinator |
| POST | `/backline/partner-vendors/{id}/approve` | Approve a PENDING or SUSPENDED vendor | OpsManager |
| POST | `/backline/partner-vendors/{id}/suspend` | Suspend an APPROVED vendor, cancelling its open cross-rental requests | OpsManager |
| POST | `/backline/cross-rental-requests` | Open a cross-rental request against an unsourced reservation | LogisticsCoordinator |
| GET | `/backline/cross-rental-requests/{id}` | Fetch a cross-rental request | OpsManager, TourManager, LogisticsCoordinator, PartnerVendorRep |
| GET | `/backline/cross-rental-requests` | List cross-rental requests, filterable | OpsManager, TourManager, LogisticsCoordinator, PartnerVendorRep |
| POST | `/backline/cross-rental-requests/{id}/accept` | Vendor rep accepts a REQUESTED cross-rental | PartnerVendorRep |
| POST | `/backline/cross-rental-requests/{id}/reject` | Vendor rep rejects a REQUESTED cross-rental | PartnerVendorRep |
| POST | `/backline/cross-rental-requests/{id}/mark-fulfilled` | Vendor rep marks an ACCEPTED cross-rental FULFILLED, sourcing the reservation cross-vendor | PartnerVendorRep |
| POST | `/backline/cross-rental-requests/{id}/settle` | Settle a FULFILLED cross-rental, computing commission | OpsManager |
| POST | `/backline/cross-rental-requests/{id}/cancel` | Cancel a REQUESTED or ACCEPTED cross-rental | LogisticsCoordinator |
| POST | `/backline/maintenance-tickets` | Open a maintenance ticket manually | WarehouseTech, OpsManager |
| GET | `/backline/maintenance-tickets/{id}` | Fetch a ticket | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| GET | `/backline/maintenance-tickets` | List tickets, filterable | OpsManager, TourManager, LogisticsCoordinator, WarehouseTech |
| POST | `/backline/maintenance-tickets/{id}/start` | Move a ticket from OPEN to IN_PROGRESS | WarehouseTech |
| POST | `/backline/maintenance-tickets/{id}/await-parts` | Move a ticket from IN_PROGRESS to AWAITING_PARTS | WarehouseTech |
| POST | `/backline/maintenance-tickets/{id}/resume` | Resume an AWAITING_PARTS ticket to IN_PROGRESS | WarehouseTech |
| POST | `/backline/maintenance-tickets/{id}/complete` | Complete an IN_PROGRESS ticket, restoring the unit | WarehouseTech |
| POST | `/backline/maintenance-tickets/{id}/cancel` | Cancel an OPEN or AWAITING_PARTS ticket | OpsManager |
| GET | `/backline/damage-claims/{id}` | Fetch a claim | OpsManager, TourManager, WarehouseTech |
| GET | `/backline/damage-claims` | List claims, filterable | OpsManager, TourManager, WarehouseTech |
| POST | `/backline/damage-claims/{id}/assess` | Assess a FILED claim (segregation of duties enforced) | OpsManager |
| POST | `/backline/damage-claims/{id}/charge` | Charge an ASSESSED or DISPUTED claim | TourManager, OpsManager |
| POST | `/backline/damage-claims/{id}/dispute` | Dispute an ASSESSED claim | TourManager |
| POST | `/backline/damage-claims/{id}/waive` | Waive an ASSESSED or DISPUTED claim | OpsManager |
| POST | `/backline/damage-claims/{id}/mark-paid` | Mark a CHARGED claim PAID | TourManager |

## 5. Error Code Catalogue

Trigger conditions for each error live in the §2 and §3 narratives; this catalogue is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_UNIT_NOT_SERVICEABLE` | 422 Unprocessable Entity |
| `ERR_GEAR_UNAVAILABLE` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_SUBSTITUTION_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_FLIGHT_CASE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_VENDOR_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_INSUFFICIENT` | 402 Payment Required |
| `ERR_INSURANCE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |

# Glider Club Soaring API — Product Requirements Document

## 1. Introduction

A volunteer-run soaring club lives and dies by its shared assets: a handful of club gliders, one or two tow planes, a rotating cast of duty officers, instructors, and tow pilots, and a membership whose dues and tow fees keep the operation solvent. Today that operation runs on a paper launch log at the flight line, a spreadsheet for dues, and a whiteboard for the duty roster — an arrangement that loses flights, misbills tows, lets airframes slip past their inspection limits, and turns every cross-country land-out into a phone tree. This document specifies the Glider Club Soaring API, the system of record for an SSA-affiliated club's day-to-day flying operation.

The API governs the full operational loop: membership tiers and monthly dues, glider reservations with instructor coverage rules, tow plane slot scheduling with hard capacity limits, the launch log itself from takeoff posting through landing and reconciliation, airframe maintenance currency with automatic grounding, student pilot progression from solo signoff through badge verification, the duty officer rotation with peer-to-peer swaps, and the coordination and cost-sharing of cross-country retrieves. A single account ledger per member ties the financial pieces together — dues postings, provisional and final tow fees, no-show and late-cancel penalties, retrieve cost shares, and payments — with automatic suspension when arrears run too deep.

All resources are mounted under `/soaring`. Because the measure of a club system is that volunteers can trust it on a busy Saturday morning, the specification emphasizes exact temporal-window semantics, exact money arithmetic in integer cents, and optimistic concurrency guards on the two operations where stale reads cause real harm: booking a glider and posting a launch against a tow slot.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or naming a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Five roles exist, spelled exactly as follows: `ClubAdmin`, `Member`, `DutyOfficer`, `Instructor`, and `TowPilot`.

- A `ClubAdmin` is the club operations administrator; the role owns configuration, maintenance logging, roster assignment, progression verification, and the ops-day close.
- A `Member` is a club pilot; the role books and flies its own reservations, pays its own account, and acts on its own duty slots.
- A `DutyOfficer` is the duty officer of the day, acting on behalf of members for launch operations and retrieve coordination.
- An `Instructor` publishes availability windows and signs student progression records.
- A `TowPilot` manages tow slots and posts launches.

Identity binding differs by role. When `X-User-Role` is `Member`, `DutyOfficer`, `Instructor`, or `TowPilot`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's foreign-key field — a reservation's `member_id`, a duty slot's assignee, a progression record's `instructor_id`, an availability window's `instructor_id`, a tow slot's `tow_pilot_id` — to `X-User-ID`. When `X-User-Role` is `ClubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, an ISO 8601 UTC timestamp with three fractional digits, refreshed on every modification; and `version`, an integer that starts at its initial value on creation and increments by one on every mutation of the resource. Automatic transitions — an ops-day-close sweep grounding an airframe, a cascade cancelling a reservation, a balance sweep — are mutations like any other: they refresh `updated_at` and increment `version` on each resource they touch.

The one exception is the maintenance log. A `MaintenanceRecord` is an immutable log entry and carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.5. The Logical Clock

The server evaluates every temporal rule in this document — windows, deadlines, sweeps, "now", "today" — against a **logical clock**, never against wall-clock time. Before any call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`. An admin-only, test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the resulting `current_utc`; there is no fallback to real time under any circumstances.

### 2.6. The Member Account Ledger

Each member carries a single account ledger summarized by `account_balance_cents`: a positive value means the member owes the club, a negative value is a credit in the member's favor. The balance is a derived figure, built from dues postings plus tow charges and penalty fees, minus payments. A launch posts a **provisional** tow debit; when the flight lands, the provisional debit is replaced by the final tow fee with only the delta applied; a voided launch reverses the provisional debit entirely. A mid-month tier change parks its prorated charge in `pending_dues_cents`, which the next ops-day close sweeps into the balance before resetting it to zero.

Three penalty fees always apply and are never waived or blocked: the late-cancel fee of 1,500 cents, the reservation no-show fee of 2,500 cents, and the duty no-show fee of 5,000 cents. Payments are the one bounded movement: a payment that would push an account deeper into credit than 50,000 cents — that is, one that would take `account_balance_cents` below −50,000 — is rejected with `ERR_CREDIT_CAP_EXCEEDED` (HTTP 402). Finally, the arrears threshold stands at 20,000 cents: a member whose balance sits at or above that figure after a dues posting is suspended automatically at the ops-day close.

### 2.7. Cents, Hours, and Rounding Discipline

All monetary values are integer cents; the API never speaks in fractional currency. Rounding is pinned per calculation rather than left to convention. Tow fees apply the tier discount first and round half up to whole cents at that discount step only; a soaring surcharge, when owed, is an integer added afterward and is never discounted. Retrieve cost allocation rounds each distance band half up, with the club's share taken as the residual so the total is always conserved. The mid-month dues proration deliberately mixes rounding modes: the old-tier half of the month is floored, the new-tier half is rounded half up. Airframe hours are compared as exact decimals — no tolerance band — and timestamps are compared to the second.

### 2.8. Airworthiness Currency

An airframe is currency-legal only while **both** of the following hold: `hours_since_inspection` is strictly below 100.0 hours — exactly 100.0 hours fails — and `annual_due_date` lies strictly in the future — a deadline exactly equal to the current instant fails. The check runs in three places: inline at reservation checkout, inline at launch posting, and as a sweep across every `AIRWORTHY` airframe at each ops-day close. An airframe that fails the sweep grounds itself with `grounded_reason` set to `INSPECTION_OVERDUE` for the hours failure or `ANNUAL_OVERDUE` for the date failure; when an airframe fails both on the same sweep, `INSPECTION_OVERDUE` is the recorded reason. Currency discipline applies to gliders and tow planes alike.

### 2.9. Time Windows, Overlap, and Buffers

Reservation windows are half-open intervals: a reservation occupies from `start_at` up to but not including `end_at`. Two reservations on the same glider overlap only when their half-open intervals intersect; back-to-back bookings where one reservation's `end_at` equals the other's `start_at` do **not** overlap and are both permitted. Instructor scheduling adds a protective buffer: an instructor is double-booked when another active reservation sits within 30 minutes on either side of a proposed one — a gap of exactly 30 minutes is allowed, anything less is a conflict. Launch-day checkout opens 15 minutes before the reservation's `start_at` and remains available through `end_at`. Flight times are strictly ordered: a landing must be after the takeoff.

### 2.10. Optimistic Concurrency Control

Two write operations — and only these two — require the caller to present the version of a parent entity it last observed.

A `POST /soaring/flights` request must carry `expected_tow_slot_version`, holding the client's last observed `version` of the target tow slot. Posting a flight legitimately advances the slot's `version` (its `confirmed_count` increments), so a second create carrying the previously observed version is stale even if the slot still has capacity. If the supplied value does not match the tow slot's current `version`, the request is rejected with `ERR_STALE_TOW_SLOT_VERSION` (HTTP 412).

A `POST /soaring/reservations` request must carry `expected_aircraft_version`, holding the client's last observed `version` of the glider. An earlier reservation's lifecycle legitimately mutates the airframe — hour accrual, version bumps — so a create carrying an old version acts on a stale view of fleet availability. If the supplied value does not match the airframe's current `version`, the request is rejected with `ERR_STALE_AIRCRAFT_VERSION` (HTTP 412).

Both fields are non-optional on their respective endpoints. Endpoints not named above do not accept a version field at all.

### 2.11. Validation Order and Resource Lookup

Requests are validated in a fixed order so that failures surface predictably. First, header presence and role recognition (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role permission for the endpoint (`ERR_FORBIDDEN_ROLE`). Next, existence: every resource referenced by path or body — member, tier, aircraft, reservation, flight, tow slot, duty slot, availability window, progression record, retrieve — must exist, or the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404); where a path nests one resource under another, identifiers are validated left to right and the first missing id produces the 404. Then state gates in this order: the target resource's own state permits the operation (`ERR_INVALID_STATE`, HTTP 409); member-side standing — pilot, instructor, or crew must be `ACTIVE` for flight-side operations, a paying member must not be `RESIGNED`, a student must be `ACTIVE` at solo signoff (`ERR_MEMBER_NOT_ACTIVE`); airworthiness including the inline currency check (`ERR_AIRCRAFT_NOT_AIRWORTHY`). Temporal checks follow: window ordering and the checkout window (`ERR_INVALID_TIME_WINDOW`, HTTP 422); then glider overlap (`ERR_GLIDER_OVERLAP`); then the instructor buffer (`ERR_INSTRUCTOR_DOUBLE_BOOKED`); then instructor availability coverage (`ERR_INSTRUCTOR_UNAVAILABLE`). Business constraints come next: tow slot capacity (`ERR_TOW_SLOT_FULL`), then — sharing one rank because they guard different operations and never compete — tow-slot coherence at launch posting (`ERR_TOW_SLOT_MISMATCH`) and the landed-out requirement at retrieve creation (`ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT`), then duty swap integrity (`ERR_SWAP_INVALID`). Fiscal bounds follow (`ERR_CREDIT_CAP_EXCEEDED`), and enum/type referential integrity is checked last (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Membership Tiers and Enrollment

Membership economics begin with the **MembershipTier** catalog, which only a `ClubAdmin` may write, though every role may list and read tiers. A tier is defined by a unique `tier_code` — club convention suggests codes such as `STUDENT`, `STANDARD`, `FAMILY`, or `TOW_PILOT` — together with `monthly_dues_cents`, the amount debited to each member on that tier at the monthly posting, and `tow_fee_discount_pct`, the fractional discount applied to tow fees, bounded inclusively between 0.00 and 0.50. Tiers may also carry `included_tows_per_month`, the number of tow launches per calendar month billed at zero cents before pay-per-tow pricing applies, defaulting to 0, and a `student_tier` flag, defaulting to false, marking tiers whose members are eligible for student progression records. Reusing an existing `tier_code` is rejected with `ERR_UNIQUE_CONSTRAINT` (HTTP 409).

A `ClubAdmin` enrolls each **Member** with a `full_name` and a `tier_id` referencing an existing tier; the optional `is_instructor` and `is_tow_pilot` flags, both defaulting to false, gate the member's ability to act as an `Instructor` or `TowPilot`. New members start in `ACTIVE` status with `account_balance_cents` at 0, `pending_dues_cents` at 0, `badge_level` of `NONE`, `solo_endorsed` false, and no `suspension_reason`. The member roster can be listed with `tier_id` and `status` filters, and a member's `status` moves among `ACTIVE`, `SUSPENDED`, and `RESIGNED` over its life.

When a `ClubAdmin` changes a member's tier mid-month by supplying a new `tier_id`, the club does not bill the change retroactively nor wait for a clean month boundary. Instead, the current month's dues are recomputed as a day-weighted blend and parked in the member's `pending_dues_cents`. Let the change month's calendar length in UTC be the days in the month; the days billed to the old tier are the day-of-month of the change minus one, and the remainder of the month — including the change day itself, which bills to the **new** tier — is billed to the new tier. The blended charge is the old tier's monthly dues multiplied by the old-tier days and divided by the days in the month, that half **floored** to whole cents, plus the new tier's monthly dues multiplied by the new-tier days and divided by the days in the month, that half **rounded half up**. At the next ops-day close, a member carrying a nonzero `pending_dues_cents` is charged that pending amount **instead of** the ordinary forward dues debit for that month, and `pending_dues_cents` returns to 0.

### 3.2. Member Accounts, Payments, and Standing

Payments restore solvency. A `Member` records a payment against their own account — a `ClubAdmin` may record one for anyone — by supplying `amount_cents`; the payment reduces `account_balance_cents` by that amount and returns the updated member. Two guards apply. A `RESIGNED` member may not make payments at all: the attempt fails with `ERR_MEMBER_NOT_ACTIVE` (HTTP 409). And per §2.6, a payment that would carry the balance below the −50,000-cent credit cap is rejected with `ERR_CREDIT_CAP_EXCEEDED` (HTTP 402).

Suspension comes in two flavors, both recorded on the member's `suspension_reason`. The system path fires at the ops-day close: after dues posting, any member whose `account_balance_cents` is at or above the 20,000-cent arrears threshold moves from `ACTIVE` to `SUSPENDED` with `suspension_reason` set to `ARREARS`. A `ClubAdmin` may also suspend a member directly, which records `MANUAL`. Either way, suspension cancels every one of the member's `BOOKED` reservations whose `start_at` lies in the future; reservations already past their start are untouched, and no tow slot is affected at this stage since a `BOOKED` reservation has no flight yet. A member suspended for `ARREARS` climbs back automatically: when a payment brings the post-payment balance below the 20,000-cent threshold, the member returns from `SUSPENDED` to `ACTIVE` and `suspension_reason` is cleared to null. Manually suspended members enjoy no such automatic path.

Resignation is the terminal act. A `Member` may resign themselves, or a `ClubAdmin` may process it, provided the member has no flight currently `IN_FLIGHT` — resigning mid-air is rejected with `ERR_MEMBER_IN_FLIGHT` (HTTP 409). Resignation moves the member to `RESIGNED` — a terminal state — and sweeps their commitments: **all** of their `BOOKED` reservations are cancelled regardless of date, every `OPEN` availability window they published as an instructor is cancelled, and every duty roster slot of theirs in `ASSIGNED` or `CONFIRMED` status with a `duty_date` of today or later is cancelled. `SUSPENDED` members block all flight-side activity until reinstated.

### 3.3. Fleet Registry, Maintenance, and Grounding

A `ClubAdmin` registers each airframe with its unique tail number in `registration`, a `kind` of `GLIDER` or `TOW_PLANE`, and the next `annual_due_date`. Duplicate tail numbers are refused with `ERR_UNIQUE_CONSTRAINT`. A new airframe enters service `AIRWORTHY` with `total_time_hours` at 0 and `hours_since_inspection` at 0. The fleet list supports `kind` and `status` filters; an airframe's `status` walks from `AIRWORTHY` to `GROUNDED` and back, or onward to the terminal `RETIRED`.

Maintenance is an append-only log. A `ClubAdmin` logs each entry with the airframe's `aircraft_id`, a `kind` of `INSPECTION_100H`, `ANNUAL`, or `REPAIR`, the `performed_at` timestamp, the `hobbs_hours_at_service` reading, and optional free-text `notes`. An `INSPECTION_100H` record resets the airframe's `hours_since_inspection` to 0. An `ANNUAL` record pushes `annual_due_date` to twelve months after `performed_at`. When a logged record restores currency on a grounded airframe whose `grounded_reason` is anything other than `MANUAL`, the airframe returns to `AIRWORTHY` and `grounded_reason` clears; a manually grounded airframe is not restored by paperwork.

Grounding itself arrives by three routes, all converging on the same cascade. The ops-day close grounds any `AIRWORTHY` airframe that fails the §2.8 currency check, recording `INSPECTION_OVERDUE` or `ANNUAL_OVERDUE`. A `ClubAdmin` may ground an airframe at will, recording `MANUAL`. And landing a flight can push an airframe over a limit, grounding it in-request (see §3.6). Whatever the route, grounding an airframe cancels every `BOOKED` reservation on that airframe whose `start_at` lies in the future, and — for tow planes — cancels every `SCHEDULED` tow slot whose `start_at` lies in the future. Flights already `IN_FLIGHT` or `LANDED` against a cancelled slot are unaffected; they consumed the slot. Instructor availability windows are independent of the airframe and do not change. A manually grounded airframe returns to service when a `ClubAdmin` ungrounds it, valid only while `grounded_reason` is `MANUAL`, clearing the reason and restoring `AIRWORTHY`.

Retirement is forever. A `ClubAdmin` may retire an airframe only while no reservation is `CHECKED_OUT` on it; a checked-out airframe refuses with `ERR_AIRCRAFT_IN_USE` (HTTP 409). Retirement is stricter than grounding in its sweep: **all** `BOOKED` reservations on the airframe cancel regardless of date, and **all** `SCHEDULED` tow slots on it cancel as well.

### 3.4. Glider Reservations and Launch-Day Checkout

Reserving a glider is the member-facing act that sets a flight day in motion. A `Member` books for themselves; a `DutyOfficer` or `ClubAdmin` may book on a member's behalf. The request names the `aircraft_id` of the glider, the pilot as `member_id`, an optional `instructor_id` for dual instructional flights, the window as `start_at` and `end_at`, and the OCC token `expected_aircraft_version` per §2.10. A successful create increments the airframe's `version` by one. The reservation list answers `aircraft_id`, `member_id`, `instructor_id`, and `status` filters, with `status` drawn from `BOOKED`, `CHECKED_OUT`, `CLOSED`, `CANCELLED`, and `NO_SHOW`.

Creation runs its checks in the §2.11 order — member standing first, window sanity next, then glider overlap, then the instructor buffer, then availability coverage, with kind and flag integrity last. The pilot's `member_id` must resolve to an `ACTIVE` member, or the create fails with `ERR_MEMBER_NOT_ACTIVE`. The window must be well ordered — `start_at` strictly before `end_at` — and `start_at` may not sit further than fifteen minutes in the past, else `ERR_INVALID_TIME_WINDOW`. The glider must be free: any other reservation in `BOOKED` or `CHECKED_OUT` on the same airframe whose half-open interval intersects the requested one yields `ERR_GLIDER_OVERLAP` (HTTP 409); per §2.9, touching endpoints are not an overlap. When `instructor_id` is supplied, two further checks bind. The instructor must not sit within 30 minutes on either side of another `BOOKED` or `CHECKED_OUT` reservation of theirs — a gap of exactly 30 minutes passes, anything less fails with `ERR_INSTRUCTOR_DOUBLE_BOOKED`. And an `OPEN` availability window of that instructor must fully cover the requested `start_at`-to-`end_at` span, else `ERR_INSTRUCTOR_UNAVAILABLE`. Finally, integrity: the reserved airframe's `kind` must be `GLIDER`, and a named instructor must carry `is_instructor` true — violations draw `ERR_REFERENTIAL_INTEGRITY` (HTTP 422).

On launch day, checkout is performed by the piloting `Member` or the `DutyOfficer`. Checkout demands the reservation still be `BOOKED` (`ERR_RESERVATION_NOT_BOOKED`), the airframe `AIRWORTHY` with the §2.8 inline currency check passing (`ERR_AIRCRAFT_NOT_AIRWORTHY`), the pilot `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), any assigned instructor also `ACTIVE` (`ERR_INSTRUCTOR_NOT_ACTIVE`), and the current instant within the window that opens 15 minutes before `start_at` and closes at `end_at` (`ERR_INVALID_TIME_WINDOW`, HTTP 422). A successful checkout moves the reservation from `BOOKED` to `CHECKED_OUT`.

Cancelling a reservation — by the piloting `Member`, a `DutyOfficer`, or a `ClubAdmin` — likewise requires `BOOKED` status, failing otherwise with `ERR_RESERVATION_NOT_BOOKED`. A member-initiated cancel made less than 24 hours before `start_at` posts the 1,500-cent late-cancel fee to the member's `account_balance_cents`; cancels fired by cascades (suspension, resignation, grounding, retirement) never charge it. A reservation that is neither flown nor cancelled is caught by the ops-day close: still `BOOKED` with `end_at` in the past, it is marked `NO_SHOW` and the 2,500-cent no-show fee lands on the member's account. `CLOSED`, `CANCELLED`, and `NO_SHOW` are all terminal.

### 3.5. Tow Slots and Launch Posting

Tow operations revolve around the **TowSlot**: a scheduled window in which one tow plane, flown by one tow pilot, can launch a bounded number of gliders. A `ClubAdmin` schedules slots, as does the `TowPilot` who will fly them. The request names the `tow_plane_id` — which must reference an airframe of `kind` `TOW_PLANE` — the `tow_pilot_id`, which must reference a member with `is_tow_pilot` true (kind and flag violations draw `ERR_REFERENTIAL_INTEGRITY`), the window as `start_at` and `end_at`, and a `capacity` of at least 1. A new slot starts `SCHEDULED` with `confirmed_count` 0. The slot list answers `tow_plane_id`, `tow_pilot_id`, and `status` filters, with `status` drawn from `SCHEDULED` and the terminal `CANCELLED`.

A slot's `confirmed_count` is the number of flights linked to it whose status is `IN_FLIGHT`, `LANDED`, or `RECONCILED` — voided flights drop out of the count. A `TowPilot` or `ClubAdmin` may cancel a slot, but only while no `IN_FLIGHT` flight is linked to it; an airborne launch blocks cancellation with `ERR_TOW_SLOT_IN_USE` (HTTP 409). Cancellation leaves `LANDED` flights as history and blocks any future launches against the slot.

Posting a launch creates the **Flight** and is performed by the piloting `Member`, the `DutyOfficer`, or the `TowPilot`. The request carries the `reservation_id` of the checked-out booking, the `tow_slot_id` it consumes, the `release_altitude_ft` in feet MSL — which must be at least 500 — the actual `takeoff_at`, and the OCC token `expected_tow_slot_version` per §2.10. Coherence is enforced before anything is recorded: the reservation must be `CHECKED_OUT`, the slot must be `SCHEDULED`, and `takeoff_at` must fall inside the slot's `start_at`-to-`end_at` window — any mismatch is `ERR_TOW_SLOT_MISMATCH`. The pilot and any instructor must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), the glider must pass the inline airworthiness gate (`ERR_AIRCRAFT_NOT_AIRWORTHY`), and the slot must have room: posting succeeds while `confirmed_count` is strictly below `capacity` — filling the last seat succeeds — but a slot whose count already equals its capacity refuses with `ERR_TOW_SLOT_FULL`.

A successful posting creates the flight in `IN_FLIGHT` status and immediately computes `provisional_fee_cents` under the provisional variant of the tow fee: take the base price for the release altitude — below 2,000 feet is 3,000 cents; 2,000 up to but not including 3,000 feet is 3,800 cents; 3,000 up to but not including 5,000 feet is 4,600 cents; 5,000 feet and above is 5,500 cents — multiply that base by one minus the member's tier `tow_fee_discount_pct`, and round half up to whole cents. The provisional variant deliberately ignores both the tier's monthly included-tow quota and any soaring surcharge. The provisional amount is debited to the member's `account_balance_cents` at once, the slot's `confirmed_count` increments by one, and the slot's `version` increments by one with it. The flight list — the club's launch log — answers `reservation_id`, `tow_slot_id`, `retrieve_id`, and `status` filters, with `status` drawn from `IN_FLIGHT`, `LANDED`, `RECONCILED`, and `VOIDED`; each flight also carries an optional `landed_at`, unset until the landing is logged, and a `retrieve_id`, unset unless a retrieve is later filed for it.

### 3.6. Landing, Reconciliation, and Cross-Country Retrieves

Logging a landing, done by the piloting `Member` or the `DutyOfficer` with the `landed_at` instant, closes out the airborne phase. The flight must be `IN_FLIGHT` — anything else fails with `ERR_FLIGHT_NOT_IN_FLIGHT` — and `landed_at` must be strictly after `takeoff_at`, else `ERR_INVALID_FLIGHT_TIMES` (HTTP 422). Landing computes `flight_minutes`: the elapsed time from takeoff to landing, in seconds divided by 60, rounded **up** to whole minutes.

With `flight_minutes` in hand, the final tow fee replaces the provisional one under the final variant. First, count the member's prior `RECONCILED` flights in the same UTC calendar month as this flight's `takeoff_at`, taking the current flight's position in `created_at` order — the current flight is that count plus one, its chronological tow-of-the-month number. If that position is within the tier's `included_tows_per_month`, the gross fee is zero; otherwise the gross is the same altitude-tier base used by the provisional variant. Second, a soaring surcharge rewards — and bills — long flights: when `flight_minutes` exceeds 60, add 400 cents for each commenced 30-minute block beyond the first 60 minutes, so minutes 61 through 90 add one block, 91 through 120 add two, and so on; flights of 60 minutes or less add nothing. Third, assemble `final_fee_cents`: apply the tier discount to the gross — one minus `tow_fee_discount_pct`, multiplied and rounded half up to whole cents — and only then add the integer surcharge, which is never discounted. The member's `account_balance_cents` absorbs the delta between the provisional debit and this final fee.

Airframe hours accrue at landing as well. The glider's `total_time_hours` and `hours_since_inspection` each grow by `flight_minutes` converted to hours. The tow plane accrues a fixed twelve-minute sortie — 0.2 hours — to both of its counters per launched flight, regardless of how long the glider soared. Immediately after accrual, both airframes are re-checked against the §2.8 currency rule: if the new hours pushed `hours_since_inspection` to 100.0 or beyond, or the annual deadline has arrived, that airframe grounds in-request with the matching `grounded_reason`, and the full §3.3 grounding cascade fires — future `BOOKED` reservations on it cancel, and for the tow plane, future `SCHEDULED` slots cancel.

Reconciliation, performed by a `DutyOfficer` or `ClubAdmin`, admits the flight into the permanent log: the flight must be `LANDED` (`ERR_FLIGHT_NOT_LANDED` otherwise) and moves to the terminal `RECONCILED`, which also moves the linked reservation from `CHECKED_OUT` to `CLOSED`. When the flight was dual instructional — its reservation carried an `instructor_id` — and the pilot is on a student tier, reconciliation updates the student's dual-hour accumulator, the figure later snapshotted onto progression records.

A false launch can be undone by a `DutyOfficer` or `ClubAdmin` while the flight is still `IN_FLIGHT` (`ERR_FLIGHT_NOT_IN_FLIGHT` otherwise): the flight moves to the terminal `VOIDED`, the provisional debit on the member's account is reversed in full, and the slot's `confirmed_count` decrements by one. Should that decrement bring the count to zero while the slot's `start_at` still lies in the future, the slot cancels itself automatically. The linked reservation stays `CHECKED_OUT` — the pilot may launch again.

When a flight ends away from home, a cross-country retrieve begins. A `Member`, `DutyOfficer`, or `ClubAdmin` files a **RetrieveRequest** naming the `flight_id` and the one-way `distance_km`, which must be greater than zero. The referenced flight must be `LANDED` or `RECONCILED` — genuinely landed out — and must not already have a non-terminal retrieve; violations fail with `ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT`. Creation computes the cost split and sets the flight's `retrieve_id` back-reference. The total cost is a 5,000-cent base plus 120 cents per commenced kilometre — the distance rounded up to a whole kilometre before the per-kilometre rate applies. The route is then divided into up to three bands: the first 50 kilometres (the whole route if shorter), the next 100 kilometres, and anything beyond 150 kilometres. The total is allocated across the bands in proportion to their kilometre widths, each band's allocation rounded half up to whole cents. The pilot pays the entire first band plus half of the second band — that half rounded half up — and nothing beyond the second band; the result is `pilot_share_cents`. The club absorbs the rest: `club_share_cents` is the total minus the pilot share, taken as the residual so the split always sums back to the total.

From `REQUESTED`, a `DutyOfficer` or `ClubAdmin` assigns a crew by naming a `crew_member_id`; the retrieve must still be `REQUESTED` (`ERR_RETRIEVE_NOT_REQUESTED`) and the crew member must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`). Assignment records the driver and moves the retrieve to `CREW_ASSIGNED`. Completion — again `DutyOfficer` or `ClubAdmin` — requires `CREW_ASSIGNED` (`ERR_RETRIEVE_NOT_ASSIGNED`), moves the retrieve to the terminal `COMPLETED`, and debits `pilot_share_cents` to the pilot member's `account_balance_cents`. A retrieve that never launches may be cancelled from `REQUESTED`, ending `CANCELLED`. The retrieve list answers `flight_id`, `crew_member_id`, and `status` filters.

### 3.7. Instruction and Student Progression

Instructors advertise when they teach. An `Instructor` publishes a window for themselves — a `ClubAdmin` may publish for any instructor — supplying `instructor_id`, `start_at`, and `end_at`; the named instructor must carry `is_instructor` true, else `ERR_REFERENTIAL_INTEGRITY`. A window opens as `OPEN` and remains so until cancelled, which the owning `Instructor` or a `ClubAdmin` may do, moving it to the terminal `CANCELLED`; resignation cascades here as well, cancelling every `OPEN` window of the departing member. The window list answers an `instructor_id` filter.

Student advancement is tracked through **StudentProgress** records, opened by an `Instructor` or `ClubAdmin` with the `student_id`, the endorsing `instructor_id`, and a `kind` drawn from `SOLO_SIGNOFF`, `CHECKRIDE_PASS`, `BADGE_A`, `BADGE_B`, `BADGE_C`, `BADGE_BRONZE`, and `BADGE_SILVER`. Opening requires the student's tier to be a student tier (`student_tier` true) and the instructor to be flagged — mismatches fail with `ERR_REFERENTIAL_INTEGRITY` — and the record starts `PENDING`. The record list answers `student_id`, `instructor_id`, `status`, and `kind` filters, with `status` drawn from `PENDING`, `SIGNED_OFF`, `VERIFIED`, and `REJECTED`.

Signoff belongs to the endorsing instructor alone: the acting instructor must be the record's `instructor_id`, or the attempt fails with `ERR_NOT_ENDORSING_INSTRUCTOR` (HTTP 403), and the record must still be `PENDING`, else `ERR_PROGRESS_NOT_PENDING`. A `SOLO_SIGNOFF` adds the club's safety gate before it can be signed: the student must be `ACTIVE` (`ERR_MEMBER_NOT_ACTIVE`), their accumulated dual instruction — the sum of `flight_minutes` converted to hours across all of the student's `RECONCILED` flights that carried an instructor — must total at least 10.0 hours, and at least one of those dual flights must have a `takeoff_at` within the trailing 90 days. Failing the hours or the recency leg rejects the signoff with `ERR_SOLO_ELIGIBILITY_FAILED` (HTTP 422). A successful signoff moves the record to `SIGNED_OFF`, snapshots the student's current dual-hour total into `dual_hours_at_signoff`, and stamps `signed_off_at`.

Verification is the `ClubAdmin`'s desk. A record must be `SIGNED_OFF` to verify — otherwise `ERR_PROGRESS_NOT_SIGNED_OFF` — and verifying moves it to the terminal `VERIFIED`. Verifying a `SOLO_SIGNOFF` flips the student's `solo_endorsed` to true. Verifying any badge kind recomputes the student's `badge_level` as the highest-ranked badge among their `VERIFIED` records, ranked `BADGE_A` below `BADGE_B` below `BADGE_C` below `BADGE_BRONZE` below `BADGE_SILVER` and surfacing as `A`, `B`, `C`, `BRONZE`, or `SILVER`; with no verified badges the level stays `NONE`. A `ClubAdmin` who finds the paperwork wanting may instead return a `SIGNED_OFF` record for rework, moving it back to `PENDING` and clearing `signed_off_at` to null — the loop may repeat. A record still `PENDING` may also be rejected outright, ending `REJECTED`.

### 3.8. Duty Officer Rotation and Swaps

The duty roster keeps one accountable officer on the field each flying day. A `ClubAdmin` assigns slots with the `duty_date` — the calendar date, recorded at 00:00Z — and the `member_id` of the assignee; a new slot starts `ASSIGNED`. The roster list answers `member_id`, `status`, and even `swap_with_slot_id` filters, with `status` drawn from `ASSIGNED`, `CONFIRMED`, `COMPLETED`, `SWAP_PENDING`, `NO_SHOW`, and `CANCELLED`.

Ownership rules the roster. Confirming a slot is the assignee's own act: the acting member must be the slot's `member_id` (`ERR_NOT_SLOT_OWNER`, HTTP 403) and the slot must still be `ASSIGNED` (`ERR_SLOT_NOT_ASSIGNED`), moving it to `CONFIRMED`. Swaps are a two-party handshake. The assignee proposes a swap by naming a target slot in `swap_with_slot_id`; the proposer must own the originating slot, the target must be `ASSIGNED` (`ERR_SWAP_TARGET_NOT_ASSIGNED`), the target must belong to a **different** member (`ERR_SWAP_SAME_MEMBER`, HTTP 422), and the target must not already stand as the recorded swap partner of a different slot's pending swap (`ERR_SWAP_INVALID`). A valid proposal moves the originating slot to `SWAP_PENDING` and records the `swap_with_slot_id`. The target slot's owner may then accept, exchanging `member_id` values between the two slots so each member takes the other's day, with both slots returning to `ASSIGNED` and the `swap_with_slot_id` reference cleared on both. Either slot's owner may instead decline, which clears the `swap_with_slot_id` and returns the originating slot to `ASSIGNED` with no exchange.

The ops-day close finalizes the roster. A slot that was `CONFIRMED` and whose `duty_date` has passed closes as `COMPLETED`. A slot still `ASSIGNED` with its `duty_date` in the past — the officer never confirmed — is marked `NO_SHOW` and the 5,000-cent duty no-show fee posts to that member's `account_balance_cents`.

### 3.9. The Ops-Day Close

The ops-day close is the club's epoch advance: a `ClubAdmin`-only act that sweeps every deferred obligation against the logical clock (§2.5) and replies with a summary carrying `dues_posted_count`, `aircraft_grounded_ids`, `no_show_reservation_ids`, and `duty_finalized_ids`.

Dues post on the **first** close executed within each UTC calendar month, under the forward variant of the dues rule: every member whose status is `ACTIVE` or `SUSPENDED` — `RESIGNED` members are excluded — is debited their tier's `monthly_dues_cents`. The exception honors §3.1: a member carrying a prorated `pending_dues_cents` from a mid-month tier change is charged that pending amount instead of the forward debit, and `pending_dues_cents` resets to 0. Immediately after posting, the arrears rule bites: any member whose `account_balance_cents` now sits at or above 20,000 cents is suspended automatically with `suspension_reason` `ARREARS`, and the §3.2 suspension cascade cancels their future `BOOKED` reservations.

The same close sweeps the fleet per §2.8: every `AIRWORTHY` airframe whose `hours_since_inspection` has reached 100.0 hours, or whose `annual_due_date` has arrived, moves to `GROUNDED` with the corresponding reason — `INSPECTION_OVERDUE` winning when both fail together — and the §3.3 grounding cascade cancels its future bookings and, for tow planes, its future slots. The close then walks the launch pipeline: any reservation still `BOOKED` whose `end_at` has passed is marked `NO_SHOW` with the 2,500-cent fee posted, and the duty roster finalizes per §3.8 — past `CONFIRMED` slots to `COMPLETED`, past never-confirmed `ASSIGNED` slots to `NO_SHOW` with the 5,000-cent fee.

## 4. Endpoint Definitions

Operations that create a new resource — tiers, members, airframes, maintenance records, availability windows, reservations, tow slots, flights, duty slots, progression records, retrieve requests — return `201 Created`; recording a payment also returns `201 Created`, with the updated member account in the response body. Operations that act on an existing resource — checkouts, cancels, state transitions, tier changes, the clock set, the ops-day close — return `200 OK`. Readers must pair this table with the §3 narratives, which carry the request payloads, validations, and side effects for each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/soaring/_clock/set_current_utc` | Set the server's logical clock | ClubAdmin |
| POST | `/soaring/tiers` | Create a membership tier | ClubAdmin |
| GET | `/soaring/tiers` | List membership tiers | All roles |
| GET | `/soaring/tiers/{id}` | Get a membership tier | All roles |
| POST | `/soaring/members` | Register a member | ClubAdmin |
| GET | `/soaring/members` | List members (filterable) | All roles |
| GET | `/soaring/members/{id}` | Get a member | All roles |
| POST | `/soaring/members/{id}/tier` | Change a member's tier (prorated dues scheduled) | ClubAdmin |
| POST | `/soaring/members/{id}/payments` | Record a payment against the member account | Member, ClubAdmin |
| POST | `/soaring/members/{id}/suspend` | Manually suspend a member | ClubAdmin |
| POST | `/soaring/members/{id}/resign` | Resign a member | Member, ClubAdmin |
| POST | `/soaring/aircraft` | Register an airframe | ClubAdmin |
| GET | `/soaring/aircraft` | List aircraft (filterable) | All roles |
| GET | `/soaring/aircraft/{id}` | Get an airframe | All roles |
| POST | `/soaring/aircraft/{id}/ground` | Manually ground an airframe | ClubAdmin |
| POST | `/soaring/aircraft/{id}/unground` | Return a manually grounded airframe to service | ClubAdmin |
| POST | `/soaring/aircraft/{id}/retire` | Retire an airframe | ClubAdmin |
| POST | `/soaring/aircraft/{id}/maintenance-records` | Log a maintenance record (100h inspection / annual / repair) | ClubAdmin |
| GET | `/soaring/aircraft/{id}/maintenance-records` | List maintenance records for an airframe | All roles |
| POST | `/soaring/instructor-availability` | Publish an instructor availability window | Instructor, ClubAdmin |
| GET | `/soaring/instructor-availability` | List availability windows | All roles |
| GET | `/soaring/instructor-availability/{id}` | Get an availability window | All roles |
| POST | `/soaring/instructor-availability/{id}/cancel` | Cancel an availability window | Instructor, ClubAdmin |
| POST | `/soaring/reservations` | Create a glider reservation (OCC on aircraft version) | Member, DutyOfficer, ClubAdmin |
| GET | `/soaring/reservations` | List reservations (filterable) | All roles |
| GET | `/soaring/reservations/{id}` | Get a reservation | All roles |
| POST | `/soaring/reservations/{id}/checkout` | Check out a reserved glider for launch | Member, DutyOfficer |
| POST | `/soaring/reservations/{id}/cancel` | Cancel a BOOKED reservation | Member, DutyOfficer, ClubAdmin |
| POST | `/soaring/tow-slots` | Schedule a tow plane slot | ClubAdmin, TowPilot |
| GET | `/soaring/tow-slots` | List tow slots | All roles |
| GET | `/soaring/tow-slots/{id}` | Get a tow slot | All roles |
| POST | `/soaring/tow-slots/{id}/cancel` | Cancel a tow slot | TowPilot, ClubAdmin |
| POST | `/soaring/flights` | Post a launch (creates Flight IN_FLIGHT, computes provisional fee) | Member, DutyOfficer, TowPilot |
| GET | `/soaring/flights` | List flights (launch log) | All roles |
| GET | `/soaring/flights/{id}` | Get a flight | All roles |
| POST | `/soaring/flights/{id}/land` | Log landing; computes final fee and accrues airframe hours | Member, DutyOfficer |
| POST | `/soaring/flights/{id}/reconcile` | Reconcile a landed flight into the launch log | DutyOfficer, ClubAdmin |
| POST | `/soaring/flights/{id}/void` | Void an IN_FLIGHT flight (false launch) | DutyOfficer, ClubAdmin |
| POST | `/soaring/duty-roster` | Assign a duty officer slot | ClubAdmin |
| GET | `/soaring/duty-roster` | List duty roster slots | All roles |
| GET | `/soaring/duty-roster/{id}` | Get a duty roster slot | All roles |
| POST | `/soaring/duty-roster/{id}/confirm` | Duty officer confirms their slot | Member |
| POST | `/soaring/duty-roster/{id}/propose-swap` | Propose swapping duty with another slot | Member |
| POST | `/soaring/duty-roster/{id}/accept-swap` | Target slot's member accepts the swap | Member |
| POST | `/soaring/duty-roster/{id}/decline-swap` | Decline a proposed swap | Member |
| POST | `/soaring/student-progress` | Open a student progression record | Instructor, ClubAdmin |
| GET | `/soaring/student-progress` | List progression records | All roles |
| GET | `/soaring/student-progress/{id}` | Get a progression record | All roles |
| POST | `/soaring/student-progress/{id}/signoff` | Instructor signs off the record | Instructor |
| POST | `/soaring/student-progress/{id}/verify` | Club admin verifies a signed-off record | ClubAdmin |
| POST | `/soaring/student-progress/{id}/return-for-rework` | Return a signed-off record to PENDING | ClubAdmin |
| POST | `/soaring/student-progress/{id}/reject` | Reject a pending record | ClubAdmin |
| POST | `/soaring/retrieves` | File a cross-country retrieve request for a landed-out flight | Member, DutyOfficer, ClubAdmin |
| GET | `/soaring/retrieves` | List retrieve requests | All roles |
| GET | `/soaring/retrieves/{id}` | Get a retrieve request | All roles |
| POST | `/soaring/retrieves/{id}/assign-crew` | Assign retrieve crew | DutyOfficer, ClubAdmin |
| POST | `/soaring/retrieves/{id}/complete` | Complete a retrieve; pilot share debited | DutyOfficer, ClubAdmin |
| POST | `/soaring/retrieves/{id}/cancel` | Cancel a retrieve request | DutyOfficer, ClubAdmin |
| POST | `/soaring/ops-day/close` | Close the ops day: dues, currency sweep, no-shows, roster finalization | ClubAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows in §2 and §3; this table is the identifier reference.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RESERVATION_NOT_BOOKED` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_MEMBER_IN_FLIGHT` | 409 Conflict |
| `ERR_INSTRUCTOR_NOT_ACTIVE` | 409 Conflict |
| `ERR_AIRCRAFT_NOT_AIRWORTHY` | 409 Conflict |
| `ERR_AIRCRAFT_IN_USE` | 409 Conflict |
| `ERR_INVALID_TIME_WINDOW` | 422 Unprocessable Entity |
| `ERR_GLIDER_OVERLAP` | 409 Conflict |
| `ERR_INSTRUCTOR_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_INSTRUCTOR_UNAVAILABLE` | 409 Conflict |
| `ERR_TOW_SLOT_FULL` | 409 Conflict |
| `ERR_TOW_SLOT_MISMATCH` | 409 Conflict |
| `ERR_TOW_SLOT_IN_USE` | 409 Conflict |
| `ERR_FLIGHT_NOT_IN_FLIGHT` | 409 Conflict |
| `ERR_FLIGHT_NOT_LANDED` | 409 Conflict |
| `ERR_INVALID_FLIGHT_TIMES` | 422 Unprocessable Entity |
| `ERR_NOT_SLOT_OWNER` | 403 Forbidden |
| `ERR_SLOT_NOT_ASSIGNED` | 409 Conflict |
| `ERR_SWAP_TARGET_NOT_ASSIGNED` | 409 Conflict |
| `ERR_SWAP_SAME_MEMBER` | 422 Unprocessable Entity |
| `ERR_SWAP_INVALID` | 409 Conflict |
| `ERR_PROGRESS_NOT_PENDING` | 409 Conflict |
| `ERR_PROGRESS_NOT_SIGNED_OFF` | 409 Conflict |
| `ERR_NOT_ENDORSING_INSTRUCTOR` | 403 Forbidden |
| `ERR_SOLO_ELIGIBILITY_FAILED` | 422 Unprocessable Entity |
| `ERR_RETRIEVE_NOT_REQUESTED` | 409 Conflict |
| `ERR_RETRIEVE_FLIGHT_NOT_LANDED_OUT` | 409 Conflict |
| `ERR_RETRIEVE_NOT_ASSIGNED` | 409 Conflict |
| `ERR_CREDIT_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_STALE_TOW_SLOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AIRCRAFT_VERSION` | 412 Precondition Failed |
| `ERR_UNIQUE_CONSTRAINT` | 409 Conflict |

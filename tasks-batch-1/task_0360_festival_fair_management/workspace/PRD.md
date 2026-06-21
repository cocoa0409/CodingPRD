# Festival & Fair Management API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Festival & Fair Management API, the operational backbone for running a multi-day outdoor festival from initial planning through final settlement. A festival is a complicated machine: thousands of patrons stream through gates on RFID wristbands that double as cashless wallets, hundreds of food and merchandise vendors apply for and pay for booth space in capacity-limited zones, dozens of artists must be slotted onto stages without colliding, and parking and camping inventory has to be sold against hard physical limits. Layered on top of all of this is the unpredictability of weather, which can suspend a live event mid-stream and, in the worst case, force a cancellation that ripples through every ticket, wristband, performance, and add-on that was sold.

The central design challenge the API addresses is keeping a large set of interdependent quantities consistent as the event unfolds. Booth slots, parking passes, and camping plots are scarce allocations that must never be oversold even when multiple operators act on the same pool. Wallet balances and refund payouts are conserved monetary quantities whose festival-wide totals must always reconcile against the individual records that compose them. The whole system is governed by a single lifecycle posture on the festival that gates which operations are permissible at any given moment — you cannot sell a ticket before sales open, you cannot scan a patron in before the gates go live, and a weather hold instantly closes entry while still letting people leave.

This specification is written for the engineers who will build that backbone. It describes the entities and their relationships, the state machines that drive each lifecycle, the pricing and refund calculations with their exact rounding behavior, the validation rules and the order in which they fire, and the role-based permissions that separate the box office from the gate from the vendor desk from the festival director's office.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which the request is made. If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five distinct roles, spelled exactly as follows: `FestivalDirector`, `BoxOffice`, `VendorManager`, `Vendor`, and `GateAttendant`. A `FestivalDirector` is the operations owner who controls festival posture, weather holds, the cancellation cascade, settlement, incident de-escalation, and the test clock. A `BoxOffice` operator runs the ticketing and wallet desk, selling tickets and add-ons, issuing and activating and cashing out wristbands, and processing voluntary refunds. A `VendorManager` adjudicates booth applications and registers vendors. A `GateAttendant` scans wristbands at the gates and logs and triages incidents. A `Vendor` is an applicant acting on its own booth application.

Four of these roles carry an opaque identity. When `X-User-Role` is `FestivalDirector`, `BoxOffice`, `VendorManager`, or `GateAttendant`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. The `Vendor` role is different: it is entity-backed. When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting `Vendor` entity, and ownership checks compare a resource's vendor foreign key to that value. Specifically, for the vendor-exclusive transitions on a booth application — paying a fee, confirming, and withdrawing — the application's `vendor_id` must equal `X-User-ID`, or the request is rejected with `ERR_NOT_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a particular endpoint states otherwise, list results are ordered by their creation timestamp, `created_at`, in ascending order. Every list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, captured when the resource is first created. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on each mutation of the resource; it is the basis for the optimistic concurrency mechanism described in §2.6.

Two record types are append-only event logs and therefore carry a reduced field set: a wallet transaction and a gate event each expose only `id` and `created_at`. Neither one has an `updated_at` field and neither one has a `version` field, because once written they are never modified. Every other resource — the festival, zones, stages, parking lots, camping areas, tickets, wristbands, vendor applications, vendors, performances, add-ons, refunds, and incidents — carries the full `id`, `created_at`, `updated_at`, and `version` set.

A consistency convention runs through the whole system: whenever a derived or aggregate field on a resource is recomputed as a side effect of some other operation — for instance when a festival's running liability totals are recalculated — that recomputation is itself a mutation of the resource, which refreshes its `updated_at` and increments its `version`. When a parent resource's slot or capacity counters change because of a child operation, the parent is likewise mutated, with its version advancing accordingly.

### 2.5. Nested Resource Retrieval and Referential Integrity

Many endpoints address a resource nested under a parent in the URL, and several carry foreign-key references in their bodies. Path identifiers are validated strictly left to right: the first identifier in the path that does not resolve to an existing resource causes the request to fail with `ERR_NOT_FOUND` before any identifier further to the right is examined. A request for a performance under a stage that does not exist, for example, fails on the missing stage before the performance is ever looked up.

Body-level foreign keys are checked after path resolution. Every foreign key supplied in a request body must resolve to an existing row of the correct entity type and, where the reference is festival-scoped, must belong to the same festival as the operation's context; otherwise the request is rejected with `ERR_FK_NOT_FOUND`.

### 2.6. Optimistic Concurrency on Capacity Pools

Two operations consume scarce capacity from a pool that is shared across operators, and both guard against committing on a stale view of that pool by requiring the caller to echo back the pool parent's last observed `version`.

The first is booth-application approval. Approving a vendor application consumes one booth slot in the requested zone and advances that zone's `version`. The approval request must therefore carry `expected_zone_version`, and this field is mandatory on the approval endpoint. The server compares it against the target zone's current `version`; if another approval has advanced the zone's version since the caller last read it, the approval is rejected with `ERR_STALE_ZONE_VERSION` and an HTTP status of 412. This prevents a second approver who is working from an out-of-date picture of remaining slot capacity from over-allocating the zone beyond its limit; the rejected caller must re-read the zone, re-confirm that a slot remains, and retry with the fresh version.

The second is the sale of a parking add-on. Selling a parking pass consumes one pass from the lot pool and advances that lot's `version`. When a parking add-on is sold, the request must carry `expected_lot_version`, which the server checks against the target parking lot's current `version`; a mismatch is rejected with `ERR_STALE_LOT_VERSION` and an HTTP status of 412, because the caller's view of sold count versus capacity is out of date and committing would risk overselling the lot. The `expected_lot_version` field applies only when the add-on being sold is of the parking kind; a camping add-on takes no version field. No endpoint other than these two takes a version field at all.

### 2.7. Monetary Precision and Rounding

Every monetary amount the system computes — booth fees, refund amounts, cash-out totals, settlement payouts, and the figures in the sales report — is rounded to exactly two decimal places using the round-half-up convention. Where a calculation is composed of several rounded sub-results, the order in which the rounding is applied is pinned by the formula and must be honored exactly as described in §3; the order is not interchangeable, because rounding an intermediate component before combining it can produce a different final cent than combining first and rounding once.

### 2.8. Conserved Quantities and Ledger Invariants

Several quantities in the system are conserved totals that the server maintains as running aggregates and must keep reconciled against the underlying records at all times.

A festival tracks `total_wallet_liability`, the running sum of the `balance` across every wristband whose `lifecycle_status` is `ACTIVE`. Topping up a wallet increases this total, spending at a booth decreases it, cashing out removes the cashed-out balance, and freezing or unfreezing a wristband removes or re-includes its balance respectively, because a frozen wristband is no longer in the `ACTIVE` set. A festival also tracks `total_refund_liability`, the running sum of the `amount` of every refund whose `status` is `ISSUED`; each refund the system issues increments this total.

A zone tracks `allocated_count`, the number of vendor applications against it whose `status` is `APPROVED` or `CONFIRMED` — this is the conserved quantity behind the booth-slot capacity check. A parking lot tracks `sold_count`, the number of sold parking add-ons drawn against it, and a camping area tracks `sold_count`, the number of sold camping add-ons drawn against it. Each of these counters moves in lockstep with the operations that consume or release the corresponding capacity, as described in the workflows of §3.

### 2.9. The Festival Posture Gate

Every child operation in the system is gated by the festival's `operational_posture`, an enumerated lifecycle field that takes one of `PLANNING`, `ON_SALE`, `LIVE`, `SUSPENDED`, `CLOSED`, or `CANCELLED`. The posture acts as a master switch: ticket sales are only permitted while the festival is `ON_SALE`, wristband activation is permitted while `ON_SALE` or `LIVE`, wallet top-ups and spends require the wristband's festival to permit cashless activity, and gate entry requires the festival to be `LIVE`. When a child operation is attempted under a posture that does not permit it, the request is rejected with `ERR_FESTIVAL_POSTURE`. The one posture-driven rule with its own dedicated code is the weather hold: a gate entry attempted while the posture is `SUSPENDED` is rejected with `ERR_FESTIVAL_SUSPENDED`, while exit scans continue to be accepted. The detailed posture transitions and their cascades live in §3.1.

## 3. Business Logic & Workflows

### 3.1. The Festival Lifecycle and Weather Response

A `FestivalDirector` creates a festival by supplying its `name`, a `start_date`, and an `end_date`, both ISO dates of the form YYYY-MM-DD and both inclusive. At creation the director may optionally override three policy knobs: `max_reentries`, the number of re-entry scans allowed after the first entry per wristband, which defaults to 1; `wristband_cashout_pct`, the processing-fee fraction withheld on a wallet cash-out, which defaults to 0.03; and `vendor_commission_pct`, the platform commission fraction withheld from a vendor's cashless gross at settlement, which defaults to 0.08. From the dates the server computes `total_days`, the inclusive count of festival days, which is the number of days obtained by subtracting the start date from the end date and adding one; this count drives both ticket face value and the weather pro-rata refund. A new festival begins with `operational_posture` of `PLANNING`, `current_festival_day` of 0, and both `total_wallet_liability` and `total_refund_liability` at 0.

The posture advances through a director-controlled state machine. From `PLANNING`, opening sales moves the festival to `ON_SALE`, but only if the festival already has at least one zone and at least one stage; this transition is what makes ticket sales permissible to the box office. From `ON_SALE`, going live moves the festival to `LIVE` and, as a side effect, sets `current_festival_day` to 1 and makes gate scans permissible. While `LIVE`, the director may advance `current_festival_day` to a specific 1-indexed day value, supplied as `day`, which must lie between 1 and `total_days`; this bounds how much of the event is considered elapsed for refund purposes. From `LIVE`, when the final day has been reached — that is, when `current_festival_day` equals `total_days` — the director may close the festival, moving the posture to `CLOSED`; closing permanently disables ticket sales and gate scans, although wallet cash-out remains permitted after close so patrons can still recover unspent funds. Each of these posture transitions advances the festival's `version`.

Weather introduces a cycle. From `LIVE`, the director may place a weather hold, moving the posture to `SUSPENDED`. While suspended, new gate entries are rejected with `ERR_FESTIVAL_SUSPENDED` but exits remain permitted, and scheduled performances are not auto-cancelled. From `SUSPENDED`, resuming returns the festival to `LIVE` and permits entries again. This `LIVE` and `SUSPENDED` cycle may repeat as the weather changes.

If the weather does not clear, the director may cancel. Cancellation can be reached from `SUSPENDED` or directly from `ON_SALE`, and the two routes share a divergent refund cascade. In both cases, every ticket whose `status` is `SOLD` or `ACTIVATED` is refunded by the weather pro-rata refund algorithm using `current_festival_day` as the elapsed-days input, the ticket's `status` is set to `REFUNDED`, and each such refund increments the festival's `total_refund_liability`. Because a cancellation from `ON_SALE` happens before the event has begun, `current_festival_day` is 0 there and every ticket is refunded at full face value; a cancellation from `SUSPENDED` happens after one or more days have opened, so refunds are prorated downward by the elapsed days. The ticket refund chains further: if a refunded ticket is linked to a wristband whose `lifecycle_status` is `ACTIVE`, that wristband is automatically frozen to `FROZEN` so no further spend can occur, and freezing it in turn triggers a recompute of `total_wallet_liability` to drop the now-frozen balance out of the active sum — a three-step chain from ticket to wristband to festival liability. The cascade also transitions every performance whose `status` is `SCHEDULED` to `CANCELLED` and every add-on whose `status` is `SOLD` to `REFUNDED`. The cancel transition advances the festival's `version`. Both `CLOSED` and `CANCELLED` are terminal postures.

Every posture transition is guarded. Attempting a transition from a posture in which it is not defined — for example resuming a festival that is not suspended, or closing one that is not live — is rejected with `ERR_INVALID_STATE`. Closing additionally requires that `current_festival_day` equal `total_days`.

### 3.2. Building the Festival: Zones, Stages, Parking, and Camping

Before sales can open, the director lays out the festival's physical and commercial structure. A zone is created with a `code` that is one of `A`, `B`, or `C` — the letter selects the premium surcharge fraction applied to booth fees — and a `slot_capacity` of at least 1, which caps how many booth applications may hold a confirmed slot in that zone; its `allocated_count` starts at 0. A stage is created with a `name` and an optional `changeover_minutes` buffer, a non-negative integer that defaults to 30 and represents the mandatory teardown-and-setup gap enforced after each performance before the next may begin on that stage. A parking lot is created with a `name`, a `capacity` of at least 1 capping the parking passes sellable across the whole festival, and a flat `price_per_pass`; its `sold_count` starts at 0. A camping area is created with a `name`, a `capacity` of at least 1 capping the camping plots sellable, and a per-night `price_per_night`; its `sold_count` starts at 0. Each of zone, stage, parking lot, and camping area records the `festival_id` of its owning festival.

### 3.3. Stages, Artists, and the Schedule

The director schedules performances onto stages. A performance is created against a stage with an `artist_name`, a `starts_at`, and an `ends_at`, both ISO 8601 UTC instants; the server denormalizes the `festival_id` onto the performance from its stage, records the `stage_id`, and sets `status` to `SCHEDULED`. The only other status a performance can take is `CANCELLED`, which the festival cancellation cascade applies to scheduled sets.

Scheduling is subject to three temporal checks. First, the interval must be well-formed: `ends_at` must be strictly later than `starts_at`, or the request is rejected with `ERR_INVALID_INTERVAL`. Second, the new performance must not collide with any other scheduled performance on the same stage once the stage's changeover buffer is taken into account. Treating each interval as half-open from its start up to but not including its end, the new performance conflicts with an existing scheduled one on the same stage when the new start is earlier than the existing end plus the changeover buffer and, simultaneously, the new end plus the changeover buffer is later than the existing start; such a collision is rejected with `ERR_STAGE_CONFLICT`. Third, the same artist must not be double-booked anywhere in the festival across all stages, evaluated with no buffer at all: treating intervals as half-open, the new performance conflicts with an existing scheduled performance of the same `artist_name` in the same festival when the new start is earlier than the existing end and the new end is later than the existing start. Exact adjacency — where one set ends at the precise instant the next begins — is allowed and does not constitute a conflict. An artist overlap is rejected with `ERR_ARTIST_DOUBLE_BOOKED`. The per-stage check carries the changeover buffer; the artist check does not.

### 3.4. Selling Tickets and Add-Ons

While the festival is `ON_SALE`, a `BoxOffice` operator sells tickets. A ticket is sold with a `ticket_type` of either `GA` or `VIP`, a `day_count` that must be between 1 and the festival's `total_days`, and a `purchaser_email` for the holder. The server computes the ticket's `face_value` as the fixed per-day price for the ticket's `ticket_type` multiplied by `day_count` — there is one per-day price for `GA` and a separate per-day price for `VIP`, and the chosen one is multiplied by the number of days the ticket admits to. A new ticket begins with `status` of `SOLD` and a null `wristband_id`; the only other statuses a ticket may reach are `ACTIVATED`, `REFUNDED`, and `VOID`. Selling a ticket when the posture is not `ON_SALE` is rejected with `ERR_FESTIVAL_POSTURE`, and a `day_count` outside the permitted range is rejected with `ERR_DAYCOUNT_RANGE`.

Add-ons attach parking or camping to an existing ticket and are also sold by the box office. An add-on carries a `kind` of either `PARKING` or `CAMPING` and records the `festival_id` and the `ticket_id` it attaches to. A parking add-on must supply a `parking_lot_id` and the parking add-on's `price` is set to that lot's `price_per_pass`; a camping add-on must instead supply a `camping_area_id` and a `nights` count between 1 and `total_days`, and its `price` is computed as the area's `price_per_night` multiplied by `nights`. Supplying the wrong combination — a camping add-on without its `camping_area_id` and `nights`, or a parking add-on without its `parking_lot_id` — is rejected with `ERR_INVALID_REQUEST`, and a `nights` value outside the permitted day range is rejected with `ERR_DAYCOUNT_RANGE`. A new add-on begins with `status` of `SOLD` and can later become `REFUNDED`.

Selling an add-on consumes capacity from the underlying pool. A parking sale requires the lot to have a free pass — that is, the lot's `sold_count` must be strictly below its `capacity` — and on success increments the lot's `sold_count` and advances the lot's `version`; a camping sale likewise requires the area's `sold_count` to be below its `capacity` and increments the area's `sold_count`. When the relevant pool is full, the sale is rejected with `ERR_CAPACITY_FULL`. A parking sale additionally requires the `expected_lot_version` concurrency field to match the lot's current `version` as described in §2.6, failing with `ERR_STALE_LOT_VERSION` on a mismatch.

### 3.5. Voluntary Refunds and the Refund Ledger

A patron may ask the box office to refund a single ticket voluntarily, distinct from a weather-driven cancellation. The fee withheld on a voluntary refund is tiered by how far in advance of the festival the request arrives. The system computes the whole number of days between today and the festival's `start_date` — today being the server's current notion of "now" as set through the test clock — by subtracting today's date from the start date. If that count of days before the event is at least 14, no fee is withheld and the fee fraction is 0.00. If it is at least 7 but fewer than 14, the fee fraction is 0.25. If it is at least 1 but fewer than 7, the fee fraction is 0.50. And if it is below 1 — that is, on the same day as or after the start — the fee fraction is 1.00, meaning no money comes back. The `fee_withheld` is the ticket's `face_value` multiplied by the applicable fee fraction, rounded to two decimal places, and the `refund_amount` recorded as the refund's `amount` is the `face_value` minus that withheld fee, again rounded to two decimal places. A voluntary refund sets `refund_kind` to `VOLUNTARY_TIERED`, transitions the ticket's `status` from `SOLD` to `REFUNDED`, and adds the refund's `amount` to the festival's `total_refund_liability`.

A refund issued by the weather cancellation cascade follows an entirely different, forward-looking algorithm rather than this chronological fee tiering. There the elapsed-days input is the festival's `current_festival_day`, the remaining days are the larger of zero and `total_days` minus elapsed days, and the `refund_amount` is the ticket's `face_value` multiplied by the ratio of remaining days to `total_days`, rounded to two decimal places. The weather variant withholds no cancellation fee, so its `fee_withheld` is 0.00, and it records a `refund_kind` of `WEATHER_PRORATA`. Every refund, by whichever route, is created with `status` of `ISSUED`, which is its only status, records the `festival_id` and the `ticket_id` it pertains to, and contributes its `amount` to the festival's `total_refund_liability`.

### 3.6. Wristbands: Issuance, Activation, and the Cashless Wallet

A wristband is the patron's physical RFID tag and cashless wallet. A `BoxOffice` operator issues one against a festival by supplying its `rfid_uid`, the physical tag UID, which must be unique among non-void wristbands within the same festival; a collision with an existing non-void tag is rejected with `ERR_DUPLICATE_RFID`. A freshly issued wristband records its `festival_id`, starts with `lifecycle_status` of `ISSUED`, `presence_status` of `OUTSIDE`, a `balance` of 0, an `entry_count` of 0, and a `reentry_used` of 0. The wristband carries two independent state dimensions: a lifecycle dimension governing the wallet and issuance, and a presence dimension governing whether the holder is currently inside the gates; the two evolve separately.

On the lifecycle dimension, activation links the wristband to a ticket. To activate, the operator supplies a `ticket_id` referencing a ticket that has `status` of `SOLD`, belongs to the same festival, and currently has a null `wristband_id`; the festival posture must be `ON_SALE` or `LIVE`. Activation sets the ticket's `wristband_id` to this wristband, moves the ticket's `status` from `SOLD` to `ACTIVATED`, and moves the wristband's `lifecycle_status` from `ISSUED` to `ACTIVE`; the presence dimension is untouched and stays `OUTSIDE`. A wristband that was issued but never activated may instead be voided from `ISSUED` to the terminal `VOID`, which frees its `rfid_uid` for reuse within the festival.

Once active, the wallet comes to life. A top-up records a wallet transaction with `kind` of `TOPUP` and a positive `amount`, adds that amount to the wristband's `balance`, and adds it to the festival's `total_wallet_liability`; a top-up requires the wristband's `lifecycle_status` to be `ACTIVE`. A spend records a wallet transaction with `kind` of `SPEND` and a positive `amount`, supplies the `booth_zone_id` of the vendor zone being paid, and on the transaction the server records the `vendor_application_id` of the confirmed vendor occupying that zone at spend time along with the denormalized `festival_id`; a spend subtracts the amount from `balance` and from `total_wallet_liability` and requires the wristband to be `ACTIVE`. A spend may never drive the balance negative: it requires `balance` to be at least the spend `amount`, and a shortfall is rejected with `ERR_INSUFFICIENT_BALANCE`. A wallet transaction's `amount` is always recorded as a positive magnitude in dollars to two decimal places, with its direction implied by `kind`; the four transaction kinds are `TOPUP`, `SPEND`, `CASHOUT`, and `CASHOUT_FEE`, and a transaction records the `wristband_id` of the wallet it affects.

The director may freeze and unfreeze a wristband on the lifecycle dimension. Freezing moves an `ACTIVE` wristband to `FROZEN`, which blocks further spend and triggers a recompute of `total_wallet_liability` to exclude this wristband's balance from the active sum. Unfreezing moves a `FROZEN` wristband back to `ACTIVE`, provided the festival is not `CANCELLED`, and recomputes `total_wallet_liability` to re-include the balance. This freeze-and-unfreeze cycle runs on the lifecycle dimension and leaves presence untouched.

Cashing out closes the wallet. A cash-out is permitted only when the wristband's `lifecycle_status` is `ACTIVE` and its `presence_status` is `OUTSIDE`, meaning the patron must have exited the grounds before recovering funds. The cash-out computes a fee as the pre-cash-out `balance` multiplied by the festival's `wristband_cashout_pct`, rounded to two decimal places, and a refund equal to the pre-cash-out balance minus that fee, again rounded to two decimal places. It writes two wallet transactions — one of `kind` `CASHOUT` and one of `kind` `CASHOUT_FEE` — sets the `balance` to 0, decrements `total_wallet_liability` by the pre-cash-out balance, and moves the wristband's `lifecycle_status` from `ACTIVE` to the terminal `CLOSED`.

### 3.7. Gate Operations: Entry, Exit, and Re-Entry

A `GateAttendant` scans wristbands at the gates, supplying the `wristband_id` and a `direction` of either `ENTER` or `EXIT`; each scan produces a gate event recording the `festival_id`, the `wristband_id`, the `direction`, an `outcome` of `ADMITTED`, `EXITED`, or `DENIED`, and a `deny_reason` that holds the error id of the rejection when the outcome is denied and is null otherwise. An entry scan advances the presence dimension from `OUTSIDE` to `INSIDE`. For an entry to be admitted, the wristband's `lifecycle_status` must be `ACTIVE` and the festival's posture must be `LIVE` rather than `SUSPENDED`; an entry while the festival is suspended is rejected with `ERR_FESTIVAL_SUSPENDED`, and an entry under any other non-permitting posture is rejected with `ERR_FESTIVAL_POSTURE`.

Re-entry is capped. The first entry on a wristband is always allowed, but each subsequent entry is a re-entry; an entry is permitted only when the wristband has not yet been inside (its `entry_count` is still 0) or when the re-entries already used remain below the festival's `max_reentries` cap. On a successful entry the server moves `presence_status` to `INSIDE`, increases `entry_count` by one, and — if the `entry_count` was already at least 1 before this scan — increases `reentry_used` by one as well, then writes a gate event with outcome `ADMITTED`. An entry that would push `reentry_used` to or beyond `max_reentries` is rejected with `ERR_REENTRY_LIMIT`. An entry scan on a wristband that is already `INSIDE` is a double-entry or pass-back attempt and is rejected with `ERR_ALREADY_INSIDE`. An exit scan requires the wristband to be `INSIDE`, moves `presence_status` back to `OUTSIDE`, and writes a gate event with outcome `EXITED`; exits are accepted even while the festival is `SUSPENDED`.

### 3.8. Vendors and the Booth Application Lifecycle

A vendor is registered with a `company_name` and a `contact_email`, and begins with a `payout_total` of 0 that accumulates settlement payouts across its confirmed booths. A booth application is submitted against a festival, supplying the applicant's `vendor_id`, the requested `booth_zone_id`, a `booth_tier` of `STANDARD`, `PREMIUM`, or `FOOD` selecting the daily base rate, a `day_count` between 1 and `total_days` for how many days the booth operates, and an optional `power_addon` boolean for an electrical hookup that defaults to false. A new application starts with `status` of `SUBMITTED`, a null `booth_fee`, and a `fee_paid` of 0. A `day_count` out of range is rejected with `ERR_DAYCOUNT_RANGE`. Submitting and reviewing applications is permitted only while the festival is in `PLANNING` or `ON_SALE`.

The application moves through a branching lifecycle with a revert edge, adjudicated by the `VendorManager` except for the vendor-owned terminal actions. A `VendorManager` starts review, moving the application from `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW`, the manager may either reject the application, moving it to the terminal `REJECTED` with no slot held, or approve it. Approval is the pivotal step: it requires that the target zone have a free slot — its `allocated_count` strictly below its `slot_capacity`, otherwise rejected with `ERR_ZONE_FULL` — and that the `expected_zone_version` match the zone's current `version` as in §2.6, otherwise rejected with `ERR_STALE_ZONE_VERSION`. On a successful approval the server computes the booth fee, persists it on the application, increments the zone's `allocated_count` by one, and advances the zone's `version`; the application moves to `APPROVED`.

From `APPROVED` there are three onward edges. The manager may return the application for revision, reverting it to `UNDER_REVIEW`, but only if `fee_paid` is still 0; the revert is a compensation that decrements the zone's `allocated_count` by one, clears `booth_fee` back to null, and advances the zone's `version`, restoring the slot to the pool. The vendor — and only the owning vendor, enforced by the ownership check that compares the application's `vendor_id` to `X-User-ID` — may pay toward the fee, with each payment of a supplied `amount` adding to `fee_paid`. The owning vendor may confirm the application, moving it from `APPROVED` to `CONFIRMED`, which makes the booth slot permanent for settlement; confirmation requires that `fee_paid` be at least the `booth_fee`, failing with `ERR_FEE_UNPAID` otherwise, and the festival must not be `CANCELLED`. The `allocated_count` is unchanged on confirmation since the slot was already counted at approval. Alternatively the owning vendor may withdraw the application from `APPROVED` to the terminal `WITHDRAWN`, permitted only when `fee_paid` is 0; withdrawal is a compensation that decrements the zone's `allocated_count` by one and advances the zone's `version`, releasing the slot. `REJECTED` and `WITHDRAWN` are terminal states. Any of these transitions attempted from a state in which it is not defined is rejected with `ERR_INVALID_STATE`.

The booth fee is computed at approval by a tiered pricing rule. The base is the per-day tier rate for the application's `booth_tier` multiplied by its `day_count`, where the tier rate is 150.00 for `STANDARD`, 300.00 for `PREMIUM`, and 450.00 for `FOOD`. A surcharge is the base multiplied by the zone-code surcharge fraction, which is 0.20 for zone code `A`, 0.10 for zone code `B`, and 0.00 for zone code `C`. The location fee is the base plus the surcharge, rounded to two decimal places — this first component is rounded before anything is added to it. If `power_addon` is requested, a power fee is the daily power rate of 40.00 multiplied by `day_count`, rounded to two decimal places; if no power is requested the power fee is 0.00. The final `booth_fee` is the location fee plus the power fee, rounded to two decimal places. The pinned order matters: the location fee is rounded first, then the power fee is added and the sum rounded again.

### 3.9. Settlement and Sales Reporting

After the festival has reached `CLOSED`, the director settles each confirmed booth. Settlement computes the booth's payout by an aggregation in a pinned order. First the gross is the sum of the `amount` of every `SPEND` wallet transaction whose `vendor_application_id` is this application, with that sum taken across all such transactions and then rounded to two decimal places — the rounding is applied once to the summed total, never per line. The commission is the gross multiplied by the festival's `vendor_commission_pct`, rounded to two decimal places and applied to the summed gross. The net is the gross minus the commission, rounded to two decimal places. The outstanding fee is the larger of zero and the application's `booth_fee` minus its `fee_paid`. The final payout is the net minus the outstanding, rounded to two decimal places, and it is credited to the vendor's `payout_total`.

The sales report is a festival-scoped set of computed aggregates, each pinning its own status filter. The `ticket_revenue` is the sum of the `face_value` of every ticket whose `status` is `SOLD` or `ACTIVATED`, rounded to two decimal places; refunded and void tickets are excluded. The `addon_revenue` is the sum of the `price` of every add-on whose `status` is `SOLD`, rounded to two decimal places; refunded add-ons are excluded. The `cashless_volume` is the sum of the `amount` of every wallet transaction whose `kind` is `SPEND`, rounded to two decimal places. The `refunds_issued` is the sum of the `amount` of every refund whose `status` is `ISSUED`, rounded to two decimal places. The `net_revenue` is the ticket revenue plus the add-on revenue minus the refunds issued, rounded to two decimal places.

### 3.10. Incidents and the Test Clock

A `GateAttendant` or `FestivalDirector` logs an incident against a festival, supplying an `incident_type` of `LOST_CHILD` or `MEDICAL`, an optional `severity` of `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` that defaults to `LOW`, an optional `linked_wristband_id` for an involved wristband, and optional free-text `notes`. The incident records its `festival_id` and starts with `status` of `OPEN`. An incident moves through a small branching machine with a revert edge. From `OPEN`, it may be escalated to `ESCALATED`, but only when its `severity` is `HIGH` or `CRITICAL`; escalation is open to a director or a gate attendant. From `ESCALATED`, only a `FestivalDirector` may de-escalate it back to `OPEN`. An incident may be resolved to the terminal `RESOLVED` from either `OPEN` or `ESCALATED`; resolving from `OPEN` is open to a director or gate attendant, while resolving from `ESCALATED` is restricted to a `FestivalDirector`. A transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`.

For deterministic date-tier calculations, an administrative capability lets a `FestivalDirector` pin the server's notion of the current moment by supplying a `to_iso8601` instant; this fixed clock is what the voluntary refund tiering reads as "today" when comparing against a festival's `start_date`.

### 3.11. Validation Ordering

When several validations could apply to one request, they are evaluated in a fixed priority order so that the failure a caller sees is deterministic. Authentication comes first: a request missing its headers fails with `ERR_UNAUTHENTICATED` before anything else. Role authorization comes second, failing with `ERR_FORBIDDEN_ROLE`. Existence of path-referenced resources comes third, validated left to right and failing with `ERR_NOT_FOUND`. Body foreign-key resolution comes fourth, failing with `ERR_FK_NOT_FOUND`. Vendor ownership of the target application comes fifth, failing with `ERR_NOT_OWNER`, and applies to the vendor-exclusive confirm, withdraw, and pay-fee actions. The state-machine check that the target is in a state from which the requested transition is defined comes sixth, failing with `ERR_INVALID_STATE`. The festival-posture gate comes seventh, failing with `ERR_FESTIVAL_POSTURE`; the more specific suspended-entry check is eighth, failing with `ERR_FESTIVAL_SUSPENDED`. The optimistic-concurrency version check is ninth, failing with `ERR_STALE_ZONE_VERSION` or `ERR_STALE_LOT_VERSION`. The gate double-entry guard is tenth, failing with `ERR_ALREADY_INSIDE`, and the re-entry-cap guard eleventh, failing with `ERR_REENTRY_LIMIT`. The per-stage scheduling conflict is twelfth (`ERR_STAGE_CONFLICT`) and the festival-wide artist double-booking thirteenth (`ERR_ARTIST_DOUBLE_BOOKED`), with the well-formed-interval check fourteenth (`ERR_INVALID_INTERVAL`). The duplicate-RFID check is fifteenth (`ERR_DUPLICATE_RFID`), the zone-full check sixteenth (`ERR_ZONE_FULL`), the capacity-full check for parking and camping seventeenth (`ERR_CAPACITY_FULL`), the insufficient-balance check eighteenth (`ERR_INSUFFICIENT_BALANCE`), and the fee-unpaid check on confirmation nineteenth (`ERR_FEE_UNPAID`). The day-count range check is twentieth (`ERR_DAYCOUNT_RANGE`), and the catch-all request-shape check — required fields present, enum and type values valid, and the kind-specific field combinations satisfied — is last at twenty-first, failing with `ERR_INVALID_REQUEST`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new resource to a collection return a `201 Created` status code. Operations that modify an existing resource, including state-machine transitions and recorded payments, return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/festivals` | Create a festival in PLANNING | FestivalDirector |
| GET | `/festivals/{id}` | Fetch a festival | FestivalDirector, BoxOffice, VendorManager, GateAttendant, Vendor |
| GET | `/festivals` | List festivals | FestivalDirector, BoxOffice, VendorManager, GateAttendant, Vendor |
| POST | `/festivals/{id}/open-sales` | Open ticket sales (PLANNING → ON_SALE) | FestivalDirector |
| POST | `/festivals/{id}/go-live` | Go live (ON_SALE → LIVE) | FestivalDirector |
| POST | `/festivals/{id}/open-day` | Advance the current festival day | FestivalDirector |
| POST | `/festivals/{id}/weather-hold` | Weather hold (LIVE → SUSPENDED) | FestivalDirector |
| POST | `/festivals/{id}/resume` | Resume (SUSPENDED → LIVE) | FestivalDirector |
| POST | `/festivals/{id}/cancel` | Cancel with refund cascade | FestivalDirector |
| POST | `/festivals/{id}/close` | Close at final day (LIVE → CLOSED) | FestivalDirector |
| GET | `/festivals/{id}/sales-report` | Computed sales aggregates | FestivalDirector, BoxOffice |
| POST | `/festivals/{id}/zones` | Create a booth zone | FestivalDirector |
| GET | `/festivals/{id}/zones` | List zones of a festival | FestivalDirector, VendorManager, Vendor |
| GET | `/zones/{id}` | Fetch a zone | FestivalDirector, VendorManager, Vendor |
| POST | `/festivals/{id}/stages` | Create a stage | FestivalDirector |
| GET | `/festivals/{id}/stages` | List stages of a festival | FestivalDirector, VendorManager, GateAttendant |
| GET | `/stages/{id}` | Fetch a stage | FestivalDirector, VendorManager |
| POST | `/festivals/{id}/parking-lots` | Create a parking lot | FestivalDirector |
| GET | `/festivals/{id}/parking-lots` | List parking lots | FestivalDirector, BoxOffice |
| GET | `/parking-lots/{id}` | Fetch a parking lot | FestivalDirector, BoxOffice |
| POST | `/festivals/{id}/camping-areas` | Create a camping area | FestivalDirector |
| GET | `/festivals/{id}/camping-areas` | List camping areas | FestivalDirector, BoxOffice |
| GET | `/camping-areas/{id}` | Fetch a camping area | FestivalDirector, BoxOffice |
| POST | `/stages/{id}/performances` | Schedule a performance | FestivalDirector |
| GET | `/stages/{id}/performances` | List performances on a stage | FestivalDirector, GateAttendant |
| GET | `/performances` | List performances (filter by festival_id) | FestivalDirector, GateAttendant |
| GET | `/performances/{id}` | Fetch a performance | FestivalDirector, GateAttendant |
| POST | `/festivals/{id}/tickets` | Sell a ticket | BoxOffice |
| GET | `/festivals/{id}/tickets` | List tickets of a festival | FestivalDirector, BoxOffice |
| GET | `/tickets/{id}` | Fetch a ticket | FestivalDirector, BoxOffice |
| GET | `/tickets` | List tickets (filter by wristband_id) | FestivalDirector, BoxOffice |
| POST | `/tickets/{id}/refund` | Patron voluntary refund | BoxOffice |
| POST | `/tickets/{id}/add-ons` | Sell a parking/camping add-on | BoxOffice |
| GET | `/tickets/{id}/add-ons` | List add-ons on a ticket | FestivalDirector, BoxOffice |
| GET | `/add-ons` | List add-ons (filter by festival_id, parking_lot_id, camping_area_id) | FestivalDirector, BoxOffice |
| GET | `/add-ons/{id}` | Fetch an add-on | FestivalDirector, BoxOffice |
| GET | `/refunds/{id}` | Fetch a refund | FestivalDirector, BoxOffice |
| GET | `/festivals/{id}/refunds` | List refunds of a festival | FestivalDirector, BoxOffice |
| GET | `/refunds` | List refunds (filter by ticket_id) | FestivalDirector, BoxOffice |
| POST | `/festivals/{id}/wristbands` | Issue an RFID wristband | BoxOffice |
| GET | `/festivals/{id}/wristbands` | List wristbands of a festival | FestivalDirector, BoxOffice, GateAttendant |
| GET | `/wristbands/{id}` | Fetch a wristband | FestivalDirector, BoxOffice, GateAttendant |
| POST | `/wristbands/{id}/activate` | Activate and link to a SOLD ticket | BoxOffice |
| POST | `/wristbands/{id}/topup` | Add funds to the cashless wallet | BoxOffice |
| POST | `/wristbands/{id}/spend` | Deduct funds at a vendor booth | BoxOffice |
| POST | `/wristbands/{id}/freeze` | Freeze a wristband (ACTIVE → FROZEN) | FestivalDirector |
| POST | `/wristbands/{id}/unfreeze` | Unfreeze a wristband (FROZEN → ACTIVE) | FestivalDirector |
| POST | `/wristbands/{id}/cashout` | Cash out and close (ACTIVE → CLOSED) | BoxOffice |
| POST | `/wristbands/{id}/void` | Void an unactivated wristband (ISSUED → VOID) | BoxOffice |
| GET | `/wristbands/{id}/wallet-txns` | List wallet txns of a wristband | FestivalDirector, BoxOffice |
| GET | `/wallet-txns` | List wallet txns (filter by festival_id, booth_zone_id, vendor_application_id) | FestivalDirector, BoxOffice |
| GET | `/wallet-txns/{id}` | Fetch a wallet txn | FestivalDirector, BoxOffice |
| POST | `/festivals/{id}/gate-scan` | Scan a wristband at the gate | GateAttendant |
| GET | `/festivals/{id}/gate-events` | List gate events of a festival | FestivalDirector, GateAttendant |
| GET | `/gate-events` | List gate events (filter by wristband_id) | FestivalDirector, GateAttendant |
| GET | `/gate-events/{id}` | Fetch a gate event | FestivalDirector, GateAttendant |
| POST | `/vendors` | Register a vendor | VendorManager, Vendor |
| GET | `/vendors/{id}` | Fetch a vendor | FestivalDirector, VendorManager, Vendor |
| POST | `/festivals/{id}/vendor-applications` | Submit a booth application | Vendor, VendorManager |
| GET | `/festivals/{id}/vendor-applications` | List applications of a festival | FestivalDirector, VendorManager |
| GET | `/vendor-applications/{id}` | Fetch an application | FestivalDirector, VendorManager, Vendor |
| GET | `/vendor-applications` | List applications (filter by vendor_id, booth_zone_id) | FestivalDirector, VendorManager, Vendor |
| POST | `/vendor-applications/{id}/start-review` | Start review (SUBMITTED → UNDER_REVIEW) | VendorManager |
| POST | `/vendor-applications/{id}/approve` | Approve (UNDER_REVIEW → APPROVED) | VendorManager |
| POST | `/vendor-applications/{id}/reject` | Reject (UNDER_REVIEW → REJECTED) | VendorManager |
| POST | `/vendor-applications/{id}/return-for-revision` | Return for revision (APPROVED → UNDER_REVIEW) | VendorManager |
| POST | `/vendor-applications/{id}/pay-fee` | Record a booth-fee payment | Vendor |
| POST | `/vendor-applications/{id}/confirm` | Confirm (APPROVED → CONFIRMED) | Vendor |
| POST | `/vendor-applications/{id}/withdraw` | Withdraw (APPROVED → WITHDRAWN) | Vendor |
| POST | `/vendor-applications/{id}/settle` | Settle a confirmed booth at close | FestivalDirector |
| POST | `/festivals/{id}/incidents` | Log a lost-child / medical incident | GateAttendant, FestivalDirector |
| GET | `/festivals/{id}/incidents` | List incidents of a festival | FestivalDirector, GateAttendant |
| GET | `/incidents/{id}` | Fetch an incident | FestivalDirector, GateAttendant |
| GET | `/incidents` | List incidents (filter by linked_wristband_id) | FestivalDirector, GateAttendant |
| POST | `/incidents/{id}/escalate` | Escalate (OPEN → ESCALATED) | FestivalDirector, GateAttendant |
| POST | `/incidents/{id}/deescalate` | De-escalate (ESCALATED → OPEN) | FestivalDirector |
| POST | `/incidents/{id}/resolve` | Resolve (OPEN\|ESCALATED → RESOLVED) | FestivalDirector, GateAttendant |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant | FestivalDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DAYCOUNT_RANGE` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FESTIVAL_POSTURE` | 409 |
| `ERR_FESTIVAL_SUSPENDED` | 409 |
| `ERR_ALREADY_INSIDE` | 409 |
| `ERR_REENTRY_LIMIT` | 409 |
| `ERR_STAGE_CONFLICT` | 409 |
| `ERR_ARTIST_DOUBLE_BOOKED` | 409 |
| `ERR_DUPLICATE_RFID` | 409 |
| `ERR_ZONE_FULL` | 409 |
| `ERR_CAPACITY_FULL` | 409 |
| `ERR_FEE_UNPAID` | 409 |
| `ERR_INSUFFICIENT_BALANCE` | 422 |
| `ERR_STALE_ZONE_VERSION` | 412 |
| `ERR_STALE_LOT_VERSION` | 412 |

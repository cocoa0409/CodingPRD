# Book Fair & Author Event Management API — Product Requirements Document

## 1. Introduction

A book-fair company runs Scholastic-style fairs: multi-day retail events hosted on a school's premises, stocked largely on consignment from publishers, headlined by visiting authors, and closed out with a financial settlement that splits proceeds between the publisher, the fair operator, and the school. Each fair touches venue scheduling against a shared school or store calendar, consignment-term negotiation with a publisher, author booking with travel and honorarium terms, signing-line crowd management for both ticketed and free events, preorder and backlist stock planning, register sales, post-fair inventory reconciliation, unsold-stock returns, promotional outreach through local media, and finally a profit-share payout that the school may take as cash or as scrip.

This document specifies the REST API that coordinates that entire lifecycle. Six distinct operator populations — company staff, school liaisons, publisher representatives, author representatives, cashiers, and signing-line staff — share the same resources under a segregation-of-duties model in which no actor both creates and approves a financial instrument. A server-owned logical clock, rather than wall-clock time, governs offer expiry and media embargoes so that multi-party negotiations remain deterministic. Three write operations are guarded by optimistic concurrency so that a negotiating party never overwrites a counter-offer it has not seen, and every monetary figure is pinned to an explicit rounding doctrine so that two independent implementations arrive at the same cent totals. Sections 2 through 5 define the global contract, the business workflows, the endpoint table, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two identity headers: `X-User-ID` and `X-User-Role`. If either header is missing or empty, the request is rejected with `ERR_MISSING_HEADERS` (HTTP 400). If the named role is not in the endpoint's authorized role list, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403).

Exactly six roles exist, spelled as follows: `Organizer`, `SchoolCoordinator`, `PublisherRep`, `AuthorRep`, `Cashier`, `LineStaff`.

Three roles are **entity-backed**. When `X-User-Role` is `SchoolCoordinator`, `X-User-ID` is the `id` of the acting `Party` whose `kind` is `SCHOOL`; when it is `PublisherRep`, `X-User-ID` is the `id` of a `Party` whose `kind` is `PUBLISHER`; when it is `AuthorRep`, `X-User-ID` is the `id` of a `Party` whose `kind` is `AUTHOR`. Ownership checks on any resource that references one of these parties compare the resource's foreign-key field — a fair's `school_party_id`, an agreement's `publisher_party_id`, or a booking's `author_party_id` — to `X-User-ID`. If the referenced `Party` does not exist, the request fails with `ERR_PARTY_NOT_FOUND` (HTTP 404); if the party exists but its `kind` does not match the role, the request fails with `ERR_ROLE_PARTY_KIND_MISMATCH` (HTTP 403); if the party simply is not the party scoped to the resource, the request fails with `ERR_PARTY_SCOPE_MISMATCH` (HTTP 403).

The remaining three roles are **opaque**. When `X-User-Role` is `Organizer`, `Cashier`, or `LineStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on the `Reconciliation` that a close-sales action spawns — but it never compares it to any entity's `id`.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and may not be negative. A non-integer or out-of-range `limit` or `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Results are always sorted by `created_at` in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in its `meta` object. List endpoints also accept optional equality filters drawn from the resource's own foreign keys and enumerations (for example `fair_id`, `status`, `line_type`, `mode`, `kind`, `channel`, `venue_key`, `publisher_party_id`, `author_party_id`, `school_party_id`, `agreement_id`, `stock_line_id`, `booking_id`, or `session_id`, as applicable per resource).

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, a `created_at` timestamp, and — with one exception — an `updated_at` timestamp and a `version` integer. Timestamps are ISO 8601 UTC with three fractional digits. Incoming datetime strings are parsed leniently: a value without a timezone designator is read as UTC, and a non-UTC offset is accepted and normalized to UTC. The `version` is an integer that starts at 1 on creation and increments by one on every state- or field-mutating write; it is the basis of the optimistic-concurrency rules in §2.6. The single exception is the `SigningTicket`: tickets are high-volume line entitlements and carry only `id` and `created_at` — both `updated_at` and `version` are absent from ticket resources.

### 2.5. The Logical Clock and Offer Expiry

The server keeps a **logical clock** that never reads wall-clock time. At server startup the logical clock is exactly `2026-08-01T00:00:00Z`. An `Organizer`-only test-driving capability advances the clock to a supplied `to_iso8601` instant — the server does not enforce forward motion and accepts any instant; the response reports `current_utc` and `expired_agreement_ids`.

Advancing the clock runs an **offer-expiry sweep**: every `ConsignmentAgreement` still in `PROPOSED` or `COUNTERED` whose `offer_expires_at` is at or before the new clock instant transitions to `EXPIRED`. Author bookings are deliberately not swept — no booking is auto-expired or auto-declined by the clock; a booking whose offer has lapsed simply surfaces `ERR_OFFER_EXPIRED` (HTTP 409) on the next counter or accept attempt. Agreement expiry is additionally applied lazily: any access to an agreement whose `offer_expires_at` has been reached transitions it to `EXPIRED` on the spot.

### 2.6. Optimistic Concurrency Control

Exactly three write operations are version-guarded; no other endpoint accepts a version field.

- Countering a consignment agreement requires `expected_agreement_version` carrying the client's last-observed `version` of the `ConsignmentAgreement`. If another writer has advanced the agreement's version since the client last read it — the classic case being the other negotiating party posting a counter-offer that legitimately supersedes the prior live offer — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting terms it has not observed.
- Countering an author booking requires `expected_booking_version` against the `AuthorBooking`'s current `version`, under the same rule and the same `ERR_STALE_VERSION` (HTTP 412) rejection.
- Posting physical counts to a reconciliation requires `expected_reconciliation_version` against the `Reconciliation`'s current `version`, again with `ERR_STALE_VERSION` (HTTP 412), because a recount legitimately supersedes the prior count set and a stale writer must not silently overwrite it.

### 2.7. Monetary Precision and Rounding Doctrine

All monetary amounts are integer cents. Two rounding doctrines are pinned and must not be reordered. Under the **per-line-then-sum** doctrine — used by publisher remittance and by return credits — each line's amount is rounded half-up to whole cents first, and the rounded line amounts are then summed; rounding only after summation is a prohibited alternative because the two orders can differ by cents. Under the **single-final-rounding** doctrine — used by the school profit share and the scrip uplift — the full computation is carried out unrounded and rounded half-up exactly once at the end. Quantities, attendance counts, and capacity figures are integer units with no rounding. Percentage fields such as `discount_pct` are decimal fractions between 0 and 1 inclusive, not whole percents.

### 2.8. Two Overlap Regimes: Venue Blocks and Signing-Floor Space

Venue-calendar conflicts and signing-floor capacity use **different interval geometry**, and the difference is load-bearing.

A `VenueSlot` occupies the venue calendar over the half-open interval that begins `setup_buffer_minutes` before its `start_at` and ends `teardown_buffer_minutes` after its `end_at`, exclusive of the final instant. Creating a slot is rejected with `ERR_VENUE_CONFLICT` (HTTP 409) when that effective buffered interval intersects the effective interval of any non-`RELEASED` slot sharing the same `venue_key`. Because the intervals are half-open, one block ending at exactly the instant another begins — buffers included — is not a conflict.

Signing sessions instead consume floor space over the **closed** interval from `start_at` through `end_at`, both endpoints included. Creating a session is rejected with `ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED` (HTTP 409) when the sum of `line_space_units` over the fair's non-`CANCELLED` sessions whose closed windows intersect the candidate's closed window, plus the candidate's own `line_space_units`, would exceed the fair's `signing_floor_capacity_units`. Two sessions whose windows merely touch at an endpoint do overlap under this regime — the opposite of the venue-calendar rule.

### 2.9. Validation Pipeline and Priority Ordering

Incoming requests are checked against a fixed ladder of rule categories; a request that fails several checks reports the earliest one on the ladder. The ladder runs: authentication checks first — header presence, role membership, party existence, party-kind match (priorities 1 through 4) — then resource existence, with path resources resolved left to right and the first missing path or body reference yielding `ERR_NOT_FOUND` (HTTP 404, priority 5); then party scope (`ERR_PARTY_SCOPE_MISMATCH`, priority 6); then request shape (priority 7); then state legality, covering both whether the target entity is in a state from which the requested transition exists — including terminal-state lockdown — and every cross-entity state gate (priority 8, `ERR_INVALID_STATE`, `ERR_FAIR_NOT_OPEN`, `ERR_AGREEMENT_NOT_ACCEPTED`, `ERR_RECONCILIATION_NOT_APPROVED`, `ERR_BOOKING_NOT_TRAVEL_READY`, `ERR_SESSION_NOT_SIGNING`); then stale-version concurrency (`ERR_STALE_VERSION`, priority 9); then the fire-marshal concurrency cap (`ERR_LINE_CAPACITY_EXCEEDED`, priority 10); then the temporal checks — venue overlap, signing-floor capacity, signing-window containment, embargo, offer expiry (priorities 11 through 15); then the negotiation round cap (`ERR_NEGOTIATION_ROUNDS_EXHAUSTED`, priority 16); then duplicate-resource checks (`ERR_DUPLICATE_RESOURCE`, priority 17); then session capacity (`ERR_SIGNING_CAPACITY_EXCEEDED`, priority 18); then physical-quantity checks (`ERR_STOCK_NOT_AVAILABLE`, `ERR_DAMAGE_EXCEEDS_ON_HAND`, `ERR_OVER_DELIVERY`, `ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND`, `ERR_FIRM_SALE_NOT_RETURNABLE`, priority 19); then referential cross-checks (`ERR_LINE_FAIR_MISMATCH`, `ERR_TICKET_SESSION_MISMATCH`, priority 20); then the fiscal checks — markdown band, tender sufficiency, promo budget, travel cap (priorities 21 through 24); and finally the closing integrity gates — segregation of duties, counts completeness, variance tolerance, and the preorder intake window (priorities 25 through 28).

Request-shape validation (priority 7, `ERR_VALIDATION`, HTTP 400) rejects missing required fields, wrong types, invalid enum values, out-of-range numbers — quantities must be positive, save that a delivered `qty_delivered` and a counted `qty_on_hand` may be zero; percentage fields must lie between 0 and 1 inclusive; an end instant must be strictly after its start instant — and any unknown field. An explicit JSON `null` for a field is treated as absent: it fails a required field as missing and is ignored for an optional one. It also enforces that a venue slot's `venue_key` equals the linked fair's `venue_key`. Where a workflow pins a relative order among specific checks — sale tender runs state before fiscal, ticket admit runs state then safety then referential, reconciliation approval runs segregation of duties before the variance gate — §3 states that order alongside the workflow. Unless a workflow in §3 pins such a gate, creating a resource is not gated on the lifecycle status of the fair, booking, or session it references: venue slots, consignment agreements, stock lines, author bookings, signing sessions, signing tickets, sales, and media blasts may all be created while their parent entity is in any state.

### 2.10. Party-Scoped Operations

The scope checks of §2.1 apply to a fixed set of operations: venue-slot confirmation is scoped to the fair's school; agreement counter, accept, and decline on the publisher side are scoped to the agreement's `publisher_party_id`; booking counter, accept, decline, and cancel on the author side are scoped to the booking's `author_party_id`; reconciliation accept and dispute are scoped to the publisher of the fair's accepted agreement; return-authorization approve and reject are scoped to the agreement's publisher; payout approval is scoped to the payout's `school_party_id`; and media-blast approve and reject are scoped to the fair's school. In every case a wrong-party actor is refused with `ERR_PARTY_SCOPE_MISMATCH` (HTTP 403). All read endpoints — every list and every single-resource read — are available to all six roles; the writes named in §3 carry the role restrictions shown in §4.

### 2.11. Derived Fair Totals and Snapshot Semantics

A fair carries five derived cent totals that the server maintains as events occur: `gross_sales_cents`, `firm_purchases_cents`, `publisher_remittance_cents`, `return_credits_cents`, and `honorarium_total_cents`. Each is recomputed at the moment its contributing event lands — gross sales on every tender, void, or preorder fulfillment; firm purchases on every backlist delivery; remittance locked once at reconciliation approval; return credits on every confirmed return credit; honoraria on every booking settlement or kill-fee accrual — and each recomputation is a mutation of the fair that refreshes its `updated_at` and bumps its `version`. The profit-share payout is the deliberate exception to live derivation: a payout that has been calculated captures a **snapshot** of the fair's totals at calculation time, and later mutations — a newly credited return, a late damage write-off — do not refresh it. Revising the payout requires an explicit recalculation, which returns it to `DRAFT` and clears its computed amounts.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Fair: Parties, Venues, and Scheduling

Before anything else, an `Organizer` registers the parties involved: each `Party` is created with a `kind` — exactly one of `SCHOOL`, `PUBLISHER`, or `AUTHOR`, immutable after creation — plus a display `name` and a `contact_email`. Any authenticated role may later read a party.

With a school party on file, the organizer creates the `Fair` itself, supplying `school_party_id` (which must reference a party of `kind` `SCHOOL` — a reference to a party of any other kind is rejected with `ERR_VALIDATION` (HTTP 400) — and thereafter scopes `SchoolCoordinator` ownership), a `title`, the `venue_key` identifying the shared venue calendar, `planned_start_date` and `planned_end_date` as ISO dates with the end no earlier than the start, the aggregate `signing_floor_capacity_units` that overlapping signing sessions may consume (a positive integer), and the `promo_budget_cents` ceiling on approved media spend (zero or more). A new fair is `DRAFT`, all five derived totals from §2.11 start at zero, and `preorder_allocation_run` is false.

The organizer then holds venue blocks. Each `VenueSlot` is created with `fair_id`, a `venue_key` that must equal the linked fair's `venue_key`, a `purpose` of `SETUP`, `FAIR_DAY`, `AUTHOR_EVENT`, or `TEARDOWN`, a `start_at` and `end_at` in ISO 8601 UTC with the end strictly after the start, and non-negative `setup_buffer_minutes` and `teardown_buffer_minutes`. The buffered half-open overlap check of §2.8 runs at creation against every non-`RELEASED` slot on the same `venue_key`. A slot begins `HELD`; confirmation — the `HELD` → `CONFIRMED` step — belongs to the `SchoolCoordinator` of the fair's school and is only possible while the fair is `DRAFT` or `SCHEDULED`. An organizer may release a slot from either `HELD` or `CONFIRMED`, moving it to `RELEASED`; a released slot stops constraining the venue calendar.

Scheduling the fair moves it `DRAFT` → `SCHEDULED` and requires at least one of the fair's venue slots to be `CONFIRMED`. Attempting any lifecycle action from a state that does not offer it is rejected with `ERR_INVALID_STATE` (HTTP 409) — the same response an actor gets when poking at an entity in a terminal state.

Cancellation hangs over the whole pre-settlement lifecycle. An organizer may cancel a fair from `DRAFT`, `SCHEDULED`, `STOCKING`, or `OPEN`, optionally supplying a `reason`, which is validated as a string but not persisted, provided no sale of the fair is currently `TENDERED`. The cancellation cascades in a deliberate order: first every `HELD` or `CONFIRMED` venue slot of the fair is released; then every non-terminal author booking of the fair is cancelled, accruing the kill fee described in §3.4; each booking so cancelled cancels its own non-terminal signing sessions (`SCHEDULED`, `OPEN_FOR_SIGNING`, or `CLOSED_FOR_SIGNING` become `CANCELLED`) — an effect of the booking transition, not of the fair directly; each session so cancelled voids its own non-terminal tickets (`ISSUED` or `ADMITTED` become `VOIDED`) — an effect of the session transition; finally every preorder still `PLACED` or `ALLOCATED` is cancelled, releasing any held stock. The fair ends `CANCELLED`, a terminal state.

### 3.2. Consignment Negotiation with the Publisher

Stocking a fair begins with terms. The organizer opens a `ConsignmentAgreement` by proposing six terms to a publisher: `discount_pct` (the organizer's discount off list price), `return_cap_pct` (the maximum fraction of delivered `FRONTLIST` copies returnable at full credit), `restocking_fee_pct` (the fee fraction deducted from credit on over-cap returns), `markdown_allowance_pct` (the deepest sell-price markdown below list that cashiers may apply) — each of the four a decimal fraction between 0 and 1 inclusive — plus `freight_responsibility` (`PUBLISHER` or `ORGANIZER`) and `offer_expiry_hours`, a positive integer number of hours after which the offer lapses. The request names `fair_id` and `publisher_party_id`; the referenced party must be of `kind` `PUBLISHER` (any other kind is rejected with `ERR_VALIDATION`, HTTP 400), and only one non-terminal agreement may exist per fair-and-publisher pair — a second live one is refused with `ERR_DUPLICATE_RESOURCE` (HTTP 409). A new agreement is `PROPOSED` with `negotiation_round` 1, `offered_by` `ORGANIZER`, and `offer_expires_at` set to the current logical clock plus `offer_expiry_hours`.

Negotiation is a cyclic exchange. While the agreement is `PROPOSED` — meaning the organizer holds the live offer — the scoped `PublisherRep` may counter it, which replaces all six terms wholesale with the payload, flips the agreement to `COUNTERED` with `offered_by` `PUBLISHER`, increments `negotiation_round` by one, resets `offer_expires_at` to the clock plus the new `offer_expiry_hours`, and bumps the agreement's `version`. While it is `COUNTERED` — the publisher holding the live offer — the `Organizer` may counter in the same fashion, flipping it back to `PROPOSED` with `offered_by` `ORGANIZER`. Every counter carries `expected_agreement_version` per §2.6. A counter is refused when the live offer has lapsed (`ERR_OFFER_EXPIRED`, HTTP 409 — and an agreement whose expiry has passed is instead transitioned to `EXPIRED`), and refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409) once the round counter would leave the six-round cap for agreements: a counter is only legal while `negotiation_round` is still below six.

Acceptance belongs to the side that does not hold the live offer: the scoped `PublisherRep` accepts a `PROPOSED` agreement, and the `Organizer` accepts a `COUNTERED` one. Acceptance moves the agreement to `ACCEPTED` and freezes its terms; the fair now has a consignment basis. Like a counter, an accept attempted after the live offer has lapsed is refused with `ERR_OFFER_EXPIRED` (HTTP 409) and transitions the agreement to `EXPIRED`; a decline instead meets the lazy expiry of §2.5 first and so reports the now-terminal state with `ERR_INVALID_STATE`. Either side may instead decline from `PROPOSED` or `COUNTERED`, ending the negotiation in `DECLINED`. `ACCEPTED`, `DECLINED`, and `EXPIRED` are all terminal.

### 3.3. Building the Inventory Plan: Stock Lines, Delivery, and Damage

Once an agreement is `ACCEPTED`, the organizer moves the fair `SCHEDULED` → `STOCKING`; the transition is impossible without at least one accepted consignment agreement on the fair.

Inventory is planned as `StockLine` records. Each line names `fair_id`, the `agreement_id` of an agreement belonging to the same fair (a cross-fair agreement is rejected with `ERR_LINE_FAIR_MISMATCH`, HTTP 409), the book's `isbn` (an ISBN-13; the server checks only that it is a string, never its format), a `title`, a positive `list_price_cents`, a `line_type`, and a positive `qty_committed` — the number of copies ordered from the publisher. The `line_type` is immutable after creation and takes one of two values: `FRONTLIST`, meaning consignment stock paid for only when sold, or `BACKLIST`, meaning a firm purchase whose cost accrues at delivery. A new line is `QUOTED` with all quantity counters at zero and `qty_on_hand_counted` null.

Committing a line (`QUOTED` → `COMMITTED`) requires the line's agreement to be `ACCEPTED` — otherwise `ERR_AGREEMENT_NOT_ACCEPTED` (HTTP 409) — and the fair to be `SCHEDULED` or `STOCKING`. Delivery (`COMMITTED` → `DELIVERED`) records a non-negative payload `qty_delivered` — zero is permitted — that may not exceed `qty_committed` (`ERR_OVER_DELIVERY`, HTTP 409) and requires the fair to be `STOCKING` or `OPEN`. Delivery sets `qty_delivered`, recomputes `qty_available_for_sale`, and — for `BACKLIST` lines only — accrues the firm-purchase cost onto the fair: `firm_purchases_cents` grows by the per-line amount computed as `qty_delivered` times `list_price_cents` scaled by one minus the agreement's `discount_pct`, rounded half-up per line before being added.

Availability obeys a copy-conservation invariant. At all times after delivery, a line's `qty_delivered` equals the sum of `qty_held_preorder`, `qty_sold`, `qty_damaged`, `qty_returned_shipped`, and `qty_available_for_sale`; equivalently, `qty_available_for_sale` is what remains of the delivered copies after held, sold, damaged, and shipped-back copies are subtracted. Every mutation that touches any of those counters — delivery, preorder allocation, fulfillment, cancellation, tender, void, damage, return shipment — recomputes availability immediately.

Damaged stock is written off by the organizer with a payload `qty`, but only against a `DELIVERED` line, only while the fair is `OPEN` or `RECONCILING`, and only up to the unsold, unheld on-hand quantity: `qty` may not exceed `qty_delivered` minus `qty_sold`, minus `qty_damaged`, minus `qty_returned_shipped`, minus `qty_held_preorder` (`ERR_DAMAGE_EXCEEDS_ON_HAND`, HTTP 409). Recording damage during `RECONCILING` is the sanctioned shrink-absorption path — the reconciliation's expected-on-hand figures are recomputed from current counters, so a write-off posted mid-reconciliation moves the books into agreement with the shelf. When the fair's reconciliation is eventually approved, every `DELIVERED` line transitions to `RECONCILED`, its counters freeze, and any further sale, damage, or return against it is rejected.

### 3.4. Author Engagement: Booking Negotiation, Travel, and Signing Sessions

An `AuthorBooking` opens when the organizer invites an author: the request carries `fair_id`, an `author_party_id` referencing an `AUTHOR` party (any other kind is rejected with `ERR_VALIDATION`, HTTP 400; the party thereafter scopes `AuthorRep` ownership), and the offer terms — a non-negative `base_honorarium_cents`, a non-negative `travel_cap_cents` capping reimbursable travel, a `bonus_threshold_attendees` of at least one, a non-negative `bonus_base_cents`, a non-negative `bonus_per_attendee_cents`, and a positive integer `offer_expiry_hours`. No uniqueness constraint applies: a fair may hold several bookings for the same author. The booking begins `INVITED` at `negotiation_round` 1 with `offered_by` `ORGANIZER` and `offer_expires_at` set from the logical clock. Two of its money fields start null — `travel_actual_cents` until travel is booked, `settled_total_cents` until the booking is settled — while `accrued_bonus_cents` starts at zero and `kill_fee_cents` likewise starts at zero, remaining zero unless the booking is cancelled after confirmation.

The negotiation mirrors the consignment exchange with tighter limits. While `INVITED` — organizer holding the offer — the scoped `AuthorRep` counters, moving the booking to `NEGOTIATING` with `offered_by` `AUTHOR`; while `NEGOTIATING`, the organizer counters back to `INVITED`. Each counter replaces the offer terms wholesale, increments the round, resets the expiry from the clock, and bumps the booking's `version`, and each carries `expected_booking_version` under §2.6. Bookings allow only four negotiation rounds — a counter is only legal while `negotiation_round` is still below four and is otherwise refused with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409) — and lapsed offers report `ERR_OFFER_EXPIRED` — recall from §2.5 that the clock sweep never expires a booking on its own. Acceptance belongs to the non-offering side: the scoped `AuthorRep` accepts an `INVITED` booking, the `Organizer` accepts a `NEGOTIATING` one, and either way the terms freeze at `CONFIRMED`. Either side may decline from `INVITED` or `NEGOTIATING`, ending at `DECLINED`.

Travel comes next. The organizer records actual travel spend as `travel_actual_cents`, moving the booking `CONFIRMED` → `TRAVEL_BOOKED`; the recorded amount may not exceed the booking's `travel_cap_cents` (`ERR_TRAVEL_CAP_EXCEEDED`, HTTP 409).

With travel booked, signing sessions can run. The organizer schedules a `SigningSession` with `booking_id`, `fair_id`, an immutable `mode` of `TICKETED` or `FREE` — the mode decides both the kind of entitlement issued and whether the session can ever earn a bonus — a `start_at` and `end_at` with the end strictly after the start, a positive `line_space_units` footprint counted against the fair's floor capacity under the closed-interval rule of §2.8, a positive `capacity_seats` bounding live entitlements, and a positive `admit_concurrent_cap` no greater than `capacity_seats`. The booking must belong to the same fair as the request's `fair_id` (`ERR_LINE_FAIR_MISMATCH`, HTTP 409). A new session is `SCHEDULED` with `attendance_count` and `bonus_cents` null.

Cancelling a booking is where the kill-fee schedule lives. From `CONFIRMED` or `TRAVEL_BOOKED`, either the organizer or the scoped `AuthorRep` may cancel the booking; the accrued `kill_fee_cents` is one quarter of `base_honorarium_cents` — rounded half-up — when cancelled from `CONFIRMED`, and one half of `base_honorarium_cents` — rounded half-up — when cancelled from `TRAVEL_BOOKED`. Every non-terminal signing session of the booking is cancelled in cascade, and each of those sessions voids its non-terminal tickets. The fair's `honorarium_total_cents` is recomputed to include the kill fee. When cancellation arrives via the fair-level cascade of §3.1 instead, bookings in `INVITED` or `NEGOTIATING` accrue no kill fee at all — the schedule is zero from those states, one quarter of base from `CONFIRMED`, one half of base from `TRAVEL_BOOKED` — while the session-and-ticket cascade runs identically.

### 3.5. Running the Signing Line

Line staff open a session for signing only inside its window. The `SCHEDULED` → `OPEN_FOR_SIGNING` step is performed by `LineStaff` and is gated by three checks evaluated in ladder order — state legality before the temporal window: the session's booking must be `TRAVEL_BOOKED` (`ERR_BOOKING_NOT_TRAVEL_READY`, HTTP 409), the session's fair must be `OPEN` (`ERR_FAIR_NOT_OPEN`, HTTP 409), and the logical clock must fall within the session's `start_at`-to-`end_at` window with both endpoints included (`ERR_OUTSIDE_SIGNING_WINDOW`, HTTP 409).

Entitlements are issued by `LineStaff` naming `session_id` and `holder_name`. The issued record's `kind` is derived from the session's `mode` at issue time — `TICKET` for a `TICKETED` session, `WRISTBAND` for a `FREE` one — and its status starts `ISSUED`. Issuance is capacity-capped: the number of the session's live entitlements — tickets in `ISSUED`, `ADMITTED`, or `REDEEMED` — may reach but never exceed `capacity_seats`, so an issue attempted when the live count already equals `capacity_seats` is refused with `ERR_SIGNING_CAPACITY_EXCEEDED` (HTTP 409). Recall from §2.4 that tickets carry no `version` and no `updated_at`.

Admission is the three-check gate. Admitting a ticket (`ISSUED` → `ADMITTED`) takes a payload `session_id` identifying the session being entered, and the checks run in a pinned order: before the named trio, the ticket itself must be `ISSUED` (`ERR_INVALID_STATE`, HTTP 409); first of the trio, the **payload** session's state — it must be `OPEN_FOR_SIGNING` (`ERR_SESSION_NOT_SIGNING`, HTTP 409); then the fire-marshal safety cap on that same payload session — the count of its tickets currently `ADMITTED` may reach but never exceed `admit_concurrent_cap`, so an admit attempted when that count already equals the cap is refused with `ERR_LINE_CAPACITY_EXCEEDED` (HTTP 409); and only then the referential match — the payload `session_id` must equal the ticket's own `session_id` (`ERR_TICKET_SESSION_MISMATCH`, HTTP 409). All session-scoped checks run against the payload session; the ticket's own session is consulted only for the final match.

Redemption records the signed book: an `ADMITTED` ticket becomes `REDEEMED` while its session is `OPEN_FOR_SIGNING` or `CLOSED_FOR_SIGNING`; against any other session state the redeem is refused with `ERR_SESSION_NOT_SIGNING`. Line staff may also void an `ISSUED` or `ADMITTED` ticket outright, moving it to `VOIDED` and releasing the live entitlement — the session's live-entitlement count decreases by one.

Closing the line is the `OPEN_FOR_SIGNING` → `CLOSED_FOR_SIGNING` step, again by `LineStaff`. Two things happen atomically: every ticket still `ISSUED` is swept to `NO_SHOW`, and `attendance_count` is frozen as the number of `ADMITTED` tickets plus the number of `REDEEMED` tickets at that moment.

Reconciling the session belongs to the organizer and requires the session's booking to be outside its terminal states. The `CLOSED_FOR_SIGNING` → `RECONCILED` step computes `bonus_cents`: a `FREE` session always earns zero; a `TICKETED` session earns zero when the frozen `attendance_count` is below the booking's `bonus_threshold_attendees`, and otherwise earns `bonus_base_cents` plus `bonus_per_attendee_cents` multiplied by the excess of attendance over the threshold — attendance exactly equal to the threshold triggers the bonus. The computed bonus bubbles up: the booking's `accrued_bonus_cents` grows by `bonus_cents`, a mutation that bumps the booking's `version`.

An organizer may also cancel a session from `SCHEDULED`, `OPEN_FOR_SIGNING`, or `CLOSED_FOR_SIGNING`; the cancellation voids every `ISSUED` or `ADMITTED` ticket while `REDEEMED` history is preserved, and `RECONCILED` and `CANCELLED` are the session's terminal states.

### 3.6. Preorders, Opening-Day Allocation, and Register Sales

Preorder intake runs while the fair is being prepared. A `Cashier` places a `Preorder` with `fair_id`, `stock_line_id`, `customer_name`, and a positive `qty`, but only while the fair is `SCHEDULED` or `STOCKING` — intake at any other time is refused with `ERR_PREORDER_WINDOW_CLOSED` (HTTP 409), and because that window check sits at the very end of the validation ladder, a preorder whose stock line belongs to a different fair is reported as `ERR_LINE_FAIR_MISMATCH` even when the window is also closed. A new preorder is `PLACED` with `fulfillment_price_cents` null.

Opening the fair — `STOCKING` → `OPEN` — requires that no stock line remain `COMMITTED`: every committed line must have been delivered. The open transition runs **preorder allocation** exactly once and sets `preorder_allocation_run` to true. Every `PLACED` preorder of the fair is processed in a pinned order — `created_at` ascending, then `qty` ascending, then `customer_name` ascending, never by id — and each preorder is decided all-or-nothing at its turn: if its `qty` is no greater than its line's current `qty_available_for_sale`, the preorder becomes `ALLOCATED` and the hold is placed (`qty_held_preorder` grows by `qty`, availability recomputed); otherwise it becomes `CONVERTED_BACKLIST` with no hold placed, its demand deferred to a firm backlist reorder outside this API. A preorder that exactly exhausts the remaining availability is allocated. When a line has zero availability, every preorder still waiting on it converts to backlist without error.

Fulfillment converts a hold into a sale. A cashier fulfills an `ALLOCATED` preorder while the fair is `OPEN` (`ERR_FAIR_NOT_OPEN` otherwise); the preorder becomes `FULFILLED`, its `fulfillment_price_cents` is fixed at `qty` times the stock line's `list_price_cents`, the line's `qty_held_preorder` decreases by `qty` while its `qty_sold` increases by `qty`, and the fair's `gross_sales_cents` grows by `fulfillment_price_cents`. A cashier may instead cancel a preorder from `PLACED` or `ALLOCATED` so long as the fair is not `RECONCILING`, `SETTLED`, or `CANCELLED`; cancelling an `ALLOCATED` preorder performs the compensating release — `qty_held_preorder` decreases by `qty` and availability is recomputed.

Register sales are built as `SaleTransaction` records. A cashier creates a sale in `DRAFT` from `fair_id` and `lines` — a non-empty array in which each line carries `stock_line_id`, a positive `qty`, and an optional `unit_price_cents` that defaults to the line's list price; the same stock line may appear on more than one line, each entry validated and applied independently, and the line array is immutable after creation. `tendered_amount_cents` and `change_cents` stay null until tender. The sale's `total_cents` is the sum over its lines of `qty` times `unit_price_cents` — pure integer math, no rounding. Both at creation and again at tender, any supplied `unit_price_cents` must sit inside the markdown band of that stock line's own consignment agreement: at least the floor of the list price scaled by one minus `markdown_allowance_pct`, and at most the list price itself (`ERR_PRICE_BEYOND_MARKDOWN`, HTTP 409). Every referenced stock line must belong to the sale's fair (`ERR_LINE_FAIR_MISMATCH`).

Tendering is the fiscal commit, and its checks run state-first. The `DRAFT` → `TENDERED` step first requires the sale's fair to be `OPEN` (`ERR_FAIR_NOT_OPEN`) before any fiscal check is evaluated; then every line's stock line must be `DELIVERED` and belong to the fair — a line failing either leg is reported as `ERR_LINE_FAIR_MISMATCH` (HTTP 409); then each line's `qty` must fit within that line's `qty_available_for_sale` (`ERR_STOCK_NOT_AVAILABLE`, HTTP 409); then the markdown band is re-checked; and finally the payload `tendered_amount_cents` must be at least the sale's `total_cents` (`ERR_TENDER_SHORT`, HTTP 402). On success each line's `qty_sold` grows by its `qty` with availability recomputed, the fair's `gross_sales_cents` grows by `total_cents` — a derived-field sync that bumps the fair's `version` — and `tendered_amount_cents` and `change_cents` (the tendered amount minus the total) are recorded.

Voiding unwinds. From `DRAFT` or `TENDERED`, a cashier may void the sale while the fair is still `OPEN`; voids when the fair is not `OPEN` are refused with `ERR_FAIR_NOT_OPEN` (HTTP 409) to protect reconciliation integrity. Voiding a `TENDERED` sale fully compensates: each line's `qty_sold` decreases by its `qty`, availability is recomputed, and the fair's `gross_sales_cents` decreases by `total_cents`. Voiding a `DRAFT` sale compensates nothing, because nothing was ever committed.

### 3.7. Closing the Fair: Reconciliation and Publisher Remittance

Close-sales flips the fair `OPEN` → `RECONCILING` once no signing session of the fair remains `SCHEDULED` or `OPEN_FOR_SIGNING`. Two side effects define the moment: every preorder still `ALLOCATED` is swept to `CANCELLED` with its hold released, and a `Reconciliation` is spawned for the fair in `OPEN` status, stamped with `created_by_user_id` equal to the acting organizer's `X-User-ID` — the segregation-of-duties anchor — and with `provisional_lines` initialized from the stock counters as they stand, `counted_lines` and `variance_lines` empty, `total_abs_variance` zero, and `remittance_cents` and `dispute_reason` null. Only one reconciliation may exist per fair; a duplicate spawn is refused with `ERR_DUPLICATE_RESOURCE`.

Each provisional line covers one `DELIVERED` or `RECONCILED` stock line of the fair, in the stock lines' creation order, and pairs `stock_line_id` with `expected_on_hand`: the copies the books say should remain, computed as `qty_delivered` minus `qty_sold`, minus `qty_damaged`, minus `qty_returned_shipped`, minus `qty_held_preorder`. The provisional expectation is recomputed from the counters as they stand on every counts call and again at submit-review — never frozen at spawn — which is precisely why recording damage during `RECONCILING` absorbs shrink through the sanctioned path of §3.3.

Physical counts enter through a superseding write. The organizer posts `lines` — each pairing a `stock_line_id` with its counted `qty_on_hand` — together with `expected_reconciliation_version` per §2.6. Every counts call replaces `counted_lines` wholesale with the latest set — an empty array is accepted and simply clears the counts — stamps each covered stock line's `qty_on_hand_counted` (null until first counted), recomputes `variance_lines` — one entry per counted line that carries a provisional expectation, shaped as `stock_line_id`, `expected_on_hand`, `qty_on_hand`, and `variance` (the counted `qty_on_hand` minus the `expected_on_hand`), while a counted line whose stock line has no provisional expectation is stored and stamped but contributes no variance entry — and `total_abs_variance` as the sum of the absolute per-line variances, and bumps the reconciliation's `version`. From `OPEN` a recount simply stays `OPEN`; from `VARIANCE_REVIEW` it returns to `OPEN`; and from `DISPUTED` it likewise returns to `OPEN`, clearing `dispute_reason`. The books-versus-shelf delta is the whole point: identical physical stock can yield a nonzero variance whenever unrecorded shrink exists, and that variance drives the review branch.

Submitting for review moves the reconciliation `OPEN` → `VARIANCE_REVIEW` and requires `counted_lines` to cover every `DELIVERED` stock line of the fair (`ERR_COUNTS_INCOMPLETE`, HTTP 409); variances and the absolute total are recomputed at the boundary.

Approval carries two gates in a pinned order. First, segregation of duties: the approving organizer's `X-User-ID` must differ from the reconciliation's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403). Only then, the tolerance gate: `total_abs_variance` must not exceed the shrink tolerance of two units (`ERR_VARIANCE_BEYOND_TOLERANCE`, HTTP 409). Approval moves the reconciliation to `APPROVED` and locks the publisher remittance: for each `FRONTLIST` line in `DELIVERED` — all of which simultaneously transition to `RECONCILED`, freezing their counters — the line's remittance is `qty_sold` times `list_price_cents` scaled by one minus the accepted agreement's `discount_pct`, rounded half-up **per line first**, and `remittance_cents` is the sum of those rounded line amounts; `BACKLIST` lines contribute nothing, their cost having accrued to `firm_purchases_cents` at delivery. The per-line-then-sum order is pinned: three lines of one sold copy each at a 999-cent list price under a 0.45 discount remit 1,647 cents, where rounding only after summation would wrongly yield 1,648. The locked amount lands on the fair as `publisher_remittance_cents`.

The organizer then submits the approved reconciliation (`APPROVED` → `SUBMITTED`), and the publisher of the fair's accepted agreement rules on it — where several agreements are `ACCEPTED`, any of their publishers passes the scope check: accept (`SUBMITTED` → `ACCEPTED`, terminal) or dispute (`SUBMITTED` → `DISPUTED`), the latter recording the payload `reason` into `dispute_reason`. A dispute is recovered by recounting, which reopens the reconciliation to `OPEN` as described above; remittance is locked only by an approval out of `VARIANCE_REVIEW`, and every such approval re-computes and overwrites it — because a first approval has already moved every `DELIVERED` line to `RECONCILED`, a re-approval after the dispute-recount cycle finds no `DELIVERED` frontlist lines and re-locks the remittance at zero.

Final settlement is the fair's last move. `RECONCILING` → `SETTLED` requires all of: the fair's latest reconciliation `ACCEPTED`; every return authorization of the fair in `CREDITED` or `REJECTED`; every author booking of the fair in `SETTLED`, `CANCELLED`, or `DECLINED`; and the fair's profit-share payout existing and `PAID` — where several payouts exist for the fair (a terminal payout does not block a later creation), the gate consults the first-created one.

### 3.8. Returning Unsold Stock

Unsold consignment stock goes back under a `ReturnAuthorization`. The organizer requests one with `fair_id`, `agreement_id`, and `lines` — a non-empty array, each line pairing `stock_line_id` with a positive `qty`, immutable after creation. Four gates apply at creation, in ladder order: the referenced agreement must be `ACCEPTED` (`ERR_AGREEMENT_NOT_ACCEPTED`, HTTP 409); the fair's latest reconciliation must be `APPROVED`, `SUBMITTED`, or `ACCEPTED` (`ERR_RECONCILIATION_NOT_APPROVED`, HTTP 409); every referenced line must be `FRONTLIST` — `BACKLIST` lines are firm purchases and cannot be returned (`ERR_FIRM_SALE_NOT_RETURNABLE`, HTTP 409); and the agreement must belong to the request's fair (`ERR_LINE_FAIR_MISMATCH`, HTTP 409) — the referential check sits at the end of the ladder, so an agreement that is both unaccepted and cross-fair reports `ERR_AGREEMENT_NOT_ACCEPTED`. A new authorization is `REQUESTED` with `credit_cents` null.

The scoped publisher — the party matching the agreement's `publisher_party_id` — rules on the request. Rejection moves it to `REJECTED`, terminal. Approval moves it to `APPROVED` subject to a physical on-hand check per line: the cumulative quantity across this authorization and all of the fair's other `APPROVED`, `SHIPPED`, or `CREDITED` authorizations for that line may not exceed the line's `qty_delivered` minus `qty_sold` minus `qty_damaged` (`ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND`, HTTP 409). Crucially, the consignment return cap is **not** a rejection: copies beyond the cap are simply credited at the reduced restocking rate by the waterfall below, and the only hard refusal is returning more than physically remains.

The organizer ships an approved authorization (`APPROVED` → `SHIPPED`); per line, `qty_returned_shipped` grows by the shipped `qty` and availability is recomputed. Confirming credit (`SHIPPED` → `CREDITED`) is where the money moves, in two cascade links. Link one computes `credit_cents` per the waterfall and advances each line's `qty_returned_credited` by its `qty`. The per-line cap is the floor of `return_cap_pct` times `qty_delivered`; prior authorizations of the fair in `APPROVED`, `SHIPPED`, or `CREDITED` status consume cap first in their creation order; and within this authorization each line's copies are split so that the in-cap portion — the smaller of the line's `qty` and the cap remaining after prior consumption, floored at zero — is credited at `list_price_cents` scaled by one minus `discount_pct`, rounded half-up, while the over-cap remainder is credited at that same discounted base further scaled by one minus `restocking_fee_pct`, also rounded half-up; the two rounded components sum to the line's credit, and the line credits sum to `credit_cents` — the same per-line-then-sum doctrine as remittance. A cumulative quantity exactly equal to the cap is fully in-cap; only the first copy beyond the cap earns the reduced rate. Link two follows from the counter mutation: the fair's `return_credits_cents` grows by `credit_cents` — while any payout already `CALCULATED` is deliberately left stale, per the snapshot semantics of §2.11, until someone recalculates it.

### 3.9. Honoraria, the School Payout, and Promotion Spend

A booking is settled once its sessions are done. The organizer settles a `TRAVEL_BOOKED` booking when every signing session of the booking is `RECONCILED` or `CANCELLED` and the booking's fair is `OPEN` or `RECONCILING`. Settlement fixes `settled_total_cents` as the sum of `base_honorarium_cents`, the accrued `accrued_bonus_cents`, and the smaller of `travel_actual_cents` and `travel_cap_cents`, and moves the booking to `SETTLED`. The fair's `honorarium_total_cents` is then recomputed as the sum of `settled_total_cents` over the fair's `SETTLED` bookings plus the sum of `kill_fee_cents` over its `CANCELLED` bookings — the two honorarium variants: a completed booking pays base plus bonuses plus capped travel, while a cancelled booking pays only its kill fee, with base and bonuses never paid.

The school's share is computed on the `ProfitSharePayout`. The organizer creates the fair's payout with `fair_id` while the fair is `RECONCILING` — at any other fair status the create fails with `ERR_INVALID_STATE` — and at most one non-terminal payout may exist per fair (`ERR_DUPLICATE_RESOURCE`). Creation copies `school_party_id` from the fair, scoping the later school approval, and leaves the payout `DRAFT` with `net_revenue_cents`, `share_cents`, `cash_amount_cents`, `scrip_amount_cents`, `mode`, and `final_amount_cents` all null.

Calculation is a pinned five-step evaluation, run by the organizer (`DRAFT` → `CALCULATED`) once the fair's latest reconciliation is `ACCEPTED` — otherwise `ERR_RECONCILIATION_NOT_APPROVED` — and every booking of the fair is in `SETTLED`, `CANCELLED`, or `DECLINED`, so the honorarium basis is final. Step one takes gross as the fair's `gross_sales_cents`. Step two sums costs as `firm_purchases_cents` plus `publisher_remittance_cents`, minus `return_credits_cents`, plus `honorarium_total_cents`, plus promo spend — the sum of `spend_cents` over the fair's media blasts in `APPROVED` or `PUBLISHED`. Step three nets revenue as gross minus costs into `net_revenue_cents`. Step four computes the tiered school share: when net revenue is zero or negative, `share_cents` is zero; otherwise the share is marginal — twenty percent of the first $2,000 of net revenue, plus twenty-five percent of the portion between $2,000 and $6,000, plus thirty percent of any portion beyond $6,000 — with the three tier amounts summed unrounded and rounded half-up exactly once into `share_cents`; per-tier rounding is prohibited. Step five computes both payout variants: `cash_amount_cents` equals `share_cents`, while `scrip_amount_cents` is `share_cents` uplifted by fifteen percent and rounded half-up — the scrip variant is never less than the cash one, so a 40,000-cent share locks 40,000 cents cash against 46,000 cents scrip. Because calculation is a snapshot, later changes to any input do not refresh these numbers; the organizer's recalculation step (`CALCULATED` → `DRAFT`) clears all computed amounts and opens the revision loop explicitly.

Approval belongs to the school. The scoped `SchoolCoordinator` — the party matching the payout's `school_party_id` — approves a `CALCULATED` payout with a payload `mode` of `CASH` or `SCRIP`; the choice is locked: `final_amount_cents` becomes `cash_amount_cents` when `CASH` is chosen and `scrip_amount_cents` when `SCRIP` is chosen, and the payout moves to `APPROVED`. The organizer then pays it (`APPROVED` → `PAID`, terminal), which is one of the four gates on fair settlement in §3.7.

Promotion runs in parallel with all of the above. The organizer drafts a `MediaBlast` with `fair_id`, a `channel` of `LOCAL_PAPER`, `RADIO`, `SOCIAL`, or `SCHOOL_NEWSLETTER`, a non-negative `spend_cents`, an `embargo_until` instant, and a `content_summary`; the blast starts `DRAFT`. Submitting moves it to `PENDING_APPROVAL` while the fair is `DRAFT`, `SCHEDULED`, `STOCKING`, or `OPEN`, and a `REJECTED` blast may be resubmitted through the same step — the revision loop. The scoped `SchoolCoordinator` of the fair's school approves or rejects from `PENDING_APPROVAL`; approval is the fiscal gate where the budget bites: the sum of `spend_cents` over the fair's blasts already `APPROVED` or `PUBLISHED`, plus the candidate's own `spend_cents`, must stay within the fair's `promo_budget_cents` (`ERR_PROMO_BUDGET_EXCEEDED`, HTTP 409). Publishing an `APPROVED` blast is the organizer's move and is embargo-gated: the logical clock must have reached `embargo_until`, otherwise `ERR_EMBARGO_ACTIVE` (HTTP 409). `PUBLISHED` is terminal.

## 4. Endpoint Definitions

Every endpoint requires the `X-User-ID` and `X-User-Role` headers of §2.1. Endpoints that create a new resource respond with HTTP 201; all other successful operations — state transitions, reads, and lists — respond with HTTP 200. Request payloads, computed fields, and side effects are defined by the §3 workflows and are deliberately not repeated here; the table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/set_current_utc` | Advance the logical clock; runs the agreement offer-expiry sweep | Organizer |
| POST | `/parties` | Register a school, publisher, or author party | Organizer |
| GET | `/parties/{id}` | Read a party | All six roles |
| POST | `/fairs` | Create a fair in `DRAFT` | Organizer |
| GET | `/fairs` | List fairs | All six roles |
| GET | `/fairs/{id}` | Read a fair including computed totals | All six roles |
| POST | `/fairs/{id}/schedule` | `DRAFT` → `SCHEDULED`; requires a `CONFIRMED` venue slot | Organizer |
| POST | `/fairs/{id}/open-stocking` | `SCHEDULED` → `STOCKING`; requires an `ACCEPTED` agreement | Organizer |
| POST | `/fairs/{id}/open` | `STOCKING` → `OPEN`; runs preorder allocation | Organizer |
| POST | `/fairs/{id}/close-sales` | `OPEN` → `RECONCILING`; sweeps unfulfilled preorders; spawns the reconciliation | Organizer |
| POST | `/fairs/{id}/settle` | `RECONCILING` → `SETTLED`; all settlement gates must hold | Organizer |
| POST | `/fairs/{id}/cancel` | Cancel the fair with the deep cascade of §3.1 | Organizer |
| POST | `/venue-slots` | Hold a venue block (`HELD`) with the buffered overlap check | Organizer |
| GET | `/venue-slots` | List venue slots | All six roles |
| GET | `/venue-slots/{id}` | Read a venue slot | All six roles |
| POST | `/venue-slots/{id}/confirm` | `HELD` → `CONFIRMED`; school-scoped | SchoolCoordinator |
| POST | `/venue-slots/{id}/release` | `HELD`/`CONFIRMED` → `RELEASED` | Organizer |
| POST | `/consignment-agreements` | Propose consignment terms (`PROPOSED`, round 1) | Organizer |
| GET | `/consignment-agreements` | List consignment agreements | All six roles |
| GET | `/consignment-agreements/{id}` | Read an agreement (terms, round, version) | All six roles |
| POST | `/consignment-agreements/{id}/counter` | Counter the live offer; flips `PROPOSED` ↔ `COUNTERED`; OCC-guarded | Organizer, PublisherRep |
| POST | `/consignment-agreements/{id}/accept` | Accept the live offer (non-offering side only) | Organizer, PublisherRep |
| POST | `/consignment-agreements/{id}/decline` | Decline the negotiation | Organizer, PublisherRep |
| POST | `/stock-lines` | Add a title to the inventory plan (`QUOTED`) | Organizer |
| GET | `/stock-lines` | List stock lines | All six roles |
| GET | `/stock-lines/{id}` | Read a stock line including all counters | All six roles |
| POST | `/stock-lines/{id}/commit` | `QUOTED` → `COMMITTED`; requires an `ACCEPTED` agreement | Organizer |
| POST | `/stock-lines/{id}/deliver` | `COMMITTED` → `DELIVERED`; records `qty_delivered`; backlist cost accrues | Organizer |
| POST | `/stock-lines/{id}/damage` | Write off damaged copies while the fair is `OPEN` or `RECONCILING` | Organizer |
| POST | `/author-bookings` | Invite an author (`INVITED`, round 1) | Organizer |
| GET | `/author-bookings` | List author bookings | All six roles |
| GET | `/author-bookings/{id}` | Read a booking (terms, counters, settlement) | All six roles |
| POST | `/author-bookings/{id}/counter` | Counter the live offer; flips `INVITED` ↔ `NEGOTIATING`; OCC-guarded | Organizer, AuthorRep |
| POST | `/author-bookings/{id}/accept` | Accept the live offer (non-offering side only) | Organizer, AuthorRep |
| POST | `/author-bookings/{id}/decline` | Decline the negotiation | Organizer, AuthorRep |
| POST | `/author-bookings/{id}/book-travel` | `CONFIRMED` → `TRAVEL_BOOKED`; records actual travel spend | Organizer |
| POST | `/author-bookings/{id}/settle` | `TRAVEL_BOOKED` → `SETTLED`; computes `settled_total_cents` | Organizer |
| POST | `/author-bookings/{id}/cancel` | Cancel a `CONFIRMED`/`TRAVEL_BOOKED` booking; kill fee accrues; sessions cascade | Organizer, AuthorRep |
| POST | `/signing-sessions` | Schedule a signing session (`SCHEDULED`); closed-interval floor-capacity check | Organizer |
| GET | `/signing-sessions` | List signing sessions | All six roles |
| GET | `/signing-sessions/{id}` | Read a session (attendance, bonus) | All six roles |
| POST | `/signing-sessions/{id}/open-signing` | `SCHEDULED` → `OPEN_FOR_SIGNING`; booking, window, and fair gates | LineStaff |
| POST | `/signing-sessions/{id}/close-signing` | `OPEN_FOR_SIGNING` → `CLOSED_FOR_SIGNING`; sweeps no-shows; freezes attendance | LineStaff |
| POST | `/signing-sessions/{id}/reconcile` | `CLOSED_FOR_SIGNING` → `RECONCILED`; computes bonus, bubbles to booking | Organizer |
| POST | `/signing-sessions/{id}/cancel` | Cancel the session; voids non-terminal tickets | Organizer |
| POST | `/signing-tickets` | Issue a ticket or wristband (kind derived from session mode) | LineStaff |
| GET | `/signing-tickets` | List signing tickets | All six roles |
| GET | `/signing-tickets/{id}` | Read a signing ticket | All six roles |
| POST | `/signing-tickets/{id}/admit` | `ISSUED` → `ADMITTED`; payload-session state, fire-marshal cap, then referential match | LineStaff |
| POST | `/signing-tickets/{id}/redeem` | `ADMITTED` → `REDEEMED` (book signed) | LineStaff |
| POST | `/signing-tickets/{id}/void` | `ISSUED`/`ADMITTED` → `VOIDED`; releases the live entitlement | LineStaff |
| POST | `/preorders` | Place a preorder (`PLACED`) while the fair is `SCHEDULED` or `STOCKING` | Cashier |
| GET | `/preorders` | List preorders | All six roles |
| GET | `/preorders/{id}` | Read a preorder | All six roles |
| POST | `/preorders/{id}/fulfill` | `ALLOCATED` → `FULFILLED`; hold converts to a sale at list price | Cashier |
| POST | `/preorders/{id}/cancel` | `PLACED`/`ALLOCATED` → `CANCELLED`; releases any hold | Cashier |
| POST | `/sales` | Create a `DRAFT` sale with lines; unit price defaults to list | Cashier |
| GET | `/sales` | List sales | All six roles |
| GET | `/sales/{id}` | Read a sale | All six roles |
| POST | `/sales/{id}/tender` | `DRAFT` → `TENDERED`; state checks before fiscal checks | Cashier |
| POST | `/sales/{id}/void` | `DRAFT`/`TENDERED` → `VOIDED`; a tendered void fully compensates | Cashier |
| GET | `/reconciliations` | List reconciliations | All six roles |
| GET | `/reconciliations/{id}` | Read a reconciliation (provisional vs counted, variance, remittance) | All six roles |
| POST | `/reconciliations/{id}/counts` | Enter or supersede physical counts; OCC-guarded; reopens review or dispute to `OPEN` | Organizer |
| POST | `/reconciliations/{id}/submit-review` | `OPEN` → `VARIANCE_REVIEW`; requires complete counts | Organizer |
| POST | `/reconciliations/{id}/approve` | `VARIANCE_REVIEW` → `APPROVED`; segregation of duties and variance gate; locks remittance | Organizer |
| POST | `/reconciliations/{id}/submit` | `APPROVED` → `SUBMITTED` (to the publisher) | Organizer |
| POST | `/reconciliations/{id}/accept` | `SUBMITTED` → `ACCEPTED`; publisher-scoped | PublisherRep |
| POST | `/reconciliations/{id}/dispute` | `SUBMITTED` → `DISPUTED`; publisher-scoped; records the reason | PublisherRep |
| POST | `/return-authorizations` | Request an unsold-return authorization (`REQUESTED`) | Organizer |
| GET | `/return-authorizations` | List return authorizations | All six roles |
| GET | `/return-authorizations/{id}` | Read a return authorization | All six roles |
| POST | `/return-authorizations/{id}/approve` | `REQUESTED` → `APPROVED`; publisher-scoped; physical on-hand check | PublisherRep |
| POST | `/return-authorizations/{id}/reject` | `REQUESTED` → `REJECTED`; publisher-scoped | PublisherRep |
| POST | `/return-authorizations/{id}/ship` | `APPROVED` → `SHIPPED`; decrements on-hand | Organizer |
| POST | `/return-authorizations/{id}/confirm-credit` | `SHIPPED` → `CREDITED`; waterfall credit; cascades to fair totals | Organizer |
| POST | `/profit-share-payouts` | Create the fair's payout (`DRAFT`) while the fair is `RECONCILING` | Organizer |
| GET | `/profit-share-payouts` | List payouts | All six roles |
| GET | `/profit-share-payouts/{id}` | Read a payout (both variant amounts, chosen mode) | All six roles |
| POST | `/profit-share-payouts/{id}/calculate` | `DRAFT` → `CALCULATED`; snapshot of both `CASH` and `SCRIP` variants | Organizer |
| POST | `/profit-share-payouts/{id}/recalculate` | `CALCULATED` → `DRAFT`; clears computed amounts | Organizer |
| POST | `/profit-share-payouts/{id}/approve` | `CALCULATED` → `APPROVED`; school-scoped; selects the payout variant | SchoolCoordinator |
| POST | `/profit-share-payouts/{id}/pay` | `APPROVED` → `PAID` | Organizer |
| POST | `/media-blasts` | Create a promotional blast (`DRAFT`) | Organizer |
| GET | `/media-blasts` | List media blasts | All six roles |
| GET | `/media-blasts/{id}` | Read a media blast | All six roles |
| POST | `/media-blasts/{id}/submit` | `DRAFT`/`REJECTED` → `PENDING_APPROVAL` | Organizer |
| POST | `/media-blasts/{id}/approve` | `PENDING_APPROVAL` → `APPROVED`; school-scoped; promo-budget gate | SchoolCoordinator |
| POST | `/media-blasts/{id}/reject` | `PENDING_APPROVAL` → `REJECTED`; school-scoped | SchoolCoordinator |
| POST | `/media-blasts/{id}/publish` | `APPROVED` → `PUBLISHED`; embargo gate on the logical clock | Organizer |

## 5. Error Code Catalogue

The trigger condition for each error is defined by the narratives in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_HEADERS` | 400 |
| `ERR_ROLE_FORBIDDEN` | 403 |
| `ERR_PARTY_NOT_FOUND` | 404 |
| `ERR_ROLE_PARTY_KIND_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_PARTY_SCOPE_MISMATCH` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FAIR_NOT_OPEN` | 409 |
| `ERR_AGREEMENT_NOT_ACCEPTED` | 409 |
| `ERR_RECONCILIATION_NOT_APPROVED` | 409 |
| `ERR_BOOKING_NOT_TRAVEL_READY` | 409 |
| `ERR_SESSION_NOT_SIGNING` | 409 |
| `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_VENUE_CONFLICT` | 409 |
| `ERR_SIGNING_FLOOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_OUTSIDE_SIGNING_WINDOW` | 409 |
| `ERR_EMBARGO_ACTIVE` | 409 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_SIGNING_CAPACITY_EXCEEDED` | 409 |
| `ERR_LINE_CAPACITY_EXCEEDED` | 409 |
| `ERR_TICKET_SESSION_MISMATCH` | 409 |
| `ERR_LINE_FAIR_MISMATCH` | 409 |
| `ERR_FIRM_SALE_NOT_RETURNABLE` | 409 |
| `ERR_RETURN_QUANTITY_EXCEEDS_ON_HAND` | 409 |
| `ERR_OVER_DELIVERY` | 409 |
| `ERR_DAMAGE_EXCEEDS_ON_HAND` | 409 |
| `ERR_STOCK_NOT_AVAILABLE` | 409 |
| `ERR_PRICE_BEYOND_MARKDOWN` | 409 |
| `ERR_TENDER_SHORT` | 402 |
| `ERR_PROMO_BUDGET_EXCEEDED` | 409 |
| `ERR_TRAVEL_CAP_EXCEEDED` | 409 |
| `ERR_COUNTS_INCOMPLETE` | 409 |
| `ERR_VARIANCE_BEYOND_TOLERANCE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PREORDER_WINDOW_CLOSED` | 409 |

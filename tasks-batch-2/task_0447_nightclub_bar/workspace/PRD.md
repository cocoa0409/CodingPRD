# Nightclub & Bar Service API — Product Requirements Document

## 1. Introduction

A busy nightclub runs three doors at once: the entrance, where every patron must pass an age and identity check before a cover charge is collected and a finite, fire-marshal-capped headcount is enforced; the floor, where VIP tables are reserved against contracted spend minimums and deposits; and the bar, where tabs accumulate line items against a card pre-authorization and where responsible-service law forbids over-pouring and late-night alcohol service. This API is the system of record that ties those three doors together under a single venue, so that a manager can see, at any instant, how many bodies are inside, how many tabs are open, and whether the room is still legally admitting guests.

The product exists to make the venue's hardest constraints unforgeable. Occupancy is a quota: the last seat under the fire-code limit is a contested resource, and two door hosts admitting at the same moment must not both win it. Money is a pricing engine: cover charges surge as the room fills, promoters discount and comp their guest lists against a fixed budget, and table tabs settle with auto-gratuity and a minimum-spend top-up. Time gates everything: as closing approaches the venue enters a last-call window that stops alcohol, and at closing it shuts entirely, cascading every open reservation, tab, and admitted patron to a settled or exited terminal state. The sections that follow specify the entities, the derived venue posture that gates child operations, the calculations that price cover and settle tabs, and the validation order that keeps the room safe and the books honest.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply uniformly across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` declares the operational capacity under which the request is made. The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `FloorManager`, `DoorHost`, `Bartender`, and `SecurityOfficer`. If either header is missing, or if `X-User-Role` does not name one of these five roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The `PlatformAdmin` is the operator superset: it may perform any operation any other role can perform, and it exclusively holds the authority to create a venue and to set the server's logical clock. A `FloorManager` owns reservations, promoters and comps, the venue's close operation, and whole-tab voids. A `DoorHost` owns the door: the guest list, ID checks, and patron admission. A `Bartender` owns bar tabs and their line items. A `SecurityOfficer` owns security incidents, refusals, and ejections, and assists at the door. The precise per-endpoint authorization is enumerated in §4.

All five roles are operator identities rather than persisted patrons. When `X-User-Role` is `PlatformAdmin`, `FloorManager`, `DoorHost`, `Bartender`, or `SecurityOfficer`, the corresponding `X-User-ID` is an opaque operator identifier that is not tied to any stored entity; the server may log it for audit purposes but never compares it to any entity's `id`, and ownership of a resource is never determined by matching `X-User-ID` against a stored field. Authorization is determined purely by the role's permission set, not by per-record ownership.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with no upper bound.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most primary resources in the system — the Venue, Promoter, Guest-List Entry, Reservation, Tab, Entry, ID Check, and Security Incident — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp indicating when the resource was last modified; it advances on every mutation of the resource's stored or derived fields.
- `version` (integer): a system-managed integer that begins at 1 on creation and increments by 1 on every subsequent mutation of the resource. It underpins the optimistic-concurrency mechanism described in §2.9.

One entity is deliberately leaner. A Tab Item (a single bar-POS line) carries only `id` and `created_at`; it has no `updated_at` and no `version`. A line is effectively immutable once written, save for the single `voided` flag described later, so it is not versioned.

The server maintains a single logical clock that supplies every timestamp the system stamps and every "current time" comparison the rules make — admission times, exit times, reservation-window checks, last-call and closing transitions, ID expiry, and age computation all read this clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z` and stays there until it is explicitly set; before any set call it never falls back to real wall-clock time. An administrative test-driving capability advances the clock to a supplied instant, and doing so recomputes the derived posture of every venue (see §2.6) and runs any close cascade that has come due.

### 2.5. Monetary Precision and Rounding

All monetary amounts in the system — cover charges, pre-authorizations, deposits, spend minimums, tab subtotals and totals, comp values — are stored and transmitted as whole integer cents. Wherever a calculation introduces a fractional cent (the surge surcharge on cover and the auto-gratuity on a tab both do), the result is rounded to the nearest whole cent using the round-half-up convention: a half-cent rounds up. Each calculation section below states exactly where rounding is applied and in what order, because the order of rounding is part of the contract, not an implementation detail.

### 2.6. Venue Posture: the Derived Gate

Every venue carries a derived aggregate field, `posture`, that takes one of exactly four values: `OPEN`, `AT_CAPACITY`, `LAST_CALL`, or `CLOSED`. Posture is never set directly by a client; it is recomputed by the server after every child mutation that could affect it (an admission, an exit, a tab or reservation transition) and after every advance of the logical clock. Posture gates which child operations are permitted, and `CLOSED` is terminal — once a venue is closed it never reopens.

A freshly created venue starts `OPEN`. The room moves to `AT_CAPACITY` when, immediately after an admission, the count of patrons inside has reached the fire-code limit and the clock has not yet entered the last-call window; while at capacity, further admissions are refused until someone exits. When an exit drops the inside count back below the fire-code limit and the clock is still before the last-call window, the venue reverts from `AT_CAPACITY` to `OPEN` and admissions resume. As closing nears, the venue moves into `LAST_CALL`; this transition is driven purely by the clock and can occur from either `OPEN` or `AT_CAPACITY`. From a capacity-bound room, entering last call stops alcohol service but leaves admissions blocked as long as the room remains full. Finally, the venue moves to `CLOSED` either when a `FloorManager` explicitly closes it or when the clock reaches the scheduled closing time. The exact clock boundaries for last call and closing, and the full close cascade, are specified in §3.

### 2.7. Hierarchical Consistency and the Close Cascade

The venue is the aggregate root, and several operations mutate more than one entity in a single logical step. Whenever such a cascade fires, every entity it touches is independently mutated — its `updated_at` is refreshed and, where the entity is versioned, its `version` is incremented. The two largest cascades are the venue close (which terminates reservations, tabs, and admitted patrons in one sweep) and the security ejection (which removes a patron from the floor and revises occupancy and posture). Each is described in full in its §3 workflow. The governing principle here is that no child is left in a stale state when its parent venue changes: closing a venue resolves every open child, and any occupancy-affecting change re-derives the venue's posture before the request returns.

### 2.8. Nested Resource Resolution and Foreign-Key Integrity

Although every collection is addressed as a flat, top-level path under the API, relationships are expressed through foreign-key fields carried in request bodies and resolved through filtered list reads. When a request path itself carries a resource identifier (for example, a specific tab and one of its items), the server validates those identifiers left to right, rejecting the request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an existing resource — the parent tab is checked before the item beneath it. Separately, when a write body carries a foreign key — a `promoter_id`, a `reservation_id`, a `guest_list_entry_id`, an `id_check_id`, or a `subject_entry_id` — the referenced row must exist and must belong to the same venue as the resource being written; a dangling or cross-venue reference is rejected with `ERR_FK_NOT_FOUND`. This foreign-key existence check is applied on admission, on tab open, on guest-list add, and on incident filing.

### 2.9. Optimistic Concurrency on the Venue

Two operations compete for finite venue resources and are therefore guarded by optimistic concurrency control against the venue's `version`: admitting a patron and booking a table reservation. Each of these write requests must carry an `expected_venue_version` field whose value is the `version` the client last observed on the target venue. This field is mandatory on those two creates; it is not accepted on, and not required by, any other endpoint.

When a patron is admitted, the request body's `expected_venue_version` is compared against the venue's current `version`. The last free seat beneath the fire-code limit is a finite resource: if another admission, an exit, or a posture recomputation has advanced the venue's `version` since the client last read it, the client's view of occupancy and posture is stale, and the admission is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412) so the client must re-read the venue before competing for the seat again. Booking a reservation is guarded identically: a table for a given window is a finite resource that another booking may have just claimed, so if `expected_venue_version` does not match the venue's current `version`, the booking is rejected with `ERR_STALE_VENUE_VERSION` (HTTP 412), and the stale writer must re-read the venue and its reservation set before re-attempting. Because every admission and every booking increments the venue's `version`, a client that issues several such writes in sequence must thread the new `version` from each response into the next request.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Venue

Only a `PlatformAdmin` may create a venue. The creator supplies the venue's display `name`, its `fire_code_capacity` (the maximum legally occupied headcount per the fire marshal's certificate, an integer of at least 1), and the scheduled `closing_time_utc` that drives the automatic last-call and close transitions. Four further inputs are optional and fall back to defaults when omitted: `last_call_offset_minutes`, the number of minutes before closing at which last call begins, defaults to 30 and must be a non-negative integer; `cover_base_cents`, the base cover charge before any discount, defaults to 2000 and must be non-negative; `cover_surge_pct`, the fractional surcharge applied to cover during the surge band, defaults to 0.5 and must lie between 0 and 2 inclusive; and `max_alcohol_strikes`, the responsible-service cap above which a tab is cut off from further alcohol, defaults to 4 and must be at least 1.

On creation the venue's `posture` is `OPEN`, its `occupancy_count` (the live count of patrons inside) is 0, its `tabs_open_count` (the count of tabs currently `OPEN` or `RUNNING`) is 0, and its `version` is 1. The `occupancy_count` is recomputed as the number of that venue's entries whose status is `INSIDE` on every admit and every exit; the `tabs_open_count` tracks how many of the venue's tabs are in `OPEN` or `RUNNING` status. Any operator may read a single venue or list venues; reads expose the live `occupancy_count`, `tabs_open_count`, `posture`, and `version`.

Closing a venue is a `FloorManager` operation (the `PlatformAdmin` may also perform it as part of its override authority). It is the system's largest cascade and is described in §3.8. No child mutation of any kind — no admission, exit, reservation or tab transition, item add or void, incident, or guest-list add — is permitted once a venue's `posture` is `CLOSED`; any such attempt is rejected with `ERR_VENUE_CLOSED`.

### 3.2. Promoters, Guest Lists, and the Comp Budget

A `FloorManager` registers a **Promoter** under a venue by supplying the `venue_id` the promoter is scoped to, the promoter's `name`, and a `comp_budget_cents` — the total comp value, in cents, that this promoter may grant across all of their guest-list entries (a non-negative integer). An optional `guest_discount_pct`, the fractional cover discount applied to that promoter's guests, defaults to 0.5 and must lie between 0 and 1 inclusive. A promoter is created with two computed counters at zero: `comp_committed_cents`, the sum of the comp values on that promoter's guest-list entries that are currently `CONFIRMED` or `REDEEMED`, and `heads_credited`, the count of entries admitted through one of this promoter's guest-list entries whose status is `INSIDE` or `EXITED`. Reads of a promoter expose both computed figures. Promoters can be listed and filtered by `venue_id`.

The **guest list** is owned at the door. A `DoorHost` (or a `FloorManager`) adds a guest-list entry by supplying the `venue_id`, the `guest_name` on the list, and the `party_size` (heads reserved under that name, an integer of at least 1). The add may optionally name a `promoter_id` to attach the entry to a promoter, and may carry a `comp_value_cents` — the cover value the promoter comps for this entry — which defaults to 0 and must be non-negative. When `promoter_id` is omitted (defaulting to null), the entry is a house guest-list add not attached to any promoter. A new entry's `status` is `CONFIRMED`, and its `redeemed_entry_id` — the entry record that eventually redeems it at the door — is null until a door admission consumes it.

Before a promoter-backed entry is accepted, the comp budget is enforced: the entry's `comp_value_cents` must not push that promoter's `comp_committed_cents` above its `comp_budget_cents`. If accepting the entry would carry the committed total past the budget ceiling, the add is rejected with `ERR_COMP_BUDGET_EXCEEDED`. Cancelling a guest-list entry sets its `status` to `CANCELLED` and recomputes the promoter's `comp_committed_cents`, releasing that entry's comp back into the budget — because a `CANCELLED` entry no longer counts toward the committed sum. Guest-list entries may be listed and filtered by `venue_id`, by `promoter_id`, or by `redeemed_entry_id`.

### 3.3. The Door: ID Verification and Refusal Logging

Every patron who wishes to enter must first clear an **ID check**. A `DoorHost` or `SecurityOfficer` runs a check by submitting the `venue_id`, the `patron_name` as printed on the document, the `date_of_birth` as a `YYYY-MM-DD` string, and the document's `id_expiry`, also `YYYY-MM-DD`. The server computes the patron's age and the verification `outcome` and stores both, along with a `refusal_reason` note when the check fails.

The patron's whole-years age is written to `computed_age_years` and is derived from the `date_of_birth` against the date portion of the logical clock at check time. Specifically, the age is the difference between the clock's calendar year and the year of birth; if the clock's month-and-day falls before the birth month-and-day, the patron has not yet had this year's birthday and the age is reduced by one. A patron whose birthday falls exactly on the check date has already had that birthday, so the age increments that day. The legal drinking age is 21, and the boundary is inclusive: a `computed_age_years` of 21 passes, while 20 is underage.

The verification `outcome` is one of `PASS`, `REFUSED_UNDERAGE`, or `REFUSED_EXPIRED_ID`, and the gate is evaluated in a pinned order: expiry is checked before age. If the document's `id_expiry` is strictly before the clock's current date, the `outcome` is `REFUSED_EXPIRED_ID` with a `refusal_reason` of "ID expired" — and this fires even for a patron well over 21, so an expired ID of a 25-year-old is refused for expiry rather than passing. The expiry boundary is itself non-strict in the patron's favor: an `id_expiry` equal to today's date is still valid and does not refuse on expiry grounds. Only if the document is unexpired does the age gate apply: if `computed_age_years` is below 21 the `outcome` is `REFUSED_UNDERAGE` with a `refusal_reason` of "Under legal drinking age". Otherwise the `outcome` is `PASS` and the `refusal_reason` is null. ID checks may be listed — they double as the refusal log — and filtered by `venue_id` and by `outcome`.

### 3.4. Admission, Occupancy, and the Cover Charge

Admission is a `DoorHost` operation. To admit a patron, the host supplies the `venue_id`, the `id_check_id` of the passing verification that authorizes the entry, and the `expected_venue_version` that guards the create against a stale venue (§2.9). Optionally the host supplies a `guest_list_entry_id` to admit the patron off a guest list. The server records the cover actually charged in `cover_paid_cents`, sets the entry's `status` to `INSIDE`, stamps `admitted_at_utc` from the logical clock, and increments the venue's `occupancy_count`. When the admission redeems a guest-list entry, that entry's `status` moves to `REDEEMED` and its `redeemed_entry_id` is set to the new entry's identifier. The admission then re-derives posture — moving `OPEN → AT_CAPACITY` if the inside count has reached the fire-code limit — and increments the venue's `version` by 1. The exit timestamp `exited_at_utc` remains null while the patron is inside.

A sequence of gates protects each admission. The verification gate requires that the `id_check_id` reference an ID check whose `outcome` is `PASS`; an admission citing a refused or missing check is rejected with `ERR_ID_CHECK_NOT_PASSED`. A re-entry gate prevents double-counting: the ID check named by `id_check_id` must not already back another entry whose status is `INSIDE` — a patron currently on the floor has an open, unexited occupancy interval and cannot be admitted a second time, so the attempt is rejected with `ERR_PATRON_ALREADY_INSIDE`. The capacity gate refuses admission when the room is full: if `occupancy_count` already equals `fire_code_capacity` at admit time, admitting would push the count past the legal limit and the request is rejected with `ERR_AT_CAPACITY`.

The cover charge written to `cover_paid_cents` is computed in three ordered steps from the venue's `cover_base_cents`. First comes the surge band, driven by how full the room is: if `occupancy_count` is at least ninety percent of `fire_code_capacity` (rounding the ninety-percent threshold up to the next whole head when it is fractional), the base is multiplied by one plus `cover_surge_pct` and the product is rounded half-up to the nearest cent to yield the surged figure; otherwise the surged figure is simply the base. Second comes the guest-list discount, applied to the surged figure: if the admission carries a `guest_list_entry_id` that is attached to a promoter, the promoter's `guest_discount_pct` is the discount, and the surged figure is multiplied by one minus that discount and rounded half-up to the nearest cent; if the guest-list entry is a house entry with no promoter, the discount is zero. Third comes the comp: the guest-list entry's `comp_value_cents` is subtracted from the post-discount amount, and the result is floored at zero so cover never goes negative; this subtraction is exact, with no rounding.

Two variants of this calculation deserve explicit statement. A walk-up admission carries no `guest_list_entry_id` at all: it receives neither discount nor comp, and its cover is exactly the surged figure (full surged base). A house-list admission carries a `guest_list_entry_id` whose `promoter_id` is null: here the surge is waived entirely — the base is used rather than the surged figure — the percentage discount is zero, but the comp still applies. The house-list case is therefore distinct both from the walk-up case (which never waives surge) and from a promoter-backed admission (which keeps the surge and applies a percentage discount).

### 3.5. Exit and Ejection

A `DoorHost` or `SecurityOfficer` marks a patron exited. Exit is permitted only while the entry's status is `INSIDE`; exiting an already-terminal entry is rejected with `ERR_INVALID_STATE`. On exit the entry's `status` becomes `EXITED`, `exited_at_utc` is stamped from the logical clock, the venue's `occupancy_count` is decremented, and posture is re-derived — reverting `AT_CAPACITY → OPEN` when the count falls below `fire_code_capacity` (provided the clock has not entered the last-call window).

Ejection is not a door action but a consequence of a security incident. When a `SecurityOfficer` files an incident whose `action` is `EJECTION` naming a subject entry that is currently `INSIDE`, the system cascades that entry from `INSIDE → EJECTED`: it stamps `exited_at_utc`, decrements the venue's `occupancy_count`, and re-derives posture exactly as a normal exit would, and the ejected patron's linked guest-list head no longer counts toward the promoter's `heads_credited`. `EJECTED` and `EXITED` are both terminal for an entry; `INSIDE` is the only state from which either is reachable.

### 3.6. Booking and Running a Table

Table service begins with a **Reservation**, booked by a `FloorManager`. The booking supplies the `venue_id`, the physical `table_label` (for example "VIP-3"), the booked `party_size` (an integer of at least 1), the hold window as `window_start_utc` and `window_end_utc`, the contracted `spend_minimum_cents` for the table over that window, and the `expected_venue_version` guarding the create (§2.9). An optional `deposit_cents`, the non-refundable-at-no-show deposit collected at booking, defaults to 0 and must be non-negative. A new reservation's `status` is `BOOKED`, and the booking increments the venue's `version` by 1.

The reservation window is half-open, `[window_start_utc, window_end_utc)`, and three temporal rules govern it. At booking time, `window_end_utc` must be strictly after `window_start_utc`. A reservation may be seated only while the logical clock falls within the half-open window — at or after the start and strictly before the end. A reservation may be cancelled only strictly before its window opens. Any of these three violations is rejected with `ERR_RESERVATION_WINDOW`. Separately, a table cannot be double-booked: a new reservation's half-open window must not overlap that of any non-terminal reservation — one in `BOOKED` or `SEATED` status — on the same venue and the same `table_label`. Because the intervals are half-open, two reservations whose endpoints merely touch (one ending exactly when the next begins) do not conflict; a genuine overlap is rejected with `ERR_TABLE_DOUBLE_BOOKED`. Reservations may be listed and filtered by `venue_id`, by `status`, and by `table_label`, and a single read exposes the computed `minimum_shortfall_cents`.

A `FloorManager` drives the reservation through its lifecycle. Seating a booked reservation advances it `BOOKED → SEATED`; seating requires that the venue's `posture` be `OPEN` or `AT_CAPACITY` (it is not permitted during `LAST_CALL` or once `CLOSED`) and that the clock fall within the window as above. Seating causes no occupancy change in itself, since heads enter the room as ordinary admission entries. A booked reservation whose window has lapsed can be marked a no-show, moving `BOOKED → NO_SHOW`; this is permitted once the clock is at or after `window_end_utc`, and on no-show the `deposit_cents` is forfeited and retained as venue revenue rather than refunded. Cancelling a booked reservation moves `BOOKED → CANCELLED` and refunds the `deposit_cents` in full, reflecting that cancellation happens before the window opens. Only a `SEATED` reservation may be settled (§3.7); attempting any of these transitions from a state that does not admit it is rejected with `ERR_INVALID_STATE`. `SETTLED`, `NO_SHOW`, and `CANCELLED` are all terminal.

### 3.7. The Bar Tab and Its Settlement

A `Bartender` opens a **Tab** by supplying the `venue_id`, the `patron_name` the tab is opened under, and the `preauth_cents` — the card pre-authorization hold placed when the tab opens (a non-negative integer). The tab may optionally name a `reservation_id` to link it to a seated reservation; left null, it is a walk-up bar tab. An optional `gratuity_pct`, the auto-gratuity fraction applied at settlement, defaults to 0.2 and must lie between 0 and 1 inclusive. A new tab opens in `status` `OPEN`, with `running_subtotal_cents`, `bac_strikes`, and `final_total_cents` all at 0, and opening a tab recomputes the venue's `tabs_open_count`. A new tab may not be opened while the venue's `posture` is `LAST_CALL`, though existing tabs may still be settled at that point. Tabs may be listed and filtered by `venue_id`, by `status`, and by `reservation_id`.

Line items are added by a `Bartender`. Each **Tab Item** carries the `tab_id` it belongs to, an item `name` (for example "House Vodka" or "Bottle Service - Tier 1"), a `category` of `ALCOHOL`, `FOOD`, `NA_BEVERAGE`, or `SERVICE`, a `qty` of at least 1, and a `unit_price_cents` that is non-negative. The first non-voided item on a tab advances it `OPEN → RUNNING`; subsequent adds keep it `RUNNING`. Each add recomputes the tab's `running_subtotal_cents`, which is the sum over the tab's non-voided lines of each line's `qty` multiplied by its `unit_price_cents`. Adding a line whose `category` is `ALCOHOL` increments the tab's `bac_strikes` by one — the count of alcohol pours since the patron's last strike reset, used to enforce the over-service cap.

Two responsible-service gates protect alcohol service, and both are checked at item-add time. The last-call gate forbids any new `ALCOHOL` item while the venue's `posture` is `LAST_CALL`, rejecting the add with `ERR_LAST_CALL_NO_ALCOHOL`. The over-service gate forbids a new `ALCOHOL` item once the tab's `bac_strikes` has reached the venue's `max_alcohol_strikes` cap — that is, when `bac_strikes` is at least `max_alcohol_strikes` — rejecting the add with `ERR_OVER_SERVICE_REFUSED`. Both gates apply only to alcohol; food, non-alcoholic beverages, and service lines are never blocked by them.

Voiding a line is a `Bartender` action that sets that line's `voided` flag to true and excludes it from the subtotal; the `running_subtotal_cents` is recomputed accordingly. If the voided line was `ALCOHOL`, the tab's `bac_strikes` is decremented by one. If voiding leaves zero non-voided items on the tab, the tab reverts `RUNNING → OPEN`, its `running_subtotal_cents` returns to 0, and its `bac_strikes` resets to 0.

Settling a tab computes its `final_total_cents` and moves it `OPEN`-or-`RUNNING` → `SETTLED`. The total is the non-voided subtotal plus auto-gratuity, with the rounding order pinned: the subtotal is the sum over all non-voided lines of `qty` times `unit_price_cents`; the gratuity is that summed subtotal multiplied by the tab's `gratuity_pct` and then rounded half-up to the nearest cent exactly once on the summed figure (sum first, then round — never round each line and then sum); and the grand total is the subtotal plus that single rounded gratuity. For a walk-up tab — one whose `reservation_id` is null — that grand total is the whole story, with no minimum top-up. On settlement the pre-authorization is captured up to `final_total_cents` and any remainder of `preauth_cents` is released, and the venue's `tabs_open_count` is recomputed. Unless the settlement is forced by the venue-close cascade, the tab's `preauth_cents` must be at least the projected `final_total_cents`; a settlement that would exceed the hold is rejected with `ERR_PREAUTH_INSUFFICIENT`. Settling an already-`SETTLED` or `VOIDED` tab is rejected with `ERR_INVALID_STATE`.

A whole tab carrying no charges may be voided by a `FloorManager`, moving it `OPEN`-or-`RUNNING` → `VOIDED`, releasing the full pre-authorization, and leaving `final_total_cents` at 0; the venue's `tabs_open_count` is recomputed. A tab void is permitted only when the tab's `running_subtotal_cents` is exactly 0 — a tab that is carrying charges cannot be voided and must be settled instead, and the attempt to void it is rejected with `ERR_TAB_NOT_EMPTY`. Both `SETTLED` and `VOIDED` are terminal for a tab.

Settling a **seated reservation** is where tables, tabs, and minimums meet, and a `FloorManager` drives it. The reservation must be `SEATED`, and its linked tab (the tab whose `reservation_id` names this reservation), if one exists, is settled as part of this operation. The minimum-spend top-up is computed in a fixed order to resolve the apparent circularity between the tab's total and the reservation's shortfall. First, the linked tab's pre-top-up grand total is computed exactly as an ordinary settlement would compute it — the non-voided subtotal plus the once-rounded gratuity, over the lines that exist before any top-up. Second, the shortfall is the contracted `spend_minimum_cents` minus that pre-top-up grand total, floored at zero. Third, if the shortfall is positive, a single `SERVICE` line named "Minimum top-up" is appended to the linked tab with `qty` 1 and `unit_price_cents` equal to the shortfall; because this line is appended only after the gratuity has already been computed in the first step, it does not itself attract gratuity. Fourth, the tab then settles, and its `final_total_cents` is the pre-top-up grand total plus the shortfall; the reservation's `minimum_shortfall_cents` records the same shortfall, and the reservation moves `SEATED → SETTLED`. When the pre-top-up total already meets or exceeds the minimum, the shortfall is zero, no `SERVICE` line is appended, and the tab's `final_total_cents` is just the pre-top-up grand total. When the pre-top-up total falls under the minimum, the shortfall is positive, the top-up line is appended at a `unit_price_cents` equal to the shortfall, and the tab's `final_total_cents` lands exactly on `spend_minimum_cents`. If a seated reservation has no linked tab at all, the pre-top-up grand total is treated as zero, so the shortfall equals the full `spend_minimum_cents`.

### 3.8. Closing the Venue and the Full Cascade

Closing is the venue's terminal event. A `FloorManager` may close a venue explicitly, and the system also closes a venue automatically when the logical clock reaches its `closing_time_utc`. Either way, the close runs a single sweeping cascade over the venue's children, and at the end the venue's `posture` becomes `CLOSED` and its `version` is incremented by 1.

The cascade resolves every open child. Every reservation still in `BOOKED` is moved to `NO_SHOW`, forfeiting its `deposit_cents`. Every reservation in `SEATED` is settled — moved `SEATED → SETTLED` with its `minimum_shortfall_cents` computed exactly as in §3.7 — which in turn drives the settlement of its linked tab, appending the minimum top-up where one is owed. Every tab still in `OPEN` or `RUNNING` is settled, its `final_total_cents` computed per §3.7 and its pre-authorization captured up to that total with the remainder released; because the close forces these settlements, the pre-authorization-sufficiency check is waived during the cascade. Every entry still `INSIDE` is moved to `EXITED` with `exited_at_utc` stamped, driving the venue's `occupancy_count` to 0. Each entity the cascade touches has its `updated_at` refreshed and, where versioned, its `version` incremented, so that nothing is left in a stale or open state behind a closed venue.

Earlier in this section it was noted that posture transitions to `LAST_CALL` and `CLOSED` are clock-driven. The boundaries are precise. The venue enters `LAST_CALL` once the logical clock reaches the instant `last_call_offset_minutes` before `closing_time_utc` and remains in last call while the clock is still strictly before `closing_time_utc`; entering last call stops new alcohol items venue-wide and blocks new tab opens, while existing tabs may still be settled. The venue moves to `CLOSED` once the clock reaches `closing_time_utc`. These recomputations happen whenever the clock is advanced, and any close that has come due runs its cascade at that moment.

### 3.9. Security Incidents and the Refusal Record

A `SecurityOfficer` files a **Security Incident** against a venue by supplying the `venue_id`, a `severity` of `MINOR`, `SERIOUS`, or `CRITICAL`, an `action` of `WARNING`, `EJECTION`, or `REFUSAL_SERVICE`, and a free-text `narrative` describing what happened. The incident may optionally name a `subject_entry_id` identifying the patron involved; for a venue-wide incident with no single subject, this is left null. The server stamps `logged_at_utc` from the logical clock when the incident is filed. As described in §3.5, an incident whose `action` is `EJECTION` naming a subject entry that is currently `INSIDE` triggers the ejection cascade on that entry. Incidents may be listed and filtered by `venue_id`, by `subject_entry_id`, and by `severity`. Like every other child write, filing an incident is refused with `ERR_VENUE_CLOSED` once the venue is closed.

### 3.10. The Order of Validation

When several checks could reject a single request, they are evaluated in a fixed priority order, so that the rejection a client receives is deterministic. Authentication comes first: a missing or unknown-role header set yields `ERR_UNAUTHENTICATED` before anything else is considered. Authorization follows: a well-authenticated but unpermitted role yields `ERR_FORBIDDEN_ROLE`. Next, path identifiers are resolved left to right, and an unresolved path id yields `ERR_NOT_FOUND`. Then body foreign keys are resolved — a dangling `promoter_id`, `reservation_id`, `guest_list_entry_id`, `id_check_id`, or `subject_entry_id` yields `ERR_FK_NOT_FOUND`. Then the request shape is validated — a missing required field, a wrong type, an out-of-range enum value, or a negative value where a non-negative one is required yields `ERR_INVALID_REQUEST`.

Only after those structural checks does the optimistic-concurrency check run on the two guarded creates: a mismatched `expected_venue_version` yields `ERR_STALE_VENUE_VERSION`. The venue-closed gate comes next, so that a closed venue surfaces as `ERR_VENUE_CLOSED` ahead of any state-specific check. After it, the target resource's own state is checked — a transition requested from a state that does not admit it yields `ERR_INVALID_STATE`. Finally the business-safety, temporal, capacity, and fiscal rules apply: the ID-check gate (`ERR_ID_CHECK_NOT_PASSED`), the last-call alcohol gate (`ERR_LAST_CALL_NO_ALCOHOL`), the over-service gate (`ERR_OVER_SERVICE_REFUSED`), the reservation-window gate (`ERR_RESERVATION_WINDOW`), the table double-book gate (`ERR_TABLE_DOUBLE_BOOKED`), the re-entry gate (`ERR_PATRON_ALREADY_INSIDE`), the capacity gate (`ERR_AT_CAPACITY`), the comp-budget gate (`ERR_COMP_BUDGET_EXCEEDED`), and the pre-authorization gate (`ERR_PREAUTH_INSUFFICIENT`) each fire in the context of the operation they guard, as described in the workflows above.

A note on test-driving capabilities: an administrative endpoint advances the logical clock to a supplied `to_iso8601` instant, recomputing every venue's posture and running any due close cascade; this is a `PlatformAdmin`-only capability. A second administrative capability seeds a venue's occupancy directly, admitting `target_inside` synthetic patrons (each backed by an auto-generated passing ID check and an `INSIDE` entry) so the venue's `occupancy_count` equals `target_inside`, recomputing posture and incrementing the venue's `version` by 1 as a single mutation; it exists only to set up the surge and capacity bands cheaply and is likewise restricted to `PlatformAdmin`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the lifecycle transitions (seat, settle, exit, close, void, cancel, and so on) — return a `200 OK` status code. The clock-set and occupancy-seed test-driving capabilities also return `200 OK`. The complete request and response semantics for each endpoint are described in the §3 workflows above; the table below gives only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/nightclub/venues` | Create a venue (posture OPEN, occupancy 0, version 1) | PlatformAdmin |
| GET | `/nightclub/venues` | List venues | PlatformAdmin, FloorManager, DoorHost, Bartender, SecurityOfficer |
| GET | `/nightclub/venues/{id}` | Read a venue with computed occupancy, tabs-open count, posture, version | PlatformAdmin, FloorManager, DoorHost, Bartender, SecurityOfficer |
| POST | `/nightclub/venues/{id}/close` | Operator close; runs the full close cascade | FloorManager, PlatformAdmin |
| POST | `/nightclub/promoters` | Register a promoter under a venue | FloorManager, PlatformAdmin |
| GET | `/nightclub/promoters` | List promoters (filter by venue_id) | FloorManager, PlatformAdmin, DoorHost |
| GET | `/nightclub/promoters/{id}` | Read a promoter with computed comp/heads counters | FloorManager, PlatformAdmin, DoorHost |
| POST | `/nightclub/guest-list` | Add a guest-list entry | DoorHost, FloorManager, PlatformAdmin |
| GET | `/nightclub/guest-list` | List guest-list entries (filter by venue_id, promoter_id, redeemed_entry_id) | DoorHost, FloorManager, PlatformAdmin |
| GET | `/nightclub/guest-list/{id}` | Read a guest-list entry | DoorHost, FloorManager, PlatformAdmin |
| POST | `/nightclub/guest-list/{id}/cancel` | Cancel a guest-list entry; releases the comp | DoorHost, FloorManager, PlatformAdmin |
| POST | `/nightclub/id-checks` | Run an ID/age verification; server computes outcome and refusal reason | DoorHost, SecurityOfficer, PlatformAdmin |
| GET | `/nightclub/id-checks` | List ID checks / refusal log (filter by venue_id, outcome) | DoorHost, SecurityOfficer, FloorManager, PlatformAdmin |
| GET | `/nightclub/id-checks/{id}` | Read an ID check | DoorHost, SecurityOfficer, FloorManager, PlatformAdmin |
| POST | `/nightclub/entries` | Admit a patron (occupancy + cover); OCC-guarded on venue version | DoorHost, PlatformAdmin |
| GET | `/nightclub/entries` | List entries (filter by venue_id, status, guest_list_entry_id, id_check_id) | DoorHost, FloorManager, SecurityOfficer, PlatformAdmin |
| GET | `/nightclub/entries/{id}` | Read an entry | DoorHost, FloorManager, SecurityOfficer, PlatformAdmin |
| POST | `/nightclub/entries/{id}/exit` | Mark a patron exited; decrements occupancy, may revert posture | DoorHost, SecurityOfficer, PlatformAdmin |
| POST | `/nightclub/reservations` | Book a table reservation; OCC-guarded on venue version; rejects double-booking | FloorManager, PlatformAdmin |
| GET | `/nightclub/reservations` | List reservations (filter by venue_id, status, table_label) | FloorManager, DoorHost, PlatformAdmin |
| GET | `/nightclub/reservations/{id}` | Read a reservation with computed minimum shortfall | FloorManager, DoorHost, PlatformAdmin |
| POST | `/nightclub/reservations/{id}/seat` | Seat a booked reservation | FloorManager, PlatformAdmin |
| POST | `/nightclub/reservations/{id}/no-show` | Mark a booked reservation a no-show; deposit forfeited | FloorManager, PlatformAdmin |
| POST | `/nightclub/reservations/{id}/cancel` | Cancel a booked reservation before its window; deposit refunded | FloorManager, PlatformAdmin |
| POST | `/nightclub/reservations/{id}/settle` | Settle a seated reservation; compute shortfall and settle linked tab | FloorManager, PlatformAdmin |
| POST | `/nightclub/tabs` | Open a bar tab with a card pre-authorization | Bartender, FloorManager, PlatformAdmin |
| GET | `/nightclub/tabs` | List tabs (filter by venue_id, status, reservation_id) | Bartender, FloorManager, PlatformAdmin |
| GET | `/nightclub/tabs/{id}` | Read a tab with subtotal, strikes, final total | Bartender, FloorManager, PlatformAdmin |
| POST | `/nightclub/tabs/{id}/items` | Add a line item; alcohol gated by last-call and over-service rules | Bartender, FloorManager, PlatformAdmin |
| GET | `/nightclub/tabs/{id}/items` | List items on a tab | Bartender, FloorManager, PlatformAdmin |
| POST | `/nightclub/tabs/{tid}/items/{itemid}/void` | Void a line item; may revert state and adjust strikes | Bartender, FloorManager, PlatformAdmin |
| POST | `/nightclub/tabs/{id}/settle` | Settle a tab; compute final total, capture pre-auth, release remainder | Bartender, FloorManager, PlatformAdmin |
| POST | `/nightclub/tabs/{id}/void` | Void an entire empty tab; release full pre-auth | FloorManager, PlatformAdmin |
| POST | `/nightclub/incidents` | File a security incident; EJECTION cascades the subject entry | SecurityOfficer, FloorManager, PlatformAdmin |
| GET | `/nightclub/incidents` | List incidents (filter by venue_id, subject_entry_id, severity) | SecurityOfficer, FloorManager, PlatformAdmin |
| GET | `/nightclub/incidents/{id}` | Read a security incident | SecurityOfficer, FloorManager, PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock; recompute all venue postures | PlatformAdmin |
| POST | `/_inject/occupancy` | Test-driving: seed a venue's occupancy to a target count | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VENUE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ID_CHECK_NOT_PASSED` | 422 Unprocessable Entity |
| `ERR_LAST_CALL_NO_ALCOHOL` | 422 Unprocessable Entity |
| `ERR_OVER_SERVICE_REFUSED` | 422 Unprocessable Entity |
| `ERR_RESERVATION_WINDOW` | 422 Unprocessable Entity |
| `ERR_TABLE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_AT_CAPACITY` | 409 Conflict |
| `ERR_PATRON_ALREADY_INSIDE` | 409 Conflict |
| `ERR_COMP_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PREAUTH_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_VENUE_CLOSED` | 409 Conflict |
| `ERR_TAB_NOT_EMPTY` | 409 Conflict |

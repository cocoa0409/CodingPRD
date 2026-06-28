# Pottery Ceramics Studio API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office API that runs a paint-your-own pottery and ceramics studio of the kind a walk-in customer would recognize as a "Color Me Mine" experience. The studio sells two intertwined things at once: floor time and finished objects. A guest arrives, pays a per-painter studio fee, picks bisque blanks off the shelf, draws on glazes and underglazes from the paint bar, and leaves the unfired pieces behind. Days later — after the studio has loaded those pieces into a kiln, fired a batch to temperature, and let them cool — the guest is notified that their pottery is ready and returns to pick it up. The API has to keep a live, honest running total of what a guest owes while their visit is still open, then settle that total exactly once at checkout with tier discounts and loyalty redemption folded in.

Around that core flow sit several supporting businesses that share the same customer base and the same loyalty currency: party and event packages booked in advance against a refundable deposit, multi-session wheel-throwing and hand-building class series with limited seats, a paint-bar inventory that must be decremented as supplies are consumed and restored when a visit is voided, and a loyalty program whose point balance, lifetime earnings, and membership tier must reconcile precisely across every settlement, reversal, and compensation. Because firing capacity is physically finite and several staff members work the counter and the kilns at once, the system also has to arbitrate concurrent attempts to load the same kiln and cascade state changes from a fired batch all the way down to the pieces, the visits, and the loyalty ledger.

The remainder of this document is organized into global, system-wide rules (Section 2), the business workflows that make up the studio's day (Section 3), a consolidated endpoint table (Section 4), and the error catalogue (Section 5). The business narratives in Section 3 are the authoritative source for request payloads and side effects; the endpoint table is intentionally terse.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request carries its caller identity in two mandatory HTTP headers: `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they act. The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `StudioStaff`, `StudioManager`, and `LoyaltyMember`.

A request whose `X-User-Role` header is absent or holds a value that is not one of these four known roles is rejected with `ERR_UNAUTHENTICATED`. There are two deliberate exceptions to the requirement that a recognized role be present: self-registration of a new loyalty member, and the opening of an anonymous walk-in visit. Both of these may be performed by `Anonymous`, which is itself a recognized role value. Once the caller is authenticated, the system checks whether their role is permitted to perform the requested operation according to the role matrix; a role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN_ROLE`.

Three of the four roles — `Anonymous`, `StudioStaff`, and `StudioManager` — carry an opaque identity. When `X-User-Role` is one of these, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it for audit but never compares it to any entity's `id`. The fourth role is identity-backed: when `X-User-Role` is `LoyaltyMember`, `X-User-ID` is the `id` of the acting `LoyaltyMember`, and ownership checks compare a resource's owning foreign key (the `member_id` on the visit, enrollment, booking, ledger row, or the member record itself) to `X-User-ID`. A `LoyaltyMember` who reads or acts on a resource whose owning `member_id` is not their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check is the reason a member may freely list their own visits, enrollments, bookings, and ledger entries, but may not reach into another member's records.

`StudioStaff` runs the front counter and the kilns: opening visits, adding pieces and supplies, settling visits, loading and firing kilns, marking pieces picked up, recording deposits, enrolling members, and marking attendance. `StudioManager` is a superset over all of those operational actions and additionally owns the privileged levers: inventory management, voids, comps, batch and booking and series cancellations, member suspension and reactivation, and control of the logical clock. The clock-control capability is restricted to `StudioManager` alone.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list is returned sorted by the resource's creation timestamp in ascending order — that is, by `created_at` from oldest to newest. The loyalty ledger listing follows this same chronological ordering, which is also the order in which the entries must be replayed.

Every paginated response carries the pagination bookkeeping in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system are mutable, first-class records that carry a common set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix, used for identity only — together with `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version`, an integer that begins at 1 and increments by one on every mutation of that resource. The mutable resources are `LoyaltyMember`, `PaintBarItem`, `StudioVisit`, `BisquePiece`, `KilnBatch`, `PartyBooking`, `ClassSeries`, and `Enrollment`.

The loyalty ledger entry is the one exception. A `LoyaltyLedgerEntry` is an append-only event record: it carries only an `id` and a `created_at`, and it has neither an `updated_at` nor a `version`, because it is never modified after it is written.

Time in this system is governed by a logical clock rather than wall-clock time. At startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real-world time. A manager may advance (or set) the clock to any supplied ISO 8601 UTC instant. Every temporal comparison in the system — whether a booking's scheduled time is in the future, whether a class enrollment window has closed, whether a kiln's firing has finished — reads this logical clock, never the host's wall clock. Setting the clock is also what drives the time-based sweeps described in Section 3.

### 2.5. Monetary and Point Precision

All money in this system is carried as whole integer cents; there are no fractional cents and no floating-point currency fields. Wherever a percentage or rate produces a fractional cent — the bisque tier discount, the party deposit — the result is rounded to the nearest whole cent using the round-half-up convention (a half-cent rounds up). Each calculation below states exactly where that single rounding step is applied, and rounding is applied only at the stated point, never repeatedly.

Loyalty points are likewise always whole integers. Where points are computed by dividing cents or by applying a bonus multiplier, the result is taken to the next-lower whole number (floored) at each step described, so that a member is never credited a fractional point. The detailed division and threshold rules live in Section 3 alongside the workflows that earn and spend points.

### 2.6. Derived Totals and Reconciliation

Several fields are not supplied by clients but are continuously derived from related records, and they must be kept in exact agreement with those records at all times. A studio visit maintains a `bisque_subtotal_cents` (the sum of the catalog prices of its live pieces), a `supplies_subtotal_cents` (the sum of its paint-bar charges), a `studio_fee_cents`, and a `provisional_total_cents` that is recomputed on demand while the visit is open. A kiln batch maintains an `occupied_slots` count that must always equal the number of pieces currently occupying it. A class series maintains an `enrolled_count`. A member maintains a `point_balance`, a `lifetime_points_earned`, and a derived `tier`. Each of these derived fields is recomputed by the operations that affect it, and recomputing such a field on its owning resource is a mutation that refreshes the owner's `updated_at` and increments its `version`.

### 2.7. Cascading State Changes and Compensation

Many operations in this domain touch more than one entity. Firing a kiln batch transitions every loaded piece within it; completing a firing transitions every firing piece to ready; cancelling a batch returns its loaded pieces to the painted state and zeroes its occupied count. Voiding a visit voids the visit's non-terminal pieces, un-loads any of them that were sitting in a kiln (decrementing that kiln's occupied count and bumping its version), and restores consumed inventory. Cancelling a class series refunds and reverses points for every active enrollment. Each of these cascades, and the exact bookkeeping each one performs, is described in full in the relevant Section 3 workflow. The governing principle here is that no cascade may leave a derived field, a slot count, an inventory level, or a loyalty balance out of agreement with the events that produced it.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several read endpoints are addressed through a parent resource — a member's visits, a member's ledger, a batch's pieces, a series' enrollments. For any path that names a resource identifier, the server validates that identifier's existence before proceeding, and where a path or body carries more than one identifier the checks proceed left to right. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND`; existence is always confirmed before any state, business, or ownership rule is evaluated.

### 2.9. Optimistic Concurrency on Kiln Loading

Loading a bisque piece into a kiln batch is the one operation in this system that is guarded by optimistic concurrency control, because the kiln's remaining capacity is a finite pool that several staff may try to fill at once. The load request must carry an `expected_kiln_batch_version` field whose value is the client's last-observed `version` of the target `KilnBatch`. The server compares that supplied value against the batch's current `version`. If they do not match — because some other load or un-load has already advanced the batch's version and shifted its occupied count since the client last read it — the load is rejected with `ERR_STALE_BATCH_VERSION` (HTTP 412) on the stale-version check, before any slot is consumed. The supplied `expected_kiln_batch_version` is a required input on the load operation. No other operation in the system takes a version field; loading is the only endpoint that participates in this concurrency control.

### 2.10. Validation Ordering

When several checks apply to a single operation, they are evaluated in a fixed priority order so that the same request always fails the same way. Authentication is checked first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Role authorization is checked next, yielding `ERR_FORBIDDEN_ROLE`. For a member acting on their own resources, ownership is checked third, yielding `ERR_NOT_RESOURCE_OWNER`. The existence of every referenced identifier is checked fourth, yielding `ERR_NOT_FOUND`. Only then is the target's state checked against the requested transition, yielding `ERR_INVALID_STATE` when the resource is not in a state that permits the action. After state comes the layer of domain-specific business rules — referential, safety, capacity, temporal, fiscal, and concurrency checks — each described with its workflow in Section 3. Field-shape validation (required fields present, enums within their allowed values, integers non-negative where required, `party_size` at least 1, `guest_count` at least the package minimum) is the catch-all and surfaces as `ERR_INVALID_REQUEST`. Within a single operation that bundles several business checks, the order in which those checks fire is given in the workflow that defines them.

## 3. Business Logic & Workflows

### 3.1. Loyalty Members, Tiers, and the Points Currency

The loyalty member is the studio's customer of record. Anyone — including an `Anonymous` caller — may self-register a member by supplying an `email`, a `full_name`, and a `phone` number. The email is the member's login handle and is lowercased on store; the phone is the contact used for pickup notifications. Although the email is conceptually the member's unique handle, registration does not reject a second member registered with an already-used email — uniqueness is not enforced as a registration-time constraint. A freshly registered member starts `ACTIVE`, in the `BRONZE` tier, with a `point_balance` of 0 and a `lifetime_points_earned` of 0. The member's `status` is either `ACTIVE` or `SUSPENDED`; a `SUSPENDED` member may neither enroll in a class nor redeem points. A manager may move a member to `SUSPENDED` and may later return them to `ACTIVE`.

Two distinct point counters live on every member and they behave differently. The `point_balance` is the spendable balance: points are added to it when a visit or enrollment settles and subtracted from it when the member redeems them or when a reversal claws them back. The `lifetime_points_earned` is a running record of everything ever earned; it climbs on every earning event but is never reduced by a redemption. It is reduced only when a previously credited earning is reversed — for example when an enrollment is withdrawn or its series is cancelled before settlement holds — so that an unwound credit is unwound from both counters.

A member's `tier` is recomputed from `lifetime_points_earned` every time that figure changes. The mapping is by threshold and the boundaries are inclusive: a member whose lifetime earnings are at least 2000 points is `GOLD`; otherwise, a member with at least 500 points is `SILVER`; and below 500 the member is `BRONZE`. Exactly 500 lifetime points lands on `SILVER`, and exactly 2000 lands on `GOLD`. This recomputation runs after every checkout, every enrollment, and every reversal that moves `lifetime_points_earned`.

Every point movement is also written, in the same operation, as an immutable `LoyaltyLedgerEntry` so that the balance can be audited and replayed. Each entry records the owning `member_id`, an `entry_type` of `EARN`, `REDEEM`, or `REVERSAL`, a signed `points_delta` (positive for an earn, negative for a redemption, and signed for a reversal), and a polymorphic pointer to whatever produced it: a `source_ref_type` of `VISIT`, `ENROLLMENT`, or `BOOKING`, together with a `source_ref_id` holding the id of that originating visit, enrollment, or booking. The entry's `created_at` is the logical-clock instant of the event and is the chronological key by which the ledger is replayed and listed. A member, staff, or manager may list a member's ledger; a member may only list their own.

### 3.2. Opening a Visit and Building Its Running Total

A studio visit is the container for a single painting session. A visit is opened with a `party_size` (the number of painters, which must be at least 1), an optional `member_id` (omitted for an anonymous walk-in, present to attribute the visit and its loyalty to a member), an optional `visit_type`, and an optional `party_booking_id`. The `visit_type` is `WALK_IN` by default or `PARTY`; a `PARTY` visit is the one spawned from a confirmed party booking and carries the `party_booking_id` of that booking. The studio fee is charged per painter on a walk-in but waived for a party (whose head charge was already covered by the package), so at creation the `studio_fee_cents` is set to the number of painters multiplied by the per-painter studio fee of 1000 cents (that is, ten dollars each) for a `WALK_IN`, and set to 0 for a `PARTY`. The visit opens in `OPEN` status with its `provisional_total_cents` initialized to that studio fee.

While a visit is `OPEN` it accepts pieces and supply consumption, and its `provisional_total_cents` is a live estimate that is recomputed whenever the visit is read. The provisional total is simply the sum of three running components: the `studio_fee_cents`, the `bisque_subtotal_cents`, and the `supplies_subtotal_cents`. Crucially, the provisional figure applies no discount and no loyalty redemption whatsoever — it is the gross estimate of what is on the table, deliberately distinct from the settled figure computed at checkout. The `settled_total_cents` and `points_earned` fields stay at 0 for the whole time the visit is `OPEN`.

Staff add bisque pieces to an `OPEN` visit (see Section 3.3) and consume paint-bar supplies against it (see Section 3.7). A visit may be read by staff, by a manager, or by the owning member. Visits may be listed and filtered by `status`, by `member_id`, and by `party_booking_id`. The two terminal outcomes of a visit — settling it at checkout and voiding it — are covered in Sections 3.8 and 3.9.

### 3.3. Bisque Pieces and Their Journey Through the Kiln

A bisque piece is a single ceramic blank a painter is decorating. A piece is created against a studio visit by supplying a `sku` (the bisqueware catalog code), a `name`, a `bisque_price_cents` (the catalog price of the blank, which must be at least 1 cent), and an optional `firing_temp`. The firing temperature is `CONE_06` by default or `CONE_6`; it determines which kiln batches the piece may later join. A piece may only be added to a visit whose status is `OPEN`; an attempt to add a piece to a visit that is not `OPEN` is rejected with `ERR_VISIT_NOT_OPEN`. On creation the piece enters `PAINTED` status with no kiln assignment, and the visit's `bisque_subtotal_cents` and `provisional_total_cents` are recomputed to fold in the new blank's price. Each piece records the `studio_visit_id` it belongs to, and once it is placed in a kiln it records the `kiln_batch_id` of that batch; the batch reference is null until the piece is loaded and is cleared again whenever the piece leaves the batch.

A piece moves through a defined lifecycle of states: `PAINTED`, `LOADED`, `FIRING`, `READY`, `PICKED_UP`, and `VOIDED`. Loading advances a piece from `PAINTED` to `LOADED` (Section 3.4). A loaded piece that has not yet been fired may be un-loaded back to `PAINTED`: un-loading is permitted only while the piece is `LOADED` and its batch is still `LOADING`, and it clears the piece's `kiln_batch_id`, decrements that batch's `occupied_slots` by one to compensate the earlier load, and increments the batch's `version`. When a batch starts firing, each of its `LOADED` pieces cascades to `FIRING`; when the firing completes, each `FIRING` piece cascades to `READY` and is stamped with a `ready_at` equal to the completion instant. The `ready_at` timestamp is the basis for the pickup notification and is null until the piece reaches `READY`.

Once a piece is `READY` it is eligible for pickup. Marking a `READY` piece picked up advances it from `READY` to `PICKED_UP`; this is permitted only from `READY`. A pickup-notification payload is available for any piece that is `READY` or `PICKED_UP`, exposing the piece's `ready_at` together with the owning member's contact details so the studio can tell the customer their pottery is finished. The notification payload is the full piece resource object (its `id`, `status`, `ready_at`, and all the other piece fields) augmented with an additional `member_contact` object holding the owning member's `member_id`, `full_name`, `phone`, and `email`; for an anonymous walk-in piece that has no owning member, each of those four `member_contact` fields is null. Requesting the notification payload for a piece that is not `READY` or `PICKED_UP` is rejected with `ERR_INVALID_STATE`. Pieces may be read individually, and listed and filtered by `studio_visit_id`, by `kiln_batch_id`, and by `status`. A piece that has reached `PICKED_UP` or `VOIDED` is terminal.

### 3.4. Loading the Kiln: Capacity, Temperature, and Concurrency

A kiln batch is a single firing load. A batch is created with a `kiln_name` (the physical kiln label), an optional `firing_temp` (again `CONE_06` by default or `CONE_6`), a `capacity_slots` (the maximum number of pieces it holds, at least 1), and an optional `turnaround_hours` (the firing duration in hours, a non-negative integer defaulting to 48 when omitted). A new batch opens in `LOADING` status with `occupied_slots` at 0 and `version` at 1.

Loading a `PAINTED` piece into a batch is the busiest contention point in the studio and the most heavily guarded action. The load request names the piece via `bisque_piece_id` and carries the `expected_kiln_batch_version` described in Section 2.9. For a load to succeed: the piece must be `PAINTED`; the batch must be in `LOADING` status; the batch's `firing_temp` must equal the piece's `firing_temp`; the batch must have a free slot (its `occupied_slots` must be strictly less than its `capacity_slots`); the piece's owning studio visit must still be `OPEN`; and the supplied `expected_kiln_batch_version` must equal the batch's current `version`. When these hold, the piece's `kiln_batch_id` is set to the batch, the piece advances from `PAINTED` to `LOADED`, the batch's `occupied_slots` is incremented by one, and the batch's `version` is incremented by one. A successful load responds with `200 OK` and returns the updated bisque-piece resource object.

The order in which a failing load is reported matters. After existence and the basic state check (a non-`LOADING` batch or a non-`PAINTED` piece yields `ERR_INVALID_STATE`), a temperature disagreement between the piece and the batch is reported as `ERR_FIRING_TEMP_MISMATCH`. A batch whose `occupied_slots` has reached its `capacity_slots` is reported as `ERR_KILN_AT_CAPACITY`. And a stale `expected_kiln_batch_version` is reported as `ERR_STALE_BATCH_VERSION` (HTTP 412). Each of these is a 409 Conflict except the stale-version rejection, which is a 412. Last of all, after the stale-version check passes, the piece's owning studio visit is verified to still be `OPEN`; a piece whose visit is no longer `OPEN` is rejected with `ERR_VISIT_NOT_OPEN` (HTTP 409).

### 3.5. Firing, Completion, Cancellation, and the Clock Sweep

A batch is fired by starting it, which moves it from `LOADING` to `FIRING`. A batch may be started only while it is `LOADING` and only when it holds at least one piece — an empty kiln cannot be fired, so the batch's `occupied_slots` must be at least 1. On start, the batch's `started_at` is set to the current logical-clock instant and its `firing_completes_at` is set to that instant plus the batch's `turnaround_hours`; every `LOADED` piece on the batch cascades to `FIRING`; and the batch becomes `FIRING`.

Completing a firing moves the batch from `FIRING` to `COMPLETED`. Completion happens one of two ways: a staff member or manager completes it explicitly, or the logical clock is advanced to or past the batch's `firing_completes_at` and the completion sweep finishes it automatically. Either way, every `FIRING` piece on the batch cascades to `READY`, each stamped with a `ready_at` equal to the current logical-clock instant, and the batch becomes `COMPLETED`. Completion is permitted only from `FIRING`.

A batch may instead be cancelled by a manager while it is still `LOADING`. Cancellation returns every `LOADED` piece on the batch to `PAINTED` with its `kiln_batch_id` cleared, sets the batch's `occupied_slots` to 0, and moves the batch to `CANCELLED`. The batch states are `LOADING`, `FIRING`, `COMPLETED`, and `CANCELLED`, of which `COMPLETED` and `CANCELLED` are terminal. Batches may be read, listed and filtered by `status` and `firing_temp`, and their member pieces listed by batch.

### 3.6. Party Bookings and the Deposit

A party booking reserves the studio for an event. A booking is created against a host member by supplying that `member_id` (the host, who must exist; the host's `status` is not checked at booking creation, so a `SUSPENDED` member may still host a booking), a `package_tier` of either `BASIC` or `DELUXE`, a `guest_count`, and a `scheduled_for` event start time. The scheduled time must be strictly after the current logical clock at creation; a booking whose `scheduled_for` is not strictly in the future is rejected with `ERR_BOOKING_DATE_PAST` (HTTP 422). The guest count must meet the package minimum — at least 6 guests for a `BASIC` package and at least 10 for a `DELUXE` package — and a count below the minimum is a field-shape failure (`ERR_INVALID_REQUEST`). For this operation specifically, after the host member's existence is confirmed the guest-count-minimum check is evaluated before the `scheduled_for` future-date check, so a booking that both undershoots the package minimum and names a non-future date is rejected with `ERR_INVALID_REQUEST`.

At creation the booking's price and deposit are computed and pinned. The per-head rate is 4500 cents for a `BASIC` package and 8000 cents for a `DELUXE` package. The `package_total_cents` is the `guest_count` multiplied by that per-head rate. The `deposit_due_cents` is one quarter of the package total — the package total multiplied by 0.25 — rounded to the nearest whole cent using round-half-up, with that single rounding applied once to the deposit figure. The booking opens in `DEPOSIT_PENDING` status with `deposit_paid_cents` at 0.

A booking in `DEPOSIT_PENDING` has three possible fates. Paying the deposit moves it from `DEPOSIT_PENDING` to `CONFIRMED`: the payment supplies an `amount_cents` that must exactly equal the booking's `deposit_due_cents` (a mismatch is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`, HTTP 422) and the clock must still be before the booking's `scheduled_for`. After the `DEPOSIT_PENDING` state check, the clock-before-`scheduled_for` check is evaluated next and a booking whose `scheduled_for` the clock has reached or passed is rejected with `ERR_INVALID_STATE` (HTTP 409); only then is the `amount_cents` compared against `deposit_due_cents`. On success the `deposit_paid_cents` is set to the paid amount and the booking is `CONFIRMED`. Expiring a booking moves it from `DEPOSIT_PENDING` to `EXPIRED`; this happens when a manager expires it or when the clock reaches or passes the booking's `scheduled_for` and the expiry sweep fires, and it requires that the clock be at or past `scheduled_for` (a manual expire attempted while the clock is still before `scheduled_for` is rejected with `ERR_INVALID_STATE`, HTTP 409). Cancelling a booking moves it from `DEPOSIT_PENDING` to `CANCELLED` at a manager's request. The booking states are `DEPOSIT_PENDING`, `CONFIRMED`, `EXPIRED`, and `CANCELLED`. Bookings may be read by staff, manager, or the host member, and listed and filtered by `status` and `member_id`.

### 3.7. Paint-Bar Inventory and Supply Consumption

The paint bar is stocked with sellable items, each a `PaintBarItem`. A manager adds an item with a `sku` (for example a glaze stock code; conceptually unique, but a duplicate `sku` is not rejected at creation — uniqueness is not enforced as a constraint), a display `name`, a `category` of `GLAZE`, `UNDERGLAZE`, `TOOL`, or `TOGO_KIT`, a `unit_price_cents` (the retail price per unit, which must be at least 0), and an optional `reorder_threshold` (a non-negative integer that defaults to 0 when omitted). A new item starts with `on_hand_qty` at 0 and `status` `ACTIVE`. An item's `status` is `ACTIVE` or `DISCONTINUED`; a discontinued item can no longer be consumed. The `on_hand_qty` is the current stock and never drops below 0. The `low_stock` flag is derived: it is true exactly when the `on_hand_qty` is at or below the `reorder_threshold`. A manager restocks an item by supplying a `qty` to add to its `on_hand_qty`, after which `low_stock` is recomputed; a manager may also discontinue an item. Items may be read, and listed and filtered by `category` and by `low_stock`.

Consuming a supply against an `OPEN` visit records a line and decrements stock. The consume request names the item via `paint_bar_item_id` and a `qty` (an integer of at least 1). The item must be `ACTIVE` and must have at least the requested quantity on hand — if the item is discontinued or its `on_hand_qty` is below the requested `qty`, the consume is rejected with `ERR_INSUFFICIENT_STOCK`; and if the visit is not `OPEN`, it is rejected with `ERR_VISIT_NOT_OPEN`. The charge for the line is the quantity multiplied by the item's `unit_price_cents`, with one twist: when the line quantity is at least 3, a bulk break applies, multiplying the line by nine-tenths (a ten-percent discount) and rounding that discounted line to the nearest whole cent with round-half-up. The rounding is applied per line, after the bulk multiplier, and the lines are then summed without any further rounding to produce the visit's `supplies_subtotal_cents`. On a successful consume, the item's `on_hand_qty` is decreased by the consumed quantity and the visit's `supplies_subtotal_cents` and `provisional_total_cents` are recomputed; the consume operation responds with `201 Created` and returns the updated studio-visit resource object (the consume line itself is internal bookkeeping and is not exposed as a resource).

This consumption is reversible. When a visit is voided, every supply line on it is treated as a compensating restore: the line's quantity is added back to the originating item's `on_hand_qty`, and a voided line is excluded from the supplies subtotal. The forward consume decrements stock by the quantity; the void-time restore increments it by the same quantity, so the paint bar's books always reconcile.

### 3.8. Checkout: The Two-Variant Settlement

Checkout is the moment a visit's gross running estimate becomes a final, discounted, loyalty-adjusted charge. Only a visit that is `OPEN` may be checked out (a checkout of a visit that is not `OPEN` is rejected with `ERR_INVALID_STATE`, HTTP 409), and a critical safety gate applies first: every piece on the visit must already be in `READY`, `PICKED_UP`, or `VOIDED`. If any piece is still `PAINTED`, `LOADED`, or `FIRING` — that is, still somewhere in the kiln pipeline — the checkout is blocked with `ERR_PIECES_NOT_READY`, because a guest cannot settle and walk away while their pottery is still in the kiln. Checkout accepts an optional `points_redeemed` value (the number of loyalty points the member elects to spend); it is 0 for an anonymous visit. If redemption is requested it is validated: the visit must belong to a member — a redemption of more than 0 points on an anonymous visit (one with no `member_id`) is rejected with `ERR_INSUFFICIENT_POINTS` (HTTP 422) — that member must be `ACTIVE` (a suspended member redeeming is rejected with `ERR_MEMBER_SUSPENDED`), and the requested `points_redeemed` must not exceed the member's `point_balance` (an over-redemption is rejected with `ERR_INSUFFICIENT_POINTS`, HTTP 422). These redemption checks fire in that order, after the `ERR_PIECES_NOT_READY` safety gate, and only when `points_redeemed` is greater than 0.

The settled charge is computed in a pinned order, because each step feeds the next. First the base components are summed: the `studio_fee_cents` (the per-painter fee for a walk-in, 0 for a party), the bisque subtotal (the sum of `bisque_price_cents` over every piece on the visit that is not `VOIDED`), and the supplies subtotal (the sum of the consume-line charges as computed in Section 3.7). Their sum is the subtotal before discount. Second, the tier discount is computed, and it applies to the bisque subtotal only: the discount percentage is keyed off the member's tier at checkout time — 0 for `BRONZE`, five percent for `SILVER`, and ten percent for `GOLD`, and 0 when the visit has no member — and the tier discount is the bisque subtotal multiplied by that percentage, rounded to the nearest whole cent with round-half-up. This rounding is applied once to the single product, not piece by piece. Third, the redemption value is computed at one cent per point: the `points_redeemed` multiplied by the per-point redemption value of 1 cent. The `discount_cents` pinned on the visit is the sum of the tier discount and the redemption value. Fourth, the `settled_total_cents` is the subtotal before discount minus the total discount, floored at 0 so it can never go negative. The difference between the provisional estimate read while the visit was open and this settled figure is exactly the `discount_cents`.

When the visit belongs to a member, checkout also credits loyalty. The points earned are computed from the post-discount net spend — the `settled_total_cents` itself. The base award is one point per 100 cents of net spend, taking the net spend, dividing by 100, and flooring to a whole number. A bonus then applies when the net spend is at least 10000 cents: if the net spend meets or exceeds that threshold, the base points are multiplied by 1.5 and floored to a whole number; below the threshold, the points earned equal the base award with no multiplier. Exactly 10000 cents of net spend triggers the bonus; one cent less does not. The resulting `points_earned` is pinned on the visit, the member's `point_balance` is increased by that amount, and the member's `lifetime_points_earned` is increased by the same amount. An anonymous visit earns 0 points, and `points_earned` is 0 while a visit is `OPEN` regardless.

The settlement's side effects are then committed in concert. If the member earned points, an `EARN` ledger entry is appended for the earned amount with `source_ref_type` `VISIT`. If the member redeemed points, their `point_balance` is decreased by `points_redeemed` and a `REDEEM` ledger entry is appended for the negative of that amount, again with `source_ref_type` `VISIT`. The member's `tier` is recomputed from the updated `lifetime_points_earned`. Every piece that is `READY` or `PICKED_UP` remains as it is. The visit moves from `OPEN` to `SETTLED`, which is terminal.

A live preview of the loyalty award is available before checkout. The points preview estimates points using the visit's gross `provisional_total_cents` as the net spend rather than the settled total, running the same one-point-per-100-cents floor and the same at-least-10000-cents bonus rule. Because the estimate uses the pre-discount figure while the actual award uses the post-discount settled total, the estimate is greater than or equal to the actual award whenever any discount applies. The preview only reports the estimate; it pins nothing. The preview response is the visit resource object as it currently stands (with its live provisional total recomputed), except that its `points_earned` field is overwritten with the estimated award (0 for a visit with no member); none of the visit's persisted fields are mutated by reading the preview.

### 3.9. Voiding a Visit

Voiding is a manager-only escape hatch that unwinds an `OPEN` visit completely. A visit may be voided only while it is `OPEN`; voiding a visit that is not `OPEN` is rejected with `ERR_INVALID_STATE` (HTTP 409). The void cascades to every non-terminal piece on the visit — every piece that is `PAINTED`, `LOADED`, `FIRING`, or `READY` — moving each to `VOIDED`. For any piece that was sitting in a kiln (that is, `LOADED`, `FIRING`, or `READY`), the void also un-loads it from its batch: the batch's `occupied_slots` is decremented by one, the batch's `updated_at` is refreshed, the batch's `version` is incremented, and the piece's `kiln_batch_id` is cleared. Every paint-bar item consumed on the visit is compensated by restoring its consumed quantity to the item's `on_hand_qty`, as described in Section 3.7. The visit's `settled_total_cents` stays at 0 and the visit moves from `OPEN` to `VOIDED`, which is terminal.

### 3.10. Class Series, Enrollment, and Class Loyalty

A class series is a multi-session offering such as a wheel-throwing course. A manager creates a series with a `title`, a `session_count` (the number of weekly sessions, at least 1), a `seat_capacity` (the maximum number of enrollments, at least 1), a `price_cents` (the full-series price per seat, at least 1), and a `starts_at` (the first session time). A series opens in `OPEN` status with `enrolled_count` at 0. The series tracks its `enrolled_count` as the number of enrollments that are `ENROLLED` or `ATTENDED`, and its status moves among `OPEN`, `FULL`, `STARTED`, and `CANCELLED`.

A member enrolls in an `OPEN` series; the enroll request supplies the `member_id` of the enrollee, who must be an `ACTIVE` member. A member acting for themselves must enroll with their own `member_id` matching `X-User-ID`; a `LoyaltyMember` who supplies a `member_id` other than their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`, a check applied after the series and member identifiers are confirmed to exist and before the series-state and business checks. Several checks guard enrollment, each with its own rejection, evaluated in the order they are listed here: the series must be `OPEN` — a series that is `FULL` is rejected with `ERR_SERIES_FULL`, while a `STARTED` or `CANCELLED` series is rejected with `ERR_INVALID_STATE`; a series whose `enrolled_count` has reached its `seat_capacity` is full and is rejected with `ERR_SERIES_FULL`; a member who already holds a non-cancelled enrollment in this series is rejected with `ERR_DUPLICATE_ENROLLMENT`; an enrollment attempted once the logical clock has reached or passed the series' `starts_at` is rejected with `ERR_ENROLLMENT_CLOSED` because the window has closed; and a suspended member is rejected with `ERR_MEMBER_SUSPENDED`.

On a successful enroll, an enrollment record is created carrying the `class_series_id` of its series and the `member_id` of the enrollee; the series' `price_cents` is snapshotted onto the enrollment as its `amount_paid_cents`, and class loyalty is earned and credited immediately. Class points are computed on their own rule, distinct from visit points: the base award is the `amount_paid_cents` divided by 100 and floored to a whole number. A long-series bonus then adds a flat 50 points when the series runs at least 6 sessions — that is, when the `session_count` is 6 or more, the points earned are the base award plus 50; otherwise the points earned equal the base award alone. (For completeness, the per-session cost of the series — the `amount_paid_cents` divided by the `session_count`, floored — is the per-session figure underlying this offering.) The resulting `points_earned` is recorded on the enrollment, added to the member's `point_balance` and to their `lifetime_points_earned`, an `EARN` ledger entry is appended with `source_ref_type` `ENROLLMENT`, and the member's `tier` is recomputed. The series' `enrolled_count` is incremented by one, and if that increment brings the count up to the `seat_capacity` the series bubbles up from `OPEN` to `FULL`.

An enrollment travels through `ENROLLED`, `ATTENDED`, `WITHDRAWN`, and `REFUNDED`. Marking an enrollment attended moves it from `ENROLLED` to `ATTENDED` and is permitted only once its parent series is `STARTED`. Enrollments may be read individually, listed within a series, and listed for a member; a member sees only their own.

### 3.11. Withdrawing, Starting, and Cancelling a Series

A member (or staff on their behalf) may withdraw from a series before it begins. Withdrawal moves an enrollment from `ENROLLED` to `WITHDRAWN` and is permitted only while the parent series is still `OPEN` or `FULL` — once the series has `STARTED`, withdrawal is refused. Withdrawing reverses the loyalty that the enrollment earned: the member's `point_balance` is decreased by the enrollment's `points_earned`, the member's `lifetime_points_earned` is decreased by the same amount, and a `REVERSAL` ledger entry is appended for the negative of that amount with `source_ref_type` `ENROLLMENT`. The series' `enrolled_count` is decremented by one, and if the series was `FULL`, dropping below `seat_capacity` bubbles it back up from `FULL` to `OPEN` because a seat has reopened. The member's `tier` is then recomputed.

A manager starts a series, moving it from `OPEN` or `FULL` to `STARTED`; starting requires the series to be in `OPEN` or `FULL` and the logical clock to have reached or passed the series' `starts_at` (a manual start attempted before the series is `OPEN`/`FULL`, or while the clock is still before `starts_at`, is rejected with `ERR_INVALID_STATE`, HTTP 409). Starting may also happen automatically: when the clock is advanced to or past a series' `starts_at`, the series-start sweep starts it. Once a series is `STARTED`, further enrollment is rejected. A series in `OPEN` or `FULL` may instead be cancelled by a manager, which moves it to `CANCELLED`. Cancellation cascades to every still-`ENROLLED` enrollment: each is moved to `REFUNDED`, and for each one the earned loyalty is reversed exactly as in a withdrawal — the member's `point_balance` and `lifetime_points_earned` are each decreased by that enrollment's `points_earned`, and a `REVERSAL` ledger entry with `source_ref_type` `ENROLLMENT` is appended. Every affected member's `tier` is recomputed. The series states `STARTED` and `CANCELLED` are terminal.

### 3.12. The Logical Clock and Its Sweeps

A manager may set the server's logical clock to a supplied instant via the clock-control capability, whose body carries the target instant as `to_iso8601`. Advancing the clock is not merely bookkeeping: moving it forward triggers three sweeps over the affected records. Any batch whose `firing_completes_at` is now at or before the clock and is still `FIRING` is completed, cascading its `FIRING` pieces to `READY` as in Section 3.5. Any booking still `DEPOSIT_PENDING` whose `scheduled_for` is now at or before the clock is expired as in Section 3.6. Any series still `OPEN` or `FULL` whose `starts_at` is now at or before the clock is started as in Section 3.11. These sweeps make the clock the single driver of all time-based transitions in the system.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. Request payloads and side effects are defined in the Section 3 narratives, not here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/loyalty-members` | Register a loyalty member | Anonymous, StudioStaff, StudioManager |
| GET | `/loyalty-members/{id}` | Fetch a member | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/loyalty-members` | List members (filter by email) | StudioStaff, StudioManager |
| POST | `/loyalty-members/{id}/suspend` | Suspend a member | StudioManager |
| POST | `/loyalty-members/{id}/reactivate` | Reactivate a suspended member | StudioManager |
| GET | `/loyalty-members/{id}/ledger` | List the member's loyalty ledger entries | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/loyalty-members/{id}/visits` | List a member's visits | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/loyalty-members/{id}/enrollments` | List a member's enrollments | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/loyalty-members/{id}/party-bookings` | List bookings hosted by a member | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/paint-bar-items` | Add a paint-bar inventory item | StudioManager |
| GET | `/paint-bar-items/{id}` | Fetch an inventory item | StudioStaff, StudioManager |
| GET | `/paint-bar-items` | List inventory (filter by category, low_stock) | StudioStaff, StudioManager |
| POST | `/paint-bar-items/{id}/restock` | Increase on-hand quantity | StudioManager |
| POST | `/paint-bar-items/{id}/discontinue` | Mark item discontinued | StudioManager |
| POST | `/studio-visits` | Open a walk-in or party visit | Anonymous, StudioStaff, StudioManager |
| GET | `/studio-visits/{id}` | Fetch a visit with live provisional total | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/studio-visits` | List visits (filter by status, member_id, party_booking_id) | StudioStaff, StudioManager |
| GET | `/studio-visits/{id}/points-preview` | Estimate points earned at current provisional total | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/studio-visits/{id}/pieces` | Add a bisque piece to an OPEN visit | StudioStaff, StudioManager |
| POST | `/studio-visits/{id}/consume` | Consume a paint-bar item on an OPEN visit | StudioStaff, StudioManager |
| POST | `/studio-visits/{id}/checkout` | Settle the visit; apply discount and loyalty | StudioStaff, StudioManager |
| POST | `/studio-visits/{id}/void` | Void an OPEN visit | StudioManager |
| GET | `/bisque-pieces/{id}` | Fetch a piece | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/bisque-pieces` | List pieces (filter by studio_visit_id, kiln_batch_id, status) | StudioStaff, StudioManager |
| POST | `/bisque-pieces/{id}/unload` | Un-load a LOADED piece back to PAINTED | StudioStaff, StudioManager |
| POST | `/bisque-pieces/{id}/pickup` | Mark a READY piece picked up | StudioStaff, StudioManager |
| GET | `/bisque-pieces/{id}/notification` | Pickup-notification payload for a READY/PICKED_UP piece | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/kiln-batches` | Create a kiln batch in LOADING | StudioStaff, StudioManager |
| GET | `/kiln-batches/{id}` | Fetch a batch | StudioStaff, StudioManager |
| GET | `/kiln-batches` | List batches (filter by status, firing_temp) | StudioStaff, StudioManager |
| GET | `/kiln-batches/{id}/pieces` | List pieces in a batch | StudioStaff, StudioManager |
| POST | `/kiln-batches/{id}/load` | Load a PAINTED piece into the batch | StudioStaff, StudioManager |
| POST | `/kiln-batches/{id}/start-firing` | Begin firing; cascade loaded pieces to firing | StudioStaff, StudioManager |
| POST | `/kiln-batches/{id}/complete-firing` | Complete firing; cascade firing pieces to ready | StudioStaff, StudioManager |
| POST | `/kiln-batches/{id}/cancel` | Cancel a LOADING batch; return pieces to PAINTED | StudioManager |
| POST | `/party-bookings` | Create a party booking with computed deposit | StudioStaff, StudioManager |
| GET | `/party-bookings/{id}` | Fetch a booking | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/party-bookings` | List bookings (filter by status, member_id) | StudioStaff, StudioManager |
| POST | `/party-bookings/{id}/pay-deposit` | Record exact deposit payment | StudioStaff, StudioManager |
| POST | `/party-bookings/{id}/expire` | Expire an overdue pending booking | StudioManager |
| POST | `/party-bookings/{id}/cancel` | Cancel a pending booking | StudioManager |
| POST | `/class-series` | Create a class/wheel series | StudioManager |
| GET | `/class-series/{id}` | Fetch a series | StudioStaff, StudioManager, LoyaltyMember |
| GET | `/class-series` | List series (filter by status) | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/class-series/{id}/enroll` | Enroll a member | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/class-series/{id}/start` | Start the series | StudioManager |
| POST | `/class-series/{id}/cancel` | Cancel a series; refund and reverse points | StudioManager |
| GET | `/class-series/{id}/enrollments` | List enrollments in a series | StudioStaff, StudioManager |
| GET | `/enrollments/{id}` | Fetch an enrollment | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/enrollments/{id}/mark-attended` | Mark an enrollment attended | StudioStaff, StudioManager |
| POST | `/enrollments/{id}/withdraw` | Withdraw before series starts; reverse points, reopen seat | StudioStaff, StudioManager, LoyaltyMember |
| POST | `/_clock/set_current_utc` | Set the server logical clock; run sweeps | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_FIRING_TEMP_MISMATCH` | 409 Conflict |
| `ERR_VISIT_NOT_OPEN` | 409 Conflict |
| `ERR_PIECES_NOT_READY` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_KILN_AT_CAPACITY` | 409 Conflict |
| `ERR_SERIES_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_ENROLLMENT_CLOSED` | 409 Conflict |
| `ERR_MEMBER_SUSPENDED` | 409 Conflict |
| `ERR_STALE_BATCH_VERSION` | 412 Precondition Failed |
| `ERR_BOOKING_DATE_PAST` | 422 Unprocessable Entity |
| `ERR_DEPOSIT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_POINTS` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |

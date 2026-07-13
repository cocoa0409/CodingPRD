# Event Ticketing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Event Ticketing API, a primary-market ticketing and box-office platform in the mold of large live-event marketplaces. The system is the authoritative record for the entire journey of a live event: a promoter announces a show and configures its pricing, the box office builds the seat map and manages inventory, buyers wait in an onsale queue, hold seats, and pay, and gate staff scan tickets at the door. Along the way the platform must reconcile three difficult realities at once — scarce seat inventory that many buyers compete for simultaneously, demand-sensitive pricing that shifts as a show sells through, and money that must flow correctly through fees, refunds, store credit, and an eventual payout to the promoter.

Because inventory is finite and contested, the platform is built around explicit holds, a first-in-first-out admission queue, and optimistic concurrency guards that reject writes made against a stale view of an event or an order. Because pricing is dynamic, the price a buyer ultimately pays is snapshotted and frozen at defined moments rather than recomputed on the fly. And because settlement to a promoter must be exact to the cent, every refund, credit, and fee is tracked as an integer number of cents and every rounding decision is pinned. The sections below define the global contracts every endpoint obeys (Section 2) and then walk the business workflows in narrative form (Section 3), before summarizing the HTTP surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that govern every endpoint. Individual business behaviors and the field-level details of each resource are developed in Section 3.

### 2.1. User and Role-Based Access Control

Every request must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing, or if `X-User-Role` is not one of the roles the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation — or a buyer attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Buyer`, `BoxOffice`, `Promoter`, and `GateScanner`.

- When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer` entity. Buyers own the purchase side of the platform: their queue tokens, holds, orders, tickets, transfers, and refund requests. Ownership checks on any resource that references a buyer compare the resource's foreign-key field to `X-User-ID`: a hold's or order's `buyer_id`, a ticket's `holder_buyer_id`, and a transfer's `from_buyer_id` must equal the acting buyer's `X-User-ID` for that buyer to mutate the resource. Accepting or declining a transfer instead compares the transfer's `to_buyer_id` to `X-User-ID`.
- When `X-User-Role` is `BoxOffice`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A box-office operator manages inventory, seat maps, queue admission, delivery and will-call, refunds, hold sweeps, and the logical clock; the server does not compare its `X-User-ID` to any entity's `id`.
- When `X-User-Role` is `Promoter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `promoter_id` on an `Event` when the promoter creates that event, but it is not an entity foreign key and is never resolved against a persisted record.
- When `X-User-Role` is `GateScanner`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. A gate scanner performs access control (ticket scanning) and gate lookups only; the server does not compare its `X-User-ID` to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no less than 1 and no greater than 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, ties (which are common because many resources are created at the same logical-clock instant) broken by ascending order of creation. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of matching items before pagination and `has_more` indicates whether items remain beyond the current page.

### 2.4. Common Resource Properties and Versioning

Every persisted resource in the system — buyers, events, price levels, seats, queue tokens, holds, orders, tickets, transfers, refund requests, and settlements — carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp expressed in ISO 8601 UTC with three fractional digits. The `id` and `created_at` are assigned once and never change.

All of the resources in this system additionally carry an `updated_at` timestamp and an integer `version`. The `updated_at` field is refreshed to the current logical clock on every mutation of the resource, including mutations that occur as a side effect of some other operation's cascade. The `version` starts at 1 when the resource is created and increases by exactly 1 on every mutation of that resource. Two entities have an important nuance in when their version advances, described where they are used: an `Event`'s `version` increases by 1 on each of its own status transitions and additionally increases by 1 each time a hold is created against it (this makes the event the concurrency parent for hold creation), and an `Order`'s `version` increases by 1 on payment and additionally increases by 1 each time a refund request is created against it (this makes the order the concurrency parent for refund creation).

### 2.5. The Logical Clock and Temporal Semantics

The platform runs on a logical clock rather than wall-clock time, so that time-dependent behavior — hold expiry, admission windows, event start times — is deterministic and test-drivable. On server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until it is explicitly set it holds that value and never falls back to real-world time. A box-office capability advances the clock to a supplied instant, passed as `to_iso8601`; every timestamp the server stamps (creation, updates, admission, expiry computations) is read from this logical clock.

Several temporal boundaries recur throughout the workflows and are defined once here for precision. A hold's expiry is **half-open**: a hold is considered expired once the clock has reached or passed its `expires_at`, i.e. the moment `expires_at` itself has lapsed counts as expired. Conversely, an order may be paid only while the clock is strictly before the hold's `expires_at`. An admission window lapses once the clock has passed the token's `purchase_deadline`; the window is still open when the clock equals `purchase_deadline`. An event's `event_datetime` must be strictly after the current clock at the moment the event is created, and a postponement's replacement datetime must likewise be strictly after the current clock. In both cases the `event_datetime` returned in responses is the exact string the client supplied, echoed verbatim rather than re-serialized into the three-fractional-digit ISO 8601 form used for server-stamped timestamps.

### 2.6. Monetary Values, Precision, and Rounding

All monetary amounts in this system are integer numbers of cents; there are no fractional-cent values in stored fields or in API responses. Wherever a calculation multiplies a cent amount by a rate or a multiplier and the result must be reduced to whole cents, the system rounds **half up** to the nearest cent. The percentage and multiplier inputs themselves (a price level's `service_fee_pct`, the dynamic multipliers, the platinum floor) are the only non-integer quantities and are used only inside these intermediate computations.

Two rounding-order rules are contractual because a naive implementation would drift by a cent. First, the per-ticket service fee is computed **per seat and then summed** — each seat's percentage fee is rounded to whole cents individually before the seats are added together, never summed and then rounded. Second, a seat's dynamic face value is rounded to whole cents *before* the min/max clamp described in Section 3 is applied. Both rules are spelled out with their formulas in the workflows that use them.

### 2.7. Optimistic Concurrency Control

Two write operations in this system are guarded by optimistic concurrency control (OCC), and only these two. Each guards against a client acting on a parent resource whose state has moved on since the client last read it.

The first guard protects hold creation. A request that creates an inventory hold against an event must carry `expected_event_version`, a non-optional field whose value is the `version` of the target `Event` as the client last observed it. If that value does not match the event's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because an event's version advances both on its own status transitions and on every hold creation, a stale `expected_event_version` is exactly the signal that another writer has repriced, rescheduled, or already taken inventory since the client's last read, so the client's picture of seat prices and availability can no longer be trusted.

The second guard protects refund-request creation. A request that creates a refund against an order must carry `expected_order_version`, a non-optional field whose value is the `version` of the target `Order` as the client last observed it. If it does not match the order's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because an order's version advances on payment and on every refund-request creation, a stale `expected_order_version` means another writer has already changed what is refundable, and the current request would otherwise overwrite a decision it never saw.

No other endpoint accepts or requires a version field. Operations that are not hold-creation or refund-creation perform no OCC check.

### 2.8. Seat Inventory Consistency and Cascading Side Effects

Seat inventory is the backbone invariant of the platform. Every `Seat` is in exactly one of the statuses `AVAILABLE`, `HELD`, or `SOLD`, and for any event the counts always satisfy: available seats plus held seats plus sold seats equals total capacity. The event exposes these as the computed fields `seats_available`, `seats_held`, `seats_sold`, and `total_capacity`, recomputed after any seat status change (hold creation, release, expiry, payment, refund, or voiding). The event's `pct_sold` is derived from them and drives dynamic pricing, as detailed in Section 3.

Because inventory and money are entangled, a single operation frequently mutates several resources at once. Whenever the workflows in Section 3 describe such a mutation, every affected resource is updated in full — its own status changes, its `updated_at` is refreshed to the clock, and its `version` increments by 1 — and the cascade continues to the resources it in turn touches. The most consequential cascades — event cancellation voiding tickets and freeing their seats, payment converting a hold and issuing tickets, and refund approval returning seats to inventory and crediting a buyer — are described in full at the workflows that trigger them. The governing rule for this section is simply that no cascade is partial: if a parent transition implies a child's transition, the child transition (and its own bump of `updated_at` and `version`) happens in the same operation.

### 2.9. Reference Resolution and Validation Ordering

Every request is validated in a fixed priority order, and the first failing check determines the error returned. The ordering is: (1) authentication of the `X-User-ID` / `X-User-Role` headers, failing with `ERR_UNAUTHENTICATED`; (2) authorization of the acting role and, for buyers, ownership of the target resource, failing with `ERR_UNAUTHORIZED`; (3) existence of every referenced identifier — path identifiers and body foreign keys alike — resolved left to right, failing with the entity-specific not-found error; (4) the optimistic-concurrency check on `expected_event_version` or `expected_order_version` where applicable, failing with `ERR_STALE_VERSION`; (5) that the target resource is in a state from which the requested transition is legal, failing with `ERR_INVALID_STATE`; (6) that the event is in a purchasable state for hold and order operations, failing with `ERR_EVENT_NOT_ON_SALE`; (7) access-control checks on tickets for scanning and transfer; (8) business-constraint checks such as presale validity, seat-map uniqueness, queue non-overlap, and non-empty seat selection; (9) temporal checks such as hold expiry and admission-window lapse; (10) seat-referential checks such as seat availability and hold overlap; (11) fiscal checks such as the per-hold seat cap and the refund balance ceiling; and (12) the settlement-readiness check.

Existence resolution deserves emphasis because payloads carry several foreign keys. Identifiers are checked in the left-to-right order they appear on the path and then in the body, and the first unresolved identifier decides the error — for example, when creating a seat the `event_id` in the path is resolved before the `price_level_id` in the body, and when creating a refund the `order_id` is resolved before any member of `ticket_ids`. Each entity has its own not-found error, all returning HTTP 404: an unresolved event yields `ERR_EVENT_NOT_FOUND`; an unresolved or cross-event `price_level_id` yields `ERR_PRICE_LEVEL_NOT_FOUND`; an unresolved or cross-event seat yields `ERR_SEAT_NOT_FOUND`; an unresolved `buyer_id` or `to_buyer_id` yields `ERR_BUYER_NOT_FOUND`; an unresolved queue token yields `ERR_QUEUE_TOKEN_NOT_FOUND`; an unresolved `hold_id` yields `ERR_HOLD_NOT_FOUND`; an unresolved `order_id` yields `ERR_ORDER_NOT_FOUND`; an unresolved ticket or a `ticket_ids` member that belongs to another order yields `ERR_TICKET_NOT_FOUND`; an unresolved transfer yields `ERR_TRANSFER_NOT_FOUND`; and an unresolved refund yields `ERR_REFUND_NOT_FOUND`. A `price_level_id` that exists but belongs to a different event, a `seat_id` that belongs to a different event, or a `ticket_ids` member that belongs to a different order are each treated as not-found for the respective entity.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Event: Promoters, Price Levels, and the Seat Map

A `Promoter` (or a `BoxOffice` operator acting on their behalf) creates an event, which is born in `DRAFT`. Creation captures the operator's `promoter_id` (supplied as a required field in the request body; when the actor is a `Promoter` it must equal their `X-User-ID`, else `ERR_UNAUTHORIZED`), a `name`, a `venue_name`, and the scheduled `event_datetime`, which must be strictly later than the current clock (otherwise `ERR_VALIDATION`). Two timing knobs are set here and reused throughout the event's life: `hold_ttl_minutes`, the number of minutes an inventory hold stays alive before it may be swept away (defaulting to 15 when omitted), and `purchase_window_minutes`, the number of minutes an admitted queue token grants its holder to complete a purchase (defaulting to 30). Presale is configured with an optional `presale_code` (null by default, which disables presale) and `presale_max_uses`, the maximum number of holds that may be admitted through that code (defaulting to 0). At creation the event's inventory counters are all zero and its `version` is 1.

Before an event can be announced, its pricing must exist. A promoter or box-office operator defines one or more price levels for the event, each supplying a `name` for the zone, a `base_face_value_cents` (which must be greater than zero), and the fee configuration: a percentage `service_fee_pct` such as 0.15, and an optional flat `service_fee_flat_cents` added after the percentage (defaulting to 0). A price level may be flagged `is_platinum` (default false), which imposes a demand floor on its seats, and may set `dynamic_pricing_enabled` (default true); when dynamic pricing is disabled the seats in that level always price at exactly their base face value regardless of how the show is selling — unless the level is also flagged `is_platinum`, in which case the platinum floor of 2.00 still applies (per Section 3.3) and the seats price at twice their base face value. Each price level references its event through `event_id`.

The seat map itself is built by the box office. Each seat is created under an event and references the price level it belongs to via `price_level_id`, which must belong to the same event, along with its physical coordinates `section`, `row`, and `seat_number`. The triple of `section`, `row`, and `seat_number` must be unique within an event; a repeat is rejected with `ERR_DUPLICATE_SEAT`. A new seat starts `AVAILABLE` and raises the event's `total_capacity` by one.

The event lifecycle is driven by a single status-transition capability available to the promoter and box office, which names a `target_status` (and, for a postponement, a `new_event_datetime`). The `status` field walks through `DRAFT`, `ANNOUNCED`, `PRESALE`, `ONSALE`, `POSTPONED`, `CANCELED`, and `COMPLETED`, and every legal transition increments the event's `version` by 1. Moving from `DRAFT` to `ANNOUNCED` requires that at least one price level already exists for the event. Announcing a presale — `ANNOUNCED` to `PRESALE` — requires that the event's `presale_code` is not null. Reaching `ONSALE`, which is legal from `ANNOUNCED`, from `PRESALE`, or from `POSTPONED`, requires that at least one seat exists. Any attempt to drive a transition that is not legal from the event's current status is rejected with `ERR_INVALID_STATE`.

An `ONSALE` event may be postponed. The postpone transition takes a `new_event_datetime` (required in the body, otherwise `ERR_VALIDATION`) that must be strictly after the current clock (otherwise `ERR_INVALID_STATE`); it sets the event's `event_datetime` to that value, and — because a postponed show should not carry live carts — every `ACTIVE` hold on the event moves to `EXPIRED` and each of that hold's seats returns from `HELD` to `AVAILABLE`. The `POSTPONED → ONSALE` leg is the reschedule step that puts the show back on sale, forming the cyclic loop between the two states.

### 3.2. Presale Codes, the Onsale Queue, and Admission

To manage the rush at onsale, buyers pass through a first-in-first-out queue before they may hold seats. A buyer joins an event's queue, supplying their `buyer_id`; the new `QueueToken` starts in `WAITING` and receives a `position` that is its 1-based rank among the currently `WAITING` tokens, ordered by `created_at` ascending. (Buyers themselves are registered by the box office with a `name` and an `email` — uniqueness of `email` is not enforced — starting with a `credit_balance_cents` of 0.)

A box-office operator admits a waiting token, which is legal only while the event is `ONSALE`. Admission moves the token from `WAITING` to `ADMITTED`, records `admitted_at` as the current clock, and computes `purchase_deadline` as `admitted_at` plus the event's `purchase_window_minutes`. Admission is guarded against giving one buyer two live windows on the same event: if the buyer already holds an `ADMITTED` token for this event whose `purchase_deadline` is at or after the current clock, the admit is rejected with `ERR_ALREADY_ADMITTED`. A token that is not in `WAITING` cannot be admitted (`ERR_INVALID_STATE`). An admitted token ultimately reaches its terminal `EXPIRED` state either when an order is placed within its window (the order consumes the token) or when the window simply lapses.

The relationship between queue admission and holding depends on the event's phase. When the event is `ONSALE`, a buyer may create a hold only if they hold an `ADMITTED` token for that event whose window is still open; a hold attempt during `ONSALE` without such a token is rejected with `ERR_NOT_ADMITTED`, and if the buyer had a token but its `purchase_deadline` has already passed (the clock is strictly beyond it), the attempt is rejected with `ERR_ADMISSION_WINDOW_EXPIRED`. When the event is instead in `PRESALE`, admission is not used; access is gated by the presale code instead, as described next.

Presale access is controlled by the code carried on the hold request. During `PRESALE`, a hold must supply the `presale_code` that matches the event's configured code, and the presale must not be exhausted. Exhaustion is measured by `presale_uses_count`, the number of holds carrying the event's presale code that are currently `ACTIVE` or `CONVERTED`; once that count reaches `presale_max_uses`, or if the supplied code is missing or wrong, the hold is rejected with `ERR_INVALID_PRESALE_CODE`. Outside of `PRESALE` the `presale_code` on a hold is left null.

### 3.3. Holding Inventory and Dynamic Pricing

A hold is a buyer's temporary claim on one or more seats. Creating a hold names the seats through a non-empty `seat_ids` array and the acting `buyer_id`, which must equal the buyer's `X-User-ID`, and it must carry the `expected_event_version` guard described in Section 2.7. A hold may cover at most two seats — the per-hold cap `MAX_SEATS_PER_HOLD` is 2 — and a request for more is rejected with `ERR_CAPACITY_EXCEEDED`. An empty `seat_ids` array is rejected with `ERR_EMPTY_SEAT_SELECTION`. The event must be in a purchasable phase: `ONSALE`, or `PRESALE` with a valid presale code; otherwise the attempt is rejected with `ERR_EVENT_NOT_ON_SALE`. Each requested seat must belong to the hold's event and be `AVAILABLE`, and no other `ACTIVE`, unexpired hold may already cover it; a seat that fails this is rejected with `ERR_SEAT_UNAVAILABLE`.

When a hold is created it starts `ACTIVE`, moves each of its seats from `AVAILABLE` to `HELD`, and freezes two values at that instant. Its `expires_at` is set to the creation clock plus the event's `hold_ttl_minutes` and never changes afterward. Its `face_subtotal_cents` is snapshotted as the sum of the `current_face_value_cents` of the held seats at that moment and is likewise frozen thereafter. Creating the hold also increments the parent event's `version` by 1, which is what makes concurrent hold creation observable through OCC.

A seat's `current_face_value_cents` is where dynamic pricing lives. The price begins from the seat's price level `base_face_value_cents` and a demand multiplier. If the price level has dynamic pricing disabled, the multiplier is exactly 1.00. Otherwise the multiplier is chosen by the event's `pct_sold`: below 50 percent sold the multiplier is 1.00; from 50 percent up to but not including 80 percent it is 1.25; at 80 percent or above it is 1.50. The 50-percent and 80-percent figures are the tier boundaries, each inclusive at its lower edge. If the seat's price level is platinum, the multiplier is then raised to whichever is larger, the tier multiplier or the platinum floor of 2.00 — so a platinum seat never prices below twice its base even in a cold sale. The raw price is the base face value multiplied by the resulting multiplier, rounded half up to whole cents. That raw price is finally clamped to lie between a floor equal to the base face value and a ceiling equal to three times the base face value: if the rounded price is below the base it is lifted to the base, and if it exceeds three times the base it is capped there.

Two readings of this price coexist. Read live off a seat, `current_face_value_cents` reflects the event's *current* `pct_sold` tier and moves as the show sells. But the moment a hold and later an order capture a price, that price is frozen: a hold's `face_subtotal_cents`, an order's `face_total_cents`, and a ticket's `face_value_cents` are all snapshotted at their creation against the then-current tier and do **not** re-price if `pct_sold` later crosses a tier boundary. A hold the buyer no longer wants can be released, moving it from `ACTIVE` to `RELEASED` and returning its seats from `HELD` to `AVAILABLE`; release is available to the owning buyer or the box office and is legal only while no paid order references the hold. The box office may also sweep an event's expired holds: any `ACTIVE` hold whose `expires_at` is at or before the current clock moves to `EXPIRED` and returns its seats to `AVAILABLE`.

### 3.4. Ordering, Payment, and Ticket Issuance

An order turns a hold into a purchase. A buyer creates an order from an `ACTIVE` hold by naming the `hold_id` and choosing a `delivery_method` of `MOBILE`, `PRINT`, or `WILL_CALL`. The order copies its `event_id` and `buyer_id` from the hold, starts in `PENDING`, and locks its money at creation. Its `face_total_cents` is the sum of the `current_face_value_cents` of the hold's seats, snapshotted now against the current tier and frozen as the final price. Its `service_fee_cents` is computed by the pinned per-seat rule: for each seat in the hold, take that seat's locked face value, multiply by the price level's `service_fee_pct`, round half up to whole cents, add the price level's `service_fee_flat_cents`, and only then sum these per-seat amounts across all seats. The order's `order_total_cents` is `face_total_cents` plus `service_fee_cents`. At creation the order's `paid_amount_cents` is 0 and its `refunded_amount_cents` is 0. Order creation is subject to the same purchasable-event gate (`ERR_EVENT_NOT_ON_SALE`) and, because it draws on a hold, to the hold not having expired: an order against a hold whose `expires_at` has lapsed is rejected with `ERR_HOLD_EXPIRED`.

Paying an order is the pivotal moment of the platform. Payment is legal only while the hold is still `ACTIVE` and not expired (the clock is strictly before the hold's `expires_at`, else `ERR_HOLD_EXPIRED`) and while the event is `ONSALE` or `PRESALE`. On success the order moves from `PENDING` to `PAID` and a chain of effects fires: the backing hold moves from `ACTIVE` to `CONVERTED` and each of its `HELD` seats becomes `SOLD`; one `Ticket` is issued per held seat; the order's `paid_amount_cents` is set to its `order_total_cents`; and the order's `version` increments by 1. Each issued ticket references its `order_id`, its `seat_id`, and its `holder_buyer_id` (initially the ordering buyer), and its `face_value_cents` is the seat's face locked at order creation. A ticket carries three independent status dimensions. Its validity `status` starts `VALID`. Its `delivery_status` starts `DELIVERED` when the order's `delivery_method` is `MOBILE`, and `PENDING` otherwise; the ticket's own `delivery_method` is copied from the order. Its access `scan_status` starts `UNSCANNED`. These three dimensions — `status` in {`VALID`, `REFUNDED`, `VOID`}, `delivery_status` in {`PENDING`, `DELIVERED`}, and `scan_status` in {`UNSCANNED`, `SCANNED`} — evolve independently of one another.

### 3.5. Fulfillment, Access Control at the Gate, and Transfers

Physical and will-call fulfillment is a box-office action. Delivering a ticket moves its `delivery_status` from `PENDING` to `DELIVERED` and leaves the validity and scan dimensions untouched; it is legal only when the ticket is `VALID` and its `delivery_status` is still `PENDING`. Mobile tickets arrive `DELIVERED` at issuance and need no such step.

At the venue gate a `GateScanner` scans tickets for entry. Scanning moves the ticket's `scan_status` from `UNSCANNED` to `SCANNED` and touches neither validity nor delivery. A scan is admitted only when the ticket is `VALID`, its `delivery_status` is `DELIVERED`, its `scan_status` is still `UNSCANNED`, and the event is `ONSALE` (the door is open during the on-sale phase). A scan of an undelivered ticket is rejected with `ERR_TICKET_NOT_DELIVERED`, and a scan of one already scanned with `ERR_TICKET_ALREADY_SCANNED`; a scan attempted against a ticket that is not `VALID`, or while the event is not `ONSALE`, is rejected with `ERR_INVALID_STATE`.

Buyers may pass tickets to one another by transfer, which covers both gifts and verified resale routing. Initiating a transfer names the `ticket_id`, the recipient `to_buyer_id`, and the `kind`, which is either `GIFT` or `RESALE`. For a resale, `list_price_cents` is required and must be greater than zero; for a gift, `list_price_cents` must be null. A malformed transfer — a resale without a positive `list_price_cents`, or a gift that nevertheless carries a `list_price_cents` — is rejected with `ERR_VALIDATION`. The initiating buyer must be the ticket's current holder, so the ticket's `holder_buyer_id` (and the transfer's `from_buyer_id`) must equal the acting `X-User-ID`. A ticket is transferable only while it is `VALID` and `UNSCANNED`: an attempt to transfer a `REFUNDED` or `VOID` ticket is rejected with `ERR_TICKET_NOT_TRANSFERABLE`, and an attempt to transfer one already `SCANNED` with `ERR_TICKET_ALREADY_SCANNED`. A new transfer starts `INITIATED`.

The recipient decides the transfer's fate. Only the buyer named as `to_buyer_id` may accept or decline it. Accepting moves the transfer from `INITIATED` to `ACCEPTED` and reassigns the ticket's `holder_buyer_id` to the `to_buyer_id`; acceptance additionally requires that the ticket is still `VALID` and `UNSCANNED` and that the event is not `CANCELED` or `COMPLETED`. Declining moves the transfer from `INITIATED` to `DECLINED` and changes nothing about the ticket. A buyer can review the transfers they sent or received, and the transfers attached to a particular ticket, through the read surfaces summarized in Section 4.

### 3.6. Refunds, Store Credit, Postponement, and Cancellation

Refunds run against paid orders and never return service fees — only face value comes back. A refund request is created against a `PAID` or `PARTIALLY_REFUNDED` order and must carry the `expected_order_version` OCC guard of Section 2.7. It names a `reason` — `CUSTOMER_REQUEST`, `POSTPONEMENT`, or `EVENT_CANCELED` — and a `refund_destination` of either `ORIGINAL` (back to the original payment) or `CREDIT` (to the buyer's store credit). It may name a subset of the order's currently-`VALID` tickets through `ticket_ids`; when `ticket_ids` is omitted, the request covers all of the order's currently-`VALID` tickets. The request's `amount_cents` is computed as the sum of the `face_value_cents` of the included tickets, and the request is created in `REQUESTED`. Creating the refund request increments the order's `version` by 1. At creation the requested amount may not exceed the order's remaining refundable face balance — that is, the order's `face_total_cents` minus its already-`refunded_amount_cents` — and a request that would exceed it is rejected with `ERR_REFUND_EXCEEDS_BALANCE`.

A box-office operator then approves or rejects the request. Rejection moves it from `REQUESTED` to `REJECTED` and makes no inventory or ledger change. Approval moves it from `REQUESTED` to `COMPLETED` and is permitted only when all of its included tickets are still `VALID` and the amount still fits within the order's remaining refundable balance (`face_total_cents` minus `refunded_amount_cents`), else `ERR_REFUND_EXCEEDS_BALANCE`. On approval, each included ticket moves from `VALID` to `REFUNDED` and its seat returns to `AVAILABLE`. The order's `refunded_amount_cents` is the sum of `amount_cents` over its `COMPLETED` refund requests; once that total reaches or exceeds the order's `face_total_cents` the order becomes `REFUNDED`, and otherwise it becomes `PARTIALLY_REFUNDED`. When the destination is `CREDIT`, the refund's `amount_cents` is added to the buyer's `credit_balance_cents`; that balance is exactly the sum of `amount_cents` over all `COMPLETED` refund requests, with destination `CREDIT`, belonging to that buyer's orders — a credit refund raises it by precisely the refund amount and nothing else ever does.

Two lifecycle events drive refunds and releases automatically. When an event is postponed, as covered in Section 3.1, live holds expire and their seats free up, but paid orders are untouched. When an event is **canceled** — legal from `DRAFT`, `ANNOUNCED`, `PRESALE`, `ONSALE`, or `POSTPONED` — a broad cascade fires. Every `PAID` or `PARTIALLY_REFUNDED` order moves to `REFUNDED`, with an automatic full refund created for the reason `EVENT_CANCELED` and destination `ORIGINAL`; every remaining `VALID` ticket of such an order moves to `VOID` and each voided ticket's seat returns to `AVAILABLE`. Every `PENDING` order moves to `CANCELED` and its backing hold moves to `RELEASED`. Any still-`ACTIVE` hold on the event moves to `RELEASED` and its seats return from `HELD` to `AVAILABLE`. The event's own `version` increments by 1 as part of the cancellation. (Cancellation is terminal, as is completion.)

### 3.7. Completion and Settlement to the Promoter

An `ONSALE` event reaches `COMPLETED` once the show has happened — that is, only when the current clock is at or after the event's `event_datetime`; an attempt before then is rejected with `ERR_INVALID_STATE`. Completion creates the event's `Settlement` in `PENDING`, referencing the event through `event_id`, with exactly one settlement per event.

The settlement accounts for the money four ways. Its `gross_face_cents` is the gross variant: the sum of `face_value_cents` over **all** tickets ever issued for the event, regardless of whether they ended up `VALID`, `REFUNDED`, or `VOID`. Its `net_to_promoter_cents` is the net variant and the actual payout basis: the sum of `face_value_cents` over only the tickets whose `status` is `VALID`, so refunded and voided face is excluded. Its `service_fees_cents` is the sum of `service_fee_cents` over the event's orders whose status is `PAID`, `PARTIALLY_REFUNDED`, or `REFUNDED`; these fees are retained by the platform and are not paid to the promoter. Its `refunds_cents` is the sum of `amount_cents` over the `COMPLETED` refund requests of the event's orders.

Finalizing the settlement is available to the box office or the promoter and requires that the event is `COMPLETED`; finalizing before completion is rejected with `ERR_SETTLEMENT_NOT_READY`. Finalization moves the settlement from `PENDING` to `FINALIZED` and freezes the four figures — `net_to_promoter_cents`, `gross_face_cents`, `refunds_cents`, and `service_fees_cents` — as the settled record of the event; a finalize attempt on a settlement already `FINALIZED` is rejected with `ERR_INVALID_STATE`. Reading the settlement (`GET /events/{event_id}/settlement`) returns an array (`response_type` "array") holding the event's single settlement, or an empty array before the event has been completed and its settlement created; while the settlement is `PENDING` the four figures are recomputed live on each read, and only finalization freezes them.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform a read return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers described in Section 2.1, and reconstructing the request body, response shape, and side effects of any mutating endpoint requires reading the corresponding workflow in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | BoxOffice |
| POST | `/buyers` | Register a buyer | BoxOffice |
| GET | `/buyers/{buyer_id}` | Get a buyer (incl. computed credit balance) | Buyer, BoxOffice |
| GET | `/buyers/{buyer_id}/queue-tokens` | List a buyer's queue tokens | Buyer, BoxOffice |
| GET | `/buyers/{buyer_id}/transfers` | List transfers where the buyer is sender or recipient | Buyer, BoxOffice |
| POST | `/events` | Create an event in DRAFT | Promoter, BoxOffice |
| GET | `/events/{event_id}` | Get an event (incl. computed inventory and pct_sold) | Buyer, BoxOffice, Promoter, GateScanner |
| POST | `/events/{event_id}/status` | Drive the event lifecycle | Promoter, BoxOffice |
| POST | `/events/{event_id}/price-levels` | Create a price level for the event | Promoter, BoxOffice |
| GET | `/events/{event_id}/price-levels` | List price levels of an event | Buyer, BoxOffice, Promoter |
| POST | `/events/{event_id}/seats` | Create a seat in the event's seat map | BoxOffice |
| POST | `/events/{event_id}/queue-tokens` | Join the onsale queue | Buyer |
| GET | `/events/{event_id}/queue-tokens` | List an event's queue tokens | Buyer, BoxOffice |
| POST | `/events/{event_id}/holds` | Create an inventory hold (OCC on event version) | Buyer |
| POST | `/events/{event_id}/sweep-holds` | Sweep expired holds and release their seats | BoxOffice |
| POST | `/events/{event_id}/settlement/finalize` | Finalize the event's settlement | BoxOffice, Promoter |
| GET | `/events/{event_id}/settlement` | Read the event's settlement | BoxOffice, Promoter |
| GET | `/seats/{seat_id}` | Get a seat (incl. computed current face value) | Buyer, BoxOffice, Promoter |
| GET | `/seats` | List seats filtered by event, price level, or status | Buyer, BoxOffice, Promoter |
| POST | `/queue-tokens/{token_id}/admit` | Admit a waiting token and open its purchase window | BoxOffice |
| GET | `/holds/{hold_id}` | Get a hold | Buyer, BoxOffice |
| GET | `/holds` | List holds filtered by event or buyer | Buyer, BoxOffice |
| POST | `/holds/{hold_id}/release` | Release an active hold and free its seats | Buyer, BoxOffice |
| POST | `/orders` | Create a pending order from an active hold | Buyer |
| GET | `/orders/{order_id}` | Get an order (incl. computed refunded amount) | Buyer, BoxOffice |
| GET | `/orders` | List orders filtered by event, buyer, or hold | Buyer, BoxOffice |
| POST | `/orders/{order_id}/pay` | Pay a pending order; issue tickets, mark seats sold | Buyer |
| POST | `/orders/{order_id}/refund-requests` | Create a refund request (OCC on order version) | Buyer, BoxOffice |
| GET | `/orders/{order_id}/refund-requests` | List an order's refund requests | Buyer, BoxOffice |
| POST | `/refund-requests/{refund_id}/approve` | Approve (complete) a refund request | BoxOffice |
| POST | `/refund-requests/{refund_id}/reject` | Reject a refund request | BoxOffice |
| GET | `/tickets/{ticket_id}` | Get a ticket | Buyer, BoxOffice, GateScanner |
| GET | `/tickets` | List tickets filtered by order, seat, or holder | Buyer, BoxOffice, GateScanner |
| GET | `/tickets/{ticket_id}/transfers` | List transfers for a ticket | Buyer, BoxOffice |
| POST | `/tickets/{ticket_id}/deliver` | Mark a print/will-call ticket delivered | BoxOffice |
| POST | `/tickets/{ticket_id}/scan` | Scan a ticket at the gate | GateScanner |
| POST | `/transfers` | Initiate a ticket transfer (gift or resale) | Buyer |
| POST | `/transfers/{transfer_id}/accept` | Accept a transfer; reassign the ticket holder | Buyer |
| POST | `/transfers/{transfer_id}/decline` | Decline a transfer | Buyer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_EVENT_NOT_FOUND` | 404 |
| `ERR_PRICE_LEVEL_NOT_FOUND` | 404 |
| `ERR_SEAT_NOT_FOUND` | 404 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_QUEUE_TOKEN_NOT_FOUND` | 404 |
| `ERR_HOLD_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_TRANSFER_NOT_FOUND` | 404 |
| `ERR_REFUND_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVENT_NOT_ON_SALE` | 409 |
| `ERR_NOT_ADMITTED` | 409 |
| `ERR_ALREADY_ADMITTED` | 409 |
| `ERR_ADMISSION_WINDOW_EXPIRED` | 409 |
| `ERR_INVALID_PRESALE_CODE` | 409 |
| `ERR_EMPTY_SEAT_SELECTION` | 422 |
| `ERR_SEAT_UNAVAILABLE` | 409 |
| `ERR_DUPLICATE_SEAT` | 409 |
| `ERR_HOLD_EXPIRED` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 422 |
| `ERR_TICKET_NOT_DELIVERED` | 409 |
| `ERR_TICKET_ALREADY_SCANNED` | 409 |
| `ERR_TICKET_NOT_TRANSFERABLE` | 409 |
| `ERR_REFUND_EXCEEDS_BALANCE` | 422 |
| `ERR_SETTLEMENT_NOT_READY` | 409 |

# Ticket Resale Marketplace API — Product Requirements Document

## 1. Introduction

The Ticket Resale Marketplace is a secondary-market platform on which independent sellers list tickets they already hold and buyers purchase them, with the platform standing in the middle as guarantor of both the money and the credential. The product has to reconcile several pressures at once: sellers want their tickets sold at the best price the market will bear, buyers want a guarantee that the barcode they receive is genuine and that they will get into the venue, and the platform must protect itself against duplicate-barcode fraud, price gouging, and chargebacks while still settling honest sellers quickly.

This API governs the full lifecycle of that marketplace. It models physical inventory (venues, sections, and individual seats), the commercial overlay (listings with fixed or demand-responsive pricing), the transaction (a reservation that holds seats, a charge that commits them, and a payout that escrows and later releases the seller's proceeds), and the post-sale protections (mobile or barcode credential transfer with last-minute compression, a buyer guarantee program that can replace or refund a bad order, and an event-cancellation flow that converts paid orders into wallet credit). Money moves in integer cents throughout; seat inventory is reserved, committed, and released through a pool whose counts must always reconcile with the underlying seat records. Because reservations, charges, clawbacks, and cancellations can race against one another, the system layers optimistic concurrency control over its two most contended resources and offers a simulated clock so that time-gated rules — reservation expiry, transfer deadlines, last-minute windows — can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint of the API. All resources are peer resources mounted at the root; they are joined to one another through foreign-key references carried in request bodies and query strings rather than through nested URL paths.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present but the role is not permitted to perform the requested operation — or an ownership-scoped role is acting on a resource it does not own — the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `PlatformAdmin`, `Seller`, `Buyer`, and `TrustSafety`.

A `Seller` is an entity-backed role: when `X-User-Role` is `Seller`, the `X-User-ID` value is the `id` of the acting `Seller` record. Ownership checks on any resource that references a seller — its listings, the seats under those listings, the transfers a seller initiates, and the payouts derived from its sales — compare the resource's seller foreign key (directly via `seller_id`, or transitively through the listing that owns the seat or the order behind the transfer or payout) to `X-User-ID`.

A `Buyer` is likewise entity-backed: when `X-User-Role` is `Buyer`, the `X-User-ID` value is the `id` of the acting `Buyer` record. Ownership checks on a buyer's orders, guarantee claims, and event credits compare the resource's `buyer_id` to `X-User-ID`.

`PlatformAdmin` and `TrustSafety` are opaque operator roles: when `X-User-Role` is either of these, `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; these roles are not ownership-scoped and act across all sellers and buyers within the operations their role permits.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless an endpoint explicitly states otherwise, list responses are sorted by `created_at` in ascending order. For listings priced in `DYNAMIC` mode, ordering still follows `created_at`; the dynamic price is a read-time projection and never affects list order.

Every list response carries these fields in the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id`, which is a UUID with no type prefix and is used for identity only — it is never derived from any input. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded when the resource is first created. All thirteen resource types in this system (Venue, Section, Event, Seller, Buyer, Listing, Seat, Order, Transfer, Payout, GuaranteeClaim, EventCredit, and FraudFlag) additionally carry `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation — and `version`, an integer that begins at 1 and increments by exactly 1 on every mutation of that resource.

The `version` increment applies to direct mutations and to mutations applied as a cascade side effect. When the system recomputes a derived field on a resource — for example refreshing a seller's `escrow_balance_cents` after a payout changes state, or recomputing a listing's `available_seat_count` after a seat is held — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the resource that carries the derived field. The `created_at` timestamp on a `Seat` doubles as the FIFO allocation key within its listing: when seats are reserved, the seats with the earliest `created_at` are taken first.

### 2.5. Seat Pool Reconciliation and Derived Counts

A `Listing` is a seat pool, and several of its fields are derived counts that must always reconcile with the underlying `Seat` records rather than being set directly. `total_seat_count` is the number of seats under the listing whose `status` is not `VOID`. `available_seat_count` is the number of seats under the listing whose `status` is `AVAILABLE`. `held_seat_count` is the number whose `status` is `HELD`. These are recomputed on every seat status change and on every reservation, charge, or release.

The pool obeys a standing invariant: for any listing, the count of `AVAILABLE` seats plus the count of `HELD` seats plus the count of `SOLD` seats plus the count of `TRANSFERRED` seats equals `total_seat_count`. A listing's `status` field tracks pool occupancy: while `available_seat_count` is greater than zero the listing is `ACTIVE`, and when `available_seat_count` reaches zero it becomes `SOLD_OUT`. A `Section` likewise exposes a derived `capacity` equal to its `row_count` multiplied by its `seats_per_row`, and a `Venue` exposes a derived `total_section_count` equal to the number of sections under it. An `Event` exposes a derived `active_listing_count` equal to the number of listings on that event whose `status` is `ACTIVE` or `SOLD_OUT`.

A seller's ledger fields are also derived and never directly set. `escrow_balance_cents` is the sum of `net_payout_cents` across that seller's payouts whose `status` is `ESCROWED`, and it never goes negative. `paid_out_balance_cents` is the sum of `net_payout_cents` across that seller's payouts whose `status` is `PAID`. `open_fraud_flag_count` is the number of fraud flags raised against that seller's listings and seats whose `status` is `OPEN` or `UNDER_REVIEW`. A buyer's `wallet_credit_cents` is the sum of `amount_cents` across that buyer's event credits whose `status` is `ISSUED`, and it never goes negative; `lifetime_orders_count` is the number of that buyer's orders whose `payment_status` reached `CHARGED` at least once.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integers in cents. Wherever a calculation specifies a fractional intermediate — a fee rate applied to a base, a demand multiplier, a goodwill bonus — the result is truncated toward zero to whole cents (floor truncation) at the point the specification names, never rounded up and never carried as a fraction into a stored field. Counts (seat counts, section counts, order counts, fraud-flag counts, negotiation rounds, attempt numbers) are plain integers. Multipliers and fee rates that are themselves inputs or configuration (such as `price_cap_multiplier` and `seller_fee_rate`) preserve their input precision and are not floored.

### 2.7. Nested Reference Validation Order

Although resources are addressed by flat paths, most operations reference other resources through path identifiers and body foreign keys. The system validates these references left to right, in dependency order: an event before a listing on it, a listing before a seat or order against it, an order before a transfer or payout or claim on it. The first identifier that fails to resolve produces that resource's specific not-found error — `ERR_EVENT_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_SECTION_NOT_FOUND`, `ERR_VENUE_NOT_FOUND`, `ERR_SELLER_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_SEAT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_CREDIT_NOT_FOUND`, or `ERR_FLAG_NOT_FOUND` — before any business rule is evaluated. Once all referenced resources resolve, cross-entity consistency is checked: a referenced section and the listing's section must agree, a polymorphic fraud subject id must match its declared `subject_type`, a guarantee replacement listing must sit on the same event as the original order, and an order's listing must match the listing named in the operation. Any such inconsistency is rejected with `ERR_REFERENTIAL_MISMATCH`.

### 2.8. Request Processing and Validation Order

For every state-changing request, validations run in a fixed priority order so that the same failing request always produces the same error regardless of how many things are wrong with it.

First, the request body is checked for well-formedness: required fields present, types and enum values valid, and numeric fields within their allowed ranges (for example `quantity` at least 1 and `face_value_cents` greater than zero). A malformed body is rejected with `ERR_INVALID_REQUEST` before any authentication or business logic runs. Next come the two authentication checks in order: header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then role permission and ownership (`ERR_FORBIDDEN_ROLE`). Third, all referenced foreign keys are resolved left to right, yielding the relevant not-found error. Fourth, cross-entity referential consistency is checked (`ERR_REFERENTIAL_MISMATCH`). Fifth, the target resource and any cross-entity dependency must be in a state that permits the transition; state failures surface as `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_EVENT_NOT_SELLING`, `ERR_LISTING_FROZEN`, `ERR_DELIVERY_BEFORE_PAYMENT`, or `ERR_PAYOUT_NOT_RELEASABLE` as appropriate. Sixth, fraud and seller-standing safety guards apply (`ERR_LISTING_FROZEN`, `ERR_SELLER_RESTRICTED`). Seventh, temporal deadlines are enforced (`ERR_RESERVATION_EXPIRED`, `ERR_TRANSFER_DEADLINE_PASSED`). Eighth, inventory and uniqueness constraints apply (`ERR_SEAT_NOT_ADDABLE`, `ERR_SPLIT_RULE_VIOLATION`, `ERR_DUPLICATE_BARCODE`, `ERR_INSUFFICIENT_SEATS`, `ERR_OPEN_CLAIM_EXISTS`, `ERR_IDEMPOTENCY_CONFLICT`). Ninth, fiscal constraints apply (`ERR_INSUFFICIENT_WALLET_CREDIT`, `ERR_PRICE_CAP_EXCEEDED`, `ERR_DYNAMIC_FLOOR_INVALID`). Last of all, optimistic-concurrency version checks apply (`ERR_STALE_LISTING_VERSION`, `ERR_STALE_PAYOUT_VERSION`). Because the version check is evaluated last, a stale-version request that is also, say, out of state will surface the state error first.

### 2.9. Optimistic Concurrency Control

Two operations in this system are guarded by optimistic concurrency control, each anchored to the `version` of a parent resource that other writers legitimately advance.

Creating an order (the reservation that holds seats) is anchored to the target `Listing`. The reservation request must carry `expected_listing_version`, which is the client's last observed `version` of that listing. Every reservation, charge, and release legitimately bumps `Listing.version`, because each one holds or returns seats from the shared pool. If the listing's current `version` no longer equals the `expected_listing_version` the client supplied — meaning another writer advanced the listing since the client last read it — the reservation is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412). This prevents a client from reserving against an inventory view it never actually observed. The same `expected_listing_version` field is required when accepting a guarantee replacement offer, where the replacement order is minted against the offered listing.

Paying a payout is anchored to the `Payout`. The pay request must carry `expected_payout_version`, the client's last observed `version` of that payout. Clawback and release transitions driven by guarantee and cancellation cascades legitimately advance `Payout.version`; if the payout's current `version` no longer matches the supplied `expected_payout_version`, the pay request is rejected with `ERR_STALE_PAYOUT_VERSION` (HTTP 412), preventing a client from paying out a payout whose state it has not observed.

No other endpoint takes a version field. Operations not named here do not perform a version check.

### 2.10. The Simulated Clock and Deterministic Sweeps

Because reservation expiry, transfer deadlines, last-minute windows, and credit validity all depend on the passage of time, the system runs on a controllable logical clock rather than wall-clock time. An admin-only capability sets the clock to an absolute UTC instant, accepting `to_iso8601`; a second admin-only capability advances the clock forward by a supplied number of minutes, accepting `by_minutes`. Both return the resulting current UTC instant.

Advancing or setting the clock fires due system sweeps deterministically: any reservation whose `reservation_expires_at` has passed is auto-refunded (its held seats return to the pool); any transfer in `SENT` whose `deadline_at` has passed transitions to `EXPIRED` and fails delivery; any event credit whose validity window has elapsed transitions from `ISSUED` to `EXPIRED`; and an event that has reached its last-minute threshold may cross into the last-minute window. These sweeps are part of the clock operation's contract, not separate requests.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Venues, Sections, and Events

The catalog is owned entirely by the platform operator. A `PlatformAdmin` creates a `Venue` with a `name` and a `timezone` (an IANA timezone name used only for display); the venue's `total_section_count` seeds at zero and grows as sections are added. Sections are then created against the venue by supplying the parent `venue_id`, a `name` such as a floor label, a `price_zone` of `PREMIUM`, `STANDARD`, or `VALUE`, the original box-office `face_value_cents` per seat (which must be greater than zero and serves as the ceiling reference for price-cap checks), and the geometry `row_count` and `seats_per_row` (each at least 1). On creation the section's `capacity` is computed as `row_count` times `seats_per_row`, and the owning venue's `total_section_count` is recomputed.

Events are created against a venue with the parent `venue_id`, a `title`, and a `doors_open_at` instant marking the start of the admission window. Two tuning inputs may be supplied at creation or left to default: `price_cap_multiplier`, the maximum listing price expressed as a multiple of a section's `face_value_cents` (at least 1.0, defaulting to 3.0), and `last_minute_cutoff_minutes`, the number of minutes before `doors_open_at` at which last-minute delivery rules engage (at least 0, defaulting to 180). A new event begins in `SCHEDULED` status.

The event drives the whole marketplace's selling window through its `status`. Opening sales moves a `SCHEDULED` event to `ON_SALE`, the precondition being that it is currently `SCHEDULED`; this is the moment at which listings on the event may themselves be activated. The same open-sales capability also returns a `POSTPONED` event to `ON_SALE`, the precondition being that it is currently `POSTPONED`. Entering the last-minute window advances an `ON_SALE` event to `LAST_MINUTE`; the preconditions are that the event is `ON_SALE` and that the current clock has reached `doors_open_at` minus `last_minute_cutoff_minutes`. From that point, new transfers on this event's orders are computed as last-minute and use the compressed deadline rule described in §3.6.

Completing an event moves it from `ON_SALE` or `LAST_MINUTE` to `COMPLETED`; the preconditions are that the event is `ON_SALE` or `LAST_MINUTE` and that the current clock has reached `doors_open_at`. Completion delists every listing on the event that is `ACTIVE`, `SOLD_OUT`, or `DRAFT`, moving each to `DELISTED`, and — the second hop of this cascade — moves every `ESCROWED` payout on the event's orders to `RELEASABLE`, since the event has happened and honest sellers can now be paid.

Postponing an event moves it from `SCHEDULED` or `ON_SALE` to `POSTPONED`, the precondition being that it is in one of those two states; listings remain in place, and buyers holding `CHARGED` orders may file an event-issue guarantee claim. Cancelling an event is the heaviest operation in the system and is described in §3.9. Both `COMPLETED` and `CANCELLED` are terminal for an event. Any attempt to drive the event status from a state the transition does not permit is rejected with `ERR_INVALID_STATE`; an operation that requires a selling event when the event is not `ON_SALE` or `LAST_MINUTE` is rejected with `ERR_EVENT_NOT_SELLING`.

### 3.2. Sellers, Buyers, and the Trust Tier

Sellers and buyers are the human counterparties. A seller is registered with a `display_name` and an opaque `payout_account_ref` that names the external destination for proceeds; a new seller starts in trust tier `NEW` with all balances at zero. A buyer is registered with a `display_name` and begins with `wallet_credit_cents` and `lifetime_orders_count` at zero. A seller's `trust_tier` is one of `NEW`, `VERIFIED`, `TRUSTED`, or `RESTRICTED`; it is set through a trust-tier adjustment available to platform and trust-safety operators, and it gates both the seller's commission rate (§3.5) and the seller's ability to sell at all. A seller in tier `RESTRICTED` is barred from activating listings — an activation attempt by a restricted seller is rejected with `ERR_SELLER_RESTRICTED`.

### 3.3. Listing Tickets: Drafting, Seats, Activation, and Pricing

A `Seller` creates a `Listing` in `DRAFT` by supplying the `event_id` the tickets are for, their own `seller_id`, the `section_id` the seats belong to, a `delivery_method` of `MOBILE_TRANSFER` or `BARCODE_PDF`, an `ask_price_cents` per seat (greater than zero), a `pricing_mode` of `FIXED` or `DYNAMIC`, and a `split_rule` of `ANY`, `PAIRS`, or `WHOLE` (defaulting to `ANY`). For a `DYNAMIC` listing the seller also supplies `dynamic_floor_cents`, the per-seat floor below which the demand-responsive price may never drop; that floor must be at most the `ask_price_cents`, and a `DYNAMIC` listing missing its floor, or one whose `dynamic_floor_cents` exceeds `ask_price_cents`, is rejected with `ERR_DYNAMIC_FLOOR_INVALID`. At creation the system validates the price against the cap: neither the `ask_price_cents` nor, for dynamic listings, the floor may exceed the section's `face_value_cents` multiplied by the event's `price_cap_multiplier`, and a violation is rejected with `ERR_PRICE_CAP_EXCEEDED`. The listing's seller foreign key must belong to the acting seller, and the named section must be consistent with the listing per §2.7.

Seats are added to a listing one at a time, and only while the listing is still `DRAFT` — adding a seat to a listing in any other status is rejected with `ERR_SEAT_NOT_ADDABLE`. A seat is created against its parent `listing_id` with a `row_label`, a `seat_number` (at least 1), and a `barcode_token`. The `section_id` on the seat is copied from the parent listing rather than supplied. The `barcode_token` must be unique across all live (non-`VOID`) seats in the system; reusing a token still held by a non-`VOID` seat is rejected with `ERR_DUPLICATE_BARCODE`. A new seat enters in `AVAILABLE` status, and the listing's seat counts reconcile per §2.5. While a seat is held or sold to an order, its `order_id` points at that order; a seat invalidated by fraud or a cascade becomes `VOID`.

Activation moves a `DRAFT` listing to `ACTIVE`. The preconditions are that the listing is `DRAFT`, that the event is currently `ON_SALE` or `LAST_MINUTE` (a non-selling event yields `ERR_EVENT_NOT_SELLING`), that the listing has at least one seat (its `total_seat_count` is 1 or more), and that the seller's `trust_tier` is not `RESTRICTED`. On activation the listing's `effective_price_cents` is recomputed. A seller may also delist a listing, moving it from `DRAFT` or `ACTIVE` to the terminal `DELISTED` state; manual delisting is permitted only from `DRAFT` or `ACTIVE`, and on delist any remaining `AVAILABLE` seats are voided. The system itself may delist a listing from any non-terminal state as part of the event-cancel cascade.

The `effective_price_cents` is the per-seat amount a buyer pays now, and it is computed as follows. Let the section's `face_value_cents` be the face value and let the price cap be the floor (truncation toward zero) of that face value multiplied by the event's `price_cap_multiplier`. For a `FIXED` listing, the raw price is simply the `ask_price_cents`. For a `DYNAMIC` listing, the raw price reflects scarcity: compute the sold ratio as `total_seat_count` minus `available_seat_count`, divided by `total_seat_count`, a value between 0 and 1; form a demand multiplier of 1.0 plus 0.50 times that sold ratio, so the multiplier ranges from 1.00 at an empty listing up to 1.50 at a fully taken one; multiply the `ask_price_cents` by that demand multiplier and take the floor; then take whichever is larger, that floored figure or the `dynamic_floor_cents`. In both modes the price cap is applied last: the `effective_price_cents` is the smaller of the raw price and the cap. The evaluation order is fixed — scarcity first, then the floor, then the cap clamp. For a `DYNAMIC` listing the `effective_price_cents` is refreshed whenever the listing is read, since the sold ratio drifts as seats move.

### 3.4. Reserving and Charging: The Buyer's Purchase

A `Buyer` purchases by first reserving seats. A reservation is created by supplying the `listing_id`, the buyer's own `buyer_id`, the desired `quantity` (at least 1), and the `expected_listing_version` the buyer last observed (the OCC anchor of §2.9). The buyer may optionally supply `applied_credit_cents` — wallet credit to apply, at least 0 and at most the buyer's `wallet_credit_cents`, defaulting to 0 — and an `idempotency_key`. A reservation that is a guarantee replacement carries `replacement_of_order_id` naming the order it replaces. Reservation is blocked unless the listing is `ACTIVE` or `SOLD_OUT` and not frozen; a frozen listing yields `ERR_LISTING_FROZEN`. The requested `quantity` may not exceed the listing's `available_seat_count`, or the reservation is rejected with `ERR_INSUFFICIENT_SEATS`. The `quantity` must also satisfy the listing's `split_rule`: a `PAIRS` listing accepts only even quantities and a `WHOLE` listing accepts only a quantity equal to the listing's entire available pool, while an `ANY` listing accepts any quantity; a violation is rejected with `ERR_SPLIT_RULE_VIOLATION`. If the buyer elects more credit than their wallet holds, the reservation is rejected with `ERR_INSUFFICIENT_WALLET_CREDIT`. Reusing an `idempotency_key` with different request parameters is rejected with `ERR_IDEMPOTENCY_CONFLICT`.

When the reservation succeeds, the system takes `quantity` seats from the pool in FIFO order by their `created_at` (earliest first), moving each from `AVAILABLE` to `HELD` and stamping each held seat's `order_id`; the listing's `available_seat_count` drops accordingly and `Listing.version` increments. If `available_seat_count` reaches zero the listing transitions `ACTIVE → SOLD_OUT`. The order's `locked_unit_price_cents` is captured from the listing's `effective_price_cents` at this moment, freezing the per-seat price. A `reservation_expires_at` instant is set, after which an uncharged reservation auto-expires. The order's provisional charge — `estimated_total_cents` and `buyer_fee_cents` — is computed by the estimate variant of the buyer-charge calculation: the base is `quantity` times `locked_unit_price_cents`; the `buyer_fee_cents` is the floor of that base times the buyer fee rate of 0.12; the gross is the base plus the `buyer_fee_cents`; and the applied credit is the smallest of the elected `applied_credit_cents`, that gross, and the buyer's `wallet_credit_cents` as of reservation time, with the estimated total being the gross minus that applied credit. At reservation the credit is only held against the wallet, not yet redeemed, so the estimate is provisional. A fresh order begins with `payment_status` `PENDING`, `delivery_status` `AWAITING`, and a `lifecycle_state` of `OPEN`.

Charging commits the purchase, moving `payment_status` from `PENDING` to `CHARGED`. The preconditions are that the order is `PENDING`, that the order's `HELD` seats still belong to it and the listing is `ACTIVE` or `SOLD_OUT` (not `DELISTED` or `FROZEN`), that the current clock is before `reservation_expires_at`, and that any `applied_credit_cents` is still within the buyer's `wallet_credit_cents`. A charge attempted after `reservation_expires_at` is rejected with `ERR_RESERVATION_EXPIRED`. On charge, the final variant of the buyer-charge calculation runs: the `final_total_cents` and the actual `buyer_fee_cents` are recomputed with exactly the same formula as the estimate, except that the applied credit is recomputed against the buyer's `wallet_credit_cents` as of charge time. If the wallet shrank between reservation and charge, the final total can exceed the estimate; the amount actually charged is `final_total_cents`, not `estimated_total_cents`. The applied event credits are then consumed FIFO by their `created_at` ascending, moving from `ISSUED` to `REDEEMED`, and the buyer's `wallet_credit_cents` is recomputed. The order's `HELD` seats become `SOLD`; a `Payout` is created in `ESCROWED` status (its commission computed per §3.5) and the seller's `escrow_balance_cents` is recomputed; the buyer's `lifetime_orders_count` is recomputed; and both `Listing.version` and `Order.version` increment.

A buyer may cancel an unpaid reservation, moving `payment_status` from `PENDING` to `REFUNDED`; the same transition also occurs automatically when the clock sweep finds the reservation past its `reservation_expires_at`. Either way the order's `HELD` seats return to `AVAILABLE`, `available_seat_count` is restored, `Listing.version` increments, a listing that had gone `SOLD_OUT` returns to `ACTIVE`, and any applied-but-not-yet-redeemed credit hold is released. `REFUNDED` and `CREDITED` are terminal payment states.

The order's `lifecycle_state` is a read-only rollup of its two payment and delivery axes, recomputed on any change to either axis and evaluated in a fixed order: if `payment_status` is `REFUNDED` or `CREDITED`, the rollup is `UNWOUND`; otherwise, if `payment_status` is `CHARGED` and `delivery_status` is `DELIVERED` or `REPLACED`, the rollup is `SETTLED`; in every other case the rollup is `OPEN`.

### 3.5. Seller Proceeds: Escrow, Commission, and Release

Each charged order mints exactly one `Payout`, born directly in `ESCROWED` status, whose `seller_id` is copied from the listing's seller and whose `order_id` names the order. Its `gross_sale_cents` is the seller-side gross — the order's `quantity` times the order's `locked_unit_price_cents`, excluding the buyer fee. Its `seller_fee_rate` is selected by the seller's `trust_tier` at charge time: 0.15 for `NEW`, 0.12 for `VERIFIED`, 0.10 for `TRUSTED`, and 0.20 for `RESTRICTED`. The `seller_fee_cents` is the floor of the `gross_sale_cents` times that `seller_fee_rate`. The `net_payout_cents` is the `gross_sale_cents` minus the `seller_fee_cents` minus any `clawback_cents`, and it never drops below zero. A freshly created payout has `clawback_cents` of 0.

A payout moves from `ESCROWED` to `RELEASABLE` either when an admin confirms the delivery window on the order or as the second hop of the event-complete cascade. Confirming the delivery window requires that the payout is `ESCROWED` and that the order's `delivery_status` is `DELIVERED` — a payout cannot be released until the buyer has actually received the seats. A `RELEASABLE` payout is then paid out, moving to the terminal `PAID` status. Paying requires that the payout is `RELEASABLE` (otherwise `ERR_PAYOUT_NOT_RELEASABLE`) and that the supplied `expected_payout_version` matches the payout's current `version` (otherwise `ERR_STALE_PAYOUT_VERSION` per §2.9); on payment the seller's `escrow_balance_cents` is decremented, the `paid_out_balance_cents` is incremented, and `Payout.version` increments. `PAID`, `CLAWED_BACK`, and `CANCELLED` are terminal payout states.

Two cascades reverse a payout. When a guarantee claim resolves as a refund or as the third hop of the event-cancel cascade, an `ESCROWED` or `RELEASABLE` payout is clawed back: its `clawback_cents` is set to the full `net_payout_cents` at that moment, its `net_payout_cents` is then driven to 0, and the seller's `escrow_balance_cents` is recomputed. This compensation is exact: a forward charge that added some amount to escrow, paired with a clawback that removes precisely that net, leaves `escrow_balance_cents` at its pre-charge value, so the escrow ledger never drifts. When instead a guarantee claim resolves as a replacement, the original `ESCROWED` payout is cancelled rather than clawed back: its `net_payout_cents` is driven to 0 and the seller's `escrow_balance_cents` is recomputed, while the replacement order mints its own payout.

### 3.6. Delivery: Transfers, Deadlines, and the Last-Minute Window

Delivery runs on the order's `delivery_status` axis, which moves independently of the payment axis. Once an order is charged, the `Seller` initiates delivery against the order; this mints a `Transfer` in `INITIATED` status whose `method` is copied from the listing's `delivery_method`, whose `is_last_minute` flag is computed at initiation, and whose `attempt_number` is set. Initiating a transfer requires the order's `delivery_status` to be `AWAITING` (or `DELIVERY_FAILED` for a retry) and the order's `payment_status` to be `CHARGED`; attempting delivery before payment is rejected with `ERR_DELIVERY_BEFORE_PAYMENT`. The first transfer on an order has `attempt_number` 1; when a prior transfer failed or expired and a new one is initiated for the same order, the `attempt_number` is the prior attempt's number plus one.

The seller then sends the credential, moving the transfer from `INITIATED` to `SENT`; the preconditions are that the transfer is `INITIATED` and the order's `payment_status` is `CHARGED`. Sending sets the transfer's `deadline_at` and moves the order's `delivery_status` from `AWAITING` or `DELIVERY_FAILED` to `IN_TRANSFER`. The `deadline_at` is computed from the clock at send time: a transfer's `is_last_minute` flag is true exactly when the send time is at or after `doors_open_at` minus `last_minute_cutoff_minutes`. If the transfer is not last-minute, the deadline is the send time plus the standard window of 1440 minutes (one full day). If it is last-minute, the deadline is the earlier of two candidates — the send time plus the compressed last-minute window of 30 minutes, or the event's `doors_open_at` — whichever comes first. Deadline arithmetic is at minute resolution.

The `Buyer` accepts the credential, moving the transfer from `SENT` to `ACCEPTED`; the preconditions are that the transfer is `SENT` and that the current clock is strictly before `deadline_at`. Acceptance at or after the deadline is rejected with `ERR_TRANSFER_DEADLINE_PASSED` — the boundary is half-open, so acceptance is valid only while the clock is strictly less than `deadline_at`. Acceptance moves the order's `delivery_status` to `DELIVERED` and turns the order's `SOLD` seats into `TRANSFERRED`, and the order's `lifecycle_state` is recomputed.

Several things can interrupt delivery. The seller may mark a transfer failed from either `INITIATED` or `SENT`, moving it to the terminal `FAILED` status and the order's `delivery_status` to `DELIVERY_FAILED`. The clock sweep expires a `SENT` transfer whose `deadline_at` has passed, moving it to the terminal `EXPIRED` status and the order to `DELIVERY_FAILED`. When delivery fails, the seats remain `SOLD` and the buyer may file a not-delivered guarantee claim; the seller may also re-initiate delivery from `DELIVERY_FAILED`, which mints a fresh transfer with the incremented `attempt_number`. Finally, the seller may recall a `SENT` credential before the buyer accepts it, moving the transfer to the terminal `RECALLED` status and returning the order's `delivery_status` to `AWAITING`; recall requires the transfer to be `SENT` and the clock to be before `deadline_at`. A transfer's terminal states are `ACCEPTED`, `EXPIRED`, `FAILED`, and `RECALLED`.

### 3.7. The Buyer Guarantee: Claims, Replacement, and Refund

When something goes wrong with a charged order, the `Buyer` files a `GuaranteeClaim` against it with a `reason` of `NOT_DELIVERED`, `INVALID_BARCODE`, `DUPLICATE_SEAT`, or `EVENT_ISSUE`. A new claim starts in `FILED` status with its `round_number` at 0. Only one open claim may exist per order at a time; filing a second while one is open is rejected with `ERR_OPEN_CLAIM_EXISTS`.

A `TrustSafety` operator drives adjudication. Investigation moves a `FILED` claim to `INVESTIGATING`. From `INVESTIGATING`, the operator may offer a replacement, moving the claim to `REPLACEMENT_OFFERED`; this requires supplying an `offered_listing_id` that references a listing whose `status` is `ACTIVE` on the same event as the original order, and whose `available_seat_count` is at least the original order's `quantity`. The buyer responds to an offer in one of two ways. Rejecting the offer returns the claim from `REPLACEMENT_OFFERED` to `INVESTIGATING` and increments the claim's `round_number` by 1 — this is the negotiation back-edge, and the cycle may repeat. Accepting the offer resolves the claim as `RESOLVED_REPLACED`; this requires the claim to be `REPLACEMENT_OFFERED` and the offered listing still `ACTIVE` with enough seats, and the buyer supplies the `expected_listing_version` of the offered listing as the OCC anchor for minting the replacement. On acceptance, a replacement `Order` is minted on the offered listing at a `locked_unit_price_cents` of 0 (the replacement is covered by the guarantee), already `CHARGED`, with its held seats moved to `SOLD`; the claim records the new order in `replacement_order_id`; the original order's `delivery_status` moves to `REPLACED` and its `SOLD` or `HELD` seats are voided; and the original `ESCROWED` payout is cancelled.

Alternatively the operator resolves the claim by refund from either `INVESTIGATING` or `REPLACEMENT_OFFERED`, moving it to `RESOLVED_REFUNDED`. The `refund_amount_cents` is computed by the guarantee-settlement calculation, which depends on the claim's `reason`. For all reasons the refund equals the order's `final_total_cents` — what the buyer actually paid after credit. The distinction lies in the applied credit: for a buyer-protection reason (`NOT_DELIVERED`, `INVALID_BARCODE`, or `DUPLICATE_SEAT`), in addition to the cash refund, a fresh `ISSUED` event credit for the order's `applied_credit_cents` is re-issued back to the buyer's wallet, so the credit is not lost. For an `EVENT_ISSUE` reason, only the cash refund is given and the previously applied credit is not re-issued, since the postponement that prompted it was the buyer's own choice. A refund resolution moves the order's `payment_status` from `CHARGED` to `REFUNDED`, claws back the `ESCROWED` or `RELEASABLE` payout, and voids the order's `SOLD` seats. The operator may also deny a claim from `FILED` or `INVESTIGATING`, moving it to `DENIED` with no financial change and the order unaffected. A claim's terminal states are `RESOLVED_REPLACED`, `RESOLVED_REFUNDED`, and `DENIED`.

### 3.8. Fraud and Duplicate Detection

A `TrustSafety` or `PlatformAdmin` operator raises a `FraudFlag` against a subject that is polymorphic: the `subject_type` is `LISTING`, `ORDER`, or `SEAT`, and exactly the matching foreign key is supplied — `listing_id` for a listing subject, `order_id` for an order subject, or `seat_id` for a seat subject. A subject id that does not match the declared `subject_type` is a referential mismatch per §2.7. The flag also carries a `signal`: `DUPLICATE_BARCODE`, `PRICE_GOUGE`, `VELOCITY`, or `CHARGEBACK`. On creation the flag's `severity` is computed and its `status` seeds at `OPEN`.

Severity is derived from the signal. A `DUPLICATE_BARCODE` signal is always `HIGH`. A `CHARGEBACK` signal is always `HIGH`. A `PRICE_GOUGE` signal is `HIGH` only when the subject listing's `effective_price_cents` exceeds the gouge band — the floor of the section's `face_value_cents` times the gouge ratio of 2.5 — and is otherwise `LOW`. A `VELOCITY` signal is always `LOW`. The moment a `HIGH`-severity flag lands on a listing, that listing is frozen: a `DRAFT` or `ACTIVE` listing transitions to `FROZEN`, and while frozen it rejects both activation and reservation with `ERR_LISTING_FROZEN`.

The flag's own lifecycle is driven by `TrustSafety`. Review moves an `OPEN` flag to `UNDER_REVIEW`. Confirmation moves a flag from `OPEN` or `UNDER_REVIEW` to the terminal `CONFIRMED` status; on confirmation, if the signal is `DUPLICATE_BARCODE` the flagged seat is voided and the listing's counts reconcile, if the subject listing is not already `FROZEN` and the severity is `HIGH` the listing is frozen, and the seller's `open_fraud_flag_count` is recomputed. Dismissal moves a flag from `OPEN` or `UNDER_REVIEW` to the terminal `DISMISSED` status; on dismissal, if this was the last `HIGH` open flag on a `FROZEN` listing the listing returns to `ACTIVE`, and the seller's `open_fraud_flag_count` is recomputed. A `FROZEN` listing returns to `ACTIVE` precisely when no other flag on it has severity `HIGH` and status `OPEN`, `UNDER_REVIEW`, or `CONFIRMED`.

### 3.9. Event Cancellation, Credits, and Their Lifecycle

Cancelling an event is the system's most consequential cascade. A `PlatformAdmin` cancels an event from `SCHEDULED`, `ON_SALE`, or `LAST_MINUTE`, driving it to the terminal `CANCELLED` status, and four hops follow in order. First, every listing on the event whose `status` is `ACTIVE`, `SOLD_OUT`, `DRAFT`, or `FROZEN` is delisted to `DELISTED`. Second, every order on the event whose `payment_status` is `CHARGED` has an `EventCredit` issued for it and its `payment_status` moves to `CREDITED`. Third, each such order's `ESCROWED` payout is clawed back, with `clawback_cents` set to the full `net_payout_cents`. Fourth, every seat on the credited orders is voided and all available counts reconcile.

The `amount_cents` of a cancellation credit is computed by the event-credit calculation, which rewards loyal buyers when the platform is at fault. The base is the order's `final_total_cents`. When the event's `status` is `CANCELLED` (treated as platform or event fault), a buyer whose `lifetime_orders_count` is at least the loyalty threshold of 3 receives a credit equal to the floor of the base times the goodwill bonus multiplier of 1.10 — a 110% credit — and the credit's `bonus_applied` flag is true; a buyer below that threshold receives a credit equal to the base, a 100% face credit, with `bonus_applied` false. When the credit arises in any other context, the amount is simply the base with no bonus.

An `EventCredit` records the `buyer_id` it belongs to, the `event_id` that generated it, and the `source_order_id` being unwound. A new credit is `ISSUED`. A credit is consumed — moving from `ISSUED` to `REDEEMED` — when a buyer's charge applies it (FIFO by `created_at` ascending), at which point the buyer's `wallet_credit_cents` is recomputed. A `TrustSafety` operator may revoke an `ISSUED` credit, moving it to the terminal `REVOKED` status and recomputing the buyer's `wallet_credit_cents`. The clock sweep expires an `ISSUED` credit whose validity window has elapsed, moving it to the terminal `EXPIRED` status and recomputing the buyer's `wallet_credit_cents`. `REDEEMED`, `EXPIRED`, and `REVOKED` are terminal credit states.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all state-transition operations and the clock controls — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the simulated current UTC clock to an absolute instant | PlatformAdmin |
| POST | `/_clock/advance` | Advance the simulated clock by N minutes; fire due sweeps | PlatformAdmin |
| POST | `/venues` | Create a venue | PlatformAdmin |
| GET | `/venues/{venueId}` | Get a venue | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/sections` | Create a section under a venue | PlatformAdmin |
| GET | `/sections/{sectionId}` | Get a section | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/sections` | List sections; filter by `venue_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/events` | Create an event | PlatformAdmin |
| GET | `/events/{eventId}` | Get an event | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/events` | List events; filter by `venue_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/events/{eventId}/open-sales` | Open the event for sales | PlatformAdmin |
| POST | `/events/{eventId}/enter-last-minute` | Enter the last-minute window | PlatformAdmin |
| POST | `/events/{eventId}/complete` | Complete the event; release escrowed payouts | PlatformAdmin |
| POST | `/events/{eventId}/cancel` | Cancel the event; run the four-hop cascade | PlatformAdmin |
| POST | `/events/{eventId}/postpone` | Postpone the event | PlatformAdmin |
| POST | `/sellers` | Register a seller | PlatformAdmin, Seller |
| GET | `/sellers/{sellerId}` | Get a seller | PlatformAdmin, Seller, TrustSafety |
| PATCH | `/sellers/{sellerId}/trust-tier` | Set a seller's trust tier | PlatformAdmin, TrustSafety |
| POST | `/buyers` | Register a buyer | PlatformAdmin, Buyer |
| GET | `/buyers/{buyerId}` | Get a buyer | PlatformAdmin, Buyer, TrustSafety |
| POST | `/listings` | Create a listing (DRAFT) | Seller |
| GET | `/listings/{listingId}` | Get a listing; refresh dynamic price | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/listings` | List listings; filter by `event_id`, `seller_id`, or `section_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/listings/{listingId}/activate` | Activate a listing | Seller |
| POST | `/listings/{listingId}/delist` | Delist a listing | Seller |
| POST | `/seats` | Add a seat to a DRAFT listing | Seller |
| GET | `/seats/{seatId}` | Get a seat | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/seats` | List seats; filter by `listing_id`, `order_id`, or `section_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/orders` | Create an order (reserve seats) | Buyer |
| GET | `/orders/{orderId}` | Get an order | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/orders` | List orders; filter by `listing_id`, `buyer_id`, or `replacement_of_order_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/orders/{orderId}/charge` | Charge the reservation | Buyer |
| POST | `/orders/{orderId}/cancel-reservation` | Cancel an unpaid reservation | Buyer |
| POST | `/orders/{orderId}/confirm-delivery-window` | Mark a delivered order's payout releasable | PlatformAdmin |
| POST | `/orders/{orderId}/transfers` | Initiate a transfer for a charged order | Seller |
| GET | `/transfers/{transferId}` | Get a transfer | PlatformAdmin, Seller, Buyer, TrustSafety |
| GET | `/transfers` | List transfers; filter by `order_id` | PlatformAdmin, Seller, Buyer, TrustSafety |
| POST | `/transfers/{transferId}/send` | Send the transfer credential | Seller |
| POST | `/transfers/{transferId}/accept` | Accept the credential | Buyer |
| POST | `/transfers/{transferId}/fail` | Mark the transfer failed | Seller |
| POST | `/transfers/{transferId}/recall` | Recall a sent credential | Seller |
| GET | `/payouts/{payoutId}` | Get a payout | PlatformAdmin, Seller, TrustSafety |
| GET | `/payouts` | List payouts; filter by `order_id` or `seller_id` | PlatformAdmin, Seller, TrustSafety |
| POST | `/payouts/{payoutId}/pay` | Release a payout to the seller | PlatformAdmin |
| POST | `/guarantee-claims` | File a guarantee claim | Buyer |
| GET | `/guarantee-claims/{claimId}` | Get a guarantee claim | PlatformAdmin, Buyer, Seller, TrustSafety |
| GET | `/guarantee-claims` | List claims; filter by `order_id`, `offered_listing_id`, or `replacement_order_id` | PlatformAdmin, Buyer, Seller, TrustSafety |
| POST | `/guarantee-claims/{claimId}/investigate` | Begin investigation | TrustSafety |
| POST | `/guarantee-claims/{claimId}/offer-replacement` | Offer a replacement listing | TrustSafety |
| POST | `/guarantee-claims/{claimId}/reject-offer` | Reject the offered replacement | Buyer |
| POST | `/guarantee-claims/{claimId}/accept-offer` | Accept the replacement | Buyer |
| POST | `/guarantee-claims/{claimId}/refund` | Resolve the claim by refund | TrustSafety |
| POST | `/guarantee-claims/{claimId}/deny` | Deny the claim | TrustSafety |
| GET | `/event-credits/{creditId}` | Get an event credit | PlatformAdmin, Buyer, TrustSafety |
| GET | `/event-credits` | List credits; filter by `buyer_id`, `event_id`, or `source_order_id` | PlatformAdmin, Buyer, TrustSafety |
| POST | `/event-credits/{creditId}/revoke` | Revoke an issued credit | TrustSafety |
| POST | `/fraud-flags` | Raise a fraud flag | TrustSafety, PlatformAdmin |
| GET | `/fraud-flags/{flagId}` | Get a fraud flag | PlatformAdmin, TrustSafety, Seller |
| GET | `/fraud-flags` | List flags; filter by `listing_id`, `order_id`, or `seat_id` | PlatformAdmin, TrustSafety, Seller |
| POST | `/fraud-flags/{flagId}/review` | Begin review | TrustSafety |
| POST | `/fraud-flags/{flagId}/confirm` | Confirm fraud | TrustSafety |
| POST | `/fraud-flags/{flagId}/dismiss` | Dismiss a flag | TrustSafety |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_VENUE_NOT_FOUND` | 404 Not Found |
| `ERR_SECTION_NOT_FOUND` | 404 Not Found |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_SELLER_NOT_FOUND` | 404 Not Found |
| `ERR_BUYER_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_SEAT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_PAYOUT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_FLAG_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENTIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_EVENT_NOT_SELLING` | 409 Conflict |
| `ERR_LISTING_FROZEN` | 409 Conflict |
| `ERR_DELIVERY_BEFORE_PAYMENT` | 409 Conflict |
| `ERR_PAYOUT_NOT_RELEASABLE` | 409 Conflict |
| `ERR_SELLER_RESTRICTED` | 409 Conflict |
| `ERR_RESERVATION_EXPIRED` | 409 Conflict |
| `ERR_TRANSFER_DEADLINE_PASSED` | 409 Conflict |
| `ERR_SPLIT_RULE_VIOLATION` | 409 Conflict |
| `ERR_DUPLICATE_BARCODE` | 409 Conflict |
| `ERR_INSUFFICIENT_SEATS` | 409 Conflict |
| `ERR_OPEN_CLAIM_EXISTS` | 409 Conflict |
| `ERR_SEAT_NOT_ADDABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_WALLET_CREDIT` | 402 Payment Required |
| `ERR_PRICE_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_DYNAMIC_FLOOR_INVALID` | 402 Payment Required |
| `ERR_STALE_LISTING_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PAYOUT_VERSION` | 412 Precondition Failed |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 Conflict |

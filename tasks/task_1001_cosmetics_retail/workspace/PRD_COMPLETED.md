# Cosmetics & Beauty Retail API — Product Requirements Document

## 1. Introduction

Beauty retail is deceptively hard software. A single foundation SKU fans out into forty shades; a shopper wants the one shade that matches her undertone and depth, wants to collect it from the store she is walking past in an hour, wants the tier discount she earned last quarter, wants the gift-with-purchase the sign in the window promised, and — if the shade is wrong after all — wants her money back. Behind her, a store associate is putting testers out on the floor, an artist is running a brow appointment, and a merchandiser is opening a limited launch that a thousand people are waiting for. Every one of those actions moves the same small pile of units.

This document specifies the backend that arbitrates all of it. The service owns the catalogue (products, shade variants, per-store inventory lots), the loyalty programme (tiers, a strictly conserved points ledger, redemption), the order pipeline across both buy-online-pickup-in-store and ship-from-store channels, gift/sample/bundle promotions, in-store service bookings, hygiene-governed returns, and limited-launch allocation. Two properties are non-negotiable and shape almost every rule below: **units are conserved** — no unit of stock is ever created or destroyed except through an explicitly named movement — and **points are conserved** — a customer's balance is, at every instant, exactly the sum of their ledger entries.

The system is deliberately deterministic. It runs on a **logical clock**, not wall-clock time, so that launch windows and return windows can be driven and audited exactly. Where a calculation could plausibly be performed in two orders, this document pins the order, because the two orders produce different numbers of cents and only one of them is correct.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. If either header is absent, or if `X-User-Role` is not one of the four declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not among the roles authorised for the requested operation (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are `Customer`, `StoreAssociate`, `BeautyArtist`, and `MerchandisingAdmin`.

A `Customer` is a loyalty member who shops, redeems points, books services and asks for returns. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` compare that resource's customer-reference field to `X-User-ID`. Concretely, a `Customer` may only read or mutate resources whose `customer_id` equals their `X-User-ID`, and an order line, return request or points-ledger entry inherits ownership from the order or customer it hangs off. A violation is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). On list endpoints the same rule is applied by *scoping* rather than by rejection: when the caller is a `Customer`, the listings of orders, order lines, points-ledger entries, service bookings and return requests are silently narrowed to that customer's own records, and a `customer_id` filter naming somebody else — or, on `GET /order-lines`, an `order_id` filter naming an order owned by somebody else — is rejected with `ERR_FORBIDDEN_OWNERSHIP` instead.

A `BeautyArtist` is an in-store service provider who accepts proposed reschedules and closes bookings. When `X-User-Role` is `BeautyArtist`, `X-User-ID` is the `id` of the acting `Artist` entity; ownership checks on any resource that references an `Artist` compare the resource's artist-reference field to `X-User-ID`.

A `StoreAssociate` is store staff: they stage pickup orders, ship parcels, put testers out on the floor, and decide returns. A `MerchandisingAdmin` operates the catalogue, inventory, promotions, launches, the loyalty cycle and the logical clock. For both of these roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server accepts it and may log it, but never compares it to any entity's `id`, and neither role is subject to the ownership check.

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

List endpoints are paginated through two query parameters. `limit` caps the number of records returned; it defaults to 10, may be no smaller than 1 and no larger than 100. `offset` is the number of records to skip and defaults to 0; the smallest accepted value is 0. A `limit` or `offset` that is not an integer, or that falls outside those bounds, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order — oldest record first.

Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` is the number of records matching the filters before pagination is applied, and `has_more` is true exactly when records remain beyond the current window.

### 2.4. The Logical Clock

No *domain* deadline in this system reads the host machine's wall clock. (The envelope's `api_request_timestamp` and the bookkeeping stamps `created_at` and `updated_at` of §2.5 are the sole exceptions: they are taken from host time, because they record when the row was written rather than when anything is due.) The server boots with its logical clock set to exactly `2026-05-01T00:00:00Z`, and that instant remains "now" until a `MerchandisingAdmin` moves it. Advancing the clock is done by supplying a target instant as `to_iso8601` — any instant is accepted, including one earlier than the present `current_utc`, though launch gates only ever step forward and are never rolled back — and the response reports the resulting `current_utc` together with `advanced_variant_ids`, the list of variant identifiers whose launch gate moved as a consequence of the new time, in creation order. This response is not an entity, so it carries no `id`.

Every deadline in this document — a limited launch opening to a tier, the thirty-day return window, the instant a loyalty cycle began, the moment a booking is due — is measured against this logical clock and against nothing else, as are the domain stamps `cycle_started_at`, `fulfilled_at` and `decided_at`.

### 2.5. Common Resource Properties

Every persisted resource carries an `id`: a server-minted UUID with no type prefix, unique across the system, and a `created_at`: an ISO 8601 UTC timestamp with three fractional digits recording when the record first came into being.

Most resources — `Store`, `Product`, `Variant`, `InventoryLot`, `Customer`, `Promotion`, `Order`, `OrderLine`, `Artist`, `ServiceBooking` and `ReturnRequest` — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that record. A "mutation" here includes derived-field recomputation: when an order's money fields are recalculated, or an inventory lot's counters move, or a customer's tier changes, that record's `updated_at` is refreshed and its `version` is incremented, exactly as if a client had edited it directly.

Points-ledger entries are the exception. A ledger entry is append-only and immutable once written, so it carries only `id` and `created_at`; it has **no** `updated_at` field and **no** `version` field.

### 2.6. Money, Points and Rounding

All money in this system is an integer number of cents. There are no floating-point amounts in any stored field or any response body. Percentages (a tier discount, a bundle discount, a restocking fee) are applied to an integer cent amount and the product is immediately rounded **half up** to a whole cent before it is used anywhere downstream. Where a calculation names a rounding step, that step happens exactly once, at exactly the point named — rounding earlier or later, or rounding an intermediate that the specification leaves unrounded, produces a different total, and the different total is wrong.

Points are integers throughout. Where a points formula multiplies by a fractional tier multiplier, the result is truncated toward zero (floored) at each named multiplication, and any cap is applied after the floors.

### 2.7. Conserved Quantities

Two invariants hold after every single operation the API exposes, and the implementation must be able to demonstrate them at any moment.

First, **units are conserved inside a lot**. For every `InventoryLot`, the total `units_received` always equals the sum of `on_hand_units`, `reserved_units`, `tester_units`, `sold_units` and `destroyed_units`. Reserving an order moves units from on-hand to reserved; handing an order over moves them from reserved to sold; converting a tester moves them from on-hand to tester; a hygiene-mandated destruction moves them from sold to destroyed; a restock moves them from sold back to on-hand; a cancellation moves them from reserved back to on-hand. No path creates or annihilates a unit.

Second, **points are conserved in the ledger**. A `Customer`'s `points_balance` always equals the arithmetic sum of `delta_points` across every `PointsLedgerEntry` belonging to that customer. There is no way to move a balance except by appending an entry, and every entry records `balance_after` — the customer's `points_balance` immediately after that entry was appended — so the ledger is self-auditing.

### 2.8. Optimistic Concurrency on Shared Counters

Two operations write to records that other actors are constantly moving underneath them, and both are guarded by an optimistic-concurrency check on the *parent* record's `version`.

Putting testers out on the floor writes to an `InventoryLot`, and the request must carry `expected_lot_version` — a required, non-optional field holding the `version` the associate observed when they last read that lot. If `expected_lot_version` does not equal the lot's current `version`, the conversion is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). A second tester conversion against the same lot is perfectly legitimate on its own terms — multiple testers per lot are normal — so the stale-version check is the only deterministic guard available: it fires whenever the lot has moved since the read, whether because an order reserved units, a return restocked units, or another conversion landed first.

Adding a line to a draft order writes to an `Order`, and the request must carry `expected_order_version` — again required, non-optional, holding the `version` the client last observed on that order. If `expected_order_version` does not equal the order's current `version`, the line addition is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). The reason is that every line addition re-runs the pricing engine and supersedes the quote the client was looking at: bundle eligibility, gift eligibility and every total can shift. A client holding a stale quote must re-read the order before adding another line.

No other endpoint takes a version field, and no other endpoint performs a version check. In particular, reserving, paying, fulfilling, cancelling, deciding a return and rescheduling a booking carry no expected-version input.

### 2.9. Validation Precedence

When more than one rule could reject a request, the rules are evaluated in a fixed order and the *first* failure is the one reported. The order is:

1. Authentication — headers present and the role recognised (`ERR_UNAUTHENTICATED`).
2. Authorisation — the acting role appears in the endpoint's role list (`ERR_UNAUTHORIZED`).
3. Path existence — every resource named in the URL path exists, checked left to right, so that the leftmost missing identifier is the one reported. Depending on which identifier fails, the code is `ERR_STORE_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND` or `ERR_RETURN_NOT_FOUND` — all HTTP 404.
4. Payload shape — on every write, all required fields are present, every enum value is legal, every numeric field is in range, `points_redeemed` is an exact multiple of 100, a pickup order carries an on-the-hour `pickup_slot_start`, and a booked artist actually holds the skill being booked. Any breach is `ERR_INVALID_REQUEST` (HTTP 400).
5. Body-reference existence — every foreign key inside the request body resolves to an existing row, reported with the same 404 family as step 3 (`ERR_STORE_NOT_FOUND`, `ERR_VARIANT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`). This applies to order creation, line addition, inventory-lot creation, service-booking creation (including its optional `linked_order_id`), return-request creation, promotion creation (its `gift_variant_id` and every member of its `bundle_variant_ids`) and the shade finder (its optional `store_id`).
6. Ownership — a `Customer` acting on someone else's resource is rejected with `ERR_FORBIDDEN_OWNERSHIP`. This guards customer reads, points-ledger reads, order creation and every order action, service-booking creation and every booking action, and return-request creation.
7. State — the target resource is in a state from which the requested transition is declared. Order actions (line addition, reserve, payment, fulfilment, cancel) report `ERR_INVALID_ORDER_STATE`; booking actions report `ERR_INVALID_BOOKING_STATE`; return creation and return decisions report `ERR_INVALID_RETURN_STATE`. All are HTTP 409.
8. Optimistic concurrency — the expected-version field matches the live parent version, per §2.8, on line addition (`ERR_STALE_ORDER_VERSION`) and tester conversion (`ERR_STALE_LOT_VERSION`).

Everything else — the business rules of §3 — is evaluated after these eight, and §3 states the relative ordering wherever two business rules could both fire on the same request.

### 2.10. Hygiene Classification

Every `Product` is stamped at creation with a `hygiene_class`, and that classification governs two entirely separate downstream policies: whether the product may be put out as a tester, and whether it may be returned. The three classes are `SEALED` (shrink-wrapped or boxed goods), `TESTER_APPLIED` (goods that may be sampled on the floor with a disposable applicator) and `DIRECT_CONTACT` (goods that touch skin, lips or eyes directly and can never be sanitised).

`DIRECT_CONTACT` is an absolute bar on both policies. A tester conversion against a lot whose product is `DIRECT_CONTACT` is rejected with `ERR_TESTER_NOT_ALLOWED` (HTTP 422), and a return request against a line whose product was `DIRECT_CONTACT` is rejected with `ERR_HYGIENE_NON_RETURNABLE` (HTTP 422). Because a `DIRECT_CONTACT` line can never reach an approval decision, no refund disposition is ever computed for one.

### 2.11. Nested Resource Retrieval

Path parameters are resolved strictly left to right. A request for a variant nested under a product resolves the product first; if the product identifier does not name an existing product, the response is `ERR_PRODUCT_NOT_FOUND` and the variant is never looked up. The same discipline applies to every action hung off an order, a lot, a booking or a return request: the parent named in the path must exist before any body field, any state rule or any business rule is considered.

## 3. Business Logic & Workflows

### 3.1. Catalogue Foundations: Stores, Products and Shade Variants

A `MerchandisingAdmin` builds the world. A **Store** is created with a `name` and a two-letter `region_code` — both are required, and both are validated only as non-empty strings, so a `region_code` of some other length is stored as given rather than rejected. Its `status` is `ACTIVE` unless the admin says otherwise (it may be supplied at creation), and the only other legal value is `PAUSED`; a paused store is one that has temporarily stopped taking business. A store also carries `bopis_slot_capacity` — how many pickup orders may occupy one sixty-minute pickup slot — which defaults to 2 and must be at least 1. Both `status` and `bopis_slot_capacity` remain editable afterwards, and each such edit increments the store's `version`.

A **Product** is a SKU family: a `name`, a `brand`, a merchandising `category` drawn from `SKINCARE`, `MAKEUP`, `FRAGRANCE` and `HAIR`, the `hygiene_class` of §2.10, and a `base_price_cents` — an integer of zero or more cents that variants inherit when they do not name a price of their own.

Under a product hang its **Variants**, one per shade or finish. Each variant records the `product_id` of the SKU family it belongs to, a human `shade_name` such as "Warm Sand", the vendor's `shade_code`, a `finish` of `MATTE`, `DEWY` or `SATIN`, an `undertone` of `WARM`, `COOL` or `NEUTRAL`, and a `depth_index` positioned on a twelve-point scale where 1 is the lightest shade and 12 the deepest — values outside 1 through 12 inclusive are rejected. A variant may carry its own `price_cents`, an integer of zero or more; when the field is omitted, the variant sells at the product's `base_price_cents`. Sellability lives in the variant's `status`, which starts at `ACTIVE` and may be moved to `DISCONTINUED`; a discontinued variant may not appear on a sale line, and an attempt to reserve or add such a line fails with `ERR_VARIANT_NOT_SELLABLE` (HTTP 409). (Naming a discontinued variant among an order's *initial* lines is not itself refused — the refusal lands when the order is reserved.) An admin may also revise a variant's `price_cents`, and may write the variant's `launch_status` directly to any of the six declared values; that write is applied verbatim, with no transition check. Each such edit increments the variant's `version`.

Finally, a variant may be flagged `is_limited_launch`. When that flag is false — the default — the variant's `launch_status` is `NOT_LIMITED` and stays there forever; the variant has no launch gate at all. When the flag is true, the variant is born in `SCHEDULED`, and it acquires a launch schedule: `launch_open_rouge_at`, `launch_open_vib_at` and `launch_open_public_at`, three UTC instants, plus `per_customer_cap`, the ceiling on how many units of this variant a single customer may hold, defaulting to 2 and never below 1. All four of these are optional inputs on every variant: `per_customer_cap` is recorded (defaulting to 2) whether the variant is limited or not, and any launch instant that is omitted is stored as null and simply never fires its gate, so a limited variant created without a `launch_open_rouge_at` stays in `SCHEDULED` however far the clock is moved. Section 3.6 explains what those gates do.

### 3.2. Stocking the Floor: Inventory Lots and Testers

Stock lives in an **InventoryLot**, and there is exactly one lot per pairing of `store_id` and `variant_id`. A second attempt to create a lot for a pairing that already has one is rejected with `ERR_LOT_ALREADY_EXISTS` (HTTP 409). The admin creating a lot supplies `units_received` — the conserved total, zero or more, that every counter on the lot must always add back up to — and may earmark part of it as `launch_reserved_units`, a sub-count of stock held back for a limited-launch draw. The earmark defaults to 0 and may be anywhere from 0 up to and including `units_received`; an earmark larger than `units_received` is a payload-shape breach and is rejected with `ERR_INVALID_REQUEST` (HTTP 400) before the `store_id` and `variant_id` are even resolved. At creation, `on_hand_units` is set equal to `units_received`, and `reserved_units`, `tester_units`, `sold_units` and `destroyed_units` all start at 0.

The five counters mean exactly what their names say. `on_hand_units` are units physically present and unreserved. `reserved_units` are units held by orders that have been reserved or staged for pickup. `tester_units` are units broken out onto the floor for customers to try; a tester is never sellable again. `sold_units` are units already handed over or shipped. `destroyed_units` are units binned because a hygiene-mandated return disposition demanded it. Note carefully that `launch_reserved_units` is *not* a sixth bucket — it is a marker on a slice of `on_hand_units`, which is why the general pool available to an ordinary shopper is `on_hand_units` less `launch_reserved_units`.

A `StoreAssociate` puts testers out by naming a lot, the number of `units` to convert (a required integer of at least 1), and the lot version they observed as `expected_lot_version` (§2.8). The conversion succeeds only if the product is not `DIRECT_CONTACT` (§2.10) and only if the lot has enough units to give: if `on_hand_units` cannot cover the requested `units`, the request is rejected with `ERR_INSUFFICIENT_STOCK` (HTTP 409). On success, the requested count moves out of `on_hand_units` and into `tester_units`, and the lot's `version` increments — which is precisely why the next associate holding a pre-conversion version number will be turned away with `ERR_STALE_LOT_VERSION`.

### 3.3. The Shade Finder

A shopper (or an associate helping one at the counter) can ask the system to find the single best shade for them. The request states the `undertone` they want, the `depth_index` they believe they sit at (which, like a variant's, must lie between 1 and 12 inclusive), and a `finish_pref` — all three required; it may optionally name a `store_id`, which restricts the answer to shades they could actually walk out with today and which must resolve to an existing store, failing with `ERR_STORE_NOT_FOUND` if it does not.

Candidacy comes first. A variant is a candidate only if its `status` is `ACTIVE`, only if its `launch_status` is either `NOT_LIMITED` or `PUBLIC` (a shade still inside a tier-gated launch window is never recommended), and only if its `depth_index` sits within two steps of the requested depth in either direction — a difference of exactly two is still inside the tolerance. When a `store_id` is supplied, the variant additionally needs an inventory lot at that store whose `on_hand_units` less its `launch_reserved_units` is at least one unit. If nothing survives the filter, the request fails with `ERR_NO_SHADE_MATCH` (HTTP 422).

Surviving candidates are scored. Each starts from a base of 100 points. Ten points are then deducted for each step of depth difference between the candidate and the request — a two-step difference costs twenty points. Twenty-five points are added when the candidate's `undertone` equals the requested undertone, and a further fifteen points are added when the candidate's `finish` equals the requested `finish_pref`. The highest score wins. When two candidates score identically, the one whose depth is closer to the request wins; if they are still tied, the older record — the earlier `created_at` — wins. Identifiers are never used to break the tie. Exactly one variant is returned, and it is returned as the bare `Variant` resource in `data` — the score is not part of the response.

### 3.4. Loyalty: Tiers, Cycles and the Points Ledger

A **Customer** is created by a `MerchandisingAdmin` with a unique `email` and a display `name`. (Uniqueness is a convention of the data, not a rule the server polices: a second customer carrying an email already in use is created without complaint.) Seeding fields let an admin place a customer at a chosen position in the programme: `initial_tier` sets the starting `tier` verbatim — it is never re-derived from the seeded spend, so an admin may legitimately seed a `ROUGE` customer with zero spend — `initial_points` sets the starting `points_balance`, and `initial_qualifying_spend_cents` sets the starting `qualifying_spend_cents`. `lifetime_spend_cents` is *not* seeded and always starts at 0, however large the seeded cycle spend. Absent a seed, a customer starts at tier `INSIDER` with a zero balance and zero spend. A new customer's `hygiene_strikes` is 0 and their `return_privilege` is `ACTIVE` (§3.9). Whenever `initial_points` is greater than zero, the system does not simply write the number into the balance — it appends a ledger entry with `entry_type` of `SEED` carrying that many points as `delta_points`, so that the conservation rule of §2.7 holds from the very first instant. The customer's `cycle_started_at` is stamped with the current logical-clock instant at creation.

Three tiers exist: `INSIDER`, `VIB` and `ROUGE`, ranked in that order. What a customer's tier is worth is the same wherever it appears: `INSIDER` earns no tier discount at all, `VIB` earns a ten-percent discount and a one-and-a-half-times points multiplier, and `ROUGE` earns a fifteen-percent discount and a two-times points multiplier.

Tier is *earned* by `qualifying_spend_cents`, the net cash the customer has spent inside the current loyalty cycle. The target tier for any spend figure is `ROUGE` when the spend is at least 100,000 cents — one thousand dollars — `VIB` when it is at least 35,000 cents and short of the ROUGE line, and `INSIDER` otherwise. Both thresholds are inclusive: a customer sitting at exactly 35,000 cents *is* a `VIB`, and one at exactly 100,000 cents *is* a `ROUGE`. Alongside this cycle figure the system tracks `lifetime_spend_cents`, the same net cash summed across all cycles, which is never reset.

The tier is re-derived in two distinct modes, and the difference between them is the whole point of the programme. The **rolling** mode runs automatically whenever an order is fulfilled and whenever a return is approved. It is monotone: it compares the target tier for the customer's current `qualifying_spend_cents` against the customer's present tier by rank, and it writes the new tier **only when the target ranks strictly higher**. A tier, once earned, is sticky for the remainder of the cycle — a refund that drags `qualifying_spend_cents` back below the threshold never claws the tier back. The **checkpoint** mode runs only when a `MerchandisingAdmin` explicitly closes the cycle. It re-derives the tier from exactly the same `qualifying_spend_cents` figure using exactly the same thresholds, but it writes the result unconditionally, so it *does* downgrade: a `ROUGE` customer who ended the cycle between 35,000 and 100,000 cents (at least 35,000 and strictly below 100,000) becomes `VIB`; a `ROUGE` or a `VIB` customer who ended below 35,000 cents becomes `INSIDER`. Having re-derived the tier, the checkpoint zeroes `qualifying_spend_cents` and stamps `cycle_started_at` with the current logical-clock instant, and the customer's `version` increments. The same spend number, run through the two modes, can produce two different tiers — that is by design.

Every movement of points is a **PointsLedgerEntry**, and each entry records the `customer_id` who owns it, the `order_id` that caused it (null for a `SEED` entry, which has no order behind it), an `entry_type`, the signed `delta_points`, and the `balance_after`. The six entry types are `SEED` (an admin's opening balance), `EARN` (points accrued at fulfilment), `REDEEM` (points spent on an order, always negative), `REVERSAL` (a redemption given back when its order was cancelled, always positive), `CLAWBACK` (points taken back when a return was refunded, always negative) and `SERVICE_BONUS` (the bonus for completing a linked in-store service). Ledger entries can be listed and filtered by `customer_id` and by `order_id`, and are returned oldest first. A ledger entry is the one resource with no not-found code of its own in the §2.9 family: reading an identifier that names no entry answers with the generic `ERR_NOT_FOUND` (HTTP 404).

### 3.5. Building the Basket: Draft Orders, Promotions and the Provisional Quote

A **Promotion** is authored by a `MerchandisingAdmin` and comes in three kinds, declared as `promo_type`. A `GWP` promotion attaches a free gift once the basket is big enough. A `SAMPLE` promotion attaches a free sample on the same terms. A `BUNDLE` promotion discounts a set of shades bought together. All three carry a `name`, a `priority` (an integer used to break ties between competing promotions of the same kind — lower wins — defaulting to 100) and a `status` that is `ACTIVE` by default and may be `ENDED`; an `ENDED` promotion is never selected.

For `GWP` and `SAMPLE`, `threshold_cents` is the minimum basket value at which the promotion becomes eligible (defaulting to 0, never negative), `gift_variant_id` names the variant that is given away, and `gift_quantity` is how many units of it are attached (defaulting to 1, at least 1). `gift_variant_id` is nonetheless an optional field on every kind of promotion: a `GWP` or `SAMPLE` authored without one is accepted, and simply never materialises a line. For `BUNDLE`, `gift_variant_id` is null and instead `bundle_variant_ids` holds an array of variant identifiers **all** of which must appear as sale lines before the bundle applies (it too is optional, defaulting to an empty array on a `BUNDLE` and to null otherwise; a bundle with no members never qualifies), while `bundle_discount_pct` is the fractional discount applied to each member line — 0.15 meaning fifteen percent — defaulting to 0 and constrained to at least 0 and strictly below 1.

An order begins life as a draft. A `Customer` or a `StoreAssociate` creates it by naming the buying `customer_id`, the fulfilling `store_id`, the `channel` — either `BOPIS` for collect-in-store or `SHIP_FROM_STORE` for a parcel — and the initial `lines`, each of which names a `variant_id` and a `quantity` of at least one unit. The `lines` array is itself required, but it may be empty: a draft with no lines at all is legal, and prices out at zero. A `BOPIS` order must also carry a `pickup_slot_start`: the UTC instant a sixty-minute collection slot begins, and it must land exactly on the hour. (A `pickup_slot_start` volunteered on a `SHIP_FROM_STORE` order is simply stored as given and never checked against the hour, because that channel has no slot.) Two further inputs belong to the reservation rules rather than the basket, and are discussed in §3.6: `allow_partial` and `points_redeemed`. The order is born with `fulfillment_status` of `DRAFT` and `payment_status` of `UNPAID`.

Each line of the basket becomes an **OrderLine** hanging off the order via its `order_id`. It carries the `variant_id` bought, the `quantity`, and a `line_type` — `SALE` for anything the customer chose, `GWP` for a materialised gift, `SAMPLE` for a materialised sample. Only gift and sample lines carry a `promotion_id` pointing at the promotion that produced them; a sale line's `promotion_id` is null. At the moment the line is created, two values are snapshotted onto it and never move again: `unit_price_cents`, copied from the variant's effective selling price (which is zero for gift and sample lines), and `hygiene_class`, copied from the owning product, because the return policy that will apply months later must be the policy in force on the day of sale. Every line also tracks `returned_quantity`, the units already given back through approved returns, starting at 0.

While the order is in `DRAFT`, more sale lines may be added, one at a time, by naming a `variant_id` and a `quantity` and supplying `expected_order_version` per §2.8. A line may only be added to a `DRAFT` order — an attempt against an order in any other fulfilment state is `ERR_INVALID_ORDER_STATE` — and it may not name a `DISCONTINUED` variant, which fails with `ERR_VARIANT_NOT_SELLABLE`. What comes back from a line addition is the re-quoted `Order`, not the newly created `OrderLine`, and the status is 200 rather than 201, because an order line is not independently created by the client (§4).

**The pricing engine.** Every touch of the basket — creating the order, and every line added afterwards — reprices the whole order and hands back a fresh quote. The steps run in this pinned order, and running them in any other order gives a different number of cents:

1. Each sale line's `line_gross_cents` is its snapshotted `unit_price_cents` multiplied by its `quantity`.
2. The bundle, if any, is selected. A `BUNDLE` promotion qualifies when its `status` is `ACTIVE` and every one of the variants in its `bundle_variant_ids` appears on the order as a sale line with a quantity of at least one unit. If several bundles qualify, they are ranked by `bundle_discount_pct` from largest to smallest; ties are broken by `priority` from smallest to largest; any remaining tie is broken by `created_at`, oldest first. One bundle wins, and a line never receives more than one bundle discount. For each sale line whose `variant_id` is one of the winning bundle's `bundle_variant_ids`, `line_discount_cents` is that line's `line_gross_cents` multiplied by the winning `bundle_discount_pct` and **rounded half up on that line, on its own**; for every other line it is 0. `line_net_cents` is then `line_gross_cents` less `line_discount_cents`. The per-line rounding matters: taking the percentage against the summed gross of the bundle members and rounding the result once produces a different cent figure, and that figure is wrong.
3. `subtotal_cents` is the sum of `line_net_cents` across the **sale** lines only. Gift and sample lines contribute nothing, because their price is zero.
4. The loyalty-tier discount is applied to that subtotal. The percentage used is the one belonging to the tier the order is priced at — no discount for `INSIDER`, ten percent for `VIB`, fifteen percent for `ROUGE`. `tier_discount_cents` is `subtotal_cents` multiplied by that percentage, rounded half up, and `discounted_subtotal_cents` is `subtotal_cents` less `tier_discount_cents`.
5. Gift and sample eligibility is tested against `discounted_subtotal_cents` — that is, **after** the tier discount and **before** any points redemption. Among `ACTIVE` `GWP` promotions, those whose `threshold_cents` is less than or equal to `discounted_subtotal_cents` qualify; they are ranked by `threshold_cents` from largest to smallest, ties broken by `priority` smallest first and then by `created_at` oldest first, and the top one is selected. `gwp_eligible` is true exactly when such a promotion was found, and false when none was.
6. Points are converted to cash last, and never move the gift threshold. Every whole block of 100 redeemed points is worth 500 cents, so `points_value_cents` is the number of 100-point blocks in `points_redeemed` multiplied by 500. `total_due_cents` is `discounted_subtotal_cents` less `points_value_cents`.

There is an obvious circularity here — the tier discount depends on the tier, the tier can be raised *by this very order*, and the gift threshold depends on the tier discount — and it is resolved by pinning: the tier used to price an order is the customer's tier as it stands **before** this order's own upgrade, and any upgrade this order earns lands only at fulfilment. The order records which pass produced its current money in `pricing_variant`. On the draft passes the value is `PROVISIONAL`: quantities are taken exactly as requested, stock is not consulted at all, `gwp_eligible` is advisory only, and **no** gift or sample line rows are created. Only the reservation pass, described next, sets `pricing_variant` to `FINAL` and materialises anything.

### 3.6. Reservation: Allocation, Limited Launches and Final Pricing

Reserving is the moment of truth: the basket stops being a quote and becomes a claim on physical units. It moves the order's `fulfillment_status` from `DRAFT` to `RESERVED`, and it may only be performed on a `DRAFT` order.

Two order-level inputs, supplied back when the order was created, now come into force. `points_redeemed` is how many of the buyer's points they wish to spend; it defaults to 0 and must be an exact multiple of 100 — anything else is `ERR_INVALID_REQUEST` at the time it is supplied. `allow_partial` defaults to false, and it decides what the system does when the shelf cannot cover the basket: with `allow_partial` false, a shortfall aborts the whole reservation; with `allow_partial` true, each sale line's `quantity` is instead clipped down to the units that can actually be drawn, and the reservation proceeds on the smaller basket.

Before any unit moves, a series of gates is checked, in this order:

- The fulfilling store's `status` must be `ACTIVE`. Reserving at a `PAUSED` store fails with `ERR_STORE_NOT_ACTIVE` (HTTP 409).
- Every sale line's variant `status` must be `ACTIVE`; a `DISCONTINUED` variant on the basket fails with `ERR_VARIANT_NOT_SELLABLE` (HTTP 409).
- For a `BOPIS` order, the requested collection slot must have room. Occupancy is a simple head-count, not a geometric overlap test: the system counts the orders at the same store carrying exactly the same `pickup_slot_start` whose `fulfillment_status` is `RESERVED` or `READY_FOR_PICKUP`. When that count has already reached the store's `bopis_slot_capacity`, the slot is full and the reservation fails with `ERR_PICKUP_SLOT_FULL` (HTTP 409). The boundary is inclusive: a store with a capacity of 2 accepts a third order only if one of the first two has left the slot.

**Limited-launch allocation.** Every sale line whose variant is flagged `is_limited_launch` then runs the allocation draw, and the draw has three gates of its own.

Gate one is the tier window, read off the variant's `launch_status`. A variant still in `SCHEDULED` has not opened; a variant whose launch has been shut down to `CLOSED` will never open again; in both cases the line fails with `ERR_LAUNCH_NOT_OPEN` (HTTP 409). A variant in `TIER_ROUGE_ONLY` may only be drawn by a customer whose tier is `ROUGE`. A variant in `TIER_VIB_PLUS` may be drawn by a customer whose tier is `VIB` or `ROUGE`. A variant in `PUBLIC` may be drawn by any tier. A customer whose tier does not clear the currently open window is turned away with `ERR_LAUNCH_TIER_LOCKED` (HTTP 403). These gates advance on the logical clock, not on demand: when a `MerchandisingAdmin` moves the clock forward, every limited variant whose thresholds the new instant has crossed is stepped through its gates in sequence — from `SCHEDULED` to `TIER_ROUGE_ONLY` once the clock reaches or passes `launch_open_rouge_at`, on to `TIER_VIB_PLUS` once it reaches or passes `launch_open_vib_at`, and on to `PUBLIC` once it reaches or passes `launch_open_public_at`, always in that order — and each step increments the variant's `version`. Separately, a `MerchandisingAdmin` may shut a launch down by setting the variant's `launch_status` to `CLOSED`, either after it has gone `PUBLIC` or from `SCHEDULED` before it ever opened; a closed launch is terminal.

Gate two is the per-customer cap. The system sums the quantities of every order line naming this variant across all of this customer's orders whose `fulfillment_status` is anything other than `CANCELLED`, **excluding the order now being reserved**. If that held count plus the quantity requested on this line exceeds the variant's `per_customer_cap`, the line fails with `ERR_LAUNCH_CAP_EXCEEDED` (HTTP 409). The boundary is inclusive in the customer's favour: held plus requested landing exactly on the cap is allowed.

Gate three is the waterfall draw itself. The launch pool is exhausted before the general pool, never the reverse. From the lot at the order's store for this variant, the units taken from the launch pool are the smaller of the line's `quantity` and the lot's `launch_reserved_units`; whatever quantity remains after that must come from the general pool, whose size is the lot's `on_hand_units` less its `launch_reserved_units`. If the remainder exceeds what the general pool holds, then — when `allow_partial` is true — the line's `quantity` is clipped down to the launch-pool units plus the general-pool units actually available, and — when `allow_partial` is false — the reservation fails with `ERR_INSUFFICIENT_STOCK` (HTTP 409). On success the lot's `launch_reserved_units` is reduced by the units taken from the launch pool, `on_hand_units` is reduced by the whole drawn amount, and `reserved_units` is increased by the same drawn amount.

A line whose variant is *not* a limited launch draws only from the general pool — `on_hand_units` less `launch_reserved_units` — so an ordinary shopper can never eat into stock earmarked for a launch. The same `ERR_INSUFFICIENT_STOCK` applies when the general pool cannot cover an ordinary line and `allow_partial` is false. A variant that has no lot at all at the order's store is treated exactly as a lot holding nothing: both its pools are zero, so the line either fails with `ERR_INSUFFICIENT_STOCK` or, under `allow_partial`, is clipped to a quantity of zero. A clipped line is never deleted — it stays on the order at its reduced quantity, zero included, and contributes nothing to the money.

**Points and the final price.** The buyer must actually own the points they are spending: if `points_redeemed` exceeds the customer's `points_balance`, the reservation fails with `ERR_INSUFFICIENT_POINTS` (HTTP 422). And points may not buy more than the basket is worth: if `points_value_cents` exceeds `discounted_subtotal_cents`, the reservation fails with `ERR_POINTS_EXCEED_SUBTOTAL` (HTTP 422).

When every gate has passed, the reservation commits its effects. The customer's current tier is snapshotted onto the order as `tier_at_reserve`, and it is that snapshot — not the customer's live tier — which drives this order's discount and, later, its points multiplier. The inventory lots are drawn as described, each lot's `version` incrementing. The pricing engine of §3.5 then re-runs, this time as the `FINAL` variant, over whatever quantities survived clipping. Because clipping can shrink the basket, the `FINAL` pass may see strictly less than the `PROVISIONAL` pass did, and `discounted_subtotal_cents` can drop below a gift threshold the provisional quote had cleared — in which case no gift line is created at all, from an identical request payload. This is intended.

Gift and sample lines are materialised only now. A `GWP` line — `line_type` of `GWP`, `unit_price_cents` of 0, `promotion_id` pointing at the winning promotion, `quantity` equal to that promotion's `gift_quantity` — is created only when `discounted_subtotal_cents` is at least the selected gift promotion's `threshold_cents` **and** the gifted variant has drawable stock at this store; if either condition fails, no gift line appears. "Drawable stock" here means the gift lot's *general* pool — `on_hand_units` less `launch_reserved_units`, net of whatever the sale lines of this same reservation have just taken — and it must cover the whole `gift_quantity`: a gift is never partially given, never draws on the launch earmark, and never appears at a store with no lot for the gifted variant. When the gift line is created it draws those units like any sale line, out of `on_hand_units` and into `reserved_units`. Sample lines are materialised for every eligible `SAMPLE` promotion — that is, every `ACTIVE` `SAMPLE` promotion whose `threshold_cents` is at most `discounted_subtotal_cents`, taken in `created_at` order — with `line_type` of `SAMPLE`, a zero `unit_price_cents` and the promotion's `gift_quantity`; sample lines never touch an inventory lot at all, so no stock is drawn for them and none is ever returned, and a sample promotion carrying no `gift_variant_id` materialises nothing. Finally, if `points_redeemed` is greater than zero, a ledger entry of type `REDEEM` is appended carrying the negative of that number as its `delta_points`, and the customer's `points_balance` falls by the same amount. The order's `pricing_variant` becomes `FINAL` and its `version` increments.

### 3.7. Payment, Fulfilment, Accrual — and Undoing It All

An order carries **two independent state dimensions on the same record**, and they evolve separately while guarding each other. `fulfillment_status` runs `DRAFT`, `RESERVED`, `READY_FOR_PICKUP`, `PICKED_UP`, `SHIPPED` and `CANCELLED`, with `PICKED_UP`, `SHIPPED` and `CANCELLED` terminal. `payment_status` runs `UNPAID`, `AUTHORIZED`, `CAPTURED`, `PARTIALLY_REFUNDED`, `REFUNDED` and `VOIDED`, with `REFUNDED` and `VOIDED` terminal.

The payment dimension is advanced by an `action` on the order. `AUTHORIZE` takes `payment_status` from `UNPAID` to `AUTHORIZED`, and is permitted only while `fulfillment_status` is `RESERVED`. `CAPTURE` takes `payment_status` from `AUTHORIZED` to `CAPTURED`, and is permitted while `fulfillment_status` is either `RESERVED` or `READY_FOR_PICKUP`. Each increments the order's `version`. An action attempted from a state that does not permit it is `ERR_INVALID_ORDER_STATE` (HTTP 409).

The fulfilment dimension is advanced by a `StoreAssociate`, again through an `action`. `MARK_READY` takes a `BOPIS` order from `RESERVED` to `READY_FOR_PICKUP`, and requires that payment be at least authorised — `payment_status` must be `AUTHORIZED` or `CAPTURED`. `HAND_OVER` takes a `BOPIS` order from `READY_FOR_PICKUP` to `PICKED_UP` and demands full payment: `payment_status` must be `CAPTURED`. `SHIP` takes a `SHIP_FROM_STORE` order from `RESERVED` straight to `SHIPPED`, and likewise demands `CAPTURED`. Attempting hand-over or shipment before capture is `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409). The channel is part of the state: `MARK_READY` or `HAND_OVER` on a `SHIP_FROM_STORE` order, and `SHIP` on a `BOPIS` one, are `ERR_INVALID_ORDER_STATE`. `MARK_READY` is the one fulfilment step whose payment requirement is *not* reported as `ERR_PAYMENT_NOT_CAPTURED`: an order still `UNPAID` cannot be staged, and the refusal is `ERR_INVALID_ORDER_STATE`, because being unauthorised is a state failure rather than a capture failure.

Hand-over and shipment are the same event wearing different clothes, and they carry an identical set of consequences. For every `SALE` and `GWP` line — sample lines excepted, since they never drew stock — the line's units move out of `reserved_units` and into `sold_units` on the relevant lot. The order's `fulfilled_at` is stamped with the current logical-clock instant, which is what the return window will later be measured from. The accrual calculation runs, writing `points_earned` onto the order; a ledger entry of type `EARN` is appended with that many points as its `delta_points` — unconditionally, so an order that earned nothing still leaves a zero-delta `EARN` entry behind — and the customer's `points_balance` rises by the same amount. The order's `total_due_cents` is added to both the customer's `qualifying_spend_cents` and their `lifetime_spend_cents`. And finally the tier is re-evaluated in **rolling** mode (§3.4) — so this order can promote the customer, but never demote them.

**How points are earned.** Points accrue on the cash actually paid, never on the part of the basket that points themselves bought: the earning base is the order's `total_due_cents`. That base is divided by 100 and truncated down to a whole number, giving the base points — 100 cents earns one point, and the remainder is discarded. The base points are then multiplied by the multiplier belonging to `tier_at_reserve` — one times for `INSIDER`, one-and-a-half times for `VIB`, twice for `ROUGE` — and the product is again truncated down to a whole number. Note that this is the tier the order was reserved at, *not* the tier the order itself may have just unlocked. On top of that, a skincare bonus of 50 points is added if **any** sale line on the order names a product in the `SKINCARE` category **and** that same line's `line_net_cents` is at least 5,000 cents (fifty dollars); the bonus is a flat 50 points and is awarded at most once per order, however many qualifying lines there are. Gift and sample lines have a `line_net_cents` of zero and so can never trigger it. The sum of the multiplied base points and the skincare bonus is finally capped: an order can never award more than 5,000 points, and `points_earned` is the smaller of the computed sum and that ceiling.

**Cancellation and compensation.** An order that has not reached a terminal fulfilment state — that is, one sitting in `DRAFT`, `RESERVED` or `READY_FOR_PICKUP` — may be cancelled by a `Customer` or a `StoreAssociate`, optionally with a `reason`; the `reason` is accepted and discarded, and is not persisted on the order. What that costs depends entirely on how far the order had got.

Cancelling a `DRAFT` order is free: the order goes to `CANCELLED` and its `version` increments, and nothing else moves, because a draft has never touched inventory and never redeemed a point.

Cancelling a `RESERVED` order — or one already staged at `READY_FOR_PICKUP`, which unwinds identically — must undo every effect the reservation caused, and it does so in a chain. First, the inventory is released: for each drawn lot, the drawn units come out of `reserved_units` and go back into `on_hand_units`, and `launch_reserved_units` is restored by exactly the number of units the reservation originally took from the launch pool, so the earmark is made whole rather than being quietly converted into general stock; the lot's `version` increments. Because that restoration also drops the customer's held-unit count for the limited variant, it re-opens headroom under `per_customer_cap` — the same customer can now go and try for the launch again. Next, if the order redeemed points, a ledger entry of type `REVERSAL` is appended carrying the redeemed points back as a positive `delta_points`, and, as a direct consequence, the customer's `points_balance` rises by exactly that amount, restoring the pre-order balance to the cent. Meanwhile the payment dimension is settled: an `AUTHORIZED` order moves to `VOIDED` with no cash movement, and a `CAPTURED` order moves to `REFUNDED` with the order's `refunded_cents` set to its full `total_due_cents`. An order that was never paid at all stays `UNPAID` — there is nothing to void.

### 3.8. In-Store Services: Booking, Rescheduling and Completion

An **Artist** works at a store, named by `store_id`, with a display `name`, a `status` that is `ACTIVE` by default and may be set to `INACTIVE` (an inactive artist takes no bookings), and a `skills` array listing which of `BROW` and `MAKEOVER` they are qualified to perform.

A `Customer` or a `StoreAssociate` books a service by naming the `customer_id`, the `store_id`, the `artist_id`, the `service_type` — `BROW` or `MAKEOVER` — and the UTC `start_at`. Booking an artist for a service they do not hold in `skills` is rejected as `ERR_INVALID_REQUEST`, and so — for the same reason, as a payload-shape breach rather than a state one — is booking an artist whose `status` is `INACTIVE`. The artist need not, however, work at the `store_id` being booked; that pairing is not checked. The booking's `duration_minutes` is derived, not supplied: a `BROW` runs 30 minutes and a `MAKEOVER` runs 60. A booking may optionally name a `linked_order_id`, tying it to a purchase; when supplied, that order must belong to the *same* customer and the *same* store as the booking, and a mismatch on either is rejected with `ERR_BOOKING_ORDER_MISMATCH` (HTTP 422) — though the artist's calendar is consulted first, so a request that both collides and mismatches reports `ERR_ARTIST_TIME_CONFLICT`. New bookings start at `CONFIRMED`, with `reschedule_count` at 0 and `bonus_points_awarded` at 0.

**Artist time is exclusive, with a sanitation buffer.** A booking occupies its artist from `start_at` up to but not including the instant fifteen minutes after the service ends — that is, `start_at` plus `duration_minutes` plus a fifteen-minute sanitation buffer. Two bookings for the same artist collide when those buffered windows intersect; because the window is half-open at its end, touching endpoints do *not* collide, and a booking that begins at the exact instant the previous booking's buffered window closes is accepted. A `MAKEOVER` starting at 10:00 therefore holds its artist until 11:15, and the next booking may begin at 11:15 but not at 11:14. Only bookings whose `status` is `CONFIRMED` or `RESCHEDULE_PENDING` occupy the artist; `COMPLETED`, `NO_SHOW` and `CANCELLED` bookings release the interval and no longer block anything. A collision is rejected with `ERR_ARTIST_TIME_CONFLICT` (HTTP 409), and the check runs both when a booking is first made and when a proposed new time is accepted.

**Rescheduling is a cycle.** A `Customer` may propose a new time, supplying `proposed_start_at`; the booking moves from `CONFIRMED` to `RESCHEDULE_PENDING` and records the proposal, and its `version` increments. Crucially, a booking sitting in `RESCHEDULE_PENDING` still occupies its **original** `start_at` window on the artist's calendar, not the proposed one — the artist's afternoon is not freed by a mere request. A `BeautyArtist` then accepts, which moves the booking back from `RESCHEDULE_PENDING` to `CONFIRMED`: the proposed instant is written into `start_at`, `proposed_start_at` is cleared to null, `reschedule_count` increments, and the `version` increments. Acceptance is refused with `ERR_ARTIST_TIME_CONFLICT` if the artist's occupied intervals would collide with the proposed window under the same buffered rule. A booking may be rescheduled at most twice: a proposal is only permitted while `reschedule_count` is strictly below 2, and a third attempt — when the count already stands at 2 — is rejected with `ERR_MAX_RESCHEDULES` (HTTP 409). The state gate precedes the count gate, so proposing against a booking that is not `CONFIRMED` reports `ERR_INVALID_BOOKING_STATE` even if it has also exhausted its reschedules. A proposal is not checked against the artist's calendar; the collision test waits for acceptance.

**Closing the booking.** A `BeautyArtist` closes a `CONFIRMED` booking with an `outcome`. An outcome of `COMPLETED` moves the booking to `COMPLETED`; an outcome of `NO_SHOW` moves it to `NO_SHOW`, which awards nothing and is terminal. When a booking completes and it carries a `linked_order_id`, the linked order's `payment_status` must be `CAPTURED` — otherwise the completion is rejected with `ERR_PAYMENT_NOT_CAPTURED` (HTTP 409) — and on success a service bonus of 200 points is written to `bonus_points_awarded`, a ledger entry of type `SERVICE_BONUS` is appended with a `delta_points` of positive 200, and the customer's `points_balance` rises by 200. A booking with no linked order completes with no points movement at all.

A `Customer` or a `StoreAssociate` may cancel a booking from either `CONFIRMED` or `RESCHEDULE_PENDING`. The booking becomes `CANCELLED`, and the artist's interval is released — computed, when the booking was pending a reschedule, from its original `start_at` and not from `proposed_start_at`, since that is the window it was actually holding.

### 3.9. Returns: Policy, Settlement and Hygiene Strikes

A `Customer` asks for a refund by raising a **ReturnRequest** against a single order line: they name the `order_line_id`, the `quantity` of units they wish to send back (at least one), and a `reason` drawn from `WRONG_SHADE`, `DAMAGED`, `CHANGED_MIND` and `ALLERGIC_REACTION`. The request opens in `REQUESTED` and is decided exactly once, ending either `APPROVED` or `DENIED`.

Before those policy gates comes a state gate: the order owning the line must actually have been fulfilled — its `fulfillment_status` must be `PICKED_UP` or `SHIPPED` — and a request against an order that has not got that far is refused with `ERR_INVALID_RETURN_STATE` (HTTP 409), which is what §2.9 step 7 means for return creation. Four further gates then sit in front of the request, and they are checked in this order. First, the customer's `return_privilege` must be `ACTIVE`; a customer whose privilege has been `SUSPENDED` cannot open a new request at all, and is refused with `ERR_RETURN_PRIVILEGE_SUSPENDED` (HTTP 403). Second, the line's snapshotted `hygiene_class` must not be `DIRECT_CONTACT` — a direct-contact good is never returnable, and the refusal is `ERR_HYGIENE_NON_RETURNABLE` (HTTP 422). Third, the return window must still be open: the logical clock must be no later than thirty days after the owning order's `fulfilled_at`, and a request beyond that is `ERR_RETURN_WINDOW_EXPIRED` (HTTP 422). Fourth, the units must exist to be returned: the line's `returned_quantity` plus the newly requested `quantity` must not exceed the line's original `quantity`, and an over-return is `ERR_RETURN_QUANTITY_EXCEEDS_LINE` (HTTP 422). That last check is re-run at *approval* time as well, because two requests raised against the same line can each be individually valid and jointly excessive; a denial, which gives nothing back, never re-checks it.

A `StoreAssociate` decides the request by supplying a `decision`. The two branches share nothing.

**Denial.** A `decision` of `DENY` requires a `deny_reason` — one of `HYGIENE_VIOLATION`, `NOT_AS_DESCRIBED` or `OUT_OF_POLICY` — and the request moves to `DENIED`. No cash moves, no points move, no inventory moves. But a `deny_reason` of `HYGIENE_VIOLATION` is a black mark: the customer's `hygiene_strikes` counter increments by one, and once `hygiene_strikes` stands at 3 or more, their `return_privilege` flips to `SUSPENDED` — which is exactly the gate that will refuse their next request. The other two deny reasons carry no strike.

**Approval.** A `decision` of `APPROVE` moves the request to `APPROVED` and sets off a chain of consequences that touches four different records. It is permitted only when the line's `returned_quantity` plus this request's `quantity` is at most the line's `quantity`.

The chain begins with the settlement calculation. The proportional share of the line's value is taken **on the whole line and rounded half up exactly once**: `refund_line_cents` is the line's `line_net_cents` multiplied by the returned `quantity`, divided by the line's full `quantity`, and that single quotient is rounded half up. (Rounding a per-unit price first and then multiplying by the quantity gives a different figure and is wrong.) The customer only ever paid the discounted price, so the tier discount they enjoyed must be surrendered proportionally too: the tier share to withhold is the order's `tier_discount_cents` multiplied by `refund_line_cents`, divided by the order's `subtotal_cents`, again rounded half up exactly once (and taken as 0 outright when the order's `subtotal_cents` is 0, since there is then no discount to surrender and nothing to divide by). Next comes `restocking_fee_cents`: for a line whose `hygiene_class` is `SEALED` it is 0, and for a line whose `hygiene_class` is `TESTER_APPLIED` it is ten percent of `refund_line_cents`, rounded half up. The cash actually refunded, `refund_cents`, is `refund_line_cents` less the tier share less `restocking_fee_cents`. The `points_clawback` is derived from that cash: the refunded cents are divided by 100 and truncated down to a whole number, that whole number is multiplied by the multiplier belonging to the order's `tier_at_reserve`, and the product is truncated down again. And the `disposition` is decided by hygiene: `RESTOCK` when the line is `SEALED`, `DESTROY` when it is `TESTER_APPLIED`. Each return request is settled independently — the shares of two separate requests against the same line are never re-derived from a summed base. The instant of the decision is stamped on `decided_at` from the logical clock.

Because that settlement produced a `refund_cents`, the order must absorb it: the amount is added to the order's `refunded_cents`, and the payment dimension advances off `CAPTURED`. If the order's `refunded_cents` plus this request's `refund_cents` still falls strictly short of `total_due_cents`, `payment_status` becomes `PARTIALLY_REFUNDED`. If it reaches or exceeds `total_due_cents`, `payment_status` becomes `REFUNDED` and `refunded_cents` is pinned to exactly `total_due_cents` — the order can never be refunded for more than it was charged. An order already sitting at `PARTIALLY_REFUNDED` moves on to `REFUNDED` by the same rule when a further approval settles the remainder.

Because the order absorbed a refund, the customer must give back what the refunded cash had bought them: `refund_cents` is subtracted from both `qualifying_spend_cents` and `lifetime_spend_cents`, and a ledger entry of type `CLAWBACK` is appended carrying the negative of `points_clawback` as its `delta_points`, dropping the customer's `points_balance` by the same amount.

And because the customer's qualifying spend just dropped, the tier is re-evaluated — in **rolling** mode, which means upgrades only. A refund can push a customer's `qualifying_spend_cents` back below the threshold that made them `VIB`, and they stay `VIB` regardless; only a checkpoint (§3.4) can take a tier away.

Alongside all of that, the physical units come back. The returned `quantity` leaves the lot's `sold_units`. When the `disposition` is `RESTOCK`, the same count is added to `on_hand_units`, becoming sellable again. When the `disposition` is `DESTROY`, the same count is added instead to `destroyed_units`, and it is gone. Either way the lot's totals still add up. Finally, the line's `returned_quantity` is increased by the returned `quantity`, so that any future request against that line is measured against what is left.

## 4. Endpoint Definitions

Operations that bring a new, independently addressable resource into existence — a store, a product, a variant, an inventory lot, a customer, a promotion, an order, an artist, a service booking, a return request — return `201 Created`. Every other successful operation, including every state transition, every action on an existing resource, every read and every list, returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and step any limited launches whose windows the new instant has crossed | MerchandisingAdmin |
| POST | `/stores` | Create a store | MerchandisingAdmin |
| GET | `/stores/{id}` | Read a store | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| PATCH | `/stores/{id}` | Update a store's operational posture or BOPIS slot capacity | MerchandisingAdmin |
| POST | `/products` | Create a product (SKU family) | MerchandisingAdmin |
| GET | `/products/{id}` | Read a product | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| POST | `/products/{id}/variants` | Create a shade/finish variant under a product | MerchandisingAdmin |
| GET | `/variants/{id}` | Read a variant | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| GET | `/variants` | List variants, optionally filtered by product or launch status | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| PATCH | `/variants/{id}` | Discontinue a variant, reprice it, or close its limited launch | MerchandisingAdmin |
| POST | `/shade-recommendations` | Shade finder: return the single best-ranked variant | Customer, StoreAssociate |
| POST | `/inventory-lots` | Create the inventory lot for one (store, variant) pair | MerchandisingAdmin |
| GET | `/inventory-lots/{id}` | Read an inventory lot (used to read the lot version before an OCC write) | MerchandisingAdmin, StoreAssociate |
| GET | `/inventory-lots` | List inventory lots filtered by store and/or variant | MerchandisingAdmin, StoreAssociate |
| POST | `/inventory-lots/{id}/tester-conversions` | Convert sellable units into in-store testers | StoreAssociate |
| POST | `/customers` | Create a loyalty customer, optionally seeded at a tier/points/spend position | MerchandisingAdmin |
| GET | `/customers/{id}` | Read a customer | MerchandisingAdmin, StoreAssociate, Customer |
| POST | `/customers/{id}/tier-checkpoint` | Close the loyalty cycle: re-derive the tier (downgrades allowed) and reset the cycle | MerchandisingAdmin |
| GET | `/points-ledger/{id}` | Read one points-ledger entry | MerchandisingAdmin, Customer |
| GET | `/points-ledger` | List points-ledger entries filtered by customer and/or order | MerchandisingAdmin, Customer |
| POST | `/promotions` | Create a GWP, SAMPLE or BUNDLE promotion | MerchandisingAdmin |
| GET | `/promotions/{id}` | Read a promotion | MerchandisingAdmin, StoreAssociate, Customer |
| GET | `/promotions` | List promotions, optionally filtered by gifted variant or type | MerchandisingAdmin, StoreAssociate, Customer |
| POST | `/orders` | Create a DRAFT order with its initial SALE lines and return the provisional quote | Customer, StoreAssociate |
| GET | `/orders/{id}` | Read an order | MerchandisingAdmin, StoreAssociate, Customer |
| GET | `/orders` | List orders filtered by customer, store and/or fulfilment status | MerchandisingAdmin, StoreAssociate, Customer |
| POST | `/orders/{id}/lines` | Add a SALE line to a DRAFT order and re-quote it | Customer, StoreAssociate |
| GET | `/order-lines/{id}` | Read one order line | MerchandisingAdmin, StoreAssociate, Customer |
| GET | `/order-lines` | List order lines filtered by order, variant and/or promotion | MerchandisingAdmin, StoreAssociate, Customer |
| POST | `/orders/{id}/reserve` | Reserve inventory, resolve promotions and redeem points; produces the final price | Customer, StoreAssociate |
| POST | `/orders/{id}/payments` | Advance the payment dimension: AUTHORIZE or CAPTURE | Customer, StoreAssociate |
| POST | `/orders/{id}/fulfillment` | Advance the fulfilment dimension: MARK_READY, HAND_OVER or SHIP | StoreAssociate |
| POST | `/orders/{id}/cancel` | Cancel a non-terminal order and compensate every side effect it caused | Customer, StoreAssociate |
| POST | `/artists` | Create a beauty artist at a store | MerchandisingAdmin |
| GET | `/artists/{id}` | Read an artist | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| GET | `/artists` | List artists, optionally filtered by store | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| POST | `/service-bookings` | Book a brow or makeover service, optionally linked to an order | Customer, StoreAssociate |
| GET | `/service-bookings/{id}` | Read a booking | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| GET | `/service-bookings` | List bookings filtered by customer, store, artist and/or linked order | MerchandisingAdmin, StoreAssociate, BeautyArtist, Customer |
| POST | `/service-bookings/{id}/reschedule` | Propose a new start time; the booking becomes RESCHEDULE_PENDING | Customer |
| POST | `/service-bookings/{id}/confirm` | Accept the proposed start; the booking returns to CONFIRMED | BeautyArtist |
| POST | `/service-bookings/{id}/complete` | Close the booking as COMPLETED or NO_SHOW | BeautyArtist |
| POST | `/service-bookings/{id}/cancel` | Cancel a booking and release the artist's interval | Customer, StoreAssociate |
| POST | `/return-requests` | Request a return against one order line | Customer |
| GET | `/return-requests/{id}` | Read a return request | MerchandisingAdmin, StoreAssociate, Customer |
| GET | `/return-requests` | List return requests filtered by order line and/or status | MerchandisingAdmin, StoreAssociate, Customer |
| POST | `/return-requests/{id}/decision` | Approve or deny a return request | StoreAssociate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STORE_NOT_FOUND` | 404 Not Found |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_VARIANT_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PROMOTION_NOT_FOUND` | 404 Not Found |
| `ERR_ARTIST_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_INVALID_BOOKING_STATE` | 409 Conflict |
| `ERR_INVALID_RETURN_STATE` | 409 Conflict |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_RETURN_PRIVILEGE_SUSPENDED` | 403 Forbidden |
| `ERR_HYGIENE_NON_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_TESTER_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RETURN_QUANTITY_EXCEEDS_LINE` | 422 Unprocessable Entity |
| `ERR_ARTIST_TIME_CONFLICT` | 409 Conflict |
| `ERR_PICKUP_SLOT_FULL` | 409 Conflict |
| `ERR_MAX_RESCHEDULES` | 409 Conflict |
| `ERR_BOOKING_ORDER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_STORE_NOT_ACTIVE` | 409 Conflict |
| `ERR_VARIANT_NOT_SELLABLE` | 409 Conflict |
| `ERR_LAUNCH_NOT_OPEN` | 409 Conflict |
| `ERR_LAUNCH_TIER_LOCKED` | 403 Forbidden |
| `ERR_LAUNCH_CAP_EXCEEDED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 422 Unprocessable Entity |
| `ERR_POINTS_EXCEED_SUBTOTAL` | 422 Unprocessable Entity |
| `ERR_PAYMENT_NOT_CAPTURED` | 409 Conflict |
| `ERR_NO_SHADE_MATCH` | 422 Unprocessable Entity |
| `ERR_LOT_ALREADY_EXISTS` | 409 Conflict |
| `ERR_NOT_FOUND` | 404 Not Found |

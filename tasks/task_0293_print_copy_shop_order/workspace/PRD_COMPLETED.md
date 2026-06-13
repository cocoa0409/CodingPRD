# Print & Copy Shop Order API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Print & Copy Shop Order API, a back-office and storefront platform that takes a customer print job from catalog selection all the way through to hand-off at the counter or onto a shipping carrier. A print shop is, at its heart, two systems fused together: a **pricing engine** that must quote a job, then later commit to a binding price that survives subsequent catalog edits, and a **production orchestrator** that shepherds files through preflight, customer proofing, large-format press scheduling, and finite daily capacity. The API exists to keep those two systems honest with one another — a price the customer was quoted must be the price they are invoiced, and a job promised for a given date must be one the shop can physically produce that day.

The platform serves three operational constituencies whose responsibilities barely overlap. Front-of-house staff configure the catalog, run pricing and tax, raise invoices, and complete fulfillment. Back-of-house operators run the technical pipeline — preflighting uploaded artwork, circulating proofs, booking the large-format presses, and marking work produced. Customers own their own orders end to end: they assemble line items, approve or reject proofs, confirm, pay, and may reorder a past job in a single action. Because money and physical capacity are both committed at confirm time, the system leans heavily on two safeguards: optimistic concurrency control on the order, so a confirm or cancel built on a stale view of the order is refused, and a strict separation between a line's forward-looking **estimate** and its **locked** price, so that catalog rate changes never silently re-price work a customer has already committed to.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request missing either header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly three roles, spelled `ShopStaff`, `ProductionOperator`, and `Customer`. `ShopStaff` is front-of-house: catalog and pricing configuration, press registration, invoicing, refunds, and fulfillment hand-off. `ProductionOperator` is back-of-house: preflight, proof submission, press bookings, and production. `Customer` is the end purchaser who owns their orders.

The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer`, and ownership checks on any resource that references a customer compare that resource's owning customer to `X-User-ID`. Concretely, a customer acting on an order, on a proof, or on a line must be the owner of the order in question — the order's `customer_id` must equal `X-User-ID` — and a violation is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403). The `ShopStaff` and `ProductionOperator` roles are by contrast **opaque**: when `X-User-Role` is `ShopStaff` or `ProductionOperator`, `X-User-ID` is an operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; these operators act on any shop's resources within their permission set without an ownership test.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A supplied value outside these bounds is silently clamped into range rather than rejected — a `limit` below 1 becomes 1, a `limit` above 100 becomes 100, and a negative `offset` becomes 0 — but a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION` (HTTP 400).

Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identity

Every resource in this system — shops, products, pricing tiers, finishing options, customers, orders, order lines, artworks, proofs, fulfillments, presses, press bookings, and capacity reservations — carries a system-minted `id` that is a UUID with no type prefix, used for identity only. Each resource also carries a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Timestamps are ISO 8601 in UTC with three fractional digits. The `version` begins at its initial value on creation and increments by one on every mutation of the resource; `updated_at` is refreshed to the time of that mutation. Where a computed field on a resource is recomputed and rewritten as the side effect of some operation, that rewrite is itself a mutation and likewise advances `version` and `updated_at`.

The `id` field is never supplied by the client; clients address resources by their server-assigned identifiers, and foreign-key fields (for example a line's owning order, or a product's owning shop) are supplied as input where the relevant workflow describes them.

### 2.5. Nested and Filtered Retrieval

This domain is flat: orders, lines, artworks, proofs, fulfillments, capacity reservations, and press bookings are peer resources joined by foreign-key fields rather than nested deeply in URL paths. Related resources are discovered through filtered list reads — products by `shop_id` or `category`, pricing tiers by `product_id`, finishing options by `product_id`, customers by `shop_id`, orders by `customer_id`, `shop_id`, or `reordered_from_order_id`, order lines by `order_id` or `product_id`, artworks by `order_line_id`, proofs by `order_line_id`, fulfillments by `order_id`, presses by `shop_id`, press bookings by `press_id` or `order_line_id`, and capacity reservations by `shop_id`, `order_line_id`, or `production_date`.

When a request names a resource by an identifier in its path, that identifier is validated for existence before the body is processed. When several resources are referenced, existence is checked left-to-right, and the first identifier that does not resolve produces `ERR_NOT_FOUND` (HTTP 404). This ordering applies uniformly: the resource named in the path is confirmed to exist before any body-referenced resource, and a missing body-referenced resource (an unknown `product_id` on a line, say) likewise yields `ERR_NOT_FOUND`.

### 2.6. Monetary Precision and Rounding

All money is held in integer **cents**, and all rates and discounts in **basis points** (one basis point is one part in ten thousand). Wherever a monetary computation introduces a fraction of a cent, the result is rounded **half up** to a whole cent. Rounding is applied at specific, pinned points in each calculation — never blanketed over an entire formula — and §3 states exactly where each rounding step falls, because the order of rounding versus multiplication is itself part of the contract. Where a value is an aggregate of already-rounded integer-cent terms, no further rounding is applied; the sum is exact.

### 2.7. The Two-Dimensional Order State Model

An order's lifecycle runs along two independent dimensions that evolve in parallel. The `production_status` dimension tracks physical progress through the values `DRAFT`, `CONFIRMED`, `IN_PRODUCTION`, `READY`, `FULFILLED`, and `CANCELLED`, beginning at `DRAFT`. The `payment_status` dimension tracks money through `UNPAID`, `INVOICED`, `PAID`, and `REFUNDED`, beginning at `UNPAID`. The two dimensions are not slaved to one another — an order can be `CONFIRMED` while still `UNPAID`, or `IN_PRODUCTION` while `INVOICED` — but several transitions on one dimension carry preconditions on the other, and those couplings are spelled out in §3. `FULFILLED` and `CANCELLED` are terminal for production; `REFUNDED` is terminal for payment.

### 2.8. Estimate vs. Locked Pricing

Every line carries two price figures with deliberately different semantics, and confusing them is the central hazard of the domain. The `estimate_line_cents` field is **provisional and forward-looking**: it is recomputed from the catalog rates *in force right now* every time the line is created or edited, so it tracks the latest published prices. The `final_line_cents` field is **locked**: it is null until the order is confirmed, at which point it is snapshotted from the rates in force *at that instant* and frozen onto the line. Once locked, no subsequent catalog edit changes it. The estimate is therefore what the customer sees while shopping; the locked figure is what they are billed. The two diverge precisely when a catalog rate changes between line creation and confirm, and the locked figure always wins for billing.

### 2.9. Optimistic Concurrency on the Order

Confirming and cancelling an order are the two operations that commit money and physical capacity, so both are guarded by optimistic concurrency control on the order's `version`. Each of these requests must carry `expected_order_version` as a required input field, carrying the client's last observed `version` of the target order. If the order's current `version` differs from the supplied `expected_order_version` — because, for instance, a reorder clone, a line lock, or a cancel advanced the version after the client last read the order — the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) before any line is locked or any reservation is released. This protects a client from confirming or cancelling against a view of the order it no longer holds. Endpoints other than confirm and cancel do not take a version field and perform no such check.

### 2.10. Daily Capacity and Press Scheduling as Shared Resources

Two finite physical resources are shared across orders. The first is the shop's **daily production capacity**: each shop publishes a `daily_unit_capacity`, the total number of production units it can schedule on any single production date across all held capacity reservations. The second is **press time** on the large-format presses, where bookings must not collide and each press enforces a mandatory cleanup buffer between consecutive jobs. Both resources are committed at confirm time (capacity) or at booking time (press), both are released when an order is cancelled, and the precise overlap and capacity arithmetic — including which boundary conditions are accepted versus rejected — is given in §3.

## 3. Business Logic & Workflows

### 3.1. Configuring the Shop and Catalog

A `ShopStaff` member stands up a shop before any order can flow, supplying its display `name` together with the operating parameters that drive pricing and scheduling. These include `tax_rate_bps`, the sales tax in basis points applied to the taxable subtotal (which must be between 0 and 2000 inclusive); `rush_surcharge_bps`, the surcharge in basis points applied to a rushed line's subtotal (between 0 and 10000 inclusive); and `rush_cutoff_hour_utc`, an hour-of-day in UTC from 0 to 23 that governs rush turnaround slippage. Turnaround is configured by `standard_turnaround_days`, the whole production days added for standard service (at least 1), and `rush_turnaround_days`, the whole days for rush service, which must be at least 0 and strictly fewer than `standard_turnaround_days`. Finally, `daily_unit_capacity` declares how many production units the shop can schedule per production date and must be at least 1.

The catalog is built from products. A `ShopStaff` member creates a product against a `shop_id`, giving it a `name` and a `category` that is one of `COPIES`, `BANNER`, or `BINDING`. Pricing starts from `base_unit_price_cents`, the per-unit price in cents before any tier discount or finishing surcharge (at least 0). The `unit_size` field declares how many production units each ordered quantity unit consumes — defaulting to 1, and greater than 1 for large-format banners, with a floor of 1. Three booleans shape the product's pipeline: `requires_proof` (default false) means an approved proof is required before the line may lock its price; `requires_press` (default false) means a banner line must hold a confirmed press booking before it can lock; and `active` (default true) governs whether the product may be added to new lines. A staff member may later edit a product's `base_unit_price_cents`, `name`, or `active` flag; doing so recomputes `estimate_line_cents` on every still-`OPEN` line that references the product, but — by the locking rule of §2.8 — never disturbs a `final_line_cents` already frozen on a locked line.

Two satellite catalog resources hang off a product. A **pricing tier** is created against a `product_id` with a `min_quantity` (at least 1), the inclusive lower bound of quantities it covers, and a `discount_bps` (between 0 and 10000 inclusive) struck off the base unit price for quantities at or above that bound. A **finishing option** is created against a `product_id` with a stable `code` (such as `LAMINATE`, `COIL_BIND`, or `GROMMETS`), a `surcharge_kind` that is either `PER_UNIT` or `FLAT`, and a `surcharge_cents` amount (at least 0) interpreted according to that kind.

### 3.2. Customers, Orders, and Line Assembly

A customer is registered — by `ShopStaff` or by the customer self-registering — with an `email` (nominally unique within the shop, though this uniqueness is not enforced on registration — a duplicate email is accepted without error), a `name`, and a home `shop_id`. Beyond these inputs, a customer carries four computed loyalty fields that the system maintains and that always start at their defaults: `completed_order_count` (starting at 0), `lifetime_paid_cents` (0), `loyalty_score` (0), and `loyalty_tier` (`NONE`). The tier is one of `NONE`, `SILVER`, or `GOLD`. How these evolve is the subject of §3.7.

An order is opened as a draft against a `shop_id` and a `customer_id`, either by the customer or by staff acting on their behalf; when the caller is a `Customer`, the supplied `customer_id` must equal that caller's `X-User-ID`, and an attempt to open an order for any other customer is rejected with `ERR_NOT_ORDER_OWNER` (HTTP 403). A fresh order begins with `production_status` `DRAFT` and `payment_status` `UNPAID`; its `reordered_from_order_id` is null unless the order was born from a reorder (see §3.8). All monetary roll-ups — `subtotal_cents`, `loyalty_discount_cents`, `rush_fee_cents`, `tax_cents`, and `total_cents` — start at 0 and remain so until confirm, and `promised_ready_date` is null until then.

Lines are added to a draft order; the add itself does not, however, verify the parent order's `production_status` — a line creation is admitted against an order in any production state, and no state-based rejection guards the operation. Adding a line requires the parent `order_id`, the `product_id` being ordered, and a `quantity` (at least 1); optionally the caller supplies `finishing_codes`, an array of finishing-option codes to apply (defaulting to an empty array), and a `service_level` that is either `STANDARD` or `RUSH` (defaulting to `STANDARD`). A new line begins with its `status` field set to `OPEN`; the line's lifecycle status (`OPEN`, `PREFLIGHT_OK`, `PROOF_PENDING`, `PROOF_APPROVED`, `PRICE_LOCKED`, `PRODUCED`), like the `status` field carried by proofs, fulfillments, press bookings, and capacity reservations, is system-managed and never set directly by the client. The product must be active when it is added; adding an inactive product is rejected with `ERR_PRODUCT_INACTIVE` (HTTP 409). Every entry in `finishing_codes` must name a finishing option belonging to that line's `product_id`; a stray code is rejected with `ERR_FINISHING_NOT_FOR_PRODUCT` (HTTP 422). On creation the system computes the line's `estimate_line_cents` and its `production_units`. A draft line that is still `OPEN` or `PREFLIGHT_OK` may be edited to change its `quantity`, `finishing_codes`, or `service_level`; each edit recomputes `estimate_line_cents` and `production_units`. The same finishing-belongs-to-product check guards edits as well as creation.

The provisional estimate is computed as follows. First, tier selection: among the pricing tiers for the line's product, choose the one with the greatest `min_quantity` that is still less than or equal to the line's `quantity`; if no tier qualifies, the tier discount is zero basis points. The discounted unit price is the base unit price multiplied by the quantity ten-thousand-minus-the-tier-discount-basis-points divided by ten thousand, rounded half up to a whole cent **at this step only**. That rounded discounted unit price is then multiplied by the quantity to give the base amount — rounding happens before the multiply, not after, and this round-then-multiply order is fixed. Next, finishing: for each applied finishing option, a `PER_UNIT` option contributes its surcharge in cents multiplied by the quantity, while a `FLAT` option contributes its surcharge once for the whole line; these are summed across all applied options. The estimate is the base amount plus the finishing total. The estimate carries no rush surcharge — rush is handled only at lock time and lives on the order, not in this figure. The `production_units` for a line is the quantity multiplied by the product's `unit_size`.

### 3.3. Artwork Upload and Preflight

Each line needs print-ready files. An `Artwork` record is uploaded — by staff or customer — against an `order_line_id`, carrying the `file_name`, the declared `page_count` (an integer, at least 1), the declared resolution `dpi` (an integer, at least 1), and the declared `bleed_mm` margin in millimeters (a number, at least 0, which may be fractional rather than a whole millimeter). A newly uploaded file has `preflight_status` `UPLOADED` and a null `preflight_reason`.

A `ProductionOperator` then runs preflight on an uploaded file. Preflight evaluates two minimums in a pinned order — resolution is checked before bleed. If the declared `dpi` is below 150, the file moves to `preflight_status` `FAILED` and `preflight_reason` records the DPI shortfall. Otherwise, if the declared `bleed_mm` is below 3 millimeters, the file moves to `FAILED` and `preflight_reason` records the bleed shortfall. Only when both minimums are met — resolution at least 150 and bleed at least 3 — does the file move to `PASSED` with a null `preflight_reason`. The boundary is inclusive of the minimum: a file at exactly 150 DPI passes the resolution check, and one at 149 fails it. Because DPI is evaluated first, a file failing both checks reports the DPI reason. Running preflight on a file that is not in `UPLOADED` is rejected as an invalid state with `ERR_INVALID_STATE` (HTTP 409).

When preflight passes, the line the artwork belongs to advances from `OPEN` to `PREFLIGHT_OK`. A failed file is not a dead end: the customer who owns it may revise the declared `page_count`, `dpi`, or `bleed_mm`, which returns the file from `FAILED` to `UPLOADED` and clears `preflight_reason` so the operator can re-run preflight against the new specs.

### 3.4. Proofing

Some products demand a customer sign-off on a visual proof before their price is allowed to lock; this is exactly the set of products whose `requires_proof` is true. For such a line, once it is `PREFLIGHT_OK`, a `ProductionOperator` submits a proof, which creates a `Proof` against the line's `order_line_id` in status `SUBMITTED` with `round_number` 1, and advances the line from `PREFLIGHT_OK` to `PROOF_PENDING`. Submitting a proof for a line whose product does not require one is rejected with `ERR_PROOF_NOT_REQUIRED` (HTTP 409); submitting against a line not in `PREFLIGHT_OK` is an invalid-state rejection.

The proof then sits with the owning customer, who makes one of two decisions. Approving the proof moves it from `SUBMITTED` to `APPROVED` and advances the line from `PROOF_PENDING` to `PROOF_APPROVED`. Requesting changes requires a `change_note` describing what to fix; a request-changes call with no `change_note` is rejected with `ERR_CHANGE_NOTE_REQUIRED` (HTTP 422). A valid request-changes moves the proof from `SUBMITTED` to `CHANGES_REQUESTED` and reopens the line, reverting it from `PROOF_PENDING` back to `PREFLIGHT_OK` so a fresh round can begin. Because these are customer decisions on the customer's own line, a caller who is not the order's owner is rejected with `ERR_NOT_ORDER_OWNER`.

The cycle continues across rounds. After changes were requested, the operator submits the next round against the same `PREFLIGHT_OK` line; this creates a new proof whose `round_number` is one greater than the prior proof's, in status `SUBMITTED`, and drives the line back to `PROOF_PENDING`. The prior `CHANGES_REQUESTED` proof is left in place as a closed record. Proofing thus oscillates between `SUBMITTED` and `CHANGES_REQUESTED` until the customer approves, at which point the line is `PROOF_APPROVED` and ready to lock.

### 3.5. Press Booking for Large-Format Work

Banner products printed on the large-format presses set `requires_press`, meaning the line must hold a confirmed press booking before its price can lock. A `ProductionOperator` first registers a press against a `shop_id` with a `name` and an optional `cleanup_buffer_minutes` (default 0, at least 0) — the mandatory idle period required *after* each booking before the next job may start on that press. The operator then books press time for a banner line by supplying the `press_id`, the line's `order_line_id`, and a half-open interval defined by `start_utc` and `end_utc` (both ISO 8601 UTC). The booking's `end_utc` must be strictly later than its `start_utc`; an interval that is empty or inverted is rejected with `ERR_BOOKING_INTERVAL_INVALID` (HTTP 422). A successful booking is `CONFIRMED`.

Bookings on the same press may not collide once the cleanup buffer is accounted for. An existing confirmed booking occupies its own interval extended at the tail by the press's cleanup buffer — that is, from its `start_utc` up to but not including its `end_utc` plus the cleanup-buffer minutes. The new booking, running from its `start_utc` up to but not including its `end_utc`, conflicts if and only if the new booking's `start_utc` is earlier than that buffer-extended end of the existing booking and the existing booking's `start_utc` is earlier than the new booking's `end_utc`. A conflict is rejected with `ERR_PRESS_DOUBLE_BOOKED` (HTTP 409). The arithmetic is at minute resolution and the buffer edge is treated as available: a new booking whose `start_utc` lands exactly on the existing booking's `end_utc` plus cleanup buffer is accepted, because the occupied window is half-open at that extended tail. A confirmed booking can be released by an operator, moving it from `CONFIRMED` to `RELEASED` and freeing the slot — including the trailing buffer — for reuse.

### 3.6. Confirming the Order: Locking, Scheduling, and Totals

Confirmation is the pivot of the whole workflow and is performed by the owning customer. It is the moment provisional becomes binding: prices lock, capacity is reserved, promised dates are computed, and totals are struck. A confirm is only entertained if a battery of preconditions holds. The order must have at least one line, and an order carrying no lines is itself rejected with `ERR_LINE_NOT_LOCKABLE` (HTTP 409). Every line must be price-lockable — meaning a line whose product requires a proof must be `PROOF_APPROVED`, and a line whose product does not require a proof must be `PREFLIGHT_OK` — and additionally every line whose product requires a press must already hold a confirmed press booking; if any line falls short, the confirm is rejected with `ERR_LINE_NOT_LOCKABLE` (HTTP 409). A fulfillment must already exist for the order, or the confirm is rejected with `ERR_FULFILLMENT_REQUIRED` (HTTP 409). And the supplied `expected_order_version` must match the order's current `version` per §2.9, failing which the confirm is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) before anything is committed.

When the preconditions hold, confirmation runs as one transaction. Each line transitions to `PRICE_LOCKED`. At that lock, each line's `final_line_cents` is snapshotted using the very same tier-and-finishing arithmetic as the estimate (the tier selection, the round-half-up at the discounted-unit step, the round-then-multiply by quantity, and the per-unit-versus-flat finishing sum of §3.2) but evaluated against the rates in force at the lock instant and then frozen. The rush surcharge is captured separately at lock onto each line's `rush_surcharge_cents`: for a `RUSH` line it is the locked `final_line_cents` multiplied by the shop's `rush_surcharge_bps` divided by ten thousand, rounded half up to a whole cent; for a `STANDARD` line it is 0. Note that `final_line_cents` itself excludes rush — the rush amount is carried separately and rolled into the order, not into the line's locked print price. Each line's `production_units` (quantity times the product's `unit_size`) is settled at this point as well.

With the lines locked, the order's money is assembled in a pinned order. The `subtotal_cents` is the sum of the locked `final_line_cents` across all the order's lines; because each line figure is already a whole-cent integer, this sum is exact and is not re-rounded. The `loyalty_discount_cents` is then struck against that subtotal using the customer's **committed** `loyalty_tier` as it stands going into this confirm — not recomputed here: a `NONE` tier yields no discount, a `SILVER` tier yields the subtotal times 500 basis points (5%), and a `GOLD` tier yields the subtotal times 1000 basis points (10%), each rounded half up to a whole cent. Next the `rush_fee_cents` is the sum of every line's captured `rush_surcharge_cents`. The taxable base is the `subtotal_cents` minus the `loyalty_discount_cents` — rush is deliberately not taxed. The `tax_cents` is that taxable base multiplied by the shop's `tax_rate_bps` divided by ten thousand, rounded half up to a whole cent; this is the only rounding step in the order roll-up beyond the per-line work already done. Finally the `total_cents` is the taxable base plus the `rush_fee_cents` plus the `tax_cents` plus the order's fulfillment shipping fee — the `ship_fee_cents` of the order's fulfillment, taken from the earliest-created fulfillment should more than one exist (which is 0 for a pickup). Confirmation advances `production_status` from `DRAFT` to `CONFIRMED` and increments the order's `version`.

Promised dates are computed at confirm from a fixed clock anchor — the current UTC instant the system is operating against. For each line, take the calendar date of that instant. A `STANDARD` line is promised that date plus the shop's `standard_turnaround_days` whole production days. A `RUSH` line starts from that date plus the shop's `rush_turnaround_days` whole days, and then slips one further production day if the confirm happened at or after the shop's `rush_cutoff_hour_utc` — the comparison is inclusive, so a confirm landing exactly on the cutoff hour incurs the slip. Each line's resulting date is written to its `promised_ready_date`, and the order's `promised_ready_date` is the latest such date across all its lines.

As the final act of confirmation, the system reserves daily capacity for each line. For every line it creates a capacity reservation in status `HELD` against the shop, the line's `order_line_id`, the line's computed `promised_ready_date` as the `production_date`, and a `units` count equal to the line's `production_units`. Before each reservation is admitted, the day's load is checked: sum the `units` of all `HELD` reservations already standing for that shop on that production date, add the line's requested production units, and reject if that running total would exceed the shop's `daily_unit_capacity`. The boundary is strict-greater: a day filled exactly to capacity is allowed, and only the unit that would push it past capacity triggers `ERR_CAPACITY_EXCEEDED` (HTTP 409).

### 3.7. Fulfillment, Payment, Production, and Loyalty Settlement

Before an order can be confirmed it needs a fulfillment, and a fulfillment is scheduled against an `order_id` with a `method` of either `PICKUP` or `SHIP`. A `SHIP` fulfillment requires a `ship_address` and a `ship_fee_cents` strictly greater than 0; a `PICKUP` fulfillment must carry no address and a `ship_fee_cents` of 0. A fulfillment that violates these field rules — a ship with no address or no fee, or a pickup carrying an address or a non-zero fee — is rejected with `ERR_FULFILLMENT_FIELDS_INVALID` (HTTP 422). A new fulfillment is `SCHEDULED`.

The payment dimension runs alongside production. A `ShopStaff` member invoices a confirmed order — permitted while `production_status` is `CONFIRMED` or `IN_PRODUCTION` and only when `total_cents` is greater than 0 — moving `payment_status` from `UNPAID` to `INVOICED`. The owning customer then pays, supplying an `amount_cents` that must equal the order's `total_cents` exactly; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A successful payment moves `payment_status` from `INVOICED` to `PAID` and adds the order's `total_cents` to the customer's `lifetime_paid_cents`.

On the production side, a `ProductionOperator` starts production on a confirmed order, which is permitted only when `production_status` is `CONFIRMED` and `payment_status` is one of `INVOICED` or `PAID`; this advances `production_status` from `CONFIRMED` to `IN_PRODUCTION`. The operator marks each locked line produced once the order is in production and the line is `PRICE_LOCKED`, advancing that line from `PRICE_LOCKED` to `PRODUCED`. When the last line of the order reaches `PRODUCED`, the order bubbles up automatically from `IN_PRODUCTION` to `READY`.

Hand-off closes the loop. A `ShopStaff` member hands off a fulfillment, permitted only when the order's `production_status` is `READY` and its `payment_status` is `PAID`. Hand-off moves the fulfillment from `SCHEDULED` to `HANDED_OFF` and drives the order's `production_status` from `READY` to `FULFILLED`. It then settles loyalty: the customer's `completed_order_count` is incremented by one, and the customer's committed `loyalty_score` and `loyalty_tier` are recomputed from realized history. That committed score is a weighted blend — the `completed_order_count` weighted by 1.0 plus the `lifetime_paid_cents` (converted to dollars by dividing by ten thousand) weighted by 0.5 — rounded half up to one decimal place. The tier follows from the score with inclusive thresholds: `GOLD` when the score is at least 6.0, `SILVER` when it is at least 3.0 but below 6.0, and `NONE` otherwise. This committed tier is the one the *next* order's loyalty discount keys on; it is not the same as the provisional preview described below.

A customer or staff member may request a **loyalty preview** for a customer, which projects the score forward as if the customer's confirmed-but-not-yet-fulfilled orders had already completed. Concretely, the projection starts from the customer's committed `completed_order_count` and committed `lifetime_paid_cents`, then folds in each of that customer's orders whose `production_status` is `CONFIRMED`, `IN_PRODUCTION`, or `READY` (orders in `DRAFT`, `CANCELLED`, or already `FULFILLED` are not folded in): each such order adds one to the projected `completed_order_count`, and — only when that order's `payment_status` is not yet `PAID`, since a `PAID` order's spend is already realized into the committed `lifetime_paid_cents` — adds the order's `total_cents` to the projected `lifetime_paid_cents`. The `projected_loyalty_score` and `projected_loyalty_tier` are then derived from those projected figures using the very same weighted-blend score formula and inclusive tier thresholds defined above for the committed score. The preview returns the `projected_loyalty_score` and `projected_loyalty_tier`, alongside the `committed_loyalty_score` as it stands today. The preview is informational only — it is shown to the customer but is never used to compute an actual discount, which always uses the committed tier.

### 3.8. Reorder, Cancellation, and Refund

A customer (or staff on their behalf) may reorder a past order, cloning it into a fresh draft for the same customer. The reorder carries `expected_order_version` for the source order as a required input field, but — unlike confirm and cancel — it performs no optimistic-concurrency check against it: the value is accepted and ignored, and a reorder is never rejected with `ERR_STALE_ORDER_VERSION` even when the supplied version does not match the source order's current `version`. It creates a new order whose `reordered_from_order_id` points at the source, in `production_status` `DRAFT`, and clones each source line's `product_id`, `quantity`, `finishing_codes`, and `service_level` into fresh `OPEN` lines on the new order — recomputing each cloned line's `estimate_line_cents` and `production_units` from the catalog rates in force at clone time. The product-active guard of §3.2 is not re-applied during this cloning: a source line referencing a product that has since gone inactive is still cloned, without an `ERR_PRODUCT_INACTIVE` rejection. The act of reordering also increments the source order's `version` — which is one of the ways a later confirm or cancel on that source can find its `expected_order_version` stale.

Cancellation is available to the owning customer while the order's `production_status` is `DRAFT` or `CONFIRMED`, and like confirm it carries `expected_order_version`, which must match the order's current `version` or the cancel is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412). This OCC guard matters most for a `CONFIRMED` order: if the order was confirmed — version bumped, reservations held — after the client last read it, the client's intended cancel cascade would be based on a stale view, which the version check refuses. A successful cancel moves `production_status` to `CANCELLED` and cascades two releases: every `HELD` capacity reservation for the order's lines moves to `RELEASED`, returning its units to the shop's daily pool for that production date, and every `CONFIRMED` press booking for the order's lines moves to `RELEASED`, freeing each slot and its trailing buffer on the press. Cancellation increments the order's `version`.

Finally, a paid order that has been cancelled may be refunded by a `ShopStaff` member. A refund is permitted only when `payment_status` is `PAID` and `production_status` is `CANCELLED`. It moves `payment_status` from `PAID` to `REFUNDED` and, as a compensating action, reduces the customer's `lifetime_paid_cents` by the order's `total_cents`, restoring it to its pre-payment value.

### 3.9. Validation Precedence and Test-Driving Hooks

When several checks could fire on one request, they are evaluated in a fixed precedence so that the reported error is deterministic. Authentication comes first: a missing `X-User-ID` or `X-User-Role` yields `ERR_UNAUTHENTICATED` before anything else. Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE`. Resource existence comes third — every path- and body-referenced resource is resolved left-to-right, yielding `ERR_NOT_FOUND` for the first that is missing. Ownership comes fourth: a customer acting on an order, proof, or line they do not own yields `ERR_NOT_ORDER_OWNER`. State validity comes fifth, yielding `ERR_INVALID_STATE` when a target is not in a state that permits the requested transition. The order-version OCC check comes sixth on confirm and cancel, yielding `ERR_STALE_ORDER_VERSION`. Only past that point do the operation-specific business checks run — finishing-belongs-to-product (`ERR_FINISHING_NOT_FOR_PRODUCT`), product-active (`ERR_PRODUCT_INACTIVE`), line-lockable (`ERR_LINE_NOT_LOCKABLE`), fulfillment-exists (`ERR_FULFILLMENT_REQUIRED`), fulfillment-fields (`ERR_FULFILLMENT_FIELDS_INVALID`), press overlap (`ERR_PRESS_DOUBLE_BOOKED`), booking interval (`ERR_BOOKING_INTERVAL_INVALID`), capacity (`ERR_CAPACITY_EXCEEDED`), and payment amount (`ERR_PAYMENT_AMOUNT_MISMATCH`) — each at the operation where §3 introduces it. A malformed request or a missing required body field is rejected with `ERR_VALIDATION` (HTTP 400).

Two administrative capabilities exist purely to make turnaround, rush-cutoff, and loyalty behavior deterministic under test, and both are restricted to `ShopStaff`. A clock-pinning capability sets the system's current UTC instant to a supplied `to_iso8601` value (stored verbatim and echoed back unchanged) and returns it as the new `current_utc`; the pinned instant governs the confirm-time promised-date and rush-cutoff arithmetic until it is changed, which is what lets that arithmetic be exercised precisely. The pin does not, however, reach the system-minted `created_at`/`updated_at` resource timestamps or the envelope's `api_request_timestamp`, which continue to read the real wall clock regardless of any pin. A loyalty-injection capability sets a customer's committed loyalty fields directly — given a `customer_id`, it writes the supplied `completed_order_count`, `lifetime_paid_cents`, `loyalty_score`, and `loyalty_tier` onto the customer — so a loyalty-dependent scenario need not replay several full order lifecycles to hand-off in its setup.

## 4. Endpoint Definitions

Endpoints that create a new, standalone resource return `201 Created`. Endpoints that modify an existing resource — including state transitions and the administrative hooks — return `200 OK`. The request body, computed response, and side effects of each endpoint are not repeated here; they are reconstructed from the §3 narratives.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/shops` | Create a shop (pricing/tax/turnaround/capacity config) | ShopStaff |
| GET | `/shops/{shop_id}` | Read a shop | ShopStaff, ProductionOperator, Customer |
| POST | `/products` | Create a catalog product | ShopStaff |
| GET | `/products` | List products; filter by shop | ShopStaff, ProductionOperator, Customer |
| GET | `/products/{product_id}` | Read a product | ShopStaff, ProductionOperator, Customer |
| PATCH | `/products/{product_id}` | Edit catalog product (price, active) | ShopStaff |
| POST | `/pricing-tiers` | Create a volume pricing tier for a product | ShopStaff |
| GET | `/pricing-tiers` | List pricing tiers; filter by product | ShopStaff, ProductionOperator, Customer |
| GET | `/pricing-tiers/{pricing_tier_id}` | Read a pricing tier | ShopStaff, ProductionOperator, Customer |
| POST | `/finishing-options` | Create a finishing add-on for a product | ShopStaff |
| GET | `/finishing-options` | List finishing options; filter by product | ShopStaff, ProductionOperator, Customer |
| GET | `/finishing-options/{finishing_option_id}` | Read a finishing option | ShopStaff, ProductionOperator, Customer |
| POST | `/presses` | Register a large-format press | ShopStaff |
| GET | `/presses` | List presses; filter by shop | ShopStaff, ProductionOperator, Customer |
| GET | `/presses/{press_id}` | Read a press | ShopStaff, ProductionOperator, Customer |
| POST | `/customers` | Register a customer | ShopStaff, Customer |
| GET | `/customers` | List customers; filter by shop | ShopStaff |
| GET | `/customers/{customer_id}` | Read a customer (committed loyalty) | ShopStaff, Customer |
| GET | `/customers/{customer_id}/loyalty-preview` | Provisional forward-looking loyalty preview | ShopStaff, Customer |
| POST | `/orders` | Create a draft order | ShopStaff, Customer |
| GET | `/orders` | List orders; filter by customer/shop/reorder source | ShopStaff, ProductionOperator, Customer |
| GET | `/orders/{order_id}` | Read an order (computed totals, both status dimensions) | ShopStaff, ProductionOperator, Customer |
| POST | `/orders/{order_id}/reorder` | Clone an order's lines into a new draft order | ShopStaff, Customer |
| POST | `/orders/{order_id}/confirm` | Confirm order: lock prices, schedule capacity, compute totals | Customer |
| POST | `/orders/{order_id}/cancel` | Cancel a draft/confirmed order; release reservations and bookings | Customer |
| POST | `/orders/{order_id}/start-production` | Move a confirmed+invoiced order into production | ProductionOperator |
| POST | `/orders/{order_id}/invoice` | Invoice a confirmed order | ShopStaff |
| POST | `/orders/{order_id}/pay` | Customer pays the invoiced total | Customer |
| POST | `/orders/{order_id}/refund` | Refund a paid+cancelled order | ShopStaff |
| POST | `/order-lines` | Add a line to a draft order | ShopStaff, Customer |
| GET | `/order-lines` | List order lines; filter by order or product | ShopStaff, ProductionOperator, Customer |
| GET | `/order-lines/{order_line_id}` | Read an order line | ShopStaff, ProductionOperator, Customer |
| PATCH | `/order-lines/{order_line_id}` | Edit a draft line's quantity/finishing/service level | ShopStaff, Customer |
| POST | `/order-lines/{order_line_id}/produce` | Mark a price-locked line produced | ProductionOperator |
| POST | `/artworks` | Upload artwork for an order line | ShopStaff, Customer |
| GET | `/artworks` | List artworks; filter by order line | ShopStaff, ProductionOperator, Customer |
| GET | `/artworks/{artwork_id}` | Read an artwork (preflight status/reason) | ShopStaff, ProductionOperator, Customer |
| PATCH | `/artworks/{artwork_id}` | Revise declared specs of a failed artwork | Customer |
| POST | `/artworks/{artwork_id}/preflight` | Run preflight on an uploaded artwork | ProductionOperator |
| POST | `/proofs` | Submit a proof round for a preflight-ok line | ProductionOperator |
| GET | `/proofs` | List proofs; filter by order line | ShopStaff, ProductionOperator, Customer |
| GET | `/proofs/{proof_id}` | Read a proof | ShopStaff, ProductionOperator, Customer |
| POST | `/proofs/{proof_id}/approve` | Customer approves a submitted proof | Customer |
| POST | `/proofs/{proof_id}/request-changes` | Customer requests changes on a submitted proof | Customer |
| POST | `/fulfillments` | Schedule pickup or shipment for an order | ShopStaff, Customer |
| GET | `/fulfillments` | List fulfillments; filter by order | ShopStaff, ProductionOperator, Customer |
| GET | `/fulfillments/{fulfillment_id}` | Read a fulfillment | ShopStaff, ProductionOperator, Customer |
| POST | `/fulfillments/{fulfillment_id}/hand-off` | Hand off a ready+paid order; marks order fulfilled | ShopStaff |
| POST | `/press-bookings` | Book press time for a banner line | ProductionOperator |
| GET | `/press-bookings` | List press bookings; filter by press or order line | ShopStaff, ProductionOperator, Customer |
| GET | `/press-bookings/{press_booking_id}` | Read a press booking | ShopStaff, ProductionOperator, Customer |
| POST | `/press-bookings/{press_booking_id}/release` | Release a confirmed press booking | ProductionOperator |
| GET | `/capacity-reservations` | List capacity reservations; filter by shop/line/date | ShopStaff, ProductionOperator |
| GET | `/capacity-reservations/{capacity_reservation_id}` | Read a capacity reservation | ShopStaff, ProductionOperator |
| POST | `/_clock/set_current_utc` | Pin the system clock for deterministic turnaround tests | ShopStaff |
| POST | `/_inject/customer-loyalty` | Directly set a customer's committed loyalty fields | ShopStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_NOT_ORDER_OWNER` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_ORDER_VERSION` | 412 |
| `ERR_VALIDATION` | 400 |
| `ERR_FINISHING_NOT_FOR_PRODUCT` | 422 |
| `ERR_PRODUCT_INACTIVE` | 409 |
| `ERR_LINE_NOT_LOCKABLE` | 409 |
| `ERR_FULFILLMENT_REQUIRED` | 409 |
| `ERR_FULFILLMENT_FIELDS_INVALID` | 422 |
| `ERR_PRESS_DOUBLE_BOOKED` | 409 |
| `ERR_BOOKING_INTERVAL_INVALID` | 422 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 |
| `ERR_PROOF_NOT_REQUIRED` | 409 |
| `ERR_CHANGE_NOTE_REQUIRED` | 422 |

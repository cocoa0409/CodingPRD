# School Fundraising Booster API — Product Requirements Document

## 1. Introduction

School booster organizations — PTOs, PTAs, and athletic boosters — run seasonal fundraising drives that look deceptively simple from the outside but carry real money and real accountability. A drive might be a catalog sale (students sell wrapping paper, cookie dough, or spirit wear), a pledge event (a read-a-thon or fun-run where donors promise money per lap or per book), or a one-off event with no per-student catalog at all. Across all three styles, the same hard questions recur: how much has actually been collected versus merely promised, which student earned which prize, how much of the gross belongs to the school once the vendor takes its cut, and when can the treasurer safely cut a check.

This API is the system of record for that entire arc. It models a campaign as the aggregate root and hangs sellers, products, orders, pledges, prize tiers, volunteers, shifts, and the final disbursement off it. The platform deliberately separates two financial views — a **forward-looking forecast** that counts everything in flight, and a **settled final** view that counts only money that has truly landed — because a booster officer planning prizes and a treasurer reconciling the books need different truths from the same data. It enforces a strict separation of duties between the officer who runs the drive and the treasurer who closes the books, guards against double-spending of catalog stock and double-booking of volunteers, and pins every monetary calculation to an exact, reproducible order of operations so that two honest implementations of these rules arrive at the same cent.

The remainder of this document specifies the global contract every endpoint honors (Section 2) and then walks the business workflows in narrative form (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply across the entire API. The whole API is mounted under the `/fundraising` path prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_UNAUTHENTICATED`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `CampaignAdmin`, `Seller`, `Treasurer`, and `SchoolOfficial`.

A `CampaignAdmin` is the booster, PTO, or PTA officer who builds and runs the program — creating campaigns, sellers, products, prize tiers, orders, pledges, volunteers, and shifts, and driving the campaign posture lifecycle up to and including closing it. The `CampaignAdmin` is deliberately segregated from the money-settlement duties. When `X-User-Role` is `CampaignAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and act on it but does not compare it to any entity's `id`.

A `Treasurer` is the school or booster treasurer who reconciles settled money and records disbursements — the profit split and vendor reconciliation. The `Treasurer` is segregated from the `CampaignAdmin`'s lifecycle operations. When `X-User-Role` is `Treasurer`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded if useful but never matched to an entity's `id`.

A `SchoolOfficial` is a school administrator with read-only oversight — campaign reports, seller credit, prize tiers, volunteers, shifts, and disbursements. When `X-User-Role` is `SchoolOfficial`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity.

A `Seller` is a student or parent acting through their personal share link. When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting `Seller` entity; ownership checks compare a resource's seller foreign key to `X-User-ID`. A `Seller` may place an order or create a pledge only when crediting themselves — that is, the `seller_id` in the request body must equal `X-User-ID` — and may read back only their own order or pledge. An attempt by a `Seller` to act on another seller's order or pledge is an `ERR_FORBIDDEN` rejection.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set, and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order.

Each list response includes four pagination fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every entity in the system carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC value with three fractional digits. The primary resources — `Campaign`, `PrizeTier`, `Seller`, `Product`, `Order`, `Pledge`, `Volunteer`, `VolunteerShift`, and `Disbursement` — additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `updated_at` field is refreshed on every mutation to the resource, and `version` is a monotonically increasing integer that begins at 1 on creation and increments by one on every mutation. The `version` field is the basis for optimistic concurrency control described in Section 2.7.

Whenever the server changes any persisted field of a resource — whether at the client's direct request or as an automatic downstream consequence of another operation — that counts as a mutation: the resource's `updated_at` is refreshed and its `version` increments. When a single request fans out to touch several resources (for example, closing a campaign that in turn cancels orders and releases reservations), each affected resource independently records its own mutation.

### 2.5. Computed Roll-Ups and Recompute-on-Read

Several fields are not stored as authored input but are derived from the current state of related records. On a `Campaign`, the fields `gross_collected_cents`, `forecast_gross_cents`, `school_profit_cents`, and `vendor_payable_cents` are computed. On a `Seller`, `credited_cents` and `earned_prize_tier_id` are computed. On a `Product`, `reserved_qty` is computed. On a `Volunteer`, `committed_minutes` is computed. On an `Order`, `gross_cents`, `tax_cents`, and `total_charged_cents` are computed at creation and stored. On a `Pledge`, `pledged_amount_cents` is computed.

Where an endpoint description says a field is recomputed on read, the server recalculates it fresh from the live source records at the moment the resource is fetched, rather than returning a stale cached figure. In particular, fetching a campaign or its report recomputes `gross_collected_cents` and `forecast_gross_cents`; fetching a seller recomputes `credited_cents` and `earned_prize_tier_id`; fetching a product (singly or in a list) recomputes `reserved_qty`; and fetching a volunteer recomputes `committed_minutes`. The `school_profit_cents` and `vendor_payable_cents` fields are an exception to live recomputation: they are zero until the campaign is reconciled, at which point they are frozen onto the campaign as a snapshot (see Section 3.7) and do not move thereafter.

### 2.6. Nested and Referential Validation Ordering

The system validates a request through a fixed precedence ladder so that errors surface in a predictable order. Authentication is checked first: a missing or malformed `X-User-ID` / `X-User-Role` header yields `ERR_UNAUTHENTICATED`. Authorization is checked second: a role not permitted for the operation — including a `Seller` whose `X-User-ID` does not match the body `seller_id` on an order or pledge create — yields `ERR_FORBIDDEN`. Existence of path resources is checked third: when a campaign, order, pledge, seller, product, shift, volunteer, prize-tier, or disbursement named in the URL path does not exist, the request is rejected with `ERR_NOT_FOUND`. Referential existence of body foreign keys is checked fourth: when a `campaign_id`, `seller_id`, `product_id`, or `volunteer_id` supplied in the body either does not exist or does not belong to the named campaign, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Request-body shape is checked fifth, as described in Section 2.8, yielding `ERR_INVALID_REQUEST`.

Only after these five gates pass does the request reach the state-and-business layer: the optimistic-concurrency check (Section 2.7), then state-transition legality, then the campaign-posture gate, then the seller-block guard, then domain-specific safety and uniqueness checks. The relative ordering of those later checks is detailed in Section 2.9 and woven through the Section 3 workflows.

### 2.7. Optimistic Concurrency Control on Reconciliation and Disbursement

Two campaign operations are protected by optimistic concurrency control against the `Campaign` aggregate's `version`: reconciling a campaign and disbursing a reconciled campaign. Both require a non-optional input field, `expected_campaign_version`, carrying the `version` of the campaign the client last observed.

When reconciling a campaign, the request must carry `expected_campaign_version` equal to the target campaign's current `version`. A closed campaign can legitimately accept a late refund or a late pledge collection that bumps its `version` and shifts its gross totals; if the client's `expected_campaign_version` was read before such a mutation, it no longer matches, and the reconcile is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412) rather than snapshotting a profit split over data the client never saw.

Likewise, when disbursing a campaign, the request must carry `expected_campaign_version` equal to the campaign's current `version`. Because the reconcile step itself increments the campaign `version`, a disburse request whose `expected_campaign_version` predates the reconcile would be paying out a view the client never confirmed; it is rejected with `ERR_STALE_CAMPAIGN_VERSION` (HTTP 412). No other endpoint in the system takes a version field, and none other applies this stale-version check.

### 2.8. Request Shape and Field Constraints

A create or update request must present a well-formed body or be rejected with `ERR_INVALID_REQUEST` (HTTP 422). All required fields must be present, every enumerated field must carry a legal value, and every cents-denominated amount must be non-negative. Specific shape rules: a campaign's `goal_cents` must be at least 1; its `profit_split_pct` must be greater than 0 and at most 1, expressed to two decimal places; and its `ends_at` must be strictly after its `starts_at`. A prize tier's `threshold_cents` must be at least 1. A product's `unit_price_cents` must be at least 1, its `unit_cost_cents` must be at least 0 and no greater than its `unit_price_cents`, and its `stock_qty` must be at least 0. An order's `lines` array must be non-empty, and every line's quantity must be at least 1. A pledge's `per_unit_cents`, `flat_cents`, and `cap_cents` must each be at least 0. A shift's `ends_at` must be strictly after its `starts_at`, and its `setup_buffer_minutes` must be at least 0.

### 2.9. Posture Gating, State Legality, and the Order of Business Checks

Beyond shape and existence, an operation must pass three layered business gates, evaluated in a fixed order. First comes state-transition legality: a transition endpoint requires its target resource to currently sit in a state from which the requested transition is defined (Section 3 details each state machine); otherwise the request is rejected with `ERR_INVALID_STATE` (HTTP 409). This same code covers attempts to reconcile a campaign that is not yet closed, to disburse a campaign that is not yet reconciled, and to disburse a campaign a second time. Note that the optimistic-concurrency check of Section 2.7 is evaluated before this state-legality check on the reconcile and disburse operations.

Second comes the **campaign-posture gate**: a campaign in `DRAFT` posture blocks the creation and transition of all of its children, and a campaign in `FROZEN` posture blocks every forward-progress child transition. A child operation barred by the current posture is rejected with `ERR_CAMPAIGN_NOT_ACTIVE` (HTTP 409).

Third comes the **seller-block guard**: a revenue-affecting transition whose crediting seller is `BLOCKED` is rejected with `ERR_SELLER_BLOCKED` (HTTP 409). This guard applies to exactly three operations — paying an order, recording a pledge, and collecting a pledge.

Within a single create or transition, these checks compose with the domain-specific guards — stock sufficiency, shift overlap, key uniqueness, and the paid-order-cancellation bar — each of which is described alongside the workflow it protects. When multiple guards could fire on one request, the precedence is: authentication, authorization, path existence, reference existence, body shape, optimistic concurrency, state legality, posture gate, seller-block guard, and then the remaining domain guards.

### 2.10. Monetary Precision and Rounding

All monetary amounts in this system are integer cents; there are no fractional-cent fields and no floating-point money. Aggregations of money — summing settled orders, summing collected pledges, summing line products — are exact integer arithmetic with no rounding, because every input is already a whole number of cents.

Rounding enters in exactly two computations, and in both the rounding is applied once, using the round-half-up convention. The first is sales tax on an order: the tax is computed on the order-level gross and rounded once to a whole number of cents. The second is the school's profit at reconciliation: the school's share of the split base is rounded once to a whole number of cents, and the vendor's payable then absorbs the exact residual so that no cent is created or lost. Both are detailed in Section 3.

### 2.11. The Logical Clock

The server runs on a logical clock rather than wall-clock time, so that time-dependent behavior is reproducible. On startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it stays at that default and never falls back to real wall-clock time. An administrative test-driving capability advances the clock to a supplied instant via the `to_iso8601` field; this is available to a `CampaignAdmin` or a `Treasurer`. The `reconciled_at` timestamp written when a campaign reconciles is taken from this logical clock.

## 3. Business Logic & Workflows

### 3.1. Building and Opening a Campaign

The aggregate root of the system is the **Campaign**, created by a `CampaignAdmin`. A new campaign is authored with a human-readable `name`, a `campaign_type`, a fundraising `goal_cents`, a `profit_split_pct`, a `vendor_name` of record for later reconciliation, and a window bounded by `starts_at` (inclusive open) and `ends_at` (exclusive close). The `campaign_type` is one of `CATALOG`, `PLEDGE`, or `EVENT`, and it signals which child workflow the drive primarily exercises — a catalog sale of products, a pledge drive, or an event with neither catalog products nor per-student pledges as its core. The `profit_split_pct` is the fraction of the eventual split base that the school retains as profit, with the vendor keeping the residual.

A campaign comes to life in `DRAFT` posture with `version` 1 and all of its computed money fields — `gross_collected_cents`, `forecast_gross_cents`, `school_profit_cents`, and `vendor_payable_cents` — sitting at zero, and `reconciled_at` null. The campaign's `posture` field is system-managed, and its lifecycle runs `DRAFT → ACTIVE → CLOSED → RECONCILED → DISBURSED`, with `FROZEN` reachable from `ACTIVE` and back. While a campaign is still in `DRAFT`, none of its children may be created or transitioned; this is the posture gate of Section 2.9 surfacing as `ERR_CAMPAIGN_NOT_ACTIVE`.

Activating a campaign moves its posture from `DRAFT` to `ACTIVE`. Activation is permitted only when the campaign has at least one `Seller` on its roster, and either has at least one `PrizeTier` defined or is of type `EVENT` (events need no prize tiers). If those preconditions are not met, the activation is rejected with `ERR_INVALID_STATE`. Once `ACTIVE`, sellers, orders, pledges, volunteers, and products may all be created and transitioned.

A `CampaignAdmin` may temporarily suspend an active drive by freezing it, moving the posture from `ACTIVE` to `FROZEN`. While `FROZEN`, all forward-progress child transitions — paying, confirming, or delivering orders; recording or collecting pledges; booking shifts — are blocked with `ERR_CAMPAIGN_NOT_ACTIVE`. Unfreezing returns the posture from `FROZEN` to `ACTIVE`, and child operations resume.

### 3.2. Closing a Campaign and Its Cascade

When the drive is over, a `CampaignAdmin` closes the campaign, moving the posture from `ACTIVE` to `CLOSED`. Closing is the system's most consequential cascade, and it reaches three levels deep. First, every `Order` that is still unpaid — `payment_status` equal to `PENDING` — and whose `fulfillment_status` is either `PLACED` or `CONFIRMED` has its `fulfillment_status` driven to `CANCELLED`. Second, each of those order cancellations releases that order's line reservations, so each affected product's `reserved_qty` recomputes downward. Third, because `reserved_qty` has fallen, each product's available headroom — its `stock_qty` minus its `reserved_qty` — is correspondingly restored. Independently, every `Pledge` still in `PROMISED` status is moved to `CANCELLED`, reflecting that uncollected promises lapse at close, and every `VolunteerShift` still `OPEN` is moved to `CANCELLED`.

Crucially, money that has already settled survives the close: orders already `PAID` and pledges already `RECORDED` are left untouched so that they can flow into reconciliation. A `CLOSED` campaign still permits a small set of settlement operations — notably delivering a `CONFIRMED` paid order, collecting a `RECORDED` pledge, and refunding a `PAID` order — which is why a late mutation can still move a closed campaign's gross totals and bump its `version`.

### 3.3. The Seller Roster, Share Links, and Blocking

A `CampaignAdmin` adds a **Seller** to a campaign's roster by supplying the parent `campaign_id`, a `display_name`, and a `guardian_email`. On creation the server mints an opaque `share_slug` — a sharing-link token guaranteed unique across all sellers in the system — and the seller starts in `ACTIVE` status. A seller carries two computed read-only fields: `credited_cents`, the settled money credited to them, and `earned_prize_tier_id`, the prize they have earned (both explained in Sections 3.5 and 3.6).

A seller's status moves between `ACTIVE` and `BLOCKED`. Blocking a seller is a cascade two levels deep that mirrors part of the campaign close. Every `Order` crediting this seller that is still unpaid — `payment_status` equal to `PENDING` — and whose `fulfillment_status` is `PLACED` or `CONFIRMED` has its `fulfillment_status` driven to `CANCELLED`, and each such cancellation releases that order's product reservations so the affected products' `reserved_qty` recomputes downward. Every `Pledge` crediting this seller that is still `PROMISED` is moved to `CANCELLED`. Blocking does not disturb already-settled money: the seller's `credited_cents` is unaffected and their `earned_prize_tier_id` is unchanged, because settled revenue stays credited. Unblocking simply returns the seller to `ACTIVE` with no cascade.

The seller-block guard of Section 2.9 means that while a seller is `BLOCKED`, three revenue-affecting transitions naming that seller are refused with `ERR_SELLER_BLOCKED`: paying one of their orders, recording one of their pledges, and collecting one of their pledges.

### 3.4. The Catalog: Products, Orders, and the Two-Dimensional Order Lifecycle

A `CampaignAdmin` stocks the catalog by creating **Products** on a campaign. A product is authored with its `campaign_id`, a `sku` that must be unique within the campaign, a `name`, a `unit_price_cents` charged to the buyer, a `unit_cost_cents` representing the vendor's cost per unit, and a `stock_qty` of units available to sell across all orders. A product also exposes a computed `reserved_qty`. A duplicate `sku` within the same campaign is rejected with `ERR_DUPLICATE_KEY`.

An **Order** is placed by either a `CampaignAdmin` or the crediting `Seller`. The order body names the `campaign_id`, the `seller_id` credited for the sale, a `buyer_name`, a `buyer_email` for the receipt, and a non-empty `lines` array. Each line names a `product_id` and a quantity, where each product referenced must belong to the same campaign and each quantity is at least 1. At placement, the order's money fields are computed and stored: `gross_cents` is the exact sum, over the lines, of each referenced product's `unit_price_cents` multiplied by that line's quantity, with no rounding at the line level because every factor is a whole number of cents. `tax_cents` is then the campaign's sales tax applied once to the order-level `gross_cents` — that is, `gross_cents` multiplied by the tax rate of 0.0825, rounded half-up once to a whole number of cents — and never computed per line and summed, which could differ by a cent. `total_charged_cents` is `gross_cents` plus `tax_cents`. A newly placed order begins with `payment_status` `PENDING` and `fulfillment_status` `PLACED`, and its `receipt_number` is null.

Placing an order takes a reservation against stock. Before the order is accepted, each line is checked against the relevant product's available headroom: the requested quantity for a product must be no greater than that product's `stock_qty` minus its current `reserved_qty`, with the boundary inclusive so that exactly exhausting the headroom is allowed. A line that would over-reserve is rejected with `ERR_INSUFFICIENT_STOCK`. A product's `reserved_qty` is itself a roll-up: it is the sum, over every order of the campaign whose `fulfillment_status` is `PLACED` or `CONFIRMED`, of the quantities of that order's lines naming the product. Delivered units have left the reserved pool and cancelled orders hold no reservation, so neither contributes; `payment_status` is irrelevant to reservation — `fulfillment_status` alone governs it.

An order carries two **independent** state dimensions. The first is `payment_status`, running `PENDING → PAID → REFUNDED`. The second is `fulfillment_status`, running `PLACED → CONFIRMED → DELIVERED`, with `CANCELLED` reachable from `PLACED` or `CONFIRMED`. A `CampaignAdmin` drives both.

Paying an order moves `payment_status` from `PENDING` to `PAID`. Payment is permitted only when the campaign posture is `ACTIVE`, the order's `fulfillment_status` is not `CANCELLED`, and the crediting seller is `ACTIVE`. On payment the server assigns the order a sequential `receipt_number`, and the order's `total_charged_cents` now counts toward both the crediting seller's `credited_cents` and the campaign's `gross_collected_cents` (the settled view); the seller's `earned_prize_tier_id` is recomputed and may cross up into a higher tier.

Refunding an order moves `payment_status` from `PAID` to `REFUNDED` and is the compensating reversal of payment. The order stops counting toward the seller's `credited_cents` and the campaign's `gross_collected_cents`, and the seller's `earned_prize_tier_id` is recomputed and may drop back down a tier. As part of the same refund, if the order's `fulfillment_status` is not already `DELIVERED` or `CANCELLED`, it is driven to `CANCELLED`, which releases that order's product reservations and recomputes the affected products' `reserved_qty`.

On the fulfillment dimension, confirming an order moves `fulfillment_status` from `PLACED` to `CONFIRMED`; it is permitted only when the campaign is `ACTIVE` and the order is already `PAID`, and the reservation is retained. Delivering an order moves `fulfillment_status` from `CONFIRMED` to `DELIVERED`; it is permitted when the order is `PAID` and the campaign posture is either `ACTIVE` or `CLOSED`, and on delivery the reservation is released into delivery so the delivered units leave the reserved pool and `reserved_qty` recomputes. Cancelling an order moves `fulfillment_status` to `CANCELLED` from either `PLACED` or `CONFIRMED` and releases the order's reservations. A cancel is allowed only when the order is not `PAID`: an attempt to cancel an order whose `payment_status` is `PAID` is refused with `ERR_PAID_ORDER_NOT_CANCELLABLE`, the caller being directed to refund it instead. Cancellation of an order may also be driven automatically by the campaign-close and seller-block cascades described above.

### 3.5. Pledges, the Revision Loop, and Collection

A **Pledge** is the pledge-drive counterpart to a catalog order, created by either a `CampaignAdmin` or the crediting `Seller`. A pledge body names the `campaign_id`, the `seller_id` credited, a `donor_name`, a `donor_email` for the tax receipt, a `per_unit_cents` amount pledged per counted unit (such as per lap), an optional `flat_cents` flat amount that defaults to 0, and an optional `cap_cents` ceiling that defaults to 0. A `cap_cents` of 0 is the sentinel for "uncapped." A pledge tracks `units_recorded` (the units actually performed, starting at 0), a computed forecast `pledged_amount_cents`, a `collected_cents` amount that stays at 0 until collection, and a `receipt_number` that is null until collection.

The pledge amount is computed as follows. The raw amount is the `flat_cents` plus the `per_unit_cents` multiplied by `units_recorded`. If `cap_cents` is 0 (uncapped), `pledged_amount_cents` equals that raw amount; otherwise `pledged_amount_cents` is the lesser of the raw amount and `cap_cents` — the cap is applied only after the flat-plus-per-unit sum, never to either term in isolation. At creation, with `units_recorded` at 0, this evaluates to the flat amount (capped if a cap applies).

A pledge's status runs `PROMISED → RECORDED → COLLECTED`, with a revision loop from `RECORDED` back to `PROMISED`, and a cancellation path to `CANCELLED` from any non-terminal state. A new pledge begins `PROMISED`. Recording a pledge moves it from `PROMISED` to `RECORDED`; it is permitted only while the campaign is `ACTIVE` and the crediting seller is `ACTIVE`. Recording takes the performed `units_recorded` from the request and recomputes `pledged_amount_cents` accordingly. Revising a pledge moves it from `RECORDED` back to `PROMISED` while the campaign is `ACTIVE`, resetting `units_recorded` to 0 and recomputing `pledged_amount_cents`; this record-and-revise loop may repeat any number of times.

Collecting a pledge moves it from `RECORDED` to `COLLECTED` and is permitted when the crediting seller is `ACTIVE` and the campaign posture is either `ACTIVE` or `CLOSED`. On collection, `collected_cents` is set to the current `pledged_amount_cents` (the value left standing after any record-and-revise loop has settled), a sequential `receipt_number` is assigned, and the pledge now counts toward the seller's `credited_cents` and the campaign's `gross_collected_cents`; the seller's `earned_prize_tier_id` is recomputed and may cross a tier. Cancelling a pledge moves it to `CANCELLED` from either `PROMISED` or `RECORDED` with no money effect, and may also be driven automatically by the campaign-close and seller-block cascades (which target only `PROMISED` pledges).

### 3.6. Prize Tiers and Seller Credit

A `CampaignAdmin` defines **Prize Tiers** on a campaign, each carrying the parent `campaign_id`, a `label`, a `threshold_cents` denoting the credited amount at which the tier is earned, and a human-readable `prize_description`. The `threshold_cents` must be unique within a campaign; a duplicate threshold within the same campaign is rejected with `ERR_DUPLICATE_KEY`.

A seller's `credited_cents` is the settled money attributed to them: the sum of `total_charged_cents` over their orders that are `PAID`, plus the sum of `collected_cents` over their pledges that are `COLLECTED`. Refunded orders and cancelled pledges contribute nothing. For prize-tier crossing detection, these settling events are processed in settlement order — by `created_at` ascending, with ties broken by `receipt_number` ascending.

From that credited figure the seller's earned prize is derived. Among the campaign's prize tiers, the seller earns the single highest tier whose `threshold_cents` is less than or equal to their `credited_cents`. The boundary is inclusive: a `credited_cents` exactly equal to a tier's `threshold_cents` earns that tier, while a `credited_cents` one cent below does not. If no tier's threshold is at or below the seller's credit, `earned_prize_tier_id` is null; otherwise it is the `id` of the qualifying tier with the greatest `threshold_cents` (unambiguous, since thresholds are unique within a campaign). Because payment, refund, and pledge collection all move `credited_cents`, each recomputes `earned_prize_tier_id`, which may step up on new revenue or step down on a refund.

### 3.7. Reconciliation, the Profit Split, and Disbursement

When a campaign is `CLOSED`, a `Treasurer` reconciles it, moving the posture from `CLOSED` to `RECONCILED`. Reconciliation requires the campaign to currently be `CLOSED` (otherwise `ERR_INVALID_STATE`) and requires `expected_campaign_version` to match the campaign's current `version` (otherwise `ERR_STALE_CAMPAIGN_VERSION`, HTTP 412, per Section 2.7). Reconciliation snapshots the final profit split onto the campaign, sets `reconciled_at` to the current logical-clock instant, and increments the campaign's `version` by one.

The profit split is computed with a pinned evaluation order that deliberately breaks the apparent circularity between gross revenue, vendor cost recovery, and school profit. First, the settled revenue is gathered as of the reconcile call: product revenue is the sum of `gross_cents` over `PAID` orders (the pre-tax product money, excluding tax), pledge revenue is the sum of `collected_cents` over `COLLECTED` pledges, and tax collected is the sum of `tax_cents` over `PAID` orders, tracked separately. Refunded orders and cancelled pledges are excluded throughout. Second, the vendor cost of goods is computed only over `PAID` orders — never over pending or forecast orders — as the sum, across those orders and across their lines, of each referenced product's `unit_cost_cents` multiplied by the line quantity. Third, the base subject to the split is the product revenue net of that vendor cost of goods, plus all pledge revenue (pledges carry no vendor cost); if this split base would be negative it is floored at zero. Fourth, the waterfall pays the school first: `school_profit_cents` is the split base multiplied by the campaign's `profit_split_pct`, rounded half-up once to whole cents, and `vendor_payable_cents` is the vendor cost of goods plus the exact residual of the split base after the school's profit is removed. The collected tax is remitted separately and belongs to neither payout bucket. These two amounts are frozen onto the campaign as `school_profit_cents` and `vendor_payable_cents`; before reconciliation both read zero.

After reconciliation, the `Treasurer` disburses the campaign, moving the posture from `RECONCILED` to `DISBURSED`, which is terminal. Disbursement requires the campaign to currently be `RECONCILED` (otherwise `ERR_INVALID_STATE`, which also bars a second disbursement) and requires `expected_campaign_version` to match the campaign's current `version` (otherwise `ERR_STALE_CAMPAIGN_VERSION`, HTTP 412). Disbursement creates a **Disbursement** record naming the `campaign_id`, copying the snapshot's `school_profit_cents` into `school_amount_cents` and `vendor_payable_cents` into `vendor_amount_cents`, carrying an optional `memo` from the treasurer, and a `status` of `RECORDED` (its only, terminal value). Disbursement also increments the campaign's `version` by one. There is at most one disbursement per campaign.

### 3.8. The Two Financial Views: Forecast vs. Final

The platform maintains two parallel financial views over the same records, and the difference between them is the difference between promised and settled money.

At the campaign level, the **final** view is `gross_collected_cents`: the sum of `total_charged_cents` over orders that are `PAID`, plus the sum of `collected_cents` over pledges that are `COLLECTED`. Refunded orders are excluded. The **forecast** view is `forecast_gross_cents`, which is forward-looking and adds not-yet-settled commitments to the same skeleton: the sum of `total_charged_cents` over orders whose `payment_status` is `PENDING` or `PAID`, plus the sum of `pledged_amount_cents` over pledges whose status is `RECORDED` or `COLLECTED`. For a `COLLECTED` pledge, `pledged_amount_cents` equals `collected_cents`, so the two views agree on settled rows; they diverge — forecast exceeding final — exactly when some order is still `PENDING` or some pledge is `RECORDED` but not yet `COLLECTED`.

The same dual view exists per seller. The final per-seller figure is `credited_cents` as defined in Section 3.6. The forward-looking projection, `forecast_credited_cents`, answers "what would this seller be credited if everything currently in flight settles": the sum of `total_charged_cents` over their orders whose `payment_status` is `PENDING` or `PAID`, plus the sum of `pledged_amount_cents` over their pledges whose status is `RECORDED` or `COLLECTED`. It is computed on a dedicated forecast read and is never persisted onto the seller. The final and forecast figures diverge for any seller holding a `PENDING` order or a `RECORDED` pledge.

### 3.9. Volunteers, Shifts, and the Overlap Guard

A `CampaignAdmin` registers a **Volunteer** on a campaign with a `campaign_id`, a `full_name`, and an `email`. A volunteer exposes a computed `committed_minutes`, the total minutes across their booked shifts.

The `CampaignAdmin` also creates **Volunteer Shifts**, each authored with a `campaign_id`, a `role_label` (such as a check-in or grill role), a `starts_at` (inclusive) and `ends_at` (exclusive) where the end must be strictly after the start, and an optional `setup_buffer_minutes` that defaults to 0. A shift's status runs `OPEN → BOOKED → RELEASED`, with `CANCELLED` reachable from `OPEN` or `BOOKED`. A new shift starts `OPEN` with its `volunteer_id` null.

Booking a shift moves it from `OPEN` to `BOOKED` and assigns a `volunteer_id`. Booking is permitted only when the campaign is `ACTIVE` and the named volunteer belongs to the same campaign. Booking is further guarded against double-booking: the requested shift's buffer-extended interval — from `setup_buffer_minutes` before its `starts_at` up to but not including its `ends_at` — must not overlap any other shift the same volunteer already has `BOOKED`. A booking that would overlap is rejected with `ERR_SHIFT_OVERLAP`. On a successful booking the volunteer's `committed_minutes` is recomputed.

A volunteer's `committed_minutes` is the sum, over that volunteer's shifts whose status is `BOOKED`, of the whole minutes between each shift's `starts_at` and `ends_at` (the elapsed interval, taken down to a whole number of minutes). The `setup_buffer_minutes` does not count toward `committed_minutes`; it only widens the overlap-guard interval at booking time. Releasing a shift moves it from `BOOKED` to `RELEASED` and recomputes the volunteer's `committed_minutes` so this shift no longer counts. Cancelling a shift moves it to `CANCELLED` from `OPEN` or `BOOKED`; when the cancelled shift had been `BOOKED`, the volunteer's `committed_minutes` is recomputed, and an `OPEN` shift may also be cancelled automatically by the campaign-close cascade.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including every posture, payment, fulfillment, pledge, seller, and shift transition — return a `200 OK` status code. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/fundraising/campaigns` | Create a campaign in DRAFT | CampaignAdmin |
| GET | `/fundraising/campaigns` | List campaigns (filter by posture / campaign_type) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/campaigns/{id}` | Get a campaign with computed gross/forecast/profit fields | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/campaigns/{id}/activate` | Activate a campaign (DRAFT to ACTIVE) | CampaignAdmin |
| POST | `/fundraising/campaigns/{id}/freeze` | Freeze a campaign (ACTIVE to FROZEN) | CampaignAdmin |
| POST | `/fundraising/campaigns/{id}/unfreeze` | Unfreeze a campaign (FROZEN to ACTIVE) | CampaignAdmin |
| POST | `/fundraising/campaigns/{id}/close` | Close a campaign with cascade (ACTIVE to CLOSED) | CampaignAdmin |
| POST | `/fundraising/campaigns/{id}/reconcile` | Reconcile and snapshot the profit split (CLOSED to RECONCILED, OCC) | Treasurer |
| POST | `/fundraising/campaigns/{id}/disburse` | Record disbursement (RECONCILED to DISBURSED, OCC) | Treasurer |
| GET | `/fundraising/campaigns/{id}/report` | Computed school report: gross, forecast, profit split, reconciled amounts | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/prize-tiers` | Create a prize tier on a campaign | CampaignAdmin |
| GET | `/fundraising/prize-tiers` | List prize tiers (filter by campaign_id) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/prize-tiers/{prize_tier_id}` | Get a prize tier | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/sellers` | Add a seller to a campaign roster (mints share_slug) | CampaignAdmin |
| GET | `/fundraising/sellers` | List sellers (filter by campaign_id / status) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/sellers/{seller_id}` | Get a seller with computed credited_cents and earned_prize_tier_id | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/sellers/{seller_id}/credit-forecast` | Forward-looking credited projection for a seller (not persisted) | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/sellers/{seller_id}/block` | Block a seller with cascade (ACTIVE to BLOCKED) | CampaignAdmin |
| POST | `/fundraising/sellers/{seller_id}/unblock` | Unblock a seller (BLOCKED to ACTIVE) | CampaignAdmin |
| POST | `/fundraising/products` | Create a catalog product on a campaign | CampaignAdmin |
| GET | `/fundraising/products` | List products (filter by campaign_id) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/products/{product_id}` | Get a product with computed reserved_qty | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/orders` | Place a catalog order crediting a seller | CampaignAdmin, Seller |
| GET | `/fundraising/orders` | List orders (filter by campaign_id / seller_id / payment_status / fulfillment_status) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/orders/{order_id}` | Get an order | CampaignAdmin, Treasurer, SchoolOfficial, Seller |
| POST | `/fundraising/orders/{order_id}/pay` | Pay an order (payment PENDING to PAID) | CampaignAdmin |
| POST | `/fundraising/orders/{order_id}/confirm` | Confirm an order (fulfillment PLACED to CONFIRMED) | CampaignAdmin |
| POST | `/fundraising/orders/{order_id}/deliver` | Deliver an order (fulfillment CONFIRMED to DELIVERED) | CampaignAdmin |
| POST | `/fundraising/orders/{order_id}/cancel` | Cancel an unpaid order (fulfillment PLACED/CONFIRMED to CANCELLED) | CampaignAdmin |
| POST | `/fundraising/orders/{order_id}/refund` | Refund an order (payment PAID to REFUNDED) | CampaignAdmin |
| POST | `/fundraising/pledges` | Create a pledge crediting a seller | CampaignAdmin, Seller |
| GET | `/fundraising/pledges` | List pledges (filter by campaign_id / seller_id / status) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/pledges/{pledge_id}` | Get a pledge | CampaignAdmin, Treasurer, SchoolOfficial, Seller |
| POST | `/fundraising/pledges/{pledge_id}/record` | Record performed units (PROMISED to RECORDED) | CampaignAdmin |
| POST | `/fundraising/pledges/{pledge_id}/revise` | Revise a pledge (RECORDED to PROMISED) | CampaignAdmin |
| POST | `/fundraising/pledges/{pledge_id}/collect` | Collect a pledge (RECORDED to COLLECTED) | CampaignAdmin |
| POST | `/fundraising/pledges/{pledge_id}/cancel` | Cancel a pledge (PROMISED/RECORDED to CANCELLED) | CampaignAdmin |
| POST | `/fundraising/volunteers` | Add a volunteer to a campaign | CampaignAdmin |
| GET | `/fundraising/volunteers` | List volunteers (filter by campaign_id) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/volunteers/{volunteer_id}` | Get a volunteer with committed_minutes | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/shifts` | Create an OPEN volunteer shift on a campaign | CampaignAdmin |
| GET | `/fundraising/shifts` | List shifts (filter by campaign_id / status / volunteer_id) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/shifts/{shift_id}` | Get a shift | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/fundraising/shifts/{shift_id}/book` | Book a shift for a volunteer, overlap-guarded (OPEN to BOOKED) | CampaignAdmin |
| POST | `/fundraising/shifts/{shift_id}/release` | Release a shift (BOOKED to RELEASED) | CampaignAdmin |
| POST | `/fundraising/shifts/{shift_id}/cancel` | Cancel a shift (OPEN/BOOKED to CANCELLED) | CampaignAdmin |
| GET | `/fundraising/disbursements` | List disbursements (filter by campaign_id) | CampaignAdmin, Treasurer, SchoolOfficial |
| GET | `/fundraising/disbursements/{disbursement_id}` | Get a disbursement | CampaignAdmin, Treasurer, SchoolOfficial |
| POST | `/_clock/set_current_utc` | Set the server logical clock | CampaignAdmin, Treasurer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_ACTIVE` | 409 Conflict |
| `ERR_SELLER_BLOCKED` | 409 Conflict |
| `ERR_INSUFFICIENT_STOCK` | 409 Conflict |
| `ERR_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_PAID_ORDER_NOT_CANCELLABLE` | 409 Conflict |

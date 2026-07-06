# Print-On-Demand Storefront API — Product Requirements Document

## 1. Introduction

The Print-On-Demand Storefront platform gives independent creators a turnkey commerce surface — a public storefront, a design library, a pricing engine, and an on-demand print supply chain — without ever holding inventory. A creator uploads artwork, chooses a blank product (a T-shirt, a mug, a wall print), sets a markup on the manufacturer's base cost, and publishes a listing. When a buyer purchases, the platform authorizes and captures payment, deterministically routes the print job to an eligible fulfillment partner in the buyer's country, and recognizes the creator's earnings only after successful delivery. Reprint cycles for failed shipments, refund flows, external channel integrations with Etsy and Shopify, and periodic payout releases are all part of the same orchestrated workflow.

Three cross-cutting concerns run through every subsystem. First, the buyer-paid gross, the partner charge, and the creator's take-home each rest on a different tiered calculation, and each must round in the order this document specifies so that a delivered order's ledger matches a released payout to the cent. Second, an order's payment status and its fulfillment status evolve on two independent state axes that occasionally couple — a full refund cancels an in-flight fulfillment, an approved reprint drags a shipped order backward into a fresh printing cycle — and the coupling rules are exhaustive rather than best-effort. Third, when a creator revises their storefront markup or a platform admin recalls an already-approved design, changes must propagate along a defined cascade so that dependent listings and orders never carry stale prices or stranded artwork.

This document specifies the API contract, the state machinery, the calculation rules, and the validation ordering that together define correct behavior. All endpoints are mounted under the top-level path prefix `/pod`, with a small `/_clock` and `/_ops` namespace reserved for test-driving instrumentation.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request except the anonymous creator-registration endpoint must carry two identifying headers: `X-User-ID`, which names the caller, and `X-User-Role`, which names the role the caller is acting under. Missing, malformed, or unrecognized headers produce `ERR_UNAUTHENTICATED` with HTTP 401. A well-formed header pair whose role is not permitted to invoke the requested endpoint produces `ERR_FORBIDDEN` with HTTP 403.

Four roles are defined, and their exact spelling is significant across the entire contract: `Anonymous`, `Creator`, `PlatformAdmin`, and `FulfillmentPartner`.

When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but does not compare it to any entity's `id`. This role covers public storefront browsing and the buyer checkout flow. When `X-User-Role` is `Creator`, `X-User-ID` is the `id` of the acting `Creator`; ownership checks on any resource that references a `Creator` (a `Storefront`, a `Design`, a `PayoutCycle`) compare that resource's foreign-key field to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; admins act system-wide and are not scoped to a specific creator. When `X-User-Role` is `FulfillmentPartner`, `X-User-ID` is the `id` of the acting `FulfillmentPartner`; the partner-facing job and order transitions compare the job's `partner_id` to `X-User-ID` for ownership.

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

Every list endpoint accepts two query parameters, `limit` and `offset`, whose semantics are uniform across the API. The `limit` parameter has a default value of 10, a minimum of 1, and a maximum of 100; any value outside that inclusive range is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter has a default of 0 and no upper bound beyond the natural size of the result set. Results are always sorted by `created_at` in ascending order, and ties within a single millisecond are broken by natural insertion order — never by `id`. The response envelope's `meta` object carries four pagination fields on list endpoints: `limit`, `offset`, `total_count` (the total number of records matching the filter, disregarding pagination), and `has_more` (true when additional pages remain, false otherwise).

### 2.4. Common Resource Properties and Timestamps

Every persisted entity except `ChannelSyncEvent` carries four common properties. The `id` is a server-minted UUID with no type prefix; clients must never construct or guess it. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits: `created_at` is fixed at the moment the row is inserted, and `updated_at` is refreshed on every state transition, cascade, or field-level mutation that this document declares. The `version` field is a non-negative integer that starts at 1 on creation and increments by exactly one on every mutation of the row, forming the substrate for optimistic concurrency control.

`ChannelSyncEvent` is an append-only log entry rather than a mutable entity; it carries only `id` and `created_at`, and neither `updated_at` nor `version` is defined for it. Rows are inserted in causal order and are never updated in place.

### 2.5. Optimistic Concurrency Control for Storefront Channel Linking

Linking a `Storefront` to an external channel — Etsy or Shopify — is the single write in this system that carries a mandatory optimistic-concurrency guard. The link-channel request must include a non-optional `expected_storefront_version` field carrying the client's last observed `version` of the target storefront. When the server processes the request, it compares `expected_storefront_version` to the storefront's current `version`. If the two do not match — because another writer has already linked, suspended, resumed, or updated the storefront since the client last read it — the request is rejected with `ERR_STALE_STOREFRONT_VERSION` and HTTP 412. The client's remedy is to re-read the storefront, observe the new `version`, decide whether the intervening change already satisfies their intent, and re-submit if needed. No other endpoint in this API requires or accepts a version field; endpoints outside the link-channel path do not participate in optimistic concurrency and do not carry any `expected_<parent>_version` input.

### 2.6. Precision, Rounding, and Currency Discipline

All monetary quantities are integer cents in United States dollars — there are no fractional-cent representations at any layer of the system. Whenever a rate, a percentage, or a basis-points multiplier is applied to a base amount, the result is rounded up to the next whole cent using the ceiling function, and rounding is applied to each component individually before components are summed. Specifically, when computing a listed price, the platform fee and the creator markup are each ceiled independently before being added to the base cost — the sum of two ceilings, not the ceiling of a sum. The partner charge follows the same discipline: the multiplier is applied to a per-unit base, scaled by the order's `item_count`, and the whole product is ceiled at the end. Payout fees, in contrast, are computed by taking the floor of the gross earnings scaled by the fee basis-points — payout fees are floored so that the platform never over-collects the fee, and the creator's net is `gross_earnings_cents` minus `fee_cents` computed exactly. All shipping surcharges are pre-declared integer constants: a domestic shipment costs 599 cents and a cross-border shipment costs 1599 cents.

### 2.7. Cascading Side Effects and Version Bumps

The system maintains hierarchical consistency across three cascade patterns. Every state transition refreshes the transitioning entity's `updated_at` and increments its `version` by one. When a transition declares a downstream cascade — such as archiving listings when a design is retroactively rejected, or cancelling pending orders when their listings archive — each affected downstream row also gets its `updated_at` refreshed and its `version` incremented. When a storefront markup change triggers a listed-price recomputation on every dependent `Listing`, each recomputed listing's `updated_at` refreshes and its `version` bumps. When a fulfillment partner's `current_backlog_hours` shifts because a new job entered the queue or an existing job shipped, the partner's `updated_at` refreshes and its `version` increments. This uniform bump discipline means that any downstream client caching a `version` will observe staleness and can trigger a targeted re-read.

### 2.8. Nested Resource Path Resolution

Endpoints with nested path parameters — such as the creator-scoped designs list, the creator-scoped payout cycles list, the product-scoped variants creation, and the storefront-scoped channel-sync-events log — validate their path segments left to right. The parent `id` is resolved first; if the parent does not exist, the response is `ERR_NOT_FOUND` with HTTP 404 for the parent, regardless of whether the child would have existed. If the parent resolves, the child is looked up in the parent's scope; a child that exists but does not belong to the named parent is treated as not found under that parent (also `ERR_NOT_FOUND`, HTTP 404). Foreign-key fields in a request body are validated after path resolution: any `storefront_id`, `design_id`, `variant_id`, `listing_id`, `order_id`, `partner_id`, `product_id`, `creator_id`, `job_id`, `routed_partner_id`, or `country_code` reference in a body that fails to resolve produces `ERR_FK_NOT_FOUND` with HTTP 404.

### 2.9. Validation Priority and Ordering

Validation is layered, and the order in which failures surface is fixed so that the API's error semantics remain deterministic. Priority 1 is authentication: header presence and role recognition, yielding `ERR_UNAUTHENTICATED` on failure. Priority 2 is authorization: whether the recognized role is permitted for the invoked endpoint, yielding `ERR_FORBIDDEN`. Priority 3 is path-parameter existence, yielding `ERR_NOT_FOUND`. Priority 4 is request-body foreign-key existence, yielding `ERR_FK_NOT_FOUND`. Priority 5 covers state-precondition checks: the generic `ERR_INVALID_STATE` for any transition whose entity state does not permit the operation, `ERR_STOREFRONT_CHANNEL_ALREADY_LINKED` for the specific case of link-channel invoked when `integration_status` is already `LINKED`, `ERR_REPRINT_ORDER_NOT_SHIPPED` for reprint approval when the linked order's `fulfillment_status` is not `SHIPPED`, and `ERR_PAYOUT_RETURN_WINDOW_EXPIRED` when a payout return is attempted after its 72-hour recall window. Priority 6 is the optimistic-concurrency check on storefront link-channel, yielding `ERR_STALE_STOREFRONT_VERSION`. Priority 7 is the creator-verification safety check on payout release, yielding `ERR_CREATOR_NOT_VERIFIED`. Priority 8 is the reprint-strike safety check on design approval, yielding `ERR_STRIKE_THRESHOLD_EXCEEDED`. Priority 9 is the design-creator referential check on listing creation, yielding `ERR_DESIGN_CREATOR_MISMATCH`. Priority 10 is the listing-availability referential check on order creation, yielding `ERR_LISTING_NOT_AVAILABLE`. Priorities 11 through 17 cover the business constraints, temporal windows, and fiscal invariants in numeric order: `ERR_SAMPLE_LIMIT_EXCEEDED`, `ERR_MARKUP_OUT_OF_RANGE`, `ERR_DESIGN_DUPLICATE_HASH`, `ERR_PAYOUT_WINDOW_OVERLAP`, `ERR_NO_ELIGIBLE_PARTNER`, `ERR_REFUND_AMOUNT_INVALID`, and `ERR_PAYOUT_ZERO_GROSS`. When multiple validations apply to the same request, the failure with the numerically lowest priority is the one returned to the caller.

### 2.10. The Logical Clock and Test-Driving Endpoints

All time-sensitive comparisons in this system — the payout return window, the trailing 90-day reprint-strike aggregation, timestamps on shipped jobs — read from a logical clock rather than the host's wall clock. On process start the logical clock is fixed at 2026-03-01T00:00:00Z and remains at that value until an admin-only test-driving endpoint advances it. Advancing the clock accepts a single `to_iso8601` input carrying the destination instant; the clock jumps to that instant and every subsequent `created_at`, `updated_at`, and `shipped_at` derives from the advanced value. A second admin-only capability triggers the full-recompute variant of the reprint-strike aggregation, walking every creator's trailing-90-day `ReprintRequest` history and rewriting `reprint_strike_count`. Both endpoints live outside the `/pod` namespace and exist purely for test orchestration.

## 3. Business Logic & Workflows

### 3.1. Creator Onboarding and KYC Verification

A new creator joins the platform anonymously by registering with three fields: their unique `email`, a public `display_name` that will appear on their storefront, and a two-letter `payout_country_code` in ISO-3166 alpha-2 form denoting the country of the bank account that will eventually receive payouts. Registration mints a `Creator` row with `verification_status` initialized to `UNVERIFIED`, `payout_wallet_cents` initialized to 0, `default_payout_fee_bps` initialized to 250, and `reprint_strike_count` initialized to 0. The `email` field must be unique across all creators; a duplicate submission is rejected as a malformed request.

A creator whose verification remains at `UNVERIFIED` may still create a storefront, upload designs, and list products, and buyers may already purchase from that storefront — the platform holds the creator's earnings in `payout_wallet_cents` regardless of verification state. What `UNVERIFIED` gates is the payout release itself. An admin operator moves a creator through KYC by invoking the verification action with an `outcome` value that either advances `verification_status` to `VERIFIED` or lands it in `REJECTED`. Intermediate `PENDING` state is used for creators whose documents are under manual review; such creators may still link a storefront to an external channel (Etsy or Shopify) but cannot yet release payouts. Only a `VERIFIED` creator may successfully release a payout cycle; any attempt to release under `UNVERIFIED`, `PENDING`, or `REJECTED` is rejected with `ERR_CREATOR_NOT_VERIFIED`.

### 3.2. Storefront Creation and Markup Configuration

A `Creator` opens their storefront by submitting a `slug` (the URL slug, unique across all storefronts on the platform), an `integration_channel` naming which sales surface the storefront will eventually sync with (`NATIVE`, `ETSY`, or `SHOPIFY`), and their chosen `markup_bps` expressed in basis-points. The `creator_id` foreign key ties the storefront to its owning creator. On creation, the storefront's `integration_status` starts at `NONE` — a `NATIVE` storefront may remain at `NONE` indefinitely, whereas an `ETSY` or `SHOPIFY` storefront is expected to be linked in a subsequent step. The markup value must fall in the inclusive range from 0 to 10000 basis-points (0% to 100%); a submission of 10001 or above is rejected with `ERR_MARKUP_OUT_OF_RANGE`, and the same range constraint applies when updating an existing storefront's markup.

Updating the markup is the pricing-engine's cascade trigger. When a creator revises `markup_bps` on their storefront, every dependent `Listing` under that storefront has its `listed_price_cents` recomputed from the new markup, its `updated_at` refreshed, and its `version` incremented. The storefront's own `version` also increments on the update. This is the second cascade pattern in the system — a depth-2 propagation — and it exists so that a listing's advertised price never lags behind the creator's currently declared markup.

### 3.3. External Channel Integration

Once a storefront has published listings and its owning creator is at least `PENDING` KYC (a `VERIFIED` or `PENDING` creator may proceed; `UNVERIFIED` and `REJECTED` cannot), the storefront can be linked to its external channel. Linking transitions `integration_status` from `NONE` to `LINKED` and simultaneously mirrors every currently-`PUBLISHED` `Listing` under that storefront onto the external channel by emitting a `ChannelSyncEvent` for each — with `event_type` set to `LISTING_MIRROR` and `channel` set to the storefront's `integration_channel`. Because the linked-channel write is the coordination point between the platform's storefront state and the external channel's mirror, this endpoint is the sole write in the system guarded by optimistic concurrency: the request must carry `expected_storefront_version`, which the server compares to the storefront's current `version`; a mismatch rejects with `ERR_STALE_STOREFRONT_VERSION` and HTTP 412, forcing the client to re-read before retrying.

An attempt to link a storefront that is already at `LINKED` is rejected with `ERR_STOREFRONT_CHANNEL_ALREADY_LINKED` — the state check surfaces before the concurrency check, per the validation ordering. An admin may `SUSPEND` a `LINKED` storefront's channel (transitioning `integration_status` from `LINKED` to `SUSPENDED`), and any `Order` under that storefront whose `payment_status` is `DRAFT` remains untouched — drafts persist across suspension. The admin resume-channel action moves `SUSPENDED` back to `LINKED`, and requires that the storefront's owning creator is `VERIFIED` at that moment. Each of link, suspend, and resume increments the storefront's `version` by one.

External channels may also push orders into the platform. When Etsy or Shopify posts an ingested order to the storefront's ingest endpoint, the server creates a native `Order` shell — with `payment_status` set to `DRAFT` and `fulfillment_status` set to `PENDING` — and emits a `ChannelSyncEvent` with `event_type` set to `ORDER_INGEST` capturing the external channel's `external_ref` for reconciliation. A third `ChannelSyncEvent` variant, `SYNC_FAIL`, records failed synchronization attempts against the storefront's log. All three event types are read back through the storefront's append-only channel-sync-events log.

### 3.4. Product Catalog and Variant Management

Blank products are administered centrally. An admin creates a `Product` by supplying a manufacturer `sku` (unique across the catalog), a `category` drawn from the set `APPAREL`, `DRINKWARE`, `ACCESSORY`, or `PRINT`, a `base_cost_cents` value of at least 100 cents, and a `dimensions_json` object describing the print area (its `width_px`, `height_px`, and `dpi`). Categories drive the platform's tiered fee, discussed below in the pricing narrative.

Beneath each product sit its `Variant` rows, keyed by `product_id`, `color`, and `size`. Each variant carries a `base_cost_delta_cents` — an additive per-unit cost adjustment layered on top of the parent product's `base_cost_cents` (defaulting to 0 when not specified) — and an `active` boolean that governs whether the variant is currently sellable. Newly created variants are `active` by default; an admin may set `active` to false to withdraw a variant from sale without archiving it. A listing referencing an inactive variant cannot be ordered, and buyers attempting to place such an order receive `ERR_LISTING_NOT_AVAILABLE`.

### 3.5. Design Upload, Mockup, and Moderation

A creator uploads a `Design` under their creator record by posting a single input, the `file_hash` — a sha256 fingerprint of the binary artwork file. The row is minted with the creator's `creator_id` on it, `status` set to `UPLOADED`, and `mockup_url` set to null. The platform enforces per-creator hash uniqueness: an attempt to upload a design whose `(creator_id, file_hash)` pair already exists for that creator is rejected with `ERR_DESIGN_DUPLICATE_HASH`. This prevents accidental double-uploads while permitting two different creators to upload the same artwork independently.

Once uploaded, the creator initiates mockup generation, which advances `status` from `UPLOADED` to `MOCKUP_READY` and populates `mockup_url` with a server-generated URL of the composited mockup image. Mockup generation requires that the design is still at `UPLOADED` and that `file_hash` is present on the row; otherwise the transition is rejected with `ERR_INVALID_STATE`.

Moderation is admin-driven. An admin either approves or rejects a design that has reached `MOCKUP_READY`. Approval transitions `status` from `MOCKUP_READY` to `APPROVED`, making the design eligible to appear on published listings. Rejection at this stage transitions `status` from `MOCKUP_READY` to `REJECTED`; because no listings can yet be `PUBLISHED` off a `MOCKUP_READY` design, this rejection has no downstream cascade beyond refreshing the design's `updated_at`.

An admin may also recall an already-`APPROVED` design, transitioning `status` from `APPROVED` to `REJECTED`. This retroactive rejection cascades along a three-level chain. First, every `Listing` whose `design_id` equals the recalled design and whose `status` is either `DRAFT` or `PUBLISHED` transitions to `ARCHIVED`, with `updated_at` refreshed and `version` incremented. Second, every `Order` whose `listing_id` sits in that just-archived set, whose `fulfillment_status` is still `PENDING`, and whose `payment_status` is either `DRAFT` or `AUTHORIZED`, has its `fulfillment_status` transitioned to `CANCELLED`; if that order's `payment_status` was `AUTHORIZED`, `payment_status` is simultaneously transitioned to `VOIDED`. Orders that had already progressed to `ROUTED`, `IN_PRINT`, `SHIPPED`, or `DELIVERED` are not touched by this cascade — their fulfillment path is already downstream of the archival cutoff.

Design approval is where the reprint-strike safety valve operates. Before an approve request lands, the acting creator's `reprint_strike_count` must be strictly less than the strike threshold, which is 5. A creator whose count has reached or exceeded 5 has any new design approval rejected with `ERR_STRIKE_THRESHOLD_EXCEEDED`. Strikes accumulate on approved consumer-fault reprints and decay only through the ops-run recompute described later.

### 3.6. Listing Composition, Pricing, and Publication

A `Listing` binds a `storefront_id`, a `design_id`, a `variant_id`, and a customer-facing `title` into a single sellable unit. On creation, the listing is minted with `status` set to `DRAFT` and its `listed_price_cents` computed by the pricing engine. Two referential guards apply. First, the design named by `design_id` and the storefront named by `storefront_id` must belong to the same creator: the storefront's `creator_id` and the design's `creator_id` must match, and a mismatch is rejected with `ERR_DESIGN_CREATOR_MISMATCH`. Second, listings are ordered only when their underlying artwork is fit for print, so the availability check applied at order time (below) requires the design's `status` to be `APPROVED`, the variant's `active` flag to be true, and the listing itself to be `PUBLISHED`; violation of any of those three conditions surfaces at order creation as `ERR_LISTING_NOT_AVAILABLE`.

The listed price is a three-input tiered calculation. The per-unit base is the product's `base_cost_cents` plus the variant's `base_cost_delta_cents`. The platform fee in basis-points is chosen by product category: `APPAREL` carries 1500 basis-points, `DRINKWARE` 1200, `ACCESSORY` 1000, and `PRINT` 800. The platform fee in cents is the per-unit base multiplied by the category's basis-points, divided by ten thousand, and then rounded up to the next whole cent. The creator's markup in cents is the per-unit base multiplied by the storefront's `markup_bps`, divided by ten thousand, and then rounded up to the next whole cent. The listed price is the sum of the per-unit base, the ceiled platform fee, and the ceiled creator markup — the two rate-based components are each ceiled individually before being added. When an order is flagged as a creator sample (its `is_sample` field is true), the `listed_price_cents` for that order's line is instead exactly the per-unit base: no platform fee and no creator markup are applied. The listed-price recomputation runs on three occasions: at listing creation, at storefront markup update (cascading across every listing under the storefront), and at the payment authorization transition where the order's `gross_amount_cents` is computed from the current `listed_price_cents`.

Publication moves a listing from `DRAFT` to `PUBLISHED`, exposing it on the storefront. A published listing may be `ARCHIVED` only by the design-rejection cascade described above; there is no direct archive endpoint. Once archived, a listing cannot be republished — a new listing must be created against a different (approved) design.

### 3.7. Order Lifecycle: Checkout, Authorization, Capture, and Routing

An `Order` runs on two independent state axes at once. The `payment_status` axis flows through `DRAFT`, `AUTHORIZED`, `CAPTURED`, and thence to `REFUND_PARTIAL`, `REFUND_FULL`, or `VOIDED`. The `fulfillment_status` axis flows through `PENDING`, `ROUTED`, `IN_PRINT`, `SHIPPED`, and either `DELIVERED` or `CANCELLED`. The two axes evolve independently — a fully captured order can still be pending routing, and a shipped order can still trigger a refund — with a small set of explicit coupling rules called out below.

**Buyer checkout.** A buyer places an order by supplying `storefront_id`, `listing_id`, `buyer_email`, `ship_country_code` (the ISO-3166 alpha-2 destination country), and `item_count` (the number of units of the single line). Buyers act under the `Anonymous` role; the ship-country code and buyer email are contact and routing inputs, respectively. On creation, the order's `payment_status` is `DRAFT` and its `fulfillment_status` is `PENDING`. The provisional variant of the profit calculation runs immediately, populating `creator_net_cents` with the creator's forward-looking margin — the per-unit creator markup ceiled independently, multiplied by `item_count`, and summed. Because the provisional variant runs before any reprint has occurred, its partner-absorb term is zero, so `creator_net_cents` equals the total gross creator markup for the order.

**Sample orders.** A creator may also place an order against their own listing with `is_sample` set to true. Sample orders bypass the platform fee and the creator markup — the buyer (who is the creator) pays only the per-unit base times `item_count` plus shipping — and force `creator_net_cents` to 0 regardless of markup. Sample orders are bounded: `item_count` must fall in the inclusive range 1 to 3, and a submission with `item_count` strictly greater than 3 is rejected with `ERR_SAMPLE_LIMIT_EXCEEDED`.

**Availability at order time.** Before an order is minted, the availability check enforces three conditions: the referenced listing's `status` must be `PUBLISHED`, its underlying design's `status` must be `APPROVED`, and the referenced variant's `active` field must be true. Any single failure yields `ERR_LISTING_NOT_AVAILABLE`.

**Authorization and capture.** An admin authorizes the buyer's payment, transitioning `payment_status` from `DRAFT` to `AUTHORIZED`. Authorization requires the listing to still be `PUBLISHED` and the variant to still be `active`; the transition computes `gross_amount_cents` as the current `listed_price_cents` multiplied by `item_count` plus `shipping_cents`. Capturing the payment transitions `payment_status` from `AUTHORIZED` to `CAPTURED` and, if `fulfillment_status` is still `PENDING`, immediately fires the routing selector. Capture requires that `fulfillment_status` is either `PENDING` or `ROUTED` — an order that was already cancelled cannot be captured.

**Routing.** Routing advances `fulfillment_status` from `PENDING` to `ROUTED`. Each `FulfillmentPartner` is registered by an admin with a display `name`, an ISO-3166 alpha-2 `country_code` identifying where the partner prints, a `cost_multiplier_bps` (10000 basis-points meaning 1.00× multiplier), and an optional `max_backlog_hours` defaulting to 168; the partner is minted with `status` set to `ACTIVE` and `current_backlog_hours` set to 0. A partner's `status` may subsequently be `ACTIVE`, `SUSPENDED`, or `RETIRED` — only `ACTIVE` partners are eligible for routing. The selector considers every `FulfillmentPartner` whose `status` is `ACTIVE`, whose `country_code` matches the order's `ship_country_code`, and whose `current_backlog_hours` is strictly less than its `max_backlog_hours`. A partner whose `current_backlog_hours` equals its `max_backlog_hours` is excluded — equality means excluded. If the country-matched candidate set is empty, the selector falls back to any `ACTIVE` partner (regardless of country) whose `current_backlog_hours` is strictly less than its `max_backlog_hours`; this is the cross-border fallback. If the fallback set is also empty, the routing attempt fails with `ERR_NO_ELIGIBLE_PARTNER`. Otherwise, the surviving candidates are ranked by `cost_multiplier_bps` ascending as the primary key, `current_backlog_hours` ascending as the tie-breaker, and `created_at` ascending as the final tie-breaker — `id` is never used to break ties. The top-ranked candidate is selected; the order's `routed_partner_id` is set to that partner's `id`, `shipping_cents` is set to 599 cents when the order is domestic (partner country matches ship country) or 1599 cents when it is cross-border, `FulfillmentJob.partner_charge_cents` is computed as the per-unit base multiplied by `item_count` multiplied by the partner's `cost_multiplier_bps` divided by ten thousand and then rounded up, a `FulfillmentJob` row is inserted with `status` set to `QUEUED` and `reprint_generation` set to 0, and the selected partner's `current_backlog_hours` is increased by the ceiling of `item_count` multiplied by 0.5.

**Refunds.** An admin issues a refund by supplying `refund_amount_cents`. The amount must be strictly positive and no greater than the order's `gross_amount_cents`; a zero or negative amount or an amount exceeding the gross is rejected with `ERR_REFUND_AMOUNT_INVALID`. A refund whose amount is strictly greater than zero and strictly less than `gross_amount_cents` transitions `payment_status` from `CAPTURED` to `REFUND_PARTIAL` and recomputes `payout_wallet_cents` on the owning creator to reflect the reduced net margin. A refund whose amount equals `gross_amount_cents` exactly transitions `payment_status` from `CAPTURED` to `REFUND_FULL`, zeros out that order's contribution to `payout_wallet_cents`, and — if `fulfillment_status` is `PENDING` or `ROUTED` at the moment of the full refund — transitions `fulfillment_status` to `CANCELLED`. When the fulfillment status was `ROUTED` at refund time, the routed partner's `current_backlog_hours` is decremented by the ceiling of `item_count` multiplied by 0.5, with the result bounded below at zero — this releases the routed capacity as a compensating action so that the partner's backlog invariant remains conserved. A cancel action separate from refund also exists: an admin cancels a still-`PENDING` order (whose `payment_status` is `DRAFT` or `AUTHORIZED`), transitioning `fulfillment_status` to `CANCELLED`, and if `payment_status` was `AUTHORIZED`, simultaneously transitioning it to `VOIDED`.

**Void.** An admin voids a not-yet-captured order by transitioning `payment_status` from `AUTHORIZED` to `VOIDED`. Void is legal only when the order's `fulfillment_status` is `PENDING` or `CANCELLED` — an order that has already routed cannot be voided directly; a full refund is the correct path there.

### 3.8. Fulfillment: Printing, Shipping, Delivery, and Reprint Cycle

Once an order is `ROUTED`, the assigned partner drives its fulfillment through a linear sequence. The partner marks the job in print, which requires the linked `FulfillmentJob.status` to be `QUEUED` and the order's `fulfillment_status` to be either `ROUTED` (the fresh-routing path) or `IN_PRINT` (the reprint-re-entry path described below); the transition sets the order's `fulfillment_status` to `IN_PRINT` and transitions the linked `FulfillmentJob.status` from `QUEUED` to `PRINTING`. The partner then marks the job shipped, transitioning `fulfillment_status` from `IN_PRINT` to `SHIPPED`, transitioning `FulfillmentJob.status` from `PRINTING` to `SHIPPED`, stamping the job's `shipped_at` with the current logical-clock instant, and decrementing the partner's `current_backlog_hours` by the ceiling of `item_count` multiplied by 0.5 (bounded below at zero). Finally, the partner marks the order delivered, transitioning `fulfillment_status` from `SHIPPED` to `DELIVERED`, transitioning `FulfillmentJob.status` from `SHIPPED` to `DELIVERED`, and — critically — this is the transition on which the creator's earnings are recognized. The final variant of the profit calculation runs here, overwriting `creator_net_cents` with the finalized value, and the creator's `payout_wallet_cents` accumulates the recognized margin.

**Failure and reprint.** A partner may report a shipped job as failed in transit, transitioning `FulfillmentJob.status` from `SHIPPED` to `FAILED`. Failed jobs do not touch `payout_wallet_cents`, because delivery never occurred — the creator's earnings are not recognized on failure. An admin then opens a `ReprintRequest` against the failed job, supplying a `fault_category` drawn from `PARTNER_FAULT`, `CONSUMER_FAULT`, or `PLATFORM_GESTURE`, and a short `reason_code` keyword (`WRONG_SIZE`, `DAMAGED`, `MISPRINT`, `LATE`, or `OTHER`). Opening the reprint request creates a `ReprintRequest` row with `status` set to `OPEN` and transitions `FulfillmentJob.status` from `FAILED` to `REPRINT_REQUESTED`. Opening a reprint against a job whose linked order is not currently at `SHIPPED` is rejected with `ERR_REPRINT_ORDER_NOT_SHIPPED`.

**Approval.** An admin approves an open reprint request. Approval requires that `FulfillmentJob.status` is `REPRINT_REQUESTED`, `ReprintRequest.status` is `OPEN`, and the linked order's `fulfillment_status` is `SHIPPED`. On approval, `ReprintRequest.status` moves to `APPROVED`, `FulfillmentJob.status` cycles back to `QUEUED`, `FulfillmentJob.reprint_generation` increments by 1, and `FulfillmentJob.partner_charge_cents` is recomputed to reflect the reprint surcharge described below. The linked order's `fulfillment_status` transitions from `SHIPPED` back to `IN_PRINT` — a legal retrograde permitted only on reprint approval — so that the reprint cycle then re-enters the print → ship → deliver sequence as if it were a fresh routing. When `fault_category` is `CONSUMER_FAULT`, the owning creator's `reprint_strike_count` is incremented by 1; when `fault_category` is `PARTNER_FAULT` or `PLATFORM_GESTURE`, the strike count is unchanged.

**Reprint surcharge and pricing recompute.** The partner charge for a reprint depends on fault. For a `CONSUMER_FAULT` reprint, the partner charge is recomputed as the initial partner charge locked at first routing plus twenty-five percent of that initial charge multiplied by the reprint generation, rounded up to the next whole cent — the surcharge scales linearly with generation and lands in the final variant of the profit calculation as the creator's absorbance. For `PARTNER_FAULT` or `PLATFORM_GESTURE` reprints, the partner charge is unchanged from the initial value — the partner absorbs the reprint cost and the creator's margin is preserved.

**Denial.** An admin may instead deny an open reprint request. Denial requires that `FulfillmentJob.status` is `REPRINT_REQUESTED` and `ReprintRequest.status` is `OPEN`; on denial, `ReprintRequest.status` moves to `DENIED` and `FulfillmentJob.status` moves to `CANCELLED`.

**Provisional and final creator profit.** The creator's take-home from an order is computed by two variants of the same calculation, populating the same `creator_net_cents` field on the order. The provisional variant runs at order creation and stores the forward-looking gross markup — the per-unit creator markup ceiled independently, multiplied by `item_count` — without any partner-absorb deduction. The final variant runs at the delivered transition and overwrites `creator_net_cents` with the same gross markup minus the final partner-absorb term. The partner-absorb term is zero when `FulfillmentJob.reprint_generation` is zero; when reprint_generation is strictly greater than zero, the absorb term is the difference between the current `partner_charge_cents` (which reflects any consumer-fault surcharge) and the initial partner charge locked at first routing. The two variants therefore diverge whenever a `CONSUMER_FAULT` reprint has occurred — that is the surcharge, and the creator absorbs it out of their delivered margin. When the order is a sample (`is_sample` is true), the final `creator_net_cents` is forced to zero regardless of markup.

**Reprint-strike scoring and decay.** The creator's `reprint_strike_count` is more than a simple counter — it is a windowed weighted score. Each approved consumer-fault reprint contributes a weight determined by its `reason_code`: `DAMAGED` contributes 1, `WRONG_SIZE` contributes 2, `MISPRINT` contributes 0 (interpreted as more likely partner-fault-adjacent), and `OTHER` contributes 1. Only reprint requests whose `status` is `APPROVED`, whose `fault_category` is `CONSUMER_FAULT`, and whose `updated_at` falls in the trailing 90-day window relative to the current logical clock instant contribute to the score. Two variants govern how the score is maintained. The incremental variant fires on each individual approved-consumer-fault reprint approval: it adds only that request's weight to the stored `reprint_strike_count`, assuming the prior aggregate is still correct. The full-recompute variant fires when the ops-run decay endpoint is invoked: it walks every creator's trailing-90-day reprint history from scratch, drops requests whose `updated_at` has fallen outside the window, and rewrites `reprint_strike_count` to the freshly-summed value. The two variants diverge whenever late-arriving retroactive corrections exist that the incremental variant missed. The strike threshold is 5; a creator whose `reprint_strike_count` has reached or exceeded 5 has any subsequent design approval blocked with `ERR_STRIKE_THRESHOLD_EXCEEDED`.

### 3.9. Payouts, Wallet Accounting, and Compensating Returns

The `Creator.payout_wallet_cents` field is the accumulator that records how much the platform owes each creator. Its evolution is deterministic. On every order transition into `DELIVERED`, the final variant of creator profit runs, and the resulting `creator_net_cents` is added into the creator's wallet. On every full refund of a captured order, the wallet's balance is reduced by that order's previously-recognized contribution — zeroing out its effect. On every partial refund, the wallet is recomputed to reflect the reduced net margin proportional to the refund. On the release of a payout cycle, the wallet is debited by the released `net_paid_cents`. On the return of a released payout, the wallet is credited back with the sum of `gross_earnings_cents` minus `fee_cents` — the fee itself is refunded to the wallet as part of the compensating action, so that wallet plus external-payout is a conserved quantity across the release/return cycle.

**Cycle creation.** An admin creates a payout cycle for a creator by supplying `cycle_start` and `cycle_end` timestamps. The window is half-open: the interval covered is inclusive of `cycle_start` and exclusive of `cycle_end`, and the cycle duration (`cycle_end` minus `cycle_start`) must be strictly greater than zero. In addition, a new draft cycle whose window overlaps any other cycle already in `DRAFT` for the same creator is rejected. Both length-non-positive and window-overlap failures surface as `ERR_PAYOUT_WINDOW_OVERLAP`. On creation, `PayoutCycle.status` starts at `DRAFT`.

**Release.** An admin releases a draft cycle. Release requires the cycle to be at `DRAFT`, the owning creator to be `VERIFIED` (any other verification value is rejected with `ERR_CREATOR_NOT_VERIFIED`), and the computed `gross_earnings_cents` to be strictly greater than zero — a release whose gross would be zero is rejected with `ERR_PAYOUT_ZERO_GROSS`. The computation follows a pinned three-step order. Step one sums the finalized creator margin (the `creator_net_cents` written by the final profit variant) across every `Order` owned by this creator whose `fulfillment_status` is `DELIVERED`, whose delivered timestamp (the order's `updated_at` at the moment of the delivered transition) falls in the half-open window `[cycle_start, cycle_end)`, and whose `is_sample` is false — sample orders are excluded from payout altogether. The sum is `gross_earnings_cents`, retained exactly with no rounding. Step two computes `fee_cents` as the floor of `gross_earnings_cents` multiplied by the creator's `default_payout_fee_bps` (frozen at release time onto the cycle) divided by ten thousand — payout fees are floored, not ceiled, so the platform never over-collects. Step three computes `net_paid_cents` as `gross_earnings_cents` minus `fee_cents` exactly. The cycle transitions to `RELEASED`, and the creator's `payout_wallet_cents` decreases by `net_paid_cents`.

**Return.** A released payout may be reversed within a 72-hour bank recall window. An admin returning a cycle at `RELEASED` moves it to `RETURNED` provided the current logical-clock instant is strictly less than the cycle's `updated_at` at release plus 72 hours; a return attempted after that window closes is rejected with `ERR_PAYOUT_RETURN_WINDOW_EXPIRED`. On successful return, the creator's `payout_wallet_cents` is credited back by `gross_earnings_cents` minus `fee_cents` — the fee is included in the restoration so the wallet-plus-external invariant holds.

## 4. Endpoint Definitions

New resource creations return HTTP 201; state transitions and reads return HTTP 200. All endpoints below are subject to the authentication, authorization, path resolution, and body foreign-key resolution guards described in §2, and their state-transition semantics, calculation triggers, and cascades are specified in §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/pod/creators/register` | Register a new creator. | `Anonymous` |
| GET | `/pod/creators/{id}` | Read a creator. | `Creator`, `PlatformAdmin` |
| POST | `/pod/creators/{id}/verify` | Verify a creator's KYC outcome. | `PlatformAdmin` |
| POST | `/pod/storefronts` | Create a storefront. | `Creator` |
| GET | `/pod/storefronts/{id}` | Read a storefront. | `Creator`, `PlatformAdmin` |
| GET | `/pod/storefronts` | List storefronts, optionally filtered by creator. | `Creator`, `PlatformAdmin` |
| PUT | `/pod/storefronts/{id}` | Update storefront markup (cascades listing prices). | `Creator` |
| POST | `/pod/storefronts/{id}/link-channel` | Link storefront to Etsy or Shopify (OCC-guarded). | `Creator` |
| POST | `/pod/storefronts/{id}/suspend-channel` | Suspend a linked storefront channel. | `PlatformAdmin` |
| POST | `/pod/storefronts/{id}/resume-channel` | Resume a suspended storefront channel. | `PlatformAdmin` |
| POST | `/pod/products` | Create a blank product SKU. | `PlatformAdmin` |
| GET | `/pod/products/{id}` | Read a product. | `Creator`, `PlatformAdmin` |
| GET | `/pod/variants/{id}` | Read a variant. | `Creator`, `PlatformAdmin` |
| GET | `/pod/variants` | List variants, optionally filtered by product. | `Creator`, `PlatformAdmin` |
| POST | `/pod/products/{id}/variants` | Create a variant under a product. | `PlatformAdmin` |
| POST | `/pod/creators/{id}/designs` | Upload a design. | `Creator` |
| GET | `/pod/designs/{id}` | Read a design. | `Creator`, `PlatformAdmin` |
| GET | `/pod/creators/{id}/designs` | List a creator's designs. | `Creator`, `PlatformAdmin` |
| POST | `/pod/designs/{id}/mockup` | Generate mockup for a design. | `Creator` |
| POST | `/pod/designs/{id}/approve` | Approve a design. | `PlatformAdmin` |
| POST | `/pod/designs/{id}/reject` | Reject or recall a design (cascades listings, orders). | `PlatformAdmin` |
| POST | `/pod/listings` | Create a listing. | `Creator` |
| GET | `/pod/listings/{id}` | Read a listing. | `Creator`, `PlatformAdmin` |
| GET | `/pod/listings` | List listings, optionally filtered. | `Creator`, `PlatformAdmin` |
| POST | `/pod/listings/{id}/publish` | Publish a listing. | `Creator` |
| POST | `/pod/orders` | Create an order (buyer checkout or creator sample). | `Anonymous`, `Creator` |
| GET | `/pod/orders/{id}` | Read an order. | `Creator`, `PlatformAdmin` |
| GET | `/pod/orders` | List orders, optionally filtered. | `Creator`, `PlatformAdmin` |
| POST | `/pod/orders/{id}/authorize` | Authorize the buyer's payment. | `PlatformAdmin` |
| POST | `/pod/orders/{id}/capture` | Capture the buyer's payment and route. | `PlatformAdmin` |
| POST | `/pod/orders/{id}/refund` | Refund a captured order (partial or full). | `PlatformAdmin` |
| POST | `/pod/orders/{id}/void` | Void a not-yet-captured order. | `PlatformAdmin` |
| POST | `/pod/orders/{id}/cancel` | Cancel a pending order. | `PlatformAdmin` |
| POST | `/pod/orders/{id}/mark-in-print` | Mark an order as printing. | `FulfillmentPartner` |
| POST | `/pod/orders/{id}/mark-shipped` | Mark an order as shipped. | `FulfillmentPartner` |
| POST | `/pod/orders/{id}/mark-delivered` | Mark an order as delivered. | `FulfillmentPartner` |
| GET | `/pod/fulfillment-jobs/{id}` | Read a fulfillment job. | `Creator`, `PlatformAdmin`, `FulfillmentPartner` |
| GET | `/pod/fulfillment-jobs` | List fulfillment jobs, optionally filtered. | `Creator`, `PlatformAdmin`, `FulfillmentPartner` |
| POST | `/pod/fulfillment-jobs/{id}/mark-failed` | Mark a shipped job as failed in transit. | `FulfillmentPartner` |
| POST | `/pod/fulfillment-jobs/{id}/reprint-requests` | Open a reprint request against a failed job. | `PlatformAdmin` |
| GET | `/pod/reprint-requests/{id}` | Read a reprint request. | `Creator`, `PlatformAdmin` |
| GET | `/pod/reprint-requests` | List reprint requests, optionally filtered. | `Creator`, `PlatformAdmin` |
| POST | `/pod/reprint-requests/{id}/approve` | Approve a reprint request. | `PlatformAdmin` |
| POST | `/pod/reprint-requests/{id}/deny` | Deny a reprint request. | `PlatformAdmin` |
| POST | `/pod/fulfillment-partners` | Register a fulfillment partner. | `PlatformAdmin` |
| GET | `/pod/fulfillment-partners/{id}` | Read a fulfillment partner. | `PlatformAdmin`, `FulfillmentPartner` |
| GET | `/pod/fulfillment-partners` | List fulfillment partners, filtered by country or status. | `PlatformAdmin` |
| POST | `/pod/creators/{id}/payout-cycles` | Create a draft payout cycle. | `PlatformAdmin` |
| GET | `/pod/payout-cycles/{id}` | Read a payout cycle. | `Creator`, `PlatformAdmin` |
| GET | `/pod/creators/{id}/payout-cycles` | List a creator's payout cycles. | `Creator`, `PlatformAdmin` |
| POST | `/pod/payout-cycles/{id}/release` | Release a payout cycle. | `PlatformAdmin` |
| POST | `/pod/payout-cycles/{id}/return` | Reverse a released payout within 72h. | `PlatformAdmin` |
| GET | `/pod/storefronts/{id}/channel-sync-events` | Read the append-only sync log. | `Creator`, `PlatformAdmin` |
| POST | `/pod/storefronts/{id}/ingest-channel-order` | Ingest an external-channel order. | `PlatformAdmin` |
| POST | `/_clock/set_current_utc` | Advance the logical clock (test-driving). | `PlatformAdmin` |
| POST | `/_ops/decay-strikes` | Run the full-recompute strike decay (test-driving). | `PlatformAdmin` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_FK_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STOREFRONT_CHANNEL_ALREADY_LINKED` | 409 |
| `ERR_DESIGN_DUPLICATE_HASH` | 409 |
| `ERR_STALE_STOREFRONT_VERSION` | 412 |
| `ERR_CREATOR_NOT_VERIFIED` | 403 |
| `ERR_STRIKE_THRESHOLD_EXCEEDED` | 422 |
| `ERR_DESIGN_CREATOR_MISMATCH` | 422 |
| `ERR_LISTING_NOT_AVAILABLE` | 422 |
| `ERR_SAMPLE_LIMIT_EXCEEDED` | 422 |
| `ERR_MARKUP_OUT_OF_RANGE` | 422 |
| `ERR_PAYOUT_WINDOW_OVERLAP` | 422 |
| `ERR_NO_ELIGIBLE_PARTNER` | 422 |
| `ERR_REFUND_AMOUNT_INVALID` | 422 |
| `ERR_PAYOUT_ZERO_GROSS` | 422 |
| `ERR_PAYOUT_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_REPRINT_ORDER_NOT_SHIPPED` | 422 |
| `ERR_INVALID_REQUEST` | 400 |

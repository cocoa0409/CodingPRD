# Community Group-Buy API — Product Requirements Document

## 1. Introduction

This service is the transactional core of a community group-buying platform. It coordinates a multi-tier hierarchy of group leaders who recruit households inside their residential communities, the suppliers and warehouses that fulfil their orders, the pickup points where neighbours collect their packages, and the after-sales agents and platform administrators who arbitrate disputes and reconcile money.

Two purchase modalities run side by side. **Group-buy campaigns** aggregate household demand against progressive discount thresholds: more participants unlock deeper discounts, and the final price is pinned only when the campaign closes. **Flash campaigns** sell limited stock from a supplier at a fixed price under aggressive concurrency: many customers race for the same units and the platform must allocate fairly without ever overselling. Both modalities feed a shared fulfilment pipeline (multi-warehouse split shipment, cold-chain routing, capacity-bound pickup points, mis-pick reconciliation) and a shared financial pipeline (multi-level commission with tiered rebates, per-line tax withholding, T+N payouts, and refund-driven clawbacks).

The platform also runs a risk-control engine that surfaces alerts for bot orders, fake group-buy fronts, and collusion between leaders and suppliers. Confirmed alerts cascade into leader suspensions and customer holds, and rolling chronic and acute risk scores are recomputed on demand. Every business operation is exposed as an HTTP API mounted under `/communities`-rooted resources and adjacent collections; this document specifies the contract that any conforming implementation must satisfy.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, empty, or carries an unrecognised role string, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` and HTTP 400.

The recognised roles are exactly six: `PlatformAdmin`, `GroupLeader`, `Customer`, `Supplier`, `PickupOperator`, and `CustomerService`. Three of these are **entity-backed**, meaning the value of `X-User-ID` is required to be the `id` of an existing entity instance:

- When `X-User-Role` is `GroupLeader`, `X-User-ID` is the `id` of the acting `GroupLeader`. Ownership checks for leader-bound resources compare the resource's `leader_id` (or its position in the leader subtree rooted at `X-User-ID` via `parent_leader_id`) to the header value.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`. Ownership checks on `Order` mutations and on `AfterSalesCase` evidence submissions compare `Order.customer_id` to the header value.
- When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier`. Ownership checks compare a resource's `supplier_id` (directly, or transitively via `Warehouse.supplier_id`) to the header value.

The other three roles are **opaque** operator identifiers. When `X-User-Role` is `PlatformAdmin`, `PickupOperator`, or `CustomerService`, the value of `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

If the header values are well-formed but resolve to a non-existent entity for an entity-backed role, or if the role is not permitted to invoke the requested endpoint per §4 and §1.7-equivalent prose throughout this document, the request is rejected with `ERR_FORBIDDEN` and HTTP 403. When the role is permitted but the acting `X-User-ID` does not match the resource's owner foreign key (for example, a `Customer` paying for an `Order` whose `customer_id` is a different value, or a `GroupLeader` extending a campaign whose `leader_id` is outside their subtree), the rejection is `ERR_OWNERSHIP_VIOLATION` (HTTP 403). Auth checks are evaluated in order: header presence, role recognition / entity resolution, role-endpoint permission, and only after those does ownership matching apply.

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

List endpoints accept two optional query-string parameters, `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 and has no upper bound besides the implicit total record count. List responses always sort by `created_at` ascending. The `meta` object on list responses populates `limit`, `offset`, `total_count` (the unpaginated cardinality), and `has_more` (true when more records exist beyond the current page). A request with `limit` outside its bounds is rejected with `ERR_VALIDATION_FAILED` and HTTP 400.

### 2.4. Common Resource Properties, Identifiers, and Versioning

Most entities expose four common system-managed fields. Every resource carries an `id`, which is a server-minted UUID with no type prefix; clients must never propose ids on create. Mutable resources additionally carry `created_at`, `updated_at`, and `version`. Both timestamps are ISO 8601 UTC strings with three fractional digits; `created_at` is fixed at creation time and `updated_at` is rewritten on every server-side mutation. The `version` field is an integer that begins at 1 on creation and is incremented by exactly one on every mutation that changes a persisted attribute.

Two entities are exceptions to the common-fields contract. A `ConsolidationBatch` exposes only `id` and `created_at` — neither `updated_at` nor `version` is present on batches. A `RiskAlert` is similarly minimal: only `id` and `created_at` are exposed; alerts have no `updated_at` and no `version` even though they pass through a state machine. Confirming or dismissing an alert mutates `status` and refreshes nothing else externally observable beyond that field.

When an endpoint declares a path parameter chain (for example, `communityId` then `pickupPointId`, or `supplierId` then `warehouseId`), the existence of each level is checked left to right from the outermost segment inward, and the first missing segment determines the not-found error: an unknown community surfaces as `ERR_COMMUNITY_NOT_FOUND` even when the inner pickup-point id is also absent. Each entity has a dedicated not-found code: `ERR_GROUP_LEADER_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND` (group-buy), `ERR_FLASH_CAMPAIGN_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_PICKUP_POINT_NOT_FOUND`, `ERR_AFTER_SALES_CASE_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_RISK_ALERT_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, and `ERR_WAREHOUSE_NOT_FOUND`. Body-referenced ids (for example a `customer_id` or `supplier_id` inside a request payload) trigger the equivalent not-found code if the referenced row is missing.

### 2.5. Time, Periods, and the Logical Clock

Every time-sensitive rule in this system is expressed in terms of `system_period_index` — a deterministic, monotonic, non-negative integer counter advanced exclusively through an admin-only test-driving capability that takes a positive `by_periods` argument with a minimum of 1 and a maximum of 365 and adds it to the global counter. Advancing the clock is the sole mechanism by which time-gated automatic transitions (campaign auto-close past `deadline_period`, payout maturation past `target_period_index`, after-sales-window expiry, and so on) become observable. Calls that would advance by 0 or by a negative amount are rejected with `ERR_VALIDATION_FAILED`.

Three companion sweeps are also exposed under the `_sweep` test-driving namespace. The payout-finalisation sweep performs two sequential passes: in the first pass, every `Order` whose `payment_status` is `REFUND_PENDING` is finalised to `REFUNDED`, the order's `refunded_amount_cents` is increased by the latest in-flight refund amount, the order's `fulfillment_status` is set to `CANCELLED` if it was currently in `NOT_PLANNED`, `PLANNED`, or `DISPATCHED` (and left unchanged if it was in `PICKED_UP` or `COMPLETED`), and any `CommissionEntry` whose `status` was `PENDING_CLAWBACK` and whose source order has just become `REFUNDED` advances to `CLAWED_BACK` (with the leader's outstanding clawback ledger `recovered_clawback_cents` incremented by the entry's `net_rebate_cents` whenever the bundling `Payout` is already `RELEASED`). In the second pass, every `Payout` with `status` equal to `SCHEDULED`, with `target_period_index` not greater than the current `system_period_index`, and with no bundled `CommissionEntry` in `PENDING_CLAWBACK` or `CLAWED_BACK`, advances from `SCHEDULED` to `MATURED`. The campaign auto-close sweep closes every `FORMING` or `EXTENDED` `GroupBuyCampaign` whose `deadline_period` is at or below the current period to either `SUCCEEDED` or `FAILED` based on its `participant_count`. The risk-recompute sweep recomputes `chronic_risk_score` and `acute_risk_score` for all `ACTIVE` leaders.

A `Community` also carries an informational `timezone_offset_minutes` value for human display; it does not influence any rule in this document.

### 2.6. Optimistic Concurrency Control

PATCH endpoints accept an optional `version` field in the request body. When it is present, the server compares it to the current `version` of the targeted resource and rejects the request with `ERR_VERSION_CONFLICT` (HTTP 409) when the values differ. Omitting the `version` field skips the check entirely and lets the mutation proceed at the latest version. Successful mutations always increment `version` by one regardless of whether the client sent the field.

### 2.7. State Cascades, Sibling Versioning, and Cross-Entity Dependencies

Mutations frequently propagate. Suspending a leader auto-closes every `FORMING` and `EXTENDED` `GroupBuyCampaign` owned by that leader as `FAILED`, which in turn forces every child `Order` of those campaigns through the auto-refund cascade described under group-buy in §3 below — `payment_status` goes from `PAID` through `REFUND_PENDING` to `REFUNDED`, `fulfillment_status` (if still `NOT_PLANNED`) ends at `CANCELLED`, and any `Shipment` rows that were already in `PLANNED` or `DISPATCHED` end at `CANCELLED`. Whenever a cascade rewrites a state field on a downstream entity, that entity's `updated_at` is refreshed and its `version` is incremented in the usual manner. Cross-entity preconditions are also enforced: planning shipments on an `Order` requires the parent `GroupBuyCampaign` to be in `SUCCEEDED`, and a `Payout` cannot mature while any of its bundled commission entries is still in `PENDING_CLAWBACK` or `CLAWED_BACK`.

Whenever a parallel scaffold of branches is involved, each branch is realised individually. The `Order` row carries two parallel state dimensions: `payment_status` and `fulfillment_status` evolve on independent rails, and a single mutation may advance one without touching the other. Similarly, when a `RiskAlert` confirmation cascades, each side-effect branch is realised on its own: a `LEADER_SUPPLIER_COLLUSION` confirmation or a `HIGH`-severity confirmation against a `GROUP_LEADER` target advances that leader's `status` to `SUSPENDED`; a `BOT_ORDER` confirmation against a `CUSTOMER` target advances the customer's `status` to `RISK_HOLD`; a `LEADER_SUPPLIER_COLLUSION` confirmation against a `GROUP_LEADER` target additionally increments that leader's `collusion_audit_count` by exactly one.

### 2.8. Monetary Precision and Rounding Policy

All monetary values are stored and exchanged as integer cents. Two distinct rounding regimes apply.

The order-total calculation uses **floor truncation** on the discount step: with the order's pre-discount `subtotal_cents` as the base and the applicable discount expressed in basis points, the discount amount in cents is the base multiplied by the discount basis points, divided by ten thousand, with any fractional cents discarded toward zero; the order total is then the base minus that discount, with the result floored at zero so that no order total is ever negative. The provisional total uses the discount basis points implied by the campaign's `participant_count` at the moment of payment; the settled total uses the basis points pinned at campaign close.

The tax-withholding calculation uses **half-up rounding per line followed by summation**. Each `CommissionEntry` derives a per-line withholding by allocating the entry's `gross_rebate_cents` across the source order's lines proportionally to each line's `unit_price_cents` multiplied by its `quantity`, with floor allocation on every line except the last and the unallocated remainder assigned to the final line. The `tax_withholding_cents` is the sum of the per-line withholdings, where each per-line withholding is the per-line gross multiplied by 700 basis points and divided by ten thousand, rounded half-up to the nearest cent before summation. The two risk scores `chronic_risk_score` and `acute_risk_score` are likewise rounded half-up to two decimal places after their weighted aggregation.

### 2.9. Validation Priority and Error Disclosure

When a single request would fail multiple checks, the server reports the first failure encountered along the following ordered evaluation pipeline. The header-presence check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`) fires first, then role recognition and entity resolution (`ERR_FORBIDDEN`), then role-endpoint permission (`ERR_FORBIDDEN`), then path-parameter existence checked outermost-first (the appropriate `*_NOT_FOUND` code), then body-reference existence, then ownership matching (`ERR_OWNERSHIP_VIOLATION`), then the target's state admits the requested transition (`ERR_INVALID_STATE`).

Two endpoint-specific priority pairs override the general state check. On a group-buy join or pay, the parent campaign's open-window check fires before any business constraint specific to the endpoint, so a campaign that has already advanced past `FORMING` / `EXTENDED` or whose `deadline_period` has been reached surfaces as `ERR_CAMPAIGN_NOT_OPEN` rather than as `ERR_INVALID_STATE`. On a flash purchase, the flash campaign's open-window check fires before the anti-oversell stock check, so a campaign whose `status` is `EXHAUSTED` (current period below `closes_at_period` and `remaining_units` at zero) or `CLOSED` (current period at or beyond `closes_at_period`) surfaces as `ERR_FLASH_CAMPAIGN_NOT_OPEN` regardless of whether a request would have triggered the stock-depletion path.

Plan-shipments enforces a second priority pair: the cold-chain safety check runs before the candidate-warehouse pool check. If the request includes any line with a cold-chain SKU and the supplier owning that SKU has no warehouse with `cold_chain_capable` set to true (regardless of warehouse status), the rejection is `ERR_COLD_CHAIN_REQUIRED`. Only when at least one cold-capable warehouse exists does the empty-pool check apply: when the eligible candidate set after region and active-status filtering is empty, the rejection is `ERR_NO_WAREHOUSE_AVAILABLE`.

Customer-status checks — `ERR_CUSTOMER_BLOCKED` when `Customer.status` is `BLOCKED` and `ERR_CUSTOMER_RISK_HOLD` when `Customer.status` is `RISK_HOLD` — guard order creation, payment, and flash purchase. Optimistic-concurrency conflicts (`ERR_VERSION_CONFLICT`) and generic field validation (`ERR_VALIDATION_FAILED`, including `ERR_INVALID_QUANTITY` when a positive-integer `quantity` is non-positive) sit at the tail of the pipeline.

## 3. Business Logic & Workflows

### 3.1. Communities, Pickup Points, and the Group-Leader Hierarchy

A `Community` is the geographic unit within which group-buy demand is aggregated. Each community is created with a unique `name`, a `region_code` (such as `CN-SH-01`) used both for warehouse-distance ranking and for SKU campaign-overlap scoping, and an optional `timezone_offset_minutes` field that is stored for human display only. New communities open in `ACTIVE` status; an administrator may move a community to `FROZEN`, which suspends new operations within it.

A `PickupPoint` belongs to exactly one community and is created with a `name`, an integer `capacity_packages` (the maximum number of packages it may simultaneously hold across the `AT_PICKUP`, `MIS_PICK`, and `RECONCILED` shipment statuses, computed dynamically as `held_package_count`), and an optional `cold_storage_capable` flag (defaulting to false). A pickup point begins in `ACTIVE` status and may be moved to `DISABLED`. The point's load condition is reported via a summary capability that exposes `held_package_count`, `capacity_packages`, a load factor, and a load state derived from that factor.

A `GroupLeader` is created against a community with an optional `parent_leader_id` (a self-reference to an upstream leader within the same community) and a `display_name`. A leader's `tier` is a computed integer: a leader without a parent is `tier` 1; a leader whose parent is in `tier` N is in `tier` N + 1; and the platform never permits a `tier` greater than 3 — submitting a `parent_leader_id` whose tier is already 3 is rejected with `ERR_VALIDATION_FAILED`. Newly created leaders begin in `PENDING_REVIEW`; they enter `ACTIVE` through approval by a `PlatformAdmin`, which requires the parent community to be in `ACTIVE` status. Two further transitions are admin-only: suspension (admin-driven, or system-driven when a `RiskAlert` is confirmed at `HIGH` severity against this leader) moves an `ACTIVE` leader to `SUSPENDED` and triggers the cascade described below; reinstatement returns a `SUSPENDED` leader to `ACTIVE` provided no `OPEN` `RiskAlert` of `HIGH` severity is currently targeting this leader, and deactivation moves a leader from `PENDING_REVIEW`, `ACTIVE`, or `SUSPENDED` to the terminal `DEACTIVATED` state provided no `FORMING` or `EXTENDED` campaign is currently owned by that leader. Leaders also expose computed audit counters: `lifetime_settled_orders`, `chronic_risk_score`, `acute_risk_score`, `collusion_audit_count`, and `created_period_index`.

When suspension fires, every `FORMING` and `EXTENDED` `GroupBuyCampaign` whose `leader_id` is the suspended leader auto-closes as `FAILED`. The downstream order, refund, and shipment-cancellation cascades are described in §3.3 and §3.6.

### 3.2. Customers, Suppliers, and Warehouses

A `Customer` is created in a home community (referenced via `community_id` at creation, snapshotted on the customer thereafter) with a `display_name`. New customers begin in `ACTIVE` status; confirmed risk alerts may move them to `RISK_HOLD`, and platform action may move them to `BLOCKED`. The customer also exposes `lifetime_completed_orders`, a counter that increments by one each time one of their orders reaches `COMPLETED`.

A `Supplier` is created with a `name` and begins in `ACTIVE`. Suppliers expose `Warehouse` rows under their own subtree. A warehouse is created with a `name`, a `region_code` (matched against the buying community's `region_code` for distance ranking), an optional `cold_chain_capable` flag (defaulting to false), an optional `handling_periods` integer of at least 1 (defaulting to 1, used to predict ETA for non-cold shipments), and an optional `cold_handling_periods` integer of at least 1 (defaulting to 1, used to predict ETA for cold-chain shipments). At creation, the request may also include an `initial_status` that overrides the default; otherwise the warehouse opens in `ACTIVE`. An administrator may later move a warehouse to `DISABLED`.

### 3.3. Group-Buy Campaign Lifecycle

A `GroupBuyCampaign` is created by a `GroupLeader` against the leader's home community. The creation payload supplies a `supplier_id` (the supplier of the campaign SKU, required at creation so that warehouse selection can run later), a `sku`, an optional `cold_chain_required` flag, a `unit_price_cents` integer greater than zero, an ordered ascending `discount_tiers` array whose entries each carry a `min_participants` integer and a `discount_basis_points` integer, an `opens_at_period`, a `deadline_period`, and an optional `cross_community_partner_leader_ids` array of up to four other leader ids that participate in cross-community team-up. Each partner leader id must reference a leader in `ACTIVE` status whose `tier` is at most 2 and whose home community differs from the creating leader's community. The campaign begins in `FORMING`, snapshots the creator's `community_id`, and exposes computed counters `participant_count`, `extension_count`, `settled_tier_index`, and `settled_discount_basis_points` (the latter two null until close).

Two campaigns must not overlap. When the creating leader's community already holds a campaign on the same `sku` whose half-open window between `opens_at_period` (inclusive) and `deadline_period` (exclusive) intersects the proposed window, and that existing campaign is in `FORMING`, `EXTENDED`, or `SUCCEEDED`, the new request is rejected with `ERR_COMMUNITY_CAMPAIGN_OVERLAP`. Adjacent windows where one campaign's `deadline_period` equals the next campaign's `opens_at_period` are explicitly permitted because the interval is half-open. When two creation requests race for the same `(community_id, sku)` window, the platform serialises on that window registration: exactly one creation succeeds, and the loser receives `ERR_COMMUNITY_CAMPAIGN_OVERLAP`.

A campaign that has not yet hit its deadline may be **extended once** by its owning leader. Extension transitions the campaign from `FORMING` to `EXTENDED`, requires `extension_count` to currently be zero, requires `system_period_index` to still be below `deadline_period`, and requires `participant_count` to have already reached at least the ceiling of 0.6 multiplied by the highest `min_participants` in the campaign's `discount_tiers`. The transition shifts `deadline_period` forward by 2 periods and increments `extension_count` by exactly one. Once that bookkeeping is recorded, the campaign returns to its `FORMING` rail (a system-driven `EXTENDED → FORMING` transition is recorded for state-machine auditing on the same period, idempotently).

A campaign closes when the owning leader (or an administrator) acts explicitly, or when the auto-close sweep encounters a campaign whose `deadline_period` has been reached. Close branches into `SUCCEEDED` or `FAILED` based on `participant_count`. The threshold is the smallest entry of `discount_tiers`: the campaign succeeds when `participant_count` is at least `discount_tiers[0].min_participants` and fails otherwise. On `SUCCEEDED`, the platform pins `settled_tier_index` and `settled_discount_basis_points` per the discount-tier-selection rule below, advances every child `Order` whose `payment_status` was `PAID` to `SETTLED`, pins each such order's `settled_total_cents` per the order-total rule below, and generates `CommissionEntry` rows for the primary, secondary, and upstream beneficiaries per the rebate and tax-withholding rules below. On `FAILED`, no commission entries are generated, every child `Order` whose `payment_status` was `PAID` flows through the auto-refund cascade — `payment_status` advances from `PAID` to `REFUND_PENDING` (synchronous) and from `REFUND_PENDING` to `REFUNDED` when the next payout-finalisation sweep runs, with `refunded_amount_cents` increased by the order's full `subtotal_cents`; the order's `fulfillment_status` is set to `CANCELLED` from `NOT_PLANNED`; and any child `Shipment` row in `PLANNED` is moved to `CANCELLED`. Once a `SUCCEEDED` or `FAILED` campaign's child orders have all reached terminal payment-and-fulfillment pairs, the campaign may be `finalize`d, advancing `status` to `CLOSED`.

#### Discount-Tier Selection

Tier selection is purely threshold-driven. Given the current `participant_count`, the platform considers every `discount_tiers` entry whose `min_participants` is at most `participant_count`; among those qualifying tiers, the platform picks the entry with the largest `min_participants` and uses that entry's index (zero-based) as `settled_tier_index` and that entry's `discount_basis_points` as `settled_discount_basis_points`. When no tier qualifies, `settled_tier_index` is null and `settled_discount_basis_points` is zero. Tier qualification is inclusive on `min_participants`: a `participant_count` exactly equal to a tier's `min_participants` qualifies for that tier.

#### Order Total

The order-total calculation runs in two variants. The provisional variant pins `provisional_discount_basis_points` and `provisional_total_cents` at the moment of payment using the discount-tier-selection result evaluated against `participant_count` as observed when the pay request commits. The final variant pins `settled_total_cents` at campaign close using the campaign's pinned `settled_discount_basis_points`. In both variants, the discount amount is the order's `subtotal_cents` multiplied by the selected discount basis points and divided by ten thousand with floor truncation; the order total is `subtotal_cents` minus that discount amount, with the result floored at zero so that no order total is ever negative.

### 3.4. Customer Participation: Joining and Paying

A customer joins a group-buy campaign by submitting an order against the campaign with their own `customer_id` and an array of `line_items`. Each line item carries a `sku`, a `unit_price_cents`, and a `quantity`; the array must be non-empty and contain at most five entries. The primary line is the campaign's own `sku`; additional lines are permitted only when they reference the `sku` of another `SUCCEEDED` campaign owned by a leader in the same subtree (cross-group bundling). A non-positive `quantity` is rejected with `ERR_INVALID_QUANTITY`. The newly created order discriminates its polymorphic campaign reference via `campaign_kind` set to `GROUP_BUY` and stores the campaign id in `campaign_id`; `flash_granted_units` is null on group-buy orders. The order begins with `payment_status` of `PENDING_PAY` and `fulfillment_status` of `NOT_PLANNED`. At creation, the platform pins `subtotal_cents` to the sum of `unit_price_cents` multiplied by `quantity` across every line; `subtotal_cents` is never recomputed thereafter. The order also captures `created_period_index` and assigns a global monotonic `created_seq` used for fairness ordering.

Two further checks guard joining. The campaign must be in `FORMING` or `EXTENDED` and the current `system_period_index` must be below `deadline_period`; otherwise the join is rejected with `ERR_CAMPAIGN_NOT_OPEN`. A customer may have at most one order in `PENDING_PAY`, `PAID`, `SETTLED`, or `PARTIALLY_REFUNDED` per campaign; a second join attempt is rejected with `ERR_DUPLICATE_PARTICIPATION`. A customer in `BLOCKED` status is rejected with `ERR_CUSTOMER_BLOCKED`; a customer in `RISK_HOLD` is rejected with `ERR_CUSTOMER_RISK_HOLD`.

Paying an order advances `payment_status` from `PENDING_PAY` to `PAID`. The pay action additionally requires the parent campaign to still be open (the same `FORMING`-or-`EXTENDED` plus pre-deadline check; failure surfaces as `ERR_CAMPAIGN_NOT_OPEN`) and the customer to still be in `ACTIVE`. On commit, the order's `paid_period_index` is stamped with the current `system_period_index`, the campaign's `participant_count` is recomputed, and the provisional totals are pinned. When a customer's pay request races with the leader's close request, the platform serialises on `GroupBuyCampaign.status`: if close wins, the pay loser sees `ERR_CAMPAIGN_NOT_OPEN`; if pay wins, close still proceeds but observes the new participant. On `SUCCEEDED`, every `PAID` order also advances to `SETTLED` and has its `settled_total_cents` pinned.

A `Customer` may not directly cancel a group-buy order; the after-sales flow governs all post-payment modifications. A direct cancel call against a group-buy order is rejected with `ERR_INVALID_STATE`. Flash orders, by contrast, may be cancelled directly before they reach `AT_PICKUP` (see §3.5).

### 3.5. Flash Purchase: Tiered Caps, Anti-Oversell, and Fairness

A `Supplier` (or an administrator) creates a `FlashCampaign` against a supplier with a `sku`, an optional `cold_chain_required` flag, a `unit_price_cents` integer greater than zero, a `tier_caps` array of objects each carrying a `tier` integer and a `max_units` integer that defines the per-customer cap for that tier window, a `total_stock` integer greater than zero, an `opens_at_period`, and a `closes_at_period`. The campaign's `status` is computed from the clock and inventory: `SCHEDULED` before `opens_at_period`, `OPEN` from `opens_at_period` until `closes_at_period` while inventory remains, `EXHAUSTED` while still inside the window when `remaining_units` is zero, and `CLOSED` once `system_period_index` reaches `closes_at_period`. Flash campaigns expose computed counters `locked_units`, `allocated_units`, and `remaining_units`, where `remaining_units` equals `total_stock` minus `locked_units` minus `allocated_units`.

A flash purchase by a `Customer` carries a single `requested_units` integer. The platform first verifies that the campaign is `OPEN`; an `EXHAUSTED` or `CLOSED` campaign rejects with `ERR_FLASH_CAMPAIGN_NOT_OPEN` regardless of the requested amount. Only after that state check does the anti-oversell check apply: if `remaining_units` is below `requested_units`, the request fails with `ERR_FLASH_STOCK_DEPLETED`. The customer must additionally be in `ACTIVE` (`BLOCKED` rejects with `ERR_CUSTOMER_BLOCKED`; `RISK_HOLD` rejects with `ERR_CUSTOMER_RISK_HOLD`).

The platform allocates units per the **fairness-weighted flash allocation** rule. A per-campaign monotonic counter `current_request_seq` starts at zero and increments on each successful purchase. The acting customer's tier window is the value of `current_request_seq` divided by 100 (the customers-per-tier constant) using floor division, capped at the last index of `tier_caps`; the per-customer cap is that tier's `max_units`. Eligibility requires `requested_units` to be strictly greater than zero and not greater than the per-customer cap. The granted quantity is the minimum of `requested_units`, `remaining_units`, and the per-customer cap; when this minimum is zero, the platform returns `ERR_FLASH_STOCK_DEPLETED`. When multiple purchase requests target the same campaign in the same period, the platform serialises them by `Customer.lifetime_completed_orders` descending, breaking ties by the customer's `created_at` ascending, and finally by the customer's `id` lexicographically ascending. Two simultaneous requests racing for the last unit serialise to exactly one winner; the loser receives `ERR_FLASH_STOCK_DEPLETED`.

On a successful purchase, the platform increases `allocated_units` by the granted amount, decreases `remaining_units` by the same amount (atomically; `locked_units` remains zero because flash purchases auto-settle), and creates an `Order` with `campaign_kind` set to `FLASH`, `campaign_id` set to the flash campaign's id, `flash_granted_units` set to the granted amount, a single line item carrying the campaign's `sku`, the campaign's `unit_price_cents`, and a `quantity` equal to the granted amount, `subtotal_cents` set to `unit_price_cents` multiplied by the granted amount, `settled_total_cents` set equal to `subtotal_cents` (flash orders carry no discount), `payment_status` set directly to `SETTLED`, and `fulfillment_status` set to `NOT_PLANNED`. When `remaining_units` drops to zero as a result, the campaign's `status` advances to `EXHAUSTED`. Flash orders never produce commission entries — commission settlement applies only to group-buy.

A flash order may be cancelled by its acting customer at any time before it reaches `AT_PICKUP`. Cancellation moves `payment_status` to `REFUNDED` and `fulfillment_status` to `CANCELLED`, and any non-terminal child `Shipment` is moved to `CANCELLED`. The platform additionally rolls back the inventory: `allocated_units` is decreased by the order's `flash_granted_units` and `remaining_units` is increased by the same amount; if the campaign's `status` was `EXHAUSTED`, the current period is still below `closes_at_period`, and `remaining_units` is now greater than zero, the campaign returns to `OPEN`.

### 3.6. Fulfilment: Shipment Planning, Dispatch, and Pickup

After a group-buy campaign succeeds (or after a flash purchase commits), the order is eligible for fulfilment. Planning shipments is performed by the supplier owning every shipped `sku` (or by an administrator) and requires the order to be in `payment_status` `SETTLED` and, for group-buy orders, the parent campaign to be in `SUCCEEDED`. The request carries a `shipment_plan` array; each element carries a `pickup_point_id` and a `line_units` array whose entries each carry a `sku` and a `quantity` representing the subset of the order's line items shipped to that destination. On commit, one `Shipment` row is created per element with `status` set to `PLANNED` and the order's `fulfillment_status` advances from `NOT_PLANNED` to `PLANNED`. The platform automatically computes each shipment's `cold_chain_segment` as true when any of its lines is a cold-chain SKU.

The platform selects each shipment's `warehouse_id` server-side. The candidate set is the supplier's `Warehouse` rows whose `status` is `ACTIVE`; when `cold_chain_segment` is true, the candidates are further filtered to those with `cold_chain_capable` set to true. The selection's primary ranking key is region match, where a warehouse whose `region_code` equals the order community's `region_code` ranks ahead of one that does not; the tie-break is `created_period_index` ascending, and if still tied, `id` lexicographically ascending. When no candidate exists at all (cold or otherwise), the safety-prioritised cold-chain check runs first: if any line is cold-chain and the supplier has no warehouse with `cold_chain_capable` set to true (regardless of `status`), the rejection is `ERR_COLD_CHAIN_REQUIRED`; otherwise the rejection for an empty post-filter set is `ERR_NO_WAREHOUSE_AVAILABLE`.

Dispatching a shipment moves `status` from `PLANNED` to `DISPATCHED`, stamps `dispatched_period_index` with the current period, and pins `predicted_eta_period_index`. Predicted ETA is `dispatched_period_index` plus the warehouse's `cold_handling_periods` when `cold_chain_segment` is true and `dispatched_period_index` plus the warehouse's `handling_periods` otherwise. Once every child shipment of an order has reached `DISPATCHED`, the order's `fulfillment_status` advances from `PLANNED` to `DISPATCHED`. Two suppliers attempting to dispatch the same shipment simultaneously serialise on the shipment's `status`: exactly one transition succeeds and the loser observes `ERR_INVALID_STATE`.

When the shipment arrives at its destination pickup point, the supplier marks it `AT_PICKUP`, advancing its `status` from `DISPATCHED` to `AT_PICKUP`. Two preconditions guard this transition. First, the destination's `held_package_count` plus one must be at most `capacity_packages` — that is, the destination strictly enforces the boundary inclusively, so `held_package_count` may equal `capacity_packages` after the increment but never exceed it; a request that would push the held count to `capacity_packages` plus one is rejected with `ERR_PICKUP_POINT_AT_CAPACITY`. Second, when `cold_chain_segment` is true, the destination must have `cold_storage_capable` set to true; otherwise the rejection is `ERR_PICKUP_POINT_COLD_INCOMPATIBLE`. On commit, the pickup point's `held_package_count` is increased by exactly one. Once every child shipment of an order has reached `AT_PICKUP` (or `RECONCILED`, see §3.7), the order's `fulfillment_status` advances from `DISPATCHED` to `AT_PICKUP`.

The acting customer confirms pickup once all child shipments are at the destination: every child shipment must be in `AT_PICKUP` or `RECONCILED`. The transition advances the order's `fulfillment_status` from `AT_PICKUP` to `PICKED_UP` and moves every child shipment to `DELIVERED`, decrementing the destination's `held_package_count` by exactly one per shipment. When seven periods elapse beyond the order's `PICKED_UP` transition with no after-sales case opened, the order auto-finalises to `COMPLETED` (driven by the clock-advance hooks); on this transition, the customer's `lifetime_completed_orders` is increased by one, and every `PENDING` `CommissionEntry` derived from this order remains eligible for `SETTLED` at the next payout assembly.

When an upstream cascade demands cancellation (parent campaign `FAILED`, after-sales-driven full refund, or a flash-order cancel), the order's `fulfillment_status` advances to `CANCELLED` from `NOT_PLANNED`, `PLANNED`, or `DISPATCHED`, and any non-terminal child `Shipment` is moved to `CANCELLED`. A shipment in `PLANNED` or `DISPATCHED` is similarly cancelled when its parent order's fulfillment cascade fires.

### 3.7. Pickup Operations: Mis-Pick, Reconciliation, and Consolidation

A `PickupOperator` who notices a sorting error reports a mis-pick, advancing the affected shipment from `AT_PICKUP` to `MIS_PICK`. Reconciling a mis-pick advances the shipment from `MIS_PICK` to `RECONCILED`; a system-driven idempotent transition then returns the shipment to `AT_PICKUP`-equivalent (recorded as `RECONCILED` to `AT_PICKUP`), so the shipment becomes eligible again for the customer's pickup confirmation and counts identically against `capacity_packages` while held.

Operators may consolidate multiple shipments into a `ConsolidationBatch` covering an inclusive period window between `window_start_period` and `window_end_period`. The batch is created against a pickup point with the two window endpoints (where `window_end_period` must be at least `window_start_period`) and a `shipment_ids` array. Each shipment id must currently be in `AT_PICKUP` at the same pickup point. To prevent overlapping consolidations, the platform expands each batch's window by a buffer of one period on each side (so the registered closed interval runs from `window_start_period` minus one to `window_end_period` plus one) and rejects any new batch whose buffered window intersects any existing batch on the same pickup point with `ERR_CONSOLIDATION_WINDOW_OVERLAP`. Two creation attempts that race on the same pickup point and overlapping buffered windows serialise to exactly one winner; the loser receives `ERR_CONSOLIDATION_WINDOW_OVERLAP`. A new batch begins in `OPEN` and may later move to `CLOSED`. Batches expose only `id` and `created_at` from the common-fields set and additionally store their own `pickup_point_id` and `shipment_ids`.

The pickup-point summary reports the destination's load. The load factor is `held_package_count` divided by `capacity_packages`, expressed to two decimal places. The load state derived from that factor is `HEALTHY` while the factor is below 0.75, `ELEVATED` when the factor is at least 0.75 and below 1.00, and `FULL` when the factor is at or above 1.00.

### 3.8. After-Sales: Filing, Evidence, Arbitration, and Resolution

An `AfterSalesCase` is opened by a `Customer` against an order they own. The filing payload supplies a `case_type` and a `requested_amount_cents`. The `case_type` is one of `REFUND_ONLY` (no return, full refund of the requested amount), `RETURN_AND_REFUND` (the customer returns goods in exchange for the refund), or `PARTIAL_COMPENSATION` (the customer keeps the goods and receives a partial credit against the order's already-settled total). Two temporal constraints apply: the case may be filed only within seven periods after the parent order's `fulfillment_status` reaches `PICKED_UP` (a later filing is rejected with `ERR_AFTER_SALES_WINDOW_EXPIRED`), and the order may carry at most one open (non-terminal) case at a time (a second filing while one is open is rejected with `ERR_AFTER_SALES_ALREADY_OPEN`). The requested amount must be a positive integer and must not exceed the order's `settled_total_cents` minus its `refunded_amount_cents`; otherwise the rejection is `ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING`. The case begins in `FILED`, captures `filed_period_index`, and exposes computed `evidence_round` (initially zero, capped at 2) and `resolved_amount_cents`.

A `CustomerService` agent moves the case from `FILED` to `UNDER_REVIEW`, then optionally requests evidence, advancing it to `EVIDENCE_REQUESTED`. Evidence requests require the case's `evidence_round` to currently be below 2; a third request is rejected with `ERR_INVALID_STATE`. The customer responds by submitting evidence, advancing the case from `EVIDENCE_REQUESTED` back to `UNDER_REVIEW` and incrementing `evidence_round` by exactly one. A case that has already cycled through evidence at least once may be escalated by the agent to `ARBITRATION`, where only a `PlatformAdmin` may resolve it; an escalation request whose `evidence_round` is still zero is rejected with `ERR_INVALID_STATE`.

Resolution carries an `outcome` of `REFUND_ONLY`, `RETURN_REFUND`, `PARTIAL_COMPENSATION`, or `REJECT`. The four resolution branches each have explicit semantics and side-effects:

- `REFUND_ONLY` requires the case's `case_type` to be `REFUND_ONLY`, sets `resolved_amount_cents` to the case's `requested_amount_cents`, and synchronously advances the parent order's `payment_status` to `REFUND_PENDING` (the further `REFUND_PENDING` to `REFUNDED` transition is driven by the next payout-finalisation sweep). Every `PENDING` `CommissionEntry` derived from the order moves to `PENDING_CLAWBACK`; any `Payout` already bundling those entries has its `total_amount_cents` recomputed with the clawback-flagged entries excluded from the total while `bundled_entry_ids` is preserved for audit.
- `RETURN_REFUND` requires the case's `case_type` to be `RETURN_AND_REFUND` and additionally requires the parent order's `fulfillment_status` to be `PICKED_UP` or `COMPLETED`. The side-effects are otherwise identical to `REFUND_ONLY`: `resolved_amount_cents` is the requested amount, the order moves to `REFUND_PENDING`, and every `PENDING` commission entry derived from the order moves to `PENDING_CLAWBACK`.
- `PARTIAL_COMPENSATION` requires the case's `case_type` to be `PARTIAL_COMPENSATION`, sets `resolved_amount_cents` to the requested amount, advances the parent order's `payment_status` to `PARTIALLY_REFUNDED`, and increases the order's `refunded_amount_cents` by `resolved_amount_cents`. Commission entries on this order have their gross rebate proportionally reduced and their status remains `PENDING` or `SETTLED` (no clawback applies unless a full refund occurs).
- `REJECT` requires no case-type match; the case advances to `REJECTED` with `resolved_amount_cents` set to zero. When this rejection follows a previous transition that pushed the order to `REFUND_PENDING`, the `PENDING_CLAWBACK` entries return to `PENDING` (the system-driven revert transition).

### 3.9. Commission, Payouts, and Clawbacks

When a group-buy campaign succeeds, the platform generates `CommissionEntry` rows per beneficiary on every settled child order. A beneficiary's `leader_role` is one of `PRIMARY` (the campaign-owning leader), `SECONDARY` (a participant in the cross-community team-up — that is, a leader in `cross_community_partner_leader_ids`), or `UPSTREAM` (a leader on the `parent_leader_id` chain above the primary). The order's source id and beneficiary leader id are stored on the entry as `order_id` and `leader_id`, and the entry begins with `payout_id` set to null.

#### Tiered Rebate

The gross rebate computation runs from three inputs: the beneficiary's `leader_role`, the primary leader's `tier`, and either the secondary partner's `tier` or, for upstream beneficiaries, the upstream depth (the number of `parent_leader_id` hops between the primary and the upstream leader, capped at 2). Three rate tables apply. The primary rate by tier is 800 basis points for `tier` 1, 500 basis points for `tier` 2, and 300 basis points for `tier` 3. The secondary bonus rate by tier is 200 basis points for `tier` 1 and 100 basis points for `tier` 2. The upstream rate by depth is 150 basis points for depth 1 and 50 basis points for depth 2. The rebate cap ratio is 1500 basis points (15 percent of the order's `settled_total_cents`).

The gross rate is selected by role. For a `PRIMARY` beneficiary, the gross rate is the primary rate at the primary's tier plus the secondary bonus rate at the cross-community partner's tier (with the bonus rate treated as zero when the campaign has no qualifying secondary partner). For a `SECONDARY` beneficiary, the gross rate is the secondary bonus rate at that secondary partner's tier. For an `UPSTREAM` beneficiary, the gross rate is the upstream rate at the upstream depth. After role selection, the rate is capped at 1500 basis points. The `gross_rebate_cents` is then the order's `settled_total_cents` multiplied by the capped rate and divided by ten thousand, with floor truncation.

#### Tax Withholding and Net Rebate

The withholding allocation begins by distributing the entry's `gross_rebate_cents` across the source order's `line_items` in proportion to each line's `unit_price_cents` multiplied by its `quantity` (the line's weight) and the order's total weight (the sum of every line's weight, equal to `subtotal_cents`). For every line except the last, the per-line gross is the entry's `gross_rebate_cents` multiplied by that line's weight and divided by the total weight, with floor truncation; the last line absorbs the remainder so that the per-line shares always sum to `gross_rebate_cents`. The per-line withholding is the per-line gross multiplied by 700 basis points and divided by ten thousand, rounded half-up to the nearest cent. The entry's `tax_withholding_cents` is the sum of those rounded per-line withholdings (round-per-line, then sum — this differs in cents from a sum-then-round computation when the per-line products leave fractional residues). The `net_rebate_cents` is `gross_rebate_cents` minus `tax_withholding_cents`.

#### T+N Payout Schedule

Each newly created `CommissionEntry` is stamped with a `payout_target_period_index` equal to the source order's `paid_period_index` plus the payout lag implied by the primary leader's `tier`: 3 periods for `tier` 1, 5 periods for `tier` 2, and 7 periods for `tier` 3.

#### Payout Assembly, Maturity, and Release

A `Payout` is assembled for a target leader and a `target_period_index`; the assembly bundles every `CommissionEntry` whose `leader_id` matches the target leader and whose `payout_target_period_index` is at or below the requested target period, regardless of whether those entries are in `PENDING` or `PENDING_CLAWBACK`. The new payout begins in `SCHEDULED` with `bundled_entry_ids` populated, `total_amount_cents` set to the sum of `net_rebate_cents` over bundled entries, and the bundled entries are marked with this payout's id (their `payout_id` field). A payout may be cancelled while still in `SCHEDULED`; cancellation moves `status` to `CANCELLED` and returns its bundled entries to the unbundled pool by setting their `payout_id` back to null so that they become eligible for the next assembly.

Maturation is driven by the payout-finalisation sweep. A `SCHEDULED` payout advances to `MATURED` only when the current `system_period_index` is at or above the payout's `target_period_index` and **none** of the bundled entries is currently in `PENDING_CLAWBACK` or `CLAWED_BACK`. While any bundled entry is still in clawback, the payout remains in `SCHEDULED` after the sweep — observably, the same condition rejects an explicit release attempt with `ERR_PAYOUT_HAS_PENDING_CLAWBACK`. A release request also requires the payout to currently be in `MATURED`; releasing a `SCHEDULED` payout is rejected with `ERR_PAYOUT_NOT_MATURED`. On `MATURED` to `RELEASED`, every bundled `CommissionEntry` advances from `PENDING` to `SETTLED`.

#### Clawback Lifecycle

When an order's `payment_status` advances to `REFUND_PENDING` (whether through campaign failure, a flash-order cancel, or an after-sales `REFUND_ONLY` / `RETURN_REFUND` resolution), every `PENDING` `CommissionEntry` derived from that order advances from `PENDING` to `PENDING_CLAWBACK`. When the order then becomes `REFUNDED`, those entries advance from `PENDING_CLAWBACK` to `CLAWED_BACK`; any `SCHEDULED` `Payout` that bundled them has its `total_amount_cents` recomputed with the clawback entries excluded, and any `RELEASED` payout that had already disbursed those amounts has the leader's `recovered_clawback_cents` ledger increased by each entry's `net_rebate_cents`. When an after-sales case resolves with `REJECT` and the order returns from `REFUND_PENDING` back to its prior payment status, the system reverts each `PENDING_CLAWBACK` entry back to `PENDING`. Partial-compensation resolutions never trigger clawback; commission entries on a partially-refunded order remain in `PENDING` or `SETTLED` and have their gross rebate proportionally adjusted.

### 3.10. Risk Alerts and Leader Risk Scores

A `RiskAlert` is opened by an administrator against one of three target kinds. The supported pairings are `BOT_ORDER` against a `CUSTOMER` or `ORDER` target, `FAKE_GROUP_BUY` against a `GROUP_LEADER` target, and `LEADER_SUPPLIER_COLLUSION` against a `GROUP_LEADER` target with a non-null `supporting_supplier_id`. An alert that violates this pairing rule is rejected with `ERR_VALIDATION_FAILED`. The alert carries a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a `target_id`, and is stamped with `created_period_index` for use by the rolling-window aggregations below. Alerts begin in `OPEN`.

Confirming an alert advances `status` to `CONFIRMED` and triggers a parallel cascade. When the alert is `LEADER_SUPPLIER_COLLUSION` against a `GROUP_LEADER`, or when its `severity` is `HIGH` against a `GROUP_LEADER`, the targeted `GroupLeader` advances from `ACTIVE` to `SUSPENDED` (with the leader-suspension cascade described under §3.1 firing). When the alert is `BOT_ORDER` against a `CUSTOMER`, the targeted `Customer` advances from `ACTIVE` to `RISK_HOLD`. When the alert is `LEADER_SUPPLIER_COLLUSION` against a `GROUP_LEADER`, the targeted leader's `collusion_audit_count` is increased by exactly one. Dismissing an alert advances `status` to `DISMISSED` with no further cascade.

#### Chronic Risk Score (30-period rolling window)

The chronic score for a leader counts three signal kinds within a window of the last 30 periods (inclusive of the current period — that is, alerts whose `created_period_index` falls between the current period minus 29 and the current period). The first count is the number of confirmed `BOT_ORDER` alerts whose `target_kind` is `ORDER` and whose targeted order's parent campaign's `leader_id` matches this leader. The second count is the number of group-buy campaigns owned by this leader that closed in `FAILED` with `participant_count` equal to zero, where the campaign's close period falls in the window. The third count is the number of confirmed `LEADER_SUPPLIER_COLLUSION` alerts targeting this leader within the window.

Each count is divided by 30 to obtain its density. The raw chronic score is the bot density multiplied by 0.30, plus the fake-group density multiplied by 0.40, plus the collusion density multiplied by 0.30, with the resulting weighted average then multiplied by 100. The `chronic_risk_score` is the minimum of the raw value and 100, rounded half-up to two decimal places.

#### Acute Risk Score (5-period rolling window)

The acute score is computed identically except that the window narrows to the last 5 periods (inclusive — `created_period_index` between the current period minus 4 and the current period), the densities divide by 5, the weights are 0.50 for bot, 0.30 for fake-group, and 0.20 for collusion, and the weighted average (multiplied by 100) is additionally multiplied by 1.5. The `acute_risk_score` is the minimum of that raw value and 100, rounded half-up to two decimal places.

Both scores are recomputed on confirmation of a risk alert against the leader, on every clock-advance, and on demand through the recompute-risk sweep.

## 4. Endpoint Definitions

All endpoints are mounted at the document root described in §1. New resources are created with HTTP 201 Created. Modifications, reads, and lifecycle transitions return 200 OK. List endpoints honour the pagination contract from §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/_clock/advance` | Advance the deterministic global `system_period_index` by `by_periods`. | PlatformAdmin |
| POST | `/_sweep/run-payouts` | Run the two-pass payout-finalisation sweep (refund finalisation, then payout maturation). | PlatformAdmin |
| POST | `/_sweep/auto-close-campaigns` | Close every `FORMING` / `EXTENDED` campaign whose deadline has been reached. | PlatformAdmin |
| POST | `/_sweep/recompute-risk` | Recompute chronic and acute risk scores for all `ACTIVE` leaders. | PlatformAdmin |
| POST | `/communities` | Create a community. | PlatformAdmin |
| GET | `/communities` | List communities. | PlatformAdmin, GroupLeader, Customer, Supplier, PickupOperator, CustomerService |
| POST | `/communities/{communityId}/group-leaders` | Create a group leader (status defaults to `PENDING_REVIEW`). | PlatformAdmin |
| GET | `/group-leaders/{leaderId}` | Get a group leader. | PlatformAdmin, GroupLeader, CustomerService |
| POST | `/group-leaders/{leaderId}/approve` | Approve a leader (`PENDING_REVIEW` → `ACTIVE`). | PlatformAdmin |
| POST | `/group-leaders/{leaderId}/suspend` | Suspend a leader (`ACTIVE` → `SUSPENDED`) with cascade. | PlatformAdmin |
| POST | `/group-leaders/{leaderId}/reinstate` | Reinstate a suspended leader (`SUSPENDED` → `ACTIVE`). | PlatformAdmin |
| POST | `/group-leaders/{leaderId}/deactivate` | Deactivate a leader (terminal `DEACTIVATED`). | PlatformAdmin |
| POST | `/customers` | Create a customer. | PlatformAdmin |
| GET | `/customers/{customerId}` | Get a customer. | PlatformAdmin, Customer, CustomerService |
| POST | `/suppliers` | Create a supplier. | PlatformAdmin |
| POST | `/suppliers/{supplierId}/warehouses` | Create a warehouse for a supplier. | PlatformAdmin, Supplier |
| GET | `/suppliers/{supplierId}/warehouses` | List a supplier's warehouses. | PlatformAdmin, Supplier |
| POST | `/suppliers/{supplierId}/flash-campaigns` | Create a flash campaign. | Supplier, PlatformAdmin |
| GET | `/flash-campaigns/{flashCampaignId}` | Get a flash campaign (exposes `total_stock`, `locked_units`, `allocated_units`, `remaining_units`, `status`). | PlatformAdmin, Supplier, Customer |
| POST | `/flash-campaigns/{flashCampaignId}/purchase` | Purchase units (anti-oversell, fairness-weighted serialization). | Customer |
| POST | `/group-leaders/{leaderId}/group-buy-campaigns` | Create a group-buy campaign with overlap validation. | GroupLeader |
| POST | `/group-buy-campaigns/{campaignId}/orders` | Join the group with an order. | Customer |
| POST | `/orders/{orderId}/cancel` | Cancel a non-shipped order (FLASH only before `AT_PICKUP`). | Customer |
| POST | `/orders/{orderId}/pay` | Pay an order (`PENDING_PAY` → `PAID`); pin provisional totals. | Customer |
| POST | `/group-buy-campaigns/{campaignId}/extend` | Extend a `FORMING` campaign once. | GroupLeader |
| POST | `/group-buy-campaigns/{campaignId}/close` | Manually close a campaign to `SUCCEEDED` or `FAILED`. | GroupLeader, PlatformAdmin |
| POST | `/group-buy-campaigns/{campaignId}/finalize` | Finalise a `SUCCEEDED` / `FAILED` campaign to `CLOSED`. | PlatformAdmin |
| GET | `/group-buy-campaigns/{campaignId}` | Get a group-buy campaign. | PlatformAdmin, GroupLeader, Customer |
| GET | `/orders/{orderId}` | Get an order. | PlatformAdmin, Customer, GroupLeader, Supplier, CustomerService |
| POST | `/orders/{orderId}/plan-shipments` | Plan one or more shipments (server-selected warehouses). | Supplier, PlatformAdmin |
| GET | `/shipments/{shipmentId}` | Get a shipment. | PlatformAdmin, Supplier, Customer, PickupOperator |
| POST | `/shipments/{shipmentId}/dispatch` | Dispatch a planned shipment. | Supplier |
| POST | `/shipments/{shipmentId}/arrive-at-pickup` | Mark a shipment `AT_PICKUP`. | Supplier |
| POST | `/shipments/{shipmentId}/report-mispick` | Report a mis-pick. | PickupOperator |
| POST | `/shipments/{shipmentId}/reconcile` | Reconcile a mis-pick. | PickupOperator |
| POST | `/orders/{orderId}/pickup-confirm` | Customer confirms pickup. | Customer |
| POST | `/communities/{communityId}/pickup-points` | Create a pickup point. | PlatformAdmin |
| GET | `/pickup-points/{pickupPointId}/summary` | Read load summary for a pickup point. | PlatformAdmin, PickupOperator |
| POST | `/pickup-points/{pickupPointId}/consolidation-batches` | Open a consolidation batch (buffered overlap rejection). | PickupOperator |
| GET | `/after-sales/{caseId}` | Get an after-sales case. | PlatformAdmin, Customer, CustomerService |
| POST | `/orders/{orderId}/after-sales-cases` | File an after-sales case. | Customer |
| POST | `/after-sales/{caseId}/start-review` | Begin review. | CustomerService |
| POST | `/after-sales/{caseId}/request-evidence` | Request additional evidence. | CustomerService |
| POST | `/after-sales/{caseId}/submit-evidence` | Customer submits evidence. | Customer |
| POST | `/after-sales/{caseId}/escalate` | Escalate to arbitration. | CustomerService |
| POST | `/after-sales/{caseId}/resolve` | Resolve a case with `outcome` of `REFUND_ONLY` / `RETURN_REFUND` / `PARTIAL_COMPENSATION` / `REJECT`. | CustomerService, PlatformAdmin |
| GET | `/group-leaders/{leaderId}/commission-entries` | List a leader's commission entries (filterable by `status`). | PlatformAdmin, GroupLeader |
| POST | `/group-leaders/{leaderId}/payouts` | Assemble a payout for a `target_period_index`. | PlatformAdmin |
| GET | `/payouts/{payoutId}` | Get a payout. | PlatformAdmin, GroupLeader |
| POST | `/payouts/{payoutId}/release` | Release a `MATURED` payout. | PlatformAdmin |
| POST | `/payouts/{payoutId}/cancel` | Cancel a `SCHEDULED` payout. | PlatformAdmin |
| POST | `/risk-alerts` | Open a risk alert. | PlatformAdmin |
| POST | `/risk-alerts/{alertId}/confirm` | Confirm a risk alert with cascade. | PlatformAdmin |
| POST | `/risk-alerts/{alertId}/dismiss` | Dismiss a risk alert. | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_COMMUNITY_NOT_FOUND` | 404 |
| `ERR_GROUP_LEADER_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_FLASH_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_PICKUP_POINT_NOT_FOUND` | 404 |
| `ERR_AFTER_SALES_CASE_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_RISK_ALERT_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_SUPPLIER_NOT_FOUND` | 404 |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CAMPAIGN_NOT_OPEN` | 409 |
| `ERR_FLASH_STOCK_DEPLETED` | 409 |
| `ERR_FLASH_CAMPAIGN_NOT_OPEN` | 409 |
| `ERR_DUPLICATE_PARTICIPATION` | 409 |
| `ERR_COMMUNITY_CAMPAIGN_OVERLAP` | 409 |
| `ERR_COLD_CHAIN_REQUIRED` | 422 |
| `ERR_NO_WAREHOUSE_AVAILABLE` | 422 |
| `ERR_PICKUP_POINT_AT_CAPACITY` | 409 |
| `ERR_PICKUP_POINT_COLD_INCOMPATIBLE` | 422 |
| `ERR_CONSOLIDATION_WINDOW_OVERLAP` | 409 |
| `ERR_AFTER_SALES_WINDOW_EXPIRED` | 409 |
| `ERR_AFTER_SALES_ALREADY_OPEN` | 409 |
| `ERR_AFTER_SALES_AMOUNT_EXCEEDS_REMAINING` | 422 |
| `ERR_PAYOUT_HAS_PENDING_CLAWBACK` | 409 |
| `ERR_PAYOUT_NOT_MATURED` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_INVALID_QUANTITY` | 400 |
| `ERR_CUSTOMER_BLOCKED` | 403 |
| `ERR_CUSTOMER_RISK_HOLD` | 403 |

---

## Generator Self-Audit

```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body: 28 required, 28 present, 0 missing
- endpoints[].path_params: 12 required, 12 present, 0 missing
- endpoints[].query_params: 1 required, 1 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 23 checked, 23 expressed in prose, 0 missing
- concurrency_rules[] with error_id: 5 checked, 5 expressed, 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 23 checked, 23 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 54 checked, 54 expressed, 0 missing
- entities[].fields[] structured content: 15 entities checked, all defaults / sources / initial values reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (Order parallel state dimensions; AfterSalesCase resolution branches; RiskAlert confirm cascade branches; campaign close success/failure; flash purchase eligibility branches; commission rate selection by leader_role), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: ~280
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

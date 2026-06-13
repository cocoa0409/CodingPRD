# Appliance & Electronics Trade-In API — Product Requirements Document

## 1. Introduction

This document specifies the Appliance & Electronics Trade-In / Buyback platform — a back-office API that takes a consumer device from a self-graded online quote all the way through shipment, hub inspection, payout, and end-of-life disposition. The business problem it solves is the gap between what a customer *says* a device is worth and what an inspector *verifies* it to be worth: the platform issues a provisional, price-locked offer from a condition questionnaire, then reconciles that offer against a physical inspection, re-quoting or recycling when the verified condition diverges from the declared one.

Four parties interact with the system. A catalog administrator curates the device catalog, the buyback price book, and the promotional offers that sweeten quotes. Customers look up their model, answer a grading questionnaire, lock in an offer, ship their unit in a prepaid kit, and accept or decline any revised offer that comes back from inspection. Grading agents receive the physical units at the hub, inspect them, and certify secure data erasure. Finance operators settle accepted trade-ins by issuing payouts and, where necessary, reversing them. The platform is fundamentally a **pricing engine wrapped in a workflow orchestrator**: every quote is a deterministic computation over a model's reference value, the device's graded condition, and any active promotion, while every trade-in is a state machine whose branches fan cascading side effects across the quote, the inspection, the payout ledger, and the disposition record.

Because money changes hands and a single physical device flows through several hands, the system treats correctness as paramount: amounts are computed in integer cents with pinned rounding, concurrent revisions to an in-flight trade-in are guarded by optimistic concurrency control, and a wallet invariant guarantees that issuing and then reversing a payout leaves the customer's balances exactly where they started.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Domain-specific lifecycle behavior is deferred to Section 3.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. A request missing either header, or carrying a header the server cannot validate, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `CatalogAdmin`, `Customer`, `GradingAgent`, and `FinanceOperator`.

- A `Customer` is **entity-backed**. When `X-User-Role` is `Customer`, the value of `X-User-ID` is the `id` of the acting `Customer` entity. Ownership checks on any resource that references a customer compare the resource's customer foreign key to `X-User-ID`: for trade-in actions reserved to the owner, the acting `Customer`'s `X-User-ID` must equal the target `TradeIn.customer_id`, and a mismatch is rejected with `ERR_NOT_OWNER` (HTTP 403).
- A `CatalogAdmin` is an **opaque** operator identity. When `X-User-Role` is `CatalogAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.
- A `GradingAgent` is likewise an **opaque** operator identity: `X-User-ID` is an opaque operator identifier not tied to any persisted entity, recorded if useful but never matched against an entity `id`.
- A `FinanceOperator` is also an **opaque** operator identity, with `X-User-ID` an opaque operator identifier not tied to any persisted entity and never compared to an entity `id`.

The authorization checks run in a fixed precedence that is detailed in Section 2.4: authentication first, then role permission, then — for the owner-restricted customer actions — the ownership comparison.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result and defaults to 0.

Unless an endpoint explicitly states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response carries the pagination bookkeeping in the `meta` object of the envelope, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Validation Ordering and Error Precedence

When several checks could fail for one request, the system evaluates them in a fixed priority so that the returned `error_id` is deterministic. The order is:

1. **Authentication** — both `X-User-ID` and `X-User-Role` present and valid, otherwise `ERR_UNAUTHENTICATED`.
2. **Role permission** — the role is allowed to invoke this operation per the matrix in Section 4, otherwise `ERR_FORBIDDEN`.
3. **Ownership** — for customer-owned trade-in actions, the acting `Customer`'s identifier equals the trade-in's owning customer, otherwise `ERR_NOT_OWNER`.
4. **Path existence** — every resource named in the URL path exists, validated left to right (see Section 2.5), otherwise `ERR_NOT_FOUND`.
5. **Body foreign keys** — on trade-in creation, the supplied `customer_id` and `device_model_id` resolve to existing rows, otherwise `ERR_FK_NOT_FOUND`.
6. **Request well-formedness** — required body fields are present and correctly typed and any enum members are valid, otherwise `ERR_INVALID_REQUEST`.
7. **State legality** — the target `TradeIn`, `Quote`, or `Payout` is in a state from which the requested transition is legal, otherwise `ERR_INVALID_STATE`.
8. **Optimistic concurrency** — where an operation requires `expected_trade_in_version`, it equals the current `version`, otherwise `ERR_STALE_VERSION`.

Beyond this spine, the remaining business checks (model retirement, promotion validity, defect membership, quote expiry, data-wipe presence, window and slot overlaps, uniqueness, and multiplier validity) fire after the structural checks above and are described alongside the workflows they guard in Section 3. Where two business checks apply to the same operation, the precedence values that pin their relative order are enumerated in those workflow narratives.

### 2.5. Resource Topology and Nested-Path Validation

The system uses a hybrid topology. A `Catalog` is the configuration root; under it hang the device price book (`DeviceModel`), the promotional offers (`PromotionCampaign`), and the hub's inspection capacity (`InspectionSlot`), each of which records its parent through a `catalog_id` reference. A `Customer` is a standalone party. A `TradeIn` is a flat resource that points across aggregates — it references a `Customer` and a `DeviceModel` — and owns a family of child records: its quotes, its shipping kit, its inspections, its payout, its data-wipe certificate, and its disposition records, each of which records its parent through a `trade_in_id` reference.

For any request whose path names more than one resource (for example, reversing a specific payout under a specific trade-in), the server validates each identifier from left to right and rejects the request with `ERR_NOT_FOUND` at the **first** identifier that does not resolve. A payout reversal under a non-existent trade-in therefore fails on the trade-in before the payout is ever consulted. This left-to-right rule applies uniformly to reads, creates, and transitions.

Child collections are discoverable by walking back from the parent: the authoritative customer edge for a payout runs from the payout's owning trade-in to that trade-in's customer rather than through the payout's own denormalized copy, and a trade-in's currently honored quote is found by listing the trade-in's quotes and selecting the one in `LOCKED` status rather than trusting any single denormalized pointer in isolation.

### 2.6. Common Resource Properties

Every persisted resource carries a system-managed `id`: a server-minted UUID with no type prefix. Every resource also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set when the resource is first created and never changed thereafter.

All resources in this system additionally carry an `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation) and a `version` (an integer that starts at its initial value and increments by one on every mutation). The `version` field is the basis for optimistic concurrency control described in Section 2.7. When a derived or denormalized field on a resource changes as a side effect of some other operation — for example, when a trade-in's `final_value_cents` or `locked_quote_id` is written, or when a customer's `wallet_balance_cents` and `lifetime_payout_cents` move — that write is itself a mutation that refreshes `updated_at` and increments `version` on the affected resource.

### 2.7. Optimistic Concurrency Control on Re-Quote Decisions

A trade-in that has been re-quoted sits in a genuinely contended state: the customer is deciding whether to accept the inspector's revised offer, while a grading agent may simultaneously revise the verified findings and mint yet another revised offer. To keep the customer from acting on an offer that has already been replaced, the two customer re-quote decisions are guarded by optimistic concurrency control on the trade-in's `version`.

Accepting a re-quote requires the request to carry `expected_trade_in_version`, and that value must equal the target `TradeIn`'s current `version`. If a grading agent has revised the findings since the customer last read the trade-in — which legitimately supersedes the prior re-quote, mints a new one, and advances `version` — then the customer's `expected_trade_in_version` no longer matches, and the acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412). Declining a re-quote is guarded identically: the decline request must carry `expected_trade_in_version` matching the trade-in's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). In both cases the trade-in may still legitimately be in its re-quoted state, so the state check passes; it is specifically the version mismatch that refuses the decision, preventing the customer from overwriting a revision they have not yet observed. No other endpoint takes a version field; operations not listed here proceed without an OCC check.

### 2.8. Monetary Precision and Rounding

All money in the system is represented as **integer cents** — there are no fractional cents anywhere in stored values or API responses, and every money field name ends in `_cents`. The single currency for a program is recorded on its catalog's `currency` field, defaulting to `USD`.

Wherever a calculation multiplies an integer cents amount by a fractional factor — a condition multiplier, a promotion percentage, or a tolerance fraction — the product is rounded to whole cents using **round half up** (a value exactly halfway between two integers rounds to the larger). Pure additions and subtractions of cents amounts introduce no further rounding, since both operands are already whole cents. The precise points at which rounding is applied within each formula are pinned in the workflow narratives of Section 3.

### 2.9. Cascading Side Effects and State Propagation

Many operations in this domain mutate more than one resource at once, and these cascades are part of the contract, not incidental bookkeeping. When an inspection forks a trade-in, it simultaneously transitions the trade-in, changes the status of one or more quotes, and may mint a disposition record. When a payout is issued, it creates the payout, moves the customer's wallet and lifetime totals, and records a refurbishment disposition. Each resource touched by such a cascade independently has its `updated_at` refreshed and its `version` incremented. The full set of secondary effects for each transition is spelled out in Section 3, and an implementation that performs only the primary mutation while skipping the cascade is non-conforming.

### 2.10. Time, Price-Lock Expiry, and the Logical Clock

The platform reasons about wall-clock time for three purposes: the price-lock window after which a locked quote can no longer be honored, the active interval of a promotion, and the scheduling of hub inspection slots. So that these time-sensitive behaviors can be exercised deterministically, an administrative test-driving capability sets the server's current UTC instant to a supplied value carried in the `to_iso8601` field, and the server reports back the instant it adopted. All expiry and window comparisons described in Section 3 are evaluated against this logical clock.

## 3. Business Logic & Workflows

### 3.1. Catalog, Device Catalog, and the Buyback Price Book

A `CatalogAdmin` stands up a trade-in program by creating a **catalog**, supplying a `name` and optionally a `currency` (defaulting to `USD`). The catalog also fixes the program-wide policy knobs that the rest of the workflow reads: `price_lock_hours`, the number of hours a locked quote stays honored before it expires, defaulting to 168; `requote_tolerance_pct`, the fraction below a locked quote within which a lower inspected value is still auto-accepted rather than re-quoted, defaulting to 0.15; `data_wipe_required_categories`, the list of device categories that must show a passing erasure certificate before any payout; and `recycle_floor_value_cents`, the value at or below which a unit is diverted to recycling instead of buyback, defaulting to 0. A catalog `name` must be unique; a colliding name is rejected with `ERR_DUPLICATE` (HTTP 409).

Within a catalog, a `CatalogAdmin` registers a **device model**, which is the unit of lookup and pricing. Each model records its `catalog_id`, a `manufacturer`, a `model_code` (the lookup key), a `category`, and a `base_value_cents` — the reference buyback value for a flawless, fully functional unit before any deductions. The `category` is one of `SMARTPHONE`, `LAPTOP`, `TABLET`, `REFRIGERATOR`, `WASHER`, `TV`, or `WEARABLE`. The `model_code` must be unique within its catalog among models that are not retired, compared case-insensitively; a collision is rejected with `ERR_DUPLICATE` (HTTP 409). A newly registered model starts with `status` of `ACTIVE`.

Two structured pricing inputs live on the model. The `condition_multipliers` field maps cosmetic grade to a multiplier fraction and must define exactly the four keys `FLAWLESS`, `GOOD`, `FAIR`, and `POOR`, each a number between 0 and 1 inclusive; a map that omits a key, adds an extra key, or carries a value outside that range is rejected with `ERR_INVALID_MULTIPLIERS` (HTTP 422). The `defect_deductions` field maps a defect-flag key to a flat cents deduction, with keys drawn from `CRACKED_SCREEN`, `BATTERY_DEGRADED`, `WATER_DAMAGE`, `MISSING_PARTS`, `WONT_POWER_ON`, and `DENTED_BODY`.

A `CatalogAdmin` may **retire** a model, moving its `status` to `RETIRED`; a retired model rejects new trade-ins and quotes. A device model — like every catalog child — exposes its parent linkage so that the catalog's models can be listed back, optionally filtered by `category` or `model_code`, and a single model can be looked up directly by its identifier.

### 3.2. Promotions and Their Non-Overlapping Windows

A `CatalogAdmin` can attach **promotion campaigns** to a catalog to layer a bonus on top of a graded quote. A campaign records its `catalog_id`, a `code` that customers supply at trade-in creation, a `category_scope` naming a single `category` the promotion applies to (or `ALL` for any category), and an active interval defined by `effective_from` (inclusive) and `effective_to` (exclusive), where `effective_to` must be strictly later than `effective_from`. The bonus itself is shaped by `bonus_pct`, a fraction added on top of the condition-graded subtotal and defaulting to 0; `bonus_flat_cents`, flat cents added after the percentage and defaulting to 0; and `bonus_cap_cents`, the maximum combined bonus the promotion may contribute to one quote. A new campaign starts with `status` of `ACTIVE`; a `CatalogAdmin` may later **expire** it, moving `status` to `EXPIRED`.

The `code` must be unique within its catalog among active campaigns, compared case-insensitively; a duplicate is rejected with `ERR_DUPLICATE` (HTTP 409). Beyond uniqueness, no two active campaigns may overlap in time on the same category lane. When creating a campaign, the system rejects it with `ERR_PROMO_WINDOW_OVERLAP` (HTTP 409) if its half-open `[effective_from, effective_to)` interval overlaps that of any existing active campaign whose lane collides — that is, the two share the same `category_scope`, or either side is scoped to `ALL`. Because the intervals are half-open, exact adjacency is permitted: one campaign's `effective_to` equal to another's `effective_from` does not conflict, since neither instant lies in both intervals. Campaigns under a catalog can be listed and filtered by `code` or by `status`.

### 3.3. Customers and the Trade-In Origination

Customers are registered with a unique `email` (compared case-insensitively; a collision is rejected with `ERR_DUPLICATE`, HTTP 409) and a `full_name`. A customer also carries two computed running totals that begin at 0: `wallet_balance_cents`, the store-credit balance, and `lifetime_payout_cents`, the conserved sum of payouts ever settled to them. Both are maintained by the payout workflow in Section 3.7 and are never written directly by the client. A customer record can be fetched to read back its wallet and lifetime totals, and a customer's own trade-ins can be listed.

A `Customer` originates a **trade-in** by submitting `customer_id`, `device_model_id`, and their self-assessed condition: `declared_grade` (one of `FLAWLESS`, `GOOD`, `FAIR`, or `POOR`), an optional `declared_defects` list of defect-flag keys defaulting to an empty list, and an optional `declared_powers_on` boolean defaulting to true. The customer may also supply a `promo_code`. At creation the supplied `customer_id` and `device_model_id` must resolve to existing rows, failing with `ERR_FK_NOT_FOUND` (HTTP 404) otherwise. If a `promo_code` is supplied, the system resolves it to a campaign and records the result in `promotion_campaign_id`, leaving that field null when no code is given. The resolution must find an `ACTIVE` campaign whose scope matches the device's category or is `ALL`; a missing, non-active, or out-of-scope code is rejected with `ERR_PROMO_INVALID` (HTTP 409). The new trade-in is created in `DRAFT` status with `final_value_cents` null and a `version` that the lifecycle's later steps will advance.

### 3.4. From Draft to Locked Quote: the Self-Graded Offer

A `Customer` who owns a `DRAFT` trade-in asks the system to **quote** it, advancing it from `DRAFT` to `QUOTED`. Before pricing, three preconditions are checked: the referenced device model's `status` must be `ACTIVE`, otherwise the quote is refused with `ERR_MODEL_RETIRED` (HTTP 409); any promotion resolved for the trade-in must still be `ACTIVE` and in scope, otherwise `ERR_PROMO_INVALID` (HTTP 409); and every entry in `declared_defects` must be a key that exists in the model's `defect_deductions`, otherwise `ERR_UNKNOWN_DEFECT` (HTTP 422).

Quoting mints an initial `Quote` whose `kind` is `INITIAL` and whose `status` is `LOCKED`, and sets the trade-in's `locked_quote_id` to point at it. The offered amount is computed deterministically from the customer's declared findings. First the **condition-graded subtotal** is found: the model's `base_value_cents` is multiplied by the multiplier for the declared grade taken from `condition_multipliers`, and that product is rounded to whole cents using round half up to give the conditioned value. The flat deductions for every declared defect are summed from `defect_deductions`. There is one override for non-powering units: if `declared_powers_on` is false, the conditioned value is instead computed using the `POOR` multiplier regardless of the declared grade, and additionally the `WONT_POWER_ON` deduction is added to the deduction total even if `WONT_POWER_ON` was not among the declared defects (if it was already listed, it is not counted twice). The graded subtotal, stored on the quote as `graded_subtotal_cents`, is the conditioned value minus the total deductions, floored at 0 so it can never go negative.

Onto that subtotal the promotion bonus is layered, but only for an initial quote that resolved a promotion. The bonus, stored as `promo_bonus_cents`, is computed by first taking the percentage part — the graded subtotal multiplied by the campaign's `bonus_pct`, rounded to whole cents using round half up — then adding the campaign's `bonus_flat_cents` flat part, and finally clamping the sum down to `bonus_cap_cents` if it would exceed the cap. The ordering is pinned and observable when the cap straddles the raw bonus: round the percentage part first, add the flat part second, then apply the cap to the combined total. When no promotion was resolved, `promo_bonus_cents` is 0. The quote's `amount_cents` is then simply the graded subtotal plus the promotion bonus; since both are already whole cents, no further rounding is applied. As the quote is locked, its `lock_expires_at` is set to its creation instant plus the catalog's `price_lock_hours`.

A `Customer` may **cancel** a trade-in while it is still in `DRAFT` or `QUOTED`, moving it to the terminal `CANCELLED` state. Cancelling from `DRAFT` has no further effect; cancelling from `QUOTED` also supersedes the locked quote, moving that `Quote` to `SUPERSEDED`.

### 3.5. Shipping the Unit and Receiving It at the Hub

Once a trade-in is `QUOTED`, the owning `Customer` requests a **shipping kit**, advancing the trade-in from `QUOTED` to `KIT_SENT`. This is permitted only while the locked quote has not expired — its `lock_expires_at` must be later than the current logical time — otherwise the request is refused with `ERR_QUOTE_EXPIRED` (HTTP 409). Dispatching the kit creates a `ShippingKit` in `DISPATCHED` status with a system-minted `tracking_number` and a prepaid `label_url`.

When the unit arrives, a `GradingAgent` marks it **received**, advancing the trade-in from `KIT_SENT` to `RECEIVED`. Receiving likewise requires that the locked quote has not expired, again failing with `ERR_QUOTE_EXPIRED` if it has, and as a side effect it moves the shipping kit's `status` to `DELIVERED_TO_HUB`. (Between dispatch and delivery a kit may be observed in the intermediate `IN_TRANSIT` status.) A trade-in's shipping kits can be listed back from the trade-in.

While a trade-in sits in `QUOTED` or `KIT_SENT` and its price-lock window lapses, an administrative **expiry sweep** transitions it to the terminal `EXPIRED` state. The sweep acts only when the current logical time is past the locked quote's `lock_expires_at`; it moves the trade-in to `EXPIRED` and moves the locked `Quote` to `EXPIRED` as well.

### 3.6. Inspection, the Fork, and the Re-Quote Loop

The pivotal step is **inspection**. A `GradingAgent` submits findings on a `RECEIVED` trade-in: a `verified_grade` (one of `FLAWLESS`, `GOOD`, `FAIR`, or `POOR`), an optional `verified_defects` list defaulting to empty, and a `verified_powers_on` boolean. Every entry in `verified_defects` must be a key present in the model's `defect_deductions`, otherwise the submission is rejected with `ERR_UNKNOWN_DEFECT` (HTTP 422). The submission advances the trade-in from `RECEIVED` to `INSPECTED`, recording the time the agent submitted findings in `graded_at` and creating an `Inspection`.

The inspection computes an `inspected_value_cents` by re-running the very same condition-grading formula described in Section 3.4 — base value times the verified grade's multiplier rounded half up, minus the summed deductions for the verified defects, floored at 0, with the identical non-powering override forcing the `POOR` multiplier and adding the `WONT_POWER_ON` deduction when `verified_powers_on` is false — but with one critical difference: **no promotion bonus is ever applied to an inspected value**. This verified amount is the final, authoritative valuation.

From the inspected value and the trade-in's locked quote amount, the system selects an `outcome`, checking the conditions in a pinned order. First, if the inspected value is at or below the catalog's `recycle_floor_value_cents`, the outcome is `RECYCLE` — the floor check is evaluated before anything else and wins outright. Otherwise the system computes the minimum acceptable value as the locked quote amount minus the tolerance band, where the band is the locked amount multiplied by the catalog's `requote_tolerance_pct` and rounded to whole cents using round half up; if the inspected value is greater than or equal to that minimum acceptable value, the outcome is `MATCH`. Failing both, when the inspected value falls below the minimum acceptable value but stays above the recycle floor, the outcome is `REQUOTE`.

Exactly one of three branch cascades then fires, selected by the outcome:

- On `MATCH`, the trade-in auto-accepts at the originally locked amount: it advances from `INSPECTED` to `ACCEPTED`, the initial `LOCKED` quote moves to `HONORED`, and the trade-in's `final_value_cents` is set to that honored quote's `amount_cents`. The customer is paid the original locked figure even though the verified value came in lower, because the shortfall stayed within tolerance.
- On `REQUOTE`, the trade-in advances from `INSPECTED` to `REQUOTED`: the prior `INITIAL` quote moves to `SUPERSEDED`, and a fresh `Quote` of `kind` `REQUOTE` is minted in `LOCKED` status with its `amount_cents` equal to the inspected value, its `promo_bonus_cents` fixed at 0, and its `lock_expires_at` set to its creation instant plus `price_lock_hours`; the trade-in's `locked_quote_id` is repointed at this new quote.
- On `RECYCLE`, the trade-in advances from `INSPECTED` to the terminal `RECYCLED` state: the prior locked quote moves to `SUPERSEDED`, and a `DispositionRecord` with `disposition` of `RECYCLE` is created.

A re-quoted trade-in awaits a customer decision, but a `GradingAgent` may first **re-inspect** it — a self-loop that keeps the trade-in in `REQUOTED`. Re-inspection accepts the same verified inputs (`verified_grade`, `verified_defects`, `verified_powers_on`), again rejecting any defect outside `defect_deductions` with `ERR_UNKNOWN_DEFECT` (HTTP 422). It is valid only when the fresh findings again yield a downgrade outcome that stays above the recycle floor; a re-inspection that would resolve to a match or to recycle is out of scope for this loop and is rejected with `ERR_INVALID_STATE` (HTTP 409). A valid re-inspection creates a second `Inspection`, recomputes `inspected_value_cents`, supersedes the current `REQUOTE` quote (moving it to `SUPERSEDED`), and mints a new `LOCKED` `REQUOTE` quote at the new inspected value with `promo_bonus_cents` of 0 and a refreshed `lock_expires_at`, repointing `locked_quote_id`. This supersede-and-replace is exactly the contended write that the version guard of Section 2.7 defends: it advances the trade-in's `version`, so a customer acceptance or decline that was prepared against the pre-revision version is correctly refused as stale.

When the customer is ready, the owning `Customer` either **accepts** the re-quote, advancing the trade-in from `REQUOTED` to `ACCEPTED`, or **declines** it, advancing from `REQUOTED` to the terminal `REJECTED` state. Both decisions carry `expected_trade_in_version` and are guarded by the optimistic concurrency rule in Section 2.7, yielding `ERR_STALE_VERSION` (HTTP 412) on a mismatch. Acceptance additionally requires that the `REQUOTE` quote has not expired, failing with `ERR_QUOTE_EXPIRED` (HTTP 409) otherwise; on success it moves the `REQUOTE` quote to `HONORED` and sets `final_value_cents` to that quote's amount. A decline moves the `REQUOTE` quote to `SUPERSEDED` and creates a `DispositionRecord` with `disposition` of `RETURN_TO_CUSTOMER` and an optional free-text `reason` note (null when none is given). A trade-in's inspections and disposition records can each be listed back from the trade-in.

### 3.7. Data-Wipe Certification, Payout, and the Wallet Ledger

Before a wipe-required device can be paid out, a `GradingAgent` records a **data-wipe certificate** against the received trade-in, supplying a `method` (one of `CRYPTO_ERASE`, `NIST_PURGE`, or `PHYSICAL_DESTROY`) and a `result` (`PASS` or `FAIL`); the system mints a `certificate_serial`. A trade-in's data-wipe certificates can be listed back.

A `FinanceOperator` settles an `ACCEPTED` trade-in by issuing a **payout**, advancing the trade-in from `ACCEPTED` to the terminal `PAID` state. The operator supplies only the `method` — one of `STORE_CREDIT`, `ACH`, or `CHECK`. There is one safety gate: if the device model's `category` is among the catalog's `data_wipe_required_categories`, a `DataWipeCertificate` with `result` of `PASS` must already exist for this trade-in, otherwise the payout is refused with `ERR_DATA_WIPE_REQUIRED` (HTTP 409). Issuing the payout creates a `Payout` whose `status` is `PAID` and whose `amount_cents` equals the trade-in's `final_value_cents` at that moment; the payout also records the owning trade-in via `trade_in_id` and carries a denormalized `customer_id` copy of the owning trade-in's customer. (The payout entity defines `ISSUED` as a pre-persist label only — a persisted payout is never observed in `ISSUED`; it is born `PAID`.)

Issuing a payout moves the wallet ledger. The customer's `lifetime_payout_cents` is increased by the payout amount in every case. Additionally, when and only when the `method` is `STORE_CREDIT`, the customer's `wallet_balance_cents` is increased by the same amount; for `ACH` and `CHECK` payouts the wallet balance is untouched and only the lifetime total moves. Issuing also creates a `DispositionRecord` with `disposition` of `REFURBISH_INVENTORY`, routing the now-bought unit into refurbishment stock.

A `FinanceOperator` may **reverse** a payout as a compensating action, but only while that `Payout` is in `PAID`; a reversal attempt against any other payout state is refused with `ERR_INVALID_STATE` (HTTP 409). Reversal moves the payout to the terminal `REVERSED` state and unwinds the ledger exactly: the customer's `lifetime_payout_cents` is decreased by the payout amount, and — only if the payout's `method` was `STORE_CREDIT` — the `wallet_balance_cents` is decreased by the same amount. The invariant is that issuing a payout and then reversing it leaves both `wallet_balance_cents` and `lifetime_payout_cents` exactly at their pre-issue values, with no net drift. The reversal is a payout-level transition; the trade-in itself remains in `PAID`. A trade-in's payouts can be listed, and a single payout can be fetched by its identifier.

### 3.8. Hub Inspection Slot Capacity

The hub schedules its physical inspection capacity as **inspection slots** booked against a category lane. A `GradingAgent` or `CatalogAdmin` books a slot under a catalog by supplying a `lane_category` (one of the seven device categories) and a closed window from `slot_start` to `slot_end`, where `slot_end` must be strictly after `slot_start`. A new slot starts with `status` of `BOOKED`.

Slots on the same lane may not crowd one another. The booked window is a closed interval, and a 30-minute buffer is added on each side of it; the new slot is rejected with `ERR_SLOT_OVERLAP` (HTTP 409) if this buffered interval overlaps any existing `BOOKED` slot on the same `lane_category`. Because the underlying interval is closed, two slots whose endpoints merely touch already conflict, and the buffer makes even near-adjacent bookings collide. A booked slot may be **released** by a `GradingAgent` or `CatalogAdmin`, which is permitted only while the slot is `BOOKED` (otherwise `ERR_INVALID_STATE`, HTTP 409); releasing moves its `status` to `RELEASED`, after which its interval no longer participates in overlap checks for subsequent bookings. A catalog's slots can be listed and filtered by `lane_category` or `status`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return `201 Created`; operations that modify or transition an existing resource, including the lifecycle transitions that return the updated trade-in, return `200 OK`. Reads return `200 OK`. Request and response payloads are intentionally omitted from this table — reconstruct them from the workflow narratives in Section 3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/catalogs` | Create a trade-in catalog/program | CatalogAdmin |
| GET | `/catalogs/{id}` | Fetch a catalog | CatalogAdmin, FinanceOperator, GradingAgent |
| POST | `/catalogs/{id}/device-models` | Register a device model under a catalog | CatalogAdmin |
| GET | `/catalogs/{id}/device-models` | List device models under a catalog | CatalogAdmin, GradingAgent, Customer |
| GET | `/device-models/{id}` | Look up a single device model | CatalogAdmin, GradingAgent, Customer |
| POST | `/device-models/{id}/retire` | Retire a device model | CatalogAdmin |
| POST | `/catalogs/{id}/promotion-campaigns` | Create a promotion campaign under a catalog | CatalogAdmin |
| GET | `/catalogs/{id}/promotion-campaigns` | List promotion campaigns under a catalog | CatalogAdmin, Customer |
| POST | `/promotion-campaigns/{id}/expire` | Expire a promotion campaign | CatalogAdmin |
| POST | `/catalogs/{id}/inspection-slots` | Book a hub inspection slot on a category lane | GradingAgent, CatalogAdmin |
| GET | `/catalogs/{id}/inspection-slots` | List inspection slots under a catalog | GradingAgent, CatalogAdmin |
| POST | `/inspection-slots/{id}/release` | Release a booked inspection slot | GradingAgent, CatalogAdmin |
| POST | `/customers` | Register a customer | CatalogAdmin, Customer |
| GET | `/customers/{id}` | Fetch a customer | CatalogAdmin, FinanceOperator, Customer |
| GET | `/customers/{id}/trade-ins` | List a customer's trade-ins | CatalogAdmin, FinanceOperator, Customer |
| POST | `/trade-ins` | Create a trade-in in DRAFT | Customer |
| GET | `/trade-ins/{id}` | Fetch a trade-in | CatalogAdmin, FinanceOperator, GradingAgent, Customer |
| GET | `/trade-ins` | List trade-ins | CatalogAdmin, FinanceOperator, GradingAgent, Customer |
| POST | `/trade-ins/{id}/quote` | Generate and lock the initial quote | Customer |
| POST | `/trade-ins/{id}/ship-kit` | Dispatch shipping kit/label | Customer |
| POST | `/trade-ins/{id}/receive` | Mark device received at hub | GradingAgent |
| POST | `/trade-ins/{id}/inspect` | Submit inspection findings (forks the trade-in) | GradingAgent |
| POST | `/trade-ins/{id}/reinspect` | Revise verified findings while re-quoted | GradingAgent |
| POST | `/trade-ins/{id}/accept-requote` | Customer accepts the re-quote | Customer |
| POST | `/trade-ins/{id}/decline-requote` | Customer declines the re-quote | Customer |
| POST | `/trade-ins/{id}/cancel` | Cancel a trade-in before shipment | Customer |
| POST | `/trade-ins/{id}/sweep-expiry` | Expire a trade-in whose locked quote has lapsed | CatalogAdmin |
| GET | `/trade-ins/{id}/quotes` | List quotes for a trade-in | CatalogAdmin, FinanceOperator, GradingAgent, Customer |
| GET | `/trade-ins/{id}/shipping-kits` | List shipping kits for a trade-in | CatalogAdmin, GradingAgent, Customer |
| GET | `/trade-ins/{id}/inspections` | List inspections for a trade-in | CatalogAdmin, FinanceOperator, GradingAgent, Customer |
| POST | `/trade-ins/{id}/data-wipe` | Record a data-wipe certificate | GradingAgent |
| GET | `/trade-ins/{id}/data-wipe-certificates` | List data-wipe certificates | CatalogAdmin, FinanceOperator, GradingAgent, Customer |
| POST | `/trade-ins/{id}/payouts` | Issue payout | FinanceOperator |
| GET | `/trade-ins/{id}/payouts` | List payouts for a trade-in | CatalogAdmin, FinanceOperator, Customer |
| GET | `/payouts/{id}` | Fetch a single payout | CatalogAdmin, FinanceOperator, Customer |
| POST | `/trade-ins/{id}/payouts/{payoutId}/reverse` | Reverse a payout (compensation) | FinanceOperator |
| GET | `/trade-ins/{id}/disposition-records` | List disposition records | CatalogAdmin, GradingAgent, Customer |
| POST | `/_clock/set_current_utc` | Set the server's current UTC instant (test-driving) | CatalogAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MODEL_RETIRED` | 409 Conflict |
| `ERR_PROMO_INVALID` | 409 Conflict |
| `ERR_UNKNOWN_DEFECT` | 422 Unprocessable Entity |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_DATA_WIPE_REQUIRED` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_MULTIPLIERS` | 422 Unprocessable Entity |
| `ERR_PROMO_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SLOT_OVERLAP` | 409 Conflict |

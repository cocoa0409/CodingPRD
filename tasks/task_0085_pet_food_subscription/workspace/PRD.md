# Pet Food Subscription API — Product Requirements Document

## 1. Introduction

A growing number of pet households want food that is tailored to the animal in front of them — a senior cat with kidney disease, a working-breed puppy that gains weight unpredictably, a multi-dog household where one pet refuses chicken — yet shop on platforms whose subscription mechanics treat every pet the same and whose recipe choices stop at "small kibble" and "large kibble". The Pet Food Subscription API is the backend that closes that gap. It carries a pet's full nutritional profile (species, breed, age, weight, activity level, allergies, intolerances, dietary preferences and aversions, and health-condition tags), turns those signals into per-cycle recipe recommendations and portion sizes, and runs the order pipeline that follows — pre-shipment confirmation, multi-warehouse routing, batch and expiration tracking, and post-delivery feedback that loops back into the next cycle's recipe.

Three concerns make this domain harder than a generic subscription billing system, and the API is designed around them. First, **safety**: a recipe that contains an allergen the pet reacts to, or that bypasses a prescribed therapeutic diet, is a clinical incident, not a customer-experience defect — the system must refuse to ship such an order even when the customer's recommendation tooling has converged on it. Second, **lifecycle elasticity**: customers pause subscriptions for vacations, skip a single cycle, cancel and then come back; the system must serialize these movements with the cycle scheduler so that the count of orders the household has been billed for, skipped, and elapsed always reconciles. Third, **structured feedback**: per-shipment ratings on palatability, stool quality, coat condition, and weight change are not free-text reviews — they drive an automated suggestion engine that proposes a recipe rotation, a portion change, or an escalation to a veterinarian, and the rules that arbitrate between those suggestions must be reproducible across implementations.

This document specifies the API contract — the global response envelope, the role and access model, the entity lifecycles, the calculation formulas, and the validation rules — that any conforming implementation must honor.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or `X-User-Role` is not one of the role names enumerated below, the request is rejected with HTTP 400 and the error id `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and valid but the role is not authorized for the requested endpoint per the §4 RBAC matrix, the request is rejected with HTTP 403 and `ERR_INSUFFICIENT_PERMISSIONS`.

Five roles exist:

- `Customer` — the end user who owns pets, subscriptions, orders, feedback, and recipe adjustments. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that ultimately references a `Customer` (a `Pet` via `customer_id`, a `Subscription` via `customer_id`, an `Order` via `customer_id`, a `RecipeAdjustment` and `ShipmentFeedback` reachable through the owning `Pet` or `Order`) compare the resource's `customer_id` (or transitively the owning Customer's `id`) to `X-User-ID`. A `Customer` may only act on resources whose ownership trail terminates at their own `id`; otherwise the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.
- `AdminOps` — platform operations: manages the recipe catalog, warehouses, and inventory lots; reads audit logs; drives the test-driver endpoints. When `X-User-Role` is `AdminOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `actor_id` on `AuditLog`) but does not compare it to any entity's `id`.
- `PaymentAdapter` — the external payment system that delivers `PAYMENT_CAPTURED`, `PAYMENT_FAILED`, and `PAYMENT_REFUNDED` events. When `X-User-Role` is `PaymentAdapter`, `X-User-ID` is an opaque adapter identifier not tied to any persisted entity; it is recorded (e.g., as `actor_id` on `AuditLog`) but never compared to an entity `id`.
- `LogisticsAdapter` — the external logistics system that delivers `SHIPMENT_DISPATCHED` and `DELIVERY_CONFIRMED` events. When `X-User-Role` is `LogisticsAdapter`, `X-User-ID` is an opaque adapter identifier handled the same way as `PaymentAdapter`.
- `VetAdapter` — the external veterinary-consultation system that delivers `VET_APPROVED` and `VET_REJECTED` events. When `X-User-Role` is `VetAdapter`, `X-User-ID` is an opaque adapter identifier handled the same way as the other event adapters.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; values outside this range are rejected with `ERR_INVALID_REQUEST`. `offset` defaults to 0 and must be a non-negative integer. List endpoints sort results by `created_at` in ascending order. Every list response includes the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` block; `total_count` is the total number of records that match the filters before pagination is applied, and `has_more` is true when `offset + limit < total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every resource is identified by an `id` that is a server-minted UUID with no type prefix; clients never supply an `id` on create. Mutable resources also carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that starts at 1 on creation and is incremented by exactly one on every successful mutation. The mutable entities are `Customer`, `Pet`, `Subscription`, `Warehouse`, `InventoryLot`, `Order`, `ShipmentFeedback`, `RecipeRecommendation`, and `RecipeAdjustment`. Two entities are immutable catalogs or append-only logs and therefore carry only `id` and `created_at` — `Recipe` (an immutable catalog row written once and read thereafter) and `AuditLog` (an append-only event stream); for these two, `updated_at` and `version` are absent from the JSON payload entirely.

Optimistic concurrency control is offered on every `PATCH` endpoint that accepts a `version` parameter in its request body — specifically the `PATCH` on a subscription, the `PATCH` on a customer's pet, and the `PATCH` on a warehouse. When the caller includes `version` and the value supplied does not equal the entity's current `version`, the request is rejected with HTTP 409 and `ERR_VERSION_CONFLICT`. When the caller omits `version`, the check is skipped and the mutation proceeds (still subject to all other validations). Successful mutations bump `version` by one and refresh `updated_at` regardless of whether a `version` value was supplied in the request.

When an operation mutates more than one entity in a single call — for example, when subscription cancellation cascades into multiple non-terminal orders and pending recipe recommendations — every affected mutable entity has its own `version` incremented by one and its own `updated_at` refreshed.

### 2.5. Precision and Rounding

All monetary amounts are integer cents. Per-line item totals, subtotals, trial-pack-discounted subtotals, shipping fees, and order totals are all computed with the rounding rule **round half up to the nearest integer cent**. Where calculation order is specified (most notably for an order's items, where per-line rounding is applied before summation), the order is binding — reversing it can produce a different cent-level result and is treated as a calculation defect.

Portion sizes are integer grams, also rounded half up. Aggregated feedback ratings (average palatability, average stool quality, average coat condition) are computed as floating-point means and then rounded half up to two decimal places.

### 2.6. Nested Resource Resolution

Several endpoints embed multiple resource identifiers in their URL path — for instance a path containing `{customerId}`, `{petId}`, and `{adjId}`. Path parameters are validated **left to right**: the leftmost id is checked first, then the next, and so on. The first missing id surfaces the corresponding 404 from the catalog `ERR_CUSTOMER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PET_NOT_FOUND`, `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_WAREHOUSE_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, or `ERR_FEEDBACK_NOT_FOUND`, and the request returns without checking the remaining ids. After the existence check, parent-child relationships are also enforced — for example, the `{petId}` on a recipe-adjustment path must belong to the household of the `Customer` whose id is `X-User-ID`, and the `{adjId}` must in turn reference that `{petId}`; mismatches are surfaced as `ERR_INSUFFICIENT_PERMISSIONS` (for a `Customer` reaching across households) or as the relevant `*_NOT_FOUND` (when the relationship is broken).

### 2.7. Validation Ordering

When a single request is subject to multiple validation rules, evaluation runs in a fixed priority order. Authentication (presence and validity of the user-context headers) is evaluated first; role authorization for the endpoint is evaluated second; then path-parameter existence, left to right; then subscription-level state preconditions; then resource-level state preconditions for the specific transition; then the safety rules (allergen exclusion and the vet-prescribed gate); then temporal windows (the modification deadline and pause-window overlap); then referential checks (recipe eligibility); then capacity and inventory checks; then payload-shape checks; finally the optimistic-concurrency `version` check. Earlier rules short-circuit later ones — if compliance and existence both fail for the same request, only the higher-priority `ERR_*_NOT_FOUND` is returned. This ordering is the discriminator for several of the concurrency scenarios in §3 and is the reason a stale-version conflict can never mask a state error (state precedes version in the order).

### 2.8. Logical Clock and Deferred Side Effects

The system maintains a logical clock that advances only when an administrator invokes the clock-advance capability described in §3.7. Advancing the clock to a future instant triggers three deferred side effects in this order: (a) the cycle scheduler emits one new `Order` per `ACTIVE` subscription whose `next_cycle_at` is now in the past, (b) any `PAUSED` subscription whose `paused_until` falls at or before the new clock value is automatically resumed and its `next_cycle_at` recomputed, and (c) any `SCHEDULED` `Order` whose `scheduled_ship_at` minus `modification_deadline_hours` falls at or before the new clock value is auto-confirmed via the same path as a customer-initiated confirmation. Calculations whose result depends on the current time — most importantly `life_stage` derivation for every pet — are re-evaluated whenever the clock advances.

### 2.9. Audit Logging

Customer-visible plan changes and feedback-driven adjustments are recorded as `AuditLog` entries. Every entry captures `actor_role`, `actor_id`, `entity_type`, `entity_id`, `event_type`, a `before` snapshot of the fields that changed, an `after` snapshot of the fields that changed, and `ts` (the logical clock time at which the entry was written). The recognized `event_type` tokens are `PLAN_MODIFIED`, `SKIPPED`, `PAUSED`, `RESUMED`, `CANCELLED`, `REACTIVATED`, `ADJUSTMENT_APPLIED`, `ADJUSTMENT_DISMISSED`, and `VET_ESCALATED`. `AuditLog` rows are append-only and immutable; the read endpoint is exposed only to `AdminOps`.

### 2.10. Conserved Invariants

Two ledger-style invariants must hold across every mutation that touches their inputs:

- **Cycle counters.** For every `Subscription`, the equality `scheduled_order_count + skipped_count == total_cycles_elapsed` must be true at all times. The scheduler increments both `scheduled_order_count` and `total_cycles_elapsed` by one when it emits an `Order`; a successful skip decrements `scheduled_order_count` by one and increments `skipped_count` by one (leaving `total_cycles_elapsed` unchanged because the cycle was already counted at generation time); a cancel cascade that turns a `SCHEDULED` or `CONFIRMED` `Order` into a `CANCELLED` one moves no counters (the cycle still counts as scheduled-then-cancelled). The skip path is the compensating action of the scheduler with respect to this invariant, and the three counters must move in lock-step in any implementation.
- **Money counters.** For every `Customer`, the sum of `total_cents` across the customer's orders whose `payment_status` is `PAID` must equal `total_charged_cents`, and the sum of `total_cents` across the customer's orders whose `payment_status` is `REFUNDED` must equal `total_refunded_cents`. A refund follows a fulfillment cancellation on a `PAID` order — both counters move in lock-step.

### 2.11. Catalog Immutability

`Recipe` is an immutable catalog: once created, its fields cannot be mutated. `RecipeRecommendation` becomes immutable the moment it transitions to `FROZEN`. `AuditLog` rows are write-once. `Pet.photo_gallery` is append-only — once a photo with its `photo_id`, `url`, and `uploaded_at` is appended via the gallery endpoint, that element cannot be edited or removed. `Pet.adjustment_history` is also append-only and only writes entries (each carrying `adjustment_id`, `applied_at`, and `summary`) when a `RecipeAdjustment` for that pet transitions into the `APPLIED` state.

## 3. Business Logic & Workflows

### 3.1. Customers, Pets, and Address Verification

A household begins with a `Customer`. The acting party submits an `email` (unique per `Customer`) and a `display_name`, optionally with a `default_shipping_address`. Address payloads share a consistent shape: `line1`, optional `line2`, `city`, `region`, `postal_code`, `country` (ISO 3166-1 alpha-2), and `verified`. On create, `verified` is forced to `false` regardless of input; the address must be verified through the dedicated verification capability before any downstream operation that requires a verified address may proceed.

Address verification is run by invoking the customer-level verify capability (which targets `default_shipping_address`) or the subscription-level verify capability (which targets the subscription's `shipping_address`). The verification calculation marks `verified` as `true` only when **all four** of the following hold simultaneously: `country` is one of `US`, `CA`, `UK`, `AU`, `DE`, `FR`, `JP`, `CN`; `postal_code` matches the country's format (for US, five digits optionally followed by a hyphen and four digits; for every other supported country, any non-empty string); `line1` is non-empty; and `city` is non-empty. If any of the four checks fails, `verified` remains `false` and the call is rejected with `ERR_ADDRESS_VERIFICATION_FAILED`.

Customer-owned pets are created underneath the customer. A pet carries a `name`, a `species` (one of `DOG` or `CAT`), a free-text `breed`, a `birthdate` (ISO date `YYYY-MM-DD`), an integer-or-decimal `weight_kg` strictly greater than 0 and at most 100, an `activity_level` (one of `LOW`, `MODERATE`, or `HIGH`), and four optional ingredient-token lists — `allergies`, `intolerances`, `dietary_preferences`, and `dietary_aversions`. The `allergies` and `intolerances` vocabularies are shared (`CHICKEN`, `BEEF`, `FISH`, `GRAIN`, `DAIRY`, `EGG`, `SOY`, and similar tokens), but `allergies` are enforced as a hard exclusion while `intolerances` only apply a soft scoring penalty. Customers may also supply `health_conditions`, a subset of `{KIDNEY, DIABETES, DENTAL}` that gates whether vet-prescribed recipes are eligible.

On create, the pet's `life_stage` is computed from `species` and `birthdate`; the system fills `photo_gallery` and `adjustment_history` with empty arrays, sets `status` to `ACTIVE`, and the `customer_id` is taken from the path parameter. `life_stage` is `PUPPY_KITTEN`, `ADULT`, or `SENIOR`, derived from the age in whole months — where months equals the number of whole 30-day intervals between `birthdate` and the logical clock's current UTC date, rounded down. For dogs, fewer than 12 months gives `PUPPY_KITTEN`, fewer than 84 gives `ADULT`, and 84 or more gives `SENIOR`. For cats, fewer than 12 months gives `PUPPY_KITTEN`, fewer than 120 gives `ADULT`, and 120 or more gives `SENIOR`. `life_stage` is recomputed on every pet write and again on every logical-clock advance, so a cat that crosses the 120-month threshold during an advance has its `life_stage` move to `SENIOR` before the cycle scheduler runs.

The pet update capability accepts changes to `weight_kg`, `activity_level`, `allergies`, `intolerances`, `dietary_preferences`, `dietary_aversions`, and `health_conditions`, with an optional `version` for the concurrency check. `birthdate` is not editable; the implementation must reject any attempt to change it. A successful update bumps the pet's `version` and refreshes its `updated_at`.

Customers append photos one at a time by calling the photo-gallery capability with a single `url`; the system mints a fresh `photo_id` and `uploaded_at`, appends the resulting object to `photo_gallery`, and returns the updated pet. Photos cannot be edited or removed once appended.

### 3.2. Subscription Lifecycle

A subscription is a single household's recurring food plan. On creation, the customer supplies `pet_ids` (a non-empty array of distinct `Pet.id` values, all of which must belong to this customer and all of which must be in `ACTIVE` status), a `frequency` (`WEEKLY`, `BIWEEKLY`, or `MONTHLY`), a `shipping_address`, and an optional `is_trial` flag that defaults to `false`. The server derives `cycle_days` from frequency — 7 for weekly, 14 for biweekly, 30 for monthly — and copies the supplied address into `shipping_address`, forcing its `verified` to `false`. The new subscription's `status` is `DRAFT` and the `customer_id` is taken from the path. `paused_until`, `cancel_reason`, and `next_cycle_at` are initialized to null; `retention_offer_applied` is `false`; the three cycle counters `scheduled_order_count`, `skipped_count`, and `total_cycles_elapsed` are all 0; and `modification_deadline_hours` defaults to 48.

A `DRAFT` subscription moves to `ACTIVE` when the customer invokes activation, provided that the subscription's `shipping_address` has been verified (otherwise `ERR_ADDRESS_NOT_VERIFIED`) and that every pet in `pet_ids` is in `ACTIVE` status (otherwise `ERR_PET_NOT_ACTIVE`). Activation sets `next_cycle_at` to the current logical clock plus `cycle_days`, computes one initial `PENDING` `RecipeRecommendation` for each pet, and appends a `PLAN_MODIFIED` audit entry.

An `ACTIVE` subscription may be paused. The pause call accepts a single `pause_until` instant in the request body. Pause is rejected with `ERR_INVALID_SUBSCRIPTION_STATE` if the subscription is not currently in `ACTIVE`, with `ERR_PAUSE_BLOCKED_IN_TRANSIT` if any of the subscription's orders is currently in `SHIPPED` but not yet `DELIVERED` (the system will not pause a shipment in transit), with `ERR_INVALID_PAUSE_WINDOW` if `pause_until` is less than or equal to the current logical clock, and with `ERR_PAUSE_WINDOW_OVERLAP` if the new half-open window `[now, pause_until)` overlaps any existing pause window recorded for this subscription. When pause succeeds, `status` becomes `PAUSED`, `paused_until` is set to the supplied `pause_until`, `next_cycle_at` is cleared to null, every `SCHEDULED` order on the subscription whose `payment_status` is `PENDING` and whose `scheduled_ship_at` is strictly before `paused_until` has its `fulfillment_status` cascaded to `CANCELLED` (its `payment_status` is left as `PENDING`), and a `PAUSED` audit entry is appended.

A `PAUSED` subscription returns to `ACTIVE` either automatically — when an admin advances the logical clock to a point at or after `paused_until` — or manually, when the customer invokes the resume capability. Either path requires that the subscription is currently in `PAUSED` (otherwise `ERR_INVALID_SUBSCRIPTION_STATE`); the side effects in both cases are identical: `paused_until` is cleared to null, `next_cycle_at` is set to the current logical clock plus `cycle_days`, and a `RESUMED` audit entry is appended.

Cancellation is a deliberate two-call dance for the `PRICE` reason. From either `ACTIVE` or `PAUSED`, the customer invokes cancel with a `cancel_reason` field whose value must be one of `PRICE`, `QUALITY`, `PET_NO_LONGER`, or `OTHER` (any other value is rejected with `ERR_INVALID_CANCEL_REASON`) and an optional `force` flag. When `cancel_reason` is `PRICE` and `retention_offer_applied` is currently `false` and `force` is not `true`, the cancel is **deflected**: `retention_offer_applied` is set to `true`, the subscription's `status` remains unchanged (`ACTIVE` or `PAUSED`), and the response carries HTTP 200 with the retention offer payload (a single one-cycle 50% discount). The customer must re-invoke cancel — typically with `force` true — to commit the cancellation. Any cancel that is not deflected sets `status` to `CANCELLED` and `cancel_reason` to the supplied value, clears `next_cycle_at` to null, cascades every non-terminal `Order` on the subscription to `fulfillment_status` `CANCELLED` (payment dimension untouched), supersedes every `PENDING` or `FROZEN` `RecipeRecommendation` to `SUPERSEDED`, and appends a `CANCELLED` audit entry.

`CANCELLED` is **not** a terminal state — a customer may reactivate. The reactivate capability requires the subscription's current `status` to be `CANCELLED` (otherwise `ERR_INVALID_SUBSCRIPTION_STATE`) and every pet in `pet_ids` to still exist and be in `ACTIVE` status (otherwise `ERR_PET_NOT_ACTIVE`); on success the status moves to `REACTIVATING` and the customer must verify the shipping address again before they can call activation a second time. The transition from `REACTIVATING` back to `ACTIVE` reuses the activate capability and re-enforces the address-verified precondition; on success it sets `next_cycle_at` to the current logical clock plus `cycle_days`, resets `retention_offer_applied` back to `false` so the retention deflection can fire again in a future lifecycle, and appends a `REACTIVATED` audit entry.

The subscription modify capability accepts changes to `frequency`, `pet_ids`, and `shipping_address`, plus an optional `version` for the concurrency check. While the subscription is `ACTIVE`, any plan modification is subject to the same modification-deadline check that governs skips: the next non-terminal `SCHEDULED` order's `scheduled_ship_at` minus `modification_deadline_hours` must remain strictly in the future (the boundary is strict less-than — equality at exactly the cutoff is rejected with `ERR_MODIFICATION_DEADLINE_PASSED`). If `pet_ids` is included, the resulting list must be non-empty, contain only ids that belong to the requesting customer, and have all member pets in `ACTIVE` status; failures surface as `ERR_INVALID_PET_LIST` or `ERR_PET_NOT_ACTIVE`. If `frequency` changes, `cycle_days` is rederived and `next_cycle_at` is recomputed. If `shipping_address` is supplied (even to the same value), its `verified` flag is forced back to `false` and a fresh verify call is required before the next activation, confirmation, or reactivation. Every successful modify appends a `PLAN_MODIFIED` audit entry.

### 3.3. Recipe Catalog, Eligibility, and Recommendation

The recipe catalog is owned by `AdminOps` and seeded ahead of time. A `Recipe` carries a stable `code`, a `target_species` of `DOG` or `CAT`, a `target_life_stage` (one of `PUPPY_KITTEN`, `ADULT`, `SENIOR`, or the wildcard `ALL` that matches every life stage), three ingredient-token lists `protein_sources`, `grain_sources` (empty for grain-free recipes), and `supplement_sources`, an energy density `kcal_per_gram` strictly greater than 0 and at most 10, a `unit_price_cents_per_100g` of at least 1, a `vet_prescribed` boolean that defaults to `false`, a `prescribed_for` list of required-condition tokens (a subset of `{KIDNEY, DIABETES, DENTAL}`) that must be non-empty when `vet_prescribed` is true, a rotation-grouping `monotony_class` label, and a `trial_eligible` boolean that defaults to `true`. Once created, the catalog row is immutable.

A `RecipeRecommendation` is the per-pet, per-cycle binding from the catalog to a particular pet for a particular cycle. It carries the owning `subscription_id`, the specific `pet_id`, a 1-based `cycle_index`, the selected `recipe_id`, a `match_score` in the range 0 to 100 used as a tie-break key, an append-only `explanation` array of ordered tokens describing the choice (`LIFE_STAGE_MATCH`, `ALLERGEN_CLEAR`, `PREFERRED_PROTEIN_HIT`, `ROTATION_OK`, and similar), and a `status` that begins at `PENDING`, moves to `FROZEN` when the cycle scheduler uses it to emit an `Order` (its `recipe_id` is then pinned into the order's items array), or moves to `SUPERSEDED` when a `RecipeAdjustment` is applied to regenerate a fresh recommendation, or when a subscription is cancelled.

Recommendations are produced by the recipe selector. The selector first runs an **eligibility filter** against every recipe in the catalog and eliminates a candidate if any of these is true: the recipe's `target_species` does not equal the pet's `species`; the recipe's `target_life_stage` is neither equal to the pet's `life_stage` nor equal to the wildcard `ALL`; any token in the pet's `allergies` appears in the union of `protein_sources`, `grain_sources`, and `supplement_sources` (this is a strict hard gate — `ERR_ALLERGEN_PROHIBITED`); the pet has at least one entry in `health_conditions` and the recipe is not `vet_prescribed` whose `prescribed_for` intersects the pet's `health_conditions` (an `ERR_VET_PRESCRIBED_REQUIRED` violation), or, symmetrically, the pet has an empty `health_conditions` list and the recipe is `vet_prescribed` (a healthy pet must not be put on a prescription diet — also `ERR_VET_PRESCRIBED_REQUIRED`); the subscription's `is_trial` is `true` and the current `cycle_index` is 1 and the recipe's `trial_eligible` is `false`; or the recipe's `monotony_class` is equal to the `monotony_class` of the recipe that was used for this pet in the most recent prior `Order` whose `fulfillment_status` is one of `CONFIRMED`, `SHIPPED`, or `DELIVERED` (`SKIPPED` and `CANCELLED` orders do not count toward rotation history — `ERR_ROTATION_VIOLATION`). Selecting the "most recent prior order" for the rotation check sorts orders by `cycle_index` descending, breaking ties by `id` in ASCII descending order.

The pets's vet-prescribed gate has two symmetric branches that must both be enforced. The **strict** variant fires when the pet has at least one health-condition tag: only vet-prescribed recipes whose `prescribed_for` overlaps the pet's `health_conditions` are eligible, and any non-prescribed recipe is eliminated even if it would otherwise score high. The **relaxed** variant fires when the pet's `health_conditions` is empty: vet-prescribed recipes are eliminated entirely, and regular recipes compete on score normally. Both branches must be evaluated with equal rigor — the difference between them is the eligibility decision, not the surfaced error.

Surviving candidates are then ranked by `match_score` in descending order. The score is computed as follows: start at 0; if the recipe is `vet_prescribed` and survived the prescribed gate, add 40; if the recipe's `target_life_stage` equals the pet's `life_stage` exactly (the wildcard `ALL` does not earn this bonus), add 30; for every token shared between the pet's `dietary_preferences` and the union of `protein_sources` and `supplement_sources`, add 10; for every token shared between the pet's `dietary_aversions` and the union of `protein_sources`, `grain_sources`, and `supplement_sources`, subtract 5; for every token shared between the pet's `intolerances` and the union of `protein_sources`, `grain_sources`, and `supplement_sources`, subtract 15. Ties in the resulting score are broken first by recipe `code` in ASCII ascending order, then by recipe `id` in ASCII ascending order. If the candidate pool is empty after eligibility filtering, the call surfaces `ERR_NO_RECIPE_AVAILABLE` and no recommendation is written.

### 3.4. Order Generation, Confirmation, and Lifecycle

Orders are not created by the customer — they are emitted by the cycle scheduler when an administrator advances the logical clock. For every subscription whose `status` is `ACTIVE` and whose `next_cycle_at` is at or before the new clock value, the scheduler emits **one** new `Order` per advance. The new order's `cycle_index` is `scheduled_order_count + 1`; its `scheduled_ship_at` is the current logical clock plus 72 hours of shipping lead time; its `subscription_id` and `customer_id` are denormalized from the subscription; its `payment_status` starts at `PENDING` and its `fulfillment_status` starts at `SCHEDULED`; its `tracking_number` is null. The order's `items` array is computed from each pet's `FROZEN` recommendation — any `PENDING` recommendations are regenerated first to ensure they reflect current pet state, then transitioned to `FROZEN` by the act of being consumed. Each element of `items` contains the `pet_id`, the pinned `recipe_id`, the per-day `portion_grams_per_day`, the `total_grams` for the cycle, the recipe's `unit_price_cents` (sourced from `unit_price_cents_per_100g`), and the line's `line_total_cents`.

After emitting, the scheduler increments the subscription's `scheduled_order_count` by one and the subscription's `total_cycles_elapsed` by one, then advances `next_cycle_at` by `cycle_days`. The scheduler emits at most one order per subscription per advance — if multiple cycles have elapsed since the last advance, the catch-up orders are deferred to subsequent advances. When the subscription's `is_trial` is true and the order's `cycle_index` is 1, the order's `is_trial_pack` is set to `true`; for all other orders `is_trial_pack` is `false`.

Per-pet portion size — `portion_grams_per_day` — is computed in two stages. First, the Resting Energy Requirement is `RER = 70 * (weight_kg ** 0.75)` kilocalories per day, where the coefficient 70 and exponent 0.75 are fixed. Multiply RER by the activity factor — 1.2 for `LOW`, 1.6 for `MODERATE`, 2.0 for `HIGH` — to get an activity-adjusted daily energy. Multiply that by the life-stage factor — 1.8 for `PUPPY_KITTEN`, 1.0 for `ADULT`, 0.8 for `SENIOR` — to get the daily kilocalorie target. Divide that daily kilocalorie figure by the selected recipe's `kcal_per_gram` to get a raw gram count, and round the raw gram count half up to the nearest integer to obtain `portion_grams_per_day`. There are two variants of this calculation. The **provisional** variant, used by the scheduler at order emission, takes `weight_kg` as currently recorded on the pet; its result lands in the order's `items[].portion_grams_per_day`. The **feedback-adjusted** variant, used when a `RecipeAdjustment` whose `portion_delta_pct` is not null transitions to `APPLIED`, takes the provisional portion, applies the signed `portion_delta_pct` percentage change to it before the recipe lookup, and then re-rounds the result half up. The same pet at the same wall-time can therefore have a different gram value on the provisional path than on the feedback-adjusted path.

Order totals follow a fixed evaluation order that is binding. For each item, `total_grams` is `portion_grams_per_day * cycle_days`; `line_total_cents` is `(total_grams / 100) * recipe.unit_price_cents_per_100g` rounded half up **per line** to an integer cent. The subtotal `subtotal_cents` is the sum of the per-line line totals — this is sum-after-round, not round-after-sum, and reversing the two operations is a defect. When the order's `is_trial_pack` is `true`, the subtotal is then multiplied by 0.5 and rounded half up to an integer cent (the 50% trial discount applies to the subtotal before shipping). `shipping_fee_cents` is then computed from the resulting subtotal by tier: when `subtotal_cents` is at least 8000 (eighty dollars), shipping is 0; when `subtotal_cents` is at least 4000 (forty dollars) but less than 8000, shipping is 499 (four dollars and ninety-nine cents); when `subtotal_cents` is below 4000, shipping is 999 (nine dollars and ninety-nine cents). The tier boundary is inclusive on the upper side — a subtotal of exactly 8000 ships free, 7999 ships at 499, and 3999 ships at 999. Finally, `total_cents` is the sum of the subtotal and the shipping fee.

A `SCHEDULED` order moves to `CONFIRMED` either when the customer invokes confirmation directly or when an administrator advances the logical clock past `scheduled_ship_at` minus `modification_deadline_hours` (in which case the order auto-confirms). Confirmation requires that the owning subscription's `status` is `ACTIVE` (otherwise `ERR_INVALID_SUBSCRIPTION_STATE`), that the order's `shipping_address_snapshot` (taken at confirmation time from the subscription's current `shipping_address`) has `verified` equal to `true` (otherwise `ERR_ADDRESS_NOT_VERIFIED`), that the warehouse selector returns a non-empty candidate set (otherwise `ERR_NO_WAREHOUSE_AVAILABLE`), and that every item can be assigned to a non-expired `InventoryLot` with sufficient grams on hand (otherwise `ERR_INSUFFICIENT_INVENTORY`). On success, the order's `warehouse_id` is set to the selector's output, its `assigned_lots` array is populated by the lot selector (each element holds the `item_index`, the chosen `lot_id`, the lot's `batch_code` and `expiration_date`, and the `grams_drawn`), each chosen `InventoryLot` has its `quantity_grams` decremented atomically by the item's `total_grams`, and the chosen warehouse's daily outbound capacity for the `scheduled_ship_at` UTC date is debited by one.

The warehouse selector first filters: only warehouses whose `status` is `ONLINE` are eligible; the order's `shipping_address_snapshot.region` must appear in the warehouse's `serves_regions`; for every item there must exist at least one `InventoryLot` at this warehouse for the item's `recipe_id` whose `expiration_date` is strictly after `scheduled_ship_at` and whose `quantity_grams` is at least the item's `total_grams`; and the warehouse's daily outbound capacity for the `scheduled_ship_at` UTC date must not yet be exhausted. Surviving warehouses are ranked by `priority_rank` in ascending order (smaller wins), with ties broken by `code` in ASCII ascending order. An empty candidate set surfaces `ERR_NO_WAREHOUSE_AVAILABLE`. The lot selector then runs per item against the chosen warehouse and picks, from the lots that satisfy the same expiration and quantity criteria, the one with the earliest `expiration_date` (First-Expire-First-Out), breaking ties first by `batch_code` in ASCII ascending order and then by `id` in ASCII ascending order. The lot's `quantity_grams` is decremented atomically by the item's `total_grams`; the resulting balance must never become negative — if two confirmations race for the last gram of the same lot, exactly one wins and the loser receives `ERR_INSUFFICIENT_INVENTORY`. If two confirmations race for the last unit of a warehouse's daily capacity, exactly one wins on the warehouse daily ledger and the loser receives `ERR_WAREHOUSE_CAPACITY_EXCEEDED`. The warehouse daily-capacity rule treats the `scheduled_ship_at` UTC date as a closed-closed window — every order whose `scheduled_ship_at` falls on the same UTC date debits the same daily counter, and a request that would push the counter past the configured `daily_outbound_capacity` is rejected.

A customer may skip a `SCHEDULED` cycle, but only inside the modification window: skip is rejected with `ERR_MODIFICATION_DEADLINE_PASSED` unless the current logical clock is strictly less than the order's `scheduled_ship_at` minus the subscription's `modification_deadline_hours`. The boundary is strict less-than — equality at exactly the cutoff is rejected, not accepted. On a successful skip, the order's `fulfillment_status` moves to `SKIPPED`, the subscription's `scheduled_order_count` is decremented by one (the just-generated order is no longer counted as scheduled), the subscription's `skipped_count` is incremented by one, the subscription's `total_cycles_elapsed` is left unchanged (the cycle was already counted at generation), the subscription's `next_cycle_at` is advanced by another `cycle_days`, and a `SKIPPED` audit entry is appended. If a customer-initiated skip and a system auto-confirm fire on the same order simultaneously, the operation that lands first wins via first-writer-wins on `fulfillment_status`: if the skip's deadline check passes and it commits first, the auto-confirm finds the order in `SKIPPED` and aborts; if the auto-confirm commits first, the skip finds the order no longer in `SCHEDULED` and is rejected with `ERR_INVALID_ORDER_STATE`. Two simultaneous pause requests on the same subscription that produce overlapping windows are serialized by first-writer-wins on `Subscription.status` — the loser receives `ERR_PAUSE_WINDOW_OVERLAP`.

The payment dimension and the fulfillment dimension are parallel: an order carries both a `payment_status` (one of `PENDING`, `PAID`, `REFUNDED`, `FAILED`) and a `fulfillment_status` (one of `SCHEDULED`, `CONFIRMED`, `SKIPPED`, `SHIPPED`, `DELIVERED`, `CANCELLED`), and they advance largely independently. Payment events arrive from the payment system as `PaymentAdapter` posts carrying an `event_type` and optionally an `amount_cents`. A `PAYMENT_CAPTURED` event moves `payment_status` from `PENDING` to `PAID`, provided that `fulfillment_status` is in `{SCHEDULED, CONFIRMED}` (otherwise `ERR_INVALID_ORDER_STATE`), and adds the order's `total_cents` to the customer's `total_charged_cents`. A `PAYMENT_FAILED` event moves `payment_status` from `PENDING` to `FAILED` with no preconditions; if `fulfillment_status` is `SCHEDULED` or `CONFIRMED` at that moment, the fulfillment dimension cascades to `CANCELLED` as a side effect. A `PAYMENT_REFUNDED` event moves `payment_status` from `PAID` to `REFUNDED`, provided that `fulfillment_status` is already `CANCELLED` (otherwise `ERR_INVALID_ORDER_STATE`), and adds the order's `total_cents` to the customer's `total_refunded_cents`.

Logistics events arrive from `LogisticsAdapter` posts carrying an `event_type` and optionally a `tracking_number`. A `SHIPMENT_DISPATCHED` event moves `fulfillment_status` from `CONFIRMED` to `SHIPPED`, provided that `payment_status` is `PAID` (otherwise `ERR_INVALID_ORDER_STATE`), and persists the supplied `tracking_number` on the order. A `DELIVERY_CONFIRMED` event moves `fulfillment_status` from `SHIPPED` to `DELIVERED` with no preconditions and opens the feedback collection window for that order. When the subscription pauses or cancels — or when a payment failure cascades — the fulfillment dimension moves a `SCHEDULED` or `CONFIRMED` order to `CANCELLED`; if `assigned_lots` is non-empty at that moment, the system restores each lot's `quantity_grams` by the `grams_drawn` it had drawn, and if `warehouse_id` is set, the warehouse's daily outbound capacity for that `scheduled_ship_at` UTC date is refunded by one. `DELIVERED` and `CANCELLED` are the terminal fulfillment states; `REFUNDED` is the only terminal payment state (a `PENDING`, `PAID`, or `FAILED` order can still move, but a `REFUNDED` order cannot).

### 3.5. Feedback Loop and Suggestion Engine

Once an order is `DELIVERED`, the feedback collection window opens. The customer submits one `ShipmentFeedback` per pet per order: the row carries the owning `order_id` (taken from the URL path) and a request body containing the `pet_id` (which must be one of the subscription's `pet_ids`), integer ratings `palatability`, `stool_quality`, and `coat_condition` each in the range 1 to 5 inclusive, a signed integer `weight_change_grams`, and an optional free-text `notes`. The system computes `adverse_flag` from the submission — `adverse_flag` is `true` when `palatability` is at most 2 or `stool_quality` is at most 2; otherwise it is `false`. Feedback whose rating fields fall outside `[1, 5]` or whose `weight_change_grams` is not an integer is rejected with `ERR_INVALID_FEEDBACK_PAYLOAD`. On success, the pet's `weight_kg` is updated by adding `weight_change_grams` divided by 1000 (so a +500 g entry raises the weight by 0.5 kg, and a -200 g entry lowers it by 0.2 kg).

Each feedback submission also triggers an aggregation step. The aggregation collects up to the most recent **3** feedback rows for the same pet (the aggregation window), ordered by `created_at` ascending. If fewer than **2** rows are available, no suggestion is emitted and the engine stops. Otherwise the aggregation computes the average palatability, average stool quality, and average coat condition, each as the arithmetic mean rounded half up to two decimal places; it computes `total_weight_change_grams` as the sum of `weight_change_grams` across the window (a signed integer); and it computes `adverse_count` as the number of rows in the window where `palatability` is at most 2 or `stool_quality` is at most 2.

The suggestion engine then evaluates a fixed priority-ordered branch chain, top-down, first-hit-wins, and emits at most one `RecipeAdjustment` whose `based_on_feedback_ids` references the feedback rows that fed the aggregation:

1. **Vet escalation has highest priority.** If `adverse_count` is at least 2, emit a `RecipeAdjustment` whose `suggestion_type` is `VET_ESCALATE`, whose `status` is auto-escalated immediately to `VET_PENDING`, and whose `rationale` is appended with the token `adverse_stool_or_palatability`. The pet's `status` is moved to `VET_HOLD` and a `VET_ESCALATED` audit entry is appended. The engine stops.
2. **Coat decline together with weight loss.** Otherwise, if the average coat condition is at most 2.50 **and** `total_weight_change_grams` is strictly less than 0, emit a `RecipeAdjustment` whose `suggestion_type` is `SWAP_RECIPE_FAMILY`; `target_recipe_id` is computed by re-running the recipe selector with rotation forced on (the chosen recipe must have a different `monotony_class` than the current one); `rationale` is appended with `coat_and_weight_decline`. The engine stops.
3. **Weight gain above tolerance.** Otherwise, if `total_weight_change_grams` is strictly greater than 500 grams, emit a `RecipeAdjustment` whose `suggestion_type` is `DECREASE_PORTION` and whose `portion_delta_pct` is `-10`; `rationale` is appended with `weight_gain_above_tolerance`. The engine stops.
4. **Weight loss above tolerance.** Otherwise, if `total_weight_change_grams` is strictly less than -500 grams, emit a `RecipeAdjustment` whose `suggestion_type` is `INCREASE_PORTION` and whose `portion_delta_pct` is `+10`; `rationale` is appended with `weight_loss_above_tolerance`. The engine stops.
5. **Low palatability without adverse stool.** Otherwise, if the average palatability is at most 3.00, emit a `RecipeAdjustment` whose `suggestion_type` is `ROTATE_PROTEIN`; `target_recipe_id` is computed by re-running the recipe selector with a forced protein-source rotation; `rationale` is appended with `low_palatability_rotation`. The engine stops.
6. **Otherwise** no suggestion is emitted.

A customer manages adjustments under their pets. Listing adjustments accepts `limit`, `offset`, and an optional `status` filter. Applying an adjustment requires the adjustment's current `status` to be either `SUGGESTED` (a regular application) or `VET_APPROVED` (the application that follows a vet approval), and rejects with `ERR_INVALID_ADJUSTMENT_STATE` otherwise; it additionally requires that the adjustment's `suggestion_type` is not `VET_ESCALATE` from the `SUGGESTED` path (those must travel through the vet adapter first), that the pet's `status` is not `VET_HOLD` and not `ARCHIVED` (otherwise `ERR_PET_NOT_ACTIVE`), and that the pet's next non-terminal `SCHEDULED` order has time-to-ship strictly greater than the modification window — equality at the cutoff is rejected with `ERR_MODIFICATION_DEADLINE_PASSED`. The recipe referenced by the adjustment's `target_recipe_id` (when present) must still pass current eligibility for the pet — species, life stage, allergen, vet-prescribed, and rotation — and is rejected with `ERR_RECIPE_NOT_ELIGIBLE` otherwise. On successful apply, the next `PENDING` `RecipeRecommendation` for the pet is regenerated to reflect the adjustment (the prior `PENDING` recommendation is moved to `SUPERSEDED`), the pet's `adjustment_history` is appended with a summary entry carrying the adjustment id, the time stored in `applied_at`, and a short rationale summary, and an `ADJUSTMENT_APPLIED` audit entry is written. Two simultaneous applies of competing adjustments for the same pet's next cycle are serialized by first-writer-wins on `RecipeAdjustment.status`; the loser receives `ERR_INVALID_ADJUSTMENT_STATE`.

Dismissing a `SUGGESTED` adjustment moves its `status` to `DISMISSED` and appends an `ADJUSTMENT_DISMISSED` audit entry; it has no further side effects. Manually escalating a `SUGGESTED` adjustment moves its `status` to `VET_PENDING`, sets the pet's `status` to `VET_HOLD`, and appends a `VET_ESCALATED` audit entry. The vet system then delivers a verdict by posting a vet event with `event_type` `VET_APPROVED` or `VET_REJECTED`. A `VET_APPROVED` event moves the adjustment from `VET_PENDING` to `VET_APPROVED` and restores the pet's `status` to `ACTIVE`; the customer must then call apply a second time to commit the adjustment, at which point the pet's `status` must still be `ACTIVE` (otherwise `ERR_PET_NOT_ACTIVE`) and the same side effects as a regular apply run. A `VET_REJECTED` event moves the adjustment from `VET_PENDING` to `VET_REJECTED`, restores the pet's `status` to `ACTIVE`, and appends an `ADJUSTMENT_DISMISSED` audit entry whose rationale records the vet rejection. `APPLIED`, `DISMISSED`, and `VET_REJECTED` are the terminal states for an adjustment.

### 3.6. Warehouses and Inventory

`AdminOps` seeds the fulfillment network. Each `Warehouse` carries a unique `code`, a `serves_regions` list of region tokens against which a subscription's `shipping_address.region` is matched, a `priority_rank` in the range 1 to 100 (smaller ranks are preferred when multiple warehouses serve the same region), a `daily_outbound_capacity` of at least 1, and a `status` of `ONLINE` or `OFFLINE` (`OFFLINE` warehouses are excluded from routing entirely). The warehouse-update capability accepts changes to `status`, `daily_outbound_capacity`, and `priority_rank`, with the optional `version` for concurrency control. Inventory lots are added underneath a warehouse and carry `warehouse_id` (system-set from the path), a `recipe_id`, a `batch_code` (unique per warehouse and recipe), an `expiration_date` (an ISO date string — the lot is unusable on or after this date), and an integer `quantity_grams` of at least 0 (the balance is decremented on order confirmation and must never become negative). Listing lots accepts `limit`, `offset`, and an optional `recipe_id` filter.

### 3.7. Administrative and Test-Driver Capabilities

Two administrator-only capabilities exist to make the system reachable from automated tests. The first is a logical-clock advance capability that accepts either an absolute `to` instant or a relative `by_hours` duration; on invocation, the logical clock moves forward to the resulting instant and the three deferred side effects — cycle scheduling, automatic pause resumption, and automatic order confirmation past the modification cutoff — run in that order. The second is an event-emit capability that accepts a `system` identifier (one of `payment`, `logistics`, `im`, `vet`), an `event_type`, and an optional `payload`; the call routes the synthetic event to the corresponding adapter so that tests need not address a specific order or adjustment to drive a system event.

`AdminOps` also reads the audit log with optional filters `entity_type`, `entity_id`, and `event_type` alongside the standard `limit` and `offset` pagination.

## 4. Endpoint Definitions

All endpoints are mounted under the `/subscriptions`-rooted API surface described above. New resources (creates) return HTTP 201 with the created resource in `data`; modifications, state transitions, and system-event ingress return HTTP 200 with the updated resource (or `{}` for capabilities with no resource payload). Reads return HTTP 200. All error responses use the standard error envelope from §2.2 with the appropriate 4xx status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/customers` | Create a Customer | `Customer`, `AdminOps` |
| GET    | `/customers/{customerId}` | Get a Customer | `Customer`, `AdminOps` |
| POST   | `/customers/{customerId}/shipping-address/verify` | Verify the customer's default shipping address | `Customer` |
| POST   | `/customers/{customerId}/pets` | Create a Pet | `Customer` |
| GET    | `/customers/{customerId}/pets` | List a customer's Pets | `Customer`, `AdminOps` |
| GET    | `/customers/{customerId}/pets/{petId}` | Get a Pet | `Customer`, `AdminOps` |
| PATCH  | `/customers/{customerId}/pets/{petId}` | Update Pet profile fields | `Customer` |
| POST   | `/customers/{customerId}/pets/{petId}/photos` | Append a photo to the gallery | `Customer` |
| POST   | `/customers/{customerId}/subscriptions` | Create a Subscription (DRAFT) | `Customer` |
| GET    | `/subscriptions/{subId}` | Get a Subscription | `Customer`, `AdminOps` |
| PATCH  | `/subscriptions/{subId}` | Modify a Subscription | `Customer` |
| POST   | `/subscriptions/{subId}/shipping-address/verify` | Verify the subscription's shipping address | `Customer` |
| POST   | `/subscriptions/{subId}/activate` | Activate from DRAFT or REACTIVATING | `Customer` |
| POST   | `/subscriptions/{subId}/pause` | Pause subscription until pause_until | `Customer` |
| POST   | `/subscriptions/{subId}/resume` | Resume from PAUSED | `Customer` |
| POST   | `/subscriptions/{subId}/cancel` | Cancel (may emit a retention offer instead) | `Customer` |
| POST   | `/subscriptions/{subId}/reactivate` | Reactivate a CANCELLED subscription | `Customer` |
| GET    | `/subscriptions/{subId}/orders` | List orders for a subscription | `Customer`, `AdminOps` |
| GET    | `/orders/{orderId}` | Get an Order | `Customer`, `AdminOps` |
| POST   | `/orders/{orderId}/confirm` | Pre-shipment confirmation | `Customer` |
| POST   | `/orders/{orderId}/skip` | Skip this cycle | `Customer` |
| POST   | `/orders/{orderId}/feedback` | Submit ShipmentFeedback | `Customer` |
| POST   | `/orders/{orderId}/events/payment` | Payment-system event ingress | `PaymentAdapter` |
| POST   | `/orders/{orderId}/events/logistics` | Logistics-system event ingress | `LogisticsAdapter` |
| GET    | `/pets/{petId}/recipe-adjustments` | List recipe adjustments for a pet | `Customer`, `AdminOps` |
| GET    | `/pets/{petId}/recipe-adjustments/{adjId}` | Get a single recipe adjustment | `Customer`, `AdminOps` |
| POST   | `/pets/{petId}/recipe-adjustments/{adjId}/apply` | Apply a SUGGESTED or VET_APPROVED adjustment | `Customer` |
| POST   | `/pets/{petId}/recipe-adjustments/{adjId}/dismiss` | Dismiss a suggestion | `Customer` |
| POST   | `/pets/{petId}/recipe-adjustments/{adjId}/escalate` | Manually escalate to vet | `Customer` |
| POST   | `/pets/{petId}/recipe-adjustments/{adjId}/events/vet` | Veterinary-consultation event ingress | `VetAdapter` |
| POST   | `/recipes` | Create a Recipe | `AdminOps` |
| GET    | `/recipes` | List recipes | `Customer`, `AdminOps` |
| GET    | `/recipes/{recipeId}` | Get a Recipe | `Customer`, `AdminOps` |
| GET    | `/pets/{petId}/recipe-recommendations` | List a Pet's RecipeRecommendations | `Customer`, `AdminOps` |
| POST   | `/warehouses` | Create a Warehouse | `AdminOps` |
| GET    | `/warehouses` | List warehouses | `AdminOps` |
| PATCH  | `/warehouses/{warehouseId}` | Update warehouse | `AdminOps` |
| POST   | `/warehouses/{warehouseId}/inventory-lots` | Add an InventoryLot to a warehouse | `AdminOps` |
| GET    | `/warehouses/{warehouseId}/inventory-lots` | List a warehouse's lots | `AdminOps` |
| GET    | `/audit-logs` | List audit log entries | `AdminOps` |
| POST   | `/_clock/advance` | Advance the logical clock | `AdminOps` |
| POST   | `/_events/emit` | Emit a synchronization event (test driver) | `AdminOps` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PET_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RECIPE_NOT_FOUND` | 404 |
| `ERR_ADJUSTMENT_NOT_FOUND` | 404 |
| `ERR_WAREHOUSE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_FEEDBACK_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_FEEDBACK_PAYLOAD` | 422 |
| `ERR_INVALID_PET_LIST` | 422 |
| `ERR_INVALID_CANCEL_REASON` | 400 |
| `ERR_INVALID_PAUSE_WINDOW` | 422 |
| `ERR_INVALID_SUBSCRIPTION_STATE` | 409 |
| `ERR_INVALID_ORDER_STATE` | 409 |
| `ERR_INVALID_ADJUSTMENT_STATE` | 409 |
| `ERR_PET_NOT_ACTIVE` | 409 |
| `ERR_PAUSE_BLOCKED_IN_TRANSIT` | 409 |
| `ERR_MODIFICATION_DEADLINE_PASSED` | 409 |
| `ERR_PAUSE_WINDOW_OVERLAP` | 409 |
| `ERR_ADDRESS_VERIFICATION_FAILED` | 422 |
| `ERR_ADDRESS_NOT_VERIFIED` | 422 |
| `ERR_ALLERGEN_PROHIBITED` | 422 |
| `ERR_VET_PRESCRIBED_REQUIRED` | 422 |
| `ERR_RECIPE_NOT_ELIGIBLE` | 422 |
| `ERR_ROTATION_VIOLATION` | 422 |
| `ERR_NO_RECIPE_AVAILABLE` | 422 |
| `ERR_NO_WAREHOUSE_AVAILABLE` | 409 |
| `ERR_WAREHOUSE_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_INVENTORY` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |

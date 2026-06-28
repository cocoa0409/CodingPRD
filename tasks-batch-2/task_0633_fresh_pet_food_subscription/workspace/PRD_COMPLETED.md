# Fresh Pet-Food Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Fresh Pet-Food Subscription API, a back-end platform for a direct-to-consumer fresh pet-food service in the spirit of The Farmer's Dog and Ollie. Pet parents register an account, build a profile for each pet, and subscribe to a vet-formulated recipe that is portioned precisely to that animal's daily energy needs. The platform's core challenge is nutritional accuracy at scale: every pet's caloric requirement is derived from its species, body weight, life stage, neuter status, activity, and weight-management goal, and that requirement must flow downstream into the grams of food packed per cycle and the price the customer pays.

The service operates as a recurring fulfillment engine. Cooked food is portioned into delivery cycles, charged on a renewal cadence, packed with enough coolant to survive carrier transit, and shipped cold. Around this spine sit the realities of a living subscription: pets gain and lose weight (triggering plan resizes), customers travel (triggering skips, pauses, and swaps), cards decline (triggering past-due recovery and eventual cancellation), and a referral program seeds new accounts with welcome credit while rewarding the referrers who brought them in. Because weight readings, billing renewals, shipments, and credit grants all interact, the system favors deterministic, immediate consistency: every mutation completes its cascade synchronously within the triggering request, and the passage of time is modeled by an explicit logical clock rather than wall-clock so that scheduled effects — resize realizations, paused-window resumes, and spoilage — are reproducible.

This PRD defines the entities, their state machines, the calculation rules governing portioning and billing, the validation and authorization rules, and the full HTTP surface. It is written for the engineers who will implement the service and the reviewers who will verify it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts: authentication, the response envelope, pagination, and the cross-cutting principles that every workflow in Section 3 depends upon.

### 2.1. User and Role-Based Access Control

Every request other than the explicitly anonymous endpoints must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If either header is missing, or if `X-User-Role` is not one of the recognized role names, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When a recognized role attempts an operation it is not permitted to perform — or when ownership is required and the actor does not own the target — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five roles, spelled exactly as follows: `PetParent`, `NutritionVet`, `BillingAdmin`, `FulfillmentOps`, and `Anonymous`.

`PetParent` is the only entity-backed role. When `X-User-Role` is `PetParent`, the value of `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an account compare the resource's owning account (its `account_id`, or for nested resources the account reachable through the parent chain) to `X-User-ID`. A `PetParent` may operate only on their own account, pets, weight logs, subscriptions, orders, and referral credits.

The other four roles are opaque operator identities not tied to any persisted entity. When `X-User-Role` is `NutritionVet`, `BillingAdmin`, `FulfillmentOps`, or `Anonymous`, the value of `X-User-ID` is an opaque operator identifier; the server may accept and log it but does not compare it to any entity's `id`. `NutritionVet` curates recipes and reads pets and weight logs for formulation review. `BillingAdmin` runs the billing lifecycle — order generation, charge, settlement, and retry — and may list all accounts. `FulfillmentOps` runs shipping — order generation, charge, settlement, shipment dispatch and delivery — and advances the logical clock. `Anonymous` is the unauthenticated capacity used to register accounts, preview referral credit, and read the clock; the anonymous endpoints (account registration, referral redeem-preview, the two clock endpoints) do not require the user-context headers.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

The platform models the passage of time through an explicit, server-held logical clock rather than wall-clock time. On server startup the clock defaults to exactly `2026-01-01T00:00:00Z`; before any client sets it, the clock reads precisely that default and never falls back to wall-clock. Any authenticated role may set the clock to an absolute ISO-8601 UTC instant supplied as `to_iso8601`, and any role — including `Anonymous` — may read it. Both clock endpoints (set and read) require no user-context headers and return the resulting clock value in the response envelope's `data` as a single field named `current_utc`, an ISO 8601 UTC timestamp with three fractional digits.

Advancing the clock only moves time forward in the model; it does not itself execute deferred work. Due scheduled effects — a paused subscription's auto-resume, a staged resize's realization, and a shipment's spoilage — are not realized by the clock advance itself. They are realized the next time the relevant business endpoint is invoked: pause auto-resume and resize realization happen during order generation, and spoilage is evaluated at delivery time. Many computations (life stage, weight-log effective dating, ship-date gating, transit elapsed days) read the current clock at the moment the operation runs.

### 2.5. Common Resource Properties and Versioning

Every primary resource carries a server-minted `id`: a UUID with no type prefix, used for identity only. Resources are never addressed by anything other than this `id`.

Most resources additionally carry three system-managed fields. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification; it is refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one on every mutation of the resource; it underpins optimistic concurrency control (see §2.8). The `Account`, `Pet`, `Recipe`, `Subscription`, `Order`, `Shipment`, and `ReferralCredit` resources all carry `created_at`, `updated_at`, and `version`.

The `WeightLog` resource is the sole exception: it is effectively immutable after creation and carries only `id` and `created_at`. A `WeightLog` has no `updated_at` and no `version`. Note, however, that a weight log's `status` may flip between `APPLIED` and `SUPERSEDED` as a bookkeeping consequence of newer readings arriving; this reclassification is not treated as a versioned mutation and does not give the log a `version`.

### 2.6. Precision, Rounding, and Monetary Representation

All monetary values are stored and returned as integer cents. Caloric targets are stored as integer kilocalories. Grams-per-day and coolant-pack counts are whole integers. Wherever the calculation rules in Section 3 call for rounding, the method is **round half up** (a value exactly at the .5 boundary rounds away from zero, upward). Rounding is applied only at the step each rule designates as final; rounding any intermediate quantity that a rule does not explicitly round is forbidden, because intermediate rounding changes downstream results. Integer-only arithmetic (for example, the billing waterfall in §3.7) performs no rounding at all.

### 2.7. Hierarchical Consistency and Cascades

Mutations and their cascades complete atomically within the triggering request. When one operation mutates several resources, all of those mutations land together: each mutated resource has its `updated_at` refreshed and its `version` incremented (except `WeightLog`, which has neither). The cascade patterns are domain-specific and are described in detail in Section 3; the governing principle here is that the server may transition a parent or sibling resource automatically — without a separate client request on that resource — whenever a business rule requires it. Examples include a failed charge bubbling a subscription from `ACTIVE` to `PAST_DUE`, a third consecutive failure cascading `PAST_DUE` to `CANCELLED` and skipping the subscription's remaining scheduled orders, a first paid order granting pending referral credits, and a spoiled shipment minting a make-good credit. Each such automatic transition independently bumps the affected resource's `version`.

### 2.8. Optimistic Concurrency Control on Subscriptions

Two subscription operations are guarded by optimistic concurrency control because they compute grams, cadence, and price against a snapshot of the subscription that a concurrent writer may already have invalidated. Both require the caller to supply `expected_subscription_version`, carrying the `version` of the subscription the client last observed.

When generating the next cycle's order, the request must include `expected_subscription_version` equal to the target subscription's current `version`. If another writer has advanced the subscription's `version` since the client last read it — by generating a cycle (which advances `next_order_date` and bumps the version) or by realizing a staged resize — the client's view of cadence, grams, and price is stale, and the generation is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412) rather than minting a duplicate or mispriced cycle.

When staging a plan resize, the request must likewise include `expected_subscription_version` equal to the subscription's current `version`. If another writer has staged a resize or generated an order in the meantime (both bump the version), the grams and price the current request computed against the prior snapshot are stale, and the resize is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412); the client must re-read the subscription and recompute. No other endpoint takes a version field, and endpoints that are not OCC-guarded perform no version check.

### 2.9. Validation Ordering

When several validations apply to a single request, they are evaluated in a fixed priority so that the same failing request always yields the same error. The order is: (1) user-context authentication, surfacing `ERR_MISSING_OR_INVALID_USER_CONTEXT`; (2) role authorization and ownership, surfacing `ERR_FORBIDDEN_ROLE`; (3) existence of every referenced resource, validated left-to-right along the path and body and surfacing the matching not-found error; (4) the target resource's state precondition for the requested transition, surfacing the matching state error; (5) cross-entity referential integrity at activation and swap (recipe published, species match, region availability); (6) allergen safety; (7) temporal-window gates; (8) domain constraints such as cadence and transit-day ranges; (9) the subscription-version optimistic-concurrency check; and (10) fiscal/uniqueness checks at registration. Where a single request could trip several of these, the lower-numbered category is reported first. The remainder of this section and Section 3 attach each individual condition to its specific error.

### 2.10. Left-to-Right Existence Resolution

Existence is checked along the request from the outermost identifier inward. An account identifier is resolved before a pet or recipe identifier; a pet or recipe before a subscription; a subscription before an order; and an order before a shipment. The first identifier that does not resolve produces its corresponding error and halts processing: `ERR_ACCOUNT_NOT_FOUND`, `ERR_PET_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, or `ERR_REFERRAL_CREDIT_NOT_FOUND` for a `referralCreditId` that does not resolve. A malformed body, a missing required field, or a type mismatch is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Accounts, the Referral Program, and the Credit Wallet

An account is the root of ownership. Anyone may register one via the anonymous registration endpoint, supplying an `email`, a `full_name`, an optional `country_code`, and an optional `referral_code`. The `email` is the login identity and must be unique across all accounts (compared case-insensitively); a collision is rejected with `ERR_EMAIL_TAKEN`. The `country_code` is one of `US` or `CA` and defaults to `US` when omitted; it gates which recipes the account may subscribe to, because a recipe ships only to the country codes in its availability list. On creation the account is assigned a server-minted, unique, uppercase eight-character `referral_code` that identifies this account's referral link, and its `status` is set to `ACTIVE`. The status enum carries the single value `ACTIVE` for an account's whole lifetime in this version; referral resolution requires the referrer to be `ACTIVE`.

When a `referral_code` is supplied at registration, it must resolve to an existing `ACTIVE` account; if it does not resolve, the registration is rejected with `ERR_REFERRAL_CODE_INVALID`, and if it resolves to the account being registered it is rejected with `ERR_SELF_REFERRAL`. On a valid code, the new account's `referred_by_account_id` is set to the referrer's `id` (it is null for an organic signup), and two referral-credit rows are minted in `PENDING` status with reason `SIGNUP` — one for each side of the referral. The new account is the `referred_account_id` on both rows; the referrer is the `referrer_account_id`.

Each account exposes two computed fiscal fields. The `wallet_credit_cents` field is the spendable balance: the sum of `amount_cents` across all `GRANTED` referral-credit rows that pay out to this account, minus credit already consumed by paid orders; it is floored so it is never negative. The `lifetime_referral_grants_cents` field accumulates the `referrer_grant_cents` ever granted with this account acting as referrer; it is monotonic and never decreases, and it is the basis for the referrer's annual cap described in §3.8.

### 3.2. Recipes and Their Curation Lifecycle

Recipes are the catalog a subscription draws from, and only a `NutritionVet` may author them. A recipe is created in `DRAFT` with a `name`, a `species` of either `DOG` or `CAT`, a `kcal_per_gram` energy density greater than zero (the metabolizable energy per gram, which converts a pet's calorie target into grams of food), and a `price_per_100g_cents` greater than zero. Three list-valued fields describe its suitability: `ingredient_allergens` holds the allergen tags present in the recipe (for example `CHICKEN` or `GRAIN`) and defaults to empty; `availability_regions` holds the country codes the recipe ships to (for example `US`, `CA`) and defaults to empty; and `vet_formulated` is a boolean, defaulting to false, recording whether a vet certified the formulation.

A recipe's `status` moves through `DRAFT`, `PUBLISHED`, and `RETIRED`, with `RETIRED` terminal. Publishing requires the recipe currently be in `DRAFT`, otherwise the request is rejected with `ERR_RECIPE_NOT_DRAFT`; on success the recipe transitions `DRAFT → PUBLISHED` and becomes selectable by subscriptions. Retiring requires the recipe be `PUBLISHED`, otherwise `ERR_RECIPE_NOT_PUBLISHED`; on success it transitions `PUBLISHED → RETIRED`. A retired recipe can no longer be activated onto or swapped onto — any subsequent activation referencing it is caught by the activation referential gate — but subscriptions that already snapshotted it are unaffected. Only a `PUBLISHED` recipe is selectable; an attempt to select a non-published recipe at activation or swap is rejected with `ERR_RECIPE_NOT_PUBLISHED`.

### 3.3. Pets, Their Caloric Target, and Life Stage

A `PetParent` registers each animal as a `Pet` under their own account, supplying the owning `account_id` (which must equal the acting parent), a `name`, a `species` of `DOG` or `CAT`, a `sex` of `MALE` or `FEMALE`, a `birth_date`, an `initial_weight_kg` greater than zero, and an `ideal_weight_kg` greater than zero. Four optional profile fields tune the nutrition math: `activity_level` is `LOW`, `MODERATE`, or `HIGH` and defaults to `MODERATE`; `neutered` is a boolean defaulting to true; `body_condition_goal` is `LOSE`, `MAINTAIN`, or `GAIN` and defaults to `MAINTAIN`; and `allergen_exclusions` is the list of allergen tags this pet must avoid (for example `[CHICKEN, BEEF, GRAIN]`), defaulting to empty. At creation the pet's `current_weight_kg` is seeded from `initial_weight_kg`, and both `daily_calorie_target` and `life_stage` are computed immediately. A pet's `status` is `ACTIVE` or `ARCHIVED`, with `ARCHIVED` terminal.

**Life stage.** The computed `life_stage` is `PUPPY_KITTEN`, `ADULT`, or `SENIOR`, derived from `birth_date` against the current logical clock. Compute the age in whole years as the number of days between the birth date and the current clock date divided by 365, taking the floor. The pet is `PUPPY_KITTEN` when that age in years is below 1; it is `SENIOR` when the age in years is at least 8; otherwise it is `ADULT`. The `SENIOR` boundary is inclusive at eight years and above, and the `PUPPY_KITTEN` boundary is a strict less-than one year.

**Daily calorie target.** The computed `daily_calorie_target` is the pet's metabolizable-energy requirement in whole kilocalories per day, and its evaluation order is pinned. First determine `life_stage` from the clock as above. Then compute a resting-energy basis: take a species resting-energy coefficient — 70.0 for a `DOG` and 60.0 for a `CAT` — and multiply it by the basis weight raised to the power 0.75. The basis weight is the pet's `ideal_weight_kg` when `body_condition_goal` is either `LOSE` or `GAIN`, and otherwise it is the pet's `current_weight_kg`. Next take four multipliers: a neuter multiplier of 1.0 when the pet is neutered and 1.2 when it is intact; an activity multiplier of 1.0 for `LOW`, 1.2 for `MODERATE`, and 1.5 for `HIGH`; a life-stage multiplier of 1.6 for `PUPPY_KITTEN`, 1.0 for `ADULT`, and 0.9 for `SENIOR`; and a goal multiplier of 0.8 for `LOSE`, 1.0 for `MAINTAIN`, and 1.15 for `GAIN`. Multiply the resting-energy basis by the four multipliers in that order, left to right, and only then round the final product half up to a whole number of kilocalories. No intermediate quantity is rounded.

A pet's mutable profile fields — `activity_level`, `neutered`, `body_condition_goal`, `ideal_weight_kg`, and `allergen_exclusions` — may be updated by the owning parent, and any such update recomputes `daily_calorie_target` immediately. Importantly, updating the pet does not by itself resize any active subscription; the new target sits on the pet until a resize or a new order generation picks it up. A pet may be archived (transitioning `ACTIVE → ARCHIVED`) only when it has no subscription in `ACTIVE`, `PAUSED`, or `PAST_DUE`; an attempt to archive a pet that still has such a subscription is rejected with `ERR_PET_HAS_ACTIVE_SUBSCRIPTION`.

### 3.4. Weight Logging and the Resize Cascade

Weight is the living input to the nutrition math. A `PetParent` records a reading by posting a `WeightLog` carrying the `pet_id`, a `weight_kg` greater than zero, and an optional `effective_date` — the logical-clock instant from which the reading applies. The effective date must not be in the future relative to the current clock; a future-dated reading is rejected with `ERR_WEIGHTLOG_FUTURE_DATED`.

Among all of a pet's logs, exactly one is `APPLIED`: the one with the latest `effective_date`, breaking ties by the earlier `created_at` (ascending). Every other log is `SUPERSEDED`. When a new log arrives, the system re-evaluates this selection across the pet's logs, flips the formerly applied log to `SUPERSEDED` if the new reading wins, and then recomputes the pet's `current_weight_kg` from the `APPLIED` log and recomputes `daily_calorie_target` as a cascade. As with a profile update, recording a weight does not itself resize an active subscription — the recomputed target waits on the pet for a resize or the next order generation to consume it.

A resize is how a changed calorie target reaches a subscription's pack and price. A `PetParent` stages a resize, which recomputes `pack_grams_per_day` from the pet's current `daily_calorie_target` and stages it to take effect at an `effective_at` instant (defaulting to the current clock, i.e. immediate). The staged grams are recorded in `pending_resize_grams_per_day` and the instant in `resize_effective_at`. The effective instant must be at or after the current clock; an effective time in the past is rejected with `ERR_RESIZE_EFFECTIVE_IN_PAST`. If the effective instant is at or before the current clock, the resize is realized immediately into `pack_grams_per_day`, `pack_total_grams`, and `cycle_price_cents`; otherwise it remains staged and is realized later, at order-generation time, once the clock has reached the effective instant. This operation requires `expected_subscription_version` and is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` on a version mismatch, as described in §2.8. Every resize bumps the subscription's `version`.

### 3.5. Subscriptions: Creation, Activation, and the Plan Estimate

A subscription binds a pet to a recipe at a chosen delivery cadence. A `PetParent` creates one in `DRAFT` by supplying the owning `account_id` (which must equal the acting parent), the `pet_id` (which must belong to that account), the `recipe_id`, and an optional `cadence_days`. The cadence is the number of days between deliveries and must be one of 14, 21, or 28, defaulting to 28; any other value is rejected with `ERR_INVALID_CADENCE`. At create time the system also enforces allergen safety: the chosen recipe's `ingredient_allergens` must share no tag with the pet's `allergen_exclusions`, and any overlap is rejected with `ERR_ALLERGEN_CONFLICT`. A draft subscription immediately computes an **estimate** of its pack and price for quoting purposes (see the calculation below). The subscription's `status` enum is `DRAFT`, `ACTIVE`, `PAUSED`, `PAST_DUE`, or `CANCELLED`, with `CANCELLED` terminal.

**Pack grams and the cycle-price estimate.** The pack and price calculation has a load-bearing rounding order: round grams-per-day first, then scale. First compute `pack_grams_per_day` as the pet's `daily_calorie_target` divided by the recipe's `kcal_per_gram`, rounded half up to a whole number of grams per day. Then `pack_total_grams` is that whole grams-per-day figure multiplied by the subscription's `cadence_days`, an exact integer. Express the total as hundreds of grams by dividing `pack_total_grams` by 100 (this may be fractional and is not rounded). Determine a volume discount from the total grams: there is no discount when `pack_total_grams` is below 4000 grams; a five-percent discount when the total is at least 4000 but below 8000 grams; and a ten-percent discount when the total is at least 8000 grams. Apply the discount to the recipe's `price_per_100g_cents` to obtain a per-hundred-gram rate (one minus the discount fraction times the base rate), and do not round this rate. Finally, `cycle_price_cents` is the hundreds-of-grams figure multiplied by that discounted rate, rounded half up to whole cents exactly once at the end. The **estimate** variant of this calculation uses the pet's live `daily_calorie_target`, is not snapshotted, and is recomputed onto `cycle_price_cents` on every resize realization and every recipe swap. The **actual** variant of the same formula is frozen onto an order at generation (see §3.6); a later weight change does not retro-price an order that has already been generated.

**Activation.** A `PetParent` activates a `DRAFT` subscription. Activation requires the subscription be in `DRAFT`, otherwise `ERR_SUBSCRIPTION_NOT_DRAFT`, and it runs the full referential, allergen, and region gate in this order: the referenced pet must be `ACTIVE` (an `ARCHIVED` pet yields `ERR_PET_ARCHIVED`); the referenced recipe must be `PUBLISHED` (`ERR_RECIPE_NOT_PUBLISHED`); the recipe's `species` must equal the pet's `species` (`ERR_RECIPE_SPECIES_MISMATCH`); the recipe's `ingredient_allergens` must be disjoint from the pet's `allergen_exclusions` (`ERR_ALLERGEN_CONFLICT`); and the account's `country_code` must appear in the recipe's `availability_regions` (`ERR_RECIPE_REGION_UNAVAILABLE`). On success the subscription transitions `DRAFT → ACTIVE` and the following are set together: `transition_remaining_cycles` is set to 2; `pack_grams_per_day`, `pack_total_grams`, and `cycle_price_cents` are computed from the pet's `daily_calorie_target` and the recipe; `next_order_date` is set to the current logical-clock date; `consecutive_failed_charges` is set to 0; and the subscription's `version` increments by one.

The `transition_remaining_cycles` field encodes the gradual food-transition schedule: it starts at 2 on first activation and is decremented by one (floored at 0) each time an order for the subscription is settled paid. Any order generated while this counter is still above zero is flagged as a transition cycle.

**Swapping the recipe.** A `PetParent` may swap a subscription onto a different `recipe_id`. The swap re-runs the same referential, allergen, and region gate as activation (published recipe, species match, allergen disjointness, region availability, surfacing the same errors), changes the `recipe_id`, recomputes `pack_grams_per_day`, `pack_total_grams`, and `cycle_price_cents` against the new recipe, and increments the subscription's `version`.

### 3.6. Skip, Pause, Resume, Cancel, and Order Generation

A subscription in flight is steered by skips, pauses, resumes, cancellations, and the renewal generator.

**Pausing and resuming.** A `PetParent` pauses an `ACTIVE` subscription, optionally supplying a `resume_at` instant. Pausing requires the subscription be `ACTIVE` (otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`) and requires that no order for the subscription is currently `CHARGING` (otherwise `ERR_ORDER_IN_FLIGHT`). On success the subscription transitions `ACTIVE → PAUSED`; `pause_until` is set to the supplied `resume_at`, or to null for an indefinite pause when none is supplied; and the version increments. Resuming requires the subscription be `PAUSED` (otherwise `ERR_SUBSCRIPTION_NOT_PAUSED`); it transitions `PAUSED → ACTIVE`, clears `pause_until` to null, sets `next_order_date` to the later of its current value and the current clock date so a paused-through window does not back-bill, and increments the version. A paused subscription also auto-resumes by the system: when an order is generated and the clock has reached or passed `pause_until`, the subscription is first resumed to `ACTIVE` (clearing `pause_until` and advancing `next_order_date` to no earlier than the clock) before the order is minted.

**Skipping an order.** A `PetParent` may skip a `SCHEDULED` order to forgive one cycle without charge. Skipping requires the order be `SCHEDULED` (otherwise `ERR_ORDER_NOT_SCHEDULED`), requires the parent subscription be `ACTIVE` or `PAUSED` (otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`), and requires that the current clock date be strictly before the order's `scheduled_ship_date` — once the ship day arrives or passes, skipping is closed and the request is rejected with `ERR_SKIP_WINDOW_CLOSED`. On success the order transitions `SCHEDULED → SKIPPED`, the subscription's `next_order_date` advances by `cadence_days`, and the subscription's version increments. `SKIPPED` is terminal for that cycle.

**Cancelling.** A `PetParent` may cancel a subscription that is `ACTIVE`, `PAUSED`, or `PAST_DUE`; cancelling one already cancelled is rejected with `ERR_SUBSCRIPTION_ALREADY_CANCELLED`, and cancellation is blocked while any order for the subscription is `CHARGING`, surfacing `ERR_ORDER_IN_FLIGHT`. On success the subscription moves to `CANCELLED` (terminal) and the cancellation cascades: every `SCHEDULED` order for the subscription is moved to `SKIPPED` (only the non-terminal scheduled orders are touched); any staged resize is cleared by setting `pending_resize_grams_per_day` and `resize_effective_at` to null; and if the owning account has no `PAID` order across any of its subscriptions, the account's `PENDING` `SIGNUP` referral-credit rows on which it is the `referred_account_id` are moved to `REVOKED` (only the pending signup rows are touched). The subscription's version increments.

**Generating the next order.** A `BillingAdmin` or `FulfillmentOps` operator generates the next cycle's order for a subscription due on or after its `next_order_date`. Generation imposes no logical-clock precondition of its own: the operator may generate the next cycle even when the current clock has not yet reached `next_order_date`, and the resulting order's `scheduled_ship_date` is the subscription's `next_order_date` at generation regardless of where the clock stands. This write is OCC-guarded: the request must carry `expected_subscription_version` matching the subscription's current `version`, failing with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412) otherwise, per §2.8. Generation realizes any due deferred work before snapshotting: if the subscription is `PAUSED` and the clock has reached or passed `pause_until`, it auto-resumes to `ACTIVE` first; and if a staged resize's `resize_effective_at` is at or before the clock, that resize is realized into the pack fields first. The new order is then created in `SCHEDULED` with a monotonic per-subscription `cycle_index` starting at 1, a `scheduled_ship_date` equal to the subscription's `next_order_date` at generation, a `food_grams` snapshot equal to the subscription's `pack_total_grams`, an `is_transition_cycle` flag set true when `transition_remaining_cycles` was still above zero at generation, and a `food_subtotal_cents` snapshot computed by the actual variant of the cycle-price calculation. Generating the order increments the subscription's `version`.

### 3.7. The Billing Waterfall: Charge, Settlement, Retry, and Past-Due Recovery

Every order carries denormalized billing context — its owning `subscription_id`, the denormalized `account_id` of the owner — and a set of computed billing fields finalized at charge time. The order `status` enum is `SCHEDULED`, `SKIPPED`, `CHARGING`, `PAID`, or `FAILED`, where `SKIPPED` and `PAID` are terminal for the cycle and `FAILED` may be retried.

**Charging.** A `BillingAdmin` or `FulfillmentOps` operator begins charging a `SCHEDULED` order. Charging requires the order be `SCHEDULED` (otherwise `ERR_ORDER_NOT_SCHEDULED`), requires the parent subscription be `ACTIVE` or `PAST_DUE` (a `PAUSED`, `DRAFT`, or `CANCELLED` subscription cannot charge, surfacing `ERR_SUBSCRIPTION_NOT_CHARGEABLE`), and requires the current clock date be on or after the order's `scheduled_ship_date` (otherwise `ERR_CHARGE_BEFORE_SHIP_DATE`). On success the order transitions `SCHEDULED → CHARGING`, and `shipping_cents`, `credit_applied_cents`, and `total_charged_cents` are finalized by the settlement calculation below.

The settlement calculation runs in a pinned order, because shipping eligibility must be decided from the pre-credit subtotal. First take the order's already-snapshotted `food_subtotal_cents`. Second, decide `shipping_cents` from that pre-credit subtotal: cold-pack shipping is free when `food_subtotal_cents` is at least 8000 cents, and otherwise it is a flat 999 cents — the boundary is inclusive, so a subtotal of exactly 8000 ships free while 7999 pays 999. Third, form the gross as `food_subtotal_cents` plus `shipping_cents`. Fourth, set `credit_applied_cents` to the smaller of the account's `wallet_credit_cents` at charge time and that gross. Fifth, set `total_charged_cents` to the gross minus `credit_applied_cents`, which is never negative. All of this is integer-cents arithmetic with no rounding. Computing shipping after applying credit is forbidden, since it would change free-ship eligibility.

**Settlement — success.** A `BillingAdmin` or `FulfillmentOps` operator settles a `CHARGING` order with an `outcome` of either `SUCCEEDED` or `DECLINED`; settling anything not `CHARGING` is rejected with `ERR_ORDER_NOT_CHARGING`. On `SUCCEEDED` the order transitions `CHARGING → PAID` and a cascade fires: the `credit_applied_cents` is consumed from the wallet (the account's `wallet_credit_cents` is recomputed downward to reflect the consumption); the subscription's `consecutive_failed_charges` resets to 0 and, if the subscription was `PAST_DUE`, it recovers to `ACTIVE`; the subscription's `next_order_date` advances by `cadence_days` and its `transition_remaining_cycles` decrements by one with a floor of 0; a `Shipment` is created in `PENDING` for the order; and, if this is the referred account's first `PAID` order, the linked `PENDING` `SIGNUP` referral-credit rows flip to `GRANTED`, cascading into both accounts' wallet and lifetime fields (see §3.8). The subscription's version increments.

**Settlement — decline, and past-due recovery.** On `DECLINED` the order transitions `CHARGING → FAILED`, the subscription's `consecutive_failed_charges` increments, and an `ACTIVE` subscription bubbles to `PAST_DUE` (leaving `next_order_date` unchanged so the same cycle retries). If that increment brings `consecutive_failed_charges` to at least 3, the failure cascades transitively: the subscription moves `PAST_DUE → CANCELLED`, all its `SCHEDULED` orders are skipped to `SKIPPED`, any staged resize is cleared (`pending_resize_grams_per_day` and `resize_effective_at` set to null), and — if the account has no `PAID` order across its subscriptions — its `PENDING` `SIGNUP` referral-credit rows where it is the `referred_account_id` are `REVOKED`. A `BillingAdmin` may retry a `FAILED` order, but only while the parent subscription is `PAST_DUE`: retry requires the order be `FAILED` (otherwise `ERR_ORDER_NOT_FAILED`) and the subscription be `PAST_DUE` (otherwise `ERR_SUBSCRIPTION_NOT_PAST_DUE`). A retry re-finalizes `shipping_cents`, `credit_applied_cents`, and `total_charged_cents` from the current `wallet_credit_cents` and moves the order `FAILED → CHARGING` for another settlement attempt. When a retried order ultimately settles `SUCCEEDED`, the subscription recovers `PAST_DUE → ACTIVE`, its `consecutive_failed_charges` resets to 0, and its `next_order_date` advances by `cadence_days`.

### 3.8. Granting and Revoking Referral Credit

Referral credit threads through the billing lifecycle. At registration, a valid `referral_code` mints two `PENDING` `SIGNUP` rows whose amounts are computed but not yet spendable. The `referred_grant_cents` — the welcome credit to the new account — is a flat 2000 cents. The `referrer_grant_cents` — the reward to the referrer — is the smaller of a flat 1500 cents and the room remaining under the referrer's annual cap, where that room is the larger of 0 and 9000 cents minus the referrer's current `lifetime_referral_grants_cents`; this clamp ensures a referrer's lifetime grants never exceed 9000 cents. Each row records its computed value in `amount_cents`, a `beneficiary` of either `REFERRER` or `REFERRED` indicating which account it pays out to, a `reason` of `SIGNUP` or `MAKE_GOOD`, and a `status` of `PENDING`, `GRANTED`, or `REVOKED`, where `REVOKED` is terminal.

The anonymous redeem-preview endpoint computes the same `referrer_grant_cents` and `referred_grant_cents` for a supplied `referral_code` (honoring the referrer's cap) and returns them alongside the resolving `referrer_account_id`, without registering anything or minting rows.

Both signup rows remain `PENDING` until the referred account's first `PAID` order, at which moment both flip `PENDING → GRANTED` and their amounts lock. On each such grant, the conserved-quantity rule holds exactly: the referrer's `lifetime_referral_grants_cents` increases by precisely that row's `referrer_grant_cents`, and each beneficiary's `wallet_credit_cents` increases by that row's `amount_cents`. A revoke reverses both effects. As described in §3.6 and §3.7, the pending signup rows of an account that never reached a paid order are revoked when the account's last live subscription is cancelled or cascade-cancelled.

A separate compensation path mints credit outside the referral flow. When a shipment is delivered late and spoils (see §3.9), a `MAKE_GOOD` referral-credit row is created already `GRANTED` to the owning account, with the `referred_account_id` set to that beneficiary account, for the full value of the spoiled order — described in the shipment workflow below.

### 3.9. Cold-Pack Shipping: Coolant, Dispatch, Delivery, and Spoilage

A paid order produces a `Shipment` in `PENDING`, carrying the `order_id`, a `transit_days` value (the carrier's transit time, defaulting to 2 and constrained to the range 1 through 5 inclusive — any value outside that range is rejected with `ERR_INVALID_TRANSIT_DAYS`), a computed `coolant_packs` count, a `dispatched_at` instant that is null until dispatch, and a `status` of `PENDING`, `DISPATCHED`, `DELIVERED`, or `SPOILED`, where `DELIVERED` and `SPOILED` are terminal.

**Coolant computation.** The number of cold packs protects the food across transit and is computed from the order's `food_grams` and the shipment's `transit_days`. Take a mass component equal to `food_grams` divided by 4000 grams per pack, rounded up to the next whole number (one pack for each 4000 grams or fraction thereof). Take a day component equal to the transit days beyond a free window of 2 days — that is, the larger of 0 and `transit_days` minus 2 — adding one extra pack per day past the window. The `coolant_packs` count is the larger of a minimum of 1 and the sum of the mass and day components. A `FulfillmentOps` operator may update `transit_days` on a `PENDING` shipment, which recomputes `coolant_packs`; the same range constraint applies and an out-of-range value is rejected with `ERR_INVALID_TRANSIT_DAYS`.

**Dispatch.** A `FulfillmentOps` operator dispatches a `PENDING` shipment. Dispatch requires the shipment be `PENDING` (otherwise `ERR_SHIPMENT_NOT_PENDING`), requires the parent order be `PAID` (only paid food ships, otherwise `ERR_ORDER_NOT_PAID`), and requires that the stored `coolant_packs` be at least the amount the coolant formula requires for the shipment's `transit_days` — if the stored packs fall short the dispatch is rejected with `ERR_INSUFFICIENT_COOLANT`. On success the shipment transitions `PENDING → DISPATCHED` and `dispatched_at` is set to the current logical clock.

**Delivery and spoilage.** A `FulfillmentOps` operator delivers a `DISPATCHED` shipment; delivering anything not `DISPATCHED` is rejected with `ERR_SHIPMENT_NOT_DISPATCHED`, and a shipment already `SPOILED` admits no further transition (`ERR_SHIPMENT_SPOILED`). Delivery compares the elapsed days from `dispatched_at` to the current clock against the shipment's `transit_days`. If the elapsed days are within the transit window (at most `transit_days`), the shipment transitions `DISPATCHED → DELIVERED`. If the elapsed days exceed `transit_days`, the food has spoiled in transit: the shipment transitions `DISPATCHED → SPOILED`, and a make-good compensation row is minted — a `MAKE_GOOD` referral-credit row created `GRANTED` to the owning account for the spoiled order's `credit_applied_cents` plus `total_charged_cents` (a full refund of the order's value returned as wallet credit). On this make-good row both `referred_account_id` and `referrer_account_id` are set to the owning account's `id` and `beneficiary` is `REFERRED`, so the credit pays out to the owning account.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return `201 Created`; operations that modify, transition, or read an existing resource return `200 OK`. Every endpoint returns its resource in the envelope's `data` field as described in §2.2. The request bodies, computed effects, and validation conditions for each endpoint are specified in the Section 3 narratives above; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an absolute UTC instant | FulfillmentOps, BillingAdmin, NutritionVet, PetParent |
| GET | `/_clock` | Read the current logical clock | FulfillmentOps, BillingAdmin, NutritionVet, PetParent, Anonymous |
| POST | `/api/accounts/register` | Register a new account; mint referral credits if a valid code is supplied | Anonymous |
| GET | `/api/accounts/{accountId}` | Read an account with computed wallet and lifetime grant fields | PetParent, BillingAdmin |
| GET | `/api/accounts` | List accounts; filter by `referred_by_account_id` | BillingAdmin |
| POST | `/api/referrals/redeem-preview` | Preview the credit a referral code would yield | Anonymous |
| GET | `/api/referral-credits` | List referral-credit rows; filter by referrer, referred, beneficiary, status | PetParent, BillingAdmin |
| GET | `/api/referral-credits/{referralCreditId}` | Read a single referral-credit row | PetParent, BillingAdmin |
| POST | `/api/recipes` | Create a recipe in DRAFT | NutritionVet |
| POST | `/api/recipes/{recipeId}/publish` | Publish a DRAFT recipe | NutritionVet |
| POST | `/api/recipes/{recipeId}/retire` | Retire a PUBLISHED recipe | NutritionVet |
| GET | `/api/recipes/{recipeId}` | Read a recipe | NutritionVet, PetParent, BillingAdmin |
| GET | `/api/recipes` | List recipes; filter by species and status | NutritionVet, PetParent, BillingAdmin |
| POST | `/api/pets` | Create a pet under the acting account | PetParent |
| GET | `/api/pets/{petId}` | Read a pet with computed nutrition fields | PetParent, NutritionVet, BillingAdmin |
| GET | `/api/pets` | List pets; filter by account and status | PetParent, NutritionVet, BillingAdmin |
| PATCH | `/api/pets/{petId}` | Update mutable pet profile fields; recompute calorie target | PetParent |
| POST | `/api/pets/{petId}/archive` | Archive a pet | PetParent |
| POST | `/api/weight-logs` | Record a body-weight reading; recompute and cascade | PetParent |
| GET | `/api/weight-logs` | List weight logs; filter by pet and status | PetParent, NutritionVet, BillingAdmin |
| GET | `/api/weight-logs/{weightLogId}` | Read a single weight log | PetParent, NutritionVet, BillingAdmin |
| POST | `/api/subscriptions` | Create a subscription in DRAFT | PetParent |
| GET | `/api/subscriptions/{subscriptionId}` | Read a subscription | PetParent, BillingAdmin, FulfillmentOps |
| GET | `/api/subscriptions` | List subscriptions; filter by account, pet, recipe, status | PetParent, BillingAdmin, FulfillmentOps |
| POST | `/api/subscriptions/{subscriptionId}/activate` | Activate a DRAFT subscription | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/pause` | Pause an ACTIVE subscription | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/resume` | Resume a PAUSED subscription | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/swap-recipe` | Swap the subscription's recipe | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/resize` | Stage a plan resize (OCC-guarded) | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/cancel` | Cancel a subscription | PetParent |
| POST | `/api/subscriptions/{subscriptionId}/orders` | Generate the next cycle order (OCC-guarded) | BillingAdmin, FulfillmentOps |
| GET | `/api/orders/{orderId}` | Read an order with computed billing fields | PetParent, BillingAdmin, FulfillmentOps |
| GET | `/api/orders` | List orders; filter by subscription, account, status | PetParent, BillingAdmin, FulfillmentOps |
| POST | `/api/orders/{orderId}/skip` | Skip a SCHEDULED order before its ship date | PetParent |
| POST | `/api/orders/{orderId}/charge` | Begin charging a SCHEDULED order | BillingAdmin, FulfillmentOps |
| POST | `/api/orders/{orderId}/settle-charge` | Settle a CHARGING order with a gateway outcome | BillingAdmin, FulfillmentOps |
| POST | `/api/orders/{orderId}/retry-charge` | Retry a FAILED order while PAST_DUE | BillingAdmin |
| GET | `/api/shipments` | List shipments; filter by order and status | PetParent, FulfillmentOps, BillingAdmin |
| GET | `/api/shipments/{shipmentId}` | Read a shipment with computed coolant | PetParent, FulfillmentOps, BillingAdmin |
| PATCH | `/api/shipments/{shipmentId}` | Update transit days on a PENDING shipment | FulfillmentOps |
| POST | `/api/shipments/{shipmentId}/dispatch` | Dispatch a PENDING shipment | FulfillmentOps |
| POST | `/api/shipments/{shipmentId}/deliver` | Deliver a DISPATCHED shipment, or spoil it if late | FulfillmentOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_PET_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_CREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_DRAFT` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_PAUSED` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_PAST_DUE` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_CHARGEABLE` | 409 Conflict |
| `ERR_SUBSCRIPTION_ALREADY_CANCELLED` | 409 Conflict |
| `ERR_PET_ARCHIVED` | 409 Conflict |
| `ERR_ORDER_NOT_SCHEDULED` | 409 Conflict |
| `ERR_ORDER_NOT_CHARGING` | 409 Conflict |
| `ERR_ORDER_NOT_FAILED` | 409 Conflict |
| `ERR_ORDER_NOT_PAID` | 409 Conflict |
| `ERR_ORDER_IN_FLIGHT` | 409 Conflict |
| `ERR_CHARGE_BEFORE_SHIP_DATE` | 422 Unprocessable Entity |
| `ERR_SHIPMENT_NOT_PENDING` | 409 Conflict |
| `ERR_SHIPMENT_NOT_DISPATCHED` | 409 Conflict |
| `ERR_SHIPMENT_SPOILED` | 409 Conflict |
| `ERR_RECIPE_NOT_DRAFT` | 409 Conflict |
| `ERR_RECIPE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_RECIPE_SPECIES_MISMATCH` | 409 Conflict |
| `ERR_RECIPE_REGION_UNAVAILABLE` | 409 Conflict |
| `ERR_ALLERGEN_CONFLICT` | 422 Unprocessable Entity |
| `ERR_SKIP_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_WEIGHTLOG_FUTURE_DATED` | 422 Unprocessable Entity |
| `ERR_RESIZE_EFFECTIVE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_INVALID_CADENCE` | 422 Unprocessable Entity |
| `ERR_INVALID_TRANSIT_DAYS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_COOLANT` | 422 Unprocessable Entity |
| `ERR_PET_HAS_ACTIVE_SUBSCRIPTION` | 409 Conflict |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 Precondition Failed |
| `ERR_EMAIL_TAKEN` | 409 Conflict |
| `ERR_REFERRAL_CODE_INVALID` | 409 Conflict |
| `ERR_SELF_REFERRAL` | 409 Conflict |

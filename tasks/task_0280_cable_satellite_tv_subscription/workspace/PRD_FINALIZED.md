# Cable / Satellite TV Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Cable / Satellite TV Subscription API, the back-office system of record that operates a residential cable and satellite television service. The platform governs the full commercial relationship with a subscriber: the channel package tier they carry, the premium and add-on channels layered on top, the leased set-top boxes and DVRs in their home, the install and service truck-rolls dispatched to them, the promotional pricing that lures and retains them, and the billing statements that settle each cycle.

At its heart this is a **pricing engine** built over an **event-sourced** account ledger. Every commercial action — activating service, changing tier, attaching a premium channel, applying a promotion, advancing a billing cycle, cancelling — recomputes a single derived figure, the account's monthly recurring charge, by re-aggregating all live line items and reconciling them against any active promotional discount. The engine must keep this figure, the account's regional sports fee, and every issued statement internally consistent even as downgrades cascade into automatic add-on drops, equipment recomputation, and promotional rollback. Several flows compute two parallel variants of the same number — a full-cycle catalog price versus a prorated mid-cycle portion, and a promotion-active price versus its post-rollback catalog price — and the system must apply the correct variant deterministically.

The intended operators are customer-service agents who manage the plan, field technicians who execute visits in the home, billing administrators who issue statements and run cycle advancement, and subscribers acting on their own self-service operations. Because several of these actors can mutate the same account, the platform enforces optimistic concurrency on tier changes and win-back promotions, so that a writer holding a stale view of the account is rejected rather than allowed to silently overwrite a change it never observed.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint. All monetary amounts in this system are integer counts of **cents** unless a field name or sentence states otherwise.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request that is missing either header, or that carries a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation under the role matrix below, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `BillingAdmin`, `CustomerServiceAgent`, `FieldTechnician`, and `Subscriber`.

- A `BillingAdmin` owns catalog configuration, billing-statement issuance, billing-cycle advancement, the early-termination-fee and waiver authority, and the test-driving clock. The `X-User-ID` of a `BillingAdmin` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- A `CustomerServiceAgent` owns the account lifecycle, plan and tier changes, add-on management, and promotions. The `X-User-ID` of a `CustomerServiceAgent` is likewise an opaque operator identifier not tied to any persisted entity, and is not compared to any entity's `id`.
- A `FieldTechnician` executes service visits in the field. This role is entity-backed by the `Technician` catalog entity: when `X-User-Role` is `FieldTechnician`, the `X-User-ID` is the `id` of the acting `Technician`. Ownership checks on any resource that references a technician compare the resource's technician foreign key to `X-User-ID` — concretely, a `FieldTechnician` may dispatch, complete, or mark a no-show only on a `ServiceVisit` whose `technician_id` equals their `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- A `Subscriber` is the account holder performing self-service. This role is entity-backed by the `Account` entity: when `X-User-Role` is `Subscriber`, the `X-User-ID` is the `id` of the owned `Account`. Ownership checks on any account-scoped resource compare the path account's `id` to `X-User-ID`; a `Subscriber` acting on an account they do not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

The role authorized for each endpoint is enumerated in the endpoint table of §4. Some read operations are shared across several roles; the write operations are tightly scoped to the owning role as described throughout §3.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response returns; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries an `id`: a server-minted UUID with no type prefix, generated by the system and never supplied by the client.

Most resources also carry three additional system-managed fields. `created_at` is an ISO 8601 UTC timestamp with three fractional digits, recorded once when the resource is created. `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including mutations that occur as cascades triggered by an operation on a different resource. `version` is an integer that begins at 1 when the resource is created and increases by exactly 1 on each mutation; it is the basis of optimistic concurrency control described in §2.9.

Four catalog-style entities are immutable reference data and therefore carry only `id` and `created_at` — they have **no** `updated_at` and **no** `version` field: the `Technician` directory entity, and the `RegionalSportsFeeRule` rate-table entity. The remaining catalog entities `ChannelPackage`, `PremiumChannel`, `EquipmentModel`, and `PromotionOffer` are full resources that do carry `updated_at` and `version`. Wherever a derived field on the `Account` (such as `monthly_recurring_cents` or `regional_sports_fee_cents`) is recomputed, that recomputation is a mutation of the account: it refreshes the account's `updated_at` and increments its `version`.

### 2.5. Hierarchical Consistency and Cascade Semantics

The `Account` is the aggregate root. A `Subscription`, an `AddOnSubscription`, an `EquipmentLease`, a `ServiceVisit`, a `PromotionApplication`, and a `BillingStatement` each hang off exactly one account and are reached through it. When an operation on the account or one of its children changes the set of live line items, the server reconciles the account's derived fields automatically — the client never recomputes them.

Several operations mutate more than one entity. The governing rule is that **every cascade is a real mutation**: each child the cascade touches has its own `status` and timestamps updated, and the account's `monthly_recurring_cents`, `updated_at`, and `version` are recomputed and bumped as part of the same operation. The specific cascades — downgrade dropping incompatible add-ons, cancellation terminating the subscription and stranding equipment, promotional rollback zeroing a discount — are described in full in their §3 workflow narratives, but in every case the account's recurring charge is left consistent with the surviving line items before the operation returns.

### 2.6. Nested Resource Retrieval and Existence Ordering

Most write and read operations address a resource through a nested path such as an account, then a sub-resource beneath it. The server validates the identifiers in the path strictly left to right. The account named first in the path is checked before any sub-resource; if it does not exist the request fails with `ERR_ACCOUNT_NOT_FOUND` (HTTP 404) before the server even looks for the sub-resource. Only once the account is confirmed does the server look up the addressed `Subscription`, `AddOnSubscription`, `EquipmentLease`, `ServiceVisit`, `PromotionApplication`, or `BillingStatement`; a missing sub-resource under an existing account fails with `ERR_SUBRESOURCE_NOT_FOUND` (HTTP 404).

When an operation's request body references a catalog entity — a `ChannelPackage`, a `PremiumChannel`, an `EquipmentModel`, a `PromotionOffer`, a `RegionalSportsFeeRule`, or a `Technician` — that referenced entity must both exist and be active; a missing or inactive catalog reference is rejected with `ERR_CATALOG_ENTITY_NOT_FOUND` (HTTP 404).

### 2.7. Validation Order and Precedence

When several validations could fire on a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. The order is: first authentication (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then resource ownership (`ERR_NOT_RESOURCE_OWNER`); then existence checks in path order — the path account (`ERR_ACCOUNT_NOT_FOUND`), then any referenced catalog entity (`ERR_CATALOG_ENTITY_NOT_FOUND`), then the addressed sub-resource (`ERR_SUBRESOURCE_NOT_FOUND`); then the state check that the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`); then the rule that the account's lifecycle must be `ACTIVE` for a plan, add-on, equipment, or promotion mutation (`ERR_ACCOUNT_NOT_ACTIVE`); then the optimistic-concurrency version check (`ERR_STALE_ACCOUNT_VERSION`); and finally the operation-specific business and body-shape checks. In short: authentication precedes authorization precedes ownership precedes existence precedes state precedes account-active precedes concurrency precedes business rules. A check earlier in this order always masks one later in the order, so an unauthenticated request is never told it also pointed at a missing account.

### 2.8. Account Activity Gate

A family of mutations may only be performed while the account's `lifecycle_status` is `ACTIVE`. These are: a tier downgrade or upgrade, attaching a premium or add-on channel, assigning leased equipment, and applying a promotion. If the account is in any other lifecycle state — `PROSPECT`, `SUSPENDED`, or `CANCELLED` — these operations are rejected with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409). This gate is distinct from the per-resource state check: the state check (`ERR_INVALID_STATE`) governs whether the *targeted sub-resource* is in a legal source state, while this gate governs whether the *account itself* is operationally live.

### 2.9. Optimistic Concurrency Control

Two write operations carry an optimistic-concurrency guard keyed on the account's `version`: a tier change (downgrade or upgrade) and a promotion application (including a win-back re-application). Each such request must include `expected_account_version`, a non-optional integer field carrying the account `version` the client last observed.

The server compares `expected_account_version` to the account's current `version`. If they match, the operation proceeds and (as every account mutation does) advances the account's `version` by one. If they do not match — because some other writer has advanced the account's version since the client last read it — the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), and no change is made. This protects against a writer overwriting an account state it never observed: for example, a second tier change that legitimately superseded the same subscription would otherwise be silently clobbered.

Endpoints not in this pair do not take a version field and perform no concurrency check; they are serialized by the ordinary mutation discipline of §2.5.

### 2.10. Monetary Precision and Rounding

All money in the system is stored and returned as integer cents. Most aggregations sum amounts that are already integer cents and therefore require no rounding. Where a calculation multiplies cents by a fraction — a percentage-off discount, or a proration factor — the result is rounded to a whole number of cents using the **round half up** convention (a value exactly halfway between two cents rounds up to the larger cent). When a statement prorates several recurring line items, the rounding is applied to **each line item independently before the lines are summed**, never to a single pre-summed total; §3.7 specifies this per-line rounding in detail.

### 2.11. Tier Ranks, Channel Kinds, and Other Enumerations

Channel packages are ranked by an integer `rank` in the range 1 through 3, paired with a `tier_code` that is one of `BASIC`, `PLUS`, or `PREMIER`, where `BASIC` has rank 1, `PLUS` has rank 2, and `PREMIER` has rank 3; a higher rank is an upgrade and a lower rank is a downgrade. A `PremiumChannel` has a `kind` of either `PREMIUM` (movie/entertainment) or `ADD_ON` (sports or international tier). An `EquipmentModel` has a `kind` of either `BOX` (a set-top box with no recording) or `DVR` (a recording device). A `PromotionOffer` has a `discount_kind` of `PERCENT_OFF_PACKAGE`, `FLAT_OFF_TOTAL`, or `EQUIPMENT_WAIVER`. A `ServiceVisit` has a `visit_type` of `INSTALL` or `SERVICE`. A `BillingStatement` has a `proration_mode` of `FULL_CYCLE` or `PRORATED`. These exact strings are the only accepted values for their respective fields; an out-of-range enum or a negative amount where a non-negative one is required falls back to `ERR_VALIDATION` (HTTP 422) when no more specific error applies.

### 2.12. The Test-Driving Clock

Because service-visit scheduling depends on comparing appointment windows against "now," the system exposes an administrative clock that a `BillingAdmin` may set to a supplied instant via a `to_iso8601` field. Setting the clock fixes the server's notion of the current UTC time for the deterministic evaluation of visit-window validity, and the response reports the resulting `current_utc`. This capability is described as a capability only; its HTTP shape lives in §4.

## 3. Business Logic & Workflows

### 3.1. Catalog Configuration: Packages, Channels, Equipment, Promotions, Fees, and Technicians

Before any account can transact, a `BillingAdmin` seeds the catalog. A **channel package** is the tier a subscription carries; it is created with a `tier_code`, a display `name`, a `monthly_fee_cents` (the catalog monthly fee, which must be zero or greater), a `channel_count` (the number of linear channels included, zero or greater), and a `rank`. The `tier_code` must be unique across active packages. A package also carries an `active` flag indicating whether it may be newly subscribed; when omitted it defaults to true.

A **premium channel** — the umbrella term for both premium entertainment channels and add-on tiers — is created with a short unique `code` (for example `HBOX` or `SHOWX`), a display `name`, a `kind`, a `monthly_fee_cents` (zero or greater), and a `min_package_rank` in the range 1 through 3. The `min_package_rank` is the minimum package rank an account must hold to carry this channel. It too carries an `active` flag defaulting to true.

An **equipment model** is created with a unique `model_code` (for example `BOX-HD` or `DVR-4K`), a `kind`, a per-unit `monthly_lease_cents` (zero or greater), and a `replacement_cost_cents` (zero or greater) — the per-unit charge billed when a unit is never returned. Its `active` flag defaults to true.

A **promotion offer** is created with a unique `code` (for example `SAVE20` or `FREEDVR`), a `discount_kind`, a `percent_off` fraction between 0 and 1 inclusive (used only when the kind is `PERCENT_OFF_PACKAGE`, otherwise 0 and defaulting to 0), a `flat_off_cents` amount (cents removed from the monthly total when the kind is `FLAT_OFF_TOTAL`, otherwise 0, defaulting to 0, and zero or greater), a `promo_months` count (the number of billing cycles the promotion applies before rollback, at least 1), a `requires_min_rank` between 1 and 3 (the minimum package rank the account must hold to keep the promotion), and a `rollback_protected` boolean (defaulting to false) that, when true, permits a win-back re-application after rollback. Its `active` flag defaults to true.

A **regional sports fee rule** is created per state with a 2-letter, unique `state_code`, a `base_fee_cents` charged for accounts at `BASIC` or `PLUS` rank in that state, a `premier_surcharge_cents` added when the account's package is at the top rank, and an `active` flag defaulting to true. A **technician** is created with a `name`, a `home_state_code` (the state they service), and an `active` flag defaulting to true that indicates availability for dispatch. A technician's `id` is the same value that appears as `X-User-ID` when that person acts as a `FieldTechnician`.

All of these catalog creations are `BillingAdmin`-exclusive. Their listing endpoints are shared with the customer-service and (for packages, channels, and visits) subscriber audiences as enumerated in §4, and support filtering — for instance premium channels by `kind`, regional fee rules by `state_code`, technicians by `home_state_code` — alongside the standard `limit` and `offset`.

### 3.2. Account Onboarding and the Lifecycle Dimension

A `CustomerServiceAgent` opens the relationship by creating an account from a `customer_name`, a `service_state_code` (the 2-letter US state code of the service address, which drives the regional sports fee), and an optional `contract_term_months`. The contract term is the committed contract length; a value of 0 — the default — means month-to-month with no early-termination obligation. A freshly created account starts with `lifecycle_status` of `PROSPECT`, `promo_status` of `NONE`, a `tenure_months` of 0, a null `active_package_id`, and a null `cancellation_effective_cycle`. The account exposes two derived figures on read — `regional_sports_fee_cents` and `monthly_recurring_cents` — both of which are 0 until the first subscription is activated.

The account carries **two independent state dimensions**. The `lifecycle_status` dimension tracks the commercial life of the account through `PROSPECT`, `ACTIVE`, `SUSPENDED`, and the terminal `CANCELLED`. The `promo_status` dimension, covered in §3.6, tracks promotional state through `NONE`, `PROMO_ACTIVE`, and `ROLLED_BACK` independently of lifecycle — an `ACTIVE` account may sit at any of the three promotional states.

Service begins when a `CustomerServiceAgent` activates the account's **first subscription**, supplying the chosen `package_id`. This is permitted only while the account is in `PROSPECT` and the referenced channel package is active. The activation advances the lifecycle from `PROSPECT` to `ACTIVE`; it creates a `Subscription` in `ACTIVE` status whose `base_fee_cents` is snapshotted from the package's `monthly_fee_cents` at this moment; it sets the account's `active_package_id` to the chosen package; it recomputes the account's `regional_sports_fee_cents` and then its `monthly_recurring_cents`; and it increments the account's `version`. A subscription created this way records its `account_id`, its `package_id`, a null `previous_subscription_id` (it superseded nothing), and a `version` and `status` of its own. While a subscription request is being processed the row begins in `PENDING` before settling at `ACTIVE`.

A `CustomerServiceAgent` may **suspend** an `ACTIVE` account: the lifecycle moves `ACTIVE → SUSPENDED`, the account's recurring charge is recomputed (and, per §3.7's pricing rule, a suspended account's recurring charge is 0 because service is paused), and the account `version` increments. Any `ACTIVE` add-on subscriptions remain attached during suspension; only billing pauses. A suspended account may be **reactivated** by a `CustomerServiceAgent`, moving `SUSPENDED → ACTIVE`, recomputing the recurring charge, and incrementing the version.

### 3.3. Cancellation and Its Cascade

Cancellation is the account's terminal act and may be requested either by a `CustomerServiceAgent` or by the owning `Subscriber`. It is permitted from either `ACTIVE` or `SUSPENDED`; from any other state the attempt is rejected with `ERR_INVALID_STATE`. Cancellation moves the lifecycle to `CANCELLED` and runs a multi-part cascade in one operation:

- The account's `cancellation_effective_cycle` is set to a snapshot of the current `tenure_months`.
- The current `ACTIVE` (or `DOWNGRADED`) subscription transitions to `TERMINATED`.
- That subscription termination drops **every** `ACTIVE` add-on subscription to `DROPPED` with a `drop_reason` of `CANCELLED`; each such drop recomputes the account's recurring charge.
- Every equipment lease still in `ASSIGNED` status that has not been returned transitions to `UNRETURNED`, and its `unreturned_charge_cents` is set to the equipment model's `replacement_cost_cents` multiplied by the lease `quantity`; the lease's monthly contribution is removed from the recurring charge.
- An early-termination fee is computed: if the account's `contract_term_months` is greater than 0 and its `tenure_months` is less than `contract_term_months`, an early-termination fee is owed (per the calculation in §3.8) and recorded on the next billing statement issued for the account.
- The account's `monthly_recurring_cents` is recomputed to 0, since no live recurring line items remain.
- The account `version` increments.

### 3.4. Tier Changes: Downgrade and Upgrade

Once an account is `ACTIVE`, a `CustomerServiceAgent` may change the package tier by downgrading to a lower-rank package or upgrading to a higher-rank one. Both target a specific current subscription, supply the new `package_id`, and carry `expected_account_version` for the concurrency guard described below. The current subscription must itself be `ACTIVE`; the target package must be active; and the target package's rank must differ from the current rank. A target whose rank equals the current rank, or that is inactive, is rejected with `ERR_SAME_OR_INVALID_TIER` (HTTP 422).

Both directions follow the same supersession pattern. The current subscription transitions `ACTIVE → SUPERSEDED`, and a **new** subscription row is created carrying `previous_subscription_id` pointing back at the one it replaced; that new row is `ACTIVE` for an upgrade and `DOWNGRADED` for a downgrade. The account's `active_package_id` is repointed to the new subscription's package. Because the rank may have crossed the top-tier surcharge threshold, the account's `regional_sports_fee_cents` is recomputed, then its `monthly_recurring_cents`, and the account `version` increments.

A **downgrade** carries one extra cascade and one extra side effect beyond the upgrade. First, every `ACTIVE` add-on subscription whose premium channel has a `min_package_rank` greater than the new package's rank is dropped to `DROPPED` with a `drop_reason` of `INCOMPATIBLE_DOWNGRADE`, because the lower tier no longer supports it; each such incompatible drop recomputes the recurring charge. Second, if a promotion is active and the post-downgrade rank falls below that promotion's `requires_min_rank`, the promotion is rolled back as part of the downgrade — see §3.6. An **upgrade** drops no add-ons and never triggers promotional rollback (a higher rank only ever keeps a promotion eligible); its cascade is limited to the supersession, the active-package repointing, the regional-sports-fee and recurring-charge recomputation, and the version bump.

Both downgrade and upgrade carry the optimistic-concurrency guard of §2.9. A tier-change request whose `expected_account_version` does not equal the account's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) and makes no change; this is the serialization point that prevents a second tier change from clobbering an account whose subscription a prior tier change already superseded.

### 3.5. Add-On Channels and Equipment Leases

Within an `ACTIVE` account, a premium or add-on channel is attached by either a `CustomerServiceAgent` or the owning `Subscriber`, supplying the `premium_channel_id`. The attach is permitted only when the premium channel's `min_package_rank` is less than or equal to the account's current package rank; a channel whose minimum rank exceeds the current rank is rejected with `ERR_ADDON_RANK_TOO_HIGH` (HTTP 422). A successful attach creates an `AddOnSubscription` in `ACTIVE` status whose `fee_cents` is snapshotted from the premium channel's `monthly_fee_cents` at attach time, recomputes the account's recurring charge, and increments the account `version`. While `ACTIVE`, an add-on's `drop_reason` is null.

An add-on may be **dropped** by user request — again by a `CustomerServiceAgent` or the owning `Subscriber` — which transitions it to `DROPPED` with a `drop_reason` of `USER`, recomputes the recurring charge, and increments the account `version`. (The two non-user drop reasons, `INCOMPATIBLE_DOWNGRADE` and `CANCELLED`, are set only by the downgrade and cancellation cascades respectively, never by a direct drop request.)

Equipment is assigned to an `ACTIVE` account by either a `CustomerServiceAgent` or a `FieldTechnician`, supplying the `equipment_model_id` and a `quantity` of at least 1. The assignment creates an `EquipmentLease` in `ASSIGNED` status whose `monthly_lease_cents` is snapshotted as the model's per-unit `monthly_lease_cents` multiplied by the `quantity`; its `unreturned_charge_cents` begins at 0. The account's recurring charge is recomputed and the account `version` increments. A lease may be **returned** by a `CustomerServiceAgent` or a `FieldTechnician`, transitioning `ASSIGNED → RETURNED`; on return the lease's monthly contribution is removed from the recurring charge, `unreturned_charge_cents` stays 0, and the account `version` increments. A lease that is never returned before account cancellation instead transitions `ASSIGNED → UNRETURNED` through the cancellation cascade of §3.3, where its `unreturned_charge_cents` becomes the model's replacement cost times quantity.

### 3.6. Promotions, Rollback, and Win-Back

A promotion is applied to an `ACTIVE` account by a `CustomerServiceAgent`, supplying the `promotion_offer_id` and `expected_account_version`. The promotional dimension begins at `NONE`. A first application is permitted only when the account is `ACTIVE`, its `promo_status` is `NONE`, the referenced offer is active, and the account's current package rank is at least the offer's `requires_min_rank`. A current rank below the offer's minimum is rejected with `ERR_PROMO_RANK_NOT_MET` (HTTP 422). Applying while a promotion is already `PROMO_ACTIVE` is rejected with `ERR_PROMO_ALREADY_ACTIVE` (HTTP 409), because at most one promotion application may be `ACTIVE` at a time.

A successful first application creates a `PromotionApplication` in `ACTIVE` status. It records `applied_at_tenure` as a snapshot of the account's `tenure_months` at application, and `rollback_at_tenure` as that snapshot plus the offer's `promo_months` — the tenure at which the promotion will roll back. Its `discount_cents_snapshot` is the discount the application contributes while active (per the discount calculation in §3.7), and its `is_winback` flag is false for a first application. The account's `promo_status` moves `NONE → PROMO_ACTIVE`, the recurring charge is recomputed to include the discount, and the account `version` increments.

A promotion rolls back in either of two ways, both moving `promo_status` to `ROLLED_BACK` and the application to `ROLLED_BACK`. The first is **time-based**: when a `BillingAdmin` advances the billing cycle (§3.9) and the new tenure reaches or exceeds the active application's `rollback_at_tenure`, the application is rolled back, its `discount_cents_snapshot` contribution drops to 0, the recurring charge is recomputed back up to catalog price, and the account `version` increments. The second is **eligibility-based**: when a downgrade (§3.4) drops the account's rank below the active promotion offer's `requires_min_rank`, that same downgrade rolls the promotion back, recomputes the recurring charge, and increments the version. Both paths leave the account at catalog pricing with the discount removed.

After a rollback, a **win-back** re-application is possible but only for a promotion offer whose `rollback_protected` flag is true. A `CustomerServiceAgent` re-applies by calling the same apply operation with `expected_account_version`; it is permitted only when the account is `ACTIVE`, its `promo_status` is `ROLLED_BACK`, the offer's `rollback_protected` is true, and the current rank is at least the offer's `requires_min_rank`. Re-applying after rollback with a non-protected offer is rejected with `ERR_PROMO_NOT_WINBACK_ELIGIBLE` (HTTP 422); a current rank below the offer's minimum is again rejected with `ERR_PROMO_RANK_NOT_MET`. A successful win-back creates a new `PromotionApplication` with `is_winback` set to true, moves `promo_status` from `ROLLED_BACK` back to `PROMO_ACTIVE`, recomputes the recurring charge, and increments the version. Both the first apply and the win-back re-apply carry the §2.9 concurrency guard: a stale `expected_account_version` is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412), since a win-back legitimately supersedes the rolled-back application and a stale apply would overwrite a promotional change the client never observed.

### 3.7. The Recurring Charge and Discount Engine

The account's `monthly_recurring_cents` is the single derived figure that every commercial action recomputes — on subscription activation, downgrade, and upgrade; on add-on attach and drop; on equipment assign and return; on promotion apply, rollback, and win-back; and on suspend, reactivate, and cancel. Its evaluation order is pinned to resolve the circular-looking dependency between the gross total and the promotional discount, and proceeds in these steps:

1. The **package base** is the `base_fee_cents` of the account's single current subscription (the one in `ACTIVE` or `DOWNGRADED` status).
2. The **add-on sum** is the total of `fee_cents` across all add-on subscriptions whose status is `ACTIVE`.
3. The **equipment sum** is the total of `monthly_lease_cents` across all equipment leases whose status is `ASSIGNED`.
4. The **regional sports fee** is the account's already-computed `regional_sports_fee_cents`.
5. The **gross** is the sum of the package base, the add-on sum, the equipment sum, and the regional sports fee.
6. The **discount** is computed from the gross and the package base by the discount rule below — it is computed only after the gross is known, because it can depend on both.
7. The recurring charge is the gross minus the discount, but never less than 0 (a negative result is clamped to 0).

Two lifecycle states short-circuit this: if the account's `lifecycle_status` is `SUSPENDED`, the recurring charge is 0 because service is paused; if it is `CANCELLED`, the recurring charge is likewise 0. All inputs are already integer cents, so steps 1 through 5 require no rounding.

The **discount** itself is driven by the single `ACTIVE` promotion application's offer. If no promotion application is `ACTIVE`, the discount is 0. Otherwise it depends on the offer's `discount_kind`:

- For `PERCENT_OFF_PACKAGE`, the discount is the package base multiplied by the offer's `percent_off` fraction, rounded half up to whole cents. This applies to the package fee **only** — the add-on, equipment, and regional-sports-fee portions are untouched.
- For `FLAT_OFF_TOTAL`, the discount is the offer's `flat_off_cents`, but capped at the gross so that the net can never go below 0 — that is, the smaller of `flat_off_cents` and the gross.
- For `EQUIPMENT_WAIVER`, the discount equals the full sum of `monthly_lease_cents` across all `ASSIGNED` equipment leases, waiving the entire equipment portion. Because this discount tracks the equipment sum, it changes whenever equipment changes even if the promotion itself does not.

### 3.8. Regional Sports Fee, Visit Fees, and Early-Termination Fees

**Regional sports fee.** The account's `regional_sports_fee_cents` is recomputed on first subscription activation and on every tier change, because a rank change can cross the top-tier surcharge threshold. The system finds the single active `RegionalSportsFeeRule` whose `state_code` matches the account's `service_state_code`; if no active rule matches, the regional sports fee is 0. Otherwise the fee is the rule's `base_fee_cents` plus, when the current package rank is at least the top rank of 3 (`PREMIER`), the rule's `premier_surcharge_cents`; below rank 3 no surcharge is added.

**Service-visit fee.** A visit's `truck_roll_fee_cents` is computed when the visit reaches a terminal outcome. On completion, an `INSTALL` visit is waived and charges 0, while a `SERVICE` visit charges the standard truck-roll fee of 99 dollars (9,900 cents). A no-show, regardless of whether the visit was an `INSTALL` or a `SERVICE`, always charges the full standard truck-roll fee of 9,900 cents. A visit cancelled from the scheduled state charges 0 and has no billing impact. Whatever fee is computed is recorded for billing on the account's next statement as a one-time visit charge.

**Early-termination fee.** When an account cancels with a contract still in force, an early-termination fee is owed and recorded on the cancellation-cycle statement. The fee is 0 in two cases: when `contract_term_months` is 0 (month-to-month, no contract), or when `tenure_months` is greater than or equal to `contract_term_months` (the contract is already satisfied). Otherwise let the remaining months be `contract_term_months` minus `tenure_months`, and apply this tenure-breakpoint schedule:

- If the remaining months are at least 12, the fee is the maximum of 240 dollars (24,000 cents).
- If the remaining months are at least 6 but fewer than 12, the fee is the mid amount of 150 dollars (15,000 cents).
- If the remaining months are at least 1 but fewer than 6, the fee is a floor of 20 dollars (2,000 cents) plus 15 dollars (1,500 cents) for each remaining month — that is, 2,000 plus the remaining-month count multiplied by 1,500 cents.

The breakpoints are inclusive at their lower edge: exactly 12 remaining months lands in the at-least-12 tier (24,000 cents), exactly 6 remaining months lands in the mid tier (15,000 cents), and exactly 5 remaining months lands in the low per-month tier.

### 3.9. Service Visits in the Field

A service visit is scheduled by a `CustomerServiceAgent` or the owning `Subscriber`, supplying the `visit_type`, an appointment `window_start` and `window_end`, and the `technician_id` of the assigned technician. A new visit is created in `SCHEDULED` status with a `truck_roll_fee_cents` of 0 and a null `outcome_note`. Three scheduling guards run on creation, all evaluated against the test-driving clock of §2.12:

- The window must be well-formed and in the future: `window_start` must be strictly earlier than `window_end`, and `window_start` must be later than the current clock time. A window where the start is not before the end, or whose start is in the past, is rejected with `ERR_INVALID_VISIT_WINDOW` (HTTP 422).
- The window must not collide with another non-terminal visit (one whose status is `SCHEDULED` or `DISPATCHED`) for the **same technician**. Technician intervals are treated as half-open `[start, end)`, so exact adjacency is allowed — an existing visit ending precisely when the new one starts, or a new visit ending precisely when an existing one starts, does not conflict — but any strictly positive overlap is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED` (HTTP 409).
- The window must not collide with another non-terminal visit (again `SCHEDULED` or `DISPATCHED`) for the **same account**, and must additionally keep at least a 60-minute buffer from any other visit on that account. Account intervals are treated as closed plus a 60-minute buffer: if the gap between the new window and another account visit is less than 60 minutes, it is rejected with `ERR_ACCOUNT_VISIT_CONFLICT` (HTTP 409).

Once scheduled, the assigned `FieldTechnician` — and only the technician whose `id` matches the visit's `technician_id` — **dispatches** to the visit, moving `SCHEDULED → DISPATCHED`. From `DISPATCHED` the technician takes one of two terminal branches. A **completion** requires an `outcome_note` to be supplied, moves `DISPATCHED → COMPLETED`, and computes the truck-roll fee per §3.8 (waived for `INSTALL`, charged for `SERVICE`); on an install completion any `ASSIGNED` equipment stays `ASSIGNED` and no fee is added. A **no-show** moves `DISPATCHED → NO_SHOW` and always charges the full service truck-roll fee regardless of `visit_type`. Separately, a `SCHEDULED` visit may be **cancelled** by a `CustomerServiceAgent` or the owning `Subscriber`, moving `SCHEDULED → CANCELLED` with a fee of 0 and no billing impact. Any transition attempted from a state the machine does not permit — completing a visit that was never dispatched, dispatching a cancelled visit — is rejected with `ERR_INVALID_STATE` (HTTP 409).

### 3.10. Billing Cycle Advancement and Statement Issuance

A `BillingAdmin` advances an account one **billing cycle** at a time, which increments the account's `tenure_months` by 1. If, after the advance, the new tenure reaches or exceeds the active promotion application's `rollback_at_tenure`, the time-based promotional rollback of §3.6 fires within the same advance: the application moves to `ROLLED_BACK`, `promo_status` moves to `ROLLED_BACK`, the recurring charge is recomputed to catalog price, and the account `version` increments.

A `BillingAdmin` issues a **billing statement** for a given cycle, supplying the `cycle_index` (the tenure month being billed, zero or greater), the `proration_mode`, and — for prorated statements — the `days_in_cycle` (calendar days in the cycle, defaulting to 30 and at least 28) and `active_days` (days the service was active in the cycle, defaulting to 30 and zero or greater). A statement is created in `DRAFT` and issued to `ISSUED`; a statement that is later reversed moves to the terminal `VOID` status. A `PRORATED` statement whose `active_days` falls outside the range 0 through `days_in_cycle` is rejected with `ERR_INVALID_PRORATION` (HTTP 422). Issuing a second statement for a `cycle_index` that already has an `ISSUED` statement on the account is rejected with `ERR_DUPLICATE_STATEMENT_CYCLE` (HTTP 409).

A statement breaks the bill into named line items: `package_charge_cents`, `addon_charge_cents`, `equipment_charge_cents`, `regional_sports_fee_cents`, `visit_charge_cents`, `promo_discount_cents`, `etf_charge_cents`, and a net `total_cents`. The `proration_mode` pins which of two variants computes these — this is the dual-variant heart of the billing engine.

The shared inputs for the cycle are: the package amount (the `base_fee_cents` of the account's single current subscription, meaning the one in `ACTIVE` or `DOWNGRADED` status as defined in §3.7 — and consequently 0 when no such subscription exists, for instance on the cancellation-cycle statement, where the §3.3 cascade has already transitioned the subscription to `TERMINATED` so that no current subscription remains and `package_charge_cents` is 0); the add-on amount (the sum of `fee_cents` across `ACTIVE` add-ons); the equipment amount (the sum of `monthly_lease_cents` across `ASSIGNED` leases, **plus** the sum of `unreturned_charge_cents` across `UNRETURNED` leases as a one-time charge); the regional sports fee (`regional_sports_fee_cents`); the visit charges (the sum of `truck_roll_fee_cents` across visits that completed or no-showed in this cycle, a one-time charge); the promotional discount computed by §3.7's discount rule over the recurring lines; and any early-termination fee owed if the account cancelled in this cycle (a one-time charge).

In the **`FULL_CYCLE`** variant, each recurring line is billed at its full catalog value and `active_days`/`days_in_cycle` are ignored: `package_charge_cents` is the package amount, `addon_charge_cents` is the add-on amount, `equipment_charge_cents` is the equipment amount (including the one-time unreturned charge), `regional_sports_fee_cents` is the regional sports fee, and `promo_discount_cents` is the discount computed over the package plus add-on plus recurring-equipment plus regional-sports-fee base.

In the **`PRORATED`** variant, let the proration factor be `active_days` divided by `days_in_cycle`. **Each recurring line item is scaled by that factor and rounded half up to whole cents independently, before any summing** — never summed first and prorated after. Thus `package_charge_cents` is the package amount times the factor rounded half up; `addon_charge_cents` is the add-on amount times the factor rounded half up; the recurring portion of equipment is the recurring equipment amount times the factor rounded half up; `regional_sports_fee_cents` is the regional sports fee times the factor rounded half up; and `promo_discount_cents` is the discount computed over the **prorated** recurring base, rounded half up. The one-time charges — unreturned-equipment replacement cost, visit truck-roll fees, and any early-termination fee — are added at full value and are **never** prorated. For the same inputs this per-line prorated rounding deliberately yields a different total than the full-cycle variant.

In both variants the one-time pieces land in their fields as: `visit_charge_cents` is the cycle's visit fees, and `etf_charge_cents` is any early-termination fee owed. The net `total_cents` is the sum of the package charge, add-on charge, equipment charge, regional-sports-fee charge, visit charge, and early-termination charge, minus the promotional discount, floored at 0.

### 3.11. Reverse-Lookup and Reporting Reads

Beyond the account-scoped collections, the system exposes flat collection reads for reporting and reverse reachability, available to a `BillingAdmin` and `CustomerServiceAgent` (and, for single-resource gets of subscriptions, add-ons, service visits, and promotion applications, to a `Subscriber`; equipment-lease and service-visit reads are also available to a `FieldTechnician`). Subscriptions may be listed filtered by `account_id`, `package_id`, `previous_subscription_id`, and `status`; add-ons by `account_id`, `premium_channel_id`, and `status`; equipment leases by `account_id`, `equipment_model_id`, and `status`; service visits by `account_id`, `technician_id`, and `status`; promotion applications by `account_id`, `promotion_offer_id`, and `status`; and accounts by `lifecycle_status` and `active_package_id`. Every account-scoped list — subscriptions, add-ons, equipment leases, service visits, promotions, and billing statements under an account — also supports a `status` (or, for statements, `cycle_index` and `status`) filter alongside the standard `limit` and `offset`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new distinct resource to a collection return a `201 Created`. Operations that modify an existing resource — including state transitions and the test-driving clock — return a `200 OK`. The complete request and response shapes are reconstructed from the §3 narratives; the table below names only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/channel-packages` | Create a channel package tier | BillingAdmin |
| GET | `/channel-packages` | List channel packages | BillingAdmin, CustomerServiceAgent, Subscriber |
| GET | `/channel-packages/{id}` | Get a channel package | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/premium-channels` | Create a premium/add-on channel | BillingAdmin |
| GET | `/premium-channels` | List premium/add-on channels | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/equipment-models` | Create an equipment model | BillingAdmin |
| GET | `/equipment-models` | List equipment models | BillingAdmin, CustomerServiceAgent |
| POST | `/promotion-offers` | Create a promotion offer | BillingAdmin |
| GET | `/promotion-offers` | List promotion offers | BillingAdmin, CustomerServiceAgent |
| POST | `/regional-sports-fee-rules` | Create a regional sports fee rule for a state | BillingAdmin |
| GET | `/regional-sports-fee-rules` | List regional sports fee rules | BillingAdmin, CustomerServiceAgent |
| POST | `/technicians` | Create a field technician | BillingAdmin |
| GET | `/technicians` | List technicians | BillingAdmin, CustomerServiceAgent |
| GET | `/subscriptions` | List subscriptions by account/package/previous/status | BillingAdmin, CustomerServiceAgent |
| GET | `/subscriptions/{id}` | Get a single subscription | BillingAdmin, CustomerServiceAgent, Subscriber |
| GET | `/add-ons` | List add-on subscriptions by premium channel | BillingAdmin, CustomerServiceAgent |
| GET | `/add-ons/{id}` | Get a single add-on subscription | BillingAdmin, CustomerServiceAgent, Subscriber |
| GET | `/equipment-leases` | List equipment leases by equipment model | BillingAdmin, CustomerServiceAgent |
| GET | `/equipment-leases/{id}` | Get a single equipment lease | BillingAdmin, CustomerServiceAgent, FieldTechnician |
| GET | `/service-visits` | List service visits by technician | BillingAdmin, CustomerServiceAgent, FieldTechnician |
| GET | `/service-visits/{id}` | Get a single service visit | BillingAdmin, CustomerServiceAgent, Subscriber, FieldTechnician |
| GET | `/promotion-applications` | List promotion applications by offer | BillingAdmin, CustomerServiceAgent |
| GET | `/promotion-applications/{id}` | Get a single promotion application | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/accounts` | Create a prospect account | CustomerServiceAgent |
| GET | `/accounts` | List accounts | BillingAdmin, CustomerServiceAgent |
| GET | `/accounts/{id}` | Get account with computed recurring and regional-sports figures | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/suspend` | Suspend an active account | CustomerServiceAgent |
| POST | `/accounts/{id}/reactivate` | Reactivate a suspended account | CustomerServiceAgent |
| POST | `/accounts/{id}/cancel` | Cancel an account (cascades termination, drops, unreturned, ETF) | CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/advance-cycle` | Advance one billing cycle; fire promo rollback when due | BillingAdmin |
| POST | `/accounts/{id}/subscriptions` | Activate the account's first subscription | CustomerServiceAgent |
| GET | `/accounts/{id}/subscriptions` | List subscriptions for an account | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/subscriptions/{sid}/downgrade` | Downgrade to a lower-rank package | CustomerServiceAgent |
| POST | `/accounts/{id}/subscriptions/{sid}/upgrade` | Upgrade to a higher-rank package | CustomerServiceAgent |
| POST | `/accounts/{id}/add-ons` | Attach a premium/add-on channel | CustomerServiceAgent, Subscriber |
| GET | `/accounts/{id}/add-ons` | List add-on subscriptions for an account | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/add-ons/{aid}/drop` | Drop an active add-on (user-initiated) | CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/equipment-leases` | Assign leased equipment | CustomerServiceAgent, FieldTechnician |
| GET | `/accounts/{id}/equipment-leases` | List equipment leases for an account | BillingAdmin, CustomerServiceAgent, FieldTechnician |
| POST | `/accounts/{id}/equipment-leases/{lid}/return` | Return leased equipment | CustomerServiceAgent, FieldTechnician |
| POST | `/accounts/{id}/service-visits` | Schedule an install/service visit | CustomerServiceAgent, Subscriber |
| GET | `/accounts/{id}/service-visits` | List service visits for an account | BillingAdmin, CustomerServiceAgent, Subscriber, FieldTechnician |
| POST | `/accounts/{id}/service-visits/{vid}/dispatch` | Technician dispatches to the visit | FieldTechnician |
| POST | `/accounts/{id}/service-visits/{vid}/complete` | Technician completes the visit | FieldTechnician |
| POST | `/accounts/{id}/service-visits/{vid}/no-show` | Technician marks customer no-show | FieldTechnician |
| POST | `/accounts/{id}/service-visits/{vid}/cancel` | Cancel a scheduled visit | CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/promotions` | Apply (or win-back) a promotion offer | CustomerServiceAgent |
| GET | `/accounts/{id}/promotions` | List promotion applications for an account | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/accounts/{id}/billing-statements` | Issue a billing statement for a cycle | BillingAdmin |
| GET | `/accounts/{id}/billing-statements` | List billing statements for an account | BillingAdmin, CustomerServiceAgent, Subscriber |
| GET | `/accounts/{id}/billing-statements/{bid}` | Get a single billing statement | BillingAdmin, CustomerServiceAgent, Subscriber |
| POST | `/_clock/set_current_utc` | Set server clock for deterministic visit-window validation | BillingAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_CATALOG_ENTITY_NOT_FOUND` | 404 |
| `ERR_SUBRESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_INVALID_VISIT_WINDOW` | 422 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 |
| `ERR_ACCOUNT_VISIT_CONFLICT` | 409 |
| `ERR_ADDON_RANK_TOO_HIGH` | 422 |
| `ERR_PROMO_RANK_NOT_MET` | 422 |
| `ERR_PROMO_NOT_WINBACK_ELIGIBLE` | 422 |
| `ERR_PROMO_ALREADY_ACTIVE` | 409 |
| `ERR_SAME_OR_INVALID_TIER` | 422 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_PRORATION` | 422 |
| `ERR_DUPLICATE_STATEMENT_CYCLE` | 409 |
| `ERR_VALIDATION` | 422 |

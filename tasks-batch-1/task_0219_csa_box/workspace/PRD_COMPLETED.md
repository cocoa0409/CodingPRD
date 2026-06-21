# Csa Box API — Product Requirements Document

## 1. Introduction

Community Supported Agriculture (CSA) connects a farm directly with the households that eat its produce: members subscribe to a seasonal share, receive a curated box of produce every delivery week, and absorb both the bounty and the risk of the growing season alongside the grower. This API is the operational backbone for running such a program at scale. It models the full arc of a season — from a farm manager configuring share sizes, pickup sites, and add-on products, through members subscribing under a sliding-scale pricing model, to the week-by-week packing and delivery of boxes, vacation holds, working-share labor credits, and the financial ledger that ties every charge, credit, and payment back to a single running balance.

The system must reconcile several concerns that pull against one another. Capacity is finite and counted in two dimensions at once — a season-wide share cap and a per-site weekly box ceiling — so confirmations and waitlist promotions race for the same scarce slots and must be serialized against stale views of the world. Pricing is variable by design: a member's self-declared pay tier scales the share price up or down so that wealthier households subsidize others. Fulfillment is temporal: boxes belong to specific delivery weeks, holds must be placed before a box ships, and waitlist offers expire. A subscription carries two independent lifecycles — one for billing, one for fulfillment — that evolve on the same record without blocking each other. The sections that follow specify these rules precisely, so that an implementation can be built to behave identically to the reference contract that the automated test suite encodes.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that apply across every endpoint. Where a rule is stated here, it governs unless a more specific business rule in Section 3 narrows it.

### 2.1. User and Role-Based Access Control

Every request to a protected endpoint must carry two HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the operational capacity under which the request is made. The system recognizes five role values, spelled exactly: `FarmManager`, `DeliveryCoordinator`, `Member`, `PlatformAdmin`, and `Anonymous`. A request to a protected endpoint that is missing either header, or that carries a malformed one, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two endpoints are deliberately unauthenticated public surfaces and require no headers: registering a new member and joining a season's waitlist. These are the operations available to the `Anonymous` role, and the authentication check is skipped for them; every other endpoint demands valid headers.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`; ownership checks on any resource that references a `Member` compare the resource's owning member — reached directly through a `member_id` field or indirectly by following a `subscription_id` to its owning `Subscription` and then that subscription's `member_id` — to `X-User-ID`. When a member acts on a `Subscription`, `VacationHold`, `WaitlistEntry`, or `WeeklyBox` that resolves to a different member, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `FarmManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `DeliveryCoordinator`, when it is `PlatformAdmin`, and when it is `Anonymous`: in each of those cases `X-User-ID` is an opaque operator identifier (absent altogether for `Anonymous`'s public endpoints) that the server does not match against any entity's `id`.

Role responsibilities divide as follows. A `FarmManager` configures the season and its catalog (seasons, share types, add-ons), confirms subscriptions, and runs weekly fulfillment such as packing, delivering, and resolving working-share shifts. A `DeliveryCoordinator` owns pickup sites and delivery zones and runs waitlist promotion. A `Member` is a subscribing household that owns its own subscriptions, holds, add-on attachments, and waitlist entries. A `PlatformAdmin` is an operational role that advances the simulated clock and may read any resource for support. The `Anonymous` role exists only for member registration and waitlist signup.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with no upper bound beyond the size of the collection. A request with `limit` below 1 or above 100, or with a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and System-Managed Fields

Nearly every persisted resource carries a standard set of system-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value of `1` on creation and increments by one with every mutation; it is the basis for the optimistic concurrency checks described below.

One entity is the exception. A `LedgerEntry` is an append-only record: once posted it is never modified. Accordingly, a `LedgerEntry` carries only `id` and `created_at` — it has no `updated_at` and no `version`. Every other entity in the system — `Season`, `PickupSite`, `ShareType`, `AddOn`, `Member`, `Subscription`, `SubscriptionAddOn`, `WeeklyBox`, `VacationHold`, `WaitlistEntry`, and `WorkShareShift` — carries the full `id`/`created_at`/`updated_at`/`version` set.

A subtlety worth stating plainly: several fields are *derived* — recomputed by the server as a side effect of other operations rather than written directly by a client. When the server recomputes a derived field on a resource (for example a subscription's `outstanding_balance_cents`, or a season's `confirmed_share_count`), that recomputation is itself a mutation of the owning resource: it refreshes the resource's `updated_at` and increments its `version`.

### 2.5. Monetary Precision and Rounding

All monetary quantities in this system are stored and exchanged as integer cents — `base_price_cents`, `weekly_price_cents`, `delivery_surcharge_cents`, `season_price_cents`, `outstanding_balance_cents`, `wallet_credit_cents`, `credit_earned_cents`, and the signed `amount_cents` on a ledger entry are all integers, never decimal currency. Wherever a calculation introduces a fractional cent — specifically the sliding-scale multiply and the working-share credit multiply — the result is rounded to a whole number of cents using the round-half-up convention (a value exactly halfway between two integers rounds up to the larger). Calculations that combine already-integer inputs (summing ledger lines, distributing a refund across weeks) introduce no fractional cents and require no rounding step beyond the integer arithmetic itself.

### 2.6. Nested Resource Retrieval and Referential Integrity

Many endpoints address a resource nested beneath a parent — for example a subscription's weekly boxes, ledger entries, vacation holds, or work-share shifts. For any such path, the system validates the identifiers left-to-right: the parent in the path is resolved first, and if it does not exist the request fails immediately with `ERR_NOT_FOUND` (HTTP 404) for that parent, before any nested or referenced identifier is examined. The same `ERR_NOT_FOUND` governs every foreign-key reference carried in a request body: if a `season_id`, `member_id`, `share_type_id`, `current_site_id`, `requested_site_id`, `site_id`, `subscription_id`, `add_on_id`, `held_box_id`, or `swap_target_box_id` names a resource that does not exist, the request is rejected with `ERR_NOT_FOUND`.

Beyond mere existence, the system enforces *season cohesion* on create operations. When a subscription is created, its referenced `share_type_id` and `current_site_id` must each belong to the same `Season` named by `season_id`; likewise a waitlist entry's `share_type_id` and `requested_site_id` must belong to its `season_id`, and an add-on attachment's `add_on_id` must share the season of the subscription it attaches to. A reference that points into a different season is rejected with `ERR_SEASON_MISMATCH` (HTTP 409).

### 2.7. State Validity and the Order of Checks

Every operation that drives a state machine is guarded by a validity check: the target resource must currently be in a state from which the requested transition is defined. An attempt to transition a resource from a state that does not permit it is rejected with `ERR_INVALID_STATE` (HTTP 409). This applies uniformly to opening and closing a season, confirming and cancelling a subscription, packing and delivering boxes, placing and releasing holds, accepting and declining waitlist offers, and completing or marking-no-show a work-share shift.

When several checks could apply to a single request, they are evaluated in a fixed priority order so that the resulting error is deterministic. Authentication comes first: a missing or malformed header surfaces `ERR_UNAUTHENTICATED` before anything else. Role authorization is next, yielding `ERR_FORBIDDEN_ROLE` when the role is not permitted. Resource ownership follows for member-actor endpoints, yielding `ERR_NOT_RESOURCE_OWNER`. Existence of all path and referenced resources is checked next, yielding `ERR_NOT_FOUND`. Season cohesion (`ERR_SEASON_MISMATCH`) is then evaluated, followed by state validity (`ERR_INVALID_STATE`). Domain-specific temporal and constraint checks — described in their respective workflows below and enumerated by priority where several share an endpoint — are evaluated after these foundational checks. Request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422) and the member-email uniqueness rule (`ERR_DUPLICATE_EMAIL`, HTTP 409) sit lower still, and the optimistic-concurrency stale-version check sits at the bottom of the order. The intent is that foundational failures (you are not who you claim, the thing does not exist, the thing is in the wrong state) are reported before fine-grained business and concurrency failures.

### 2.8. Cascading Side Effects and Hierarchical Consistency

A single business action frequently mutates more than one resource. Confirming a subscription, for instance, both posts ledger charges and bumps season- and site-level counters. Cancelling a subscription unwinds an entire chain of dependents in a defined sequence. Whenever this document describes such a cascade, every hop in the cascade occurs as part of the same operation, and each mutated resource independently has its `updated_at` refreshed and its `version` incremented. Counter fields that the system maintains — a season's `confirmed_share_count`, a pickup site's `active_subscription_count`, and an add-on's `committed_count` — are never set directly by a client; they are recomputed by the server as side effects of the operations that change them, and each recompute is a mutation of its owning resource. The specific cascades are detailed in Section 3 alongside the workflows that trigger them.

### 2.9. Optimistic Concurrency on Capacity-Sensitive Writes

Two operations contend for scarce season capacity, and both are therefore guarded by optimistic concurrency control keyed on the `Season` record. Each guarded write requires the caller to submit `expected_season_version` — a non-optional field carrying the `version` of the `Season` as the client last observed it — and the server compares that value against the season's current `version` before proceeding.

The first guarded write is confirming a subscription. The request must carry `expected_season_version` matching the target season's current `version`. Each confirm increments the season's `version` (because it changes `confirmed_share_count`), so if another writer has advanced the season's version since this client last read it, the confirm is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client that believed the last slot was free — under a now-stale season view — from silently over-filling `total_share_capacity`.

The second guarded write is promoting the waitlist. Promoting the next waitlist entry must likewise carry `expected_season_version` matching the season's current `version`. Because a confirm or a prior promotion bumps the season's `version`, a coordinator acting on a stale season view (where a slot still appeared free) is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than offering a slot that no longer exists. No other endpoint in the system takes a version field; only these two confirm-and-promote writes carry `expected_season_version`.

## 3. Business Logic & Workflows

### 3.1. Building a Season and Its Catalog

A season is the top-level container for an offering cycle, and only a `FarmManager` may create one. Creating a season supplies its `name` (a label such as "Summer 2026"), a `week_count` giving the number of delivery weeks, which must be a whole number from 1 through 52 inclusive, a `first_delivery_date` (the UTC-midnight ISO date of delivery week 1, with each subsequent week falling exactly seven days after the previous), a `signup_close_date` (the ISO datetime after which new subscriptions can no longer be confirmed and are instead waitlisted), and a `total_share_capacity` giving the season-wide ceiling on confirmed subscriptions across all sites combined, which must be a whole number of zero or greater. A new season begins in the `DRAFT` state, and its `confirmed_share_count` starts at 0.

Before members can subscribe, the season's catalog must be populated. A `FarmManager` defines one or more **share types**, each scoped to a season via `season_id` and carrying a `size` of `SMALL`, `MEDIUM`, or `LARGE`, a `base_price_cents` giving the full-season list price at the baseline pay tier (which must be a positive whole number), and an `items_per_box` giving how many produce line items are composed into each weekly box for that share (at least 1). A `FarmManager` also defines **add-ons** — supplementary products attached on top of a share — each scoped by `season_id`, with a `kind` of either `EGGS` or `FLOWERS`, a `weekly_price_cents` per delivery week (a positive whole number), and a `weekly_supply_cap` giving the maximum number of attachments the farm can fulfill for that add-on across the whole season (zero or greater). An add-on's `committed_count`, which tracks how many attachments are currently live, starts at 0.

Pickup logistics are owned by a `DeliveryCoordinator`, who creates **pickup sites** and delivery zones. A pickup site is scoped to a season by `season_id` and carries a `name`, a `kind` that is either `PICKUP` for a physical pickup location or `HOME_DELIVERY` for a routed delivery zone, a `weekly_capacity` giving the maximum number of boxes that may be fulfilled at the site in any single delivery week (zero or greater), and, optionally, a `delivery_surcharge_cents` (a per-week surcharge, defaulting to 0, that applies only when the site's `kind` is `HOME_DELIVERY` and is ignored for `PICKUP`). A site's `active_subscription_count`, used for capacity checks, starts at 0.

Opening the season for signups moves it from `DRAFT` to `OPEN`, an action reserved to a `FarmManager`. This is permitted only once the season has at least one share type and at least one pickup site defined; an attempt to open a season lacking either is rejected with `ERR_INVALID_STATE`. Once open, subscriptions may be created and confirmed against it. Later, a `FarmManager` may close the season, moving it from `OPEN` to `CLOSED` — permitted only from the `OPEN` state, again surfacing `ERR_INVALID_STATE` otherwise. After closing, no new confirmed subscriptions are accepted and further signups are routed to the waitlist; `CLOSED` is terminal.

### 3.2. Members and the Sliding Scale

Anyone may register as a **member** without authentication, supplying an `email` and a `full_name`, and optionally a `sliding_scale_tier`. The email must be unique on a case-insensitive basis; registering an email that already exists (ignoring letter case) is rejected with `ERR_DUPLICATE_EMAIL`. The sliding-scale tier is the member's self-declared pay tier and is one of `SOLIDARITY`, `BASELINE`, or `SUSTAINER`, defaulting to `BASELINE` when omitted. A newly registered member's `wallet_credit_cents` — the running credit balance, in cents, accrued from completed working-share shifts and refunded held weeks — starts at 0.

The pay tier governs how much a member pays for the same share. The sliding scale is a price multiplier on the share's base price: the `SOLIDARITY` tier pays a multiplier of 0.80, the `BASELINE` tier pays 1.00, and the `SUSTAINER` tier pays 1.25. The intent is solidarity pricing — sustainers subsidize the solidarity tier — and the multiplier is applied at confirmation time, as described in the subscription lifecycle below.

### 3.3. Subscribing: From Pending Payment Through Confirmation

A `Member` creates a **subscription** against an `OPEN` season by supplying the `season_id`, the `member_id` of the owning member, the chosen `share_type_id`, the `current_site_id` naming the assigned site or delivery zone, and optionally `working_share_opt_in`, a boolean (defaulting to false) declaring whether the household joins the working-share labor program. The chosen share type and site must both belong to the named season, or the create is rejected with `ERR_SEASON_MISMATCH`. A new subscription begins with its billing axis in `PENDING_PAYMENT` and its fulfillment axis in `NOT_STARTED`; its `season_price_cents` and `outstanding_balance_cents` both start at 0. The two axes are independent: `billing_status` tracks the money side and `fulfillment_status` tracks the produce side, and they evolve separately on the same record.

Confirming a subscription is a `FarmManager` action that moves the billing axis from `PENDING_PAYMENT` to `CONFIRMED`. Confirmation is gated by a battery of checks, evaluated after the foundational authentication, authorization, ownership, existence, and state checks. The relevant business gates, in their priority order, are: the season-close temporal window (`ERR_SIGNUP_CLOSED`, HTTP 409) — the current clock must be at or before the season's `signup_close_date`; then the site weekly-capacity gate (`ERR_SITE_CAPACITY_FULL`, HTTP 409) — the assigned site's `active_subscription_count` must be strictly less than its `weekly_capacity`; then the season-capacity gate (`ERR_SEASON_CAPACITY_FULL`, HTTP 409) — the season's `confirmed_share_count` must be strictly less than its `total_share_capacity`; and finally the optimistic-concurrency gate (`ERR_STALE_VERSION`, HTTP 412) on `expected_season_version`. The season itself must also be `OPEN` for a confirm to be defined at all. Both capacity gates use a strict less-than comparison, so the last available slot may be taken but the count may never reach or exceed its cap.

When all gates pass, confirmation performs a coordinated cascade. The season price is computed and frozen: the member's pay-tier multiplier (0.80 for `SOLIDARITY`, 1.00 for `BASELINE`, 1.25 for `SUSTAINER`) is multiplied against the share type's `base_price_cents`, and the product is rounded half-up to a whole number of cents and stored as the subscription's `season_price_cents`. This value is *pinned* at confirm time using the tier as it stood then; it is never recomputed if the member later edits their tier. A `CHARGE_SEASON` ledger entry is posted for that amount. If the assigned site is a `HOME_DELIVERY` zone, a `CHARGE_SURCHARGE` ledger entry is also posted, equal to the site's `delivery_surcharge_cents` multiplied by the season's `week_count`; this entry is posted only when that product is non-zero, so a `HOME_DELIVERY` site with a `delivery_surcharge_cents` of 0 posts no surcharge entry. The system then generates one `WeeklyBox` per delivery week — `week_count` boxes in all, with `week_index` running from 1 to `week_count`, each starting in the `SCHEDULED` state with its `site_id` set to the subscription's `current_site_id` and its `item_count` at 0. The subscription's `outstanding_balance_cents` is recomputed, the season's `confirmed_share_count` is incremented by one, the assigned site's `active_subscription_count` is incremented by one, and the subscription's `version` is incremented.

The season's own `version` advances on each confirm as well — this is the increment that the optimistic-concurrency check described earlier defends against, since `confirmed_share_count` is changing.

### 3.4. The Ledger and the Outstanding Balance

Every financial movement on a subscription is recorded as an immutable, append-only **ledger entry** carrying a `subscription_id`, an `entry_type`, a signed `amount_cents`, and an optional free-text `memo` (defaulting to an empty string). The `entry_type` is one of six values: `CHARGE_SEASON` for the full-season share charge, `CHARGE_ADDON` for an add-on charge, `CHARGE_SURCHARGE` for a home-delivery surcharge, `CREDIT_WORKSHARE` for working-share labor credit, `CREDIT_HOLD_REFUND` for a refunded held week, and `PAYMENT` for a member payment applied. Charge entries carry a positive `amount_cents`; credit and payment entries carry a negative `amount_cents`. A `Member` (or a `FarmManager` on their behalf) may apply a payment, which posts a `PAYMENT` entry with a negative `amount_cents` (the supplied positive `amount_cents` negated) and recomputes the balance; this operation returns the newly created `PAYMENT` ledger entry as its `data` with a `201 Created` status.

The subscription's `outstanding_balance_cents` is a derived field, recomputed from scratch whenever any ledger entry is posted and on the confirm, cancel, hold, and release side effects. Its evaluation order is fixed to avoid any circular dependency. First, sum the `amount_cents` of all charge entries — those of type `CHARGE_SEASON`, `CHARGE_ADDON`, and `CHARGE_SURCHARGE` — to obtain the gross charges. Second, sum the magnitudes of the hold-refund credits (the `CREDIT_HOLD_REFUND` entries, stored negative) and subtract that total from the gross charges to obtain the net amount after refunds. Third, determine the wallet credit to apply: take the smaller of the member's available `wallet_credit_cents` and the net-after-refunds amount floored at zero (so wallet credit is never applied against a negative net). Fourth, sum the magnitudes of the `PAYMENT` entries (also stored negative) to obtain total payments. The outstanding balance is then the net-after-refunds amount, minus the wallet credit applied, minus the total payments, with the final result floored at zero so the balance never goes negative. Capping the wallet application by the post-refund gross rather than by the final balance is what keeps the computation from looping.

This calculation has two readings depending on lifecycle stage, and both must be produced faithfully. Before confirmation — while `billing_status` is `PENDING_PAYMENT`, before any `CHARGE_SEASON` has been posted — the gross charges exclude the season charge, so the balance reflects only any add-ons attached so far; this provisional balance is genuinely lower than the finalized one. Once `billing_status` is `CONFIRMED` or `ACTIVE`, the gross charges include `CHARGE_SEASON`, producing the higher, finalized balance for the same add-on state.

### 3.5. Add-Ons: Attaching and Detaching

A `Member` attaches an add-on to one of their subscriptions by naming the `subscription_id` and the `add_on_id`; the add-on must belong to the same season as the subscription, on pain of `ERR_SEASON_MISMATCH`. An attachment may be created only while the add-on has remaining supply: its `committed_count` must be strictly less than its `weekly_supply_cap`, and an attempt to attach when the committed count has reached the cap is rejected with `ERR_ADDON_SUPPLY_EXHAUSTED`. A successful attachment is recorded as a junction record in the `ATTACHED` state, increments the add-on's `committed_count` by one, and posts a `CHARGE_ADDON` ledger entry.

The add-on charge is the add-on's `weekly_price_cents` multiplied by the number of remaining weeks. The remaining weeks are counted as the number of this subscription's weekly boxes whose `status` is neither `DELIVERED` nor `SKIPPED` — that is, the boxes not yet terminal. If no weekly boxes exist yet because the subscription is still `PENDING_PAYMENT` and has not been confirmed, the remaining weeks instead equal the season's `week_count`. After the charge posts, the subscription's `outstanding_balance_cents` is recomputed.

Detaching an add-on is also a `Member` action; it is defined only while the junction record is `ATTACHED` (otherwise `ERR_INVALID_STATE`). It moves the junction record from `ATTACHED` to `DETACHED`, decrements the owning add-on's `committed_count` by one (freeing a unit of its weekly supply cap), posts an offsetting credit — a `CREDIT_HOLD_REFUND` ledger entry with a negative `amount_cents` equal to the add-on's `weekly_price_cents` multiplied by the remaining weeks counted as of the detach (the same not-yet-terminal-box count, or the season's `week_count` when no boxes exist) — and recomputes the subscription's `outstanding_balance_cents`. The credit entry is posted only when that amount is non-zero.

### 3.6. Weekly Fulfillment: Packing and Delivering Boxes

Each delivery week, a `FarmManager` works through the generated boxes. A box created at confirmation sits in `SCHEDULED`. Packing a box advances it from `SCHEDULED` to `PACKED`; this is permitted only when the box is `SCHEDULED` and when the routing site's `active_subscription_count` does not exceed its `weekly_capacity`. Packing sets the box's `item_count` to the share type's `items_per_box` — or to twice that figure when the box is the target of a swap hold (a double box). Delivering a box advances it from `PACKED` to `DELIVERED`, permitted only from `PACKED`. `DELIVERED` and `SKIPPED` are the two terminal box states.

Delivery is where the two subscription axes wake up. When the box being delivered is the *first* box of its subscription to reach `DELIVERED`, the subscription's billing axis flips from `CONFIRMED` to `ACTIVE` and, in the same step, its fulfillment axis flips from `NOT_STARTED` to `IN_SEASON`. (The billing-axis flip to `ACTIVE` requires that at least one of the subscription's boxes is `DELIVERED`, and the fulfillment-axis flip to `IN_SEASON` requires the subscription's billing axis to be `CONFIRMED` or `ACTIVE` — both conditions are satisfied at the moment of first delivery.) Separately, whenever a box reaches a terminal state, the system checks whether *every* box of the subscription is now terminal — that is, whether the count of the subscription's boxes whose `status` is neither `DELIVERED` nor `SKIPPED` has fallen to zero. When that bubble-up condition holds, the fulfillment axis advances from `IN_SEASON` to `COMPLETED`. Neither fulfillment-axis transition posts any ledger change. A box's `item_count` equals the share type's `items_per_box` for a normally packed box and 0 for a `SKIPPED` box.

### 3.7. Vacation Holds: Refunds and Swaps

When a member will be away, they place a **vacation hold** on a scheduled box. A hold names the `subscription_id` and the `held_box_id` of the box being held, and optionally a `swap_target_box_id`. Placing a hold advances the held box from `SCHEDULED` to `HELD`, and is permitted only when the box is currently `SCHEDULED` and the current clock is strictly before that box's delivery date — which is the season's `first_delivery_date` plus seven days for each week beyond the first (that is, plus seven days times the quantity `week_index` minus one). Placing or releasing a hold at or after the held box's delivery date is rejected with `ERR_HOLD_WINDOW_PASSED` (HTTP 409).

The hold's `mode` is derived from whether a swap target was supplied. With no `swap_target_box_id`, the hold is a `REFUND`: the held week's value is refunded to the member as wallet credit. When a `swap_target_box_id` is supplied, the hold is a `SWAP`: the held week's value is carried forward into the target box as a double box, with no refund. A supplied swap target must satisfy three conditions — it must belong to the same subscription, it must have a `week_index` strictly greater than the held box's `week_index`, and it must itself be `SCHEDULED`; a swap target failing any of these is rejected with `ERR_INVALID_SWAP_TARGET` (HTTP 422). In `SWAP` mode the system arranges for the target box's `item_count` to become twice the share type's `items_per_box` on delivery, and posts no ledger entry. In `REFUND` mode the system posts a `CREDIT_HOLD_REFUND` ledger entry for one week's pro-rata share value and then recomputes the subscription's `outstanding_balance_cents`.

The per-week refund value is computed so that the sum of all per-week refunds reconciles exactly to the pinned `season_price_cents`, with no cent lost or gained to rounding. Divide `season_price_cents` by the season's `week_count` using integer division (discarding any fractional part) to get a base per-week amount, and let the remainder be `season_price_cents` minus that base amount times `week_count`. The weeks with the lowest `week_index` absorb the remainder one cent at a time: a held box whose `week_index` is less than or equal to the remainder is refunded the base amount plus one cent, while a held box whose `week_index` is greater than the remainder is refunded exactly the base amount. This distributes the leftover cents deterministically to the earliest weeks first.

A hold begins in the `ACTIVE` state. A `Member` may release an active hold, which returns the held box from `HELD` to `SCHEDULED` and moves the hold from `ACTIVE` to `RELEASED`; release is permitted only while the hold is `ACTIVE` and the current clock is still strictly before the held box's delivery date. On release of a `REFUND`-mode hold, the original `CREDIT_HOLD_REFUND` is reversed by posting an offsetting charge — a `CHARGE_SEASON` ledger entry with a positive `amount_cents` equal to that held week's per-week refund value — and the subscription's `outstanding_balance_cents` is recomputed. If, instead, the clock passes a held box's delivery date while the box is still `HELD` and its hold still `ACTIVE`, the system moves the box from `HELD` to `SKIPPED` and the hold from `ACTIVE` to `CONSUMED`; if that skip makes every box of the subscription terminal, the fulfillment axis advances to `COMPLETED`.

### 3.8. The Waitlist: Queue, Offer, and Conversion

When capacity is exhausted or a season has closed, prospective members join the **waitlist**. Joining is an unauthenticated public action: an entry supplies the `season_id`, the `member_id`, the requested `share_type_id`, and the requested `requested_site_id`, with the share type and site required to belong to the named season (`ERR_SEASON_MISMATCH` otherwise). A new entry enters the queue in the `WAITING` state, with its `offer_expires_at` null.

A `DeliveryCoordinator` promotes the waitlist when a slot opens. Promotion selects, for a given season, requested site, and share type, the `WAITING` entry with the earliest `created_at`, and moves it from `WAITING` to `OFFERED`. Promotion is gated: a season-level slot must exist (the season's `confirmed_share_count` strictly less than its `total_share_capacity`), the requested site must have room (its `active_subscription_count` strictly less than its `weekly_capacity`, surfacing `ERR_SITE_CAPACITY_FULL` if not), and the optimistic-concurrency check on `expected_season_version` must pass (`ERR_STALE_VERSION` otherwise). On promotion, the entry's `offer_expires_at` is set to the current clock plus 48 hours, and the season's `version` is incremented.

An offered entry resolves in one of three ways. The member may accept, which is permitted only while the entry is `OFFERED` and the current clock is at or before `offer_expires_at`; accepting moves the entry from `OFFERED` to `CONVERTED` and creates a fresh `PENDING_PAYMENT` subscription for that member with the requested share and site, with `working_share_opt_in` defaulting to false (no capacity counter changes until that new subscription is itself confirmed). The accept response returns the updated waitlist entry (now `CONVERTED`) as its `data`, not the newly created subscription. Accepting after the deadline is rejected with `ERR_OFFER_EXPIRED` (HTTP 409). The member may instead decline, permitted while the entry is `OFFERED`, which moves it from `OFFERED` to `DECLINED` and leaves the slot open for the next promotion. Or the offer may simply lapse: when the clock passes `offer_expires_at` while the entry is still `OFFERED`, the system moves it from `OFFERED` to `EXPIRED`, again leaving the slot open. `CONVERTED`, `DECLINED`, and `EXPIRED` are all terminal.

### 3.9. Working Shares and Labor Credit

A subscription that opted into the working-share program (its `working_share_opt_in` is true) can have **work-share shifts** scheduled against it. Scheduling a shift — an action available to both a `FarmManager` and the owning `Member` — supplies a `scheduled_date` and the shift length in `hours` (which must be greater than zero), and creates the shift in the `SCHEDULED` state with `credit_earned_cents` at 0. Both scheduling and completing a shift require the subscription's `working_share_opt_in` to be true; an attempt against a subscription that did not opt in is rejected with `ERR_NOT_WORKING_SHARE` (HTTP 409).

A `FarmManager` resolves a scheduled shift one of two ways. Marking a no-show moves the shift from `SCHEDULED` to `NO_SHOW`; no credit accrues, `credit_earned_cents` stays 0, and no ledger entry is posted. Completing a shift moves it from `SCHEDULED` to `COMPLETED` and accrues wallet credit. The credit is computed against a fixed hourly rate of 1500 cents per hour, subject to a daily cap of 6 creditable hours per calendar date. Concretely: consider all of this subscription's already-`COMPLETED` shifts that fall on the same UTC calendar date as this shift and were created earlier (ordered by `created_at` ascending), and sum their hours to get the prior same-date hours. The creditable hours are this shift's `hours`, but no more than the daily cap of 6 hours minus those prior same-date hours, and never less than zero. The earned credit is the creditable hours multiplied by 1500 cents per hour, rounded half-up to a whole number of cents, and stored as `credit_earned_cents`. Thus a shift whose hours fit entirely under the remaining daily room is credited in full; a shift that straddles the cap is credited only for the hours up to 6 for that date, with the remainder earning zero; and a shift on a date already at or over its cap earns nothing.

On completion, the cascade runs in order: the `credit_earned_cents` is computed, a `CREDIT_WORKSHARE` ledger entry is posted on the subscription, the member's `wallet_credit_cents` is incremented by the earned credit, and the subscription's `outstanding_balance_cents` is recomputed with the now-available wallet credit applied.

### 3.10. Cancellation and Its Cascade

A `Member` may cancel their subscription from any non-terminal billing state — that is, while `billing_status` is `PENDING_PAYMENT`, `CONFIRMED`, or `ACTIVE` — moving it to `CANCELLED`, which is terminal. Cancellation unwinds the subscription's dependents in a defined three-hop cascade. First, every non-terminal weekly box (those in `SCHEDULED` or `HELD`) is moved to `SKIPPED`. Second, for each such box that was `HELD`, its covering vacation hold is released, moving that hold from `ACTIVE` to `RELEASED`. Third, every `ATTACHED` add-on attachment is detached, moving it to `DETACHED` and decrementing each affected add-on's `committed_count`. Alongside these hops, the system posts a `CREDIT_HOLD_REFUND` covering the undelivered prepaid weeks — when cancelling from `ACTIVE`, that refund covers only the weeks whose box was still non-terminal — recomputes `outstanding_balance_cents`, reconciles the season's `confirmed_share_count` and the site's `active_subscription_count` by recomputing them from the surviving `CONFIRMED`/`ACTIVE` subscriptions (a decrement of one when the cancelled subscription had been confirmed, and no change when cancelling a never-confirmed `PENDING_PAYMENT` subscription), and increments the subscription's `version`.

### 3.11. The Simulated Clock

Because temporal windows govern confirmations, holds, and waitlist offers, a `PlatformAdmin` can advance the system's simulated current UTC time through an administrative test-driving capability that accepts a `to_iso8601` target instant. Advancing the clock not only sets the new current time but also fires every clock-driven transition that the new time makes due: any `HELD` box whose delivery date has now passed (with its hold still `ACTIVE`) is moved to `SKIPPED` and its hold to `CONSUMED`, and any `OFFERED` waitlist entry whose `offer_expires_at` has now passed is moved to `EXPIRED`. These are the same system transitions described in the fulfillment and waitlist workflows; the clock advance is simply what triggers them deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the lifecycle actions that drive a state machine — return a `200 OK` status code. The request body, response body, and side effects of each endpoint are not repeated here; they are specified in the Section 3 narratives above and must be reconstructed from them.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/seasons` | Create a season (DRAFT) | FarmManager |
| GET    | `/seasons/{id}` | Fetch a season | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/seasons` | List seasons (paginated) | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/seasons/{id}/open` | Open a season for signups | FarmManager |
| POST   | `/seasons/{id}/close` | Close a season | FarmManager |
| POST   | `/seasons/{id}/promote-waitlist` | Promote the earliest eligible waitlist entry to OFFERED | DeliveryCoordinator |
| POST   | `/pickup-sites` | Create a pickup site / delivery zone for a season | DeliveryCoordinator |
| GET    | `/pickup-sites/{id}` | Fetch a pickup site | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/pickup-sites` | List pickup sites; filter by season | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/share-types` | Create a share type for a season | FarmManager |
| GET    | `/share-types/{id}` | Fetch a share type | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/share-types` | List share types; filter by season | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/add-ons` | Create an add-on for a season | FarmManager |
| GET    | `/add-ons/{id}` | Fetch an add-on | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/add-ons` | List add-ons; filter by season | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/members` | Register a member (no auth) | Anonymous |
| GET    | `/members/{id}` | Fetch a member | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/subscriptions` | Create a draft subscription (PENDING_PAYMENT) for an OPEN season | Member |
| GET    | `/subscriptions/{id}` | Fetch a subscription with computed balances | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/subscriptions` | List subscriptions; filter by season, member, share type, or site | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/subscriptions/{id}/confirm` | Confirm a subscription: charge season, generate weekly boxes | FarmManager |
| POST   | `/subscriptions/{id}/cancel` | Cancel a subscription and cascade box/hold/add-on teardown | Member |
| POST   | `/subscription-add-ons` | Attach an add-on to a subscription | Member |
| DELETE | `/subscription-add-ons/{id}` | Detach an add-on | Member |
| GET    | `/subscriptions/{id}/add-ons` | List a subscription's add-on attachments | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/subscription-add-ons/{id}` | Fetch an add-on attachment | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/subscription-add-ons` | List add-on attachments; filter by add-on | FarmManager, DeliveryCoordinator, PlatformAdmin |
| GET    | `/subscriptions/{id}/weekly-boxes` | List a subscription's weekly boxes | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/weekly-boxes/{id}` | Fetch a weekly box | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/weekly-boxes` | List weekly boxes; filter by site or subscription | FarmManager, DeliveryCoordinator, PlatformAdmin |
| POST   | `/weekly-boxes/{id}/pack` | Pack a scheduled box for the week | FarmManager |
| POST   | `/weekly-boxes/{id}/deliver` | Mark a packed box delivered | FarmManager |
| POST   | `/vacation-holds` | Place a vacation hold (refund or swap) on a scheduled box | Member |
| GET    | `/vacation-holds/{id}` | Fetch a vacation hold | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/vacation-holds` | List vacation holds; filter by held box or swap target | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/subscriptions/{id}/vacation-holds` | List a subscription's vacation holds | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/vacation-holds/{id}/release` | Release an active hold before its delivery date | Member |
| POST   | `/waitlist-entries` | Join a season's waitlist (no auth) | Anonymous |
| GET    | `/waitlist-entries/{id}` | Fetch a waitlist entry | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/waitlist-entries` | List waitlist entries; filter by season, member, share type, or site | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/waitlist-entries/{id}/accept` | Accept an offered waitlist slot, creating a subscription | Member |
| POST   | `/waitlist-entries/{id}/decline` | Decline an offered slot | Member |
| POST   | `/subscriptions/{id}/work-share-shifts` | Schedule a working-share shift for an opted-in subscription | FarmManager, Member |
| GET    | `/subscriptions/{id}/work-share-shifts` | List a subscription's work-share shifts | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| GET    | `/work-share-shifts/{id}` | Fetch a work-share shift | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/work-share-shifts/{id}/complete` | Mark a shift complete and accrue wallet credit | FarmManager |
| POST   | `/work-share-shifts/{id}/mark-no-show` | Mark a shift as a no-show | FarmManager |
| GET    | `/subscriptions/{id}/ledger-entries` | List a subscription's ledger entries (append-only) | FarmManager, DeliveryCoordinator, Member, PlatformAdmin |
| POST   | `/subscriptions/{id}/payments` | Apply a member payment (posts a PAYMENT ledger entry) | Member, FarmManager |
| POST   | `/_clock/set_current_utc` | Set the simulated current UTC time | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_SEASON_MISMATCH` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SIGNUP_CLOSED` | 409 |
| `ERR_HOLD_WINDOW_PASSED` | 409 |
| `ERR_INVALID_SWAP_TARGET` | 422 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_ADDON_SUPPLY_EXHAUSTED` | 409 |
| `ERR_NOT_WORKING_SHARE` | 409 |
| `ERR_SITE_CAPACITY_FULL` | 409 |
| `ERR_SEASON_CAPACITY_FULL` | 409 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_EMAIL` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VALIDATION_PAGINATION` | 422 |

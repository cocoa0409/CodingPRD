# Meal Kit Subscription API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Meal Kit Subscription API, the back-end service that powers a HelloFresh-style weekly meal-kit business. The platform lets members choose a plan size and number of servings, browse and curate a weekly recipe box, set dietary preferences and allergen restrictions, and have their box charged and shipped on a schedule that respects a delivery-day selection cutoff and a cold-pack shipping zone. Around that core flow sit the commercial mechanics every subscription business depends on: provisional and final billing, monthly add-on proration when a member pauses, loyalty discounts that grow with shipped-box history, and a referral program that rewards members for recruiting friends.

The system is fundamentally a pricing-and-scheduling engine. The hardest parts of the domain are not the create/read operations on the catalog, but the two-phase money path — a *provisional* weekly bill computed when a member locks their selection, and a separate *final* charge computed at the cutoff sweep from live data that may have drifted since lock — together with the scheduled, deferred actions (cutoffs, auto-resume from pause, renewals) that must fire deterministically against a controllable logical clock. Because several independent actors (the member, an operations team, and a platform administrator) and automated sweeps all touch overlapping data, the design leans on explicit state machines, optimistic concurrency on plan changes, and a carefully reconciled credit wallet so that every cent of referral credit, pause proration, and loyalty discount is accounted for exactly once.

This specification is written for the engineers who will implement the service. It describes the entities and their relationships, the lifecycle state machines, every calculation with its exact evaluation order, the validation rules and the order in which they fire, the full endpoint surface, and the error catalogue. Monetary precision, scheduling determinism, and ledger consistency are treated as first-class correctness requirements throughout.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which that principal is acting. If either header is missing, or if `X-User-Role` is not one of the declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role (or the specific identity) is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes four roles: `Anonymous`, `Member`, `PlatformOps`, and `PlatformAdmin`.

When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the only operation an anonymous caller may perform is registering a new member. The server does not compare an anonymous `X-User-ID` to any entity's `id`.

When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `Member`. Ownership checks on any resource that references a member compare that resource's owning member to `X-User-ID`: a subscription's `member_id` must equal `X-User-ID`, and a weekly box (and its recipe slots) is owned by the member who owns the box's subscription. A member acting on a subscription, weekly box, or box-recipe slot it does not own is rejected with `ERR_UNAUTHORIZED`.

When `X-User-Role` is `PlatformOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; this role charges, ships, and refunds boxes and is not subject to per-member ownership checks. The server does not compare it to any entity's `id`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque administrator identifier not tied to any persisted entity; this role manages the catalog (plans, shipping zones, recipes), the member lifecycle, referral voiding, and the test clock, and may list all members. The server does not compare it to any entity's `id`.

Creating a referral is a shared operation available to both `Member` and `PlatformAdmin`. The read (GET) endpoints over the catalog, a member's own records, and referrals are available to the roles named in §4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0, with a minimum of 0.

Unless an endpoint explicitly states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes the following fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — `Plan`, `ShippingZone`, `Recipe`, `Member`, `Subscription`, `WeeklyBox`, `BoxRecipe`, and `Referral` — carries a system-managed identity and audit set:

- `id` — a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it is refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by one on every mutation. It is the basis for optimistic concurrency control where that applies.

All eight entities in this system carry the full set above, including `updated_at` and `version`. The `id` is always a UUID without any entity-type prefix.

### 2.5. Money, Precision, and Rounding

All monetary amounts in this system are stored and returned as **integer cents** — for example, a charge of nine dollars and ninety-nine cents is represented as the integer `999`. There are no fractional-cent values and no floating-point money fields. Configuration fields that are themselves amounts (such as a zone's cold-pack surcharge) are likewise integer cents.

Because amounts are integers, rounding only ever arises where a calculation multiplies by a fraction or a percentage. Where rounding is required, the system uses the **round-half-up** method, and each calculation specifies the single point at which it rounds. The weekly-box charge rounds exactly once — at the loyalty-discount percentage step — and never rounds any other intermediate value. The pause proration rounds exactly once, after the full fee-times-unused-days-divided-by-cycle-days expression is evaluated, and never rounds per day. The referral reward involves no rounding at all. These single-rounding rules are normative: rounding at any other step is incorrect.

### 2.6. The Credit Wallet and Derived-Field Reconciliation

Each member owns a single running credit wallet, `credit_balance_cents`, which is read-only to clients and reconciled exclusively by the system. Three independent flows move this wallet, and each must keep it exact: pause proration credits it when a subscription is paused; referral settlement credits it when a referral settles; and weekly-box billing both deducts from it at the final charge and restores to it on refund. Whenever a flow changes `credit_balance_cents`, that change is a mutation of the owning member that refreshes the member's `updated_at` and increments the member's `version`.

A second derived field, `lifetime_box_count`, is a read-only count of the member's weekly boxes that have reached `SHIPPED`. It too is system-maintained, increments by one each time one of the member's boxes ships, and drives the member's loyalty tier. Like the wallet, every change to `lifetime_box_count` is a member mutation that refreshes `updated_at` and increments `version`.

These derived fields are never accepted as client input. On member registration they are initialized to `0`.

### 2.7. Scheduling, the Logical Clock, and Delivery Cutoffs

The system runs against a logical clock rather than wall-clock time, so that scheduled behavior is deterministic and testable. A platform administrator may set the current clock instant directly by supplying a `now_iso8601` value. Setting the clock does **not** trigger any automatic sweep: charging a box that has reached its cutoff is an explicit operation, never an implicit side effect of moving the clock.

Each weekly box has a read-only cutoff instant, `cutoff_at`, that marks the moment its recipe selection locks for that delivery. Selection-side operations (locking a selection, skipping a box, and adding a recipe slot) are only permitted while the current clock is strictly before `cutoff_at`; attempting any of them at or after the cutoff is rejected with `ERR_CUTOFF_PASSED`. Conversely, charging a box is only permitted once the current clock is at or after `cutoff_at`; charging before the cutoff is rejected with `ERR_CUTOFF_NOT_REACHED`.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several paths address a resource nested under another (for example, a specific recipe slot under a specific weekly box). When a path carries more than one identifier, the system validates them left to right and rejects on the **first** identifier that does not resolve, returning the not-found error for that resource. For instance, a request for a box-recipe slot under a non-existent weekly box fails with `ERR_WEEKLY_BOX_NOT_FOUND` before the slot is ever looked up. More generally, the existence of every path and body resource id — across `Member`, `Subscription`, `WeeklyBox`, `Recipe`, `Plan`, `ShippingZone`, `BoxRecipe`, and `Referral` — is checked left to right, each missing resource yielding its specific `ERR_{RESOURCE}_NOT_FOUND` code (`ERR_MEMBER_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_WEEKLY_BOX_NOT_FOUND`, `ERR_BOX_RECIPE_NOT_FOUND`, `ERR_RECIPE_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SHIPPING_ZONE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`).

### 2.9. Validation Ordering

When several checks apply to one request, they fire in a fixed priority order so that the same bad request always produces the same error. The order is: first, the user-context header check (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, authorization, covering both role permission and member ownership (`ERR_UNAUTHORIZED`); third, existence of all referenced resources, left to right (the `ERR_{RESOURCE}_NOT_FOUND` family); fourth, the target resource's state being correct for the operation (the state-conflict family such as `ERR_SELECTION_NOT_OPEN`, `ERR_BOX_NOT_LOCKED`, `ERR_SUBSCRIPTION_NOT_ACTIVE`, and so on); fifth, the optimistic-concurrency version check on plan changes (`ERR_STALE_SUBSCRIPTION_VERSION`); sixth, the temporal cutoff checks (`ERR_CUTOFF_PASSED` for selection-side writes, `ERR_CUTOFF_NOT_REACHED` for charging); then, the business-rule checks that follow — allergen safety, diet compatibility, box capacity and duplicates, delivery-date overlap, pause-window overlap, referential serviceability and plan activity, and referral integrity, each described where it is enforced below. Malformed bodies — a missing required field, a wrong type, or an out-of-range value — are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.10. Optimistic Concurrency Control on Plan Changes

Changing a subscription's plan is the one mutation guarded by optimistic concurrency. A plan-change request must carry `expected_subscription_version`, a non-optional field holding the `version` of the subscription the client last observed. The server compares it to the subscription's current `version`; if they do not match — because a pause, a resume, or an earlier plan change has advanced the version since the client last read the subscription — the request is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412), so the client cannot overwrite a newer plan binding it has not seen. A successful plan change installs the new plan as the one in force and increments the subscription's `version` by one. No other endpoint accepts or requires a version field; only the plan-change operation is version-guarded.

### 2.11. Parallel State Dimensions and Cascades

A weekly box carries two state dimensions that evolve independently: a selection dimension (`selection_status`, one of `OPEN`, `LOCKED`, `SKIPPED`) and a fulfillment dimension (`fulfillment_status`, one of `PENDING`, `CHARGED`, `SHIPPED`, `REFUNDED`). A subscription has its own lifecycle (`ACTIVE`, `PAUSED`, `CANCELLED`), a referral has its own (`PENDING`, `SETTLED`, `VOID`), and a member has its own (`ACTIVE`, `DEACTIVATED`). Several operations on a parent cascade into children: pausing or cancelling a subscription reaches into its in-scope boxes, shipping a referee's first box can settle the referrer's referral, and deactivating a member voids that member's pending inbound referrals. Each such cascade is spelled out in §3 alongside the workflow that triggers it. Whenever a cascade mutates a resource, that resource's `updated_at` is refreshed and its `version` incremented, exactly as for a direct mutation.

## 3. Business Logic & Workflows

### 3.1. The Catalog: Plans, Shipping Zones, and Recipes

Before any member can subscribe, a platform administrator builds out three catalogs. A **Plan** defines the box size: a `code` (such as `COUPLE_3`) intended to be unique but not enforced as such by the server — the server stores the supplied `code` verbatim and performs no duplicate-`code` check, so a repeated `code` is accepted rather than rejected; a `servings_per_meal` value that must be either 2 or 4, a `meals_per_week` count between 2 and 6 inclusive, and an `is_active` flag (defaulting to true) that controls whether new subscriptions may select it. A new subscription may only bind to a plan whose `is_active` is true; binding to an inactive plan is rejected with `ERR_PLAN_INACTIVE`.

A **ShippingZone** captures the logistics of a delivery area: a `zone_code` that is intended to be unique but is not enforced as unique by the server (the supplied value is stored verbatim with no duplicate-`zone_code` check, so a repeated `zone_code` is accepted rather than rejected) and that must be one of `ZONE_A`, `ZONE_B`, `ZONE_C`, or `ZONE_D`; a `cold_pack_surcharge_cents` (a flat per-box surcharge that must be zero or greater) added to every box delivered into that zone; a `cutoff_weekday` expressed as an ISO weekday from 1 (Monday) through 7 (Sunday) inclusive, marking the day of the week on which selection locks ahead of a delivery; and a `serviceable` flag (defaulting to true) indicating whether the zone accepts new deliveries. A new member's zone must be serviceable, or registration is rejected with `ERR_ZONE_NOT_SERVICEABLE`.

A **Recipe** describes a dish that can be slotted into a box: a `title` for display, an `is_premium` flag (defaulting to false) that marks recipes carrying a per-slot upcharge, a `contains_allergens` array of allergen tags the recipe contains (such as `PEANUT`, `DAIRY`, `GLUTEN`, or `SHELLFISH`, defaulting to an empty list), a `diet_tags` array of compatibility tags (such as `VEGETARIAN`, `PESCATARIAN`, or `LOW_CARB`, defaulting to an empty list), and an `is_available` flag (defaulting to true) governing whether the recipe may be selected into new boxes. The catalog also supports reverse lookups: one can list every recipe slot that selected a given recipe, exposing the `recipe_id` reachability across boxes.

### 3.2. Member Registration and the Referral Graph

A prospective customer registers as a **Member** with an `email` that is expected to be unique across all members but whose uniqueness the server does not enforce — the supplied `email` is stored verbatim with no duplicate-email check, so a repeated `email` is accepted rather than rejected; a `full_name`; and a `shipping_zone_id` naming the `ShippingZone` they deliver into. Registration is the one action an anonymous caller may take. Optionally the registrant supplies a `referred_by_member_id`, the `id` of an existing member who recruited them — a self-referential link that is null for an organic signup. On registration the system mints a unique `referral_code` for the new member, sets `credit_balance_cents` and `lifetime_box_count` to 0, and sets the member's `status` to `ACTIVE`. When a `referred_by_member_id` is supplied, a corresponding referral in `PENDING` status is established linking the referrer to the new referee. Members can be listed (by an administrator) and filtered by `referred_by_member_id` or by `shipping_zone_id` to walk the reverse foreign-key reachability.

A member's read view exposes the running `credit_balance_cents` and `lifetime_box_count`. A dedicated referral-summary read computes, for a member acting as a referrer, three figures: a forward-looking `forward_estimate_cents`, a `settled_total_cents`, and a `pending_count`. The forward estimate is described in §3.7.

A member can be moved from `ACTIVE` to `DEACTIVATED` by an administrator. Deactivation requires the member to currently be `ACTIVE`, otherwise it is rejected with `ERR_MEMBER_NOT_ACTIVE`; and it requires that the member hold no subscription that is either `ACTIVE` or `PAUSED`, otherwise it is rejected with `ERR_MEMBER_HAS_LIVE_SUBSCRIPTION`. When deactivation succeeds, the member's `status` becomes `DEACTIVATED`, and as a cascade, every still-`PENDING` referral in which this member is the referee is moved to `VOID`, with each such referral's `reward_cents` remaining 0.

### 3.3. Creating and Operating a Subscription

A member creates a **Subscription** for themselves by naming the owning `member_id` and the `plan_id` to bind. The creator may also set a `diet_preference` — one of `STANDARD`, `VEGETARIAN`, `PESCATARIAN`, `LOW_CARB`, or `FAMILY_FRIENDLY`, defaulting to `STANDARD` — which both drives the diet premium in pricing and forms the base of the diet/allergen filtering; a `blocked_allergens` array of allergen tags that must never appear in any selected recipe (defaulting to an empty list); and an optional `monthly_addon_fee_cents` flat monthly add-on (such as premium support, defaulting to 0) that is prorated when the subscription is paused. The creator must supply a `billing_cycle_day`, the day of the month from 1 through 28 inclusive on which the monthly add-on renews. On creation the subscription's `status` is `ACTIVE` and its `version` is 1. The plan bound at creation must be active (else `ERR_PLAN_INACTIVE`). A subscription read exposes its `status`, `version`, and `scheduled_resume_date` (a read-only ISO date that is null whenever the subscription is not paused). Subscriptions can be listed and filtered by `member_id` or `plan_id`.

The subscription lifecycle is cyclic between `ACTIVE` and `PAUSED`, with `CANCELLED` as the terminal state. The plan currently in force is recorded in `plan_id`, which a plan change replaces.

**Changing the plan.** A member changes the plan in force by submitting a new `plan_id` together with `expected_subscription_version`, under the optimistic-concurrency rule of §2.10: the supplied version must equal the subscription's current `version` or the change is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). The new plan must itself be active, or the change is rejected with `ERR_PLAN_INACTIVE`. On success the new plan supersedes the prior binding and the subscription's `version` increments by one.

**Pausing.** A member pauses an `ACTIVE` subscription by supplying a `resume_date`. The subscription must be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`), and the `resume_date` must be strictly after the current clock date (else `ERR_INVALID_RESUME_DATE`). The requested pause window, running from now to the `resume_date`, must not overlap any existing non-cancelled pause window on the same subscription; windows are treated as half-open intervals, so adjacency — where one window's `resume_date` equals the next window's start — is allowed, but a true overlap is rejected with `ERR_PAUSE_WINDOW_OVERLAP`. When the pause succeeds, the subscription moves to `PAUSED`; `scheduled_resume_date` is set to the supplied `resume_date`; the unused portion of the monthly add-on fee is computed (see §3.6) and credited to the member's `credit_balance_cents`; and, as a cascade, every owning weekly box that is still `OPEN` on its selection dimension, still `PENDING` on its fulfillment dimension, and scheduled to deliver on or before the `resume_date` is moved to `SKIPPED` on its selection dimension. The subscription's `version` increments by one.

**Resuming.** A member resumes a `PAUSED` subscription. It must be `PAUSED` (else `ERR_SUBSCRIPTION_NOT_PAUSED`). On success the subscription returns to `ACTIVE`, `scheduled_resume_date` is cleared to null, and `version` increments by one.

**Cancelling.** A member cancels a subscription that is either `ACTIVE` or `PAUSED`; cancelling reaches the terminal `CANCELLED` state. Cancelling from `ACTIVE` requires the subscription to be `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`), and cancelling from `PAUSED` requires it to be `PAUSED` (else `ERR_SUBSCRIPTION_NOT_PAUSED`). In both cases, as a cascade, every owning weekly box whose fulfillment dimension is still `PENDING` has its selection dimension set to `SKIPPED` while its `fulfillment_status` remains `PENDING` — only non-terminal boxes are touched. When cancelling from `PAUSED`, `scheduled_resume_date` is additionally cleared to null. In all cancellation paths the subscription's `version` increments by one.

### 3.4. Building a Weekly Box and Curating Its Recipes

A member creates a **WeeklyBox** against one of their subscriptions by naming the `subscription_id` and a `delivery_date`. The `delivery_date` must be strictly after the subscription's current clock date; a `delivery_date` that is on or before the current clock date is rejected with `ERR_VALIDATION` (HTTP 400). At most one non-`SKIPPED` box may occupy a given `delivery_date` for a subscription — a closed-point collision on the delivery date — and a second non-`SKIPPED` box on the same date is rejected with `ERR_DELIVERY_DATE_TAKEN`. On creation the box's `cutoff_at` is computed (see §3.6), its `selection_status` is `OPEN`, its `fulfillment_status` is `PENDING`, its `provisional_charge_cents` is initialized to `0`, and its `final_charge_cents` is initialized to `null`. A box read exposes both status dimensions and the two charge figures, `provisional_charge_cents` and `final_charge_cents`. Boxes can be listed and filtered by `subscription_id`.

Within an `OPEN` box, a member curates the menu by adding recipe slots. Each added slot is a **BoxRecipe** junction row created by naming a `recipe_id`; the row records its `box_id`, the chosen `recipe_id`, and an `is_premium_snapshot` — a read-only copy of the recipe's `is_premium` flag captured at the moment of selection, which is what later drives the per-slot premium upcharge. Adding a slot is permitted only before the cutoff (else `ERR_CUTOFF_PASSED`). Three business checks guard every addition, evaluated in this order. First, allergen safety: the recipe must not contain any allergen present in the subscription's `blocked_allergens` set — if it does, the addition is rejected with `ERR_ALLERGEN_BLOCKED`. Second, diet compatibility: when the subscription's `diet_preference` is neither `STANDARD` nor `FAMILY_FRIENDLY`, the recipe's `diet_tags` must include that `diet_preference` tag, or the addition is rejected with `ERR_DIET_INCOMPATIBLE`; for `STANDARD` and `FAMILY_FRIENDLY` preferences no diet tag is required. Third, capacity and uniqueness: a box may hold at most as many slots as the plan's `meals_per_week`, and a slot whose addition would exceed that count is rejected with `ERR_BOX_FULL`; the same recipe may not be added twice to one box, and a duplicate is rejected with `ERR_DUPLICATE_RECIPE`.

A member may remove a recipe slot from an `OPEN` box, addressing the slot by its identifier (`boxRecipeId`) under the box; the slot is deleted. Listing the slots of a box walks the reverse reachability of `box_id`.

### 3.5. The Box Lifecycle: Lock, Skip, Charge, Ship, Refund

The selection dimension and the fulfillment dimension of a weekly box advance on separate tracks; the following describes both and the cross-dimension preconditions that tie them together.

**Locking the selection.** A member locks an `OPEN` box, advancing its `selection_status` from `OPEN` to `LOCKED`. Locking requires four conditions: the box's `selection_status` is `OPEN` (else `ERR_SELECTION_NOT_OPEN`); the owning subscription's `status` is `ACTIVE` (else `ERR_SUBSCRIPTION_NOT_ACTIVE`); the number of recipe slots on the box is exactly the plan's `meals_per_week` (else `ERR_SELECTION_INCOMPLETE`); and the current clock is strictly before `cutoff_at` (else `ERR_CUTOFF_PASSED`). On a successful lock, the box's `provisional_charge_cents` is computed under the provisional variant of the weekly-box charge described in §3.6, taking a snapshot of the member's credit and loyalty standing as they stand at the lock instant; locking performs no credit deduction. The locked set of recipe slots is frozen from this point.

**Skipping.** A member skips a box before its cutoff, moving its `selection_status` to `SKIPPED`. A skip is allowed from `OPEN` and from `LOCKED`. Skipping from `OPEN` requires `selection_status` to be `OPEN` (else `ERR_SELECTION_NOT_OPEN`) and the current clock strictly before `cutoff_at` (else `ERR_CUTOFF_PASSED`). Skipping from `LOCKED` requires `selection_status` to be `LOCKED` (else `ERR_SELECTION_NOT_LOCKED`), additionally requires that the fulfillment dimension is still `PENDING` — a box already charged cannot be skipped, and an attempt is rejected with `ERR_BOX_ALREADY_CHARGED` — and likewise requires the current clock strictly before `cutoff_at` (else `ERR_CUTOFF_PASSED`). When a box is skipped from `LOCKED`, its `provisional_charge_cents` is reset to 0. (Because no box at `OPEN` has yet been charged, the skip-from-`OPEN` path leaves the fulfillment dimension `PENDING`.)

**Charging.** Charging advances the fulfillment dimension from `PENDING` to `CHARGED`. It is performed by the operations role on a box whose selection is locked, at or after the cutoff. Charging requires the box's `selection_status` to be `LOCKED` (else `ERR_BOX_NOT_LOCKED`), the current clock to be at or after `cutoff_at` (else `ERR_CUTOFF_NOT_REACHED`), and the `fulfillment_status` to be `PENDING` (else `ERR_BOX_NOT_PENDING`). On a successful charge, the box's `final_charge_cents` is computed under the final variant of the weekly-box charge (see §3.6) from the live selection and the live `credit_balance_cents` at the charge instant, the `fulfillment_status` becomes `CHARGED`, and the credit actually applied to this box is deducted from the member's `credit_balance_cents`.

**Shipping.** The operations role ships a `CHARGED` box, advancing its fulfillment dimension from `CHARGED` to `SHIPPED`. Shipping requires the `fulfillment_status` to be `CHARGED` (else `ERR_BOX_NOT_CHARGED`) and the owning member's shipping zone to be serviceable (else `ERR_ZONE_NOT_SERVICEABLE`). On a successful ship, the owning member's `lifetime_box_count` increments by one. Furthermore, if this is the referee member's very first box to reach `SHIPPED`, the system settles that referee's `PENDING` referral as a cascade — moving the referral toward `SETTLED`, which in turn credits the referrer's `credit_balance_cents` as described in §3.7.

**Refunding.** The operations role refunds a `CHARGED` box, advancing its fulfillment dimension from `CHARGED` to the terminal `REFUNDED`. Refunding requires the `fulfillment_status` to be `CHARGED` (else `ERR_BOX_NOT_CHARGED`). On a successful refund, the credit that was consumed when this box was charged is restored to the member's `credit_balance_cents` as a compensating ledger entry.

### 3.6. How a Box Is Priced and When It Locks

**The cutoff projection.** When a weekly box is created, its `cutoff_at` is derived from the delivery date and the member's shipping zone. Starting from the calendar day immediately before the `delivery_date` and walking backward one day at a time, the system finds the most recent day whose ISO weekday equals the zone's `cutoff_weekday`; `cutoff_at` is that day at 23:59:59.000Z. By construction this instant always falls strictly before the delivery date. The cutoff is expressed as an ISO 8601 UTC timestamp with millisecond precision.

**The weekly-box charge.** The charge for a box is computed by a fixed, eleven-step procedure, all amounts in integer cents and evaluated strictly in this order. First, the total servings for the box is the plan's `servings_per_meal` multiplied by the plan's `meals_per_week`. Second, a per-serving rate is chosen by tier: if total servings is at least 16, the rate is 899 cents; if total servings is at least 8 but below 16, the rate is 999 cents; and if total servings is below 8, the rate is 1099 cents. Third, the base amount is the per-serving rate plus a diet premium for the subscription's `diet_preference`, with that sum multiplied by the total servings; the diet premium is 0 for `STANDARD`, 0 for `VEGETARIAN`, 150 cents for `PESCATARIAN`, 200 cents for `LOW_CARB`, and 0 for `FAMILY_FRIENDLY`. Fourth, a premium upcharge of 400 cents is added for each recipe slot on the box whose `is_premium_snapshot` is true — that is, 400 cents multiplied by the count of premium slots. Fifth, the subtotal is the base plus that premium upcharge. Sixth, the zone total is the subtotal plus the cold-pack surcharge of the member's shipping zone (`cold_pack_surcharge_cents`).

Seventh, a loyalty percentage is looked up from the member's `lifetime_box_count`, read as a pre-increment snapshot — that is, the box's own eventual shipment has not yet bumped the counter: the percentage is 10 percent when `lifetime_box_count` is at least 24, 5 percent when it is at least 12 but below 24, and 0 percent when it is below 12. Eighth, the loyalty discount is the zone total multiplied by the loyalty percentage, rounded half-up to whole cents at this single step — this is the only rounding in the entire calculation, performed once here and never on any intermediate value. Ninth, the amount after loyalty is the zone total minus the loyalty discount. Tenth, the credit applied is the smallest of three quantities: the member's current `credit_balance_cents`, the per-box referral-credit cap of 2000 cents, and the amount after loyalty. Eleventh, the charge is the amount after loyalty minus the credit applied.

This procedure runs in two variants. The **provisional** variant runs when the box transitions from `OPEN` to `LOCKED` and writes its result to `provisional_charge_cents`; it reads the member's `credit_balance_cents` and `lifetime_box_count` as they stand at the lock instant and does **not** deduct any credit or mutate the wallet, and it operates on the recipe set frozen at lock. The **final** variant runs when the box transitions from `PENDING` to `CHARGED` at the cutoff and writes its result to `final_charge_cents`; it re-reads the *live* `credit_balance_cents` and `lifetime_box_count` at the charge instant — which may have changed since lock, for example because a referral settled or another box shipped and bumped the loyalty tier — and it **does** deduct the credit applied from the member's `credit_balance_cents`. The final variant prices the same frozen lock-time recipe set as the provisional variant.

**Pause proration.** When a subscription is paused, the unused portion of the monthly add-on fee for the current billing cycle is refunded as credit. The cycle length is 30 days. The number of days elapsed in the cycle is the difference between the current clock date and the most recent `billing_cycle_day` anchor falling on or before the current date, clamped to lie between 0 and 30 inclusive. The unused days is 30 minus that elapsed count, but never less than 0. The proration credit is the subscription's `monthly_addon_fee_cents` multiplied by the unused days, divided by 30, with the result of that whole expression rounded half-up to whole cents exactly once — the rounding is applied after the multiply-and-divide, never per day.

### 3.7. The Referral Program

A **Referral** records that one member (`referrer_member_id`) recruited another (`referee_member_id`). A referral may be created directly by naming both members, or it arises automatically when a new member registers with a `referred_by_member_id`. A referral begins in `PENDING` with `reward_cents` of 0. Creation forbids self-referral: the `referrer_member_id` must differ from the `referee_member_id`, or it is rejected with `ERR_SELF_REFERRAL`; and a referee who already has a referral cannot be referred again, an attempt being rejected with `ERR_REFEREE_ALREADY_REFERRED`. Referrals can be listed and filtered by `referrer_member_id` or `referee_member_id`.

**Settlement.** A referral settles automatically when the referee's first weekly box reaches `SHIPPED` (the cascade noted in §3.5). At that moment the system counts how many of the referrer's referrals have already settled within the current billing cycle. The referrer's "current billing cycle" for this cap is the 30-day window whose anchor is the most recent date on or before the current clock date whose day-of-month equals the `billing_cycle_day` of the referrer's most-recently-created subscription (the subscription with the latest `created_at`); a referral counts toward the settled count only if its own settlement instant falls on or after that anchor instant (the anchor date at 00:00:00 UTC). If the referrer owns no subscription at all, there is no anchor and every one of the referrer's already-`SETTLED` referrals counts toward the cap regardless of when it settled. If that settled count is below the per-cycle cap of 3, the referral settles: its `reward_cents` is set to the fixed reward of 1500 cents, its `status` becomes `SETTLED`, and that 1500 cents is credited to the referrer's `credit_balance_cents`. Eligibility among a referrer's referrals is ordered by their `created_at` ascending within the current billing cycle. If, however, the settled count has already reached the cap of 3, the referral does not settle and earns no reward: instead it moves to `VOID` with `reward_cents` of 0. Both `SETTLED` and `VOID` are terminal states.

**Voiding.** An administrator may void a `PENDING` referral directly. Voiding requires the referral to be `PENDING` (else `ERR_REFERRAL_NOT_PENDING`); on success the referral's `status` becomes `VOID` and its `reward_cents` is set to 0.

**The forward estimate.** The referral-summary read for a member acting as referrer reports a forward-looking projection alongside actuals. The `forward_estimate_cents` is the fixed reward of 1500 cents multiplied by the count of that member's `PENDING` referrals — an uncapped, not-yet-credited optimistic upper bound. The summary also reports `settled_total_cents` (the total already settled) and `pending_count` (the number of pending referrals). This forward estimate deliberately ignores the per-cycle cap; the actual settled rewards honor it.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify an existing resource — including state transitions — return `200 OK`. A successful resource removal returns `204 No Content`. The table below lists the full endpoint surface; request and response details are reconstructed from the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plans` | Create a plan in the catalog | PlatformAdmin |
| GET | `/plans` | List plans | PlatformAdmin, Member |
| GET | `/plans/{id}` | Get a plan | PlatformAdmin, Member |
| POST | `/shipping-zones` | Create a shipping zone surcharge/cutoff config | PlatformAdmin |
| GET | `/shipping-zones` | List shipping zones | PlatformAdmin, Member |
| GET | `/shipping-zones/{id}` | Get a shipping zone | PlatformAdmin, Member |
| POST | `/recipes` | Create a recipe in the catalog | PlatformAdmin |
| GET | `/recipes` | List recipes | PlatformAdmin, Member |
| GET | `/recipes/{id}` | Get a recipe | PlatformAdmin, Member |
| GET | `/recipes/{id}/box-recipes` | List recipe slots that selected this recipe | PlatformAdmin, Member |
| POST | `/members` | Register a member (mints referral code; optional referrer link) | Anonymous |
| GET | `/members` | List all members (filter by referrer or zone) | PlatformAdmin |
| GET | `/members/{id}` | Get a member | PlatformAdmin, Member |
| GET | `/members/{id}/referral-summary` | Computed referral estimate and settled total | PlatformAdmin, Member |
| POST | `/members/{id}/deactivate` | Deactivate a member | PlatformAdmin |
| POST | `/subscriptions` | Create a subscription for a member | Member |
| GET | `/subscriptions` | List subscriptions (filter by member or plan) | PlatformAdmin, Member |
| GET | `/subscriptions/{id}` | Get a subscription | PlatformAdmin, Member |
| POST | `/subscriptions/{id}/plan-changes` | Change plan (optimistic concurrency on version) | Member |
| POST | `/subscriptions/{id}/pause` | Pause a subscription until a resume date | Member |
| POST | `/subscriptions/{id}/resume` | Resume a paused subscription | Member |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Member |
| POST | `/weekly-boxes` | Create a weekly box on a delivery date | Member |
| GET | `/weekly-boxes` | List weekly boxes (filter by subscription) | PlatformAdmin, Member |
| GET | `/weekly-boxes/{id}` | Get a weekly box | PlatformAdmin, Member |
| POST | `/weekly-boxes/{id}/recipes` | Add a recipe slot to an open box | Member |
| GET | `/weekly-boxes/{id}/recipes` | List recipe slots for a box | PlatformAdmin, Member |
| DELETE | `/weekly-boxes/{id}/recipes/{boxRecipeId}` | Remove a recipe slot from an open box | Member |
| POST | `/weekly-boxes/{id}/lock-selection` | Lock selection; compute provisional charge | Member |
| POST | `/weekly-boxes/{id}/skip` | Skip a box before cutoff | Member |
| POST | `/weekly-boxes/{id}/charge` | Charge a locked box at/after cutoff | PlatformOps |
| POST | `/weekly-boxes/{id}/ship` | Ship a charged box | PlatformOps |
| POST | `/weekly-boxes/{id}/refund` | Refund a charged box | PlatformOps |
| POST | `/referrals` | Create a referral linking referrer and referee | PlatformAdmin, Member |
| GET | `/referrals` | List referrals (filter by referrer or referee) | PlatformAdmin, Member |
| GET | `/referrals/{id}` | Get a referral | PlatformAdmin, Member |
| POST | `/referrals/{id}/void` | Void a pending referral | PlatformAdmin |
| POST | `/_clock/set` | Set the system clock (test-driving) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_WEEKLY_BOX_NOT_FOUND` | 404 Not Found |
| `ERR_BOX_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_RECIPE_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPPING_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_REFERRAL_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_SUBSCRIPTION_NOT_PAUSED` | 409 Conflict |
| `ERR_SELECTION_NOT_OPEN` | 409 Conflict |
| `ERR_SELECTION_NOT_LOCKED` | 409 Conflict |
| `ERR_BOX_NOT_LOCKED` | 409 Conflict |
| `ERR_BOX_NOT_PENDING` | 409 Conflict |
| `ERR_BOX_ALREADY_CHARGED` | 409 Conflict |
| `ERR_BOX_NOT_CHARGED` | 409 Conflict |
| `ERR_REFERRAL_NOT_PENDING` | 409 Conflict |
| `ERR_MEMBER_NOT_ACTIVE` | 409 Conflict |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 Precondition Failed |
| `ERR_CUTOFF_PASSED` | 409 Conflict |
| `ERR_CUTOFF_NOT_REACHED` | 409 Conflict |
| `ERR_INVALID_RESUME_DATE` | 422 Unprocessable Entity |
| `ERR_DELIVERY_DATE_TAKEN` | 409 Conflict |
| `ERR_PAUSE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ALLERGEN_BLOCKED` | 422 Unprocessable Entity |
| `ERR_DIET_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_BOX_FULL` | 409 Conflict |
| `ERR_DUPLICATE_RECIPE` | 409 Conflict |
| `ERR_SELECTION_INCOMPLETE` | 409 Conflict |
| `ERR_ZONE_NOT_SERVICEABLE` | 422 Unprocessable Entity |
| `ERR_PLAN_INACTIVE` | 422 Unprocessable Entity |
| `ERR_SELF_REFERRAL` | 422 Unprocessable Entity |
| `ERR_REFEREE_ALREADY_REFERRED` | 422 Unprocessable Entity |
| `ERR_MEMBER_HAS_LIVE_SUBSCRIPTION` | 409 Conflict |
| `ERR_VALIDATION` | 400 Bad Request |

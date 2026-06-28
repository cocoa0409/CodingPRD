# Car Subscription & Flexible Lease API — Product Requirements Document

## 1. Introduction

The Car Subscription & Flexible Lease platform replaces the rigid multi-year auto lease with an all-inclusive monthly subscription: a single recurring fee bundles the vehicle, its insurance, and its scheduled maintenance, while the subscriber retains the freedom to swap into a different vehicle, upgrade or downgrade their plan tier, and walk away after a minimum commitment window. This document specifies the API that runs the entire operation end to end — from publishing plan tiers and stocking regional fleets, through credit-driven eligibility scoring and deposit calculation, to vehicle reservation and delivery, recurring mileage-aware billing, mid-term swaps, and the final return inspection where a security deposit is reconciled against damage and outstanding charges.

Two business pressures shape every rule here. The first is **finite fleet utilization**: a region holds only so many cars, and the same physical vehicle cannot be reserved for two subscribers at once, so the system tracks allocation state with strict concurrency control and keeps a live read on how much of each fleet is working versus idle. The second is **pricing fairness across a flexible commitment**: included mileage, tiered overage, prorated swap adjustments, forward-looking early-cancellation penalties, and a credit-weighted deposit must all compute to the cent and survive audit. Because the subscription's commercial life (draft, delivery, active use, return, closure) advances independently of its payment standing (current versus past-due), the platform models these as two parallel state axes on the same subscription and resolves their interactions explicitly rather than by accident.

The intended operators are a platform catalog administrator, regional fleet operators who handle the physical logistics of assigning, delivering, swapping, inspecting, and maintaining vehicles, billing administrators who own all financial settlement, and the members themselves who subscribe, drive, request swaps, and eventually return their cars. Everything below is written so that an engineer can implement the system without further clarification.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the operational capacity under which they act. If either header is missing, or if `X-User-Role` does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. The one structural exception is the logical-clock control endpoint, which still requires the platform administrator role even though it is a system-maintenance capability rather than a business operation.

The system recognizes exactly four roles, spelled precisely as follows: `PlatformAdmin`, `FleetOperator`, `BillingAdmin`, and `Member`. When a recognized but unauthorized role attempts an operation it is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE`.

`PlatformAdmin` is an operator superset: it manages the plan catalog, creates fleets, drives the logical clock, and may perform every read. Its `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may accept and log it but never compares it to any entity's `id`. `FleetOperator` owns vehicle, fleet, and courier logistics — assignment, activation, swaps, inspections, delivery slots, and maintenance — and its `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. `BillingAdmin` owns financial settlement — eligibility decisions, billing-cycle close, billing-status flips, and deposit settlement — and its `X-User-ID` is also an opaque operator identifier with no entity backing.

`Member` is different. When `X-User-Role` is `Member`, the `X-User-ID` is the `id` of the acting `Applicant`; ownership checks on any resource that references an `Applicant` compare the resource's foreign-key field to `X-User-ID`. Concretely, a `Member` acting on a `Subscription` must own it, meaning the supplied `X-User-ID` must equal that subscription's `applicant_id`; if it does not, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership rule applies specifically when a member initiates a return, performs an early cancellation, or requests a swap on a subscription.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` below 1 or above 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Most resources in the system carry a standard set of system-managed fields. The `id` is a unique, server-minted identifier formatted as a UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification and is refreshed on every mutation. The `version` field is a system-managed integer that begins at its initial value and increments by one on each mutation; it is the basis for optimistic concurrency control described in §2.7.

There is one deliberate exception to this convention. The `Invoice` resource is immutable once posted: it carries only an `id` and a `created_at`, and has neither an `updated_at` nor a `version` field. Every other entity — `SubscriptionPlan`, `Fleet`, `Vehicle`, `Applicant`, `Subscription`, `BillingCycle`, `SwapRequest`, `ReturnInspection`, `DamageLineItem`, `Courier`, and `DeliverySlot` — carries the full set of `id`, `created_at`, `updated_at`, and `version`.

All timestamps the system records — including a subscription's `term_start_iso` and `cycle_start_iso`, a billing cycle's `cycle_start_iso` and `cycle_end_iso`, an invoice's `posted_at_iso`, and a delivery slot's `window_start_iso` and `window_end_iso` — are expressed in UTC. Wherever the specification refers to "now," it means the server's logical clock, never wall-clock time (see §2.8).

### 2.5. Monetary Values, Counting Bases, and Precision

All monetary amounts in this system are stored and exchanged as **integer cents**; there are no fractional-cent values in any payload. Where a calculation produces a non-integer intermediate (for example a prorated daily fee), the result is rounded to the nearest whole cent using the round-half-up convention before it is stored or summed. Several derived quantities make this explicit below in §3, and each names round-half-up as its rounding method.

Two derived ratios are expressed as decimals rather than cents. A fleet's `utilization_pct` and an applicant's `eligibility_score` are each computed to four decimal places using round-half-up. A fleet's utilization is the fraction of its vehicles currently in use; when a fleet has no vehicles at all, its utilization is exactly 0 rather than an error or null, to avoid dividing by zero.

The canonical, persisted definition of "in use" for utilization counts a vehicle whose `status` is either `RESERVED` or `ASSIGNED`. A vehicle in `AVAILABLE`, `MAINTENANCE`, or `IN_INSPECTION` does not count as in use. Concretely, the persisted utilization is the count of a fleet's vehicles in `RESERVED` or `ASSIGNED` divided by the total count of that fleet's vehicles in any state, to four decimals — so a fleet of four vehicles holding one `RESERVED` and one `ASSIGNED` reads `0.5000`. The system also offers a what-if projection under an alternate counting basis (see §3.7) that does not mutate the canonical value.

### 2.6. Fleet and Subscription Consistency Cascades

Vehicle allocation is the spine of the system, and every change to a vehicle's allocation `status` ripples outward immediately and synchronously. Whenever a vehicle's `status` changes — on assignment, activation, swap approval, swap completion, return settlement, or entry to and exit from maintenance — the owning `Fleet` recomputes its derived counts. A fleet's `total_vehicles` is the count of all vehicles whose `fleet_id` is that fleet, regardless of state; its `in_use_count` is the count of those vehicles in `RESERVED` or `ASSIGNED`; and its `utilization_pct` is recomputed from the two per §2.5. These three fields are always derived, never directly written by a client.

Because a single operation can touch more than one entity, the system runs cascades to a fixed depth. Assigning a vehicle, for example, mutates the `Vehicle` and then recomputes that vehicle's `Fleet`; settling a return mutates the `ReturnInspection`, then releases the `Vehicle` to `AVAILABLE`, then recomputes that vehicle's `Fleet`. Each entity that a cascade mutates has its own `updated_at` refreshed and its own `version` incremented; a parent's reconciliation is itself a mutation of that parent. Derived counters on a `Fleet` (its `in_use_count` and `utilization_pct`) and derived running totals on a `Subscription` (its `lifetime_billed_cents`) are recomputed as part of the triggering operation, not lazily.

The `Subscription` carries two independent state axes that evolve separately. Its `lifecycle_status` tracks commercial progress through `DRAFT`, `PENDING_DELIVERY`, `ACTIVE`, `RETURN_PENDING`, and `CLOSED`. Its `billing_status` tracks payment standing as either `CURRENT` or `PAST_DUE`. These are orthogonal: a subscription can be `ACTIVE` and `PAST_DUE` at the same time. Operations that read or guard on one axis must not silently mutate the other.

### 2.7. Optimistic Concurrency Control

Two operations reserve a vehicle and therefore guard against a stale view of that vehicle with optimistic concurrency control. Both target the `Vehicle` as the concurrency parent and both require the caller to supply `expected_vehicle_version`, carrying the client's last observed `version` of that vehicle, as a non-optional field.

When a `FleetOperator` assigns a vehicle to a subscription, the request must carry `expected_vehicle_version` matching the target vehicle's current `version`. If another operator has advanced that vehicle's `version` since the client last read it — for instance by reserving the same `AVAILABLE` vehicle for a different subscription, a legitimate supersede — the assignment is rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), so the operator with the stale view cannot overwrite a reservation it never observed. The same rule governs swap approval: approving a swap reserves the target vehicle, so the approval request must carry `expected_vehicle_version` matching the target vehicle's current `version`, and a mismatch is likewise rejected with `ERR_STALE_VEHICLE_VERSION` (HTTP 412), leaving exactly one writer able to reserve that target.

A third operation guards the subscription itself. Early cancellation requires `expected_subscription_version` matching the subscription's current `version`; if the subscription's `version` has advanced since the client last read it, the cancellation is rejected with `ERR_STALE_SUBSCRIPTION_VERSION` (HTTP 412). No other endpoint accepts a version field, and endpoints not named here perform no concurrency check.

### 2.8. The Logical Clock and Scheduled Time

The system runs on a logical clock rather than wall-clock time. At startup the clock reads exactly `2026-04-01T00:00:00Z`, and until it is explicitly set it remains at this default and never falls back to real time. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant; the clock then reports the supplied `now_iso`. Every time-dependent rule in this specification — the elapsed-months math behind a minimum-term check, the proration window of a swap, the instant an invoice is posted, the moment a subscription becomes active — reads this logical clock.

### 2.9. Nested Path Resolution and Referential Existence

The topology is flat: collections such as subscriptions, vehicles, fleets, applicants, billing cycles, invoices, swap requests, return inspections, couriers, delivery slots, and subscription plans are peers addressed from the root. Some read paths nest one collection under another (for example, the vehicles of a fleet, the billing cycles of a subscription, or the damage line items of an inspection). For any such path, the system validates each identifier left to right and rejects the first one that does not resolve to an existing resource with `ERR_NOT_FOUND`. The same `ERR_NOT_FOUND` rule covers any foreign-key reference named in a request body that does not point at an existing resource.

### 2.10. Validation Ordering

When several checks guard a single operation, they are evaluated in a fixed priority order so that the rejection a client receives is deterministic. Authentication comes first: presence and recognition of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`). Next, role authorization against the permission matrix (`ERR_FORBIDDEN_ROLE`). Next, for a member acting on a subscription, resource ownership (`ERR_NOT_RESOURCE_OWNER`). Next, existence of every referenced resource, validated left to right (`ERR_NOT_FOUND`). Next, structural validity of the request body — required fields present, correctly typed, and enum values within their declared sets (`ERR_INVALID_REQUEST`). Next, that the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`).

Only after those generic gates do the domain rules run, themselves ordered: plan-tier match on assignment (`ERR_PLAN_MISMATCH`), then applicant eligibility (`ERR_NOT_ELIGIBLE`), then the past-due block on return and cancellation (`ERR_BILLING_PAST_DUE`), then the minimum-term check on early cancellation (`ERR_MIN_TERM_ELAPSED`), then the vehicle slot-overlap check (`ERR_VEHICLE_SLOT_OVERLAP`), then the courier buffer check (`ERR_COURIER_BUFFER_CONFLICT`), then uniqueness constraints (`ERR_DUPLICATE_VALUE`), then odometer regression on cycle close (`ERR_ODOMETER_REGRESSION`), then the vehicle-version concurrency check (`ERR_STALE_VEHICLE_VERSION`), then the subscription-version concurrency check (`ERR_STALE_SUBSCRIPTION_VERSION`), and finally the no-vehicle-available check on assignment (`ERR_NO_VEHICLE_AVAILABLE`). Where an operation is guarded by several of these, the earlier rule in this ordering surfaces first.

## 3. Business Logic & Workflows

### 3.1. Building the Catalog: Plans and Fleets

Before any subscriber can be served, a `PlatformAdmin` publishes the plan catalog. A `SubscriptionPlan` is created with a `tier` label — one of `ESSENTIAL`, `PLUS`, or `PREMIUM` — which must be unique among plans whose catalog `status` is `ACTIVE`; a collision is rejected with `ERR_DUPLICATE_VALUE`. The plan carries the all-inclusive `monthly_fee_cents` (at least 1), the `included_miles_per_cycle` allowance (zero or more), and an optional `free_buffer_miles` grace amount beyond the included allowance that defaults to 0 when omitted and must be zero or more. Overage pricing is tiered: `overage_tier1_rate_cents` is the per-mile cents for the first block of billable overage miles and must be zero or more, while `overage_tier2_rate_cents` applies beyond that block and must be at least as large as the tier-one rate. The plan also sets `included_swaps_per_term`, the number of free swaps granted before a swap fee applies, which defaults to 0 and must be zero or more; `min_term_months`, the minimum commitment in whole months (at least 1); and `deposit_base_cents`, the base refundable deposit before any eligibility multiplier (zero or more). A plan's `status` is system-managed, defaults to `ACTIVE`, and may also read `RETIRED`.

A `PlatformAdmin` also creates each `Fleet` with a display `name` and a `region_code` such as a state abbreviation. On creation a fleet's derived `total_vehicles`, `in_use_count`, and `utilization_pct` all initialize to 0. Fleets and plans may be read by the platform administrator, fleet operators, and billing administrators; plans may additionally be read by members browsing the catalog, and plan listings may be filtered by catalog `status`. Fleet listings may be filtered by `region_code`.

### 3.2. Stocking Fleets with Vehicles

A `FleetOperator` (or a `PlatformAdmin`) adds a `Vehicle` to a fleet by supplying its `fleet_id`, the `plan_id` tier under which the vehicle is offered, its `vin` (which must be unique across all vehicles — a duplicate is rejected with `ERR_DUPLICATE_VALUE`), a human `model_label`, and its current `odometer_miles` (zero or more). A new vehicle's allocation `status` defaults to `AVAILABLE`, and its `active_subscription_id` defaults to null. Adding a vehicle recomputes the owning fleet's `total_vehicles` and `utilization_pct`.

A vehicle moves through a cyclic allocation lifecycle: `AVAILABLE`, `RESERVED`, `ASSIGNED`, `IN_INSPECTION`, and a side branch of `MAINTENANCE`. The detailed transitions are described in the workflows that drive them. Two standalone fleet operations sit outside the subscription flow. A `FleetOperator` may move a vehicle that is in `ASSIGNED` into `MAINTENANCE`, provided the vehicle's `active_subscription_id` has no delivery slot still in the `SCHEDULED` (non-terminal) state; if such a slot exists the transition is rejected with `ERR_INVALID_STATE` (this is treated as a state-precondition check, not as a slot-overlap or courier-buffer error, and no overlap or buffer geometry is actually computed — the mere existence of a `SCHEDULED` slot for that subscription blocks it). When the vehicle has no `active_subscription_id`, no slot check applies. This transition increments the vehicle's `version`, decrements the owning fleet's `in_use_count`, and recomputes `utilization_pct` (a `MAINTENANCE` vehicle is not in use). When servicing finishes, the operator returns the vehicle from `MAINTENANCE` to `AVAILABLE`, which increments the vehicle's `version`. Attempting either transition from the wrong state is rejected with `ERR_INVALID_STATE`.

Vehicles can be fetched individually or listed and filtered by `fleet_id`, `plan_id`, `active_subscription_id`, or `status`; the vehicles of a specific fleet can also be listed directly with an optional `status` filter.

### 3.3. Applicants and the Eligibility Decision

A prospective subscriber is registered as an `Applicant` — by a `Member` registering themselves or by a `PlatformAdmin` — with a `full_name`, an `email` (unique across applicants; a duplicate is rejected with `ERR_DUPLICATE_VALUE`), a `credit_score` between 300 and 850 inclusive, a `monthly_income_cents` figure (zero or more), and a `history_flag` of `CLEAN`, `MINOR`, or `SEVERE`. Until a decision is made, the computed fields `eligibility_status`, `eligibility_score`, and `required_deposit_cents` are all null.

A `BillingAdmin` (or `PlatformAdmin`) runs the eligibility decision against a named plan by supplying the `plan_id` in the request body. The decision computes a weighted score from three normalized inputs. The credit component normalizes the credit score onto a zero-to-one scale by subtracting 300 and dividing by 550. The income component takes the ratio of the applicant's monthly income to the named plan's `monthly_fee_cents`, caps that ratio at 5, and then divides the capped ratio by 5 to land on a zero-to-one scale. The history component maps `CLEAN` to 1.0, `MINOR` to 0.5, and `SEVERE` to 0.0. The raw score is the credit component weighted at 0.5, plus the income component weighted at 0.3, plus the history component weighted at 0.2. The stored `eligibility_score` is this raw score rounded half-up to four decimal places.

The score then determines both the `eligibility_status` and the `required_deposit_cents`. A score of at least 0.80 yields `APPROVED`, and the required deposit is the plan's `deposit_base_cents` multiplied by one. A score from 0.60 up to but not including 0.80 yields `CONDITIONAL`, and the required deposit is `deposit_base_cents` multiplied by two. A score below 0.60 yields `DECLINED`, and the required deposit is null. The boundaries are inclusive at the lower edge: a score of exactly 0.80 is `APPROVED` at a one-times deposit, exactly 0.60 is `CONDITIONAL` at a two-times deposit, and a score such as 0.5991 is `DECLINED`. The decision endpoint returns the updated applicant.

### 3.4. Opening a Subscription and Reserving a Vehicle

A `Member` (or `PlatformAdmin`) opens a `Subscription` by supplying the `applicant_id` and the `plan_id`. The new subscription starts with `lifecycle_status` of `DRAFT`, `billing_status` of `CURRENT`, `deposit_held_cents` of 0, and `swaps_used` of 0; its `active_vehicle_id`, `cycle_start_iso`, and `term_start_iso` are null at this point, and its derived `lifetime_billed_cents` is 0. Subscriptions can be fetched (returning both state axes and the derived `lifetime_billed_cents`) and listed with filters on `applicant_id`, `plan_id`, `active_vehicle_id`, `lifecycle_status`, or `billing_status`.

Reservation is a `FleetOperator` action that advances the subscription from `DRAFT` to `PENDING_DELIVERY`. The operator supplies the `vehicle_id` to reserve along with `expected_vehicle_version` for the concurrency check (§2.7); both fields are mandatory and a request missing either is rejected with `ERR_INVALID_REQUEST`. The transition requires that the subscription's `lifecycle_status` is `DRAFT`, that the referenced applicant's `eligibility_status` is either `APPROVED` or `CONDITIONAL` (otherwise `ERR_NOT_ELIGIBLE`), that the target vehicle's `status` is `AVAILABLE` (otherwise the target-vehicle state gate rejects with `ERR_INVALID_STATE`), and that the target vehicle's `plan_id` equals the subscription's `plan_id` (otherwise `ERR_PLAN_MISMATCH`; note that this tier match is enforced only on initial assignment, never on a later swap). The target vehicle's `AVAILABLE` state check is treated as a state gate that rejects with `ERR_INVALID_STATE`, but in this operation it is evaluated after the plan-tier match (`ERR_PLAN_MISMATCH`) and the eligibility check (`ERR_NOT_ELIGIBLE`) and before the `expected_vehicle_version` concurrency check; concretely the enforced order for this endpoint is the subscription `DRAFT` state, then plan-tier match, then applicant eligibility, then the target-vehicle `AVAILABLE` state, then the vehicle-version concurrency check. Because the `AVAILABLE` check still precedes the concurrency check, a request that supplies a stale `expected_vehicle_version` for a target vehicle that is no longer `AVAILABLE` — for instance because another operator already reserved it in a legitimate supersede — is rejected with `ERR_INVALID_STATE` rather than `ERR_STALE_VEHICLE_VERSION`. Assignment always targets an explicit `vehicle_id`; there is no pool-draw fallback that selects a vehicle automatically, so this endpoint never reaches the `ERR_NO_VEHICLE_AVAILABLE` condition (which remains in the catalogue but is not surfaced by any current endpoint).

A successful reservation cascades across entities. The target vehicle moves `AVAILABLE → RESERVED`, its `active_subscription_id` is set to this subscription, and its `version` increments by one. The subscription's `active_vehicle_id` is set to the reserved vehicle, and its `deposit_held_cents` is set to the applicant's `required_deposit_cents` captured at this moment. The owning fleet's `in_use_count` increases by one and its `utilization_pct` is recomputed. This is the canonical serialization point that the concurrency check protects: only the writer whose `expected_vehicle_version` still matches wins the `AVAILABLE` vehicle.

### 3.5. Delivery, Activation, and the First Billing Cycle

Before a reserved subscription can become active, delivery logistics must be arranged (see §3.10). Activation is a `FleetOperator` action advancing the subscription from `PENDING_DELIVERY` to `ACTIVE`. It requires that the subscription's `lifecycle_status` is `PENDING_DELIVERY`, that the active vehicle's `status` is `RESERVED`, and that a delivery slot for this subscription with `kind` of `DELIVERY` exists in the `SCHEDULED` state. Failing the state precondition yields `ERR_INVALID_STATE`.

Activation cascades several effects. The active vehicle moves `RESERVED → ASSIGNED` and its `version` increments by one (utilization is unchanged because both `RESERVED` and `ASSIGNED` count as in use). The matching `DELIVERY` delivery slot moves from `SCHEDULED` to `FULFILLED`. The subscription's `term_start_iso` and `cycle_start_iso` are both set to the logical clock's current instant — the term anchor that all minimum-term math reads from. Finally, the system opens the first `BillingCycle` for the subscription in the `OPEN` state, with its `cycle_index` set to 1 and its `odometer_start_miles` captured from the vehicle's current `odometer_miles`.

A `BillingCycle` records the `subscription_id` it bills and the `vehicle_id` whose odometer it measures, its 1-based `cycle_index`, a `cycle_start_iso` opening the half-open window and a `cycle_end_iso` (null until the cycle closes) ending it, an `odometer_start_miles` captured at open, an `odometer_end_miles` reported at close (null until then), a `status` of `OPEN` or `CLOSED`, and an `overage_cents` that is 0 while open and is set at close. Billing cycles can be fetched, listed and filtered by `subscription_id`, `vehicle_id`, or `status`, and the cycles belonging to a particular subscription can be listed directly with an optional `status` filter.

### 3.6. Closing a Cycle and Tiered Mileage Overage

A `BillingAdmin` closes an `OPEN` cycle by reporting the `odometer_end_miles`. The reported reading must be at least the cycle's `odometer_start_miles`; a regression where the end reading is below the start reading is rejected with `ERR_ODOMETER_REGRESSION`. Closing a cycle from any state other than `OPEN` is rejected with `ERR_INVALID_STATE`.

The overage charge is computed from this single cycle's odometer delta, with no carryover from prior cycles. The mileage delta is the reported `odometer_end_miles` minus the `odometer_start_miles`. From that delta the system subtracts, in order, first the plan's `included_miles_per_cycle` and then the plan's `free_buffer_miles`; the billable overage is whatever remains, floored at zero (it is never negative). The billable miles are then split across two rate tiers: the first 200 billable miles fall in tier one, and any billable miles beyond 200 fall in tier two. The overage is the tier-one miles multiplied by the plan's `overage_tier1_rate_cents` plus the tier-two miles multiplied by the plan's `overage_tier2_rate_cents`, rounded half-up to whole cents and stored as the cycle's `overage_cents`. The boundary is exact: a delta equal to the included allowance plus the buffer produces zero billable miles and zero overage, while a delta one mile larger bills exactly one mile.

Closing the cycle posts a `CYCLE` invoice whose `source_ref_id` is the closing cycle's `id` and whose amount is the plan's monthly fee plus this overage, adds that amount to the subscription's `lifetime_billed_cents`, and writes the reported reading back to the vehicle's `odometer_miles`. The cycle's `status` moves from `OPEN` to `CLOSED`, its `cycle_end_iso` is set to the logical clock's current instant, and — if the subscription is still `ACTIVE` — the system opens the next billing cycle with `cycle_index` incremented by one in the `OPEN` state, carrying the same `vehicle_id`, its `cycle_start_iso` set to that same close instant, its `odometer_start_miles` captured from the reported end reading, its `cycle_end_iso` and `odometer_end_miles` null, and its `overage_cents` 0.

### 3.7. Reading Fleet Utilization Under a Counting Basis

Beyond the persisted `utilization_pct`, the platform exposes a what-if utilization projection that lets an operator see how a fleet would read under a different counting basis without mutating the canonical value. The projection accepts an optional `basis` query-parameter selector and returns the chosen `basis` echoed verbatim, the fleet's `total_vehicles`, the `in_use_count` under that basis, and the resulting `utilization_pct`. The assignment-only basis is selected by the exact value `ASSIGNED_ONLY`; any other value, including an omitted `basis`, selects the canonical reservation-inclusive basis and the returned `basis` reads `RESERVATION_INCLUSIVE`. Under the canonical, reservation-inclusive basis, both `RESERVED` and `ASSIGNED` vehicles count as in use, so a fleet of four with one `RESERVED` and one `ASSIGNED` reads `0.5000`. Under the assignment-only basis, only `ASSIGNED` vehicles count, so the identical fleet reads `0.2500` — a different number for the same physical state. As everywhere, an empty fleet reads `0` rather than dividing by zero.

### 3.8. Swaps and Upgrades

A `Member` requests a swap on their own subscription by supplying the `to_vehicle_id` they wish to move into; the system records the request with `status` `REQUESTED` and captures `from_vehicle_id` from the subscription's current `active_vehicle_id` (which may be null if the subscription has no active vehicle). Recording the request performs no `lifecycle_status` check — the requirement that the subscription be `ACTIVE` is enforced only at approval (below), so a request may be filed against a subscription in any lifecycle state. The `to_vehicle_id` must reference an existing vehicle, but its allocation `status` and plan tier are not validated at request time. The request also stores the `subscription_id` it belongs to and reserves the computed fields `swap_fee_applied_cents` and `net_adjustment_cents`, both defaulting to 0 until completion. Swap requests can be fetched and listed with filters on `subscription_id`, `from_vehicle_id`, `to_vehicle_id`, or `status`. A member acting on a swap request for a subscription they do not own is rejected with `ERR_NOT_RESOURCE_OWNER`.

A `FleetOperator` approves a swap, advancing it `REQUESTED → APPROVED`. Approval requires that the swap is in `REQUESTED`, that the subscription's `lifecycle_status` is `ACTIVE`, and that the target vehicle's `status` is `AVAILABLE` (the target may belong to any plan tier — a swap is allowed to upgrade or downgrade). Because approval reserves the target vehicle, the operator must supply `expected_vehicle_version` matching that target's current `version`, and a mismatch is rejected with `ERR_STALE_VEHICLE_VERSION` per §2.7. On approval the target vehicle moves `AVAILABLE → RESERVED`, its `active_subscription_id` is set to the subscription, and its `version` increments by one; the target's fleet has its `in_use_count` increased by one and its `utilization_pct` recomputed. This is a fork: the target is now reserved while the original `from_vehicle` remains `ASSIGNED`, and the two branches rejoin at completion.

A `FleetOperator` completes an approved swap, advancing it `APPROVED → COMPLETED`. Completion requires that the swap is in `APPROVED`, that the `from_vehicle` is `ASSIGNED`, and that the target vehicle is `RESERVED`. Completion first computes the swap fee and the net proration adjustment (§3.9), posts a `SWAP` invoice for the net adjustment, and adds that amount to `lifetime_billed_cents`. The two vehicle branches then diverge: the `from_vehicle` moves `ASSIGNED → IN_INSPECTION`, its `active_subscription_id` is cleared to null, and its `version` increments; the target vehicle moves `RESERVED → ASSIGNED` and its `version` increments. The subscription's `active_vehicle_id` is set to the target, its `plan_id` is updated to the target vehicle's `plan_id`, and its `swaps_used` increases by one. Both affected fleets are recomputed: the `from_vehicle`'s fleet sees that vehicle leave in-use status, while the target's fleet keeps it in use.

A `FleetOperator` may also reject a swap, which always moves it to `REJECTED`. If the swap was still `REQUESTED`, rejection makes no vehicle or fee changes because the target was never reserved. If the swap had already been `APPROVED`, rejection is a compensating action: the target vehicle moves `RESERVED → AVAILABLE`, its `active_subscription_id` is cleared to null, its `version` increments, and the target's fleet has its `in_use_count` decreased by one and `utilization_pct` recomputed — leaving that fleet's `in_use_count` exactly as it stood before the approval. Rejecting from any state other than `REQUESTED` or `APPROVED` is rejected with `ERR_INVALID_STATE`.

### 3.9. Swap Proration and the Swap Fee

The net adjustment posted at swap completion combines a proration delta with a possible swap fee, computed in a pinned order. The proration window is the calendar month of the subscription's `cycle_start_iso`: the cycle-day count is the number of days in that month, and the remaining days are the whole days from the logical clock's current instant to the end of that window (the `cycle_start_iso` plus the cycle-day count), floored to a whole number and never below zero. The credit for the old vehicle is the old plan's `monthly_fee_cents` multiplied by the remaining days divided by the cycle-day count, rounded half-up to whole cents. The charge for the new vehicle is the new plan's `monthly_fee_cents` multiplied by the remaining days divided by the cycle-day count, rounded half-up to whole cents. Each leg is rounded independently to whole cents before they are combined.

The swap fee is gated on the subscription's swap allowance and is evaluated before `swaps_used` is incremented. If the subscription's `swaps_used` is greater than or equal to the originating plan's `included_swaps_per_term`, the `swap_fee_applied_cents` is 7500 cents; otherwise the swap is within the included allowance and `swap_fee_applied_cents` is 0. The `net_adjustment_cents` is the new-vehicle charge minus the old-vehicle credit plus the swap fee. This sum may be negative when a downgrade's credit exceeds the new charge, in which case the posted `SWAP` invoice carries a net credit (a negative `amount_cents`).

### 3.10. Couriers and Delivery Slots

Delivery and return logistics run on couriers and time slots. A `FleetOperator` (or `PlatformAdmin`) registers a `Courier` with a `name`, the `fleet_id` whose vehicles the courier serves, and a `buffer_minutes` travel pad that defaults to 30 and must be zero or more. Couriers can be fetched and listed, filtered by `fleet_id`.

A `FleetOperator` schedules a `DeliverySlot` by supplying the `courier_id` fulfilling it, the `subscription_id` being served, the `kind` (`DELIVERY` or `RETURN`), and the `window_start_iso` and `window_end_iso` bounding the slot, where the end must be strictly after the start. A new slot's `status` defaults to `SCHEDULED` and may later read `FULFILLED` or `CANCELLED`. Slots can be fetched and listed with filters on `courier_id`, `subscription_id`, `kind`, or `status`.

Two geometric rules guard slot scheduling. The first protects the vehicle: a new `DELIVERY` or `RETURN` slot must not overlap an existing non-cancelled slot bound to the same vehicle's active reservation window — operationally, the slots compared are those sharing the new slot's `subscription_id` (the subscription identifies the vehicle reservation served), and the slot's own `vehicle_id` is not a stored or compared field — treated as a half-open interval from start up to but not including end — so two slots that merely touch end-to-start (one ending exactly when the next begins) are allowed, but any true overlap is rejected with `ERR_VEHICLE_SLOT_OVERLAP`. The second protects the courier: a new slot must keep at least the courier's `buffer_minutes` of clear gap from every other non-cancelled slot of the same courier, with each slot treated as a closed interval padded by the buffer on both sides; if two padded closed intervals so much as touch, the new slot is rejected with `ERR_COURIER_BUFFER_CONFLICT`.

### 3.11. Returning a Vehicle and Settling the Deposit

A `Member` initiates a return on their own subscription, advancing it `ACTIVE → RETURN_PENDING`. This requires that the subscription's `lifecycle_status` is `ACTIVE` and that its `billing_status` is `CURRENT`; an attempt while the subscription is `PAST_DUE` is rejected with `ERR_BILLING_PAST_DUE`. Initiating a return does not yet change any vehicle state; the physical return is scheduled separately through a `RETURN` delivery slot.

A `FleetOperator` opens a `ReturnInspection` by supplying the `subscription_id`, the `vehicle_id` being inspected, and the `reported_odometer_miles` at return (zero or more). The inspection starts in `OPEN`. If the inspected vehicle is still `ASSIGNED`, opening the inspection moves it `ASSIGNED → IN_INSPECTION` and increments its `version`. The inspection also carries computed fields that stay at their defaults until settlement: `total_damage_cents`, `deposit_applied_cents`, `deposit_refunded_cents`, and `balance_due_cents`, all initially 0.

While the inspection is `OPEN`, a `FleetOperator` records damage as `DamageLineItem` entries, each supplying the `inspection_id`, a `severity` of `MINOR`, `MODERATE`, or `SEVERE`, an `amount_cents` of at least 1, and an optional free-text `note` that defaults to null. Damage line items can be listed for an inspection. The operator then assesses the `OPEN` inspection, advancing it `OPEN → ASSESSED`; assessment sets `total_damage_cents` to the sum of the `amount_cents` of all damage line items belonging to that inspection.

A `BillingAdmin` settles an `ASSESSED` inspection, advancing it `ASSESSED → SETTLED` and driving the rest of the closure cascade. Settlement requires that the inspection is `ASSESSED`, and that either the subscription's `lifecycle_status` is `RETURN_PENDING`, or the subscription's `active_vehicle_id` is this vehicle and the vehicle is `IN_INSPECTION` (the early-cancel path, §3.12). Settlement runs the deposit waterfall described below, then cascades: the inspected vehicle moves `IN_INSPECTION → AVAILABLE` with its `active_subscription_id` cleared to null and its `version` incremented; the owning fleet's `in_use_count` is decremented and `utilization_pct` recomputed; the subscription's `active_vehicle_id` is cleared to null and, when it was `RETURN_PENDING`, its `lifecycle_status` advances `RETURN_PENDING → CLOSED`. Settlement posts a `RETURN_SETTLEMENT` invoice and adds its amount to `lifetime_billed_cents`.

The deposit waterfall reconciles the held deposit against everything owed. The outstanding amount is the inspection's `total_damage_cents` plus the sum of the subscription's unpaid `CYCLE` invoice amounts plus the sum of its unpaid `EARLY_CANCEL` invoice amounts. Because no endpoint records payment against an individual invoice, every posted `CYCLE` and `EARLY_CANCEL` invoice for the subscription is treated as unpaid at settlement time, so these two sums are simply the full running totals of the subscription's `CYCLE` and `EARLY_CANCEL` invoice `amount_cents` respectively. The `deposit_applied_cents` is the lesser of the subscription's `deposit_held_cents` and that outstanding amount. The `deposit_refunded_cents` is the held deposit minus the applied portion. The `balance_due_cents` is the outstanding amount minus the applied portion, and it is exactly this still-owed remainder that becomes the `RETURN_SETTLEMENT` invoice's amount. All inputs are already whole cents, so no rounding is needed. When nothing is outstanding, the applied portion is 0, the entire deposit is refunded, and the balance due is 0.

### 3.12. Early Cancellation Before the Minimum Term

A `Member` may end an `ACTIVE` subscription early, advancing it `ACTIVE → CLOSED`. Early cancellation requires that the subscription's `lifecycle_status` is `ACTIVE`, that the minimum term has not yet elapsed (the logical clock's current instant is before the `term_start_iso` plus the plan's `min_term_months` whole months; reaching or passing that instant is rejected with `ERR_MIN_TERM_ELAPSED`), and that the supplied `expected_subscription_version` matches the subscription's current `version` (otherwise `ERR_STALE_SUBSCRIPTION_VERSION` per §2.7). Like initiating a return, early cancellation is blocked while the subscription is `PAST_DUE` and is rejected with `ERR_BILLING_PAST_DUE`.

The early-cancellation fee is forward-looking: it charges for the commitment the member is walking away from, ignoring days already used in the current open cycle. The elapsed full months are the whole months between `term_start_iso` and the logical clock's current instant, floored. The remaining full months are the plan's `min_term_months` minus those elapsed months, floored at zero. The fee is the remaining full months multiplied by the plan's `monthly_fee_cents` multiplied by 0.50 (a fifty-percent penalty on the projected unfulfilled months), rounded half-up to whole cents. Early cancellation posts an `EARLY_CANCEL` invoice for this fee and adds it to `lifetime_billed_cents`, then increments the subscription's `version`. The active vehicle moves `ASSIGNED → IN_INSPECTION` and its `version` increments, because the car still has to be physically returned and inspected — a separate inspection is opened and settled afterward, at which point the deposit waterfall runs.

The platform also exposes a non-mutating cancellation quote that lets a member, billing administrator, or platform administrator preview the fee under a chosen `mode` and returns the chosen `mode` and the resulting `fee_cents`. The `mode` is supplied as a query parameter; the chronological mode is selected by the exact value `CHRONOLOGICAL`, while any other value (including an omitted `mode`) is treated as the forward-looking mode and the returned `mode` reads `FORWARD_LOOKING`. The forward-looking mode reproduces the fee charged on an actual early cancellation. A chronological mode reconstructs the actual unbilled accrual instead: it is a flat early-termination fee of `160000` cents plus the plan's `monthly_fee_cents` divided by the current cycle's day count multiplied by the unbilled days remaining in the open cycle, rounded half-up to whole cents. The current cycle's day count is the number of days in the calendar month of the subscription's `cycle_start_iso`, and the unbilled days remaining are the whole days from the logical clock's current instant to that `cycle_start_iso` plus the day count, floored to a whole number and never below zero. For the very same subscription state the two modes deliberately produce different numbers, because one prices the unfulfilled future at half-fee while the other prices the unbilled remainder of the current cycle.

### 3.13. Billing Status: Delinquency and Recovery

The subscription's billing axis is driven directly by a `BillingAdmin` and is independent of the lifecycle axis. The administrator flags delinquency by moving `billing_status` from `CURRENT` to `PAST_DUE`; this requires only that the subscription is currently `CURRENT` and sets `billing_status` to `PAST_DUE`, with no invoice precondition — the operator marks the account directly. The administrator records recovery by moving `billing_status` from `PAST_DUE` to `CURRENT`, which requires that the subscription is currently `PAST_DUE`. Because this axis is independent of `lifecycle_status`, a subscription can be `ACTIVE` and `PAST_DUE` simultaneously, and it is precisely the `PAST_DUE` standing that blocks both initiating a return and early cancellation with `ERR_BILLING_PAST_DUE`.

### 3.14. Invoices

Every billable event posts an immutable `Invoice` recording the `subscription_id` it bills, a `source_kind` describing which workflow produced it — `CYCLE`, `SWAP`, `EARLY_CANCEL`, or `RETURN_SETTLEMENT` — a polymorphic `source_ref_id` pointing at the producing record (a billing cycle, a swap request, the subscription itself, or a return inspection according to the `source_kind`), the net `amount_cents` charged (which may be negative for a net credit on a swap downgrade), and the `posted_at_iso` instant from the logical clock at which it was posted. The subscription's derived `lifetime_billed_cents` is the running sum of the `amount_cents` of every invoice posted for that subscription. Invoices can be fetched, listed and filtered by `subscription_id` or `source_kind`, and the invoices of a particular subscription can be listed directly with an optional `source_kind` filter.

## 4. Endpoint Definitions

Operations that create a new, standalone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and the logical-clock control — return a `200 OK` status code. All endpoints are mounted from the root.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/subscription-plans` | Create a subscription plan tier | PlatformAdmin |
| GET | `/subscription-plans/{id}` | Fetch a plan | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/subscription-plans` | List plans | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/fleets` | Create a fleet | PlatformAdmin |
| GET | `/fleets/{id}` | Fetch a fleet with derived utilization | PlatformAdmin, FleetOperator, BillingAdmin |
| GET | `/fleets` | List fleets | PlatformAdmin, FleetOperator, BillingAdmin |
| GET | `/fleets/{id}/vehicles` | List vehicles of a fleet | PlatformAdmin, FleetOperator, BillingAdmin |
| GET | `/fleets/{id}/utilization` | Computed utilization under a chosen counting basis | PlatformAdmin, FleetOperator, BillingAdmin |
| POST | `/vehicles` | Add a vehicle to a fleet under a plan | FleetOperator, PlatformAdmin |
| GET | `/vehicles/{id}` | Fetch a vehicle | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/vehicles` | List/filter vehicles | PlatformAdmin, FleetOperator, BillingAdmin |
| POST | `/vehicles/{id}/maintenance` | Move an ASSIGNED vehicle into MAINTENANCE | FleetOperator |
| POST | `/vehicles/{id}/maintenance-complete` | Return a MAINTENANCE vehicle to AVAILABLE | FleetOperator |
| POST | `/applicants` | Register an applicant | PlatformAdmin, Member |
| GET | `/applicants/{id}` | Fetch an applicant | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/applicants/{id}/decide-eligibility` | Run eligibility scoring against a named plan | BillingAdmin, PlatformAdmin |
| POST | `/subscriptions` | Create a DRAFT subscription | Member, PlatformAdmin |
| GET | `/subscriptions/{id}` | Fetch a subscription | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/subscriptions` | List/filter subscriptions | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/subscriptions/{id}/assign-vehicle` | Reserve a vehicle for a DRAFT subscription | FleetOperator |
| POST | `/subscriptions/{id}/activate` | Activate after delivery slot fulfilled; opens billing cycle #1 | FleetOperator |
| POST | `/subscriptions/{id}/initiate-return` | Member starts the return flow | Member |
| POST | `/subscriptions/{id}/early-cancel` | Member cancels before min-term | Member |
| GET | `/subscriptions/{id}/cancel-quote` | What-if quote of the cancellation fee under a given mode | Member, BillingAdmin, PlatformAdmin |
| POST | `/subscriptions/{id}/mark-past-due` | Flip billing_status to PAST_DUE | BillingAdmin |
| POST | `/subscriptions/{id}/record-payment` | Flip billing_status back to CURRENT | BillingAdmin |
| GET | `/subscriptions/{id}/billing-cycles` | List billing cycles of a subscription | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/subscriptions/{id}/invoices` | List invoices of a subscription | PlatformAdmin, BillingAdmin, Member |
| GET | `/billing-cycles/{id}` | Fetch a billing cycle | PlatformAdmin, BillingAdmin, Member |
| GET | `/billing-cycles` | List/filter billing cycles | PlatformAdmin, BillingAdmin, Member |
| POST | `/billing-cycles/{id}/close` | Close an OPEN cycle; bills tiered overage; opens the next | BillingAdmin |
| GET | `/invoices/{id}` | Fetch an invoice | PlatformAdmin, BillingAdmin, Member |
| GET | `/invoices` | List/filter invoices | PlatformAdmin, BillingAdmin, Member |
| POST | `/subscriptions/{id}/swap-requests` | Member requests a vehicle swap/upgrade | Member |
| GET | `/swap-requests/{id}` | Fetch a swap request | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/swap-requests` | List/filter swap requests | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/swap-requests/{id}/approve` | Approve a swap; reserve the target vehicle | FleetOperator |
| POST | `/swap-requests/{id}/complete` | Complete an approved swap; prorate and post invoice | FleetOperator |
| POST | `/swap-requests/{id}/reject` | Reject a swap; compensate if it was approved | FleetOperator |
| POST | `/return-inspections` | Open a return inspection for a returning vehicle | FleetOperator |
| GET | `/return-inspections/{id}` | Fetch a return inspection | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/return-inspections` | List/filter return inspections | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/return-inspections/{id}/damage-line-items` | Add a damage line item to an OPEN inspection | FleetOperator |
| GET | `/return-inspections/{id}/damage-line-items` | List damage line items of an inspection | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/return-inspections/{id}/assess` | Assess an OPEN inspection; sum damage line items | FleetOperator |
| POST | `/return-inspections/{id}/settle` | Settle an ASSESSED inspection; run deposit waterfall | BillingAdmin |
| POST | `/couriers` | Register a delivery courier for a fleet | FleetOperator, PlatformAdmin |
| GET | `/couriers/{id}` | Fetch a courier | PlatformAdmin, FleetOperator, BillingAdmin |
| GET | `/couriers` | List couriers | PlatformAdmin, FleetOperator, BillingAdmin |
| POST | `/delivery-slots` | Schedule a delivery/return slot | FleetOperator |
| GET | `/delivery-slots/{id}` | Fetch a delivery slot | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| GET | `/delivery-slots` | List/filter delivery slots | PlatformAdmin, FleetOperator, BillingAdmin, Member |
| POST | `/_clock/set_current_utc` | Set the server logical clock (UTC) | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PLAN_MISMATCH` | 409 |
| `ERR_NOT_ELIGIBLE` | 409 |
| `ERR_BILLING_PAST_DUE` | 409 |
| `ERR_MIN_TERM_ELAPSED` | 409 |
| `ERR_VEHICLE_SLOT_OVERLAP` | 409 |
| `ERR_COURIER_BUFFER_CONFLICT` | 409 |
| `ERR_DUPLICATE_VALUE` | 409 |
| `ERR_ODOMETER_REGRESSION` | 422 |
| `ERR_STALE_VEHICLE_VERSION` | 412 |
| `ERR_STALE_SUBSCRIPTION_VERSION` | 412 |
| `ERR_NO_VEHICLE_AVAILABLE` | 409 |
| `ERR_INVALID_PAGINATION` | 422 |

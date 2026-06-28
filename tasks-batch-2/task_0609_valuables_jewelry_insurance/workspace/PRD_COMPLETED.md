# Valuables & Jewelry Insurance API — Product Requirements Document

## 1. Introduction

Insuring fine jewelry, watches, and loose stones demands a discipline that ordinary property coverage does not: each piece must be individually appraised, individually priced against the theft-and-loss exposure of where it is kept, and individually re-valued as precious-metal and stone markets drift upward. This document specifies the Valuables & Jewelry Insurance API, a Jewelers-Mutual-style platform that carries a scheduled-item book from the first quote through binding, premium collection, mid-term amendment, loss adjudication, and repair-network settlement.

The platform is built around two financial engines that operate side by side. A **pricing engine** computes per-item annual premiums from zip-level risk bands, category loadings, value tiers, coverage breadth, and deductible elections, then aggregates them into a policy premium under a strictly pinned rounding order. A **ledger-reconciliation engine** keeps each policy's insured value and premium continuously consistent as items are revalued by an inflation guard, added or removed by endorsement, or written off by total-loss settlement. Layered over both is a logical clock that the platform — never wall-clock time — uses to expire appraisals, lapse delinquent policies, and trigger annual revaluation epochs.

The actors are deliberately specialized. An **Underwriter** prices and binds coverage and maintains the rate and repair-shop catalogs; a **Policyholder** owns their policies and claims, pays premium, and supplies claim information; a **ClaimsAdjuster** runs the adjudication loop; an **Appraiser** files independent valuations; and a network **RepairShop** acts on the repair orders assigned to it. The sections below define the global contract every endpoint shares (§2), the business workflows where the substantive rules live (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. The substantive business logic — state transitions, pricing math, settlement formulas, validation ordering — is developed in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted for the targeted operation — or whose user does not own a resource they are required to own — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The platform recognizes exactly five roles, spelled precisely as follows: `Underwriter`, `ClaimsAdjuster`, `Appraiser`, `Policyholder`, and `RepairShop`.

Three of these roles are **opaque** operator identities. When `X-User-Role` is `Underwriter`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. When `X-User-Role` is `ClaimsAdjuster`, `X-User-ID` is likewise an opaque adjudicator identifier with no entity backing. When `X-User-Role` is `Appraiser`, `X-User-ID` is an opaque appraiser identifier; the server records it as the `appraiser_id` of any Appraisal that role files, but it is not matched against any entity's `id`.

Two roles are **entity-backed**. When `X-User-Role` is `Policyholder`, `X-User-ID` is the `id` of the acting Policyholder; ownership checks on any resource that references a Policyholder compare that resource's owning policyholder to `X-User-ID`. A Policyholder may read and act only on policies, scheduled items, claims, endorsements, repair orders, and payments that belong to a policy whose `policyholder_id` is their own `X-User-ID`. When `X-User-Role` is `RepairShop`, `X-User-ID` is the `id` of the acting RepairShop; ownership checks on a repair order compare its `repair_shop_id` to `X-User-ID`, so a shop may accept, complete, or deem-total-loss only the repair orders assigned to it.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of resources returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of leading resources and defaults to 0. Unless an endpoint states otherwise, list results are sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Most resources in this system are mutable and carry a uniform set of system-managed fields. Each such resource exposes an `id` — a server-minted UUID with no type prefix — alongside `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and a `version` integer. The `version` begins at its initial value when the resource is created and increments by one on every mutation; `updated_at` is refreshed on every mutation in lockstep. These mutable resources are Policyholder, RepairShop, Policy, ScheduledItem, Appraisal, Endorsement, Claim, RepairOrder, and PremiumPayment.

One entity is an exception. A RiskZone is an immutable rate row: it carries only `id` and `created_at`, and it has neither an `updated_at` nor a `version` field. Wherever this document speaks of version increments or `updated_at` refreshes, those mechanics never apply to RiskZone.

A note on identifiers used throughout: foreign keys such as `policyholder_id`, `policy_id`, `scheduled_item_id`, `appraisal_id`, `target_item_id`, `claim_id`, `repair_shop_id`, and `appraiser_id` are all UUID strings referencing the `id` of another resource. They are never exposed to the client as schema declarations; they surface only through the workflow narratives in §3 and through the request payloads each operation expects.

### 2.5. Monetary Values, Precision, and Rounding

Every monetary amount in the system is an integer count of cents — there are no fractional-cent fields and no floating-point currency in stored state. Wherever a calculation produces a non-integer intermediate, the result is committed to whole cents using **round half up**, except where a specific step is explicitly directed to truncate downward (floor). The two places that floor rather than round are called out where they occur in §3: the halving of a deductible for an in-network partial-damage repair, and the integer count of completed policy years used by revaluation. Percentages such as `inflation_guard_pct` are carried as decimals (for example, 0.04 represents four percent) and participate in arithmetic at full precision; only the final committed cent figure is rounded.

### 2.6. The Logical Clock and Time-Driven Reconciliation

The platform keeps a single logical clock that is the sole source of "now." On server startup the clock reads exactly `2026-01-01T00:00:00Z`; before any client sets it, every time comparison uses that default, and the system never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied absolute ISO-8601 UTC instant via the `to_iso8601` field, and is available to `Underwriter` and `ClaimsAdjuster` operators.

Advancing the clock is not a passive act: it fires every time-driven transition that the new instant has made due. Appraisals whose validity window has closed move from `VALID` to `EXPIRED`. Policies that are already `PAST_DUE` and have sat past their grace window move from `ACTIVE` to `LAPSED`; a policy whose `billing_status` is `PAID` never lapses on a clock advance, so advances driven purely by revaluation leave a paid policy's coverage untouched. Active scheduled items on inflation-guarded policies are revalued once for each full policy year that has newly elapsed. These cascades and their exact thresholds are specified in §3; this subsection establishes only that they are triggered by clock advance and computed against the logical clock.

### 2.7. Hierarchical Consistency and Automatic Propagation

The entity tree is rooted at the Policy, which owns its scheduled items, endorsements, claims, and premium payments; a claim in turn owns its repair order. Many operations on a child resource ripple upward or downward without an explicit client call on the affected resource. Binding a policy activates its pending items; applying an endorsement recomputes the policy's insured value and premium; settling a total-loss claim removes the item and again recomputes the policy aggregates; a repair order reaching closure settles its parent claim and unlocks the underlying item. Whenever the server mutates a resource as part of such a cascade, that resource's `updated_at` is refreshed and its `version` increments exactly as it would for a direct mutation. The precise cascades — which entity changes, in what order, and under what precondition — are detailed in the §3 workflow that owns each operation.

### 2.8. Nested Resource Retrieval and Existence Ordering

Several paths embed more than one resource identifier — a claim lives beneath its policy, a repair order beneath its claim. For any such request, the server validates the chain left to right and rejects with `ERR_NOT_FOUND` (HTTP 404) at the first path segment that names a resource which does not exist. A claim operation under a non-existent policy fails on the policy before the claim is ever consulted. This left-to-right existence check (priority three among the global validations) runs after authentication and authorization but before any body-level or state-level rule.

### 2.9. Optimistic Concurrency Control

Two operations are guarded by optimistic concurrency control, because each legitimately supersedes financial state that a stale client could otherwise overwrite.

Applying a draft endorsement is guarded on the parent **Policy**. The apply request must carry `expected_policy_version`, a non-optional field carrying the policy `version` the client last observed. If that value does not match the policy's current `version` — because another endorsement or a premium payment has advanced the policy since the client read it — the apply is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents an endorsement from recomputing `premium_delta_cents` against an outdated insured-value-and-premium base.

Approving a claim is guarded on the parent **Claim**. The approve request must carry `expected_claim_version`, a non-optional field carrying the claim `version` the client last observed. If a request-info or provide-info cycle has advanced the claim's `version` since the adjuster read it, the approve is rejected with `ERR_STALE_VERSION` (HTTP 412), so the adjuster never settles against a claim view that has since moved on.

No other endpoint accepts a version field; operations not named here perform their mutation without an OCC check.

### 2.10. Validation Ordering

When several rules could reject one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization including ownership (`ERR_FORBIDDEN`), then left-to-right existence of every path resource (`ERR_NOT_FOUND`), then body well-formedness — required fields present, enum values in range, monetary amounts strictly greater than zero, and ZIP codes exactly five digits (`ERR_INVALID_REQUEST`, HTTP 422). Only after these four global gates pass does the system evaluate state legality (`ERR_INVALID_STATE`, HTTP 409) and then the operation-specific business rules described in §3. Where an operation carries an OCC field, the stale-version check (`ERR_STALE_VERSION`) is the concurrency guard layered over that operation as described in §2.9. Throughout §3, each business rule is paired with the exact error it raises; this subsection fixes only their relative ordering.

## 3. Business Logic & Workflows

### 3.1. Catalog Foundations: Policyholders, Risk Zones, Repair Shops, and Appraisals

Before any coverage exists, an `Underwriter` populates the supporting catalogs. A **Policyholder** is registered with an `email` (unique across policyholders and used as their login identity), a `full_name`, and a five-digit `residence_zip`. Every policyholder is born in `status` `ACTIVE`, which is the only status a policyholder ever holds — there is no suspension flow for the insured principal.

The rating catalog is a set of **RiskZone** rows, each created by an `Underwriter` for a three-digit ZIP prefix. A risk zone carries a `zip_prefix` (the unique three-digit prefix it covers), a `risk_band` drawn from `LOW`, `MODERATE`, `HIGH`, or `SEVERE`, a `rate_per_thousand_cents` giving the annual base premium in cents per one thousand dollars of insured value, and a `catastrophe_loaded` boolean that defaults to false and, when true, marks the zone as carrying a flat catastrophe surcharge. Risk zones are the immutable rate rows described in §2.4.

The repair network is a set of **RepairShop** records, each registered by an `Underwriter` with a `name`, a five-digit `service_zip`, and an `in_network` flag that defaults to true. A shop's `status` defaults to `ACTIVE` and may later be moved to `SUSPENDED`; a suspended shop cannot receive or accept new repair orders. Whether a shop is `in_network` matters at settlement time, because an in-network shop earns the policyholder a reduced deductible on partial-damage repairs.

Independent valuations live in **Appraisal** records. An `Appraiser` or an `Underwriter` files an appraisal for a given `policyholder_id`, supplying an `appraised_value_cents` (which must be greater than zero), an `effective_date_iso` recording when the appraisal was performed against the logical clock, and an optional `valid_months` that defaults to 36. The filing operator's identity is recorded as the `appraiser_id` from the acting `X-User-ID`. An appraisal opens in `status` `VALID` and remains valid over the half-open window beginning at `effective_date_iso` and ending the instant `valid_months` later — valid for instants at or after the effective date and strictly before the effective date plus `valid_months`. When the logical clock reaches or passes that window end, a clock advance moves the appraisal from `VALID` to `EXPIRED`. When a newer valid appraisal is attached to the same scheduled item, the prior one moves from `VALID` to `SUPERSEDED`; this supersession fires at the moment a scheduled item is created with that newer appraisal attached, and "the same scheduled item" is resolved as any earlier scheduled item on the same policy carrying the identical `description`, whose previously attached `VALID` appraisal is then flipped to `SUPERSEDED`. Appraisals can be listed and filtered by `policyholder_id`.

### 3.2. Quoting and Scheduling Items

An `Underwriter` opens coverage by creating a **Policy** for a `policyholder_id`. The quote fixes the coverage shape through several elections. The `coverage_type` is either `ALL_RISK`, which covers any cause of loss that is not excluded, or `NAMED_PERIL`, which covers only the causes enumerated in `listed_perils` — a subset of `THEFT`, `FIRE`, `FLOOD`, `ACCIDENTAL_DAMAGE`, and `MYSTERIOUS_DISAPPEARANCE` that defaults to empty and is ignored entirely for `ALL_RISK`. The `valuation_basis` is either `AGREED_VALUE` or `REPLACEMENT_COST` and selects which settlement algorithm a future claim follows. The `deductible_option` is one of `ZERO`, `LOW`, `STANDARD`, or `HIGH`. A `worldwide_coverage` boolean defaults to false and, when true, extends coverage to losses outside the residence country. Inflation handling is set by `inflation_guard_mode`, one of `NONE`, `SIMPLE`, or `COMPOUND`, paired with an `inflation_guard_pct` that defaults to zero and stays zero whenever the mode is `NONE`. A freshly created policy opens with `coverage_status` `QUOTED` and `billing_status` `UNBILLED`. Its computed fields — `deductible_cents`, `total_insured_value_cents`, and `annual_premium_cents` — are not yet resolved at quote time. Policies can be listed and filtered by `policyholder_id`.

Into a quoted policy the `Underwriter` schedules items. A **ScheduledItem** is created under its policy and carries a `description`, a `category` drawn from `RING`, `NECKLACE`, `WATCH`, `LOOSE_STONE`, or `OTHER`, a five-digit `location_zip` naming where the item is normally kept, and a `scheduled_value_cents` that must be greater than zero. The item may also reference an `appraisal_id` backing that scheduled value. On creation the item's `policy_id` is set from the path policy and its `item_status` is `PENDING`. Its `current_value_cents` is not yet populated and its `revaluation_epoch` begins at zero. Creating a scheduled item is permitted while the policy is `QUOTED` (the item will activate at bind) and while it is `BOUND` or `ACTIVE` (the pending item then awaits an add-item endorsement to activate it); creating one against a `CANCELLED` policy is rejected with `ERR_INVALID_STATE`. Scheduled items can be listed and filtered by `policy_id` or by `appraisal_id`.

### 3.3. Binding Coverage and Resolving the Deductible

Binding is the transition that turns a quote into live coverage, performed by an `Underwriter` and moving `coverage_status` from `QUOTED` to `BOUND`. Several preconditions guard it, each with its own rejection. The policy must currently be `QUOTED`, or the bind is rejected with `ERR_INVALID_STATE`. The policy must hold at least one `PENDING` scheduled item, or the bind is rejected with `ERR_NO_SCHEDULED_ITEMS`. For a `NAMED_PERIL` policy, `listed_perils` must be non-empty, or the bind is rejected with `ERR_NAMED_PERIL_REQUIRES_PERILS`. Finally, every scheduled item whose `scheduled_value_cents` exceeds ten thousand dollars must carry a non-null `appraisal_id` pointing to a currently valid appraisal, or the bind is rejected with `ERR_APPRAISAL_REQUIRED`. This appraisal threshold is strict: an item valued at exactly ten thousand dollars needs no appraisal, while an item valued at ten thousand dollars and one cent does.

When the preconditions hold, binding performs a cascade. The deductible is resolved from `deductible_option` into `deductible_cents`: `ZERO` resolves to zero cents, `LOW` to twenty-five thousand cents, `STANDARD` to fifty thousand cents, and `HIGH` to one hundred thousand cents. Each `PENDING` scheduled item transitions to `ACTIVE`, its `current_value_cents` is set equal to its `scheduled_value_cents`, and its `revaluation_epoch` is set to zero. The policy's `total_insured_value_cents` and `annual_premium_cents` are then recomputed (per the pricing rules in §3.4). The `bound_at_iso` field is stamped with the current logical clock, anchoring all future revaluation epochs. Binding increments the policy's `version` by one.

### 3.4. Pricing: Per-Item Premium and Policy Aggregation

The premium for a single active scheduled item is built from several factors that interact non-linearly. Begin with a base figure: divide the item's `current_value_cents` by one hundred thousand to obtain the insured value expressed in thousands of dollars, then multiply by the `rate_per_thousand_cents` of the risk zone whose `zip_prefix` equals the first three digits of the item's `location_zip`; if no risk zone matches that prefix, the moderate default band is used, whose default `rate_per_thousand_cents` is zero and which is not catastrophe-loaded (so an unmatched item contributes only the per-item minimum, with no catastrophe surcharge). Multiply that base by the **category multiplier** for the item's `category`: `RING` contributes a factor of 1.00, `NECKLACE` 1.05, `WATCH` 1.20, `LOOSE_STONE` 1.40, and `OTHER` 1.10. Multiply again by the **coverage multiplier**: an `ALL_RISK` policy applies a factor of 1.30, while a `NAMED_PERIL` policy applies 1.00. Multiply by the **value-tier multiplier**, which loads high-value pieces: an item whose `current_value_cents` is at most five thousand dollars takes a factor of 1.00; an item above five thousand dollars but at most twenty thousand dollars takes 1.10; an item above twenty thousand dollars takes 1.25. Multiply finally by the **deductible credit** for the policy's `deductible_option`: `ZERO` carries 1.10 (electing no deductible costs more), `LOW` carries 1.00, `STANDARD` carries 0.92, and `HIGH` carries 0.85.

After all five multiplicative factors are applied, round the product half up to whole cents, then take the greater of that figure and the twenty-five-hundred-cent per-item minimum (twenty-five dollars). Only then, after the rounding and the floor, add the flat catastrophe surcharge: if the item's matched risk zone has `catastrophe_loaded` true, add fifteen hundred cents (fifteen dollars); otherwise add nothing. The result is that item's annual premium contribution.

The policy's `annual_premium_cents` aggregates these per-item figures under a rounding order that is pinned and must not be reordered. Each item premium is rounded to whole cents first, inside the per-item computation above, and only the already-rounded per-item figures are summed — this is round-then-sum, explicitly not sum-the-raw-figures-then-round. The aggregation covers every scheduled item whose `item_status` is `ACTIVE` or `SUSPENDED`; items that are `PENDING` or `REMOVED` are excluded. The policy's `total_insured_value_cents` is the sum of `current_value_cents` over those same `ACTIVE`-or-`SUSPENDED` items. Both aggregates are recomputed on bind, on every applied endorsement, and whenever an item is removed.

### 3.5. Inflation-Guard Revaluation

Inflation-guarded policies revalue their items as policy years elapse. When the clock advances, for each scheduled item whose `item_status` is `ACTIVE` on a policy whose `inflation_guard_mode` is not `NONE`, the system computes the number of completed policy years since `bound_at_iso` — the count of whole twelve-month periods elapsed, floored to an integer — and treats that count as the item's new `revaluation_epoch`. The epoch count is capped at ten; revaluation never applies more than ten cycles to any item.

The revalued `current_value_cents` depends on the guard mode, and the two modes diverge once two or more epochs have elapsed. Under `SIMPLE` mode the value is the item's original `scheduled_value_cents` multiplied by one plus the product of `inflation_guard_pct` and the epoch count — linear growth on the original scheduled value — with the result rounded half up to whole cents. Under `COMPOUND` mode the value is the original `scheduled_value_cents` multiplied by the quantity one plus `inflation_guard_pct`, raised to the power of the epoch count — annual compounding — again rounded half up to whole cents. Because revaluation changes `current_value_cents`, and `current_value_cents` feeds both the policy aggregates and any future settlement, a revaluation that lands a new epoch also feeds back into the policy's insured value. The `revaluation_epoch` recorded on the item is what later settlement reads to apply replacement-cost depreciation.

### 3.6. Premium Collection, Billing, and the Coverage-Billing Interplay

A policy carries two status dimensions that evolve independently: `coverage_status`, the coverage lifecycle, and `billing_status`, the premium-payment dimension. Premium becomes payable only after bind. A `Policyholder` (or an `Underwriter` acting for them) records a **PremiumPayment** against the policy, supplying an `amount_cents`; the payment is created in `status` `RECEIVED` with its `policy_id` set from the path policy. Two preconditions guard the payment: the policy's `coverage_status` must be one of `BOUND`, `ACTIVE`, or `LAPSED`, or the payment is rejected with `ERR_POLICY_NOT_BILLABLE`; and the tendered `amount_cents` must be at least the policy's `annual_premium_cents`, or it is rejected with `ERR_PREMIUM_UNDERPAID`.

A sufficient payment drives `billing_status` from `UNBILLED` to `PAID`, clears any `past_due_since` anchor back to null, and increments the policy's `version`. Crucially, the billing transition can bubble into coverage: a policy that is `BOUND` automatically advances its `coverage_status` to `ACTIVE` the moment `billing_status` becomes `PAID`, since active coverage requires a paid premium. A policy that is `LAPSED` may also bubble back to `ACTIVE` on payment, but only within the reinstatement window described below.

The billing dimension can also regress. An `Underwriter` may reverse a previously received payment; reversal requires the payment to be in `status` `RECEIVED` (otherwise `ERR_INVALID_STATE`), sets that payment's `status` to `REVERSED`, drives `billing_status` from `PAID` to `PAST_DUE`, and stamps `past_due_since` with the current clock. A policy enters `PAST_DUE` only through an explicit reversal — never automatically on a clock advance — which is exactly why a paid policy's coverage stays stable across revaluation-driven clock advances. Once `PAST_DUE`, the policy is again billable: a fresh sufficient payment (`amount_cents` at least `annual_premium_cents`) returns `billing_status` to `PAID` and increments `version`.

### 3.7. Lapse and Reinstatement Windows

Delinquency is bounded by two thirty-day windows, both measured against the logical clock and anchored at `past_due_since`. A policy that is `ACTIVE` and `PAST_DUE` lapses when the clock has advanced at least thirty days beyond the instant it entered `PAST_DUE`; on that clock advance the system moves `coverage_status` from `ACTIVE` to `LAPSED`. Only a `PAST_DUE` policy can lapse; a `PAID` policy never lapses on a clock advance. Lapsing does not disturb claims already open on the policy, but no new claim may be filed once coverage is `LAPSED`.

Reinstatement reverses a lapse within its own thirty-day window. When a `LAPSED` policy receives a sufficient payment and the clock is still within thirty days of the lapse anchor, the payment both sets `billing_status` to `PAID` and bubbles `coverage_status` from `LAPSED` back to `ACTIVE`. A payment that arrives after the reinstatement window closes still settles the billing dimension but leaves the policy `LAPSED`.

### 3.8. Cancellation

An `Underwriter` or the owning `Policyholder` may cancel a policy. Cancellation is available from `QUOTED`, `BOUND`, or `ACTIVE`, and `CANCELLED` is terminal. The single guard is that no claim on the policy may be in `UNDER_REVIEW`, `INFO_REQUESTED`, or `APPROVED`; if any open claim sits in one of those statuses, the cancel is rejected with `ERR_OPEN_CLAIM_BLOCKS_CANCEL`. When cancellation proceeds, `coverage_status` becomes `CANCELLED` and every scheduled item on the policy transitions to `item_status` `REMOVED`.

### 3.9. Mid-Term Amendments: Endorsements

Coverage changes mid-term through **Endorsement** records, drafted and applied by an `Underwriter`. An endorsement is created in `status` `DRAFT`, with its `policy_id` set from the path policy, and carries an `endorsement_type` of `ADD_ITEM`, `REMOVE_ITEM`, or `CHANGE_DEDUCTIBLE`. An add or remove endorsement names a `target_item_id`; a change-deductible endorsement instead names a `new_deductible_option` (one of `ZERO`, `LOW`, `STANDARD`, `HIGH`) and leaves the target null. A draft endorsement may be rejected by an `Underwriter`, which moves it to the terminal `REJECTED` status and leaves the policy's `annual_premium_cents` untouched — the reject is a compensating no-op, so a draft followed by a reject leaves the premium exactly at its pre-draft value. Endorsements can be listed and filtered by `policy_id` or by `target_item_id`.

Applying a draft endorsement, also an `Underwriter` action, moves it from `DRAFT` to the terminal `APPLIED` status and mutates the policy. Several preconditions guard the apply, evaluated after the global gates of §2.10. The parent policy's `coverage_status` must be `BOUND` or `ACTIVE`, or the apply is rejected with `ERR_INVALID_STATE`. The optimistic-concurrency guard of §2.9 then applies: the request's `expected_policy_version` must match the policy's current `version`, or the apply is rejected with `ERR_STALE_VERSION`. For a `REMOVE_ITEM` endorsement, the target item must not be locked by an open claim (an item suspended by an open claim), or the apply is rejected with `ERR_ITEM_LOCKED_BY_CLAIM`. For a `CHANGE_DEDUCTIBLE` endorsement, the `new_deductible_option` must differ from the policy's current option, or the apply is rejected with `ERR_NO_OP_ENDORSEMENT`.

On a successful apply the system computes the signed `premium_delta_cents` (per §3.10), enacts the structural change, recomputes the policy aggregates, applies the delta to `annual_premium_cents`, and increments the policy's `version`. An `ADD_ITEM` apply transitions its target scheduled item from `PENDING` to `ACTIVE`. A `REMOVE_ITEM` apply transitions its target item from `ACTIVE` to `REMOVED`. A `CHANGE_DEDUCTIBLE` apply updates the policy's `deductible_option` and re-resolves `deductible_cents`. In every case the policy's `total_insured_value_cents` and `annual_premium_cents` are recomputed against the post-change item set.

### 3.10. Endorsement Proration

The `premium_delta_cents` an endorsement applies is prorated over the portion of the policy year that remains. Measure the whole days elapsed since `bound_at_iso` against the logical clock, subtract that from the three-hundred-sixty-five-day policy year, and take the greater of that difference and zero to obtain the days remaining; the proration fraction is the days remaining divided by three hundred sixty-five. For an `ADD_ITEM` endorsement, compute the target item's full annual premium (per §3.4) and set `premium_delta_cents` to that figure multiplied by the proration fraction, rounded half up. For a `REMOVE_ITEM` endorsement, compute the full annual premium the target item had been contributing and set `premium_delta_cents` to the negative of that figure multiplied by the proration fraction, rounded half up. For a `CHANGE_DEDUCTIBLE` endorsement, compute the policy's full annual premium under the old `deductible_option` and again under the `new_deductible_option`, and set `premium_delta_cents` to the difference (new total minus old total) multiplied by the proration fraction, rounded half up. The signed delta is what mutates `annual_premium_cents` on apply.

### 3.11. Filing and Adjudicating Claims

A loss is reported as a **Claim** filed by a `Policyholder` or a `ClaimsAdjuster` against an active policy. Filing requires the parent policy's `coverage_status` to be `ACTIVE`, or the file is rejected with `ERR_POLICY_NOT_ACTIVE`. The claim names a `scheduled_item_id`, a `peril` (one of `THEFT`, `FIRE`, `FLOOD`, `ACCIDENTAL_DAMAGE`, `MYSTERIOUS_DISAPPEARANCE`), a `loss_type` of either `TOTAL_LOSS` or `PARTIAL_DAMAGE`, and a `claimed_amount_cents` (the amount asserted for a partial-damage loss; not used in the settlement of a total loss, which settles against item value, but still a required field on every filing — `claimed_amount_cents` must always be present and strictly greater than zero regardless of `loss_type`, or the file is rejected with `ERR_INVALID_REQUEST`). The claim may also carry a `loss_zip` naming where the loss occurred and an `occurred_outside_country` boolean that defaults to false. On filing, the claim opens in `status` `FNOL` with its `policy_id` set from the path policy, its `settlement_cents` and `deductible_applied_cents` at zero, and its `info_request_count` at zero. Claims can be listed and filtered by `policy_id` or by `scheduled_item_id`.

A `ClaimsAdjuster` begins adjudication by starting review, which moves the claim from `FNOL` to `UNDER_REVIEW`. Starting review enforces three checks. The parent policy must be `ACTIVE`, or it is rejected with `ERR_POLICY_NOT_ACTIVE`. For a `NAMED_PERIL` policy, the claim's `peril` must be among the policy's `listed_perils`, or it is rejected with `ERR_PERIL_NOT_COVERED`. If `occurred_outside_country` is true, the policy's `worldwide_coverage` must be true, or it is rejected with `ERR_WORLDWIDE_NOT_COVERED`. When review begins, the referenced scheduled item transitions from `ACTIVE` to `SUSPENDED`, locking it for the duration of the claim.

Adjudication carries a bounded cyclic loop. From `UNDER_REVIEW` the adjuster may request more information, moving the claim to `INFO_REQUESTED` and incrementing `info_request_count` by one; this is permitted only while `info_request_count` is below the limit of two, and a third request is rejected with `ERR_INFO_REQUEST_LIMIT`. The owning `Policyholder` answers by providing information, moving the claim from `INFO_REQUESTED` back to `UNDER_REVIEW`. The loop may repeat up to the limit, letting the adjuster gather facts before deciding.

From `UNDER_REVIEW` the adjuster either denies or approves. Denial moves the claim to the terminal `DENIED` status, unlocks the referenced item by returning it from `SUSPENDED` to `ACTIVE`, and leaves `settlement_cents` at zero; a claim sitting in `INFO_REQUESTED` may likewise be denied, again unlocking the item. Approval moves the claim from `UNDER_REVIEW` to `APPROVED` and computes the payout. Approval is OCC-guarded as described in §2.9: the request's `expected_claim_version` must match the claim's current `version`, or it is rejected with `ERR_STALE_VERSION`. On approval the system computes `settlement_cents` and `deductible_applied_cents` per the valuation-basis variant in §3.12; a total-loss claim is then ready for direct settlement, while a partial-damage claim awaits a repair order.

### 3.12. Settlement Calculation

The payout uses the referenced item's `current_value_cents` — the inflation-guard-adjusted value — and the policy's `deductible_cents`. First determine the effective deductible: for a `PARTIAL_DAMAGE` claim whose repair is handled by an in-network shop (the assigned `RepairShop` has `in_network` true), the deductible is halved, taking the floor of dividing `deductible_cents` by two; in every other case the effective deductible is the full `deductible_cents`. Next determine the gross. For a `TOTAL_LOSS` claim the gross is the full insured value of the item; for a `PARTIAL_DAMAGE` claim the gross is the lesser of `claimed_amount_cents` and the item's `current_value_cents`. The `settlement_cents` is then the greater of zero and the gross minus the effective deductible, and `deductible_applied_cents` is the gross minus that settlement — the portion actually withheld, which never exceeds the deductible.

The gross for a total loss depends on the policy's `valuation_basis`. Under `AGREED_VALUE`, the gross is the item's `current_value_cents` in full, with no depreciation — the agreed value is paid regardless of market movement or how many revaluation epochs have passed. Under `REPLACEMENT_COST`, the gross is computed by depreciating the replacement figure: take the lesser of the item's `current_value_cents` and its original `scheduled_value_cents` (the replacement cap factor is one, so replacement gross never exceeds the scheduled value), multiply by one minus the product of five percent and the item's `revaluation_epoch`, and round the result half up to whole cents. Because replacement reimburses depreciated cost-to-replace rather than the agreed sum, the two bases produce identical figures only while `revaluation_epoch` is zero and diverge once the item has been revalued at least once.

### 3.13. Settling and Closing Claims

A total-loss claim settles directly. A `ClaimsAdjuster` settles an `APPROVED` claim, moving it to `SETTLED`; this direct settle is available only when `loss_type` is `TOTAL_LOSS`, and attempting it on a partial-damage claim is rejected with `ERR_PARTIAL_REQUIRES_REPAIR` because partial losses settle through repair-order closure. On a total-loss settle the referenced scheduled item transitions from `SUSPENDED` to `REMOVED`, and the policy's `total_insured_value_cents` and `annual_premium_cents` are recomputed against the reduced item set. Once a claim reaches `SETTLED`, the adjuster closes it, moving it from `SETTLED` to the terminal `CLOSED` status.

The interaction between a claim's lifecycle and its item is worth restating, because it is the serialization point between adjudication and amendment. While a claim referencing an item is open — that is, while review has suspended the item — the item is locked: it cannot be the target of a remove-item endorsement, and an attempt to remove it is rejected with `ERR_ITEM_LOCKED_BY_CLAIM`. When the referencing claim reaches a terminal disposition without a total loss (denied, or settled and closed on a partial repair), the item is unlocked back to `ACTIVE`. When a total-loss claim settles, the item is instead removed from coverage and excluded from all future insured-value aggregation and revaluation.

### 3.14. The Repair Path for Partial Losses

A partial-damage claim that has been approved is serviced through a **RepairOrder**. A `ClaimsAdjuster` assigns a repair order to the approved claim, naming the `repair_shop_id` of the servicing shop; the claim must currently be `APPROVED` and its `loss_type` must be `PARTIAL_DAMAGE`, or the assign is rejected with `ERR_INVALID_STATE`. Because the servicing shop's `in_network` flag is only known at assign, assigning recomputes the claim's `settlement_cents` and `deductible_applied_cents` per §3.12 against the now-known shop — halving the effective deductible when that shop is in-network — and bumps the claim's `version`; the order then opens in `status` `ASSIGNED`, its `claim_id` is set from the path claim, and its `authorized_amount_cents` is set to that recomputed `settlement_cents` — the cap the insurer authorizes for the repair. The assigned shop must be `ACTIVE`; assigning to a suspended shop is rejected with `ERR_SHOP_SUSPENDED`. Repair orders can be listed and filtered by `claim_id` or by `repair_shop_id`.

The assigned `RepairShop` accepts the order, moving it from `ASSIGNED` to `IN_PROGRESS`; acceptance again requires the shop to be `ACTIVE`, failing with `ERR_SHOP_SUSPENDED` otherwise. From `IN_PROGRESS` the order forks two ways and both branches converge on `CLOSED`.

On the repair branch, the shop completes the work, reporting an `actual_cost_cents`. The reported cost must not exceed the order's `authorized_amount_cents`, or completion is rejected with `ERR_REPAIR_EXCEEDS_AUTH`. A valid completion moves the order to `REPAIRED` and then automatically to `CLOSED`, and that closure cascades upward: the parent claim moves from `APPROVED` to `SETTLED`, and the referenced scheduled item is unlocked from `SUSPENDED` back to `ACTIVE`.

On the total-loss branch, the shop or a `ClaimsAdjuster` deems the item beyond economical repair, moving the order from `IN_PROGRESS` to `DEEMED_TOTAL_LOSS` and then automatically to `CLOSED`. This upgrade reclassifies the claim's `loss_type` to `TOTAL_LOSS`, recomputes `settlement_cents` along the full-item-value total-loss path of §3.12, removes the referenced scheduled item by transitioning it from `SUSPENDED` to `REMOVED`, and recomputes the policy's `total_insured_value_cents` and `annual_premium_cents` against the reduced item set.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return `201 Created`. Operations that modify or transition an existing resource — including binding, applying an endorsement, advancing a claim, or acting on a repair order — return `200 OK`. The administrative clock advance returns `200 OK`. The table below lists the method, path, purpose, and authorized roles for every endpoint; the request and response shapes are reconstructed from the workflows in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock and fire time-driven transitions | Underwriter, ClaimsAdjuster |
| POST | `/policyholders` | Register a Policyholder | Underwriter |
| GET | `/policyholders/{id}` | Get a Policyholder | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/risk-zones` | Create a RiskZone rate row | Underwriter |
| GET | `/risk-zones/{id}` | Get a RiskZone | Underwriter, ClaimsAdjuster |
| POST | `/repair-shops` | Register a RepairShop | Underwriter |
| GET | `/repair-shops/{id}` | Get a RepairShop | Underwriter, ClaimsAdjuster, RepairShop |
| POST | `/repair-shops/{repairShopId}/suspend` | Suspend a RepairShop | Underwriter |
| POST | `/appraisals` | File an Appraisal | Appraiser, Underwriter |
| GET | `/appraisals/{id}` | Get an Appraisal | Underwriter, ClaimsAdjuster, Appraiser, Policyholder |
| GET | `/appraisals` | List Appraisals (filter by `policyholder_id`) | Underwriter, ClaimsAdjuster, Appraiser, Policyholder |
| POST | `/policies` | Create a QUOTED Policy | Underwriter |
| GET | `/policies/{id}` | Get a Policy | Underwriter, ClaimsAdjuster, Policyholder |
| GET | `/policies` | List Policies (filter by `policyholder_id`) | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/policies/{policyId}/bind` | Bind a QUOTED Policy | Underwriter |
| POST | `/policies/{policyId}/cancel` | Cancel a Policy | Underwriter, Policyholder |
| POST | `/policies/{policyId}/scheduled-items` | Create a ScheduledItem under a Policy | Underwriter |
| GET | `/scheduled-items/{id}` | Get a ScheduledItem | Underwriter, ClaimsAdjuster, Policyholder |
| GET | `/scheduled-items` | List ScheduledItems (filter by `policy_id` or `appraisal_id`) | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/policies/{policyId}/endorsements` | Draft an Endorsement | Underwriter |
| GET | `/endorsements/{id}` | Get an Endorsement | Underwriter, ClaimsAdjuster, Policyholder |
| GET | `/endorsements` | List Endorsements (filter by `policy_id` or `target_item_id`) | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/policies/{policyId}/endorsements/{endorsementId}/apply` | Apply a DRAFT Endorsement (OCC-guarded) | Underwriter |
| POST | `/policies/{policyId}/endorsements/{endorsementId}/reject` | Reject a DRAFT Endorsement | Underwriter |
| POST | `/policies/{policyId}/claims` | File a Claim against an ACTIVE Policy | Policyholder, ClaimsAdjuster |
| GET | `/claims/{id}` | Get a Claim | Underwriter, ClaimsAdjuster, Policyholder |
| GET | `/claims` | List Claims (filter by `policy_id` or `scheduled_item_id`) | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/policies/{policyId}/claims/{claimId}/start_review` | Begin adjudication | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/request_info` | Request more information | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/provide_info` | Supply requested information | Policyholder |
| POST | `/policies/{policyId}/claims/{claimId}/approve` | Approve a claim (OCC-guarded) | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/deny` | Deny a claim | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/settle` | Settle an APPROVED TOTAL_LOSS claim | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/close` | Close a SETTLED claim | ClaimsAdjuster |
| POST | `/policies/{policyId}/claims/{claimId}/repair-order` | Assign a RepairOrder | ClaimsAdjuster |
| GET | `/repair-orders/{id}` | Get a RepairOrder | Underwriter, ClaimsAdjuster, Policyholder, RepairShop |
| GET | `/repair-orders` | List RepairOrders (filter by `claim_id` or `repair_shop_id`) | Underwriter, ClaimsAdjuster, Policyholder, RepairShop |
| POST | `/policies/{policyId}/claims/{claimId}/repair-order/accept` | Accept a RepairOrder | RepairShop |
| POST | `/policies/{policyId}/claims/{claimId}/repair-order/complete` | Complete a repair | RepairShop |
| POST | `/policies/{policyId}/claims/{claimId}/repair-order/deem_total_loss` | Deem the item a total loss | RepairShop, ClaimsAdjuster |
| POST | `/policies/{policyId}/payments` | Record a premium payment | Policyholder, Underwriter |
| GET | `/premium-payments/{id}` | Get a PremiumPayment | Underwriter, ClaimsAdjuster, Policyholder |
| GET | `/premium-payments` | List PremiumPayments (filter by `policy_id`) | Underwriter, ClaimsAdjuster, Policyholder |
| POST | `/policies/{policyId}/payments/{paymentId}/reverse` | Reverse a received payment | Underwriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_SCHEDULED_ITEMS` | 409 |
| `ERR_NAMED_PERIL_REQUIRES_PERILS` | 409 |
| `ERR_APPRAISAL_REQUIRED` | 409 |
| `ERR_POLICY_NOT_ACTIVE` | 409 |
| `ERR_PERIL_NOT_COVERED` | 409 |
| `ERR_WORLDWIDE_NOT_COVERED` | 409 |
| `ERR_ITEM_LOCKED_BY_CLAIM` | 409 |
| `ERR_NO_OP_ENDORSEMENT` | 422 |
| `ERR_INFO_REQUEST_LIMIT` | 409 |
| `ERR_SHOP_SUSPENDED` | 409 |
| `ERR_REPAIR_EXCEEDS_AUTH` | 409 |
| `ERR_PREMIUM_UNDERPAID` | 409 |
| `ERR_POLICY_NOT_BILLABLE` | 409 |
| `ERR_PARTIAL_REQUIRES_REPAIR` | 409 |
| `ERR_OPEN_CLAIM_BLOCKS_CANCEL` | 409 |
| `ERR_STALE_VERSION` | 412 |

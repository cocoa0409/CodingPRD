# Production Home Sales API — Product Requirements Document

## 1. Introduction

A production homebuilder sells homes the way a manufacturer sells configured products: a community is opened for sales, lots are released for purchase at published prices, buyers reserve a homesite, sign a purchase agreement for a floor plan and elevation, personalize the home at the design center, and then wait through construction milestones until closing. Each of those steps carries money and risk — lot premiums and price-phase uplifts, earnest money held in trust, design options whose prices lock against construction cutoffs, incentive dollars drawn from a finite community budget, and closing estimates that slip as stages complete late. This document specifies the API that runs that entire commercial workflow for a multi-community builder.

The API is the system of record for community and lot inventory, release pricing, reservations, purchase agreements, design-center selections, construction progress, incentive approvals, and warranty enrollment. It serves six kinds of callers — unauthenticated registrants, platform operators, sales directors, sales agents, buyers, and construction managers — and it answers to one logical clock, so that reservation holds, price-phase windows, contingency deadlines, and closing forecasts all behave deterministically as time advances. Wherever money is computed, the rules are pinned to the cent; wherever a client writes against data it previously read, optimistic concurrency guards prevent silent overwrites.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request missing either header or carrying one that is blank, or naming a role the system does not recognize, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Even with valid headers, a caller whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Six roles are recognized, spelled exactly as follows: `Anonymous`, `PlatformAdmin`, `SalesDirector`, `SalesAgent`, `Buyer`, and `ConstructionManager`. An `Anonymous` caller may only self-register as a buyer. A `PlatformAdmin` operates the test-driving logical clock. A `SalesDirector` owns community setup, pricing phases, plan and option catalogs, lot inventory release, and incentive decisions. A `SalesAgent` creates and manages purchase agreements, contingency clearances, closings, and incentive requests. A `Buyer` reserves lots, signs and cancels their own contract, makes design selections, and acknowledges the warranty. A `ConstructionManager` advances construction milestones.

Role identity is bound to resources as follows. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting Buyer; ownership checks on any resource that references a Buyer — an agreement's `buyer_id`, a lot's `reserved_buyer_id`, or a reservation payload's `buyer_id` — compare that field to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `Anonymous`, `PlatformAdmin`, `SalesDirector`, `SalesAgent`, or `ConstructionManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`, and the ownership exemption that staff roles enjoy (for example, a `SalesDirector` releasing another buyer's reservation or a `SalesAgent` cancelling another party's agreement) follows from this opaqueness.

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

Requests outside the declared API surface — an undeclared path, or an unsupported method on a declared path — are rejected with `ERR_NOT_FOUND` (HTTP 404), a generic identifier beyond the per-resource 404 catalogue of §5.

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items from the start of the result set and defaults to 0. A `limit` that is not an integer or falls outside the 1–100 range, or an `offset` that is not an integer or is negative, is rejected with `ERR_INVALID_REQUEST`.

Unless otherwise specified, list endpoints sort by creation timestamp (`created_at`) in ascending order, using stable insertion order to break ties. The milestone list is the single documented exception — it orders by construction sequence rather than by creation time; see §3.6. Documented per-endpoint filters are exact matches on the named field, and multiple filters on one request combine conjunctively; query parameters beyond the documented filters and the two pagination parameters are ignored.

Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

All resources in this API — Community, PricePhase, Lot, HomePlan, OptionCatalogItem, Buyer, PurchaseAgreement, OptionSelection, ConstructionMilestone, and IncentiveRequest — share the same four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by exactly 1 on every mutation of the resource.

Mutations frequently cascade across resources, and each touched resource obeys these semantics independently. When a buyer confirms a design selection, for example, both the selection and its owning agreement are mutated, so both resources' `version` values increment and both `updated_at` timestamps refresh. The same rule applies when an incentive decision or a milestone completion ripples up to the agreement. Clients that cache a resource must treat any related write as potentially advancing the cached resource's `version`.

### 2.5. Money, Precision, and Rounding

All monetary amounts in this API — prices, premiums, budgets, earnest money, fees, incentives, refunds, and totals — are represented as integer cents. Fields whose names end in `_cents` are integers; no monetary field carries a fractional value.

Where a calculation cannot land exactly on a whole cent, the system rounds half up to the nearest cent, and the rounding order is pinned wherever intermediate components exist: for release pricing, the base component and the premium component are each rounded half up to whole cents first and only then summed, because rounding the unrounded sum instead can differ by a cent. The same half-up rule governs the re-release uplift, the past-cutoff change fee, the forfeited share of earnest money, and the incentive-cap ceiling.

Schedule arithmetic works in whole days added to the current logical timestamp; the padded closing estimate rounds each stage's inflated duration up to the next whole day before summing. Slippage detection compares two timestamps to the second.

### 2.6. The Logical Clock and Its Scheduled Sweep

All time-dependent behavior in the system — price-phase windows, reservation holds, contingency deadlines, closing estimates, and slippage flags — reads from a single server-side logical clock, never from wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`. Every server-generated timestamp — `created_at`, `updated_at`, and the envelope's `api_request_timestamp` — reads from this same logical clock. Client-supplied datetime fields (`effective_from`, `effective_to`, `contingency_deadline`, `outside_close_date`) are stored and returned exactly as the request string supplied them, never normalized; only server-generated timestamps are rendered in the canonical three-fractional-digit UTC format.

A `PlatformAdmin`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant and receives back an object carrying `current_utc`, the clock's new reading echoed verbatim as the supplied `to_iso8601` string. Setting the clock deterministically executes a scheduled sweep at the new instant, in three parts: every price phase's status is re-derived against its window, every reservation hold whose expiry has been reached is released, and every agreement whose contingency deadline has passed with unresolved contingencies is auto-cancelled. The detailed consequences of each sweep branch live in §3.1, §3.2, and §3.4 respectively.

### 2.7. The Construction Stage Calendar

Construction progress, design-option cutoffs, and closing forecasts all speak the same ordered stage language. The five build stages, in order, are `PRE_CONSTRUCTION`, then `FOUNDATION`, then `FRAMING`, then `DRYWALL`, then `FINAL_WALKTHROUGH`. An agreement's `current_stage` draws from those five plus two bookend values: `NOT_STARTED` before construction tracking begins and `COMPLETE` once every milestone has finished. Stage comparisons throughout this document are ordinal comparisons against that fixed ordering — "past" a stage means strictly later in the ordering, and a window that runs "through" a stage includes that stage exactly.

Each build stage carries a planned duration used by the closing forecast: 30 days for `PRE_CONSTRUCTION`, 21 days for `FOUNDATION`, 28 days for `FRAMING`, 35 days for `DRYWALL`, and 14 days for `FINAL_WALKTHROUGH`. A flat 7-day close buffer is appended to every estimate, and the buyer-facing padded variant inflates each remaining stage's planned duration by a 15 percent weather buffer.

### 2.8. The Community Incentive Ledger

Each community operates a closed incentive budget. A community is created with `incentive_budget_total_cents`, and its `incentive_budget_remaining_cents` begins equal to that total. From then on the remaining budget is a derived ledger balance: it equals the total minus the sum of `amount_cents` over all incentive requests in `APPROVED` status whose agreement belongs to that community. Requests in `SUBMITTED`, `DENIED`, or `REVOKED` status contribute nothing.

The ledger is conserved: at every instant, the remaining budget plus the sum of approved amounts across the community equals the original total. Approval debits the ledger at the moment of approval; revocation — which happens only as part of agreement cancellation — restores the exact approved amount back to the remaining balance. No other operation moves this balance.

### 2.9. Optimistic Concurrency Control

Two write endpoints carry optimistic concurrency guards, and no other endpoint accepts a version field.

Creating a purchase agreement requires the request body to include `expected_lot_version`, carrying the lot's `version` as the client last observed it. If the lot's current `version` has advanced past that value — for instance because another writer reserved the lot or released a reservation after the client priced the deal — the create is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412), forcing a re-read before the contract is drafted.

Clearing or waiving a contingency requires the request body to include `expected_agreement_version`, carrying the agreement's `version` as the client last observed it. Each clearance itself mutates the agreement and may promote it to `CONTINGENCIES_CLEARED`, so a clearance submitted against a version the agreement has already advanced beyond is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), forcing the client to re-read the current contingency state.

### 2.10. Request Validation Order, Nested Retrieval, and Buyer Data Scoping

Every request is evaluated against an ordered cascade of checks; the first failing tier determines the error response, and later tiers are not evaluated. The tiers, in order:

1. **Header context** — `X-User-ID` and `X-User-Role` must be present and the role must be one of the six declared roles, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization** — the caller's role must be authorized for the endpoint, else `ERR_FORBIDDEN_ROLE`.
3. **Body well-formedness** — a missing required field, an unknown (undeclared) field, a wrong type, an unknown enum member, or a numeric value out of range (for example a `quantity` below 1 or an `amount_cents` below 1) is rejected with `ERR_INVALID_REQUEST`. An explicit JSON `null` on an optional field is treated as if the field were absent.
4. **Resource existence** — path identifiers are resolved first, then foreign-key identifiers from the request body, validated left to right. The first unresolvable identifier produces its dedicated 404: `ERR_COMMUNITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_OPTION_ITEM_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_SELECTION_NOT_FOUND`, `ERR_MILESTONE_NOT_FOUND`, or `ERR_INCENTIVE_NOT_FOUND`. On a path that nests one resource under another — the community-scoped catalog listings are the example — an unresolvable community `id` reports `ERR_COMMUNITY_NOT_FOUND` before any child-side validation runs.
5. **Buyer ownership** — a `Buyer`-role caller must own the targeted resource: reservation requires the body's `buyer_id` to equal the caller; signing, cancelling, acknowledging warranty, and every selection action require the agreement's `buyer_id` to equal the caller; releasing a reservation as a buyer requires the lot's `reserved_buyer_id` to equal the caller. Violations are rejected with `ERR_NOT_RESOURCE_OWNER`.
6. **Optimistic concurrency** — on the two guarded endpoints named in §2.9, a stale expected version is rejected with the corresponding 412 error.
7. **State admissibility** — the target resource's current state must admit the requested transition, else one of the 409 state errors: `ERR_COMMUNITY_INVALID_STATE`, `ERR_COMMUNITY_NOT_SELLING`, `ERR_LOT_INVALID_STATE`, `ERR_LOT_NOT_RELEASED`, `ERR_LOT_NOT_RESERVED_BY_BUYER`, `ERR_AGREEMENT_INVALID_STATE`, `ERR_CONTINGENCY_NOT_PENDING`, `ERR_MILESTONE_OUT_OF_ORDER`, `ERR_MILESTONE_ALREADY_COMPLETE`, `ERR_SELECTION_INVALID_STATE`, `ERR_INCENTIVE_INVALID_STATE`, or `ERR_CLOSE_BLOCKED`.
8. **Time and stage windows** — reservation holds, option cutoff windows, and price-phase window overlap: `ERR_LOT_HOLD_ACTIVE`, `ERR_OPTION_CUTOFF_PASSED`, or `ERR_PHASE_WINDOW_OVERLAP`.
9. **Uniqueness** — a duplicate `lot_number` within a community is rejected with `ERR_DUPLICATE_LOT_NUMBER`.
10. **In-community cross-references** — referenced plans, elevations, and option items must belong to the same community as the deal, else `ERR_PLAN_NOT_IN_COMMUNITY`, `ERR_ELEVATION_NOT_AVAILABLE`, or `ERR_OPTION_NOT_IN_COMMUNITY`.
11. **Money guards** — earnest-money minimum, incentive budget, and incentive cap: `ERR_EARNEST_BELOW_MINIMUM`, `ERR_INCENTIVE_BUDGET_EXCEEDED`, or `ERR_INCENTIVE_CAP_EXCEEDED`.

The ordering is observable. A reservation attempted on a lot another buyer holds surfaces `ERR_LOT_HOLD_ACTIVE` from the temporal tier only after the lot has been found to exist and its state examined; the same attempt on a lot whose hold has already expired but which the sweep has not yet released surfaces `ERR_LOT_NOT_RELEASED` from the earlier state tier instead. Within the money tier on an incentive approval, the budget check runs before the cap check, so an approval that would violate both reports `ERR_INCENTIVE_BUDGET_EXCEEDED`.

Buyers see only their own commercial records. On the list endpoints for agreements, option selections, incentive requests, and milestones, a `Buyer` caller's results are filtered to records whose owning agreement's `buyer_id` equals the caller's identity; likewise, a `Buyer` reading a single agreement may read only their own. Staff roles are unscoped.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Community and Its Catalogs

A `SalesDirector` begins by creating a community, supplying its `name` and the total incentive pool `incentive_budget_total_cents` (an integer-cent amount that may be zero but never negative). The new community starts in `SETUP` status with `incentive_budget_remaining_cents` initialized to the full total. Nothing can be sold while the community is in `SETUP`: releasing a lot, reserving a lot, or signing an agreement against a community that has not opened is rejected with `ERR_COMMUNITY_NOT_SELLING`. When the sales team is ready, the director opens sales, moving the community from `SETUP` to `SELLING`; invoking that transition on a community already in `SELLING` is rejected with `ERR_COMMUNITY_INVALID_STATE`. Opening sales mutates the community and increments its `version`.

With the community defined, the director builds its three catalogs. **Home plans** are created with a `community_id`, a `plan_name`, a `base_price_cents` strictly greater than zero, and an `elevations` list. Each elevation entry carries a `name` and a `price_cents` of zero or more; the list must contain at least one entry, and elevation names must be unique within the plan. **Design-center option items** are created with a `community_id`, an `option_name`, a `category` drawn from `STRUCTURAL`, `KITCHEN`, `BATH`, `FLOORING`, `ELECTRICAL`, or `OUTDOOR`, a unit `price_cents` strictly greater than zero, and two stage markers: `cutoff_stage`, the last build stage during which the option may be freely selected or re-opened, and `install_stage`, the stage after which a confirmed selection is treated as physically installed. A malformed payload — a missing required field, a wrong type, an unknown enum member, a negative price, or an elevations list violating its shape constraints — is rejected with `ERR_INVALID_REQUEST`. The catalog listings of a community are reachable as community-scoped collections, and the option-catalog listing may additionally be filtered by `category`.

**Price phases** let the director raise prices over time. A phase is created with a `community_id`, a `phase_name`, a fractional `uplift_pct` of any numeric value — zero and negative uplifts are not rejected — (for example 0.03 for a three percent uplift), and a half-open window from `effective_from` (inclusive) to `effective_to` (exclusive); a window whose end is not strictly after its start is malformed and rejected with `ERR_INVALID_REQUEST`. A community's phase windows may touch but never overlap: a new phase whose window intersects an existing phase of the same community is rejected with `ERR_PHASE_WINDOW_OVERLAP`, while one whose `effective_from` lands exactly on the previous phase's `effective_to` is legal adjacency. A phase's `status` is never set by the client — it is derived from the logical clock at creation and re-derived on every clock set: `SCHEDULED` while the current instant is earlier than `effective_from`, `ACTIVE` while the instant is at or after `effective_from` and strictly before `effective_to`, and `EXPIRED` once the instant reaches `effective_to`. Because windows cannot overlap, at most one phase of a community is `ACTIVE` at any instant.

### 3.2. Lot Inventory: Release Pricing, Reservations, and Holds

Lots are the salable homesites. A `SalesDirector` creates each lot in `DRAFT` status with a `community_id`, a `lot_number` that must be unique within its community (a duplicate is rejected with `ERR_DUPLICATE_LOT_NUMBER`), a `base_price_cents` strictly greater than zero, a `lot_type` of `STANDARD`, `CORNER`, `VIEW`, or `CUL_DE_SAC`, and an optional `view_adjustment_cents` of zero or more (a negative value is malformed), defaulting to 0, for premium frontage. A fresh lot's `release_count` is 0, and its `release_price_cents` is null while it sits in `DRAFT` — the published price exists only after release. The lot inventory listing may be filtered by `community_id`, `reserved_buyer_id`, or `status`.

Releasing a lot is the pricing event. A director may release only a `DRAFT` lot (any other state is rejected with `ERR_LOT_INVALID_STATE`), and only while the lot's community is `SELLING` (else `ERR_COMMUNITY_NOT_SELLING`). At release, the lot's `release_price_cents` is computed and frozen. The premium side of the formula starts from a per-type premium — zero cents for `STANDARD`, $15,000 for `CORNER`, $25,000 for `VIEW`, and $10,000 for `CUL_DE_SAC` — adds the lot's `view_adjustment_cents`, and caps the combined premium at $30,000, taking the lesser of the cap and the raw sum. If the lot's community has an `ACTIVE` price phase at the release instant, that phase's `uplift_pct` applies; with no active phase the uplift is zero. The base component is the lot's `base_price_cents` multiplied by one plus the uplift fraction, rounded half up to whole cents; the premium component is the capped premium multiplied by one plus the same uplift fraction, likewise rounded half up; the release price is the sum of the two rounded components, in that pinned order. Releasing mutates the lot and increments its `version`.

Before any reservation can exist, the buyer must be on file. Registration is the one act open to an `Anonymous` caller: it creates a Buyer record from a `full_name` and a contact `email`, and the returned `id` is the identity that buyer will present in the `X-User-ID` header for the rest of the journey.

A `Buyer` reserves a `RELEASED` lot by posting a body containing their `buyer_id`, which must equal the caller's identity (a mismatch is `ERR_NOT_RESOURCE_OWNER`). The community must still be `SELLING` (else `ERR_COMMUNITY_NOT_SELLING`). If the lot is in any state other than `RELEASED`, the outcome depends on which state: a lot in `RESERVED` whose hold is still active — the current instant strictly earlier than its `hold_expires_at` — rejects the reservation with `ERR_LOT_HOLD_ACTIVE`; a lot in `RESERVED` whose hold has expired but which the sweep has not yet released, or a lot in any other non-`RELEASED` state, is rejected with `ERR_LOT_NOT_RELEASED`. A successful reservation moves the lot to `RESERVED`, records the caller in `reserved_buyer_id`, sets `hold_expires_at` to 72 hours after the reservation instant, and increments the lot's `version`.

Reservation churn never reprices a lot. The holder — or a `SalesDirector`, who is exempt from the holder check — may release an active reservation, returning the lot from `RESERVED` to `RELEASED` with `reserved_buyer_id` and `hold_expires_at` cleared; the lot must be `RESERVED` (else `ERR_LOT_INVALID_STATE`), and a `Buyer` caller who is not the holder is rejected with `ERR_NOT_RESOURCE_OWNER`. Independently, the clock sweep releases any reservation whose expiry has been reached: once the current instant is at or after `hold_expires_at`, the lot returns to `RELEASED` by the same field-clearing path. In both paths the `release_price_cents` is left unchanged and `release_count` is not incremented — only post-contract fallout, covered in §3.8, reprices a lot.

### 3.3. Drafting and Signing the Purchase Agreement

Once a buyer holds a reservation, a `SalesAgent` drafts the purchase agreement against that lot. The creation payload carries `buyer_id`, `lot_id`, `plan_id`, `elevation_name`, `earnest_money_deposited_cents`, `contingency_deadline`, `outside_close_date`, an optional `has_sale_of_home_contingency` defaulting to false, and the optimistic-concurrency field `expected_lot_version` described in §2.9. Earnest money must meet the trust minimum of $1,000 — a deposit below that floor is rejected with `ERR_EARNEST_BELOW_MINIMUM` (HTTP 402). The deal must also stay inside one community: the referenced plan must belong to the same community as the lot (else `ERR_PLAN_NOT_IN_COMMUNITY`, HTTP 422), and the `elevation_name` must appear among the plan's `elevations` entries (else `ERR_ELEVATION_NOT_AVAILABLE`, HTTP 422). The agreement is created in `DRAFT` status with its `community_id` denormalized from the lot's community, its `options_total_cents`, `change_fees_total_cents`, and `incentives_total_cents` all at 0, its `warranty_status` at `NONE`, its `warranty_term_months` at 0, its `slippage_flag` false, and its three contingency trackers, its three price snapshots (`lot_price_snapshot_cents`, `plan_price_snapshot_cents`, `elevation_price_snapshot_cents`), its `provisional_total_cents`, its two closing estimates, and its `final_total_cents`, `refund_amount_cents`, `forfeited_amount_cents`, `cancel_reason`, and `warranty_enrolled_at` all null. Linking the agreement marks the lot: the lot's `version` increments by 1 at creation even though its status does not yet change. The full set of agreement statuses is `DRAFT`, `PENDING_CONTINGENCIES`, `CONTINGENCIES_CLEARED`, `CLOSED`, and `CANCELLED`.

Signing is the buyer's act, and it is a heavily guarded transition. The agreement must be in `DRAFT` (else `ERR_AGREEMENT_INVALID_STATE`), the acting buyer must equal the agreement's `buyer_id` (else `ERR_NOT_RESOURCE_OWNER`), the referenced lot must be in `RESERVED` with its `reserved_buyer_id` equal to the agreement's `buyer_id` (else `ERR_LOT_NOT_RESERVED_BY_BUYER`), and the community must be `SELLING` (else `ERR_COMMUNITY_NOT_SELLING`); within the state tier the lot check is evaluated before the community check. When signing succeeds, prices are snapshotted into `lot_price_snapshot_cents` (the lot's current `release_price_cents`), `plan_price_snapshot_cents` (the plan's `base_price_cents`), and `elevation_price_snapshot_cents` (the price of the chosen elevation entry). The `provisional_total_cents` is fixed at that moment as the sum of the three snapshots and never changes afterwards. Contingency trackers are initialized: `financing_contingency_status` and `appraisal_contingency_status` start at `PENDING`, and `sale_of_home_contingency_status` starts at `PENDING` when `has_sale_of_home_contingency` is true or at `WAIVED` when it is false; each tracker later resolves to `CLEARED` or `WAIVED`. The agreement's `current_stage` becomes `PRE_CONSTRUCTION`, matching the earliest unstarted milestone.

Signing also builds the construction plan: five milestones are auto-created, one per build stage, numbered by `sequence_no` from 1 through 5 in stage order, each with its planned duration from the stage calendar in `planned_duration_days`, each starting in `NOT_STARTED` status with `completed_at` and `buyer_notified_at` null. The closing estimate and slippage flag are computed for the first time (§3.6). Finally, the lot moves from `RESERVED` to `SOLD`, clearing `hold_expires_at` while retaining `reserved_buyer_id` as the purchaser record, and both the lot and the agreement increment their `version`. The agreement emerges in `PENDING_CONTINGENCIES`.

### 3.4. Contingency Clearance and the Deadline Sweep

Between signing and closing, three contingencies track the deal's conditions: `financing_contingency_status`, `appraisal_contingency_status`, and `sale_of_home_contingency_status`. A `SalesAgent` clears or waives one at a time by submitting `contingency_type`, an `action` that resolves the named tracker to `CLEARED` or `WAIVED`, and the OCC field `expected_agreement_version` (§2.9). Only a tracker still in `PENDING` may be cleared or waived; acting on one that has already resolved is rejected with `ERR_CONTINGENCY_NOT_PENDING`. Each successful clearance mutates the agreement and increments its `version`. When the last unresolved tracker lands in `CLEARED` or `WAIVED` — all three trackers now resting in that pair of states — the agreement promotes itself from `PENDING_CONTINGENCIES` to `CONTINGENCIES_CLEARED`, a further mutation that increments the agreement's `version` again.

Contingencies can also expire. The agreement's `contingency_deadline` is supplied at drafting time; whenever the logical clock is set strictly later than that deadline while any of the three trackers is still `PENDING`, the sweep cancels the agreement outright. The cancellation carries `cancel_reason` `CONTINGENCY_EXPIRED` and always refunds the earnest money in full: `refund_amount_cents` equals `earnest_money_deposited_cents` and `forfeited_amount_cents` is 0. The full cascade — selections cancelled, incentives revoked, the lot re-released and repriced — is the same one described in §3.8.

### 3.5. Design-Center Selections and the Cutoff Calendar

A buyer personalizes the home by selecting options from the community's design-center catalog. Creating a selection takes `agreement_id`, `option_item_id`, and an optional `quantity` defaulting to 1 (a value below 1 is malformed). The option item must belong to the same community as the agreement (else `ERR_OPTION_NOT_IN_COMMUNITY`, HTTP 422), and the agreement's `current_stage` must not have moved past the item's `cutoff_stage` — selection is free while the current stage's ordinal is at or below the cutoff stage's ordinal, and once the ordinal ordering places `current_stage` strictly beyond `cutoff_stage` the create is rejected with `ERR_OPTION_CUTOFF_PASSED`. A created selection starts in `SELECTED` status with `unit_price_cents` snapshotted from the catalog item's current `price_cents`, `line_total_cents` computed as that unit price multiplied by the quantity, `selected_at_stage` recording the agreement's stage at selection time, `change_fee_cents` at 0, and `confirmed_at_stage` and `cancel_reason` null. The agreement's `options_total_cents` — the sum of `line_total_cents` over its selections in `SELECTED`, `CONFIRMED`, or `INSTALLED` status — absorbs the new line, and the agreement's `version` increments alongside the selection's creation. Selection listings may be filtered by `agreement_id`, `option_item_id`, or `status`.

Confirming a selection locks it in. The buyer (who must own the agreement, else `ERR_NOT_RESOURCE_OWNER`) may confirm only a `SELECTED` line (else `ERR_SELECTION_INVALID_STATE`), and only while the agreement is in `PENDING_CONTINGENCIES` or `CONTINGENCIES_CLEARED` (else `ERR_AGREEMENT_INVALID_STATE`). Confirmation stamps `confirmed_at_stage` with the agreement's current stage and never charges a fee — a stale `SELECTED` line cannot survive into a past-cutoff stage, because the milestone sweep of §3.6 cancels it first, so no confirm can ever occur past cutoff. Both the selection and the agreement increment their `version`.

While still inside the free window, a confirmation can be undone: re-opening a `CONFIRMED` line returns it to `SELECTED` and clears `confirmed_at_stage`. The same cutoff comparison guards the re-open — once the agreement's `current_stage` ordinal has moved strictly past the item's `cutoff_stage` ordinal, unconfirming is rejected with `ERR_OPTION_CUTOFF_PASSED`; at exact stage equality the window is still open. The selection must be `CONFIRMED` (else `ERR_SELECTION_INVALID_STATE`) and the caller must own the agreement. Both resources increment their `version`.

Cancelling a selection is always possible from `SELECTED` or `CONFIRMED` — any other state, including `INSTALLED`, is rejected with `ERR_SELECTION_INVALID_STATE` — and always records `cancel_reason` `BUYER_REQUEST`. Cancelling a merely-`SELECTED` line is free regardless of stage. Cancelling a `CONFIRMED` line is free inside the cutoff window but incurs a change fee once the agreement's `current_stage` ordinal is strictly past the item's `cutoff_stage` ordinal: the fee is ten percent of the line's `line_total_cents`, rounded half up to whole cents, recorded in the selection's `change_fee_cents` and added to the agreement's `change_fees_total_cents`. Either way the line leaves the options total — `options_total_cents` is recomputed without it — and both selection and agreement increment their `version`. The selection lifecycle's terminal states are `INSTALLED` and `CANCELLED`; its remaining cancel reasons, `CUTOFF_EXPIRED` and `AGREEMENT_CANCELLED`, come from the system paths in §3.6 and §3.8 rather than from the buyer.

### 3.6. Construction Milestones, Closing Estimates, and Slippage

A `ConstructionManager` reports progress by completing milestones. Completion is strictly sequential: the milestone must be in `NOT_STARTED` (a repeat completion is rejected with `ERR_MILESTONE_ALREADY_COMPLETE`), every milestone of the same agreement with a lower `sequence_no` must already be `COMPLETE` (else `ERR_MILESTONE_OUT_OF_ORDER`), and the agreement must be in `PENDING_CONTINGENCIES` or `CONTINGENCIES_CLEARED` (else `ERR_AGREEMENT_INVALID_STATE`). On completion the milestone stamps `completed_at` with the current instant and sets `buyer_notified_at` equal to it — that equality is the buyer-facing milestone communication, the moment the buyer is told the stage finished. Milestone listings are ordered by `sequence_no` ascending rather than by creation time, with stable insertion order breaking ties between equal `sequence_no` values, and may be filtered by `agreement_id`, `stage`, or `status`.

Completion advances the agreement's `current_stage` to the stage of its earliest remaining `NOT_STARTED` milestone, or to `COMPLETE` when none remain. That advance drives two automated sweeps over the agreement's selections. First, every selection still in `SELECTED` whose option's `cutoff_stage` ordinal now lies strictly behind the new `current_stage` ordinal is cancelled with `cancel_reason` `CUTOFF_EXPIRED` and no change fee — unconfirmed selections simply lapse. Second, every selection in `CONFIRMED` whose option's `install_stage` ordinal now lies strictly behind the new stage becomes `INSTALLED`. After both sweeps the agreement's `options_total_cents` is recomputed over the surviving non-cancelled lines. The milestone, the agreement, and each swept selection all increment their `version`.

Each signing and each milestone completion also recomputes the two closing forecasts. Both variants consider only the agreement's `NOT_STARTED` milestones, in `sequence_no` order, and both ignore partial progress inside the current stage — the full planned duration of every unstarted stage counts, and completed stages contribute nothing. The internal `estimated_close_standard` is the current logical timestamp plus the raw `planned_duration_days` of every remaining stage plus the 7-day close buffer. The buyer-facing `estimated_close_padded` inflates each remaining stage's planned duration by the 15 percent weather buffer, rounds each stage's inflated value up to the next whole day before any summation, then adds those whole-day values and the same 7-day buffer to the current timestamp. Whenever any milestone remains, the padded estimate is strictly later than the standard one. The `slippage_flag` is recomputed alongside: it is true exactly when `estimated_close_padded` falls strictly later than the agreement's `outside_close_date`, compared to the second — a padded estimate landing exactly on the outside date is not slippage.

### 3.7. Incentives and Rate Buydowns

A `SalesAgent` requests an incentive against an agreement by supplying `agreement_id`, an `incentive_type` of `RATE_BUYDOWN`, `CLOSING_COST_CREDIT`, or `PRICE_REDUCTION`, and an `amount_cents` of at least one cent. The agreement must be in `PENDING_CONTINGENCIES` or `CONTINGENCIES_CLEARED` — a request against an agreement in any other status is rejected with `ERR_AGREEMENT_INVALID_STATE`, a state check that precedes the money guards. The request cannot exceed the money available: if the amount surpasses the community's `incentive_budget_remaining_cents`, creation is rejected outright with `ERR_INCENTIVE_BUDGET_EXCEEDED` (HTTP 402).

Small, affordable requests approve themselves. When the amount is at or below the $3,000 auto-approval limit — exactly the limit still qualifies — and the community's remaining budget covers the amount and the agreement's cap check passes, the new request lands directly in `APPROVED` with `auto_approved` set to true and `decided_at` stamped; the community budget is debited, the agreement's `incentives_total_cents` grows by the amount, and the agreement's `version` increments. Any request that fails one of those conditions is instead created in `SUBMITTED` with `auto_approved` false and `decided_at` null, awaiting a human decision. Incentive listings may be filtered by `agreement_id` or `status`.

A `SalesDirector` decides a pending request by submitting an `action` of `APPROVE` or `DENY`; the request must be in `SUBMITTED`, else `ERR_INCENTIVE_INVALID_STATE`. Approval re-runs both money guards in order: first the community budget must cover the amount (`incentive_budget_remaining_cents` minus `amount_cents` must not go negative, else `ERR_INCENTIVE_BUDGET_EXCEEDED`), then the agreement-level cap — the agreement's cumulative `incentives_total_cents` plus this amount must not exceed six percent of its `provisional_total_cents`, that ceiling rounded half up to whole cents (else `ERR_INCENTIVE_CAP_EXCEEDED`). The cap base is always the immutable provisional total fixed at signing; it is never re-derived from `final_total_cents`, which would make the rule circular. An approved decision debits the community budget, raises the agreement's `incentives_total_cents`, stamps `decided_at`, and increments the agreement's `version`. A denial simply stamps `decided_at` and moves the request to `DENIED` with no ledger movement; `DENIED` and `REVOKED` are terminal, as is `APPROVED` until a cancellation revokes it. When an agreement is cancelled, every `APPROVED` request on it moves to `REVOKED`, the exact amount is restored to the community's remaining budget, and the agreement's `incentives_total_cents` is reduced accordingly.

### 3.8. Cancellation, Refunds, and Re-Release

An agreement in `DRAFT`, `PENDING_CONTINGENCIES`, or `CONTINGENCIES_CLEARED` may be cancelled by the owning `Buyer` or by a `SalesAgent` (a buyer cancelling someone else's contract is rejected with `ERR_NOT_RESOURCE_OWNER`; any other status is rejected with `ERR_AGREEMENT_INVALID_STATE`). The caller supplies a `reason` of `BUYER_DEFAULT` or `BUILDER_DEFAULT` — any other value is rejected with `ERR_INVALID_REQUEST` — and the reason, combined with the status at cancellation, fixes the earnest-money split. The trust invariant always holds: `refund_amount_cents` plus `forfeited_amount_cents` equals `earnest_money_deposited_cents`.

Three branches refund everything. A cancellation from `DRAFT` returns the full deposit with nothing forfeited — and because the lot was never marked `SOLD` for an unsigned agreement, the lot is left entirely unchanged. A cancellation from `PENDING_CONTINGENCIES` also refunds in full regardless of reason. A cancellation from `CONTINGENCIES_CLEARED` with reason `BUILDER_DEFAULT` refunds in full as well. The single forfeiture branch is `CONTINGENCIES_CLEARED` with `BUYER_DEFAULT`: the forfeited share is 25 percent of the deposited earnest money, rounded half up to whole cents, and the remainder is refunded. The deadline sweep of §3.4 is the fifth path into cancellation and, as noted there, always refunds in full under `CONTINGENCY_EXPIRED`.

Every cancellation cascades. All of the agreement's selections in `SELECTED` or `CONFIRMED` move to `CANCELLED` with `cancel_reason` `AGREEMENT_CANCELLED` and no change fee, and `options_total_cents` is recomputed. Every `APPROVED` incentive request on the agreement moves to `REVOKED` with the budget restoration described in §3.7. And if the agreement had been signed, its lot returns from `SOLD` to `RELEASED`: the reservation fields are cleared, `release_count` increments by 1, and the lot is repriced upward — the new `release_price_cents` is the previous release price inflated by 2 percent, rounded half up to whole cents, with no re-evaluation of the phase window or the lot-type premium. The agreement and each cascaded resource increment their `version`. A cancelled agreement is terminal; `CLOSED` and `CANCELLED` are the two terminal agreement states.

### 3.9. Closing the Sale and the Warranty

Closing is a `SalesAgent` act with two hard preconditions: the agreement must be in `CONTINGENCIES_CLEARED` (else `ERR_AGREEMENT_INVALID_STATE`), and all five of its construction milestones must be `COMPLETE` (else `ERR_CLOSE_BLOCKED`). At close the final price crystallizes: `final_total_cents` is the immutable `provisional_total_cents` plus `options_total_cents` plus `change_fees_total_cents` minus `incentives_total_cents` — identical inputs priced at signing would give a different number than at close once options and incentives exist, which is exactly why the two totals are computed at different moments. Warranty enrollment happens in the same motion: `warranty_status` moves from `NONE` to `ENROLLED`, `warranty_term_months` is set to the standard 12-month term, and `warranty_enrolled_at` is stamped with the closing instant. The lot completes its own lifecycle, moving from `SOLD` to its terminal `CLOSED` state, and both lot and agreement increment their `version`.

One buyer act remains after closing. The owning buyer acknowledges the enrolled warranty, moving `warranty_status` from `ENROLLED` to `ACKNOWLEDGED`; the agreement must be `CLOSED` with the warranty still `ENROLLED` (else `ERR_AGREEMENT_INVALID_STATE`), and the caller must own the agreement (else `ERR_NOT_RESOURCE_OWNER`). This is a self-transition on the contract dimension — the agreement's `status` stays `CLOSED` — restricted to the warranty dimension alone, and it increments the agreement's `version` like any other mutation.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — state transitions, clearances, decisions, sweeps triggered by the clock — return `200 OK`. Unless an endpoint is listed as returning only a scalar payload, the created or updated resource is returned in the response's `data` field.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/homebuilder/communities` | Create a community (starts in `SETUP`; remaining incentive budget initialized to the total) | SalesDirector |
| GET | `/homebuilder/communities/{id}` | Get one community | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/communities/{id}/open-sales` | Open the community for sales (`SETUP` → `SELLING`) | SalesDirector |
| POST | `/homebuilder/price-phases` | Create a pricing phase with a non-overlapping half-open window; status derived from the logical clock | SalesDirector |
| GET | `/homebuilder/communities/{id}/price-phases` | List pricing phases of a community | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/plans` | Create a home plan with elevations | SalesDirector |
| GET | `/homebuilder/communities/{id}/plans` | List plans offered in a community | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/option-catalog-items` | Create a design-center option with cutoff and install stages | SalesDirector |
| GET | `/homebuilder/communities/{id}/option-catalog-items` | List the design-center catalog of a community (filterable by `category`) | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/lots` | Create a lot in `DRAFT` | SalesDirector |
| GET | `/homebuilder/lots` | List lots (filterable by `community_id`, `reserved_buyer_id`, `status`) | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| GET | `/homebuilder/lots/{id}` | Get one lot | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/lots/{id}/release` | Release a `DRAFT` lot for sale; computes and freezes `release_price_cents` | SalesDirector |
| POST | `/homebuilder/lots/{id}/reserve` | Buyer reserves a `RELEASED` lot; 72-hour hold begins | Buyer |
| POST | `/homebuilder/lots/{id}/release-reservation` | Release an active reservation (holder or SalesDirector); no repricing | Buyer, SalesDirector |
| POST | `/homebuilder/buyers` | Register a buyer | Anonymous |
| POST | `/homebuilder/agreements` | Create a `DRAFT` purchase agreement against a reserved lot; OCC-guarded on the lot's version | SalesAgent |
| GET | `/homebuilder/agreements` | List agreements (filterable by `buyer_id`, `lot_id`, `plan_id`, `community_id`, `status`); Buyer sees only own | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| GET | `/homebuilder/agreements/{id}` | Get one agreement; Buyer may read only own | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/agreements/{id}/sign` | Buyer signs: price snapshots, contingency initialization, five milestones created, lot moves to `SOLD` | Buyer |
| POST | `/homebuilder/agreements/{id}/contingency-clearance` | Clear or waive one contingency; OCC-guarded on the agreement's version | SalesAgent |
| POST | `/homebuilder/agreements/{id}/cancel` | Cancel a non-terminal agreement; refund split by state and reason; cascades to selections, incentives, and the lot | Buyer, SalesAgent |
| POST | `/homebuilder/agreements/{id}/close` | Close the sale: final price, warranty enrollment, lot moves to `CLOSED` | SalesAgent |
| POST | `/homebuilder/agreements/{id}/acknowledge-warranty` | Buyer acknowledges the enrolled warranty | Buyer |
| POST | `/homebuilder/option-selections` | Buyer selects a design-center option; rejected past the option's cutoff stage | Buyer |
| GET | `/homebuilder/option-selections` | List selections (filterable by `agreement_id`, `option_item_id`, `status`); Buyer scoped to own agreements | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| GET | `/homebuilder/option-selections/{id}` | Get one selection | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/option-selections/{id}/confirm` | Confirm a `SELECTED` selection (never a fee) | Buyer |
| POST | `/homebuilder/option-selections/{id}/unconfirm` | Re-open a `CONFIRMED` selection while inside the free cutoff window | Buyer |
| POST | `/homebuilder/option-selections/{id}/cancel` | Cancel a `SELECTED` (always free) or `CONFIRMED` (fee past cutoff) selection | Buyer |
| GET | `/homebuilder/milestones` | List milestones (sorted by `sequence_no` ascending; filterable by `agreement_id`, `stage`, `status`); Buyer scoped to own agreements | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| GET | `/homebuilder/milestones/{id}` | Get one milestone | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/milestones/{id}/complete` | Complete a milestone in sequence order; advances stage, recomputes estimates, sweeps selections | ConstructionManager |
| POST | `/homebuilder/incentive-requests` | Request an incentive or rate buydown; auto-approves at or below the limit when budget and cap allow | SalesAgent |
| GET | `/homebuilder/incentive-requests` | List incentive requests (filterable by `agreement_id`, `status`); Buyer scoped to own agreements | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| GET | `/homebuilder/incentive-requests/{id}` | Get one incentive request | PlatformAdmin, SalesDirector, SalesAgent, Buyer, ConstructionManager |
| POST | `/homebuilder/incentive-requests/{id}/decide` | SalesDirector approves or denies a `SUBMITTED` request; approval enforces budget then cap | SalesDirector |
| POST | `/_clock/set_current_utc` | Set the server's logical clock and run the scheduled sweep at the new instant | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_COMMUNITY_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_OPTION_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_BUYER_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SELECTION_NOT_FOUND` | 404 Not Found |
| `ERR_MILESTONE_NOT_FOUND` | 404 Not Found |
| `ERR_INCENTIVE_NOT_FOUND` | 404 Not Found |
| `ERR_COMMUNITY_INVALID_STATE` | 409 Conflict |
| `ERR_COMMUNITY_NOT_SELLING` | 409 Conflict |
| `ERR_LOT_INVALID_STATE` | 409 Conflict |
| `ERR_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_LOT_HOLD_ACTIVE` | 409 Conflict |
| `ERR_LOT_NOT_RESERVED_BY_BUYER` | 409 Conflict |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_CONTINGENCY_NOT_PENDING` | 409 Conflict |
| `ERR_MILESTONE_OUT_OF_ORDER` | 409 Conflict |
| `ERR_MILESTONE_ALREADY_COMPLETE` | 409 Conflict |
| `ERR_SELECTION_INVALID_STATE` | 409 Conflict |
| `ERR_INCENTIVE_INVALID_STATE` | 409 Conflict |
| `ERR_CLOSE_BLOCKED` | 409 Conflict |
| `ERR_OPTION_CUTOFF_PASSED` | 409 Conflict |
| `ERR_PHASE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_LOT_NUMBER` | 409 Conflict |
| `ERR_OPTION_NOT_IN_COMMUNITY` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_IN_COMMUNITY` | 422 Unprocessable Entity |
| `ERR_ELEVATION_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_EARNEST_BELOW_MINIMUM` | 402 Payment Required |
| `ERR_INCENTIVE_BUDGET_EXCEEDED` | 402 Payment Required |
| `ERR_INCENTIVE_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_NOT_FOUND` | 404 Not Found |

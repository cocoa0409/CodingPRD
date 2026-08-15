# Hop Farm Contract Supply API — Product Requirements Document

## 1. Introduction

A Yakima Valley hop grower sells an agricultural product whose value is not known when it is planted, and not even when it is picked. Acreage is committed to varieties months before a single bine is harvested; brewers sign multi-year supply contracts against that acreage; and the price those contracts actually pay is settled only after the crop has been cut, kiln-dried, pelletized, and assayed for alpha-acid content in the lab. In a short crop year there is not enough pellet inventory to fill every contract, and the grower must allocate pro-rata, carry the shortfall against each buyer, and decide which surplus lots — if any — go to the spot market instead. Crop insurance stands behind the whole program as the yield-risk backstop.

This document specifies the Hop Farm Contract Supply API, the system of record for that cycle. It governs field and kiln registration, per-season planting plans with projected and actual yields, the harvest-lot kiln pipeline with its moisture safety gate, provisional and final alpha-acid testing with a regrade cascade, pelletizing with processing-loss accounting and cold-storage aging, multi-year contracts with alpha-adjusted pricing and concurrency-guarded amendments, pro-rata allocation runs with FIFO reservation and settlement, the brewery sample and spot-sale channel, segregation-of-duties-controlled insurance claims, and the crop-year rollover that closes the season. All temporal reasoning — storage age, carryover decay, contract term completion — is evaluated against a single server-held logical clock so behavior is deterministic and reproducible.

The API is mounted under the `/api` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across every endpoint: authentication and role resolution, the response envelope, pagination, resource identity, the logical clock, concurrency control, precision, and the priority order in which validation failures surface.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorized-role list in §4; a role not permitted to call the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes four roles, spelled exactly as follows: `FarmManager`, `LabTechnician`, `ContractManager`, and `InsuranceAdjuster`. The `FarmManager` runs grower-side operations — fields, kilns, planting plans, harvest lots, pelletizing, the crop-year rollover — and files insurance claims. The `LabTechnician` posts alpha-acid lab tests. The `ContractManager` runs the sales desk — contracts and amendments, allocation runs and the allocation lifecycle, spot sales, and brewery samples. The `InsuranceAdjuster` reviews, decides, and pays insurance claims. Read access is broad: every retrieval and list endpoint accepts any of the four roles.

All four roles are **opaque**: when `X-User-Role` is `FarmManager`, `LabTechnician`, `ContractManager`, or `InsuranceAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`. There is exactly one place an operator identifier is persisted and later compared: an insurance claim records the filer's `X-User-ID` in its `filed_by_user_id` field at filing time, and the segregation-of-duties rule in §3.8 compares that stored value against the `X-User-ID` of whoever attempts to review, decide, or pay the claim. That comparison is against a recorded field, not against any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Version Counter

Every resource carries `id`, a server-minted UUID with no type prefix, and `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. Nearly every resource additionally carries `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at its initial value on creation and increments by exactly 1 on every mutation of that resource. Datetime values supplied in request bodies — the `kiln_window_start` and `kiln_window_end` of kiln loading and redrying (§3.2), and the clock's `to_iso8601` (§2.5) — are stored as instants and rendered in that same canonical form wherever they surface in a response: ISO 8601 UTC with exactly three fractional digits, so a window submitted as `2026-08-05T12:30:00Z` reads back as `2026-08-05T12:30:00.000Z`. One resource family is deliberately leaner: a `LabTest` carries only `id` and `created_at` — a posted lab result is an immutable record, and both `updated_at` and `version` are absent from it.

The `version` counter is both the backbone of optimistic concurrency control (§2.6) and a visible audit signal: every state transition, every cascade touch, and every computed-field update on a versioned resource moves the counter by one. When a single call mutates several resources — a contract termination that cancels allocations and releases pellet lots, or a final lab test that regrades lots and delivered allocations — each affected resource's `version` increments independently, and each affected resource's `updated_at` refreshes.

### 2.5. The Logical Clock and Crop-Year Boundaries

All temporal evaluation in the system reads a single server-held logical clock, never the host wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`; the clock never falls back to wall-clock time on its own. Any of the four roles may advance it through a test-driving capability that accepts a `to_iso8601` instant and returns the new `current_utc`; this capability is the one endpoint mounted outside the `/api` prefix.

The logical clock does real work: it stamps each pellet lot's `entered_storage_at` at pelletize time, it measures the storage months that drive carryover decay, and at crop-year rollover it decides which pellet lots flip to carryover age and which active contracts have run past their final contracted year (§3.9).

### 2.6. Optimistic Concurrency Control

Exactly one write in this API is OCC-guarded, and the guard is non-optional: amending a contract. Every contract-amendment request must carry `expected_contract_version`, holding the target contract's `version` as the client last observed it. If the contract's current `version` has advanced beyond that observed value — a contract may legitimately be amended repeatedly during volume and price renegotiation, and a writer working from a stale read would silently clobber an intervening amendment — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), reducing the conflict to a deterministic stale-version rejection. A successful amendment applies the supplied changes and increments the contract's `version` by 1. No other endpoint accepts a version field.

### 2.7. Units, Precision, and Rounding

Weights are integer pounds throughout: wet and dried lot weights, pellet quantities, contracted volumes, allocated and delivered pounds, yield projections, and insurance guarantees are all whole pounds. Money is integer cents: prices per pound, per-point premiums and discounts, sale totals, settlement totals, and indemnity amounts are computed and stored as whole cents. Two measurement families carry decimals: moisture is expressed as a percentage rounded half-up to 1 decimal place, and alpha-acid values — a posted `alpha_pct`, a pellet lot's `blended_alpha_pct`, an allocation's `delivered_alpha_pct` — are rounded half-up to 2 decimal places. Contract pricing inputs such as `alpha_floor_pct` and claim inputs such as `coverage_pct` preserve the precision they were supplied with.

Rounding is applied once at the end of a computation, never incrementally. Where an aggregate feeds a rounded result, the system aggregates first and rounds the aggregate once; rounding each component first and summing is a different, forbidden order. The pelletizing yield rule in §3.4 shows the pinned order with a worked contrast.

### 2.8. Validation Priority Order

When several checks could fail on the same request, the system reports failures in a fixed priority order so callers see the most fundamental problem first, and a failure at any tier masks every lower tier. The order is:

1. Authentication — both headers present and the role declared, else `ERR_UNAUTHENTICATED`.
2. Role authorization — the role appears in the endpoint's allowed list, else `ERR_FORBIDDEN`.
3. Path existence — every resource identifier in the path resolves, validated left to right, else `ERR_NOT_FOUND`.
4. Request shape — required body fields present; enum values valid; integer and number ranges respected (`acreage` above zero, `wet_lbs` above zero, prices above zero, `alpha_pct` greater than zero and at most 25, `term_end_year` no earlier than `term_start_year`, `coverage_pct` greater than zero and at most 1, `kiln_window_end` strictly after `kiln_window_start`, `source_lot_ids` carrying at least one entry); datetimes well-formed; and unknown body fields rejected — any failure yields `ERR_INVALID_REQUEST`.
5. Segregation of duties on claim review, decision, and payment, else `ERR_SEGREGATION_OF_DUTIES`.
6. State-machine from-state — the target resource is in a state from which the requested transition exists, else `ERR_INVALID_STATE`.
7. Optimistic concurrency on contract amendments, else `ERR_STALE_VERSION`.
8. Field-season uniqueness on plan creation, else `ERR_FIELD_SEASON_CONFLICT`.
9. The kiln-window buffer rule on kiln loading and redrying, else `ERR_KILN_WINDOW_OVERLAP`.
10. The moisture release gate, else `ERR_MOISTURE_UNSAFE`.
11. Linked-entity usability — the plan is harvesting for lot creation, source lots are dried for pelletizing, a selected sample exists for a spot confirm, the contract is active for an allocation confirm, a prior provisional test exists before a final, every source final is posted before settle, and the plan is complete before claim payment — each surfacing its referential error (`ERR_LOT_NOT_DRIED`, `ERR_SAMPLE_NOT_SELECTED`, `ERR_CONTRACT_NOT_ACTIVE`, `ERR_PROVISIONAL_REQUIRED`, `ERR_FINAL_TEST_REQUIRED`, `ERR_PLAN_NOT_COMPLETE`) as narrated in §3.
12. Aggregate and uniqueness constraints — the acreage ceiling, dried-weight feasibility, single-variety and single-crop-year blending, at most one final test per lot, at most one open claim per plan (`ERR_ACREAGE_EXCEEDED`, `ERR_WEIGHT_IMPOSSIBLE`, `ERR_MIXED_VARIETY`, `ERR_MIXED_CROP_YEAR`, `ERR_DUPLICATE_FINAL_TEST`, `ERR_DUPLICATE_CLAIM`).
13. The buyer credit-limit check at spot-sale confirm, else `ERR_CREDIT_LIMIT_EXCEEDED`.

A call that is both unauthenticated and aimed at a non-existent resource therefore surfaces only `ERR_UNAUTHENTICATED`.

### 2.9. Path Identifier Validation

Endpoint paths in this API are flat — each carries at most one resource identifier, such as a plan, lot, contract, allocation, sale, sample, or claim id. That identifier is validated for existence before any business rule is evaluated, and an unknown identifier is rejected with `ERR_NOT_FOUND` (HTTP 404). Existence checking precedes even request-shape and state checks for the addressed resource, so a caller never receives a business-rule error about a resource that does not exist.

## 3. Business Logic & Workflows

This section follows the crop year in the order work actually happens: land and planting, contracts, the kiln pipeline, the lab, pelletizing and storage, allocation and settlement, the sample and spot channel, insurance, and the year-end rollover.

### 3.1. Fields, Kilns, and the Planting Plan

Land comes first. A `FarmManager` registers each **Field** with a `name` and its total plantable `acreage`, which must be greater than zero, and registers each physical drying **Kiln** with a `name`. These two resources are the operational scaffolding everything else hangs from.

Against a registered field, a `FarmManager` authors a **PlantingPlan** for one crop year, supplying the `field_id`, the `crop_year` the plan covers, the `variety` — one of `CASCADE`, `CENTENNIAL`, `CTZ`, `CITRA`, or `MOSAIC` — and the `planned_acreage`. The planned acreage must be at least 1, and it may not exceed the field's total `acreage`; an overage is rejected with `ERR_ACREAGE_EXCEEDED`. A field accepts only one live plan per season: if a plan that is not `CANCELLED` already exists for the same `field_id` and `crop_year`, the new plan is rejected with `ERR_FIELD_SEASON_CONFLICT`.

At creation the plan computes its `projected_yield_lbs`: the `planned_acreage` multiplied by the variety's base yield per acre — 1800 lbs for `CASCADE`, 2000 for `CENTENNIAL`, 2200 for `CTZ`, 1900 for `CITRA`, and 1700 for `MOSAIC` — an exact integer product with no rounding. The `actual_yield_lbs` stays null until the plan completes; the plan's `status` begins at `DRAFT`.

The plan lifecycle is a `FarmManager`'s progression with a built-in revision loop. Approval moves a plan from `DRAFT` to `GROWING`. Revision sends a `GROWING` plan back to `DRAFT`, but only while no harvest lot has yet been created against it — once cutting has started, the plan can no longer be revised. Opening the harvest moves `GROWING` to `HARVESTING`. Cancellation moves a plan from `DRAFT` or `GROWING` to `CANCELLED`, again only while no harvest lot exists; a plan with lots on the ground is committed. Completion moves a plan from `HARVESTING` to `COMPLETE`, and it is gated on an empty kiln pipeline: no linked harvest lot may remain in `HARVESTED`, `IN_KILN`, or `MOISTURE_CHECK` status, while lots already `DRIED` or `CONSUMED` are allowed. Completion computes the `actual_yield_lbs` as the sum of `dried_lbs` over the plan's linked harvest lots in `DRIED` or `CONSUMED` status — the actual variant of the yield figure, generally different from the projection. Completion deliberately does not touch the plan's insurance claims: any claim's filing-time estimate stands as filed, and the final indemnity variant is computed only at payment (§3.8). Plans are listable with `field_id`, `crop_year`, and `status` filters.

### 3.2. Harvest Lots and the Kiln Pipeline

Once a plan is `HARVESTING`, a `FarmManager` cuts **HarvestLot** records against it, supplying the `planting_plan_id` and the green `wet_lbs` picked in that lot, which must be greater than zero. Creating a lot against a plan in any other status is rejected with `ERR_INVALID_STATE`. The lot copies `variety` and `crop_year` from its plan at creation — denormalized so inventory can be filtered without joining — and opens in `HARVESTED` status, with `kiln_id`, `kiln_window_start`, `kiln_window_end`, `dried_lbs`, `moisture_pct`, and both alpha fields all null until the pipeline fills them.

Loading the kiln moves a lot from `HARVESTED` to `IN_KILN` and records which kiln it occupies and when: the request carries the `kiln_id`, the `kiln_window_start`, and the `kiln_window_end`, and the window end must be strictly after the start. Kiln time is a scarce, schedulable resource governed by a thirty-minute buffer rule. Windows are half-open intervals — the start inclusive, the end exclusive. A proposed window conflicts with an occupying window on the same kiln unless the two are separated by at least thirty minutes on one side or the other: the proposed window must start at or after the occupying window's end plus thirty minutes, or end at or before the occupying window's start minus thirty minutes. The occupying set is every other harvest lot with the same `kiln_id` whose status is `IN_KILN` or `MOISTURE_CHECK`. Adjacency with exactly thirty minutes of clearance is allowed on both sides. A violation is rejected with `ERR_KILN_WINDOW_OVERLAP`; a successful load records the kiln and the window on the lot.

Finishing the drying run moves a lot from `IN_KILN` to `MOISTURE_CHECK` and records its `dried_lbs`. Drying obeys a feasibility envelope derived from the crop's physics: the model treats a lot's bone-dry solids as 24 percent of its wet weight — equivalently, green hops carry 76 percent water — so the recorded `dried_lbs` must be at least the wet weight times 0.24 rounded up to a whole pound, and no more than the wet weight itself. A weight outside that envelope is rejected with `ERR_WEIGHT_IMPOSSIBLE`. A valid finish computes the lot's `moisture_pct`: the dried weight minus 24 percent of the wet weight, that difference divided by the dried weight, expressed as a percentage, rounded half-up to one decimal place.

What happens next depends on that reading. A lot whose `moisture_pct` is above 10.0 percent is not safe to store and may be sent back into the kiln: redrying moves it from `MOISTURE_CHECK` back to `IN_KILN` under a fresh window — supplied again as `kiln_window_start` and `kiln_window_end` and subject to the same thirty-minute buffer rule — and updates the recorded window on the lot. The redry loop may repeat, and each pass through finish-drying recomputes `moisture_pct`. A lot already at or below 10.0 percent cannot be redried — the attempt is rejected with `ERR_INVALID_STATE`; it should be released instead. Release moves a lot from `MOISTURE_CHECK` to `DRIED` and is permitted only when `moisture_pct` is at most 10.0 percent, otherwise `ERR_MOISTURE_UNSAFE`. A released lot stops occupying its kiln: its window no longer participates in the buffer rule. Harvest lots are listable with `planting_plan_id`, `kiln_id`, and `status` filters. The final step of a lot's life — from `DRIED` to `CONSUMED` — happens at the pelletizer (§3.4).

### 3.3. Alpha-Acid Testing and the Regrade Cascade

Alpha-acid content is the crop's quality signal, and it arrives through the lab. A `LabTechnician` posts a **LabTest** naming the `harvest_lot_id`, a `test_type` of `PROVISIONAL` or `FINAL`, and the measured `alpha_pct`, which must be greater than zero and at most 25. A test is accepted once a lot has left the kiln — that is, in `DRIED` or `CONSUMED` status, since a consumed lot's alpha fields deliberately remain available for downstream regrading — while posting against a lot still in the pipeline (`HARVESTED`, `IN_KILN`, or `MOISTURE_CHECK`) is rejected with `ERR_LOT_NOT_DRIED`.

A `PROVISIONAL` result sets the lot's `alpha_pct_provisional`, and the latest posted provisional wins when several are run. A `FINAL` result is stricter: the lot must already carry at least one provisional, otherwise the final is rejected with `ERR_PROVISIONAL_REQUIRED`, and a lot may carry at most one final — a second is rejected with `ERR_DUPLICATE_FINAL_TEST`. A posted final sets the lot's `alpha_pct_final`. Lab tests are immutable records: as noted in §2.4, a fetched test carries only `id` and `created_at` from the common fields, and tests are listable with a `harvest_lot_id` filter.

Posting a final fires the **regrade cascade**. Every pellet lot whose blend includes the tested lot recomputes its `blended_alpha_pct` (§3.4), and every allocation that has been delivered but not yet settled and whose delivered lots include such a pellet lot recomputes its `delivered_alpha_pct` and its `estimated_unit_price_cents` — the provisional pricing variant runs again over the improved alpha data. Allocations already `SETTLED` are never reopened by a regrade.

### 3.4. Pelletizing and Cold-Storage Inventory

Pelletizing turns dried lots into a storable, sellable product. A `FarmManager` creates a **PelletLot** by naming the `source_lot_ids` — at least one entry, since an empty array fails request-shape validation — and the cold-storage `storage_room` the lot will occupy. Every source lot must be `DRIED`, otherwise `ERR_LOT_NOT_DRIED`; all source lots must share one `variety`, otherwise `ERR_MIXED_VARIETY`; and all must share one `crop_year`, otherwise `ERR_MIXED_CROP_YEAR`. A successful pelletize moves every source lot from `DRIED` to `CONSUMED`, copies the shared `variety` and `crop_year` onto the pellet lot, and stamps `entered_storage_at` from the logical clock.

Two figures are computed at creation under a pinned aggregate-then-round order. The `qty_lbs` is the total dried weight of the source lots reduced by an 8 percent processing loss, rounded half-up once to a whole pound — the rounding applies to the aggregate, never per source lot. Consider two source lots of 104 dried lbs each: together 208 lbs, reduced by 8 percent is 191.36, which rounds half-up to 191 lbs. Rounding each lot first would give 96 plus 96, a total of 192 — a different, forbidden order. The `blended_alpha_pct` is the weight-weighted alpha of the blend: for each source lot, the effective alpha is its `alpha_pct_final` when set, otherwise its `alpha_pct_provisional`; the blend is the sum of each lot's dried weight times its effective alpha, divided by the sum of the dried weights, rounded half-up to 2 decimal places, applied once after aggregation. The same `blended_alpha_pct` — not the quantity — is recomputed when a source lot's final test posts a regrade, and again when carryover decay fires at rollover (§3.9).

A pellet lot carries two independent state dimensions. The `inventory_status` — `AVAILABLE` at creation, later `RESERVED`, `SOLD`, or `DELIVERED` — tracks its commercial commitments: drafting a spot sale or confirming an allocation reserves it, cancelling returns it to `AVAILABLE`, a confirmed spot sale marks it `SOLD`, and an allocation delivery marks it `DELIVERED`. The `age_class` — `CURRENT` at creation, eventually `CARRYOVER` — tracks warehouse age and flips only at crop-year rollover. Neither dimension implies the other: a carryover lot can sit `AVAILABLE` or stand `RESERVED`, and a current-crop lot can be sold or delivered without aging. Pellet lots are listable with `variety`, `inventory_status`, and `age_class` filters, plus a `source_lot_ids` membership filter for tracing a harvest lot into the pellet lot that consumed it.

### 3.5. Supply Contracts and Alpha-Adjusted Pricing

The sales desk's instrument is the multi-year **Contract**. A `ContractManager` creates one with the counterparty `brewery_name`, the contracted `variety`, the inclusive term bounds `term_start_year` and `term_end_year` (the end may not precede the start), the `annual_volume_lbs` of pellets contracted per crop year (greater than zero), and the pricing block: `base_price_cents_per_lb` (greater than zero), the `alpha_floor_pct` against which quality is measured (greater than zero, for example 12.0), the `alpha_premium_cents_per_point` added per percentage point of alpha above the floor, and the `alpha_discount_cents_per_point` subtracted per point below it — both per-point rates at least zero. A new contract opens in `DRAFT` with its `consecutive_shortfall_years` counter at 0.

Activation moves a contract from `DRAFT` to `ACTIVE`. Suspension moves an `ACTIVE` contract to `SUSPENDED`, and it is deliberately non-destructive: no allocation changes state, but while a contract is suspended, confirming or delivering its allocations is rejected with `ERR_CONTRACT_NOT_ACTIVE`. Reinstatement moves `SUSPENDED` back to `ACTIVE`, and the suspend–reinstate loop may repeat as often as negotiations require.

Amendments renegotiate terms in place. An amendment is allowed from `DRAFT`, `ACTIVE`, or `SUSPENDED` — attempting one on a completed, defaulted, or terminated contract fails the from-state check with `ERR_INVALID_STATE` — and it is the OCC-guarded write of §2.6: the request must carry `expected_contract_version`, and a stale read is rejected with `ERR_STALE_VERSION`. The body may change any of `annual_volume_lbs`, `base_price_cents_per_lb`, `alpha_floor_pct`, `alpha_premium_cents_per_point`, or `alpha_discount_cents_per_point`; a successful amendment applies the supplied changes and increments the contract's `version` by 1.

Termination moves a contract from `DRAFT`, `ACTIVE`, or `SUSPENDED` to `TERMINATED` and unwinds its open commitments: every allocation of the contract in `PROJECTED`, `CONFIRMED`, or `DELIVERED` moves to `CANCELLED`; each cancelled allocation that had been confirmed releases its reserved pellet lots from `RESERVED` back to `AVAILABLE`; and a delivered allocation keeps its `delivered_lbs` and `delivered_lot_ids` as a historical record — its lots were physically delivered and are not released. Two further contract transitions are system-driven rather than desk-driven and are covered where they fire: a contract defaults when its shortfall counter reaches 2 (§3.6), and it completes when the crop-year rollover carries the calendar past its final contracted year (§3.9).

The pricing rule beneath every delivery and settlement is the **alpha price adjustment**. The alpha gap is the delivered alpha minus the contract's `alpha_floor_pct`, computed exactly in percentage points including fractions — an alpha of 12.75 against a floor of 12.0 is a gap of 0.75 points. When the delivered alpha is at or above the floor, the unit price is the `base_price_cents_per_lb` plus the gap times `alpha_premium_cents_per_point`. When the delivered alpha is below the floor, the unit price is the base minus the shortfall times `alpha_discount_cents_per_point`, but never less than 100 cents per pound — that floor clamps the discount. The result is rounded half-up once, at the very end, to integer cents. When the alpha equals the floor exactly, the unit price equals the base price: no premium, no discount.

### 3.6. Allocation Runs, Pro-Rata Waterfall, and Settlement

Each crop year, a `ContractManager` triggers an **allocation run** for a `crop_year` and `variety` pair, and the system divides that variety's available pellet inventory across the contracts entitled to it. A contract is eligible when its `status` is `ACTIVE`, its `variety` matches the run's, the run's crop year falls inclusively between its `term_start_year` and `term_end_year`, and it does not already hold a non-terminal allocation — one in `PROJECTED`, `CONFIRMED`, or `DELIVERED` — for that crop year. Eligible inventory is every pellet lot of the run's variety in `AVAILABLE` inventory status, of any `age_class` and any crop year; carryover inventory is fair game.

A rerun supersedes its own projections. Before computing anything, any existing `PROJECTED` allocations for the same pair move to `CANCELLED`; allocations in `CONFIRMED`, `DELIVERED`, or `SETTLED` are untouched, and their contracts are excluded from the new run's input set precisely because they already hold a live allocation for the year.

The waterfall itself works in pounds. Let the contracted total be the sum of `annual_volume_lbs` over the eligible contracts, and the available total be the sum of `qty_lbs` over the eligible lots. When the available total meets or exceeds the contracted total, every contract is allocated its full `annual_volume_lbs` with a `shortfall_lbs` of 0. Otherwise each contract's exact share is the available total multiplied by its `annual_volume_lbs` and divided by the contracted total; its base allocation is that exact share rounded down to a whole pound, and the leftover pounds — the available total minus the sum of the base allocations — are then distributed one pound at a time to contracts in descending order of fractional part, ties broken in favor of the contract created earlier, until no pounds remain. Each contract's `shortfall_lbs` is its `annual_volume_lbs` minus its `allocated_lbs`. Two invariants hold at the end of every run: for each contract, allocated plus shortfall equals its annual volume; and the total allocated across contracts equals the smaller of the available and contracted totals.

The run creates one **Allocation** per eligible contract in `PROJECTED` status, recording the `contract_id`, the run's `crop_year`, the contract's `variety`, and the computed `allocated_lbs` and `shortfall_lbs`. The remaining fields are staged: `reserved_lot_ids` and `delivered_lot_ids` start empty, `delivered_lbs` starts at 0, and `delivered_alpha_pct`, `estimated_unit_price_cents`, `delivery_shortfall_lbs`, `unit_price_cents`, and `settlement_total_cents` stay null until their stages arrive. The run responds with the `available_lbs`, the `contracted_total_lbs`, and the `created_allocation_ids`. Allocations are listable with `contract_id`, `crop_year`, and `status` filters, plus `reserved_lot_ids` and `delivered_lot_ids` membership filters for tracing lots through their commitments.

Confirming an allocation moves it from `PROJECTED` to `CONFIRMED` and is gated on the contract being `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE` — this is where a suspension bites. Confirmation makes a FIFO reservation against the warehouse: the system walks the pellet lots of the contract's variety that are `AVAILABLE`, oldest first by `entered_storage_at` with ties broken by earlier `created_at`, and reserves a lot only when doing so does not push the cumulative reserved total above the allocation's `allocated_lbs`; it stops when the cumulative total reaches `allocated_lbs` or the pool is exhausted. Reserved lots move to `RESERVED` and are recorded in the allocation's `reserved_lot_ids`. Because lots are indivisible, an allocation can end up under-reserved when no remaining whole lot fits.

Delivery moves a `CONFIRMED` allocation to `DELIVERED` and consumes the reservation. The `reserved_lot_ids` must be non-empty, otherwise the delivery is rejected with `ERR_EMPTY_DELIVERY`. On success the `delivered_lot_ids` are the reserved ids, `delivered_lbs` is the sum of the reserved lots' `qty_lbs`, and each reserved lot moves from `RESERVED` to `DELIVERED`. Two computed fields land at delivery: `delivered_alpha_pct` is the qty-weighted blend of the delivered lots' `blended_alpha_pct`, rounded half-up to 2 decimal places, and `estimated_unit_price_cents` is the alpha price adjustment of §3.5 run as the provisional variant over that delivered alpha — provisional because a pending final test can still move it through the regrade cascade.

Settlement closes the allocation. Moving from `DELIVERED` to `SETTLED` requires that every source harvest lot of every delivered pellet lot has its `alpha_pct_final` posted, otherwise `ERR_FINAL_TEST_REQUIRED`. Settlement records `delivery_shortfall_lbs` as the `allocated_lbs` minus the `delivered_lbs`, computes the `unit_price_cents` as the alpha price adjustment run as the final variant over the `delivered_alpha_pct` — the formula is identical, but the alpha inputs are now purely final, so the result diverges from the estimate whenever a final differed from its provisional — and sets `settlement_total_cents` to the `delivered_lbs` times the `unit_price_cents`. Settlement also updates the contract's shortfall memory: if the allocation's `shortfall_lbs` plus its `delivery_shortfall_lbs` exceeds zero, the contract's `consecutive_shortfall_years` increments by 1; otherwise the counter resets to 0. When the counter reaches 2, the contract auto-transitions from `ACTIVE` to `DEFAULTED`: every allocation of that contract in `PROJECTED` or `CONFIRMED` moves to `CANCELLED`, and each such confirmed allocation's reserved pellet lots return from `RESERVED` to `AVAILABLE`.

An allocation may also be cancelled outright — by a `ContractManager`, or by the system during contract termination, default, completion, or an allocation-run supersede — moving it from `PROJECTED` or `CONFIRMED` to `CANCELLED`. Cancelling a confirmed allocation releases its reserved lots back to `AVAILABLE` and clears its `reserved_lot_ids`.

### 3.7. Brewery Samples and the Spot Market

Surplus and carryover inventory sells through a sample-first spot channel. A `ContractManager` sends a **BrewerySample** by naming the `pellet_lot_id` and the evaluating `brewery_name`; the lot must be `AVAILABLE` or `RESERVED`, since a lot already `SOLD` or `DELIVERED` has left the channel and yields `ERR_INVALID_STATE`. Each sample carries a system-assigned `sample_round`: 1 plus the count of all prior samples for the same lot-and-brewery pair. A sample opens `SENT`, and the desk later records an `outcome` — `SELECTED` or `REJECTED`, both terminal for that row. Rejection does not close the door: a fresh sample may be sent to the same brewery for the same lot, and it is created with the next `sample_round`, forming a resend loop at the pair level. Samples are listable with `pellet_lot_id`, `brewery_name`, and `status` filters.

With interest established, a `ContractManager` drafts a **SpotSale** against one pellet lot, supplying the `pellet_lot_id`, the `buyer_name`, the negotiated `price_cents_per_lb` (greater than zero), and the buyer-declared `buyer_credit_limit_cents` (at least zero). Drafting is a whole-lot commitment: the lot must be `AVAILABLE` — drafting against a lot already reserved, sold, or delivered fails the from-state check with `ERR_INVALID_STATE` — the sale snapshots the lot's full `qty_lbs` into its own `qty_lbs` at draft time, the lot moves from `AVAILABLE` to `RESERVED`, and the sale opens in `DRAFT` with its `sale_total_cents` null until confirmation.

Confirmation moves a sale from `DRAFT` to `CONFIRMED` behind two gates, evaluated in priority order. First, the quality gate: a sample with the sale's `pellet_lot_id` and `buyer_name` must exist in `SELECTED` status, otherwise `ERR_SAMPLE_NOT_SELECTED`. Second, the fiscal gate: the sale's `qty_lbs` times its `price_cents_per_lb` must not exceed the `buyer_credit_limit_cents`, otherwise `ERR_CREDIT_LIMIT_EXCEEDED`. A successful confirmation sets `sale_total_cents` to that product and moves the lot from `RESERVED` to `SOLD`. Cancelling a draft sale moves it to `CANCELLED` and returns the lot from `RESERVED` to `AVAILABLE`. Spot sales are listable with `pellet_lot_id` and `status` filters.

### 3.8. Crop Insurance: Filing, Segregation of Duties, and Payment

Crop insurance backstops the yield risk on each planned block. A `FarmManager` files an **InsuranceClaim** against a plan that is `GROWING`, `HARVESTING`, or `COMPLETE` — a plan still in `DRAFT` or already `CANCELLED` yields `ERR_INVALID_STATE` — supplying the `planting_plan_id`, the insured `price_election_cents_per_lb` (greater than zero), and optionally the `coverage_pct`, the share of the guarantee yield being insured, which must be greater than 0 and at most 1 and defaults to 0.75 when omitted. A plan carries at most one open claim at a time — one in `FILED`, `UNDER_REVIEW`, or `APPROVED` — and a second filing is rejected with `ERR_DUPLICATE_CLAIM`.

Filing pins two numbers that never move afterward. The `guarantee_lbs` is the plan's `planned_acreage` times the same per-acre base yield table used for projections — 1800 for `CASCADE`, 2000 for `CENTENNIAL`, 2200 for `CTZ`, 1900 for `CITRA`, 1700 for `MOSAIC` — times the `coverage_pct`, rounded half-up to a whole pound. The `indemnity_estimate_cents` is the preliminary indemnity variant: the greater of zero and the `guarantee_lbs` minus the plan's `projected_yield_lbs`, that difference times the `price_election_cents_per_lb`. It is computed once at filing, stored, and not recomputed later — completing the plan does not touch it, by design (§3.1). Filing also records the caller's `X-User-ID` in `filed_by_user_id`, which becomes the segregation-of-duties anchor for everything that follows.

An `InsuranceAdjuster` then drives the claim through review. Beginning review moves a claim from `FILED` to `UNDER_REVIEW`; deciding from `UNDER_REVIEW` records an `outcome` of `APPROVED` or `DENIED`; payment moves an `APPROVED` claim to `PAID`. All three adjuster actions enforce segregation of duties: the caller's `X-User-ID` must differ from the claim's `filed_by_user_id`, and a self-review, self-decision, or self-payment is rejected with `ERR_SEGREGATION_OF_DUTIES`. Payment carries one further gate: the linked plan must be `COMPLETE`, otherwise `ERR_PLAN_NOT_COMPLETE`, because the final indemnity needs the kiln-dried actuals. A successful payment computes `indemnity_final_cents` as the final variant: the greater of zero and the `guarantee_lbs` minus the plan's `actual_yield_lbs`, times the `price_election_cents_per_lb` — diverging from the filing estimate whenever actual production differed from the projection. Claims are listable with `planting_plan_id` and `status` filters.

### 3.9. Crop-Year Rollover

The season closes with an ops run a `FarmManager` triggers: the crop-year rollover. It reads the logical clock's year and runs two sweeps, returning the `carried_over_lot_ids` and the `completed_contract_ids` it touched.

The first sweep ages the warehouse. Every pellet lot whose `age_class` is `CURRENT`, whose `crop_year` is before the clock's year, and whose `inventory_status` is `AVAILABLE` or `RESERVED` flips to `CARRYOVER`; lots already `SOLD` or `DELIVERED` have left the warehouse and are not aged. The flip fires carryover decay exactly once: count the full calendar months between the lot's `entered_storage_at` and the logical clock, subtract a 6-month storage grace period (never going below zero), and shrink the lot's `blended_alpha_pct` by 1 percent per remaining decay month, compounding — formally, multiplied by 0.99 raised to the power of the number of decay months — rounding the result half-up to 2 decimal places. Lots already in `CARRYOVER` are never decayed again by later rollovers.

The second sweep closes out contracts. Every `ACTIVE` contract whose `term_end_year` is before the clock's year transitions to `COMPLETED`; its allocations in `PROJECTED` or `CONFIRMED` are cancelled, and each such confirmed allocation releases its reserved pellet lots from `RESERVED` back to `AVAILABLE`. Note the asymmetry with termination (§3.5): completion does not cancel a `DELIVERED` allocation — a delivery already made in the final year stands.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, drive a state transition, or perform an action return `200 OK`. All responses use the envelope of §2.2, and list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/fields` | Create a field | FarmManager |
| GET | `/api/fields/{field_id}` | Get a field | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/kilns` | Create a kiln | FarmManager |
| GET | `/api/kilns/{kiln_id}` | Get a kiln | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/planting-plans` | Create a planting plan (DRAFT; computes projected yield) | FarmManager |
| GET | `/api/planting-plans/{plan_id}` | Get a planting plan | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/planting-plans` | List planting plans | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/planting-plans/{plan_id}/approve` | DRAFT -> GROWING | FarmManager |
| POST | `/api/planting-plans/{plan_id}/revise` | GROWING -> DRAFT (requires no linked harvest lot) | FarmManager |
| POST | `/api/planting-plans/{plan_id}/open-harvest` | GROWING -> HARVESTING | FarmManager |
| POST | `/api/planting-plans/{plan_id}/complete` | HARVESTING -> COMPLETE; computes actual yield | FarmManager |
| POST | `/api/planting-plans/{plan_id}/cancel` | DRAFT or GROWING -> CANCELLED (requires no linked harvest lot) | FarmManager |
| POST | `/api/contracts` | Create a multi-year supply contract (DRAFT) | ContractManager |
| GET | `/api/contracts/{contract_id}` | Get a contract | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/contracts/{contract_id}/activate` | DRAFT -> ACTIVE | ContractManager |
| POST | `/api/contracts/{contract_id}/suspend` | ACTIVE -> SUSPENDED (non-destructive gate) | ContractManager |
| POST | `/api/contracts/{contract_id}/reinstate` | SUSPENDED -> ACTIVE | ContractManager |
| POST | `/api/contracts/{contract_id}/amendments` | Amend contract terms (OCC-guarded; DRAFT, ACTIVE, or SUSPENDED) | ContractManager |
| POST | `/api/contracts/{contract_id}/terminate` | Terminate; cancels non-terminal allocations and releases reserved lots | ContractManager |
| POST | `/api/harvest-lots` | Create a harvest lot (plan must be HARVESTING) | FarmManager |
| GET | `/api/harvest-lots/{lot_id}` | Get a harvest lot | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/harvest-lots` | List harvest lots | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/harvest-lots/{lot_id}/load-kiln` | HARVESTED -> IN_KILN; records kiln and window; 30-minute buffer rule | FarmManager |
| POST | `/api/harvest-lots/{lot_id}/finish-drying` | IN_KILN -> MOISTURE_CHECK; records dried weight and computes moisture | FarmManager |
| POST | `/api/harvest-lots/{lot_id}/redry` | MOISTURE_CHECK -> IN_KILN with a new window (moisture above 10.0 only) | FarmManager |
| POST | `/api/harvest-lots/{lot_id}/release` | MOISTURE_CHECK -> DRIED (moisture at most 10.0); frees the kiln window | FarmManager |
| POST | `/api/lab-tests` | Post an alpha-acid test; FINAL fires the regrade cascade | LabTechnician |
| GET | `/api/lab-tests/{test_id}` | Get a lab test | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/lab-tests` | List lab tests | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/pellet-lots` | Pelletize DRIED harvest lots into a cold-storage pellet lot | FarmManager |
| GET | `/api/pellet-lots/{lot_id}` | Get a pellet lot | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/pellet-lots` | List pellet lots | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/allocation-runs` | Run pro-rata allocation for a (crop_year, variety) pair; supersedes PROJECTED allocations | ContractManager |
| GET | `/api/allocations/{allocation_id}` | Get an allocation | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/allocations` | List allocations | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/allocations/{allocation_id}/confirm` | PROJECTED -> CONFIRMED; FIFO-reserves AVAILABLE lots of the contract variety | ContractManager |
| POST | `/api/allocations/{allocation_id}/cancel` | PROJECTED or CONFIRMED -> CANCELLED; releases reserved lots | ContractManager |
| POST | `/api/allocations/{allocation_id}/deliver` | CONFIRMED -> DELIVERED; consumes the reserved lots | ContractManager |
| POST | `/api/allocations/{allocation_id}/settle` | DELIVERED -> SETTLED; final price, settlement total, shortfall accrual | ContractManager |
| POST | `/api/spot-sales` | Create a whole-lot spot sale draft; lot AVAILABLE -> RESERVED | ContractManager |
| GET | `/api/spot-sales/{sale_id}` | Get a spot sale | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/spot-sales` | List spot sales | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/spot-sales/{sale_id}/confirm` | DRAFT -> CONFIRMED (selected sample, then credit limit); lot -> SOLD | ContractManager |
| POST | `/api/spot-sales/{sale_id}/cancel` | DRAFT -> CANCELLED; lot RESERVED -> AVAILABLE | ContractManager |
| POST | `/api/samples` | Send a brewery sample (lot must be AVAILABLE or RESERVED) | ContractManager |
| GET | `/api/samples/{sample_id}` | Get a brewery sample | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/samples` | List brewery samples | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/samples/{sample_id}/decide` | SENT -> SELECTED or REJECTED | ContractManager |
| POST | `/api/insurance-claims` | File a crop insurance claim; computes guarantee and preliminary estimate | FarmManager |
| GET | `/api/insurance-claims/{claim_id}` | Get an insurance claim | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| GET | `/api/insurance-claims` | List insurance claims | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |
| POST | `/api/insurance-claims/{claim_id}/begin-review` | FILED -> UNDER_REVIEW (segregation of duties) | InsuranceAdjuster |
| POST | `/api/insurance-claims/{claim_id}/decide` | UNDER_REVIEW -> APPROVED or DENIED (segregation of duties) | InsuranceAdjuster |
| POST | `/api/insurance-claims/{claim_id}/pay` | APPROVED -> PAID (plan must be COMPLETE); computes final indemnity | InsuranceAdjuster |
| POST | `/api/ops/crop-year-rollover` | Year-end rollover: carryover flips with alpha decay, contract completion cascade | FarmManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving) | FarmManager, LabTechnician, ContractManager, InsuranceAdjuster |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_FIELD_SEASON_CONFLICT` | 409 |
| `ERR_KILN_WINDOW_OVERLAP` | 409 |
| `ERR_MOISTURE_UNSAFE` | 422 |
| `ERR_WEIGHT_IMPOSSIBLE` | 422 |
| `ERR_LOT_NOT_DRIED` | 422 |
| `ERR_MIXED_VARIETY` | 422 |
| `ERR_MIXED_CROP_YEAR` | 422 |
| `ERR_DUPLICATE_FINAL_TEST` | 422 |
| `ERR_PROVISIONAL_REQUIRED` | 422 |
| `ERR_FINAL_TEST_REQUIRED` | 422 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_SAMPLE_NOT_SELECTED` | 422 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 |
| `ERR_EMPTY_DELIVERY` | 422 |
| `ERR_ACREAGE_EXCEEDED` | 422 |
| `ERR_DUPLICATE_CLAIM` | 422 |
| `ERR_PLAN_NOT_COMPLETE` | 422 |

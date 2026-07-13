# Distillery DSP API — Product Requirements Document

## 1. Introduction

This document specifies the backend API for a bonded Distilled Spirits Plant (DSP) operating under United States Alcohol and Tobacco Tax and Trade Bureau (TTB) rules. A distillery is a heavily regulated ledger: every proof gallon of spirit that a still produces must be gauged into bond, tracked as it moves through the production, storage, and processing accounts, and eventually accounted for either as a taxpaid removal, an in-bond transfer, an export, or a documented loss. Losses themselves come in three flavors — the evaporative "angel's share" that a barrel gives up while it ages, the small shortfall between what is drawn from a barrel and what actually ends up in bottles, and the wholesale write-off of a destroyed barrel. The invariant that gives this system its shape is conservation: the cumulative proof gallons ever gauged into bond must always equal the sum of what is still under bond, what has been removed, and what has been lost.

Layered on top of the production ledger are the commercial and compliance workflows that a working distillery lives by. Compliance staff shepherd Certificate of Label Approval (COLA) applications through TTB review, record excise tax on removals under the Craft Beverage Modernization Act (CBMA) reduced-rate regime, and file monthly excise reports. Sales staff move finished cases through the three-tier system, self-distribution, the tasting-room point of sale, and members-only club allocation releases, while the tasting room itself books tours against a fixed room capacity. These flows interlock: a barrel cannot be bottled until its label is approved, a three-tier order cannot ship until the goods it draws on have been tax-determined, and a taxpaid removal that empties a run's inventory silently cancels the orders that were still waiting on it.

The purpose of this API is to make those interlocks enforceable and auditable. Because tax buckets and aging losses depend on the passage of time, the server runs on a controllable logical clock rather than wall-clock time, so that gauging, aging, removals, and reporting can be exercised deterministically. Every endpoint is a small, precise transition on this shared ledger; the sections below define the transitions, the arithmetic, and the guard rails.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If `X-User-Role` is missing or is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

There are exactly five roles, spelled precisely as follows:

- **`ProductionManager`** — runs bonded production: mash batches, distillation runs, barreling, and bottling runs.
- **`ComplianceOfficer`** — handles DSP registration, COLA label applications, TTB tax removals, and excise reports.
- **`SalesManager`** — owns wholesale and self-distribution sales orders and controls the club allocation-release window.
- **`TastingRoomStaff`** — runs the tasting-room point of sale and tour bookings.
- **`Customer`** — a direct or club customer who may act only on its own sales orders and tour bookings.

Four of these roles — `ProductionManager`, `ComplianceOfficer`, `SalesManager`, and `TastingRoomStaff` — are operator roles. When `X-User-Role` is any of these, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any sales order or tour booking that references a customer compare the resource's `customer_id` to `X-User-ID`. A `Customer` who invokes a sales-order or tour-booking operation on a row whose `customer_id` does not equal its `X-User-ID` is rejected with `ERR_FORBIDDEN` (HTTP 403). For a list operation, which has no single target row, a `Customer`'s results are instead automatically narrowed to only those sales orders or tour bookings whose `customer_id` equals its `X-User-ID`.

The server evaluates guard conditions in a fixed order, so that the error a caller sees is always the earliest applicable one. Authentication is checked first (`ERR_UNAUTHENTICATED`, 401), then role authorization (`ERR_FORBIDDEN`, 403), then the existence of every path id and every referenced foreign-key id in the body (`ERR_NOT_FOUND`, 404), then — for a `Customer` — ownership of the target row (`ERR_FORBIDDEN`, 403), then body validation of required fields, types, enum legality, and positive quantities (`ERR_VALIDATION`, 422), then the legality of the requested state transition (`ERR_INVALID_STATE`, 409), and finally the operation-specific business rules described throughout Section 3. Where a single operation carries several business rules, their relative order is called out in the workflow that owns them.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of Section 2.5 rather than wall-clock time.
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

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` defaults to 10, has a minimum of 1 and a maximum of 100. The `offset` defaults to 0 and has a minimum of 0. Results are always ordered by `created_at` ascending — oldest first; rows that share a `created_at` value (created at the same logical-clock instant) are further ordered by their creation sequence, i.e. the order in which they were inserted. Each list response reports pagination state in `meta` via `limit`, `offset`, `total_count` (the count of all rows matching the request before the page window is applied), and `has_more` (true when rows remain beyond the current window). Where a list endpoint documents a filter parameter — such as `distillery_id`, `mash_batch_id`, `distillation_run_id`, `barrel_id`, `label_application_id`, `bottling_run_id`, or `customer_id` — the filter narrows the collection before pagination is applied.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id`, which is a UUID with no type prefix. Every resource also carries a `created_at` timestamp, formatted as an ISO 8601 UTC instant with three fractional digits, set from the logical clock at creation. All entities in this system carry the full set of common fields: in addition to `id` and `created_at`, each carries an `updated_at` timestamp (same format, refreshed on every mutation) and a `version` integer that begins at 1 and increments by one on every mutation that changes the resource. A read never advances `version` or `updated_at`; a state transition or a computed-field update does. When one operation mutates several entities, each mutated entity has its own `updated_at` refreshed and its own `version` incremented independently.

### 2.5. The Logical Clock and Temporal Semantics

Time in this system is a server-held logical clock, never wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it continues to read exactly that default. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant; any subsequent creation, fill, removal, or aging computation reads its "now" from this clock. Because barrel aging and the calendar-year CBMA bucket both depend on elapsed logical time, this clock is the single source of temporal truth. A barrel's `fill_date` and a removal's `removal_date` are both stamped from the clock at the moment of the event.

### 2.6. Proof Gallons, Rounding, and the CBMA Ledger

Proof gallons are the fundamental unit of bonded inventory. Wherever a proof-gallon quantity is computed — at gauge, at barrel aging, at bottling completion, and at removal — the result is rounded to one decimal place (the nearest tenth of a proof gallon) using round-half-up. Monetary excise amounts are held in whole cents and rounded half-up to the nearest cent. A proof value is twice the alcohol-by-volume percentage, so a spirit's proof-gallon content is its volume in U.S. gallons multiplied by its proof and divided by 100.

The CBMA reduced-rate regime tracks, per distillery, the taxpaid proof gallons removed so far in the current calendar year in `cbma_pg_removed_ytd`. A distillery's `cbma_rate_tier` is `REDUCED` while `cbma_pg_removed_ytd` is below 100,000 proof gallons, and `STANDARD` once `cbma_pg_removed_ytd` reaches or exceeds 100,000 proof gallons. Because reaching that boundary through ordinary black-box operation is infeasible, an administrative test-driving capability seeds a distillery's `cbma_pg_removed_ytd` directly: given a `distillery_id` and a non-negative `cbma_pg_removed_ytd` value, it sets that field (rounded to the nearest tenth using round-half-up), recomputes `cbma_rate_tier`, and increments the distillery's `version`.

### 2.7. The Bonded Proof-Gallon Ledger and Its Conservation Invariant

Each `Distillery` maintains a running set of proof-gallon accounts that together form an auditable ledger. `total_gauged_pg` is the cumulative proof gallons ever gauged into bond; it only ever increases and serves as the conservation anchor. `production_account_pg` holds gauged spirits not yet barreled; `storage_account_pg` holds spirits filled into barrels and aging; `processing_account_pg` holds bottled spirits still in bond and not yet removed. `removed_pg` is the cumulative proof gallons removed from bond for any reason. Three loss accounts capture leakage: `angel_share_losses_pg` accumulates evaporative loss realized when a barrel is drawn or destroyed, `bottling_losses_pg` accumulates the shortfall between what is drawn and what is bottled, and `destroyed_losses_pg` accumulates the remaining contents written off when a barrel is destroyed.

`bonded_total_pg` is a derived figure: the sum of `production_account_pg`, `storage_account_pg`, and `processing_account_pg` — that is, everything still under bond. It is recomputed on every event that touches those three accounts. The governing invariant, which must hold after every production or removal event, is a conservation identity: `total_gauged_pg` equals the sum of `production_account_pg`, `storage_account_pg`, `processing_account_pg`, `removed_pg`, `angel_share_losses_pg`, `bottling_losses_pg`, and `destroyed_losses_pg`. Every production or removal event moves proof gallons between exactly the accounts named in its workflow, never creating or destroying proof gallons outside this identity.

### 2.8. Cascading State Propagation and Hierarchical Consistency

Several operations trigger multi-hop cascades across entities. When a bottling run completes, its source barrel is emptied, the barrel's distillation run may close once its last open barrel leaves aging, and the run's mash batch is then archived — a four-hop chain from bottling to barrel to run to mash. Separately, when a tax removal reduces a run's available inventory to zero, every still-pending sales order on that run is automatically cancelled. In every cascade, each affected entity independently transitions its own `status`, refreshes its own `updated_at`, and increments its own `version`. The exact preconditions and side effects of each hop are described in the workflows of Section 3.

### 2.9. Optimistic Concurrency Control for Excise Filings

Filing a monthly excise report is guarded by optimistic concurrency control against the parent distillery. The filing request must carry `expected_distillery_version` holding the `version` of the target `Distillery` that the client last observed. If `expected_distillery_version` does not match the distillery's current `version` — because another removal or another filing has advanced the ledger since the client read it — the filing is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a client from snapshotting a removal ledger it has not actually observed. A filing that passes the guard itself increments the distillery's `version`. No other write endpoint takes a version field; the excise-report filing is the only optimistic-concurrency-guarded operation in the system.

### 2.10. Referenced-Resource Resolution

Wherever a request supplies a path id together with one or more foreign-key ids in its body, the server resolves them left to right and rejects the first one that does not exist with `ERR_NOT_FOUND` (HTTP 404). Existence resolution precedes body validation, so a request that both references a missing entity and carries a malformed field surfaces the missing-entity error first.

## 3. Business Logic & Workflows

### 3.1. Registering a Distillery and Its Ledger

A `ComplianceOfficer` registers a bonded premises by supplying a `name`, a `dsp_permit_number` (the TTB basic permit or registry number), and a two-letter `state_code`. On registration, all proof-gallon accounts — `total_gauged_pg`, `production_account_pg`, `storage_account_pg`, `processing_account_pg`, `removed_pg`, `angel_share_losses_pg`, `bottling_losses_pg`, `destroyed_losses_pg`, and `bonded_total_pg` — are initialized to 0, `cbma_pg_removed_ytd` is 0, `cbma_rate_tier` is `REDUCED`, and `club_release_active` is false. Reading a distillery returns the current ledger snapshot.

The club allocation-release window is toggled by a `SalesManager`, who supplies an `active` boolean; the request sets `club_release_active` to the supplied value. This flag gates whether members-only club orders may be paid, as described in the sales workflow.

### 3.2. Mashing and Distillation: From Grain Bill to Gauged Proof Gallons

A `ProductionManager` starts production by creating a mash batch against a distillery, supplying the `distillery_id`, a `grain_bill` recipe descriptor, and the wash `volume_gallons` produced by fermentation. A new batch begins `FERMENTING`. A fermenting batch that will not be used may be dumped by the `ProductionManager`, moving it from `FERMENTING` to `DUMPED`; dumping is legal only from `FERMENTING`.

From a fermenting batch the `ProductionManager` creates a distillation run, referencing the `distillery_id` and the `mash_batch_id`, and declaring the `spirit_type` (one of `WHISKEY`, `GIN`, `VODKA`, `RUM`, or `BRANDY`), the `gauge_method` (`VOLUME` or `WEIGHT`), the `collected_proof` of the spirits collected, the `collected_wine_gallons` of volume collected, and, when weight gauging is intended, the `collected_weight_lbs` net weight. A new run begins `DISTILLING`.

Gauging is the pivotal production event. When the `ProductionManager` gauges a run, the run advances from `DISTILLING` to `GAUGED`. Gauging is legal only from `DISTILLING`; the referenced mash batch must still be `FERMENTING`, otherwise the gauge is rejected with `ERR_MASH_NOT_AVAILABLE`. When the `gauge_method` is `WEIGHT`, `collected_weight_lbs` must be greater than zero, otherwise the gauge is rejected with `ERR_VALIDATION`. The gauge computes the run's `proof_gallons` according to the selected method. Under the `VOLUME` variant, the volume in wine gallons is taken directly from `collected_wine_gallons`. Under the `WEIGHT` variant, the volume in wine gallons is `collected_weight_lbs` divided by 7.28 (the assumed pounds per gallon of spirit); because the two variants derive volume differently, the same collected inputs yield a different `proof_gallons` depending on the method. In both cases, `proof_gallons` is that wine-gallon volume multiplied by `collected_proof` and divided by 100, rounded to the nearest tenth using round-half-up. The run's `remaining_proof_gallons` is initialized equal to its `proof_gallons`, and its `open_barrel_count` starts at 0.

Gauging also moves proof gallons into the ledger and bubbles a state change to the mash batch. The run's newly determined `proof_gallons` is added to the distillery's `total_gauged_pg` and to its `production_account_pg`, and `bonded_total_pg` is recomputed. The referenced mash batch transitions from `FERMENTING` to `DISTILLED`. Once distilled, a batch is archived automatically much later, when its distillation run closes (see the bottling cascade below); a mash batch may transition from `DISTILLED` to `ARCHIVED` only when the run referencing it has reached `CLOSED`.

### 3.3. Barreling and the Angel's Share

Once a run is gauged, the `ProductionManager` fills barrels from it. Filling a barrel references the source `distillation_run_id` and supplies the `char_level` (one of `CHAR_1`, `CHAR_2`, `CHAR_3`, `CHAR_4`), a `rickhouse_position` label, and the `fill_proof_gallons` drawn into the barrel. The barrel's `distillery_id` is inherited from the source run. A new barrel begins `AGING`, its `fill_date` is stamped from the logical clock, and angel's-share evaporation begins accruing from that instant. Filling transfers proof gallons within the ledger: the run's `remaining_proof_gallons` is reduced by `fill_proof_gallons`, the run's `open_barrel_count` is increased by one, the distillery's `production_account_pg` is reduced by `fill_proof_gallons`, and its `storage_account_pg` is increased by the same amount.

Angel's share is computed on demand from the clock. The whole number of months a barrel has aged is the whole months elapsed from its `fill_date` to the current clock, rounded down. Its `angel_share_pg` is `fill_proof_gallons` multiplied by the annual evaporation rate of 0.05 (five percent per year) and by the number of months aged divided by twelve, rounded to the nearest tenth using round-half-up. The barrel's `current_proof_gallons` is `fill_proof_gallons` minus `angel_share_pg`, floored at zero so it can never go negative. Reading a barrel returns its `angel_share_pg` and `current_proof_gallons` evaluated at the current clock.

A `ProductionManager` may destroy an aging barrel, moving it from `AGING` to `DESTROYED`; destruction is legal only from `AGING`. On destruction, the barrel's accrued `angel_share_pg` is realized into the distillery's `angel_share_losses_pg`, and the barrel's entire remaining contents leave storage: the distillery's `storage_account_pg` is reduced by the sum of the barrel's `current_proof_gallons` and its `angel_share_pg`, its `destroyed_losses_pg` is increased by `current_proof_gallons`, and the source run's `open_barrel_count` is reduced by one. If that reduction brings the run's `open_barrel_count` to zero while the run is `GAUGED`, the run closes and its mash batch is archived, exactly as in the bottling cascade below. Destruction is a compensating write-off that keeps the conservation identity intact: every proof gallon that was filled leaves storage, split between the destroyed and angel-share loss accounts.

### 3.4. Label Approval: The COLA Lifecycle

Before any spirit can be bottled under a brand, its label must clear TTB review. A `ComplianceOfficer` creates a label application by supplying the `distillery_id`, the `brand_name`, the `spirit_type` (`WHISKEY`, `GIN`, `VODKA`, `RUM`, or `BRANDY`), the `label_proof` stated on the label, and the `net_contents_ml` of the bottle. A new application begins `DRAFT`, with `ttb_id` and `correction_notes` both unset.

The application moves through review under the `ComplianceOfficer`'s control. Submitting a draft advances it from `DRAFT` to `SUBMITTED`. Deciding a submitted application takes an `outcome`: an `APPROVE` outcome advances it from `SUBMITTED` to `APPROVED` and assigns its `ttb_id` (the TTB COLA identifier), while a `RETURN` outcome moves it from `SUBMITTED` to `NEEDS_CORRECTION` and records the supplied `correction_notes` (an optional string; when it is omitted, `correction_notes` is left unset). An application in `NEEDS_CORRECTION` may be resubmitted, moving it back from `NEEDS_CORRECTION` to `SUBMITTED` and clearing its `correction_notes` — this revision loop may repeat any number of times. Each of these transitions is legal only from the state named as its origin; attempting one from any other state is rejected as an illegal state transition.

### 3.5. Bottling Runs: Scheduling, Line Contention, and Completion

A `ProductionManager` schedules a bottling run by referencing the source `barrel_id` and the `label_application_id`, choosing a bottling `line_id` (`LINE_A` or `LINE_B`), and supplying the half-open interval `scheduled_start` and `scheduled_end` (the end being exclusive, and required to be strictly after `scheduled_start`, otherwise the request is rejected with `ERR_VALIDATION`), the `bottle_size_ml`, the `bottles_per_case`, and the `planned_cases` to produce. The run's `distillery_id` is inherited from the barrel's distillation run. A new run begins `SCHEDULED`. Scheduling checks line contention: if any run that is `SCHEDULED` or `BOTTLING` on the same `line_id` already occupies an interval that overlaps the requested `scheduled_start`-to-`scheduled_end` window, the request is rejected with `ERR_LINE_CONFLICT`; two runs that merely touch — one ending exactly when the next begins — do not conflict.

Starting a scheduled run advances it from `SCHEDULED` to `BOTTLING`. Starting is legal only from `SCHEDULED`; beyond that, two referential guards apply, in order: the referenced label application must be `APPROVED`, otherwise the start is rejected with `ERR_LABEL_NOT_APPROVED`, and the referenced barrel must be `AGING`, otherwise the start is rejected with `ERR_BARREL_NOT_AGING`. A scheduled run that is not needed may instead be cancelled, moving it from `SCHEDULED` to `CANCELLED`; cancellation is legal only from `SCHEDULED`.

Completing a run advances it from `BOTTLING` to `COMPLETED` and is the origin of the four-hop production cascade. Completion is legal only from `BOTTLING`. The bottled proof gallons are computed by a pinned, sum-then-round procedure: first, the total volume in milliliters is the run's `cases_bottled` multiplied by `bottles_per_case` and by `bottle_size_ml`; that total is converted to wine gallons by dividing by 3785.411784 milliliters per gallon; then `bottled_proof_gallons` is the wine-gallon figure multiplied by the referenced label application's `label_proof` and divided by 100, with a single round to the nearest tenth applied once at the very end. Per-case rounding is explicitly not used — all bottle volume is summed before the single final rounding. Completion requires that the barrel's `current_proof_gallons` at the completion clock be at least the computed `bottled_proof_gallons`, otherwise it is rejected with `ERR_INSUFFICIENT_PROOF_GALLONS`.

On completion, the run records its inventory and losses and updates the ledger. The run's `draw_proof_gallons` is set to the barrel's `current_proof_gallons` at that moment, and its `bottling_loss_pg` is `draw_proof_gallons` minus `bottled_proof_gallons` (never negative). The run's `cases_bottled` and `cases_available` are both set to `planned_cases`, `cases_reserved`, `cases_shipped`, and `cases_removed` are 0, `inventory_status` is `IN_STOCK`, and `tax_status` is `IN_BOND`. In the ledger, the drawn proof gallons leave storage into the processing and loss accounts: the distillery's `storage_account_pg` is reduced by `draw_proof_gallons`, its `processing_account_pg` is increased by `bottled_proof_gallons`, and its `bottling_losses_pg` is increased by `bottling_loss_pg`. The barrel is then emptied as the second hop of the cascade: the barrel moves from `AGING` to `EMPTIED`, its accrued `angel_share_pg` is realized into the distillery's `angel_share_losses_pg` and additionally removed from `storage_account_pg`, so that the barrel's entire filled contents — drawn plus evaporated — have left storage. As the third hop, the source distillation run's `open_barrel_count` is reduced by one; if that brings it to zero while the run is `GAUGED`, the run advances from `GAUGED` to `CLOSED`. As the fourth hop, when the run closes, its mash batch advances from `DISTILLED` to `ARCHIVED`.

### 3.6. Tax Removal, Excise, and the CBMA Tiers

A `ComplianceOfficer` removes finished goods from bond by creating a tax removal that references the `bottling_run_id`, declares a `removal_reason` (`TAXPAID` for goods on which excise is due, `TRANSFER_IN_BOND` for an in-bond transfer, or `EXPORT`), and states the `removed_cases`. The removal's `distillery_id` is inherited from the run. The referenced run must be `COMPLETED`, otherwise the removal is rejected as an illegal state transition (`ERR_INVALID_STATE`); and the run must have at least `removed_cases` in `cases_available`, otherwise the removal is rejected with `ERR_INSUFFICIENT_INVENTORY`. For a `TAXPAID` removal only, the distillery's `bonded_total_pg` must be at least the removal's computed proof gallons, otherwise it is rejected with `ERR_INSUFFICIENT_BONDED_PG`; these checks are applied in that order — inventory sufficiency before bonded sufficiency. A removal is created final in the `DETERMINED` state, and its `removal_date` is stamped from the logical clock, which places it in a calendar-year CBMA bucket.

The removal's proof gallons are pro-rated from the run's already-computed bottled total: `removed_proof_gallons` is the run's `bottled_proof_gallons` multiplied by `removed_cases` divided by the run's `cases_bottled`, rounded to the nearest tenth using round-half-up. This authoritative figure uses the actual `removed_cases`, distinguishing it from any provisional estimate made earlier from `planned_cases` at planning time. For a `TAXPAID` removal, the excise is split across the CBMA tiers using the distillery's `cbma_pg_removed_ytd` as it stands before this removal. The portion taxed at the reduced rate, `reduced_rate_pg`, is the smaller of `removed_proof_gallons` and the remaining reduced-rate headroom — that is, 100,000 proof gallons minus the current `cbma_pg_removed_ytd` — but never less than zero. The remainder, `standard_rate_pg`, is `removed_proof_gallons` minus `reduced_rate_pg`. The `excise_tax_due_cents` is `reduced_rate_pg` multiplied by the reduced rate of 270 cents per proof gallon plus `standard_rate_pg` multiplied by the standard rate of 1,350 cents per proof gallon, rounded half-up to whole cents. For any non-`TAXPAID` reason, `reduced_rate_pg` and `standard_rate_pg` are zero, `excise_tax_due_cents` is 0, and no CBMA headroom is consumed.

Every removal reduces the run's on-hand inventory: the run's `cases_available` is reduced by `removed_cases` and its `cases_removed` is increased by the same amount, and if that brings `cases_available` to zero, the run's `inventory_status` becomes `SOLD_OUT`. A `TAXPAID` removal additionally updates the bond and CBMA ledger: the run's `tax_status` becomes `TAX_DETERMINED`, the distillery's `processing_account_pg` is reduced by `removed_proof_gallons`, its `removed_pg` is increased by `removed_proof_gallons`, its `cbma_pg_removed_ytd` is increased by `removed_proof_gallons`, its `cbma_rate_tier` is recomputed against the 100,000 proof-gallon boundary, and `bonded_total_pg` is recomputed. Finally, whenever a removal drives a run's `inventory_status` to `SOLD_OUT`, every sales order on that run whose `fulfillment_status` is still `PENDING` is automatically cancelled, moving each such order's `fulfillment_status` to `CANCELLED`.

### 3.7. Excise Reporting

A `ComplianceOfficer` files a monthly TTB excise return by supplying the `distillery_id`, the `period_month` in `YYYY-MM` form, and the optimistic-concurrency guard `expected_distillery_version`. A filing that carries an `expected_distillery_version` not equal to the distillery's current `version` is rejected on the stale-version check with `ERR_STALE_VERSION`, as described in the concurrency section. A report is created in the `FILED` state. Its `total_removed_pg` is the sum of `removed_proof_gallons` over all `TAXPAID` tax removals whose `removal_date` falls in `period_month`, and its `total_excise_due_cents` is the sum of `excise_tax_due_cents` over those same removals. Filing supersedes any earlier report for the same distillery and `period_month`: the prior `FILED` report for that period transitions to `SUPERSEDED`, and the new report records that prior report's id in its own `supersedes_report_id`; when there is no prior report for the period, `supersedes_report_id` remains unset. A successful filing increments the distillery's `version`.

### 3.8. Customers and the Dual-Axis Sales Order

A `SalesManager` or `TastingRoomStaff` member creates a customer by supplying a `name`, an `email` (the login identity), a ship-to `state_code`, an optional `club_tier` (`NONE`, `SILVER`, `GOLD`, or `RESERVE`, defaulting to `NONE`), and an optional `age_verified` flag (defaulting to false). A `Customer` may read its own record.

A sales order evolves along two independent axes at once: a `payment_status` axis that runs `UNPAID` to `PAID` to `REFUNDED`, and a `fulfillment_status` axis that runs `PENDING` to `ALLOCATED` to either `SHIPPED` or `CANCELLED`. An order is created — by a `SalesManager`, `TastingRoomStaff`, or the owning `Customer` — by supplying the `customer_id`, the `bottling_run_id` that supplies the finished goods, the `channel` (`THREE_TIER`, `SELF_DISTRIBUTION`, `TASTING_ROOM`, or `CLUB`), the `cases` ordered, the `unit_price_cents` per case (a non-negative integer; zero is accepted), and an optional `includes_cocktail` flag (defaulting to false, a tasting-room cocktail add-on). The order's `distillery_id` is inherited from the run. Pricing is computed at creation: the `subtotal_cents` is `unit_price_cents` multiplied by `cases`, and the `total_cents` is that subtotal plus a cocktail surcharge of 1,200 cents when `includes_cocktail` is true, or the subtotal alone otherwise. A new order begins with `payment_status` `UNPAID` and `fulfillment_status` `PENDING`.

Paying an order — permitted to a `SalesManager` or the owning `Customer` — advances `payment_status` from `UNPAID` to `PAID` and, in the same step, advances `fulfillment_status` from `PENDING` to `ALLOCATED`, reserving inventory. Payment is subject to several checks in this order: the order must be `UNPAID` and `PENDING`, otherwise it is rejected as an illegal state transition; the customer's `age_verified` must be true, otherwise it is rejected with `ERR_AGE_NOT_VERIFIED`; if the `channel` is `CLUB`, the distillery's `club_release_active` must be true and the customer's `club_tier` must not be `NONE`, otherwise it is rejected with `ERR_CLUB_NOT_ELIGIBLE`; and the run must have at least `cases` in `cases_available`, otherwise it is rejected with `ERR_INSUFFICIENT_INVENTORY` (the same insufficient-inventory rule that guards tax removal). On a successful payment, the run's `cases_available` is reduced by `cases` and its `cases_reserved` is increased by `cases`; if `cases_available` reaches zero, the run's `inventory_status` becomes `SOLD_OUT`.

Shipping an allocated order is a `SalesManager` action that advances `fulfillment_status` from `ALLOCATED` to `SHIPPED`. The order must be `ALLOCATED` and its `payment_status` must be `PAID`. For a `THREE_TIER` order, the referenced run's `tax_status` must be `TAX_DETERMINED`, otherwise the shipment is rejected with `ERR_NOT_TAX_DETERMINED`; `SELF_DISTRIBUTION` and `TASTING_ROOM` orders are exempt from this requirement. On shipment, the run's `cases_reserved` is reduced by `cases` and its `cases_shipped` is increased by `cases`.

Cancelling an order — permitted to a `SalesManager` or the owning `Customer` — moves `fulfillment_status` to `CANCELLED` from either `PENDING` or `ALLOCATED`. If the order was `ALLOCATED`, its reservation is released: the run's `cases_reserved` is reduced by `cases`, its `cases_available` is increased by `cases`, and if `cases_available` becomes positive again the run's `inventory_status` returns to `IN_STOCK`. This is the compensating counterpart to payment's reservation. Refunding is a `SalesManager` action that advances `payment_status` from `PAID` to `REFUNDED`; it requires that the order be `PAID` and that its `fulfillment_status` already be `CANCELLED`, otherwise it is rejected as an illegal state transition.

### 3.9. The Tasting Room: Tour Bookings and Capacity

A `TastingRoomStaff` member or a `Customer` requests a tour by supplying the `customer_id`, the `distillery_id`, the `start_time` and `end_time` (the end being exclusive, and required to be strictly after `start_time`, otherwise the request is rejected with `ERR_VALIDATION`), the `party_size`, and an optional `includes_tasting` flag (defaulting to false). A new booking begins `REQUESTED`.

Confirming a tour is a `TastingRoomStaff` action that advances it from `REQUESTED` to `CONFIRMED`, subject to two checks applied in order. First, no already-confirmed tour at the same distillery may start within 30 minutes — that is, strictly less than 30 minutes before or after; two starts exactly 30 minutes apart do not conflict — of this tour's `start_time`, otherwise the confirmation is rejected with `ERR_TOUR_OVERLAP`. Second, the sum of `party_size` across all confirmed tours whose windows overlap this tour's `start_time`-to-`end_time` interval, plus this tour's own `party_size`, must not exceed the tasting-room capacity of 20 guests, otherwise the confirmation is rejected with `ERR_TOUR_CAPACITY`. A tour may be cancelled — by a `TastingRoomStaff` member or the owning `Customer` — from either `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`; cancelling a confirmed tour frees the capacity it held for overlapping windows.

## 4. Endpoint Definitions

All endpoints are mounted under `/dsp`. Creation of a new resource returns HTTP 201; all other successful operations — reads, list retrievals, and state transitions on existing resources — return HTTP 200. Request bodies, response payloads, and side effects for each operation are defined by the workflows in Section 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/dsp/_clock/set_current_utc` | Set the server logical clock | ProductionManager, ComplianceOfficer, SalesManager, TastingRoomStaff |
| POST | `/dsp/_ledger/set_cbma_ytd` | Seed a distillery's CBMA year-to-date removed proof gallons | ComplianceOfficer |
| POST | `/dsp/distilleries` | Register a DSP | ComplianceOfficer |
| GET | `/dsp/distilleries/{id}` | Get a distillery (ledger snapshot) | ProductionManager, ComplianceOfficer, SalesManager, TastingRoomStaff |
| GET | `/dsp/distilleries` | List distilleries | ProductionManager, ComplianceOfficer, SalesManager, TastingRoomStaff |
| POST | `/dsp/distilleries/{id}/club-release` | Open or close the club allocation-release window | SalesManager |
| POST | `/dsp/mash-batches` | Create a mash batch | ProductionManager |
| GET | `/dsp/mash-batches/{id}` | Get a mash batch | ProductionManager, ComplianceOfficer |
| GET | `/dsp/mash-batches` | List mash batches | ProductionManager, ComplianceOfficer |
| POST | `/dsp/mash-batches/{id}/dump` | Dump a fermenting mash batch | ProductionManager |
| POST | `/dsp/distillation-runs` | Create a distillation run | ProductionManager |
| GET | `/dsp/distillation-runs/{id}` | Get a distillation run | ProductionManager, ComplianceOfficer |
| GET | `/dsp/distillation-runs` | List distillation runs | ProductionManager, ComplianceOfficer |
| POST | `/dsp/distillation-runs/{id}/gauge` | Gauge the run into proof gallons | ProductionManager |
| POST | `/dsp/barrels` | Fill a barrel from a gauged run | ProductionManager |
| GET | `/dsp/barrels/{id}` | Get a barrel | ProductionManager, ComplianceOfficer |
| GET | `/dsp/barrels` | List barrels | ProductionManager, ComplianceOfficer |
| POST | `/dsp/barrels/{id}/dump` | Destroy an aging barrel | ProductionManager |
| POST | `/dsp/label-applications` | Create a COLA label application | ComplianceOfficer |
| GET | `/dsp/label-applications/{id}` | Get a label application | ProductionManager, ComplianceOfficer |
| GET | `/dsp/label-applications` | List label applications | ProductionManager, ComplianceOfficer |
| POST | `/dsp/label-applications/{id}/submit` | Submit a draft application | ComplianceOfficer |
| POST | `/dsp/label-applications/{id}/decide` | Record a TTB decision (approve or return) | ComplianceOfficer |
| POST | `/dsp/label-applications/{id}/resubmit` | Resubmit a returned application | ComplianceOfficer |
| POST | `/dsp/bottling-runs` | Schedule a bottling run on a line | ProductionManager |
| GET | `/dsp/bottling-runs/{id}` | Get a bottling run | ProductionManager, ComplianceOfficer, SalesManager |
| GET | `/dsp/bottling-runs` | List bottling runs | ProductionManager, ComplianceOfficer, SalesManager |
| POST | `/dsp/bottling-runs/{id}/start` | Start a scheduled run | ProductionManager |
| POST | `/dsp/bottling-runs/{id}/complete` | Complete a run and produce inventory | ProductionManager |
| POST | `/dsp/bottling-runs/{id}/cancel` | Cancel a scheduled run | ProductionManager |
| POST | `/dsp/tax-removals` | Remove finished goods from bond | ComplianceOfficer |
| GET | `/dsp/tax-removals/{id}` | Get a tax removal | ComplianceOfficer |
| GET | `/dsp/tax-removals` | List tax removals | ComplianceOfficer |
| POST | `/dsp/excise-reports` | File a monthly excise report | ComplianceOfficer |
| GET | `/dsp/excise-reports/{id}` | Get an excise report | ComplianceOfficer |
| GET | `/dsp/excise-reports` | List excise reports | ComplianceOfficer |
| POST | `/dsp/customers` | Create a customer | SalesManager, TastingRoomStaff |
| GET | `/dsp/customers/{id}` | Get a customer | SalesManager, TastingRoomStaff, Customer |
| GET | `/dsp/customers` | List customers | SalesManager, TastingRoomStaff |
| POST | `/dsp/sales-orders` | Create a sales order | SalesManager, TastingRoomStaff, Customer |
| GET | `/dsp/sales-orders/{id}` | Get a sales order | SalesManager, TastingRoomStaff, Customer |
| GET | `/dsp/sales-orders` | List sales orders | SalesManager, TastingRoomStaff, Customer |
| POST | `/dsp/sales-orders/{id}/pay` | Pay an order and reserve inventory | SalesManager, Customer |
| POST | `/dsp/sales-orders/{id}/ship` | Ship an allocated order | SalesManager |
| POST | `/dsp/sales-orders/{id}/cancel` | Cancel a pending or allocated order | SalesManager, Customer |
| POST | `/dsp/sales-orders/{id}/refund` | Refund a paid, cancelled order | SalesManager |
| POST | `/dsp/tour-bookings` | Request a tasting-room tour | TastingRoomStaff, Customer |
| GET | `/dsp/tour-bookings/{id}` | Get a tour booking | TastingRoomStaff, Customer |
| GET | `/dsp/tour-bookings` | List tour bookings | TastingRoomStaff, Customer |
| POST | `/dsp/tour-bookings/{id}/confirm` | Confirm a tour | TastingRoomStaff |
| POST | `/dsp/tour-bookings/{id}/cancel` | Cancel a tour | TastingRoomStaff, Customer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_MASH_NOT_AVAILABLE | 409 |
| ERR_LABEL_NOT_APPROVED | 409 |
| ERR_BARREL_NOT_AGING | 409 |
| ERR_INSUFFICIENT_PROOF_GALLONS | 409 |
| ERR_LINE_CONFLICT | 409 |
| ERR_NOT_TAX_DETERMINED | 409 |
| ERR_INSUFFICIENT_INVENTORY | 409 |
| ERR_INSUFFICIENT_BONDED_PG | 409 |
| ERR_AGE_NOT_VERIFIED | 403 |
| ERR_CLUB_NOT_ELIGIBLE | 409 |
| ERR_TOUR_OVERLAP | 409 |
| ERR_TOUR_CAPACITY | 409 |
| ERR_STALE_VERSION | 412 |

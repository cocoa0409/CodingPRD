# Hospital Linen Distribution API — Product Requirements Document

## 1. Introduction

Hospital linen services sit at an awkward intersection of clinical safety and contract finance. Every day, exchange carts cycle clean sheets, towels, patient gowns, and isolation garments to nursing units while soiled linen flows back out to an external laundry vendor by the pound. Par levels must hold on every unit, clean-storage practices must be attested, isolation linen must follow a double-bag protocol, and emergency reserves must be reachable within minutes during a patient surge. Meanwhile the vendor invoice is only ever provisionally known at pickup time — true cost emerges piece by piece as clean linen returns, losses accumulate, and quality complaints are adjudicated into credits.

This document specifies the Hospital Linen Distribution API, the system of record for that entire loop. It governs facility contract terms, per-unit par configuration, the exchange cart cycle from scheduling through unit-side recount, weighed soiled manifests, vendor returns with wash-life retirement, shrinkage investigation, dual-basis vendor invoicing with segregation of duties, complaint-driven credits, surge posture with reserve allocation, and cost-per-adjusted-patient-day reporting. The API is deliberately ledger-minded: every piece of linen is accounted for at all times, every cent of billing can be traced to a weight ticket or a returned piece count, and every cross-role handoff is explicit.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules that apply uniformly to every resource and endpoint.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. The system recognizes five roles: `LinenManager`, `EVSOperator`, `LaundryVendor`, `UnitClerk`, and `InfectionControlOfficer`. A request with missing or blank headers, or whose role is not one of these declared roles, is rejected with `ERR_UNAUTHENTICATED`. Access to each operation is restricted by role as enumerated in §4; an attempt to perform an operation outside the caller's role is rejected with `ERR_UNAUTHORIZED_ROLE`. Two further role-adjacent rules exist: a `UnitClerk` acting on a resource belonging to a different unit is rejected with `ERR_UNIT_OWNERSHIP`, and invoice finalization attempted by the same user who created the invoice is rejected with `ERR_SEGREGATION_OF_DUTIES`.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `UnitClerk`, `X-User-ID` is the `id` of the acting `Unit`; ownership checks on any resource that references a unit compare the resource's `unit_id` field to `X-User-ID`. When `X-User-Role` is `LinenManager`, `EVSOperator`, `LaundryVendor`, or `InfectionControlOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `recorded_by_user_id` on a soiled manifest, or as `created_by_user_id` and `finalized_by_user_id` on an invoice — but never treats it as the `id` of a persisted entity.

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

Endpoints returning lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to those bounds rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter specifies how many items to skip and defaults to 0; negative values are clamped to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order, with ties broken by creation order, oldest first. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`. Individual list endpoints additionally accept the resource-specific filter query parameters named in §3 (for example, units may be filtered by `facility_id` or `unit_tier`).

### 2.4. Common Resource Properties

Every resource in the system — Facility, Unit, LinenStock, ParLevel, CartExchangeRun, SoiledManifest, VendorInvoice, Complaint, and SurgeEvent — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, uniquely identifying the resource.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation, including mutations caused by cascaded derived-field recomputation (for example, when a surge activation rewrites a par level's effective par, or a manifest return moves a stock's piece counters). Within a single request a resource's `version` (and `updated_at`) advances at most once, however many of its fields that request mutates, and a resource the request leaves untouched is not bumped at all.

### 2.5. The Logical Clock

All business timing in the system is governed by a logical clock rather than wall-clock time; every server-generated timestamp — `created_at`, `updated_at`, `api_request_timestamp`, and `completed_at` alike — reads this clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. An administrative test-driving capability, restricted to `LinenManager`, sets the logical clock to a supplied `to_iso8601` instant — any valid instant is accepted, with no monotonicity constraint — and returns the resulting `current_utc`. The logical clock determines cart-run completion timestamps (`completed_at`), lateness evaluation (`late_delivery`), and the trailing 30-day window used for unit quality standing.

### 2.6. Monetary Values, Rates, and Rounding

All monetary amounts are represented as integer cents; no fractional cents are stored or returned. The standard rounding method is round half up. Two rounding disciplines are pinned and may not be reordered: per-line invoice amounts are rounded before any summation takes place, and a stock's per-piece wash rate — its `piece_weight_lbs` multiplied by the facility's `rate_per_lb_cents`, rounded half up to a whole cent — is computed once per stock and then reused wherever a per-piece rate is needed. Derived ratios that are not integer cents, namely cost per adjusted patient day and the cumulative loss rate, are carried at exactly two decimal places, rounded half up.

### 2.7. Piece Conservation and Inventory Non-Negativity

Every piece of linen in a facility is accounted for at all times by the counters on its `LinenStock` row: `in_circulation` (clean pieces available to restock), `in_wash` (pieces in the soiled-to-vendor pipeline), `reserve_pieces` (emergency reserve), `retired_pieces` (condemned or wash-life-expired), and `lost_pieces` (cumulative shrinkage). Piece movements between these counters are atomic within the request that triggers them — a cart completion, a manifest creation, a vendor return, a surge allocation, or an adjustment either applies all of its counter mutations or none of them. Retired pieces leave circulation permanently, keeping the total accounted pieces conserved. No counter may ever be driven below zero; a return or adjustment that would do so is rejected with `ERR_NEGATIVE_INVENTORY`.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each requires its version field as a non-optional input:

- Updating a par level requires `expected_par_level_version`, carrying the client's last observed `version` of that par level. If the par level's current `version` has advanced since the client last read it — for example because a surge activation or closure cascade rewrote its effective par and bumped its version — the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a par configuration it has not observed.
- Recording a stock adjustment requires `expected_linen_stock_version`, carrying the client's last observed `version` of that linen stock. If the stock's current `version` has advanced since the client last read it — for example because a cart-run completion or a manifest return mutated its counters and bumped its version — the adjustment is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not listed here do not take a version field.

### 2.9. Validation Order

When several checks could reject the same request, they are evaluated in a fixed order so that the surfaced error is deterministic. The order is: first, authentication — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`). Second, role authorization for the endpoint, including the conditional complaint-role rule (`ERR_UNAUTHORIZED_ROLE`). Third, segregation of duties on invoice finalization (`ERR_SEGREGATION_OF_DUTIES`). Fourth, existence — every path identifier and every body foreign-key reference, validated left to right, with the first missing reference surfacing as `ERR_NOT_FOUND`. Fifth, request shape — required fields present, enum members valid, numeric ranges respected (`ERR_INVALID_REQUEST`). Sixth, optimistic concurrency (`ERR_STALE_VERSION`). Seventh, state guards — the resource must be in a valid from-state for the requested transition (`ERR_INVALID_STATE`, or `ERR_ALREADY_TERMINAL` when the resource is already in a terminal state), unit-clerk ownership (`ERR_UNIT_OWNERSHIP`), surge-posture blocks (`ERR_FACILITY_IN_SURGE`), and invoice-creation manifest status. Eighth, safety attestations — isolation protocol acknowledgement (`ERR_ISOLATION_PROTOCOL_REQUIRED`) and clean-storage attestation (`ERR_STORAGE_NOT_ATTESTED`). Ninth, temporal window rules (`ERR_INVALID_WINDOW`, `ERR_RUN_WINDOW_CONFLICT`, `ERR_SURGE_WINDOW_CONFLICT`). Tenth, referential integrity — linkage, uniqueness, and configuration prerequisites (`ERR_CART_RUN_ALREADY_LINKED`, `ERR_MANIFEST_ALREADY_INVOICED`, `ERR_PAR_LEVEL_CONFLICT`, `ERR_NO_ISOLATION_LINE`, `ERR_NO_PAR_LEVEL`). Eleventh and last, fiscal and count guards (`ERR_COUNT_EXCEEDS_ON_HAND`, `ERR_NEGATIVE_INVENTORY`, `ERR_CONTRACT_CAP_EXCEEDED`). Because of this ordering, a missing header surfaces as `ERR_UNAUTHENTICATED` even when the request body is also malformed, and a stale version surfaces as `ERR_STALE_VERSION` before any state-transition check runs.

### 2.10. Resource References and Facility Scoping

All resources are peers under the API root; relationships between them are carried by identifier fields in request bodies rather than by nested URL paths. Wherever such a reference appears — `facility_id`, `unit_id`, `stock_id`, `manifest_id`, `invoice_id`, or the elements of a `cart_run_ids` or `manifest_ids` list — the referenced resource must exist, and list elements must additionally belong to the facility given in the same request. References are validated left to right; the first identifier that does not resolve (or resolves to a resource outside the given facility's scope) rejects the request with `ERR_NOT_FOUND`, before any business rule is evaluated.

## 3. Business Logic & Workflows

### 3.1. Facility Onboarding, Nursing Units, and the Linen Catalog

A `LinenManager` begins by registering a **Facility** with its display `name` and its vendor contract terms: `rate_per_lb_cents`, the contracted wash rate in cents per pound applied to all linen categories; `isolation_surcharge_pct`, a surcharge fraction (for example 0.25) applied to any manifest or invoice line flagged as isolation; and optionally `monthly_cap_cents`, a contract cap on a single invoice's final total — when omitted it is null and no cap is enforced. `rate_per_lb_cents` must be an integer greater than or equal to zero, `isolation_surcharge_pct` a number greater than or equal to zero, and `monthly_cap_cents`, when present, an integer greater than or equal to zero; violations are rejected with `ERR_INVALID_REQUEST`. A new facility starts with `surge_posture` of `NORMAL` and a `credit_balance_cents` of zero; the credit balance is a vendor-credit pool that later receives credits from verified complaints whose invoice is already settled or not yet finalized.

Within a facility, a `LinenManager` registers each nursing **Unit** by supplying the `facility_id`, a unit `name` (for example "4 West" or "ICU"), and a `unit_tier` of either `CRITICAL` or `STANDARD` — the tier drives the order of surge reserve allocation. A unit's `quality_flag` starts at `CLEAR`; the rule that later flips it to `WATCH` lives with the complaint workflow in §3.7. The unit list may be filtered by `facility_id` or `unit_tier`.

The linen catalog is built item by item. Registering a **LinenStock** takes the `facility_id`; a `sku` item code that must be unique within the facility — a duplicate `sku` is rejected with `ERR_INVALID_REQUEST`; a `display_name` such as "Flat Sheet Twin"; a `category` of `FLATWORK`, `TERRY`, `PATIENT_APPAREL`, or `ISOLATION`; the `piece_weight_lbs` clean weight of one piece, which drives every weight-to-piece conversion; `unit_cost_cents`, the replacement cost per piece; `max_wash_cycles`, the wash-life limit whose crossings retire pieces; `reorder_point_pieces`, the availability threshold that drives stock posture; and the seeded opening balances `opening_pieces` and `opening_reserve_pieces`. Validation requires `piece_weight_lbs` to be a number strictly greater than zero; `unit_cost_cents`, `reorder_point_pieces`, `opening_pieces`, and `opening_reserve_pieces` to be integers greater than or equal to zero; and `max_wash_cycles` to be an integer of at least one — violations are rejected with `ERR_INVALID_REQUEST`. At creation, `in_circulation` is seeded from `opening_pieces`, `reserve_pieces` from `opening_reserve_pieces`, and `in_wash`, `retired_pieces`, `lost_pieces`, and `wash_cycles_completed` all begin at zero; `shrinkage_status` begins `NORMAL`.

A stock's `posture` is recomputed whenever `in_circulation` or `reserve_pieces` changes, including at creation. The available supply is the sum of `in_circulation` and `reserve_pieces`. When the available supply is strictly below `reorder_point_pieces`, posture is `CRITICAL`; otherwise, when it is strictly below one and a half times `reorder_point_pieces` rounded down to a whole piece, posture is `LOW`; otherwise it is `SUFFICIENT`. The stock list may be filtered by `facility_id`, `category`, or `posture`.

Found linen, donations, and write-offs are recorded by a `LinenManager` as a stock adjustment carrying `delta_pieces` (positive for found or donated pieces, negative for write-offs), a free-text `reason`, and the OCC field `expected_linen_stock_version` described in §2.8. The delta is applied to `in_circulation`, and the stock's `version` increments by one. If applying the delta would drive any counter negative, the adjustment is rejected with `ERR_NEGATIVE_INVENTORY`.

### 3.2. Par Levels and Exchange Cart Scheduling

A **ParLevel** configures how many pieces of one item one unit should hold. A `LinenManager` creates it with `unit_id`, `stock_id`, `base_par_quantity` (an integer greater than or equal to zero), and a `cart_cycle` cadence label of `DAILY`, `TWICE_DAILY`, or `WEEKLY`. The pair of `unit_id` and `stock_id` is unique: configuring a second par level for an existing pair is rejected with `ERR_PAR_LEVEL_CONFLICT`. A new par level starts with `on_hand` at zero and `effective_par` equal to `base_par_quantity`. Thereafter `effective_par` tracks surge posture: while the facility's `surge_posture` is `SURGE`, it is `base_par_quantity` multiplied by the active surge's `par_multiplier`, rounded up to the next whole piece; otherwise it is simply `base_par_quantity`. The par-level list may be filtered by `unit_id` or `stock_id`.

A `LinenManager` may update a par level's `base_par_quantity`, its `cart_cycle`, or both, but only while the facility is not in surge — a par-level edit attempted while the facility's `surge_posture` is `SURGE` is rejected with `ERR_FACILITY_IN_SURGE`. The update is OCC-guarded by `expected_par_level_version` per §2.8, recomputes `effective_par` when not in surge, and increments the par level's `version` by one.

With pars in place, an `EVSOperator` schedules a **CartExchangeRun** for a unit by supplying `unit_id`, `scheduled_start`, and `scheduled_end` (both ISO 8601 instants). The window end must be after its start, or the request is rejected with `ERR_INVALID_WINDOW`. A unit with no par levels configured cannot have a run scheduled at all — the attempt is rejected with `ERR_NO_PAR_LEVEL`. Scheduling also enforces separation between a unit's runs: the new window must not overlap, and must leave at least two hours clear against, the window of any other run of the same unit that has not yet reached `RECONCILED`; violations are rejected with `ERR_RUN_WINDOW_CONFLICT`. A newly scheduled run starts in `SCHEDULED` status with `manifest_id` null, `shortage_flag` false, `completed_at` null, `late_delivery` false, `soiled_lines` and `restock_lines` empty, and `storage_attested` null (the attestation is set true at completion and carried on the run thereafter). The cart-run list may be filtered by `unit_id`, `status`, or `manifest_id`.

### 3.3. Cart Completion, Restocking, and the Dispute–Recount Cycle

Completing a cart run is the daily heartbeat of the system, performed by an `EVSOperator`. The completion payload carries `soiled_lines` — one entry per collected item, each naming a `stock_id` and the soiled `pieces` count collected from the unit (piece counts must be zero or greater); duplicate `stock_id` entries within the list are summed into a single per-stock count — and `storage_attested`, the unit's clean-storage compliance attestation. Completion without a true `storage_attested` is rejected with `ERR_STORAGE_NOT_ATTESTED`. Each soiled line's `pieces` must not exceed the unit's current `on_hand` for that stock — a stock with no par level configured on the unit counts as `on_hand` zero — or the completion is rejected with `ERR_COUNT_EXCEEDS_ON_HAND`.

On completion the run moves from `SCHEDULED` to `COMPLETED`, and restocking is computed line by line. First the unit's `on_hand` for each collected stock is reduced by the soiled pieces. Then, for every par level configured on the unit — visited in par-level creation order, whether or not its item was collected — the deficit is the item's `effective_par` minus the unit's post-collection `on_hand`, or zero when that difference is negative. Triage applies under scarcity: when the stock's `posture` is `CRITICAL` and the unit's `unit_tier` is `STANDARD`, the deficit is halved and rounded down before delivery is computed. The delivered quantity is the smaller of the deficit and the stock's `in_circulation`. The delivered pieces are added to the unit's `on_hand` and subtracted from the stock's `in_circulation`, while the soiled pieces are added to the stock's `in_wash`. The run records what was actually delivered as `restock_lines` — one entry per par level of the unit, in par-level creation order, each naming a `stock_id` and its delivered `pieces`, including zero-piece entries — and `shortage_flag` is set to true when any restock line delivered fewer pieces than its deficit. Finally `completed_at` is stamped from the logical clock, and `late_delivery` is set to true when `completed_at` falls after `scheduled_end`.

Count confirmation belongs to the unit. A `UnitClerk` whose `X-User-ID` equals the run's `unit_id` — a mismatch is rejected with `ERR_UNIT_OWNERSHIP` — may dispute a `COMPLETED` run, moving it to `DISPUTED` with an optional `reason` (accepted but not persisted or returned). From `DISPUTED`, the clerk submits a recount carrying `corrected_soiled_lines` (aggregated per `stock_id` exactly like completion's `soiled_lines`); each corrected line's `pieces` must not exceed the soiled pieces currently recorded for that stock on the run — a stock absent from the recorded lines counts as zero, and a prior recount's corrections count as the recorded values — or the recount is rejected with `ERR_INVALID_REQUEST` (this count check is evaluated after the state and ownership guards). A recount moves the run from `DISPUTED` to `RECOUNTED`, rewrites the run's recorded `soiled_lines` with the corrected counts, and applies compensation: for each corrected line, the unit's `on_hand` increases by the difference between the currently recorded and corrected soiled counts, and the stock's `in_wash` decreases by the same difference. A restock top-up then follows per corrected line's stock: the top-up quantity is the smaller of the remaining deficit — `effective_par` minus the corrected `on_hand`, or zero when that difference is negative — and the stock's `in_circulation`; the top-up is added to `on_hand` and subtracted from `in_circulation`, and no triage halving applies to it. Overstock above par that results from this compensation is allowed and is not clamped. If the unit is still dissatisfied, a `RECOUNTED` run may be disputed again, returning to `DISPUTED` — the dispute–recount cycle may repeat. When the unit is satisfied, the clerk confirms final counts: reconciliation moves a run from `COMPLETED` to `RECONCILED`, or from `RECOUNTED` to `RECONCILED`, and `RECONCILED` is terminal — any further transition attempt on a terminal resource is rejected with `ERR_ALREADY_TERMINAL`, while a transition from any other invalid from-state is rejected with `ERR_INVALID_STATE`.

### 3.4. Soiled Manifests and the Isolation Handling Protocol

Once cart runs are reconciled, an `EVSOperator` assembles a **SoiledManifest**: the weighed, vendor-bound record of soiled linen. The creation payload carries `facility_id`, the `cart_run_ids` being consolidated, weighed `lines` — each naming a `stock_id` (which must resolve to a stock of the given facility, else `ERR_NOT_FOUND`), a `weight_lbs` strictly greater than zero, and an `isolation_flag` — and an optional `isolation_protocol_ack` that defaults to false. Every element of `cart_run_ids` must exist and belong to the given facility (`ERR_NOT_FOUND`), and every referenced run must be in `RECONCILED` status and not already linked to another manifest; a run that fails either condition rejects the creation with `ERR_CART_RUN_ALREADY_LINKED`.

Each manifest line's expected piece count is derived from the dock scale: `weight_lbs` divided by the stock's `piece_weight_lbs`, rounded half up to a whole piece; the derived value is carried on the line as `expected_pieces` in manifest responses. Because the dock scale is more authoritative than unit-floor counts, creation applies a dock-scale recount adjustment per line: the stock's `in_wash` increases by the expected piece count minus the soiled pieces recorded for that stock across the linked cart runs. The linked runs' `manifest_id` is set to the new manifest, `recorded_by_user_id` captures the creator's `X-User-ID`, and the manifest starts in `DISPATCHED` status with `invoice_id` null. The manifest list may be filtered by `facility_id`, `status`, or `invoice_id`.

Isolation linen — Category `ISOLATION` items and any line whose `isolation_flag` is true — travels under a double-bag, red-bag handling protocol. When any line of a manifest has `isolation_flag` set to true, the creation payload must carry `isolation_protocol_ack` as true; a manifest that omits the acknowledgement is rejected with `ERR_ISOLATION_PROTOCOL_REQUIRED`.

### 3.5. Vendor Returns, Wash-Life Retirement, and Shrinkage Reconciliation

Clean linen comes back through the vendor. A `LaundryVendor` records a return against a `DISPATCHED` manifest by supplying `returned_lines`, each naming a `stock_id`, the clean `pieces` returned, and the `condemned_pieces` rejected at the vendor — both counts are required integers greater than or equal to zero (send `condemned_pieces` zero when nothing is condemned). Every returned line's stock must appear among the manifest's `lines`; an unknown stock is rejected with `ERR_INVALID_REQUEST`. A return may not drive inventory negative: per line, the stock's `in_wash` minus the sum of the line's `pieces`, its `condemned_pieces`, and the line's lost amount — the positive difference between the line's expected pieces and the sum of returned and condemned pieces, or zero when that difference is not positive — must remain at least zero, or the return is rejected with `ERR_NEGATIVE_INVENTORY`.

A successful return moves the manifest from `DISPATCHED` to `RETURNED` and mutates the stock per line. `wash_cycles_completed` increases by the returned `pieces`. Wash-life retirement follows a first-in-first-out rotation approximation: the number of multiples of `max_wash_cycles` reached by the new cumulative wash count minus the number reached by the prior cumulative count — each count divided by `max_wash_cycles` and rounded down — gives the pieces retired at this crossing, capped at the line's returned pieces. `retired_pieces` increases by the condemned pieces plus these newly retired pieces. `in_circulation` increases by the returned pieces minus the newly retired ones, since retired pieces leave circulation. `in_wash` decreases by the returned pieces, the condemned pieces, and the lost amount.

Reconciliation closes the loop. A `LinenManager` reconciles a `RETURNED` manifest, moving it to `RECONCILED` — the manifest's terminal state. Per line, the lost amount computed as above is added to the stock's `lost_pieces`. The stock's cumulative loss rate is then recomputed across all `RECONCILED` manifests of the facility — manifests still `DISPATCHED` or `RETURNED` are excluded — as one hundred times the total lost pieces divided by the total expected pieces, rounded half up to two decimal places. When that rate reaches or exceeds 5.00 percent, the stock's `shrinkage_status` flips from `NORMAL` to `INVESTIGATION`; this flag is sticky and never returns to `NORMAL` automatically. Reconciliation also resolves quality fallout: every complaint referencing this manifest that is currently `VERIFIED` automatically transitions to `RESOLVED`, rewash resolution being implied by the reconciliation itself.

### 3.6. Vendor Invoicing: Provisional Weight-Based and Final Piece-Count Billing

Billing runs in two passes that intentionally diverge. A `LinenManager` opens a **VendorInvoice** by supplying `facility_id`, the `manifest_ids` to bill, `period_start` and `period_end` (inclusive billing bounds; the end must be after the start, and a violation is rejected as `ERR_INVALID_REQUEST`), and `period_adjusted_patient_days`, which must be at least one. Every element of `manifest_ids` must exist and belong to the given facility (`ERR_NOT_FOUND`); each referenced manifest must be in `RETURNED` or `RECONCILED` status (a manifest in any other status rejects creation with `ERR_INVALID_STATE`); and no referenced manifest may already belong to another invoice (`ERR_MANIFEST_ALREADY_INVOICED`).

Creation computes `provisional_total_cents` on a weight basis, using every line of every linked manifest, whether that manifest is `RETURNED` or already `RECONCILED` at creation time. Each line's amount is its `weight_lbs` multiplied by the facility's `rate_per_lb_cents`, rounded half up to a whole cent; when the line's `isolation_flag` is true, a surcharge equal to that rounded line amount multiplied by the facility's `isolation_surcharge_pct`, itself rounded half up to a whole cent, is added. The provisional total is the sum of these per-line amounts — per-line rounding always happens before summation. The invoice starts in `PROVISIONAL` status, the linked manifests' `invoice_id` is set, `created_by_user_id` captures the creator's `X-User-ID`, `credit_total_cents` starts at zero, and `final_total_cents`, `billed_total_cents`, and `cost_per_apd_cents` remain null until finalization. The invoice list may be filtered by `facility_id` or `status`.

Finalization reconciles billing to piece counts. It is permitted from `PROVISIONAL` and again from `DISPUTED`, but three guards apply first: segregation of duties requires the finalizing user's `X-User-ID` to differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`); every linked manifest must be `RECONCILED` (`ERR_MANIFEST_NOT_RECONCILED`); and when the facility's `monthly_cap_cents` is set, the computed final total must not exceed it (`ERR_CONTRACT_CAP_EXCEEDED`). The evaluation order is pinned to break any apparent cycle between credits and totals: first the per-piece rate is computed once per stock — `piece_weight_lbs` multiplied by `rate_per_lb_cents`, rounded half up to a whole cent; second, `final_total_cents` is computed as the sum over every returned line of the line's returned `pieces` multiplied by its stock's per-piece rate, with an isolation surcharge — the line amount multiplied by `isolation_surcharge_pct`, rounded half up to a whole cent — added whenever the corresponding manifest line was isolation-flagged; third, `credit_total_cents` is taken from the verified complaints routed to this invoice; fourth, `billed_total_cents` is the final total minus the credit total, and it is recomputed on every later credit change. `cost_per_apd_cents` is `billed_total_cents` divided by `period_adjusted_patient_days`, rounded half up to two decimal places. `finalized_by_user_id` records the finalizing user. Re-finalization after a dispute recomputes all three derived figures fresh.

From `FINALIZED`, a `LaundryVendor` may dispute the invoice — moving it to `DISPUTED` with an optional `reason` (accepted but not persisted or returned) — and a `LinenManager` may record payment, moving it to `SETTLED`, which is terminal. Because the provisional pass uses vendor-scale weights while the final pass uses returned piece counts, the two totals legitimately diverge for identical manifests; the provisional figure is a billing estimate, never a liability floor.

### 3.7. Quality Complaints, Credits, and Unit Watch Standing

A `UnitClerk` files a **Complaint** for their own unit — the payload's `unit_id` must equal the clerk's `X-User-ID`, or the filing is rejected with `ERR_UNIT_OWNERSHIP` — by naming the `manifest_id` and `stock_id` the complaint refers to, a `complaint_type` of `STAINS`, `TEARS`, `FOREIGN_OBJECT`, `ODOR`, or `ISOLATION_BREACH`, and `pieces_affected`, which must be at least one. An `ISOLATION_BREACH` complaint additionally requires the referenced manifest to contain an isolation-flagged line for the referenced stock; without one the filing is rejected with `ERR_NO_ISOLATION_LINE`. A new complaint starts `OPEN` with `credit_cents` zero and `routed_invoice_id` null. The complaint list may be filtered by `unit_id`, `stock_id`, `manifest_id`, or `status`.

Adjudication is role-split by complaint type: verifying or rejecting an `ISOLATION_BREACH` complaint is reserved for an `InfectionControlOfficer`, while all other complaint types are adjudicated by a `LinenManager`; the wrong role is rejected with `ERR_UNAUTHORIZED_ROLE` (the conditional check is evaluated once the complaint has been loaded, so an unknown complaint id surfaces `ERR_NOT_FOUND` first). Verification moves an `OPEN` complaint to `VERIFIED` and prices its credit: `credit_cents` is `pieces_affected` multiplied by the stock's per-piece rate computed from the facility's current contracted `rate_per_lb_cents` at verify time — deliberately independent of any invoice's computed totals, which breaks any circularity between credits and billing. The credit is then routed. When the referenced manifest sits on an invoice that is `FINALIZED` or `DISPUTED`, the invoice's `credit_total_cents` increases by the credit and its `billed_total_cents` decreases by the same amount. When the manifest sits on an invoice that is `PROVISIONAL` (not yet finalized) or `SETTLED`, or on no invoice at all, the facility's `credit_balance_cents` increases instead. Either way, `routed_invoice_id` records the invoice containing the manifest at verify time, remaining null only when the manifest was not yet invoiced. Rejection moves an `OPEN` complaint to `REJECTED` — a terminal state — under the same conditional role rule, with an optional `reason` (accepted but not persisted or returned).

A verified credit is not irrevocable. A `LinenManager` may rescind a `VERIFIED` complaint, moving it to `RESCINDED` — also a terminal state — and applying the exact compensation of verification: if the credit was routed to an invoice, that invoice's `credit_total_cents` decreases and its `billed_total_cents` increases by the credit amount; otherwise the facility's `credit_balance_cents` decreases by the credit amount. Separately, as noted in §3.5, a `VERIFIED` complaint moves automatically to `RESOLVED` — also terminal — when its manifest is reconciled.

Complaint history feeds unit standing. A unit's `quality_flag` is `WATCH` whenever the count of that unit's complaints in `VERIFIED` or `RESOLVED` status created within the trailing 30 days of the logical clock (the window boundary is inclusive: a complaint created exactly 30 days ago still counts) reaches three or more, and `CLEAR` otherwise; the flag is evaluated on unit reads and at complaint verification.

### 3.8. Surge Posture and Emergency Reserve Allocation

When a facility braces for a census surge, a `LinenManager` declares a **SurgeEvent** with `facility_id`, a `severity` label of `LEVEL_1` or `LEVEL_2` (a label only — the system attaches no behavioral difference to the severity), a `par_multiplier` applied to effective pars while the surge is active (for example 1.5; it must be a number greater than zero, else `ERR_INVALID_REQUEST`), and the closed-interval window `starts_at` to `ends_at`. The window end must be after its start (`ERR_INVALID_WINDOW`), and because surge windows are closed intervals, any overlap with another `DECLARED` or `ACTIVE` surge of the same facility — including merely sharing an endpoint — is rejected with `ERR_SURGE_WINDOW_CONFLICT`. A new surge event starts in `DECLARED` status. The surge-event list may be filtered by `facility_id` or `status`.

Activation is the consequential step: it requires the facility's `surge_posture` to be `NORMAL`, and an activation attempted while the facility is already in surge is rejected with `ERR_FACILITY_IN_SURGE`. Activation moves the event from `DECLARED` to `ACTIVE`, flips the facility's `surge_posture` from `NORMAL` to `SURGE`, and recomputes every par level of the facility: each `effective_par` becomes `base_par_quantity` multiplied by the surge's `par_multiplier`, rounded up to the next whole piece. The enlarged pars immediately drive an emergency reserve waterfall. Each stock of the facility that has `reserve_pieces` greater than zero is visited in order of stock creation, oldest first. For each stock, the candidate par levels are those of the stock whose units belong to the facility, ranked with `CRITICAL`-tier units before `STANDARD`-tier units, then by deficit ratio — the candidate's deficit divided by its `effective_par` — in descending order, with ties broken by unit creation time, oldest first. Each candidate in rank order, while reserve remains, receives the smaller of its deficit — `effective_par` minus `on_hand`, or zero when that difference is negative — and the remaining reserve; the stock's `reserve_pieces` decreases and the candidate's `on_hand` increases by the allocation. An empty candidate pool or a zero reserve never blocks activation: the surge still activates, simply with zero allocations.

Closing an `ACTIVE` surge moves it to `CLOSED` (terminal). The facility's `surge_posture` returns from `SURGE` to `NORMAL` when no other `ACTIVE` surge exists for the facility, and every par level's `effective_par` reverts to `base_par_quantity`. Reserve pieces allocated to units during the surge stay at the units — there is no clawback. While a facility is in surge, par-level updates remain blocked as described in §3.2.

### 3.9. Cost per Adjusted Patient Day Reporting

Management reporting reads cost per adjusted patient day on two bases, exposed through a computed facility metrics read restricted to `LinenManager`. The posted basis is cash-basis: the sum of `billed_total_cents` over the facility's `SETTLED` invoices divided by the sum of `period_adjusted_patient_days` over those same invoices, rounded half up to two decimal places, returned as `cost_per_apd_posted_cents`. The accrual basis includes open invoices: the sum of `billed_total_cents` over `FINALIZED`, `DISPUTED`, and `SETTLED` invoices plus the sum of `provisional_total_cents` over `PROVISIONAL` invoices, divided by the sum of `period_adjusted_patient_days` over all of the facility's invoices, rounded half up to two decimal places, returned as `cost_per_apd_accrual_cents`. Either figure is 0 when its invoice set is empty. The response also carries `posted_invoice_count`, the number of `SETTLED` invoices feeding the posted figure, and `accrual_invoice_count`, the number of invoices of all statuses feeding the accrual figure. The two bases diverge for identical data whenever open invoices exist, and the accrual figure is the one that moves as provisional bills are created.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; recording a stock adjustment also returns `201 Created`, carrying the updated stock in `data`. Operations that modify an existing resource — including all state transitions, recounts, returns, reconciliations, and the par-level update — return `200 OK`. All endpoints require the authentication headers described in §2.1, and all list endpoints follow the pagination contract of §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/facilities` | Create a facility with its vendor contract terms | LinenManager |
| GET | `/facilities/{facilityId}` | Get a facility | All roles |
| GET | `/facilities/{facilityId}/metrics` | Cost per adjusted patient day on posted and accrual bases | LinenManager |
| POST | `/units` | Create a nursing unit | LinenManager |
| GET | `/units/{unitId}` | Get a unit | All roles |
| GET | `/units` | List units | All roles |
| POST | `/linen-stocks` | Register a linen item with opening circulation and reserve | LinenManager |
| GET | `/linen-stocks/{stockId}` | Get a linen stock row | All roles |
| GET | `/linen-stocks` | List linen stock rows | All roles |
| POST | `/linen-stocks/{stockId}/adjustments` | Record a found/donation/write-off adjustment (OCC-guarded) | LinenManager |
| POST | `/par-levels` | Configure par level for a unit/item pair | LinenManager |
| GET | `/par-levels/{parLevelId}` | Get a par level | All roles |
| GET | `/par-levels` | List par levels | All roles |
| PUT | `/par-levels/{parLevelId}` | Update base par and/or cart cycle (OCC-guarded; blocked during surge) | LinenManager |
| POST | `/cart-runs` | Schedule an exchange cart run for a unit | EVSOperator |
| GET | `/cart-runs/{cartRunId}` | Get a cart run | All roles |
| GET | `/cart-runs` | List cart runs | All roles |
| POST | `/cart-runs/{cartRunId}/complete` | Record soiled counts and restock the unit to par | EVSOperator |
| POST | `/cart-runs/{cartRunId}/dispute` | Unit disputes recorded counts | UnitClerk |
| POST | `/cart-runs/{cartRunId}/recount` | Unit submits corrected soiled counts | UnitClerk |
| POST | `/cart-runs/{cartRunId}/reconcile` | Unit confirms final counts (terminal) | UnitClerk |
| POST | `/soiled-manifests` | Create a weighed vendor-bound soiled manifest from reconciled cart runs | EVSOperator |
| GET | `/soiled-manifests/{manifestId}` | Get a manifest | All roles |
| GET | `/soiled-manifests` | List manifests | All roles |
| POST | `/soiled-manifests/{manifestId}/return` | Vendor records returned clean pieces per item | LaundryVendor |
| POST | `/soiled-manifests/{manifestId}/reconcile` | Reconcile expected vs returned; compute shrinkage | LinenManager |
| POST | `/invoices` | Create a provisional weight-based invoice over manifests | LinenManager |
| GET | `/invoices/{invoiceId}` | Get an invoice | All roles |
| GET | `/invoices` | List invoices | All roles |
| POST | `/invoices/{invoiceId}/finalize` | Reconcile to piece-count billing (from PROVISIONAL or DISPUTED) | LinenManager |
| POST | `/invoices/{invoiceId}/dispute` | Vendor disputes a finalized invoice | LaundryVendor |
| POST | `/invoices/{invoiceId}/settle` | Record payment of a finalized invoice | LinenManager |
| POST | `/complaints` | Unit files a linen quality complaint | UnitClerk |
| GET | `/complaints/{complaintId}` | Get a complaint | All roles |
| GET | `/complaints` | List complaints | All roles |
| POST | `/complaints/{complaintId}/verify` | Verify a complaint and route its credit | LinenManager, InfectionControlOfficer |
| POST | `/complaints/{complaintId}/reject` | Reject a complaint (same conditional role rule as verify) | LinenManager, InfectionControlOfficer |
| POST | `/complaints/{complaintId}/rescind` | Rescind a verified complaint; exactly reverses its credit | LinenManager |
| POST | `/surge-events` | Declare a surge event with par multiplier and window | LinenManager |
| GET | `/surge-events/{surgeEventId}` | Get a surge event | All roles |
| GET | `/surge-events` | List surge events | All roles |
| POST | `/surge-events/{surgeEventId}/activate` | Activate a surge: posture flip, effective-par cascade, reserve waterfall | LinenManager |
| POST | `/surge-events/{surgeEventId}/close` | Close an active surge: posture and pars revert | LinenManager |
| POST | `/_clock/set_current_utc` | Set the logical clock | LinenManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_UNIT_OWNERSHIP` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_FACILITY_IN_SURGE` | 409 |
| `ERR_ISOLATION_PROTOCOL_REQUIRED` | 422 |
| `ERR_STORAGE_NOT_ATTESTED` | 422 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_RUN_WINDOW_CONFLICT` | 409 |
| `ERR_SURGE_WINDOW_CONFLICT` | 409 |
| `ERR_CART_RUN_ALREADY_LINKED` | 409 |
| `ERR_MANIFEST_ALREADY_INVOICED` | 409 |
| `ERR_PAR_LEVEL_CONFLICT` | 409 |
| `ERR_NO_ISOLATION_LINE` | 422 |
| `ERR_NO_PAR_LEVEL` | 409 |
| `ERR_COUNT_EXCEEDS_ON_HAND` | 409 |
| `ERR_NEGATIVE_INVENTORY` | 409 |
| `ERR_CONTRACT_CAP_EXCEEDED` | 422 |
| `ERR_MANIFEST_NOT_RECONCILED` | 409 |

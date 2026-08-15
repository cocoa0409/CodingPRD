# Potato Storage & Packing API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Potato Storage & Packing API, the system of record for an Idaho potato packing cooperative that takes delivery of harvested field lots, holds them in climate-managed storage sheds across a season, and packs them to customer specification. The API coordinates three concerns that interact tightly in practice: the physical weight ledger of every stored lot (what was received, what was lost to shrink, what was packed, what was culled or condemned), the food-safety posture of each storage shed (wash-water checks and periodic audits), and the commercial book of the season (grower-facing settlements, buyer-facing contracts, and the allocation of raw potato supply to packed demand).

Operators who use this API range from intake clerks logging trucks at harvest through quality assurance managers enforcing wash-water discipline to settlement clerks closing out a grower's season. The system is therefore built around a small set of role-scoped workflows whose business rules interlock across entity boundaries: a wash-water failure in one shed can abort a scheduled pack run, hold lots, release raw reservations, restore contract commitment, and force an open-market order back to the request queue — all as one cascade. Similarly, a grower's settlement is a derived number whose value depends on which pack orders have shipped, which lots have closed, and which assessments were in force when the clerk drafted the statement. Precision about these rules is the substance of this document.

## 2. Global Specifications & System-Wide Principles

This section pins down contract-level rules that apply across every endpoint and every entity in the system.

### 2.1. User and Role-Based Access Control

Every request to the API carries two mandatory HTTP headers: `X-User-ID` identifies the acting operator, and `X-User-Role` names the capacity in which they are acting. A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once a well-formed identity is established, the server checks the role's permission to perform the requested operation; a role attempting an operation outside its scope is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes eight roles, spelled exactly as follows: `ShedAdmin`, `IntakeClerk`, `StorageManager`, `QualityAssuranceManager`, `SalesManager`, `PackLineSupervisor`, `SettlementClerk`, and `Grower`.

For seven of those roles — `ShedAdmin`, `IntakeClerk`, `StorageManager`, `QualityAssuranceManager`, `SalesManager`, `PackLineSupervisor`, and `SettlementClerk` — the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity. The server may record it where a transition calls for it (for example, as `finalized_by_clerk_id` on a `GrowerSettlement` when a `SettlementClerk` finalizes), but it never compares the header against any entity's `id` field for those roles.

The `Grower` role is the single exception. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` resource; ownership checks on any resource that references a `Grower` compare the resource's foreign-key field to `X-User-ID`. A `Grower` calling for their own settlements or disputing one is therefore checked against the settlement's `grower_id`, and a request that names another grower's settlement is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

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

List endpoints paginate via two query parameters. `limit` controls the maximum number of items returned: it defaults to 10, must be at least 1, and is capped at 100. `offset` controls how many items are skipped from the front of the result and defaults to 0. Both are optional.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order.

The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource (`Grower`, `StorageShed`, `StorageBin`, `FieldLot`, `CustomerContract`, `PackOrder`, `PackRun`, `FoodSafetyAudit`, `GrowerSettlement`) carries a standard system-managed envelope:

- `id` is a server-minted UUID string with no type prefix.
- `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` is an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` is an integer that increments by one on every mutation; it is the field against which optimistic concurrency is checked.

Three subordinate resource types are immutable after creation and therefore omit both `updated_at` and `version`, carrying only `id` and `created_at`: `GradeOutAssessment`, `PackRunLotDraw`, and `WashWaterCheck`. Any rule that says a mutation "recomputes" a derived field on a parent entity counts as a mutation of that parent and therefore refreshes `updated_at` and bumps `version`.

### 2.5. Logical Clock and Time Semantics

The API is driven by a logical clock, not the wall clock. On startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`. The logical clock is advanced by an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the current time to that value. All timestamps written by the server (`binned_at`, `closed_at`, `completed_at`, `paid_at`, audit `closed_at`) are stamped from this logical clock, never from wall time.

Advancing the logical clock applies any due system transitions. In particular, the season-settle sweep runs on every clock advance: any `ACTIVE` contract whose `delivery_window_end` is now in the past is settled. When a contract's packed actuals have reached at least its committed volume the contract is marked `FULFILLED`; otherwise it is marked `SHORTFALLED`. Any commitment a contract still had reserved at that moment stays reserved until the orders holding it cancel or ship.

### 2.6. Weights, Units, and Precision

Potato weights throughout the system are expressed in hundredweight (`cwt`) carried to two decimal places. Dollar-denominated amounts are carried as integer cents or as cent-valued numbers with two decimal places, depending on context; wherever a rounding step is prescribed it is "round half up" — the half-cent rounds away from zero. The packing carton size on a pack order is expressed in pounds via `pack_unit_weight_lbs`.

Three precision rules are load-bearing. First, the expected-packout fraction used to size raw reservations is carried at four decimal places internally, then the resulting raw reservation is rounded half-up to two decimal places of hundredweight, subject to a guard that prevents a reservation from exceeding what the lot can physically supply. Second, the coverage quantity allocated per lot during the waterfall is floored to two decimal places before the per-lot raw draw is computed. Third, every per-lot financial line on a settlement (the storage fee, the inhibitor fee, and the processing credit) is rounded half-up to two decimal places first and only then summed; the summing-then-rounding order is forbidden, because at the storage rate in force the two orders diverge by at least one cent whenever an odd number of lots lands on a fractional-cent product.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, and they are the only two endpoints that take a version field. Every other endpoint — including all state-transition endpoints — does not take a version field.

Creating a grade-out assessment against a field lot requires the client to supply `expected_field_lot_version` carrying the lot's current `version` as last observed. If the lot's `version` has advanced since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason is that a newly recorded assessment supersedes the prior one as the lot's shrink and packout baseline, so a writer holding a stale lot version would silently re-baseline from outdated weight state.

Creating a grower settlement requires the client to supply `expected_grower_version` carrying the grower's current `version` as last observed. If the grower's `version` has advanced since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). The reason is that creating a settlement for a season legitimately supersedes the prior provisional settlement for that season, so a writer holding a stale grower version would supersede a settlement it never observed.

### 2.8. Nested Resource Retrieval

Requests targeting nested resources are validated left-to-right along the path. Existence of each path identifier is checked in order — grower, then shed, then bin, then lot, then contract, then order, then run, then audit, then settlement — and the request is rejected with the `404` error corresponding to the first missing identifier. For example, a wash-water check posted against a non-existent shed returns `ERR_SHED_NOT_FOUND` before any other rule is consulted, and a settlement read against a non-existent settlement identifier returns `ERR_SETTLEMENT_NOT_FOUND`.

### 2.9. Validation Order

When a single request would trip more than one rule, the server evaluates checks in a fixed priority order so that the surfaced error is deterministic. The order, from first to last, is:

1. **Authentication context** — presence and well-formedness of `X-User-ID` and `X-User-Role`; failures surface as `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Authorization and ownership** — role permission for the operation and any ownership rule (a `Grower` acting on another grower's settlement); failures surface as `ERR_INSUFFICIENT_PERMISSIONS`. The segregation-of-duties clerk check on settlement re-finalize is the one exception to this tier — it is evaluated with the state checks in tier 5.
3. **Existence** — path identifiers and body foreign-key references, validated left-to-right; failures surface as the appropriate `ERR_*_NOT_FOUND` (`ERR_GROWER_NOT_FOUND`, `ERR_SHED_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_FIELD_LOT_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_PACK_ORDER_NOT_FOUND`, `ERR_PACK_RUN_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_SETTLEMENT_NOT_FOUND`).
4. **Optimistic concurrency** — `expected_field_lot_version` against the lot's current `version` and `expected_grower_version` against the grower's current `version`; failures surface as `ERR_STALE_VERSION`.
5. **State gates** — the target resource must be in a state that admits the operation (the lot intake/binned/closed gates, order requested/allocated gates, run scheduled gate, contract active gate, settlement provisional/finalized/disputed gates, audit field-work gate, and the segregation-of-duties clerk identity check on re-finalize); failures surface as one of `ERR_LOT_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_RUN_INVALID_STATE`, `ERR_CONTRACT_INVALID_STATE`, `ERR_SETTLEMENT_INVALID_STATE`, `ERR_AUDIT_INVALID_STATE`, or `ERR_SOD_REFINALIZE_CLERK`.
6. **Food-safety gates** — shed quarantine and restriction gates, the lot hold gate on sprout-inhibitor application, and the wash-check freshness gate on pack-run creation; failures surface as `ERR_SHED_QUARANTINED`, `ERR_SHED_RESTRICTED`, `ERR_LOT_QUALITY_HOLD`, or `ERR_WASH_CHECK_STALE`.
7. **Cross-reference integrity** — bin variety-lock matching, contract-to-order variety matching, and settlement season-label uniqueness against non-superseded conflicts; failures surface as `ERR_BIN_VARIETY_MISMATCH`, `ERR_INVALID_REQUEST`, or `ERR_SETTLEMENT_SEASON_CONFLICT`.
8. **Temporal windows** — the sprout-inhibitor retreat window, the pack-line schedule overlap check, and the contract delivery-window ordering; failures surface as `ERR_RETREAT_WINDOW_VIOLATION`, `ERR_LINE_SCHEDULE_CONFLICT`, or `ERR_INVALID_REQUEST`.
9. **Shape and constraint checks** — bin capacity, assessment percentage summation, cumulative shrink monotonicity and ceiling, draw balance, draws within reservation, the run grade gate, the remnant-close ceiling, and general required-field and enum membership checks; failures surface as `ERR_BIN_CAPACITY_EXCEEDED`, `ERR_GRADE_PERCENT_SUM_INVALID`, `ERR_SHRINK_INVALID`, `ERR_RUN_DRAW_IMBALANCE`, `ERR_RUN_DRAW_EXCEEDS_RESERVATION`, `ERR_GRADE_SPEC_NOT_MET`, `ERR_LOT_REMNANT_TOO_LARGE`, or `ERR_INVALID_REQUEST`.
10. **Fiscal checks on allocation** — the contract commitment ceiling, the open-market cap, and the allocation pool sufficiency check; failures surface as `ERR_COMMITMENT_EXCEEDED`, `ERR_OPEN_MARKET_CAP_EXCEEDED`, or `ERR_INSUFFICIENT_ALLOCATION_POOL`.

A corollary of this ordering is that a food-safety failure surfaces ahead of a shape error, and a shape error surfaces ahead of a fiscal ceiling — so a request that violates both `ERR_SHED_QUARANTINED` and `ERR_COMMITMENT_EXCEEDED` always returns the former.

### 2.10. Hierarchical Consistency and Cascading Side Effects

Mutations on one entity routinely propagate to others. When a parent resource changes state in a way that makes children non-operational, the system cascades the change without further client action; conversely, when a child mutation changes the criteria for a parent's derived state, the parent's derived state is recomputed. The most consequential example is the shed food-safety posture cascade described in §3.7, but smaller examples are threaded through the workflows: an assessment re-baselines its lot's shrink; a run close updates the lot's weight ledger, the order's accumulated pack total, and the contract's commitment ledger in one transaction; a lot condemnation closes the lot and releases reservations held against it. Each cascade mutates every affected resource independently, refreshing its `updated_at` and incrementing its `version` where the entity carries one.

## 3. Business Logic & Workflows

### 3.1. Harvest Intake and Bin Assignment

The season begins with growers and sheds coming on the books. A `ShedAdmin` registers a `Grower` with a `name`, an accounting `grower_code` that must be unique across growers, and an optional `region` label. The same role provisions a `StorageShed` with a `name`, and then adds individual `StorageBin` resources to it, each with a `bin_code` that must be unique within its shed and a physical `capacity_cwt` expressed in hundredweight to two decimal places and strictly greater than zero.

Once a grower exists, an `IntakeClerk` can receive a `FieldLot` against that grower by providing the `variety` (one of `RUSSET_BURBANK`, `RUSSET_NORKOTAH`, `RANGER_RUSSET`, `YUKON_GOLD`, or `RED_LASODA`), the `harvest_date` as an ISO 8601 date, and the `original_weight_cwt` scaled at the truck. The new lot starts in `storage_status` `INTAKE` with `quality_status` `CLEAR`; it has no `bin_id` yet, and its shrink, packed, cull, condemned, and processing-credit accumulators all start at zero. Its `available_cwt` — the weight-conservation anchor — initially equals the original weight.

Assigning a lot to a bin is a separate step performed by an `IntakeClerk` once a target `bin_id` has been chosen. The operation is permitted only while the lot is in `INTAKE`; a lot already `BINNED` or `CLOSED` is rejected with `ERR_LOT_INVALID_STATE`. The target bin must exist (else `ERR_BIN_NOT_FOUND`) and must belong to a shed whose posture is currently `NORMAL` — a `RESTRICTED` shed rejects the assignment with `ERR_SHED_RESTRICTED` and a `QUARANTINED` shed rejects it with `ERR_SHED_QUARANTINED`. Two physical constraints then apply. First, the bin's `variety_lock` must either be unset or equal the lot's variety; a mismatch is `ERR_BIN_VARIETY_MISMATCH`. Second, the bin's `occupied_cwt` plus the lot's `available_cwt` must not exceed the bin's `capacity_cwt`; an exact fit is allowed, but any excess is rejected with `ERR_BIN_CAPACITY_EXCEEDED`.

A successful assignment sets the lot's `bin_id`, stamps `binned_at` with the current logical clock, transitions the lot to `BINNED`, and bumps the lot's `version`. The bin's `variety_lock`, if previously unset, takes on the lot's variety; the bin's `occupied_cwt` is then maintained as the sum of `available_cwt` over all `BINNED` lots in that bin, recomputed whenever the underlying lots change. When a bin's occupancy falls back to zero — because every lot in it has closed — its `variety_lock` is cleared back to unset so the bin can receive a different variety.

### 3.2. In-Storage Stewardship: Assessments, Sprout Inhibition, and Lot Close-Out

While a lot sits in storage, a `StorageManager` maintains its weight ledger and keeps sprouting in check.

Recording a `GradeOutAssessment` captures the lot's condition at a point in time: the `assessment_date`, the sample percentages `us1_pct`, `us2_pct`, and `cull_pct` (each between 0 and 100 with two decimal places, and the three must sum to exactly 100.00 — any deviation is `ERR_GRADE_PERCENT_SUM_INVALID`), and the `cumulative_shrink_cwt` measured since intake. Two rules govern that cumulative shrink number: it must be at least the previous assessment's cumulative value (shrink is monotonic non-decreasing), and it must not exceed the original weight less what has already been packed, culled, or condemned; violating either bound is `ERR_SHRINK_INVALID`. Because a new assessment supersedes the prior shrink baseline, the create is concurrency-guarded: the client must present `expected_field_lot_version` matching the lot's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. Assessments are immutable once recorded — they carry no `updated_at` or `version`.

A newly recorded assessment re-baselines the lot: the lot's `shrink_cwt` is set to the assessment's `cumulative_shrink_cwt` (it replaces, never accumulates), and the lot's `available_cwt` is recomputed as the original weight minus shrink, packed, cull, and condemned. If the re-baseline drives `available_cwt` to zero the lot auto-closes from `BINNED` to `CLOSED` with `closed_at` stamped. The assessment itself derives `packable_fraction` — the sum of `us1_pct` and `us2_pct` divided by 100, carried at four decimal places — which becomes the lot's expected packout basis for later allocation decisions. When a lot has more than one assessment, "the latest assessment" means the one with the greatest `assessment_date`, ties broken by `created_at`.

Sprout-inhibitor applications are recorded by a `StorageManager` supplying an `applied_at` timestamp. The operation is refused on a lot whose `quality_status` is `ON_HOLD` (`ERR_LOT_QUALITY_HOLD`). A retreat window applies: a new application must fall at least 21 days after the previous one — an application exactly 21 days after the prior `last_inhibitor_applied_at` is allowed, anything earlier is rejected with `ERR_RETREAT_WINDOW_VIOLATION`. Each accepted application increments `inhibitor_application_count`, refreshes `last_inhibitor_applied_at` to the supplied `applied_at`, and bumps the lot's `version`.

Closing out a lot is normally automatic — a lot whose `available_cwt` reaches zero transitions itself from `BINNED` to `CLOSED`. A `StorageManager` can also close a lot manually when only a small remnant remains: the manual close is permitted while `available_cwt` is at most 5.0 hundredweight (exactly 5.0 is allowed; anything larger is `ERR_LOT_REMNANT_TOO_LARGE`). Manual close books the remnant into shrink, setting the lot's `shrink_cwt` to the original weight less what has been packed, culled, and condemned, and stamps `closed_at`. Either path recomputes the bin's `occupied_cwt` and clears the bin's `variety_lock` if the bin is now empty.

### 3.3. Commercial Book: Contracts and Pack Orders

The sales side of the shed is owned by the `SalesManager`. A `CustomerContract` is created with a `buyer_name`, the contracted `variety`, the `committed_volume_cwt` in packed hundredweight equivalent (two decimal places, strictly greater than zero), the `price_cents_per_cwt` as an integer number of cents (strictly greater than zero), a `grade_min_us1_pct` floor on the US No. 1 share the buyer will accept across packed output, a `delivery_window_start` and `delivery_window_end` (the end must be strictly after the start, else `ERR_INVALID_REQUEST`), and a `priority_rank` label used for reporting only — it does not influence allocation order. A new contract starts in `ACTIVE` status.

A `PackOrder` expresses a concrete demand against a shed's pack line. The order's `order_type` is either `CONTRACT` or `OPEN_MARKET`. A `CONTRACT` order must carry a `contract_id` referencing an existing contract (else `ERR_CONTRACT_NOT_FOUND`) whose variety matches the order's `variety` (a mismatch is `ERR_INVALID_REQUEST`); an `OPEN_MARKET` order must instead carry a `market_price_cents_per_cwt` integer cents sale price. Supplying a `contract_id` on an `OPEN_MARKET` order, or omitting the market price on one, or omitting the contract reference on a `CONTRACT` order, is `ERR_INVALID_REQUEST`. Every order also names the `shed_id` whose pack line and storage pool will serve it, a `pack_unit_weight_lbs` carton weight in pounds (strictly greater than zero), a `grade_min_us1_pct` customer specification, a `requested_packed_cwt` in packed hundredweight (two decimals, strictly greater than zero), and an optional `allocation_policy` — `LOT_ASSESSMENT` by default, or `SHED_BLEND` — which selects the expected-packout variant used to size raw draws. New orders start in `REQUESTED` status with an empty `reservations` list and zero `packed_to_date_cwt`.

The contract maintains a small commitment ledger. `allocated_active_cwt` is the sum over the contract's orders in `ALLOCATED` or `PACKING` of each order's requested volume less what it has already packed; `packed_to_date_cwt` is the sum of packed actuals over all of the contract's orders; and `remaining_committed_cwt` is the committed volume less both of those quantities. These three fields are recomputed whenever an underlying order changes state or accumulates pack output.

### 3.4. Allocation: The Waterfall

Allocation converts an order's packed-cwt request into raw reservations on specific lots. A `SalesManager` triggers allocation against an order in `REQUESTED` for a full allocation, or against an order in `ALLOCATED` for a top-up after a partial fill or a partial reservation release; an order in any other state is rejected with `ERR_ORDER_INVALID_STATE`.

The eligible pool for an order is the set of lots that satisfy all of: the lot is in `storage_status` `BINNED`; its `quality_status` is `CLEAR`; its variety matches the order's `variety`; its bin sits in the order's shed; that shed's posture is not `QUARANTINED`; and the lot has allocatable weight — its `available_cwt` less its `reserved_cwt` — strictly greater than zero.

Within the pool, lots are ranked by `harvest_date` ascending with ties broken by `created_at` ascending (never by `id`). The waterfall walks the ranked list and assigns coverage from each lot in turn. The expected-packout fraction used depends on the order's `allocation_policy`. Under `LOT_ASSESSMENT`, each lot's fraction is its latest assessment's `packable_fraction`; a lot with no assessment uses the default blend fraction of 0.75. Under `SHED_BLEND`, a single realized fraction is computed across every lot in the shed — the total `packed_cwt` over all draws from `COMPLETED` runs in the shed divided by the total `raw_drawn_cwt` over the same draws (`ABORTED` runs are excluded) — and applied uniformly; if the shed has no completed run yet, the same 0.75 default applies.

For each lot in rank order, the coverage offered by that lot is the lot's allocatable weight multiplied by the applicable fraction, floored to two decimal places. The amount taken from the lot is the smaller of the remaining need and that coverage. The raw reservation written for the lot is the taken amount divided by the fraction, rounded half-up to two decimal places, but capped at the lot's allocatable weight — the cap guards against rounding the reservation past what the lot can physically supply. Each reservation records the `field_lot_id`, the reserved `raw_cwt`, and the `packed_equiv_cwt` covered, and the lot's `reserved_cwt` is increased by the raw amount.

The operation is atomic. Before any reservation is written, the server checks that the coverage summed across the entire eligible pool meets the need — where need is the requested volume less what has already been packed less the packed-equivalent already covered by existing reservations. If the pool's total coverage falls short, or the pool is empty, the request is rejected with `ERR_INSUFFICIENT_ALLOCATION_POOL` and no reservations are created.

Two fiscal ceilings apply on top of the pool check. For a `CONTRACT` order, the requested volume must not exceed the contract's `remaining_committed_cwt` (equality is allowed); exceeding it is `ERR_COMMITMENT_EXCEEDED`, and a contract that is no longer `ACTIVE` rejects the allocation with `ERR_CONTRACT_INVALID_STATE`. For an `OPEN_MARKET` order, the requested volume must not exceed the open-market cap for the order's variety and shed; exceeding it is `ERR_OPEN_MARKET_CAP_EXCEEDED`, with equality allowed. The cap is computed by taking, for every lot in the same eligible pool, the lot's allocatable weight multiplied by its lot-assessment fraction — the cap always uses the lot-assessment basis regardless of the order's `allocation_policy` — rounding each per-lot product half-up to two decimals, summing, and then subtracting the total `remaining_committed_cwt` over every `ACTIVE` contract of the same variety (`FULFILLED` and `SHORTFALLED` contracts are excluded from the subtraction). The cap is floored at zero.

A successful first allocation from `REQUESTED` transitions the order to `ALLOCATED` and bumps its `version`. For a `CONTRACT` order, the contract's commitment ledger is debited at the same time: `remaining_committed_cwt` is reduced by the requested volume and `allocated_active_cwt` is increased by the same amount. A subsequent top-up from `ALLOCATED` appends further reservations without touching the contract ledger — the commitment was already debited at the first allocation — and the order remains in `ALLOCATED`.

### 3.5. Pack-Line Operations: Scheduling, Closing, and Draw Accounting

Once an order is `ALLOCATED`, a `PackLineSupervisor` schedules a `PackRun` against it by supplying a `scheduled_start` and `scheduled_end`. The window must be ordered — an end at or before the start is `ERR_INVALID_REQUEST`. Three operational gates guard run creation. First, the order must currently be `ALLOCATED`; scheduling from any other state is `ERR_ORDER_INVALID_STATE`. Second, the shed's posture must not be `QUARANTINED` (`ERR_SHED_QUARANTINED`). Third, the shed must have a fresh `PASS` wash-water check: the most recent `PASS` check — selected by `measured_at` descending, ties broken by `created_at` descending — must lie within a freshness window of the current logical clock. The window is 12 hours when the shed is in `NORMAL` posture and 4 hours when it is `RESTRICTED`; a check exactly at the boundary counts as fresh. `FAIL` checks recorded after the most recent `PASS` do not extend or invalidate freshness — they act through posture instead — and a shed with no recorded `PASS` at all is treated as stale. A stale shed rejects the run with `ERR_WASH_CHECK_STALE`.

On top of those gates, the new window is checked against the line schedule. Two runs share a shed when their orders both name that shed. A new run conflicts with an existing `SCHEDULED` run on the same shed whenever the two windows overlap under a sanitation buffer: when the two orders are of different varieties the buffer is one hour, and when they are of the same variety the buffer is zero. Formally, a conflict exists when the new run's start falls before the other run's end plus the buffer and the other run's start falls before the new run's end plus the buffer; half-open adjacency — a new run starting exactly when the prior one ends plus buffer — is allowed. A conflict is rejected with `ERR_LINE_SCHEDULE_CONFLICT`.

A successfully created run starts in `SCHEDULED` and transitions the order from `ALLOCATED` to `PACKING`, bumping the order's `version`.

Closing a run is the moment the weight ledger moves. A `PackLineSupervisor` closes a run by supplying an `outcome` and, when completing, a non-empty `draws` list. Only a `SCHEDULED` run can be closed; anything else is `ERR_RUN_INVALID_STATE`.

When the outcome is `ABORTED`, no draws are recorded, the run transitions to `ABORTED`, and the order drops back from `PACKING` to `ALLOCATED` as a compensating action — reservations and lot weights are unchanged.

When the outcome is `COMPLETED`, every draw in the list is validated. Each draw names a `field_lot_id` and supplies `raw_drawn_cwt`, `packed_cwt`, `us1_cwt`, `us2_cwt`, `cull_cwt`, and a `cull_channel` of `PROCESSING` or `WASTE`. Each draw's lot must hold an active reservation on the order and the draw's `raw_drawn_cwt` must not exceed the reserved raw amount; a draw without a reservation, or one that exceeds it, is `ERR_RUN_DRAW_EXCEEDS_RESERVATION`. Within each draw the weights must balance: the raw drawn must equal the packed plus the cull, and the US No. 1 plus US No. 2 portions must equal the packed; any imbalance, any duplicated lot within a single run, or an empty draw list on a completing close is `ERR_RUN_DRAW_IMBALANCE`. Across the whole run, the aggregate US No. 1 share — the total `us1_cwt` divided by the total `packed_cwt`, expressed as a percentage — must meet or exceed the order's `grade_min_us1_pct`; falling short is `ERR_GRADE_SPEC_NOT_MET`.

A completing close then applies the draw ledger to every affected lot in one transaction. For each draw, the lot's `packed_total_cwt` increases by the draw's `packed_cwt`, its `cull_total_cwt` increases by the draw's `cull_cwt`, its `available_cwt` decreases by the `raw_drawn_cwt`, and its `reserved_cwt` decreases by the same raw amount; the reservation on that lot is consumed. When the draw's `cull_channel` is `PROCESSING`, the lot's `processing_credit_cwt` also increases by the `cull_cwt`. A lot driven to zero available weight auto-closes. The run's `packed_total_cwt` and `cull_total_cwt` are set from the draw sums, `completed_at` is stamped from the logical clock, and the run transitions to `COMPLETED`.

The order then resolves. Its `packed_to_date_cwt` increases by the run's total packed. If the accumulated total has reached the requested volume, the order transitions to `SHIPPED`; otherwise it cycles back to `ALLOCATED` — a partial fill from which it may later be topped up or run again. For a `CONTRACT` order, the contract's packed ledger moves in step: its `packed_to_date_cwt` increases by the run's packed total and its `allocated_active_cwt` decreases by the same amount.

### 3.6. Cancellation and De-allocation

An order can be cancelled by a `SalesManager` from either `REQUESTED` or `ALLOCATED`; cancelling from any other state is `ERR_ORDER_INVALID_STATE`. Cancelling from `REQUESTED` simply marks the order `CANCELLED` — there are no reservations to release. Cancelling from `ALLOCATED` releases every reservation the order holds — each referenced lot's `reserved_cwt` is decremented by the reservation's raw amount — and, for a `CONTRACT` order, restores the commitment ledger: the contract's `allocated_active_cwt` decreases by the requested volume less what has been packed to date, and its `remaining_committed_cwt` increases by the same amount. The order lands in `CANCELLED` with its `version` bumped.

A separate de-allocation path is triggered not by an operator but by the reservation-release cascade described in the next subsection. When a hold, condemnation, or quarantine releases enough reservations that the order's remaining packed-equivalent coverage falls below its outstanding need — the requested volume less what has already been packed — the order is reset. Every remaining reservation is released (each lot's `reserved_cwt` decremented accordingly), the contract ledger is restored as on a cancellation from `ALLOCATED` (decrementing `allocated_active_cwt` and incrementing `remaining_committed_cwt` by the outstanding need), and the order's status moves from `ALLOCATED` or `PACKING` back to `REQUESTED`. A partial release that still leaves the order covered leaves the order in place; only the released reservation's packed-equivalent is credited back to the contract's `allocated_active_cwt` and `remaining_committed_cwt` in that case.

### 3.7. Food Safety: Wash-Water Checks, Audits, and the Quarantine Cascade

Food safety is the province of the `QualityAssuranceManager`, who is deliberately segregated from the `PackLineSupervisor` (the same operator may not run the line) and from intake.

Wash-water discipline is enforced through `WashWaterCheck` records, each capturing `measured_at`, `turbidity_ntu`, `chlorine_ppm`, and `water_temp_f`. The check's `result` is derived: it is `PASS` when turbidity is at most 4.0 NTU, chlorine is between 50 and 200 ppm inclusive, and water temperature is between 45 and 60 degrees Fahrenheit inclusive; otherwise it is `FAIL`. A turbidity reading of exactly 4.0 passes; 4.01 fails.

Each recorded check updates two shed-level counters. A `FAIL` increments `consecutive_wash_failures`; if the failing check's turbidity exceeds 8.0 NTU it also sets `wash_quarantine_flag`. A `PASS` resets `consecutive_wash_failures` to zero and clears `wash_quarantine_flag`. Audits interact with a third flag: closing an audit with a `FAIL` outcome sets `audit_failed_flag`, and a later audit on the same shed closing `PASS` clears it.

After every check and every audit close, the shed's `posture` is recomputed. The shed is `QUARANTINED` whenever either quarantine flag is set; otherwise it is `RESTRICTED` when `consecutive_wash_failures` has reached at least two; otherwise it is `NORMAL`. Posture gates intake and packing as described elsewhere: a `RESTRICTED` or `QUARANTINED` shed rejects new bin assignments (`ERR_SHED_RESTRICTED` and `ERR_SHED_QUARANTINED` respectively), a `QUARANTINED` shed rejects pack-run creation, and the wash-freshness window for run creation tightens from 12 hours in `NORMAL` to 4 hours in `RESTRICTED`. While `QUARANTINED`, a hold release on any of the shed's lots is also refused with `ERR_SHED_QUARANTINED`.

Entering `QUARANTINED` fires a cascade. Every `SCHEDULED` pack run whose order names this shed auto-transitions to `ABORTED`, and each such run's order drops from `PACKING` back to `ALLOCATED` with its reservations retained. Every `CLEAR` lot in the shed's bins transitions to `ON_HOLD`. Then, for every order holding a reservation on any newly held lot, that lot's reservation is released (the lot's `reserved_cwt` decremented) and the order's coverage is rechecked: if the remaining reservations no longer cover the outstanding need, the full de-allocation reset of §3.6 applies; a `CONTRACT` order's commitment ledger is restored on the full reset, or credited by the released packed-equivalent on a partial release.

Leaving `QUARANTINED` requires both flags to be clear — `wash_quarantine_flag` cleared by a later `PASS` check and `audit_failed_flag` cleared by a later audit closing `PASS`, with both required when both were set — and `consecutive_wash_failures` below two. The posture then returns to `NORMAL`, but lots placed `ON_HOLD` by the quarantine stay on hold until a `QualityAssuranceManager` explicitly releases them.

Food-safety audits follow their own small lifecycle. A `QualityAssuranceManager` opens a `FoodSafetyAudit` against a shed by recording a `field_work_date`; the audit starts in `FIELD_WORK` with a null `outcome`. Closing an audit supplies an `outcome`, plus `critical_findings` and `minor_findings` counts; only a `FIELD_WORK` audit can be closed, else `ERR_AUDIT_INVALID_STATE`. A `PASS` close transitions the audit to `PASSED`, clears the shed's `audit_failed_flag`, stamps `closed_at`, and recomputes posture — which may lift the shed out of quarantine. A `FAIL` close transitions the audit to `FAILED`, sets `audit_failed_flag`, and recomputes posture into `QUARANTINED` with the full cascade described above. The re-audit loop is cross-instance: a failed audit keeps the flag set until a new audit on the same shed closes `PASS`.

### 3.8. Lot Quality Holds and Condemnation

Independent of the storage lifecycle, each lot carries a parallel quality dimension. A `QualityAssuranceManager` moves a lot from `CLEAR` to `ON_HOLD` by submitting a quality transition whose `to_status` is `ON_HOLD`. The lot must currently be `BINNED` (an `INTAKE` or `CLOSED` lot is `ERR_LOT_INVALID_STATE`) and currently `CLEAR`. The transition bumps the lot's `version` and fires the reservation-release cascade: for every order holding a reservation on the lot, that reservation is released and the order's coverage rechecked, with the full de-allocation reset of §3.6 applying if coverage falls short.

Releasing a hold is a transition whose `to_status` is `CLEAR`. It requires the lot to be `ON_HOLD` and its shed's posture not to be `QUARANTINED` (`ERR_SHED_QUARANTINED`); success returns the lot to `CLEAR`.

Condemnation is a transition whose `to_status` is `CONDEMNED` and which carries a `diversion_channel` of `PROCESSING_CREDIT` or `WASTE`. Condemnation is reachable only from `ON_HOLD` — a direct transition from `CLEAR` is `ERR_LOT_INVALID_STATE` — and a missing or out-of-set diversion channel is `ERR_INVALID_REQUEST`. The lot's entire `available_cwt` is booked into `condemned_cwt`; when the diversion channel is `PROCESSING_CREDIT`, the same weight is also added to `processing_credit_cwt`. With availability at zero the lot auto-closes to `CLOSED` with `closed_at` stamped, the reservation-release cascade runs (it is idempotent when no reservations remain), and the bin's occupancy is recomputed, clearing the variety lock if the bin is now empty.

### 3.9. Grower Settlement

At the end of a season, the cooperative settles with each grower. A `SettlementClerk` opens a `GrowerSettlement` against a grower by supplying a `season_label`. Because a create supersedes any prior provisional settlement for the same season, the operation is concurrency-guarded on the grower: the request must carry `expected_grower_version` matching the grower's current `version`, and a stale value is rejected with `ERR_STALE_VERSION`. The `season_label` must be unique per grower among settlements that are not `SUPERSEDED` — a `FINALIZED`, `DISPUTED`, or `PAID` settlement already on the books for the same season rejects the create with `ERR_SETTLEMENT_SEASON_CONFLICT`. When a settlement for the same season does exist in `PROVISIONAL`, creating the new one flips the old one to `SUPERSEDED` and the new settlement starts in `PROVISIONAL`. The create bumps the grower's `version`.

A settlement computes six money fields on top of a packed basis, recorded on the settlement as `packed_cwt_basis`. The basis depends on which variant is being computed. The provisional variant — computed at create — sums, over every lot the grower has in any storage state, a per-lot term: for a lot not yet closed, the term is its actual `packed_total_cwt` plus the estimated packout of the remainder (the lot's `available_cwt` multiplied by its latest-assessment packout fraction, defaulting to 0.75 when the lot has no assessment); for a `CLOSED` lot, the term is just the actual `packed_total_cwt`. Each per-lot term is rounded half-up to two decimals before summing. The final variant — computed at finalize — requires every lot to be `CLOSED` and uses only actual packed totals.

The pool price, recorded on the settlement as `pool_price_cents`, is the volume-weighted realized price per packed hundredweight across the whole operation. It is computed in two steps to resolve an apparent circularity. First, the pool aggregate is built from shipped orders only: the sum, over every `SHIPPED` contract order, of its `packed_to_date_cwt` multiplied by its contract's `price_cents_per_cwt`, plus the corresponding sum over `SHIPPED` open-market orders using each order's `market_price_cents_per_cwt`, divided by the total `packed_to_date_cwt` across all shipped orders, rounded half-up to two decimals. Only then is the grower's basis multiplied by that price. A grower's own shipped orders do contribute to the pool that prices that grower's settlement, and provisional settlements never feed the pool. When no shipped order exists at all, the fallback is the contract blend: the sum over every `ACTIVE` contract of its `committed_volume_cwt` times `price_cents_per_cwt` divided by the total committed volume across those contracts, again rounded half-up to two decimals. When there are also no active contracts, the pool price is zero.

The settlement's `gross_cents` is the packed basis multiplied by the pool price, rounded half-up to two decimals. Three adjustments follow. `storage_fees_cents` is the sum over the grower's lots of a per-lot storage fee: the fee per lot is 12.5 cents times the lot's `original_weight_cwt` times the number of completed whole weeks in storage, rounded half-up to two decimals per lot before summing. For the provisional variant the week count is the whole weeks between the lot's `binned_at` and the settlement clock time (zero if the lot has not been binned yet); for the final variant it is the whole weeks between `binned_at` and `closed_at`. Exactly fourteen days in storage counts as exactly two weeks. The per-lot-then-sum rounding order is pinned — summing first and rounding once is forbidden, because at this rate the two orders diverge by at least a cent whenever an odd number of lots lands on a fractional-cent product. `inhibitor_fees_cents` is the sum over the grower's lots of 8 cents times the lot's `original_weight_cwt` times its `inhibitor_application_count`, again rounded per lot before summing. `processing_credits_cents` is the sum over the grower's lots of 150 cents times the lot's `processing_credit_cwt`, also rounded per lot before summing. The `net_payable_cents` is the gross less storage fees less inhibitor fees plus processing credits; no floor is applied, so a negative net means the grower owes the shed.

Finalization moves the settlement from `PROVISIONAL` to `FINALIZED`. It is refused when the settlement is in any other state (`ERR_SETTLEMENT_INVALID_STATE`) and refused while any of the grower's lots is not yet `CLOSED` (`ERR_SETTLEMENT_LOTS_NOT_CLOSED`). On success the final variant is computed, the acting clerk's `X-User-ID` is recorded as `finalized_by_clerk_id`, and the settlement's `version` bumps.

The grower may dispute a `FINALIZED` settlement — and only their own: the grower ownership rule requires the acting `X-User-ID` to equal the settlement's `grower_id`, and a mismatch is `ERR_INSUFFICIENT_PERMISSIONS`. A dispute against a settlement in any other state is `ERR_SETTLEMENT_INVALID_STATE`. The dispute call accepts an optional `reason`. A successful dispute moves the settlement to `DISPUTED`.

Re-finalizing a `DISPUTED` settlement repeats the final computation, but segregation of duties applies: the clerk performing the re-finalize must not be the clerk recorded in `finalized_by_clerk_id`; the same clerk id is rejected with `ERR_SOD_REFINALIZE_CLERK` (HTTP 403). The lot-closure precondition still applies on re-finalize, so any lot that has somehow reopened blocks the operation with `ERR_SETTLEMENT_LOTS_NOT_CLOSED`. A successful re-finalize overwrites `finalized_by_clerk_id` with the new clerk's id.

Payment closes the loop: a `SettlementClerk` pays a `FINALIZED` settlement, which transitions it to `PAID` and stamps `paid_at` from the logical clock. Payment from any other state is `ERR_SETTLEMENT_INVALID_STATE`.

### 3.10. Reading the Operation

Most resources are directly readable. A grower record — including its `version`, which the settlement create flow needs for optimistic concurrency — is readable by administrative and operational roles as well as by the grower themselves. A shed record exposes its derived `posture` and the wash-failure counters. A field lot record exposes its derived weight-ledger fields — `shrink_cwt`, `packed_total_cwt`, `cull_total_cwt`, `condemned_cwt`, `processing_credit_cwt`, `available_cwt`, and `reserved_cwt` — alongside its two status dimensions.

List endpoints give visibility across the hierarchy. Bins are listed under their shed (reverse-reaching `StorageBin.shed_id`) for occupancy visibility. Field lots are listed across the operation with optional filters on `grower_id`, `bin_id`, `variety`, and `storage_status`. Assessments are listed under their lot. Run draws are listed two ways — under the run (reverse-reaching each draw's `pack_run_id`) or under the lot (reverse-reaching each draw's `field_lot_id`). Pack orders are listed with optional filters on `contract_id`, `shed_id`, and `status`. Runs are listed under their order (reverse-reaching each run's `pack_order_id`). Wash-water checks and audits are listed under their shed. Settlements are listed under their grower. Every list follows the pagination contract of §2.3 and returns in `created_at` ascending order.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including state transitions and sub-resource closes — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/potato-shed/growers` | Register a grower | ShedAdmin |
| GET | `/potato-shed/growers/{id}` | Read a grower (version for settlement OCC) | ShedAdmin, IntakeClerk, StorageManager, SettlementClerk, Grower |
| POST | `/potato-shed/sheds` | Create a storage shed (posture starts NORMAL) | ShedAdmin |
| GET | `/potato-shed/sheds/{id}` | Read a shed incl. derived posture and wash-fail counters | ShedAdmin, IntakeClerk, StorageManager, QualityAssuranceManager, SalesManager, PackLineSupervisor, SettlementClerk |
| POST | `/potato-shed/sheds/{id}/bins` | Create a bin in a shed | ShedAdmin |
| GET | `/potato-shed/sheds/{id}/bins` | List bins of a shed | ShedAdmin, IntakeClerk, StorageManager, QualityAssuranceManager, SalesManager |
| POST | `/potato-shed/growers/{id}/field-lots` | Field lot intake (INTAKE state, unbinned) | IntakeClerk |
| GET | `/potato-shed/field-lots/{id}` | Read a field lot incl. derived weight ledger fields | ShedAdmin, IntakeClerk, StorageManager, QualityAssuranceManager, SalesManager, PackLineSupervisor, SettlementClerk, Grower |
| GET | `/potato-shed/field-lots` | List field lots with optional filters | ShedAdmin, IntakeClerk, StorageManager, QualityAssuranceManager, SalesManager, SettlementClerk, Grower |
| POST | `/potato-shed/field-lots/{id}/bin-assignment` | Assign an INTAKE lot to a bin | IntakeClerk |
| POST | `/potato-shed/field-lots/{id}/assessments` | Record a grade-out assessment (OCC on lot version) | StorageManager |
| GET | `/potato-shed/field-lots/{id}/assessments` | List assessments of a lot | ShedAdmin, StorageManager, QualityAssuranceManager, SettlementClerk |
| POST | `/potato-shed/field-lots/{id}/sprout-inhibitor-applications` | Record a sprout-inhibitor application (21-day retreat window) | StorageManager |
| POST | `/potato-shed/field-lots/{id}/quality-transition` | Quality hold / release / condemn | QualityAssuranceManager |
| POST | `/potato-shed/field-lots/{id}/close` | Close a BINNED lot whose remnant is at most 5.0 cwt | StorageManager |
| GET | `/potato-shed/field-lots/{id}/lot-draws` | List run draws against this lot | ShedAdmin, StorageManager, SalesManager, PackLineSupervisor, SettlementClerk |
| POST | `/potato-shed/contracts` | Create a customer contract | SalesManager |
| GET | `/potato-shed/contracts/{id}` | Read a contract incl. commitment ledger | ShedAdmin, SalesManager, SettlementClerk |
| POST | `/potato-shed/pack-orders` | Create a pack order (CONTRACT or OPEN_MARKET) | SalesManager |
| GET | `/potato-shed/pack-orders/{id}` | Read a pack order incl. reservations | ShedAdmin, SalesManager, PackLineSupervisor, SettlementClerk |
| GET | `/potato-shed/pack-orders` | List pack orders with optional filters | ShedAdmin, SalesManager, PackLineSupervisor, SettlementClerk |
| POST | `/potato-shed/pack-orders/{id}/allocate` | Run the allocation waterfall (full from REQUESTED, top-up from ALLOCATED) | SalesManager |
| POST | `/potato-shed/pack-orders/{id}/cancel` | Cancel a REQUESTED or ALLOCATED order | SalesManager |
| POST | `/potato-shed/pack-orders/{id}/pack-runs` | Schedule a pack run | PackLineSupervisor |
| GET | `/potato-shed/pack-orders/{id}/pack-runs` | List runs of an order | ShedAdmin, SalesManager, PackLineSupervisor |
| POST | `/potato-shed/pack-runs/{id}/close` | Close a run: COMPLETED with draws, or ABORTED | PackLineSupervisor |
| GET | `/potato-shed/pack-runs/{id}` | Read a pack run | ShedAdmin, SalesManager, PackLineSupervisor |
| GET | `/potato-shed/pack-runs/{id}/lot-draws` | List draws of a run | ShedAdmin, SalesManager, PackLineSupervisor, SettlementClerk |
| POST | `/potato-shed/sheds/{id}/wash-water-checks` | Record a wash-water check; recompute posture | QualityAssuranceManager |
| GET | `/potato-shed/sheds/{id}/wash-water-checks` | List wash-water checks of a shed | ShedAdmin, QualityAssuranceManager, PackLineSupervisor |
| POST | `/potato-shed/sheds/{id}/audits` | Open a food-safety audit | QualityAssuranceManager |
| POST | `/potato-shed/audits/{id}/close` | Close an audit PASS/FAIL | QualityAssuranceManager |
| GET | `/potato-shed/sheds/{id}/audits` | List audits of a shed | ShedAdmin, QualityAssuranceManager |
| POST | `/potato-shed/growers/{id}/settlements` | Create a PROVISIONAL settlement for a season (OCC on grower version) | SettlementClerk |
| GET | `/potato-shed/settlements/{id}` | Read a settlement | ShedAdmin, SettlementClerk, Grower |
| GET | `/potato-shed/growers/{id}/settlements` | List settlements of a grower | ShedAdmin, SettlementClerk, Grower |
| POST | `/potato-shed/settlements/{id}/finalize` | Finalize PROVISIONAL or re-finalize DISPUTED | SettlementClerk |
| POST | `/potato-shed/settlements/{id}/dispute` | Grower disputes a FINALIZED settlement | Grower |
| POST | `/potato-shed/settlements/{id}/pay` | Pay a FINALIZED settlement | SettlementClerk |
| POST | `/potato-shed/_clock/set_current_utc` | Advance the logical clock and run the contract settle sweep | ShedAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 |
| `ERR_GROWER_NOT_FOUND` | 404 |
| `ERR_SHED_NOT_FOUND` | 404 |
| `ERR_BIN_NOT_FOUND` | 404 |
| `ERR_FIELD_LOT_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_PACK_ORDER_NOT_FOUND` | 404 |
| `ERR_PACK_RUN_NOT_FOUND` | 404 |
| `ERR_AUDIT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_CONTRACT_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 |
| `ERR_AUDIT_INVALID_STATE` | 409 |
| `ERR_SHED_QUARANTINED` | 409 |
| `ERR_SHED_RESTRICTED` | 409 |
| `ERR_LOT_QUALITY_HOLD` | 409 |
| `ERR_WASH_CHECK_STALE` | 409 |
| `ERR_RETREAT_WINDOW_VIOLATION` | 409 |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 |
| `ERR_BIN_VARIETY_MISMATCH` | 409 |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 |
| `ERR_GRADE_PERCENT_SUM_INVALID` | 422 |
| `ERR_SHRINK_INVALID` | 422 |
| `ERR_RUN_DRAW_IMBALANCE` | 422 |
| `ERR_RUN_DRAW_EXCEEDS_RESERVATION` | 422 |
| `ERR_GRADE_SPEC_NOT_MET` | 422 |
| `ERR_LOT_REMNANT_TOO_LARGE` | 409 |
| `ERR_COMMITMENT_EXCEEDED` | 402 |
| `ERR_OPEN_MARKET_CAP_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_ALLOCATION_POOL` | 422 |
| `ERR_SETTLEMENT_LOTS_NOT_CLOSED` | 409 |
| `ERR_SOD_REFINALIZE_CLERK` | 403 |
| `ERR_SETTLEMENT_SEASON_CONFLICT` | 409 |

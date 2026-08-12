# Mushroom Farm API — Product Requirements Document

## 1. Introduction

A specialty mushroom farm in Kennett Square operates a tightly coupled production chain: compost and straw-sawdust substrate is mixed in tonnage batches, pasteurized in steam tunnels, inoculated with spawn, and then booked into growing rooms where each crop moves through colonization, casing, and fruiting phases before the room is turned over for the next cycle. Alongside the physical pipeline, the farm runs a commercial book — buyers commit to weekly deliveries of specific varieties and grades, packaged lots are allocated first-expiry-first-out against those commitments, and shortfalls are settled with tiered penalties. Harvest labor is paid piece-rate with grade-weighted bonuses under strict segregation of duties, and any contamination event can cascade a room into quarantine, aborting its crop and putting committed supply at risk.

This document specifies the API that orchestrates that operation end to end. It covers substrate batch and pasteurization cycle management, spawn run and fruiting room scheduling, flush-cycle yield tracking, contamination response, harvest payroll, packaging and shelf-life enforcement, spent substrate disposal and resale, and the buyer commitment book. All time-gated rules — scheduling windows, colonization minimums, shelf-life expiry, and weekly settlement — evaluate against a single logical clock that the farm manager controls, so the entire facility advances deterministically from one ops-run checkpoint to the next.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting user, and `X-User-Role` naming their role. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the attempted operation is rejected with `ERR_FORBIDDEN` (HTTP 403).

The recognized roles, spelled exactly as shown, are: `FarmManager`, `CompostSupervisor`, `GradingInspector`, `HarvestCrewLead`, `PayrollClerk`, `SalesManager`, `QualityInspector`, `BuyerPortal`, and `Any`. `Any` is a marker role for read-only access: every authenticated role may use all GET endpoints.

- A `FarmManager` runs the growing side: rooms, room cycles, flush recording, packaging, worker administration, the logical clock, the daily sweep, and spent-substrate disposal. Their `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- A `CompostSupervisor` runs substrate production: varieties, batches, tunnels, pasteurization cycles, spawning, and batch retirement. Their `X-User-ID` is opaque.
- A `GradingInspector` grades and reopens flush harvests and is deliberately segregated from piece logging and piece approval. Their `X-User-ID` is opaque.
- A `HarvestCrewLead` logs piece-rate picking entries. When `X-User-Role` is `HarvestCrewLead`, `X-User-ID` is the `id` of the acting `Worker`; ownership checks compare against that entity. If no `Worker` with that id exists, the request is rejected with `ERR_IDENTITY_NOT_RESOLVED` (HTTP 403).
- A `PayrollClerk` approves and disputes pieces and runs payouts; they may never approve or dispute a piece whose `logged_by_user_id` equals their own `X-User-ID`, a violation rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Their `X-User-ID` is opaque.
- A `SalesManager` runs the commercial side: buyers, commitments, commitment lines, allocation, shipping, and spent-substrate resale. Their `X-User-ID` is opaque.
- A `QualityInspector` owns contamination reporting, confirmation, remediation, and clearance. Their `X-User-ID` is opaque.
- A `BuyerPortal` caller is buyer self-service. When `X-User-Role` is `BuyerPortal`, `X-User-ID` is the `id` of the acting `Buyer`; if no such buyer exists the request is rejected with `ERR_IDENTITY_NOT_RESOLVED`. A `BuyerPortal` caller may create commitments only for itself: the `buyer_id` of the new commitment must equal its `X-User-ID`, otherwise the request is rejected with `ERR_BUYER_MISMATCH` (HTTP 403).

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` defaults to 0. List responses are sorted by `created_at` ascending, and the `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource in this API carries a common set of system-managed properties. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` is refreshed on every mutation. The `version` field is an integer that increments by 1 on every mutation of the resource, and it anchors the optimistic concurrency rules in §2.6.

Consistency is immediate: whenever an operation cascades into derived fields or related entities — a graded flush bubbling up to its cycle, a payout settling a flush, a quarantine aborting a crop — all of those effects are reconciled inside the same request, and the response reflects the fully reconciled state.

### 2.5. The Logical Clock

The server never consults the wall clock. On startup the logical clock is exactly `2026-05-01T00:00:00Z`, and every time-gated rule in this document — window checks, colonization minimums, shelf-life expiry, settlement timing — evaluates against it. A `FarmManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; the new value must be greater than or equal to the current logical time, and a target before it is rejected with `ERR_CLOCK_REGRESSION` (HTTP 409). The response reports the resulting time as `current_utc`.

### 2.6. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency on a parent entity's `version`, and these are the only endpoints that accept a version field.

Booking a new room cycle against a growing room requires the request to carry `expected_room_version`, the client’s last observed `version` of that `GrowingRoom`. If another writer has advanced the room’s version since the client last read it — for example by booking a cycle in the same room, which legitimately bumps the room’s version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from booking against a room schedule it has not observed.

Activating a buyer commitment requires the request to carry `expected_commitment_version`, the client’s last observed `version` of that `BuyerCommitment`. If the commitment’s version has advanced since the client last read it, the activation is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named in this section do not take a version field.

### 2.7. Numeric Precision and Rounding

Kilogram quantities are held at 2 decimal places, rounded half-up wherever a computation produces them. Money is held in whole cents, rounded half-up at the moment each monetary value is computed. Pasteurization temperature-hour thresholds compare at 1 decimal place. Instant comparisons for shelf life and windows operate at second precision.

Payroll rounding is pinned per piece: each piece’s pay is rounded to whole cents at the moment it is computed — at logging for the provisional figure and at approval for the final figure — and worker accruals and payouts sum those already-rounded per-piece cent values. The system never rounds after summation.

### 2.8. Validation Order and Request Rejection

Incoming requests are validated in a fixed priority order, so the first failing check determines the rejection. Authentication comes first: the presence of `X-User-ID` and `X-User-Role` is checked before anything else (priority 1), then identity resolution for entity-backed roles (priority 2), then role permission and buyer-ownership rules (priority 3). Existence follows: path resource ids must exist and are validated left to right along the URL (priority 4), then foreign-key references in the request body — `batch_id`, `tunnel_id`, `room_id`, `variety_id`, `worker_id`, `buyer_id` — must exist (priority 5). A missing resource surfaces from the family `ERR_VARIETY_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_TUNNEL_NOT_FOUND`, `ERR_CYCLE_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_ROOM_CYCLE_NOT_FOUND`, `ERR_FLUSH_NOT_FOUND`, `ERR_PIECE_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, or `ERR_SPENT_LOT_NOT_FOUND` (all HTTP 404).

Optimistic-concurrency stale-version rejection (priority 6, `ERR_STALE_VERSION`, HTTP 412) is checked before state preconditions, so a stale writer gets a deterministic 412 regardless of the target’s subsequent state. State preconditions come next (priority 7), then safety gating such as quarantine blocks (priority 8), then temporal rules such as window overlap and clock checks (priority 9), then business constraints such as capacity, sufficiency, and segregation-of-duties checks (priority 10), and finally fiscal rules such as the spent-lot price floor (priority 11).

Malformed requests — a missing required field, a type mismatch, an enum value outside its declared constraints, a non-positive quantity, a `week_end` that is not strictly after its `week_start`, a `planned_end` that is not strictly after its `planned_start`, a no-op status change, or a `flush_yield_distribution` whose length does not equal `max_flushes` — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

## 3. Business Logic & Workflows

### 3.1. Varieties and the Substrate Production Pipeline

Everything starts with the variety catalog. A `CompostSupervisor` registers a mushroom variety with a unique `variety_code`, a `display_name`, the `substrate_recipe` it requires (one of `PHASE_II_COMPOST` or `STRAW_SAWDUST`), the `target_bioefficiency_pct` expressing expected fresh kilograms harvested per 100 kilograms of spawned substrate, `shelf_life_days` in whole days, `spawn_run_days` and `casing_days` as minimum whole-day phase durations, `max_flushes` of at least 1, and a `flush_yield_distribution`: an array of fractions whose length must equal `max_flushes` and which must sum to 1.0, describing what share of total expected yield each flush index should produce. A distribution whose length disagrees with `max_flushes` is rejected with `ERR_INVALID_REQUEST`. A new variety starts with `active_committed_kg` and `planned_production_kg` both at 0.0; these are computed demand and supply signals maintained by the system.

Substrate is produced in batches. A `CompostSupervisor` creates a batch by naming its `recipe` (again `PHASE_II_COMPOST` or `STRAW_SAWDUST`) and its `tonnage`, which must be greater than zero. A batch is born in `MIXED` status with its `remaining_tonnage` initialized to its full `tonnage`, and with `variety_id` and `spawn_kg` both null until spawning. Batches may be listed with optional filters on `variety_id` and `status`.

Pasteurization tunnels are registered with a unique `tunnel_code` and a `capacity_tonnes` greater than zero, and enter service `AVAILABLE`. Scheduling a pasteurization cycle binds a `batch_id`, a `tunnel_id`, and a planned window `planned_start` to `planned_end` (the end must be strictly after the start, otherwise `ERR_INVALID_REQUEST`). The batch must be `MIXED` — otherwise `ERR_BATCH_NOT_MIXED` — and the batch’s `tonnage` must not exceed the tunnel’s `capacity_tonnes`, a violation rejected with `ERR_TUNNEL_CAPACITY_EXCEEDED`. Tunnel bookings follow half-open interval semantics: two cycles collide only when their `[planned_start, planned_end)` intervals intersect, so a new cycle starting exactly when an existing one ends is allowed, and only cycles still in `SCHEDULED` or `RUNNING` block a booking. A genuine collision is rejected with `ERR_TUNNEL_WINDOW_OVERLAP`. Creating the cycle flips the batch from `MIXED` to `PASTEURIZING` and increments the batch’s `version` by 1. Cycles may be listed filtered by `batch_id`, `tunnel_id`, or `status`.

When the planned window opens, the supervisor starts the cycle. Starting requires the cycle to be `SCHEDULED` (otherwise `ERR_CYCLE_INVALID_STATE`), the tunnel to be `AVAILABLE` (otherwise `ERR_TUNNEL_NOT_AVAILABLE`), and the logical clock to fall within `[planned_start, planned_end]` inclusive (otherwise `ERR_CYCLE_WINDOW_NOT_OPEN`). A successful start moves the cycle to `RUNNING` and stamps `actual_start` with the current clock time.

Completion is a threshold judgment. The supervisor reports `hours_at_target_temp`, and the cycle may complete only when that figure is at least 6.0 hours — the boundary is inclusive, so exactly 6.0 completes. Below 6.0 hours the completion is rejected with `ERR_PASTEURIZATION_INCOMPLETE` and the cycle stays `RUNNING`. A successful completion moves the cycle to `COMPLETED` and advances the batch from `PASTEURIZING` to `CONDITIONED`, bumping the batch’s `version`. A cycle that suffers contamination or a temperature excursion is instead failed: failing requires `RUNNING` (otherwise `ERR_CYCLE_INVALID_STATE`), moves the cycle to `FAILED`, drops the batch back from `PASTEURIZING` to `MIXED` so it can be rebooked, and — because the tunnel itself is now suspect — forces the tunnel from `AVAILABLE` to `OUT_OF_SERVICE`. A still-`SCHEDULED` cycle may instead be aborted, moving it to `ABORTED` and likewise returning the batch from `PASTEURIZING` to `MIXED`, though an abort does not take the tunnel out of service. Only an `OUT_OF_SERVICE` tunnel can be sanitized; sanitizing returns it to `AVAILABLE`, and attempting it on an available tunnel is rejected with `ERR_TUNNEL_NOT_AVAILABLE`.

A `CONDITIONED` batch is spawned with a variety. Spawning requires the batch to be `CONDITIONED` (otherwise `ERR_BATCH_NOT_CONDITIONED`) and requires the variety’s `substrate_recipe` to equal the batch’s `recipe`, a mismatch rejected with `ERR_RECIPE_MISMATCH`. The operation records the chosen `variety_id` and the `spawn_kg` mixed in, moves the batch to `SPAWNED`, and bumps its `version`.

The batch’s `remaining_tonnage` is a ledger: it equals the batch’s `tonnage` minus the sum of `allocated_tonnage` over every room cycle of the batch whose status is anything other than `CANCELLED`. Booking a cycle debits the reservation; cancelling a `SCHEDULED` cycle credits the reservation back; aborting a placed cycle does not release tonnage because the substrate is physically consumed and a spent-substrate lot is produced instead. If a reservation draws `remaining_tonnage` down to exactly zero while the batch is `SPAWNED`, the batch automatically transitions `SPAWNED → EXHAUSTED`, bumping its `version`. Finally, an `EXHAUSTED` batch may be retired — retirement requires the batch to be `EXHAUSTED` (otherwise `ERR_BATCH_NOT_EXHAUSTED`) and requires every room cycle of the batch to be in `CLOSED`, `CANCELLED`, or `ABORTED` and every spent substrate lot of the batch to be `SOLD` or `DISPOSED`, otherwise `ERR_UNRESOLVED_SPENT_LOTS`. Retirement moves the batch to its terminal `RETIRED` status and bumps `version`. The batch also carries two computed money ledgers: `spent_revenue_cents`, the sum of `sale_price_cents` over its `SOLD` spent lots, and `disposal_cost_cents`, the sum of `disposal_cost_cents` over its `DISPOSED` spent lots, both starting at 0.

### 3.2. Room Booking and the Crop Cycle

A `FarmManager` registers growing rooms with a unique `room_code` and a `capacity_tonnes` greater than zero. A room carries two independent status dimensions that evolve in parallel: `occupancy_status`, which cycles `IDLE → OCCUPIED → TURNAROUND → IDLE` entirely through system-driven hops, and `health_status`, which moves among `CLEAR`, `WATCH`, and `QUARANTINED` based on contamination events (§3.7). A new room is `IDLE` and `CLEAR`.

Booking a room cycle is an OCC-guarded creation. The request names the `room_id`, the `batch_id` to draw from, the `allocated_tonnage` to reserve, the occupancy window `planned_start` to `planned_end`, and the `expected_room_version` covered in §2.6. The batch must be `SPAWNED` (otherwise `ERR_BATCH_NOT_SPAWNED`), the `allocated_tonnage` must be greater than zero, must not exceed the room’s `capacity_tonnes` (otherwise `ERR_ROOM_CAPACITY_EXCEEDED`), and must not exceed the batch’s `remaining_tonnage` (otherwise `ERR_INSUFFICIENT_SUBSTRATE`). Rooms enforce a turnover buffer: every existing cycle of the room in `SCHEDULED`, `SPAWN_RUN`, `CASING`, `FRUITING`, or `TURNAROUND` blocks the half-open interval from its own `planned_start` up to its `planned_end` plus 2 days, and a new cycle whose `[planned_start, planned_end)` intersects any blocking interval is rejected with `ERR_ROOM_WINDOW_OVERLAP`. A new cycle starting exactly at an existing cycle’s `planned_end` plus 2 days is allowed. A successful booking debits `allocated_tonnage` from the batch’s `remaining_tonnage` (auto-exhausting the batch at exactly zero as described in §3.1), copies the `variety_id` from the batch, increments the room’s `version` by 1, and recomputes the variety’s `planned_production_kg`. Cycles may be listed filtered by `room_id`, `batch_id`, `variety_id`, or `status`.

Placement begins the crop. When the logical clock falls within `[planned_start, planned_end]` inclusive, a `FarmManager` places the cycle, moving it from `SCHEDULED` to `SPAWN_RUN`. Placement requires the cycle to be `SCHEDULED` (otherwise `ERR_ROOM_CYCLE_INVALID_PHASE`), the room’s `occupancy_status` to be `IDLE` (otherwise `ERR_ROOM_NOT_IDLE`), the room’s `health_status` to be anything other than `QUARANTINED` (otherwise `ERR_ROOM_QUARANTINED`), and the window to be open (otherwise `ERR_CYCLE_WINDOW_NOT_OPEN`). Placement stamps `placed_at` and `phase_entered_at` with the clock time, flips the room’s `occupancy_status` from `IDLE` to `OCCUPIED`, and computes the cycle’s two yield projections. The `scheduled_projection_kg` is the forward-looking estimate: `allocated_tonnage` times 1000 times the variety’s `target_bioefficiency_pct` divided by 100. The `actualized_projection_kg` starts equal to the scheduled figure and thereafter tracks reality (§3.3).

Phase advancement is clock-gated by the variety. Advancing from `SPAWN_RUN` to `CASING` requires the logical clock to have reached `placed_at` plus the variety’s `spawn_run_days` whole days; advancing from `CASING` to `FRUITING` requires the clock to have reached `phase_entered_at` plus the variety’s `casing_days` whole days. Either advance attempted too early is rejected with `ERR_COLONIZATION_INCOMPLETE`, and an advance from the wrong phase is rejected with `ERR_ROOM_CYCLE_INVALID_PHASE`. Each successful advance refreshes `phase_entered_at` to the current clock time.

Cropping ends in one of two ways. A `FarmManager` may manually end cropping on a `FRUITING` cycle — even one with zero recorded flushes — or the system ends it automatically the moment a grading brings the cycle’s `flush_count` to the variety’s `max_flushes`. Either way the cycle moves `FRUITING → TURNAROUND`, and the turnover produces a `SpentSubstrateLot` whose `tonnage` is the cycle’s `allocated_tonnage` multiplied by 0.75 and rounded to 2 decimal places — a 40.0-tonne allocation yields a 30.00-tonne lot, the 25% mass loss being moisture and ammonia off-gassing — with `disposal_only` set to false for an ordinary turnover. The room’s `occupancy_status` moves from `OCCUPIED` to `TURNAROUND`, and the variety’s `planned_production_kg` is recomputed as the cycle leaves the planning set. Once cleanout is finished, certifying the cleanout moves the cycle `TURNAROUND → CLOSED` and returns the room’s `occupancy_status` from `TURNAROUND` to `IDLE`, freeing the room regardless of its health posture.

Two early exits exist. Cancelling is only possible while the cycle is still `SCHEDULED` (otherwise `ERR_ROOM_CYCLE_INVALID_PHASE`); it moves the cycle to `CANCELLED`, credits the full `allocated_tonnage` back to the batch’s `remaining_tonnage` as the compensating action of the original reservation, and recomputes `planned_production_kg`. Aborting applies to a placed cycle in `SPAWN_RUN`, `CASING`, or `FRUITING` — whether invoked manually by a `FarmManager` or triggered by the quarantine cascade of §3.7 — and moves the cycle to `ABORTED`. An abort consumes the tonnage (no credit back), still produces a spent lot at the same 0.75 factor, sets the lot’s `disposal_only` to true if and only if the abort was caused by the quarantine cascade, moves the room `OCCUPIED → TURNAROUND`, and recomputes both the variety’s `planned_production_kg` and the `supply_at_risk` flag of every `ACTIVE` commitment line of that variety.

### 3.3. Flush Harvests, Grading, and Yield Projection

While a cycle is `FRUITING`, a `FarmManager` records flush harvests against it. Recording requires the cycle to be `FRUITING` and the room not to be `QUARANTINED` — a quarantined room’s flushes cannot be recorded or packed, rejected with `ERR_ROOM_QUARANTINED`. The picker reports the `total_kg` picked, which must be greater than zero; the system assigns `flush_number` automatically as the count of existing flushes of the cycle plus one, stamps `recorded_at` with the clock time, and creates the flush in `RECORDED` status. Recording a flush that would exceed the variety’s `max_flushes` is rejected with `ERR_FLUSH_LIMIT_REACHED` (HTTP 409). Flushes may be listed under their cycle or farm-wide filtered by `room_cycle_id` and `status`.

Grading turns a recorded flush into marketable truth. A `GradingInspector` grades a flush that is `RECORDED` (otherwise `ERR_FLUSH_NOT_RECORDED`) by splitting it into `grade_a_kg`, `grade_b_kg`, and `cull_kg`; the three figures must sum to `total_kg` exactly at 2 decimal places, otherwise `ERR_GRADE_SPLIT_MISMATCH`. Grading stamps `graded_at`, moves the flush to `GRADED`, and bubbles up to the cycle: `flush_count` — the count of flushes in `GRADED` or `SETTLED` — increases by 1 and `harvested_kg` — the sum of `total_kg` over those same flushes — increases by the flush’s `total_kg`, and the cycle’s `actualized_projection_kg` is recomputed. If the grading makes `flush_count` equal the variety’s `max_flushes`, the cycle automatically ends cropping exactly as the manual path does: `FRUITING → TURNAROUND`, the spent lot is created with `disposal_only` false, and the room moves to `TURNAROUND`.

The actualized projection is a chronological replayer. It takes the graded reality so far — the sum of `total_kg` over flushes in `GRADED` or `SETTLED` — and adds, for each remaining flush index from `flush_count` plus one through `max_flushes`, the cycle’s total expected kilograms (the same `allocated_tonnage` times 1000 times `target_bioefficiency_pct` divided by 100 used for the scheduled figure) multiplied by that flush index’s entry in the variety’s `flush_yield_distribution`. The scheduled projection, by contrast, is computed once at placement and never observes actual flushes. Consider a 40.0-tonne allocation of a variety with `target_bioefficiency_pct` 25.0 and distribution [0.5, 0.3, 0.2]: the total expectation is 10000.0 kg, so `scheduled_projection_kg` stays 10000.0, but after flush 1 is graded at 100.0 kg the actualized figure becomes 100.0 plus 3000.0 plus 2000.0 — 5100.0 kg — diverging as soon as reality departs from the distribution.

A grading can be walked back, but only while nothing downstream has committed to it. Reopening requires the flush to be `GRADED` (otherwise `ERR_FLUSH_NOT_GRADED`), the parent cycle to still be `FRUITING` (otherwise `ERR_ROOM_CYCLE_INVALID_PHASE`), no packaged lots to exist for the flush, and every harvest piece of the flush to still be `LOGGED`; packaged lots or already-approved pieces block the reopen with `ERR_FLUSH_HAS_COMMITTED_PIECES`. A successful reopen clears `grade_a_kg`, `grade_b_kg`, `cull_kg`, and `graded_at` back to null, returns the flush to `RECORDED`, decrements the cycle’s `flush_count` by 1 and `harvested_kg` by the flush’s `total_kg` as exact compensation, and recomputes the actualized projection. Finally, a flush settles automatically: the moment it has at least one harvest piece and every piece is `PAID`, the system moves the flush from `GRADED` to its terminal `SETTLED` status.

### 3.4. Piece-Rate Labor and Payroll

Harvest workers are registered by a `FarmManager` with a `full_name`, a `crew_code`, and a `piece_rate_cents_per_kg` greater than zero. A worker starts `ACTIVE` with `accrued_unpaid_cents` and `lifetime_paid_cents` both 0. A `FarmManager` may suspend or reactivate a worker by patching its `status` to `SUSPENDED` or `ACTIVE`; a patch that requests the status the worker already has is a no-op rejected with `ERR_INVALID_REQUEST`.

Piece logging is the crew lead’s job. A `HarvestCrewLead` logs a picking entry on a flush that is `RECORDED` (otherwise `ERR_FLUSH_NOT_RECORDED`), naming the `worker_id` credited and the `kg_picked`, which must be greater than zero. The worker must be `ACTIVE`, otherwise `ERR_WORKER_NOT_ACTIVE`. The system stores the caller’s `X-User-ID` as the piece’s `logged_by_user_id` — the segregation-of-duties anchor — snapshots the worker’s current rate into `rate_cents_per_kg`, computes `provisional_pay_cents` as the flat figure `kg_picked` times `rate_cents_per_kg` rounded half-up to whole cents, and creates the piece in `LOGGED` status. Pieces may be listed under their flush or farm-wide filtered by `worker_id`, `flush_id`, or `status`.

Approval is where grades meet money, and it belongs to a `PayrollClerk` — never to the person who logged the piece. Approving requires the piece to be `LOGGED` or `DISPUTED` (otherwise `ERR_PIECE_INVALID_STATE`) and the parent flush to be `GRADED` (otherwise `ERR_FLUSH_NOT_GRADED`), and the clerk’s `X-User-ID` must differ from the piece’s `logged_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`. Approval computes `final_pay_cents` using the parent flush’s grade shares: the piece earns `kg_picked` times `rate_cents_per_kg` times a weighting factor of 1.20 times the grade-A share (the flush’s `grade_a_kg` divided by its `total_kg`), plus 1.00 times the grade-B share, plus 0.0 times the cull share, with the whole result rounded half-up to whole cents at that moment. For a piece of 40.0 kg at a rate of 50 cents per kilogram on a flush graded 60% A, 30% B, 10% cull, the factor is 1.02: the provisional figure at logging was 2000 cents, and the final figure at approval is 2040 cents. Approval moves the piece to `APPROVED` and adds `final_pay_cents` to the worker’s `accrued_unpaid_cents`. A `DISPUTED` piece follows the identical path back to `APPROVED`, with the same preconditions and the same computation.

Dispute is the compensating twin of approval. A `PayrollClerk` may dispute an `APPROVED` piece (from any other state, `ERR_PIECE_INVALID_STATE`), subject to the same segregation-of-duties check against `logged_by_user_id`. Disputing moves the piece to `DISPUTED` and subtracts its `final_pay_cents` from the worker’s `accrued_unpaid_cents`, exactly reversing the approval; the `final_pay_cents` value itself is retained on the piece for audit. Approve-then-dispute therefore returns the accrual to its prior value exactly.

Payout turns accrual into wages. When a `PayrollClerk` runs a worker’s payout, every `APPROVED` piece of that worker moves to `PAID`; the paid total is the sum of the already-rounded per-piece `final_pay_cents` values; the worker’s `accrued_unpaid_cents` returns to 0 and `lifetime_paid_cents` grows by the paid total. The response reports `paid_piece_count` and `total_paid_cents`. After each payout the system checks the affected flushes: if a flush now has at least one piece and every piece is `PAID`, the flush bubbles up from `GRADED` to `SETTLED`.

### 3.5. Packaging, Shelf-Life, and Order Allocation

A `GRADED` flush is packed into sellable lots by a `FarmManager`. The room of the flush’s cycle must not be `QUARANTINED`, otherwise `ERR_ROOM_QUARANTINED`. Each lot declares a `grade` of `A` or `B` — culls are not packable — a `units` count greater than zero, and a `kg_per_unit` greater than zero; the lot’s `lot_kg` is `units` times `kg_per_unit`, rounded half-up to 2 decimal places. Packaging draws down per-grade remaining kilograms: for grade A the remaining is the flush’s `grade_a_kg` minus the sum of `lot_kg` over every packaged lot of this flush with grade A, and likewise for grade B against `grade_b_kg` — every created lot counts regardless of its later status, because packing consumes physical product. A lot whose `lot_kg` exceeds the remaining kilograms of its grade is rejected with `ERR_INSUFFICIENT_GRADE_KG`; packaging a flush that is not `GRADED` is rejected with `ERR_FLUSH_NOT_GRADED`. A new lot is `IN_STOCK`, stamped with `packed_at` at the clock time, and its `expires_at` is `packed_at` plus the variety’s `shelf_life_days` whole days — the exact instant that many days later. Its `variety_id` is copied from the flush’s cycle. Lots may be listed filtered by `flush_id`, `variety_id`, `allocated_line_id`, or `status`.

The shelf-life clock is enforced at two points. During the daily sweep, any lot in `IN_STOCK` or `ALLOCATED` whose `expires_at` is less than or equal to the current clock time moves to `EXPIRED` — the boundary is inclusive, so a lot expiring exactly at the sweep instant expires. When an `ALLOCATED` lot expires, its commitment line is credited back: `allocated_kg` decreases by `lot_kg` and `allocated_line_id` is cleared to null. Shipping, by contrast, uses a strict guard: a lot may ship only while `expires_at` is strictly greater than the current clock time, and equality is rejected with `ERR_LOT_EXPIRED`.

Allocation is a first-expiry-first-out sweep performed by a `SalesManager` against an `ACTIVE` commitment line (otherwise `ERR_LINE_NOT_ACTIVE`), carrying a `target_kg`. The guard comes first: `target_kg` must not exceed the line’s open commitment — `committed_kg` minus `delivered_kg` minus `allocated_kg` — otherwise `ERR_ALLOCATION_EXCEEDS_OPEN_COMMITMENT`. The candidate pool is every `IN_STOCK` packaged lot of the line’s variety, farm-wide, whose grade satisfies the line’s `min_grade` — a `min_grade` of `B` accepts both `A` and `B` lots, while `A` accepts only `A` lots — and whose `expires_at` is strictly after the current clock time. Candidates are ranked by `expires_at` ascending with ties broken by `created_at` ascending, never by id. The sweep then walks the ranked list taking whole lots while the running total plus the candidate’s `lot_kg` stays within `target_kg`, and it stops at the first lot that would overshoot — no skipping ahead to a smaller lot. If nothing at all was taken, the allocation is rejected with `ERR_NO_ELIGIBLE_LOTS`. Each taken lot moves `IN_STOCK → ALLOCATED`, records the line in its `allocated_line_id`, and adds its `lot_kg` to the line’s `allocated_kg`; the response reports the `allocated_lot_ids` and the total `allocated_kg`.

Two manual exits manage allocated stock. Deallocating returns an `ALLOCATED` lot to `IN_STOCK`, subtracting its `lot_kg` from the line’s `allocated_kg` and clearing `allocated_line_id`; a lot that is not `ALLOCATED` is rejected with `ERR_LOT_NOT_ALLOCATED`. Shipping an `ALLOCATED` lot — again `ERR_LOT_NOT_ALLOCATED` otherwise, and subject to the strict expiry guard above — moves it to `SHIPPED`, moves its `lot_kg` from the line’s `allocated_kg` into `delivered_kg`, and recomputes the parent commitment’s `total_delivered_kg`.

### 3.6. Buyer Commitments and Weekly Settlement

Buyers are registered by a `SalesManager` with a `name` and start `ACTIVE`, carrying a `lifetime_shortfall_penalty_cents` of 0. Suspension and reactivation patch the buyer’s `status` between `ACTIVE` and `SUSPENDED`; a no-op patch is rejected with `ERR_INVALID_REQUEST`.

A buyer commitment begins life in `DRAFT`. Creation names the `buyer_id` and a purchase-order `reference`; the buyer must be `ACTIVE`, otherwise `ERR_BUYER_NOT_ACTIVE`, and a `BuyerPortal` caller must be creating for itself per §2.1. Commitments may be listed filtered by `buyer_id` and `status`. While the commitment is `DRAFT`, a `SalesManager` adds lines to it — a commitment in any other status rejects the addition with `ERR_COMMITMENT_NOT_DRAFT`. Each line names the `variety_id`, a `committed_kg` greater than zero, the delivery window `week_start` to `week_end` (end strictly after start, otherwise `ERR_INVALID_REQUEST`), and an optional `min_grade` of `A` or `B` defaulting to `B`. The line’s `commitment_id` is taken from the path. New lines start `DRAFT` with `delivered_kg` and `allocated_kg` at 0.0, `settlement_outcome` null, `shortfall_kg` 0.0, `penalty_cents` 0, and `supply_at_risk` false. Adding a line recomputes the commitment’s `total_committed_kg` — the sum of `committed_kg` over its child lines — but deliberately does not increment the commitment’s `version`. Lines may be listed filtered by `commitment_id`, `variety_id`, or `status`.

Activation is the OCC-guarded handshake described in §2.6. The commitment must be `DRAFT` (otherwise `ERR_COMMITMENT_NOT_DRAFT`) and must have at least one line (otherwise `ERR_COMMITMENT_EMPTY`); the request must carry `expected_commitment_version`. Activation moves the commitment to `ACTIVE`, moves every child line from `DRAFT` to `ACTIVE`, increments the commitment’s `version` by 1, and recomputes each affected variety’s `active_committed_kg` — the sum of `committed_kg` over that variety’s `ACTIVE` lines. From then on, each active line’s `supply_at_risk` flag tracks the planning book: it is true whenever the variety’s `planned_production_kg` — the sum of `scheduled_projection_kg` over that variety’s cycles in `SCHEDULED`, `SPAWN_RUN`, `CASING`, or `FRUITING` — falls below the line’s undelivered remainder, `committed_kg` minus `delivered_kg`.

Cancelling a commitment is allowed only while nothing has moved against it. The commitment must be `ACTIVE` (otherwise `ERR_COMMITMENT_NOT_ACTIVE`), every line’s `delivered_kg` must be 0 (otherwise `ERR_COMMITMENT_HAS_DELIVERIES`), and no packaged lot may be `ALLOCATED` to any of its lines (otherwise `ERR_COMMITMENT_HAS_ALLOCATIONS`). Cancellation moves the commitment to `CANCELLED` and every child line to `CANCELLED` — a `DRAFT` line simply flips, while an `ACTIVE` line’s cancellation additionally recomputes the variety’s `active_committed_kg`.

Settlement happens in the daily ops-run checkpoint, a `FarmManager` capability that also runs the shelf-life expiry of §3.5. For each `ACTIVE` line whose `week_end` is strictly before the current clock time, the sweep computes the outcome. The `shortfall_kg` is `committed_kg` minus `delivered_kg`, clamped at zero so it never goes negative. Delivery is judged against a 5% tolerance: if `delivered_kg` is at least 95% of `committed_kg` — the boundary is inclusive, so exactly 95% counts — the line settles `FULFILLED` with `penalty_cents` 0. Otherwise the line settles `SHORTFALL` and pays a tiered penalty on the shortfall: when the shortfall ratio — `shortfall_kg` divided by `committed_kg` — is at most 0.15, the rate is 120 cents per shortfall kilogram; when it is above 0.15 but at most 0.40, the rate is 200; above 0.40, the rate is 350. The `penalty_cents` is the shortfall kilograms times the selected rate, rounded half-up to whole cents. For example, a line committed to 500 kg that delivered 400 kg records a shortfall of 100 kg, a ratio of 0.20, the 200-cent tier, and a penalty of 20000 cents; a line committed to 500 kg that delivered 475 kg meets the inclusive 95% boundary and settles `FULFILLED` with no penalty, though its `shortfall_kg` of 25.0 is still recorded. Settling a line adds its `penalty_cents` to the buyer’s `lifetime_shortfall_penalty_cents` and recomputes the commitment’s totals — `total_committed_kg`, `total_delivered_kg`, and `total_shortfall_penalty_cents`, each the sum of the corresponding line figure. When every line of a commitment has reached `SETTLED` or `CANCELLED`, the commitment itself bubbles up from `ACTIVE` to `CLOSED`. The sweep response reports `expired_lot_count`, `settled_line_count`, and `closed_commitment_count`.

### 3.7. Contamination Events and Room Health

A `QualityInspector` reports a contamination event against a room, optionally pinning a specific cycle of that room — a `room_cycle_id` that does not belong to the given `room_id` is rejected with `ERR_ROOM_CYCLE_NOT_FOUND`. The report names the `pathogen` (one of `TRICHODERMA`, `COBWEB`, `BACTERIAL_BLOTCH`, or `VIRUS`), a `severity` from 1 to 5, and an `affected_zone_pct` from 0 to 100. A new event is `REPORTED`, and a merely reported event never moves the room’s posture. Events may be listed filtered by `room_id`, `room_cycle_id`, or `status`.

Confirmation is the hinge. Confirming requires the event to be `REPORTED` (otherwise `ERR_EVENT_INVALID_STATE`) and moves it to `CONFIRMED`. If the confirmed `severity` is 4 or higher, the room’s `health_status` goes to `QUARANTINED`, and the quarantine cascades: any room cycle of that room in `SPAWN_RUN`, `CASING`, or `FRUITING` is aborted, producing a spent lot with `disposal_only` set to true and recomputing both the variety’s `planned_production_kg` and the `supply_at_risk` flags of the variety’s `ACTIVE` commitment lines. If the confirmed severity is 3 or lower and the room is `CLEAR`, the room moves to `WATCH` instead. A false alarm can be dismissed while still `REPORTED`, moving the event to `DISMISSED` with no posture change. Confirmed events proceed through remediation: a `CONFIRMED` event begins remediation, moving to `REMEDIATING`, and a `REMEDIATING` event is cleared, moving to `CLEARED` — each step from the wrong state is rejected with `ERR_EVENT_INVALID_STATE`.

The room’s health posture is recomputed after every confirm, dismiss, or clear on any event of the room, from the set of open events — those in `REPORTED`, `CONFIRMED`, or `REMEDIATING`. If any open event in `CONFIRMED` or `REMEDIATING` has `severity` of 4 or higher, the room is `QUARANTINED`. Otherwise, if any open event is in `CONFIRMED` or `REMEDIATING`, the room is `WATCH`. Otherwise — no open events at all, or only events still `REPORTED` — the room is `CLEAR`. So clearing the last severe event while a lesser confirmed event remains drops the room from `QUARANTINED` to `WATCH`, and clearing the final open event returns it to `CLEAR`.

Quarantine gates the growing operation. While a room’s `health_status` is `QUARANTINED`, placing a cycle into that room is rejected with `ERR_ROOM_QUARANTINED`, and recording or packaging flushes of that room’s cycle is likewise rejected with `ERR_ROOM_QUARANTINED`. Notably, certifying a cleanout still frees a quarantined room’s occupancy, since the two status dimensions are independent.

### 3.8. Spent Substrate Recovery and Batch Retirement

Every crop that ends — by turnover or by abort — leaves behind a spent substrate lot. The lot references the `room_cycle_id` that produced it and the `batch_id` copied from that cycle, and its `tonnage` is the cycle’s `allocated_tonnage` times 0.75 rounded to 2 decimal places. Lots born of a quarantine-cascade abort carry `disposal_only` true; all others carry false. A lot starts `AVAILABLE` with `reserved_buyer_id`, `sale_price_cents`, and `disposal_cost_cents` all null. Lots may be listed filtered by `room_cycle_id`, `batch_id`, `reserved_buyer_id`, or `status`.

Resale is a `SalesManager` workflow. Reserving a lot for a buyer requires the lot to be `AVAILABLE` (otherwise `ERR_SPENT_LOT_INVALID_STATE`), requires the lot not to be `disposal_only` (otherwise `ERR_SPENT_LOT_DISPOSAL_ONLY`), and requires the named `buyer_id` to exist (otherwise `ERR_BUYER_NOT_FOUND`) and be `ACTIVE` (otherwise `ERR_BUYER_NOT_ACTIVE`); reservation records the buyer in `reserved_buyer_id`. A reservation can be released, returning the lot to `AVAILABLE` and clearing `reserved_buyer_id`. Selling requires the lot to be `RESERVED` (otherwise `ERR_SPENT_LOT_INVALID_STATE`) and again rejects disposal-only lots with `ERR_SPENT_LOT_DISPOSAL_ONLY`; the agreed `sale_price_cents` must be at least the lot’s `tonnage` times 1500 cents per tonne, rounded to whole cents — a price below that floor is rejected with `ERR_PRICE_BELOW_FLOOR`. A sale records `sale_price_cents`, moves the lot to `SOLD`, and adds the price to the batch’s `spent_revenue_cents`.

Disposal is the universal exit, and the only terminal path for a disposal-only lot. A `FarmManager` may dispose a lot in `AVAILABLE` or `RESERVED` (from any other state, `ERR_SPENT_LOT_INVALID_STATE`); disposing computes `disposal_cost_cents` as the lot’s `tonnage` times 2500 cents per tonne in tipping fees, rounded to whole cents, moves the lot to `DISPOSED`, clears `reserved_buyer_id` if one was set, and adds the cost to the batch’s `disposal_cost_cents`. Only once every spent lot of a batch has reached `SOLD` or `DISPOSED` — and every cycle of the batch is terminal — can the batch itself be retired, as told in §3.1.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Creation of a new resource returns HTTP 201 with the created resource; modifications, state transitions, and action endpoints return HTTP 200 with the updated resource or result payload. All GET endpoints are readable by every authenticated role (role `Any`).

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/_clock/set_current_utc` | Advance the logical clock to `to_iso8601` (no regression) | FarmManager |
| POST | `/api/operations/run-daily-sweep` | Expire lots, settle due commitment lines, close finished commitments | FarmManager |
| POST | `/api/varieties` | Register a mushroom variety | CompostSupervisor |
| GET | `/api/varieties/{varietyId}` | Get a variety with computed supply/demand fields | Any |
| POST | `/api/buyers` | Register a buyer | SalesManager |
| GET | `/api/buyers/{buyerId}` | Get a buyer | Any |
| PATCH | `/api/buyers/{buyerId}` | Suspend or reactivate a buyer | SalesManager |
| POST | `/api/buyer-commitments` | Create a commitment in DRAFT | SalesManager, BuyerPortal |
| GET | `/api/buyer-commitments` | List commitments, optionally filtered | Any |
| GET | `/api/buyer-commitments/{commitmentId}` | Get a commitment | Any |
| POST | `/api/buyer-commitments/{commitmentId}/activate` | Activate a DRAFT commitment (OCC-guarded) | SalesManager |
| POST | `/api/buyer-commitments/{commitmentId}/cancel` | Cancel an ACTIVE commitment with no deliveries or allocations | SalesManager |
| POST | `/api/buyer-commitments/{commitmentId}/lines` | Add a line to a DRAFT commitment | SalesManager |
| GET | `/api/commitment-lines` | List commitment lines, optionally filtered | Any |
| GET | `/api/commitment-lines/{lineId}` | Get a commitment line | Any |
| POST | `/api/commitment-lines/{lineId}/allocate` | FEFO-allocate IN_STOCK lots to an ACTIVE line | SalesManager |
| POST | `/api/substrate-batches` | Create a substrate batch in MIXED | CompostSupervisor |
| GET | `/api/substrate-batches` | List substrate batches, optionally filtered | Any |
| GET | `/api/substrate-batches/{batchId}` | Get a substrate batch | Any |
| POST | `/api/substrate-batches/{batchId}/spawn` | Spawn a CONDITIONED batch with a variety | CompostSupervisor |
| POST | `/api/substrate-batches/{batchId}/retire` | Retire an EXHAUSTED batch once cycles and spent lots are terminal | CompostSupervisor |
| POST | `/api/pasteurization-tunnels` | Register a pasteurization tunnel | CompostSupervisor |
| GET | `/api/pasteurization-tunnels/{tunnelId}` | Get a tunnel | Any |
| POST | `/api/pasteurization-tunnels/{tunnelId}/sanitize` | Return an OUT_OF_SERVICE tunnel to AVAILABLE | CompostSupervisor |
| POST | `/api/pasteurization-cycles` | Schedule a pasteurization cycle for a MIXED batch | CompostSupervisor |
| GET | `/api/pasteurization-cycles` | List pasteurization cycles, optionally filtered | Any |
| GET | `/api/pasteurization-cycles/{cycleId}` | Get a pasteurization cycle | Any |
| POST | `/api/pasteurization-cycles/{cycleId}/start` | Start a SCHEDULED cycle within its window | CompostSupervisor |
| POST | `/api/pasteurization-cycles/{cycleId}/complete` | Complete a RUNNING cycle (at least 6.0 hours at target temp) | CompostSupervisor |
| POST | `/api/pasteurization-cycles/{cycleId}/fail` | Fail a RUNNING cycle; batch back to MIXED, tunnel OUT_OF_SERVICE | CompostSupervisor |
| POST | `/api/pasteurization-cycles/{cycleId}/abort` | Abort a SCHEDULED cycle; batch back to MIXED | CompostSupervisor |
| POST | `/api/rooms` | Register a growing room | FarmManager |
| GET | `/api/rooms` | List growing rooms | Any |
| GET | `/api/rooms/{roomId}` | Get a growing room | Any |
| POST | `/api/room-cycles` | Book a room cycle (OCC-guarded on the room version) | FarmManager |
| GET | `/api/room-cycles` | List room cycles, optionally filtered | Any |
| GET | `/api/room-cycles/{roomCycleId}` | Get a room cycle with both yield projections | Any |
| POST | `/api/room-cycles/{roomCycleId}/place` | Place a SCHEDULED cycle into its room at window open | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/advance` | Advance SPAWN_RUN to CASING to FRUITING per minimum day counts | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/end-cropping` | End cropping on a FRUITING cycle (manual turnover) | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/certify-cleanout` | Certify cleanout of a TURNAROUND cycle, freeing the room | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/cancel` | Cancel a SCHEDULED cycle, releasing the tonnage reservation | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/abort` | Abort a placed cycle, consuming tonnage and producing a spent lot | FarmManager |
| POST | `/api/room-cycles/{roomCycleId}/flushes` | Record a flush harvest on a FRUITING cycle | FarmManager |
| GET | `/api/room-cycles/{roomCycleId}/flushes` | List flushes of a cycle | Any |
| GET | `/api/flushes` | List flush harvests, optionally filtered | Any |
| GET | `/api/flushes/{flushId}` | Get a flush harvest | Any |
| POST | `/api/flushes/{flushId}/grade` | Grade a RECORDED flush; split must sum to total | GradingInspector |
| POST | `/api/flushes/{flushId}/reopen` | Reopen a GRADED flush for correction | GradingInspector |
| POST | `/api/flushes/{flushId}/packaged-lots` | Pack a GRADED flush into sellable lots | FarmManager |
| GET | `/api/packaged-lots` | List packaged lots, optionally filtered | Any |
| GET | `/api/packaged-lots/{lotId}` | Get a packaged lot | Any |
| POST | `/api/packaged-lots/{lotId}/deallocate` | Return an ALLOCATED lot to IN_STOCK | SalesManager |
| POST | `/api/packaged-lots/{lotId}/ship` | Ship an ALLOCATED lot against its commitment line | SalesManager |
| POST | `/api/flushes/{flushId}/pieces` | Log a piece-rate picking entry on a RECORDED flush | HarvestCrewLead |
| GET | `/api/flushes/{flushId}/pieces` | List pieces of a flush | Any |
| GET | `/api/pieces` | List pieces, optionally filtered | Any |
| GET | `/api/pieces/{pieceId}` | Get a piece | Any |
| POST | `/api/pieces/{pieceId}/approve` | Approve a LOGGED or DISPUTED piece (grade-weighted final pay) | PayrollClerk |
| POST | `/api/pieces/{pieceId}/dispute` | Dispute an APPROVED piece (compensating reversal) | PayrollClerk |
| POST | `/api/workers` | Register a harvest worker | FarmManager |
| GET | `/api/workers/{workerId}` | Get a worker | Any |
| PATCH | `/api/workers/{workerId}` | Suspend or reactivate a worker | FarmManager |
| POST | `/api/workers/{workerId}/payout` | Pay out all APPROVED pieces of a worker | PayrollClerk |
| POST | `/api/contamination-events` | Report a contamination event on a room | QualityInspector |
| GET | `/api/contamination-events` | List contamination events, optionally filtered | Any |
| GET | `/api/contamination-events/{eventId}` | Get a contamination event | Any |
| POST | `/api/contamination-events/{eventId}/confirm` | Confirm a REPORTED event (severity 4+ triggers quarantine cascade) | QualityInspector |
| POST | `/api/contamination-events/{eventId}/dismiss` | Dismiss a REPORTED event as a false alarm | QualityInspector |
| POST | `/api/contamination-events/{eventId}/remediate` | Begin remediation on a CONFIRMED event | QualityInspector |
| POST | `/api/contamination-events/{eventId}/clear` | Clear a REMEDIATING event; recompute room posture | QualityInspector |
| GET | `/api/spent-substrate-lots` | List spent substrate lots, optionally filtered | Any |
| GET | `/api/spent-substrate-lots/{lotId}` | Get a spent substrate lot | Any |
| POST | `/api/spent-substrate-lots/{lotId}/reserve` | Reserve an AVAILABLE lot for an ACTIVE buyer | SalesManager |
| POST | `/api/spent-substrate-lots/{lotId}/release` | Release a reservation back to AVAILABLE | SalesManager |
| POST | `/api/spent-substrate-lots/{lotId}/sell` | Sell a RESERVED lot at or above the price floor | SalesManager |
| POST | `/api/spent-substrate-lots/{lotId}/dispose` | Dispose an AVAILABLE or RESERVED lot at the tipping-fee rate | FarmManager |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_IDENTITY_NOT_RESOLVED | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_BUYER_MISMATCH | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VARIETY_NOT_FOUND | 404 |
| ERR_BUYER_NOT_FOUND | 404 |
| ERR_COMMITMENT_NOT_FOUND | 404 |
| ERR_LINE_NOT_FOUND | 404 |
| ERR_BATCH_NOT_FOUND | 404 |
| ERR_TUNNEL_NOT_FOUND | 404 |
| ERR_CYCLE_NOT_FOUND | 404 |
| ERR_ROOM_NOT_FOUND | 404 |
| ERR_ROOM_CYCLE_NOT_FOUND | 404 |
| ERR_FLUSH_NOT_FOUND | 404 |
| ERR_PIECE_NOT_FOUND | 404 |
| ERR_WORKER_NOT_FOUND | 404 |
| ERR_EVENT_NOT_FOUND | 404 |
| ERR_LOT_NOT_FOUND | 404 |
| ERR_SPENT_LOT_NOT_FOUND | 404 |
| ERR_BATCH_NOT_MIXED | 409 |
| ERR_BATCH_NOT_CONDITIONED | 409 |
| ERR_BATCH_NOT_SPAWNED | 409 |
| ERR_BATCH_NOT_EXHAUSTED | 409 |
| ERR_CYCLE_INVALID_STATE | 409 |
| ERR_TUNNEL_NOT_AVAILABLE | 409 |
| ERR_ROOM_NOT_IDLE | 409 |
| ERR_ROOM_CYCLE_INVALID_PHASE | 409 |
| ERR_FLUSH_NOT_RECORDED | 409 |
| ERR_FLUSH_NOT_GRADED | 409 |
| ERR_FLUSH_HAS_COMMITTED_PIECES | 409 |
| ERR_PIECE_INVALID_STATE | 409 |
| ERR_COMMITMENT_NOT_DRAFT | 409 |
| ERR_COMMITMENT_NOT_ACTIVE | 409 |
| ERR_COMMITMENT_EMPTY | 409 |
| ERR_COMMITMENT_HAS_DELIVERIES | 409 |
| ERR_COMMITMENT_HAS_ALLOCATIONS | 409 |
| ERR_LINE_NOT_ACTIVE | 409 |
| ERR_EVENT_INVALID_STATE | 409 |
| ERR_LOT_NOT_ALLOCATED | 409 |
| ERR_LOT_EXPIRED | 409 |
| ERR_SPENT_LOT_INVALID_STATE | 409 |
| ERR_UNRESOLVED_SPENT_LOTS | 409 |
| ERR_ROOM_QUARANTINED | 409 |
| ERR_SPENT_LOT_DISPOSAL_ONLY | 409 |
| ERR_TUNNEL_WINDOW_OVERLAP | 409 |
| ERR_ROOM_WINDOW_OVERLAP | 409 |
| ERR_CYCLE_WINDOW_NOT_OPEN | 409 |
| ERR_COLONIZATION_INCOMPLETE | 409 |
| ERR_CLOCK_REGRESSION | 409 |
| ERR_TUNNEL_CAPACITY_EXCEEDED | 422 |
| ERR_ROOM_CAPACITY_EXCEEDED | 422 |
| ERR_RECIPE_MISMATCH | 422 |
| ERR_INSUFFICIENT_SUBSTRATE | 422 |
| ERR_PASTEURIZATION_INCOMPLETE | 422 |
| ERR_GRADE_SPLIT_MISMATCH | 422 |
| ERR_FLUSH_LIMIT_REACHED | 409 |
| ERR_INSUFFICIENT_GRADE_KG | 422 |
| ERR_NO_ELIGIBLE_LOTS | 422 |
| ERR_ALLOCATION_EXCEEDS_OPEN_COMMITMENT | 422 |
| ERR_BUYER_NOT_ACTIVE | 409 |
| ERR_WORKER_NOT_ACTIVE | 409 |
| ERR_PRICE_BELOW_FLOOR | 422 |

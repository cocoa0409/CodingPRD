# Apple Packinghouse & Controlled-Atmosphere Storage API — Product Requirements Document

## 1. Introduction

Every autumn, a Washington apple packer takes delivery of thousands of field bins from dozens of growers, each bin traceable to a specific orchard block and each block carrying its own agronomic clock. This document specifies the Apple Packinghouse & Controlled-Atmosphere Storage API: the system of record for the packer's post-harvest operation, covering lot receiving with orchard/block traceability, controlled-atmosphere (CA) room management with oxygen setpoints and sealing schedules, presize grading, packing-line execution against retail-customer packaging specifications, storage-disorder monitoring with release prioritization, and cull/juice diversion for fruit that will never pack.

Two commercial commitments shape the design. First, fruit is perishable inventory held under managed atmospheres: rooms are sealed at a target oxygen concentration, inspected for scald, bitter pit, and decay, and emptied against deadlines derived from the fruit's agronomic storage life, the room's opening date, and disorder-driven priority releases. The API therefore treats time as a first-class input, driven by a deterministic logical clock rather than the wall clock. Second, the packer markets fruit through pooled sales: cartons are attributed to variety-and-grade marketing pools, growers receive provisional advances against an estimated pool price, and a pool close computes the final pool-average price that settles every grower — a reconciliation model in which estimates, advances, clawbacks, and rounding drift must all reconcile to the cent.

The API is a flat, multi-root REST surface guarded by role-based access control. Six roles share the work; optimistic concurrency protects the two highest-contention writes (room schedule edits and pool closes); and automatic cascades keep lots, rooms, allocations, pools, and settlements mutually consistent without requiring clients to issue compensating calls.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes exactly six roles. `Admin` is the packinghouse platform administrator and holds a superset of every operational role, and is additionally the only role that may register growers and drive the logical clock. `ReceivingClerk` staffs the receiving desk: orchard-block registration, lot receiving, and presize. `StorageOperator` runs CA storage: room registration and scheduling, sealing and opening, atmosphere readings, disorder inspections, bin allocations, releases, and lot diversion. `PackingSupervisor` runs the packing lines: scheduling, completing, cancelling, and voiding packing runs. `PoolManager` is the marketing office: packaging specs, pools, pooled sales, pool closes and reopens, and settlement advances. `Grower` is an external grower with read-only access scoped to its own records. A request with a missing or unrecognized header is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a recognized role attempting an operation outside its grant is rejected with `ERR_FORBIDDEN` (HTTP 403).

Identity semantics differ by role. When `X-User-Role` is `Admin`, `ReceivingClerk`, `StorageOperator`, `PackingSupervisor`, or `PoolManager`, the `X-User-ID` value is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it against any entity's `id`. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower` entity, and ownership checks compare the addressed resource's grower reference to that value. A grower caller addressing another grower's record, block list, lots, allocations, or settlements is rejected with `ERR_GROWER_SCOPE_VIOLATION` (HTTP 403); this scoping applies to the grower self-read, the grower's block list, the lot list and detail, the allocation list and detail, and the settlement list and detail. On the lot, allocation, and settlement list endpoints, grower callers are force-filtered to their own data — the lot list is constrained to the caller's own `grower_id`, the allocation list to allocations of the caller's own lots, and the settlement list to the caller's own rows. Read endpoints outside that scope (rooms, room inspections, specs, packing runs, pools) are freely readable by every authenticated role, including `Grower`.

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

Endpoints that return lists are paginated through the `limit` and `offset` query parameters. `limit` specifies the maximum number of items returned; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. `offset` specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Beyond pagination, list endpoints accept resource-scoped filters. The lot list filters by `grower_id`, `block_id`, and `status`; the allocation list by `room_id`, `lot_id`, and `status`; the packing-run list by `lot_id`, `spec_id`, `pool_id`, and `status`; the settlement list by `grower_id`, `pool_id`, and `status`. Block lists and inspection lists are scoped by their parent path rather than by query filter.

### 2.4. The Logical Clock

A single logical clock is the sole time source for the domain. Every timestamp the server stamps — a lot's `received_at`, an allocation's `allocated_at`, an inspection's `inspected_at`, a room's `sealed_at` and `actual_opened_at`, an allocation's `released_at` — reads this clock, and every deadline comparison (storage-life expiry, `must_release_by`, `must_empty_by`, and the future-date rule applied to a sealing request's `planned_open_date`) is evaluated against it. When the server starts and the clock has never been set, it reads exactly 2026-08-01T00:00:00Z; the logical clock must never fall back to wall-clock time.

An `Admin` may set the clock through a test-driving capability that accepts a `to_iso8601` instant, which must be a valid ISO 8601 UTC timestamp. Setting the clock backwards is rejected with `ERR_INVALID_REQUEST`.

### 2.5. Common Resource Properties

Every primary resource — growers, orchard blocks, lots, CA rooms, storage allocations, packaging specs, packing runs, pools, and grower settlements — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set at creation.
- `updated_at` (string): the same format, refreshed on any change to the resource's properties.
- `version` (integer): incremented by one on every mutation of the resource, including mutations caused by automatic cascades rather than direct client writes.

The disorder inspection is the single exception: it is an append-only event record and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it.

### 2.6. Precision, Rounding, and Units

Numeric discipline is fixed per quantity class. Fruit weights — `received_weight_lbs`, the presize size classes, run input and output weights, `diverted_weight_lbs`, and `weight_balance_lbs` — are exact decimal quantities, summed and compared with no rounding. Packout percentages (`est_packout_pct`, `actual_packout_pct`, and a run's `packout_pct`) and the `release_priority_score` are rounded half-up to one decimal place. An inspection's `disorder_index` is rounded half-up to two decimal places. All money is integer cents; any division or rate application that yields fractional cents is rounded half-up to whole cents. Bin quantities are whole integers. The phrase "rounded half-up" everywhere in this document means the conventional round-half-up rule applied at the stated decimal position.

### 2.7. Optimistic Concurrency Control

Exactly two writes are guarded by optimistic concurrency control, each requiring a non-optional version field echoing the client's last observed `version` of the parent resource.

Updating a room's sealing schedule (`PUT /ca-rooms/{id}/schedule`) requires `expected_ca_room_version`. If the room's stored `version` no longer matches the supplied value — because another schedule edit committed after the client's read, or because any cascade that touches the room (for example an inspection-driven `priority_release` update) has advanced it — the update is based on a stale view and is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the room before retrying.

Closing a pool (`POST /pools/{poolId}/close`) requires `expected_pool_version`. Closing commits the pool-average price computed from the totals the client last observed; if the pool's `version` has advanced since that read (a sale was recorded, a run completed or was voided), the close is based on stale totals and is rejected with `ERR_STALE_VERSION` (HTTP 412). The pool remains open, and a request carrying the current version may legitimately close it.

On both endpoints, omitting the version field entirely is rejected with `ERR_VERSION_REQUIRED` (HTTP 400). No endpoint other than these two accepts a version field.

### 2.8. Nested Resource Retrieval and Referential Existence

When a path contains several identifiers — a block under a grower, or allocations, inspections, readings, seals, opens, and schedule updates under a room — identifiers are validated left to right, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. Identifiers supplied in the request body must exist as well: the `grower_id` and `block_id` of a new lot, the `lot_id` of a new allocation, and the `lot_id`, `spec_id`, and `pool_id` of a new packing run each produce the same `ERR_NOT_FOUND` when they dangle.

### 2.9. Validation Order

When several checks would fail on a single call, the first applicable tier below determines the response. Individual errors carry the HTTP statuses catalogued in §5; a tier may group errors whose statuses differ.

1. **Authentication** — `X-User-Role` and `X-User-ID` are present and the role is one of the six declared roles, else `ERR_UNAUTHENTICATED`.
2. **Endpoint authorization** — the role is permitted on this endpoint, else `ERR_FORBIDDEN`.
3. **Grower scope** — a `Grower` caller addresses only its own record, blocks, lots, allocations, and settlements, else `ERR_GROWER_SCOPE_VIOLATION`.
4. **Existence** — path identifiers resolve left to right, then body-supplied foreign keys exist, else `ERR_NOT_FOUND`.
5. **Request shape** — required fields are present, JSON types are correct, enum values fall within their declared sets, percentage fields stay within 0 to 100, and creation quantities (`bins`, `received_bin_count`, `received_weight_lbs`, `input_weight_lbs`, `storage_life_days`, `bin_capacity`) are strictly positive, else `ERR_INVALID_REQUEST`. Sign rules on sale amounts are deliberately not evaluated here; they are fiscal checks at the final tier.
6. **OCC presence** — the two guarded endpoints carry their version field, else `ERR_VERSION_REQUIRED`.
7. **OCC freshness** — the supplied version equals the parent resource's current `version`, else `ERR_STALE_VERSION`.
8. **State gates** — the entity-specific preconditions of §3: presize requires a `RECEIVED` lot; diversion requires a `RECEIVED` or `IN_STORAGE` lot; allocation requires a `RECEIVED` or `PRESIZED` lot; run creation requires a `RELEASED` lot; allocation requires an `AVAILABLE`, `FILLING`, or `OPENED` room; sealing requires `FILLING` with at least one allocated bin; opening requires `SEALED`; manual and selected release require an `OPENED` room; inspections require `SEALED` or `OPENED`; schedule updates require `AVAILABLE`, `FILLING`, or `SEALED`; releases require an `ACTIVE` allocation; run scheduling requires an `ACTIVE` spec; completion and cancellation require a `SCHEDULED` run; voiding requires `COMPLETED`; sales, completions, and voids require an `OPEN` or `REOPENED` pool; closing requires `OPEN` or `REOPENED`; reopening requires `CLOSED`; an advance requires an `ACCRUING` settlement whose pool is `OPEN`. When several state gates fail on one call, the error is reported in this fixed order: lot first, then spec, pool, room, allocation, run, and settlement last. The block-to-grower referential check at lot creation (`ERR_BLOCK_GROWER_MISMATCH`) is also evaluated at this tier.
9. **Seal safety** — oxygen at setpoint, else `ERR_O2_NOT_AT_SETPOINT`.
10. **Temporal rules** — `ERR_OPEN_DATE_NOT_FUTURE`, `ERR_RUN_WINDOW_INVALID`, `ERR_LINE_SCHEDULE_OVERLAP`, and `ERR_LOT_STORAGE_LIFE_EXCEEDED`.
11. **Business constraints** — room capacity (`ERR_ROOM_CAPACITY_EXCEEDED`), weight balance (`ERR_WEIGHT_BALANCE_EXCEEDED`), color minimums (`ERR_COLOR_BELOW_SPEC`), exact weight splits (`ERR_RUN_WEIGHT_MISMATCH`), uniqueness keys (`ERR_UNIQUE_CONSTRAINT_VIOLATION`), and the pool-close guards (`ERR_POOL_HAS_OPEN_RUNS`, `ERR_POOL_EMPTY`). Within this tier, the no-open-runs check is evaluated before the non-empty check: a close that violates both reports `ERR_POOL_HAS_OPEN_RUNS`.
12. **Fiscal rules** — sale amount signs (`ERR_SALE_AMOUNT_INVALID`) and the attributed-carton requirement on advances (`ERR_NO_ATTRIBUTED_CARTONS`).

### 2.10. Conservation of Fruit Weight and Bin Capacity

A lot's `weight_balance_lbs` is at all times exactly its `received_weight_lbs` minus its `diverted_weight_lbs` minus the summed `input_weight_lbs` of its `COMPLETED`, non-`VOIDED` packing runs, computed with exact decimal arithmetic. Completing a run and later voiding it forms a compensating pair that leaves the balance exactly unchanged. Diverting a lot assigns the entire current balance to `diverted_weight_lbs`, which drives the balance to zero while keeping the identity intact, since the divert touches neither the received weight nor the run history.

A room's `bins_allocated` is the summed `bins` of its `ACTIVE` storage allocations, and its `bins_free` is `bin_capacity` minus `bins_allocated`. Creating an allocation and later releasing it is likewise a compensating pair that leaves `bins_free` exactly unchanged.

### 2.11. Automatic State Propagation

Many operations mutate several aggregates in a single commit, and the server performs these cascades itself rather than exposing compensating endpoints. An inspection can tighten a room's opening date and every allocation deadline beneath it; opening a room rewrites allocation deadlines and scores; releasing or diverting frees room capacity and can return a room to `AVAILABLE`; completing or voiding a run ripples into lot balances, pool totals, and settlement attribution; closing or reopening a pool reprices every settlement and can close or reopen the lots behind them. Every resource mutated by a cascade — whether directly addressed by the client or touched only as a downstream effect — refreshes its `updated_at` and increments its `version` per §2.5, which is precisely what the two concurrency guards of §2.7 observe.

## 3. Business Logic & Workflows

### 3.1. Growers, Orchard Blocks, and Lot Receiving

An `Admin` registers each grower or ranch by its legal `name` plus a packer-assigned `grower_code`. The code must be unique across all growers and is immutable once assigned; a duplicate is rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`.

With the grower on file, a `ReceivingClerk` registers orchard blocks beneath it, supplying an `orchard_name`, a `block_code`, the planted `variety` — one of `HONEYCRISP`, `GALA`, `FUJI`, `GRANNY_SMITH`, or `COSMIC_CRISP` — and `storage_life_days`, the agronomic maximum number of days fruit from that block may be stored, which must be strictly positive. The block's `grower_id` is taken from the grower it is created under. At most one block row may exist for a given combination of grower, `orchard_name`, `block_code`, and `variety`; a duplicate is rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`. The storage-life figure is not decorative: it bounds how long lots from the block may sit before packing (§3.4) and seeds the release deadline of every allocation holding the block's fruit (§3.2).

Fruit arrives at the receiving dock in field bins. A `ReceivingClerk` receives a lot by naming the delivering `grower_id` and source `block_id`, the `received_bin_count` (strictly positive), the net `received_weight_lbs` (strictly positive), and the `avg_color_pct` — the sampled average red-color coverage at receiving, between 0 and 100, which later gates which customer specs the lot can pack against. The block must belong to the stated grower: when the block's owning grower differs from the lot's `grower_id`, receiving is rejected with `ERR_BLOCK_GROWER_MISMATCH`, evaluated at the state-gate tier of §2.9. A freshly received lot is stamped with `received_at` from the logical clock, enters `RECEIVED` status, and its `weight_balance_lbs` is initialized to `received_weight_lbs`. The four presize profile fields (`size_small_lbs`, `size_medium_lbs`, `size_large_lbs`, `presize_cull_lbs`) and `diverted_weight_lbs` all start at zero; `est_packout_pct` and `actual_packout_pct` remain null until their respective computations exist.

Before storage or packing, the receiving desk may run the lot over the presize line. Presizing a lot that is not `RECEIVED` is rejected with `ERR_LOT_INVALID_STATE`. The clerk reports how the lot graded: `size_small_lbs`, `size_medium_lbs`, `size_large_lbs`, and `presize_cull_lbs`. These four figures must sum exactly to the lot's `received_weight_lbs`; any discrepancy is rejected with `ERR_RUN_WEIGHT_MISMATCH`, the same code used for weight splits at the packing line. On success the profile is stored, the lot transitions `RECEIVED → PRESIZED`, and its forward-looking `est_packout_pct` is computed: one hundred times the combined graded weight — small plus medium plus large — divided by the total presize throughput including culls (the three size classes plus `presize_cull_lbs`), rounded half-up to one decimal place. Because it is derived from the presize profile rather than realized line results, the estimate can diverge from the eventual `actual_packout_pct` whenever line-level cull and juice differ from the presize cull estimate.

### 3.2. Room Registration, Bin Allocation, Sealing, and Atmosphere Control

A `StorageOperator` registers each CA room with a unique `room_code` (duplicates rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`), a `bin_capacity` in whole bins (strictly positive), and an `o2_setpoint_pct` — the target oxygen percentage once sealed, between 0.1 and 21.0 inclusive. A new room starts `AVAILABLE` with `current_o2_pct` at 20.9 (ambient air), `atmosphere_alarm` false, `priority_release` false, `disorder_index` zero, and `o2_excursion_count` zero; `sealed_at`, `actual_opened_at`, and `must_empty_by` are null until their events occur.

Placing fruit into a room creates a storage allocation naming the `lot_id` and the number of `bins` (strictly positive); the allocation's `room_id` is taken from the room it is created under. The lot must be `RECEIVED` or `PRESIZED` (else `ERR_LOT_INVALID_STATE`), and the room must be `AVAILABLE`, `FILLING`, or `OPENED` — fruit may legitimately be added to an already-opened room (else `ERR_ROOM_INVALID_STATE`). The requested bins may not exceed the room's `bins_free`, else `ERR_ROOM_CAPACITY_EXCEEDED`. The new allocation is `ACTIVE`, stamped `allocated_at` from the logical clock, and its `must_release_by` deadline is the lot's `received_at` plus the block's `storage_life_days` — further clamped to the earlier of that and the room's `must_empty_by` whenever the room is already `OPENED`. The room's `bins_allocated` grows by the allocated bins; the first allocation into an `AVAILABLE` room moves it `AVAILABLE → FILLING`, while an `OPENED` room stays `OPENED`. Symmetrically, the lot's first `ACTIVE` allocation moves it from `RECEIVED` or `PRESIZED` to `IN_STORAGE`.

While a room is `AVAILABLE`, `FILLING`, or `SEALED`, a `StorageOperator` may revise its schedule — a new `planned_open_date`, a new `o2_setpoint_pct`, or both. Attempts in any other room state are rejected with `ERR_ROOM_INVALID_STATE`. This is one of the two OCC-guarded writes of §2.7: the request must carry `expected_ca_room_version`, and a committed update increments the room's `version` by one.

Sealing commits the room to controlled atmosphere. The room must be `FILLING` with at least one allocated bin, else `ERR_ROOM_INVALID_STATE`. Two further gates apply, in the order of §2.9: the safety gate requires the absolute difference between `current_o2_pct` and `o2_setpoint_pct` to be no greater than the oxygen tolerance `O2_TOLERANCE_PCT`, compared with exact decimal arithmetic — equality is within tolerance and passes, while a strictly greater deviation is rejected with `ERR_O2_NOT_AT_SETPOINT`; the temporal gate requires the supplied `planned_open_date` to lie strictly after the current logical clock, else `ERR_OPEN_DATE_NOT_FUTURE`. A successful seal records `sealed_at` from the clock, stores `planned_open_date`, and transitions the room `FILLING → SEALED`.

Opening a room — allowed only from `SEALED`, else `ERR_ROOM_INVALID_STATE` — starts the emptying clock: `actual_opened_at` is stamped from the logical clock and `must_empty_by` is set to the opening instant plus `ROOM_EMPTY_DAYS`. The opening then cascades to the room's contents: every `ACTIVE` allocation has its `must_release_by` tightened to the earlier of its existing deadline and the room's new `must_empty_by`, and each allocation's `release_priority_score` is recomputed. Opening a room that holds zero `ACTIVE` allocations — for example after a diversion emptied it while it was `SEALED` — is permitted, and the room simply stays `OPENED`; the automatic return to `AVAILABLE` fires only when a release or diversion while `OPENED` drops `bins_allocated` to zero.

Oxygen is tracked through recorded readings. Posting a reading with `o2_pct` stores it as the room's `current_o2_pct`. Alarm semantics apply only while the room is `SEALED`: a reading whose absolute deviation from `o2_setpoint_pct` strictly exceeds `O2_TOLERANCE_PCT` (exact decimal comparison, equality within tolerance) raises `atmosphere_alarm` and, only when the alarm flips from false to true, increments `o2_excursion_count` by one; a subsequent reading back within tolerance clears the alarm. Either flip recomputes the release scores of the room's `ACTIVE` allocations. Readings recorded while the room is not `SEALED` update the stored value without any alarm behavior.

### 3.3. Disorder Monitoring, Release Prioritization, and Diversion

While fruit sits in a `SEALED` or `OPENED` room, a `StorageOperator` records storage-disorder inspections; attempting one in any other room state is rejected with `ERR_ROOM_INVALID_STATE`. Each inspection captures three sampled percentages — `scald_pct`, `bitter_pit_pct`, and `decay_pct`, each between 0 and 100 — and is stamped `inspected_at` from the logical clock. The inspection's `disorder_index` blends the three samples: twenty percent of the scald figure, plus thirty percent of the bitter-pit figure, plus fifty percent of the decay figure, rounded half-up to two decimal places. The room's own `disorder_index` always reflects the latest inspection (zero when the room has never been inspected), and every `ACTIVE` allocation's `release_priority_score` is recomputed on each new inspection. A room's inspection history is retrievable as a paginated list.

Decay is the trigger the packer fears most. When an inspection's `decay_pct` reaches at least 5.0 percent — the threshold is inclusive — the priority-release cascade fires immediately. First the room: `priority_release` is set true, and `planned_open_date` is pulled in to the earlier of its current value and now plus `PRIORITY_OPEN_DAYS`. Then the fruit: every `ACTIVE` allocation in the room has its `must_release_by` tightened to the earlier of its existing deadline and now plus `PRIORITY_RELEASE_DAYS`, with release scores recomputed. Any client holding a stale room `version` discovers the cascade the next time its schedule update is rejected per §2.7.

Release scores decide which fruit leaves an opened room first. An allocation's `release_priority_score` is the sum of five terms: twice the room's `disorder_index`; forty points while the room's `atmosphere_alarm` is set; thirty points while the room's `priority_release` is set; the whole days the room has been open — measured with whole-day floor semantics from `actual_opened_at` to the current logical clock, and zero while the room is not `OPENED` — capped at twenty; and an urgency term of thirty minus the whole days remaining until the allocation's own `must_release_by`, where days remaining is computed with whole-day floor semantics and never falls below zero, so an allocation at or past its deadline contributes the full thirty points while one more than thirty days out contributes nothing. The total is rounded half-up to one decimal place. Scores are recomputed whenever an inspection is created for the room, whenever the atmosphere alarm changes in either direction, when the room opens, and when the priority-release cascade fires.

Releasing an allocation takes fruit out of storage and makes it packable. While an allocation is `ACTIVE`, its `released_at` and `release_reason` are null; both are set only when the release happens. A manual release by a `StorageOperator` requires the allocation to be `ACTIVE` (else `ERR_ALLOCATION_INVALID_STATE`) and its room to be `OPENED` (else `ERR_ROOM_INVALID_STATE`). The release stamps `released_at` from the clock, records `release_reason` `MANUAL`, and cascades in two directions: the room's `bins_allocated` falls by the released bins, and if that empties an `OPENED` room to zero the room returns to `AVAILABLE`, clearing `atmosphere_alarm` and `priority_release` and wiping `actual_opened_at` and `must_empty_by` for the next fill; meanwhile, if this is the lot's first release, the lot transitions `IN_STORAGE → RELEASED`.

When the operator prefers the system to choose, the selector release on an `OPENED` room (else `ERR_ROOM_INVALID_STATE`) ranks the room's `ACTIVE` allocations by `release_priority_score` from highest to lowest, breaking ties toward the earliest `allocated_at` and then the earliest `created_at`. If the room holds no `ACTIVE` allocations, the request is rejected with `ERR_NO_RELEASABLE_ALLOCATIONS`. The chosen allocation releases exactly as a manual release, except its `release_reason` is `SELECTED`.

Some fruit never packs. A `StorageOperator` may divert an entire lot to cull or juice while the lot is `RECEIVED` or `IN_STORAGE`; any other lot state is rejected with `ERR_LOT_INVALID_STATE`. Diversion sets the lot's `diverted_weight_lbs` to its entire current `weight_balance_lbs`, taking the balance to zero, and moves the lot to the terminal `DIVERTED` state. The cascade releases every `ACTIVE` allocation of the lot with `release_reason` `DIVERSION`, each affected room's `bins_allocated` falls accordingly, and any `FILLING` or `OPENED` room emptied to zero returns to `AVAILABLE` under the same clearing rules as a manual release. A lot diverted from `RECEIVED` never passed through storage, yet the same cascade shape applies — there are simply no allocations to release.

### 3.4. Packaging Specifications and the Packing Line

Retail customers buy to a spec. A `PoolManager` creates each packaging spec with the `customer_name` it serves, a `label_code` for the customer's label program, a `grade_min` of `EXTRA_FANCY`, `FANCY`, or `UTILITY` (the minimum grade packed under the spec), an integer `color_min_pct` between 0 and 100, a carton `size_class` of `SMALL`, `MEDIUM`, or `LARGE`, and a `pack_style` of `TRAY`, `BAG`, or `POUCH`. Specs are versioned by replacement: creating a new `ACTIVE` spec in the same scope — same `customer_name`, `size_class`, and `pack_style` — automatically supersedes the previously `ACTIVE` spec, which transitions `ACTIVE → SUPERSEDED`. A `SUPERSEDED` spec refuses new work: scheduling a run against it is rejected with `ERR_SPEC_INVALID_STATE`.

With fruit released and a spec in force, a `PackingSupervisor` schedules a packing run by naming the `lot_id`, the `spec_id`, the marketing `pool_id`, the `line_code` of the packing line, a half-open scheduling window from `scheduled_start` to `scheduled_end`, and the `input_weight_lbs` fed to the line. The gates, all evaluated under the §2.9 ordering: the lot must be `RELEASED` (else `ERR_LOT_INVALID_STATE`); the spec must be `ACTIVE` (else `ERR_SPEC_INVALID_STATE`); the pool must be `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`); the window must be strictly positive — `scheduled_end` strictly after `scheduled_start` — else `ERR_RUN_WINDOW_INVALID`; the window must not overlap any other `SCHEDULED` run on the same `line_code`, where windows are half-open intervals so back-to-back adjacency is permitted, else `ERR_LINE_SCHEDULE_OVERLAP`; the lot's `avg_color_pct` must be at least the spec's `color_min_pct` — equality passes and a strictly lower value is rejected with `ERR_COLOR_BELOW_SPEC`; the `input_weight_lbs` must be strictly positive and no more than the lot's current `weight_balance_lbs`, else `ERR_WEIGHT_BALANCE_EXCEEDED`; and the run may not be scheduled once the fruit is too old — when the current logical clock has passed the lot's `received_at` plus the block's `storage_life_days`, creation is rejected with `ERR_LOT_STORAGE_LIFE_EXCEEDED`. A newly created run is `SCHEDULED`.

Completion records what the line actually produced. The run must be `SCHEDULED` (else `ERR_RUN_INVALID_STATE`) and its pool must still be `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`). The supervisor reports `cartons_produced` (zero or more) and the three-way weight split: `packed_weight_lbs`, `cull_weight_lbs`, and `juice_weight_lbs`, each zero or more. The three weights must sum exactly to the run's `input_weight_lbs`; any mismatch is rejected with `ERR_RUN_WEIGHT_MISMATCH`. A successful completion moves the run `SCHEDULED → COMPLETED` and sets its `packout_pct` — one hundred times `packed_weight_lbs` divided by the sum of the three output weights, rounded half-up to one decimal place — then cascades outward. The lot's `weight_balance_lbs` falls by `input_weight_lbs`, and its `actual_packout_pct` is recomputed as a chronological aggregate over the lot's `COMPLETED`, non-`VOIDED` runs: one hundred times the summed `packed_weight_lbs` divided by the summed packed, cull, and juice weights across those runs, rounded half-up to one decimal place. Runs in `SCHEDULED`, `CANCELLED`, or `VOIDED` status never enter the aggregate, which remains null until the lot's first completion. A `RELEASED` lot whose balance reaches zero transitions `RELEASED → PACKED`. The pool's `total_packed_cartons` grows by `cartons_produced`, and the pool's totals and estimated price are recomputed. Finally, the grower settlement for the pairing of the lot's grower and this pool is auto-created in `ACCRUING` status if absent, and its `attributed_cartons` is recomputed.

Cancellation is the quiet exit: a `SCHEDULED` run (else `ERR_RUN_INVALID_STATE`) moves to `CANCELLED`, freeing its line window with no weight or pool effects, since nothing was consumed.

Voiding is the loud one — the compensation path for a completion that should not stand. The run must be `COMPLETED` (else `ERR_RUN_INVALID_STATE`) and its pool must still be `OPEN` or `REOPENED`; once a pool is closed its results are locked, and a void against it is rejected with `ERR_POOL_INVALID_STATE`. The void moves the run `COMPLETED → VOIDED`, clears its `packout_pct`, credits the lot's `weight_balance_lbs` back by `input_weight_lbs`, and recomputes `actual_packout_pct` excluding the voided run. A `PACKED` lot whose balance is positive again reverts `PACKED → RELEASED`, reopening it for further packing — the deliberate revision loop of the lot lifecycle. The pool's `total_packed_cartons` falls by `cartons_produced` with totals and estimated price recomputed, and the settlement's `attributed_cartons` is recomputed to match.

### 3.5. Marketing Pools and Pooled Sales

A `PoolManager` opens each marketing pool for a `variety` (the same five-variety enumeration used by blocks), a `grade_class` of `EXTRA_FANCY`, `FANCY`, or `UTILITY`, and a `season` label such as 2026-2027. The triple of `variety`, `grade_class`, and `season` is unique; a duplicate pool is rejected with `ERR_UNIQUE_CONSTRAINT_VIOLATION`. A new pool is `OPEN` with every total zeroed and `pool_price_per_carton_cents` null until the first close computes it.

Sales against the pool are recorded as they occur, while the pool is `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`). Each sale names `cartons_sold` and `gross_revenue_cents`, both strictly positive, and `deduction_cents` — freight and commission — which may be zero but never negative; violations are rejected with `ERR_SALE_AMOUNT_INVALID`. Recording a sale adds the gross to `total_sales_cents`, adds the deduction to `total_sale_deductions_cents`, recomputes the estimated price, and increments the pool's `version` by one — the increment that a stale pool close will later trip over.

Pool economics reduce to a few figures. `total_deductions_cents` combines the packing charge — 650 cents for every packed carton, that is `total_packed_cartons` times 650 — with the accumulated `total_sale_deductions_cents`. The pool's net value is `total_sales_cents` minus `total_deductions_cents`. While the pool is `OPEN` or `REOPENED`, the provisional `estimated_price_cents` is that net divided by `total_packed_cartons`, rounded half-up to whole cents, but never allowed below the floor of 1,000 cents per carton; when no cartons have been packed yet, the estimate is exactly the floor. The estimate reflects only sales recorded so far and exists to price advances (§3.6).

### 3.6. Advances, Pool Close, and Settlement Reconciliation

Grower settlements are the per-grower ledger of a pool: exactly one settlement exists for each pairing of grower and pool, auto-created the first time one of the grower's lots completes a run attributed to that pool. The settlement's `attributed_cartons` aggregates `cartons_produced` over the `COMPLETED`, non-`VOIDED` runs whose lots belong to that grower and whose pool is this one. `advance_amount_cents`, `final_payment_cents`, `paid_final_cents`, and `clawback_cents` all start at zero, and the row begins `ACCRUING`. A `Grower` caller may read its own settlements; the list endpoint filters by `grower_id`, `pool_id`, and `status`.

While the pool is `OPEN`, a `PoolManager` may pay the provisional advance on an `ACCRUING` settlement — attempts in any other settlement state are rejected with `ERR_SETTLEMENT_INVALID_STATE`, and advances are not paid while the pool is `REOPENED` or `CLOSED` (`ERR_POOL_INVALID_STATE`). The settlement must have at least one attributed carton, else `ERR_NO_ATTRIBUTED_CARTONS`. The advance is sixty percent of the provisional value: `attributed_cartons` times the pool's current `estimated_price_cents` times 0.60, rounded half-up to whole cents, recorded as `advance_amount_cents` as the settlement moves `ACCRUING → ADVANCE_PAID`. Because it is priced off the floored estimate, the advance and the eventual final payment differ even on identical carton counts.

Closing a pool is the settlement event. The pool must be `OPEN` or `REOPENED` (else `ERR_POOL_INVALID_STATE`), the request must carry the OCC field `expected_pool_version` per §2.7, no `SCHEDULED` run may still reference the pool (else `ERR_POOL_HAS_OPEN_RUNS`, evaluated before the emptiness check), and `total_packed_cartons` must be at least one (else `ERR_POOL_EMPTY`). On close the final price is computed with a pinned rounding order: first the per-carton price — the pool's net value divided by `total_packed_cartons` — is rounded half-up to whole cents and stored as `pool_price_per_carton_cents`, and only then is it multiplied per grower. The rounding this introduces is not hidden: `rounding_drift_cents` records the gap between the rounded per-carton price times `total_packed_cartons` and the true net, may be negative, and is recorded on the pool but never redistributed. A committed close increments the pool's `version` by one.

The close then cascades. Every settlement of the pool in `ACCRUING` or `ADVANCE_PAID` computes its final position and moves to `SETTLED`: the settlement value is `attributed_cartons` times `pool_price_per_carton_cents`; the delta is that value minus `advance_amount_cents` and minus `paid_final_cents`; `final_payment_cents` is the delta with a floor of zero; when the delta is negative, `clawback_cents` grows by the shortfall; and `paid_final_cents` accumulates each computed `final_payment_cents`. The second hop settles the fruit itself: for each lot whose runs fed a settlement that just became `SETTLED`, if every settlement touching that lot is `SETTLED` and the lot is `PACKED`, the lot transitions `PACKED → CLOSED`.

Late-arriving sales happen, so a `CLOSED` pool — and only a `CLOSED` pool, else `ERR_POOL_INVALID_STATE` — may be reopened by a `PoolManager`. The pool moves `CLOSED → REOPENED`; the previously computed `pool_price_per_carton_cents` is retained until the next close recomputes it. The cascade runs in reverse: every `SETTLED` settlement of the pool reverts to `ADVANCE_PAID`, its final numbers now stale until the re-close, and each lot that reached `CLOSED` through this pool's settlements reverts `CLOSED → PACKED`. Re-closing a `REOPENED` pool follows the same preconditions and cascades as the first close, recomputing the price over all recorded sales; because the final-position formula subtracts `paid_final_cents`, settlements pay only the delta against what prior closes already computed.

## 4. Endpoint Definitions

Operations that create new resources — registering a grower, block, lot, room, allocation, inspection, spec, run, or pool — return `201 Created`. Operations that modify an existing resource, including state transitions, readings, releases, sales, closes, and advances, return `200 OK`, as do all reads. Authorized roles are listed below; "All roles" means every authenticated role, with `Grower` access scoped per §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/growers` | Register a grower | Admin |
| GET | `/growers/{id}` | Get a grower (Grower role: self only) | All roles |
| POST | `/growers/{id}/blocks` | Register an orchard block for a grower | Admin, ReceivingClerk |
| GET | `/growers/{id}/blocks` | List a grower's orchard blocks | All roles |
| POST | `/lots` | Receive a lot (bin delivery) tied to grower and block | Admin, ReceivingClerk |
| GET | `/lots/{lotId}` | Get a lot | All roles |
| GET | `/lots` | List lots with filters | All roles |
| POST | `/lots/{lotId}/presize` | Run the presize line over a RECEIVED lot | Admin, ReceivingClerk |
| POST | `/lots/{lotId}/divert` | Divert a whole lot to cull/juice | Admin, StorageOperator |
| POST | `/ca-rooms` | Register a CA room | Admin, StorageOperator |
| GET | `/ca-rooms/{id}` | Get a CA room | All roles |
| PUT | `/ca-rooms/{id}/schedule` | Update the room's sealing schedule / oxygen setpoint (OCC-guarded) | Admin, StorageOperator |
| POST | `/ca-rooms/{id}/seal` | Seal a FILLING room | Admin, StorageOperator |
| POST | `/ca-rooms/{id}/open` | Open a SEALED room; starts the must-empty clock | Admin, StorageOperator |
| POST | `/ca-rooms/{id}/atmosphere-readings` | Record an oxygen reading | Admin, StorageOperator |
| POST | `/ca-rooms/{id}/inspections` | Record a storage-disorder inspection | Admin, StorageOperator |
| GET | `/ca-rooms/{id}/inspections` | List a room's disorder inspections | All roles |
| POST | `/ca-rooms/{id}/allocations` | Allocate bins of a lot into a room | Admin, StorageOperator |
| POST | `/ca-rooms/{id}/select-release` | Release the top-ranked ACTIVE allocation of an OPENED room | Admin, StorageOperator |
| GET | `/allocations/{allocationId}` | Get a storage allocation | All roles |
| GET | `/allocations` | List allocations with filters | All roles |
| POST | `/allocations/{allocationId}/release` | Manually release an ACTIVE allocation | Admin, StorageOperator |
| POST | `/specs` | Create a packaging spec; supersedes the prior ACTIVE spec in the same scope | Admin, PoolManager |
| GET | `/specs/{specId}` | Get a packaging spec | All roles |
| POST | `/packing-runs` | Schedule a packing run | Admin, PackingSupervisor |
| GET | `/packing-runs/{runId}` | Get a packing run | All roles |
| GET | `/packing-runs` | List packing runs with filters | All roles |
| POST | `/packing-runs/{runId}/complete` | Complete a SCHEDULED run; records outputs and fires cascades | Admin, PackingSupervisor |
| POST | `/packing-runs/{runId}/cancel` | Cancel a SCHEDULED run | Admin, PackingSupervisor |
| POST | `/packing-runs/{runId}/void` | Void a COMPLETED run; compensates all completion effects | Admin, PackingSupervisor |
| POST | `/pools` | Open a marketing pool for variety, grade class, and season | Admin, PoolManager |
| GET | `/pools/{poolId}` | Get a pool | All roles |
| POST | `/pools/{poolId}/sales` | Record a pooled sale | Admin, PoolManager |
| POST | `/pools/{poolId}/close` | Close a pool: final price, settlements, lot closure (OCC-guarded) | Admin, PoolManager |
| POST | `/pools/{poolId}/reopen` | Reopen a CLOSED pool for late-arriving sales | Admin, PoolManager |
| GET | `/settlements/{settlementId}` | Get a grower settlement (Grower role: own only) | Admin, PoolManager, Grower |
| GET | `/settlements` | List settlements with filters | Admin, PoolManager, Grower |
| POST | `/settlements/{settlementId}/advance` | Pay the provisional advance on an ACCRUING settlement | Admin, PoolManager |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (test-driving endpoint) | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_GROWER_SCOPE_VIOLATION` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VERSION_REQUIRED` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_LOT_INVALID_STATE` | 409 |
| `ERR_ROOM_INVALID_STATE` | 409 |
| `ERR_ALLOCATION_INVALID_STATE` | 409 |
| `ERR_SPEC_INVALID_STATE` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_POOL_INVALID_STATE` | 409 |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 |
| `ERR_O2_NOT_AT_SETPOINT` | 409 |
| `ERR_OPEN_DATE_NOT_FUTURE` | 422 |
| `ERR_RUN_WINDOW_INVALID` | 422 |
| `ERR_LINE_SCHEDULE_OVERLAP` | 409 |
| `ERR_LOT_STORAGE_LIFE_EXCEEDED` | 422 |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 409 |
| `ERR_WEIGHT_BALANCE_EXCEEDED` | 422 |
| `ERR_COLOR_BELOW_SPEC` | 422 |
| `ERR_UNIQUE_CONSTRAINT_VIOLATION` | 409 |
| `ERR_RUN_WEIGHT_MISMATCH` | 422 |
| `ERR_POOL_EMPTY` | 409 |
| `ERR_POOL_HAS_OPEN_RUNS` | 409 |
| `ERR_SALE_AMOUNT_INVALID` | 422 |
| `ERR_NO_ATTRIBUTED_CARTONS` | 409 |
| `ERR_NO_RELEASABLE_ALLOCATIONS` | 409 |
| `ERR_BLOCK_GROWER_MISMATCH` | 409 |

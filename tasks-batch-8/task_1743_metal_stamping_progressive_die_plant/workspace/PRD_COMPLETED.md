# Metal Stamping & Progressive Die Plant API — Product Requirements Document

## 1. Introduction

Deep inside every automotive body program sits a stamping plant whose economics are decided by three unforgiving disciplines: how well its dies are paired to parts and presses, how faithfully it traces every kilogram of coil steel back to a mill heat lot, and how honestly it passes steel-market volatility through to customer piece prices. A progressive-die plant runs this gauntlet at stroke rates that leave no room for paperwork archaeology — a misassigned die, a coil whose heat lot is later implicated in a defect, or a misapplied steel-index adjustment each surfaces weeks later as warranty claims, line-down charges, or margin erosion.

The Metal Stamping & Progressive Die Plant API is the plant's system of record for that entire coil-to-invoice chain. It governs customer contracts indexed to published steel benchmarks; part masters and the strip layouts that define their steel content; the die fleet with its repair thresholds and the press fleet it must physically fit; coil receiving and quality disposition under heat-lot traceability; die changeovers planned against SMED targets; production runs with in-die reject sensing; outside processing loops for secondary operations; PPAP submissions and layered process audits; and the index-linked price adjustment written when an order closes. Nine operator roles act under explicit segregation-of-duties rules, and every state transition, calculation, and rejection rule in this document is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, checks, and invariants that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. The system recognizes exactly nine roles, spelled exactly as follows: `PlantAdmin`, `ProcessEngineer`, `ToolroomManager`, `SetupLead`, `ProductionPlanner`, `PressOperator`, `QualityEngineer`, `ShippingClerk`, and `CostAnalyst`. A request missing either header, or presenting a role outside this list, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint in §4 without exception — including the administrative logical-clock endpoint. A request whose role is well-formed but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

For every one of these nine roles — `PlantAdmin`, `ProcessEngineer`, `ToolroomManager`, `SetupLead`, `ProductionPlanner`, `PressOperator`, `QualityEngineer`, `ShippingClerk`, and `CostAnalyst` — the `X-User-ID` header is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, to enforce segregation of duties when a PPAP submission or a layered audit is dispositioned by someone other than the user who created the record — but it never compares `X-User-ID` to any resource's `id`, and no resource in the system is "owned" by a user in the entity sense.

Role scopes are as follows. A `PlantAdmin` administers the plant: creates customers and presses, publishes steel-index values, and drives the logical clock, with broad read access. A `ProcessEngineer` owns part master data: creates parts, authors and approves strip layouts, pairs parts with dies, and submits PPAP documentation. A `ToolroomManager` owns the die fleet and its repair lifecycle: creates dies, sends them to repair, completes repairs, and retires them. A `SetupLead` plans, starts, completes, and cancels die changeovers. A `ProductionPlanner` owns production orders — creating, releasing, completing, closing, and cancelling them — and schedules production runs. A `PressOperator` works the floor: starts, completes, and aborts runs and records in-die reject events. A `QualityEngineer` is the quality gatekeeper: approves, rejects, holds, and releases coils; reviews and dispositions PPAP submissions; and schedules and records layered audits. A `ShippingClerk` handles receiving and outside-processing logistics: receives coils, creates outside processing orders, records return shipments, and closes outside orders short. A `CostAnalyst` holds a read-only financial view over customers, parts, production orders, price adjustments, index publications, and heat-lot exposure.

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

Requests to undefined routes — including defined paths with an unsupported method — are rejected in this same envelope with `ERR_NOT_FOUND` (404).

### 2.3. Pagination

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400).

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Ties on creation timestamp are broken by creation order; the index-publications listing is ordered by creation order outright, never by `published_at`.

The `meta` object of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and Common Resource Properties

The server maintains a logical UTC clock that governs every timestamp the system records on its own initiative. Before any call to the clock-advance capability, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. A `PlantAdmin` advances the logical clock through an administrative capability that accepts a `to_iso8601` instant — any valid ISO 8601 instant is accepted, with no monotonicity enforcement. Wherever this document says "now" — recording a changeover's `actual_start` or `actual_end`, stamping an audit's `executed_at`, or selecting the applicable steel-index publication at order release or close — it means this logical clock.

Every primary resource carries a standard set of system-managed properties: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; `updated_at`, in the same format, refreshed on every mutation; and `version`, an integer managed by the server that starts at 1 at creation and increments by one on every mutation. Clients read `version` but never write it directly; it exists to support the optimistic concurrency rules of §2.8. Client-supplied datetimes (`due_date`, `scheduled_start`, `scheduled_end`, `planned_start`, `planned_end`, `scheduled_date`, `published_at`, `sensed_at`) are normalized to UTC — a value without an offset is read as UTC — and stored in the same three-fractional-digit format, with sub-millisecond precision truncated.

Three resource kinds are append-only ledger records and are deliberately exempt from the full common set: a `RejectEvent`, an `IndexPublication`, and a `PriceAdjustment` each carry only `id` and `created_at`. Neither `updated_at` nor `version` exists on these three, because they are never modified after creation.

### 2.5. Validation Pipeline and Check Ordering

When several checks could reject the same request, the server evaluates them in a single, fixed pipeline order, and the first failing check determines the response. The order is:

1. **Authentication.** Both `X-User-ID` and `X-User-Role` are present and the role is one of the nine declared roles. Every endpoint requires these headers — no endpoint, not even the clock endpoint, is callable without them. Failure: `ERR_UNAUTHENTICATED` (401).
2. **Authorization.** The presented role is permitted for the target endpoint per the role assignments of §4. Failure: `ERR_UNAUTHORIZED` (403).
3. **Existence.** Every resource referenced in the path exists, validated left to right along the path (customer, part, die, press, coil, order, run, changeover event, audit, layout, submission, outside-processing order). The first missing reference produces `ERR_NOT_FOUND` (404). Resources referenced by identifier fields in a request body are existence-checked the same way — after required-field presence validation and before all remaining field-shape and business checks — in the order the endpoint's narrative names them.
4. **State-machine precondition.** The target resource's current state permits the requested action — a run must be `RUNNING` to complete, a coil must be `APPROVED` to feed a run start, and so on through every state machine in §3. Failure: `ERR_INVALID_STATE` (409).
5. **Quality and compliance gates.** A quarantined, held, or rejected coil blocks any run start, and a die at or beyond its repair threshold blocks die-change start and run start; these gates guard run start and die-change start only — they are not evaluated at run-scheduling or changeover-planning time. Failure: `ERR_QUALITY_HOLD` (422).
6. **Segregation of duties.** The acting user must not be the creator of the PPAP submission or layered audit being dispositioned. This check guards PPAP approval, PPAP rejection, and audit recording. Failure: `ERR_SEGREGATION_OF_DUTIES` (422).
7. **Physical fit.** The press's `tonnage` is at least the die's `rated_tonnage` and the press's `bed_width_mm` is at least the die's `min_bed_width_mm`, checked at die-change start and again when a production run is scheduled. Failure: `ERR_PRESS_CAPACITY_INSUFFICIENT` (422).
8. **Material compatibility.** The coil's `material_spec` equals the part's `material_spec` and the coil's `thickness_mm` equals the part's `thickness_mm`, checked when a run is scheduled and again when it is started. Failure: `ERR_MATERIAL_MISMATCH` (422).
9. **Coil weight sufficiency.** The coil's `remaining_weight_kg` must cover the estimated consumption at run scheduling and run start, and must cover the actual consumption at run completion. Failure: `ERR_COIL_WEIGHT_EXCEEDED` (422).
10. **Changeover-window overlap.** A planned changeover's window, extended by its teardown buffer, must not overlap other changeovers or runs on the same press (§2.10). Failure: `ERR_CHANGEOVER_CONFLICT` (409).
11. **PPAP level match.** A submission's `level` must equal the part's `ppap_required_level`, and a control plan must be attached whenever the level is 2 or higher. Failure: `ERR_PPAP_LEVEL_MISMATCH` (422).
12. **Release gates.** All four order-release gates of §3.5 must hold. Failure: `ERR_RELEASE_GATE_UNMET` (422).
13. **Run-window overlap.** A new run's half-open window must not overlap another `SCHEDULED` or `RUNNING` run on the same press (§2.10). Failure: `ERR_PRESS_SCHEDULE_CONFLICT` (409).
14. **Price floor.** The index-adjusted piece price computed at order close must be at least one cent. Failure: `ERR_PRICE_FLOOR_BREACH` (422).
15. **Field shape.** Required fields are present, boolean fields carry JSON booleans, enum values are among the declared sets, datetimes are valid ISO 8601, numeric fields are positive where declared, `planned_end` is later than `planned_start`, and `scheduled_end` is later than `scheduled_start`. Failure: `ERR_INVALID_REQUEST` (400).
16. **Uniqueness.** `customer_code`, `die_code`, `press_code`, and `coil_number` are each unique across the whole plant, and `part_number` is unique within each customer. Failure: `ERR_DUPLICATE` (409).

Because the pipeline is ordered, an unauthenticated caller always receives 401 even when the path references a nonexistent resource, and a nonexistent resource referenced in the path always surfaces as 404 rather than a state or business error. The numbered list fixes the relative order of the business checks (4 through 14) against one another; field-shape validation (check 15) interleaves around them as each endpoint consumes its inputs — on action endpoints targeting an existing resource, the state-machine precondition (check 4) and segregation of duties (check 6) are evaluated before the request body is shape-validated, while on creation endpoints required-field presence, body-referenced existence, and the remaining field-shape checks all run before the business checks that consume those values. Uniqueness (check 16) is evaluated last of all.

### 2.6. Hierarchical Retrieval and Reverse-Reachability Listings

For any request whose path contains nested resource identifiers — for example, listing the runs of a particular press at `/api/presses/{id}/production-runs` — the server validates the path left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource, before any business rule is evaluated. This ordering is simply the pipeline's existence check applied per path segment.

Beyond the nested forms, the API provides filtered collection listings that make foreign-key relationships reachable in reverse. Customers can be listed filtered by `active`; parts by `customer_id`; dies by `status`; presses by `status`; part–die assignments by `part_id` or `die_id`; die changeovers by `press_id`, `from_die_id`, `to_die_id`, or `status`; production runs by `production_order_id`, `press_id`, `die_id`, `coil_id`, or `status`; layered audits by `press_id`, `escalated_from_id`, `result`, or `audit_tier`; steel coils by `status` or `heat_lot_number`; strip layouts of a part by `status`; production orders by `part_id` or `status`; runs of an order by `status`; outside-processing orders of an order by `status`; and index publications by `index_code`. All of these listings accept the `limit` and `offset` pagination parameters of §2.3. Filters match by exact equality and a value matching nothing yields an empty page, with two exceptions: an `audit_tier` filter value that is not an integer is rejected with `ERR_INVALID_REQUEST` (400), and the customers `active` filter selects active customers only for the literal value `true` (case-insensitive), selecting inactive customers for any other value.

### 2.7. Units, Precision, and Rounding Discipline

Weights are carried in kilograms to exactly 3 decimal places, rounded half up — this governs `received_weight_kg`, `remaining_weight_kg`, `steel_consumed_kg`, and the heat-lot exposure aggregate. Scrap rates are carried to exactly 6 decimal places, rounded half up, and each rate is computed as an exact rational number first and rounded once at the end. Money is carried in integer cents: piece prices and the final adjusted price are whole cents, and the steel-index material term is rounded to whole cents (round half up) before it is ever added to a base price. Changeover performance uses whole minutes per event — elapsed seconds are truncated down to whole minutes — while the rolling SMED performance average is rounded to 2 decimal places, round half up. All counts (shots, rejects, part quantities, findings) are integers.

Physical dimensions are millimeters (`thickness_mm`, `strip_width_mm`, `pitch_mm`, `bed_width_mm`, `min_bed_width_mm`), press capacity is tons (`tonnage`, `rated_tonnage`), press speed is strokes per minute (`strokes_per_min`), and steel-index values are US dollars per metric ton (`base_index_value`, `value_usd_per_ton`, `steel_index_at_release`, `applied_index_value`). In request bodies, `tonnage`, `rated_tonnage`, `bed_width_mm`, `min_bed_width_mm`, `strokes_per_min`, `total_stations`, `repair_threshold_shots`, `parts_per_strip_segment`, `base_piece_price_cents`, `ppap_required_level`, `smed_target_minutes`, and every count or quantity field (`quantity_ordered`, `shots_recorded`, `station_number`, reject-event `quantity`, `quantity_sent`, the return quantities, PPAP `level`, `audit_tier`, `findings_count`, and the expected-version fields) must be JSON integers, whereas `thickness_mm`, `strip_width_mm`, `pitch_mm`, the weight fields, `base_index_value`, `value_usd_per_ton`, and `pass_through_pct` accept any JSON number. In responses, fixed-precision decimal quantities serialize as JSON numbers, and an integral value may serialize without a decimal point.

### 2.8. Optimistic Concurrency Control on Shared Ledgers

Three write operations in this system mutate a parent entity whose state other writers may be reading; each therefore requires a non-optional expected-version field in its request body, carrying the value of the parent's `version` that the client last observed. If the parent entity's current `version` no longer matches the supplied value — because another writer has legitimately advanced it since the client last read the resource — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and nothing is written.

- Approving a strip layout requires `expected_part_version`, matched against the part's current `version`. This is the serialization point for layout supersession: if another writer has just approved a competing layout revision for the same part — which legitimately superseded the prior approved layout and advanced the part's version — the current writer's view of the part is stale and the approval is rejected.
- Completing a production run requires `expected_coil_version`, matched against the coil's current `version`. This guards the conserved coil ledger: if another writer has just completed a different run on the same coil — which legitimately decremented `remaining_weight_kg` and advanced the coil's version — the completing run's consumption decision rests on a stale view of the ledger and is rejected. The completing run's own state is validly `RUNNING`; only the coil version check rejects the write.
- Releasing a production order requires `expected_order_version`, matched against the order's current `version`; a stale view of the order at release time is likewise rejected with `ERR_STALE_VERSION` (HTTP 412).

A missing or non-integer expected-version field is rejected with `ERR_INVALID_REQUEST` (400); only a well-formed integer that no longer matches draws `ERR_STALE_VERSION` (412). Within the §2.5 pipeline the version match is evaluated after the target resource's state-machine precondition and after the expected-version field's own shape validation, and before the remaining business gates — except at run completion, where §3.7's pinned guard order places it after the zero-shots and reject-count checks.

No endpoint other than these three accepts a version field.

### 2.9. The Conserved Coil Ledger and Heat-Lot Traceability

A steel coil's weight is a conserved ledger quantity. At receipt, `remaining_weight_kg` is initialized exactly equal to `received_weight_kg`; thereafter the only write that ever decrements it is the successful completion of a production run, which subtracts that run's `steel_consumed_kg` (§3.7). The ledger never goes negative — a completion that would drive it below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED` — and when a completion lands it on exactly zero, the coil transitions itself from `APPROVED` to `DEPLETED`. Aborting a run never decrements the ledger: steel partially consumed by an aborted run is scrap-in-place and remains inside the coil's remaining weight.

Every coil also carries the mill's `heat_lot_number`, and that identifier is the plant's traceability spine. When a tier-3 layered audit fails, every coil still `APPROVED` that shares an implicated heat lot is quarantined as a group (§3.9), and the exposure read described in §3.4 lets quality and cost staff quantify a suspect lot before or after such an event.

### 2.10. Press Time Discipline: Overlaps and Teardown Buffers

A press executes at most one run at a time, and its calendar is governed by two overlap rules. For production runs, the window from `scheduled_start` to `scheduled_end` is treated as half-open: a new run's window must not overlap any existing `SCHEDULED` or `RUNNING` run on the same press, though back-to-back scheduling — one run's `scheduled_start` exactly equal to the previous run's `scheduled_end` — is allowed. A violation is rejected with `ERR_PRESS_SCHEDULE_CONFLICT` (409).

Changeovers carry an additional teardown allowance. A new die changeover's occupancy runs from its `planned_start` to thirty minutes after its `planned_end`, and that extended window must not overlap the likewise-extended window (its own `planned_start` to thirty minutes after its own `planned_end`) of any `PLANNED` or `IN_PROGRESS` changeover on the same press, nor the window of any `SCHEDULED` or `RUNNING` production run on that press; every window comparison treats both windows as half-open, so windows that merely touch at an endpoint do not conflict. A violation is rejected with `ERR_CHANGEOVER_CONFLICT` (409). Independently of planning, at most one changeover per press may be `IN_PROGRESS` at any moment, enforced at start time.

A press's own availability is tracked by its `status`: `IDLE` when free, `IN_SETUP` while a changeover is underway, and `RUNNING` while a production run executes on it. Every press begins life `IDLE`.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding and Steel-Index Publications

Commercial life begins when a `PlantAdmin` registers a customer. The record captures the customer's legal `name`, a plant-wide unique `customer_code`, the `steel_index_basis` naming which published benchmark the customer's price adjustments track — one of `CRU_HRC`, `CRU_CRC`, or `LME_STEEL_SCRAP` — and the `base_index_value`, the index value in US dollars per metric ton pinned at contract signing, from which all later price adjustments are computed as deltas. The `base_index_value` must be non-negative. The `pass_through_pct` records the fraction of index movement passed through to the piece price, expressed between 0 and 1 inclusive: 0 insulates the customer entirely, 1 passes every dollar of movement through. The `active` flag defaults to true; an inactive customer cannot receive new production orders, a rule enforced at order release (§3.5). Registering a duplicate `customer_code` is rejected with `ERR_DUPLICATE`.

Steel-index publications are the raw material of repricing. A `PlantAdmin` publishes each reading as an `IndexPublication` carrying its `index_code` (again one of `CRU_HRC`, `CRU_CRC`, or `LME_STEEL_SCRAP`), the `published_at` timestamp, and the `value_usd_per_ton`, which must be non-negative. These records are append-only. Whenever the system must select "the current index value" for a customer's basis, it takes the publication for that `index_code` with the latest `published_at` at or before the reference instant; if several publications share that same `published_at`, the tie is broken by earliest `created_at`, and if no publication for the `index_code` stands at or before the reference instant, the selection yields no value (null).

### 3.2. Part Master Data and Strip Layout Engineering

A `ProcessEngineer` registers each stampable part under its owning customer by supplying the `customer_id`, the customer-facing `part_number` (unique within that customer, with duplicates rejected `ERR_DUPLICATE`), the `material_spec` describing the steel grade (for example HSLA 340), the `thickness_mm`, the engineering `net_weight_kg` of the finished part, the contractual `base_piece_price_cents` before any steel-index adjustment, and the `ppap_required_level`, an integer from 1 to 5. The `thickness_mm` must be greater than zero, the `net_weight_kg` non-negative, and the `base_piece_price_cents` an integer of at least 1. The part's `steel_content_kg` — the kilograms of steel consumed per good part — is computed, not entered: it reads 0 until a strip layout for the part reaches `APPROVED`, and from then on it mirrors that layout's gross weight per part.

The strip layout is the process engineer's geometric definition of how a part nests into coil strip. Creating one takes the `part_id`, a `revision` code, the `strip_width_mm` of coil consumed, the `pitch_mm` progression per stroke, the `parts_per_strip_segment` produced per pitch advance, and the `gross_weight_per_part_kg` including skeleton scrap. The `strip_width_mm`, `pitch_mm`, and `gross_weight_per_part_kg` must each be greater than zero, and `parts_per_strip_segment` an integer of at least 1. A layout's `status` walks a short lifecycle — `DRAFT`, then `APPROVED`, then `SUPERSEDED` — and approval is where the geometry becomes contract. Approving a layout requires it to be `DRAFT` (any other state is `ERR_INVALID_STATE`) and requires the request to carry `expected_part_version` per §2.8. When approval succeeds, three things happen together: the part's `steel_content_kg` is synced to the approved layout's `gross_weight_per_part_kg`; any previously `APPROVED` layout for the same part becomes `SUPERSEDED` (a system-driven transition that refreshes its `updated_at`), so that at most one layout per part is ever `APPROVED`; and the part's `version` increments with its `updated_at` refreshed. It is exactly that version increment which makes the OCC check bite: a writer who read the part before a competing approval went through, and who now tries to approve their own revision with the old `expected_part_version`, is rejected with `ERR_STALE_VERSION` (412) instead of silently double-superseding. The approved layout's geometry also anchors scrap accounting: the standard scrap rate defined in §3.7 is read from whichever layout held `APPROVED` status at the moment a run started.

### 3.3. Toolroom Operations: Dies, Presses, and Part–Die Pairing

The toolroom fleet is registered by a `ToolroomManager`. A die record carries a plant-wide unique `die_code`; a `die_type` of either `PROGRESSIVE` or `TRANSFER`; the `total_stations` count, at least 1; the `rated_tonnage` naming the minimum press tonnage the die needs; the `min_bed_width_mm` naming the minimum press bed width it bolts onto; and the `repair_threshold_shots` policy: when shots since the last completed repair reach this value, the die must go to repair before it is scheduled again. A die's `status` cycles through `AVAILABLE`, `ASSIGNED`, `IN_REPAIR`, and the terminal `RETIRED`, starting at `AVAILABLE`. Two counters age the die: `total_shots_lifetime`, the cumulative strokes across every production run that ever used it, and `shots_since_repair`, the strokes since the last completed repair — both start at 0. The `rated_tonnage`, `min_bed_width_mm`, and `repair_threshold_shots` are each integers of at least 1.

Presses are registered by a `PlantAdmin` with a unique `press_code`, a `tonnage`, a `bed_width_mm`, and a rated `strokes_per_min` — each an integer of at least 1; the press's `status` starts `IDLE` and moves among `IDLE`, `IN_SETUP`, and `RUNNING` as changeovers and runs come and go (§3.6, §3.7).

Pairing a part to a die is an explicit engineering act: a `ProcessEngineer` creates a part–die assignment referencing the `part_id` and the `die_id`. The assignment's `qualified` flag starts false and flips to true only when a PPAP submission for the part is approved (§3.5) — this is the PPAP gate that order release later inspects. Assignments disappear in exactly one way: retiring a die deletes every assignment that references it.

The die repair cycle enforces the threshold policy. A `ToolroomManager` may send a die to repair from either `AVAILABLE` or `ASSIGNED`, but only once its `shots_since_repair` has reached or exceeded its `repair_threshold_shots`; attempting repair earlier violates the transition's precondition and is rejected with `ERR_INVALID_STATE`. Pulling a die to repair has teeth: every `SCHEDULED` production run referencing that die is aborted in the same motion. These repair-pull aborts do not trigger the automatic order reversion of §3.5: an `IN_PROGRESS` order left with no `SCHEDULED` or `RUNNING` runs by a repair pull stays `IN_PROGRESS`. Completing the repair returns the die from `IN_REPAIR` to `AVAILABLE` and resets `shots_since_repair` to 0. Retirement is allowed only from `AVAILABLE` and only while no `SCHEDULED` or `RUNNING` production run references the die; retiring moves the die to the terminal `RETIRED` state and deletes all of its part–die assignments. Symmetrically, the threshold policy also blocks the other direction: a die that is at or beyond its repair threshold cannot be scheduled into new work — starting a changeover with it or running against it is rejected with `ERR_QUALITY_HOLD` (§3.6, §3.7).

### 3.4. Coil Receiving, Disposition, and the Weight Ledger

Steel arrives by the coil. A `ShippingClerk` receives each coil with its plant-wide unique `coil_number`, the mill `heat_lot_number` that anchors traceability, the `material_spec`, the `thickness_mm`, and the `received_weight_kg` as weighed at receipt. The `thickness_mm` and `received_weight_kg` must each be greater than zero, and the received weight is rounded to 3 decimal places half up at receipt. The system immediately sets `remaining_weight_kg` equal to `received_weight_kg`, and the coil enters its disposition lifecycle in `RECEIVED`. From there a `QualityEngineer` dispositions it: approval moves `RECEIVED` to `APPROVED`; rejection moves `RECEIVED` to the terminal `REJECTED`. An approved coil can be put on hold — `APPROVED` to `ON_HOLD` — and later released back, `ON_HOLD` to `APPROVED`. Holding a coil deliberately does not abort the `SCHEDULED` runs that already reference it; instead the block is enforced at start time, when attempting to start a run against a held coil is rejected `ERR_QUALITY_HOLD`. The remaining states arrive by system action rather than operator action: a coil becomes `QUARANTINED` only through the heat-lot cascade of §3.9, and `APPROVED` becomes `DEPLETED` automatically when a run completion lands `remaining_weight_kg` on exactly zero. `REJECTED` and `DEPLETED` are terminal.

Only `APPROVED` coils may feed production. Starting a run against a coil that is `QUARANTINED`, `ON_HOLD`, or `REJECTED` draws `ERR_QUALITY_HOLD` (422); a coil in any other non-approved disposition (for example still `RECEIVED`) fails the state precondition with `ERR_INVALID_STATE` (409). Material compatibility is enforced twice — at scheduling and at start: the coil's `material_spec` must equal the part's `material_spec` and the coil's `thickness_mm` must equal the part's `thickness_mm`, else `ERR_MATERIAL_MISMATCH` (422).

For heat-lot situational awareness, the API offers a computed exposure read for any heat lot number, available to `PlantAdmin`, `QualityEngineer`, and `CostAnalyst`. It reports the exposure in kilograms: the sum of `remaining_weight_kg` over every coil bearing that `heat_lot_number` whose `status` is `APPROVED`, `ON_HOLD`, or `QUARANTINED`, expressed to 3 decimal places rounded half up. Alongside the tonnage it reports the affected orders: the distinct production orders served by any production run referencing a coil of that heat lot, where the run's `status` is `SCHEDULED`, `RUNNING`, or `COMPLETED`. The read returns `heat_lot_number`, `exposure_kg`, and `affected_order_ids` — the distinct order ids, sorted ascending; a heat lot with no matching coils reports `exposure_kg` 0 and an empty `affected_order_ids`.

### 3.5. PPAP Review and Production Order Release

Before a part may be released to production, its production part approval must clear quality review. A `ProcessEngineer` opens the cycle by submitting a PPAP package for the `part_id` at a declared `level` with a `control_plan_attached` flag. Two submission rules are checked: the submitted `level` must equal the part's `ppap_required_level`, and whenever the level is 2 or higher a control plan must be attached — a violation of either is `ERR_PPAP_LEVEL_MISMATCH` (422). The submission's `submission_revision` starts at 1 and its `status` starts `SUBMITTED`.

A `QualityEngineer` then begins review, moving `SUBMITTED` to `UNDER_REVIEW`, and from `UNDER_REVIEW` either approves or rejects. Segregation of duties applies to both dispositions: the acting quality engineer must not be the same user who created the submission, or the action is rejected with `ERR_SEGREGATION_OF_DUTIES` (422). Approval moves the submission to the terminal `APPROVED` state and flips every part–die assignment for the part to `qualified` true — this is the moment the PPAP gate opens. Rejection moves it to `REJECTED` and requires a `rejection_reason` to be supplied. A rejected package is final for that revision; the team resubmits by creating a new submission for the same part, which is accepted only while the part's previous submission sits in `REJECTED`, and the new submission's `submission_revision` is set to the previous maximum revision plus one, restarting the cycle at `SUBMITTED`. The resubmission precondition is evaluated after the two level rules above, and submitting while the part's previous submission is not `REJECTED` is rejected with `ERR_INVALID_STATE` (409).

With quality groundwork laid, a `ProductionPlanner` creates a production order with the `part_id` to stamp, the `quantity_ordered` (at least 1), and the contractual `due_date`. The planner may optionally declare the order's `pricing_variant`; when omitted it defaults to `RELEASE_LOCKED`, the alternative being `SHIPMENT_SPOT`, and the choice governs which index reading reprices the order at close (§3.10). A new order is `OPEN`, with `quantity_produced_good` and `quantity_scrapped` both 0.

Release moves the order `OPEN` to `RELEASED` and is gated four ways: the order must currently be `OPEN` (otherwise `ERR_INVALID_STATE`); the owning customer must be `active`; at least one part–die assignment for the part must exist with `qualified` true; an `APPROVED` strip layout must exist for the part; and a PPAP submission for the part must stand `APPROVED`. Any unmet gate is rejected with `ERR_RELEASE_GATE_UNMET` (422). The release request must also carry `expected_order_version` per §2.8, and a stale order view is rejected `ERR_STALE_VERSION` (412). On successful release the server captures `steel_index_at_release`: the latest applicable index value for the customer's `steel_index_basis` per the selection rule of §3.1, evaluated against the logical clock at the moment of release. The field reads null until release, and when the selection yields no value at release time it is captured as null. The order's `version` increments and `updated_at` refreshes.

An order can be cancelled from `OPEN` or `RELEASED` — from any other state the attempt is `ERR_INVALID_STATE` — provided no production run for the order is currently `RUNNING`; cancelling while a run is `RUNNING` is likewise rejected with `ERR_INVALID_STATE` (409). Cancellation moves it to the terminal `CANCELLED` and aborts every `SCHEDULED` run belonging to the order. The full order lifecycle is `OPEN`, `RELEASED`, `IN_PROGRESS`, `COMPLETED`, `CLOSED`, and `CANCELLED`; the middle transitions are driven by run activity (§3.7) and close-out (§3.10), and an `IN_PROGRESS` order that loses all active runs to an operator abort or the heat-lot quarantine cascade — every one aborted, none left `SCHEDULED` or `RUNNING` — reverts automatically to `RELEASED` (the die-repair pull of §3.3 is the one abort path that does not revert the order).

### 3.6. Die Changeovers and SMED Performance

Changeovers are the plant's deliberate answer to setup waste, and each is tracked as a die change event. A `SetupLead` plans one by naming the `press_id`, the `from_die_id` of the die being removed (null when the press has no die installed — an initial setup), the `to_die_id` being installed, the `planned_start` and `planned_end` instants (the end must be later than the start, else `ERR_INVALID_REQUEST`), and the `smed_target_minutes` budget for the change, a non-negative integer. A planned event starts in `PLANNED` and is subject at creation time to the press-calendar rule of §2.10: its window, extended thirty minutes past `planned_end` for teardown, must not overlap any other `PLANNED` or `IN_PROGRESS` changeover or any `SCHEDULED` or `RUNNING` run on the same press, on pain of `ERR_CHANGEOVER_CONFLICT`. A plan that is no longer wanted can be cancelled, moving `PLANNED` to the terminal `CANCELLED`.

Starting the changeover moves it `PLANNED` to `IN_PROGRESS` and is the most heavily guarded transition in the toolroom. The event must be `PLANNED`; the press must be `IDLE` or `RUNNING`; no other changeover may already be `IN_PROGRESS` on that press; the incoming die must be `AVAILABLE` and below its repair threshold — a die whose `shots_since_repair` has reached or exceeded its `repair_threshold_shots` is rejected with `ERR_QUALITY_HOLD`; and the press must physically fit the die, `tonnage` at least the die's `rated_tonnage` and `bed_width_mm` at least the die's `min_bed_width_mm`, else `ERR_PRESS_CAPACITY_INSUFFICIENT`. On a successful start, three side effects land together: the press moves to `IN_SETUP`, the incoming die moves `AVAILABLE` to `ASSIGNED` with its `version` incremented and `updated_at` refreshed, and the event's `actual_start` is stamped with the current logical time. A run already underway on the press is not disturbed.

Completing the changeover moves `IN_PROGRESS` to the terminal `COMPLETED`. The press returns to `IDLE`; the removed die, when `from_die_id` was not null and the die still stands `ASSIGNED`, moves back to `AVAILABLE` with its `version` incremented; and the event's `actual_end` is stamped. Completion also computes `variance_minutes`: the elapsed time between `actual_start` and `actual_end`, truncated down to a whole number of minutes, minus the `smed_target_minutes`. A negative variance means the crew beat its target.

SMED performance is tracked per press as a computed read available to `PlantAdmin`, `SetupLead`, and `ProductionPlanner`. It reports the arithmetic mean of the per-event `variance_minutes` over the most recent `COMPLETED` changeovers for that press, taking the newest N events where N is the smaller of 10 and the number of `COMPLETED` events the press has, selected by `actual_end` descending with ties broken by earliest `created_at`, and rounding the mean to 2 decimal places half up. Note the order of operations: each event's duration is truncated to whole minutes first, and the rolling figure averages those truncated integers — it is not a truncation of the average interval. The read returns `press_id`, `events_considered` (the number of events actually averaged), and `average_variance_minutes`; a press with no `COMPLETED` changeovers reports `events_considered` 0 and `average_variance_minutes` 0.

### 3.7. Production Runs: Scheduling, Sensing, and Settlement

A `ProductionPlanner` schedules a run by naming the `production_order_id` it serves, the `press_id`, the `die_id`, and the `coil_id` it will consume — the coil reference is the heat-lot link that traceability later depends on — together with `scheduled_start` and `scheduled_end` (the end must be later than the start). The new run is `SCHEDULED`, with `shots_recorded`, `good_count`, and `reject_count` all 0. Scheduling is checked four ways, per the pipeline of §2.5: the press must physically fit the die (`ERR_PRESS_CAPACITY_INSUFFICIENT`); the coil and part must be materially compatible (`ERR_MATERIAL_MISMATCH`); the coil's `remaining_weight_kg` must cover the run's estimated steel consumption — the planned good-part quantity multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up, where the planned good-part quantity is the order's `quantity_ordered` minus its `quantity_produced_good` when that difference is positive and the full `quantity_ordered` otherwise — else `ERR_COIL_WEIGHT_EXCEEDED`; and the run's half-open window must not collide with another `SCHEDULED` or `RUNNING` run on the press (`ERR_PRESS_SCHEDULE_CONFLICT`). Scheduling consults neither the die's repair threshold nor the coil's disposition; both gate the run's start instead.

A `PressOperator` starts the run, moving `SCHEDULED` to `RUNNING`. The run must be `SCHEDULED`; its order must be `RELEASED` or `IN_PROGRESS`; the press must be `IDLE`; the die must be `ASSIGNED` — that is, installed on the press through a completed changeover; the coil must be `APPROVED` under the disposition rules of §3.4; material compatibility is verified again (`ERR_MATERIAL_MISMATCH`); and coil sufficiency is verified again against the same estimate (`ERR_COIL_WEIGHT_EXCEEDED`). A die at or beyond its repair threshold blocks the start with `ERR_QUALITY_HOLD`, as does a coil that is `QUARANTINED`, `ON_HOLD`, or `REJECTED`. When the start succeeds, the press moves to `RUNNING`, and an order that was `RELEASED` advances to `IN_PROGRESS` with its `version` incremented and `updated_at` refreshed. The start also computes and stores the run's engineering-standard scrap rate from whichever strip layout stands `APPROVED` for the part at that moment, so the rate is visible on the run while it is `RUNNING`.

While the run is `RUNNING`, in-die sensing feeds it. The operator records each reject event with the `station_number` where it fired (an integer of at least 1), the `sensor_code` — one of `MISFEED`, `SHORT_FEED`, `PART_EJECT_FAIL`, `DOUBLE_BLANK`, or `SLUG_DETECT` — the `quantity` of rejected parts in the event (at least 1), and the `sensed_at` timestamp. Each event belongs to exactly one run via its `production_run_id`, and the run's `reject_count` is always the sum of the `quantity` values of its own reject events — there is no cross-run leakage. Recording a reject event against a run that is not `RUNNING` is a state violation, `ERR_INVALID_STATE`.

Completion is the settlement event. The operator completes the run with the final `shots_recorded` and an `expected_coil_version` per §2.8. The `shots_recorded` must be a non-negative integer; a negative value is `ERR_INVALID_REQUEST` (400). The guards are: the run must be `RUNNING` (`ERR_INVALID_STATE`); a completion reporting zero shots is rejected with `ERR_NO_SHOTS_RECORDED` (422), because the run's actual scrap rate would be undefined; if the accumulated `reject_count` exceeds `shots_recorded` — which would make the good count negative — completion is rejected with `ERR_REJECT_COUNT_EXCEEDS_SHOTS` (422); a stale coil version is rejected with `ERR_STALE_VERSION` (412); and consumption that would push the coil's ledger below zero is rejected with `ERR_COIL_WEIGHT_EXCEEDED`. On success the books settle in one motion. The run's `good_count` is its `shots_recorded` minus its total `reject_count`. Its `steel_consumed_kg` is the `good_count` multiplied by the part's `steel_content_kg`, rounded to 3 decimal places half up. The coil's `remaining_weight_kg` is decremented by exactly that amount at the same precision, the coil's `version` increments, and if the remainder is exactly zero the coil moves `APPROVED` to `DEPLETED`. The press returns to `IDLE`. The order's `quantity_produced_good` increases by the `good_count` and its `quantity_scrapped` increases by the `reject_count`. The die ages: both `total_shots_lifetime` and `shots_since_repair` increase by the run's `shots_recorded`.

Two scrap-rate measures accompany settlement, one per accounting convention. The engineering-standard scrap rate is the layout's `gross_weight_per_part_kg` minus the part's `net_weight_kg`, divided by the `gross_weight_per_part_kg` — it is geometry, independent of sensed rejects. It is first computed at run start from the layout then `APPROVED`, and recomputed at completion from the part's then-current `steel_content_kg` — which mirrors the layout `APPROVED` at completion time — and it is the completion-time value that persists on the completed run. The sensed-actual scrap rate is the run's `reject_count` divided by its `shots_recorded`, produced only at completion. The scrap variance is the rounded actual rate minus the rounded standard rate, itself rounded to 6 decimal places half up. Both rates are computed as exact rational values and rounded once, at the end, to 6 decimal places half up; the actual rate and the variance remain null until the run completes, and no per-order scrap aggregate is computed.

Abandonment has two shapes. Aborting a `RUNNING` run — whether by operator action or by a system cascade such as the die-repair pull or the heat-lot quarantine — returns the press to `IDLE`, preserves the run's counters as they stand (`good_count` is written only by a completion, so an aborted run's `good_count` remains 0), and deliberately does not decrement the coil for steel consumed up to that point (scrap-in-place, per §2.9); if no other run of the same order then remains `SCHEDULED` or `RUNNING`, the order reverts from `IN_PROGRESS` to `RELEASED`. Aborting a `SCHEDULED` run is a quieter affair with no press or coil side effects, because the run never started. Either way, `ABORTED` is terminal, as is `COMPLETED`.

### 3.8. Outside Processing and Short-Shipment Handling

Stamped parts frequently leave the plant for secondary operations. A `ShippingClerk` sends a batch out by creating an outside processing order against the `production_order_id`, naming the `operation_type` — one of `PLATING`, `HEAT_TREAT`, `E_COAT`, or `DEBURR` — and the `quantity_sent`, at least 1. The order starts `SENT`, with `quantity_returned_good` and `quantity_returned_scrap` both 0. The parent production order's status is not consulted at creation.

Returns arrive through the same clerk. Recording a return takes the `quantity_returned_good` and `quantity_returned_scrap` of the shipment — each a non-negative integer — and is accepted while the outside order is `SENT` or `PARTIAL_RETURN`. The cumulative return totals after each receipt may never exceed the `quantity_sent` — an over-shipment is rejected with `ERR_RETURN_QUANTITY_EXCEEDED` (422) — and within that bound the counters simply accumulate. A receipt that leaves cumulative returns below `quantity_sent` places the order in `PARTIAL_RETURN` (and further partial receipts keep it there); a receipt that brings cumulative returns exactly to `quantity_sent` closes it, moving it to `CLOSED` from either `SENT` or `PARTIAL_RETURN`.

When a processor cannot or will not return the full batch, the clerk closes the order short. Close-short is permitted only once the parent production order is `COMPLETED` — attempting it earlier is rejected with `ERR_ORDER_NOT_COMPLETED` (409) — and only with a written `shortage_acknowledgment` attached to the request, a non-empty string validated before the parent-completion check, so a missing or empty acknowledgment draws `ERR_INVALID_REQUEST` (400) even when the parent is not yet `COMPLETED`. The outside order moves to `CLOSED`, and the shortage — the `quantity_sent` minus the `quantity_returned_good` minus the `quantity_returned_scrap` — is added to the parent order's `quantity_scrapped`. `CLOSED` is terminal.

### 3.9. Layered Audits and the Heat-Lot Quarantine Cascade

Layered process audits verify that standards hold at every level of the plant. A `QualityEngineer` schedules an audit against a `press_id` at a declared `audit_tier`: tier 1 is the shift supervisor's check, tier 2 the plant manager's, and tier 3 corporate quality. Any other `audit_tier` value is rejected with `ERR_INVALID_REQUEST` (400). Scheduling also fixes the `scheduled_date`. The audit's `result` starts `PENDING`, its `findings_count` starts 0, and its `escalated_from_id` is null for a normally scheduled audit.

Recording the result takes the `result` — `PASS` or `FAIL` — and the `findings_count`, a non-negative integer, and stamps `executed_at` with the logical clock. The audit must be `PENDING` (else `ERR_INVALID_STATE`), and segregation of duties applies: the recording user must not be the same user who created the audit, or the recording is rejected with `ERR_SEGREGATION_OF_DUTIES`. A `FAIL` recorded with fewer than 1 finding is rejected with `ERR_AUDIT_FINDINGS_REQUIRED` (422). Both `PASS` and `FAIL` are terminal for the audit itself — but failure has a tail. When an audit at tier 1 or tier 2 fails, the system automatically creates a new layered audit for the same press at the next tier up, with `escalated_from_id` pointing back to the failed audit. The escalated audit's `scheduled_date` is stamped with the logical clock at the moment of escalation, and as a system-created record it has no creator, so segregation of duties never blocks recording its result. There is no tier above 3, so a tier-3 failure escalates differently: it detonates the heat-lot quarantine cascade.

The cascade works from the failed tier-3 audit's press outward through the traceability spine. Every steel coil whose `heat_lot_number` was consumed by runs on that press — runs in `COMPLETED` or `RUNNING` status on that press, regardless of when they ran, with no time window bounding the implication — and which still stands `APPROVED` transitions to `QUARANTINED`; the quarantine applies lot-wide, to every `APPROVED` coil sharing an implicated `heat_lot_number`, not merely the coils physically consumed on that press. From there the damage propagates through the schedule: every `SCHEDULED` production run referencing a quarantined coil is aborted; every `RUNNING` run referencing one is aborted with its `good_count` preserved; and the parent order of each aborted run, if it stood `IN_PROGRESS`, reverts to `RELEASED`. The exposure read of §3.4 reports the same heat lot's outstanding kilograms and affected orders for containment planning.

### 3.10. Order Close-Out and Index-Linked Price Adjustment

When production has satisfied the contract, a `ProductionPlanner` completes the order: the order must be `IN_PROGRESS`, its accumulated `quantity_produced_good` must be at least its `quantity_ordered`, and no run of the order may still be `RUNNING`. Completion moves it to `COMPLETED`; no per-order scrap aggregate is computed — scrap rates live on the individual runs.

Closing is the financial settlement, moving `COMPLETED` to the terminal `CLOSED`. Two preconditions bind it: the order must be `COMPLETED`, and every outside processing order belonging to it must already be `CLOSED` — an order cannot be financially settled while parts remain in a processor's hands. At close the system writes a `PriceAdjustment`, an append-only record carrying the `production_order_id`, the `variant_applied`, a snapshot of the customer's `base_index_value`, the `applied_index_value` the variant selected, and the resulting `adjusted_piece_price_cents`. The close responds with the updated order object; the written adjustment is read back through the order's price-adjustment listing.

The adjustment formula's evaluation order is pinned, and each step feeds the next. First, the index delta is the `applied_index_value` minus the customer's `base_index_value`, in US dollars per metric ton. Second, the pass-through is the index delta multiplied by the customer's `pass_through_pct`; this value may be negative when the market has fallen. Third, the material term in cents is the pass-through amount multiplied by the part's `steel_content_kg`, multiplied by 100, and divided by 1,000 — converting dollars per metric ton into cents per part through the part's steel content. Fourth, the material term is rounded to whole cents, round half up, before any addition takes place; this per-part rounding happens first, deliberately. Fifth, the adjusted piece price is the part's `base_piece_price_cents` plus the rounded material term, yielding integer cents. Finally the floor is enforced: the adjusted piece price must come to at least 1 cent, and if it would not, the close is rejected with `ERR_PRICE_FLOOR_BREACH` (422) and no adjustment is written.

Which index value fills `applied_index_value` depends on the order's `pricing_variant`. Under `RELEASE_LOCKED` — the default — the adjustment applies the value captured at release in `steel_index_at_release`; spot movement after release has no effect on the order's price. Under `SHIPMENT_SPOT`, the adjustment applies the latest index publication for the customer's `steel_index_basis` with a `published_at` at or before the close timestamp, selected by latest `published_at` with ties broken by earliest `created_at`; identical order data yields a different adjusted price whenever the index moved between release and close. If the variant's selection yields no value — no qualifying publication at release for `RELEASE_LOCKED`, or none at or before close for `SHIPMENT_SPOT` — the `applied_index_value` falls back to the customer's `base_index_value`, making the index delta zero. The adjustments written for an order are listed through the order's price-adjustment listing, available to `PlantAdmin`, `ProductionPlanner`, and `CostAnalyst`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/api` prefix. Operations that create a new resource return `201 Created`; operations that modify an existing resource or invoke an action on it return `200 OK`. Request bodies, response payloads, OCC fields, and side effects are specified by the narratives of §2 and §3; this table is the routing and authorization index.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the server's logical UTC clock | PlantAdmin |
| POST | `/api/index-publications` | Publish a steel index value | PlantAdmin |
| GET | `/api/index-publications` | List index publications | PlantAdmin, ProductionPlanner, CostAnalyst |
| POST | `/api/customers` | Create a customer | PlantAdmin |
| GET | `/api/customers` | List customers | PlantAdmin, ProductionPlanner, CostAnalyst |
| GET | `/api/customers/{id}` | Get a customer | PlantAdmin, ProductionPlanner, CostAnalyst |
| GET | `/api/customers/{id}/parts` | List parts of a customer | PlantAdmin, ProductionPlanner, CostAnalyst |
| POST | `/api/parts` | Create a part | ProcessEngineer |
| GET | `/api/parts` | List parts | PlantAdmin, ProcessEngineer, ProductionPlanner, QualityEngineer, CostAnalyst |
| GET | `/api/parts/{id}` | Get a part | PlantAdmin, ProcessEngineer, ProductionPlanner, QualityEngineer, CostAnalyst |
| GET | `/api/parts/{id}/strip-layouts` | List strip layouts for a part | PlantAdmin, ProcessEngineer, QualityEngineer |
| GET | `/api/parts/{id}/ppap-submissions` | List PPAP submissions for a part | PlantAdmin, ProcessEngineer, QualityEngineer |
| GET | `/api/parts/{id}/die-assignments` | List die assignments for a part | PlantAdmin, ProcessEngineer, ProductionPlanner |
| POST | `/api/dies` | Create a die | ToolroomManager |
| GET | `/api/dies` | List dies | PlantAdmin, ToolroomManager, SetupLead, ProductionPlanner |
| GET | `/api/dies/{id}` | Get a die | PlantAdmin, ToolroomManager, SetupLead, ProductionPlanner |
| POST | `/api/dies/{id}/send-to-repair` | Send a die to repair; aborts its SCHEDULED runs | ToolroomManager |
| POST | `/api/dies/{id}/complete-repair` | Complete a die repair; resets shots since repair | ToolroomManager |
| POST | `/api/dies/{id}/retire` | Retire a die; deletes its part–die assignments | ToolroomManager |
| POST | `/api/presses` | Create a press | PlantAdmin |
| GET | `/api/presses` | List presses | PlantAdmin, ProductionPlanner, SetupLead, PressOperator, QualityEngineer |
| GET | `/api/presses/{id}` | Get a press | PlantAdmin, ProductionPlanner, SetupLead, PressOperator, QualityEngineer |
| GET | `/api/presses/{id}/die-change-events` | List changeovers for a press | PlantAdmin, ProductionPlanner, SetupLead |
| GET | `/api/presses/{id}/production-runs` | List production runs for a press | PlantAdmin, ProductionPlanner, PressOperator |
| GET | `/api/presses/{id}/layered-audits` | List layered audits for a press | PlantAdmin, QualityEngineer |
| GET | `/api/presses/{id}/smed-performance` | Rolling average SMED variance for a press | PlantAdmin, SetupLead, ProductionPlanner |
| POST | `/api/part-die-assignments` | Pair a part with a die | ProcessEngineer |
| GET | `/api/part-die-assignments` | List part–die assignments | PlantAdmin, ProcessEngineer, ProductionPlanner |
| GET | `/api/part-die-assignments/{id}` | Get a part–die assignment | PlantAdmin, ProcessEngineer, ProductionPlanner |
| GET | `/api/die-change-events` | List changeovers (filtered) | PlantAdmin, SetupLead, ProductionPlanner |
| GET | `/api/production-runs` | List production runs (filtered) | PlantAdmin, ProductionPlanner, PressOperator, QualityEngineer |
| GET | `/api/layered-audits` | List layered audits (filtered) | PlantAdmin, QualityEngineer |
| POST | `/api/steel-coils` | Receive a steel coil | ShippingClerk |
| GET | `/api/steel-coils` | List steel coils | PlantAdmin, ShippingClerk, QualityEngineer, ProductionPlanner |
| GET | `/api/steel-coils/{id}` | Get a steel coil | PlantAdmin, ShippingClerk, QualityEngineer, ProductionPlanner, PressOperator |
| POST | `/api/steel-coils/{id}/approve` | Approve a received coil for production | QualityEngineer |
| POST | `/api/steel-coils/{id}/reject` | Reject a received coil | QualityEngineer |
| POST | `/api/steel-coils/{id}/hold` | Place an approved coil on hold | QualityEngineer |
| POST | `/api/steel-coils/{id}/release-hold` | Release a coil hold | QualityEngineer |
| GET | `/api/heat-lots/{heat_lot_number}/exposure` | Exposure kilograms and affected orders for a heat lot | PlantAdmin, QualityEngineer, CostAnalyst |
| POST | `/api/strip-layouts` | Create a strip layout for a part | ProcessEngineer |
| GET | `/api/strip-layouts/{id}` | Get a strip layout | PlantAdmin, ProcessEngineer, QualityEngineer |
| POST | `/api/strip-layouts/{id}/approve` | Approve a layout; supersedes the prior approved layout; syncs part steel content | ProcessEngineer |
| POST | `/api/production-orders` | Create a production order | ProductionPlanner |
| GET | `/api/production-orders` | List production orders | PlantAdmin, ProductionPlanner, CostAnalyst, PressOperator |
| GET | `/api/production-orders/{id}` | Get a production order | PlantAdmin, ProductionPlanner, CostAnalyst, PressOperator |
| POST | `/api/production-orders/{id}/release` | Release an order; captures the steel index at release | ProductionPlanner |
| POST | `/api/production-orders/{id}/complete` | Complete an order once the good quantity is reached | ProductionPlanner |
| POST | `/api/production-orders/{id}/close` | Close an order; writes the price adjustment | ProductionPlanner |
| POST | `/api/production-orders/{id}/cancel` | Cancel an order; aborts its SCHEDULED runs | ProductionPlanner |
| GET | `/api/production-orders/{id}/production-runs` | List production runs for an order | PlantAdmin, ProductionPlanner, PressOperator |
| GET | `/api/production-orders/{id}/price-adjustments` | List price adjustments written for an order | PlantAdmin, ProductionPlanner, CostAnalyst |
| GET | `/api/production-orders/{id}/outside-processing-orders` | List outside processing orders for an order | PlantAdmin, ProductionPlanner, ShippingClerk |
| POST | `/api/die-change-events` | Plan a die changeover on a press | SetupLead |
| GET | `/api/die-change-events/{id}` | Get a changeover | PlantAdmin, SetupLead, ProductionPlanner |
| POST | `/api/die-change-events/{id}/start` | Begin a changeover; installs the incoming die | SetupLead |
| POST | `/api/die-change-events/{id}/complete` | Complete a changeover; computes SMED variance | SetupLead |
| POST | `/api/die-change-events/{id}/cancel` | Cancel a planned changeover | SetupLead |
| POST | `/api/production-runs` | Schedule a production run | ProductionPlanner |
| GET | `/api/production-runs/{id}` | Get a production run | PlantAdmin, ProductionPlanner, PressOperator, QualityEngineer |
| POST | `/api/production-runs/{id}/start` | Start a run; press RUNNING; order IN_PROGRESS | PressOperator |
| POST | `/api/production-runs/{id}/complete` | Complete a run; settles coil, order, and die ledgers | PressOperator |
| POST | `/api/production-runs/{id}/abort` | Abort a scheduled or running run | PressOperator |
| GET | `/api/production-runs/{id}/reject-events` | List reject events for a run | PlantAdmin, PressOperator, QualityEngineer |
| POST | `/api/production-runs/{id}/reject-events` | Record an in-die sensing reject event on a running run | PressOperator |
| POST | `/api/outside-processing-orders` | Send stamped parts to an outside processor | ShippingClerk |
| GET | `/api/outside-processing-orders/{id}` | Get an outside processing order | PlantAdmin, ShippingClerk, ProductionPlanner |
| POST | `/api/outside-processing-orders/{id}/receive-return` | Record a return shipment from the processor | ShippingClerk |
| POST | `/api/outside-processing-orders/{id}/close-short` | Close an outside order short of full return | ShippingClerk |
| POST | `/api/ppap-submissions` | Submit PPAP for a part | ProcessEngineer |
| GET | `/api/ppap-submissions/{id}` | Get a PPAP submission | PlantAdmin, ProcessEngineer, QualityEngineer |
| POST | `/api/ppap-submissions/{id}/begin-review` | Move a submission to UNDER_REVIEW | QualityEngineer |
| POST | `/api/ppap-submissions/{id}/approve` | Approve a PPAP submission; qualifies all part–die assignments | QualityEngineer |
| POST | `/api/ppap-submissions/{id}/reject` | Reject a PPAP submission with a reason | QualityEngineer |
| POST | `/api/layered-audits` | Schedule a layered audit on a press | QualityEngineer |
| GET | `/api/layered-audits/{id}` | Get a layered audit | PlantAdmin, QualityEngineer |
| POST | `/api/layered-audits/{id}/record` | Record an audit result; FAIL escalates to the next tier | QualityEngineer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_QUALITY_HOLD` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 422 Unprocessable Entity |
| `ERR_PRESS_CAPACITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_MATERIAL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PRESS_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_CHANGEOVER_CONFLICT` | 409 Conflict |
| `ERR_PPAP_LEVEL_MISMATCH` | 422 Unprocessable Entity |
| `ERR_RELEASE_GATE_UNMET` | 422 Unprocessable Entity |
| `ERR_COIL_WEIGHT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRICE_FLOOR_BREACH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NO_SHOTS_RECORDED` | 422 Unprocessable Entity |
| `ERR_REJECT_COUNT_EXCEEDS_SHOTS` | 422 Unprocessable Entity |
| `ERR_RETURN_QUANTITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_AUDIT_FINDINGS_REQUIRED` | 422 Unprocessable Entity |

# Cheese Plant Aging Program API — Product Requirements Document

## 1. Introduction

A Wisconsin cheese plant runs on commitments made hours, weeks, or months before their consequences become visible: milk is accepted at the receiving bay before its fate in the vat is known, vats are booked against culture and coagulant lots that may expire before the make starts, and wheels enter the aging cellar long before a grader decides whether they may be sold. This document specifies the Cheese Plant Aging Program API, mounted under the `/plant` path prefix, which governs that full arc — raw milk intake and safety acceptance, vat scheduling with variety-specific make procedures, additive lot control, yield accounting with whey-stream valorization, aging-room inventory with turn schedules, quality grading and release decisions, private-label versus branded allocation, cut-and-wrap conversion with waste accountability, and export certification.

Two disciplines cut across everything the system does. The first is segregation of duties: no cheesemaker may sign two consecutive steps of the same make, and no grader may grade a batch whose make steps they signed. The second is ledgered consistency — liters of milk committed to make sheets, additive quantities consumed and refunded, wheels resting in each room, and the plant's total aging capacity are maintained as running totals that move exactly once per business event and are repaired by explicit compensation when a make is cancelled. All temporal reasoning runs on a logical plant clock rather than wall-clock time, so that lot expiry, wheel age, and turn scheduling are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the operator's role. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A recognized role attempting an operation it is not permitted to perform is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Nine roles exist:

- `PlantAdmin` — plant administrator; owns configuration resources (the plant itself, vats, aging rooms, additive-lot receipt) and the logical clock.
- `MilkReceiver` — intake operator; records raw-milk receipts and accepts or rejects them.
- `MakePlanner` — production planner; books vats and cancels makes.
- `Cheesemaker` — licensed cheesemaker; starts makes, signs off make-procedure steps, completes makes, performs CIP cleaning, and records whey valorization; the cheesemaker's identity is tracked on step sign-offs for segregation of duties.
- `QAGrader` — quality grader; releases and recalls additive lots, grades batches, and releases graded batches; a grader must never grade a batch whose make steps that same user signed.
- `AgingRoomOperator` — aging-cellar operator; places, turns, moves, and removes wheel units, and updates room environment readings.
- `SalesPlanner` — sales and allocations planner; creates and cancels private-label and branded orders.
- `CutWrapOperator` — cut-and-wrap room operator; creates, reconciles, and voids conversion runs.
- `ComplianceOfficer` — export compliance officer; requests, issues, denies, and revokes export certificates.

For every one of these nine roles — `PlantAdmin`, `MilkReceiver`, `MakePlanner`, `Cheesemaker`, `QAGrader`, `AgingRoomOperator`, `SalesPlanner`, `CutWrapOperator`, and `ComplianceOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against a resource's `id`. The identifier is nevertheless recorded where accountability matters: each make-step sign-off appends the signer's `X-User-ID` to the make sheet's `step_signer_ids`, and each grading event stores the grader's `X-User-ID` as `grader_user_id`. Segregation-of-duties checks compare these recorded identifiers against the `X-User-ID` presented by later requests.

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

### 2.3. Pagination and List Filtering

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

Every list endpoint also accepts optional equality filters drawn from the resource's own fields. Milk intakes filter by `plant_id` and `status`; vats by `plant_id` and `status`; additive lots by `plant_id`, `kind`, and `status`; make sheets by `plant_id`, `vat_id`, `milk_intake_id`, `culture_lot_id`, `coagulant_lot_id`, and `status`; cheese batches by `plant_id`, `make_sheet_id`, `variety`, `status`, and `current_grade`; whey streams by `plant_id` and `make_sheet_id`; aging rooms by `plant_id`, `status`, and `posture`; aging units by `plant_id`, `cheese_batch_id`, `aging_room_id`, `status`, and `turns_due`; grading events by `plant_id`, `cheese_batch_id`, and `supersedes_grading_event_id`; allocation orders by `plant_id`, `cheese_batch_id`, `channel`, and `status`; cut-wrap runs by `plant_id`, `allocation_order_id`, and `status`; export certificates by `plant_id`, `cut_wrap_run_id`, and `status`. Filters combine with `limit` and `offset` on every list endpoint.

### 2.4. The Logical Plant Clock

All temporal reasoning in the system — lot expiry, wheel age, turn schedules, issuance timestamps — reads from a logical clock maintained by the server, never from wall-clock time. Before any clock call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time under any circumstance. A `PlantAdmin` advances the clock by supplying a `to_iso8601` timestamp; the call succeeds with HTTP 200 and returns the new logical time as `now` alongside `expired_lot_ids`, the identifiers of every additive lot the advance expired.

Advancing the clock triggers two maintenance sweeps. First, every additive lot currently `RELEASED` whose `expires_at` is at or earlier than the new logical time transitions to `EXPIRED` — a lot expiring exactly at the new clock reading is expired. Second, `age_days` and `turns_due` are recomputed for every aging unit currently `IN_ROOM`. The same age and turn projection is also recomputed whenever an aging unit is read, so reported ages always reflect the current logical time.

### 2.5. Common Resource Properties and Cascading Consistency

Every resource in this API — plants, milk intakes, vats, make sheets, additive lots, cheese batches, whey streams, aging rooms, aging units, grading events, allocation orders, cut-wrap runs, and export certificates — carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits set at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that increments by one on every mutation of the resource.

Cascading side effects count as mutations. Booking a make sheet bumps the vat's `version` and refreshes its `updated_at`; placing an aging unit does the same to the room. When one request touches several resources — completing a make creates a cheese batch and a whey stream, dirties the vat, and may consume the milk intake — each touched resource is updated independently and atomically with the request. Parent resources never silently drift from their children: occupancy, commitment, and capacity ledgers described in §3 are adjusted in the same operation that causes them, and compensating reversals (additive refunds, milk un-commits) apply only to non-terminal resources so that settled history is never rewritten.

### 2.6. Nested Resource Retrieval

Requests that carry several resource identifiers — whether in a hierarchical creation path such as a vat created under a plant, or as foreign-key references in a request body — are validated for existence in a strict left-to-right order: path identifiers first, in the order they appear in the URL, then body references. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource, and no later validation runs.

### 2.7. Units, Precision, and Rounding

Computed mass and percentage values stored by the system — the two yield figures, whey quantities and the valorization rate, cut-wrap input weight and reconciliation gap — are rounded half-up to exactly two decimal places and returned as JSON numbers, not strings. Grading readings (`moisture_pct`, `fat_dry_basis_pct`) are recorded to one decimal place and all grade comparisons are exact, with no rounding tolerance. Wheel counts, make-step counters, and `priority` are integers. Volumes are liters, masses are kilograms, temperatures are Celsius, and humidities are percent. For whey accounting, one liter of milk is treated as one kilogram. Age figures are whole days obtained by flooring, never by rounding up. The variety constants cited throughout §3 — make-step counts, minimum ages, wheel weights, turn intervals, recovery factors, moisture targets, and grading bands — are exact values, applied as written.

### 2.8. Optimistic Concurrency Control

Two write endpoints carry an optimistic concurrency check, and both checks are mandatory. Creating a make sheet (`POST /plant/make-sheets`) requires a non-optional `expected_vat_version` field carrying the target vat's `version` as the client last observed it. If the vat's current `version` differs — because another planner has since booked or cancelled a make on that vat, each of which advances the vat's version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is written. Placing an aging unit (`POST /plant/aging-units`) likewise requires a non-optional `expected_aging_room_version` carrying the room's last-observed `version`; a mismatch — for example because another operator has since placed or removed wheels, advancing the room's version and possibly flipping its posture — is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts a version field.

### 2.9. Validation Order

A request whose payload is malformed — an unrecognized enum value, a non-positive quantity, or a booking interval whose end is not after its start — is rejected with `ERR_INVALID_REQUEST` (HTTP 400) when the request is parsed, before any business rule runs.

When several checks could fail on one well-formed request, the server evaluates them in a fixed priority order and reports only the first failure encountered. Authentication comes first: missing or malformed `X-User-ID` or `X-User-Role` headers, or an unrecognized role, fail with `ERR_UNAUTHENTICATED`. Authorization is second: a recognized role not permitted on the endpoint fails with `ERR_UNAUTHORIZED`. Existence is third: any unresolvable identifier fails with `ERR_NOT_FOUND` in the left-to-right order of §2.6. The optimistic-concurrency check is fourth: on the two endpoints of §2.8, a stale expected version fails with `ERR_STALE_VERSION` before any state or business rule is consulted. Fifth, the target resource must be in a state that permits the requested transition, failing with `ERR_INVALID_STATE`.

The remaining rungs are business rules, evaluated in this order. Sixth, the milk safety gates on acceptance: `ERR_SCC_LIMIT` and `ERR_ANTIBIOTIC_POSITIVE`. Seventh, additive-lot usability and segregation of duties: `ERR_ADDITIVE_LOT_UNUSABLE`, `ERR_SOLE_OPERATOR`, and `ERR_STEP_SOLE_OPERATOR`. Eighth, cross-entity state gates: `ERR_MILK_NOT_ACCEPTED`, `ERR_WHEELS_UNPLACED`, `ERR_BATCH_NOT_RELEASED`, and `ERR_PLANT_NOT_EXPORT_LISTED`. Ninth, booking, quantity, and sequencing constraints: `ERR_VAT_OVERLAP`, `ERR_ADDITIVE_INSUFFICIENT`, `ERR_STEP_OUT_OF_ORDER`, `ERR_WHEELS_EXHAUSTED`, and `ERR_CERT_ALREADY_EXISTS`. Tenth, temporal rules: `ERR_AGE_MINIMUM_NOT_MET`, and lot expiry against the logical clock, which surfaces as `ERR_ADDITIVE_LOT_UNUSABLE`. Eleventh, capacity gates: `ERR_VAT_CAPACITY`, `ERR_ROOM_FULL`, `ERR_ROOM_DEVIATION`, and `ERR_ROOM_DECOMMISSIONED`. Twelfth, fiscal plausibility: `ERR_YIELD_IMPOSSIBLE`, `ERR_WASTE_NEGATIVE`, `ERR_WASTE_TOLERANCE`, and `ERR_ORDER_OVERFILL`. Thirteenth and last, the whey valorization cap: `ERR_WHEY_OVER_VALORIZED`.

### 2.10. Varieties, Channels, and Enumerations

Four cheese varieties exist, spelled exactly `CHEDDAR`, `COLBY`, `BRICK`, and `MUENSTER`; the variety pins a battery of constants (make-step counts, minimum ages, wheel weights, turn intervals, recovery factors, moisture targets, grading bands) introduced in context throughout §3. An additive lot's `kind` is either `CULTURE` or `COAGULANT`. An allocation order's `channel` is either `PRIVATE_LABEL` or `BRANDED`. A batch's `current_grade` is one of `UNGRADED`, `GRADE_A`, `GRADE_B`, `DOWNGRADE`, or `CONDEMNED`, and its `release_decision` is one of `PENDING`, `RELEASED`, or `REJECTED`. A room's `posture` is one of `AVAILABLE`, `FULL`, or `DEVIATION`. Any request value outside these sets is rejected with `ERR_INVALID_REQUEST`.

Status machines, whose transitions §3 narrates in full, use these exact state strings. A milk intake is `RECEIVED`, `ACCEPTED`, `REJECTED`, or `CONSUMED`. A vat is `IDLE`, `BOOKED`, `IN_MAKE`, `CLEANING`, or `DECOMMISSIONED`. A make sheet is `SCHEDULED`, `IN_PROGRESS`, `CURD_READY`, `COMPLETED`, or `CANCELLED`. An additive lot is `QUARANTINE`, `RELEASED`, `DEPLETED`, `EXPIRED`, or `RECALLED`. A cheese batch is `GREEN`, `AGING`, `GRADED`, `RELEASED`, `ALLOCATED`, or `CONDEMNED`. An aging room is `ACTIVE` or `DECOMMISSIONED`. An aging unit is `IN_ROOM`, `MOVED`, or `REMOVED`. An allocation order is `OPEN`, `PARTIALLY_FILLED`, `FILLED`, or `CANCELLED`. A cut-wrap run is `DRAFT`, `RECONCILED`, or `VOIDED`. An export certificate is `REQUESTED`, `ISSUED`, `DENIED`, or `REVOKED`.

## 3. Business Logic & Workflows

### 3.1. Plant Configuration: Vats, Aging Rooms, and Additive Lots

A `PlantAdmin` begins by registering the plant with its `name` and Wisconsin dairy plant `license_number`; the `export_listed` flag, which records whether the plant appears on the federal export-eligible regulatory listing, defaults to `false` when omitted, and a later plant update may flip it — each such update increments the plant's `version` by one. The plant's `total_aging_capacity_wheels` is a computed ledger, the sum of `capacity_wheels` over all of the plant's aging rooms that are not `DECOMMISSIONED`; a new plant starts at zero.

Vats come next. Each vat is created under its plant with a `code` unique per plant (such as VAT-3) and a `capacity_liters` ceiling, and is born `IDLE` with `cip_clean` set to `true`. Only an `IDLE` vat may be decommissioned — a vat with any make sheet in `SCHEDULED`, `IN_PROGRESS`, or `CURD_READY` is by construction not idle — and decommissioning moves it to terminal `DECOMMISSIONED`; any other state at decommission time fails with `ERR_INVALID_STATE`.

Aging rooms are created with a `code` unique per plant, a `capacity_wheels` ceiling in wheel positions, and initial environment readings `temp_c` and `humidity_pct`. A new room is `ACTIVE` with `wheels_present` at zero, its `posture` derived immediately, and the plant's `total_aging_capacity_wheels` increases by the new room's capacity in the same operation. An `AgingRoomOperator` may update a room's `temp_c` and `humidity_pct` readings (either or both); each update re-derives the posture and increments the room's `version` by one. Decommissioning a room requires it to be completely empty — a `wheels_present` above zero fails with `ERR_ROOM_NOT_EMPTY` — and drops the plant's total aging capacity by the room's `capacity_wheels`; a decommissioned room's `posture` is frozen and never re-derived.

Room posture follows a pinned evaluation order, because environment outranks capacity. Whenever `wheels_present`, `capacity_wheels`, or the environment readings change, posture is re-derived: first the environment band is checked, and a `temp_c` strictly below 7.0 or strictly above 13.0 Celsius, or a `humidity_pct` strictly below 80.0 or strictly above 90.0 percent, forces `DEVIATION` no matter how empty the room is — the boundary readings themselves (exactly 7.0, exactly 13.0, exactly 80.0, exactly 90.0) are in band. Only when the environment is in band does capacity apply: a room whose `wheels_present` exactly equals its `capacity_wheels` is `FULL`, and anything short of that is `AVAILABLE`.

Additive lots are received by a `PlantAdmin` declaring the `kind`, the `supplier_lot_no` (unique per plant and kind — duplicate receipts are rejected), the `expires_at` timestamp, and the `quantity_initial` received. The lot is born in `QUARANTINE` with `quantity_on_hand` set to `quantity_initial`; quantities are counted in units for cultures and milliliters for coagulants. A `QAGrader` releases a quarantined lot (`QUARANTINE` → `RELEASED`), making it eligible for makes, and may recall a lot from either `QUARANTINE` or `RELEASED`, sending it to terminal `RECALLED`. Recall does not auto-cancel make sheets that already reference the lot: such a make sheet stays `SCHEDULED` but will fail at start time with `ERR_ADDITIVE_LOT_UNUSABLE`, which is the intended cross-entity gate. Two further transitions are automatic: a `RELEASED` lot whose `quantity_on_hand` reaches zero through make-start consumption becomes `DEPLETED`, and a `DEPLETED` lot returns to `RELEASED` when a make-sheet cancellation refunds a quantity that lifts `quantity_on_hand` above zero. The clock sweep of §2.4 carries `RELEASED` lots to `EXPIRED`.

### 3.2. Milk Receiving and Safety Acceptance

A `MilkReceiver` records each tanker receipt under its plant with the external `hauler_ticket` manifest reference, the `received_at` timestamp, the `volume_liters` delivered, the lab-measured `fat_pct` (for example 3.85) and `protein_pct` (for example 3.10), the `somatic_cell_count` per milliliter, and the rapid-screen `antibiotics_detected` flag, which defaults to `false` when omitted. The intake is born `RECEIVED` with `consumed_liters` at zero.

Acceptance is a deliberate act gated by two safety rules, evaluated in this order: the `somatic_cell_count` must be no greater than 400,000 — a reading of exactly 400,000 passes, anything strictly above fails with `ERR_SCC_LIMIT` — and the antibiotic screen must be negative, with a detected result failing with `ERR_ANTIBIOTIC_POSITIVE`. Passing both moves the intake `RECEIVED` → `ACCEPTED`. Rejection moves it `RECEIVED` → `REJECTED`, which is terminal; a rejected intake is ineligible for make-sheet commitment forever after. Acceptance or rejection attempted on an intake that has already left `RECEIVED` fails with `ERR_INVALID_STATE`.

An accepted intake's remaining life is tracked through `consumed_liters`, which climbs as make sheets start against it. The moment `consumed_liters` exactly equals `volume_liters` after a commit, the intake transitions automatically from `ACCEPTED` to terminal `CONSUMED`.

### 3.3. Booking the Vat: Make Sheet Scheduling

A `MakePlanner` books production by creating a make sheet naming the `vat_id` and `milk_intake_id`, the `variety`, the booking interval `scheduled_start` to `scheduled_end`, the `liters_committed` from that intake, the `culture_lot_id` and `coagulant_lot_id` to consume, and the planned draws `culture_units_planned` and `coagulant_ml_planned`. The interval's end must be after its start, and all quantities must be positive, failing `ERR_INVALID_REQUEST` otherwise. Every referenced identifier must exist, per §2.6. Because booking mutates the vat, the request must also carry `expected_vat_version` as specified in §2.8; a stale reading is rejected with `ERR_STALE_VERSION` before anything else about the booking is examined.

Three booking gates then apply. The vat must be clean: `cip_clean` of `false` fails with `ERR_VAT_NOT_CLEAN`. The requested interval must not collide with the vat's existing active bookings — the make sheets on that vat in `SCHEDULED`, `IN_PROGRESS`, or `CURD_READY`. Intervals are half-open: each booking includes its start instant and excludes its end instant, so a collision exists exactly when the requested start falls before an existing booking's end and the requested end falls after that booking's start. Back-to-back adjacency — the requested start equalling an existing end, or the requested end equalling an existing start — does not overlap and is always allowed; a true collision fails with `ERR_VAT_OVERLAP`. Finally, `liters_committed` must not exceed the vat's `capacity_liters`, failing `ERR_VAT_CAPACITY`; a commitment exactly equal to capacity passes.

A successful booking is born `SCHEDULED`. The variety pins `make_steps_required` at creation — eight steps for `CHEDDAR`, six for `COLBY`, five each for `BRICK` and `MUENSTER` — while `make_steps_completed` starts at zero and `step_signer_ids` starts empty. The vat moves `IDLE` → `BOOKED` on its first active booking; additional non-overlapping bookings queue on the same vat, leaving it `BOOKED`, and every booking increments the vat's `version` by one. These queued `SCHEDULED` makes form the vat's booking queue, and the vat returns to `IDLE` only when its last active make completes or is cancelled.

Booking deliberately verifies nothing about the milk or the lots beyond existence. Milk acceptance and availability, lot usability, and lot sufficiency are all start-time gates, not booking-time gates — a planner may legitimately book a make against milk still awaiting acceptance or lots still in quarantine, and those commitments are validated when the cheesemaker starts the make.

Cancelling a make sheet is the `MakePlanner`'s compensation path. A make still `SCHEDULED` moves to `CANCELLED` with no further unwinding, since nothing was consumed. A make already `IN_PROGRESS` is cancelled with compensation: the culture lot's `quantity_on_hand` is increased by `culture_units_planned` and the coagulant lot's by `coagulant_ml_planned` — a lot sitting `DEPLETED` returns to `RELEASED` when the refund lifts it above zero — and the intake's `consumed_liters` is decreased by `liters_committed`, reversing the commit. Each reversal obeys §2.5's non-terminal rule: a lot already `EXPIRED` or `RECALLED` at cancel time is not refunded, and an intake already `CONSUMED` keeps its `consumed_liters` unchanged; the cancellation itself — the move to `CANCELLED` and the vat re-derivation — proceeds either way. In both cases the vat returns to `IDLE` only when no other make sheet on it remains in `SCHEDULED`, `IN_PROGRESS`, or `CURD_READY`; with a queue still active, the vat stays `BOOKED`. Cancelling a make that has reached `CURD_READY` or beyond is rejected with `ERR_INVALID_STATE`.

### 3.4. Running the Make: Start, Step Sign-Offs, and Completion

A `Cheesemaker` starts a `SCHEDULED` make — a make in any other state fails with `ERR_INVALID_STATE` — and start is where the deferred gates fire. The milk intake must be `ACCEPTED`, failing `ERR_MILK_NOT_ACCEPTED` otherwise. The intake's unconsumed volume — its `volume_liters` minus its `consumed_liters` — must be at least `liters_committed`, failing `ERR_MILK_SHORTFALL`; an unconsumed volume exactly equal to the commitment passes. Both additive lots must be `RELEASED` with an `expires_at` strictly later than the current logical time — a lot quarantined, recalled, depleted, or expired (including expiry exactly at the current time) fails with `ERR_ADDITIVE_LOT_UNUSABLE`. Each lot's `quantity_on_hand` must be at least the planned draw, failing `ERR_ADDITIVE_INSUFFICIENT`; exact equality passes.

Starting consumes. The culture lot's `quantity_on_hand` drops by `culture_units_planned` and the coagulant lot's by `coagulant_ml_planned`, with any lot driven to exactly zero cascading to `DEPLETED`. The intake's `consumed_liters` rises by `liters_committed` — milk is committed at start, not at schedule time — and if that brings `consumed_liters` exactly to `volume_liters`, the intake becomes `CONSUMED`. The make moves `SCHEDULED` → `IN_PROGRESS` and the vat moves `BOOKED` → `IN_MAKE`.

While the make runs, cheesemakers sign off its procedure steps in strict sequence. The sign-off for a given `stepNo` is accepted only when `make_steps_completed` is exactly `stepNo` minus one — steps are numbered from one, so the first sign-off requires zero completed steps — and any other arrival order fails with `ERR_STEP_OUT_OF_ORDER`. Segregation of duties applies within the procedure: the same cheesemaker may not sign two consecutive steps, so a signer whose `X-User-ID` matches the previous step's entry in `step_signer_ids` is rejected with `ERR_STEP_SOLE_OPERATOR`. Each accepted sign-off appends the signer to `step_signer_ids` and raises `make_steps_completed` by one; when the count reaches `make_steps_required`, the make moves `IN_PROGRESS` → `CURD_READY`.

Completion is the make's fiscal event. A `Cheesemaker` completes a `CURD_READY` make by recording the actual hooped `green_weight_kg` and the `wheels_produced` pressed from the batch. The green weight must be positive — zero or negative fails `ERR_INVALID_REQUEST` — and must not exceed `liters_committed`, since that would imply a yield above one hundred percent, failing `ERR_YIELD_IMPOSSIBLE`; a green weight exactly equal to the committed liters passes. At least one wheel must have been produced, failing `ERR_INVALID_REQUEST` otherwise.

Completing the make fans out into a cascade. A cheese batch is created in `GREEN` with `current_grade` `UNGRADED` and `release_decision` `PENDING`, carrying the make's `variety`, its `make_sheet_id`, the recorded `green_weight_kg` and `wheels_produced`, both yield figures of §3.5, `wheels_placed` at zero, and `min_age_days` pinned by variety: sixty days for `CHEDDAR`, zero for `COLBY`, thirty for `BRICK`, twenty-one for `MUENSTER`. A whey stream is created alongside it with `total_whey_kg` fixed at that moment. The vat moves `IN_MAKE` → `CLEANING` with `cip_clean` set to `false`, closing the vat to new bookings until cleaning completes. A `Cheesemaker` later completes CIP on a `CLEANING` vat — any other vat state fails with `ERR_INVALID_STATE` — which returns the vat to `IDLE` and restores `cip_clean` to `true`.

### 3.5. Yield Accounting and Whey Valorization

Every batch carries two yield figures computed at the moment the make completes. The provisional yield is a component-model estimate derived from the committed milk. The committed liters are multiplied by the intake's `fat_pct` divided by one hundred to obtain the kilograms of butterfat received, treating one liter as one kilogram; the same construction with `protein_pct` gives the kilograms of true protein. Recovered fat is the fat mass multiplied by the variety's fat-recovery factor — 0.93 for `CHEDDAR`, 0.92 for `COLBY`, 0.91 for `BRICK`, 0.90 for `MUENSTER` — and recovered protein uses 0.78, 0.77, 0.76, and 0.75 for the four varieties respectively. Estimated total solids are the recovered fat plus the recovered protein plus an other-solids allowance of 5.7 multiplied by the committed liters divided by one hundred. Estimated cheese mass is those solids divided by one minus the variety's target moisture fraction — 0.39 for `CHEDDAR`, 0.40 for `COLBY`, 0.42 for `BRICK`, 0.44 for `MUENSTER`. Finally `yield_provisional_pct` is the estimated cheese mass divided by `liters_committed` and multiplied by one hundred, rounded half-up to two decimal places. The actual yield `yield_actual_pct` is observed rather than modeled: `green_weight_kg` divided by `liters_committed`, multiplied by one hundred, rounded half-up to two decimal places. For identical inputs the two figures diverge whenever actual press and hoop losses differ from the theoretical recovery.

The whey stream accounts for everything that left the vat as something other than cheese. Its `total_whey_kg` is fixed at creation as `liters_committed` minus `green_weight_kg`, again treating one liter as one kilogram, and never changes afterward. A `Cheesemaker` records valorization — whey sold into WPC or feed channels — by setting `valorized_kg`, and each update re-derives the stream in a pinned order: first `disposed_kg` as `total_whey_kg` minus `valorized_kg`, then `valorization_rate_pct` as `valorized_kg` divided by `total_whey_kg` and multiplied by one hundred. Each stored field is rounded half-up to two decimal places in that order. A valorized amount that would push `disposed_kg` below zero is rejected with `ERR_WHEY_OVER_VALORIZED`; valorizing exactly the total, leaving zero disposal, is permitted. A stream whose `total_whey_kg` is zero carries a `valorization_rate_pct` of exactly 0.00.

### 3.6. Aging Cellar Operations: Placement, Turns, Moves, and Removal

An `AgingRoomOperator` places wheels by creating an aging unit naming the `cheese_batch_id`, the destination `aging_room_id`, and the `wheel_count` in this placement. Because placement mutates the room, the request must carry `expected_aging_room_version` per §2.8, and a stale reading fails with `ERR_STALE_VERSION` before placement rules run. Placement is then gated four ways. The room must be `ACTIVE`, failing `ERR_ROOM_DECOMMISSIONED` otherwise. The room's environment must be in band, since a `DEVIATION` posture fails the placement with `ERR_ROOM_DEVIATION`. Capacity must hold after the placement: `wheels_present` plus `wheel_count` must not exceed `capacity_wheels`, failing `ERR_ROOM_FULL`; landing exactly at capacity passes and flips the room to `FULL`. The batch must have wheels left to place: `wheel_count` must not exceed the batch's `wheels_produced` minus its `wheels_placed`, failing `ERR_WHEELS_EXHAUSTED`, with exact equality permitted.

A successful placement is born `IN_ROOM` with `entered_at` and `last_turned_at` both set to the current logical time. The batch's `wheels_placed` rises by `wheel_count`, and the batch's first placement moves it `GREEN` → `AGING`. The room's `wheels_present` rises by `wheel_count`, its `posture` is re-derived per §3.1, and its `version` increments by one. The plant's `total_aging_capacity_wheels` is untouched — placements change occupancy, never capacity.

Aging is clockwork. An `IN_ROOM` unit's `age_days` is the elapsed time from `entered_at` to the current logical time, divided into whole days of 86,400 seconds and floored — never rounded up. Its `turns_due` flag is true exactly when the whole days since `last_turned_at`, floored the same way, reach or exceed the variety's turn interval: seven days for `CHEDDAR`, five for `COLBY`, three each for `BRICK` and `MUENSTER`. A unit exactly at its interval is due. Recording a turn sets `last_turned_at` to the current logical time and recomputes `turns_due`, which will read false until the interval elapses again.

Moves relocate a unit between rooms. The operator names a `destination_aging_room_id`, which must differ from the unit's current room — moving a unit to the room it already occupies fails with `ERR_INVALID_REQUEST` — and the destination re-applies the full placement gate set for the incoming `wheel_count`: a decommissioned destination fails `ERR_ROOM_DECOMMISSIONED`, a deviating one fails `ERR_ROOM_DEVIATION`, and one without headroom fails `ERR_ROOM_FULL`. The move walks the unit `IN_ROOM` → `MOVED` → `IN_ROOM`, with the intermediate state committing and immediately re-entering: `aging_room_id` is updated while `entered_at` — and therefore the unit's age — is preserved. The source room's `wheels_present` falls by `wheel_count`, the destination's rises by the same, and both postures are re-derived.

Removal ends a unit's cellar life, and wheels may leave aging only for allocation or destruction: the unit's batch must be `RELEASED` or `CONDEMNED`, failing `ERR_INVALID_STATE` otherwise. Removal moves the unit `IN_ROOM` → terminal `REMOVED`, drops the room's `wheels_present` by `wheel_count`, and re-derives the posture.

### 3.7. Quality Grading and the Release Decision

A `QAGrader` grades a batch by recording `moisture_pct`, `fat_dry_basis_pct`, `body_score`, and `flavor_score` against its `cheese_batch_id`; the scores are integers from one to ten, with anything outside that range rejected as `ERR_INVALID_REQUEST`. The system stamps the event with the grader's `X-User-ID` as `grader_user_id` and the current logical time as `graded_at`, and computes `assigned_grade` from the readings.

Before a batch's first grading, three gates apply. Every produced wheel must rest in the cellar — `wheels_placed` must exactly equal `wheels_produced`, failing `ERR_WHEELS_UNPLACED` otherwise (a `GREEN` batch, having placed nothing, always fails here). The youngest of the batch's `IN_ROOM` aging units — the minimum of their `age_days` — must be at least the batch's `min_age_days`, failing `ERR_AGE_MINIMUM_NOT_MET`; a youngest unit whose age exactly equals the minimum passes. And the grader must be independent of the make: a `grader_user_id` appearing anywhere in the originating make sheet's `step_signer_ids` fails with `ERR_SOLE_OPERATOR`. Passing all three moves the batch `AGING` → `GRADED` — unless the assigned grade is `CONDEMNED`, which instead sends the batch straight to `CONDEMNED` with the cascade described below.

The grade ladder is evaluated top-down, and the first matching rung wins. A `body_score` of two or less, or a `flavor_score` of two or less, condemns the batch outright: `CONDEMNED`. Otherwise, a `moisture_pct` strictly above the variety's ceiling — 39.0 for `CHEDDAR`, 40.0 for `COLBY`, 44.0 for `BRICK`, 46.0 for `MUENSTER` — yields `DOWNGRADE`; moisture exactly at the ceiling passes the check. Otherwise, a `fat_dry_basis_pct` strictly below the variety's floor — 50.0 for `CHEDDAR`, `COLBY`, and `BRICK`, 48.0 for `MUENSTER` — also yields `DOWNGRADE`; fat exactly at the floor passes. Otherwise, a batch whose `body_score` is at least eight, whose `flavor_score` is at least eight, and whose `moisture_pct` is at or below the variety's grade-A moisture ceiling — 37.0 for `CHEDDAR`, 38.0 for `COLBY`, 42.0 for `BRICK`, 44.0 for `MUENSTER` — earns `GRADE_A`. Everything else is `GRADE_B`.

Whatever the outcome, the batch's `moisture_pct`, `fat_dry_basis_pct`, and `current_grade` are updated to the latest event's readings and assigned grade. A batch already `GRADED` may be re-graded while its `release_decision` is still `PENDING` — a released batch may not be re-graded, failing `ERR_INVALID_STATE` — and the independence check against `step_signer_ids` applies again. Each re-grade chains to its predecessor: the new event's `supersedes_grading_event_id` references the previously latest grading event on that batch, forming a self-referential audit chain.

Condemnation cascades. Whenever a grading assigns `CONDEMNED` — a first grading or a re-grade — the batch moves to terminal `CONDEMNED`, its `release_decision` is set to `REJECTED`, and every `OPEN` or `PARTIALLY_FILLED` allocation order against the batch is cancelled; `FILLED` orders are retained for traceability.

Release is the grader's final word on a `GRADED` batch — any other batch state fails `ERR_INVALID_STATE`. Only `GRADE_A` and `GRADE_B` batches are releasable; a `current_grade` of `DOWNGRADE`, `CONDEMNED`, or `UNGRADED` fails with `ERR_GRADE_NOT_RELEASABLE`. Release sets the batch's `release_decision` to `RELEASED` and moves the batch `GRADED` → `RELEASED`, opening it to sales allocation. The batch's final move, `RELEASED` → terminal `ALLOCATED`, is automatic: it happens the moment one of its allocation orders reaches `FILLED`, per §3.8.

### 3.8. Allocation, Cut-and-Wrap Conversion, and Waste Accountability

A `SalesPlanner` commits released cheese to customers by creating an allocation order naming the `cheese_batch_id`, the `channel` (`PRIVATE_LABEL` or `BRANDED`), the `customer_name`, the `wheels_requested`, and a `priority` in which lower numbers allocate earlier. The batch's status must be `RELEASED`, failing `ERR_BATCH_NOT_RELEASED` otherwise. The order is born `OPEN` with `wheels_cut` at zero.

When several unfilled orders compete for one batch, an allocation preview shows how the wheels would waterfall. The candidate set is the batch's orders in `OPEN` or `PARTIALLY_FILLED`; they are ranked by `priority` ascending, ties broken by `created_at` ascending — earliest order first, never by identifier. Each order's remaining need is its `wheels_requested` minus its `wheels_cut`. The wheel pool is the batch's `wheels_produced` minus its `wheels_placed` minus the cuts already committed across the candidate orders. Walking the ranked list, each order receives its remaining need capped by what remains of the pool before the next order is considered. The preview returns `order_sequence`, the candidate order identifiers in ranking order, and `wheels_allocated`, the wheels each would receive; a batch with no candidate orders yields an empty preview, not an error.

Cancelling an order is permitted only while nothing has been cut against it: a `wheels_cut` above zero fails with `ERR_ORDER_HAS_CUTS`, and a clean cancel moves the order `OPEN` → terminal `CANCELLED`.

Conversion happens in the cut-and-wrap room. A `CutWrapOperator` drafts a run against an order with `allocation_order_id`, the whole `wheels_in` fed to the cutter, the saleable `finished_case_weight_kg`, and the rind-and-trim `trim_waste_kg`. The draft is born `DRAFT`, and two figures are computed immediately: `input_weight_kg`, the `wheels_in` multiplied by the variety's standard wheel weight — 18.0 kilograms for `CHEDDAR`, 12.0 for `COLBY`, 2.5 for `BRICK`, 3.0 for `MUENSTER` — computed exactly with no intermediate rounding, and `reconciliation_gap_kg`, the input weight minus the finished case weight minus the trim waste. Both stored figures are rounded half-up to two decimal places.

Reconciliation is where waste is policed, and its gates fire in the validation order of §2.9. The order must still be `OPEN` or `PARTIALLY_FILLED`, failing `ERR_INVALID_STATE`. The batch's `release_decision` must be `RELEASED`, failing `ERR_BATCH_NOT_RELEASED`. The run must not over-fill its order: `wheels_cut` plus `wheels_in` must not exceed `wheels_requested`, failing `ERR_ORDER_OVERFILL`, with an exact fill permitted. The gap must not be negative — outputs exceeding inputs fail with `ERR_WASTE_NEGATIVE`. And the gap must fit the waste tolerance: a gap strictly greater than two percent of the run's `input_weight_kg` fails with `ERR_WASTE_TOLERANCE`, while a gap exactly equal to two percent of the input passes. The comparison is made against the tolerance computed from the exact, unrounded input weight.

A successful reconcile moves the run `DRAFT` → terminal `RECONCILED` and posts `wheels_in` into the order's `wheels_cut`. The order's status re-derives from the new total: still zero cut leaves it `OPEN`; a positive total short of `wheels_requested` moves it `OPEN` → `PARTIALLY_FILLED`; and a total exactly equal to `wheels_requested` moves it to terminal `FILLED` — from `OPEN` directly or from `PARTIALLY_FILLED` — and bubbles the batch up to `ALLOCATED` in the same operation. A draft run that should never post is voided instead, moving `DRAFT` → terminal `VOIDED` with no effect on the order.

### 3.9. Export Certification

A `ComplianceOfficer` requests an export certificate for a cut-wrap run by naming the `cut_wrap_run_id`, the `destination_country`, and the foreign `consignee`. Only one active certificate may exist per run: a second request while a certificate for the same run sits in `REQUESTED` or `ISSUED` fails with `ERR_CERT_ALREADY_EXISTS`. The request itself is deliberately lightweight — the regulatory gates fire at issuance, not at request time — and the certificate is born `REQUESTED`.

Issuance applies both gates: the plant's `export_listed` must be `true`, failing `ERR_PLANT_NOT_EXPORT_LISTED`, and the run must be `RECONCILED`, failing `ERR_RUN_NOT_RECONCILED`. Issuing mints the server-generated `certificate_number`, stamps `issued_at` from the logical clock, and moves the certificate `REQUESTED` → `ISSUED`. A requested certificate may instead be denied, moving `REQUESTED` → terminal `DENIED`, and an issued certificate may later be revoked, moving `ISSUED` → terminal `REVOKED`. Because uniqueness covers only active certificates, a fresh request may follow a denial or a revocation. Every terminal transition attempted from the wrong state — issuing a denied certificate, revoking one never issued, and the like — fails with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Endpoints that create a new resource — a plant, intake, vat, additive lot, make sheet, aging room, aging unit, grading event, allocation order, cut-wrap run, or export certificate — return `201 Created`. All other operations, including state transitions, modifications, the logical-clock call, and reads, return `200 OK` on success. Complete request and response semantics for each endpoint are governed by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/_clock/set_current_utc` | Set the logical clock; sweeps lot expiry and recomputes ages | PlantAdmin |
| POST | `/plant/plants` | Create a plant | PlantAdmin |
| GET | `/plant/plants/{plantId}` | Get a plant | PlantAdmin, MakePlanner, Cheesemaker, MilkReceiver, QAGrader, AgingRoomOperator, CutWrapOperator, SalesPlanner, ComplianceOfficer |
| PATCH | `/plant/plants/{plantId}` | Update plant flags (e.g. `export_listed`) | PlantAdmin |
| POST | `/plant/plants/{plantId}/milk-intakes` | Record a milk intake receipt | MilkReceiver |
| GET | `/plant/milk-intakes/{milkIntakeId}` | Get a milk intake | PlantAdmin, MakePlanner, Cheesemaker, MilkReceiver, QAGrader |
| GET | `/plant/milk-intakes` | List milk intakes | PlantAdmin, MakePlanner, Cheesemaker, MilkReceiver, QAGrader |
| POST | `/plant/milk-intakes/{milkIntakeId}/accept` | Accept an intake after safety gates | MilkReceiver |
| POST | `/plant/milk-intakes/{milkIntakeId}/reject` | Reject an intake | MilkReceiver |
| POST | `/plant/plants/{plantId}/vats` | Create a vat | PlantAdmin |
| GET | `/plant/vats/{vatId}` | Get a vat | PlantAdmin, MakePlanner, Cheesemaker |
| GET | `/plant/vats` | List vats | PlantAdmin, MakePlanner, Cheesemaker |
| POST | `/plant/vats/{vatId}/cip` | Complete CIP cleaning on a vat | Cheesemaker |
| POST | `/plant/vats/{vatId}/decommission` | Decommission an idle vat | PlantAdmin |
| POST | `/plant/plants/{plantId}/additive-lots` | Receive an additive lot (culture or coagulant) | PlantAdmin |
| GET | `/plant/additive-lots/{additiveLotId}` | Get an additive lot | PlantAdmin, Cheesemaker, QAGrader, MakePlanner |
| GET | `/plant/additive-lots` | List additive lots | PlantAdmin, Cheesemaker, QAGrader, MakePlanner |
| POST | `/plant/additive-lots/{additiveLotId}/release` | Release a lot from quarantine | QAGrader |
| POST | `/plant/additive-lots/{additiveLotId}/recall` | Recall a lot | QAGrader |
| POST | `/plant/make-sheets` | Book a vat and create a make sheet (OCC on the vat) | MakePlanner |
| GET | `/plant/make-sheets/{makeSheetId}` | Get a make sheet | PlantAdmin, MakePlanner, Cheesemaker, QAGrader |
| GET | `/plant/make-sheets` | List make sheets | PlantAdmin, MakePlanner, Cheesemaker, QAGrader |
| POST | `/plant/make-sheets/{makeSheetId}/start` | Start the make; consumes additive lots and commits milk | Cheesemaker |
| POST | `/plant/make-sheets/{makeSheetId}/steps/{stepNo}/sign-off` | Sign off a make-procedure step (strictly sequential; no consecutive same-operator) | Cheesemaker |
| POST | `/plant/make-sheets/{makeSheetId}/complete` | Complete the make; creates the cheese batch and whey stream | Cheesemaker |
| POST | `/plant/make-sheets/{makeSheetId}/cancel` | Cancel a make; refunds lots and milk commitment when in progress | MakePlanner |
| GET | `/plant/cheese-batches/{cheeseBatchId}` | Get a cheese batch | PlantAdmin, MakePlanner, Cheesemaker, QAGrader, AgingRoomOperator, SalesPlanner, CutWrapOperator, ComplianceOfficer |
| GET | `/plant/cheese-batches` | List cheese batches | PlantAdmin, MakePlanner, Cheesemaker, QAGrader, AgingRoomOperator, SalesPlanner, CutWrapOperator, ComplianceOfficer |
| POST | `/plant/cheese-batches/{cheeseBatchId}/release` | Release a graded batch for allocation | QAGrader |
| GET | `/plant/cheese-batches/{cheeseBatchId}/allocation-preview` | Preview waterfall allocation of open orders against this batch | PlantAdmin, SalesPlanner, QAGrader |
| GET | `/plant/whey-streams/{wheyStreamId}` | Get a whey stream | PlantAdmin, Cheesemaker, QAGrader |
| GET | `/plant/whey-streams` | List whey streams | PlantAdmin, Cheesemaker, QAGrader |
| PUT | `/plant/whey-streams/{wheyStreamId}` | Record the whey valorization amount | Cheesemaker |
| POST | `/plant/plants/{plantId}/aging-rooms` | Create an aging room | PlantAdmin |
| GET | `/plant/aging-rooms/{agingRoomId}` | Get an aging room | PlantAdmin, AgingRoomOperator, QAGrader |
| GET | `/plant/aging-rooms` | List aging rooms | PlantAdmin, AgingRoomOperator, QAGrader |
| PATCH | `/plant/aging-rooms/{agingRoomId}` | Update room environment readings | AgingRoomOperator |
| POST | `/plant/aging-rooms/{agingRoomId}/decommission` | Decommission an empty room | PlantAdmin |
| POST | `/plant/aging-units` | Place wheels from a batch into an aging room (OCC on the room) | AgingRoomOperator |
| GET | `/plant/aging-units/{agingUnitId}` | Get an aging unit | PlantAdmin, AgingRoomOperator, QAGrader |
| GET | `/plant/aging-units` | List aging units | PlantAdmin, AgingRoomOperator, QAGrader |
| POST | `/plant/aging-units/{agingUnitId}/turn` | Record a turn (flip/brushing) of the wheels | AgingRoomOperator |
| POST | `/plant/aging-units/{agingUnitId}/move` | Move a unit to a different room | AgingRoomOperator |
| POST | `/plant/aging-units/{agingUnitId}/remove` | Remove wheels from aging (release for allocation or destruction) | AgingRoomOperator |
| POST | `/plant/grading-events` | Record a grading event for a batch (may re-grade; supersedes the prior event) | QAGrader |
| GET | `/plant/grading-events/{gradingEventId}` | Get a grading event | PlantAdmin, QAGrader |
| GET | `/plant/grading-events` | List grading events | PlantAdmin, QAGrader |
| POST | `/plant/allocation-orders` | Create an allocation order against a batch | SalesPlanner |
| GET | `/plant/allocation-orders/{allocationOrderId}` | Get an allocation order | PlantAdmin, SalesPlanner, CutWrapOperator, QAGrader |
| GET | `/plant/allocation-orders` | List allocation orders | PlantAdmin, SalesPlanner, CutWrapOperator, QAGrader |
| POST | `/plant/allocation-orders/{allocationOrderId}/cancel` | Cancel an uncut order | SalesPlanner |
| POST | `/plant/cut-wrap-runs` | Create a draft cut-and-wrap run against an order | CutWrapOperator |
| GET | `/plant/cut-wrap-runs/{cutWrapRunId}` | Get a cut-wrap run | PlantAdmin, CutWrapOperator, ComplianceOfficer, SalesPlanner |
| GET | `/plant/cut-wrap-runs` | List cut-wrap runs | PlantAdmin, CutWrapOperator, ComplianceOfficer, SalesPlanner |
| POST | `/plant/cut-wrap-runs/{cutWrapRunId}/reconcile` | Reconcile a run: waste tolerance gate, posts wheels to the order | CutWrapOperator |
| POST | `/plant/cut-wrap-runs/{cutWrapRunId}/void` | Void a draft run | CutWrapOperator |
| POST | `/plant/export-certificates` | Request an export certificate for a reconciled run | ComplianceOfficer |
| GET | `/plant/export-certificates/{exportCertificateId}` | Get an export certificate | PlantAdmin, ComplianceOfficer |
| GET | `/plant/export-certificates` | List export certificates | PlantAdmin, ComplianceOfficer |
| POST | `/plant/export-certificates/{exportCertificateId}/issue` | Issue the certificate (plant export-listing gate) | ComplianceOfficer |
| POST | `/plant/export-certificates/{exportCertificateId}/deny` | Deny a requested certificate | ComplianceOfficer |
| POST | `/plant/export-certificates/{exportCertificateId}/revoke` | Revoke an issued certificate | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue fixes only the identifier and HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SCC_LIMIT` | 422 Unprocessable Entity |
| `ERR_ANTIBIOTIC_POSITIVE` | 422 Unprocessable Entity |
| `ERR_MILK_NOT_ACCEPTED` | 409 Conflict |
| `ERR_MILK_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_VAT_OVERLAP` | 409 Conflict |
| `ERR_VAT_CAPACITY` | 409 Conflict |
| `ERR_VAT_NOT_CLEAN` | 409 Conflict |
| `ERR_ADDITIVE_LOT_UNUSABLE` | 422 Unprocessable Entity |
| `ERR_ADDITIVE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_STEP_OUT_OF_ORDER` | 409 Conflict |
| `ERR_STEP_SOLE_OPERATOR` | 422 Unprocessable Entity |
| `ERR_YIELD_IMPOSSIBLE` | 422 Unprocessable Entity |
| `ERR_WHEY_OVER_VALORIZED` | 422 Unprocessable Entity |
| `ERR_ROOM_FULL` | 409 Conflict |
| `ERR_ROOM_DEVIATION` | 409 Conflict |
| `ERR_ROOM_DECOMMISSIONED` | 409 Conflict |
| `ERR_ROOM_NOT_EMPTY` | 409 Conflict |
| `ERR_WHEELS_EXHAUSTED` | 409 Conflict |
| `ERR_WHEELS_UNPLACED` | 409 Conflict |
| `ERR_AGE_MINIMUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_SOLE_OPERATOR` | 422 Unprocessable Entity |
| `ERR_GRADE_NOT_RELEASABLE` | 409 Conflict |
| `ERR_BATCH_NOT_RELEASED` | 409 Conflict |
| `ERR_ORDER_OVERFILL` | 422 Unprocessable Entity |
| `ERR_ORDER_HAS_CUTS` | 409 Conflict |
| `ERR_WASTE_NEGATIVE` | 422 Unprocessable Entity |
| `ERR_WASTE_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_PLANT_NOT_EXPORT_LISTED` | 409 Conflict |
| `ERR_RUN_NOT_RECONCILED` | 409 Conflict |
| `ERR_CERT_ALREADY_EXISTS` | 409 Conflict |

# Tree Nut Huller Processor API — Product Requirements Document

## 1. Introduction

A California almond huller operates in the narrow window between harvest and marketing. Growers deliver field-run lots of almonds — still carrying their hulls, shells, sticks, and harvest moisture — and the plant must weigh each lot at the scale, draw samples for the laboratory, decide whether the lot needs drying before it can be hulled, route it toward in-shell or kernel production, and ultimately pay the grower on the graded weight of edible kernel the lot actually produced. Along the way the plant warehouses four distinct product forms, fumigates storage bins on a regulated cycle, sells hull and shell byproduct to whoever will haul it, and fills buyer contracts that specify not just a product form but a sizing specification and a defect ceiling. Every one of those decisions is constrained by food-safety law: a single aflatoxin sample at or above the federal action level can quarantine a full lot and every bin position it touches.

This document specifies the Tree Nut Huller Processor API, a flat, multi-collection REST surface that models that operation end to end. It covers field lot intake and the receiving laboratory, dryer reservations and moisture correction, hulling runs and their yield accounting, bin storage with first-in-first-out rotation, fumigation scheduling with aeration buffers, buyer contracts and shipment planning, grower settlements, and byproduct sales. The system is ledger-minded throughout: weights, reservations, and cents are recomputed deterministically from recorded events, grower balances move only through explicit settlement actions, and a logical clock — never the wall clock — governs every schedule window so that the plant's behavior is fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold for every resource and every request, independent of the workflow in play.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The declared roles are `PlantAdmin`, `IntakeOperator`, `LabTechnician`, `PlantOperator`, `Grower`, and `Buyer`. A request missing either header, or presenting an `X-User-Role` value outside that declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the targeted endpoint — or, for the entity-backed roles described below, that reaches outside its ownership scope — is rejected with `ERR_FORBIDDEN` (HTTP 403).

The four plant-side roles carry opaque identities. When `X-User-Role` is `PlantAdmin`, `IntakeOperator`, `LabTechnician`, or `PlantOperator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it against any resource's `id`. `PlantAdmin` owns huller administration: master data (growers, buyers, dryers, bins), buyer contracts, settlements, fumigation scheduling, and the logical clock. `IntakeOperator` runs the scale house: lot intake, routing, resampling, and disposition. `LabTechnician` records laboratory tests. `PlantOperator` runs the plant floor: processing runs, drying batches, placements, withdrawals, shipments, and byproduct sales.

The two external roles are entity-backed. When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a grower compare the resource's `grower_id` field to `X-User-ID`, so a grower sees only their own lots and settlements. When `X-User-Role` is `Buyer`, `X-User-ID` is the `id` of the acting `Buyer`; ownership checks compare the contract's `buyer_id` (directly, or through the shipment's contract) to `X-User-ID`, so a buyer sees only their own contracts and shipments. On list endpoints the ownership scope is forced regardless of query parameters: for an entity-backed caller, a `grower_id` filter on `/lots` or `/settlements`, or a `buyer_id` filter on `/contracts`, that names another owner is overridden by the caller's own id rather than combined with it, while the buyer scope on `/shipments` combines conjunctively with whatever other filters are supplied.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.5 (on error responses as well).
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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items from the front of the result set and defaults to 0. Both are optional on every list endpoint. A `limit` or `offset` that does not parse as an integer, a `limit` outside [1, 100], or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400).

Unless a section states otherwise, every list endpoint returns resources sorted by `created_at` in ascending order — oldest first; ties on `created_at` break by creation order, earliest-created first. Endpoint-specific filter parameters combine conjunctively; a filter on an entity identifier that matches nothing simply yields an empty page rather than a not-found error, and a filter that takes an enum value rejects an out-of-set value with `ERR_INVALID_ENUM` (400).

The `meta` object of every list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reports the full size of the filtered result set and `has_more` indicates whether items remain beyond the returned window.

### 2.4. Common Resource Properties

Every resource in this API — growers, buyers, field lots, lab tests, processing runs, dryers, drying batches, storage bins, placements, withdrawals, fumigation events, contracts, shipments, settlements, and byproduct sales — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-05-01T07:15:00.123Z`), set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation.

A mutation is any change to the resource's stored fields, whether client-driven or system-driven. Cascading updates described later in this document — a lot rejected by an aflatoxin failure, a bin pulled into `FUMIGATING`, a contract advanced to `FULFILLED` by a shipment confirmation — are mutations of the affected resource and therefore refresh its `updated_at` and increment its `version`, exactly as a direct write would.

### 2.5. The Logical Clock and Lazy Fumigation Clearance

All scheduling in the plant — dryer windows, fumigation events, aeration buffers — is evaluated against a server-maintained **logical clock**, never against wall-clock time. Before any client has set it, the logical clock starts at exactly `2026-05-01T00:00:00Z`; the server must not fall back to wall-clock time at startup or at any other point. Timestamps the system stamps onto records, such as a lab test's `recorded_at`, a placement's `placed_at`, and a withdrawal's `withdrawn_at`, are all taken from this logical clock.

A `PlantAdmin` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` instant — earlier or later than the current value; the clock is simply set, with no monotonicity constraint — and answers with the resulting clock value in a `current_utc` field of the response body. Setting the clock is never inert: it triggers **lazy fumigation clearance**. Any fumigation event sitting in `AERATING` whose `cleared_at` is at or before the current clock transitions to `CLEARED`; its bin moves from `AERATING` back to `AVAILABLE` and the bin's `fumigation_cleared_at` is reset to null; placements of that bin held in `FUMIGATION_HOLD` return to `STORED`; and any shipment in `BLOCKED` whose allocated placements have all returned to `STORED` moves back to `PLANNED`. The same lazy clearance is in fact evaluated at the head of every request the server receives — always before the request's own rules are checked, and in particular before any operation touching a bin whose fumigation event is in `AERATING` — so a bin never stays locked past its clearance instant merely because nobody advanced the clock.

### 2.6. Weights, Money, and Rounding Discipline

Weights are carried as numbers in pounds. Any computed weight — intake-derived estimates, graded kernel weight, bin occupancy figures, FIFO allocations, byproduct stock — is rounded to exactly 2 decimal places using round-half-up, and weight quantities returned by the API observe that same precision.

Money is carried in integer cents. Prices are whole-cent rates per pound: a grower's `base_price_cents_per_lb` and a contract's or byproduct sale's `price_cents_per_lb` are positive integers. Settlement arithmetic is component-rounded: each settlement component (`base_cents`, `premium_cents`, `moisture_deduction_cents`) is individually rounded half-up to whole cents — 0 decimal places — **before** any summation, and the settlement's `total_cents` is the integer sum of those already-rounded components. The total is never produced by summing unrounded components and rounding once at the end. Grower balances (`payable_outstanding_cents`, `lifetime_paid_cents`) and a byproduct sale's `total_cents` are likewise whole cents.

Timestamp comparisons for schedule windows and interval overlap are exact comparisons of the parsed ISO 8601 values — fractional seconds included when supplied, and a value without a zone offset is read as UTC; a timestamp field that does not parse as ISO 8601 is a request-shape failure (`ERR_INVALID_REQUEST`, 400). The aflatoxin verdict compares the sample's parts-per-billion value at 1 decimal place of significance against the action level.

### 2.7. Optimistic Concurrency on Lots and Contracts

Two creation endpoints are optimistic-concurrency controlled against a parent resource's `version`, because both parents legitimately accumulate many children over time.

Creating a processing run requires the request to carry `expected_lot_version`, a non-optional field holding the `version` of the target field lot as the client last observed it. If the lot's current `version` no longer matches — because another write, such as an earlier run creation or a state cascade, has advanced it — the creation is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Creating a shipment likewise requires `expected_contract_version`, matched against the buyer contract's current `version`; a mismatch is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). In both cases the client must re-read the parent and retry with the fresh version; a second creation carrying a current version succeeds, since multiple runs per lot and multiple shipments per contract are legitimate. No other endpoint takes a version field — clients must not send one elsewhere, and no other write performs this check.

Successful creation under either rule itself increments the parent's `version` by one (and refreshes its `updated_at`), so back-to-back creators must always work from a fresh read.

### 2.8. Validation Order and Error Precedence

A single request can violate several rules at once — a mistyped enum on a lot that is also in the wrong state, against a bin that is also full. The plant resolves such collisions with a fixed precedence order: when a request violates rules from several of the ten categories below, the violation belonging to the **earliest** category is the one reported, and the rest are masked until the request is retried.

1. **Authentication.** `X-User-Role` and `X-User-ID` are present and the role is declared; otherwise `ERR_UNAUTHENTICATED` (401).
2. **Authorization and ownership scope.** The role is permitted for the endpoint, and an entity-backed caller (`Grower` or `Buyer`) is inside its ownership scope; otherwise `ERR_FORBIDDEN` (403). A grower asking after another grower's lot hears `ERR_FORBIDDEN`, never whether that lot exists. Ownership is evaluated against an existing resource: on `/growers/{id}` and `/buyers/{id}`, where the scope question is settled by the caller's own identity, the 403 fires before any lookup; on every other entity-scoped read an unresolvable path id draws its 404 (category 3) before ownership of that resource can be evaluated.
3. **Existence.** Path identifiers are validated left to right, then body foreign-key fields (`grower_id`, `lot_id`, `dryer_id`, `bin_id`, `contract_id`, `buyer_id`) must reference existing entities; otherwise the matching per-entity not-found error (404) from §2.9.
4. **Optimistic concurrency.** `expected_lot_version` against the lot on run creation, `expected_contract_version` against the contract on shipment creation; mismatches yield `ERR_STALE_LOT_VERSION` or `ERR_STALE_CONTRACT_VERSION` (412).
5. **Request shape.** Required fields are present — a field supplied with an explicit null value counts as absent — types are correct, a body that parses to a non-object JSON value is a shape failure, enum values belong to their declared sets, and the test-type-conditional field rules on lab-test recording hold; fields outside an endpoint's defined request shape are otherwise ignored. Violations draw `ERR_INVALID_REQUEST` (400), or `ERR_INVALID_ENUM` (400) specifically for enum membership failures.
6. **State preconditions.** The target entity is in a valid from-state for the requested transition. Triggers attempted on an entity already in a terminal state are rejected with `ERR_ALREADY_TERMINAL` (409); any other invalid from-state with `ERR_INVALID_STATE` (409). This category covers every action endpoint — routing, resample, dispose, run start/complete/cancel, batch start/complete/cancel, fumigation start/begin-aeration/cancel, contract suspend/resume/close, shipment confirm/cancel, settlement approve/void/pay/cancel — and also the state gates on recording a lab test (a kernel grade requires a `PROCESSED` lot; moisture and aflatoxin tests require a lot that has not reached a terminal state) and on reserving a drying batch (the lot must already have a recorded moisture/kernel test).
7. **Safety lockouts.** Aflatoxin clearance for routing (`ERR_AFLATOXIN_UNRESOLVED`, 422) and the fumigation lockout on placements, withdrawals, shipment creation, and shipment confirmation (`ERR_BIN_FUMIGATION_ACTIVE`, 422), the latter evaluated only after lazy clearance has run.
8. **Temporal conflicts.** Dryer reservation overlap (`ERR_DRYER_TIME_CONFLICT`, 409), fumigation schedule overlap including the aeration buffer (`ERR_FUMIGATION_TIME_CONFLICT`, 409), and schedule-window violations on batch start, batch complete, and fumigation start (`ERR_SCHEDULE_WINDOW_NOT_OPEN`, 422).
9. **Physical and product constraints.** The drying prerequisite for moist lots (`ERR_DRYING_REQUIRED`, 422), bin product-form admissibility (`ERR_BIN_PRODUCT_MISMATCH`, 422), bin capacity (`ERR_BIN_CAPACITY_EXCEEDED`, 422), the sizing-spec gate on shipment allocation (`ERR_SPEC_MISMATCH`, 422), the non-negative shrink rule on run completion (`ERR_SHRINK_NEGATIVE`, 422), and the per-lot output ceiling on placements (`ERR_LOT_OUTPUT_EXCEEDED`, 422).
10. **Fiscal and stock ceilings.** Contract remaining quantity (`ERR_CONTRACT_REMAINING_EXCEEDED`, 422), the FIFO free pool on withdrawals (`ERR_INSUFFICIENT_STORED`, 422), and plant-wide byproduct stock (`ERR_BYPRODUCT_STOCK_EXCEEDED`, 422).

### 2.9. Referential Integrity and Not-Found Errors

Identifiers in the URL path are validated left to right, and the request is rejected at the **first** identifier that does not resolve, with the error specific to that resource. Only after every path identifier resolves does the server validate foreign keys carried in the request body, checking them in the order `grower_id`, `lot_id`, `dryer_id`, `bin_id`, `contract_id`, `buyer_id` and rejecting at the first that does not resolve. Each resource type has its own not-found error, all HTTP 404: `ERR_GROWER_NOT_FOUND` for grower references, `ERR_BUYER_NOT_FOUND` for buyer references, `ERR_LOT_NOT_FOUND` for lot references, `ERR_DRYER_NOT_FOUND` for dryer references, `ERR_DRYING_BATCH_NOT_FOUND` for drying-batch path ids, `ERR_BIN_NOT_FOUND` for bin references, `ERR_PROCESSING_RUN_NOT_FOUND` for processing-run path ids, `ERR_FUMIGATION_NOT_FOUND` for fumigation path ids, `ERR_CONTRACT_NOT_FOUND` for contract references, `ERR_SHIPMENT_NOT_FOUND` for shipment path ids, and `ERR_SETTLEMENT_NOT_FOUND` for settlement path ids. Resource types without a dedicated not-found identifier — lab tests, placements, and withdrawals — answer an unresolvable path id with `ERR_NOT_FOUND` (404), which also answers requests to undefined routes.

### 2.10. Plant-Wide Safety Cascades

Two safety regimes propagate far beyond the record that triggered them, and the system applies both automatically, without a client request on the affected resources.

The **aflatoxin regime** binds a lot, its bin positions, and its planned shipments into one fate. When a recorded aflatoxin sample fails the action level, the lot is rejected, every stored placement of that lot is quarantined, and every planned shipment whose reservations touch those placements is blocked. The regime also has a compensation path: if the lot is resampled and a later sample passes, the quarantine unwinds — placements return to stored status and blocked shipments whose allocations are clean return to planned. Disposal is the terminal branch: quarantined placements leave the bins entirely.

The **fumigation regime** binds a bin, its contents, and its shippers. Starting a fumigation event pulls the bin out of service, holds every stored placement in it, and blocks planned shipments reserving those placements; clearing the event — always lazily, when the clock shows the aeration buffer has elapsed — releases all three in the same breath. The detailed state pairs and their guards live in §3.2 and §3.6.

Bubble-up transitions work the same way in the commercial direction: confirming a shipment can fulfill its contract, and paying a settlement settles its lot. No cascade ever skips the bookkeeping of §2.4 — every resource a cascade touches takes its own `updated_at` refresh and `version` increment.

## 3. Business Logic & Workflows

### 3.1. Master Data: Growers, Buyers, and Plant Equipment

Everything in the plant hangs off a small set of registered counterparties and equipment, all maintained by a `PlantAdmin`.

A grower registration records the ranch's legal `name`, a `ranch_code` that must be unique across all growers (a duplicate is rejected with `ERR_INVALID_REQUEST`), and the contracted `base_price_cents_per_lb` — a positive whole-cent rate that will eventually price each pound of graded kernel. Registration may also set a `premium_rate_pct`, a grade premium expressed as a fraction between 0 and 1 inclusive that rewards lots whose edible kernel share clears the premium bar; when omitted (or supplied as null) it defaults to `0.0`. Two computed balances follow the grower through the season: `payable_outstanding_cents`, the sum of `total_cents` over that grower's settlements currently in `ISSUED` status, and `lifetime_paid_cents`, the sum over settlements in `PAID` status. Both start at 0 and move only through the settlement actions of §3.8.

A buyer registration is simpler: a company `name` and a `buyer_code` unique across buyers (duplicates again drawing `ERR_INVALID_REQUEST`). Equipment registration covers dryers and storage bins. A dryer is registered with a unique `dryer_code` and a `capacity_lbs` — a positive integer ceiling on the lot gross weight a single batch may hold. A bin is registered with a unique `bin_code`, its own positive integer `capacity_lbs`, and `allowed_product_forms`, a non-empty subset of the four product forms `IN_SHELL`, `KERNEL`, `HULL`, and `SHELL` declaring what the bin may hold; duplicate `dryer_code` or `bin_code` values are likewise rejected with `ERR_INVALID_REQUEST`. Dryers can be listed by `PlantAdmin` and `PlantOperator`, and bins can be listed and re-read individually by those roles; growers and buyers can be listed by `PlantAdmin`, while a `Grower` or `Buyer` caller may read back only its own record.

### 3.2. Field Lot Intake and the Receiving Laboratory

The season begins at the scale house. An `IntakeOperator` receives a field lot by naming the delivering `grower_id`, the almond `variety` (Nonpareil, Monterey, and the like), and the `gross_weight_lbs` — the scale weight at intake, which must be greater than zero. The lot is born in `RECEIVED` status, and at that moment every laboratory-derived field on it is null: `intake_moisture_pct`, `intake_kernel_pct`, `intake_fm_pct`, `aflatoxin_ppb`, `edible_kernel_pct`, `size_spec`, `post_dry_moisture_pct`, `requires_drying`, `provisional_kernel_lbs`, and `graded_kernel_weight_lbs` all wait for evidence, while its harvest accumulators `kernel_out_lbs`, `shell_out_lbs`, and `hull_out_lbs` start at 0.

All evidence arrives through the laboratory. A `LabTechnician` records a lab test against a `lot_id`, choosing a `test_type` of `MOISTURE_KERNEL`, `AFLATOXIN`, or `KERNEL_GRADE`; the system stamps `recorded_at` from the logical clock. The payload's remaining fields are **conditionally required by test type**, and supplying a field the type forbids is as much an error as omitting one it requires — either violation is rejected with `ERR_INVALID_REQUEST`:

- A `MOISTURE_KERNEL` test requires `moisture_pct` (greater than 0 and less than 100), `kernel_pct` (greater than 0 and at most 1, the kernel fraction of the sample), and `foreign_material_pct` (at least 0 and less than 1). The aflatoxin and grade fields are forbidden on this type.
- An `AFLATOXIN` test requires `aflatoxin_ppb` (zero or greater, parts per billion). Every other measurement field is forbidden.
- A `KERNEL_GRADE` test requires `edible_kernel_pct` (greater than 0 and at most 1, the edible share of kernel) and a `size_spec` of `SPEC_20_22`, `SPEC_23_25`, `SPEC_25_27`, or `UNSIZED`. Every other measurement field is forbidden. A kernel grade may only be recorded against a lot in `PROCESSED` status; against any other state the recording is rejected with `ERR_INVALID_STATE` — or with `ERR_ALREADY_TERMINAL` when the lot is in a terminal state, per §2.8.

Moisture and aflatoxin tests may be recorded against any lot that has not reached a terminal state (`DISPOSED` or `SETTLED`); an enum value outside the declared sets above draws `ERR_INVALID_ENUM`. Recording the first moisture/kernel test against a `RECEIVED` lot advances it to `SAMPLED` and fills the intake profile: `intake_moisture_pct`, `intake_kernel_pct`, and `intake_fm_pct` always reflect the **latest** recorded moisture/kernel test (where two tests of a type share a `recorded_at`, the later-created test is the latest — here and wherever the latest test of a type is consulted). From that profile the lot's drying flag is derived — `requires_drying` is true when the intake moisture exceeds the 8.0 percent standard moisture level, false once the intake moisture is known to be at or below it, and null until then — along with a forward-looking kernel estimate, `provisional_kernel_lbs`, computed as the lot's `gross_weight_lbs` multiplied by its `intake_kernel_pct`, multiplied by one minus `intake_fm_pct`, and then discounted by one percent per point of intake moisture above the 8.0 percent standard, fractional excess prorated — an intake moisture of 9.5 percent carries an excess of 1.5 points and therefore a 1.5 percent discount (no discount applies when the moisture is at or below standard); the result is rounded half-up to 2 decimal places.

The aflatoxin gate is a hard threshold. Every recorded aflatoxin test receives an `aflatoxin_verdict` — a computed field set only on `AFLATOXIN` tests and null on the other types — of `FAIL` when the sample is at or above the action level of 20.0 parts per billion and `PASS` below it; the boundary value 20.0 itself fails. A `PASS` recorded against a `SAMPLED` lot advances it to `GRADED` and copies the sample's value onto the lot's `aflatoxin_ppb`. A `FAIL` — from any lot in `SAMPLED`, `GRADED`, `ROUTED_IN_SHELL`, `ROUTED_KERNEL`, `PROCESSING`, or `PROCESSED` — drives the lot to `REJECTED`, copies the sample onto `aflatoxin_ppb`, and fires the first cascade of §2.10: every `STORED` placement of this lot moves to `QUARANTINED`, and every `PLANNED` shipment whose allocations reference any of those placements moves to `BLOCKED`. An aflatoxin test recorded against a lot in any other non-terminal state — a `PASS` against a lot that is not `SAMPLED`, or a `FAIL` against a `RECEIVED` or already `REJECTED` lot — still copies its value onto the lot's `aflatoxin_ppb` but changes no status and fires no cascade.

Rejection is not necessarily the end. An `IntakeOperator` may resample a `REJECTED` lot, cycling it back to `SAMPLED` and resetting its `aflatoxin_ppb` to null while the lot awaits a new aflatoxin test; its placements stay `QUARANTINED` throughout, and only a subsequent `PASS` — which transitions the lot from `SAMPLED` to `GRADED` as usual — releases them back to `STORED` and returns any `BLOCKED` shipment whose allocated placements are all stored again to `PLANNED`. The alternative is disposal: disposing a `REJECTED` lot moves it to `DISPOSED`, moves its `QUARANTINED` placements to `DISPOSED`, and recomputes the affected bins' occupancy fields since the disposed weight physically leaves the bins. Both actions require the lot to be `REJECTED`; from any other state they are rejected with `ERR_INVALID_STATE`.

Lots may be browsed through the list endpoint — filterable by `grower_id` and by `status` — with a `Grower` caller seeing only its own lots, and read individually by any plant role or by the owning grower.

### 3.3. Drying Operations and Moisture Correction

A lot whose intake moisture exceeded the 8.0 percent standard carries `requires_drying` true, and the plant will not route it until a drying run has been completed (§3.4). A `PlantOperator` reserves a dryer by creating a drying batch naming the `dryer_id`, the `lot_id`, and a reservation window from `start_at` to `end_at`; the end must be strictly later than the start. Reservation requires the lot to already have a recorded moisture/kernel test — the plant does not book dryer time for untested lots — and a lot without one is rejected with `ERR_INVALID_STATE`. The batch is created in `SCHEDULED` status.

Dryer windows are **half-open intervals**: a reservation occupies its dryer from `start_at` up to but not including `end_at`. A new batch conflicts with an existing one on the same dryer when the existing batch is `SCHEDULED` or `DRYING` and the two windows genuinely overlap — the new start falls before the existing end while the new end falls after the existing start. Adjacent bookings do not conflict: a new batch beginning exactly at an existing batch's `end_at` is legal, as is one ending exactly at the other's `start_at`. Conflicting reservations are rejected with `ERR_DRYER_TIME_CONFLICT` (409). Batches that are `COMPLETED` or `CANCELLED` no longer occupy the dryer.

Running the batch is clock-gated. Starting moves `SCHEDULED` to `DRYING` and is only permitted once the logical clock has reached `start_at`; an early start is rejected with `ERR_SCHEDULE_WINDOW_NOT_OPEN` (422). Completion moves `DRYING` to `COMPLETED`, is only permitted once the clock has reached `end_at` — again, `ERR_SCHEDULE_WINDOW_NOT_OPEN` if early — and records the measured `final_moisture_pct` (greater than 0, less than 100) supplied at completion. That final moisture is copied onto the lot as `post_dry_moisture_pct`, which always reflects the latest completed batch for the lot and is null until one exists; it is the value settlement arithmetic will later prefer over intake moisture. A batch still in `SCHEDULED` may instead be cancelled, moving it to `CANCELLED`. Batches may be listed filtered by `dryer_id`, `lot_id`, or `status`, and read individually.

### 3.4. Routing Decisions and Hulling Runs

Once a lot is `GRADED`, an `IntakeOperator` routes it by supplying a `route` of `IN_SHELL` or `KERNEL`, moving the lot to `ROUTED_IN_SHELL` or `ROUTED_KERNEL` respectively. Both branches carry identical gates. The lot must be `GRADED`; any other state draws `ERR_INVALID_STATE`, and a terminal lot draws `ERR_ALREADY_TERMINAL`. The latest recorded aflatoxin test must exist with a `PASS` verdict — routing a lot with no passing aflatoxin result on file is rejected with `ERR_AFLATOXIN_UNRESOLVED`. And when the lot's `requires_drying` flag is true, routing is refused with `ERR_DRYING_REQUIRED` until at least one drying batch for the lot has reached `COMPLETED`.

Hulling itself is organized as processing runs, created by a `PlantOperator` against a `lot_id` under the optimistic concurrency rule of §2.7 — the request must carry `expected_lot_version` equal to the lot's current `version`, and a stale value is rejected with `ERR_STALE_LOT_VERSION` (412). The lot must be in `ROUTED_IN_SHELL`, `ROUTED_KERNEL`, or already `PROCESSING`; multiple runs per lot are legitimate, and the first non-cancelled run moves the lot from its routed state into `PROCESSING` while incrementing the lot's `version` by one. Each run is created in `QUEUED` status with an `input_weight_lbs` snapshot the server computes at creation: the lot's `gross_weight_lbs` minus the sum of `input_weight_lbs` over the lot's other runs that are not `CANCELLED`. A run's output fields — `kernel_out_lbs`, `shell_out_lbs`, and `hull_out_lbs` — are null until completion.

A `QUEUED` run may be started, moving it to `RUNNING`, provided its lot is in `ROUTED_IN_SHELL`, `ROUTED_KERNEL`, or `PROCESSING`; or it may be cancelled, moving `QUEUED` to `CANCELLED`. Completing a `RUNNING` run records the three output weights supplied at completion, each zero or greater. Hulling always loses something — tramp material, moisture, dust — so the three outputs summed together may not exceed the run's `input_weight_lbs`; a completion whose outputs exceed the snapshot is rejected with `ERR_SHRINK_NEGATIVE`, the shrink being the non-negative difference between input and outputs. A successful completion moves the run to `COMPLETED` and recomputes the lot's harvest accumulators `kernel_out_lbs`, `shell_out_lbs`, and `hull_out_lbs` as the sums of the corresponding outputs over the lot's `COMPLETED` runs only — queued, running, and cancelled runs never contribute. The first completion moves the lot from `PROCESSING` to `PROCESSED`.

Grading closes the loop on yield. A kernel-grade test (§3.2) recorded against the `PROCESSED` lot computes the lot's `graded_kernel_weight_lbs`: the sum of `kernel_out_lbs` over the lot's `COMPLETED` runs multiplied by the test's `edible_kernel_pct`, rounded half-up to 2 decimal places. This final, actual figure — not the intake estimate — is what grower payment is based on, and the test's `size_spec` is likewise copied onto the lot. Because later runs can still complete after a grade exists, every subsequent run completion recomputes `graded_kernel_weight_lbs` from the then-current completed-run totals whenever a kernel grade is on file. Runs may be listed filtered by `lot_id` or `status` and read individually.

### 3.5. Storage Bins, Placements, and FIFO Withdrawals

Processed product moves into storage bins, each a `PlantAdmin`-registered box with a `bin_code`, a `capacity_lbs`, an `allowed_product_forms` list, and a status of `AVAILABLE`, `FUMIGATING`, or `AERATING`. Three computed figures describe every bin's load. `occupied_lbs` sums `remaining_lbs` over the bin's placements in `STORED`, `FUMIGATION_HOLD`, or `QUARANTINED` status — withdrawn and disposed placements no longer occupy space. `available_now_lbs` is the current capacity picture: `capacity_lbs` minus `occupied_lbs`, what could be placed right now. `projected_available_lbs` is the forward-looking picture: it additionally subtracts the `allocated_planned_lbs` reserved by planned or blocked shipments across those same placements, answering what remains free assuming every outstanding shipment actually ships, and is therefore never greater than `available_now_lbs`. All three are rounded half-up to 2 decimal places and recomputed on any mutation touching the bin's placements or the shipments reserving them.

A `PlantOperator` places product into a bin by naming the `bin_id`, the source `lot_id`, the `product_form` (`IN_SHELL`, `KERNEL`, `HULL`, or `SHELL`), and a positive `quantity_lbs`. Placement is guarded by a stack of rules. The source lot must be `PROCESSED` — unprocessed lots have nothing to store — else `ERR_INVALID_STATE`. The bin must be `AVAILABLE` once lazy fumigation clearance has run; a bin in `FUMIGATING` or `AERATING` rejects the placement with `ERR_BIN_FUMIGATION_ACTIVE`. The bin must admit the form: a `product_form` outside the bin's `allowed_product_forms` draws `ERR_BIN_PRODUCT_MISMATCH`. Capacity must hold with equality allowed: the bin's `occupied_lbs` plus the new `quantity_lbs` may equal but not exceed `capacity_lbs`, else `ERR_BIN_CAPACITY_EXCEEDED`. Finally, the plant will not warehouse more of a form than the lot produced: the cumulative placed weight of that `product_form` for that lot — across all bins and counting placements in every status, so weight already withdrawn or disposed still counts against the ceiling — may not exceed the lot's recorded output of that form, else `ERR_LOT_OUTPUT_EXCEEDED`; the recorded output of a form is the lot's `kernel_out_lbs` for `KERNEL`, `shell_out_lbs` for `SHELL`, `hull_out_lbs` for `HULL`, and — in-shell product still carrying its shell — `kernel_out_lbs` plus `shell_out_lbs` for `IN_SHELL`. A successful placement is created in `STORED` status with `remaining_lbs` initialized equal to `quantity_lbs`, `allocated_planned_lbs` at 0, and `placed_at` stamped from the logical clock; the bin's occupancy figures are recomputed.

Withdrawals pull stock back out on strict rotation. A withdrawal names a `bin_id`, a `product_form`, and a positive `quantity_lbs`, and the server consumes the bin's `STORED` placements of that form in first-in-first-out order — sorted by `placed_at` ascending, ties broken by `created_at` ascending and any remaining ties by creation order (earliest-created first), never by identifier. Each placement contributes its **free** weight, meaning `remaining_lbs` minus the `allocated_planned_lbs` already reserved by shipments, and the walk consumes from each placement only what is needed until the requested `quantity_lbs` is satisfied, possibly taking the last placement partially. If the free pool across all matching stored placements is smaller than the request, the withdrawal is rejected with `ERR_INSUFFICIENT_STORED`. The consumption is recorded on the withdrawal as `allocations`, an ordered list of the placements consumed with each entry's placement, its lot, and the quantity taken, and the withdrawal is stamped `withdrawn_at` from the logical clock. Placements whose `remaining_lbs` reaches zero — here or through shipment confirmation — transition from `STORED` to `WITHDRAWN`, and the bin's occupancy figures are recomputed. The fumigation lockout applies to withdrawals exactly as to placements: a bin not `AVAILABLE` after lazy clearance rejects the withdrawal with `ERR_BIN_FUMIGATION_ACTIVE`.

Placements and withdrawals may be listed — placements filtered by `bin_id`, `lot_id`, or `status`; withdrawals by `bin_id` — and read individually, as can bins themselves, which may also be listed filtered by `status`.

### 3.6. Fumigation and the Aeration Cycle

Bins are fumigated on schedule, and the schedule is protective: the aeration buffer that follows fumigation is part of the reservation. A `PlantAdmin` schedules a fumigation event for a `bin_id` with a `start_at` instant and a positive whole number of `aeration_hours`; the event is created in `SCHEDULED` status with `cleared_at` still null.

Fumigation windows are **closed intervals**, and they include the aeration tail. An event's effective end is its `cleared_at` when one has been set, otherwise its `start_at` plus its `aeration_hours`; the event occupies its bin from `start_at` through that effective end, **both endpoints inclusive**. A new event conflicts with an existing one on the same bin when the existing event is `SCHEDULED`, `ACTIVE`, or `AERATING` and the two closed intervals touch or overlap — the new start falls at or before the existing effective end while the new effective end falls at or after the existing start. Unlike the dryer rule, touching counts: a new event whose `start_at` is exactly an existing event's effective end conflicts and must instead begin strictly later. Conflicting schedules are rejected with `ERR_FUMIGATION_TIME_CONFLICT` (409). `CLEARED` and `CANCELLED` events no longer occupy the bin.

Starting a `SCHEDULED` event requires the logical clock to have reached its `start_at` (early starts draw `ERR_SCHEDULE_WINDOW_NOT_OPEN`) and the bin to be `AVAILABLE` — a start attempted while the bin is not `AVAILABLE` is rejected with `ERR_INVALID_STATE` (409). A successful start moves the event to `ACTIVE` and fires the fumigation cascade: the bin moves from `AVAILABLE` to `FUMIGATING` with its `fumigation_cleared_at` reset to null, every `STORED` placement in the bin moves to `FUMIGATION_HOLD`, and every `PLANNED` shipment whose allocations reference any of those placements moves to `BLOCKED`.

Ending the fumigation is a deliberate second step: beginning aeration moves the event from `ACTIVE` to `AERATING` and sets its `cleared_at` to the current logical clock plus the event's `aeration_hours`. The bin follows from `FUMIGATING` to `AERATING`, carrying the countdown on its `fumigation_cleared_at` field. Clearance itself is lazy, per §2.5: once the logical clock reaches `cleared_at` — discovered either when the clock is set or when any operation touches the bin — the event moves to `CLEARED`, the bin returns to `AVAILABLE` with `fumigation_cleared_at` reset to null, held placements return from `FUMIGATION_HOLD` to `STORED`, and `BLOCKED` shipments whose allocated placements are all stored again return to `PLANNED`. A `SCHEDULED` event may instead be cancelled to `CANCELLED`. Events may be listed filtered by `bin_id` or `status` and read individually. While a bin sits in `FUMIGATING` or `AERATING`, the lockout of §2.8 forbids placements, withdrawals, shipment creation, and shipment confirmation touching it — all rejected with `ERR_BIN_FUMIGATION_ACTIVE` after lazy clearance has been given its chance to run.

### 3.7. Buyer Contracts and Shipment Planning

Sell-side planning starts with a buyer contract. A `PlantAdmin` creates a contract for a `buyer_id` naming a `product_form` of `IN_SHELL` or `KERNEL`, a `size_spec`, a `max_defects_pct` defect ceiling (at least 0 and less than 1), a positive whole-cent `price_cents_per_lb`, and a positive `required_qty_lbs` total. The contract's `size_spec` may be `SPEC_20_22`, `SPEC_23_25`, `SPEC_25_27`, or `UNSIZED`; an `UNSIZED` contract accepts lots of any size spec, while a sized contract accepts only lots whose `size_spec` equals it exactly. Contracts are created in `OPEN` status with `reserved_qty_lbs` and `delivered_qty_lbs` both at 0 — the first summing `quantity_lbs` over the contract's `PLANNED` and `BLOCKED` shipments, the second over its `DELIVERED` ones. A `PlantAdmin` may suspend an `OPEN` contract to `SUSPENDED`, which bars new shipment planning while leaving existing reservations intact, and resume a `SUSPENDED` contract back to `OPEN`. Contracts close from `OPEN`, `SUSPENDED`, or `FULFILLED` to `CLOSED`, but only when `reserved_qty_lbs` is exactly zero — the plant will not close a contract with stock still reserved, and a close attempted with a non-zero reserved quantity is rejected with `ERR_INVALID_STATE` (409). Both `FULFILLED` and `CLOSED` are terminal.

A `PlantOperator` plans a shipment against a contract by naming the `contract_id`, the source `bin_id`, a positive `quantity_lbs`, and — under §2.7 — the `expected_contract_version`; a stale version is rejected with `ERR_STALE_CONTRACT_VERSION` (412). Planning requires the contract to be `OPEN` and the bin to be `AVAILABLE` after lazy clearance, else `ERR_BIN_FUMIGATION_ACTIVE`. The shipment draws stock of the contract's `product_form` from the bin using the same FIFO walk as a withdrawal — `STORED` placements of the matching form, oldest `placed_at` first with `created_at` as tie-break, each contributing only its free weight — except that planning **reserves** rather than consumes: each selected placement's `allocated_planned_lbs` rises by the reserved quantity while `remaining_lbs` stays put. If the free pool cannot cover the request, the planning is rejected with `ERR_INSUFFICIENT_STORED`. Two further gates apply at planning time. The sizing gate: when the contract's `size_spec` is anything but `UNSIZED`, every allocated placement's lot must carry exactly that `size_spec`, else `ERR_SPEC_MISMATCH`. The remaining-quantity gate: the contract's `reserved_qty_lbs` plus `delivered_qty_lbs` plus the new `quantity_lbs` may not exceed `required_qty_lbs`, else `ERR_CONTRACT_REMAINING_EXCEEDED`. Where several of these planning gates fail together, the order of report is fixed — the sizing gate first, then the remaining-quantity gate, then free-pool sufficiency — consistent with the category order of §2.8.

A planned shipment is created in `PLANNED` status with its `allocations` recorded — the ordered list of reserved placements, each entry naming the placement, its lot, and the reserved quantity — while the contract's `reserved_qty_lbs` rises by `quantity_lbs` and its `version` increments by one. Confirming a `PLANNED` shipment delivers it: the bin must be `AVAILABLE` after lazy clearance (`ERR_BIN_FUMIGATION_ACTIVE` otherwise) and no allocated placement may sit in `QUARANTINED` — such a shipment would already have been forced to `BLOCKED` by the cascades, and only `PLANNED` shipments confirm. Confirmation decrements each allocated placement's `remaining_lbs` by its allocated quantity, sends placements that reach zero from `STORED` to `WITHDRAWN`, releases the `allocated_planned_lbs` reservation on each, moves the shipment to `DELIVERED`, shifts the contract's `reserved_qty_lbs` down and `delivered_qty_lbs` up by `quantity_lbs`, recomputes the bin's occupancy figures, and — when delivered quantity reaches the contract's `required_qty_lbs` exactly — moves an `OPEN` contract to `FULFILLED`. Cancelling a `PLANNED` shipment is the gentler exit: it moves the shipment to `CANCELLED`, releases the `allocated_planned_lbs` reservations without touching any `remaining_lbs`, and lowers the contract's `reserved_qty_lbs` by `quantity_lbs`. Between those poles, the cascades of §2.10 can push a `PLANNED` shipment to `BLOCKED` the moment any allocated placement leaves `STORED`, and release it back to `PLANNED` once every allocated placement is `STORED` again. Shipments may be listed filtered by `contract_id`, `bin_id`, or `status`, and read individually; a `Buyer` caller sees only shipments of its own contracts, and contracts likewise list — filterable by `buyer_id` and `status` — and read with the same ownership scope.

### 3.8. Grower Settlement and Payment

Payment begins once a lot is `PROCESSED` and a kernel grade is on file. A `PlantAdmin` creates a settlement naming only the `lot_id`; against a lot that is not `PROCESSED`, or one lacking a recorded `KERNEL_GRADE` test, the creation is rejected with `ERR_INVALID_STATE`. At creation the settlement snapshots the lot's `graded_kernel_weight_lbs` onto its own field of the same name, copies the delivering grower from the lot onto `grower_id`, and prices the snapshot in the component-rounded discipline of §2.6. The effective moisture for pricing is the lot's `post_dry_moisture_pct` when one exists, otherwise its `intake_moisture_pct`; the moisture excess is the amount by which that effective moisture exceeds the 8.0 percent standard, or zero when it does not. Three components are computed, each rounded half-up to whole cents before any summation:

- `base_cents` — the snapshotted graded kernel weight multiplied by the grower's `base_price_cents_per_lb`.
- `premium_cents` — the already-rounded `base_cents` multiplied by the grower's `premium_rate_pct`, but only when the lot's `edible_kernel_pct` is at least 0.70, the premium grade bar; below the bar the premium is exactly zero.
- `moisture_deduction_cents` — the already-rounded `base_cents` multiplied by one-half of one percent for each point of moisture excess (a rate of 0.005 of base per excess point).

The settlement's `total_cents` is then the integer sum of the already-rounded components: `base_cents` plus `premium_cents` minus `moisture_deduction_cents`. New settlements are born in `DRAFT`.

The settlement lifecycle is a small ledger with explicit, compensating actions. Approving a `DRAFT` settlement moves it to `ISSUED` and adds its `total_cents` to the grower's `payable_outstanding_cents` — the grower now has money on the books. Voiding an `ISSUED` settlement is the exact compensation of approval: it moves the settlement back to `DRAFT` and subtracts the same `total_cents` from `payable_outstanding_cents`. Paying an `ISSUED` settlement moves it to `PAID`, subtracts `total_cents` from `payable_outstanding_cents`, adds it to the grower's `lifetime_paid_cents`, and — bubbling up per §2.10 — moves the settlement's lot from `PROCESSED` to `SETTLED`, the lot's terminal resting state alongside `DISPOSED`. Cancelling is available only from `DRAFT` and moves the settlement to `CANCELLED` with no balance effects. `PAID` and `CANCELLED` are terminal: actions attempted on a settlement already in either state are rejected with `ERR_ALREADY_TERMINAL`, while actions from any other wrong state draw `ERR_INVALID_STATE`. Settlements may be listed filtered by `lot_id`, `grower_id`, or `status`, and read individually; a `Grower` caller sees only its own.

### 3.9. Byproduct Sales of Hull and Shell

Hulls and shells leave the plant as saleable byproduct, tracked against plant-wide production rather than against any bin. A `PlantOperator` records a byproduct sale with a `product_form` of `HULL` or `SHELL`, a positive `quantity_lbs`, a positive whole-cent `price_cents_per_lb`, and a free-text `buyer_name` — byproduct counterparties are not registered `Buyer` entities. The sale's `total_cents` is the quantity multiplied by the price, rounded half-up to whole cents.

Stock accounting is a simple running reconciliation per form. The available stock of a form is the sum of the corresponding output — `hull_out_lbs` for `HULL`, `shell_out_lbs` for `SHELL` — over **all** completed processing runs plant-wide, minus the summed `quantity_lbs` of every byproduct sale of that form ever recorded. Sales are append-only: they are never reversed, so history never rewrites. A sale is allowed only when its `quantity_lbs` does not exceed the available stock of its form at that moment; overselling is rejected with `ERR_BYPRODUCT_STOCK_EXCEEDED`. Sales may be listed filtered by `product_form`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. The table below is a contract summary only: request fields, computed fields, side effects, and the guards behind each call are defined by the narratives in §2 and §3, not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/growers` | Register a grower with contracted pricing | PlantAdmin |
| GET | `/growers` | List growers (paginated) | PlantAdmin |
| GET | `/growers/{id}` | Read one grower; Grower role limited to own id | PlantAdmin, Grower |
| POST | `/buyers` | Register a buyer | PlantAdmin |
| GET | `/buyers` | List buyers (paginated) | PlantAdmin |
| GET | `/buyers/{id}` | Read one buyer; Buyer role limited to own id | PlantAdmin, Buyer |
| POST | `/lots` | Field lot intake; created in `RECEIVED` | IntakeOperator |
| GET | `/lots` | List lots, filterable by `grower_id` and `status`; Grower sees only own | PlantAdmin, IntakeOperator, LabTechnician, PlantOperator, Grower |
| GET | `/lots/{id}` | Read one lot; Grower limited to own lots | PlantAdmin, IntakeOperator, LabTechnician, PlantOperator, Grower |
| POST | `/lots/{id}/route` | Route a `GRADED` lot to in-shell or kernel processing | IntakeOperator |
| POST | `/lots/{id}/resample` | Re-open a `REJECTED` lot for re-sampling | IntakeOperator |
| POST | `/lots/{id}/dispose` | Dispose a `REJECTED` lot and its quarantined placements | IntakeOperator |
| POST | `/lab-tests` | Record a lab test; conditional required fields per `test_type` | LabTechnician |
| GET | `/lab-tests` | List lab tests, filterable by `lot_id` and `test_type` | PlantAdmin, LabTechnician, IntakeOperator, PlantOperator |
| GET | `/lab-tests/{id}` | Read one lab test | PlantAdmin, LabTechnician, IntakeOperator, PlantOperator |
| POST | `/processing-runs` | Create a hulling run for a routed lot (OCC on lot version) | PlantOperator |
| GET | `/processing-runs` | List processing runs, filterable by `lot_id` and `status` | PlantAdmin, PlantOperator |
| GET | `/processing-runs/{id}` | Read one processing run | PlantAdmin, PlantOperator |
| POST | `/processing-runs/{id}/start` | Start a `QUEUED` run | PlantOperator |
| POST | `/processing-runs/{id}/complete` | Complete a `RUNNING` run, recording yield outputs | PlantOperator |
| POST | `/processing-runs/{id}/cancel` | Cancel a `QUEUED` run | PlantOperator |
| POST | `/dryers` | Register a dryer | PlantAdmin |
| GET | `/dryers` | List dryers (paginated) | PlantAdmin, PlantOperator |
| POST | `/drying-batches` | Reserve a dryer window for a lot (half-open overlap rule) | PlantOperator |
| GET | `/drying-batches` | List drying batches, filterable by `dryer_id`, `lot_id`, and `status` | PlantAdmin, PlantOperator |
| GET | `/drying-batches/{id}` | Read one drying batch | PlantAdmin, PlantOperator |
| POST | `/drying-batches/{id}/start` | Start a `SCHEDULED` batch once the clock reaches its start | PlantOperator |
| POST | `/drying-batches/{id}/complete` | Complete a `DRYING` batch at/after its end, recording final moisture | PlantOperator |
| POST | `/drying-batches/{id}/cancel` | Cancel a `SCHEDULED` batch | PlantOperator |
| POST | `/bins` | Register a storage bin with allowed product forms | PlantAdmin |
| GET | `/bins` | List bins with computed capacity fields, filterable by `status` | PlantAdmin, PlantOperator |
| GET | `/bins/{id}` | Read one bin (`occupied_lbs`, `available_now_lbs`, `projected_available_lbs`) | PlantAdmin, PlantOperator |
| POST | `/placements` | Place processed product into a bin | PlantOperator |
| GET | `/placements` | List placements, filterable by `bin_id`, `lot_id`, and `status` | PlantAdmin, PlantOperator |
| GET | `/placements/{id}` | Read one placement | PlantAdmin, PlantOperator |
| POST | `/withdrawals` | Withdraw product from a bin, consuming stored placements FIFO | PlantOperator |
| GET | `/withdrawals` | List withdrawals, filterable by `bin_id` | PlantAdmin, PlantOperator |
| GET | `/withdrawals/{id}` | Read one withdrawal | PlantAdmin, PlantOperator |
| POST | `/fumigations` | Schedule a bin fumigation with aeration buffer (closed-interval rule) | PlantAdmin |
| GET | `/fumigations` | List fumigation events, filterable by `bin_id` and `status` | PlantAdmin, PlantOperator |
| GET | `/fumigations/{id}` | Read one fumigation event | PlantAdmin, PlantOperator |
| POST | `/fumigations/{id}/start` | Start a `SCHEDULED` fumigation (cascade: bin, placements, shipments) | PlantAdmin |
| POST | `/fumigations/{id}/begin-aeration` | End fumigation and start the aeration buffer | PlantAdmin |
| POST | `/fumigations/{id}/cancel` | Cancel a `SCHEDULED` fumigation | PlantAdmin |
| POST | `/contracts` | Create a buyer contract with sizing spec | PlantAdmin |
| GET | `/contracts` | List contracts, filterable by `buyer_id` and `status`; Buyer sees only own | PlantAdmin, Buyer, PlantOperator |
| GET | `/contracts/{id}` | Read one contract; Buyer limited to own | PlantAdmin, Buyer, PlantOperator |
| POST | `/contracts/{id}/suspend` | Suspend an `OPEN` contract (no new shipments) | PlantAdmin |
| POST | `/contracts/{id}/resume` | Resume a `SUSPENDED` contract | PlantAdmin |
| POST | `/contracts/{id}/close` | Close a contract with no reserved quantity | PlantAdmin |
| POST | `/shipments` | Plan a shipment against a contract from a bin (OCC on contract version; FIFO reservation) | PlantOperator |
| GET | `/shipments` | List shipments, filterable by `contract_id`, `bin_id`, and `status`; Buyer sees only own contracts' shipments | PlantAdmin, PlantOperator, Buyer |
| GET | `/shipments/{id}` | Read one shipment; Buyer limited to own contracts | PlantAdmin, PlantOperator, Buyer |
| POST | `/shipments/{id}/confirm` | Confirm a `PLANNED` shipment (delivers stock; may fulfill the contract) | PlantOperator |
| POST | `/shipments/{id}/cancel` | Cancel a `PLANNED` shipment (releases the reservation only) | PlantOperator |
| POST | `/settlements` | Create a grower settlement for a `PROCESSED`, kernel-graded lot | PlantAdmin |
| GET | `/settlements` | List settlements, filterable by `lot_id`, `grower_id`, and `status`; Grower sees only own | PlantAdmin, Grower |
| GET | `/settlements/{id}` | Read one settlement; Grower limited to own | PlantAdmin, Grower |
| POST | `/settlements/{id}/approve` | Issue a `DRAFT` settlement (grower payable rises) | PlantAdmin |
| POST | `/settlements/{id}/void` | Void an `ISSUED` settlement back to `DRAFT` (compensation) | PlantAdmin |
| POST | `/settlements/{id}/pay` | Pay an `ISSUED` settlement (lot becomes `SETTLED`) | PlantAdmin |
| POST | `/settlements/{id}/cancel` | Cancel a `DRAFT` settlement | PlantAdmin |
| POST | `/byproduct-sales` | Sell hull or shell byproduct stock | PlantOperator |
| GET | `/byproduct-sales` | List byproduct sales, filterable by `product_form` | PlantAdmin, PlantOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving); triggers lazy fumigation clearance | PlantAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are defined where the guarded behavior lives, in §2 and §3 — not repeated here. Two identifiers sit outside the per-resource catalogue: `ERR_NOT_FOUND` covers path ids of resource types without a dedicated not-found error — lab tests, placements, and withdrawals — as well as requests to undefined routes, and is also reported with HTTP 405 when a defined route receives an unsupported method; `ERR_INTERNAL` (500) covers unexpected server faults.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_GROWER_NOT_FOUND` | 404 |
| `ERR_BUYER_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_DRYER_NOT_FOUND` | 404 |
| `ERR_DRYING_BATCH_NOT_FOUND` | 404 |
| `ERR_BIN_NOT_FOUND` | 404 |
| `ERR_PROCESSING_RUN_NOT_FOUND` | 404 |
| `ERR_FUMIGATION_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_LOT_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALREADY_TERMINAL` | 409 |
| `ERR_AFLATOXIN_UNRESOLVED` | 422 |
| `ERR_BIN_FUMIGATION_ACTIVE` | 422 |
| `ERR_DRYER_TIME_CONFLICT` | 409 |
| `ERR_FUMIGATION_TIME_CONFLICT` | 409 |
| `ERR_SCHEDULE_WINDOW_NOT_OPEN` | 422 |
| `ERR_DRYING_REQUIRED` | 422 |
| `ERR_BIN_PRODUCT_MISMATCH` | 422 |
| `ERR_BIN_CAPACITY_EXCEEDED` | 422 |
| `ERR_SPEC_MISMATCH` | 422 |
| `ERR_SHRINK_NEGATIVE` | 422 |
| `ERR_LOT_OUTPUT_EXCEEDED` | 422 |
| `ERR_CONTRACT_REMAINING_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_STORED` | 422 |
| `ERR_BYPRODUCT_STOCK_EXCEEDED` | 422 |
| `ERR_INTERNAL` | 500 |

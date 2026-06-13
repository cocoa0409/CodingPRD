# Food Safety & Traceability API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Food Safety & Traceability platform, a back-office system that lets a food-manufacturing facility carry the genealogy of every lot it handles from supplier intake all the way through in-house production and, when something goes wrong, back out again as a mock recall trace. The platform is built around the obligations that the Food Safety Modernization Act places on a manufacturer: knowing who supplied each raw material, holding inbound material behind a certificate-of-analysis acceptance gate, monitoring critical control points such as cold-chain temperature, freezing suspect product on a moment's notice, and being able to answer "one up, one down" — what went into this lot, and where did this lot go — within minutes rather than days.

The domain is naturally a graph problem. A finished good is produced by drawing measured quantities from one or more released source lots, so the lots a facility holds form a directed acyclic genealogy in which finished lots point back at the raw materials they consumed. Much of the system's hardest behavior — recall exposure, allergen inheritance, the way a hold on one lot freezes everything downstream of it — is a traversal of that graph. Layered on top of the graph is a set of compliance gates (COA acceptance, supplier approval, HACCP excursion limits, first-expired-first-out rotation) that decide whether a lot may move to the next stage of its life.

Time in this system is deliberate, not wall-clock. Each facility owns a logical clock that advances only when an operator explicitly steps it forward, and expiration sweeps, excursion accruals, and "is this lot past its date" checks all read that logical clock. This determinism is what makes recall drills and shelf-life rotation reproducible. The sections below define the global contracts every endpoint obeys (Section 2) and then walk the business workflows in detail (Section 3), with the endpoint and error catalogues collected at the end.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, formats, and cross-cutting principles that apply across the entire API. The whole API is mounted under the `/traceability` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles, spelled precisely as follows: `QualityManager`, `ReceivingClerk`, `ProductionOperator`, and `SafetyAuditor`. A `QualityManager` owns certificate decisions, lot release and rejection, hold issuance and resolution, the setup of facilities, suppliers, ingredients, allergen profiles and zones, and advancing the facility clock. A `ReceivingClerk` receives raw-material lots, attaches supplier certificates, and books lots into storage zones. A `ProductionOperator` opens, finalizes, and aborts production runs, adds consumed-lot lines, and records critical-control-point readings. A `SafetyAuditor` has read-only oversight, including recall traces, hold orders, and genealogy.

All four roles are operator capacities rather than persisted entities. When `X-User-Role` is `QualityManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `ReceivingClerk`, when it is `ProductionOperator`, and when it is `SafetyAuditor`: in each case `X-User-ID` is an opaque operator identifier with no ownership relationship to any stored record, and authorization is decided purely from the role's permission set, never from a match between `X-User-ID` and a resource field.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, and it accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless an endpoint states otherwise, every list response is sorted by the resource's creation timestamp, `created_at`, in ascending order. The `meta` block of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Facility Clock

Most resources in the system carry a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on every mutation. The `version` field is an integer that begins at its initial value and increments by one with every modification to the resource; it is the basis for optimistic concurrency control described in Section 2.7. The same three-fractional-digit ISO 8601 UTC rendering used for `created_at` and `updated_at` also applies to every other datetime *value* field that the server computes or normalizes from an input instant before returning it — including the facility clock `current_utc`, a production run's `started_at`, a lot's `production_date`, `expiration_date`, and `effective_expiration_date`, and a storage booking's `start_utc` and `end_utc`; each is rendered as a full ISO 8601 UTC timestamp with three fractional digits and a trailing `Z` (for example `2026-01-11T00:00:00.000Z`), regardless of the precision of the original input.

One entity is deliberately leaner. An `AllergenProfile` is immutable after creation and therefore carries only `id` and `created_at`; it has no `updated_at` field and no `version` field. Every other entity — facilities, suppliers, ingredients, lots, certificates, production runs, consumed-lot lines, critical-control-point readings, hold orders, storage zones, and storage bookings — carries the full `id`, `created_at`, `updated_at`, and `version` set.

Time is not taken from the host clock. Each `Facility` owns a deterministic logical clock exposed as `current_utc`. At creation the clock is seeded to the supplied `initial_utc`, and from then on it advances only when an operator explicitly steps it forward. Every temporal decision in the system — whether a lot is past its expiration, whether a critical-control-point reading lies in the future, and the expiry sweep itself — reads the owning facility's `current_utc` rather than real time.

### 2.5. Hierarchical Consistency, Cascades, and Genealogy Propagation

Many operations in this system touch more than one record. When that happens, every secondary effect is part of the same atomic operation, and each mutated resource independently refreshes its `updated_at` and increments its `version`. There are three principal cascades.

The first cascade fires when a production run is finalized: inventory is drawn down from each source lot, any source lot whose remaining quantity reaches zero is marked terminal, and a brand-new finished lot is minted — three classes of mutation in one transaction, detailed in Section 3.4.

The second cascade governs holds. Issuing a hold freezes not only the directly targeted lot but every finished lot transitively downstream of it in the genealogy, and resolving a hold either thaws those lots or destroys them depending on the disposition. This propagation walks the genealogy graph, not any ordering of identifiers, and is detailed in Sections 3.6 and 3.7.

The third cascade is the supplier-suspension chain that runs when a certificate is rejected, described in Section 3.3. In all cascades, terminal lots are never re-mutated: a lot already in a terminal status is skipped by the freeze, the destroy, and the expiry sweep alike.

### 2.6. Nested Resource Retrieval and Path Validation

The entity topology is flat: every collection lives directly under `/traceability/<segment>` and relationships are expressed as foreign-key fields in request and response bodies rather than as nesting in the URL. A handful of read endpoints nonetheless place a parent identifier in the path — for example, listing the suppliers, ingredients, allergen profiles, zones, or critical-control-point readings that belong to a given parent. For any request whose path carries one or more resource identifiers, the system validates them left to right and rejects on the first identifier that does not resolve to an existing resource, returning the not-found error appropriate to that position (`ERR_FACILITY_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`, `ERR_COA_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, or `ERR_BOOKING_NOT_FOUND`). This existence check is evaluated after authentication and authorization but before any business rule.

### 2.7. Optimistic Concurrency Control

Two operations are guarded by optimistic concurrency control because they act on a parent whose state a concurrent writer may have already advanced.

Resolving a hold order requires the request body to carry `expected_hold_order_version`, the `version` of the target hold order that the client last observed. If that value does not match the hold order's current `version` — for instance because a prior writer has already resolved the hold, advancing its version since the client read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check is performed before any state precondition, so a resolution carrying a pre-resolution version becomes a deterministic stale-version rejection rather than a second resolution computed against outdated state.

Finalizing a production run requires the request body to carry `expected_production_run_version`, the `version` of the run that the client last observed. Adding a consumed-lot line to a run bumps that run's `version`; a finalize request that carries the version from before a line was added is therefore operating on a stale view of the bill of materials and is rejected with `ERR_STALE_VERSION` (HTTP 412) on the version check, before any inventory is drawn. This check is likewise performed before all other finalize preconditions. No endpoint other than hold resolution and run finalization takes a version field in its body.

### 2.8. Validation Ordering and Precedence

When several checks could fail on the same request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication of the headers comes first, yielding `ERR_MISSING_AUTH`. Role authorization comes second, yielding `ERR_FORBIDDEN_ROLE`. Path-identifier existence comes third, yielding the appropriate not-found error. Body well-formedness comes fourth: required body fields must be present and their types and enums valid — `received_qty` and `quantity` must be greater than zero, and `severity_rank` must lie within 1 through 5 — otherwise `ERR_INVALID_REQUEST`. Body foreign-key resolution and same-facility ownership come fifth, yielding `ERR_CROSS_FACILITY_REFERENCE` when a referenced entity belongs to a different facility. Lot-code uniqueness comes sixth, yielding `ERR_DUPLICATE_LOT_CODE`. The optimistic-concurrency version check comes seventh, yielding `ERR_STALE_VERSION`. The target-state check comes eighth, yielding the relevant not-in-state error. The remaining business-specific gates — supplier approval, hold freeze, certificate acceptance, expiry, first-expired-first-out, reading order, quantity sufficiency, interval validity, and zone capacity — follow in the order described in Sections 2.9 through 2.11 and Section 3, with their individual precedence stated where each rule is introduced.

### 2.9. Precision and Rounding

Quantities are tracked in base units. Wherever a quantity total is computed — the available quantity of a lot, the recall exposure quantity, and the capacity load of a storage booking — the result is rounded half up to three decimal places. For recall exposure in particular the rounding order is sum-then-round: every included quantity is accumulated at full precision and the single resulting total is rounded once, never rounded lot-by-lot and then summed. Excursion minutes are whole numbers obtained by taking the floor of an elapsed-minutes value. Supplier failure streaks and the held-lot count are plain integer counts. Expiration dates are computed by adding a whole number of days to a production date.

### 2.10. Supplier Approval and the Failure-Streak Protocol

Each `Supplier` carries an `approval_status` that is either `APPROVED` or `SUSPENDED`, initialized to `APPROVED` at registration, and a `failed_coa_streak` integer that begins at 0. The streak counts consecutive certificate rejections for that supplier. The third consecutive rejection suspends the supplier; more precisely, when the streak reaches three or more it flips `approval_status` to `SUSPENDED`. A second consecutive rejection (streak of two) does not. Any certificate acceptance resets the streak to 0, so only an unbroken run of rejections accumulates toward suspension. A supplier's `coa_required` flag, which defaults to true, declares whether inbound lots from that supplier must clear an accepted certificate before they may be released. Supplier approval is a receiving gate: a new raw-material lot may only be received from a supplier currently in `APPROVED` status, and an attempt to receive from a `SUSPENDED` supplier is rejected with `ERR_SUPPLIER_NOT_APPROVED`.

### 2.11. Cold-Chain Critical Limits, Expiration, and Capacity

Cold-chain monitoring rests on the storage parameters of each `Ingredient`: a `storage_target_c` setpoint in Celsius, a `storage_tolerance_c` allowed deviation that defaults to 2 degrees, and a `shelf_life_days` count used to derive expirations. A temperature reading is a deviation only when its distance from the target strictly exceeds the tolerance; a reading exactly at the tolerance boundary is still in spec. Excursion minutes accrue against a lot and, once the running total strictly exceeds the cumulative limit, an automatic temperature hold is raised — the exact accrual arithmetic and the limit value are given in Section 3.5.

Storage capacity is governed per zone. A `StorageZone` has a finite `capacity_units` and a `target_temp_c` setpoint; bookings into the zone occupy capacity over half-open time intervals, and the peak coincident occupancy may never exceed the zone's capacity. The interval and capacity arithmetic is detailed in Section 3.8.

## 3. Business Logic & Workflows

### 3.1. Facilities, Suppliers, Ingredients, and Allergen Profiles

The root of every data graph is a `Facility`, created by a `QualityManager` with a `name`, a `gln` (Global Location Number), and an `initial_utc` seed for its clock. The `gln` must be unique across all facilities. On creation the facility's `current_utc` is set equal to the supplied `initial_utc`. Thereafter a `QualityManager` advances the clock by supplying a `to_utc` instant; the new instant must be strictly greater than the current value, and a non-advancing or backward step is rejected with `ERR_CLOCK_NOT_MONOTONIC`. Advancing the clock also runs the expiration sweep described in Section 3.5.

A `QualityManager` registers a `Supplier` under a facility by supplying the owning `facility_id`, the supplier's legal `name`, and optionally the `coa_required` flag. On registration the supplier's `approval_status` is set to `APPROVED` and its `failed_coa_streak` to 0, as described in Section 2.10.

Ingredients carry the recipe and storage data for a material. A `QualityManager` defines an `Ingredient` with the owning `facility_id`, a `name`, the `storage_target_c` setpoint, optionally a `storage_tolerance_c` deviation (defaulting to 2 degrees), the `shelf_life_days` count, and optionally a list of `declared_allergen_codes` (defaulting to an empty list) naming the allergens intrinsic to the material, such as `MILK` or `SOY`. The `shelf_life_days` value is the number of days from production or receipt to expiration and is used to compute a lot's expiration when none is supplied.

Allergen severity is described by an `AllergenProfile`, registered by a `QualityManager` with the owning `facility_id`, a `code` such as `MILK`, `EGG`, `PEANUT`, `SOY`, or `WHEAT`, a human-readable `name`, and a `severity_rank` from 1 (lowest) to 5 (highest). The `code` must be unique per facility, and a `severity_rank` outside the 1-through-5 range fails body validation with `ERR_INVALID_REQUEST`. The severity rank is what decides, later, which allergen controls a multi-allergen lot: the higher rank wins.

### 3.2. Receiving a Lot and the Expiration Metric

Lots enter the system in one of two ways. Clients may directly receive only a raw-material lot; a finished lot is never posted by a client and is instead minted by production finalize (Section 3.4). A `ReceivingClerk` or a `QualityManager` receives a lot by supplying the `facility_id`, the `ingredient_id`, a `lot_code`, the `lot_kind` (which a client may set only to `RAW_MATERIAL`), the `received_qty` in base units, the `production_date`, optionally the originating `supplier_id` (which is null for in-house finished lots), and optionally an `expiration_date`. The `lot_code` must be unique within the pairing of facility and ingredient; a collision is rejected with `ERR_DUPLICATE_LOT_CODE`. Receiving a raw-material lot that names a supplier draws the supplier-approval gate of Section 2.10.

On receipt the lot's `status` is set to `RECEIVED`, its `available_qty` is initialized to the `received_qty`, and its `hold_status` is `FREE`. When the body omits `expiration_date`, it is computed as the `production_date` plus the ingredient's `shelf_life_days`. The lot's controlling expiration metric, `effective_expiration_date`, is set from the provisional rule: it equals the supplied `expiration_date` if one was given, otherwise the `production_date` plus the ingredient's `shelf_life_days`. The `coa_status` is set to `PENDING` when the originating supplier requires a certificate and the lot is raw material, and to `NOT_REQUIRED` otherwise. The lot's `effective_allergen_codes` is initialized to the ingredient's `declared_allergen_codes`, and its `controlling_allergen_code` is computed from that set as the code of highest severity rank, breaking ties by choosing the lexicographically smallest code, and is null when the set is empty. The lot's `cumulative_excursion_minutes` begins at 0.

The `effective_expiration_date` is deliberately distinct from the raw input `expiration_date`. While the certificate is not yet accepted — that is, while `coa_status` is `NOT_REQUIRED` or `PENDING` — the provisional metric above governs. Once a certificate on the lot is accepted, the metric is recomputed by the finalized rule: it becomes the `production_date` plus the smaller of the ingredient's `shelf_life_days` and the certificate's attested shelf life. Taking the smaller of the two can only shorten the lot's life, never extend it. Every downstream temporal gate — the release expiry check, the first-expired-first-out rotation check, and the clock expiry sweep — reads `effective_expiration_date`, never the raw `expiration_date`.

A lot's lifecycle status moves through `RECEIVED`, then to `RELEASED`, `REJECTED`, `CONSUMED`, `EXPIRED`, or `DESTROYED`. Releasing a lot is a `QualityManager` action that advances it from `RECEIVED` to `RELEASED`, making it consumable by production. Release requires, in order: the lot is in `RECEIVED` status (otherwise `ERR_LOT_NOT_RECEIVED`); the lot's `hold_status` is `FREE`, with a held lot rejected by `ERR_LOT_ON_HOLD` — this safety freeze precedes the certificate and expiry checks; if the supplier requires a certificate and the lot is raw material, its `coa_status` is `ACCEPTED`, otherwise `ERR_COA_NOT_ACCEPTED`; and the facility's `current_utc` is strictly earlier than the lot's `effective_expiration_date`, otherwise `ERR_LOT_EXPIRED`. A successful release sets `status` to `RELEASED` and increments the lot's `version`. Rejecting a lot is likewise a `QualityManager` action available only from `RECEIVED` (otherwise `ERR_LOT_NOT_RECEIVED`); it sets `status` to `REJECTED` and increments the `version`.

### 3.3. The Certificate of Analysis Acceptance Gate

A `CertificateOfAnalysis` records a supplier's lab attestation for a particular lot. A `ReceivingClerk` or `QualityManager` attaches a certificate by supplying the `lot_id` it covers, the `measured_allergen_codes` detected by lab testing (defaulting to an empty list), the `pathogen_pass` boolean indicating whether the pathogen panel passed, and the `declared_shelf_life_days` the supplier attests. On attachment the certificate's `status` is `PENDING`, the covered lot's `coa_status` is set to `PENDING`, and the certificate's `supplier_id` is copied from the lot rather than supplied by the client.

A `QualityManager` decides a pending certificate by supplying a `decision` of accept or reject; the certificate must be in `PENDING` status or the decision is rejected with `ERR_COA_NOT_PENDING`. Accepting a certificate enforces three further preconditions, each with its own error. First, the `measured_allergen_codes` must be a subset of the ingredient's `declared_allergen_codes`; if the lab detected an allergen the ingredient never declared, acceptance is blocked with `ERR_COA_ALLERGEN_UNDISCLOSED`. Second, `pathogen_pass` must be true, otherwise `ERR_COA_PATHOGEN_FAIL`. Third, the certificate's `declared_shelf_life_days` must be at least the ingredient's `shelf_life_days`; a shorter attested shelf life blocks acceptance with `ERR_COA_SHELF_LIFE_SHORT`.

An accepted certificate moves to `ACCEPTED` and produces several effects in one transaction: the covered lot's `coa_status` becomes `ACCEPTED`; the lot's `effective_expiration_date` is recomputed by the finalized rule of Section 3.2 (the production date plus the smaller of the ingredient shelf life and the certificate's attested shelf life); the supplier's `failed_coa_streak` is reset to 0; and the certificate's `version` is incremented.

Rejecting a certificate is the symmetric branch and is available only from `PENDING`. It sets the certificate's `rejection_reason` to `MANUAL`, sets the covered lot's `coa_status` to `REJECTED`, increments the supplier's `failed_coa_streak` by one, and increments the certificate's `version`. If that increment brings the supplier's `failed_coa_streak` to three or more, the supplier's `approval_status` flips to `SUSPENDED` in the same transaction — the second hop of the supplier-suspension cascade described in Section 2.10. The `rejection_reason` field, which is otherwise unset, takes one of the values `ALLERGEN_UNDISCLOSED`, `PATHOGEN_FAIL`, `SHELF_LIFE_SHORT`, or `MANUAL`; a manual reject records `MANUAL`.

### 3.4. Production Runs, the Bill of Materials, and Finalization

A `ProductionOperator` opens a `ProductionRun` for a finished good by supplying the `facility_id`, the recipe `ingredient_id` of the finished good, and a `planned_output_qty` in base units greater than zero. On opening, the run's `status` is `OPEN` and its `started_at` is stamped with the facility's `current_utc`. The bill of materials is assembled line by line: the operator adds a `ConsumedLot` line by supplying the parent `production_run_id`, the `source_lot_id` to draw from, and the `quantity` in base units greater than zero. Each added line increments the run's `version` by one — which is precisely why a stale finalize is caught by the optimistic-concurrency check of Section 2.7. The run also tracks an `output_lot_id`, which is null until the run is finalized.

Finalizing a run is a `ProductionOperator` action that advances it from `OPEN` to `FINALIZED`, and it is the most heavily gated operation in the system. The finalize body carries `expected_production_run_version`. The preconditions are evaluated in this order. The optimistic-concurrency version check comes first, rejecting a stale finalize with `ERR_STALE_VERSION` before anything else. Next, the run must hold at least one consumed-lot line, otherwise `ERR_NO_CONSUMED_LOTS`. Then every source lot referenced must be in `RELEASED` status, otherwise `ERR_SOURCE_LOT_NOT_RELEASED`. Then every source lot's `hold_status` must be `FREE`, otherwise `ERR_LOT_ON_HOLD`. Then no source lot may be past expiration at the facility's `current_utc` — that is, each source lot's `effective_expiration_date` must be strictly later than `current_utc` — otherwise `ERR_SOURCE_LOT_EXPIRED`. Then the first-expired-first-out rotation gate applies: a source lot may be consumed only if no other released, free, same-ingredient, same-facility lot has an earlier `effective_expiration_date`; bypassing an earlier-expiring lot is rejected with `ERR_FEFO_VIOLATION`. Ties in `effective_expiration_date` for the rotation comparison are broken by earlier `production_date` first, then by earlier `created_at`, and never by identifier. Finally, every line's `quantity` must not exceed its source lot's `available_qty`, otherwise `ERR_INSUFFICIENT_LOT_QTY`. A run that is not `OPEN` cannot be finalized, aborted, or have a line added, which surfaces as `ERR_RUN_NOT_OPEN`.

When all gates pass, finalize executes as one atomic draw. Each consumed-lot line is applied in order of its own `created_at` ascending — never by lot identifier. For each line the source lot's `available_qty` is reduced by the line's `quantity`, floored at zero. The available quantity of a source lot is, in steady state, its `received_qty` minus the sum of all consumed-lot quantities drawn from it by finalized runs, floored at zero; quantities drawn by open or aborted runs never count. Any source lot whose `available_qty` reaches exactly zero after its draw and that is currently `RELEASED` transitions to `CONSUMED`, the second hop of this cascade. All quantity arithmetic is rounded half up to three decimal places.

In the same transaction the run mints its finished lot. The new lot is created with `status` `RECEIVED`, `lot_kind` `FINISHED`, a null `supplier_id`, a `lot_code` formed as the literal prefix `FIN-` followed by the production run's identifier (which is unique within the facility-and-ingredient pairing), `received_qty` and `available_qty` both set to the run's `planned_output_qty`, `hold_status` `FREE`, and `coa_status` `NOT_REQUIRED`. The finished lot's `effective_allergen_codes` is the distinct union of the output ingredient's `declared_allergen_codes` and the `effective_allergen_codes` of every source lot; its `controlling_allergen_code` is then the code in that union of highest `severity_rank`, breaking ties by the lexicographically smallest code, and is null when the union is empty. An undeclared cross-contact — an allergen present in a source lot but absent from the output ingredient's declared codes — does not block finalize; the inherited code is simply carried on the finished lot so downstream allergen-control reads can see it. The finished lot's `production_date` is set to the run's `started_at`, and both its `expiration_date` and `effective_expiration_date` are set to `started_at` plus the ingredient's `shelf_life_days`. The run's `status` becomes `FINALIZED`, its `output_lot_id` is set to the minted lot's id, and its `version` increments.

Aborting a run is the sibling branch from `OPEN`, available to a `ProductionOperator` and permitted only while the run is `OPEN` (otherwise `ERR_RUN_NOT_OPEN`). An abort draws no inventory — the consumed-lot lines have no effect on any `available_qty` — sets the run's `status` to `ABORTED`, and increments its `version`.

### 3.5. Temperature Monitoring, Excursion Accrual, and the Expiry Sweep

A `ProductionOperator` or `QualityManager` records a temperature reading against a lot by supplying the `lot_id`, the `ccp_type` (which is `TEMPERATURE`), the `measured_value_c` in Celsius, and the `measured_at` timestamp of the reading. The reading's timeline must be monotonic: `measured_at` must be at or before the facility's `current_utc` and strictly later than the most recent prior reading's `measured_at` for that lot. A reading whose `measured_at` is in the future relative to the clock, or at or before the lot's latest prior reading, collides with the timeline and is rejected with `ERR_READING_OUT_OF_ORDER`.

Each reading is classified and may accrue excursion minutes. The reading's `classification` is `DEVIATION` when the absolute difference between `measured_value_c` and the ingredient's `storage_target_c` is strictly greater than the ingredient's `storage_tolerance_c`; a difference exactly equal to the tolerance is `IN_SPEC`. When the reading is a `DEVIATION` and the lot already has a prior reading, the reading's `excursion_minutes` is the whole number of minutes between the prior reading's `measured_at` and this reading's `measured_at`, taken as the floor of the elapsed minutes; the prior reading is the lot's most recent earlier reading ordered by `measured_at` ascending with ties broken by `created_at` ascending. When the reading is `IN_SPEC`, or when it is a `DEVIATION` but there is no prior reading, its `excursion_minutes` is 0. The accrued minutes are added to the lot's `cumulative_excursion_minutes`.

The cumulative total drives an automatic safety hold. Once a lot's `cumulative_excursion_minutes` strictly exceeds 120 minutes, the system automatically issues a hold order against that lot with reason `TEMPERATURE_EXCURSION`. The boundary is strict: a cumulative total of exactly 120 minutes does not trigger a hold, while 121 does.

The expiry sweep runs whenever the facility clock advances to a new `to_utc` (Section 3.1). Every lot that is in `RELEASED` status and whose `hold_status` is `FREE` and whose `effective_expiration_date` is at or before the new clock value transitions to `EXPIRED` and has its `version` incremented. A held lot is frozen and is deliberately skipped by the sweep even if its date has passed, since a held lot must not change status out from under an active investigation.

### 3.6. Issuing a Hold and Freezing the Genealogy

A `QualityManager` issues a `HoldOrder` by supplying the `facility_id`, the `target_lot_id` of the directly held lot, and a `reason` drawn from `ALLERGEN`, `PATHOGEN`, `TEMPERATURE_EXCURSION`, `RECALL`, or `OTHER`. Temperature holds are also raised automatically by the excursion logic of Section 3.5; those carry reason `TEMPERATURE_EXCURSION`.

On issue, the hold computes its covered set once and pins it. The covered set is the target lot together with every finished lot transitively downstream of the target through finalized consumed-lot edges — the one-down closure of the genealogy. Every lot in the covered set that is not already in a terminal status has its `hold_status` set to `HELD`. The hold records the number of distinct lots in the covered set as `held_lot_count`, a snapshot taken at issue time, and its `status` is set to `ACTIVE`. Covered-set membership is a property of the genealogy, not of any identifier ordering. A lot's `hold_status` is `HELD` whenever any active hold order covers it, directly or through genealogy, and `FREE` otherwise.

### 3.7. Resolving a Hold: Release versus Dispose

A `QualityManager` resolves an active hold by supplying a `disposition` of release or dispose together with `expected_hold_order_version`. The version check of Section 2.7 is applied first, then the hold must be in `ACTIVE` status, otherwise `ERR_HOLD_NOT_ACTIVE`. The two dispositions are parallel branches with divergent effects.

A release disposition sets the hold's `disposition` to `RELEASED` and its `status` to `RELEASED`, then recomputes the `hold_status` of every lot in the covered set: a lot becomes `FREE` if no other active hold still covers it, and remains `HELD` if some other active hold does. The hold's `version` then increments.

A dispose disposition sets the hold's `disposition` to `DISPOSED` and its `status` to `DISPOSED`, then destroys product. Every lot in the covered set that is not already terminal transitions to `DESTROYED` and has its `available_qty` set to zero. Because the covered set already contains every finished lot transitively downstream of the target, this single pass destroys the directly held lot and all of its downstream descendants together — the transitive genealogy is destroyed as one unit. The hold's `version` then increments. Disposing a hold is the system event that drives covered lots from `RELEASED` to `DESTROYED`, and equally drives a still-`RECEIVED` covered lot to `DESTROYED`; in both cases the lot's `available_qty` is zeroed and its `version` incremented.

### 3.8. Cold Storage Zones and Interval Bookings

A `QualityManager` creates a `StorageZone` with the owning `facility_id`, a `zone_code` unique within the facility, a `capacity_units` ceiling greater than zero, and a `target_temp_c` setpoint. The `capacity_units` is the maximum aggregate occupancy that time-overlapping bookings may impose on the zone at any single instant.

A `QualityManager` or `ReceivingClerk` books a lot into a zone by supplying the `lot_id` occupying the zone, a `start_utc`, an `end_utc`, and the `capacity_units` this booking occupies (greater than zero). The booking owns the half-open interval that begins at `start_utc` inclusive and ends at `end_utc` exclusive. The interval must be valid — `end_utc` strictly greater than `start_utc` — otherwise `ERR_INVALID_INTERVAL`.

Capacity is checked as a peak coincident load rather than a whole-interval sum. Two bookings on the same zone overlap when the candidate's start is strictly before the existing booking's end and the existing booking's start is strictly before the candidate's end; because the intervals are half-open, two bookings that merely touch at an endpoint — where one ends exactly when the other begins — do not overlap. For every instant inside the candidate's interval, the coincident load is the candidate's `capacity_units` plus the sum of the `capacity_units` of every existing booking that also covers that instant. If at any such overlapping sub-interval the summed capacity, including the candidate, exceeds the zone's `capacity_units`, the booking is rejected with `ERR_ZONE_CAPACITY_EXCEEDED`. The capacity comparison rounds half up to three decimal places. The booking carries the parent `zone_id`.

### 3.9. The Mock Recall Trace

A `QualityManager` or `SafetyAuditor` runs a one-up/one-down mock recall trace against any lot. The trace reports the `recalled_lot_id`, the `one_up_source_lot_ids`, the `one_down_finished_lot_ids`, the `exposure_variant`, and the `exposure_qty`. The genealogy is a directed acyclic graph in which an edge from a source lot to a finished lot exists exactly when a consumed-lot line of a finalized run links them; the graph is cycle-free because a finished lot only ever consumes lots that existed before its run's `started_at`.

The one-up set, `one_up_source_lot_ids`, is the immediate source lots one hop up from the recalled lot — the direct consumed-lot parents of the recalled lot — and is empty when the recalled lot is raw material. The one-down set, `one_down_finished_lot_ids`, is the transitive closure of finished lots reachable downstream from the recalled lot. When traversing children, the order is by consumed-lot `created_at` ascending and then by lot `created_at` ascending, never by identifier.

The exposure quantity has two variants, chosen by whether the recalled lot is currently covered by a disposed hold. When the recalled lot is not covered by any disposed hold at trace time, the provisional variant applies: `exposure_variant` reflects the provisional case, and `exposure_qty` is the sum of `received_qty` over all downstream finished lots in the closure — the worst case in which every produced unit is assumed still in commerce. When the recalled lot is covered by a disposed hold at trace time, the finalized variant applies: `exposure_qty` is the sum of `received_qty` over the downstream finished lots in the closure excluding any currently in `DESTROYED` status, netting out the units already pulled. In both variants the quantities are accumulated at full precision and the single total is then rounded half up to three decimal places.

## 4. Endpoint Definitions

Operations that create a new standalone resource return a `201 Created` status code. Operations that retrieve a resource or a list, and operations that drive an existing resource through a state transition (release, reject, decide, finalize, abort, resolve, clock advance), return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/traceability/facilities` | Create a facility with a deterministic clock seeded by initial_utc | QualityManager |
| GET | `/traceability/facilities/{id}` | Get a facility | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/facilities/{id}/clock` | Advance the facility clock; sweep released free lots into expired | QualityManager |
| POST | `/traceability/suppliers` | Register a supplier under a facility | QualityManager |
| GET | `/traceability/suppliers/{id}` | Get a supplier | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| GET | `/traceability/facilities/{id}/suppliers` | List suppliers under a facility | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/ingredients` | Define an ingredient with storage limits and allergen profile | QualityManager |
| GET | `/traceability/facilities/{id}/ingredients` | List ingredients under a facility | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/allergen-profiles` | Register an allergen profile for a facility | QualityManager |
| GET | `/traceability/facilities/{id}/allergen-profiles` | List allergen profiles under a facility | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/lots` | Receive a raw-material lot | ReceivingClerk, QualityManager |
| GET | `/traceability/lots/{id}` | Get a lot with computed fields | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| GET | `/traceability/lots` | List lots, filterable by facility_id, supplier_id, ingredient_id, status | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/lots/{lid}/release` | QC-release a received lot for consumption | QualityManager |
| POST | `/traceability/lots/{lid}/reject` | QC-reject a received lot | QualityManager |
| GET | `/traceability/lots/{lid}/recall-trace` | One-up/one-down mock recall trace with exposure quantity | QualityManager, SafetyAuditor |
| POST | `/traceability/coa` | Attach a supplier certificate to a lot | ReceivingClerk, QualityManager |
| GET | `/traceability/coa/{id}` | Get a certificate of analysis | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| GET | `/traceability/coa` | List certificates, filterable by lot_id and supplier_id | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/coa/{cid}/decide` | Accept or reject a pending certificate | QualityManager |
| POST | `/traceability/production-runs` | Open a production run for a finished good | ProductionOperator |
| GET | `/traceability/production-runs/{id}` | Get a production run | QualityManager, ProductionOperator, SafetyAuditor |
| GET | `/traceability/production-runs` | List production runs, filterable by facility_id, ingredient_id, output_lot_id | QualityManager, ProductionOperator, SafetyAuditor |
| POST | `/traceability/production-runs/{rid}/consumed-lots` | Add a bill-of-materials line drawing from a source lot | ProductionOperator |
| GET | `/traceability/consumed-lots/{id}` | Get a consumed-lot line | QualityManager, ProductionOperator, SafetyAuditor |
| GET | `/traceability/consumed-lots` | List consumed-lot lines, filterable by production_run_id and source_lot_id | QualityManager, ProductionOperator, SafetyAuditor |
| POST | `/traceability/production-runs/{rid}/finalize` | Finalize an open run: draw inventory and mint the finished lot | ProductionOperator |
| POST | `/traceability/production-runs/{rid}/abort` | Abort an open run with no inventory effect | ProductionOperator |
| POST | `/traceability/ccp-readings` | Record a temperature CCP reading; classify and accrue excursion | ProductionOperator, QualityManager |
| GET | `/traceability/lots/{id}/ccp-readings` | List a lot's CCP readings | QualityManager, ProductionOperator, SafetyAuditor |
| POST | `/traceability/hold-orders` | Issue a hold on a target lot and freeze its downstream genealogy | QualityManager |
| GET | `/traceability/hold-orders/{id}` | Get a hold order | QualityManager, SafetyAuditor |
| GET | `/traceability/hold-orders` | List hold orders, filterable by facility_id, target_lot_id, status | QualityManager, SafetyAuditor |
| POST | `/traceability/hold-orders/{hid}/resolve` | Resolve an active hold by release or dispose | QualityManager |
| POST | `/traceability/zones` | Create a cold-storage zone with finite aggregate capacity | QualityManager |
| GET | `/traceability/zones/{id}` | Get a storage zone | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| GET | `/traceability/facilities/{id}/zones` | List zones under a facility | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| POST | `/traceability/zones/{zid}/bookings` | Book a lot into a zone for a half-open interval | QualityManager, ReceivingClerk |
| GET | `/traceability/bookings/{id}` | Get a storage booking | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |
| GET | `/traceability/bookings` | List storage bookings, filterable by zone_id and lot_id | QualityManager, ReceivingClerk, ProductionOperator, SafetyAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLIER_NOT_FOUND` | 404 Not Found |
| `ERR_INGREDIENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_COA_NOT_FOUND` | 404 Not Found |
| `ERR_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_FACILITY_REFERENCE` | 409 Conflict |
| `ERR_DUPLICATE_LOT_CODE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_COA_NOT_PENDING` | 409 Conflict |
| `ERR_COA_ALLERGEN_UNDISCLOSED` | 409 Conflict |
| `ERR_COA_PATHOGEN_FAIL` | 409 Conflict |
| `ERR_COA_SHELF_LIFE_SHORT` | 409 Conflict |
| `ERR_COA_NOT_ACCEPTED` | 409 Conflict |
| `ERR_LOT_NOT_RECEIVED` | 409 Conflict |
| `ERR_LOT_ON_HOLD` | 409 Conflict |
| `ERR_LOT_EXPIRED` | 409 Conflict |
| `ERR_SUPPLIER_NOT_APPROVED` | 403 Forbidden |
| `ERR_RUN_NOT_OPEN` | 409 Conflict |
| `ERR_NO_CONSUMED_LOTS` | 409 Conflict |
| `ERR_SOURCE_LOT_NOT_RELEASED` | 409 Conflict |
| `ERR_SOURCE_LOT_EXPIRED` | 409 Conflict |
| `ERR_INSUFFICIENT_LOT_QTY` | 409 Conflict |
| `ERR_FEFO_VIOLATION` | 409 Conflict |
| `ERR_READING_OUT_OF_ORDER` | 409 Conflict |
| `ERR_HOLD_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLOCK_NOT_MONOTONIC` | 409 Conflict |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_INTERVAL` | 409 Conflict |
| `ERR_ZONE_CAPACITY_EXCEEDED` | 409 Conflict |

# Thermoforming & Vacuum-Form Plant API — Product Requirements Document

## 1. Introduction

A custom thermoforming operation lives and dies by traceability. Sheet arrives from suppliers as virgin lot stock in gauges measured to the thousandth of a millimetre; trim and skeletal waste are ground back into regrind that may — or may not — be blended back into production depending on the cleanliness grade of the product being formed; tools graduate from cheap prototype molds to rated production assets only after qualification; and every order carries both a schedule dimension and a quality dimension that move independently of one another. This document specifies the REST API that acts as the plant's system of record for all of it: material sourcing, the regrind loop, tool lifecycle, packaging approval, production orders, forming runs, inspection, secondary assembly, and the cleanliness certificates that gate movement between stages.

The API is built around two cross-cutting disciplines. The first is **quota discipline**: virgin lots and regrind batches are finite mass pools that are reserved against orders, consumed by completions, and released on cancellation, with conservation invariants that must hold bit-exactly after every mutation. The second is **compliance discipline**: a three-tier cleanliness model (industrial, food, medical) governs which materials, tools, stations, booths, and packaging may touch which orders; certificates expire against a server-side logical clock; and segregation-of-duties rules ensure that no operator both creates and certifies the same regrind batch, or both records and dispositions the same inspection. Time itself is explicit in this system: certificate validity and all scheduling comparisons are evaluated against a logical clock that starts at a fixed instant and advances only under test control, never silently against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes seven role names, spelled exactly as follows: `MaterialsPlanner`, `ToolingEngineer`, `PackagingEngineer`, `PlantManager`, `ProductionScheduler`, `QualityInspector`, and `Any`. Their remits: `MaterialsPlanner` owns virgin sheet sourcing, the regrind pool, and scrap certification; `ToolingEngineer` owns tool build, the prototype-to-production step, and drawing revision; `PackagingEngineer` drafts custom and stock packaging specs but cannot approve them; `PlantManager` is the final authority on custom packaging approval; `ProductionScheduler` owns production orders, material allocations, machine resources, forming runs, and assembly tasks; `QualityInspector` records and dispositions quality inspections and issues cleanliness certificates; `Any` is a shorthand meaning that any authenticated role may use the read endpoints and advance the logical clock.

For every role in this system — `MaterialsPlanner`, `ToolingEngineer`, `PackagingEngineer`, `PlantManager`, `ProductionScheduler`, `QualityInspector`, and `Any` alike — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on certain resources where accountability matters: as `created_by_user_id` and `decided_by_user_id` on a regrind batch, as `decided_by_user_id` on a packaging spec, and as `recorded_by_user_id` and `dispositioned_by_user_id` on a quality inspection. Segregation-of-duties checks compare those recorded identifiers against the `X-User-ID` of the incoming request; no `X-User-ID` is ever compared to any entity's `id`.

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
- A request that matches no defined route, or uses a method the route does not support, is likewise rejected with `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to the nearest bound rather than rejected, while a value that does not parse as an integer is `ERR_INVALID_REQUEST`. The `offset` parameter specifies how many items to skip and defaults to 0; a negative `offset` is clamped to 0, and a non-integer `offset` is likewise `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation (insertion) order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All primary resources — material lots, regrind batches, tools, packaging specs, production orders, material allocations, machine resources, forming runs, quality inspections, and assembly tasks — share a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation while `updated_at` refreshes on every mutation. `version` is an integer that starts at 1 at creation and increments by exactly one on every successful mutation of the resource, including mutations driven by system cascades rather than direct client action.

Two resources are deliberately lighter: a scrap record and a cleanliness certificate carry only `id` and `created_at`. Both `updated_at` and `version` are absent from these two resources — they are immutable records once written, and nothing on them ever increments.

### 2.5. Cleanliness Grades, Certificates, and the Logical Clock

The plant recognizes three cleanliness grades, ranked `INDUSTRIAL` (lowest) below `FOOD` below `MEDICAL` (highest). Wherever this document says one grade must be "at least" another, it means a comparison of these ranks. Grades attach to lots (as a release requirement), regrind batches (as source and certified grades), tools, packaging specs, machine resources, and orders.

A **cleanliness certificate** is a polymorphic attestation issued by a `QualityInspector`. Its `subject_type` is one of `MATERIAL_LOT`, `REGRIND_BATCH`, `TOOL`, or `PACKAGING_SPEC`, and its `subject_id` is the `id` of an entity of that type — there is no foreign-key prefix; the join runs through the pair of fields, and certificates for a given subject are retrievable by filtering the certificate list on `subject_type` and `subject_id`. Each certificate also carries the certified `grade`, the issuing laboratory or authority in `cert_body`, an `issued_at` instant, and an `expires_at` instant that must be later than `issued_at`. A certificate is valid at logical time T when T falls in the half-open interval from `issued_at` (inclusive) to `expires_at` (exclusive): it becomes valid exactly at its issuance instant and is already invalid at exactly its expiry instant.

All time-dependent evaluation in the system runs against a **server logical clock**. At startup the clock reads exactly 2026-05-01T00:00:00Z; it never falls back to wall-clock time. The clock advances only through an administrative, test-driving capability — available to any authenticated role — that sets the clock to a supplied `to_iso8601` instant and returns the new reading as `current_utc`; the returned `current_utc` echoes the supplied `to_iso8601` string verbatim, and the clock may be set to any parseable instant, earlier or later than the current reading, with no monotonicity constraint. Every certificate-validity comparison and every scheduling comparison in this document uses this clock.

Wherever a rule requires "a currently valid certificate at grade at least X" and no such certificate exists — because none was ever issued at a sufficient grade, or because the qualifying one has expired at the current logical time — the rejection is `ERR_CERTIFICATE_INVALID` (HTTP 422).

### 2.6. Measurement Precision, Rounding, and Plant-Wide Constants

Decimal discipline is uniform across the plant. All monetary values are rounded half-up to exactly two decimal places. All sheet-mass and scrap-mass values are rounded half-up to exactly three decimal places. Wall-thickness readings are rounded half-up to the nearest 0.001 mm per measurement before any aggregation, and wall deviation percentages are rounded half-up to two decimal places. Two intermediate values carry finer precision: the per-shot amortization rate of a production tool is rounded half-up to four decimal places, and the per-run machine-cost component inside final costing is rounded half-up to four decimal places before being summed.

Five plant-wide constants appear throughout the business rules:

- The **trim allowance** adds 18 percent to nominal part mass when planning material: an order's sheet requirement is its ordered quantity times its nominal per-part mass scaled by a factor of 1.18.
- A fixed **setup fee** of 250.00 is charged on every order's cost, both provisional and final.
- Regrind is valued at 60 percent of the reference virgin cost when costing material.
- A prototype tool may accumulate at most 500 planned or ordered shots before its economics are exhausted; completing a prototype build materializes this 500-shot limit on the tool.
- Inspection booths require a 30-minute turnover when a food- or medical-grade session follows an industrial-grade session.

Regrind blending is capped by the order's cleanliness grade: an `INDUSTRIAL` order may draw at most 40 percent of its required material mass from regrind, a `FOOD` order at most 15 percent, and a `MEDICAL` order nothing at all — the medical cap is zero, so any regrind allocation against a medical order violates the cap.

### 2.7. Optimistic Concurrency Control on Order Staging

Exactly one endpoint in the API participates in optimistic concurrency control: the staging action on a production order. A staging request must carry `expected_production_order_version`, a non-optional input holding the `version` of the order as the client last observed it. If that value no longer matches the order's current `version` — for example because a material allocation was created or released against the order after the client's read, each of which advances the order's `version` — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the order before staging. No other endpoint accepts a version field; requests to any other operation must not carry one.

### 2.8. Resource Identification and Existence Checking

The resource topology is flat: every resource is addressed at the top level by its own `id`, and cross-references travel in request bodies and query parameters rather than through URL nesting. When a request references resources — path identifiers first, in left-to-right order, then identifiers referenced inside the request body — each must exist, or the request is rejected with the 404 error specific to the missing resource: `ERR_MATERIAL_LOT_NOT_FOUND`, `ERR_REGRIND_BATCH_NOT_FOUND`, `ERR_TOOL_NOT_FOUND`, `ERR_PACKAGING_SPEC_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_MACHINE_RESOURCE_NOT_FOUND`, `ERR_FORMING_RUN_NOT_FOUND`, `ERR_SCRAP_RECORD_NOT_FOUND`, `ERR_QUALITY_INSPECTION_NOT_FOUND`, `ERR_ASSEMBLY_TASK_NOT_FOUND`, or `ERR_CERTIFICATE_NOT_FOUND`. For a certificate issuance, the polymorphic subject must exist as an entity of the declared `subject_type`; a `subject_id` naming no such entity yields the not-found error of that subject kind.

### 2.9. Validation Precedence

When several rules could reject the same request, checks are evaluated in a fixed priority order, and the earliest failing check determines the error returned. The order is:

1. **User context** — the `X-User-ID` and `X-User-Role` headers are present and non-empty (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the role is permitted on this endpoint (`ERR_FORBIDDEN_ROLE`).
3. **Request schema** — required fields are present, enum values are legal, numeric constraints hold (positive where required, non-negative where required), conditional fields are supplied exactly when required, and range inversions are absent (`ERR_INVALID_REQUEST`).
4. **Existence** — path identifiers and body-referenced identifiers resolve, left to right (the resource-specific 404 errors).
5. **OCC freshness** — where applicable, the expected version matches (`ERR_STALE_VERSION`).
6. **State legality** — the target entity is in a legal from-state for the requested transition (the 409 state errors, such as `ERR_INVALID_ORDER_STATE`).
7. **Cleanliness compatibility** — grade-rank comparisons between order, spec, lot or batch certificate, tool, station, and booth (`ERR_GRADE_INCOMPATIBLE`).
8. **Temporal rules** — window overlaps, the booth turnover buffer, and certificate time-validity at the current logical time (`ERR_STATION_WINDOW_OVERLAP`, `ERR_BOOTH_WINDOW_OVERLAP`, `ERR_BOOTH_BUFFER_VIOLATION`, `ERR_CERTIFICATE_INVALID`).
9. **Domain constraints** — resin matching, gauge matching, blend caps, prototype rules, segregation of duties, disposition-measurement consistency, assembly sequencing, and pack gates.
10. **Material sufficiency** — source pools actually hold the requested mass (`ERR_INSUFFICIENT_MATERIAL`).

The practical consequence is that earlier failures mask later ones: a request with a malformed body is rejected as `ERR_INVALID_REQUEST` before any state check runs; a stale staging attempt surfaces `ERR_STALE_VERSION` before material coverage is ever measured; and a grade-incompatible certificate that is also expired surfaces `ERR_GRADE_INCOMPATIBLE` (the rank check at priority 7) rather than `ERR_CERTIFICATE_INVALID` (the time check at priority 8).

The schema tier's conditional-field rules are worth stating in full: `lot_id` is required exactly when `source_type` is `VIRGIN_LOT` and must be null otherwise; `regrind_batch_id` is required exactly when `source_type` is `REGRIND` and must be null otherwise; `insert_part_code` is required exactly when `task_type` is `INSERT`; `certified_grade` is required on a batch decision unless the decision is a rejection; `scrapped_qty` is required exactly when the `disposition` is `SCRAP`; and `forming_run_id` is required exactly when `inspection_type` is `FIRST_ARTICLE` and must be null for `FINAL`. Range rules require `spec_min_wall_mm` no greater than `spec_nominal_wall_mm`, `expires_at` later than `issued_at`, `planned_end` later than `planned_start`, `scheduled_end` later than `scheduled_start`, and `max_gauge_mm` no less than `min_gauge_mm`.

## 3. Business Logic & Workflows

### 3.1. Virgin Sheet Intake and Lot Certification

A `MaterialsPlanner` receives virgin sheet into the plant by registering a material lot with its supplier identifier `lot_code`, its `resin_type` — one of `PETG`, `HIPS`, `ABS`, `PP`, or `PC`, immutable once created — the sheet thickness `gauge_mm` in millimetres to three decimal places, the minimum certification grade needed to release the lot as `cleanliness_grade_required`, the received mass `quantity_kg`, and the purchase price `unit_cost_per_kg`. Gauge, quantity, and unit cost must all be positive. A new lot enters `QUARANTINE` with `allocated_kg` and `consumed_kg` both at zero.

Release from quarantine is a side effect of certification, not a direct action. When a `QualityInspector` issues a cleanliness certificate whose `subject_type` is `MATERIAL_LOT` and whose `subject_id` names the lot, and the certificate's `grade` is at least the lot's `cleanliness_grade_required`, and the certificate is currently valid at the logical time of issuance, the lot automatically transitions `QUARANTINE` → `CERTIFIED`, refreshing its `updated_at` and advancing its `version` by one.

Three derived masses track every lot. `allocated_kg` is the sum of `qty_kg` over the lot's allocations in `RESERVED` or `REVIEW` status; `consumed_kg` is the sum over its `CONSUMED` allocations; and `available_kg` is always exactly `quantity_kg` minus `allocated_kg` minus `consumed_kg`. This invariant is maintained on every allocation mutation, and it is strict: reserving a quantity against a lot and later releasing that same allocation must leave `available_kg` bit-identical to its value before the pair, with equality evaluated at three decimal places.

Two events move a certified lot to a terminal state. A `MaterialsPlanner` may block a lot after a contamination event; blocking requires the lot to be `CERTIFIED` — from any other status the attempt is rejected with `ERR_INVALID_LOT_STATE` — and it cascades: every allocation of that lot currently `RESERVED` flips to `REVIEW`, and the lot's `version` advances. Separately, when consumption drives a lot's `available_kg` to exactly zero, the system automatically moves the lot `CERTIFIED` → `DEPLETED` and advances its `version`. `BLOCKED` and `DEPLETED` are both terminal.

### 3.2. The Regrind Loop: Scrap, Batches, and Segregated Decisions

Trim and skeletal waste flow back into production through a controlled loop of two record types. The loop's intake point is the **scrap record**, which the system creates automatically when a forming run completes with a positive `scrap_weight_kg` (see §3.6). The record carries the `forming_run_id` of the completing run, a `resin_type` copied from the run's production order, a `weight_kg` equal to the reported scrap mass, and a `regrind_batch_id` that stays null until certification; it starts in `PENDING`. No scrap record is created for a run that reports zero scrap. Scrap records are append-only audit entries: they carry an `id` and a `created_at` but no `updated_at` and no `version`.

A `MaterialsPlanner` opens a **regrind batch** with a plant-internal `batch_code`, a single `resin_type` (batches are single-resin only, immutable after creation), a `source_grade` recording the highest cleanliness grade among the scrap sources feeding the batch, and a positive fill target `target_kg` in kilograms. The batch opens in `ACCEPTING` with `accumulated_kg`, `reserved_kg`, and `consumed_kg` all at zero, and the creator's `X-User-ID` is recorded as `created_by_user_id` — this value anchors the segregation-of-duties rule at decision time.

Certifying scrap into a batch is a `MaterialsPlanner` action that takes the target `regrind_batch_id` and a `decision`. With `decision` of `CERTIFY`, three preconditions apply: the scrap record must be `PENDING` (otherwise `ERR_INVALID_SCRAP_STATE`), the batch must be `ACCEPTING` (otherwise `ERR_INVALID_BATCH_STATE`), and the batch's `resin_type` must equal the scrap's `resin_type` (otherwise `ERR_RESIN_MISMATCH`). On success the record's `regrind_batch_id` is set to the batch, the record moves to `CERTIFIED`, the batch's `accumulated_kg` increases by the record's `weight_kg`, and the batch's `version` advances by one. If that increase brings `accumulated_kg` to at least `target_kg`, the batch automatically advances `ACCEPTING` → `PENDING_CERT` and its `version` advances again. With `decision` of `REJECT`, the only state precondition is that the record is `PENDING` — the referenced batch must still exist per §2.8, but no batch-state or resin check applies; the record moves to `REJECTED` and nothing else changes. Both `CERTIFIED` and `REJECTED` are terminal for the record.

Once a batch reaches `PENDING_CERT`, a decision is required — and it must come from a **different** `MaterialsPlanner` than the one who created the batch. If the decider's `X-User-ID` equals the batch's `created_by_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Deciding a batch not in `PENDING_CERT` is rejected with `ERR_INVALID_BATCH_STATE`. Three decisions exist, with symmetric side effects where they certify mass:

- A `decision` of `CERTIFIED` requires `certified_grade` in the request. The batch moves to `CERTIFIED`, the supplied grade is stored as `certified_grade`, `max_blend_pct` is set to the blend cap for that certified grade, the decider is recorded as `decided_by_user_id`, and `version` advances.
- A `decision` of `DOWNGRADED` also requires `certified_grade`, and the supplied grade must rank strictly below the batch's `source_grade` — a downgrade to an equal or higher grade is rejected with `ERR_INVALID_REQUEST`. The side effects are otherwise identical to certification: grade stored, `max_blend_pct` set from the certified grade, decider recorded, `version` advanced.
- A `decision` of `REJECTED` is permitted only while no material allocation references the batch; if any allocation does, the rejection fails with `ERR_INVALID_BATCH_STATE`. A rejected batch leaves the eligible regrind pool and its `version` advances.

Until a certifying or downgrading decision lands, both `certified_grade` and `max_blend_pct` are null. The batch's own mass invariant mirrors the lot's: `available_kg` is always `accumulated_kg` minus `reserved_kg` minus `consumed_kg`, where `reserved_kg` sums `qty_kg` over the batch's allocations in `RESERVED` or `REVIEW` and `consumed_kg` sums those `CONSUMED`.

### 3.3. Tooling: Prototype Build, Qualification, Production, and Revision

A `ToolingEngineer` registers a tool in `DRAFT` with its `tool_code`, the `part_number` it forms, a `tool_type` of `FORM_MOLD`, `TRIM_FIXTURE`, or `MATCHED_SET`, the gauge window it is built for as `min_gauge_mm` and `max_gauge_mm` (the maximum no less than the minimum), the highest product grade the tool is validated for as `cleanliness_grade`, and the positive `prototype_cost` of building the prototype. A new tool starts with `drawing_revision` at 1 and `shots_used` at 0.

The tool lifecycle is a cycle with a qualification gate. Completing the prototype build moves `DRAFT` → `PROTOTYPE`; attempting it from any other state is `ERR_INVALID_TOOL_TRANSITION`. The transition materializes the plant's prototype shot limit on the tool: `proto_shot_limit` is set to 500. Submitting for qualification moves the tool to `QUALIFICATION` and is legal from either `PROTOTYPE` or `UNDER_REVISION`; from anywhere else it is `ERR_INVALID_TOOL_TRANSITION`.

Approving production is the consequential step. It requires the tool to be in `QUALIFICATION` (otherwise `ERR_INVALID_TOOL_TRANSITION`) and it is gated on cleanliness: a currently valid certificate must exist with `subject_type` `TOOL` and `subject_id` naming the tool, at a `grade` at least the tool's `cleanliness_grade`, otherwise `ERR_CERTIFICATE_INVALID`. The request supplies the `production_cost` of the production build and the tool's `rated_lifetime_shots`, both positive; both are null until this moment. Approval pins the drawing: `qualified_drawing_revision` is set to the tool's current `drawing_revision`, capturing exactly which revision was qualified. The tool enters `PRODUCTION` and its `version` advances. If the tool is later revised and re-qualified, a fresh approval re-pins `qualified_drawing_revision` to whatever `drawing_revision` is current at that re-approval.

Revision is where the tool cycle bites the floor. Revising moves `PRODUCTION` → `UNDER_REVISION` (legal only from `PRODUCTION`, else `ERR_INVALID_TOOL_TRANSITION`), increments `drawing_revision` by one, and advances the tool's `version` — and then it cascades two hops outward. First, every production order whose `tool_id` names this tool and whose `schedule_status` is `STAGED` or `RUNNING` is forced to `ON_HOLD`. Second, for each order held by that first hop, every material allocation of the order in `RESERVED` moves to `REVIEW`, awaiting re-validation when the order resumes (§3.6).

Tool state drives order economics through the amortization rule used by both cost variants. When the tool is in `PROTOTYPE`, the tooling charge is flat: the tool's full `prototype_cost` lands on the single order. When the tool is in `PRODUCTION`, the charge is amortized: a per-shot rate is computed as `production_cost` divided by `rated_lifetime_shots`, rounded half-up to four decimal places, and the order's charge is that per-shot rate multiplied by the order's `ordered_qty`, rounded half-up to two decimal places. The same order quantity therefore yields materially different charges depending on the tool's state — the prototype-to-production step changes unit economics. A tool in any state other than `PRODUCTION` with a recorded production cost — for example a prototype re-submitted to `QUALIFICATION` before any production approval — charges the flat `prototype_cost`. Independently of costing, `shots_used` accumulates the completed shots of every completed run of every order formed on the tool.

### 3.4. Packaging Specifications: Stock and Custom

A `PackagingEngineer` drafts a packaging spec with a `spec_code`, a `spec_type` of `STOCK` or `CUSTOM` (immutable after creation), the product grade the packaging supports as `cleanliness_grade`, and a `per_pack_cost` that may be zero but never negative. The two spec types enter the world differently: a `STOCK` spec is born `ACTIVE` and immediately usable, while a `CUSTOM` spec is born `PENDING_APPROVAL` and must survive a decision.

The decision belongs to `PlantManager` and only makes sense from `PENDING_APPROVAL`; deciding a spec in any other state is `ERR_INVALID_SPEC_STATE`. A `decision` of `APPROVED` is certificate-gated: a currently valid certificate must exist with `subject_type` `PACKAGING_SPEC` naming this spec, at a `grade` at least the spec's `cleanliness_grade`, otherwise `ERR_CERTIFICATE_INVALID`. A `decision` of `REJECTED` carries no certificate gate. Either way the decider's `X-User-ID` is recorded as `decided_by_user_id` — null until this point — and the spec's `version` advances. `REJECTED` is terminal, and a rejected spec poisons any order created against it (§3.5).

### 3.5. Production Orders and Material Reservations

A `ProductionScheduler` opens a production order with a customer-facing `order_code`; the `part_number` to form, which must equal the `part_number` of the referenced tool (a mismatch is `ERR_INVALID_REQUEST`); the `resin_type`; the positive integer `ordered_qty` of good parts required; the `required_gauge_mm` the order must run; the required product grade `cleanliness_grade`; the wall-thickness spec `spec_nominal_wall_mm` with `spec_min_wall_mm` no greater than nominal; the `nominal_part_weight_kg` per part before trim allowance; the `std_cycle_time_s` and `std_machine_rate_per_hour` used for provisional costing; the `tool_id`; the `packaging_spec_id`; and an optional `is_prototype_order` flag defaulting to false.

Creation is gated on both assets. The referenced tool must be in `PROTOTYPE` or `PRODUCTION` — any other tool state is `ERR_TOOL_NOT_QUALIFIED`. The order's `required_gauge_mm` must lie within the tool's gauge window, no less than `min_gauge_mm` and no greater than `max_gauge_mm`, otherwise `ERR_GAUGE_MISMATCH`. If the tool is in `PROTOTYPE`, the order must declare `is_prototype_order` as true (otherwise `ERR_PROTOTYPE_ORDER_REQUIRED`), and its `ordered_qty` must not exceed the tool's 500-shot prototype limit (otherwise `ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED`). The referenced packaging spec must be `ACTIVE`, `PENDING_APPROVAL`, or `APPROVED`; creating an order against a `REJECTED` spec is `ERR_PACK_SPEC_NOT_APPROVED`. Finally, the spec's `cleanliness_grade` must rank at least as high as the order's `cleanliness_grade`, otherwise `ERR_GRADE_INCOMPATIBLE`. These creation gates evaluate in a fixed order: tool state, spec state, spec grade, part-number equality, gauge window, and finally the prototype rules.

At creation the system computes `required_material_kg`: the ordered quantity times the nominal per-part mass times 1.18 (nominal mass plus the 18-percent trim allowance), rounded half-up to three decimal places. The order is born with `schedule_status` `QUEUED` and `quality_status` `PENDING` — two independent dimensions that move separately — with `shots_completed` and `shots_scrapped` at zero and `provisional_cost`, `tooling_charge`, and `final_cost` all null.

**Reserving material.** A `ProductionScheduler` reserves mass against an order by creating a material allocation naming the `production_order_id`, a `source_type` of `VIRGIN_LOT` or `REGRIND`, the source identifier (`lot_id` or `regrind_batch_id` per the conditional-field rule), and a positive `qty_kg`. The order's schedule must be `QUEUED`, `STAGED`, or `ON_HOLD`; allocating against an order in any other schedule state is `ERR_ORDER_NOT_ALLOCATABLE`. This order-state check fires before the referenced lot or batch is itself resolved, so a non-allocatable order masks even a missing source. A new allocation is born `RESERVED`. Creating one adds `qty_kg` to the lot's `allocated_kg` or the batch's `reserved_kg` and advances the order's `version` by one.

The virgin branch enforces five checks beyond schema and existence: the lot must be `CERTIFIED` (otherwise `ERR_INVALID_LOT_STATE`); the lot's `resin_type` must equal the order's `resin_type` (otherwise `ERR_RESIN_MISMATCH`); the lot's `gauge_mm` must equal the order's `required_gauge_mm` exactly (otherwise `ERR_GAUGE_MISMATCH`); a cleanliness certificate must exist for the lot at a grade at least the order's grade regardless of its expiry (a rank failure is `ERR_GRADE_INCOMPATIBLE`) and that certificate must be currently valid at the logical time (otherwise `ERR_CERTIFICATE_INVALID`); and the lot's `available_kg` must be at least the requested `qty_kg` (otherwise `ERR_INSUFFICIENT_MATERIAL`).

The regrind branch is the quota system's tightest chokepoint. The batch must be `CERTIFIED` or `DOWNGRADED` (otherwise `ERR_INVALID_BATCH_STATE`). Its `certified_grade` must rank at least as high as the order's `cleanliness_grade` (otherwise `ERR_GRADE_INCOMPATIBLE`), and the same two-step certificate rule as the virgin branch applies — a certificate must exist for the batch at sufficient grade, and it must be currently valid. The batch's `resin_type` must equal the order's (otherwise `ERR_RESIN_MISMATCH`). The batch's eligible mass — its `accumulated_kg` minus `reserved_kg` minus `consumed_kg` — must cover the request (otherwise `ERR_INSUFFICIENT_MATERIAL`). And the blend cap binds cumulatively: the cap in kilograms is the order's `required_material_kg` multiplied by the blend cap for the order's grade — 40 percent for `INDUSTRIAL`, 15 percent for `FOOD`, zero for `MEDICAL` — rounded half-up to three decimal places, and the sum of `qty_kg` over all of the order's `RESERVED` regrind allocations including the new request must not exceed it, otherwise `ERR_BLEND_CAP_EXCEEDED`. Because the medical cap is zero, any regrind allocation against a `MEDICAL` order violates it.

**Releasing and reviewing.** An allocation in `RESERVED` or `REVIEW` may be released by a `ProductionScheduler`; releasing from any other status is `ERR_ALLOCATION_NOT_RELEASABLE`. Release moves the allocation to `RELEASED`, subtracts its `qty_kg` from the lot's `allocated_kg` or the batch's `reserved_kg`, and advances the order's `version`. Both `CONSUMED` and `RELEASED` are terminal. The conservation invariant of §3.1 makes the reserve-then-release pair a no-op on the source pool's available mass. Allocations also move `RESERVED` → `REVIEW` without any client action — as a cascade from a lot block (§3.1) or a tool revision (§3.3) — and return `REVIEW` → `RESERVED` only by passing re-validation inside an order resume.

**Staging.** Staging is the moment the material plan freezes into a costed plan, and it runs under optimistic concurrency control as specified in §2.7: the request carries `expected_production_order_version`, and a mismatch with the order's current `version` is `ERR_STALE_VERSION`. The staged checks then apply: the order must be `QUEUED` (otherwise `ERR_INVALID_ORDER_STATE`); the tool must be `PROTOTYPE` or `PRODUCTION` (otherwise `ERR_TOOL_NOT_QUALIFIED`); the sum of `qty_kg` over the order's `RESERVED` allocations must reach at least `required_material_kg` (otherwise `ERR_INSUFFICIENT_MATERIAL`, HTTP 402); and the regrind blend cap is re-checked against the cumulative `RESERVED` regrind mass (otherwise `ERR_BLEND_CAP_EXCEEDED`). On success the system computes `provisional_cost` and `tooling_charge`, moves the order `QUEUED` → `STAGED`, and advances its `version`.

The provisional cost prices the plan. A reference virgin cost is taken first: the `unit_cost_per_kg` of the order's virgin allocation carrying the greatest `qty_kg`, with ties broken by the earliest `created_at`; regrind is then valued at 60 percent of that reference. If the order holds no virgin allocation in the relevant status, the reference virgin cost is zero, and regrind mass then contributes zero to the material component. The machine component is the ordered quantity times `std_cycle_time_s`, divided by 3600 to yield hours, times `std_machine_rate_per_hour`, rounded half-up to two decimal places. The material component is the sum over `RESERVED` virgin allocations of `qty_kg` times the lot's `unit_cost_per_kg`, plus the sum over `RESERVED` regrind allocations of `qty_kg` times the regrind unit cost, rounded half-up to two decimal places. The tooling charge follows the tool-state amortization rule of §3.3 using the tool's current status. The order's `provisional_cost` is the 250.00 setup fee plus the machine component, the material component, and the tooling charge, rounded half-up to two decimal places.

### 3.6. Running the Forming Floor: Stations, Runs, and Order Completion

Floor capacity is modeled as machine resources, registered by a `ProductionScheduler` with a `resource_code`, a `resource_type` of `FORMING_STATION` or `INSPECTION_BOOTH` (immutable after creation), the highest product grade the resource may touch as `cleanliness_grade`, and a positive `machine_rate_per_hour`. For forming stations this rate is the actual hourly rate used in final costing; booths may carry any positive rate.

**Scheduling a run** on a station takes the `production_order_id`, the `station_id` (which must reference a resource of type `FORMING_STATION`; pointing at a booth is `ERR_INVALID_REQUEST`), a planned window from `planned_start` to `planned_end` with the end later than the start, the `oven_temp_c` setpoint, the actual `cycle_time_s` per shot, and `shots_planned`, all positive where numeric. The order must be `STAGED` or `RUNNING` — otherwise `ERR_ORDER_NOT_RUNNING`. Both the tool's `cleanliness_grade` and the station's `cleanliness_grade` must rank at least as high as the order's grade, otherwise `ERR_GRADE_INCOMPATIBLE`. For an order running on a prototype tool, the cumulative `shots_planned` across the order's runs must not exceed the tool's 500-shot prototype limit, otherwise `ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED`. A new run is born `SCHEDULED` with `shots_completed`, `scrap_weight_kg`, and `actual_end` null until completion, and the order's very first run flips the order `STAGED` → `RUNNING` and advances the order's `version`.

Station occupation uses half-open windows: a run occupies its station from `planned_start` inclusive to `planned_end` exclusive. A new run conflicts with another run on the same station only if that run is still `SCHEDULED` and the two windows genuinely intersect — that is, unless the new window ends no later than the existing window's start or begins no earlier than the existing window's end. Such a conflict is rejected with `ERR_STATION_WINDOW_OVERLAP`. Back-to-back scheduling is explicitly allowed: a new run starting at exactly the instant another run ends does not conflict. Completed runs never block a station.

**Holding and resuming.** A `ProductionScheduler` may hold a `RUNNING` order, moving it to `ON_HOLD` and advancing its version; holding from any other schedule state is `ERR_INVALID_ORDER_STATE`. Orders also land in `ON_HOLD` without a direct request — through the tool-revision cascade of §3.3 and through a `REWORK` disposition (§3.7). Resuming is the deliberate inverse and the plant's re-validation point. It requires the order to be `ON_HOLD` (otherwise `ERR_INVALID_ORDER_STATE`) and the tool to be `PROTOTYPE` or `PRODUCTION` again (otherwise `ERR_TOOL_NOT_QUALIFIED`). Then every allocation of the order sitting in `REVIEW` is re-validated: for a virgin allocation the lot must be `CERTIFIED` with `available_kg` at least the allocation's `qty_kg`; for a regrind allocation the batch must still be `CERTIFIED` or `DOWNGRADED` with `available_kg` at least the allocation's `qty_kg`. Each allocation that passes returns to `RESERVED`. If any allocation fails, the resume is rejected with `ERR_ALLOCATION_REVIEW_FAILED` and the order stays `ON_HOLD`. A successful resume also clears a quality dimension held for rework — `quality_status` moves `REWORK_HOLD` → `PENDING` — and advances the order's `version`.

**Completing a run** is a `ProductionScheduler` action carrying the `shots_completed` of good shots, the `scrap_weight_kg` of trim and scrap mass, and the `actual_end` timestamp. The run must be `SCHEDULED` (otherwise `ERR_INVALID_RUN_STATE`); `shots_completed` and `scrap_weight_kg` must be non-negative and `actual_end` must be later than `planned_start` (violations are `ERR_INVALID_REQUEST`). Completion then chains outward: the run moves to `COMPLETED`; the order's `shots_completed` increases by the reported good shots; the tool's `shots_used` increases by the same amount; the order's `version` advances; and if the reported `scrap_weight_kg` is greater than zero, a `PENDING` scrap record is created for the regrind loop exactly as §3.2 describes. Finally, the completion check runs: if the order's schedule is `RUNNING`, its `shots_completed` has reached at least its `ordered_qty`, and its `quality_status` is `RELEASED`, the order completes.

**Order completion** is always automatic — never a direct client action — and it is evaluated both at run completion and at a `PASS` disposition. When it fires, the cascade runs three hops deep. Hop 1: every allocation of the order still `RESERVED` moves to `CONSUMED`. Hop 2: for each consumed virgin allocation the lot's `allocated_kg` decreases and its `consumed_kg` increases by the allocation's `qty_kg`; for each consumed regrind allocation the batch's `reserved_kg` decreases and its `consumed_kg` increases likewise. Hop 3: each touched lot recomputes `available_kg`, and a lot whose available mass reaches exactly zero moves `CERTIFIED` → `DEPLETED` per §3.1. The order's `final_cost` is computed, the schedule moves to the terminal `COMPLETED` state, and the order's `version` advances.

The final cost prices actuality, and it legitimately differs from the provisional figure. Its machine component sums one term per `COMPLETED` run — the station's `machine_rate_per_hour` times the elapsed hours from `planned_start` to `actual_end`, each run's term rounded half-up to four decimal places — with the sum then rounded half-up to two decimal places. Its material component sums `CONSUMED` allocations: virgin mass at the lot's `unit_cost_per_kg`, regrind mass at 60 percent of the reference virgin cost, where the reference follows the same greatest-`qty_kg` rule as the provisional variant, now read over the order's consumed virgin allocations; the component is rounded half-up to two decimal places. The tooling charge is recomputed by the same §3.3 rule, using the tool's status at completion time. The `final_cost` is the 250.00 setup fee plus these three components, rounded half-up to two decimal places.

**Cancellation** releases the plan back to the pools. A `ProductionScheduler` may cancel from `QUEUED`, `STAGED`, `RUNNING`, or `ON_HOLD` — from anywhere else it is `ERR_INVALID_ORDER_STATE`. Every allocation of the order in `RESERVED` or `REVIEW` moves to `RELEASED`, with the lot's `allocated_kg` or the batch's `reserved_kg` decremented by each released `qty_kg`, and the order's `version` advances. `CANCELLED` and `COMPLETED` are the schedule dimension's terminal states.

One conservation invariant guards the shot counters: at all times, an order's `shots_completed` plus its `shots_scrapped` equals the sum of `shots_completed` over the order's `COMPLETED` forming runs, with integer-exact equality. A run completion adds the same quantity to both sides; a `SCRAP` disposition (§3.7) moves quantity from `shots_completed` to `shots_scrapped` without changing either side's total.

### 3.7. Inspection and Disposition

Quality work runs on inspection booths, scheduled in windows. A `QualityInspector` records an inspection with the `production_order_id`, an optional `forming_run_id`, the `booth_id` (which must reference an `INSPECTION_BOOTH`; pointing at a forming station is `ERR_INVALID_REQUEST`), an `inspection_type` of `FIRST_ARTICLE` or `FINAL`, a booth window from `scheduled_start` to `scheduled_end` with the end later than the start, and the `wall_measurements_mm` array — a non-empty array of positive per-cavity readings. The booth's `cleanliness_grade` must rank at least as high as the order's grade, otherwise `ERR_GRADE_INCOMPATIBLE`. Two inspection-type gates apply: a `FIRST_ARTICLE` inspection must reference a `COMPLETED` run, and a `FINAL` inspection — which never references a run — requires the order's `shots_completed` to be greater than zero; violations are `ERR_INVALID_REQUEST`. These two gates are evaluated after the booth grade check and the booth temporal checks below, not at schema time. The recorder's `X-User-ID` is captured as `recorded_by_user_id`, and the inspection is born `RECORDED`.

Booth scheduling uses half-open windows like stations, but with a hygiene twist. An overlap with another inspection on the same booth that is still `RECORDED` — windows genuinely intersecting, adjacency alone being no conflict — is rejected with `ERR_BOOTH_WINDOW_OVERLAP`; inspections already `DISPOSITIONED` no longer occupy their booth. On top of raw overlap, a turnover buffer protects grade transitions: when the earlier session's order is `INDUSTRIAL` grade and the later session's order is `FOOD` or `MEDICAL`, the later session must begin no earlier than 30 minutes after the earlier session's end. A tighter gap is rejected with `ERR_BOOTH_BUFFER_VIOLATION`; a gap of exactly 30 minutes is allowed. Sessions whose grades do not match that earlier-industrial to later-food-or-medical pattern need no buffer. Like the overlap rule, the buffer is measured only against inspections still `RECORDED`.

Wall-thickness statistics are computed at recording time under a pinned rounding order. First, each reading in `wall_measurements_mm` is individually rounded half-up to the nearest 0.001 mm. Then `min_wall_mm` is the smallest of those per-measurement-rounded readings, `avg_wall_mm` is the mean of the rounded readings itself rounded half-up to 0.001 mm, and `deviation_pct` is the difference between the order's `spec_nominal_wall_mm` and `min_wall_mm`, divided by `spec_nominal_wall_mm`, multiplied by 100, and rounded half-up to two decimal places. The stored `wall_measurements_mm` array echoes the submitted readings verbatim; the per-measurement rounding feeds only the derived statistics. Rounding after aggregation instead is non-conformant: a raw reading of 1.2305 mm against a `spec_min_wall_mm` of 1.231 must pass after per-measurement rounding (the rounded reading is 1.231, which meets the floor), whereas comparing the raw minimum would fail it.

Disposition is deliberately segregated: the `QualityInspector` who dispositions an inspection must not be the one who recorded it — an `X-User-ID` matching `recorded_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) — and the inspection must still be `RECORDED`, otherwise `ERR_INSPECTION_ALREADY_DISPOSITIONED`. The dispositioner's identity is stored as `dispositioned_by_user_id`, the inspection moves to the terminal `DISPOSITIONED` state, and the order's `version` advances. The three dispositions carry measurement-consistency gates and distinct order effects:

- `PASS` requires `min_wall_mm` to be at least the order's `spec_min_wall_mm`; passing an under-wall inspection is `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`. On success the order's `quality_status` moves `PENDING` → `RELEASED` (a PASS landing when the quality dimension is no longer `PENDING` leaves it unchanged), and the completion check runs immediately — if `shots_completed` has already reached `ordered_qty`, the full completion cascade of §3.6 fires at this moment.
- `REWORK` moves the order's `quality_status` `PENDING` → `REWORK_HOLD`; if the order's schedule is `RUNNING`, it is simultaneously forced to `ON_HOLD`. The path back runs through resume (§3.6), which returns the quality dimension to `PENDING`.
- `SCRAP` requires `min_wall_mm` strictly below `spec_min_wall_mm` (otherwise `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT`) and requires a positive `scrapped_qty` naming how many parts are condemned; `scrapped_qty` must also not exceed the order's current `shots_completed` (otherwise `ERR_INVALID_REQUEST`). On success the order's `shots_completed` decreases by `scrapped_qty` and its `shots_scrapped` increases by the same amount, preserving the shot-conservation invariant.

### 3.8. Secondary Assembly and Packing

Formed parts frequently need secondary operations — trimming, insert placement, bonding, packing — modeled as assembly tasks on the order. A `ProductionScheduler` adds a task with the `production_order_id`, a `task_type` of `TRIM`, `INSERT`, `BOND`, or `PACK`, a positive `sequence_no` defining execution order within the order (lower numbers complete first), and — exactly when the type is `INSERT` — the `insert_part_code` of the inserted component. A task is born `PENDING`.

Completing a task is guarded on four fronts. The task must be `PENDING` (otherwise `ERR_INVALID_TASK_STATE`); the order's schedule must be `RUNNING`, `ON_HOLD`, or `COMPLETED` (otherwise `ERR_INVALID_ORDER_STATE`); and every task of the same order with a lower `sequence_no` must already be `COMPLETED`, otherwise `ERR_ASSEMBLY_SEQUENCE_VIOLATION`. A `PACK` task carries two additional gates: the order's `quality_status` must be `RELEASED` (otherwise `ERR_ORDER_QUALITY_NOT_RELEASED`), and the order's packaging spec must be `ACTIVE` or `APPROVED` (otherwise `ERR_PACK_SPEC_NOT_APPROVED`) — packing against a spec still awaiting decision, or one already rejected, is not permitted. Completion moves the task to the terminal `COMPLETED` state and advances its `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, and all reads, return `200 OK`. All list endpoints accept the pagination parameters of §2.3, and many accept filters: `status` on lots, batches, tools, specs, allocations, runs, scrap records, inspections, and tasks; `resin_type` on lots; `spec_type` on specs; `schedule_status`, `tool_id`, and `packaging_spec_id` on orders; `resource_type` on machine resources; and the foreign-key reverse-reachability filters `production_order_id`, `lot_id`, `regrind_batch_id`, `station_id`, `forming_run_id`, and `booth_id` on their respective collections, with `subject_type` and `subject_id` filtering the polymorphic certificate list. The table below is a navigational summary only; request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/material-lots` | Receive a virgin sheet lot into `QUARANTINE` | MaterialsPlanner |
| GET | `/material-lots` | List material lots | Any authenticated role |
| GET | `/material-lots/{lotId}` | Get one material lot | Any authenticated role |
| POST | `/material-lots/{lotId}/block` | Block a `CERTIFIED` lot; its `RESERVED` allocations move to `REVIEW` | MaterialsPlanner |
| POST | `/regrind-batches` | Open a regrind batch in `ACCEPTING` | MaterialsPlanner |
| GET | `/regrind-batches` | List regrind batches | Any authenticated role |
| GET | `/regrind-batches/{batchId}` | Get one regrind batch | Any authenticated role |
| POST | `/regrind-batches/{batchId}/decide` | Certify, downgrade, or reject a `PENDING_CERT` batch (segregated from creator) | MaterialsPlanner |
| POST | `/tools` | Register a tool in `DRAFT` | ToolingEngineer |
| GET | `/tools` | List tools | Any authenticated role |
| GET | `/tools/{toolId}` | Get one tool | Any authenticated role |
| POST | `/tools/{toolId}/complete-prototype` | Move `DRAFT` → `PROTOTYPE`; materializes the 500-shot prototype limit | ToolingEngineer |
| POST | `/tools/{toolId}/submit-qualification` | Move `PROTOTYPE` or `UNDER_REVISION` → `QUALIFICATION` | ToolingEngineer |
| POST | `/tools/{toolId}/approve-production` | Move `QUALIFICATION` → `PRODUCTION`; pins the qualified drawing revision | ToolingEngineer |
| POST | `/tools/{toolId}/revise` | Move `PRODUCTION` → `UNDER_REVISION`; holds affected orders and reviews their allocations | ToolingEngineer |
| POST | `/packaging-specs` | Create a packaging spec; `STOCK` born `ACTIVE`, `CUSTOM` born `PENDING_APPROVAL` | PackagingEngineer |
| GET | `/packaging-specs` | List packaging specs | Any authenticated role |
| POST | `/packaging-specs/{specId}/decide` | Approve (certificate-gated) or reject a custom spec | PlantManager |
| POST | `/production-orders` | Create a production order in `QUEUED`; computes `required_material_kg` | ProductionScheduler |
| GET | `/production-orders` | List production orders | Any authenticated role |
| GET | `/production-orders/{orderId}` | Get one production order | Any authenticated role |
| POST | `/production-orders/{orderId}/stage` | Move `QUEUED` → `STAGED` under OCC; verifies coverage and blend cap; computes provisional cost | ProductionScheduler |
| POST | `/production-orders/{orderId}/hold` | Move `RUNNING` → `ON_HOLD` | ProductionScheduler |
| POST | `/production-orders/{orderId}/resume` | Move `ON_HOLD` → `RUNNING`; re-validates `REVIEW` allocations; clears rework hold | ProductionScheduler |
| POST | `/production-orders/{orderId}/cancel` | Cancel from `QUEUED`, `STAGED`, `RUNNING`, or `ON_HOLD`; releases allocations | ProductionScheduler |
| POST | `/material-allocations` | Reserve virgin lot or regrind mass against an order | ProductionScheduler |
| GET | `/material-allocations` | List allocations with reverse-reachability filters | Any authenticated role |
| GET | `/material-allocations/{allocationId}` | Get one allocation | Any authenticated role |
| POST | `/material-allocations/{allocationId}/release` | Release a `RESERVED` or `REVIEW` allocation; restores the source balance | ProductionScheduler |
| POST | `/machine-resources` | Register a forming station or inspection booth | ProductionScheduler |
| GET | `/machine-resources` | List machine resources | Any authenticated role |
| GET | `/machine-resources/{resourceId}` | Get one machine resource | Any authenticated role |
| POST | `/forming-runs` | Schedule a forming run on a station; the first run moves the order to `RUNNING` | ProductionScheduler |
| GET | `/forming-runs` | List forming runs with reverse-reachability filters | Any authenticated role |
| GET | `/forming-runs/{runId}` | Get one forming run | Any authenticated role |
| POST | `/forming-runs/{runId}/complete` | Complete a run with shots, scrap, and actual end; may complete the order | ProductionScheduler |
| GET | `/scrap-records` | List scrap records with reverse-reachability filters | Any authenticated role |
| GET | `/scrap-records/{scrapId}` | Get one scrap record | Any authenticated role |
| POST | `/scrap-records/{scrapId}/certify` | Certify scrap into an `ACCEPTING` batch of the same resin, or reject it | MaterialsPlanner |
| POST | `/quality-inspections` | Record an inspection with wall measurements on a booth window | QualityInspector |
| GET | `/quality-inspections` | List inspections with reverse-reachability filters | Any authenticated role |
| GET | `/quality-inspections/{inspectionId}` | Get one inspection | Any authenticated role |
| POST | `/quality-inspections/{inspectionId}/disposition` | Pass, rework, or scrap the inspection (segregated from recorder) | QualityInspector |
| POST | `/assembly-tasks` | Add a trim, insert, bond, or pack task to an order | ProductionScheduler |
| GET | `/assembly-tasks` | List assembly tasks for an order | Any authenticated role |
| GET | `/assembly-tasks/{taskId}` | Get one assembly task | Any authenticated role |
| POST | `/assembly-tasks/{taskId}/complete` | Complete a task in sequence; pack tasks carry quality and spec gates | ProductionScheduler |
| POST | `/cleanliness-certificates` | Issue a certificate for a lot, batch, tool, or packaging spec | QualityInspector |
| GET | `/cleanliness-certificates` | List certificates with polymorphic subject filters | Any authenticated role |
| GET | `/cleanliness-certificates/{certId}` | Get one certificate | Any authenticated role |
| POST | `/_clock/set_current_utc` | Advance the server logical clock to a supplied instant | Any authenticated role |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined by the rules in §2 and §3, not by this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MATERIAL_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_REGRIND_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_TOOL_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGING_SPEC_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_MACHINE_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_FORMING_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_SCRAP_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_QUALITY_INSPECTION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSEMBLY_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_LOT_STATE` | 409 Conflict |
| `ERR_INVALID_TOOL_TRANSITION` | 409 Conflict |
| `ERR_TOOL_NOT_QUALIFIED` | 409 Conflict |
| `ERR_INVALID_BATCH_STATE` | 409 Conflict |
| `ERR_INVALID_ORDER_STATE` | 409 Conflict |
| `ERR_ORDER_NOT_ALLOCATABLE` | 409 Conflict |
| `ERR_ORDER_NOT_RUNNING` | 409 Conflict |
| `ERR_INVALID_RUN_STATE` | 409 Conflict |
| `ERR_INVALID_SCRAP_STATE` | 409 Conflict |
| `ERR_INSPECTION_ALREADY_DISPOSITIONED` | 409 Conflict |
| `ERR_ALLOCATION_NOT_RELEASABLE` | 409 Conflict |
| `ERR_INVALID_TASK_STATE` | 409 Conflict |
| `ERR_PACK_SPEC_NOT_APPROVED` | 409 Conflict |
| `ERR_INVALID_SPEC_STATE` | 409 Conflict |
| `ERR_ORDER_QUALITY_NOT_RELEASED` | 409 Conflict |
| `ERR_ALLOCATION_REVIEW_FAILED` | 409 Conflict |
| `ERR_GRADE_INCOMPATIBLE` | 422 Unprocessable Entity |
| `ERR_STATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BOOTH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BOOTH_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_CERTIFICATE_INVALID` | 422 Unprocessable Entity |
| `ERR_RESIN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_GAUGE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BLEND_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PROTOTYPE_ORDER_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DISPOSITION_CONTRADICTS_MEASUREMENT` | 422 Unprocessable Entity |
| `ERR_ASSEMBLY_SEQUENCE_VIOLATION` | 409 Conflict |
| `ERR_INSUFFICIENT_MATERIAL` | 402 Payment Required |

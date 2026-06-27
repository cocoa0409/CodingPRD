# Water Fire Restoration API — Product Requirements Document

## 1. Introduction

When a property suffers a water, fire, or smoke loss, the restoration crew that arrives on site is running a stopwatch against secondary damage — mold blooms within days, structural materials wick moisture upward by the hour, and an insurance adjuster on the other end of the phone needs a defensible paper trail for every dollar billed. This document specifies the backend API for a Servpro-style disaster-cleanup operation that orchestrates that entire arc: the first-notice-of-loss (FNOL) intake call, dispatch of a certified technician, the engineering of drying chambers and equipment, the daily psychrometric monitoring log, the Xactimate-style scope estimate that the carrier settles against, contents pack-out and storage, and final completion with a warranty clock.

The system is fundamentally a **workflow-orchestration engine layered over an insurance ledger**. A single loss job marches through a strict lifecycle, and at each gate the API must verify that the physical reality (chambers dried, equipment pulled, estimate approved) and the financial reality (coverage limit, deductible, depreciation) line up before it allows the next step. Two parallel concerns thread through everything: a *projection* view used while work is underway (estimated drying days, required equipment counts) and a *realized* view used at settlement (actual placement days, actual moisture readings). Keeping those two views reconcilable — never conflated — is the central engineering discipline of this product.

This PRD is written for the engineers who will implement the service. It leads with the domain narrative and the business rules that govern it; the precise HTTP contract (paths, status codes, error catalogue) is consolidated at the end. Readers should expect to assemble the full behavior of any one endpoint by combining the workflow narrative in Section 3 with the cross-cutting principles in Section 2.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API. The domain workflows in Section 3 assume everything stated here.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing either header — or carrying an `X-User-Role` that is not one of the five recognized role strings below — is rejected with `ERR_UNAUTHENTICATED` (an unrecognized role is treated as an authentication failure, not an `ERR_FORBIDDEN_ROLE`). A request whose role is recognized but not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes five roles, spelled exactly as follows: `PlatformAdmin`, `Dispatcher`, `Technician`, `Estimator`, and `Adjuster`.

- **`PlatformAdmin`** is the operational superuser: it registers pool resources (technicians and equipment units), opens claims and jobs, sets the logical clock, and can read every resource. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`Dispatcher`** owns loss-job intake, technician dispatch, and job cancellation. When `X-User-Role` is `Dispatcher`, `X-User-ID` is likewise an opaque operator identifier; the server does not compare it to any entity's `id`.
- **`Technician`** is the field operator: it owns mitigation progression, drying chambers, equipment placement and removal, moisture readings, contents handling, and job completion. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician` entity; ownership checks on any resource that references a `Technician` compare the resource's technician foreign key to `X-User-ID`.
- **`Estimator`** owns authoring of Xactimate scope estimates. When `X-User-Role` is `Estimator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`Adjuster`** is the insurance adjuster: it opens claims, approves estimates (settling the claim), and runs contents valuation. When `X-User-Role` is `Adjuster`, `X-User-ID` is an opaque operator identifier. The server records it — when a claim is opened, the acting adjuster's `X-User-ID` is stored on the claim as `adjuster_user_id` — but it does not compare `adjuster_user_id` to any entity's `id`; the claim is owned by whatever opaque operator string was recorded.

Authorization is evaluated before any other business rule: the header-presence check fires first, then the role-permission check, and only then does the system proceed to resource lookup and domain validation.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets how many items to skip from the front of the result set and defaults to 0. These bounds are enforced rather than clamped: a `limit` below 1 or above 100, an `offset` below 0, or a non-integer value for either is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless an endpoint explicitly states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Every list response includes these four fields inside the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Resource Versioning

Most resources in the system carry a standard set of system-managed fields:

- **`id`** — a server-minted UUID, with no type prefix, uniquely identifying the resource.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- **`version`** — an integer that begins at 1 on creation and increments by exactly 1 on every mutation. It underpins optimistic concurrency control (see §2.7).

`InsuranceClaim`, `LossJob`, `DryingChamber`, `EquipmentUnit`, `EquipmentPlacement`, `ScopeEstimate`, and `ContentsItem` all carry the full set above, including `updated_at` and `version`.

Two entities are exceptions and carry **only** `id` and `created_at` — they have no `updated_at` and no `version`, because they are immutable after creation: `Technician` and `MoistureReading`. A moisture reading, once logged, is never edited (the drying log is append-only); a technician record is a simple pool entry. Where this PRD refers generally to "mutating a resource and bumping its version," that applies only to the seven versioned entities.

All timestamps the system records — `created_at`, `updated_at`, `completed_at`, `warranty_expires_on` — are read from the server's **logical clock**, never from wall-clock time. The logical clock starts at `2026-01-01T00:00:00Z` and is only ever moved by the administrative clock-set capability described in §3.7. Before any clock-set call, every timestamp reflects exactly that default instant.

### 2.5. State Recomputation and Cascading Side Effects

Several resources carry **derived state** that the server recomputes automatically whenever an upstream change occurs — clients never set these fields directly.

A `DryingChamber`'s `latest_moisture_content_pct` and `is_dry` flag are recomputed every time a moisture reading is logged against it (§3.4). A chamber may auto-transition between `OPEN` and `DRIED` as a direct consequence, with no separate client request. Whenever any chamber's dry state changes — or a chamber is decommissioned — the owning job's `drying_status` is recomputed from the chamber dry flags. When a chamber transitions to `DRIED` or back to `OPEN` automatically, that is a mutation of the chamber: its `updated_at` is refreshed and its `version` increments. The same holds for the job whenever its `drying_status` changes.

Cancellation of a job is the system's most far-reaching cascade. Depending on the job's stage it releases equipment, decommissions chambers, and returns contents — a multi-hop fan-out detailed in §3.6. Every entity touched by a cascade is independently mutated: its `updated_at` is refreshed and (for versioned entities) its `version` increments. Approving an estimate likewise reaches across an aggregate boundary, mutating the parent claim (§3.5). The governing principle is that the system keeps parent and child state mutually consistent at all times: a change to a child that alters a parent's derived state propagates immediately to the parent within the same operation.

### 2.6. Nested and Path-Referenced Resource Resolution

Although the topology is flat — every resource is a top-level collection under `/restoration`, addressed by its own `id` and joined to others by foreign keys — many operations still reference a resource through a path identifier (a job, chamber, estimate, placement, or contents item). The system resolves path identifiers left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that names no existing resource, before evaluating any body content or business rule.

Foreign keys supplied in a request body are validated separately. When a create, dispatch, or placement request carries a reference such as `claim_id`, `job_id`, `chamber_id`, `equipment_unit_id`, or `technician_id` that names no existing resource, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. Both `ERR_NOT_FOUND` and `ERR_REFERENCE_NOT_FOUND` resolve to HTTP 404; the distinction is whether the missing reference came from the URL path or the request body.

### 2.7. Optimistic Concurrency Control on Estimate Creation

Creating a new scope estimate is the one write in the system guarded by optimistic concurrency control. A request to create a scope estimate must carry `expected_job_version`, a non-optional field whose value is the client's last observed `version` of the target `LossJob`. The server compares `expected_job_version` against the job's current `version`. If they do not match — because another writer has advanced the job's version since the client last read it — the create is rejected with `ERR_STALE_JOB_VERSION` at HTTP 412.

This guard exists because a new draft estimate legitimately supersedes the prior draft on the same job: if the client's view of which estimate is the live draft is stale, allowing the create would let it overwrite an estimate it never observed. No other endpoint takes a version field; OCC applies only to estimate creation, and only against the job's version.

### 2.8. Monetary Precision and Rounding

All monetary amounts in the system are stored and returned as integer **cents** — `coverage_limit_cents`, `deductible_cents`, `scope_lines_total_cents`, `equipment_estimate_cents`, `estimate_total_cents`, `acv_total_cents`, `declared_value_cents`, `allocated_value_cents`, and the unit prices inside scope line items are all whole-cent integers. Where a calculation produces a fractional intermediate (for example, per-line depreciation or tax), the result is rounded to whole cents using the **round-half-up** method before it participates in any further summation. Percentages supplied on a claim — `depreciation_pct` and `tax_pct` — are numbers in the range 0 through 100. Every client-supplied integer-cents amount and integer quantity must be a non-negative integer: `coverage_limit_cents`, `deductible_cents`, `declared_value_cents`, `estimated_drying_days`, and each scope line item's `qty` and `unit_price_cents` must be `>= 0`, and a negative or non-integer value (booleans are not accepted as integers) is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Two physical calculations also round half up: the grains-per-pound humidity ratio is rounded to a whole number, and drying-progress percentages are rounded to two decimal places. Equipment-sizing intermediates use a specific mix of ceiling and round-half-up rounding, spelled out where the sizing formula is described (§3.3).

### 2.9. Certification, Peril, and Loss-Type Enumerations

Several fields are constrained to fixed enumerations, and the system rejects any out-of-enumeration value with `ERR_INVALID_REQUEST` (HTTP 422):

- A claim's `peril` is one of `WATER`, `FIRE`, or `MOLD`.
- A claim's `status` is `OPEN` or `SETTLED`.
- A job's `loss_type` is one of `WATER`, `FIRE`, or `SMOKE`.
- A job's `status` progresses through `FNOL`, `DISPATCHED`, `MITIGATION`, `MONITORING`, `COMPLETED`, and `CANCELLED`; its `drying_status` is one of `NOT_STARTED`, `DRYING`, or `DRY_STANDARD_MET`.
- A technician's `certification` is one of `WRT` (water restoration), `ASD` (structural drying), or `AMRT` (mold remediation).
- A chamber's `status` is `OPEN`, `DRIED`, or `DECOMMISSIONED`.
- An equipment unit's `kind` (and the `kind` copied onto a placement) is `AIR_MOVER` or `DEHUMIDIFIER`; its `status` is `AVAILABLE` or `DEPLOYED`.
- A placement's `status` is `ACTIVE` or `REMOVED`.
- An estimate's `status` is `DRAFT`, `APPROVED`, or `SUPERSEDED`.
- A contents item's `status` is `PACKED_OUT`, `STORED`, or `RETURNED`.

### 2.10. Validation Ordering

When multiple checks could reject a single request, the system evaluates them in a fixed priority order so that the returned error is deterministic. The order is: (1) authentication — the headers must be present, else `ERR_UNAUTHENTICATED`; (2) authorization — the role must be permitted, else `ERR_FORBIDDEN_ROLE`; (3) path-resource existence — every path-referenced resource must exist, else `ERR_NOT_FOUND`; (4) body foreign-key existence — every referenced foreign key must exist, else `ERR_REFERENCE_NOT_FOUND`; (5) request validity — required fields, enums, and ranges must be valid, else `ERR_INVALID_REQUEST`; (6) state validity — the target resource must be in a state that admits the requested transition, else `ERR_INVALID_STATE`. Business-specific safety, referential, fiscal, and concurrency checks (priorities 7 and beyond) are evaluated after these six and are described alongside the workflows they guard in Section 3.

## 3. Business Logic & Workflows

### 3.1. Opening a Claim and Intaking a Loss

Every restoration begins with money and a phone call. An `Adjuster` (or a `PlatformAdmin`) opens an **insurance claim** by supplying the `carrier_name`, the `policy_number`, the cause of loss as `peril`, and the `coverage_limit_cents`. Three optional financial parameters may also be supplied, each defaulting to 0 when omitted: `deductible_cents`, the policy deductible; `depreciation_pct`, the recoverable depreciation percentage applied per estimate line item; and `tax_pct`, the sales-tax percentage applied to summed actual-cash-value. On creation the claim's `status` is `OPEN`, its `settled_estimate_id` is null, and `adjuster_user_id` is set to the `X-User-ID` of the acting adjuster (the opaque operator string, never required to equal any entity `id`). The claim settles later — at most once — when an estimate against one of its jobs is approved.

With a claim on file, a `Dispatcher` (or a `PlatformAdmin`) performs **FNOL intake** by creating a **loss job**. The intake payload carries the `claim_id` that funds the loss, the `property_address` of the loss site, and the `loss_type`. When the loss type is `WATER`, the payload must also carry the `water_category` (the IICRC contamination category: 1 for clean, 2 for gray, 3 for black water) and the `water_class` (the IICRC evaporation class, 1 through 4); both are required for a water loss and are rejected as `ERR_INVALID_REQUEST` if missing. The category must be 1, 2, or 3 and the class must be 1, 2, 3, or 4. For a `FIRE` or `SMOKE` loss these two fields are not supplied and remain null.

At intake the system computes one derived field immediately: `antimicrobial_required` is set to true when the water category is 3, or when the loss type is `FIRE` or `SMOKE`; otherwise it is false. A fresh job starts in `FNOL` status with `monitoring_day` at 0, `drying_status` at `NOT_STARTED`, `version` at 1, and `assigned_technician_id`, `completed_at`, and `warranty_expires_on` all null.

Two pools feed jobs. A `Dispatcher` or `PlatformAdmin` registers a **technician** into the pool by supplying a `full_name`, a `certification`, and an optional `active` flag that defaults to true. Separately, a `Dispatcher` or `PlatformAdmin` registers an **equipment unit** into the pool with an `asset_tag` and a `kind` of either `AIR_MOVER` or `DEHUMIDIFIER`; a newly registered unit's `status` is `AVAILABLE` with `active_placement_id` null. The `asset_tag` is the operator-facing label for the unit and is expected to be unique in practice, but the server records whatever value is supplied and does not enforce uniqueness — registering a second unit with an already-used `asset_tag` succeeds. Claims, jobs, technicians, and units can each be retrieved individually or listed; the listing endpoints accept filters that provide reverse-reachability — claims filter by `status` or `settled_estimate_id`; jobs filter by `claim_id`, `status`, or `assigned_technician_id`; technicians filter by `certification` or `active`; units filter by `status`, `kind`, or `active_placement_id`.

### 3.2. Dispatch and the Certification Gate

Dispatch is the first state transition on a job and the first place where physical credentials gate the workflow. A `Dispatcher` dispatches a technician to a job in `FNOL` status by submitting a payload containing the `technician_id`; this advances the job `FNOL → DISPATCHED` and sets `assigned_technician_id` to that technician. The transition runs three checks. First, the referenced technician must exist and be available — `active` must be true — otherwise the dispatch is rejected with `ERR_TECHNICIAN_UNAVAILABLE`. Second and third, the technician's certification must match the loss profile, and the two constraints apply independently and cumulatively (a technician must satisfy every constraint that fires): if the job's `loss_type` is `WATER`, the technician's `certification` must be `WRT` or `ASD`; if the `loss_type` is `FIRE` or `SMOKE`, **or** the job's `antimicrobial_required` flag is true, the technician's `certification` must be `AMRT` or `ASD`. A certification that fails to match any constraint that fires is rejected with `ERR_CERTIFICATION_MISMATCH`. Because a category-3 water loss is still a `WATER` loss yet also sets `antimicrobial_required` to true, both constraints fire at once, so such a job demands a technician whose certification satisfies both `{WRT, ASD}` and `{AMRT, ASD}` — that is, `ASD` specifically; an `AMRT`-only technician is rejected on a category-3 water job.

Dispatch is one of two ways a job leaves `FNOL`. The other is cancellation, available to a `Dispatcher` from `FNOL`, `DISPATCHED`, `MITIGATION`, and `MONITORING` (the cascade behavior of cancellation grows as the job progresses — see §3.6). A job that is still in `FNOL` and is cancelled simply moves to `CANCELLED`. A `DISPATCHED` job that is cancelled moves to `CANCELLED` and releases its technician by clearing `assigned_technician_id` back to null.

### 3.3. Building Drying Chambers and Sizing Equipment

Once a technician is on site, the crew maps the affected areas into **drying chambers**. A `Technician` creates a chamber against a job by supplying the `job_id`, a `room_label`, the `floor_area_sqft` (a non-negative integer), an optional `wet_wall_linear_ft` (a non-negative integer defaulting to 0), the `dehu_ppd_rating` (the AHAM pints-per-day rating of the dehumidifier model intended for the room, a required integer of at least 1 since it is a divisor in the dehumidifier-sizing formula), and the `dry_standard_pct` (the target moisture content read from an unaffected reference material; any number is accepted). A `floor_area_sqft` or `wet_wall_linear_ft` below 0, or a `dehu_ppd_rating` below 1, is rejected with `ERR_INVALID_REQUEST`. The `room_label` must be unique among the job's chambers that are not `DECOMMISSIONED`; a collision is rejected with `ERR_DUPLICATE_ROOM_LABEL`. A new chamber starts in `OPEN` status with `is_dry` false and `latest_moisture_content_pct` null.

At creation the system computes two required equipment counts that drive both the drying plan and the estimate. The sizing depends on a **sizing class**: for a `WATER` job the class is the job's `water_class`; for a `FIRE` or `SMOKE` job the class defaults to 2.

The **required air mover count**, `air_movers_required`, is the sum of two terms. The first term is the floor-area term: divide `floor_area_sqft` by the per-class square-footage divisor — 100 square feet per air mover for class 1, 70 for class 2, 60 for class 3, and 50 for class 4 — take the ceiling of that quotient, then take the larger of that value and 1, so the floor-area term is never below 1. The second term is the wet-wall term: divide `wet_wall_linear_ft` by 16 linear feet per air mover and take the ceiling. The two terms are added together.

The **required dehumidifier count**, `dehumidifiers_required`, is derived from a water-load figure. First compute the water load in pints per day by multiplying `floor_area_sqft` by the per-class load factor — 0.5 for class 1, 1.0 for class 2, 1.5 for class 3, and 2.0 for class 4 — and round that product half up to two decimal places. Then divide the rounded water load by the chamber's `dehu_ppd_rating` and take the ceiling of that quotient; that ceiling is `dehumidifiers_required`.

Chambers can be retrieved individually or listed with filters by `job_id` or `status`. A chamber that is `OPEN` or `DRIED` can be decommissioned by a `Technician`, moving it to `DECOMMISSIONED` — but only if no `ACTIVE` placement still references it; an attempt to decommission a chamber that still holds equipment is rejected with `ERR_CHAMBER_HAS_EQUIPMENT`. A `DECOMMISSIONED` chamber is excluded from `room_label` uniqueness checks and from the job's `drying_status` computation, and the job's `drying_status` is recomputed when a chamber is decommissioned.

Mitigation formally begins when a `Technician` starts mitigation on a `DISPATCHED` job, advancing it `DISPATCHED → MITIGATION`. This requires that at least one non-`DECOMMISSIONED` drying chamber already exists on the job; a start-mitigation attempt against a job with zero such chambers is rejected with `ERR_NO_CHAMBERS`.

### 3.4. Placing Equipment, Logging Readings, and Reaching Dry

During mitigation the crew deploys physical equipment into chambers. A `Technician` creates a **placement** by supplying the `job_id`, the `chamber_id`, and the `equipment_unit_id` of the device to deploy. The placement is valid only when the chosen equipment unit's `status` is `AVAILABLE` and the chamber belongs to the same job named by the placement's `job_id`; a unit that is already deployed, or a chamber that belongs to a different job, is rejected with `ERR_EQUIPMENT_NOT_AVAILABLE`. On a successful placement the unit's `kind` is copied onto the placement, `placed_on_day` is stamped with the job's current `monitoring_day`, the placement's `status` is `ACTIVE`, and `removed_on_day` and `billable_days` start at null and 0 respectively. As a cross-entity side effect, the deployed unit's `status` flips to `DEPLOYED` and its `active_placement_id` is set to this placement's id.

Pulling a unit reverses that. A `Technician` removes an `ACTIVE` placement, moving it `ACTIVE → REMOVED`. On removal, `removed_on_day` is stamped with the job's current `monitoring_day`, and `billable_days` is computed as the larger of 1 and the difference between `removed_on_day` and `placed_on_day` — so a unit removed on the same day it was placed still bills for one day. The cross-entity effect mirrors placement: the unit's `status` returns to `AVAILABLE` and its `active_placement_id` is cleared to null, returning it to the shared pool. Placements can be retrieved individually or listed, filtered by `job_id`, `chamber_id`, `equipment_unit_id`, or `status`. Equipment units can be listed filtered by `active_placement_id` to find the placement currently holding a unit.

The job advances from mitigation into daily monitoring when a `Technician` begins monitoring, moving it `MITIGATION → MONITORING`. The gate here is equipment sufficiency: every `OPEN` chamber must already have `ACTIVE` placements totaling at least its `air_movers_required` count of `AIR_MOVER` units and at least its `dehumidifiers_required` count of `DEHUMIDIFIER` units. If any `OPEN` chamber is under-equipped against either threshold, the transition is rejected with `ERR_EQUIPMENT_UNDERSIZED`. Once in monitoring, the crew advances the monitoring clock: a `Technician` advances the day, incrementing the job's `monitoring_day` by 1 each time. This epoch index — distinct from the wall/logical clock — is what stamps `placed_on_day` and `removed_on_day` and ultimately drives billable days.

Each monitoring day the crew logs a **moisture reading** against a chamber. A `Technician` logs a reading by supplying the `temp_f` (dry-bulb temperature inside the chamber, in degrees Fahrenheit), the `relative_humidity_pct` (relative humidity, 0 through 100), and the `moisture_content_pct` (the material moisture content of the affected material). The reading also records, from the system, the `job_id` and `chamber_id` (the latter from the path, the former denormalized from the chamber so readings can be listed job-wide) and the job's current `monitoring_day`. Readings are retrievable individually and listable filtered by `chamber_id` or `job_id`. A reading is append-only and immutable once written.

Writing a reading triggers two computations. First, the system computes the reading's **grains-per-pound humidity ratio**, `gpp`, a psychrometric measure derived from temperature and relative humidity. Convert the dry-bulb temperature to Celsius by subtracting 32 from `temp_f` and multiplying by five-ninths. Compute the saturation vapor pressure in hectopascals as 6.112 multiplied by the exponential of (17.62 times the Celsius temperature, divided by the sum of 243.12 and the Celsius temperature). Multiply that saturation pressure by `relative_humidity_pct` divided by 100 to get the actual vapor pressure. Compute the humidity ratio in pounds of water per pound of dry air as 0.62198 multiplied by the actual vapor pressure, divided by the quantity (1013.25 minus the actual vapor pressure), where 1013.25 hectopascals is the standard atmospheric pressure. Finally multiply the humidity ratio by 7000 grains per pound and round the result half up to a whole number of grains; that is `gpp`.

Second, the system recomputes the chamber's dry state. The chamber's `latest_moisture_content_pct` is set to the `moisture_content_pct` of the newest reading on the chamber — newest by `created_at` descending, which is unambiguous because readings are append-only and their creation timestamps strictly increase. The chamber's `is_dry` flag is true when that latest moisture content is **less than or equal to** the chamber's `dry_standard_pct` plus a tolerance of 4 percentage points; the boundary is inclusive, so a latest reading exactly at the dry standard plus 4 counts as dry. When the recompute flips a chamber's dry state, the chamber auto-transitions: an `OPEN` chamber whose reading makes it dry moves to `DRIED`, and a `DRIED` chamber whose new reading makes it no longer dry reverts to `OPEN` (a re-wetting reading reopens a previously dried chamber). These transitions are cyclic and driven entirely by readings, with no separate client request.

Each such chamber transition bubbles up to the job's `drying_status`, recomputed from the chamber dry flags as follows: when there is at least one non-`DECOMMISSIONED` chamber and every such chamber is `DRIED`, the job's `drying_status` becomes `DRY_STANDARD_MET`; otherwise, when at least one non-`DECOMMISSIONED` chamber has had a moisture reading logged (its `latest_moisture_content_pct` is non-null) or is `DRIED`, the status is `DRYING`; otherwise — no progress recorded anywhere — it remains `NOT_STARTED`. Thus a job moves `NOT_STARTED → DRYING` the moment the first reading is logged against any of its chambers, and if a re-wetting reading drops a chamber back to `OPEN` after the standard had been met, the job's `drying_status` falls from `DRY_STANDARD_MET` back to `DRYING`.

### 3.5. The Scope Estimate, Insurance Math, and Settlement

In parallel with the drying work, an `Estimator` authors a **scope estimate** — the Xactimate-style line-item scope plus a forward-looking equipment projection. An estimate is created against a job with the `job_id`, the `estimated_drying_days` (the estimator's projected drying duration), the `line_items` array, and the `expected_job_version` required by the concurrency guard of §2.7. Each entry in `line_items` is an object carrying a `qty` and a `unit_price_cents`. Creating a new draft estimate is OCC-guarded: `expected_job_version` must equal the job's current `version`, else `ERR_STALE_JOB_VERSION` (HTTP 412). A successful create starts the estimate in `DRAFT` status, increments the job's `version` by 1, and — because only one draft may be live at a time — automatically supersedes any prior `DRAFT` estimate on the same job, moving that prior draft `DRAFT → SUPERSEDED`.

Creation computes four monetary fields. The **scope-lines total**, `scope_lines_total_cents`, is the sum over every line item of its `qty` multiplied by its `unit_price_cents`. The **equipment estimate**, `equipment_estimate_cents`, is a forward-looking projection: it is `estimated_drying_days` multiplied by the sum, taken over every non-`DECOMMISSIONED` chamber on the job, of that chamber's `air_movers_required` multiplied by the air-mover day rate of 2500 cents plus that chamber's `dehumidifiers_required` multiplied by the dehumidifier day rate of 8000 cents. Note this uses each chamber's *required* counts, not the actual placements on the ground. The **estimate total**, `estimate_total_cents`, is `scope_lines_total_cents` plus `equipment_estimate_cents`.

The fourth field, `acv_total_cents`, is the insurance actual-cash-value, and its evaluation order is pinned. Walk the `line_items` in the order supplied. For each line, compute its replacement-cost value as `qty` times `unit_price_cents`, then compute the depreciation for that line as that replacement-cost value multiplied by the claim's `depreciation_pct` divided by 100, rounded half up to whole cents — the rounding happens per line, never after summation. Accumulate, across all lines, the replacement-cost value minus the per-line depreciation; call that running sum the ACV subtotal. Then compute tax as the ACV subtotal multiplied by the claim's `tax_pct` divided by 100, rounded half up to whole cents. The `acv_total_cents` is the ACV subtotal plus that tax. Estimates can be retrieved individually or listed filtered by `job_id` or `status`.

Settlement happens when an `Adjuster` approves a `DRAFT` estimate, advancing it `DRAFT → APPROVED`. Three preconditions guard approval, and they have distinct error codes. The parent claim's `status` must still be `OPEN`; approving against a claim already `SETTLED` is rejected with `ERR_CLAIM_ALREADY_SETTLED`. The estimate's `estimate_total_cents` must not exceed the claim's `coverage_limit_cents`; an over-limit estimate is rejected with `ERR_OVER_COVERAGE_LIMIT`. And no other estimate on the same job may already be `APPROVED`; a second approval is rejected with `ERR_ESTIMATE_ALREADY_APPROVED`. On a successful approval the estimate becomes `APPROVED`, and across the aggregate boundary the parent claim transitions to `SETTLED` with its `settled_estimate_id` set to this estimate's id.

### 3.6. Contents Pack-Out, Valuation, and the Cancellation Cascade

While structural drying proceeds, the crew removes salvageable belongings in a **pack-out**. A `Technician` packs out a **contents item** by supplying the `job_id`, a `description`, and the owner-declared `declared_value_cents`. A new item starts in `PACKED_OUT` status with `allocated_value_cents` at 0. Chain-of-custody moves forward through technician actions: a `PACKED_OUT` item can be moved into storage (`PACKED_OUT → STORED`), and an item can be returned to the owner either from storage (`STORED → RETURNED`) or directly from pack-out without intermediate storage (`PACKED_OUT → RETURNED`). Contents items are retrievable individually and listable filtered by `job_id` or `status`.

Coverage for contents is allocated by a **waterfall valuation** that an `Adjuster` or `Technician` runs across a job's pack-out inventory. First determine the available pool as the claim's `coverage_limit_cents` minus its `deductible_cents`, floored at 0 (never negative). Then walk the job's contents items whose status is `PACKED_OUT` or `STORED`, in `created_at` ascending order (never by id), and for each item allocate the smaller of the remaining pool and the item's `declared_value_cents` into that item's `allocated_value_cents`, decrementing the remaining pool by the amount allocated. Items that exhaust the pool receive what remains; later items receive 0. The conserved property is that the sum of allocated values over the included items equals the smaller of the available pool and the total declared value of those items. The valuation response is an object carrying `allocated_total_cents` (the summed allocation), `claim_limit_cents` (the available pool actually used — `coverage_limit_cents` minus `deductible_cents`, floored at 0), and `items`, an array of the included items in the same `created_at`-ascending order, each entry carrying `id`, `declared_value_cents`, `allocated_value_cents`, and `status`. Running the valuation persists each included item's recomputed `allocated_value_cents` (a mutation that refreshes `updated_at` and bumps `version`); items excluded from the walk are untouched.

Cancellation grows teeth as the job advances, and this is where the system's largest cascade lives. A `Dispatcher` cancelling a job in `MITIGATION` or `MONITORING` runs a three-hop release. Hop one: every `ACTIVE` equipment placement on the job is moved to `REMOVED`, stamped exactly as a normal removal would stamp it — `removed_on_day` is set to the job's current `monitoring_day` and `billable_days` is set to the larger of 1 and `removed_on_day` minus `placed_on_day`. Hop two: each unit freed in hop one has its `status` set back to `AVAILABLE` and its `active_placement_id` cleared to null. Hop three: every `OPEN` drying chamber on the job is moved to `DECOMMISSIONED`. In addition, every contents item still in `PACKED_OUT` or `STORED` is moved to `RETURNED`. The job itself moves to `CANCELLED`. (Cancellation from `FNOL` or `DISPATCHED`, by contrast, runs no equipment or contents cascade, as described in §3.2 — only the `DISPATCHED` case releases the assigned technician.)

### 3.7. Completion, Final Billing, Drying Progress, and the Clock

A job reaches the end of its useful life when a `Technician` completes it, advancing it `MONITORING → COMPLETED`. Three preconditions gate completion. The job's `drying_status` must be `DRY_STANDARD_MET` — equivalently, every non-`DECOMMISSIONED` chamber must be `DRIED` — else the completion is rejected with `ERR_DRY_STANDARD_NOT_MET`. No equipment placement on the job may still be `ACTIVE`; a lingering active placement is rejected with `ERR_EQUIPMENT_STILL_DEPLOYED`. And an `APPROVED` scope estimate must exist for the job, else `ERR_NO_APPROVED_ESTIMATE`. On successful completion the job's `status` becomes `COMPLETED`, `completed_at` is stamped with the logical clock's current instant, and `warranty_expires_on` is set to `completed_at` plus the warranty window, which is exactly 365 days. As a finalizing side effect, every contents item still in `STORED` on the job is moved to `RETURNED`.

If the drying has regressed, the crew can step back rather than complete. A `Technician` reopens mitigation on a `MONITORING` job, reverting it `MONITORING → MITIGATION` to add drying capacity. This is only meaningful when there is still wet work to do: at least one non-`DECOMMISSIONED` chamber must have `is_dry` false, otherwise the reopen is rejected with `ERR_NOTHING_TO_REOPEN`. The loop `MONITORING → MITIGATION → MONITORING` lets the crew add chambers or placements before resuming monitoring.

Two computed read endpoints close the financial loop without mutating anything. The **final billing** view recomputes the job's true cost from realized placements. The realized equipment cost sums, over every equipment placement on the job — whether `ACTIVE` or `REMOVED`, walked in `created_at` ascending order — the placement's day rate (2500 cents for an `AIR_MOVER`, 8000 cents for a `DEHUMIDIFIER`) multiplied by its `billable_days`. The final total is the `scope_lines_total_cents` of the `APPROVED` estimate plus that realized equipment cost. The billing variance is the final total minus the approved estimate's `estimate_total_cents`. The response surfaces all four figures: `scope_lines_total_cents`, `final_equipment_cents`, `final_total_cents`, and `billing_variance_cents`. This realized billing diverges from the estimate's forward-looking equipment projection whenever the actual billable days differ from `estimated_drying_days` multiplied by the required counts — the dual-variant calculation the system is built around.

The **drying-progress** view reports, per chamber, how far each affected chamber has dried relative to an unaffected baseline, and accepts an optional `mode`. The system first establishes the job reference: the `reference_gpp` is the `gpp` of the newest reading (by `created_at` descending) on the chamber whose `room_label` is `UNAFFECTED-REF`. For each target chamber, the initial gpp difference is the `gpp` of that chamber's first reading (by `created_at` ascending) minus the reference gpp, and the current gpp difference is the chamber's current gpp minus the reference gpp. The progress percentage is the initial difference minus the current difference, divided by the initial difference, multiplied by 100, and rounded half up to two decimal places. The chamber's current gpp depends on `mode`: in the default instantaneous mode — when `mode` is `INSTANT` or omitted — it is the `gpp` of the single newest reading by `created_at` descending; in trailing mode — when `mode` is `TRAILING` — it is the mean of the two newest readings' `gpp`, rounded half up to a whole number (when a chamber has only a single reading, the mean is taken over that one reading). Any `mode` value other than `INSTANT` or `TRAILING` is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The two modes diverge whenever the two newest readings differ. The response is an object carrying `job_reference_gpp` (null when no `UNAFFECTED-REF` chamber exists or it has no readings) and `per_chamber`, an array — in chamber `created_at`-ascending order and excluding the `UNAFFECTED-REF` chamber itself — whose entries each carry `chamber_id`, `room_label`, and `progress_pct`. A chamber's `progress_pct` is null when the job reference gpp is null, when the chamber has no readings, or when its initial gpp difference is zero (division undefined); otherwise it is the rounded percentage described above.

Finally, the system runs on a **logical clock** that a `PlatformAdmin` can set for deterministic test-driving. This administrative capability sets the server's logical clock to a supplied instant via the `to_iso8601` field (a value that is not a parseable ISO 8601 datetime is rejected with `ERR_INVALID_REQUEST`); on success it returns `200 OK` with a data object carrying a single `current_utc` field holding the newly set clock instant formatted as an ISO 8601 UTC timestamp with three fractional digits. As stated in §2.4, the clock defaults to `2026-01-01T00:00:00Z` at startup and supplies every timestamp the system records — including `completed_at` and `warranty_expires_on` — so that completion and warranty math are reproducible.

## 4. Endpoint Definitions

Operations that create a brand-new resource return `201 Created`; operations that modify or transition an existing resource, run a computation, or set the clock return `200 OK`. All listing and retrieval operations return `200 OK`. To reconstruct the full request body, response shape, and side effects of any endpoint below, refer back to the workflow narrative in Section 3 and the cross-cutting principles in Section 2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/restoration/technicians` | Register a technician | PlatformAdmin, Dispatcher |
| GET | `/restoration/technicians/{technicianId}` | Get a technician | PlatformAdmin, Dispatcher, Technician |
| GET | `/restoration/technicians` | List technicians | PlatformAdmin, Dispatcher, Technician |
| POST | `/restoration/equipment-units` | Register an equipment unit into the pool | PlatformAdmin, Dispatcher |
| GET | `/restoration/equipment-units/{unitId}` | Get an equipment unit | PlatformAdmin, Dispatcher, Technician |
| GET | `/restoration/equipment-units` | List equipment units | PlatformAdmin, Dispatcher, Technician |
| POST | `/restoration/claims` | Open an insurance claim | Adjuster, PlatformAdmin |
| GET | `/restoration/claims/{claimId}` | Get a claim | Adjuster, PlatformAdmin, Dispatcher |
| GET | `/restoration/claims` | List claims | Adjuster, PlatformAdmin, Dispatcher |
| POST | `/restoration/jobs` | Create a loss job (FNOL intake) | Dispatcher, PlatformAdmin |
| GET | `/restoration/jobs/{jobId}` | Get a loss job | Dispatcher, PlatformAdmin, Technician, Adjuster |
| GET | `/restoration/jobs` | List loss jobs | Dispatcher, PlatformAdmin, Technician, Adjuster |
| POST | `/restoration/jobs/{jobId}/dispatch` | Dispatch a technician to the job | Dispatcher |
| POST | `/restoration/jobs/{jobId}/start-mitigation` | Begin mitigation | Technician |
| POST | `/restoration/jobs/{jobId}/begin-monitoring` | Begin daily monitoring | Technician |
| POST | `/restoration/jobs/{jobId}/reopen-mitigation` | Revert monitoring back to mitigation | Technician |
| POST | `/restoration/jobs/{jobId}/advance-day` | Advance the monitoring-day epoch by 1 | Technician |
| POST | `/restoration/jobs/{jobId}/complete` | Complete the job and start the warranty clock | Technician |
| POST | `/restoration/jobs/{jobId}/cancel` | Cancel the job (cascades) | Dispatcher |
| GET | `/restoration/jobs/{jobId}/drying-progress` | Computed drying-progress percentage per chamber | Technician, Dispatcher, Adjuster, PlatformAdmin |
| GET | `/restoration/jobs/{jobId}/billing` | Computed final billing vs approved estimate | Adjuster, Dispatcher, PlatformAdmin |
| POST | `/restoration/jobs/{jobId}/contents/value` | Run contents waterfall valuation | Adjuster, Technician |
| POST | `/restoration/chambers` | Create a drying chamber | Technician |
| GET | `/restoration/chambers/{chamberId}` | Get a chamber | Technician, Dispatcher, Adjuster, PlatformAdmin |
| GET | `/restoration/chambers` | List chambers | Technician, Dispatcher, Adjuster, PlatformAdmin |
| POST | `/restoration/chambers/{chamberId}/decommission` | Decommission a chamber | Technician |
| POST | `/restoration/chambers/{chamberId}/readings` | Log a psychrometric / moisture reading | Technician |
| GET | `/restoration/readings/{readingId}` | Get a moisture reading | Technician, Dispatcher, Adjuster, PlatformAdmin |
| GET | `/restoration/readings` | List readings | Technician, Dispatcher, Adjuster, PlatformAdmin |
| POST | `/restoration/placements` | Place an available equipment unit into a chamber | Technician |
| GET | `/restoration/placements/{placementId}` | Get a placement | Technician, Dispatcher, Adjuster, PlatformAdmin |
| GET | `/restoration/placements` | List placements | Technician, Dispatcher, Adjuster, PlatformAdmin |
| POST | `/restoration/placements/{placementId}/remove` | Remove (pull) a deployed unit | Technician |
| POST | `/restoration/estimates` | Create a Xactimate scope estimate | Estimator |
| GET | `/restoration/estimates/{estimateId}` | Get an estimate | Estimator, Adjuster, Dispatcher, PlatformAdmin |
| GET | `/restoration/estimates` | List estimates | Estimator, Adjuster, Dispatcher, PlatformAdmin |
| POST | `/restoration/estimates/{estimateId}/approve` | Approve an estimate; settle the claim | Adjuster |
| POST | `/restoration/contents` | Pack out a contents item into inventory | Technician |
| GET | `/restoration/contents/{itemId}` | Get a contents item | Technician, Dispatcher, Adjuster, PlatformAdmin |
| GET | `/restoration/contents` | List contents | Technician, Dispatcher, Adjuster, PlatformAdmin |
| POST | `/restoration/contents/{itemId}/store` | Move a packed-out item into storage | Technician |
| POST | `/restoration/contents/{itemId}/return` | Return a contents item to the owner | Technician |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TECHNICIAN_UNAVAILABLE` | 409 |
| `ERR_CERTIFICATION_MISMATCH` | 409 |
| `ERR_NO_CHAMBERS` | 409 |
| `ERR_EQUIPMENT_NOT_AVAILABLE` | 409 |
| `ERR_DUPLICATE_ROOM_LABEL` | 409 |
| `ERR_EQUIPMENT_UNDERSIZED` | 409 |
| `ERR_CHAMBER_HAS_EQUIPMENT` | 409 |
| `ERR_DRY_STANDARD_NOT_MET` | 409 |
| `ERR_EQUIPMENT_STILL_DEPLOYED` | 409 |
| `ERR_NO_APPROVED_ESTIMATE` | 409 |
| `ERR_NOTHING_TO_REOPEN` | 409 |
| `ERR_OVER_COVERAGE_LIMIT` | 409 |
| `ERR_ESTIMATE_ALREADY_APPROVED` | 409 |
| `ERR_CLAIM_ALREADY_SETTLED` | 409 |
| `ERR_STALE_JOB_VERSION` | 412 |

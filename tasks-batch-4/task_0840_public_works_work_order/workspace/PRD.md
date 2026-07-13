# Public Works Work-Order & Asset Management API — Product Requirements Document

## 1. Introduction

Municipal public-works departments juggle a continuous flow of citizen-reported problems, scheduled preventive maintenance, field inspections, and capital reconstruction — all against a shared inventory of roads, signs, and signals stored in a geographic asset registry. This document specifies the backend service that ties those activities together: 311 intake and triage, a geographic asset registry keyed to linear GIS segments, condition inspection with pavement/condition-index scoring, the work-order lifecycle, crew and equipment dispatch, material and yard inventory, right-of-way and utility coordination, and the cost/labor accounting that ultimately decides whether a job is booked as routine maintenance or capitalized as a betterment.

The service is designed around segregation of duties: distinct operator roles own distinct steps of every workflow, and a single physical operation frequently mutates several records at once. Accepting an inspection can promote a condition score onto an asset, spawn a repair work order, and drive the asset into a repair state; completing that work order consumes reserved materials, rolls up labor and material cost, posts the total to a capital or maintenance ledger, frees the crew, releases occupied right-of-way, and closes the originating citizen request. The requirements below describe each of these cascades precisely, because the correctness of the whole system depends on every secondary effect firing exactly once and in the right order.

Because the platform is exercised deterministically, all time-dependent logic (asset age, service-level deadlines, dispatch windows) is driven by a logical clock rather than wall-clock time. The clock, its default, and the arithmetic that depends on it are described in §2.7.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming that operator's role. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly five roles, spelled precisely as follows:

- **`Supervisor`** — stewards the asset, crew, and material catalogs, adjudicates inspections, and retires assets.
- **`Inspector`** — authors and submits field inspections.
- **`Dispatcher`** — runs 311 intake, drives the work-order lifecycle up to hand-off, and reserves crews and materials.
- **`CrewLead`** — performs field execution of work orders and consumes materials.
- **`Coordinator`** — manages right-of-way and utility-coordination permits.

For all five roles, `identity` is opaque: `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity, and the server never compares it to any entity's `id`. The server does, however, record it where a workflow demands it. Specifically, when an `Inspector` creates an inspection the server freezes the caller's `X-User-ID` into the inspection's `inspector_id`, and when a `Supervisor` accepts or rejects an inspection the server records that supervisor's `X-User-ID` in the inspection's `decided_by`. These recorded identifiers drive the segregation-of-duties rule in §3.3; they are stored and compared to each other, not to any entity `id`.

All read (GET) endpoints are available to every one of the five roles, as is the logical-clock control endpoint. Write endpoints are restricted to the owning role(s) as tabulated in §4.

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

List endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum of 100. `offset` defaults to 0 and has no upper bound beyond the size of the collection. A `limit` or `offset` outside its allowed bounds is a malformed-request error (`ERR_VALIDATION`, HTTP 400).

Every list is returned in ascending `created_at` order (oldest first). The `meta` block of a list response includes `limit`, `offset`, `total_count` (the number of records matching the filters before pagination), and `has_more` (true when records remain beyond the current page). Any resource-specific filter query parameters are described alongside the relevant workflow in §3 and summarized against each list endpoint in §4.

### 2.4. Common Resource Properties and Versioning

Every persisted resource — `Asset`, `Inspection`, `ServiceRequest`, `WorkOrder`, `Crew`, `Dispatch`, `Yard`, `MaterialItem`, `MaterialReservation`, and `ROWPermit` — carries four system-managed common properties. `id` is a server-minted UUID with no type prefix. `created_at` is the ISO 8601 UTC timestamp (three fractional digits) of creation, taken from the logical clock. `updated_at` is the logical-clock timestamp of the most recent mutation. `version` is an integer that starts at 1 on creation and increments by one on every mutation of that resource.

Any state transition, computed-field recomputation, or ledger update that the specification attributes to a resource increments that resource's `version` and refreshes its `updated_at`. Because a single operation can touch several resources, the specification is careful in §3 to enumerate exactly which resources are bumped; when, for example, completing a work order consumes a material reservation, both the reservation and its material item advance their own `version`.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control (OCC) against a parent resource whose availability the writer is reasoning about. In each case the request must supply the parent's last-observed `version`, and the server rejects the write if the parent has moved on.

When a `Dispatcher` reserves a crew (creating a `Dispatch`), the request body must include `expected_crew_version`, carrying the client's last-observed `version` of the target `Crew`. If that value does not equal the crew's current `version` — because another dispatch, cancellation, or release has already shifted the crew's committed windows and availability — the reservation is rejected with `ERR_STALE_CREW_VERSION` (HTTP 412). This is a stale-version check on `Crew.version`, not a timing rule: the writer's view of the crew's free time is out of date and must be refreshed before retrying.

When reserving material (creating a `MaterialReservation`), the request body must include `expected_material_item_version`, carrying the client's last-observed `version` of the target `MaterialItem`. If that value does not equal the item's current `version` — because another reservation, consumption, release, or restock has already changed the item's reserved and available quantities — the reservation is rejected with `ERR_STALE_MATERIAL_VERSION` (HTTP 412).

No other endpoint takes a version field; only crew reservation and material reservation carry these expected-version inputs.

### 2.6. Validation Order and Error Precedence

When several checks could reject the same request, they are evaluated in a fixed priority order, so that the returned `error_id` is deterministic. The order is:

1. Authentication — headers present and `X-User-Role` known, else `ERR_UNAUTHENTICATED` (401).
2. Authorization — the role may perform this operation, else `ERR_UNAUTHORIZED` (403).
3. Body well-formedness — all required fields present, enum values legal, and numeric ranges satisfied (for example `raw_distress_index` between 0 and 100 inclusive, `qty` greater than 0, `window_end` strictly greater than `window_start`, and `decision` drawn from the allowed set), else `ERR_VALIDATION` (400).
4. Existence — every path `id` and every foreign-key `id` in the body exists, validated left-to-right in the order `asset_id`, `work_order_id`, `crew_id`, `material_item_id`, `service_request_id`, `duplicate_of_id`; a miss yields the resource-specific not-found error (see §5) at HTTP 404.
5. Legal state — the target resource is in a state from which the requested transition is defined, else `ERR_INVALID_STATE` (409).
6. Not terminal — the target resource is not already in a terminal state (see §2.10 for the terminal set per entity), else `ERR_ALREADY_TERMINAL` (409).
7. and beyond — business-safety, referential, temporal, fiscal, and concurrency checks specific to each operation, described in §3 and listed here for precedence: segregation of duties on inspection acceptance (`ERR_SEGREGATION_OF_DUTIES`), right-of-way clearance on work-order dispatch (`ERR_ROW_NOT_APPROVED`), presence of a reserved crew dispatch on work-order dispatch (`ERR_NO_DISPATCH_FOR_WORKORDER`), the reservation-target work-order state check (`ERR_INVALID_STATE`), the duplicate-of-self check on triage (`ERR_DUPLICATE_SELF`), the open-work-order check on asset retirement (`ERR_ASSET_HAS_OPEN_WORKORDER`), the crew-window conflict check on dispatch creation (`ERR_CREW_WINDOW_CONFLICT`), the right-of-way segment conflict check on permit approval (`ERR_ROW_SEGMENT_CONFLICT`), the optimistic-concurrency version checks (`ERR_STALE_MATERIAL_VERSION` / `ERR_STALE_CREW_VERSION`), and finally the sufficient-material check on reservation creation (`ERR_INSUFFICIENT_MATERIAL`).

The practical consequence of this ordering is that a stale-state or terminal-state problem is reported before any of the deeper business checks, and authentication/authorization always win over everything else.

### 2.7. The Logical Clock and Time Arithmetic

All time math in the system — asset age for condition scoring, service-level deadlines, and dispatch/permit window comparisons — reads from a logical clock rather than the host wall clock. On server startup the clock reads exactly `2026-03-01T00:00:00Z`, and it continues to read exactly that value until it is explicitly moved. Any role may advance the clock by supplying a new instant in the `to_iso8601` field; the clock jumps to that instant and stays there. Timestamps written to `created_at`, `updated_at`, `last_inspection_at`, and `sla_due_at` are all drawn from this logical clock.

### 2.8. Monetary Precision and Rounding

All money is stored and computed in integer cents. Wherever a calculation produces a fractional cent, the result is rounded half up (ties away from zero) to a whole cent. This applies to per-line material consumption cost, to the tiered labor cost of a dispatch, and to the betterment threshold used in capitalization. The pavement/condition index is likewise rounded half up to a whole integer before being clamped into the range 0 through 100. The exact points at which rounding is applied — in particular, that each material line is rounded before the lines are summed rather than after — are pinned in §3 because the ordering can change a total by a cent.

### 2.9. GIS Segments, Time Windows, and Conflict Geometry

Assets and permits are anchored to linear GIS segments identified by `gis_segment_id`. Right-of-way conflicts are computed per segment: two permits collide only when they occupy the same `gis_segment_id`. Time windows appear in two flavors with deliberately different boundary semantics. A crew dispatch window `[window_start, window_end)` is half-open (the end instant is not part of the window), and `window_end` must be strictly after `window_start`. A right-of-way permit window `[window_start, window_end]` is closed on both ends (adjacency counts as touching), and here too `window_end` must be strictly after `window_start`. The precise overlap tests, including the mobilization buffer applied to crew windows, are given in §3.5 and §3.7.

### 2.10. Terminal States and Cascading Consistency

Each entity has a set of terminal states from which no further transition is allowed; attempting any action on a terminal resource returns `ERR_ALREADY_TERMINAL`. The terminal states are: `Asset` `RETIRED`; `Inspection` `ACCEPTED`; `ServiceRequest` `CLOSED` and `DUPLICATE`; `WorkOrder` `COMPLETED` and `CANCELLED`; `Dispatch` `RELEASED` and `CANCELLED`; `MaterialReservation` `CONSUMED` and `RELEASED`; `ROWPermit` `DENIED` and `RELEASED`. `Crew` has no terminal state; it merely oscillates between `AVAILABLE` and `ON_ASSIGNMENT` as a computed availability indicator.

Several operations propagate state across entities. Accepting an inspection can drive its asset, and possibly spawn a work order; dispatching a work order activates its reserved crew dispatches and approved permits; completing or cancelling a work order releases every resource it holds and may return its asset to service. Each such cascade bumps the `version` and refreshes the `updated_at` of every resource it mutates. The invariants tie together conserved quantities — a crew's `committed_minutes` and a material item's `reserved_qty` — which must return exactly to their prior values when a reservation is undone. These cascades are specified operation-by-operation in §3.

## 3. Business Logic & Workflows

### 3.1. The GIS Asset Registry and Asset Lifecycle

The registry is the backbone of the system. A `Supervisor` registers each asset with its `asset_class` (one of `ROAD`, `SIGN`, or `SIGNAL`), the `gis_segment_id` of the linear segment it sits on, a human-readable `location_desc`, the `install_date` from which its age is measured, and a `replacement_value_cents` betterment basis that must be zero or greater. A newly registered asset begins life in `status` `ACTIVE`. Its condition attributes — `pci_score` and `condition_state`, its `last_inspection_at` timestamp, and its two running ledgers `maintenance_cost_to_date_cents` and `capital_cost_to_date_cents` — start empty or at zero: `pci_score`, `condition_state`, and `last_inspection_at` are initially null, while both cost ledgers start at 0. Assets can be fetched individually and listed; the list view can be filtered by `asset_class`, by `status`, and by `condition_state`.

An asset moves through three lifecycle states. Registration puts it in `ACTIVE`. The asset advances `ACTIVE → UNDER_REPAIR` automatically, as the system's response to a repair work order being spawned for a failed condition (§3.3). It returns `UNDER_REPAIR → ACTIVE` automatically once the work order that caused the repair reaches a terminal state and no other non-terminal work order remains on that asset (§3.8, §3.9). Both of those transitions are system-driven and each bumps `Asset.version`.

Retirement is the one operator-driven asset transition. A `Supervisor` retires an `ACTIVE` asset, moving it `ACTIVE → RETIRED`; `RETIRED` is terminal. Retirement is refused if any work order in a non-terminal status (`DRAFT`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD`) still references the asset, in which case the request fails with `ERR_ASSET_HAS_OPEN_WORKORDER`. Because `ACTIVE` is the only legal from-state for retirement, attempting to retire an asset that is `UNDER_REPAIR` is an illegal-state condition (`ERR_INVALID_STATE`), and attempting to retire one that is already `RETIRED` is `ERR_ALREADY_TERMINAL`.

An asset's `condition_state` is derived from its `pci_score` by fixed thresholds, recomputed every time the score is (re)set at inspection acceptance. A score of at least 85 is `GOOD`; a score below 85 but at least 70 is `FAIR`; a score below 70 but at least 55 is `POOR`; anything below 55 is `FAILED`. All three boundaries are inclusive lower bounds. A `FAILED` result is the trigger that pulls the asset into repair, as described next.

### 3.2. 311 Intake and Triage

Citizen reports enter through 311 intake. A `Dispatcher` records a `ServiceRequest` against an existing asset (`asset_id`), capturing the intake `channel` (`PHONE`, `WEB`, or `APP`), the problem `category` (`POTHOLE`, `SIGN_DAMAGE`, or `SIGNAL_OUTAGE`), a free-text `reported_by` contact, and the reported `location_desc`. New requests are created in `status` `NEW`.

At creation the system derives two computed fields from the reported `category`. The `priority` is assigned by category: a `SIGNAL_OUTAGE` is `EMERGENCY`, a `POTHOLE` is `HIGH`, and `SIGN_DAMAGE` is `MEDIUM`. From the resulting priority the system computes the service-level deadline `sla_due_at` as the request's `created_at` plus a fixed whole-hour offset: 4 hours for `EMERGENCY`, 48 hours (two days) for `HIGH`, 120 hours (five days) for `MEDIUM`, and 240 hours (ten days) for `LOW`. The `priority` field itself may take any of `LOW`, `MEDIUM`, `HIGH`, or `EMERGENCY`, though intake categories only ever produce `MEDIUM`, `HIGH`, or `EMERGENCY`. Requests can be fetched and listed, with list filters on `asset_id`, on `status`, and on `duplicate_of_id`.

Triage is performed by a `Dispatcher` on a request that is still `NEW`. When triaged without a duplicate reference, the request advances `NEW → TRIAGED` and becomes eligible to be linked to a work order. When the dispatcher supplies a `duplicate_of_id` naming another existing service request, the request advances `NEW → DUPLICATE` instead, and its `duplicate_of_id` is recorded; `DUPLICATE` is terminal. The referenced `duplicate_of_id` must name an existing service request and must not be the request's own `id` — a self-reference is rejected with `ERR_DUPLICATE_SELF`. Triaging a request that is not `NEW` is an illegal-state condition, and triaging one already in a terminal `CLOSED` or `DUPLICATE` state yields `ERR_ALREADY_TERMINAL`.

A `TRIAGED` request advances `TRIAGED → LINKED` automatically when a work order is created that names it (§3.4), and a `LINKED` request advances `LINKED → CLOSED` automatically when that linked work order completes (§3.8). Both are system-driven and terminal-bound: `CLOSED` is a terminal state.

### 3.3. Condition Inspection and PCI Adjudication

Field condition is captured through inspections and made official only on supervisory acceptance, under strict segregation of duties. An `Inspector` creates an `Inspection` against an asset (`asset_id`), declaring the `inspection_type` (`PREVENTIVE` or `CONDITION`), the field-measured `raw_distress_index` (a number from 0 to 100 inclusive, where higher means worse), and the planned `scheduled_window_start` and `scheduled_window_end`. On creation the server freezes the caller's `X-User-ID` into `inspector_id`, sets `status` to `DRAFT`, leaves `decided_by` null, and immediately computes `computed_pci`. Inspections can be fetched and listed, with list filters on `asset_id` and on `status`.

The pavement/condition index is computed at creation from the raw distress reading, the asset class's severity weight, and the asset's age. First, a severity weight is selected by the asset's `asset_class`: 1.0 for `ROAD`, 0.6 for `SIGN`, and 0.8 for `SIGNAL`. Second, the asset's age in whole years is the number of days between the current logical-clock instant and the asset's `install_date`, divided by 365.25 and rounded down to a whole number. Third, an age penalty is formed from that age: the base penalty is the age in years multiplied by 1.5 points per year, capped at a maximum of 25 points. For a `CONDITION` survey the full age penalty is used; for a `PREVENTIVE` survey the age term is first multiplied by a preventive factor of 0.5 (i.e. the age-in-years times 1.5 times 0.5, still capped at 25), so a preventive survey of the same asset with the same distress reading yields a higher index. Fourth, a base index is computed as 100 minus the product of `raw_distress_index` and the severity weight. Finally, `computed_pci` is the base index minus the age penalty, rounded half up to a whole integer and then clamped into the range 0 through 100.

An inspection advances through its lifecycle by submission and adjudication. The authoring `Inspector` submits a `DRAFT` inspection, moving it `DRAFT → SUBMITTED`. A `Supervisor` then adjudicates the submitted inspection by supplying a `decision` of `ACCEPT` or `REJECT`. A rejection moves the inspection `SUBMITTED → REJECTED`, recording the deciding supervisor's `X-User-ID` in `decided_by`; the inspector may then revise and resubmit, which moves it `REJECTED → SUBMITTED` again (this revision loop is the only way back out of `REJECTED`). Acceptance moves the inspection `SUBMITTED → ACCEPTED`, a terminal state.

Acceptance is guarded and cascading. The deciding supervisor's `X-User-ID` must differ from the inspection's `inspector_id`: an operator may not accept their own inspection, and a self-decision is rejected with `ERR_SEGREGATION_OF_DUTIES`. Acceptance is also refused when the target asset is `RETIRED` (an illegal-state condition). On a valid acceptance the system records the supervisor in `decided_by`, promotes the inspection's `computed_pci` onto the asset as its new `pci_score`, recomputes the asset's `condition_state` from the thresholds in §3.1, and sets the asset's `last_inspection_at` to the current clock time. If the recomputed `condition_state` is `FAILED` and the asset is currently `ACTIVE`, the system auto-creates a repair work order for that asset — with `work_type` `MAINTENANCE`, `origin` `INSPECTION`, and `status` `DRAFT` — which in turn drives the asset `ACTIVE → UNDER_REPAIR`. This full acceptance cascade bumps both `Inspection.version` and `Asset.version`. A rejection, by contrast, touches only the inspection.

### 3.4. Work Order Planning and Scheduling

A `WorkOrder` is the unit of field work. A `Dispatcher` raises one against an asset (`asset_id`), declaring the accounting intent `work_type` (`MAINTENANCE` or `CAPITAL`), the `origin` (`INSPECTION`, `SERVICE_REQUEST`, or `PREVENTIVE`), and optionally a scheduling `priority` (`LOW`, `MEDIUM`, `HIGH`, or `EMERGENCY`, defaulting to `MEDIUM`), a `service_request_id`, and an `estimated_cost_cents` planner estimate (defaulting to 0). A new work order starts in `status` `DRAFT`. Its computed cost fields — `labor_cost_cents`, `material_cost_cents`, and `actual_cost_cents` — start at 0, its `capitalized` flag starts false, and `scheduled_start`/`scheduled_end` start null. When a `service_request_id` is supplied and that request is currently `TRIAGED`, creating the work order links it: the service request advances `TRIAGED → LINKED`. Work orders can be fetched (the fetch includes the computed cost fields) and listed, with list filters on `asset_id`, on `service_request_id`, on `status`, and on `work_type`.

Scheduling is the first operator transition. A `Dispatcher` schedules a `DRAFT` work order by supplying `scheduled_start` and `scheduled_end`, where `scheduled_end` must be strictly after `scheduled_start`; the values are recorded and the work order advances `DRAFT → SCHEDULED`. Only once a work order is `SCHEDULED` can crews be reserved and permits attached to it, and only once those preconditions are met can it be dispatched (§3.8).

### 3.5. Crew Dispatch and Labor Costing

Crews are the labor resource. A `Supervisor` creates a `Crew` with a display `name`, a `crew_type` discipline (`PAVING`, `SIGNS`, or `SIGNALS`), and an `hourly_rate_cents` labor rate that must be zero or greater. A crew starts `AVAILABLE` with `committed_minutes` at 0. Its `status` is a computed availability indicator: it flips `AVAILABLE → ON_ASSIGNMENT` when its first reserved-or-active dispatch appears and flips `ON_ASSIGNMENT → AVAILABLE` when its last reserved-or-active dispatch is cancelled or released. This is an indicator only, not a booking blocker — a single crew may hold several dispatches at once as long as their windows do not collide. Crews can be fetched and listed, with list filters on `crew_type` and on `status`.

A `Dispatcher` reserves a crew against a scheduled work order by creating a `Dispatch`, naming the `work_order_id` and `crew_id`, the assignment `window_start` and `window_end`, and the planned `labor_hours` to bill (which must be greater than 0); the request must also carry `expected_crew_version` for the OCC check in §2.5. The referenced work order must be `SCHEDULED`, and `window_end` must be strictly after `window_start`. The half-open window `[window_start, window_end)` — extended by a mobilization buffer of 30 minutes on each side — must not overlap any existing `RESERVED` or `ACTIVE` dispatch window on the same crew; a collision is rejected with `ERR_CREW_WINDOW_CONFLICT`. A crew may legitimately hold multiple dispatches across non-overlapping (buffer-separated) windows. On success the dispatch is created in `status` `RESERVED`, its `labor_cost_cents` is computed, the crew's `status` becomes `ON_ASSIGNMENT`, the crew's `committed_minutes` is increased by the whole number of minutes in the `[window_start, window_end)` window, and `Crew.version` is incremented.

The labor cost of a dispatch is tiered on overtime. The regular portion is the lesser of `labor_hours` and an overtime threshold of 8 hours; the overtime portion is any hours beyond 8 (and zero when `labor_hours` does not exceed 8). The `labor_cost_cents` is the regular hours multiplied by the crew's `hourly_rate_cents`, plus the overtime hours multiplied by the crew's `hourly_rate_cents` multiplied by an overtime multiplier of 1.5, with the full sum rounded half up to whole cents. When `labor_hours` is 8 or fewer there is simply no overtime term.

A dispatch can be cancelled directly by a `Dispatcher`, moving a `RESERVED` or `ACTIVE` dispatch to `CANCELLED`. Cancellation returns the crew's committed time: the crew's `committed_minutes` is decreased by that window's minutes, the crew's `status` returns to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and `Crew.version` is incremented (as is the dispatch's own `version`). `RELEASED` and `CANCELLED` are terminal dispatch states. The system-driven dispatch transitions — `RESERVED → ACTIVE` on work-order dispatch, and `ACTIVE → RELEASED` or `RESERVED → RELEASED` on work-order completion — are described with their parent transitions in §3.8; the release transitions carry the same crew-time-return side effects as a cancellation.

### 3.6. Yards, Materials, and Reservations

Materials are stocked in yards. A `Supervisor` creates a `Yard` with a `name` and `location_desc`, and stocks it by creating `MaterialItem` records, each naming its `material_type` (`ASPHALT_TON`, `SIGN_BLANK`, or `SIGNAL_LAMP`), the holding `yard_id`, a `unit` of measure label, an initial `on_hand_qty` (zero or greater), a `unit_cost_cents` per-unit cost (zero or greater), and an optional `reorder_point` low-stock threshold that is informational only (defaulting to 0). A material item tracks a computed `reserved_qty` (the sum of `qty` over its `RESERVED` reservations, starting at 0) and a computed `available_qty` equal to `on_hand_qty` minus `reserved_qty`. A `Supervisor` restocks an item by supplying a `qty` to add, which increases `on_hand_qty` by that amount and increments the item's `version`. Yards and material items can be fetched and listed; the material-items list filters on `material_type` and on `yard_id`.

A `Dispatcher` or a `CrewLead` reserves material against a work order by creating a `MaterialReservation`, naming the `work_order_id` and `material_item_id` and a `qty` greater than 0; the request must carry `expected_material_item_version` for the OCC check in §2.5. The referenced work order must be in one of `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` — a `DRAFT`, `COMPLETED`, or `CANCELLED` work order cannot receive reservations, and a violation is an illegal-state condition (`ERR_INVALID_STATE`). The requested `qty` must not exceed the item's current `available_qty`; an over-reservation is rejected with `ERR_INSUFFICIENT_MATERIAL`. On success the reservation is created `RESERVED` with `consumed_cost_cents` at 0, the item's `reserved_qty` is increased by `qty`, and the item's `version` is incremented. Reservations can be fetched and listed, with list filters on `work_order_id`, on `material_item_id`, and on `status`.

A `RESERVED` reservation can be released directly by a `Dispatcher` or `CrewLead`, moving it `RESERVED → RELEASED`. Release returns the held quantity — the item's `reserved_qty` is decreased by `qty` while `on_hand_qty` is left unchanged — and increments the item's `version` and the reservation's `version`. `CONSUMED` and `RELEASED` are terminal reservation states. Consumption itself is not a direct operation; it happens only as part of work-order completion (§3.8), where each still-`RESERVED` reservation moves `RESERVED → CONSUMED`, its `consumed_cost_cents` is set to `qty` multiplied by the item's `unit_cost_cents` rounded half up to whole cents, the item's `on_hand_qty` and `reserved_qty` are each reduced by `qty`, and both the item's and the reservation's `version` are incremented.

### 3.7. Right-of-Way and Utility Coordination

Field work that occupies public space requires a permit. A `Coordinator` requests a `ROWPermit` for a work order (`work_order_id`), naming the `permit_type` (`LANE_CLOSURE`, `EXCAVATION`, or `UTILITY_COORD`), the `gis_segment_id` the permit occupies, the occupation `window_start` and `window_end` (with `window_end` strictly after `window_start`), an optional `utility_company` (defaulting to null), and a `clearance_required` flag (defaulting to true). A permit starts in `status` `REQUESTED`. Permits can be fetched and listed, with list filters on `work_order_id`, on `status`, and on `gis_segment_id`.

A `Coordinator` adjudicates a `REQUESTED` permit with a `decision` of `APPROVE` or `DENY`. A denial moves the permit `REQUESTED → DENIED`, a terminal state. An approval moves it `REQUESTED → APPROVED`, but only if it does not collide on its segment: no other permit on the same `gis_segment_id` in status `APPROVED` or `ACTIVE` may have a closed occupation window `[window_start, window_end]` that intersects this permit's closed window, where adjacency (touching endpoints) counts as an intersection. A collision is rejected with `ERR_ROW_SEGMENT_CONFLICT`.

A permit's later life is largely system-driven. An `APPROVED` permit advances `APPROVED → ACTIVE` when its work order is dispatched (§3.8). A permit that is `APPROVED` or `ACTIVE` can be released — either directly by a `Coordinator` or by the system when the work order completes or is cancelled — moving it to `RELEASED`, a terminal state. The `clearance_required` flag is the safety gate: a work order carrying any `clearance_required` permit that is not yet `APPROVED` cannot be dispatched, as described next.

### 3.8. Execution, Completion, and Cost Settlement

Once a work order is `SCHEDULED`, has crews reserved and any required permits approved, a `Dispatcher` dispatches it, advancing it `SCHEDULED → DISPATCHED`. Two preconditions guard this step beyond the state check. There must be at least one `RESERVED` dispatch for the work order, or it is rejected with `ERR_NO_DISPATCH_FOR_WORKORDER`. And every permit on the work order whose `clearance_required` is true must be `APPROVED`, or it is rejected with `ERR_ROW_NOT_APPROVED`. On success, dispatching cascades: every `RESERVED` dispatch for the work order advances `RESERVED → ACTIVE`, every `APPROVED` permit for the work order advances `APPROVED → ACTIVE`, and the work order's `version` is bumped (each activated dispatch and permit bumps its own `version` too).

A `CrewLead` then drives execution. Starting work advances the order `DISPATCHED → IN_PROGRESS`. Work may be paused and resumed any number of times: a `CrewLead` puts an in-progress order on hold (`IN_PROGRESS → ON_HOLD`) and resumes it (`ON_HOLD → IN_PROGRESS`). Each of these transitions bumps only the work order's `version`.

Completion is the settlement event, driven by a `CrewLead` on an `IN_PROGRESS` order and advancing it `IN_PROGRESS → COMPLETED` (a terminal state). Completion runs a full cascade in a pinned order:

- Each still-`RESERVED` material reservation for the work order is consumed (`RESERVED → CONSUMED`): its `consumed_cost_cents` becomes `qty` times the item's `unit_cost_cents` rounded half up to whole cents, the item's `on_hand_qty` and `reserved_qty` are each reduced by `qty`, and the item's `version` is bumped.
- The cost is rolled up. The `material_cost_cents` is the sum, over the work order's `CONSUMED` reservations, of each reservation's line cost computed as `qty` times the item's `unit_cost_cents` rounded half up to whole cents — each line is rounded before the lines are summed, never after, because summing first and rounding once can differ by a cent. The `labor_cost_cents` is the sum of `labor_cost_cents` over the work order's dispatches whose status is not `CANCELLED` (each such dispatch's labor cost is already whole cents). The `actual_cost_cents` is `labor_cost_cents` plus `material_cost_cents`.
- Capitalization is determined from the settled `actual_cost_cents` (see below), setting the `capitalized` flag.
- The total is posted to exactly one asset ledger: if `capitalized` is true, `actual_cost_cents` is added to the asset's `capital_cost_to_date_cents`; otherwise it is added to the asset's `maintenance_cost_to_date_cents`.
- Every `ACTIVE` or `RESERVED` dispatch for the work order is released (`ACTIVE → RELEASED` or `RESERVED → RELEASED`): the crew's `committed_minutes` is reduced by that dispatch's window minutes, the crew's `status` returns to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and `Crew.version` is bumped.
- Every `APPROVED` or `ACTIVE` permit for the work order is released (to `RELEASED`).
- If the work order carries a `service_request_id` and that service request is `LINKED`, the request advances `LINKED → CLOSED`.
- If the asset is `UNDER_REPAIR` and no other non-terminal work order remains on it, the asset returns `UNDER_REPAIR → ACTIVE`.
- Finally the work order advances to `COMPLETED`; its own `version` and the asset's `version` are bumped.

The capitalization decision is a two-branch test evaluated after `actual_cost_cents` is settled. If the declared `work_type` is `CAPITAL`, the order is capitalized outright. Otherwise, for a `MAINTENANCE` order, a betterment test applies: the order is reclassified as capital only when `actual_cost_cents` is at least a capitalization floor of 500,000 cents (5,000 dollars) *and* is at least the asset's `replacement_value_cents` multiplied by a betterment fraction of 0.25 (rounded half up to whole cents). Both comparisons are inclusive lower bounds, and both must hold. When either fails, the `MAINTENANCE` order stays an expense: its total goes to `maintenance_cost_to_date_cents` and the capital ledger is untouched. When both hold (or the order was `CAPITAL`), `capitalized` is true and the total goes to `capital_cost_to_date_cents` instead — the same settled cost, a different ledger and flag.

### 3.9. Cancellation and Resource Release

A `Dispatcher` can cancel a work order from any non-terminal state — `DRAFT`, `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` — moving it to `CANCELLED` (a terminal state). Cancelling a `DRAFT` order, which holds no reserved resources, simply sets the status. Cancelling from any of `SCHEDULED`, `DISPATCHED`, `IN_PROGRESS`, or `ON_HOLD` runs the release cascade: every `RESERVED` or `ACTIVE` dispatch for the work order is cancelled (`→ CANCELLED`), returning the crew's `committed_minutes`, flipping the crew back to `AVAILABLE` when it has no remaining `RESERVED` or `ACTIVE` dispatch, and bumping `Crew.version`; every `RESERVED` reservation is released (`→ RELEASED`), decreasing the item's `reserved_qty` by `qty` with `on_hand_qty` unchanged and bumping the item's `version`; every `APPROVED` or `ACTIVE` permit is released (`→ RELEASED`); and if the asset is `UNDER_REPAIR` and no other non-terminal work order remains on it, the asset returns `UNDER_REPAIR → ACTIVE`. In contrast to completion, cancellation never consumes material (reservations are released, not consumed, so `on_hand_qty` is preserved), never rolls up cost, and never closes a linked service request. The work order's `version` is bumped on cancellation.

## 4. Endpoint Definitions

All endpoints are mounted at the service root. Creating a new resource returns HTTP 201; all other successful reads, transitions, and modifications return HTTP 200. Request and response payloads are as described in the §3 narratives; the table below lists only the method, path, purpose, and authorized roles.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/assets` | Register a GIS asset | Supervisor |
| GET | `/assets/{id}` | Fetch an asset | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/assets` | List assets | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/assets/{id}/retire` | Retire an asset | Supervisor |
| POST | `/inspections` | Create an inspection (computes the condition index) | Inspector |
| GET | `/inspections/{id}` | Fetch an inspection | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/inspections` | List inspections | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/inspections/{id}/submit` | Submit or resubmit an inspection | Inspector |
| POST | `/inspections/{id}/decision` | Accept or reject a submitted inspection | Supervisor |
| POST | `/service-requests` | Create a 311 service request | Dispatcher |
| GET | `/service-requests/{id}` | Fetch a service request | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/service-requests` | List service requests | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/service-requests/{id}/triage` | Triage a request to triaged or duplicate | Dispatcher |
| POST | `/work-orders` | Create a work order | Dispatcher |
| GET | `/work-orders/{id}` | Fetch a work order (includes computed cost fields) | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/work-orders` | List work orders | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/work-orders/{id}/schedule` | Schedule a work order | Dispatcher |
| POST | `/work-orders/{id}/dispatch` | Dispatch a scheduled work order | Dispatcher |
| POST | `/work-orders/{id}/start` | Start work | CrewLead |
| POST | `/work-orders/{id}/hold` | Put work on hold | CrewLead |
| POST | `/work-orders/{id}/resume` | Resume held work | CrewLead |
| POST | `/work-orders/{id}/complete` | Complete work and settle cost | CrewLead |
| POST | `/work-orders/{id}/cancel` | Cancel a work order and release resources | Dispatcher |
| POST | `/crews` | Create a crew | Supervisor |
| GET | `/crews/{id}` | Fetch a crew | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/crews` | List crews | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/dispatches` | Reserve a crew to a scheduled work order | Dispatcher |
| GET | `/dispatches/{id}` | Fetch a dispatch | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/dispatches` | List dispatches | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/dispatches/{id}/cancel` | Cancel a dispatch and free the crew | Dispatcher |
| POST | `/yards` | Create a storage yard | Supervisor |
| GET | `/yards/{id}` | Fetch a yard | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/yards` | List yards | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/material-items` | Create a stocked material item | Supervisor |
| GET | `/material-items/{id}` | Fetch a material item | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/material-items` | List material items | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/material-items/{id}/restock` | Increase on-hand quantity | Supervisor |
| POST | `/material-reservations` | Reserve material against a work order | Dispatcher, CrewLead |
| GET | `/material-reservations/{id}` | Fetch a material reservation | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/material-reservations` | List material reservations | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/material-reservations/{id}/release` | Release a reserved material reservation | Dispatcher, CrewLead |
| POST | `/row-permits` | Request a right-of-way / utility permit | Coordinator |
| GET | `/row-permits/{id}` | Fetch a permit | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| GET | `/row-permits` | List permits | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |
| POST | `/row-permits/{id}/decision` | Approve or deny a requested permit | Coordinator |
| POST | `/row-permits/{id}/release` | Release an approved/active permit | Coordinator |
| POST | `/_clock/set_current_utc` | Advance the logical clock | Supervisor, Dispatcher, Inspector, CrewLead, Coordinator |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the §2 and §3 narratives; the table below lists only the identifier and its HTTP status code.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_ASSET_NOT_FOUND | 404 |
| ERR_INSPECTION_NOT_FOUND | 404 |
| ERR_SERVICE_REQUEST_NOT_FOUND | 404 |
| ERR_WORK_ORDER_NOT_FOUND | 404 |
| ERR_CREW_NOT_FOUND | 404 |
| ERR_MATERIAL_ITEM_NOT_FOUND | 404 |
| ERR_MATERIAL_RESERVATION_NOT_FOUND | 404 |
| ERR_ROW_PERMIT_NOT_FOUND | 404 |
| ERR_DISPATCH_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_ROW_NOT_APPROVED | 409 |
| ERR_NO_DISPATCH_FOR_WORKORDER | 409 |
| ERR_CREW_WINDOW_CONFLICT | 409 |
| ERR_ROW_SEGMENT_CONFLICT | 409 |
| ERR_INSUFFICIENT_MATERIAL | 409 |
| ERR_STALE_MATERIAL_VERSION | 412 |
| ERR_STALE_CREW_VERSION | 412 |
| ERR_DUPLICATE_SELF | 409 |
| ERR_ASSET_HAS_OPEN_WORKORDER | 409 |

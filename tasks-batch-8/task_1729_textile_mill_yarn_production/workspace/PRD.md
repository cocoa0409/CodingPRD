# Textile Mill Yarn Production API — Product Requirements Document

## 1. Introduction

A Carolina textile mill runs on a simple physical truth: fiber comes in the dock door, and first-quality roll goods go out to customers who approved an exact shade. Everything in between — blending cotton with polyester across shared fiber lots, matching yarn lots to machines whose count ranges actually fit the recipe, holding dye batches to a customer-approved shade band, and deciding which yards ship against an order and which go to the close-out table — is a chain of allocation and approval decisions where a stale number or an out-of-band measurement costs real money.

This document specifies the Textile Mill Yarn Production API, the system of record for that chain. It governs fiber receiving and blend recipe engineering, spinning machine scheduling and yarn count control, customer shade approval via lab dips, the wet-processing workflow with its quality gates and rework loop, roll put-up with yardage accounting, and the customer-order allocation pipeline that separates first-quality goods from seconds. The API is mounted under the `/mill` path prefix and serves six operational roles, each owning a distinct stage of the mill's production lifecycle.

The requirements below are written for the engineering team building the service. §2 fixes the system-wide contracts — envelope shape, pagination, precision, concurrency, and the ordered validation cascade. §3 narrates the business workflows in which every rule lives. §4 and §5 are the compact endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming their operational capacity. The system recognizes exactly six roles: `MillPlanner`, `SpinningSupervisor`, `DyeHouseOperator`, `QualityInspector`, `CustomerServiceRep`, and `MillAdmin`. A request whose `X-User-Role` header is missing or does not map to one of these declared roles is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but not permitted to invoke the target endpoint is rejected with `ERR_FORBIDDEN`.

All six roles use opaque operator identity. For every role — `MillPlanner`, `SpinningSupervisor`, `DyeHouseOperator`, `QualityInspector`, `CustomerServiceRep`, and `MillAdmin` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `submitted_by_operator_id` on a lab dip, where the submission workflow writes it) but does not compare it to any entity's `id`.

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

List endpoints paginate via query parameters. `limit` sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object.

Beyond pagination, list endpoints accept optional equality filters drawn from the resource's own fields — `status` on most resources, plus `fiber_type` on fiber lots, `recipe_id` on yarn lots, `machine_id` and `yarn_lot_id` on machine assignments, `customer_code` and `color_code` on shade bands and customer orders, `shade_band_id` on lab dips and dye lots, `yarn_lot_id` and `vat_id` on dye lots, and `dye_lot_id`, `is_second_quality`, and `allocated_order_id` on finished rolls.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields. `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on any mutation of the resource. `version` is a system-managed integer that increments by one on every mutation, including mutations caused by cascade side effects from operations on related resources. One deliberate exception: a blend component carries only `id` and `created_at` — because components are detached and re-derived rather than updated in place, `updated_at` and `version` are absent from that resource entirely.

### 2.5. Weights, Yardage, Color, and Precision Standards

All arithmetic is performed in decimal. Final stored values follow these precision rules, each using round-half-up: fiber weights (`received_weight_lbs`, `available_weight_lbs`, `component_weight_lbs`, `total_component_weight_lbs`, `spun_weight_lbs`) are carried to a precision of 0.01 pound; purchase and computed yarn costs (`unit_cost_per_lb`, `projected_cost_per_lb`, `actual_cost_per_lb`) are carried to 0.0001 USD, and every cost calculation rounds its result to 4 decimal places, round half up; shrinkage percentages, yarn-count deviation, yardage deviation, and all yardage aggregates round to 2 decimal places, round half up; color difference (delta-E) values round to 3 decimal places, round half up.

A request whose payload is malformed, missing a required field, or violates a field's type or range — a non-positive weight, a `hand_score` outside the 1–5 band, a shrinkage percentage outside 0–100 — is rejected with `ERR_INVALID_REQUEST`.

### 2.6. Production Lineage and Hierarchical Consistency

The mill's data forms a lineage: fiber lots feed blend recipes through components, recipes anchor yarn lots, yarn lots feed dye lots, dye lots yield quality tests and finished rolls, and rolls satisfy customer orders. When an operation on one resource changes the facts another resource's state depends on, the system reconciles the dependent resource immediately — refreshing its `updated_at` and incrementing its `version` — without waiting for a separate client request. Approving a dye lot, for example, advances the parent yarn lot from `DYEING` to `FINISHED` and increments the yarn lot's `version`; dye lot rejection walks the yarn lot back to `GREIGE` and returns its yards. Automatic reconciliations also run with no client request at all: a fiber lot whose available weight reaches zero becomes `EXHAUSTED`, a customer order crosses allocation thresholds as rolls come and go, and a yarn lot whose every finished roll has left `AVAILABLE` settles into `ALLOCATED`.

### 2.7. Nested Resource Retrieval

For any endpoint whose path contains multiple resource identifiers, identifiers are validated strictly left to right. The request is rejected with `ERR_NOT_FOUND` at the first path identifier that does not resolve to an existing resource, before any later identifier or body field is examined. A quality test recorded under a non-existent dye lot therefore fails on the dye lot identifier before the payload is ever inspected.

### 2.8. Optimistic Concurrency Control

Two write operations in this API require the client to prove it has observed the parent's current state. Approving a blend recipe requires the request to carry `expected_recipe_version` equal to the recipe's current `version`; if the recipe's version has advanced since the client last read it — because components were added or the recipe was otherwise mutated — the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from approving a composition it has not observed. Allocating a roll into a customer order likewise requires `expected_order_version` equal to the order's current `version`; a mismatch — the order's `allocated_yards` having been mutated by another allocation or release since the client last read it — is rejected with `ERR_STALE_VERSION` (HTTP 412). These are the only two version-guarded writes; no other endpoint accepts a version field.

### 2.9. Floor Scheduling Discipline: Machine Windows and Vat Cooldown

Two temporal guards keep the floor honest. A spinning machine can hold only one live assignment at a time: a new assignment's window — treated as half-open, covering its `window_start` inclusively and its `window_end` exclusively — must not overlap any other assignment on the same machine that is `SCHEDULED` or `IN_PROGRESS`, and `window_end` must fall strictly after `window_start`. Dye vats need turn-around time between batches: two dye lots sharing the same `vat_id` must respect a 30-minute cooldown between their scheduled batches, measured against each lot's `scheduled_at` instant. Either violation is rejected with `ERR_WINDOW_CONFLICT`.

### 2.10. The Ordered Validation Cascade

Every mutating request passes through a fixed validation cascade, evaluated in this exact order so that earlier failures mask later ones deterministically:

1. Authentication — the `X-User-Role` header is present and maps to a declared role (`ERR_UNAUTHENTICATED`).
2. Authorization — the role is permitted to invoke the endpoint (`ERR_FORBIDDEN`).
3. Path existence — every path-template identifier resolves to an existing entity, left to right (`ERR_NOT_FOUND`).
4. Reference existence — every foreign-key field in the request body, such as `fiber_lot_id`, `recipe_id`, `machine_id`, `yarn_lot_id`, `shade_band_id`, `dye_lot_id`, or `roll_id`, resolves to an existing entity (`ERR_REFERENCE_NOT_FOUND`).
5. State legality — the target entity's current state permits the requested transition (`ERR_INVALID_STATE`).
6. Quality gates — dye-lot approval is blocked while its quality test graded `REJECTED`, and a yarn lot cannot enter dyeing under a recipe that is not `APPROVED` (`ERR_QUALITY_GATE_FAILED`).
7. Uniqueness — a `recipe_code` already held by a non-superseded recipe, or a `machine_code` already registered, cannot be reused (`ERR_DUPLICATE_KEY`).
8. Temporal discipline — machine window overlap and vat cooldown as defined in §2.9 (`ERR_WINDOW_CONFLICT`).
9. Referential integrity — a finished roll cannot be cut from a dye lot that is not `APPROVED`, and a lab dip cannot be approved when its measured color difference exceeds the band's tolerance (`ERR_REFERENTIAL_VIOLATION`).
10. Capacity — a yarn lot must hold enough greige yards to cover a dye lot's request, and a fiber lot must hold enough available weight to cover a component's committed weight (`ERR_INSUFFICIENT_CAPACITY`).
11. Channel discipline — a roll flagged as second quality cannot be allocated into a normal customer order (`ERR_SECOND_QUALITY_NOT_ALLOCATABLE`).

## 3. Business Logic & Workflows

### 3.1. Fiber Receiving and Blend Engineering

A `MillPlanner` opens the production chain at the dock. Receiving a fiber lot records its `fiber_type` — one of `COTTON`, `POLYESTER`, `RAYON`, `WOOL`, or `NYLON` — its gross `received_weight_lbs` (strictly greater than zero), and its `unit_cost_per_lb` (zero or greater). The lot's `available_weight_lbs` is initialized equal to the received weight and is thereafter maintained by blend consumption: it can never fall below zero nor exceed the received weight. New lots begin life in `RECEIVED` status.

Recipe design starts when the planner creates a blend recipe with a human-readable `recipe_code` (for example, "CTN-POLY-60-40") and a `target_yarn_count_ne` greater than zero, expressing the English cotton count the yarn should spin to. A recipe is born in `DRAFT`. The code is unique among recipes that have not been superseded: reusing a code held by a `DRAFT` or `REJECTED` recipe is rejected with `ERR_DUPLICATE_KEY`. There is one deliberate exception — creating a fresh recipe whose `recipe_code` matches a currently `APPROVED` recipe is how the mill revises a blend: the incoming recipe is created in `DRAFT`, and the previously approved recipe with that code is automatically moved from `APPROVED` to `SUPERSEDED`. Yarn lots already spun from the superseded recipe are unaffected and keep pointing at it.

While the recipe is in `DRAFT`, the planner adds components, each naming a `fiber_lot_id` and a `component_weight_lbs` strictly greater than zero. The fiber lot must exist (`ERR_REFERENCE_NOT_FOUND`) and must hold enough available weight to cover the committed component weight, failing with `ERR_INSUFFICIENT_CAPACITY` when it does not. Every add re-derives the recipe's `total_component_weight_lbs` as the sum of its component weights and recomputes every component's `proportion_pct` — that component's weight divided by the recipe's total component weight, expressed as a percentage. Components are subordinate records of their recipe; reading the components of a recipe, or reading which components consume a given fiber lot, are both supported list views.

Approval is the commitment point. The planner's approval request must carry `expected_recipe_version` per §2.8. Approval proceeds only when the recipe is in `DRAFT`, has at least one component, and every referenced fiber lot is still in `RECEIVED` or `BLENDED` status; a recipe in any other state yields `ERR_INVALID_STATE`. On approval the recipe's `approved_at` is stamped (it is null until then), its `version` increments, and its `projected_cost_per_lb` is computed with the forward-looking blend cost estimate: the sum, over all components, of each component's weight multiplied by its fiber lot's current `unit_cost_per_lb` at approval time, divided by the recipe's `total_component_weight_lbs`, rounded to 4 decimal places round half up. Simultaneously each referenced fiber lot is debited — its `available_weight_lbs` reduced by the component weight it contributes and its `updated_at` refreshed — and any such lot still in `RECEIVED` transitions to `BLENDED`. A lot whose available weight reaches zero automatically transitions from `BLENDED` to `EXHAUSTED`, after which no further components may reference it. Rejection is the softer exit: a `DRAFT` recipe rejected by the planner moves to `REJECTED`, all of its components are detached (deleted), no fiber lot weights change, and the recipe's `version` increments.

### 3.2. Machines, Spinning, and Count Control

A `MillAdmin` registers each spinning machine with its floor `machine_code` (unique — duplicates are rejected with `ERR_DUPLICATE_KEY`) and its supported count band, `supported_count_min_ne` and `supported_count_max_ne`, both strictly greater than zero with the maximum strictly above the minimum. Machines begin `ACTIVE`; over their life they may pass through `DOWN` to `DECOMMISSIONED`.

The `SpinningSupervisor` records spun output as yarn lots, each carrying the `recipe_id` it was spun from — which must resolve (`ERR_REFERENCE_NOT_FOUND`) and must be an `APPROVED` recipe — plus the `spun_weight_lbs` produced and the measured `actual_yarn_count_ne`, both strictly greater than zero. A yarn lot starts in `GREIGE`. Its `greige_yards_available` is initialized from the spun weight using the standard yards-per-pound figure for the count band the lot's actual count falls into: 8,400 yards per pound at Ne 10, 16,800 yards per pound at Ne 20, and 25,200 yards per pound at Ne 30. That greige yardage is the lot's allocatable inventory for everything downstream.

Scheduling is the supervisor's lever. A machine assignment names the `machine_id`, the `yarn_lot_id`, and a production window from `window_start` (inclusive) to `window_end` (exclusive, strictly later than the start). Selector eligibility is enforced at scheduling time: the recipe's `target_yarn_count_ne` must lie within the machine's supported band from `supported_count_min_ne` to `supported_count_max_ne`, and a recipe whose target falls outside is rejected with `ERR_COUNT_OUT_OF_RANGE`. The window must also clear the §2.9 overlap rule against the machine's other live assignments. Assignments begin `SCHEDULED`; starting one requires the assignment to be `SCHEDULED` and the machine `ACTIVE` — anything else is `ERR_INVALID_STATE` — and moves it to `IN_PROGRESS`.

Completion does the real accounting. When an `IN_PROGRESS` assignment is completed, two things happen. First, the yarn lot's `actual_cost_per_lb` is computed with the chronological blend cost variant: the sum, over the recipe's components, of each component's weight multiplied by the `unit_cost_per_lb` recorded on its fiber lot at the moment the assignment completes, divided by the lot's `spun_weight_lbs`, rounded to 4 decimal places round half up. Because the denominator is the actual spun weight rather than the planned component sum — waste and count change pull the two apart — this chronological figure legitimately differs from the recipe's `projected_cost_per_lb` for identical inputs. Second, count change is detected: the deviation of `actual_yarn_count_ne` from the recipe's `target_yarn_count_ne`, expressed as a percentage of the target and rounded to 2 decimal places round half up, is compared against a tolerance of 3 percent; when the absolute deviation exceeds that tolerance, the lot is flagged for `QualityInspector` review. A `SCHEDULED` assignment may instead be cancelled, moving it to `CANCELLED`; assignments in `COMPLETED` and `CANCELLED` are terminal.

### 3.3. Shade Bands and the Customer Lab Dip Conversation

Color is a customer contract before it is a production target. A `CustomerServiceRep` creates a shade band for a `customer_code` and the mill's internal `color_code` (for example, "NAVY-2B"), anchored at a CIELAB centroid given by `centroid_l`, `centroid_a`, and `centroid_b`, with a `delta_e_tolerance` strictly greater than zero defining the maximum acceptable color difference from that centroid for first-quality goods. Bands begin `ACTIVE` and may later be `ARCHIVED`.

Against an existing band, a `DyeHouseOperator` submits a lab dip: a trial dyeing whose `measured_delta_e` — zero or greater — captures the measured color difference versus the band centroid, rounded to 3 decimal places round half up. The submitting operator's `X-User-ID` is recorded as `submitted_by_operator_id`. Color difference anywhere in this system is the Euclidean distance in CIELAB space: the square root of the sum of the squared differences between measured L*, a*, b* and the band's `centroid_l`, `centroid_a`, `centroid_b`, and a measurement passes the band when it is less than or equal to `delta_e_tolerance`. A dip begins `PENDING`. The customer, through a `CustomerServiceRep`, then approves or rejects it. Approval requires the dip to be `PENDING` and its `measured_delta_e` to fall within the band's tolerance; a dip whose measured difference exceeds the tolerance cannot be approved and is rejected with `ERR_SHADE_OUT_OF_BAND`. Rejection from `PENDING` needs no further condition. Both outcomes are terminal.

### 3.4. Dye Lot Submission and the Wet-Processing Workflow

With an approved shade target in hand, the `DyeHouseOperator` submits greige yarn for dyeing. The dye lot payload names the `yarn_lot_id`, the target `shade_band_id`, the `vat_id` identifying which dye vat will take the batch, the `scheduled_at` instant the lot enters the vat, and the `requested_yards` of greige yarn submitted — strictly greater than zero. The vat and schedule fields are not decorative: they feed the §2.9 cooldown rule, which rejects a batch that would land on the same `vat_id` within half an hour of another batch with `ERR_WINDOW_CONFLICT`.

Submission is gated by three guards. The yarn lot must currently be `GREIGE` (`ERR_INVALID_STATE` otherwise). Its `greige_yards_available` must cover the `requested_yards`, else `ERR_INSUFFICIENT_CAPACITY`. And the recipe the yarn was spun from must still be `APPROVED` — dyeing yarn from a recipe that has left that state is a quality-gate violation, rejected with `ERR_QUALITY_GATE_FAILED`. On success the dye lot is created in `SUBMITTED`, the yarn lot moves from `GREIGE` to `DYEING`, its `greige_yards_available` is debited by the requested yards, and the yarn lot's `version` increments as part of the cascade.

From `SUBMITTED`, the operator starts the batch, moving the dye lot to `DYEING` — permitted only while the parent yarn lot is itself in `DYEING`. When the batch has run and at least one quality test exists for the lot, the operator submits the shade for review, moving the dye lot to `SHADE_PENDING`; at that moment the dye lot's `measured_delta_e` is populated from the latest quality test's recorded shade values. Greige yarn that should never have gone forward can also be stopped at the source: a `QualityInspector` may reject a yarn lot outright while it is `GREIGE`, moving it to the terminal `REJECTED` state and zeroing its `greige_yards_available`.

### 3.5. Quality Testing, Grading, and the Rework Loop

Quality judgment is the `QualityInspector`'s exclusive province. A quality test recorded against a dye lot captures the `shrinkage_pct_provisional` — an oven-dry shrinkage estimate between 0 and 100, taken within 4 hours of dyeing — and a subjective `hand_score` on an integer scale from 1 to 5. The `shrinkage_pct_final`, the conditioned-atmosphere figure taken 24 hours later, is optional at recording time and stays null until conditioning completes; the inspector later patches the test with the final value.

Every test derives a `grade` the moment it is recorded, and again when the final shrinkage arrives. The grading ladder uses the final shrinkage when it is present and the provisional shrinkage otherwise: a shrinkage input of 8.0 percent or more grades the lot `REJECTED`; a shrinkage input of at least 5.0 percent but below 8.0 grades it `SECOND_QUALITY`; below that, a `hand_score` under 3 still grades it `SECOND_QUALITY`; only a lot clearing all three hurdles earns `FIRST_QUALITY`. Percentages round to 2 decimal places round half up. Because the final measurement replaces the provisional input, patching in the final shrinkage may upgrade or downgrade the earlier provisional grade. Recording a test also refreshes shade data: the dye lot's `measured_delta_e` is updated from the test's recorded shade values per the §3.3 color-distance rule, at 3-decimal precision.

Adjudication closes the loop. A dye lot in `SHADE_PENDING` can be approved by the inspector only when a quality test exists whose grade is `FIRST_QUALITY` or `SECOND_QUALITY`; approval of a lot whose test graded `REJECTED` is blocked by the quality gate with `ERR_QUALITY_GATE_FAILED`. Approval moves the dye lot to `APPROVED`, advances the yarn lot from `DYEING` to `FINISHED`, increments the yarn lot's `version`, and makes finished-roll put-up permitted for that dye lot. Rejection from `SHADE_PENDING` moves the dye lot to `REJECTED` and runs the rework loop — the loop is, in the normal course, how a lot whose quality test graded `REJECTED` gives its yarn back: the yarn lot returns from `DYEING` to `GREIGE`, its `greige_yards_available` is credited back by the dye lot's `requested_yards`, its `version` increments, and the lot may be resubmitted in a fresh dye lot. `APPROVED` and `REJECTED` are terminal for the dye lot.

### 3.6. Roll Put-Up and Yardage Accounting

Once a dye lot is `APPROVED`, the `DyeHouseOperator` cuts finished rolls from it; attempting put-up against a dye lot in any other state is a referential violation rejected with `ERR_REFERENTIAL_VIOLATION`. Each roll declares `put_up_yards` — the yards wound on at put-up — and, after inspection, the physically measured `actual_yards`; both are strictly greater than zero. At creation the roll's `yardage_deviation_pct` is computed as the difference between actual and put-up yards, divided by the put-up yards, expressed as a percentage and rounded to 2 decimal places round half up. The roll's `is_second_quality` flag is inherited from the parent dye lot's quality test: true when that test graded `SECOND_QUALITY`, marking the roll for the close-out channel rather than normal allocation. Every roll begins `AVAILABLE`, with `allocated_order_id` null until the roll is allocated.

Yardage aggregates follow two pinned orderings, and the mill keeps them distinct on purpose. Put-up totals used in variance reporting round each roll's `put_up_yards` to 2 decimal places first and then sum. Allocation totals that drive customer-order status do the opposite: they sum the raw `actual_yards` of the allocated rolls and round the aggregate to 2 decimal places, round half up. When put-up values carry fractional yards beyond the cent, the two orderings can diverge — by at most half a cent-yard per roll in the aggregate — and both are correct within their own purpose.

### 3.7. Customer Orders, Allocation, and the Seconds Channel

A `CustomerServiceRep` opens a customer order with the `customer_code`, the `color_code` being ordered, and the total `requested_yards` (strictly greater than zero). The `yardage_tolerance_pct` — the acceptable over/under-ship allowance — defaults to 2.0 percent when omitted and must lie between 0 and 10. Orders begin `OPEN`, and their `allocated_yards` starts at zero.

Allocation marries rolls to orders. The rep's allocation request names the `roll_id` and must carry `expected_order_version` per §2.8, with a stale version rejected as `ERR_STALE_VERSION`. Four guards apply: the roll must be `AVAILABLE`; it must be first quality — a roll whose `is_second_quality` is true is rejected with `ERR_SECOND_QUALITY_NOT_ALLOCATABLE` and belongs to the close-out channel; the order must be `OPEN` or `PARTIALLY_ALLOCATED`; and the color must match — the `color_code` on the shade band of the roll's dye lot must equal the order's `color_code`. On success the roll moves from `AVAILABLE` to `ALLOCATED`, the roll's `actual_yards` is added to the order's `allocated_yards`, and the order's `version` increments. Status then follows the totals automatically: an order whose `allocated_yards` is above zero is at least `PARTIALLY_ALLOCATED`, and once `allocated_yards` reaches the fill threshold — the `requested_yards` reduced by the `yardage_tolerance_pct` allowance — it becomes `FULLY_ALLOCATED`.

After allocation, three paths remain. Shipping an `ALLOCATED` roll moves it to `SHIPPED`, and when every roll allocated to an order has shipped, the order itself settles to `SHIPPED`. Releasing an allocated roll returns it from `ALLOCATED` to `AVAILABLE`, subtracts its `actual_yards` from the order's `allocated_yards`, and the order's status reverts accordingly — from `FULLY_ALLOCATED` back to `PARTIALLY_ALLOCATED`, or to `OPEN` once nothing remains allocated. Cancelling is permitted while an order is `OPEN` or `PARTIALLY_ALLOCATED`: every roll allocated to the order cascades from `ALLOCATED` back to `AVAILABLE`, the order's `allocated_yards` is zeroed, its `version` increments, and the order lands in `CANCELLED`. Second-quality rolls follow their own exit: a roll that is `AVAILABLE` and flagged `is_second_quality` can be routed to `CLOSE_OUT`. Finally, a yarn lot whose production has fully drained into orders — every finished roll of every dye lot of that lot sitting in `ALLOCATED`, `SHIPPED`, or `CLOSE_OUT` — automatically transitions from `FINISHED` to `ALLOCATED`, closing its lifecycle.

## 4. Endpoint Definitions

Operations that create new resources return `201 Created`; operations that modify an existing resource — including all state-transition actions — return `200 OK`. Request bodies, derived fields, and side effects for each endpoint are defined by the workflows in §3; the table below is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mill/fiber-lots` | Receive a new fiber lot | MillPlanner |
| GET | `/mill/fiber-lots` | List fiber lots (filterable) | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| GET | `/mill/fiber-lots/{id}` | Read one fiber lot | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| GET | `/mill/fiber-lots/{id}/blend-components` | List blend components consuming this fiber lot | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| POST | `/mill/blend-recipes` | Create a blend recipe (DRAFT); supersedes an APPROVED recipe with the same code | MillPlanner |
| GET | `/mill/blend-recipes` | List blend recipes | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| GET | `/mill/blend-recipes/{id}` | Read one blend recipe | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| POST | `/mill/blend-recipes/{id}/components` | Add a fiber component to a DRAFT recipe | MillPlanner |
| GET | `/mill/blend-recipes/{id}/components` | List components of a recipe | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| POST | `/mill/blend-recipes/{id}/approve` | Approve a DRAFT recipe (OCC via expected_recipe_version) | MillPlanner |
| POST | `/mill/blend-recipes/{id}/reject` | Reject a DRAFT recipe | MillPlanner |
| POST | `/mill/spinning-machines` | Register a spinning machine | MillAdmin |
| GET | `/mill/spinning-machines` | List spinning machines | MillPlanner, SpinningSupervisor, MillAdmin |
| GET | `/mill/spinning-machines/{id}` | Read one spinning machine | MillPlanner, SpinningSupervisor, MillAdmin |
| POST | `/mill/yarn-lots` | Record a spun yarn lot | SpinningSupervisor |
| GET | `/mill/yarn-lots` | List yarn lots | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| GET | `/mill/yarn-lots/{id}` | Read one yarn lot | MillPlanner, SpinningSupervisor, DyeHouseOperator, QualityInspector, CustomerServiceRep |
| POST | `/mill/yarn-lots/{id}/reject` | Reject a GREIGE yarn lot (zeroes greige yards) | QualityInspector |
| POST | `/mill/machine-assignments` | Schedule a yarn lot onto a machine over a window | SpinningSupervisor |
| GET | `/mill/machine-assignments` | List machine assignments (filterable by machine, yarn lot) | MillPlanner, SpinningSupervisor, MillAdmin |
| GET | `/mill/machine-assignments/{id}` | Read one machine assignment | MillPlanner, SpinningSupervisor, MillAdmin |
| POST | `/mill/machine-assignments/{id}/start` | Begin an assignment | SpinningSupervisor |
| POST | `/mill/machine-assignments/{id}/complete` | Complete an assignment; computes actual yarn cost | SpinningSupervisor |
| POST | `/mill/machine-assignments/{id}/cancel` | Cancel a SCHEDULED assignment | SpinningSupervisor |
| POST | `/mill/shade-bands` | Create a customer-approved shade tolerance band | CustomerServiceRep |
| GET | `/mill/shade-bands` | List shade bands | CustomerServiceRep, DyeHouseOperator, QualityInspector |
| GET | `/mill/shade-bands/{id}` | Read one shade band | CustomerServiceRep, DyeHouseOperator, QualityInspector |
| POST | `/mill/lab-dips` | Submit a lab dip against a shade band | DyeHouseOperator |
| GET | `/mill/lab-dips` | List lab dips (filterable by shade band) | DyeHouseOperator, CustomerServiceRep, QualityInspector |
| GET | `/mill/lab-dips/{id}` | Read one lab dip | DyeHouseOperator, CustomerServiceRep, QualityInspector |
| POST | `/mill/lab-dips/{id}/approve` | Customer approves a lab dip | CustomerServiceRep |
| POST | `/mill/lab-dips/{id}/reject` | Customer rejects a lab dip | CustomerServiceRep |
| POST | `/mill/dye-lots` | Submit a yarn lot for dyeing | DyeHouseOperator |
| GET | `/mill/dye-lots` | List dye lots | DyeHouseOperator, QualityInspector, CustomerServiceRep, MillPlanner |
| GET | `/mill/dye-lots/{id}` | Read one dye lot | DyeHouseOperator, QualityInspector, CustomerServiceRep, MillPlanner |
| POST | `/mill/dye-lots/{id}/start` | Begin dyeing | DyeHouseOperator |
| POST | `/mill/dye-lots/{id}/quality-tests` | Record a quality test; triggers grade computation | QualityInspector |
| GET | `/mill/dye-lots/{id}/quality-tests` | List quality tests for a dye lot | DyeHouseOperator, QualityInspector, CustomerServiceRep |
| PATCH | `/mill/quality-tests/{id}` | Update a quality test with final shrinkage after conditioning | QualityInspector |
| POST | `/mill/dye-lots/{id}/submit-shade` | Mark dye lot shade pending review | DyeHouseOperator |
| POST | `/mill/dye-lots/{id}/approve` | Approve dye lot after shade review; yarn lot becomes FINISHED | QualityInspector |
| POST | `/mill/dye-lots/{id}/reject` | Reject dye lot; yarn lot returns to GREIGE and yards are credited back | QualityInspector |
| POST | `/mill/finished-rolls` | Put-up a finished roll from an APPROVED dye lot | DyeHouseOperator |
| GET | `/mill/finished-rolls` | List finished rolls | DyeHouseOperator, QualityInspector, CustomerServiceRep |
| GET | `/mill/finished-rolls/{id}` | Read one finished roll | DyeHouseOperator, QualityInspector, CustomerServiceRep |
| POST | `/mill/finished-rolls/{id}/ship` | Ship an allocated roll | CustomerServiceRep |
| POST | `/mill/finished-rolls/{id}/release` | Release an allocated roll back to AVAILABLE | CustomerServiceRep |
| POST | `/mill/finished-rolls/{id}/close-out` | Route a second-quality roll to the close-out channel | CustomerServiceRep |
| POST | `/mill/customer-orders` | Open a customer order | CustomerServiceRep |
| GET | `/mill/customer-orders` | List customer orders | CustomerServiceRep, MillPlanner |
| GET | `/mill/customer-orders/{id}` | Read one customer order | CustomerServiceRep, MillPlanner |
| POST | `/mill/customer-orders/{id}/allocate` | Allocate an AVAILABLE first-quality roll to this order (OCC via expected_order_version) | CustomerServiceRep |
| POST | `/mill/customer-orders/{id}/cancel` | Cancel an order; releases all allocated rolls | CustomerServiceRep |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the §2 principles and §3 workflow narratives; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_QUALITY_GATE_FAILED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_KEY` | 409 Conflict |
| `ERR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_REFERENTIAL_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CAPACITY` | 422 Unprocessable Entity |
| `ERR_COUNT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_SHADE_OUT_OF_BAND` | 422 Unprocessable Entity |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SECOND_QUALITY_NOT_ALLOCATABLE` | 422 Unprocessable Entity |

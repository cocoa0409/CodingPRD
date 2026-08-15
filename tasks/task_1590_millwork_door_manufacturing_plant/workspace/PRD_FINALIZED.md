# Millwork Door Plant API — Product Requirements Document

## 1. Introduction

An architectural millwork and door plant earns its margin on coordination. A single order travels from sales configuration — species, sticking profile, hardware prep — through shop drawing submittal and architect approval, onto the moulder line, into the spray booth, under serialized fire-label control, and finally onto a truck bound for the jobsite, where punch-list deficiencies can send individual openings back through the entire loop. Every stage is owned by a different desk, and a mistake upstream compounds downstream: a superseded drawing must stop the moulder schedule, a failed gloss reading sends work back through a capacity-constrained booth, and a fire label once destroyed can never be reused.

This document specifies the Millwork Door Plant API, the system of record for that journey. The service is mounted under `/millwork` and governs projects, orders and their openings, submittal revisions with version-pinned configuration snapshots, machining programs and moulder setup scheduling, finishing batches with sheen conformance, serialized fire-label rolls and allocations, delivery trips planned against opening ready dates, and punch-list rework. It enforces segregation of duties between the people who perform work and the people who verify it, optimistic concurrency on the two resources whose versions pin downstream commitments, and strict capacity, changeover, and purge discipline on the shop's shared machines and booths.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API. Business behavior lives in §3; anything stated here governs every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted for the attempted operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

The system recognizes eight role names, spelled exactly as follows: `PlantManager`, `Estimator`, `Architect`, `ProductionLead`, `LabelAuthority`, `QAInspector`, `ShippingCoordinator`, and the read-only `Any`. Their charters:

- A `PlantManager` is the plant's general manager: this role owns projects, registers shop resources (moulder machines, spray booths, fire-label rolls, hardware templates), plans delivery trips, authorizes rework, and closes shipped orders.
- An `Estimator` sits in sales and estimating: this role configures orders and their openings, drafts and submits shop drawings, and drives change orders and cancellations.
- An `Architect` is the external design professional: this role approves or rejects submittals and may also report punch deficiencies observed in the field.
- A `ProductionLead` runs the shop floor: machining programs, moulder setup slots, finishing batches, label application, and rework execution.
- A `LabelAuthority` is the agency-authorized label control issuer: this role issues and voids serialized fire labels and retires label rolls.
- A `QAInspector` owns quality assurance: sheen measurement, label verification, punch triage and verification, and opening acceptance. For any given label allocation, the verifier must be a different user than both the issuer and the applier; for any given punch item, the verifier must be a different user than the reporter.
- A `ShippingCoordinator` runs logistics: trip assignment and the dispatch lifecycle.
- `Any` is a shared read-only designation: any authenticated principal, regardless of declared role, may call the read endpoints.

Identity model: for every one of these eight roles — `PlantManager`, `Estimator`, `Architect`, `ProductionLead`, `LabelAuthority`, `QAInspector`, `ShippingCoordinator`, and `Any` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow captures an actor (for example, as `submitted_by` or `reviewed_by` on a shop drawing, as `issued_by`, `applied_by`, or `verified_by` on a label allocation, or as `reported_by` on a punch item), but it never compares `X-User-ID` against any entity's `id` for ownership.

Authorization on status-transition endpoints is per target state, not merely per endpoint: the only role accepted is the actor declared on the matching state-machine transition for the requested target. For example, on the order status capability, an `Estimator` moves an order to `CONFIGURED` or `CANCELLED`, a `ProductionLead` moves it to `IN_PRODUCTION`, `FINISHING`, or `READY_TO_SHIP`, a `ShippingCoordinator` moves it to `SHIPPED`, and a `PlantManager` moves it to `CLOSED`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0.

Unless a list endpoint states otherwise, results are sorted by `created_at` in ascending order. The openings list additionally breaks ties by server insertion order rather than by any identifier.

Every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Version Counters

All fourteen resources — Project, HardwareTemplate, MoulderMachine, SprayBooth, FireLabelRoll, MillworkOrder, Opening, ShopDrawing, MachiningProgram, MoulderSetupSlot, FinishingBatch, LabelAllocation, DeliveryTrip, and PunchItem — carry the same four system-managed properties:

- `id` (string): a server-minted UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp, in the same format, refreshed on every mutation.
- `version` (integer): a counter that increments by exactly one on every mutation of the resource, whether the mutation arrives directly or through a cascade from another resource.

Cascades mutate their targets as real writes. Submitting, approving, or rejecting a shop drawing — and even creating a new drawing revision — each increment the parent order's `version` by one. Issuing, applying, or voiding a label allocation increments the underlying roll's `version` by one. Assigning or unassigning an opening increments the trip's `version` by one. A punch item's rework authorization that voids applied labels also bumps the affected roll's `version`. These counters are the substrate for the concurrency rules in §2.6.

### 2.5. The Validation Ladder: Order of Evaluation

Every request is evaluated against a fixed ladder of checks. Evaluation stops at the first rung that fails, and that rung's error is the one returned — a later rung never masks an earlier one. The ladder, from first to last:

1. **Authentication context.** `X-User-ID` and `X-User-Role` must be present and non-empty; failures return `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Authorization.** The role must be permitted for the operation, including the per-target-state actor rule of §2.1 on status endpoints; failures return `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403). On status endpoints whose authorized actor differs by target state, this rung reads the requested target from the raw request body without performing payload validation: when the target does not resolve to one of that endpoint's per-target transitions — because the target field is absent or names a state no transition of that endpoint targets — the per-target rule has nothing to match, and the rung is instead decided against the endpoint's full authorized role set of §4. A missing target field is still reported as a payload error, but only at rung 4, so on these endpoints the existence check of rung 3 always fires before any complaint about a missing target.
3. **Existence.** Path identifiers are validated left to right first, then foreign-key fields in the request body in their declared input order; each missing resource returns its own `ERR_{RESOURCE}_NOT_FOUND` (HTTP 404) — concretely `ERR_PROJECT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_OPENING_NOT_FOUND`, `ERR_DRAWING_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`, `ERR_MACHINE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_BOOTH_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_TRIP_NOT_FOUND`, `ERR_PUNCH_NOT_FOUND`, or `ERR_TEMPLATE_NOT_FOUND`.
4. **Payload well-formedness.** Required fields must be present, unknown fields are rejected, enum values must be in range, and the structural time rules of §2.8 and §3.7 must hold; failures return `ERR_INVALID_REQUEST`, `ERR_INVALID_SLOT_HOURS`, `ERR_INVALID_CURE_WINDOW`, or `ERR_INVALID_TRIP_DATES` (HTTP 400).
5. **Optimistic concurrency.** Where an endpoint takes an expected-version field (§2.6), it must equal the parent resource's current `version`; this rung is evaluated before any business logic and fails with `ERR_STALE_ORDER_VERSION` or `ERR_STALE_ROLL_VERSION` (HTTP 412).
6. **State gates.** The target resource must be in the state the operation requires — both per-entity from-states and cross-entity gates such as an order being in production — failing with the per-transition errors catalogued in §5 (HTTP 409).
7. **Fire and compliance safety.** Rated-order template rules, machine species support, label-series matching, segregation of duties, self-approval bans, and booth cross-family purging; failures return HTTP 403 safety errors.
8. **Uniqueness and structural constraints.** Duplicate codes, single-active-drawing and single-active-allocation rules, machine slot overlap, the changeover buffer, and program–order matching; failures return HTTP 409.
9. **Cross-aggregate referential coherence.** An opening's order must belong to the trip's project, a rework batch must belong to the punch opening's order, and an opening's fire rating must not outrank its order's maximum; failures return HTTP 409.
10. **Temporal delivery windows.** A trip's jobsite arrival must not fall after an assigned opening's required-on-site date; failures return `ERR_DELIVERY_WINDOW_MISSED` (HTTP 409).
11. **Fiscal quota and capacity.** Label serial sufficiency, truck capacity, and booth capacity; failures return HTTP 402.

Two finer orderings sit inside this ladder and are binding. On label issuance, the rated-opening check (`ERR_OPENING_NOT_RATED`) is evaluated before the finish-passed gate (`ERR_OPENING_NOT_FINISH_PASSED`). On beginning rework, the batch–order match (`ERR_REWORK_BATCH_ORDER_MISMATCH`) is evaluated before batch usability (`ERR_REWORK_BATCH_NOT_USABLE`).

### 2.6. Optimistic Concurrency Control on Pinned Parents

Two write operations draw serialized resources from, or pin a snapshot of, a parent entity, and those two operations carry mandatory expected-version fields. These are the only endpoints in the API that accept a version field; no other endpoint takes one.

- Creating a shop drawing revision requires the request to carry `expected_order_version`, holding the `version` of the target MillworkOrder as the client last observed it. Because the new revision pins the order's configuration, a client acting on a superseded view would pin the wrong configuration. If `expected_order_version` differs from the order's current `version` — because another writer has advanced the order since the client last read it — the create is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412).
- Issuing a label allocation requires the request to carry `expected_roll_version`, holding the `version` of the target FireLabelRoll as the client last observed it. Because issuance draws serialized labels from the roll, a stale view would draw serials already committed by another issuance. If `expected_roll_version` differs from the roll's current `version`, the create is rejected with `ERR_STALE_ROLL_VERSION` (HTTP 412).

### 2.7. Money, Gloss Units, and Rounding Discipline

All monetary values are integer cents. Every monetary calculation rounds half-up to whole cents at the step where the scaffold of a calculation calls for rounding, and every stored or returned money field — `budget_quote_cents`, `merchandise_total_cents`, `freight_fee_cents`, `contract_price_cents` — is an integer number of cents. Monetary values appear in responses as numbers, not strings.

Gloss is measured in gloss units. Sheen conformance compares a measured gloss reading against the batch's target in gloss units; the comparison tolerance is stated in §3.5 and its boundary is inclusive.

Truck fill percentages are numbers rounded half-up to exactly one decimal place. A fill of exactly half a tenth rounds upward.

### 2.8. Shop-Hour Windows: Half-Open Intervals on Machines and Booths

The shop schedules work in integer shop-hour indexes. A moulder setup slot occupies the window from its `start_hour` (inclusive) to its `end_hour` (exclusive), and a finishing batch occupies a cure window from its `cure_start_hour` (inclusive) to its `cure_end_hour` (exclusive). Two structural rules are enforced at payload time: a slot whose `end_hour` is not strictly later than its `start_hour` is rejected with `ERR_INVALID_SLOT_HOURS` (HTTP 400), and a cure window spanning fewer than four shop-hours is rejected with `ERR_INVALID_CURE_WINDOW` (HTTP 400).

Overlap has a precise half-open meaning everywhere in this API: a new window overlaps an existing window when the new window starts before the existing one ends and the existing one starts before the new one ends. Touching endpoints are not overlap — a window that begins exactly when another ends, or ends exactly when another begins, is adjacent and never counts as overlapping.

Machines and booths treat overlapping windows differently, and the difference is deliberate. A moulder machine is exclusive: one overlapping slot on the same machine is already too many, and a cross-species-family pair of windows must additionally respect a changeover buffer. A spray booth is shared: several batches may cure in overlapping windows up to the booth's `capacity`, but batches of different finish families may never share an overlapping window at all. The full rules live in §3.4 and §3.5.

### 2.9. Fire-Rating Governance and Segregation of Duties

Fire-rated work is governed as a cross-cutting compliance regime. Fire ratings are ranked `NONE`, then `MIN_20`, then `MIN_45`, then `MIN_90` in increasing severity; an opening may carry any rating up to and including the maximum its order declares. Serialized labels come on rolls whose `label_series` is one of `UL_20MIN`, `UL_45MIN`, or `UL_90MIN`, and the series must correspond exactly to the opening's rating — `MIN_20` openings draw from `UL_20MIN` rolls, `MIN_45` from `UL_45MIN`, and `MIN_90` from `UL_90MIN`. Every serial on a roll is accounted for at all times: the counts of issued, applied, spoiled, and available serials always sum to the roll's `serial_capacity`, and a spoiled serial is never returned to the available pool.

Three segregation-of-duties bans apply throughout. The architect approving a shop drawing must not be the user who submitted it. The QA inspector verifying a label allocation must be neither the user who issued it nor the user who applied it. The QA inspector verifying a resolved punch item must not be the user who reported it. Violations of the first ban surface as `ERR_SELF_APPROVAL_FORBIDDEN`; violations of the latter two surface as `ERR_SEGREGATION_OF_DUTIES_VIOLATION`.

### 2.10. Cascades, Dual Axes, and Terminal-State Discipline

State in this API propagates downward and sideways without waiting for explicit client requests. When a shop drawing is submitted, approved, or rejected, the parent order moves in lockstep. When a finishing batch passes measurement, every eligible opening of the order advances. When a trip departs and later arrives, every assigned opening moves along the shipping axis. When a punch item is authorized for rework, its opening falls back on the fabrication axis and its applied labels are voided. Each such cascade mutates its targets as real writes under §2.4.

The Opening is the one entity with two parallel state dimensions on a single resource: a fabrication axis tracked by `fab_status` (`QUEUED`, `MACHINED`, `FINISHED`, `LABELED`, `STAGED`, `REWORK`, `CANCELLED`) and a delivery axis tracked by `ship_status` (`UNSCHEDULED`, `SCHEDULED`, `SHIPPED`, `DELIVERED`, `PUNCH_LISTED`, `ACCEPTED`, `CANCELLED`). Both axes start together — an opening is created `QUEUED` and `UNSCHEDULED` — and both end together when an opening is cancelled, but in between they advance independently on different triggers.

Terminal states accept no transitions, and no from-to pair other than the ones narrated in §3 is permitted. An attempt at an undeclared pair is rejected with the entity's own invalid-transition error: `ERR_INVALID_PROJECT_STATUS_TRANSITION`, `ERR_INVALID_ORDER_STATUS_TRANSITION`, `ERR_INVALID_OPENING_STATUS_TRANSITION`, `ERR_INVALID_DRAWING_STATUS_TRANSITION`, `ERR_INVALID_PROGRAM_STATUS_TRANSITION`, `ERR_INVALID_SLOT_STATUS_TRANSITION`, `ERR_INVALID_BATCH_STATUS_TRANSITION`, `ERR_INVALID_ROLL_STATUS_TRANSITION`, `ERR_INVALID_ALLOCATION_STATUS_TRANSITION`, `ERR_INVALID_TRIP_STATUS_TRANSITION`, or `ERR_INVALID_PUNCH_STATUS_TRANSITION` (all HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Standing Up the Plant: Projects and Shop Resources

Work begins when a `PlantManager` registers a **Project** with a `name`, the jobsite's `site_address`, and a `contract_code`. The contract code must be unique across all projects in the system. A new project opens in `OPEN` status, and both order creation and trip planning are gated on that: attempting either against a project that is no longer `OPEN` fails with `ERR_PROJECT_NOT_OPEN`. When every order belonging to a project has reached `CLOSED` or `CANCELLED`, a `PlantManager` may mark the project `COMPLETED`; if any order is still mid-lifecycle the attempt fails with `ERR_ORDERS_NOT_TERMINAL`. A project may be archived from either `OPEN` or `COMPLETED` — both transitions are unconditional — and `ARCHIVED` is terminal. Any other project transition pair is rejected with `ERR_INVALID_PROJECT_STATUS_TRANSITION`. The project list can be filtered by `status`.

Four kinds of shop resource are registered by a `PlantManager` before production can be scheduled. A **HardwareTemplate** carries a unique `template_code`, a `manufacturer`, and the boolean `fire_rated_compatible`, which records whether the template's mortise pattern may be used on fire-rated openings; the template list filters by `template_code`. A **MoulderMachine** carries a unique `machine_code`, a `supported_species` list naming which species codes its tooling can run — a subset of `OAK`, `MAPLE`, `CHERRY`, `WALNUT`, and `PAINT_GRADE` — and an `active` flag that defaults to `true` at registration and records whether the machine currently accepts new setup slots; the machine list filters by `machine_code`. A **SprayBooth** carries a unique `booth_code` and a `capacity` — the maximum number of curing batches whose cure windows may overlap in that booth — which defaults to 2 when omitted; the booth list filters by `booth_code`. A **FireLabelRoll** is registered with a `label_series` of `UL_20MIN`, `UL_45MIN`, or `UL_90MIN` and a `serial_capacity` counting the total serialized labels on the roll; at registration `serials_issued`, `serials_applied`, and `serials_spoiled` are all zero, `serials_available` equals `serial_capacity`, and the roll is `ACTIVE`. The roll list filters by `label_series` and `status`.

### 3.2. Order Configuration and the Opening Schedule

Against an `OPEN` project, an `Estimator` creates a **MillworkOrder** by naming the project (`project_id`) and supplying an `order_code` that must be unique within that project — a duplicate fails with `ERR_ORDER_CODE_NOT_UNIQUE`. The configuration captured at creation is the full shop definition of the order: a `species` of `OAK`, `MAPLE`, `CHERRY`, `WALNUT`, or `PAINT_GRADE`; a `profile_code` identifying the sticking profile for the moulder knives; a `finish_system` of `CLEAR_COAT`, `STAIN`, or `PAINT`; a `sheen_target` of `MATTE`, `SATIN`, `SEMI_GLOSS`, or `HIGH_GLOSS`; a `hardware_prep_mode` of `TEMPLATE_PREP` (the plant mortises per template) or `INSTALLER_PREP` (the installer preps in the field); an optional `hardware_template_id` referencing the registered template to mortise against; and a `fire_rating_required` of `NONE`, `MIN_20`, `MIN_45`, or `MIN_90`, declaring the maximum fire rating any opening of the order may carry. A new order is `DRAFT` with `config_locked` false. The order list filters by `project_id`, `hardware_template_id`, and `status`.

Openings give the order its physical content. An `Estimator` adds an **Opening** by naming the order (`order_id`) and supplying an `opening_no` unique within the order (duplicates fail with `ERR_OPENING_NO_NOT_UNIQUE`), the opening's `width_in` and `height_in` in inches, its `fire_rating`, and the ISO `required_on_site_date` by which the opening must reach the jobsite. A `leaf_count` may be supplied for multi-leaf openings and defaults to 1. The opening's rating may not outrank the order's declared maximum under the severity ranking of §2.9; an opening demanding more than the order allows fails with `ERR_OPENING_RATING_EXCEEDS_ORDER`. Each new opening starts `QUEUED` on the fabrication axis and `UNSCHEDULED` on the delivery axis, with `assigned_trip_id` null. The opening list filters by `order_id`, `assigned_trip_id`, `fab_status`, and `ship_status`.

Configuration moves an order from `DRAFT` to `CONFIGURED` (an `Estimator` action) and runs four gates. First, at least one opening whose fabrication state is anything other than `CANCELLED` must exist, failing with `ERR_NO_OPENINGS`. Second, an order whose `hardware_prep_mode` is `TEMPLATE_PREP` must reference a template through `hardware_template_id`, failing with `ERR_TEMPLATE_REQUIRED`. Third, an order whose `fire_rating_required` is anything other than `NONE` must use `TEMPLATE_PREP` — field prep by an installer is forbidden on rated work — failing with `ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP` (HTTP 403). Fourth, such a rated order's referenced template must have `fire_rated_compatible` true, failing with `ERR_TEMPLATE_NOT_FIRE_RATED` (HTTP 403).

On a successful configure, the system computes and stores the provisional price in `budget_quote_cents` using the budget variant of order pricing. The base leaf price depends on the order's species: 42000 cents per leaf for `OAK`, 38000 for `MAPLE`, 51000 for `CHERRY`, 56000 for `WALNUT`, and 29000 for `PAINT_GRADE`. Every non-cancelled opening of the order contributes a line, regardless of fabrication state — at this point they are all queued. Each line is the opening's `leaf_count` multiplied by the species base price, then uplifted by a flat 12% waste allowance and a further flat 8% finish upcharge, with the result rounded half-up to whole cents; a flat hardware allowance of 5500 cents per opening is then added to the line. The budget quote is the sum of those lines plus a single flat freight allowance of 25000 cents.

While an order remains in `DRAFT` or `CONFIGURED`, an `Estimator` may still edit its configuration — any of `species`, `profile_code`, `finish_system`, `sheen_target`, `hardware_prep_mode`, `hardware_template_id`, or `fire_rating_required` — and each edit increments the order's `version`. Once the order has moved past `CONFIGURED` the configuration is locked (`config_locked` true from approval onward), and edit attempts fail with `ERR_ORDER_CONFIG_LOCKED`.

Cancellation is the estimator's escape hatch, available from `DRAFT`, `CONFIGURED`, `SUBMITTED`, or `APPROVED`; from any later state the request fails with `ERR_ORDER_NOT_CANCELLABLE`. Cancelling an order is a deep cascade: every opening in a non-terminal state becomes `CANCELLED` on both axes, any opening assigned to a trip is detached (its `assigned_trip_id` cleared) and the affected trips recompute their committed leaves; shop drawings in `DRAFT` or `SUBMITTED` move to `VOID` while an approved drawing moves to `SUPERSEDED`; machining programs in `CREATED`, `SETUP_BOOKED`, `PROVEN`, or `RELEASED` move to `VOIDED` and their booked slots move to `CANCELLED`; and label allocations of the order's openings in `ISSUED` or `APPLIED` move to `VOIDED`, with their serials passing into each roll's spoiled count, never to return. `CLOSED` and `CANCELLED` are the order's terminal states, and any other order transition pair fails with `ERR_INVALID_ORDER_STATUS_TRANSITION`.

### 3.3. Shop Drawings, Architect Review, and the Contract Price

Submittals are version-pinned snapshots. An `Estimator` creates a **ShopDrawing** revision against an order by naming the `order_id` and presenting `expected_order_version` under the concurrency rule of §2.6. Creation is only meaningful against a `CONFIGURED` order — anything else fails with `ERR_ORDER_NOT_CONFIGURED` — and only when no other drawing of the same order sits in `DRAFT` or `SUBMITTED`, failing otherwise with `ERR_ACTIVE_DRAWING_EXISTS`. The server assigns `revision_no` as one greater than the count of the order's existing drawings, links `supersedes_drawing_id` to the previous revision (null on the first), snapshots the order's current configuration into `pinned_species`, `pinned_profile_code`, `pinned_sheen_target`, `pinned_fire_rating_required`, and `pinned_hardware_prep_mode`, and creates the revision in `DRAFT`. Creating a revision is itself an order mutation and increments the order's `version` by one. The drawing list filters by `order_id`, `supersedes_drawing_id`, and `status`.

Submitting a drawing (an `Estimator` moving it from `DRAFT` to `SUBMITTED`) again requires the order to be `CONFIGURED` (`ERR_ORDER_NOT_CONFIGURED`) and no sibling drawing of the order to be in `SUBMITTED` (`ERR_ACTIVE_DRAWING_EXISTS`). Submission records the acting user in `submitted_by` and cascades the order from `CONFIGURED` to `SUBMITTED`, incrementing the order's `version`. From there the submittal belongs to the `Architect`. Approval moves the drawing from `SUBMITTED` to `APPROVED` and may carry an optional `review_note`; the approver's `X-User-ID` must differ from `submitted_by`, and a self-approval attempt fails with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403). Approval records `reviewed_by` and the `review_note`, cascades the order from `SUBMITTED` to `APPROVED`, sets `config_locked` true, and computes the contract price fields described below. If an earlier revision of the same order was still `APPROVED`, approval of the new revision supersedes it: the old drawing moves to `SUPERSEDED`, its machining programs in `CREATED`, `SETUP_BOOKED`, or `PROVEN` move to `VOIDED`, and those programs' booked setup slots move to `CANCELLED`. Rejection moves the drawing from `SUBMITTED` to `REJECTED`, records `reviewed_by` and the `review_note`, and returns the order from `SUBMITTED` to `CONFIGURED`. An estimator may also void a draft drawing outright, moving it from `DRAFT` to `VOID`. `REJECTED`, `SUPERSEDED`, and `VOID` are terminal, and any other drawing pair fails with `ERR_INVALID_DRAWING_STATUS_TRANSITION`. Every approval and rejection increments the order's `version`.

Approval is the moment the contract price is struck. The contract variant reprices the same non-cancelled openings the budget variant saw — by construction the two variants yield different totals for identical input. Each opening's contract line is built as follows: the opening's `leaf_count` is multiplied by the species base price, then by one plus the species' own waste allowance — 14% for `OAK`, 10% for `MAPLE`, 18% for `CHERRY`, 20% for `WALNUT`, and 8% for `PAINT_GRADE` — then by a finish-percentage factor whose tier is keyed on the total leaf count across the order's priced openings; that product is rounded half-up to whole cents. Added to the rounded figure are a hardware adjustment per opening — a charge of 8500 cents when the order is `TEMPLATE_PREP`, or a credit of 4000 cents when it is `INSTALLER_PREP` — and a per-leaf fire surcharge of 6000 cents for `MIN_20` openings, 9500 cents for `MIN_45`, and 14000 cents for `MIN_90`, while unrated openings contribute no surcharge.

The rounding order is pinned and non-negotiable: each opening's line is rounded to whole cents first, and only then are the rounded lines summed into `merchandise_total_cents`. Summing raw line values and rounding once at the end is wrong and produces different cents — for eleven lines whose raw value is 64392.6 cents, the pinned order yields 664323 while sum-then-round yields 664319.

Freight is then computed from `merchandise_total_cents` alone, never from the final contract price, which resolves the otherwise circular dependency between the freight tier and a total that includes freight. Merchandise below 500000 cents pays a flat 25000 cents. Merchandise from 500000 cents up to and including 2000000 cents pays four percent of the merchandise total, rounded half-up to whole cents. Merchandise strictly above 2000000 cents pays three percent, rounded half-up. The freight lands in `freight_fee_cents`, and `contract_price_cents` is the merchandise total plus the freight fee.

A computed read, the order's invoice summary, reports the rolled-up figures — `merchandise_total_cents`, `freight_fee_cents`, `contract_price_cents`, the provisional `budget_quote_cents`, and the priced `line_count` — recomputed under the same pinned rounding order.

When an approved order must change, an `Estimator` issues a change order, reverting the order from `APPROVED` to `CONFIGURED`. The change order is refused with `ERR_PRODUCTION_ALREADY_RELEASED` when a machining program in `RELEASED` status exists for the order's current approved drawing — released production may only be torn down by cancelling the order. Otherwise the cascade mirrors approval in reverse: the approved drawing moves to `SUPERSEDED`, its programs in `CREATED`, `SETUP_BOOKED`, or `PROVEN` move to `VOIDED`, their booked slots move to `CANCELLED`, `config_locked` returns to false, and the order's `version` increments.

### 3.4. Machining Programs and Moulder Setup Slots

With a drawing approved, a `ProductionLead` authors a **MachiningProgram** by naming the approved drawing (`drawing_id`), the order (`order_id`), and the `estimated_minutes` the run is expected to take. The referenced drawing must be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`), and the payload's `order_id` must equal the drawing's own order (`ERR_PROGRAM_ORDER_MISMATCH`). The server generates a `program_code` and creates the program in `CREATED` status. The program list filters by `drawing_id`, `order_id`, and `status`.

Before the line can run, the program needs machine time. Booking a **MoulderSetupSlot** — a `ProductionLead` action supplying `program_id`, `machine_id`, and the half-open window from `start_hour` to `end_hour` — requires the program to be in `CREATED` status (`ERR_PROGRAM_NOT_AWAITING_SETUP`) and is subject to the window rules of §2.8. The machine's `supported_species` must contain the program's order species; booking onto a machine that cannot run the species fails with `ERR_MACHINE_SPECIES_UNSUPPORTED` (HTTP 403). The slot's `species` is copied from the program's order at booking, because it drives the changeover buffer below. A booked slot is `BOOKED`, and the booking cascades the program from `CREATED` to `SETUP_BOOKED`.

Two scheduling rules protect the machine, both evaluated against the machine's existing slots in `BOOKED` or `COMPLETED` status. The overlap rule is absolute: any overlap under the half-open definition of §2.8 is rejected with `ERR_MACHINE_SLOT_OVERLAP`, while mere adjacency is always allowed. The changeover rule guards species families: `PAINT_GRADE` stock belongs to the paint family, while `OAK`, `MAPLE`, `CHERRY`, and `WALNUT` belong to the stain family. For a non-overlapping existing slot whose family differs from the new slot's, the gap between the windows — the shop-hours separating the earlier window's end from the later window's start, zero when they touch — must be at least two hours; a smaller cross-family gap is rejected with `ERR_CHANGEOVER_BUFFER_VIOLATION`, a gap of exactly two hours is permitted, and same-family neighbors never require a buffer.

Completing a booked slot (a `ProductionLead` moving it from `BOOKED` to `COMPLETED`) proves the first article and cascades the program from `SETUP_BOOKED` to `PROVEN`. Explicitly cancelling a booked slot returns its program from `SETUP_BOOKED` to `CREATED`; by contrast, a slot cancelled because its program was voided leaves the program `VOIDED`. From `PROVEN`, a `ProductionLead` releases the program to `RELEASED` — again requiring the referenced drawing to be `APPROVED` (`ERR_DRAWING_NOT_APPROVED`) — and release is what unlocks production on the order. A program may be voided from `CREATED`, `SETUP_BOOKED`, or `PROVEN` by a `ProductionLead` or by cascade, and voiding cancels its booked slots; a `RELEASED` program moves to `VOIDED` only through the order-cancellation cascade of §3.2, since a change order is blocked while one exists. Any other program pair — a direct jump from `CREATED` to `RELEASED`, say — fails with `ERR_INVALID_PROGRAM_STATUS_TRANSITION`, and undeclared slot pairs fail with `ERR_INVALID_SLOT_STATUS_TRANSITION`. The slot list filters by `machine_id`, `program_id`, and `status`.

With at least one `RELEASED` program on the order's current approved drawing, a `ProductionLead` moves the order from `APPROVED` to `IN_PRODUCTION`; without one the attempt fails with `ERR_NO_RELEASED_PROGRAM`. Only then may openings be machined: advancing an opening's fabrication axis from `QUEUED` to `MACHINED` requires the order to be `IN_PRODUCTION` and otherwise fails with `ERR_ORDER_NOT_IN_PRODUCTION`. Undeclared opening fabrication pairs — leaping from `QUEUED` straight to `STAGED`, or anything out of `CANCELLED` — fail with `ERR_INVALID_OPENING_STATUS_TRANSITION`. When every non-cancelled opening of the order has reached `MACHINED`, `FINISHED`, `LABELED`, or `STAGED`, a `ProductionLead` may move the order from `IN_PRODUCTION` to `FINISHING`; any straggler fails the transition with `ERR_OPENINGS_NOT_MACHINED`.

### 3.5. Finishing Batches and Sheen Conformance

Once an order is in finishing, a `ProductionLead` creates a **FinishingBatch** by naming the `order_id`, the `booth_id` whose cure window the batch will occupy, the half-open window from `cure_start_hour` to `cure_end_hour`, and optionally `is_rework_batch`, which defaults to false and marks a batch that refinishes rework openings. The cure window must span at least four shop-hours (`ERR_INVALID_CURE_WINDOW` per §2.8). A non-rework batch may only be created while the order is in `FINISHING` (`ERR_ORDER_NOT_FINISHING`), while a rework batch requires at least one opening of the order to be sitting in `REWORK` (`ERR_NO_REWORK_OPENINGS`). At creation the server copies the order's finish system into the batch's `finish_family` — `PAINT` maps to the paint family, while `CLEAR_COAT` and `STAIN` both map to the clear-stain family — and maps the order's sheen target into `sheen_target_gu`, the batch's gloss-unit goal: 15 for `MATTE`, 35 for `SATIN`, 60 for `SEMI_GLOSS`, and 85 for `HIGH_GLOSS`. A new batch is `MIXED`.

The booth's load discipline differs from the machine's in exactly one way: sharing is allowed up to capacity. Against the booth's existing batches in `MIXED`, `SPRAYED`, or `CURED`, the new batch's window is tested for overlap as in §2.8. If the number of overlapping existing batches already equals the booth's `capacity`, creation fails with `ERR_BOOTH_CAPACITY_EXCEEDED` (HTTP 402); an overlapping count exactly one below capacity is permitted. Independently of headroom, any overlapping existing batch whose finish family differs from the new batch's family is rejected with `ERR_BOOTH_PURGE_VIOLATION` (HTTP 403) — a booth never cures paint and clear-stain work in overlapping windows — while adjacent, non-overlapping batches of different families are allowed. The batch list filters by `order_id`, `booth_id`, and `status`.

A `ProductionLead` walks the batch from `MIXED` to `SPRAYED` and from `SPRAYED` to `CURED`; undeclared batch pairs — from `MIXED` straight to `CURED`, or anything out of the terminal states — fail with `ERR_INVALID_BATCH_STATUS_TRANSITION`. Quality gate sits at the end of the cure: a `QAInspector` submits a `sheen_measured_gu` reading for the batch, which is only accepted while the batch is `CURED` (`ERR_BATCH_NOT_CURED`). The server computes `delta_gu` as the absolute difference between the measured reading and the batch's `sheen_target_gu`. A deviation of no more than 2.0 gloss units passes — exactly 2.0 passes, while 2.1 fails — moving the batch to `PASSED`; anything greater moves it to `FAILED`. Both `sheen_measured_gu` and `delta_gu` are null until measured.

Passing a batch is the fabrication axis's great consolidator: every opening of the batch's order sitting in `MACHINED` or `REWORK` moves to `FINISHED`, and every punch item linked to this batch through `rework_batch_id` that is sitting in `IN_REWORK` moves to `RESOLVED`. A failed batch changes nothing downstream; the openings stay where they are.

### 3.6. Serialized Fire Labels: Issuance, Application, Verification

Rated openings cannot leave the shop unlabeled, and the label supply is the serialized roll of §3.1. A `LabelAuthority` issues a **LabelAllocation** by naming the `opening_id`, the `roll_id` to draw serials from, and `expected_roll_version` under the concurrency rule of §2.6. Issuance runs its gates in a fixed order: first the opening must be rated — its `fire_rating` something other than `NONE` — failing with `ERR_OPENING_NOT_RATED`; then the opening's fabrication axis must be `FINISHED`, failing with `ERR_OPENING_NOT_FINISH_PASSED`. The roll must be `ACTIVE` (`ERR_ROLL_NOT_ACTIVE`), the opening must not already hold an allocation in `ISSUED`, `APPLIED`, or `VERIFIED` (`ERR_ACTIVE_ALLOCATION_EXISTS`), and the roll's `label_series` must match the opening's rating per the correspondence of §2.9 (`ERR_LABEL_SERIES_MISMATCH`, HTTP 403). Finally the roll must have enough stock: when `serials_available` is smaller than the opening's `leaf_count`, issuance fails with `ERR_INSUFFICIENT_LABEL_SERIALS` (HTTP 402).

A successful issuance draws one label per leaf: `serial_count` is set to the opening's `leaf_count`, the acting user is recorded as `issued_by`, and the allocation is `ISSUED`. On the roll, `serials_issued` grows and `serials_available` shrinks by that count, and the roll's `version` increments by one. The allocation list filters by `opening_id`, `roll_id`, and `status`.

Application is the shop floor's step: a `ProductionLead` moves an `ISSUED` allocation to `APPLIED`, again requiring the opening's fabrication axis to be `FINISHED` (`ERR_OPENING_NOT_FINISH_PASSED`) and the roll to be `ACTIVE` (`ERR_ROLL_NOT_ACTIVE`). Application records `applied_by`, moves the opening's fabrication axis from `FINISHED` to `LABELED`, shifts the allocation's serials on the roll from `serials_issued` into `serials_applied`, and increments the roll's `version`. Whenever a roll's available count reaches zero while no serials remain outstanding in issued allocations, the roll moves itself from `ACTIVE` to `DEPLETED` — application included. Verification closes the loop: a `QAInspector` moves an `APPLIED` allocation to `VERIFIED`, recording `verified_by`, and per §2.9 the verifier's `X-User-ID` must equal neither `issued_by` nor `applied_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, HTTP 403). Undeclared allocation pairs — issuing straight to `VERIFIED`, or anything out of `VERIFIED` or `VOIDED` — fail with `ERR_INVALID_ALLOCATION_STATUS_TRANSITION`.

Labels can also be destroyed. A `LabelAuthority` may void an `ISSUED` allocation, which moves its serials from `serials_issued` into `serials_spoiled` and increments the roll's `version`. When a punch item on the opening is authorized for rework (§3.8), the opening's allocations in `APPLIED` or `VERIFIED` are voided by cascade — the label is physically destroyed in rework — and those serials move from `serials_applied` into `serials_spoiled`, again bumping the roll's `version`. The conservation invariant of §2.9 holds after every one of these operations: issued plus applied plus spoiled plus available always equals `serial_capacity`, and spoiled serials never return. A `LabelAuthority` may retire an `ACTIVE` roll only when no serials remain outstanding in issued allocations — `serials_issued` must be zero — failing otherwise with `ERR_OUTSTANDING_SERIALS`; `DEPLETED` and `RETIRED` are terminal, and any other roll pair fails with `ERR_INVALID_ROLL_STATUS_TRANSITION`.

Labels gate staging. A `ProductionLead` stages a non-rated opening directly from `FINISHED` to `STAGED`; a rated opening attempting that same direct move is rejected with `ERR_LABELING_REQUIRED`, because rated work must pass through `LABELED`. Moving a `LABELED` opening to `STAGED` requires an allocation on the opening to have reached `VERIFIED`, failing otherwise with `ERR_LABEL_NOT_VERIFIED`. Once every non-cancelled opening of the order sits in `STAGED`, a `ProductionLead` moves the order from `FINISHING` to `READY_TO_SHIP`; any opening short of staging fails the transition with `ERR_OPENINGS_NOT_STAGED`.

### 3.7. Delivery Trips and the Opening Shipping Axis

Logistics begins when a `PlantManager` plans a **DeliveryTrip** for an `OPEN` project (`ERR_PROJECT_NOT_OPEN` otherwise), supplying the `project_id`, a `trip_code`, the truck's `truck_capacity_leaves`, a `departure_date`, and the jobsite `site_arrival_date`. An arrival date earlier than the departure date is rejected with `ERR_INVALID_TRIP_DATES` (HTTP 400). A new trip is `PLANNED` with `leaves_committed` at zero, and the trip list filters by `project_id` and `status`.

A `ShippingCoordinator` builds the manifest by assigning openings, one `opening_id` at a time, to a `PLANNED` trip — assigning to a trip in any other state fails with `ERR_INVALID_TRIP_STATUS_TRANSITION`. Five gates guard assignment. The opening's fabrication axis must be `STAGED` (`ERR_OPENING_NOT_STAGED`); its shipping axis must be `UNSCHEDULED` (`ERR_OPENING_ALREADY_SCHEDULED`); the opening's order must belong to the same project the trip serves (`ERR_TRIP_PROJECT_MISMATCH`); the trip's `site_arrival_date` must not fall after the opening's `required_on_site_date` (`ERR_DELIVERY_WINDOW_MISSED`); and the opening's `leaf_count` added to the trip's `leaves_committed` must not exceed `truck_capacity_leaves` — an exact fit is permitted, an overflow fails with `ERR_TRUCK_CAPACITY_EXCEEDED` (HTTP 402). A successful assignment moves the opening's shipping axis from `UNSCHEDULED` to `SCHEDULED`, sets its `assigned_trip_id`, adds its leaves to `leaves_committed`, recomputes the trip's `projected_fill_pct`, and increments the trip's `version`.

Unassignment is the exact compensating action, also by a `ShippingCoordinator`, also requiring the trip `PLANNED`, and requiring that the opening's `assigned_trip_id` names this trip (`ERR_OPENING_NOT_ON_TRIP`). It returns the opening to `UNSCHEDULED`, clears `assigned_trip_id`, subtracts the opening's leaves from `leaves_committed`, and increments the trip's `version`. The pair is conservative: an assign followed by the matching unassign leaves the trip's committed leaves, the opening's shipping axis, and the opening's trip reference exactly as they were before.

Two fill figures track the truck. The forward-looking `projected_fill_pct` divides the committed leaves plus the leaves of every opening of the trip's project that is `STAGED` but still `UNSCHEDULED` by `truck_capacity_leaves`, multiplies by one hundred, and rounds half-up to one decimal; it is recomputed on every assign and unassign and on each read. The settled `realized_fill_pct` counts only the committed leaves actually on the truck under the same formula and precision, is computed and frozen at departure, and is null until the trip departs. Whenever staged-but-unscheduled openings exist in the project, the two figures diverge for identical trip data by construction.

Departure moves the trip from `PLANNED` to `DEPARTED` (a `ShippingCoordinator` action) under two gates: at least one opening must be assigned (`ERR_NO_OPENINGS_ASSIGNED`), and every assigned opening's fabrication axis must be `STAGED` (`ERR_OPENINGS_NOT_STAGED`). Departure cascades every assigned opening's shipping axis from `SCHEDULED` to `SHIPPED` and computes `realized_fill_pct`. Arrival moves the trip from `DEPARTED` to `DELIVERED` and cascades the assigned openings from `SHIPPED` to `DELIVERED`. Closing a delivered trip requires every assigned opening to have reached `ACCEPTED` on the shipping axis (`ERR_OPENINGS_NOT_ACCEPTED`). Cancelling a `PLANNED` trip returns its assigned openings to `UNSCHEDULED`, clears their trip references, and zeroes `leaves_committed`. `CLOSED` and `CANCELLED` are terminal, and any other trip pair — such as `PLANNED` straight to `DELIVERED` — fails with `ERR_INVALID_TRIP_STATUS_TRANSITION`.

On the order side, a `ShippingCoordinator` moves the order from `READY_TO_SHIP` to `SHIPPED` once every non-cancelled opening's shipping axis is `SHIPPED`, `DELIVERED`, `PUNCH_LISTED`, or `ACCEPTED`; any opening short of that set fails the transition with `ERR_OPENINGS_NOT_SHIPPED`.

### 3.8. Punch-List Rework and Final Acceptance

Delivery is not acceptance. A `QAInspector` or an `Architect` reports a **PunchItem** against a delivered opening by naming the `opening_id`, a `category` of `FINISH_DEFECT`, `HARDWARE_MISALIGNMENT`, `TRANSIT_DAMAGE`, or `LABEL_MISSING`, a `severity` of `MINOR` or `MAJOR`, and a free-text `description`. Reporting requires the opening's shipping axis to be `DELIVERED` or `PUNCH_LISTED` (`ERR_OPENING_NOT_DELIVERED`). The report is created in `REPORTED` status with the acting user captured as `reported_by`, and the first report on a `DELIVERED` opening moves that opening's shipping axis from `DELIVERED` to `PUNCH_LISTED`. The punch list filters by `opening_id`, `rework_batch_id`, and `status`.

Triage is QA's: a `QAInspector` moves an item from `REPORTED` to `TRIAGED`, and may discard an invalid report from `TRIAGED` to `REJECTED_INVALID`. Authorizing rework is the plant manager's call and is reserved for serious defects: a `PlantManager` moves a `TRIAGED` item to `REWORK_AUTHORIZED` only when its `severity` is `MAJOR`, failing otherwise with `ERR_PUNCH_NOT_MAJOR`. Authorization cascades hard: the opening's fabrication axis falls back from `FINISHED`, `LABELED`, or `STAGED` to `REWORK`, and the opening's label allocations in `APPLIED` or `VERIFIED` are voided per §3.6, their serials passing from applied to spoiled on each roll with the roll's `version` bumped.

A `ProductionLead` then begins rework, moving the item from `REWORK_AUTHORIZED` to `IN_REWORK`, optionally naming a `rework_batch_id` that is recorded on the item. Two checks run in a fixed order: when a `rework_batch_id` is supplied, its batch's order must equal the punch opening's order (`ERR_REWORK_BATCH_ORDER_MISMATCH`, checked first); and for a `FINISH_DEFECT` item the `rework_batch_id` is mandatory and must name a batch whose `is_rework_batch` is true and whose status is `MIXED`, `SPRAYED`, or `CURED` — a missing batch id on a finish defect, a non-rework batch, or a batch outside those statuses all fail with `ERR_REWORK_BATCH_NOT_USABLE`.

Resolution arrives by two routes. A batch-linked finish defect resolves by cascade when its linked rework batch passes measurement per §3.5. Any other in-rework item — one without a linked batch — is resolved directly by a `ProductionLead`; the same direct resolve is also the disposition for a `MINOR` item still in `TRIAGED`. Resolving anything else fails with `ERR_PUNCH_NOT_RESOLVABLE`: the resolve capability requires either a triaged minor item or an in-rework item with no linked batch. A `RESOLVED` item is verified by a `QAInspector` moving it to `VERIFIED`, which requires the verifier's `X-User-ID` to differ from `reported_by` (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`) and the opening's fabrication axis to have been driven back to `STAGED` (`ERR_OPENING_NOT_RESTAGED`). `VERIFIED` and `REJECTED_INVALID` are terminal, and undeclared punch pairs — reporting straight to `VERIFIED`, for instance — fail with `ERR_INVALID_PUNCH_STATUS_TRANSITION`.

Final acceptance belongs to the `QAInspector` and acts on the opening's shipping axis, which must be `DELIVERED` or `PUNCH_LISTED` (`ERR_OPENING_NOT_DELIVERED`). Accepting a `DELIVERED` opening requires that no punch item on the opening sit in `REPORTED`, `TRIAGED`, `REWORK_AUTHORIZED`, `IN_REWORK`, or `RESOLVED` (`ERR_OPEN_PUNCH_ITEMS`). Accepting a `PUNCH_LISTED` opening requires every punch item on it to be `VERIFIED` or `REJECTED_INVALID` (`ERR_OPEN_PUNCH_ITEMS`) and the fabrication axis to be fully re-staged at `STAGED` (`ERR_OPENING_NOT_RESTAGED`). Acceptance moves the shipping axis to `ACCEPTED`.

Closure then rolls upward. A `PlantManager` moves a `SHIPPED` order to `CLOSED` when every non-cancelled opening sits at `ACCEPTED` (`ERR_OPENINGS_NOT_ACCEPTED`) and no punch item on any opening of the order remains in `REPORTED`, `TRIAGED`, `REWORK_AUTHORIZED`, `IN_REWORK`, or `RESOLVED` (`ERR_OPEN_PUNCH_ITEMS`). And with every order of a project at `CLOSED` or `CANCELLED`, the project itself may be marked `COMPLETED` per §3.1 — the loop from configuration to jobsite acceptance fully closed.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — status transitions, configuration edits, assignments, measurements, and the change-order, accept, begin-rework, and resolve actions — return `200 OK`. Reads return `200 OK`. Status-transition requests carry the desired state in a `target_status` field — the opening fabrication-axis endpoint alone uses `target_fab_status` instead — and drawing review may additionally carry a `review_note`. The table below is a routing summary only; request fields, preconditions, cascades, and computed values are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/millwork/projects` | Create a project | PlantManager |
| GET | `/millwork/projects` | List projects | Any |
| GET | `/millwork/projects/{id}` | Get a project | Any |
| PUT | `/millwork/projects/{id}/status` | Transition project status | PlantManager |
| POST | `/millwork/hardware-templates` | Register a hardware prep template | PlantManager |
| GET | `/millwork/hardware-templates` | List hardware templates | Any |
| GET | `/millwork/hardware-templates/{id}` | Get a hardware template | Any |
| POST | `/millwork/moulder-machines` | Register a moulder machine | PlantManager |
| GET | `/millwork/moulder-machines` | List moulder machines | Any |
| GET | `/millwork/moulder-machines/{id}` | Get a moulder machine | Any |
| POST | `/millwork/spray-booths` | Register a spray booth | PlantManager |
| GET | `/millwork/spray-booths` | List spray booths | Any |
| GET | `/millwork/spray-booths/{id}` | Get a spray booth | Any |
| POST | `/millwork/fire-label-rolls` | Register a serialized fire-label roll | PlantManager |
| GET | `/millwork/fire-label-rolls` | List fire label rolls | Any |
| GET | `/millwork/fire-label-rolls/{id}` | Get a fire label roll | Any |
| PUT | `/millwork/fire-label-rolls/{id}/status` | Retire a roll | LabelAuthority |
| POST | `/millwork/orders` | Create an order (DRAFT) | Estimator |
| GET | `/millwork/orders` | List orders | Any |
| GET | `/millwork/orders/{id}` | Get an order | Any |
| PUT | `/millwork/orders/{id}` | Edit order configuration while unlocked | Estimator |
| PUT | `/millwork/orders/{id}/status` | Transition order status (per-target actor: CONFIGURED = Estimator; IN_PRODUCTION, FINISHING, READY_TO_SHIP = ProductionLead; SHIPPED = ShippingCoordinator; CLOSED = PlantManager; CANCELLED = Estimator) | Estimator, ProductionLead, ShippingCoordinator, PlantManager |
| POST | `/millwork/orders/{id}/change-order` | Revert an APPROVED order to CONFIGURED, superseding the approved drawing | Estimator |
| GET | `/millwork/orders/{id}/invoice-summary` | Computed read: per-line totals and rolled-up invoice figures | Any |
| POST | `/millwork/openings` | Add an opening to an order | Estimator |
| GET | `/millwork/openings` | List openings | Any |
| GET | `/millwork/openings/{id}` | Get an opening | Any |
| PUT | `/millwork/openings/{id}/status` | Advance the fabrication axis (MACHINED or STAGED) | ProductionLead |
| POST | `/millwork/openings/{id}/accept` | Accept a delivered or punch-listed opening | QAInspector |
| POST | `/millwork/shop-drawings` | Create a DRAFT drawing revision pinning the order's current configuration (OCC on order version) | Estimator |
| GET | `/millwork/shop-drawings` | List shop drawings | Any |
| GET | `/millwork/shop-drawings/{id}` | Get a shop drawing | Any |
| PUT | `/millwork/shop-drawings/{id}/status` | Submit, approve, reject, or void a drawing (SUBMITTED, VOID = Estimator; APPROVED, REJECTED = Architect) | Estimator, Architect |
| POST | `/millwork/machining-programs` | Create a machining program for an APPROVED drawing | ProductionLead |
| GET | `/millwork/machining-programs` | List machining programs | Any |
| GET | `/millwork/machining-programs/{id}` | Get a machining program | Any |
| PUT | `/millwork/machining-programs/{id}/status` | Release or void a program | ProductionLead |
| POST | `/millwork/moulder-setup-slots` | Book a moulder setup slot for a CREATED program | ProductionLead |
| GET | `/millwork/moulder-setup-slots` | List moulder setup slots | Any |
| GET | `/millwork/moulder-setup-slots/{id}` | Get a setup slot | Any |
| PUT | `/millwork/moulder-setup-slots/{id}/status` | Complete or cancel a booked slot | ProductionLead |
| POST | `/millwork/finishing-batches` | Create a finishing batch occupying a booth cure window | ProductionLead |
| GET | `/millwork/finishing-batches` | List finishing batches | Any |
| GET | `/millwork/finishing-batches/{id}` | Get a finishing batch | Any |
| PUT | `/millwork/finishing-batches/{id}/status` | Advance a batch (SPRAYED, CURED) | ProductionLead |
| POST | `/millwork/finishing-batches/{id}/measure` | QA sheen measurement; PASSED when the gloss deviation is within tolerance, else FAILED | QAInspector |
| POST | `/millwork/label-allocations` | Issue serialized labels for a rated FINISHED opening (OCC on roll version) | LabelAuthority |
| GET | `/millwork/label-allocations` | List label allocations | Any |
| GET | `/millwork/label-allocations/{id}` | Get a label allocation | Any |
| PUT | `/millwork/label-allocations/{id}/status` | Apply, verify, or void an allocation (APPLIED = ProductionLead; VERIFIED = QAInspector; VOIDED = LabelAuthority) | ProductionLead, QAInspector, LabelAuthority |
| POST | `/millwork/delivery-trips` | Plan a delivery trip | PlantManager |
| GET | `/millwork/delivery-trips` | List delivery trips | Any |
| GET | `/millwork/delivery-trips/{id}` | Get a delivery trip | Any |
| POST | `/millwork/delivery-trips/{id}/assign` | Assign a STAGED opening to a PLANNED trip | ShippingCoordinator |
| POST | `/millwork/delivery-trips/{id}/unassign` | Remove an opening from a PLANNED trip | ShippingCoordinator |
| PUT | `/millwork/delivery-trips/{id}/status` | Transition a trip (DEPARTED, DELIVERED, CLOSED, CANCELLED) | ShippingCoordinator |
| POST | `/millwork/punch-items` | Report a punch-list deficiency on a delivered opening | QAInspector, Architect |
| GET | `/millwork/punch-items` | List punch items | Any |
| GET | `/millwork/punch-items/{id}` | Get a punch item | Any |
| PUT | `/millwork/punch-items/{id}/status` | Transition a punch item (TRIAGED, REJECTED_INVALID, VERIFIED = QAInspector; REWORK_AUTHORIZED = PlantManager) | QAInspector, PlantManager |
| POST | `/millwork/punch-items/{id}/begin-rework` | Start rework, optionally linking a rework finishing batch (required for FINISH_DEFECT) | ProductionLead |
| POST | `/millwork/punch-items/{id}/resolve` | Resolve a MINOR triaged item or a non-batch in-rework item | ProductionLead |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is the canonical id-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_OPENING_NOT_FOUND` | 404 Not Found |
| `ERR_DRAWING_NOT_FOUND` | 404 Not Found |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_MACHINE_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_BOOTH_NOT_FOUND` | 404 Not Found |
| `ERR_BATCH_NOT_FOUND` | 404 Not Found |
| `ERR_ROLL_NOT_FOUND` | 404 Not Found |
| `ERR_ALLOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_TRIP_NOT_FOUND` | 404 Not Found |
| `ERR_PUNCH_NOT_FOUND` | 404 Not Found |
| `ERR_TEMPLATE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_SLOT_HOURS` | 400 Bad Request |
| `ERR_INVALID_CURE_WINDOW` | 400 Bad Request |
| `ERR_INVALID_TRIP_DATES` | 400 Bad Request |
| `ERR_STALE_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_ROLL_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PROJECT_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_ORDER_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_OPENING_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_DRAWING_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_PROGRAM_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_SLOT_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_BATCH_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_ALLOCATION_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_TRIP_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_PUNCH_STATUS_TRANSITION` | 409 Conflict |
| `ERR_INVALID_ROLL_STATUS_TRANSITION` | 409 Conflict |
| `ERR_PROJECT_NOT_OPEN` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIGURED` | 409 Conflict |
| `ERR_ORDER_CONFIG_LOCKED` | 409 Conflict |
| `ERR_ORDER_NOT_IN_PRODUCTION` | 409 Conflict |
| `ERR_ORDER_NOT_FINISHING` | 409 Conflict |
| `ERR_NO_OPENINGS` | 409 Conflict |
| `ERR_OPENINGS_NOT_MACHINED` | 409 Conflict |
| `ERR_OPENINGS_NOT_STAGED` | 409 Conflict |
| `ERR_OPENINGS_NOT_SHIPPED` | 409 Conflict |
| `ERR_OPENINGS_NOT_ACCEPTED` | 409 Conflict |
| `ERR_OPEN_PUNCH_ITEMS` | 409 Conflict |
| `ERR_ORDERS_NOT_TERMINAL` | 409 Conflict |
| `ERR_PRODUCTION_ALREADY_RELEASED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_NO_RELEASED_PROGRAM` | 409 Conflict |
| `ERR_PROGRAM_NOT_AWAITING_SETUP` | 409 Conflict |
| `ERR_BATCH_NOT_CURED` | 409 Conflict |
| `ERR_NO_REWORK_OPENINGS` | 409 Conflict |
| `ERR_OPENING_NOT_DELIVERED` | 409 Conflict |
| `ERR_OPENING_NOT_STAGED` | 409 Conflict |
| `ERR_OPENING_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_OPENING_NOT_ON_TRIP` | 409 Conflict |
| `ERR_NO_OPENINGS_ASSIGNED` | 409 Conflict |
| `ERR_OPENING_NOT_FINISH_PASSED` | 409 Conflict |
| `ERR_OPENING_NOT_RESTAGED` | 409 Conflict |
| `ERR_LABELING_REQUIRED` | 409 Conflict |
| `ERR_LABEL_NOT_VERIFIED` | 409 Conflict |
| `ERR_OPENING_NOT_RATED` | 409 Conflict |
| `ERR_ROLL_NOT_ACTIVE` | 409 Conflict |
| `ERR_OUTSTANDING_SERIALS` | 409 Conflict |
| `ERR_PUNCH_NOT_MAJOR` | 409 Conflict |
| `ERR_PUNCH_NOT_RESOLVABLE` | 409 Conflict |
| `ERR_REWORK_BATCH_NOT_USABLE` | 409 Conflict |
| `ERR_DRAWING_NOT_APPROVED` | 409 Conflict |
| `ERR_MACHINE_SPECIES_UNSUPPORTED` | 403 Forbidden |
| `ERR_LABEL_SERIES_MISMATCH` | 403 Forbidden |
| `ERR_RATED_ORDER_REQUIRES_TEMPLATE_PREP` | 403 Forbidden |
| `ERR_TEMPLATE_NOT_FIRE_RATED` | 403 Forbidden |
| `ERR_SELF_APPROVAL_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_BOOTH_PURGE_VIOLATION` | 403 Forbidden |
| `ERR_ORDER_CODE_NOT_UNIQUE` | 409 Conflict |
| `ERR_OPENING_NO_NOT_UNIQUE` | 409 Conflict |
| `ERR_ACTIVE_DRAWING_EXISTS` | 409 Conflict |
| `ERR_ACTIVE_ALLOCATION_EXISTS` | 409 Conflict |
| `ERR_MACHINE_SLOT_OVERLAP` | 409 Conflict |
| `ERR_CHANGEOVER_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_PROGRAM_ORDER_MISMATCH` | 409 Conflict |
| `ERR_TEMPLATE_REQUIRED` | 409 Conflict |
| `ERR_TRIP_PROJECT_MISMATCH` | 409 Conflict |
| `ERR_REWORK_BATCH_ORDER_MISMATCH` | 409 Conflict |
| `ERR_OPENING_RATING_EXCEEDS_ORDER` | 409 Conflict |
| `ERR_DELIVERY_WINDOW_MISSED` | 409 Conflict |
| `ERR_INSUFFICIENT_LABEL_SERIALS` | 402 Payment Required |
| `ERR_TRUCK_CAPACITY_EXCEEDED` | 402 Payment Required |
| `ERR_BOOTH_CAPACITY_EXCEEDED` | 402 Payment Required |

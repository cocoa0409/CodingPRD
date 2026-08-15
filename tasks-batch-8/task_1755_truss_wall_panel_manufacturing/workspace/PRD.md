# Truss & Wall-Panel Manufacturing API — Product Requirements Document

## 1. Introduction

This document specifies the API for a component manufacturing plant that produces engineered roof trusses, floor trusses, and wall panels for builder customers. The system runs the plant end to end: customer accounts and credit terms, engineer-of-record registration, job intake against a closed jobsite delivery window, component design and professional-engineer seal, cut-list explosion with waste-adjusted lumber and plate requirements, inventory lot ledgering, production batching sequenced by requested completion and jig changeover, buffered crane picks, shipping loads with bundle maps and dispatch gates, final freight and storage settlement, field-damage claims with rebuild cascades, and design change orders applied after cutting has already begun.

Two structural realities of the business shape every workflow in this document. First, material is finite: lumber and plate lots are received in fixed quantities, reserved against cut-list lines, consumed when a batch enters cutting, and scrapped when members are wasted — the plant's inventory ledger must conserve every board foot and every plate across these movements. Second, time is contractual: delivery windows close, jobsites accept only a bounded number of drops per day, cranes must be booked with mandatory buffers, staged loads accrue storage fees after a free-days allowance, and an engineer's license expires at a fixed instant. All of these temporal rules read a single server-side logical clock described in §2.5, never wall-clock time.

All endpoints are mounted under the `/plant` path prefix. The document is organized as global system-wide specifications (§2), business workflows (§3), the endpoint contract (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. The system recognizes exactly eight roles: `PlantManager`, `DesignEngineer`, `ProductionPlanner`, `InventoryManager`, `ShopFloorLead`, `ShippingCoordinator`, `ClaimsAdjuster`, and `CustomerContact`. A request with missing headers, an undeclared role, or — for entity-backed roles — an `X-User-ID` that does not resolve to an existing instance of the backing entity is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not in the endpoint's authorized list is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Two roles are entity-backed. When `X-User-Role` is `DesignEngineer`, `X-User-ID` is the `id` of the acting `Engineer`; seal-attribution fields such as `submitted_by_engineer_id` and `sealed_by_engineer_id` are populated from this header. When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `CustomerAccount`; ownership checks on any resource that references a customer compare the resource's `customer_id` (directly, or through its owning job) to `X-User-ID`, and a `CustomerContact` acting outside its own customer scope — creating a job for another customer, filing a claim against another customer's delivery, withdrawing another customer's change order, or reading another customer's jobs, designs, loads, claims, or change orders — is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403).

The remaining six roles carry opaque identities. When `X-User-Role` is `PlantManager`, `ProductionPlanner`, `InventoryManager`, `ShopFloorLead`, `ShippingCoordinator`, or `ClaimsAdjuster`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `requested_by` on a change order or as `triaged_by` and `decided_by` on a damage claim — but never compares it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`. Many list endpoints additionally accept resource-specific filter parameters — for example `status`, `job_id`, or `customer_id` — which are introduced alongside each resource in §3.

### 2.4. Resource Identity, Timestamps, and Versioning

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `created_at` is fixed at creation, while `updated_at` refreshes on every mutation. The `version` field is an integer that increments by exactly 1 on every mutation of the resource, including mutations the server applies as cascade side effects — a reservation release that restores a lot's availability, for instance, increments that lot's `version`.

One resource is the exception: a `JigSetup` is immutable after creation and carries only `id` and `created_at`. Both `updated_at` and `version` are absent from it.

### 2.5. The Plant Logical Clock

The server maintains a single logical clock that every temporal rule in this document reads: license expiry, delivery-window containment, dispatch deadlines, storage-day accrual, and slot-in-past checks all evaluate against it. Before any call to the clock-setting capability, the logical clock reads exactly 2026-08-01T00:00:00Z — the startup default — and it never falls back to wall-clock time. A `PlantManager` may advance the clock by supplying a `to_iso8601` instant; the capability responds with the resulting `current_utc`. Nothing else in the API moves the clock.

### 2.6. Optimistic Concurrency Control on Parent Versions

Four creation endpoints participate in optimistic concurrency control against a parent entity's `version`. Each requires a non-optional expected-version field carrying the client's last observed `version` of the parent; if the parent's current `version` has advanced since that read, the create is rejected purely on the version mismatch — the request is treated as acting on a stale view, regardless of whether the payload would otherwise succeed:

- `POST /plant/material-reservations` requires `expected_lot_version` matching the target lot's current `version`; a mismatch is rejected with `ERR_STALE_LOT_VERSION` (HTTP 412). Another writer may legitimately have created, consumed, or released a reservation against the same lot, mutating its availability, so the current writer's view of remaining availability is stale.
- `POST /plant/jobs/{job_id}/designs` requires `expected_job_version` matching the target job's current `version`; a mismatch is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). A new design revision legitimately coexists with — and is intended to supersede — the current sealed revision, so a sequential second create would otherwise succeed on a stale job view.
- `POST /plant/jobs/{job_id}/change-orders` likewise requires `expected_job_version`; a mismatch is rejected with `ERR_STALE_JOB_VERSION` (HTTP 412). A second change order against the same sealed design is a legitimate product operation, so the stale-view create is rejected to force the writer to re-read the job.
- `POST /plant/crane-slots` requires `expected_crane_version` matching the target crane's current `version`; a mismatch is rejected with `ERR_STALE_CRANE_VERSION` (HTTP 412). A non-overlapping slot would legitimately succeed on the updated crane, so the stale-view booking is rejected purely on the version.

Endpoints not listed here do not take a version field.

### 2.7. Validation Order and Nested Path Resolution

Every request is validated in a fixed priority order, and when a request violates several rules the rejection reported is the one earliest in that order. Authentication comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_FORBIDDEN_ROLE`), then customer-ownership scope (`ERR_FORBIDDEN_OWNERSHIP`), then existence (`ERR_NOT_FOUND`), then request schema (`ERR_INVALID_REQUEST`), then the optimistic-concurrency version checks of §2.6 (the stale-version errors). Only after all six universal layers pass do state-machine guards and business rules run, in the orders stated within each §3 workflow.

Existence validation covers every identifier in the URL path and every foreign key in the request body, checked left-to-right: path identifiers in template order first, then body fields in their declared input order. A request naming a non-existent job in the path therefore fails with `ERR_NOT_FOUND` before any body reference is examined, and a body naming a non-existent lot fails before any state or business rule runs.

Schema validation (`ERR_INVALID_REQUEST`, HTTP 400) covers required-field presence, type agreement, enum membership within the declared sets, and the conditional-input rules scattered through §3: lumber attributes are required exactly when a lot's `lot_kind` is `LUMBER`, plate attributes exactly when it is `PLATE`; `rescheduled_date` is required exactly when a load transition's `to_state` is `RESCHEDULED`; `crane_hours_actual` exactly when `to_state` is `CLOSED`; `damage_pct` is required on a claim decision unless the decision is `DENY`; a reservation carries exactly one of `cut_list_line_id` and `cut_list_id`; a plate lot's `received_board_feet` must be 0 and a lumber lot's `received_plates` must be 0; a crane slot's `end_at` must be strictly after its `start_at`; and a job's `delivery_window_end` must be on or after its `delivery_window_start`.

### 2.8. Board-Foot and Plate Conservation

Every inventory lot behaves as a conservation ledger. For a lumber lot, the quantities `available_bf`, `reserved_bf`, `consumed_bf`, and `scrapped_bf` partition what was received: reserving moves board feet from available to reserved, releasing moves them back to available exactly (release is the compensating action of reserve), consuming moves them from reserved to consumed, and scrapping moves them from consumed to scrapped. The four quantities together with any manual adjustments always account for the received volume — no board foot is created or destroyed by any transition. Plate lots mirror this ledger with `available_plates`, `reserved_plates`, `consumed_plates`, and `scrapped_plates`. Manual physical-count corrections post through the adjustment capability and are included in the conservation sum.

A lot whose available and reserved quantities have all reached zero — `available_bf`, `reserved_bf`, `available_plates`, and `reserved_plates` all equal to 0, on a lot that actually received something (its `received_board_feet` plus `received_plates` greater than 0) — is automatically transitioned from `ACTIVE` to `DEPLETED` after any consume, release, or adjustment that produces that state.

### 2.9. Precision, Rounding, and Money

Board-foot quantities are decimal values carried to exactly 2 decimal places, rounded half-up; this rounding applies per computed line value before any summation, as detailed in §3.4. All monetary amounts are integer cents — freight, storage fees, claim amounts, credit limits, and unit costs are whole cents, and any intermediate monetary computation that produces a fractional cent is rounded half-up to a whole cent. Storage-day arithmetic uses whole calendar days only, with no partial days (§3.7). Crane-slot boundaries carry minute precision. Enum and status fields are exact uppercase strings as enumerated in §3; timestamps are ISO 8601 UTC.

### 2.10. Compound Job Posture

Every job exposes a derived `posture` field — one of `GREEN`, `AT_RISK`, or `BLOCKED`, defaulting to `GREEN` at creation — that aggregates the health of everything beneath it. The derivation is recomputed on every mutation of the job's children (designs, cut lists, batches, loads, claims, change orders), on any change to the owning customer's `credit_hold`, and on every read of the job.

The tiers are evaluated in strict priority, and the first matching tier wins. A job is `BLOCKED` if any of the following holds: its customer's `credit_hold` is true; any of its change orders is in `APPROVED`; any of its cut lists is in `RECONCILING`; or any damage claim on any of its loads is in `APPROVED_REBUILD` or `REBUILD_IN_PROGRESS`. Otherwise the job is `AT_RISK` if any of the following holds: any of its production batches is in `QC_FAILED` or `REWORK`; any of its delivery loads is in `RETURNED`; or any of its component designs is in `SEAL_REQUESTED`. Otherwise the job is `GREEN`.

## 3. Business Logic & Workflows

### 3.1. Plant Master Data: Customer Accounts, Engineers, Jig Setups, and Cranes

Before any job can flow through the plant, four kinds of master data must exist. A `PlantManager` registers each builder as a customer account with a `company_name`, a `credit_limit_cents` ceiling on outstanding freight expressed in integer cents, and `delivery_terms` of either `FOB_PLANT` or `DELIVERED`. Optional account terms include `credit_hold` (default false), `storage_free_days` (default 2 whole days), `storage_daily_fee_cents` (default 15000), `storage_fee_cap_cents` (default 300000), and `max_drops_per_day` (default 2) — the aggregate jobsite capacity that bounds how many of one job's loads may share a single scheduled date. Each account tracks a computed `credit_used_cents`, initially 0, which aggregates the customer's freight exposure: the sum of `provisional_freight_cents` over the customer's loads in `PLANNED`, `STAGED`, or `LOADING`, plus the sum of `final_freight_cents` over loads in `DISPATCHED`, `DELIVERED`, `RETURNED`, `RESCHEDULED`, `CLAIM_HOLD`, or `CLOSED`; a load in `CANCELLED` contributes nothing. A `PlantManager` may update the credit and storage terms on an existing account; setting `credit_hold` to true immediately recomputes the posture of every job belonging to that customer, flipping each to `BLOCKED` per §2.10. The customer list supports filtering by `credit_hold`.

Engineers of record are registered by a `PlantManager` with a `full_name`, a PE `license_number`, a two-letter `license_state`, a `license_expiry` instant, and a `seal_authority` of `TRUSS_ONLY` or `TRUSS_AND_PANEL`. An engineer may seal a design only while the logical clock is on or before their `license_expiry`, only when their `license_state` equals the job's `jobsite_state`, and — for wall-panel work — only with the `TRUSS_AND_PANEL` authority; the seal workflow in §3.3 enforces each of these gates. The engineer list supports filtering by `license_state`.

Jig setups describe the plant's assembly jigs. A `PlantManager` creates each jig with a unique, immutable `setup_code` (for example, JIG-ROOF-A), a `component_type_supported` of `FLOOR_TRUSS`, `ROOF_TRUSS`, or `WALL_PANEL`, a `plate_class` of `P20`, `P18`, or `P16`, and a `changeover_minutes_from` map. That map records, for each source `setup_code`, the integer minutes needed to change over to this jig from that source; a source with no entry means a default of 60 minutes, and an entry whose source equals the target's own code means 0 minutes. The build-sequencing rule in §3.6 consumes this matrix. The jig list supports filtering by `component_type_supported`.

Plant cranes are registered by a `PlantManager` with a unique `crane_code`, a `capacity_lbs` maximum single-pick weight, a `crane_class` of `LIGHT`, `STANDARD`, or `HEAVY`, and an `hourly_rate_cents` used later in final freight. A crane's `status` is `ACTIVE` or `OUT_OF_SERVICE`; a `PlantManager` flips it between the two, and each flip increments the crane's `version`. The crane list supports filtering by `status` and `crane_class`.

### 3.2. Job Intake, Confirmation, and Cancellation

A job represents one builder's order of manufactured components for one jobsite. Creation is open to a `PlantManager`, or to a `CustomerContact` whose `X-User-ID` must equal the body's `customer_id`. The intake payload carries `job_name`, `jobsite_address`, the two-letter `jobsite_state` that will constrain which engineers may seal its designs, the closed delivery window from `delivery_window_start` through `delivery_window_end` (an inclusive interval at UTC date granularity; the end must be on or after the start), the `contracted_value_cents` of the manufactured components, and an optional `crane_required_at_jobsite` flag (default false) that adds a flat 25000 cents to provisional freight per §3.7.

A job is born `QUOTED`. A `PlantManager` confirms it — `QUOTED` to `CONFIRMED` — which increments the job's `version`; attempting confirmation from any other status is rejected with `ERR_INVALID_STATE`. From there the job advances on its own: the moment the job's first cut list reaches `RELEASED`, the job moves `CONFIRMED` to `IN_PRODUCTION`, and the moment its first delivery load reaches `DISPATCHED`, it moves `IN_PRODUCTION` to `SHIPPING`, each step incrementing `version`. The job reaches `COMPLETED` automatically once every delivery load of the job is `CLOSED` or `CANCELLED`, every production batch is `LOADED` or `CANCELLED`, no damage claim on any of the job's loads remains open in `FILED`, `TRIAGED`, `APPROVED_REBUILD`, `APPROVED_CREDIT`, or `REBUILD_IN_PROGRESS`, and at least one delivery load exists; completion recomputes the job's `invoiced_cents`.

Two computed money fields follow the job through its life. `invoiced_cents`, initially 0, is the `contracted_value_cents` plus the sum of `final_freight_cents` over the job's `CLOSED` loads. `credit_issued_cents`, initially 0, is the sum of `residual_credit_cents` over the job's damage claims currently in `SETTLED`; §3.8 describes how settlement adds to it and how a post-settlement reversal subtracts exactly the same amount back out.

Cancellation is a `PlantManager` action available from `QUOTED`, `CONFIRMED`, or `IN_PRODUCTION`, and it is refused with `ERR_INVALID_STATE` while any of the job's loads is in `DISPATCHED`, `DELIVERED`, `RETURNED`, `RESCHEDULED`, or `CLAIM_HOLD` — freight already on the road must be settled, not cancelled. Cancelling a job fires a full down-cascade in one operation: every load in `PLANNED`, `STAGED`, or `LOADING` moves to `CANCELLED`, and each cancelled load's bundles in `PACKED` (for a load in `LOADING`, also bundles in `LOADED`) move to `SUPERSEDED`; every production batch not already `LOADED` or `CANCELLED` moves to `CANCELLED`, with the surviving batches' build sequence renumbered per §3.6; every cut list in `EXPLODED`, `RELEASED`, or `RECONCILING` moves to `SUPERSEDED`; and every reservation still `RESERVED` on lines or lists of the job moves to `RELEASED`, restoring each touched lot's availability and incrementing each lot's `version`. The job's own `version` increments by 1. Reading a job recomputes its `posture` per §2.10, and the job list supports filtering by `customer_id`, `status`, and `posture`.

### 3.3. Engineering: Component Designs, Revision Chains, and Seal Governance

Within a job, a `DesignEngineer` authors component designs. The create payload carries `component_ref` (the customer-facing label, such as TR-01), `component_type` (`FLOOR_TRUSS`, `ROOF_TRUSS`, or `WALL_PANEL`), `span_ft`, `pitch_degrees` (0 for floor trusses and wall panels), `design_load_psf`, `lumber_grade` (`SPF_NO2`, `SPF_MSR2400`, or `SYP_NO1`, which drives the waste base rate in §3.4), `plating` (`P20`, `P18`, or `P16`, which plate lots must match), `quantity_required` (the number of identical components the job needs, which drives the plate requirement), the OCC field `expected_job_version` per §2.6, and optionally `supersedes_design_id` when the new design revises a sealed one. Each create increments the job's `version` and recomputes its posture.

Discipline around `component_ref` keeps the revision chain unambiguous. At most one design per (job, `component_ref`) pair may sit in `DRAFT` or `SEAL_REQUESTED` at a time, and creating a revision while a `SEALED` design exists for the same pair requires `supersedes_design_id` naming that current sealed revision. Violating either rule is rejected with `ERR_DUPLICATE_COMPONENT_REF` (HTTP 409); supplying a `supersedes_design_id` when no `SEALED` revision exists for that `component_ref` is instead rejected with `ERR_REVISION_CHAIN_BROKEN` (HTTP 422). These two checks run after the stale-version check of §2.6. The server assigns each new design a `revision_no` equal to 1 plus the maximum `revision_no` among designs of the same (job, `component_ref`) — the first design for a pair is revision 1, its successor 2, and so on. A design is considered current when it is the `SEALED` revision with the highest `revision_no` for its pair and has not been `SUPERSEDED`. For reference, each design also carries `est_board_feet_per_unit`, an informational estimate equal to `span_ft` multiplied by a fixed unit board-feet-per-span factor keyed on `component_type`, rounded half-up to 2 decimal places.

The seal lifecycle enforces professional-engineer governance. A design starts in `DRAFT`; its author moves it `DRAFT` to `SEAL_REQUESTED`, which records `submitted_by_engineer_id` from `X-User-ID`. A second engineer then seals it — `SEAL_REQUESTED` to `SEALED` — passing four safety gates evaluated in this order: first, the sealing engineer's `license_expiry` must be on or after the current logical clock, else `ERR_ENGINEER_LICENSE_EXPIRED`; second, the sealing engineer's `license_state` must equal the job's `jobsite_state`, else `ERR_ENGINEER_LICENSE_STATE_MISMATCH`; third, a `WALL_PANEL` design requires the sealer's `seal_authority` to be `TRUSS_AND_PANEL`, else `ERR_SEAL_AUTHORITY_INSUFFICIENT`; fourth, segregation of duties requires the sealing engineer's id to differ from `submitted_by_engineer_id`, else `ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER`. Requesting a seal on a design that is not in `SEAL_REQUESTED` is rejected with `ERR_DESIGN_NOT_AWAITING_SEAL`. A successful seal sets `sealed_by_engineer_id` from `X-User-ID` and `sealed_at` to the current logical clock — both are null until then — and recomputes the job's posture, since the design no longer counts as an outstanding `SEAL_REQUESTED`. Reviewers may instead reject the design back to `DRAFT`, which clears `submitted_by_engineer_id` to null so a fresh submission records a fresh submitter, and a `DRAFT` design may be abandoned to `VOID`. Once `SEALED`, a design leaves that state only when a change order is applied against it (§3.9), moving it to `SUPERSEDED`; any other transition request on a design is rejected with `ERR_INVALID_STATE`. The design list supports filtering by `job_id`, `supersedes_design_id`, `submitted_by_engineer_id`, `sealed_by_engineer_id`, `status`, and `component_ref`.

### 3.4. Cut-List Explosion and Material Requirement Math

Once a design is sealed and current, a `ProductionPlanner` explodes it into a cut list — the bill of materials the shop will cut. Explosion requires the design to be `SEALED` and current per §3.3; exploding a superseded or out-of-date revision is rejected with `ERR_DESIGN_NOT_CURRENT`. The payload names a `jig_setup_id` whose `component_type_supported` must equal the design's `component_type`, else `ERR_JIG_COMPONENT_MISMATCH`, and a `lines` array of member specifications, each with a `member_label` (such as TC-1), a nominal `dimension` of `L2X4`, `L2X6`, or `L2X8`, a `length_ft` cut length, and a `qty` piece count. The created cut list is born `EXPLODED`, carries a denormalized `job_id` taken from its design, and spawns one cut-list line child per entry of `lines`, each born `PENDING`. A cut list created by the claim-rebuild cascade instead carries a `rebuild_for_claim_id` naming its originating damage claim (§3.8).

Explosion computes the material math that drives everything downstream. For each line, `line_board_feet` is `qty` multiplied by `length_ft` multiplied by the per-foot board-foot factor of its `dimension` — 0.6667 for `L2X4`, 1.0 for `L2X6`, and 1.3333 for `L2X8` — rounded half-up to 2 decimal places. The line's `waste_pct` starts from a base rate keyed on the design's `lumber_grade`: 0.08 for `SPF_NO2`, 0.05 for `SPF_MSR2400`, and 0.06 for `SYP_NO1`. To that base, a length surcharge is added: 0.04 when `length_ft` is at least 20 feet, else 0.02 when it is at least 16 feet but under 20, else 0. The sum is then capped at 0.11 — the smaller of the summed rate and the cap applies. Because the cap clamps the sum, grade and length interact non-linearly: an `SPF_NO2` line at 20 feet or more lands exactly on the cap, while an `SPF_MSR2400` line of the same length does not. The line's `required_board_feet` — its reservation coverage requirement — is `line_board_feet` multiplied by one plus `waste_pct`, rounded half-up to 2 decimal places.

Header totals follow a pinned rounding order. `total_board_feet` is the sum of the lines' `required_board_feet` values, each already rounded to 2 decimals — the system rounds per line first, then sums the rounded values. Summing raw values and rounding once at the end is forbidden and produces different totals: two `L2X4` lines of 8.0 feet at quantity 1 in `SPF_NO2` yield 5.76 plus 5.76, totalling 11.52 under the pinned order, versus 11.51 if the raw sum were rounded once. `total_pieces` is the integer sum of `qty` over all lines. `total_plates` is the design's `quantity_required` multiplied by a per-unit plate count keyed on `component_type`: 24 for `FLOOR_TRUSS`, 28 for `ROOF_TRUSS`, and 12 for `WALL_PANEL`. Totals are computed over all lines regardless of later status changes — line statuses evolve, but the header totals do not.

Release moves a cut list `EXPLODED` to `RELEASED`; attempting it from any other status is rejected with `ERR_CUT_LIST_NOT_RELEASED`. The release re-verifies that the design is `SEALED` and current (else `ERR_DESIGN_NOT_CURRENT`) and that the jig's `component_type_supported` matches the design's `component_type` (else `ERR_JIG_COMPONENT_MISMATCH`) — in that order, the status guard before the currency and jig checks. When this is the job's first cut list to reach `RELEASED`, the job itself advances `CONFIRMED` to `IN_PRODUCTION` per §3.2, and the job's posture is recomputed. A `ProductionPlanner` also reconciles a list in `RECONCILING` (a state entered only through the change-order cascade of §3.9): reconciliation to `CLOSED` — rejected with `ERR_CUT_LIST_NOT_RECONCILING` from any other status — scraps every remaining `PENDING` line with no lot impact (their reservations were already released by the cascade), and scraps every `CUT` line with waste accrual: for each such line, walking its `CONSUMED` reservations in reservation `created_at` ascending order, each touched lot's `scrapped_bf` increases by the covered amount and its `consumed_bf` decreases by the same amount, until the line's full `required_board_feet` has been accounted — the conservation invariant of §2.8 holds throughout. The job's posture is then recomputed. The cut-list list supports filtering by `design_id`, `job_id`, `jig_setup_id`, `rebuild_for_claim_id`, and `status`; the line list by `cut_list_id`, `status`, and `dimension`.

### 3.5. Yard Inventory: Lot Receipt, Reservations, and Consumption

An `InventoryManager` receives material into lots. Each lot declares a `lot_kind` of `LUMBER` or `PLATE`, and the schema rules of §2.7 apply: a lumber lot requires `lumber_dimension` (`L2X4`, `L2X6`, or `L2X8`) and `lumber_grade` (`SPF_NO2`, `SPF_MSR2400`, or `SYP_NO1`) and must report `received_plates` of 0; a plate lot requires a `plate_class` of `P20`, `P18`, or `P16` and must report `received_board_feet` of 0. Received volumes land in `received_board_feet` and `received_plates` (each defaulting to 0), and unit costs `unit_cost_cents_per_bf` and `unit_cost_cents_per_plate` (each defaulting to 0) are informational, used for rebuild costing context. At receipt, `available_bf` initializes to `received_board_feet` and `available_plates` to `received_plates`, with `reserved_bf`, `consumed_bf`, `scrapped_bf`, `reserved_plates`, `consumed_plates`, and `scrapped_plates` all starting at 0; the lot is born `ACTIVE`.

Lots may be quarantined and restored — `ACTIVE` to `QUARANTINED` and back — by an `InventoryManager`, each flip incrementing the lot's `version`. A quarantined lot rejects reservation consumption with `ERR_INVALID_STATE`, and the reservation rules below require an `ACTIVE` lot as well. Physical-count corrections post through the adjustment capability with a mandatory `reason` plus any of `adjust_available_bf`, `adjust_scrapped_bf`, `adjust_available_plates`, and `adjust_scrapped_plates`; each adjustment increments the lot's `version` and re-runs the `DEPLETED` check of §2.8. The lot list supports filtering by `lot_kind`, `status`, `lumber_dimension`, and `lumber_grade`.

Reservations are the plant's mechanism for earmarking finite material against cut lists, created by a `ProductionPlanner` with the OCC field `expected_lot_version` per §2.6. Kind discipline is checked first, before availability: a reservation against a lumber lot must carry `cut_list_line_id` naming the line it feeds, a `reserved_bf` greater than 0, and `reserved_plates` of exactly 0, and the lot's `lumber_dimension` and `lumber_grade` must equal the line's cut list's design values; a reservation against a plate lot must instead carry `cut_list_id`, a `reserved_plates` greater than 0, and `reserved_bf` of exactly 0, and the lot's `plate_class` must equal the design's `plating`. Any violation is rejected with `ERR_RESERVATION_KIND_MISMATCH` (HTTP 422). Only then is availability checked: `reserved_bf` must not exceed the lot's `available_bf` (lumber) or `reserved_plates` its `available_plates` (plate), and the lot must be `ACTIVE`, else `ERR_INSUFFICIENT_INVENTORY` (HTTP 422). A successful create decrements the lot's available quantity, increments its reserved quantity, and increments the lot's `version`; the reservation is born `RESERVED`.

From `RESERVED`, a reservation ends in one of two compensating directions. Consumption by an `InventoryManager` — allowed only while the lot is `ACTIVE`, else `ERR_INVALID_STATE` — moves the reservation to `CONSUMED` and shifts the lot's reserved quantity into consumed (`reserved_bf` into `consumed_bf`, or the plate mirror), incrementing the lot's `version`. Release moves it to `RELEASED` and restores availability exactly: the lot's reserved quantity decreases by the reservation's amount and its available quantity increases by the same amount — the exact compensating action of the original reserve — again incrementing the lot's `version` and re-running the `DEPLETED` check. Releases also fire automatically from the scrap, change-order, and job-cancel cascades described in §3.4, §3.6, §3.9, and §3.2. The reservation list supports filtering by `lot_id`, `cut_list_line_id`, `cut_list_id`, and `status`.

### 3.6. Production: Batches, Build Sequencing, Crane Picks, and Quality Control

A `ProductionPlanner` schedules production batches against a job, naming a `cut_list_id` that must be `RELEASED` (else `ERR_CUT_LIST_NOT_RELEASED`), a `jig_setup_id` whose `component_type_supported` must equal the cut list's design `component_type` (else `ERR_JIG_COMPONENT_MISMATCH`; the status guard fires before the jig check), and a `requested_completion_at` instant that is the primary build-sequence sort key. Each batch carries a computed `build_sequence_no` and is born `SCHEDULED`. Batches created by the claim-rebuild cascade of §3.8 instead carry `is_rebuild` set to true and a `source_claim_id` naming their claim. The batch list supports filtering by `job_id`, `cut_list_id`, `jig_setup_id`, `source_claim_id`, and `status`.

Build sequencing is deterministic across the job. The candidate set is every batch of the job not in `CANCELLED` or `LOADED`. Batches sort first by `requested_completion_at`, earliest first. Within a group of exactly equal `requested_completion_at` values, the order is chosen greedily by changeover minimization: starting from the group anchor — the batch with the earliest `created_at`, which has no predecessor — the system repeatedly picks the remaining batch whose jig minimizes the changeover from the previously placed batch's jig, where the changeover is the target jig's `changeover_minutes_from` entry keyed on the previous jig's `setup_code`, defaulting to 60 minutes when that entry is missing and counting 0 when the two codes are identical. Remaining ties break by `created_at`, earliest first. The ordered candidates are then numbered 1 through N into `build_sequence_no`. The sequence is recomputed on every batch create and on any batch of the job reaching `CANCELLED`, so later inserts shift their successors and departed batches leave the candidate set to be renumbered.

Crane time is booked in buffered intervals. A `ProductionPlanner` books a crane slot with `crane_id`, a `purpose` of `BUILD_PICK` (a batch staging pick, which requires `production_batch_id`) or `LOAD_PICK` (a truck loading pick, which requires `delivery_load_id`), the half-open interval from `start_at` to `end_at`, and the OCC field `expected_crane_version` per §2.6. Three checks follow in a fixed order after the version check: the buffered overlap rule, the crane's service state, and the slot's position in time. Under the overlap rule, slots occupy half-open intervals — the start inclusive, the end exclusive — with a mandatory 30-minute buffer on the same crane: a new slot is rejected with `ERR_CRANE_SLOT_OVERLAP` (HTTP 409) unless, for every existing slot on that crane in `BOOKED` or `COMPLETED`, the new slot's `start_at` is at or after the existing slot's `end_at` plus 30 minutes, or the new slot's `end_at` is at or before the existing slot's `start_at` minus 30 minutes. Exactly 30 minutes of gap is acceptable — a slot starting precisely 30 minutes after another ends is accepted, while 29 minutes is rejected — and `CANCELLED` slots occupy nothing. The crane itself must be `ACTIVE`, else `ERR_INVALID_STATE`, and the slot's `start_at` must be on or after the current logical clock, else `ERR_SLOT_IN_PAST`. A successful booking increments the crane's `version`. Slots are born `BOOKED` and are moved to `COMPLETED` or `CANCELLED` by a `ProductionPlanner`; cancelling frees the interval, and later overlap checks ignore it. The slot list supports filtering by `crane_id`, `production_batch_id`, `delivery_load_id`, and `status`.

The batch build lifecycle belongs to the `ShopFloorLead`. Entering `CUTTING` from `SCHEDULED` is the heaviest gate in the plant and its checks run in a fixed order: the transition itself must be declared from the batch's current status (else `ERR_INVALID_STATE` or, for batch-specific violations, `ERR_BATCH_INVALID_TRANSITION`); the cut list must be `RELEASED`, else `ERR_CUT_LIST_NOT_RELEASED`; the cut list's design must be `SEALED` and current, else `ERR_DESIGN_NOT_CURRENT`; the job must be `IN_PRODUCTION`; and coverage must be complete — every line of the cut list still in `PENDING` must have its `RESERVED` lumber reservations summing to at least the line's `required_board_feet`, and the cut list's `RESERVED` plate reservations must sum to at least the list's `total_plates` — else `ERR_RESERVATION_COVERAGE_SHORT` (HTTP 422). Entering `CUTTING` consumes the coverage: every `RESERVED` lumber reservation on the cut list's lines and every `RESERVED` plate reservation on the list move to `CONSUMED`, shifting each lot's reserved quantity into consumed and incrementing each lot's `version`. Marking work complete then happens line by line: a `ShopFloorLead` marks a `PENDING` line as `CUT`, which requires some batch referencing the line's cut list to be in `CUTTING`, else the request is rejected with `ERR_INVALID_STATE`.

From `CUTTING` the batch moves to `ASSEMBLY` only when every line of its cut list is in `CUT` or `SCRAPPED`, then to `BUILT`, and from `BUILT` either to `QC_PASSED` or to `QC_FAILED` — a failure recomputes the job's posture to `AT_RISK` per §2.10. A failed batch enters `REWORK` and returns to `QC_PASSED` from there, recomputing posture again. A `QC_PASSED` batch reaches `STAGED` only once at least one crane slot referencing it via `production_batch_id`, with `purpose` `BUILD_PICK` and status `COMPLETED`, exists. The remaining transitions are system-only: a `STAGED` batch moves to `LOADED` when a load it is bundled into enters `LOADING`, and a `LOADED` batch returns to `STAGED` when its truck comes back (§3.7); any batch not yet `LOADED` or `CANCELLED` moves to `CANCELLED` only through the change-order or job-cancel cascades. Requesting `STAGED` to `LOADED` or any direct cancellation is rejected with `ERR_BATCH_INVALID_TRANSITION` (HTTP 409).

Lines may also be scrapped directly by a `ShopFloorLead`. Scrapping a `PENDING` line releases every `RESERVED` reservation on it — each lot's `available_bf` is restored by the reservation's `reserved_bf`, the lot's `reserved_bf` decreases by the same amount, and each lot's `version` increments. Scrapping a `CUT` line walks its `CONSUMED` reservations in `created_at` ascending order, moving material from consumed to scrapped on each lot — `consumed_bf` decreases by the covered amount, `scrapped_bf` increases by the same amount, and the lot's `version` increments — until the line's `required_board_feet` is fully covered, preserving the conservation invariant of §2.8.

### 3.7. Shipping and Freight: Loads, Bundle Maps, Dispatch Gates, Storage, and Settlement

A `ShippingCoordinator` plans delivery loads against a job, supplying a `scheduled_date` and a `planned_weight_est_lbs` estimate. Three gates guard load creation, evaluated in this order after the universal checks of §2.7: the `scheduled_date` must fall inside the job's closed delivery window — on or after `delivery_window_start` and on or before `delivery_window_end` — else `ERR_OUTSIDE_DELIVERY_WINDOW` (HTTP 422); the aggregate drops-per-day capacity must admit one more load, meaning the count of the job's loads sharing that `scheduled_date` with any status other than `CANCELLED` must be strictly less than the customer's `max_drops_per_day` before this load is added, else `ERR_DROPS_PER_DAY_EXCEEDED` (HTTP 422); and the customer's `credit_used_cents` plus this load's provisional freight must not exceed `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

Provisional freight is quoted at planning time from the estimate alone — measured bundle weights play no part. `provisional_freight_cents` is a flat base of 50000 cents, plus the `planned_weight_est_lbs` multiplied by 12 cents per pound rounded half-up to whole cents, plus a flat 25000 cents when the job's `crane_required_at_jobsite` is true. The new provisional immediately counts toward the customer's `credit_used_cents` per §3.1. A load is born `PLANNED`; the load list supports filtering by `job_id`, `status`, and `scheduled_date`.

The bundle map assembles the load. Adding a bundle requires `production_batch_id`, `stack_position`, `weight_lbs`, and optionally `split_from_bundle_id` marking the bundle as split off from another bundle of the same load. The load must be in `PLANNED`, `STAGED`, or `LOADING`; the referenced batch must be `STAGED` and belong to the same job as the load; and at least one `LOAD_PICK` slot in `BOOKED` or `COMPLETED` must exist for the load, since it anchors the weight check — a violation of any of these three referential conditions is rejected with `ERR_BUNDLE_JOB_MISMATCH` (HTTP 422). Two constraint checks precede that referential check, in this order: `weight_lbs` must not exceed the `capacity_lbs` of the crane on the load's earliest-start `BOOKED` or `COMPLETED` `LOAD_PICK` slot — equality is permitted, strictly greater is rejected with `ERR_BUNDLE_OVERWEIGHT` (HTTP 422) — and `stack_position`, the load-order position where 1 is the floor, must be unique among the load's non-`SUPERSEDED` bundles, else `ERR_STACK_POSITION_CONFLICT` (HTTP 409). Each accepted bundle is born `PACKED`, and the load's `actual_total_weight_lbs` is recomputed. The bundle list supports filtering by `delivery_load_id`, `production_batch_id`, `split_from_bundle_id`, and `status`.

The load lifecycle runs `PLANNED` to `STAGED` to `LOADING` to `DISPATCHED` to `DELIVERED` to `CLOSED`, with a return loop and a claim hold along the way; any undeclared transition or failed state guard is rejected with `ERR_LOAD_INVALID_TRANSITION` (HTTP 409). Staging requires at least one bundle of the load in `PACKED` and stamps `staged_at` with the current logical clock — the storage anchor, null until this transition. Loading requires at least one `COMPLETED` crane slot referencing the load via `delivery_load_id` with `purpose` `LOAD_PICK`, and every non-`SUPERSEDED` bundle of the load in `PACKED`; entering `LOADING` moves all those bundles to `LOADED` and moves every referenced batch currently `STAGED` to `LOADED`, leaving already-`LOADED` batches untouched.

Dispatch is guarded temporally first, then fiscally. The `scheduled_date` must lie inside the job's closed delivery window and the current logical clock must be on or before `delivery_window_end`, else `ERR_OUTSIDE_DELIVERY_WINDOW`; the customer's `credit_hold` must be false, else `ERR_CREDIT_HOLD` (HTTP 402) — a check deliberately performed after the temporal gates; and `credit_used_cents` plus this load's `provisional_freight_cents` must not exceed `credit_limit_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`. Dispatch stamps `last_dispatched_at` — null until the first dispatch — with the current logical clock, and if this is the job's first `DISPATCHED` load the job advances `IN_PRODUCTION` to `SHIPPING`; the job's posture is recomputed. Delivery moves every `LOADED` bundle to `DELIVERED`. A return — `DISPATCHED` to `RETURNED` — moves every `LOADED` bundle to `RETURNED`, returns every referenced `LOADED` batch to `STAGED`, and recomputes the job's posture to `AT_RISK`.

A returned load is rescheduled by moving `RETURNED` to `RESCHEDULED` with a `rescheduled_date` in the request (required exactly for this target state per §2.7): the new date must lie inside the closed delivery window, else `ERR_OUTSIDE_DELIVERY_WINDOW`, and the drops-per-day capacity on the new date must admit the load, else `ERR_DROPS_PER_DAY_EXCEEDED`; the load's `scheduled_date` is updated and posture recomputed. Re-dispatch from `RESCHEDULED` re-runs the same temporal and fiscal guards as a first dispatch, stamps `last_dispatched_at` anew — extending the storage window, since it always reflects the latest dispatch — moves bundles in `RETURNED` back to `LOADED`, and moves referenced batches currently `STAGED` back to `LOADED`.

Closing a load — from `DELIVERED`, or from `CLAIM_HOLD` once no claim of the load remains open in `FILED`, `TRIAGED`, `APPROVED_REBUILD`, `APPROVED_CREDIT`, or `REBUILD_IN_PROGRESS` — requires `crane_hours_actual` in the request (null until this point) and settles the freight. Final freight is computed in a pinned evaluation order, each step feeding the next. First, `actual_total_weight_lbs` is the sum of `weight_lbs` over the load's bundles in `PACKED`, `LOADED`, `DELIVERED`, `RETURNED`, or `DAMAGED` — `SUPERSEDED` bundles are excluded, so a change-order apply between staging and close changes this base. Second, the crane is the one on the load's earliest-`start_at` `BOOKED` or `COMPLETED` `LOAD_PICK` slot, ties broken by slot `created_at` ascending, and `crane_hours_actual` multiplied by that crane's `hourly_rate_cents`, rounded half-up to whole cents, gives the crane cost. Third, the overweight surcharge applies only to the excess above 20000 pounds: the amount by which `actual_total_weight_lbs` strictly exceeds 20000, multiplied by 18 cents per pound — a load at exactly 20000 pounds pays nothing. Fourth, the storage fee accrues per the rule below. Fifth, `final_freight_cents` is the 50000-cent base, plus `actual_total_weight_lbs` multiplied by 12 cents per pound rounded half-up, plus the surcharge, plus the crane cost, plus the storage fee — all integer cents. Because the surcharge tier keys on the post-supersede measured weight from step one, an implementation keyed on `planned_weight_est_lbs` or on a staging-time snapshot reaches a different tier decision. Closing switches this load's contribution to `credit_used_cents` from provisional to final, recomputes the job's `invoiced_cents`, and runs the job-completion check of §3.2.

Storage accrues between staging and the last dispatch. The days stored are the whole calendar days between the UTC date part of `staged_at` and the UTC date part of `last_dispatched_at`. Billable days are the days stored minus the customer's `storage_free_days`, floored at zero — a load stored exactly `storage_free_days` days bills nothing, and one day beyond bills exactly one daily fee. `storage_fee_cents`, null until close, is then the billable days multiplied by the customer's `storage_daily_fee_cents`, capped at the customer's `storage_fee_cap_cents` — the smaller of the two applies. A `RETURNED` then `RESCHEDULED` then re-`DISPATCHED` loop extends the days stored, because `last_dispatched_at` always holds the latest dispatch instant. Both `final_freight_cents` and `storage_fee_cents` remain null until the load closes.

### 3.8. Field Damage Claims: Triage, Decision, Rebuild, and the Settlement Waterfall

When a delivery arrives damaged, short, or defective, the builder's `CustomerContact` files a damage claim against a bundle of the load, supplying `bundle_id`, a `claim_type` of `FIELD_DAMAGE`, `MATERIAL_DEFECT`, or `SHORT_SHIPMENT`, a free-text `description`, and the `claimed_amount_cents`. The bundle must belong to that load, else `ERR_CLAIM_BUNDLE_NOT_IN_LOAD` (HTTP 422), and the filer's `X-User-ID` must equal the customer owning the load's job, else `ERR_FORBIDDEN_OWNERSHIP`; the server records it as `filed_by_customer_id`. Filing against a load in `DELIVERED` moves the load to `CLAIM_HOLD`. The claim is born `FILED`; the claim list supports filtering by `delivery_load_id`, `bundle_id`, `filed_by_customer_id`, and `status`.

A `ClaimsAdjuster` triages the claim — `FILED` to `TRIAGED` — recording `triaged_by` from `X-User-ID`; `triaged_by` is null until triage, and `decided_by` is null until a decision. Decision then requires a different adjuster: segregation of duties forbids the decider from equalling `triaged_by`, enforced with `ERR_CLAIM_DECIDER_MUST_DIFFER` (HTTP 422) after the action guard itself (an action attempted from the wrong claim status is rejected with `ERR_CLAIM_INVALID_TRANSITION`, HTTP 409). The `decision` payload is one of `APPROVE_REBUILD`, `APPROVE_CREDIT`, or `DENY`. For either approval path, `damage_pct` — the adjuster-assessed damaged fraction, strictly greater than 0 and at most 1 — must be provided, and `approved_cap_cents` is computed: the component value is the damaged bundle's batch's cut list's `total_board_feet` multiplied by 850 cents per board foot, rounded half-up to whole cents, and the cap is the smaller of `claimed_amount_cents` and `damage_pct` multiplied by that component value, rounded half-up to whole cents. The same formula applies to every `claim_type`. A successful decision records `decided_by` from `X-User-ID`; `approved_cap_cents`, like `damage_pct`, stays null until the claim is decided.

The two approval paths diverge sharply. `APPROVE_REBUILD` — moving the claim to `APPROVED_REBUILD` — marks the damaged bundle `DELIVERED` to `DAMAGED` and fires the rebuild cascade: the system clones the damaged bundle's batch's cut list into a new cut list in `EXPLODED` with fresh `PENDING` lines of identical specifications, stamped with `rebuild_for_claim_id` naming the claim, with the line math of §3.4 recomputed for the clone; it then creates a rebuild production batch in `SCHEDULED` with `is_rebuild` true, `source_claim_id` naming the claim, the same jig, and a `requested_completion_at` of the current logical clock plus 7 days; and it recomputes the job's build sequence. The claim then continues immediately to `REBUILD_IN_PROGRESS`, and the job's posture reads `BLOCKED` per §2.10 for as long as the claim remains unsettled. `APPROVE_CREDIT` is the lighter path: the cap is computed identically, but the bundle stays `DELIVERED` and nothing is rebuilt. A `DENY` decision computes no cap, and if no other claim on the load remains open, the load is released from `CLAIM_HOLD` back to `DELIVERED`.

Settlement converts the cap into money. From `APPROVED_CREDIT`, or from `REBUILD_IN_PROGRESS` once the rebuild batch identified by `source_claim_id` has reached `STAGED` or `LOADED`, a `ClaimsAdjuster` settles with three actual cost amounts: `rebuild_material_cents`, `rebuild_labor_cents`, and `redelivery_cents`. The approved cap distributes across them as a waterfall in that fixed order: the material bucket receives the smaller of the actual material amount and the cap remaining; the labor bucket then receives the smaller of the actual labor amount and what remains; the redelivery bucket likewise; and whatever remains afterward is `residual_credit_cents`, issued back to the customer as credit. All four settlement numbers — `rebuild_material_cents`, `rebuild_labor_cents`, `redelivery_cents`, and `residual_credit_cents` — are null until the claim settles. Conservation is exact in integer cents — the three buckets plus the residual always sum precisely to `approved_cap_cents`. Settlement adds `residual_credit_cents` to the job's `credit_issued_cents`, recomputes posture, and releases the load `CLAIM_HOLD` to `DELIVERED` when no other claim on it remains open.

Voiding unwinds a claim. A claim in `FILED` or `TRIAGED` may be voided outright, releasing the load to `DELIVERED` if no other claim remains open. A claim already `SETTLED` may also be voided as a post-settlement reversal: the job's `credit_issued_cents` decreases by exactly the claim's `residual_credit_cents` — the compensating pair leaves the customer's issued credit unchanged — and posture is recomputed. All claim actions respect the status guards: triage only from `FILED`, decide only from `TRIAGED`, settle only from `APPROVED_CREDIT` or `REBUILD_IN_PROGRESS`, and void only from `FILED`, `TRIAGED`, or `SETTLED`; anything else is `ERR_CLAIM_INVALID_TRANSITION`.

### 3.9. Design Change Orders After Cut

A design change after material has been cut is the most destructive operation in the plant, and it is gated accordingly. A change order is requested by the owning `CustomerContact` or by a `ProductionPlanner`, naming `supersedes_design_id` — the current `SEALED` design being changed — a free-text `reason`, the OCC field `expected_job_version` per §2.6, and optionally `new_design_id`. The server records `requested_by` from `X-User-ID`, and each create increments the job's `version`. The order is born `REQUESTED`; the change-order list supports filtering by `job_id`, `supersedes_design_id`, `new_design_id`, and `status`.

Assessment by a `ProductionPlanner` moves the order `REQUESTED` to `IMPACT_ASSESSED` and quantifies the blast radius: `impact_lines_scrapped` counts the lines in `CUT` status across all cut lists of the superseded design at that moment, and `impact_open_reservations` counts the reservations still `RESERVED` on lines or lists of that design — both null until assessed. The assessment may also supply `new_design_id` if it was not set at create; when supplied, the candidate must belong to the same job, carry the same `component_ref` as the superseded design, and have its own `supersedes_design_id` equal to this order's `supersedes_design_id`, else `ERR_REVISION_CHAIN_BROKEN` (HTTP 422).

Approval by a `PlantManager` — `IMPACT_ASSESSED` to `APPROVED` — demands a chain-valid successor: `new_design_id` must be set, the new design must be `SEALED`, its `revision_no` must be strictly greater than the superseded design's, and its `supersedes_design_id` must equal the order's `supersedes_design_id`, with chain violations rejected as `ERR_REVISION_CHAIN_BROKEN`. Approval immediately recomputes the job's posture to `BLOCKED`, where it stays until the order is applied. A `PlantManager` may instead reject the order from `REQUESTED` or `IMPACT_ASSESSED`, and the owning customer may withdraw it from `REQUESTED` — withdrawal requires `X-User-ID` equal to the job's `customer_id`, else `ERR_FORBIDDEN_OWNERSHIP`. Any action attempted from a status that does not declare it is rejected with `ERR_CHANGE_ORDER_INVALID_TRANSITION` (HTTP 409).

Applying an approved order — a `PlantManager` action — first re-verifies that the new design is still `SEALED` and current, rejecting with `ERR_DESIGN_NOT_CURRENT` if a newer `SEALED` revision has since appeared. The apply then executes a six-hop cascade in order. Hop 1: the superseded design moves `SEALED` to `SUPERSEDED`. Hop 2: each cut list of that design moves — a list in `EXPLODED` goes to `SUPERSEDED`; a list in `RELEASED` with no line in `CUT` goes to `SUPERSEDED`; a list in `RELEASED` with at least one line in `CUT` goes to `RECONCILING`, the design-change-after-cut state that §3.4's reconcile later closes. Hop 3: every reservation still `RESERVED` on `PENDING` lines of those lists — or plate-level reservations on the lists themselves — moves to `RELEASED`, restoring each lot's available quantity exactly and incrementing each lot's `version`; for a list that went to `SUPERSEDED` without any cut line, this covers all of its `RESERVED` reservations. Hop 4: every production batch referencing those cut lists and sitting in `SCHEDULED`, `CUTTING`, `ASSEMBLY`, `BUILT`, `QC_PASSED`, `QC_FAILED`, `REWORK`, or `STAGED` moves to `CANCELLED`, and the surviving batches' `build_sequence_no` values are recomputed per §3.6. Hop 5: every bundle in `PACKED` referencing a cancelled batch moves to `SUPERSEDED`, its delivery load — if in `PLANNED`, `STAGED`, or `LOADING` — reopens to `PLANNED`, and the load's `actual_total_weight_lbs` is recomputed excluding the superseded bundles. Hop 6: the job's posture is recomputed, reading `BLOCKED` for as long as any cut list remains `RECONCILING`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all lifecycle transitions, confirmations, cancellations, settlements, and the clock-setting capability — return `200 OK`, as do all reads. The table below is a navigational summary only; request payloads, conditional inputs, guards, and side effects are defined by the workflows in §3 and the global rules in §2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/customer-accounts` | Create a customer account | PlantManager |
| GET | `/plant/customer-accounts/{id}` | Read one customer account | All roles |
| GET | `/plant/customer-accounts` | List customer accounts | All except CustomerContact |
| PATCH | `/plant/customer-accounts/{id}` | Update credit/storage terms; setting `credit_hold` true flips all of the customer's jobs to posture `BLOCKED` | PlantManager |
| POST | `/plant/engineers` | Register an engineer of record | PlantManager |
| GET | `/plant/engineers/{id}` | Read one engineer | All except CustomerContact |
| GET | `/plant/engineers` | List engineers | All except CustomerContact |
| POST | `/plant/jobs` | Create a job; CustomerContact creators must pass their own `customer_id` | CustomerContact, PlantManager |
| GET | `/plant/jobs/{id}` | Read one job including derived `posture` | All roles |
| GET | `/plant/jobs` | List jobs with filters | All roles |
| POST | `/plant/jobs/{id}/confirm` | `QUOTED` to `CONFIRMED` | PlantManager |
| POST | `/plant/jobs/{id}/cancel` | Cancel a job with the full down-cascade (loads, batches, cut lists, reservations) | PlantManager |
| POST | `/plant/jobs/{job_id}/designs` | Create a design or revision; OCC-guarded on the job's `version` | DesignEngineer |
| GET | `/plant/designs/{id}` | Read one design | All roles |
| GET | `/plant/designs` | List designs with filters | All roles |
| POST | `/plant/designs/{id}/transition` | Design lifecycle: `DRAFT` to `SEAL_REQUESTED` to `SEALED`, reject back to `DRAFT`, `DRAFT` to `VOID`; seal runs the license/state/authority/segregation gates | DesignEngineer |
| POST | `/plant/designs/{design_id}/cut-lists` | Explode a sealed current design into a cut list with line children and computed totals | ProductionPlanner |
| GET | `/plant/cut-lists/{id}` | Read one cut list | All except CustomerContact |
| GET | `/plant/cut-lists` | List cut lists with filters | All except CustomerContact |
| POST | `/plant/cut-lists/{id}/release` | `EXPLODED` to `RELEASED`; first release moves the job to `IN_PRODUCTION` | ProductionPlanner |
| POST | `/plant/cut-lists/{id}/reconcile` | `RECONCILING` to `CLOSED`; scraps lines with waste accrual | ProductionPlanner |
| GET | `/plant/cut-list-lines` | List cut list lines with filters | All except CustomerContact |
| GET | `/plant/cut-list-lines/{id}` | Read one cut list line | All except CustomerContact |
| POST | `/plant/cut-list-lines/{id}/mark-cut` | `PENDING` to `CUT`; requires a batch of the line's cut list in `CUTTING` | ShopFloorLead |
| POST | `/plant/cut-list-lines/{id}/scrap` | `PENDING` or `CUT` to `SCRAPPED`; releases reservations or accrues waste | ShopFloorLead |
| POST | `/plant/jig-setups` | Create an immutable jig setup with its changeover matrix | PlantManager |
| GET | `/plant/jig-setups/{id}` | Read one jig setup | All except CustomerContact |
| GET | `/plant/jig-setups` | List jig setups | All except CustomerContact |
| POST | `/plant/inventory-lots` | Receive a lumber or plate lot; availability initializes to received quantities | InventoryManager |
| GET | `/plant/inventory-lots/{id}` | Read one lot | All except CustomerContact |
| GET | `/plant/inventory-lots` | List lots with filters | All except CustomerContact |
| POST | `/plant/inventory-lots/{id}/adjust` | Manual availability/scrap adjustment with a mandatory `reason` | InventoryManager |
| POST | `/plant/inventory-lots/{id}/transition` | `ACTIVE` to `QUARANTINED` and back | InventoryManager |
| POST | `/plant/material-reservations` | Reserve lumber against a line or plates against a list; OCC-guarded on the lot's `version` | ProductionPlanner |
| GET | `/plant/material-reservations` | List reservations with filters | All except CustomerContact |
| GET | `/plant/material-reservations/{id}` | Read one reservation | All except CustomerContact |
| POST | `/plant/material-reservations/{id}/consume` | `RESERVED` to `CONSUMED`; reserved shifts to consumed on the lot | InventoryManager |
| POST | `/plant/material-reservations/{id}/release` | `RESERVED` to `RELEASED`; availability restored exactly | InventoryManager |
| POST | `/plant/cranes` | Register a plant crane | PlantManager |
| GET | `/plant/cranes/{id}` | Read one crane | All except CustomerContact |
| GET | `/plant/cranes` | List cranes | All except CustomerContact |
| POST | `/plant/cranes/{id}/transition` | `ACTIVE` to `OUT_OF_SERVICE` and back | PlantManager |
| POST | `/plant/crane-slots` | Book a buffered crane interval; OCC-guarded on the crane's `version` | ProductionPlanner |
| GET | `/plant/crane-slots` | List crane slots with filters | All except CustomerContact |
| GET | `/plant/crane-slots/{id}` | Read one crane slot | All except CustomerContact |
| POST | `/plant/crane-slots/{id}/transition` | `BOOKED` to `COMPLETED` or `CANCELLED`; cancelling frees the interval | ProductionPlanner |
| POST | `/plant/jobs/{job_id}/batches` | Schedule a production batch off a `RELEASED` cut list | ProductionPlanner |
| GET | `/plant/batches/{id}` | Read one batch | All except CustomerContact |
| GET | `/plant/batches` | List batches with filters | All except CustomerContact |
| POST | `/plant/batches/{id}/transition` | Batch lifecycle including the QC fail/rework loop; `STAGED` to `LOADED` and any direct cancel are system-only | ShopFloorLead |
| POST | `/plant/jobs/{job_id}/loads` | Plan a delivery load; computes provisional freight; checks window, drops-per-day, and credit | ShippingCoordinator |
| GET | `/plant/loads/{id}` | Read one load | All roles |
| GET | `/plant/loads` | List loads with filters | All roles |
| POST | `/plant/loads/{id}/transition` | Load lifecycle including the return/reschedule loop and final-freight close; conditional inputs `rescheduled_date` and `crane_hours_actual` | ShippingCoordinator |
| POST | `/plant/loads/{load_id}/bundles` | Add a bundle to the load's bundle map with crane-capacity and stack-position checks | ShippingCoordinator |
| GET | `/plant/bundles/{id}` | Read one bundle | All except CustomerContact |
| GET | `/plant/bundles` | List bundles with filters | All except CustomerContact |
| POST | `/plant/loads/{load_id}/claims` | File a damage claim against a delivered bundle; the load moves to `CLAIM_HOLD` | CustomerContact |
| GET | `/plant/claims/{id}` | Read one claim | All roles |
| GET | `/plant/claims` | List claims with filters | All roles |
| POST | `/plant/claims/{id}/triage` | `FILED` to `TRIAGED`; records `triaged_by` | ClaimsAdjuster |
| POST | `/plant/claims/{id}/decide` | `TRIAGED` to `APPROVED_REBUILD`, `APPROVED_CREDIT`, or `DENIED`; computes the cap; rebuild decision fires the rebuild cascade | ClaimsAdjuster |
| POST | `/plant/claims/{id}/settle` | Settle with actual cost inputs; waterfall buckets plus residual credit | ClaimsAdjuster |
| POST | `/plant/claims/{id}/void` | Void from `FILED` or `TRIAGED`, or reverse a `SETTLED` claim | ClaimsAdjuster |
| POST | `/plant/jobs/{job_id}/change-orders` | Request a design change; OCC-guarded on the job's `version` | CustomerContact, ProductionPlanner |
| GET | `/plant/change-orders/{id}` | Read one change order | All roles |
| GET | `/plant/change-orders` | List change orders with filters | All roles |
| POST | `/plant/change-orders/{id}/assess` | `REQUESTED` to `IMPACT_ASSESSED`; computes impact counts; may set `new_design_id` | ProductionPlanner |
| POST | `/plant/change-orders/{id}/approve` | `IMPACT_ASSESSED` to `APPROVED`; requires a sealed chain-valid new design | PlantManager |
| POST | `/plant/change-orders/{id}/reject` | `REQUESTED` or `IMPACT_ASSESSED` to `REJECTED` | PlantManager |
| POST | `/plant/change-orders/{id}/apply` | `APPROVED` to `APPLIED`; runs the six-hop cascade | PlantManager |
| POST | `/plant/change-orders/{id}/withdraw` | `REQUESTED` to `WITHDRAWN` by the owning customer | CustomerContact |
| POST | `/plant/_clock/set_current_utc` | Set the server's logical clock | PlantManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are defined by the narratives in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DESIGN_NOT_AWAITING_SEAL` | 409 Conflict |
| `ERR_DESIGN_NOT_CURRENT` | 409 Conflict |
| `ERR_CUT_LIST_NOT_RELEASED` | 409 Conflict |
| `ERR_CUT_LIST_NOT_RECONCILING` | 409 Conflict |
| `ERR_BATCH_INVALID_TRANSITION` | 409 Conflict |
| `ERR_LOAD_INVALID_TRANSITION` | 409 Conflict |
| `ERR_CLAIM_INVALID_TRANSITION` | 409 Conflict |
| `ERR_CHANGE_ORDER_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ENGINEER_LICENSE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_ENGINEER_LICENSE_STATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_SEAL_AUTHORITY_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SEALER_MUST_DIFFER_FROM_SUBMITTER` | 422 Unprocessable Entity |
| `ERR_CLAIM_DECIDER_MUST_DIFFER` | 422 Unprocessable Entity |
| `ERR_CRANE_SLOT_OVERLAP` | 409 Conflict |
| `ERR_BUNDLE_OVERWEIGHT` | 422 Unprocessable Entity |
| `ERR_STACK_POSITION_CONFLICT` | 409 Conflict |
| `ERR_INSUFFICIENT_INVENTORY` | 422 Unprocessable Entity |
| `ERR_RESERVATION_KIND_MISMATCH` | 422 Unprocessable Entity |
| `ERR_JIG_COMPONENT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_COMPONENT_REF` | 409 Conflict |
| `ERR_REVISION_CHAIN_BROKEN` | 422 Unprocessable Entity |
| `ERR_RESERVATION_COVERAGE_SHORT` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_DELIVERY_WINDOW` | 422 Unprocessable Entity |
| `ERR_DROPS_PER_DAY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SLOT_IN_PAST` | 422 Unprocessable Entity |
| `ERR_BUNDLE_JOB_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_BUNDLE_NOT_IN_LOAD` | 422 Unprocessable Entity |
| `ERR_CREDIT_HOLD` | 402 Payment Required |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_JOB_VERSION` | 412 Precondition Failed |
| `ERR_STALE_LOT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CRANE_VERSION` | 412 Precondition Failed |

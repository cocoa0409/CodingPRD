# Exhibition Venue API — Product Requirements Document

## 1. Introduction

Exhibition and convention venues operate at the intersection of physical space, time, and money: floor plans must be partitioned into halls, zones, aisles and grid cells; booths must be priced, allocated to qualified exhibitors, and adjusted when objections arise; setup and teardown must be choreographed around dock arrivals, crane and forklift availability, and safety inspections; tickets must be sold across channels and scanned at the gate against a hard occupancy ceiling; sponsor entitlements must be tracked to deadline; and every consequential decision must leave an audit trail. The Exhibition Venue API is the system of record that coordinates all of these concerns for a single trade-show operator running many exhibitions back-to-back.

The product is a multi-tenant, role-aware HTTP API whose primary users are the venue's own staff (administrative, operational, and front-gate), the exhibitors who rent booths and order services, and the third-party service providers who execute on-site work. The API governs every lifecycle step of an exhibition from initial layout drafting through final post-event entitlement reporting. The design emphasizes posture-driven gating so that a single exhibition's state controls who may enter, scan, or sell tickets at any given moment; explicit hierarchical cascades so that publishing an allocation, activating a floor plan, or closing an exhibition propagates correctly through booths, applications, tickets, and entitlements; and a small number of monetary calculations (booth pricing, work-order billing, ticket pricing, make-good credits, fulfillment scores) that must be reproducible to the cent.

All resource paths in this document are mounted under the `/exhibitions` prefix where applicable, with cross-cutting top-level resources (allocations, applications, booths, dock-slots, work-orders, tickets, entitlements) addressed by their own identifiers. Time-gated transitions (such as objection-window expiry and entitlement deadline lapses) are reachable in tests through a privileged clock-advance capability documented in §4.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: how callers authenticate, how responses are shaped, how lists are paginated, and the cross-cutting principles that every domain workflow inherits.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the calling principal, and `X-User-Role`, which names the operational capacity in which the caller is acting. Requests missing either header are rejected with `ERR_AUTH_REQUIRED` (401). Requests whose role is not on the endpoint's permitted list are rejected with `ERR_FORBIDDEN` (403). The system recognizes exactly six roles, spelled as `VenueAdmin`, `VenueOps`, `Exhibitor`, `ServiceProvider`, `GateOperator`, and `TestHarness`.

`VenueAdmin`, `VenueOps`, `ServiceProvider`, `GateOperator`, and `TestHarness` are opaque operator roles. When `X-User-Role` is any of these five, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it (for example, as `inspector_id` on a SafetyInspection or as `actor_id` on an AuditLogEntry where a scaffold transition writes it) but does not compare it to any entity's `id`. `TestHarness` is a privileged test-only role used to advance the logical clock; it is not intended to be exposed in production.

`Exhibitor` is entity-backed against ExhibitorApplication: when `X-User-Role` is `Exhibitor`, `X-User-ID` is the opaque exhibitor identifier carried as the `exhibitor_id` foreign key on ExhibitorApplication, BoothAllocation, DockSlot, WorkOrder, and SponsorEntitlement. Ownership checks on any of these resources compare the resource's `exhibitor_id` field to `X-User-ID`; the same exhibitor uses the same opaque string across all of their applications, and ExhibitorApplication is the first persisted record minted under that identifier.

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

Endpoints that return list responses accept two query parameters: `limit` and `offset`. The `limit` parameter caps the number of items returned in a single page; its default is 10, its minimum is 1, and its maximum is 100. The `offset` parameter is the number of items to skip from the start of the result set; its default is 0. Unless an endpoint explicitly overrides the order (for example, with a `sort_by` parameter on the applications list), list responses are sorted by `created_at` ascending. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the standard `api_request_id` and `api_request_timestamp`.

### 2.4. Common Resource Properties and Identifiers

Every primary resource in the system carries a server-minted `id` formatted as a UUID (no type prefix) and a `created_at` timestamp serialized as an ISO 8601 UTC value with three fractional digits. Most resources additionally carry `updated_at` (also ISO 8601 UTC with three fractional digits, refreshed on every mutation) and a `version` field that is a non-negative integer starting at 0 or 1 and incremented by 1 on every server-side mutation of the row. Two entities are exceptions: FloorPlanVersion and SafetyInspection carry only `id` and `created_at` — they have neither `updated_at` nor `version`, because once captured they are not in-place editable rows. The same `id`-only-plus-`created_at` convention applies to AuditLogEntry rows, which are append-only.

Sub-objects embedded in `cells` arrays (floor-plan cell descriptors and booth cell coordinates), in WorkOrder `lines`, and in AuditLogEntry `payload` fields do not receive separately addressable identifiers; they are mutated only by replacing the owning row through one of its workflow endpoints.

### 2.5. Optimistic Concurrency Control

All mutation endpoints that target a specific row by identifier accept an optional `version` field in the request body. When `version` is present, the server compares it against the row's current `version`; if they do not match, the request is rejected with `ERR_VERSION_CONFLICT` (409). When `version` is omitted from the request body, the OCC check is skipped and the mutation proceeds against whatever the current row state is. A successful mutation always increments `version` by 1 and refreshes `updated_at`.

### 2.6. Hierarchical Consistency and Cascading Effects

Several lifecycle transitions deliberately propagate state into dependent rows in a single atomic step. Publishing the allocation set for an exhibition moves every BoothAllocation that is still in the `PROPOSED` state to `PUBLISHED`, pins the price quoted to each, and writes one AuditLogEntry per allocation; the cascade depth is one. Activating a FloorPlanVersion moves any currently-`ACTIVE` plan on the same hall to `SUPERSEDED` and forcibly transitions every Booth tied to the superseded plan to the `BLOCKED` status; the cascade depth is one. Closing the doors of an `OPEN` exhibition moves the exhibition to `TEARDOWN`, lowers the exhibition's posture to `RESTRICTED`, and voids every Ticket still in `ISSUED`. Closing an exhibition out of `TEARDOWN` moves the exhibition to `CLOSED`, lowers posture to `FROZEN`, and auto-misses any SponsorEntitlement still in `IN_PROGRESS` or `MAKE_GOOD_OFFERED` — each such row recomputes its make-good credit and final fulfillment score.

Scanning a ticket into an `OPEN` exhibition is itself a two-level cascade: the ticket's own status flips to `SCANNED_IN`, the exhibition's `live_occupancy` increments, and the exhibition's posture may flip from `OPEN` to `RESTRICTED` once occupancy crosses the saturation threshold. Scanning out is the symmetric counterpart and may restore posture to `OPEN` once occupancy falls below the recovery threshold. Each cascade reaches `updated_at`/`version` on every row it mutates.

The advance-clock capability is itself a cascade source: when the test harness advances the logical clock past the `deadline` of any SponsorEntitlement still in `IN_PROGRESS`, that entitlement is auto-MISSED with its make-good credit computed and final fulfillment score pinned at the moment the clock crosses the deadline. The cascade depth is two (entitlement state change, then derived monetary fields).

### 2.7. Nested Resource Retrieval

Endpoints whose path embeds more than one identifier validate those identifiers strictly in left-to-right order, returning `ERR_NOT_FOUND` (404) for the first identifier that does not resolve. The full resolution order is Exhibition first, then Hall, then FloorPlanVersion, then Booth, then BoothAllocation, then DockSlot, then WorkOrder, then Ticket, then SponsorEntitlement, then ExhibitorApplication. A request that targets, for example, a booth under a non-existent hall fails at the hall step with `ERR_NOT_FOUND` and never reaches booth resolution.

### 2.8. Monetary Precision and Rounding

Every monetary field in the system is stored and exchanged as integer cents — no fractional cents anywhere on the wire. All monetary calculations apply round-half-up at the precision points documented in §3 for each formula. Where a multi-step formula has multiple rounding points (notably the per-line work-order billing and the multiplier chain for booth pricing), the evaluation order of rounding is pinned and described with the calculation. The `fulfillment_score` and the `priority_score` are not monetary; they are kept to four decimal places using round-half-up.

### 2.9. Posture-Driven Gating

Each Exhibition carries a `posture` that runs orthogonally to its lifecycle `status` and gates real-time gate operations. The three legal values are `OPEN` (entry permitted, ticket scanning enabled), `RESTRICTED` (gate scanning blocked for non-staff; staff-only entry), and `FROZEN` (all gate operations and new ticket sales blocked). Posture is computed by the server in response to lifecycle transitions and ticket scans, never set directly by a client. Attempts to scan tickets in or out when the posture forbids the operation are rejected with `ERR_POSTURE_BLOCKED` (409). The default initial posture of a `DRAFT` exhibition is `FROZEN`.

### 2.10. Validation Priority

When multiple validations apply to a single request, the server evaluates them in a fixed priority order and returns the first failing error. The order is: authentication header presence first (`ERR_AUTH_REQUIRED`), then role permission (`ERR_FORBIDDEN`), then path-identifier existence (`ERR_NOT_FOUND`, applied left-to-right per §2.7), then state-transition legality (`ERR_INVALID_STATE`), then domain-safety gates such as posture, safety-inspection presence, and overnight-permit requirement, then business constraints (fire-safety cells, utility load, theme intersection, capacity, group, relocation tier, work-order line shape, dispute resolution band, floor-plan lock), and finally OCC (`ERR_VERSION_CONFLICT`, evaluated last among 409-class errors when a `version` was supplied). The downstream effect is that, for instance, a stale-version object directed at the wrong-state row will surface as `ERR_INVALID_STATE` rather than `ERR_VERSION_CONFLICT`, and a compliance/posture failure will surface ahead of a business-constraint failure when both could apply.

### 2.11. Audit Logging

Every consequential allocation-side or entitlement-side decision is recorded as an AuditLogEntry. The append-only entry carries a `subject_kind` of `ALLOCATION` or `ENTITLEMENT`, the `subject_id` of the affected row, an `action` string (such as `PUBLISH`, `OBJECT`, `RELOCATE`, `REVOKE`, `FULFILL`, `MAKE_GOOD_OFFERED`), the `actor_role` and `actor_id` of the principal that triggered it, and an action-specific JSON `payload` snapshot.

### 2.12. Concurrency and Serialization

Concurrent operations on the same shared resource serialize first-writer-wins. Two exhibitors attempting to book overlapping intervals on the same `dock_code` serialize on DockSlot row creation: at most one succeeds, the loser receives `ERR_DOCK_SLOT_OVERLAP` (409). Two BoothAllocation creations against the same booth serialize on the booth's `AVAILABLE → RESERVED` transition: at most one succeeds, the loser receives `ERR_BOOTH_ALREADY_ALLOCATED` (409). Two simultaneous relocate attempts on the same allocation serialize on its `RELOCATING → PUBLISHED` transition: exactly one wins, the loser receives `ERR_INVALID_STATE` (409). Two scan-ins of the same ticket serialize on its `ISSUED → SCANNED_IN` transition: only one increments `live_occupancy`, the loser receives `ERR_INVALID_STATE` (409). Two scan-ins racing at the capacity boundary (`live_occupancy` equal to one less than `capacity_max`) serialize on the atomic occupancy increment: exactly one succeeds, the loser receives `ERR_CAPACITY_EXCEEDED` (409). A confirm and a revoke racing on the same allocation in `PUBLISHED` serialize on its outgoing transition: exactly one wins, the loser receives `ERR_INVALID_STATE` (409).

## 3. Business Logic & Workflows

### 3.1. The Exhibition Lifecycle and Postures

The central organizing entity is the **Exhibition**. A `VenueAdmin` initiates one by supplying its `name`, a `theme_code` tag used downstream to gate exhibitor applications, the `open_date` and `close_date` timestamps that bracket the show, the `capacity_max` ceiling on simultaneous on-site occupants, and optionally an `objection_window_hours` value (defaulting to seventy-two hours) that controls how long published allocations may be objected to. A freshly created exhibition is in the `DRAFT` lifecycle status with posture `FROZEN`.

Once at least one Hall under the exhibition has an `ACTIVE` floor plan and the `theme_code` is non-empty, the admin may open intake, transitioning the exhibition from `DRAFT` to `INTAKE_OPEN`. The posture is set to `FROZEN` on this transition — entry remains blocked because the show is not running yet. The system then accepts exhibitor applications until the admin publishes the allocation set, transitioning to `ALLOCATION_PUBLISHED`. Publication requires every application to be in one of `QUALIFIED`, `REJECTED`, or `WITHDRAWN`, and at least one BoothAllocation in `PROPOSED` to exist for the exhibition. Publication cascades each proposed allocation to `PUBLISHED`, pins its quoted price, stamps each with the publication moment, writes an AuditLogEntry per allocation, and stamps the exhibition's `allocation_published_at` to the current server clock.

Moving from `ALLOCATION_PUBLISHED` to `SETUP` requires that every BoothAllocation on the exhibition has reached `CONFIRMED` or `REVOKED`, and that the current server clock is at or beyond the moment the allocation was published plus the exhibition's `objection_window_hours` value (so the objection window has elapsed). On the transition to `SETUP`, the posture moves to `RESTRICTED` (gate scanning blocked, staff only). Opening the doors then requires a `PRE_OPEN` SafetyInspection with a `PASS` result on the exhibition, and the current clock to be at or beyond `open_date`; on success, the exhibition moves to `OPEN` and posture flips to `OPEN`. Closing the doors requires the current clock to be at or beyond `close_date` and the exhibition's `live_occupancy` to be exactly zero; the transition lowers posture to `RESTRICTED` and voids any Ticket still in `ISSUED`. Closing the exhibition out of `TEARDOWN` requires every WorkOrder to be in `BILLED`, `RESOLVED`, or `CANCELLED`, and every SponsorEntitlement to be in `FULFILLED`, `MISSED`, `MAKE_GOOD_ACCEPTED`, or `WAIVED`; the transition lowers posture to `FROZEN` and auto-MISSes any entitlement still in `IN_PROGRESS` or `MAKE_GOOD_OFFERED`, recomputing its `make_good_credit_cents` and pinning its final `fulfillment_score`. `CLOSED` is terminal. A failure of any of these preconditions surfaces as `ERR_INVALID_STATE`; an attempt to open the doors without a `PRE_OPEN` `PASS` surfaces as `ERR_SAFETY_INSPECTION_MISSING`.

### 3.2. Halls, Floor Plans, and Booths

A **Hall** is created under an exhibition by supplying a `hall_code` unique within that exhibition, a `zone_label` identifying its zone within the venue layout, an `aisle_label` for its aisle within that zone, the integer `grid_rows` and `grid_cols` that describe its grid dimensions, and an array `fire_safety_zone_cells` of `{row, col}` coordinates reserved as fire-safety constraints on which no booth may stand. Each hall also tracks `floor_plan_active_version`, an integer that mirrors the currently-active plan's version number; this field starts at 1 and is maintained by the system.

A **FloorPlanVersion** belongs to a hall (its `hall_id` foreign key) and contains a `cells` array describing every cell in the hall's grid as a `{row, col, kind, power_kw, water_lpm, network_mbps}` descriptor, where the `kind` is one of `FIXED`, `MODULAR`, or `FIRE_SAFETY`. The version's `version_number` is monotonically increasing per hall and starts at 1; the version's `status` runs through `DRAFT`, `ACTIVE`, and `SUPERSEDED`. Activation is only permitted while the owning exhibition is still in `DRAFT` — once intake has opened, an activation attempt is rejected with `ERR_FLOOR_PLAN_LOCKED`. Activation also requires that the cells exactly cover the full `grid_rows`-by-`grid_cols` extent of the hall and that no two cells share the same `(row, col)` pair; failures surface as `ERR_INVALID_INPUT`. On a successful activation, the previously-`ACTIVE` plan on the same hall is automatically moved to `SUPERSEDED`, the hall's `floor_plan_active_version` is set to this plan's `version_number`, the version's `published_at` is stamped, and every Booth that referenced the superseded plan is forcibly moved to `BLOCKED`.

A **Booth** lives inside an active floor plan and is described by a `code` unique within its hall (e.g. `A-12`), a `floor_plan_version_id` that must be `ACTIVE` at the moment the booth is created, a `cells` array of `{row, col}` coordinates the booth occupies (at least one cell, every cell must exist in the plan, and every referenced cell must be of `kind` `FIXED` or `MODULAR`), and a `tier` chosen from `STANDARD`, `PREMIUM`, or `ISLAND`. Any attempt to place a booth on a `FIRE_SAFETY` cell is rejected with `ERR_FIRE_SAFETY_CELL`. At creation time the server computes the boolean `is_corner` flag (true when the booth's cell rectangle touches at least two perpendicular aisle edges), the booth's `power_kw_capacity` and `water_lpm_capacity` as the sum of the corresponding per-cell fields across the booth's cells, and the booth's `network_mbps_capacity` as the integer sum of the cells' `network_mbps`. The booth's `base_price_cents` is computed via the at-creation variant of the booth pricing rule described below, and the booth's `status` starts at `AVAILABLE`.

The booth pricing rule produces an integer-cent quote in four pinned steps. **Step one** picks a tier base in cents: two hundred thousand for `STANDARD`, three hundred and fifty thousand for `PREMIUM`, and six hundred thousand for `ISLAND`. **Step two** computes a cell-count multiplier that is one in every case except `ISLAND` booths with more than four cells; for those, every cell beyond the fourth adds ten percent — so a six-cell `ISLAND` carries a multiplier of one plus zero-point-one times two, equal to one-point-two. Booths in `STANDARD` or `PREMIUM` always use a multiplier of one regardless of cell count. **Step three** picks a corner multiplier of one-point-one-five when the booth's `is_corner` flag is true, and one otherwise. **Step four** picks a theme add-on of fifty thousand cents when the exhibition's `theme_code` starts with the prefix `PRO_`, and zero otherwise. The evaluation order is pinned: multiply the tier base by the cell-count multiplier, then by the corner multiplier, then round half-up to integer cents, then add the theme add-on. The at-creation variant writes the result to the booth's `base_price_cents` field. The at-publish-or-relocate variant re-evaluates the same formula against the booth's current state and the exhibition's current `theme_code` at the moment the allocation moves into `PUBLISHED` (either from `PROPOSED` at first publication or from `RELOCATING` after a successful relocate), and pins the result into the allocation's `quoted_price_cents` — if the booth's `tier` or `is_corner` has changed since creation, the published quote will differ from `base_price_cents`.

A booth's `status` runs through `AVAILABLE` (default), `RESERVED` (an allocation is being proposed against it), `ALLOCATED` (the allocation has been published), `RELOCATING` (the allocation is being moved to a different booth), and `BLOCKED` (taken out of service, typically because its plan was superseded).

### 3.3. Exhibitor Applications and Allocation Priority

An **ExhibitorApplication** is created by a caller acting as `Exhibitor` against a target exhibition. The submission payload carries the exhibitor's declared `theme_tags` array, the `requested_tier` (one of `STANDARD`, `PREMIUM`, or `ISLAND`), the `sponsorship_level` (one of `NONE`, `BRONZE`, `SILVER`, `GOLD`, or `PLATINUM`, defaulting to `NONE`), and the `seniority_years` count of years the exhibitor has continuously participated (defaulting to zero). The system also records `exhibitor_id` (equal to `X-User-ID` for the calling exhibitor) and the target `exhibition_id`. A newly created application is in `DRAFT`.

When the exhibitor submits the application, the system requires the owning exhibition to be in `INTAKE_OPEN` (otherwise `ERR_INVALID_STATE`), and on successful submission it assigns a random integer `lottery_token` drawn uniformly from the closed interval bounded below by 0 and above by 999999, and computes the application's `priority_score`. The score is a weighted sum with a pinned evaluation order: a sponsor weight first (0 for `NONE`, 100 for `BRONZE`, 250 for `SILVER`, 500 for `GOLD`, 1000 for `PLATINUM`), plus a seniority weight equal to ten times the smaller of `seniority_years` and twenty (so each year adds ten, capped at twenty years), plus a lottery component equal to `lottery_token` divided by ten thousand (yielding a value in the closed-open interval bounded below by zero and above by one hundred). The lottery component is intentionally bounded under one hundred so that it cannot outrank any sponsor-tier gap; it is only a final tiebreak. The lottery component is rounded half-up to four decimal places, and the final score is sorted descending when the admin ranks applications.

After submission the admin can start review (moving the application to `UNDER_REVIEW`), qualify it (moving it to `QUALIFIED`, provided the application's `theme_tags` set intersects the singleton set containing the exhibition's `theme_code` — failure surfaces as `ERR_THEME_MISMATCH`), or reject it (moving it to `REJECTED` while recording a non-empty `rejection_reason` on the row). An exhibitor can withdraw their own application from `SUBMITTED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`. When an admin later creates a BoothAllocation against a `QUALIFIED` application, the application is moved to the terminal `ALLOCATED` state as a side-effect.

### 3.4. Booth Allocation, Publication, Objection, and Relocation

A **BoothAllocation** is created by the admin by linking a qualified application to an available booth via a payload containing the `application_id` and the `booth_id`; the system denormalizes `exhibition_id` and `exhibitor_id` from the application onto the allocation. The booth must be in `AVAILABLE` status — creating an allocation against any other status is rejected with `ERR_BOOTH_ALREADY_ALLOCATED`. On creation, the booth moves to `RESERVED` and the application moves to `ALLOCATED`. The allocation starts in `PROPOSED`.

Publication is not per-row but per-exhibition: when the admin moves the exhibition from `INTAKE_OPEN` to `ALLOCATION_PUBLISHED`, every allocation still in `PROPOSED` is cascaded to `PUBLISHED` in a single step. For each cascading allocation, the at-publish-or-relocate variant of the booth pricing rule is evaluated and the result is pinned to `quoted_price_cents`, the booth moves to `ALLOCATED`, `published_at` is stamped to the current server clock, and an AuditLogEntry with `action` `PUBLISH` is recorded carrying the pinned price in its payload.

Once published, an allocation enters its objection window. The exhibitor named by the allocation may file an objection by supplying a `reason`, moving the allocation from `PUBLISHED` to `OBJECTED` and writing an AuditLogEntry with `action` `OBJECT` and the reason in its payload. The objection is only accepted while the current server clock is strictly less than the allocation's `published_at` plus the exhibition's `objection_window_hours`; later objections are rejected with `ERR_OBJECTION_WINDOW_CLOSED`. The acting exhibitor's `X-User-ID` must equal the allocation's `exhibitor_id`. Alternatively, the exhibitor may confirm the allocation (moving it from `PUBLISHED` to the terminal `CONFIRMED` and emitting an exhibitor-CRM sync event), or the admin may revoke it (moving it from `PUBLISHED` to the terminal `REVOKED` while supplying a `reason` — revocation requires the exhibition to be in `ALLOCATION_PUBLISHED` and cascades by setting the booth back to `AVAILABLE`, reverting the application to `QUALIFIED`, and writing an AuditLogEntry with `action` `REVOKE`).

Relocation is the admin's response to an objection. From `OBJECTED`, the admin starts the relocation, which moves the allocation to `RELOCATING`, frees the original booth back to `AVAILABLE`, and stashes the original `booth_id` in `relocation_source_booth_id`. The admin then supplies a `target_booth_id` to complete the relocation; the target booth must currently be `AVAILABLE` and must share the same `tier` as the original booth — a tier mismatch is rejected with `ERR_RELOCATION_TIER_MISMATCH`. On success, the allocation's `booth_id` is rewritten to the target, the target booth moves to `ALLOCATED`, `quoted_price_cents` is re-pinned via the at-publish-or-relocate variant of the booth pricing rule, the allocation moves back to `PUBLISHED`, and an AuditLogEntry with `action` `RELOCATE` is recorded carrying the from and to booth identifiers in its payload.

### 3.5. Move-In, Move-Out, and Safety Gating

Setup and teardown move through the venue's loading docks. A **DockSlot** is created by the exhibitor by supplying the `dock_code` of the physical dock (e.g. `D1`, `D2`), a `window_kind` of `MOVE_IN` or `MOVE_OUT`, the inclusive `start_at` and exclusive `end_at` ISO-8601 timestamps bounding the slot, the `allocation_id` of the BoothAllocation booking the slot, and optional booleans `crane_required`, `forklift_required`, and `overnight_permit` that default to false. The system requires that the acting exhibitor's `X-User-ID` equals the allocation's `exhibitor_id`, that the allocation is in `CONFIRMED`, that a `MOVE_IN` slot is booked only while the exhibition is in `SETUP`, and that a `MOVE_OUT` slot is booked only while the exhibition is in `TEARDOWN`. A new slot enters `BOOKED` directly on creation.

Two business-temporal validations gate slot creation. First, the `[start_at, end_at)` half-open interval must not overlap any other `BOOKED` slot on the same `dock_code`; overlap is rejected with `ERR_DOCK_SLOT_OVERLAP`. Second, crane and forklift contention are checked exhibition-wide and per-resource: at most one `BOOKED` slot anywhere on the exhibition may have `crane_required` true at the same `start_at`, and the same rule applies independently to `forklift_required` — a conflict surfaces as `ERR_RESOURCE_CONFLICT`. Any slot whose `[start_at, end_at)` crosses 22:00 local must be created with `overnight_permit` set to true; missing the permit surfaces as `ERR_OVERNIGHT_PERMIT_REQUIRED`.

Completing a slot is the operations team's responsibility and moves it from `BOOKED` to the terminal `COMPLETED`. For a `MOVE_IN` slot, completion requires a SafetyInspection of kind `BOOTH_MOVE_IN` linked to that slot's `dock_slot_id` with a `PASS` result; the absence of such an inspection surfaces as `ERR_SAFETY_INSPECTION_MISSING`. If the slot also has `overnight_permit` set to true, the linking inspection must have been recorded within the last eight hours of the current clock. On completion, the slot's `safety_inspection_passed` flag is set to true; this flag is required to be true on any earlier `MOVE_IN` slot of the same allocation before subsequent `MOVE_IN` slots may be completed. The exhibitor may also cancel a `BOOKED` slot, moving it to the terminal `CANCELLED` and clearing the slot's `allocation_id`.

A **SafetyInspection** is recorded by operations with `kind` `PRE_OPEN`, `BOOTH_MOVE_IN`, or `OVERNIGHT`, a `result` of `PASS` or `FAIL`, the `inspector_id` of the operator, an optional `dock_slot_id` (required for `BOOTH_MOVE_IN`, null for an exhibition-wide `PRE_OPEN`), and optional free-text `notes`. SafetyInspection rows are immutable once recorded and carry only `id` and `created_at`.

### 3.6. Exhibitor Service Work Orders

A **WorkOrder** captures an exhibitor's request for venue-provided services against a confirmed allocation. The exhibitor creates a draft work order by supplying the target `exhibition_id`, the target `allocation_id`, and an array of `lines`, each line containing a `service_code` from the catalog (`EXTRA_POWER`, `FURNITURE`, `NETWORK`, `CLEANING`, `SECURITY`), an integer `quantity`, and an integer `unit_price_cents`. The system also records the ordering `exhibitor_id` (which must equal the allocation's `exhibitor_id`). On submission, the system requires that the allocation is in `CONFIRMED`, that every line has a strictly positive `quantity` and a strictly positive `unit_price_cents`, and that the lines array is non-empty — failures of those input shapes surface as `ERR_INVALID_INPUT`. The work order also enforces a utility-load constraint at submit time: the sum of `quantity` across lines whose `service_code` is `EXTRA_POWER` (interpreted in kilowatts) on this booth must not exceed the booth's `power_kw_capacity`; an exceedance surfaces as `ERR_UTILITY_CAPACITY_EXCEEDED`.

Submitting the work order computes the billing fields and pins them. The billing rule processes each line with a pinned per-line-rounding-precedes-aggregation order. For each line, multiply `unit_price_cents` by `quantity` to obtain an exact integer line gross; if the line's `service_code` equals `CLEANING`, multiply the line gross by ninety-five hundredths (a five percent per-line discount applied before rounding); for every other service code use the line gross unchanged; then round the per-line amount half-up to integer cents. Sum the per-line rounded amounts to produce `subtotal_cents`. Compute `tax_cents` as `subtotal_cents` multiplied by six hundredths and rounded half-up to integer cents. Compute `total_cents` as the integer sum of `subtotal_cents` and `tax_cents`. The submission also pins `resolved_total_cents` initially to `total_cents`.

After submission, operations dispatches the work order (moving it from `SUBMITTED` to `DISPATCHED`), the service provider confirms execution (moving it from `DISPATCHED` to `EXECUTED`), and operations bills it (moving it from `EXECUTED` to the terminal `BILLED`, refreshing `resolved_total_cents` to `total_cents` and emitting a payment-system sync event with `total_cents`). The exhibitor may instead dispute an executed work order by supplying a non-empty `dispute_reason`, moving it from `EXECUTED` to `DISPUTED`. Operations resolves a disputed work order by supplying a `resolved_total_cents` value that must be greater than or equal to zero and less than or equal to the pinned `total_cents`; an out-of-band value surfaces as `ERR_DISPUTE_RESOLUTION_INVALID`. On resolution, the work order moves to the terminal `RESOLVED` and a payment-system sync event is emitted with the agreed `resolved_total_cents`. The exhibitor may also cancel a draft work order, moving it from `DRAFT` to the terminal `CANCELLED`.

### 3.7. Tickets, Capacity, and Posture

A **Ticket** is issued through the exhibition's ticket endpoint. The caller (admin, ops, or exhibitor) supplies the ticket `kind` (`VISITOR`, `PROFESSIONAL_BUYER`, `STUDENT`, or `VIP`), the sale `channel` (`ONLINE_PRESALE` or `ONSITE`), and an optional `group_id` string identifying the organized delegation; the system mints a unique `qr_code` and computes the `price_cents`. The ticket starts in `ISSUED`.

The ticket pricing rule picks a base in cents by `kind` — five thousand for `VISITOR`, twelve thousand for `PROFESSIONAL_BUYER`, two thousand five hundred for `STUDENT`, and thirty thousand for `VIP`. It then applies a channel multiplier: when `channel` is `ONSITE` and `kind` is anything other than `VIP`, the multiplier is one-point-two (a twenty-percent onsite surcharge); in every other case the multiplier is one. Finally it applies a group multiplier: when the ticket's `group_id` is not null and the count of issued tickets sharing the same `group_id` at the issuance instant is at least ten, the multiplier is zero-point-eight-five (a fifteen-percent group discount); in every other case the multiplier is one. The pinned `price_cents` is the base multiplied by the channel multiplier multiplied by the group multiplier, rounded half-up to integer cents. The group eligibility requires that the `group_id` string is identical across all members and the group is non-empty; a request that violates either condition (or a discount request below the ten-member threshold) is rejected with `ERR_GROUP_INVALID`.

Scanning a ticket in at the gate requires the exhibition's posture to be `OPEN` (otherwise `ERR_POSTURE_BLOCKED`) and the exhibition's `live_occupancy` to be strictly less than `capacity_max` (otherwise `ERR_CAPACITY_EXCEEDED` — note that an exhibition created with `capacity_max` of zero blocks every scan-in). On success, the ticket moves from `ISSUED` to `SCANNED_IN`, `scanned_in_at` is stamped to the current clock, `live_occupancy` increments by one, and an access-control gate sync event is emitted. The posture follows a saturation rule: if the ratio of `live_occupancy` to `capacity_max` reaches at least ninety-five hundredths after the increment, the exhibition's posture moves from `OPEN` to `RESTRICTED`. Scanning out moves the ticket from `SCANNED_IN` to the terminal `SCANNED_OUT`, decrements `live_occupancy`, stamps `scanned_out_at`; if the posture is currently `RESTRICTED` and the ratio of `live_occupancy` to `capacity_max` falls strictly below ninety hundredths after the decrement, the posture moves back to `OPEN`. A ticket may also be voided from `ISSUED` by an admin (terminal `VOID`) or refunded by an admin (terminal `REFUNDED`); refund is only permitted when the ticket's `channel` is `ONLINE_PRESALE` and the exhibition's `status` is not `OPEN`, and it emits a payment-system sync event with the negative of `price_cents`.

### 3.8. Sponsor Entitlements and Make-Good

A **SponsorEntitlement** captures one promised benefit owed to a sponsoring exhibitor. The admin creates each entitlement under an exhibition by supplying the `exhibitor_id` of the sponsor, the `entitlement_code` from the catalog (`SIGNAGE`, `PROGRAM_AD`, `LOUNGE`, `SPEAKING_SLOT`, or `BRANDED_GIFT`), the `sponsor_tier` (`BRONZE`, `SILVER`, `GOLD`, or `PLATINUM`) granting the entitlement, and the `deadline` timestamp by which fulfillment evidence is due. The entitlement starts in `PLANNED`.

Operations starts work on the entitlement (moving it from `PLANNED` to `IN_PROGRESS`) and later fulfills it by supplying an `evidence_url` (photo or document URL); fulfillment is only accepted when the `evidence_url` is non-empty and the current clock is at or before `deadline`, and on success the entitlement moves from `IN_PROGRESS` to the terminal `FULFILLED`, the entitlement's final `fulfillment_score` is computed and pinned, and an AuditLogEntry with `action` `FULFILL` is written carrying `evidence_url` in its payload. If the clock moves past `deadline` or the exhibition reaches `TEARDOWN`, the entitlement can be marked missed (manually by the admin, or automatically by the clock-advance cascade), moving it from `IN_PROGRESS` to `MISSED`. The miss transition computes `make_good_credit_cents` and the final `fulfillment_score`. The admin may then offer a make-good, moving the entitlement from `MISSED` to `MAKE_GOOD_OFFERED` and writing an AuditLogEntry with `action` `MAKE_GOOD_OFFERED` carrying `make_good_credit_cents` in its payload; offering requires `make_good_credit_cents` to be strictly positive. The exhibitor accepts the offer, moving the entitlement to the terminal `MAKE_GOOD_ACCEPTED` and emitting a payment-system sync event with the negative of `make_good_credit_cents`. Alternatively, the exhibitor may waive a planned entitlement directly from `PLANNED` to the terminal `WAIVED`. All exhibitor-side transitions require the acting `X-User-ID` to equal the entitlement's `exhibitor_id`.

The make-good credit picks a per-tier base in cents — ten thousand for `BRONZE`, twenty-five thousand for `SILVER`, sixty thousand for `GOLD`, one hundred and twenty thousand for `PLATINUM` — multiplies it by a per-entitlement factor (`SIGNAGE` factor five-tenths, `PROGRAM_AD` factor four-tenths, `LOUNGE` factor eight-tenths, `SPEAKING_SLOT` factor one, `BRANDED_GIFT` factor three-tenths), and rounds the product half-up to integer cents.

The `fulfillment_score` has two evaluation variants. The **provisional** variant is computed live for the entitlement report while the exhibition is not yet `CLOSED`; it does not mutate the row. It treats entitlements in `IN_PROGRESS` or `MAKE_GOOD_OFFERED` as one (assuming they will fulfill), `FULFILLED` as one, `MAKE_GOOD_ACCEPTED` as one-half, `MISSED` or `WAIVED` as zero, and any other state as one. The **final** variant is pinned to `fulfillment_score` at the terminal transition (or at the close-exhibition auto-MISS). For `FULFILLED` the final value is one; for `MAKE_GOOD_ACCEPTED` it is one-half; for `WAIVED` it is zero; for `MISSED` it starts at one-half and decays by one-tenth for each full twenty-four hours past `deadline` (compute the elapsed hours past `deadline` at the moment of the terminal transition, clamp to zero or above, take the integer floor of that elapsed-hours value divided by twenty-four to obtain the number of completed late days, then take the larger of zero and one-half minus one-tenth times that number of completed late days). Both variants are kept to four decimal places using round-half-up. Because the two variants treat in-flight and missed states differently, values for the same entitlement at the same instant typically differ between the variants — the entitlement report returns the provisional shape while the exhibition is open and the final shape after it has closed.

The post-event entitlement report is therefore a computed projection over the exhibition's entitlement set, aggregating status counts, the live or pinned `fulfillment_score`, and total make-good credits owed.

## 4. Endpoint Definitions

Operations that create a new resource (an exhibition, hall, floor plan, booth, application, allocation, dock slot, safety inspection, work order, ticket, or entitlement) return `201 Created`. Operations that mutate an existing resource (state transitions, dispute resolution, scan-in/out, fulfill/miss/offer/accept/waive, clock advance, list reads, single-resource reads) return `200 OK`. Error responses use the codes catalogued in §5. Request bodies, response bodies, and the side-effects of each endpoint are described narratively in §3 and §2 — this table is the routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/_clock/advance` | Advance the server's logical clock to a supplied `to` instant (test-driving capability) | TestHarness |
| POST   | `/exhibitions` | Create a new exhibition in `DRAFT` | VenueAdmin |
| GET    | `/exhibitions/{id}` | Read a single exhibition | VenueAdmin, VenueOps, Exhibitor, GateOperator, ServiceProvider |
| POST   | `/exhibitions/{id}/open-intake` | Move exhibition from `DRAFT` to `INTAKE_OPEN` | VenueAdmin |
| POST   | `/exhibitions/{id}/publish-allocation` | Move exhibition to `ALLOCATION_PUBLISHED`; cascade `PROPOSED` allocations | VenueAdmin |
| POST   | `/exhibitions/{id}/start-setup` | Move exhibition to `SETUP` after objection window | VenueAdmin |
| POST   | `/exhibitions/{id}/open-doors` | Move exhibition to `OPEN` (requires `PRE_OPEN` pass) | VenueAdmin |
| POST   | `/exhibitions/{id}/close-doors` | Move exhibition to `TEARDOWN`; void issued tickets | VenueAdmin |
| POST   | `/exhibitions/{id}/close` | Move exhibition to terminal `CLOSED`; auto-MISS remaining entitlements | VenueAdmin |
| GET    | `/exhibitions/{id}/entitlement-report` | Computed sponsor entitlement report | VenueAdmin, Exhibitor |
| GET    | `/exhibitions/{id}/audit-log` | List audit log entries; supports `subject_kind` filter | VenueAdmin |
| GET    | `/exhibitions/{id}/occupancy` | Real-time occupancy snapshot | VenueAdmin, VenueOps, GateOperator |
| POST   | `/exhibitions/{id}/halls` | Create a hall under the exhibition | VenueAdmin |
| POST   | `/halls/{hall_id}/floor-plans` | Create a `DRAFT` floor plan version | VenueAdmin |
| POST   | `/halls/{hall_id}/floor-plans/{id}/activate` | Activate a floor plan; supersede prior active | VenueAdmin |
| POST   | `/halls/{hall_id}/booths` | Create a booth on the active plan | VenueAdmin |
| GET    | `/halls/{hall_id}/booths` | List booths in a hall; supports `status` filter, `limit`, `offset` | VenueAdmin, VenueOps, Exhibitor |
| GET    | `/booths/{id}` | Read a single booth | VenueAdmin, VenueOps, Exhibitor |
| POST   | `/exhibitions/{id}/applications` | Submit a new exhibitor application | Exhibitor |
| POST   | `/applications/{id}/submit` | Move application from `DRAFT` to `SUBMITTED` | Exhibitor |
| POST   | `/applications/{id}/start-review` | Move application to `UNDER_REVIEW` | VenueAdmin |
| POST   | `/applications/{id}/qualify` | Move application to `QUALIFIED` | VenueAdmin |
| POST   | `/applications/{id}/reject` | Move application to `REJECTED` with `rejection_reason` | VenueAdmin |
| POST   | `/applications/{id}/withdraw` | Move application to `WITHDRAWN` | Exhibitor |
| GET    | `/exhibitions/{id}/applications` | List applications; supports `status`, `sort_by`, `limit`, `offset` | VenueAdmin |
| POST   | `/allocations` | Create a `PROPOSED` allocation | VenueAdmin |
| POST   | `/allocations/{id}/object` | File an objection within the objection window | Exhibitor |
| POST   | `/allocations/{id}/confirm` | Confirm a published allocation | Exhibitor |
| POST   | `/allocations/{id}/start-relocation` | Start a relocation from `OBJECTED` | VenueAdmin |
| POST   | `/allocations/{id}/relocate` | Complete relocation to a new booth | VenueAdmin |
| POST   | `/allocations/{id}/revoke` | Revoke a published allocation | VenueAdmin |
| GET    | `/allocations/{id}` | Read a single allocation | VenueAdmin, Exhibitor |
| POST   | `/exhibitions/{id}/dock-slots` | Book a dock slot | Exhibitor |
| POST   | `/dock-slots/{id}/complete` | Move a slot to `COMPLETED` | VenueOps |
| POST   | `/dock-slots/{id}/cancel` | Move a slot to `CANCELLED` | Exhibitor |
| POST   | `/exhibitions/{id}/safety-inspections` | Record a safety inspection | VenueOps |
| POST   | `/work-orders` | Create a `DRAFT` work order | Exhibitor |
| POST   | `/work-orders/{id}/submit` | Submit a work order; pin billing | Exhibitor |
| POST   | `/work-orders/{id}/dispatch` | Dispatch a submitted work order | VenueOps |
| POST   | `/work-orders/{id}/confirm-execution` | Confirm on-site execution | ServiceProvider |
| POST   | `/work-orders/{id}/bill` | Bill an executed work order | VenueOps |
| POST   | `/work-orders/{id}/dispute` | Open a dispute on an executed work order | Exhibitor |
| POST   | `/work-orders/{id}/resolve` | Resolve a dispute with a `resolved_total_cents` concession | VenueOps |
| POST   | `/work-orders/{id}/cancel` | Cancel a draft work order | Exhibitor |
| POST   | `/exhibitions/{id}/tickets` | Issue a ticket; mint `qr_code` and pin price | VenueAdmin, VenueOps, Exhibitor |
| POST   | `/tickets/{id}/scan-in` | Scan a ticket in at the gate | GateOperator |
| POST   | `/tickets/{id}/scan-out` | Scan a ticket out at the gate | GateOperator |
| POST   | `/tickets/{id}/refund` | Refund an online-presale ticket before opening | VenueAdmin |
| POST   | `/tickets/{id}/void` | Void an issued ticket | VenueAdmin |
| POST   | `/exhibitions/{id}/entitlements` | Create a `PLANNED` sponsor entitlement | VenueAdmin |
| POST   | `/entitlements/{id}/start` | Move entitlement to `IN_PROGRESS` | VenueOps |
| POST   | `/entitlements/{id}/fulfill` | Fulfill an entitlement with `evidence_url` | VenueOps |
| POST   | `/entitlements/{id}/mark-missed` | Mark an entitlement missed | VenueAdmin |
| POST   | `/entitlements/{id}/offer-make-good` | Offer a make-good credit | VenueAdmin |
| POST   | `/entitlements/{id}/accept-make-good` | Accept a make-good offer | Exhibitor |
| POST   | `/entitlements/{id}/waive` | Waive a planned entitlement | Exhibitor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_POSTURE_BLOCKED` | 409 |
| `ERR_SAFETY_INSPECTION_MISSING` | 409 |
| `ERR_OVERNIGHT_PERMIT_REQUIRED` | 422 |
| `ERR_FIRE_SAFETY_CELL` | 422 |
| `ERR_UTILITY_CAPACITY_EXCEEDED` | 422 |
| `ERR_THEME_MISMATCH` | 422 |
| `ERR_OBJECTION_WINDOW_CLOSED` | 409 |
| `ERR_DOCK_SLOT_OVERLAP` | 409 |
| `ERR_RESOURCE_CONFLICT` | 409 |
| `ERR_CAPACITY_EXCEEDED` | 409 |
| `ERR_GROUP_INVALID` | 422 |
| `ERR_RELOCATION_TIER_MISMATCH` | 422 |
| `ERR_INVALID_INPUT` | 422 |
| `ERR_DISPUTE_RESOLUTION_INVALID` | 422 |
| `ERR_FLOOR_PLAN_LOCKED` | 409 |
| `ERR_BOOTH_ALREADY_ALLOCATED` | 409 |

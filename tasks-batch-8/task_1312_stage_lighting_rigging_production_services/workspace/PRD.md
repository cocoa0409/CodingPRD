# Stage Lighting, Rigging & Production Services API — Product Requirements Document

## 1. Introduction

A concert production vendor lives and dies by a chain of interlocking commitments: a lighting design becomes a rigging plot, the plot becomes a set of engineered hang points, the hang points drive equipment pulls, the equipment drives truck packs, and all of it is staffed by union crew whose hours convert into money under rules that change from venue to venue. When any link in that chain is rushed — a bay overloaded because two plots were never cross-checked, a crew call published inside the contractual lead window, a generator undersized because feeder loss was ignored — the failure surfaces on show day, when it is most expensive. This document specifies an API that manages that entire chain for a stage lighting, rigging, and production services company, from the first venue booking through post-event damage reconciliation and final settlement with the client.

The system covers design and plot development with structural load calculations, rigging point approval with independent engineering sign-off, equipment pull lists with warehouse prep scheduling, crew calls governed by per-venue union labor rules, load-in and load-out scheduling with truck pack weight enforcement, power distribution and rental generator planning, safety inspection and certification, and damage or loss reconciliation after the event. All resources are mounted under the `/api` prefix. A distinguishing property of the domain is that readiness is *derived*: a production may only advance toward load-in when the system itself can see an approved plot with approved points, an approved power plan, a fully staged pull list, and confirmed crew — and the system revokes that readiness automatically when the underlying facts change.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. A request missing either header, or presenting a role the system does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The declared roles are `PlatformAdmin`, `ProductionManager`, `RiggingSupervisor`, `StructuralEngineer`, `WarehouseChief`, `SafetyInspector`, `CrewChief`, and `ClientContact`. Each operation is restricted to a named set of roles (see §4); a request whose role is not listed for that operation — including a transition request whose `to` value belongs to a different role's transitions — is rejected with `ERR_FORBIDDEN` (HTTP 403).

For most roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. This applies individually to `PlatformAdmin`, `ProductionManager`, `RiggingSupervisor`, `StructuralEngineer`, `WarehouseChief`, `SafetyInspector`, and `ClientContact`: the server may record the identifier where a workflow writes it — for example `submitted_by_user_id` on a rigging point created by a `RiggingSupervisor`, `reviewed_by_user_id` on a point approved by a `StructuralEngineer`, `approved_by_user_id` on a plot approved by a `StructuralEngineer`, or `inspector_user_id` on an inspection begun by a `SafetyInspector` — but it never compares the header value to any entity's `id` for these roles. Segregation-of-duties and continuity checks for these roles compare the header against such recorded fields, not against resource identifiers.

`CrewChief` is the exception. When `X-User-Role` is `CrewChief`, `X-User-ID` is the `id` of the acting `Technician`; ownership checks on a crew assignment compare the assignment's `technician_id` field to `X-User-ID`. A `CrewChief` confirming an assignment or reporting hours on it must be the technician named by that assignment, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items and defaults to 0. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Several list endpoints accept optional filter query parameters in addition to `limit` and `offset`: productions may be filtered by `venue_id` and `status`; assets by `asset_class` and `status`; pull list entries by `status`; load schedules by `direction`; inspections by `inspection_type`; and damage reports by `status`.

### 2.4. Common Resource Properties and the Logical Clock

Every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` timestamp records creation as an ISO 8601 UTC value with three fractional digits (for example, `2026-08-01T09:15:30.123Z`). The `updated_at` timestamp follows the same format and is refreshed on any mutation of the resource. The `version` is a system-managed integer that increments by exactly 1 on every mutation, including mutations driven indirectly by cascades or by recomputation of a derived field.

All time-gated business rules in this document — deadlines, earliest-start gates, billing timestamps, depreciation ages — are evaluated against a server-maintained **logical clock**, never against wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time thereafter. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant; no other role may invoke it, and it is the only way time moves in a running server.

### 2.5. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and both are creation endpoints whose payload must carry the client's last-observed `version` of a parent resource.

Creating a lighting plot under a production requires the request to include `expected_production_version`, matching the production's current `version`. If the production's version has advanced since the client last read it — for example because another plot was created against it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read the production before drafting. This guard exists because approving a new plot supersedes the production's currently approved plot, so drafting from a stale production view is never safe.

Reserving a rigging point on a plot requires the request to include `expected_plot_version`, matching the plot's current `version`. Every point reservation mutates the plot — the recomputed `total_factored_load_kg` advances the plot's `version` — so a client holding a stale load picture is rejected with `ERR_STALE_VERSION` (HTTP 412) and must re-read the plot before adding more load. No endpoint other than these two creation operations accepts a version field.

### 2.6. Validation Pipeline and Error Ordering

Every write request is evaluated against a fixed pipeline of check categories, and a request that fails an earlier category reports that error without ever reaching a later one. The pipeline order is:

1. **Authentication** — presence of well-formed `X-User-ID` and `X-User-Role` headers with a recognized role (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is listed for the endpoint, and for transition requests the role owns the requested `to` transition (`ERR_FORBIDDEN`).
3. **Segregation of duties** — where applicable, the approver must not be the submitter (`ERR_SOD_VIOLATION`).
4. **Ownership and continuity** — identity-bound actions such as a `CrewChief` self-confirming, or an inspector passing an inspection they began (`ERR_NOT_RESOURCE_OWNER`).
5. **Request schema** — required fields present, enum members valid, numeric ranges respected, and every time window's end strictly after its start; productions additionally require `load_in_at` strictly before `show_at` strictly before `load_out_at`. Unique-attribute collisions on a technician's `union_card_no`, an asset's `asset_tag`, or a truck's `plate_no` are schema-category failures. All of these surface as `ERR_INVALID_REQUEST` (HTTP 400).
6. **Resource existence** — path and body identifiers resolve, validated left to right (`ERR_RESOURCE_NOT_FOUND`, HTTP 404).
7. **Terminal-state guard** — a transition attempted from a terminal state is rejected (`ERR_ALREADY_TERMINAL`, HTTP 409).
8. **Declared-transition and parent-state gates** — the requested `to` must be a declared transition from the entity's current state for this actor, and child-creation endpoints require their parent to be in the correct state (`ERR_INVALID_STATE`, HTTP 409).
9. **Optimistic concurrency** — the two OCC-guarded creations (`ERR_STALE_VERSION`, HTTP 412).
10. **Structural and capacity limits** — point overload, bay overload, generator capacity, house power, phase imbalance, and truck pack limits (HTTP 422 family).
11. **Uniqueness and booking constraints** — point label holds, venue double-booking, dock window conflicts, dock door validity, technician turnaround, classification mapping, duplicate damage reports, settlement uniqueness (HTTP 409/422).
12. **Temporal deadlines** — engineering submission lead time, crew call publish lead time, and the clock gates (HTTP 422).
13. **Referential prerequisites** — plot contents, plot submission state, version pins, readiness posture, asset availability, schedule authorization, headcount, open-item gates at close, inspection prerequisites, settlement state, unresolved damage (HTTP 409/422).
14. **Fiscal bounds** — valuation method legality, repair quote presence, dispute adjustment range, and finally the worked-hours range (HTTP 422).

Two orderings deserve emphasis because they surprise implementers. First, segregation of duties (category 3) is evaluated before ownership continuity (category 4), so a final-inspection pass attempted by an engineer who approved a point on the same production reports `ERR_SOD_VIOLATION` even if some other identity check would also fail. Second, the `worked_hours` range check sits in the fiscal category at the very end of the pipeline — it is evaluated after all state checks, so an hour-reporting request against an assignment in the wrong state reports its state error first, and only an assignment in a valid state can ever surface `ERR_HOURS_OUT_OF_RANGE`.

### 2.7. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers sequentially, left to right. The first identifier that does not resolve to an existing resource terminates the request with `ERR_RESOURCE_NOT_FOUND` (HTTP 404); later identifiers are never examined. A request targeting a rigging point under a non-existent plot therefore fails on the plot identifier before the point is ever considered, and the same discipline applies to body-supplied references such as a `truck_id` or `asset_id` once path identifiers have been validated.

### 2.8. Measurement, Money, and Rounding Discipline

All money in the system is integer cents. Per-line labor charges and per-report damage assessments are rounded half-up to whole cents at the moment each line is computed; equipment rental charges are rounded half-up to whole cents once per entry after summing per-day amounts. Settlement aggregates are pure integer arithmetic over already-rounded cent values and are never re-rounded.

Physical and electrical quantities follow fixed decimal contracts. `factored_load_kg` and `pack_weight_kg` are stored at 2 decimal places, rounded half-up. The rigging `utilization` ratio and the power plan's `max_phase_imbalance_pct` are stored at 4 decimal places, rounded half-up. `total_load_watts` and `required_kva` are stored at 2 decimal places, rounded half-up. `worked_hours` accepts at most 2 decimal places. Rounding method is always round half-up; no field uses banker's rounding or truncation.

### 2.9. Hierarchical Consistency, Derived State, and Cascades

The system maintains consistency between parents and children automatically. When a child mutation changes a derived value on a parent — a point reservation changing a plot's `total_factored_load_kg`, a check-out changing a schedule's `pack_weight_kg`, a charge changing a settlement's `damage_total_cents` — the parent's `updated_at` refreshes and its `version` increments by 1, exactly as if the parent had been written directly. When a child mutation invalidates a parent's current lifecycle state, the server transitions the parent itself: releasing an approved point can downgrade a production from `READY_FOR_LOADIN` back to `PLANNING`, and a failed inspection can pull a production from `SHOW_READY` back to `LOAD_IN`. Conversely, when a parent is cancelled, the cancellation cascades downward through every non-terminal child. These server-driven mutations do not require a client request on the affected resource, and each affected resource's `version` increments independently.

One derived value deserves special attention: each production carries a `posture` field — `BLOCKED`, `PARTIAL`, or `READY` — recomputed on every mutation of the production's plots, rigging points, power plans, pull list entries, or crew calls. The readiness rules are defined in §3.2; the principle here is that posture is never written by clients and is always current as of the last mutation.

## 3. Business Logic & Workflows

### 3.1. Registering the Shop: Venues, Technicians, Assets, and Trucks

Before any production can be planned, the vendor registers its operating environment. A `ProductionManager` registers each **venue** with its display `name` and its `union_ruleset` — `IATSE`, `TEAMSTERS`, or `NON_UNION` — which governs every crew call staffed at that venue. The structural parameters are `max_point_capacity_kg`, the greatest factored load any single rigging point may carry, and `bay_aggregate_limit_kg`, the greatest summed factored load permitted across all points sharing one structural bay; both must be positive. Electrical capacity arrives as `house_power_amps_per_phase`, the house service in amps per phase at the venue's 208-volt service, and logistics capacity as `dock_doors`, the number of loading dock doors (at least one). Five labor parameters carry defaults and may be omitted at registration: `min_call_hours` (default 4), the minimum hours billed per crew member per day; `ot1_threshold_hours` (default 8), the daily straight-time ceiling before time-and-a-half; `ot2_threshold_hours` (default 12), the daily ceiling before double time; `turnaround_min_hours` (default 8), the minimum rest gap between two call windows for the same technician; `crew_call_publish_lead_hours` (default 48), how far before call start a call must be published; and `engineering_submission_lead_hours` (default 72), how far before production load-in rigging points must reach engineering review.

Technicians are registered by a `ProductionManager` with a `full_name`, a globally unique `union_card_no`, a trade `classification` of `LIGHTING_TECH`, `RIGGER`, or `STAGEHAND`, and a positive `hourly_rate_cents` straight-time rate. Trucks are registered by the `WarehouseChief` with a globally unique `plate_no` and a positive `capacity_kg` legal payload.

Equipment assets are the `WarehouseChief`'s responsibility. Each asset carries a globally unique serialized `asset_tag`; an `asset_class` of `MOVING_LIGHT`, `LED_PANEL`, `TRUSS_12IN`, `CHAIN_MOTOR`, `DISTRO_BOX`, `CABLE_FEEDER`, `CONSOLE`, or `FOLLOWSPOT`; a positive pack `weight_kg`; an informational `power_draw_watts` nameplate draw that defaults to 0; a positive `daily_rate_cents` rental day rate; a positive `replacement_cost_cents` used as the damage valuation basis; and an `acquired_at` timestamp that anchors depreciation. A new asset begins its inventory lifecycle at `AVAILABLE`. From there the `WarehouseChief` may retire it (`AVAILABLE` → `RETIRED`), and a repaired asset may be returned to service (`DAMAGED` → `AVAILABLE`, the quality-control pass) or written off (`DAMAGED` → `RETIRED`). The intermediate inventory states `RESERVED`, `PREPPED`, and `DEPLOYED` are never set by hand — they are driven exclusively by pull-list cascades described in §3.6.

### 3.2. Booking a Production: Occupancy, Readiness, and the Lifecycle Spine

A `ProductionManager` books a **production** at a venue by supplying the hosting `venue_id`, a show `name`, and three timestamps that define the venue occupancy window: `load_in_at` (occupancy start, inclusive), `show_at`, and `load_out_at` (occupancy end, inclusive). The schema requires `load_in_at` strictly before `show_at` strictly before `load_out_at`. Beyond schema validity, the venue's calendar is exclusive: if the closed occupancy window of the new production intersects the closed occupancy window of any other non-`CANCELLED` production at the same venue, the booking is rejected with `ERR_VENUE_DOUBLE_BOOKED` (HTTP 409). Two productions that merely touch — one loading out exactly when another loads in — still intersect under the closed-interval rule, since both endpoints count.

A new production begins in `DRAFT` status with `posture` `BLOCKED`. The lifecycle spine is driven by the `ProductionManager`: `DRAFT` → `PLANNING` opens the planning surface (plots, points, pull lists, crew calls, power plans, load schedules, and inspections may only be created while the production is `PLANNING`, with the single exception that inspections may also be scheduled during `LOAD_IN`).

The gate into `READY_FOR_LOADIN` is the derived readiness posture, and advancing without it fails with `ERR_PRODUCTION_NOT_READY` (HTTP 409). A production's `posture` is `READY` only when all five of the following hold: (a) the production has a lighting plot in `APPROVED` status; (b) that approved plot carries at least one rigging point in `APPROVED` status, and every rigging point on it is either `APPROVED` or `RELEASED`; (c) the production has a power plan in `APPROVED` status; (d) no pull list entry of the production is still in `REQUESTED` or `RESERVED`; and (e) no crew call of the production is still in `DRAFT` or `PUBLISHED`. When condition (a) fails — no approved plot at all — the posture is `BLOCKED`; when (a) holds but any of (b) through (e) fails, the posture is `PARTIAL`. Posture is recomputed on every mutation of the production's plots, points, power plans, pull list entries, or crew calls.

From `READY_FOR_LOADIN`, the production may enter `LOAD_IN` only once the logical clock has reached `load_in_at`; an early attempt is rejected with `ERR_TOO_EARLY` (HTTP 422). The move from `LOAD_IN` to `SHOW_READY` is never made by hand — it fires automatically when a `FINAL` safety inspection passes (see §3.7). From `SHOW_READY`, marking the show complete requires the logical clock to have reached `show_at` (again `ERR_TOO_EARLY`), after which `SHOW_COMPLETE` → `LOAD_OUT` is ungated.

Closing the production — `LOAD_OUT` → `CLOSED` — is gated on two open-item checks, evaluated in order: first, every pull list entry of the production must have reached `RETURNED`, `DAMAGED`, `LOST`, or `CANCELLED`, otherwise the close is rejected with `ERR_OPEN_PULL_LIST` (HTTP 409); second, every load schedule of the production must be `COMPLETE` or `CANCELLED`, otherwise `ERR_OPEN_LOAD_SCHEDULE` (HTTP 409). The final step, `CLOSED` → `SETTLED`, is system-fired the moment the production's settlement reaches `PAID` or `RESOLVED` (see §3.9).

Cancellation is available from `DRAFT`, `PLANNING`, and `READY_FOR_LOADIN`, and it triggers a full teardown cascade: every crew call in `DRAFT`, `PUBLISHED`, or `CONFIRMED` moves to `CANCELLED`, and each cancelled call's assignments in `ASSIGNED`, `CONFIRMED`, or `WORKED` move to `CANCELLED`; every rigging point in `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED` moves to `RELEASED`, recomputing its plot's `total_factored_load_kg`; every pull list entry in `REQUESTED`, `RESERVED`, or `PREPPED` moves to `CANCELLED`, and each asset thereby freed (an asset in `RESERVED` or `PREPPED`) returns to `AVAILABLE`, immediately running the waitlist promotion scan of §3.6; every load schedule in `PLANNED`, `CONFIRMED`, or `AUTHORIZED` moves to `CANCELLED`; and every safety inspection in `SCHEDULED`, `IN_PROGRESS`, or `FAILED` moves to `CANCELLED`. Entities already in a terminal state are untouched by the cascade.

Readiness can also be revoked. If a child mutation — releasing an approved rigging point, or a failed final inspection while the production still counted as ready — recomputes the posture of a `READY_FOR_LOADIN` production to `PARTIAL` or `BLOCKED`, the system downgrades the production back to `PLANNING`, increments its `version`, and the production must re-earn readiness before load-in can begin.

### 3.3. Lighting Plots and the Rigging Engineering Loop

The lighting design workflow centers on the **lighting plot**, a revisioned document owned by a production. A `ProductionManager` creates a plot under a `PLANNING` production by supplying a `title` and the OCC token `expected_production_version` (§2.5); the server assigns a `revision` number, a per-production sequence starting at 1 that uniquely orders the production's plots. Every plot carries its owning `production_id`, and every rigging point carries the `plot_id` of the plot it hangs from, so clients can traverse from any child record back to its place in the production. Creating the plot is itself a mutation of the production and increments the production's `version` by 1 — which is exactly why a second client drafting from a stale read is caught by the OCC guard. A new plot begins in `DRAFT`.

A `RiggingSupervisor` then reserves **rigging points** on a `DRAFT` plot, one hang at a time. Each reservation names the venue's physical `point_label`, a non-negative `bay_index` grouping the point into a structural bay, a `hang_type` of `STRAIGHT`, `BRIDLE`, or `DEAD_HANG`, a non-negative `motor_count` (default 0), and a positive `deadweight_kg` static hung load, together with the OCC token `expected_plot_version`. The server records the reserving supervisor as `submitted_by_user_id`.

Every reservation computes the point's `factored_load_kg` immediately. The base load is the `deadweight_kg` multiplied by a dynamic factor that depends on the hang geometry: 1.10 for `STRAIGHT` hangs, 1.10 for `BRIDLE` hangs, and 1.00 for `DEAD_HANG`. To that base the system adds the self-weight of the chain motors — the `motor_count` multiplied by 20 kilograms per motor. For a `BRIDLE` hang, and only for a `BRIDLE` hang, the combined base-plus-motors figure is then multiplied by a 1.15 uncertainty factor; `STRAIGHT` and `DEAD_HANG` points stop at base plus motors. The result is rounded half-up to 2 decimal places and stored as `factored_load_kg`, and the point's `utilization` — the factored load divided by the venue's `max_point_capacity_kg` — is stored at 4 decimal places, rounded half-up. The point capacity check permits the factored load to equal the venue's per-point limit exactly; a factored load strictly greater than `max_point_capacity_kg` rejects the reservation with `ERR_POINT_OVERLOAD` (HTTP 422).

Labels are scarce physical resources. A `point_label` may not be reserved while it is held by any non-`RELEASED` point at the same venue whose production's closed occupancy window intersects the reserving production's; a collision is rejected with `ERR_POINT_ALREADY_RESERVED` (HTTP 409). Releasing a point frees its label for future windows. Each reservation also recomputes the plot's `total_factored_load_kg` — the sum of `factored_load_kg` over the plot's points in `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` status, with `RELEASED` points excluded — and because that derived field changes, the plot's `version` increments with every reservation, which is what invalidates other holders of `expected_plot_version`. On a reservation request, the OCC guard fires before the capacity check, which fires before the label-uniqueness check.

With at least one point in place, the `ProductionManager` submits the plot (`DRAFT` → `SUBMITTED`). Submission requires the production to be `PLANNING` (otherwise `ERR_INVALID_STATE`) and requires at least one rigging point in `RESERVED`, `UNDER_REVIEW`, or `APPROVED` status — submitting an empty plot is rejected with `ERR_EMPTY_PLOT` (HTTP 422). Any `rejection_reason` from a prior review loop is cleared at submission.

Points enter engineering individually. A `RiggingSupervisor` submits a `RESERVED` point for review (`RESERVED` → `UNDER_REVIEW`), which is gated on two preconditions: the logical clock must not have passed the engineering deadline — submission must occur at or before `load_in_at` minus the venue's `engineering_submission_lead_hours`, else `ERR_ENGINEERING_DEADLINE_PASSED` (HTTP 422) — and the point's plot must be `SUBMITTED` or `APPROVED`, else `ERR_PLOT_NOT_SUBMITTED` (HTTP 409). Entering review captures `plot_version_at_submission`, the plot's current `version`, pinning the point's review to that revision of the plot.

Engineering decisions belong to the `StructuralEngineer`. Approving a point (`UNDER_REVIEW` → `APPROVED`) enforces three checks, evaluated in order — segregation of duties first, so a self-approval surfaces `ERR_SOD_VIOLATION` (HTTP 403) rather than being masked by later checks; then the bay aggregate load; then the version pin. Segregation of duties requires the approver's `X-User-ID` to differ from the point's `submitted_by_user_id`. The bay aggregate check sums, for each `bay_index`, the per-point rounded `factored_load_kg` of every rigging point on the production's plots that are `SUBMITTED` or `APPROVED`, counting points in `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` status and excluding `RELEASED` points and points on `SUPERSEDED` plots; the bay's sum may equal the venue's `bay_aggregate_limit_kg` exactly, and a sum strictly greater rejects the approval with `ERR_BAY_OVERLOAD` (HTTP 422). Finally, the version pin requires the plot's current `version` to still equal `plot_version_at_submission`; any intervening mutation of the plot — another reservation, a submit, a release — rejects the approval with `ERR_STALE_PLOT_REVISION` (HTTP 409). A successful approval records the engineer as `reviewed_by_user_id` and recomputes the production's posture.

The engineer may instead reject the point (`UNDER_REVIEW` → `REJECTED`), and the supervisor may then revise it (`REJECTED` → `RESERVED`) by supplying new `deadweight_kg` and `motor_count` values; the revision recomputes `factored_load_kg` and `utilization`, re-applies the per-point capacity check with the same equality-passes rule (`ERR_POINT_OVERLOAD` on failure), and refreshes the plot's `total_factored_load_kg`. A supervisor may also release a point outright from `RESERVED`, `UNDER_REVIEW`, `REJECTED`, or `APPROVED`; every release recomputes the plot's `total_factored_load_kg` and frees the `point_label`. Releasing an `APPROVED` point additionally recomputes the production's posture, and if the production was `READY_FOR_LOADIN` and its posture drops below `READY`, the production is downgraded to `PLANNING` automatically.

Plot-level approval (`SUBMITTED` → `APPROVED`) rests with the `StructuralEngineer` and enforces the same bay aggregate rule across the plot's non-`RELEASED` points, with `ERR_BAY_OVERLOAD` on violation. Approval stamps `approved_by_user_id` with the engineer's `X-User-ID` and `approved_at` with the logical clock, then fires the supersede cascade: any other `APPROVED` plot of the same production moves to `SUPERSEDED`, and every rigging point on that superseded plot with status `RESERVED`, `UNDER_REVIEW`, `APPROVED`, or `REJECTED` moves to `RELEASED`, which recomputes the superseded plot's `total_factored_load_kg` to 0. The production's posture is then recomputed. An engineer may also return the plot to drafting (`SUBMITTED` → `DRAFT`) — a rejection that requires a `rejection_reason` in the payload, its absence rejected with `ERR_INVALID_REQUEST` — and the reason is stored on the plot until a later resubmission clears it.

### 3.4. Power Distribution Planning

Electrical design runs on the **power plan**, created by a `ProductionManager` while the production is `PLANNING`. The plan declares the connected load per phase — `phase_l1_watts`, `phase_l2_watts`, `phase_l3_watts`, each non-negative — the `feeder_length_m` cable run in meters, and a `generator_required` flag choosing between a rental generator and house power. Until the plan is first submitted, the computed fields `total_load_watts`, `required_kva`, `selected_generator_tier_kva`, and `max_phase_imbalance_pct` are null; `required_kva` and `selected_generator_tier_kva` remain null permanently on house-powered plans.

Submission (`DRAFT` → `SUBMITTED`, by the `ProductionManager`) runs the full sizing computation in a pinned evaluation order, because each stage feeds the next. First, the subtotal is the sum of the three phase wattages. Second, the feeder loss is the subtotal multiplied by 0.03 for every 100 meters of the run — precisely, the subtotal times 0.03 times the `feeder_length_m` divided by 100. Third, `total_load_watts` is the subtotal plus the feeder loss, stored at 2 decimal places, rounded half-up. Fourth, the supply branch. On the generator branch (`generator_required` true), `required_kva` is the loss-inclusive `total_load_watts` divided by the product of a 0.9 power factor, a 0.8 derating factor, and 1000 — stored at 2 decimal places, rounded half-up — and `selected_generator_tier_kva` is the smallest tier from the rental fleet's 45, 60, 100, 150, 200, 300, and 400 kVA tiers that is greater than or equal to the requirement; a requirement exceeding the largest 400 kVA tier fails submission with `ERR_GENERATOR_CAPACITY_EXCEEDED` (HTTP 422). On the house branch (`generator_required` false), each phase's wattage must not exceed the venue's `house_power_amps_per_phase` multiplied by 208 volts; any phase above that service limit fails with `ERR_HOUSE_POWER_OVERLOAD` (HTTP 422). Fifth, after the supply branch clears, the imbalance check: `max_phase_imbalance_pct` is the spread between the largest and smallest phase loads divided by the largest phase load, stored at 4 decimal places rounded half-up — defined as 0 when all three phases carry zero — and an imbalance strictly greater than 0.15 fails with `ERR_PHASE_IMBALANCE` (HTTP 422). Per the validation pipeline, the supply-branch capacity failures surface before the imbalance failure when both apply. The computed values persist only when every check passes; a failed submission leaves the plan in `DRAFT` with its computed fields untouched.

Electrical sign-off belongs to the `SafetyInspector`. Approving a plan (`SUBMITTED` → `APPROVED`) requires the production to still be `PLANNING` (otherwise `ERR_INVALID_STATE`), supersedes any other `APPROVED` power plan of the same production (moving it to `SUPERSEDED`), and recomputes the production's posture. Rejection moves the plan to `REJECTED`. The revision loop (`REJECTED` → `DRAFT`) lets the `ProductionManager` resupply the phase wattages, `feeder_length_m`, and `generator_required`; all computed fields reset to null until the next submission.

### 3.5. Crew Calls and Union Labor Accounting

Staffing begins with the **crew call**, created by a `ProductionManager` while the production is `PLANNING`. The call names a `department` — `LIGHTING`, `RIGGING`, or `STAGEHANDS` — a `call_start` and `call_end` window (end strictly after start), and a positive `required_headcount`. Calls begin in `DRAFT`.

Publishing a call (`DRAFT` → `PUBLISHED`) is deadline-gated: the logical clock must be at or before `call_start` minus the venue's `crew_call_publish_lead_hours`, or the publish is rejected with `ERR_CREW_CALL_LATE` (HTTP 422). Only published calls accept crew.

Assigning a technician to a `PUBLISHED` call creates a **crew assignment** in `ASSIGNED` status, carrying the `crew_call_id` and the `technician_id` from the payload. Two booking constraints apply, evaluated in this order. First, turnaround: for every other assignment of the same technician in `ASSIGNED`, `CONFIRMED`, or `WORKED` status, the rest gap between the two call windows must be at least the venue's `turnaround_min_hours` — a gap exactly equal to the minimum passes — and a tighter turnaround is rejected with `ERR_TECHNICIAN_TURNAROUND` (HTTP 409). Second, classification: the technician's trade must match the call's department mapping — `LIGHTING` calls take `LIGHTING_TECH`, `RIGGING` calls take `RIGGER`, and `STAGEHANDS` calls take `STAGEHAND` — and a mismatch is rejected with `ERR_CLASSIFICATION_MISMATCH` (HTTP 422).

Confirming an assignment (`ASSIGNED` → `CONFIRMED`) is identity-bound: a `CrewChief` confirms their own assignment, meaning `X-User-ID` must equal the assignment's `technician_id`, else `ERR_NOT_RESOURCE_OWNER`. Once the count of `CONFIRMED` assignments reaches the call's `required_headcount`, the `ProductionManager` may confirm the call itself (`PUBLISHED` → `CONFIRMED`); shortfalls are rejected with `ERR_CREW_HEADCOUNT_UNMET` (HTTP 409).

Hours flow in after the work. A `CONFIRMED` assignment advances to `WORKED` either by the owning `CrewChief` (same ownership rule) or by a `ProductionManager` entering hours on their behalf; both supply `worked_hours`, which must be greater than 0, at most 24, and expressed with no more than 2 decimal places, else `ERR_HOURS_OUT_OF_RANGE` (HTTP 422) — and per the pipeline, this range check runs after all state checks, so an hours report against a stale-state assignment reports the state error instead. Technicians who never appeared are marked `NO_SHOW` from `ASSIGNED` or `CONFIRMED` by the `ProductionManager`.

Completing the call (`CONFIRMED` → `COMPLETED`) requires every assignment to be in `WORKED`, `NO_SHOW`, or `CANCELLED` (otherwise `ERR_INVALID_STATE`) and requires the logical clock to have reached `call_end` (otherwise `ERR_TOO_EARLY`). Completion runs the labor computation for each `WORKED` assignment and stamps each one's `labor_charge_cents`, then moves each `WORKED` assignment to `RECONCILED`; the call's `labor_cost_cents` is the sum of those per-assignment charges. The computation is pinned: each assignment's charge is rounded half-up to whole cents *before* summation, and summing unrounded lines and rounding once is a different, forbidden order.

The per-assignment charge starts from billable hours — the greater of the technician's `worked_hours` and the venue's `min_call_hours`, so short shifts still bill the union minimum. What happens next depends on the venue's `union_ruleset`. Under the union variant (`IATSE` or `TEAMSTERS`), billable hours split into three tiers: straight-time hours are the smaller of the billable hours and the venue's `ot1_threshold_hours`; first-tier overtime hours are the hours beyond `ot1_threshold_hours` (never negative), capped at the span between `ot2_threshold_hours` and `ot1_threshold_hours`; and double-time hours are whatever remains beyond `ot2_threshold_hours` (never negative). An `IATSE` call adds a flat two-hour meal penalty to the paid-hours total whenever the technician's `worked_hours` exceeded six hours; `TEAMSTERS` calls omit the meal penalty. Paid hours equal the straight-time hours, plus one and a half times the first-tier overtime hours, plus twice the double-time hours, plus the meal penalty hours; the assignment's `labor_charge_cents` is the technician's `hourly_rate_cents` multiplied by those paid hours, rounded half-up to whole cents. Under the non-union variant (`NON_UNION`), straight time runs to a fixed ten hours, hours beyond ten are paid at one and a half times, there is no double-time tier and no meal penalty, and the charge is the same rate-times-paid-hours product rounded half-up to whole cents. `NO_SHOW` and `CANCELLED` assignments contribute nothing to the call's `labor_cost_cents`.

Cancelling a call from `DRAFT`, `PUBLISHED`, or `CONFIRMED` cascades to its assignments: every assignment in `ASSIGNED`, `CONFIRMED`, or `WORKED` moves to `CANCELLED`.

### 3.6. Pull Lists, Truck Packs, and Warehouse Fulfillment

Gear flows to the show through **pull list entries**. The `WarehouseChief` requests a serialized asset for a `PLANNING` production by supplying the `asset_id`; the entry begins in `REQUESTED`. An asset that is `RETIRED`, `LOST`, or `DAMAGED` cannot be pulled — the request fails with `ERR_ASSET_NOT_AVAILABLE` (HTTP 409) — while an asset that is merely busy is a different story: multiple `REQUESTED` entries may stack against the same asset, forming its waitlist.

Reserving an entry (`REQUESTED` → `RESERVED`) requires the asset to be `AVAILABLE` at that moment (else `ERR_ASSET_NOT_AVAILABLE`) and flips the asset to `RESERVED`. The waitlist makes reservation automatic where possible: whenever an asset returns to `AVAILABLE` from `RESERVED`, `PREPPED`, or `DEPLOYED` — that is, on an entry cancellation or a check-in — the system scans the waitlist, considering exactly the `REQUESTED` entries for that asset whose productions are in `PLANNING`. If the candidate set is empty, nothing happens; otherwise exactly one entry is promoted, the one with the earliest `created_at` (ascending, at three-fractional-digit precision, which is the final ordering key — the tie-break never reaches the `id`), moving the promoted entry to `RESERVED` and the asset back to `RESERVED`. Note that a quality-control pass returning a `DAMAGED` asset to service does not run this scan; promotion is tied to assets freed from active pulls.

Prepping (`RESERVED` → `PREPPED`) records the prep window — `prep_window_start` and `prep_window_end`, both required with the end strictly after the start (else `ERR_INVALID_REQUEST`) — and moves the asset to `PREPPED`.

Truck logistics are planned as **load schedules**. A `ProductionManager` plans a run for a `PLANNING` production by naming the `truck_id`, a `direction` of `LOAD_IN` or `LOAD_OUT`, a non-negative `dock_door_index`, and a half-open dock window from `window_start` (inclusive) to `window_end` (exclusive, strictly after start). The dock door must exist: a `dock_door_index` at or beyond the venue's `dock_doors` count is rejected with `ERR_DOCK_DOOR_INVALID` (HTTP 422) at planning time. Confirming the run (`PLANNED` → `CONFIRMED`) checks the dock calendar: no other run in `CONFIRMED` or `AUTHORIZED` status at the same venue and the same `dock_door_index` may have a half-open window intersecting this one — windows that merely touch endpoints are allowed — and a collision is rejected with `ERR_DOCK_WINDOW_CONFLICT` (HTTP 409). Authorizing the run (`CONFIRMED` → `AUTHORIZED`) matches the production's state to the direction: a `LOAD_IN` run requires the production to be `READY_FOR_LOADIN` or `LOAD_IN`, while a `LOAD_OUT` run requires `SHOW_COMPLETE` or `LOAD_OUT`; a mismatch is rejected with `ERR_SCHEDULE_NOT_AUTHORIZED` (HTTP 409). Authorized runs are closed out as `AUTHORIZED` → `COMPLETE`, and runs may be cancelled from `PLANNED` or `CONFIRMED`.

Check-out (`PREPPED` → `OUT`) is the moment gear meets truck. The payload must name the `load_schedule_id` of the run carrying the item (its absence is `ERR_INVALID_REQUEST`); the referenced run must be `AUTHORIZED` with direction `LOAD_IN` (else `ERR_SCHEDULE_NOT_AUTHORIZED`); and the truck must physically take the weight. The truck check recomputes the run's `pack_weight_kg` *including the new entry*: the sum of `weight_kg` over all entries checked out onto that schedule, uplifted by a 2 percent dunnage allowance, rounded half-up to 2 decimal places. A pack weight equal to the truck's `capacity_kg` passes; strictly greater rejects the check-out with `ERR_TRUCK_OVERLOAD` (HTTP 422). Following the validation pipeline, the capacity verdict surfaces ahead of the schedule-authorization verdict when both would fail. A successful check-out stamps `out_at` with the logical clock, moves the asset to `DEPLOYED`, and persists the schedule's recomputed `pack_weight_kg` (which is 0 before any check-out).

Check-in (`OUT` → `RETURNED`) stamps `returned_at` with the logical clock and runs rental billing for the entry. Billable days count every calendar date touched from the date of `out_at` through the date of `returned_at`, both endpoints inclusive, so a same-day return bills exactly one day. The pricing is tiered: each of the first three days bills at the asset's full `daily_rate_cents`; days four through seven bill at half the daily rate each; days eight and beyond bill at a quarter of the daily rate each. The `rental_charge_cents` is the sum of those per-day amounts, rounded half-up to whole cents once per entry. Check-in also returns the asset to `AVAILABLE`, which immediately runs the waitlist promotion scan — the promoted entry and the asset both move to `RESERVED`.

Individual entries may be cancelled from `REQUESTED` (a no-op for the asset) or from `RESERVED` (the asset returns to `AVAILABLE` and the waitlist scan runs). Entries still `PREPPED` cannot be cancelled individually; only the production-level cancel cascade of §3.2 frees them. The remaining exits from `OUT` — into `DAMAGED` or `LOST` — are driven by damage assessment, covered next in the lifecycle but told in §3.8.

### 3.7. Safety Inspection and Show Certification

Certification runs through **safety inspections**, scheduled by the `ProductionManager` while the production is `PLANNING` or `LOAD_IN`, with an `inspection_type` of `RIGGING`, `ELECTRICAL`, or `FINAL`. Each inspection starts `SCHEDULED` with `attempt_no` 1.

A `SafetyInspector` begins an inspection (`SCHEDULED` → `IN_PROGRESS`), which records them as `inspector_user_id` and enforces per-type gates. A `RIGGING` inspection requires every rigging point on the production's currently `APPROVED` plot to be `APPROVED`; otherwise the begin is rejected with `ERR_RIGGING_NOT_APPROVED` (HTTP 409). An `ELECTRICAL` inspection requires the production to have an `APPROVED` power plan; otherwise `ERR_POWER_PLAN_NOT_APPROVED` (HTTP 409). A `FINAL` inspection requires the production to be in `LOAD_IN` (otherwise `ERR_INVALID_STATE`) and, in addition, requires the production's latest-attempt `RIGGING` and `ELECTRICAL` inspections to both be `PASSED` — the "latest attempt" of a type being the inspection of that type with the highest `attempt_no` — otherwise `ERR_PREREQUISITE_INSPECTION_MISSING` (HTTP 409).

Passing an inspection (`IN_PROGRESS` → `PASSED`) is continuity-bound: the passer must be the inspector who began it, meaning `X-User-ID` must equal `inspector_user_id`, else `ERR_NOT_RESOURCE_OWNER`. Passing a `FINAL` inspection carries a second, segregation-of-duties gate that is evaluated first per the pipeline: the passer must differ from the `reviewed_by_user_id` of every rigging point on the production's currently `APPROVED` plot, so the engineer who approved the hang cannot certify the show — a violation is `ERR_SOD_VIOLATION`. A passing `FINAL` inspection fires the production's `LOAD_IN` → `SHOW_READY` transition automatically.

Failing an inspection (`IN_PROGRESS` → `FAILED`) requires the inspector's `findings` text in the payload (its absence is `ERR_INVALID_REQUEST`). If the production was `SHOW_READY` at the time, it is downgraded to `LOAD_IN`, and the production's posture is recomputed either way. Re-inspection is a loop, not a new document: the `ProductionManager` reschedules (`FAILED` → `SCHEDULED`), which increments `attempt_no` by 1 and clears both `inspector_user_id` and `findings` for the next attempt.

### 3.8. Damage and Loss Reconciliation

When gear comes back broken — or doesn't come back — the `WarehouseChief` files a **damage report** against the production, naming the `pull_list_entry_id` of the affected entry and a `report_type` of `DAMAGE` (repairable) or `LOSS` (unrecoverable). Filing requires the entry to still be `OUT` (otherwise `ERR_INVALID_STATE`), and at most one open report may exist per entry: a second filing while a `FILED` or `ASSESSED` report already exists for the same entry is rejected with `ERR_DUPLICATE_DAMAGE_REPORT` (HTTP 409). Reports begin in `FILED`.

Assessment (`FILED` → `ASSESSED`, by the `WarehouseChief`) chooses a `valuation_method` and is gated by two checks evaluated in order. A `LOSS` report accepts only `DEPRECIATED` valuation; assessing a loss as `REPAIR_QUOTE` is rejected with `ERR_VALUATION_METHOD_INVALID` (HTTP 422). Then, quote handling: `REPAIR_QUOTE` valuation requires a positive `repair_quote_cents` in the payload (its absence is `ERR_REPAIR_QUOTE_REQUIRED`, HTTP 422), while `DEPRECIATED` valuation forbids the field entirely (its presence is `ERR_INVALID_REQUEST`).

Valuation itself has two variants. Under `DEPRECIATED` — mandatory for `LOSS`, optional for `DAMAGE` — the asset's age is the number of full 365.25-day anniversaries elapsed between `acquired_at` and the logical clock; the depreciation factor is 1.00 reduced by 0.10 per full year of age, never falling below a 0.20 floor; and the `assessed_charge_cents` is the asset's `replacement_cost_cents` multiplied by that factor, rounded half-up to whole cents. Under `REPAIR_QUOTE` — available to `DAMAGE` reports only — the charge is the `repair_quote_cents` uplifted by 15 percent for diminution of value, rounded half-up to whole cents, independent of the asset's age.

Assessment has teeth beyond the charge. The entry leaves `OUT`: a `DAMAGE` report moves it to `DAMAGED`, a `LOSS` report moves it to `LOST`, and in both cases the entry's `returned_at` is set to the assessment clock time and its `rental_charge_cents` is computed with billing ending at that same moment, per the tiered day-rate rule of §3.6. The asset follows: to `DAMAGED` or to `LOST` respectively. A `DAMAGED` asset can later be QC-passed back to `AVAILABLE` or written off to `RETIRED` by the `WarehouseChief`; `LOST` is terminal for the asset.

Charging and waiving close the loop. Charging (`ASSESSED` → `CHARGED`, by the `WarehouseChief`) requires the production's settlement to exist and still be `DRAFT` (otherwise `ERR_SETTLEMENT_NOT_DRAFT`, HTTP 409); the report's `assessed_charge_cents` is debited into the settlement's `damage_total_cents`, its `grand_total_cents` is recomputed, and both the report's and the settlement's `version` increment. A `ProductionManager` may waive an `ASSESSED` report outright, or waive a `CHARGED` report — compensation after the fact — which again requires the settlement to be `DRAFT` (same `ERR_SETTLEMENT_NOT_DRAFT`) and credits the `assessed_charge_cents` back out of `damage_total_cents` with the grand total recomputed. Both waive paths land in `WAIVED`.

### 3.9. Settlement, Disputes, and Production Closure

The **settlement statement** is the production's final invoice, generated by the `ProductionManager` once the production is `CLOSED` (otherwise `ERR_INVALID_STATE`). Exactly one settlement may exist per production; a second generation attempt is rejected with `ERR_SETTLEMENT_EXISTS` (HTTP 409). Generation takes no request body.

The statement carries two families of totals. The live totals are `labor_total_cents` — the sum of `labor_cost_cents` over the production's `COMPLETED` crew calls — `equipment_total_cents` — the sum of `rental_charge_cents` over entries in `RETURNED`, `DAMAGED`, or `LOST` — and `damage_total_cents`, which counts `assessed_charge_cents` over `CHARGED` reports only and moves with every subsequent charge or waive while the settlement is `DRAFT`. The `grand_total_cents` is the sum of the three. All settlement arithmetic is integer-cent addition over already-rounded inputs; nothing is re-rounded at the aggregate level. Alongside the live totals, generation freezes a forward-looking snapshot: `provisional_damage_cents` captures the sum of `assessed_charge_cents` over reports then in `ASSESSED` or `CHARGED` at creation time, and `provisional_grand_total_cents` is `labor_total_cents` plus `equipment_total_cents` plus that provisional damage figure. Neither provisional field is ever recomputed.

Issuing the statement (`DRAFT` → `ISSUED`) requires every damage report of the production to be in `CHARGED` or `WAIVED` — open reports block issuance with `ERR_UNRESOLVED_DAMAGE_REPORTS` (HTTP 409) — and recomputes `damage_total_cents` over `CHARGED` reports and the `grand_total_cents` as the final variant, after which the totals stop moving; the provisional fields stay frozen regardless.

The client then has their say. A `ClientContact` disputes an issued statement (`ISSUED` → `DISPUTED`), and the `ProductionManager` resolves the dispute (`DISPUTED` → `RESOLVED`) by supplying a signed `dispute_adjustment_cents`, a field that defaults to 0 and stays there on a statement that is paid without dispute. The adjustment's magnitude may not exceed the settlement's `damage_total_cents` at resolve time — a larger swing is rejected with `ERR_ADJUSTMENT_OUT_OF_RANGE` (HTTP 422) — and a valid adjustment is added into `grand_total_cents`. Alternatively, an undisputed statement is marked paid (`ISSUED` → `PAID`). Either terminal outcome — `RESOLVED` or `PAID` — fires the production's own final transition, `CLOSED` → `SETTLED`, closing the lifecycle that began with the venue booking.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including all lifecycle transitions and the damage assessment — return `200 OK`. Request payloads, computed fields, cascades, and error triggers are defined by the workflows in §3 and the principles in §2; the table below is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/venues` | Register a venue with structural, power, dock, and union-rule parameters | ProductionManager |
| GET | `/api/venues` | List venues (paginated) | All roles |
| GET | `/api/venues/{id}` | Fetch one venue | All roles |
| GET | `/api/venues/{id}/productions` | List productions hosted at this venue | All roles |
| POST | `/api/technicians` | Register a technician | ProductionManager |
| GET | `/api/technicians/{id}` | Fetch one technician | All roles |
| GET | `/api/technicians/{id}/crew-assignments` | List a technician's crew assignments across all calls | All roles |
| POST | `/api/productions` | Create a production at a venue; closed-interval occupancy check applies | ProductionManager |
| GET | `/api/productions` | List productions, optionally filtered by `venue_id` and `status` | All roles |
| GET | `/api/productions/{id}` | Fetch one production including derived `posture` | All roles |
| POST | `/api/productions/{id}/transition` | Drive the production lifecycle; valid `to` values and gates per §3.2 | ProductionManager |
| POST | `/api/productions/{id}/plots` | Create a lighting plot (revision assigned server-side); OCC via `expected_production_version` | ProductionManager |
| GET | `/api/productions/{id}/plots` | List plots of a production | All roles |
| GET | `/api/plots/{id}` | Fetch one plot including `total_factored_load_kg` | All roles |
| POST | `/api/plots/{id}/transition` | Plot review lifecycle: submit, approve, or reject with `rejection_reason` | ProductionManager, StructuralEngineer |
| POST | `/api/plots/{id}/rigging-points` | Reserve a rigging point on a `DRAFT` plot; computes factored load; OCC via `expected_plot_version` | RiggingSupervisor |
| GET | `/api/plots/{id}/rigging-points` | List points on a plot | All roles |
| GET | `/api/rigging-points/{id}` | Fetch one rigging point | All roles |
| POST | `/api/rigging-points/{id}/transition` | Point lifecycle: submit to engineering, revise with `deadweight_kg`/`motor_count`, release, approve, reject | RiggingSupervisor, StructuralEngineer |
| POST | `/api/assets` | Register an equipment asset | WarehouseChief |
| GET | `/api/assets` | List assets, optionally filtered by `asset_class` and `status` | All roles |
| GET | `/api/assets/{id}` | Fetch one asset | All roles |
| GET | `/api/assets/{id}/pull-list-entries` | List pull list entries referencing this asset | All roles |
| POST | `/api/assets/{id}/transition` | Asset manual lifecycle: retire, or QC-pass from `DAMAGED` to `AVAILABLE` | WarehouseChief |
| POST | `/api/productions/{id}/pull-list-entries` | Request an asset for a production; multiple `REQUESTED` entries per asset form the waitlist | WarehouseChief |
| GET | `/api/productions/{id}/pull-list-entries` | List a production's pull list, optionally filtered by `status` | All roles |
| GET | `/api/pull-list-entries/{id}` | Fetch one pull list entry | All roles |
| GET | `/api/pull-list-entries/{id}/damage-reports` | List damage reports filed against this entry | All roles |
| POST | `/api/pull-list-entries/{id}/transition` | Pull lifecycle: reserve, prep, check out, return, cancel per §3.6 | WarehouseChief |
| POST | `/api/productions/{id}/crew-calls` | Create a crew call | ProductionManager |
| GET | `/api/productions/{id}/crew-calls` | List a production's crew calls | All roles |
| GET | `/api/crew-calls/{id}` | Fetch one crew call including `labor_cost_cents` once completed | All roles |
| POST | `/api/crew-calls/{id}/transition` | Call lifecycle: publish, confirm, complete, cancel per §3.5 | ProductionManager |
| POST | `/api/crew-calls/{id}/assignments` | Assign a technician to a `PUBLISHED` call; turnaround and classification enforced | ProductionManager |
| GET | `/api/crew-calls/{id}/assignments` | List assignments of a call | All roles |
| GET | `/api/crew-assignments/{id}` | Fetch one assignment | All roles |
| POST | `/api/crew-assignments/{id}/transition` | Assignment lifecycle: confirm, report `worked_hours`, mark no-show per §3.5 | ProductionManager, CrewChief |
| POST | `/api/productions/{id}/power-plans` | Create a power plan | ProductionManager |
| GET | `/api/productions/{id}/power-plans` | List a production's power plans | All roles |
| GET | `/api/power-plans/{id}` | Fetch one power plan including computed sizing fields | All roles |
| POST | `/api/power-plans/{id}/transition` | Plan lifecycle: submit (runs sizing), approve, reject, revise per §3.4 | ProductionManager, SafetyInspector |
| POST | `/api/trucks` | Register a truck | WarehouseChief |
| GET | `/api/trucks/{id}` | Fetch one truck | All roles |
| GET | `/api/trucks/{id}/load-schedules` | List runs assigned to this truck | All roles |
| POST | `/api/productions/{id}/load-schedules` | Plan a dock run; dock door validity checked here, window conflict at confirmation | ProductionManager |
| GET | `/api/productions/{id}/load-schedules` | List a production's load schedules, optionally filtered by `direction` | All roles |
| GET | `/api/load-schedules/{id}` | Fetch one load schedule including `pack_weight_kg` | All roles |
| GET | `/api/load-schedules/{id}/pull-list-entries` | List pull list entries checked out onto this run | All roles |
| POST | `/api/load-schedules/{id}/transition` | Run lifecycle: confirm, authorize, complete, cancel per §3.6 | ProductionManager |
| POST | `/api/productions/{id}/inspections` | Schedule a safety inspection (`PLANNING` or `LOAD_IN` productions) | ProductionManager |
| GET | `/api/productions/{id}/inspections` | List a production's inspections, optionally filtered by `inspection_type` | All roles |
| GET | `/api/inspections/{id}` | Fetch one inspection | All roles |
| POST | `/api/inspections/{id}/transition` | Inspection lifecycle: begin, pass, fail with `findings`, reschedule per §3.7 | ProductionManager, SafetyInspector |
| POST | `/api/productions/{id}/damage-reports` | File a damage/loss report against an `OUT` pull list entry | WarehouseChief |
| GET | `/api/productions/{id}/damage-reports` | List a production's damage reports, optionally filtered by `status` | All roles |
| GET | `/api/damage-reports/{id}` | Fetch one damage report | All roles |
| POST | `/api/damage-reports/{id}/assess` | Assess a `FILED` report: valuation, billing cutoff, entry and asset cascade | WarehouseChief |
| POST | `/api/damage-reports/{id}/transition` | Claim lifecycle: charge (debits the `DRAFT` settlement) or waive per §3.8 | ProductionManager, WarehouseChief |
| POST | `/api/productions/{id}/settlement` | Generate the production's settlement (production must be `CLOSED`; one per production) | ProductionManager |
| GET | `/api/productions/{id}/settlement` | Fetch the production's settlement (array of length 0 or 1) | All roles |
| GET | `/api/settlements/{id}` | Fetch one settlement | All roles |
| POST | `/api/settlements/{id}/transition` | Settlement lifecycle: issue, dispute, resolve with `dispute_adjustment_cents`, mark paid per §3.9 | ProductionManager, ClientContact |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock to a supplied `to_iso8601` instant | PlatformAdmin |

## 5. Error Code Catalogue

The table below enumerates every error identifier and its HTTP status. Trigger conditions are defined in the narrative of §2 and §3 alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_RESOURCE_NOT_FOUND` | 404 Not Found |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_POINT_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_BAY_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_GENERATOR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_HOUSE_POWER_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_PHASE_IMBALANCE` | 422 Unprocessable Entity |
| `ERR_TRUCK_OVERLOAD` | 422 Unprocessable Entity |
| `ERR_POINT_ALREADY_RESERVED` | 409 Conflict |
| `ERR_VENUE_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_DOCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DOCK_DOOR_INVALID` | 422 Unprocessable Entity |
| `ERR_TECHNICIAN_TURNAROUND` | 409 Conflict |
| `ERR_CLASSIFICATION_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_DAMAGE_REPORT` | 409 Conflict |
| `ERR_SETTLEMENT_EXISTS` | 409 Conflict |
| `ERR_ENGINEERING_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_CREW_CALL_LATE` | 422 Unprocessable Entity |
| `ERR_TOO_EARLY` | 422 Unprocessable Entity |
| `ERR_EMPTY_PLOT` | 422 Unprocessable Entity |
| `ERR_PLOT_NOT_SUBMITTED` | 409 Conflict |
| `ERR_STALE_PLOT_REVISION` | 409 Conflict |
| `ERR_PRODUCTION_NOT_READY` | 409 Conflict |
| `ERR_ASSET_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SCHEDULE_NOT_AUTHORIZED` | 409 Conflict |
| `ERR_CREW_HEADCOUNT_UNMET` | 409 Conflict |
| `ERR_OPEN_PULL_LIST` | 409 Conflict |
| `ERR_OPEN_LOAD_SCHEDULE` | 409 Conflict |
| `ERR_PREREQUISITE_INSPECTION_MISSING` | 409 Conflict |
| `ERR_RIGGING_NOT_APPROVED` | 409 Conflict |
| `ERR_POWER_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_SETTLEMENT_NOT_DRAFT` | 409 Conflict |
| `ERR_UNRESOLVED_DAMAGE_REPORTS` | 409 Conflict |
| `ERR_VALUATION_METHOD_INVALID` | 422 Unprocessable Entity |
| `ERR_REPAIR_QUOTE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ADJUSTMENT_OUT_OF_RANGE` | 422 Unprocessable Entity |
| `ERR_HOURS_OUT_OF_RANGE` | 422 Unprocessable Entity |

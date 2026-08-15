# Shipyard Repair & Drydock API — Product Requirements Document

## 1. Introduction

A Gulf Coast repair yard lives and dies by its dock windows. Every redelivery commitment is a chain of dependencies: steel must be cropped before coatings can be applied, the class surveyor must attend before the dock can be flooded, and every calendar day of slippage beyond the contractual redelivery date accrues liquidated damages that can reach a double-digit percentage of the contract price. This document specifies the Shipyard Repair & Drydock API, the system of record for that business — from berth capacity and vessel dimensions, through bid pricing and contract award, to growth-work adjudication, regulatory surveys, environmental permits, delivery accounting, and warranty re-work.

Seven operator roles across the yard, the vessel owner, and external trade firms share the surface, and the system is deliberately strict about the order in which their decisions interlock. Commercial terms freeze at award; growth work discovered after docking is priced, gated by segregation of duties, and — above a defined threshold — countersigned by the owner before it enters the schedule. Safety and environmental controls, hot-work permits in particular, are first-class gates on work execution rather than paperwork afterthoughts. All scheduling consequences — the critical path, the forecast redelivery, and the provisional liquidated-damages accrual — are recomputed eagerly as the work graph mutates, so every reader of a project sees the current commercial exposure at a glance.

## 2. Global Specifications & System-Wide Principles

This section fixes the contracts that apply uniformly across the API. All endpoints described in §4 are mounted under the `/v1` path prefix.

### 2.1. User and Role-Based Access Control

Every request carries two mandatory HTTP headers: `X-User-ID` identifying the acting user and `X-User-Role` declaring the capacity in which they act. Seven roles are recognized: `YardAdmin`, `ProjectManager`, `CommercialApprover`, `ShipownerRep`, `ClassSurveyor`, `EnvironmentalOfficer`, and `Subcontractor`. A request missing either header, carrying either header blank (empty or all whitespace), or carrying a role string outside this set is rejected with `ERR_UNAUTHENTICATED`. Beyond authentication, every endpoint lists the roles permitted to invoke it (see §4); an authenticated caller whose role is not listed is rejected with `ERR_FORBIDDEN`.

For six of the seven roles — `YardAdmin`, `ProjectManager`, `CommercialApprover`, `ShipownerRep`, `ClassSurveyor`, and `EnvironmentalOfficer` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it on resources (as the `proposed_by_user_id` of a change order, the `surveyor_user_id` of a survey, or the `filed_by_user_id` of a warranty claim) and later compare it for authorization, but it is never the `id` of a stored record. When `X-User-Role` is `Subcontractor`, `X-User-ID` is the `id` of the acting `Subcontractor` entity; ownership checks on any work item that references a subcontractor compare the item's `subcontractor_id` field against `X-User-ID`.

Role intent, in brief. A `YardAdmin` administers the yard's books — docks, subcontractor registry, and the logical clock. A `ProjectManager` owns the repair-project lifecycle: vessels, projects, bookings, work specification, growth-work proposals, and warranty disposition. A `CommercialApprover` awards contracts and adjudicates change orders, and may never approve a change order that same user proposed. A `ShipownerRep` countersigns large change orders and files warranty claims, with identity compared against the owning vessel's recorded `owner_user_id`. A `ClassSurveyor` schedules and records regulatory surveys against their own calendar. An `EnvironmentalOfficer` applies for, grants, suspends, and closes environmental permits. A `Subcontractor` may start and complete only work items assigned to it.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server-side logical clock of §2.5 rather than the host's wall clock.
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
- Requests addressed to undefined paths are rejected with `ERR_NOT_FOUND`; a defined path invoked with an unsupported method yields `ERR_METHOD_NOT_ALLOWED` (HTTP 405), and an unexpected server failure yields `ERR_INTERNAL` (HTTP 500), both in the same envelope.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter skips that many items from the front of the result set and defaults to 0. A `limit` above 100 is silently capped at 100 rather than rejected, while a non-integer `limit`, a `limit` below 1, a non-integer `offset`, or a negative `offset` is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with resources stamped within the same logical instant kept in creation order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when `offset` plus the number of items in the returned page is less than `total_count`.

### 2.4. Common Resource Properties

Every resource in the system — dock berths, vessels, subcontractors, repair projects, dock reservations, work items, change orders, surveys, permits, and warranty claims — carries a standard set of system-managed properties:

- `id` (string): a unique server-minted identifier formatted as a UUID, with no type prefix of any kind.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created, read from the server-side logical clock of §2.5 rather than the host's wall clock.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource and likewise read from the server-side logical clock of §2.5.
- `version` (integer): a system-managed counter that increments by exactly one on every mutation of the resource, including the automatic transitions and derived-field recomputations described in §3 wherever this document states that an increment occurs. A derived-field recomputation that leaves every stored roll-up value unchanged is not a mutation: it refreshes neither `updated_at` nor `version`. A single request that changes several fields of one resource still increments that resource's `version` by exactly one. Lifecycle timestamps stamped from the logical clock (for example `actual_dock_in_utc`, `completed_at_utc`, `delivered_at_utc`, `forecast_delivery_utc`) render the same instant in canonical UTC form, omitting the fractional part for whole-second instants.

The API surface is flat: every resource is addressed by its own `id`, and relationships between resources are expressed through identifiers carried in payloads (for example, a work item's `project_id`) rather than through nested paths.

### 2.5. The Logical Clock

All time-dependent behaviour in the system — window checks, permit validity, warranty expiry, delivery dates, turnaround buffers — is evaluated against a server-side logical clock, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to the host's wall clock. A `YardAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and returns the new logical time as `current_utc`, echoed in the exact form supplied.

Setting the clock is not inert: each advance runs two sweeps. First, any permit still in `APPLIED`, `GRANTED`, or `SUSPENDED` whose `valid_to` lies strictly before the new logical time transitions to `EXPIRED`, incrementing the permit's `version` by one. Second, any repair project still in `DELIVERED` whose `warranty_end_utc` lies strictly before the new logical time transitions to the terminal `CLOSED` state, incrementing the project's `version` by one.

### 2.6. Money, Cents, and Rounding Discipline

All monetary amounts in the system are integers denominated in cents. Rounding is pinned to the line level: every priced line (a work item's `line_total_cents`, a change order's `proposed_cost_cents`, a reservation's `dockage_fee_cents`) is rounded half-up to a whole cent individually, and every total is a sum of already-rounded line values. Summing unrounded products and rounding once at the end is a rejected alternative, because it can yield a different cent. Percentage-derived amounts — the fifteen percent materials markup and the liquidated-damages cap — are likewise rounded half-up to a whole cent. Damages arithmetic on dates uses whole calendar days; scheduling arithmetic uses whole days.

### 2.7. Dock Occupancy and Interval Semantics

Three interval disciplines coexist in the system, and confusing them is the classic source of off-by-one disputes at the dock edge. Dock reservations occupy a half-open window: occupation runs from `start_utc` (inclusive) up to but not including `end_utc`, and for conflict purposes the dock is additionally held for a twelve-hour turnaround buffer after `end_utc` — time for undocking, cleaning, and block reset that is never chargeable to the customer. Because the occupied window is half-open, a booking whose start falls exactly twelve hours after a prior booking's end touches without overlapping and is permitted. Surveys, by contrast, are booked under closed-interval semantics: touching endpoints count as overlap. Permits likewise use closed, day-granular validity windows that include both the `valid_from` and the `valid_to` instants.

### 2.8. Optimistic Concurrency Control on the Project

Two creation endpoints carry optimistic concurrency control on the parent repair project: proposing a change order and booking a dock reservation both require the client to supply `expected_project_version`, carrying the `version` of the repair project as last observed by the client. If the project's current `version` differs from the supplied value — because another writer has since submitted the bid, awarded the contract, booked a window, proposed a change order, or otherwise mutated the project — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is created. Both of these creations themselves increment the parent project's `version` by one, which is exactly what makes a second write against an unrefreshed copy fail: the client must re-read the project and resubmit with the current version. No other endpoint takes a version field.

### 2.9. Validation Order

Every request is validated against an ordered ladder of rungs; a request failing any rung is rejected without evaluating later rungs, while checks sharing a rung carry no relative order among themselves. The ladder, from first to last:

1. Presence of `X-User-ID` and `X-User-Role`, and membership of the role in the declared set — failures yield `ERR_UNAUTHENTICATED`.
2. The acting role is listed among the endpoint's permitted roles — failures yield `ERR_FORBIDDEN`.
3. Request well-formedness: required fields present, types correct, enum values valid, and a non-empty `reason` or `description` where one is required — failures yield `ERR_INVALID_REQUEST`.
4. Identifier resolution: path identifiers first, resolved left to right, then identifiers referenced in the body (`vessel_id`, `dock_id`, `project_id`, `work_item_id`, `subcontractor_id`, and each element of `depends_on_ids`) — the first miss yields `ERR_NOT_FOUND`.
5. State preconditions: the generic check that the requested transition is defined from the target's current state (`ERR_INVALID_STATE`), together with the specific state guards `ERR_PROJECT_NOT_CONTRACTED`, `ERR_PROJECT_NOT_IN_DOCK`, `ERR_CHANGE_ORDER_NOT_REVIEWABLE`, `ERR_OWNER_APPROVAL_NOT_REQUIRED`, and the stale-version rejection `ERR_STALE_VERSION`.
6. Identity-scoped authorization: segregation of duties (`ERR_SEGREGATION_OF_DUTIES`) and ownership checks (`ERR_OWNERSHIP_MISMATCH`).
7. Business safety: the hot-work permit gate (`ERR_HOT_WORK_PERMIT_REQUIRED`).
8. Business constraints: vessel fit (`ERR_VESSEL_EXCEEDS_DOCK_LIMITS`), reservation and permit window validity (`ERR_RESERVATION_WINDOW_INVALID`, `ERR_PERMIT_WINDOW_INVALID`), survey window validity (reported as `ERR_INVALID_REQUEST`), mode-conditional pricing inputs (`ERR_PRICING_INPUT_INVALID`), dependency acyclicity (`ERR_DEPENDENCY_CYCLE`), trade matching (`ERR_TRADE_MISMATCH`), bid content (`ERR_BID_EMPTY`), and survey-result discipline (`ERR_SURVEY_RESULT_INVALID`).
9. Temporal conflicts: dock-slot intersection (`ERR_DOCK_SLOT_CONFLICT`), surveyor schedule overlap (`ERR_SURVEYOR_SCHEDULE_CONFLICT`), hot-work grant exclusivity (`ERR_HOT_WORK_PERMIT_CONFLICT`), and warranty-window filing (`ERR_WARRANTY_EXPIRED`).
10. Referential business checks: dependency completion (`ERR_DEPENDENCY_NOT_MET`) and work-item membership (`ERR_WORK_ITEM_NOT_IN_PROJECT`).
11. Fiscal checks: the change budget (`ERR_CHANGE_BUDGET_EXCEEDED`) and subcontractor capacity (`ERR_SUBCONTRACTOR_CAPACITY`).

## 3. Business Logic & Workflows

### 3.1. Registering the Yard's Books: Docks, Vessels, and Trade Firms

Docks come first. A `YardAdmin` registers each drydock and repair berth under a human-readable `name` (for example, "Drydock 2") together with three dimensional ceilings — `max_length_m` for length overall, `max_beam_m` for beam, and `max_depth_m` for draft over the blocks, all three stored as supplied with no positivity constraint — and a `daily_rate_cents` of zero or more, the base dockage rate per booked night before the length multiplier is applied. The three ceilings drive the inclusive fit check enforced at booking time (§3.3).

Vessels are registered by a `ProjectManager`, who records the vessel's `name`, her `imo_number` — unique across every vessel the yard has registered, a duplicate rejected with `ERR_INVALID_REQUEST` — and her `length_m`, `beam_m`, and `draft_m` in metres, likewise stored as supplied without positivity validation, the three dimensions the dock fit check consumes. Registration also records the `owner_user_id`: the opaque operator identifier of the `ShipownerRep` who speaks for the vessel. The system later compares that value against `X-User-ID` when an owner countersigns a large change order (§3.5) or files a warranty claim (§3.8).

Trade firms are registered by a `YardAdmin` with a company `name`, the array of `trade_codes` the firm is certified for (for example `HULL_STEEL`, `PIPING`, `COATINGS`, `ELECTRICAL`, or `MACHINERY`; the array may be empty), and a reference `day_rate_cents` of zero or more that is advisory only and never enters any calculation. Certification matters operationally: a work item may only be assigned to a firm whose `trade_codes` contain the item's `trade_code`, a rule enforced when the assignment is made (§3.4). Reading any dock, vessel, or subcontractor record is open to every role.

### 3.2. Project Setup and the Base Specification

A repair engagement begins when a `ProjectManager` opens a project against a registered vessel and a registered dock, supplying the `vessel_id`, the `dock_id`, and the `contract_delivery_date` as an ISO 8601 calendar date — the redelivery commitment against which liquidated damages later accrue per calendar day. Three optional commercial parameters complete the setup: `warranty_days`, the length of the post-delivery warranty window in calendar days, which must be positive and defaults to 90; `change_budget_cents`, a ceiling on the sum of approved change-order costs, which when omitted admits change orders of any size; and `required_survey_types`, the list of survey kinds that must each be passed before work can be called complete, where an omitted or empty list means there is no survey gate at all and an entry outside the four declared survey types of §3.6 is rejected with `ERR_INVALID_REQUEST`. The project is born in `DRAFT`, with its commercial and scheduling fields — `awarded_price_cents`, `contracted_price_cents`, `ld_daily_rate_cents`, `actual_dock_in_utc`, `forecast_delivery_utc`, `liquidated_damages_cents`, `delivered_at_utc`, `warranty_end_utc` — null until the lifecycle fills them in, `critical_path_days` at zero, and `provisional_ld_cents` at zero. Projects can be listed and filtered by `vessel_id`, `dock_id`, or `status`.

While the project is in `DRAFT` or `BID_SUBMITTED`, the `ProjectManager` builds the base specification by adding work lines. Each line names its `project_id`, a free-text `description`, the `trade_code` of the trade that will perform it, a planned `duration_days` of at least one whole day, and a `pricing_mode` of either `LUMP_SUM` or `TIME_AND_MATERIALS`. Lines created this way carry an `origin_kind` of `BASE_SPEC` and land in `PLANNED`; a line's `completed_at_utc` stays null until the line completes.

The pricing mode dictates which pricing inputs are required and how the line's `line_total_cents` is computed. A `LUMP_SUM` line must supply a `quantity` greater than zero — quantities may carry fractional values, and no decimal-precision limit is enforced — together with a `unit_price_cents`; its priced value is the quantity multiplied by the unit price, rounded half-up to a whole cent. A `TIME_AND_MATERIALS` line must supply `estimated_hours` greater than zero and an `hourly_rate_cents` of zero or more, and may supply a `materials_cost_cents` of zero or more that defaults to zero when omitted; its priced value is the estimated hours multiplied by the hourly rate, rounded half-up to a whole cent, plus the materials subtotal increased by a fifteen percent markup and itself rounded half-up to a whole cent. Consequently, a time-and-materials line prices strictly higher than a lump-sum line of equivalent labour value whenever a nonzero materials subtotal is charged. A negative `unit_price_cents` is refused on these base-spec lines — credit pricing exists only on growth work (§3.5). A negative `hourly_rate_cents` or `materials_cost_cents` is likewise rejected with `ERR_PRICING_INPUT_INVALID` whatever the pricing mode, while inputs the line's mode does not consume (for example `materials_cost_cents` on a `LUMP_SUM` line) are stored on the line without entering its priced value. Any missing or non-positive mode-conditional input is rejected with `ERR_PRICING_INPUT_INVALID`.

Work lines may declare sequencing: each element of a line's `depends_on_ids` names a prerequisite line in the same project — an element naming no existing line of the project is rejected with `ERR_NOT_FOUND` — and the list defaults to empty. The dependency graph must stay acyclic and may never reference the line itself — a violation, whether at creation or at a later edit, is rejected with `ERR_DEPENDENCY_CYCLE`. Two execution flags complete the line: `requires_hot_work`, defaulting to false, marks the task as burning or welding work subject to the permit gate of §3.4, and `subcontractor_id`, null until the line is assigned, names the firm that will perform it.

The project's `bid_total_cents` is a live roll-up: the sum of `line_total_cents` across its work items whose `origin_kind` is `BASE_SPEC` and whose status is anything but `CANCELLED`. When the specification is complete, the `ProjectManager` submits the bid, moving the project from `DRAFT` to `BID_SUBMITTED`. Submission requires at least one non-cancelled `BASE_SPEC` line — an empty specification is rejected with `ERR_BID_EMPTY` — recomputes `bid_total_cents` from the roll-up, and increments the project's `version` by one. Base-spec lines may still be added while the project is `BID_SUBMITTED`; later states lock the specification.

### 3.3. Award and Dock Occupancy

Award is a `CommercialApprover` act that moves a submitted project from `BID_SUBMITTED` to `CONTRACTED`, and it freezes commercial terms. The current `bid_total_cents` is snapshot into `awarded_price_cents`; `contracted_price_cents` — null, like the awarded figure, until this moment — initialises to the awarded figure; `ld_daily_rate_cents` is selected from the liquidated-damages tier table of §3.7 against the contracted price; and `provisional_ld_cents` is recomputed, which before docking — when no forecast yet exists — stands at zero. The award increments the project's `version` by one.

Dock time is then booked by the `ProjectManager`; booking itself carries no project-state precondition — the `CONTRACTED` requirement bites only at activation (below). A booking names the `project_id`, an occupation window from `start_utc` (inclusive) to `end_utc` (exclusive), and the `expected_project_version` required by the concurrency rule of §2.8; the reservation's `dock_id` is copied from the project's `dock_id` at creation, so bookings always target the dock the project was opened against. Three validations then apply in addition to the concurrency check. The vessel must fit the dock: her `length_m` must not exceed the dock's `max_length_m`, her `beam_m` must not exceed `max_beam_m`, and her `draft_m` must not exceed `max_depth_m` — all three comparisons are inclusive, so a vessel exactly at a limit fits — and any excess is rejected with `ERR_VESSEL_EXCEEDS_DOCK_LIMITS`. The window must be sensible: `end_utc` strictly after `start_utc`, or the booking is rejected with `ERR_RESERVATION_WINDOW_INVALID`. And the dock must be free: the occupied window — the booked window extended by the twelve-hour turnaround buffer — must not intersect the occupied window of any other `BOOKED` or `ACTIVE` reservation of the same dock; because occupied windows are half-open, a new start falling exactly twelve hours after a prior booking's end is allowed, while any stricter intersection is rejected with `ERR_DOCK_SLOT_CONFLICT`.

A successful booking lands in `BOOKED`, its `dockage_fee_cents` is computed at creation, and the parent project's `version` increments by one. The fee charges the number of whole 24-hour nights fully inside the half-open window — the turnaround buffer is never chargeable — multiplied by the dock's `daily_rate_cents` and by a length-overall multiplier taken from the vessel's `length_m`: 1.00 when she is shorter than 100 metres, 1.25 when her length is at least 100 metres and shorter than 200 metres, and 1.60 when her length is 200 metres or more; the product is rounded half-up to a whole cent. Booking a second, disjoint window for the same project is legitimate product behaviour — but because the first booking has already advanced the project's `version`, the second must be submitted against the refreshed version or it fails the stale-version check. Reservations can be listed and filtered by `dock_id`, `project_id`, or `status`.

Docking in is driven from the reservation. While a reservation is `BOOKED` and the logical time falls inside its window — on or after `start_utc` and strictly before `end_utc` — the `ProjectManager` may activate it, provided the parent project is `CONTRACTED`; activating against a project in any other state is rejected with `ERR_PROJECT_NOT_CONTRACTED`, and activating outside the window is rejected with `ERR_INVALID_STATE`. Activation stamps `activated_at_utc` — null until this moment — moves the reservation to `ACTIVE`, and in the same stroke moves the parent project from `CONTRACTED` to `IN_DOCK`: `actual_dock_in_utc` is set to the current logical time, `critical_path_days` is recomputed, `forecast_delivery_utc` is established from the docking instant plus the critical path plus any approved schedule deltas, `provisional_ld_cents` is recomputed, and the project's `version` increments by one. A `BOOKED` reservation may alternatively be cancelled, moving it to `CANCELLED` and freeing its window — turnaround buffer included — for future bookings. Release from `ACTIVE` happens only through the completion gate of §3.7, which stamps `released_at_utc`.

### 3.4. Executing Work in the Dock

Sequencing in the dock is governed by the dependency graph and a derived readiness signal. An item's `ready` flag is derived, never stored as a state: it is true exactly when the item is `PLANNED` and every item named in its `depends_on_ids` is `COMPLETE`, and it is exposed as a read-only `ready` field on every work-item response. A reverse lookup lists the items that depend on a given item — every work item whose `depends_on_ids` contains the addressed item — which planners use for impact analysis before edits. Work items can be listed and filtered by `project_id`, `subcontractor_id`, `origin_change_order_id`, or `status`.

While a line is still `PLANNED`, the `ProjectManager` may edit its `depends_on_ids`, its `subcontractor_id`, or its `duration_days`. The edit is cycle-checked — the revised `depends_on_ids` must keep the project's work-item graph acyclic and must not reference the item itself, or it is rejected with `ERR_DEPENDENCY_CYCLE` — and trade-checked: when a `subcontractor_id` is assigned, that firm's `trade_codes` must contain the item's `trade_code`, or the edit is rejected with `ERR_TRADE_MISMATCH`. Supplying an explicit null `subcontractor_id` clears the assignment without any existence or trade check, an explicit null `depends_on_ids` is treated as the empty list, and fields outside the three editable ones are ignored; the edit increments the item's `version` by one whether or not any supplied value differs from the stored one. A change to `duration_days` or `depends_on_ids` recomputes the project's critical path.

Starting a line moves it from `PLANNED` to `IN_PROGRESS` and is open to the `ProjectManager` and to the assigned firm acting in the `Subcontractor` role. Five gates guard the start. First, the parent project must be `IN_DOCK` — with the single exception that a `WARRANTY_REWORK` line may start while its project is `DELIVERED` — otherwise the start is rejected with `ERR_PROJECT_NOT_IN_DOCK`. Second, when the actor is a `Subcontractor` and the item carries a `subcontractor_id`, the caller's `X-User-ID` must equal that `subcontractor_id`; a firm touching another firm's assignment is rejected with `ERR_OWNERSHIP_MISMATCH`. Third, hot work: when `requires_hot_work` is true, the project must hold a `HOT_WORK` permit in `GRANTED` status whose window covers the current logical time — the time must fall on or after `valid_from` and on or before `valid_to` — or the start is rejected with `ERR_HOT_WORK_PERMIT_REQUIRED`; `SUSPENDED` and `EXPIRED` permits do not satisfy this gate. Fourth, every item named in `depends_on_ids` must already be `COMPLETE`, or the start is rejected with `ERR_DEPENDENCY_NOT_MET`. Fifth, crew loading: when the item carries a `subcontractor_id`, that firm must currently hold fewer than three `IN_PROGRESS` work items — a start that would give it a fourth is rejected with `ERR_SUBCONTRACTOR_CAPACITY`, while holding exactly three in-progress items is permitted. A successful start increments the work item's `version` by one.

Completing a line moves it from `IN_PROGRESS` to `COMPLETE` and stamps `completed_at_utc` with the current logical time; when the actor is a `Subcontractor`, the same ownership comparison applies, again rejecting strangers with `ERR_OWNERSHIP_MISMATCH`. Completion ripples outward. The derived `ready` flags of dependent items recompute. The project's completion gate is re-evaluated and, if satisfied, the project auto-transitions from `IN_DOCK` to `WORK_COMPLETE`, cascading the reservation release described in §3.7. When the completed item is a `WARRANTY_REWORK` line, the warranty claim whose `rework_work_item_id` references it auto-transitions from `ACCEPTED` to `CLOSED` (§3.8). And the project's `critical_path_days`, `forecast_delivery_utc`, and `provisional_ld_cents` are recomputed.

Cancelling a line moves it from `PLANNED` to `CANCELLED` and is available only for base-spec lines: growth items materialised by change orders and rework items materialised by warranty claims may never be cancelled, and a cancel attempted against a line that is not `PLANNED`, or against a growth or rework line, is rejected with `ERR_INVALID_STATE`. Cancellation excludes the line from the bid roll-up — `bid_total_cents` is recomputed over the remaining non-cancelled `BASE_SPEC` lines — and recomputes the critical path.

The critical path itself is recomputed whenever the work graph changes: when a line is added, edited in duration or dependencies, cancelled, or completed; when growth work joins the graph; and when the project docks in. The calculation considers only items whose status is `PLANNED` or `IN_PROGRESS`. For each such item, its chain length is its own `duration_days` plus the greatest chain length among the prerequisites it names in `depends_on_ids` that are themselves still unfinished; an item with no unfinished prerequisites contributes only its own duration. The project's `critical_path_days` is the greatest chain length among all unfinished items, and zero when none remain. Because acyclicity is guaranteed at write time by the `ERR_DEPENDENCY_CYCLE` check, this longest-chain evaluation always terminates, and ties between chains contribute identical sums, so no tie-breaking rule can affect the value. The forecast redelivery instant, `forecast_delivery_utc`, is then `actual_dock_in_utc` plus `critical_path_days` whole days plus the sum of `schedule_delta_days` across the project's `APPROVED` change orders; it remains null until the project reaches `IN_DOCK`.

### 3.5. Growth Work and the Change-Order Loop

Growth work — defects discovered only once the vessel is opened up in dock — enters the system as a change order proposed by the `ProjectManager` while the project is `IN_DOCK`; proposals against a project in any other state are rejected with `ERR_PROJECT_NOT_IN_DOCK`. The proposal names the `project_id` and the `expected_project_version` required by §2.8, a `description` of the discovered work, the `trade_code` that will perform it, a `duration_days` of at least one, and a signed `schedule_delta_days` expressing the delivery-schedule impact in whole days — positive pushes redelivery out, negative pulls it in. Pricing follows the same mode-conditional rules as base-spec lines: a `LUMP_SUM` proposal requires `quantity` greater than zero and `unit_price_cents`, a `TIME_AND_MATERIALS` proposal requires `estimated_hours` greater than zero and `hourly_rate_cents` with an optional `materials_cost_cents` defaulting to zero, and violations are rejected with `ERR_PRICING_INPUT_INVALID`. Unlike base-spec lines, a negative `unit_price_cents` is permitted here, producing a credit change order that reduces the contract price.

At creation the system prices the proposal into `proposed_cost_cents` under the same per-line rounding discipline as §3.2, records the creating manager's `X-User-ID` as `proposed_by_user_id`, and computes `requires_owner_countersign`: true exactly when `proposed_cost_cents` is strictly greater than 5000000 cents (that is, $50,000.00) — a proposal priced exactly at that amount does not require the countersign. The change order lands in `UNDER_REVIEW` with `commercial_approved_by`, `owner_approved_by`, `approved_at_utc`, and `rejection_reason` all null, and the creation increments the parent project's `version` by one. Change orders can be listed and filtered by `project_id` or `status`.

Adjudication is split across two desks. Commercial approval is a `CommercialApprover` act guarded by segregation of duties: the approver's `X-User-ID` is compared against the change order's `proposed_by_user_id`, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES`. If the project carries a `change_budget_cents` ceiling, approval is refused with `ERR_CHANGE_BUDGET_EXCEEDED` whenever the sum of `proposed_cost_cents` across the project's already-`APPROVED` change orders plus this proposal would exceed the ceiling; a project without the ceiling admits change orders of any size. A passing commercial approval records `commercial_approved_by` as the approver's `X-User-ID`.

Whether the approval completes depends on the countersign. When `requires_owner_countersign` is true and `owner_approved_by` is still null, the change order stays in `UNDER_REVIEW` and none of the cascade effects fire; when no countersign is required, or the countersign is already recorded, the approval becomes final. Final approval stamps `approved_at_utc` with the current logical time and fires a three-link cascade across the project. First, the growth work materialises as a new work item built from the change order's own specification — its `description`, `trade_code`, pricing inputs, and `duration_days` — with an `origin_kind` of `CHANGE_ORDER`, the `origin_change_order_id` set to the change order's id, a `line_total_cents` equal to the change order's `proposed_cost_cents`, an empty `depends_on_ids`, `requires_hot_work` false, no `subcontractor_id`, and status `PLANNED`. Second, the project's `contracted_price_cents` is recomputed as `awarded_price_cents` plus the sum of `proposed_cost_cents` over all of the project's `APPROVED` change orders — credit orders, whose proposed cost is negative, reduce the contract price — and the new contract price re-selects `ld_daily_rate_cents` from the tier table of §3.7. Third, the change order's `schedule_delta_days` joins the approved-delta sum, so `forecast_delivery_utc` and `provisional_ld_cents` are recomputed. Every approval or countersign call — final or not — increments the change order's `version` by one and the parent project's `version` by one.

The owner's countersign is a `ShipownerRep` act whose `X-User-ID` must equal the `owner_user_id` recorded on the project's vessel; any other caller is rejected with `ERR_OWNERSHIP_MISMATCH`. Countersigning a change order that does not require it — one priced at or below the threshold — is rejected with `ERR_OWNER_APPROVAL_NOT_REQUIRED`. A successful countersign records `owner_approved_by`; when `commercial_approved_by` is already present, the full approval cascade above fires. The two approvals may arrive in either order — whichever lands last completes the transition to `APPROVED`.

A `CommercialApprover` may instead reject the proposal, supplying a non-empty `reason` that is recorded as `rejection_reason`; an empty reason fails well-formedness with `ERR_INVALID_REQUEST`. Rejection moves the change order from `UNDER_REVIEW` to `REJECTED`, and rejection is not terminal: the proposing `ProjectManager` may loop a `REJECTED` change order back to `UNDER_REVIEW` by revising any of `quantity`, `unit_price_cents`, `estimated_hours`, `hourly_rate_cents`, `materials_cost_cents`, `duration_days`, or `schedule_delta_days`. The revision reprices `proposed_cost_cents` under the same per-line rules — with the mode-conditional inputs again guarded by `ERR_PRICING_INPUT_INVALID` — recomputes `requires_owner_countersign` against the new price, and clears both `commercial_approved_by` and `owner_approved_by` so negotiation restarts from a clean sheet; the recorded `rejection_reason` is retained. Alternatively, the `ProjectManager` may withdraw an `UNDER_REVIEW` proposal outright, moving it to the terminal `WITHDRAWN` state. Approve, reject, owner-countersign, and withdraw are defined only from `UNDER_REVIEW`, and revise only from `REJECTED`; invoking any of them from any other state is rejected with `ERR_CHANGE_ORDER_NOT_REVIEWABLE`.

### 3.6. Surveys, Permits, and Environmental Control

Regulatory attendance is arranged through surveys. A `ClassSurveyor` books a survey by naming the `project_id`, a `survey_type` of `CLASS_RENEWAL`, `CLASS_INTERMEDIATE`, `USCG_INSPECTION`, or `LOAD_LINE`, and a planned interval from `scheduled_start_utc` to `scheduled_end_utc`; the end must be strictly after the start, or the booking fails well-formedness with `ERR_INVALID_REQUEST`. The creating surveyor's `X-User-ID` is recorded as `surveyor_user_id`, and bookings are checked against that surveyor's own calendar under closed-interval semantics: any overlap with another of the same surveyor's `SCHEDULED` surveys — including a new survey whose start coincides exactly with another's end — is rejected with `ERR_SURVEYOR_SCHEDULE_CONFLICT`. A booked survey sits in `SCHEDULED` with its `result` and `deficiency_count` unset. Surveys can be listed and filtered by `project_id`, `surveyor_user_id`, or `status`.

Recording the outcome belongs to the surveyor who booked it: the recorder's `X-User-ID` is compared against `surveyor_user_id`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. Discipline is enforced on the outcome pair. A `result` of `PASSED` requires `deficiency_count` to be omitted or zero; a `result` of `FAILED` requires a `deficiency_count` of at least one; any other combination is rejected with `ERR_SURVEY_RESULT_INVALID`. Both outcomes are terminal for the survey. A recorded `PASSED` re-evaluates the project's completion gate (§3.7). A recorded `FAILED` leaves the project in `IN_DOCK`: the failure is superseded by booking a fresh survey of the same `survey_type`, because the completion gate consults only the latest survey of each required type.

Environmental control is exercised through permits. An `EnvironmentalOfficer` applies for a permit by naming the `project_id`, a `permit_type` of `HOT_WORK`, `PAINT_SPRAY`, `BALLAST_DISCHARGE`, or `HULL_BLASTING`, and a validity window from `valid_from` through `valid_to`; the window is a closed, day-granular interval, and `valid_to` must be strictly after `valid_from` or the application is rejected with `ERR_PERMIT_WINDOW_INVALID`. A permit's dock scope derives from its project's dock, which is what makes hot-work exclusivity a per-dock rule. Applications land in `APPLIED`, and permits can be listed and filtered by `project_id`, `permit_type`, or `status`.

Granting a permit moves it from `APPLIED` to `GRANTED` and increments the permit's `version` by one. For `HOT_WORK` the grant is exclusive per dock: if any other `GRANTED` hot-work permit exists for a project sharing the same dock whose closed day-interval overlaps the applicant's — touching days count as overlap — the grant is rejected with `ERR_HOT_WORK_PERMIT_CONFLICT`. A granted permit may later be suspended, moving it from `GRANTED` to `SUSPENDED`, and suspension stops the permit from satisfying the hot-work start gate of §3.4 immediately. Closing is terminal and available from `APPLIED`, `GRANTED`, or `SUSPENDED`. Finally, the clock sweep of §2.5 moves any permit in one of those three states to `EXPIRED` once the logical time runs strictly past `valid_to`, and an expired permit no longer satisfies the hot-work gate either.

### 3.7. Completing Work and Delivering the Vessel

The transition from `IN_DOCK` to `WORK_COMPLETE` is automatic — no operator invokes it. The gate is re-evaluated whenever a work item completes and whenever a survey is recorded `PASSED`, and it opens when two conditions hold together: every work item of the project is in `COMPLETE` or `CANCELLED`, and for every entry of `required_survey_types` the project's latest survey of that type — latest by creation timestamp — is `PASSED`. A project created with an empty `required_survey_types` carries no survey gate at all. When the gate opens, the project's `ACTIVE` dock reservation is released in the same stroke, moving to `RELEASED` with `released_at_utc` set to the current logical time and freeing the dock window, and the project's `version` increments by one.

From `WORK_COMPLETE`, a `ProjectManager` delivers the vessel, moving the project to `DELIVERED`. Delivery stamps `delivered_at_utc` with the current logical time, runs the final liquidated-damages variant against the actual delivery date and freezes the result into `liquidated_damages_cents`, opens the warranty window by setting `warranty_end_utc` to the delivery instant plus `warranty_days` calendar days, freezes `provisional_ld_cents` at its last computed value, and increments the project's `version` by one. These three fields — `delivered_at_utc`, `liquidated_damages_cents`, and `warranty_end_utc` — have been null since creation and are set only here.

Liquidated damages accrue per calendar day of late redelivery, at a daily rate tiered on the project's `contracted_price_cents`. A contracted price below 50000000 cents (that is, $500,000.00) selects a rate of 200000 cents per day ($2,000.00). A contracted price of at least 50000000 cents and at most 200000000 cents ($2,000,000.00) selects 500000 cents per day ($5,000.00) — a contract priced at exactly 50000000 cents therefore falls in this middle tier. A contracted price above 200000000 cents selects 1000000 cents per day ($10,000.00). Lateness is the number of whole calendar days between the delivery date and the `contract_delivery_date`, floored at zero for early or on-time delivery. The first three calendar days of lateness are grace days: chargeable days are the late days minus three, again floored at zero, so a delivery exactly three days late accrues nothing. The accrual is the chargeable days multiplied by the tier's daily rate, and the assessed damages are the lesser of that accrual and a cap of ten percent of the contracted price, the cap itself rounded half-up to a whole cent.

Two variants of this calculation exist. While the project has not yet been delivered, a forward-looking provisional variant runs against the calendar date of `forecast_delivery_utc` and is recomputed into `provisional_ld_cents` on every mutation that touches the contracted price, the forecast, or the tier rate. At the delivery transition, the final variant runs once against the calendar date of `delivered_at_utc`, and its result is frozen into `liquidated_damages_cents` while the provisional figure freezes at its last computed value. Thereafter the project rests in `DELIVERED` until the warranty window closes: the clock sweep of §2.5 moves it to the terminal `CLOSED` state once the logical time runs strictly past `warranty_end_utc`.

### 3.8. Warranty Claims and Re-Work

After delivery, the owner may allege defects in the delivered work. A `ShipownerRep` files a claim naming the `project_id`, the `work_item_id` of the delivered work item alleged defective, and a `description` of the defect. Three guards protect filing. The caller's `X-User-ID` — recorded on the claim as `filed_by_user_id` — must equal the `owner_user_id` of the project's vessel, or the filing is rejected with `ERR_OWNERSHIP_MISMATCH`. The project must be `DELIVERED` and the current logical time must be at or before `warranty_end_utc` — filing exactly at the window's end instant is allowed — or the filing is rejected with `ERR_WARRANTY_EXPIRED`. And the named work item must actually belong to the named project, or the filing is rejected with `ERR_WORK_ITEM_NOT_IN_PROJECT`. A valid claim lands in `FILED`, with `rework_work_item_id` and `denial_reason` null, and claims can be listed and filtered by `project_id`, `work_item_id`, `rework_work_item_id`, or `status`.

Disposition belongs to the `ProjectManager`. Accepting a claim — supplying `rework_duration_days` for the repair, an integer of at least one failing well-formedness with `ERR_INVALID_REQUEST` otherwise — moves it from `FILED` to `ACCEPTED` and materialises a zero-priced rework work item: its `origin_kind` is `WARRANTY_REWORK`, its `line_total_cents` is zero, its `trade_code`, `description`, `pricing_mode`, and pricing inputs are copied from the defective item, its `duration_days` takes the supplied rework duration, it is born with an empty `depends_on_ids`, `requires_hot_work` false, and no `subcontractor_id`, and the new item's id is recorded on the claim as `rework_work_item_id`. The yard absorbs rework cost, so the project's `contracted_price_cents` is unchanged. Because the project is `DELIVERED` rather than `IN_DOCK`, the usual in-dock start rule is relaxed for exactly this case: a rework item may be started while its project is `DELIVERED`, as §3.4 describes. When that rework item completes, the claim closes itself, moving from `ACCEPTED` to `CLOSED`.

Denying a claim instead requires a non-empty `reason`, which is recorded as `denial_reason`; an empty reason is rejected with `ERR_INVALID_REQUEST`. Denial moves the claim from `FILED` to the terminal `DENIED` state. Accept and deny are defined only from `FILED`; acting on a claim in any other state is rejected with `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or act upon an existing resource, and all reads, return a `200 OK` status code. The table below is a summary only; request payloads, response shapes, and side effects are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/docks` | Register a dock/berth with dimensional ceilings and base dockage rate | YardAdmin |
| GET | `/v1/docks/{id}` | Fetch one dock | Any |
| POST | `/v1/vessels` | Register a vessel with its dimensions and owner | ProjectManager |
| GET | `/v1/vessels/{id}` | Fetch one vessel | Any |
| POST | `/v1/subcontractors` | Register a subcontractor with certified trades | YardAdmin |
| GET | `/v1/subcontractors/{id}` | Fetch one subcontractor | Any |
| POST | `/v1/repair-projects` | Open a repair project in `DRAFT` against a vessel and a dock | ProjectManager |
| GET | `/v1/repair-projects/{id}` | Fetch one project with computed fields (bid totals, forecast, damages accruals) | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep, ClassSurveyor, EnvironmentalOfficer |
| GET | `/v1/repair-projects` | List projects; filter by vessel, dock, or status | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep, ClassSurveyor, EnvironmentalOfficer |
| POST | `/v1/repair-projects/{id}/submit-bid` | Move `DRAFT` → `BID_SUBMITTED`; requires a non-empty base spec | ProjectManager |
| POST | `/v1/repair-projects/{id}/award` | Move `BID_SUBMITTED` → `CONTRACTED`; freezes the awarded price and selects the damages tier | CommercialApprover |
| POST | `/v1/repair-projects/{id}/deliver` | Move `WORK_COMPLETE` → `DELIVERED`; assesses final liquidated damages and opens the warranty window | ProjectManager |
| POST | `/v1/dock-reservations` | Book a dock window for a project; validates vessel fit and overlap; OCC on the project version | ProjectManager |
| GET | `/v1/dock-reservations/{id}` | Fetch one reservation | YardAdmin, ProjectManager, CommercialApprover, EnvironmentalOfficer |
| GET | `/v1/dock-reservations` | List reservations; filter by dock, project, or status | YardAdmin, ProjectManager, CommercialApprover, EnvironmentalOfficer |
| POST | `/v1/dock-reservations/{id}/activate` | Move `BOOKED` → `ACTIVE`; docks the project in | ProjectManager |
| POST | `/v1/dock-reservations/{id}/cancel` | Move `BOOKED` → `CANCELLED`; frees the window including the turnaround buffer | ProjectManager |
| POST | `/v1/work-items` | Add a base-spec work line to a `DRAFT` or `BID_SUBMITTED` project | ProjectManager |
| GET | `/v1/work-items/{id}` | Fetch one work item | Any |
| GET | `/v1/work-items` | List work items; filter by project, subcontractor, origin change order, or status | Any |
| GET | `/v1/work-items/{id}/dependents` | List work items whose dependency lists contain this item | Any |
| PATCH | `/v1/work-items/{id}` | Edit a `PLANNED` item's dependencies, subcontractor assignment, or duration | ProjectManager |
| POST | `/v1/work-items/{id}/start` | Move `PLANNED` → `IN_PROGRESS` under the five start gates | ProjectManager, Subcontractor |
| POST | `/v1/work-items/{id}/complete` | Move `IN_PROGRESS` → `COMPLETE`; re-evaluates the completion gate | ProjectManager, Subcontractor |
| POST | `/v1/work-items/{id}/cancel` | Move `PLANNED` → `CANCELLED` for base-spec items only | ProjectManager |
| POST | `/v1/change-orders` | Propose growth work discovered in dock; OCC on the project version | ProjectManager |
| GET | `/v1/change-orders/{id}` | Fetch one change order | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep |
| GET | `/v1/change-orders` | List change orders; filter by project or status | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep |
| POST | `/v1/change-orders/{id}/approve` | Commercial approval; fires the approval cascade unless the owner countersign is outstanding | CommercialApprover |
| POST | `/v1/change-orders/{id}/owner-approve` | Owner countersign for over-threshold change orders | ShipownerRep |
| POST | `/v1/change-orders/{id}/reject` | Move `UNDER_REVIEW` → `REJECTED` with a reason | CommercialApprover |
| POST | `/v1/change-orders/{id}/revise` | Loop `REJECTED` → `UNDER_REVIEW` with repriced fields | ProjectManager |
| POST | `/v1/change-orders/{id}/withdraw` | Move `UNDER_REVIEW` → `WITHDRAWN` (terminal) | ProjectManager |
| POST | `/v1/surveys` | Schedule a class or Coast Guard survey against the surveyor's own calendar | ClassSurveyor |
| GET | `/v1/surveys/{id}` | Fetch one survey | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep, ClassSurveyor, EnvironmentalOfficer |
| GET | `/v1/surveys` | List surveys; filter by project, surveyor, or status | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep, ClassSurveyor, EnvironmentalOfficer |
| POST | `/v1/surveys/{id}/record-result` | Record `PASSED` or `FAILED` with deficiency discipline | ClassSurveyor |
| POST | `/v1/permits` | Apply for an environmental permit window | EnvironmentalOfficer |
| GET | `/v1/permits/{id}` | Fetch one permit | YardAdmin, ProjectManager, CommercialApprover, EnvironmentalOfficer |
| GET | `/v1/permits` | List permits; filter by project, type, or status | YardAdmin, ProjectManager, CommercialApprover, EnvironmentalOfficer |
| POST | `/v1/permits/{id}/grant` | Move `APPLIED` → `GRANTED`; hot-work grants enforce per-dock exclusivity | EnvironmentalOfficer |
| POST | `/v1/permits/{id}/suspend` | Move `GRANTED` → `SUSPENDED`; hot-work coverage stops immediately | EnvironmentalOfficer |
| POST | `/v1/permits/{id}/close` | Move `APPLIED`, `GRANTED`, or `SUSPENDED` → `CLOSED` (terminal) | EnvironmentalOfficer |
| POST | `/v1/warranty-claims` | File a defect claim against a delivered work item | ShipownerRep |
| GET | `/v1/warranty-claims/{id}` | Fetch one warranty claim | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep |
| GET | `/v1/warranty-claims` | List claims; filter by project, defective item, rework item, or status | YardAdmin, ProjectManager, CommercialApprover, ShipownerRep |
| POST | `/v1/warranty-claims/{id}/accept` | Move `FILED` → `ACCEPTED`; spawns the zero-priced rework work item | ProjectManager |
| POST | `/v1/warranty-claims/{id}/deny` | Move `FILED` → `DENIED` with a reason | ProjectManager |
| POST | `/v1/_clock/set_current_utc` | Advance the logical clock; sweeps permit expiry and warranty closure | YardAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_NOT_CONTRACTED` | 409 Conflict |
| `ERR_PROJECT_NOT_IN_DOCK` | 409 Conflict |
| `ERR_CHANGE_ORDER_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_OWNER_APPROVAL_NOT_REQUIRED` | 409 Conflict |
| `ERR_HOT_WORK_PERMIT_REQUIRED` | 409 Conflict |
| `ERR_VESSEL_EXCEEDS_DOCK_LIMITS` | 422 Unprocessable Entity |
| `ERR_RESERVATION_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_PERMIT_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_PRICING_INPUT_INVALID` | 422 Unprocessable Entity |
| `ERR_DEPENDENCY_CYCLE` | 422 Unprocessable Entity |
| `ERR_TRADE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BID_EMPTY` | 422 Unprocessable Entity |
| `ERR_SURVEY_RESULT_INVALID` | 422 Unprocessable Entity |
| `ERR_DOCK_SLOT_CONFLICT` | 409 Conflict |
| `ERR_SURVEYOR_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_HOT_WORK_PERMIT_CONFLICT` | 409 Conflict |
| `ERR_WARRANTY_EXPIRED` | 409 Conflict |
| `ERR_DEPENDENCY_NOT_MET` | 409 Conflict |
| `ERR_WORK_ITEM_NOT_IN_PROJECT` | 422 Unprocessable Entity |
| `ERR_CHANGE_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SUBCONTRACTOR_CAPACITY` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

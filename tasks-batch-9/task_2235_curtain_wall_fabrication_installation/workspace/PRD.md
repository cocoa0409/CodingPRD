# Curtain Wall Fabrication & Installation API — Product Requirements Document

## 1. Introduction

A curtain wall subcontractor sits in an uncomfortable position on any high-rise project: it is simultaneously a design office, a factory, a procurement desk and a field installation crew, and every one of those four hats depends on the other three. Engineering cannot seal a structural calculation until the architect has closed the design-assist conversation; the factory cannot batch a panel until the architect has approved the drawing set and the glass fabricator has confirmed a coating; the field cannot hang a panel until the structural contractor has poured slab-edge embeds within tolerance and a hoist window has been reserved; and nobody gets paid until the wall has demonstrably kept water out. The current practice of tracking all of this on spreadsheets and email threads fails in exactly the places where it costs the most money — a coating re-fire silently invalidates a release that the shop has already started glazing, or a failed field spray test quietly leaves a floor billed as weather-tight when it is not.

This document specifies an API that makes those dependencies explicit and enforceable. The system tracks a facade package from the design-assist phase through the unitized-versus-stick-built system decision, delegated-design submittal cycles, performance mockup qualification, glass procurement, fabrication release, floor-by-floor installation, water and air infiltration field testing, defect remediation and finally punch-list close-out. Two commercial engines run alongside the workflow: a field-labor cost model that produces both a forward-looking estimate at panel-hang time and a chronological actual at certification time, and an earned-value model that converts weather-tight zones into certified revenue net of retention.

The design goal throughout is that the system should refuse work that the project is not ready for, and should retract work whose basis has been withdrawn. When a submittal returns for revision or a coating specification is re-fired, live fabrication releases are revoked, their panel lots are held, and any zone that depended on those lots loses its weather-tight status along with the earned value it had booked. That retraction chain — not the happy path — is the hardest part of this specification and the part that most needs to be built exactly as written.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts and cross-cutting rules that apply across the whole API. Collections are mounted at the root of the service; there is no shared resource prefix.

### 2.1. Project Participants and Role-Based Access Control

Every request must present two headers: `X-User-Role`, naming the participant capacity the caller is acting in, and `X-User-ID`, naming the individual operator. A request that arrives without `X-User-Role`, or with it empty, is rejected with `ERR_MISSING_ROLE` (HTTP 401); the only exception is the clock-setting capability described in §2.5, which is exempt from the role-header requirement. When the role is present but is not one of the roles the addressed operation permits, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Eight participant roles exist, spelled exactly as follows. `CWProjectManager` is the curtain wall subcontractor's project manager, who opens the facade package, owns the unitized-versus-stick-built decision, registers test laboratories and installation zones, releases fabrication and certifies weather-tightness. `CWDetailer` is the shop-drawing detailer, who prepares and resubmits submittals, re-details movement joints and answers punch items. `DelegatedEngineer` is the delegated design engineer of record, whose only write capability is applying a professional seal — and who is barred from reviewing what it sealed. `ArchitectOfRecord` is the architect or owner's reviewer, who runs the submittal review cycle, burns down review notes and waives non-critical punch items. `GlazingProcurement` places and manages glass orders, coating revisions, expedites, receipts and breakage stock. `StructuralContractor` is the concrete contractor pouring the slab edges, who owns embed survey and pour confirmation. `FieldSuperintendent` owns hoisting equipment, reservations, the installation sequence, crew-day logs and shop-to-site lot movement. `QCInspector` is the quality-control and testing agency, which records mockup and field test results, schedules field tests, raises defects and re-inspects remediation — but never re-inspects an item it raised itself.

All eight roles carry an **opaque** identity. When `X-User-Role` is `CWProjectManager`, `CWDetailer`, `DelegatedEngineer`, `ArchitectOfRecord`, `GlazingProcurement`, `StructuralContractor`, `FieldSuperintendent` or `QCInspector`, the accompanying `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity and is never compared against any resource's `id`. The server does record it in specific places where a scaffolded transition writes it — `sealed_by_user_id` on a submittal at seal time, `reviewed_by_user_id` on a submittal at review time, `surveyed_by_user_id` on an embed survey, `recorded_by_user_id` on a field test, `raised_by_user_id` and `reinspected_by_user_id` on a defect item — and it compares the incoming `X-User-ID` against those previously recorded values to enforce segregation of duties. It never resolves `X-User-ID` to a stored user record.

Five operations record or compare an acting operator and therefore additionally require `X-User-ID` to be present and non-empty: applying a submittal seal, starting a submittal review, recording a review decision, re-inspecting a defect item, and posting a crew day. A missing or empty `X-User-ID` on any of those five is rejected with `ERR_MISSING_USER` (HTTP 401).

Every read operation in the system is available to all eight roles. Write operations are restricted as tabulated in §4.

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

### 2.3. Pagination and Collection Filtering

List responses are paginated through two query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100. `offset` sets the number of rows skipped before the page begins; it defaults to 0 and may not be negative. The `meta` block of a list response carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the size of the filtered set before the page window is applied and `has_more` indicates whether rows remain beyond it. Unless a specific endpoint says otherwise, list results are sorted by `created_at` in ascending order.

Filters are additive: supplying several narrows the set. The facade-package list accepts `state`, `engineering_posture` and `system_type`. The submittal list accepts `package_id`, `state` and `submittal_type`, and the package-scoped submittal view accepts `state`. The package-scoped zone view accepts `weather_status`. The glass-order list accepts `package_id`, `state` and `risk_flag`. The fabrication-release list accepts `package_id`, `submittal_id`, `glass_order_id` and `state`. The panel-lot list accepts `release_id`, `glass_order_id`, `zone_id` and `fabrication_status`, and the release-scoped and order-scoped lot views each accept `fabrication_status`. The breakage-draw list accepts `glass_order_id`, `panel_lot_id` and `status`. The laboratory list accepts `name`. The mockup-test list accepts `package_id`, `test_lab_id`, `retest_of_test_id` and `state`. The embed-survey list accepts `zone_id` and `state`. The installation-zone list accepts `package_id`, `install_status`, `weather_status` and `floor_number`. The crew-day list accepts `zone_id`, `status` and `work_date`, and the zone-scoped crew-day view accepts `status`. The hoist-rig list accepts `package_id` and `status`, and the rig-scoped reservation view accepts `status`. The reservation list accepts `rig_id`, `zone_id` and `status`. The field-test list accepts `zone_id`, `test_kind` and `state`, and the zone-scoped field-test view accepts `test_kind` and `state`. The defect-item list — which is the project punch list — accepts `package_id`, `zone_id`, `field_test_id`, `mockup_test_id`, `status`, `severity` and `origin`. Only the list endpoints named above honour `limit` and `offset`; the nested child views scoped to a single parent return the whole child set.

### 2.4. Resource Identity, Timestamps and Revision Counters

Every resource is identified by `id`, a server-minted UUID carrying no type prefix and no embedded semantics; clients never supply it. Almost every resource additionally carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the row is created and increases by exactly 1 on every mutation the server performs on that row. `updated_at` is refreshed on the same events that advance `version`. A mutation reached indirectly — through one of the cascades described in §2.11 — advances the affected row's `version` and refreshes its `updated_at` just as a directly requested mutation would.

Test laboratories are the single exception. A laboratory is an immutable accreditation reference: it carries only `id` and `created_at`. It has no `updated_at`, no `version` and no update capability of any kind. Any implementation that emits `updated_at` or `version` on a laboratory is wrong.

New resources are returned with HTTP 201. Operations that modify an existing resource — every state transition, every compensating action, every recomputation — return HTTP 200 with the updated resource in `data`.

### 2.5. The Logical Project Clock

The service does not read the host wall clock. Every default timestamp, every lead-time arithmetic step, every hoist-window comparison and every "now" in this document reads a **logical clock** that the test harness controls. An administrative capability, available to all eight roles and exempt from the role-header requirement, sets the clock: the payload carries `to_iso8601`, and the response reports the new `current_utc`. A malformed or absent `to_iso8601` is rejected with `ERR_INVALID_REQUEST`. Until the clock is set for the first time it reads `2026-08-01T00:00:00Z`.

Fields written from the logical clock rather than from a request payload include `sealed_at` on a submittal, `released_at` on a fabrication release, `shipped_at` on a panel lot, `last_risk_computed_at` on a glass order, `result_recorded_at` on mockup and field tests, `hang_completed_at` and `weather_tight_at` on a zone, and `closed_at` on a defect item. The only clock-typed field taken from a request body instead is `poured_at` on an embed survey, which records when the structural contractor states the concrete was actually placed.

### 2.6. Path Resolution and Cross-Reference Integrity

Nested paths are resolved strictly left to right. A request addressed at a child of an installation zone — an embed survey, a field test, a crew day — resolves the zone named by `{id}` first, and if that zone does not exist the request fails with `ERR_ZONE_NOT_FOUND` before the child body is examined at all. Where a second path variable follows, such as the `crew_day_id` segment written `{crew_day_id}` on the crew-day void capability, it is resolved only after its parent resolved successfully, and a crew-day log that does not exist yields `ERR_RESOURCE_NOT_FOUND`.

The same left-to-right discipline governs foreign keys carried in request bodies. When a payload names both a package and a zone, the package is resolved first; a zone that exists but belongs to a different package than the one named in the request is treated exactly like a zone that does not exist, and reported as `ERR_ZONE_NOT_FOUND`. Arrays of references are validated in the order they appear: the `zone_ids` array on a fabrication release is walked front to back, and the first element that either does not resolve or resolves to a zone whose `package_id` differs from the release's `package_id` produces `ERR_ZONE_NOT_FOUND`, with no later element examined.

### 2.7. Units, Precision and Rounding Discipline

Money is always integer **cents** — `contract_value_cents`, `unit_rate_cents_per_sqm`, `base_labor_rate_cents_per_hour`, `provisional_labor_cost_cents`, `final_labor_cost_cents`, `day_cost_cents`, `certified_line_cents`, `earned_value_certified_cents`, `retention_held_cents`, `invoice_subtotal_cents`, `surcharge_cents` and `invoice_cents` are all whole cents. There are no fractional-cent values anywhere in the system.

Wherever a value is rounded, the method is **round half up**: a value exactly on the midpoint rounds away from zero. Dimensional and scoring quantities are held to two decimal places — `thermal_movement_allowance_mm`, `deflection_limit_mm`, `risk_score`, `certified_area_sqm` and `planned_shop_hours` all round half up to two decimals. The crew-hour ledger quantities `consumed_crew_hours` and `remaining_crew_hours` round half up to one decimal place. `effective_lead_days` is a whole number of days. Two reservations of glass stock are floored rather than rounded, as noted in §2.10.

Rounding position matters as much as rounding method. Two places in this system round *per element* and then sum, never the other way round: the chronological field-labor total rounds each crew day to whole cents before the days are added together, and the earned-value calculation rounds each zone's certified line to whole cents before the lines are added together. Summing unrounded products and rounding once at the end produces answers that differ by a cent or two, and is not acceptable.

### 2.8. Stale-Version Guards on Release and Breakage Writes

Two write operations are guarded by optimistic concurrency control, because in both cases the operation is legitimately repeatable and therefore cannot be protected by a state precondition alone.

Creating a fabrication release requires the non-optional input field `expected_package_version`, carrying the client's last observed `version` of the `FacadePackage` named by `package_id`. If that value does not equal the package's current `version`, the create is rejected with `ERR_STALE_PACKAGE_VERSION` (HTTP 412). A second release covering a zone that an earlier release already covered is a perfectly legitimate operation — it re-points held lots and re-allocates lites — so nothing in the package's state can distinguish an intentional supersession from a client working off a stale picture. The version check is what forces the writer to prove its view of the package's posture, mockup qualification and zone roster is current before it supersedes anything.

Drawing replacement lites from breakage stock requires the non-optional input field `expected_glass_order_version`, carrying the client's last observed `version` of the `GlassOrder` named by `glass_order_id`. A mismatch with the order's current `version` is rejected with `ERR_STALE_GLASS_ORDER_VERSION` (HTTP 412). Repeated draws are each legitimate while stock remains, so the order's state never blocks a second draw; the stale-version check is what forces the writer to re-read `available_stock_lites` before committing another draw.

Both checks are evaluated after the addressed rows have been confirmed to exist and before any state or business rule is applied, so a client working from a stale read is told to refresh rather than being handed a misleading business error. No other endpoint in this system accepts a version field, and none should be invented.

### 2.9. The Engineering Posture Gate

Each facade package carries a derived gate, `engineering_posture`, whose value is one of `OPEN`, `RESTRICTED` or `FROZEN`. It is accompanied by two derived counters. `blocking_submittal_count` is the number of the package's shop-drawing submittals whose state is either `REVISION_REQUIRED` or `ESCALATED`. `open_critical_defect_count` is the number of the package's defect items whose `severity` is `CRITICAL` and whose `status` is either `OPEN` or `REMEDIATION_SUBMITTED`.

From those two counters the posture is derived as follows. The posture is `FROZEN` when any submittal of the package is in state `ESCALATED`, or when `open_critical_defect_count` is 2 or more. Otherwise the posture is `RESTRICTED` when `blocking_submittal_count` is 1 or more, or when `open_critical_defect_count` is exactly 1. Otherwise the posture is `OPEN`. A fresh package therefore opens at `OPEN` with both counters at 0; one submittal sitting in `REVISION_REQUIRED` with no defects yields `RESTRICTED`; one open critical defect yields `RESTRICTED`; two open critical defects yield `FROZEN`; and a single `ESCALATED` submittal yields `FROZEN` even when the package has no defects at all.

The posture is re-derived from scratch — never incremented or decremented in place — on every write that can change either input: every submittal review, resubmittal, reopen, escalation and revision; every mockup result; every field-test result; and every defect transition including creation, remediation submission, re-inspection (pass or fail) and waiver. One derivation pass always reaches a fixed point.

A `FROZEN` posture blocks five operations: releasing fabrication, advancing a panel lot through the shop, setting a zone's anchors, hanging a zone's panels and certifying a zone weather-tight. All five report `ERR_ENGINEERING_POSTURE_FROZEN` (HTTP 422). A `RESTRICTED` posture blocks nothing on its own — it is a reporting state that tells the project manager engineering attention is owed.

### 2.10. Ledger Invariants and Derived-Field Reconciliation

Three ledgers in this system must balance exactly after every operation that touches them, and each is fully re-derived on every such operation rather than adjusted incrementally.

The **glass lite ledger** on each order must satisfy two identities at all times. First, `committable_lites` must equal `allocated_lites` plus `breakage_stock_lites` plus `unallocated_lites`. Second, `breakage_stock_lites` must equal `available_stock_lites` plus `drawn_lites`. `committable_lites` is `received_lites` once the order's state is `RECEIVED` or `CLOSED`, and `ordered_lites` before that — lites may be committed to a release from the moment the order is placed, and the physical count supersedes the ordered count at receipt. `allocated_lites` is the sum of `lite_count` over every panel lot pointing at the order, in any `fabrication_status` whatsoever, because lots are never deleted. `breakage_stock_lites` is zero before receipt, because no physical stock exists to hold back, and at receipt becomes the received count multiplied by three percent and then **floored** to a whole lite — floored, never rounded. `drawn_lites` is the sum of `quantity_lites` over the order's breakage draws whose `status` is `DRAWN`; `available_stock_lites` is `breakage_stock_lites` less `drawn_lites`. `unallocated_lites` is `committable_lites` less `allocated_lites` less `breakage_stock_lites`. Breakage stock is reserved *ahead* of allocation: a release may consume only from `unallocated_lites` and never from `breakage_stock_lites`. Because the commitment base switches at receipt, a short shipment retroactively shrinks `unallocated_lites`, which may go negative; the negative figure is reported, not clamped.

The **zone crew-hour ledger** must satisfy `budget_crew_hours` equals `consumed_crew_hours` plus `remaining_crew_hours` after every crew-day posting and every void. `consumed_crew_hours` is the sum, over the zone's crew-day logs whose `status` is `POSTED`, of each log's `crew_size` multiplied by its `shift_hours`. `remaining_crew_hours` is the budget less the consumed figure and may go negative; an overrun is reported, not clamped. Voided logs are excluded from the sum entirely.

The **earned-value ledger** on the package — `certified_area_sqm`, `retention_held_cents` and `earned_value_certified_cents` — is re-derived from the current set of weather-tight zones on every certification and on every revert cascade, as specified in §3.9.

Derived fields on children are reconciled when a parent decision changes their basis. When the system decision is taken, every installation zone already registered against the package has its `thermal_movement_allowance_mm` and `deflection_limit_mm` recomputed against the newly chosen system type. When a crew-day log is voided, the surviving logs' `day_index` values are re-packed from 1 and the zone's `final_labor_cost_cents` is recomputed if the zone is currently weather-tight.

### 2.11. Two Independent Zone Axes and Cascade Semantics

An installation zone carries two status dimensions on the same row, and they advance independently. `install_status` runs `PLANNED` → `ANCHORS_SET` → `PANELS_HUNG` and tracks physical erection. `weather_status` runs `NOT_TIGHT` → `WEATHER_TIGHT`, can revert `WEATHER_TIGHT` → `REMEDIATION`, and can re-advance `REMEDIATION` → `WEATHER_TIGHT` any number of times. Hanging panels never touches `weather_status`; certifying weather-tightness never touches `install_status`. Neither axis has a terminal value: a zone is never finished in the sense that it refuses further transitions.

Retraction propagates in ordered hops, and every hop is a real mutation with its own `version` increment and `updated_at` refresh. Two originating events start the longest chain — a submittal returning for revision or escalating, and a coating revision that pushes a glass order's risk over the release threshold — and both are described in full in §3.2 and §3.4. The shape is always the same: releases are revoked, the revoked releases' lots are held, zones holding a newly held lot lose their weather-tight status, and the package's earned value and lifecycle state fall back accordingly. A failed field test starts a parallel chain that begins with a defect rather than a revocation. In every case the implementer must run *all* the hops; stopping after the first is the most common way to get this specification wrong.

The package's own lifecycle is a compound machine whose middle states are bubbled up from children rather than requested directly. `DESIGN_ASSIST` → `SYSTEM_SELECTED` is the only operator-driven forward transition until close-out; `SYSTEM_SELECTED` → `MOCKUP_QUALIFIED`, `MOCKUP_QUALIFIED` → `IN_FABRICATION`, `IN_INSTALLATION` → `WEATHER_TIGHT_ACHIEVED` and `IN_FABRICATION` → `IN_INSTALLATION` all fire as system events, and `WEATHER_TIGHT_ACHIEVED` → `IN_INSTALLATION` is a revert edge that makes the aggregate non-monotonic. `CLOSED_OUT` is the only terminal package state.

### 2.12. Order of Rejection

When a request violates more than one rule, exactly one error is returned: the violation that comes first in the following order. The ordering is normative — a reader who treats these as an unordered set of independent checks will return the wrong code in a large fraction of cases.

1. `X-User-Role` absent or empty — `ERR_MISSING_ROLE` (401). Applies to every endpoint except the clock-setting capability.
2. `X-User-Role` not among the roles the endpoint permits — `ERR_UNAUTHORIZED` (403). Applies to every endpoint that declares a role list.
3. `X-User-ID` absent or empty — `ERR_MISSING_USER` (401). Applies to the five operations named in §2.1: submittal seal, submittal review start, submittal review decision, defect re-inspection and crew-day posting.
4. A required input field absent, null, or of the wrong JSON type — `ERR_INVALID_REQUEST` (400). Applies to every write endpoint.
5. An enum field carrying a value outside its declared set, or a date or timestamp field that is not ISO 8601 — `ERR_INVALID_ENUM` (400). Applies to every write endpoint carrying an enum, date or timestamp field.
6. A numeric field outside its declared range — areas, spans, hours or rates at or below zero, lite or panel counts below 1, `tolerance_mm` at or below zero — `ERR_VALUE_OUT_OF_RANGE` (400). This range gate governs zone creation, glass-order placement, mockup booking, crew-day posting, breakage draws and rig registration; the same code is returned wherever else a declared numeric bound is violated, including package creation, laboratory registration, embed-survey opening, expedite tier selection, receipt counts, note burn-down, joint retuning and reservation panel counts.
7. `window_end` at or before `window_start` — `ERR_INVALID_WINDOW` (400). Applies to mockup booking, hoist reservation and laboratory registration.
8. Existence checks, in this internal order: the addressed facade package does not exist — `ERR_PACKAGE_NOT_FOUND` (404), on every endpoint carrying an `{id}` path parameter or a `*_id` body field; then the addressed submittal — `ERR_SUBMITTAL_NOT_FOUND` (404), on submittal endpoints and release creation; then the addressed glass order — `ERR_GLASS_ORDER_NOT_FOUND` (404), on glass-order endpoints, release creation and breakage draws; then the addressed zone — `ERR_ZONE_NOT_FOUND` (404), on zone endpoints, release creation, embed-survey opening, field-test scheduling and reservation creation, and also when the zone belongs to another package than the one named in the request; then the addressed panel lot or fabrication release — `ERR_LOT_NOT_FOUND` (404), on panel-lot and fabrication-release endpoints; then the addressed embed survey — `ERR_SURVEY_NOT_FOUND` (404), on embed-survey endpoints; then the addressed mockup test or field test — `ERR_TEST_NOT_FOUND` (404), on mockup-test and field-test endpoints; then the addressed defect item — `ERR_DEFECT_NOT_FOUND` (404), on defect-item endpoints; then the addressed hoist rig or reservation — `ERR_HOIST_NOT_FOUND` (404), on hoist endpoints and on panel hanging; then a referenced laboratory, crew-day log or breakage draw — `ERR_RESOURCE_NOT_FOUND` (404), on mockup booking, crew-day voiding and breakage-draw cancellation.
9. Stale parent version: `ERR_STALE_PACKAGE_VERSION` (412) on release creation, then `ERR_STALE_GLASS_ORDER_VERSION` (412) on breakage draws.
10. State checks, in this internal order: the entity's current state has no transition for this trigger — `ERR_INVALID_STATE` (409), on every action endpoint that declares a transition; then the entity is already in a terminal state — `ERR_TERMINAL_STATE` (409), on every action endpoint against an entity with terminal states, the terminal values being `APPROVED`, `VOIDED`, `CLOSED`, `CLOSED_OUT`, `PASSED`, `FAILED`, `SHIPPED`, `POURED`, `CONSUMED`, `CANCELLED` and `WAIVED`; then the zone's `install_status` does not match the transition's from-state — `ERR_ZONE_SEQUENCE_VIOLATION` (409), on anchor setting, panel hanging and weather-tight certification; then an escalated submittal resubmitted without a dispute reference — `ERR_DISPUTE_REF_REQUIRED` (409); then a coating revision attempted after receipt — `ERR_COATING_REVISION_AFTER_RECEIPT` (409).
11. Referential and segregation-of-duties checks, in this internal order: `ERR_SEAL_REQUIRED` (422), then `ERR_SEALER_CANNOT_REVIEW` (422), then `ERR_INSPECTOR_CONFLICT` (422), then `ERR_SEAL_INVALID` (422).
12. Release admissibility, in this internal order: `ERR_SUBMITTAL_NOT_APPROVED` (422), then `ERR_ENGINEERING_POSTURE_FROZEN` (422), then `ERR_MOCKUP_NOT_QUALIFIED` (422).
13. Embed sequencing: `ERR_EMBED_SURVEY_NOT_ACCEPTED` (422) on anchor setting, then `ERR_POUR_BEFORE_ACCEPTANCE` (422) on pour confirmation.
14. Safety checks, in this internal order: `ERR_ENGINEERING_POSTURE_FROZEN` (422) on anchor setting, panel hanging, weather-tight certification and panel-lot advancement; then `ERR_PANEL_LOTS_NOT_SHIPPED` (422); then `ERR_HOIST_WINDOW_INVALID` (422); then `ERR_NO_FIELD_TEST_EVIDENCE` (422); then `ERR_OPEN_CRITICAL_DEFECT` (422) on weather-tight certification and on package close-out; then `ERR_THERMAL_MOVEMENT_EXCEEDED` (422); then `ERR_DEFLECTION_LIMIT_UNSET` (422); then `ERR_WAIVER_NOT_PERMITTED` (422).
15. Capacity checks, in this internal order: `ERR_HOIST_WINDOW_CONFLICT` (409), then `ERR_GLASS_BALANCE_INSUFFICIENT` (422), then `ERR_LAB_CAPACITY_EXCEEDED` (409), then `ERR_BREAKAGE_STOCK_EXHAUSTED` (422), then `ERR_DRAW_QUANTITY_INVALID` (422).
16. Fiscal checks, in this internal order: `ERR_BILLING_EXCEEDS_CONTRACT` (422), then `ERR_GLASS_RISK_THRESHOLD_EXCEEDED` (422), then `ERR_CREW_DAY_DUPLICATE` (409), then `ERR_ZONES_NOT_WEATHER_TIGHT` (422), then `ERR_PUNCH_LIST_OPEN` (422).

Three consequences of that ordering are worth calling out because they are easy to get backwards. A zone still in `PLANNED` whose lots are unshipped reports the sequence violation, not the unshipped-lot error, because the zone-sequence check outranks the panel-lot readiness check. A release quoting an unapproved submittal against an order with insufficient glass reports the unapproved submittal, because release admissibility outranks capacity. And a certification attempt on a zone with an open critical defect that would also bill past the contract value reports the open critical defect, because safety outranks fiscal.

## 3. Business Logic & Workflows

### 3.1. Opening a Package and the Unitized-versus-Stick-Built Fork

A `CWProjectManager` opens the engagement by registering the facade package. The payload carries the contract scope `name`, the `floor_count` of building floors in scope (at least 1), the contracted `total_area_sqm` of curtain wall (greater than zero), the subcontract `contract_value_cents` (greater than zero), the `unit_rate_cents_per_sqm` at which certified area will be valued (greater than zero), the straight-time `base_labor_rate_cents_per_hour` for field crew (greater than zero), the `design_temp_delta_c` temperature swing in Celsius the facade must accommodate (greater than zero), and the contract `weather_tightness_deadline_date` as a `YYYY-MM-DD` UTC calendar date. A `system_type` value may appear in the payload, but it is not honoured at creation: the package always opens with `system_type` `UNDECIDED`, and the only thing that ever changes it is the system decision described below. The package opens in state `DESIGN_ASSIST` with `engineering_posture` `OPEN`, `blocking_submittal_count` and `open_critical_defect_count` at 0, `planned_shop_hours` and `planned_field_crew_size` at 0, `certified_area_sqm`, `earned_value_certified_cents`, `retention_held_cents` and `weather_tight_zone_count` all at 0, and `mockup_qualified` false.

Installation zones may be registered at any time, and the project manager typically lays out the whole elevation before the system decision is taken. Each zone names its parent package by `package_id` and carries the `floor_number` it serves (at least 1), an `elevation_label` of `NORTH`, `SOUTH`, `EAST` or `WEST`, the `area_sqm` of curtain wall in the zone (greater than zero), the `height_m` of the zone above grade (greater than zero), the vertical mullion `span_mm` in millimetres (at least 1), an `anchor_type` of `SLOTTED`, `PINNED` or `FIXED`, the `designed_joint_mm` movement joint width the shop drawings provide (greater than zero), the `planned_panel_count` of panels planned for the zone (at least 1), and the `budget_crew_hours` field-labor budget in person-hours (greater than zero). A new zone starts with `install_status` `PLANNED` and `weather_status` `NOT_TIGHT`, with `provisional_labor_cost_cents`, `final_labor_cost_cents`, `certified_line_cents`, `weather_tight_at` and `hang_completed_at` all null, `weather_tight_cycle_count` at 0, `consumed_crew_hours` at 0 and `remaining_crew_hours` equal to the budget.

**The system decision is the project's single most consequential fork.** A `CWProjectManager` fixes it by supplying `system_type` as either `UNITIZED` or `STICK_BUILT`; the transition is admissible only while the package's `system_type` is still `UNDECIDED` and its state is still `DESIGN_ASSIST`, and it moves the package `DESIGN_ASSIST` → `SYSTEM_SELECTED`. Choosing `UNITIZED` moves labour into the shop: `planned_shop_hours` becomes the contracted `total_area_sqm` multiplied by 0.55 shop hours per square metre, rounded half up to two decimal places, and `planned_field_crew_size` becomes 4 glaziers. Choosing `STICK_BUILT` moves labour into the field: `planned_shop_hours` becomes the contracted `total_area_sqm` multiplied by 0.18 shop hours per square metre, rounded half up to two decimals, and `planned_field_crew_size` becomes 8 glaziers. Both branches then reconcile every installation zone that already exists on the package, recomputing that zone's `thermal_movement_allowance_mm` and `deflection_limit_mm` against the newly fixed system type, and both bump the package's `version` by 1. Attempting the decision a second time, or on a package that has already left `DESIGN_ASSIST`, fails with `ERR_INVALID_STATE`.

Two derived dimensional limits sit on every zone, and both depend on the system decision. The **required thermal movement**, `thermal_movement_allowance_mm`, is computed from a full two-by-three-by-three matrix of system type, anchor detail and elevation band; all eighteen combinations are reachable and none collapses into another. Start with the multiplicative chain: the zone's `span_mm` multiplied by the thermal coefficient 0.0000234 per degree Celsius, multiplied by the package's `design_temp_delta_c`, multiplied by a system factor, multiplied by an anchor factor. The system factor is 1.00 when the package's `system_type` is `UNITIZED` and 1.25 when it is `STICK_BUILT`. The anchor factor is 1.30 for `SLOTTED`, 1.15 for `PINNED` and 1.00 for `FIXED`. To that product an elevation addend is then added — never before the multiplication: 0.00 mm when `height_m` is 20.0 or less, 1.50 mm when `height_m` is greater than 20.0 and 40.0 or less, and 3.00 mm when `height_m` is greater than 40.0. The sum is rounded half up to two decimal places. While the package's `system_type` is still `UNDECIDED` the field is null, and a zone with a null allowance cannot be certified weather-tight.

The **allowable mullion deflection**, `deflection_limit_mm`, is the zone's `span_mm` divided by a divisor selected by the same decision — 240 for `UNITIZED`, 175 for `STICK_BUILT` — rounded half up to two decimal places. A structural-deflection field test passes only when the measured deflection is strictly less than this limit; a measurement exactly equal to the limit fails.

A `CWDetailer` may re-detail a zone's movement joint at any point by supplying a new `designed_joint_mm`, which must be greater than zero. Re-detailing recomputes `thermal_movement_allowance_mm` against the current system and anchor configuration. This is a double-edged capability: retuning the joint *narrower* than the computed allowance is permitted at the time of the retune but will later block weather-tight certification, as §3.8 describes.

### 3.2. Delegated Design: Sealing, Review Rounds, Escalation and Note Burn-Down

A `CWDetailer` opens each submittal against its package by `package_id`, declaring a `submittal_type` of `SHOP_DRAWING`, `STRUCTURAL_CALCULATION`, `COATING_SPEC` or `MOCKUP_TEST_PLAN`, a `title`, and a `drawing_set_ref` identifying the current drawing or calculation set revision. The optional `delegated_design_scope` flag — false unless supplied — marks the submittal as carrying delegated design responsibility, which means it needs a professional seal before anyone may review it. Submittals open in state `SUBMITTED` with `revision_cycle` 1, `open_notes_count` 0, and `sealed_by_user_id`, `seal_license_no`, `sealed_at`, `reviewed_by_user_id`, `review_decision` and `escalation_ref` all null.

Sealing is the `DelegatedEngineer`'s only write capability. The payload carries the engineer's professional `seal_license_no`; the server records that number, sets `sealed_by_user_id` to the acting `X-User-ID` and stamps `sealed_at` from the logical clock. A seal request with no licence number, or one aimed at a submittal that already carries a seal for its current `revision_cycle`, is rejected with `ERR_SEAL_INVALID`. Note that sealing does not change the submittal's state — a sealed submittal is still `SUBMITTED`.

Review begins when an `ArchitectOfRecord` starts it, moving the submittal `SUBMITTED` → `UNDER_REVIEW`. Two gates guard that step. If the submittal's `submittal_type` is `STRUCTURAL_CALCULATION`, or its `delegated_design_scope` is true, then `sealed_by_user_id` must not be null; an unsealed delegated-design set is refused with `ERR_SEAL_REQUIRED`. And segregation of duties is absolute: if the acting `X-User-ID` equals the submittal's `sealed_by_user_id`, the request is refused with `ERR_SEALER_CANNOT_REVIEW`. The same sealer-versus-reviewer check is applied again when the review decision is recorded, and again on the reopen edge.

Recording the review decision is a four-way branch on the payload's `decision` field, and each branch carries the same specification weight. All four set `reviewed_by_user_id` to the acting `X-User-ID`, bump the submittal's `version` by 1, and require the submittal to be in `UNDER_REVIEW`.

- `APPROVED` moves the submittal `UNDER_REVIEW` → `APPROVED`, sets `review_decision` to `APPROVED`, and forces `open_notes_count` to 0. `APPROVED` is terminal: the submittal accepts no further transitions.
- `APPROVED_AS_NOTED` moves the submittal `UNDER_REVIEW` → `APPROVED_AS_NOTED` and requires the payload's `notes_count` to be at least 1; `open_notes_count` becomes exactly that `notes_count`, and `review_decision` becomes `APPROVED_AS_NOTED`. This branch is the divergent sibling of `APPROVED`: fabrication may be released against an approved-as-noted set, but the package cannot close out until the notes have been burned down to zero. `APPROVED_AS_NOTED` is *not* terminal.
- `REVISION_REQUIRED` while the submittal's `revision_cycle` is 2 or less moves it `UNDER_REVIEW` → `REVISION_REQUIRED` and sets `review_decision` to `REVISION_REQUIRED`.
- `REVISION_REQUIRED` while the submittal's `revision_cycle` is 3 or more moves it `UNDER_REVIEW` → `ESCALATED` instead, sets `review_decision` to `REVISION_REQUIRED`, and records the payload's `escalation_ref` as the delegated-design dispute reference when one is supplied. The boundary is exact: a third round (`revision_cycle` 2) still returns for revision, a fourth (`revision_cycle` 3) escalates.

Both revision branches — the `REVISION_REQUIRED` one and the `ESCALATED` one — then run **the same four-hop revocation cascade**, and both must run all four hops:

1. Every fabrication release whose authorising submittal is this submittal and whose state is `RELEASED` transitions to `REVOKED` with `revoked_reason` `SUBMITTAL_REVISION`.
2. Caused by hop 1: every panel lot belonging to each revoked release whose `fabrication_status` is `BATCHED` or `GLAZED` records that value into `status_before_hold` and transitions to `ON_HOLD` with `hold_reason` `SUBMITTAL_REVISION`. Lots already `SHIPPED` are untouched.
3. Caused by hop 2: every zone that now holds an `ON_HOLD` lot and whose `weather_status` is `WEATHER_TIGHT` reverts to `weather_status` `REMEDIATION`, and its `weather_tight_at` is cleared.
4. Caused by hop 3: the package's `weather_tight_zone_count` decrements, its `certified_area_sqm`, `earned_value_certified_cents` and `retention_held_cents` recompute over the surviving weather-tight zones, and a package sitting in `WEATHER_TIGHT_ACHIEVED` reverts to `IN_INSTALLATION`.

Both branches also recompute `blocking_submittal_count` and `engineering_posture` on the package. The escalation branch differs in one respect worth stating explicitly: because any `ESCALATED` submittal forces the posture to `FROZEN`, escalation additionally halts release, shop advancement, anchor setting, panel hanging and certification across the entire package, whereas a plain `REVISION_REQUIRED` (with no critical defects and no other escalation) leaves the posture at `RESTRICTED`, which blocks nothing.

Resubmittal is the cycle edge and belongs to the `CWDetailer`. From `REVISION_REQUIRED` the submittal returns to `SUBMITTED`: `revision_cycle` increments by 1, `drawing_set_ref` is replaced with the value in the payload, and `sealed_by_user_id`, `seal_license_no` and `sealed_at` are all cleared, because a new drawing set requires a new seal. From `ESCALATED` the submittal likewise returns to `SUBMITTED` with `revision_cycle` incremented by 1 and the same three seal fields cleared — but only when the payload carries a non-empty `dispute_resolution_ref`. An escalated submittal resubmitted without that reference is refused with `ERR_DISPUTE_REF_REQUIRED`. Either resubmittal recomputes the package's `blocking_submittal_count` and `engineering_posture`, which is how a package escapes `FROZEN`.

Two capabilities exist on the approved-as-noted path. An `ArchitectOfRecord` may **reopen** a submittal, dragging it `APPROVED_AS_NOTED` → `UNDER_REVIEW` while its `open_notes_count` is at least 1 and while the acting `X-User-ID` differs from `sealed_by_user_id`. The payload's `reopen_reason` is stored; `review_decision` remains `APPROVED_AS_NOTED` until a new decision is recorded; the package's `engineering_posture` is recomputed but does not change on this edge, because `UNDER_REVIEW` is not one of the blocking states. This re-entry edge is precisely what lets a later `REVISION_REQUIRED` decision revoke fabrication releases that have already been issued against a live package. Separately, an `ArchitectOfRecord` may **burn down notes** on an `APPROVED_AS_NOTED` submittal by supplying `notes_closed`, which reduces `open_notes_count` by that many; `open_notes_count` never falls below 0, a negative `notes_closed` is refused with `ERR_VALUE_OUT_OF_RANGE`, and a burn-down aimed at a submittal in any other state is refused with `ERR_INVALID_STATE`. `VOIDED` is the submittal machine's other terminal state alongside `APPROVED`.

### 3.3. Qualifying the System: Mockup Chambers and Their Invoices

Performance mockups are run at accredited laboratories, which a `CWProjectManager` registers with a `name`, a `chamber_capacity` giving the number of test chambers that may be occupied at the same instant (at least 1), and an `accreditation_ref`. As noted in §2.4, a laboratory is an immutable reference row with no `version` and no update path.

Booking a mockup test is shared between `CWProjectManager` and `QCInspector`. The payload names the package by `package_id` and the laboratory by `test_lab_id`, and gives `window_start` (inclusive) and `window_end` (exclusive) for the chamber occupation, plus `chambers_required`, the number of chambers held for the whole window (at least 1). A first attempt leaves `retest_of_test_id` null and `attempt_no` at its default of 1; a retest names the failed test it re-runs through `retest_of_test_id` — which points at another mockup test and resolves the self-referential retest chain — and carries an `attempt_no` of 2 or more, attempts of 2 or more being the ones that bear a retest surcharge. A window whose `window_end` is at or before its `window_start` is refused with `ERR_INVALID_WINDOW`.

Chamber capacity is shared across the laboratory's whole book, compared on **half-open** intervals. Sum `chambers_required` over every mockup test of that laboratory whose state is `SCHEDULED` and whose own half-open window from `window_start` up to but not including `window_end` intersects the requested window; add the newly requested `chambers_required`; and if the total exceeds the laboratory's `chamber_capacity`, refuse the booking with `ERR_LAB_CAPACITY_EXCEEDED`. Two windows that merely touch at an endpoint do not intersect, so a test ending at noon and a test starting at noon can both be booked against a single-chamber laboratory.

The invoice is priced at booking time and re-priced when the result is recorded, in four ordered stages with a deliberate trap in the middle. First, `chamber_hours` is the elapsed time from `window_start` to `window_end` expressed in hours and rounded **up** to a whole hour, multiplied by `chambers_required`. Second, `invoice_subtotal_cents` is a base laboratory fee of 480,000 cents plus `chamber_hours` multiplied by a chamber-hour rate of 21,500 cents. Third, `surcharge_cents` is zero whenever `retest_of_test_id` is null; otherwise it is `invoice_subtotal_cents` multiplied by a tier rate and rounded half up to whole cents, where the tier rate is 0.02 when the subtotal is 600,000 cents or less, 0.04 when the subtotal is 800,000 cents or less, 0.06 when the subtotal is 2,000,000 cents or less, and 0.10 above that. Fourth, `invoice_cents` is `invoice_subtotal_cents` plus `surcharge_cents`. **The tier is selected from the stage-two subtotal alone.** It must never be re-selected from `invoice_cents` after the surcharge has been added, even in the case where adding the surcharge pushes the total across the next tier ceiling.

A `QCInspector` records the result, moving the test out of `SCHEDULED`. The payload supplies all three measurements: `water_penetration_observed`, the measured `air_infiltration_cfm`, and the measured `structural_deflection_mm` at design pressure. The test reaches `PASSED` only when all three conditions hold together — no water penetration was observed, the air infiltration is strictly less than 0.06 cfm, and the mullion deflection is strictly less than 19.00 mm. If any one of the three fails, the test reaches `FAILED`. Both outcomes stamp the three measurements and `result_recorded_at`, and both are terminal.

Passing is what qualifies the package: it sets `mockup_qualified` to true and, when the package is sitting in `SYSTEM_SELECTED`, bubbles it `SYSTEM_SELECTED` → `MOCKUP_QUALIFIED`. Failing raises a defect automatically — a defect item with `origin` `MOCKUP_TEST`, `severity` `CRITICAL`, `package_id` copied from the test, `mockup_test_id` pointing at the test, `zone_id` left null because a mockup defect is package-level rather than zone-level, `raised_by_user_id` set to the acting `X-User-ID`, and `status` `OPEN` — and then recomputes the package's `open_critical_defect_count` and `engineering_posture`. One failed mockup therefore drives the package to `RESTRICTED`; two open critical defects drive it to `FROZEN`.

### 3.4. Glass Procurement: Lead-Time Risk, Coating Re-Fires, Receipt and Breakage Stock

`GlazingProcurement` places each glass order against its package by `package_id`, naming the `supplier_name` glass fabricator, the current low-e `coating_code`, the `quoted_lead_time_days` the supplier quotes from order placement (at least 1), and the `ordered_lites` count (at least 1). The optional `expedite_authorized` flag — false unless supplied — records that an expedite premium has been authorised commercially. Orders open in state `ORDERED` with `expedite_tier` 0, `coating_revision_count` 0, `re_fire_required` false, `received_lites` 0 and `breakage_stock_lites` 0, and their procurement risk is scored immediately.

**Procurement risk** is the mechanism that keeps a late or troubled glass order from authorising fabrication. Each order carries `risk_score` on a 0.00-to-100.00 scale, the `effective_lead_days` the score was computed against, the `risk_variant` that produced it, a boolean `risk_flag`, and `last_risk_computed_at` stamped from the logical clock. Two variants exist, and the variant is re-selected from the order's own counters on every scoring. The `NOMINAL` variant applies when `expedite_tier` is 0 and `coating_revision_count` is 0: `effective_lead_days` is the `quoted_lead_time_days` plus a re-fire penalty of 21 days for each coating revision recorded, and the judgement horizon is 90 days. The `EXPEDITE_ADJUSTED` variant applies when `expedite_tier` is 1 or more, or `coating_revision_count` is 1 or more: `effective_lead_days` is the `quoted_lead_time_days`, plus 21 days per coating revision, less 10 recovered days for each expedite tier bought, with the result floored at zero if the credits would take it negative, and the judgement horizon is the shorter 45 days. The expedited variant therefore diverges from the nominal one in two terms at once — it credits the days bought *and* judges the surviving float against a nearer horizon.

The scoring tail is shared by both variants, evaluated against the variant's own `effective_lead_days` and horizon. Take `days_to_deadline` as the whole number of days from the current logical-clock calendar date to the package's `weather_tightness_deadline_date`. The **lead component** is `effective_lead_days` divided by `days_to_deadline` — or divided by 1 when `days_to_deadline` is below 1 — clamped into the range 0 to 1 inclusive. The **float** is `days_to_deadline` less `effective_lead_days`, and the **calendar component** is 1 less the float divided by the horizon, clamped into the range 0 to 1 inclusive. The **coating component** is `coating_revision_count` divided by the maximum tolerated 2 revisions, clamped into the range 0 to 1 inclusive. Weight the lead component at 0.45, the calendar component at 0.35 and the coating component at 0.20; sum the three weighted terms; multiply by 100; and round half up to two decimal places to obtain `risk_score`. The components themselves are never rounded before weighting. `risk_flag` is true when `risk_score` is at or above the release threshold of 70.00 — exactly 70.00 sets the flag, 69.99 does not.

Production starts when `GlazingProcurement` advances the order `ORDERED` → `IN_PRODUCTION`. Two things can happen during production. Buying an expedite records a new `expedite_tier` of 1 or 2 (values outside that set are refused as out of range), switches `risk_variant` to `EXPEDITE_ADJUSTED` and rescores the order, without changing its state. A **coating revision** is more disruptive: it is the cycle edge that sends the order back `IN_PRODUCTION` → `ORDERED` for a re-fire. The payload carries the new `coating_code` and `re_fire_required`; the server increments `coating_revision_count` by 1, replaces `coating_code`, sets `re_fire_required` to true, switches `risk_variant` to `EXPEDITE_ADJUSTED`, and recomputes `risk_score`, `effective_lead_days`, `risk_flag` and `last_risk_computed_at`. A coating revision attempted once the order is `RECEIVED` or `CLOSED` is refused with `ERR_COATING_REVISION_AFTER_RECEIPT` — the glass is already on site and cannot be re-specified.

When and only when that recomputation **flips `risk_flag` to true**, the coating revision runs a two-hop cascade: first, every fabrication release drawing on this order whose state is `RELEASED` transitions to `REVOKED` with `revoked_reason` `GLASS_RE_FIRE`; second, caused by that, every panel lot of each revoked release whose `fabrication_status` is `BATCHED` or `GLAZED` records that value into `status_before_hold` and transitions to `ON_HOLD` with `hold_reason` `GLASS_RE_FIRE`. Any zone that was `WEATHER_TIGHT` and now holds a held lot reverts to `weather_status` `REMEDIATION`, with the package-level earned-value consequences described in §3.9.

Receipt advances the order `IN_PRODUCTION` → `RECEIVED`. The payload carries `received_lites`, which must be at least 1. On receipt the commitment base switches from `ordered_lites` to `received_lites`, `breakage_stock_lites` is set to three percent of `received_lites` floored to a whole lite, and `available_stock_lites` and `unallocated_lites` are recomputed. A short shipment therefore retroactively reduces the unallocated balance, exactly as §2.10 describes. A read-only rescoring capability, shared between `GlazingProcurement` and `CWProjectManager`, re-derives `risk_score` against the current logical clock without changing the order's state, re-selecting the variant from the current `expedite_tier` and `coating_revision_count`.

The order reaches its terminal `CLOSED` state as a system event, not by request: once the order has at least one panel lot, every panel lot of the order has reached `fabrication_status` `SHIPPED`, and `unallocated_lites` has fallen to 0, the order transitions `RECEIVED` → `CLOSED`.

**Breakage replacement stock** is the small reserve held back at receipt against field breakage, coating defects and mockup consumption. `GlazingProcurement` draws from it by naming the order through `glass_order_id`, the lot whose broken lite is being replaced through `panel_lot_id`, the `quantity_lites` to draw (at least 1), a `reason` of `FIELD_BREAKAGE`, `COATING_DEFECT`, `HANDLING_DAMAGE` or `MOCKUP_CONSUMPTION`, and — because this write is guarded by optimistic concurrency — `expected_glass_order_version`. Draws are created with `status` `DRAWN` and `cancelled_reason` null. Two capacity limits apply in order: a draw for more lites than the order's `available_stock_lites` is refused with `ERR_BREAKAGE_STOCK_EXHAUSTED`, and a draw whose `quantity_lites` exceeds the `lite_count` of the referenced panel lot is refused with `ERR_DRAW_QUANTITY_INVALID`, because a replacement draw cannot exceed the glass content of the lot it repairs. A `quantity_lites` below 1 is caught earlier, as an out-of-range numeric value.

Cancelling a draw is a compensating action. It moves the draw `DRAWN` → `CANCELLED`, stores the free-text `cancelled_reason` from the payload, and recomputes the order's `drawn_lites` and `available_stock_lites` so that `breakage_stock_lites` equals `available_stock_lites` plus `drawn_lites` again with no drift whatsoever. Because it changes the order's balances, the cancellation bumps both the draw's `version` and the glass order's `version` by 1. `CANCELLED` is terminal for a draw.

### 3.5. Releasing Fabrication and Driving Panel Lots Through the Shop

A fabrication release is the cross-aggregate authorisation that lets the shop cut metal, and only a `CWProjectManager` may issue one. The payload names the package by `package_id`, the approved submittal authorising the work by `submittal_id`, the glass the lots will draw from by `glass_order_id`, and the `zone_ids` array of installation zones the release covers, each of which must belong to the same package as the release itself. It also carries `panels_per_zone`, the number of panels fabricated per covered zone (at least 1), and `lites_per_panel`, the glass lites consumed per panel (at least 1). The write is guarded by `expected_package_version` as described in §2.8.

Five business gates are evaluated in the order fixed by §2.12. The referenced submittal's state must be `APPROVED` or `APPROVED_AS_NOTED`; anything else — including `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUIRED`, `ESCALATED` or `VOIDED` — is refused with `ERR_SUBMITTAL_NOT_APPROVED`. The package's `engineering_posture` must not be `FROZEN`, or the release is refused with `ERR_ENGINEERING_POSTURE_FROZEN`. The package's `mockup_qualified` must be true — meaning some mockup test of the package has reached `PASSED` — or the release is refused with `ERR_MOCKUP_NOT_QUALIFIED`. The glass balance must cover the request: the total requested panel count across the covered zones, multiplied by the standard glazing content of two lites per panel, must not exceed the order's `unallocated_lites`, or the release is refused with `ERR_GLASS_BALANCE_INSUFFICIENT`. And the referenced order's `risk_flag` must be false; an order at or above the 70.00 risk threshold refuses the release with `ERR_GLASS_RISK_THRESHOLD_EXCEEDED`.

A successful release is created in state `RELEASED` with `released_at` stamped from the logical clock, `revoked_reason` null, and `system_type_at_release` pinned as a copy of the package's `system_type` — either `UNITIZED` or `STICK_BUILT` — so that the shop's basis is frozen even if the package is later re-planned. It then creates **one panel lot per covered zone**, in the order the `zone_ids` array listed them, and sets `lot_count` to the number of lots created. Each lot is a system-populated row: `release_id` points at the release, `glass_order_id` at the order, `zone_id` at the covered zone, `panel_count` is a copy of the release's `panels_per_zone`, `lite_count` is that `panel_count` multiplied by the release's `lites_per_panel`, `fabrication_status` opens at `BATCHED`, and `hold_reason`, `status_before_hold` and `shipped_at` are all null. Each lot's human-readable `lot_code` is derived by joining the literal prefix `LOT-F`, the covered zone's `floor_number`, a hyphen, and the zone's `elevation_label` — so a lot for the north elevation of floor 12 reads `LOT-F12-NORTH`. Creating the first release of a package bubbles the package `MOCKUP_QUALIFIED` → `IN_FABRICATION`.

A release also **un-holds what a previous revision froze**. When a new release covers a zone whose lots are sitting `ON_HOLD` with `hold_reason` `SUBMITTAL_REVISION`, each such lot returns to the value recorded in its `status_before_hold`: a lot held from `BATCHED` transitions `ON_HOLD` → `BATCHED`, and a lot held from `GLAZED` transitions `ON_HOLD` → `GLAZED`. In both cases the lot's `release_id` is re-pointed to the new release and its `hold_reason` and `status_before_hold` are cleared. This is why release creation cannot be guarded by state alone and needs the stale-version check: superseding a release is legitimate, so only a current view of the package makes the write safe.

Lots move through the shop under the `FieldSuperintendent`, who supplies a `to_status` of `GLAZED` or `SHIPPED`; any other value is refused as an invalid enum. `BATCHED` → `GLAZED` requires the lot's own `fabrication_status` to be `BATCHED`, the lot's fabrication release to still be `RELEASED`, and the lot's glass order to have reached `RECEIVED` — glass cannot be glazed into a panel before it is physically on site. `GLAZED` → `SHIPPED` requires the lot to be `GLAZED` and its release still `RELEASED`, and stamps `shipped_at` from the logical clock. Shipping also triggers two bubble-up closures: when every lot of the release has reached `SHIPPED`, the release transitions `RELEASED` → `CLOSED`; and when every lot of the glass order has reached `SHIPPED` and the order's `unallocated_lites` is 0, the order transitions `RECEIVED` → `CLOSED`. `SHIPPED` is terminal for a lot, and a `FROZEN` posture blocks shop advancement entirely.

Revocation runs the other way. When a release is revoked — whether by a submittal revision or by a glass re-fire — its state moves `RELEASED` → `REVOKED`, `revoked_reason` is set to `SUBMITTAL_REVISION` or `GLASS_RE_FIRE` according to which cascade originated it, and every lot of the release with `fabrication_status` `BATCHED` or `GLAZED` is put `ON_HOLD` after recording its prior value in `status_before_hold`. A lot going `ON_HOLD` additionally reverts its own zone to `weather_status` `REMEDIATION` if that zone was `WEATHER_TIGHT`. `REVOKED` and `CLOSED` are both terminal for a release.

### 3.6. Embed Coordination, Hoisting and the Installation Sequence

Anchor embeds must be surveyed and poured before a single panel bracket can be set, and that survey belongs to the `StructuralContractor` rather than to the curtain wall trade — the detailer lays the embeds out, the concrete contractor confirms where they actually ended up. Opening a survey against a zone takes the zone from the request path and carries the `embed_layout_ref` drawing reference issued to the structural contractor, the `planned_anchor_count` of embeds planned in the zone (at least 1), and optionally a `tolerance_mm` acceptance tolerance for as-built deviation, which defaults to 25.0 mm and must be greater than zero. The survey opens in state `PENDING_SURVEY` with `surveyed_anchor_count`, `max_deviation_mm` and `surveyed_by_user_id` null, `survey_attempt_count` 0 and `poured_at` null.

Recording an as-built survey supplies `surveyed_anchor_count` and `max_deviation_mm`. Every survey attempt, whatever its outcome, stamps those two values, sets `surveyed_by_user_id` to the acting `X-User-ID` and increments `survey_attempt_count` by 1. The outcome is `ACCEPTED` only when both conditions hold: the `surveyed_anchor_count` equals the `planned_anchor_count`, and the `max_deviation_mm` is strictly less than the survey's `tolerance_mm`. A deviation exactly equal to the tolerance rejects. Otherwise the outcome is `REJECTED`. A rejected survey may be re-surveyed after embed remediation, and the re-survey either moves `REJECTED` → `ACCEPTED` under the same two conditions or self-loops `REJECTED` → `REJECTED`, closing the revision cycle. Confirming the pour then moves the survey `ACCEPTED` → `POURED`, recording `poured_at` from the payload; a pour confirmation attempted while the survey is `PENDING_SURVEY` or `REJECTED` is refused with `ERR_POUR_BEFORE_ACCEPTANCE`, because concrete cannot legitimately be placed over embeds nobody has accepted. `POURED` is terminal.

Hoisting capacity is registered by the `FieldSuperintendent`. Each rig names its package by `package_id` and carries a site `rig_code`, a `rig_kind` of `MAST_CLIMBER`, `TOWER_CRANE` or `MONORAIL`, a `capacity_panels_per_shift` figure for how many panels it can hoist per shift (at least 1), and optionally `changeover_buffer_minutes`, the minimum idle time required between two reservations on that rig, which defaults to three quarters of an hour — 45 minutes — and may not be negative. Rigs are registered with `status` `ACTIVE`; `OUT_OF_SERVICE` is the alternative value.

Reserving a rig names it by `rig_id` and the served zone by `zone_id`, and gives `window_start` (inclusive), `window_end` (exclusive) and the `planned_panel_count` of panels planned for the window (at least 1). A reservation stores its buffer-expanded blocked interval alongside the raw window: `blocked_from` is `window_start` pulled back by the rig's `changeover_buffer_minutes`, and `blocked_until` is `window_end` pushed out by the same amount. Occupancy is exclusive: the **requested raw window**, from `window_start` up to but not including `window_end`, must not intersect the stored interval from `blocked_from` up to but not including `blocked_until` of any reservation on the same rig whose `status` is `RESERVED` or `CONSUMED`. Note carefully that only the stored intervals are buffer-expanded — the requested window is never expanded a second time. With a 45-minute buffer, a request starting half an hour after an existing window ends conflicts and is refused with `ERR_HOIST_WINDOW_CONFLICT`, while a request starting exactly 45 minutes after that window ends is accepted. A reservation whose `window_end` is at or before its `window_start` is refused as an invalid window. Cancelling a reservation moves it `RESERVED` → `CANCELLED`, stores the free-text `cancelled_reason`, and stops its blocked interval from obstructing new bookings — a previously conflicting reservation becomes bookable immediately. `CANCELLED` and `CONSUMED` are both terminal for a reservation.

With embeds poured, the `FieldSuperintendent` sets a zone's anchors, advancing `install_status` `PLANNED` → `ANCHORS_SET`. The zone must have an embed survey in state `POURED`, or the request is refused with `ERR_EMBED_SURVEY_NOT_ACCEPTED`; an accepted-but-unpoured survey is not sufficient. The package's `engineering_posture` must not be `FROZEN`. The first zone of a package to reach `ANCHORS_SET` bubbles the package `IN_FABRICATION` → `IN_INSTALLATION`.

Hanging panels advances `install_status` `ANCHORS_SET` → `PANELS_HUNG` and is the busiest gate in the system. The payload carries `hoist_reservation_id`, naming the reservation the hang will consume. Four conditions must hold. The zone must be in `ANCHORS_SET`, or the request fails with `ERR_ZONE_SEQUENCE_VIOLATION`. The package's `engineering_posture` must not be `FROZEN`. The zone must have at least one panel lot and **every** panel lot pointing at the zone must have reached `fabrication_status` `SHIPPED` — a zone with no lots at all, or with a single lot still `BATCHED`, `GLAZED` or `ON_HOLD`, is refused with `ERR_PANEL_LOTS_NOT_SHIPPED`. And the referenced reservation must have `status` `RESERVED`, must belong to this same zone, and the current logical-clock instant must fall inside its half-open window — at or after `window_start` and strictly before `window_end`; otherwise the request is refused with `ERR_HOIST_WINDOW_INVALID`. On success the zone stamps `hang_completed_at` from the logical clock, the referenced reservation transitions `RESERVED` → `CONSUMED`, and the zone's forward-looking labor estimate is written as described in §3.7. Hanging panels never touches `weather_status`.

### 3.7. Crew Days and the Two Faces of Field Labor Cost

Every zone carries two labor cost figures that are computed by different rules from different inputs, and the divergence between them is the project's field-productivity signal.

The **forward-looking estimate**, `provisional_labor_cost_cents`, is stamped at the moment panels finish hanging. Begin with a productivity rate that follows the system decision: 12 panels per crew day when the package's `system_type` is `UNITIZED`, and 6 panels per crew day when it is `STICK_BUILT` — a unitized panel goes up roughly twice as fast because the shop did the assembly. Divide the zone's `planned_panel_count` by that rate and round **up** to a whole number of crew days. Multiply those crew days by the package's `planned_field_crew_size` and by a standard shift of 8.0 hours to obtain the planned hours. Multiply the planned hours by the package's `base_labor_rate_cents_per_hour` and round half up to whole cents. This variant deliberately charges every hour at straight time and ignores elevation entirely: at hang time no crew-day logs exist yet, so neither overtime nor a high-elevation factor can be known.

The **chronological actual**, `final_labor_cost_cents`, is computed from what the crew actually did. A `FieldSuperintendent` posts one crew day per working day against a zone, supplying the `work_date` as a `YYYY-MM-DD` UTC calendar date, the `crew_size` of glaziers on the wall that day (at least 1), the `shift_hours` worked per crew member (greater than zero and no more than 16), and the `panels_installed` that day (zero or more). Logs are created with `status` `POSTED`. A second posted log for the same zone and the same `work_date` is refused with `ERR_CREW_DAY_DUPLICATE`. Each posting assigns `day_index`, the 1-based chronological position of the log among the zone's `POSTED` logs ordered by `work_date` ascending and then by `created_at` ascending, and derives two person-hour splits: `straight_person_hours` is the lesser of `shift_hours` and the 8.0-hour standard shift, multiplied by `crew_size`; `overtime_person_hours` is the excess of `shift_hours` over 8.0 — or zero when there is no excess — multiplied by `crew_size`. Posting also rolls the zone's crew-hour ledger described in §2.10.

Each log's own `day_cost_cents` is derived as follows. Its straight person-hours are charged at the package's `base_labor_rate_cents_per_hour`; its overtime person-hours are charged at that same rate multiplied by an overtime multiplier of 1.5; the two amounts are added to give the day's base. That base is then multiplied by an elevation factor of 1.15 when the zone's `height_m` is strictly greater than 20.0 metres, and by 1.00 otherwise. The product is rounded half up to whole cents and stored as `day_cost_cents`.

`final_labor_cost_cents` is stamped when a zone is certified weather-tight, and re-stamped whenever a crew day of an already-weather-tight zone is voided. It is computed by walking the zone's crew-day logs whose `status` is `POSTED` in `work_date` ascending and then `created_at` ascending order — never in `id` order — computing each day's `day_cost_cents` exactly as above, and summing those already-rounded per-day amounts. Because each day is rounded to whole cents *before* it enters the sum, the zone total must equal the sum of the surviving logs' persisted `day_cost_cents` values exactly. `VOIDED` logs contribute nothing.

Voiding is the compensating action for a mis-posted day. It moves the log `POSTED` → `VOIDED`, storing the payload's `void_reason`. The voided log's `day_index` is cleared to null, and the surviving `POSTED` logs of the zone are re-indexed from 1 in the same `work_date`-then-`created_at` order, so the index sequence never leaves a gap. The zone's `consumed_crew_hours` and `remaining_crew_hours` are recomputed so that the budget identity still holds, and when the zone's `weather_status` is currently `WEATHER_TIGHT` its `final_labor_cost_cents` is recomputed over the survivors as well. Voiding bumps both the log's `version` and the zone's `version` by 1. `VOIDED` is terminal for a crew-day log.

### 3.8. Field Testing, Defects and Weather-Tight Certification

Field testing is the `QCInspector`'s domain. A test is scheduled against a zone with a `test_kind` of `WATER_AAMA_501_2` for the AAMA 501.2 spray test, `AIR_INFILTRATION` for air leakage, or `STRUCTURAL_DEFLECTION` for mullion deflection at design pressure; a `scheduled_for` instant; and optionally an `attempt_no` for this kind in this zone, which defaults to 1 and must be at least 1. Scheduling a `STRUCTURAL_DEFLECTION` test on a zone whose package still has `system_type` `UNDECIDED` is refused with `ERR_DEFLECTION_LIMIT_UNSET`: without a system decision the zone's `deflection_limit_mm` is null, so there is no pass/fail line to test against. Tests open in state `SCHEDULED` with `water_penetration_observed`, `measured_air_leakage_cfm`, `measured_deflection_mm`, `outcome_reason`, `recorded_by_user_id` and `result_recorded_at` all null.

Recording a result requires the test to still be `SCHEDULED` and the zone's `install_status` to be `PANELS_HUNG` — a zone whose panels are not up cannot be tested, and an attempt against a zone that has not reached `PANELS_HUNG` is refused as an invalid state with `ERR_INVALID_STATE`. The payload carries only the measurement its kind needs: `water_penetration_observed` for a water test, `measured_air_leakage_cfm` for an air test (in cfm per square foot), `measured_deflection_mm` for a deflection test. If the measurement the `test_kind` requires is absent, the request is refused as an invalid request. Both outcomes set `recorded_by_user_id` to the acting `X-User-ID` and stamp `result_recorded_at` from the logical clock, and both are terminal.

The pass line differs per kind, and equality always fails. A `WATER_AAMA_501_2` test reaches `PASSED` when `water_penetration_observed` is false. An `AIR_INFILTRATION` test reaches `PASSED` when `measured_air_leakage_cfm` is strictly less than the 0.06 cfm air-leakage limit. A `STRUCTURAL_DEFLECTION` test reaches `PASSED` when `measured_deflection_mm` is strictly less than the zone's computed `deflection_limit_mm`. A passing result sets `outcome_reason` to `WITHIN_TOLERANCE`.

A failing result sets `outcome_reason` according to the kind — `WATER_PENETRATION` for observed water, `AIR_LEAKAGE_EXCEEDED` for air leakage at or beyond the limit, `DEFLECTION_EXCEEDED` for deflection at or beyond the limit — and then runs a four-hop cascade, all four hops of which must fire:

1. A defect item is created with `origin` `FIELD_TEST`, `field_test_id` pointing at the test, `zone_id` copied from the test, `package_id` taken from the zone's package, `status` `OPEN`, and `raised_by_user_id` set to the acting `X-User-ID`. Its `severity` is `CRITICAL` when the outcome was `WATER_PENETRATION` or `DEFLECTION_EXCEEDED`, and `MAJOR` when the outcome was `AIR_LEAKAGE_EXCEEDED` — leaking air is a defect, but water intrusion and structural overdeflection are safety matters.
2. Caused by hop 1: the package's `open_critical_defect_count` and `engineering_posture` are recomputed, so a single critical field-test defect drives the package to `RESTRICTED` and a second one to `FROZEN`.
3. Caused by hop 1: if the zone's `weather_status` was `WEATHER_TIGHT` it reverts to `REMEDIATION`, and both `weather_tight_at` and `certified_line_cents` are cleared.
4. Caused by hop 3: the package's `weather_tight_zone_count` decrements, its `certified_area_sqm`, `earned_value_certified_cents` and `retention_held_cents` recompute, and a package sitting in `WEATHER_TIGHT_ACHIEVED` reverts to `IN_INSTALLATION`.

Defects also arrive by hand. A `QCInspector` or an `ArchitectOfRecord` raises one against a package by `package_id`, optionally naming a `zone_id` (left null for package-level mockup defects), optionally naming the `field_test_id` or `mockup_test_id` that raised it according to `origin`, and supplying an `origin` of `MOCKUP_TEST`, `FIELD_TEST` or `PUNCH_LIST`, a `severity` of `CRITICAL`, `MAJOR` or `MINOR`, and a free-text `description`. Items open with `status` `OPEN`, `raised_by_user_id` set from the acting `X-User-ID`, `reinspect_fail_count` 0, and `remediation_note`, `reinspected_by_user_id`, `waiver_ref` and `closed_at` all null. Raising an item recomputes the package's posture.

Remediation is the `CWDetailer`'s response: supplying a `remediation_note` narrative moves the item `OPEN` → `REMEDIATION_SUBMITTED` and stores the note. Note that a `REMEDIATION_SUBMITTED` critical defect still counts toward `open_critical_defect_count` — submitting a remediation does not relieve the posture.

Re-inspection belongs to a `QCInspector`, with one hard constraint: **the inspector who raised an item may not re-inspect it.** When the acting `X-User-ID` equals the item's `raised_by_user_id`, the request is refused with `ERR_INSPECTOR_CONFLICT`. The payload carries an `outcome` of `PASS` or `FAIL`. A `PASS` moves the item `REMEDIATION_SUBMITTED` → `CLOSED`, setting `reinspected_by_user_id` and stamping `closed_at`. A `FAIL` moves it `REMEDIATION_SUBMITTED` → `OPEN`, increments `reinspect_fail_count` by 1, sets `reinspected_by_user_id`, and clears `remediation_note` so a fresh narrative must be written — this is the cycle edge that lets an item bounce indefinitely. Both outcomes recompute the package's posture; the `PASS` branch also recomputes `open_critical_defect_count`.

An `ArchitectOfRecord` may **waive** a defect instead, moving it `OPEN` → `WAIVED` and storing the payload's `waiver_ref` architect waiver reference along with `closed_at`. Waivers are for non-critical items only: an item whose `severity` is `CRITICAL` is refused with `ERR_WAIVER_NOT_PERMITTED`. `CLOSED` and `WAIVED` are the defect machine's terminal states.

**Weather-tight certification** is the milestone that converts installed area into money, and only a `CWProjectManager` may sign it. The payload may carry an optional `certification_note`. Certification advances `weather_status` from `NOT_TIGHT` → `WEATHER_TIGHT` on a first pass, or `REMEDIATION` → `WEATHER_TIGHT` after remediation; the two edges have identical preconditions and identical side effects, except that the post-remediation edge evaluates the evidence against the latest attempt of each test kind. A zone may be certified, reverted and re-certified any number of times. Eight conditions must hold:

- The zone's `install_status` must be `PANELS_HUNG`; otherwise `ERR_ZONE_SEQUENCE_VIOLATION`.
- The zone's `weather_status` must be `NOT_TIGHT` or `REMEDIATION`.
- The package's `engineering_posture` must not be `FROZEN`; otherwise `ERR_ENGINEERING_POSTURE_FROZEN`.
- The zone must have at least one `PASSED` field test of kind `WATER_AAMA_501_2` **and** at least one `PASSED` field test of kind `AIR_INFILTRATION`. An empty passed set fails here, and so does a set holding only one of the two kinds; one of each kind satisfies it. The rejection is `ERR_NO_FIELD_TEST_EVIDENCE`. A passed `STRUCTURAL_DEFLECTION` test is not required for certification.
- No field test of the zone may be in state `FAILED` whose linked defect item is not yet `CLOSED` or `WAIVED`.
- No defect item of the zone may have `severity` `CRITICAL` with `status` `OPEN` or `REMEDIATION_SUBMITTED`; otherwise `ERR_OPEN_CRITICAL_DEFECT`.
- The zone's computed `thermal_movement_allowance_mm` must not exceed its `designed_joint_mm`. When the computed movement no longer fits the detailed joint — typically because the joint was retuned narrower, or because the system decision widened the requirement — certification is refused with `ERR_THERMAL_MOVEMENT_EXCEEDED`.
- Adding this zone's certified line must not push the package's certified subtotal past its `contract_value_cents`; otherwise `ERR_BILLING_EXCEEDS_CONTRACT`.

On success the zone stamps `weather_tight_at` from the logical clock and increments `weather_tight_cycle_count` by 1, writes `final_labor_cost_cents` from the chronological walk of §3.7, writes its own `certified_line_cents`, and rolls the package's `certified_area_sqm`, `earned_value_certified_cents`, `retention_held_cents` and `weather_tight_zone_count` forward. Once every zone of the package is `WEATHER_TIGHT`, the package bubbles `IN_INSTALLATION` → `WEATHER_TIGHT_ACHIEVED`; that bubble requires the package to have at least one zone.

The revert direction is a system event rather than a request: a zone leaves `WEATHER_TIGHT` for `REMEDIATION` whenever a field test of the zone is recorded `FAILED` or a panel lot of the zone goes `ON_HOLD`. The revert clears `weather_tight_at` and `certified_line_cents`, decrements the package's `weather_tight_zone_count`, recomputes `certified_area_sqm`, `earned_value_certified_cents` and `retention_held_cents`, and reverts the package `WEATHER_TIGHT_ACHIEVED` → `IN_INSTALLATION`. Note that `weather_tight_cycle_count` is a running total of certifications and is never decremented by a revert.

### 3.9. Earned Value, Retention and Punch-List Close-Out

Earned value is derived from nothing but the current set of weather-tight zones, in three ordered stages where each stage consumes the *rounded* output of the one before it. Stage one, per zone, taking the package's weather-tight zones in `weather_tight_at` ascending then `created_at` ascending order: for every installation zone of the package whose `weather_status` is `WEATHER_TIGHT`, that zone's `certified_line_cents` is its `area_sqm` multiplied by the package's `unit_rate_cents_per_sqm` multiplied by the weather-tight milestone factor of 0.95 — the milestone releases ninety-five percent of the unit value, with the remainder falling due at close-out — rounded half up to whole cents. Stage two: the certified subtotal is the sum of those stage-one line values, each of which is already rounded to whole cents; the unrounded products must never be summed and rounded once at the end. Also in stage two, `certified_area_sqm` is the sum of those same zones' `area_sqm` values, rounded half up to two decimal places. Stage three: `retention_held_cents` is the certified subtotal multiplied by a retention rate of 0.05 — five percent withheld — rounded half up to whole cents, and `earned_value_certified_cents` is the certified subtotal less that retention. Retention is taken on the rounded subtotal, never line by line.

Zones in `NOT_TIGHT` or `REMEDIATION` contribute nothing, which is why a revert cascade simply removes the reverted zone's line from the sum and re-runs all three stages. A dedicated computed read on the package re-derives the whole ledger from the current weather-tight zone set without mutating anything, reporting `certified_area_sqm`, the `certified_subtotal_cents` intermediate, `retention_held_cents`, `earned_value_certified_cents`, `weather_tight_zone_count` and the `contract_value_cents` ceiling side by side.

Close-out is the package's terminal transition, `WEATHER_TIGHT_ACHIEVED` → `CLOSED_OUT`, taken by a `CWProjectManager` with an optional `closeout_note`. Four conditions must hold together. Every installation zone of the package must have `weather_status` `WEATHER_TIGHT` and `install_status` `PANELS_HUNG`; a zone that is not weather-tight refuses close-out with `ERR_ZONES_NOT_WEATHER_TIGHT`. No defect item of the package may have `status` `OPEN` or `REMEDIATION_SUBMITTED`. No shop-drawing submittal of the package may be in `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUIRED` or `ESCALATED`. And the sum of `open_notes_count` across the package's submittals must be exactly 0 — an approved-as-noted set with two unclosed notes blocks close-out just as firmly as an unfinished review. The last three of those four conditions all report `ERR_PUNCH_LIST_OPEN`, and an open critical defect in package scope reports `ERR_OPEN_CRITICAL_DEFECT` ahead of them, since safety outranks fiscal completeness.

Consider a scenario that shows why the zone roster is checked directly rather than inferred from the package's state. A package reaches `WEATHER_TIGHT_ACHIEVED` with three certified zones; the project manager then registers a fourth zone for a late scope addition. Adding a zone does not change the package's state, so the package still reads `WEATHER_TIGHT_ACHIEVED` — but the fourth zone is `NOT_TIGHT`, and close-out is correctly refused with `ERR_ZONES_NOT_WEATHER_TIGHT`.

Close-out freezes `earned_value_certified_cents` and `retention_held_cents` at their current values and bumps the package's `version` by 1. `CLOSED_OUT` accepts no further transitions.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`. Endpoints that modify an existing resource — every state transition, every compensating action, every recomputation — return HTTP 200 with the updated resource. Read endpoints return HTTP 200. Error responses carry the status code listed in §5. Request and response payload contents are not restated here; they are specified in the §3 narratives that describe the corresponding business operations.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Sets the logical clock that every timestamp, lead-time delta and window comparison reads. | All roles |
| POST | `/facade-packages` | Opens a facade package in `DESIGN_ASSIST`. | `CWProjectManager` |
| GET | `/facade-packages` | Filtered, paginated package list. | All roles |
| GET | `/facade-packages/{id}` | Reads one package, including the `version` used for optimistic concurrency on release creation. | All roles |
| POST | `/facade-packages/{id}/system-decision` | Fixes the unitized-versus-stick-built fork and reconciles every existing zone's derived limits. | `CWProjectManager` |
| POST | `/facade-packages/{id}/close-out` | Terminal transition; freezes earned value and retention. | `CWProjectManager` |
| GET | `/facade-packages/{id}/earned-value` | Computed read of the certified earned-value ledger; mutates nothing. | All roles |
| GET | `/facade-packages/{id}/submittals` | Submittals of the package. | All roles |
| GET | `/facade-packages/{id}/zones` | Zones of the package. | All roles |
| POST | `/shop-drawing-submittals` | Creates a submittal in `SUBMITTED` with `revision_cycle` 1. | `CWDetailer` |
| GET | `/shop-drawing-submittals` | Filtered submittal list. | All roles |
| GET | `/shop-drawing-submittals/{id}` | Reads one submittal. | All roles |
| POST | `/shop-drawing-submittals/{id}/seal` | Applies the delegated designer's professional seal. | `DelegatedEngineer` |
| POST | `/shop-drawing-submittals/{id}/start-review` | `SUBMITTED` → `UNDER_REVIEW`; enforces the seal requirement and sealer/reviewer segregation. | `ArchitectOfRecord` |
| POST | `/shop-drawing-submittals/{id}/review` | Four-way review branch; the revision branches run the four-hop revocation cascade. | `ArchitectOfRecord` |
| POST | `/shop-drawing-submittals/{id}/resubmit` | Cycle edge back to `SUBMITTED`; increments the revision round and clears the seal. | `CWDetailer` |
| POST | `/shop-drawing-submittals/{id}/reopen-review` | `APPROVED_AS_NOTED` → `UNDER_REVIEW` re-entry edge. | `ArchitectOfRecord` |
| POST | `/shop-drawing-submittals/{id}/close-notes` | Burns down open reviewer notes on an approved-as-noted submittal. | `ArchitectOfRecord` |
| POST | `/glass-orders` | Places a glass order in `ORDERED` and scores it under the nominal risk variant. | `GlazingProcurement` |
| GET | `/glass-orders` | Filtered glass-order list. | All roles |
| GET | `/glass-orders/{id}` | Reads one order, including its `version` and the whole lite ledger. | All roles |
| POST | `/glass-orders/{id}/start-production` | `ORDERED` → `IN_PRODUCTION`. | `GlazingProcurement` |
| POST | `/glass-orders/{id}/coating-revision` | Re-fire cycle edge back to `ORDERED`; may revoke releases and hold their lots. | `GlazingProcurement` |
| POST | `/glass-orders/{id}/request-expedite` | Buys expedite tier 1 or 2 and rescores the order. | `GlazingProcurement` |
| POST | `/glass-orders/{id}/receive` | `IN_PRODUCTION` → `RECEIVED`; reserves breakage stock and opens the lite ledger. | `GlazingProcurement` |
| POST | `/glass-orders/{id}/recompute-risk` | Re-derives the risk score against the current logical clock without changing state. | `GlazingProcurement`, `CWProjectManager` |
| GET | `/glass-orders/{id}/panel-lots` | Lots cut from this order. | All roles |
| POST | `/fabrication-releases` | Releases fabrication for a zone set, creating one panel lot per zone. | `CWProjectManager` |
| GET | `/fabrication-releases` | Filtered release list. | All roles |
| GET | `/fabrication-releases/{id}` | Reads one release, including its revocation reason. | All roles |
| GET | `/fabrication-releases/{id}/panel-lots` | Lots created by this release. | All roles |
| GET | `/panel-lots` | Filtered lot list. | All roles |
| GET | `/panel-lots/{id}` | Reads one lot, including its hold reason and pre-hold status. | All roles |
| POST | `/panel-lots/{id}/advance-fabrication` | `BATCHED` → `GLAZED` → `SHIPPED`, with bubble-up closure of release and order. | `FieldSuperintendent` |
| POST | `/breakage-draws` | Draws replacement lites from breakage stock. | `GlazingProcurement` |
| GET | `/breakage-draws` | Filtered draw list. | All roles |
| GET | `/breakage-draws/{id}` | Reads one draw. | All roles |
| POST | `/breakage-draws/{id}/cancel` | Compensating action returning drawn lites to available stock. | `GlazingProcurement` |
| POST | `/test-labs` | Registers an accredited mockup laboratory as an immutable reference row. | `CWProjectManager` |
| GET | `/test-labs` | Laboratory list. | All roles |
| GET | `/test-labs/{id}` | Reads one laboratory. | All roles |
| POST | `/mockup-tests` | Books chamber time against the laboratory's capacity and prices the invoice. | `CWProjectManager`, `QCInspector` |
| GET | `/mockup-tests` | Filtered mockup list, resolving the retest chain. | All roles |
| GET | `/mockup-tests/{id}` | Reads one mockup test, including its invoice breakdown. | All roles |
| POST | `/mockup-tests/{id}/record-result` | `SCHEDULED` → `PASSED` or `FAILED`; qualifies the package or raises a critical defect. | `QCInspector` |
| POST | `/installation-zones/{id}/embed-surveys` | Opens the pre-pour embed survey for a zone in `PENDING_SURVEY`. | `StructuralContractor` |
| GET | `/embed-surveys` | Filtered survey list. | All roles |
| GET | `/embed-surveys/{id}` | Reads one survey, including its attempt count. | All roles |
| POST | `/embed-surveys/{id}/survey` | Records an as-built survey; accepts, rejects, or self-loops on rejection. | `StructuralContractor` |
| POST | `/embed-surveys/{id}/confirm-pour` | `ACCEPTED` → `POURED`. | `StructuralContractor` |
| POST | `/installation-zones` | Creates a zone in `PLANNED` / `NOT_TIGHT` and derives its dimensional limits. | `CWProjectManager` |
| GET | `/installation-zones` | Filtered zone list. | All roles |
| GET | `/installation-zones/{id}` | Reads one zone: both status axes, both labor variants and the crew-hour ledger. | All roles |
| POST | `/installation-zones/{id}/set-anchors` | `install_status` `PLANNED` → `ANCHORS_SET`; requires a poured embed survey. | `FieldSuperintendent` |
| POST | `/installation-zones/{id}/hang-panels` | `install_status` `ANCHORS_SET` → `PANELS_HUNG`; consumes a hoist reservation. | `FieldSuperintendent` |
| POST | `/installation-zones/{id}/certify-weather-tight` | `weather_status` → `WEATHER_TIGHT`; books the certified line and rolls earned value. | `CWProjectManager` |
| POST | `/installation-zones/{id}/retune-joint` | Re-details the movement joint and recomputes the thermal allowance. | `CWDetailer` |
| GET | `/installation-zones/{id}/crew-day-logs` | Crew-day ledger of the zone in chronological order. | All roles |
| GET | `/installation-zones/{id}/field-tests` | Field tests of the zone. | All roles |
| POST | `/installation-zones/{id}/crew-days` | Posts a crew day, splitting straight and overtime hours and pricing the day. | `FieldSuperintendent` |
| GET | `/crew-day-logs` | Filtered crew-day list. | All roles |
| GET | `/crew-day-logs/{id}` | Reads one crew day. | All roles |
| POST | `/installation-zones/{id}/crew-days/{crew_day_id}/void` | Compensating action; re-packs the chronological index and restores the budget identity. | `FieldSuperintendent` |
| POST | `/hoist-rigs` | Registers a hoist or crane with its changeover buffer. | `FieldSuperintendent` |
| GET | `/hoist-rigs` | Filtered rig list. | All roles |
| GET | `/hoist-rigs/{id}` | Reads one rig. | All roles |
| GET | `/hoist-rigs/{id}/reservations` | Reservations on this rig with their buffer-expanded blocked intervals. | All roles |
| POST | `/hoist-reservations` | Reserves exclusive rig occupancy against the buffer-expanded blocked intervals. | `FieldSuperintendent` |
| GET | `/hoist-reservations` | Filtered reservation list. | All roles |
| GET | `/hoist-reservations/{id}` | Reads one reservation. | All roles |
| POST | `/hoist-reservations/{id}/cancel` | Releases the rig window and its buffer. | `FieldSuperintendent` |
| POST | `/installation-zones/{id}/field-tests` | Schedules a water, air-infiltration or structural-deflection field test. | `QCInspector` |
| GET | `/field-tests` | Filtered field-test list. | All roles |
| GET | `/field-tests/{id}` | Reads one field test, including its outcome reason. | All roles |
| POST | `/field-tests/{id}/record-result` | `SCHEDULED` → `PASSED` or `FAILED`; a failure runs the four-hop cascade. | `QCInspector` |
| POST | `/defect-items` | Raises a punch-list or nonconformance item in `OPEN`. | `QCInspector`, `ArchitectOfRecord` |
| GET | `/defect-items` | Filtered defect list; this is the project punch list. | All roles |
| GET | `/defect-items/{id}` | Reads one defect item, including its failed re-inspection count. | All roles |
| POST | `/defect-items/{id}/submit-remediation` | `OPEN` → `REMEDIATION_SUBMITTED`. | `CWDetailer` |
| POST | `/defect-items/{id}/reinspect` | `REMEDIATION_SUBMITTED` → `CLOSED` on pass, or back to `OPEN` on fail. | `QCInspector` |
| POST | `/defect-items/{id}/waive` | `OPEN` → `WAIVED` for non-critical items only. | `ArchitectOfRecord` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_ROLE` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_MISSING_USER` | 401 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_ENUM` | 400 |
| `ERR_VALUE_OUT_OF_RANGE` | 400 |
| `ERR_INVALID_WINDOW` | 400 |
| `ERR_PACKAGE_NOT_FOUND` | 404 |
| `ERR_SUBMITTAL_NOT_FOUND` | 404 |
| `ERR_GLASS_ORDER_NOT_FOUND` | 404 |
| `ERR_ZONE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_SURVEY_NOT_FOUND` | 404 |
| `ERR_TEST_NOT_FOUND` | 404 |
| `ERR_DEFECT_NOT_FOUND` | 404 |
| `ERR_HOIST_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_STALE_PACKAGE_VERSION` | 412 |
| `ERR_STALE_GLASS_ORDER_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_TERMINAL_STATE` | 409 |
| `ERR_ZONE_SEQUENCE_VIOLATION` | 409 |
| `ERR_DISPUTE_REF_REQUIRED` | 409 |
| `ERR_COATING_REVISION_AFTER_RECEIPT` | 409 |
| `ERR_CREW_DAY_DUPLICATE` | 409 |
| `ERR_HOIST_WINDOW_CONFLICT` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_SEAL_REQUIRED` | 422 |
| `ERR_SEAL_INVALID` | 422 |
| `ERR_SEALER_CANNOT_REVIEW` | 422 |
| `ERR_INSPECTOR_CONFLICT` | 422 |
| `ERR_SUBMITTAL_NOT_APPROVED` | 422 |
| `ERR_ENGINEERING_POSTURE_FROZEN` | 422 |
| `ERR_MOCKUP_NOT_QUALIFIED` | 422 |
| `ERR_EMBED_SURVEY_NOT_ACCEPTED` | 422 |
| `ERR_POUR_BEFORE_ACCEPTANCE` | 422 |
| `ERR_PANEL_LOTS_NOT_SHIPPED` | 422 |
| `ERR_HOIST_WINDOW_INVALID` | 422 |
| `ERR_NO_FIELD_TEST_EVIDENCE` | 422 |
| `ERR_OPEN_CRITICAL_DEFECT` | 422 |
| `ERR_THERMAL_MOVEMENT_EXCEEDED` | 422 |
| `ERR_DEFLECTION_LIMIT_UNSET` | 422 |
| `ERR_WAIVER_NOT_PERMITTED` | 422 |
| `ERR_GLASS_BALANCE_INSUFFICIENT` | 422 |
| `ERR_BREAKAGE_STOCK_EXHAUSTED` | 422 |
| `ERR_DRAW_QUANTITY_INVALID` | 422 |
| `ERR_GLASS_RISK_THRESHOLD_EXCEEDED` | 422 |
| `ERR_BILLING_EXCEEDS_CONTRACT` | 422 |
| `ERR_ZONES_NOT_WEATHER_TIGHT` | 422 |
| `ERR_PUNCH_LIST_OPEN` | 422 |

# Sterile Processing Department API — Product Requirements Document

## 1. Introduction

Every surgical case a hospital runs depends on an invisible supply chain: instrument trays that have been decontaminated, assembled against a precise count sheet, sterilized in a documented load, biologically monitored, and released before they may anywhere near an operating room. When that chain breaks — a positive biological indicator discovered after release, a loaner set arriving hours before an early-morning case, a technician whose certification quietly lapsed last week — the consequences are measured in cancelled surgeries, infection risk, and regulatory exposure. Sterile processing departments track this work today with paper count sheets, whiteboards, and institutional memory.

This document specifies an API for operating a hospital Sterile Processing Department (SPD) end to end: tray templates and their count-sheet specifications, the physical tray reprocessing pipeline from decontamination through assembly verification, sterilizer and load orchestration with chamber-capacity and scheduling-window controls, biological indicator incubation with load release and recall cascades, tray reservations against the OR schedule, immediate-use steam sterilization (IUSS) exception tracking under a rolling-rate supervisor gate, the instrument repair-or-replace economic decision cycle, technician certification and competency scoring, and tiered loaner-set intake deadlines. The system enforces segregation of duties at load release, optimistic concurrency on the scheduling desk's most contended writes, and a deterministic logical clock against which every deadline, sterility expiry, and rolling compliance window is evaluated.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request missing either header, or carrying a role that is not one of the declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Access to each operation is then restricted by role; a caller whose role is not listed for the endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes five declared roles, plus the conventional marker `Any` used in this document to mean that every declared role may perform the operation (in practice, all read operations):

- **`FacilityAdmin`** — the SPD facility administrator. Owns configuration: tray templates, sterilizers, instruments, technician records, repair-order dispatch and receipt, and the logical clock.
- **`SpdTechnician`** — a certified SPD technician. Runs decontamination, assembly, count-sheet verification, instrument assignment and flagging, load operation, IUSS logging, and loaner intake.
- **`SpdSupervisor`** — the SPD supervisor, also a credentialed technician identity. Releases loads (never a load they operated themselves), recalls loads, discards quarantined trays, suspends and reinstates technicians, and logs IUSS exceptions beyond the technician rolling-rate allowance.
- **`OrScheduler`** — the OR scheduling desk. Schedules cases, reserves and releases trays, books loaner sets, and starts, completes, and cancels cases.
- **`QualityAuditor`** — the quality/compliance auditor. Records biological indicator results, adds follow-up indicators to loads, reviews IUSS exceptions, and may recall released loads.

Role identity semantics are part of the contract. When `X-User-Role` is `SpdTechnician`, `X-User-ID` is the `id` of the acting `Technician`; attribution and standing checks on any record that references a `Technician` — a load's `operator_id`, an assembly verification's `technician_id`, an IUSS exception's `logged_by_id` — compare that foreign-key field to `X-User-ID`. The same rule applies when `X-User-Role` is `SpdSupervisor`: `X-User-ID` is again the `id` of a `Technician`, which is what makes the load-release segregation check (releaser versus recorded `operator_id`) meaningful. When `X-User-Role` is `FacilityAdmin`, `OrScheduler`, `QualityAuditor`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Logical Clock and Lazy Expiry Sweeps

Every timestamp comparison in this system — deadlines, sterility expiries, rolling windows, incubation maturities — is evaluated against the server's **logical clock**, never against wall-clock time. At startup, before any adjustment, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `FacilityAdmin`-only capability sets the logical clock to a supplied ISO 8601 instant via the `to_iso8601` field; the response echoes the new value as `current_utc`. Once set, the logical clock never falls back to wall-clock time.

Two system transitions are **lazy sweeps**: a `STERILE` tray whose sterility has lapsed, and an `ACTIVE` technician whose certification has lapsed. The server applies a due sweep to the *target entity of the endpoint being served* — the addressed resource, or each row of a list response — before validation and before responding. Linked entities are **not** swept transitively. For example, starting an OR case observes its reserved trays exactly as stored: a tray whose `sterility_expires_at` has passed but which has not itself been read or touched is still seen in its stale `STERILE` state and trips `ERR_RESERVED_TRAY_EXPIRED` at case start; a subsequent direct read of that tray then applies the sweep. The two sweep rules differ at the boundary: the tray sterility sweep fires when the logical clock reaches or passes `sterility_expires_at`, whereas the technician certification sweep fires only when the logical clock is strictly past `certification_expires_at`.

### 2.5. Common Resource Properties and Identity Conventions

All primary resources — tray templates, trays, instruments, repair orders, sterilizers, sterilization loads, biological indicators, OR cases, tray reservations, IUSS exceptions, technicians, and loaner sets — share a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- **`version` (integer):** initialized to 1 at creation and incremented by 1 on every mutation; the basis for optimistic concurrency control.

One exception exists. Assembly verification records are immutable audit entries and carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.6. Validation Order: How Requests Are Screened

Every request is screened against a fixed, priority-ordered gauntlet. When several checks could fail on the same request, the earliest one in this order determines the rejection:

1. **Header presence.** `X-User-ID` and `X-User-Role` are present and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization.** The caller's role is listed for the endpoint (`Any` admits every declared role) — otherwise `ERR_FORBIDDEN_ROLE` (403).
3. **Path existence.** Resource identifiers in the path are validated left to right — the leftmost missing id wins with `ERR_NOT_FOUND` (404).
4. **Request shape.** Required fields are present, types are valid, enum values fall inside their declared sets, justification strings are at least 20 characters, and body foreign-key references (`tray_id`, `case_id`, `instrument_id`, `sterilizer_id`, `template_id`) resolve to existing rows — otherwise one of `ERR_INVALID_REQUEST`, `ERR_INVALID_ENUM_VALUE`, or `ERR_JUSTIFICATION_TOO_SHORT` (all 400).
5. **Optimistic concurrency.** Where an OCC field applies (§2.7), it must equal the parent's current `version` — checked *before any business rule*, otherwise `ERR_STALE_VERSION` (412).
6. **State-machine preconditions.** The target resource's own status gate is checked first (the `ERR_TRAY_NOT_*`, `ERR_LOAD_NOT_*`, `ERR_CASE_NOT_*`, `ERR_RESERVATION_NOT_ACTIVE`, `ERR_BI_ALREADY_RECORDED`, `ERR_INSTRUMENT_NOT_*`, `ERR_REPAIR_ORDER_NOT_*`, `ERR_LOANER_NOT_*`, `ERR_IUSS_ALREADY_REVIEWED`, and `ERR_TECHNICIAN_NOT_*` families, 409), and only then linked-entity state gates: `ERR_LOANER_NOT_READY` at case start, `ERR_TRAY_NOT_STERILE` at reservation creation, `ERR_STERILIZER_NOT_IDLE` at load start.
7. **Patient-safety gates.** On load release, the segregation-of-duties check (`ERR_RELEASE_OPERATOR_SEGREGATION`, 403) is evaluated before the biological-indicator check (`ERR_BI_NOT_PASSED`, 409). On reservation creation, the sterility-expiry gate (`ERR_STERILITY_EXPIRED_FOR_CASE`) precedes every temporal gate. On case start, `ERR_RESERVED_TRAY_EXPIRED` fires here.
8. **Temporal gates.** Incubation maturity (`ERR_BI_STILL_INCUBATING`), sterilizer planned-window overlap (`ERR_STERILIZER_WINDOW_CONFLICT`), load start before its planned start (`ERR_LOAD_PLANNED_START_NOT_REACHED`), and tray reservation turnover-buffer conflicts (`ERR_TRAY_RESERVATION_TIME_CONFLICT`).
9. **Constraint gates**, in this relative order: technician standing (`ERR_TECHNICIAN_SUSPENDED`, `ERR_CERTIFICATION_EXPIRED`), method certification (`ERR_CERTIFICATION_METHOD_MISMATCH`), certification level (`ERR_CERTIFICATION_LEVEL_INSUFFICIENT`), the hydrogen-peroxide competency gate (`ERR_COMPETENCY_BELOW_THRESHOLD`) — these four plus `ERR_IUSS_RATE_EXCEEDED` carry 403; then load emptiness (`ERR_LOAD_EMPTY`) and chamber capacity (`ERR_LOAD_CAPACITY_EXCEEDED`); instrument assignment rules (`ERR_INSTRUMENT_ALREADY_ASSIGNED`, `ERR_INSTRUMENT_CYCLE_LIMIT`); uniqueness (`ERR_DUPLICATE_SERIAL_NUMBER`, `ERR_DUPLICATE_TEMPLATE_CODE`); the IUSS rolling-rate gate (eligibility itself, `ERR_IUSS_TRAY_NOT_ELIGIBLE`, is a state check at step 6); and repair outcome-override justification (`ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED`, 400). Except where noted, gates in this step reject with 409.

### 2.7. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and in both cases the version field is a **non-optional** input:

- Updating a tray template (`PUT /spd/tray-templates/{id}`) must carry `expected_template_version` equal to the template's current `version`. A successful update increments `TrayTemplate.version` by 1, so a subsequent update carrying an older observed version is deterministically rejected as stale.
- Creating a tray reservation against a case (`POST /spd/or-cases/{id}/reservations`) must carry `expected_or_case_version` equal to the case's current `version`. Each successful reservation creation mutates the case (status recompute) and increments `ORCase.version` by 1, so a second creation carrying a previously observed version is deterministically rejected as stale.

In both cases a mismatch with the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), evaluated at screening step 5 — before any business rule. Endpoints not named above do not take a version field.

### 2.8. Nested Resource Retrieval

For any endpoint whose path contains resource identifiers, the system validates existence in a strict left-to-right order and rejects the request with `ERR_NOT_FOUND` (404) at the *first* identifier that does not correspond to an existing resource. A request addressed to a biological indicator under a non-existent sterilization load, for instance, fails on the load before the indicator is ever consulted.

### 2.9. Monetary Values, Cents, and Rounding

All monetary amounts in this system are integer counts of cents — there are no decimal dollar values anywhere. `replacement_cost_cents` must be strictly greater than zero at instrument registration; `quoted_cost_cents` and `actual_cost_cents` record vendor quotes and final invoices in cents on repair orders; `total_chargeback_cents` records the department chargeback on a released load.

Two rounding rules are pinned. First, the load chargeback rounds **per tray line first**: each member tray's raw fee is rounded half up to whole cents, and only then are the per-tray fees summed — summing raw fees and rounding once at the end is the forbidden variant. Second, IUSS compliance rates are reported to exactly 4 decimal places using round half up. The repair-versus-replace recommendation (§3.3) uses exact decimal arithmetic with no rounding applied before its threshold comparison.

### 2.10. Sterility Shelf-Life Tiers

A tray's sterile shelf life is assigned at load release and is driven entirely by its template's `packaging_type`. A `WRAPPED` tray receives 720 hours (thirty days) of shelf life; a `RIGID_CONTAINER` tray receives 2,160 hours (ninety days). Concretely, each member tray's `sterility_expires_at` is set to the load's `released_at` plus the tier hours for its packaging.

Every expiry comparison downstream is strict. Reserving a tray for a case requires `sterility_expires_at` to be strictly later than the case's `scheduled_start_at`; case start requires each reserved tray's `sterility_expires_at` to be strictly later than the current logical time; and the lazy sterility sweep (§2.4) fires the moment the logical clock reaches `sterility_expires_at`.

## 3. Business Logic & Workflows

### 3.1. Tray Templates and the Availability Projection

A **tray template** is the count-sheet specification from which physical trays are assembled. A `FacilityAdmin` registers a template with a unique `code` (a second registration of the same code is rejected with `ERR_DUPLICATE_TEMPLATE_CODE`), a human-readable `name`, a surgical `specialty` label, a `packaging_type` of either `WRAPPED` or `RIGID_CONTAINER` (which drives the sterility shelf-life tier per §2.10), a non-empty `instrument_requirements` list whose lines each name an `instrument_type` and a required `quantity` of at least 1 (an empty list is rejected with `ERR_INVALID_REQUEST`), and the standard `assembly_minutes` labor estimate. The template list can be filtered by `specialty`, and templates are paginated with the usual `limit` and `offset`. Updates — which may revise `name`, `specialty`, `packaging_type`, `instrument_requirements`, or `assembly_minutes` — are OCC-guarded per §2.7 and increment the template's `version` by 1 on success.

For planning against the OR schedule, the system computes a forward-looking **availability projection** for one template over one future window. Given a `window_start_at` instant (call it W), the response reports the `template_id`, the echoed `window_start_at`, and two sanctioned counts side by side:

- `confirmed_available_count` — the conservative variant: trays of this template currently `STERILE` whose `sterility_expires_at` is later than W. Only physically sterile stock counts.
- `pipeline_available_count` — the optimistic variant: everything in the confirmed count, plus trays of this template currently `IN_LOAD` whose load is `LOADING`, `RUNNING`, or `COMPLETED` and whose *projected release instant* falls at or before W (the boundary is inclusive). The projected release instant is, for a `LOADING` load, its `planned_start_at` plus the sterilizer's `cycle_minutes` plus a 3-hour biological-indicator incubation allowance; for a `RUNNING` load, `started_at` plus `cycle_minutes` plus the same 3 hours; for a `COMPLETED` load, `completed_at` plus 3 hours.

Trays in any other status — including `QUARANTINED` and `IN_USE` — count in neither variant, and existing reservations never reduce either count, because bookings are temporal rather than status-based. Identical inputs therefore yield a strictly larger pipeline count whenever qualifying in-pipeline trays exist.

### 3.2. The Tray Reprocessing Pipeline: Decontamination, Assembly, Verification

A `SpdTechnician` registers a physical tray against a template by supplying the `template_id` and the tray's physical `label` (barcode text). A new tray begins its life `AWAITING_DECONTAMINATION`, with `current_load_id` null, `cycles_completed` at 0, `quarantine_reason` null, and `sterility_expires_at` null. From there a tray walks the reprocessing pipeline through `IN_DECONTAMINATION`, `DECONTAMINATED`, `IN_ASSEMBLY`, `ASSEMBLED`, `IN_LOAD`, and `STERILE`, with `IN_USE`, `QUARANTINED`, and the terminal `DISCARDED` as the off-line states. Trays can be listed with filters on `template_id`, `current_load_id`, and `status`, and every read of a tray — single or listed — applies the lazy sterility sweep of §2.4 before responding.

Beginning decontamination is the entry gate of the pipeline and also the reprocessing path out of quarantine: it is permitted from either `AWAITING_DECONTAMINATION` or `QUARANTINED` (any other status is rejected with `ERR_TRAY_NOT_READY_FOR_DECONTAMINATION`), and when the tray enters from `QUARANTINED` its `quarantine_reason` is cleared back to null. Completing decontamination requires `IN_DECONTAMINATION` (else `ERR_TRAY_NOT_IN_DECONTAMINATION`) and lands the tray `DECONTAMINATED`. Beginning assembly requires `DECONTAMINATED` (else `ERR_TRAY_NOT_DECONTAMINATED`) and moves the tray `IN_ASSEMBLY`.

While a tray is `IN_ASSEMBLY`, a technician submits the assembled count sheet as `lines` — one line per instrument type found, each pairing an `instrument_type` with a non-negative `counted_qty`. The submission is rejected with `ERR_TRAY_NOT_IN_ASSEMBLY` if the tray is anywhere else in the pipeline. The system scores the submission against the template's `instrument_requirements`: the `result` is `PASS` when every requirement line's `counted_qty` matches the required `quantity` exactly and no extra `instrument_type` appears; otherwise the `result` is `FAIL`. The computed `mismatch_count` tallies every requirement line whose counted quantity differs from the requirement — missing types count as a counted quantity of 0, and unexpected extra types each count as a mismatch. A `PASS` verification persists the record (with `mismatch_count` 0) and advances the tray to `ASSEMBLED`. A `FAIL` verification leaves the tray `IN_ASSEMBLY`, persists the record with its non-zero `mismatch_count`, and attributes a 2-point competency demerit to the acting technician (§3.8) — re-verification is allowed afterward. Each verification record carries the `tray_id` verified and the acting `technician_id` taken from `X-User-ID`; the verification history can be listed filtered by `tray_id`, `technician_id`, or `result`. Verification records are audit entries: they carry only `id` and `created_at` (§2.5).

A `SpdSupervisor` may discard a quarantined tray — the tray must be `QUARANTINED`, else `ERR_TRAY_NOT_QUARANTINED` — moving it to the terminal `DISCARDED` state.

### 3.3. Instruments and the Repair-or-Replace Cycle

A `FacilityAdmin` registers each instrument with its `instrument_type` (the key that matches template requirement lines, e.g. a scalpel), a unique `serial_number` (duplicates rejected with `ERR_DUPLICATE_SERIAL_NUMBER`), the lifecycle limit `max_cycles`, the new-unit `replacement_cost_cents` (strictly greater than zero), and a `criticality` of `ROUTINE` or `CRITICAL`. Used stock may be registered with a non-zero `usage_cycles`; omitted, it defaults to 0. New instruments are `IN_SERVICE` with `repair_count` 0 and `assigned_tray_id` null. The instrument list filters by `status`, `assigned_tray_id`, and `instrument_type`.

Assignment of an instrument to a tray happens while the tray is `IN_ASSEMBLY`: the technician supplies the `tray_id`. The instrument must be `IN_SERVICE` (else `ERR_INSTRUMENT_NOT_IN_SERVICE`), currently unassigned — `assigned_tray_id` null — (else `ERR_INSTRUMENT_ALREADY_ASSIGNED`), and below its lifecycle limit: assignment is blocked when `usage_cycles` has reached `max_cycles`, equality included (else `ERR_INSTRUMENT_CYCLE_LIMIT`). The tray must be `IN_ASSEMBLY` (else `ERR_TRAY_NOT_IN_ASSEMBLY`). A successful assignment sets the instrument's `assigned_tray_id`.

When an instrument is damaged, a technician flags it for repair: the instrument must be `IN_SERVICE` (else `ERR_INSTRUMENT_NOT_IN_SERVICE`), and flagging moves it to `FLAGGED_FOR_REPAIR` while opening a **repair order** in `OPEN` status with the order's `instrument_id` set. The assignment linkage is deliberately preserved at flag time — the tray cascade fires only when the instrument physically leaves the building.

A `FacilityAdmin` dispatches the repair by sending the order, which must be `OPEN` (else `ERR_REPAIR_ORDER_NOT_OPEN`), recording the `vendor` and `quoted_cost_cents`. Sending moves the order `OPEN → SENT` and the instrument `FLAGGED_FOR_REPAIR → OUT_FOR_REPAIR`, and triggers the tray demotion cascade: if the instrument still had an `assigned_tray_id`, the owning tray — when it sits in `IN_ASSEMBLY`, `ASSEMBLED`, or `IN_LOAD` — demotes to `IN_ASSEMBLY`; a tray that was `IN_LOAD` additionally leaves its load (its `current_load_id` clears and the load's `tray_count` decrements by 1); a tray already `IN_ASSEMBLY` simply stays `IN_ASSEMBLY`. The instrument's `assigned_tray_id` then clears to null.

When the vendor returns the instrument, the same admin role receives the order — it must be `SENT` (else `ERR_REPAIR_ORDER_NOT_SENT`) — supplying the final `actual_cost_cents` and the applied `outcome` of `FIXED` or `CONDEMNED`, plus an optional `override_justification`. At that moment the system computes the order's `recommended_outcome` through the repair-versus-replace decision ladder:

1. If the instrument's `usage_cycles` has reached or exceeded `max_cycles`, recommend `CONDEMNED`.
2. Otherwise, if its `repair_count` has reached or exceeded 3 completed repairs, recommend `CONDEMNED`.
3. Otherwise compute the base ratio of `actual_cost_cents` to `replacement_cost_cents`, adjust it upward by 25 percent for each prior completed repair (that is, multiply by one plus 0.25 times `repair_count`), and — when the instrument is `CRITICAL` and its remaining cycles (`max_cycles` minus `usage_cycles`) are 10 or fewer — multiply the adjusted ratio by 1.5. An adjusted ratio of 0.6 or higher recommends `CONDEMNED`; below 0.6 recommends `FIXED`. A ratio landing exactly on 0.6 condemns, and no rounding is applied before the comparison.

If the applied `outcome` differs from the computed `recommended_outcome`, the receive is accepted only with an `override_justification` of at least 20 characters (else `ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED`, 400), and the order records `outcome_overridden` as true. Receiving with `FIXED` closes the order `SENT → CLOSED_FIXED` and returns the instrument `OUT_FOR_REPAIR → IN_SERVICE` with `repair_count` incremented by 1. Receiving with `CONDEMNED` closes the order `SENT → CLOSED_CONDEMNED` and moves the instrument `OUT_FOR_REPAIR → RETIRED`. Repair orders can be listed filtered by `instrument_id` and `status`.

A `FacilityAdmin` may also retire an instrument outright from `IN_SERVICE` or `FLAGGED_FOR_REPAIR` (any other status draws `ERR_INSTRUMENT_NOT_RETIRABLE`). Retiring a flagged instrument auto-condemns its still-`OPEN` repair order to `CLOSED_CONDEMNED`, and if the instrument was assigned, its `assigned_tray_id` clears with the same tray demotion cascade as at send time. `RETIRED` is terminal.

### 3.4. Sterilizers and Load Orchestration

Sterilizers are registered by a `FacilityAdmin` with a `name`, a `method` of `STEAM_GRAVITY`, `STEAM_PREVAC`, or `LOW_TEMP_H2O2`, a `chamber_capacity` of at least 1 tray, a nominal `cycle_minutes` of at least 1, and a `required_certification_level` between 1 and 3. A new sterilizer is `IDLE`; it reads `RUNNING` whenever one of its loads is running. The sterilizer list filters by `status` and `method`.

A `SpdTechnician` schedules a load by supplying the `sterilizer_id` and a `planned_start_at`. The load is created `LOADING` with `tray_count` 0 and its `operator_id` taken from the creator's `X-User-ID`. Scheduling enforces a planned-window overlap rule on the target sterilizer: the new load occupies the half-open window from `planned_start_at` up to (but not including) `planned_start_at` plus `cycle_minutes`, and any intersection with another `LOADING` or `RUNNING` load's window on the same sterilizer is rejected with `ERR_STERILIZER_WINDOW_CONFLICT` — adjacency, where one window ends exactly as the other begins, is allowed. Loads list with filters on `sterilizer_id`, `operator_id`, and `status`.

Trays are added to a load one at a time while it is `LOADING`: the tray must be `ASSEMBLED` (else `ERR_TRAY_NOT_ASSEMBLED`), the load must be `LOADING` (else `ERR_LOAD_NOT_LOADING`), and the load's `tray_count` must still be below the sterilizer's `chamber_capacity` — adding when the count already equals capacity is rejected with `ERR_LOAD_CAPACITY_EXCEEDED`. Each addition moves the tray `ASSEMBLED → IN_LOAD`, sets its `current_load_id` to the load, and increments `tray_count` by 1.

Starting the cycle is the most heavily gated action in the department. The load must be `LOADING`; it must hold at least one tray (else `ERR_LOAD_EMPTY`); the sterilizer must be `IDLE` (else `ERR_STERILIZER_NOT_IDLE`); and the logical clock must have reached `planned_start_at` — starting early is rejected with `ERR_LOAD_PLANNED_START_NOT_REACHED`. The acting technician must exist and be in good standing: a `SUSPENDED` technician draws `ERR_TECHNICIAN_SUSPENDED` and a `CERTIFICATION_EXPIRED` one (post-sweep, §2.4) draws `ERR_CERTIFICATION_EXPIRED`. The sterilizer's `method` must appear in the technician's `certified_methods` (else `ERR_CERTIFICATION_METHOD_MISMATCH`), and the technician's `certification_level` must be at least the sterilizer's `required_certification_level` (else `ERR_CERTIFICATION_LEVEL_INSUFFICIENT`). For a `LOW_TEMP_H2O2` sterilizer there is one further gate: the technician's rolling `competency_score` must be at least 70 — a score of exactly 70 passes — else `ERR_COMPETENCY_BELOW_THRESHOLD`. On a successful start the load moves `LOADING → RUNNING`, `started_at` is stamped, and the sterilizer flips to `RUNNING`. Per the screening order of §2.6, the load's own status gate fires before the linked sterilizer-idle gate, the planned-start gate is temporal, and the technician standing, method, level, competency, and emptiness checks follow in the constraint tier's declared order.

Completing the cycle requires the load `RUNNING` (else `ERR_LOAD_NOT_RUNNING`) and moves it to `COMPLETED`: `completed_at` is stamped, the sterilizer returns to `IDLE`, and exactly one biological indicator is auto-created for the load — `INCUBATING`, result `PENDING`, `lot_number` defaulting to `AUTO-LOT`, and `due_at` set to `completed_at` plus 3 hours.

Two ways out of the pipeline exist before release. Recording a cycle-parameter failure requires `RUNNING` (else `ERR_LOAD_NOT_RUNNING`), moves the load to `FAILED_CYCLE`, frees the sterilizer to `IDLE`, returns every member tray to `ASSEMBLED` with `current_load_id` cleared, and attributes an 8-point competency demerit to the load's `operator_id`. Aborting is available only while `LOADING` (else `ERR_LOAD_NOT_LOADING`): the load moves to `ABORTED` and its member trays return to `ASSEMBLED` the same way. Both are terminal states for the load.

### 3.5. Biological Monitoring, Load Release, and Recall

Every completed load is shadowed by at least one **biological indicator** (BI). A BI begins `INCUBATING` with result `PENDING` and a `due_at` maturity instant; a `QualityAuditor` records its outcome by supplying a `result` of `NEGATIVE` or `POSITIVE` (any other value is rejected with `ERR_INVALID_ENUM_VALUE`). Recording is allowed only while the BI is `INCUBATING` — a second recording draws `ERR_BI_ALREADY_RECORDED` — and not before `due_at`: an early attempt is rejected with `ERR_BI_STILL_INCUBATING`, while arriving exactly at `due_at` is accepted. A successful recording stamps `recorded_at` and moves the BI to `RESULT_RECORDED`. Beyond the auto-created cycle indicator, an auditor may attach an extra follow-up (spore-strip) BI to a load while the load is `COMPLETED` or `RELEASED` — against a load in any other state the attempt is rejected with `ERR_BI_LOAD_STATE_INVALID`. A manually added BI may carry its own `lot_number` (defaulting again to `AUTO-LOT`), starts `INCUBATING`/`PENDING`, and sets its `due_at` to the creation instant plus 3 hours. Indicators list with filters on `load_id` and `result`.

**Release** is a supervisor act with a hard segregation-of-duties rule. The load must be `COMPLETED` (else `ERR_LOAD_NOT_RELEASABLE`); the caller's `X-User-ID` must differ from the load's recorded `operator_id` — the technician who ran the cycle may never release it, else `ERR_RELEASE_OPERATOR_SEGREGATION` (403), and this check is evaluated before the biological check per §2.6; and the load's biological evidence must be clean: at least one BI exists for the load, and *every* BI of the load is `RESULT_RECORDED` with result `NEGATIVE`, else `ERR_BI_NOT_PASSED`. On release the load moves `COMPLETED → RELEASED` and `released_at` is stamped. Every member tray moves `IN_LOAD → STERILE`: its `sterility_expires_at` is assigned per the shelf-life tiers of §2.10, its `cycles_completed` increments by 1, and its `current_load_id` clears. Every instrument assigned to those trays gains one `usage_cycles`. The load's `total_chargeback_cents` — null until this moment — is computed as the department chargeback: a base fee of 1,000 cents per member tray, multiplied by the sterilizer's method factor — 1.0 for `STEAM_GRAVITY`, 1.2375 for `STEAM_PREVAC`, 1.7625 for `LOW_TEMP_H2O2` — with each tray's fee rounded half up to whole cents *first* and the per-tray fees summed *afterward*. The order is pinned: three trays on a prevacuum sterilizer bill 3,714 cents (three times the individually rounded 1,237.5-cent line), whereas summing raw fees and rounding once would wrongly produce 3,713 cents.

**Recall** unwinds a release. A `RELEASED` load — any other state draws `ERR_LOAD_NOT_RECALLABLE` — is recalled either manually by a `SpdSupervisor` or `QualityAuditor` supplying a free-text `reason`, or automatically by the system when a `POSITIVE` BI result lands on a `RELEASED` load, in which case `recall_reason` is recorded as the literal `BI_POSITIVE`. Either way the load moves `RELEASED → RECALLED` with `recall_reason` set and `recalled_at` stamped. The recall cascade then fires: every member tray currently `STERILE` moves to `QUARANTINED` with `quarantine_reason` copied from the load's `recall_reason` and `sterility_expires_at` cleared to null; every reservation still `RESERVED` on those trays moves to `CANCELLED`; and each case stripped of a reservation this way, if it was `TRAYS_RESERVED`, falls to `AT_RISK`.

A `POSITIVE` BI landing on a load still `COMPLETED` takes the lighter path: the load moves to `FAILED_BI` and every member tray returns `IN_LOAD → DECONTAMINATED` with `current_load_id` cleared — the trays need reprocessing, not reassembly.

### 3.6. OR Scheduling: Cases, Reservations, and Immediate-Use Exceptions

An `OrScheduler` schedules an OR case with a unique `case_number` (a duplicate is rejected with `ERR_INVALID_REQUEST`), the `surgeon`, a `scheduled_start_at` strictly before `scheduled_end_at` (an inverted or touching window is rejected with `ERR_INVALID_REQUEST`), and a `priority` of `ELECTIVE`, `URGENT`, or `EMERGENCY`. New cases are `SCHEDULED` with `version` 1, and the case list filters by `status` and `priority`.

**Reservations** are temporal bookings, not status changes: reserving a tray leaves it `STERILE`, and one tray may hold multiple non-overlapping reservations. Creating one requires the case to be `SCHEDULED`, `TRAYS_RESERVED`, or `AT_RISK` (else `ERR_CASE_NOT_RESERVABLE`), and the payload carries the `tray_id` plus the OCC field `expected_or_case_version` per §2.7. The tray must be `STERILE` as stored (post-sweep, else `ERR_TRAY_NOT_STERILE`) with a `sterility_expires_at` strictly later than the case's `scheduled_start_at` — this expiry gate (`ERR_STERILITY_EXPIRED_FOR_CASE`) is evaluated before any temporal-overlap check. The turnover rule then expands the new case's window by 45 minutes on both sides and rejects any intersection with another `RESERVED` reservation's case window for the same tray (`ERR_TRAY_RESERVATION_TIME_CONFLICT`); a gap of exactly 45 minutes between the expanded windows is allowed. On success the reservation is created `RESERVED` with `reserved_at` stamped, the case moves from `SCHEDULED` (or `AT_RISK`) to `TRAYS_RESERVED`, and the case's `version` increments by 1 — which is precisely what makes a second reservation carrying a stale `expected_or_case_version` fail. Reservations list filtered by `case_id`, `tray_id`, and `status`.

Releasing a reservation is the compensating action of reserving: the reservation must be `RESERVED` (else `ERR_RESERVATION_NOT_ACTIVE`) and moves to `RELEASED`. The tray is untouched and stays `STERILE`; the owning case recomputes — when no `RESERVED` reservations remain and the case is `TRAYS_RESERVED` or `AT_RISK`, it returns to `SCHEDULED`. The same release-and-recompute applies when the lazy sterility sweep retires a `STERILE` tray: the tray drops to `AWAITING_DECONTAMINATION` with `sterility_expires_at` cleared, and each of its `RESERVED` reservations moves to `RELEASED` under the same case recompute. (Recall, by contrast, *cancels* reservations per §3.5.)

**Starting a case** has two sanctioned paths. On the reservation path, the case must be `TRAYS_RESERVED` or `AT_RISK` with at least one `RESERVED` reservation (else `ERR_CASE_NOT_STARTABLE`); every `RESERVED` reservation's tray must still be `STERILE` with `sterility_expires_at` later than now (else `ERR_RESERVED_TRAY_EXPIRED` — remembering from §2.4 that reserved trays are observed as stored, not transitively swept); and every loaner set booked for the case must be `READY` (else `ERR_LOANER_NOT_READY`). On the emergency IUSS path, a case still `SCHEDULED` may start only when at least one IUSS exception references it (else `ERR_CASE_NOT_STARTABLE`); the loaner gate applies identically. Either path moves the case to `IN_PROGRESS`, transitions the reserved trays `STERILE → IN_USE`, and flips linked `READY` loaner sets to `IN_USE`.

**Completing a case** requires `IN_PROGRESS` (else `ERR_CASE_NOT_COMPLETABLE`): `completed_at` is stamped, its `RESERVED` reservations move to `USED`, the trays they held move `IN_USE → AWAITING_DECONTAMINATION` with `sterility_expires_at` cleared, trays referenced by the case's IUSS exceptions and currently `IN_USE` likewise return to `AWAITING_DECONTAMINATION`, and linked loaner sets move `IN_USE → RETURNED`.

**Cancelling a case** is permitted from `SCHEDULED`, `TRAYS_RESERVED`, or `AT_RISK` (else `ERR_CASE_NOT_CANCELLABLE`) and moves the case to `CANCELLED`; its `RESERVED` reservations are `RELEASED` while the trays themselves remain `STERILE`, untouched.

**IUSS exceptions** track immediate-use steam sterilization — a tray flashed for a case outside the normal pipeline. A `SpdTechnician` or `SpdSupervisor` logs one with the `tray_id`, the `case_id`, and a `justification` of at least 20 characters (shorter draws `ERR_JUSTIFICATION_TOO_SHORT`). The tray must be `DECONTAMINATED` or `ASSEMBLED` (else `ERR_IUSS_TRAY_NOT_ELIGIBLE`) and moves to `IN_USE`, linked to the exception; on the referenced case's completion the tray returns to `AWAITING_DECONTAMINATION`. Referencing a case already `COMPLETED` or `CANCELLED` is rejected with `ERR_CASE_TERMINAL_FOR_IUSS`. Logging is rate-gated on a rolling window: count the exceptions with `logged_at` inside the trailing 168 hours — the window start is exclusive, the current instant inclusive — and add the prospective event; if that prospective count reaches 4, the caller must be a `SpdSupervisor`, else `ERR_IUSS_RATE_EXCEEDED` (403). A technician may therefore log the first, second, and third events inside a window; the fourth belongs to the supervisor alone. The exception records `logged_by_id` from `X-User-ID` and `logged_at` from the logical clock, starts `DOCUMENTED`, and lists filtered by `tray_id`, `case_id`, and `logged_by_id`. A `QualityAuditor` reviews a `DOCUMENTED` exception — a second review draws `ERR_IUSS_ALREADY_REVIEWED` — moving it to `REVIEWED` and recording an optional `review_note`.

### 3.7. Loaner Set Intake and Processing

Vendor-owned **loaner sets** arrive ahead of the cases that need them. An `OrScheduler` books a set with the `vendor`, the `case_id` it is loaned for, and a `tray_count` of at least 1; the booking is created `BOOKED`. The intake deadline is tiered off the linked case: `due_by` is the case's `scheduled_start_at` minus 24 hours when `tray_count` is below 10, and minus 48 hours when `tray_count` is 10 or more.

A `SpdTechnician` records intake against a `BOOKED` set (else `ERR_LOANER_NOT_BOOKED`). The lateness verdict branches on `due_by`: arriving at or before the deadline — an arrival exactly at `due_by` counts as on time — moves the set to `RECEIVED` with `received_late` false; arriving strictly after moves it to `LATE_RECEIVED` with `received_late` true. Either way `received_at` is stamped from the logical clock.

Processing finishes when a technician marks the set ready: the set must be `RECEIVED` or `LATE_RECEIVED` (else `ERR_LOANER_NOT_RECEIVED`) and moves to `READY`; a set that arrived late keeps `received_late` true as a permanent audit trail. From there the set rides the case lifecycle — `READY → IN_USE` when the owning case starts, and `IN_USE → RETURNED` (terminal) when it completes. Loaner sets list filtered by `case_id` and `status`.

### 3.8. Technician Standing, Competency, and Compliance Reporting

A `FacilityAdmin` registers each technician with a `name`, a `certification_level` from 1 to 3, a non-empty `certified_methods` list drawn from the three sterilizer methods, and a `certification_expires_at`. New technicians are `ACTIVE` with both `competency_score` and `competency_score_lifetime` at 100. The admin may later update `certification_level`, `certified_methods`, or `certification_expires_at`; renewing `certification_expires_at` to an instant beyond the current logical time reactivates a `CERTIFICATION_EXPIRED` technician back to `ACTIVE`. A `SpdSupervisor` suspends an `ACTIVE` technician (else `ERR_TECHNICIAN_NOT_ACTIVE`) to `SUSPENDED`, and reinstates a `SUSPENDED` one (else `ERR_TECHNICIAN_NOT_SUSPENDED`) back to `ACTIVE`. Independently of any human action, the lazy certification sweep (§2.4) flips an `ACTIVE` technician to `CERTIFICATION_EXPIRED` the first time the technician is read or touched after the logical clock has passed `certification_expires_at`. The technician list filters by `status` and applies the same sweep to every returned row.

**Competency scoring** converts two kinds of demerit events into a gating score: each failed assembly verification attributed to the technician costs 2 points (event time being the record's `created_at`), and each load that reached `FAILED_CYCLE` under their operation costs 8 points (event time being the transition's logical timestamp). Two window variants are maintained. The rolling variant, surfaced as `competency_score`, counts only events aged at most 90 days, weighting each at 1.0 when aged at most 30 days, at 0.5 when aged more than 30 and at most 60 days, and at 0.25 when aged more than 60 and at most 90 days. The lifetime variant, surfaced as `competency_score_lifetime`, counts every event at full weight regardless of age — an identical event history therefore yields a lifetime score lower than or equal to the rolling score. Each score is 100 minus the weighted sum of demerit points, floored at 0, and multiples of 0.5 are possible. The rolling score gates `LOW_TEMP_H2O2` load starts at 70 per §3.4.

**Compliance reporting** aggregates the department's safety KPIs over rolling windows. The summary reports `iuss_count_7d` — exceptions with `logged_at` in the trailing 168 hours, window start exclusive and the current instant inclusive; `completed_cases_30d` — cases `COMPLETED` with `completed_at` in the trailing 720 hours on the same window semantics; `scheduled_cases_30d` — cases whose `scheduled_start_at` falls in the trailing 720 hours, regardless of status; and two rate variants to 4 decimal places, round half up: `iuss_rate_per_completed` divides `iuss_count_7d` by the larger of `completed_cases_30d` and 1, while `iuss_rate_per_scheduled` divides it by the larger of `scheduled_cases_30d` and 1 — the scheduled denominator is never the smaller one, so identical numerators yield a smaller-or-equal scheduled rate. The summary also reports `loads_recalled_30d`, counting loads currently `RECALLED` whose recall happened within the trailing 720 hours, and `trays_quarantined_count`, counting trays currently `QUARANTINED`.

## 4. Endpoint Definitions

Operations that create a new resource — a template, tray, instrument, sterilizer, load, case, technician, loaner set, reservation, assembly verification, IUSS exception, repair order (via flagging), or an added biological indicator — return `201 Created`. Operations that modify an existing resource, including every state transition, return `200 OK`. Readers should reconstruct each operation's request payload and cascading side effects from the §3 narratives; the table below is a locator, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/spd/tray-templates` | Create a tray template (count sheet spec) | FacilityAdmin |
| GET | `/spd/tray-templates` | List tray templates | Any |
| GET | `/spd/tray-templates/{id}` | Get one tray template | Any |
| PUT | `/spd/tray-templates/{id}` | Update a tray template (OCC-guarded) | FacilityAdmin |
| GET | `/spd/tray-templates/{id}/availability` | Computed availability projection (both variants) for a window | Any |
| POST | `/spd/trays` | Register a physical tray (starts AWAITING_DECONTAMINATION) | SpdTechnician |
| GET | `/spd/trays` | List/filter trays | Any |
| GET | `/spd/trays/{id}` | Get one tray | Any |
| POST | `/spd/trays/{id}/decontamination/start` | Begin decontamination (also the QUARANTINED reprocessing entry) | SpdTechnician |
| POST | `/spd/trays/{id}/decontamination/complete` | Finish decontamination | SpdTechnician |
| POST | `/spd/trays/{id}/assembly/start` | Begin assembly | SpdTechnician |
| POST | `/spd/trays/{id}/assembly-verifications` | Submit the assembly count sheet; PASS moves tray to ASSEMBLED, FAIL keeps IN_ASSEMBLY and records a competency demerit | SpdTechnician |
| GET | `/spd/assembly-verifications` | List/filter assembly verifications | Any |
| GET | `/spd/assembly-verifications/{id}` | Get one assembly verification | Any |
| POST | `/spd/trays/{id}/discard` | Discard a quarantined tray | SpdSupervisor |
| POST | `/spd/instruments` | Register an instrument | FacilityAdmin |
| GET | `/spd/instruments` | List/filter instruments | Any |
| GET | `/spd/instruments/{id}` | Get one instrument | Any |
| POST | `/spd/instruments/{id}/assign` | Assign an instrument to a tray under assembly | SpdTechnician |
| POST | `/spd/instruments/{id}/flag-for-repair` | Flag an instrument for repair; opens a RepairOrder | SpdTechnician |
| POST | `/spd/instruments/{id}/retire` | Retire an instrument directly | FacilityAdmin |
| GET | `/spd/repair-orders` | List/filter repair orders | Any |
| GET | `/spd/repair-orders/{id}` | Get one repair order | Any |
| POST | `/spd/repair-orders/{id}/send` | Send the instrument to the vendor | FacilityAdmin |
| POST | `/spd/repair-orders/{id}/receive` | Receive the instrument back with a disposition | FacilityAdmin |
| POST | `/spd/sterilizers` | Register a sterilizer | FacilityAdmin |
| GET | `/spd/sterilizers` | List/filter sterilizers | Any |
| GET | `/spd/sterilizers/{id}` | Get one sterilizer | Any |
| POST | `/spd/sterilization-loads` | Schedule a load on a sterilizer (planned window overlap check) | SpdTechnician |
| GET | `/spd/sterilization-loads` | List/filter loads | Any |
| GET | `/spd/sterilization-loads/{id}` | Get one load | Any |
| POST | `/spd/sterilization-loads/{id}/trays` | Add an ASSEMBLED tray to a LOADING load (capacity check) | SpdTechnician |
| POST | `/spd/sterilization-loads/{id}/start` | Start the cycle (technician certification, sterilizer idle, planned-start gates) | SpdTechnician |
| POST | `/spd/sterilization-loads/{id}/complete` | Complete the cycle; auto-creates the biological indicator | SpdTechnician |
| POST | `/spd/sterilization-loads/{id}/fail-cycle` | Record a cycle parameter failure | SpdTechnician |
| POST | `/spd/sterilization-loads/{id}/abort` | Abort a load still loading | SpdTechnician |
| POST | `/spd/sterilization-loads/{id}/release` | Release a completed load after a negative BI (segregation of duties: releaser != operator) | SpdSupervisor |
| POST | `/spd/sterilization-loads/{id}/recall` | Manually recall a released load | SpdSupervisor, QualityAuditor |
| POST | `/spd/sterilization-loads/{id}/biological-indicators` | Add an extra (follow-up / spore-strip) biological indicator to a load; allowed while the load is COMPLETED or RELEASED | QualityAuditor |
| GET | `/spd/biological-indicators` | List/filter BIs | Any |
| GET | `/spd/biological-indicators/{id}` | Get one BI | Any |
| POST | `/spd/biological-indicators/{id}/record-result` | Record the incubated BI result | QualityAuditor |
| POST | `/spd/or-cases` | Schedule an OR case | OrScheduler |
| GET | `/spd/or-cases` | List/filter cases | Any |
| GET | `/spd/or-cases/{id}` | Get one case | Any |
| POST | `/spd/or-cases/{id}/reservations` | Reserve a sterile tray for a case (OCC on the case); the tray stays STERILE — the booking is temporal | OrScheduler |
| GET | `/spd/tray-reservations` | List/filter reservations | Any |
| GET | `/spd/tray-reservations/{id}` | Get one reservation | Any |
| POST | `/spd/tray-reservations/{id}/release` | Release an active reservation (compensating action of reserve; tray stays STERILE) | OrScheduler |
| POST | `/spd/or-cases/{id}/start` | Start the case (reservation or IUSS path, loaner gate, expiry gate) | OrScheduler |
| POST | `/spd/or-cases/{id}/complete` | Complete the case; instruments/trays cycle back to decontamination | OrScheduler |
| POST | `/spd/or-cases/{id}/cancel` | Cancel a non-terminal case | OrScheduler |
| POST | `/spd/iuss-exceptions` | Log an immediate-use steam sterilization exception (rolling-window supervisor gate) | SpdTechnician, SpdSupervisor |
| GET | `/spd/iuss-exceptions` | List/filter IUSS exceptions | Any |
| GET | `/spd/iuss-exceptions/{id}` | Get one IUSS exception | Any |
| POST | `/spd/iuss-exceptions/{id}/review` | Auditor review of an IUSS exception | QualityAuditor |
| POST | `/spd/technicians` | Register a technician with certifications | FacilityAdmin |
| GET | `/spd/technicians` | List/filter technicians | Any |
| GET | `/spd/technicians/{id}` | Get one technician | Any |
| PUT | `/spd/technicians/{id}` | Update certifications / renew (reactivates CERTIFICATION_EXPIRED when new expiry > now) | FacilityAdmin |
| POST | `/spd/technicians/{id}/suspend` | Suspend a technician | SpdSupervisor |
| POST | `/spd/technicians/{id}/reinstate` | Reinstate a suspended technician | SpdSupervisor |
| POST | `/spd/loaner-sets` | Book a loaner set for a case (due_by computed per tiered lead time) | OrScheduler |
| GET | `/spd/loaner-sets` | List/filter loaner sets | Any |
| GET | `/spd/loaner-sets/{id}` | Get one loaner set | Any |
| POST | `/spd/loaner-sets/{id}/receive` | Record loaner intake; branches RECEIVED vs LATE_RECEIVED on due_by | SpdTechnician |
| POST | `/spd/loaner-sets/{id}/mark-ready` | Finish loaner processing | SpdTechnician |
| GET | `/spd/compliance/summary` | Compliance KPIs over rolling windows (both IUSS rate variants) | Any |
| POST | `/_clock/set_current_utc` | Set the server's logical clock (ISO8601); startup default is exactly 2026-05-01T00:00:00Z and the clock never falls back to wall-clock time | FacilityAdmin |

## 5. Error Code Catalogue

Trigger conditions for every error live in the §2 and §3 narratives; this catalogue is a lookup of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM_VALUE` | 400 Bad Request |
| `ERR_JUSTIFICATION_TOO_SHORT` | 400 Bad Request |
| `ERR_DUPLICATE_SERIAL_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_TEMPLATE_CODE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_TRAY_NOT_READY_FOR_DECONTAMINATION` | 409 Conflict |
| `ERR_TRAY_NOT_IN_DECONTAMINATION` | 409 Conflict |
| `ERR_TRAY_NOT_DECONTAMINATED` | 409 Conflict |
| `ERR_TRAY_NOT_IN_ASSEMBLY` | 409 Conflict |
| `ERR_TRAY_NOT_ASSEMBLED` | 409 Conflict |
| `ERR_TRAY_NOT_STERILE` | 409 Conflict |
| `ERR_TRAY_NOT_QUARANTINED` | 409 Conflict |
| `ERR_LOAD_NOT_LOADING` | 409 Conflict |
| `ERR_LOAD_NOT_RUNNING` | 409 Conflict |
| `ERR_LOAD_NOT_RELEASABLE` | 409 Conflict |
| `ERR_LOAD_NOT_RECALLABLE` | 409 Conflict |
| `ERR_LOAD_EMPTY` | 409 Conflict |
| `ERR_LOAD_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_STERILIZER_NOT_IDLE` | 409 Conflict |
| `ERR_LOAD_PLANNED_START_NOT_REACHED` | 409 Conflict |
| `ERR_RELEASE_OPERATOR_SEGREGATION` | 403 Forbidden |
| `ERR_BI_NOT_PASSED` | 409 Conflict |
| `ERR_STERILITY_EXPIRED_FOR_CASE` | 409 Conflict |
| `ERR_RESERVED_TRAY_EXPIRED` | 409 Conflict |
| `ERR_BI_STILL_INCUBATING` | 409 Conflict |
| `ERR_BI_LOAD_STATE_INVALID` | 409 Conflict |
| `ERR_BI_ALREADY_RECORDED` | 409 Conflict |
| `ERR_STERILIZER_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRAY_RESERVATION_TIME_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_SUSPENDED` | 403 Forbidden |
| `ERR_CERTIFICATION_EXPIRED` | 403 Forbidden |
| `ERR_CERTIFICATION_METHOD_MISMATCH` | 403 Forbidden |
| `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` | 403 Forbidden |
| `ERR_COMPETENCY_BELOW_THRESHOLD` | 403 Forbidden |
| `ERR_TECHNICIAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_SUSPENDED` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_INSTRUMENT_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_INSTRUMENT_CYCLE_LIMIT` | 409 Conflict |
| `ERR_INSTRUMENT_NOT_RETIRABLE` | 409 Conflict |
| `ERR_REPAIR_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_REPAIR_ORDER_NOT_SENT` | 409 Conflict |
| `ERR_OUTCOME_OVERRIDE_JUSTIFICATION_REQUIRED` | 400 Bad Request |
| `ERR_CASE_NOT_RESERVABLE` | 409 Conflict |
| `ERR_CASE_NOT_STARTABLE` | 409 Conflict |
| `ERR_CASE_NOT_COMPLETABLE` | 409 Conflict |
| `ERR_CASE_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_RESERVATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_LOANER_NOT_READY` | 409 Conflict |
| `ERR_LOANER_NOT_BOOKED` | 409 Conflict |
| `ERR_LOANER_NOT_RECEIVED` | 409 Conflict |
| `ERR_IUSS_TRAY_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_IUSS_RATE_EXCEEDED` | 403 Forbidden |
| `ERR_IUSS_ALREADY_REVIEWED` | 409 Conflict |
| `ERR_CASE_TERMINAL_FOR_IUSS` | 409 Conflict |

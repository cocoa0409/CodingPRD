# Industrial Refrigeration PSM API — Product Requirements Document

## 1. Introduction

Ammonia remains the workhorse refrigerant of cold-storage warehouses, food processing plants, and beverage facilities — and it is unforgiving. A single accidental release at or above the federal reportable quantity triggers emergency notification duties measured in minutes, and an inventory that crosses the process safety threshold pulls the entire facility into the scope of process safety management and risk management program obligations. Operators of these plants therefore live or die by the quality of their records: current P&IDs and relief-design calculations, a defensible mechanical-integrity inspection history, an auditable refrigerant charge ledger, documented training and emergency drills, disciplined incident and audit cycles, and tight control over contractors performing hot work anywhere near charged piping.

This document specifies the Industrial Refrigeration PSM API, the system of record for exactly those obligations, with all resources mounted under the `/psm` prefix. The platform models each facility's ammonia charge as an append-only ledger whose running total drives threshold applicability; schedules and scores mechanical-integrity inspections; governs the lifecycle of process safety information, training records, emergency drills, incidents with their corrective actions, compliance audits, contractor qualifications, hot work permits, and leak events with their regulatory notification clocks. A computed compliance posture distills a facility's open obligations into a single gating signal, and a floating-head-pressure calculator supports energy optimization without compromising safe operating limits. Because every workflow in this document is time-aware, the platform runs on a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Six roles are recognized — `FacilityAdmin`, `PsCoordinator`, `MaintenanceLead`, `ComplianceOfficer`, `Operator`, and `ContractorRep`. A request missing either header, or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is not permitted for the target endpoint, or that fails an entity-backed ownership check, is rejected with `ERR_FORBIDDEN` (403).

The six roles divide responsibility along a strict segregation-of-duties model:

- `FacilityAdmin` is the facility administrator, owning facility, refrigeration-system, and employee master data, including refrigeration-system status changes, and sharing logical-clock control with the compliance function.
- `PsCoordinator` is the PSM coordinator, owning process safety information (P&ID) currency, training records, and emergency-response drills.
- `MaintenanceLead` is the mechanical-integrity lead, owning the equipment registry, the inspection program, contractor qualification, and the issuer side of hot work permitting — issuance and voiding, never performance.
- `ComplianceOfficer` is the compliance officer, owning incident investigation assignment and closure, corrective-action creation, the compliance audit cycle, leak confirmation and regulatory notification, and the global checkpoint run.
- `Operator` is a certified refrigeration operator — an `Employee` of a facility — who posts charge adjustments, records gauge readings, reports suspected leaks, and completes or verifies corrective actions as the pinned assignee or investigator.
- `ContractorRep` represents a `Contractor` company, requesting hot work permits and starting or closing permitted work — the performer side of the permit segregation, never the issuer.

Identity semantics differ by role. When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of the acting `Employee`; it must reference an existing employee, and ownership checks on any resource that references an employee — such as a reported-by, assignee, or investigator field — compare that field to `X-User-ID`. When `X-User-Role` is `ContractorRep`, `X-User-ID` is the `id` of the acting `Contractor`, and any permit field that references a contractor compares against it. When `X-User-Role` is `FacilityAdmin`, `PsCoordinator`, `MaintenanceLead`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit purposes but never compares it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps how many items a page carries; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter states how many items to skip and defaults to 0. Every list is returned sorted by `created_at` in ascending order. The `meta` envelope of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Server-Computed Fields

Every resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp rendered in ISO 8601 UTC with three fractional digits. Mutable resources additionally carry `updated_at`, refreshed to the logical clock on every mutation, and `version`, an integer starting from its initial value and incremented on every mutation, including mutations driven by server-side recomputation and cascades. One deliberate exception exists: the charge ledger entry is an append-only event carrying only `id` and `created_at`; both `updated_at` and `version` are absent from it, and a mistaken posting is corrected by posting a compensating entry, never by editing the original.

Many fields are server-computed rather than client-supplied — charge rollups and postures on the facility, integrity statuses on equipment, currencies on training records, notification bookkeeping on leak events, and pending-action counts on incidents among them. The platform maintains these fields itself: they refresh whenever an input changes, and time-dependent ones also refresh when the logical clock is observed on a read or swept by the checkpoint. Charge weights are carried to one tenth of a pound and pressures to one tenth of a psig, each rounded half up at the point its owning workflow declares; posture scores and counts are plain integers.

### 2.5. The Logical Clock and the Compliance Checkpoint

All time-dependent behavior — due dates, expiries, notification deadlines, training currencies — observes a single logical clock, never wall-clock time. At startup, before any call, the clock reads exactly 2026-08-01T00:00:00Z. A caller acting as `FacilityAdmin` or `ComplianceOfficer` may set the clock by supplying `to_iso8601`; the response echoes the new `current_utc`, and every derived field that depends on time observes the new clock on the next read or checkpoint.

Separately, a `ComplianceOfficer` may run the global compliance checkpoint, a sweep against the current logical clock with four marking passes and one recomputation pass. First, every inspection still `SCHEDULED` whose `due_at` lies strictly before the current time is marked `OVERDUE`, and the affected equipment's integrity status and the owning facility's posture are recomputed. Second, every contractor standing `QUALIFIED` whose `qualified_until` lies strictly before the current time is marked `EXPIRED`. Third, every hot work permit standing `ISSUED` whose `valid_until` has been reached is marked `EXPIRED`. Fourth, every confirmed leak whose notification still stands `PENDING` with a `notification_deadline_at` strictly before the current time is marked `OVERDUE`. The sweep closes by recomputing every facility's `overdue_inspection_count`, `expired_training_count`, `posture_score`, and `compliance_posture`, and its response reports the size of each marking pass as `inspections_marked_overdue`, `contractors_expired`, `permits_expired`, and `notifications_marked_overdue`.

### 2.6. The Charge Ledger: Append-Only Posting, Per-Line Rounding, and Solvency

Refrigerant charge is tracked as an append-only ledger of adjustment entries. The rounding order is pinned: each requested quantity is rounded first, per line, at posting time — to the nearest tenth of a pound, half up — and stamped onto the entry as its `rounded_lbs`; the ledger stores and sums only those rounded values. The facility's book inventory is therefore the sum of the `rounded_lbs` of every `ADD` entry minus the sum of the `rounded_lbs` of every `REMOVE` entry, taken across the facility's entire ledger with no time window. A separate gauge variant, used only for reconciliation, sums physical readings instead of ledger lines; the two variants and their divergence are described in §3.2.

Two fiscal guards protect the ledger. Every posted `quantity_lbs` must be strictly positive — a zero or negative quantity is rejected with `ERR_QUANTITY_NOT_POSITIVE` (422) — and a `REMOVE` posting may never drive the facility's book inventory below zero; a removal that would do so is rejected with `ERR_CHARGE_NEGATIVE` (422).

### 2.7. Facility Compliance Posture as a Gating Signal

Each facility carries a live compliance posture derived from three counts. The `overdue_inspection_count` tallies inspections standing `OVERDUE` whose equipment belongs to the facility's systems. The `open_incident_count` tallies the facility's incidents in any non-closed state — `REPORTED`, `UNDER_INVESTIGATION`, `ACTIONS_ASSIGNED`, or `REOPENED`. The `expired_training_count` tallies training records of the facility's `ACTIVE` employees whose expiry the clock has reached or passed.

From these counts the platform computes the `posture_score`: five points for every overdue inspection, three for every open incident, and two for every expired training record, summed as integers with no rounding. The `compliance_posture` then bands the score — `COMPLIANT` when the score is zero, `DEGRADED` when it sits between one and nine inclusive, and `NONCOMPLIANT` once it reaches ten. Posture is recomputed on every mutation of its inputs: an incident opened, closed, or reopened (including the incident a confirmed leak auto-creates), an inspection marked overdue or completed late, a checkpoint sweep, and training expiry observed at the checkpoint.

Posture is not merely reporting garnish: a facility standing `NONCOMPLIANT` may not have hot work permits issued against its systems, and the attempt is rejected with `ERR_FACILITY_NONCOMPLIANT` (409).

### 2.8. Optimistic Concurrency Control

Two write operations guard against stale client views through optimistic concurrency control, each keyed to a parent entity's `version`.

Posting a charge adjustment requires the request to carry `expected_facility_version`, the facility version the client last observed. If that value does not match the facility's current `version` — because another posting has advanced it since the client last read the facility — the request is rejected with `ERR_STALE_VERSION` (412). Ledger postings remain semantically valid in any order, so no state precondition can ever reject a stale writer; the version check is what forces the client to re-read the charge posture before posting on top of it.

Issuing a new PSI document requires the request to carry `expected_system_version`, the refrigeration system's version the client last observed. A mismatch with the system's current `version` is likewise rejected with `ERR_STALE_VERSION` (412). A later document legitimately supersedes an earlier one for the same system and document type, so a second sequential issuance is not rejectable by state; the version check is what prevents a coordinator from unknowingly superseding a revision it never saw.

No endpoint other than these two accepts a version field.

### 2.9. Validation Pipeline and Error Precedence

Requests that are structurally malformed — a missing required field, an unknown field, an invalid enum member, or an out-of-range scalar such as a `safety_score` outside 0 to 100 — are rejected with `ERR_VALIDATION` (400) as the payload is parsed. Every well-formed request is then evaluated against an ordered pipeline of checks, and a failure at any stage short-circuits every later stage, so the earliest failing check determines the error returned.

1. Authentication first: the headers are present and the role is recognized (`ERR_UNAUTHENTICATED`, 401).
2. Authorization and entity-backed ownership next: the role is permitted on the endpoint, and any identity pin holds (`ERR_FORBIDDEN`, 403).
3. Existence third: the path identifier — paths in this API carry at most one — and every resource referenced in the body resolve to real records (`ERR_NOT_FOUND`, 404).
4. The stale-version guard fourth, on the two OCC-protected writes (`ERR_STALE_VERSION`, 412).
5. Source-state validity fifth: the target stands in a state that permits the requested transition — issuance only from `REQUESTED`, permit closure only from `IN_PROGRESS`, investigator assignment only from `REPORTED` or `REOPENED`, leak confirmation only from `SUSPECTED`, and so on (`ERR_INVALID_STATE`, 409).
6. Safety and compliance gates sixth: contractor qualification, system in service, equipment integrity, facility posture, the investigator-is-not-reporter and verifier-is-not-completer segregations, and the drill training quorum (`ERR_CONTRACTOR_NOT_QUALIFIED`, `ERR_SYSTEM_OUT_OF_SERVICE`, `ERR_EQUIPMENT_INTEGRITY_FAILED`, `ERR_FACILITY_NONCOMPLIANT`, `ERR_INVESTIGATOR_IS_REPORTER`, `ERR_VERIFIER_IS_COMPLETER`, `ERR_DRILL_TRAINING_SHORTFALL`).
7. Temporal window sanity seventh: permit and drill windows well formed, qualification expiries in the future, permit starts inside the validity window (`ERR_INVALID_WINDOW`, `ERR_PERMIT_OUTSIDE_WINDOW`).
8. Resource conflicts eighth: permit window overlap on a shared system and the drill quiet gap (`ERR_PERMIT_WINDOW_CONFLICT`, `ERR_DRILL_GAP_VIOLATION`).
9. Cross-facility referential integrity ninth (`ERR_CROSS_FACILITY_REFERENCE`, 422), detailed in §2.10.
10. Fiscal and quantity rules last: ledger solvency, positive quantities, incident closure with open actions, redundant notification, and non-empty decommissioning (`ERR_CHARGE_NEGATIVE`, `ERR_QUANTITY_NOT_POSITIVE`, `ERR_ACTIONS_OPEN`, `ERR_NOTIFICATION_NOT_REQUIRED`, `ERR_SYSTEM_NOT_EMPTY`).

Because the order is fixed, a permit issuance against an out-of-service system whose window also conflicts with a neighbor reports the out-of-service gate, not the conflict; and a stale-version charge posting against a facility that would also fail solvency reports the stale version.

### 2.10. Cross-Facility Referential Integrity

Facilities are hard tenancy boundaries. Whenever a request references a refrigeration system, that system must belong to the facility named on the acted resource — this holds when posting a charge adjustment with an optional system attribution and when requesting a hot work permit. Whenever an incident report names involved equipment, the equipment's system must belong to the incident's facility. And whenever a request references employees — the reporter on an incident, the assignee on a corrective action, the investigator on an assignment, the attendee roster on a conducted drill — each must belong to the same facility as the acted resource. Any breach of these rules is rejected with `ERR_CROSS_FACILITY_REFERENCE` (422).

## 3. Business Logic & Workflows

### 3.1. Facility Master Data and Refrigeration Systems

A `FacilityAdmin` onboards a plant by creating a **Facility** with a `name` and, optionally, a `threshold_lbs` — the PSM threshold quantity in pounds, defaulting to 10000.0 when omitted. A new facility begins clean: `total_charge_lbs` at 0.0, `charge_posture` at `BELOW_THRESHOLD`, `psm_program_status` at `NOT_REQUIRED`, `compliance_posture` at `COMPLIANT`, `posture_score` at 0, and all three posture counts at zero.

Refrigeration systems are registered under a facility by the same role, each carrying the owning `facility_id`, a `name` such as "Engine Room 1", and its nameplate `design_charge_lbs`. Four tuning inputs have defaults the creator may override: `condenser_approach_f` defaults to 15.0, `min_head_psig` to 150.0, `max_head_psig` to 185.0, and `float_head_enabled` to true. A new system starts `IN_SERVICE`, and its `last_gauge_reading_lbs` and `last_gauge_reading_at` stay null until the first physical gauge reading is posted. Registering a system does not mutate the facility record — the facility's `version` is untouched by system creation.

From `IN_SERVICE`, a `FacilityAdmin` may take a system to `OUT_OF_SERVICE`, and from there either return it to `IN_SERVICE` or retire it to `DECOMMISSIONED`; the desired target is supplied as `to_status`. Any other move — decommissioning directly from `IN_SERVICE`, for instance — is rejected with `ERR_INVALID_STATE`. Decommissioning carries a precondition: the net book charge attributed to the system, meaning the signed sum of its ledger lines' `rounded_lbs`, must equal exactly zero, failing which the request is rejected with `ERR_SYSTEM_NOT_EMPTY` (409). While a system stands `OUT_OF_SERVICE` it is excluded from the gauge-variant charge rollup; once `DECOMMISSIONED` it is permanently excluded from every rollup and gate. The systems list accepts `facility_id` and `status` filters.

An `Operator` records a physical gauge reading by posting `reading_lbs` for a system; the platform stamps `last_gauge_reading_lbs` with the reading and `last_gauge_reading_at` with the logical clock. These readings feed only the gauge variant of the charge rollup — they never alter the book inventory.

### 3.2. Refrigerant Charge Accounting and the Threshold Crossing

Charge movements enter the ledger through an `Operator` posting a **ChargeAdjustment**. The payload names the `facility_id`, may optionally attribute the movement to one `system_id` of that same facility (a cross-facility attribution is rejected with `ERR_CROSS_FACILITY_REFERENCE`), declares the `adjustment_type` as `ADD` or `REMOVE`, gives a strictly positive `quantity_lbs`, a free-text `reason` such as "charging after pump-out", and the OCC token `expected_facility_version` per §2.8. On success the platform stamps the per-line `rounded_lbs` (rounded to the tenth of a pound, half up), records the acting operator as `posted_by_employee_id` from the request's `X-User-ID`, increments the facility's `version` by one, and recomputes the book inventory and charge posture. Ledger entries may be listed with `facility_id`, `system_id`, `posted_by_employee_id`, and `adjustment_type` filters.

The `total_charge_lbs` on the facility is always the book variant — the rounded `ADD` lines minus the rounded `REMOVE` lines across the ledger's unbounded history — recomputed on every successful posting. The `charge_posture` reads `AT_OR_ABOVE_THRESHOLD` whenever that book total reaches or exceeds `threshold_lbs`, and `BELOW_THRESHOLD` otherwise.

A posting that flips the posture from `BELOW_THRESHOLD` to `AT_OR_ABOVE_THRESHOLD` triggers the threshold cascade: the facility's `psm_program_status` flips to `REQUIRED` and stays there — the flag is sticky and never auto-reverts, even if the charge later drops — and the platform auto-creates a **ComplianceAudit** with `origin` `AUTO_THRESHOLD`, standing `SCHEDULED`, starting at the crossing instant, and due 1095 days (three years) after it.

For reconciliation, a computed charge-summary read on a facility returns `facility_id`, `threshold_lbs`, `book_charge_lbs`, `gauge_charge_lbs`, `delta_lbs`, and `charge_posture`, recalculating the rollup each time it is read. The book figure is the ledger variant above; the gauge figure sums, over the facility's `IN_SERVICE` systems only, each system's `last_gauge_reading_lbs`, substituting the nameplate `design_charge_lbs` for any system never gauged; `delta_lbs` records the difference between the gauge total and the book total. The two variants diverge whenever physical inventory drifts from the ledger, which is precisely what the reconciliation exists to expose.

### 3.3. Mechanical Integrity and the Inspection Cycle

A `MaintenanceLead` builds the equipment registry, creating each **Equipment** record under its system via `system_id`, with an asset `tag_number` unique within that system, an `equipment_type` of `VESSEL`, `COMPRESSOR`, `PIPING_CIRCUIT`, or `PRV`, a strictly positive `inspection_interval_days`, and an `inspection_method` of `FIXED` or `CONDITION_BASED`. Freshly registered equipment reads `integrity_status` `CURRENT`, with `last_completed_at`, `last_result`, and `next_due_at` all null until its first inspection completes. The equipment list accepts `system_id` and `integrity_status` filters.

Inspections are scheduled per equipment with an `equipment_id` and a `due_at`, landing in `SCHEDULED`. When the checkpoint finds a `SCHEDULED` inspection whose `due_at` lies strictly before the clock, it flips the inspection to `OVERDUE` and recomputes the equipment's integrity status and the facility's overdue count and posture. The inspections list filters by `equipment_id` and `status`.

Completion belongs to the `MaintenanceLead` and is accepted from either `SCHEDULED` or `OVERDUE`. The completion payload carries the `result` — `PASS` or `FAIL` — and optional `findings` notes. The platform stamps `completed_at` from the logical clock and sets `completed_late` to true only when the inspection stood `OVERDUE` at completion; an on-cycle completion from `SCHEDULED` records `completed_late` false. The equipment record absorbs the outcome: `last_completed_at` and `last_result` are set, and `next_due_at` is recomputed by method. Under `FIXED`, the next due date is exactly the base `inspection_interval_days` after completion, regardless of result. Under `CONDITION_BASED`, a `PASS` extends the interval to one and a half times the base — the product rounded down to a whole number of days — but never beyond 1095 days after completion, while a `FAIL` forces a recheck 30 days after completion.

The equipment's `integrity_status` is then re-derived: `FAILED` whenever `last_result` is `FAIL`; otherwise `OVERDUE` when a linked inspection stands `OVERDUE` or the recomputed `next_due_at` lies strictly in the past; otherwise `DUE_SOON` when `next_due_at` falls no more than 30 days ahead; otherwise `CURRENT`.

A `FAIL` result carries a safety cascade beyond the equipment record: every hot work permit on the failed equipment's system standing `ISSUED` or `IN_PROGRESS` is automatically moved to `SUSPENDED`. And when the completed inspection had stood `OVERDUE`, the facility's `overdue_inspection_count` decrements and its posture recomputes.

### 3.4. Floating Head Pressure Optimization

An `Operator` or `MaintenanceLead` may ask, on demand, what head pressure a system should target right now, supplying the current `wet_bulb_f` and `condenser_load_pct`. The computation first derates the approach temperature for high condenser load: the effective approach is the system's `condenser_approach_f` plus 5.0 degrees when the load is at least 90 percent, plus 2.5 degrees when the load is at least 75 percent but below 90, and unchanged below 75. The condensing temperature is the wet-bulb temperature plus this effective approach.

The raw saturation pressure is then read from the ammonia saturation table — 50 degrees Fahrenheit maps to 74.5 psig, 60 to 92.9, 70 to 114.1, 80 to 138.8, 90 to 166.4, and 100 to 196.6 — interpolating linearly between the bracketing table points and rounding the interpolated result once, to one tenth of a psig, half up.

What happens next depends on the system's floating-head flag. When `float_head_enabled` is false, the calculation short-circuits: the target is always the system's `max_head_psig` regardless of weather or load, and the response's `variant` reads `fixed_design`. When floating is enabled, the target clamps the raw pressure into the safe band — the greater of the raw pressure and `min_head_psig`, then the lesser of that result and `max_head_psig` — and the `variant` reads `floating`. The response reports the full working: `system_id`, `effective_approach_f`, `condensing_temp_f`, `raw_psig`, `target_psig`, and `variant`.

### 3.5. People and Paper: PSI Documents, Training, and Emergency Drills

Process safety information is versioned per system and document type. A `PsCoordinator` issues a new document with `system_id`, a `doc_type` of `PID`, `PSV_CALC`, or `RELIEF_DESIGN`, a human `revision_label` such as "Rev C", a `content_uri` locating the controlled content, and the OCC token `expected_system_version` per §2.8. The new document issues directly as `CURRENT`; any prior document for the same system-and-type pair standing `CURRENT` or `UNDER_REVIEW` is automatically moved to `SUPERSEDED` in the same operation, preserving exactly one `CURRENT` document per pair, and the system's `version` increments by one. Between issuances, a `PsCoordinator` may open a review, moving `CURRENT` to `UNDER_REVIEW`, and later reaffirm the document, returning `UNDER_REVIEW` to `CURRENT` and stamping `last_reaffirmed_at` from the logical clock (it stays null until the first reaffirmation). The document list filters by `system_id`, `doc_type`, and `status`.

People enter the system through the `FacilityAdmin`, who registers each **Employee** with a `facility_id`, a `full_name`, and an optional `employment_status` defaulting to `ACTIVE` (the only alternative is `INACTIVE`). Employees may be listed by `facility_id` and `employment_status`.

Training currency follows a three-year refresher cycle. A `PsCoordinator` records a completed course with `employee_id`, a `topic` of `PSM_OVERVIEW`, `AMMONIA_OPERATOR`, or `EMERGENCY_RESPONSE`, and the `completed_at` timestamp; the platform computes `expires_at` as exactly 1095 days after completion and derives the record's `currency` — `EXPIRED` once the clock reaches or passes `expires_at`, `EXPIRING_SOON` while expiry lies no more than 90 days ahead, and `CURRENT` otherwise. Training records list by `employee_id` and `topic`. Only expired records belonging to `ACTIVE` employees count toward the facility's `expired_training_count`.

Drills rehearse the emergency plan. A `PsCoordinator` schedules one with `facility_id`, a `drill_type` of `TABLETOP`, `FIELD`, or `EVACUATION`, and an inclusive window from `scheduled_start_at` to `scheduled_end_at`; the end must come strictly after the start, else `ERR_INVALID_WINDOW`. Scheduling also enforces a quiet period against every other `PLANNED` or `CONDUCTED` drill of the same facility: a conflict exists unless the new drill begins no earlier than 24 hours after the existing drill's scheduled end, or ends no later than 24 hours before the existing drill's scheduled start — exactly 24 hours of separation satisfies the rule in both directions — and a violating schedule is rejected with `ERR_DRILL_GAP_VIOLATION` (409). New drills stand `PLANNED`; the drill list filters by `facility_id` and `status`.

Conducting a drill moves it from `PLANNED` to `CONDUCTED`. The `PsCoordinator` supplies the `attendee_employee_ids` roster, and two guards apply: every roster entry must reference an `ACTIVE` employee of the drill's own facility (`ERR_CROSS_FACILITY_REFERENCE`), and at least two attendees must each hold an `AMMONIA_OPERATOR` training record whose currency is not `EXPIRED` at conduct time — fewer than two such attendees means rejection with `ERR_DRILL_TRAINING_SHORTFALL` (422). On success the roster is recorded on the drill and `conducted_at` is stamped from the logical clock; both stay null until then.

### 3.6. Incident Response and Corrective-Action Discipline

Anyone on the floor can raise a concern: an `Operator` or a `ComplianceOfficer` reports an **Incident** with `facility_id`, an optional involved `equipment_id` whose system must belong to that facility (`ERR_CROSS_FACILITY_REFERENCE` otherwise), a `severity` of `NEAR_MISS`, `RECORDABLE`, or `REPORTABLE`, a free-text `description`, and the `reported_by_employee_id` of an `ACTIVE` employee of the facility. When the reporter's role is `Operator`, the report must be self-attributed — the `reported_by_employee_id` must equal the request's `X-User-ID`, else `ERR_FORBIDDEN`. A new incident stands `REPORTED`; the facility's `open_incident_count` increments and its posture recomputes. Incidents list by `facility_id`, `equipment_id`, `reported_by_employee_id`, `investigator_employee_id`, `source_leak_event_id`, and `status`.

Investigation begins when a `ComplianceOfficer` assigns an investigator, moving the incident from `REPORTED` — or from `REOPENED` after a reopen cycle — to `UNDER_INVESTIGATION`. The `investigator_employee_id` must reference an `ACTIVE` employee of the same facility (`ERR_NOT_FOUND` when unknown, `ERR_CROSS_FACILITY_REFERENCE` when of another facility) and must differ from the reporter, a segregation-of-duties pin enforced as `ERR_INVESTIGATOR_IS_REPORTER` (422). Assigning from `REOPENED` replaces whatever investigator the record previously held; the field stays null until the first assignment.

Corrective work hangs off the incident. A `ComplianceOfficer` creates a **CorrectiveAction** with the parent `incident_id`, a `description` of the work, an `assignee_employee_id` who must be an `ACTIVE` employee of the incident's facility, and a `due_at`. The action opens as `OPEN`; the incident's `pending_action_count` — its tally of actions in any status other than `VERIFIED` — increments, and when the incident stood `UNDER_INVESTIGATION`, its first action moves it automatically to `ACTIONS_ASSIGNED`. Corrective actions list by `incident_id`, `assignee_employee_id`, and `status`.

Completion and verification are deliberately split. The assignee, acting in the `Operator` role with an `X-User-ID` matching the action's `assignee_employee_id` (`ERR_FORBIDDEN` otherwise), completes an `OPEN` action, moving it to `COMPLETED` and decrementing the pending count. Verification belongs to the incident's investigator: acting as an `Operator` whose `X-User-ID` matches the incident's `investigator_employee_id`, they move a `COMPLETED` action to `VERIFIED`, or reject it back to `OPEN`, which increments the pending count again. The second segregation pin forbids self-verification: when the investigator and the assignee are the same employee, a verify attempt is refused with `ERR_VERIFIER_IS_COMPLETER` (422).

Closure requires a clean sheet. From `UNDER_INVESTIGATION`, a `ComplianceOfficer`'s close succeeds only while the pending count is zero — which, since the first action would have advanced the incident, means no corrective actions exist. From `ACTIONS_ASSIGNED`, close requires every action `VERIFIED`; a nonzero `pending_action_count` is rejected with `ERR_ACTIONS_OPEN` (409). Either close decrements the facility's `open_incident_count` and recomputes its posture. A closed incident is not necessarily finished: a `ComplianceOfficer` may reopen it with a `reason`, moving `CLOSED` to `REOPENED`, incrementing its `reopen_count` (which starts at 0), raising `open_incident_count` once more, and recomputing posture — after which a fresh investigator assignment returns it to `UNDER_INVESTIGATION`.

### 3.7. Contractor Stewardship and Hot Work Permitting

Contractors are vetted before they ever touch charged equipment. A `MaintenanceLead` registers each company with a `company_name` and a `safety_score` from 0 to 100 inclusive (outside that range, `ERR_VALIDATION`); registration lands with `qualification_status` at `PENDING`, and `qualified_until` stays null until the first qualification. Qualification supplies a `qualified_until` timestamp that must lie in the future of the logical clock — a past or present timestamp is `ERR_INVALID_WINDOW` — and moves `PENDING` to `QUALIFIED`, or renews an `EXPIRED` record back to `QUALIFIED`. Suspension moves `QUALIFIED` to `SUSPENDED`; reinstatement returns `SUSPENDED` to `QUALIFIED` but only while `qualified_until` still lies in the future. Independently, the checkpoint expires any `QUALIFIED` contractor whose `qualified_until` has passed.

Hot work itself runs on a permit with a strict issuer–performer segregation. The request comes from the performing side: a `ContractorRep` supplies `facility_id`, `system_id`, `contractor_id`, a free-text `work_description`, and the validity window `valid_from` through `valid_until`. Three guards run at request time. The window is half-open — it begins at `valid_from` inclusive and ends at `valid_until` exclusive — and the start must precede the end (`ERR_INVALID_WINDOW`). The `contractor_id` must be the requester's own (`ERR_FORBIDDEN`), and the system must belong to the named facility (`ERR_CROSS_FACILITY_REFERENCE`). And the window must not collide with any other permit on the same system standing `REQUESTED`, `ISSUED`, or `IN_PROGRESS`: two windows overlap when each begins before the other ends, while touching endpoints — one window beginning exactly as another ends — do not conflict; a genuine overlap is rejected with `ERR_PERMIT_WINDOW_CONFLICT` (409). A clean request stands `REQUESTED`. Permits list by `facility_id`, `system_id`, `contractor_id`, and `status`.

Issuance is the issuer's side. A `MaintenanceLead` moves a `REQUESTED` permit to `ISSUED` only through five gates: the contractor currently `QUALIFIED` (`ERR_CONTRACTOR_NOT_QUALIFIED`), the system `IN_SERVICE` (`ERR_SYSTEM_OUT_OF_SERVICE`), no equipment on the system standing `FAILED` (`ERR_EQUIPMENT_INTEGRITY_FAILED`), the facility not `NONCOMPLIANT` (`ERR_FACILITY_NONCOMPLIANT`), and the window-conflict check re-evaluated against the live permit book, since other permits may have appeared since the request.

Starting work belongs to the performer. The permit's own `ContractorRep` — identity pinned by `contractor_id`, else `ERR_FORBIDDEN` — moves the permit from `ISSUED`, or from `SUSPENDED` when resuming interrupted work, to `IN_PROGRESS`. Three gates apply at the moment of starting: the logical clock must sit inside the window, at or after `valid_from` and strictly before `valid_until` (`ERR_PERMIT_OUTSIDE_WINDOW`, 409); the contractor must still be `QUALIFIED` (`ERR_CONTRACTOR_NOT_QUALIFIED`); and no equipment on the system may stand `FAILED` (`ERR_EQUIPMENT_INTEGRITY_FAILED`). The same representative later closes the work, moving `IN_PROGRESS` to `CLOSED`. A `MaintenanceLead` may void a permit that stands `REQUESTED` or `ISSUED`, moving it to `VOIDED`.

Two automatic paths complete the permit machine, both described where they originate: a failed inspection suspends every `ISSUED` or `IN_PROGRESS` permit on the affected system (§3.3), and the checkpoint moves an `ISSUED` permit whose `valid_until` has been reached to `EXPIRED` (§2.5). `CLOSED`, `VOIDED`, and `EXPIRED` are terminal.

### 3.8. Leak Events and Regulatory Notification

An `Operator` who suspects a release reports a **LeakEvent** with the affected `system_id`, a strictly positive `estimated_release_lbs`, and a `source_description` of where the leak was detected. The event stands `SUSPECTED` with `notification_status` `NOT_REQUIRED`, and its confirmation fields — `final_release_lbs`, `confirmed_at`, `notification_deadline_at`, `notified_at`, `auto_incident_id` — all remain null. Leak events list by `system_id`, `auto_incident_id`, and `status`.

A `ComplianceOfficer` then resolves the suspicion. Dismissing the event as `FALSE_ALARM` is terminal and carries no further effects. Confirming it requires a strictly positive `final_release_lbs` (`ERR_QUANTITY_NOT_POSITIVE` otherwise) and sets off a chain. The event moves to `CONFIRMED`, `confirmed_at` is stamped from the logical clock, and the notification obligation is computed: a confirmed quantity of at least 100 pounds — the CERCLA reportable quantity for ammonia, where exactly 100.0 qualifies — sets `notification_required` true, fixes `notification_deadline_at` at fifteen minutes after confirmation, and moves `notification_status` to `PENDING`; anything below the reportable quantity leaves the deadline null and the status `NOT_REQUIRED`. Confirmation also auto-creates an incident for the system's facility: `severity` `REPORTABLE` when the release reaches the reportable quantity, otherwise `RECORDABLE`; `reported_by_employee_id` left null as the one exception to the reporting rule of §3.6; `source_leak_event_id` pointing back at the leak; and the leak's `auto_incident_id` set to the new incident. The facility's `open_incident_count` increments and its posture recomputes, just as for a hand-filed report.

Regulatory notification is recorded as a self-transition on the `CONFIRMED` event: the leak's own status stays `CONFIRMED` while only the notification bookkeeping evolves. The call is accepted only while `notification_status` stands `PENDING` or `OVERDUE` — a notification that was never required, or one already recorded, is rejected with `ERR_NOTIFICATION_NOT_REQUIRED` (409). When accepted, `notified_at` is stamped from the logical clock, the status moves to `NOTIFIED`, and `late_notification` is computed: true only when the notification landed strictly after the deadline, since landing exactly at the deadline counts as on time. Should the clock pass the deadline while the notification is still outstanding, the checkpoint flips `PENDING` to `OVERDUE` — the obligation remains, and a late notification is still recordable through the same path.

### 3.9. The Compliance Audit Cycle

Audits arrive through two doors. A `ComplianceOfficer` schedules one manually with `facility_id`, `scheduled_start_at`, `due_at`, and the `lead_auditor`'s name; it lands `SCHEDULED` with `origin` `MANUAL`, the default origin. The threshold cascade of §3.2 opens the second door: a facility's first crossing from `BELOW_THRESHOLD` to `AT_OR_ABOVE_THRESHOLD` auto-creates an audit with `origin` `AUTO_THRESHOLD`, scheduled to start at the crossing instant and due 1095 days — three years — later.

Execution is deliberately simple. Starting an audit moves `SCHEDULED` to `IN_PROGRESS`; closing it requires a `findings_count` of zero or more — a missing or negative count is rejected with `ERR_VALIDATION` — and moves `IN_PROGRESS` to `CLOSED`. Any other sequencing, such as closing an audit never started, is `ERR_INVALID_STATE`. The audit list filters by `facility_id`, `status`, and `origin`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Every other successful operation — single-resource reads, list reads, state transitions, computed reads, the clock set, and the checkpoint run — returns `200 OK`. The request and response payloads of each endpoint are specified by the workflows of §3; this table is a navigational index, not a schema.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/psm/_clock/set_current_utc` | Set the logical clock | FacilityAdmin, ComplianceOfficer |
| POST | `/psm/facilities` | Create a facility | FacilityAdmin |
| GET | `/psm/facilities/{id}` | Get a facility with computed charge and posture fields | All roles |
| GET | `/psm/facilities/{id}/charge-summary` | Book-versus-gauge charge reconciliation for the facility | All roles |
| POST | `/psm/refrigeration-systems` | Create a refrigeration system | FacilityAdmin |
| GET | `/psm/refrigeration-systems/{id}` | Get a refrigeration system | All roles |
| GET | `/psm/refrigeration-systems` | List refrigeration systems | All roles |
| POST | `/psm/refrigeration-systems/{id}/status` | Transition system status (in service, out of service, decommissioned) | FacilityAdmin |
| POST | `/psm/refrigeration-systems/{id}/gauge-readings` | Record a physical gauge reading in pounds | Operator |
| POST | `/psm/refrigeration-systems/{id}/head-pressure-target` | Compute the floating head pressure target | Operator, MaintenanceLead |
| POST | `/psm/equipment` | Register equipment under a system | MaintenanceLead |
| GET | `/psm/equipment/{id}` | Get equipment | All roles |
| GET | `/psm/equipment` | List equipment | All roles |
| POST | `/psm/psid-documents` | Issue a new current PSI document, superseding the prior one | PsCoordinator |
| GET | `/psm/psid-documents/{id}` | Get a PSI document | All roles |
| GET | `/psm/psid-documents` | List PSI documents | All roles |
| POST | `/psm/psid-documents/{id}/start-review` | Move a current PSI document into review | PsCoordinator |
| POST | `/psm/psid-documents/{id}/reaffirm` | Reaffirm a document under review back to current | PsCoordinator |
| POST | `/psm/charge-adjustments` | Post an append-only charge ledger entry | Operator |
| GET | `/psm/charge-adjustments/{id}` | Get a charge adjustment | All roles |
| GET | `/psm/charge-adjustments` | List charge adjustments | All roles |
| POST | `/psm/inspections` | Schedule a mechanical-integrity inspection | MaintenanceLead |
| GET | `/psm/inspections/{id}` | Get an inspection | All roles |
| GET | `/psm/inspections` | List inspections | All roles |
| POST | `/psm/inspections/{id}/complete` | Complete an inspection with a pass or fail result | MaintenanceLead |
| POST | `/psm/employees` | Register an employee | FacilityAdmin |
| GET | `/psm/employees/{id}` | Get an employee | All roles |
| GET | `/psm/employees` | List employees | All roles |
| POST | `/psm/training-records` | Record completed training with computed expiry | PsCoordinator |
| GET | `/psm/training-records/{id}` | Get a training record | All roles |
| GET | `/psm/training-records` | List training records | All roles |
| POST | `/psm/drill-events` | Schedule an emergency-response drill | PsCoordinator |
| GET | `/psm/drill-events/{id}` | Get a drill event | All roles |
| GET | `/psm/drill-events` | List drill events | All roles |
| POST | `/psm/drill-events/{id}/conduct` | Conduct a planned drill with an attendee roster | PsCoordinator |
| POST | `/psm/incidents` | Report an incident or near-miss | Operator, ComplianceOfficer |
| GET | `/psm/incidents/{id}` | Get an incident | All roles |
| GET | `/psm/incidents` | List incidents | All roles |
| POST | `/psm/incidents/{id}/assign-investigator` | Assign or replace the investigator | ComplianceOfficer |
| POST | `/psm/incidents/{id}/close` | Close an incident with no pending corrective actions | ComplianceOfficer |
| POST | `/psm/incidents/{id}/reopen` | Reopen a closed incident | ComplianceOfficer |
| POST | `/psm/corrective-actions` | Create a corrective action on an incident | ComplianceOfficer |
| GET | `/psm/corrective-actions/{id}` | Get a corrective action | All roles |
| GET | `/psm/corrective-actions` | List corrective actions | All roles |
| POST | `/psm/corrective-actions/{id}/complete` | Assignee completes an open action | Operator |
| POST | `/psm/corrective-actions/{id}/verify` | Investigator verifies a completed action | Operator |
| POST | `/psm/corrective-actions/{id}/reject` | Investigator rejects a completed action back to open | Operator |
| POST | `/psm/compliance-audits` | Schedule a PSM compliance audit | ComplianceOfficer |
| GET | `/psm/compliance-audits/{id}` | Get an audit | All roles |
| GET | `/psm/compliance-audits` | List audits | All roles |
| POST | `/psm/compliance-audits/{id}/start` | Start a scheduled audit | ComplianceOfficer |
| POST | `/psm/compliance-audits/{id}/close` | Close an in-progress audit with a findings count | ComplianceOfficer |
| POST | `/psm/contractors` | Register a contractor | MaintenanceLead |
| GET | `/psm/contractors/{id}` | Get a contractor | All roles |
| POST | `/psm/contractors/{id}/qualify` | Qualify a contractor with an expiry timestamp | MaintenanceLead |
| POST | `/psm/contractors/{id}/suspend` | Suspend a qualified contractor | MaintenanceLead |
| POST | `/psm/contractors/{id}/reinstate` | Reinstate a suspended contractor | MaintenanceLead |
| POST | `/psm/hot-work-permits` | Request a hot work permit | ContractorRep |
| GET | `/psm/hot-work-permits/{id}` | Get a hot work permit | All roles |
| GET | `/psm/hot-work-permits` | List hot work permits | All roles |
| POST | `/psm/hot-work-permits/{id}/issue` | Issue a requested permit after the safety gates | MaintenanceLead |
| POST | `/psm/hot-work-permits/{id}/start` | Start permitted work inside its validity window | ContractorRep |
| POST | `/psm/hot-work-permits/{id}/close` | Close in-progress permitted work | ContractorRep |
| POST | `/psm/hot-work-permits/{id}/void` | Void a requested or issued permit | MaintenanceLead |
| POST | `/psm/leak-events` | Report a suspected ammonia leak | Operator |
| GET | `/psm/leak-events/{id}` | Get a leak event | All roles |
| GET | `/psm/leak-events` | List leak events | All roles |
| POST | `/psm/leak-events/{id}/confirm` | Confirm a leak, computing notification duties and the auto-incident | ComplianceOfficer |
| POST | `/psm/leak-events/{id}/false-alarm` | Dismiss a suspected leak as a false alarm | ComplianceOfficer |
| POST | `/psm/leak-events/{id}/notify-regulator` | Record the regulatory notification for a confirmed leak | ComplianceOfficer |
| POST | `/psm/checkpoints/run` | Run the global compliance checkpoint against the logical clock | ComplianceOfficer |

## 5. Error Code Catalogue

The catalogue below fixes every error identifier and its HTTP status. The conditions that trigger each error are specified in §2 and §3, alongside the workflows they guard.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_PERMIT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DRILL_GAP_VIOLATION` | 409 Conflict |
| `ERR_CONTRACTOR_NOT_QUALIFIED` | 422 Unprocessable Entity |
| `ERR_EQUIPMENT_INTEGRITY_FAILED` | 422 Unprocessable Entity |
| `ERR_FACILITY_NONCOMPLIANT` | 409 Conflict |
| `ERR_SYSTEM_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_INVESTIGATOR_IS_REPORTER` | 422 Unprocessable Entity |
| `ERR_VERIFIER_IS_COMPLETER` | 422 Unprocessable Entity |
| `ERR_DRILL_TRAINING_SHORTFALL` | 422 Unprocessable Entity |
| `ERR_ACTIONS_OPEN` | 409 Conflict |
| `ERR_CHARGE_NEGATIVE` | 422 Unprocessable Entity |
| `ERR_QUANTITY_NOT_POSITIVE` | 422 Unprocessable Entity |
| `ERR_CROSS_FACILITY_REFERENCE` | 422 Unprocessable Entity |
| `ERR_NOTIFICATION_NOT_REQUIRED` | 409 Conflict |
| `ERR_PERMIT_OUTSIDE_WINDOW` | 409 Conflict |
| `ERR_SYSTEM_NOT_EMPTY` | 409 Conflict |

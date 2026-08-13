# Ballast Water & Vessel Environmental Compliance API — Product Requirements Document

## 1. Introduction

US-flag vessel operators face a dense regulatory landscape for ballast water management: exchange-versus-treatment compliance determinations that vary voyage by voyage, reporting obligations tied to arrival and discharge timelines, port state control deficiency rectification workflows, and parallel record-keeping obligations for garbage, sewage, oily water, and emissions. Manual tracking across these dimensions is error-prone and exposes operators to enforcement action, detention, and civil penalties. This document specifies a compliance-audit and workflow-orchestration API that a US-flag vessel operator can use to register vessels and their ballast water management plans, record ballast water handling events per voyage, compute exchange-versus-treatment determinations, manage sampling and inspection results, track port state control deficiencies through rectification and verification, maintain statutorily required record books, evaluate fuel sulfur compliance, schedule crew drills, and respond to enforcement cases.

The system serves five distinct actor types — shore-side compliance officers, vessel masters, flag surveyors, port state control officers, and a platform administrator — with strict segregation of duties between the person who claims a deficiency rectified and the person who verifies that claim, and between the person who records a sampling inspection and the person who evaluates it. Every mutating operation flows through optimistic concurrency control where specified, and the vessel's aggregate compliance posture (`OPEN`, `RESTRICTED`, or `FROZEN`) gates which downstream operations are permitted at any moment.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` identifying the acting principal, and `X-User-Role` naming the principal's role. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The known roles are exactly these five, spelled as shown: `PlatformAdmin`, `ShoreComplianceOfficer`, `VesselMaster`, `FlagSurveyor`, and `PSCOfficer`.

All five roles use opaque identity. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform administrator owns only the test-driving clock endpoint and otherwise shares read access. When `X-User-Role` is `ShoreComplianceOfficer`, `X-User-ID` is an opaque shore-side operator identifier not compared to any entity's `id`. When `X-User-Role` is `VesselMaster`, `X-User-ID` is an opaque ship's-master identifier; the server may record it (for example, as the claimer of a rectification) but does not compare it to any entity's `id`. When `X-User-Role` is `FlagSurveyor`, `X-User-ID` is an opaque flag-state surveyor identifier not tied to any persisted entity. When `X-User-Role` is `PSCOfficer`, `X-User-ID` is an opaque port state control officer identifier; the server records it where a scaffold transition writes it but does not compare it to any entity's `id`. Segregation-of-duties checks compare `X-User-ID` values across two requests on the same entity rather than against any stored entity identifier.

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

List endpoints accept two query parameters: `limit` (default 10, minimum 1, maximum 100) and `offset` (default 0). A `limit` above 100 is clamped to 100 rather than rejected; a non-integer `limit` or `offset`, a `limit` below 1, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Results are sorted by `created_at` ascending, with ties broken by creation order. The `meta` block of a list response includes `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted entity carries a server-minted `id` that is a UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format, and a `version` integer that starts at 1 and increments by 1 on every mutation. Two entity kinds — `BallastWaterEvent` and `RecordBookEntry` — are append-only ledger records and carry only `id` and `created_at`; `updated_at` and `version` are absent from these two entities.

### 2.5. Hierarchical Path Validation and Nested Resource Retrieval

URL paths nest child resources under their ancestors (vessel, then voyage, then the voyage-scoped child). The path parameters are `vessel_id`, `voyage_id`, `plan_id`, `report_id`, `inspection_id`, `record_id`, `deficiency_id`, `book_id`, `drill_id`, and `case_id`. Path parameters are validated left to right: each segment's identifier must resolve to an existing entity, and each child must belong to the ancestor named to its left. A failure at any segment is rejected with `ERR_NOT_FOUND` (HTTP 404). An attempt to invoke a state transition that the target entity's current state does not permit is rejected with `ERR_INVALID_STATE` (HTTP 409), and a generic request-body validation failure — a missing required field, a bad type, or a bad enum value — is rejected with `ERR_VALIDATION` (HTTP 400).

### 2.6. Precision, Rounding, and Timestamp Conventions

Volumes and percentages are carried to 3 decimal places and rounded half up; this rounding is applied to a ballast water event's `volume_m3` at recording time and to a determination's volume fields, while other numeric quantities — such as a record book entry's `quantity` or an emissions record's `sulfur_content_pct` — are persisted exactly as supplied. Computed UTC deadlines and timestamps are precise to the second. Severity scores are integer arithmetic with no rounding. Sulfur boundary comparisons are inclusive: a reading of exactly 0.10 percent inside an Emission Control Area is compliant.

### 2.7. Optimistic Concurrency Control

Three write endpoints require an explicit expected-version field naming the client's last observed version of a parent entity. Creating a new plan revision requires `expected_vessel_version` matching the target vessel's current `version`. Recording a ballast water event requires `expected_voyage_version` matching the target voyage's current `version`. Claiming a deficiency rectified requires `expected_deficiency_version` matching the target deficiency's current `version`. In each case, if the supplied value does not match the parent entity's current `version` — because another writer has advanced that version since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The expected-version field must be present and an integer (otherwise `ERR_VALIDATION`), and the stale-version comparison runs after path resolution and any state-machine legality check on the target entity, and before vessel-frozen and remaining request-payload checks. Endpoints not listed here do not take a version field.

### 2.8. Vessel Compliance Posture as a Cross-Cutting Gate

Every vessel carries a derived `compliance_posture` of `OPEN`, `RESTRICTED`, or `FROZEN`. The posture is recomputed whenever a child entity mutates. A vessel is `FROZEN` when it has an active enforcement case whose `hold_flag` is true. Otherwise it is `RESTRICTED` while an enforcement case is active on the vessel, when at least one priority-one port state control deficiency is in `OPEN`, `RECTIFYING`, `RECTIFIED`, or `REOPENED` status, or when a `CRITICAL` noncompliance record detected within the last 180 days is not yet `CLOSED`. Otherwise the vessel is `OPEN`. When the posture is `FROZEN`, exactly five operations are rejected with `ERR_VESSEL_FROZEN` (HTTP 409): voyage departure, voyage arrival, recording a ballast water event, manual determination recompute, and report submission; other operations — including voyage creation, plan workflow, report acknowledgement or rejection, inspections, deficiencies, record books, emissions, drills, and noncompliance or enforcement-case workflow — are not gated by the posture.

### 2.9. Segregation of Duties

Two specific segregation rules are enforced. The same `X-User-ID` may not both claim a deficiency rectified and verify that same deficiency. The same `X-User-ID` may not both record a sampling inspection and evaluate that same inspection. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Validation Priority Ordering

When a request triggers multiple validation failures, they surface in a fixed priority order so the client sees the most fundamental problem first: authentication (401) before authorization (403), authorization before path resolution (404), path resolution before state-machine legality (409), state-machine legality before segregation-of-duties and vessel-frozen business-safety checks, and those before temporal, constraint, referential, and fiscal checks on the request payload.

## 3. Business Logic & Workflows

### 3.1. Vessel Registration and Ballast Water Management Plans

A `ShoreComplianceOfficer` registers a new US-flag vessel by supplying its `imo_number` (a unique 7-digit numeric string; a malformed or already-registered `imo_number` is rejected with `ERR_VALIDATION`, HTTP 400), `vessel_name`, `bwms_type` (one of `NONE`, `EXCHANGE_ONLY`, `TREATMENT_USCG_TYPE_APPROVED`, or `TREATMENT_ALTERNATIVE`), `gross_tonnage` (an integer at least 1), `keel_laid_date`, and `ballast_capacity_m3` (greater than 0). The `flag_state` is fixed to `US` for every vessel in this system. The `bwms_installation_date` is required if and only if `bwms_type` is not `NONE`; when `bwms_type` is `NONE` it may still be supplied and is then stored. A newly registered vessel starts with `version` 1 and `compliance_posture` `OPEN`.

Every child resource of a vessel carries a `vessel_id` tying it back to its owning vessel, and every voyage-scoped child additionally carries a `voyage_id`.

Once a vessel exists, a `ShoreComplianceOfficer` drafts a ballast water management plan revision against it. The plan carries `plan_revision` (an integer at least 1 that must be strictly greater than every existing revision for the same vessel; a regression is rejected with `ERR_PLAN_REVISION_REGRESSION`), `approval_authority` (either `USCG` or `CLASS_SOCIETY_ON_BEHALF`), `approved_at`, `exchange_distance_nm` (greater than 0; at least 200 for open-ocean exchange), and `sediment_management_included`. Because plan creation is an OCC-guarded write, the request must carry `expected_vessel_version` matching the vessel's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Creating the plan increments the vessel's `version` by 1. The plan starts in `DRAFT`.

Submission by a `ShoreComplianceOfficer` moves the plan from `DRAFT` to `SUBMITTED`, provided the vessel's `bwms_type` is not `NONE` or the plan includes sediment management procedures (a submission violating this is rejected with `ERR_INVALID_STATE`, HTTP 409); the vessel's `version` increments by 1 as a cascade. Approval by a `FlagSurveyor` moves a `SUBMITTED` plan to `APPROVED` — but only if no other plan for the same vessel is already `APPROVED` with a higher `plan_revision`, and only if approving would not leave two plans `APPROVED` at once (a violation is rejected with `ERR_MULTIPLE_APPROVED_PLANS`, HTTP 409). Approval supersedes any prior `APPROVED` plan, which transitions to `SUPERSEDED`; the newly approved plan becomes the governing plan for compliance determination; the vessel's `version` increments by 1; and a compliance determination is recomputed for every non-terminal voyage of the vessel with trigger reason `PLAN_AMENDMENT`, incrementing each such voyage's `version` by 1. A plan in `DRAFT` or `SUBMITTED` may be withdrawn by a `ShoreComplianceOfficer`, moving it to `WITHDRAWN` (without changing the vessel's `version`); both `SUPERSEDED` and `WITHDRAWN` are terminal.

### 3.2. Voyage Lifecycle and Ballast Water Events

A voyage is created against a vessel by a `ShoreComplianceOfficer` or `VesselMaster`, supplying `voyage_number` (unique per vessel; a duplicate is rejected with `ERR_DUPLICATE_VOYAGE_NUMBER`, HTTP 409), `departure_port` and `arrival_port` as UN/LOCODEs (accepted as opaque non-empty strings without format validation), `departed_at`, optionally `arrived_at`, and the two routing flags `crosses_captain_of_port_zones` and `enters_us_eez`. A new voyage starts with `compliance_status` `PENDING` and `reporting_status` `NOT_DUE`.

Departure by the `VesselMaster` moves the voyage from `PENDING` to `IN_PROGRESS`. Three preconditions gate departure: the voyage must still be `PENDING`; the vessel's `compliance_posture` must not be `FROZEN`; and the vessel must have at least one plan in `APPROVED` state (departure without one is rejected with `ERR_INVALID_STATE`, HTTP 409). On departure the system computes a compliance determination with trigger reason `VOYAGE_DEPARTURE`, creates a voyage-scoped record book of kind `BALLAST_WATER` in `OPEN` status, and flips the voyage's `reporting_status` from `NOT_DUE` to `DUE` while instantiating a `PRE_ARRIVAL` report in `DRAFT` whose deadline is 24 hours before `arrived_at`; if `arrived_at` is not yet known, the report's `due_at` stays null, and arrival fills it — only if still null — to 24 hours before the recorded `arrived_at`.

While the voyage is underway, the `VesselMaster` records ballast water events; event recording is not gated on the voyage's `compliance_status` — only the OCC, vessel-frozen, and payload checks described here apply. Each event carries `event_kind` (one of `UPTAKE`, `DISCHARGE`, `EXCHANGE_START`, `EXCHANGE_COMPLETE`, `TREATMENT_START`, `TREATMENT_COMPLETE`, `TANK_FLUSH`, or `SEDIMENT_DISPOSAL`), `occurred_at`, `tank_id`, and `volume_m3` (greater than 0, checked against the supplied value before rounding). The event's `volume_m3` is rounded half up to 3 decimal places when the event is recorded, and that carried value is what is persisted on the event; the chronological per-tank balance check, the single-event capacity check, and the compliance determination's volume sums all operate on the carried per-event values, so rounding applies to each event before any summation. `EXCHANGE_START`, `EXCHANGE_COMPLETE`, and `DISCHARGE` events also require `latitude` and `longitude`, which must be numbers. `EXCHANGE_COMPLETE` and `DISCHARGE` additionally require `distance_from_shore_nm`, a number at least 0. `UPTAKE` events require `salinity_ppt` (a number at least 0) and `source_port_locode` (a non-empty string). Because event recording is OCC-guarded, the request must carry `expected_voyage_version` matching the voyage's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). Persisting an event increments the voyage's `version` by 1 and triggers a recomputation of the compliance determination with trigger reason `BALLAST_EVENT_RECORDED`.

Several payload validations guard event recording, surfacing in the priority order established in §2.10 after the earlier auth, path, state, and safety gates. The `occurred_at` must fall within the voyage window — from 6 hours before `departed_at` to 6 hours after `arrived_at`, both ends inclusive, with no upper window bound while `arrived_at` is unknown — and may not be in the future; a violation is rejected with `ERR_EVENT_OUT_OF_WINDOW` (HTTP 422). A `DISCHARGE` on a tank must have at least one prior `UPTAKE` on the same `tank_id` — an `UPTAKE` whose `occurred_at` is at or before the discharge's counts; otherwise the request is rejected with `ERR_DISCHARGE_WITHOUT_UPTAKE` (HTTP 422). An `EXCHANGE_COMPLETE` whose `distance_from_shore_nm` is less than 3 nautical miles is physically implausible for inshore exchange and is rejected with `ERR_EXCHANGE_TOO_CLOSE` (HTTP 422). The chronological per-tank balance — cumulative uptake minus cumulative discharge on that tank, replayed in `occurred_at` order with the new event applied after existing events that share its `occurred_at` — must never go negative at any point in the voyage's event timeline; a violation is rejected with `ERR_TANK_BALANCE_NEGATIVE` (HTTP 422). And no single event's `volume_m3` may exceed the vessel's `ballast_capacity_m3`; a violation is rejected with `ERR_VOLUME_EXCEEDS_CAPACITY` (HTTP 422).

### 3.3. Exchange-Versus-Treatment Compliance Determination

The compliance determination is the heart of the ballast water workflow. It recomputes on voyage departure, on every recorded ballast event, on voyage arrival, on plan approval (as `PLAN_AMENDMENT`), and on manual recompute. The governing plan is the vessel's highest-`plan_revision` plan in `APPROVED` state.

The computation walks the voyage's ballast events ordered by `occurred_at` ascending, breaking ties by `created_at` ascending. The `total_discharged_volume_m3` is the sum of all `DISCHARGE` event volumes. Each `DISCHARGE` is attributed to the most recent `UPTAKE` on the same `tank_id` whose `occurred_at` is at or before the discharge's; a discharge with no such uptake on its tank is unattributed and counts toward `noncompliant_volume_m3`. For an attributed discharge, two paths are checked. The treatment path is satisfied when a `TREATMENT_COMPLETE` exists on the same tank whose `occurred_at` falls between the source uptake's `occurred_at` and the discharge's `occurred_at`, both ends inclusive. The exchange path is satisfied when an `EXCHANGE_COMPLETE` exists on the same tank in the same (inclusive) time window and its `distance_from_shore_nm` is at least the governing plan's `exchange_distance_nm` and at least 200 nautical miles — the open-ocean exchange-area test is applied to the event's `distance_from_shore_nm`; while no plan is `APPROVED`, the exchange path cannot be satisfied.

Two voyage-level exemptions short-circuit the per-discharge walk and are checked in this order: if the voyage's `enters_us_eez` is false, the determination basis is `EXEMPT_NO_US_EEZ`; otherwise, if the voyage does not cross Captain of the Port zones, the basis is `EXEMPT_SAME_COTP` (such a voyage stays within a single zone, so the source uptake port and discharge port are necessarily within the same zone). For an exempt basis the walk is skipped, so the three classified volumes are each 0.000 while `total_discharged_volume_m3` still sums the voyage's `DISCHARGE` events.

For each attributed, non-exempt discharge: if only the treatment path is satisfied, the volume adds to `treatment_compliant_volume_m3`; if only the exchange path is satisfied, it adds to `exchange_compliant_volume_m3`; if both are satisfied, treatment is preferred (the more stringent standard) and the volume adds to `treatment_compliant_volume_m3`; if neither is satisfied, it adds to `noncompliant_volume_m3`. The final `determination_basis` is `TREATMENT_COMPLIANT` when the noncompliant volume is zero and at least some volume is treatment-compliant (including the case where both compliant volumes are positive, since treatment is preferred); `EXCHANGE_COMPLIANT` when the noncompliant and treatment-compliant volumes are both zero and the exchange-compliant volume is positive; `NONCOMPLIANT_MIXED` when the noncompliant volume is positive and at least one of the compliant volumes is also positive; `NONCOMPLIANT_NO_METHOD` when the noncompliant volume is positive and no compliant volume exists; and `INSUFFICIENT_DATA` when there is nothing to classify (the provisional case at departure, before any discharge exists). All volumes are carried to 3 decimal places, rounded half up.

Each recomputation writes a new determination row with `computed_at` set to the current UTC, `trigger_reason` recording why it ran, and `is_current` true for the newest row per voyage (only one row is current at a time); the voyage's `determination_id` points at the current row.

On arrival — recorded by the `VesselMaster` supplying `arrived_at` — the determination is recomputed with trigger reason `VOYAGE_ARRIVAL` and the voyage's `compliance_status` commits, with the outcome chosen in this order. If the latest basis is `EXCHANGE_COMPLIANT` or `TREATMENT_COMPLIANT`, the voyage transitions `IN_PROGRESS` to `COMPLIANT` and the vessel's `version` increments, regardless of any open noncompliance records. Otherwise, if the basis is `NONCOMPLIANT_MIXED` or `NONCOMPLIANT_NO_METHOD`, or any `OPEN` noncompliance record for the voyage has severity `MAJOR` or `CRITICAL`, the voyage transitions to `NONCOMPLIANT`; a noncompliance record with `source_type` `DETERMINATION_NONCOMPLIANT` is created if one is not already present, and the vessel's `version` increments. Otherwise, if the basis is `EXEMPT_SAME_COTP` or `EXEMPT_NO_US_EEZ`, the voyage transitions to `EXEMPT` (the vessel's `version` does not increment). Any other basis — `INSUFFICIENT_DATA` with no `OPEN` `MAJOR` or `CRITICAL` record — leaves the voyage `IN_PROGRESS`. A manual recompute by a `ShoreComplianceOfficer` or `FlagSurveyor` runs the same algorithm with trigger reason `MANUAL_RECOMPUTE`, updates the voyage's `determination_id`, and increments the voyage's `version`.

### 3.4. Reporting Obligations and Deadlines

Each voyage carries a parallel `reporting_status` axis — `NOT_DUE`, `DUE`, `SUBMITTED`, `ACKNOWLEDGED`, or `OVERDUE` — independent of `compliance_status`. Three values of `report_type` exist. A `PRE_ARRIVAL` report is due 24 hours before `arrived_at`. A `POST_DISCHARGE` report is due 6 hours after the last `DISCHARGE` event on the voyage; it is instantiated in `DRAFT` when the voyage's first `DISCHARGE` is recorded, and while it remains `DRAFT` each subsequently recorded `DISCHARGE` moves its `due_at` to 6 hours after that event. An `ANNUAL_SUMMARY` report would be due January 31 at 23:59:59 UTC following the calendar year end, aggregating across all voyages in that calendar year rather than sitting on a single voyage, but the system never instantiates one — only `PRE_ARRIVAL` and `POST_DISCHARGE` reports are ever created.

A report in `DRAFT` whose deadline passes while still unsubmitted flips the voyage's `reporting_status` to `OVERDUE` and creates a noncompliance record with `source_type` `REPORT_OVERDUE`; the `reporting_status` flip occurs only from `DUE`, while the `REPORT_OVERDUE` record is created once per overdue report regardless of the voyage's current `reporting_status`. The report's own `is_overdue` flag is true exactly when its `status` is `DRAFT` and the current UTC is past `due_at`.

Submission by the `VesselMaster` — carrying the free-form `payload_summary`, which must be present (any non-null JSON value) — requires the report to be in `DRAFT` and the voyage's `reporting_status` to be `DUE` or `OVERDUE`. Submission sets `submitted_at` to the current UTC, moves the report from `DRAFT` to `SUBMITTED`, and flips the voyage's `reporting_status` to `SUBMITTED`. A `FlagSurveyor` may then acknowledge the report, moving it from `SUBMITTED` to `ACKNOWLEDGED` and the voyage's `reporting_status` to `ACKNOWLEDGED`; or reject it with a `rejection_reason` (a required non-empty string), moving the report to `REJECTED` and returning the voyage's `reporting_status` to `DUE` so the master must resubmit. Both `ACKNOWLEDGED` and `REJECTED` are terminal for the report.

### 3.5. Sampling, Inspection, and Exceedance Response

A `PSCOfficer` or `FlagSurveyor` records a sampling inspection against a voyage, supplying `inspection_kind` (one of `PORT_STATE_CONTROL`, `FLAG_STATE`, `CLASS_SOCIETY`, or `COMPANY_INTERNAL`), `sampled_at`, `sampled_by_role` (one of `PSC_OFFICER`, `FLAG_SURVEYOR`, or `COMPANY_AUDITOR`), `indicator_organism_concentration` (at least 0), `tss_mg_per_l` (at least 0), and `findings` (an array of finding codes, empty when clean). The inspection starts in `RECORDED` with `exceeded` null until evaluation. Recording the inspection also updates the vessel's `last_psc_inspection_at` to the inspection's `sampled_at` when the kind is `PORT_STATE_CONTROL`, without incrementing the vessel's `version`.

Evaluation by a `FlagSurveyor` moves the inspection from `RECORDED` to `EVALUATED` and computes the `exceeded` flag. The statutory threshold is an indicator organism concentration of 10 cfu/100mL and a total suspended solids level of 50 mg/L; a reading at or above either limit — 10 exactly counts as an exceedance — sets `exceeded` true. For `COMPANY_INTERNAL` inspections the company applies stricter limits of 5 cfu/100mL and 25 mg/L. Segregation of duties forbids the same `X-User-ID` that recorded the inspection from evaluating it; a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

When `exceeded` is true, evaluation cascades: if the inspection kind is `PORT_STATE_CONTROL`, a port state control deficiency is created with `action_code` defaulting to `A15`, `deficiency_code` `14806`, `identified_at` set to the inspection's `sampled_at`, a `rectification_deadline` 14 days later, and `is_priority_one` true; a noncompliance record with `source_type` `SAMPLING_EXCEEDANCE` is created; and the vessel's `compliance_posture` is recomputed (it may become `RESTRICTED`). Closing by a `FlagSurveyor` moves the inspection from `EVALUATED` to `CLOSED` — but if `exceeded` is true, every linked noncompliance record must first be `RESPONDED` or `CLOSED`; the vessel's `version` increments on close. A closed inspection may be reopened by a `FlagSurveyor` within 90 days of `sampled_at` (up to and including `sampled_at` plus 90 days), moving it from `CLOSED` to `REOPENED`; reopening flips any noncompliance record previously closed under the inspection back from `CLOSED` to `OPEN` and recomputes the vessel's posture.

### 3.6. Port State Control Deficiency Rectification

A deficiency is identified against a vessel during a voyage, linked to the PSC inspection that found it via `psc_inspection_id`, and carries a `deficiency_code`, an `action_code`, and `identified_at`. The action code drives the `rectification_deadline`: `A10` means rectify before departure (the deadline is the voyage's `departed_at` if the vessel has not yet departed, otherwise `identified_at` itself); `A15` allows 14 days from `identified_at`; `A16` allows 30 days; `A17` allows 7 days; `A99` allows 21 days. The `is_priority_one` flag is true exactly when the action code is `A10` or `A15` — these block departure and feed the vessel's compliance posture.

The deficiency's `rectification_status` runs `OPEN` to `RECTIFYING` to `RECTIFIED` to `VERIFIED`, with `REOPENED` reachable from `RECTIFIED` on rejection. Beginning rectification by the `VesselMaster` moves the deficiency from `OPEN` to `RECTIFYING` and increments the vessel's `version`. Claiming rectification by the `VesselMaster` moves it from `RECTIFYING` to `RECTIFIED` and stamps `rectified_at`; this claim is OCC-guarded and must carry `expected_deficiency_version` matching the deficiency's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412). Verification by a `PSCOfficer` moves the deficiency from `RECTIFIED` to `VERIFIED` and stamps `verified_at`; segregation of duties forbids the verifying officer from being the same `X-User-ID` that claimed rectification, with a violation rejected as `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Verification recomputes the vessel's posture — if the deficiency was priority-one and every other priority-one deficiency is now `VERIFIED`, the posture may lift from `RESTRICTED` back to `OPEN`. Alternatively, a `PSCOfficer` may reject the verification, moving the deficiency from `RECTIFIED` back toward `OPEN` via `REOPENED`, extending the `rectification_deadline` by 7 days, and recomputing the vessel's posture.

### 3.7. Record Books and Statutory Entries

Four kinds of record book exist, identified by `book_kind`: `BALLAST_WATER`, `GARBAGE`, `SEWAGE`, and `OILY_WATER`. The ballast water book is voyage-scoped and auto-created on departure; the voyage's `bw_record_book_id` points at it. Standing ship-level books of the other three kinds are created explicitly by a `ShoreComplianceOfficer` or `VesselMaster` with an optional `voyage_id`; requesting `book_kind` `BALLAST_WATER` through that endpoint is rejected with `ERR_VALIDATION` (HTTP 400), and a supplied `voyage_id` must resolve to a voyage of the same vessel, likewise `ERR_VALIDATION`. A new book starts `OPEN`.

Entries are appended to a book by the `VesselMaster`. Each entry names its book via `record_book_id` and carries `entry_kind`, `occurred_at`, `quantity` (greater than 0, interpreted as cubic meters or kilograms depending on kind), `signed_by`, and optionally `countersigned_by`, `position_lat`, `position_lon`, and `distance_from_shore_nm`. The allowed entry kinds depend on the book: a `BALLAST_WATER` book accepts `UPTAKE`, `DISCHARGE`, `EXCHANGE`, `TREATMENT`, and `TANK_FLUSH`; a `GARBAGE` book accepts `DISCHARGE_SEA`, `DISCHARGE_RECEPTION`, and `INCINERATION`; a `SEWAGE` book accepts `DISCHARGE_TREATED` and `DISCHARGE_UNTREATED`; an `OILY_WATER` book accepts `BILGE_DISCHARGE`, `SLUDGE_DISPOSAL`, and `ODM_FLUSH`. An entry kind not allowed for the book's kind is rejected with `ERR_ENTRY_KIND_MISMATCH` (HTTP 422). Position coordinates are required for the discharge-type entries — `DISCHARGE`, `DISCHARGE_SEA`, `DISCHARGE_RECEPTION`, `DISCHARGE_TREATED`, `DISCHARGE_UNTREATED`, and `BILGE_DISCHARGE` — and `distance_from_shore_nm` is required for `DISCHARGE_SEA`, `DISCHARGE_UNTREATED`, and `BILGE_DISCHARGE`; a missing position or distance is rejected with `ERR_VALIDATION` (HTTP 400). A countersignature is required for `OILY_WATER` and `SEWAGE` entries; this requirement is enforced at sealing rather than at append, so an entry may be recorded without it and it is the seal operation that is rejected — with `ERR_INVALID_STATE` (HTTP 409) — while any entry in an `OILY_WATER` or `SEWAGE` book lacks one.

Sealing by the `VesselMaster` moves a book from `OPEN` to `SEALED`, after which it is immutable and archived; the vessel's `version` increments. Sealing requires the book to be `OPEN`; for a `BALLAST_WATER` book, the voyage's `compliance_status` must be `COMPLIANT`, `NONCOMPLIANT`, or `EXEMPT`; and every entry in the book must carry its required countersignature. Appending to a sealed book is rejected with `ERR_BOOK_SEALED` (HTTP 409).

### 3.8. Emissions and Fuel Sulfur Compliance

The `VesselMaster` records fuel consumption for a voyage, supplying `fuel_type` (one of `HFO`, `VLSFO`, `MGO`, `MDO`, `LNG`, or `BIOFUEL_BLEND`), `sulfur_content_pct` (at least 0 and at most 5.0 — outside that range the request is rejected with `ERR_SULFUR_OUT_OF_RANGE`, HTTP 422), `consumed_volume_mt` (greater than 0), `inside_eca_hours` and `outside_eca_hours` (both at least 0), and `scrubber_installed`. The record starts in `PENDING_EVAL`.

Evaluation by a `ShoreComplianceOfficer` resolves the record to `COMPLIANT`, `NONCOMPLIANT`, or `EXEMPT_SCRUBBER`. The sulfur limits are 0.10 percent inside an Emission Control Area and 0.50 percent outside. When a scrubber is installed, the record is `EXEMPT_SCRUBBER` whenever any `inside_eca_hours` were logged, and simply `COMPLIANT` when none were; EGCS operating hours are not separately recorded, so no operating-time ratio is verified. Without a scrubber, no weighted average across zones is permitted: the fuel must satisfy the strictest applicable zone for the hours burned. The record is compliant when either no ECA hours were logged or the sulfur content is at most 0.10 percent — and in all cases the sulfur content is at most 0.50 percent. A boundary reading of exactly 0.10 percent is compliant. For `BIOFUEL_BLEND`, the supplied sulfur content is taken as the blend-weighted average and compared against the same limits directly; no pro rata split of consumption is performed. Only a `COMPLIANT` evaluation increments the vessel's `version` (an `EXEMPT_SCRUBBER` outcome does not); a noncompliant evaluation creates a noncompliance record with `source_type` `DETERMINATION_NONCOMPLIANT` and recomputes the vessel's posture.

### 3.9. Crew Training and Drills

Drills are scheduled against a vessel by a `ShoreComplianceOfficer` or `VesselMaster`, supplying `drill_kind` (one of `BWMS_OPERATION`, `EMERGENCY_BALLAST_EXCHANGE`, `OIL_SPILL_RESPONSE`, `SEWAGE_SYSTEM`, `GARBAGE_MANAGEMENT`, or `MARPOL_AWARENESS`), `scheduled_for`, and `attendees`. The drill's `completion_status` starts `SCHEDULED`.

Completion by the `VesselMaster` — optionally supplying `completed_at` (defaulting to the current UTC) and the final `attendees` list (defaulting to the scheduled list) — moves the drill from `SCHEDULED` to `COMPLETED`, stamps `completed_at`, and computes `next_due_at` as `completed_at` plus the drill's recurrence interval: 90 days for `BWMS_OPERATION`, 180 days for `EMERGENCY_BALLAST_EXCHANGE`, 90 days for `OIL_SPILL_RESPONSE`, 180 days for `SEWAGE_SYSTEM`, 180 days for `GARBAGE_MANAGEMENT`, and 365 days for `MARPOL_AWARENESS`. For a `BWMS_OPERATION` drill the `officer_present` flag must be true — the attendee list must include at least one officer, where an attendee counts as an officer when it is a string containing "officer" (case-insensitively), or an object whose `rank`, `role`, `title`, or `position` contains "officer", or an object with `officer` or `is_officer` set true — or the completion is rejected with `ERR_OFFICER_REQUIRED` (HTTP 422). A drill still `SCHEDULED` more than 30 days past `scheduled_for` flips to `OVERDUE`, and if the drill is `BWMS_OPERATION` or `OIL_SPILL_RESPONSE`, a noncompliance record with `source_type` `MISSING_METHOD` is created, linked to the drill via `source_id` and carrying no `voyage_id`. A drill may be cancelled by the `VesselMaster` while still `SCHEDULED` and no later than `scheduled_for`, moving it to `CANCELLED`.

### 3.10. Noncompliance Response and Enforcement Escalation

A noncompliance record is created by the system whenever a sampling exceedance, overdue report, missing method, PSC deficiency, or noncompliant determination warrants one; its `source_type` names the trigger and its `source_id` points at the triggering entity, and its `response_status` starts `OPEN`. Its `severity` — `MINOR`, `MAJOR`, or `CRITICAL` — is derived from a weighted score at detection time. A sampling exceedance contributes 40 points, a PSC deficiency 30, a noncompliant determination 25, an overdue report 10, and a missing method 15. If the voyage already has a prior noncompliance record that escalated, 25 more points are added; if the vessel's posture was `RESTRICTED` at detection time, 15 more. A score of at least 70 yields `CRITICAL`; at least 40 yields `MAJOR`; otherwise `MINOR`. The response deadline is 30 days from `detected_at` for `MINOR`, 14 days for `MAJOR`, and 72 hours for `CRITICAL`.

Response by a `ShoreComplianceOfficer` moves the record from `OPEN` to `RESPONDED`, provided the response arrives by `response_due_at` — a response after the deadline is rejected with `ERR_INVALID_STATE` (HTTP 409); the vessel's `version` increments. Closure by a `FlagSurveyor` moves a `RESPONDED` record to `CLOSED` and recomputes the vessel's posture. Escalation is system-driven: an `OPEN` record escalates when more than 7 days have passed since `response_due_at`, or when a `CRITICAL` record has gone 24 hours without response (24 hours since its `detected_at`). Escalation creates an enforcement case if none is active (otherwise attaching to the existing active case) — an escalation-created case opens with `severity` `NOTICE_OF_VIOLATION` and `hold_flag` false — flips the record's `response_status` to `ESCALATED`, sets the record's `escalated_to_case_id`, sets the vessel's `active_enforcement_case_id`, and flips the vessel's posture to `FROZEN` if the case's `hold_flag` is true, otherwise `RESTRICTED`.

### 3.11. Enforcement Cases

An enforcement case is opened against a vessel with `opened_at`, `opened_reason`, `severity` (one of `NOTICE_OF_VIOLATION`, `CIVIL_PENALTY`, or `DETENTION_ORDER`), and `hold_flag`. The `hold_flag` may be true only for a `DETENTION_ORDER`; when true it forces the vessel's posture to `FROZEN`. The case starts `ACTIVE` and carries `linked_noncompliance_ids` referencing the records escalated into it.

Submitting a response by a `ShoreComplianceOfficer` moves the case from `ACTIVE` to `UNDER_REVIEW` and increments the vessel's `version`. Closure by a `FlagSurveyor` moves the case from `UNDER_REVIEW` to `CLOSED_COMPLIANT` — or to `CLOSED_PENALTY` when the closure request carries `penalty_assessed` true (`penalty_assessed` is optional, defaults to false, and a non-boolean value is rejected with `ERR_VALIDATION`, HTTP 400). Closing as `CLOSED_COMPLIANT` requires every linked noncompliance record to be `CLOSED`; closing as `CLOSED_PENALTY` imposes no such requirement. Either closure stamps `closed_at`, clears the vessel's `active_enforcement_case_id`, and recomputes the vessel's posture. Withdrawal by a `FlagSurveyor` moves an `ACTIVE` case to `WITHDRAWN`, likewise stamping `closed_at`, clearing `active_enforcement_case_id`, and recomputing posture.

### 3.12. Logical Clock for Time-Derived Transitions

The server runs on a logical clock that starts at 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `PlatformAdmin` may advance the clock by supplying `to_iso8601`; the clock is set to exactly the supplied value and the endpoint returns HTTP 200 with an empty data object. Advancing the clock re-evaluates every time-derived transition: reports whose deadline has passed flip their voyage to `OVERDUE` and spawn the corresponding noncompliance record; drills more than 30 days past schedule flip to `OVERDUE` and spawn `MISSING_METHOD` records where applicable; and open noncompliance records past their escalation threshold escalate into enforcement cases.

## 4. Endpoint Definitions

All endpoints live under the `/vessels` prefix except the clock endpoint. Creating a new resource returns HTTP 201; modifying an existing resource returns HTTP 200. Every mutating endpoint enforces the validation priority order of §2.10, and the OCC-guarded writes of §2.7 require their expected-version field. List endpoints additionally accept exact-match query filters: vessels — `imo_number`, `compliance_posture`; plans — `status`; voyages — `compliance_status`, `reporting_status`; ballast-events — `event_kind`, `tank_id`; determinations — `is_current`; reports — `report_type`, `status`; inspections — `inspection_kind`, `status`; noncompliance — `response_status`, `severity`; deficiencies — `rectification_status`, `is_priority_one`; record-books — `book_kind`, `status`, `voyage_id`; entries — `entry_kind`; emissions — `compliance_status`; drills — `drill_kind`, `completion_status`; enforcement-cases — `status`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Advance the server logical clock | PlatformAdmin |
| POST | /vessels | Register a new US-flag vessel | ShoreComplianceOfficer |
| GET | /vessels | List vessels with pagination and filters | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor, PlatformAdmin |
| GET | /vessels/{vessel_id} | Fetch a single vessel | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor, PlatformAdmin |
| POST | /vessels/{vessel_id}/plans | Create a new plan revision in DRAFT | ShoreComplianceOfficer |
| GET | /vessels/{vessel_id}/plans | List plans for a vessel | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| GET | /vessels/{vessel_id}/plans/{plan_id} | Fetch one plan | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/plans/{plan_id}/submit | Submit a plan for approval | ShoreComplianceOfficer |
| POST | /vessels/{vessel_id}/plans/{plan_id}/approve | Approve a submitted plan, superseding any prior | FlagSurveyor |
| POST | /vessels/{vessel_id}/plans/{plan_id}/withdraw | Withdraw a DRAFT or SUBMITTED plan | ShoreComplianceOfficer |
| POST | /vessels/{vessel_id}/voyages | Create a voyage in PENDING | ShoreComplianceOfficer, VesselMaster |
| GET | /vessels/{vessel_id}/voyages | List voyages for a vessel | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| GET | /vessels/{vessel_id}/voyages/{voyage_id} | Fetch a voyage | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/depart | Mark voyage departed; fires departure determination | VesselMaster |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/arrive | Mark voyage arrived; commits final determination | VesselMaster |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/ballast-events | Record a ballast water event | VesselMaster |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/ballast-events | List ballast events for a voyage | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/determinations | List determinations for a voyage, newest first | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/determinations/recompute | Manually trigger recomputation | ShoreComplianceOfficer, FlagSurveyor |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/reports | List reports for a voyage | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/submit | Submit a DRAFT report | VesselMaster |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/acknowledge | Acknowledge a submitted report | FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/reports/{report_id}/reject | Reject a submitted report | FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/inspections | Record a sampling or inspection | PSCOfficer, FlagSurveyor |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/inspections | List inspections | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/evaluate | Evaluate a recorded inspection | FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/close | Close an evaluated inspection | FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/inspections/{inspection_id}/reopen | Reopen a closed inspection within 90 days | FlagSurveyor |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/noncompliance | List noncompliance records for a voyage | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/noncompliance/{record_id}/respond | Respond to an OPEN noncompliance | ShoreComplianceOfficer |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/noncompliance/{record_id}/close | Close a RESPONDED noncompliance | FlagSurveyor |
| GET | /vessels/{vessel_id}/deficiencies | List deficiencies for a vessel | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/deficiencies/{deficiency_id}/begin-rectification | Mark deficiency rectification started | VesselMaster |
| POST | /vessels/{vessel_id}/deficiencies/{deficiency_id}/claim-rectified | Master claims rectification complete | VesselMaster |
| POST | /vessels/{vessel_id}/deficiencies/{deficiency_id}/verify | PSC verifies rectification | PSCOfficer |
| POST | /vessels/{vessel_id}/deficiencies/{deficiency_id}/reject-verification | PSC rejects rectification claim | PSCOfficer |
| POST | /vessels/{vessel_id}/record-books | Create a standing record book | ShoreComplianceOfficer, VesselMaster |
| GET | /vessels/{vessel_id}/record-books | List record books for a vessel | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/record-books/{book_id}/entries | Append an entry to a record book | VesselMaster |
| GET | /vessels/{vessel_id}/record-books/{book_id}/entries | List entries in a book | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/record-books/{book_id}/seal | Seal a record book | VesselMaster |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/emissions | Create an emissions/fuel record | VesselMaster |
| GET | /vessels/{vessel_id}/voyages/{voyage_id}/emissions | List emissions records for a voyage | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/voyages/{voyage_id}/emissions/{record_id}/evaluate | Evaluate an emissions record | ShoreComplianceOfficer |
| POST | /vessels/{vessel_id}/drills | Schedule a drill | ShoreComplianceOfficer, VesselMaster |
| GET | /vessels/{vessel_id}/drills | List drills | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/drills/{drill_id}/complete | Mark drill completed | VesselMaster |
| POST | /vessels/{vessel_id}/drills/{drill_id}/cancel | Cancel a scheduled drill | VesselMaster |
| GET | /vessels/{vessel_id}/enforcement-cases | List enforcement cases | ShoreComplianceOfficer, VesselMaster, PSCOfficer, FlagSurveyor |
| POST | /vessels/{vessel_id}/enforcement-cases/{case_id}/submit-response | Operator submits response | ShoreComplianceOfficer |
| POST | /vessels/{vessel_id}/enforcement-cases/{case_id}/close | Close case as compliant or penalty | FlagSurveyor |
| POST | /vessels/{vessel_id}/enforcement-cases/{case_id}/withdraw | Withdraw an active case | FlagSurveyor |

## 5. Error Code Catalogue

A request path or method the API does not define is rejected with `ERR_NOT_FOUND` (HTTP 404); an unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500).

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_VESSEL_FROZEN | 409 |
| ERR_EVENT_OUT_OF_WINDOW | 422 |
| ERR_DISCHARGE_WITHOUT_UPTAKE | 422 |
| ERR_EXCHANGE_TOO_CLOSE | 422 |
| ERR_PLAN_REVISION_REGRESSION | 422 |
| ERR_MULTIPLE_APPROVED_PLANS | 409 |
| ERR_DUPLICATE_VOYAGE_NUMBER | 409 |
| ERR_BOOK_SEALED | 409 |
| ERR_ENTRY_KIND_MISMATCH | 422 |
| ERR_TANK_BALANCE_NEGATIVE | 422 |
| ERR_VOLUME_EXCEEDS_CAPACITY | 422 |
| ERR_SULFUR_OUT_OF_RANGE | 422 |
| ERR_OFFICER_REQUIRED | 422 |
| ERR_VALIDATION | 400 |
| ERR_INTERNAL | 500 |

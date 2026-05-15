# Epidemic Monitoring API — Product Requirements Document

## 1. Introduction

Public-health response during an active outbreak depends on a single platform that can simultaneously ingest cases from hospitals, drive contact tracing through field teams, manage isolation in centralized facilities or at home, run laboratory testing through a documented chain of custody, score regional risk based on confirmed-case density and contact-graph topology, allocate scarce protective equipment and test kits across districts under priority rules, and publish daily bulletins to the public. The Epidemic Monitoring API exists as the connective tissue between hospital information systems, laboratory information systems, transit and venue code platforms, sub-district CDC offices, expert review panels, and press channels. Every operational entity in the response — from a single contact event to a sub-district risk tier — flows through this API, and every published statistic is reconstructible from its persisted records.

This specification defines the resources, lifecycles, calculations, and access controls the platform must enforce. It is written for engineers implementing the server: the prose describes domain behaviour first and pins implementation contracts (response envelopes, status codes, precision rules) second. Where a rule applies across many endpoints — authentication, pagination, optimistic concurrency, audit logging — it is stated once in §2. Where a rule belongs to a specific workflow — case deduplication, isolation release eligibility, supply waterfall — it is stated in §3 as part of that workflow's narrative.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares that user's operational capacity. Eight roles are recognized: `HospitalReporter`, `LabTechnician`, `CDCDispatcher`, `CDCTracer`, `CDCSupervisor`, `RiskExpert`, `PressOfficer`, and `SupplyManager`. A request missing either header is rejected with `ERR_AUTH_REQUIRED`; a request whose declared role is not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN`.

Four of these roles are entity-backed: when `X-User-Role` is `HospitalReporter`, `LabTechnician`, `CDCDispatcher`, or `CDCTracer`, the value of `X-User-ID` is the `id` of the acting `ReportingInstitution`. Ownership checks on any resource that references a `ReportingInstitution` — for example, the `reporting_institution_id` on a `Case`, the `ordering_institution_id` on a `TestOrder`, the `requesting_institution_id` on a `SupplyRequest`, or the `assigned_cdc_id` on a `TracingTask` — compare the resource's foreign-key field to `X-User-ID`. The remaining four roles (`CDCSupervisor`, `RiskExpert`, `PressOfficer`, `SupplyManager`) are opaque operator identifiers not tied to any persisted entity. The server may record an opaque identifier — for example, as `expert_reviewer_id` on a `RiskTierDecision` written by `RiskExpert` review, or as `actor_id` on an `AuditLog` row — but it does not compare an opaque `X-User-ID` to any entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; the `offset` parameter defaults to 0 with a minimum of 0. Values outside those bounds are rejected with `ERR_INVALID_PAGINATION`. Unless otherwise noted, all list endpoints return resources sorted by `created_at` ascending. The `meta` block on list responses carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources carry four common fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits, set at creation and never mutated; `updated_at`, the same format, refreshed on every mutation; and `version`, an integer starting at 1 and incremented on every mutation. Two entities — `ContactEvent` and `DailyHealthReport`, together with the append-only ledger entities `RiskTierDecision`, `Dispatch`, and `AuditLog` — are exceptions: they carry only `id` and `created_at`; both `updated_at` and `version` are absent on those entities because their lifecycle treats each row as a write-once event.

### 2.5. Optimistic Concurrency Control

Any mutating endpoint that exposes the version field accepts an optional `version` integer in the request body. When supplied, the server compares it against the current persisted `version` of the targeted resource; a mismatch is rejected with `ERR_VERSION_CONFLICT`. When omitted, the OCC check is skipped and the mutation proceeds against whatever the current state happens to be. Every successful mutation increments `version` by one and refreshes `updated_at`, even when only a computed field or cascade changed.

### 2.6. Nested Resource Retrieval and Reference Resolution

URL paths that nest resources — for example, daily reports filed beneath an isolation, or a test-order result endpoint — are validated left to right. The first path identifier that does not resolve produces `ERR_NOT_FOUND` before any further check runs. Foreign keys carried in the request body — `person_id`, `reporting_institution_id`, `ordering_institution_id`, `requesting_institution_id`, `assigned_cdc_id`, `region_id`, `case_id`, `isolation_id`, `request_id`, `source_person_id`, `target_person_id`, `facility_id`, `sku`, and `entity_id` — are resolved separately; a missing body FK yields `ERR_REFERENCE_NOT_FOUND`.

### 2.7. Authority of the Reporting Institution

Four mutating endpoints — case filing, test-order creation, test-result ingestion, and contact-event ingestion — additionally require that the acting `ReportingInstitution` carry `status` equal to `ACTIVE`. A request originating from an institution in `SUSPENDED` or `ARCHIVED` status is rejected with `ERR_INSTITUTION_INACTIVE`.

### 2.8. Validation Priority

When more than one validation could fire on a single request, the server evaluates checks in a fixed priority order: header presence first (yielding `ERR_AUTH_REQUIRED`), then role authorization (`ERR_FORBIDDEN`), then path-resource existence (`ERR_NOT_FOUND`), then body-FK existence (`ERR_REFERENCE_NOT_FOUND`), then state-transition admissibility (`ERR_INVALID_STATE`), then institution-active checks (`ERR_INSTITUTION_INACTIVE`), then the isolation-violation terminal-state guard, then case-deduplication uniqueness (`ERR_DUPLICATE_CASE`), then bulletin-date uniqueness (`ERR_DUPLICATE_BULLETIN`), then test-result freshness (`ERR_TEST_RESULT_EXPIRED`), then isolation-date plausibility (`ERR_ISOLATION_DATE_INVALID`), then facility capacity (`ERR_FACILITY_AT_CAPACITY`), then release eligibility (`ERR_RELEASE_NOT_ELIGIBLE`), then the self-contact guard (`ERR_SELF_CONTACT`), then contact-time plausibility (`ERR_EVENT_TIME_INVALID`), then supply solvency (`ERR_SUPPLY_INSUFFICIENT`), then dispatch-quantity matching (`ERR_DISPATCH_QUANTITY_MISMATCH`), then consumption ceiling (`ERR_CONSUMPTION_EXCEEDS_DISPATCH`), then tier-staleness (`ERR_TIER_STALE`), then bulletin-channel validity (`ERR_INVALID_CHANNELS`), then optimistic-concurrency (`ERR_VERSION_CONFLICT`), and finally pagination bounds (`ERR_INVALID_PAGINATION`). Whichever check fires first is the one returned; later checks are not evaluated for that request.

### 2.9. Precision, Rounding, and Time Semantics

All monetary, density, and exposure calculations round half-up to two decimal places. Where a multi-step calculation pins intermediate rounding (for example, regional density is rounded before contact-chain weight is added, and the final sum is re-rounded), the per-calculation narrative in §3 makes that order explicit. Day-granular comparisons compute the elapsed-day count as the floor of total seconds since the start instant divided by 86400. Hour-granular comparisons (such as the SLA-overdue severity threshold) use a non-strict `<=` boundary. Supply allocations operate in integer units only — there is no fractional remainder, no proportional split.

The platform exposes three test-only capabilities for time-sensitive workflows. An admin-only clock-advance capability accepts a `seconds` body parameter and advances the simulated wall clock for any time-gated transition. A sweep capability runs all deferred system transitions — most importantly, test-order expiry into `VOID` when the validity window is exceeded with the result still `PENDING`, and the rolling refresh from `EXTENDED` back to `ACTIVE` on isolations whose `planned_end_date` is still in the future. An event-emit capability accepts a `source` and a `payload` and simulates an inbound HIS, LIS, transit-code, or venue-code event that fans into a `ContactEvent` or a `TestOrder` result.

### 2.10. Audit Trail

Every status transition on `Case`, `RiskTierDecision`, `Isolation`, and `TestOrder` appends a row to `AuditLog` carrying `entity_type`, `entity_id`, `from_state`, `to_state`, `actor_role`, `actor_id`, and `at`. Audit rows are append-only (no `version`, no `updated_at`); they are queryable by `CDCSupervisor` for retrospective investigation, filtered by `entity_type`, `entity_id`, `since`, and `until`.

### 2.11. Hierarchical State Consistency

A single mutating call may cascade across two or more entities. When this happens, each touched entity has its own `updated_at` refreshed and its own `version` incremented; an idle entity in the same call is not version-bumped. Cascade examples are detailed in the §3 workflow narratives. When a caller pins a `version` that no longer matches the persisted row at the moment the mutation commits, the rejection is `ERR_VERSION_CONFLICT`.

## 3. Business Logic & Workflows

### 3.1. Reporting Institutions, Regions, Persons, and Facilities

Before any reporting can begin, the platform is seeded with `ReportingInstitution` rows by `CDCSupervisor` operators. Each carries an `institution_code` (a unique alphanumeric short code, between 4 and 12 characters long), an `institution_type` drawn from `HOSPITAL`, `LAB`, `CDC`, `VENUE`, and `TRANSIT`, and a `district_code` identifying the sub-district where the institution sits. New institutions default to operational `status` `ACTIVE`; a supervisor can later move an institution into `SUSPENDED` (temporarily off-platform) or `ARCHIVED` (permanently retired). Only `ACTIVE` institutions can file cases, order or result tests, or feed contact events.

Sub-districts themselves are modelled as `Region` rows, each keyed by a unique `district_code`. Each region records its resident `population` (which must be strictly greater than zero, since population is the denominator of the density score), a `current_risk_tier` and a `provisional_risk_tier` (both drawn from `LOW`, `MEDIUM`, `HIGH` and defaulting to `LOW`), and `last_tier_decision_id` pointing to the most recent `RiskTierDecision` row that wrote `current_risk_tier`.

Individuals being tracked are stored as `Person` rows. Each carries a `person_hash` — a unique 16-character lowercase hex deduplication hash derived from the person's national-id last four digits, date of birth, and name initials — a structured `demographics` object containing age band, gender, and occupation category, the `district_code` of residence, an `isolation_status` (one of `NONE`, `ACTIVE`, `RELEASED`, `VIOLATED_TERMINATED`, defaulting to `NONE`), and `latest_case_id` pointing at the most recent `Case` for this person (nullable).

Centralized isolation requires physical infrastructure, registered as `IsolationFacility` rows. Each has a unique `facility_code`, a `district_code`, a positive `capacity` count of beds, a computed `occupied` count starting at zero, and an operational `status` of `OPEN`, `FULL`, or `CLOSED`, defaulting to `OPEN`. As centralized isolations admit and release residents, the platform increments and decrements `occupied`; when `occupied` reaches `capacity`, the facility transitions to `FULL` and refuses further admissions, and when a release later drops `occupied` below `capacity` the facility transitions back to `OPEN`.

### 3.2. Case Reporting and Deduplication

A case is filed by a `HospitalReporter` or `CDCDispatcher` with a payload carrying `person_id`, `reporting_institution_id`, `case_type` (one of `SUSPECTED`, `CONFIRMED`, `ASYMPTOMATIC`), `onset_date` (a UTC date taken at midnight), `symptoms` (a list of symptom enum codes), and optionally `exposure_history` (free-text snippets used by tracers downstream). On creation the server stamps `reported_at` with the current wall clock and computes `report_deadline_at` as the `onset_date` plus the report-window constant — 24 hours from onset. The boolean `is_late_report` is then set to true exactly when `reported_at` is strictly later than `report_deadline_at`; equality counts as on-time and the flag is persisted once at creation and not recomputed later.

The case `status` begins at `REPORTED`. Two cases for the same `(person_id, case_type)` cannot both be in non-terminal status. When a hospital files a duplicate report for a person who already has a non-terminal case (`REPORTED`, `UNDER_TRACING`, or `CONFIRMED`) of the same type, the new row is auto-marked `DEDUPLICATED` with its `superseded_by_case_id` pointing at the surviving case. Two reporting institutions racing on the same `(person_id, case_type)` are serialized by ascending `reported_at`, with ties broken by `Case.id` lexicographic ascending; the winner advances normally and the loser receives `ERR_DUPLICATE_CASE`.

Creating a case also kicks off provisional risk recompute for the case's resident `Region` — see §3.6.

### 3.3. The Contact Graph and Tracing Workflow

Contact relationships are stored as `ContactEvent` edges between two `Person` nodes. Each edge carries `source_person_id` (the index/origin person), `target_person_id` (the contacted person), `event_type` (`TRANSIT`, `VENUE`, `COWORKER`, or `HOUSEHOLD`), `event_time`, `duration_minutes` (which must be non-negative), `distance_meters` (also non-negative), and `ingested_from` indicating the upstream feed: `HIS`, `LIS`, `TRANSIT_CODE`, `VENUE_CODE`, or `MANUAL`. Ingestion is performed by a `CDCTracer` or a `HospitalReporter`. Two referential constraints fire at ingest time: `source_person_id` must differ from `target_person_id`, rejected with `ERR_SELF_CONTACT`, and `event_time` cannot be in the future, rejected with `ERR_EVENT_TIME_INVALID`.

On ingest the server computes the per-edge weight that determines the `tier` of the contacted person. The base weight is read from a per-channel table: a `HOUSEHOLD` contact weighs 10 points, a `COWORKER` contact 6, a `VENUE` contact 4, and a `TRANSIT` contact 2. Proximity multiplies the weight by one if `distance_meters` is at most 1.5, and by one-half otherwise. Duration multiplies by the smaller of two quantities — the number of minutes divided by 60, and a cap of 4. The raw edge weight is the product of base weight, proximity factor, and duration factor. The edge's `tier` is set to `CLOSE` when this raw weight is at least 5.0, and `SUB_CLOSE` otherwise. The same ingest path also triggers a recompute of the contacted person's overall exposure score (§3.7).

A `CDCDispatcher` opens a `TracingTask` for a non-deduplicated case by submitting a payload with `case_id` and `assigned_cdc_id`; this is permitted only when the source case is in `REPORTED` status with `case_type` in `CONFIRMED` or `ASYMPTOMATIC` (suspected cases trace only after a positive test moves them along the case lifecycle). Creating the tracing task stamps `dispatched_at`, computes `due_at` as the dispatched-at moment plus the SLA window, sets `status` to `DISPATCHED`, transitions the underlying case from `REPORTED` to `UNDER_TRACING`, and appends an audit row.

A field tracer accepts the task (`DISPATCHED → IN_PROGRESS`), which also sets the case to `UNDER_TRACING` if the case is still in `REPORTED`. When the contact list is finalized — `discovered_contact_count` may be zero — the tracer marks the task complete (`IN_PROGRESS → COMPLETED`), stamping `completed_at`, and for every linked `ContactEvent` whose `tier` is `CLOSE` the system auto-creates an `Isolation` in `ACTIVE` for the contacted person (mode defaulting to `HOME` unless the tracer overrides on the call). Completion also triggers a regional risk recompute (§3.6). A `CDCSupervisor` may either close the completed task (`COMPLETED → CLOSED`) or send it back for revision (`COMPLETED → NEEDS_REVISION`); rejection cancels any auto-created isolation that is still `ACTIVE` and has not yet received a `DailyHealthReport`. A tracer can re-accept a needs-revision task (`NEEDS_REVISION → IN_PROGRESS`) and re-walk the workflow.

Each tracing task also exposes a computed SLA severity on read. If the task is in a non-terminal status (`DISPATCHED`, `IN_PROGRESS`, or `NEEDS_REVISION`) and the current time is strictly later than `due_at`, the task is overdue: severity is `SOFT` when the elapsed time past `due_at` is at most 12 hours (the `<=` boundary is non-strict) and `HARD` otherwise. Tasks not overdue carry severity `NONE`. This is not a persisted field and is recomputed on every read of the single-task and list endpoints; the list endpoint also accepts an `overdue` filter.

### 3.4. Isolation Lifecycle and Daily Reporting

A `CDCTracer` opens an `Isolation` for a person by submitting `person_id`, `mode` (`CENTRALIZED`, `HOME`, or `MEDICAL_OBSERVATION`), an optional `facility_id` for the centralized mode (null otherwise), and a `start_date` at midnight UTC. The `start_date` must not lie in the future, and if the person has an indexing case it cannot be earlier than that case's `onset_date`; either violation is rejected with `ERR_ISOLATION_DATE_INVALID`. The server computes `planned_end_date` as `start_date` plus the minimum-days constant for the mode: 14 days for centralized, 10 days for home, and 7 days for medical-observation. The isolation enters `ACTIVE` with `extension_count`, `daily_reports_received`, and `violations_count` all initialized to zero, and `actual_end_date` left unset until termination.

Centralized admission additionally checks the facility: the facility must have `status` equal to `OPEN` and `occupied` strictly less than `capacity`. Failing that, the request is rejected with `ERR_FACILITY_AT_CAPACITY`. On a successful centralized admission, `occupied` is incremented, the person's `isolation_status` is set to `ACTIVE`, and if the increment causes `occupied` to equal `capacity` the facility transitions to `FULL`. Two simultaneous centralized admissions to the same facility holding only one remaining bed serialize on the facility's `occupied` field — the first writer wins and the second receives `ERR_FACILITY_AT_CAPACITY`.

The isolated person — or staff acting on their behalf — submits a `DailyHealthReport` once per day with `report_date` (midnight UTC), `temperature_c`, and a list of `symptoms`. The server sets `is_abnormal` true exactly when `temperature_c` is at least the fever threshold or the `symptoms` list is non-empty, and increments `daily_reports_received` on the parent isolation.

Release eligibility is evaluated on demand by a tracer calling the check-release capability with an optional `mode_hint`. The decision is taken in four checks evaluated top-down — first match wins. First, the elapsed whole-day count since `start_date` must be at least the minimum-days constant for the isolation's `mode`; if not, the outcome is `NOT_ELIGIBLE`. Second, if any `DailyHealthReport` whose `report_date` falls in the trailing 3-day abnormal window has `is_abnormal` true, the outcome is `EXTEND`. Third, the count of `TestOrder` rows for this person with `status` `RESULTED`, `result` `NEGATIVE`, `test_type` `PCR`, and `collected_at` strictly later than `start_date` must be at least 2; if fewer, the outcome is `EXTEND`. Fourth, those negative tests must fall on at least two distinct UTC collection dates; if not, the outcome is `EXTEND`. If all four checks pass, the outcome is `RELEASE`. An `EXTEND` outcome moves the isolation from `ACTIVE` to `EXTENDED`, increments `extension_count` by 1, and shifts `planned_end_date` to the current moment plus 7 days; a `RELEASE` outcome moves the isolation to its terminal status, stamps `actual_end_date`, sets the person's `isolation_status` to `RELEASED`, and for centralized isolations decrements `occupied` (flipping `FULL` back to `OPEN` when `occupied` drops below `capacity`). If the caller requests a release-only check and the decision is anything other than `RELEASE`, the call is rejected with `ERR_RELEASE_NOT_ELIGIBLE`. Two tracers racing on release for the same isolation serialize on the isolation's `status` field — the first writer wins and the loser receives `ERR_INVALID_STATE`. An extended isolation later rolls forward through the sweep capability: when the simulated clock advances and the isolation's `status` is `EXTENDED` while `now()` is still earlier than `planned_end_date`, the sweep transitions it back to `ACTIVE` for further evaluation.

Geofence and access-control breaches are recorded by the tracer through the violation capability with a `reason` body field. A violation can only be recorded against a non-terminal isolation (`ACTIVE` or `EXTENDED`); recording one against a terminal isolation is rejected with `ERR_INVALID_STATE`. A successful violation increments `violations_count`, stamps `actual_end_date`, sets the person's `isolation_status` to `VIOLATED_TERMINATED`, transitions the isolation itself to `VIOLATED_TERMINATED`, and for centralized isolations decrements `occupied`.

### 3.5. Test Ordering, Chain of Custody, and Lab Results

A test is ordered by a `HospitalReporter` or `CDCTracer` against a `Person` with `test_type` `PCR`, `ANTIGEN`, or `ANTIBODY`, and an `ordering_institution_id`. The order enters `ORDERED` with an empty `chain_of_custody`. Sample collection — recorded by the ordering hospital — appends a chain-of-custody entry (each entry carries actor role, actor id, action, and timestamp), stamps `collected_at`, and moves the order to `COLLECTED`. The laboratory ingests the outcome through the result endpoint with a body carrying `result`; the test must still be valid at this moment — the elapsed time between `collected_at` and the result ingest must not exceed the per-modality validity window, otherwise `ERR_TEST_RESULT_EXPIRED` fires. A successful ingest appends another chain-of-custody entry, stamps `result_recorded_at`, and moves the order to `RESULTED`.

If the result is `POSITIVE` and the person has an open case in `REPORTED` or `UNDER_TRACING` whose `test_type` is `PCR`, the case advances along its lifecycle (see §3.6). If the result is `POSITIVE` and the person has no open case, a reminder side-effect is emitted but no case is auto-created. The lab can flag a resulted order for follow-up (`RESULTED → FOLLOW_UP`) only when `result` is `POSITIVE` or `INVALID`. A tracer can close a follow-up order, and either a tracer can close a resulted order whose `result` is `NEGATIVE`. A test that lingers in `COLLECTED` with `result` still `PENDING` past its validity window is reaped by the sweep capability: `status` becomes `VOID`, `result` becomes `INVALID`, and a system entry is appended to `chain_of_custody`.

### 3.6. Regional Risk Tier Computation and Approval

A region's provisional risk is recomputed whenever a case is filed, whenever a case advances to `CONFIRMED`, whenever a tracing task is completed (which adds close-tier contact events), and on demand via the recompute capability for a region. The computation runs over a trailing 14-day window. Within that window, the platform counts confirmed-or-tracing-active cases for residents of the region (case `status` in `CONFIRMED` or `UNDER_TRACING`), counts asymptomatic-typed cases regardless of their status as long as they are not `DEDUPLICATED`, and counts the number of distinct connected components in the contact-event subgraph restricted to those residents. Cases marked `DEDUPLICATED` and contact events whose `event_time` is in the future are excluded.

The density score is then the count of confirmed cases multiplied by a weight of 3, plus the count of asymptomatic cases multiplied by a weight of 1, divided by the region's `population`, multiplied by 100 000 — yielding cases per 100 000 residents. That density figure is rounded half-up to two decimal places. To it the platform adds the count of distinct contact-chain connected components multiplied by a weight of 5; the resulting total is rounded again half-up to two decimal places. Tier mapping is closed-interval and evaluated top-down: a final score of at least 50.00 yields `HIGH`; otherwise a score of at least 10.00 yields `MEDIUM`; anything else is `LOW`. The result is written to the region's `provisional_risk_tier`. This automatic path does not write `current_risk_tier`.

A `CDCSupervisor` creates a `RiskTierDecision` referencing the `region_id`; the server snapshots the latest computed tier into `provisional_tier` and stores the region's pre-decision tier in `previous_tier`. Each decision carries a `mode` of either `AUTO` (when the formula-derived `provisional_tier` is accepted as-is and no expert override is needed) or `EXPERT_OVERRIDE` (when a `RiskExpert` later supplies a `final_tier` that diverges from the formula). If the `provisional_tier` snapshot disagrees with whatever the score formula would produce at the moment the decision is created, the call is rejected with `ERR_TIER_STALE`. The decision enters `PROVISIONAL`; if the supervisor submits it for review (`PROVISIONAL → UNDER_REVIEW`), the platform requires that `provisional_tier` actually differs from the region's `current_risk_tier` — there is no point reviewing a no-op. Under review, a `RiskExpert` either approves with a body carrying `final_tier` and `expert_reviewer_id` (`UNDER_REVIEW → APPROVED`), or rejects with `expert_reviewer_id` (`UNDER_REVIEW → REJECTED`). The `final_tier` set on approval may diverge from `provisional_tier` — that divergence is the entire point of `EXPERT_OVERRIDE`.

Two simultaneous review actions on the same decision (an expert approval racing a supervisor rejection, for instance) serialize on the decision's `status` — exactly one terminal action wins and the loser receives `ERR_INVALID_STATE`.

A `PressOfficer` then publishes the approved decision (`APPROVED → PUBLISHED`), permitted as long as the `final_tier` differs from the region's `current_risk_tier` or this is the first publication for that region. Publishing stamps `published_at`, writes `Region.current_risk_tier` to `final_tier`, sets `Region.last_tier_decision_id` to this decision's `id`, recomputes `priority_score` on every `PENDING` `SupplyRequest` whose requesting institution sits in this region (the cascade described in §3.7), and if `final_tier` is `HIGH`, flags any `DRAFT` `Bulletin` for the same `bulletin_date` to include this region in its high-tier bucket. The decision's `previous_tier` records the tier prior to this transition.

### 3.7. Supply Inventory, Priority, and the Allocation Waterfall

A `SupplyManager` seeds reserve inventory with `SupplyItem` rows. Each carries a unique `sku`, a `category` from `PPE`, `TEST_KIT`, `MEDICATION`, or `VACCINE`, a `reserve_quantity` of on-hand units, and an `allocated_quantity` reserved but not yet dispatched. Both quantities are integers.

Institutions submit demand via `SupplyRequest` rows: `sku`, `requesting_institution_id`, and `requested_quantity` (strictly positive). On creation the server computes a `priority_score` as the sum of two weights — the tier weight read from the requesting institution's region (`HIGH` contributes 100, `MEDIUM` contributes 30, `LOW` contributes 0) and the category weight of the requested item (`PPE` contributes 5, `TEST_KIT` contributes 3, `MEDICATION` contributes 8, `VACCINE` contributes 6). The request enters `PENDING` with `allocated_quantity`, `dispatched_quantity`, and `consumed_quantity` all zero.

Allocation is performed by the supply manager either against a single request or in batch by `sku`. The batch path is a strict waterfall: among all `PENDING` requests for the `sku`, sort by `priority_score` descending, then `created_at` ascending, then `id` ascending, and walk the sorted list. At each request allocate the smaller of the request's `requested_quantity` and the remaining available — defined as the item's `reserve_quantity` minus its `allocated_quantity`. The last request in line that can only be partially satisfied receives the entire remaining available (it is not split across multiple requests); there is no proportional split, no fractional unit, and no redistribution of any remainder. If at any point the chosen allocation cannot satisfy the request from the remaining reserve, the platform records the partial allocation and continues; any request whose allocated quantity is zero stays in `PENDING`. A single-request allocate runs the same logic restricted to that one request. Allocations move the request from `PENDING` to `ALLOCATED`, write `allocated_quantity` to the value computed above, and increment the item's `allocated_quantity` by the same amount.

If two allocations race over the same item and would jointly drive `allocated_quantity` past `reserve_quantity`, serialization on the item's `allocated_quantity` field gives the first writer the allocation and the second receives `ERR_SUPPLY_INSUFFICIENT`. The same error fires when a single allocate would over-commit on its own.

Dispatch is initiated by the supply manager with a `quantity` body field. The quantity must equal the request's `allocated_quantity`; mismatch is rejected with `ERR_DISPATCH_QUANTITY_MISMATCH`. A successful dispatch creates a `Dispatch` row referencing the `request_id` with `status` `IN_TRANSIT`, decrements both `reserve_quantity` and `allocated_quantity` on the item by the dispatched amount, sets the request's `dispatched_quantity` to the allocated value, and moves the request from `ALLOCATED` to `DISPATCHED`. A subsequent deliver call (by the supply manager or the receiving hospital) stamps `delivered_at`, moves the dispatch to `DELIVERED`, and rolls the parent request from `DISPATCHED` to `DELIVERED`. The receiving institution then reports consumption with `consumed_quantity` in the body; this must not exceed `dispatched_quantity`, with `ERR_CONSUMPTION_EXCEEDS_DISPATCH` thrown otherwise, and the successful call rolls the request to `CONSUMED`.

A request can also be cancelled by the supply manager. Cancelling a `PENDING` request simply moves it to `CANCELLED`; cancelling an `ALLOCATED` request also decrements the item's `allocated_quantity` by the previously-allocated amount, returning that capacity to the next allocation cycle.

Risk publication cascades into allocation: when a region's `current_risk_tier` is updated by a published decision, every `PENDING` `SupplyRequest` from that region has its `priority_score` recomputed against the new tier weight. The next batch allocate therefore re-sorts those requests against their freshly weighted scores.

### 3.8. Person-level Exposure Score and Graph Read

The platform exposes a per-person exposure score derived from the same `ContactEvent` data that classifies edge tiers. For a target person, the server gathers every `ContactEvent` where `target_person_id` matches and `event_time` falls in the trailing 14-day exposure window, then replays them in `event_time` ascending order (ties broken by event `id` ascending). For each event, the raw weight is computed as in §3.3 — base weight from `event_type`, proximity factor from `distance_meters`, duration factor as the smaller of `duration_minutes / 60` and a cap of 4. The raw weight is then attenuated by a linear decay factor: the larger of zero and one minus the number of whole days between `event_time` and the current moment divided by 14. The raw weight times the decay factor is added to a running accumulator. After all events are folded in, the accumulator is rounded half-up to two decimal places and returned as the person's `contact_exposure_score`. Contact events sourced from a person whose `Case.status` is `DEDUPLICATED` are excluded from the input set. The default-read path uses chronological replay.

The same endpoint accepts a `projection` query parameter. When the projection variant is requested, decay aging is bypassed for events whose `event_time` falls within the trailing single day — those events use a days-since-event count of zero, producing a typically higher numeric score for the same input set. The two variants therefore return different scores for identical inputs.

Persons also expose a contact-graph slice with an optional `depth` query parameter, returning the node and edge subgraph reachable from the target person within the exposure window.

### 3.9. Bulletins and Public Disclosure

A `PressOfficer` drafts a daily `Bulletin` by submitting `bulletin_date` (midnight UTC) and a non-empty subset of `channels` drawn from `WEBSITE`, `APP`, and `PRESS`; an empty list or a value outside that set is rejected with `ERR_INVALID_CHANNELS`. Each `bulletin_date` is unique — a second draft for the same date is rejected with `ERR_DUPLICATE_BULLETIN`, and two press officers racing on the same date serialize on the date-uniqueness check with the loser receiving the same error. On draft creation the server snapshots `total_new_cases` (the count of `Case` rows whose `reported_at` falls on `bulletin_date` in UTC) and `tier_summary` (an object containing the count of sub-districts in each of `HIGH`, `MEDIUM`, and `LOW`); `status` enters `DRAFT` and `rumor_corrections` initializes empty.

Publishing the bulletin (`DRAFT → PUBLISHED`) re-snapshots `total_new_cases` and `tier_summary` at publish time, and requires that `channels` remains non-empty. A published bulletin may be retracted (`PUBLISHED → RETRACTED`) with an optional `reason` body field; if a reason is supplied, a rumor-correction stub is appended to `rumor_corrections`. A retracted bulletin may be republished (`RETRACTED → PUBLISHED`), again requiring non-empty `channels`. After the configured archive delay has elapsed since `bulletin_date`, the bulletin may be archived (`PUBLISHED → ARCHIVED`); archiving before the delay is rejected as an invalid state transition.

### 3.10. Case Confirmation and Recovery

A case that started as `SUSPECTED` or `ASYMPTOMATIC` and is currently `UNDER_TRACING` advances to `CONFIRMED` when a positive PCR result is ingested for its person (`status` `UNDER_TRACING → CONFIRMED`). On that transition the case's `case_type` is set to `CONFIRMED` if it was previously `SUSPECTED`, the region's provisional risk tier is recomputed, and an audit row is appended.

A `CDCDispatcher` may mark a case `RECOVERED` (`CONFIRMED → RECOVERED`) only when three conditions hold: the case is currently `CONFIRMED`; the person's linked isolation is in `RELEASED` (a violated or active isolation blocks recovery); and at least two prior `TestOrder` rows for the same person carry `result` `NEGATIVE`, `test_type` `PCR`, and chronologically distinct collection dates. Recovery is terminal and appends an audit row.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`. Endpoints that modify an existing resource return HTTP 200 with the updated resource. Read endpoints return HTTP 200. Error responses use the status codes pinned in §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /epi/institutions | Register a reporting institution. | CDCSupervisor |
| GET | /epi/institutions/{id} | Read an institution. | CDCSupervisor, CDCDispatcher, CDCTracer, HospitalReporter, LabTechnician, SupplyManager, PressOfficer, RiskExpert |
| POST | /epi/regions | Create a sub-district region. | CDCSupervisor |
| GET | /epi/regions/{id} | Read a region. | CDCSupervisor, CDCDispatcher, CDCTracer, RiskExpert, PressOfficer |
| POST | /epi/regions/{id}/recompute-risk | Manually trigger regional risk recompute. | CDCSupervisor |
| POST | /epi/persons | Register a person. | CDCSupervisor, HospitalReporter |
| GET | /epi/persons/{id} | Read a person. | CDCSupervisor, CDCDispatcher, CDCTracer, HospitalReporter, LabTechnician |
| GET | /epi/persons/{id}/exposure-score | Read computed exposure score (chronological or projection variant). | CDCSupervisor, CDCTracer |
| GET | /epi/persons/{id}/contact-graph | Read contact-graph slice for a person. | CDCSupervisor, CDCTracer |
| POST | /epi/facilities | Register an isolation facility. | CDCSupervisor |
| GET | /epi/facilities/{id} | Read a facility. | CDCSupervisor, CDCTracer |
| POST | /epi/cases | File a case (auto-deduplicates on collision). | HospitalReporter, CDCDispatcher |
| GET | /epi/cases/{id} | Read a case. | CDCSupervisor, CDCDispatcher, CDCTracer, HospitalReporter |
| GET | /epi/cases | List cases. | CDCSupervisor, CDCDispatcher, CDCTracer, HospitalReporter |
| POST | /epi/cases/{id}/recover | Mark a confirmed case as recovered. | CDCDispatcher |
| POST | /epi/contact-events | Ingest a contact edge into the graph. | CDCTracer, HospitalReporter |
| POST | /epi/tracing-tasks | Dispatch a tracing task for a case. | CDCDispatcher |
| GET | /epi/tracing-tasks/{id} | Read a tracing task. | CDCSupervisor, CDCTracer, CDCDispatcher |
| GET | /epi/tracing-tasks | List tracing tasks. | CDCSupervisor, CDCTracer, CDCDispatcher |
| POST | /epi/tracing-tasks/{id}/accept | Accept a dispatched or needs-revision task. | CDCTracer |
| POST | /epi/tracing-tasks/{id}/complete | Confirm tracing complete. | CDCTracer |
| POST | /epi/tracing-tasks/{id}/reject | Reject a completed task. | CDCSupervisor |
| POST | /epi/tracing-tasks/{id}/close | Close a completed task. | CDCSupervisor |
| POST | /epi/isolations | Create an isolation. | CDCTracer |
| GET | /epi/isolations/{id} | Read an isolation. | CDCSupervisor, CDCTracer |
| POST | /epi/isolations/{id}/daily-report | Submit a daily health report. | CDCTracer, HospitalReporter |
| POST | /epi/isolations/{id}/violation | Record a violation. | CDCTracer |
| POST | /epi/isolations/{id}/check-release | Run release eligibility (extend or release). | CDCTracer |
| POST | /epi/test-orders | Order a test. | HospitalReporter, CDCTracer |
| POST | /epi/test-orders/{id}/collect | Record sample collection. | HospitalReporter |
| POST | /epi/test-orders/{id}/result | Lab ingests a result. | LabTechnician |
| POST | /epi/test-orders/{id}/flag-followup | Flag for abnormal-result follow-up. | LabTechnician |
| POST | /epi/test-orders/{id}/close | Close a test order. | CDCTracer |
| GET | /epi/test-orders/{id} | Read a test order. | CDCSupervisor, CDCTracer, HospitalReporter, LabTechnician |
| GET | /epi/test-orders | List test orders. | CDCSupervisor, CDCTracer, HospitalReporter, LabTechnician |
| POST | /epi/risk-decisions | Create a provisional risk-tier decision. | CDCSupervisor |
| GET | /epi/risk-decisions/{id} | Read a risk-tier decision. | CDCSupervisor, RiskExpert, PressOfficer |
| POST | /epi/risk-decisions/{id}/submit-review | Submit for expert review. | CDCSupervisor |
| POST | /epi/risk-decisions/{id}/approve | Expert approves with a final tier. | RiskExpert |
| POST | /epi/risk-decisions/{id}/reject | Expert rejects. | RiskExpert |
| POST | /epi/risk-decisions/{id}/publish | Publish approved decision. | PressOfficer |
| POST | /epi/supply-items | Register a supply item. | SupplyManager |
| GET | /epi/supply-items/{id} | Read a supply item. | SupplyManager, CDCSupervisor |
| POST | /epi/supply-requests | Submit a supply demand. | HospitalReporter, CDCTracer, CDCSupervisor |
| GET | /epi/supply-requests/{id} | Read a supply request. | SupplyManager, CDCSupervisor, HospitalReporter, CDCTracer |
| POST | /epi/supply-requests/{id}/allocate | Allocate a single supply request. | SupplyManager |
| POST | /epi/supply/allocate-batch | Allocate all pending requests for an sku via waterfall. | SupplyManager |
| POST | /epi/supply-requests/{id}/dispatch | Dispatch the allocated quantity. | SupplyManager |
| POST | /epi/dispatches/{id}/deliver | Mark dispatch delivered. | SupplyManager, HospitalReporter |
| POST | /epi/supply-requests/{id}/consume | Report consumption. | HospitalReporter, CDCTracer |
| POST | /epi/supply-requests/{id}/cancel | Cancel a supply request. | SupplyManager |
| POST | /epi/bulletins | Create a draft bulletin. | PressOfficer |
| GET | /epi/bulletins/{id} | Read a bulletin. | CDCSupervisor, PressOfficer |
| GET | /epi/bulletins | List bulletins. | CDCSupervisor, PressOfficer |
| POST | /epi/bulletins/{id}/publish | Publish a draft or retracted bulletin. | PressOfficer |
| POST | /epi/bulletins/{id}/retract | Retract a published bulletin. | PressOfficer |
| POST | /epi/bulletins/{id}/archive | Archive a published bulletin after the archive delay. | PressOfficer |
| GET | /epi/audit-logs | Query audit logs. | CDCSupervisor |
| POST | /_clock/advance | Advance the simulated wall clock. | CDCSupervisor |
| POST | /_sweep/run | Run system sweeps (test expiry, isolation rollover). | CDCSupervisor |
| POST | /_events/emit | Simulate an inter-agency event. | CDCSupervisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_AUTH_REQUIRED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_DUPLICATE_CASE | 409 |
| ERR_DUPLICATE_BULLETIN | 409 |
| ERR_INSTITUTION_INACTIVE | 403 |
| ERR_TEST_RESULT_EXPIRED | 422 |
| ERR_ISOLATION_DATE_INVALID | 422 |
| ERR_FACILITY_AT_CAPACITY | 409 |
| ERR_RELEASE_NOT_ELIGIBLE | 422 |
| ERR_SELF_CONTACT | 422 |
| ERR_EVENT_TIME_INVALID | 422 |
| ERR_SUPPLY_INSUFFICIENT | 409 |
| ERR_DISPATCH_QUANTITY_MISMATCH | 422 |
| ERR_CONSUMPTION_EXCEEDS_DISPATCH | 422 |
| ERR_TIER_STALE | 422 |
| ERR_INVALID_CHANNELS | 422 |
| ERR_INVALID_PAGINATION | 400 |

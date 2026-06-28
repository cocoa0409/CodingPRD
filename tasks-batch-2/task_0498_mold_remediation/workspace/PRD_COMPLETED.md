# Mold Remediation API — Product Requirements Document

## 1. Introduction

Environmental remediation contractors operate at the intersection of public-health regulation, insurance economics, and tightly choreographed field work. A single asbestos, lead, or mold project moves through a long chain of irreversible decisions — an area is assessed and sampled, a negative-pressure containment is stood up, certified crews abate the hazard, waste is manifested to a licensed hauler, an independent hygienist clears the work, and only then is the insurer billed. Each of those steps is gated by a regulator, a safety threshold, or a financial cap, and getting the ordering wrong is not merely inconvenient: it exposes workers, voids permits, and produces a clearance sign-off that will not survive audit.

This document specifies the Mold & Environmental Remediation API, a backend that models the full lifecycle of a remediation **Project** and the regulated artifacts hanging off it — assessments, samples, containment zones, pressure logs, abatement orders, worker assignments, disposal manifests, clearance tests, permits, and insurance claims. The system is built around two organizing ideas. First, a project carries a derived **posture** that summarizes where its field work stands, recomputed from its children every time one of them transitions; almost every consequential operation is gated by that posture. Second, the system is a tamper-evident sign-off chain enforcing **segregation of duties**: the hygienist who signs off a clearance can be neither the worker who sampled it nor the lead who performed the abatement. Throughout, calculations come in deliberately divergent pairs — a forward-looking insurance estimate against a finalized settlement, a per-tier disposal fee that must be floored tier-by-tier — so that an implementation that conflates them will diverge in ways that matter.

The audience for this document is the engineering team building the service. It states the domain rules first and the HTTP surface second; the endpoint and error tables in Sections 4 and 5 are summaries, and the behavior behind each endpoint must be reconstructed from the business narrative in Sections 2 and 3.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resource collections are mounted under the `/api` prefix.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_AUTH_HEADER`. If `X-User-Role` carries a value that is not one of the recognized roles, the request is rejected with `ERR_INVALID_ROLE`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly five roles: `ProjectManager`, `AbatementSupervisor`, `LabTech`, `Hygienist`, and `ComplianceOfficer`. A `ProjectManager` owns the project lifecycle — creating and abandoning projects, activating and dismantling containment zones, cancelling orders, voiding samples and manifests, accepting manifests, and opening and submitting insurance claims. An `AbatementSupervisor` runs the abatement floor — creating orders, assigning workers, logging pressure, drafting and submitting disposal manifests, and starting and completing orders. A `LabTech` handles the laboratory and sampling work — collecting samples, uploading results, and creating and analyzing clearance tests. A `Hygienist` is the independent certified industrial hygienist who performs clearance sign-off and final project sign-off and nothing else. A `ComplianceOfficer` handles regulatory and fiscal duties — the full permit lifecycle, insurance settlement and denial, worker registration, and the logical clock. All five roles may read (perform `GET` operations) across every resource collection.

For each of these five roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. None of the roles is entity-backed: the server may accept and log the identifier, but it never compares `X-User-ID` to any entity's `id`, and ownership of a resource is never determined by matching the header against a stored foreign key. Authorization is purely role-based; identity-based ownership checks do not exist in this system. (The independence rule that governs clearance sign-off — described later — is enforced by comparing worker `id` values supplied in request bodies, not by inspecting `X-User-ID`.)

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of records returned; it defaults to 10, may not be less than 1, and may not exceed 100. The `offset` parameter is the number of records to skip and defaults to 0. A `limit` outside the 1–100 range, a negative `offset`, or a non-integer value supplied for either parameter is rejected with `ERR_INVALID_REQUEST`. List endpoints return their records sorted by creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

Several list endpoints also accept domain filters that narrow the result set by a foreign-key or enum value — these are described with their respective workflows in Section 3 and summarized in Section 4 — but the pagination contract above applies uniformly.

### 2.4. Common Resource Properties and the Logical Clock

Most resources are mutable, audit-tracked entities. Projects, workers, assessments, samples, containment zones, abatement orders, disposal manifests, clearance tests, permits, insurance claims, and worker assignments each carry four system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp, also with three fractional digits, refreshed on every mutation. The `version` field is an integer that starts at 1 (or its initial value on creation) and increments by one on every mutation of the resource, supporting optimistic concurrency control as described in Section 2.6.

One resource is an exception. A **PressureLog** is an append-only event record: it carries only an `id` (a server-minted UUID) and a `created_at` timestamp. A PressureLog has no `updated_at` and no `version`, because it is never modified after creation — it is a single immutable reading. The error catalogue defines no PressureLog-specific not-found code; a request naming a pressure log that does not exist is rejected with `ERR_ZONE_NOT_FOUND`.

The system runs on a **logical clock** rather than wall-clock time. At startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call it stays at exactly that default and never falls back to the host's real time. An administrative test-driving capability lets a `ComplianceOfficer` advance the clock by supplying a `to_iso8601` instant; the response reports the new clock as `current_utc`. Every temporal rule in this document — certification validity, fit-test windows, future-timestamp rejection, NESHAP lead time — is evaluated against this logical clock, never against real time. Conversely, the system-managed audit timestamps (`created_at`, `updated_at`) and the response envelope's `api_request_timestamp` are stamped from the host's real wall-clock time, not from the logical clock.

### 2.5. Project Posture and Derived-Field Reconciliation

Every Project carries a computed **posture** that is distinct from its lifecycle `status`. The `status` field tracks whether the project is open or closed (`OPEN`, then either `SIGNED_OFF` or `ABANDONED`), while `posture` summarizes where the field work stands and is one of `ASSESSMENT`, `CONTAINED`, `ABATING`, `CLEARANCE_PENDING`, `VERIFIED`, or `FROZEN`. A project's posture is recomputed from its children every time one of them transitions in a way flagged below, and it is evaluated by a fixed precedence in which the **first matching rule wins**:

1. The posture is `FROZEN` if any of the project's containment zones is in `BREACHED` status. `FROZEN` outranks every other posture — a breach freezes the project even while abatement is otherwise running.
2. Otherwise the posture is `VERIFIED` if there is at least one abatement order, every abatement order is either `COMPLETED` or `CANCELLED`, at least one non-cancelled order exists and every non-cancelled order has a `SIGNED_OFF` clearance test, and the project's `open_finding_count` is zero. (If every order is `CANCELLED`, this rule does not apply, because no non-cancelled order remains to carry a sign-off.)
3. Otherwise the posture is `CLEARANCE_PENDING` if there is at least one non-cancelled abatement order and every non-cancelled abatement order is `COMPLETED` (some still awaiting sign-off).
4. Otherwise the posture is `ABATING` if any abatement order is in `IN_PROGRESS` or `REOPENED` status.
5. Otherwise the posture is `CONTAINED` if any containment zone is in `ACTIVE` status.
6. Otherwise the posture is `ASSESSMENT`, the default that a freshly created project carries.

This precedence is authoritative and must be applied top to bottom. Alongside posture, a project carries an `open_finding_count`: the number of assessments under the project whose `finding_level` is either `ELEVATED` or `HAZARDOUS` and whose `status` is not yet `CLEARED`. Both `posture` and `open_finding_count` are derived fields — clients never set them directly. The same is true of `neshap_required` on the project, of `is_cert_current` on a worker, of `finding_level` on an assessment, of `concentration` and `result_grade` on a sample, of `latest_pressure_pa` and `is_compliant` on a zone, of `revision_index` and the recomputed `disposal_fee_cents`, of `clearance_concentration` and `outcome` on a clearance test, of `notice_days` on a permit, and of `estimated_amount_cents` and `settled_amount_cents` on an insurance claim. Whenever a derived field changes on a parent as a consequence of a child transition, that parent is itself mutated: its `updated_at` is refreshed and its `version` is incremented.

### 2.6. Optimistic Concurrency Control on Clearance Sign-Off

Exactly one operation participates in optimistic concurrency control: signing off a passed clearance test. A clearance sign-off request must carry `expected_project_version`, a non-optional field holding the `version` of the parent project that the client last observed. Before any business rule is evaluated, the server compares `expected_project_version` against the project's current `version`. If they do not match — because another sign-off has since advanced the project's version and cleared assessments, or because a clearance failure cascade has reopened an order and mutated the project — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This stale-version check protects the signer from acting on an outdated view of the project and the set of assessments the sign-off would clear; the signer's pinned version no longer matches the live project, so the write is refused. No other endpoint in the system takes a version field, and no other endpoint performs an OCC check.

### 2.7. Validation Ordering

When a request can fail several checks, the checks are evaluated in a fixed priority order and the **first** failing check determines the response. The order is: presence of the authentication headers (`ERR_MISSING_AUTH_HEADER`); recognized role (`ERR_INVALID_ROLE`); role permitted for the operation (`ERR_FORBIDDEN_ROLE`); existence of every resource identifier in the URL path, validated left to right (a `404` naming the first missing resource); existence of every foreign-key reference carried in the request body (a `404` naming the missing resource); cross-project consistency of those body references (`ERR_CROSS_PROJECT_REFERENCE`); request well-formedness — required fields present, enums valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`); timestamps not in the future relative to the logical clock (`ERR_TIMESTAMP_IN_FUTURE`); the optimistic-concurrency check where it applies (`ERR_STALE_VERSION`); the state-machine guard that the target is in a state from which the transition is defined (`ERR_INVALID_STATE`); and finally the operation-specific business and safety rules described throughout Section 3. Within a given endpoint, an earlier check that fails masks any later check that would also have failed — for example, a missing header is reported before an invalid role, and an unknown path resource is reported before any body validation.

When an endpoint path contains several resource identifiers, the system validates them in sequential left-to-right order and rejects the request with the `404` corresponding to the first identifier that does not resolve. Body foreign keys are checked only after every path identifier resolves. For body foreign keys, a missing referent yields the resource-specific not-found error (`ERR_PROJECT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_ABATEMENT_ORDER_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, or `ERR_ASSIGNMENT_NOT_FOUND` as appropriate).

### 2.8. Cross-Project Referential Integrity

Many create operations name a project together with one or more children of that project. Whenever a body carries both a `project_id` and another project-scoped reference — a `zone_id`, an `abatement_order_id`, an `assessment_id`, and so on — the referenced child must belong to the same project. If, for example, a `zone_id` resolves to a zone whose own project is different from the supplied `project_id`, or an `abatement_order_id` resolves to an order under a different project, the request is rejected with `ERR_CROSS_PROJECT_REFERENCE` (HTTP 409). This check runs after each referenced resource is confirmed to exist and before the request's well-formedness and business rules are evaluated.

### 2.9. Numeric Precision and Monetary Rounding

Monetary amounts are stored in integer cents — `disposal_fee_cents`, `estimated_amount_cents`, `settled_amount_cents`, `deductible_cents`, and `coverage_limit_cents` are all whole-cent integers. The disposal fee uses a floor at every step, detailed with the disposal workflow. Labor amounts inside the insurance calculations are rounded to the nearest whole cent using the round-half-up convention, per order, before they are summed; the summed integer cents are then exact. Air sample and clearance concentrations are computed as a count divided by a volume, scaled to spores per cubic meter, and rounded half up to a whole number (zero decimal places). Permit notice lead time is floored to whole days. Each calculation states its own rounding discipline where it is defined; where a calculation pins an order of operations (floor-then-sum, deductible-then-cap, per-manifest-then-total), that order is authoritative and a different order producing a different result is wrong.

### 2.10. Hierarchical Cascades and Reconciliation

A single field operation frequently mutates more than one entity. The system performs these cascades synchronously and to completion within the triggering request. Three families of cascade recur. First, **sample and assessment cascades**: uploading or voiding a sample recomputes the parent assessment's `finding_level`, which in turn recomputes the project's `open_finding_count`, which in turn recomputes the project's `posture`. Second, **containment cascades**: a pressure reading recomputes a zone's `latest_pressure_pa` and `is_compliant`, may flip the zone between `ACTIVE` and `BREACHED`, and recomputes the project's posture (a breach can freeze the project, and a restoring reading can unfreeze it). Third, **clearance and billing cascades**: a failed clearance reopens its order, voids that order's manifests, and recomputes both the insurance settlement and the project posture; a successful sign-off clears the covered assessments, recomputes `open_finding_count`, and recomputes posture. Each entity touched by a cascade is independently mutated, with its `updated_at` refreshed and (for entities that carry one) its `version` incremented. The specific cascade chains are described where each workflow is detailed in Section 3.

## 3. Business Logic & Workflows

### 3.1. Workers, Certification, and PPE Eligibility

The workforce is modeled as a pool of **Worker** records, each registered with a `full_name`, a certification discipline `cert_type` (one of `ASBESTOS`, `LEAD`, `MOLD`, or `HYGIENIST`), a certification expiry `cert_expires_at`, and a respirator fit-test timestamp `ppe_fit_test_at`. Worker registration is open to both a `ProjectManager` and a `ComplianceOfficer`. Every worker exposes a computed eligibility flag, `is_cert_current`, that the system recalculates whenever the worker is read or whenever an operation depends on it. A worker is current when two independent conditions both hold: the certification has not expired — `cert_expires_at` is strictly after the logical clock's current instant — and the respirator fit test is still inside its validity window — `ppe_fit_test_at` is strictly after the logical clock's current instant minus 365 days. If either condition fails, `is_cert_current` is false. The certification comparison is strict: a certification whose expiry equals the current instant is not current.

This eligibility flag is consulted at three later moments — starting an abatement order, assigning a worker to an order, and signing off a clearance — and the specific cross-checks that pair it with discipline matching and independence are described with those workflows.

### 3.2. The Project Lifecycle and Posture Transitions

A `ProjectManager` opens a remediation **Project** by supplying a `site_name`, a primary `hazard_class` (one of `ASBESTOS`, `LEAD`, or `MOLD`), the affected `structure_sqft` (a positive integer), and a regulatory `jurisdiction_code`. A new project starts with `status` `OPEN`, `posture` `ASSESSMENT`, `open_finding_count` zero, and a computed `neshap_required` flag. The NESHAP applicability flag is true exactly when the hazard class is `ASBESTOS` and the affected area is at least 160 square feet; for any other hazard class, or for an asbestos project under 160 square feet, it is false. This flag later gates whether abatement may start without a notification on file.

As field work proceeds, the project's posture climbs and falls through the precedence ladder defined in Section 2.5: a freshly created project sits at `ASSESSMENT`; activating the first containment zone advances it to `CONTAINED`; starting an abatement order advances it to `ABATING`; completing every non-cancelled order brings it to `CLEARANCE_PENDING`; and signing off the last outstanding clearance — with no open findings remaining — brings it to `VERIFIED`. A zone breach overrides all of these with `FROZEN` until pressure is restored.

The lifecycle closes in one of two ways. A `Hygienist` performs the final sign-off only when the project is `OPEN`, its posture is `VERIFIED`, and its `open_finding_count` is zero; the project's `status` then becomes the terminal `SIGNED_OFF`. Attempting this against a project that is not `OPEN` is rejected with `ERR_INVALID_STATE`; against a project whose posture is not `VERIFIED` with `ERR_PROJECT_NOT_VERIFIED`; and against a project that still has open findings with `ERR_OPEN_FINDINGS_REMAIN`. Alternatively, a `ProjectManager` may abandon an `OPEN` project, which moves `status` to the terminal `ABANDONED`; abandonment is refused with `ERR_ABATEMENT_IN_PROGRESS` if any abatement order is currently `IN_PROGRESS` or `REOPENED`. When a project is abandoned, every `PLANNED` abatement order under it is cancelled, and each such cancellation in turn releases that order's `ACTIVE` worker assignments, moving them to `RELEASED`.

### 3.3. Assessments and Sampling

Within a project, a `ProjectManager` or a `LabTech` records an **Assessment** of an inspected area by supplying the `project_id`, the `assessor_worker_id` of the worker who performed the inspection, and an `area_label`. An assessment starts in `DRAFT` with a `finding_level` of `CLEAN`. As samples are collected and analyzed, the assessment progresses `DRAFT → SAMPLED → ANALYZED → CLEARED`. The first sample created under a `DRAFT` assessment moves it to `SAMPLED`. Once every child sample has reached either `ANALYZED` or `VOIDED`, and at least one is `ANALYZED`, the assessment advances from `SAMPLED` to `ANALYZED` and its `finding_level` is computed. An assessment reaches the terminal `CLEARED` state only when a `SIGNED_OFF` clearance test covers its zone, as described in Section 3.8.

A **Sample** is collected by a `LabTech`, who supplies the `assessment_id`, the denormalized `project_id`, the `sample_type` (`AIR` or `SURFACE`), and a `collected_at` timestamp. For an `AIR` sample the air volume `volume_liters` is required and must be greater than zero; for a `SURFACE` sample `volume_liters` must be omitted entirely. Supplying volume for a surface sample, or omitting it (or supplying a non-positive value) for an air sample, is an `ERR_INVALID_REQUEST`. A `collected_at` after the logical clock's current instant is rejected with `ERR_TIMESTAMP_IN_FUTURE`. A new sample starts in `PENDING`, with `raw_count` null until results arrive.

When the laboratory reports a result, a `LabTech` uploads it to a `PENDING` sample, supplying `raw_count` — which must be present and at least zero, otherwise `ERR_INVALID_REQUEST`; the sample's `PENDING` state guard (`ERR_INVALID_STATE`) is evaluated before this `raw_count` validation. Uploading transitions the sample `PENDING → ANALYZED` and computes two derived fields. The `concentration` is computed first: for an `AIR` sample it is the raw count divided by the sampled volume in liters, multiplied by 1000 liters per cubic meter, then rounded half up to a whole number, expressed as spores per cubic meter; for a `SURFACE` sample the concentration is simply the raw count itself. The `result_grade` is then derived from the concentration by tiered thresholds keyed on sample type, with the lower bound of each tier inclusive. For an air sample, a concentration below 1000 spores per cubic meter grades `CLEAN`; a concentration at or above 1000 but below 10000 grades `ELEVATED`; a concentration at or above 10000 grades `HAZARDOUS`. For a surface sample, a raw count below 50 grades `CLEAN`; a count at or above 50 but below 500 grades `ELEVATED`; a count at or above 500 grades `HAZARDOUS`.

Uploading a result then cascades: the parent assessment's `finding_level` is recomputed, then the project's `open_finding_count`, then the project's `posture`. The `finding_level` of an assessment is the worst grade among its samples that are currently `ANALYZED` — samples that are `VOIDED` or still `PENDING` are excluded. Severity orders `CLEAN` below `ELEVATED` below `HAZARDOUS`; the finding level is the highest-severity grade across the analyzed samples, and if there are no analyzed samples the finding level is `CLEAN`.

A `ProjectManager` may void a sample. Voiding a `PENDING` sample simply moves it to `VOIDED` and recomputes the parent assessment's `finding_level`. Voiding an `ANALYZED` sample also moves it to `VOIDED` but carries an extra precondition and a longer cascade: it is permitted only when the parent assessment is not already `CLEARED` — voiding an analyzed sample under a `CLEARED` assessment is rejected with `ERR_ASSESSMENT_ALREADY_CLEARED` — and on success it recomputes the parent assessment's `finding_level`, then the project's `open_finding_count` (because the finding level may have changed), then the project's `posture`. Attempting to void a sample that is neither `PENDING` nor `ANALYZED` is an `ERR_INVALID_STATE`.

### 3.4. Containment Zones and Pressure Monitoring

A negative-pressure **ContainmentZone** isolates the work area. A `ProjectManager` or an `AbatementSupervisor` creates a zone by supplying the `project_id`, a `zone_label`, and the `required_pressure_pa` — the required negative-pressure magnitude in Pascals, expressed as a positive number, which must be at least 5 (the absolute floor any zone may require). A new zone starts in `SETUP` with `latest_pressure_pa` of 0 and `is_compliant` false.

Pressure is monitored by appending **PressureLog** readings. An `AbatementSupervisor` logs a reading against a zone by supplying the `zone_id`, the measured negative-pressure magnitude `reading_pa` (a positive number), and the `reading_at` timestamp, which must not be after the logical clock's current instant (else `ERR_TIMESTAMP_IN_FUTURE`). Each new reading recomputes the zone's `latest_pressure_pa`, defined as the `reading_pa` of the zone's reading with the greatest `reading_at`, breaking ties by the greatest `created_at`; if the zone has no readings the value is 0. The zone is then compliant — `is_compliant` true — exactly when `latest_pressure_pa` is greater than or equal to `required_pressure_pa`.

A new reading can drive a state change. If the zone is currently `ACTIVE` and the recomputed reading leaves it not compliant, the zone transitions `ACTIVE → BREACHED`, `is_compliant` is set false, and the project's posture is recomputed — a breach freezes the project to `FROZEN`, which outranks `ABATING`. If the zone is currently `BREACHED` and a later reading restores compliance, the zone transitions `BREACHED → ACTIVE`, `is_compliant` is set true, and the project's posture is recomputed, clearing the freeze back to whatever the precedence ladder now yields (typically `ABATING` or `CONTAINED`).

A `ProjectManager` activates a `SETUP` zone, moving it `SETUP → ACTIVE`. Activation requires the zone to be compliant at the moment of activation — that is, a pressure reading at or above the required magnitude must already be on file — otherwise the activation is rejected with `ERR_CONTAINMENT_NOT_COMPLIANT`. Activating the first zone recomputes the project posture, advancing it from `ASSESSMENT` to `CONTAINED`. A `ProjectManager` dismantles an `ACTIVE` zone, moving it to the terminal `DISMANTLED`, only when two conditions hold: no abatement order in that zone is in `PLANNED`, `IN_PROGRESS`, or `REOPENED` status (otherwise `ERR_ABATEMENT_IN_PROGRESS`), and a `SIGNED_OFF` clearance test exists for the zone (otherwise `ERR_NO_PASSING_CLEARANCE`). Dismantling recomputes the project posture. Activating or dismantling a zone that is not in the required starting state yields `ERR_INVALID_STATE`.

### 3.5. Abatement Orders, Crews, and the Revision Loop

The removal work itself is an **AbatementOrder**. An `AbatementSupervisor` creates an order by supplying the `project_id`, the `zone_id` it runs in, the `lead_worker_id`, the `abatement_type` (`ASBESTOS`, `LEAD`, or `MOLD`), and the `planned_weight_kg` of hazardous material expected to be removed (a positive number). A revision of a previously failed order additionally carries `supersedes_order_id` pointing at the predecessor; the system then computes the order's `revision_index`, which is 0 for an original order and the predecessor's `revision_index` plus 1 for a superseding revision. A new order starts `PLANNED`.

Crews are attached through **WorkerAssignment** records. An `AbatementSupervisor` assigns a worker to an order by supplying the `abatement_order_id`, the `worker_id`, and the shift window `shift_start_at` and `shift_end_at`; the shift end must be strictly after the shift start, otherwise `ERR_INVALID_REQUEST`. A new assignment starts `ACTIVE`. Worker assignments have no direct release endpoint: an assignment reaches `RELEASED` only as a cascade when its order is cancelled (or when an abandoned project cancels its `PLANNED` orders).

Starting an order is the most heavily gated transition in the system. An `AbatementSupervisor` starts an order that is `PLANNED` (or restarts one that is `REOPENED`), moving it to `IN_PROGRESS`. Several preconditions must all hold, each with its own rejection: the order must be in `PLANNED` or `REOPENED` (else `ERR_INVALID_STATE`); the referenced zone must be `ACTIVE` (else `ERR_ZONE_NOT_ACTIVE`); the lead worker must be current and their `cert_type` must equal the order's `abatement_type` (else `ERR_WORKER_NOT_CERTIFIED`); and at least one `ACTIVE` worker assignment on the order must belong to a worker whose certification is current (else `ERR_NO_CERTIFIED_CREW`). When the project's `neshap_required` flag is true, starting additionally requires an `ACKNOWLEDGED` `NESHAP_NOTIFICATION` permit whose `notice_days` is at least 10 and whose `work_start_at` is at or before the logical clock's current instant (else `ERR_NESHAP_NOTICE_NOT_MET`); this NESHAP gate is evaluated before the certified-crew check, so when both would fail `ERR_NESHAP_NOTICE_NOT_MET` is reported ahead of `ERR_NO_CERTIFIED_CREW`. On a successful start from `PLANNED`, the project posture is recomputed, advancing `CONTAINED → ABATING`; a successful restart from `REOPENED` likewise recomputes posture back to `ABATING`.

An `AbatementSupervisor` completes an `IN_PROGRESS` order, moving it to `COMPLETED`, by supplying the actual `removed_weight_kg`, which must be present and greater than zero (else `ERR_INVALID_REQUEST`); the order's `IN_PROGRESS` state guard (`ERR_INVALID_STATE`) is evaluated before this `removed_weight_kg` validation. Completion further requires that the referenced zone still be `ACTIVE` (else `ERR_ZONE_NOT_ACTIVE`) and that an `ACCEPTED` disposal manifest exist for the order whose `manifest_weight_kg` is at least the reported `removed_weight_kg` (else `ERR_MANIFEST_WEIGHT_SHORT`). Completing an order recomputes the insurance claim's estimate and settlement, and recomputes the project posture — when every non-cancelled order has reached `COMPLETED`, posture advances to `CLEARANCE_PENDING`.

The revision loop is what makes the order state machine cyclic. A `COMPLETED` order is reopened — `COMPLETED → REOPENED` — automatically by the system when a clearance test for that order fails, as detailed in Section 3.8. A `REOPENED` order is started again by an `AbatementSupervisor`, returning to `IN_PROGRESS`, subject to the zone-active, lead-certification, and certified-crew gates above (the NESHAP gate is not re-checked on the reopened restart).

Orders can also be cancelled by a `ProjectManager`. Cancelling a `PLANNED` order moves it to the terminal `CANCELLED` and releases all of its `ACTIVE` worker assignments to `RELEASED`, then recomputes posture. Cancelling an `IN_PROGRESS` order is permitted only when no clearance test in `ANALYZED`, `PASSED`, or `SIGNED_OFF` status references the order (otherwise `ERR_CLEARANCE_IN_PROGRESS`); on success it releases the order's `ACTIVE` assignments to `RELEASED`, recomputes the insurance estimate (the order leaves provisional scope), and recomputes posture. Cancelling from any other state is `ERR_INVALID_STATE`.

### 3.6. Disposal Manifests and Tiered Fees

Hazardous waste leaves the site under a **DisposalManifest**. An `AbatementSupervisor` drafts a manifest for an order by supplying the `abatement_order_id`, the denormalized `project_id`, the licensed `hauler_name`, and the declared `manifest_weight_kg` (a positive number). The manifest's `disposal_fee_cents` is computed provisionally on creation and finalized later on acceptance. A new manifest starts in `DRAFT`.

The disposal fee is a tiered per-kilogram charge with a hazard surcharge, and the order of operations is pinned. The declared weight is split across three marginal tiers: the portion up to 100 kg is charged at 80 cents per kilogram; the portion above 100 kg and up to 500 kg is charged at 120 cents per kilogram; and the portion above 500 kg is charged at 200 cents per kilogram. The cost of each tier is computed and **floored to whole cents independently, tier by tier, before the tiers are summed** — this per-tier flooring is authoritative, and summing first and rounding once is wrong. The floored tier costs are then added to a base fee of zero cents (there is no separate flat base charge). A surcharge multiplier is then applied according to the parent order's `abatement_type`: an asbestos order multiplies the base fee by 1.5, a lead order by 1.25, and a mold order by 1.0. The product is floored once more to whole cents to give `disposal_fee_cents`. In short: floor each tier's marginal cost, sum the floored tiers, multiply by the hazard surcharge, then floor the result.

A manifest moves through `DRAFT → SUBMITTED → ACCEPTED`, and may be voided to the terminal `VOIDED`. An `AbatementSupervisor` submits a `DRAFT` manifest only when the parent order is `IN_PROGRESS` or `COMPLETED` (otherwise `ERR_INVALID_STATE`); and when the parent order's `abatement_type` is `ASBESTOS`, an `ACKNOWLEDGED` `TRANSPORT` permit must exist for the project, otherwise the submission is rejected with `ERR_TRANSPORT_PERMIT_MISSING`. A `ProjectManager` accepts a `SUBMITTED` manifest, moving it to `ACCEPTED`; acceptance finalizes `disposal_fee_cents` and recomputes both the insurance estimate and settlement. A `ProjectManager` may void a `SUBMITTED` manifest manually, which recomputes the insurance estimate. An `ACCEPTED` manifest is not voided manually; it moves to `VOIDED` only as a cascade when its parent order is reopened after a failed clearance, and that void recomputes the insurance settlement (the manifest leaves the actuals). Submitting, accepting, or voiding a manifest from a state where the transition is not defined is `ERR_INVALID_STATE`.

### 3.7. Permits and NESHAP Notification

Regulatory paperwork is modeled as **Permit** records, created by a `ComplianceOfficer` with the `project_id`, the `permit_type` (`NESHAP_NOTIFICATION`, `DEMOLITION`, or `TRANSPORT`), the `postmarked_at` notification timestamp, and the planned `work_start_at`. The postmark must not be after the logical clock's current instant (else `ERR_TIMESTAMP_IN_FUTURE`). On creation the system computes `notice_days`, the whole number of 24-hour periods between postmark and planned start: the elapsed seconds from `postmarked_at` to `work_start_at` are divided by 86400 and floored; if the planned start is at or before the postmark the notice is 0 days.

A permit advances `DRAFT → SUBMITTED → ACKNOWLEDGED → EXPIRED`, each step driven by a `ComplianceOfficer`. Submitting a `DRAFT` permit is unconditional except for a `NESHAP_NOTIFICATION`, whose `notice_days` must be at least 10 at submission time, otherwise the submission is rejected with `ERR_NESHAP_NOTICE_NOT_MET`. Acknowledging a `SUBMITTED` permit moves it to `ACKNOWLEDGED`, and expiring an `ACKNOWLEDGED` permit moves it to the terminal `EXPIRED`. Each transition from the wrong starting state is an `ERR_INVALID_STATE`. The 10-day NESHAP lead requirement reappears at abatement start for NESHAP-required projects, where an acknowledged notification with sufficient lead and a past-due `work_start_at` is the precondition described in Section 3.5.

### 3.8. Clearance Testing, the Pass/Fail Fork, and Sign-Off

Post-remediation verification is a **ClearanceTest**. A `LabTech` creates a test against a completed order by supplying the `project_id`, the `zone_id` being cleared, the `abatement_order_id` under test, the `sampler_worker_id` who collected the clearance samples, the post-remediation air structure count `clearance_air_count` (non-negative), and the air volume sampled `clearance_volume_liters` (positive). A new test starts in `DRAFT`. The `signoff_worker_id` is left unset until sign-off.

A `LabTech` analyzes a `DRAFT` test, moving it to `ANALYZED`, only when the referenced order is `COMPLETED` (otherwise `ERR_ORDER_NOT_COMPLETED`). Analysis computes `clearance_concentration` as the clearance air count divided by the clearance volume in liters, multiplied by 1000 liters per cubic meter, rounded half up to a whole number of spores per cubic meter. The `outcome` is then determined against a hazard-specific limit keyed on the project's `hazard_class`: 70 spores per cubic meter for asbestos, 200 for lead, and 900 for mold. The outcome is `PASS` when the clearance concentration is strictly below the applicable limit, and `FAIL` when it is at or above the limit — a concentration exactly equal to the limit fails. Analysis then auto-forks: a `PASS` moves the test `ANALYZED → PASSED`, and a `FAIL` moves it `ANALYZED → FAILED`.

The two branches diverge sharply. `PASSED` is an intermediate state awaiting an independent sign-off. `FAILED` is terminal for that test and triggers a four-hop cascade: the referenced order is reopened (`COMPLETED → REOPENED`); that order's `ACCEPTED` (and `SUBMITTED`) disposal manifests are voided to `VOIDED`; the insurance settlement is recomputed because the voided manifests leave the actuals; and the project posture is recomputed down to `ABATING`. A failed clearance thus rewinds the order back into the revision loop, where a superseding revision can be created and run again.

Sign-off is where segregation of duties is enforced. A `Hygienist` signs off a `PASSED` test, supplying `signoff_worker_id` and the `expected_project_version` for the optimistic-concurrency check. Several preconditions apply, evaluated after the OCC check described in Section 2.6: the test must be `PASSED` (else `ERR_INVALID_STATE`); the optimistic-concurrency check must pass (else `ERR_STALE_VERSION`); the nominated sign-off worker must be a current `HYGIENIST` — `cert_type` equal to `HYGIENIST` and `is_cert_current` true (else `ERR_WORKER_NOT_CERTIFIED`); and the sign-off worker must be independent, meaning `signoff_worker_id` is neither the `sampler_worker_id` of this test nor the `lead_worker_id` of the referenced abatement order (else `ERR_SIGNOFF_NOT_INDEPENDENT`). On success the test moves `PASSED → SIGNED_OFF`, its `signoff_worker_id` is recorded, and a cascade runs: because assessments carry no zone reference, every assessment under the project that is currently in `ANALYZED` status advances `ANALYZED → CLEARED` (no matter which zone the sign-off cleared); the project's `open_finding_count` is recomputed (the cleared assessments drop out); the project posture is recomputed, reaching `VERIFIED` once every zone is cleared and no findings remain; and finally the project's `version` is incremented by one. That version bump is what makes a competing in-flight sign-off's `expected_project_version` stale.

### 3.9. Insurance Billing: Estimate versus Settlement

Each project may carry an **InsuranceClaim**, opened by a `ProjectManager` with the `project_id`, the `policy_number`, the `deductible_cents` (non-negative), and the `coverage_limit_cents` (positive). A new claim starts `OPEN` with `estimated_amount_cents` and `settled_amount_cents` both zero. The claim exposes two deliberately different computed amounts.

The **estimate** (`estimated_amount_cents`) is forward-looking and provisional. Its scope is the set of abatement orders whose status is `PLANNED`, `IN_PROGRESS`, or `COMPLETED` (orders that are `CANCELLED` or `REOPENED` are excluded). The labor component sums, over those scope orders, the order's `planned_weight_kg` multiplied by 1500 cents per kilogram, each product rounded half up to whole cents before summing. The disposal component sums the `disposal_fee_cents` of every disposal manifest in `DRAFT`, `SUBMITTED`, or `ACCEPTED` status whose order is in scope, where each manifest's fee was already tiered and rounded on its own; the per-manifest fees are summed and the order of operations matters — two separate 60 kg manifests, each entirely inside the first disposal tier, do not produce the same total as one 120 kg manifest whose 20 kg crosses into the second tier. The estimate is the labor plus disposal sum; no deductible and no coverage cap are applied. The estimate is recomputed whenever an order is created, started, completed, or cancelled, whenever a manifest is created, submitted, accepted, or voided, and on claim submission.

The **settlement** (`settled_amount_cents`) is the final figure over actuals only. Its scope is the abatement orders whose status is `COMPLETED`. The labor component sums, over those completed orders, the actual `removed_weight_kg` multiplied by 1500 cents per kilogram, each product rounded half up to whole cents before summing. The disposal component sums the `disposal_fee_cents` of only the `ACCEPTED` manifests whose order is completed. Those two sums give the gross. The deductible is then subtracted, floored at zero — the amount after deductible is the gross minus `deductible_cents` but never below zero. Finally the coverage cap is applied: the settlement is the smaller of the after-deductible amount and `coverage_limit_cents`. The order is pinned — deductible first, then cap — and applying the cap before the deductible would be wrong. The settlement is recomputed when an order completes, when a manifest is accepted or voided, on the clearance-failure cascade, and on claim settlement.

The claim advances `OPEN → SUBMITTED → SETTLED`, or `SUBMITTED → DENIED`. A `ProjectManager` submits an `OPEN` claim only when the project posture is `CLEARANCE_PENDING` or `VERIFIED` (otherwise `ERR_PROJECT_NOT_READY_FOR_BILLING`); submission recomputes the estimate and also reconciles the `settled_amount_cents` against the current actuals. A `ComplianceOfficer` settles a `SUBMITTED` claim only when the project posture is `VERIFIED` (otherwise `ERR_PROJECT_NOT_VERIFIED`); settlement recomputes the final settled amount. There is one fiscal guard at settlement: if the gross settlement (before deductible and cap) exceeds `coverage_limit_cents`, the request must carry `allow_over_cap` set to true to proceed; if `allow_over_cap` is omitted or false while the gross exceeds the coverage limit, the settle is rejected with `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 402) so that an over-cap claim is never silently capped without an explicit operator decision. A `ComplianceOfficer` may instead deny a `SUBMITTED` claim, moving it to the terminal `DENIED`. Any of these transitions from the wrong starting state is an `ERR_INVALID_STATE`.

## 4. Endpoint Definitions

Operations that create a brand-new resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the logical-clock setter — return a `200 OK` status code. All list endpoints accept the `limit` and `offset` query parameters described in Section 2.3, plus the domain filters noted below; all read and list endpoints are open to every recognized role.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Set the server logical clock | ComplianceOfficer |
| POST | `/api/workers` | Register a worker with certification and PPE data | ProjectManager, ComplianceOfficer |
| GET | `/api/workers` | List workers (filter: `cert_type`) | All roles |
| GET | `/api/workers/{wid}` | Get a worker with computed `is_cert_current` | All roles |
| POST | `/api/projects` | Create a remediation project | ProjectManager |
| GET | `/api/projects` | List projects (filters: `hazard_class`, `posture`) | All roles |
| GET | `/api/projects/{pid}` | Get a project with computed posture and counts | All roles |
| POST | `/api/projects/{pid}/signoff` | Final project sign-off; closes the project | Hygienist |
| POST | `/api/projects/{pid}/abandon` | Abandon a project; cancel planned orders, release crews | ProjectManager |
| POST | `/api/assessments` | Create an assessment under a project | ProjectManager, LabTech |
| GET | `/api/assessments` | List assessments (filters: `project_id`, `assessor_worker_id`) | All roles |
| GET | `/api/assessments/{aid}` | Get an assessment with computed `finding_level` | All roles |
| POST | `/api/samples` | Collect a sample under an assessment | LabTech |
| GET | `/api/samples` | List samples (filters: `assessment_id`, `project_id`) | All roles |
| GET | `/api/samples/{sid}` | Get a sample with computed concentration and grade | All roles |
| POST | `/api/samples/{sid}/result` | Upload lab `raw_count`; analyze the sample | LabTech |
| POST | `/api/samples/{sid}/void` | Void a sample | ProjectManager |
| POST | `/api/containment-zones` | Create a containment zone | ProjectManager, AbatementSupervisor |
| GET | `/api/containment-zones` | List containment zones (filter: `project_id`) | All roles |
| GET | `/api/containment-zones/{zid}` | Get a zone with computed pressure and compliance | All roles |
| POST | `/api/containment-zones/{zid}/pressure-logs` | Append a pressure reading; recompute compliance | AbatementSupervisor |
| GET | `/api/pressure-logs` | List pressure logs (filter: `zone_id`) | All roles |
| GET | `/api/pressure-logs/{plid}` | Get a single pressure log reading | All roles |
| POST | `/api/containment-zones/{zid}/activate` | Activate a zone (requires compliant pressure) | ProjectManager |
| POST | `/api/containment-zones/{zid}/dismantle` | Dismantle a zone | ProjectManager |
| POST | `/api/abatement-orders` | Create an abatement order | AbatementSupervisor |
| GET | `/api/abatement-orders` | List orders (filters: `project_id`, `zone_id`, `lead_worker_id`, `supersedes_order_id`) | All roles |
| GET | `/api/abatement-orders/{aid}` | Get an abatement order | All roles |
| POST | `/api/abatement-orders/{aid}/start` | Start or restart an order | AbatementSupervisor |
| POST | `/api/abatement-orders/{aid}/complete` | Complete an order (requires `removed_weight_kg`) | AbatementSupervisor |
| POST | `/api/abatement-orders/{aid}/cancel` | Cancel an order | ProjectManager |
| POST | `/api/assignments` | Assign a worker to an abatement order | AbatementSupervisor |
| GET | `/api/assignments` | List assignments (filters: `abatement_order_id`, `worker_id`) | All roles |
| GET | `/api/assignments/{asid}` | Get a worker assignment | All roles |
| POST | `/api/disposal-manifests` | Create a disposal manifest for an order | AbatementSupervisor |
| GET | `/api/disposal-manifests` | List manifests (filters: `abatement_order_id`, `project_id`) | All roles |
| GET | `/api/disposal-manifests/{mid}` | Get a manifest with computed `disposal_fee_cents` | All roles |
| POST | `/api/disposal-manifests/{mid}/submit` | Submit a manifest | AbatementSupervisor |
| POST | `/api/disposal-manifests/{mid}/accept` | Accept a manifest; finalize fee; recompute claim | ProjectManager |
| POST | `/api/disposal-manifests/{mid}/void` | Void a submitted manifest | ProjectManager |
| POST | `/api/clearance-tests` | Create a clearance test against a completed order | LabTech |
| GET | `/api/clearance-tests` | List clearance tests (filters: `project_id`, `zone_id`, `abatement_order_id`, `sampler_worker_id`, `signoff_worker_id`) | All roles |
| GET | `/api/clearance-tests/{cid}` | Get a clearance test with computed concentration and outcome | All roles |
| POST | `/api/clearance-tests/{cid}/analyze` | Analyze a test; compute outcome; fork pass/fail | LabTech |
| POST | `/api/clearance-tests/{cid}/signoff` | Sign off a passed test (independent Hygienist; OCC) | Hygienist |
| POST | `/api/permits` | Create a permit or notification | ComplianceOfficer |
| GET | `/api/permits` | List permits (filters: `project_id`, `permit_type`) | All roles |
| GET | `/api/permits/{pmid}` | Get a permit with computed `notice_days` | All roles |
| POST | `/api/permits/{pmid}/submit` | Submit a permit | ComplianceOfficer |
| POST | `/api/permits/{pmid}/acknowledge` | Acknowledge a permit | ComplianceOfficer |
| POST | `/api/permits/{pmid}/expire` | Expire a permit | ComplianceOfficer |
| POST | `/api/insurance-claims` | Open an insurance claim for a project | ProjectManager |
| GET | `/api/insurance-claims` | List insurance claims (filter: `project_id`) | All roles |
| GET | `/api/insurance-claims/{clid}` | Get a claim with estimated and settled amounts | All roles |
| POST | `/api/insurance-claims/{clid}/submit` | Submit a claim | ProjectManager |
| POST | `/api/insurance-claims/{clid}/settle` | Settle a claim (`allow_over_cap` for over-cap) | ComplianceOfficer |
| POST | `/api/insurance-claims/{clid}/deny` | Deny a claim | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_HEADER` | 401 Unauthorized |
| `ERR_INVALID_ROLE` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_ASSESSMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SAMPLE_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_ABATEMENT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_CLEARANCE_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_WORKER_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_PROJECT_REFERENCE` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_TIMESTAMP_IN_FUTURE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_ALREADY_CLEARED` | 409 Conflict |
| `ERR_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_ZONE_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLEARANCE_IN_PROGRESS` | 409 Conflict |
| `ERR_ABATEMENT_IN_PROGRESS` | 409 Conflict |
| `ERR_NO_PASSING_CLEARANCE` | 409 Conflict |
| `ERR_MANIFEST_WEIGHT_SHORT` | 409 Conflict |
| `ERR_PROJECT_NOT_READY_FOR_BILLING` | 409 Conflict |
| `ERR_PROJECT_NOT_VERIFIED` | 409 Conflict |
| `ERR_OPEN_FINDINGS_REMAIN` | 409 Conflict |
| `ERR_WORKER_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_SIGNOFF_NOT_INDEPENDENT` | 422 Unprocessable Entity |
| `ERR_CONTAINMENT_NOT_COMPLIANT` | 422 Unprocessable Entity |
| `ERR_NESHAP_NOTICE_NOT_MET` | 422 Unprocessable Entity |
| `ERR_TRANSPORT_PERMIT_MISSING` | 422 Unprocessable Entity |
| `ERR_NO_CERTIFIED_CREW` | 422 Unprocessable Entity |
| `ERR_COVERAGE_LIMIT_EXCEEDED` | 402 Payment Required |

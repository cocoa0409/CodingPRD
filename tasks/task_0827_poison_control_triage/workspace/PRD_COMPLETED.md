# Poison Control Triage API — Product Requirements Document

## 1. Introduction

Poison control centers field time-critical calls in which a caller reports a possible exposure — a substance, a dose, a route of contact — and a specialist must rapidly convert incomplete information into a defensible clinical decision: manage the patient at home, or refer them to an emergency department. This API is the system of record for that decision pipeline. It captures call intake and patient demographics, records one or more substance exposures, computes toxicity and aggregate risk from reference pharmacology, selects a management protocol, and enforces the safety gates that keep high-risk patients from being sent home.

Beyond the single call, the platform coordinates the downstream obligations that a poison center carries. Scheduled follow-up calls track a home-managed patient's recovery and can escalate a case that worsens; healthcare-facility consults let a senior toxicologist confirm a real ingested dose and re-score the case against laboratory truth; and a surveillance channel feeds anonymized case outcomes to national poisoning statistics. Each of these functions is expressed as a governed lifecycle with explicit state transitions, cascading side effects, and role-based authority, so that every clinical and administrative action is auditable and every derived number is reproducible.

This document specifies the complete contract: the global conventions every endpoint honors, the business rules that govern each workflow, the full endpoint surface, and the catalogue of error codes the system emits.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational role. The system recognizes exactly four roles: `Specialist`, `Toxicologist`, `SurveillanceOfficer`, and `SystemAdmin`. If either header is missing or `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Two of the roles are backed by a persisted entity, and two are opaque operator identities:

- When `X-User-Role` is `Specialist`, `X-User-ID` is the `id` of the acting `Specialist`; ownership and attribution checks on any resource that references a specialist compare that resource's specialist foreign-key field to `X-User-ID`. In particular, opening a case stamps `intake_specialist_id` from `X-User-ID`.
- When `X-User-Role` is `Toxicologist`, `X-User-ID` is likewise the `id` of the acting `Specialist` record (a toxicologist is a senior specialist holding the `TOXICOLOGIST` credential); the same ownership comparison applies, and opening a facility consult stamps `requesting_specialist_id` from `X-User-ID`.
- When `X-User-Role` is `SurveillanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `author_ref` on a `CaseNote` — but never compares it to any entity's `id`.
- When `X-User-Role` is `SystemAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it may be recorded as `author_ref` for documentation but is never used as a business-decision input.

The `Toxicologist` role is a clinical superset of `Specialist`: any operation a `Specialist` may perform, a `Toxicologist` may also perform, plus the toxicologist-exclusive authority described throughout §3.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100, and a supplied value outside that range is clamped into it (a `limit` below 1 becomes 1, above 100 becomes 100). The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is not a valid integer is rejected with `ERR_VALIDATION` (HTTP 422). Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order, with ties on an identical `created_at` (common while the logical clock is held fixed) broken by ascending creation order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a system-managed `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits marking when the resource was first created. Most resources additionally carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits), refreshed on every mutation, and a `version` — an integer that starts at 1 and increments by one on every mutation of that resource, used for optimistic concurrency control as described in §2.7.

One resource is deliberately leaner: a `CaseNote` is an append-only documentation record and therefore carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because it is never modified after creation.

### 2.5. The Logical Clock

All scheduling, expiry, and time-stamping in this system are driven by a logical clock rather than wall-clock time, so that time-dependent behavior is deterministic and test-drivable. At server startup the logical clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it remains at this default and never falls back to real wall-clock time. A `SystemAdmin` may advance or reset the clock by supplying a new instant in the `to_iso8601` field; this becomes the reference "now" used by follow-up scheduling, retry rescheduling, and every logical-clock timestamp — including each resource's `created_at` and `updated_at` as well as `resolved_at` and `reported_at`. The envelope's `api_request_timestamp` is the sole timestamp drawn from real wall-clock time rather than the logical clock.

### 2.6. Numeric Precision and Rounding

Every computed score, aggregate, and billing figure is carried to 2 decimal places using the round-half-up convention. Where a calculation prescribes an intermediate rounding step — for example, rounding each per-exposure contribution before those contributions are summed — that intermediate rounding is also performed to 2 decimal places, round-half-up, and the pinned order of operations described in §3 must be honored exactly, because rounding before versus after summation can change the final result.

### 2.7. Optimistic Concurrency Control

Creating a risk assessment for a case is guarded by optimistic concurrency control against the parent `ExposureCase`. The create request must carry `expected_case_version` holding the `version` of the target `ExposureCase` that the client last observed. If another writer has advanced the case's `version` since then — by creating a superseding assessment or adding an exposure — the client's view is stale, and the create is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412), preventing the client from overwriting an assessment it has not observed. A successful create increments the case's `version` by one. This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.8. Nested Resource Retrieval and Existence Ordering

Many endpoints address a resource through a path that names a case and then a sub-resource. Path identifiers are validated left to right. The owning case is resolved first: if the case `id` in the path does not resolve, the request fails immediately with `ERR_CASE_NOT_FOUND` (HTTP 404) before any sub-resource is considered. When a sub-resource id in the path — an exposure, risk assessment, disposition, follow-up call, facility consult, or NPDS report — does not resolve, the request fails with `ERR_RESOURCE_NOT_FOUND` (HTTP 404). Separately, when a request body references a configuration or peer resource by foreign key — a `substance_id`, `facility_id`, `risk_assessment_id`, or `primary_substance_id` — and that reference does not resolve, the request fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404).

### 2.9. Hierarchical Consistency and Cascades

The `ExposureCase` is the aggregate root; its exposures, risk assessments, dispositions, follow-up calls, and case notes live under it, while facility consults and NPDS reports reference a case from outside the tree. Many operations mutate more than one entity at once, and the system applies every cascade immediately and synchronously within the triggering request. When the server automatically advances a resource — superseding an assessment, cancelling follow-up calls, escalating a case, or bubbling a case to a resolved state — each affected resource is independently mutated, with its `updated_at` refreshed and its `version` incremented. The specific cascades are described in the workflow that triggers them in §3; the governing principle here is that they are never deferred and never partial.

### 2.10. Order of Validation

When several checks could apply to one request, they are evaluated in a fixed priority order, and the first failure determines the error returned. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of path-referenced resources — the owning case (`ERR_CASE_NOT_FOUND`) before any nested sub-resource (`ERR_RESOURCE_NOT_FOUND`) — then existence of body-referenced foreign keys (`ERR_REFERENCE_NOT_FOUND`), then whether the target entity is in a state that permits the requested transition (`ERR_INVALID_STATE`, HTTP 409). Only after all of those pass are the operation-specific business rules evaluated. Malformed payloads — a missing required field, a wrong type, or an invalid enum value — are rejected with `ERR_INVALID_REQUEST` (HTTP 400). A semantic validation failure that is not covered by any more specific code is reported with the generic `ERR_VALIDATION` (HTTP 422). The business rules that sit at the tail of this order, and their specific codes, are introduced alongside the workflows they guard in §3.

## 3. Business Logic & Workflows

### 3.1. Reference Configuration

Before any call can be triaged, a `SystemAdmin` seeds the reference data. A **substance** is registered with a `name`, a toxicologic `category` — one of `ANALGESIC`, `HOUSEHOLD_CHEMICAL`, `PESTICIDE`, `PLANT`, `PHARMACEUTICAL`, `HYDROCARBON`, or `HEAVY_METAL` — a `toxic_dose_mg_per_kg` reference toxic dose greater than zero that serves as the denominator of the dose-ratio calculation, an `onset_hours` symptom-onset window greater than zero, and a canonical `reference_route` — one of `INGESTION`, `INHALATION`, `DERMAL`, `OCULAR`, or `INJECTION`. Each substance also exposes a surveillance counter, `aggregate_case_count`, which begins at 0 and reflects how many submitted NPDS reports credit this substance; it is maintained by the surveillance workflow, not supplied at creation.

A **healthcare facility** is registered with a `name`, a `facility_type` — one of `ED`, `URGENT_CARE`, `ICU`, or `CLINIC` — an optional consult-acceptance `status` that defaults to `ACCEPTING` and is otherwise `DIVERTING` or `OFFLINE`, and a `consult_capacity` of at least 1 that caps how many consults it may hold at once. Its `active_consult_count` starts at 0 and is maintained automatically as consults open and close.

A **protocol** describes how a given tier is managed. It is created with a `risk_tier` — one of `MINIMAL`, `MODERATE`, `SEVERE`, or `CRITICAL` — a `management_setting` of either `HOME` or `ED`, a `followup_count` of zero or more scheduled follow-up calls to generate under home management, a `followup_interval_hours` greater than zero between consecutive follow-up calls, and an optional `requires_toxicologist` flag that defaults to false. When `requires_toxicologist` is true, a risk assessment on that tier may only be finalized by a `Toxicologist`.

A **specialist** is registered with a `full_name`, a `credential` of either `SPI` or `TOXICOLOGIST`, and an optional `certification_active` flag that defaults to true and indicates whether the specialist may currently act on cases. The `TOXICOLOGIST` credential is the certification that backs the `Toxicologist` role.

### 3.2. Call Intake, Interpreters, and Documentation

A `Specialist` (or `Toxicologist`) opens a case at intake by recording the patient's `patient_age_years` (zero or greater), `patient_weight_kg` (greater than zero, and the per-kilogram denominator for toxicity), `patient_sex` — one of `MALE`, `FEMALE`, or `UNKNOWN` — and a free-text `chief_complaint`. Two optional intake fields capture language support: `interpreter_required` defaults to false, and `interpreter_language` holds the ISO language code (for example `es` or `zh`) and defaults to null. When `interpreter_required` is true, `interpreter_language` must be supplied; omitting it is rejected with `ERR_INTERPRETER_LANGUAGE_REQUIRED` (HTTP 422). On creation the case enters `INTAKE`, its `intake_specialist_id` is stamped from `X-User-ID`, and its computed fields — `status`, `risk_tier` (null until an assessment exists), `pending_followup_count` (0), and `resolved_at` (null) — take their initial values.

Throughout the case, an authorized specialist may append documentation. A **case note** carries a `note_type` — one of `INTAKE`, `CLINICAL`, `INTERPRETER`, `DISPOSITION`, or `FOLLOWUP` — and a free-text `body`. Notes are append-only: each records its `author_ref` from `X-User-ID` for attribution only, and this value is never an input to any business decision. Cases may be listed and filtered by `status` and by `intake_specialist_id`; their notes may be listed per case.

### 3.3. Recording Exposures and Toxicity Scoring

Onto a case, the specialist records one or more **exposures**. Each exposure names the `substance_id` involved, the `route` of exposure — one of `INGESTION`, `INHALATION`, `DERMAL`, `OCULAR`, or `INJECTION` — a reported dose range with `dose_range_low_mg` (zero or greater) and `dose_range_high_mg` (which must be at least `dose_range_low_mg`), and `time_since_exposure_hours` (zero or greater) elapsed since the exposure. The system records the owning `case_id` from the path. An exposure's `identified` flag is true once its `substance_id` resolves to a known substance. A `confirmed_dose_mg` field remains null until a facility consult later writes a laboratory-verified dose.

The moment an exposure is recorded, the system computes its `toxicity_score` and `severity_band` using the **ESTIMATED** variant of the toxicity calculation, which uses the worst-case upper bound of the reported range. The score is built as follows. First, a bioavailability factor is selected by route: `INGESTION` and `INJECTION` are 1.0, `INHALATION` is 0.8, `DERMAL` is 0.4, and `OCULAR` is 0.3. The effective dose in milligrams is the applicable dose multiplied by that bioavailability factor; under the ESTIMATED variant the applicable dose is `dose_range_high_mg`, whereas once `confirmed_dose_mg` is present the **CONFIRMED** variant uses `confirmed_dose_mg` in its place. The effective dose is divided by the case's `patient_weight_kg` to give a per-kilogram dose, and that per-kilogram dose is divided by the substance's `toxic_dose_mg_per_kg` to give the dose ratio.

A time-attenuation factor then discounts stale exposures. If `time_since_exposure_hours` is less than or equal to the substance's `onset_hours`, the time factor is exactly 1.0. Otherwise, the number of whole onset-windows that have elapsed beyond onset is computed by taking the hours past onset, dividing by `onset_hours`, and rounding down to a whole number; the time factor is 1.0 minus 0.1 for each such whole window, but never allowed to fall below 0.5 — that is, the larger of 0.5 and that reduced value. The `toxicity_score` is the dose ratio multiplied by the time factor, rounded half-up to 2 decimal places. Its `severity_band` is `MINIMAL` when the score is below 0.25, `MODERATE` when it is at least 0.25 but below 0.75, `SEVERE` when it is at least 0.75 but below 1.5, and `CRITICAL` when it is 1.5 or greater. Exposures may be listed and filtered by `case_id` or by `substance_id`.

Adding an exposure to a case that is already in `MONITORING` is a clinically significant event: it drives the case from `MONITORING` to `RETRIAGE`. As part of that transition, the case's active risk assessment moves from `COMPLETED` or `FINALIZED` to `SUPERSEDED`, and its active disposition moves from `ACTIVE` to `SUPERSEDED`, so the case must be re-assessed and re-dispositioned before it can settle again.

### 3.4. Triage, Risk Assessment, and Finalization

Once at least one exposure is on the case, a `Specialist` triages it, advancing the case from `INTAKE` to `TRIAGED`. Triage is refused with `ERR_NO_EXPOSURES` (HTTP 422) if the case has no exposures, and it requires that every exposure be `identified`. Triage mutates no fields beyond `status`; its purpose is to enable risk assessment.

Creating a **risk assessment** aggregates the case's exposure scores into two figures. The **MAX** variant, `aggregate_score_max`, is the maximum `toxicity_score` across all of the case's exposures, and its band — using the same thresholds as an exposure's severity band — becomes the assessment's `risk_tier`. The **ADDITIVE** variant, `aggregate_score_additive`, is a co-ingestant-weighted sum. For each exposure, an interaction weight is chosen from its own toxicity band — `MINIMAL` weights 0.5, `MODERATE` weights 1.0, `SEVERE` weights 1.25, and `CRITICAL` weights 1.5 — and the exposure's contribution is its `toxicity_score` multiplied by that weight, rounded half-up to 2 decimal places. These per-exposure contributions are rounded first and only then summed; the pinned order matters. A co-ingestant multiplier of 1.15 applies when at least two exposures have a `toxicity_score` of 0.25 or greater, and is 1.00 otherwise. The additive aggregate is the sum of the rounded contributions multiplied by that multiplier, the product rounded half-up to 2 decimal places. Every exposure of the case participates in both aggregates, regardless of its state. The MAX variant drives tier, disposition, and protocol selection; the ADDITIVE variant later drives the NPDS medical outcome.

With the tier known, the system selects a `protocol_id` by protocol selection: among all protocols whose `risk_tier` equals the assessment's tier, the earliest-created one (by `created_at` ascending) is chosen; if none matches, `protocol_id` is null. A new assessment starts in `COMPLETED` status and immediately supersedes any prior active assessment on the case, moving that prior assessment to `SUPERSEDED`. As described in §2.7, the create carries `expected_case_version`, is rejected with `ERR_STALE_CASE_VERSION` on a version mismatch, and on success increments the case's `version` by one. Creating an assessment is permitted only while the case is `TRIAGED` or `RETRIAGE`; from any other status the request is rejected with `ERR_INVALID_STATE` (HTTP 409). When more than one of these gates would fail, they are evaluated in the order case state (`ERR_INVALID_STATE`), then version staleness (`ERR_STALE_CASE_VERSION`), then presence of at least one exposure (`ERR_NO_EXPOSURES`). Assessments may be listed and filtered by `case_id` or `protocol_id`.

Finalizing an assessment advances it from `COMPLETED` to `FINALIZED` and refreshes the case's `risk_tier` mirror. Its checks are evaluated in a fixed order: assessment state first, then the toxicologist-authority gate, then protocol availability. Finalization is permitted only when the assessment is in `COMPLETED`; otherwise `ERR_INVALID_STATE` applies. Next, if the selected protocol's `requires_toxicologist` is true (the `SEVERE` and `CRITICAL` tiers), the acting role must be `Toxicologist`; a non-toxicologist attempt is rejected with `ERR_TOXICOLOGIST_REQUIRED` (HTTP 403), while the `MINIMAL` and `MODERATE` tiers admit either a `Specialist` or a `Toxicologist`. Finally, if `protocol_id` is still null at finalize because no protocol matched the tier, finalization is refused with `ERR_NO_PROTOCOL` (HTTP 409). A newer assessment created for the same case, or the case entering `RETRIAGE`, moves an earlier `COMPLETED` assessment to `SUPERSEDED`; and when a `FINALIZED` assessment's case enters `RETRIAGE`, that assessment moves to `SUPERSEDED` and the case's `risk_tier` mirror is cleared until re-assessment.

### 3.5. Disposition and the Home-Management Safety Gate

A **disposition** records the care-setting decision and must reference a `risk_assessment_id` that belongs to the same case and is `FINALIZED`; a `risk_assessment_id` that resolves to no assessment, or to one owned by a different case, is treated as an unresolved reference and fails with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Its `disposition_type` is either `HOME_MANAGEMENT` or `ED_REFERRAL`. Two business rules govern a disposition, and they are evaluated in a fixed order: the home-management safety gate is checked before the facility-pairing rule, so that when both would fail on one request the safety failure is the one reported. The safety gate allows a home-management decision only when the referenced assessment's `risk_tier` is `MINIMAL` or `MODERATE`; a home-management disposition on a `SEVERE` or `CRITICAL` case is rejected with `ERR_UNSAFE_DISPOSITION` (HTTP 422). The facility-pairing rule then requires that `ED_REFERRAL` supply a `facility_id` naming the referral target while `HOME_MANAGEMENT` leave `facility_id` null; violating this pairing is rejected with `ERR_DISPOSITION_FACILITY_MISMATCH` (HTTP 422). Each new disposition is created with status `ACTIVE`, superseding any prior active disposition.

A home-management disposition drives the case from `TRIAGED` to `MONITORING` (or from `RETRIAGE` back to `MONITORING` when a fresh `FINALIZED` assessment of tier `MINIMAL` or `MODERATE` exists). It also runs the follow-up schedule: it creates exactly `followup_count` follow-up calls drawn from the selected protocol, and sets the case's `pending_followup_count` to the number of calls scheduled. Each generated call is placed relative to the current logical clock: for the call at ordinal position i, counting from 0, its `scheduled_start` is the current clock plus (i + 1) times the protocol's `followup_interval_hours`, and its `scheduled_end` is 30 minutes after that start. Each generated call is assigned to the case's `intake_specialist_id`, is given the matching `sequence_index`, and starts in `SCHEDULED`.

An ED-referral disposition instead drives the case from `TRIAGED` to `REFERRED` (or from `RETRIAGE` to `REFERRED` when a fresh `FINALIZED` assessment exists), and the case then awaits a facility consult. Both transitions require the referenced assessment to be `FINALIZED`; the referral transition additionally requires that `facility_id` name a real facility. Dispositions may be listed and filtered by `case_id`, `risk_assessment_id`, or `facility_id`.

### 3.6. Follow-Up Calls and the Monitoring Lifecycle

Beyond the calls generated automatically, a `Specialist` may schedule a **follow-up call** on a case by supplying the `assigned_specialist_id` responsible for placing it, a zero-based `sequence_index`, a `scheduled_start`, and a `scheduled_end`. Three checks guard scheduling, and they are evaluated in a fixed order — case-overlap first, then specialist double-booking, and finally window well-formedness — so that when more than one would fail the earlier check in this order is the one reported. First, the new call must not overlap, on a half-open basis, any existing `SCHEDULED` or `ATTEMPTED` call of the same case: two windows conflict when they share any instant in their half-open ranges, but adjacency where one window's end equals another's start is allowed; an overlap is rejected with `ERR_FOLLOWUP_OVERLAP` (HTTP 409). Second, the assigned specialist must not be double-booked across all cases: treating the new call's window as a closed interval, the gap between it and every existing `SCHEDULED` or `ATTEMPTED` call of the same specialist must be at least 15 minutes — a gap of exactly 15 minutes is allowed, while any smaller gap, including touching intervals, is rejected with `ERR_SPECIALIST_DOUBLE_BOOKED` (HTTP 409). Third, the window must be well formed: `scheduled_end` must be strictly greater than `scheduled_start`, or the request is rejected with `ERR_INVALID_WINDOW` (HTTP 422). A newly scheduled call starts in `SCHEDULED` and increments the case's `pending_followup_count`. Follow-up calls may be listed and filtered by `case_id` or `assigned_specialist_id`.

Placing a call moves it from `SCHEDULED` to `ATTEMPTED` and increments its `attempt_count` by one; it is permitted only while the call is `SCHEDULED` and the owning case is not `CLOSED`. Completing a call resolves the attempt against an `outcome` value the caller supplies, which may be `RESOLVED`, `WORSENED`, or `NO_ANSWER`. When the outcome is `NO_ANSWER` and the call's `attempt_count` is below 3, the call reverts from `ATTEMPTED` back to `SCHEDULED`, and its window is rescheduled for a retry so that `scheduled_start` is exactly 6 hours after the current logical clock and `scheduled_end` sits one original window-duration (the call's prior `scheduled_end` minus `scheduled_start` span) after that new start. When the outcome is `RESOLVED` or `WORSENED`, or when it is `NO_ANSWER` with an `attempt_count` of 3 or more, the call moves from `ATTEMPTED` to `COMPLETED`. On completion the call's `outcome` is stored — recorded as `LOST_TO_FOLLOWUP` in the `NO_ANSWER`-with-three-or-more-attempts case — and the case's `pending_followup_count` is decremented.

Completion also drives the case. If the outcome is `RESOLVED` and every follow-up call of the case is now terminal (each `COMPLETED` or `CANCELLED`) with none carrying a `WORSENED` outcome, the case bubbles from `MONITORING` up to `RESOLVED`: its `resolved_at` is stamped from the logical clock, and if the case's active assessment is still `COMPLETED` it is finalized to `FINALIZED` as part of that cascade. If the outcome is `WORSENED`, the case is driven to `RETRIAGE`, superseding its active assessment and disposition so it can be re-assessed.

### 3.7. Facility Consults and the Dose-Confirmation Cascade

For a referred case, a `Toxicologist` opens a **facility consult** by naming the `case_id`, the consulting `facility_id`, and the `consult_duration_minutes` (greater than zero) to be billed. Opening a consult does not gate on the case's status: no case-state error is raised even when the referenced case is not in `REFERRED`. The facility must currently be accepting: a consult against a facility whose `status` is not `ACCEPTING` is rejected with `ERR_FACILITY_NOT_ACCEPTING` (HTTP 409), and a consult opened when the facility's `active_consult_count` already equals its `consult_capacity` is rejected with `ERR_FACILITY_AT_CAPACITY` (HTTP 409). A new consult starts in `ACTIVE`, increments the facility's `active_consult_count`, and stamps `requesting_specialist_id` from `X-User-ID`. Consults may be listed and filtered by `case_id`, `facility_id`, or `requesting_specialist_id`. A toxicologist may also withdraw an `ACTIVE` consult, moving it to `CANCELLED` and decrementing the facility's `active_consult_count`.

Closing a consult is the system's most consequential cascade. The toxicologist supplies a `confirmed_dose_mg`, which is required to close; without it the close is refused. On close, the consult computes its net `billing_units` and moves from `ACTIVE` to `CLOSED`, and the facility's `active_consult_count` is decremented by one. Billing is computed in a pinned order. First, the specialist units are the per-tier rate for the case's active risk tier — 1 unit for `MINIMAL`, 2 for `MODERATE`, 3 for `SEVERE`, 4 for `CRITICAL` — multiplied by `consult_duration_minutes`, divided by 60, and rounded half-up to 2 decimal places. Gross units are a base of 2 units plus those specialist units, rounded half-up to 2 decimal places. A volume discount is then keyed on those gross (pre-discount) units: no discount when gross units are below 5, a 10 percent discount when they are at least 5 but below 10, and a 20 percent discount when they are 10 or more. The net `billing_units` is the gross units multiplied by one minus the discount fraction, rounded half-up to 2 decimal places.

Closing then re-scores the case against the confirmed dose in three cascade hops. First, every exposure on the case has its `confirmed_dose_mg` set from the consult's confirmed dose, and its `toxicity_score` (and `severity_band`) is recomputed under the CONFIRMED variant, which typically diverges from the ESTIMATED score. Second, the case's active risk assessment recomputes both its aggregate scores and its `risk_tier`. Third, if that recomputed `risk_tier` escalates to `CRITICAL`, the case is driven from `MONITORING` to `REFERRED`: its active home-management disposition moves to `SUPERSEDED`, and all of its `SCHEDULED` or `ATTEMPTED` follow-up calls are cancelled, each decrementing `pending_followup_count`. Separately, a case awaits closure of its consult to settle: a referred case whose consult reaches `CLOSED` with no home follow-ups still scheduled bubbles from `REFERRED` to `RESOLVED`, stamping `resolved_at`.

Case closure ends the lifecycle. A `Specialist` may close a case that is `RESOLVED`, moving it to `CLOSED`; a `Toxicologist` may close a `REFERRED` case to `CLOSED` once its facility consult is `CLOSED` or `CANCELLED`. A closed case is terminal and admits no further transitions; a follow-up call still `SCHEDULED` when its case is closed is cancelled as part of that closure, decrementing `pending_followup_count`.

### 3.8. NPDS Surveillance Reporting

A `SurveillanceOfficer` submits an **NPDS report** for a case, naming the `case_id` and the `primary_substance_id` credited in surveillance counters. The case must have an active, non-superseded risk assessment; a submission for a case without one is rejected with `ERR_NO_ACTIVE_ASSESSMENT` (HTTP 409). On submission, the report derives its `medical_outcome` from the active assessment's `aggregate_score_additive`: the outcome is `MINOR` when the additive score is below 0.5, `MODERATE` when it is at least 0.5 but below 1.5, and `MAJOR` when it is 1.5 or greater. The report starts in `SUBMITTED` (its `report_status`), stamps `reported_at` from the logical clock, and increments the credited substance's `aggregate_case_count` by one. Reports may be listed and filtered by `case_id` or `primary_substance_id`.

A `SurveillanceOfficer` (or a `Toxicologist`) may retract a submitted report, moving its `report_status` from `SUBMITTED` to `RETRACTED` and decrementing the credited substance's `aggregate_case_count` by one as a compensating adjustment. Retraction is permitted only while the report is `SUBMITTED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource, and read operations, return `200 OK`. The logical-clock control endpoint returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/substances` | Create a substance reference row | SystemAdmin |
| GET | `/substances/{id}` | Fetch a substance including its surveillance counter | SystemAdmin, Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/healthcare-facilities` | Create a healthcare facility | SystemAdmin |
| GET | `/healthcare-facilities/{id}` | Fetch a facility including its active consult count | SystemAdmin, Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/protocols` | Create a management protocol for a risk tier | SystemAdmin |
| POST | `/specialists` | Create a poison-information specialist or toxicologist | SystemAdmin |
| POST | `/exposure-cases` | Open a new exposure case (call intake) | Specialist, Toxicologist |
| GET | `/exposure-cases/{id}` | Fetch a case with computed status, tier, and pending follow-ups | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/exposure-cases` | List cases (filter by status, intake specialist) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/exposure-cases/{id}/triage` | Advance a case from intake to triaged | Specialist, Toxicologist |
| POST | `/exposure-cases/{id}/close` | Close a resolved case, or a referred case for a Toxicologist | Specialist, Toxicologist |
| POST | `/exposure-cases/{id}/exposures` | Record a substance exposure on the case | Specialist, Toxicologist |
| GET | `/exposures/{id}` | Fetch a single exposure with score and band | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/exposures` | List exposures (filter by case or substance) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/exposure-cases/{id}/risk-assessments` | Create a risk assessment (create-with-supersede, OCC on case version) | Specialist, Toxicologist |
| GET | `/risk-assessments/{id}` | Fetch a risk assessment | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/risk-assessments` | List risk assessments (filter by case or protocol) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/risk-assessments/{id}/finalize` | Finalize a risk assessment | Specialist, Toxicologist |
| POST | `/exposure-cases/{id}/dispositions` | Record a home-management or ED-referral disposition | Specialist, Toxicologist |
| GET | `/dispositions/{id}` | Fetch a disposition | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/dispositions` | List dispositions (filter by case, assessment, or facility) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/exposure-cases/{id}/follow-up-calls` | Schedule a follow-up call on the case | Specialist, Toxicologist |
| GET | `/follow-up-calls/{id}` | Fetch a follow-up call | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/follow-up-calls` | List follow-up calls (filter by case or assigned specialist) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/follow-up-calls/{id}/attempt` | Record a call attempt | Specialist, Toxicologist |
| POST | `/follow-up-calls/{id}/complete` | Complete a call with an outcome | Specialist, Toxicologist |
| POST | `/facility-consults` | Open a healthcare-facility consult for a referred case | Toxicologist |
| GET | `/facility-consults/{id}` | Fetch a facility consult | Specialist, Toxicologist, SurveillanceOfficer |
| GET | `/facility-consults` | List facility consults (filter by case, facility, or requesting specialist) | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/facility-consults/{id}/close` | Close a consult, confirm the dose, and cascade re-scoring | Toxicologist |
| POST | `/npds-reports` | Submit an NPDS surveillance report for a case | SurveillanceOfficer |
| GET | `/npds-reports/{id}` | Fetch an NPDS report | SurveillanceOfficer, Toxicologist |
| GET | `/npds-reports` | List NPDS reports (filter by case or primary substance) | SurveillanceOfficer, Toxicologist |
| POST | `/npds-reports/{id}/retract` | Retract a submitted NPDS report | SurveillanceOfficer, Toxicologist |
| POST | `/exposure-cases/{id}/notes` | Append a documentation note to a case | Specialist, Toxicologist |
| GET | `/exposure-cases/{id}/notes` | List a case's documentation notes | Specialist, Toxicologist, SurveillanceOfficer |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_EXPOSURES` | 422 |
| `ERR_UNSAFE_DISPOSITION` | 422 |
| `ERR_TOXICOLOGIST_REQUIRED` | 403 |
| `ERR_DISPOSITION_FACILITY_MISMATCH` | 422 |
| `ERR_FACILITY_NOT_ACCEPTING` | 409 |
| `ERR_FACILITY_AT_CAPACITY` | 409 |
| `ERR_FOLLOWUP_OVERLAP` | 409 |
| `ERR_SPECIALIST_DOUBLE_BOOKED` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_STALE_CASE_VERSION` | 412 |
| `ERR_NO_ACTIVE_ASSESSMENT` | 409 |
| `ERR_NO_PROTOCOL` | 409 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INTERPRETER_LANGUAGE_REQUIRED` | 422 |
| `ERR_VALIDATION` | 422 |
</content>
</invoke>

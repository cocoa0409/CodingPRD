# GP EHR Visit API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the General Practice Electronic Health Record and Visit Management API. The platform is built to support a multidisciplinary primary-care clinic where receptionists, nurses, providers, pharmacists, billing staff, and administrators each perform tightly scoped clinical and administrative work against the same shared longitudinal patient record. The system spans the full ambulatory care lifecycle: enrolling patients, binding each patient to a single primary care provider, scheduling and conducting consultations, physicals, and vaccinations, capturing vital signs, posting CPT-coded billing lines, authoring and electronically transmitting prescriptions (including DEA-scheduled controlled substances under EPCS rules), issuing referrals to specialists, and exchanging messages through a patient portal.

Because the artifacts produced here — prescription signatures, audit log entries, HEDIS measure snapshots — are used downstream for regulatory filings, fiscal reconciliation, and clinical quality reporting, the system enforces strong segregation-of-duties controls, deterministic two-variant pricing for billed services, and immutable point-in-time HEDIS measure freezes. Many rules cascade across entities: completing an encounter recomputes per-line allowed amounts and refreshes HEDIS measurements; cancelling a `CHECKED_IN` encounter cascades to draft prescriptions; escalating a portal message auto-schedules a follow-up consultation. The contract that follows is designed so that every such side effect is observable to the test harness and reconstructable by a downstream auditor.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the calling principal, and `X-User-Role` declaring the calling role. Requests missing or malformed in either header are rejected with `ERR_AUTH_REQUIRED`. Requests carrying valid headers but invoking an operation outside the role's permitted set are rejected with `ERR_FORBIDDEN`.

The system recognizes eight roles, each spelled exactly as follows:

- `PatientPortalUser` — a patient acting through the portal. When `X-User-Role` is `PatientPortalUser`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a patient compare the resource's `patient_id` (or, for the patient record itself, its `id`) to `X-User-ID`. A `PatientPortalUser` may only read patient-scoped resources whose owning `Patient.id` equals their `X-User-ID`.
- `Provider` — a licensed clinician. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on resources that reference a provider (for instance, the `provider_id` on an `Encounter`, `Prescription`, or `Referral`, or the `referring_provider_id` / `referred_to_provider_id` on a `Referral`) compare the relevant foreign key to `X-User-ID`.
- `Nurse` — performs check-in, captures vital signs, triages and escalates portal messages. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it in audit logs but does not compare it to any entity's `id`.
- `Receptionist` — handles front-desk scheduling and intake. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `BillingClerk` — maintains CPT line items. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Pharmacist` — dispenses prescriptions. `X-User-ID` is an opaque operator identifier not tied to any persisted entity; segregation-of-duties checks compare it to the `provider_id` recorded on the prescription being dispensed.
- `ClinicAdmin` — platform administrator: onboards providers and CPT codes, runs HEDIS recompute, unbinds PCPs, reads the audit log. `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `TestHarness` — a pseudo-role used only by the automated test harness to advance the logical clock and run sweeps. `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and this role is never used by production clients.

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

List endpoints accept two query parameters. `limit` controls the maximum number of items returned: it defaults to 10, has a minimum of 1, and a maximum of 100. `offset` is the number of items skipped before the page begins; it defaults to 0. Unless an endpoint explicitly states otherwise, list results are sorted by `created_at` in ascending order. The `meta` object of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — `Patient`, `Provider`, `Encounter`, `Prescription`, `Referral`, and `PortalMessage` — carry a common set of system-managed fields:

- `id` (string) — a server-minted unique identifier formatted as a UUID. Identifiers carry no type prefix.
- `created_at` (string) — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first persisted.
- `updated_at` (string) — an ISO 8601 UTC timestamp updated on every successful mutation of the resource.
- `version` (integer) — increments by exactly one on every successful mutation and is used for optimistic concurrency control.

Three entities deliberately do not carry the full common-field set: `CptLineItem`, `CptFeeCatalog`, and `HedisMeasurement` each carry only an `id` (the `CptFeeCatalog` instead uses `cpt_code` as its primary key in place of `id`) and a `created_at` (or, for `HedisMeasurement`, the equivalent `computed_at` snapshot timestamp). These three entities do **not** carry `updated_at` and do **not** carry `version`; supplying or expecting a version on them is a contract error. `AuditLog` likewise carries no `updated_at` or `version`, only the timestamps and identifying fields described in §3.

### 2.5. Optimistic Concurrency Control

Every PATCH endpoint and every action endpoint on a versioned resource accepts an optional `version` field in the request body. When supplied, the server compares it against the persisted `version` on the target resource: if the two do not match, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted, the server proceeds without an OCC check. The OCC check is evaluated only after authentication, authorization, path existence, and reference resolution succeed.

### 2.6. Nested Resource Retrieval

When an endpoint path contains multiple resource identifiers (for example, a route that names both a patient and an encounter), the system resolves the path segments strictly left-to-right and returns `ERR_NOT_FOUND` against the first segment whose target does not exist. Body foreign-key references — `patient_id`, `provider_id`, `encounter_id`, the `cpt_code` referenced by a billing line — are resolved separately, after the path is fully valid; a missing body reference yields `ERR_REFERENCE_NOT_FOUND`.

### 2.7. Validation Ordering

When multiple validation rules apply to the same request, they execute in a fixed priority order so that the rejection a client receives is deterministic. The order is:

1. Authentication header presence and well-formedness (`ERR_AUTH_REQUIRED`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN`).
3. Existence of path-parameter resources (`ERR_NOT_FOUND`).
4. Existence of body foreign-key references (`ERR_REFERENCE_NOT_FOUND`).
5. State eligibility for the requested transition (the entity-specific state error such as `ERR_INVALID_ENCOUNTER_STATE`, `ERR_INVALID_PRESCRIPTION_STATE`, or `ERR_REFERRAL_NOT_PENDING`).
6. Business-safety, business-referential, business-temporal, business-constraint, and business-fiscal rules, evaluated in the order in which they are described in §3. Optimistic concurrency (`ERR_VERSION_CONFLICT`) sits at the very tail of business validation, after every other business check.

A higher-priority rule that fires masks any lower-priority failure on the same request. Specifically: a missing or unauthorized header masks every business error; a missing path resource masks every state and business error; a body-reference miss masks every state and business error; and a state violation masks every business and OCC error.

### 2.8. Monetary Values and Precision

Every monetary amount on the system is denominated in integer cents. Catalog prices (`list_price_cents`, `allowed_price_cents`) are supplied as non-negative integers and stored as such. The provisional `list_charge_cents` snapshotted onto a `CptLineItem` at line creation, and the `allowed_amount_cents` recomputed at encounter completion, are likewise integer cents. Wherever the allowed-amount calculation performs a multiplication that would yield a fractional cent, the result is rounded **half up** to the nearest whole cent. Rounding happens at the two pinned steps named in §3.3 — once per line after the modifier multiplier is applied, and once per line after the tier factor is apportioned — never on intermediate sums.

### 2.9. Time, Clock, and Sweep

All datetime fields are recorded as ISO 8601 UTC timestamps with three fractional digits of precision. The expression "now" in any rule below refers to the server's monotonic logical clock. Two test-only operations exist to drive deterministic time: an admin-only clock-advance capability advances the server clock by a supplied number of `seconds` or directly to a supplied absolute ISO instant via a `to` parameter, and a sweep capability runs every time-gated state transition (encounters becoming `NO_SHOW`, prescriptions becoming `EXPIRED`, referrals becoming `EXPIRED`). Both are reserved to the `TestHarness` role and are exempt from the authentication header check; production clients never invoke them.

### 2.10. Audit Logging

Several state-changing actions write a row to the immutable `AuditLog`. Each row records `actor_role` (the caller's `X-User-Role`), `actor_id` (the caller's `X-User-ID`), an `action` string such as `patient.view`, `prescription.sign`, or `referral.accept`, the `target_entity` type, the `target_id` of the affected resource, and an `occurred_at` server-clock timestamp. For controlled-substance prescription signing only, an additional `epcs_signature_hash` is written — a SHA-256 digest computed over the concatenation `provider_id|prescription_id|otp|signed_at_iso`. For every other audit row, `epcs_signature_hash` is null.

### 2.11. Cascade Discipline and Versioning on Mutation

Every server-initiated state change or derived-field write counts as a mutation: it refreshes `updated_at` and increments `version` on the affected resource (except on those resources that carry no `version`; see §2.4). When a single client request causes mutations on more than one resource — encounter completion writing `allowed_amount_cents` and `is_preventive` onto each `CptLineItem` and refreshing the `HedisMeasurement` rows, a `CHECKED_IN` cancellation cascading draft prescriptions to `CANCELLED`, a portal-message escalation auto-creating a follow-up encounter — every affected resource has its `updated_at` refreshed and (where applicable) its `version` incremented. A client holding a stale `version` on any of those resources will see `ERR_VERSION_CONFLICT` on its next mutation attempt against that resource.

### 2.12. Segregation of Duties

A single individual may not occupy two opposing roles on the same prescription. In particular, the `Provider` who signed a prescription must not also dispense it. This is enforced at dispense time by comparing the dispenser's `X-User-ID` to the prescription's recorded `provider_id`; a match rejects the request with `ERR_SEGREGATION_OF_DUTIES`. Portal access is similarly compartmentalized: only the patient themselves, acting as `PatientPortalUser` with `X-User-ID` equal to the `Patient.id` and with `portal_enabled` true on that patient, may exercise portal read operations on patient-scoped resources; any other combination is rejected with `ERR_PORTAL_DISABLED`.

## 3. Business Logic & Workflows

### 3.1. Patient Onboarding, PCP Binding, and Panel Accounting

A new patient is created by a `Receptionist` or `ClinicAdmin`. The intake payload supplies the patient's clinic-unique Medical Record Number `mrn` (which must match the pattern of the three letters `MRN` followed by exactly eight digits), legal `first_name` and `last_name`, an ISO-date `date_of_birth` (in YYYY-MM-DD form), and the `sex_at_birth` chosen from `MALE`, `FEMALE`, or `UNKNOWN`. Three optional fields may also be supplied at create: `portal_enabled` (a boolean defaulting to false), `smoking_status` (one of `NEVER`, `FORMER`, `CURRENT`, or `UNKNOWN`, defaulting to `UNKNOWN`), and `chronic_conditions` (an array of ICD-10 code strings such as `E11.9` or `I10`, defaulting to the empty array). The server initializes the patient's `pcp_provider_id` to null, leaves `pcp_bound_at` null, and sets `status` to `ACTIVE`.

Two mutable patient fields beyond those three are updatable post-creation: `smoking_status`, `chronic_conditions`, and `portal_enabled` may be revised through the patient PATCH operation (which also accepts an optional `version` for OCC). The MRN, demographics, and `status` are not client-mutable through that operation.

A `Patient` may have at most one bound `Provider` at a time. Binding by a `Receptionist` or `ClinicAdmin` supplies a `provider_id` and writes it to the patient's `pcp_provider_id`, stamping `pcp_bound_at` with the current server time. Three rules guard the bind:

- The target provider must have `role_type` of either `PCP_ONLY` or `BOTH`; a `SPECIALIST_ONLY` provider cannot serve as PCP and the request is rejected with `ERR_PROVIDER_NOT_PCP`.
- The patient must not already have a non-null `pcp_provider_id`. If they do, the request is rejected with `ERR_PCP_ALREADY_BOUND`. This is the serialization point for two providers attempting to claim the same patient simultaneously: at most one binding succeeds, and any later attempt — whether from a racing concurrent caller or from a fresh request after the binding was committed — sees `ERR_PCP_ALREADY_BOUND`.
- The provider must have headroom on their panel. Specifically, when the bind is attempted, the provider's current `panel_size` plus one must be less than or equal to their `panel_cap` (which defaults to 2000 when not supplied at provider creation). The panel-cap check is enforced only when the provider's `role_type` is `PCP_ONLY` or `BOTH`. A bind that would exceed the cap is rejected with `ERR_PANEL_FULL`.

The `panel_size` on a `Provider` is a derived count: the number of `Patient` rows whose `pcp_provider_id` equals that provider's `id` and whose `status` equals `ACTIVE`. It is recomputed by the server on every successful bind, on every unbind, and whenever a patient's `status` transitions between `ACTIVE` and `INACTIVE`. The recomputed `panel_size` is the literal count of qualifying patient rows — never an incremental delta — so the field always reconciles with the underlying patient population.

Unbinding is reserved to `ClinicAdmin`. It clears `pcp_provider_id` back to null on the patient and refreshes `panel_size` on the prior PCP using the same recount procedure.

### 3.2. Provider Onboarding and Specialty Roles

Providers are onboarded by a `ClinicAdmin`. The payload includes the 10-digit `npi` (matching exactly ten digits), the provider's `full_name`, the `role_type` (one of `PCP_ONLY`, `SPECIALIST_ONLY`, or `BOTH`), and an optional `specialty` descriptor. The `specialty` is required when `role_type` is `SPECIALIST_ONLY` or `BOTH`. Two prescriber-credential fields are optional: `dea_number`, which is required only to author controlled-substance prescriptions, and `epcs_enrolled`, a boolean defaulting to false that indicates whether the provider has completed EPCS identity proofing. An optional `panel_cap` (defaulting to 2000) sets the maximum panel headcount; `panel_size` is server-computed and starts at zero. The provider's `status` is initialized to `ACTIVE`.

Provider listing supports filtering by `role_type` and `specialty` in addition to the standard `limit` and `offset` paging controls.

### 3.3. Encounter Scheduling, Check-In, Completion, and Billing

A clinical visit is represented by an `Encounter`. Scheduling is performed by a `Receptionist` or `ClinicAdmin`, who specifies the `provider_id` who will conduct the visit, the `encounter_type` (one of `CONSULTATION`, `PHYSICAL`, or `VACCINATION`), the `scheduled_start` and `scheduled_end` as ISO 8601 instants, and optionally an initial `chief_complaint`. New encounters open in the `SCHEDULED` state with `actual_start`, `actual_end`, `vital_signs`, and `bmi` all null.

Three scheduling-time constraints fire before the row is persisted:

- The time window must satisfy `scheduled_end` strictly later than `scheduled_start`, and the duration from start to end must be no more than 120 minutes. A request violating either of those conditions is rejected with `ERR_INVALID_TIME_RANGE`.
- The new window must not temporally overlap any other non-terminal encounter belonging to the same `provider_id`. Overlap here is evaluated under closed-open interval semantics: an existing encounter whose `[scheduled_start, scheduled_end)` shares any positive-measure interval with the new request's `[scheduled_start, scheduled_end)` is a conflict, but back-to-back encounters that meet exactly at the boundary instant are permitted. A conflict yields `ERR_PROVIDER_TIME_CONFLICT`.
- The new window must not be within 15 minutes of any other non-terminal encounter for the same `patient_id`. Overlap here is evaluated under closed-closed interval semantics with a 15-minute buffer extended on each side: the new window is rejected if any other non-terminal encounter for the same patient ends within 15 minutes before the new `scheduled_start` or begins within 15 minutes after the new `scheduled_end`. A conflict yields `ERR_PATIENT_TIME_CONFLICT`. Back-to-back patient visits within 15 minutes are forbidden.

Non-terminal here means any encounter whose `status` is not in the terminal set `{COMPLETED, CANCELLED, NO_SHOW}`.

A `Nurse` or `Receptionist` may check in a scheduled encounter, advancing it from `SCHEDULED` to `CHECKED_IN`. Check-in succeeds only if the patient's `status` is `ACTIVE`, the provider's `status` is `ACTIVE`, and the current server time is at or after the scheduled start minus 30 minutes (so a patient may arrive up to half an hour early but no earlier). On success the server stamps `actual_start` with the current time. A check-in attempted from any other state yields `ERR_INVALID_ENCOUNTER_STATE`.

Once `CHECKED_IN`, a `Nurse` or `Provider` may PATCH the encounter to populate or revise `vital_signs` and `chief_complaint` (and may supply an optional `version` for OCC). The `vital_signs` object holds six fields: `bp_systolic`, `bp_diastolic`, `pulse`, `temp_c`, `weight_kg`, and `height_cm`. A `BillingClerk` or `Provider` may append CPT line items in this window; each line item references the encounter through `encounter_id`, supplies a `cpt_code` (a five-digit string matching the CPT-4 pattern), a `units` count between 1 and 50 inclusive, and optionally a `modifier` such as `25`, `59`, `TC`, or `26`. Adding a unit count outside the inclusive 1–50 range is rejected with `ERR_INVALID_BILLING_UNITS`; the same error guards CPT catalog creation when `allowed_price_cents` exceeds `list_price_cents`. On a successful line append, the server snapshots a provisional cash charge as `list_charge_cents` equal to the catalog's `list_price_cents` for that `cpt_code` multiplied by the supplied `units`; this provisional figure ignores the modifier and ignores the catalog's `is_telehealth_eligible` flag. `is_preventive` on the line is left at its default of false at append time, and `allowed_amount_cents` is left null. A line whose parent encounter is no longer `CHECKED_IN` cannot be appended, and a previously-added line may be removed via the delete-line operation only while the parent encounter is still `CHECKED_IN`.

A `Provider` completes the encounter, transitioning it from `CHECKED_IN` to `COMPLETED`. Completion enforces type-specific gating:

- For `encounter_type` of `PHYSICAL`, the `vital_signs` object must be fully populated — every one of `bp_systolic`, `bp_diastolic`, `pulse`, `temp_c`, `weight_kg`, and `height_cm` must be a present, non-null value.
- For `encounter_type` of `CONSULTATION`, the `chief_complaint` field must be non-empty.
- At least one `CptLineItem` must exist on the encounter; completing with zero billable lines yields `ERR_NO_BILLABLE_LINES`.

Attempting completion from any non-`CHECKED_IN` state yields `ERR_INVALID_ENCOUNTER_STATE`.

On a successful completion the server performs an ordered cascade. First, `actual_end` is stamped with the current server time. Second, if the encounter is a `PHYSICAL`, the body mass index `bmi` is computed as the patient's `weight_kg` divided by the square of the patient's `height_cm` after dividing height by 100, rounded half-up to one decimal place; the result is stored on the encounter. Third, for every `CptLineItem` on the encounter, the server snapshots `is_preventive` from the matching `CptFeeCatalog` row (so the catalog's preventive flag is captured at completion time and is no longer affected by later catalog edits). Fourth, for every `CptLineItem` on the encounter, the server recomputes `allowed_amount_cents` according to the tiered allowed-amount procedure described below. Fifth and finally, the server recomputes the patient's `HedisMeasurement` rows for the current calendar year, but only for the AWV and CBP measures.

The allowed-amount procedure runs across all line items on the encounter together (no filter on `is_preventive`):

1. For each line, compute a base allowed amount equal to the catalog's `allowed_price_cents` for that `cpt_code` multiplied by the line's `units`. The result is integer cents.
2. Apply the modifier multiplier to the per-line base. The multiplier is 1.25 when the line's `modifier` equals the string `25`, 1.00 when the modifier equals the string `59`, 0.65 when the modifier equals the string `TC`, 0.35 when the modifier equals the string `26`, and 1.00 in every other case (including when the modifier is null or absent). Multiply the per-line base by the multiplier and round the result half-up to the nearest whole cent. Each line stores this as its provisional per-line allowed amount before the tier factor is applied.
3. Sum the per-line amounts across every line on the encounter to obtain the encounter total. Select the tier factor from the encounter total using these brackets: when the encounter total is at most 50000 cents, the tier factor is 1.00; when the encounter total is greater than 50000 cents and at most 200000 cents, the tier factor is 0.95; when the encounter total is greater than 200000 cents, the tier factor is 0.90.
4. The adjusted encounter total is the encounter total multiplied by the tier factor, rounded half-up to the nearest whole cent. For each line, compute an apportioned share equal to that line's per-line amount multiplied by the tier factor, rounded half-up to the nearest whole cent. Sum the apportioned shares; the residual is the adjusted encounter total minus that sum (which may be positive, negative, or zero by a few cents because each apportion was rounded independently). Assign the entire residual — as a single cents value, not split — to the line with the largest per-line amount before apportion; if multiple lines tie for the largest pre-apportion amount, the residual goes to the line whose `id` is lexicographically smallest. The line's final `allowed_amount_cents` is the apportioned share plus the residual; for every other line the `allowed_amount_cents` equals the apportioned share alone. The residual rule guarantees that the sum of `allowed_amount_cents` across all lines on the encounter equals the adjusted encounter total exactly.

The allowed-amount calculation differs from the line-creation `list_charge_cents` calculation along three axes: it uses the catalog's `allowed_price_cents` rather than `list_price_cents`; it applies modifier multipliers and the encounter-level tier factor, neither of which the list-charge formula touches; and it rounds per line before summing the encounter total, where the list-charge formula has no rounding at all. For the same inputs the two figures can differ — both remain on the encounter as legitimate records.

A `Receptionist` or `Provider` may cancel an encounter, but the rules differ by the encounter's current state. A `SCHEDULED` encounter may be cancelled only while the current server time is strictly before the encounter's `scheduled_start`; once start has passed, the encounter is no longer eligible to cancel from the scheduled state. A `CHECKED_IN` encounter may be cancelled only if no `CptLineItem` exists on it; once any line has been appended, the encounter is locked against cancellation and must complete (or be remediated by deleting all line items first). Cancellation is forbidden after the encounter has already reached a terminal state. A successful cancellation sets the encounter's `status` to `CANCELLED` and cascades: every `DRAFT` `Prescription` whose `encounter_id` equals this encounter is transitioned to `CANCELLED`, refreshing `updated_at` and incrementing `version` on each affected prescription. Already-`SIGNED`, `TRANSMITTED`, `DISPENSED`, `CANCELLED`, or `EXPIRED` prescriptions are not affected. An ineligible cancel attempt yields `ERR_INVALID_ENCOUNTER_STATE`.

A `SCHEDULED` encounter is moved to `NO_SHOW` by the sweep when the current server time is strictly past its `scheduled_end`. The sweep additionally writes an `AuditLog` entry for the no-show transition.

### 3.4. Prescription Authoring, Signing, Transmission, Dispensing, and Cancellation

A `Provider` authors a new `Prescription` against a specific patient by supplying the authoring `provider_id`, the originating `encounter_id` (whose state must be `CHECKED_IN` or `COMPLETED` at the time the prescription is created or signed), the `drug_name`, an `rxnorm_code` identifier, an `is_controlled` boolean, the `dose_mg` strength, a `quantity` between 1 and 360 tablets, and a `refills_authorized` integer between 0 and 5. If `is_controlled` is true, the `dea_schedule` must be one of `II`, `III`, `IV`, or `V`; if `is_controlled` is false, `dea_schedule` must be null. Schedule II prescriptions carry an inviolable constraint: `refills_authorized` must equal exactly zero, both at creation and at sign time. A schedule II prescription submitted with any non-zero `refills_authorized` is rejected with `ERR_SCHEDULE_II_NO_REFILLS`. The new prescription opens in `DRAFT` with `signed_at`, `expires_at`, and `refills_remaining` all null, and `status` of `DRAFT`.

Signing transitions the prescription from `DRAFT` to `SIGNED`. The signing `Provider` must match the prescription's recorded `provider_id`. The associated encounter's `status` must be either `CHECKED_IN` or `COMPLETED`. For controlled prescriptions the signing path requires additional safeguards: the provider's `epcs_enrolled` flag must be true, the provider's `dea_number` must be non-null, and the request body must include `epcs_two_factor_token` as a six-digit OTP string. A controlled signing attempt missing any of those three conditions is rejected with `ERR_EPCS_NOT_ENROLLED`. For non-controlled prescriptions the `epcs_two_factor_token` is not required.

On a successful sign, the server stamps `signed_at` with the current time, sets `status` to `SIGNED`, seeds `refills_remaining` with the value of `refills_authorized`, and computes `expires_at` according to drug class: 365 days after `signed_at` for non-controlled prescriptions, 180 days after `signed_at` for schedule III, IV, or V controlled prescriptions, and 30 days after `signed_at` for schedule II controlled prescriptions (which also necessarily have zero refills). The `expires_at` is recorded to second precision. The server also writes an `AuditLog` entry for the signing; for controlled signings only, the audit row's `epcs_signature_hash` is populated with the SHA-256 hash of `provider_id|prescription_id|otp|signed_at_iso`.

Once signed, a `Provider` may transmit the prescription to the pharmacy, advancing it from `SIGNED` to `TRANSMITTED`. Transmission is rejected if the current server time is at or after the prescription's `expires_at`.

Dispensing is reserved to a `Pharmacist` and operates only on a `TRANSMITTED` prescription. Two preconditions guard each dispense: the current server time must be strictly before `expires_at`, and `refills_remaining` must be at least zero. The segregation-of-duties rule from §2.12 also fires here: if the dispenser's `X-User-ID` matches the prescription's recorded `provider_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. On a successful dispense, the server inspects `refills_remaining`: when it is zero before the dispense, the prescription transitions to the terminal state `DISPENSED`; when it is greater than zero, the server decrements `refills_remaining` by one and the prescription stays in `TRANSMITTED`, available for the next dispensing cycle. Two pharmacists racing to dispense the same prescription must serialize through the prescription's `version`: exactly one dispense commits and the other receives `ERR_VERSION_CONFLICT`.

A `Provider` may cancel a prescription from `DRAFT`, `SIGNED`, or `TRANSMITTED`, transitioning it to the terminal `CANCELLED` state with no further preconditions on the prescription itself. Two clients racing to sign and to cancel the same draft prescription serialize first-writer-wins on the prescription's `status`: exactly one operation commits and the other receives `ERR_INVALID_PRESCRIPTION_STATE`.

The sweep operation transitions a prescription to `EXPIRED` when the current server time is at or after the prescription's `expires_at` and the prescription is currently in either `SIGNED` or `TRANSMITTED`. `EXPIRED` is terminal.

### 3.5. Referrals: PCP-to-Specialist Routing and Lifecycle

A `Provider` issues a `Referral` from a patient's PCP to a specialist. The request supplies the `referring_provider_id`, the `referred_to_provider_id`, the originating `encounter_id` (which must be `COMPLETED`), a free-text clinical `reason`, and an optional `priority` chosen from `ROUTINE` (the default) or `URGENT`. Two integrity rules fire:

- The `referring_provider_id` must equal the patient's current `pcp_provider_id` at the moment of create. A mismatch is rejected with `ERR_REFERRER_NOT_PCP`.
- The `referred_to_provider_id` must not equal the `referring_provider_id`, and the referred-to provider's `role_type` must be `SPECIALIST_ONLY` or `BOTH`. A violation on either condition yields `ERR_INVALID_SPECIALIST`.

The new referral opens in `PENDING`, with `accepted_at` and `response_note` both null. The server computes `expires_at` at create: 72 hours after `created_at` when `priority` is `URGENT`, and 30 days after `created_at` when `priority` is `ROUTINE`.

The receiving specialist (a `Provider` whose `id` equals the referral's `referred_to_provider_id`) may either accept or reject. Both transitions require the current server time to be strictly before `expires_at`, the patient's `status` to be `ACTIVE` (for accept), and the acting provider's identity (and, for accept only, a `role_type` in `SPECIALIST_ONLY` or `BOTH`) to match. Acceptance moves the referral from `PENDING` to `ACCEPTED` and stamps `accepted_at` with the current server time; an optional `response_note` may be supplied. Rejection moves the referral from `PENDING` to the terminal `REJECTED` state. Two specialists racing to accept the same `PENDING` referral serialize first-writer-wins: exactly one accept commits and the loser receives `ERR_REFERRAL_NOT_PENDING`. The same error fires whenever an accept or reject is attempted against a referral that is no longer in `PENDING`.

After acceptance the specialist may either complete the referral or return it to the PCP. Returning to the PCP is a cyclic transition that moves the referral from `ACCEPTED` back to `PENDING` without changing `expires_at`, used when the specialist needs more input from the PCP before conducting their visit. The return is permitted only when no `COMPLETED` encounter exists with `provider_id` equal to the `referred_to_provider_id` and linked to this referral. Completion moves the referral from `ACCEPTED` to the terminal `COMPLETED` state and requires at least one `COMPLETED` encounter on this patient whose `provider_id` equals the `referred_to_provider_id` and whose timestamps fall on or after the referral's `accepted_at`. Both transitions accept an optional `response_note` and an optional `version`.

The sweep operation transitions any `PENDING` referral whose current server time is at or after its `expires_at` into the terminal `EXPIRED` state.

### 3.6. Patient Portal Messaging

A patient may exchange messages with their bound PCP through the portal. A `PatientPortalUser` (or, on the provider-reply side, a `Provider`) creates a new `PortalMessage` by supplying the `patient_id`, the `provider_id` (which must equal the patient's current `pcp_provider_id`), and a `body` string between 1 and 2000 characters inclusive. The server records the `sender_role` as either `PATIENT` or `PROVIDER` based on the caller's `X-User-Role`. New messages open with `status` of `UNREAD` and `triage_status` of `NEW`.

Portal-message lifecycle has **two independent dimensions** that evolve on the same row without affecting each other. The first dimension is the recipient-driven `status`: a `PatientPortalUser` or `Provider` advances `UNREAD` to `READ` by marking the message read, and then a `READ` message may be archived to terminal `ARCHIVED`. Marking read or archiving never touches the triage dimension.

The second dimension is the nurse-driven `triage_status`. A `Nurse` advances `NEW` to `TRIAGED` by triaging the message; this is permitted only when `sender_role` is `PATIENT` (provider-authored messages are not triaged). A `Nurse` then advances `TRIAGED` to `ESCALATED` by escalating; escalation is permitted only when `triage_status` is currently `TRIAGED`. Triaging and escalating never touch the `status` dimension. On escalation, the server performs a cascade: it auto-schedules an `Encounter` of `encounter_type` `CONSULTATION` within 24 hours, with `provider_id` set to the patient's bound `pcp_provider_id`. The new encounter opens in `SCHEDULED` like any other; its `updated_at` and `version` are stamped fresh, and the portal message's `updated_at` and `version` advance because the escalate is a mutation on it.

Portal read operations are guarded by the §2.12 portal-access rule: `Patient.portal_enabled` must be true, the caller's `X-User-Role` must be `PatientPortalUser`, and the caller's `X-User-ID` must equal the `Patient.id` of the resource being read. Any violation yields `ERR_PORTAL_DISABLED`.

### 3.7. CPT Fee Catalog Maintenance

The `CptFeeCatalog` is an administrative reference table keyed by `cpt_code` (a unique five-digit string used as the primary key in place of an `id`). A `ClinicAdmin` creates an entry by supplying the `cpt_code`, a human `description`, the non-negative `list_price_cents`, the non-negative `allowed_price_cents` (which must be less than or equal to `list_price_cents` — a violation yields `ERR_INVALID_BILLING_UNITS`), an optional `is_preventive` flag (defaulting to false), and an optional `is_telehealth_eligible` flag (defaulting to false). The `is_preventive` flag is the source of truth for the AWV preventive-care numerator: encounter completion snapshots it onto every `CptLineItem` so that subsequent catalog edits do not retroactively change historical HEDIS results.

### 3.8. HEDIS Quality Measurement

HEDIS measurement is a per-(patient, measure_id, measurement_year) computation that produces a `HedisMeasurement` row identifying whether the patient qualifies for the measure's denominator and, if so, whether they also satisfy the numerator. Four measure keys are supported: `AWV`, `CBP`, `TSC`, and `CCS`. A measurement row stores `patient_id`, `measure_id`, `measurement_year` (a four-digit integer such as 2026), the boolean `in_denominator`, the boolean `in_numerator`, and a `computed_at` snapshot timestamp. The triple of (`patient_id`, `measure_id`, `measurement_year`) is unique on the table.

Age at year-end is computed in integer years as the `measurement_year` minus the year of the patient's `date_of_birth`, minus an additional 1 only if the month-day pair of `date_of_birth` falls strictly later in the calendar than December 31 (which never happens, so in practice the age is `measurement_year` minus the birth year). The four measures evaluate as follows:

- **AWV (Adult Wellness Visit, age at least 18).** The denominator is met when the patient's age at year-end is at least 18 and the patient's `status` is `ACTIVE` on December 31 of the measurement year. The numerator is met when the denominator is met and at least one `COMPLETED` encounter exists in the measurement year that has at least one `CptLineItem` whose snapshotted `is_preventive` is true.
- **CBP (Controlling High Blood Pressure, age between 18 and 85 inclusive, with hypertension).** The denominator is met when the patient's age at year-end is at least 18 and at most 85, the string `I10` appears in the patient's `chronic_conditions` array, and at least one `COMPLETED` encounter exists for the patient in the measurement year. The numerator is met when the denominator is met and the patient's most recent `COMPLETED` encounter in the year has both `vital_signs.bp_systolic` strictly less than 140 and `vital_signs.bp_diastolic` strictly less than 90. "Most recent" is determined by `actual_end` in descending order, with ties broken by `Encounter.id` in ascending lexicographic order.
- **TSC (Tobacco Screening and Cessation, age at least 18).** The denominator is met when the patient's age at year-end is at least 18 and at least one `COMPLETED` encounter exists for the patient in the measurement year. The numerator is met when the denominator is met, the patient's `smoking_status` is in the set `{NEVER, FORMER, CURRENT}`, and additionally, if the smoking status is `CURRENT`, at least one `CONSULTATION` encounter exists in the measurement year carrying a `CptLineItem` with `cpt_code` equal to either `99406` or `99407`.
- **CCS (Cervical Cancer Screening, female, age between 21 and 64 inclusive).** The denominator is met when the patient's `sex_at_birth` is `FEMALE` and the age at year-end is at least 21 and at most 64. The numerator is met when the denominator is met and at least one `COMPLETED` encounter exists in the measurement year that carries a `CptLineItem` with `cpt_code` equal to either `88141` or `88142`.

The HEDIS evaluation has **two variants**, and they can disagree for the same patient and year:

- **Provisional, year-to-date.** Used when the HEDIS read endpoint is called with the `as_of` query parameter equal to `YTD`. Looks only at `COMPLETED` encounters whose `actual_end` is at or before the current server time. The denominator's status check uses the patient's `status` and `smoking_status` as they are right now rather than as they will be on December 31. The provisional variant computes in memory and writes no row to the table.
- **Final, year-end freeze.** Triggered by the HEDIS recompute action, which accepts a four-digit `year` and an optional `patient_ids` filter. Uses every `COMPLETED` encounter whose `actual_end` falls within January 1 through December 31 of the supplied `measurement_year`. The denominator status check uses the patient's `status` and `smoking_status` as of December 31. The result is persisted as an immutable `HedisMeasurement` snapshot — one row per (patient, `measure_id`, `year`).

The two variants can diverge when, for instance, the patient becomes `INACTIVE` in November (the provisional reading in October counts them in the denominator; the final freeze does not), or when their `smoking_status` changes late in the year (the TSC numerator can flip). Both readings are correct for their respective semantics.

Encounter completion triggers an in-flight HEDIS recompute as part of its cascade, but only for the AWV and CBP measures and only for the current calendar year. The TSC and CCS measures are evaluated only when the on-demand HEDIS read or the explicit recompute action runs.

### 3.9. Audit Reads and the Test-Driven Clock

A `ClinicAdmin` is the only role permitted to read audit logs. The audit listing accepts optional filters by `target_entity`, `target_id`, `actor_id`, and `action`, in addition to the standard `limit` and `offset` paging controls. Each row carries `actor_role`, `actor_id`, `action`, `target_entity`, `target_id`, `occurred_at`, and the optional `epcs_signature_hash` described in §2.10. Reading a `Patient` record (the `patient.view` action) writes an audit row; signing, transmitting, cancelling, dispensing, and the referral lifecycle actions write rows of analogous form. Sweep-driven state changes also produce audit entries.

The test-only clock-advance and sweep capabilities are reserved to the `TestHarness` role. Clock-advance accepts either a relative `seconds` integer or an absolute target `to` instant; whichever is supplied, downstream `now()` reads see the new value. The sweep capability returns counts of how many encounters became `NO_SHOW`, how many prescriptions became `EXPIRED`, and how many referrals became `EXPIRED` on that sweep call. Both are exempt from the authentication header check so that the harness can drive deterministic time without holding clinical credentials.

## 4. Endpoint Definitions

Operations that create a new standalone resource — a patient record, a provider, an encounter, a CPT catalog entry, a prescription, a referral, a portal message, or a CPT line item — return `201 Created`. Operations that modify an existing resource (state transitions, PATCH updates, binds, unbinds, recomputes) return `200 OK`. Deletion of a CPT line item returns `204 No Content`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/patients` | Create patient record | Receptionist, ClinicAdmin |
| GET    | `/patients/{id}` | Retrieve patient record | Receptionist, Nurse, Provider, ClinicAdmin, PatientPortalUser |
| PATCH  | `/patients/{id}` | Update mutable patient fields | Nurse, Provider, ClinicAdmin |
| GET    | `/patients` | List patients with filter/sort/paginate | Receptionist, Nurse, Provider, ClinicAdmin |
| POST   | `/patients/{id}/bind-pcp` | Bind patient to a primary care provider | Receptionist, ClinicAdmin |
| POST   | `/patients/{id}/unbind-pcp` | Remove PCP binding | ClinicAdmin |
| POST   | `/providers` | Create provider | ClinicAdmin |
| GET    | `/providers/{id}` | Retrieve provider | Receptionist, Nurse, Provider, ClinicAdmin |
| GET    | `/providers` | List providers | Receptionist, Nurse, Provider, ClinicAdmin |
| POST   | `/patients/{patient_id}/encounters` | Schedule encounter | Receptionist, ClinicAdmin |
| GET    | `/encounters/{id}` | Retrieve encounter | Receptionist, Nurse, Provider, ClinicAdmin, PatientPortalUser |
| PATCH  | `/encounters/{id}` | Update vital_signs / chief_complaint on a CHECKED_IN encounter | Nurse, Provider |
| POST   | `/encounters/{id}/check-in` | Transition SCHEDULED to CHECKED_IN | Nurse, Receptionist |
| POST   | `/encounters/{id}/complete` | Transition CHECKED_IN to COMPLETED; cascade billing and HEDIS | Provider |
| POST   | `/encounters/{id}/cancel` | Cancel SCHEDULED or eligible CHECKED_IN encounter | Receptionist, Provider |
| POST   | `/encounters/{id}/cpt-line-items` | Append CPT line item to a CHECKED_IN encounter | Provider, BillingClerk |
| DELETE | `/cpt-line-items/{id}` | Remove CPT line item (only while parent encounter is CHECKED_IN) | BillingClerk, Provider |
| POST   | `/cpt-codes` | Create CPT code entry in fee catalog | ClinicAdmin |
| GET    | `/cpt-codes/{cpt_code}` | Retrieve CPT entry | Receptionist, Nurse, Provider, ClinicAdmin, BillingClerk |
| POST   | `/patients/{patient_id}/prescriptions` | Create DRAFT prescription | Provider |
| GET    | `/prescriptions/{id}` | Retrieve prescription | Provider, Pharmacist, PatientPortalUser, ClinicAdmin |
| POST   | `/prescriptions/{id}/sign` | Sign prescription (EPCS 2FA required for controlled) | Provider |
| POST   | `/prescriptions/{id}/transmit` | Send prescription to pharmacy | Provider |
| POST   | `/prescriptions/{id}/dispense` | Pharmacist dispenses one fill | Pharmacist |
| POST   | `/prescriptions/{id}/cancel` | Cancel non-terminal prescription | Provider |
| POST   | `/patients/{patient_id}/referrals` | Create referral (PCP to specialist) | Provider |
| GET    | `/referrals/{id}` | Retrieve referral | Provider, ClinicAdmin, PatientPortalUser |
| POST   | `/referrals/{id}/accept` | Specialist accepts referral | Provider |
| POST   | `/referrals/{id}/reject` | Specialist rejects referral | Provider |
| POST   | `/referrals/{id}/return-to-pcp` | Cycle ACCEPTED back to PENDING | Provider |
| POST   | `/referrals/{id}/complete` | Mark referral COMPLETED after specialist encounter | Provider |
| POST   | `/portal/messages` | Patient or provider posts portal message | PatientPortalUser, Provider |
| GET    | `/portal/messages/{id}` | Retrieve portal message | PatientPortalUser, Provider, Nurse |
| POST   | `/portal-messages/{id}/mark-read` | Mark message READ (status dimension) | PatientPortalUser, Provider |
| POST   | `/portal-messages/{id}/archive` | Archive READ message (status dimension) | PatientPortalUser, Provider |
| POST   | `/portal-messages/{id}/triage` | Nurse marks NEW to TRIAGED (triage_status dimension) | Nurse |
| POST   | `/portal-messages/{id}/escalate` | Nurse escalates TRIAGED to ESCALATED; auto-schedules consultation | Nurse |
| GET    | `/hedis/measurements/{patient_id}/{year}` | Retrieve HEDIS measure status (provisional via `as_of=YTD`, else final) | Provider, ClinicAdmin |
| POST   | `/hedis/recompute` | Compute final HedisMeasurement snapshots for a given year | ClinicAdmin |
| GET    | `/audit-logs` | List audit log entries filtered by target/actor/action | ClinicAdmin |
| POST   | `/_clock/advance` | Test-only: advance server clock by `seconds` or to absolute `to` | TestHarness |
| POST   | `/_sweep/run` | Test-only: run time-gated sweeps for NO_SHOW and EXPIRED transitions | TestHarness |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_AUTH_REQUIRED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_INVALID_ENCOUNTER_STATE` | 409 Conflict |
| `ERR_INVALID_PRESCRIPTION_STATE` | 409 Conflict |
| `ERR_REFERRAL_NOT_PENDING` | 409 Conflict |
| `ERR_VERSION_CONFLICT` | 409 Conflict |
| `ERR_EPCS_NOT_ENROLLED` | 403 Forbidden |
| `ERR_SCHEDULE_II_NO_REFILLS` | 422 Unprocessable Entity |
| `ERR_PROVIDER_NOT_PCP` | 422 Unprocessable Entity |
| `ERR_PCP_ALREADY_BOUND` | 409 Conflict |
| `ERR_REFERRER_NOT_PCP` | 422 Unprocessable Entity |
| `ERR_INVALID_SPECIALIST` | 422 Unprocessable Entity |
| `ERR_INVALID_TIME_RANGE` | 422 Unprocessable Entity |
| `ERR_PROVIDER_TIME_CONFLICT` | 409 Conflict |
| `ERR_PATIENT_TIME_CONFLICT` | 409 Conflict |
| `ERR_PANEL_FULL` | 422 Unprocessable Entity |
| `ERR_NO_BILLABLE_LINES` | 422 Unprocessable Entity |
| `ERR_INVALID_BILLING_UNITS` | 422 Unprocessable Entity |
| `ERR_PORTAL_DISABLED` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |

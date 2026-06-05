# Immunization Information System API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a State Immunization Information System (IIS): the system of record a public-health registry uses to track childhood vaccination histories, evaluate each child against the recommended schedule and the CDC catch-up rules, and issue the school-enrollment proof that families present at registration. The registry sits at the intersection of three constituencies whose needs frequently pull in different directions — clinic records staff who enter doses and corrections, administering providers who submit batches and file adverse-event reports, and the state registrar who governs the vaccine catalogue, adjudicates submissions, runs schedule evaluations, and issues certificates.

The hard problems this API exists to solve are problems of *consistency under change*. A single dose recorded today can shift a child's compliance posture; a lot recall announced next week can retroactively invalidate doses already counted, cascading through schedule evaluations and revoking certificates that were valid at issuance; a confirmed serious adverse event can contraindicate an entire antigen family and pull a previously up-to-date child into non-compliance. Every dose is validity-checked against minimum-age and minimum-interval rules with the CDC four-day grace window, every lot's inventory is a conserved quantity that must never drift, and every certificate is issued against a frozen evaluation snapshot guarded by optimistic concurrency. The specification below describes the entities, lifecycles, calculations, and guardrails that keep this web of derived state correct as the underlying facts move beneath it.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which the user is acting. The system recognizes exactly three roles: `ImmunizationRegistrar`, `RecordsClerk`, and `Provider`. A request that omits either header, or that presents an `X-User-Role` value that is not one of these three, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is well-formed but not permitted to perform the requested operation under the access matrix in Section 4 is rejected with `ERR_FORBIDDEN` (HTTP 403). Authentication is checked before authorization, and both precede any other validation.

When `X-User-Role` is `ImmunizationRegistrar`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`. When `X-User-Role` is `RecordsClerk`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity; ownership checks on any resource that references a `Provider` compare the resource's provider foreign key to `X-User-ID` — in particular, a `Provider` may submit only a `ProviderReport` whose `provider_id` equals its own `X-User-ID`.

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

List endpoints accept two query parameters. `limit` caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items to skip from the front of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `total_count` reflects the full size of the collection before the limit/offset window is applied and `has_more` indicates whether further items remain beyond the current window.

### 2.4. Common Resource Properties and Versioning

Every entity in this system — `Patient`, `Provider`, `VaccineProduct`, `VaccineLot`, `Immunization`, `AllergyRecord`, `ProviderReport`, `AdverseEvent`, `ScheduleEvaluation`, `SchoolComplianceCertificate`, and `LotRecall` — carries the same four system-managed fields. The `id` is a server-minted UUID with no type prefix, used for identity only. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource, including mutations driven by cascaded side effects rather than a direct client request. The `version` field is an integer that starts at 1 and increments by exactly 1 on every mutation, including cascaded ones; it is the target of optimistic concurrency control for certificate issuance.

For `Immunization`, `created_at` doubles as the secondary chronological tie-break key for series ordering, with `administered_date` as the primary sort key. For `ScheduleEvaluation`, `created_at` is the tie-break key used to identify the latest evaluation for a patient.

### 2.5. Nested Resource Retrieval and Existence Checking

Several paths address a resource nested beneath a parent — a patient's immunizations, a lot's recalls, a recall's reversal. For any such path the system validates the referenced resources left-to-right in the order they appear, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. This existence sweep covers every path-referenced and body-referenced resource — patient, provider, lot, product, immunization, report, evaluation, recall, and adverse event — and runs after authentication and authorization but before any business rule is evaluated.

### 2.6. Schedule Posture and Derived-Field Reconciliation

Three derived fields are kept reconciled with the facts beneath them and must never be set directly by a client. A `Patient` carries `schedule_status`, a copy of the `overall_status` of that patient's most recent `ScheduleEvaluation`; a patient who has never been evaluated reads `UP_TO_DATE`. The same `Patient` carries `active_certificate_id`, a convenience pointer to the `id` of the single non-superseded, non-revoked `SchoolComplianceCertificate` for that patient, or `null` when none exists; this is a derived pointer, not a stored child foreign key, and the full set of a patient's certificates is discovered by listing them. A `VaccineLot` carries `administered_count`, the running count of that lot's doses, which is reconciled on every recording, invalidation, and revalidation as described in Section 2.8.

Whenever any of these derived fields changes, the owning resource is treated as mutated: its `updated_at` is refreshed and its `version` is incremented by 1. This applies equally when the change originates from a cascade rather than a direct write.

### 2.7. Dose Validity, Ages, and the Four-Day Grace Rule

Every recorded dose is assigned a `validity`, one of `VALID`, `INVALID_INTERVAL`, `INVALID_AGE`, or `INVALID_RECALL`, and a `dose_number`, its 1-based position within the patient's valid-dose ordering for the product's antigen. These two computed fields are produced by a single chronological replay, the dose-validity computation, run whenever a dose is recorded (directly or through report adjudication), corrected, invalidated by a recall, or revalidated by a recall reversal.

The replay is performed per patient and per antigen, grouping vaccine products by their `antigen` family. The patient's non-`DELETED` doses of that antigen are ordered by `administered_date` ascending, breaking ties by `created_at` ascending — never by `id`. The replay walks that order maintaining a running "last valid date" (initially none) and a running valid-dose index (initially zero). For each dose drawn from a lot of a product whose `grace_period_days` is the grace window, the patient's age in days is the exact calendar-day difference between the patient's `date_of_birth` and the dose's `administered_date`. The dose is classified in this order: if the dose's lot is in `RECALLED` status and the dose is not already `INVALIDATED`, its validity is `INVALID_RECALL` and it is not counted; otherwise, if the patient's age in days is strictly less than the product's `min_age_days` reduced by the grace window, its validity is `INVALID_AGE` and it is not counted; otherwise, if a prior valid date exists and the number of days from that prior valid date to this dose's `administered_date` is strictly less than the product's `min_interval_days` reduced by the grace window, its validity is `INVALID_INTERVAL` and it is not counted; otherwise the dose is `VALID`, the valid-dose index advances by one, this dose's `dose_number` is set to that new index, and the running last-valid-date becomes this dose's `administered_date`. A dose that is not `VALID` keeps whatever `dose_number` it previously held but is excluded from counting. All day arithmetic is exact integer calendar-day subtraction on UTC dates. The standard grace window is four days, applied identically to both the minimum-age and the minimum-interval thresholds.

The patient's age is always measured relative to the dose's administration date, but the system's notion of "today" — the current clock date used for the default evaluation date and for the rule that a `date_of_birth` may not be in the future — is the server clock, which an administrator may set for test-driving by supplying a `to_iso8601` instant.

### 2.8. Lot Inventory as a Conserved Quantity

A lot's `administered_count` is an invariant, not a free-running counter: for every `VaccineLot` it must at all times equal the number of that lot's `Immunization` rows whose `status` is `RECORDED` or `AMENDED`. The forward actions — recording a dose, accepting a line during adjudication, and revalidating a struck dose on recall reversal — each add 1. The compensating actions — invalidating a dose by recall, deleting a dose, and the inverse of a revalidation — each subtract 1, exactly undoing the forward action. The available capacity of a lot is its `doses_total` minus its `administered_count`, and this difference must never go below zero.

Capacity is enforced at recording time: a new dose against a lot is permitted only while `administered_count` is strictly less than `doses_total`. Recording the dose that brings the count up to exactly `doses_total` is allowed; the next dose, which would push the count past `doses_total`, is rejected with `ERR_LOT_DEPLETED` (HTTP 422). The registry does not use a separate quarantine state — capacity exhaustion is expressed purely through this count check while the lot remains `AVAILABLE`.

### 2.9. Precision and Rounding

All day-based quantities — ages, intervals, due-date offsets — are exact integer calendar-day arithmetic; there is no rounding in the day domain. Inventory and dose counts are exact integers. The single field expressed with fractional precision is the compliance percentage `completeness_pct`, which is computed to exactly 2 decimal places using the round-half-up method. The order of rounding for that percentage is pinned in Section 3.6 and must be followed exactly, because rounding per antigen first and averaging afterward yields different cents than averaging raw ratios and rounding once.

### 2.10. Optimistic Concurrency Control on Certificate Issuance

Issuing a school compliance certificate is the one operation in this system guarded by optimistic concurrency control, because issuance both reads and advances the `Patient` it targets. A certificate-issuance request must carry `expected_patient_version` as a non-optional field, and that value must equal the target patient's current `version`. If it does not match — for example because an earlier issuance has already superseded the patient's prior certificate and thereby incremented the patient's `version` while changing `active_certificate_id` — the request is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412), so that a client carrying a stale view of the patient cannot overwrite a certificate state it never observed. No other endpoint accepts or requires a version field; only certificate issuance performs this check.

## 3. Business Logic & Workflows

### 3.1. The Vaccine Catalogue: Products and Lots

Before any dose can be recorded, the registrar defines the vaccine catalogue. Defining a `VaccineProduct` (an action reserved to the `ImmunizationRegistrar`) requires a `product_code` such as DTAP, MMR, IPV, HEPB, or VAR, which is a stable, non-empty code that must be unique across all products; an `antigen` family such as DTAP, MMR, or POLIO, which is the bucket used for school-mandate accounting and which several products may share; a `doses_in_series`, the number of valid doses needed to complete the primary series, which must be at least 1; a `min_age_days`, the absolute minimum patient age in days at which dose one may validly be given, which must be at least 0; a `recommended_age_days`, the routine-schedule target age for dose one, which must be greater than or equal to `min_age_days`; and a `min_interval_days`, the minimum number of days that must elapse between two consecutive valid doses, which must be at least 0. The `grace_period_days` is optional and defaults to 4, and must be at least 0; it is the four-day window applied to both the age and interval thresholds. The product's `status` is optional and defaults to `ACTIVE`; only `ACTIVE` products may back new lots and recordings, and a product may instead be `RETIRED`. If `recommended_age_days` is supplied below `min_age_days`, or any analogous cross-field constraint is violated, the creation is rejected with `ERR_VALIDATION` (HTTP 422).

Registering a `VaccineLot` (also registrar-only) ties a physical lot to a product. The payload supplies the `product_id` of the backing product, a `lot_number` that is non-empty and unique within that product, a `received_date` marking the earliest valid administration date for doses drawn from the lot, an `expiration_date` marking the latest valid administration date, and a `doses_total`, the total doses originally in the lot, which must be at least 1. The `expiration_date` must be strictly after the `received_date`; a violation is rejected with `ERR_VALIDATION`. A lot is created with `administered_count` of 0 and `status` of `AVAILABLE`; its status later becomes `RECALLED` only through a recall, and returns to `AVAILABLE` only through a reversal. A duplicate `lot_number` within the same product, like a duplicate `product_code` or a duplicate provider `vfc_pin`, is rejected with `ERR_DUPLICATE` (HTTP 409).

### 3.2. Enrolling Providers and Recording Doses

A `Provider` is enrolled by the registrar with a clinic or practitioner `name`, a `vfc_pin` (the Vaccines-for-Children PIN, non-empty and unique across providers), and an `authorized_product_codes` list naming the `product_code` values the provider may administer; the list is optional and defaults to empty. The provider's `status` is optional and defaults to `ENROLLED`, the only other value being `SUSPENDED`. A duplicate `vfc_pin` is rejected with `ERR_DUPLICATE`.

A child is registered as a `Patient` by supplying a `full_name`, a `date_of_birth` as an ISO `YYYY-MM-DD` date that must be a calendar date on or before the current clock date and that is immutable thereafter, and a two-uppercase-letter `state_code` naming the state of residence. A newly created patient has `schedule_status` of `UP_TO_DATE` and `active_certificate_id` of `null`. A `date_of_birth` after the clock date, like any missing required field, bad type, or invalid enum value, is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Recording a directly administered dose creates an `Immunization` in `RECORDED` status. The recorder supplies the `patient_id` of the child, the `lot_id` of the lot the dose was drawn from, the `provider_id` of the administering provider, and the `administered_date` the dose was given; a directly recorded dose has a `report_id` of `null`. The dose's `dose_number` and `validity` are then computed by the dose-validity replay of Section 2.7, and the backing lot's `administered_count` is incremented by 1. Before the dose is accepted, the recording passes through the gauntlet of safety and inventory checks described in Section 3.3; only after those pass is the row created. Recording also offers a stricter interval guard than the replay's silent classification: when a dose is recorded as a strict, reject-on-violation dose, a dose whose gap from the prior valid same-antigen dose is less than `min_interval_days` reduced by the grace window is refused outright with `ERR_INTERVAL_TOO_SHORT` (HTTP 422) rather than being recorded and merely flagged `INVALID_INTERVAL`.

A dose may be corrected by a `RecordsClerk`, who supplies a new `administered_date`. A correction is permitted only when the dose's `status` is `RECORDED` (moving it to `AMENDED`) or already `AMENDED` (keeping it `AMENDED`); from any other status the correction is rejected with `ERR_INVALID_STATE` (HTTP 409). The corrected `administered_date` must keep the dose within its lot's window — not before `received_date` and not after `expiration_date` — or the correction is rejected with `ERR_LOT_EXPIRED` (HTTP 422). A successful correction recomputes this dose's `validity` and `dose_number` together with those of every same-antigen sibling of the patient, reconciles the `administered_count` of every affected lot, and increments the dose's `version` by 1. An `AMENDED` dose behaves identically to a `RECORDED` one for all counting purposes; the distinct status exists only to mark corrected rows for audit.

Retracting a dose is reserved to the registrar and sets the dose's `status` to `DELETED`. Retraction is permitted only when the dose is `RECORDED` or `AMENDED`; otherwise it is rejected with `ERR_INVALID_STATE`. A dose may not be retracted while any adverse event referencing it is in `REPORTED`, `UNDER_REVIEW`, or `CONFIRMED` status; such an attempt is rejected with `ERR_ADVERSE_EVENT_BLOCKS_DELETE` (HTTP 409). A successful retraction decrements the lot's `administered_count` by 1, recomputes `dose_number` and `validity` for the patient's same-antigen series, and increments the dose's `version` by 1.

### 3.3. Recording Guardrails and Their Evaluation Order

A recording — whether a direct dose or a single line within an adjudicated report — is subject to a fixed ordered cascade of checks, evaluated highest-priority first so that the most fundamental failure is the one reported. After authentication, authorization, and existence resolution have passed, and after the request body has been validated for required fields, correct types, and valid enum members (failures here being `ERR_INVALID_REQUEST`), the recording checks run in this order:

First, provider authorization: the administering provider's `authorized_product_codes` must contain the `product_code` of the lot's product, or the recording is rejected with `ERR_PRODUCT_NOT_AUTHORIZED` (HTTP 422). Next, the lot must not be recalled: a dose against a lot whose `status` is `RECALLED` is rejected with `ERR_LOT_RECALLED` (HTTP 409). Next, lot expiry: the `administered_date` must lie within the lot's window, not before `received_date` and not after `expiration_date`, or the dose is rejected with `ERR_LOT_EXPIRED`. Next, the safety check: the patient must have no `CONTRAINDICATED` allergy record for the product's antigen, or the dose is rejected with `ERR_CONTRAINDICATED` (HTTP 422). Next, for strict directly-recorded doses, the minimum-interval guard described above, rejecting with `ERR_INTERVAL_TOO_SHORT`. Finally, lot capacity: the lot must have remaining capacity per Section 2.8, or the dose is rejected with `ERR_LOT_DEPLETED`.

This same ordering — provider authorization, then recall, then expiry, then contraindication, then capacity — governs each line during report adjudication; the strict interval guard applies only to direct recordings. The general transition guard sits above all of these: any state-transition endpoint whose target resource is not in a state from which the requested transition is defined is rejected with `ERR_INVALID_STATE` before the per-line business checks run.

### 3.4. Contraindications and the Allergy Record

A patient's contraindications and precautions are captured as `AllergyRecord` entries. A clinician records one by supplying the `patient_id`, the `antigen` family the record concerns (matching a product's `antigen`), and an optional `severity` that defaults to `CONTRAINDICATED`, the alternative being `PRECAUTION`. A `CONTRAINDICATED` record blocks any new dose of a product mapping to that antigen for as long as the record stands; a `PRECAUTION` record allows the dose while standing as a recorded warning. Every manually entered record has `origin` of `MANUAL` and a `source_event_id` of `null`.

The registry also creates allergy records automatically. When a serious adverse event is confirmed, the cascade described in Section 3.5 creates a record with `origin` of `ADVERSE_EVENT`, `severity` of `CONTRAINDICATED`, and `source_event_id` set to the confirming adverse event's `id`. The `origin` field is therefore system-controlled and is never supplied by a client.

### 3.5. Adverse Events and the VAERS Cascade

A VAERS adverse-event report is filed against a specific dose. The filer supplies the `immunization_id` of the suspect dose, a `seriousness` that is either `SERIOUS` or `NON_SERIOUS` (defaulting to `NON_SERIOUS`), and a free-text `symptoms` description; the system copies the dose's `patient_id` onto the new `AdverseEvent` and starts it in `REPORTED` status. The report then moves through a registrar-driven lifecycle. From `REPORTED` it advances to `UNDER_REVIEW` on review; from `UNDER_REVIEW` it advances to `CONFIRMED` on confirmation; and it may be dismissed to `DISMISSED` either directly from `REPORTED` or from `UNDER_REVIEW`. Each of these four transitions requires the report to be in the stated originating status — `REPORTED` for review, `UNDER_REVIEW` for confirm, and `REPORTED` or `UNDER_REVIEW` for dismiss — and a transition attempted from any other status is rejected with `ERR_INVALID_STATE`. Each transition increments the event's `version` by 1.

Confirmation is where the two branches diverge. Confirming an event whose `seriousness` is `SERIOUS` creates, as cascade hop one, a `CONTRAINDICATED` `AllergyRecord` of `origin` `ADVERSE_EVENT` on the patient for the dose's product antigen — but only if no allergy record already exists for that antigen, so a confirmation never produces a duplicate contraindication. Confirming an event whose `seriousness` is `NON_SERIOUS` performs no such creation; the two branches differ only in this spawned record, and a non-serious confirmation simply records the status change. When the contraindication is created, it becomes a fact the next schedule evaluation must honor: as cascade hop two, the affected antigen is rendered unsatisfiable, so the patient's next evaluation marks that antigen, and therefore the overall posture, `NON_COMPLIANT`.

### 3.6. Schedule Evaluation, Due Dates, and Completeness

Running an evaluation produces a `ScheduleEvaluation` snapshot for a patient. The caller may supply an `as_of_date`; when omitted it defaults to the current clock date. The evaluation computes, per mandated antigen, an entry in `antigen_results` and rolls those up into an `overall_status` and a `completeness_pct`, then copies the resulting `overall_status` onto the patient's `schedule_status` and increments the patient's `version` by 1. The mandated antigen set is the distinct set of `antigen` values over all `ACTIVE` products; `state_code` is recorded on the patient but the mandate in this registry is the full active-product antigen set, each antigen weighted equally.

For each mandated antigen the engine computes, using only the `VALID` doses produced by the dose-validity replay: a `valid_dose_count`, the number of valid doses of that antigen; a `required_doses`, the `doses_in_series` of the antigen's product; and a `satisfied` flag that is true exactly when the valid-dose count is greater than or equal to the required count. It also computes two distinct due dates from two different baselines. Let the patient's "last valid date" be the `administered_date` of the highest-numbered valid dose, or the patient's `date_of_birth` if the antigen has no valid dose yet. When the valid-dose count is zero, the `next_valid_due_date` is the `date_of_birth` plus `min_age_days` reduced by the grace window, and the `next_recommended_due_date` is the `date_of_birth` plus `recommended_age_days`. When the valid-dose count is greater than zero, the `next_valid_due_date` is the last valid date plus `min_interval_days` reduced by the grace window, and the `next_recommended_due_date` is the last valid date plus the full `min_interval_days` with no grace applied. The minimum-interval baseline is the earliest date a catch-up dose may be given and still count; the recommended baseline uses the un-graced cadence and therefore always lands on the same date or later than the minimum baseline for identical patient data. Each antigen result object carries `antigen`, `valid_dose_count`, `required_doses`, `next_valid_due_date`, `next_recommended_due_date`, and `satisfied`.

The compliance percentage is computed with the rounding order pinned: for each mandated antigen, the per-antigen percentage is 100 multiplied by the lesser of its valid-dose count and its required count, divided by its required count, and that quotient is rounded half-up to 2 decimal places *per antigen first*. The overall `completeness_pct` is then the sum of those already-rounded per-antigen percentages divided by the number of mandated antigens, with that average rounded half-up to 2 decimal places. Rounding per antigen before averaging is mandatory; averaging the raw ratios and rounding once would yield different cents.

The `overall_status` is resolved in this order: if any mandated antigen has a `CONTRAINDICATED` allergy record and is unsatisfied, the status is `NON_COMPLIANT`; otherwise, if every antigen is satisfied, the status is `UP_TO_DATE`; otherwise, if every unsatisfied antigen has a `next_valid_due_date` strictly after the `as_of_date` (its next dose is not yet due), the status is `CONDITIONAL`; otherwise the status is `BEHIND`. These same four values are the only ones `schedule_status` and `overall_status` ever take.

### 3.7. School Compliance Certificates and Their Revocation

A school compliance certificate is the artifact a family presents at enrollment, and it is always issued against a specific evaluation snapshot. The registrar issues one by citing the `evaluation_id` of the snapshot and supplying the `expected_patient_version` for the optimistic-concurrency check of Section 2.10. Issuance is permitted only when the cited evaluation's `overall_status` is `UP_TO_DATE` or `CONDITIONAL`; an evaluation that is `BEHIND` or `NON_COMPLIANT` cannot back a certificate and the issuance is rejected with `ERR_NOT_COMPLIANT` (HTTP 422). The certificate's `certificate_type` is derived from the snapshot: `COMPLETE` when the evaluation is `UP_TO_DATE`, and `CONDITIONAL` when the evaluation is `CONDITIONAL`.

A new certificate is created in `ACTIVE` status. Issuing it supersedes the patient's prior `ACTIVE` certificate: that prior certificate transitions from `ACTIVE` to `SUPERSEDED`, the patient's `active_certificate_id` is set to the new certificate's `id`, and the patient's `version` is incremented (the very increment that makes a second issuance carrying the old `expected_patient_version` stale). A certificate also leaves `ACTIVE` through revocation: when a lot recall or a confirmed serious adverse-event cascade recomputes a patient's evaluation and the recomputed `overall_status` drops to `BEHIND` or `NON_COMPLIANT`, the patient's `ACTIVE` certificate transitions from `ACTIVE` to `REVOKED`, the patient's `active_certificate_id` is set to `null`, and the certificate's `version` is incremented. `SUPERSEDED` and `REVOKED` are both terminal.

### 3.8. Provider Batch Reporting and Fork-Join Adjudication

Providers submit doses in batches rather than one at a time. A provider (or the registrar) opens a `ProviderReport` by supplying the `provider_id` and a `line_count`, the number of dose lines the provider intends to submit, which must be at least 1; the report begins in `DRAFT` status with `accepted_count` and `rejected_count` both 0. The provider then attaches dose lines one at a time, each line supplying a `patient_id`, a `lot_id`, and an `administered_date`; a line is only a pending intention and is not materialized into an `Immunization` until adjudication accepts it.

Submitting a draft report is reserved to the owning `Provider` and moves it from `DRAFT` to `SUBMITTED`. Submission requires that the report is in `DRAFT`, that the count of attached lines equals the report's `line_count`, and that the acting provider is the report's provider and is `ENROLLED`. A count mismatch is rejected with `ERR_LINE_COUNT_MISMATCH` (HTTP 422); a provider whose `status` is `SUSPENDED` attempting to submit is rejected with `ERR_PROVIDER_SUSPENDED` (HTTP 409); a report not in `DRAFT` is rejected with `ERR_INVALID_STATE`. Submission increments the report's `version` by 1.

Adjudication is reserved to the registrar and is the fork-join heart of batch processing: it must be applied to a `SUBMITTED` report and processes exactly `line_count` lines, applying to each line the ordered per-line checks of Section 3.3 (provider authorization, recall, expiry, contraindication, and capacity). The realized split of passing and failing lines selects exactly one of three terminal outcomes. When every line passes, the report transitions from `SUBMITTED` to `ACCEPTED`: a `RECORDED` `Immunization` is created for each line with its `report_id` set to this report, the dose-validity replay runs for each, each affected lot's `administered_count` is incremented by 1, and `accepted_count` is set to `line_count` while `rejected_count` is set to 0. When at least one line passes and at least one line fails, the report transitions from `SUBMITTED` to `PARTIALLY_REJECTED`: an `Immunization` is materialized only for the accepted lines and only those lots' `administered_count` values are incremented, while `accepted_count` and `rejected_count` are set to the realized split. When every line fails, the report transitions from `SUBMITTED` to `REJECTED`: no `Immunization` is created at all, `accepted_count` is set to 0, and `rejected_count` is set to `line_count`. All three outcomes increment the report's `version` by 1, and `ACCEPTED` and `REJECTED` are terminal.

### 3.9. Lot Recalls, Cascading Invalidation, and Compensating Reversal

A lot recall is the registry's most far-reaching event. The registrar issues a `LotRecall` against a lot by supplying a free-text `reason`. Issuing the recall sets the lot's `status` to `RECALLED` and then cascades in three hops. Cascade hop one: every `Immunization` on the lot that is `RECORDED` or `AMENDED` transitions to `INVALIDATED`, its `validity` is set to `INVALID_RECALL`, the lot's `administered_count` is decremented by 1 for each such dose (honoring the conserved-quantity invariant of Section 2.8), the patient's remaining valid same-antigen doses are renumbered, and each struck dose's `version` is incremented; the recall's `invalidated_count` is set to the number of doses struck. Cascade hop two: every affected patient's latest `ScheduleEvaluation` and `schedule_status` are recomputed against the now-reduced valid-dose counts. Cascade hop three: any `ACTIVE` certificate whose patient's recomputed `overall_status` has dropped to `BEHIND` or `NON_COMPLIANT` is revoked as described in Section 3.7.

A recall can be undone. Reversing a recall is reserved to the registrar and is permitted only while the recall is in its issued posture and the lot is still recalled by it; a reversal attempted otherwise is rejected with `ERR_INVALID_STATE`. The reversal is a precise compensation: the lot's `status` returns to `AVAILABLE`, and every `Immunization` struck by this recall transitions from `INVALIDATED` back to `RECORDED`. For each restored dose the lot's `administered_count` is incremented by 1, the dose's `validity` is recomputed by the dose-validity replay — which may resolve to `VALID` or, if interval or age rules now fail, to an interval or age failure — its `dose_number` is recomputed across the patient's same-antigen series, and the dose's `version` is incremented. The reversal increments the recall's `version` by 1. The invalidate-then-reverse cycle, taking a dose `RECORDED → INVALIDATED → RECORDED`, is the one cycle in the dose lifecycle; every other dose path is one-way.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that read a resource or list, or that drive a state transition or other modification on an existing resource, return `200 OK`. Every endpoint requires the authentication headers of Section 2.1, and access is restricted to the roles named below. The request and response payloads for each endpoint are described in the workflow narratives of Section 3; the table is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/patients` | Register a child | ImmunizationRegistrar, RecordsClerk |
| GET | `/patients/{id}` | Fetch a patient | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/patients` | List patients | ImmunizationRegistrar, RecordsClerk |
| GET | `/patients/{id}/immunizations` | List a patient's immunizations | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/patients/{id}/allergy-records` | List a patient's allergy records | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/patients/{id}/evaluations` | List a patient's schedule evaluations | ImmunizationRegistrar, RecordsClerk |
| GET | `/patients/{id}/certificates` | List a patient's certificates | ImmunizationRegistrar, RecordsClerk |
| POST | `/providers` | Enroll a provider | ImmunizationRegistrar |
| GET | `/providers/{id}` | Fetch a provider | ImmunizationRegistrar, Provider |
| POST | `/products` | Define a vaccine product / series | ImmunizationRegistrar |
| GET | `/products/{id}` | Fetch a product | ImmunizationRegistrar, Provider, RecordsClerk |
| POST | `/lots` | Register a vaccine lot | ImmunizationRegistrar |
| GET | `/lots/{id}` | Fetch a lot | ImmunizationRegistrar, Provider |
| GET | `/lots` | List lots, optionally filtered by product | ImmunizationRegistrar, Provider |
| GET | `/lots/{id}/immunizations` | List immunizations drawn from a lot | ImmunizationRegistrar, Provider |
| POST | `/lots/{id}/recalls` | Issue a recall on a lot | ImmunizationRegistrar |
| GET | `/lots/{id}/recalls` | List recalls on a lot | ImmunizationRegistrar, Provider |
| POST | `/lots/{id}/recalls/{recall_id}/reverse` | Reverse a recall | ImmunizationRegistrar |
| POST | `/immunizations` | Record a directly administered dose | ImmunizationRegistrar, RecordsClerk |
| GET | `/immunizations/{id}` | Fetch an immunization | ImmunizationRegistrar, RecordsClerk, Provider |
| PATCH | `/immunizations/{id}` | Correct a dose's administered date | RecordsClerk |
| DELETE | `/immunizations/{id}` | Retract a dose | ImmunizationRegistrar |
| GET | `/immunizations` | List immunizations, optionally filtered | ImmunizationRegistrar, RecordsClerk, Provider |
| POST | `/allergy-records` | Record a contraindication or precaution | ImmunizationRegistrar, RecordsClerk |
| GET | `/allergy-records/{id}` | Fetch an allergy record | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/allergy-records` | List allergy records, optionally filtered | ImmunizationRegistrar, RecordsClerk, Provider |
| POST | `/provider-reports` | Open a draft batch report | Provider, ImmunizationRegistrar |
| POST | `/provider-reports/{id}/lines` | Attach one dose line to a draft report | Provider, ImmunizationRegistrar |
| GET | `/provider-reports/{id}` | Fetch a report | Provider, ImmunizationRegistrar |
| GET | `/provider-reports` | List reports, optionally filtered by provider | Provider, ImmunizationRegistrar |
| GET | `/provider-reports/{id}/immunizations` | List immunizations materialized from a report | Provider, ImmunizationRegistrar |
| POST | `/provider-reports/{id}/submit` | Submit a draft report for adjudication | Provider |
| POST | `/provider-reports/{id}/adjudicate` | Adjudicate a submitted report | ImmunizationRegistrar |
| POST | `/adverse-events` | File a VAERS adverse-event report | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/adverse-events/{id}` | Fetch an adverse event | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/adverse-events` | List adverse events, optionally filtered | ImmunizationRegistrar, RecordsClerk, Provider |
| POST | `/adverse-events/{id}/review` | Move a report to under review | ImmunizationRegistrar |
| POST | `/adverse-events/{id}/confirm` | Confirm a report | ImmunizationRegistrar |
| POST | `/adverse-events/{id}/dismiss` | Dismiss a report | ImmunizationRegistrar |
| POST | `/patients/{id}/evaluations` | Run the catch-up engine for a patient | ImmunizationRegistrar, RecordsClerk |
| GET | `/evaluations/{id}` | Fetch a schedule evaluation | ImmunizationRegistrar, RecordsClerk |
| POST | `/patients/{id}/certificates` | Issue a school compliance certificate | ImmunizationRegistrar |
| GET | `/certificates/{id}` | Fetch a certificate | ImmunizationRegistrar, RecordsClerk, Provider |
| GET | `/certificates` | List certificates, optionally filtered | ImmunizationRegistrar, RecordsClerk, Provider |
| POST | `/_clock/set_current_utc` | Test-driving: set the server's current UTC instant | ImmunizationRegistrar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_PRODUCT_NOT_AUTHORIZED` | 422 |
| `ERR_LOT_RECALLED` | 409 |
| `ERR_LOT_EXPIRED` | 422 |
| `ERR_CONTRAINDICATED` | 422 |
| `ERR_INTERVAL_TOO_SHORT` | 422 |
| `ERR_LOT_DEPLETED` | 422 |
| `ERR_NOT_COMPLIANT` | 422 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
| `ERR_LINE_COUNT_MISMATCH` | 422 |
| `ERR_PROVIDER_SUSPENDED` | 409 |
| `ERR_DUPLICATE` | 409 |
| `ERR_ADVERSE_EVENT_BLOCKS_DELETE` | 409 |
| `ERR_VALIDATION` | 422 |

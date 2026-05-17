# State Immunization Information System API — Product Requirements Document

## 1. Introduction

State health departments operate an Immunization Information System (IIS) as the source-of-truth registry for childhood vaccination history. The system must simultaneously serve four distinct constituencies — clinicians administering vaccines, school registrars verifying entry requirements, public-health officers managing supply and recalls, and reviewing clinicians adjudicating adverse events — each with different write privileges and different views of the same underlying patient record. Because a single lot recall can cascade through hundreds of administered doses, demote previously-issued school certificates, and reopen adverse-event reviews in the same atomic request, the IIS cannot be modeled as a CRUD store; it is a tightly coupled compliance engine where one input mutates many entities in a deterministic, auditable sequence.

This document specifies the REST API that backs this IIS. The API is built around the CDC's routine and catch-up immunization schedules, the federal VAERS adverse-event reporting pathway, and state-level school enrollment requirements. Three design tensions drive the specification. First, **safety supersedes throughput**: a known anaphylactic allergy must block administration before any age or interval check is even attempted. Second, **segregation of duties is mandatory for VAERS**: the clinician who administered a dose may not be the one who clinically adjudicates the adverse event reported against it. Third, **lot recalls fan out**: a single recall request triggers a three-hop cascade across administered doses, school certificates, and adverse-event reviews, and the system must complete every hop synchronously within the recall request itself before responding to the issuer.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID` (the acting user's identifier) and `X-User-Role` (the user's role). If either header is absent the server responds with `ERR_AUTH_HEADER_MISSING`. If `X-User-Role` is not one of the four declared roles below, the server responds with `ERR_AUTH_HEADER_INVALID`. If the role is recognised but is not permitted to invoke the requested endpoint, the server responds with `ERR_FORBIDDEN`.

The four roles are:

- `ProviderClinician` — a clinician at a `ProviderOrganization` who schedules doses, administers them, records allergies, and reports adverse events.
- `ReviewingClinician` — an independent clinician (different from the administering clinician) who opens, concludes, and submits adverse-event cases to VAERS.
- `SchoolRegistrar` — school staff who create, issue, and revoke school enrollment certificates; cannot administer doses.
- `PublicHealthOfficer` — state public-health staff who manage vaccine products, lots, recalls, antigen schedule rules, and provider organizations; cannot administer doses or perform adverse-event clinical review.

For all four roles, `X-User-ID` is an opaque operator identifier and is **not** the `id` of any persisted entity in the system. The server does not compare `X-User-ID` to any entity's `id`. It is, however, recorded on the dose record as `administering_clinician_id` when a `ProviderClinician` administers a dose, and that recorded value is later used as the segregation-of-duties anchor when an adverse event tied to the dose is concluded or submitted to VAERS — see §3 for the exact rule.

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

All list endpoints accept two query parameters: `limit` and `offset`. The default value of `limit` is `10`, its minimum is `1`, and its maximum is `100`. The default value of `offset` is `0`. Unless a particular endpoint specifies otherwise, list results are sorted by `created_at` in ascending order. The `meta` object on every list response carries `limit`, `offset`, `total_count` (the total number of records that match the filter, ignoring pagination), and `has_more` (true when more records remain after this page).

### 2.4. Common Resource Properties

Every persisted entity carries an `id`, which is a server-minted UUID that is not prefixed with any type discriminator. Every entity also carries a `created_at` timestamp recorded when the entity was first persisted. Both timestamps follow ISO 8601 UTC notation with three fractional-second digits.

Most entities additionally carry `updated_at` and `version`. `updated_at` is refreshed every time any mutating operation touches the entity (including system-driven cascades — a school certificate demoted by a lot recall has its `updated_at` advanced even though the request was not addressed to it). `version` is an integer that starts at `1` on creation and increments by exactly `1` on every persisted mutation, again including cascades.

The `AllergyRecord` entity is the single exception: its record is immutable once written and therefore carries only `id` and `created_at` — both `updated_at` and `version` are absent from its representation. The `recorded_at` field on an allergy record likewise reflects the moment the allergy was first entered and is never rewritten.

### 2.5. Nested Resource Validation Order

Many endpoints address nested resources — for example, a single dose lives under `/patients/{patient_id}/doses/{dose_id}`. The server validates path parameters strictly left-to-right. The `patient_id` is checked first; a non-existent patient yields `ERR_PATIENT_NOT_FOUND` before the system attempts to find the dose. Only when the parent is confirmed does the server resolve the child segment; a missing dose under a real patient yields `ERR_DOSE_NOT_FOUND`. The same left-to-right discipline applies to `cert_id` under a patient (`ERR_CERTIFICATE_NOT_FOUND`), to `lot_id` (`ERR_LOT_NOT_FOUND`), to `product_id` (`ERR_PRODUCT_NOT_FOUND`), to an adverse-event `id` (`ERR_ADVERSE_EVENT_NOT_FOUND`), and to a provider-organization `id` (`ERR_PROVIDER_NOT_FOUND`).

### 2.6. Validation Priority — the Layered Gate Order

When a single request can fail several checks, the server evaluates them in a strictly ordered cascade and returns the first failure it encounters. Lower-numbered checks shield higher-numbered ones from being reached at all — this ordering is observable in tests and must not be reordered.

1. **Authentication first.** `ERR_AUTH_HEADER_MISSING` is returned when either header is absent. Only after both headers are present does the system check that `X-User-Role` is one of the four recognised roles (`ERR_AUTH_HEADER_INVALID`). Only after the role parses does it check that the role is permitted on the endpoint (`ERR_FORBIDDEN`).
2. **Existence next**, in path order — patient, then dose / lot / product / adverse event / certificate / provider as relevant. All existence checks share the 404 status code and each has its own dedicated error id (named in §2.5).
3. **State checks**, including dose-state preconditions (`ERR_INVALID_STATE`), lot-recall state (`ERR_LOT_RECALLED`), and lot-exhaustion state (`ERR_LOT_EXHAUSTED`), are evaluated before business-safety rules so that a structurally impossible request fails fast.
4. **Safety supersedes other business rules.** For dose administration, the allergy contraindication check (`ERR_ALLERGY_CONTRAINDICATION`) is checked before age range, before catch-up interval, and before temporal sanity. For adverse-event review and VAERS submission, the segregation-of-duties check (`ERR_SOD_VIOLATION`) is similarly prioritized over the reportability check.
5. **Business constraints** — age range (`ERR_AGE_OUT_OF_RANGE`), minimum catch-up interval (`ERR_MIN_INTERVAL_VIOLATION`), temporal bounds on `administered_at` (`ERR_ADMIN_TIME_OUT_OF_RANGE`), lot-product correspondence (`ERR_LOT_PRODUCT_MISMATCH`), dose-patient correspondence on adverse-event creation (`ERR_DOSE_PATIENT_MISMATCH`), and onset-window on adverse-event creation (`ERR_ONSET_OUT_OF_WINDOW`).
6. **Provider eligibility and uniqueness** — provider-suspended status blocks new dose scheduling (`ERR_PROVIDER_SUSPENDED`), and the per-(patient, school year) uniqueness check on certificates (`ERR_CERTIFICATE_DUPLICATE`).
7. **Reportability** — VAERS submission requires either a computed `vaers_required` of true or an explicit elective flag (`ERR_VAERS_NOT_REPORTABLE`).
8. **Generic shape** — required-field presence and type checks emit `ERR_VALIDATION`.
9. **Optimistic-concurrency mismatch** — `ERR_VERSION_CONFLICT` is emitted last among the request-level checks.

The practical consequence: if a request both lacks a header and would also fail RBAC, the response is `ERR_AUTH_HEADER_MISSING`, not `ERR_FORBIDDEN`. If a dose-administer request both has a contraindicating allergy and is also out of the age window, the response is `ERR_ALLERGY_CONTRAINDICATION`, not `ERR_AGE_OUT_OF_RANGE`. Tests assert this ordering directly.

### 2.7. Optimistic Concurrency Control

Action endpoints (the various state-transition operations) and any update endpoint accept an optional `version` field in the request body. If `version` is supplied and does not match the current server-held version of the targeted entity, the request is rejected with `ERR_VERSION_CONFLICT`. If `version` is omitted, the check is skipped and the operation proceeds. On a successful mutation, the entity's `version` increments by exactly `1` and its `updated_at` is refreshed.

### 2.8. Precision and Rounding

The reporting compliance score is the only floating-point computation exposed by the API. It is rounded to two decimal places using the round-half-up rule. The rounding order is itself fixed and non-commutative: each individual per-dose contribution is rounded to two decimal places first, those rounded values are summed and divided by the dose count, and finally that average is rounded to two decimal places. "Sum first, then round" is **not** equivalent in boundary cases and is explicitly forbidden.

All age and interval thresholds in the immunization schedule are expressed in whole days. Patient age in days is computed as the floor of the calendar-day difference between `administered_at` and `date_of_birth`; no time-of-day arithmetic enters the comparison.

The VAERS rapid-onset window is expressed in floating-point hours. Lag in hours is computed as the elapsed wall-clock seconds between onset and administration divided by 3600. The boundary comparison uses an inclusive "at most" — exactly 24.0 hours qualifies, 24.0001 hours does not.

### 2.9. Synchronous Cascades and Hierarchical Consistency

The system is consistency-immediate: every cascade that a write triggers must complete inside the same request, with every affected entity's `updated_at` refreshed and `version` incremented before the API responds. There is no eventual-consistency tier, no background reconciliation, and no deferred queue. A lot recall, in particular, is the single largest fan-out operation in the system; its full three-hop cascade — `VaccineLot` → `AdministeredDose` → `SchoolEnrollmentCertificate`, with a parallel third hop into `AdverseEvent.clinical_review_status` — is described in §3.5.

A `created_at` timestamp is never rewritten. An `updated_at` field is rewritten on every mutation, including cascades that touch an entity indirectly. A `version` integer is incremented by exactly one on every such write.

### 2.10. Test-Driving Capabilities

Because reporting compliance scores depend on a 365-day rolling window, lot expirations depend on the calendar, and the VAERS rapid-onset comparison depends on wall-clock arithmetic, the system exposes two test-driving capabilities under the public-health role. The first advances the server's logical clock to a supplied `to_timestamp`. The second simulates the federal VAERS acknowledgement webhook, accepting an `adverse_event_id` and an `outcome` and driving the adverse event's submission status accordingly. Both are restricted to `PublicHealthOfficer`. Their HTTP contracts appear in §4.

## 3. Business Logic & Workflows

### 3.1. Patient Registration and Demographics

The patient record is the root of the hierarchical model — administered doses, allergies, and school enrollment certificates all live underneath a single patient. A `SchoolRegistrar`, a `ProviderClinician`, or a `PublicHealthOfficer` may register a patient by supplying the patient's `first_name` (1 to 80 characters), `last_name` (1 to 80 characters), `date_of_birth` (an ISO 8601 calendar date that must lie strictly in the past relative to the server's current time), `sex_at_birth` (`FEMALE`, `MALE`, or `UNKNOWN` — this drives HPV schedule eligibility and demographic reporting), `state_resident` (a boolean defaulting to true, indicating residency in the state operating this IIS), and `guardian_contact_email` (used for recall notifications and required for state residents). The optional `medical_exemption_on_file` flag defaults to false and, when set to true, allows school certificates to certify medical exemption per CDC ACIP guidance.

Each patient carries a system-managed `status` that starts at `ACTIVE` and may evolve through `DECEASED`, `MERGED_OUT`, or `ARCHIVED` over its lifecycle. The `date_of_birth` is immutable once set — it anchors every age-in-days computation downstream, and rewriting it would silently revalidate decades of dose records. The `PublicHealthOfficer` is the only role permitted to enumerate the cross-patient list endpoint with filters such as `status`, `state_resident`, `date_of_birth_after`, and `date_of_birth_before`; individual-patient reads are broader and available to all four roles.

### 3.2. Vaccine Catalog, Lots, and the Provider Network

A vaccine product carries a CDC `cvx_code` (1 to 6 characters, globally unique among `ACTIVE` products) together with a `trade_name`, an `antigens` array of one or more antigen identifiers (such as `DTAP_DIPHTHERIA`, `DTAP_TETANUS`, `DTAP_PERTUSSIS`, `MMR_MEASLES`, `MMR_MUMPS`, `MMR_RUBELLA`, `HEPB`, `HPV`, `POLIO`, `VARICELLA`), an integer `min_age_days` (at least zero) marking the earliest age in days at which any dose of the product may be administered, an integer `max_age_days` marking the latest such age (a null value indicates no upper bound), a `route` of administration (`IM`, `SC`, `ORAL`, or `INTRANASAL`), an optional `contraindication_flags` array of allergen identifiers, and a system-managed `status` that begins at `ACTIVE` and may transition to `DISCONTINUED`. Only `PublicHealthOfficer` may register a new product or view the broad listing of products by `antigen` or by `status`.

Inventory is tracked at the lot level. A `VaccineLot` references its `vaccine_product_id` and its custodial `provider_organization_id`, carries a manufacturer-issued `lot_number` (unique within a given `vaccine_product_id`), an `expiration_date`, and a system-managed `doses_on_hand` integer that begins at the value supplied at lot creation. The lot's `status` begins at `AVAILABLE`. When `doses_on_hand` reaches zero through normal administration, the status auto-transitions to `EXHAUSTED`. When a recall is issued, the status transitions to `RECALLED` and the system records `recalled_at` and the reason supplied in the request as `recall_reason` (`MANUFACTURER_DEFECT`, `CONTAMINATION`, or `EXPIRED`). Either a `ProviderClinician` or a `PublicHealthOfficer` may register a lot.

A `ProviderOrganization` represents a clinic, hospital, or pharmacy where doses are administered. Each carries a legal `name`, a 10-digit `npi`, and a `reporting_jurisdiction` of either `IN_STATE` or `OUT_OF_STATE`. The system maintains `reporting_compliance_score` (a derived number on the closed interval from zero to 100, defaulting to 100.00) and a `status` of either `ACTIVE` or `SUSPENDED`. The compliance score is described in §3.6.

### 3.3. Scheduling a Dose and Administering It

Dose recording is a two-step ceremony. A `ProviderClinician` first schedules a future dose by posting under the patient with a payload containing `vaccine_product_id`, `lot_id`, `provider_organization_id`, and `administering_clinician_id` (the opaque identifier of the clinician who will give the injection). This persists an `AdministeredDose` with `dose_state` set to `SCHEDULED`, mirrors `patient_id` from the URL, and stamps the moment the record was first POSTed as `reported_at` — that timestamp is later consumed by the compliance score and is **not** overwritten when the dose is subsequently administered. If the recording `ProviderOrganization` is in `SUSPENDED` status, the schedule request is rejected with `ERR_PROVIDER_SUSPENDED`.

A scheduled dose may then be advanced to `ADMINISTERED` by a `ProviderClinician`. The administer request carries only the `administered_at` instant. Before the system accepts the transition it evaluates the following chain in priority order, and the **first** failing check is what the client sees:

- The lot must be selectable for new administration — its `status` must equal `AVAILABLE` (a `RECALLED` lot yields `ERR_LOT_RECALLED`).
- The dose's `dose_state` must be exactly `SCHEDULED` (anything else yields `ERR_INVALID_STATE`).
- The lot must still hold inventory — `doses_on_hand` must be at least 1 (`ERR_LOT_EXHAUSTED`).
- The patient must have no `AllergyRecord` whose `allergen_code` appears in the product's `contraindication_flags` and whose `severity` is either `SEVERE` or `ANAPHYLAXIS` (`ERR_ALLERGY_CONTRAINDICATION`). This safety gate sits above age, interval, and temporal checks because administering a contraindicated product to a known anaphylactic patient is the most harmful failure mode in the system.
- The patient's age in days at `administered_at` must lie within `[min_age_days, max_age_days]` inclusive (a null `max_age_days` means no upper bound); exactly equal to `min_age_days` is allowed, one day short is rejected (`ERR_AGE_OUT_OF_RANGE`).
- If the antigen series for which this dose counts has a `dose_sequence_number` greater than 1, the most recent prior `ADMINISTERED` dose in that same antigen series must exist, and the elapsed days between the new `administered_at` and the prior dose's `administered_at` must be at least the rule's `catchup_min_interval_days`. Exactly equal to the minimum is allowed; one day short is rejected (`ERR_MIN_INTERVAL_VIOLATION`).
- The `administered_at` instant must satisfy two temporal sanity bounds: it must be at most the server's current time, and it must be strictly after the patient's `date_of_birth` (`ERR_ADMIN_TIME_OUT_OF_RANGE`).
- The `lot_id` supplied at scheduling time must refer to a lot whose `vaccine_product_id` equals the product on the dose record (`ERR_LOT_PRODUCT_MISMATCH`).

When all checks pass, the system performs four synchronous side effects in one atomic step. The lot's `doses_on_hand` is decremented by one; if the resulting value is zero the lot's `status` auto-transitions to `EXHAUSTED`. The dose's `catchup_flag` is computed by the CDC catch-up rule described in §3.7, recording true on the dose record if the schedule projection for this position was the catch-up variant. The owning provider organization's `reporting_compliance_score` is recomputed against the rolling window. Finally, every `SchoolEnrollmentCertificate` for this patient whose `certificate_status` is `DRAFT` or `DEFICIENT` has its `missing_antigens` recomputed; if the recompute reveals an empty set, the certificate auto-bubbles up to `ISSUED` and its `issued_at` is stamped.

A scheduled dose can also be cancelled by the same `ProviderClinician` role, advancing `dose_state` from `SCHEDULED` to `CANCELLED`. Cancellation requires only that the dose is in `SCHEDULED` state and has no side effects beyond the state change.

An already-administered dose can be invalidated due to data error by a `PublicHealthOfficer`, supplying the `reason` `DATA_ERROR`. The dose's `dose_state` advances `ADMINISTERED → INVALIDATED`, `invalidation_reason` is recorded as `DATA_ERROR`, the lot's `doses_on_hand` is incremented by one (data-error invalidations always restore stock), and the school-coverage recomputation runs for the patient — demoting any `ISSUED` certificate to `DEFICIENT` if the recompute newly uncovers an antigen.

### 3.4. Allergies and the Contraindication Bridge

A patient's allergy history is recorded by a `ProviderClinician` posting under the patient with an `allergen_code` (one of `EGG`, `LATEX`, `NEOMYCIN`, `GELATIN`, `YEAST`, or `OTHER`) and a `severity` of `MILD`, `MODERATE`, `SEVERE`, or `ANAPHYLAXIS`. The record carries `patient_id` mirrored from the URL, a `recorded_at` timestamp set on entry, and is immutable thereafter — there is no update endpoint, and the entity carries neither `updated_at` nor `version`. Listing allergies under a patient is available to clinicians, reviewing clinicians, and public-health officers.

The link between allergy and dose administration is the contraindication check described above: a product's `contraindication_flags` enumerates the allergen codes whose presence at `SEVERE` or `ANAPHYLAXIS` severity prevents the product from being administered. Lower severities do not block.

### 3.5. Lot Recalls — the Three-Hop Cascade

A `PublicHealthOfficer` issues a recall against a lot by posting under the lot with a `reason`. If the lot's `status` was `AVAILABLE` or `EXHAUSTED` immediately prior, the recall proceeds; the lot transitions to `RECALLED`, the request's `reason` is recorded as `recall_reason`, and `recalled_at` is stamped. The recall request then completes three cascading hops before responding.

**Cascade hop 1 — administered doses.** Every `AdministeredDose` whose `lot_id` matches the recalled lot and whose `dose_state` is `ADMINISTERED` is transitioned to `INVALIDATED` with `invalidation_reason` recorded as `LOT_RECALL`. For each such dose, the system then restores `doses_on_hand` by one **only if** the `recall_reason` is anything other than `EXPIRED` and the lot's status was `AVAILABLE` immediately before the recall. An `EXPIRED` recall does not restore inventory (the doses are physically unusable), and a recall of an `EXHAUSTED` lot leaves `doses_on_hand` at zero — the inventory was depleted before the recall and the invalidations do not refill it.

**Cascade hop 2 — school enrollment certificates.** For every `SchoolEnrollmentCertificate` whose `patient_id` matches an affected patient and whose `certificate_status` is `ISSUED` or `EXEMPTION_GRANTED`, the system reruns the school coverage evaluation. If the recompute reveals at least one uncovered antigen, the certificate's `certificate_status` is auto-demoted to `DEFICIENT` and `missing_antigens` is updated with the alphabetically sorted list.

**Cascade hop 3 — adverse-event clinical review.** Every `AdverseEvent` whose `dose_id` references one of the just-invalidated doses and whose `clinical_review_status` is currently `PENDING_REVIEW` is auto-advanced to `UNDER_REVIEW` — the recall is itself a clinically significant event that necessarily opens an investigation, even if no reviewing clinician has explicitly requested one. The `vaers_submission_status` dimension is untouched by the cascade.

In parallel, the recall recomputes `reporting_compliance_score` for every `ProviderOrganization` that recorded one of the invalidated doses — invalidated doses are excluded from the rolling window, so the score is recomputed on the surviving set.

### 3.6. Provider Reporting Compliance — Rolling Window, Pinned Rounding

A provider organization's `reporting_compliance_score` summarizes how promptly its dose administrations have been reported. It is recomputed on every `SCHEDULED → ADMINISTERED` transition, on every `ADMINISTERED → INVALIDATED` transition, and whenever a single-provider read is served. The window is the rolling 365 days ending at the server's current time, evaluated against `reported_at` (the moment a dose was first POSTed). Doses still in `SCHEDULED` state do not enter the window; doses in `INVALIDATED` state are dropped from the window (the report has effectively been voided); only `ADMINISTERED` rows count. If the window is empty, the score defaults to 100.00.

For each qualifying dose, the system computes the reporting lag in hours as the wall-clock seconds between `reported_at` and `administered_at` divided by 3600, and assigns a per-dose score:

- A lag of at most 24 hours earns 100.00 — full credit, on-time.
- A lag greater than 24 hours and at most 72 hours falls on a linear ramp from 100 down to 40: the score is 100.00 minus the lag in hours minus 24, multiplied by 1.25. So a lag of exactly 24 hours earns 100, a lag of 48 hours earns 70, and a lag of exactly 72 hours earns 40.
- A lag greater than 72 hours and at most 168 hours (one week) is floored at 40.00.
- A lag greater than 168 hours earns 0.00.

Doses are processed in chronological order by `administered_at` ascending, with `id` ascending as the tie-breaker. The rounding is pinned and order-sensitive: each per-dose score is rounded to two decimal places using round-half-up **first**, the rounded values are then summed and divided by the count, and the resulting average is rounded once more to two decimal places using round-half-up. The two roundings are not equivalent — for example, per-dose raw scores of 30.555 and 30.554 round-then-sum to (30.56 + 30.55) ÷ 2 = round(30.555, 2) = 30.56, while sum-then-round would yield round((30.555 + 30.554) ÷ 2, 2) = round(30.5545, 2) = 30.55. The system is pinned to round-then-sum-then-round-the-average.

When the recomputed score falls below 70.00, the provider organization's `status` auto-transitions to `SUSPENDED`. A suspended provider may not schedule new doses (`ERR_PROVIDER_SUSPENDED`). A `PublicHealthOfficer` may also manually suspend a provider, and may reinstate a suspended provider only when its score has climbed back to at least 90.00.

### 3.7. The CDC Catch-Up Schedule — Dual Variants of the Same Calculation

The childhood immunization schedule is modeled as a directed acyclic graph of `AntigenScheduleRule` rows. Each rule pins one antigen-and-sequence slot — its `antigen` (one of the ten antigen identifiers listed in §3.2), its `dose_sequence_number` (1 for the first dose in the series, 2 for the second, and so on; unique within the antigen), its `routine_min_age_days`, `routine_recommended_age_days`, `routine_max_age_days`, its `catchup_min_interval_days` (the minimum number of days between this dose and the previous one in the same antigen series under CDC catch-up rules), an optional `prerequisite_rule_id` self-referencing the rule for the prior dose in the same series (null when the rule is the first dose), and a boolean `school_enrollment_required` indicating whether this dose must be present (or covered by exemption) to issue a school certificate. Only the `PublicHealthOfficer` may register a rule.

Two schedule **variants** govern when a given dose may next be due for a patient. Both variants run over prior `AdministeredDose` rows for the patient in the same antigen series, ordered by `administered_at` ascending; only doses currently in `ADMINISTERED` state count toward "prior doses". `SCHEDULED`, `INVALIDATED`, and `CANCELLED` rows are explicitly excluded — including invalidated rows would let a recalled dose still satisfy a schedule position, and including scheduled rows would let a not-yet-administered plan jump the queue.

- **Routine variant** — used when the patient's current age in days is at most the rule's `routine_max_age_days` and no prior dose in the series was administered after its own rule's `routine_max_age_days`. The eligible age in days is the rule's `routine_min_age_days`. The next-due date is the patient's `date_of_birth` plus the rule's `routine_recommended_age_days`. The `catchup_flag` for any dose recorded under this projection is false.

- **Catch-up variant** — used when the patient's current age in days is greater than the rule's `routine_max_age_days`, **or** when any previously administered dose in the same antigen series was given after its own rule's `routine_max_age_days`. The eligible date is the **greater** of (a) `date_of_birth` plus the rule's `routine_min_age_days` and (b) the `administered_at` of the most recent `ADMINISTERED` dose in the series plus the rule's `catchup_min_interval_days`. The next-due date equals that eligible date; the `routine_recommended_age_days` is ignored in this variant. The `catchup_flag` for any dose recorded under this projection is true.

The next-due endpoint returns, for each antigen series, the projected next-due date, the variant used (`routine` or `catchup`), and the list of antigens missing for school enrollment. The catch-up calculation is also consulted internally during dose administration — that is how the dose's `catchup_flag` gets set, and is what makes the CDC catch-up logic observable on the dose record itself.

Age is measured in calendar days only: patient age in days equals the floor of the calendar-day difference between the comparison date and `date_of_birth`. No time-of-day arithmetic enters the comparison.

### 3.8. School Enrollment Certificates — Coverage Evaluation and Lifecycle

A `SchoolRegistrar` creates a draft certificate under a patient by supplying `school_year` (formatted `YYYY-YYYY`, with the second four-digit year exactly one greater than the first) and `grade_level` (one of `K`, `G1` through `G12`). The certificate's `patient_id` mirrors the URL, its `certificate_status` begins at `DRAFT`, its `missing_antigens` starts as the empty array, and `issued_at` is null. At most one certificate with `certificate_status` other than `REVOKED` may exist for a given (`patient_id`, `school_year`) pair; a second attempt is rejected with `ERR_CERTIFICATE_DUPLICATE`.

Issuance runs the **school coverage evaluation**. The system first computes the required antigen set as the antigens of every `AntigenScheduleRule` whose `school_enrollment_required` is true. It then computes the covered antigen set by taking the union of the `antigens` arrays of the products attached to every `AdministeredDose` for this patient currently in `ADMINISTERED` state, intersected with the required set. The `missing_antigens` array is the set difference (required minus covered), sorted alphabetically ascending by antigen name so that the result is order-stable across invocations.

Three outcomes resolve in a fixed precedence:

- If `medical_exemption_on_file` on the patient is true, the certificate's `certificate_status` becomes `EXEMPTION_GRANTED`, `missing_antigens` is set to the empty array, and `issued_at` is stamped. Exemption suppresses the coverage requirement entirely — it wins over `ISSUED` when both could theoretically apply.
- Otherwise, if `missing_antigens` evaluates to empty, `certificate_status` becomes `ISSUED` and `issued_at` is stamped.
- Otherwise, `certificate_status` becomes `DEFICIENT`, `missing_antigens` retains the sorted list of uncovered antigens, and `issued_at` remains null.

A certificate already in `DEFICIENT` state may auto-bubble up to `ISSUED` when a later dose administration causes the recompute (run automatically at administer time, see §3.3) to find `missing_antigens` empty — the system stamps `issued_at` at that moment. Conversely, a certificate in `ISSUED` or `EXEMPTION_GRANTED` may be auto-demoted to `DEFICIENT` when a lot recall (§3.5) or a data-error invalidation (§3.3) causes the recompute to newly uncover an antigen. A `SchoolRegistrar` may revoke a certificate from `ISSUED`, `DEFICIENT`, or `EXEMPTION_GRANTED` into the terminal `REVOKED` state; revocation has no further side effects.

Listing certificates under a patient supports filters on `school_year` and `certificate_status` and is open to school registrars, provider clinicians, and public-health officers.

### 3.9. Adverse Events — Parallel Review and Submission Dimensions

A report of a suspected vaccine-induced adverse event is opened by either a `ProviderClinician` or a `ReviewingClinician` posting an `AdverseEvent` with `patient_id`, `dose_id` (the suspected trigger dose, which must belong to `patient_id` — mismatch yields `ERR_DOSE_PATIENT_MISMATCH`), `onset_at` (the instant symptoms began, which must be at or after the dose's `administered_at` and within 42 days of it; outside that window yields `ERR_ONSET_OUT_OF_WINDOW`), a `symptom_codes` array of at least one MedDRA-like code, and a `seriousness` of `NON_SERIOUS`, `SERIOUS`, or `DEATH`. The referenced dose must be in `dose_state` `ADMINISTERED` at report time.

At creation the system runs the **VAERS reportability determination**. The reporting lag in hours is the wall-clock seconds between `onset_at` and the referenced dose's `administered_at` divided by 3600. The persisted `vaers_required` field is true if and only if either `seriousness` is `SERIOUS` or `DEATH`, or the lag in hours is at most 24.0. The boundary is exact and inclusive: a lag of exactly 24.0 hours qualifies, 24.0001 hours does not, and a lag of zero qualifies. Negative lags (onset before administration) are already rejected at the priority-90 validation gate (`ERR_ONSET_OUT_OF_WINDOW`).

An `AdverseEvent` carries two state dimensions that evolve **independently** on the same row:

- `clinical_review_status` runs `PENDING_REVIEW → UNDER_REVIEW → (CAUSALLY_RELATED | NOT_RELATED)`.
- `vaers_submission_status` runs `NOT_SUBMITTED → SUBMITTED → (ACK_RECEIVED | REJECTED)`.

The clinical-review dimension is driven by a `ReviewingClinician`. Opening the case advances it from `PENDING_REVIEW` to `UNDER_REVIEW`; the same transition can also fire as cascade hop 3 of a lot recall, in which case the actor is the system. Concluding the case requires the body to supply a `conclusion` of either `CAUSALLY_RELATED` or `NOT_RELATED`, and the dimension advances accordingly. **Segregation of duties is enforced** on both the conclude step and the VAERS submission step: the acting `X-User-ID` must not equal the `administering_clinician_id` recorded on the referenced dose. A self-review or self-submission yields `ERR_SOD_VIOLATION`. The SOD rule does not apply when the cascade-driven `PENDING_REVIEW → UNDER_REVIEW` transition is performed by the system itself (the system has no clinician identity to compare).

A conclusion of `CAUSALLY_RELATED` does **not** automatically submit the case to VAERS. The system logs an audit note when `vaers_required` is true and submission has not yet occurred, but it does not auto-fire submission — submission is always a separate, deliberate action.

The submission dimension is driven by a `ReviewingClinician` posting the submit action. Two preconditions guard it: the clinical review must already be at least `UNDER_REVIEW` (specifically, `clinical_review_status` must be one of `UNDER_REVIEW`, `CAUSALLY_RELATED`, or `NOT_RELATED`), and either `vaers_required` must be true or the request body must carry `elective` set to true. Otherwise the submission is rejected with `ERR_VAERS_NOT_REPORTABLE`. When the submission lands, the system mints a UUID and writes it as `vaers_submission_id`, advancing `vaers_submission_status` from `NOT_SUBMITTED` to `SUBMITTED`. The downstream acknowledgement — `SUBMITTED → ACK_RECEIVED` or `SUBMITTED → REJECTED` — is delivered by the test-only VAERS acknowledgement webhook, whose body carries an `outcome` of `ACK` or `REJECT`.

### 3.10. Concurrency Resolutions

Several races are explicitly serialized.

When two clinicians simultaneously try to administer doses from the same lot whose `doses_on_hand` is `1`, the decrement on `doses_on_hand` is first-writer-wins; exactly one administer succeeds, and the loser receives `ERR_LOT_EXHAUSTED`. When a recall is issued at the same moment a clinician is trying to administer from the same lot, the lot's `status` transition is first-writer-wins on `VaccineLot.status`; if the recall lands first, the in-flight administer is rejected with `ERR_LOT_RECALLED`, and if the administer lands first, the dose is created in `ADMINISTERED` state and the recall's cascade then invalidates it as part of hop 1.

When two reviewing clinicians simultaneously conclude the same adverse-event review, the change to `clinical_review_status` is first-writer-wins; exactly one conclusion is recorded, and the second sees `ERR_INVALID_STATE` because the dimension is no longer in `UNDER_REVIEW`. When two reviewing clinicians simultaneously submit the same adverse event to VAERS, the change to `vaers_submission_status` is first-writer-wins; at most one submission lands, and the second receives `ERR_VAERS_ALREADY_SUBMITTED`. When two school registrars simultaneously issue certificates for the same patient and `school_year`, uniqueness over (`patient_id`, `school_year`) restricted to `certificate_status` other than `REVOKED` is enforced first-writer-wins; the second receives `ERR_CERTIFICATE_DUPLICATE`.

## 4. Endpoint Definitions

New-resource creation endpoints return HTTP 201. All other successful operations — reads, list views, state-transition actions, and cascade-triggering writes such as recall and invalidate — return HTTP 200. Every endpoint requires the `X-User-ID` and `X-User-Role` headers per §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/patients` | Register a new patient. | SchoolRegistrar, ProviderClinician, PublicHealthOfficer |
| GET | `/patients/{patient_id}` | Read a single patient. | SchoolRegistrar, ProviderClinician, ReviewingClinician, PublicHealthOfficer |
| GET | `/patients` | List patients with filtering and pagination. | PublicHealthOfficer |
| GET | `/patients/{patient_id}/next-due` | Compute next-due doses per antigen series. | ProviderClinician, SchoolRegistrar |
| POST | `/vaccine-products` | Register a vaccine product. | PublicHealthOfficer |
| GET | `/vaccine-products/{product_id}` | Read a vaccine product. | SchoolRegistrar, ProviderClinician, ReviewingClinician, PublicHealthOfficer |
| GET | `/vaccine-products` | List vaccine products. | SchoolRegistrar, ProviderClinician, ReviewingClinician, PublicHealthOfficer |
| POST | `/vaccine-lots` | Provider records a new lot in inventory. | ProviderClinician, PublicHealthOfficer |
| GET | `/vaccine-lots/{lot_id}` | Read a lot. | ProviderClinician, PublicHealthOfficer |
| POST | `/vaccine-lots/{lot_id}/recall` | Public health issues a recall on a lot. | PublicHealthOfficer |
| POST | `/patients/{patient_id}/doses` | Schedule a future dose. | ProviderClinician |
| POST | `/patients/{patient_id}/doses/{dose_id}/administer` | Mark a scheduled dose administered now. | ProviderClinician |
| POST | `/patients/{patient_id}/doses/{dose_id}/cancel` | Cancel a scheduled dose. | ProviderClinician |
| POST | `/patients/{patient_id}/doses/{dose_id}/invalidate` | Invalidate an administered dose due to data error. | PublicHealthOfficer |
| GET | `/patients/{patient_id}/doses` | List administered and scheduled doses for a patient. | ProviderClinician, SchoolRegistrar, ReviewingClinician, PublicHealthOfficer |
| GET | `/patients/{patient_id}/doses/{dose_id}` | Read a single dose. | ProviderClinician, SchoolRegistrar, ReviewingClinician, PublicHealthOfficer |
| POST | `/patients/{patient_id}/allergies` | Record an allergy. | ProviderClinician |
| GET | `/patients/{patient_id}/allergies` | List patient allergies. | ProviderClinician, ReviewingClinician, PublicHealthOfficer |
| POST | `/adverse-events` | Report an adverse event. | ProviderClinician, ReviewingClinician |
| POST | `/adverse-events/{id}/start-review` | Reviewing clinician opens the case for review. | ReviewingClinician |
| POST | `/adverse-events/{id}/conclude-review` | Reviewing clinician records a verdict. | ReviewingClinician |
| POST | `/adverse-events/{id}/submit-vaers` | Submit the adverse event to VAERS. | ReviewingClinician |
| GET | `/adverse-events/{id}` | Read an adverse event. | ReviewingClinician, ProviderClinician, PublicHealthOfficer |
| GET | `/adverse-events` | List adverse events with filters. | ReviewingClinician, PublicHealthOfficer |
| POST | `/antigen-schedule-rules` | Register a schedule rule. | PublicHealthOfficer |
| GET | `/antigen-schedule-rules` | List schedule rules. | PublicHealthOfficer, SchoolRegistrar, ProviderClinician, ReviewingClinician |
| POST | `/patients/{patient_id}/certificates` | Create a draft certificate. | SchoolRegistrar |
| POST | `/patients/{patient_id}/certificates/{cert_id}/issue` | Issue the certificate (evaluates coverage). | SchoolRegistrar |
| POST | `/patients/{patient_id}/certificates/{cert_id}/revoke` | Revoke a certificate. | SchoolRegistrar |
| GET | `/patients/{patient_id}/certificates` | List certificates. | SchoolRegistrar, ProviderClinician, PublicHealthOfficer |
| POST | `/provider-organizations` | Register a provider. | PublicHealthOfficer |
| GET | `/provider-organizations/{id}` | Read a provider; recomputes compliance score. | PublicHealthOfficer, ProviderClinician |
| POST | `/provider-organizations/{id}/suspend` | Manually suspend a provider. | PublicHealthOfficer |
| POST | `/provider-organizations/{id}/reinstate` | Reinstate a suspended provider. | PublicHealthOfficer |
| POST | `/_clock/advance` | Test-only: advance the server's logical clock to a supplied instant. | PublicHealthOfficer |
| POST | `/_events/vaers-ack` | Test-only: simulate the federal VAERS acknowledgement webhook. | PublicHealthOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_HEADER_MISSING` | 401 |
| `ERR_AUTH_HEADER_INVALID` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_PROVIDER_SUSPENDED` | 403 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_DOSE_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_ADVERSE_EVENT_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_LOT_RECALLED` | 409 |
| `ERR_LOT_EXHAUSTED` | 409 |
| `ERR_CERTIFICATE_DUPLICATE` | 409 |
| `ERR_VAERS_ALREADY_SUBMITTED` | 409 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_ALLERGY_CONTRAINDICATION` | 422 |
| `ERR_AGE_OUT_OF_RANGE` | 422 |
| `ERR_MIN_INTERVAL_VIOLATION` | 422 |
| `ERR_ADMIN_TIME_OUT_OF_RANGE` | 422 |
| `ERR_LOT_PRODUCT_MISMATCH` | 422 |
| `ERR_DOSE_PATIENT_MISMATCH` | 422 |
| `ERR_ONSET_OUT_OF_WINDOW` | 422 |
| `ERR_SOD_VIOLATION` | 422 |
| `ERR_VAERS_NOT_REPORTABLE` | 422 |
| `ERR_VALIDATION` | 400 |

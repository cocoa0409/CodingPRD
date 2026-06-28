# Podiatry Foot-Care Practice API — Product Requirements Document

## 1. Introduction

A podiatry and foot-care practice sits at an unusual intersection of clinical judgment, payer rules, and inventory logistics. A single patient visit can spawn a routine nail debridement that may or may not be covered depending on the patient's diabetic status and how recently the same service was last paid, an orthotic prescription that must wend its way through prior authorization and a fabrication lab, a durable medical equipment (DME) dispense whose rental charges must rent-to-own without ever overcharging, and an imaging study competing for time on a shared machine. This document specifies the back-end API that coordinates all of these threads so that clinical authorship, revenue-cycle coding, payer adjudication, and front-desk scheduling each operate from one consistent record.

The system is organized around a flat collection of peer resources — practices, providers, modalities, patients, encounters, procedures, prior authorizations, orthotic prescriptions, lab orders, DME dispenses, imaging orders, referrals, and recalls — all reachable under a single `/podiatry` mount. Rather than nesting child resources beneath their parents in the URL, relationships are carried as foreign-key references inside request bodies and discovered through filtered list endpoints. The guiding design tension this API resolves is compliance: Medicare-style frequency rules for routine foot care, prior-authorization unit draw-downs that must never go negative, payer fee splits computed to the cent, and optimistic concurrency so that two writers acting on a stale view of the same authorization or imaging machine cannot both believe they hold the last available slot.

Because time-dependent rules (authorization validity windows, frequency intervals, recall cadences) pervade the domain, the server runs on a **logical clock** rather than wall-clock time. Every date, window, and expiry decision reads this clock, and an administrative capability lets test harnesses advance it deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes exactly five roles, spelled precisely as `PracticeAdmin`, `Podiatrist`, `BillingSpecialist`, `FrontDesk`, and `PayerAgent`. If either header is absent, or if `X-User-Role` is not one of these five declared roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The five roles partition the work of the practice. A `PracticeAdmin` is an operational identity that provisions the static backbone of the practice — practices, providers, and imaging modalities — and controls the logical clock. A `Podiatrist` is the clinical author who completes exams, adds procedures, writes orthotic prescriptions, orders imaging and referrals, and revises patient risk factors. A `BillingSpecialist` runs the revenue cycle: requesting prior authorizations, coding, recoding, submitting and voiding encounters, and creating, shipping, or cancelling lab orders. A `FrontDesk` operator handles intake and scheduling: registering patients, scheduling encounters, dispensing and returning DME, receiving lab orders, cancelling imaging, and managing recalls. A `PayerAgent` is the payer-side actor who approves or denies authorizations, decides orthotic prescriptions, and adjudicates submitted claims. All five roles may perform any GET (read) operation.

Identity binding differs by role and matters for ownership checks. When `X-User-Role` is `Podiatrist`, `X-User-ID` is the `id` of the acting `Provider`; ownership checks on any resource that references a `Provider` compare the resource's provider foreign key to `X-User-ID`. In particular, completing an exam requires that the acting `Podiatrist`'s `X-User-ID` equal the encounter's `provider_id`. The other four roles — `PracticeAdmin`, `BillingSpecialist`, `FrontDesk`, and `PayerAgent` — carry an opaque operator identifier in `X-User-ID` that is not tied to any persisted entity; the server may accept and record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0.

Unless an endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response carries the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp that is an ISO 8601 UTC instant with three fractional digits. Resources whose attributes can change over their lifetime additionally carry an `updated_at` timestamp (same ISO 8601 UTC format, refreshed on every mutation) and an integer `version` that begins at its initial value and increments by one on every mutation. In this domain all thirteen business entities — `Practice`, `Provider`, `Modality`, `Patient`, `PriorAuthorization`, `Encounter`, `Procedure`, `OrthoticRx`, `LabOrder`, `DmeDispense`, `ImagingOrder`, `Referral`, and `RecallSchedule` — carry the full set of `id`, `created_at`, `updated_at`, and `version`.

The `version` field is the anchor of optimistic concurrency control described in §2.10 and is exposed on every read so a client can capture the value it last observed.

### 2.5. The Logical Clock

The system never reads wall-clock time for any business decision. Instead it maintains a single logical clock that all date, validity-window, expiry, and frequency-window rules consult. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z` and holds that value until it is explicitly moved; it never falls back to real-world time. A `PracticeAdmin` may move the clock to an absolute instant by supplying a `to_iso8601` value, and any role may read the current instant. Whenever this document refers to "the current date" or "at draw time," it means the date component of this logical clock.

### 2.6. Foreign Keys, Path Resolution, and Reverse Reachability

Because the topology is flat, a child resource names its parents through foreign-key fields in its creation body rather than through the URL. Whenever a write supplies a foreign key — `practice_id`, `patient_id`, `provider_id`, `modality_id`, `encounter_id`, `prior_authorization_id`, or `orthotic_rx_id` — the referenced row must exist; a dangling reference is rejected with `ERR_FK_NOT_FOUND` (HTTP 404). For endpoints that address a resource by an `id` in the path, a path identifier that names no existing row is rejected with `ERR_NOT_FOUND` (HTTP 404), and when a path contains more than one identifier they are validated left to right, the first missing one determining the error.

To navigate relationships in the absence of nested URLs, list endpoints accept optional filter query parameters that mirror the foreign keys. Providers, modalities, patients, and prior authorizations are filterable by `practice_id` or `patient_id` respectively; encounters by `patient_id` and/or `provider_id`; procedures by `encounter_id`; orthotic prescriptions by `encounter_id` and/or `prior_authorization_id`; lab orders by `orthotic_rx_id`; DME dispenses by `prior_authorization_id` and/or `encounter_id`; imaging orders by `encounter_id` and/or `modality_id`; referrals by `encounter_id`; and recalls by `patient_id`.

### 2.7. Request Validation

After authentication and authorization, and after foreign-key existence is confirmed, each write endpoint validates its body. Every required field must be present and well-typed, every enum-valued field must hold one of its allowed values, every scheduled interval must have its end strictly after its start (an encounter's `scheduled_end` must be after its `scheduled_start`, and an imaging study's `study_end` must be after its `study_start`), every quantity or unit count (`authorized_units`, `units`, `units_drawn`, and each line item's `quantity`) must be at least 1, every `discount_pct` must lie between 0 and 1 inclusive, and `monthly_rental_cents` must be supplied whenever `acquisition_mode` is `RENTAL`. Any violation of these structural rules is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

### 2.8. Monetary Precision and Rounding

All money is represented in integer cents. Where a calculation must convert a fractional product into cents, the system rounds half up. The half-up rounding applies only where this document explicitly invokes it — most notably to the payer's portion of a covered charge and to each lab-order line — and where a remainder is described as "the rest," that remainder is the exact integer difference and is not independently rounded. Unit counts and day counts are always whole integers; `remaining_units` is floored at zero and never goes negative.

### 2.9. Hierarchical Consistency and Cascades

Many operations mutate more than one resource. When an operation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; this is true of derived-field updates as well as status changes. Several operations additionally cascade into related resources, and in each such case the secondary resource is itself mutated (its own `updated_at` refreshed and `version` incremented). The specific cascades — an encounter adjudication advancing a patient's frequency window, a received lab order fulfilling its prescription, a returned DME dispense or cancelled lab order restoring authorization units and possibly reviving an exhausted authorization, and a voided encounter cancelling its scheduled imaging — are described where the workflows that trigger them appear in §3. The system performs these reconciliations automatically, without the client issuing a separate request against the secondary resource.

### 2.10. Optimistic Concurrency Control

Two write endpoints draw against a shared parent whose state another writer may already have advanced, and both require an optimistic-concurrency token so a client cannot act on a stale view.

When dispensing DME, the request must carry `expected_prior_authorization_version` holding the `version` of the target `PriorAuthorization` that the client last observed. This is a required input, not an optional one. If that value does not match the authorization's current `version` — because an earlier dispense or a compensating return has since drawn down or restored `remaining_units` and bumped the authorization's `version` — the dispense is rejected with `ERR_PA_VERSION_STALE` (HTTP 412). The check runs before any business rule so that a stale view never mutates state, ensuring two independent draws cannot both believe they hold the last unit.

When ordering imaging, the request must carry `expected_modality_version` holding the `version` of the target `Modality` that the client last observed; this too is required. If it does not match the modality's current `version` — because an earlier booking has since occupied an interval and bumped the modality's `version` — the order is rejected with `ERR_MODALITY_VERSION_STALE` (HTTP 412), again evaluated before booking logic so that two studies are never reasoned against an out-of-date view of the machine's occupied intervals. Endpoints other than these two do not accept or require any version field.

### 2.11. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the reported error is deterministic. The order is: first, user-context authentication (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of every path identifier (`ERR_NOT_FOUND`); then existence of every body foreign key (`ERR_FK_NOT_FOUND`); then structural body validation (`ERR_INVALID_REQUEST`); then, on the two OCC-guarded creates, the optimistic-concurrency version check (`ERR_PA_VERSION_STALE` or `ERR_MODALITY_VERSION_STALE`); then the target entity's state legality for the requested transition (`ERR_ENCOUNTER_BAD_STATE` and its analogues on the other lifecycles); then the rendering-provider ownership check on exam completion (`ERR_NOT_RENDERING_PROVIDER`); then the business-referential checks for authorization category match (`ERR_PA_CATEGORY_MISMATCH`) and drawable state (`ERR_PA_NOT_DRAWABLE`); then the temporal checks for authorization expiry (`ERR_PA_EXPIRED`), provider double-booking (`ERR_PROVIDER_DOUBLE_BOOKED`), and modality double-booking (`ERR_MODALITY_DOUBLE_BOOKED`); and finally the unit-budget check (`ERR_PA_UNITS_EXCEEDED`). Earlier checks mask later ones: a request that fails both an existence check and a state check surfaces the existence error.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Practice and Its Resources

A `PracticeAdmin` establishes the static backbone before any clinical work occurs. Creating a practice supplies a `name` and an `npi` (the group's ten-digit National Provider Identifier), and may optionally set two policy levers that otherwise take their defaults: `routine_care_min_interval_days`, the minimum number of days that must elapse between covered routine foot-care procedures, which defaults to 61; and `fee_split_medicare_pct`, the fraction of an allowed amount the payer covers on a covered line, which defaults to 0.80 with the patient owing the rest. These two values are the practice-level constants that the coverage and charge rules in §3.4 read.

Providers are provisioned against a practice with a `practice_id`, a `full_name`, and a `role_type` that is either `PODIATRIST` or `NP_PA`; an optional `is_active` flag (defaulting to true) records whether the provider accepts new encounters. Imaging modalities are likewise provisioned with a `practice_id`, a `name`, a `modality_type` that is one of `XRAY`, `ULTRASOUND`, or `MRI`, and an optional `cleanup_buffer_minutes` (defaulting to 15) that fixes the mandatory idle gap required after each study on that machine before the next may start. A modality's read exposes its `version` precisely so callers can supply the OCC token described in §2.10 when booking against it.

### 3.2. Patient Intake and Diabetic-Foot Risk Stratification

A `FrontDesk` operator registers a patient with a `practice_id`, a `full_name`, and a `date_of_birth` (an ISO date in `YYYY-MM-DD` form), along with five clinical risk booleans that each default to false when omitted: `has_diabetes_mellitus`, `has_loss_protective_sensation`, `has_peripheral_arterial_disease`, `has_foot_deformity`, and `has_prior_ulcer_or_amputation`. Of these, the first records the qualifying systemic condition that gates routine-care coverage, while the latter four feed the risk computation. A newly registered patient has its `last_covered_routine_care_date` set to null, signifying that no covered routine care has yet been adjudicated.

The patient's `diabetic_foot_risk_category` is a derived integer from 0 to 3 computed from four of the risk booleans — loss of protective sensation, peripheral arterial disease, foot deformity, and prior ulcer or amputation — under a fixed precedence in which the highest applicable category wins. If the patient has a prior ulcer or amputation, the category is 3. Otherwise, if the patient has loss of protective sensation and additionally has either peripheral arterial disease or a foot deformity, the category is 2. Otherwise, if the patient has loss of protective sensation, the category is 1. Otherwise the category is 0. This single computation reads only the four booleans on the one patient row and consults no other entity.

A `Podiatrist` may later revise a patient's risk profile by submitting any subset of the same five booleans — `has_diabetes_mellitus`, `has_loss_protective_sensation`, `has_peripheral_arterial_disease`, `has_foot_deformity`, and `has_prior_ulcer_or_amputation`. When risk factors are updated, the `diabetic_foot_risk_category` is recomputed by the same precedence rule and the patient's `version` is incremented. A patient read exposes both the computed `diabetic_foot_risk_category` and the `last_covered_routine_care_date`.

### 3.3. The Encounter Lifecycle: Scheduling Through Adjudication

The `Encounter` is the clinical and billing hub of a visit, and it follows a branching lifecycle with a revert. A `FrontDesk` operator schedules an encounter against a provider by supplying a `patient_id`, a `provider_id`, a `scheduled_start` and `scheduled_end` (ISO 8601 UTC instants, end after start), and the office-visit line's `exam_billed_cents` and `exam_fee_cap_cents` (each a non-negative integer). The encounter begins in `OPEN`, with `exam_coverage_decision` at `PENDING` and both `total_medicare_pays_cents` and `total_patient_resp_cents` at 0. Scheduling enforces a provider's calendar: the new interval, treated as half-open from start up to but not including end, must not overlap any non-`VOIDED` encounter already on the same `provider_id`; two appointments that merely touch at the boundary are allowed, but a genuine overlap is rejected with `ERR_PROVIDER_DOUBLE_BOOKED`.

A `Podiatrist` advances the encounter from `OPEN` to `EXAM_DONE` by completing the exam, but only the rendering provider may do so: the acting podiatrist's `X-User-ID` must equal the encounter's `provider_id`, failing which the request is rejected with `ERR_NOT_RENDERING_PROVIDER`; completing an exam on an encounter not in `OPEN` is rejected with `ERR_ENCOUNTER_BAD_STATE`. No charges are computed at this step. Coding, performed by a `BillingSpecialist`, advances `EXAM_DONE → CODED` and is where all financial computation happens: the exam line's `exam_coverage_decision` is set to `COVERED` (the office visit is always covered), each child procedure's `coverage_decision` is decided per §3.4, each line's payer and patient portions are split per §3.5, and the encounter's `total_medicare_pays_cents` and `total_patient_resp_cents` are recomputed as the sums of the per-line payer and patient amounts across the exam line and all procedures. Coding an encounter not in `EXAM_DONE` is rejected with `ERR_ENCOUNTER_BAD_STATE`.

Should a coding error surface, the same `BillingSpecialist` can recode, reverting `CODED → EXAM_DONE`: this resets the exam's `exam_coverage_decision` back to `PENDING`, every child procedure's `coverage_decision` back to `PENDING`, every per-line `medicare_pays_cents` and `patient_resp_cents` to 0, and the encounter's two totals to 0, leaving the encounter ready to be corrected and re-coded. Recoding an encounter not in `CODED` is rejected with `ERR_ENCOUNTER_BAD_STATE`. From `CODED`, the billing specialist submits the claim, advancing `CODED → SUBMITTED`; submitting from any other state is rejected with `ERR_ENCOUNTER_BAD_STATE`.

A `PayerAgent` adjudicates a submitted claim, advancing `SUBMITTED → ADJUDICATED`, which is terminal; adjudicating from any other state is rejected with `ERR_ENCOUNTER_BAD_STATE`. Adjudication is the moment the patient's frequency window advances: for each child procedure that is routine and was decided `COVERED`, the patient's `last_covered_routine_care_date` is set to the later of its existing value and that procedure's `service_date`. This patient mutation increments the patient's `version`, and because the frequency window is read at coding time (see §3.4), advancing it here means any future encounter coded afterward sees the new last-covered date.

Finally, a `BillingSpecialist` may void an encounter that is in `OPEN`, `EXAM_DONE`, or `CODED` (a void from any other state — for example a `SUBMITTED` or already-`ADJUDICATED` encounter — is rejected with `ERR_ENCOUNTER_BAD_STATE`). Voiding moves the encounter to `VOIDED` (terminal), resets all per-line and encounter-level charge fields to 0 and all coverage decisions to `PENDING`, and as a cascade cancels any child imaging order still in `SCHEDULED` — moving each such `ImagingOrder` to `CANCELLED` and thereby freeing the modality interval it held.

### 3.4. Coverage Decisions and the Medicare Frequency Rule

Procedure lines are added by a `Podiatrist` to an encounter that is still `OPEN` or `EXAM_DONE`. Each `Procedure` supplies an `encounter_id`, a `procedure_kind`, a `service_date` (the ISO date the work was performed), and the line's `billed_cents` and `fee_cap_cents`. On creation the owning `patient_id` is copied from the encounter, the `coverage_decision` starts at `PENDING`, and a derived `is_routine` flag is set true exactly when `procedure_kind` is one of `ROUTINE_NAIL_DEBRIDEMENT` or `ROUTINE_CALLUS_PARING`. The other two kinds, `WOUND_DEBRIDEMENT` and `NAIL_AVULSION`, are non-routine.

Coverage is decided per procedure at coding time. A non-routine procedure is always `COVERED`. A routine procedure must clear two independent gates. First, if the patient does not have diabetes mellitus, the procedure is `DENIED_NO_QUALIFYING_DX` — routine foot care requires the qualifying systemic condition. Second, if the patient does have diabetes mellitus, the frequency window is checked: if the patient's `last_covered_routine_care_date` is null (no prior covered routine care), the procedure is eligible and `COVERED`; otherwise the gap in whole calendar days from that last covered date to the procedure's `service_date` is computed, and the procedure is `COVERED` when that gap is at least the practice's `routine_care_min_interval_days` and `DENIED_FREQUENCY` when the gap is strictly less. The boundary is inclusive: a gap exactly equal to the minimum interval is covered.

Two subtleties govern this rule. The `last_covered_routine_care_date` consulted is the value as of coding time, and it only advances at adjudication (see §3.3); consequently, coding two routine procedures within the same not-yet-adjudicated encounter evaluates both against the same pre-encounter last-covered date. And the two outcomes for a diabetic patient are genuinely different results on the same metric: when the window is satisfied the systemic-condition coverage path makes the line `COVERED`, but when the gap falls short the very same patient and diagnosis yield `DENIED_FREQUENCY` purely because the temporal window blocks it — in which case, per §3.5, the full billed amount becomes the patient's responsibility. A read of a procedure exposes its `coverage_decision`, its `is_routine` flag, and its per-line `medicare_pays_cents` and `patient_resp_cents`.

### 3.5. Charge Splitting

Once coverage is decided, each line — the exam line and every procedure line — is split into a payer portion and a patient portion in a pinned order that deliberately breaks the circular dependency between coverage and charge. The coverage decision is settled first (by §3.4 for procedures; the exam line is always `COVERED`). Next, the allowed amount for the line is the lesser of its billed amount and its fee-schedule cap — for a procedure that is the lesser of `billed_cents` and `fee_cap_cents`, and for the exam line the lesser of `exam_billed_cents` and `exam_fee_cap_cents`. Then the split depends on coverage. For a `COVERED` line, the payer portion (`medicare_pays_cents`) is the allowed amount multiplied by the practice's `fee_split_medicare_pct`, rounded half up to whole cents, and the patient portion (`patient_resp_cents`) is the exact remainder — the allowed amount minus the payer portion. For a line denied under either `DENIED_FREQUENCY` or `DENIED_NO_QUALIFYING_DX`, the payer portion is 0 and the patient portion is the full billed amount of the line, uncapped — that is, the billed amount itself rather than the allowed amount. The encounter totals are then the sum of the payer portions across all lines and the sum of the patient portions across all lines.

### 3.6. Prior Authorizations and Unit Draw-Downs

A `BillingSpecialist` requests a prior authorization for a patient by supplying a `patient_id`, a `service_category` that is one of `DME`, `ORTHOTIC`, or `IMAGING`, an `hcpcs_code` (the authorized HCPCS or L-code), an `authorized_units` count of at least 1, and a `valid_from_date` and `valid_through_date` (inclusive ISO-date bounds of the window during which the authorization may be used). The authorization is created in `REQUESTED` with `units_consumed` at 0 and `remaining_units` equal to `authorized_units`. A `PayerAgent` either approves it, advancing `REQUESTED → APPROVED` (initializing `units_consumed` to 0 and `remaining_units` to `authorized_units`), or denies it, advancing `REQUESTED → DENIED` (terminal). Approving or denying an authorization that is not in `REQUESTED` is rejected with `ERR_PA_BAD_STATE`. A read exposes `units_consumed`, `remaining_units`, `version`, and `status`.

Only an `APPROVED` authorization is drawable. Whenever a DME dispense or a lab order draws against an authorization, the draw quantity is added to `units_consumed` and `remaining_units` is recomputed as `authorized_units` minus `units_consumed`; if `remaining_units` reaches exactly 0, the authorization automatically transitions `APPROVED → EXHAUSTED` and accepts no further draws. A draw whose quantity exceeds the current `remaining_units` is rejected with `ERR_PA_UNITS_EXCEEDED`, and an attempt to draw against an authorization that is not `APPROVED` — whether `REQUESTED`, `DENIED`, or already `EXHAUSTED` — is rejected with `ERR_PA_NOT_DRAWABLE`. Expiry is evaluated at draw time against the logical clock: when the current logical date is past the `valid_through_date`, the authorization automatically transitions `APPROVED → EXPIRED` (terminal) and the attempted draw is rejected with `ERR_PA_EXPIRED`. The system maintains the invariant that, at all times, `units_consumed` equals the sum of `units` over all non-reversed DME dispenses plus the sum of `units_drawn` over all non-cancelled lab orders linked to the authorization, and `remaining_units` equals `authorized_units` minus `units_consumed`, never falling below 0.

Reversals restore units. When a DME dispense is returned or a lab order is cancelled, its draw quantity is subtracted from `units_consumed` and `remaining_units` is recomputed; and if the authorization had been `EXHAUSTED` and `remaining_units` thereby becomes greater than 0, the authorization is revived `EXHAUSTED → APPROVED`. The specific draw and restore amounts and their version effects are detailed in the DME and lab-order workflows below.

### 3.7. Orthotic Prescriptions and the Fabrication Lab

The orthotic pathway runs from a clinical prescription through payer review and into a fabrication lab, with a cyclic revision loop. A `Podiatrist` creates an `OrthoticRx` against an encounter by supplying an `encounter_id`, the `prior_authorization_id` of the `ORTHOTIC`-category authorization the prescription will draw against, an `l_code` (for example L3000 or L3020), and a `foot_side` of `LEFT`, `RIGHT`, or `BILATERAL`. The owning `patient_id` is copied from the encounter and the prescription starts in `DRAFT`.

The podiatrist submits the draft to the payer, advancing `DRAFT → PENDING_PA`; this requires the prescription to be in `DRAFT` (else `ERR_RX_BAD_STATE`) and the linked authorization's `service_category` to be `ORTHOTIC` (else `ERR_PA_CATEGORY_MISMATCH`). A `PayerAgent` then renders a decision carrying a `decision` value. When the decision is to approve, the prescription advances `PENDING_PA → APPROVED`, which additionally requires the linked authorization to be in `APPROVED` (else `ERR_PA_NOT_DRAWABLE`); when the decision is to revise, the prescription cycles back `PENDING_PA → DRAFT`, where it may be edited and resubmitted. Either decision requires the prescription to be in `PENDING_PA`, else `ERR_RX_BAD_STATE`. A `Podiatrist` may cancel an `APPROVED` prescription, advancing `APPROVED → CANCELLED` (terminal), but only when no lab order for that prescription is in `SHIPPED` or `RECEIVED`; a cancel attempt that is blocked by such a lab order, or that targets a prescription not in `APPROVED`, is rejected with `ERR_RX_BAD_STATE`.

A `BillingSpecialist` creates a fabrication `LabOrder` by supplying an `orthotic_rx_id`, a `lab_name`, a `line_items` array, and a `units_drawn` count of at least 1. Each element of `line_items` is an object with a `description`, an `l_code`, a `unit_price_cents` integer, a `quantity` integer of at least 1, and a `discount_pct` between 0 and 1. The lab order's `total_cents` is computed with a pinned rounding order — round each line, then sum — rather than summing then rounding: for each line item, the raw line charge is its `unit_price_cents` multiplied by its `quantity` multiplied by one minus its `discount_pct`, that raw line is rounded half up to whole cents, and the rounded line cents are accumulated into the running total, which becomes `total_cents`. Rounding each line before summing can differ from rounding the sum when two half-cent fractions both round up. Creating a lab order draws `units_drawn` from the prescription's linked authorization and is subject to the authorization rules of §3.6 applied to that linked authorization: the category must be `ORTHOTIC` (else `ERR_PA_CATEGORY_MISMATCH`), the authorization must be drawable (else `ERR_PA_NOT_DRAWABLE`), within its window (else `ERR_PA_EXPIRED`), and have enough remaining units (else `ERR_PA_UNITS_EXCEEDED`); a successful draw may auto-exhaust the authorization. The lab order starts in `QUEUED`.

The lab order then moves through fabrication. A `BillingSpecialist` ships it, advancing `QUEUED → SHIPPED`; a `FrontDesk` operator receives it, advancing `SHIPPED → RECEIVED`. Receiving cascades up: the parent `OrthoticRx` is bubbled to `FULFILLED`, which is terminal. A `BillingSpecialist` may instead cancel a still-`QUEUED` lab order, advancing `QUEUED → CANCELLED` (terminal); cancellation compensates the authorization by subtracting the lab order's `units_drawn` from `units_consumed`, recomputing `remaining_units`, and — if the authorization was `EXHAUSTED` and `remaining_units` becomes greater than 0 — reviving it to `APPROVED`. Any ship, receive, or cancel attempted from an illegal state is rejected with `ERR_LAB_ORDER_BAD_STATE`. A read of a lab order exposes its `total_cents`.

### 3.8. DME Dispensing and Rent-to-Own Charges

A `FrontDesk` operator dispenses durable medical equipment against a `DME`-category authorization. The dispense supplies a `prior_authorization_id`, an `encounter_id`, an `hcpcs_code` (the dispensed boot or brace L-code), an `acquisition_mode` of `PURCHASE` or `RENTAL`, a `units` count of at least 1, a `purchase_price_cents` (the full purchase price for one unit), an optional `monthly_rental_cents` that is required when `acquisition_mode` is `RENTAL`, and the `expected_prior_authorization_version` OCC token described in §2.10. On creation the owning `patient_id` is copied from the encounter and the dispense starts in `DISPENSED`. As with all draws, the linked authorization's category must be `DME` (else `ERR_PA_CATEGORY_MISMATCH`), it must be drawable (else `ERR_PA_NOT_DRAWABLE`), within its window (else `ERR_PA_EXPIRED`), and have at least `units` remaining (else `ERR_PA_UNITS_EXCEEDED`). A successful dispense draws `units` from the authorization, increments the authorization's `version`, and may auto-exhaust it.

The dispense's `this_period_charge_cents` follows a rent-to-own waterfall, and the running `cumulative_rental_paid_cents` records the total charged to date for the device line. For a `PURCHASE`, `this_period_charge_cents` and `cumulative_rental_paid_cents` are both the full `purchase_price_cents`. For a `RENTAL`, the prior cumulative contribution is the sum of the charges of all earlier `RENTAL` dispenses for the same `hcpcs_code` under the same authorization, taken in chronological order by `created_at` ascending; the remaining amount to the cap is `purchase_price_cents` minus that prior cumulative. If the remaining amount to the cap is zero or less, `this_period_charge_cents` is 0; otherwise it is the lesser of `monthly_rental_cents` and the remaining amount to the cap. The new `cumulative_rental_paid_cents` is the prior cumulative plus `this_period_charge_cents`. This guarantees that rental charges never make the cumulative exceed the purchase price — once the renter has paid in the full purchase price across periods, further rental periods charge nothing.

A `FrontDesk` operator may return a dispensed device, advancing `DISPENSED → RETURNED`; for a `PURCHASE` the `DISPENSED` state is otherwise terminal. A return from any state other than `DISPENSED` is rejected with `ERR_DME_BAD_STATE`. Returning compensates the authorization: the dispense's `units` are subtracted from `units_consumed`, `remaining_units` is recomputed, the authorization's `version` is incremented, and if the authorization had been `EXHAUSTED` and `remaining_units` becomes greater than 0 it is revived to `APPROVED`.

### 3.9. Imaging Orders and Modality Scheduling

A `Podiatrist` orders an imaging study by supplying an `encounter_id`, the `modality_id` of the machine, a `study_start` and `study_end` (ISO 8601 UTC, end after start), and the `expected_modality_version` OCC token described in §2.10. The owning `patient_id` is copied from the encounter and the order starts in `SCHEDULED`; a successful booking increments the modality's `version`. The machine's calendar is enforced with a buffer: the new study's interval, expanded by the modality's `cleanup_buffer_minutes` added after its end, must not overlap the buffered interval of any non-`CANCELLED` study already on the same `modality_id`. Because the buffer extends each study's footprint, two studies that would otherwise abut must be separated by at least the cleanup buffer; an overlap of the buffered intervals is rejected with `ERR_MODALITY_DOUBLE_BOOKED`.

A `Podiatrist` completes a study, advancing `SCHEDULED → COMPLETED` (terminal). A `FrontDesk` operator cancels a scheduled study, advancing `SCHEDULED → CANCELLED` (terminal), which frees the modality interval the study held. Completing or cancelling a study not in `SCHEDULED` is rejected with `ERR_IMAGING_BAD_STATE`. As noted in §3.3, voiding the parent encounter also cancels any of its still-`SCHEDULED` imaging orders.

### 3.10. Referrals and Recall Scheduling

A `Podiatrist` creates a referral record from an encounter by supplying an `encounter_id`, a `specialty` of `VASCULAR`, `ENDOCRINOLOGY`, `ORTHOPEDIC_SURGERY`, or `WOUND_CARE`, and a free-text `reason`. The owning `patient_id` is copied from the encounter and the referral is created directly in `SENT`, which is terminal — the referral is an informational record with no further transitions.

A `FrontDesk` operator queues a recall for a patient by supplying a `patient_id` and an `anchor_date` (the ISO date the recall cadence is measured from, typically the encounter's service date). The recall's `interval_days` is derived from the patient's `diabetic_foot_risk_category` as snapshotted at creation time — category 0 yields 365 days, category 1 yields 180 days, category 2 yields 90 days, and category 3 yields 30 days — and the `due_date` is the `anchor_date` advanced by `interval_days` whole calendar days. This snapshot is deliberate: a recall is not re-derived if the patient's risk category later changes. The recall starts in `PENDING`, and a read exposes both `interval_days` and `due_date`. A `FrontDesk` operator may complete a pending recall, advancing `PENDING → COMPLETED` (terminal), or cancel it, advancing `PENDING → CANCELLED` (terminal); completing or cancelling a recall not in `PENDING` is rejected with `ERR_RECALL_BAD_STATE`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that read, or that modify an existing resource (including all lifecycle transitions and the logical-clock control), return `200 OK`. The request and response bodies for each operation are not restated here; reconstruct them from the workflow narratives in §3 and the field and validation rules in §2. In the Authorized Role(s) column, "All roles" means all five of `PracticeAdmin`, `Podiatrist`, `BillingSpecialist`, `FrontDesk`, and `PayerAgent`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock to an absolute instant | PracticeAdmin |
| GET | `/_clock` | Read the current logical clock instant | All roles |
| POST | `/podiatry/practices` | Create a practice | PracticeAdmin |
| GET | `/podiatry/practices/{practiceId}` | Get a practice | All roles |
| POST | `/podiatry/providers` | Create a provider | PracticeAdmin |
| GET | `/podiatry/providers` | List providers, filterable by `practice_id` | All roles |
| GET | `/podiatry/providers/{providerId}` | Get a provider | All roles |
| POST | `/podiatry/modalities` | Create an imaging modality | PracticeAdmin |
| GET | `/podiatry/modalities` | List modalities, filterable by `practice_id` | All roles |
| GET | `/podiatry/modalities/{modalityId}` | Get a modality | All roles |
| POST | `/podiatry/patients` | Register a patient | FrontDesk |
| GET | `/podiatry/patients` | List patients, filterable by `practice_id` | All roles |
| GET | `/podiatry/patients/{patientId}` | Get a patient | All roles |
| PATCH | `/podiatry/patients/{patientId}/risk-factors` | Update a patient's risk factors | Podiatrist |
| POST | `/podiatry/prior-authorizations` | Request a prior authorization | BillingSpecialist |
| GET | `/podiatry/prior-authorizations` | List prior authorizations, filterable by `patient_id` | All roles |
| GET | `/podiatry/prior-authorizations/{paId}` | Get a prior authorization | All roles |
| POST | `/podiatry/prior-authorizations/{paId}/approve` | Approve a prior authorization | PayerAgent |
| POST | `/podiatry/prior-authorizations/{paId}/deny` | Deny a prior authorization | PayerAgent |
| POST | `/podiatry/encounters` | Schedule an encounter | FrontDesk |
| GET | `/podiatry/encounters` | List encounters, filterable by `patient_id` and/or `provider_id` | All roles |
| GET | `/podiatry/encounters/{encounterId}` | Get an encounter | All roles |
| POST | `/podiatry/encounters/{encounterId}/complete-exam` | Complete the exam | Podiatrist |
| POST | `/podiatry/encounters/{encounterId}/code` | Code the encounter | BillingSpecialist |
| POST | `/podiatry/encounters/{encounterId}/recode` | Revert a coded encounter for correction | BillingSpecialist |
| POST | `/podiatry/encounters/{encounterId}/submit` | Submit the coded claim | BillingSpecialist |
| POST | `/podiatry/encounters/{encounterId}/adjudicate` | Adjudicate the claim | PayerAgent |
| POST | `/podiatry/encounters/{encounterId}/void` | Void the encounter | BillingSpecialist |
| POST | `/podiatry/procedures` | Add a procedure line to an encounter | Podiatrist |
| GET | `/podiatry/procedures` | List procedures, filterable by `encounter_id` | All roles |
| GET | `/podiatry/procedures/{procedureId}` | Get a procedure | All roles |
| POST | `/podiatry/orthotic-rxs` | Create an orthotic prescription | Podiatrist |
| GET | `/podiatry/orthotic-rxs` | List orthotic Rxs, filterable by `encounter_id` and/or `prior_authorization_id` | All roles |
| GET | `/podiatry/orthotic-rxs/{rxId}` | Get an orthotic Rx | All roles |
| POST | `/podiatry/orthotic-rxs/{rxId}/submit-to-payer` | Submit an orthotic Rx for payer review | Podiatrist |
| POST | `/podiatry/orthotic-rxs/{rxId}/payer-decision` | Approve or revise an orthotic Rx | PayerAgent |
| POST | `/podiatry/orthotic-rxs/{rxId}/cancel` | Cancel an approved orthotic Rx | Podiatrist |
| POST | `/podiatry/lab-orders` | Create a fabrication lab order | BillingSpecialist |
| GET | `/podiatry/lab-orders` | List lab orders, filterable by `orthotic_rx_id` | All roles |
| GET | `/podiatry/lab-orders/{labOrderId}` | Get a lab order | All roles |
| POST | `/podiatry/lab-orders/{labOrderId}/ship` | Ship a lab order | BillingSpecialist |
| POST | `/podiatry/lab-orders/{labOrderId}/receive` | Receive a lab order | FrontDesk |
| POST | `/podiatry/lab-orders/{labOrderId}/cancel` | Cancel a queued lab order | BillingSpecialist |
| POST | `/podiatry/dme-dispenses` | Dispense DME against a prior authorization | FrontDesk |
| GET | `/podiatry/dme-dispenses` | List DME dispenses, filterable by `prior_authorization_id` and/or `encounter_id` | All roles |
| GET | `/podiatry/dme-dispenses/{dispenseId}` | Get a DME dispense | All roles |
| POST | `/podiatry/dme-dispenses/{dispenseId}/return` | Return a dispensed DME | FrontDesk |
| POST | `/podiatry/imaging-orders` | Order imaging on a modality | Podiatrist |
| GET | `/podiatry/imaging-orders` | List imaging orders, filterable by `encounter_id` and/or `modality_id` | All roles |
| GET | `/podiatry/imaging-orders/{imagingOrderId}` | Get an imaging order | All roles |
| POST | `/podiatry/imaging-orders/{imagingOrderId}/complete` | Complete an imaging study | Podiatrist |
| POST | `/podiatry/imaging-orders/{imagingOrderId}/cancel` | Cancel a scheduled imaging study | FrontDesk |
| POST | `/podiatry/referrals` | Create a referral record | Podiatrist |
| GET | `/podiatry/referrals` | List referrals, filterable by `encounter_id` | All roles |
| GET | `/podiatry/referrals/{referralId}` | Get a referral | All roles |
| POST | `/podiatry/recalls` | Queue a recall for a patient | FrontDesk |
| GET | `/podiatry/recalls` | List recalls, filterable by `patient_id` | All roles |
| GET | `/podiatry/recalls/{recallId}` | Get a recall | All roles |
| POST | `/podiatry/recalls/{recallId}/complete` | Complete a recall | FrontDesk |
| POST | `/podiatry/recalls/{recallId}/cancel` | Cancel a recall | FrontDesk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_NOT_RENDERING_PROVIDER` | 403 Forbidden |
| `ERR_ENCOUNTER_BAD_STATE` | 409 Conflict |
| `ERR_PA_BAD_STATE` | 409 Conflict |
| `ERR_RX_BAD_STATE` | 409 Conflict |
| `ERR_LAB_ORDER_BAD_STATE` | 409 Conflict |
| `ERR_DME_BAD_STATE` | 409 Conflict |
| `ERR_IMAGING_BAD_STATE` | 409 Conflict |
| `ERR_RECALL_BAD_STATE` | 409 Conflict |
| `ERR_PA_CATEGORY_MISMATCH` | 409 Conflict |
| `ERR_PA_NOT_DRAWABLE` | 409 Conflict |
| `ERR_PA_EXPIRED` | 409 Conflict |
| `ERR_PA_UNITS_EXCEEDED` | 409 Conflict |
| `ERR_PROVIDER_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_MODALITY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_PA_VERSION_STALE` | 412 Precondition Failed |
| `ERR_MODALITY_VERSION_STALE` | 412 Precondition Failed |

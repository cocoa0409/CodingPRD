# Pet Hospital API — Product Requirements Document

## 1. Introduction

A working pet hospital is a knot of independent workflows that nonetheless share the same animal, the same owner, and the same money. A triage nurse routes a panicked owner and pet through symptom intake; a vet later writes a treatment plan and orders labs; a senior reviewer approves controlled-drug prescriptions; a pharmacist dispenses; the cashier reconciles deposits, package discounts, insurance, and refunds; and somewhere alongside all of it a vaccine-recall notice can arrive that retroactively requalifies a pet's next-due dose. Each of those threads must remain auditable on its own and consistent with the others — a recalled vaccine batch cannot leave a stale "due in 90 days" reminder, a dispensed drug cannot leave a bill that still says "issued", and a controlled-drug prescription cannot leave the building unless the prescribing and reviewing vets are different people.

This document specifies the REST API that ties those threads together. The API serves seven role types — front-desk triage nurses, drafting and reviewing veterinarians, pharmacists, cashiers, owner-service operators, and a platform-admin role for catalog and event ingestion — over a single resource graph rooted in the visit. The system is event-aware: external lab results, payments, refund confirmations, IM-bridge notifications, and vaccine-batch recalls all enter through dedicated event endpoints with idempotency keys, so the same external event delivered twice never produces a double write. Above all, the API is opinionated about ordering: a visit is registered before it is triaged, triaged before consultation, finalized before billing, paid before invoiced, and closed only after every loose prescription and bill are themselves finalized. The sections below specify those orderings precisely and the side effects each transition must produce.

All endpoints are mounted under `/pet-hospital`.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` (the caller's stable identifier) and `X-User-Role` (one of the role names below). If either header is missing or blank the request is rejected with `ERR_AUTH_MISSING`. If `X-User-Role` is present but does not match one of the recognized role names, the request is rejected with `ERR_AUTH_INVALID_ROLE`. If the role is recognized but is not authorized for the endpoint per the role-to-endpoint mapping in §4, the request is rejected with `ERR_FORBIDDEN`.

The seven recognized roles are `TriageNurse`, `DraftingVet`, `ReviewingVet`, `Pharmacist`, `Cashier`, `OwnerService`, and `PlatformAdmin`. Each is described briefly below; for each, `X-User-ID` is treated as an **opaque operator identifier** that the server may persist on audit-log entries and on prescription/visit records but does not compare against any entity's `id` for ownership purposes — the role-to-endpoint mapping alone determines access.

- `TriageNurse` — front-desk staff who register pets, run triage and re-triage, cancel visits before clinical work begins, and collect lab samples.
- `DraftingVet` — veterinarians who diagnose, draft and finalize treatment records, draft and amend prescriptions, manage lab orders, and run hospitalization care.
- `ReviewingVet` — senior veterinarians who approve or reject prescriptions; for any prescription containing at least one item that references a controlled drug, the `ReviewingVet` whose `X-User-ID` is recorded on approval must differ from the `drafting_vet_id` already recorded on the prescription.
- `Pharmacist` — dispenses approved prescriptions and adjusts drug stock or interaction tables.
- `Cashier` — manages bills, deposits, payments, refunds, invoices, visit closure, and discharge.
- `OwnerService` — owner-side customer-service operator who manages owner records, contact-verification flows, and reads visit history on behalf of an owner.
- `PlatformAdmin` — system operator with rights to manage the drug catalog, vaccine schedules, and cages, query the audit log, ingest external events (payment, refund-confirm, external-lab-result, vaccine-batch-recall, IM emit), and advance the test clock.

Several entities carry operator-identity fields whose values come directly from `X-User-ID`. `Visit.assigned_vet_id` is set by triage routing and matched against `X-User-ID` whenever a `DraftingVet` action is taken on the visit. `Prescription.drafting_vet_id` is recorded at draft creation from the caller's `X-User-ID`; `Prescription.reviewing_vet_id` is recorded at approval or rejection. `AuditLog.actor_role` and `AuditLog.actor_id` capture the headers of the action that produced the entry. None of these fields is compared to a stored user record.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, the maximum is 100. The default `offset` is 0. Results are sorted by `created_at` in ascending order unless an endpoint description in §3 specifies otherwise (the per-pet visit history list, for example, returns visits newest first). The pagination block in `meta` exposes four fields — `limit`, `offset`, `total_count`, and `has_more` — where `total_count` is the absolute count of matching rows server-side and `has_more` is true when `offset + limit` is less than `total_count`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Most resources — `Owner`, `Pet`, `Visit`, `TreatmentRecord`, `LabReport`, `Drug`, `Prescription`, `Cage`, `Hospitalization`, and `Bill` — carry four system-managed fields in addition to their domain attributes. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` timestamps are ISO 8601 UTC with three fractional digits; `created_at` is set on resource creation and never changed, `updated_at` is refreshed on every successful mutation. The `version` field is an integer that starts at 1 on creation and increments by exactly 1 on every successful mutation, including state-machine transitions and cascade-driven mutations.

Three entities are deliberately lighter and do **not** carry `updated_at` or `version`: a `VaccineSchedule` row, a `VaccinationRecord`, and an `AuditLog` entry each carry only `id` and `created_at`. Vaccination records mutate only by status flip (the `status` field can become `RECALLED` or `SUPERSEDED`); audit-log entries are append-only and never mutate; vaccine-schedule rows are administrative configuration. None of the three participates in optimistic concurrency.

For the entities that do carry `version`, the optimistic-concurrency mechanism works as follows. Mutation endpoints that accept a `version` field in the request body — most prominently `PATCH /treatment-records/{tr_id}`, `PATCH /pets/{pet_id}`, and `PATCH /drugs/{drug_id}` — compare the supplied `version` to the current entity's `version`. A mismatch is rejected with `ERR_STALE_VERSION`. When the request body omits `version`, the OCC check is skipped and the mutation proceeds without it. The `version` field is also incremented on cascade-driven mutations: when a hospitalization discharge appends `HOSPITAL_DAY` line items to a bill, both the hospitalization and the bill have their `version` incremented and `updated_at` refreshed.

### 2.5. Nested Resource Path Validation

Several endpoints take more than one path parameter — for instance the per-pet visit-creation, visit-history, vaccinations, and vaccine-due endpoints. Path parameters are validated **left to right**. A request to a path of the form `/pets/{pet_id}/visits` first verifies that `pet_id` resolves to an existing `Pet`; if it does not, the response is `ERR_NOT_FOUND` with no further checking of the inner segment. Only after the outer reference resolves is the inner resource looked up. This ordering also governs `ERR_REFERENCE_NOT_FOUND`: foreign keys named in the request body — `owner_id`, `visit_id`, `drug_code`, `cage_id`, and similar — are verified after path parameters. A request-body FK that fails to resolve produces `ERR_REFERENCE_NOT_FOUND` with HTTP 422.

### 2.6. Validation Priority Order

When several validation categories could fire on the same request, the server evaluates them in a fixed order so that the response is deterministic. Authentication runs first: missing headers, then unrecognized role, then RBAC denial. Existence checks run next: path parameters left-to-right, then body-level foreign keys. State-machine admissibility runs after that — a transition rejected because the entity is in the wrong state surfaces `ERR_INVALID_STATE` before any business-safety check on the same request. OCC version comparison sits at the same priority tier as state admissibility (priority 11) and is applied where the endpoint accepts `version`. Business-safety checks come after state and OCC: archived-pet protection on visit creation, owner-contact verification on triage and prescription submit, segregation-of-duties on prescription approval, dosage-rationality on prescription submission and approval, severe-interaction blocking on approval. Business-referential checks then enforce cross-entity invariants such as visit-state requirements on treatment-record and lab-report transitions, the "no open prescriptions when closing or discharging" rule, and the lab-items shape rule. Business-constraint and business-temporal checks (cage capacity, vaccine age-min, vaccine cooldown, batch recall, cage overlap) follow. Business-fiscal checks (admission-hold deposit floor, refund-cap rule) sit at the last business tier. Generic schema/format errors on individual fields surface as `ERR_VALIDATION_FAILED` and are treated as low-priority structural errors that fire only when no higher-tier check applies.

### 2.7. Hierarchical Consistency, Cascades, and Audit

Side effects of a state transition or mutation always fan out within the same logical request. When a treatment record transitions from `DRAFT` to `FINALIZED`, three things happen in order: a snapshot containing the `visit_id`, the `diagnosis_code`, and the finalization timestamp is appended to the corresponding `Pet.medical_history` array; a `CONSULT` line item is appended to the bill for the visit, which forces a recompute of `provisional_total_cents`; and a `FINALIZE` audit-log entry is written with `subject_type` of `TREATMENT_RECORD`. When a prescription is dispensed, drug stock is decremented per item, `dispensed_at` is set, a `DRUG` line item is appended to the visit's bill, and — if the bill was in `ISSUED` status — the bill drops back to `DRAFT` so it can be re-issued with the new line. When a hospitalization is discharged, `discharged_at` is set, the cage's `occupancy_count` is decremented by 1, and one `HOSPITAL_DAY` line item is appended per calendar day spanned between admission and discharge. When a vaccine batch recall arrives, every matching `ACTIVE` `VaccinationRecord` flips to `RECALLED`, every affected pet's vaccine-due list is recomputed under the post-recall variant, and an outbound IM-bridge emission is generated.

Mutations that carry `version` increment the affected entity's `version` and refresh `updated_at` on success. Cascade-driven mutations follow the same rule: the bill mutated as a side effect of a dispense gets its `version` bumped; the cage mutated as a side effect of a discharge gets its `version` bumped; and the pet whose `medical_history` is appended on treatment-record finalize gets its `version` bumped. Audit-log entries themselves do not carry `version` (they are append-only) but they record the `from_state` and `to_state` of the action they describe along with a `payload_hash` that captures the relevant fields at the time of the event.

### 2.8. Money, Precision, and Rounding

All monetary amounts are integer cents. Bill arithmetic uses the half-up rounding mode at every phase, and the same amount is never rounded twice. The provisional and final bill totals are computed in pinned phases: per-line totals first (the per-line `line_total_cents` is the line `qty` multiplied by its `unit_price_cents`, rounded half-up), then the gross of all line totals, then any package discount applied as a percentage of the gross with the discount itself rounded half-up to whole cents, then the deposit subtraction, then the insurance subtraction. The package-discount percentage is selected from a tier table keyed on the **gross before discount** — never on the discounted total — and the path of re-running the tier selection against the post-discount value is forbidden. Triage scoring rounds to 1 decimal place using half-up. Vaccine-due dates are computed in whole days; a due date that equals "today" is considered overdue.

### 2.9. Sorting, Idempotency, and Determinism

External event endpoints — payment, refund-confirm, external-lab-result, vaccine-batch-recall — are idempotent on their declared idempotency key (`event_id` for payments, refunds, and vaccine recalls; `external_lab_ref` for lab-result callbacks). A duplicate delivery is a no-op: the second arrival returns 200 with the same response body and writes nothing further. List endpoints default to `created_at` ascending; the per-pet visit-history list is the documented exception (newest first). Where business logic requires a deterministic tie-break — for example, the vet selector at triage time, or the abnormal-codes ordering on a finalized lab report — the rule is spelled out in the §3 narrative for the relevant workflow.

## 3. Business Logic & Workflows

### 3.1. Owner Onboarding, Contact Verification, and Deposits

An owner is created through a creation request handled by `OwnerService` or `PlatformAdmin`. The body carries the owner's `full_name` (1 to 80 characters, non-empty after trim), a `phone_e164` value matching the international E.164 format (a leading `+`, then between 7 and 15 digits, with the first digit non-zero) and unique per owner, and an `email` (RFC-5322 lite, lowercased, unique per owner). The `contact_verified` flag defaults to false on creation, the `verification_code_hash` defaults to null, the `verification_expires_at` defaults to null, and the `deposit_balance_cents` defaults to 0.

Contact verification is a two-step flow. The owner-service operator first issues a verification code by calling the issue-verification action; this operation generates a system-generated code, stores its hash in `verification_code_hash`, and sets `verification_expires_at` to ten minutes after the issue time. The operator then submits the code through the verify-contact action, passing the cleartext `code` in the body. On a successful match the system flips `contact_verified` to true, clears `verification_code_hash` to null, and clears `verification_expires_at` to null.

A `Cashier` may top up an owner's deposit balance by calling the deposit endpoint with an `amount_cents` value; the call increments `deposit_balance_cents` by that amount. The deposit balance is the running prepaid pool across all of the owner's open visits. It is decremented at hospitalization-admission time (the admission hold) and at bill-issue time (deposit applied to the issued bill). Both decrements are restored on the corresponding cancel/refund pathways described elsewhere.

### 3.2. Pet Records, Soft Delete, and Visit History

A pet is created with an `owner_id` that must reference an existing owner and that cannot be reassigned later, a `name` (1 to 60 characters), a `species` chosen from `DOG`, `CAT`, `RABBIT`, `BIRD`, or `OTHER`, a `birth_date` (ISO 8601 date, no later than the current UTC date), and a `weight_kg` of at least 0.05 kilograms and no more than 200 kilograms with up to two decimal places. The `medical_history` array starts empty and is appended to (in chronological order of finalization) every time one of the pet's treatment records transitions from `DRAFT` to `FINALIZED`. The `archived` flag starts at false.

The pet update action accepts an optional `weight_kg`, an optional `name`, and an optional `version` for the OCC check; only the fields supplied in the body are mutated. The pet delete action is a soft delete restricted to `PlatformAdmin`: it sets `archived` to true. An archived pet cannot start a new visit (any attempt is rejected with `ERR_PET_ARCHIVED`), but it remains queryable for read endpoints and for visit-history listing. The visit-history listing for a pet returns the pet's visits newest-first and is paginated by `limit` and `offset`.

### 3.3. Vaccine Schedules, Vaccination Records, and Recalls

A `PlatformAdmin` creates vaccine-schedule rules; each rule pairs a `species` with a `vaccine_code` (matching the regex of an uppercase letter followed by 1 to 31 uppercase-alphanumeric-or-underscore characters) and is unique within a (`species`, `age_min_days`) pair. The `age_min_days` value is the minimum age in days at which the first dose is due (between 0 and 7300 inclusive); the optional `booster_interval_days` is the gap in days between successive doses (between 7 and 1825 inclusive when present, null for single-dose schedules). The optional `required` flag defaults to false and marks legally required vaccines such as rabies.

A vaccination record is recorded under a pet by a `DraftingVet` or `TriageNurse`. The body carries the `vaccine_code` (which must match a `VaccineSchedule` for the pet's species), the `administered_at` timestamp, and the `batch_id` (matching the regex of 4 to 32 uppercase alphanumeric or hyphen characters). On creation the record's `status` defaults to `ACTIVE` and `next_due_at` is computed as the administration timestamp plus the schedule's `booster_interval_days` (null for single-dose). Recording also marks any earlier active record with the same `vaccine_code` for the same pet as `SUPERSEDED`. Three guard rails apply at recording time: the administration timestamp must be at least the pet's birth date plus the matching schedule's `age_min_days`, otherwise the system returns `ERR_VACCINE_AGE_MIN`; the batch must not currently be a recalled batch, otherwise the system returns `ERR_BATCH_RECALLED`; and a re-vaccination cooldown applies — a new active record with the same `vaccine_code` cannot be administered earlier than the prior active record's `administered_at` plus half of the schedule's `booster_interval_days` (the boundary is half-open: the prior administration plus the cooldown duration is the earliest valid moment), otherwise the system returns `ERR_VACCINE_COOLDOWN`.

The due-list endpoint computes due-vaccine items for a pet. The pet's age in days is the floor of (today minus `birth_date`). For each schedule whose `species` matches the pet's and whose `age_min_days` is not greater than the pet's age in days, the system gathers the pet's records with that `vaccine_code` filtered to status `ACTIVE` only (`RECALLED` and `SUPERSEDED` records are excluded from this base list), sorted ascending by `administered_at` with `id` ascending as the tie-break. If the active history is empty, the next due date is the pet's `birth_date` plus `age_min_days` days. Otherwise, when the schedule is multi-dose, the next due date is the latest active record's `administered_at` plus `booster_interval_days` days; when the schedule is single-dose, the schedule is considered satisfied and produces no due item. A schedule's due item is marked `overdue` when its computed due date is no later than the current UTC date — that is, a due date equal to today is overdue.

A vaccine-batch-recall event arrives through the dedicated event endpoint with the `batch_id`, the `vaccine_code`, and an `event_id` for idempotency. Processing the event flips every matching `ACTIVE` vaccination record to `RECALLED`, immediately sets each affected record's `next_due_at` to the same record's `administered_at` (so the dose reads as "due now"), recomputes each affected pet's vaccine-due list, and emits an outbound IM-bridge notification to the pet's owner via the IM-emit endpoint. Under the post-recall variant of the due-list calculation, a recalled dose is treated as if it had never been administered: the system falls back to the latest still-active prior dose for that schedule, or to `birth_date` plus `age_min_days` days when no earlier active dose exists. The batch-recall event is idempotent on its `event_id` paired with the batch identification — a duplicate delivery returns 200 and writes nothing further.

### 3.4. Visit Registration, Triage, and Routing

A visit is opened in `REGISTERED` by a `TriageNurse` or `OwnerService` operator. The visit-creation body carries `symptom_text` (1 to 2000 characters of the owner's symptom description) and `severity_score` (an integer between 1 and 10, where 1 is routine and 10 is critical). The created visit carries a `pet_id` (taken from the path), a default `status` of `REGISTERED`, and a `closed_at` of null. Two preconditions guard visit creation: the pet must not be archived (otherwise `ERR_PET_ARCHIVED`), and the visit-FK existence chain must resolve (path parameter first, body FKs after).

Triage moves the visit from `REGISTERED` to `TRIAGED`. Two preconditions apply: the owner's `contact_verified` must be true (otherwise `ERR_OWNER_NOT_VERIFIED`), and the pet must not be archived. Triage runs three coupled computations in the order below.

First, the **triage priority score**. A species factor is selected from the table 1.0 for `DOG`, 1.0 for `CAT`, 1.2 for `RABBIT`, 1.3 for `BIRD`, and 1.1 for `OTHER`. The pet's age in days is the floor of (today minus `birth_date`). An age factor is 1.3 when the pet's age in days is at most 90, 1.2 when the pet's age in days is at least 4380, and 1.0 otherwise. The raw score is the visit's `severity_score` multiplied by the species factor and then by the age factor. The final score is the raw score multiplied by 10, rounded half-up to the nearest whole number, and divided by 10 — yielding 1 decimal place. The bucket is selected with **lower-bound-inclusive** boundaries: a final score of at least 8.0 maps `triage_priority` to `EMERGENCY`; otherwise a final score of at least 5.0 maps it to `URGENT`; otherwise it maps to `ROUTINE`. The constants in this calculation are an emergency threshold of 8.0, an urgent threshold of 5.0, a pediatric age boundary of 90 days, and a geriatric age boundary of 4380 days (twelve years).

Second, the **department routing**. When `triage_priority` is `EMERGENCY`, `department_code` is set to `EMERGENCY` regardless of symptom keywords. Otherwise the symptom text is lower-cased and inspected: if it contains the substring "skin", `department_code` is `DERMATOLOGY`; otherwise if it contains "tooth" or "dental", `department_code` is `DENTAL`; otherwise if `severity_score` is at least 6, `department_code` is `SURGERY`; otherwise `department_code` is `INTERNAL_MED`. The `department_code` enum admits exactly the values `INTERNAL_MED`, `SURGERY`, `EMERGENCY`, `DERMATOLOGY`, and `DENTAL`.

Third, the **vet selector**. The eligible candidate set is the vets currently active in the chosen `department_code`. The set is ranked by current open-visit count ascending, with vet `id` ascending as the tie-break. The lowest-ranked candidate becomes `assigned_vet_id`. If the eligible set is empty, the request is rejected with `ERR_NO_VET_AVAILABLE`.

A `TriageNurse` may also re-route by re-triaging from `IN_CONSULT` back to `TRIAGED`; this branch-back is only allowed before any treatment record on the visit has been finalized (otherwise the request is rejected with `ERR_INVALID_STATE`), and it re-runs the routing rules — in particular, `assigned_vet_id` may change. A `TriageNurse` may cancel a visit from `REGISTERED` or from `TRIAGED` only when the visit has no treatment record, no lab report, no prescription, and no hospitalization yet attached.

The drafting vet who consults the visit calls the start-consult action to advance from `TRIAGED` to `IN_CONSULT`; the request is admitted only when `X-User-ID` matches the visit's `assigned_vet_id`. The same vet later calls the end-consult action to advance from `IN_CONSULT` to `CONSULT_DONE`, which requires that at least one treatment record on the visit has reached `FINALIZED`.

### 3.5. Treatment Records, Diagnosis, and Consent

A drafting vet creates a treatment record under a visit by supplying the `visit_id`, the `consultation_notes` (1 to 4000 characters of free text), the `diagnosis_code` (matching the regex of an uppercase letter followed by 1 to 15 uppercase-alphanumeric-or-period characters), the `treatment_plan` (1 to 2000 characters), and an initial value for `consent_recorded`. The visit must be in `IN_CONSULT` (otherwise `ERR_INVALID_STATE`). The record's `status` defaults to `DRAFT`. The `consent_recorded_at` timestamp is null at creation; the system sets it to the current time the first moment `consent_recorded` flips from false to true (it is not rewritten on subsequent updates).

The finalize action moves the record from `DRAFT` to `FINALIZED`. Three preconditions apply: `consent_recorded` must be true; the caller's `X-User-ID` must equal the visit's `assigned_vet_id`; and the visit must be in `IN_CONSULT`. On success, three side effects fire: an entry of the form `{visit_id, diagnosis_code, finalized_at}` is appended to the pet's `medical_history` (cascade hop 1, ordered by finalization time ascending); a `CONSULT` line item is appended to the visit's bill, which forces a recompute of `provisional_total_cents` (cascade hop 2); and an audit-log entry is written with a `subject_type` of `TREATMENT_RECORD` and an `action` of `FINALIZE`.

A treatment record can be amended after finalization. The amend action is an update that requires the `version` field for OCC and accepts optional `consultation_notes` and optional `treatment_plan`. The visit must be in `IN_CONSULT` or `CONSULT_DONE` for the amend to be admitted, and the caller's `X-User-ID` must equal `assigned_vet_id`. On success, the record's `status` becomes `AMENDED` and an audit-log entry of `action` `AMEND` is written; the `payload_hash` for the amend captures the new field values. The pet's `medical_history` snapshot is **not** rewritten by an amend — the array is event-style append-only and the originally finalized entry stays as-is.

### 3.6. Lab Reports, Sample Lifecycle, and Abnormal Flags

A drafting vet orders tests by creating a lab report under a visit. The body carries the `visit_id` and the `test_items` array — between 1 and 50 entries, each of the form `{code, name, ref_low, ref_high}` with `ref_low` non-negative and strictly less than `ref_high`, and with each `code` unique within the report. A non-empty array with all unique codes and well-ordered ranges is required (otherwise `ERR_LAB_ITEMS_INVALID`). The new report's `status` defaults to `ORDERED`, `sample_collected_at` is null, `external_lab_ref` is null, `results` is empty, and `abnormal_codes` is empty.

A `TriageNurse` advances the report from `ORDERED` to `SAMPLE_COLLECTED` by calling the collect-sample action with `sample_collected_at` in the body; the lab-report id appears in the URL as `lr_id`. The same role advances the report from `SAMPLE_COLLECTED` to `SENT_TO_LAB` by calling the send-to-lab action with `external_lab_ref` (matching the regex of 6 to 40 uppercase-alphanumeric-or-hyphen characters) in the body. The external lab returns results through the dedicated event endpoint, posting an `external_lab_ref`, the `results` array, and an `event_id`. The event endpoint is idempotent on `external_lab_ref` — when a duplicate event with the same `external_lab_ref` arrives, the response is 200 with the same body and no double-write. On first arrival, the event matches the lab report whose `external_lab_ref` is the supplied value (the lab report must currently be in `SENT_TO_LAB`), checks that the results-array length matches the test-items length and that the result codes are a permutation of the test-item codes, sets `results`, recomputes `abnormal_codes`, and transitions the report to `RESULT_RECEIVED`.

The `abnormal_codes` array is computed with **exclusive** boundary semantics on both ends: a value strictly less than its item's `ref_low` or strictly greater than `ref_high` flags the code as abnormal, but a value exactly equal to either reference bound is normal. The resulting list of abnormal codes is sorted in ascending lexicographic order for determinism.

A drafting vet whose `X-User-ID` matches the visit's `assigned_vet_id` finalizes the report from `RESULT_RECEIVED` to `FINALIZED`; the visit must be in `IN_CONSULT` or `CONSULT_DONE`. Finalization appends a `LAB` line item to the visit's bill and recomputes `provisional_total_cents`. A drafting vet may cancel the report from `ORDERED` or `SAMPLE_COLLECTED`; cancellation has no further side effects. The history endpoint compares the supplied report to the most-recent prior `FINALIZED` lab report for the same pet (the same `pet_id` derived through the visit) and returns a comparison structure useful for clinical follow-up.

### 3.7. Drug Catalog and Prescription Lifecycle

`PlatformAdmin` populates the drug catalog. Each drug carries a `code` (unique, regex-constrained as an uppercase letter followed by 1 to 31 uppercase-alphanumeric-or-underscore characters), a `name` (1 to 80 characters), a `controlled` flag (default false; true marks special-control drugs that require segregation-of-duties at approval time), a `dosage_min_mg_per_kg` (strictly greater than 0), a `dosage_max_mg_per_kg` (greater than or equal to `dosage_min_mg_per_kg`), an `interactions` array of `{with_drug_code, severity}` entries where severity is one of `MILD`, `MODERATE`, or `SEVERE`, and a `stock_units` integer (default 0). The drug update action accepts an optional `stock_units`, an optional `interactions` replacement, and an optional `version` for OCC.

A drafting vet drafts a prescription by posting the `visit_id` and the `items` array — between 1 and 20 entries, each of the form `{drug_code, dose_mg_per_kg, frequency_per_day, duration_days, units}`. Subsequent prescription actions reference the prescription via the URL path parameter `rx_id`. The new prescription is created with `drafting_vet_id` set from the caller's `X-User-ID`, `reviewing_vet_id` null, `interaction_risk` defaulting to `NONE`, `status` defaulting to `DRAFT`, `rejection_reason` null, and `dispensed_at` null.

The submit action moves the prescription from `DRAFT` to `PENDING_REVIEW`. The visit must be in `IN_CONSULT`, the caller's `X-User-ID` must equal `drafting_vet_id`, the owner's `contact_verified` must be true at this moment (otherwise `ERR_OWNER_NOT_VERIFIED`), each item's `dose_mg_per_kg` must lie within the inclusive range from the drug's `dosage_min_mg_per_kg` up to and including the drug's `dosage_max_mg_per_kg` (otherwise `ERR_DOSAGE_OUT_OF_RANGE`), and the **dosage rationality** equation must hold for each item — the item's `units` must equal the ceiling of the product of `dose_mg_per_kg`, the pet's `weight_kg`, the item's `frequency_per_day`, and the item's `duration_days` (with the ceiling applied at the end of that three-way product). The submit action also runs the drug-interaction calculation: a severity rank of 0 is assigned to no-interaction, 1 to `MILD`, 2 to `MODERATE`, and 3 to `SEVERE`; the system enumerates every unordered pair drawn from the `items` array, looks up the directed interaction edge of one drug toward another in the first drug's `interactions` table, and tracks the maximum severity rank across all such pairs. The prescription's `interaction_risk` is set to the enum value corresponding to that maximum (or `NONE` when no pair has an edge). Submission writes an audit-log entry with `subject_type` of `PRESCRIPTION`, `action` of `SUBMIT`, `from_state` of `DRAFT`, and `to_state` of `PENDING_REVIEW`.

The approve action moves the prescription from `PENDING_REVIEW` to `APPROVED`. The body accepts an optional `override_acknowledged` flag. Three preconditions apply. **Segregation of duties**: when at least one of the prescription's items references a drug whose `controlled` flag is true, the caller's `X-User-ID` must differ from `drafting_vet_id` — otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. **Severe-interaction guard**: when the prescription's `interaction_risk` is `SEVERE`, the request body must carry `override_acknowledged` set to true — otherwise the request is rejected with `ERR_SEVERE_INTERACTION`. **Dosage rationality**: each item's `dose_mg_per_kg` must remain within the drug's inclusive dosage range. On success, `reviewing_vet_id` is set to the caller's `X-User-ID` and an `APPROVE` audit-log entry is written. The reject action moves the prescription from `PENDING_REVIEW` to `REJECTED`; the body must carry a `rejection_reason` of 1 to 500 characters; on success, `reviewing_vet_id` is set and a `REJECT` audit-log entry is written. The redraft action moves the prescription from `REJECTED` back to `DRAFT`, which clears `reviewing_vet_id` and `rejection_reason`; only the original drafting vet (whose `X-User-ID` equals `drafting_vet_id`) may redraft. The DRAFT-PENDING_REVIEW-REJECTED loop may repeat any number of times.

The dispense action, run by a `Pharmacist`, moves the prescription from `APPROVED` to `DISPENSED`. Two preconditions apply: every item's `units` must be no greater than the corresponding drug's `stock_units` at dispense time, and the visit must be in `IN_CONSULT`, `CONSULT_DONE`, or `HOSPITALIZED`. On success, every item's drug has its `stock_units` decremented by the item's `units`; `dispensed_at` is set to the current time; a `DRUG` line item is appended to the visit's bill and the bill's `provisional_total_cents` is recomputed (cascade hop 1); and, if the bill was in `ISSUED` at the time of the dispense, the bill drops back to `DRAFT` so it must be re-issued with the new line included (cascade hop 2). A `DISPENSE` audit-log entry is written.

A drafting vet may cancel a prescription from `DRAFT` or from `PENDING_REVIEW`; cancellation writes a `CANCEL` audit-log entry. The terminal states for a prescription are `DISPENSED` and `CANCELLED`.

Two simultaneous approvals on the same prescription serialize first-writer-wins on the prescription's `status`: exactly one approve succeeds, and the loser receives `ERR_PRESCRIPTION_ALREADY_REVIEWED` because its `version` field is stale relative to the now-`APPROVED` row. When an approve and a reject arrive concurrently for the same `PENDING_REVIEW` prescription, exactly one operation succeeds and the loser sees `ERR_INVALID_STATE` because the prescription has already moved out of `PENDING_REVIEW`. When two dispenses race for the same approved prescription, drug stock is decremented exactly once for that prescription; the second dispense is rejected with `ERR_INVALID_STATE` because `status` has already advanced past `APPROVED`.

### 3.8. Cages, Hospitalization Lifecycle, and Cage Capacity

A `PlatformAdmin` creates cages. A cage carries a `cage_code` (regex-constrained as an uppercase letter followed by 1 to 15 uppercase-alphanumeric-or-hyphen characters and unique across the system), a `ward_code` from `ISOLATION`, `GENERAL`, or `ICU`, and a `capacity` from 1 through 4 inclusive. The cage's `occupancy_count` is computed as the count of hospitalization rows with status `IN_CARE` currently assigned to it.

A drafting vet admits a visit by creating a hospitalization with the `visit_id` and the `cage_id`; once admitted, the hospitalization is referenced by the URL path parameter `h_id`. The visit must be in `CONSULT_DONE` (otherwise `ERR_INVALID_STATE`), the cage's `occupancy_count` must be strictly less than the cage's `capacity` at admission time (otherwise `ERR_CAGE_CAPACITY_EXCEEDED`), and the owner's `deposit_balance_cents` must be at least 50,000 cents — that is, at least five hundred dollars — to satisfy the admission hold (otherwise `ERR_INSUFFICIENT_DEPOSIT`). Admission has two side effects: the cage's `occupancy_count` is incremented by 1, and the owner's `deposit_balance_cents` is decremented by 50,000 cents (the admission hold). Also at admission, the visit transitions from `CONSULT_DONE` to `HOSPITALIZED`. The new hospitalization carries an `admitted_at` timestamp, a `discharged_at` of null, an empty `daily_care_log` array, and a `status` of `ADMITTED`.

When two hospitalization-create requests race for the same cage at its capacity boundary, the cage's atomic check-and-increment guarantees that at most one assignment can push `occupancy_count` up to `capacity`; the other request is rejected with `ERR_CAGE_CAPACITY_EXCEEDED`. Beyond the immediate admission check, a temporal-overlap rule also applies: across the interval from `admitted_at` to either `discharged_at` (or, when the hospitalization is still open, to plus-infinity), the aggregate count of active occupants on a single cage must never exceed the cage's `capacity`. A request that would violate this aggregate constraint is rejected with `ERR_CAGE_OVERLAP_CAPACITY`.

The drafting vet then advances the hospitalization from `ADMITTED` to `IN_CARE` by calling the begin-care action (no preconditions). Daily care entries are appended through the care-log action with `note` and `treatment_executed`; new entries are accepted only while the hospitalization is in `ADMITTED` or `IN_CARE`. The drafting vet then calls the request-discharge action to advance from `IN_CARE` to `DISCHARGE_PENDING`; the precondition is that every prescription on the visit has reached `DISPENSED`, `REJECTED`, or `CANCELLED` (otherwise `ERR_PENDING_PRESCRIPTIONS`). The cashier then calls the discharge action to advance from `DISCHARGE_PENDING` to `DISCHARGED`; the precondition is that the visit's bill is in one of `ISSUED`, `PARTIALLY_PAID`, `PAID`, or `INVOICED`. On discharge, three side effects fire: `discharged_at` is set to the current time; the cage's `occupancy_count` is decremented by 1; and one `HOSPITAL_DAY` line item is appended to the visit's bill per calendar day spanned between `admitted_at` and `discharged_at`, with `provisional_total_cents` recomputed afterward.

A drafting vet may cancel a hospitalization while it is still in `ADMITTED` and only when no daily-care entry on it has `treatment_executed` set to true. Cancellation decrements the cage's `occupancy_count` by 1 and refunds the admission hold by incrementing the owner's `deposit_balance_cents` by 50,000 cents.

### 3.9. Bills, Discounts, Payments, Refunds, and Invoices

A cashier creates one bill per visit by posting the `visit_id` and optionally a `package_code` and an `insurance_estimate_cents`. The new bill carries a `line_items` array (initially empty, computed from the visit's children as treatment records, lab reports, prescriptions, and hospitalizations finalize), a `package_code` (optional, must reference a known package configuration when set, with at most one package per bill), an `insurance_estimate_cents` (default 0), an `insurance_actual_cents` (default 0, populated by the external insurance settlement event), a `deposit_applied_cents` of 0, a `provisional_total_cents` of 0, a `final_total_cents` of 0, a `paid_amount_cents` of 0, a `refund_amount_cents` of 0, an `invoice_no` of null, and a `status` of `DRAFT`. Exactly one bill exists per visit.

The bill recompute action recomputes `provisional_total_cents` from the current line items and is idempotent. The line items contributing to the bill are aggregated from the visit's children with statuses pinned exactly: only finalized treatment records contribute `CONSULT` lines, only finalized lab reports contribute `LAB` lines, only dispensed prescriptions contribute `DRUG` lines, and only discharged hospitalizations contribute `HOSPITAL_DAY` lines. Treatment records still in draft, amended treatment records, cancelled lab reports, and cancelled prescriptions do not contribute. Each line carries a `kind` of `CONSULT`, `LAB`, `DRUG`, or `HOSPITAL_DAY`, a `ref_id` pointing back to the source row, a `qty`, a `unit_price_cents`, and a `line_total_cents`.

The provisional total is computed in pinned phases. Phase 1 produces each line's `line_total_cents` as the line's `qty` multiplied by its `unit_price_cents`, rounded half-up to whole cents. Phase 2 sums the per-line totals into the gross. Phase 3 applies a tier-based package discount keyed on the gross **before** the discount is applied. When `package_code` is `DENTAL_PKG`, the package tier percentage is 15 if the gross is at least 50,000 cents (five hundred dollars), 10 if the gross is at least 20,000 cents (two hundred dollars) but less than 50,000 cents, and 5 otherwise. When `package_code` is `SURGERY_PKG`, the package tier percentage is 20 if the gross is at least 150,000 cents (fifteen hundred dollars) and 12 otherwise. When `package_code` is unset, no discount applies. The package-discount amount is the gross multiplied by the tier percentage divided by 100, rounded half-up to whole cents. The gross-after-discount is the gross minus the package-discount amount. The tier selection is **single-pass**: it is keyed only on the pre-discount gross, never re-evaluated against the post-discount value, even when re-evaluation would land in a different tier. Phase 4 subtracts the deposit-applied amount (already deducted as a side effect of the issue transition described below). Phase 5 subtracts the insurance term: for the provisional total, the insurance applied is the smaller of the bill's `insurance_estimate_cents` and the gross-after-discount minus the deposit-applied amount. The provisional total is then the gross-after-discount minus the deposit-applied amount minus the insurance applied, with a floor of 0 — a result smaller than 0 is replaced by 0.

The issue action moves the bill from `DRAFT` to `ISSUED`. Two preconditions apply: the visit must be in `CONSULT_DONE` or `HOSPITALIZED`, and `provisional_total_cents` must already have been recomputed. On entry to `ISSUED`, the system applies the deposit: `deposit_applied_cents` is set to the smaller of the owner's `deposit_balance_cents` and the gross-after-discount, and the owner's `deposit_balance_cents` is decremented by that same applied amount. A drafted bill can be cancelled by the cashier only when the visit itself is in `CANCELLED`; cancellation restores the deposit by incrementing the owner's `deposit_balance_cents` by `deposit_applied_cents`.

Payments arrive through the payment event endpoint with the `bill_id`, the `amount_cents`, and an `event_id`; the endpoint is idempotent on `event_id`, and a duplicate event_id is rejected with `ERR_DUPLICATE_EVENT`. A payment whose amount is strictly positive but whose cumulative paid-amount has not yet reached the gross-after-discount minus the deposit-applied amount transitions the bill from `ISSUED` to `PARTIALLY_PAID` and increments `paid_amount_cents` by the event amount. A payment whose cumulative paid-amount reaches the same threshold (the gross-after-discount minus the deposit-applied amount) transitions the bill into `PAID` from either `ISSUED` (single-payment path) or `PARTIALLY_PAID` (final installment path); both paths increment `paid_amount_cents` and recompute `final_total_cents`. Two simultaneous payment events with the same `event_id` serialize on that key — exactly one is applied, the other is a no-op rejected with `ERR_DUPLICATE_EVENT`.

The final total is computed identically to the provisional total through the deposit phase, then the insurance term switches: the insurance applied is the smaller of the bill's `insurance_actual_cents` and the gross-after-discount minus the deposit-applied amount. The final total is the gross-after-discount minus the deposit-applied amount minus that insurance applied, floored at 0. When the actual reimbursement turns out larger than the estimate and the customer has already paid more than the recomputed final total, the bill triggers an automatic refund flow: `refund_amount_cents` is provisionally set to `paid_amount_cents` minus `final_total_cents`, and the bill transitions from `PAID` to `REFUND_PENDING`. The cashier may also explicitly initiate a refund from `PAID` or from `INVOICED` by calling the refund action with an `amount_cents` and a `reason`; the precondition is that the cumulative refund — the proposed `amount_cents` plus the existing `refund_amount_cents` — must not exceed `paid_amount_cents`, otherwise the request is rejected with `ERR_REFUND_EXCEEDS_PAID`. A `REFUND_PENDING` bill is finalized by the external refund-confirm event (idempotent on `event_id`); on confirm, `refund_amount_cents` is incremented by the event amount, the bill transitions to `REFUNDED`, and the cascade restores both the owner's `deposit_balance_cents` and the affected drugs' `stock_units` per the bill's refund breakdown.

The cashier issues an invoice from `PAID` by calling the issue-invoice action; on success, `invoice_no` is set to a string of the form `INV-YYYYMMDD-{seq6}` (six-digit zero-padded sequence per day) and the bill transitions to `INVOICED`. A `PAID` bill that has not yet been invoiced may also enter `REFUND_PENDING`; an invoiced bill that requires a refund follows the `INVOICED` to `REFUND_PENDING` to `REFUNDED` path.

When a prescription is dispensed against a bill that is currently in `ISSUED`, the system runs a cascade-driven revert: a new `DRUG` line item is appended, `provisional_total_cents` is recomputed against the new line set, and the bill's `status` is moved from `ISSUED` back to `DRAFT` so the cashier must re-issue. Only the system itself can perform this `ISSUED` to `DRAFT` revert — no role-facing action is exposed for it.

### 3.10. Visit Closure and Audit Trail

A cashier closes a visit, transitioning it to `CLOSED`. From `CONSULT_DONE`, closure requires that the visit's bill exists and is in `INVOICED` or `REFUNDED`, and that every prescription on the visit has reached `DISPENSED`, `REJECTED`, or `CANCELLED` — open prescriptions are rejected with `ERR_PENDING_PRESCRIPTIONS`. From `HOSPITALIZED`, closure additionally requires that every hospitalization on the visit is in `DISCHARGED`. On either path the visit moves to `CLOSED` and `closed_at` is set to the current time. When any treatment record on the visit was amended during the lifetime of the visit, an audit-log entry of `subject_type` `TREATMENT_RECORD` and `action` `FINALIZE` is appended at closure to bookend the amend trail.

The audit log is queryable by `PlatformAdmin` through the audit-log read endpoint, with optional filters `subject_type`, `subject_id`, and `action`, plus the standard `limit` and `offset`. Each entry carries a `subject_type` (one of `PRESCRIPTION` or `TREATMENT_RECORD`), a `subject_id`, an `actor_role`, an `actor_id`, an `action` (one of `DRAFT`, `SUBMIT`, `APPROVE`, `REJECT`, `DISPENSE`, `FINALIZE`, `AMEND`, or `CANCEL`), a `from_state` (which may be null for create-style entries), a `to_state`, a `payload_hash` (the SHA-256 hex digest of the canonical JSON of the relevant fields at the time of the event), and an `occurred_at` timestamp. Audit-log entries are append-only and never carry `version` or `updated_at`.

For deterministic test runs, an admin-only test-driving capability advances the logical clock by a supplied number of `seconds` so that vaccine-due dates and audit timestamps move predictably. The IM-bridge endpoint is an admin-only outbound stub that records emissions of `recipient_owner_id`, `kind`, and `payload` for assertion purposes; it is the cascade target of the vaccine-batch-recall flow described in §3.3.

## 4. Endpoint Definitions

All POST endpoints that create a new resource respond with HTTP 201; all other modifications and reads respond with HTTP 200. Error responses use the HTTP status codes catalogued in §5. The table below summarizes method, path, brief description, and authorized roles; consult §3 for request bodies, response payloads, side effects, and validation conditions.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /pet-hospital/owners | Create owner. | OwnerService, PlatformAdmin |
| GET | /pet-hospital/owners/{owner_id} | Read owner. | OwnerService, PlatformAdmin, TriageNurse, Cashier |
| POST | /pet-hospital/owners/{owner_id}/issue-verification | Issue contact-verification code. | OwnerService, PlatformAdmin |
| POST | /pet-hospital/owners/{owner_id}/verify-contact | Submit verification code. | OwnerService, PlatformAdmin |
| POST | /pet-hospital/owners/{owner_id}/deposits | Top up owner deposit. | Cashier |
| POST | /pet-hospital/pets | Create pet. | OwnerService, PlatformAdmin, TriageNurse |
| GET | /pet-hospital/pets/{pet_id} | Read pet (includes medical_history). | OwnerService, TriageNurse, DraftingVet, ReviewingVet, Pharmacist, Cashier, PlatformAdmin |
| PATCH | /pet-hospital/pets/{pet_id} | Update pet weight or name. | TriageNurse, DraftingVet, OwnerService |
| DELETE | /pet-hospital/pets/{pet_id} | Soft-delete (archive) pet. | PlatformAdmin |
| GET | /pet-hospital/pets/{pet_id}/visits | List pet's visit history (newest first). | OwnerService, TriageNurse, DraftingVet, PlatformAdmin |
| GET | /pet-hospital/pets/{pet_id}/vaccines/due-list | Compute vaccine due list. | OwnerService, TriageNurse, DraftingVet |
| POST | /pet-hospital/pets/{pet_id}/vaccinations | Record vaccination. | DraftingVet, TriageNurse |
| POST | /pet-hospital/vaccine-schedules | Create vaccine-schedule rule. | PlatformAdmin |
| POST | /pet-hospital/_events/vaccine-batch-recall | External vaccine-batch recall event (idempotent). | PlatformAdmin |
| POST | /pet-hospital/pets/{pet_id}/visits | Create visit. | TriageNurse, OwnerService |
| GET | /pet-hospital/visits/{visit_id} | Read visit. | TriageNurse, DraftingVet, ReviewingVet, Pharmacist, Cashier, OwnerService, PlatformAdmin |
| POST | /pet-hospital/visits/{visit_id}/triage | Triage and route visit. | TriageNurse |
| POST | /pet-hospital/visits/{visit_id}/start-consult | Begin consultation. | DraftingVet |
| POST | /pet-hospital/visits/{visit_id}/re-triage | Re-route visit (cycle back). | TriageNurse |
| POST | /pet-hospital/visits/{visit_id}/end-consult | End consultation. | DraftingVet |
| POST | /pet-hospital/visits/{visit_id}/close | Close visit. | Cashier |
| POST | /pet-hospital/visits/{visit_id}/cancel | Cancel visit. | TriageNurse |
| POST | /pet-hospital/treatment-records | Draft treatment record. | DraftingVet |
| PATCH | /pet-hospital/treatment-records/{tr_id} | Amend finalized treatment record. | DraftingVet |
| POST | /pet-hospital/treatment-records/{tr_id}/finalize | Finalize treatment record. | DraftingVet |
| POST | /pet-hospital/lab-reports | Order lab tests. | DraftingVet |
| POST | /pet-hospital/lab-reports/{lr_id}/collect-sample | Mark sample collected. | TriageNurse |
| POST | /pet-hospital/lab-reports/{lr_id}/send-to-lab | Send sample to lab. | TriageNurse |
| POST | /pet-hospital/_events/external-lab-result | External lab callback (idempotent on external_lab_ref). | PlatformAdmin |
| POST | /pet-hospital/lab-reports/{lr_id}/finalize | Finalize lab report. | DraftingVet |
| GET | /pet-hospital/lab-reports/{lr_id}/history | Compare to last finalized report for the pet. | DraftingVet, OwnerService |
| POST | /pet-hospital/lab-reports/{lr_id}/cancel | Cancel pre-result lab report. | DraftingVet |
| POST | /pet-hospital/drugs | Create drug. | PlatformAdmin |
| PATCH | /pet-hospital/drugs/{drug_id} | Adjust stock or interactions. | PlatformAdmin, Pharmacist |
| POST | /pet-hospital/prescriptions | Draft prescription. | DraftingVet |
| POST | /pet-hospital/prescriptions/{rx_id}/submit | Submit for review. | DraftingVet |
| POST | /pet-hospital/prescriptions/{rx_id}/approve | Approve prescription. | ReviewingVet |
| POST | /pet-hospital/prescriptions/{rx_id}/reject | Reject prescription. | ReviewingVet |
| POST | /pet-hospital/prescriptions/{rx_id}/redraft | Redraft from rejected. | DraftingVet |
| POST | /pet-hospital/prescriptions/{rx_id}/dispense | Dispense approved prescription. | Pharmacist |
| POST | /pet-hospital/prescriptions/{rx_id}/cancel | Cancel prescription. | DraftingVet |
| POST | /pet-hospital/cages | Create cage. | PlatformAdmin |
| POST | /pet-hospital/hospitalizations | Admit visit to cage. | DraftingVet |
| POST | /pet-hospital/hospitalizations/{h_id}/begin-care | Move from admitted to in-care. | DraftingVet |
| POST | /pet-hospital/hospitalizations/{h_id}/care-log | Append daily-care entry. | DraftingVet |
| POST | /pet-hospital/hospitalizations/{h_id}/request-discharge | Request discharge. | DraftingVet |
| POST | /pet-hospital/hospitalizations/{h_id}/discharge | Confirm discharge. | Cashier |
| POST | /pet-hospital/hospitalizations/{h_id}/cancel | Cancel pre-care hospitalization. | DraftingVet |
| POST | /pet-hospital/bills | Create bill. | Cashier |
| POST | /pet-hospital/bills/{bill_id}/recompute | Recompute provisional total. | Cashier |
| POST | /pet-hospital/bills/{bill_id}/issue | Move bill from draft to issued. | Cashier |
| POST | /pet-hospital/_events/payment | External payment event (idempotent). | PlatformAdmin |
| POST | /pet-hospital/bills/{bill_id}/issue-invoice | Issue invoice. | Cashier |
| POST | /pet-hospital/bills/{bill_id}/refund | Initiate refund. | Cashier |
| POST | /pet-hospital/_events/refund-confirm | External refund confirmation event (idempotent). | PlatformAdmin |
| POST | /pet-hospital/bills/{bill_id}/cancel | Cancel draft bill. | Cashier |
| GET | /pet-hospital/audit-logs | Query audit trail. | PlatformAdmin |
| POST | /pet-hospital/_events/im-emit | Outbound IM-bridge stub. | PlatformAdmin |
| POST | /pet-hospital/_clock/advance | Advance test clock. | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the §2 and §3 narratives where they apply. The table below records only the error identifier and its HTTP status code.

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 409 |
| ERR_PET_ARCHIVED | 409 |
| ERR_OWNER_NOT_VERIFIED | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_DOSAGE_OUT_OF_RANGE | 422 |
| ERR_SEVERE_INTERACTION | 422 |
| ERR_PENDING_PRESCRIPTIONS | 409 |
| ERR_LAB_ITEMS_INVALID | 422 |
| ERR_CAGE_CAPACITY_EXCEEDED | 409 |
| ERR_CAGE_OVERLAP_CAPACITY | 409 |
| ERR_INSUFFICIENT_DEPOSIT | 402 |
| ERR_VACCINE_AGE_MIN | 422 |
| ERR_VACCINE_COOLDOWN | 422 |
| ERR_BATCH_RECALLED | 422 |
| ERR_REFUND_EXCEEDS_PAID | 422 |
| ERR_DUPLICATE_EVENT | 409 |
| ERR_PRESCRIPTION_ALREADY_REVIEWED | 409 |
| ERR_NO_VET_AVAILABLE | 409 |
| ERR_VALIDATION_FAILED | 422 |

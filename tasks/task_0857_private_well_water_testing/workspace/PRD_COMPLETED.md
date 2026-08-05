# Private Well Water Testing API — Product Requirements Document

## 1. Introduction

Private drinking-water wells sit at the intersection of property rights, public health, and environmental stewardship. Unlike municipal utilities, a private well is regulated only at the moments that matter: when it is drilled, when it is sampled, when contamination surfaces, and when the property changes hands or the well is abandoned. This document specifies the backend service that a county or state groundwater program uses to administer that entire regulatory arc — from a driller's construction permit through routine and real-estate water testing, laboratory result intake, health advisories, contamination casework, and final decommissioning — as a single authoritative registry.

The service coordinates four distinct actors whose duties must never blur: well owners (applicants) who file for permits and submit samples, licensed drillers who perform the physical work and file logs, laboratory analysts who receive and analyze samples, and health officers who exercise regulatory judgment. Because a single lab result can simultaneously determine whether water is safe to drink, open a contamination investigation, and issue a public advisory, the platform treats every well as carrying two independent status dimensions — a registry lifecycle and a potability (health) status — that evolve on separate tracks but reconcile against one shared body of evidence. Money, advisory counts, and health status are all derived quantities that must remain internally consistent after every mutation.

This PRD defines the resource model, the state machines that govern each entity, the fee and water-quality calculations, the validation and authorization rules, and the complete HTTP surface. It is the sole contract for the implementation; every behavior a client can observe is specified here.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the named role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is always evaluated before authorization, and both precede any inspection of the request body or referenced resources.

The four roles are `Applicant`, `Driller`, `LabAnalyst`, and `HealthOfficer`.

An `Applicant` is a well owner. Applicants register wells, submit construction and abandonment permit applications, pay permit fees, submit water samples, create real-estate test requirements, and attach candidate samples to those requirements. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an applicant compare that resource's applicant foreign key to `X-User-ID` (for example, an applicant fetching its own account record); when such an ownership check fails — an applicant fetching an applicant record other than its own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Ownership is enforced this way only on the account-fetch endpoint; other applicant-role endpoints that carry an applicant foreign key in the body (creating a well, submitting a permit or sample, paying a permit, attaching a candidate sample) do not compare the acting `X-User-ID` against that foreign key.

A `Driller` is a licensed well driller. Drillers file driller logs that complete construction permits and complete approved abandonment work. When `X-User-Role` is `Driller`, `X-User-ID` is the `id` of the acting `Driller` entity; ownership checks on any resource that references a driller compare the resource's driller foreign key to `X-User-ID`.

A `LabAnalyst` is a laboratory analyst who receives samples, begins analysis, and records results. When `X-User-Role` is `LabAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may accept and log it, but it is not compared to any entity's `id`.

A `HealthOfficer` is a regulatory officer. Health officers manage aquifer, applicant, and driller records, review and issue construction permits, run the expiry sweep and logical clock, issue and lift advisories, drive contamination cases, and certify or waive real-estate requirements. When `X-User-Role` is `HealthOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, but it does record it for segregation-of-duties enforcement: when an officer opens a contamination case, the officer's `X-User-ID` is stored as `opened_by_officer_id`, and when a different officer later closes that case, the closing `X-User-ID` is stored as `closed_by_officer_id`.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a supplied `limit` below 1 or above 100, and a supplied `offset` below 0, are silently clamped to the nearest bound rather than rejected. The `offset` defaults to 0 and has no upper bound. List results are always ordered by `created_at` ascending, with ties broken by ascending order of original insertion (creation sequence). The `meta` block of a list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records beyond the current page remain).

### 2.4. Common Resource Properties and Entity Persistence

Every resource is assigned a server-minted `id` — a UUID with no type prefix — at creation, and a `created_at` timestamp recording the logical-clock instant of creation. Timestamps throughout the system are ISO 8601 UTC values with three fractional digits.

Most entities additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 when the resource is created and increases by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical-clock instant at the same time. The entities that carry `updated_at` and `version` are `Applicant`, `Driller`, `Well`, `ConstructionPermit`, `DrillerLog`, `WaterSample`, `Advisory`, `ContaminationCase`, `AbandonmentPermit`, and `RealEstateTestRequirement`.

Two entities are exceptions. An `Aquifer` is an immutable configuration record: it carries only `id` and `created_at` — it has neither `updated_at` nor `version`, and once created it is never modified. A `SampleResult` is an append-only laboratory record: it too carries only `id` and `created_at`, has neither `updated_at` nor `version`, and is never mutated after creation. When a downstream event would "change" the effect of a result (such as invalidating its parent sample), the change is recorded on other entities, never on the immutable result row.

### 2.5. Referenced-Resource Resolution and Nested Paths

Endpoints reference resources both through path identifiers and through foreign keys in the request body. All referenced resources are validated to exist. When several references appear, they are checked left-to-right in the order they appear in the path and then the body, and the first unresolved reference determines the error. Each resource type has its own not-found error: `ERR_APPLICANT_NOT_FOUND`, `ERR_DRILLER_NOT_FOUND`, `ERR_AQUIFER_NOT_FOUND`, `ERR_WELL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_DRILLER_LOG_NOT_FOUND`, `ERR_SAMPLE_NOT_FOUND`, `ERR_RESULT_NOT_FOUND`, `ERR_ADVISORY_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ABANDONMENT_NOT_FOUND`, and `ERR_REQUIREMENT_NOT_FOUND`, each returning HTTP 404. Existence is checked at priority just after body well-formedness and just before any state check (see §2.9).

### 2.6. Parallel Well Status Dimensions

A `Well` carries two enumerated status fields that evolve independently. The `registry_status` dimension tracks the regulatory lifecycle and moves through `PROPOSED`, `PERMITTED`, `ACTIVE`, `INACTIVE`, and the terminal `DECOMMISSIONED`. The `potability_status` dimension tracks drinking-water safety and takes the values `UNKNOWN`, `POTABLE`, `ADVISORY`, and `UNSAFE`. A well is created with `registry_status` of `PROPOSED` and `potability_status` of `UNKNOWN`. Neither dimension constrains the other: a well can be `ACTIVE` while `UNSAFE`, or `INACTIVE` while `POTABLE`. The registry dimension advances through permit and abandonment workflows; the potability dimension is recomputed from laboratory evidence and open contamination cases. Section 3 details both tracks. Separately, a health officer may deactivate a well — moving `registry_status` from `ACTIVE` to `INACTIVE` — and later reactivate it — moving it from `INACTIVE` back to `ACTIVE`; requesting deactivation on a well that is not `ACTIVE`, or reactivation on a well that is not `INACTIVE`, is rejected with `ERR_INVALID_STATE` (HTTP 409). Neither transition touches the potability dimension.

### 2.7. Derived and Reconciled Quantities

Several fields are never written directly by clients; they are recomputed from underlying records so that they always agree with the ground truth.

An `Applicant` carries `net_fees_paid_cents`, defaulting to 0, defined as the sum, over all construction permits belonging to that applicant, of the amount currently charged when the fee has been paid (otherwise zero) minus the amount refunded. Concretely, for each of the applicant's construction permits, take `fee_charged_cents` if `fee_paid` is true (else take zero) and subtract `fee_refunded_cents`; sum these across the applicant's permits. This quantity is recomputed whenever a permit is paid, denied, or completed by a driller log, and it is the conserved money quantity the system uses to detect accounting drift.

A `Well` carries `active_advisory_count`, defaulting to 0, defined as the number of advisories for that well whose `status` is `ACTIVE`. It is recomputed whenever an advisory is issued (manually or by cascade) and whenever an advisory is lifted. A `Well` also carries `depth_ft`, initially null, which is set from a driller log's reported total depth when the log is filed, and `potability_status`, which is recomputed as described in §3.

### 2.8. Monetary Values, Precision, and Rounding

All monetary amounts are integer counts of cents. Where a calculation multiplies a base amount by a rate and produces a fractional cent, the result is rounded half-up (round half away from zero at the .5 boundary) to a whole cent. The exact point at which rounding is applied matters and is specified per calculation in §3: for the permit fee, the depth-base amount multiplied by the intended-use multiplier is rounded to whole cents before any surcharge or expedite fee is added; for the sample panel fee, each analyte line is rounded to whole cents individually and only then are the rounded lines summed. Nitrate running averages are rounded half-up to three decimal places before being compared to a threshold. All threshold comparisons on concentrations use "greater than or equal to."

### 2.9. Validation Ordering and Error Precedence

When more than one rule could reject a request, the checks are applied in a fixed priority order and the first failing check determines the response. The global order is: authentication (`ERR_UNAUTHENTICATED`) first; then authorization (`ERR_UNAUTHORIZED`); then request-body well-formedness (`ERR_VALIDATION` — required fields present, enum values in range, and `requested_analytes` a non-empty subset of `BACTERIA`, `NITRATE`, `LEAD`); then, specifically for a sample result, the non-negativity of concentrations (`ERR_ANALYTE_OUT_OF_RANGE`); then existence of every referenced resource (the `ERR_*_NOT_FOUND` family); then state validity for the requested transition (the generic `ERR_INVALID_STATE` and its endpoint-specific siblings); then optimistic-concurrency version checks; then segregation-of-duties; then the domain safety, referential, temporal, and fiscal checks in the order given in §3. Wherever an endpoint-specific state error exists (for example `ERR_PERMIT_NOT_ISSUED`, `ERR_REQUIREMENT_NOT_OPEN`, `ERR_WELL_NOT_ACTIVE`), it is raised in place of the generic `ERR_INVALID_STATE` for that endpoint.

### 2.10. Optimistic Concurrency Control

One operation in the system is guarded by optimistic concurrency control: attaching a candidate sample to a real-estate test requirement. Because each attachment legitimately supersedes the prior candidate — a party may swap in a newer passing test — the requirement stays open across attachments, and the only way to distinguish a client acting on a stale view is the version. The attach request must carry `expected_requirement_version`, the `version` of the target `RealEstateTestRequirement` the client last observed. If that value does not equal the requirement's current `version` — because an earlier attachment already advanced it since the client read the record — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a candidate it never saw. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Registry Foundations: Aquifers, Applicants, Drillers, and Wells

Before any permitting can occur, a health officer seeds the registry with configuration and party records. An aquifer record captures the hydrogeologic rules for a groundwater basin: its `name`, its `sensitivity` (`HIGH`, `MODERATE`, or `LOW`), the minimum required distances from a wellhead to the nearest septic system (`min_setback_septic_ft`) and to the nearest property line (`min_setback_property_line_ft`), and the minimum permitted drilling depth for the basin (`min_well_depth_ft`). Aquifers are immutable once created. A health officer also registers each applicant by `full_name`, `email`, and two-letter USPS `mailing_state`; a newly registered applicant starts with `net_fees_paid_cents` of 0. Drillers are registered with a `license_number`, the two-letter `license_state` that issued it, and a `license_expires_on` instant; a new driller's `status` begins as `ACTIVE`. A health officer may later suspend a driller, moving `status` to `SUSPENDED`; a suspended driller can neither file logs nor complete abandonments.

A well owner creates the well registry record themselves. Creating a well requires the owning `applicant_id`, the `aquifer_id` of the drawn basin, the wellhead `latitude` and `longitude` in decimal degrees, the `parcel_apn` (assessor parcel number) of the hosting parcel, and the `intended_use` — `DOMESTIC`, `IRRIGATION`, or `LIVESTOCK`. A new well is born in registry status `PROPOSED` and potability status `UNKNOWN`, with `active_advisory_count` at 0 and `depth_ft` unset. Wells can be listed and filtered by owning applicant, by aquifer, and by either status dimension.

### 3.2. Construction Permitting: Application, Fee, and Review

The construction of a well is authorized by a construction permit, which a well owner submits for a well they own; a well is typically still `PROPOSED` at this point, but the well's `registry_status` is not gated at submission — submission is accepted regardless of the well's current registry status. The application carries the `well_id`, the `applicant_id` (which must equal the well's owning applicant — a mismatch is rejected with `ERR_APPLICANT_MISMATCH`, HTTP 409), the assigned `driller_id`, the applicant's `proposed_depth_ft`, the measured `setback_septic_ft` and `setback_property_line_ft` distances from the wellhead, the driller's on-site work window given as `scheduled_start` and `scheduled_end` (the end must be strictly after the start, otherwise the request is rejected with `ERR_VALIDATION` (HTTP 400) as a body well-formedness failure, checked before any referenced-resource existence check), and an optional `expedite` flag defaulting to false. A new permit enters status `SUBMITTED` with `fee_paid` false, `fee_charged_cents` at 0, and `fee_refunded_cents` at 0.

At submission the system computes the permit's fee **estimate** and stores it in `fee_estimate_cents`. The estimate is built from three ingredients. First, a depth base is chosen by tier from the proposed depth: a depth of at most 100 feet yields a base of 15000 cents; a depth greater than 100 but at most 300 feet yields 25000 cents; a depth greater than 300 feet yields 40000 cents. Second, this depth base is multiplied by an intended-use multiplier drawn from the well: 1.0 for `DOMESTIC`, 1.2 for `IRRIGATION`, and 1.5 for `LIVESTOCK`; this product is rounded half-up to a whole number of cents. Third, to that rounded amount the system adds an aquifer sensitivity surcharge — 10000 cents for a `HIGH` aquifer, 5000 cents for a `MODERATE` aquifer, and nothing for a `LOW` aquifer — and then, only if the permit is expedited, a further 20000-cent expedite fee. The estimate uses the applicant's proposed depth; the same formula is later re-run against the driller's actual depth to produce the final fee (see §3.3).

Paying a permit is an applicant action available on a submitted permit: it sets `fee_paid` to true, copies `fee_estimate_cents` into `fee_charged_cents`, and triggers a recomputation of the paying applicant's `net_fees_paid_cents`. A health officer then reviews the submitted permit. Approval enforces two gates in a fixed order: first the **setback safety** check, then the **fee** check. The setback check requires that the measured septic setback is at least the aquifer's `min_setback_septic_ft` and that the measured property-line setback is at least the aquifer's `min_setback_property_line_ft`; if either falls short, approval is rejected with `ERR_SETBACK_VIOLATION` (HTTP 422). Only if the setbacks pass does the officer's approval then require that the fee has been paid; an unpaid permit is rejected with `ERR_FEE_UNPAID` (HTTP 402). Because safety precedes fiscal, a permit that violates setbacks and is also unpaid surfaces the setback violation, not the unpaid fee. A successful approval moves the permit from `SUBMITTED` to `APPROVED`.

Alternatively, a health officer may deny a submitted permit. Denial moves it from `SUBMITTED` to `DENIED` and, if the fee had been paid, issues a compensating refund: `fee_refunded_cents` is set to the current `fee_charged_cents`, and the applicant's `net_fees_paid_cents` is recomputed so the refund is reflected. Denying an unpaid permit refunds nothing.

Issuing an approved permit is the officer action that both reserves the driller's calendar and advances the well. Issuance is permitted only from `APPROVED` status and only if the assigned driller's work window is free. Specifically, the assigned driller must have no other permit in `ISSUED` or `COMPLETED` status whose scheduled window, when each side is expanded by the travel buffer `DRILL_TRAVEL_BUFFER_HOURS` (4 hours), overlaps this permit's scheduled window; the windows are treated as half-open on `[scheduled_start, scheduled_end)`. A conflict is rejected with `ERR_DRILLER_SCHEDULE_CONFLICT` (HTTP 409). On success the permit moves from `APPROVED` to `ISSUED`; the system stamps `issued_on` with the current instant and sets `expires_on` to `issued_on` plus the permit validity period `PERMIT_VALIDITY_DAYS` (365 days); and, as a cross-entity side effect, the well moves from registry status `PROPOSED` to `PERMITTED`.

### 3.3. Driller Logs, Fee Finalization, and Well Activation

When drilling is finished, the assigned driller files a driller log against the issued permit. The log carries the `construction_permit_id` it completes, the acting `driller_id`, the actual `total_depth_ft`, the `static_water_level_ft` (depth to standing water), the `casing_depth_ft` (depth of the surface casing), the `grout_type` (`BENTONITE`, `CEMENT`, or `NEAT_CEMENT`), and the `completed_on` instant. Several checks guard this filing, applied in the following order. The referenced permit must be in `ISSUED` status; a log against a permit in any other status is rejected with `ERR_PERMIT_NOT_ISSUED` (HTTP 409). Next, the driller's license must be valid at the moment of filing: the driller's `status` must be `ACTIVE` and the completion instant must fall strictly before the driller's `license_expires_on`; a suspended or lapsed license is rejected with `ERR_DRILLER_LICENSE_INVALID` (HTTP 422). Finally, the filing driller must be the one assigned to the permit — the log's `driller_id` must equal the permit's assigned driller — otherwise the filing is rejected with `ERR_DRILLER_NOT_ASSIGNED` (HTTP 409). Because the license check precedes the assignment check, a filing whose driller both holds an invalid license and is not the assigned driller surfaces `ERR_DRILLER_LICENSE_INVALID`.

Filing the log completes the permit and activates the well in one cascade. The permit moves from `ISSUED` to `COMPLETED`. The system recomputes the permit fee **final** variant from the actual drilled depth — the identical tiered formula from §3.2, but now keyed on `total_depth_ft` rather than the proposed depth — and stores it in `fee_final_cents`; it then sets `fee_charged_cents` to that final amount, replacing the previously charged estimate. The paying applicant's `net_fees_paid_cents` is reconciled by the delta between final and estimate so the ledger reflects the true charge. Finally the well takes on its measured depth — `depth_ft` is set to the log's `total_depth_ft` — and the well's registry status advances from `PERMITTED` to `ACTIVE`, making it eligible for water sampling.

### 3.4. Water Sampling and the Laboratory Pipeline

A well owner submits a water sample only against an `ACTIVE` well; a submission against a well in any other registry status is rejected with `ERR_WELL_NOT_ACTIVE` (HTTP 409). The submission carries the `well_id`, the `submitted_by_applicant_id`, the `sample_type` (`ROUTINE`, `REAL_ESTATE`, or `CONTAMINATION_FOLLOWUP`), the `requested_analytes` (a non-empty subset of `BACTERIA`, `NITRATE`, and `LEAD`), the `collected_on` instant the sample was drawn, and an external `chain_of_custody_id`. A new sample enters status `SUBMITTED`.

At submission the system computes `panel_fee_cents`, the price of the requested laboratory panel. Each requested analyte has a base price — 3000 cents for `BACTERIA`, 2500 cents for `NITRATE`, and 4500 cents for `LEAD` — and each base price is multiplied by a regional factor of 1.075. The order of operations is fixed and consequential: the system multiplies each requested analyte's base by 1.075, rounds that single line half-up to a whole cent, and only after every line is individually rounded does it sum the rounded lines into `panel_fee_cents`. Rounding the summed total instead of the individual lines would differ by a cent and is incorrect.

The laboratory then walks the sample through its pipeline. A lab analyst receives the sample, moving it from `SUBMITTED` to `RECEIVED`; begins analysis, moving it from `RECEIVED` to `IN_ANALYSIS`; and finally records results (see §3.5), which moves it from `IN_ANALYSIS` to `RESULTED`. Each step requires the sample to be in the immediately preceding status; an out-of-order call is rejected with `ERR_INVALID_STATE` (HTTP 409). Separately, a health officer may invalidate a sample that has already been resulted, moving it from `RESULTED` to `INVALIDATED`; invalidation triggers a recomputation of the well's potability status from the latest remaining resulted sample (see §3.5), so that a withdrawn result no longer influences the health picture. This recomputation is the reconciling variant (not the direct single-result assignment used when a fresh result is recorded): if the well has any contamination case that is not `CLOSED` (that is, in `OPEN`, `INVESTIGATING`, `MITIGATION`, or `RESOLVED`), potability is forced to `UNSAFE` regardless of remaining samples; otherwise potability is taken from the confirmed grade of the latest remaining resulted sample (ordered as in §3.5); and if no resulted sample remains, potability is set to `UNKNOWN`.

### 3.5. Recording Results: Advisory Levels and the Contamination Cascade

Recording a laboratory result is a lab-analyst action against a sample that is `IN_ANALYSIS`; a result for a sample in any other status is rejected with `ERR_INVALID_STATE` (HTTP 409). The result carries the `water_sample_id`, the total-coliform reading `bacteria_coliform` and the E. coli reading `ecoli` (each `PRESENT`, `ABSENT`, or `NOT_TESTED`), the `nitrate_mg_l` concentration in milligrams per liter, the `lead_ppb` concentration in parts per billion, and the `analyzed_on` instant. Both concentrations must be non-negative; a negative `nitrate_mg_l` or `lead_ppb` is rejected with `ERR_ANALYTE_OUT_OF_RANGE` (HTTP 400). Recording the result creates an immutable `SampleResult` row and moves the sample from `IN_ANALYSIS` to `RESULTED`.

From the result the system derives an advisory level using a common grading rule. Given a nitrate value together with the bacteria, E. coli, and lead readings, the grade is `UNSAFE` if either bacterial reading is `PRESENT`, or the lead value is at least the lead action level of 15.0 parts per billion, or the nitrate value is at least the nitrate maximum contaminant level of 10.0 milligrams per liter; otherwise the grade is `ADVISORY` if the nitrate value is at least the nitrate advisory level of 5.0 milligrams per liter; otherwise the grade is `SAFE`.

Two grades are computed and stored. The **provisional** level, `advisory_level_provisional`, applies the grading rule to this sample's own nitrate value, ignoring history. The **confirmed** level, `advisory_level_confirmed`, applies the grading rule to a two-sample running nitrate average. To form that average, the system locates the single most recent *other* resulted result on the same well — considering only results whose sample is `RESULTED` (never `INVALIDATED`), ordered by the sample's `collected_on` descending with ties broken by the result's `created_at` descending. If such a prior result exists, the confirmed nitrate is the average of this sample's nitrate and the prior sample's nitrate, rounded half-up to three decimal places; if no prior result exists, the confirmed nitrate is simply this sample's nitrate. The confirmed grade then applies the grading rule to that confirmed nitrate together with this sample's bacteria, E. coli, and lead readings. Because the confirmed level blends in an elevated prior sample, it can reach `UNSAFE` while the provisional level for the same sample remains only `ADVISORY`.

The result also records `exceedances`, the subset of `BACTERIA`, `NITRATE`, and `LEAD` that breached its confirmed threshold: `BACTERIA` when either bacterial reading is `PRESENT`, `NITRATE` when the confirmed nitrate is at least 10.0 milligrams per liter, and `LEAD` when the lead value is at least 15.0 parts per billion.

The confirmed level drives the well's health dimension. The system recomputes `potability_status` from the confirmed grade of this newly recorded result: a `SAFE` confirmed grade sets potability to `POTABLE`, an `ADVISORY` grade sets it to `ADVISORY`, and an `UNSAFE` grade sets it to `UNSAFE`. This is the mapping used everywhere potability is recomputed from a result. When the confirmed grade is `UNSAFE`, a further cascade fires: the system auto-opens a contamination case on the well in status `OPEN` with its `source_sample_id` pointing at the triggering sample, a `severity` of `HIGH`, and `opened_by_officer_id` set to null (the cascade is triggered by the lab-analyst result, not by an officer, so no officer identity is recorded — and `closed_by_officer_id` and `resolution_notes` remain null); and as that case's own entry side effects it sets the well's `potability_status` to `UNSAFE`, auto-issues an active advisory whose `source_case_id` is the new case, and increments the well's `active_advisory_count` by one. The auto-issued advisory carries `advisory_type` `DO_NOT_DRINK`, an `effective_from` equal to the current logical-clock instant and an `effective_to` 365 days after it, and a system-generated `reason` string. This is a depth-three cascade: recording the result moves the sample to `RESULTED`, that transition opens the contamination case, and the case's creation issues the advisory and bumps the well's derived counts and health status.

### 3.6. Health Advisories

Beyond the advisories the contamination cascade issues automatically, a health officer may issue an advisory by hand. A manual advisory carries the `well_id`, the `advisory_type` (`BOIL_WATER`, `DO_NOT_DRINK`, `NITRATE`, or `LEAD`), the active window given as `effective_from` and `effective_to` (the end must be strictly after the start, otherwise the request is rejected with `ERR_VALIDATION`, HTTP 400, as a body well-formedness failure checked before referenced-resource existence), and a free-text `reason`. A manual advisory is created `ACTIVE` with `source_case_id` null, and it increments the well's `active_advisory_count`. Before it is issued, the system guards against overlapping advisories of the same kind: if any existing `ACTIVE` advisory of the same `advisory_type` on the well has a closed interval `[effective_from, effective_to]` that overlaps the proposed interval — where two closed intervals overlap when each starts no later than the other ends — the request is rejected with `ERR_ADVISORY_WINDOW_OVERLAP` (HTTP 409). Advisories of different types, or lifted advisories, never conflict.

A health officer may lift any active advisory, moving its `status` from `ACTIVE` to `LIFTED` and decrementing the well's `active_advisory_count`. Advisories can be listed and filtered by well, by originating case, by status, and by type.

### 3.7. Contamination Casework and Segregation of Duties

A contamination case may arise automatically from an unsafe confirmed result (see §3.5) or be opened by hand. A health officer manually opens a case with the `well_id`, a `severity` (`LOW`, `MODERATE`, `HIGH`, or `CRITICAL`), and optionally the `source_sample_id` that prompted it. A manually opened case starts in status `OPEN`, records the opening officer's `X-User-ID` as `opened_by_officer_id`, and sets the well's `potability_status` to `UNSAFE`.

A case advances through a defined progression under health-officer control. From `OPEN` it moves to `INVESTIGATING`, from `INVESTIGATING` to `MITIGATION`, and from `MITIGATION` to `RESOLVED`; each of these steps is requested by naming the desired next status in a `to_status` field, and each requires the case to currently be in the immediately preceding status, otherwise the transition is rejected with `ERR_INVALID_STATE` (HTTP 409). A `to_status` value that is not one of the recognized case statuses (`OPEN`, `INVESTIGATING`, `MITIGATION`, `RESOLVED`, `CLOSED`) is rejected earlier with `ERR_VALIDATION` (HTTP 400) as a well-formedness failure; naming a recognized status that is nonetheless not a legal next step — including `CLOSED`, which is reached only through the dedicated close endpoint — yields `ERR_INVALID_STATE`. A resolved case is not necessarily final: from `RESOLVED` the officer may reopen the case back to `INVESTIGATING`, again by supplying `to_status`, forming a cycle that lets a case that resurfaces be worked again. Each accepted transition advances the case's `version`.

Closing a case is the terminal step and the point at which segregation of duties is enforced. A case may be closed only from `RESOLVED` status, and only by an officer different from the one who opened it: the closing officer's `X-User-ID` must not equal the case's `opened_by_officer_id`, or the close is rejected with `ERR_SELF_CLOSE_FORBIDDEN` (HTTP 403). A successful close carries optional `resolution_notes`, records the closing officer as `closed_by_officer_id`, and moves the case to `CLOSED`. Closing also runs a cleanup cascade: every `ACTIVE` advisory whose `source_case_id` is this case is lifted (moved from `ACTIVE` to `LIFTED`) and the well's `active_advisory_count` is decremented accordingly; then the well's `potability_status` is recomputed from the confirmed level of the latest remaining resulted sample, using the same `SAFE`→`POTABLE`, `ADVISORY`→`ADVISORY`, `UNSAFE`→`UNSAFE` mapping. This recomputation is the reconciling variant: if any other contamination case on the well is still not `CLOSED` (in `OPEN`, `INVESTIGATING`, `MITIGATION`, or `RESOLVED`), potability is forced to `UNSAFE` irrespective of samples; and if no resulted sample remains, potability is set to `UNKNOWN`. Because potability only returns to a healthy value once no case remains open, a well can climb back out of `UNSAFE` only after its last blocking case is resolved and closed.

### 3.8. Abandonment and Decommissioning

When a well reaches the end of its life, its owner submits an abandonment (decommission) permit carrying the `well_id`, the `applicant_id` (which must equal the well's owning applicant, else `ERR_APPLICANT_MISMATCH`, HTTP 409), the `driller_id` who will perform the work, the `reason` (`DRY`, `CONTAMINATED`, `REPLACED`, or `CODE_VIOLATION`), and the `method` (`PERFORATE_FILL`, `OVERDRILL`, or `EXCAVATE`). A new abandonment permit enters status `SUBMITTED`.

A health officer reviews the submission. Approval requires two things beyond the submitted status: the well must currently be `ACTIVE` (a well in any other registry status is rejected with `ERR_WELL_NOT_ACTIVE`, HTTP 409), and there must be no outstanding construction work — no construction permit on the same well may be in a non-terminal status of `SUBMITTED`, `APPROVED`, or `ISSUED`; if such a permit exists the approval is rejected with `ERR_ABANDONMENT_BLOCKED` (HTTP 409). A successful approval moves the abandonment permit from `SUBMITTED` to `APPROVED`. Alternatively the officer may deny it, moving it from `SUBMITTED` to `DENIED`.

The assigned driller completes an approved abandonment. Completion requires the abandonment permit to be `APPROVED` and the acting driller to be the permit's assigned driller with a valid license. These are checked in order after the `APPROVED` state check: first the acting principal's `X-User-ID` must equal the permit's assigned `driller_id`, and if it does not the completion is rejected with `ERR_UNAUTHORIZED` (HTTP 403); then the license must be valid — the driller's `status` must be `ACTIVE` and the completion instant must fall strictly before the driller's `license_expires_on`, otherwise the completion is rejected with `ERR_DRILLER_LICENSE_INVALID` (HTTP 422). On completion the permit's `completed_on` is stamped with the current instant, the permit moves from `APPROVED` to `COMPLETED`, and, as a cross-entity effect, the well's registry status advances from `ACTIVE` to the terminal `DECOMMISSIONED`.

### 3.9. Real-Estate Test Requirements

A property sale or refinance can require a passing water test. Either an applicant or a health officer creates a real-estate test requirement carrying the `well_id`, the responsible `applicant_id`, the `transaction_type` (`SALE` or `REFINANCE`), the `closing_date` of the transaction, and an optional `required_analytes` list that defaults to all three of `BACTERIA`, `NITRATE`, and `LEAD`. A new requirement is `OPEN` with `linked_sample_id` null.

The responsible applicant attaches a candidate sample to the requirement, supplying the `linked_sample_id` of the chosen water sample and the `expected_requirement_version` (see §2.10); the endpoint requires the `Applicant` role but does not verify that the caller's `X-User-ID` matches the requirement's responsible `applicant_id`. Attachment is allowed only while the requirement is `OPEN`; an attempt against a requirement in any other status is rejected with `ERR_REQUIREMENT_NOT_OPEN` (HTTP 409). The checks then proceed in order: the version guard (`ERR_STALE_VERSION`, HTTP 412) as described in §2.10; then the temporal validity window; then the sample-safety check. The window requires that the sample was collected no later than the transaction's closing and not too long before it: the sample's `collected_on` must be at or before the `closing_date`, and the gap from collection to closing must be no greater than the real-estate validity span `REAL_ESTATE_TEST_VALIDITY_DAYS` (90 days); a violation is rejected with `ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW` (HTTP 422). The safety check requires that the linked sample is `RESULTED` and that its result's `advisory_level_confirmed` is `SAFE`; otherwise the attachment is rejected with `ERR_SAMPLE_NOT_SAFE` (HTTP 422). A successful attachment sets `linked_sample_id` to the chosen sample, superseding any previously attached candidate, and advances the requirement's `version`. The requirement deliberately stays `OPEN` so that a newer passing sample can later supersede the current one; only the version guard distinguishes a client acting on a stale view.

A health officer certifies a requirement, moving it from `OPEN` to `SATISFIED`; certification requires that the requirement is `OPEN` and that a candidate sample is currently attached (`linked_sample_id` is not null). A requirement that is not `OPEN` is rejected with `ERR_REQUIREMENT_NOT_OPEN` (HTTP 409); an `OPEN` requirement with no candidate attached is rejected with `ERR_INVALID_STATE` (HTTP 409), the requirement-state check preceding the candidate-presence check. An officer may instead waive a requirement, moving it from `OPEN` to `WAIVED` and optionally recording a `reason`; waiving a requirement that is not `OPEN` is likewise rejected with `ERR_REQUIREMENT_NOT_OPEN`. Requirements can be listed and filtered by well, by responsible applicant, by attached sample, and by status.

### 3.10. Time, Expiry, and the Logical Clock

The service runs on a logical clock rather than wall-clock time so that time-dependent behavior is deterministic and test-driveable. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any call it holds precisely this default and never falls back to real-world time. A health officer advances it by supplying a new instant in the `to_iso8601` field; all timestamp stamping (`created_at`, `updated_at`, `issued_on`, `completed_on`, and the like) uses the current logical-clock instant.

A health officer runs the expiry sweep to age out overdue records in two ways. Any construction permit in `ISSUED` status whose `expires_on` is at or before the current instant is moved to `EXPIRED`. Any real-estate test requirement in `OPEN` status whose `closing_date` is strictly before the current instant — that is, the current instant is past the closing date — is moved to `EXPIRED`. Note the boundary difference: a permit expires once the current instant reaches its expiry instant, while a requirement expires only once the current instant is strictly beyond its closing date.

## 4. Endpoint Definitions

The following table lists every endpoint. Endpoints that create a new resource return HTTP 201; endpoints that modify or transition an existing resource, and all read endpoints, return HTTP 200. Request and response bodies are not repeated here — reconstruct them from the workflow narratives in §3, which specify the inputs each operation consumes and the side effects it produces.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/aquifers` | Create an aquifer configuration record | HealthOfficer |
| GET | `/aquifers/{id}` | Fetch an aquifer | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/applicants` | Register an applicant / well owner account | HealthOfficer |
| GET | `/applicants/{id}` | Fetch an applicant (an applicant may fetch its own record) | Applicant, HealthOfficer |
| POST | `/drillers` | Register a licensed driller | HealthOfficer |
| GET | `/drillers/{id}` | Fetch a driller | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/drillers/{id}/suspend` | Suspend a driller license | HealthOfficer |
| POST | `/wells` | Create a well registry record | Applicant |
| GET | `/wells/{id}` | Fetch a well | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/wells` | List/filter wells | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/wells/{id}/deactivate` | Deactivate an active well | HealthOfficer |
| POST | `/wells/{id}/reactivate` | Reactivate an inactive well | HealthOfficer |
| POST | `/construction-permits` | Submit a well-construction permit application | Applicant |
| GET | `/construction-permits/{id}` | Fetch a construction permit | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/construction-permits` | List/filter construction permits | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/construction-permits/{id}/pay` | Pay the permit fee estimate | Applicant |
| POST | `/construction-permits/{id}/approve` | Approve a submitted permit | HealthOfficer |
| POST | `/construction-permits/{id}/deny` | Deny a submitted permit; refund any paid fee | HealthOfficer |
| POST | `/construction-permits/{id}/issue` | Issue an approved permit; reserve the driller window | HealthOfficer |
| POST | `/driller-logs` | File the completion log for an issued permit | Driller |
| GET | `/driller-logs/{id}` | Fetch a driller log | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/driller-logs` | List/filter driller logs | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/water-samples` | Submit a water sample for an active well | Applicant |
| GET | `/water-samples/{id}` | Fetch a water sample | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/water-samples` | List/filter water samples | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/water-samples/{id}/receive` | Lab receives the sample | LabAnalyst |
| POST | `/water-samples/{id}/begin-analysis` | Lab begins analysis | LabAnalyst |
| POST | `/water-samples/{id}/invalidate` | Invalidate a resulted sample | HealthOfficer |
| POST | `/sample-results` | Record lab results | LabAnalyst |
| GET | `/sample-results/{id}` | Fetch a sample result | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/sample-results` | List/filter sample results | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/advisories` | Manually issue a health advisory | HealthOfficer |
| GET | `/advisories/{id}` | Fetch an advisory | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/advisories` | List/filter advisories | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/advisories/{id}/lift` | Lift an active advisory | HealthOfficer |
| POST | `/contamination-cases` | Manually open a contamination case | HealthOfficer |
| GET | `/contamination-cases/{id}` | Fetch a contamination case | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/contamination-cases` | List/filter contamination cases | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/contamination-cases/{id}/transition` | Advance or reopen a case status | HealthOfficer |
| POST | `/contamination-cases/{id}/close` | Close a resolved case | HealthOfficer |
| POST | `/abandonment-permits` | Submit an abandonment / decommission permit | Applicant |
| GET | `/abandonment-permits/{id}` | Fetch an abandonment permit | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/abandonment-permits` | List/filter abandonment permits | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/abandonment-permits/{id}/approve` | Approve an abandonment permit | HealthOfficer |
| POST | `/abandonment-permits/{id}/deny` | Deny an abandonment permit | HealthOfficer |
| POST | `/abandonment-permits/{id}/complete` | Complete the decommission | Driller |
| POST | `/real-estate-requirements` | Create a real-estate test requirement | Applicant, HealthOfficer |
| GET | `/real-estate-requirements/{id}` | Fetch a real-estate test requirement | Applicant, Driller, LabAnalyst, HealthOfficer |
| GET | `/real-estate-requirements` | List/filter real-estate test requirements | Applicant, Driller, LabAnalyst, HealthOfficer |
| POST | `/real-estate-requirements/{id}/link-sample` | Attach or supersede a candidate sample | Applicant |
| POST | `/real-estate-requirements/{id}/certify` | Certify the requirement as satisfied | HealthOfficer |
| POST | `/real-estate-requirements/{id}/waive` | Waive the requirement | HealthOfficer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | HealthOfficer |
| POST | `/_ops/expiry-sweep` | Expire past-due issued permits and open requirements | HealthOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_VALIDATION | 400 |
| ERR_ANALYTE_OUT_OF_RANGE | 400 |
| ERR_APPLICANT_NOT_FOUND | 404 |
| ERR_DRILLER_NOT_FOUND | 404 |
| ERR_AQUIFER_NOT_FOUND | 404 |
| ERR_WELL_NOT_FOUND | 404 |
| ERR_PERMIT_NOT_FOUND | 404 |
| ERR_DRILLER_LOG_NOT_FOUND | 404 |
| ERR_SAMPLE_NOT_FOUND | 404 |
| ERR_RESULT_NOT_FOUND | 404 |
| ERR_ADVISORY_NOT_FOUND | 404 |
| ERR_CASE_NOT_FOUND | 404 |
| ERR_ABANDONMENT_NOT_FOUND | 404 |
| ERR_REQUIREMENT_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_PERMIT_NOT_ISSUED | 409 |
| ERR_REQUIREMENT_NOT_OPEN | 409 |
| ERR_WELL_NOT_ACTIVE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_SELF_CLOSE_FORBIDDEN | 403 |
| ERR_SETBACK_VIOLATION | 422 |
| ERR_DRILLER_LICENSE_INVALID | 422 |
| ERR_DRILLER_NOT_ASSIGNED | 409 |
| ERR_APPLICANT_MISMATCH | 409 |
| ERR_SAMPLE_OUTSIDE_VALIDITY_WINDOW | 422 |
| ERR_DRILLER_SCHEDULE_CONFLICT | 409 |
| ERR_ADVISORY_WINDOW_OVERLAP | 409 |
| ERR_SAMPLE_NOT_SAFE | 422 |
| ERR_ABANDONMENT_BLOCKED | 409 |
| ERR_FEE_UNPAID | 402 |


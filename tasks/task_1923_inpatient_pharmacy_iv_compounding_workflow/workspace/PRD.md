# Inpatient Pharmacy IV Compounding API — Product Requirements Document

## 1. Introduction

Hospital inpatient pharmacies operate at the intersection of clinical judgment, sterile compounding discipline, and controlled-substance accountability. Every intravenous dose that reaches a patient's bedside passes through a chain of custody — prescriber order, pharmacist verification, technician compounding under USP 797/800 cleanroom conditions, QA release, cabinet dispensing, and bedside administration — and every link in that chain must be auditable, replayable, and defensible in front of a state board of pharmacy. Errors at any step are not abstract data-quality issues; they are medication errors, diversion events, or regulatory citations.

This document specifies the Inpatient Pharmacy IV Compounding API, the system of record for that chain. It governs order verification with renal dose adjustment and dose rounding, USP 797 beyond-use dating with manufacturer stability extension, hazardous-drug compounding gating under USP 800, automated dispensing cabinet (ADC) inventory with a chronological ledger and discrepancy escalation, controlled-substance diversion risk scoring, drug-shortage substitution protocols, and the batch yield and waste accounting that QA pharmacists use to decide whether a compounding run may be released. All temporal reasoning — certification expiry, beyond-use expiry, protocol expiry, session windows, after-hours activity — is evaluated against a single server-controlled logical clock so that behavior is deterministic and reproducible.

The API is mounted under the `/pharmacy` path prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that apply uniformly across every endpoint: authentication and role resolution, the response envelope, pagination, resource identity, precision, concurrency control, the logical clock, and the priority order in which validation failures surface.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Once authenticated, the role is checked against the endpoint's authorized-role list (§4); a role not permitted to call the endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes six roles, spelled exactly as follows: `PharmacyAdmin`, `Prescriber`, `Pharmacist`, `PharmacyTechnician`, `Nurse`, and `DiversionOfficer`.

Two of these roles are **opaque**: when `X-User-Role` is `PharmacyAdmin` or `DiversionOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server does not compare it to any entity's `id`, and no existence check is performed against the staff roster for these two roles.

The remaining four roles are **entity-backed** by `StaffMember`. When `X-User-Role` is `Prescriber`, `Pharmacist`, `PharmacyTechnician`, or `Nurse`, `X-User-ID` is the `id` of the acting `StaffMember`. The server resolves the `StaffMember` row with that `id`; the row must exist, its `active` flag must be true, and its `staff_role` must equal the `X-User-Role` header value — so a call made as `Pharmacist` must present the `id` of a staff member whose `staff_role` is `PHARMACIST`. A missing row, an inactive row, or a `staff_role` that disagrees with the header is rejected with `ERR_ROLE_MISMATCH` (HTTP 403). Ownership checks throughout the workflow — the ordering prescriber on a discontinuation, the compounder barred from QA-ing their own batch, the witness barred from being the waste recorder — all compare a resource's foreign-key staff field against `X-User-ID`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. List responses carry four pagination fields in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Version Counter

Every resource carries `id`, a server-minted UUID with no type prefix, and `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at its initial value on creation and increments by exactly 1 on every mutation of that resource. Two resource families are deliberately leaner: a `ClinicalIntervention`, an `InventoryEvent`, and a `WasteRecord` each carry only `id` and `created_at` — they are append-only records, and both `updated_at` and `version` are absent from them.

The `version` counter is the backbone of optimistic concurrency control, and it is also a visible audit signal: every state transition, every cascade touch, and every field update on a versioned resource moves the counter by one. When a single call mutates several resources — for example a discontinuation that also cancels preparations, a batch, and a hood session — each affected resource's `version` increments independently, and each affected resource's `updated_at` refreshes.

### 2.5. Optimistic Concurrency Control

Two write endpoints require an explicit optimistic-concurrency field, and the requirement is non-optional: the field must be present on every call, and a mismatch is always rejected.

Creating a medication order requires the request to carry `expected_patient_version`, the `version` of the target `PatientProfile` as the client last observed it. If the patient's current `version` has advanced since that observation — for example because another order creation against the same patient superseded a prior open order and bumped the patient's version — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against a patient record it has not observed. A successful create itself increments the patient's `version` by 1.

Restocking an ADC pocket requires the request to carry `expected_pocket_version`, the `version` of the target `ADCPocket` as the client last observed it. Restock is otherwise always legitimate on an `ACTIVE` pocket, so the sole OCC ground for rejection is that another ledger mutation — a restock, dispense, return, waste, or adjustment — advanced the pocket's `version` after the client's physical observation; such a call is rejected with `ERR_STALE_VERSION` (HTTP 412).

Two further endpoints accept an optional version guard: order verification and order resumption each accept `expected_order_version`, and batch completion accepts `expected_batch_version`. When one of these optional fields is supplied, it is checked against the resource's current `version` and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412); when it is omitted, the call proceeds without an OCC check. Endpoints not named in this subsection take no version field at all.

### 2.6. The Logical Clock

All temporal evaluation in the system — session windows, certification expiry, beyond-use expiry, protocol expiry, the 30-day diversion window, after-hours classification, and age computation — reads a single server-held logical clock, never the host wall clock. Before any client sets it, the logical clock reads exactly `2026-08-01T00:00:00Z`.

A `PharmacyAdmin` advances the clock through a test-driving capability that accepts a `to_iso8601` instant and returns the new `now`. Setting the clock runs two expiry sweeps before the response is returned, and the same sweeps are evaluated before any dispense is processed: first, every compounded preparation whose `bud_expiry` has been reached or passed — that is, the logical clock is at or after `bud_expiry`, the boundary itself counts as expired — and whose status is `COMPOUNDED` or `QA_PASSED` transitions to `EXPIRED`, with a waste record appended for each expired preparation carrying the reason `EXPIRED`; second, every substitution protocol in `ACTIVE` whose `expires_at` has been reached or passed transitions to `EXPIRED`, running the same compensation cascade as a manual revocation.

### 2.7. Validation Priority Order

When several checks could fail on the same request, the system reports failures in a fixed priority order so that callers see the most fundamental problem first. The order is: authentication headers first (`ERR_UNAUTHENTICATED`); then role permission (`ERR_FORBIDDEN`); then the entity-backed staff resolution (`ERR_ROLE_MISMATCH`); then request-body well-formedness — required fields present, types valid, enum values in range (`ERR_INVALID_REQUEST`); then path-identifier existence, validated left to right (`ERR_NOT_FOUND`); then body-referenced foreign-key existence (`ERR_NOT_FOUND`); then the optimistic-concurrency check (`ERR_STALE_VERSION`); then the terminal-state guard (`ERR_ORDER_ALREADY_TERMINAL`); then the state-machine from-state check (`ERR_INVALID_STATE`); then business-safety rules (allergy screen, hazardous-drug certification, hood rating, waste witnessing, segregation of duties, prescriber ownership); then business-constraint rules (quantities, hood overlap, coverage capacity, pocket capacity, stock sufficiency, drug match, waste tolerance); then business-temporal rules (session window, session active, beyond-use expiry, protocol expiry); and finally business-referential rules (verification required, preparation QA-passed, pocket active, formulary status, substitution preconditions). A failure at any tier masks every lower tier: a call that is both unauthenticated and against a non-existent resource surfaces only `ERR_UNAUTHENTICATED`.

### 2.8. Nested Resource Retrieval

Whenever an endpoint path contains resource identifiers, the system validates them sequentially, left to right, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. Body-referenced foreign keys — such as the patient, drug, hood, protocol, or witness named inside a request payload — are validated for existence after the path identifiers, and a dangling reference likewise yields `ERR_NOT_FOUND`.

### 2.9. Precision and Rounding

All clinical quantities in this system are computed and stored at 2 decimal places using round-half-up, unless a rule states otherwise. This applies to body-mass index, ideal and adjusted body weight, creatinine clearance, renal-adjusted doses, waste overage percentages, and the diversion risk score. Dose volumes follow a step ladder rather than a fixed two-decimal rounding (§3.4), and the inventory ledger is integer-exact — pocket unit counts are whole units, never fractional. Beyond-use dating is computed in whole hours and stored as an ISO 8601 UTC timestamp.

## 3. Business Logic & Workflows

This section walks the medication-use process in the order a dose travels through the hospital: the formulary and staffing configuration that makes work possible; the patient's clinical panel; the order and its verification; the compounding batch and its quality gates; the cabinet ledger; and the surveillance layers — discrepancies, diversion, and shortage substitution — that sit on top of the operational flow.

### 3.1. Staff, Formulary, Hoods, and Coverage: the Configuration Layer

A `PharmacyAdmin` registers each staff member with a `full_name` and a `staff_role` drawn from `PRESCRIBER`, `PHARMACIST`, `TECHNICIAN`, or `NURSE`. Note that the roster enum uses `TECHNICIAN` while the calling role header uses `PharmacyTechnician`; the staff row's `staff_role` must equal the header value's corresponding enum as described in §2.1. Staff who compound hazardous drugs carry `hd_compounding_certified` set to true together with `hd_cert_expires_at`, the certification expiry timestamp; when the certification flag is false, the expiry is null. Every staff member also carries a system-managed `active` flag, initially true; an inactive staff member may not act, and calls presenting their `id` fail the role-resolution check. The staff directory can be listed with an optional `staff_role` filter.

The formulary is a catalog of drug products, each registered by a `PharmacyAdmin` with a `name` (the generic name and strength label), a controlled-substance `schedule` of `NON_CONTROLLED`, `C_II`, `C_III`, `C_IV`, or `C_V`, the `concentration_mg_per_ml` used to convert a milligram dose into a milliliter volume, and the `vial_size_ml` of a single vial, which the batch yield calculation consumes. Hazardous drugs are flagged with `is_hazardous`, which drives USP 800 hood and certification gating at batch start. Stability documentation is captured per storage condition: `has_stability_data` marks that manufacturer data exists, and `stability_hours_room`, `stability_hours_refrigerated`, and `stability_hours_frozen` hold the supported hours for each condition, each null when no data exists for that condition. The `renal_dosing_policy` selects which weight variant feeds the Cockcroft-Gault equation at verification — `IBW` (the default) or `ABW_WHEN_OBESE`. While a drug sits on the shortage list its `in_shortage` flag is true, which gates protocol activation; the flag and the formulary `status` (`ACTIVE` by default, `DISCONTINUED` when withdrawn) are the two fields a `PharmacyAdmin` can update on an existing drug, and either update increments the drug's `version`. The drug catalog is listable with `status`, `is_hazardous`, `schedule`, and `in_shortage` filters, and each drug also exposes the list of substitution protocols naming it as the shortage drug.

Compounding hoods are registered with a `name`, an `iso_class` of `ISO_5`, `ISO_7`, or `ISO_8`, and an `is_hd_rated` flag marking the hood as rated for USP 800 hazardous compounding. Hood time is a scarce, schedulable resource: a `PharmacyTechnician` reserves a hood window by supplying `hood_id`, `start_at`, and `end_at`. Windows are half-open intervals — `start_at` inclusive, `end_at` exclusive — and `end_at` must be strictly after `start_at`, otherwise the request fails with `ERR_INVALID_QUANTITY`. No two sessions on the same hood whose status is `SCHEDULED` or `IN_USE` may overlap; adjacency, where one session's `start_at` equals another's `end_at`, is allowed. An overlapping reservation is rejected with `ERR_HOOD_OVERLAP`. A session begins `SCHEDULED`; starting it (a `PharmacyTechnician` action) requires the logical clock to fall inside the window — at or after `start_at` and strictly before `end_at` — failing which the start is rejected with `ERR_HOOD_SESSION_OUTSIDE_WINDOW`, and a successful start moves the session to `IN_USE` and increments its `version`. From `IN_USE` the technician completes the session, moving it to `COMPLETED`; from either `SCHEDULED` or `IN_USE` the technician may cancel it, moving it to `CANCELLED`. Sessions are listable with `hood_id` and `status` filters.

Pharmacist zone coverage is scheduled by a `PharmacyAdmin` as coverage shifts, each naming a `staff_id`, a `zone` label such as `CENTRAL` or `SATELLITE_ER`, and a half-open `start_at`/`end_at` window with the same strict ordering requirement. At most two coverage shifts per zone may overlap at any instant; a new shift that would create a three-way overlap is rejected with `ERR_COVERAGE_CAP_EXCEEDED`. Coverage shifts are listable with `staff_id` and `zone` filters.

### 3.2. The Patient Renal Panel

A `PharmacyAdmin` registers each patient with `full_name`, `date_of_birth`, `sex` (`M` or `F`, which the Cockcroft-Gault equation consumes), `height_cm`, `weight_kg`, the serum creatinine `scr_mg_dl`, and optionally `allergy_drug_product_ids`, an array of drug product ids this patient must never receive (empty by default). Registration computes and stores the clinical panel that verification later reads, and the same recomputation runs whenever a `PharmacyAdmin` updates the panel — the updatable fields are `weight_kg`, `scr_mg_dl`, and `allergy_drug_product_ids` — with each update incrementing the patient's `version`.

The computed panel comprises six values. `age_years` is the whole-year floor between `date_of_birth` and the logical clock, with the birthday counting on the date itself. `bmi` is `weight_kg` divided by the square of `height_cm` expressed in meters, rounded half-up to 2 decimal places. `ibw_kg` is the ideal body weight: for a male, 50 plus 2.3 times the number of inches by which the patient's height exceeds 60 inches (height in inches being `height_cm` divided by 2.54); for a female, 45.5 plus the same 2.3-per-inch term; rounded half-up to 2 decimal places. `abw_kg` is the adjusted body weight — `ibw_kg` plus 0.4 times the excess of `weight_kg` over `ibw_kg`, at 2 decimal places — and is null whenever `bmi` is below 30. `crcl_ibw_ml_min` is the Cockcroft-Gault creatinine clearance computed with `ibw_kg`, and `crcl_abw_ml_min` the same computation with `abw_kg`, each rounded half-up to 2 decimal places, with `crcl_abw_ml_min` null whenever `bmi` is below 30. The Cockcroft-Gault computation itself is: take 140 minus `age_years`, multiply by the weight in use, multiply by 0.85 when the patient is female (1.0 when male), and divide by 72 times `scr_mg_dl`.

### 3.3. Ordering, Verification, and the Clinical Review Loop

A `Prescriber` creates a medication order by naming the `patient_id`, the `drug_product_id`, the administration `route` (`IV`, `PO`, or `IM`), the `ordered_dose_mg` per administration, the `frequency_per_day`, optionally the `duration_days` (defaulting to 1), and the OCC field `expected_patient_version` (§2.5). The creating prescriber's `X-User-ID` is captured as the order's `prescriber_staff_id`. A new order opens with `verification_status` of `PENDING` and `fulfillment_status` of `NONE`, with `substitution_pending` false and `substituted_by_protocol_id` null. The renal outputs — `crcl_used_ml_min`, `renal_adjusted_dose_mg`, and `final_dose_ml` — remain null until verification computes them, and `discontinue_reason` stays null unless the order is discontinued.

Order creation carries an implicit replacement rule: when the same prescriber creates an order for a patient and drug that already has an open order — one whose `verification_status` is `PENDING`, `VERIFIED`, or `ON_HOLD` and whose `fulfillment_status` is neither `DISPENSED` nor `ADMINISTERED` — the prior order is superseded: its `verification_status` becomes `SUPERSEDED`, its `version` increments, and the same three-level cancellation cascade described for discontinuation below runs against its preparations, batches, and hood sessions. This supersede is why order creation is OCC-guarded on the patient: a successful create also increments the patient's `version` by 1, so a client holding a pre-supersede patient version is necessarily acting on a stale view. Orders are listable with `patient_id`, `prescriber_staff_id`, `drug_product_id`, `verification_status`, `fulfillment_status`, and `substituted_by_protocol_id` filters.

Verification is a `Pharmacist` action on a `PENDING` order, optionally guarded by `expected_order_version`. Three preconditions guard it, surfacing in this order relative to the global priority tiers: the order must still be `PENDING` (a from-state failure yields `ERR_INVALID_STATE`); the ordered drug must not appear in the patient's `allergy_drug_product_ids` (an allergy hit is rejected with `ERR_ALLERGY_CONFLICT`); and the ordered drug's formulary `status` must be `ACTIVE` (a discontinued drug yields `ERR_DRUG_DISCONTINUED`). A successful verification performs three computations and one routing decision. First, the renal dose adjustment (§3.4) selects the weight variant per the drug's `renal_dosing_policy`, computes the creatinine clearance, maps it to a tier factor, and stores the chosen clearance in `crcl_used_ml_min` and the adjusted dose in `renal_adjusted_dose_mg`. Second, the dose-rounding step ladder converts `renal_adjusted_dose_mg` to a volume via the drug's `concentration_mg_per_ml` and stores it in `final_dose_ml`. Third, fulfillment routes by route: an `IV` order moves `fulfillment_status` from `NONE` to `QUEUED` to await compounding, while a non-IV order moves straight from `NONE` to `READY` for cabinet dispensing. Verification increments the order's `version` by 1.

The clinical review loop runs through intervention documentation. A `Pharmacist` documents an intervention on an order by supplying an `intervention_type` of `DOSE_CLARIFICATION`, `ALLERGY`, `RENAL`, `SHORTAGE`, or `OTHER`, a free-text `note`, and optionally `placed_on_hold` (default false). Every call appends an immutable `ClinicalIntervention` row stamped with the documenting pharmacist's `id` as `pharmacist_staff_id`; the row is a 201-created resource, listable per order and across the pharmacy with a `pharmacist_staff_id` filter. When `placed_on_hold` is true and the order is currently `PENDING` or `VERIFIED`, the order's `verification_status` moves to `ON_HOLD`. Resuming is the reverse `Pharmacist` action on an `ON_HOLD` order, again optionally guarded by `expected_order_version`: the allergy screen re-runs (an allergy now present yields `ERR_ALLERGY_CONFLICT`), the renal adjustment and final dose are recomputed because the patient panel may have changed, fulfillment moves from `NONE` to `QUEUED` for IV or `READY` for non-IV when it was still `NONE`, and the order returns to `VERIFIED` with its `version` incremented.

Discontinuation is the prescriber's prerogative, and only the ordering prescriber may exercise it: the caller's `X-User-ID` must equal the order's `prescriber_staff_id`, otherwise the call is rejected with `ERR_NOT_ORDER_PRESCRIBER`. The order's `verification_status` must be `PENDING`, `VERIFIED`, or `ON_HOLD`, and its `fulfillment_status` must be neither `DISPENSED` nor `ADMINISTERED` — a fulfillment already that far along makes the discontinuation an `ERR_INVALID_STATE`. Any mutation attempted on an order whose verification is already `DISCONTINUED` or `SUPERSEDED`, or whose fulfillment is `ADMINISTERED`, is rejected outright with `ERR_ORDER_ALREADY_TERMINAL`. A successful discontinuation stores the supplied `reason` in `discontinue_reason`, moves verification to `DISCONTINUED`, increments the order's `version`, and runs a three-level cascade. Level one: every `CompoundedPreparation` of this order in `PLANNED` or `COMPOUNDED` moves to `CANCELLED`. Level two: each affected batch recomputes its `demand_ml` and `vials_used`, and a batch left with zero preparations in `PLANNED`, `COMPOUNDED`, or `QA_PASSED` auto-transitions from `DRAFT` or `IN_PROGRESS` to `CANCELLED`. Level three: a batch cancelled at level two cancels its hood session when that session is `SCHEDULED` or `IN_USE`. The supersede path runs the identical cascade.

Administration is the terminal step: a `Nurse` marks a `DISPENSED` order administered, moving `fulfillment_status` to `ADMINISTERED` and incrementing the order's `version`.

### 3.4. Renal Dosing and the Dose-Rounding Step Ladder

Two calculations sit underneath verification, resumption, and substitution, and their wording here is the operative specification.

The renal dose adjustment begins from the patient panel. The age term is `age_years` as defined in §3.2 — whole years from `date_of_birth` to the logical clock, birthday inclusive. Height in inches is `height_cm` divided by 2.54. The ideal body weight is sex-linked: for `sex` `M`, 50 plus 2.3 times the inches above 60; for `sex` `F`, 45.5 plus 2.3 times the inches above 60; rounded half-up to 2 decimal places. Body-mass index is `weight_kg` over the square of `height_cm` in meters, 2 decimal places round-half-up. The weight actually fed to Cockcroft-Gault depends on the drug's `renal_dosing_policy`. Under the `IBW` policy the ideal body weight is used regardless of BMI — this is the `IBW`-variant behavior, in which identical inputs always yield the ideal-weight clearance. Under the `ABW_WHEN_OBESE` policy the choice turns on obesity: when `bmi` is at least 30, the weight used is the adjusted body weight — ideal plus 0.4 times the excess of actual over ideal, itself at 2 decimal places — and otherwise the actual `weight_kg` is used; for an obese patient the adjusted weight is higher than the ideal, so identical inputs yield a higher creatinine clearance and potentially a higher tier than the `IBW` policy would. Creatinine clearance is then 140 minus age, times the chosen weight, times 0.85 for a female patient or 1.0 for a male, divided by 72 times `scr_mg_dl`, rounded half-up to 2 decimal places; the rounded value is stored on the order as `crcl_used_ml_min`. The dose factor tiers off that rounded clearance: a clearance of at least 50 maps to a factor of 1.00; at least 30 but below 50 maps to 0.75; at least 10 but below 30 maps to 0.50; and below 10 maps to 0.25. The `renal_adjusted_dose_mg` is the `ordered_dose_mg` times the tier factor, rounded half-up to 2 decimal places.

The dose-rounding step ladder converts milligrams to milliliters and governs every volume the system reports. The step size depends on the raw value: below 1 the step is 0.1; from 1 up to and including 10 the step is 0.5; above 10 the step is 1.0. Rounding to a step means dividing the raw value by its step, rounding that quotient half-up to a whole number, and multiplying back by the step. The `final_dose_ml` of an order is the step-rounded value of `renal_adjusted_dose_mg` divided by the drug's `concentration_mg_per_ml`. The same ladder applies to milligram quantities during substitution. Wherever several component volumes feed an aggregate — the batch demand calculation is the case that matters — each component volume is rounded to its step first and only then summed. Summing first and rounding the total is explicitly not the policy and yields different results; implementations must round-then-sum.

### 3.5. Compounding: Batches, Preparations, and Quality Gates

A `PharmacyTechnician` opens a compounding batch by naming the `hood_session_id` it will occupy, the `order_ids` it will fulfill, the `usp_risk_level` of the run (`LOW`, `MEDIUM`, or `HIGH`), and optionally `documents_stability_source` (default false) to assert that the batch record cites the manufacturer stability source enabling extended dating. Every order named must be `VERIFIED` — including a non-verified order fails the whole create with `ERR_ORDER_NOT_VERIFIED` — and must be an `IV` order awaiting compounding. Creation writes one `CompoundedPreparation` row per order, each opening in `PLANNED` with its `batch_id` pointing at the new batch, its `order_id` at the order, and its `drug_product_id` denormalized from the order at that moment; each order's `fulfillment_status` moves from `QUEUED` to `COMPOUNDING`. The batch itself opens in `DRAFT` with `rework_count` 0 and `qa_pharmacist_staff_id` null, and its initial `demand_ml` and `vials_used` are computed from the planned preparations. The technician who created the batch is recorded as `compounder_staff_id` from `X-User-ID`.

Starting the batch is the technician's next step and carries the hazardous-drug gates. The batch must be in `DRAFT`. Its hood session must be `IN_USE` — starting against a session in any other state is rejected with `ERR_HOOD_SESSION_NOT_ACTIVE`. When any preparation's drug is hazardous, two further gates apply: the session's hood must have `is_hd_rated` true, otherwise `ERR_HOOD_NOT_HD_RATED`; and the compounder must hold current certification — `hd_compounding_certified` true with `hd_cert_expires_at` later than the logical clock — otherwise `ERR_HD_CERTIFICATION_REQUIRED`. At least one preparation must still be `PLANNED`. A successful start moves the batch to `IN_PROGRESS` and increments its `version`.

Completing the batch is where volumes, waste, and dating are pinned. The technician supplies `prepared_volumes_ml` — one entry per preparation currently `PLANNED`, so the count must match exactly, otherwise `ERR_INVALID_REQUEST` — a non-negative `waste_ml` (a negative value yields `ERR_INVALID_QUANTITY`), the `storage_condition` applied to the run's preparations (`ROOM`, `REFRIGERATED`, or `FROZEN`), and optionally `expected_batch_version` as an OCC guard. Completion moves every `PLANNED` preparation to `COMPOUNDED`, recording its `prepared_volume_ml` and `storage_condition`; computes the batch yield-and-waste figures and the per-preparation beyond-use expiry described below; appends a `WasteRecord` for the compounding waste with the batch reference set and `volume_ml` equal to the recorded waste; and moves the batch to `QA_REVIEW`, incrementing its `version`.

The batch yield calculation has a pinned evaluation order, because the size tier depends on quantities that must be computed first and re-evaluating vial counts against the tier is forbidden. First, `demand_ml` is the sum over the batch's non-cancelled preparations — those in `PLANNED` or `COMPOUNDED` — of each preparation's step-rounded volume: its order's `renal_adjusted_dose_mg` divided by the drug's `concentration_mg_per_ml`, rounded per the step ladder, then summed (round-then-sum, per §3.4). Second, `vials_used` is `demand_ml` divided by the batch drug's `vial_size_ml`, rounded up to a whole vial. Third, the drawn volume for this run is `vials_used` times `vial_size_ml`. Fourth, the run's waste is the recorded `waste_ml` input. Fifth, `overage_pct` is the run's waste divided by the run's drawn volume, times 100, rounded half-up to 2 decimal places. Sixth, the batch's size tier is read off the run's drawn volume: below 25 mL the batch is SMALL with a 60 percent waste tolerance; from 25 mL up to and including 100 mL it is MEDIUM with a 30 percent tolerance; above 100 mL it is LARGE with a 10 percent tolerance. Two batch figures are lifetime accumulators rather than per-run values: `total_drawn_ml` and the batch's own `waste_ml` each sum across all completions, so rework runs add to them. The `delivered_ml` is the sum of `prepared_volume_ml` over preparations currently `QA_PASSED` or `DISPENSED`. An invariant holds at every observable read: `total_drawn_ml` equals `delivered_ml` plus `waste_ml`. The same recompute runs whenever the order-discontinuation cascade touches the batch and whenever a rework creates fresh preparations.

Beyond-use dating is computed per preparation at completion. The base table is keyed by the batch's `usp_risk_level` and the preparation's `storage_condition`, in whole hours: a `LOW`-risk preparation keeps 48 hours at `ROOM`, 336 hours `REFRIGERATED`, and 1080 hours `FROZEN`; a `MEDIUM`-risk preparation keeps 30 hours at `ROOM`, 216 hours `REFRIGERATED`, and 1080 hours `FROZEN`; a `HIGH`-risk preparation keeps 24 hours at `ROOM`, 72 hours `REFRIGERATED`, and 1080 hours `FROZEN`. The default variant takes the table value directly. The stability-extended variant applies only when the drug's `has_stability_data` is true, the batch's `documents_stability_source` is true, and the drug's stability hours for the chosen storage condition are not null; in that case the beyond-use hours are the drug's stability hours for that condition, capped at 720 hours — so identical completion times yield a later expiry under the extended variant than under the table variant. The resulting `bud_expiry` is the completion timestamp (read from the logical clock) plus the beyond-use hours, stored as an ISO 8601 UTC instant, and it remains null until completion computes it. A preparation is expired when the logical clock reaches or passes `bud_expiry` — the boundary is inclusive-expired.

Quality review belongs to a `Pharmacist`, with segregation of duties enforced on both branches: the reviewing pharmacist's `X-User-ID` must differ from the batch's `compounder_staff_id`, and a self-review is rejected with `ERR_SOD_VIOLATION`. QA release additionally gates on waste: the batch's `overage_pct` must not exceed the tolerance of its size tier — 60 percent for SMALL, 30 percent for MEDIUM, 10 percent for LARGE — otherwise the release is rejected with `ERR_WASTE_TOLERANCE_EXCEEDED`. A successful release moves every `COMPOUNDED` preparation to `QA_PASSED`, moves every linked order's `fulfillment_status` from `COMPOUNDING` to `READY`, records the releasing pharmacist in `qa_pharmacist_staff_id`, and moves the batch to the terminal `RELEASED` state with its `version` incremented. QA rejection instead moves every `COMPOUNDED` preparation to `WASTED`, adds each rejected preparation's `prepared_volume_ml` into the batch's `waste_ml`, appends a `WasteRecord` with reason `QA_REJECT`, and moves the batch to `REJECTED`, incrementing its `version`.

A rejected batch gets up to two rework cycles. Calling rework on a `REJECTED` batch whose `rework_count` is below 2 increments `rework_count` by 1, creates fresh `PLANNED` preparations for linked orders still `VERIFIED` (preparations of discontinued or superseded orders stay `CANCELLED` or `WASTED`), and returns the batch to `DRAFT` with its `version` incremented. Calling rework when `rework_count` is already 2 does not cycle again: the same call instead moves the batch to the terminal `FAILED` state, returned with a 200 status — the rework cap of 2 has been reached. Separately, the system itself can cancel a batch: when the order cascade removes the last preparation in `PLANNED`, `COMPOUNDED`, or `QA_PASSED`, a batch in `DRAFT` or `IN_PROGRESS` moves to `CANCELLED` and its hood session, if `SCHEDULED` or `IN_USE`, is cancelled with it.

Preparations are listable per batch and across the pharmacy with `batch_id`, `order_id`, `drug_product_id`, and `status` filters; batches are listable with `status`, `compounder_staff_id`, `qa_pharmacist_staff_id`, and `hood_session_id` filters; the waste records of a batch are listable from the batch.

### 3.6. Cabinet Inventory: Pockets, the Ledger, and Dispensing

Automated dispensing cabinets are registered by a `PharmacyAdmin` as stations with a `name` and a `zone`; each station's pockets are configured under it, one drug per pocket, with the pocket's `drug_product_id` and its physical capacity `max_units`. A pocket opens `ACTIVE` with `on_hand_units` zero and `pick_blocked` false. Stations are listable with a `zone` filter, pockets per station, and pockets globally with `drug_product_id` and `status` filters.

The pocket's `on_hand_units` is not an independent counter — it is defined as the chronological replay of the pocket's `InventoryEvent` ledger, and it must equal that replay after every mutation. Each ledger event carries the `pocket_id` it mutates, an optional `order_id` (set on dispense and return events tied to an order, null otherwise), the `recorded_by_staff_id` taken from the caller's `X-User-ID`, an `event_type` of `RESTOCK`, `DISPENSE`, `RETURN`, `WASTE`, `COUNT`, or `ADJUSTMENT`, a signed `units_delta`, the `occurred_at` logical-clock timestamp, and the computed `expected_on_hand_after` — the pocket's `on_hand_units` immediately after applying the event. The replay convention is: restock adds its units, dispense subtracts, return adds, waste subtracts, adjustment adds or subtracts its signed amount, and a count contributes zero; events replay in `occurred_at` ascending order with `created_at` ascending as the tie-break, starting from zero. Ledger events are listable per pocket and globally with `order_id`, `recorded_by_staff_id`, `witness_staff_id`, and `event_type` filters. Every pocket-mutating call below also increments the pocket's `version` by 1, and all unit quantities must be at least 1 — a zero or negative `units` is rejected with `ERR_INVALID_QUANTITY`.

Restock is a `PharmacyTechnician` action carrying `units` and the mandatory OCC field `expected_pocket_version` (§2.5). Capacity is enforced: the restock may not push `on_hand_units` above `max_units`, otherwise the call is rejected with `ERR_POCKET_CAPACITY_EXCEEDED`. Success appends a `RESTOCK` event and adds `units` to `on_hand_units`.

Dispense is a `Nurse` action carrying the `order_id` and `units`, and it is the most heavily guarded call in the cabinet flow. The order's `verification_status` must be `VERIFIED`, otherwise `ERR_ORDER_NOT_VERIFIED`. The pocket's drug must equal the order's drug — `drug_product_id` matching `drug_product_id` — otherwise `ERR_DRUG_MISMATCH`. The pocket must be `ACTIVE`; dispensing from a `QUARANTINED` pocket is rejected with `ERR_POCKET_QUARANTINED`. The pocket must hold at least `units` on hand, otherwise `ERR_INSUFFICIENT_STOCK`. For an `IV` order, two further gates apply: a linked preparation in `QA_PASSED` must exist, otherwise `ERR_PREPARATION_NOT_QA_PASSED`, and the logical clock must be strictly before that preparation's `bud_expiry` — dispensing at or after the expiry is rejected with `ERR_BUD_EXPIRED`, the sweep having already run. Success appends a `DISPENSE` event with `units_delta` equal to negative `units`, subtracts the units from `on_hand_units`, moves the order's `fulfillment_status` from `READY` to `DISPENSED`, moves the linked `QA_PASSED` preparation to `DISPENSED`, and increments the order's `version` by 1 alongside the pocket's.

Return is the mirror `Nurse` action: it carries `units` and an optional `order_id`, requires the pocket's drug to match the returning order's drug when an `order_id` is given (mismatch yields `ERR_DRUG_MISMATCH`), appends a `RETURN` event, and adds the units back to `on_hand_units`.

Waste at the cabinet is shared between `PharmacyTechnician` and `Pharmacist`, carrying `units` and, for controlled drugs, a witness. When the pocket's drug is schedule `C_II`, a `witness_staff_id` must be present — its absence is rejected with `ERR_WITNESS_REQUIRED` — and the witness must differ from the recorder: a `witness_staff_id` equal to the caller's `X-User-ID` is rejected with `ERR_WITNESS_SELF_FORBIDDEN`. Stock sufficiency is enforced as on dispense (`ERR_INSUFFICIENT_STOCK`). Success appends a `WASTE` event with negative `units_delta`, appends a `WasteRecord` with the `pocket_id` set and `units` recorded (its `volume_ml` stays null, as does its `batch_id`), and subtracts the units from `on_hand_units`. The witness is also stored on both the ledger event's `witness_staff_id` and the waste record's `witness_staff_id`.

Physical counts belong to the `Pharmacist`. The caller supplies `physical_count_units`; the system appends a `COUNT` event (whose `units_delta` is zero and whose `observed_count_units` holds the supplied count) and computes the variance as the observed count minus the expected on-hand from the ledger replay. When the absolute variance breaches the schedule-specific threshold — 2 units for a `C_II` drug, 5 units for any other schedule — a `DiscrepancyCase` opens in `OPEN` status, recording the `pocket_id` and the signed `variance_units`. The count call returns the `variance_units`, the `expected_on_hand_units` from the replay, the `discrepancy_case_id` (null when no case opened), and the `event_id` of the appended count event. A count that stays within threshold appends its event and opens nothing.

Quarantine is the pharmacist's hold on a pocket: quarantining an `ACTIVE` pocket moves it to `QUARANTINED` and releasing returns it to `ACTIVE`, each incrementing the pocket's `version`. A quarantined pocket refuses dispenses, as above.

### 3.7. Discrepancy Resolution and Diversion Surveillance

A discrepancy case opened by a count moves through a short pharmacist-driven workflow. Investigation moves the case from `OPEN` to `INVESTIGATING`, incrementing its `version`. Resolution from `INVESTIGATING` branches on the supplied `resolution`. Under `FOUND_ERROR`, an `adjustment_units` value must be present and non-zero — otherwise `ERR_INVALID_REQUEST` — and the system appends an `ADJUSTMENT` ledger event whose `units_delta` equals `adjustment_units`, adds `adjustment_units` to the pocket's `on_hand_units`, records the resolving pharmacist in `resolved_by_staff_id`, moves the case to `RESOLVED`, and increments both the case's `version` and the pocket's `version` by 1. Under `UNRESOLVED_ESCALATE`, a `subject_staff_id` must be present — otherwise `ERR_INVALID_REQUEST` — and the system auto-creates a `DiversionCase` in `OPEN` status with `opened_via` of `ESCALATION`, the station taken from the pocket, the `source_discrepancy_case_id` pointing at this case, and the named subject; the discrepancy case records its `resolved_by_staff_id`, moves to `ESCALATED`, and increments its `version`. Discrepancy cases are listable with `pocket_id`, `status`, and `resolved_by_staff_id` filters.

Diversion cases may also be opened directly: a `DiversionOfficer` creates one with the `station_id`, the `subject_staff_id` under review, a free-text `reason`, and optionally a `source_discrepancy_case_id` (null when the opening is manual, in which case `opened_via` is `MANUAL`). Review moves an `OPEN` case to `UNDER_REVIEW`, incrementing its `version`. Adjudication from `UNDER_REVIEW` branches on the supplied `outcome`: `SUBSTANTIATED` or `CLOSED_UNSUBSTANTIATED`, each terminal, each storing the supplied note in `outcome_note`. Diversion cases are listable with `station_id`, `subject_staff_id`, `status`, and `source_discrepancy_case_id` filters; the adjudication inputs are the `outcome` and the `note`.

The third opening path is the risk score. A `DiversionOfficer` evaluates the trailing-30-day diversion risk for a triple of `station_id`, `subject_staff_id`, and `drug_product_id`. The window is every ledger event at pockets of that station, recorded by that subject, for the named drug's schedule, with `occurred_at` falling in the inclusive range from 30 days before the logical clock to the logical clock itself — both bounds inclusive. Three signals feed the score. The variance signal `v` sums, over the window's `COUNT` events, the absolute difference between each count's `observed_count_units` and the expected on-hand at count time; this sum is divided by 2. The waste signal `w` counts the window's `WASTE` events on pockets whose drug is controlled — any schedule other than `NON_CONTROLLED`. The after-hours signal `a` counts all events in the window whose `occurred_at` hour is before 6 or at or after 22, evaluated in UTC. The raw score is 10 times the halved variance sum, plus 5 times the waste count, plus 3 times the after-hours count. Two escalation rules then apply: if any single count in the window has an absolute variance of at least 10 and the drug is `C_II`, the raw score is raised to at least 80; and if the drug is `C_II`, the raw score is multiplied by 1.5. The final score rounds half-up to 2 decimal places and tiers as follows: a score of at least 75 is `OPEN_CASE`; at least 50 but below 75 is `WATCH`; below 50 is `CLEAR`. The `OPEN_CASE` tier auto-creates a `DiversionCase` in `OPEN` status with `opened_via` of `RISK_SCORE`. The evaluation returns the `score`, the `tier`, the `window_event_count`, and the `diversion_case_id` (null unless a case was created).

### 3.8. Shortage Substitution Protocols

When a drug goes on the shortage list, a `PharmacyAdmin` authors a substitution protocol naming the `shortage_drug_product_id`, the `substitute_drug_product_id` (the therapeutic equivalent), a `conversion_factor` that multiplies an ordered milligram dose into substitute milligrams, a `max_dose_mg` upper clamp, the protocol's `expires_at` instant, and optionally a `min_dose_mg` lower clamp (default 0). The protocol opens in `DRAFT`.

Activation is the `PharmacyAdmin` action that arms a `DRAFT` protocol, and it is gated three ways: the shortage drug's `in_shortage` flag must be true, otherwise `ERR_DRUG_NOT_IN_SHORTAGE`; the substitute drug's formulary `status` must be `ACTIVE`, otherwise `ERR_NO_ELIGIBLE_SUBSTITUTE`; and the logical clock must be strictly before `expires_at` — activating at or after expiry is rejected with `ERR_PROTOCOL_EXPIRED`. Activation moves the protocol to `ACTIVE` and runs a two-level flagging cascade. Level one: every medication order whose `drug_product_id` is the shortage drug, whose `verification_status` is `PENDING`, `VERIFIED`, or `ON_HOLD`, and whose `fulfillment_status` is neither `DISPENSED` nor `ADMINISTERED` has its `substitution_pending` set to true, and each such order's `version` increments by 1. Level two: every ADC pocket whose `drug_product_id` is the shortage drug has its `pick_blocked` set to true, and each such pocket's `version` increments by 1. The protocol's own `version` increments as well.

Applying the protocol is a `Pharmacist` action on a flagged order, naming the `protocol_id` and optionally `expected_order_version`. The guards fire in priority order: the order must be `VERIFIED`; its `substitution_pending` must be true, otherwise `ERR_SUBSTITUTION_NOT_PENDING`; the named protocol must be `ACTIVE` and its `shortage_drug_product_id` must equal the order's current `drug_product_id`, otherwise `ERR_NO_ACTIVE_PROTOCOL`; the substitute drug must be formulary-`ACTIVE`, otherwise `ERR_NO_ELIGIBLE_SUBSTITUTE`; the substitute drug must not appear in the patient's `allergy_drug_product_ids`, otherwise `ERR_ALLERGY_CONFLICT`; and the order's `fulfillment_status` must be `QUEUED` or `COMPOUNDING` — anything else yields `ERR_INVALID_STATE`. A successful substitution rewrites the order: `drug_product_id` becomes the protocol's `substitute_drug_product_id`; `ordered_dose_mg` becomes the substitution-equivalent dose — the original `ordered_dose_mg` times the protocol's `conversion_factor`, that product step-rounded on the same ladder as dose volumes, then clamped to no less than the protocol's `min_dose_mg` and no more than its `max_dose_mg`; `substituted_by_protocol_id` records the protocol and `substitution_pending` flips to false; the renal adjustment and final dose are recomputed for the new drug; and the order's `version` increments by 1.

Revocation is the `PharmacyAdmin` unwind of an `ACTIVE` protocol, and expiry of an `ACTIVE` protocol at the clock sweep runs the identical compensation: every order this protocol flagged that still has `substitution_pending` true and has not yet been substituted (`substituted_by_protocol_id` still null) has its `substitution_pending` reset to false, and every pocket this protocol blocked has its `pick_blocked` reset to false; a manual revocation also increments the protocol's `version`. Expired protocols land in `EXPIRED`, revoked ones in `REVOKED`; both are terminal. Protocols are listable with `substitute_drug_product_id` and `status` filters.

### 3.9. Waste Accounting Across the Two Domains

Waste is recorded in two shapes that share one read model. Compounding waste arises at batch completion and QA rejection: those records carry the `batch_id`, a `volume_ml`, a `reason` such as `PARTIAL_VIAL`, `QA_REJECT`, `EXPIRED`, or `CONTAMINATION`, and null `pocket_id` and `units`. ADC waste arises at the cabinet waste call: those records carry the `pocket_id` and `units`, with null `batch_id` and `volume_ml`. Both shapes record the `recorded_by_staff_id` from the caller and, for `C_II` drugs, the `witness_staff_id`. Waste records are listable globally with `pocket_id`, `recorded_by_staff_id`, and `witness_staff_id` filters, per batch, and — like every ledger line and intervention — a fetched waste record carries only `id` and `created_at` from the common system fields, with no `updated_at` and no `version`, because waste records are never mutated after they are written.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, trigger a state transition, or perform an action return `200 OK`. The rework endpoint returns `200` on both its cycle and its terminal `FAILED` outcome. All responses use the envelope of §2.2; list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pharmacy/staff` | Register a staff member | PharmacyAdmin |
| GET | `/pharmacy/staff/{id}` | Fetch one staff member | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/staff` | List staff | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/patients` | Register a patient; computes renal panel fields | PharmacyAdmin |
| GET | `/pharmacy/patients/{id}` | Fetch one patient | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| PATCH | `/pharmacy/patients/{id}` | Update renal panel / allergies; recomputes derived fields | PharmacyAdmin |
| POST | `/pharmacy/drug-products` | Add a formulary drug | PharmacyAdmin |
| GET | `/pharmacy/drug-products/{id}` | Fetch one drug | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/drug-products` | List drugs | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| PATCH | `/pharmacy/drug-products/{id}` | Update shortage flag / formulary status | PharmacyAdmin |
| GET | `/pharmacy/drug-products/{id}/substitution-protocols` | List substitution protocols for a shortage drug | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/hoods` | Register a compounding hood | PharmacyAdmin |
| GET | `/pharmacy/hoods/{id}` | Fetch one hood | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/hoods` | List hoods | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/medication-orders` | Create a medication order; supersedes prior open same-drug order; OCC-guarded on patient version | Prescriber |
| GET | `/pharmacy/medication-orders/{id}` | Fetch one order | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/medication-orders` | List orders with filters | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/medication-orders/{id}/verify` | Pharmacist verification: allergy screen, renal adjustment, dose rounding | Pharmacist |
| POST | `/pharmacy/medication-orders/{id}/resume` | Resume an ON_HOLD order back to VERIFIED | Pharmacist |
| POST | `/pharmacy/medication-orders/{id}/discontinue` | Prescriber discontinues an order; cascades to preparations, batch, hood session | Prescriber |
| POST | `/pharmacy/medication-orders/{id}/administer` | Nurse marks a dispensed order administered | Nurse |
| POST | `/pharmacy/medication-orders/{id}/interventions` | Document a clinical intervention; optionally place order on hold | Pharmacist |
| GET | `/pharmacy/medication-orders/{id}/interventions` | List interventions of an order | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/interventions/{id}` | Fetch one intervention | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/interventions` | List interventions | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/medication-orders/{id}/substitute` | Apply an ACTIVE substitution protocol to a flagged order | Pharmacist |
| POST | `/pharmacy/hood-sessions` | Reserve a hood window; half-open overlap check on the same hood | PharmacyTechnician |
| GET | `/pharmacy/hood-sessions/{id}` | Fetch one hood session | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/hood-sessions` | List hood sessions | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/hood-sessions/{id}/start` | Mark session in use; clock must be inside the window | PharmacyTechnician |
| POST | `/pharmacy/hood-sessions/{id}/complete` | Close an in-use session | PharmacyTechnician |
| POST | `/pharmacy/hood-sessions/{id}/cancel` | Cancel a scheduled/in-use session | PharmacyTechnician |
| POST | `/pharmacy/coverage-shifts` | Schedule pharmacist zone coverage; rejects a third overlapping shift per zone | PharmacyAdmin |
| GET | `/pharmacy/coverage-shifts/{id}` | Fetch one coverage shift | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/coverage-shifts` | List coverage shifts | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/batches` | Create a compounding batch from verified IV orders; creates PLANNED preparations | PharmacyTechnician |
| GET | `/pharmacy/batches/{id}` | Fetch one batch | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/batches` | List batches | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/batches/{id}/start` | Begin compounding; HD gating on hood rating and compounder certification | PharmacyTechnician |
| POST | `/pharmacy/batches/{id}/complete` | Record prepared volumes and waste; computes yield, overage, BUD per preparation | PharmacyTechnician |
| POST | `/pharmacy/batches/{id}/qa-release` | Pharmacist QA release; SoD vs compounder; waste tolerance gate | Pharmacist |
| POST | `/pharmacy/batches/{id}/qa-reject` | Pharmacist QA reject; preparations wasted | Pharmacist |
| POST | `/pharmacy/batches/{id}/rework` | Rework a rejected batch; at rework cap transitions to FAILED instead | PharmacyTechnician |
| GET | `/pharmacy/batches/{id}/preparations` | List preparations of a batch | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/batches/{id}/waste-records` | List waste records of a batch | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/preparations/{id}` | Fetch one preparation | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/preparations` | List preparations | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/adc-stations` | Register a dispensing cabinet | PharmacyAdmin |
| GET | `/pharmacy/adc-stations/{id}` | Fetch one cabinet | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/adc-stations` | List cabinets | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/adc-stations/{id}/pockets` | Configure a pocket (single drug per pocket) | PharmacyAdmin |
| GET | `/pharmacy/adc-stations/{id}/pockets` | List pockets of a cabinet | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/adc-pockets/{id}` | Fetch one pocket | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/adc-pockets` | List pockets | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/adc-pockets/{id}/restock` | Restock a pocket; OCC-guarded on pocket version | PharmacyTechnician |
| POST | `/pharmacy/adc-pockets/{id}/dispense` | Dispense units against a verified order | Nurse |
| POST | `/pharmacy/adc-pockets/{id}/return` | Return units to a pocket | Nurse |
| POST | `/pharmacy/adc-pockets/{id}/waste` | Record ADC waste; C_II waste requires a distinct witness | PharmacyTechnician, Pharmacist |
| POST | `/pharmacy/adc-pockets/{id}/count` | Physical count; opens a discrepancy case when variance breaches threshold | Pharmacist |
| POST | `/pharmacy/adc-pockets/{id}/quarantine` | Quarantine a pocket (blocks dispense) | Pharmacist |
| POST | `/pharmacy/adc-pockets/{id}/release-quarantine` | Release a pocket from quarantine | Pharmacist |
| GET | `/pharmacy/adc-pockets/{id}/events` | Ledger events of a pocket | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/adc-pockets/{id}/discrepancy-cases` | Discrepancy cases of a pocket | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/inventory-events/{id}` | Fetch one ledger event | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/inventory-events` | List ledger events | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/discrepancy-cases/{id}` | Fetch one discrepancy case | PharmacyAdmin, Pharmacist, DiversionOfficer |
| GET | `/pharmacy/discrepancy-cases` | List discrepancy cases | PharmacyAdmin, Pharmacist, DiversionOfficer |
| POST | `/pharmacy/discrepancy-cases/{id}/investigate` | Move case to INVESTIGATING | Pharmacist |
| POST | `/pharmacy/discrepancy-cases/{id}/resolve` | Resolve with compensating adjustment, or escalate to diversion | Pharmacist |
| POST | `/pharmacy/diversion-cases` | Manually open a diversion case | DiversionOfficer |
| GET | `/pharmacy/diversion-cases/{id}` | Fetch one diversion case | PharmacyAdmin, DiversionOfficer |
| GET | `/pharmacy/diversion-cases` | List diversion cases | PharmacyAdmin, DiversionOfficer |
| POST | `/pharmacy/diversion-cases/{id}/review` | Move case to UNDER_REVIEW | DiversionOfficer |
| POST | `/pharmacy/diversion-cases/{id}/adjudicate` | Branching adjudication | DiversionOfficer |
| POST | `/pharmacy/diversion-risk/evaluate` | Compute the 30-day diversion risk score; OPEN_CASE tier auto-creates a case | DiversionOfficer |
| POST | `/pharmacy/substitution-protocols` | Create a substitution protocol (DRAFT) | PharmacyAdmin |
| GET | `/pharmacy/substitution-protocols/{id}` | Fetch one protocol | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/substitution-protocols` | List protocols | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/substitution-protocols/{id}/activate` | Activate a protocol; flags affected orders and blocks shortage-drug pockets | PharmacyAdmin |
| POST | `/pharmacy/substitution-protocols/{id}/revoke` | Revoke an active protocol; compensating cascade unflags orders and unblocks pockets | PharmacyAdmin |
| GET | `/pharmacy/waste-records/{id}` | Fetch one waste record | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| GET | `/pharmacy/waste-records` | List waste records | PharmacyAdmin, Prescriber, Pharmacist, PharmacyTechnician, Nurse, DiversionOfficer |
| POST | `/pharmacy/_clock/set_current_utc` | Set the logical clock; runs preparation and protocol expiry sweeps | PharmacyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_ROLE_MISMATCH` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_ORDER_ALREADY_TERMINAL` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_ALLERGY_CONFLICT` | 422 |
| `ERR_HD_CERTIFICATION_REQUIRED` | 422 |
| `ERR_HOOD_NOT_HD_RATED` | 422 |
| `ERR_WITNESS_REQUIRED` | 422 |
| `ERR_WITNESS_SELF_FORBIDDEN` | 422 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_ORDER_PRESCRIBER` | 403 |
| `ERR_INVALID_QUANTITY` | 400 |
| `ERR_HOOD_OVERLAP` | 409 |
| `ERR_COVERAGE_CAP_EXCEEDED` | 409 |
| `ERR_POCKET_CAPACITY_EXCEEDED` | 422 |
| `ERR_INSUFFICIENT_STOCK` | 422 |
| `ERR_DRUG_MISMATCH` | 422 |
| `ERR_WASTE_TOLERANCE_EXCEEDED` | 422 |
| `ERR_HOOD_SESSION_OUTSIDE_WINDOW` | 422 |
| `ERR_HOOD_SESSION_NOT_ACTIVE` | 409 |
| `ERR_BUD_EXPIRED` | 422 |
| `ERR_PROTOCOL_EXPIRED` | 422 |
| `ERR_ORDER_NOT_VERIFIED` | 422 |
| `ERR_PREPARATION_NOT_QA_PASSED` | 422 |
| `ERR_POCKET_QUARANTINED` | 409 |
| `ERR_DRUG_DISCONTINUED` | 422 |
| `ERR_SUBSTITUTION_NOT_PENDING` | 422 |
| `ERR_NO_ACTIVE_PROTOCOL` | 422 |
| `ERR_NO_ELIGIBLE_SUBSTITUTE` | 422 |
| `ERR_DRUG_NOT_IN_SHORTAGE` | 422 |

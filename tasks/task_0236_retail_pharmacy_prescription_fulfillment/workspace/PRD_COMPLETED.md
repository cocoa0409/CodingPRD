# Retail Pharmacy Fulfillment API — Product Requirements Document

## 1. Introduction

This document specifies the Retail Pharmacy Fulfillment API, a back-office platform that drives an electronic prescription from intake all the way through to the moment a patient walks away from the counter with medication in hand. The product exists because a community pharmacy is, in practice, three businesses braided together: a clinical safety operation that must screen every fill for drug interactions, allergies, and overdose risk; a real-time billing operation that must adjudicate each fill against a payer's plan and collect the correct out-of-pocket amount; and a regulatory operation that must police controlled-substance dispensing against prescriber DEA credentials and a prescription-drug-monitoring posture. A mistake in any one of these threads — an un-reviewed severe interaction, a copay that ignores the patient's annual cap, a controlled fill dispensed to a patient the monitoring program has flagged — is not a rounding error but a patient-safety or compliance failure.

The system models this work as a set of cooperating lifecycles. A prescription is intaken once and then yields a sequence of fills; each fill marches through a fulfillment workflow (clinical review, adjudication, possible prior-authorization detour, staging, and dispensing) while a second, independent claim dimension tracks the money. Layered on top is a patient-level controlled-substance posture that the act of dispensing a controlled drug can silently tighten. The API is consumed by four kinds of staff — administrators who curate reference data and run scheduled sweeps, technicians who do intake and routine processing, pharmacists who perform every clinical and regulatory judgment, and cashiers who collect payment — and the segregation between these roles is itself a compliance control, not merely a convenience.

Because every date-sensitive rule (refill timing, prior-auth and prescription expiry, will-call pickup windows, and the monitoring-program lookback) must be deterministic and testable, the platform never reads the host machine's clock. Instead, all date arithmetic reads a single server-controlled logical clock that an administrator advances explicitly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that govern every endpoint. Where a rule is stated here, it is binding even if a later workflow narrative does not repeat it.

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the actor: `X-User-ID`, an opaque string identifying the individual staff member, and `X-User-Role`, declaring the capacity in which they act. If either header is absent or malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 401). The system recognizes exactly four roles, spelled precisely as `PharmacyAdmin`, `Pharmacist`, `Technician`, and `Cashier`. When an authenticated actor attempts an operation their role is not permitted to perform, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

All four roles are operator roles whose identity is opaque: for each of `PharmacyAdmin`, `Pharmacist`, `Technician`, and `Cashier`, the `X-User-ID` is an operator identifier that is not tied to any persisted entity. The server never compares `X-User-ID` to any resource's `id`. It does, however, record the identifier where a workflow calls for an audit trail or a separation-of-duties comparison — for example, the technician who creates a fill has their `X-User-ID` retained so it can later be compared against the pharmacist who overrides or dispenses that fill, the pharmacist who clears a DUR alert is written to the fill's `dur_override_by`, and the staff member collecting money is recorded on a payment's `tendered_by`. These are recorded values used for comparison, never foreign keys into a user table.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of leading items to skip and defaults to 0. Unless an endpoint explicitly states otherwise, all list responses are sorted by `created_at` in ascending order, with the resource `id` used as a secondary tie-break when two records share the same `created_at`. Every list response surfaces `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the count of all matching records before pagination and `has_more` is true when records remain beyond the current page.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources are mutable and additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every change) and an integer `version` that begins at 1 and increments by one on every mutation of that resource. The sole exception is the logical clock resource: it is a singleton whose `id` is the literal string `clock`, it carries `created_at`, but it has neither an `updated_at` nor a `version` field.

The clock resource exposes a single deterministic field, `current_utc`, which begins at `2026-01-01T00:00:00.000Z`. Every date computation in the system — refill-too-soon timing, prescription and prior-auth expiry, will-call pickup deadlines, and the monitoring-program lookback window — reads `current_utc`, never the host machine's wall clock. An administrator advances the clock to a supplied instant; reading the clock is available to all roles.

### 2.5. Precision, Rounding, and Monetary Representation

All monetary amounts are stored and returned as integer cents (`unit_price_cents`, `copay_min_cents`, `copay_max_cents`, `dispensing_fee_cents`, `allowed_amount_cents`, `gross_amount_cents`, `provisional_copay_cents`, `final_copay_cents`, `plan_paid_cents`, and `amount_cents`). Wherever a coinsurance computation multiplies an amount by a fractional `copay_pct`, the single resulting product is rounded to a whole number of cents using the round-half-up convention. Day counts used in the refill-too-soon edit are whole integers obtained by flooring, as described in §3. The monitoring-program risk score is a whole integer.

### 2.6. Hierarchical Consistency and Cascading Side Effects

Many operations in this domain mutate more than one resource. Whenever a transition's side effects touch a second resource — a fill's dispensing recomputing its parent prescription's `refills_remaining`, a prior-auth decision flipping the linked fill's workflow and claim status, a controlled dispense driving a patient's monitoring posture — the system applies every stated effect as part of the same request, and each mutated resource independently refreshes its own `updated_at` and increments its own `version`. A reader must not assume that an operation named for one entity leaves the rest of the graph untouched; the workflow narratives in §3 enumerate every cascade, and all of them are mandatory.

Two cascades deserve emphasis here because they reach across aggregates. First, when a fill reaches the dispensed state for a controlled drug, the system regenerates the patient's monitoring report, which in turn may drive the patient's `pdmp_flag` and then the patient's `controlled_status` — a three-step cascade from a single dispense. Second, decommissioning a parent flows downward: discontinuing a prescription cancels its not-yet-processed fills.

### 2.7. Nested Resource Retrieval and Reference Validation

Several endpoints address a resource by an `id` embedded in the path; some also accept foreign-key identifiers in the request body. Path identifiers are validated first, left to right: if a path `id` does not resolve to an existing resource, the request fails immediately with `ERR_NOT_FOUND` (HTTP 404) before any foreign-key body validation runs (though generic body-schema validation of the fields the endpoint reads still runs ahead of this path-id check, per §2.8). Body fields that reference other resources — `patient_id`, `prescriber_id`, `drug_id`, `plan_id`, and `fill_id` on the creating endpoints — are validated next; a reference to a non-existent resource is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Only after existence is established does the system evaluate state and business rules.

### 2.8. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed priority so that the returned error is deterministic. The order is: (1) presence and well-formedness of the `X-User-ID` and `X-User-Role` headers (`ERR_MISSING_USER_CONTEXT`); (2) role authorization for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); (3) existence of every path resource id, left to right (`ERR_NOT_FOUND`); (4) existence of every body foreign-key reference (`ERR_REFERENCE_NOT_FOUND`); (5) the optimistic-concurrency version check where the endpoint requires one (`ERR_STALE_PRESCRIPTION_VERSION` or `ERR_STALE_PA_VERSION`); (6) the target resource being in a valid from-state for the requested transition (the generic `ERR_INVALID_STATE`, or the more specific state error the transition nominates); then the business-safety, business-temporal, and business-constraint checks in the priority sequence given in §3 for each workflow. Generic body-schema validation — malformed body, missing required field, illegal enum value, or out-of-range numeric, reported as `ERR_INVALID_REQUEST` (HTTP 400) — is, in this implementation, performed early rather than last: it runs immediately after the header (1) and role-authorization (2) checks, parsing every body field the endpoint reads before any path-id existence (3), body foreign-key existence (4), version (5), state (6), or business check runs. Consequently, when a request both carries a malformed/missing/out-of-range body field and references a non-existent path id or foreign key, `ERR_INVALID_REQUEST` is returned (it preempts `ERR_NOT_FOUND` and `ERR_REFERENCE_NOT_FOUND`). Where a workflow lists more than one business check, the relative order among those checks is stated in the workflow narrative and is binding.

### 2.9. Optimistic Concurrency Control

Two write operations require the client to prove it is acting on a current view of a parent resource, guarding against a second writer having advanced that parent in the interim.

When submitting a claim for a fill, the request must carry `expected_prescription_version` holding the client's last-observed `version` of the fill's parent prescription. If that value does not match the prescription's current `version`, the submission is rejected with `ERR_STALE_PRESCRIPTION_VERSION` (HTTP 412). This is exactly the situation in which another fill of the same prescription has already adjudicated — legitimately decrementing `refills_remaining` and bumping the prescription's `version` — leaving the current client's view stale; the check prevents the client from submitting against a prescription it has not re-read.

When approving a prior-authorization request, the request must carry `expected_priorauthrequest_version` holding the client's last-observed `version` of that prior-auth request. If it does not match the request's current `version`, the approval is rejected with `ERR_STALE_PA_VERSION` (HTTP 412). The same version field and the same `ERR_STALE_PA_VERSION` rejection apply when denying a prior-auth request. These rejections capture the case where the prior-auth was already decided — an approve or deny legitimately bumps its `version` — so the current writer's view is stale. No other endpoint takes a version field, and where no version field is defined the server performs no concurrency check.

### 2.10. Reference Data Uniqueness

Three pieces of reference data must be globally unique at creation time. A drug product's `ndc` must not duplicate an existing drug; a collision is rejected with `ERR_DUPLICATE_NDC` (HTTP 409). An insurance plan's routing pair, the combination of `bin` and `pcn`, must be unique; a collision is rejected with `ERR_DUPLICATE_PLAN_ROUTING` (HTTP 409). A prescriber's `npi` must be unique; a collision is rejected with `ERR_DUPLICATE_NPI` (HTTP 409).

### 2.11. State Enumerations

For precise reference, the workflows in §3 use these exact state strings. A prescription's `status` is one of `ACTIVE`, `EXHAUSTED`, `EXPIRED`, or `DISCONTINUED`. A fill's fulfillment `status` is one of `ENTERED`, `DUR_REVIEW`, `ADJUDICATING`, `PA_REFERRAL`, `READY_FILL`, `WILL_CALL`, `DISPENSED`, `RETURNED_TO_STOCK`, or `CANCELLED`. A fill's independent `claim_status` is one of `UNCLAIMED`, `SUBMITTED`, `PAID`, `REJECTED`, `PA_PENDING`, or `REVERSED`. A prior-auth request's `status` is one of `PENDING`, `APPROVED`, `DENIED`, or `EXPIRED`. A patient's monitoring `pdmp_flag` is one of `CLEAR`, `REVIEW`, or `BLOCKED`, and the parallel `controlled_status` is one of `ELIGIBLE` or `LOCKED`. A drug product's `status` is one of `ACTIVE` or `DISCONTINUED`. The controlled-substance schedule `dea_schedule` is one of `NONE`, `CII`, `CIII`, `CIV`, or `CV`. Clinical severities (`dur_severity`, an alert's `severity`, an interaction rule's `severity`) are ranked `NONE`, `MINOR`, `MODERATE`, `SEVERE`; an alert's `alert_type` is one of `INTERACTION`, `ALLERGY`, `DUPLICATE_THERAPY`, or `HIGH_DOSE`; and a prior-auth `reason` is one of `DRUG_PA_REQUIRED`, `PLAN_PA_REQUIRED`, or `CONTROLLED_PA_REQUIRED`.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Drugs, Plans, Formulary, Interactions, Prescribers

Before any clinical work can happen, an administrator curates the catalog. A drug product is created with its 11-digit `ndc`, a `name`, an optional controlled-substance schedule `dea_schedule` (defaulting to `NONE`), an acquisition cost `unit_price_cents` (zero or greater, per dispensing unit such as a tablet), an optional `pa_required` flag (defaulting to false) marking drugs that always demand prior authorization regardless of any plan's formulary, and an optional `therapeutic_substitute_of_id` pointing at the brand product this generic substitutes for (null for non-substitutes). On creation the drug's `status` is `ACTIVE` and its computed `is_active` flag is true. An administrator may later discontinue a drug, which sets `status` to `DISCONTINUED` and `is_active` to false; a discontinued drug rejects new clinical use as described below. The drug list may be filtered by `therapeutic_substitute_of_id` to find all generics linked to a given brand.

An insurance plan carries its routing `bin` and `pcn`, a display `name`, a coinsurance fraction `copay_pct` between 0.0 and 1.0 that expresses the share of the allowed amount the patient pays, an optional `copay_min_cents` floor (defaulting to 0, zero or greater) the patient always pays, a `copay_max_cents` ceiling that must be strictly greater than `copay_min_cents`, an optional flat `dispensing_fee_cents` (defaulting to 100, zero or greater) added before coinsurance, an optional `refill_too_soon_threshold_pct` (defaulting to 0.80, between 0.0 and 1.0) governing how much of a prior supply must elapse before a refill clears, and an optional `requires_pa_for_controlled` flag (defaulting to false) that, when true, refers every Schedule `CII` claim to prior authorization before adjudication.

A formulary entry binds a drug to a plan: it names the `plan_id` and `drug_id`, a formulary `tier` from 1 through 4 (lower is cheaper), the plan-negotiated `allowed_amount_cents` per dispensing unit (zero or greater), and an optional plan-specific `requires_pa` flag (defaulting to false). Formulary entries may be listed filtered by `plan_id` or `drug_id`. An interaction rule pairs two drugs by `drug_a_id` and `drug_b_id`, with a `severity` and a human-readable `detail`; interaction rules may be listed filtered by `drug_a_id` or `drug_b_id`. A prescriber is created with a `full_name`, a unique 10-digit `npi`, an optional `dea_number`, and an optional `dea_active` flag (defaulting to true) indicating whether that DEA registration is currently valid; both fields matter when a controlled prescription is involved.

### 3.2. Patients and Their Monitoring Posture

A patient is registered with a `full_name`, a `date_of_birth` as an ISO date in `YYYY-MM-DD` form, an optional `plan_id` linking active coverage (null marks a cash patient), an optional `allergy_classes` array of allergy-class strings such as `PENICILLIN` or `SULFA` (defaulting to an empty list) used by allergy screening, an optional `auto_refill_enrolled` flag (defaulting to false), and an optional `med_sync_day`, a day-of-month from 1 through 28 to which the patient's chronic medications are synchronized (null when not enrolled). At registration the patient's computed `pdmp_flag` is `CLEAR` and the parallel `controlled_status` is `ELIGIBLE`. Patients may be listed filtered by `plan_id`, and an individual fetch returns the live computed `pdmp_flag` and `controlled_status`.

These two patient fields form a parallel monitoring dimension that the act of dispensing controlled drugs tightens automatically. The monitoring posture is driven by a risk score recomputed from the patient's controlled-fill history (§3.7). When a freshly computed report places the patient's risk in the review band, the `pdmp_flag` advances from `CLEAR` to `REVIEW`; the `controlled_status` stays `ELIGIBLE` and the pharmacist merely sees an advisory. When the risk reaches the block band, the `pdmp_flag` becomes `BLOCKED` — whether the patient was previously `CLEAR` or `REVIEW` — and at that point the parallel `controlled_status` flips to `LOCKED`, after which new controlled claims are refused. A pharmacist may manually lift a block: this requires the patient to currently be `BLOCKED` (otherwise `ERR_PATIENT_NOT_BLOCKED`) and an `override_reason` to be supplied (otherwise `ERR_OVERRIDE_REASON_REQUIRED`); on success the `pdmp_flag` returns to `CLEAR` and `controlled_status` returns to `ELIGIBLE`.

### 3.3. Prescription Intake and Lifecycle

A prescription is intaken by a technician or administrator with the `patient_id`, `prescriber_id`, and `drug_id` it concerns, the `quantity_per_fill` (a positive number of dispensing units), the `days_supply` each fill is expected to last (positive), an optional `refills_authorized` count beyond the original fill (defaulting to 0, zero or greater), and the `written_utc` date it was written. At intake the prescription enters `ACTIVE` status, its `refills_remaining` is set equal to `refills_authorized`, and its `expires_utc` is computed from the written date: a non-controlled drug expires 365 days after `written_utc`, while a controlled drug (any schedule from `CII` through `CV`) expires 180 days after `written_utc`. The `last_dispensed_utc` is null until the first fill is dispensed. If the prescribed drug is controlled, intake additionally requires the prescriber to have a `dea_number` on file with `dea_active` true; otherwise the intake is rejected with `ERR_PRESCRIBER_DEA_INVALID` (HTTP 422). Intake against a drug whose `status` is `DISCONTINUED` is rejected with `ERR_DRUG_DISCONTINUED`. Prescriptions may be listed filtered by `patient_id`, `prescriber_id`, or `drug_id`, and an individual fetch returns the computed `refills_remaining` and `last_dispensed_utc`.

A prescription leaves `ACTIVE` along one of three paths. It becomes `EXHAUSTED` automatically as a bubble-up: when one of its fills reaches the dispensed state and the recomputed `refills_remaining` has fallen to 0, the system transitions the prescription from `ACTIVE` to `EXHAUSTED` in the same operation. It becomes `EXPIRED` through an administrator-run sweep that checks whether `current_utc` has moved strictly past `expires_utc`; if so, the prescription transitions `ACTIVE → EXPIRED`. A pharmacist may discontinue an `ACTIVE` prescription; this requires the prescription to currently be `ACTIVE` (otherwise `ERR_PRESCRIPTION_NOT_ACTIVE`) and requires that no fill of the prescription sit in a non-terminal workflow state other than `ENTERED` (otherwise `ERR_OPEN_FILL_EXISTS`). On discontinuation the prescription transitions to `DISCONTINUED` and, cascading downward, every fill still in `ENTERED` is moved to `CANCELLED`.

The `refills_remaining` figure is a derived value reconciled on every fill lifecycle change — fill creation, cancellation, dispensing, and return-to-stock. It is computed as the authorized refill count minus the number of fills of that prescription that are currently "consuming" a refill, floored at zero so it never goes negative. A fill counts as consuming when its workflow status is one of `ADJUDICATING`, `PA_REFERRAL`, `READY_FILL`, `WILL_CALL`, or `DISPENSED`, excluding the original fill whose `fill_sequence` is 1; fills in `ENTERED`, `DUR_REVIEW`, `CANCELLED`, or `RETURNED_TO_STOCK` do not count toward consumption. Whenever this recomputation drives `refills_remaining` to 0 on the back of a dispense, the parent prescription auto-exhausts as described above.

### 3.4. The Fill Workflow: Intake, Clinical Review, and Override

A fill (or refill) is created by a technician or administrator against a `prescription_id`; that is the only body field. On creation the fill enters `ENTERED` status with a `claim_status` of `UNCLAIMED`, is assigned a `fill_sequence` (1 for the original, incrementing for each subsequent fill of the same prescription), copies `quantity_dispensed` from the prescription's `quantity_per_fill` and `days_supply` from the prescription's `days_supply`, and computes `gross_amount_cents` as the drug's `unit_price_cents` multiplied by `quantity_dispensed`. The creating technician's `X-User-ID` is recorded on the fill (in its `created_by` field, which is included in the fill response) for later separation-of-duties comparison, and the parent prescription's `refills_remaining` is recomputed. Creating a refill — any fill whose `fill_sequence` is greater than 1 — requires `refills_remaining` to be greater than 0 at creation time, otherwise the creation is rejected with `ERR_NO_REFILLS_REMAINING`. A fill cannot be created against a prescription that is not `ACTIVE` (`ERR_PRESCRIPTION_NOT_ACTIVE`), and the prescriber's DEA standing is re-checked for controlled drugs as at intake (`ERR_PRESCRIBER_DEA_INVALID`). Fills may be listed filtered by `prescription_id`, and an individual fetch returns the fill's `claim_status`, its copay fields, and its `dur_severity`.

Clinical review begins when a technician or pharmacist runs the drug-utilization-review screen on a fill. This is permitted only when the fill is `ENTERED` (otherwise `ERR_FILL_NOT_ENTERED`), the parent prescription is `ACTIVE` (otherwise `ERR_PRESCRIPTION_NOT_ACTIVE`), and the drug's `status` is `ACTIVE` (otherwise `ERR_DRUG_DISCONTINUED`). The screen creates a DUR alert row for each finding, rolls the highest severity into the fill's `dur_severity`, and then branches: if no alerts were raised the `dur_severity` is `NONE` and the fill auto-advances from `ENTERED` straight through `DUR_REVIEW` to `ADJUDICATING`; otherwise the fill settles in `DUR_REVIEW` awaiting a pharmacist's override. Each DUR alert carries the `fill_id` it was raised against, an `alert_type`, a `severity`, a human-readable `detail`, an `overridden` flag that starts false, and an optional `override_reason` captured at override time. The DUR severity roll-up is detailed in §3.5; alerts may be listed filtered by `fill_id`.

A pharmacist clears review by overriding the alerts, which advances the fill from `DUR_REVIEW` to `ADJUDICATING`. This requires the fill to be in `DUR_REVIEW` (otherwise `ERR_FILL_NOT_IN_DUR_REVIEW`), and every `MODERATE` and `SEVERE` alert on the fill must carry an `override_reason` — an `override_reason` is therefore mandatory whenever a `SEVERE` alert is present, and its absence is rejected with `ERR_OVERRIDE_REASON_REQUIRED` (HTTP 422). When the drug is Schedule `CII`, the acting pharmacist's `X-User-ID` must differ from the `X-User-ID` of the technician who created the fill; a same-person override is a separation-of-duties violation rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On success every `MODERATE` and `SEVERE` alert on the fill has its `overridden` flag set to true and the fill's `dur_override_by` is set to the acting pharmacist's `X-User-ID`. If a fill still carries un-overridden `MODERATE` or `SEVERE` alerts when a claim submission is attempted, that submission is refused with `ERR_DUR_NOT_OVERRIDDEN`.

### 3.5. DUR Screening: How Severity Is Determined

The drug-utilization-review screen aggregates findings from four heterogeneous sources and reports the single highest severity, ranked `NONE` below `MINOR` below `MODERATE` below `SEVERE`. The first source is drug-drug interactions: for every interaction rule that pairs the fill's drug with the drug on any non-cancelled fill of the same patient, the rule's own `severity` contributes. The second source is allergy screening: if the fill's drug shares an allergy class present in the patient's `allergy_classes`, a `SEVERE` finding contributes. Because a drug product carries no explicit allergy-class field, the match is realized by testing whether the drug's `name` appears as one of the strings in the patient's `allergy_classes`. The third source is duplicate therapy: if any other non-cancelled fill of the same patient is for the same drug, a `MODERATE` finding contributes. The fourth source is high-dose detection: if the fill's `quantity_dispensed` divided by its `days_supply` exceeds four units per day, a `MODERATE` finding contributes. The fill's `dur_severity` is the maximum severity across whatever findings were produced, and `NONE` when there were none. Each contributing finding becomes a DUR alert with the corresponding `alert_type` of `INTERACTION`, `ALLERGY`, `DUPLICATE_THERAPY`, or `HIGH_DOSE`.

### 3.6. Adjudication, the Prior-Auth Detour, and the Two Copays

Claim submission is the system's busiest operation, run by a technician or pharmacist, and it carries one body field beyond context: `expected_prescription_version`. The fill must be in `ADJUDICATING` (otherwise `ERR_FILL_NOT_ADJUDICATING`) and its `claim_status` must be `UNCLAIMED` (otherwise `ERR_CLAIM_ALREADY_OPEN`). The checks then proceed in this order. First the version guard described in §2.9 runs: `expected_prescription_version` must match the prescription's current `version`, else `ERR_STALE_PRESCRIPTION_VERSION`. Next, any un-overridden `MODERATE` or `SEVERE` DUR alert blocks the submission with `ERR_DUR_NOT_OVERRIDDEN`. Then, for an insured patient, the drug must appear on the patient's plan formulary (or be flagged for prior auth); a drug absent from the formulary is rejected with `ERR_DRUG_NOT_ON_FORMULARY` (HTTP 422). For a controlled drug, the patient's `controlled_status` must be `ELIGIBLE`, otherwise `ERR_PATIENT_CONTROLLED_LOCKED` (HTTP 403); this gate consults only the patient's currently persisted `controlled_status` (the committed posture), and submit-claim does not recompute any monitoring score of its own. The refill-too-soon edit (§3.8) is then applied.

Submission then forks on whether prior authorization is required. Prior auth is required when any of three conditions holds: the drug's `pa_required` is true, the matching formulary entry's `requires_pa` is true, or the drug is Schedule `CII` and the plan's `requires_pa_for_controlled` is true. If prior auth is required and no `APPROVED` prior-auth request already exists for this fill, the submission takes the referral branch: it transitions the fill from `ADJUDICATING` to `PA_REFERRAL`, creates a prior-auth request in `PENDING` status with its `reason` set (`DRUG_PA_REQUIRED`, `PLAN_PA_REQUIRED`, or `CONTROLLED_PA_REQUIRED` according to which condition fired), records `submitted_utc` as `current_utc`, sets `expires_utc` to 30 days after `submitted_utc`, sets the fill's `claim_status` to `PA_PENDING`, and increments the prescription's `version` by one. An already-`APPROVED` prior-auth request for the fill suppresses re-referral so that the resubmitted claim clears straight through.

Otherwise the claim pays. On the pay branch the fill transitions from `ADJUDICATING` to `READY_FILL`, the system computes the copays described below, sets the fill's `claim_status` to `PAID`, and increments the prescription's `version` by one. The prior-auth request itself carries the `fill_id` it concerns, a `prescription_id` copied from the fill at referral, the `reason`, `submitted_utc`, a `decided_utc` (null while pending), the `expires_utc`, and its `status`. Prior-auth requests may be listed filtered by `fill_id` or `prescription_id`.

Two copay figures are computed and they are deliberately different. The **provisional** copay is a forward-looking estimate computed at submission from the static formulary allowed amount, ignoring the patient's prior fills. It is built by taking the allowed amount per unit (`allowed_amount_cents` from the single formulary entry matching the fill's drug and the patient's plan; if no such entry exists, `ERR_DRUG_NOT_ON_FORMULARY`), multiplying it by the fill's `quantity_dispensed`, adding the plan's `dispensing_fee_cents` to obtain an allowed total, multiplying that total by the plan's `copay_pct` and rounding the single product half-up to whole cents, and then clamping that figure to lie at or above the plan's `copay_min_cents` and at or below the plan's `copay_max_cents`. The result is stored as `provisional_copay_cents`. Crucially, the provisional estimate applies `copay_max_cents` as a per-fill ceiling.

The **final** copay is the adjudicated, chronological figure locked when the claim pays, and it treats `copay_max_cents` as the patient's annual out-of-pocket maximum applied cumulatively rather than per fill. It begins identically — allowed total equals `allowed_amount_cents` times `quantity_dispensed` plus the plan's `dispensing_fee_cents`, then that total times `copay_pct` rounded half-up to whole cents — and takes this raw figure raised to at least `copay_min_cents` as the current fill's tentative copay. The system then sums the `final_copay_cents` already contributed by the patient's earlier fills on the same plan: it considers the patient's prior fills for the same patient-and-plan whose status is not `CANCELLED`, excluding any fill whose claim was `REVERSED` and any fill that has not yet been adjudicated (whose `final_copay_cents` is still null), processed in `created_at` ascending order, and totals their final copays to get the prior out-of-pocket. "Same patient-and-plan" is evaluated against the patient's current `plan_id` binding (fills do not store their own plan). The remaining annual room is the plan's `copay_max_cents` minus that prior out-of-pocket, but never less than zero. The fill's `final_copay_cents` is the smaller of the current fill's tentative copay and that remaining room, and `plan_paid_cents` is the allowed total minus `final_copay_cents`. Because the provisional figure caps each fill independently while the final figure draws down a shared annual cap, on a patient's second and later fills — once earlier copays have neared the annual maximum — the provisional and final copays diverge.

For a cash patient (one whose `plan_id` is null) both copay variants collapse to the same simple rule: there is no formulary lookup, the `provisional_copay_cents` and the `final_copay_cents` are both set equal to `gross_amount_cents`, and `plan_paid_cents` is 0.

### 3.7. Controlled Substances: PDMP Risk and the Dispensing Lock

The monitoring-program risk score combines a controlled-fill volume signal with a prescriber-shopping signal. The system counts the patient's qualifying controlled fills — fills whose drug's `dea_schedule` is `CII`, `CIII`, `CIV`, or `CV` — that fall within a 90-day lookback window measured back from `current_utc`, recording that as `controlled_fill_count`, and counts the distinct prescribers across those same fills as `distinct_prescriber_count`. Each fill is anchored at its logical dispense instant (the `current_utc` captured when it was dispensed); a fill qualifies when the floored whole-day gap between that anchor and the current `current_utc` is 90 or fewer (so exactly 90 days back is still inside the window, and a fill anchored after the current clock is excluded). The `risk_score` is the controlled-fill count multiplied by a per-fill weight of 10, plus the prescriber-shopping excess (the distinct prescriber count minus 1, but never below 0) multiplied by a per-prescriber weight of 15. The resulting flag is `BLOCKED` when the score is at least 60, otherwise `REVIEW` when the score is at least 30, otherwise `CLEAR`. A report records the `patient_id` it concerns, the optional `fill_id` that triggered it (null for manual queries), the `lookback_days` (90), the `controlled_fill_count`, the `distinct_prescriber_count`, the `risk_score`, and the `resulting_flag` it drove the patient's posture to. Reports may be listed filtered by `patient_id` or `fill_id`.

This score has two variants that differ only in which fills they count. The **committed** variant counts only fills already in `DISPENSED` status — the settled, chronological view — and it is the one that drives the persisted `pdmp_flag` and `controlled_status`. It is the default for a manual monitoring query and the variant regenerated as a dispense-time side effect. The **provisional** variant is forward-looking and, were it computed, would count the already-`DISPENSED` fills plus the in-flight fill currently being adjudicated (a fill in `ADJUDICATING` or `READY_FILL`), so that it would exceed the committed score by exactly one fill's weight (and possibly one prescriber's weight) on the boundary fill; it is never persisted to `pdmp_flag`. In this implementation, however, no provisional monitoring score is ever computed: submit-claim of a controlled drug gates solely on the patient's already-persisted (committed) `controlled_status` as described in §3.6, and the only monitoring recomputation that ever runs is the committed variant — triggered by a manual `/pdmp-reports` query and as the dispense-time side effect — so a controlled claim is admitted whenever `controlled_status` is `ELIGIBLE` regardless of any in-flight fill.

A pharmacist may run a manual monitoring query for a patient; this regenerates the report using the committed variant and recomputes the patient's `pdmp_flag` and `controlled_status` from the `resulting_flag`. When the report regeneration places risk in the review band (score at least 30 and below 60) the patient moves toward `REVIEW`; when it reaches the block band (score at least 60) the patient becomes `BLOCKED` and `controlled_status` flips to `LOCKED`, as enumerated in §3.2.

### 3.8. The Refill-Too-Soon Edit

A refill must not be filled until enough of the prior supply has been used up. During claim submission the system computes the required elapsed days as the prior fill's `days_supply` multiplied by the plan's `refill_too_soon_threshold_pct` (which defaults to 0.80), with the product floored to a whole number of days. The prior fill's `days_supply` is read from the parent prescription's `days_supply` (each fill copies that value, so the two are equal). For a cash patient (no plan), the edit still runs and uses the same 0.80 default threshold. It then computes the elapsed days as the whole number of calendar days between the parent prescription's `last_dispensed_utc` and `current_utc`, also floored. The refill is allowed only when the elapsed days are greater than or equal to the required days; when elapsed days equal required days the refill passes, and when elapsed days fall one short the refill is rejected with `ERR_REFILL_TOO_SOON`. A first fill, for which `last_dispensed_utc` is still null, always passes this edit. The only prior fill that matters is the most recent dispense, which is exactly what `last_dispensed_utc` records.

### 3.9. Staging, Payment, Dispensing, and Reversal

Once a fill is `READY_FILL` with a `PAID` claim, a technician or pharmacist stages it for pickup. Staging requires the fill to be in `READY_FILL` (otherwise `ERR_FILL_NOT_READY`) and the `claim_status` to be `PAID` (otherwise `ERR_CLAIM_NOT_PAID`); on success the fill moves to `WILL_CALL` and its `pickup_deadline_utc` is set to 10 days after `current_utc`.

Payment is collected by a cashier or technician, recording the `fill_id` being paid, the `amount_cents` collected, and the `tendered_by` identifier of the collector. For an insured fill the `amount_cents` must equal the fill's `final_copay_cents`; for a cash patient it must equal the fill's `gross_amount_cents`; a mismatch is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A payment record starts with its `refunded` flag false. Payment records may be listed filtered by `fill_id`.

Dispensing is the regulated culmination, performed by a pharmacist. It requires the fill to be in `WILL_CALL` (otherwise `ERR_FILL_NOT_WILL_CALL`), the will-call window to be open — `current_utc` at or before `pickup_deadline_utc`, otherwise `ERR_WILL_CALL_EXPIRED` — and a payment record to exist for the fill whose `amount_cents` equals the fill's `final_copay_cents`, otherwise `ERR_PAYMENT_REQUIRED`. As with override, when the drug is Schedule `CII` the dispensing pharmacist's `X-User-ID` must differ from the technician who created the fill, otherwise `ERR_SEGREGATION_OF_DUTIES`. On success the system first sets the fill's `status` to `DISPENSED` — set before the monitoring regeneration below so the committed count includes this very fill — then sets the parent prescription's `last_dispensed_utc` to `current_utc`, recomputes `refills_remaining` and auto-exhausts the prescription if it hits 0, and, if the drug is controlled, regenerates the patient's monitoring report under the committed variant and recomputes the patient's `pdmp_flag` and `controlled_status` from the result.

A paid claim that has not yet dispensed can be reversed by a pharmacist. Reversal requires the `claim_status` to be `PAID` (otherwise `ERR_CLAIM_NOT_PAID`) and the fill not to be `DISPENSED` (otherwise `ERR_FILL_ALREADY_DISPENSED`); it sets `claim_status` to `REVERSED`, reverses `plan_paid_cents` back to 0, and refunds any existing payment record by setting its `refunded` flag to true. Reversal conserves money: `gross_amount_cents` is untouched while the plan-paid and final copay amounts revert to 0.

### 3.10. Prior-Auth Decisions, Cancellation, Expiry, and Will-Call Return

A pharmacist resolves a pending prior-auth request by approving or denying it, each carrying `expected_priorauthrequest_version`. Approval requires the request to be `PENDING` (otherwise `ERR_PA_NOT_PENDING`), `current_utc` to be at or before its `expires_utc` (otherwise `ERR_PA_EXPIRED`), and the version to match (otherwise `ERR_STALE_PA_VERSION`). On approval the request transitions from `PENDING` to `APPROVED`, sets `decided_utc` to `current_utc`, increments its own `version` by one, and cycles the linked fill back: the fill's `claim_status` returns to `UNCLAIMED` and its `status` returns from `PA_REFERRAL` to `ADJUDICATING`, so the claim can be resubmitted and — because an approved request now exists — clear to `READY_FILL`. Denial requires the request to be `PENDING` (`ERR_PA_NOT_PENDING`) and the version to match (`ERR_STALE_PA_VERSION`); it transitions the request from `PENDING` to `DENIED`, sets `decided_utc` to `current_utc`, increments its own `version`, sets the linked fill's `claim_status` to `REJECTED` and its `status` from `PA_REFERRAL` to `CANCELLED`, and recomputes the parent prescription's `refills_remaining`. An administrator-run sweep expires a still-pending request once `current_utc` passes its `expires_utc`: the request transitions from `PENDING` to `EXPIRED`, and the linked fill's `claim_status` becomes `REJECTED` while its `status` becomes `CANCELLED`.

A non-terminal fill can be cancelled by a pharmacist or technician. Cancellation is allowed when the fill's `status` is one of `ENTERED`, `DUR_REVIEW`, `ADJUDICATING`, `PA_REFERRAL`, `READY_FILL`, or `WILL_CALL` (a fill already in a terminal state is rejected with `ERR_FILL_NOT_CANCELLABLE`), and only when the `claim_status` is not `PAID` — a paid claim must be reversed first, otherwise `ERR_CLAIM_PAID_REVERSE_FIRST`. On cancellation the fill moves to `CANCELLED`; if its `claim_status` was `SUBMITTED` or `PA_PENDING` that claim is moved to `REVERSED`; and the parent prescription's `refills_remaining` is recomputed.

When a will-call fill is not picked up in time, an administrator-run sweep returns it to stock. The sweep applies when the fill is `WILL_CALL` and `current_utc` has passed its `pickup_deadline_utc`: the fill transitions to `RETURNED_TO_STOCK`, its `claim_status` becomes `REVERSED` as a compensation for the paid claim, `plan_paid_cents` is reversed and any payment record is refunded with its `refunded` flag set true, and the parent prescription's `refills_remaining` is recomputed so the returned fill no longer counts.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that read a resource or modify an existing one — including every state-transition action and every system sweep — return `200 OK`. All request and response bodies follow the envelope of §2.2; the specific fields each operation consumes and the side effects it produces are defined in the §3 workflow narratives, not in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the deterministic pharmacy clock | PharmacyAdmin |
| GET | `/_clock` | Read the current pharmacy clock | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/drug-products` | Create a drug product | PharmacyAdmin |
| GET | `/drug-products` | List drug products | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/drug-products/{id}` | Get a drug product | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/drug-products/{id}/discontinue` | Discontinue a drug product | PharmacyAdmin |
| POST | `/insurance-plans` | Create an insurance plan | PharmacyAdmin |
| GET | `/insurance-plans` | List insurance plans | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/insurance-plans/{id}` | Get an insurance plan | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/formulary-entries` | Add a drug to a plan formulary | PharmacyAdmin |
| GET | `/formulary-entries` | List formulary entries | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/formulary-entries/{id}` | Get a formulary entry | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/interaction-rules` | Create a drug-drug interaction rule | PharmacyAdmin |
| GET | `/interaction-rules` | List interaction rules | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/interaction-rules/{id}` | Get an interaction rule | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/patients` | Register a patient | PharmacyAdmin, Technician |
| GET | `/patients` | List patients | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/patients/{id}` | Get a patient | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/patients/{id}/clear-pdmp-block` | Pharmacist manually clears a PDMP block | Pharmacist |
| POST | `/prescribers` | Create a prescriber | PharmacyAdmin |
| GET | `/prescribers` | List prescribers | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/prescribers/{id}` | Get a prescriber | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/prescriptions` | Intake an e-prescription | PharmacyAdmin, Technician |
| GET | `/prescriptions` | List prescriptions | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/prescriptions/{id}` | Get a prescription | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/prescriptions/{id}/discontinue` | Discontinue a prescription | Pharmacist |
| POST | `/prescriptions/{id}/expire-scan` | System sweep: expire the prescription if past its expiry | PharmacyAdmin |
| POST | `/fills` | Create a fill or refill for a prescription | PharmacyAdmin, Technician |
| GET | `/fills` | List fills | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/fills/{id}` | Get a fill | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/fills/{id}/run-dur` | Run the DUR/drug-interaction screen on a fill | Technician, Pharmacist |
| POST | `/fills/{id}/override-dur` | Pharmacist overrides DUR alerts and advances the fill | Pharmacist |
| POST | `/fills/{id}/submit-claim` | Submit the insurance claim for real-time adjudication | Technician, Pharmacist |
| POST | `/fills/{id}/reverse-claim` | Reverse a paid claim | Pharmacist |
| POST | `/fills/{id}/stage-will-call` | Stage a ready fill in will-call | Technician, Pharmacist |
| POST | `/fills/{id}/dispense` | Dispense a will-call fill to the patient | Pharmacist |
| POST | `/fills/{id}/cancel` | Cancel a non-terminal fill | Pharmacist, Technician |
| POST | `/fills/{id}/expire-will-call` | System sweep: return an expired will-call fill to stock | PharmacyAdmin |
| GET | `/dur-alerts` | List DUR alerts | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/dur-alerts/{id}` | Get a DUR alert | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/prior-auth-requests` | List PA requests | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/prior-auth-requests/{id}` | Get a PA request | PharmacyAdmin, Pharmacist, Technician, Cashier |
| POST | `/prior-auth-requests/{id}/approve` | Approve a prior-auth request | Pharmacist |
| POST | `/prior-auth-requests/{id}/deny` | Deny a prior-auth request | Pharmacist |
| POST | `/prior-auth-requests/{id}/expire-scan` | System sweep: expire a pending PA past its expiry | PharmacyAdmin |
| POST | `/pdmp-reports` | Manually query PDMP for a patient | Pharmacist |
| GET | `/pdmp-reports` | List PDMP reports | PharmacyAdmin, Pharmacist |
| GET | `/pdmp-reports/{id}` | Get a PDMP report | PharmacyAdmin, Pharmacist |
| POST | `/payment-records` | Collect patient payment for a fill at pickup | Cashier, Technician |
| GET | `/payment-records` | List payment records | PharmacyAdmin, Pharmacist, Technician, Cashier |
| GET | `/payment-records/{id}` | Get a payment record | PharmacyAdmin, Pharmacist, Technician, Cashier |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 401 Unauthorized |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_NDC` | 409 Conflict |
| `ERR_DUPLICATE_PLAN_ROUTING` | 409 Conflict |
| `ERR_DUPLICATE_NPI` | 409 Conflict |
| `ERR_STALE_PRESCRIPTION_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PA_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 Conflict |
| `ERR_OPEN_FILL_EXISTS` | 409 Conflict |
| `ERR_FILL_NOT_ENTERED` | 409 Conflict |
| `ERR_FILL_NOT_IN_DUR_REVIEW` | 409 Conflict |
| `ERR_FILL_NOT_ADJUDICATING` | 409 Conflict |
| `ERR_FILL_NOT_READY` | 409 Conflict |
| `ERR_FILL_NOT_WILL_CALL` | 409 Conflict |
| `ERR_FILL_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_FILL_ALREADY_DISPENSED` | 409 Conflict |
| `ERR_CLAIM_ALREADY_OPEN` | 409 Conflict |
| `ERR_CLAIM_NOT_PAID` | 409 Conflict |
| `ERR_CLAIM_PAID_REVERSE_FIRST` | 409 Conflict |
| `ERR_PA_NOT_PENDING` | 409 Conflict |
| `ERR_PA_EXPIRED` | 409 Conflict |
| `ERR_PATIENT_NOT_BLOCKED` | 409 Conflict |
| `ERR_PRESCRIBER_DEA_INVALID` | 422 Unprocessable Entity |
| `ERR_DRUG_DISCONTINUED` | 409 Conflict |
| `ERR_DUR_NOT_OVERRIDDEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PATIENT_CONTROLLED_LOCKED` | 403 Forbidden |
| `ERR_OVERRIDE_REASON_REQUIRED` | 422 Unprocessable Entity |
| `ERR_REFILL_TOO_SOON` | 409 Conflict |
| `ERR_WILL_CALL_EXPIRED` | 409 Conflict |
| `ERR_NO_REFILLS_REMAINING` | 409 Conflict |
| `ERR_DRUG_NOT_ON_FORMULARY` | 422 Unprocessable Entity |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_PAYMENT_REQUIRED` | 409 Conflict |

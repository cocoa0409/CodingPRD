# Ambulance EMS Billing API — Product Requirements Document

## 1. Introduction

Ground ambulance and emergency medical services (EMS) operate at the intersection of clinical documentation and a uniquely adversarial reimbursement landscape. A single transport begins as a NEMSIS electronic patient-care record (ePCR) imported from a dispatch system, must be coded to a level of service, attested for medical necessity, certified by a physician where the rules demand it, and only then offered to a cascade of payers — Medicare, Medicaid, automobile insurers, and commercial plans — each sequenced according to the patient's coordination-of-benefits ordering and each applying its own fee schedule. This API is the system of record that drives a transport from that first imported run record through to a fully reconciled ledger in which every cent billed has been either paid, contractually adjusted, written off as charity, capped under balance-billing protections, or recorded as a patient balance.

The system serves an EMS agency's billing operation as a set of cooperating roles. Dispatchers import run records and schedule the vehicles and crews that perform them. Coders assign the level of service that determines the HCPCS base rate and attest that the patient's condition required ambulance transport. Compliance officers sign Physician Certification Statements, return incomplete documentation for revision, and apply the charity and No Surprises Act write-offs that protect patients from surprise bills. Billers submit claims in payer sequence, post the 835 remittances that adjudicate them, run the denial-appeal-resubmit negotiation loop, and post payments. A billing administrator bootstraps the reference data and exercises discretionary overrides.

Two themes run through every workflow. The first is **dual-dimension state**: a transport tracks its documentation lifecycle and its billing lifecycle as two independent dimensions that advance on their own triggers but guard each other at key gates. The second is **ledger reconciliation**: every charge, remittance, payment, and adjustment recomputes a small family of derived totals on the transport, and the correctness of patient liability depends entirely on those totals being recomputed in a pinned order after each posting.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across the entire API. All resource collections are flat: entities reference one another by foreign key, and list endpoints expose those references through filterable reverse-reachability rather than deep URL nesting.

### 2.1. User and Role-Based Access Control

Every request other than the three bootstrap-open creation endpoints must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. When either header is missing or invalid on a protected endpoint, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are present and valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `BillingAdmin`, `Dispatcher`, `Coder`, `Biller`, and `ComplianceOfficer`. The three creation endpoints that bootstrap reference data — registering an agency, creating a payer plan, and creating a patient — are open and may be invoked anonymously (no valid role required), in addition to being available to the relevant authenticated roles. Because these three endpoints are bootstrap-open, no role restriction is enforced on them: a request that supplies authentication headers passes so long as the header pair is a valid `X-User-ID`/`X-User-Role` pair naming any of the five recognized roles (the roles named in §4 for these three endpoints are advisory, not enforced); only a malformed header pair — exactly one header present, or an unrecognized role value — is rejected with `ERR_UNAUTHENTICATED`.

Four of the five roles are entity-backed. When `X-User-Role` is `Dispatcher`, `Coder`, `Biller`, or `ComplianceOfficer`, the `X-User-ID` is the `id` of the acting `AgencyStaff` member; ownership and authority checks on any resource that references an `AgencyStaff` member compare the resource's foreign-key field to `X-User-ID`. In particular, the PCS-signature authority check reads the acting `AgencyStaff` record identified by `X-User-ID`. When `X-User-Role` is `BillingAdmin`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip; it defaults to 0 and must be at least 0. A `limit` outside the inclusive range of 1 through 100, or a negative `offset`, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 422) on any list endpoint.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. List responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Identifiers

Every resource carries a server-minted `id` formatted as a UUID with no type prefix. Every resource also carries a `created_at`, an ISO 8601 UTC timestamp with three fractional digits set when the resource is first created. All of the entities in this system — `Agency`, `AgencyStaff`, `PayerPlan`, `Patient`, `Vehicle`, `CrewMember`, `UnitAssignment`, `Transport`, `Charge`, `Claim`, `RemittanceLine`, `Payment`, and `Adjustment` — additionally carry an `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and a `version` (an integer beginning at 1 and incremented by exactly one on every mutation of the resource). The `version` integer is the basis for the optimistic concurrency control described in §2.7.

### 2.5. Hierarchical Consistency, Cascades, and Derived-Field Reconciliation

Several operations mutate more than one entity. Whenever a posting touches a transport's financial picture — the synthesis of charges at coding time, the posting of a remittance line, the posting of a payment, or the posting of an adjustment — the system recomputes the transport's family of derived ledger fields and refreshes the transport's `updated_at` and `version`. Posting a remittance, in particular, is a cascade: it sets the adjudicated amounts on the claim, may create a payer payment, records the contractual write-off, reconciles the transport ledger, and may automatically advance the transport's billing dimension when the payer sequence is exhausted. These automatic billing-dimension advances are server-driven; the client does not request them on a separate resource.

When a request path contains more than one resource identifier (for example, a claim's remittances are reached beneath a claim, and a transport's claims beneath a transport), the system validates each identifier left-to-right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first path segment whose resource does not exist, before evaluating any foreign keys carried in the body. Foreign-key targets named in the request body — `payer_plan_id`, `patient_id`, `prior_claim_id`, `agency_id`, `transport_id`, and `claim_id` — are validated only after the path resolves; a missing body FK target is rejected with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404).

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Where a calculation produces a fractional cent, the result is rounded half up to the nearest whole cent. Several totals floor at zero: a derived total can never be reported as negative even when intermediate subtraction would suggest it. The specific rounding boundaries — in particular the per-tier rounding of the mileage charge and the whole-percent rounding of the charity income test — are stated with the calculations that own them in §3.

### 2.7. Optimistic Concurrency Control on Claim Submission

Submitting a new primary claim against a transport is the one operation in this system guarded by optimistic concurrency control. A request to submit a claim must carry `expected_transport_version` as a required field, holding the `version` of the target transport that the client last observed. If `expected_transport_version` does not equal the transport's current `version`, the request is rejected with `ERR_STALE_TRANSPORT_VERSION` (HTTP 412). This guard exists because a primary rebill legitimately supersedes the prior primary claim: a request carrying the transport's current `version` succeeds and replaces the prior primary, whereas a request still carrying an older `version` is working from a superseded view of the transport and is rejected. The rejection is keyed purely on the version integer. No other endpoint accepts or requires a transport-version field.

### 2.8. The Parallel State Model of a Transport

A `Transport` advances along two independent state dimensions. The `documentation_status` dimension tracks the ePCR and compliance lifecycle and moves through `IMPORTED`, `CODED`, `NECESSITY_REVIEW`, `DOCUMENTATION_COMPLETE`, and `RETURNED`. The `billing_status` dimension tracks the claim and payer-sequence lifecycle and moves through `UNBILLED`, `BILLING_IN_PROGRESS`, `BILLED`, `PATIENT_BALANCE`, `CLOSED`, and `VOID`, of which `CLOSED` and `VOID` are terminal. The two dimensions advance on their own triggers, but the documentation dimension gates the billing dimension: billing cannot begin until documentation is complete (§3.4). A separate `Claim` entity carries its own cyclic lifecycle through `DRAFT`, `SUBMITTED`, `PAID`, `DENIED`, `APPEALED`, and `CLOSED` (§3.6).

### 2.9. Reference-Data Lifecycle and Operational Gates

Reference entities carry simple operational status flags that gate the workflows that consume them. An `Agency` has a `status` of `ACTIVE` or `SUSPENDED`; a `SUSPENDED` agency cannot import new runs. A `PayerPlan` has a `status` of `ACTIVE` or `INACTIVE`; an `INACTIVE` plan cannot be named on a new claim. A `Vehicle` has a `status` of `IN_SERVICE` or `OUT_OF_SERVICE`; an `OUT_OF_SERVICE` vehicle cannot be assigned. A `CrewMember` has a `status` of `ACTIVE` or `INACTIVE`, and an `AgencyStaff` member has a `status` of `ACTIVE` or `DEACTIVATED`. All five status flags are system-managed: an agency, payer plan, vehicle, crew member, and staff member are each created in their respective active/in-service default state, and dedicated capabilities transition the agency and plan and vehicle out of it.

## 3. Business Logic & Workflows

### 3.1. Establishing the Agency, Its Staff, and Its Fleet

An EMS operation begins by registering an `Agency`. The bootstrap-open creation supplies the agency `name`, its 10-digit `npi`, and the two-letter `state_code` of the US state it operates in. Two policy parameters are set at the agency level. The `base_state_is_no_surprises` flag — defaulting to false — declares whether the agency's state extends ground-ambulance balance-billing protection beyond the federal baseline; this flag participates in the No Surprises protection test described in §3.10. The `charity_fpl_threshold_pct` — defaulting to 200 — is the household-income ceiling, expressed as a percent of the Federal Poverty Level, at or below which a patient qualifies for a full charity write-off (§3.10). A new agency is created with `status` `ACTIVE`.

Staff are registered against an agency. Each `AgencyStaff` record names its `agency_id`, the staff member's `full_name`, and a functional `role` drawn from `Dispatcher`, `Coder`, `Biller`, or `ComplianceOfficer` — this role is the binding used for the `X-User-Role` header. The optional `pcs_signature_authority` flag — defaulting to false — marks whether the staff member may attest a Physician Certification Statement signature; only a compliance officer holding this authority can complete documentation, as described in §3.4. A staff member is created `ACTIVE` and may later be `DEACTIVATED`.

The fleet consists of vehicles and crew members, each registered against an `agency_id`. A `Vehicle` carries a `unit_call_sign` that is unique per agency and a `turnaround_minutes` buffer — defaulting to 30 — that represents the minimum decontamination and restock time required between back-to-back assignments of that vehicle; this buffer is treated as part of the vehicle's occupied interval for overlap detection (§3.2). A vehicle is created `IN_SERVICE` and may be taken `OUT_OF_SERVICE`. A `CrewMember` carries a `full_name` and a `certification` — `EMT`, `AEMT`, or `PARAMEDIC` — that expresses the highest scope of practice the member is credentialed for; an `EMT` covers BLS work, an `AEMT` covers BLS and ALS1 work, and a `PARAMEDIC` covers any level of service. A crew member is created `ACTIVE`.

Payer plans and patients round out the reference data. A `PayerPlan` names its display `name`, a `payer_type` drawn from `MEDICARE`, `MEDICAID`, `AUTO`, `COMMERCIAL`, or `SELF_PAY`, a `qpa_multiplier` (the Qualifying Payment Amount multiplier applied to the Medicare allowed amount to derive a commercial or auto plan's allowed cap, defaulting to 1.0 and ignored for Medicare, Medicaid, and self-pay), and an `allows_balance_billing` flag (defaulting to true) governing whether the plan permits the agency to bill the patient the gap between billed charge and the plan's allowed amount. A plan is created `ACTIVE` and may be deactivated to `INACTIVE`. A `Patient` carries a `full_name`, a `date_of_birth` as an ISO 8601 date, a `household_size` (defaulting to 1), an `annual_household_income_cents` (self-reported, defaulting to null meaning not provided), and a `coverages` array. Each entry in `coverages` is an object holding a `payer_plan_id` and a `policy_rank`, where `policy_rank` is the patient-asserted payer ordering with 1 designating the primary payer; each `payer_plan_id` resolves to a payer plan.

### 3.2. Scheduling Units: Vehicle and Crew Assignment

Before or alongside billing, a `Dispatcher` schedules the physical resources that perform a transport by creating a `UnitAssignment`. The payload names the `transport_id` the run serves, the `vehicle_id` of the assigned ambulance, the `crew_member_id` of the assigned lead crew member, and the dispatch-to-clear occupied window as `window_start_iso` and `window_end_iso` (both ISO 8601 UTC). The window end must be strictly after the window start; a window whose `window_end_iso` is equal to or earlier than its `window_start_iso` is rejected with `ERR_INVALID_WINDOW` (HTTP 422).

Several constraints guard the assignment beyond the window check. The assigned vehicle must be `IN_SERVICE` and the assigned crew member must be `ACTIVE`; otherwise the request is rejected with `ERR_RESOURCE_OUT_OF_SERVICE` (HTTP 409). When the transport has already been coded to a level of service, the crew member's certification must cover that level — an `EMT` may serve only `BLS`, an `AEMT` may serve `BLS` or `ALS1`, and a `PARAMEDIC` may serve any of `BLS`, `ALS1`, `ALS2`, or `SCT`; a certification that does not cover the coded level is rejected with `ERR_CREW_CERT_INSUFFICIENT` (HTTP 409).

Two overlap checks complete the assignment validation, and they use deliberately different interval semantics. The vehicle overlap check treats each assignment as occupying a closed interval extended by the vehicle's turnaround buffer: the candidate occupies the interval from `window_start_iso` through `window_end_iso` plus the vehicle's `turnaround_minutes`, and the request is rejected with `ERR_VEHICLE_DOUBLE_BOOKED` (HTTP 409) if that buffered interval intersects any existing assignment's buffered interval for the same vehicle, with a boundary touch at the buffer edge counting as a conflict. The crew overlap check treats each assignment as occupying a half-open interval from `window_start_iso` up to but not including `window_end_iso`, with no buffer; the request is rejected with `ERR_CREW_DOUBLE_BOOKED` (HTTP 409) if that half-open interval intersects any existing half-open interval for the same crew member, so that a back-to-back assignment whose start equals a prior assignment's end is permitted.

### 3.3. Importing a Run and Assigning Level of Service

A `Dispatcher` brings a transport into the system by importing a NEMSIS dispatch/run record. The import names the `agency_id` that performed the transport and the `patient_id` who was transported, an agency-assigned `run_number`, the `dispatch_iso` timestamp, the loaded mileage, and the HCPCS origin and destination geography. The `origin_modifier` is a single-letter HCPCS origin code drawn from `S` (scene), `H` (hospital), `N` (skilled nursing), `R` (residence), `E` (emergency room), `P` (physician office), or `I` (intermediate stop). The `destination_modifier` is a single-letter HCPCS destination code drawn from `H`, `N`, `R`, `E`, `P`, `I`, or `X` (freestanding emergency department). The `loaded_miles` is the odometer loaded mileage (patient onboard) to one decimal place and must be strictly greater than zero; a `loaded_miles` of zero or less is rejected with `ERR_INVALID_LOADED_MILES` (HTTP 422). The optional `is_rural_pickup` flag (defaulting to false) marks the pickup ZIP as rural for the mileage rural-bonus rule, and the optional `emergency_indicator` flag (defaulting to false) marks the dispatch as an emergency response, which drives both the HCPCS base code and the PCS requirement.

The importing agency must be `ACTIVE`; an import attempted under a `SUSPENDED` agency is rejected with `ERR_AGENCY_SUSPENDED` (HTTP 409). The `run_number` must be unique per agency across all transports that are not voided; a collision with an existing non-void transport of the same agency is rejected with `ERR_DUPLICATE_RUN_NUMBER` (HTTP 409). A freshly imported transport begins with `documentation_status` `IMPORTED` and `billing_status` `UNBILLED`, with its `level_of_service` null, `medical_necessity_met` false, `pcs_signed` false, and every derived ledger total — `total_billed_cents`, `total_allowed_cents`, `total_paid_cents`, `total_writeoff_cents`, `patient_responsibility_cents`, and `balance_cents` — at zero.

Coding the transport advances `documentation_status` from `IMPORTED` to `CODED` and is performed by a `Coder`, who supplies the `level_of_service` as one of `BLS`, `ALS1`, `ALS2`, or `SCT`. Coding is permitted only while the transport's `billing_status` is `UNBILLED`; once billing has started the transport cannot be recoded, and an attempt is rejected with `ERR_INVALID_DOCUMENTATION_STATE` (HTTP 409). Coding assigns the `level_of_service`, resolves the two HCPCS lines, synthesizes the two `Charge` rows, recomputes `total_billed_cents` as the sum of those charges, and recomputes `balance_cents`.

Charge synthesis resolves the base code from the level of service together with the emergency indicator. For `BLS`, the base HCPCS code is `A0429` (BLS emergency) when the transport's `emergency_indicator` is true and `A0428` (BLS non-emergency) otherwise. For `ALS1`, the base code is `A0427` (ALS1 emergency) when `emergency_indicator` is true and `A0426` (ALS1 non-emergency) otherwise. For `ALS2`, the base code is always `A0433`, because ALS2 is always treated as emergency-grade. For `SCT`, the base code is always `A0434`. The mileage line always uses the ground-mileage code `A0425`. The system synthesizes exactly two `Charge` rows per coded transport: a `BASE_RATE` charge with `units` of 1, and a `MILEAGE` charge with `units` equal to the transport's `loaded_miles`. Each `Charge` records its owning `transport_id`, its `charge_type` (`BASE_RATE` or `MILEAGE`), its resolved `hcpcs_code`, its `units`, and its computed `billed_amount_cents`.

The billed amount of each charge line is computed as follows. The `BASE_RATE` line's `billed_amount_cents` is the base-rate amount for the resolved base code, drawn from the schedule in which `A0428` is 45000 cents, `A0429` is 60000 cents, `A0426` is 65000 cents, `A0427` is 80000 cents, `A0433` is 110000 cents, and `A0434` is 130000 cents. The `MILEAGE` line's `billed_amount_cents` is computed at 1750 cents per loaded mile, with a rural bonus applied to the first 17 loaded miles only when the pickup is rural. When `is_rural_pickup` is true, the system splits the mileage into a rural portion equal to the lesser of the loaded miles and 17.0 and a normal portion equal to the loaded miles minus 17.0 but not below zero; it then computes the rural tier as the rural miles multiplied by 1750 cents and by the rural bonus factor of 1.5, rounds that tier half up to a whole cent, computes the normal tier as the normal miles multiplied by 1750 cents, rounds that tier half up to a whole cent, and sums the two rounded tiers. When `is_rural_pickup` is false, the mileage billed amount is simply the loaded miles multiplied by 1750 cents, rounded half up to a whole cent. The rounding is applied to each tier before summing, never to the sum.

### 3.4. The Documentation Lifecycle and Its Revision Loop

Once a transport is `CODED`, the `Coder` attests medical necessity, advancing `documentation_status` from `CODED` to `NECESSITY_REVIEW` and setting `medical_necessity_met` to true. The same attestation action also serves the revision loop: a transport sitting in `RETURNED` is moved back to `NECESSITY_REVIEW` by the coder re-attesting, again setting `medical_necessity_met` to true. Attestation is admitted only from `CODED` or `RETURNED`; from any other documentation state the request is rejected with `ERR_INVALID_DOCUMENTATION_STATE` (HTTP 409).

A `ComplianceOfficer` resolves a transport in `NECESSITY_REVIEW` in one of two directions. Signing the Physician Certification Statement advances `documentation_status` from `NECESSITY_REVIEW` to `DOCUMENTATION_COMPLETE`. This step requires that the acting `AgencyStaff` member hold `pcs_signature_authority` equal to true; a compliance officer lacking that authority is rejected with `ERR_PCS_AUTHORITY_REQUIRED` (HTTP 403). Whether a PCS signature is actually recorded depends on the PCS requirement test: a Physician Certification Statement is `REQUIRED` for a non-emergency transport that originates from a skilled-nursing facility (`origin_modifier` `N`) or a residence (`origin_modifier` `R`), and is `NOT_REQUIRED` otherwise — specifically, if the transport's `emergency_indicator` is true the requirement is `NOT_REQUIRED`, otherwise if the `origin_modifier` is `N` or `R` the requirement is `REQUIRED`, and in every other case it is `NOT_REQUIRED`. When the requirement is `REQUIRED`, signing records `pcs_signed` as true; when the requirement is `NOT_REQUIRED`, the step still completes and leaves `pcs_signed` false. Either way the transport reaches `DOCUMENTATION_COMPLETE`, which is the gate that the billing dimension requires before any claim may be submitted.

Alternatively, the compliance officer may return the documentation for revision, advancing `documentation_status` from `NECESSITY_REVIEW` to `RETURNED` and resetting `medical_necessity_met` to false. `RETURNED` is not terminal; it is the entry point of the revision loop in which the coder re-attests to return the transport to `NECESSITY_REVIEW`. Both signing and returning are admitted only from `NECESSITY_REVIEW`; attempted from any other documentation state they are rejected with `ERR_INVALID_DOCUMENTATION_STATE` (HTTP 409).

### 3.5. Voiding an Unbilled Transport

Before any claim exists, a `Biller` may void a transport, advancing `billing_status` from `UNBILLED` to the terminal `VOID`. Voiding is admitted only while the transport's `billing_status` is `UNBILLED`; once any claim exists the transport's billing status no longer admits the void transition and the attempt is rejected with `ERR_INVALID_BILLING_STATE` (HTTP 409). Voiding deletes the synthesized charge rows and resets `total_billed_cents` to zero. Because the run-number uniqueness constraint spans only non-void transports, voiding also frees the transport's `run_number` for reuse by a future import.

### 3.6. Submitting Claims and Walking the Payer Sequence

Billing begins when a `Biller` submits the first, primary claim against a transport, which advances `billing_status` from `UNBILLED` to `BILLING_IN_PROGRESS`. The submission names the `payer_plan_id` the claim goes to, omits or leaves null the `prior_claim_id` for a primary claim, and carries `expected_transport_version` as described in §2.7. Submitting the primary claim is guarded by a stack of preconditions evaluated in order. First, the transport must have reached `DOCUMENTATION_COMPLETE`; a claim attempted before then is rejected with `ERR_DOCUMENTATION_INCOMPLETE` (HTTP 409). The transport's `medical_necessity_met` must be true, or the request is rejected with `ERR_MEDICAL_NECESSITY_NOT_MET` (HTTP 409). When the PCS requirement test resolves to `REQUIRED`, the transport's `pcs_signed` must be true, or the request is rejected with `ERR_PCS_MISSING` (HTTP 409). The named payer plan must be `ACTIVE`, or the request is rejected with `ERR_PAYER_PLAN_INACTIVE` (HTTP 409). And `expected_transport_version` must match the transport's current `version`, or the request is rejected with `ERR_STALE_TRANSPORT_VERSION` (HTTP 412).

A submitted claim is created already in `SUBMITTED` status (the `DRAFT` to `SUBMITTED` transition is bundled into creation). The system assigns the new claim a `sequence_rank` derived from the `prior_claim_id` chain depth — 1 for the primary, 2 for the secondary, 3 for the tertiary — records its `transport_id`, sets its `billed_amount_cents` equal to the transport's `total_billed_cents` at submission, and computes its `prior_paid_cents` as the coordination-of-benefits context. The `prior_paid_cents` is the sum of `paid_amount_cents` across every claim already in this transport's chain whose `status` is `PAID` and whose `sequence_rank` is strictly less than the new claim's rank; claims that are `DENIED` or `SUBMITTED` are excluded from that sum, and the claims are summed in ascending `sequence_rank` order. Submitting the primary claim sets `billing_status` to `BILLING_IN_PROGRESS` and increments the transport's `version` by one.

A secondary or tertiary claim is submitted the same way but with `prior_claim_id` naming the immediately preceding claim in the sequence. A downstream claim is admitted only while the transport's `billing_status` is `BILLING_IN_PROGRESS`; a downstream submission attempted while the transport is in any other billing state (and, symmetrically, a fresh primary attempted while the transport is neither `UNBILLED` nor `BILLING_IN_PROGRESS`) is rejected with `ERR_INVALID_BILLING_STATE` (HTTP 409), and this billing-state admissibility gate is evaluated ahead of the documentation, necessity, PCS, payer-active, prior-claim, sequence, and version checks below. Two additional preconditions guard a downstream claim. The named `prior_claim_id` must resolve to a claim of the same transport whose status is `PAID` or `DENIED`; an unadjudicated prior claim is rejected with `ERR_PRIOR_CLAIM_NOT_ADJUDICATED` (HTTP 409). And the named payer must match the patient's coverage entry whose `policy_rank` equals the new claim's `sequence_rank`; a mismatch is rejected with `ERR_PAYER_SEQUENCE_MISMATCH` (HTTP 409).

A primary rebill is also possible while the transport is `BILLING_IN_PROGRESS`: submitting a fresh primary claim (again with `prior_claim_id` omitted or null) that legitimately supersedes the prior primary. A primary rebill is admitted only when the existing `sequence_rank` 1 claim is in `SUBMITTED` or `DENIED` status — a primary that has already been `PAID` cannot be rebilled, and the attempt is rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409) — and only when no claim of `sequence_rank` greater than 1 yet exists, because the primary cannot be rebilled once a secondary has been opened (likewise rejected with `ERR_INVALID_CLAIM_STATE`). The rebill again requires a matching `expected_transport_version` (§2.7). When admitted, the rebill supersedes the prior primary by setting that claim's status to `CLOSED`, creates a new `sequence_rank` 1 claim in `SUBMITTED` status, leaves `billing_status` at `BILLING_IN_PROGRESS`, and increments the transport's `version` by one.

### 3.7. Adjudication: Posting Remittances

A `Biller` adjudicates a `SUBMITTED` claim by posting an 835 remittance line against it. The remittance names its owning `claim_id`, an `outcome` of `PAID`, `PARTIAL`, or `DENIED`, the `paid_cents` the payer remitted, an optional `reported_allowed_cents` (the allowed amount the payer reports; null lets the system derive the allowed amount from the fee schedule), and a `denial_reason` that is required when the outcome is `DENIED` and drawn from `NOT_MEDICALLY_NECESSARY`, `MISSING_PCS`, `NON_COVERED_DESTINATION`, `COB_PRIMARY_NOT_BILLED`, or `DUPLICATE`. A `DENIED` remittance that omits the `denial_reason`, or a `PAID` or `PARTIAL` remittance that carries one, is rejected with `ERR_DENIAL_REASON_REQUIRED` (HTTP 422). The target claim must be in `SUBMITTED` status; a remittance posted against a claim in any other status is rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409).

A `PAID` or `PARTIAL` remittance advances the claim from `SUBMITTED` to `PAID`. The system first computes the claim's adjudicated allowed amount. When `reported_allowed_cents` is provided, the allowed amount is that reported figure verbatim. When `reported_allowed_cents` is null, the allowed amount is derived from the Medicare fee-schedule baseline for this transport's charges, scaled by payer type: for a `MEDICARE` plan the allowed amount equals the baseline; for a `MEDICAID` plan it is the baseline multiplied by 0.80 and rounded half up; for a `COMMERCIAL` or `AUTO` plan it is the baseline multiplied by the plan's `qpa_multiplier` and rounded half up; and for a `SELF_PAY` plan it equals the transport's `total_billed_cents`. The Medicare baseline for the transport is the sum of the base-rate component (drawn from the schedule in which `A0428` is 23000 cents, `A0429` is 31000 cents, `A0426` is 33000 cents, `A0427` is 41000 cents, `A0433` is 56000 cents, and `A0434` is 66000 cents) and the mileage component (computed at 800 cents per loaded mile, with the same first-17-mile rural bonus factor of 1.5 applied when the pickup is rural). Regardless of how the allowed amount is first derived, it is then capped at the remaining gap available to this payer: the allowed amount is the lesser of itself and the claim's `billed_amount_cents` minus the claim's `prior_paid_cents`, so that a secondary or tertiary payer never allows more than what remains after upstream payers.

Posting a `PAID` or `PARTIAL` remittance sets the claim's `allowed_amount_cents` to the computed allowed amount and its `paid_amount_cents` to the remittance's `paid_cents`, creates a payer `Payment` (a `Payment` with `source` `PAYER` and this claim's `claim_id`) for the paid amount, and records the line's `contractual_adjustment_cents`. The payer `Payment` is created only when `paid_cents` is strictly greater than zero; a `PAID` or `PARTIAL` remittance whose `paid_cents` is exactly zero records no `Payment`. The paid amount may never exceed what the payer allows: a remittance whose `paid_cents` exceeds the claim's derived or reported allowed amount is rejected with `ERR_PAID_EXCEEDS_ALLOWED` (HTTP 422).

The contractual adjustment recorded on a `PAID` or `PARTIAL` line depends on the claim's payer type and sequence rank. For a primary claim (`sequence_rank` 1) on a `MEDICARE` or `MEDICAID` plan, the full gap is automatically written off: the contractual adjustment is the claim's `billed_amount_cents` minus its `allowed_amount_cents`, floored at zero. For a primary claim on a `COMMERCIAL`, `AUTO`, or `SELF_PAY` plan, the contractual adjustment is zero at remittance time; the billed-minus-allowed gap is not auto-written-off and instead remains on the patient balance, to be resolved later either by an explicit balance-billing cap adjustment (when the patient is protected) or by legitimate balance billing of the full gap (when the patient is not protected), as described in §3.10. For a secondary or tertiary claim (`sequence_rank` greater than 1), each downstream payer writes off only the residual gap it was billed: the contractual adjustment is the claim's `billed_amount_cents` minus its `prior_paid_cents` minus its `allowed_amount_cents`, floored at zero.

A `DENIED` remittance advances the claim from `SUBMITTED` to `DENIED`, sets the claim's `allowed_amount_cents` and `paid_amount_cents` both to zero, and records no payer payment. After either outcome, the system reconciles the transport ledger and advances the billing dimension if the payer sequence is now exhausted.

### 3.8. The Denial-Appeal-Resubmit Negotiation Loop

A `DENIED` claim can be contested. A `Biller` appeals a denied claim, advancing its status from `DENIED` to `APPEALED`; the appeal is admitted only when the claim is `DENIED` and a resolvable denial reason exists (the latest `DENIED` remittance line is present), and is otherwise rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409). An appealed claim can then be resubmitted, advancing its status from `APPEALED` back to `SUBMITTED` and resetting its `allowed_amount_cents` and `paid_amount_cents` to zero; resubmission is admitted only from `APPEALED` and is otherwise rejected with `ERR_INVALID_CLAIM_STATE`. A resubmitted claim re-enters adjudication, so the cycle `DENIED` then `APPEALED` then `SUBMITTED` then `PAID` or `DENIED` may repeat across negotiation rounds.

The payer sequence is exhausted, and the transport's billing dimension advances out of `BILLING_IN_PROGRESS`, when no claim for the transport remains in `DRAFT`, `SUBMITTED`, or `APPEALED` — that is, when the latest claim has settled as `PAID` or `DENIED` and there is no further payer to bill. When the sequence is exhausted, the system recomputes the transport's patient responsibility and reconciles its ledger (recomputing `balance_cents`, `total_allowed_cents`, `total_paid_cents`, and `total_writeoff_cents`), and the billing dimension transitions from `BILLING_IN_PROGRESS` to `BILLED`. As part of leaving `BILLING_IN_PROGRESS`, a settled claim whose status is `PAID` automatically transitions to the terminal `CLOSED`, and a settled `DENIED` claim with no further coverage entry at the next `policy_rank` (one greater than its `sequence_rank`) likewise transitions to `CLOSED`.

From `BILLED`, the transport advances automatically based on the patient's remaining liability. When `patient_responsibility_cents` is greater than zero after the final payer adjudicates, the transport transitions from `BILLED` to `PATIENT_BALANCE`. When `patient_responsibility_cents` equals zero, the transport skips `PATIENT_BALANCE` and transitions directly from `BILLED` to the terminal `CLOSED`. A transport in `PATIENT_BALANCE` later transitions to `CLOSED` automatically once its remaining patient balance reaches zero through a patient payment, a charity write-off, a balance-billing cap, or an uncollectible write-off; that final transition reconciles the ledger one more time.

### 3.9. Posting Payments and Reconciling the Ledger

A `Biller` posts a `Payment` against a transport. The payment names its `transport_id`, a `source` of `PAYER` or `PATIENT`, an `amount_cents` that must be strictly greater than zero, and — for a payer payment — an optional `claim_id` attributing it to a specific claim (left null for a direct patient payment). The server stamps the payment's `posted_iso` at posting time. Payer payments are ordinarily created automatically as the side effect of a paid remittance (§3.7); patient payments are posted directly. A patient payment may not overpay the patient's current balance: an `amount_cents` for a `PATIENT`-source payment that exceeds the transport's current `patient_responsibility_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422).

Every payment posting reconciles the transport ledger, recomputes patient responsibility, and may advance the billing dimension to `CLOSED` when the balance reaches zero. The ledger reconciliation recomputes the transport's derived totals in a pinned order, because some totals depend on others: first `total_billed_cents` as the sum of the transport's charges' `billed_amount_cents`; then `total_allowed_cents` as the sum of the reported-or-derived allowed amounts across the posted remittance lines; then `total_paid_cents` as the sum of all payment `amount_cents` (both payer and patient); then `total_writeoff_cents` as the sum of all adjustment `amount_cents` plus the sum of all remittance lines' `contractual_adjustment_cents`; then `patient_responsibility_cents` per the patient-responsibility calculation below; and finally `balance_cents` as the transport's `total_billed_cents` minus `total_paid_cents` minus `total_writeoff_cents`, floored at zero.

Patient responsibility is the residual the patient owes after all payers and all write-offs. The system computes the total payer-sourced payments, the total patient-sourced payments, and the total write-offs (the sum of all adjustment `amount_cents` plus the sum of all remittance lines' `contractual_adjustment_cents`), then sets `patient_responsibility_cents` to the transport's `total_billed_cents` minus payer payments minus patient payments minus write-offs, floored at zero.

### 3.10. Write-Offs: Charity, No Surprises Caps, and Discretionary Adjustments

When a transport carries a remaining patient balance, a `ComplianceOfficer` (or a `BillingAdmin`) may apply an `Adjustment` to write some or all of it down. The adjustment names its `transport_id`, an `adjustment_type` of `CHARITY`, `UNCOLLECTIBLE`, `BALANCE_BILLING_CAP`, or `GOODWILL`, and — for the discretionary types — a `requested_amount_cents`. The applied write-off amount is recorded in the adjustment's `amount_cents`: for `CHARITY` and `BALANCE_BILLING_CAP` the server computes it, while for `UNCOLLECTIBLE` and `GOODWILL` it is taken from the request's `requested_amount_cents` (which is ignored for `CHARITY` and `BALANCE_BILLING_CAP`). Every persisted `Adjustment` additionally carries a `requested_amount_cents` field that echoes the request's `requested_amount_cents` verbatim — the supplied amount for the discretionary types, and null when no `requested_amount_cents` was supplied (as on a `CHARITY` or `BALANCE_BILLING_CAP` request that omits it). Every adjustment posting reconciles the ledger, recomputes patient responsibility, and may advance the transport to `CLOSED` when the balance reaches zero.

A `CHARITY` adjustment writes off the patient's full current balance when the patient qualifies on income. The patient's annual household income must be provided; a charity request when `annual_household_income_cents` is null is rejected with `ERR_CHARITY_INCOME_REQUIRED` (HTTP 422). Qualification is a Federal Poverty Level test: the FPL base for the household is 1508000 cents (the first-person figure) plus 532000 cents for each additional household member beyond the first — that is, the first-person figure plus the per-additional-member figure multiplied by the household size minus one. The patient's income as a percent of that FPL base is the income multiplied by 100, divided by the FPL base, and rounded half up to a whole percent. When that whole-percent figure is at or below the agency's `charity_fpl_threshold_pct`, the patient qualifies and the write-off equals the transport's current `patient_responsibility_cents`; when it exceeds the threshold, the request is rejected with `ERR_CHARITY_NOT_QUALIFIED` (HTTP 409). The rounding to a whole percent occurs before the comparison.

A `BALANCE_BILLING_CAP` adjustment is the No Surprises Act gap write-off, valid only when the patient is protected from balance billing. The patient is protected when the primary payer's `payer_type` is `MEDICARE` or `MEDICAID`, or when the primary payer's `payer_type` is `COMMERCIAL` or `AUTO` and either the plan's `allows_balance_billing` is false or the agency's `base_state_is_no_surprises` is true. A balance-billing cap requested when the primary payer is `COMMERCIAL` or `AUTO` but balance billing is not barred — neither the plan flag is false nor is the agency in a No Surprises state — is rejected with `ERR_BALANCE_BILLING_NOT_PROTECTED` (HTTP 409). When valid, the cap writes off the portion of the patient's current responsibility that exceeds the in-network cost share. The cost share is the primary claim's `allowed_amount_cents` minus the payer payment posted for that primary claim, floored at zero; the write-off is the transport's current `patient_responsibility_cents` minus that cost share, floored at zero. When the primary remittance already recorded a contractual write-off (the protected Medicare or Medicaid path), this gap is already zero and the cap adjustment posts an `amount_cents` of zero; for a protected commercial or auto patient whose primary remittance recorded no contractual write-off, the cap adjustment writes the gap down to the cost share.

These two computed write-offs realize the two patient-liability trajectories. For a `MEDICARE` or `MEDICAID` primary, the contractual write-off recorded at adjudication leaves the patient owing only the cost share (allowed minus payer-paid) immediately after adjudication. For a `COMMERCIAL` or `AUTO` primary that is not protected — `allows_balance_billing` true and the agency not in a No Surprises state — no contractual write-off is recorded and no cap is permitted, so the patient owes the full gap (billed minus payer-paid): the standard balance-bill outcome. For a `COMMERCIAL` or `AUTO` primary that is protected, the contractual write-off is zero at adjudication so the patient's responsibility first shows the full gap, and the compliance officer's balance-billing cap adjustment then writes the gap down to the cost share: the No Surprises outcome.

The two discretionary write-offs are simpler. An `UNCOLLECTIBLE` adjustment records bad debt and a `GOODWILL` adjustment records a discretionary courtesy; for both, the applied `amount_cents` is the `requested_amount_cents`, which must not exceed the transport's current `patient_responsibility_cents`, or the request is rejected with `ERR_WRITEOFF_EXCEEDS_BALANCE` (HTTP 422).

### 3.11. The Ordering of Validation Checks

Across all endpoints the validation checks are evaluated in a fixed priority so that the same request always fails for the same reason. Authentication is checked first: a missing or invalid header pair yields `ERR_UNAUTHENTICATED` before anything else. Authorization is next: a role not permitted for the operation yields `ERR_UNAUTHORIZED`. Then path existence is checked left-to-right, yielding `ERR_NOT_FOUND` for the first missing path resource, followed by the existence of body foreign-key targets, yielding `ERR_REFERENCED_RESOURCE_NOT_FOUND`. Next the request shape is checked: required body fields present and well-typed (such as `loaded_miles`, `dispatch_iso`, `origin_modifier`, `run_number`, and `level_of_service` on coding) yield `ERR_INVALID_REQUEST` when violated, and enum fields carrying a value outside their allowed set (`origin_modifier`, `destination_modifier`, `level_of_service`, `payer_type`, `outcome`, `adjustment_type`) yield `ERR_INVALID_ENUM`. Domain-specific business constraints — loaded-mileage positivity, run-number uniqueness, state admissibility, safety and referential gates, and fiscal ceilings — are evaluated after those structural checks, in the order their owning workflows describe above; the pagination bounds check applies last on list endpoints. When several gates could apply to one request, the earlier-priority gate's error is the one returned.

## 4. Endpoint Definitions

Operations that create a new resource return HTTP 201. Operations that modify an existing resource — including the documentation and billing state transitions and the deactivation and out-of-service capabilities — return HTTP 200. The three bootstrap-open creation endpoints (agency, payer plan, patient) may be called anonymously as well as by the listed roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Register an EMS agency (bootstrap-open) | BillingAdmin, Anonymous |
| GET | `/agencies/{id}` | Fetch an agency | BillingAdmin, Dispatcher, Coder, Biller, ComplianceOfficer |
| GET | `/agencies/{id}/staff` | List an agency's staff | BillingAdmin, ComplianceOfficer, Biller |
| POST | `/staff` | Register an agency staff member | BillingAdmin |
| GET | `/staff/{id}` | Fetch a staff member | BillingAdmin, ComplianceOfficer, Biller |
| POST | `/payer-plans` | Create a payer plan (bootstrap-open) | BillingAdmin, Anonymous |
| GET | `/payer-plans/{id}` | Fetch a payer plan | BillingAdmin, Biller, ComplianceOfficer |
| POST | `/payer-plans/{id}/deactivate` | Deactivate a payer plan | BillingAdmin |
| POST | `/patients` | Create a patient with coverage list (bootstrap-open) | BillingAdmin, Dispatcher, Anonymous |
| GET | `/patients/{id}` | Fetch a patient | BillingAdmin, Dispatcher, Coder, Biller, ComplianceOfficer |
| POST | `/vehicles` | Register an ambulance unit | BillingAdmin |
| GET | `/vehicles/{id}` | Fetch a vehicle | BillingAdmin, Dispatcher |
| POST | `/vehicles/{id}/out-of-service` | Take a vehicle out of service | BillingAdmin |
| GET | `/agencies/{id}/vehicles` | List an agency's vehicles | BillingAdmin, Dispatcher |
| POST | `/crew-members` | Register a crew member | BillingAdmin |
| GET | `/crew-members/{id}` | Fetch a crew member | BillingAdmin, Dispatcher |
| GET | `/agencies/{id}/crew-members` | List an agency's crew members | BillingAdmin, Dispatcher |
| POST | `/unit-assignments` | Assign a vehicle and crew member to a transport over a time window | Dispatcher |
| GET | `/unit-assignments/{id}` | Fetch a unit assignment | BillingAdmin, Dispatcher |
| GET | `/transports/{id}/unit-assignments` | List a transport's unit assignments | BillingAdmin, Dispatcher |
| GET | `/unit-assignments` | List unit assignments, filterable by `vehicle_id` or `crew_member_id` | BillingAdmin, Dispatcher |
| POST | `/transports` | Import a NEMSIS dispatch/run record as a Transport | Dispatcher |
| GET | `/transports/{id}` | Fetch a transport with computed ledger fields | BillingAdmin, Dispatcher, Coder, Biller, ComplianceOfficer |
| GET | `/transports` | List transports, filterable by `agency_id` or `patient_id` | BillingAdmin, Dispatcher, Coder, Biller, ComplianceOfficer |
| POST | `/transports/{id}/code` | Assign level of service; synthesize charges | Coder |
| POST | `/transports/{id}/attest-necessity` | Attest medical necessity | Coder |
| POST | `/transports/{id}/sign-pcs` | Record PCS signature and complete documentation | ComplianceOfficer |
| POST | `/transports/{id}/return-documentation` | Return documentation for revision | ComplianceOfficer |
| POST | `/transports/{id}/void` | Void an unbilled transport | Biller |
| GET | `/transports/{id}/charges` | List a transport's charges | BillingAdmin, Coder, Biller, ComplianceOfficer |
| POST | `/transports/{id}/claims` | Submit a claim to the next payer in sequence | Biller |
| GET | `/claims/{id}` | Fetch a claim | BillingAdmin, Biller, ComplianceOfficer |
| GET | `/transports/{id}/claims` | List a transport's claims in sequence | BillingAdmin, Biller, ComplianceOfficer |
| GET | `/claims` | List claims, filterable by `prior_claim_id` or `payer_plan_id` | BillingAdmin, Biller, ComplianceOfficer |
| POST | `/claims/{id}/appeal` | Appeal a denied claim | Biller |
| POST | `/claims/{id}/resubmit` | Resubmit an appealed claim | Biller |
| POST | `/claims/{id}/remittances` | Post an 835 remittance line adjudicating a claim | Biller |
| GET | `/claims/{id}/remittances` | List remittance lines for a claim | BillingAdmin, Biller, ComplianceOfficer |
| POST | `/transports/{id}/payments` | Post a payer or patient payment | Biller |
| GET | `/transports/{id}/payments` | List a transport's payments, filterable by `claim_id` | BillingAdmin, Biller, ComplianceOfficer |
| GET | `/payments/{id}` | Fetch a payment | BillingAdmin, Biller, ComplianceOfficer |
| GET | `/payments` | List payments, filterable by `claim_id` or `transport_id` | BillingAdmin, Biller, ComplianceOfficer |
| POST | `/transports/{id}/adjustments` | Apply a write-off (charity, uncollectible, balance-billing cap, or goodwill) | ComplianceOfficer, BillingAdmin |
| GET | `/transports/{id}/adjustments` | List a transport's adjustments | BillingAdmin, ComplianceOfficer, Biller |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCED_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_LOADED_MILES` | 422 |
| `ERR_DUPLICATE_RUN_NUMBER` | 409 |
| `ERR_INVALID_DOCUMENTATION_STATE` | 409 |
| `ERR_INVALID_BILLING_STATE` | 409 |
| `ERR_INVALID_CLAIM_STATE` | 409 |
| `ERR_PCS_AUTHORITY_REQUIRED` | 403 |
| `ERR_DOCUMENTATION_INCOMPLETE` | 409 |
| `ERR_MEDICAL_NECESSITY_NOT_MET` | 409 |
| `ERR_PCS_MISSING` | 409 |
| `ERR_PAYER_PLAN_INACTIVE` | 409 |
| `ERR_PRIOR_CLAIM_NOT_ADJUDICATED` | 409 |
| `ERR_PAYER_SEQUENCE_MISMATCH` | 409 |
| `ERR_DENIAL_REASON_REQUIRED` | 422 |
| `ERR_PAID_EXCEEDS_ALLOWED` | 422 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_CHARITY_INCOME_REQUIRED` | 422 |
| `ERR_CHARITY_NOT_QUALIFIED` | 409 |
| `ERR_BALANCE_BILLING_NOT_PROTECTED` | 409 |
| `ERR_WRITEOFF_EXCEEDS_BALANCE` | 422 |
| `ERR_STALE_TRANSPORT_VERSION` | 412 |
| `ERR_AGENCY_SUSPENDED` | 409 |
| `ERR_INVALID_WINDOW` | 422 |
| `ERR_RESOURCE_OUT_OF_SERVICE` | 409 |
| `ERR_CREW_CERT_INSUFFICIENT` | 409 |
| `ERR_VEHICLE_DOUBLE_BOOKED` | 409 |
| `ERR_CREW_DOUBLE_BOOKED` | 409 |
| `ERR_VALIDATION_PAGINATION` | 422 |

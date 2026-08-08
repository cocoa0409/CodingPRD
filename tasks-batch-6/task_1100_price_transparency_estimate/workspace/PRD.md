# Price Transparency & Cost Estimate API — Product Requirements Document

## 1. Introduction

Hospitals are now obligated to publish machine-readable negotiated rates and to hand every patient a good-faith estimate of what a shoppable service will cost them before care is rendered. Meeting that obligation is not a reporting afterthought — it is a live pricing engine that must reconcile chargemaster list prices, payer-specific negotiated rates, and each patient's year-to-date benefit accumulation into a single defensible number, and then stand behind that number when the patient disputes it or when the actual visit settles at a different figure than the projection.

This document specifies the Price Transparency & Cost Estimate service. The service ingests procedures and their gross charges, payer contracts and the negotiated rates that hang off them, and benefit plans that describe a patient's deductible, coinsurance, copay, and out-of-pocket ceiling. From those inputs it assembles and prices a Good-Faith-Estimate two different ways — once as a forward-looking projection at the moment of issue, and again as a settled figure when the linked appointment completes — because a patient's accumulators can move between those two moments. Around that core it layers shoppable-service comparison, prior-authorization gating, provider-and-room scheduling with two different collision models, a patient-initiated dispute loop, and an administrative transparency report. The remainder of this document defines the global contracts every endpoint honors (Section 2) and the business workflows that tie the entities together (Section 3), followed by the endpoint and error catalogues (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules and contracts that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a role string the system does not recognize, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `PatientUser`, `ProviderStaff`, `PayerAnalyst`, and `Admin`.

- When `X-User-Role` is `PatientUser`, `X-User-ID` is the `id` of the acting `Patient`. Ownership checks on any resource that references a `Patient` compare the resource's patient foreign key to `X-User-ID`: a `PatientUser` may only accept, dispute, cancel, or read estimates, disputes, and appointments that belong to the patient whose `id` equals `X-User-ID`. A `PatientUser` mutation that targets a resource tied to a different patient is rejected with `ERR_UNAUTHORIZED`.
- When `X-User-Role` is `ProviderStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`; provider-side staff act across all patients.
- When `X-User-Role` is `PayerAnalyst`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`.
- When `X-User-Role` is `Admin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is not compared to any entity's `id`.

Section 4 lists the authorized role(s) for each endpoint. Read (GET) operations are broadly available to all four roles, subject to the `PatientUser` ownership scoping described above; write operations are restricted to the roles named in Section 4.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order. The `meta` object of every list response includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

Every persisted resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities in this system are mutable and therefore also carry an `updated_at` timestamp (ISO 8601 UTC, three fractional digits) and an integer `version`. The `version` begins at 1 on creation and increments by exactly 1 on every mutation that changes the resource; `updated_at` is refreshed to the logical-clock instant on every such mutation. When a computed field such as an accumulator or an estimate money field changes as a side effect of another operation, that too is a mutation of the owning resource and advances its `version` and `updated_at`.

Timestamps that the system stamps itself — `created_at`, `updated_at`, `issued_at`, `settled_at`, and the clock's reported `now` — are read from the logical clock described in Section 3.9, never from wall-clock time.

### 2.5. Monetary Amounts, Cents, and Rounding

All monetary quantities in this system are integers denominated in whole cents — gross charges, negotiated flat amounts, deductibles, out-of-pocket maximums, copays, and every computed estimate figure. Wherever a computation multiplies a cents amount by a fraction (a percent-of-charge rate, a coinsurance rate, or the self-pay discount), the product is rounded to a whole number of cents using the round-half-up convention: a fractional cent of exactly one half rounds up to the next whole cent. Rate and fraction inputs themselves — `percent_of_charge` and `coinsurance_rate` — are stored at the precision supplied and are not rounded.

One rounding rule is load-bearing and is stated here so it is not missed later: per-line coinsurance is rounded to whole cents **for each line individually, and the already-rounded line values are then summed** to produce the estimate-level coinsurance. The system never sums unrounded line coinsurance and rounds once at the end. Deductible amounts are exact integer cents and involve no rounding.

### 2.6. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency control against a parent resource whose accumulated state the client must have observed before writing.

- Creating an `Estimate` requires the field `expected_patient_version`, carrying the `version` of the target `Patient` that the client last read. If `expected_patient_version` does not equal the patient's current `version`, the create is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412). Because an estimate is meaningful only against the benefit-accumulation baseline the client last saw, a stale value means the patient's accumulators moved — another estimate was attached, an accumulation was posted, or a prior estimate settled — since the client read. Each successful create itself advances the patient's `version`, so a second create replaying a pre-create version is deterministically rejected.
- Ingesting a `NegotiatedRate` requires the field `expected_contract_version`, carrying the `version` of the target `PayerContract` the client last read. If `expected_contract_version` does not equal the contract's current `version`, the ingest is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412). A newer rate for the same contract-and-procedure pair supersedes the prior one, so a stale contract version signals that another ingest batch already advanced the contract.

No other endpoint takes a version field, and endpoints not named here perform no version check.

### 2.7. Referential Integrity and Existence Ordering

Every request that references other resources — through a path identifier or through a foreign-key field in the body — is validated for existence before any business rule runs, and the references are checked left-to-right in the order they appear (path identifier first, then body foreign keys in declaration order). The first identifier that does not resolve to an existing resource stops the request with the not-found error specific to that resource type: `ERR_PROCEDURE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_RATE_NOT_FOUND`, `ERR_BENEFIT_PLAN_NOT_FOUND`, `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_ROOM_NOT_FOUND`, `ERR_ESTIMATE_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_PRIOR_AUTH_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_DISPUTE_NOT_FOUND`, each returned with HTTP 404.

The overall precedence of checks on any write is: authentication first (`ERR_UNAUTHENTICATED`), then authorization including patient ownership (`ERR_UNAUTHORIZED`), then body well-formedness (`ERR_VALIDATION`), then existence of referenced resources (the 404 family above), then the stale-version guard where applicable (`ERR_STALE_PATIENT_VERSION` / `ERR_STALE_CONTRACT_VERSION`), then the target resource's own-state precondition (`ERR_INVALID_STATE`), then cross-entity state and the remaining domain rules. Body well-formedness covers presence of required fields, correct types, legal enum values, and honored numeric ranges; a violation yields `ERR_VALIDATION` (HTTP 422). In particular, a `NegotiatedRate` whose `rate_type` is `FLAT` must supply `flat_amount_cents`, and one whose `rate_type` is `PERCENT` must supply `percent_of_charge`; the wrong pairing is an `ERR_VALIDATION`.

### 2.8. Benefit Accumulators and Estimate Staleness Propagation

Each `Patient` carries two year-to-date accumulators, `deductible_met_cents` and `oop_met_cents`, both starting at 0. These accumulators are the moving baseline against which every estimate for that patient is priced, and they change through exactly three channels: an estimate settling (advancing both), an externally-sourced accumulation adjustment (advancing or moving both), and the voiding of a previously settled estimate (reversing both). Every one of these mutations advances the patient's `version`.

Because a priced estimate is a snapshot taken against a particular accumulator baseline, any change to a patient's accumulators after an estimate was priced makes that estimate's projected numbers stale. Whenever the accumulators move, every estimate belonging to that patient that is not in a terminal state — that is, every estimate not in `VOID` — other than the one that caused the change has its `recompute_required` flag set to true, marking its projection as needing a fresh pricing run. This flag is descriptive: it flags staleness for the reader and does not by itself re-price the estimate.

### 2.9. Scheduling Resource Availability

An appointment reserves two physical resources at once — a `Provider` and a `Room` — and the two resources use deliberately different collision models. An appointment's requested window runs from `scheduled_start` (inclusive) to `scheduled_end` (exclusive).

A provider is treated as needing cleanup and turnaround between patients, so provider bookings are **buffered by 15 minutes**. A provider is unavailable for a requested window if the provider already has an appointment in `SCHEDULED` or `COMPLETED` status such that fewer than 15 minutes of clearance separate the two windows — equivalently, if the requested window overlaps any existing such window after each existing window is extended by 15 minutes on both ends. A conflict yields `ERR_PROVIDER_UNAVAILABLE`. A room, by contrast, uses **strict half-open** semantics with no buffer: a room is unavailable only if some existing `SCHEDULED` or `COMPLETED` appointment for that room has a half-open interval that actually overlaps the requested half-open interval; two bookings that merely touch end-to-start (one ending exactly when the next begins) do not conflict. A room conflict yields `ERR_ROOM_UNAVAILABLE`. Cancelling an appointment frees both the provider and the room intervals it held, so those windows become available to later bookings.

## 3. Business Logic & Workflows

### 3.1. The Chargemaster and Shoppable-Service Comparison

`ProviderStaff` seeds the catalog by creating a `Procedure`, the record of a shoppable service. Each procedure declares a `code_system` — one of `CPT`, `HCPCS`, or `DRG` — together with the `code` string itself (for example, an imaging CPT code), a human-readable `description`, and a `setting` of either `INPATIENT` or `OUTPATIENT`. Two booleans govern how the procedure behaves downstream: `is_shoppable`, which defaults to true and controls whether the procedure surfaces in shoppable comparison, and `requires_prior_auth`, which defaults to false and, when true, forces an approved authorization before an appointment covering the procedure can be scheduled. The chargemaster list price is `gross_charge_cents`, a non-negative integer that is the basis both for percent-of-charge negotiated rates and for self-pay pricing. Procedures can be fetched individually and listed with optional filters on `code_system` and `is_shoppable`.

The shoppable comparison capability answers, for one procedure, "what does this cost across payers?" It gathers every non-superseded `NegotiatedRate` for the procedure whose `PayerContract` is in `ACTIVE` status, optionally narrowed by a `payer_type` filter when the caller supplies one, and computes each candidate's allowed amount using the same flat-or-percent rule described in Section 3.4. The count of qualifying rates is returned as `sample_count`. When `sample_count` is zero, both `median_allowed_cents` and `min_allowed_cents` are null. Otherwise the candidate allowed amounts are sorted ascending: `min_allowed_cents` is the smallest, and `median_allowed_cents` is the middle value when the count is odd, or the mean of the two middle values rounded half up to whole cents when the count is even. Alongside these, the response reports the procedure's own `gross_charge_cents` and a `self_pay_price_cents` equal to the gross charge multiplied by 0.65 — that is, the gross charge less a 35% self-pay discount — rounded half up to whole cents. The response also echoes the `procedure_id`. The `MEDIAN` figure reflects the central negotiated allowed across contracts while the `MIN` figure reflects the lowest; the two diverge whenever the negotiated rates are not all equal.

### 3.2. Payer Contracts and Negotiated-Rate Ingestion

A `PayerAnalyst` records a `PayerContract` capturing the `payer_name`, the `payer_type` (`COMMERCIAL`, `MEDICARE`, or `MEDICAID`), the `methodology` by which rates are expressed (`FEE_SCHEDULE`, `PERCENT_OF_CHARGE`, or `CASE_RATE`), and the `effective_date` and `expiration_date` of the agreement. A contract is born in `DRAFT` `status`. Activating the contract advances it from `DRAFT` to `ACTIVE` and increments the contract's `version` by 1; activation is permitted only while the contract is in `DRAFT`, and an attempt to activate a contract that is not in `DRAFT` is rejected with `ERR_INVALID_STATE`. `ACTIVE` is a required precondition before any insured estimate that references the contract may be issued.

Negotiated rates hang off a contract. Ingesting a `NegotiatedRate` records the `contract_id` and `procedure_id` it links, a `rate_type` of `FLAT` or `PERCENT`, and the amount in whichever form the type demands: a `FLAT` rate carries a non-negative `flat_amount_cents`, while a `PERCENT` rate carries `percent_of_charge`, a fraction strictly greater than 0 and at most 1. The ingest request also carries `expected_contract_version` for the stale-contract guard described in Section 2.6. Ingesting a rate for a contract-and-procedure pair that already has a live rate supersedes the old one: the prior non-superseded rate for that same `contract_id` and `procedure_id` has its `superseded` flag set to true, and the contract's `version` is incremented by 1. Superseded rates are excluded from pricing and from shoppable comparison. Negotiated rates can be fetched individually and listed with optional filters on `contract_id`, `procedure_id`, and `superseded`.

### 3.3. Benefit Plans, Patients, and External Accumulation Adjustments

A `PayerAnalyst` defines a `BenefitPlan` describing a patient's coverage for a `plan_year`: the `payer_name` administering it, the `individual_deductible_cents`, the `individual_oop_max_cents` (which may not be below the deductible), the `coinsurance_rate` (a fraction between 0 and 1 inclusive, the patient's share of allowed amounts after the deductible is met), the flat `copay_cents` applied once per estimate, and the `in_network` flag, which defaults to true.

`ProviderStaff` registers a `Patient` against a plan, supplying the patient's `name`, `member_id`, and the `benefit_plan_id` of the plan that covers them. A newly registered patient's `deductible_met_cents` and `oop_met_cents` both start at 0. Patients can be fetched — the fetched record includes the live accumulators — and listed with an optional `benefit_plan_id` filter.

Benefit accumulation does not only happen inside this system; a claim adjudicated elsewhere (say, from an explanation of benefits) can move a patient's year-to-date totals. A `PayerAnalyst` posts such a movement as an accumulation adjustment, supplying `deductible_delta_cents`, `oop_delta_cents`, and a `source` label describing where the adjustment came from. The adjustment adds `deductible_delta_cents` to the patient's `deductible_met_cents` and `oop_delta_cents` to the patient's `oop_met_cents`, increments the patient's `version` by 1, and — per Section 2.8 — sets `recompute_required` to true on every one of that patient's estimates that is not in `VOID`.

### 3.4. Assembling and Pricing a Good-Faith Estimate

An estimate is built up in `DRAFT`, then priced and frozen at issue. Either a `PatientUser` (acting on their own patient) or `ProviderStaff` creates an `Estimate` by supplying the `patient_id`, the `estimate_type`, and — for the stale-patient guard of Section 2.6 — `expected_patient_version`. The `estimate_type` is either `GFE_INSURED`, which must carry a `contract_id` naming the payer contract to price against, or `GFE_SELFPAY`, which must omit `contract_id` entirely. Supplying a `contract_id` on a self-pay estimate, or omitting it on an insured estimate, is rejected with `ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH`. Creating the estimate attaches a fresh `DRAFT` estimate to the patient, snapshots the accumulation baseline, becomes the patient's current good-faith estimate superseding any prior non-terminal estimate they held, and increments the patient's `version` by 1. Every estimate carries computed money fields that remain null until issue: `allowed_amount_cents`, `deductible_applied_cents`, `coinsurance_cents`, `copay_cents`, `patient_responsibility_cents`, `plan_paid_cents`, and a `responsibility_basis` that records which pricing variant produced the current numbers.

Line items are added to a `DRAFT` estimate one at a time, each naming a `procedure_id`. The system assigns each new `EstimateLine` a `line_number` sequentially starting at 1; this ordering is authoritative — it fixes the order in which the deductible is consumed and the order in which line rounding happens, and it is never derived from insertion `id`. Each line also carries the `estimate_id` it belongs to and, once priced, its own `allowed_amount_cents`, `deductible_applied_cents`, `coinsurance_cents`, `line_patient_responsibility_cents`, and the version-pinning references `pinned_rate_id` and `pinned_rate_version`.

Issuing a draft estimate is the pricing event, and it may proceed only when the estimate is in `DRAFT`, has at least one line, and — for an insured estimate — references a contract in `ACTIVE` status with a live negotiated rate for every line's procedure. Issuing an estimate with no lines is rejected with `ERR_ESTIMATE_NO_LINES`; issuing an insured estimate whose contract is not `ACTIVE` is rejected with `ERR_CONTRACT_NOT_ACTIVE`; and issuing an insured estimate any of whose line procedures lacks a non-superseded negotiated rate under the contract is rejected with `ERR_NO_NEGOTIATED_RATE`. A successful issue advances the estimate from `DRAFT` to `ISSUED`, records `issued_at`, sets `responsibility_basis` to `ESTIMATE`, and increments the estimate's `version` by 1.

Pricing at issue runs in three stages. **First, each line's allowed amount.** For a `GFE_SELFPAY` estimate a line's `allowed_amount_cents` is the procedure's `gross_charge_cents` multiplied by 0.65 (the gross charge less the 35% self-pay discount), rounded half up to whole cents. For a `GFE_INSURED` estimate the single non-superseded negotiated rate for the estimate's `contract_id` and the line's `procedure_id` is pinned to the line — its identifier into `pinned_rate_id` and its `version` into `pinned_rate_version` — and the allowed amount is that rate's `flat_amount_cents` when the rate is `FLAT`, or the procedure's `gross_charge_cents` multiplied by the rate's `percent_of_charge` rounded half up to whole cents when the rate is `PERCENT`. Self-pay lines pin no rate.

**Second, the deductible-and-coinsurance aggregation across lines.** Lines are processed in ascending `line_number` order. A running deductible-met figure begins at the patient's `deductible_met_cents` as of the pricing clock. For each line in turn, the remaining deductible is the plan's `individual_deductible_cents` minus that running figure, floored at 0; the line's `deductible_applied_cents` is the smaller of the line's `allowed_amount_cents` and that remaining deductible; the line's `coinsurance_cents` is the plan's `coinsurance_rate` applied to the line's allowed amount less its deductible portion, rounded half up to whole cents (rounded per line, as stressed in Section 2.5); and the line's `line_patient_responsibility_cents` is its `deductible_applied_cents` plus its `coinsurance_cents`. The running deductible-met figure then grows by the line's `deductible_applied_cents` before the next line is processed. The estimate's `deductible_applied_cents` is the sum of the per-line deductible portions, and the estimate's `coinsurance_cents` is the sum of the already-rounded per-line coinsurance values. The estimate's `allowed_amount_cents` is the sum of the line allowed amounts.

**Third, the patient-responsibility roll-up.** For a `GFE_SELFPAY` estimate the patient owes the entire allowed amount: `patient_responsibility_cents` equals `allowed_amount_cents`, while `copay_cents` and `plan_paid_cents` are both 0. For a `GFE_INSURED` estimate the `copay_cents` is the plan's `copay_cents` (applied once for the whole estimate); a pre-cap responsibility is formed as the estimate's `deductible_applied_cents` plus its `coinsurance_cents` plus that copay; the remaining out-of-pocket room is the plan's `individual_oop_max_cents` minus the patient's `oop_met_cents` as of the pricing clock, floored at 0; and `patient_responsibility_cents` is the smaller of the pre-cap responsibility and that remaining room. The plan's share, `plan_paid_cents`, is the estimate's `allowed_amount_cents` minus `patient_responsibility_cents`. This roll-up runs in two variants that differ only in which clock supplies the patient's accumulators: the `ESTIMATE` variant at issue uses the accumulators as of issue time, and the `FINAL` variant at settlement uses the accumulators as of settlement time. Because intervening claims or adjustments may have moved the accumulators between those moments, the `FINAL` figure can differ from the `ESTIMATE` figure even for identical allowed amounts.

### 3.5. Patient Review: Acceptance and the Dispute Loop

Once an estimate is `ISSUED`, the patient it belongs to decides what to do with it. A `PatientUser` who owns the estimate's patient may accept it, advancing the estimate from `ISSUED` to `ACCEPTED` and incrementing its `version` by 1; acceptance is the precondition for scheduling care against the estimate. A `PatientUser` who does not own the patient is refused with `ERR_UNAUTHORIZED`, and accepting anything not currently `ISSUED` is refused with `ERR_INVALID_STATE`.

Alternatively, the owning `PatientUser` may dispute the issued estimate by filing a `Dispute`, supplying the `estimate_id`, a free-text `reason`, and the `disputed_amount_cents` they contest (a non-negative integer). Filing the dispute creates it in `OPEN` status and moves the linked estimate from `ISSUED` to `DISPUTED`. This opens a revision loop: `ProviderStaff` first takes the open dispute under review, advancing it from `OPEN` to `UNDER_REVIEW` and incrementing its `version` by 1, and then resolves it. Resolution requires a `resolution` outcome and returns the estimate from `DISPUTED` back to `ISSUED` in both cases, which is what makes the loop cyclic. Assigning a dispute that is not `OPEN`, or resolving one that is not `UNDER_REVIEW`, is refused with `ERR_INVALID_STATE`.

The two resolution outcomes are treated with equal weight. When the outcome upholds the original estimate, the dispute settles in `RESOLVED_UPHELD`, an optional `resolution_note` may be recorded, and the estimate's numbers are left exactly as issued. When the outcome adjusts the estimate, the dispute settles in `RESOLVED_ADJUSTED` and the reviewer must supply `adjusted_patient_responsibility_cents`, which becomes the estimate's new `patient_responsibility_cents`; the estimate's `plan_paid_cents` is then recomputed as its `allowed_amount_cents` minus that adjusted value, so the allowed amount is conserved and only the patient/plan split moves. An optional `resolution_note` may accompany an adjustment as well. The adjusted value must lie between 0 and the estimate's current `patient_responsibility_cents` inclusive; an adjustment outside that range, or a resolution declaring the adjusted outcome without supplying `adjusted_patient_responsibility_cents`, is rejected with `ERR_INVALID_ADJUSTMENT`.

### 3.6. Prior Authorization

Some procedures cannot be delivered until the payer signs off. When a procedure's `requires_prior_auth` flag is true, an appointment covering it needs an approved authorization on file. `ProviderStaff` requests a `PriorAuthorization` against an estimate, supplying the `estimate_id`, the `procedure_code` the request covers, and the `requested_units` (at least 1). The authorization starts in `REQUESTED`. A `PayerAnalyst` then either approves or denies it. Approval advances it from `REQUESTED` to `APPROVED`, sets the payer-issued `auth_number`, the `approved_units` granted, and the `expiration_date` after which the authorization is no longer valid, and increments its `version` by 1. Denial advances it from `REQUESTED` to `DENIED`, records a `denial_reason`, and increments its `version` by 1. Approving or denying an authorization that is not in `REQUESTED` is refused with `ERR_INVALID_STATE`. An approved authorization is later consumed automatically when the linked appointment completes, advancing it from `APPROVED` to `CONSUMED`.

### 3.7. Scheduling and Completing Care

The schedulable resources are set up first. `ProviderStaff` creates a `Provider` — a rendering clinician identified by `name`, `npi` (National Provider Identifier), and clinical `specialty` — and a `Room`, a physical room or equipment slot identified by `name` and a `room_type` of `EXAM`, `PROCEDURE`, or `IMAGING`. Both are schedulable resources whose availability is governed by Section 2.9.

Scheduling turns an accepted estimate into a booked visit. `ProviderStaff` schedules an `Appointment` by naming the `patient_id`, the `estimate_id`, the `provider_id`, the `room_id`, and the requested `scheduled_start` and `scheduled_end`. The estimate being scheduled must be in `ACCEPTED` status; scheduling against an estimate in any other state is refused with `ERR_ESTIMATE_NOT_ACCEPTED`. If any procedure on the estimate's lines has `requires_prior_auth` set, the request must also carry a `prior_auth_id` whose `PriorAuthorization` is in `APPROVED` status; a missing or non-approved authorization is refused with `ERR_PRIOR_AUTH_NOT_APPROVED`, and an authorization that is approved but whose `expiration_date` falls before the appointment's start is refused with `ERR_PRIOR_AUTH_EXPIRED`. When no line procedure requires authorization, `prior_auth_id` may be omitted. The provider-buffer and room-half-open availability checks of Section 2.9 then apply, yielding `ERR_PROVIDER_UNAVAILABLE` or `ERR_ROOM_UNAVAILABLE` on a conflict. A successful schedule creates the appointment in `SCHEDULED`. Appointments can be fetched and listed with optional filters on `patient_id`, `estimate_id`, `provider_id`, `room_id`, `prior_auth_id`, and `status`.

A scheduled appointment ends one of two ways. `ProviderStaff` may cancel it — a `PatientUser` owning the appointment's patient may also cancel — moving it from `SCHEDULED` to `CANCELLED` and freeing the held provider and room windows. Or `ProviderStaff` may complete it, moving it from `SCHEDULED` to `COMPLETED`, which fires the settlement cascade. Completion drives three coordinated effects. First, the linked estimate, which was `ACCEPTED`, settles to `SETTLED`: the deductible-and-coinsurance aggregation and the patient-responsibility roll-up of Section 3.4 are re-run in the `FINAL` variant against the patient's accumulators as of settlement — refreshing the estimate's `deductible_applied_cents`, `coinsurance_cents`, and `patient_responsibility_cents`, setting `responsibility_basis` to `FINAL`, and recording `settled_at`. Second, the patient's accumulators advance: `deductible_met_cents` grows by this estimate's settled `deductible_applied_cents`, `oop_met_cents` grows by its settled `patient_responsibility_cents`, and the patient's `version` increments by 1; as a consequence, every other non-`VOID` estimate of the same patient has its `recompute_required` set to true, per Section 2.8. Third, the linked approved authorization, if any, is consumed from `APPROVED` to `CONSUMED`.

### 3.8. Voiding an Estimate and Reversal

`ProviderStaff` may void an estimate that is in `ISSUED`, `ACCEPTED`, or `SETTLED`, moving it to the terminal `VOID` state and incrementing its `version` by 1; voiding an estimate in any other state is refused with `ERR_INVALID_STATE`. Voiding an estimate that had already settled must undo exactly the benefit accumulation that settlement applied: the patient's `deductible_met_cents` is reduced by that estimate's `deductible_applied_cents`, the patient's `oop_met_cents` is reduced by that estimate's `patient_responsibility_cents`, and the patient's `version` is incremented by 1. Voiding an estimate that had not yet settled makes no accumulator change. Because voiding is what removes an estimate from the patient's active set, a voided estimate is never a candidate for the staleness cascade of Section 2.8.

### 3.9. Transparency Reporting and the Logical Clock

An `Admin` can pull an aggregate price-transparency report, optionally narrowed by `code_system` and `payer_type`. The report returns `procedure_count`, `rate_count`, an `avg_allowed_cents_by_code_system` object giving the average negotiated allowed amount grouped by code system, and `issued_estimate_count`.

Because every settlement, expiration, and timestamp in this system depends on time, an `Admin` also controls a logical clock that supplies the system's notion of "now." The clock starts at `2026-05-01T00:00:00Z` on server startup; before any call it reads exactly that default and never falls back to wall-clock time. An administrative test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the new `now`. All server-stamped timestamps — including `issued_at` and `settled_at` — are read from this clock.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including state transitions, activation, approval, resolution, and adjustment postings — return `200 OK`. All list and fetch operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/procedures` | Create a shoppable procedure (chargemaster entry) | ProviderStaff |
| GET | `/procedures/{id}` | Fetch a procedure | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/procedures` | List procedures | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/procedures/{id}/comparison` | Shoppable-service comparison for a procedure | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/payer-contracts` | Create a payer contract (DRAFT) | PayerAnalyst |
| GET | `/payer-contracts/{id}` | Fetch a payer contract | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/payer-contracts/{id}/activate` | Activate a DRAFT contract | PayerAnalyst |
| POST | `/negotiated-rates` | Ingest a negotiated rate (supersedes prior; OCC on contract) | PayerAnalyst |
| GET | `/negotiated-rates/{id}` | Fetch a negotiated rate | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/negotiated-rates` | List negotiated rates | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/benefit-plans` | Create a benefit plan | PayerAnalyst |
| GET | `/benefit-plans/{id}` | Fetch a benefit plan | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/patients` | Register a patient against a benefit plan | ProviderStaff |
| GET | `/patients/{id}` | Fetch a patient including accumulators | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/patients` | List patients | ProviderStaff, PayerAnalyst, Admin |
| POST | `/patients/{id}/accumulation-adjustments` | Apply an external benefit accumulation | PayerAnalyst |
| POST | `/providers` | Create a rendering provider | ProviderStaff |
| GET | `/providers/{id}` | Fetch a provider | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/rooms` | Create a room/equipment resource | ProviderStaff |
| GET | `/rooms/{id}` | Fetch a room | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/estimates` | Create a Good-Faith-Estimate (DRAFT; OCC on patient) | PatientUser, ProviderStaff |
| GET | `/estimates/{id}` | Fetch an estimate | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/estimates` | List estimates | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/estimates/{id}/lines` | Add a line to a DRAFT estimate | PatientUser, ProviderStaff |
| POST | `/estimates/{id}/issue` | Price and issue a DRAFT estimate | ProviderStaff |
| POST | `/estimates/{id}/accept` | Patient accepts an ISSUED estimate | PatientUser |
| POST | `/estimates/{id}/void` | Void an estimate (reverses accumulation if SETTLED) | ProviderStaff |
| GET | `/estimate-lines/{id}` | Fetch an estimate line | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/estimate-lines` | List estimate lines | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/prior-authorizations` | Request prior authorization | ProviderStaff |
| GET | `/prior-authorizations/{id}` | Fetch a prior authorization | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/prior-authorizations` | List prior authorizations | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/prior-authorizations/{id}/approve` | Approve a prior authorization | PayerAnalyst |
| POST | `/prior-authorizations/{id}/deny` | Deny a prior authorization | PayerAnalyst |
| POST | `/appointments` | Schedule an appointment for an ACCEPTED estimate | ProviderStaff |
| GET | `/appointments/{id}` | Fetch an appointment | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/appointments` | List appointments | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/appointments/{id}/complete` | Complete an appointment (cascades settlement) | ProviderStaff |
| POST | `/appointments/{id}/cancel` | Cancel a scheduled appointment | ProviderStaff, PatientUser |
| POST | `/disputes` | File a dispute against an ISSUED estimate | PatientUser |
| GET | `/disputes/{id}` | Fetch a dispute | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| GET | `/disputes` | List disputes | PatientUser, ProviderStaff, PayerAnalyst, Admin |
| POST | `/disputes/{id}/assign` | Take an OPEN dispute under review | ProviderStaff |
| POST | `/disputes/{id}/resolve` | Resolve a dispute (uphold or adjust) | ProviderStaff |
| GET | `/reports/price-transparency` | Aggregate transparency report | Admin |
| POST | `/_clock/set_current_utc` | Set the logical clock | Admin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_PROCEDURE_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_RATE_NOT_FOUND` | 404 |
| `ERR_BENEFIT_PLAN_NOT_FOUND` | 404 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_ROOM_NOT_FOUND` | 404 |
| `ERR_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_LINE_NOT_FOUND` | 404 |
| `ERR_PRIOR_AUTH_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 |
| `ERR_ESTIMATE_NOT_ACCEPTED` | 409 |
| `ERR_ESTIMATE_NO_LINES` | 422 |
| `ERR_ESTIMATE_TYPE_CONTRACT_MISMATCH` | 422 |
| `ERR_INVALID_ADJUSTMENT` | 422 |
| `ERR_PRIOR_AUTH_NOT_APPROVED` | 409 |
| `ERR_PRIOR_AUTH_EXPIRED` | 409 |
| `ERR_NO_NEGOTIATED_RATE` | 422 |
| `ERR_PROVIDER_UNAVAILABLE` | 409 |
| `ERR_ROOM_UNAVAILABLE` | 409 |

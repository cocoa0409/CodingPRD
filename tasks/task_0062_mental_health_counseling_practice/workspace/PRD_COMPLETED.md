# Mental Health Counseling Practice API — Product Requirements Document

## 1. Introduction

A behavioral-health group practice operates at the intersection of three rarely-reconciled disciplines: clinical licensure governance, revenue-cycle billing, and crisis safety management. This API unifies them into a single system of record. Clinicians progress through a regulated credentialing ladder — from an associate working under supervision toward fully independent practice — and every billable session they render feeds both their supervised-hour accruals and the practice's claims pipeline. At the same time, the platform must honor the hard realities of mental-health care: a patient assessed at high suicide risk cannot be quietly billed and forgotten; a session delivered by telehealth into another state is only lawful if the clinician is licensed there for that modality.

The system is designed for four distinct operators who share the same data but hold very different authority. A credentialing-and-compliance director governs licenses, promotions, and supervision review; clinicians render and document their own sessions; billers drive the insurance claim lifecycle and write-offs; and front-desk staff intake patients and schedule appointments. Because no single operator is a superset of the others, the API enforces both role-based authorization and, for clinicians, resource ownership. The remainder of this document specifies the global contracts that every endpoint obeys (Section 2), the business workflows that tie credentialing, scheduling, documentation, billing, and crisis response together (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes exactly four roles, spelled precisely as follows: `ClinicalDirector`, `Therapist`, `Biller`, and `FrontDesk`. A request missing either header is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted to invoke the targeted endpoint is rejected with `ERR_UNAUTHORIZED`.

The four roles relate to persisted identity differently. When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist`; ownership checks on any resource that references a `Therapist` compare the resource's clinician foreign key to `X-User-ID`. Concretely, when a clinician acts to render or complete an appointment, or to sign or co-sign a clinical note, `X-User-ID` must equal the rendering clinician of the linked appointment (or, for co-signing, that clinician's supervisor), failing which the request is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ClinicalDirector`, `Biller`, or `FrontDesk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the count of items to skip from the front of the result set and defaults to 0.

Unless a specific workflow states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Mutation Semantics

Every persisted resource in this system — therapists, state licenses, supervision logs, patients, insurance policies, payer contracts, appointments, clinical notes, claims, crisis assessments, and safety plans — carries a system-managed `id` that is a UUID with no type prefix, and a `created_at` timestamp formatted as an ISO 8601 UTC instant with three fractional digits. All of these resources additionally carry an `updated_at` timestamp, refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one with each modification. There are no immutable-after-creation resources in this domain; every entity participates in the standard `updated_at` and `version` discipline.

When the server recomputes a derived field — for example, refreshing a therapist's accrued hours after a session is rendered or completed, or adjusting an insurance policy's met-deductible total after a claim settles — that recomputation is itself a mutation of the affected resource and therefore refreshes its `updated_at` and increments its `version`. All such effects settle atomically within the single request that triggers them; the system never leaves a cascade half-applied.

### 2.5. Nested Reference Resolution

Resources in this domain are peers linked by foreign keys rather than deeply nested URL paths; child resources are discovered through filtered list endpoints (for example, listing supervision logs by `therapist_id`, or claims by `appointment_id`). For any request, the server validates referenced identifiers left-to-right: the path identifier first, then each required foreign-key reference in the request body. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.6. Monetary Values, Hours, and Rounding Precision

Monetary amounts in this system are stored and exchanged as integer cents — copays, coinsurance-derived amounts, deductibles, contracted rates, billed charges, and patient responsibility are all whole-cent integers. Wherever a calculation produces a fractional cent (for instance, multiplying a standard rate by a sliding-fee multiplier, or a charge by a coinsurance fraction), the result is rounded to the nearest whole cent using the round-half-up convention.

Two derived quantities are expressed not in cents but with two-decimal precision, also rounded half up: a patient's federal-poverty-line percentage, and the supervised-hour totals accrued by a clinician. A crisis risk score is likewise a number carried to two decimal places, rounded half up. Wherever this document states an hour threshold, remember that session lengths are recorded in minutes and an hour is sixty of those minutes.

### 2.7. Credentialing and Supervision Governance

The right to render billable care follows a strict ladder. A clinician's `credential_status` is one of `ASSOCIATE`, `SUPERVISED_PRACTICE`, `INDEPENDENT`, or `SUSPENDED`, and the companion boolean `requires_supervision` is true while the clinician is `ASSOCIATE` or `SUPERVISED_PRACTICE` and false once `INDEPENDENT`. A clinician who requires supervision may only have their notes finalized when an independent supervisor has co-signed them. The supervisory relationship is expressed by a clinician's optional `supervisor_id`, which, when set, must point to a clinician whose `credential_status` is `INDEPENDENT`. A clinician also records an optional informational `home_state_code` — a USPS two-letter code, uppercase when provided — which is descriptive only and never gates any operation; licensure is governed entirely by state-license records.

### 2.8. Licensure and Telehealth Authorization

Each state license a clinician holds carries a `status` of `ACTIVE`, `EXPIRED`, or `REVOKED`, an `expires_on` instant, and a `telehealth_authorized` flag indicating whether that jurisdiction's license permits telehealth delivery to patients physically located in that state. A license is considered to have lapsed to `EXPIRED` once the server's current UTC clock reaches or passes its `expires_on` instant; this lapse is evaluated whenever a license-gated operation reads the license, so an expired license silently stops satisfying licensure preconditions for new sessions. A director may also explicitly revoke an active license, moving it to `REVOKED`, after which it likewise no longer satisfies licensure preconditions. Because the practice serves patients across state lines, the system exposes a director-only test-driving capability that sets the server's current UTC clock to a supplied `to_iso8601` instant; license expiry and session-time gates are all evaluated against that clock.

### 2.9. Optimistic Concurrency Control

Certain high-stakes mutations are guarded by optimistic concurrency control to prevent a client from acting on a version of a record it has not actually observed. The guarded operations are: opening an insurance claim, and each claim-lifecycle transition (adjudicate, deny, resubmit, void), and the two therapist-credential transitions (promote and suspend).

For a claim-lifecycle transition, the request must carry `expected_claim_version` matching the target claim's current `version`; if another writer has advanced that claim's version since the client last read it, the transition is rejected with `ERR_STALE_VERSION` (HTTP 412). For opening a claim, the request must carry `expected_appointment_version` matching the target appointment's current `version`, again rejected with `ERR_STALE_VERSION` (HTTP 412) on mismatch. For a therapist promotion or suspension, the request must carry `expected_therapist_version` matching that therapist's current `version`, rejected the same way on mismatch. Each successful guarded write increments the parent record's `version` by one. Endpoints not in this guarded set take no version field.

### 2.10. Sliding Fee Scale and Self-Pay Pricing

The practice offers income-based discounts to self-pay patients. On patient registration, and again whenever a patient's financials are updated, the system computes the patient's federal-poverty-line percentage and the resulting `sliding_fee_multiplier`. The poverty line for a household is the base figure of 15,060 dollars plus 5,380 dollars for each household member beyond the first — that is, the base plus the per-additional-person amount multiplied by one less than the household size. The patient's `fpl_percent` is their annual household income divided by that poverty line, multiplied by 100, rounded half up to two decimal places.

The multiplier is then assigned by band, where each band's upper boundary is inclusive: a percentage at or below 150 yields a multiplier of 0.20; above 150 and at or below 200 yields 0.40; above 200 and at or below 250 yields 0.60; above 250 and at or below 300 yields 0.80; anything above 300 yields 1.00 (no discount). This multiplier scales the standard procedure rate when a self-pay session is rendered, as detailed in Section 3.

### 2.11. Insurance Allowed-Amount and Cost-Share Waterfall

When an insurance claim is adjudicated, patient and payer responsibility are computed by a deductible-first waterfall whose first step depends on the payer's network status. The standard rate for the session's procedure code is the billed charge: 22,000 cents for code `90791` and 15,000 cents for code `90834`. If the governing payer contract is in-network, the allowed amount is the smaller of that billed charge and the contract's contracted rate for the same code; if the payer is out-of-network, the allowed amount equals the full billed charge with no contracted cap.

From the allowed amount, the deductible is consumed first: the deductible applied is the smaller of the allowed amount and the policy's remaining deductible, where remaining deductible is the policy's total deductible minus the cents already met, floored at zero. The amount remaining after the deductible is then subject to cost sharing. Under a copay model, the cost share is the smaller of the fixed copay and that post-deductible remainder. Under a coinsurance model, the cost share is the post-deductible remainder multiplied by the coinsurance fraction, rounded half up to the nearest cent. The patient's total responsibility is the deductible applied plus the cost share, and the payer's payment is the allowed amount minus that patient responsibility.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clinicians and Their Licenses

A compliance director registers a clinician by supplying their `full_name`, an optional `home_state_code`, and an optional `supervisor_id`. When a `supervisor_id` is supplied, it is resolved at registration: a `supervisor_id` that does not reference any clinician is rejected with `ERR_NOT_FOUND`, and a `supervisor_id` that references a clinician whose `credential_status` is not `INDEPENDENT` is rejected with `ERR_INVALID_REQUEST`. Every new clinician begins life in `ASSOCIATE` standing and requiring supervision; the computed credential and hour fields — `credential_status`, `requires_supervision`, `verified_direct_hours`, `projected_direct_hours`, and `verified_supervision_hours` — are all managed by the system rather than supplied by the caller. Anyone in the practice may retrieve a clinician record or list clinicians, and the clinician list can be narrowed by `supervisor_id` to discover a given supervisor's supervisees.

Licensure is issued separately. A director issues a state license against a clinician by providing the `therapist_id`, the two-letter `state_code`, the board-issued `license_number`, the `expires_on` instant, and an optional `telehealth_authorized` flag that defaults to true. A new license is born `ACTIVE`. Licenses are retrievable individually and as a filtered list — by `therapist_id` or by `state_code` — so that a clinician's full jurisdictional footprint can be enumerated. A director may revoke an active license at any time, an action that drives its status to `REVOKED`.

### 3.2. Accruing and Reviewing Supervised Hours

Two distinct hour totals track a clinician's progress toward independence, and they are deliberately different. The **projected** direct hours sum the session length over all of this clinician's appointments in `SCHEDULED`, `RENDERED`, or `COMPLETED` status, dividing total minutes by sixty and rounding to two decimal places — a forward-looking caseload figure. The **verified** direct hours are stricter: they sum session length only over appointments that have reached `COMPLETED` and whose clinical note is `CO_SIGNED`, again as minutes over sixty rounded to two decimals. Projected hours are recomputed whenever a session is rendered; verified hours are recomputed whenever a session is completed.

Supervision itself is logged and reviewed. A clinician or director records a supervision session by submitting the supervisee's `therapist_id`, the supervising `supervisor_id`, the `hours` recorded (which must be greater than zero), and the `logged_on` instant; the log is born `SUBMITTED`. A director then reviews it: accepting a log is permitted only when the log is in `SUBMITTED` status (otherwise `ERR_INVALID_STATE`) and its `supervisor_id` references an `INDEPENDENT` clinician — a log whose supervisor is not `INDEPENDENT` is likewise rejected with `ERR_INVALID_STATE`, checked after the `SUBMITTED` precondition — and acceptance moves the log to `ACCEPTED` and recomputes the supervisee's `verified_supervision_hours` as the sum of the hours across that clinician's accepted logs, rounded to two decimals. Rejecting a log instead moves it to `REJECTED` with no further effect. Supervision logs are retrievable individually and as a list filtered by `therapist_id` or `supervisor_id`. Because the promotion thresholds described next are unreachable by rendering thousands of real sessions in a test, a director-only injection capability can directly set a clinician's `verified_direct_hours` and `verified_supervision_hours` to supplied totals.

### 3.3. Advancing and Suspending the Credential Ladder

Promotion advances a clinician one rung and is a director-only action requiring `expected_therapist_version` to match the clinician's current `version`. Moving from `ASSOCIATE` to `SUPERVISED_PRACTICE` requires verified direct hours of at least 1,500; the clinician remains in need of supervision, and the version increments by one. Notably, a supervisor is not required to promote — the supervisory link governs note co-signing while supervision is required, not the advancement itself, which also allows the practice's very first independent clinician to be bootstrapped without a pre-existing independent supervisor. Moving from `SUPERVISED_PRACTICE` to `INDEPENDENT` is the demanding step: it requires verified direct hours of at least 3,000, verified supervision hours of at least the verified direct hours divided by twenty, and at least one state license in `ACTIVE` status; on success the clinician no longer requires supervision and the version increments by one. A promotion whose hour, supervision-ratio, or license thresholds are unmet is rejected with `ERR_PROMOTION_NOT_ELIGIBLE`.

Suspension is the terminal credential event and may be applied from any of `ASSOCIATE`, `SUPERVISED_PRACTICE`, or `INDEPENDENT`. It is director-only and likewise requires `expected_therapist_version` to match. Suspending a clinician moves them to `SUSPENDED`, increments their version by one, and cascades a cancellation across all of that clinician's appointments currently in `SCHEDULED` status, driving each to `CANCELLED`. A request to promote or suspend a clinician from a state where that transition is not defined is rejected with `ERR_INVALID_STATE`.

### 3.4. Intake, Patient Financials, and Coverage

Front-desk staff or a director register a patient with their `full_name`, their `location_state_code` (the uppercase two-letter state where they are physically located during sessions, which governs cross-state telehealth checks), their `annual_household_income` in whole dollars (which must be zero or greater), and their `household_size` (which must be at least one). Registration immediately computes the patient's `fpl_percent` and `sliding_fee_multiplier` per the sliding-fee bands. A patient begins `ACTIVE` and their lifecycle status is one of `ACTIVE`, `ON_CLINICAL_HOLD`, or `DISCHARGED`. Updating a patient's financials — supplying a revised `annual_household_income` and `household_size` — recomputes the sliding-fee scale in place. Patients are retrievable individually and as a list optionally filtered by `status`.

Coverage is attached as an insurance policy. Creating a policy requires the `patient_id` it belongs to, the `contract_id` of the governing payer contract, and a `cost_share_model` of either `COPAY` or `COINSURANCE`; the request may also carry a `copay_cents` (used under the copay model, defaulting to 0 and never negative), a `coinsurance_rate` (a fraction between 0 and 1 inclusive, used under the coinsurance model, defaulting to 0), and a `deductible_total_cents` (defaulting to 0, never negative). A new policy's `deductible_met_cents` starts at 0 and only ever rises as claims settle against it, until any external reset. Policies are retrievable individually and as a list filtered by `patient_id` or `contract_id`. Payer contracts themselves are created with a `payer_name`, an `in_network` flag, and the two contracted allowed amounts `contracted_rate_90791_cents` and `contracted_rate_90834_cents` (each zero or greater); an out-of-network contract bills at the standard procedure rate with no allowed-amount cap. A contract is retrievable by id.

### 3.5. Scheduling Sessions and Avoiding Conflicts

An appointment is scheduled by front-desk, a clinician, or a director, supplying the rendering `therapist_id`, the `patient_id` seen, the `cpt_code` (`90791` or `90834`), the `modality` (`IN_PERSON` or `TELEHEALTH`), the `start_at` instant, the `duration_minutes`, the `payment_path` (`INSURANCE` or `SELF_PAY`), and an optional `insurance_policy_id`. New appointments are born `SCHEDULED`, and the appointment's status thereafter is one of `SCHEDULED`, `RENDERED`, `COMPLETED`, `CLAIMED`, `WRITTEN_OFF`, or `CANCELLED`. Scheduling runs a battery of checks. The session length must match the procedure code — a `90791` must be exactly 60 minutes and a `90834` exactly 45 minutes — or the request is rejected with `ERR_CPT_DURATION_MISMATCH`. Payment-path coherence is enforced next: an `INSURANCE` session requires a non-null `insurance_policy_id` whose own patient matches the appointment's patient, while a `SELF_PAY` session requires the policy reference to be absent; a violation is rejected with `ERR_PAYMENT_PATH_INVALID`. Within this step, a missing `insurance_policy_id` on an `INSURANCE` session, a `SELF_PAY` session that nonetheless carries a policy reference, and an `INSURANCE` session whose referenced policy belongs to a different patient all yield `ERR_PAYMENT_PATH_INVALID`; however, an `INSURANCE` session whose supplied `insurance_policy_id` does not resolve to any existing policy is rejected with `ERR_NOT_FOUND`.

Two distinct double-booking rules then apply, and they differ deliberately in their interval arithmetic. For the rendering clinician, the new session's interval is treated as half-open — running from `start_at` up to but not including its end — so a new session that overlaps any existing non-terminal session for the same clinician is rejected with `ERR_THERAPIST_DOUBLE_BOOKED`, while sessions that merely abut end-to-start are permitted. For the patient, the interval is treated as closed — including both endpoints — so a new session that touches or overlaps any existing non-terminal session for the same patient is rejected with `ERR_PATIENT_DOUBLE_BOOKED`, and even back-to-back adjacency is disallowed. Appointments are retrievable individually and as a list filtered by `therapist_id`, `patient_id`, `insurance_policy_id`, or `status`. A scheduled session may be cancelled by front-desk or a director, moving it to `CANCELLED`.

### 3.6. Rendering, Documenting, and Completing a Session

Rendering is the clinician's act of marking that a scheduled session actually took place, advancing it from `SCHEDULED` to `RENDERED`, and only the rendering clinician may perform it. The appointment must be in `SCHEDULED` status, failing which the render is rejected with `ERR_INVALID_STATE`. A render is then gated by a sequence of conditions evaluated in the following order. First, the patient must not be on a clinical hold; rendering against a patient whose status is `ON_CLINICAL_HOLD` is rejected with `ERR_PATIENT_ON_HOLD` — this hold gate is checked before the start-time and suspension gates below. Next, the session's `start_at` must be at or before the server's current UTC clock, failing which the render is rejected with `ERR_INVALID_STATE`. Next, the rendering clinician must not be `SUSPENDED`, failing which the render is likewise rejected with `ERR_INVALID_STATE`. The clinician must then hold a state license in `ACTIVE` status whose `state_code` equals the patient's `location_state_code`, failing which the render is rejected with `ERR_NO_ACTIVE_LICENSE_IN_STATE`; and if the session's `modality` is `TELEHEALTH`, that matching license's `telehealth_authorized` flag must be true, failing which it is rejected with `ERR_TELEHEALTH_NOT_AUTHORIZED`. On a successful render, a self-pay session has its `patient_charge_cents` stamped from the self-pay pricing calculation — the standard procedure rate (22,000 cents for `90791`, 15,000 cents for `90834`) multiplied by the patient's `sliding_fee_multiplier`, rounded half up to the nearest whole cent — while the clinician's `projected_direct_hours` are recomputed. Until a session is rendered its `patient_charge_cents` is 0.

Documentation rides alongside. A clinician creates a draft progress note for an appointment by supplying the `appointment_id` and the `narrative` text; the note is born `DRAFT`, its `signed_by_id` and `cosigned_by_id` both empty. The rendering clinician signs the note, which requires that the acting clinician be the rendering clinician of the linked appointment, advances it from `DRAFT` to `SIGNED`, and stamps `signed_by_id` with the signer. A supervisor then co-signs: co-signing requires that the acting clinician be the rendering clinician's supervisor and be `INDEPENDENT`, advances the note from `SIGNED` to `CO_SIGNED`, and stamps `cosigned_by_id`. Both the supervisor-match requirement and the co-signer's `INDEPENDENT` requirement are enforced as ownership checks: a request whose acting clinician is not the rendering clinician's supervisor, or who is the supervisor but is not `INDEPENDENT`, is rejected with `ERR_NOT_RESOURCE_OWNER`. The supervisor-match check is applied before the note's `SIGNED` state precondition, and the `INDEPENDENT` check after it. Notes are retrievable individually and as a list filtered by `appointment_id`, `signed_by_id`, `cosigned_by_id`, or `status`.

Completing a rendered session advances it from `RENDERED` to `COMPLETED` and is performed by the rendering clinician. The appointment must be in `RENDERED` status, failing which completion is rejected with `ERR_INVALID_STATE`. Completion requires that a clinical note for the appointment already exist in `SIGNED` or `CO_SIGNED` status; the absence of any such note is treated as a state precondition and likewise rejected with `ERR_INVALID_STATE`. Moreover, if the rendering clinician still requires supervision, the note must be `CO_SIGNED` rather than merely `SIGNED`, failing which completion is rejected with `ERR_COSIGN_REQUIRED`. On completion, the clinician's `verified_direct_hours` are recomputed.

### 3.7. The Insurance Claim Lifecycle and Ledger

From `COMPLETED`, an insurance-path session forks toward billing while a self-pay session forks toward write-off. A biller opens a claim by supplying the `appointment_id` and `expected_appointment_version`. The appointment must be in `COMPLETED` status and on the `INSURANCE` payment path — a non-`COMPLETED` appointment, or one not on the `INSURANCE` path, is rejected with `ERR_INVALID_STATE` (the `COMPLETED` precondition checked first, then the payment-path precondition). It must also not already carry a non-void claim, otherwise the create is rejected with `ERR_CLAIM_ALREADY_EXISTS`, which is evaluated after those two preconditions and before the `expected_appointment_version` version match. Opening a claim creates it in `SUBMITTED` status, copies the `insurance_policy_id` and `cpt_code` from the appointment, stamps the `billed_charge_cents` at the standard procedure rate, advances the appointment from `COMPLETED` to `CLAIMED`, and increments the appointment's version by one. A claim's status is one of `SUBMITTED`, `ADJUDICATED`, `DENIED`, `RESUBMITTED`, or `VOID`. Claims are retrievable individually and as a list filtered by `appointment_id` or `insurance_policy_id`.

Adjudication is the settlement step, allowed from either `SUBMITTED` or `RESUBMITTED`, and it stamps the ledger fields — `allowed_amount_cents`, `deductible_applied_cents`, `patient_responsibility_cents`, and `payer_paid_cents` — via the allowed-amount-and-waterfall calculation of Section 2.11. Adjudication then cascades: it increases the policy's `deductible_met_cents` by the deductible just applied, and it copies the computed patient responsibility onto the linked appointment's `patient_charge_cents`. A biller may instead deny a `SUBMITTED` claim, moving it to `DENIED`, and a denied claim may be resubmitted, moving it from `DENIED` to `RESUBMITTED` and back into the adjudication queue — the revert loop that lets a once-denied claim be settled. An adjudicated claim may be voided, moving it to `VOID`; voiding is a compensating reversal that decreases the policy's `deductible_met_cents` by exactly the amount this claim had applied (restoring it to its pre-adjudication value), resets the linked appointment's `patient_charge_cents` to 0, and reverts that appointment from `CLAIMED` back to `COMPLETED`. Each of these four claim transitions requires `expected_claim_version` to match and increments the claim's version by one; a transition requested from a state where it is not defined is rejected with `ERR_INVALID_STATE`. Separately, a biller may write off a completed self-pay session, moving it from `COMPLETED` to `WRITTEN_OFF` and zeroing its `patient_charge_cents`; an appointment that is not in `COMPLETED` status, or that is not on the `SELF_PAY` payment path, is rejected with `ERR_INVALID_STATE` (the `COMPLETED` precondition checked first, then the self-pay precondition).

### 3.8. Crisis Assessment, Clinical Holds, and Safety Plans

A clinician or director records a crisis assessment against a patient by supplying the `patient_id`, the assessing `therapist_id`, and four severity factors each in the range 0 through 3: `ideation_score`, `plan_score`, `means_access_score`, and `prior_attempts_score`. The patient must exist and must not be `DISCHARGED`; a crisis assessment recorded against a `DISCHARGED` patient is rejected with `ERR_INVALID_STATE`. On creation the system computes a `risk_score` and a `risk_band`. The raw score weights the four factors — ideation at 0.30, plan at 0.30, means access at 0.25, and prior attempts at 0.15 — and that weighted sum is then divided by 3 and multiplied by 100 to normalize onto a 0-to-100 scale, rounded half up to two decimal places. The band follows from the score: a score at or above 70 is `HIGH`, a score at or above 40 (but below 70) is `MODERATE`, and anything below 40 is `LOW`. A newly created assessment is `OPEN`. When the resulting band is `HIGH`, the assessment cascades to place the patient `ON_CLINICAL_HOLD` — which is precisely why a held patient's sessions cannot be rendered until the hold lifts.

A high-risk assessment demands a safety plan before it can be closed. A clinician or director attaches a safety plan to an assessment by supplying the `crisis_assessment_id`, the documented `warning_signs`, the `coping_strategies`, and a non-empty `emergency_contacts` array of crisis-line and emergency contacts. Resolving an assessment advances it from `OPEN` to `RESOLVED`, but if its band is `HIGH` and no safety plan exists for it, resolution is rejected with `ERR_SAFETY_PLAN_REQUIRED`. When an assessment is resolved and the patient has no other open assessment remaining, the patient's hold is lifted and their status reverts to `ACTIVE`. Crisis assessments are retrievable individually and as a list filtered by `patient_id` or `therapist_id` and optionally by `status`; safety plans are retrievable individually and as a list filtered by `crisis_assessment_id`.

### 3.9. The Order of Validation

When several conditions guard one operation, they are evaluated in a fixed order so that failures surface predictably. Authentication of the request headers comes first (`ERR_UNAUTHENTICATED`), then role authorization for the endpoint (`ERR_UNAUTHORIZED`), then, for clinician actions on appointments and notes, the resource-ownership check (`ERR_NOT_RESOURCE_OWNER`). The system next resolves every referenced identifier left-to-right (`ERR_NOT_FOUND`), then validates the shape of the request body — required fields, types, enum membership, and numeric ranges such as a severity factor within 0 through 3, a procedure code within the allowed set, or a household size of at least one (`ERR_INVALID_REQUEST`). Body-shape checks specific to scheduling follow: the procedure-code-to-duration match (`ERR_CPT_DURATION_MISMATCH`), then payment-path coherence (`ERR_PAYMENT_PATH_INVALID`). Only then are state-machine preconditions evaluated — whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`) — followed by the domain safety and referential gates: the crisis safety-plan gate (`ERR_SAFETY_PLAN_REQUIRED`), the clinical-hold gate (`ERR_PATIENT_ON_HOLD`), the active-license gate (`ERR_NO_ACTIVE_LICENSE_IN_STATE`), the telehealth gate (`ERR_TELEHEALTH_NOT_AUTHORIZED`), the co-sign gate (`ERR_COSIGN_REQUIRED`), and the promotion-eligibility gate (`ERR_PROMOTION_NOT_ELIGIBLE`). On render specifically, only the appointment-status precondition (the session must be `SCHEDULED`) is checked at the state-machine-precondition step; the clinical-hold gate (`ERR_PATIENT_ON_HOLD`) is then evaluated, and the render's remaining `ERR_INVALID_STATE` conditions — that `start_at` is at or before the current clock, and that the clinician is not `SUSPENDED` — are checked after the hold gate but before the active-license and telehealth gates. The scheduling overlap checks for the clinician and the patient (`ERR_THERAPIST_DOUBLE_BOOKED`, then `ERR_PATIENT_DOUBLE_BOOKED`) and the one-live-claim check (`ERR_CLAIM_ALREADY_EXISTS`) are likewise applied within their respective creates. The optimistic-concurrency version match (`ERR_STALE_VERSION`) is evaluated last among the business checks on every concurrency-guarded write.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify, transition, or otherwise act upon an existing resource return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST  | `/therapists`                       | Register a clinician (starts ASSOCIATE)                        | ClinicalDirector |
| GET   | `/therapists/{id}`                  | Fetch a therapist with computed credential and hour fields     | ClinicalDirector, Therapist, Biller, FrontDesk |
| GET   | `/therapists`                       | List therapists; filter by supervisor_id                       | ClinicalDirector, Therapist, Biller, FrontDesk |
| POST  | `/therapists/{id}/promote`          | Advance credential_status one step                             | ClinicalDirector |
| POST  | `/therapists/{id}/suspend`          | Suspend a clinician; cancels their scheduled appointments      | ClinicalDirector |
| POST  | `/state-licenses`                   | Issue a state license to a therapist                           | ClinicalDirector |
| GET   | `/state-licenses/{id}`              | Fetch a state license                                          | ClinicalDirector, Therapist, Biller, FrontDesk |
| GET   | `/state-licenses`                   | List licenses; filter by therapist_id or state_code            | ClinicalDirector, Therapist, Biller, FrontDesk |
| POST  | `/state-licenses/{id}/revoke`       | Revoke a license                                               | ClinicalDirector |
| POST  | `/supervision-logs`                 | Record a supervision session (starts SUBMITTED)                | ClinicalDirector, Therapist |
| GET   | `/supervision-logs/{id}`            | Fetch a supervision log                                        | ClinicalDirector, Therapist |
| GET   | `/supervision-logs`                 | List supervision logs; filter by therapist_id or supervisor_id | ClinicalDirector, Therapist |
| POST  | `/supervision-logs/{id}/accept`     | Accept a log; recomputes verified_supervision_hours            | ClinicalDirector |
| POST  | `/supervision-logs/{id}/reject`     | Reject a supervision log                                       | ClinicalDirector |
| POST  | `/patients`                         | Register a patient; computes sliding fee scale                 | FrontDesk, ClinicalDirector |
| GET   | `/patients/{id}`                    | Fetch a patient                                                | FrontDesk, ClinicalDirector, Therapist, Biller |
| GET   | `/patients`                         | List patients; filter by status                                | FrontDesk, ClinicalDirector, Therapist, Biller |
| PATCH | `/patients/{id}/financials`         | Update income/household; recomputes sliding fee scale          | FrontDesk, ClinicalDirector |
| POST  | `/insurance-policies`               | Attach an insurance policy to a patient                        | FrontDesk, ClinicalDirector, Biller |
| GET   | `/insurance-policies/{id}`          | Fetch an insurance policy                                      | FrontDesk, ClinicalDirector, Biller |
| GET   | `/insurance-policies`               | List policies; filter by patient_id or contract_id             | FrontDesk, ClinicalDirector, Biller |
| POST  | `/payer-contracts`                  | Create a payer contract                                        | ClinicalDirector, Biller |
| GET   | `/payer-contracts/{id}`             | Fetch a payer contract                                         | ClinicalDirector, Biller, FrontDesk |
| POST  | `/appointments`                     | Schedule a session; runs CPT/duration, payment-path, overlap checks | FrontDesk, Therapist, ClinicalDirector |
| GET   | `/appointments/{id}`                | Fetch an appointment                                           | FrontDesk, Therapist, ClinicalDirector, Biller |
| GET   | `/appointments`                     | List appointments; filter by therapist_id, patient_id, insurance_policy_id, status | FrontDesk, Therapist, ClinicalDirector, Biller |
| POST  | `/appointments/{id}/render`         | Mark a session rendered; enforces licensure/telehealth/hold gates | Therapist |
| POST  | `/appointments/{id}/complete`       | Complete a rendered session; enforces note/cosign gates        | Therapist |
| POST  | `/appointments/{id}/write-off`      | Charity write-off a completed self-pay session                 | Biller |
| POST  | `/appointments/{id}/cancel`         | Cancel a scheduled session                                     | FrontDesk, ClinicalDirector |
| POST  | `/clinical-notes`                   | Create a draft progress note for an appointment                | Therapist |
| GET   | `/clinical-notes/{id}`              | Fetch a clinical note                                          | Therapist, ClinicalDirector |
| GET   | `/clinical-notes`                   | List clinical notes; filter by appointment_id, signed_by_id, cosigned_by_id, status | Therapist, ClinicalDirector |
| POST  | `/clinical-notes/{id}/sign`         | Rendering therapist signs the note                             | Therapist |
| POST  | `/clinical-notes/{id}/cosign`       | Supervisor co-signs a signed note                              | Therapist |
| POST  | `/claims`                           | Open an insurance claim for a completed insurance appointment  | Biller |
| GET   | `/claims/{id}`                      | Fetch a claim with adjudication ledger fields                  | Biller, ClinicalDirector |
| GET   | `/claims`                           | List claims; filter by appointment_id or insurance_policy_id   | Biller, ClinicalDirector |
| POST  | `/claims/{id}/adjudicate`           | Adjudicate a claim; applies deductible and syncs charge        | Biller |
| POST  | `/claims/{id}/deny`                 | Deny a submitted/resubmitted claim                             | Biller |
| POST  | `/claims/{id}/resubmit`             | Resubmit a denied claim                                        | Biller |
| POST  | `/claims/{id}/void`                 | Void an adjudicated claim; compensating reversal               | Biller |
| POST  | `/crisis-assessments`               | Record a crisis assessment; HIGH places patient on hold        | Therapist, ClinicalDirector |
| GET   | `/crisis-assessments/{id}`          | Fetch a crisis assessment                                      | Therapist, ClinicalDirector |
| GET   | `/crisis-assessments`               | List crisis assessments; filter by patient_id or therapist_id  | Therapist, ClinicalDirector |
| POST  | `/crisis-assessments/{id}/resolve`  | Resolve a crisis assessment; HIGH requires a SafetyPlan        | Therapist, ClinicalDirector |
| POST  | `/safety-plans`                     | Attach a safety plan to a HIGH-risk crisis assessment          | Therapist, ClinicalDirector |
| GET   | `/safety-plans/{id}`                | Fetch a safety plan                                            | Therapist, ClinicalDirector |
| GET   | `/safety-plans`                     | List safety plans; filter by crisis_assessment_id              | Therapist, ClinicalDirector |
| POST  | `/_clock/set_current_utc`           | Test-driving: set the server's current UTC clock               | ClinicalDirector |
| POST  | `/_inject/therapist_hours`          | Test-driving: set a therapist's verified hour totals           | ClinicalDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED`            | 401 |
| `ERR_UNAUTHORIZED`               | 403 |
| `ERR_NOT_RESOURCE_OWNER`         | 403 |
| `ERR_NOT_FOUND`                  | 404 |
| `ERR_INVALID_REQUEST`            | 422 |
| `ERR_CPT_DURATION_MISMATCH`      | 422 |
| `ERR_PAYMENT_PATH_INVALID`       | 422 |
| `ERR_INVALID_STATE`              | 409 |
| `ERR_SAFETY_PLAN_REQUIRED`       | 409 |
| `ERR_PATIENT_ON_HOLD`            | 409 |
| `ERR_NO_ACTIVE_LICENSE_IN_STATE` | 409 |
| `ERR_TELEHEALTH_NOT_AUTHORIZED`  | 409 |
| `ERR_COSIGN_REQUIRED`            | 409 |
| `ERR_PROMOTION_NOT_ELIGIBLE`     | 409 |
| `ERR_THERAPIST_DOUBLE_BOOKED`    | 409 |
| `ERR_PATIENT_DOUBLE_BOOKED`      | 409 |
| `ERR_CLAIM_ALREADY_EXISTS`       | 409 |
| `ERR_STALE_VERSION`              | 412 |

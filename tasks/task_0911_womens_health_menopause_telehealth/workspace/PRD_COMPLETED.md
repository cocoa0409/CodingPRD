# Women's Health & Menopause Telehealth API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Women's Health & Menopause Telehealth API, a platform that carries a patient from her first symptom-intake questionnaire all the way through a clinical visit, a hormone-replacement-therapy (HRT) prescription, ongoing lab surveillance, refills, and the financial reconciliation that sits behind every clinical event. The domain is deliberately safety-first: HRT carries absolute contraindications, refills may be gated on recent lab work, and a lapse in a patient's paid membership can pause her active therapy. The API must encode these clinical guardrails as hard, testable rules rather than advisory notes.

Two concerns run through the whole system in parallel. The first is **compliance gating** — the sequence of clearances (intake submitted, visit completed, contraindications reviewed, labs reviewed as normal) that must be satisfied before medication flows. The second is **money** — every visit and every refill produces a charge, and each charge is priced twice: once as a provisional estimate at service time and once as a final adjudicated amount that draws down a patient's insurance deductible and out-of-pocket accumulator, or applies a flat cash discount. Because charges, deductibles, refill counts, and adherence scores are all conserved or derived quantities, the system treats forward operations and their compensating reversals as strict mirror images so that no ledger silently drifts.

The API is consumed by four distinct actors — patients, clinicians, billing operators, and care coordinators — each owning a different surface of the workflow. The entities are peers linked by foreign keys rather than a deep containment tree, so most collections live at the root of the URL space. A logical clock, settable by billing operators, drives every date-sensitive rule (coverage windows, intake validity, adherence elapsed-day math) so that behavior is deterministic and reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting invariants that every endpoint inherits.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an unrecognized role, is rejected with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401). When the headers are present and valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403).

The system recognizes exactly four roles, spelled precisely: `Patient`, `Provider`, `BillingAdmin`, and `CareCoordinator`.

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient` entity. The system enforces this ownership comparison in exactly one place — visit scheduling, where the body `patient_id` must equal `X-User-ID` and the referenced intake must belong to that same patient, else `ERR_PATIENT_MISMATCH`. The other patient-driven operations (creating and submitting intake assessments, cancelling visits, requesting refills, creating and cancelling subscriptions, and appending care-plan messages) are gated by role and by the existence of the referenced resources, but do not additionally compare a resource's patient foreign key to `X-User-ID`. A patient acts on her own intake assessments, visits, refill requests, subscriptions, and care-plan messages.
- When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity. When a provider writes a prescription, the prescription's `provider_id` is set from `X-User-ID` — the acting clinician. Providers own visit completion, intake clearing, prescribing, lab ordering and resolution, and the full refill approval chain.
- When `X-User-Role` is `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`. Billing operators attach insurance policies, adjudicate and reverse charges, run dunning, and drive the logical clock.
- When `X-User-Role` is `CareCoordinator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity, recorded but never compared to an entity `id`. Care coordinators onboard patients and providers and participate in care-plan messaging.

Read endpoints (`GET`) are available to all four roles. The write privileges of each role are enumerated in the endpoint table of §4; any deviation surfaces as `ERR_ROLE_NOT_PERMITTED`.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return resources sorted by their `created_at` timestamp in ascending order, with ties — which are common because the logical clock is frozen between advances, so many resources share a `created_at` — broken by ascending creation sequence (server-side insertion order). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties

Nearly every resource in this system carries a standard set of system-managed fields:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at creation.
- `updated_at` — an ISO 8601 UTC timestamp, refreshed on every mutation.
- `version` — an integer that begins at 1 on creation and increments by 1 on every mutation.

There is one deliberate exception: a `CarePlanMessage` is an append-only event-log entry and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never mutated after it is written.

Whenever the server mutates a resource — whether in direct response to a client call or as an automatic cascade — it refreshes that resource's `updated_at` and increments its `version`. Derived-field recomputations that change a stored value (for example, a prescription's `refills_remaining` moving as a refill is fulfilled, or a policy's `remaining_deductible_cents` moving as a charge adjudicates) are mutations and bump `updated_at` and `version` on the affected resource.

### 2.5. The Logical Clock and Temporal Semantics

The system runs on a logical clock rather than wall-clock time. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any client sets it, every timestamp the system mints derives from this default — never from real time. A billing operator advances the clock by supplying a target instant `to_iso8601`. All date-sensitive computations — a prescription's `coverage_start_date`, a refill's `fill_date`, a lab's `resulted_at`, an intake's `submitted_at`, and every elapsed-day adherence calculation — read the current logical clock.

### 2.6. Optimistic Concurrency on Subscription Creation

Creating a subscription is guarded by optimistic concurrency on the patient. A `POST /subscriptions` request must include `expected_patient_version` as a required field carrying the `version` of the target `Patient` that the client last observed. Before any subscription business logic runs, the server compares `expected_patient_version` to the patient's current `version`. If they do not match — because a newer subscription has already superseded the prior one and advanced the patient's version since the client last read it — the create is rejected with `ERR_STALE_PATIENT_VERSION` (HTTP 412), preventing the client from acting on a stale view of the patient's membership. No other endpoint accepts a version field; only subscription creation carries this check.

### 2.7. Monetary Pricing, Scoring Precision, and Rounding

All monetary amounts are stored and returned as integer cents. The single rounding convention throughout the system is **round half up**. Wherever a pricing step produces a fractional cent — the cash-discount multiplication and the coinsurance multiplication — the result is rounded half up to a whole cent.

Two non-monetary computed values carry their own precision. The symptom severity score is rounded half up to 2 decimal places (with a pinned per-domain-then-total rounding order described in §3.2). The Proportion of Days Covered (PDC) adherence figures are rounded half up to 4 decimal places.

### 2.8. Hierarchical Consistency and Cascading Side Effects

Every stateful resource exposes its lifecycle position through a `status` field whose permitted values are the exact uppercase strings enumerated in §3. Many operations mutate more than one entity. When they do, every secondary effect is part of the same logical operation and must complete together. The recurring cascade patterns are:

- **Prescription suspension** (whether a provider suspends directly, a lab comes back abnormal, or a subscription is cancelled) denies that prescription's still-open refill requests, and each denial writes a system-authored notice to the care plan.
- **Prescription discontinuation** cancels the prescription's pending lab orders and denies its open refill requests.
- **Refill reversal** restores the prescription's refill count and either voids or reverses the linked charge; a charge reversal in turn restores the insurance policy's deductible and out-of-pocket accumulators.
- **Charge adjudication and reversal** move conserved amounts on the insurance policy in equal and opposite directions.

Each entity touched by a cascade is independently mutated: its `updated_at` and `version` advance as described in §2.4.

### 2.9. Nested Resource Retrieval and Path Validation

Several paths nest one resource under another (for example, a patient's insurance policies, or a prescription's lab orders). The server validates path identifiers left to right and rejects the request at the first identifier that does not resolve, returning the not-found error specific to that resource type: `ERR_PATIENT_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`, `ERR_INSURANCE_POLICY_NOT_FOUND`, `ERR_INTAKE_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_PRESCRIPTION_NOT_FOUND`, `ERR_LAB_ORDER_NOT_FOUND`, `ERR_REFILL_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, or `ERR_CARE_PLAN_NOT_FOUND` (all HTTP 404). For a nested path, a missing parent is reported before the child is even looked up.

The list collections that hang off a parent — a patient's insurance policies, intake assessments, and subscriptions; a prescription's lab orders and refills; a care plan's messages — exist to provide reverse reachability from the parent to resources that reference it by foreign key.

### 2.10. Validation Order and Priority

When several checks could fail on the same request, the outcome is deterministic because checks run in a fixed priority order. Earlier checks mask later ones. The global order is:

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers must be present and valid, else `ERR_MISSING_AUTH_CONTEXT` (401). Applies to every endpoint.
2. **Authorization** — the role must be permitted for the operation, else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint.
3. **Path existence** — every path-referenced resource must exist, validated left to right, else the resource-specific 404 of §2.9. Applies to every endpoint carrying path ids.
4. **Optimistic concurrency** — on subscription creation, `expected_patient_version` must equal the patient's current `version`, else `ERR_STALE_PATIENT_VERSION` (412). This runs before any subscription business logic.
5. **Body validation** — request-body types, enum members, and required fields must be well-formed, else `ERR_VALIDATION` (422). Applies to every write endpoint.
6. **Ownership / referential** — body-referenced foreign keys are first checked for existence, each non-resolving id yielding its resource-specific 404 of §2.9 (evaluated before the ownership comparison). Then, on visit scheduling, the body `patient_id` and the referenced intake's patient must equal the acting patient, else `ERR_PATIENT_MISMATCH` (422). Prescribing carries only the `visit_id` body foreign key, validated for existence alone (`ERR_VISIT_NOT_FOUND`); it applies no patient-mismatch check.
7. **Target state** — the target resource must be in a state that allows the requested transition, else the resource-specific `ERR_..._INVALID_STATE` (409). Applies to all lifecycle action endpoints.

Beyond this common spine, several endpoint-specific checks are ordered relative to one another, and two ordering conflicts are resolved explicitly:

- **Conflict A (refill approval).** The parent-prescription-must-be-`ACTIVE` state check (yielding `ERR_PRESCRIPTION_NOT_ACTIVE`, 409) is evaluated **before** the lab-required safety check (yielding `ERR_LAB_REQUIRED_BEFORE_REFILL`, 409). If a refill is approved against a prescription that is both non-`ACTIVE` and missing its required normal lab, the response is `ERR_PRESCRIPTION_NOT_ACTIVE`.
- **Conflict B (visit scheduling).** The provider slot-overlap check (yielding `ERR_PROVIDER_SLOT_OVERLAP`, 409) is evaluated **before** the past-due-membership fiscal check (yielding `ERR_SUBSCRIPTION_PAST_DUE`, 402). If a visit would both overlap another slot and be blocked by a past-due subscription, the response is `ERR_PROVIDER_SLOT_OVERLAP`.

The remaining endpoint-specific checks — intake-not-cleared and intake-expired on prescribing, intake-not-submitted on visit scheduling, coverage-window conflict on prescribing, refills-remaining on refill request, and one-policy-per-patient on policy attach — are described alongside the workflows they guard in §3.

### 2.11. Conserved-Quantity Invariants

Two quantities in the system are conserved and must hold after every forward operation and every compensating reversal.

**Refill count.** For any prescription, `refills_remaining` plus the count of that prescription's refills currently in `FULFILLED` status always equals `total_refills_authorized`. Fulfilling a refill decrements `refills_remaining` by 1 as the refill enters `FULFILLED` (net change zero); reversing a fulfilled refill increments `refills_remaining` by 1 as the refill leaves `FULFILLED` (net change zero).

**Insurance deductible.** For any insurance policy, `remaining_deductible_cents` plus `consumed_deductible_cents` always equals `deductible_cents`. Adjudicating an insured charge subtracts the applied deductible from `remaining_deductible_cents` and adds the same amount to `consumed_deductible_cents` (net change zero); reversing that charge adds it back to `remaining_deductible_cents` and subtracts it from `consumed_deductible_cents` (net change zero).

## 3. Business Logic & Workflows

### 3.1. Onboarding: Patients, Providers, and Insurance

A care coordinator registers a `Patient` by supplying her `full_name`, `email` (which is unique across patients; a duplicate email is rejected with `ERR_VALIDATION`, 422), `date_of_birth` as an ISO date, `state_code` as the two-letter U.S. state of residence (a licensure gate), a `billing_mode` of either `CASH` or `INSURANCE`, and a `menopause_stage` of `PERIMENOPAUSE`, `MENOPAUSE`, `POSTMENOPAUSE`, or `UNKNOWN`. A newly registered patient begins with `version` at 1.

A care coordinator also registers a `Provider` with a `full_name`, a `specialty` of `GYNECOLOGY`, `ENDOCRINOLOGY`, or `FAMILY_MEDICINE`, an `npi` National Provider Identifier, and a `visit_fee_cents` list price (a non-negative integer) that will become the allowed amount of any visit charge this provider generates.

A billing operator may attach at most one `InsurancePolicy` to a patient. The policy is created with a `payer_name`, an annual `deductible_cents` (a non-negative integer), a `coinsurance_rate` expressed as a fraction between 0 and 1 inclusive (for example, 0.20 for twenty percent), and an annual `out_of_pocket_max_cents` (a non-negative integer); any of these three numeric fields falling outside its bound is rejected with `ERR_VALIDATION` (422). At creation the system seeds the three conserved accumulators: `remaining_deductible_cents` is initialized to `deductible_cents`, `consumed_deductible_cents` is initialized to 0, and `oop_accumulated_cents` is initialized to 0. Because a patient may hold only one policy, a second attach attempt is rejected with `ERR_POLICY_ALREADY_EXISTS` (409). A policy references its owner through `patient_id`.

### 3.2. Intake and Symptom Assessment

A patient's clinical journey opens with an `IntakeAssessment`, created in `DRAFT` status against her own record (its `patient_id`). At creation she supplies `symptom_ratings` — a list of `{domain, severity}` entries where `domain` is one of `VASOMOTOR`, `SLEEP`, `MOOD`, `GENITOURINARY`, or `COGNITIVE` and `severity` is an integer from 0 through 10 — and `reported_conditions`, a list drawn from `BREAST_CANCER_HISTORY`, `VTE_HISTORY`, `UNDIAGNOSED_BLEEDING`, `STROKE_HISTORY`, and `NONE`.

Submitting an intake (a patient action) is permitted only while it is `DRAFT`; a submit from any other state is rejected with `ERR_INTAKE_INVALID_STATE` (409). On submit the system performs two computations and records `submitted_at` as the current logical-clock instant.

The first computation is the **symptom severity score**, written to `symptom_severity_score`. Each symptom domain carries a weight: `VASOMOTOR` is 1.0, `SLEEP` is 0.833, `MOOD` is 0.667, `GENITOURINARY` is 0.75, and `COGNITIVE` is 0.6. For each `{domain, severity}` entry, the per-domain contribution is the severity multiplied by that domain's weight, rounded half up to 2 decimal places. The score is the sum of those already-rounded per-domain contributions, with that sum itself rounded half up to 2 decimal places. The rounding order is pinned: round each per-domain contribution to 2 decimals first, then sum, then round the total — never sum first and round once.

The second computation is the **absolute-contraindication flag**, written to `has_absolute_contraindication`. The absolute-contraindication set is `BREAST_CANCER_HISTORY`, `VTE_HISTORY`, `UNDIAGNOSED_BLEEDING`, and `STROKE_HISTORY`. If `reported_conditions` contains at least one member of that set, `has_absolute_contraindication` is true and the assessment transitions `DRAFT → FLAGGED`; if it contains none of them, the flag is false and the assessment transitions `DRAFT → CLEARED`.

A `FLAGGED` assessment can be salvaged: a provider reviewing the case may clear it, transitioning `FLAGGED → CLEARED`. Clearing is permitted only from `FLAGGED`, otherwise `ERR_INTAKE_INVALID_STATE` (409). A `DRAFT` assessment is not yet submitted and carries a null `submitted_at`.

### 3.3. Scheduling and Completing Visits

A patient schedules a `Visit` by supplying `patient_id`, `provider_id`, `intake_assessment_id`, and the slot bounds `scheduled_start` (inclusive) and `scheduled_end` (exclusive). The referenced intake must belong to the same patient, and the `patient_id` in the body must be the acting patient; a mismatch on either body foreign key is rejected with `ERR_PATIENT_MISMATCH` (422). The referenced intake must already be submitted — that is, in `CLEARED` or `FLAGGED` — otherwise the schedule is rejected with `ERR_INTAKE_NOT_SUBMITTED` (409).

Two further checks guard scheduling, in the order fixed by Conflict B in §2.10. First, the new slot must not overlap any other `SCHEDULED` visit for the same provider. Overlap is judged on the half-open interval from `scheduled_start` up to but not including `scheduled_end`, so two visits that merely touch at an endpoint do not conflict; a true overlap is rejected with `ERR_PROVIDER_SLOT_OVERLAP` (409). Second, if the patient currently holds a subscription in `PAST_DUE`, scheduling is refused with `ERR_SUBSCRIPTION_PAST_DUE` (402). A new visit is created in `SCHEDULED` status.

When a provider completes a visit, the visit transitions `SCHEDULED → COMPLETED`; completion is allowed only from `SCHEDULED`, otherwise `ERR_VISIT_INVALID_STATE` (409). Completion has a financial side effect: the system creates a `Charge` with `billable_kind` of `VISIT`, `billable_id` set to the visit's id, `allowed_amount_cents` set to the provider's `visit_fee_cents`, and `billing_mode` snapshotted from the patient's `billing_mode`, all in `ESTIMATED` status. It computes the estimated patient responsibility on that charge (per §3.8) and records the new charge's id on the visit as `visit_charge_id`. Until completion, `visit_charge_id` is null.

A patient may cancel her own `SCHEDULED` visit, transitioning `SCHEDULED → CANCELLED`; a cancel from any other state is rejected with `ERR_VISIT_INVALID_STATE` (409).

### 3.4. Prescribing HRT and Opening a Care Plan

Once a visit is complete, its provider may write a `Prescription` from it. The provider supplies `visit_id`, the `hrt_type` (`ESTROGEN_PATCH`, `ESTROGEN_ORAL`, `PROGESTERONE`, `COMBINED`, or `VAGINAL_ESTROGEN`), `days_supply_per_fill` (at least 1), `total_refills_authorized` (at least 0), the boolean `lab_required_before_refill`, `coverage_days` (at least 0), and `refill_price_cents` (a non-negative integer, the list price each refill charge will carry); a value violating these numeric bounds is rejected with `ERR_VALIDATION` (422). The prescription copies `patient_id` from the source visit and sets `provider_id` to the acting clinician from `X-User-ID`.

Several gates apply to prescribing. The source visit must be `COMPLETED` and its intake must be `CLEARED`; if not, the request is rejected with `ERR_INTAKE_NOT_CLEARED` (409). The sole body foreign key is `visit_id`; if it does not resolve the request is rejected with `ERR_VISIT_NOT_FOUND` (404), and prescribing applies no `ERR_PATIENT_MISMATCH` check — the prescription's `patient_id` is copied from the source visit, so no cross-patient mismatch can arise. The backing intake must have been submitted within the last 90 days of the current logical clock; an older intake yields `ERR_INTAKE_EXPIRED` (409). Finally, the new coverage window must not crowd an existing one: for the same patient and the same `hrt_type`, the new window must be separated by at least a 7-day buffer from the window of any `ACTIVE` or `SUSPENDED` prescription of that same type. Windows are treated as closed intervals and the buffer is inclusive, so the gap between the two windows must be at least 7 days; a smaller gap (including any overlap or touching) is rejected with `ERR_COVERAGE_WINDOW_CONFLICT` (409).

On creation the prescription starts `ACTIVE`, sets `refills_remaining` equal to `total_refills_authorized`, records `coverage_start_date` as the current logical-clock date, and sets `coverage_end_date` to that start date advanced by `coverage_days` days. Its `last_fill_date` is null until the first refill is fulfilled. The system also auto-creates the prescription's 1:1 `CarePlan` — carrying the `patient_id` and the `prescription_id` — and records its id on the prescription as `care_plan_id`.

A prescription moves through a cyclic lifecycle. A provider may suspend an `ACTIVE` prescription (`ACTIVE → SUSPENDED`); this is permitted only from `ACTIVE`, else `ERR_PRESCRIPTION_INVALID_STATE` (409), and an optional `reason` may accompany it. Suspension denies every one of that prescription's refills still in `REQUESTED`, stamping each with the denial reason "prescription suspended"; each such denial appends a system-authored `DENIAL_NOTICE` to the care plan.

A provider may reactivate a `SUSPENDED` prescription (`SUSPENDED → ACTIVE`), permitted only from `SUSPENDED`, else `ERR_PRESCRIPTION_INVALID_STATE` (409). Reactivation carries two further preconditions: if `lab_required_before_refill` is true, a lab order for this prescription must be `REVIEWED` with a `NORMAL` result, otherwise `ERR_LAB_REQUIRED_BEFORE_REFILL` (409); and the patient must not hold any subscription in `PAST_DUE`, otherwise `ERR_SUBSCRIPTION_PAST_DUE` (402). On success the system appends a system-authored `GENERAL` care-plan message reading "prescription reactivated".

A provider may discontinue a prescription from either `ACTIVE` or `SUSPENDED` (`ACTIVE → DISCONTINUED` or `SUSPENDED → DISCONTINUED`), permitted only from those two states, else `ERR_PRESCRIPTION_INVALID_STATE` (409), optionally with a `reason`. Discontinuation cascades twice: every lab order of the prescription still in `PENDING` is cancelled (`PENDING → CANCELLED`), and every refill still in `REQUESTED` or `APPROVED` is denied with the denial reason "prescription discontinued". `DISCONTINUED` and `EXPIRED` are terminal. A prescription becomes `EXPIRED` by system action when a refill request or approval is attempted after its `coverage_end_date` — that is, when the current logical-clock date is later than `coverage_end_date`.

### 3.5. Labs and the Safety Gate

A provider orders a lab against a prescription by supplying a `panel_type` of `LIPID`, `HORMONE`, `LIVER`, or `MAMMOGRAM`; the new `LabOrder` references its `prescription_id` and begins `PENDING`. Resolving the lab (a provider action) records the `result` and transitions `PENDING → REVIEWED`; resolution is allowed only from `PENDING`, else `ERR_LAB_ORDER_INVALID_STATE` (409), and the supplied `result` must be either `NORMAL` or `ABNORMAL`, else `ERR_VALIDATION` (422). On resolve the system sets `result` and stamps `resulted_at` with the current logical-clock date.

An abnormal result is a safety event. If the resolved `result` is `ABNORMAL` and the parent prescription is `ACTIVE`, the system cascades the prescription into suspension (`ACTIVE → SUSPENDED`), which in turn denies that prescription's `REQUESTED` refills and appends a `DENIAL_NOTICE` to the care plan for each. A lab reaches `CANCELLED` only by system cascade when its prescription is discontinued.

The lab requirement is the core refill safety gate. When a prescription has `lab_required_before_refill` set to true, a refill may not be approved and a suspended prescription may not be reactivated until a `REVIEWED` lab with a `NORMAL` result exists for that prescription; the guard is `ERR_LAB_REQUIRED_BEFORE_REFILL` (409) in both cases.

### 3.6. The Refill Lifecycle and Adherence

A patient requests a refill against a prescription; the new `Refill` references its `prescription_id` and starts `REQUESTED`. A request is refused unless the prescription has at least one refill remaining — that is, `refills_remaining` is 1 or greater — otherwise `ERR_NO_REFILLS_REMAINING` (409).

A provider approves a `REQUESTED` refill (`REQUESTED → APPROVED`). Approval requires the refill to be `REQUESTED`, else `ERR_REFILL_INVALID_STATE` (409); the parent prescription to be `ACTIVE`, else `ERR_PRESCRIPTION_NOT_ACTIVE` (409); and, when the prescription requires labs, a `REVIEWED`-`NORMAL` lab to exist, else `ERR_LAB_REQUIRED_BEFORE_REFILL` (409). As fixed by Conflict A in §2.10, the prescription-active check precedes the lab check. A provider may instead deny a `REQUESTED` refill (`REQUESTED → DENIED`), permitted only from `REQUESTED`, else `ERR_REFILL_INVALID_STATE` (409); an optional `denial_reason` may be supplied and is recorded on the refill, and the denial appends a system-authored `DENIAL_NOTICE` to the prescription's care plan.

A provider fulfills an `APPROVED` refill (`APPROVED → FULFILLED`). Fulfillment requires the refill to be `APPROVED`, else `ERR_REFILL_INVALID_STATE` (409), and the prescription to be `ACTIVE`, else `ERR_PRESCRIPTION_NOT_ACTIVE` (409). On fulfillment the system snapshots `days_supply` from the prescription's `days_supply_per_fill`, stamps `fill_date` with the current logical-clock date, decrements the prescription's `refills_remaining` by 1, sets the prescription's `last_fill_date` to that fill date, and creates a `Charge` with `billable_kind` of `REFILL`, `billable_id` set to the refill's id, `allowed_amount_cents` set to the prescription's `refill_price_cents`, and `billing_mode` snapshotted from the patient — in `ESTIMATED` status with its estimated responsibility computed (per §3.8) — recording the charge's id on the refill as `charge_id`.

A provider may reverse a `FULFILLED` refill (`FULFILLED → REVERSED`), permitted only from `FULFILLED`, else `ERR_REFILL_INVALID_STATE` (409), optionally with a `reason`. Reversal restores the count — `refills_remaining` is incremented by 1 — and cascades to the linked charge identified by `charge_id`: if that charge is still `ESTIMATED` it is voided (`ESTIMATED → VOID`); if it has already been adjudicated it is reversed (`ADJUDICATED → REVERSED`), which restores the insurance policy's deductible and out-of-pocket accumulators as described in §3.8. `DENIED` and `REVERSED` are terminal refill states.

**Adherence.** Each care plan exposes two Proportion-of-Days-Covered figures and a status band, recomputed whenever the care plan is read and whenever a refill is fulfilled or reversed. Let elapsed days be the number of days from the prescription's `coverage_start_date` to the current logical-clock date, floored at a minimum of 1. The realized supply is the sum of `days_supply` across the prescription's `FULFILLED` refills. The projected supply is that realized supply plus the prescription's `days_supply_per_fill` multiplied by the count of the prescription's refills currently in `REQUESTED` or `APPROVED`. Then `realized_pdc` is the smaller of the realized supply and elapsed days, divided by elapsed days, rounded half up to 4 decimals; `projected_pdc` is the smaller of the projected supply and elapsed days, divided by elapsed days, rounded half up to 4 decimals. The realized figure counts only fulfilled refills and drives the status; the projected figure additionally counts pending refills as if they will each be fulfilled at the full `days_supply_per_fill`, and so diverges from realized whenever a pending refill exists.

The `adherence_status` band is read off `realized_pdc`: below 0.80 it is `NON_ADHERENT`; from 0.80 up to but not including 0.90 it is `AT_RISK`; at 0.90 or above it is `ADHERENT`. The 0.80 floor is inclusive on the `AT_RISK` side and the 0.90 floor is inclusive on the `ADHERENT` side.

### 3.7. Subscriptions and Membership

A patient creates a `Subscription` by supplying `patient_id`, a `plan_tier` of `ESSENTIAL` or `PLUS`, and `expected_patient_version` (see §2.6). The system derives `monthly_fee_cents` from the tier — 3,900 cents ($39.00) for `ESSENTIAL` and 7,900 cents ($79.00) for `PLUS` — stamps `started_at` with the current logical-clock instant, and starts the subscription `ACTIVE`. Creating a new subscription supersedes the patient's prior membership: any existing subscription of that patient in `ACTIVE` or `PAST_DUE` transitions to `SUPERSEDED`, and the patient's `version` is incremented by 1. That version bump is exactly what a stale `expected_patient_version` on a subsequent create would fail against.

A billing operator may mark an `ACTIVE` subscription past due (`ACTIVE → PAST_DUE`), permitted only from `ACTIVE`, else `ERR_SUBSCRIPTION_INVALID_STATE` (409). There is no dedicated reinstatement action; a `PAST_DUE` subscription leaves that state only by being cancelled or by being superseded when a fresh subscription is created.

A patient may cancel her subscription from either `ACTIVE` or `PAST_DUE` (`ACTIVE → CANCELLED` or `PAST_DUE → CANCELLED`), permitted only from those two states, else `ERR_SUBSCRIPTION_INVALID_STATE` (409). Cancellation cascades to therapy: every `ACTIVE` prescription belonging to that patient is suspended (`ACTIVE → SUSPENDED`), and each such suspension appends a system-authored `SUSPENSION_NOTICE` to that prescription's care plan. `CANCELLED` and `SUPERSEDED` are terminal.

### 3.8. Charge Pricing, Adjudication, and Reversal

Charges are never created directly by a client; they arise as side effects of completing a visit or fulfilling a refill. Every charge carries the patient's `patient_id`, the polymorphic pair `billable_kind` and `billable_id` (which resolves to a visit id when the kind is `VISIT` and a refill id when the kind is `REFILL`, and is not itself a foreign-key-prefixed field), a `billing_mode` snapshot, an `allowed_amount_cents`, and — for insured charges — an `insurance_policy_id` resolved to the patient's single policy at charge creation (null for cash charges — and also null when an `INSURANCE`-mode patient has no policy on record at charge creation, in which case responsibility is the full `allowed_amount_cents` with `deductible_applied_cents` and `insurance_paid_cents` both 0 — and likewise not a foreign-key-prefixed field).

**Pricing.** Patient responsibility is computed twice against the same algorithm but with different policy inputs. Let the allowed amount be `allowed_amount_cents`.

- If the charge's billing mode is `CASH`, responsibility is the allowed amount multiplied by 90 percent — that is, the allowed amount less a 10 percent cash discount — rounded half up to whole cents. For cash charges `deductible_applied_cents` is 0 and `insurance_paid_cents` is 0.
- If the billing mode is `INSURANCE`, the algorithm applies the policy in a pinned order: deductible first, then coinsurance on the remainder, then the out-of-pocket cap last. The deductible portion is the smaller of the policy's `remaining_deductible_cents` and the allowed amount. The amount after deductible is the allowed amount minus that deductible portion. The coinsurance portion is the after-deductible amount multiplied by the policy's `coinsurance_rate`, rounded half up to whole cents. The pre-cap responsibility is the deductible portion plus the coinsurance portion. The out-of-pocket room is the policy's `out_of_pocket_max_cents` minus its `oop_accumulated_cents`. The final responsibility is the smaller of the pre-cap responsibility and that out-of-pocket room. The deductible applied equals the deductible portion, and insurance paid equals the allowed amount minus the final responsibility.

**Estimate versus final.** The *estimate* variant runs at charge creation and writes `estimated_patient_responsibility_cents`, using the policy's `remaining_deductible_cents` and `oop_accumulated_cents` as they stand at service time (a snapshot). The *final* variant runs at adjudication and writes `final_patient_responsibility_cents`, recomputing against the policy's current `remaining_deductible_cents` and `oop_accumulated_cents` — which may have shrunk because other charges adjudicated in between — so the final amount diverges from the estimate once the deductible is partially consumed.

**Adjudication.** A billing operator adjudicates an `ESTIMATED` charge (`ESTIMATED → ADJUDICATED`), permitted only from `ESTIMATED`, else `ERR_CHARGE_INVALID_STATE` (409). Adjudication computes `final_patient_responsibility_cents`, `insurance_paid_cents` (the allowed amount minus the final responsibility, 0 for cash), and `deductible_applied_cents` against the current policy state. For an insured charge it then draws down the policy: `remaining_deductible_cents` decreases by the deductible applied, `consumed_deductible_cents` increases by the same, and `oop_accumulated_cents` increases by the final responsibility. Until adjudication, `final_patient_responsibility_cents`, `insurance_paid_cents`, and `deductible_applied_cents` are null.

**Reversal.** A billing operator may reverse an `ADJUDICATED` charge (`ADJUDICATED → REVERSED`), permitted only from `ADJUDICATED`, else `ERR_CHARGE_INVALID_STATE` (409), optionally with a `reason`; a charge may also reach `REVERSED` by cascade from a refill reversal. For an insured charge, reversal restores the policy in exact mirror image: `remaining_deductible_cents` increases by the previously applied deductible, `consumed_deductible_cents` decreases by the same, and `oop_accumulated_cents` decreases by the previously recorded final responsibility. A charge that is still `ESTIMATED` when its refill is reversed is voided (`ESTIMATED → VOID`) rather than reversed. `ADJUDICATED`, `VOID`, and `REVERSED` are terminal charge states, reachable only along the paths described here.

### 3.9. Care-Plan Messaging

A care plan accumulates an append-only stream of `CarePlanMessage` entries, each referencing its `care_plan_id`, carrying a `body`, and tagged with a `message_type` of `GENERAL`, `ADHERENCE_OUTREACH`, `SUSPENSION_NOTICE`, or `DENIAL_NOTICE` (defaulting to `GENERAL` when omitted). A patient, provider, or care coordinator may append a message; the system derives the `author_kind` from `X-User-Role` — `PATIENT`, `PROVIDER`, or `CARE_COORDINATOR` respectively. Messages generated by the system's own cascades — suspension notices when membership lapses or a prescription is suspended, and denial notices when refills are denied — carry an `author_kind` of `SYSTEM`. Because these entries are an immutable event log, each carries only its `id` and `created_at`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including every lifecycle action and the logical-clock control — return `200 OK`. Request and response bodies are reconstructed from the workflow narratives in §3; the table below is a routing and authorization summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | BillingAdmin |
| POST | `/patients` | Register a patient | CareCoordinator |
| GET | `/patients/{id}` | Get a patient | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/providers` | Register a provider | CareCoordinator |
| POST | `/patients/{id}/insurance-policies` | Attach an insurance policy to a patient | BillingAdmin |
| GET | `/patients/{id}/insurance-policies` | List a patient's insurance policies | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/patients/{id}/intake-assessments` | Create a DRAFT intake assessment | Patient |
| POST | `/intake-assessments/{id}/submit` | Submit an intake; score and flag; clear or flag | Patient |
| POST | `/intake-assessments/{id}/clear` | Clear a flagged intake after review | Provider |
| GET | `/intake-assessments/{id}` | Get an intake assessment | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/patients/{id}/intake-assessments` | List a patient's intake assessments | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/visits` | Schedule a visit | Patient |
| POST | `/visits/{id}/complete` | Complete a visit; create a VISIT charge | Provider |
| POST | `/visits/{id}/cancel` | Cancel a scheduled visit | Patient |
| GET | `/visits/{id}` | Get a visit | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/visits` | List/filter visits | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/prescriptions` | Write an HRT prescription; auto-create a care plan | Provider |
| POST | `/prescriptions/{id}/suspend` | Suspend an active prescription | Provider |
| POST | `/prescriptions/{id}/reactivate` | Reactivate a suspended prescription | Provider |
| POST | `/prescriptions/{id}/discontinue` | Discontinue a prescription | Provider |
| GET | `/prescriptions/{id}` | Get a prescription | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/prescriptions` | List/filter prescriptions | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/prescriptions/{id}/lab-orders` | Order a lab against a prescription | Provider |
| POST | `/lab-orders/{id}/resolve` | Record and review a lab result | Provider |
| GET | `/lab-orders/{id}` | Get a lab order | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/prescriptions/{id}/lab-orders` | List a prescription's lab orders | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/prescriptions/{id}/refills` | Request a refill | Patient |
| POST | `/refills/{id}/approve` | Approve a refill | Provider |
| POST | `/refills/{id}/deny` | Deny a refill | Provider |
| POST | `/refills/{id}/fulfill` | Fulfill an approved refill; create a REFILL charge | Provider |
| POST | `/refills/{id}/reverse` | Reverse a fulfilled refill | Provider |
| GET | `/refills/{id}` | Get a refill | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/prescriptions/{id}/refills` | List a prescription's refills | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/subscriptions` | Create a subscription (OCC on Patient.version) | Patient |
| POST | `/subscriptions/{id}/cancel` | Cancel a subscription | Patient |
| POST | `/subscriptions/{id}/mark-past-due` | Mark a subscription past due | BillingAdmin |
| GET | `/subscriptions/{id}` | Get a subscription | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/patients/{id}/subscriptions` | List a patient's subscriptions | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/charges/{id}/adjudicate` | Adjudicate an estimated charge | BillingAdmin |
| POST | `/charges/{id}/reverse` | Reverse an adjudicated charge | BillingAdmin |
| GET | `/charges/{id}` | Get a charge | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/charges` | List/filter charges | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/care-plans/{id}` | Get a care plan (computes PDC and status on read) | Patient, Provider, BillingAdmin, CareCoordinator |
| GET | `/care-plans` | List/filter care plans | Patient, Provider, BillingAdmin, CareCoordinator |
| POST | `/care-plans/{id}/messages` | Append a message to a care plan | Patient, Provider, CareCoordinator |
| GET | `/care-plans/{id}/messages` | List a care plan's messages | Patient, Provider, BillingAdmin, CareCoordinator |

The filterable list endpoints accept optional query parameters: visits by `patient_id`, `provider_id`, or `intake_assessment_id`; prescriptions by `patient_id`, `provider_id`, or `visit_id`; charges by `patient_id` or `billable_id`; and care plans by `patient_id` or `prescription_id`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 |
| `ERR_ROLE_NOT_PERMITTED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_PROVIDER_NOT_FOUND` | 404 |
| `ERR_INSURANCE_POLICY_NOT_FOUND` | 404 |
| `ERR_INTAKE_NOT_FOUND` | 404 |
| `ERR_VISIT_NOT_FOUND` | 404 |
| `ERR_PRESCRIPTION_NOT_FOUND` | 404 |
| `ERR_LAB_ORDER_NOT_FOUND` | 404 |
| `ERR_REFILL_NOT_FOUND` | 404 |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 |
| `ERR_CHARGE_NOT_FOUND` | 404 |
| `ERR_CARE_PLAN_NOT_FOUND` | 404 |
| `ERR_STALE_PATIENT_VERSION` | 412 |
| `ERR_PATIENT_MISMATCH` | 422 |
| `ERR_INTAKE_INVALID_STATE` | 409 |
| `ERR_VISIT_INVALID_STATE` | 409 |
| `ERR_PRESCRIPTION_INVALID_STATE` | 409 |
| `ERR_PRESCRIPTION_NOT_ACTIVE` | 409 |
| `ERR_LAB_ORDER_INVALID_STATE` | 409 |
| `ERR_REFILL_INVALID_STATE` | 409 |
| `ERR_SUBSCRIPTION_INVALID_STATE` | 409 |
| `ERR_CHARGE_INVALID_STATE` | 409 |
| `ERR_INTAKE_NOT_CLEARED` | 409 |
| `ERR_INTAKE_NOT_SUBMITTED` | 409 |
| `ERR_LAB_REQUIRED_BEFORE_REFILL` | 409 |
| `ERR_PROVIDER_SLOT_OVERLAP` | 409 |
| `ERR_COVERAGE_WINDOW_CONFLICT` | 409 |
| `ERR_INTAKE_EXPIRED` | 409 |
| `ERR_NO_REFILLS_REMAINING` | 409 |
| `ERR_POLICY_ALREADY_EXISTS` | 409 |
| `ERR_SUBSCRIPTION_PAST_DUE` | 402 |

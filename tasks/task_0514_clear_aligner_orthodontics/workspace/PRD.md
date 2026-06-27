# Clear-Aligner Orthodontics API — Product Requirements Document

## 1. Introduction

Direct-to-consumer clear-aligner orthodontics compresses a traditionally office-bound treatment into a remote, mail-order experience: a patient captures dental impressions at home or at a partner scanning clinic, a licensed clinician reviews the case and authors a treatment plan, manufacturing presses a numbered sequence of aligner trays, and those trays ship one cadence at a time while the patient checks in with progress photos. This API is the backend system of record for that entire journey — from intake through plan review, manufacturing, shipment, financing, refinement, completion, retainer subscription, and, where clinical eligibility fails, decline and refund.

The platform serves four non-overlapping operator populations who never inherit one another's authority. Patients own intake, check-ins, refinement requests, and the initiation of financing, refunds, and retainers on their own cases. Clinicians author and review plans, assess check-ins, decide eligibility, grant or deny refinements, and close out finished cases. A manufacturing-and-fulfilment function presses trays and runs the shipping lifecycle. A billing back-office activates financing, posts payments, runs delinquency sweeps, and approves and settles refunds. Because money, clinical safety, and physical inventory all move inside the same workflow, every state change must settle its downstream consequences — ledger debits, case posture, shipment status — atomically within the request that triggered it; the system never defers a side effect to a later sweep except where a sweep is explicitly the trigger.

This document specifies the global contracts that every endpoint honours (Section 2), the business workflows and their interlocking rules (Section 3), the endpoint surface (Section 4), and the catalogue of error identifiers (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. If either header is absent, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. If both headers are present but the named role is not permitted to invoke the requested endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). Authentication is always checked before authorization.

The system recognises exactly four roles, spelled precisely as follows: `Patient`, `Clinician`, `ManufacturingOps`, and `BillingAdmin`. No role is a superset of another; each owns a distinct slice of the workflow.

Two of these roles are backed by persisted business entities, and two are opaque operational identities:

- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks on any resource that references a `Patient` compare the resource's patient foreign key to `X-User-ID`. A patient acts on their own intake, check-ins, refinement requests, financing, refunds, and retainers.
- When `X-User-Role` is `Clinician`, `X-User-ID` is the `id` of the acting `Clinician`; ownership and assignment checks on any resource that references a `Clinician` compare the resource's clinician foreign key to `X-User-ID`. In particular, plan-review actions verify that the acting clinician's `id` equals the case's `assigned_clinician_id`.
- When `X-User-Role` is `ManufacturingOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`.
- When `X-User-Role` is `BillingAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints accept two pagination query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. Lists are returned in ascending order of `created_at` — the oldest record first — unless an endpoint's narrative explicitly states otherwise. Each list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` is the full count of matching records ignoring pagination and `has_more` is true when records beyond the current page remain.

### 2.4. Common Resource Properties and the Versioning Contract

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 on creation and increments by one on every mutation that changes the resource. These three behaviours — `updated_at` refresh and `version` increment on mutation — apply to `Patient`, `Clinician`, `TreatmentCase`, `IntakeRecord`, `TreatmentPlan`, `AlignerStep`, `Shipment`, `RefinementRequest`, `FinancingPlan`, `Installment`, `RetainerSubscription`, and `RefundRequest`.

The single exception is `ProgressCheckin`, which is an append-only audit record: a `ProgressCheckin` carries only `id` and `created_at`. It has no `updated_at` field and no `version` field. The one mutation a check-in undergoes — a clinician setting its `tracking_assessment` — is treated as recording an assessment on an immutable submission rather than versioned editing, so neither field appears.

### 2.5. Logical Clock

All time-dependent behaviour reads a server logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any explicit set it never falls back to real time. An administrative test-driving capability advances the clock to a supplied UTC instant, and the value it carries is the `to_iso8601` field. Installment due dates, delinquency-sweep eligibility, shipment windows, intake capture timestamps, and projected ship dates are all evaluated against this logical clock.

### 2.6. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Every calculation that produces a fractional cent is rounded half-up to the nearest whole cent — that is, a value exactly halfway between two integers rounds away from zero to the larger magnitude. Where a calculation is described as having pinned evaluation order, the rounding occurs at each pinned step as described in Section 3, and intermediate results are carried as already-rounded integer cents into the next step. Counts (such as step counts and installment counts) are integers and are never rounded because they are never fractional.

### 2.7. Optimistic Concurrency on Guarded Writes

Two write operations are guarded by optimistic concurrency control, each requiring the client to submit the version it last observed of a parent resource so that the server can reject a write founded on a stale view.

Opening a refund request requires the field `expected_case_version`, carrying the client's last observed `version` of the target `TreatmentCase`. If that value does not match the case's current `version`, the open is rejected with `ERR_STALE_CASE_VERSION` (HTTP 412). The canonical situation this prevents: a refinement grant has just raised the case's `total_contracted_cents` and bumped the case `version`, so a refund opened from the pre-refinement view would otherwise compute against an outdated contracted amount; the version check rejects the stale request rather than letting it overwrite a posture the client never saw.

Activating a financing plan requires the field `expected_financing_plan_version`, carrying the client's last observed `version` of the target `FinancingPlan`. If that value does not match the plan's current `version`, activation is rejected with `ERR_STALE_FINANCING_VERSION` (HTTP 412). This guards the case where the plan's terms were amended — a fresh `down_payment_cents` or `apr_bps` write bumped the plan `version` — after the activating client loaded it; activating against the stale version would amortize the wrong principal.

No other endpoint accepts a version field; only these two creates/activations carry an `expected_*_version` input, and supplying it elsewhere has no defined effect.

### 2.8. Hierarchical Consistency and Cascades

Many operations mutate more than one resource. Whenever a transition changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented; the same holds for every secondary resource a cascade touches. Cascades are described in full in the workflow narratives of Section 3 — for example, settling a refund drives the case to `REFUNDED`, cancels outstanding shipments, voids unstarted steps, cancels any financing plan, and waives its scheduled installments, all within the one settling request. The ledger fields on a case (`amount_collected_cents`, `outstanding_principal_cents` on the financing plan, `refund_issued_cents`, `total_contracted_cents`, `planned_step_count`, `refinement_count`) are maintained by these side effects rather than written directly by clients.

### 2.9. Nested Resource Retrieval

Endpoints whose paths nest one resource under another validate the path left-to-right. For a path such as a plan's or a case's nested collection, the outermost path identifier is resolved first; if any path-referenced resource does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404) before inner identifiers or the body are examined. Reverse-reachability list endpoints (the steps, check-ins, refinements, intake records, and installments belonging to a parent) resolve their parent identifier the same way.

### 2.10. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then authorization (`ERR_UNAUTHORIZED`), then existence of path-referenced resources (`ERR_NOT_FOUND`), then existence of body foreign keys (`ERR_FK_NOT_FOUND`), then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`), then the optimistic-concurrency version check on guarded writes (`ERR_STALE_CASE_VERSION` or `ERR_STALE_FINANCING_VERSION`). Only after all of those pass are the domain-specific business rules of Section 3 evaluated. A malformed body — a missing required field, an unrecognised enum value, or a type mismatch — is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a business-rule violation with no more specific code is rejected with the generic `ERR_VALIDATION` (HTTP 422). The body foreign keys that participate in the existence check at this stage include `case_id`, `financing_plan_id`, `step_id`, `triggering_checkin_id`, `patient_id`, and `author_clinician_id`.

## 3. Business Logic & Workflows

### 3.1. Actors, Patients, and Clinicians

A `Patient` record is registered with a contact `email`, a `full_name`, a two-letter US `state_code`, and a `date_of_birth` given as an ISO date. The `email` must be non-empty and unique across all patients, and `state_code` must be two uppercase letters. The patient's `state_code` is consequential: it gates which clinicians may review the case, because teledentistry is licensed per state. A derived boolean, `is_minor_at_intake`, marks whether the patient was under 18 at the moment the case's intake was captured; it is computed from `date_of_birth` against the intake record's `captured_at` instant — true when the patient's age at that instant is less than 18 — and defaults to false until an intake exists. This flag drives guardian-consent gating later in the lifecycle.

A `Clinician` is onboarded with a `full_name`, an array of `license_state_codes` (a non-empty array of two-letter codes), a `role_type` that is one of `DENTIST` or `ORTHODONTIST`, and an `active` flag indicating whether they currently accept assignments, which defaults to true when omitted. A plan may only be reviewed for a patient whose `state_code` appears in the reviewing clinician's `license_state_codes`.

When a case is submitted for clinical review, the system selects the assigned clinician automatically. The candidate set is every clinician whose `active` is true and whose `license_state_codes` contains the patient's `state_code`. Among those candidates, the system ranks by current open-case load ascending and chooses the least-loaded clinician, where a clinician's open load is the number of treatment cases assigned to them whose `status` is any of `UNDER_REVIEW`, `PLAN_APPROVED`, `ACTIVE`, or `REFINEMENT`. Cases that have reached `INTAKE_PENDING`, `DECLINED`, `COMPLETED`, or `REFUNDED` do not count toward load. Ties on load are broken by choosing the clinician with the earliest `created_at` (the earliest-onboarded); because `created_at` is unique per clinician, no further tiebreak is needed. If the candidate set is empty — no active, suitably-licensed clinician exists — submission is rejected with `ERR_NO_ELIGIBLE_CLINICIAN` (HTTP 422) and the case remains in `INTAKE_PENDING`.

### 3.2. Case Creation and Intake

A `TreatmentCase` is created for a patient by supplying `patient_id`, an `intake_channel` of either `IMPRESSION_KIT` or `IN_OFFICE_SCAN`, and a `list_price_cents` (the sticker price quoted at creation, which must be at least 0). A new case begins life in `INTAKE_PENDING`. Its `assigned_clinician_id` is null until review begins. The computed ledger fields all start at their defaults: `total_contracted_cents` is 0 until the plan is approved, `amount_collected_cents` is 0, `refund_issued_cents` is 0, `refinement_count` is 0, and `planned_step_count` is 0. The `guardian_consent` flag defaults to false.

Impressions reach the case as one or more `IntakeRecord` entries. An intake record references its parent through `case_id` and carries a `channel` (again `IMPRESSION_KIT` or `IN_OFFICE_SCAN`), a `quality_score` between 0.0 and 1.0 inclusive graded on upload, and one of two channel-specific fields. The record's `captured_at` is set to the current logical clock at the moment the intake is registered. The intake `channel` must equal the parent case's `intake_channel`; a mismatch is rejected with `ERR_CHANNEL_MISMATCH` (HTTP 422). Additionally, the channel-specific field is mandatory: when the channel is `IMPRESSION_KIT`, the carrier `kit_tracking_number` of the returned kit is required (and `scan_clinic_state_code` is unused), while when the channel is `IN_OFFICE_SCAN`, the `scan_clinic_state_code` (the US state of the partner clinic that performed the scan) is required (and `kit_tracking_number` is unused); the absent required field yields `ERR_INTAKE_FIELDS_INCOMPLETE` (HTTP 422).

For a minor patient, guardian consent is recorded separately by setting the case's `guardian_consent` flag to the supplied boolean value. This is an ordinary case mutation and may be performed before the plan is approved.

### 3.3. Submitting for Review and the Usability Gate

Before a clinician can look at a case, the patient submits it for review, which moves the case from `INTAKE_PENDING` to `UNDER_REVIEW`. Two preconditions guard this transition. First, the case must currently be in `INTAKE_PENDING`; a case already past intake cannot be resubmitted, and a wrong-state attempt is an `ERR_INVALID_STATE` (HTTP 409). Second, the case must hold at least one intake record whose `channel` equals the case's `intake_channel` and whose `quality_score` is at least the minimum usable quality of 0.60; if no intake meets that bar, the submission is rejected with `ERR_INTAKE_NOT_USABLE` (HTTP 422), because the images are clinically unusable. When both pass, the assignment selector of Section 3.1 runs and sets `assigned_clinician_id`; if it finds no eligible clinician, the submission fails with `ERR_NO_ELIGIBLE_CLINICIAN` and the case stays in `INTAKE_PENDING`.

### 3.4. Plan Authoring and the Review Loop

A `TreatmentPlan` is authored against an under-review case. Creating a plan supplies `case_id`, the `author_clinician_id` of the authoring clinician, a `proposed_step_count` (the number of aligner steps the plan would manufacture, at least 1), a `weeks_per_step` (the wear duration per step in weeks, at least 1, which drives shipment cadence and the projected end date), and an optional `discount_code`. A fresh plan is created in `DRAFT` with its `revision` set to 1.

The plan moves through a cyclic review loop. Submitting a draft advances it from `DRAFT` to `SUBMITTED`. A submitted plan may be sent back from `SUBMITTED` to `CHANGES_REQUESTED`. A changed plan is then resubmitted from `CHANGES_REQUESTED` back to `SUBMITTED`, and on each such resubmission the plan's `revision` is incremented by one; the resubmission may carry updated values for `proposed_step_count`, `weeks_per_step`, or `discount_code`. This loop may repeat any number of times, with `revision` advancing each cycle. Every one of these transitions — submit, request-changes, and resubmit — requires that the plan's case is `UNDER_REVIEW` where applicable and that the acting clinician's `id` equals the case's `assigned_clinician_id`; an acting clinician who is not the assigned one, or who is not licensed in the patient's `state_code` (their `license_state_codes` must contain it), is rejected with `ERR_CLINICIAN_NOT_LICENSED` (HTTP 422). Submission specifically requires the plan to be in `DRAFT` and the case in `UNDER_REVIEW`; request-changes requires the plan in `SUBMITTED`; resubmission requires the plan in `CHANGES_REQUESTED`. The clinician-licensing check guards plan submission, plan approval, and eligibility decline alike.

A plan's `status` is one of `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED`, `APPROVED`, or `ELIGIBILITY_DECLINED`. The two outcomes that close the loop — approval and eligibility decline — are described next.

### 3.5. Approval: Pricing, Step Generation, and Guardian Consent

Approving a submitted plan is the pivotal event of the case lifecycle. It is permitted only when the plan is `SUBMITTED`, the plan's case is `UNDER_REVIEW`, and the acting clinician's `id` equals the case's `assigned_clinician_id`. One safety gate applies here specifically: if the patient is a minor at intake (`is_minor_at_intake` is true) and the case's `guardian_consent` is not true, approval is rejected with `ERR_GUARDIAN_CONSENT_REQUIRED` (HTTP 422); a minor's case cannot reach `PLAN_APPROVED` without recorded guardian consent.

On approval, the case moves from `UNDER_REVIEW` to `PLAN_APPROVED`, the plan's `status` becomes `APPROVED`, and three computations settle atomically. First, the contracted price is computed and written to `total_contracted_cents` (see the pricing rule below). Second, the system generates a number of `AlignerStep` rows equal to the plan's `proposed_step_count`, each in `PLANNED` status with `step_index` running 1 through N, and sets the case's `planned_step_count` to that count. Third, each step's projected `scheduled_ship_at` is computed as the case's approval time plus `(step_index − 1)` multiplied by `weeks_per_step` weeks — so step 1 projects to the approval instant, step 2 to one wear interval later, and so on.

**Case price.** The contracted total is built in a pinned order from the case's `list_price_cents`, its `intake_channel`, and the approved plan's `proposed_step_count` and `discount_code`. Begin with the list price as the base. If the case's `intake_channel` is `IN_OFFICE_SCAN`, add an in-office scan surcharge of 25000 cents to the base; an impression-kit case adds nothing. Next, select a complexity multiplier from the proposed step count: a count of 14 or fewer is the LIGHT tier with a multiplier of 0.80; a count from 15 through 28 inclusive is the MODERATE tier with a multiplier of 1.00; a count of 29 or more is the COMPLEX tier with a multiplier of 1.35. Multiply the surcharge-adjusted base by the selected multiplier and round that product half-up to whole cents — this rounding happens after the multiply and before any discount. Finally, apply the promo discount keyed on this post-tier total: a `discount_code` of `WELCOME15` discounts 15 percent of the tiered total, rounded half-up to whole cents; a `discount_code` of `FLAT200` discounts a flat 20000 cents; any other code, or no code, discounts nothing. The contracted total is the tiered total minus the discount, floored at 0 so it never goes negative. The evaluation order is fixed: compute the tiered total first, then select the discount band from that tiered total, then subtract.

### 3.6. Eligibility Decline and the Refund Cascade

Instead of approving, a clinician may decline the case on clinical-eligibility grounds. Declining requires the plan to be `SUBMITTED` and the acting clinician to be the assigned, suitably-licensed reviewer (otherwise `ERR_CLINICIAN_NOT_LICENSED`). On decline, the plan's `status` becomes `ELIGIBILITY_DECLINED`, the case moves from `UNDER_REVIEW` to `DECLINED`, and the system automatically opens a `RefundRequest` against the case with `reason` set to `ELIGIBILITY_DECLINE` — a cascade one level deep that spares the patient from having to file the refund themselves. Refund computation and settlement are covered in Section 3.11.

### 3.7. Financing: Activation, Amortization, and Delinquency

A `FinancingPlan` is a monthly-pay arrangement created against a case by supplying `case_id`, a `term_months` of 12, 24, or 36, a `down_payment_cents` (at least 0), and an `apr_bps` annual percentage rate in basis points (at least 0, e.g. 1499 means 14.99 percent). A financing plan carries two parallel lifecycle dimensions that evolve independently on the same row. The first, `billing_state`, tracks the schedule and is one of `PENDING_ACTIVATION`, `ACTIVE`, `PAID_OFF`, or `CANCELLED`, beginning at `PENDING_ACTIVATION`. The second, `delinquency_state`, tracks payment health and is one of `CURRENT`, `DELINQUENT`, or `DEFAULTED`, beginning at `CURRENT`. The plan also carries computed `financed_principal_cents` and `outstanding_principal_cents`, both starting at 0.

Activation moves `billing_state` from `PENDING_ACTIVATION` to `ACTIVE`. It is permitted only when the plan's case is `PLAN_APPROVED` and the `down_payment_cents` does not exceed the case's `total_contracted_cents`; a down payment larger than the contracted total is rejected with `ERR_DOWN_PAYMENT_EXCEEDS_TOTAL` (HTTP 422). Activation is additionally guarded by optimistic concurrency on the plan as described in Section 2.7 — the request must carry `expected_financing_plan_version` matching the plan's current `version`, or it fails with `ERR_STALE_FINANCING_VERSION`. On a successful activation, the system sets `financed_principal_cents` to the case's `total_contracted_cents` minus the `down_payment_cents`, posts the down payment by adding `down_payment_cents` to the case's `amount_collected_cents`, generates the installment schedule, and sets `outstanding_principal_cents` equal to `financed_principal_cents`. Activation also increments the plan's `version` by one.

**Amortization.** Activation generates `term_months` `Installment` rows from the financed principal in a pinned order so that the scheduled amounts total exactly the financed principal plus all interest. Let the principal be `financed_principal_cents` and the count be `term_months`. The decimal monthly rate is the `apr_bps` divided by 10000 and then divided by 12. When the monthly rate is zero, the base payment is the principal divided by the number of installments, rounded half-up to whole cents — a straight-line schedule with no interest portion. When the monthly rate is positive, the base payment is the standard amortized payment: the principal multiplied by the factor formed by taking the monthly rate times the quantity (one plus the monthly rate) raised to the power of the term, divided by the quantity (one plus the monthly rate) raised to the power of the term minus one — and that base payment is rounded half-up to whole cents. Each of installments 1 through the second-to-last carries this base payment as its `amount_cents`. The principal and interest split is computed by declining balance in sequence: for each installment, the interest portion is the running balance multiplied by the monthly rate, rounded half-up to whole cents; the `principal_portion_cents` is the base payment minus that interest; and the running balance is reduced by that principal portion before the next installment. The final installment is made to absorb the residual: its `amount_cents` is the financed principal plus the total interest minus the sum of the earlier installments' amounts, so that the schedule's principal portions sum exactly to the financed principal and no rounding drift accumulates. Each `Installment` carries a `sequence_no` numbered 1-based, a computed `due_at`, and a `status`.

Each installment's `due_at` is the activation datetime plus `sequence_no` calendar months. Installments begin `SCHEDULED` and may become `POSTED`, `LATE`, or `WAIVED`.

**Posting a payment.** A `BillingAdmin` posts the next installment, moving it from `SCHEDULED` (or `LATE`) to `POSTED`. Posting requires the plan's `billing_state` to be `ACTIVE` and requires every installment with a lower `sequence_no` to already be `POSTED` or `WAIVED`; an attempt to post while a lower-sequence installment is still `SCHEDULED` or `LATE` is rejected with `ERR_INSTALLMENT_OUT_OF_ORDER` (HTTP 422). On posting, the installment's `amount_cents` is added to the case's `amount_collected_cents`, and the installment's `principal_portion_cents` is subtracted from the plan's `outstanding_principal_cents`. If `outstanding_principal_cents` reaches 0, the plan bubbles up from `ACTIVE` to `PAID_OFF` and its `delinquency_state` is reset to `CURRENT`. The plan's `delinquency_state` is then recomputed (see below) — a cascade from posting to outstanding-principal recompute to delinquency recompute.

**Delinquency sweep.** A delinquency sweep examines the plan's `SCHEDULED` installments and moves each one whose `due_at` plus a grace period of 5 days is at or before the current logical clock from `SCHEDULED` to `LATE`, then recomputes `delinquency_state`.

**Delinquency state.** The delinquency state is decided from the count of installments on the plan currently in `LATE` status (installments in `POSTED` or `WAIVED` are not counted). When the late count is 0, the state is `CURRENT`. When the late count is 1 or 2, the state is `DELINQUENT`. When the late count is 3 or more — the default threshold being 3 — the state is `DEFAULTED`. This recomputation behaves differently depending on its trigger: evaluated after a payment posts (when a formerly-late installment has cleared), the recount of remaining late installments may move the plan back from `DELINQUENT` toward `CURRENT`, a genuine recovery; evaluated during a sweep, it can only add late installments, so the state monotonically worsens toward `DEFAULTED` until a payment posts.

When the last installment posts and outstanding principal reaches 0, the plan transitions from `ACTIVE` to `PAID_OFF` and `delinquency_state` is set to `CURRENT`, as noted above.

### 3.8. Manufacturing and Shipment

Once the money side of a case is settled, manufacturing begins. Activating a case moves it from `PLAN_APPROVED` to `ACTIVE` and is permitted only when the money side is settled — that is, the case has a financing plan whose `billing_state` is `ACTIVE`, or the case's `amount_collected_cents` is at least its `total_contracted_cents`. An activation attempt that meets neither condition is rejected with `ERR_PAYMENT_NOT_SETTLED` (HTTP 422). On activation, the step at `step_index` 1 moves from `PLANNED` to `IN_PRODUCTION`.

An `AlignerStep` carries a `case_id`, a 1-based `step_index`, a `status` of `PLANNED`, `IN_PRODUCTION`, `MANUFACTURED`, `SHIPPED`, or `VOID`, a `supersedes_step_id` (null for first-run steps; for refinement-generated steps it points at the original step the new one replaces), and the computed `scheduled_ship_at`. Steps manufacture strictly in order. Starting production on a step moves it from `PLANNED` to `IN_PRODUCTION` and is allowed only when the case is `ACTIVE` or `REFINEMENT` and the immediately-prior `step_index` step (if there is one) is already `SHIPPED`; starting a step while its predecessor has not shipped is rejected with `ERR_STEP_ORDER_VIOLATION` (HTTP 422). Completing production moves a step from `IN_PRODUCTION` to `MANUFACTURED`.

A `Shipment` carries the manufactured step it transports via `step_id` (a cross-aggregate reference, since the shipment lives outside the case's own tree), a `carrier_code` of `GROUND` or `EXPRESS`, a `window_start`, a `window_end`, and a `status` of `BOOKED`, `IN_TRANSIT`, `DELIVERED`, or `CANCELLED`. Booking a shipment requires the referenced step to be `MANUFACTURED` and creates the shipment in `BOOKED`. The carrier window must be valid and non-conflicting:

- The `window_start` must be strictly before `window_end`; an inverted or empty window is rejected with `ERR_WINDOW_INVERTED` (HTTP 422).
- For `GROUND` shipments, the windows booked for the same step are treated as half-open intervals from `window_start` inclusive to `window_end` exclusive; two such windows for the same step must not overlap, though touching endpoints (one window's end equal to another's start) are allowed. An overlap is rejected with `ERR_GROUND_WINDOW_OVERLAP` (HTTP 409).
- For `EXPRESS` shipments, the windows booked for the same step are treated as closed intervals from `window_start` to `window_end` inclusive, so even touching endpoints collide; additionally, an express buffer of 24 hours must separate express windows on the same step — a new express window whose `window_start` is less than 24 hours after a prior express window's `window_end` is rejected. Either condition yields `ERR_EXPRESS_WINDOW_OVERLAP` (HTTP 409).

Dispatching a booked shipment moves it from `BOOKED` to `IN_TRANSIT` and, across the aggregate boundary, moves the referenced step from `MANUFACTURED` to `SHIPPED`; the dispatch requires the referenced step to be `MANUFACTURED`. When a step ships, the next `PLANNED` step (if any) becomes eligible to start production. Marking a shipment delivered moves it from `IN_TRANSIT` to `DELIVERED`. Cancelling a shipment is permitted from `BOOKED` or `IN_TRANSIT`, sets the shipment to `CANCELLED`, and — if the referenced step had been moved to `SHIPPED` solely by this shipment — reverts that step from `SHIPPED` back to `MANUFACTURED`.

### 3.9. Progress Check-ins and Refinement

While wearing trays, a patient submits a `ProgressCheckin` against a case, carrying the `reported_step_index` they currently report wearing (at least 1) and a `photo_quality_score` between 0.0 and 1.0 inclusive for the submitted photo. A new check-in's `tracking_assessment` is `PENDING`. A clinician later assesses the check-in, setting `tracking_assessment` to either `ON_TRACK` or `OFF_TRACK`. A check-in is an append-only record, so it carries no `version` or `updated_at`.

When teeth are tracking off plan, a mid-course correction is requested. A `RefinementRequest` cites the case via `case_id`, names the justifying check-in via `triggering_checkin_id`, and specifies an `additional_step_count` of extra steps (at least 1). A request begins in `REQUESTED`, and its `is_billable` flag defaults to false until decided at grant time. A refinement may be denied, moving it from `REQUESTED` to `DENIED`, or granted.

Granting a refinement re-opens an active case, moving it from `ACTIVE` to `REFINEMENT`, and is permitted only when the case is `ACTIVE`, the refinement is `REQUESTED`, and the triggering check-in belongs to this case and has a `tracking_assessment` of `OFF_TRACK`; a grant whose triggering check-in is not on this case or is not off-track is rejected with `ERR_REFINEMENT_NOT_JUSTIFIED` (HTTP 422). On grant, the refinement's `status` becomes `GRANTED`, the case's `refinement_count` is incremented, and the system generates `additional_step_count` new `AlignerStep` rows in `PLANNED`, each with its `supersedes_step_id` set to the matching original step it replaces, and bumps the case's `planned_step_count` accordingly.

**Refinement fee.** Whether a granted refinement is billable is decided from the case's `refinement_count` read before this grant increments it. The case includes one free refinement: when the pre-increment `refinement_count` is at least 1 (the included allotment of 1 having already been consumed), the refinement's `is_billable` is set true and a refinement fee of 30000 cents is appended to the case ledger, raising the case's `total_contracted_cents` by that fee — a cascade one level deep. When the pre-increment `refinement_count` is below 1, the refinement is free, `is_billable` stays false, and no fee is added. In effect, the first granted refinement is free and the second granted refinement is the first billable one.

After the refinement steps progress, a case is resumed from `REFINEMENT` back to `ACTIVE`. Resume is permitted only when the case is `REFINEMENT` and every refinement-generated step for the case is in one of `PLANNED`, `IN_PRODUCTION`, `MANUFACTURED`, or `SHIPPED`; on resume the lowest-`step_index` `PLANNED` refinement step moves to `IN_PRODUCTION`. Because a case can re-enter refinement, this is a cyclic loop: `ACTIVE → REFINEMENT → ACTIVE`, possibly several times.

### 3.10. Completion and Retainers

A case is completed by moving it from `ACTIVE` to `COMPLETED`. Completion requires the case to be `ACTIVE`, every non-`VOID` `AlignerStep` for the case to be `SHIPPED`, and the latest `ProgressCheckin` for the case to have a `tracking_assessment` of `ON_TRACK`. Both `COMPLETED` and `REFUNDED` are terminal postures for a case.

After completion, the patient may start a `RetainerSubscription`, supplying `case_id`, a `cadence` of `QUARTERLY` or `SEMIANNUAL`, and a `per_shipment_fee_cents` charge per retainer shipment (at least 0). A subscription may only be created for a case in `COMPLETED` status; an attempt to start one for any other case status is rejected with `ERR_CASE_NOT_COMPLETED` (HTTP 422). A new subscription is `ACTIVE`, and its `next_ship_at` is set to the current logical clock advanced by one cadence interval. The subscription's `status` is one of `ACTIVE`, `PAUSED`, or `CANCELLED`. The patient may pause it (from `ACTIVE` to `PAUSED`), resume it (from `PAUSED` back to `ACTIVE`, which advances `next_ship_at` by one cadence interval from the current clock), or cancel it (from `ACTIVE` or `PAUSED` to the terminal `CANCELLED`).

### 3.11. Refunds and Settlement

A `RefundRequest` is opened against a case by supplying `case_id`, a `reason` of `ELIGIBILITY_DECLINE`, `PATIENT_CANCEL`, or `GOODWILL`, and the `expected_case_version` for the optimistic-concurrency check of Section 2.7. A refund begins in `OPEN`, with `computed_refund_cents` and `restocking_fee_cents` both at 0. Opening a refund increments the case's `version` by one. (Eligibility-decline refunds are opened automatically by the system as described in Section 3.6.)

A `BillingAdmin` works the refund through its lifecycle. Approving it moves it from `OPEN` to `APPROVED` and is permitted only when the refund is `OPEN` and the case's `status` is one of `DECLINED`, `PLAN_APPROVED`, or `ACTIVE`; at approval the refund and restocking amounts are computed (see below). A refund may instead be rejected, moving it from `OPEN` to the terminal `REJECTED`. An approved refund is then settled, moving it from `APPROVED` to `SETTLED`, permitted only when the refund is `APPROVED` and the case's `status` is one of `DECLINED`, `PLAN_APPROVED`, or `ACTIVE`.

**Refund amount.** The refund and restocking amounts depend on the `reason` and on case progress, measured over first-run steps only (refinement steps, which carry a non-null `supersedes_step_id`, are excluded). When the reason is `ELIGIBILITY_DECLINE`, the refund is the full `amount_collected_cents` on the case and the `restocking_fee_cents` is 0 — the case never became deliverable, so everything collected comes back with no fee. When the reason is `GOODWILL`, the refund is likewise the full `amount_collected_cents` with a `restocking_fee_cents` of 0. When the reason is `PATIENT_CANCEL`, the refund is pro-rated: let the shipped fraction be the count of first-run steps (those with a null `supersedes_step_id`) currently `SHIPPED` divided by the count of non-`VOID` first-run steps (guaranteed to be at least 1 once a plan is approved); the consumed value is the case's `total_contracted_cents` multiplied by that shipped fraction, rounded half-up to whole cents; the `restocking_fee_cents` is a flat 7500 cents; and `computed_refund_cents` is the `amount_collected_cents` minus the consumed value minus the restocking fee, floored at 0 so it never goes negative. Because a patient-cancel withholds both consumed value and the restocking fee, an identical amount collected yields a strictly smaller refund than the eligibility-decline variant.

**Settlement cascade.** Settling an approved refund drives the case to `REFUNDED` and unwinds the case atomically within the settling request. The case's `refund_issued_cents` is set to the refund's `computed_refund_cents` and the case's `status` becomes `REFUNDED`. Every non-`DELIVERED` shipment for the case's steps is cancelled, and every `PLANNED` or `IN_PRODUCTION` `AlignerStep` for the case is voided — moved to `VOID` with the case's `planned_step_count` decremented for each. If a financing plan exists for the case, its `billing_state` is set to `CANCELLED` and all of its `SCHEDULED` (and `LATE`) installments are marked `WAIVED`. The full chain is: settle → case `REFUNDED` → financing `CANCELLED` → installments `WAIVED`, with shipments cancelled and unstarted steps voided along the way. (A pure decline-then-settle, where the case is `DECLINED` and no manufacturing ever started, simply sets `refund_issued_cents` and moves the case to `REFUNDED`.) Note that an `AlignerStep` may also be voided by a plan superseding it; in both the refund-settle and supersede paths, a step in `PLANNED` or `IN_PRODUCTION` becomes `VOID` and the case's `planned_step_count` is decremented.

## 4. Endpoint Definitions

All endpoints share the response envelope of Section 2.2. Endpoints that create a brand-new resource return HTTP 201; endpoints that modify, transition, or read an existing resource return HTTP 200. Request bodies, the fields each endpoint expects, and the side effects each triggers are described in the workflow narratives of Section 3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/patients` | Register a patient. | Patient, BillingAdmin |
| GET | `/patients/{id}` | Fetch a patient. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| POST | `/clinicians` | Onboard a clinician. | BillingAdmin |
| GET | `/clinicians/{id}` | Fetch a clinician. | Clinician, BillingAdmin, ManufacturingOps |
| POST | `/cases` | Create a treatment case for a patient. | Patient, BillingAdmin |
| GET | `/cases/{id}` | Fetch a case with computed ledger fields. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| GET | `/cases` | List/filter cases. | Clinician, BillingAdmin, ManufacturingOps |
| POST | `/cases/{id}/intake-records` | Upload an intake record (impression kit or in-office scan). | Patient, ManufacturingOps |
| GET | `/cases/{id}/intake-records` | List intake records for a case. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| POST | `/cases/{id}/guardian-consent` | Record guardian consent for a minor patient's case. | Patient, BillingAdmin |
| POST | `/cases/{id}/submit-for-review` | Submit a case for clinical review; assigns a clinician. | Patient |
| POST | `/cases/{id}/activate` | Activate manufacturing once the money side is settled. | ManufacturingOps |
| POST | `/cases/{id}/resume` | Resume an in-refinement case back to active manufacturing. | ManufacturingOps |
| POST | `/cases/{id}/complete` | Mark a case complete when all steps shipped and tracking on-track. | Clinician |
| GET | `/cases/{id}/aligner-steps` | List aligner steps for a case. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| GET | `/cases/{id}/checkins` | List progress check-ins for a case. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| GET | `/cases/{id}/refinements` | List refinement requests for a case. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| POST | `/plans` | Author a draft treatment plan for an under-review case. | Clinician |
| GET | `/plans/{id}` | Fetch a plan. | Clinician, BillingAdmin, Patient |
| GET | `/plans` | List plans, filterable by case. | Clinician, BillingAdmin, Patient |
| POST | `/plans/{id}/submit` | Submit a draft plan for the assigned clinician's review. | Clinician |
| POST | `/plans/{id}/request-changes` | Send a submitted plan back for changes (review loop). | Clinician |
| POST | `/plans/{id}/resubmit` | Resubmit a changed plan; advances revision. | Clinician |
| POST | `/plans/{id}/approve` | Approve a submitted plan, pricing the case and generating aligner steps. | Clinician |
| POST | `/plans/{id}/decline-eligibility` | Decline a case on clinical eligibility grounds; opens a refund. | Clinician |
| GET | `/aligner-steps/{id}` | Fetch an aligner step. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| GET | `/aligner-steps` | List aligner steps, filterable by case or superseded step. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| POST | `/aligner-steps/{id}/start-production` | Begin manufacturing a planned step (strict in-order). | ManufacturingOps |
| POST | `/aligner-steps/{id}/complete-production` | Finish manufacturing a step. | ManufacturingOps |
| POST | `/shipments` | Book a shipment for a manufactured step within a carrier window. | ManufacturingOps |
| GET | `/shipments/{id}` | Fetch a shipment. | Patient, ManufacturingOps, BillingAdmin |
| GET | `/shipments` | List shipments, filterable by step. | Patient, ManufacturingOps, BillingAdmin |
| POST | `/shipments/{id}/dispatch` | Dispatch a booked shipment; ships the step. | ManufacturingOps |
| POST | `/shipments/{id}/mark-delivered` | Mark an in-transit shipment delivered. | ManufacturingOps |
| POST | `/shipments/{id}/cancel` | Cancel a shipment; reverts the step if it was shipped solely by this shipment. | ManufacturingOps |
| POST | `/cases/{id}/checkins` | Submit a progress check-in with a photo quality score. | Patient |
| POST | `/checkins/{id}/assess` | Clinician sets the tracking assessment on a check-in. | Clinician |
| GET | `/checkins/{id}` | Fetch a check-in. | Patient, Clinician, BillingAdmin, ManufacturingOps |
| POST | `/refinements` | Request a mid-course correction citing an off-track check-in. | Patient |
| GET | `/refinements/{id}` | Fetch a refinement request. | Patient, Clinician, BillingAdmin |
| GET | `/refinements` | List refinement requests, filterable by case or triggering check-in. | Patient, Clinician, BillingAdmin |
| POST | `/refinements/{id}/grant` | Grant a refinement; generates correction steps and may add a billable fee. | Clinician |
| POST | `/refinements/{id}/deny` | Deny a refinement request. | Clinician |
| POST | `/financing-plans` | Create a monthly-pay financing plan for an approved case. | Patient, BillingAdmin |
| GET | `/financing-plans/{id}` | Fetch a financing plan. | Patient, BillingAdmin |
| GET | `/financing-plans` | List financing plans, filterable by case. | Patient, BillingAdmin |
| POST | `/financing-plans/{id}/activate` | Activate a financing plan; amortizes principal into installments. | BillingAdmin |
| GET | `/financing-plans/{id}/installments` | List installments for a plan. | Patient, BillingAdmin |
| POST | `/financing-plans/{id}/installments/{seq}/post-payment` | Post a monthly installment payment (in-order). | BillingAdmin |
| POST | `/financing-plans/{id}/run-delinquency-sweep` | Sweep overdue installments to LATE and recompute delinquency. | BillingAdmin |
| POST | `/refunds` | Open a refund request against a case. | Patient, BillingAdmin |
| GET | `/refunds/{id}` | Fetch a refund request. | Patient, BillingAdmin |
| GET | `/refunds` | List refunds, filterable by case. | Patient, BillingAdmin |
| POST | `/refunds/{id}/approve` | Approve a refund; computes refund and restocking amounts. | BillingAdmin |
| POST | `/refunds/{id}/reject` | Reject a refund request. | BillingAdmin |
| POST | `/refunds/{id}/settle` | Settle an approved refund; drives the case to REFUNDED with full cascade. | BillingAdmin |
| POST | `/retainers` | Start a retainer subscription for a completed case. | Patient, BillingAdmin |
| GET | `/retainers/{id}` | Fetch a retainer subscription. | Patient, BillingAdmin |
| GET | `/retainers` | List retainer subscriptions, filterable by case. | Patient, BillingAdmin |
| POST | `/retainers/{id}/pause` | Pause a retainer subscription. | Patient |
| POST | `/retainers/{id}/resume` | Resume a paused retainer subscription. | Patient |
| POST | `/retainers/{id}/cancel` | Cancel a retainer subscription. | Patient |
| POST | `/_clock/set_current_utc` | Set the server logical clock to an explicit UTC instant. | BillingAdmin, ManufacturingOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_FK_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_CASE_VERSION | 412 |
| ERR_STALE_FINANCING_VERSION | 412 |
| ERR_CHANNEL_MISMATCH | 422 |
| ERR_INTAKE_FIELDS_INCOMPLETE | 422 |
| ERR_INTAKE_NOT_USABLE | 422 |
| ERR_NO_ELIGIBLE_CLINICIAN | 422 |
| ERR_CLINICIAN_NOT_LICENSED | 422 |
| ERR_GUARDIAN_CONSENT_REQUIRED | 422 |
| ERR_REFINEMENT_NOT_JUSTIFIED | 422 |
| ERR_STEP_ORDER_VIOLATION | 422 |
| ERR_GROUND_WINDOW_OVERLAP | 409 |
| ERR_EXPRESS_WINDOW_OVERLAP | 409 |
| ERR_WINDOW_INVERTED | 422 |
| ERR_DOWN_PAYMENT_EXCEEDS_TOTAL | 422 |
| ERR_INSTALLMENT_OUT_OF_ORDER | 422 |
| ERR_PAYMENT_NOT_SETTLED | 422 |
| ERR_CASE_NOT_COMPLETED | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_VALIDATION | 422 |

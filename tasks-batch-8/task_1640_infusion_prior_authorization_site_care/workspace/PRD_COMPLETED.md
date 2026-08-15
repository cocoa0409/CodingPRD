# Infusion Prior Authorization API — Product Requirements Document

## 1. Introduction

Infusion therapy sits at one of the most authorization-heavy intersections of outpatient care. Every regimen must clear a payer's prior-authorization rules, the clinical evidence on file must answer policy-specific criteria, the benefit channel — medical versus pharmacy — determines how the drug is procured and billed, and payer steering policies increasingly push clinically appropriate infusions out of hospital outpatient departments and into home and office settings. When any of these steps is mishandled, the provider absorbs a denied claim and the patient inherits a surprise bill.

This document specifies the Infusion Prior Authorization & Site-of-Care Steering API, mounted under `/infusion`, which manages that lifecycle end to end: payer policy configuration and authorization-requirement lookup, patient intake with plan accumulators, authorization request drafting and submission, clinical criteria review, benefit investigation with buy-and-bill routing, site-of-care steering determinations, medical determinations guarded by optimistic concurrency, multi-level appeals with peer-to-peer review, financial clearance built on a patient-responsibility estimate, chair scheduling inside the authorization validity window, and dose changes that may force re-authorization. All time-driven behavior — authorization expiry, missed appointments, completed infusions, peer-to-peer no-shows — is governed by a logical clock that tests can advance deterministically.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. The system recognizes five roles, spelled exactly as follows: `PolicyAdmin`, `AuthCoordinator`, `MedicalDirector`, `FinanceSpecialist`, and `Scheduler`. A request missing either header (an empty header value counts as missing), or carrying a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-formed request whose role is not listed among the endpoint's authorized roles is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Each role owns a distinct slice of the workflow. A `PolicyAdmin` administers payer policies and infusion chairs and operates the test clock. An `AuthCoordinator` owns intake, submission, criteria, appeals, and dose changes. A `MedicalDirector` records determinations, reviews criteria, decides appeals, and runs peer-to-peer calls. A `FinanceSpecialist` verifies benefits and manages financial clearance. A `Scheduler` books, confirms, and cancels chair appointments.

All five roles are opaque identities. When `X-User-Role` is `PolicyAdmin`, `AuthCoordinator`, `MedicalDirector`, `FinanceSpecialist`, or `Scheduler`, the accompanying `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it against any entity's `id`. The server does, however, record it on the resources the operator touches — as `created_by_user_id` on authorization requests and criteria submissions, as `decided_by_user_id` on authorization determinations, appeals, and dose-change decisions, as `reviewed_by_user_id` on criteria reviews, as `verified_by_user_id` on benefit investigations, and as `estimated_by_user_id` and `cleared_by_user_id` on financial clearances — and the segregation-of-duties checks in §2.8 compare those recorded identifiers against the caller's `X-User-ID`.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter states how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1–100 range, or a negative `offset` is rejected with `ERR_VALIDATION_FAILED` (400). Unless otherwise specified, list endpoints return resources sorted by creation timestamp in ascending order, with ties broken by creation (insertion) order. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope; `has_more` is true exactly when `offset` plus the number of items returned in the page is less than `total_count`.

### 2.4. The Logical Clock and Time-Driven Transitions

The system runs on a logical clock rather than wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and there is no wall-clock fallback. Every timestamp the server assigns — `submitted_at`, `pended_at`, `denied_at`, the computed validity-window bounds, and every `created_at` / `updated_at` — reads this clock. A `PolicyAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`. Setting the clock synchronously applies every time-based transition whose trigger has fired: an `APPROVED` authorization whose `auth_valid_to` now lies in the past becomes `EXPIRED`; a `CONFIRMED` appointment whose `scheduled_end` has been reached becomes `COMPLETED`; a `SCHEDULED` appointment still unconfirmed sixty minutes past its `scheduled_start` becomes `MISSED`; and a peer-to-peer call still `SCHEDULED` thirty minutes past its `scheduled_end` becomes `NO_SHOW`.

### 2.5. Common Resource Properties

Every resource in this API carries the same set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation. The `version` field is an integer, 1 at creation, that increments by exactly one on every mutation of the resource, including mutations applied by system cascades and clock-driven transitions. No resource in this domain omits `updated_at` or `version`.

### 2.6. Monetary Values, Scores, and Rounding Discipline

All monetary amounts — policy reference values, patient accumulators, allowed amounts, billed charges, line-item shares, and the responsibility estimate — are integer cents; no fractional cent ever persists. Rounding follows the round-half-up method everywhere it occurs. The patient-responsibility waterfall rounds per line item to whole cents and only then sums the per-line shares. A `discount_rate` multiplication applied to billed charges rounds half-up to whole cents before entering the waterfall. The `steer_score` produced by a site-of-care determination is rounded half-up to three decimal places. The `delta_pct` computed for a dose change is rounded half-up to two decimal places.

### 2.7. Optimistic Concurrency Control on Determinations

Recording a medical determination against an authorization request is the one write in the system guarded by optimistic concurrency control. The request body must carry `expected_authorization_version`, a non-optional field holding the client's last observed `version` of the authorization request. If the request's current `version` does not equal that value — typically because another writer has already recorded a determination, or the coordinator has resubmitted the request — the write is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from deciding a request it has not observed. No other endpoint accepts a version field; every other mutation proceeds without an OCC check.

### 2.8. Segregation of Duties

Three steps in the workflow are forbidden to the operator who originated the record under review. First, the `MedicalDirector` recording a determination on an authorization request must not be the operator recorded as that request's `created_by_user_id`. Second, the `MedicalDirector` reviewing a clinical criteria submission must not be the coordinator recorded as that submission's `created_by_user_id`. Third, the `FinanceSpecialist` clearing a financial clearance must not be the specialist recorded as its `estimated_by_user_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and the check applies to exactly three capabilities: recording a determination, reviewing a criteria submission, and clearing a financial clearance.

### 2.9. Validation Pipeline and Nested Resource Resolution

Validation runs as a fixed pipeline, and an earlier failure masks every later check. The stages, in order, are:

1. **Authentication** — both headers present and the role declared, otherwise `ERR_UNAUTHENTICATED` (401).
2. **Role authorization** — the acting role is listed for the endpoint, otherwise `ERR_UNAUTHORIZED_ROLE` (403).
3. **Request-body shape** — required fields present, enum values valid, datetime fields parseable, and wherever a time window is supplied the `scheduled_end` strictly after the `scheduled_start`; violations carry `ERR_VALIDATION_FAILED` (400).
4. **Resource existence** — path- and body-referenced resources are resolved left to right (patient, policy, authorization request, appeal, criteria submission, clearance, line item, chair, appointment, dose-change request, benefit investigation, peer-to-peer review), and the first missing reference yields that resource's dedicated 404: `ERR_PATIENT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_AUTH_REQUEST_NOT_FOUND`, `ERR_CRITERIA_SUBMISSION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_P2P_NOT_FOUND`, `ERR_BENEFIT_INVESTIGATION_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`, `ERR_LINE_ITEM_NOT_FOUND`, `ERR_CHAIR_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, or `ERR_DOSE_CHANGE_NOT_FOUND`. A request targeting a line item under a clearance that does not exist therefore fails with `ERR_CLEARANCE_NOT_FOUND` before the line item is ever examined.
5. **Segregation of duties** — per §2.8, `ERR_SEGREGATION_OF_DUTIES` (403).
6. **State preconditions and cross-entity state gates** — the parent-approval gate surfaces as `ERR_AUTH_NOT_APPROVED` (409) on appointment booking, dose-change creation, clearance creation, and clearance recompute; every other from-state violation, including any write aimed at a resource in a terminal state, surfaces as `ERR_INVALID_STATE` (409). These two checks share the same rank.
7. **Dose ceiling** — `ERR_DOSE_EXCEEDS_MAX` (422).
8.–10. **Submission referential gates** — verified benefit (`ERR_BENEFIT_NOT_VERIFIED`), accepted criteria (`ERR_MISSING_REQUIRED_CRITERIA`), then site-determination presence (`ERR_SITE_DETERMINATION_MISSING`), each 422 and evaluated in that order.
11.–12. **Open-record uniqueness** — `ERR_DUPLICATE_OPEN_APPEAL` before `ERR_DUPLICATE_OPEN_CLEARANCE`, both 409.
13. **Benefit routing** — `ERR_ROUTING_VIOLATION` (422).
14. **Clearance-cleared gate** — `ERR_CLEARANCE_NOT_CLEARED` (422).
15.–16. **Temporal gates** — the authorization validity window (`ERR_OUTSIDE_VALIDITY_WINDOW`, 422) before the appeal deadline (`ERR_APPEAL_WINDOW_CLOSED`, 422).
17.–20. **Constraint checks** — chair site match (`ERR_SITE_NOT_ALLOWED`, 422), chair schedule overlap (`ERR_CHAIR_SCHEDULE_CONFLICT`, 409), reviewer slot overlap (`ERR_REVIEWER_SLOT_CONFLICT`, 409), then policy uniqueness (`ERR_DUPLICATE_POLICY`, 409).
21. **Prepay limit** — `ERR_PREPAY_LIMIT_EXCEEDED` (402).
22. **Optimistic concurrency** — the `ERR_STALE_VERSION` (412) check on determinations runs last of all.

### 2.10. Cascading State Consistency

Several operations mutate more than one aggregate, and the cascades are part of the contract. An appeal decided or resolved in the member's favor moves the parent authorization request from `DENIED` to `APPROVED` and recomputes its validity window from the decision date; an appeal upheld at the external level, or upheld through a peer-to-peer call, moves the parent from `DENIED` to `DENIED_CLOSED`. Approving a dose change that requires re-authorization supersedes the parent request and cancels its future appointments — a depth-3 cascade from the decision, to the request, to each appointment — while the request's clearance stays on hold. Creating such a dose-change request in the first place places the request's open clearance on hold. Advancing the logical clock applies the auto-transitions enumerated in §2.4. Every step of every cascade is an independent mutation: each resource a cascade touches has its `version` incremented by one and its `updated_at` refreshed.

## 3. Business Logic & Workflows

### 3.1. Payer Policy Configuration and Requirement Lookup

Everything in the system is downstream of a payer policy, so configuration comes first. A `PolicyAdmin` authors a policy by supplying the `payer_code` and `drug_code` pair that identifies what the policy governs, plus a human-readable `regimen_name`. The combination of `payer_code` and `drug_code` is unique across the system: attempting to author a second policy with a pair already on file is rejected with `ERR_DUPLICATE_POLICY` (409). Policies are assumed to require prior authorization unless `requires_prior_auth` is explicitly set false on creation.

The policy's `benefit_channel` declares which benefit the regimen pays under — `MEDICAL`, `PHARMACY`, or `EITHER`. When `buy_and_bill_required` is true (it defaults to false), the provider must procure the drug under the medical channel, and a later pharmacy-channel verification is refused as a routing violation (§3.3). Authorization longevity is governed by `validity_days` for the medical channel and `pharmacy_validity_days` for the pharmacy channel, the latter defaulting to 30 days, while `max_course_days` caps the total course of therapy regardless of channel. Patient safety is anchored by `max_dose_mg`, an absolute ceiling on any single dose. Financial behavior is shaped by `allowed_amount_known` (default true), which selects the estimation method described in §3.6; by the `discount_rate` (default 0.80) applied to billed charges when allowed amounts are not published; and by the reference values `deductible_cents`, `coinsurance_pct`, and `oop_max_cents`. The `prepay_limit_cents` value is the ceiling a patient's estimate must not exceed at clearance time. Site-of-care posture lives in `site_policy`, one of `NO_STEERING` (the default), `STEER_TO_HOME`, or `STEER_TO_OFFICE`, paired with `steer_threshold` (default 1.50), the score at or above which steering fires.

Any authorized role may run the authorization-requirement lookup, passing a `payer_code` and a `drug_code` as query parameters (a call missing either is rejected with `ERR_VALIDATION_FAILED`); the response carries the matching policy's `policy_id`, `requires_prior_auth`, `benefit_channel`, `validity_days`, `pharmacy_validity_days`, `max_dose_mg`, `site_policy`, and `buy_and_bill_required`. When no policy matches the pair, the lookup is rejected with `ERR_POLICY_NOT_FOUND`.

### 3.2. Patient Intake and Drafting the Authorization Request

An `AuthCoordinator` registers each patient with the payer's `member_id`, the patient's `full_name`, the primary `diagnosis_code` (ICD-10), and the `payer_code` the patient is enrolled with. Intake also captures the plan-year boundary `plan_year_end` — which later caps any authorization validity window — and the patient's live accumulators, `deductible_remaining_cents` and `oop_remaining_cents`, which drive the responsibility estimate. Two geography fields steer the site-of-care score: `rural_resident` (default false) selects which scoring variant applies, and `travel_minutes_to_hospital` (default 0) measures the one-way drive to the hospital outpatient department.

With a patient and a policy in place, the coordinator drafts an authorization request by providing the `patient_id`, the governing `policy_id`, the ordering provider's `requested_site_type` (`HOME`, `OFFICE`, or `HOSPITAL_OUTPATIENT`), the `requested_dose_mg`, and the intake `patient_weight_kg`. A dose above the policy's `max_dose_mg` ceiling is rejected on the spot with `ERR_DOSE_EXCEEDS_MAX` (422). When the draft is a re-authorization replacing an earlier, superseded request, the coordinator sets `supersedes_request_id` to the replaced request; the field is otherwise omitted. Any existing request may be named in `supersedes_request_id`, regardless of its status. The new request is born in `DRAFT` status with the creating operator recorded in `created_by_user_id`. Referenced resources must exist: an unknown patient yields `ERR_PATIENT_NOT_FOUND`, an unknown policy `ERR_POLICY_NOT_FOUND`, and an unknown `supersedes_request_id` `ERR_AUTH_REQUEST_NOT_FOUND`. The request collection supports filtering by `patient_id`, `policy_id`, `status`, and `supersedes_request_id`, alongside the standard `limit` and `offset` pagination parameters; a `status` filter value outside the declared request-status set is rejected with `ERR_VALIDATION_FAILED` (400).

### 3.3. Clinical Evidence, Benefit Verification, and Site-of-Care Steering

Three evidentiary workstreams hang off a draft request, and all three must be satisfied before submission.

A coordinator answers policy criteria by filing criteria submissions, each carrying the `criterion_code` being answered and a `response_value` documenting the clinical evidence, and each recording the `authorization_request_id` it belongs to. A submission is born `SUBMITTED` with the filer in `created_by_user_id`. A `MedicalDirector` then reviews it with an `outcome` of `ACCEPTED` or `REJECTED`; the reviewer must differ from the filer per §2.8, and the reviewer is recorded in `reviewed_by_user_id`. Both outcomes are terminal — a `REJECTED` criterion is corrected by filing a new submission, never by reopening the old one, and the pend-and-resubmit cycle in §3.4 depends on that freshness.

The benefit workstream opens when a coordinator starts a benefit investigation on the request, born `INITIATED`. A `FinanceSpecialist` verifies it by declaring the `determined_channel` as `MEDICAL` or `PHARMACY`. When the governing policy's `buy_and_bill_required` is true, a `PHARMACY` verification is rejected with `ERR_ROUTING_VIOLATION` (422) — the drug must be procured buy-and-bill under the medical benefit. Successful verification stamps `VERIFIED` (a terminal state), derives the `routing` as `BUY_AND_BILL` for a medical channel or `SPECIALTY_PHARMACY` for a pharmacy channel, and records the specialist in `verified_by_user_id`.

The third workstream is the site-of-care steering determination, run by a `MedicalDirector`, who supplies four amounts: `home_allowed_cents` and `hospital_allowed_cents` (plan allowed amounts) plus `home_billed_cents` and `hospital_billed_cents` (provider billed charges). The computation first derives a burden index from the patient's `travel_minutes_to_hospital`, clamped into the range 0 to 120 minutes and expressed as a fraction of that 120-minute cap — a patient forty-five minutes from the hospital contributes 0.375. Which cost ratio feeds the score then depends on the patient. For a non-rural patient (`rural_resident` false), the `COST_RATIO` variant divides `hospital_allowed_cents` by `home_allowed_cents`, and the `steer_score` is that ratio at full weight plus the burden index at half weight, rounded half-up to three decimal places. For a rural resident, the `TRAVEL_BURDEN` variant instead divides `hospital_billed_cents` by `home_billed_cents`, and the score is that ratio plus the burden index — both terms at full weight — again rounded half-up to three decimal places; identical inputs therefore yield a different `steer_score` under the two variants. If the divisor of the applicable cost ratio is zero, the ratio contributes 0 to the score. The determination records which variant fired in `score_variant`.

What the score does depends on the policy's `site_policy`. Under `NO_STEERING`, the recommendation is always the requested site: `recommended_site_type` equals the request's `requested_site_type` and `steered` is false. Under a steering posture, a `steer_score` at or above the policy's `steer_threshold` pushes the recommendation to the policy's target — `HOME` under `STEER_TO_HOME`, `OFFICE` under `STEER_TO_OFFICE` — and `steered` is true exactly when that recommendation differs from the requested site. Below the threshold, the recommendation falls back to the requested site with `steered` false.

### 3.4. Submission, Determination, and the Authorization Validity Window

Submitting a `DRAFT` request moves it to `SUBMITTED` and passes three gates, evaluated in this order: at least one benefit investigation of the request must be `VERIFIED` (otherwise `ERR_BENEFIT_NOT_VERIFIED`), at least one criteria submission must be `ACCEPTED` (otherwise `ERR_MISSING_REQUIRED_CRITERIA`), and at least one site-of-care determination must exist (otherwise `ERR_SITE_DETERMINATION_MISSING`). A successful submission stamps `submitted_at` from the logical clock and increments the request's `version` by one. Submitting from any other state — apart from the resubmission of a `PENDED` request described below — is rejected with `ERR_INVALID_STATE`.

Once `SUBMITTED`, a `MedicalDirector` records a determination whose `outcome` is `APPROVED`, `DENIED`, or `PENDED`, carrying the `expected_authorization_version` required by §2.7. The segregation check of §2.8 fires before the stale-version check: a decider who created the request is refused with `ERR_SEGREGATION_OF_DUTIES`, and a version mismatch is refused with `ERR_STALE_VERSION`. All three outcomes record the decider in `decided_by_user_id` and increment `version` by one.

Approval fixes the authorization validity window. The `auth_valid_from` bound is the decision date truncated to midnight — 00:00:00Z of that day. The window's base length is the policy's `validity_days`, or its `pharmacy_validity_days` when the policy's `benefit_channel` is `PHARMACY`. The `auth_valid_to` bound is the earliest of three instants: `auth_valid_from` plus the base length in days, the patient's `plan_year_end`, and `auth_valid_from` plus the policy's `max_course_days` in days. The window is a closed interval: an appointment satisfies it when its `scheduled_start` falls on or after `auth_valid_from` and on or before `auth_valid_to`; either bound exactly is acceptable. Approval also copies `requested_dose_mg` into `approved_dose_mg`.

A denial requires a `denial_reason` in the determination payload; the system stamps `denied_at` from the logical clock and sets `appeal_deadline` to sixty days after that instant. A pend stamps `pended_at` and returns the request to the coordinator for more evidence. Resubmitting a `PENDED` request carries one decisive gate: at least one `ACCEPTED` criteria submission created after `pended_at` — stale acceptances from before the pend do not count, and without a fresh one the resubmission is rejected with `ERR_MISSING_REQUIRED_CRITERIA`. A successful resubmission re-stamps `submitted_at` and increments `version`.

Two system transitions round out the lifecycle. When the logical clock advances past `auth_valid_to`, an `APPROVED` request becomes `EXPIRED`, incrementing `version`. The `SUPERSEDED` and `DENIED_CLOSED` terminals arrive by cascade — through dose-change approval (§3.8) and appeal resolution (§3.5) respectively — and `SUPERSEDED`, `EXPIRED`, and `DENIED_CLOSED` are terminal: any further write against a request in one of those states is rejected with `ERR_INVALID_STATE`.

### 3.5. Appeals, Escalation, and Peer-to-Peer Review

A coordinator may open an appeal on a `DENIED` request by supplying a `reason`; the request's status is a hard gate, and attempting the write against a request in any other state is rejected with `ERR_INVALID_STATE`. Two further gates apply. The appeal must be opened on or before the request's `appeal_deadline`; a later attempt is rejected with `ERR_APPEAL_WINDOW_CLOSED` (422). And at most one appeal per request may be open at a time: if another appeal exists in any status other than `CLOSED_UPHELD` or `CLOSED_OVERTURNED`, creation is rejected with `ERR_DUPLICATE_OPEN_APPEAL` (409). A new appeal is born at `LEVEL_1`. Note that a lapsed `appeal_deadline` does not close the underlying request — it merely blocks new appeals; the only path from `DENIED` to `DENIED_CLOSED` runs through an appeal that reaches `CLOSED_UPHELD`.

A `MedicalDirector` decides the appeal at its current level with an `outcome` of `UPHELD` or `OVERTURNED`. At `LEVEL_1`, an `UPHELD` decision moves the appeal to `LEVEL_1_DECIDED`, recording `decided_by_user_id` and incrementing `version`. An `OVERTURNED` decision at `LEVEL_1` closes the appeal as `CLOSED_OVERTURNED` and cascades: the parent request moves `DENIED` → `APPROVED`, its validity window is recomputed from the decision date exactly as in §3.4, and the request's `version` increments by one. The same two outcomes exist at `LEVEL_2` with equal weight: `UPHELD` yields `LEVEL_2_DECIDED` with `decided_by_user_id` recorded, and `OVERTURNED` closes the appeal as `CLOSED_OVERTURNED` with the identical request-approval cascade. Between levels, a coordinator escalates: from `LEVEL_1_DECIDED` to `LEVEL_2`, and from `LEVEL_2_DECIDED` to `EXTERNAL_REVIEW`, each incrementing `version`. At `EXTERNAL_REVIEW`, an `UPHELD` decision closes the appeal as `CLOSED_UPHELD` and cascades the parent request `DENIED` → `DENIED_CLOSED` with a version increment, while an `OVERTURNED` decision closes it as `CLOSED_OVERTURNED` with the same approval cascade as the earlier levels.

A peer-to-peer call can be scheduled by a `MedicalDirector` on an appeal resting at a decided level — `LEVEL_1_DECIDED` or `LEVEL_2_DECIDED`; attempting it at any other appeal status is rejected with `ERR_INVALID_STATE`. The scheduling payload names the `reviewer_user_id` whose calendar the call occupies — the payer medical director on the other end of the line — plus a `scheduled_start` and `scheduled_end` that form a closed interval (the body-validation stage still requires the end strictly after the start), and the call is recorded against its `appeal_id`. The new review is born `SCHEDULED` with `reschedule_count` zero. Calendar integrity is enforced per reviewer: the proposed window must not overlap any other review booked for the same `reviewer_user_id` that is not yet `COMPLETED`, and because the intervals are closed, windows that merely touch at an endpoint still conflict; violations are rejected with `ERR_REVIEWER_SLOT_CONFLICT` (409).

Rescheduling moves a `SCHEDULED` review to a new window (a self-loop back to `SCHEDULED`) or revives a `NO_SHOW` review back to `SCHEDULED`. Two preconditions guard it: the review's `reschedule_count` must be below two before the call — the third attempt is rejected with `ERR_P2P_RESCHEDULE_LIMIT` (409) — and the new window must survive the same closed-interval conflict check, evaluated against the reviewer's other reviews that are not yet `COMPLETED`. A successful reschedule replaces `scheduled_start` and `scheduled_end`, increments `reschedule_count` by one, and increments `version`. If the logical clock advances thirty minutes past a `SCHEDULED` call's `scheduled_end` with no completion recorded, the system marks the call `NO_SHOW`.

Completing a `SCHEDULED` call records an `outcome` of `UPHOLD` or `OVERTURN`, moves the review to `COMPLETED`, and cascades. An `UPHOLD` outcome moves an appeal resting at `LEVEL_1_DECIDED` or `LEVEL_2_DECIDED` to `CLOSED_UPHELD`; an `OVERTURN` outcome moves it to `CLOSED_OVERTURNED` — in both cases, from either decided level, with equal effect. If the appeal has left the decided levels by the time the call completes, the completion stands but the appeal (and therefore the request) is left untouched. The appeal's own cascade then moves the authorization request: a closed-upheld appeal drives `DENIED` → `DENIED_CLOSED`, while a closed-overturned appeal drives `DENIED` → `APPROVED` with the validity window recomputed from that decision date. The chain from call completion, to appeal closure, to request resolution is a single synchronous transaction, and every resource it touches increments `version` per §2.10.

### 3.6. Financial Clearance and the Patient Responsibility Estimate

Once a request is `APPROVED`, a `FinanceSpecialist` opens a financial clearance on it; attempting to open one against a request in any other status is rejected with `ERR_AUTH_NOT_APPROVED` (409). Uniqueness is enforced across open records: if the request already has a clearance in `ESTIMATED` or `CLEARED` status, creation is rejected with `ERR_DUPLICATE_OPEN_CLEARANCE` (409). The new clearance's `method` is derived from the policy — `ACCUMULATOR_METHOD` when the policy's `allowed_amount_known` is true, `BILLED_CHARGES_METHOD` when false — its status is born `ESTIMATED`, the opening specialist is recorded in `estimated_by_user_id`, and an initial estimate is computed immediately over zero line items. Each clearance records the `authorization_request_id` it belongs to.

Responsibility line items are the estimate's raw material. A specialist adds a line with a `description` (drug, administration, supplies), the plan's `allowed_amount_cents` for the line, and the provider's `billed_charges_cents`; each line carries the `financial_clearance_id` of its parent clearance and is born `ACTIVE` with a computed `patient_share_cents`. Lines may be added only while the clearance is `ESTIMATED`, and only an `ACTIVE` line may be voided; writes against a clearance in another status, or against an already-`VOIDED` line, are rejected with `ERR_INVALID_STATE`. Voiding flips the line to `VOIDED`, and both additions and voids recompute the clearance estimate.

The estimate itself is a deductible-then-coinsurance waterfall, rebuilt from scratch at clearance creation, on every line-item addition or void, and on every recompute. Only `ACTIVE` line items participate, processed in creation order, oldest first. The patient's `deductible_remaining_cents` is copied into a running deductible balance (a negative accumulator is treated as zero) — a snapshot for the computation; the patient record is never mutated. For each line, a base amount is established first: under `ACCUMULATOR_METHOD` the base is the line's `allowed_amount_cents`; under `BILLED_CHARGES_METHOD` the base is the line's `billed_charges_cents` multiplied by the policy's `discount_rate`, rounded half-up to whole cents. The deductible applied to the line is the smaller of that base and the remaining deductible balance, and the running balance is reduced by the applied amount. The line's coinsurance is whatever remains of the base after the deductible application, multiplied by the policy's `coinsurance_pct`, rounded half-up to whole cents. The line's `patient_share_cents` is the applied deductible plus the coinsurance — rounding happens per line, and only then are the per-line shares summed, in the same pinned order. The clearance's `estimated_patient_responsibility_cents` is the smaller of that sum and the patient's `oop_remaining_cents`. Because the two methods differ only in how the base is derived, identical line inputs yield a different estimate whenever billed charges and allowed amounts diverge; the policy's `deductible_cents` and `oop_max_cents` remain plan reference values and do not enter this waterfall.

Clearing is a deliberate second-person act. A `FinanceSpecialist` other than the one recorded in `estimated_by_user_id` performs it — same-operator clears are rejected with `ERR_SEGREGATION_OF_DUTIES` — and two business gates apply: at least one benefit investigation of the parent request must be `VERIFIED` (otherwise `ERR_BENEFIT_NOT_VERIFIED`), and the current `estimated_patient_responsibility_cents` must not exceed the policy's `prepay_limit_cents` (otherwise `ERR_PREPAY_LIMIT_EXCEEDED`, HTTP 402). A successful clear moves the clearance to `CLEARED`, records the clearer in `cleared_by_user_id`, and increments `version`; `CLEARED` is terminal.

One more status exists for dose-change turbulence. When a dose-change request requiring re-authorization is created on the parent request (§3.8), the request's `ESTIMATED` clearance cascades to `ON_HOLD` with a version increment. An `ON_HOLD` clearance returns to `ESTIMATED` through a recompute, which a `FinanceSpecialist` may invoke once the parent request is `APPROVED` again — reachable after the dose change is rejected — and attempting it while the parent is anything else is rejected with `ERR_AUTH_NOT_APPROVED`. Invoking the recompute on a clearance in any status other than `ON_HOLD` is rejected with `ERR_INVALID_STATE`, a check that fires before the parent-approval gate. The recompute rebuilds the estimate per the waterfall and increments `version`.

### 3.7. Chair Scheduling and the Appointment Lifecycle

Infusion chairs are configured by a `PolicyAdmin` with the `site_type` the chair belongs to (`HOME`, `OFFICE`, or `HOSPITAL_OUTPATIENT`), a human-readable `label`, and a `turnover_buffer_minutes` cleaning buffer — defaulting to fifteen minutes — that is appended to each appointment's end for overlap purposes.

A `Scheduler` books an infusion on an `APPROVED` request by naming a `chair_id` and the infusion's `scheduled_start` and `scheduled_end`. Booking enforces a stack of gates: the parent request must be `APPROVED` (otherwise `ERR_AUTH_NOT_APPROVED`); the window bounds must be sane, with `scheduled_end` strictly after `scheduled_start` (otherwise `ERR_VALIDATION_FAILED`); the `scheduled_start` must fall inside the closed validity window of §3.4 (otherwise `ERR_OUTSIDE_VALIDITY_WINDOW`); and the chair's `site_type` must equal the `recommended_site_type` of the request's latest site-of-care determination — the one with the greatest `created_at`, ties broken in favor of the most recently created — and a request with no site-of-care determination at all also fails this gate (otherwise `ERR_SITE_NOT_ALLOWED`, 422).

Chair occupancy is a conserved quantity. The occupied count of a chair is the number of its appointments in `SCHEDULED`, `CONFIRMED`, or `COMPLETED` status, and every booking or cancellation keeps that count honest — a cancellation releases the occupation and decreases the count by one. Overlap is judged on buffered, half-open intervals: a new appointment occupies the interval from its `scheduled_start` up to but not including its `scheduled_end` extended by the chair's `turnover_buffer_minutes`. The booking conflicts with any existing appointment on the same chair whose status is neither `CANCELLED` nor `MISSED` when the new start falls before the existing appointment's buffered end and the existing start falls before the new appointment's buffered end; such a booking is rejected with `ERR_CHAIR_SCHEDULE_CONFLICT` (409). Back-to-back adjacency — a new start exactly equal to an existing buffered end — is permitted.

Confirmation is the second checkpoint. A `Scheduler` confirms a `SCHEDULED` appointment only when the parent request is still `APPROVED` (`ERR_AUTH_NOT_APPROVED` otherwise), when the request's financial clearance is `CLEARED` — the selector is the request's unique clearance in `ESTIMATED` or `CLEARED` status, at most one of which can exist per the duplicate-open-clearance rule, so an `ON_HOLD` clearance fails this gate with `ERR_CLEARANCE_NOT_CLEARED` (422) — and when `scheduled_start` still satisfies the closed validity window (`ERR_OUTSIDE_VALIDITY_WINDOW` otherwise). Confirmation moves the appointment to `CONFIRMED` and increments `version`.

From there, three endings exist. A `Scheduler` may cancel a `SCHEDULED` or `CONFIRMED` appointment, moving it to `CANCELLED` and releasing the chair occupation; the same `CANCELLED` landing also arrives by cascade when the parent request is superseded (§3.8). When the logical clock reaches the `scheduled_end` of a `CONFIRMED` appointment, the system marks it `COMPLETED`. When the clock advances sixty minutes past the `scheduled_start` of a `SCHEDULED` appointment that was never confirmed, the system marks it `MISSED`. `COMPLETED`, `CANCELLED`, and `MISSED` are all terminal.

### 3.8. Dose Changes and Re-Authorization

Mid-course dose changes are filed by an `AuthCoordinator` against an `APPROVED` request — any other parent status is rejected with `ERR_AUTH_NOT_APPROVED` — by supplying the proposed `new_dose_mg`, which must respect the policy's `max_dose_mg` ceiling just as the original dose did (violations carry `ERR_DOSE_EXCEEDS_MAX`). Creation computes two derived fields. The `delta_pct` is the absolute difference between `new_dose_mg` and the request's `approved_dose_mg`, divided by `approved_dose_mg`, multiplied by one hundred to express it as a percentage, and rounded half-up to two decimal places (an `approved_dose_mg` of zero yields a `delta_pct` of 0.00). The `reauth_required` flag is true when `delta_pct` reaches the re-authorization threshold of 20.00 — exactly 20.00 triggers re-authorization, while 19.99 does not. The request is born `PENDING`.

Creation has one immediate cascade: when `reauth_required` is true and the parent request has a clearance in `ESTIMATED` status (at most one can exist, per the duplicate-open-clearance rule), that clearance moves to `ON_HOLD` with a version increment, freezing financial clearance until the dose question resolves.

A `MedicalDirector` then decides the dose change with an `outcome` of `APPROVED` or `REJECTED`, recorded in `decided_by_user_id` with a version increment. Approval splits two ways. When `reauth_required` is true, the parent authorization request cascades `APPROVED` → `SUPERSEDED`; every appointment of that request still in `SCHEDULED` or `CONFIRMED` status whose `scheduled_start` lies after the current logical clock moves to `CANCELLED`, releasing each chair's occupation; and the request's clearance remains `ON_HOLD`. When `reauth_required` is false, approval simply writes `new_dose_mg` into the parent request's `approved_dose_mg` and increments the request's `version` — no re-authorization is needed for a sub-threshold adjustment. If the parent request is no longer `APPROVED` when an approval is decided, the decision is still recorded on the dose-change request but no cascade or dose write runs on the parent. Rejection leaves the parent request untouched in `APPROVED`, and the `ON_HOLD` clearance (if any) becomes eligible for the recompute described in §3.6. Either way, `APPROVED` and `REJECTED` are terminal for the dose-change request. The replacement authorization that follows a supersede is drafted as in §3.2, naming the superseded request in `supersedes_request_id`.

## 4. Endpoint Definitions

Operations that create a new resource — a policy, patient, authorization request, determination of record such as a site-of-care determination, benefit investigation, criteria submission, appeal, peer-to-peer review, financial clearance, line item, chair, appointment, or dose-change request — return `201 Created`. Operations that act on an existing resource without creating a new one — submissions, determinations, verifications, reviews, decisions, escalations, reschedules, completions, voids, clears, recomputes, confirms, cancels, and the clock advance — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/infusion/payer-policies` | Create a payer policy (unique `payer_code` + `drug_code`) | PolicyAdmin |
| GET | `/infusion/payer-policies/{id}` | Read a payer policy | PolicyAdmin, AuthCoordinator, MedicalDirector, FinanceSpecialist, Scheduler |
| POST | `/infusion/patients` | Register a patient with plan accumulators | AuthCoordinator |
| GET | `/infusion/patients/{id}` | Read a patient | PolicyAdmin, AuthCoordinator, MedicalDirector, FinanceSpecialist, Scheduler |
| GET | `/infusion/authorization-requirements/lookup` | Look up authorization requirements by `payer_code` + `drug_code` | PolicyAdmin, AuthCoordinator, MedicalDirector, FinanceSpecialist, Scheduler |
| POST | `/infusion/authorization-requests` | Create an authorization request in `DRAFT` | AuthCoordinator |
| GET | `/infusion/authorization-requests` | List authorization requests with filters and pagination | PolicyAdmin, AuthCoordinator, MedicalDirector, FinanceSpecialist, Scheduler |
| GET | `/infusion/authorization-requests/{id}` | Read one authorization request | PolicyAdmin, AuthCoordinator, MedicalDirector, FinanceSpecialist, Scheduler |
| POST | `/infusion/authorization-requests/{id}/submit` | Submit a `DRAFT` or resubmit a `PENDED` request | AuthCoordinator |
| POST | `/infusion/authorization-requests/{id}/determinations` | Record an `APPROVED` / `DENIED` / `PENDED` determination with OCC | MedicalDirector |
| POST | `/infusion/authorization-requests/{id}/site-of-care-determinations` | Run the site-of-care steering determination | MedicalDirector |
| GET | `/infusion/authorization-requests/{id}/site-of-care-determinations` | List site-of-care determinations of a request | MedicalDirector, AuthCoordinator, Scheduler |
| POST | `/infusion/authorization-requests/{id}/benefit-investigations` | Open a benefit investigation (medical vs pharmacy) | AuthCoordinator |
| GET | `/infusion/authorization-requests/{id}/benefit-investigations` | List benefit investigations of a request | AuthCoordinator, FinanceSpecialist, MedicalDirector |
| POST | `/infusion/benefit-investigations/{id}/verify` | Verify the benefit channel and derive buy-and-bill routing | FinanceSpecialist |
| POST | `/infusion/authorization-requests/{id}/criteria-submissions` | Submit a clinical criterion response | AuthCoordinator |
| GET | `/infusion/authorization-requests/{id}/criteria-submissions` | List criteria submissions of a request | AuthCoordinator, MedicalDirector |
| POST | `/infusion/criteria-submissions/{id}/reviews` | Accept or reject a criterion submission | MedicalDirector |
| POST | `/infusion/authorization-requests/{id}/appeals` | Open an appeal on a `DENIED` request within the appeal window | AuthCoordinator |
| GET | `/infusion/authorization-requests/{id}/appeals` | List appeals of a request | AuthCoordinator, MedicalDirector |
| GET | `/infusion/appeals/{id}` | Read one appeal | AuthCoordinator, MedicalDirector |
| POST | `/infusion/appeals/{id}/decisions` | Decide `UPHELD` / `OVERTURNED` at the current appeal level | MedicalDirector |
| POST | `/infusion/appeals/{id}/escalations` | Escalate `LEVEL_1_DECIDED` → `LEVEL_2` or `LEVEL_2_DECIDED` → `EXTERNAL_REVIEW` | AuthCoordinator |
| POST | `/infusion/appeals/{id}/peer-to-peer-reviews` | Schedule a peer-to-peer call on a decided appeal level | MedicalDirector |
| GET | `/infusion/appeals/{id}/peer-to-peer-reviews` | List peer-to-peer reviews of an appeal | MedicalDirector, AuthCoordinator |
| POST | `/infusion/peer-to-peer-reviews/{id}/reschedules` | Reschedule a `SCHEDULED` or `NO_SHOW` review (at most two reschedules) | MedicalDirector |
| POST | `/infusion/peer-to-peer-reviews/{id}/completions` | Complete a peer-to-peer call with outcome `UPHOLD` / `OVERTURN` | MedicalDirector |
| POST | `/infusion/authorization-requests/{id}/financial-clearances` | Open a financial clearance on an `APPROVED` request | FinanceSpecialist |
| GET | `/infusion/authorization-requests/{id}/financial-clearances` | List financial clearances of a request | FinanceSpecialist, AuthCoordinator |
| GET | `/infusion/financial-clearances/{id}` | Read one financial clearance | FinanceSpecialist, AuthCoordinator |
| POST | `/infusion/financial-clearances/{id}/line-items` | Add a responsibility line item to an `ESTIMATED` clearance | FinanceSpecialist |
| GET | `/infusion/financial-clearances/{id}/line-items` | List line items of a clearance | FinanceSpecialist, AuthCoordinator |
| POST | `/infusion/responsibility-line-items/{id}/voids` | Void an `ACTIVE` line item and recompute the estimate | FinanceSpecialist |
| POST | `/infusion/financial-clearances/{id}/clear` | Clear an `ESTIMATED` clearance (segregation of duties, prepay limit) | FinanceSpecialist |
| POST | `/infusion/financial-clearances/{id}/recompute` | Move `ON_HOLD` → `ESTIMATED` with a recomputed estimate | FinanceSpecialist |
| POST | `/infusion/infusion-chairs` | Create an infusion chair resource | PolicyAdmin |
| GET | `/infusion/infusion-chairs/{id}` | Read one infusion chair | PolicyAdmin, Scheduler, AuthCoordinator |
| GET | `/infusion/infusion-chairs/{id}/appointments` | List appointments occupying a chair | PolicyAdmin, Scheduler, AuthCoordinator |
| POST | `/infusion/authorization-requests/{id}/appointments` | Schedule an infusion within the validity window on a matching-site chair | Scheduler |
| GET | `/infusion/authorization-requests/{id}/appointments` | List appointments of a request | Scheduler, AuthCoordinator, MedicalDirector |
| POST | `/infusion/appointments/{id}/confirm` | Confirm a `SCHEDULED` appointment | Scheduler |
| POST | `/infusion/appointments/{id}/cancel` | Cancel a `SCHEDULED` or `CONFIRMED` appointment | Scheduler |
| POST | `/infusion/authorization-requests/{id}/dose-change-requests` | Request a dose change on an `APPROVED` authorization | AuthCoordinator |
| GET | `/infusion/authorization-requests/{id}/dose-change-requests` | List dose-change requests of a request | AuthCoordinator, MedicalDirector |
| POST | `/infusion/dose-change-requests/{id}/decisions` | Approve or reject a dose change | MedicalDirector |
| POST | `/infusion/_clock/set_current_utc` | Advance the test-driving logical clock | PolicyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_VALIDATION_FAILED` | 400 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_POLICY_NOT_FOUND` | 404 |
| `ERR_AUTH_REQUEST_NOT_FOUND` | 404 |
| `ERR_CRITERIA_SUBMISSION_NOT_FOUND` | 404 |
| `ERR_APPEAL_NOT_FOUND` | 404 |
| `ERR_P2P_NOT_FOUND` | 404 |
| `ERR_BENEFIT_INVESTIGATION_NOT_FOUND` | 404 |
| `ERR_CLEARANCE_NOT_FOUND` | 404 |
| `ERR_LINE_ITEM_NOT_FOUND` | 404 |
| `ERR_CHAIR_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_DOSE_CHANGE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_AUTH_NOT_APPROVED` | 409 |
| `ERR_DUPLICATE_POLICY` | 409 |
| `ERR_DUPLICATE_OPEN_APPEAL` | 409 |
| `ERR_DUPLICATE_OPEN_CLEARANCE` | 409 |
| `ERR_CHAIR_SCHEDULE_CONFLICT` | 409 |
| `ERR_REVIEWER_SLOT_CONFLICT` | 409 |
| `ERR_P2P_RESCHEDULE_LIMIT` | 409 |
| `ERR_MISSING_REQUIRED_CRITERIA` | 422 |
| `ERR_SITE_DETERMINATION_MISSING` | 422 |
| `ERR_BENEFIT_NOT_VERIFIED` | 422 |
| `ERR_CLEARANCE_NOT_CLEARED` | 422 |
| `ERR_DOSE_EXCEEDS_MAX` | 422 |
| `ERR_SITE_NOT_ALLOWED` | 422 |
| `ERR_OUTSIDE_VALIDITY_WINDOW` | 422 |
| `ERR_APPEAL_WINDOW_CLOSED` | 422 |
| `ERR_ROUTING_VIOLATION` | 422 |
| `ERR_PREPAY_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_VERSION` | 412 |

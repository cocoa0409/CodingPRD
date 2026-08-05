# Denture & Removable-Prosthetics Clinic API — Product Requirements Document

## 1. Introduction

A denture and removable-prosthetics clinic is not one workflow but several that run at different speeds and settle against each other only at the end. A clinician takes an impression or an intraoral scan, judges its quality, books a wax or framework try-in, ships the work to an external laboratory, receives it back, inspects it, delivers the finished appliance, and then lives with that appliance for years — adjusting it, relining it, repairing it, recalling the patient, and occasionally remaking it under warranty. In parallel, and on an entirely different calendar, the front office asks the carrier for a predetermination, submits a claim to a primary plan and then a secondary plan, strikes an installment plan for whatever the patient still owes, and chases that plan when it goes unpaid. The two calendars touch in exactly the places that hurt: a laboratory's workmanship failure becomes a credit against a patient's installment schedule; an unpaid balance freezes new fabrication but must never freeze the payment that would cure it; a remake restarts the clinical warranty while deliberately refusing to restart the insurance replacement clock.

This document specifies the REST API that runs that clinic. Every resource is mounted under `/prosthetics`. The system is deliberately opinionated about ordering: the order in which requests are refused, the order in which money is computed, the order in which cascading side effects fire, and the order in which installments absorb a credit are all pinned here, because in this domain two implementations that differ only in ordering will produce different numbers and different error codes for the same request.

Three structural commitments shape the rest of the document. First, a **per-arch** model: a case may cover the maxillary arch, the mandibular arch, or both, and each arch advances on its own clock, so one arch can be sitting in a remake while its sibling is already delivered. Second, a **parallel-axis** model on the delivered appliance: warranty and recall are two independent state axes carried on one row, and a movement on one never implies a movement on the other. Third, a **fiscal gate**: a patient whose installment plan has gone delinquent or defaulted is frozen out of new clinical starts, but never out of reading their record, never out of emergency repair, and never out of paying.

## 2. Global Specifications & System-Wide Principles

### 2.1. Clinic Identity and Role-Based Access Control

Every request to every endpoint must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, if `X-User-ID` is empty, or if `X-User-Role` does not name one of the six declared roles, the request is refused with `ERR_UNAUTHENTICATED` and HTTP 401. This is the first check the server performs on any request, ahead of everything else including resource lookup. When the headers are well-formed but the named role does not appear in the authorised-role list of the endpoint being called (§4 carries that list per endpoint), the request is refused with `ERR_FORBIDDEN_ROLE` and HTTP 403.

The six roles are `Prosthodontist`, `ClinicalDirector`, `LabTechnician`, `FrontOffice`, `Patient`, and `PlatformAdmin`, spelled exactly so.

- The `Prosthodontist` is the treating clinician and owns the clinical surface: exam close-out, arch planning, impressions, try-in decisions, clinic-side QC, delivery, post-delivery services, recall visits, and remake *requests*.
- The `ClinicalDirector` is the authorising clinician. It is the only role that may adjudicate a warranty fault or decide a remake request, and — by design — it is never permitted to decide a remake it itself requested.
- The `LabTechnician` is the external laboratory acting as itself.
- The `FrontOffice` owns billing and insurance: coverages, predeterminations, claims, payment plans, laboratory dispatch logistics, and payment reversals.
- The `Patient` acts on their own record only.
- The `PlatformAdmin` is an operator role. It owns laboratory registration, the delinquency sweep, and the logical clock, and performs no clinical work.

Two of these roles are entity-backed, meaning `X-User-ID` is the identifier of a persisted row:

- When `X-User-Role` is `LabTechnician`, `X-User-ID` is the `id` of the acting `DentalLab`; ownership checks on any resource that references a laboratory compare the resource's `dental_lab_id` to `X-User-ID`. Concretely, a laboratory may only receive a lab case that was dispatched to it.
- When `X-User-Role` is `Patient`, `X-User-ID` is the `id` of the acting `Patient`; ownership checks compare the patient reachable from the resource to `X-User-ID`. The ownership map resolves a patient row to its own `id`, a payment plan to its `patient_id`, an installment to its parent plan's `patient_id`, and a case to its `patient_id`.

The remaining four roles — `Prosthodontist`, `ClinicalDirector`, `FrontOffice`, and `PlatformAdmin` — are opaque. For each of them, `X-User-ID` is an operator identifier not tied to any persisted entity. The server records it where a transition says to (as `decided_by_user_id` on a try-in milestone, and as `requested_by_user_id` and `approved_by_user_id` on a remake request) but never compares it to any entity's `id`.

Ownership enforcement is a distinct, third check that runs after authentication and role authorisation and before any resource-existence check. It is enforced on exactly five endpoints:

- `GET /prosthetics/patients/{patient_id}`
- `GET /prosthetics/payment-plans/{payment_plan_id}`
- `GET /prosthetics/installments/{installment_id}`
- `POST /prosthetics/installments/{installment_id}/pay`
- `POST /prosthetics/lab-cases/{lab_case_id}/receive`

On the first four, a `Patient` caller whose `X-User-ID` is not the owning patient is refused. On the fifth, a `LabTechnician` whose `X-User-ID` differs from the lab case's `dental_lab_id` is refused. In every case the refusal is `ERR_NOT_OWNER` with HTTP 403. Callers in other roles are not subject to this check on these endpoints; their access is decided by the role list alone.

Segregation of duties is enforced on identity, not on role. Two different people may both hold `ClinicalDirector`; what the system forbids is the same `X-User-ID` both requesting and deciding the same remake. That check is described in §2.8 at its ladder position and again in §3.7 where it belongs to the workflow.

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

### 2.3. Pagination and List Ordering

Every list endpoint accepts two optional query parameters. `limit` defaults to 10 when omitted, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 when omitted and has a minimum of 0; there is no upper bound on it. A `limit` below 1 or above 100, or a negative `offset`, is a request-schema failure and is refused with `ERR_VALIDATION` and HTTP 400.

List results are ordered by `created_at` ascending. Because two rows minted inside the same cascade can carry the same `created_at`, ties are broken by `id` ascending so that pagination is stable across pages.

The `meta` block of a list response carries `limit` and `offset` echoing the effective values actually applied, `total_count` giving the number of rows matching the filters *before* the limit and offset window is applied, and `has_more`, which is true exactly when `offset` plus the number of returned rows is strictly less than `total_count`.

Filter query parameters, where an endpoint declares them, are combined with logical AND, and an omitted filter is simply not applied. The filters each list endpoint accepts are named in §3 alongside the workflow that needs them, and the full endpoint inventory is in §4.

### 2.4. Resource Identity, Versioning and Response Projection

Every resource type in this system — `Patient`, `Coverage`, `DentalLab`, `ProsthesisCase`, `CaseArch`, `ImpressionRecord`, `TryInMilestone`, `LabCase`, `Prosthesis`, `PostDeliveryService`, `WarrantyClaim`, `RemakeRequest`, `Predetermination`, `Claim`, `PaymentPlan`, and `Installment` — carries the same four common properties, without exception:

- `id`: a server-minted UUID. It carries no type prefix; it is a bare UUID string. Clients never supply it.
- `created_at`: the instant the row was created.
- `updated_at`: the instant the row was last mutated. At creation it equals `created_at`.
- `version`: an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row.

The `version` field is the backbone of the concurrency rules in §2.8 and of the cascade accounting in §2.13, so its granularity matters. One request may mutate several rows; each mutated row's `version` advances by exactly 1 for that request, regardless of how many individual fields on it changed. A row that a request merely reads does not advance. A row that a request writes twice inside one cascade still advances by 1 in total, not 2.

Response projection is post-commit. The body a mutating call returns is the state of the resource *after* the write has been applied, including the already-incremented `version` and the already-refreshed `updated_at`. A client that reads `version` out of a create or update response and then uses it as an expected-version input on a subsequent request must find it accepted.

Fields declared nullable are always present in the response body; when they have no value they are rendered as JSON `null` rather than omitted. Computed collection fields — `required_milestones` and `completed_milestones` on an arch — are always present as JSON arrays, empty rather than null when they hold nothing.

### 2.5. Timestamps and the Rendering of Instants

There is exactly one rendering convention for instants in this API, and it applies uniformly. **Every instant — server-written stamp, caller-supplied instant echoed back, or derived/computed instant — is rendered as an ISO 8601 UTC timestamp with exactly three fractional-second digits and a trailing `Z`, in the form `YYYY-MM-DDTHH:MM:SS.sssZ`.** There is no second convention and no field exempt from it.

That covers, without exception:

- Server-written stamps: `created_at`, `updated_at`, `reviewed_at`, `decided_at`, `dispatched_at`, `received_at`, `expired_at`, `completed_at`, `voided_at`, `adjudicated_at`, `determined_at`, `submitted_at`, `reversed_at`, `paid_at`, `delivered_at`, and `fabrication_started_at`.
- Caller-supplied instants echoed back: `effective_date` on a coverage and `first_due_date` on a payment plan are normalised into the canonical form on the way in, so a caller who submits `2026-05-01T00:00:00Z` reads back `2026-05-01T00:00:00.000Z`. The same normalisation applies to the clock-setting input.
- Derived and computed instants: `promised_due_at`, `shelf_life_expires_at`, `warranty_expires_at`, `frequency_anchor_at`, `replacement_eligible_date`, `recall_due_at`, `adjustment_window_ends_at`, `mandatory_reline_due_at`, `expires_at`, `due_date`, and `last_frequency_anchor_at`.

**Deadlines are instants, never end-of-day markers.** When a rule adds a whole number of calendar days or months to an anchor instant, the time-of-day component of the anchor is preserved exactly. A shelf life of 45 days computed from a dispatch at `2026-05-01T09:15:00.000Z` expires at `2026-06-15T09:15:00.000Z`, not at the end of that calendar day. Nothing in this specification snaps a deadline to midnight or to 23:59:59.

Calendar-month arithmetic (used by the replacement-frequency clock and the service-frequency limits) keeps the day-of-month and clamps to the last day of the target month when the target month is shorter: 60 months after `2026-03-31` lands on `2031-03-31`, and 1 month after `2026-01-31` would land on `2026-02-28`.

One field is deliberately not an instant: `date_of_birth` on a patient is a plain calendar date string in `YYYY-MM-DD` form and is stored and echoed exactly as supplied.

### 2.6. The Logical Clock

Nothing in this system reads the host machine's wall clock. Every window, ceiling, expiry, grace period, due date, overlap interval, and frequency limit described in this document is evaluated against a **logical clock** that the server holds.

Before any caller has set it, the logical clock reads exactly `2026-05-01T00:00:00.000Z`. It never falls back to real time, never drifts, and never advances on its own. A `PlatformAdmin` moves it by supplying a target instant as `to_iso8601`; the endpoint answers with the resulting clock in a `current_utc` field and HTTP 200.

Moving the clock has consequences on the next read of every clock-derived band, because three families of transition are evaluated lazily whenever the affected row is read or handled rather than being driven by any caller action: the warranty band on a delivered appliance, the recall band on that same appliance, and the expiry of an approved or alternate-benefit predetermination. Those three are described where they belong, in §3.6 and §3.8.

### 2.7. Money, Precision and Rounding

All monetary amounts are decimal numbers carried to **two decimal places**, and every rounding operation in this specification is **round half up** (a value exactly at the midpoint rounds away from zero, so 0.125 becomes 0.13). Money is rendered in responses as a JSON number with two decimal places.

Two ordering rules govern how rounding interacts with the rest of the arithmetic, and both are load-bearing:

1. **Round each declared step, then combine.** Where a calculation in §3 is written as numbered steps, the rounding happens at each numbered step, not once at the end. Where a cap or floor is applied to a rounded product — for instance the annual-maximum cap on an insurance payment — the product is rounded first and the cap is applied to the rounded value afterwards.
2. **Round the unit, then place the residual.** Where a principal is divided into equal installments, the per-installment base is rounded first and the whole residual is placed on the final installment. Summing first and rounding once is specifically wrong here and will produce a different schedule.

Counts, scores, ceilings, and day/month intervals are integers and are compared exactly. Where a boundary is inclusive or exclusive, this document says so at that boundary; no boundary is left to inference.

### 2.8. Optimistic Concurrency on Supersede-Style Creates

Three create operations in this system legitimately *supersede* something that already exists. Because a supersede write is not guarded by any state precondition — the older row is in a perfectly valid state and is simply displaced — the only protection against a client acting on a view it has not refreshed is an explicit expected-version check. All three are guarded, and no other endpoint in this API takes a version field.

- `POST /prosthetics/lab-cases` requires `expected_case_arch_version`, carrying the client's last observed `version` of the `CaseArch` named by `case_arch_id`. If that value does not equal the arch's current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP 412. The rule exists because a newer draft lab case supersedes an older draft lab case on the same arch; without the check a second create working from a stale view of the arch would silently discard the first dispatch plan.
- `POST /prosthetics/services` requires `expected_prosthesis_version`, carrying the client's last observed `version` of the `Prosthesis` named by `prosthesis_id`. A mismatch with the prosthesis's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412. A newer service of the same `service_type` voids an older un-completed one, so a client working from a stale view of `adjustments_remaining`, `in_patient_possession`, or `warranty_status` would supersede work it never saw.
- `POST /prosthetics/payment-plans` requires `expected_prosthesis_case_version`, carrying the client's last observed `version` of the `ProsthesisCase` named by `case_id`. A mismatch with the case's current `version` is rejected with `ERR_STALE_VERSION` and HTTP 412. A newer plan supersedes the case's current active or delinquent plan and strikes its principal from the case's patient responsibility, so a stale view of that amount would mint a schedule for the wrong balance.

In all three the field is a required input, not an optional one: omitting it is a request-schema failure refused with `ERR_VALIDATION` and HTTP 400, and that schema check sits *below* the version check on the ladder, so a request that omits the field never reaches the version comparison.

### 2.9. Path Resolution and Nested Reads

Path parameters are resolved strictly left to right, and the first segment that names nothing decides the error. The path parameters used across this API are `patient_id`, `coverage_id`, `lab_id`, `case_id`, `case_arch_id`, `impression_id`, `try_in_id`, `lab_case_id`, `prosthesis_id`, `service_id`, `warranty_claim_id`, `remake_request_id`, `predetermination_id`, `claim_id`, `payment_plan_id`, and `installment_id`.

Five entity types carry their own dedicated not-found code, and everything else shares one:

- a `patient_id` that names no patient yields `ERR_PATIENT_NOT_FOUND`;
- a `case_id` that names no case yields `ERR_CASE_NOT_FOUND`;
- a `case_arch_id` that names no arch yields `ERR_ARCH_NOT_FOUND`;
- a `lab_case_id` that names no lab case yields `ERR_LAB_CASE_NOT_FOUND`;
- a `prosthesis_id` that names no prosthesis yields `ERR_PROSTHESIS_NOT_FOUND`;
- a path segment naming a `Coverage`, `DentalLab`, `ImpressionRecord`, `TryInMilestone`, `PostDeliveryService`, `WarrantyClaim`, `RemakeRequest`, `Predetermination`, `Claim`, `PaymentPlan`, or `Installment` that resolves to no row yields `ERR_RESOURCE_NOT_FOUND`.

All six carry HTTP 404.

Foreign keys arriving in a **request body** are a separate matter and are checked one rung lower, after the write gate. A body field naming a row that does not exist — `patient_id`, `case_id`, `case_arch_id`, `dental_lab_id`, `prosthesis_id`, `coverage_id`, `warranty_claim_id`, `post_delivery_service_id`, `attributed_lab_case_id`, `superseded_prosthesis_id`, or `payment_plan_id` — is refused with `ERR_REFERENCE_NOT_FOUND` and HTTP 404, which is a different code from the path-segment codes above.

### 2.10. The Order of Refusal

When a request violates more than one rule, exactly one error comes back, and which one is not a matter of implementation taste. The server evaluates its checks as a strict ladder of 31 rungs in the order below, stops at the first rung that fails, and returns that rung's code. A rung that a request does not reach never runs and never writes anything (with the two deliberate exceptions called out in §2.12). The ladder is listed here once, in full, in evaluation order.

1. **Rung 1 — authentication.** `X-User-Role` is present and names one of the six roles, and `X-User-ID` is present and non-empty. Failure: `ERR_UNAUTHENTICATED`, HTTP 401. Scope: every endpoint.
2. **Rung 2 — role authorisation.** The role named by `X-User-Role` appears in the authorised-role list of the endpoint being called. Failure: `ERR_FORBIDDEN_ROLE`, HTTP 403. Scope: every endpoint.
3. **Rung 3 — entity-backed ownership.** As described in §2.1. Failure: `ERR_NOT_OWNER`, HTTP 403. Scope: `GET /prosthetics/patients/{patient_id}`, `GET /prosthetics/payment-plans/{payment_plan_id}`, `GET /prosthetics/installments/{installment_id}`, `POST /prosthetics/installments/{installment_id}/pay`, and `POST /prosthetics/lab-cases/{lab_case_id}/receive` — five endpoints and no others.
4. **Rung 4 — path existence.** Every resource named by a path segment exists, validated left to right, with the per-entity codes of §2.9. Failure: `ERR_PATIENT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_ARCH_NOT_FOUND`, `ERR_LAB_CASE_NOT_FOUND`, `ERR_PROSTHESIS_NOT_FOUND`, or `ERR_RESOURCE_NOT_FOUND`; all HTTP 404. Scope: every endpoint that has a path parameter. Note that this rung sits *below* ownership: a `Patient` caller asking for someone else's plan is told it is not the owner, not that the plan does not exist.
5. **Rung 5 — the global write gate.** Detailed in §2.11. Failure: `ERR_ACCOUNT_DELINQUENT`, HTTP 403. Scope: the gated family enumerated in §2.11. This rung sits above every schema, enum, concurrency, and state check, and therefore pre-empts 26 of the 31 rungs below it.
6. **Rung 6 — body foreign keys.** Every foreign key supplied in the request body names an existing row of its declared parent entity, as listed in §2.9. Failure: `ERR_REFERENCE_NOT_FOUND`, HTTP 404. Scope: every create that accepts a foreign key in its body.
7. **Rung 7 — request schema and ranges.** Every required input field of the endpoint is present, types match, numeric fields lie inside their declared ranges, pagination parameters are in bounds, and declared uniqueness pairs are free. The declared ranges are: `quality_score` from 0 to 100 inclusive; `unit_count` from 1 to 32 inclusive; `bench_line` from 1 to the target laboratory's `bench_line_count` inclusive; `installment_count` from 2 to 12 inclusive; `down_payment_amount` at least 0.20 times the case's *pre-discount* patient responsibility (the value observed before any prompt-pay discount is struck, as described in §3.9); `amount_paid` strictly greater than zero and equal to the installment's `amount` to the cent; `limit` from 1 to 100; `offset` at least 0. The declared uniqueness pairs are `case_id` together with `arch_position` on a new arch, and `patient_id` together with `rank` on a new coverage. Failure: `ERR_VALIDATION`, HTTP 400.
8. **Rung 8 — enum membership, exhaustively routed.** A value outside the declared member set of any of the following fields routes to `ERR_INVALID_ENUM` with HTTP 422, **and only these fields do**:
   - `prosthesis_type` on `POST /prosthetics/cases`
   - `arch_position` on `POST /prosthetics/case-arches`
   - `capture_method` on `POST /prosthetics/impressions` and on `POST /prosthetics/impressions/{impression_id}/request-retake`
   - `milestone_kind` on `POST /prosthetics/try-ins`
   - `decision` on `POST /prosthetics/try-ins/{try_in_id}/decide`
   - `turnaround_class` on `POST /prosthetics/lab-cases`
   - `purpose` on `POST /prosthetics/lab-cases`
   - `qc_result` on `POST /prosthetics/lab-cases/{lab_case_id}/qc`
   - `recall_outcome` on `POST /prosthetics/prostheses/{prosthesis_id}/recall-complete`
   - `service_type` on `POST /prosthetics/services`
   - `fault_verdict` on `POST /prosthetics/warranty-claims/{warranty_claim_id}/adjudicate`
   - `resolved_verdict` on `POST /prosthetics/warranty-claims/{warranty_claim_id}/clinical-review`
   - `reason_code` on `POST /prosthetics/remake-requests`
   - `rank` on `POST /prosthetics/coverages`
   - `cob_convention` on `POST /prosthetics/coverages`
   - `determination` on `POST /prosthetics/predeterminations/{predetermination_id}/determine`
   - `adjudication_outcome` on `POST /prosthetics/claims/{claim_id}/post-payment`
   - `frequency` on `POST /prosthetics/payment-plans`

   **No other field routes to this error; all other enum-membership failures route to `ERR_VALIDATION`.** That includes every enum-valued *query* filter on a list endpoint and every enum-valued field the server computes rather than accepts.
9. **Rung 9 — optimistic concurrency.** The supplied `expected_case_arch_version`, `expected_prosthesis_version`, or `expected_prosthesis_case_version` equals the current `version` of the named parent row, as specified in §2.8. Failure: `ERR_STALE_VERSION`, HTTP 412. Scope: `POST /prosthetics/lab-cases`, `POST /prosthetics/services`, `POST /prosthetics/payment-plans`.
10. **Rung 10 — terminal state.** The target row is not already in a terminal state of the state axis the operation drives. This rung is **axis-scoped**: an operation that drives a prosthesis's recall axis is gated by the recall terminal set only, and an operation that drives its warranty axis by the warranty terminal set only, so a warranty-voided appliance is not thereby blocked from a recall operation and vice versa. Failure: `ERR_TERMINAL_STATE`, HTTP 409. Scope: every state-changing endpoint. This rung sits directly above rung 11 and rung 12, which matters for the pre-emption described in §2.12.
11. **Rung 11 — remake eligibility.** The arch a remake is requested for has `remake_eligibility` of `ELIGIBLE`. Failure: `ERR_REMAKE_FINAL_DENIED`, HTTP 409. Scope: `POST /prosthetics/remake-requests`. This rung sits above rung 22 and pre-empts it on every attempt after the first; see §2.12.
12. **Rung 12 — from-state.** The target row's current state is a declared origin state of the transition the endpoint drives. Failure: `ERR_INVALID_STATE`, HTTP 409. Scope: every state-changing endpoint.
13. **Rung 13 — cross-entity state.** A precondition checked against a *different* row than the target. There are exactly seven:
    - `POST /prosthetics/case-arches/{case_arch_id}/start-fabrication` — the parent case's `case_status` must be `EXAM_COMPLETE` when the arch is leaving `PLANNED`, and `IN_FABRICATION` when it is leaving `REMAKE_PENDING`.
    - `POST /prosthetics/prostheses` — the named arch's `arch_status` must be `READY_FOR_DELIVERY`.
    - `POST /prosthetics/services/{service_id}/complete` on a row that is `AT_LAB` — the linked lab case's `lab_status` must be `QC_PASSED`.
    - `POST /prosthetics/remake-requests/{remake_request_id}/approve` — when the request cites a `warranty_claim_id`, that claim's `claim_status` must be `CLINIC_FAULT` or `LAB_FAULT`.
    - `POST /prosthetics/try-ins` — the parent arch's `arch_status` must be `MILESTONE_PENDING`.
    - `POST /prosthetics/impressions` — the parent arch's `arch_status` must be `IMPRESSION_PENDING`.
    - `POST /prosthetics/lab-cases` — the parent arch's `arch_status` must be `LAB_FABRICATION`.

    Failure: `ERR_CROSS_ENTITY_STATE`, HTTP 409. A lab case that the system mints for itself as part of a post-delivery service is not a caller create and is therefore not subject to this rung.
14. **Rung 14 — segregation of duties.** The `X-User-ID` approving or denying a remake request differs from that request's `requested_by_user_id`. Failure: `ERR_SEGREGATION_OF_DUTIES`, HTTP 403. Scope: `POST /prosthetics/remake-requests/{remake_request_id}/approve` and `POST /prosthetics/remake-requests/{remake_request_id}/deny`.
15. **Rung 15 — laboratory shelf life (mutate-then-reject).** On `POST /prosthetics/lab-cases/{lab_case_id}/receive`, when the logical clock is strictly after the lab case's `shelf_life_expires_at`, the row is first written to `EXPIRED` and only then does the call raise. Failure: `ERR_LAB_CASE_EXPIRED`, HTTP 409. Full semantics in §2.12.
16. **Rung 16 — milestone sequence.** A try-in may only be created with a `milestone_kind` equal to the parent arch's `next_required_milestone`, and an approving decision is only accepted on the row whose `milestone_kind` equals `next_required_milestone`. Creating a try-in at all on an arch whose `required_milestones` list is empty always fails here. Failure: `ERR_MILESTONE_SEQUENCE`, HTTP 422. Scope: `POST /prosthetics/try-ins` and `POST /prosthetics/try-ins/{try_in_id}/decide`.
17. **Rung 17 — impression retake ceiling.** The parent arch's `retake_count` is strictly below 3. Failure: `ERR_RETAKE_LIMIT_EXCEEDED`, HTTP 409. Scope: `POST /prosthetics/impressions/{impression_id}/request-retake`.
18. **Rung 18 — try-in adjust ceiling.** The milestone's `adjust_count` is strictly below 2 when the decision is an adjustment. Failure: `ERR_TRYIN_LIMIT_EXCEEDED`, HTTP 409. Scope: `POST /prosthetics/try-ins/{try_in_id}/decide`.
19. **Rung 19 — QC resend ceiling.** The lab case's `resend_count` is strictly below 2. Failure: `ERR_QC_RESEND_LIMIT_EXCEEDED`, HTTP 409. Scope: `POST /prosthetics/lab-cases/{lab_case_id}/resend`.
20. **Rung 20 — arch possession.** The arch holds no other lab case whose `lab_status` is `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT`, and — when the arch's `last_lab_received_at` is not null — the logical clock is **strictly after** `last_lab_received_at` plus 24 hours. A dispatch at exactly `last_lab_received_at` plus 24 hours is therefore a conflict, not a pass. Failure: `ERR_ARCH_OCCUPIED`, HTTP 409. Scope: `POST /prosthetics/lab-cases/{lab_case_id}/dispatch`.
21. **Rung 21 — bench-line overlap.** Detailed in §3.5. Failure: `ERR_LAB_SLOT_CONFLICT`, HTTP 409. Scope: `POST /prosthetics/lab-cases/{lab_case_id}/dispatch`. Rung 20 is evaluated before rung 21, so an arch that is itself still occupied reports arch occupancy even when the target bench line is also busy.
22. **Rung 22 — remake ceiling (mutate-then-reject).** On `POST /prosthetics/remake-requests`, when the target arch's `remake_request_count` is already at or above 2, the request row is first created and moved to `FINAL_DENIED`, the arch's `remake_eligibility` is first flipped to `FINAL_DENIED`, and only then does the call raise. Failure: `ERR_REMAKE_LIMIT_EXCEEDED`, HTTP 409. Full semantics in §2.12.
23. **Rung 23 — warranty already spent.** The prosthesis a warranty claim is adjudicated against does not have `warranty_status` of `WARRANTY_CONSUMED` or `WARRANTY_VOIDED`. An appliance whose warranty is already consumed or voided cannot fund a second no-charge remedy. `WARRANTY_EXPIRED` deliberately **passes** this rung, so that rung 24 stays reachable. Failure: `ERR_WARRANTY_CONSUMED`, HTTP 409. Scope: `POST /prosthetics/warranty-claims/{warranty_claim_id}/adjudicate` and `POST /prosthetics/warranty-claims/{warranty_claim_id}/clinical-review`.
24. **Rung 24 — warranty window.** The logical clock is at or before the prosthesis's `warranty_expires_at` **when the verdict is `CLINIC_FAULT` or `LAB_FAULT`**. This rung is deliberately not applied when the verdict is `PATIENT_FAULT` or `INDETERMINATE`, because a chargeable verdict does not depend on the warranty window. Failure: `ERR_WARRANTY_EXPIRED`, HTTP 422. Scope: the same two adjudication endpoints as rung 23.
25. **Rung 25 — service-type eligibility.** A clasp addition is only accepted when the prosthesis type is `CAST_PARTIAL` or `FLEXIBLE_PARTIAL`; a rebase is refused when the prosthesis type is `FLEXIBLE_PARTIAL`. Failure: `ERR_SERVICE_NOT_ELIGIBLE`, HTTP 422. Scope: `POST /prosthetics/services`.
26. **Rung 26 — service frequency limit.** Detailed in §3.7. Failure: `ERR_SERVICE_FREQUENCY_LIMIT`, HTTP 422. Scope: `POST /prosthetics/services`. Rung 25 is evaluated before rung 26, so an ineligible service type reports ineligibility even when it would also be inside a frequency window.
27. **Rung 27 — coordination-of-benefits rank uniqueness.** A patient may hold at most one coverage at `PRIMARY` and at most one at `SECONDARY`. Failure: `ERR_COB_RANK_CONFLICT`, HTTP 409. Scope: `POST /prosthetics/coverages`.
28. **Rung 28 — waiting period.** The logical clock is at or after the targeted coverage's `effective_date` plus its `waiting_period_days` days. The check runs against the primary coverage when the claim moves from `DRAFT` to `SUBMITTED_PRIMARY`, and against the secondary coverage when it moves from `PRIMARY_PAID` to `SUBMITTED_SECONDARY`. Failure: `ERR_WAITING_PERIOD`, HTTP 422. Scope: `POST /prosthetics/claims/{claim_id}/submit`.
29. **Rung 29 — replacement frequency.** Detailed in §3.8. Failure: `ERR_FREQUENCY_LIMIT`, HTTP 422. Scope: `POST /prosthetics/claims/{claim_id}/submit`.
30. **Rung 30 — predetermination gate.** When the target case's `predetermination_required` is true, a predetermination for that case must exist whose `determination_status` is `APPROVED` or `ALTERNATE_BENEFIT` and whose `expires_at` is strictly after the logical clock. A `DENIED`, `SUBMITTED`, or `EXPIRED` determination — or no determination at all — fails here. Failure: `ERR_PREDETERMINATION_REQUIRED`, HTTP 422. Scope: `POST /prosthetics/case-arches/{case_arch_id}/start-fabrication` and `POST /prosthetics/claims/{claim_id}/submit`.
31. **Rung 31 — annual maximum.** The coverage the current submission targets has `benefit_remaining` strictly greater than 0.00. Failure: `ERR_ANNUAL_MAX_EXHAUSTED`, HTTP 422. Scope: `POST /prosthetics/claims/{claim_id}/submit`. Claim submission therefore runs rungs 28, 29, 30, and 31 in that order, and a claim that fails several of them reports the lowest-numbered failure.

**Friction point — coverage rank uniqueness is claimed by two rungs.** The rule that a patient holds at most one coverage per rank appears twice in this specification: rung 7 lists the `patient_id`-and-`rank` pair among its uniqueness checks (`ERR_VALIDATION`, HTTP 400), and rung 27 restates the same condition as a dedicated coordination-of-benefits check (`ERR_COB_RANK_CONFLICT`, HTTP 409). Read strictly by ladder order the earlier rung would fire and the later one would be unreachable; read by specificity the dedicated rung is exactly what its dedicated code exists for. This document records the disagreement rather than resolving it. The other uniqueness pair carries no such ambiguity: a duplicate `case_id`-and-`arch_position` belongs to rung 7 and `ERR_VALIDATION` alone.

### 2.11. The Global Write Gate

A patient who owes the clinic money on a broken installment plan does not get new laboratory work started on their behalf. That policy is implemented as a single gate at rung 5: **the patient reached from the target resource must not own any `PaymentPlan` whose `plan_status` is `DELINQUENT` or `DEFAULTED`.** When such a plan exists, the call is refused with `ERR_ACCOUNT_DELINQUENT` and HTTP 403 *before* any body-reference, schema, enum, concurrency, or state check runs. The mirror of the gate is carried on the patient row as `write_gate_active`, a computed boolean that is true exactly when the patient owns at least one delinquent or defaulted plan.

The patient is reached from whichever resource the call targets: from `patient_id` on a create that names one, from the case on an arch operation, from the case behind the arch on an impression, try-in, lab case, or delivery, and from the arch behind the prosthesis on a service.

**Gated family — every endpoint below is frozen while the gate is up:**

- `POST /prosthetics/cases`
- `POST /prosthetics/case-arches`
- `POST /prosthetics/case-arches/{case_arch_id}/start-fabrication`
- `POST /prosthetics/impressions`
- `POST /prosthetics/impressions/{impression_id}/request-retake`
- `POST /prosthetics/try-ins`
- `POST /prosthetics/lab-cases`
- `POST /prosthetics/lab-cases/{lab_case_id}/dispatch`
- `POST /prosthetics/lab-cases/{lab_case_id}/resend`
- `POST /prosthetics/prostheses`
- `POST /prosthetics/remake-requests`
- `POST /prosthetics/services`, except when it is an emergency repair (see the carve-out below)

**Outside the gate — and the reason each one is excluded:**

- **Every `GET` endpoint.** Reading is never frozen; the patient and the front office must be able to see why the account is gated and what is owed.
- `POST /prosthetics/patients` and `POST /prosthetics/coverages`. Registration and insurance enrolment precede any balance and cannot be the thing a balance blocks.
- `POST /prosthetics/labs`. Laboratory configuration is clinic-wide, not patient-scoped, so no patient gate can apply to it.
- `POST /prosthetics/payment-plans`. Establishing — or replacing — a plan is the remedy for the gate; gating it would make the gate permanent.
- `POST /prosthetics/installments/{installment_id}/pay`. Paying is the cure; gating the cure makes the gate unrecoverable.
- `POST /prosthetics/installments/{installment_id}/reverse-payment`. The front office must be able to undo a mis-posted payment even on a gated account.
- `POST /prosthetics/payment-plans/{payment_plan_id}/assess-delinquency`. The sweep is what raises and lowers the gate; it cannot be subject to it.
- `POST /prosthetics/services` when `is_emergency_repair` is true **and** `service_type` is `REPAIR`. A patient whose denture has fractured cannot eat; emergency repair is a clinical-safety carve-out. Both conditions are required: an emergency flag on any other service type does not lift the gate, and a repair without the flag does not lift it either.
- `POST /prosthetics/services/{service_id}/complete` and `POST /prosthetics/services/{service_id}/void`. Finishing or undoing work already started is not a new fabrication start, and the appliance must come back to the patient.
- `POST /prosthetics/lab-cases/{lab_case_id}/receive` and `POST /prosthetics/lab-cases/{lab_case_id}/qc`. Work already at the laboratory must be received and inspected regardless of the balance; only *new* dispatches are frozen.
- `POST /prosthetics/impressions/{impression_id}/review` and `POST /prosthetics/try-ins/{try_in_id}/decide`. Judging an appointment that already happened is not a new start.
- `POST /prosthetics/prostheses/{prosthesis_id}/recall-complete`. Recall is a safety follow-up on an appliance the patient already has.
- `POST /prosthetics/warranty-claims`, `POST /prosthetics/warranty-claims/{warranty_claim_id}/adjudicate`, and `POST /prosthetics/warranty-claims/{warranty_claim_id}/clinical-review`. Fault adjudication decides who owes the money; letting the clinic's own receivable block it would let the clinic profit from its own delay.
- `POST /prosthetics/predeterminations`, `POST /prosthetics/predeterminations/{predetermination_id}/determine`, `POST /prosthetics/claims`, `POST /prosthetics/claims/{claim_id}/submit`, `POST /prosthetics/claims/{claim_id}/post-payment`, and `POST /prosthetics/claims/{claim_id}/reverse`. Insurance work reduces the balance and is part of the remedy path.
- `POST /prosthetics/remake-requests/{remake_request_id}/approve` and `POST /prosthetics/remake-requests/{remake_request_id}/deny`. The request creation was already gated; deciding an existing request is not a new start.
- `POST /prosthetics/cases/{case_id}/complete-exam` and `POST /prosthetics/cases/{case_id}/cancel`. Closing out or cancelling an existing case reduces exposure rather than adding to it.
- `POST /prosthetics/_clock/set_current_utc`. Test-driving infrastructure, outside the business surface entirely.

The gate rises and falls on its own, driven by the plan lifecycle described in §3.9; there is no endpoint that sets `write_gate_active` directly.

### 2.12. Mutate-Then-Reject, and What the Second Attempt Sees

Two rungs on the ladder break the usual "a failing rung writes nothing" rule. Each of them performs a bookkeeping write, **commits it**, and only then raises. The write survives the error; it is not rolled back. And in both cases the *second* attempt on the same row does not reach the same rung at all, because the write the first attempt committed trips a higher rung — which means the second attempt reports a different error.

**Rung 15 — receiving a lab case past its shelf life.** When a laboratory tries to return a case and the logical clock is strictly after that case's `shelf_life_expires_at`, the server first sets `lab_status` to `EXPIRED`, stamps `expired_at` with the logical clock, releases both the laboratory bench-line occupation and the arch occupation the case was holding, and increments the lab case's `version` by 1. That write is committed. Only then does the call fail with `ERR_LAB_CASE_EXPIRED` and HTTP 409. If the parent arch was in `LAB_FABRICATION` it stays in `LAB_FABRICATION`, so a fresh lab case can be drafted and dispatched for it.

*On a subsequent receive attempt against that same lab case*, the row is now sitting in `EXPIRED`, which is a terminal state of the lab-case axis. Rung 10 therefore fires first, the call returns **`ERR_TERMINAL_STATE` with HTTP 409 — not `ERR_LAB_CASE_EXPIRED`** — and no further write of any kind is performed.

**Rung 22 — requesting a remake past the ceiling.** When a remake is requested on an arch whose `remake_request_count` is already at or above 2, the server first creates the remake request row in `PENDING_APPROVAL`, immediately moves it to `FINAL_DENIED` with `decided_at` stamped, flips the arch's `remake_eligibility` to `FINAL_DENIED`, and increments the arch's `version` by 1. That write is committed — the denied request row is a real, persisted row and is discoverable by listing remake requests filtered on `case_arch_id`. Only then does the call fail with `ERR_REMAKE_LIMIT_EXCEEDED` and HTTP 409.

*On a subsequent remake request against that same arch*, the arch's `remake_eligibility` is now `FINAL_DENIED`, so rung 11 fires first, the call returns **`ERR_REMAKE_FINAL_DENIED` with HTTP 409 — not `ERR_REMAKE_LIMIT_EXCEEDED`** — and **no second `FINAL_DENIED` request row is minted.** The arch accumulates exactly one final-denied row no matter how many times the request is repeated.

### 2.13. Cascades, Bubble-Ups and Conserved Quantities

Several operations in this system mutate more than one row. Where they do, the full chain is spelled out in the §3 subsection that owns the operation, and each link's effect on `version` and `updated_at` is stated there. Two chains are large enough to have names used throughout this document: the **delivery cascade**, which runs when an appliance is delivered, and the **remake cascade**, which runs when a remake is authorised. Both are described in §3.6 and §3.7 respectively.

Parent state is often derived by bubble-up rather than by a direct call: a case moves to `IN_FABRICATION` because one of its arches left `PLANNED`, and to `DELIVERED` because its last outstanding arch was delivered. Every such bubble-up increments the parent's `version` by 1 and refreshes its `updated_at`, exactly as a direct mutation would.

Four quantities are **conserved** — they must hold at every instant an observer could read them, both after the forward action and after the compensating action that undoes it:

1. **Adjustment allowance.** On any prosthesis, `adjustments_used` plus `adjustments_remaining` always equals 4. Completing an included adjustment moves one unit from remaining to used; voiding that completed row moves it back. A *chargeable* adjustment — one past the count or past the window — must move neither counter, so the sum is untouched on that path too.
2. **Payment plan balance.** On any payment plan, `paid_amount` plus `outstanding_amount` always equals `principal_amount`. Paying an installment moves the installment's `amount` from outstanding to paid; reversing that payment moves it back.
3. **Laboratory credit.** On any laboratory, `credit_issued_total` minus `credit_applied_total` always equals `credit_available_balance`. Adjudicating a lab-fault warranty claim issues credit; applying that credit during a remake raises `credit_applied_total` by exactly the amount `credit_available_balance` falls by, leaving `credit_issued_total` untouched.
4. **Coverage benefit.** On any coverage, `benefit_used_ytd` plus `benefit_remaining` always equals `annual_maximum_amount`. Posting a payment consumes benefit; reversing the claim returns it.

## 3. Business Logic & Workflows

### 3.1. Registration: Patients, Coverages and Laboratories

Everything begins with a patient record, which a `FrontOffice` or `PlatformAdmin` operator registers with three pieces of information: `full_name`, `date_of_birth`, and `phone`. The record is minted with three derived fields already settled — `write_gate_active` false, `delivered_prosthesis_count` zero, and `last_frequency_anchor_at` null — and the server maintains all three from then on. `delivered_prosthesis_count` counts the appliances delivered to this patient that are *not* remakes: every prosthesis whose arch belongs to one of this patient's cases and whose `is_remake` is false. `last_frequency_anchor_at` is the greatest `frequency_anchor_at` across all of this patient's prostheses, or null while the patient has none; it is the anchor of the insurance replacement clock and is discussed again in §3.8.

Insurance enrolment attaches a coverage to a patient. The enrolling operator supplies `patient_id`, `carrier_name`, `rank`, and `effective_date`, and may supply six further values, each of which has a default the server applies when it is omitted: `annual_maximum_amount` defaults to 1500.00, `coinsurance_major_rate` defaults to 0.50, `waiting_period_days` defaults to 180, `replacement_frequency_months` defaults to 60, `cob_convention` defaults to `STANDARD`, and `alternate_benefit_enabled` defaults to true. `rank` is either `PRIMARY` or `SECONDARY` and nothing else; `cob_convention` is either `STANDARD` or `NON_DUPLICATION` and nothing else. A patient may hold one coverage at each rank; a second coverage at a rank the patient already holds collides with `ERR_COB_RANK_CONFLICT` as described at rung 27.

A newly enrolled coverage starts with `benefit_used_ytd` at 0.00 and `benefit_remaining` equal to `annual_maximum_amount`, which is what establishes the coverage-benefit conservation described in §2.13. Thereafter `benefit_used_ytd` is the sum of `plan_paid_amount` over the claims that cite this coverage and whose `adjudication_status` is `PRIMARY_PAID`, `SECONDARY_PAID`, or `CLOSED`, and `benefit_remaining` is `annual_maximum_amount` minus `benefit_used_ytd`, floored at 0.00 so that it never goes negative. Coverages can be listed and filtered by `patient_id` and by `rank`.

External laboratories are registered by a `PlatformAdmin` alone, because a laboratory is clinic-wide configuration rather than anything belonging to a patient. Registration takes `lab_name` and three optional operating parameters: `bench_line_count`, which defaults to 3 and must be at least 1 and at most 10; `standard_turnaround_days`, which defaults to 10; and `rush_turnaround_days`, which defaults to 4. The identifier that comes back from registration is the value a laboratory sends as `X-User-ID` when it acts as a `LabTechnician`. A new laboratory's credit ledger — `credit_issued_total`, `credit_applied_total`, and `credit_available_balance` — starts at 0.00 on all three counters.

### 3.2. Case Intake, Arch Planning and the Exam Close-Out

A prosthesis case is opened for one patient at one `prosthesis_type`, and the type chosen at intake parameterises almost everything that follows: the fee, the required try-in sequence, the recall interval, and which post-delivery services are even permitted. The six types are `COMPLETE_DENTURE`, `IMMEDIATE_DENTURE`, `CAST_PARTIAL`, `FLEXIBLE_PARTIAL`, `OVERDENTURE`, and `IMPLANT_RETAINED_OVERDENTURE`. A `Prosthodontist` or a `FrontOffice` operator opens the case by supplying `patient_id` and `prosthesis_type` — an act inside the global write gate, so a patient with a broken payment plan gets no new case opened; the case is born in `INTAKE` with `fee_schedule_total` at 0.00 and `predetermination_required` false, and with `fabrication_started_at` and `delivered_at` both null. Cases can be listed and filtered by `patient_id` and by `case_status`.

Each case then acquires one or two **arch units**. A `Prosthodontist` adds an arch by naming the `case_id` and the `arch_position`, which is `MAXILLARY` or `MANDIBULAR`; adding an arch is likewise inside the global write gate, at most one arch row may exist per case per position, and a duplicate pair is a rung 7 schema failure. A new arch is born in `PLANNED` with `retake_count`, `remake_count`, and `remake_request_count` at zero, `remake_eligibility` at `ELIGIBLE`, `fee_schedule_amount` at 0.00, and `last_lab_received_at` null. At creation the server also computes the arch's `required_milestones` from the parent case's `prosthesis_type`, and that list is what the try-in stage will walk:

- A `COMPLETE_DENTURE` requires a wax try-in and then a finish try-in, in that order.
- An `IMMEDIATE_DENTURE` requires **no** try-in milestones at all — its `required_milestones` is the empty list.
- A `CAST_PARTIAL` requires a framework try-in, then a wax try-in, then a finish try-in, in that order.
- A `FLEXIBLE_PARTIAL` requires a wax try-in only.
- An `OVERDENTURE` requires a wax try-in and then a finish try-in.
- An `IMPLANT_RETAINED_OVERDENTURE` requires a framework try-in and then a finish try-in.

Alongside `required_milestones` the arch carries `completed_milestones`, the ordered list of `milestone_kind` values of this arch's try-in rows that reached approval, sorted by their `created_at` ascending, and `next_required_milestone`, which is the first entry of `required_milestones` not yet present in `completed_milestones`, or null once every required milestone is complete. Arches can be listed and filtered by `case_id` and by `arch_status`.

Closing the exam is what prices the case. A `Prosthodontist` closes it, moving `case_status` from `INTAKE` to `EXAM_COMPLETE`; the call requires that at least one arch already exists on the case, and a case with no arches is refused with `ERR_VALIDATION`. Closing the exam sets each non-abandoned arch's `fee_schedule_amount` to the fee for the case's `prosthesis_type` — 1800.00 for a complete denture, 2100.00 for an immediate denture, 1650.00 for a cast partial, 1200.00 for a flexible partial, 2400.00 for an overdenture, and 3600.00 for an implant-retained overdenture — then sets the case's `fee_schedule_total` to the sum of `fee_schedule_amount` over every arch of the case whose `arch_status` is not `ARCH_ABANDONED`, rounded half up to two decimal places. Because the sum is order-independent no tie-break is needed. Finally it sets `predetermination_required` to true exactly when `fee_schedule_total` is at or above 1500.00, and increments the case's `version` by 1. A single-arch complete denture at 1800.00 therefore requires a predetermination; a single-arch flexible partial at 1200.00 does not; a two-arch flexible partial at 2400.00 does.

Fabrication starts per arch, not per case. When a `Prosthodontist` starts fabrication on an arch sitting in `PLANNED`, three preconditions apply beyond the ladder's generic checks: the parent case must be in `EXAM_COMPLETE`, the patient must not be behind the write gate, and — when the case's `predetermination_required` is true — a live approved or alternate-benefit predetermination must exist for the case, failing which the call is refused with `ERR_PREDETERMINATION_REQUIRED`. The arch moves `PLANNED → IMPRESSION_PENDING`, its `retake_count` is reset to zero, its `required_milestones` is recomputed from the case's `prosthesis_type`, and its `version` is incremented by 1. That same action bubbles the parent case from `EXAM_COMPLETE` to `IN_FABRICATION`, stamps the case's `fabrication_started_at` with the logical clock, and increments the case's `version` by 1 — a bubble-up that happens only once, on the first arch of the case to leave `PLANNED`.

The same action serves the remake loop. An arch sitting in `REMAKE_PENDING` restarts with `REMAKE_PENDING → IMPRESSION_PENDING`; here the parent case must already be in `IN_FABRICATION` and the patient must still be clear of the write gate, `retake_count` is again reset to zero, the arch's `version` is incremented by 1, and no case-level bubble-up occurs because the case is already where it needs to be.

Cancellation is available to a `Prosthodontist` from `INTAKE`, `EXAM_COMPLETE`, or `IN_FABRICATION`, optionally carrying a `cancellation_reason`, and it cascades in three directions at once. The case moves to `CANCELLED`. Every arch of the case whose `arch_status` is not already `ARCH_CLOSED` or `ARCH_ABANDONED` moves to `ARCH_ABANDONED` — and that includes an arch already sitting in `DELIVERED`, so a two-arch case can be cancelled after one arch was delivered and the delivered arch is abandoned along with its sibling. Every lab case belonging to those arches whose `lab_status` is not `QC_PASSED`, `EXPIRED`, or `CANCELLED` moves to `CANCELLED`, releasing whatever bench-line occupation it held. Every try-in milestone of those arches sitting in `PENDING_APPROVAL` or `ADJUST_REQUESTED` moves to `CANCELLED`. Each touched row's `version` increments by 1.

At the far end of the lifecycle sits closure, which the system performs for itself rather than any caller invoking it. A case in `DELIVERED` moves to `CLOSED` once every claim of the case has an `adjudication_status` of `CLOSED`, `DENIED`, or `REVERSED`, **and** every payment plan of the case has a `plan_status` of `PAID_OFF` or `SUPERSEDED` — or, where the case never needed a plan at all, once the case has no payment plan and its `patient_responsibility_amount` is 0.00. Closure sets every arch of the case still sitting in `DELIVERED` to `ARCH_CLOSED` and increments the case's `version` by 1. `CLOSED` and `CANCELLED` are the two terminal states of the case axis; `ARCH_CLOSED` and `ARCH_ABANDONED` are the two terminal states of the arch axis.

### 3.3. Impression Capture and the Three-Band Quality Review

With the arch in `IMPRESSION_PENDING`, a `Prosthodontist` records a capture by naming the `case_arch_id` and the `capture_method`, which is either `PHYSICAL_IMPRESSION` or `DIGITAL_SCAN`. The parent arch must be in `IMPRESSION_PENDING` for the capture to be accepted at all; an arch anywhere else yields `ERR_CROSS_ENTITY_STATE`. Creating the record is inside the write gate. The record is born in `PENDING_REVIEW` with `attempt_number` equal to the arch's current `retake_count` plus one — so the first capture after fabrication starts is attempt 1 — and with `quality_score` null, `retake_required` false, `reviewed_at` null, and `superseded_by_impression_id` null.

Review is a separate act, and it deliberately sits **outside** the write gate: the appointment already happened, and refusing to judge it would help nobody. The reviewing clinician supplies an integer `quality_score` between 0 and 100 inclusive; a score outside that range is a rung 7 schema failure. The score decides the band, and the boundaries are inclusive on the lower edge in both cases:

- A score of **85 or more** puts the record in `ACCEPTED`. `retake_required` stays false.
- A score of **at least 70 but below 85** puts the record in `PROVISIONAL_ACCEPTED` and sets `retake_required` to true.
- A score **below 70** puts the record in `REJECTED` and likewise sets `retake_required` to true.

In all three bands the review stamps `reviewed_at` with the logical clock, persists the supplied `quality_score`, and increments the record's `version` by 1. Where the bands differ is what happens to the arch. On `ACCEPTED`, the arch advances out of `IMPRESSION_PENDING` — to `MILESTONE_PENDING` when its `required_milestones` list is non-empty, with `next_required_milestone` set to the first entry of that list, or straight to `LAB_FABRICATION` when the list is empty, which holds only for an `IMMEDIATE_DENTURE`. Either way the arch's `version` increments by 1. On `PROVISIONAL_ACCEPTED` and on `REJECTED`, the arch is left exactly where it was, in `IMPRESSION_PENDING`, and the clinician's next move is a retake.

Requesting a retake is inside the write gate and is only available on a record sitting in `PROVISIONAL_ACCEPTED` or `REJECTED`. It carries one input, the `capture_method` of the replacement capture, which need not match the method of the record being replaced. Before anything happens the arch's `retake_count` must be **strictly below 3**; at three retakes the arch is out of attempts and the request is refused with `ERR_RETAKE_LIMIT_EXCEEDED`. When it is allowed, four things happen together: the arch's `retake_count` increases by one and its `version` increments by 1; a successor record is created on the same arch in `PENDING_REVIEW` with `attempt_number` one higher than the superseded record's and the `capture_method` supplied on the request; the superseded record's `quality_status` becomes `SUPERSEDED` and its `superseded_by_impression_id` is set to the successor's identifier; and the superseded record's `version` increments by 1. **The response body is the superseded record, not the successor** — the successor is reachable by following `superseded_by_impression_id`, or by listing impression records filtered on `case_arch_id`, on `quality_status`, or on `superseded_by_impression_id`.

`ACCEPTED` and `SUPERSEDED` are the two terminal states of the impression axis. `PROVISIONAL_ACCEPTED` and `REJECTED` are not terminal, precisely because the retake leg has to remain reachable from both of them.

### 3.4. Try-In Milestones and the Type-Parameterised Sequence

A try-in milestone is booked on an arch that is in `MILESTONE_PENDING`, by a `Prosthodontist`, naming the `case_arch_id` and the `milestone_kind` — `WAX`, `FRAMEWORK`, or `FINISH`. Booking is inside the write gate. The arch must be in `MILESTONE_PENDING`, or the booking is refused with `ERR_CROSS_ENTITY_STATE`; and the `milestone_kind` must equal the arch's `next_required_milestone`, or the booking is refused with `ERR_MILESTONE_SEQUENCE`. Because an `IMMEDIATE_DENTURE` has an empty `required_milestones` list, and therefore a null `next_required_milestone` from the very start, **any** attempt to book a try-in on an immediate denture fails with `ERR_MILESTONE_SEQUENCE`. A framework try-in is only ever the next required milestone on a `CAST_PARTIAL` or an `IMPLANT_RETAINED_OVERDENTURE`; on the other types it can never be booked. The row is created in `PENDING_APPROVAL` with `adjust_count` zero and `decided_at` and `decided_by_user_id` null.

Deciding a milestone is outside the write gate — judging an appointment that already happened is not a new start — and the decision carries a single `decision` input taking one of four values: `APPROVE`, `ADJUST`, `RESUBMIT`, or `REJECT`. Every one of the four stamps `decided_at` with the logical clock, records the calling `X-User-ID` in `decided_by_user_id`, and increments the milestone's `version` by 1. Beyond that they diverge sharply, and each branch carries its own preconditions:

**Approval.** Permitted from `PENDING_APPROVAL` only, and only while the parent arch is in `MILESTONE_PENDING` and this row's `milestone_kind` equals the arch's `next_required_milestone`; approving an out-of-sequence row is refused with `ERR_MILESTONE_SEQUENCE`. Approval moves the row to `APPROVED`, appends its `milestone_kind` to the arch's `completed_milestones`, and recomputes `next_required_milestone`. When that recomputation yields null — meaning the last required milestone has just been approved — the arch advances `MILESTONE_PENDING → LAB_FABRICATION` and its `version` increments by 1. A cast partial therefore needs three approvals before its arch reaches the laboratory stage; a flexible partial needs one.

**Adjustment.** Permitted from `PENDING_APPROVAL`, and only while the row's `adjust_count` is **strictly below 2**; a third adjustment on the same row is refused with `ERR_TRYIN_LIMIT_EXCEEDED`. It moves the row `PENDING_APPROVAL → ADJUST_REQUESTED`, increases `adjust_count` by one, and leaves the parent arch untouched in `MILESTONE_PENDING`.

**Resubmission.** Permitted from `ADJUST_REQUESTED` only, and it moves the row back `ADJUST_REQUESTED → PENDING_APPROVAL`, closing the adjust-and-re-try-in cycle on the same row. `adjust_count` is deliberately **not** reset, so the ceiling of two is cumulative across the life of the row: adjust, resubmit, adjust, resubmit leaves the row at two adjustments and a third adjustment is refused.

**Rejection.** Permitted from `PENDING_APPROVAL`, and only while the parent arch is in `MILESTONE_PENDING`. It moves the row to `REJECTED_FOR_REMAKE` and, as a side effect, auto-creates a remake request on the parent arch in `PENDING_APPROVAL` with `reason_code` of `TRYIN_REJECTED`, `requested_by_user_id` set to the deciding `X-User-ID`, and `warranty_claim_id` null. That auto-created request is what later drives the arch into `REMAKE_PENDING`, described in §3.7.

Milestones sitting in `PENDING_APPROVAL` or `ADJUST_REQUESTED` when their case is cancelled move to `CANCELLED` with a `version` increment, as covered in §3.2. `APPROVED`, `REJECTED_FOR_REMAKE`, and `CANCELLED` are the three terminal states of the milestone axis. Try-in milestones can be listed and filtered by `case_arch_id` and by `approval_status`.

### 3.5. Laboratory Coordination, Bench Lines and the Shelf-Life Clock

Once an arch reaches `LAB_FABRICATION`, the work has to go out to a laboratory, and a **lab case** is the paperwork that travels with it. A `Prosthodontist` or a `FrontOffice` operator drafts one by naming the `case_arch_id` it belongs to, the `dental_lab_id` it is going to, the `bench_line` it will occupy, the `turnaround_class` it is booked at, the `unit_count` of billable units on it, the `purpose` it exists for, and the `expected_case_arch_version` that guards the write. `lab_invoice_amount` is optional and defaults to 450.00; it is the amount the laboratory invoices the clinic and, later, the base of any lab-fault credit. `turnaround_class` is `STANDARD` or `RUSH`. `purpose` is one of `FABRICATION`, `RELINE`, `REBASE`, `REPAIR`, `ADDITION`, or `REMAKE`. `unit_count` must be at least 1 and at most 32, and `bench_line` must be at least 1 and at most the target laboratory's `bench_line_count` — a laboratory left on the default of 3 bench lines therefore accepts bench lines 1, 2, and 3 only.

Drafting a lab case is inside the write gate and requires the parent arch to be in `LAB_FABRICATION`, failing which the create is refused with `ERR_CROSS_ENTITY_STATE`. It also **supersedes**: any lab case already sitting in `DRAFT` on the same arch is moved to `CANCELLED`, releasing whatever bench-line reservation it held, and the arch's `version` is incremented by 1. That supersede is exactly why the create is guarded by `expected_case_arch_version`, as §2.8 explains. The new row is born in `DRAFT`, with `rush_fee_amount` at 0.00, `resend_count` at zero, and `dispatched_at`, `promised_due_at`, `shelf_life_expires_at`, `received_at`, `qc_result`, and `expired_at` all null.

**Dispatch** is what starts the clocks, and it is inside the write gate. Before anything is written, two overlap checks run in order. The first, at rung 20, is about the arch: the arch must hold no other lab case whose `lab_status` is `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT`, and — when the arch's `last_lab_received_at` is not null — the logical clock must be strictly after `last_lab_received_at` plus 24 hours. That buffer is a closed interval on the wrong side: a dispatch at exactly 24 hours after the last return is still a conflict and yields `ERR_ARCH_OCCUPIED`; only 24 hours and one millisecond later does it pass. The second check, at rung 21, is about the laboratory's capacity: the interval running from the dispatch instant up to but **not including** the new case's `promised_due_at` must not intersect the same half-open interval of any other lab case sharing the same `dental_lab_id` and `bench_line` whose `lab_status` is `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT`. Because the intervals are half-open, touching is permitted: a dispatch landing exactly on another case's `promised_due_at` passes, while a dispatch one millisecond earlier collides with `ERR_LAB_SLOT_CONFLICT`.

Dispatch then stamps `dispatched_at` with the logical clock and derives three values from it. `promised_due_at` is `dispatched_at` plus the laboratory's `standard_turnaround_days` when `turnaround_class` is `STANDARD`, or plus its `rush_turnaround_days` when it is `RUSH`; on a laboratory left at its defaults that is ten calendar days for a standard case and four for a rush case, with the time-of-day of the dispatch preserved. `shelf_life_expires_at` is `dispatched_at` plus 45 calendar days, and it is computed identically for both turnaround classes. `rush_fee_amount` is 0.00 for a standard case; for a rush case it is 120.00 plus 35.00 multiplied by the case's `unit_count`, rounded half up to two decimal places — so a rush case of three units carries a rush fee of 225.00. That rush fee is added to the parent case's `billed_amount`, the case's money fields are recomputed as described in §3.9, and the lab case's `version` increments by 1.

**Receiving** is the laboratory's own act, and only a `LabTechnician` whose `X-User-ID` equals the lab case's `dental_lab_id` may perform it — anyone else's laboratory identity is refused with `ERR_NOT_OWNER`. Receiving is outside the write gate: work already at the laboratory must come back regardless of the patient's balance. From `DISPATCHED` or from `RESENT` the case moves to `RETURNED`, `received_at` is stamped with the logical clock, the parent arch's `last_lab_received_at` is set to that same instant — which is what arms the 24-hour buffer for the next dispatch on that arch — and the lab case's `version` increments by 1. If the logical clock is strictly after `shelf_life_expires_at`, the mutate-then-reject behaviour of §2.12 takes over instead: the row is flipped to `EXPIRED`, `expired_at` is stamped, both occupations are released, the write is committed, and the call raises `ERR_LAB_CASE_EXPIRED`. A second attempt on that same row returns `ERR_TERMINAL_STATE` instead, and the arch — if it was in `LAB_FABRICATION` — stays there so a fresh lab case can be drafted.

**Clinic QC** happens on a `RETURNED` case and is outside the write gate. A `Prosthodontist` supplies a `qc_result` of `PASS` or `FAIL`, and the result is persisted on the row. A pass moves the case to `QC_PASSED`; when the case's `purpose` is `FABRICATION` or `REMAKE` this also advances the parent arch `LAB_FABRICATION → READY_FOR_DELIVERY` with a `version` increment on the arch, and when the `purpose` is `RELINE`, `REBASE`, `REPAIR`, or `ADDITION` it instead makes the post-delivery service linked to this lab case completable, as §3.7 describes. A fail moves the case to `QC_FAILED`, leaves the parent arch in `LAB_FABRICATION`, and opens the resend leg. Either way the lab case's `version` increments by 1.

**Resending** a QC-failed case is inside the write gate and is available from `QC_FAILED` only. The case's `resend_count` must be strictly below 2, so a case may be resent twice and a third resend is refused with `ERR_QC_RESEND_LIMIT_EXCEEDED`; and the logical clock must still be at or before `shelf_life_expires_at`, a resend attempted after that instant being refused with `ERR_LAB_CASE_EXPIRED` — without, on this path, any accompanying write, because the mutate-then-reject behaviour belongs to the receive path alone. A permitted resend moves the case `QC_FAILED → RESENT`, increases `resend_count` by one, clears `received_at` back to null, and — critically — **leaves `shelf_life_expires_at` exactly where it was**, so the 45-day shelf-life clock keeps running from the original dispatch and is not renewed by the resend. The cycle `QC_FAILED → RESENT → RETURNED → QC_FAILED` can therefore repeat at most twice before the ceiling stops it.

Lab cases are also cancelled from the outside. A case cancellation, an approved remake on the arch, the voiding of the post-delivery service that a lab case was created for, and the drafting of a newer lab case on the same arch all move an open lab case to `CANCELLED`, provided its `lab_status` is not already `QC_PASSED`, `EXPIRED`, or `CANCELLED`. The `DRAFT`, `DISPATCHED`, and `RESENT` legs explicitly release the laboratory bench-line reservation the case was holding; in every leg the row leaves the set of statuses that counts as occupying, and each cancelled row's `version` increments by 1. `QC_PASSED`, `EXPIRED`, and `CANCELLED` are the three terminal states of the lab-case axis. Lab cases can be listed and filtered by `case_arch_id`, by `dental_lab_id`, and by `lab_status`.

### 3.6. Delivery, the Two Clocks That Disagree, and the Recall Cycle

Delivery is the hinge of the whole system. A `Prosthodontist` delivers the finished appliance for one arch by naming the `case_arch_id`; on a remake the delivery additionally names the `superseded_prosthesis_id` of the appliance being replaced, and on an original delivery that field is omitted or null. Delivery is inside the write gate, and the named arch must be sitting in `READY_FOR_DELIVERY` or the call is refused with `ERR_CROSS_ENTITY_STATE`.

What follows is the **delivery cascade**, four links deep:

- **Link 1** creates the prosthesis row itself, in `warranty_status` `IN_WARRANTY` and `recall_status` `RECALL_SCHEDULED`, with `adjustments_used` at zero, `adjustments_remaining` at 4, `in_patient_possession` true, and `delivered_at` stamped with the logical clock. `prosthesis_type` is copied from the arch's parent case at this moment, and `is_remake` is true exactly when `superseded_prosthesis_id` is not null.
- **Link 2**, caused by link 1, moves the parent arch `READY_FOR_DELIVERY → DELIVERED` and increments the arch's `version` by 1.
- **Link 3**, caused by link 2, bubbles the parent case `IN_FABRICATION → DELIVERED` once every arch of that case is either `DELIVERED` or `ARCH_ABANDONED` and at least one of them is `DELIVERED`; while any arch of the case is still in `PLANNED`, `IMPRESSION_PENDING`, `MILESTONE_PENDING`, `LAB_FABRICATION`, `READY_FOR_DELIVERY`, or `REMAKE_PENDING`, the case stays in `IN_FABRICATION`. The bubble-up stamps the case's `delivered_at` with the logical clock, recomputes the case's `billed_amount` and `patient_responsibility_amount`, and increments the case's `version` by 1.
- **Link 4**, caused by link 3, auto-creates exactly one claim for the case, in `DRAFT`, with its `coverage_id` set to the coverage of the case's patient whose `rank` is `PRIMARY` — but only when exactly one such coverage exists. **When the patient holds no primary coverage, no claim is created and delivery is otherwise unaffected.** This leg fires only on the case-level transition to `DELIVERED`; a delivery that leaves the case in `IN_FABRICATION` mints no claim.

On a remake delivery there is one further effect: the superseded appliance named by `superseded_prosthesis_id` has its `warranty_status` set to `WARRANTY_VOIDED` and its `recall_status` set to `RECALL_CLOSED_SUPERSEDED`, with its own `version` increment.

**The two clocks.** Delivery starts two long-running clocks on the new appliance, and they are deliberately built to disagree on a remake.

- `warranty_expires_at` is always `delivered_at` plus 365 calendar days — **this** delivery's `delivered_at`, whether the appliance is an original or a remake. A remake therefore buys a full fresh year of warranty.
- `frequency_anchor_at` is the anchor of the *insurance* replacement clock, and it depends on which kind of delivery this is. On an original delivery, where `superseded_prosthesis_id` is null, `frequency_anchor_at` equals this appliance's `delivered_at`. On a remake delivery, where `superseded_prosthesis_id` is set, `frequency_anchor_at` is copied verbatim from the superseded appliance's `frequency_anchor_at`. A remake therefore buys **no** new frequency eligibility at all.
- `replacement_eligible_date` is `frequency_anchor_at` plus 60 calendar months, keeping the day-of-month and clamping to the last day of a shorter target month.

The consequence is worth stating plainly: an appliance remade three years after its original delivery is under warranty for a year from the remake, but its `replacement_eligible_date` still counts from the original delivery five years earlier, so the carrier's replacement window is untouched by the clinic's own rework.

Delivery also fixes two smaller windows. `adjustment_window_ends_at` is `delivered_at` plus 90 calendar days, and it bounds the included-adjustment allowance of §3.7. `mandatory_reline_due_at` is `delivered_at` plus 180 calendar days **when the `prosthesis_type` is `IMMEDIATE_DENTURE`, and null for every other type** — an immediate denture is placed on a healing ridge and is expected to need a hard reline within six months.

Finally, the patient's own counters move: `delivered_prosthesis_count` rises by one for a non-remake delivery, and `last_frequency_anchor_at` becomes the greatest `frequency_anchor_at` across the patient's appliances.

**The warranty axis.** Warranty and recall are two independent axes riding on the same prosthesis row; a movement on one never implies a movement on the other. The warranty axis starts at `IN_WARRANTY` and has four possible values.

- `IN_WARRANTY → WARRANTY_CONSUMED` happens when a warranty claim on this appliance reaches `CLINIC_FAULT` or `LAB_FAULT`, provided the appliance is currently `IN_WARRANTY` and the logical clock is at or before `warranty_expires_at`. It also sets that claim's `warranty_consumed` to true. A `PATIENT_FAULT` verdict deliberately does **not** reach this transition.
- `IN_WARRANTY → WARRANTY_EXPIRED` and `WARRANTY_CONSUMED → WARRANTY_EXPIRED` are both evaluated lazily, on every read or handling of the row, and fire when the logical clock is strictly after `warranty_expires_at`.
- `IN_WARRANTY → WARRANTY_VOIDED` and `WARRANTY_CONSUMED → WARRANTY_VOIDED` fire when the parent arch enters `REMAKE_PENDING`, and apply to the most recent appliance of that arch.

Each of those transitions increments the prosthesis's `version` by 1. `WARRANTY_EXPIRED` and `WARRANTY_VOIDED` are the two terminal states of the warranty axis.

**The recall axis.** The recall axis starts at `RECALL_SCHEDULED`. Its first due date is computed from the appliance type: 365 days after delivery for a `COMPLETE_DENTURE`, a `CAST_PARTIAL`, or a `FLEXIBLE_PARTIAL`; 180 days for an `OVERDENTURE` or an `IMPLANT_RETAINED_OVERDENTURE`; and only 90 days for an `IMMEDIATE_DENTURE`, which needs watching soonest. More precisely, `recall_due_at` is `delivered_at` plus the appliance type's interval multiplied by one more than the appliance's `recall_cycle_count`, so the first cycle is one interval out, the second is two intervals out, and so on.

Banding is evaluated lazily against the logical clock whenever the row is read or handled. A row moves `RECALL_SCHEDULED → RECALL_DUE` once the logical clock is **at or after** `recall_due_at` — the boundary instant itself counts as due. A row moves `RECALL_DUE → RECALL_OVERDUE` around the point 30 days later; see the friction note at the end of this subsection for the exact boundary.

Closing a recall visit is a `Prosthodontist` act, sits outside the write gate because recall is a safety follow-up on an appliance the patient already holds, and carries one `recall_outcome` input with three permitted values:

- **`NO_ACTION`** — the appliance is fine. The row returns to `RECALL_SCHEDULED`, `recall_cycle_count` increases by one, and `recall_due_at` therefore advances by one further interval of the appliance type. This is the recall *cycle*: a clean recall reschedules the same row instead of terminating it, and a complete denture recalled cleanly twice is next due three years after delivery. The leg is declared from `RECALL_DUE` and from `RECALL_OVERDUE`.
- **`RELINE_INDICATED`** — the row moves to `RECALL_COMPLETED` and a post-delivery service of `service_type` `HARD_RELINE_LAB` is auto-created on this appliance in `REQUESTED`. Because it is minted by the system rather than requested by a caller, it carries no laboratory routing of its own and stays in `REQUESTED`.
- **`REMAKE_EVALUATION`** — the row moves to `RECALL_COMPLETED` and a remake request is auto-created on the parent arch in `PENDING_APPROVAL` with `reason_code` of `RECALL_EVALUATION` and `requested_by_user_id` set to the calling `X-User-ID`.

Both completing outcomes are accepted from `RECALL_SCHEDULED`, `RECALL_DUE`, and `RECALL_OVERDUE` alike. Separately, a row in any of those three bands moves to `RECALL_CLOSED_SUPERSEDED` when the parent arch enters `REMAKE_PENDING`, provided it is the most recent appliance of that arch. Every recall transition increments the prosthesis's `version` by 1. `RECALL_COMPLETED` and `RECALL_CLOSED_SUPERSEDED` are the two terminal states of the recall axis.

Reading one prosthesis re-evaluates both clock-driven axes against the logical clock before the row is projected, so a caller who advances the clock and then reads sees the new bands. Prostheses can be listed and filtered by `case_arch_id`, by `superseded_prosthesis_id`, by `warranty_status`, and by `recall_status`.

**Friction point — the overdue boundary.** Two statements in this specification disagree about the exact instant a recall becomes overdue. The recall banding rule places a row in the overdue band once the logical clock is **at or after** `recall_due_at` plus 30 days, an inclusive boundary; the recall state-machine description moves the row `RECALL_DUE → RECALL_OVERDUE` only once the clock is **strictly after** that same instant. Every instant strictly after `recall_due_at` plus 30 days is overdue on both readings, and every instant before it is merely due on both readings; only the single boundary instant is disputed. This document records the disagreement rather than resolving it, and pins no behaviour at exactly `recall_due_at` plus 30 days. A separate note: the no-action outcome above has declared legs only from `RECALL_DUE` and `RECALL_OVERDUE`, so a no-action recall closed on a row still sitting in `RECALL_SCHEDULED` has no declared destination.

### 3.7. Post-Delivery Services, Warranty Fault and Remake Authorisation

An appliance in a patient's mouth generates work for years. A **post-delivery service** is one unit of that work, requested by a `Prosthodontist` or a `FrontOffice` operator against a delivered appliance. The request names the `prosthesis_id`, the `service_type`, and the `expected_prosthesis_version` that guards the write; it may also carry `is_emergency_repair`, which defaults to false, and — for the service types that go out to a laboratory — a `dental_lab_id` and a `bench_line`. Those last two are required when the service type is a laboratory type and ignored otherwise.

The seven service types split into two branches that behave differently in every respect that matters:

- **Chairside**: `ADJUSTMENT`, `SOFT_RELINE_CHAIRSIDE`, and `REPAIR`. The service moves immediately from `REQUESTED` to `IN_CHAIR`, and the appliance's `in_patient_possession` stays true — the patient keeps the denture.
- **Laboratory**: `HARD_RELINE_LAB`, `REBASE`, `TOOTH_ADDITION`, and `CLASP_ADDITION`. The service moves immediately from `REQUESTED` to `AT_LAB`, a lab case is auto-created in `DRAFT` on the appliance's parent arch, the service's `lab_case_id` is set to that new lab case, and `in_patient_possession` is set to **false** — the appliance has left the patient. The auto-created lab case takes its `dental_lab_id` and `bench_line` from the service request, and is minted with `turnaround_class` `STANDARD`, `unit_count` 1, and `lab_invoice_amount` 450.00. Its `purpose` is derived from the service type: a hard reline becomes `RELINE`, a rebase becomes `REBASE`, and both a tooth addition and a clasp addition become `ADDITION`.

That divergence of side effects is the entire point of the fork: only the laboratory branch mints a lab case and only the laboratory branch takes the appliance out of the patient's possession.

Requesting a service also **supersedes**. Any older service of the same `service_type` on the same appliance that has not completed — one sitting in `REQUESTED`, `IN_CHAIR`, or `AT_LAB` — is moved to `VOIDED` with `voided_at` stamped; if that superseded row was `AT_LAB`, its linked lab case is cancelled, its bench-line reservation released, and `in_patient_possession` restored to true. This supersede is why the create is guarded by `expected_prosthesis_version`, as §2.8 explains. Every service request increments the appliance's `version` by 1.

Two eligibility rules stand between a request and its acceptance, evaluated in this order. First, **type eligibility**: a `CLASP_ADDITION` is only accepted on a partial — that is, on a `CAST_PARTIAL` or a `FLEXIBLE_PARTIAL` — and a `REBASE` is refused outright on a `FLEXIBLE_PARTIAL`, both refusals carrying `ERR_SERVICE_NOT_ELIGIBLE`. Second, **frequency**: each service type has a minimum interval, expressed in whole calendar months, that must have elapsed since the most recent completed service of that same type on that same appliance. A hard reline may be repeated only every 24 months; a chairside soft reline only every 6 months; a rebase only every 36 months. Adjustments, repairs, tooth additions, and clasp additions carry an interval of zero months, which means no limit at all. Where the interval is non-zero, the server finds the most recent completed service of that type on that appliance — ordering candidates by `completed_at` descending and breaking ties by `created_at` descending, and ignoring voided rows entirely — and requires the logical clock to be at or after that row's `completed_at` plus the interval. The boundary is inclusive: exactly 24 months after a hard reline, another hard reline is permitted. When no completed service of that type exists on the appliance, the request is eligible. A request inside the interval is refused with `ERR_SERVICE_FREQUENCY_LIMIT`.

Requesting a service is inside the global write gate — with the emergency carve-out of §2.11, which requires both that `service_type` is `REPAIR` and that `is_emergency_repair` is true. Completing and voiding a service both sit outside the gate.

**Completing a service** is a `Prosthodontist` act. A chairside service completes straight from `IN_CHAIR`. A laboratory service completes from `AT_LAB` only once its linked lab case has reached `QC_PASSED`; completing earlier is refused with `ERR_CROSS_ENTITY_STATE`. Completion fixes the money classification on the row, and the rule has a dual character on adjustments:

- For an `ADJUSTMENT`, two conditions are tested. The count condition is that the appliance's `adjustments_used` is **strictly below 4**; the window condition is that the logical clock is **at or before** `adjustment_window_ends_at`, which is inclusive of the boundary instant. When both hold, `charge_basis` is `INCLUDED` and `charge_amount` is 0.00, and the completion consumes one unit of the allowance: `adjustments_used` rises by one and `adjustments_remaining` falls by one. When either fails — the fifth adjustment, or any adjustment after the 90-day window closes — `charge_basis` is `CHARGEABLE`, `charge_amount` is 85.00, and **neither allowance counter moves**, which is what keeps the conservation invariant of §2.13 intact on that path.
- Otherwise, when the service is one a warranty claim in `CLINIC_FAULT` or `LAB_FAULT` was raised over — a claim citing this service through its `post_delivery_service_id` — `charge_basis` is `WARRANTY_NO_CHARGE` and `charge_amount` is 0.00.
- Otherwise `charge_basis` is `CHARGEABLE` and `charge_amount` is the fee for the service type: 260.00 for a chairside soft reline, 420.00 for a laboratory hard reline, 590.00 for a rebase, 180.00 for a repair, 155.00 for a tooth addition, and 195.00 for a clasp addition. All fees are carried to two decimal places.

Completion also stamps `completed_at`, adds `charge_amount` to the parent case's `billed_amount` and recomputes the case's patient responsibility as described in §3.9, restores `in_patient_possession` to true when the row was a laboratory service, and increments the service's `version` by 1.

**Voiding a service** is available to a `FrontOffice` or `Prosthodontist` operator. From `REQUESTED` or `IN_CHAIR` it simply stamps `voided_at` and moves the row to `VOIDED`. From `AT_LAB` it additionally cancels the linked lab case, releases its bench-line reservation, and restores `in_patient_possession` to true. From `COMPLETED` it is the declared **compensating action**: when the voided row was an adjustment classified as `INCLUDED`, `adjustments_used` falls by one and `adjustments_remaining` rises by one, restoring the allowance; the row's `charge_amount` is subtracted from the case's `billed_amount` and the case's patient responsibility recomputed; `charge_amount` is then set to 0.00; and `voided_at` is stamped. Every void increments the service's `version` by 1.

`COMPLETED` is deliberately **not** a terminal state of the service axis — void is its declared compensating action and must stay reachable. `VOIDED` is the only terminal state. Every trigger other than void attempted from `COMPLETED` is refused with `ERR_INVALID_STATE`. Services can be listed and filtered by `prosthesis_id`, by `lab_case_id`, by `service_type`, and by `service_status`.

When an appliance fails and somebody has to pay for it, a **warranty claim** decides who. A `Prosthodontist` or a `FrontOffice` operator opens one against a delivered appliance, outside the write gate, supplying the `prosthesis_id` and a free-text `reported_issue`, and optionally a `post_delivery_service_id` naming the service whose result the patient disputes and an `attributed_lab_case_id` naming the lab case whose workmanship is under suspicion. The claim is born in `SUBMITTED` with `fault_verdict` null, `lab_credit_amount` 0.00, `patient_charge_amount` 0.00, `warranty_consumed` false, and `adjudicated_at` null.

Adjudication belongs to the `ClinicalDirector` alone and is outside the write gate — fault adjudication decides who owes the money, and letting the clinic's own receivable block it would let the clinic profit from its own delay. The adjudicating director supplies a `fault_verdict` taking one of four values, and the claim fans out four ways:

- **`CLINIC_FAULT`** sets `warranty_consumed` to true, `lab_credit_amount` to 0.00, and `patient_charge_amount` to 0.00, stamps `adjudicated_at`, and moves the referenced appliance `IN_WARRANTY → WARRANTY_CONSUMED`. The clinic absorbs the whole cost.
- **`LAB_FAULT`** sets `warranty_consumed` to true and `patient_charge_amount` to 0.00, stamps `adjudicated_at`, moves the appliance `IN_WARRANTY → WARRANTY_CONSUMED`, and computes a credit: `lab_credit_amount` is the attributed lab case's `lab_invoice_amount` multiplied by 0.60, rounded half up to two decimal places — so a lab case invoiced at the default 450.00 yields a credit of 270.00. That amount is added to the attributed laboratory's `credit_issued_total` and to its `credit_available_balance`, leaving `credit_applied_total` untouched. This leg requires the claim to carry an `attributed_lab_case_id`.
- **`PATIENT_FAULT`** sets `warranty_consumed` to **false** — the warranty is deliberately *not* consumed — leaves `lab_credit_amount` at 0.00, sets `patient_charge_amount` to 180.00, adds that amount to the case's `billed_amount` and recomputes the case's patient responsibility, stamps `adjudicated_at`, and leaves the appliance in `IN_WARRANTY`. The patient broke it, the patient pays, and the warranty survives for a future genuine failure.
- **`INDETERMINATE`** moves the claim to `CLINICAL_REVIEW` rather than to any terminal verdict, records `INDETERMINATE` in `fault_verdict`, and leaves `lab_credit_amount`, `patient_charge_amount`, and `warranty_consumed` at their defaults. No money moves and the appliance is untouched.

Every one of the four increments the claim's `version` by 1. Two ladder rungs guard the whole family. Rung 23 refuses adjudication against an appliance whose `warranty_status` is `WARRANTY_CONSUMED` or `WARRANTY_VOIDED` with `ERR_WARRANTY_CONSUMED`; an appliance in `WARRANTY_EXPIRED` deliberately passes that rung so the next one can speak. Rung 24 then refuses a `CLINIC_FAULT` or `LAB_FAULT` verdict recorded after the appliance's `warranty_expires_at` with `ERR_WARRANTY_EXPIRED`, and is deliberately not applied to a `PATIENT_FAULT` or `INDETERMINATE` verdict, because a chargeable verdict does not depend on the warranty window at all.

A claim parked in `CLINICAL_REVIEW` is resolved by the same role through a second decision carrying a `resolved_verdict` of `CLINIC_FAULT`, `LAB_FAULT`, or `PATIENT_FAULT`. Each resolution applies **exactly** the side-effect set of the corresponding adjudication leg above — the same money fields, the same warranty movement, the same credit arithmetic on a lab-fault resolution, the same `adjudicated_at` stamp — and increments the claim's `version` by 1. The lab-fault resolution likewise requires an `attributed_lab_case_id`. Both adjudication and clinical review are subject to rungs 23 and 24 in the same way. `CLINIC_FAULT`, `LAB_FAULT`, and `PATIENT_FAULT` are the three terminal states of the claim axis. Warranty claims can be listed and filtered by `prosthesis_id`, by `post_delivery_service_id`, by `attributed_lab_case_id`, and by `claim_status`.

*Friction point — a lab-fault verdict without an attributed lab case.* The lab-fault legs above require `attributed_lab_case_id` to be present, while the credit rule separately describes a zero-credit outcome for "a lab-fault verdict with no attributed lab case". This document records both statements without resolving whether such a verdict is admissible; where it is admitted, the credit is 0.00 and no laboratory ledger moves. A lab-fault verdict submitted with no `attributed_lab_case_id` is otherwise treated as a missing required input and refused with `ERR_VALIDATION`.

**Remaking an arch** is the last resort, and it is deliberately a two-person operation. A `Prosthodontist` requests the remake, inside the write gate, naming the `case_arch_id`, a `reason_code` of `TRYIN_REJECTED`, `FIT_FAILURE`, `LAB_DEFECT`, `PATIENT_DISSATISFACTION`, or `RECALL_EVALUATION`, and optionally the `warranty_claim_id` of the adjudicated fault the remake answers. The row is created in `PENDING_APPROVAL` with `requested_by_user_id` stamped from the calling `X-User-ID`, `decided_at` and `approved_by_user_id` null, and `attempt_number` set to the arch's `remake_request_count` plus one — after which the arch's `remake_request_count` itself rises by one. Its `charge_basis` is `NO_CHARGE` when the cited warranty claim is in `CLINIC_FAULT` or `LAB_FAULT`, and `CHARGEABLE` in every other case, including when no claim is cited at all. The system mints requests of this shape for itself in two places already described: a rejected try-in mints one with `reason_code` `TRYIN_REJECTED`, and a recall closed for remake evaluation mints one with `reason_code` `RECALL_EVALUATION`.

The counter that the ceiling watches is `remake_request_count`, and it counts the arch's remake requests whose `authorization_status` is `PENDING_APPROVAL`, `APPROVED`, or `DENIED`. Rows in `FINAL_DENIED` are deliberately excluded from it, so the counter cannot run away once the ceiling has been hit. An arch may accumulate at most two such requests; a third request trips the mutate-then-reject behaviour of §2.12, and every request after that is pre-empted by the arch's `remake_eligibility` of `FINAL_DENIED`. Separately, the arch carries `remake_count`, which counts only the requests that were actually approved.

Deciding a remake belongs to the `ClinicalDirector` and sits outside the write gate, because the request creation was already gated and deciding an existing request is not a new start. Both decisions are subject to segregation of duties: the deciding `X-User-ID` must differ from the request's `requested_by_user_id`, and a self-decision is refused with `ERR_SEGREGATION_OF_DUTIES`. **Denial** — which may carry an optional `denial_reason` — moves the row to `DENIED`, records `approved_by_user_id` and `decided_at`, leaves the parent arch entirely untouched, and increments the request's `version` by 1.

**Approval** requires, beyond segregation of duties, that the parent arch is in `DELIVERED` or `MILESTONE_PENDING`, and — when the request cites a `warranty_claim_id` — that the cited claim's `claim_status` is `CLINIC_FAULT` or `LAB_FAULT`, failing which the approval is refused with `ERR_CROSS_ENTITY_STATE`. Approval then runs the **remake cascade**, six links deep, each caused by the one before it:

- **Link 1** sets `authorization_status` to `APPROVED`, records `approved_by_user_id` and `decided_at`, and increments the request's `version` by 1.
- **Link 2**, caused by link 1, moves the parent arch to `REMAKE_PENDING` — from `DELIVERED` when the appliance was already handed over, or from `MILESTONE_PENDING` when a try-in was rejected before any delivery ever happened — increases the arch's `remake_count` by one, and increments the arch's `version` by 1.
- **Link 3**, caused by link 2, sets the arch's most recent appliance to `warranty_status` `WARRANTY_VOIDED` and `recall_status` `RECALL_CLOSED_SUPERSEDED`, and moves every lab case of that arch whose `lab_status` is `DRAFT`, `DISPATCHED`, `RETURNED`, `QC_FAILED`, or `RESENT` to `CANCELLED`.
- **Link 4**, caused by link 3, moves laboratory credit — but only when the request's `charge_basis` is `NO_CHARGE` and the cited warranty claim is in `LAB_FAULT`. The amount applied is the lesser of the claim's `lab_credit_amount` and the attributed laboratory's `credit_available_balance`. The laboratory's `credit_applied_total` rises by that amount and its `credit_available_balance` falls by the same, with `credit_issued_total` untouched — the conservation of §2.13 holding across the move.
- **Link 5**, caused by link 4, applies that credit to the case's payment plan whose `plan_status` is `ACTIVE` or `DELINQUENT`: the plan's `principal_amount` falls by the applied amount, its `applied_lab_credit_amount` rises by it, and its still-open installments are re-struck as described in §3.9.
- **Link 6**, caused by link 5, moves the re-struck plan to `PAID_OFF` when its `outstanding_amount` reaches 0.00 — which, when it is the patient's only delinquent plan, lowers the global write gate.

Alongside those six, approval moves the parent case back from `DELIVERED` to `IN_FABRICATION` when the case was in `DELIVERED`, clearing the case's `delivered_at` back to null and incrementing the case's `version` by 1. That is the case-level cycle: a case that already delivered re-enters fabrication when one of its arches is remade, while the sibling arch stays exactly where it was. From `REMAKE_PENDING` the arch restarts through the fabrication-start action of §3.2, closing the per-arch cycle `DELIVERED → REMAKE_PENDING → IMPRESSION_PENDING`. `APPROVED`, `DENIED`, and `FINAL_DENIED` are the three terminal states of the authorisation axis. Remake requests can be listed and filtered by `case_arch_id`, by `warranty_claim_id`, and by `authorization_status`; that listing is also the only way to discover a `FINAL_DENIED` row minted by the ceiling.

### 3.8. Insurance: Predetermination, Claims and Coordination of Benefits

Expensive removable prosthetics are rarely started without asking the carrier first. When a case's `fee_schedule_total` reaches 1500.00 the case's `predetermination_required` becomes true, and from that moment neither fabrication nor claim submission can proceed without a live carrier answer in hand.

A `FrontOffice` operator submits a preauthorization by naming the `case_id` and the `coverage_id` it is sent to. The row is created in `SUBMITTED`, with `requested_amount` fixed at the case's `fee_schedule_total` as observed at that instant, `allowed_amount`, `estimated_plan_payment`, and `estimated_patient_responsibility` all at 0.00, and `alternate_benefit_type`, `determined_at`, and `expires_at` all null. Predeterminations are outside the write gate, because insurance work reduces the balance and is part of the remedy path. They can be listed and filtered by `case_id`, by `coverage_id`, and by `determination_status`.

The carrier's answer arrives as a `determination` of `APPROVED`, `ALTERNATE_BENEFIT`, or `DENIED`, accepted only while the row is still in `SUBMITTED`, and the three answers fan out:

- **`APPROVED`** sets `allowed_amount` equal to `requested_amount` and leaves `alternate_benefit_type` null. The plan pays coinsurance on what was actually requested.
- **`ALTERNATE_BENEFIT`** is the carrier downgrading the treatment to a cheaper alternative it is willing to fund. It requires the cited coverage's `alternate_benefit_enabled` to be true and requires the case's `prosthesis_type` to have a declared downgrade target; an implant-retained overdenture and a plain overdenture both downgrade to `COMPLETE_DENTURE`, and a cast partial downgrades to `FLEXIBLE_PARTIAL`, while the other three types have no declared target. A determination that cannot satisfy both conditions is refused with `ERR_VALIDATION`. When it can, `alternate_benefit_type` is set to the downgrade target and `allowed_amount` is set to the fee of that target type — 1800.00 for a complete denture, 1200.00 for a flexible partial — multiplied by the number of the case's arches whose `arch_status` is not `ARCH_ABANDONED`. A two-arch implant-retained overdenture requested at 7200.00 is therefore allowed at 3600.00, and the patient owes the whole difference.
- **`DENIED`** sets `allowed_amount` to 0.00, `estimated_plan_payment` to 0.00, and `estimated_patient_responsibility` to the full `requested_amount`. It stamps `determined_at` and leaves `expires_at` null — a denial never enters a validity window.

For the two paying answers the estimate is computed the same way from whichever allowed basis the branch produced. The uncapped estimate is `allowed_amount` multiplied by the cited coverage's `coinsurance_major_rate`, rounded half up to two decimal places; `estimated_plan_payment` is then the lesser of that rounded figure and the coverage's `benefit_remaining` — the cap is applied **after** the rounding, never before. `estimated_patient_responsibility` is `requested_amount` minus `estimated_plan_payment`, rounded half up to two decimal places. On a standard coverage paying half of an approved 1800.00 case, the estimate is 900.00 unless only 700.00 of annual benefit is left, in which case it is 700.00.

Both paying answers stamp `determined_at` with the logical clock and compute `expires_at` as `determined_at` plus 180 calendar days. All three answers increment the predetermination's `version` by 1. Once the logical clock passes `expires_at` strictly, an `APPROVED` or `ALTERNATE_BENEFIT` row moves lazily to `EXPIRED` — evaluated on every read or handling of the row, including a read of the row itself — with a further `version` increment. `DENIED` and `EXPIRED` are the two terminal states of the determination axis, and only `APPROVED` or `ALTERNATE_BENEFIT` rows still inside their validity window satisfy the predetermination gate at rung 30.

**Claims** run a two-stage coordination of benefits. One claim is opened per case against its primary coverage — either by the `FrontOffice` naming a `case_id` and a `coverage_id`, or automatically by the delivery cascade of §3.6 — and starts in `DRAFT` with `submission_target` `PRIMARY`, every money field at 0.00, `predetermination_id`, `cob_convention_applied`, `submitted_at`, `adjudicated_at`, and `reversed_at` all null. Claims are outside the write gate and can be listed and filtered by `case_id`, by `coverage_id`, by `predetermination_id`, and by `adjudication_status`.

Submitting a claim is one action that behaves differently depending on the stage the claim has reached. Its first stage moves `DRAFT → SUBMITTED_PRIMARY` and runs four ladder rungs in strict order — 28, 29, 30, then 31:

1. **Waiting period.** The logical clock must be at or after the primary coverage's `effective_date` plus its `waiting_period_days` days; earlier is `ERR_WAITING_PERIOD`. On a coverage left at its default of 180 days, a claim submitted 179 days after enrolment fails and one submitted on day 180 passes.
2. **Replacement frequency.** Consider the appliances belonging to this patient through cases **other than** this claim's own case. When that set is non-empty, the logical clock must be at or after the greatest `replacement_eligible_date` across it; earlier is `ERR_FREQUENCY_LIMIT`. Because a remake never advances `frequency_anchor_at`, a remade appliance buys the patient no new replacement window here.
3. **Predetermination gate.** When the case's `predetermination_required` is true, a determination for the case must exist in `APPROVED` or `ALTERNATE_BENEFIT` with `expires_at` strictly after the logical clock; otherwise `ERR_PREDETERMINATION_REQUIRED`.
4. **Annual maximum.** The primary coverage's `benefit_remaining` must be strictly greater than 0.00; a coverage at exactly 0.00 yields `ERR_ANNUAL_MAX_EXHAUSTED`.

A first-stage submission that clears all four sets `billed_amount` to the case's `fee_schedule_total`, resolves `predetermination_id` to the case's determination whose `determination_status` is `APPROVED` or `ALTERNATE_BENEFIT` with the latest `created_at` — or to null when none exists — sets `allowed_amount` to that determination's `allowed_amount` when one was resolved and to `billed_amount` otherwise, keeps `submission_target` at `PRIMARY`, stamps `submitted_at`, and increments the claim's `version` by 1.

The second stage moves `PRIMARY_PAID → SUBMITTED_SECONDARY` and requires that exactly one coverage exists for the case's patient at `rank` `SECONDARY`; the waiting-period rung is then re-run against **that** coverage rather than the primary one. It sets `submission_target` to `SECONDARY`, copies the secondary coverage's `cob_convention` into the claim's `cob_convention_applied`, stamps `submitted_at` afresh, and increments the claim's `version` by 1.

Recording the carrier's adjudication carries an `adjudication_outcome` of `PAID` or `DENIED`, and what it does depends on which stage is outstanding.

**Primary paid.** The uncapped payment is the claim's `allowed_amount` multiplied by the primary coverage's `coinsurance_major_rate`, rounded half up to two decimal places; `primary_paid_amount` is the lesser of that rounded figure and the primary coverage's `benefit_remaining`, the cap again applied after the rounding. `plan_paid_amount` is set equal to `primary_paid_amount`. The claim's own `patient_responsibility_amount` is `billed_amount` minus `plan_paid_amount`, rounded half up to two decimal places and floored at 0.00. The primary coverage's `benefit_used_ytd` rises by `primary_paid_amount` and its `benefit_remaining` falls by the same. The case's `insurance_paid_amount` and `patient_responsibility_amount` are recomputed as described in §3.9, `adjudicated_at` is stamped, and the claim's `version` increments by 1. When the patient holds no coverage at `SECONDARY`, the claim then moves straight on to `CLOSED` with a further `version` increment.

**Primary denied.** `primary_paid_amount` and `plan_paid_amount` stay at 0.00, the claim's `patient_responsibility_amount` becomes the full `billed_amount`, `adjudicated_at` is stamped, the claim moves to `DENIED`, and its `version` increments by 1.

**Secondary paid.** This is the dual-variant leg, and the convention recorded in `cob_convention_applied` selects the formula. Two intermediate quantities are computed first, both rounded half up to two decimal places: the amount the secondary *would have* paid as a primary, which is the claim's `allowed_amount` multiplied by the secondary coverage's `coinsurance_major_rate`; and the patient's outstanding balance, which is `billed_amount` minus `primary_paid_amount`, floored at 0.00. Then:

- Under the **`STANDARD`** convention, the secondary tops the patient up towards the allowed amount: the raw figure is the lesser of (the claim's `allowed_amount` minus `primary_paid_amount`, rounded half up to two decimal places) and the patient's outstanding balance.
- Under the **`NON_DUPLICATION`** convention, the secondary pays only the excess of what it would have paid over what the primary actually paid: the raw figure is the amount it would have paid as a primary minus `primary_paid_amount`, rounded half up to two decimal places and floored at 0.00. Where the primary already paid at least as much, the secondary pays nothing.

In both conventions, `secondary_paid_amount` is the raw figure floored at 0.00 and then capped at the secondary coverage's `benefit_remaining`. `plan_paid_amount` becomes `primary_paid_amount` plus `secondary_paid_amount`, rounded half up to two decimal places, and the claim's `patient_responsibility_amount` becomes `billed_amount` minus `plan_paid_amount`, rounded half up and floored at 0.00. The secondary coverage's `benefit_used_ytd` rises by `secondary_paid_amount` and its `benefit_remaining` falls by the same, the case's money fields are recomputed, `adjudicated_at` is stamped, the claim's `version` increments by 1, and the claim then moves on to `CLOSED` with a further increment.

**Secondary denied.** `secondary_paid_amount` stays at 0.00, `plan_paid_amount` stays equal to `primary_paid_amount`, `adjudicated_at` is stamped, the claim moves to `DENIED`, and its `version` increments by 1.

A closed claim can still be **reversed**, optionally carrying a `reversal_reason`, and that reversal is the declared compensating action of the coverage-benefit conservation. It decreases the primary coverage's `benefit_used_ytd` by `primary_paid_amount` and the secondary coverage's `benefit_used_ytd` by `secondary_paid_amount`, restoring both `benefit_remaining` figures to their pre-adjudication values; sets `primary_paid_amount`, `secondary_paid_amount`, and `plan_paid_amount` all to 0.00; recomputes the case's `insurance_paid_amount` and `patient_responsibility_amount`; stamps `reversed_at`; and increments the claim's `version` by 1. `CLOSED` is deliberately **not** a terminal state of the adjudication axis, precisely so that reversal stays reachable; every trigger other than reversal attempted from `CLOSED` is refused with `ERR_INVALID_STATE`. `DENIED` and `REVERSED` are the two terminal states.

### 3.9. The Case Balance, Payment Plans and Collections

Everything the patient owes is derived, never stored by hand, and it is derived in a fixed nine-step order. The order matters most at step 7, where a discount tier is chosen: **the tier is keyed on the responsibility figure computed at step 6, before any discount is struck, and it is never re-derived from the post-discount total.** The whole computation re-runs whenever a lab case is dispatched, a post-delivery service is completed, a post-delivery service is voided, a warranty claim is adjudicated, a claim payment is posted, a claim is reversed, and a payment plan is created.

1. The **gross fee** is the case's `fee_schedule_total`.
2. The **rush total** is the sum of `rush_fee_amount` over the case's lab cases whose `lab_status` is `DISPATCHED`, `RETURNED`, `QC_PASSED`, `QC_FAILED`, `RESENT`, or `EXPIRED`. A lab case still in `DRAFT` has no rush fee yet, and a `CANCELLED` lab case's rush fee drops out of the total.
3. The **service total** is the sum of `charge_amount` over the case's post-delivery services whose `service_status` is `COMPLETED`, plus the sum of `patient_charge_amount` over the case's warranty claims whose `claim_status` is `PATIENT_FAULT`.
4. `billed_amount` is the gross fee plus the rush total plus the service total, rounded half up to two decimal places.
5. `insurance_paid_amount` is the sum of `plan_paid_amount` over the case's claims whose `adjudication_status` is `PRIMARY_PAID`, `SECONDARY_PAID`, or `CLOSED`.
6. The **pre-discount responsibility** is `billed_amount` minus `insurance_paid_amount`, rounded half up to two decimal places and floored at 0.00.
7. The **discount rate** is chosen from the pre-discount responsibility of step 6 alone, with both tier boundaries inclusive on their lower edge: 0.05 when it is at or above 2500.00; 0.03 when it is at or above 1000.00 but below 2500.00; and 0.00 below 1000.00.
8. `prompt_pay_discount_amount` is the pre-discount responsibility multiplied by that rate, rounded half up to two decimal places — **but only when the case has a payment plan whose `plan_status` is `ACTIVE` or `DELINQUENT` and whose `pay_in_full` is true.** In every other situation it is 0.00.
9. `patient_responsibility_amount` is the pre-discount responsibility minus `prompt_pay_discount_amount`, rounded half up to two decimal places.

All of the sums above are order-independent, so no tie-break is required anywhere in this computation.

A **payment plan** finances what is left. A `FrontOffice` operator creates one — outside the write gate, because establishing or replacing a plan is precisely the remedy for a gated account — by supplying `patient_id`, `case_id`, `installment_count`, `down_payment_amount`, `first_due_date`, `frequency`, and `expected_prosthesis_case_version`, and optionally `pay_in_full`, which defaults to false. `installment_count` must be at least 2 and at most 12. `frequency` is `MONTHLY` or `BIWEEKLY`.

The sequence of checks and effects at creation is pinned, because the down-payment floor and the discount interact. The floor is checked **first**, and it is checked against the **pre-discount** responsibility: `down_payment_amount` must be at least 0.20 times the case's `patient_responsibility_amount` as it stands before any prompt-pay discount is struck, and a smaller down payment is a rung 7 failure carrying `ERR_VALIDATION`. Only once that check has passed is the prompt-pay discount applied to the case — steps 7 and 8 above, which now see a live plan with `pay_in_full` true — and only then is the plan's `principal_amount` struck as the resulting `patient_responsibility_amount` minus `down_payment_amount`, rounded half up to two decimal places.

Creating a plan also **supersedes**. Any existing plan on the same case whose `plan_status` is `ACTIVE` or `DELINQUENT` moves to `SUPERSEDED`, has its `superseded_by_plan_id` set to the new plan's identifier, and has every one of its own installments still sitting in `SCHEDULED` or `MISSED` moved to `WAIVED`; where the superseded plan was `DELINQUENT`, its `missed_count` is recomputed to zero and the patient's `write_gate_active` falls back to false unless some other plan of that patient is still `DELINQUENT` or `DEFAULTED`. The case's `version` increments by 1. This supersede is what `expected_prosthesis_case_version` guards, as §2.8 explains.

**Minting the schedule** follows a rounding order that is easy to get wrong. The per-installment base is `principal_amount` divided by `installment_count`, rounded half up to two decimal places. Every installment from the first up to the second-to-last carries exactly that base as its `amount`. The final installment — the one whose `sequence_number` equals `installment_count` — carries `principal_amount` minus the base multiplied by one less than `installment_count`, rounded half up to two decimal places, and it is the only row whose `is_residual_installment` is true. Summing first and rounding once at the end produces a different schedule and is wrong here. A principal of 1000.00 over 3 installments therefore yields 333.33, 333.33, and 333.34.

Due dates are struck from `first_due_date`: installment number *k* falls due at `first_due_date` plus one less than *k* multiplied by the spacing, where the spacing is 30 days for a `MONTHLY` plan and 14 days for a `BIWEEKLY` plan. Each installment is born in `SCHEDULED` with `paid_at` null. The plan itself is born in `ACTIVE` with `paid_amount` at 0.00, `outstanding_amount` equal to `principal_amount`, `missed_count` at zero, `applied_lab_credit_amount` at 0.00, and `superseded_by_plan_id` null. Throughout the plan's life, `paid_amount` is the sum of `amount` over its installments in `PAID` plus the sum over those in `WAIVED`, and `outstanding_amount` is `principal_amount` minus `paid_amount`. Plans can be listed and filtered by `patient_id`, by `case_id`, by `superseded_by_plan_id`, and by `plan_status`; installments by `payment_plan_id` and by `installment_status`.

**Paying** an installment is available to the owning `Patient` and to a `FrontOffice` operator, and it sits outside the write gate for the obvious reason: gating the cure would make the gate unrecoverable. The payer supplies `amount_paid`, which must be strictly greater than zero and must equal the installment's `amount` to the cent; a mismatch is refused with `ERR_VALIDATION`. A payment moves the row `SCHEDULED → PAID` or `MISSED → PAID`, stamps `paid_at`, raises the plan's `paid_amount` by the installment's `amount`, lowers its `outstanding_amount` by the same, and increments the installment's `version` by 1. Paying a row that was `MISSED` additionally lowers the plan's `missed_count` by one, and when `missed_count` reaches zero the plan **cures** back from `DELINQUENT` or `DEFAULTED` to `ACTIVE` — which sets the patient's `write_gate_active` to false unless another plan of that patient is still delinquent or defaulted, lowering the global write gate. When `outstanding_amount` reaches 0.00 the plan moves to `PAID_OFF`; from `DELINQUENT` that move additionally requires `missed_count` to be zero, and it likewise lowers the write gate where no other broken plan remains.

**Reversing** a posted payment belongs to the `FrontOffice`, sits outside the write gate so a mis-posted payment can be undone even on a gated account, and is the declared compensating action of the payment-plan conservation. It is available from `PAID`, and the destination is decided by where the logical clock sits relative to the grace boundary rather than by anything the caller says: when the clock is **at or before** the installment's `due_date` plus 10 days the row returns to `SCHEDULED`, and when the clock is **strictly after** that instant the row goes to `MISSED` instead and the plan's `missed_count` rises by one, which will re-raise the write gate through the plan's delinquency transition at the next sweep. Either way the plan's `paid_amount` falls by the installment's `amount`, its `outstanding_amount` rises by the same, `paid_at` is cleared back to null, and the installment's `version` increments by 1.

**The delinquency sweep** is what raises and lowers the gate, so it necessarily sits outside the gate itself. A `PlatformAdmin` or `FrontOffice` operator runs it against one plan. It walks that plan's installments in `SCHEDULED` only — rows in `PAID` and `WAIVED` are never swept — and moves to `MISSED` every row whose `due_date` plus 10 days is **strictly before** the logical clock. The grace boundary is strict on that side: an installment observed at exactly 10 days after its `due_date` is still on time and is not swept. Each swept row increments the plan's `missed_count` by one and its own `version` by 1. The plan's `missed_count` is then re-derived as the count of its installments sitting in `MISSED`, and the plan's status follows from it: at 3 or more the plan is `DEFAULTED`; at 1 or 2 it is `DELINQUENT`; at zero the plan's status is left exactly as it was. A sweep that leaves the plan `DELINQUENT` or `DEFAULTED` sets the patient's `write_gate_active` to true. The declared movements are `ACTIVE → DELINQUENT`, `ACTIVE → DEFAULTED`, and `DELINQUENT → DEFAULTED`, and the sweep increments the plan's `version` by 1.

**Re-striking a schedule after a laboratory credit** is the last piece, and it is the fifth link of the remake cascade of §3.7. The amount actually applied is the lesser of the warranty claim's `lab_credit_amount` and the laboratory's `credit_available_balance`. The plan's `principal_amount` falls by that amount and its `applied_lab_credit_amount` rises by it, both rounded half up to two decimal places; on the laboratory side `credit_applied_total` rises by the same amount and `credit_available_balance` falls by it. The credit is then consumed against the plan's still-open installments — those in `SCHEDULED` or `MISSED`, with rows in `PAID` and `WAIVED` excluded — **processed in descending `sequence_number` order, from the last open row backwards, so that the earliest due dates are preserved**. `sequence_number` is unique within a plan, so no tie-break is needed. Each row absorbs the lesser of its own `amount` and whatever credit remains: its `amount` falls by that much, rounded half up to two decimal places, the remaining credit falls by the same, and a row driven to 0.00 moves to `WAIVED`. A row waived out of `SCHEDULED` simply counts as satisfied in the plan's `paid_amount`; a row waived out of `MISSED` counts as satisfied and additionally lowers `missed_count` by one. Finally the plan's `outstanding_amount` is re-derived as `principal_amount` minus `paid_amount`, rounded half up to two decimal places, and a plan whose `outstanding_amount` reaches 0.00 moves to `PAID_OFF`.

`PAID_OFF` and `SUPERSEDED` are the two terminal states of the plan axis; `WAIVED` is the only terminal state of the installment axis, since `PAID` must remain reversible and `MISSED` must remain curable.

## 4. Endpoint Definitions

Every endpoint that mints a brand-new resource answers with HTTP 201; every endpoint that modifies an existing resource, and every read, answers with HTTP 200. The clock-setting endpoint answers 200 as well, since it creates no resource. The request and response shapes are not repeated here — they are established by the workflow narratives in §3 — and the table below carries only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/prosthetics/_clock/set_current_utc` | Sets the server's logical clock to a supplied instant and answers with the resulting clock. | `PlatformAdmin` |
| POST | `/prosthetics/patients` | Registers a patient. | `FrontOffice`, `PlatformAdmin` |
| GET | `/prosthetics/patients/{patient_id}` | Reads one patient; a `Patient` caller may only read its own row. | `FrontOffice`, `Prosthodontist`, `ClinicalDirector`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/patients` | Lists patients. | `FrontOffice`, `Prosthodontist`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/coverages` | Enrols a patient in an insurance coverage at a given coordination-of-benefits rank. | `FrontOffice`, `PlatformAdmin` |
| GET | `/prosthetics/coverages/{coverage_id}` | Reads one coverage. | `FrontOffice`, `PlatformAdmin`, `Prosthodontist` |
| GET | `/prosthetics/coverages` | Lists coverages, optionally filtered by patient and rank. | `FrontOffice`, `PlatformAdmin`, `Prosthodontist` |
| POST | `/prosthetics/labs` | Registers an external dental laboratory; the returned identifier is what a `LabTechnician` sends as `X-User-ID`. | `PlatformAdmin` |
| GET | `/prosthetics/labs/{lab_id}` | Reads one laboratory, including its credit ledger fields. | `PlatformAdmin`, `FrontOffice`, `Prosthodontist`, `LabTechnician` |
| GET | `/prosthetics/labs` | Lists laboratories. | `PlatformAdmin`, `FrontOffice`, `Prosthodontist` |
| POST | `/prosthetics/cases` | Opens a prosthesis case for a patient at a chosen prosthesis type. Inside the global write gate. | `Prosthodontist`, `FrontOffice` |
| GET | `/prosthetics/cases/{case_id}` | Reads one case, including its derived money fields. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/cases` | Lists cases. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/cases/{case_id}/complete-exam` | Closes the exam stage: prices every arch, totals the case, and decides whether a predetermination is required. | `Prosthodontist` |
| POST | `/prosthetics/cases/{case_id}/cancel` | Cancels a case and cascades the cancellation to its arches, try-ins, and open lab cases. | `Prosthodontist` |
| POST | `/prosthetics/case-arches` | Adds an arch unit to a case, at most one per position. Inside the global write gate. | `Prosthodontist` |
| GET | `/prosthetics/case-arches/{case_arch_id}` | Reads one arch, including its required, completed, and next-required milestones. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| GET | `/prosthetics/case-arches` | Lists arches. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/case-arches/{case_arch_id}/start-fabrication` | Starts — or, after a remake, restarts — fabrication on one arch. Inside the global write gate; also enforces the predetermination gate. | `Prosthodontist` |
| POST | `/prosthetics/impressions` | Records an impression or digital scan on an arch. Inside the global write gate. | `Prosthodontist` |
| GET | `/prosthetics/impressions/{impression_id}` | Reads one impression record. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| GET | `/prosthetics/impressions` | Lists impression records. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/impressions/{impression_id}/review` | Scores an impression and assigns one of the three quality bands. Outside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/impressions/{impression_id}/request-retake` | Supersedes a provisionally-accepted or rejected record and mints its successor; answers with the superseded row. Inside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/try-ins` | Books the next required try-in milestone on an arch. Inside the global write gate; enforces the milestone sequence. | `Prosthodontist` |
| GET | `/prosthetics/try-ins/{try_in_id}` | Reads one try-in milestone. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| GET | `/prosthetics/try-ins` | Lists try-in milestones. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/try-ins/{try_in_id}/decide` | Records the clinical decision on a try-in, including the resubmission leg that closes the adjust cycle. Outside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/lab-cases` | Creates a draft lab case for an arch, superseding an existing draft on the same arch. Version-guarded on the arch. Inside the global write gate. | `Prosthodontist`, `FrontOffice` |
| GET | `/prosthetics/lab-cases/{lab_case_id}` | Reads one lab case. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `LabTechnician` |
| GET | `/prosthetics/lab-cases` | Lists lab cases. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `LabTechnician` |
| POST | `/prosthetics/lab-cases/{lab_case_id}/dispatch` | Sends the case to the laboratory, starting the turnaround and shelf-life clocks. Inside the global write gate; enforces both overlap checks. | `FrontOffice`, `Prosthodontist` |
| POST | `/prosthetics/lab-cases/{lab_case_id}/receive` | The laboratory returns the finished case to the clinic. Outside the global write gate; carries the shelf-life mutate-then-reject behaviour. | `LabTechnician` |
| POST | `/prosthetics/lab-cases/{lab_case_id}/qc` | Records the clinic's QC inspection on a returned case. Outside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/lab-cases/{lab_case_id}/resend` | Sends a QC-failed case back to the laboratory. Inside the global write gate; bounded by the resend ceiling. | `FrontOffice`, `Prosthodontist` |
| POST | `/prosthetics/prostheses` | Delivers the finished appliance for one arch; head of the delivery cascade. Inside the global write gate. | `Prosthodontist` |
| GET | `/prosthetics/prostheses/{prosthesis_id}` | Reads one appliance, including both parallel axes, both clocks, and the adjustment allowance counters. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/prostheses` | Lists appliances. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/prostheses/{prosthesis_id}/recall-complete` | Closes a recall visit with one of three outcomes. Outside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/services` | Requests a post-delivery service, superseding an older un-completed service of the same type. Version-guarded on the appliance. Inside the global write gate except for an emergency repair. | `Prosthodontist`, `FrontOffice` |
| GET | `/prosthetics/services/{service_id}` | Reads one post-delivery service. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/services` | Lists post-delivery services. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/services/{service_id}/complete` | Completes a service and fixes its charge basis and amount. Outside the global write gate. | `Prosthodontist` |
| POST | `/prosthetics/services/{service_id}/void` | Voids a service; on a completed row this is the compensating action of the adjustment allowance. Outside the global write gate. | `FrontOffice`, `Prosthodontist` |
| POST | `/prosthetics/warranty-claims` | Opens a warranty claim against a delivered appliance. Outside the global write gate. | `Prosthodontist`, `FrontOffice` |
| GET | `/prosthetics/warranty-claims/{warranty_claim_id}` | Reads one warranty claim. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/warranty-claims` | Lists warranty claims. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/warranty-claims/{warranty_claim_id}/adjudicate` | Records the four-way fault verdict. Outside the global write gate. | `ClinicalDirector` |
| POST | `/prosthetics/warranty-claims/{warranty_claim_id}/clinical-review` | Resolves an indeterminate claim into one of the three real verdicts. Outside the global write gate. | `ClinicalDirector` |
| POST | `/prosthetics/remake-requests` | Requests a remake of one arch. Inside the global write gate; carries the remake-ceiling mutate-then-reject behaviour. | `Prosthodontist` |
| GET | `/prosthetics/remake-requests/{remake_request_id}` | Reads one remake request. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| GET | `/prosthetics/remake-requests` | Lists remake requests; the only channel through which a finally-denied row is discoverable. | `Prosthodontist`, `FrontOffice`, `ClinicalDirector`, `PlatformAdmin` |
| POST | `/prosthetics/remake-requests/{remake_request_id}/approve` | Authorises a remake under segregation of duties; head of the six-link remake cascade. Outside the global write gate. | `ClinicalDirector` |
| POST | `/prosthetics/remake-requests/{remake_request_id}/deny` | Denies a remake under segregation of duties. Outside the global write gate. | `ClinicalDirector` |
| POST | `/prosthetics/predeterminations` | Submits a preauthorization request for a case to one coverage. Outside the global write gate. | `FrontOffice` |
| GET | `/prosthetics/predeterminations/{predetermination_id}` | Reads one predetermination, re-evaluating its expiry against the logical clock. | `FrontOffice`, `Prosthodontist`, `PlatformAdmin` |
| GET | `/prosthetics/predeterminations` | Lists predeterminations. | `FrontOffice`, `Prosthodontist`, `PlatformAdmin` |
| POST | `/prosthetics/predeterminations/{predetermination_id}/determine` | Records the carrier's three-way answer and computes the benefit estimate. Outside the global write gate. | `FrontOffice` |
| POST | `/prosthetics/claims` | Opens a claim for a case against its primary coverage. Outside the global write gate. | `FrontOffice` |
| GET | `/prosthetics/claims/{claim_id}` | Reads one claim. | `FrontOffice`, `Prosthodontist`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/claims` | Lists claims. | `FrontOffice`, `Prosthodontist`, `PlatformAdmin` |
| POST | `/prosthetics/claims/{claim_id}/submit` | Submits the claim to the coverage its current stage targets, running the waiting-period, replacement-frequency, predetermination, and annual-maximum checks. Outside the global write gate. | `FrontOffice` |
| POST | `/prosthetics/claims/{claim_id}/post-payment` | Records the carrier's adjudication for the current stage. Outside the global write gate. | `FrontOffice` |
| POST | `/prosthetics/claims/{claim_id}/reverse` | Reverses a closed claim; the compensating action of the coverage-benefit conservation. Outside the global write gate. | `FrontOffice` |
| POST | `/prosthetics/payment-plans` | Creates an installment plan for a case's patient responsibility, superseding the case's current plan. Version-guarded on the case. Outside the global write gate. | `FrontOffice` |
| GET | `/prosthetics/payment-plans/{payment_plan_id}` | Reads one payment plan; a `Patient` caller may only read its own. | `FrontOffice`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/payment-plans` | Lists payment plans. | `FrontOffice`, `PlatformAdmin`, `Prosthodontist` |
| POST | `/prosthetics/payment-plans/{payment_plan_id}/assess-delinquency` | Sweeps the plan's scheduled installments past their grace boundary and re-derives the plan status. Outside the global write gate, since it is what raises and lowers it. | `PlatformAdmin`, `FrontOffice` |
| GET | `/prosthetics/installments/{installment_id}` | Reads one installment; a `Patient` caller may only read its own. | `FrontOffice`, `PlatformAdmin`, `Patient` |
| GET | `/prosthetics/installments` | Lists installments; the only channel through which cascade-minted installment rows are discoverable. | `FrontOffice`, `PlatformAdmin`, `Patient` |
| POST | `/prosthetics/installments/{installment_id}/pay` | Pays one installment; a `Patient` caller may only pay its own. Outside the global write gate, since paying is the cure. | `Patient`, `FrontOffice` |
| POST | `/prosthetics/installments/{installment_id}/reverse-payment` | Reverses a posted installment payment; the compensating action of the payment-plan conservation. Outside the global write gate. | `FrontOffice` |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_PATIENT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_ARCH_NOT_FOUND` | 404 |
| `ERR_LAB_CASE_NOT_FOUND` | 404 |
| `ERR_PROSTHESIS_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_DELINQUENT` | 403 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_TERMINAL_STATE` | 409 |
| `ERR_REMAKE_FINAL_DENIED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CROSS_ENTITY_STATE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_LAB_CASE_EXPIRED` | 409 |
| `ERR_MILESTONE_SEQUENCE` | 422 |
| `ERR_RETAKE_LIMIT_EXCEEDED` | 409 |
| `ERR_TRYIN_LIMIT_EXCEEDED` | 409 |
| `ERR_QC_RESEND_LIMIT_EXCEEDED` | 409 |
| `ERR_ARCH_OCCUPIED` | 409 |
| `ERR_LAB_SLOT_CONFLICT` | 409 |
| `ERR_REMAKE_LIMIT_EXCEEDED` | 409 |
| `ERR_WARRANTY_CONSUMED` | 409 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_SERVICE_NOT_ELIGIBLE` | 422 |
| `ERR_SERVICE_FREQUENCY_LIMIT` | 422 |
| `ERR_COB_RANK_CONFLICT` | 409 |
| `ERR_WAITING_PERIOD` | 422 |
| `ERR_FREQUENCY_LIMIT` | 422 |
| `ERR_PREDETERMINATION_REQUIRED` | 422 |
| `ERR_ANNUAL_MAX_EXHAUSTED` | 422 |


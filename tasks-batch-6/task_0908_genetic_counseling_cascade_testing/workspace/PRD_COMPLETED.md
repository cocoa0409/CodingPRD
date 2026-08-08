# Genetic Counseling & Cascade Testing API — Product Requirements Document

## 1. Introduction

Hereditary-risk clinics coordinate a long, branching journey: a patient is referred, a family pedigree is assembled, pre-test counseling and consent are documented, a genetic panel is ordered from a laboratory, a result is released and disclosed, and — when a pathogenic variant is confirmed — the finding cascades outward to at-risk relatives who each become new patients. Alongside this clinical thread runs an entirely separate insurance and billing thread, because authorization, submission, and adjudication of a claim proceed on their own timetable and must never be conflated with where the patient sits clinically. This API models that whole enterprise as a set of peer resources joined by references, with a self-referential family pedigree at its heart and a cascade that propagates real financial and clinical side effects through the kindred.

The product's defining challenge is bookkeeping under motion. A single family carries an outreach budget that is reserved when an invitation is sent, converted to spend when it is accepted, and released when it is declined or expires — an invariant that must hold after every transition. A counseling case tracks two independent lifecycles at once. A disclosure of an actionable result silently manufactures a surveillance plan and, for the highest-risk patients, a specialist referral. Accepting a cascade invitation manufactures an entirely new counseling case for the relative. Every one of these derived effects, every threshold, and every rounding rule described below is a hard requirement: the system is correct only when the ledgers, the risk tiers, and the cascade counters all reconcile.

This document specifies the complete contract — the global conventions every endpoint obeys, the business workflows and their scattered rules, the endpoint catalogue, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and conventions that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles: `GeneticCounselor`, `LabTechnician`, `BillingSpecialist`, and `ProgramAdmin`. Their authority is partitioned by resource type. A `GeneticCounselor` is the clinical owner and drives cases, pedigrees, consent, sessions, orders, disclosure, cascade outreach, surveillance plans, and referrals. A `LabTechnician` enters and releases laboratory results. A `BillingSpecialist` owns the insurance-claim lifecycle. A `ProgramAdmin` performs setup — registering families, counselors, and labs — and controls the logical clock. Every role may call every read (GET) endpoint.

Two roles are entity-backed, which ties `X-User-ID` to a persisted resource and to ownership checks. When `X-User-Role` is `GeneticCounselor`, `X-User-ID` is the `id` of the acting `Counselor`; ownership checks on any resource that references a `Counselor` compare that resource's counselor foreign key to `X-User-ID`. Concretely, a counselor may book only their own sessions — the `counselor_id` on a new session must equal `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `LabTechnician`, `X-User-ID` is the `id` of the acting `Lab`; releasing a result compares the parent test order's `lab_id` to `X-User-ID`, and a mismatch is likewise rejected with `ERR_NOT_RESOURCE_OWNER`. The other two roles are opaque: when `X-User-Role` is `BillingSpecialist` or `ProgramAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. A `limit` below 1 or above 100 is clamped into that range and a negative `offset` is clamped to 0, rather than rejected; a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order, ties broken by creation order (insertion sequence). Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties and Versioning

Every resource in this system carries a system-managed `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, recorded when the resource is first created. Every resource type in this specification is also mutable and additionally carries an `updated_at` timestamp (same ISO 8601 UTC format), refreshed on every change, and a `version`, an integer that begins at 1 on creation and increments by one on each mutation. Because the counseling case is the pivot of the whole workflow, its `version` is load-bearing: several state transitions increment it, and the disclosure cascade may increment it more than once in a single call as it walks through its hops. Whenever a derived field is recomputed as a side effect of an operation — a ledger total, a cascade counter, a risk tier — that recomputation is a mutation of the owning resource and updates its `updated_at` and `version` accordingly. Every lifecycle-bearing resource other than the counseling case exposes its current position through a single `status` field; the counseling case is the sole exception, splitting its state into the two independent `clinical_status` and `billing_status` fields described below.

### 2.5. Validation Ordering and Nested-Resource Resolution

When an endpoint path names a resource by identifier, existence is validated before any business rule runs. For paths that thread through more than one identifier, resolution proceeds left to right, and the first identifier that does not resolve produces its own not-found error (for example `ERR_CASE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_RESULT_NOT_FOUND`) before any deeper resource is consulted.

The system evaluates each request through a fixed priority ladder, and the earliest failing rung determines the error returned. Authentication is checked first: absent or malformed headers yield `ERR_UNAUTHENTICATED`. Role authorization is second, yielding `ERR_FORBIDDEN`. Existence of every path- and body-referenced resource is third, yielding the appropriate not-found error. Fourth is entity-backed ownership — for releasing a result and for booking a session — yielding `ERR_NOT_RESOURCE_OWNER`. Fifth is the optimistic-concurrency check on surveillance-plan creation, yielding `ERR_STALE_VERSION`. Sixth is body validation — required fields present and well-typed, enum members valid, and numeric ranges respected (`coverage_pct` and `estimated_allowed_rate` each within 0 to 1 inclusive; a session's `scheduled_end` strictly after its `scheduled_start`; an order's `processing_end` strictly after its `processing_start`; `degree` within its allowed set) — yielding `ERR_VALIDATION`. Seventh is the state-machine check, confirming the target resource is in a state that permits the transition, yielding the relevant invalid-state error. The remaining domain rules — consent presence, cascade actionability, temporal overlap, uniqueness and structural constraints, and fiscal sufficiency — follow, and are described alongside the workflows they guard. This ordering matters: a request that fails several rungs surfaces the earliest one, so a mid-workflow state problem never masks a missing header or an unknown identifier.

### 2.6. Parallel Clinical and Billing Axes

A counseling case advances along two wholly independent state axes that never share a transition. The clinical axis, `clinical_status`, begins at `INTAKE` and moves through `RISK_ASSESSED`, `TESTING`, `DISCLOSED`, and `SURVEILLANCE`, with `WITHDRAWN` as its terminal state. The billing axis, `billing_status`, begins at `UNBILLED` and moves through `PENDING_AUTH`, `AUTHORIZED`, and `BILLED` to the terminal outcomes `PAID` or `DENIED`, and can be sent back to `UNBILLED` by a compensating void. The two axes evolve on their own; a case can be fully disclosed clinically while its claim is still unbilled, or paid while clinically still in testing. Whenever either axis transitions, the case's `version` increments and its `updated_at` refreshes, so both axes contribute to the same monotonic version counter even though their state strings are disjoint.

### 2.7. The Family Outreach Ledger

Each `Family` authorizes a cascade-outreach budget, `outreach_budget_cents`, a non-negative integer number of cents fixed at creation. Against that budget the system maintains three derived cent totals that together must always reconcile. `outreach_reserved_cents` is the sum of `estimated_cost_cents` over the family's invitations currently in `SENT` status. `outreach_spent_cents` is the sum of `estimated_cost_cents` over invitations in `ACCEPTED` status. `outreach_available_cents` is the budget minus reserved minus spent. The invariant `outreach_budget_cents` equals `outreach_available_cents` plus `outreach_reserved_cents` plus `outreach_spent_cents` holds at every instant, which is why sending, declining, accepting, and expiring an invitation each recompute the ledger from the current set of invitations rather than nudging a running balance. All four quantities are integer cents.

The family also tracks cascade uptake. `cascade_invitations_sent_count` is the number of the family's invitations whose status is anything other than `DRAFT` — that is, every invitation that has ever been sent. `cascade_cases_count` is the number of counseling cases in the family whose `originating_invitation_id` is set (the cases manufactured by accepting an invitation). `cascade_uptake_pct` is `cascade_cases_count` divided by `cascade_invitations_sent_count`, rounded half up to four decimal places; when the denominator is zero the uptake is exactly 0.0.

### 2.8. The Session Credit Ledger

A counseling case is provisioned with `covered_sessions`, the non-negative integer count of insurance-authorized counseling sessions. Against it, `sessions_used` counts the case's sessions in `SCHEDULED`, `COMPLETED`, or `NO_SHOW` status, and `sessions_remaining` is `covered_sessions` minus `sessions_used`. A cancelled session is excluded from the count — its credit is refunded — so the invariant `covered_sessions` equals `sessions_remaining` plus `sessions_used` holds at all times. Both totals are integer counts.

### 2.9. Laboratory Capacity and Counselor Scheduling

Two temporal-overlap protocols protect finite human and laboratory capacity. A `Lab` declares `max_concurrent_capacity`, the maximum number of test orders whose processing windows may overlap at any single instant (always at least 1), and exposes `current_processing_load`, the count of that lab's orders currently in `SUBMITTED` status. When an order is submitted, the system counts how many of the lab's already-submitted orders have processing windows that overlap the new order's window; if admitting the new order would push the count of simultaneously-overlapping windows beyond `max_concurrent_capacity`, submission is rejected with `ERR_LAB_CAPACITY_EXCEEDED`.

For counselors, the constraint is against double-booking: a counselor may not hold two active sessions whose scheduled intervals overlap. When a session is booked, its `scheduled_start`–`scheduled_end` interval is checked against that counselor's other non-cancelled sessions, and an overlap is rejected with `ERR_COUNSELOR_DOUBLE_BOOKED`. Two intervals that merely touch at an endpoint — one beginning exactly when another ends — are treated as adjacent, not overlapping.

### 2.10. Optimistic Concurrency Control

Surveillance-plan creation is guarded by optimistic concurrency against the parent counseling case. A request to create a surveillance plan must carry `expected_counseling_case_version`, a non-optional field holding the `version` of the `CounselingCase` the client last observed. If that value does not equal the case's current `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP 412. This protects the supersede semantics of surveillance plans: creating a new `ACTIVE` plan legitimately supersedes the prior `ACTIVE` plan for the case and bumps the case version, so if another writer has already done so, the current writer is acting on a stale view and must re-read before retrying. No other endpoint takes a version field, and no other endpoint performs this check.

### 2.11. Numeric Precision and Rounding

Monetary quantities in this system are integer cents and are neither rounded nor represented with decimal places; arithmetic on them is exact integer arithmetic except where a rate is applied. When a rate multiplies a cent amount — the estimated allowed amount at authorization, and each line's patient share at adjudication — the product is rounded half up to a whole number of cents. Risk probabilities are fractions in the range 0 to 0.99 and are rounded half up to four decimal places wherever a formula produces them. Risk-tier boundary comparisons are performed on the exact fraction, with the high boundary inclusive. Screening intervals and session counts are whole integers.

### 2.12. The Logical Clock

The server keeps a logical clock rather than reading wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and before any set call it stays at that default and never falls back to real time. A `ProgramAdmin` may advance or set the clock by supplying an ISO 8601 instant as `to_iso8601`. Logical-clock values populate consent signing timestamps and gate invitation expiry.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Families, Counselors, and Laboratories

Before any clinical work begins, a `ProgramAdmin` provisions the reference resources. A family is created with a `family_name` and its `outreach_budget_cents`; on creation the outreach ledger initializes with `outreach_reserved_cents` and `outreach_spent_cents` at zero and `outreach_available_cents` equal to the full budget, and both cascade counters at zero. A counselor is registered with a `full_name` and an `npi` (National Provider Identifier). A laboratory is registered with a `lab_name`, its `max_concurrent_capacity`, and a nominal `turnaround_days`; its `current_processing_load` starts at zero. These setup resources are read-visible to every role but writable only by the admin.

### 3.2. Opening a Counseling Case and Building the Pedigree

A `GeneticCounselor` opens a counseling case by naming the `family_id` it belongs to and the `assigned_counselor_id` of record, together with the patient's `patient_name`, `patient_dob` (in year-month-day form), `sex` (`MALE`, `FEMALE`, or `OTHER`), and self-reported `ancestry` (`ASHKENAZI_JEWISH`, `EUROPEAN`, `AFRICAN`, `ASIAN`, `HISPANIC`, or `OTHER`, which feeds prior-risk scoring). The counselor supplies a free-text `referral_reason` and the case's `covered_sessions` allotment. Two fields are optional: `relationship_to_proband` defaults to `PROBAND` and otherwise takes `FIRST_DEGREE`, `SECOND_DEGREE`, or `THIRD_DEGREE`; and `familial_variant_known` defaults to false, marking whether a specific pathogenic variant already identified in the family is the test target (which later enables true-negative interpretation). A newly opened case starts with `clinical_status` at `INTAKE`, `billing_status` at `UNBILLED`, `sessions_used` at zero, and `sessions_remaining` equal to `covered_sessions`. Its `prior_risk_pct`, `residual_risk_pct`, `risk_tier`, and `carrier_result` are all initially unset, and `originating_invitation_id` is null for a proband case — it is populated only when the case is manufactured by a cascade acceptance. Cases can be listed with optional filters on `family_id`, `assigned_counselor_id`, and `originating_invitation_id`.

The pedigree is the self-referential family tree hung off a proband case. A counselor adds a member by naming the `counseling_case_id` it belongs to, the member's `relationship` (`SELF`, `PARENT`, `SIBLING`, `CHILD`, `GRANDPARENT`, `AUNT_UNCLE`, `COUSIN`, `NIECE_NEPHEW`, or `HALF_SIBLING`), the `degree` of relationship (`0`, `1`, `2`, or `3`), and whether the member is `affected`. Optional inputs are the `age_of_onset` in years (null when unknown or unaffected), a `deceased` flag defaulting to false, and a `related_member_id` linking this member to another member as a tree edge. A member whose `relationship` is `SELF` must carry `degree` `0`; a structural mismatch is a validation failure. The system derives `is_at_risk` as true exactly when the member is not the `SELF` node, the degree is 1 or 2, and the member is not deceased — these are the cascade candidates. Pedigree members can be listed with optional filters on `counseling_case_id` and `related_member_id`.

### 3.3. Consent and Pre-Test Counseling

Consent is documented per case. A counselor creates a consent record against a `counseling_case_id` with a `consent_type` of `TESTING`, `RESULT_DISCLOSURE`, `CASCADE_CONTACT`, or `DATA_SHARING`; it begins `PENDING` with a null `signed_at`. Signing a pending consent — permitted only while it is `PENDING`, otherwise `ERR_CONSENT_INVALID_STATE` — moves it to `SIGNED` and stamps `signed_at` with the current logical clock. A signed consent may be revoked back to `REVOKED`, but only while it is `SIGNED` and only if no result has yet been disclosed for the case: once any test result for the case reaches `DISCLOSED`, revocation is locked and rejected with `ERR_CONSENT_LOCKED_BY_DISCLOSURE`. Consent records can be listed filtered by `counseling_case_id`.

Counseling itself happens in sessions. Booking a session names the `counseling_case_id`, the `counselor_id` delivering it (which must equal the acting counselor's `X-User-ID`), a `session_type` of `PRE_TEST`, `DISCLOSURE`, or `FOLLOW_UP`, and the `scheduled_start` and `scheduled_end` instants (the end strictly after the start). Booking is fiscal: it consumes a session credit, so a case with no remaining credits — `sessions_remaining` not greater than zero — is refused with `ERR_NO_SESSION_CREDITS`, and the counselor must also be free of an overlapping session as described in the scheduling protocol. Booking additionally requires the case not to be `WITHDRAWN`; a session booked on a withdrawn case is rejected with `ERR_CASE_INVALID_CLINICAL_STATE` (checked after resolution and ownership, before the overlap and credit checks). A successful booking creates the session `SCHEDULED`, increments `sessions_used`, and recomputes `sessions_remaining`. Completing a scheduled session moves it to `COMPLETED` and leaves the credit consumed. Marking a scheduled session as a no-show moves it to `NO_SHOW`, and its credit likewise remains consumed. Cancelling a scheduled session is the compensating path: it moves the session to `CANCELLED`, decrements `sessions_used`, recomputes `sessions_remaining` (refunding the credit), and frees the counselor's slot. Each of the three lifecycle actions requires the session to be `SCHEDULED`; otherwise the transition is rejected with `ERR_SESSION_INVALID_STATE`. Sessions can be listed filtered by `counseling_case_id` and `counselor_id`.

### 3.4. Pedigree-Based Risk Assessment

Once at least one pedigree member exists, a counselor runs risk assessment on a case that is still at `INTAKE`; a case in any other clinical state is rejected with `ERR_CASE_INVALID_CLINICAL_STATE`, and a case with no pedigree members is rejected with `ERR_PEDIGREE_EMPTY`. Assessment computes the pre-test carrier probability from the pedigree and moves the case from `INTAKE` to `RISK_ASSESSED`.

The prior-risk calculation weighs the family's affected relatives. Only members who are `affected` and are not the `SELF` node contribute. Each contributing member earns a degree weight — 1.0 for a first-degree member, 0.5 for a second-degree member, and 0.25 for a third-degree member, while a self or degree-zero member and any unrecognized degree contribute a weight of zero — multiplied by an onset multiplier keyed on `age_of_onset`: 3 when onset is before age 40, 2 when onset is at least 40 but before 50, and 1 when onset is 50 or older; an unknown or null onset also uses a multiplier of 1. Summing weight times multiplier across all contributing members yields the affected-units total. The raw risk is a population baseline of 0.05 plus 0.05 for each affected unit. If the case's `ancestry` is `ASHKENAZI_JEWISH`, a bonus of 0.10 is added; otherwise no bonus applies. The result is capped at 0.99 — the smaller of 0.99 and the summed value — and rounded half up to four decimal places to produce `prior_risk_pct`. Risk assessment then sets the case's `risk_tier` from this prior value using the tiering rule described with disclosure below. The assessment increments the case `version`.

### 3.5. Test Ordering, Laboratory Coordination, and Results

A counselor drafts a test order for a case at a lab by naming the `counseling_case_id`, the performing `lab_id`, the `panel_name`, the `list_price_cents`, and the `processing_start` and `processing_end` instants of the lab window (the end strictly after the start); an optional `cpt_codes` array of CPT code strings defaults to empty. The order is created `DRAFT`.

Submitting the drafted order is the gate into testing and carries several preconditions evaluated together. The order must be `DRAFT` (else `ERR_ORDER_INVALID_STATE`); the case must be at `RISK_ASSESSED` (else `ERR_CASE_INVALID_CLINICAL_STATE`); a `TESTING`-type consent record for the case must be `SIGNED` (else `ERR_CONSENT_REQUIRED`); and the lab must have processing capacity for the window (else `ERR_LAB_CAPACITY_EXCEEDED`). On success the order moves from `DRAFT` to `SUBMITTED`, the lab's `current_processing_load` is recomputed to reflect the reserved slot, and the case advances from `RISK_ASSESSED` to `TESTING`, incrementing the case `version`. An order may instead be cancelled while it is `DRAFT` or `SUBMITTED`, moving it to `CANCELLED`, releasing any reserved lab slot, and recomputing `current_processing_load`; a cancel from any other state is rejected with `ERR_ORDER_INVALID_STATE`. Orders can be listed filtered by `counseling_case_id` and `lab_id`.

The laboratory enters the result. A `LabTechnician` records a result against a `test_order_id` whose order is `SUBMITTED` (else `ERR_ORDER_INVALID_STATE`), supplying the `gene` symbol, the `variant` nomenclature, and an ACMG-style `classification` of `PATHOGENIC`, `LIKELY_PATHOGENIC`, `VUS`, `LIKELY_BENIGN`, or `BENIGN`. Recording creates the result `PENDING`, advances the order from `SUBMITTED` to `RESULTED`, and recomputes the lab's `current_processing_load` as the slot is released. Releasing the pending result — permitted only while it is `PENDING` (else `ERR_RESULT_INVALID_STATE`) and only by the lab that owns the parent order (else `ERR_NOT_RESOURCE_OWNER`) — moves it from `PENDING` to `RELEASED` and computes `is_actionable`, which is true exactly when the `classification` is `PATHOGENIC` or `LIKELY_PATHOGENIC`. Results can be listed filtered by `test_order_id`.

### 3.6. Disclosure and the Disclosure Cascade

Disclosure is the richest single operation in the system. A counselor discloses a released result on a case that is in `TESTING`; the result must be `RELEASED` (else `ERR_RESULT_INVALID_STATE`) and the case must be `TESTING` (else `ERR_CASE_INVALID_CLINICAL_STATE`). Disclosure moves the result from `RELEASED` to `DISCLOSED` and then fires a chain of derived effects on the case.

First, the case's `carrier_result` is set by mapping the result's `classification`: `PATHOGENIC` or `LIKELY_PATHOGENIC` map to `POSITIVE_PATHOGENIC`, `BENIGN` or `LIKELY_BENIGN` map to `NEGATIVE`, and `VUS` maps to `VUS`. From that carrier result the system computes `residual_risk_pct`, the post-test carrier probability. A `POSITIVE_PATHOGENIC` result sets the residual risk to the confirmed-carrier value of 0.99. A `NEGATIVE` result branches on whether the family's variant was known: when `familial_variant_known` is true this is a true negative and the residual risk collapses to the population baseline of 0.05; when it is false the negative is uninformative and the residual risk is the case's `prior_risk_pct` multiplied by an uninformative factor of 0.5, rounded half up to four decimal places. A `VUS` result does not change management, so the residual risk equals the case's `prior_risk_pct` unchanged. The case's `risk_tier` is then recomputed from the residual value, and the case moves to `DISCLOSED`.

The risk tier is a threshold classification over whichever probability is in force — the `residual_risk_pct` when it has been set, otherwise the `prior_risk_pct`. The tier is `HIGH` when that probability is at least 0.20, `MODERATE` when it is at least 0.10 but below 0.20, and `LOW` when it is below 0.10. The 0.20 high boundary is inclusive.

The cascade continues automatically. If the disclosed result is actionable, the system auto-creates an `ACTIVE` surveillance plan for the case, copying the case's `risk_tier` onto the plan, giving it an empty `modalities` list, and deriving `screening_interval_months` from that tier — 6 months for `HIGH`, 12 for `MODERATE`, 24 for `LOW` — and the case advances from `DISCLOSED` to `SURVEILLANCE`. If that auto-created plan's `risk_tier` is `HIGH`, the system further auto-creates a `PENDING` referral linked to the plan, with `specialty` `HIGH_RISK_CLINIC`, `urgency` `ROUTINE`, and a system-generated `reason`. Across these hops the case `version` increments, and it may increment more than once in the single disclosure call. A disclosed, actionable result is also the precondition that unlocks family cascade outreach.

### 3.7. Cascade Family Outreach

When a proband's result is disclosed and actionable, the counselor reaches out to at-risk relatives. An invitation is drafted by naming the `family_id`, the `proband_case_id` whose actionable result drives the outreach, the `pedigree_member_id` of the at-risk relative, the `relative_name`, the `relationship` (`PARENT`, `SIBLING`, `CHILD`, `GRANDPARENT`, `AUNT_UNCLE`, `COUSIN`, `NIECE_NEPHEW`, or `HALF_SIBLING`), the `degree` (`1`, `2`, or `3`), the `contact_method` (`LETTER`, `EMAIL`, or `PHONE`), and the `expires_at` instant after which a sent invitation may lapse. On creation the invitation is `DRAFT` and its `estimated_cost_cents` is computed from the outreach price sheet: a base of 500 cents for `LETTER`, 100 cents for `EMAIL`, or 800 cents for `PHONE`, plus a degree surcharge of 0 cents for a first-degree relative, 200 cents for a second-degree relative, or 400 cents for a third-degree relative. Invitations can be listed filtered by `family_id`, `proband_case_id`, and `pedigree_member_id`.

Sending an invitation — the transition into `SENT`, allowed from either `DRAFT` or `DECLINED` (else `ERR_INVITATION_INVALID_STATE`) — carries two further preconditions: the proband case must have a `DISCLOSED` test result that is actionable (else `ERR_RESULT_NOT_ACTIONABLE`), and the family's `outreach_available_cents` must be at least this invitation's `estimated_cost_cents` (else `ERR_OUTREACH_BUDGET_EXCEEDED`). A send reserves the cost — adding `estimated_cost_cents` to `outreach_reserved_cents` and recomputing availability — and recomputes `cascade_invitations_sent_count`. Because `DECLINED` can be sent again, outreach is cyclic: a declined invitation re-enters `SENT` under the same preconditions and re-reserves its cost.

The other transitions out of `SENT` each reconcile the ledger. Declining a sent invitation moves it to `DECLINED` and releases the reservation, subtracting `estimated_cost_cents` from `outreach_reserved_cents` and recomputing availability. Expiring a sent invitation is permitted only once the logical clock has reached or passed `expires_at` (else `ERR_INVITATION_NOT_EXPIRABLE`); it moves the invitation to `EXPIRED` and likewise releases the reservation. Each of decline and expire requires the invitation to be `SENT` (else `ERR_INVITATION_INVALID_STATE`). Accepting a sent invitation is the productive terminus: it converts the reservation to spend — subtracting `estimated_cost_cents` from `outreach_reserved_cents` and adding it to `outreach_spent_cents` — and then manufactures a new counseling case for the relative. The relative's case is created in the same family, its `originating_invitation_id` set to the accepted invitation, its `assigned_counselor_id` copied from the proband case, its `relationship_to_proband` derived from the invitation's `degree` (degree 1 becomes `FIRST_DEGREE`, 2 becomes `SECOND_DEGREE`, 3 becomes `THIRD_DEGREE`), `familial_variant_known` set to true, its `patient_name` copied from the invitation's `relative_name`, and its `sex` and `ancestry` copied from the proband case; its `referral_reason` is a system-generated cascade note, and it opens at `clinical_status` `INTAKE` and `billing_status` `UNBILLED`. Acceptance accepts optional `patient_dob` (null when omitted) and `covered_sessions` (defaulting to 0 when omitted) inputs for the new case. Creating that case recomputes the family's `cascade_cases_count` and `cascade_uptake_pct`. Acceptance requires the invitation to be `SENT` (else `ERR_INVITATION_INVALID_STATE`).

### 3.8. Insurance Authorization and Billing

The billing thread is owned by a `BillingSpecialist` and driven by a single insurance claim per case. Opening a claim names the `counseling_case_id`, the `test_order_id` being billed, the `payer_name`, the `member_number`, the `coverage_pct` (the fraction of the allowed amount the payer covers, from 0 to 1), the `estimated_allowed_rate` (the fraction of the billed total the payer is expected to deem allowable, from 0 to 1), and the `line_items` array (which must contain at least one element), each element an object with a `cpt` string and a `billed_cents` integer. At most one non-void claim may exist for a case; a second is rejected with `ERR_CLAIM_ALREADY_EXISTS`. On creation the claim is `DRAFT`, its `billed_total_cents` is computed as the sum of the line items' `billed_cents`, and the case's `billing_status` moves from `UNBILLED` to `PENDING_AUTH`, incrementing the case `version`.

The claim then walks its lifecycle, and every transition requires the claim to be in the expected state, otherwise `ERR_CLAIM_INVALID_STATE`. Authorizing a `DRAFT` claim computes `estimated_allowed_cents` as `billed_total_cents` multiplied by `estimated_allowed_rate`, rounded half up to whole cents, moves the claim to `AUTHORIZED`, and sets the case `billing_status` to `AUTHORIZED`. Submitting an `AUTHORIZED` claim moves it to `SUBMITTED` and the case to `BILLED`. Adjudicating a `SUBMITTED` claim takes an `outcome` and, when paying, a per-line `line_allowed_cents` payload. An outcome of `PAID` sets `final_allowed_cents` to the sum of the adjudicated per-line allowed amounts and computes `patient_responsibility_cents`; the claim moves to `PAID` and the case to `PAID`. An outcome of `DENIED` sets both `final_allowed_cents` and `patient_responsibility_cents` to zero and moves the claim and case to `DENIED`. Voiding is the compensating exit: a claim in `DRAFT` or `AUTHORIZED` may be voided (from any other state, `ERR_CLAIM_INVALID_STATE`), which moves the claim to `VOID` and returns the case's `billing_status` to `UNBILLED`. Every billing transition increments the case `version`. Claims can be listed filtered by `counseling_case_id` and `test_order_id`.

Patient responsibility is computed with a load-bearing rounding order. For each line in the adjudication payload, the patient's share is that line's allowed amount multiplied by one minus `coverage_pct`, rounded half up to whole cents; the per-line rounded shares are then summed to give `patient_responsibility_cents`. Rounding each line before summing is required and differs from summing first when fractional cents accumulate across lines.

### 3.9. Surveillance Plans and Referrals

A surveillance plan can also be created manually when disclosure produced no automatic plan. A counselor creates a plan by naming the `counseling_case_id`, an optional `modalities` array of screening-modality strings (defaulting to empty), and the mandatory `expected_counseling_case_version` for the concurrency check. The plan copies the case's `risk_tier`, derives `screening_interval_months` from that tier (6 months for `HIGH`, 12 for `MODERATE`, 24 for `LOW`), and is created `ACTIVE`. Creating a new active plan supersedes the prior active plan for the same case, moving that earlier plan from `ACTIVE` to `SUPERSEDED`, and the case advances from `DISCLOSED` to `SURVEILLANCE`; the manual create requires the case to be `DISCLOSED` (else `ERR_CASE_INVALID_CLINICAL_STATE`) and increments the case `version`. An active plan may be closed with an `outcome` that moves it to `COMPLETED` or `CANCELLED`; a plan not in `ACTIVE` is rejected with `ERR_PLAN_INVALID_STATE`. Plans can be listed filtered by `counseling_case_id`.

Referrals route a patient to specialty care. A counselor creates a referral by naming the `counseling_case_id`, the `specialty` (`BREAST_SURGERY`, `GI_ONCOLOGY`, `GYN_ONCOLOGY`, `CARDIOLOGY`, `ENDOCRINOLOGY`, or `HIGH_RISK_CLINIC`), and the `reason`, with an optional `urgency` (`ROUTINE` or `URGENT`, defaulting to `ROUTINE`) and an optional `surveillance_plan_id` linking the referral to a plan. It is created `PENDING`. Closing a pending referral with an `outcome` moves it to `COMPLETED` or `CANCELLED`; a referral not in `PENDING` is rejected with `ERR_REFERRAL_INVALID_STATE`. Referrals can be listed filtered by `counseling_case_id` and `surveillance_plan_id`.

Finally, a case that has run its course clinically may be withdrawn from the workflow from any clinical state other than the terminal `WITHDRAWN` — including `INTAKE`, `RISK_ASSESSED`, `TESTING`, `DISCLOSED`, or `SURVEILLANCE` — moving `clinical_status` to `WITHDRAWN` and incrementing the case `version`; withdrawing an already-`WITHDRAWN` case is rejected with `ERR_CASE_INVALID_CLINICAL_STATE`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state transitions and the logical-clock setter — return `200 OK`. All read operations return `200 OK`. In the Authorized Role(s) column, "All roles" denotes the four roles `GeneticCounselor`, `LabTechnician`, `BillingSpecialist`, and `ProgramAdmin`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | ProgramAdmin |
| POST | `/families` | Create a family with an outreach budget | ProgramAdmin |
| GET | `/families/{id}` | Get a family (ledger and cascade uptake) | All roles |
| POST | `/counselors` | Register a genetic counselor | ProgramAdmin |
| GET | `/counselors/{id}` | Get a counselor | All roles |
| POST | `/labs` | Register a testing lab | ProgramAdmin |
| GET | `/labs/{id}` | Get a lab | All roles |
| POST | `/counseling-cases` | Open a counseling case | GeneticCounselor |
| GET | `/counseling-cases` | List counseling cases | All roles |
| GET | `/counseling-cases/{id}` | Get a counseling case | All roles |
| POST | `/counseling-cases/{id}/assess-risk` | Compute prior risk and risk tier | GeneticCounselor |
| POST | `/counseling-cases/{id}/withdraw` | Withdraw a case | GeneticCounselor |
| POST | `/pedigree-members` | Add a pedigree member | GeneticCounselor |
| GET | `/pedigree-members` | List pedigree members | All roles |
| GET | `/pedigree-members/{id}` | Get a pedigree member | All roles |
| POST | `/consent-records` | Create a consent record | GeneticCounselor |
| GET | `/consent-records` | List consent records | All roles |
| GET | `/consent-records/{id}` | Get a consent record | All roles |
| POST | `/consent-records/{id}/sign` | Sign a pending consent | GeneticCounselor |
| POST | `/consent-records/{id}/revoke` | Revoke a signed consent | GeneticCounselor |
| POST | `/counseling-sessions` | Book a counseling session | GeneticCounselor |
| GET | `/counseling-sessions` | List counseling sessions | All roles |
| GET | `/counseling-sessions/{id}` | Get a counseling session | All roles |
| POST | `/counseling-sessions/{id}/complete` | Mark a session completed | GeneticCounselor |
| POST | `/counseling-sessions/{id}/cancel` | Cancel a session (refunds credit) | GeneticCounselor |
| POST | `/counseling-sessions/{id}/no-show` | Mark a session no-show | GeneticCounselor |
| POST | `/test-orders` | Draft a genetic test order | GeneticCounselor |
| GET | `/test-orders` | List test orders | All roles |
| GET | `/test-orders/{id}` | Get a test order | All roles |
| POST | `/test-orders/{id}/submit` | Submit a drafted order to the lab | GeneticCounselor |
| POST | `/test-orders/{id}/cancel` | Cancel an order | GeneticCounselor |
| POST | `/test-results` | Enter a result for a submitted order | LabTechnician |
| GET | `/test-results` | List test results | All roles |
| GET | `/test-results/{id}` | Get a test result | All roles |
| POST | `/test-results/{id}/release` | Release a pending result | LabTechnician |
| POST | `/test-results/{id}/disclose` | Disclose a released result (cascade) | GeneticCounselor |
| POST | `/cascade-invitations` | Draft a cascade outreach invitation | GeneticCounselor |
| GET | `/cascade-invitations` | List cascade invitations | All roles |
| GET | `/cascade-invitations/{id}` | Get a cascade invitation | All roles |
| POST | `/cascade-invitations/{id}/send` | Send or re-send an invitation | GeneticCounselor |
| POST | `/cascade-invitations/{id}/decline` | Record a decline | GeneticCounselor |
| POST | `/cascade-invitations/{id}/accept` | Accept and auto-create the relative's case | GeneticCounselor |
| POST | `/cascade-invitations/{id}/expire` | Expire a sent invitation | GeneticCounselor |
| POST | `/insurance-claims` | Open an insurance claim | BillingSpecialist |
| GET | `/insurance-claims` | List insurance claims | All roles |
| GET | `/insurance-claims/{id}` | Get an insurance claim | All roles |
| POST | `/insurance-claims/{id}/authorize` | Authorize; compute estimated allowed | BillingSpecialist |
| POST | `/insurance-claims/{id}/submit` | Submit the authorized claim | BillingSpecialist |
| POST | `/insurance-claims/{id}/adjudicate` | Adjudicate a submitted claim | BillingSpecialist |
| POST | `/insurance-claims/{id}/void` | Void a draft/authorized claim | BillingSpecialist |
| POST | `/surveillance-plans` | Create a surveillance plan (OCC) | GeneticCounselor |
| GET | `/surveillance-plans` | List surveillance plans | All roles |
| GET | `/surveillance-plans/{id}` | Get a surveillance plan | All roles |
| POST | `/surveillance-plans/{id}/close` | Close an active plan | GeneticCounselor |
| POST | `/referrals` | Create a specialist referral | GeneticCounselor |
| GET | `/referrals` | List referrals | All roles |
| GET | `/referrals/{id}` | Get a referral | All roles |
| POST | `/referrals/{id}/close` | Close a pending referral | GeneticCounselor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_FAMILY_NOT_FOUND` | 404 |
| `ERR_COUNSELOR_NOT_FOUND` | 404 |
| `ERR_LAB_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_PEDIGREE_MEMBER_NOT_FOUND` | 404 |
| `ERR_CONSENT_NOT_FOUND` | 404 |
| `ERR_SESSION_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_RESULT_NOT_FOUND` | 404 |
| `ERR_INVITATION_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_REFERRAL_NOT_FOUND` | 404 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PEDIGREE_EMPTY` | 409 |
| `ERR_CASE_INVALID_CLINICAL_STATE` | 409 |
| `ERR_CONSENT_INVALID_STATE` | 409 |
| `ERR_CONSENT_LOCKED_BY_DISCLOSURE` | 409 |
| `ERR_CONSENT_REQUIRED` | 409 |
| `ERR_SESSION_INVALID_STATE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_RESULT_INVALID_STATE` | 409 |
| `ERR_RESULT_NOT_ACTIONABLE` | 409 |
| `ERR_INVITATION_INVALID_STATE` | 409 |
| `ERR_INVITATION_NOT_EXPIRABLE` | 409 |
| `ERR_CLAIM_INVALID_STATE` | 409 |
| `ERR_CLAIM_ALREADY_EXISTS` | 409 |
| `ERR_PLAN_INVALID_STATE` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_COUNSELOR_DOUBLE_BOOKED` | 409 |
| `ERR_LAB_CAPACITY_EXCEEDED` | 409 |
| `ERR_NO_SESSION_CREDITS` | 402 |
| `ERR_OUTREACH_BUDGET_EXCEEDED` | 402 |

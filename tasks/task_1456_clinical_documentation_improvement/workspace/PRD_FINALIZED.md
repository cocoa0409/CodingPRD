# Clinical Documentation Improvement API — Product Requirements Document

## 1. Introduction

Hospitals lose substantial revenue every year to documentation gaps that surface only at claims time: a coder assigns a diagnosis-related group that understates patient severity, a payer denies the claim for insufficient clinical evidence, and by then the attending physician has moved on to the next admission. A Clinical Documentation Improvement (CDI) program closes that gap by placing a specialist between the medical record and the final code — someone who reviews charts while the patient is still in house, asks clarifying questions of the attending provider, and ensures the documented severity of illness and risk of mortality actually support the coded diagnosis. This document specifies the API that powers such a program: prioritizing which charts to review first, generating compliant non-leading queries, tracking provider responses through escalating windows, reconciling disagreements between CDI specialists and HIM coders, and measuring the financial impact on the facility's case mix index.

The system is organized around the `CDIProgram`, a top-level container that holds a facility's configuration, its roster of providers and patients, and its reporting snapshots. Within a program, `HIMCoder` operators register patient cases, `CDISpecialist` operators open reviews and send queries, `Provider` users respond to queries addressed to them, and `CDIManager` operators administer the program lifecycle, resolve mismatches, and advance the logical clock that drives escalation deadlines. A `ComplianceAuditor` role observes the program and contributes denial-prevention targets. Time in this system is logical rather than wall-clock: each program maintains a `current_period_index` that advances only when an authorized operator explicitly moves it forward, and every deadline, escalation window, and snapshot is expressed in these periods.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The recognized roles are `CDIManager`, `CDISpecialist`, `HIMCoder`, `Provider`, `ComplianceAuditor`, and `SystemAdmin`. A request missing either header, or carrying a role outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED`.

Role identity is interpreted in two distinct ways. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting `Provider` entity; ownership checks on any resource that references a `Provider` — most importantly the recipient field on a query — compare the resource's foreign-key field to `X-User-ID`. This is what enforces segregation of duties on query responses: only the addressed provider may answer. When `X-User-Role` is any of `CDIManager`, `CDISpecialist`, `HIMCoder`, `ComplianceAuditor`, or `SystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `cdi_specialist_id` on a `CDIReview` or `coder_user_id` on a `ReconciliationEvent`) but does not compare it to any entity's `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. Every list response sorts by the resource's `created_at` timestamp in ascending order, and the `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Mutation Semantics

Every entity in the system carries a standard set of system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation; and `version`, an integer that increments by exactly 1 on every modification. All entities in this domain carry the full set of four common fields. A mutation caused by a cascade — for example, a case transitioning to `UNDER_REVIEW` because one of its reviews was activated — counts as a modification of the parent: its `updated_at` refreshes and its `version` increments by 1, exactly as if the client had written to it directly.

Request bodies are closed schemas. Every endpoint whose request body declares a set of fields — the resource-creation and update operations and the body-bearing actions enumerated in §3 and §4 — rejects any request field outside that declared set with `ERR_INVALID_REQUEST`. Computed and system-managed attributes are therefore never accepted as input: a provider's `education_score`, `education_flag`, and `pattern_tally_json`, for example, cannot be supplied at registration, and the same holds for every other resource's server-managed fields. Action endpoints that declare no request-body fields (such as suspend, resume, hold, cancel, and the like) do not inspect the body beyond requiring it, when present, to be a JSON object.

### 2.5. The Logical Clock and Period Semantics

Time inside a program is measured in integer periods, not wall-clock timestamps. Each `CDIProgram` carries a `current_period_index` that starts at 0 when the program is created and advances only when a `CDIManager` or `SystemAdmin` explicitly advances it by a positive number of periods via the program's clock-advance capability. The mapping from logical periods to wall-clock time is anchored by a test-driving facility: period 0 corresponds to `2026-08-01T00:00:00Z`, and each day constitutes one period. A `SystemAdmin` may reset that epoch to an absolute ISO 8601 instant through a dedicated administrative capability that accepts a `to_iso8601` timestamp and reports the resulting `current_utc` and `period_index`; the server startup default is `2026-08-01T00:00:00Z` (period 0). All due dates, escalation windows, admission and discharge markers, and snapshot boundaries are expressed in periods relative to this clock. Advancing a program's clock by `by_periods` periods adds that count to the program's `current_period_index`, re-evaluates every query in `SENT` or `ESCALATED` status for auto-escalation or closure as `NO_RESPONSE`, recomputes the `priority_score` of every case in `OPEN`, `UNDER_REVIEW`, or `RECONCILED` status (the length-of-stay factor may have crossed a boundary), and increments the program's `version` by 1.

### 2.6. Program-Wide Write Gating

A program that is not `ACTIVE` refuses nearly all writes. Any attempt to create or modify a resource belonging to a program in `SUSPENDED` or `CLOSED` status is rejected with `ERR_PROGRAM_NOT_ACTIVE`. The only write operations exempt from this gate are the program's own lifecycle transitions — suspend, resume, and close — the program's clock advance, and the administrative clock-reset capability. Reads are never gated by program status.

### 2.7. Precision and Rounding

All DRG weights, CMI values, priority scores, and opportunity deltas in the system are decimal numbers carried to exactly 4 decimal places, rounded half-up. Inputs declared as DRG weights (such as `initial_drg_weight`, `proposed_drg_weight`, and `coder_drg_weight`) must be at least 0.1000. When a computed value combines a ratio and a difference — as in the case mix index lift — the ratios are rounded to 4 decimal places first, and only then is the subtraction performed. Severity-of-illness and risk-of-mortality values are integers in the range 1 through 4 inclusive. Provider education scores are integers with a floor of 0.

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to prove they have observed the current state of the resource they are about to mutate, by carrying a non-optional expected-version field in the request body. Closing a review requires `expected_review_version`; if the value does not match the review's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This captures the case where a side effect — a query response that mutated the review's opportunity deltas, or an auto-escalation that advanced one of its child queries — has legitimately moved the review forward since the caller last read it. Finalizing a case's coding requires `expected_case_version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because a prior `AGREE` response or a reconciliation resolution may have updated the case's working DRG fields, and finalizing against a stale snapshot would silently overwrite newer CDI decisions. Sending a query requires `expected_query_version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because edits to the query's text or indicators after the caller's last read invalidate the lint assumptions under which the send was prepared. No other endpoint takes a version field.

### 2.9. Nested Resource Retrieval

Wherever an endpoint path contains multiple resource identifiers, the system validates them sequentially from left to right and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource. A request addressed to a query under a non-existent review, or a review under a non-existent case, fails at the leftmost unresolvable segment without evaluating the remaining path or any business rules.

### 2.10. Validation Order

When several validation rules could reject the same request, the server applies them in a fixed priority order so that the surfaced error is deterministic. Authentication (`ERR_UNAUTHENTICATED`) is checked first, then role authorization (`ERR_UNAUTHORIZED`), then path-identifier existence (`ERR_NOT_FOUND`), then the program-active gate (`ERR_PROGRAM_NOT_ACTIVE`), then the target resource's state precondition (`ERR_INVALID_STATE`). Only after those five generic gates pass do business rules run: query language lint (`ERR_LEADING_LANGUAGE`), provider program membership (`ERR_PROVIDER_NOT_IN_PROGRAM`), the one-active-review-per-case constraint (`ERR_REVIEW_ALREADY_ACTIVE`), unresolved-query blocking (`ERR_UNRESOLVED_QUERY_EXISTS`), the discharge precondition (`ERR_CASE_NOT_DISCHARGED`), DRG match (`ERR_DRG_MISMATCH`), denial-target satisfaction (`ERR_DENIAL_TARGET_UNMET`), query-recipient segregation (`ERR_NOT_QUERY_RECIPIENT`), the intensive-review response restriction (`ERR_PROVIDER_UNDER_INTENSIVE_REVIEW`), default-policy uniqueness (`ERR_DEFAULT_POLICY_CONFLICT`), open-cases blocking on program close (`ERR_OPEN_CASES_REMAIN`), and target window validity (`ERR_INVALID_REQUEST`). Where two checks share a category, the more specific condition wins; in particular, the segregation-of-duties check that the responding provider is the addressed recipient applies with the same force whether framed as a constraint or a referential check.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program

A `CDIManager` establishes a `CDIProgram` by supplying a `facility_name`, a unique `program_code`, and the program's `baseline_cmi` — the case mix index measured at program launch, which must be at least 0.1000. The `program_code` is immutable after creation. The new program begins in `ACTIVE` status with `current_period_index` set to 0.

Once a program exists, the manager configures how quickly unanswered queries escalate by creating an `EscalationPolicy` with a `name`, a `response_due_periods` value of at least 1 (the periods a provider has to respond before the first escalation), an `escalation_stage_periods` value of at least 1 (the periods between successive escalation stages), and a `max_escalation_stage` between 1 and 5 inclusive (the highest stage; at the next expiry beyond it the query auto-closes as `NO_RESPONSE`). A policy's `is_default` flag marks the program's default policy; exactly one default exists per program, so setting `is_default` to true on one policy clears it on all sibling policies of the same program, and an attempt to clear the default or introduce a second one is rejected with `ERR_DEFAULT_POLICY_CONFLICT`. Policy `name` values are unique within their program, and an update to an existing policy — which may touch `name`, `response_due_periods`, `escalation_stage_periods`, `max_escalation_stage`, or `is_default` — increments the policy's `version` by 1.

The manager also registers the medical staff. A `Provider` is registered with a `cdi_program_id`, an `npi` (National Provider Identifier, unique per program), a `full_name`, and a `specialty` label that later drives education-pattern grouping. New providers start with an `education_score` of 100, an `education_flag` of `NONE`, and an empty `pattern_tally_json` map.

Program lifecycle is managed through three transitions. Suspension moves a program from `ACTIVE` to `SUSPENDED` and is rejected with `ERR_INVALID_STATE` if the program is not `ACTIVE`. Resumption returns a `SUSPENDED` program to `ACTIVE`, rejected with `ERR_INVALID_STATE` from any other state. Closure moves a program from either `ACTIVE` or `SUSPENDED` to `CLOSED`; it is rejected with `ERR_INVALID_STATE` from any other state, and with `ERR_OPEN_CASES_REMAIN` whenever any patient case in the program is still in `OPEN`, `UNDER_REVIEW`, or `RECONCILED` status. Each transition increments the program's `version` by 1.

### 3.2. Case Intake and the Priority Score

An `HIMCoder` registers a `PatientCase` by supplying the owning `cdi_program_id`, a medical record number `mrn` unique within the program, the `admission_period` and `discharge_period` (with discharge no earlier than admission, both non-negative period indexes), the `attending_provider_id` of the attending of record, and the results of the coder's first-pass review: `initial_drg_code` and `initial_drg_weight` (at least 0.1000, 4-decimal). At registration the case's working documentation mirrors the coder's first pass: `working_drg_code` and `working_drg_weight` start equal to the initial values, `working_soi` and `working_rom` both start at 1, `reconciliation_status` starts at `NOT_REQUIRED`, and `status` starts at `OPEN`.

Every case in `OPEN`, `UNDER_REVIEW`, or `RECONCILED` status carries a computed `priority_score` that ranks review urgency; cases that reach `FINAL_CODED` or `CLOSED` are excluded from the computation. The score is the product of three tiers, multiplied by 100 and rounded half-up to 4 decimal places. Tier 1 is the base opportunity: normally the amount by which `working_drg_weight` exceeds `initial_drg_weight`, floored at zero. Tier 2 is an acuity multiplier that rises non-linearly with severity: it is 1.00 when both `working_soi` and `working_rom` are 1; 1.10 when `working_soi` is 2 and `working_rom` is at most 2; 1.25 when `working_soi` is 3 or `working_rom` is 3; and 1.50 when `working_soi` is 4 or `working_rom` is 4. Tier 3 is a length-of-stay pressure factor: 1.30 when the program's `current_period_index` is strictly greater than the case's `discharge_period`, 1.15 when it equals `discharge_period`, and 1.00 when it is still below it.

The base opportunity has two variants. When a case in `OPEN` or `UNDER_REVIEW` has at least one query in `DRAFT`, `SENT`, or `ESCALATED` status, the provisional variant applies: the base opportunity is the larger of `working_drg_weight` and the largest `proposed_drg_weight` across those open queries, minus `initial_drg_weight` — optimistic, treating open proposals as achievable. When a case has no open queries, or is `RECONCILED`, the residual variant applies: the base opportunity is simply `working_drg_weight` minus `initial_drg_weight` — only realized deltas count. Because a newly registered case has no queries at all, its initial `priority_score` uses the residual variant and therefore starts at zero. The score is recomputed on case creation, on any change to `initial_drg_weight`, `working_drg_weight`, `working_soi`, `working_rom`, or the admission and discharge periods, on every clock advance that may cross a discharge boundary, and whenever the case's open-query set or an open query's proposal may have changed — that is, when a query on the case is drafted, edited, cancelled, responded to, or auto-closed as `NO_RESPONSE` (the last as part of the clock-advance recomputation of §2.5). A recomputation that does not accompany a write to the case's own fields is a system-side refresh: it does not by itself increment the case's `version` or refresh its `updated_at`. Responses and resolutions that do rewrite the case's working fields — an `AGREE` response per §3.6, a `CODER_PREVAILS` resolution per §3.7 — remain ordinary modifications of the case under §2.4.

### 3.3. Opening and Managing a Review

A `CDISpecialist` opens a `CDIReview` against a case by supplying the `patient_case_id`. The review records the `X-User-ID` of the opening specialist as `cdi_specialist_id`, stamps `opened_period` with the program's current period, denormalizes the case's program into `cdi_program_id` for filtering, and starts in `DRAFT` status with `opportunity_weight_delta`, `opportunity_soi_delta`, and `opportunity_rom_delta` all at zero and `closed_reason` unset.

Activation moves a review from `DRAFT` to `ACTIVE`. The review must currently be `DRAFT` (else `ERR_INVALID_STATE`), its parent case must be in `OPEN` or `UNDER_REVIEW` (else `ERR_CASE_NOT_REVIEWABLE`), the program must be `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`), and no other review on the same case may already be `ACTIVE` (else `ERR_REVIEW_ALREADY_ACTIVE`). When activation succeeds on a case that was `OPEN`, the case cascades to `UNDER_REVIEW`, and the case's `version` increments by 1 as part of that cascade; the review's `version` also increments by 1.

An `ACTIVE` review may be placed `ON_HOLD`, but only while none of its queries is in `SENT` or `ESCALATED` status — a pending provider question cannot be shelved, and the attempt is rejected with `ERR_UNRESOLVED_QUERY_EXISTS`. Resuming returns an `ON_HOLD` review to `ACTIVE`, requiring the parent case to be in `OPEN` or `UNDER_REVIEW` (`ERR_CASE_NOT_REVIEWABLE`) and no other review on the same case to be `ACTIVE` (`ERR_REVIEW_ALREADY_ACTIVE`). Any review state precondition failure on these transitions surfaces as `ERR_INVALID_STATE`.

Closure moves a review from `ACTIVE` or `ON_HOLD` to `CLOSED`. The caller must supply a `closed_reason` of `OPPORTUNITY_CAPTURED`, `NO_OPPORTUNITY`, or `CASE_DISCHARGED`, and no query of the review may remain in `DRAFT`, `SENT`, or `ESCALATED` status (else `ERR_UNRESOLVED_QUERY_EXISTS`). Closure is an OCC-protected write per §2.8. When the last `ACTIVE` review on a case closes and no `OPEN` reconciliation event exists for that case, the case cascades back to `OPEN` with its `version` incremented. A review may also end with `closed_reason` `SUPERSEDED` where the workflow dictates; the value is part of the review's audit record alongside `NULL` for reviews that have not yet closed.

### 3.4. Drafting, Linting, and Sending Queries

Within an active review, a `CDISpecialist` drafts a `CDIQuery` addressed to a provider. The draft names the owning `cdi_review_id`, the recipient `provider_id`, the `escalation_policy_id` that will govern its due window, free-text `query_text`, a list of objective `clinical_indicators` cited in support, and the specialist's proposed documentation: `proposed_drg_code`, `proposed_drg_weight` (at least 0.1000), `proposed_soi`, and `proposed_rom` (each an integer from 1 to 4). The draft records the denormalized `patient_case_id` and `cdi_program_id` of its review's case, starts in `DRAFT` status with `escalation_stage` at 0, and may be freely edited while still a draft — text, indicators, proposed values, recipient, or policy — with each edit incrementing the query's `version` by 1. No recipient scrutiny runs at draft time: creating a draft, or editing a draft's recipient, accepts any `provider_id` value, whether or not it names a provider registered in the review's program — a draft may legitimately exist with a cross-program or unknown recipient, because the `ERR_PROVIDER_NOT_IN_PROGRAM` check below is enforced only on the send path.

Sending a query is the moment of compliance scrutiny, and it is an OCC-protected write per §2.8 requiring `expected_query_version`. The query must be in `DRAFT` (`ERR_INVALID_STATE`), its parent review must be `ACTIVE` (`ERR_REVIEW_NOT_ACTIVE`), the program must be `ACTIVE` (`ERR_PROGRAM_NOT_ACTIVE`), and the addressed provider must belong to the same program as the review's case (`ERR_PROVIDER_NOT_IN_PROGRAM`). The centerpiece is the non-leading lint, which runs over the query's `query_text`, `clinical_indicators`, and `proposed_drg_code` at send time. The lint records a finding for each occurrence — case-insensitive — of any leading phrase in the query text: "do you agree that", "isn't it true", "clearly indicates", "should be coded as", "please document", "the patient has", or "confirm the diagnosis of". It records an `ANSWER_IN_QUESTION` finding when the proposed DRG code appears as a literal token inside the query text, and a `NO_INDICATORS` finding when the clinical indicators list is empty. The outcome is stored for audit: `compliant_language` is true only when the findings list is empty, and `lint_findings` preserves every finding recorded. If any finding is present, the send fails with `ERR_LEADING_LANGUAGE` and the query remains in `DRAFT`.

A successful send transitions the query to `SENT`, stamps `sent_period` with the program's current period, computes `due_period` as the `sent_period` plus the governing policy's `response_due_periods`, and increments the query's `version` by 1. A query in `DRAFT`, `SENT`, or `ESCALATED` may instead be cancelled by a `CDISpecialist`, moving it to `CANCELLED` (`ERR_INVALID_STATE` from any other state); cancelling a query that was `SENT` or `ESCALATED` creates no education event and changes no scores, and every cancellation increments the query's `version` by 1.

### 3.5. Escalation and Non-Response

Unanswered queries escalate automatically as the program's clock advances. Whenever `current_period_index` advances past a query's current escalation threshold — computed as the query's `due_period` plus its current `escalation_stage` multiplied by the policy's `escalation_stage_periods` — and the query's `escalation_stage` is still below the policy's `max_escalation_stage`, the query moves from `SENT` to `ESCALATED` (or from `ESCALATED` to a further `ESCALATED` stage): `escalation_stage` increments by 1, `last_escalated_period` records the current period, and a `ProviderEducationEvent` with `pattern_tag` `NO_RESPONSE_PATTERN` and `points_deducted` 3 is recorded against the addressed provider. The query's `version` increments by 1 with each escalation.

When a query has already reached the policy's `max_escalation_stage` and the clock advances past the final threshold — `due_period` plus `max_escalation_stage` multiplied by `escalation_stage_periods` — the query closes as `NO_RESPONSE`. Terminal closure records a harsher education event: `pattern_tag` `NO_RESPONSE_PATTERN` with `points_deducted` 6 against the addressed provider. The owning review's opportunity deltas are unchanged by a non-response, and the query's `version` increments by 1. Both escalation and non-response closure apply to queries in either `SENT` or `ESCALATED` status and are re-evaluated on every clock advance.

### 3.6. Provider Response and Its Cascades

The addressee answers a query by recording a `QueryResponse` with a `response_type` of `AGREE`, `DISAGREE`, `CLARIFICATION_REQUESTED`, or `CLINICALLY_UNSUPPORTED`, plus a non-empty `response_text`. Only a query in `SENT` or `ESCALATED` status accepts a response (`ERR_INVALID_STATE` otherwise), and segregation of duties is strictly enforced: the responder's `X-User-ID` must equal the query's `provider_id`, and any other responder — including the CDI specialist who authored the query — is rejected with `ERR_NOT_QUERY_RECIPIENT`. A provider whose `education_flag` has fallen to `INTENSIVE_REVIEW` may submit only `CLARIFICATION_REQUESTED` responses; any other response type from such a provider is rejected with `ERR_PROVIDER_UNDER_INTENSIVE_REVIEW`.

A recorded response captures `responder_provider_id` from the acting user, links itself to its owning query via `cdi_query_id`, stamps `responded_period` with the current period, denormalizes `patient_case_id` from the query, and computes `was_overdue` as true exactly when `responded_period` is greater than the query's `due_period`. The query transitions to `RESPONDED`, its `response_id` is linked to the new response, and its `version` increments by 1.

The cascades depend on the response type. On `AGREE`, the case's working documentation is rewritten to the proposal: `working_drg_code` becomes `proposed_drg_code`, `working_drg_weight` becomes `proposed_drg_weight`, `working_soi` becomes `proposed_soi`, `working_rom` becomes `proposed_rom`, the case's `priority_score` is recomputed, and the owning review's opportunity deltas are recomputed. On `CLINICALLY_UNSUPPORTED`, the case is untouched, but a `ProviderEducationEvent` with `pattern_tag` `CLINICALLY_UNSUPPORTED_PATTERN` and `points_deducted` 4 is recorded against the responder. Independently of type, whenever the response is overdue, a further `ProviderEducationEvent` with `pattern_tag` `OVERDUE_PATTERN` and `points_deducted` 2 is recorded against the responder. Each education event in turn recomputes the provider's `education_score` and `education_flag` per §3.8.

A review's opportunity deltas accumulate its realized wins. `opportunity_weight_delta` is the sum, across the review's queries in `RESPONDED` status whose response type was `AGREE`, of each query's `proposed_drg_weight` minus the case's `initial_drg_weight`. `opportunity_soi_delta` and `opportunity_rom_delta` are the corresponding sums of `proposed_soi` minus 1 and `proposed_rom` minus 1, where 1 is the severity and mortality baseline every case starts with. These deltas are cumulative realizations: they are not recomputed downward when a later `AGREE` overwrites an earlier one, so two `AGREE` responses on the same case stack. A `CLINICALLY_UNSUPPORTED` response does not change review deltas, because the case was not updated.

### 3.7. Final Coding, Mismatch, and Reconciliation

When a case's documentation is complete, an `HIMCoder` attempts final coding by submitting `coder_drg_code` and `coder_drg_weight` alongside the OCC token `expected_case_version` (per §2.8). The preconditions run in the validation order of §2.10: the case must be in `OPEN`, `UNDER_REVIEW`, or `RECONCILED` status (`ERR_INVALID_STATE`); the program's `current_period_index` must be at least the case's `discharge_period` (`ERR_CASE_NOT_DISCHARGED`); no review of the case may be in `DRAFT`, `ACTIVE`, or `ON_HOLD` (`ERR_OPEN_REVIEW_EXISTS`); and no query of the case may be in `SENT` or `ESCALATED` (`ERR_UNRESOLVED_QUERY_EXISTS`).

The decisive check compares the coder's assertion to the case's working documentation. If `coder_drg_code` differs from `working_drg_code`, or `coder_drg_weight` differs from `working_drg_weight`, finalization is blocked: a `ReconciliationEvent` is created in `OPEN` status capturing the coder's `coder_drg_code` and `coder_drg_weight` as inputs and snapshotting the case's current working values as `cdi_drg_code` and `cdi_drg_weight`; the event records the coder's `X-User-ID` as `coder_user_id` and the program as `cdi_program_id`; the case's `reconciliation_status` becomes `PENDING`; a case that was `OPEN` moves to `UNDER_REVIEW`; and the request is rejected with `ERR_DRG_MISMATCH`.

Even when the DRG matches, denial-prevention targets may still block finalization. For every `DenialRiskTarget` whose `drg_code` equals the case's `working_drg_code` and whose active window — from `active_from_period` through `active_to_period`, both inclusive — contains the program's `current_period_index`, two requirements must hold. Every tag in the target's `required_evidence_tags` must appear in the union of `clinical_indicators` across the case's queries that are `RESPONDED` with a response type of `AGREE`, and the case's `working_soi` must be at least the target's `severity_floor`. Any shortfall is rejected with `ERR_DENIAL_TARGET_UNMET`.

When every check passes, the case transitions to `FINAL_CODED`, its `reconciliation_status` is unchanged (it is already `NOT_REQUIRED` or was resolved earlier), and its `version` increments by 1. A `FINAL_CODED` case may later be closed by a `CDIManager`, moving it to `CLOSED` (`ERR_INVALID_STATE` from any other state) and incrementing its `version` by 1.

Reconciliation is adjudicated by a `CDIManager`. Resolution accepts an `outcome` of `CDI_PREVAILS` or `CODER_PREVAILS` plus a non-empty `resolution_note`, and requires the event to be `OPEN` (`ERR_INVALID_STATE`). When the CDI position prevails, the event moves to `RESOLVED_CDI_PREVAILS`, the case's `reconciliation_status` becomes `RESOLVED_CDI_PREVAILS`, and the working DRG fields are left unchanged — the CDI values win. When the coder prevails, the event moves to `RESOLVED_CODER_PREVAILS`, the case's `reconciliation_status` becomes `RESOLVED_CODER_PREVAILS`, its `working_drg_code` and `working_drg_weight` are overwritten with the coder's values, and its `priority_score` is recomputed. A `CDIManager` may instead escalate an `OPEN` event, moving it to `ESCALATED` and setting the case's `reconciliation_status` to `ESCALATED`. In all three outcomes, if no other `OPEN` reconciliation event remains on the case, the case cascades to `RECONCILED` with its `version` incremented, and the event's own `version` increments by 1. A case whose reconciliation events have all reached `RESOLVED_CDI_PREVAILS`, `RESOLVED_CODER_PREVAILS`, or `ESCALATED` — and whose last `ACTIVE` review has closed — is eligible to return to `OPEN` only when no open reconciliation exists; conversely, the resolution of a case's only `OPEN` event moves it from `UNDER_REVIEW` to `RECONCILED`.

### 3.8. Provider Education and the Score Bands

Every education event — whether auto-generated by escalation, non-response, unsupported responses, or overdue replies, or recorded manually — adjusts the provider's standing. A `CDIManager` or `CDISpecialist` may record a manual `ProviderEducationEvent` by supplying the `provider_id`, a `pattern_tag` of `LEADING_LANGUAGE`, `NO_RESPONSE_PATTERN`, `CLINICALLY_UNSUPPORTED_PATTERN`, or `OVERDUE_PATTERN`, a `points_deducted` value between 1 and 25 inclusive, a `source_query_id` referencing any query within the program, and a free-text `note`. The event stamps `recorded_period` with the current period and denormalizes the provider's `cdi_program_id`.

Each event subtracts its `points_deducted` from the provider's `education_score` (which never falls below 0), increments `pattern_tally_json` for that `pattern_tag` by 1, and triggers recomputation of the provider's `education_flag`. The score is 100 minus the total points deducted across all of the provider's education events regardless of age, floored at zero. The flag bands are exact: a score of 85 or higher yields `NONE`; 70 through 84 yields `WATCH`; 50 through 69 yields `COACHING`; below 50 yields `INTENSIVE_REVIEW`. The boundary behavior matters: 85 is `NONE` while 84 is `WATCH`; 70 is `WATCH` while 69 is `COACHING`; 50 is `COACHING` while 49 is `INTENSIVE_REVIEW`. The flag is consulted on every query response, where `INTENSIVE_REVIEW` restricts the provider to clarification requests as described in §3.6.

### 3.9. Denial-Prevention Targets and Impact Reporting

A `CDIManager` or `ComplianceAuditor` defines `DenialRiskTarget` records that encode the documentation bar a DRG must clear before final coding. Each target names its `cdi_program_id`, the `drg_code` it applies to, the `required_evidence_tags` that must all appear in the case's agreed clinical indicators, the `severity_floor` (an integer from 1 to 4) that the case's `working_soi` must meet, and the inclusive window `active_from_period` through `active_to_period` during which the target applies. A target whose `active_to_period` is earlier than its `active_from_period` is rejected with `ERR_INVALID_REQUEST`.

Impact reporting is delivered through `CMISnapshot` records, taken on demand by a `CDIManager` or `ComplianceAuditor`. A snapshot stamps `as_of_period` with the program's current period and includes every case in the program whose status is `RECONCILED`, `FINAL_CODED`, or `CLOSED` and whose `discharge_period` is no later than the `as_of_period`. The snapshot reports `case_count` as the number of included cases; `unadjusted_cmi` as the mean of `initial_drg_weight` across included cases — the coder's first-pass DRG before any CDI query — rounded half-up to 4 decimal places; and `adjusted_cmi` as the mean of `working_drg_weight` across the same cases, likewise rounded to 4 decimal places. The `cdi_lift` is the difference between the two rounded means, itself expressed to 4 decimal places: each ratio is rounded first, and only then is the subtraction performed. If no cases qualify, all four numeric fields report 0.0000 and no division occurs.

The snapshot also audits denial prevention. For each included case, the system considers every `DenialRiskTarget` whose `drg_code` equals the case's `working_drg_code` and whose active window contains the case's finalization period — targets whose window closed before the case finalized, or opened after, do not count against that case. A case counts as a miss when any such target has a `required_evidence_tags` entry absent from the union of `clinical_indicators` across the case's `RESPONDED`-with-`AGREE` queries, or when the case's `working_soi` is below the target's `severity_floor`. The snapshot's `denial_target_misses` is the integer count of included cases that missed at least one applicable target at finalize time.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or transition its state return `200 OK`. All endpoints are mounted under the `/api` prefix.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/cdi-programs` | Create a CDI program | CDIManager |
| GET | `/api/cdi-programs` | List CDI programs (paginated; filterable by `status`) | CDIManager, CDISpecialist, HIMCoder, Provider, ComplianceAuditor, SystemAdmin |
| GET | `/api/cdi-programs/{programId}` | Get a CDI program | CDIManager, CDISpecialist, HIMCoder, Provider, ComplianceAuditor, SystemAdmin |
| POST | `/api/cdi-programs/{programId}/suspend` | Suspend a program | CDIManager |
| POST | `/api/cdi-programs/{programId}/resume` | Resume a suspended program | CDIManager |
| POST | `/api/cdi-programs/{programId}/close` | Close a program | CDIManager |
| POST | `/api/cdi-programs/{programId}/clock/advance` | Advance the program's logical clock by `by_periods` periods | CDIManager, SystemAdmin |
| GET | `/api/cdi-programs/{id}/cmi-snapshots` | List CMI snapshots for a program | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| POST | `/api/cdi-programs/{id}/cmi-snapshots` | Take a CMI snapshot at the current period | CDIManager, ComplianceAuditor |
| POST | `/api/escalation-policies` | Create an escalation policy | CDIManager |
| GET | `/api/escalation-policies` | List escalation policies (filterable by `cdi_program_id`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/escalation-policies/{policyId}` | Get an escalation policy | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| PUT | `/api/escalation-policies/{policyId}` | Update an escalation policy | CDIManager |
| POST | `/api/providers` | Register a provider | CDIManager |
| GET | `/api/providers` | List providers (filterable by `cdi_program_id`, `education_flag`, `specialty`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/providers/{providerId}` | Get a provider | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| GET | `/api/providers/{id}/education-events` | List education events for a provider (filterable by `pattern_tag`) | CDIManager, CDISpecialist, ComplianceAuditor |
| POST | `/api/patient-cases` | Register a patient case | HIMCoder |
| GET | `/api/patient-cases` | List cases (filterable by `cdi_program_id`, `status`, `attending_provider_id`, `priority_score_min`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/patient-cases/{caseId}` | Get a case | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| GET | `/api/patient-cases/{id}/reviews` | List reviews for a case (filterable by `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/patient-cases/{id}/reconciliations` | List reconciliation events for a case (filterable by `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| POST | `/api/patient-cases/{caseId}/finalize-coding` | Attempt final coding (OCC via `expected_case_version`) | HIMCoder |
| POST | `/api/patient-cases/{caseId}/close` | Close a FINAL_CODED case | CDIManager |
| POST | `/api/cdi-reviews` | Open a CDI review on a case | CDISpecialist |
| GET | `/api/cdi-reviews` | List reviews (filterable by `patient_case_id`, `cdi_program_id`, `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/cdi-reviews/{reviewId}` | Get a review | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/cdi-reviews/{id}/queries` | List queries for a review (filterable by `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| POST | `/api/cdi-reviews/{reviewId}/activate` | Activate a review | CDISpecialist |
| POST | `/api/cdi-reviews/{reviewId}/hold` | Put a review on hold | CDISpecialist |
| POST | `/api/cdi-reviews/{reviewId}/resume` | Resume a held review | CDISpecialist |
| POST | `/api/cdi-reviews/{reviewId}/close` | Close a review (OCC via `expected_review_version`) | CDISpecialist |
| POST | `/api/cdi-queries` | Create a query draft | CDISpecialist |
| GET | `/api/cdi-queries` | List queries (filterable by `cdi_review_id`, `patient_case_id`, `cdi_program_id`, `provider_id`, `escalation_policy_id`, `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| GET | `/api/cdi-queries/{queryId}` | Get a query | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| PUT | `/api/cdi-queries/{queryId}` | Edit a DRAFT query | CDISpecialist |
| POST | `/api/cdi-queries/{queryId}/send` | Send a query (OCC via `expected_query_version`; runs non-leading lint) | CDISpecialist |
| POST | `/api/cdi-queries/{queryId}/cancel` | Cancel a query in DRAFT, SENT, or ESCALATED | CDISpecialist |
| POST | `/api/cdi-queries/{id}/responses` | Provider responds to a query | Provider |
| GET | `/api/cdi-queries/{id}/responses` | Get the response on a query (zero or one) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor, Provider |
| GET | `/api/reconciliation-events` | List reconciliation events (filterable by `patient_case_id`, `cdi_program_id`, `status`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/reconciliation-events/{eventId}` | Get a reconciliation event | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| POST | `/api/reconciliation-events/{eventId}/resolve` | Resolve a reconciliation event | CDIManager |
| POST | `/api/reconciliation-events/{eventId}/escalate` | Escalate a reconciliation event | CDIManager |
| POST | `/api/denial-risk-targets` | Create a denial risk target | CDIManager, ComplianceAuditor |
| GET | `/api/denial-risk-targets` | List denial risk targets (filterable by `cdi_program_id`, `drg_code`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/denial-risk-targets/{targetId}` | Get a denial risk target | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| POST | `/api/provider-education-events` | Manually record a provider education event | CDIManager, CDISpecialist |
| GET | `/api/provider-education-events` | List provider education events (filterable by `provider_id`, `cdi_program_id`, `pattern_tag`) | CDIManager, CDISpecialist, ComplianceAuditor |
| GET | `/api/cmi-snapshots` | List CMI snapshots (filterable by `cdi_program_id`) | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| GET | `/api/cmi-snapshots/{snapshotId}` | Get a CMI snapshot | CDIManager, CDISpecialist, HIMCoder, ComplianceAuditor |
| POST | `/api/_clock/set_current_utc` | Test-driving: reset the logical clock epoch to `to_iso8601` | SystemAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_OPEN_CASES_REMAIN` | 409 |
| `ERR_CASE_NOT_REVIEWABLE` | 409 |
| `ERR_REVIEW_ALREADY_ACTIVE` | 409 |
| `ERR_REVIEW_NOT_ACTIVE` | 409 |
| `ERR_UNRESOLVED_QUERY_EXISTS` | 409 |
| `ERR_LEADING_LANGUAGE` | 422 |
| `ERR_PROVIDER_NOT_IN_PROGRAM` | 422 |
| `ERR_NOT_QUERY_RECIPIENT` | 403 |
| `ERR_PROVIDER_UNDER_INTENSIVE_REVIEW` | 403 |
| `ERR_CASE_NOT_DISCHARGED` | 422 |
| `ERR_DRG_MISMATCH` | 409 |
| `ERR_DENIAL_TARGET_UNMET` | 422 |
| `ERR_DEFAULT_POLICY_CONFLICT` | 409 |
| `ERR_OPEN_REVIEW_EXISTS` | 409 |

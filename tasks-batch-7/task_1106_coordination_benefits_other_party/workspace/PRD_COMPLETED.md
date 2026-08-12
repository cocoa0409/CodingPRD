# Coordination of Benefits & Other-Party Liability API — Product Requirements Document

## 1. Introduction

Health plans routinely pay claims for members who turn out to have had other coverage all along — a working spouse's group health plan, Medicare entitlement by age or disability, Medicaid, TRICARE, or an individual policy. When another payer should have paid first, every dollar the plan advanced is a dollar at risk. The Coordination of Benefits (COB) and Other-Party Liability API exists to systematize the discovery of that other coverage, the determination of which payer is primary for a given service date, the correction of claims already paid in the wrong position, and the recovery of overpayments from providers.

The platform serves several operator populations with deliberately segregated duties: eligibility staff maintain member demographics and enrollment, COB specialists verify coverage evidence and decide primacy, claims examiners adjudicate and rework claims, recovery specialists pursue provider reimbursements, and auditors close out periodic savings reports. Members themselves participate through a self-service survey channel. Because coverage can be discovered months after the fact — through a returned survey, a CMS data match, a remark on an incoming claim, or an eligibility vendor match — the system must support retroactive verification, retroactive primacy changes, and a disciplined claim-rework pipeline whose financial effects are tracked to the cent.

All capabilities are exposed as a REST API mounted under `/cob`. This document specifies the global contract (authentication, envelopes, pagination, concurrency control, the logical clock), the business workflows from discovery through recovery and reporting, the complete endpoint inventory, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules and boilerplate that apply uniformly to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity in which they act. A request missing either header, or presenting a role string outside the recognized catalog, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the headers are accepted, the role must also be permitted to invoke the specific endpoint; an attempt outside the role's grant is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly seven roles:

- `PlatformAdmin` — system administrator; owns rule configuration, provider registration, and the logical clock, and may read across all resources.
- `EligibilityAnalyst` — member enrollment and demographic maintenance; creates and disenrolls members, and may register coverages, submit leads, send surveys, and submit MSP questionnaires.
- `COBAnalyst` — the COB specialist; verifies and rejects coverages, dispositions leads, drafts and finalizes primacy determinations, adjudicates and voids MSP questionnaires, and may draft claim adjustments.
- `ClaimsExaminer` — the claims adjudicator; submits claims and claim lines, adjudicates, pays, readjudicates, repays, applies and voids adjustments, and may draft claim adjustments.
- `RecoverySpecialist` — recovery and refund specialist; reopens and closes claims, drafts, issues, escalates, and writes off recovery requests, and posts reimbursements.
- `COBAuditor` — savings reporting and audit; opens and closes savings periods and may read across all resources.
- `MemberSelf` — member self-service; responds to own surveys and reads own member record, coverages, surveys, and determinations.

Identity semantics differ by role. When `X-User-Role` is `PlatformAdmin`, `EligibilityAnalyst`, `COBAnalyst`, `ClaimsExaminer`, `RecoverySpecialist`, or `COBAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. When `X-User-Role` is `MemberSelf`, `X-User-ID` is the `id` of the acting Member. The server enforces this ownership on exactly two operations: fetching a member record, where the path's member id must equal `X-User-ID`, and responding to a survey, where the survey's owning member must equal `X-User-ID`; a mismatch — for example, a member attempting to answer another member's survey — is rejected with `ERR_FORBIDDEN` (HTTP 403). The remaining `MemberSelf`-accessible endpoints perform no ownership comparison.

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

Requests that match no route, or a route with an unsupported method, are rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope. An unexpected server failure surfaces as `ERR_INTERNAL` (HTTP 500) in this envelope; it is the only error identifier outside the 4xx catalogue of §5.

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter states how many items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` below 1 or above 100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by `id` in ascending order.

Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Common Resource Properties

Nearly every resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that increments on every modification to the resource, providing the basis for optimistic concurrency control.

The one exception is the Reimbursement resource, which is an immutable ledger posting: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from Reimbursements, and no operation mutates a posted Reimbursement.

Any mutation described in this document as incrementing a resource's `version` also refreshes that resource's `updated_at`.

### 2.5. Monetary Representation and Per-Line Rounding

All monetary amounts are represented as integer cents — billed, allowed, paid, recovered, and reported figures alike. Payment mathematics are performed per claim line and rounded half-up to integer cents on each line; claim-level totals are then formed by summing the already-rounded line values, and a sum is never re-rounded. This per-line-then-sum convention is normative wherever this document describes payment computation, on both initial adjudication and readjudication. Overpayment and underpayment figures on adjustments are differences of integer-cent totals and therefore require no rounding. Counts, such as rework estimates and adjusted-claim tallies, are whole numbers.

### 2.6. The Logical Clock

Time-dependent behavior throughout the system — survey expiry, recovery due dates, savings period closure, MSP coordination windows, age computation — is governed by a single server-side logical clock, never by wall-clock time. At server startup the logical clock reads 2026-05-01T00:00:00Z, and the server must not fall back to wall-clock time under any circumstance. A `PlatformAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Advancing the clock has exactly one eager side effect: every MemberSurvey still in `SENT` status whose `due_at` is earlier than the new clock transitions to `EXPIRED`. No other time-driven transitions fire eagerly — in particular, recovery escalations and write-offs remain explicit operator actions even when a request is long past due.

### 2.7. Optimistic Concurrency Control

Two write endpoints in the system carry a mandatory expected-version field that guards against acting on a stale view of a parent aggregate; no other endpoint accepts a version field.

First, creating a new rule configuration (`POST /cob/rule-configs`) requires the client to supply `expected_active_config_version`, carrying the client's last observed `version` of the currently `ACTIVE` configuration. If the supplied value does not match the current `ACTIVE` config's `version` — because another writer has since created a newer config that superseded the one the client read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The match is a literal integer comparison against the `version` field of the current `ACTIVE` configuration record; since each newly created configuration record starts at `version` 1 (see §3.1), a value last observed on an earlier, now-`SUPERSEDED` configuration can numerically coincide with the current `ACTIVE` record's `version`, and in that case the values are considered to match. When no `ACTIVE` configuration exists yet, `expected_active_config_version` is omitted from the request entirely; supplying an integer value when no `ACTIVE` configuration exists is rejected with `ERR_STALE_VERSION` (HTTP 412).

Second, drafting a primacy determination (`POST /cob/members/{id}/primacy-determinations`) requires the client to supply `expected_member_version`, carrying the client's last observed `version` of the member. If the member's `version` has advanced since that observation — for example because another writer has just verified a new coverage, which legitimately changes the eligible coverage set — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from drafting against a coverage landscape it has not observed.

### 2.8. Nested Resource Retrieval

Endpoints that address nested resources validate path identifiers sequentially, left to right. A request under a member path first confirms the member exists, then confirms the child (coverage, lead, survey, questionnaire, determination) exists and belongs to that member; a request under a claim path likewise walks claim, then adjustment, recovery request, or reimbursement. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing record, or where a nested child does not belong to the parent named in the path.

### 2.9. Validation Order and Cascading Consistency

When several validations could reject the same request, header presence and role recognition (family 1) and role authorization for the endpoint (family 2) are always evaluated first, in that order. Beyond those two, the server guarantees no global precedence across families: each endpoint applies its remaining checks in its own fixed order and surfaces the first failure it encounters. The validation families the endpoints draw on are:

1. Header presence and role recognition (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_UNAUTHORIZED`).
3. Existence and nesting of every path-templated identifier (`ERR_NOT_FOUND`).
4. Whether the entity is in a state from which the requested transition is valid (`ERR_INVALID_STATE`).
5. Temporal checks — coverage effective windows, future-dated service dates, survey responses past their due instant (`ERR_INVALID_COVERAGE_WINDOW`).
6. Uniqueness constraints (`ERR_DUPLICATE_OUR_PLAN`).
7. Determination referential integrity (`ERR_INVALID_DETERMINATION_REFERENCE`).
8. MSP compliance (`ERR_MSP_QUESTIONNAIRE_REQUIRED`).
9. Recovery-amount fiscal integrity (`ERR_NO_OVERPAYMENT`).
10. Reimbursement caps (`ERR_OVERRECOVERY`).
11. Past-due gating for escalation and write-off (`ERR_NOT_PAST_DUE`).
12. Existence of exactly one final primacy determination at adjudication (`ERR_NO_FINAL_PRIMACY`).
13. Member-enrollment gating on member-scoped writes (`ERR_MEMBER_DISENROLLED`).

A request whose required input is missing or of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400); where such input validation competes with a family check, which one surfaces first is endpoint-specific.

The system also maintains consistency across aggregate boundaries whenever a child record mutates. Verifying a coverage, drafting or finalizing a determination, adjudicating a questionnaire, recording a survey response, or adjudicating a claim each increment the owning Member's `version` in addition to the mutated resource's own `version`, so a member's version is a faithful cursor over everything that has happened to their COB landscape. The server performs these cascading mutations automatically as part of the triggering operation; clients never patch them directly.

## 3. Business Logic & Workflows

### 3.1. Rule Configuration and Plan-Level Governance

A single `PlatformAdmin`-maintained **rule configuration** anchors every COB decision the system makes. A configuration is created with a unique `config_name`, the `dependent_primacy_rule` governing dependent-child primacy (one of `BIRTHDAY_RULE`, `GENDER_RULE`, or `CUSTODIAL_DECREE`), the `msp_employer_size_threshold` (the employer employee count at or above which a group plan pays before Medicare for age- and disability-based entitlement), the `esrd_coordination_months` (the number of months from ESRD onset during which a group plan remains primary over Medicare — thirty months is the conventional setting), the `retroactive_lookback_months` (how far before discovery a newly verified other-coverage window may reach back and trigger claim rework), the `recovery_window_days` (the number of days after a recovery request is issued within which reimbursement must post before escalation is permitted), and the `savings_period_length_days` (the standard length, in days, of each COB savings reporting period — thirty days is typical).

A configuration begins life in `ACTIVE` status. Creating a new configuration whose `config_name` differs from the currently `ACTIVE` one supersedes it: the prior record transitions from `ACTIVE` to `SUPERSEDED`, its `version` increments, and the new record starts at `version` 1. Only one configuration may be `ACTIVE` at a time, and `config_name` must be unique among `ACTIVE` configs; a collision is rejected with `ERR_DUPLICATE_OUR_PLAN` (HTTP 409), the shared uniqueness rejection described in §2.9. Because creation supersedes the incumbent, it is guarded by the `expected_active_config_version` mechanism of §2.7. Configurations may be listed — filterable by `status` — and fetched individually by the analyst and auditor roles as well as the administrator.

### 3.2. Member Enrollment, Demographics, and Disenrollment

An `EligibilityAnalyst` enrolls each member by supplying the `member_external_id` from the enrollment feed (recorded as supplied; the server does not enforce its uniqueness), the member's `full_name`, `date_of_birth` as an ISO calendar date, and `gender` (`MALE`, `FEMALE`, `OTHER`, or `UNKNOWN`). Household structure is captured through `relation_to_subscriber` — `SELF`, `SPOUSE`, `CHILD`, or `OTHER_DEPENDENT` — together with `subscriber_member_id`, which is null for a `SELF` member and otherwise points at the subscriber's member record; the pointer is stored as supplied, without validating that the referenced subscriber exists or that a `SELF` member's pointer is null. The reverse direction is also addressable: an endpoint lists the dependents of a member, i.e. every member whose `subscriber_member_id` points at it.

COB-relevant attributes ride on the member record. `employment_status` is required at enrollment and is one of `ACTIVE`, `RETIRED`, `COBRA`, or `TERMINATED`. The subscriber's `employer_size` (employee count at their employer, defaulting to 0) feeds the Medicare Secondary Payer rules. `custodial_decree_on_file` (default false) records that a court decree specifies which parent's plan is primary for a dependent child. Medicare posture is captured by `medicare_entitlement_reason` — `NONE` (the default), `AGE`, `DISABILITY`, `ESRD`, or `ESRD_AND_AGE` — with `esrd_onset_date` required whenever the entitlement reason includes ESRD (a missing value then is rejected with `ERR_INVALID_REQUEST`); a value supplied alongside a non-ESRD entitlement reason is stored as supplied rather than nulled. The derived `other_coverage_count` reflects how many of the member's coverages are currently `VERIFIED`, excluding the plan's own coverage, and is recomputed by the system whenever verification outcomes change.

A member begins in `ENROLLED` status and remains writable for COB purposes only while enrolled: registering a coverage, verifying a coverage, sending a survey, responding to a survey, drafting a primacy determination, submitting a claim, or adjudicating a claim all require the member to be `ENROLLED`, and any of them attempted against a disenrolled member is rejected with `ERR_MEMBER_DISENROLLED` (HTTP 409).

Disenrollment itself is performed by an `EligibilityAnalyst`, is valid only from `ENROLLED` status — disenrolling a member who is not currently `ENROLLED` is rejected with `ERR_INVALID_STATE` (HTTP 409) — and is blocked while the member has any claim still in `RECEIVED` or `REOPENED` status; the attempt is rejected with `ERR_OPEN_CLAIMS_EXIST` (HTTP 409). When disenrollment proceeds, the member moves from `ENROLLED` to `DISENROLLED`, every coverage of theirs still in `PENDING_VERIFICATION` is automatically rejected (transitioning to `REJECTED`), every survey still `SENT` is expired (transitioning to `EXPIRED`), and the member's `version` increments. The member directory supports filtering by `status` and by `relation_to_subscriber`.

### 3.3. Discovering Other Coverage: Leads, Surveys, and Verification

Other coverage surfaces through four channels, captured by the `source` of an **other-coverage lead**: `MEMBER_SURVEY`, `DATA_MATCH_CMS`, `CLAIM_INDICATION`, or `ELIGIBILITY_MATCH`. A `COBAnalyst` or `EligibilityAnalyst` submits a lead against a member with its `source` and a free-form `raw_payload` describing the evidence (a survey response, a CMS match row, and the like); the system stamps `received_at` and the lead begins with `disposition` `RECEIVED`. Leads may be listed per member with `disposition` and `source` filters, and fetched individually.

The survey channel is member-driven. A `COBAnalyst` or `EligibilityAnalyst` sends a **member survey**; the system records `sent_at` as the current logical clock and computes `due_at` as thirty days after `sent_at`. The survey sits in `SENT` status until the member answers or time runs out. A `MemberSelf` caller answers by submitting `response_payload`; ownership is enforced by comparing `X-User-ID` to the survey's owning member, with mismatches rejected as `ERR_FORBIDDEN`. Responding requires the current clock to be on or before `due_at` — a late response is rejected with `ERR_SURVEY_EXPIRED` (HTTP 409), the same temporal violation family catalogued under `ERR_INVALID_COVERAGE_WINDOW` in §2.9. A successful response moves the survey from `SENT` to `RESPONDED`, stamps `responded_at` (null until that moment; `response_payload` is likewise null until supplied), automatically creates an other-coverage lead whose `source` is `MEMBER_SURVEY` and whose `raw_payload` carries the submitted `response_payload`, and increments both the survey's and the member's `version`. Should the clock advance past `due_at` while the survey is still `SENT`, the survey transitions to `EXPIRED` automatically (see §2.6). Surveys are listed per member with a `status` filter.

Evidence becomes actionable as a **coverage** record. A `COBAnalyst` or `EligibilityAnalyst` registers a coverage under a member with the external `payer_id`, a human-readable `plan_name`, the `coverage_kind` — one of `OUR_PLAN`, `GROUP_HEALTH`, `MEDICARE_PART_A`, `MEDICARE_PART_B`, `MEDICARE_ADVANTAGE`, `MEDICAID`, `TRICARE`, or `INDIVIDUAL` — the `subscriber_relationship` of the member on that coverage (`SELF`, `SPOUSE`, `PARENT`, or `OTHER`), the `policy_holder_dob` used by the birthday rule, the `policy_holder_gender` used by the gender rule (defaulting to `UNKNOWN`), the `effective_from` date, an optional `effective_to` date (null means open-ended), and the `verification_source` channel through which the coverage was discovered (the same four-value enumeration as lead `source`). The derived flag `is_ours` is true exactly when `coverage_kind` is `OUR_PLAN`. Registration already enforces the effective-window rule — `effective_from` must be strictly earlier than `effective_to` whenever an end date is present, an inverted window rejected with `ERR_INVALID_COVERAGE_WINDOW` (HTTP 400) — and the same check is applied again at verification. When the supplied `verification_source` matches the `source` of an existing `RECEIVED` lead for the same member, the registration links that lead to the new coverage, recording the lead's id on the coverage as `linked_lead_id`.

A new coverage begins in `PENDING_VERIFICATION` and is decided by a `COBAnalyst`. Verification first requires the member to be `ENROLLED` (otherwise `ERR_MEMBER_DISENROLLED`), and requires `effective_from` to be strictly earlier than `effective_to` whenever an end date is present — an inverted window is rejected with `ERR_INVALID_COVERAGE_WINDOW` (HTTP 400). For the plan's own coverage there is an additional exclusivity rule: at most one `OUR_PLAN` coverage per member may be `VERIFIED` at any time, and verifying a second is rejected with `ERR_DUPLICATE_OUR_PLAN` (HTTP 409). On successful verification the coverage transitions from `PENDING_VERIFICATION` to `VERIFIED`, the member's `other_coverage_count` is recomputed (counting only `VERIFIED` coverages and excluding `OUR_PLAN` ones), any linked lead transitions from `RECEIVED` to `VERIFIED_COVERAGE`, and both the coverage's and the member's `version` increment. Rejection moves the coverage from `PENDING_VERIFICATION` to `REJECTED`, recomputes `other_coverage_count`, and transitions any linked lead from `RECEIVED` to `REJECTED_NO_COVERAGE`. A `COBAnalyst` may also disposition a lead directly: marking it a duplicate moves it from `RECEIVED` to `REJECTED_DUPLICATE` — the server does not verify that a matching `VERIFIED` coverage actually exists; any `RECEIVED` lead may be so marked — while rejecting it as unsubstantiated moves it from `RECEIVED` to `REJECTED_NO_COVERAGE`. Coverages are listed per member with `verification_status` and `coverage_kind` filters.

Retroactive discovery is where COB earns its keep: when a verified coverage's `effective_from` lies in the past, claims already paid for service dates inside the coverage window may need rework. The server itself computes and stores no rework volume projection or estimate at verification time — the verification response carries only the updated coverage record, and any workload projection is derived downstream by the consumer. The active configuration's `retroactive_lookback_months` documents how far before discovery a newly verified other-coverage window may reach back and trigger claim rework, but the server applies no lookback bound at verification.

### 3.4. Medicare Secondary Payer Compliance

Whenever Medicare coverage enters the picture, federal MSP rules decide who pays first, and the system enforces them through a questionnaire workflow. A questionnaire may be submitted by a `COBAnalyst`, an `EligibilityAnalyst`, or the member via `MemberSelf`. Submission captures the `respondent_role` (`SELF`, `SPOUSE`, or `AUTHORIZED_REP`), whether the member (or spouse, when the respondent is the spouse) is covered under an active-employer group plan via `has_employer_group_health`, the `employer_size` of the employer providing that group health coverage, the `disability_flag` indicating Medicare entitlement due to disability, the `esrd_flag` indicating entitlement due to end-stage renal disease, and the `esrd_onset_date`. The three flags default to false and `employer_size` to null when omitted; submission performs no completeness validation — in particular `esrd_onset_date` is stored as supplied, its requiredness when `esrd_flag` is true being enforced only at adjudication (below). At submission the system derives `age_at_submission` from the member's `date_of_birth` against the current logical clock, and `is_age_65_plus`, which is true when that age is at least 65. The questionnaire begins in `SUBMITTED` status, and its `msp_result` is not yet decided.

Adjudication by a `COBAnalyst` computes the result. The questionnaire must be complete before it can be adjudicated: `employer_size` must be populated when `has_employer_group_health` is true, and `esrd_onset_date` must be populated when `esrd_flag` is true; an incomplete questionnaire is rejected with `ERR_MSP_INCOMPLETE` (HTTP 422). The determination then evaluates a fixed ladder of rules against the questionnaire and the `ACTIVE` rule configuration — when no `ACTIVE` configuration exists, adjudication simply records `MSP_EXEMPT` — and the first rule that fires decides; later rules run only when no earlier one has fired. Month arithmetic on `esrd_onset_date` clamps the day to the target month's length:

1. If `has_employer_group_health` is false, the result is `MEDICARE_PRIMARY` — with no group plan in the picture there is nothing to coordinate.
2. If `esrd_flag` is true and the date `esrd_coordination_months` after `esrd_onset_date` is later than the current clock, the result is `MEDICARE_SECONDARY` — the member is still inside the ESRD coordination window.
3. If `esrd_flag` is true and that coordination end date is on or before the current clock, the result is `MEDICARE_PRIMARY` — the ESRD window is exhausted.
4. If `is_age_65_plus` is true and `employer_size` is at least the configuration's `msp_employer_size_threshold`, the result is `MEDICARE_SECONDARY` — a large active-employer plan pays first for age-based entitlement.
5. If `is_age_65_plus` is true and `employer_size` is below that threshold, the result is `MEDICARE_PRIMARY` — Medicare pays first for small employers.
6. If `disability_flag` is true and `employer_size` is at least the threshold, the result is `MEDICARE_SECONDARY` — the large-employer rule for disability-based entitlement.
7. Otherwise the result is `MSP_EXEMPT`, the rare case that fits no MSP rubric.

Adjudication moves the questionnaire from `SUBMITTED` to `ADJUDICATED`, records the computed `msp_result`, and increments both the questionnaire's and the member's `version`. A `COBAnalyst` may instead void a `SUBMITTED` questionnaire, moving it to `VOIDED`; if any `FINALIZED` primacy determination references the voided questionnaire, that determination is automatically superseded (transitioning to `SUPERSEDED`) as a cascade. Questionnaires are listed per member with a `status` filter.

### 3.5. Determining Primacy

Primacy is decided per member and per service date through a **primacy determination** drafted and finalized by a `COBAnalyst`. Drafting requires the `as_of_service_date` for which primacy is being determined — it must be on or before the current logical clock, since primacy is never decided for future dates, and a future-dated value is rejected with `ERR_INVALID_COVERAGE_WINDOW` — plus an optional `msp_questionnaire_id` and the mandatory `expected_member_version` guard of §2.7. A fresh draft is in `DRAFT` status, its `deciding_rule` is null, its `ordered_coverage_ids` is empty, its `superseded_by_id` is null, and its creation increments the member's `version`. Drafting against a member also participates in supersession: if a `FINALIZED` determination already exists for the same member with the same `as_of_service_date`, that incumbent is automatically superseded once the new determination finalizes.

Finalization is where the ordering is actually computed and locked. The server itself computes `ordered_coverage_ids` at finalization as exactly the member's in-scope coverages — every `VERIFIED` coverage whose `effective_from` is on or before the `as_of_service_date` and whose `effective_to` is either null or on or after that date — ordered primary first, then secondary, and so on by the selection ladder below; the client does not supply `ordered_coverage_ids` or `deciding_rule`, and any such values on the draft or in the finalization request are overwritten rather than validated. Referential integrity guards only the questionnaire reference: when a questionnaire is referenced while no Medicare coverage is in scope, the reference must resolve to an `ADJUDICATED` questionnaire of the same member, and violations are rejected with `ERR_INVALID_DETERMINATION_REFERENCE` (HTTP 422). MSP compliance requires that whenever any in-scope coverage has a `coverage_kind` beginning with `MEDICARE_` — that is, `MEDICARE_PART_A`, `MEDICARE_PART_B`, or `MEDICARE_ADVANTAGE` — the `msp_questionnaire_id` must be supplied and must reference an `ADJUDICATED` questionnaire for this member; any failure of that requirement, including an invalid reference, is rejected with `ERR_MSP_QUESTIONNAIRE_REQUIRED` (HTTP 422).

The server computes `deciding_rule` as the rule the fixed selection ladder produces for the given inputs; because the client asserts no rule, no assertion mismatch can arise. The ladder applies the following rules in order, and the first rule matching the situation wins and is recorded:

1. `CUSTODIAL_DECREE` — the member is a `CHILD` and `custodial_decree_on_file` is true: the server cannot determine which parent the court order designates, so this branch always falls back to the birthday rule — when at least two in-scope coverages are parent-held, they are ordered among themselves by the birthday rule of rule 4 with the remaining coverages appended, and otherwise all in-scope coverages are ordered by the birthday rule. `BIRTHDAY_RULE` is recorded in both cases and `CUSTODIAL_DECREE` is never recorded; the configured `dependent_primacy_rule` is never consulted on this path.
2. `MEDICARE_MSP` — any in-scope coverage has a `coverage_kind` beginning with `MEDICARE_` and a questionnaire is referenced: the referenced questionnaire's `msp_result` decides the ordering between Medicare and the group plan. `MEDICARE_SECONDARY` places the `GROUP_HEALTH` coverages first, then the Medicare coverages, then any others; `MEDICARE_PRIMARY` and `MSP_EXEMPT` both place the Medicare coverages first, then the `GROUP_HEALTH` coverages, then any others; within each group the coverages keep their registration order.
3. `ACTIVE_VS_RETIRED` — keyed on the member's single `employment_status`: the active-employer set (the `GROUP_HEALTH` coverages, when `employment_status` is `ACTIVE`) and the retired set (the `GROUP_HEALTH` coverages, when `employment_status` is `RETIRED` or `COBRA`) can never both be non-empty, so this rule never fires and `ACTIVE_VS_RETIRED` is never recorded; the ladder always proceeds past it.
4. `BIRTHDAY_RULE` — for a dependent child (without a custodial decree, which rule 1 captures) with at least two in-scope parent-held coverages: order those coverages by the `policy_holder_dob` month-and-day in ascending calendar order, so the parent whose birthday occurs earlier in the calendar year holds the primary coverage; a tie on month-and-day is broken by the birth year (the earlier year is primary), a remaining tie is broken by the coverage records' `created_at` in ascending order, and any tie still remaining is broken by `id` ascending. Non-parent-held coverages are appended after the parent-held ones in their registration order.
5. `GENDER_RULE` — for a dependent child with at least two in-scope parent-held coverages, but only when the active configuration's `dependent_primacy_rule` is `GENDER_RULE` (when no configuration is `ACTIVE`, the birthday rule applies instead): the parent-held coverages whose `policy_holder_gender` is `MALE` come first, then the non-`MALE` ones, each group keeping its registration order, with non-parent-held coverages appended; dates of birth are never consulted on this path.
6. `LONGER_ENROLLMENT` — a `SELF` member with two or more in-scope coverages, whatever their `subscriber_relationship`: order by `effective_from` ascending (longer-enrolled first), breaking ties by the coverage records' `created_at` ascending and then by `id` ascending.
7. `NONE` — zero or one coverages are in scope, so no ordering decision is needed. `NONE` is also the fallback whenever multiple coverages are in scope but no earlier rule applies (for example `SPOUSE` or `OTHER_DEPENDENT` members, or a `CHILD` with fewer than two parent-held coverages); the coverages are then ordered by `created_at` ascending, ties broken by `id` ascending.

The full `deciding_rule` vocabulary a determination can carry is `NONE`, `BIRTHDAY_RULE`, `GENDER_RULE`, `CUSTODIAL_DECREE`, `ACTIVE_VS_RETIRED`, `MEDICARE_MSP`, `COURT_ORDER`, and `LONGER_ENROLLMENT`. Finalization moves the determination from `DRAFT` to `FINALIZED`, computes and records `deciding_rule` and `ordered_coverage_ids`, and increments both the determination's and the member's `version`.

Supersession completes the picture: when a newly finalized determination overlaps an incumbent `FINALIZED` determination for the same member and service date, the incumbent transitions from `FINALIZED` to `SUPERSEDED`, its `superseded_by_id` is set to the new determination's `id`, every claim whose `service_date` matches and whose `primacy_determination_id` points at the old determination — whatever the claim's status — automatically gets a draft claim adjustment created with cause `PRIMACY_DETERMINATION_SUPERSEDED` and `triggering_determination_id` set to the new determination's `id`, and the `version` increments on both the old and the new determination records. Determinations are listed per member with a `status` filter, and two top-level reverse-lookup endpoints expose individual determinations and a cross-member list filterable by `status`, `msp_questionnaire_id`, `superseded_by_id`, and `member_id`.

### 3.6. Claim Adjudication and Payment Position

Claims are submitted against registered servicing providers. A `PlatformAdmin` registers each provider with its `npi` (a unique national provider identifier), `legal_name`, and `tin`; providers carry an `ACTIVE` or `TERMINATED` status, and the provider directory can be listed with an `npi` filter and fetched individually.

A `ClaimsExaminer` submits a claim by naming the patient (`member_id`), the servicing provider (`provider_id`), the unique external claim number `claim_external_id` (a duplicate is rejected with `ERR_DUPLICATE_OUR_PLAN`, per the uniqueness family of §2.9), the `service_date`, the `received_date`, and the `total_billed_cents` — conventionally the sum of billed amounts across the claim's lines, recorded as supplied without a sum check. A `member_id` or `provider_id` that resolves to no existing record is rejected with `ERR_NOT_FOUND` (HTTP 404). The member must be `ENROLLED` at submission (`ERR_MEMBER_DISENROLLED` otherwise). A new claim is in `RECEIVED` status, its `primacy_determination_id` is null until adjudication, and its `rework_cycle_count` — the number of times the claim has been reprocessed due to retroactive coverage change — begins at zero. Lines are added to the claim — in any claim status — with a client-supplied `line_number` (recorded as supplied; 1-based sequencing and per-claim uniqueness are not enforced), the `procedure_code` (CPT/HCPCS), `billed_cents`, `allowed_cents` after repricing, and `primary_paid_cents`, the amount the primary payer paid on the line: it defaults to 0 when omitted, and the server does not enforce that it be 0 when this plan is primary or populated when this plan is secondary. The claim directory supports filtering by `status`, `member_id`, `provider_id`, and `primacy_determination_id`.

Adjudication by a `ClaimsExaminer` requires the member to be `ENROLLED` at the time of adjudication, and requires exactly one `FINALIZED` primacy determination to exist for the member and service date — if none or several match, adjudication is rejected with `ERR_NO_FINAL_PRIMACY` (HTTP 422). Adjudication records that determination's `id` on the claim and computes each line's `paid_cents`, and thereby the claim totals, according to the plan's payment position:

- **This plan is primary** (the first entry of the determination's `ordered_coverage_ids` is the `OUR_PLAN` coverage): each line's `paid_cents` is the lesser of its `allowed_cents` and its `billed_cents`, rounded half-up to integer cents per line. The claim's `total_allowed_cents` is the sum of the lines' `allowed_cents`, `total_paid_cents` is the sum of the lines' `paid_cents`, and `total_primary_paid_cents` is 0.
- **This plan is secondary** (the first entry of `ordered_coverage_ids` is any other coverage): each line's `paid_cents` is the greater of zero and the amount by which the lesser of `allowed_cents` and `billed_cents` exceeds the line's `primary_paid_cents` — the plan pays the residual after the primary's payment, capped at what it would have paid as primary. Claim totals are the sums across lines: `total_paid_cents` over `paid_cents`, `total_primary_paid_cents` over `primary_paid_cents`, and `total_allowed_cents` over `allowed_cents`, again rounded per line then summed, with the sum never re-rounded.

Two adjudication variants exist in time. Initial adjudication — the transition from `RECEIVED` to `ADJUDICATED` — computes lines using the single `FINALIZED` determination whose `as_of_service_date` equals the claim's `service_date`; coverages still `PENDING_VERIFICATION` neither block payment nor record any alert flag. In the secondary position, this provisional pass uses the `primary_paid_cents` supplied on the line by the provider or remittance, which may be 0 when the primary's payment is not yet known — in which case the line pays at its full allowed amount. Final readjudication — the rework transition from `REOPENED` to `READJUDICATED` — recomputes lines against the latest `FINALIZED` determination effective on the `service_date`, pending coverages again do not block, and the secondary pass uses the verified `primary_paid_cents` from the primary payer's remittance; overpayment versus underpayment is then derived by diffing the provisional and final results. Payment moves the claim from `ADJUDICATED` to `PAID` and increments its `version`; adjudication itself increments both the claim's and the member's `version`.

### 3.7. Rework, Adjustments, and Recovery

Retroactive coverage changes send paid claims back through the machine. A `RecoverySpecialist` reopens a claim — only a `PAID` claim can be reopened — and the reopen must be backed by a triggering claim adjustment whose `cause` is one of `NEW_COVERAGE_DISCOVERED`, `PRIMACY_DETERMINATION_SUPERSEDED`, or `MSP_QUESTIONNAIRE_ADJUDICATED` — any adjustment on the claim with a qualifying cause authorizes the reopen, whatever the adjustment's own status; without one, the reopen is rejected with `ERR_NO_VALID_ADJUSTMENT_CAUSE` (HTTP 409). Note that `MANUAL_REVIEW`, though a legitimate adjustment cause for drafting, does not authorize a reopen. Reopening moves the claim from `PAID` to `REOPENED`, increments `rework_cycle_count` by one, and increments the claim's `version`.

**Claim adjustments** are the bookkeeping of rework. A `ClaimsExaminer` or `COBAnalyst` drafts an adjustment against a claim with a `cause` — `NEW_COVERAGE_DISCOVERED`, `PRIMACY_DETERMINATION_SUPERSEDED`, `MSP_QUESTIONNAIRE_ADJUDICATED`, or `MANUAL_REVIEW` — and an optional `triggering_determination_id` naming the new determination driving the change; the draft is in `DRAFT` status. Applying the adjustment is a `ClaimsExaminer` action requiring the claim to be in `PAID` or `REOPENED` status. When the cause is `PRIMACY_DETERMINATION_SUPERSEDED`, the triggering determination must be `FINALIZED`; otherwise the apply is rejected with `ERR_TRIGGERING_DET_NOT_FINAL` (HTTP 422). On apply, the adjustment snapshots `pre_paid_cents` from the claim's current `total_paid_cents`, recomputes the claim under the triggering determination to produce `post_paid_cents` — or, when `triggering_determination_id` is unset or unresolved, under the determination currently recorded on the claim, and when neither resolves performs no recomputation, leaving `post_paid_cents` equal to `pre_paid_cents` — and derives the financial delta: `overpayment_cents` is the amount by which the pre-adjustment total exceeds the post-adjustment total, floored at zero, and `underpayment_cents` is the amount by which the post-adjustment total exceeds the pre-adjustment total, floored at zero — by construction at most one of the two is positive. The adjustment transitions from `DRAFT` to `APPLIED` and its `version` increments; a draft may instead be voided, moving it from `DRAFT` to `VOIDED` with no further effect. Readjudication of the claim requires an `APPLIED` adjustment to exist for it — without one, the readjudicate action is rejected with `ERR_NO_APPLIED_ADJUSTMENT` (HTTP 409) — and recomputes each line's `paid_cents` and the claim totals against the most recently created `FINALIZED` determination for the member and the claim's `service_date`, recording that determination's `id` as the claim's new `primacy_determination_id`; when no `FINALIZED` determination exists for the service date, the claim still transitions to `READJUDICATED` with its existing determination and amounts unchanged. Readjudication moves the claim from `REOPENED` to `READJUDICATED` and increments the claim's `version`, but not the member's. Repayment then moves it from `READJUDICATED` to `REPAID`, again incrementing the claim's `version`. Adjustments are listed per claim with a `status` filter, and top-level reverse lookups expose single adjustments and a cross-claim list filterable by `status`, `claim_id`, and `triggering_determination_id`.

When rework establishes that the plan overpaid, a `RecoverySpecialist` drafts a **recovery request** against the claim, naming the `provider_id` from whom reimbursement is sought and the `amount_cents` to recover. The named `provider_id` must resolve to an existing provider, otherwise the request is rejected with `ERR_NOT_FOUND` (HTTP 404). Fiscal integrity is strict: the `amount_cents` must equal the originating adjustment's `overpayment_cents` — the originating adjustment being the most recently created `APPLIED` adjustment on the claim, whose id the request records as `adjustment_id`; arbitrary splits are not permitted — and that overpayment must be greater than zero; drafting or issuing otherwise is rejected with `ERR_NO_OVERPAYMENT` (HTTP 422). Issuing the request additionally requires the claim to be `REPAID`, so the overpayment is fully established first. Issuance moves the request from `DRAFT` to `ISSUED`, stamps `issued_at` with the current logical clock, computes `due_date` as `issued_at` plus the active configuration's `recovery_window_days` (defaulting to thirty days when no configuration is `ACTIVE`), and increments the request's `version`.

Reimbursements post against an issued request with an `amount_cents` and a `method` — `PROVIDER_REFUND_CHECK`, `OFFSET_AGAINST_FUTURE_CLAIMS`, or `CARRIER_TO_CARRIER_TRANSFER` — and are stamped with a `received_at` equal to the current logical clock; `amount_cents` is checked only against the remaining balance, so zero or negative amounts are accepted. A reimbursement may not exceed the remaining unrecovered balance, that is, the request's `amount_cents` minus its `amount_recovered_cents` at posting time; an excess is rejected with `ERR_OVERRECOVERY` (HTTP 422). Each posting adds its amount to `amount_recovered_cents`, and the request's status follows the money automatically: the first partial posting moves it from `ISSUED` to `PARTIALLY_RECOVERED`, and when `amount_recovered_cents` reaches `amount_cents` the request becomes `FULLY_RECOVERED` — a single reimbursement covering the full amount moves an `ISSUED` request directly to `FULLY_RECOVERED`, with `amount_recovered_cents` set equal to `amount_cents`.

When reimbursement does not arrive, escalation and write-off are explicit `RecoverySpecialist` actions gated on being past due. Escalating an `ISSUED` request requires the current clock to be later than `due_date` with `amount_recovered_cents` still below `amount_cents`; a request not yet past due is rejected with `ERR_NOT_PAST_DUE` (HTTP 409), and a successful escalation moves the request to `ESCALATED` and increments its `version`. Writing off an `ISSUED` request carries the same past-due-with-balance precondition and the same `ERR_NOT_PAST_DUE` rejection, moving the request to `WRITTEN_OFF` and incrementing its `version`. A request already `PARTIALLY_RECOVERED` can likewise be escalated when the clock is past `due_date` and a balance remains, or written off once the clock is past `due_date`. A claim can finally be closed — moving from `REPAID` to `CLOSED` by a `RecoverySpecialist` — only when every recovery request against it is terminal, meaning `FULLY_RECOVERED` or `WRITTEN_OFF`; closure increments the claim's `version`. Recovery requests are listed per claim with a `status` filter, reimbursements are listed per recovery request, and top-level reverse lookups expose individual recovery requests and reimbursements plus cross-claim lists filterable by `status`, `claim_id`, and `provider_id` for requests, and by `recovery_request_id` for reimbursements.

### 3.8. Savings Reporting

The **COB savings period** is the unit of program accounting, maintained by a `COBAuditor`. Opening a period requires its `period_start_date` and `period_end_date`, both inclusive, conventionally spanning the active configuration's `savings_period_length_days`. The period sits in `OPEN` posture while claims are adjudicated, adjustments are applied, and reimbursements post.

Closing a period requires the current logical clock to be later than `period_end_date`; an attempt before the period has ended is rejected with `ERR_PERIOD_NOT_ENDED` (HTTP 409). At close, the period's three totals are snapshotted. `total_avoided_cents` sums, over every claim line on claims whose primacy placed this plan in a secondary position with `service_date` inside the period, the amount by which the line's `allowed_cents` exceeds this plan's `paid_cents` — the expenditure the plan avoided by not being primary. `total_recovered_cents` sums every reimbursement `amount_cents` whose `received_at` falls inside the period. `total_claims_adjusted` counts the adjustments in `APPLIED` status whose `updated_at` falls inside the period. Closing moves the posture from `OPEN` to `CLOSED` and increments the period's `version`. Periods are listed with a `posture` filter and fetched individually.

## 4. Endpoint Definitions

Operations that create a new resource — a rule config, provider, member, coverage, lead, survey, questionnaire, determination draft, claim, claim line, adjustment, recovery request, reimbursement, or savings period — return `201 Created`. Operations that modify or act upon an existing resource (verification, disenrollment, adjudication, payment, reopen, readjudication, repayment, closure, apply/void, issue/escalate/write-off, survey response, period close, and the clock capability) return `200 OK`. All endpoints are mounted under the `/cob` prefix. The table below is a summary only; request payloads, derived fields, and side effects are specified in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cob/rule-configs` | Create a new ACTIVE rule config; supersedes the prior ACTIVE config | PlatformAdmin |
| GET | `/cob/rule-configs` | List rule configs | PlatformAdmin, COBAnalyst, COBAuditor |
| GET | `/cob/rule-configs/{id}` | Fetch a rule config by id | PlatformAdmin, COBAnalyst, COBAuditor |
| POST | `/cob/providers` | Register a provider | PlatformAdmin |
| GET | `/cob/providers/{id}` | Fetch a provider | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAnalyst |
| GET | `/cob/providers` | List providers | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAnalyst |
| POST | `/cob/members` | Create a member | EligibilityAnalyst |
| GET | `/cob/members/{id}` | Fetch a member | PlatformAdmin, EligibilityAnalyst, COBAnalyst, ClaimsExaminer, RecoverySpecialist, COBAuditor, MemberSelf |
| GET | `/cob/members` | List members | PlatformAdmin, EligibilityAnalyst, COBAnalyst, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| POST | `/cob/members/{id}/disenroll` | Disenroll a member | EligibilityAnalyst |
| GET | `/cob/members/{id}/dependents` | List members whose subscriber pointer references this member | PlatformAdmin, EligibilityAnalyst, COBAnalyst, ClaimsExaminer, MemberSelf |
| POST | `/cob/members/{id}/coverages` | Register an other-coverage record for a member | COBAnalyst, EligibilityAnalyst |
| GET | `/cob/members/{id}/coverages` | List coverages for a member | PlatformAdmin, COBAnalyst, EligibilityAnalyst, ClaimsExaminer, RecoverySpecialist, MemberSelf |
| GET | `/cob/members/{id}/coverages/{coverageId}` | Fetch a coverage | PlatformAdmin, COBAnalyst, EligibilityAnalyst, ClaimsExaminer, RecoverySpecialist, MemberSelf |
| POST | `/cob/members/{id}/coverages/{coverageId}/verify` | Verify a coverage | COBAnalyst |
| POST | `/cob/members/{id}/coverages/{coverageId}/reject` | Reject a coverage | COBAnalyst |
| POST | `/cob/members/{id}/other-coverage-leads` | Submit an other-coverage lead | COBAnalyst, EligibilityAnalyst |
| GET | `/cob/members/{id}/other-coverage-leads` | List leads for a member | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| GET | `/cob/members/{id}/other-coverage-leads/{leadId}` | Fetch a lead | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| POST | `/cob/members/{id}/other-coverage-leads/{leadId}/mark-duplicate` | Mark a lead as a duplicate of existing verified coverage | COBAnalyst |
| POST | `/cob/members/{id}/other-coverage-leads/{leadId}/reject` | Reject a lead (no coverage found) | COBAnalyst |
| POST | `/cob/members/{id}/member-surveys` | Send a member survey | COBAnalyst, EligibilityAnalyst |
| GET | `/cob/members/{id}/member-surveys` | List surveys for a member | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| GET | `/cob/members/{id}/member-surveys/{surveyId}` | Fetch a survey | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| POST | `/cob/members/{id}/member-surveys/{surveyId}/respond` | Submit a survey response (member self-service) | MemberSelf |
| POST | `/cob/members/{id}/msp-questionnaires` | Submit an MSP questionnaire | COBAnalyst, EligibilityAnalyst, MemberSelf |
| GET | `/cob/members/{id}/msp-questionnaires` | List questionnaires for a member | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| GET | `/cob/members/{id}/msp-questionnaires/{questionnaireId}` | Fetch a questionnaire | PlatformAdmin, COBAnalyst, EligibilityAnalyst, MemberSelf |
| POST | `/cob/members/{id}/msp-questionnaires/{questionnaireId}/adjudicate` | Adjudicate an MSP questionnaire | COBAnalyst |
| POST | `/cob/members/{id}/msp-questionnaires/{questionnaireId}/void` | Void an MSP questionnaire | COBAnalyst |
| POST | `/cob/members/{id}/primacy-determinations` | Draft a new primacy determination | COBAnalyst |
| GET | `/cob/members/{id}/primacy-determinations` | List primacy determinations for a member | PlatformAdmin, COBAnalyst, ClaimsExaminer, RecoverySpecialist, MemberSelf |
| GET | `/cob/members/{id}/primacy-determinations/{determinationId}` | Fetch a determination | PlatformAdmin, COBAnalyst, ClaimsExaminer, RecoverySpecialist, MemberSelf |
| POST | `/cob/members/{id}/primacy-determinations/{determinationId}/finalize` | Finalize a determination; computes rule and ordering | COBAnalyst |
| POST | `/cob/claims` | Submit a claim | ClaimsExaminer |
| GET | `/cob/claims/{id}` | Fetch a claim | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAnalyst, COBAuditor |
| GET | `/cob/claims` | List claims | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAnalyst, COBAuditor |
| POST | `/cob/claims/{id}/lines` | Add a claim line | ClaimsExaminer |
| GET | `/cob/claims/{id}/lines` | List lines on a claim | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAnalyst, COBAuditor |
| POST | `/cob/claims/{id}/adjudicate` | Adjudicate a claim; computes per-line payment by primacy | ClaimsExaminer |
| POST | `/cob/claims/{id}/pay` | Mark a claim paid | ClaimsExaminer |
| POST | `/cob/claims/{id}/reopen` | Reopen a paid claim for rework | RecoverySpecialist |
| POST | `/cob/claims/{id}/readjudicate` | Readjudicate a reopened claim against the new determination | ClaimsExaminer |
| POST | `/cob/claims/{id}/repay` | Mark a claim repaid after readjudication | ClaimsExaminer |
| POST | `/cob/claims/{id}/close` | Close a claim (terminal) | RecoverySpecialist |
| POST | `/cob/claims/{id}/adjustments` | Create a draft claim adjustment | ClaimsExaminer, COBAnalyst |
| GET | `/cob/claims/{id}/adjustments` | List adjustments on a claim | PlatformAdmin, ClaimsExaminer, COBAnalyst, RecoverySpecialist, COBAuditor |
| GET | `/cob/claims/{id}/adjustments/{adjustmentId}` | Fetch an adjustment | PlatformAdmin, ClaimsExaminer, COBAnalyst, RecoverySpecialist, COBAuditor |
| POST | `/cob/claims/{id}/adjustments/{adjustmentId}/apply` | Apply an adjustment; computes over/underpayment | ClaimsExaminer |
| POST | `/cob/claims/{id}/adjustments/{adjustmentId}/void` | Void an adjustment | ClaimsExaminer |
| POST | `/cob/claims/{id}/recovery-requests` | Draft a recovery request | RecoverySpecialist |
| GET | `/cob/claims/{id}/recovery-requests` | List recovery requests on a claim | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| GET | `/cob/claims/{id}/recovery-requests/{recoveryId}` | Fetch a recovery request | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| POST | `/cob/claims/{id}/recovery-requests/{recoveryId}/issue` | Issue a recovery request | RecoverySpecialist |
| POST | `/cob/claims/{id}/recovery-requests/{recoveryId}/escalate` | Escalate an overdue recovery request | RecoverySpecialist |
| POST | `/cob/claims/{id}/recovery-requests/{recoveryId}/write-off` | Write off an overdue recovery request | RecoverySpecialist |
| POST | `/cob/claims/{id}/recovery-requests/{recoveryId}/reimbursements` | Post a reimbursement against a recovery request | RecoverySpecialist |
| GET | `/cob/claims/{id}/recovery-requests/{recoveryId}/reimbursements` | List reimbursements against a recovery request | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| POST | `/cob/savings-periods` | Open a new savings reporting period | COBAuditor |
| GET | `/cob/savings-periods/{id}` | Fetch a savings period | PlatformAdmin, COBAuditor, COBAnalyst |
| GET | `/cob/savings-periods` | List savings periods | PlatformAdmin, COBAuditor, COBAnalyst |
| POST | `/cob/savings-periods/{id}/close` | Close a savings period; snapshots totals | COBAuditor |
| GET | `/cob/primacy-determinations/{id}` | Fetch a single primacy determination by id (top-level reverse lookup) | PlatformAdmin, COBAnalyst, ClaimsExaminer, RecoverySpecialist, MemberSelf |
| GET | `/cob/primacy-determinations` | List primacy determinations across members | PlatformAdmin, COBAnalyst, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| GET | `/cob/adjustments/{id}` | Fetch a single claim adjustment by id (top-level reverse lookup) | PlatformAdmin, ClaimsExaminer, COBAnalyst, RecoverySpecialist, COBAuditor |
| GET | `/cob/adjustments` | List claim adjustments across claims | PlatformAdmin, ClaimsExaminer, COBAnalyst, RecoverySpecialist, COBAuditor |
| GET | `/cob/recovery-requests/{id}` | Fetch a single recovery request by id (top-level reverse lookup) | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| GET | `/cob/recovery-requests` | List recovery requests across claims | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| GET | `/cob/reimbursements/{id}` | Fetch a single reimbursement by id (top-level reverse lookup) | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| GET | `/cob/reimbursements` | List reimbursements across recovery requests | PlatformAdmin, ClaimsExaminer, RecoverySpecialist, COBAuditor |
| POST | `/cob/_clock/set_current_utc` | Set the logical clock (test-driving capability) | PlatformAdmin |

## 5. Error Code Catalogue

The following table lists every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_COVERAGE_WINDOW` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MEMBER_DISENROLLED` | 409 Conflict |
| `ERR_OPEN_CLAIMS_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_OUR_PLAN` | 409 Conflict |
| `ERR_NO_FINAL_PRIMACY` | 422 Unprocessable Entity |
| `ERR_MSP_QUESTIONNAIRE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_MSP_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_INVALID_DETERMINATION_REFERENCE` | 422 Unprocessable Entity |
| `ERR_TRIGGERING_DET_NOT_FINAL` | 422 Unprocessable Entity |
| `ERR_NO_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_OVERRECOVERY` | 422 Unprocessable Entity |
| `ERR_NOT_PAST_DUE` | 409 Conflict |
| `ERR_SURVEY_EXPIRED` | 409 Conflict |
| `ERR_NO_VALID_ADJUSTMENT_CAUSE` | 409 Conflict |
| `ERR_NO_APPLIED_ADJUSTMENT` | 409 Conflict |
| `ERR_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INTERNAL` | 500 Internal Server Error |

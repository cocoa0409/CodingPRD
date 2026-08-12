# Corporate Investigations API — Product Requirements Document

## 1. Introduction

Modern corporations face sustained regulatory and reputational exposure when employee misconduct goes undetected or is investigated inconsistently. Allegations arrive through hotlines, anonymous portals, manager referrals, and external channels; the difference between a defensible investigation and a lawsuit often comes down to whether the organization can demonstrate a chain of custody over evidence, segregation of duties between drafters and approvers, attorney-client privilege over sensitive artifacts, and a tamper-evident audit trail of every stage gate. This document specifies the Corporate Investigations API, a system built for an in-house investigations team that handles the full lifecycle of an employee-misconduct case: intake and triage, plan approval, evidence preservation and collection, witness interviews with Upjohn warnings, findings calibration, disciplinary recommendation, regulatory self-disclosure, remediation tracking, and cross-case pattern analysis.

The system serves eight distinct operator roles — intake coordinators, investigators, investigations managers, HR business partners, general counsel, the chief legal officer, compliance auditors, and a system administrator for test-driving the logical clock — and enforces segregation of duties at every sensitive transition so that no single operator can both propose and approve, draft and ratify, or own and verify the same artifact. All state changes, derived counters, and cross-entity cascades are immediately and atomically visible in the response that produces them.

The API is mounted under `/api`. All endpoints are versioned implicitly by that prefix; there is no further version segment.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` (the opaque identifier of the acting operator) and `X-User-Role` (one of the declared role names below). Missing or unknown values are rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not listed in the endpoint's authorized role set, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The eight declared role names, spelled exactly as the server expects them in `X-User-Role`, are:

- `IntakeCoordinator`
- `Investigator`
- `InvestigationsManager`
- `HRBusinessPartner`
- `GeneralCounsel`
- `ChiefLegalOfficer`
- `ComplianceAuditor`
- `SystemAdmin`

Every role's `X-User-ID` is **opaque** — it is not the `id` of any persisted entity. The server may record it on rows it creates or transitions (for example, as `lead_investigator_id` on a `Case`, `drafter_id` on an `InvestigationPlan`, `approved_by` on a plan, `proposed_by` on a `DisciplinaryRecommendation`, `designated_by` on a `PrivilegeDesignation`, `decided_by` on a `SelfDisclosureDecision`, or `verified_by` on a `RemediationAction`), and segregation-of-duties rules compare these recorded opaque ids to the calling `X-User-ID`. No resource-ownership check against any entity's `id` is performed for any role.

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

All list endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 and is clamped into the range 1 to 100 (a value below 1 is read as 1, a value above 100 as 100); a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. `offset` defaults to 0 and is clamped to a minimum of 0. List results are sorted by `created_at` ascending unless a different sort option is explicitly named in §3; rows whose `created_at` values are exactly equal (the logical clock has whole-second resolution) are ordered by creation (insertion) order, and `id` is never used as a tie-break. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`; `total_count` is the number of rows remaining after filters are applied and before the page is sliced, and `has_more` is true exactly when `offset` plus the number of rows returned is less than `total_count`.

### 2.4. Common Resource Properties, Identity, and Versioning

Every persisted resource carries `id` as a server-minted UUID with no type prefix. Every resource also carries `created_at` and `updated_at` as ISO 8601 UTC timestamps at whole-second precision, serialized as `YYYY-MM-DDTHH:MM:SSZ`, and an integer `version` starting at 1 that increments by exactly 1 on each mutation of that row driven through that row's own endpoints, including cascades that move the row's own status. The recomputation of a `Case`'s derived fields (`preservation_completeness_ratio`, `active_privileged_artifact_count`, `open_remediation_count`, `case_priority_score`, `priority_tier`, `pattern_escalated`) triggered by mutations of other entities does not by itself increment the `Case`'s `version`; the `Case`'s version increments only on its own transitions and on the creates and approvals where §3 explicitly states the increment. There are no exceptions: all fourteen entities declared by this document share these common fields.

### 2.5. Idempotency on POST

Every POST request must carry an `Idempotency-Key` header. A request without one is rejected with `ERR_MISSING_IDEMPOTENCY_KEY` (HTTP 400). When the server receives a key it has already seen, it compares the request against the original over the HTTP method, the request path, and the JSON payload (compared as parsed JSON, insensitive to key ordering): an identical request returns the original response unchanged, replayed with its original status code and body, while a difference in any of the three is rejected with `ERR_IDEMPOTENCY_REPLAY_MISMATCH` (HTTP 409).

### 2.6. The Logical Clock and Test-Driving

All deadline, cooling-off, overdue, recency, and window computations in this document read a single logical clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`; before any clock-set call it never falls back to wall-clock time. A `SystemAdmin` may advance the clock by supplying a `to_iso8601` instant to the test-driving endpoint; the supplied instant is stored truncated to whole-second precision and is not required to be later than the current value, and once set, all subsequent reads observe the new value. The clock-set endpoint responds HTTP 200 with a `data` object of the form `{"current_utc": "<new clock value>"}`. Operations that stamp the current instant — `issued_at`, `acknowledged_at`, `upjohn_delivered_at`, `completed_at`, `decided_at`, `filed_at`, `distributed_at`, `window_end` — read from this clock.

### 2.7. Optimistic Concurrency Control on Case-Bound Creates

Three creation endpoints are protected by optimistic concurrency control on the parent `Case`: creating an `InvestigationPlan`, creating a `CaseReport`, and creating a `SelfDisclosureDecision`. Each of these requests must carry an `expected_case_version` field whose value equals the parent `Case`'s current `version` at the time the server processes the request. An absent field is rejected with `ERR_MISSING_REQUIRED_FIELD` (HTTP 400). A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a plan, report, or disclosure whose underlying case it has not observed. No other endpoint accepts a version field.

### 2.8. Validation Priority Order

When multiple validation rules apply to a single request, the server evaluates them in a fixed priority order so that callers see a deterministic error. From highest to lowest:

1. **Authentication** — `X-User-Role` and `X-User-ID` presence and role recognition (`ERR_UNAUTHENTICATED`).
2. **Idempotency** — `Idempotency-Key` presence on POSTs and replay consistency (`ERR_MISSING_IDEMPOTENCY_KEY`, `ERR_IDEMPOTENCY_REPLAY_MISMATCH`).
3. **Authorization** — caller role membership in the endpoint's role set (`ERR_UNAUTHORIZED_ROLE`).
4. **Existence** — path ids validated left-to-right, then body-referenced ids such as `allegation_id`, `subject_id`, `preservation_notice_id`, `target_id`, and elements of `evidence_item_ids` (`ERR_NOT_FOUND`).
5. **Optimistic-concurrency state** — `expected_case_version` matches the parent case (`ERR_STALE_VERSION`).
6. **State machine legality** — within this tier the per-transition actor role is checked first (a violation is rejected with `ERR_UNAUTHORIZED_ROLE`), then the target entity's from-state is checked against the requested transition (`ERR_INVALID_STATE`).
7. **Segregation-of-duties and compliance-safety gates** — `ERR_SOD_PLAN_APPROVAL`, `ERR_SOD_FINDING_FINALIZATION`, `ERR_SOD_DISCIPLINE_APPROVAL`, `ERR_SOD_REMEDIATION_VERIFICATION`, `ERR_SOD_DISCLOSURE_OVERRIDE`, `ERR_UPJOHN_REQUIRED`, `ERR_PRIVILEGE_PENDING`, `ERR_PRIVILEGED_DISTRIBUTION`, `ERR_COOLING_OFF`, `ERR_ORDERED_NOTICE_RESTRICTION`.
8. **Business constraints** — uniqueness, overlap, threshold, and aggregate rules: `ERR_PLAN_SUBMITTED_EXISTS`, `ERR_DUPLICATE_SUBJECT`, `ERR_DUPLICATE_DESIGNATION`, `ERR_INTERVIEWER_OVERLAP`, `ERR_ROOM_OVERLAP`, `ERR_SCOPE_OVERLAP`, `ERR_OPEN_RECOMMENDATION_EXISTS`, `ERR_THRESHOLD_NOT_MET`, `ERR_EMPTY_COLLECTION`, `ERR_OPEN_COLLECTION_SCOPES`, `ERR_PRESERVATION_INCOMPLETE`, `ERR_FINDINGS_NOT_FINAL`, `ERR_UNRESOLVED_DISCIPLINE`, `ERR_DISCLOSURE_REQUIRED`, `ERR_OPEN_REMEDIATION`, `ERR_SUBJECT_HAS_OPEN_FINDINGS`, `ERR_VALIDATION`.
9. **Cross-entity referential rules** — `ERR_CUSTODIAN_NOT_PRESERVED`, `ERR_NOTICE_NOT_ACKNOWLEDGED`, `ERR_ALLEGATION_NOT_LINKED`, `ERR_SUBJECT_NOT_IN_CASE`, `ERR_EVIDENCE_NOT_REVIEWABLE`, `ERR_TARGET_CASE_MISMATCH`.
10. **Clock-relative rules** — `ERR_INTERVIEW_WINDOW_EXPIRED`, `ERR_NO_SHOW_TOO_EARLY`, `ERR_SCHEDULE_IN_PAST`, plus internal window-order checks surfaced as `ERR_VALIDATION`.

Required-field presence (`ERR_MISSING_REQUIRED_FIELD`) and malformed-value errors (`ERR_VALIDATION`) are not separately tiered: each surfaces at the moment the handler reads the field in question. A handler reads its primary payload fields after path-id existence (tier 4) and before the numbered tiers above, so those parse-time errors precede body-referenced existence, optimistic-concurrency, state, and business checks; companion fields of a transition payload (such as `rationale`, `rejection_reason`, or `completion_note`) are read at the point in the transition where they gate, after that transition's earlier checks. Two same-payload checks run ahead of tier 5: the plan-creation `planned_end`-strictly-after-`planned_start` check and the report-creation non-empty-`distribution_list` check. Interview creation applies its `scheduled_end`-strictly-after-`scheduled_start` check before the tier-8 overlap checks; collection-scope creation applies its closed-interval window-order check at tier 10, after the tier-8 overlap and tier-9 coverage checks.

### 2.9. Numeric Precision and Rounding

All monetary-free numeric quantities in this system are unitless scores, integer counts, integer minutes, or ratios. The rounding contract is uniform: any place this document says "round half-up" refers to half-up rounding (toward positive infinity on ties). Two-decimal scores and ratios are rounded half-up to 2 decimal places. Integer indexes are rounded half-up at the multiplication step. Per-item evidence effort minutes are rounded UP to whole minutes (ceiling) before any sum is taken. Datetime comparisons are at second precision.

### 2.10. Nested Resource Retrieval

When an endpoint's URL contains more than one path parameter, the server resolves them left-to-right. If a parent id does not exist, the request fails with `ERR_NOT_FOUND` (HTTP 404) before any child id is consulted. The same rule applies to body-referenced ids — `allegation_id`, `subject_id`, `preservation_notice_id`, `target_id`, and elements of `evidence_item_ids` — each of which must exist and is reported as `ERR_NOT_FOUND` when it does not.

### 2.11. State-Transition Endpoint Contract

Every state-machine transition endpoint accepts a single required payload field, `to_status`, naming the target state as an exact UPPERCASE string from the entity's state enumeration. An absent `to_status` is rejected with `ERR_MISSING_REQUIRED_FIELD`; a value outside the entity's state enumeration is rejected with `ERR_VALIDATION`; an in-enumeration value naming a transition that is not legal from the entity's current state is rejected with `ERR_INVALID_STATE`. Individual transitions may additionally require companion fields such as `rationale`, `rejection_reason`, `completion_note`, `new_start`, `new_end`, `decision`, `consistency_level`, `subject_admission`, or `finding_type` — these are described in §3 alongside the transitions they gate.

### 2.12. Recomputed-on-Read Derived Flags

Two per-row fields are recomputed against the logical clock on every read rather than stored persistently: `is_overdue` on `RemediationAction` and the time-relative urgency term inside `case_priority_score`. All other derived counters and ratios are recomputed atomically by the mutations that affect them and are returned in the same response.

## 3. Business Logic & Workflows

This section walks the lifecycle of a corporate investigation as it actually unfolds, from the moment an allegation arrives to the day a case is closed and its lessons feed cross-case pattern analysis. Sub-sections follow the natural narrative stages of the pipeline rather than entity boundaries; rules for a given entity appear wherever the narrative naturally touches them.

### 3.1. Intake, Triage, and Case Creation

A case begins when an `IntakeCoordinator` files it. Creation requires `title`, `allegation_category`, `severity`, and `lead_investigator_id`; `description` and `department` are optional at this stage. The `allegation_category` is one of `FRAUD`, `HARASSMENT`, `CONFLICT_OF_INTEREST`, `DATA_BREACH`, `BRIBERY`, `POLICY_VIOLATION`. The `severity` is one of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` and is provisional at create time — it will be confirmed at triage. The `lead_investigator_id` is the opaque `X-User-ID` of the assigned lead investigator and serves as the segregation-of-duties anchor when findings are later finalized.

Upon creation the server assigns a `case_number` of the form `INV-<yyyy>-<NNNN>` — for example `INV-2026-0001` — where the four-digit sequence is zero-padded and ordered by `created_at` across all cases created in the same calendar year. The new case enters `INTAKE` status. Its initial derived values are: `preservation_completeness_ratio` of 1.00 (vacuous compliance with no notices yet), `active_privileged_artifact_count` of 0, `open_remediation_count` of 0, `pattern_escalated` false, and a `case_priority_score` computed by the rule described in §3.10 below. That score is then mapped into a `priority_tier` of `ROUTINE`, `ELEVATED`, or `URGENT` by the same rule.

Allegations arrive against the case. Filing one requires `reporter_channel` (one of `HOTLINE`, `EMAIL`, `MANAGER_REFERRAL`, `ANONYMOUS_PORTAL`, `EXTERNAL`), `is_anonymous`, and `narrative`; `reporter_ref` and `occurred_at` are optional. When `is_anonymous` is true, `reporter_ref` must be null — providing one is rejected with `ERR_VALIDATION`. An allegation cannot be filed against a `CLOSED` or `DISMISSED` case; the attempt is rejected with `ERR_INVALID_STATE`. A successfully filed allegation enters `SUBMITTED`.

Triage is the `IntakeCoordinator`'s next step. Moving a case from `INTAKE` to `TRIAGED` requires the payload to carry a confirmed `severity` (one of the four values) and a non-empty `department` — omitting either is rejected with `ERR_MISSING_REQUIRED_FIELD` (a `department` that is present but empty or whitespace-only counts as omitted; a `severity` value outside the four is rejected with `ERR_VALIDATION`). On a successful triage the case's `severity` and `department` are overwritten by the payload values, every allegation still in `SUBMITTED` advances to `TRIAGED` alongside the parent, and the case's `case_priority_score` is recomputed (because the severity term may have changed). Dismissal, performed by an `IntakeCoordinator`, is also possible from either `INTAKE` or `TRIAGED` and requires a `rationale` in the payload; on dismissal every allegation in `SUBMITTED` or `TRIAGED` cascades to `DISMISSED`. Individual allegations may also be moved independently from `SUBMITTED` to `TRIAGED` (when not already moved by the case-level cascade); this move imposes no requirement on the parent case's status. From `TRIAGED` an allegation may move to `LINKED` (permitted only while the parent case is in `TRIAGED`, `PLANNING`, `FIELDWORK`, or `FINDINGS` — otherwise `ERR_INVALID_STATE`), or from `SUBMITTED` or `TRIAGED` to `DISMISSED` with a `rationale`.

### 3.2. Investigation Planning and Approval

Once a case is `TRIAGED` or `PLANNING`, an `Investigator` may draft an `InvestigationPlan` (creation while the case is in any other status is rejected with `ERR_INVALID_STATE`). Creation requires `scope_statement`, `planned_start`, and `planned_end` — the planned end must be strictly after the planned start, otherwise `ERR_VALIDATION` — together with the OCC field `expected_case_version` per §2.7. The new plan's `plan_version` is one greater than the maximum `plan_version` of all plans ever created for the case; the very first plan has `plan_version` 1. The creating investigator's `X-User-ID` is recorded as `drafter_id`, which will anchor the segregation-of-duties check at approval.

Plan creation has two cascades. First, any prior plan of the same case that is still in `DRAFT` or `REJECTED` is moved to `SUPERSEDED`. Second, the parent case's `version` increments by 1 on every plan creation, and if the parent case is `TRIAGED` it also advances to `PLANNING`. Creation is blocked while another plan of the case is in `SUBMITTED` (`ERR_PLAN_SUBMITTED_EXISTS`) — a submitted plan must be approved or rejected before a fresh draft can begin.

A plan in `DRAFT` may be submitted by any `Investigator` (the submitter is not required to be the recorded `drafter_id`), transitioning `DRAFT` to `SUBMITTED`; the parent case must still be in `PLANNING` (`ERR_INVALID_STATE` otherwise). An `InvestigationsManager` then decides. Approval transitions `SUBMITTED` to `APPROVED`, records the approver's `X-User-ID` as `approved_by`, advances the parent case from `PLANNING` to `FIELDWORK`, and increments the case's `version` by 1. Rejection transitions `SUBMITTED` to `REJECTED` and records the supplied `rejection_reason`. Both approval and rejection are subject to segregation of duties: the acting manager's `X-User-ID` must differ from the plan's `drafter_id`, or the call is rejected with `ERR_SOD_PLAN_APPROVAL`. A missing `rejection_reason` on a rejection is rejected with `ERR_MISSING_REQUIRED_FIELD`.

### 3.3. Subjects, Preservation, and Collection Scoping

With a plan approved and the case in `FIELDWORK`, three parallel tracks open: subject attachment, legal preservation, and collection scoping. Subject attachment itself is not gated on the case's status.

An `Investigator` attaches a `CaseSubject` by supplying `employee_ref` (the HR employee identifier and the cross-case pattern-analysis key) and `role_in_case` (one of `PRIMARY`, `ACCESSORY`, `PERSON_OF_INTEREST`). At most one subject with the same `employee_ref` may be non-terminal on a case — duplicates are rejected with `ERR_DUPLICATE_SUBJECT`. New subjects enter `ACTIVE`. An `Investigator` or `InvestigationsManager` may later move a subject to `CLEARED` (permitted only when no `Finding` references the subject in `DRAFT`, `CALIBRATED`, or `CHALLENGED` — otherwise `ERR_SUBJECT_HAS_OPEN_FINDINGS`) or to `SEPARATED` (unconditionally). Both `CLEARED` and `SEPARATED` are terminal for the subject.

In parallel, `GeneralCounsel` issues `PreservationNotice` rows. Issuance requires `custodian_ref`, `scope` (one of `EMAIL`, `DEVICES`, `CHAT`, `FILES`, `ALL_DATA`), and `is_regulator_ordered`. Issuance is permitted only when the case is in `PLANNING` or any later non-terminal status; in particular, the case must not be `INTAKE`, `CLOSED`, or `DISMISSED`. A new notice enters `ISSUED`, with `issued_at` set to the current logical clock, and the case's `preservation_completeness_ratio` is recomputed. A notice in `ISSUED` may be acknowledged by `GeneralCounsel`, which sets `acknowledged_at` to the current logical clock and again recomputes the ratio.

Releasing a notice — whether from `ISSUED` or `ACKNOWLEDGED` — moves it to `RELEASED`. If `is_regulator_ordered` is true, release is forbidden until the parent case is `CLOSED`; attempting earlier release is rejected with `ERR_ORDERED_NOTICE_RESTRICTION`. Release has a two-hop cascade: every `CollectionScope` of the same case whose `custodian_ref` matches the released notice's `custodian_ref` and that is currently in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` is moved to `WITHDRAWN` (hop 1); the parent case's `preservation_completeness_ratio` is then recomputed, with `RELEASED` notices excluded from both numerator and denominator (hop 2).

The `preservation_completeness_ratio` is the count of the case's notices in `ACKNOWLEDGED` divided by the sum of the counts in `ACKNOWLEDGED` and `ISSUED`; `RELEASED` notices are excluded from both terms. When the case has no notices in `ISSUED` or `ACKNOWLEDGED`, the ratio is defined to be 1.00. The ratio is rounded half-up to 2 decimal places.

### 3.4. Collection Scopes and Evidence Custody

Collection scopes describe what will actually be pulled from which custodian. An `Investigator` proposes a scope with `custodian_ref`, `data_source` (one of `EMAIL`, `DEVICE`, `CHAT`, `FILES`), `planned_start`, and `planned_end`; `preservation_notice_id` is optional. Scope creation requires the parent case to be in `FIELDWORK`. The window is closed-interval: `planned_end` must be greater than or equal to `planned_start` (equal is allowed), otherwise `ERR_VALIDATION`. The custodian must be covered by an `ISSUED` or `ACKNOWLEDGED` preservation notice whose `scope` covers the requested `data_source` — `ALL_DATA` covers every source; `EMAIL` covers `EMAIL`; `DEVICES` covers `DEVICE`; `CHAT` covers `CHAT`; `FILES` covers `FILES` — otherwise the create is rejected with `ERR_CUSTODIAN_NOT_PRESERVED`. When supplied, `preservation_notice_id` must reference an existing notice and is recorded as a back-reference; the coverage requirement is satisfied by any covering notice of the case, not necessarily the referenced one. Two scopes of the same case with the same `custodian_ref` and `data_source` may not have overlapping planned windows while either is in `PROPOSED`, `APPROVED`, or `IN_PROGRESS`; the closed-interval intersection test treats touching endpoints as a conflict (`ERR_SCOPE_OVERLAP`). A new scope enters `PROPOSED`, with `collected_item_count` and `collected_bytes` initialized to 0 and `review_effort_minutes` null until completion.

Scope approval is performed by an `InvestigationsManager` and requires the case still be in `FIELDWORK` and the covering preservation notice be `ACKNOWLEDGED` (an `ISSUED`-but-unacknowledged covering notice is rejected with `ERR_NOTICE_NOT_ACKNOWLEDGED`). The investigator then begins the collection (`APPROVED` to `IN_PROGRESS`), which requires the covering notice to still be in `ISSUED` or `ACKNOWLEDGED` — if it has been released in the meantime, the begin is rejected with `ERR_CUSTODIAN_NOT_PRESERVED`. A scope in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` may be moved to `WITHDRAWN` at any time by an `Investigator` or `InvestigationsManager`; each withdraw recomputes the case's derived fields.

Evidence items are logged against a scope in `IN_PROGRESS`. Logging requires `custodian_ref`, `hash_value` (the SHA-256 content hash for chain of custody), `size_bytes`, and `captured_at`; `description` is optional. The supplied `custodian_ref` must equal the scope's `custodian_ref`, and `size_bytes` must be greater than zero — violations are rejected with `ERR_VALIDATION`. A newly logged item enters `LOGGED`, its `case_id` is denormalized from the scope (and equals the scope's case), and the scope's `collected_item_count` and `collected_bytes` are recomputed. The custody totals count only items in `LOGGED`, `UNDER_REVIEW`, or `ADMITTED`; `EXCLUDED` items drop out of both terms and re-enter if restored.

Evidence review walks the item through `LOGGED` to `UNDER_REVIEW` to `ADMITTED` or `EXCLUDED`. An `ADMITTED` item may also move to `EXCLUDED`, and an additional restore path returns `EXCLUDED` to `ADMITTED`. Both the admit and the restore are blocked while any `PrivilegeDesignation` exists with `target_type` of `EVIDENCE_ITEM`, `target_id` equal to the item, and `status` of `DESIGNATED` (pending confirmation); the rejection is `ERR_PRIVILEGE_PENDING`. Every transition recomputes the parent scope's `collected_item_count` and `collected_bytes`.

Completing a collection, performed by an `Investigator`, moves a scope from `IN_PROGRESS` to `COLLECTED` and requires at least one linked evidence item in `LOGGED`, `UNDER_REVIEW`, or `ADMITTED`; otherwise `ERR_EMPTY_COLLECTION`. On this transition the scope's `review_effort_minutes` is computed. The computation has a pinned rounding order: for each evidence item linked to the scope whose status at completion time is one of `LOGGED`, `UNDER_REVIEW`, `ADMITTED`, or `EXCLUDED`, the per-item raw effort is the item's `size_bytes` divided by one million and then multiplied by 2 (the minutes-per-megabyte constant); each per-item raw value is rounded UP to the next whole minute (ceiling); the rounded per-item minutes are summed to a subtotal; the subtotal is multiplied by 1.15 (the overhead constant); and the product is rounded half-up to a whole number of minutes. The alternative order — summing raw sizes first and rounding once at the end — is forbidden because it produces a different result.

### 3.5. Witness Interviews and the Upjohn Warning

Interviews are scheduled by an `Investigator` while the case is in `FIELDWORK`. Scheduling requires `witness_ref`, `interviewer_id`, `scheduled_start`, and `scheduled_end`; `room_ref` and `is_subject_interview` are optional. The scheduled end must be strictly after the scheduled start. When `is_subject_interview` is true (the witness is also a case subject), the interview never counts toward the substantiation W term described in §3.7; the default is false. A new interview enters `SCHEDULED` with `no_show_count` 0.

Two overlap rules apply at scheduling. First, the same `interviewer_id` may not have another interview in `SCHEDULED` or `UPJOHN_DELIVERED` whose half-open interval — start inclusive, end exclusive — intersects the requested window; adjacent windows where one's end equals the other's start are permitted. Violations are rejected with `ERR_INTERVIEWER_OVERLAP`. Second, when `room_ref` is supplied, the same room may not have another interview in `SCHEDULED` or `UPJOHN_DELIVERED` whose window, expanded by fifteen minutes on both sides, intersects the requested window — back-to-back bookings with a gap of less than fifteen minutes are rejected (`ERR_ROOM_OVERLAP`).

Once `SCHEDULED`, the interviewer delivers the Upjohn warning by transitioning the interview to `UPJOHN_DELIVERED`. This transition requires the current logical clock to be no later than `scheduled_end`; after that moment the window has expired and the transition is rejected with `ERR_INTERVIEW_WINDOW_EXPIRED`. On success `upjohn_delivered_at` is set to the current logical clock.

Completion moves `UPJOHN_DELIVERED` to `COMPLETED`. Two preconditions apply: `upjohn_delivered_at` must already be present (the Upjohn warning must precede completion; `ERR_UPJOHN_REQUIRED` otherwise), and the payload must carry a non-empty `completion_note` (`ERR_MISSING_REQUIRED_FIELD` otherwise). On success `completed_at` is set to the current logical clock.

A witness who does not appear is recorded by transitioning `SCHEDULED` to `NO_SHOW`, which requires the current logical clock to be strictly later than `scheduled_end`; attempting it at or before the scheduled end is rejected with `ERR_NO_SHOW_TOO_EARLY`. The payload may carry an optional `no_show_reason`; the value is accepted but not recorded on the interview. Each transition into `NO_SHOW` increments `no_show_count` by exactly 1. From `NO_SHOW` the interview may be rescheduled back to `SCHEDULED`: the payload must carry `new_start` and `new_end` (`ERR_MISSING_REQUIRED_FIELD` when absent), with `new_start` strictly before `new_end` (`ERR_VALIDATION` otherwise), `new_start` must be no earlier than the current logical clock (`ERR_SCHEDULE_IN_PAST`), the interviewer half-open overlap check is re-run on the new window (`ERR_INTERVIEWER_OVERLAP`), and the room fifteen-minute-buffer overlap check is re-run when `room_ref` is present (`ERR_ROOM_OVERLAP`); in both re-run checks the interview being rescheduled is excluded from the scan. On a successful reschedule `scheduled_start` and `scheduled_end` are overwritten by `new_start` and `new_end`, and `upjohn_delivered_at` is cleared — the Upjohn warning must be delivered anew before the rescheduled interview may complete. Either `SCHEDULED` or `UPJOHN_DELIVERED` may also transition to `CANCELLED`; on the latter path `upjohn_delivered_at` is retained for audit.

### 3.6. Privilege Designation

`GeneralCounsel` designates privilege over an artifact of the case by creating a `PrivilegeDesignation` with `target_type` (one of `EVIDENCE_ITEM`, `INTERVIEW`, `CASE_REPORT`), `target_id` (the polymorphic id of the designated `EvidenceItem`, `WitnessInterview`, or `CaseReport`), and `privilege_type` (one of `ACP` for attorney-client privileged or `WORK_PRODUCT`); `rationale` is optional. The designated target must belong to the same case as the designation — a mismatch is rejected with `ERR_TARGET_CASE_MISMATCH`. At most one active designation — `DESIGNATED`, `CONFIRMED`, or `CHALLENGED` — may exist per (`target_type`, `target_id`) pair; a second active designation is rejected with `ERR_DUPLICATE_DESIGNATION`. The designating counsel's `X-User-ID` is recorded as `designated_by`, the new designation enters `DESIGNATED`, and the case's `active_privileged_artifact_count` is incremented by 1.

The designation lifecycle runs `DESIGNATED` to `CONFIRMED` (performed by `GeneralCounsel`), `CONFIRMED` to `CHALLENGED` (performed by `ChiefLegalOfficer`), `CHALLENGED` back to `CONFIRMED` (reaffirm, performed by `GeneralCounsel`), and from any of `DESIGNATED`, `CONFIRMED`, or `CHALLENGED` to `WAIVED` (performed by `GeneralCounsel`). Moving to `CONFIRMED` leaves the case's `active_privileged_artifact_count` unchanged because `CONFIRMED` still counts as active. Moving to `WAIVED` from any of the three active states decrements the case's `active_privileged_artifact_count` by 1. The count of a case's privileged artifacts equals the number of `PrivilegeDesignation` rows for the case in `DESIGNATED`, `CONFIRMED`, or `CHALLENGED`.

### 3.7. Findings, Substantiation, and Calibration

A `Finding` ties an allegation to a subject and, optionally, to supporting evidence. Creation requires `allegation_id` and `subject_id`; `evidence_item_ids` is optional and defaults to an empty array. The case must be in `FINDINGS`. The referenced allegation must be in `LINKED` status and belong to the case, otherwise `ERR_ALLEGATION_NOT_LINKED`. The referenced subject must belong to the case, otherwise `ERR_SUBJECT_NOT_IN_CASE`. Each element of `evidence_item_ids` must reference an `EvidenceItem` that belongs to the case and is in `UNDER_REVIEW` or `ADMITTED` at link time, otherwise `ERR_EVIDENCE_NOT_REVIEWABLE`. A new finding enters `DRAFT`, and the server computes its `substantiation_score_provisional` per the provisional variant of the substantiation rule below.

The substantiation score is the minimum of 1.00 and the weighted sum of four terms: 0.25 times the evidence count E, plus 0.15 times the interview count W, plus the consistency term C, plus 0.10 times the admission indicator A. The result is rounded half-up to 2 decimal places, applied once after the minimum is taken.

The provisional variant, computed at creation, defines E as the number of evidence ids in the finding's `evidence_item_ids` whose item status is `UNDER_REVIEW` or `ADMITTED`, W as the number of `WitnessInterview` rows of the case with `is_subject_interview` false and status `UPJOHN_DELIVERED` or `COMPLETED`, C fixed at 0.15 (the MEDIUM consistency value), and A fixed at 0. The final variant, computed at calibration and recalibration, narrows both input sets: E counts only evidence in `ADMITTED`, W counts only interviews in `COMPLETED` (still restricted to `is_subject_interview` false), and C and A come from the calibrate payload — C is 0.00 when `consistency_level` is `LOW`, 0.15 when `MEDIUM`, or 0.30 when `HIGH`; A is 1 when `subject_admission` is true, 0 otherwise.

Calibration is performed by an `HRBusinessPartner` and moves the finding from `DRAFT` to `CALIBRATED`. The payload must carry `consistency_level` (one of `LOW`, `MEDIUM`, `HIGH`) and `finding_type` (one of `SUBSTANTIATED`, `UNSUBSTANTIATED`, `INCONCLUSIVE`); `subject_admission` is optional and defaults to false. Missing required fields are rejected with `ERR_MISSING_REQUIRED_FIELD`. On calibration, `substantiation_score_final` is computed per the final variant, and `consistency_level`, `subject_admission`, and `finding_type` are recorded. A `SUBSTANTIATED` finding requires `substantiation_score_final` to be at least 0.70; below the threshold the calibration is rejected with `ERR_THRESHOLD_NOT_MET`.

Finalization is performed by an `InvestigationsManager` and moves the finding from `CALIBRATED` to `FINAL`. Segregation of duties applies: the approver's `X-User-ID` must differ from the parent case's `lead_investigator_id`, otherwise `ERR_SOD_FINDING_FINALIZATION`. `FINAL` is challengeable — `GeneralCounsel` or an `InvestigationsManager` may move a `FINAL` finding to `CHALLENGED`, and doing so recalls every `DisciplinaryRecommendation` of the finding currently in `APPROVED` to `RECALLED`. A `CHALLENGED` finding may be recalibrated back to `CALIBRATED` by an `HRBusinessPartner` under the same payload requirements and the same 0.70 substantiation threshold as the original calibration; on recalibration `substantiation_score_final` is recomputed.

### 3.8. Disciplinary Recommendation

Once a finding is `FINAL`, an `HRBusinessPartner` may propose a `DisciplinaryRecommendation` against it. At most one `PROPOSED` recommendation may exist per finding — a second concurrent proposal is rejected with `ERR_OPEN_RECOMMENDATION_EXISTS`. The proposal payload carries `mitigation_count`, `aggravation_count`, `recommended_action` (one of `COACHING`, `WARNING`, `SUSPENSION`, `TERMINATION`, `NONE`), and an optional `justification`. Both counts accept values 0, 1, or 2; values above 2 are clamped to 2, and negative values are rejected with `ERR_VALIDATION`. `justification` is required whenever the `recommended_action` differs from the computed `suggested_action`; its absence in that case is rejected with `ERR_MISSING_REQUIRED_FIELD`, while any supplied value — even an empty string — satisfies the requirement.

At proposal the server records the proposing partner's `X-User-ID` as `proposed_by`, snapshots the parent case's `severity` into `severity_assessment`, computes `prior_history_count`, computes both index variants, and maps `index_calibrated` into `suggested_action`.

`prior_history_count` is the number of `Finding` rows in `FINAL` status with `finding_type` of `SUBSTANTIATED` on cases other than this case, whose subject's `employee_ref` equals this finding's subject's `employee_ref`, and whose `created_at` is strictly earlier than this finding's `created_at`. Ties in `created_at` are broken in favor of the earliest-created finding.

The discipline severity index has two variants, both stored on the recommendation. The base is 10 times the severity weight, where `LOW` weighs 1, `MEDIUM` 2, `HIGH` 3, and `CRITICAL` 4. The prior-history multiplier is 1 plus 0.25 times the smaller of `prior_history_count` and 3. The `index_policy_matrix` is the product of the base and the multiplier, rounded half-up to an integer, and it ignores mitigation and aggravation entirely. The `index_calibrated` is `index_policy_matrix` plus 5 times the smaller of `aggravation_count` and 2, minus 5 times the smaller of `mitigation_count` and 2.

The tier mapping is shared by both variants: an index strictly below 20 maps to `COACHING`; an index of at least 20 and at most 39 maps to `WARNING`; an index of at least 40 and at most 59 maps to `SUSPENSION`; an index of at least 60 maps to `TERMINATION`. The `suggested_action` stored on the recommendation is the tier of `index_calibrated`; the tier of `index_policy_matrix` is derivable from the stored `index_policy_matrix` and is not itself stored.

Approval or rejection of a recommendation is performed by an `InvestigationsManager`. Approval is subject to segregation of duties: the approver's `X-User-ID` must differ from `proposed_by`, otherwise `ERR_SOD_DISCIPLINE_APPROVAL`. Rejection requires a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent). An `APPROVED` recommendation is recalled to `RECALLED` automatically when its parent finding moves from `FINAL` to `CHALLENGED` — whether by direct challenge or by the case-reopen cascade. `RECALLED` is terminal for that row; a new recommendation may be proposed once the finding returns to `FINAL`.

### 3.9. Case Report, Privilege Pinning, and Distribution

An `Investigator` drafts a `CaseReport` against a case in `FINDINGS`, `DISPOSITION`, or `REMEDIATION`. Creation requires `title`, `distribution_tier` (one of `RESTRICTED`, `LEGAL_CONFIDENTIAL`, `BOARD`), `distribution_list` (a non-empty array of opaque recipient ids — an empty list is rejected with `ERR_VALIDATION`), and `report_privilege_type` (one of `ACP`, `WORK_PRODUCT`, `NONE`), together with the OCC field `expected_case_version` per §2.7. Any prior report of the same case still in `DRAFT` is moved to `SUPERSEDED`, and the case's `version` increments by 1. The new report enters `DRAFT`.

Legal review, performed by an `Investigator`, moves the report from `DRAFT` to `LEGAL_REVIEW` and requires every finding of the parent case to be in `FINAL` — a case with any finding in `DRAFT`, `CALIBRATED`, or `CHALLENGED` rejects the transition with `ERR_FINDINGS_NOT_FINAL`.

Distribution approval is performed by `GeneralCounsel` and moves the report from `LEGAL_REVIEW` to `DISTRIBUTION_APPROVED`. Approval requires every `PrivilegeDesignation` of the case to be in `CONFIRMED` or `WAIVED` — any designation still in `DESIGNATED` or `CHALLENGED` rejects the approval with `ERR_PRIVILEGE_PENDING`. On approval, `pinned_designation_snapshot` is set to the list of ids of the case's `PrivilegeDesignation` rows that are in `CONFIRMED` at that instant, ordered by `created_at` ascending with creation order breaking exact ties; this version-pinned snapshot locks the privilege basis of the approved report.

Distribution moves `DISTRIBUTION_APPROVED` to `DISTRIBUTED` and is performed by `GeneralCounsel`. When the report's `distribution_tier` is `BOARD`, two additional gates apply: the acting caller must instead be a `ChiefLegalOfficer` (otherwise `ERR_UNAUTHORIZED_ROLE`), and no evidence item linked to any finding of the case may carry a `PrivilegeDesignation` of type `ACP` in `DESIGNATED` or `CONFIRMED` (otherwise `ERR_PRIVILEGED_DISTRIBUTION`). On successful distribution `distributed_at` is set to the current logical clock. A `DISTRIBUTED` report may be recalled by `GeneralCounsel` to `RECALLED`, which is terminal.

### 3.10. Case Priority Score

The case priority score is a raw integer stored as `case_priority_score` and mapped into `priority_tier`. The evaluation order is pinned to break any appearance of circularity between score, tier, and backlog:

1. The raw score is 10 times the severity weight (`LOW` 1, `MEDIUM` 2, `HIGH` 3, `CRITICAL` 4), plus 15 if `pattern_escalated` is true, plus 10 if there exists a `SelfDisclosureDecision` of this case in `PENDING` whose `decision_deadline` is no later than the current logical clock plus 7 days. The raw score depends only on severity and on these flags and deadlines; backlog never feeds it.
2. The `priority_tier` is `URGENT` when the raw score is at least 40, `ELEVATED` when it is at least 20 and below 40, and `ROUTINE` when it is below 20.
3. Backlog ordering — used only by the priority-sorted list option — orders cases within a tier by raw score descending, then by `created_at` ascending; `created_at` is the only permitted tie-break criterion, exact `created_at` ties fall back to creation (insertion) order, and the `id` must not be used.

The score is recomputed at case creation, on any transition that changes severity, on changes to `pattern_escalated`, on changes to the urgency term's relevance (such as a `PENDING` decision being created or decided), and on pattern-alert transitions that flow through `pattern_escalated`.

### 3.11. Regulatory Self-Disclosure

A `SelfDisclosureDecision` records the organization's position on whether to self-disclose to a regulator. `GeneralCounsel` opens one against a case in `FINDINGS` or `DISPOSITION`, supplying `regulator` (one of `SEC`, `DOJ`, `DOL`, `FINRA`, `DATA_PROTECTION`), `decision_deadline`, and the OCC field `expected_case_version` per §2.7. Creation supersedes any prior decision of the same case for the same regulator that is still in `PENDING` (moving it to `SUPERSEDED`), increments the case's `version` by 1, and recomputes the case's `case_priority_score` because the deadline-urgency term may now apply. The new decision enters `PENDING`.

Decision is made by the `ChiefLegalOfficer` and moves `PENDING` to `DECIDED`. The payload must carry `decision` as one of `DISCLOSE` or `NO_DISCLOSE` (`ERR_MISSING_REQUIRED_FIELD` when absent); an optional `rationale` may be supplied in the decide payload and is recorded when present. On decision, `decided_by` is set to the caller's `X-User-ID`, `decided_at` is set to the current logical clock, and the case's `case_priority_score` is recomputed (the deadline-urgency term is re-evaluated).

Filing is performed by `GeneralCounsel` and moves `DECIDED` to `FILED`. Two preconditions apply: the recorded `decision` must be `DISCLOSE` (otherwise `ERR_DECISION_NOT_DISCLOSE`), and the current logical clock must be at least `decided_at` plus 72 hours — a mandatory cooling-off period (otherwise `ERR_COOLING_OFF`). On success `filed_at` is set to the current logical clock.

A decided decision may be overridden by the `ChiefLegalOfficer` to `OVERRIDDEN`. The override is subject to segregation of duties: the overrider's `X-User-ID` must differ from `decided_by` (`ERR_SOD_DISCLOSURE_OVERRIDE`), and the payload must carry a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent).

The disclosure gate on case progression is in §3.12 below.

### 3.12. Findings-Exit, Disposition, Remediation, and Case Close

Three stage gates guard the back half of the case pipeline, each checked on the corresponding transition.

Moving a case from `FIELDWORK` to `FINDINGS` is performed by an `Investigator` and requires two conditions: no `CollectionScope` of the case may remain in `PROPOSED`, `APPROVED`, or `IN_PROGRESS` (`ERR_OPEN_COLLECTION_SCOPES`), and the case's `preservation_completeness_ratio` must equal 1.00 (`ERR_PRESERVATION_INCOMPLETE`) — meaning every issued notice has been acknowledged and none remain in `ISSUED`. A reverse path from `FINDINGS` back to `FIELDWORK` is available to an `InvestigationsManager`; this cycle permits additional evidence collection after findings work has begun.

Moving from `FINDINGS` to `DISPOSITION` is performed by an `InvestigationsManager` and requires every `Finding` of the case to be in `FINAL` — none in `DRAFT`, `CALIBRATED`, or `CHALLENGED` — otherwise `ERR_FINDINGS_NOT_FINAL`.

Moving from `DISPOSITION` to `REMEDIATION` is performed by an `InvestigationsManager` and requires two conditions. First, every `DisciplinaryRecommendation` on every finding of the case must be in `APPROVED` or `REJECTED` — none may remain in `PROPOSED` — otherwise `ERR_UNRESOLVED_DISCIPLINE`. Second, if the case's severity is `CRITICAL`, there must be at least one `SelfDisclosureDecision` of the case in `DECIDED`, `FILED`, or `OVERRIDDEN`, and none may be in `PENDING` — otherwise `ERR_DISCLOSURE_REQUIRED`.

### 3.13. Remediation Actions

`HRBusinessPartner` opens remediation actions against a case in `DISPOSITION` or `REMEDIATION`. Creation requires `action_type` (one of `POLICY_UPDATE`, `TRAINING`, `PROCESS_CHANGE`, `CONTROL_IMPLEMENTATION`, `MONITORING`), `owner_ref` (an opaque owner identifier and the segregation-of-duties anchor for verification), `description`, and `due_date`. A new action enters `OPEN`, and the parent case's `open_remediation_count` is incremented by 1.

The action's `is_overdue` flag is recomputed on every read and on every transition: it is true when the current logical clock is strictly later than `due_date` and the action's status is one of `OPEN`, `IN_PROGRESS`, or `AWAITING_VERIFICATION`. The boundary is strict — when the clock equals `due_date` exactly, `is_overdue` is false.

The action progresses `OPEN` to `IN_PROGRESS` to `AWAITING_VERIFICATION` (both moves performed by `HRBusinessPartner`). Verification is performed by a `ComplianceAuditor` and moves `AWAITING_VERIFICATION` to `VERIFIED`; segregation of duties requires the verifier's `X-User-ID` to differ from `owner_ref` (`ERR_SOD_REMEDIATION_VERIFICATION`). On verification `verified_by` is set to the caller's `X-User-ID` and the case's `open_remediation_count` is decremented by 1. A `ComplianceAuditor` may instead reject the verification, returning the action from `AWAITING_VERIFICATION` to `IN_PROGRESS`; rejection requires a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent). Independently, `GeneralCounsel` may waive an action from either `OPEN` or `IN_PROGRESS` to `WAIVED`; waiver also requires a `rationale` and decrements the case's `open_remediation_count` by 1.

The count of a case's open remediations equals the number of `RemediationAction` rows for the case in `OPEN`, `IN_PROGRESS`, or `AWAITING_VERIFICATION`.

### 3.14. Case Close and Reopen

Closing a case is performed by an `InvestigationsManager` and moves `REMEDIATION` to `CLOSED`. It requires every `RemediationAction` of the case to be in `VERIFIED` or `WAIVED` — any action still in `OPEN`, `IN_PROGRESS`, or `AWAITING_VERIFICATION` rejects the close with `ERR_OPEN_REMEDIATION`. `CLOSED` is reopenable.

Reopening is performed by an `InvestigationsManager` and moves `CLOSED` back to `FIELDWORK`. The payload must carry a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent). Reopen triggers a three-hop cascade: every `Finding` of the case in `FINAL` moves to `CHALLENGED` (hop 1); every `DisciplinaryRecommendation` in `APPROVED` whose finding just became `CHALLENGED` moves to `RECALLED` (hop 2, caused by hop 1); and every `CaseReport` of the case in `DISTRIBUTED` moves to `RECALLED` because its findings basis is challenged (hop 3, also caused by hop 1). The case's derived fields are then recomputed.

`DISMISSED` is the case's only true terminal state.

### 3.15. Pattern Alerts and Cross-Case Pattern Analysis

`ComplianceAuditor` runs a cross-case pattern scan over a rolling window. The scan accepts an optional `window_days` parameter (default 90), supplied either in the JSON body or as a query parameter; it must be a positive number and is otherwise rejected with `ERR_VALIDATION`. The window ends at the current logical clock and starts `window_days` earlier; a case qualifies for the window when its `created_at` falls within the closed interval [`window_start`, `window_end`]. Four alert types are produced. `REPEAT_SUBJECT` fires when at least 2 cases in the window share a subject `employee_ref`. `CATEGORY_SPIKE` fires when at least 3 cases share an `allegation_category`. `DEPARTMENT_CLUSTER` fires when at least 3 cases share a `department` (cases with no `department` recorded never cluster). `RETALIATION_RISK` fires when a `witness_ref` of an earlier-created case appears as a subject `employee_ref` of a later-created case within the window. Cases in `DISMISSED` never qualify. Each alert's `alert_key` is the grouping key — the `employee_ref` for `REPEAT_SUBJECT` and `RETALIATION_RISK`, the category for `CATEGORY_SPIKE`, the department for `DEPARTMENT_CLUSTER` — and `window_start` and `window_end` record the scan bounds. The scan is idempotent on (`alert_type`, `alert_key`, `window_start`): an existing `OPEN` or `ACKNOWLEDGED` alert with the same key is returned, not duplicated. New alerts enter `OPEN`. Each alert's `case_ids` lists the qualifying cases ordered by `created_at` ascending.

Each newly created alert's `pattern_risk_score` and `risk_tier` are computed by the pattern-risk rule. Let C be the qualifying case set, with n its size (n is at least 2 by construction). The severity maximum `sev_max` is the largest severity weight across C, where `LOW` weighs 1, `MEDIUM` 2, `HIGH` 3, and `CRITICAL` 4. The recency distance d is the number of days between the latest case `created_at` in C and `window_end`, rounded DOWN to whole days, and is always between 0 and 90 inclusive. The recency factor is the larger of 0.20 and the quantity 1 minus d divided by 90. The distinct-department count is the number of distinct non-null `department` values across C; the spread factor is 1 plus 0.25 times the smaller of (distinct-department count minus 1) and 2. The volume factor is 1 plus 0.5 times (n minus 1). The score is 10 times `sev_max` times the volume factor times the recency factor times the spread factor, capped at 100 by an outer minimum, and rounded half-up to 2 decimal places after the cap. The `risk_tier` is `HIGH` when the score is at least 70, `MEDIUM` when it is at least 40 and below 70, and `LOW` when it is below 40.

An `InvestigationsManager` may acknowledge an `OPEN` alert (moving it to `ACKNOWLEDGED`), escalate an `ACKNOWLEDGED` alert (moving it to `ESCALATED`), or dismiss an alert from either `OPEN` or `ACKNOWLEDGED` to `DISMISSED`. Dismissal requires a `rationale` (`ERR_MISSING_REQUIRED_FIELD` when absent). Acknowledging and dismissing each recompute `pattern_escalated` for every case in the alert's `case_ids`. Escalation has a two-hop cascade: every case in `case_ids` has its `pattern_escalated` recomputed by the defining rule below — which the now-`ESCALATED` alert forces to true for every case it names when its `alert_type` is `REPEAT_SUBJECT` or `DEPARTMENT_CLUSTER`, regardless of the case's own status (hop 1) — and each such case recomputes its `case_priority_score` and `priority_tier` from the new flag (hop 2, caused by hop 1).

A case's `pattern_escalated` flag is true while any non-dismissed `PatternAlert` with `alert_type` of `REPEAT_SUBJECT` or `DEPARTMENT_CLUSTER` names the case in `case_ids` and is in `ACKNOWLEDGED` or `ESCALATED`. It is recomputed on every alert transition that affects the case.

### 3.16. Listing and Cross-Entity Lookup

Every list endpoint accepts the standard pagination parameters and returns rows sorted by `created_at` ascending. Several lists expose foreign-key reverse-lookup filters: allegations by `case_id`, `status`, `reporter_channel`; plans by `case_id`, `status`; subjects by `case_id`, `employee_ref`, `status`; preservation notices by `case_id`, `custodian_ref`, `status`; collection scopes by `case_id`, `preservation_notice_id`, `custodian_ref`, `data_source`, `status`; evidence items by `collection_scope_id`, `case_id`, `custodian_ref`, `status`; interviews by `case_id`, `witness_ref`, `interviewer_id`, `status`; privilege designations by `case_id`, `target_type`, `privilege_type`, `status`; findings by `case_id`, `allegation_id`, `subject_id`, `finding_type`, `status`; disciplinary recommendations by `finding_id`, `status`, `recommended_action`; reports by `case_id`, `status`, `distribution_tier`; self-disclosure decisions by `case_id`, `regulator`, `status`, `decision`; remediation actions by `case_id`, `owner_ref`, `status`, `action_type`; pattern alerts by `alert_type`, `alert_key`, `status`. The case list additionally accepts `status`, `category`, `severity`, `department`, and `lead_investigator_id` filters, plus a `sort` parameter; when `sort` is `priority`, cases are ordered by tier first (`URGENT` ahead of `ELEVATED` ahead of `ROUTINE`), then by raw `case_priority_score` descending within a tier, then by `created_at` ascending as the only permitted tie-break.

## 4. Endpoint Definitions

All endpoints follow the response envelope, pagination, and validation-priority contracts of §2. Resource-creating endpoints return HTTP 201 with the created resource; state-transition and other modification endpoints return HTTP 200 with the updated resource; list and get endpoints return HTTP 200. The pattern-scan endpoint returns HTTP 200 with the array of alerts produced (or reused) by the scan; that array is not paginated — its `meta` block reports `limit` and `total_count` equal to the number of alerts returned and `offset` 0.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|---------------------|
| POST | `/api/cases` | Create a case in INTAKE | IntakeCoordinator |
| GET | `/api/cases` | List cases with filters and priority sort option | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/cases/{id}` | Get one case | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/cases/{id}/transition` | Drive the Case state machine | IntakeCoordinator, Investigator, InvestigationsManager |
| POST | `/api/cases/{id}/allegations` | File an allegation against a case | IntakeCoordinator |
| GET | `/api/allegations` | List allegations | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/allegations/{id}` | Get one allegation | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/allegations/{id}/transition` | Allegation state machine | IntakeCoordinator, InvestigationsManager |
| POST | `/api/cases/{id}/plans` | Create a DRAFT investigation plan (OCC) | Investigator |
| GET | `/api/plans` | List plans | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/plans/{id}` | Get one plan | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/plans/{id}/transition` | Plan submit / approve / reject | Investigator, InvestigationsManager |
| POST | `/api/cases/{id}/subjects` | Attach a subject to a case | Investigator |
| GET | `/api/subjects` | List subjects | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/subjects/{id}` | Get one subject | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/subjects/{id}/transition` | Subject CLEARED / SEPARATED | Investigator, InvestigationsManager |
| POST | `/api/cases/{id}/preservation-notices` | Issue a preservation notice | GeneralCounsel |
| GET | `/api/preservation-notices` | List preservation notices | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/preservation-notices/{id}` | Get one preservation notice | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/preservation-notices/{id}/transition` | ACKNOWLEDGED / RELEASED | GeneralCounsel |
| POST | `/api/cases/{id}/collection-scopes` | Propose a collection scope | Investigator |
| GET | `/api/collection-scopes` | List collection scopes | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/collection-scopes/{id}` | Get one collection scope | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/collection-scopes/{id}/transition` | Scope machine (APPROVED / IN_PROGRESS / COLLECTED / WITHDRAWN) | Investigator, InvestigationsManager |
| POST | `/api/collection-scopes/{id}/evidence-items` | Log an evidence item into a scope | Investigator |
| GET | `/api/evidence-items` | List evidence items | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/evidence-items/{id}` | Get one evidence item | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/evidence-items/{id}/transition` | Evidence machine (UNDER_REVIEW / ADMITTED / EXCLUDED / restore) | Investigator |
| POST | `/api/cases/{id}/interviews` | Schedule a witness interview | Investigator |
| GET | `/api/interviews` | List interviews | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/interviews/{id}` | Get one interview | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/interviews/{id}/transition` | Interview machine (Upjohn / complete / no-show / reschedule / cancel) | Investigator |
| POST | `/api/cases/{id}/privilege-designations` | Designate privilege over an artifact | GeneralCounsel |
| GET | `/api/privilege-designations` | List privilege designations | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/privilege-designations/{id}` | Get one privilege designation | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/privilege-designations/{id}/transition` | Designation machine (CONFIRMED / CHALLENGED / reaffirm / WAIVED) | GeneralCounsel, ChiefLegalOfficer |
| POST | `/api/cases/{id}/findings` | Create a DRAFT finding | Investigator |
| GET | `/api/findings` | List findings | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/findings/{id}` | Get one finding | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/findings/{id}/transition` | Finding machine (CALIBRATED / FINAL / CHALLENGED / recalibrate) | HRBusinessPartner, InvestigationsManager, GeneralCounsel |
| POST | `/api/findings/{id}/disciplinary-recommendations` | Propose discipline on a FINAL finding | HRBusinessPartner |
| GET | `/api/disciplinary-recommendations` | List disciplinary recommendations | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/disciplinary-recommendations/{id}` | Get one disciplinary recommendation | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/disciplinary-recommendations/{id}/transition` | Approve / reject a recommendation | InvestigationsManager |
| POST | `/api/cases/{id}/reports` | Create a DRAFT case report (OCC) | Investigator |
| GET | `/api/reports` | List case reports | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/reports/{id}` | Get one case report | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/reports/{id}/transition` | Report machine (LEGAL_REVIEW / DISTRIBUTION_APPROVED / DISTRIBUTED / RECALLED) | Investigator, GeneralCounsel, ChiefLegalOfficer |
| POST | `/api/cases/{id}/self-disclosure-decisions` | Open a PENDING disclosure decision (OCC) | GeneralCounsel |
| GET | `/api/self-disclosure-decisions` | List disclosure decisions | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/self-disclosure-decisions/{id}` | Get one disclosure decision | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/self-disclosure-decisions/{id}/transition` | Disclosure machine (DECIDED / FILED / OVERRIDDEN) | ChiefLegalOfficer, GeneralCounsel |
| POST | `/api/cases/{id}/remediation-actions` | Create an OPEN remediation action | HRBusinessPartner |
| GET | `/api/remediation-actions` | List remediation actions | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/remediation-actions/{id}` | Get one remediation action | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/remediation-actions/{id}/transition` | Remediation machine (IN_PROGRESS / AWAITING_VERIFICATION / VERIFIED / reject / WAIVED) | HRBusinessPartner, ComplianceAuditor, GeneralCounsel |
| POST | `/api/pattern-alerts/scan` | Run cross-case pattern analysis over the rolling window | ComplianceAuditor |
| GET | `/api/pattern-alerts` | List pattern alerts | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| GET | `/api/pattern-alerts/{id}` | Get one pattern alert | IntakeCoordinator, Investigator, InvestigationsManager, HRBusinessPartner, GeneralCounsel, ChiefLegalOfficer, ComplianceAuditor |
| POST | `/api/pattern-alerts/{id}/transition` | Alert machine (ACKNOWLEDGED / ESCALATED / DISMISSED) | InvestigationsManager |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock (test-driving) | SystemAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3 alongside the workflows that produce them. This table is an index of identifiers to HTTP status codes only.

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_MISSING_IDEMPOTENCY_KEY | 400 |
| ERR_IDEMPOTENCY_REPLAY_MISMATCH | 409 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_MISSING_REQUIRED_FIELD | 400 |
| ERR_STALE_VERSION | 412 |
| ERR_INVALID_STATE | 409 |
| ERR_SOD_PLAN_APPROVAL | 403 |
| ERR_SOD_FINDING_FINALIZATION | 403 |
| ERR_SOD_DISCIPLINE_APPROVAL | 403 |
| ERR_SOD_REMEDIATION_VERIFICATION | 403 |
| ERR_SOD_DISCLOSURE_OVERRIDE | 403 |
| ERR_UPJOHN_REQUIRED | 409 |
| ERR_PRIVILEGE_PENDING | 409 |
| ERR_PRIVILEGED_DISTRIBUTION | 403 |
| ERR_COOLING_OFF | 409 |
| ERR_ORDERED_NOTICE_RESTRICTION | 409 |
| ERR_DISCLOSURE_REQUIRED | 409 |
| ERR_DECISION_NOT_DISCLOSE | 409 |
| ERR_PLAN_SUBMITTED_EXISTS | 409 |
| ERR_DUPLICATE_SUBJECT | 409 |
| ERR_DUPLICATE_DESIGNATION | 409 |
| ERR_INTERVIEWER_OVERLAP | 409 |
| ERR_ROOM_OVERLAP | 409 |
| ERR_SCOPE_OVERLAP | 409 |
| ERR_OPEN_RECOMMENDATION_EXISTS | 409 |
| ERR_THRESHOLD_NOT_MET | 409 |
| ERR_EMPTY_COLLECTION | 409 |
| ERR_OPEN_COLLECTION_SCOPES | 409 |
| ERR_PRESERVATION_INCOMPLETE | 409 |
| ERR_FINDINGS_NOT_FINAL | 409 |
| ERR_UNRESOLVED_DISCIPLINE | 409 |
| ERR_OPEN_REMEDIATION | 409 |
| ERR_SUBJECT_HAS_OPEN_FINDINGS | 409 |
| ERR_CUSTODIAN_NOT_PRESERVED | 409 |
| ERR_NOTICE_NOT_ACKNOWLEDGED | 409 |
| ERR_ALLEGATION_NOT_LINKED | 409 |
| ERR_SUBJECT_NOT_IN_CASE | 409 |
| ERR_EVIDENCE_NOT_REVIEWABLE | 409 |
| ERR_TARGET_CASE_MISMATCH | 409 |
| ERR_INTERVIEW_WINDOW_EXPIRED | 409 |
| ERR_NO_SHOW_TOO_EARLY | 409 |
| ERR_SCHEDULE_IN_PAST | 409 |

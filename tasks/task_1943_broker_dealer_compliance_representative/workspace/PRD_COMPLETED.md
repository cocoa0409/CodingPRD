# Broker-Dealer Compliance API — Product Requirements Document

## 1. Introduction

An independent broker-dealer lives under continuous regulatory obligation: every branch office must be inspected on a defined cycle, every piece of registered-representative correspondence must pass supervisory review, outside business activities and private securities transactions must be approved before they begin, customer complaints must be evaluated for reportability, and disclosure events must be filed and acknowledged on statutory timelines. When a representative becomes statutorily disqualified, the firm's obligations expand immediately — heightened supervision plans must be activated, pending activity approvals must be suspended, and the affected branch's inspection posture must tighten. This document specifies the Broker-Dealer Compliance API, the system of record through which a firm administers that entire supervisory program.

The API serves four operator populations. Firm administrators maintain the reference data — branch offices and registered representatives — and drive the logical clock used for deadline evaluation. Compliance analysts perform intake and fieldwork: they schedule inspections, record findings, capture correspondence, receive customer complaints, draft disclosure events, and log regulators' exam requests. Compliance principals hold decision authority: they adjudicate findings, review and resolve correspondence escalations, approve or reject outside activities, resolve and report complaints, file and acknowledge disclosures, supervise heightened plans, run the annual compliance meeting, and publish written supervisory procedures. Registered representatives interact with the system in a narrow, self-service capacity — submitting their own outside-activity requests and attesting to their own annual compliance meeting obligations. The design enforces segregation of duties throughout: the analyst who drafts cannot publish, the principal who escalates cannot resolve, and every decision is stamped with the identity of its maker.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contractual formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five role values, spelled exactly as follows: `FirmAdmin`, `ComplianceAnalyst`, `CompliancePrincipal`, `RegisteredRep`, and `Any`. The `Any` role is an umbrella read role: every authenticated caller, regardless of their specific role, may call the read endpoints. If either header is missing, or the role value is not one of the recognized values, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). If the caller's role is not permitted for the target endpoint — or an entity-backed ownership check fails — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `RegisteredRep`, `X-User-ID` is the `id` of the acting RegisteredRepresentative; ownership checks on any resource that references a RegisteredRepresentative compare the resource's foreign-key field to `X-User-ID`. This binding is what lets a representative submit an outside-activity request without supplying a representative identifier in the payload, withdraw only their own requests, and attest only their own attestations. When `X-User-Role` is `FirmAdmin`, `ComplianceAnalyst`, `CompliancePrincipal`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records these opaque identifiers on the resources the operator touches — for example, as `reviewed_by` on a CorrespondenceItem, `decided_by` on an OutsideActivityRequest, `verified_by` on an InspectionFinding, or `drafted_by` and `published_by` on a WSPDocument — but never compares them to any entity's `id`. The only comparisons performed on opaque identifiers are the segregation-of-duties checks described in §2.6, which compare the caller's identifier against an operator identifier previously recorded on the same resource.

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

Endpoints that return lists of resources are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0. Both parameters must be integers; a non-integer value, an out-of-range `limit`, or a negative `offset` is rejected with `ERR_VALIDATION` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties broken by insertion order so that resources created in the same logical instant preserve their true creation sequence. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in the system — BranchOffice, RegisteredRepresentative, BranchInspection, InspectionFinding, CorrespondenceItem, OutsideActivityRequest, CustomerComplaint, DisclosureEvent, HeightenedSupervisionPlan, ComplianceMeeting, Attestation, WSPDocument, and ExamDocumentRequest — carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; the timestamp is taken from the logical clock at creation time.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource; like `created_at`, it is taken from the logical clock.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by cascade side effects originating from another resource.

Because cascades mutate related resources inside the same request, a single client operation can increment the `version` of several resources at once — for example, acknowledging a statutory-disqualification disclosure can advance the versions of the representative, the branch, and a scheduled inspection in one atomic commit. Clients that hold a resource must therefore treat its `version` as volatile whenever they perform operations elsewhere in the system.

### 2.5. The Logical Clock and Deadline Sweeps

Regulatory deadlines in this system are evaluated against a logical clock, not wall-clock time. A `FirmAdmin` may set the logical clock to an absolute ISO 8601 UTC instant by supplying `to_iso8601` to the clock-setting capability; the response echoes the new value as `current_utc`. The clock is free-setting — it may be moved forward or backward — and before any call has been made, the startup default is exactly 2026-08-01T00:00:00Z. All deadline arithmetic described in this document (review deadlines, filing deadlines, report deadlines, attestation windows, plan windows, inspection due dates) is evaluated against this logical clock.

Every clock set triggers five sweeps, applied atomically with the clock change:

1. Any InspectionFinding in `OPEN` whose `due_date` is earlier than the new clock date transitions to `OVERDUE`.
2. Any CorrespondenceItem in `PENDING_REVIEW` whose `review_deadline` is earlier than the new clock time transitions to `OVERDUE`.
3. Any Attestation in `PENDING` whose `attest_deadline` is earlier than the new clock date transitions to `OVERDUE`.
4. Any ExamDocumentRequest in `OPEN` whose `due_date` is earlier than the new clock date transitions to `OVERDUE`.
5. Any HeightenedSupervisionPlan in `ACTIVE` whose `end_date` is on or before the new clock date transitions to `COMPLETED`.

These sweeps are the only system-initiated state transitions; all other transitions require an explicit operator action. Deadline boundaries are strict in the direction stated: a correspondence item whose `review_deadline` is exactly the current clock time remains `PENDING_REVIEW`, while an attestation may be completed on its `attest_deadline` itself, since attestation is permitted while the current date is on or before the deadline.

### 2.6. Segregation of Duties and the Decision Audit Trail

The firm's supervisory model separates intake from decision. `ComplianceAnalyst` operators capture, draft, schedule, and intake; `CompliancePrincipal` operators decide, file, publish, and close. Two explicit segregation-of-duties rules are enforced against recorded operator identifiers. First, a correspondence escalation may only be resolved by a principal whose `X-User-ID` differs from the identifier recorded in the item's `escalated_by` field; an attempt by the same principal to resolve their own escalation is rejected with `ERR_SOD_ESCALATION_RESOLVER` (HTTP 403). Second, a WSP document may only be published by a principal whose `X-User-ID` differs from the identifier recorded in the document's `drafted_by` field; an attempt by the drafting analyst to publish their own document is rejected with `ERR_SOD_WSP_PUBLISHER` (HTTP 403).

Every decision the system records is attributable. Correspondence items carry `reviewed_by` (the first reviewing principal), `escalated_by` (the escalating principal, null unless the item was escalated), and `resolved_by` (the principal who resolved an escalation, null unless resolved). Outside-activity requests carry `decided_by` once a decision has been made. Findings carry `verified_by` once closure is verified. WSP documents carry `drafted_by` and `published_by`. Disclosure events record `filed_at`, complaints record `reported_at`, exam requests record `fulfilled_at`, meetings record `held_at`, and attestations record `attested_at` — each an immutable stamp of when the act occurred on the logical clock. These fields, once written, are never rewritten by later actions.

### 2.7. Derived Branch Health Indicators and Cascade Recomputation

A branch office's supervisory posture is described by four derived indicators that the server recomputes whenever underlying facts change: `open_findings_count`, `high_severity_open_count`, `risk_score`, and `posture`, together with the derived scheduling field `next_inspection_due_date`. The counts aggregate findings across all of the branch's inspections: a finding counts toward `open_findings_count` while its status is `OPEN`, `OVERDUE`, or `REMEDIATION_SUBMITTED`, and toward `high_severity_open_count` when its severity is `HIGH` and its status is one of those same three. A finding stops counting the moment it is verified closed. The branch also tracks `sd_rep_count`, the number of its representatives who are statutorily disqualified and not terminated.

Recomputation is atomic with the triggering event. Recording a finding, submitting its remediation, adjudicating it, sweeping it to `OVERDUE`, acknowledging a disqualifying disclosure, or closing an inspection each recompute the affected indicators inside the same request, and each such recomputation that mutates the BranchOffice refreshes its `updated_at` and increments its `version` as described in §2.4. The same hierarchical-consistency principle applies one level down: each BranchInspection maintains its own `open_findings_count` and `high_severity_open_count` over its findings, and those counts move in lockstep with the finding transitions described in §3.2. The specific formulas behind `risk_score`, `posture`, and `next_inspection_due_date` are given in §3.1 and §3.2 alongside the workflows that trigger them.

### 2.8. Monetary Precision and Score Arithmetic

All monetary amounts in this API are integer numbers of cents. Fields such as `damages_claimed_cents`, `damages_paid_cents`, `legal_cost_cents`, `estimated_gross_comp_cents`, `supervisory_fee_cents`, `provisional_reserve_cents`, and `final_reserve_cents` are whole-cent integers; any multiplication that produces a fractional cent is rounded to the nearest whole cent using round-half-up. Where a total is built from per-item amounts — the PST supervisory fee accrual of §3.4 is the canonical case — each item's amount is rounded to whole cents first and the rounded amounts are then summed; summing unrounded amounts and rounding once at the end is not permitted, because the two orders can differ by a cent.

Risk scores, by contrast, are integer point values that involve no rounding at all: the correspondence provisional risk score and the branch risk score are sums of integer weights, optionally clamped to integer ceilings and floors as their respective formulas specify. Calendar arithmetic (deadlines, due dates, cycle lengths) is performed as exact date or timestamp arithmetic in UTC; date-plus-days and date-plus-months operations mean calendar arithmetic, not fixed-second offsets.

### 2.9. Optimistic Concurrency Control

Two write operations and one conditional-close operation are guarded by optimistic concurrency control against the parent entity whose fields they depend on. Creating a heightened supervision plan accepts `expected_representative_version`, holding the `version` of the target RegisteredRepresentative as the client last observed it. When the field is supplied as an integer and the representative's current `version` no longer matches — because, for instance, an activity decision or a disqualification cascade has advanced it — the create is rejected with `ERR_STALE_REPRESENTATIVE_VERSION` (HTTP 412). Scheduling a branch inspection accepts `expected_branch_version`, holding the `version` of the target BranchOffice as the client last observed it; a supplied integer that mismatches the branch's current `version` is rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412), so that scheduling decisions are never made on stale cycle math, posture, or due-date state. The same `expected_branch_version` field is honored when closing an inspection, since closing recomputes branch-level fields; a supplied stale value is likewise rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412). On all three guarded endpoints the field is optional: when it is omitted or null, no OCC check runs and the operation proceeds. Endpoints not named here do not take a version field. The OCC check, when it runs, runs after authentication, authorization, and existence checks, but before every business rule on the guarded endpoint.

### 2.10. Validation Order and Error Precedence

When a request fails more than one rule, the error that surfaces is determined by a fixed evaluation order:

1. **User context.** The `X-User-ID` and `X-User-Role` headers must be present and the role recognized; otherwise `ERR_MISSING_USER_CONTEXT` (HTTP 400).
2. **Role membership and ownership.** The caller's role must be authorized for the endpoint, and where entity-backed ownership is declared — outside-activity creation and withdrawal, and attestation — the caller's `X-User-ID` must bind to the referenced representative resource; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). (Attestation ownership failure carries its own code, `ERR_NOT_ATTESTATION_OWNER`, also HTTP 403.)
3. **Existence.** Every identifier in the path and every foreign-key reference in the body (`branch_id`, `rep_id`, `inspection_id`, `meeting_id`, and the like) must resolve to an existing resource. Identifiers are validated left to right, and the first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404).
4. **Optimistic concurrency.** On the guarded endpoints of §2.9, when `expected_representative_version` or `expected_branch_version` is supplied as an integer, the value must equal the parent entity's current `version`; a mismatch yields its 412 error before any business check runs. When the field is omitted or null, no OCC check runs.
5. **State preconditions.** The target resource must be in a state from which the requested transition exists; violations carry the per-resource 409 codes (`ERR_INSPECTION_INVALID_STATE`, `ERR_FINDING_INVALID_STATE`, `ERR_CORRESPONDENCE_INVALID_STATE`, `ERR_ACTIVITY_NOT_PENDING_DECISION`, `ERR_COMPLAINT_NOT_RESOLVABLE`, `ERR_REPORT_NOT_REQUIRED`, `ERR_DISCLOSURE_INVALID_STATE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_MEETING_NOT_HELD`, `ERR_ATTESTATION_NOT_PENDING`, `ERR_WSP_NOT_DRAFT`, `ERR_EXAM_REQUEST_INVALID_STATE`, or the generic `ERR_INVALID_STATE`).
6. **Regulatory gates and segregation of duties.** The supervisory gates — heightened-plan prerequisites, active-representative prerequisites, and the two segregation-of-duties rules of §2.6 — are evaluated next, each surfacing its specific code (for instance `ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN`, `ERR_REP_NOT_ACTIVE`, `ERR_SOD_ESCALATION_RESOLVER`, `ERR_SOD_WSP_PUBLISHER`, `ERR_NOT_ATTESTATION_OWNER`).
7. **Temporal rules.** Date-versus-clock rules surface as 422 errors: `ERR_PLAN_START_IN_PAST`, `ERR_MEETING_DATE_NOT_REACHED`, `ERR_ATTESTATION_DEADLINE_PASSED`.
8. **Business constraints.** Uniqueness, overlap, gap, and threshold rules surface their specific codes (`ERR_PLAN_WINDOW_OVERLAP`, `ERR_PLAN_ALREADY_ACTIVE`, `ERR_DUPLICATE_MEETING_YEAR`, `ERR_PST_COMP_DETAILS_REQUIRED`, `ERR_INSPECTION_GAP_VIOLATION`, `ERR_INSPECTION_ALREADY_OPEN`, `ERR_MEETING_NOT_HELD`).
9. **Schema validation.** Only after all domain rules pass are field-level checks applied: required fields present, enum membership exact, and monetary or count fields non-negative integers (`damages_claimed_cents`, `damages_paid_cents`, `legal_cost_cents`, `estimated_gross_comp_cents`, `lexicon_hits`). Violations are reported as `ERR_VALIDATION` (HTTP 400). A request that violates both a domain rule and a schema rule therefore reports the domain rule's specific error, never `ERR_VALIDATION`.

## 3. Business Logic & Workflows

### 3.1. Branch Offices, Registered Representatives, and the Inspection Cycle

A `FirmAdmin` opens the firm's book by creating branch offices, supplying a `name`, a `region` code, and optionally an `inspection_cycle_months` value that defaults to 12 when omitted and, when supplied, must be a positive integer (a non-positive value is rejected with `ERR_VALIDATION`, HTTP 400). A new branch starts with `posture` of `NORMAL`, all derived counts at zero, and a `risk_score` of zero; its `next_inspection_due_date` is initialized to the branch's creation date plus the inspection cycle. The branch listing can be filtered by `region`, alongside the standard `limit` and `offset` parameters, and a single branch read exposes all of the computed posture, risk, and due-date fields.

Representatives are registered against a branch by a `FirmAdmin` supplying `crd_number` (unique across the firm; a duplicate submission is rejected with `ERR_VALIDATION`, HTTP 400), `full_name`, the `branch_id` of the assigned branch, and `hire_date`. A new representative starts with `status` of `ACTIVE`, `supervision_tier` of `STANDARD`, `is_statutorily_disqualified` false, and zeroed counters: `compliance_flag_count`, `active_approved_activity_count`, and `pst_fee_total_cents`. The representative listing supports filters on `branch_id`, `status`, and `supervision_tier`.

Termination is a principal-only act with compensating cascades. A `CompliancePrincipal` may terminate a representative whose `status` is `ACTIVE`; invoking termination on a representative in any other state — including an already `TERMINATED` one — is rejected with `ERR_INVALID_STATE` (HTTP 409). On termination, every OutsideActivityRequest of the representative that sits in `SUBMITTED` or `SUSPENDED_REVIEW` is moved to `WITHDRAWN` (no count or fee adjustments apply, because none of those requests had been approved), every HeightenedSupervisionPlan of the representative in `ACTIVE` is moved to `TERMINATED` with `terminated_reason` set to `REP_TERMINATED`, and the branch's `sd_rep_count` is recomputed — decrementing if the terminated representative had been SD-flagged. The representative's own `is_statutorily_disqualified` and `supervision_tier` are deliberately left unchanged as historical fact, and the representative's `version` increments by one.

The inspection cycle is governed by the branch's derived `next_inspection_due_date`. Its base date is the `completed_date` of the branch's most recently closed inspection — ties broken by earliest inspection creation — or, when the branch has never had a closed inspection, the branch's creation date. The cycle length is 6 months whenever the branch's `sd_rep_count` is at least one, and the branch's `inspection_cycle_months` otherwise. Cycle acceleration is sticky: once `inspection_cycle_months` has been reduced to 6 by the disqualification cascade of §3.6, it never reverts automatically, even if the branch's `sd_rep_count` later falls back to zero. The due date itself is the base date plus the applicable number of months.

### 3.2. Inspection Fieldwork: Findings, Remediation, and Branch Risk

A `ComplianceAnalyst` schedules a branch inspection by supplying the `branch_id`, a `scheduled_date`, and the `expected_branch_version` guard of §2.9. Two scheduling constraints protect the cycle's integrity, and both yield 409 conflicts. First, the `scheduled_date` must fall at least 300 days after the `completed_date` of the branch's last `CLOSED` inspection; a shorter gap is rejected with `ERR_INSPECTION_GAP_VIOLATION`. Second, a branch may have at most one inspection that is not yet `CLOSED` — that is, at most one inspection in `SCHEDULED`, `IN_PROGRESS`, or `AWAITING_REMEDIATION`; attempting to schedule a second is rejected with `ERR_INSPECTION_ALREADY_OPEN`. A successful scheduling increments the branch's `version` by one. Inspection listings can be filtered by `branch_id` and `status`.

Fieldwork begins when an analyst starts a `SCHEDULED` inspection, moving it to `IN_PROGRESS` and stamping `started_at` with the current logical clock; starting from any other state is rejected with `ERR_INSPECTION_INVALID_STATE`. While the inspection is `IN_PROGRESS`, analysts record findings against it, each carrying the parent `inspection_id`, a `severity` of `LOW`, `MEDIUM`, or `HIGH`, a free-text `description`, and a remediation `due_date`. Recording a finding increments the inspection's `open_findings_count` — and `high_severity_open_count` when the severity is `HIGH` — and immediately recomputes the branch's counts, `risk_score`, and `posture`. Findings can be listed with filters on `inspection_id`, `severity`, and `status`.

The branch `risk_score` weighs only findings in the scored statuses `OPEN` and `OVERDUE`: fifteen points for each scored `HIGH` finding, five for each scored `MEDIUM`, and two for each scored `LOW`, plus a flat twenty points whenever the branch's `sd_rep_count` is at least one, with the total capped at 100. Because `REMEDIATION_SUBMITTED` and `VERIFIED_CLOSED` findings are excluded from the scored set, the score responds to remediation and adjudication without further input. The score is recomputed whenever a finding of the branch is created, remediated, adjudicated, or swept to `OVERDUE`.

Posture escalation is threshold-driven. When any single inspection of the branch accumulates two or more `HIGH` findings in the counting statuses — a count of exactly one does not trigger — the branch's `posture` becomes `REMEDIATION_REQUIRED`, and its `next_inspection_due_date` is pulled in to the earlier of its current value and the current clock date plus 90 days. This pull-in applies only on the upward transition into `REMEDIATION_REQUIRED`; when the count later subsides, the posture returns to `NORMAL` without restoring the original due date.

Remediation is an analyst act with an unlimited revision loop. An analyst may submit remediation on a finding in `OPEN` or `OVERDUE`, moving it to `REMEDIATION_SUBMITTED` and recording the payload's `remediation_note`; invoking remediation from any other state is rejected with `ERR_FINDING_INVALID_STATE`. The finding leaves the scored set, so the branch `risk_score` is recomputed. A principal then adjudicates a `REMEDIATION_SUBMITTED` finding with a `decision` of `VERIFY` or `REOPEN`; adjudicating from any other state is likewise `ERR_FINDING_INVALID_STATE`. Verification moves the finding to `VERIFIED_CLOSED`, stamps `verified_by` with the principal's identifier, and decrements the inspection's `open_findings_count` by one. Reopening returns the finding to `OPEN`, increments its `reopen_count` by one, records the payload's `rejection_reason` in `adjudication_note`, and recomputes the branch score as the finding re-enters the scored set — the exact compensation of the remediation transition. Both adjudication outcomes recompute the branch's counts, posture, and risk.

Closing is a conditional principal action that forks on the inspection's aggregate child state, and the close request carries the `expected_branch_version` guard. From `IN_PROGRESS`, the close moves the inspection directly to `CLOSED` when the inspection's `open_findings_count` is zero — a zero-finding close — and to `AWAITING_REMEDIATION` when open findings remain, marking the end of fieldwork and the start of the remediation period. From `AWAITING_REMEDIATION`, the close succeeds only when every finding of the inspection has reached `VERIFIED_CLOSED`; if any finding remains non-terminal, the close is rejected with `ERR_FINDINGS_STILL_OPEN`, and a close attempted from a state the transition does not allow — including a terminal `CLOSED` — is rejected with `ERR_INSPECTION_INVALID_STATE`. Reaching `CLOSED` stamps `completed_date` with the current clock date and triggers the full branch recomputation: counts, posture, `risk_score`, and a fresh `next_inspection_due_date` computed as the completion date plus the applicable cycle, with the branch's `version` incremented by one.

### 3.3. Correspondence Surveillance and Escalation

Every piece of representative correspondence enters the supervisory queue through analyst capture. A `ComplianceAnalyst` captures an item by supplying the authoring `rep_id`, a `channel` of `EMAIL`, `SMS`, `SOCIAL_MEDIA`, or `PAPER_LETTER`, a `subject`, an optional `body_excerpt` (defaulting to empty), and `lexicon_hits`, the non-negative count of surveillance-lexicon matches. Capture stamps `captured_at` from the logical clock, sets the `review_deadline` to exactly 30 days after `captured_at`, computes the `provisional_risk_score`, and places the item in `PENDING_REVIEW`. The correspondence listing supports `rep_id` and `status` filters.

The provisional risk score is a weighted sum in integer points, capped at 100: ten points per lexicon hit, plus a channel weight — 5 for `EMAIL`, 10 for `PAPER_LETTER`, 20 for `SMS`, and 25 for `SOCIAL_MEDIA` — plus 30 additional points when the authoring representative's current `supervision_tier` is `HEIGHTENED`, and zero when it is `STANDARD`. The score is computed once, at capture, from the representative's tier at that moment.

Principal review proceeds by decision. Reviewing an item in `PENDING_REVIEW` or `OVERDUE` — review from any other state is rejected with `ERR_CORRESPONDENCE_INVALID_STATE` — takes a `decision` of `APPROVE`, `FLAG`, or `ESCALATE`, with an optional `note`. An `APPROVE` decision moves the item to `APPROVED`, stamps `reviewed_by`, and sets `final_risk_score` equal to the provisional score unchanged. A `FLAG` decision moves the item to `FLAGGED`, stamps `reviewed_by`, sets `final_risk_score` to the greater of the provisional score and 70 — so a provisional 20 flags at 70 — and increments the representative's `compliance_flag_count` by one. An `ESCALATE` decision moves the item to `ESCALATED` and stamps `escalated_by`, leaving the final score unwritten.

An escalated item is resolved through a second, segregated decision carrying a `decision` of `APPROVE` or `FLAG` and an optional `note`; resolving from any state other than `ESCALATED` is `ERR_CORRESPONDENCE_INVALID_STATE`. The resolving principal must differ from the principal recorded in `escalated_by`, per §2.6 — the same principal resolving their own escalation is rejected with `ERR_SOD_ESCALATION_RESOLVER`. A resolving `APPROVE` moves the item to `APPROVED`, stamps `resolved_by`, and sets `final_risk_score` to the lesser of the provisional score and 30 — so a provisional 80 resolves down to 30. A resolving `FLAG` moves the item to `FLAGGED`, stamps `resolved_by`, sets `final_risk_score` to the greater of the provisional score and 70, and increments the representative's `compliance_flag_count`. `APPROVED` and `FLAGGED` are terminal; an item left unreviewed past its `review_deadline` is swept to `OVERDUE` per §2.5 but remains reviewable.

### 3.4. Outside Business Activities and Private Securities Transactions

A registered representative requests approval for outside work by submitting a request carrying an `activity_type` of `OUTSIDE_BUSINESS_ACTIVITY` or `PRIVATE_SECURITIES_TRANSACTION`, a free-text `description`, a `compensation_expected` flag, an optional `estimated_gross_comp_cents`, and a planned `start_date`. The request's `rep_id` is never a payload field: it is bound at creation to the caller's `X-User-ID` under the entity-backed identity rule of §2.1. If the caller's `X-User-ID` does not resolve to an existing RegisteredRepresentative, the submission is rejected with `ERR_NOT_FOUND` (HTTP 404). Submission requires the representative to be `ACTIVE`; a request by or for a `TERMINATED` representative is rejected with `ERR_REP_NOT_ACTIVE` (HTTP 409). New requests start in `SUBMITTED`, and the activity listing supports `rep_id`, `activity_type`, and `status` filters.

Decisions belong to the principal and are evaluated in a fixed gate order. For an `APPROVE` decision: the activity must be in `SUBMITTED` — deciding in any other state is rejected with `ERR_ACTIVITY_NOT_PENDING_DECISION`; the representative must still be `ACTIVE`, else `ERR_REP_NOT_ACTIVE`; if the representative is statutorily disqualified, they must have a heightened supervision plan in `ACTIVE`, else `ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN` (HTTP 403); and if the request is a compensated private securities transaction — `activity_type` of `PRIVATE_SECURITIES_TRANSACTION` with `compensation_expected` true — then `estimated_gross_comp_cents` must be present and greater than zero, else `ERR_PST_COMP_DETAILS_REQUIRED` (HTTP 422). An approval stamps `decided_by`, increments the representative's `active_approved_activity_count` by one, and increments the representative's `version` by one. An `APPROVE_WITH_CONDITIONS` decision applies the same gates and side effects, additionally requiring the payload's `conditions` to be a non-empty array, which is then recorded on the request; the resulting status is `APPROVED_WITH_CONDITIONS`. On requests decided any other way, `conditions` remains null. A `REJECT` decision requires only the `SUBMITTED` state, stamps `decided_by`, and moves the request to `REJECTED`.

Approval of a compensated private securities transaction accrues a supervisory fee. The per-approval fee is the estimated gross compensation multiplied by 2.5 percent, rounded half-up to whole cents and recorded on the request as `supervisory_fee_cents`; the same rounded amount is added to the representative's running `pst_fee_total_cents`. The rounding order is pinned: each approval's fee is rounded to whole cents before any summation, and the representative's total is the sum of those per-approval rounded fees — summing gross amounts and rounding once at the end is forbidden, because the orders genuinely differ (two transactions of 33333 cents each yield 833 plus 833, totaling 1666 cents, versus 1667 under sum-then-round). A request that was not an approved compensated PST carries a null `supervisory_fee_cents`.

Withdrawal and revocation are compensating acts. The owning representative — identified by the `X-User-ID` matching the request's `rep_id`, with a mismatch rejected as `ERR_FORBIDDEN_ROLE` — may withdraw a request in `SUBMITTED`, `SUSPENDED_REVIEW`, `APPROVED`, or `APPROVED_WITH_CONDITIONS`; withdrawing from any other state is `ERR_ACTIVITY_NOT_PENDING_DECISION`. When the withdrawn request had been approved, the representative's `active_approved_activity_count` decrements by one and the request's `supervisory_fee_cents` is subtracted from `pst_fee_total_cents` (null-safe); withdrawals from `SUBMITTED` or `SUSPENDED_REVIEW` adjust nothing. A principal may likewise revoke an approved request — one in `APPROVED` or `APPROVED_WITH_CONDITIONS`, else `ERR_ACTIVITY_NOT_PENDING_DECISION` — supplying a `reason`; revocation performs the same compensating reversal of count and fee, moving the request to `REVOKED`. The conservation invariant follows directly: an approval's increment paired with its own withdrawal or revocation nets to zero on both the count and the fee total.

The disqualification cascade of §3.6 suspends pending requests: every request of the affected representative in `SUBMITTED` moves to `SUSPENDED_REVIEW`. A principal may later resume such a request, returning it from `SUSPENDED_REVIEW` to `SUBMITTED`, but only while the representative has a heightened supervision plan in `ACTIVE` — resuming without one is rejected with `ERR_NO_ACTIVE_HEIGHTENED_PLAN`, and resuming from any state other than `SUSPENDED_REVIEW` is `ERR_ACTIVITY_NOT_PENDING_DECISION`. The suspension loop between `SUBMITTED` and `SUSPENDED_REVIEW` is cyclic, guarded entirely by plan state.

### 3.5. Customer Complaints and Regulatory Reporting

Complaint intake is an analyst function. A `ComplianceAnalyst` intakes a complaint with the subject `rep_id`, an `allegation_type` of `FORGERY`, `THEFT`, `MISREPRESENTATION`, `SUITABILITY`, `UNAUTHORIZED_TRADING`, or `OTHER`, the `damages_claimed_cents` as a non-negative integer of cents, the `received_date`, and an optional `description` defaulting to empty. Intake computes three derived fields immediately. The `reportable` flag is true when claimed damages are at least 500000 cents (five thousand dollars) — exactly 500000 is reportable, 499999 is not — or when the allegation is `FORGERY` or `THEFT`, regardless of amount. The `report_deadline` is the `received_date` plus 30 days. The `provisional_reserve_cents` is the claimed amount multiplied by an allegation rate — one hundred percent for `FORGERY` and `THEFT`, sixty percent for `MISREPRESENTATION`, fifty percent for `UNAUTHORIZED_TRADING`, forty percent for `SUITABILITY`, and twenty-five percent for `OTHER` — rounded half-up to whole cents. The complaint's `status` begins as `RECEIVED`, and its `regulatory_status` — a parallel dimension independent of `status` — initializes to `REQUIRED` when the complaint is reportable and `NOT_REQUIRED` otherwise. The complaint listing supports `rep_id`, `status`, and `regulatory_status` filters.

While a complaint remains `RECEIVED`, an analyst may amend its `damages_claimed_cents`. Amendment recomputes reportability and the provisional reserve, and flips `regulatory_status` in whichever direction the threshold was crossed — a downward amendment that drops claimed damages below the threshold on a non-forgery allegation moves `regulatory_status` from `REQUIRED` back to `NOT_REQUIRED`, and an upward crossing moves it from `NOT_REQUIRED` to `REQUIRED`. Because `FILED` is terminal for the regulatory axis, an amendment on a complaint whose `regulatory_status` is already `FILED` leaves that status untouched even when the recomputed reportability would otherwise flip it. Amending a complaint no longer in `RECEIVED` is rejected with `ERR_COMPLAINT_NOT_RESOLVABLE`.

Resolution is a principal act requiring the complaint to be in `RECEIVED`, again with `ERR_COMPLAINT_NOT_RESOLVABLE` on any other state. The principal supplies `damages_paid_cents` and `legal_cost_cents`, and the system computes the `final_reserve_cents` as the lesser of two figures: the sum of damages paid and legal costs, or one hundred twenty-five percent of the claimed damages rounded half-up to whole cents. The two reserve variants can differ substantially on identical inputs — a suitability claim of 2000000 cents provisions at 800000 under the rate-keyed variant but finalizes at no more than 1500000 when the actual outlay is lower than the cap. Resolution moves `status` to `RESOLVED`, which is terminal for the complaint axis.

A significant payment triggers a disclosure cascade: when `damages_paid_cents` is at least 150000 cents — exactly 150000 triggers — resolution automatically creates a DisclosureEvent in `DRAFT` with `event_type` of `CUSTOMER_AWARD`, `event_date` set to the current clock date, `rep_id` taken from the resolved complaint, and `source_complaint_id` recording the complaint's `id`. The auto-created event then follows the ordinary disclosure lifecycle of §3.6.

Regulatory reporting rides the parallel axis. A principal files the regulatory report for a complaint only while its `regulatory_status` is `REQUIRED`; filing from any other regulatory state is rejected with `ERR_REPORT_NOT_REQUIRED`. Filing stamps `reported_at` with the current clock date, sets `is_late_report` to true when the filing date falls after the `report_deadline`, and moves `regulatory_status` to `FILED`, which is terminal for the regulatory axis. The two axes never interact: a complaint may be resolved before or after its report is filed, and resolution neither requires nor performs a filing.

### 3.6. Disclosure Events and the Statutory-Disqualification Cascade

Analysts draft disclosure events against a representative, supplying the `rep_id`, an `event_type` of `FELONY_CONVICTION`, `SECURITIES_MISDEMEANOR`, `REGULATORY_BAR`, `CUSTOMER_AWARD`, `CIVIL_JUDGMENT`, or `BANKRUPTCY`, the `event_date` of the underlying event, and an optional `description` defaulting to empty. Drafting computes two derived fields: `is_sd_trigger`, which is true exactly when the event type is `FELONY_CONVICTION`, `SECURITIES_MISDEMEANOR`, or `REGULATORY_BAR`, and `filing_deadline`, which is the `event_date` plus 30 days. The new event starts in `DRAFT`. Disclosure listings filter by `rep_id`, `event_type`, and `status`.

A principal files a `DRAFT` event — filing from any other state is rejected with `ERR_DISCLOSURE_INVALID_STATE` — stamping `filed_at` from the logical clock and computing `is_late`, true when the calendar date of `filed_at` falls after the `filing_deadline`. The event moves to `FILED`. Acknowledgement, also principal-only and also guarded by `ERR_DISCLOSURE_INVALID_STATE` from non-`FILED` states, moves the event to `ACKNOWLEDGED` and — only when the event is an SD trigger — fires a three-link cascade plus a fan-out, all in one atomic commit.

The cascade's first link acts on the representative: `is_statutorily_disqualified` becomes true (and never auto-reverts), `supervision_tier` becomes `HEIGHTENED`, and the representative's `version` increments by one. The fan-out acts on the representative's pending outside activities: every request in `SUBMITTED` moves to `SUSPENDED_REVIEW`, per §3.4. The second link acts on the branch: `sd_rep_count` is recomputed, and when the count is at least one the branch's inspection cycle accelerates — `inspection_cycle_months` is reduced to the lesser of its current value and 6, `next_inspection_due_date` is recomputed on the shortened cycle per §3.1, and the branch's `version` increments by one. The third link acts on scheduling: if the branch has an inspection in `SCHEDULED` whose `scheduled_date` falls after the freshly computed `next_inspection_due_date`, that inspection's `scheduled_date` is pulled forward to the due date, and the inspection's `version` increments by one. A non-trigger event — a `CUSTOMER_AWARD`, `CIVIL_JUDGMENT`, or `BANKRUPTCY` — acknowledges quietly with none of these effects.

### 3.7. Heightened Supervision Plans

Heightened supervision plans define the supervised window for a disqualified representative. A `CompliancePrincipal` creates a plan by supplying the `rep_id`, a `start_date`, an `end_date`, a non-empty `conditions` array of supervision condition strings, and the `expected_representative_version` guard of §2.9. The plan window is half-open: it covers dates from `start_date` inclusive up to but not including `end_date`. Two plans of the same representative in `DRAFT` or `ACTIVE` must not overlap; because the window is half-open, one plan's `end_date` may coincide with another's `start_date` without conflict, but any true overlap is rejected with `ERR_PLAN_WINDOW_OVERLAP`. The `start_date` must not lie in the past — a start date earlier than the current clock date is rejected with `ERR_PLAN_START_IN_PAST` (HTTP 422). Creation places the plan in `DRAFT` and increments the representative's `version` by one; plan listings filter by `rep_id` and `status`.

Activation enforces three gates in sequence: the plan must be in `DRAFT` — activating or terminating from a non-matching state is rejected with `ERR_PLAN_NOT_ACTIVE`; the representative must carry the statutory-disqualification flag, else `ERR_REP_NOT_STATUTORILY_DISQUALIFIED`; and no other plan of the same representative may already be `ACTIVE`, else `ERR_PLAN_ALREADY_ACTIVE`. An activated plan is the key that unlocks the gates of §3.4: approval decisions for a disqualified representative, and resumption of suspended requests, both consult it.

A principal may terminate an `ACTIVE` plan manually, moving it to `TERMINATED` with `terminated_reason` set to `MANUAL`. Two system-driven endings exist alongside the manual one: representative termination cascades any `ACTIVE` plan to `TERMINATED` with `terminated_reason` of `REP_TERMINATED`, and the clock sweep moves an `ACTIVE` plan whose `end_date` has been reached to `COMPLETED`. `TERMINATED` and `COMPLETED` are both terminal.

### 3.8. The Annual Compliance Meeting and Attestations

Once per calendar year the firm holds its compliance meeting. A `CompliancePrincipal` schedules it by supplying the `year` and the planned `meeting_date`; only one meeting may exist per calendar year, and a duplicate year is rejected with `ERR_DUPLICATE_MEETING_YEAR`. Scheduling fans out the attestation obligation: for every representative whose `status` is `ACTIVE` at creation time — visited in creation order, earliest first — the system creates an Attestation in `PENDING`, binding the `meeting_id` and `rep_id` and setting the `attest_deadline` to the `meeting_date` plus 30 days. Terminated representatives receive no attestation. The meeting starts in `SCHEDULED`; meeting listings filter by `year` and `status`, and attestation listings support both `meeting_id` and `rep_id` filters alongside `status`.

Holding the meeting requires two conditions: the meeting must be `SCHEDULED` — holding or closing from a non-matching state is rejected with `ERR_MEETING_NOT_HELD` — and the current clock date must be on or after the `meeting_date`, else `ERR_MEETING_DATE_NOT_REACHED` (HTTP 422). Holding stamps `held_at` from the clock and moves the meeting to `HELD`.

Attestation is the representative's own act, bound by the entity-backed identity rule. The caller's `X-User-ID` must equal the attestation's `rep_id`, else `ERR_NOT_ATTESTATION_OWNER` (HTTP 403); the attestation must be `PENDING`, else `ERR_ATTESTATION_NOT_PENDING`; the current clock date must be on or before the `attest_deadline` — the deadline day itself is still attestable — else `ERR_ATTESTATION_DEADLINE_PASSED` (HTTP 422); and the parent meeting must be in `HELD`, else `ERR_MEETING_NOT_HELD`. A successful attestation stamps `attested_at` and moves the attestation to `ATTESTED`. An attestation left `PENDING` past its deadline is swept to `OVERDUE` per §2.5. Closing the meeting requires every one of its attestations to have reached a terminal state — `ATTESTED` or `OVERDUE`; closing while any attestation remains `PENDING` is rejected with `ERR_ATTESTATIONS_STILL_PENDING`. A meeting with all attestations resolved moves to `CLOSED`.

### 3.9. Written Supervisory Procedures and Examination Readiness

The firm's written supervisory procedures live as versioned documents, one thread per policy area. A `ComplianceAnalyst` drafts a WSP document by supplying a `policy_area` of `CORRESPONDENCE`, `OBA_PST`, `COMPLAINTS`, `DISCLOSURE`, `HEIGHTENED_SUPERVISION`, `INSPECTIONS`, or `BOOKS_RECORDS`, plus a `title` and an `effective_date`. Drafting stamps `drafted_by` with the analyst's identifier and assigns `version_number` as one greater than the highest existing `version_number` within the same policy area — or 1 when the area has no documents yet. The document starts in `DRAFT`; the document listing filters by `policy_area`, `status`, and `supersedes_id`.

Publication is the principal's act, segregated from drafting per §2.6: the document must be in `DRAFT`, else `ERR_WSP_NOT_DRAFT`, and the publishing principal's identifier must differ from `drafted_by`, else `ERR_SOD_WSP_PUBLISHER`. Publishing stamps `published_by` and enforces the singleton invariant — at most one document per policy area may be `PUBLISHED` at any time. In the same atomic request, the policy area's currently published document, if one exists, moves to `SUPERSEDED`, and the newly published document's `supersedes_id` is set to that document's `id`; when the area has never had a published document, `supersedes_id` remains null. Publication and supersession are inseparable: exactly one `PUBLISHED` document per policy area exists whenever any document of that area has ever been published.

Examination readiness is tracked through document production requests. A `ComplianceAnalyst` logs a regulator's request with the `regulator` — `SEC`, `FINRA`, or `STATE` — the regulator's `request_ref`, the `document_type` sought (`TRADE_BLOTTER`, `CORRESPONDENCE_LOG`, `COMPLAINT_FILE`, `WSP_COPY`, or `OBA_REGISTER`), an optional `branch_id` scope defaulting to null, and the production `due_date`. The request opens in `OPEN`; exam request listings filter by `branch_id` and `status`. Fulfillment, also an analyst act, is permitted from `OPEN` or `OVERDUE` — fulfilling an already `FULFILLED` request is rejected with `ERR_EXAM_REQUEST_INVALID_STATE` — and records the `produced_document_ref`, stamps `fulfilled_at` from the logical clock, and computes `is_late`, true when the calendar date of `fulfilled_at` falls after the `due_date`. A request left `OPEN` past its `due_date` is swept to `OVERDUE` per §2.5 and remains fulfillable.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions, the complaint amendment, and the clock set — return `200 OK`, as do all list and single-resource reads. Error responses use the envelope of §2.2 with the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock and run deadline sweeps | FirmAdmin |
| POST | `/branches` | Create a branch office | FirmAdmin |
| GET | `/branches` | List branch offices | Any |
| GET | `/branches/{id}` | Get one branch office | Any |
| POST | `/representatives` | Register a representative | FirmAdmin |
| GET | `/representatives` | List representatives | Any |
| GET | `/representatives/{id}` | Get one representative | Any |
| POST | `/representatives/{id}/terminate` | Terminate a representative | CompliancePrincipal |
| POST | `/inspections` | Schedule a branch inspection | ComplianceAnalyst |
| GET | `/inspections` | List inspections | Any |
| GET | `/inspections/{id}` | Get one inspection | Any |
| POST | `/inspections/{id}/start` | Begin inspection fieldwork | ComplianceAnalyst |
| POST | `/inspections/{id}/close` | Conditionally close an inspection | CompliancePrincipal |
| POST | `/findings` | Record a finding on an in-progress inspection | ComplianceAnalyst |
| GET | `/findings` | List findings | Any |
| GET | `/findings/{id}` | Get one finding | Any |
| POST | `/findings/{id}/remediate` | Submit remediation for a finding | ComplianceAnalyst |
| POST | `/findings/{id}/adjudicate` | Verify or reopen a remediated finding | CompliancePrincipal |
| POST | `/correspondence-items` | Capture a correspondence item | ComplianceAnalyst |
| GET | `/correspondence-items` | List correspondence items | Any |
| GET | `/correspondence-items/{id}` | Get one correspondence item | Any |
| POST | `/correspondence-items/{id}/review` | Review decision: approve, flag, or escalate | CompliancePrincipal |
| POST | `/correspondence-items/{id}/resolve-escalation` | Resolve an escalated item (segregated) | CompliancePrincipal |
| POST | `/outside-activities` | Submit an outside activity or PST request | RegisteredRep |
| GET | `/outside-activities` | List outside activity requests | Any |
| GET | `/outside-activities/{id}` | Get one outside activity request | Any |
| POST | `/outside-activities/{id}/decide` | Decide a pending request | CompliancePrincipal |
| POST | `/outside-activities/{id}/withdraw` | Withdraw own request | RegisteredRep |
| POST | `/outside-activities/{id}/revoke` | Revoke an approved request | CompliancePrincipal |
| POST | `/outside-activities/{id}/resume` | Resume a suspended request | CompliancePrincipal |
| POST | `/complaints` | Intake a customer complaint | ComplianceAnalyst |
| GET | `/complaints` | List complaints | Any |
| GET | `/complaints/{id}` | Get one complaint | Any |
| PATCH | `/complaints/{id}` | Amend claimed damages while received | ComplianceAnalyst |
| POST | `/complaints/{id}/resolve` | Resolve a complaint with payment figures | CompliancePrincipal |
| POST | `/complaints/{id}/report` | File the regulatory report | CompliancePrincipal |
| POST | `/disclosure-events` | Draft a disclosure event | ComplianceAnalyst |
| GET | `/disclosure-events` | List disclosure events | Any |
| GET | `/disclosure-events/{id}` | Get one disclosure event | Any |
| POST | `/disclosure-events/{id}/file` | File a disclosure event | CompliancePrincipal |
| POST | `/disclosure-events/{id}/acknowledge` | Acknowledge a filed disclosure event | CompliancePrincipal |
| POST | `/supervision-plans` | Create a heightened supervision plan | CompliancePrincipal |
| GET | `/supervision-plans` | List supervision plans | Any |
| GET | `/supervision-plans/{id}` | Get one supervision plan | Any |
| POST | `/supervision-plans/{id}/activate` | Activate a supervision plan | CompliancePrincipal |
| POST | `/supervision-plans/{id}/terminate` | Terminate an active plan manually | CompliancePrincipal |
| POST | `/meetings` | Schedule the annual compliance meeting | CompliancePrincipal |
| GET | `/meetings` | List compliance meetings | Any |
| GET | `/meetings/{id}` | Get one compliance meeting | Any |
| POST | `/meetings/{id}/hold` | Mark the meeting as held | CompliancePrincipal |
| POST | `/meetings/{id}/close` | Close the meeting once attestations are terminal | CompliancePrincipal |
| GET | `/attestations` | List attestations | Any |
| GET | `/attestations/{id}` | Get one attestation | Any |
| POST | `/attestations/{id}/attest` | Attest to the annual compliance meeting | RegisteredRep |
| POST | `/wsp-documents` | Draft a WSP document | ComplianceAnalyst |
| GET | `/wsp-documents` | List WSP documents | Any |
| GET | `/wsp-documents/{id}` | Get one WSP document | Any |
| POST | `/wsp-documents/{id}/publish` | Publish a WSP draft, superseding its predecessor | CompliancePrincipal |
| POST | `/exam-requests` | Log a regulator's exam document request | ComplianceAnalyst |
| GET | `/exam-requests` | List exam document requests | Any |
| GET | `/exam-requests/{id}` | Get one exam document request | Any |
| POST | `/exam-requests/{id}/fulfill` | Produce the requested record | ComplianceAnalyst |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_STALE_REPRESENTATIVE_VERSION` | 412 |
| `ERR_STALE_BRANCH_VERSION` | 412 |
| `ERR_INSPECTION_GAP_VIOLATION` | 409 |
| `ERR_INSPECTION_ALREADY_OPEN` | 409 |
| `ERR_INSPECTION_INVALID_STATE` | 409 |
| `ERR_FINDINGS_STILL_OPEN` | 409 |
| `ERR_FINDING_INVALID_STATE` | 409 |
| `ERR_CORRESPONDENCE_INVALID_STATE` | 409 |
| `ERR_SOD_ESCALATION_RESOLVER` | 403 |
| `ERR_ACTIVITY_NOT_PENDING_DECISION` | 409 |
| `ERR_SD_REP_REQUIRES_HEIGHTENED_PLAN` | 403 |
| `ERR_REP_NOT_ACTIVE` | 409 |
| `ERR_NO_ACTIVE_HEIGHTENED_PLAN` | 409 |
| `ERR_PST_COMP_DETAILS_REQUIRED` | 422 |
| `ERR_PLAN_START_IN_PAST` | 422 |
| `ERR_PLAN_WINDOW_OVERLAP` | 409 |
| `ERR_REP_NOT_STATUTORILY_DISQUALIFIED` | 409 |
| `ERR_PLAN_ALREADY_ACTIVE` | 409 |
| `ERR_PLAN_NOT_ACTIVE` | 409 |
| `ERR_COMPLAINT_NOT_RESOLVABLE` | 409 |
| `ERR_REPORT_NOT_REQUIRED` | 409 |
| `ERR_DISCLOSURE_INVALID_STATE` | 409 |
| `ERR_MEETING_DATE_NOT_REACHED` | 422 |
| `ERR_DUPLICATE_MEETING_YEAR` | 409 |
| `ERR_MEETING_NOT_HELD` | 409 |
| `ERR_ATTESTATIONS_STILL_PENDING` | 409 |
| `ERR_NOT_ATTESTATION_OWNER` | 403 |
| `ERR_ATTESTATION_NOT_PENDING` | 409 |
| `ERR_ATTESTATION_DEADLINE_PASSED` | 422 |
| `ERR_WSP_NOT_DRAFT` | 409 |
| `ERR_SOD_WSP_PUBLISHER` | 403 |
| `ERR_EXAM_REQUEST_INVALID_STATE` | 409 |
| `ERR_INVALID_STATE` | 409 |

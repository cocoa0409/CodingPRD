# Consumer Complaint Management Regulator API — Product Requirements Document

## 1. Introduction

A bank's complaint management office carries a regulatory obligation that most operational teams underestimate until the first CFPB examination letter arrives: every consumer complaint must be captured, coded against a governed taxonomy, responded to inside a fixed statutory window, linked to a root-cause analysis, and traced through remediation — with the full audit trail intact years after closure. Complaints arriving through the regulator's own portal are the highest-stakes slice of this work, because the response clock starts the moment the complaint is registered and the regulator's own system of record is watching. Missed deadlines, unsubstantiated repeat issues on a single product, or a remediation payment made without proper sign-off are each independently examinable findings.

This document specifies the Consumer Complaint Management & Regulator Response API, the backend service that the complaint management office uses to run that lifecycle end to end. The system covers complaint intake across channels with taxonomy coding, automatic regulator-portal referral tracking against a fifteen-calendar-day response deadline, root-cause analysis with a thirty-day completion deadline, remediation and restitution decisions under segregation-of-duties controls, quality review of drafted responses, executive and legal escalation, product-level trend reporting with early-warning thresholds, and a derived product intake posture that gates new complaints when substantiated issue counts breach defined limits. All deadline, retention, and aging arithmetic reads a single logical clock so that examination scenarios can be replayed deterministically.

The audience is the engineering team building this service. Every rule stated here is a contract: state names, field names, error identifiers, and calculation constants are spelled exactly once and reused consistently throughout the document.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, carrying exactly one declared role name. A request missing either header, or presenting a role string outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403). Authorization is evaluated after authentication and before any resource-existence check, so a caller without permission learns nothing about whether a resource exists.

The declared roles are exactly these seven:

- `IntakeSpecialist` — front-line intake staff; creates complaints and reads shared resources.
- `CaseHandler` — complaint case worker: triage, investigation, root-cause analysis, response drafting, remediation drafting, and referral responses.
- `QAReviewer` — response quality reviewer; barred by segregation of duties from reviewing complaints they created.
- `RemediationApprover` — approves, rejects, and reverses remediation decisions; barred from acting on decisions they drafted.
- `ExecutiveReviewer` — owns the executive and legal escalation path.
- `ComplaintManager` — the complaint management office administrator: configuration (products, channels, taxonomy, templates), the logical clock, referral close and regulator-reopen, product unfreeze, and trend snapshots.
- `Auditor` — read-only access to all resources, including the audit trail and trend snapshots.

All seven roles carry `identity: opaque` semantics. For `IntakeSpecialist`, `CaseHandler`, `QAReviewer`, `RemediationApprover`, `ExecutiveReviewer`, `ComplaintManager`, and `Auditor` alike, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where the lifecycle requires attribution — for example as `owner_user_id` on a `Complaint` at intake, `drafted_by_user_id` on a `RemediationDecision`, `approved_by_user_id` on approval, `reviewer_user_id` on a `QualityReview`, `raised_by_user_id` on an `EscalationCase`, and `actor_user_id` together with `actor_role` on every `IntakeEvent` — and segregation-of-duties checks compare those recorded identifiers against the incoming `X-User-ID`, but no role's `X-User-ID` is ever matched against an entity's `id`.

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

List endpoints accept `limit` and `offset` query parameters. `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. Results are sorted by `created_at` ascending. The `meta` block of every list response carries `limit`, `offset`, `total_count`, and `has_more` so callers can page deterministically to the end of any collection.

### 2.4. Common Resource Properties and Mutation Semantics

Every resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp. Most resources additionally carry `updated_at` and a `version` integer. All timestamps are ISO 8601 UTC with three fractional digits. `version` starts at 1 at creation and increments by exactly 1 on every mutation of that resource, giving clients a cheap optimistic-concurrency signal and giving the audit trail a stable ordering.

Two resource kinds deliberately carry a lighter footprint because they are append-only audit or point-in-time reporting records: `IntakeEvent` and `TrendSnapshot` expose `id` and `created_at` only — both `updated_at` and `version` are absent on these two. Every other resource type (`Product`, `Channel`, `TaxonomyCategory`, `ResponseTemplate`, `Complaint`, `RegulatoryReferral`, `RootCauseAnalysis`, `RemediationDecision`, `QualityReview`, `EscalationCase`) carries the full common set.

Whenever a mutation touches a resource, that resource's `updated_at` refreshes to the logical-clock instant of the mutation and its `version` increments by 1. Cross-resource cascades follow the same rule per touched resource: a regulator-reopen that ripples into the parent complaint bumps the complaint's `version`, and the subsequent product counter refresh recomputes derived fields without touching the complaint again.

### 2.5. The Logical Clock

All deadline, aging, retention, and window arithmetic in the system reads a single logical clock — never wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z. A `ComplaintManager` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` instant and sets the clock to that value; the endpoint returns the current logical time as `current_utc`. Before any such call the default value stands, and the clock never falls back to wall-clock time under any circumstance.

Setting the clock is itself a business event: because the trailing-90-day substantiation window shifts with the clock, advancing the clock recomputes `posture` for every `Product`. Any deadline or expiry rule described in §3 — referral response deadlines, RCA deadlines, retention purge eligibility — evaluates against this clock at the instant the request is processed.

### 2.6. Validation Order

Every request passes through a fixed pipeline of checks, and the ordering matters whenever several failures coincide: an earlier failure masks all later ones, and the response carries the earliest applicable error. The pipeline runs in this exact sequence:

1. **Authentication** — `X-User-ID` and `X-User-Role` must be present and the role must be one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization** — the role must be permitted for the endpoint per the RBAC matrix; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403).
3. **Existence** — path-template identifiers are validated left to right along nested URLs, and business codes referenced in the request body must resolve to live records; otherwise `ERR_NOT_FOUND` (HTTP 404).
4. **Request shape** — required request-body fields must be present and correctly typed, enum members must be valid, integer ranges are enforced (`claimed_loss_cents` must be at least 0, each line item's `amount_cents` must be at least 0), and a quality-review window's `window_end_at` must lie strictly after its `window_start_at`; otherwise `ERR_INVALID_REQUEST` (HTTP 400).
5. **Business and workflow rules** — posture gating (`ERR_PRODUCT_FROZEN`), segregation of duties (`ERR_SOD_SELF_REVIEW`, `ERR_SOD_SELF_APPROVAL`), state-machine from-state checks (`ERR_INVALID_STATE_TRANSITION`), taxonomy retirement (`ERR_CATEGORY_RETIRED`), template activeness and channel/category matching (`ERR_TEMPLATE_NOT_ACTIVE`, `ERR_TEMPLATE_MISMATCH`), deadline rules (`ERR_RCA_DEADLINE_PASSED`, `ERR_RETENTION_EXPIRED`), window-overlap rules (`ERR_REVIEW_WINDOW_OVERLAP`, `ERR_SNAPSHOT_WINDOW_OVERLAP`), composite gates (`ERR_RCA_REQUIRED`, `ERR_QA_PASS_REQUIRED`, `ERR_ESCALATION_OPEN`), the restitution authority cap (`ERR_RESTITUTION_OVER_AUTHORITY`), referral-open blocking (`ERR_REFERRAL_OPEN`), template-in-use blocking (`ERR_TEMPLATE_IN_USE`), review ownership (`ERR_REVIEW_NOT_OWNED`), remediability (`ERR_COMPLAINT_NOT_REMEDIABLE`), and finally optimistic-concurrency staleness (`ERR_STALE_VERSION`, HTTP 412).

Within the business layer the same discipline holds: a request that would fail both a segregation-of-duties check and a state check surfaces the segregation error, and a stale-version rejection is always the last gate evaluated, after every semantic check has already passed. The precise trigger conditions for each rule live with the workflows in §3; the catalogue in §5 maps identifiers to status codes only.

### 2.7. Optimistic Concurrency Control

Two write operations guard against stale-client writes using optimistic concurrency on the parent `Complaint`:

- **Taxonomy recoding** requires the request to carry `expected_complaint_version`, the complaint `version` the client last observed.
- **Remediation-decision creation** likewise requires `expected_complaint_version` naming the complaint version against which the decision was drafted.

In both cases the server compares the supplied value to the complaint's current `version`. A mismatch means another writer has advanced the complaint since the client last read it — a recode, a triage, a referral submission, anything that legitimately bumps the version — and the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection exists so that a client holding a stale fact pattern never silently overwrites a newer category assignment or drafts remediation on facts it has not observed. Endpoints not named in this subsection do not take a version field at all.

### 2.8. Monetary Precision and Rounding

All money is integer cents; no fractional cents ever appear on the wire or in storage. Restitution computation applies a pinned rounding order — each line item's amount is floored individually before the per-line results are summed (see §3.6) — because the alternative order (sum first, floor once) yields a different total whenever two or more lines carry a proportional rate below the full hundred percent. Scores and ages are likewise integers: ages are whole days with fractional days discarded, and the timeliness score is an integer clamped between 0 and 100. Rate expressions use basis points, again as integers produced by floor operations.

### 2.9. Nested Resource Retrieval

Nested URLs are validated left to right: a request addressed at a complaint's referrals, events, RCAs, quality reviews, escalations, or remediation decisions first resolves the parent complaint identifier and only then the child resource; failure at any hop yields `ERR_NOT_FOUND` and deeper path segments are never consulted. Business codes in request bodies (`channel_code`, `product_code`, `category_code`, `template_key`, `parent_category_code`, `new_category_code`, `linked_product_code`, `response_template_key`) resolve through the referenced record's unique code, and an unresolvable code is likewise `ERR_NOT_FOUND`. The path parameters used across the routing table are `productId`, `channelId`, `categoryId`, `templateId`, `complaintId`, `referralId`, `rcaId`, `decisionId`, `reviewId`, and `escalationId`, with the generic `id` appearing on nested collection routes; each names the `id` of the resource at that position in the hierarchy.

### 2.10. Audit Trail

Every `Complaint` accumulates an append-only `IntakeEvent` stream recording each material fact of its life: `CREATED`, `TAXONOMY_RECODED`, `STATUS_CHANGED`, `RESPONSE_DRAFTED`, `QA_PASSED`, `QA_FAILED`, `REFERRAL_FILED`, `REFERRAL_RESPONDED`, `REMEDIATION_APPROVED`, `REMEDIATION_PAID`, `REMEDIATION_REVERSED`, `ESCALATED`, `ESCALATION_RESOLVED`, `REOPENED`, and `WITHDRAWN`. Each event carries `complaint_id`, an `event_type` drawn from the fifteen declared values above, the acting operator's `actor_user_id` and `actor_role`, an event-specific structured `payload` capturing old and new values, and `event_at` stamped from the logical clock when the event is appended. The trail is exposed read-only, ordered by `event_at` ascending with `created_at` ascending as the tiebreak. Because `IntakeEvent` records are immutable audit entries, they carry neither `updated_at` nor `version` (see §2.4).

## 3. Business Logic & Workflows

### 3.1. Reference Data: Products, Channels, and the Taxonomy

Before any complaint can enter the system, the office maintains three families of reference data, all administered by a `ComplaintManager`.

A **Product** is created with a unique business `product_code` (for example, `CKNG-STD`) and a human-readable `display_name`. At creation its intake-gating `posture` is `OPEN`, `open_complaint_count` is 0, `substantiated_count_90d` is 0, and `early_warning_active` is false; all four derived attributes then track the product's complaint traffic for the rest of its life (see §3.8).

A **Channel** is created with a unique `channel_code` (for example, WEB, PHONE, BRANCH, or CFPB_PORTAL) and a `display_name`. The boolean `is_regulator_portal`, defaulting to false, marks channels whose complaints are legally referrals: when a complaint arrives on such a channel, a `RegulatoryReferral` is created atomically in the same intake request (see §3.2).

A **TaxonomyCategory** is created with a unique `category_code` (for example, FEES.OVERDRAFT) and an optional `parent_category_code` naming another category's code; a null `parent_category_code` marks a root. The hierarchy is self-referential and exists to support rollup trend reporting: a complaint coded to a leaf still rolls up to its ancestors. A `ComplaintManager` retires a category through the retire action, which sets `retired` to true and bumps the category's `version`; retired categories remain on historical records but cannot be assigned to new complaints — intake and recode attempts against a retired category are rejected with `ERR_CATEGORY_RETIRED`.

### 3.2. Intake and Automatic Regulator Referral

An `IntakeSpecialist` or `CaseHandler` intakes a complaint by supplying `complainant_ref` (an opaque external customer reference), `channel_code`, `product_code`, `category_code`, a free-text `narrative`, an optional `claimed_loss_cents` (the alleged monetary loss in integer cents, defaulting to 0 and never negative), and an optional `portal_ref`. Intake is refused with `ERR_PRODUCT_FROZEN` whenever the linked product's `posture` is `FROZEN`, and with `ERR_CATEGORY_RETIRED` when the named category has been retired.

A successful intake stamps `received_at` from the logical clock, sets `status` to `INTAKE`, records the acting `X-User-ID` as `owner_user_id` (the anchor for later segregation-of-duties checks), initializes `version` at 1, appends a `CREATED` audit event, increments the product's `open_complaint_count` by 1, and recomputes the product's `posture`.

When the intake channel has `is_regulator_portal` true, the same request atomically creates a `RegulatoryReferral` alongside the complaint. The referral's `received_via_portal_at` equals the complaint's `received_at`; its `portal_ref` is the supplied value, defaulting to `AUTO-` followed by the complaint's `id` when omitted; and its `response_due_at` is exactly fifteen calendar days after `received_via_portal_at`, computed with calendar-day arithmetic that preserves the time of day and applies no business-day adjustment. The referral opens in `OPEN` status with `timeliness` `PENDING` and `submitted_at` null, and a `REFERRAL_FILED` event lands on the complaint's audit trail. The timeliness comparison used later is inclusive: a response submitted exactly at `response_due_at` counts as on time.

### 3.3. Working the Complaint: Triage, Investigation, Recode

A `CaseHandler` triages an `INTAKE` complaint, moving `INTAKE → TRIAGED`; triage from any other state is `ERR_INVALID_STATE_TRANSITION`, and triage against a retired category is additionally blocked by `ERR_CATEGORY_RETIRED`. Triage appends `STATUS_CHANGED`, bumps the complaint's `version`, and recomputes the product's `posture`.

Starting the investigation moves `TRIAGED → INVESTIGATING`; the same action also serves reopened complaints, so `REOPENED → INVESTIGATING` is legal under the identical precondition (the complaint's `status` must be either `TRIAGED` or `REOPENED`, otherwise `ERR_INVALID_STATE_TRANSITION`). Both forms append `STATUS_CHANGED` and bump `version`.

At any point a `CaseHandler` may recode the complaint's taxonomy by supplying `new_category_code` together with `expected_complaint_version`. A retired target category is refused with `ERR_CATEGORY_RETIRED`; a version mismatch is refused with `ERR_STALE_VERSION` per §2.7. A successful recode updates `category_code`, bumps the complaint's `version` by 1, and appends a `TAXONOMY_RECODED` event whose payload records the old and new codes.

### 3.4. Root-Cause Analysis

A `CaseHandler` opens a root-cause analysis on a complaint by supplying a `verdict` — one of `SUBSTANTIATED`, `NOT_SUBSTANTIATED`, or `INCONCLUSIVE` — a `linked_product_code` naming the product or process to which the root cause is attributed (which may differ from the complaint's own product), and the implicated `process_step`. The new RCA starts in `DRAFT` with `completed_at` null. Only one `DRAFT` or `COMPLETED` RCA may exist per complaint at any time: creating a fresh RCA automatically supersedes any prior `DRAFT` of the same complaint, moving it `DRAFT → SUPERSEDED` as a system action.

Completing the RCA is a `CaseHandler` action guarded by three checks: the RCA must be in `DRAFT` (otherwise `ERR_INVALID_STATE_TRANSITION`); the `verdict` must be one of the three declared values (otherwise `ERR_INVALID_REQUEST`); and the logical clock must not be past the complaint's `received_at` plus thirty calendar days — the boundary is inclusive, so completion exactly at the deadline succeeds, and anything later is `ERR_RCA_DEADLINE_PASSED`. Completion stamps `completed_at` from the clock, moves the RCA `DRAFT → COMPLETED`, and bumps its `version`. When the completed `verdict` is `SUBSTANTIATED`, the cascade continues one hop further: `substantiated_count_90d` is recomputed for the product named by `linked_product_code`, and that product's `posture` is recomputed against the thresholds in §3.8.

### 3.5. Drafting, Quality Review, and Resolution

Once a `COMPLETED` RCA exists, a `CaseHandler` drafts the consumer-facing response, moving `INVESTIGATING → RESPONSE_DRAFTED`. Drafting without a completed RCA is refused with `ERR_RCA_REQUIRED`. The draft persists `response_text` and may name a `response_template_key`; when a template is named it must be `ACTIVE` (otherwise `ERR_TEMPLATE_NOT_ACTIVE`) and its `channel_code` and `category_code` must both equal the complaint's own values at draft time (otherwise `ERR_TEMPLATE_MISMATCH`). Drafting appends `RESPONSE_DRAFTED` and bumps the complaint's `version`.

Submitting for quality assurance moves `RESPONSE_DRAFTED → RESPONSE_QA`, appending `STATUS_CHANGED` and bumping `version`. Quality review then proceeds under its own discipline (see §3.7): a `QAReviewer` claims an `OPEN` `QualityReview`, and either completes it or fails the draft. Completing a review with `PASS` leaves the complaint in `RESPONSE_QA` — a pass alone never resolves anything — while the dedicated qa-fail action moves the complaint `RESPONSE_QA → INVESTIGATING`, completes the acting reviewer's `OPEN` review with outcome `FAIL` in the same call, appends `QA_FAILED`, and bumps the complaint's `version`. The qa-fail action is refused with `ERR_SOD_SELF_REVIEW` when the acting reviewer is the complaint's `owner_user_id`.

Resolution is a `CaseHandler` action moving `RESPONSE_QA → RESOLVED`, guarded by two further checks evaluated after the state check: a `QualityReview` with `status` `COMPLETED` and `outcome` `PASS` must exist for the complaint (otherwise `ERR_QA_PASS_REQUIRED`), and no `EscalationCase` of the complaint may sit in `RAISED` or `ACKNOWLEDGED` (otherwise `ERR_ESCALATION_OPEN`). On resolution, `resolved_at` is stamped from the logical clock, `retention_purge_at` is fixed at the same calendar date five years after `resolved_at` (with February 29 mapping to February 28 in non-leap years), the product's `open_complaint_count` decrements by 1, the product's `posture` recomputes, a `STATUS_CHANGED` event is appended, and the complaint's `version` bumps. `RESOLVED` is terminal — but see reopening below.

Reopening is available to `CaseHandler` and `ComplaintManager` while the record is still within its retention window: the logical clock must be strictly before `retention_purge_at`, or the attempt is refused with `ERR_RETENTION_EXPIRED`. A successful reopen moves `RESOLVED → REOPENED`, clears both `resolved_at` and `retention_purge_at` to null, increments the product's `open_complaint_count` by 1, recomputes `posture`, appends `REOPENED`, and bumps `version`. The loop `RESOLVED → REOPENED → INVESTIGATING → … → RESOLVED` may repeat any number of times within retention.

Withdrawal by a `CaseHandler` or `ComplaintManager` moves a complaint from any non-terminal state — `INTAKE`, `TRIAGED`, `INVESTIGATING`, `RESPONSE_DRAFTED`, or `RESPONSE_QA` — to `WITHDRAWN`; from any other state the request is `ERR_INVALID_STATE_TRANSITION`. Withdrawal is blocked with `ERR_REFERRAL_OPEN` while any referral of the complaint is `OPEN` or `REOPENED_BY_REGULATOR`. Its terminal side effects mirror resolution: `resolved_at` stamps the clock, `retention_purge_at` is set to five years after `resolved_at` under the same leap-year rule, the product's open count decrements and `posture` recomputes, `WITHDRAWN` is appended, and `version` bumps.

Two derived ages accompany every complaint read. `days_open_calendar` counts whole days from `received_at` to an end instant — `resolved_at` when the complaint is `RESOLVED` or `WITHDRAWN`, the current logical clock otherwise — discarding fractional days; for terminal complaints the value is frozen at resolution and immune to later clock movement, while for open complaints it grows as the clock advances. `days_open_business` counts, over the same window, only calendar dates strictly after the intake date and on or before the end date that fall Monday through Friday and are not in the fixed holiday set (2026-01-01, 2026-07-04, 2026-12-25); the intake date itself is never counted. Whenever a weekend or holiday falls inside the window, the business count is strictly smaller than the calendar count.

### 3.6. Remediation and Restitution

A `CaseHandler` drafts a `RemediationDecision` against a complaint by supplying a `decision_type` — one of `NO_ACTION`, `CORRECTION`, `RESTITUTION`, or `CORRECTION_AND_RESTITUTION` — a `line_items` array, and `expected_complaint_version` per §2.7. Each line item carries a `label`, an `amount_cents` of at least 0, and an optional `rounding_rate_bps`. The decision opens in `DRAFT` with `drafted_by_user_id` set to the acting `X-User-ID`; creation itself bumps the parent complaint's `version` by 1, because the drafting basis has advanced.

The decision's `restitution_amount_cents` is computed under a pinned rounding order: for each line item, multiply its `amount_cents` by its `rounding_rate_bps` (defaulting to 10000, the full amount, when omitted), divide by 10000, and floor to a whole cent — then sum the per-line results. Flooring per line before summation is the specification; summing raw amounts first and flooring once at the end yields a different total whenever two or more lines carry a rate below the full amount and is a violation. When `line_items` is empty — as it always is for `NO_ACTION` and `CORRECTION` — `restitution_amount_cents` is 0.

Submitting a `DRAFT` decision moves it `DRAFT → PENDING_APPROVAL` and bumps its `version`, under two guards: a `RESTITUTION` or `CORRECTION_AND_RESTITUTION` decision must carry non-empty `line_items` and a `restitution_amount_cents` greater than 0 (otherwise `ERR_INVALID_REQUEST`), and the parent complaint must sit in `INVESTIGATING`, `RESPONSE_DRAFTED`, `RESPONSE_QA`, `RESOLVED`, or `REOPENED` — a complaint still in `INTAKE` or `TRIAGED`, or already `WITHDRAWN`, makes the submit `ERR_COMPLAINT_NOT_REMEDIABLE`.

Approval and rejection belong to a `RemediationApprover`, and segregation of duties is enforced on both: the acting `X-User-ID` must differ from the decision's `drafted_by_user_id`, or the request is `ERR_SOD_SELF_APPROVAL`. Approval carries a further authority cap: when `restitution_amount_cents` exceeds 2500000 cents, the acting approver must also present the request header `X-Manager-Authority` with the value true, or the approval is refused with `ERR_RESTITUTION_OVER_AUTHORITY`. A successful approval moves `PENDING_APPROVAL → APPROVED`, records the acting user as `approved_by_user_id`, recomputes the complaint's `approved_restitution_cents` upward by this decision's `restitution_amount_cents`, appends `REMEDIATION_APPROVED` to the complaint's audit trail, and bumps the decision's `version`. Rejection moves `PENDING_APPROVAL → REJECTED` with the same self-approval guard and a version bump, and is terminal.

An `APPROVED` decision has two exits. A `CaseHandler` marks it paid, moving `APPROVED → PAID`: the complaint's `paid_restitution_cents` recomputes upward by the decision's amount, `REMEDIATION_PAID` is appended, and the decision's `version` bumps. Alternatively a `RemediationApprover` reverses it, moving `APPROVED → REVERSED`: the complaint's `approved_restitution_cents` recomputes downward by the decision's amount, `REMEDIATION_REVERSED` is appended, and `version` bumps. Approve-then-reverse is the designed compensation path and restores `approved_restitution_cents` to its pre-approval value. `PAID`, `REJECTED`, and `REVERSED` are all terminal. On the complaint, `approved_restitution_cents` always equals the sum of `restitution_amount_cents` over its decisions in `APPROVED` or `PAID` status, and `paid_restitution_cents` the sum over decisions in `PAID` status alone.

### 3.7. Quality Review Governance

A `QAReviewer` claims a review on a complaint by supplying a sampling window `window_start_at` (inclusive) and `window_end_at` (exclusive, and required to lie strictly after the start). The review opens in `OPEN` with `reviewer_user_id` set to the acting user and `outcome` null. One reviewer may not hold two `OPEN` reviews whose half-open intervals intersect: touching endpoints — one window's end exactly equal to the other's start — do not overlap, but any genuine intersection is refused with `ERR_REVIEW_WINDOW_OVERLAP`.

Completing a review is restricted to the owning reviewer: the acting `X-User-ID` must equal the review's `reviewer_user_id` (otherwise `ERR_REVIEW_NOT_OWNED`), the review must be `OPEN` (otherwise `ERR_INVALID_STATE_TRANSITION`), the supplied `outcome` must be `PASS` or `FAIL` (otherwise `ERR_INVALID_REQUEST`), and segregation of duties bars the reviewer from completing a review on a complaint whose `owner_user_id` equals their own identifier (`ERR_SOD_SELF_REVIEW`). Completion persists the `outcome`, moves the review `OPEN → COMPLETED`, appends `QA_PASSED` on a pass or `QA_FAILED` on a failure, recomputes the complaint's `timeliness_score` because the quality bonus input has changed (see §3.9), and bumps the review's `version`.

Cancellation moves `OPEN → CANCELLED` and is available to a `QAReviewer` — again only their own reviews, or `ERR_REVIEW_NOT_OWNED` — and to a `ComplaintManager`, who is not subject to the ownership check. `COMPLETED` and `CANCELLED` are terminal.

### 3.8. Regulator Referral Lifecycle and the Response Clock

A referral's life begins `OPEN` (created automatically at portal intake, §3.2). A `CaseHandler` submits the regulator-facing response by supplying a non-empty `response_text` — an empty body is `ERR_INVALID_REQUEST` — from either `OPEN` or `REOPENED_BY_REGULATOR`; any other state is `ERR_INVALID_STATE_TRANSITION`. Submission stamps `submitted_at` from the logical clock, moves the referral to `RESPONSE_SUBMITTED`, derives `timeliness` as `ON_TIME` when `submitted_at` is at or before `response_due_at` and `LATE` otherwise, recomputes the parent complaint's `timeliness_score`, appends `REFERRAL_RESPONDED` on the complaint, and bumps the referral's `version`.

From `RESPONSE_SUBMITTED` a `ComplaintManager` may close the referral, moving it to the terminal `CLOSED_BY_REGULATOR`, or register a regulator reopen, moving it `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR`. The reopen is a three-hop cascade: first the referral's own `version` bumps; then, when the parent complaint is `RESOLVED`, it transitions to `REOPENED` with `resolved_at` and `retention_purge_at` cleared to null and the complaint's `version` bumped; and when that second hop fired, the product's `open_complaint_count` increments by 1 and its `posture` recomputes. The cycle `RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR → RESPONSE_SUBMITTED` may repeat; crucially, resubmission after a regulator reopen re-derives `timeliness` against the **same** original `response_due_at` — a regulator reopen never extends the deadline.

The complaint-level `timeliness_score` distills referral responsiveness and review quality into an integer between 0 and 100, recomputed at every referral response submission and at every quality-review completion, and null until the first referral response is submitted. The computation proceeds in a pinned order. First, whole days to respond are counted from the complaint's `received_at` to the referral's `submitted_at`, discarding fractional days. A base score starts at 100 and loses 5 points per day to respond, floored at 0. The base is then halved when the referral's `timeliness` is `LATE` (multiplier one-half) and left whole when `ON_TIME` (multiplier one), and this product is floored to an integer **before** any bonuses apply. A quality bonus then adds 10 when the latest `COMPLETED` quality review passed, subtracts 15 when it failed, and adds 0 when no completed review exists. A high-value bonus adds 5 when the complaint's `claimed_loss_cents` is at least 1000000 cents. Finally the total is capped at 100 and floored at 0.

### 3.9. Escalation Path and Response Templates

A `CaseHandler` or `ComplaintManager` raises an `EscalationCase` on a complaint by supplying an `escalation_tier` of `EXECUTIVE` or `LEGAL` and a free-text `reason`; the case opens `RAISED` with `raised_by_user_id` set to the acting user and an `ESCALATED` event appended to the complaint. From there an `ExecutiveReviewer` acknowledges the case (`RAISED → ACKNOWLEDGED`), resolves an acknowledged case (`ACKNOWLEDGED → RESOLVED`, appending `ESCALATION_RESOLVED` on the parent complaint), or dismisses a raised case outright (`RAISED → DISMISSED`). Each transition bumps the case's `version`, and `RESOLVED` and `DISMISSED` are terminal. As §3.5 states, any case sitting in `RAISED` or `ACKNOWLEDGED` blocks resolution of its complaint with `ERR_ESCALATION_OPEN`.

Response templates are governed by the `ComplaintManager` under a single-active-per-pair invariant. A template is created in `DRAFT` with a unique `template_key`, the `channel_code` and `category_code` it serves, and its `body` text. Publishing moves `DRAFT → ACTIVE` — from any other state, `ERR_INVALID_STATE_TRANSITION` — and automatically retires any other `ACTIVE` template carrying the same `(channel_code, category_code)` pair, moving it to `RETIRED` and bumping its `version`; the published template's own `version` bumps as well, so at most one template per pair is ever `ACTIVE`. Retiring an `ACTIVE` template directly is blocked with `ERR_TEMPLATE_IN_USE` while any complaint in `RESPONSE_DRAFTED` or `RESPONSE_QA` references it via `response_template_key`; otherwise it moves to the terminal `RETIRED` with a version bump.

### 3.10. Trend Snapshots, Early Warning, and Product Posture

Trend reporting is snapshot-based. A `ComplaintManager` or `ExecutiveReviewer` evaluates and persists a `TrendSnapshot` for a product by supplying `period_start_at` (inclusive) and `period_end_at` (inclusive — the interval is closed on both ends, and the end must be at or after the start, otherwise `ERR_INVALID_REQUEST`). Windows for the same product must not overlap under closed-interval semantics: a new window is refused with `ERR_SNAPSHOT_WINDOW_OVERLAP` whenever its start falls at or before an existing snapshot's end while that snapshot's start falls at or before the new window's end — two windows sharing exactly one boundary date count as overlapping.

Snapshot evaluation follows a pinned order. First `complaint_count` counts the product's complaints whose `received_at` falls inside the closed window on both ends. Then `substantiated_count` counts, among those, complaints whose latest RCA verdict is `SUBSTANTIATED`. Then `substantiation_rate_bps` is derived in basis points: 0 when `complaint_count` is 0, otherwise the substantiated count times 10000 divided by the complaint count, floored to an integer. The live `open_complaint_count` of the product is read next. Finally `early_warning` is true when `complaint_count` is at least 3 **and** at least one of two conditions holds — `substantiation_rate_bps` is at least 5000, or the live open count is at least 10. An empty window never warns, regardless of the live open count. The snapshot persists `product_code`, the window bounds, all computed values, and `evaluated_at` stamped from the logical clock; because a snapshot is a point-in-time record it carries neither `updated_at` nor `version`.

Persisting a snapshot updates the product's `early_warning_active` to the snapshot's `early_warning` value and recomputes the product's `posture`. The posture machine is derived, not user-driven: aggregates are refreshed first — `open_complaint_count` counts the product's complaints in `INTAKE`, `TRIAGED`, `INVESTIGATING`, `RESPONSE_DRAFTED`, `RESPONSE_QA`, or `REOPENED`, and `substantiated_count_90d` counts complaints whose latest RCA verdict is `SUBSTANTIATED` and whose `received_at` falls within the trailing ninety calendar days of the logical clock — and the posture then derives by threshold: `FROZEN` when `substantiated_count_90d` reaches at least 5; otherwise `WATCH` when `early_warning_active` is true or `substantiated_count_90d` is at least 3; otherwise `OPEN`. The posture recomputes on every complaint status change, every RCA completion, every snapshot evaluation, every clock set, and every manual unfreeze. While a product is `FROZEN`, complaint intake on it is rejected with `ERR_PRODUCT_FROZEN`. A `ComplaintManager` may also unfreeze a `FROZEN` product manually, moving it to `WATCH` and bumping the product's `version`; the system path back from `FROZEN` to `WATCH` fires on its own whenever a recompute finds `substantiated_count_90d` below 5.

## 4. Endpoint Definitions

All endpoints are mounted under `/complaint-office`. Creating a new resource returns HTTP 201; actions that modify an existing resource and all reads return HTTP 200. Request payloads, response shapes, side effects, and error triggers are specified in §2 and §3; this table is the routing and authorization contract only.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /complaint-office/_clock/set_current_utc | Set the logical clock (startup default 2026-08-01T00:00:00Z; recomputes every product's posture) | ComplaintManager |
| POST | /complaint-office/products | Create a Product | ComplaintManager |
| GET | /complaint-office/products/{productId} | Get a Product | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/products | List Products (optional `posture` filter) | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| POST | /complaint-office/products/{productId}/unfreeze | Manual posture override FROZEN → WATCH | ComplaintManager |
| GET | /complaint-office/products/{id}/complaints | List complaints of a product (optional `status` filter) | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/products/{id}/trend-snapshots | List trend snapshots of a product | ComplaintManager, CaseHandler, ExecutiveReviewer, Auditor |
| POST | /complaint-office/products/{id}/trend-snapshots | Evaluate and persist a TrendSnapshot for a closed period window | ComplaintManager, ExecutiveReviewer |
| POST | /complaint-office/channels | Create a Channel | ComplaintManager |
| GET | /complaint-office/channels/{channelId} | Get a Channel | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/channels | List Channels | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| POST | /complaint-office/taxonomy-categories | Create a TaxonomyCategory | ComplaintManager |
| GET | /complaint-office/taxonomy-categories/{categoryId} | Get a TaxonomyCategory | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/taxonomy-categories | List TaxonomyCategories (optional `parent_category_code`, `retired` filters) | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| POST | /complaint-office/taxonomy-categories/{categoryId}/retire | Retire a TaxonomyCategory | ComplaintManager |
| POST | /complaint-office/response-templates | Create a ResponseTemplate (DRAFT) | ComplaintManager |
| GET | /complaint-office/response-templates/{templateId} | Get a ResponseTemplate | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/response-templates | List ResponseTemplates (optional `channel_code`, `category_code`, `status` filters) | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| POST | /complaint-office/response-templates/{templateId}/publish | Publish a DRAFT template; supersedes the ACTIVE template of the same pair | ComplaintManager |
| POST | /complaint-office/response-templates/{templateId}/retire | Retire an ACTIVE template | ComplaintManager |
| POST | /complaint-office/complaints | Intake a complaint; auto-creates a RegulatoryReferral on portal channels | IntakeSpecialist, CaseHandler |
| GET | /complaint-office/complaints/{complaintId} | Get a Complaint (computed ages evaluated at read time) | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/complaints | List Complaints (optional `status`, `product_code`, `channel_code`, `category_code` filters) | ComplaintManager, CaseHandler, IntakeSpecialist, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/complaints/{id}/events | Audit trail: the complaint's IntakeEvents, ordered by event_at then created_at ascending | ComplaintManager, CaseHandler, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| POST | /complaint-office/complaints/{complaintId}/triage | INTAKE → TRIAGED | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/start_investigation | TRIAGED or REOPENED → INVESTIGATING | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/taxonomy_recodes | Recode the complaint's taxonomy category (OCC-guarded) | CaseHandler |
| POST | /complaint-office/complaints/{id}/rcas | Create a RootCauseAnalysis (DRAFT); supersedes any prior DRAFT of the same complaint | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/draft_response | INVESTIGATING → RESPONSE_DRAFTED | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/submit_for_qa | RESPONSE_DRAFTED → RESPONSE_QA | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/qa_fail | RESPONSE_QA → INVESTIGATING; completes the acting reviewer's OPEN review with FAIL | QAReviewer |
| POST | /complaint-office/complaints/{complaintId}/resolve | RESPONSE_QA → RESOLVED | CaseHandler |
| POST | /complaint-office/complaints/{complaintId}/reopen | RESOLVED → REOPENED (within retention) | CaseHandler, ComplaintManager |
| POST | /complaint-office/complaints/{complaintId}/withdraw | Any non-terminal status → WITHDRAWN | CaseHandler, ComplaintManager |
| GET | /complaint-office/complaints/{id}/referrals | List referrals of a complaint | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/referrals/{referralId} | Get a RegulatoryReferral | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| POST | /complaint-office/referrals/{referralId}/submit_response | OPEN or REOPENED_BY_REGULATOR → RESPONSE_SUBMITTED | CaseHandler |
| POST | /complaint-office/referrals/{referralId}/close | RESPONSE_SUBMITTED → CLOSED_BY_REGULATOR | ComplaintManager |
| POST | /complaint-office/referrals/{referralId}/regulator_reopen | RESPONSE_SUBMITTED → REOPENED_BY_REGULATOR; cascades a RESOLVED parent complaint to REOPENED | ComplaintManager |
| GET | /complaint-office/complaints/{id}/rcas | List RCAs of a complaint | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/rcas | List RCAs across complaints (optional `complaint_id`, `linked_product_code`, `status` filters) | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/rcas/{rcaId} | Get an RCA | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| POST | /complaint-office/rcas/{rcaId}/complete | DRAFT → COMPLETED with 30-day deadline enforcement | CaseHandler |
| POST | /complaint-office/complaints/{id}/remediation_decisions | Create a RemediationDecision (DRAFT); OCC-guarded on complaint version | CaseHandler |
| GET | /complaint-office/complaints/{id}/remediation_decisions | List remediation decisions of a complaint (optional `status` filter) | ComplaintManager, CaseHandler, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| GET | /complaint-office/remediation-decisions/{decisionId} | Get a RemediationDecision | ComplaintManager, CaseHandler, QAReviewer, RemediationApprover, ExecutiveReviewer, Auditor |
| POST | /complaint-office/remediation-decisions/{decisionId}/submit | DRAFT → PENDING_APPROVAL | CaseHandler |
| POST | /complaint-office/remediation-decisions/{decisionId}/approve | PENDING_APPROVAL → APPROVED (segregation of duties + authority cap) | RemediationApprover |
| POST | /complaint-office/remediation-decisions/{decisionId}/reject | PENDING_APPROVAL → REJECTED (segregation of duties) | RemediationApprover |
| POST | /complaint-office/remediation-decisions/{decisionId}/mark_paid | APPROVED → PAID | CaseHandler |
| POST | /complaint-office/remediation-decisions/{decisionId}/reverse | APPROVED → REVERSED (compensating action) | RemediationApprover |
| POST | /complaint-office/complaints/{id}/quality-reviews | Claim a QA review occupying a half-open sampling window | QAReviewer |
| GET | /complaint-office/complaints/{id}/quality-reviews | List quality reviews of a complaint | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/quality-reviews/{reviewId} | Get a QualityReview | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| POST | /complaint-office/quality-reviews/{reviewId}/complete | OPEN → COMPLETED with PASS or FAIL | QAReviewer |
| POST | /complaint-office/quality-reviews/{reviewId}/cancel | OPEN → CANCELLED | QAReviewer, ComplaintManager |
| POST | /complaint-office/complaints/{id}/escalations | Raise an EscalationCase | CaseHandler, ComplaintManager |
| GET | /complaint-office/complaints/{id}/escalations | List escalations of a complaint | ComplaintManager, CaseHandler, QAReviewer, ExecutiveReviewer, Auditor |
| GET | /complaint-office/escalations/{escalationId} | Get an EscalationCase | ComplaintManager, CaseHandler, ExecutiveReviewer, Auditor |
| POST | /complaint-office/escalations/{escalationId}/acknowledge | RAISED → ACKNOWLEDGED | ExecutiveReviewer |
| POST | /complaint-office/escalations/{escalationId}/resolve | ACKNOWLEDGED → RESOLVED | ExecutiveReviewer |
| POST | /complaint-office/escalations/{escalationId}/dismiss | RAISED → DISMISSED | ExecutiveReviewer |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in §2 and §3 alongside the workflow each rule guards; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_PRODUCT_FROZEN | 409 |
| ERR_CATEGORY_RETIRED | 409 |
| ERR_TEMPLATE_NOT_ACTIVE | 409 |
| ERR_TEMPLATE_MISMATCH | 409 |
| ERR_TEMPLATE_IN_USE | 409 |
| ERR_RCA_REQUIRED | 409 |
| ERR_RCA_DEADLINE_PASSED | 409 |
| ERR_QA_PASS_REQUIRED | 409 |
| ERR_ESCALATION_OPEN | 409 |
| ERR_SOD_SELF_REVIEW | 409 |
| ERR_SOD_SELF_APPROVAL | 409 |
| ERR_RESTITUTION_OVER_AUTHORITY | 409 |
| ERR_REFERRAL_OPEN | 409 |
| ERR_REVIEW_NOT_OWNED | 409 |
| ERR_REVIEW_WINDOW_OVERLAP | 409 |
| ERR_SNAPSHOT_WINDOW_OVERLAP | 409 |
| ERR_RETENTION_EXPIRED | 409 |
| ERR_COMPLAINT_NOT_REMEDIABLE | 409 |
| ERR_STALE_VERSION | 412 |

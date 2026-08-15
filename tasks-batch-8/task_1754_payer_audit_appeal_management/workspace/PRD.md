# Payer Audit & Appeal Management API — Product Requirements Document

## 1. Introduction

Provider revenue-cycle teams operate under constant audit pressure from Recovery Audit Contractors (RACs) and commercial payers. Every audit letter arrives with a records-submission deadline measured in days, a portfolio of claims whose dollars are at risk, and — once the payer issues its determination — a structured ladder of appeal levels whose filing windows close whether or not the team is watching. Missed records deadlines convert into automatic technical denials; missed appeal windows convert recoverable denials into final write-downs; and recoupment demands begin accruing interest while the appeals that could reverse them are still working their way through the queue.

This document specifies the Payer Audit & Appeal Management API, which tracks the full lifecycle of payer audits from intake through closure. The platform covers payer configuration and appeal-track rules, audit intake with deadline enforcement, clinical and technical denial categorization, multi-level appeal progression with evidence-packet readiness for the ALJ and external-review levels, overpayment recoupment demands with tiered interest accrual, remittance offset accounting through both manual allocation and an automatic waterfall, and corrective action plans that close the loop on recurring denial root causes. Success-rate analytics grouped by payer and issue code feed a frozen prior-quarter snapshot that weights the net exposure view, so leadership always sees both the gross dollars at risk and a vindication-adjusted net figure.

Two design commitments shape everything that follows. First, time in this system is a logical clock under administrative control — every deadline evaluation, automatic sweep, and interest accrual reads the same logical "now," making behavior deterministic and fully auditable. Second, money moves only through explicit ledger artifacts: recoupment demands, remittances, and offset transactions, each of which can be reversed with full restoration of the counterparties' balances.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify the caller's operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).

The system recognizes eight acting roles. `RevenueCycleAdmin` is the platform administrator responsible for payer and issue-code configuration, logical clock control, and payer suspension. `HIMCoordinator` handles health information management: audit intake, claim lines, and records submission. `AppealsSpecialist` drafts, files, and withdraws appeals and assembles evidence packets. `DepartmentDirector` holds director authority over plan activation, required-item waivers, high-exposure case closure, and write-offs. `PFSAccountant` runs patient financial services: offsets, allocation, reversals, and write-offs. `ComplianceOfficer` proposes corrective action plans and runs their effectiveness checks. `InternalAuditor` verifies or marks ineffective those corrective action plans, segregated from the proposer. `PayerAgent` is the payer-side operator performing reviews, determinations, appeal decisions, recoupment demands, and remittances. Two further names appear in the authorization model: `System`, the automation principal behind clock-evaluated transitions and cascades, which has no direct endpoint access, and `Any`, which denotes that every read endpoint is open to any authenticated caller regardless of role. An attempt to perform an operation outside the caller's designated role is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

When `X-User-Role` is `PayerAgent`, `X-User-ID` is the `id` of the acting `Payer`; ownership checks on any resource that references a payer compare the resource's foreign-key field to `X-User-ID`. Concretely, a `PayerAgent` caller must be acting on behalf of the payer that owns the target: the case's `payer_id` when beginning review or posting a determination, the payer of the appeal's case when posting an appeal decision, the case's payer when issuing a recoupment demand, the demand's `payer_id` when adjusting principal, and the `payer_id` supplied in the request body when registering a remittance. Any mismatch is rejected with `ERR_PAYER_MISMATCH` (HTTP 403).

For the seven remaining acting roles — `RevenueCycleAdmin`, `HIMCoordinator`, `AppealsSpecialist`, `DepartmentDirector`, `PFSAccountant`, `ComplianceOfficer`, and `InternalAuditor` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `proposed_by_user_id` or `verified_by_user_id` on a corrective action plan, or as `actor_user_id` on a case event) but never compares it to any entity's `id`. The single comparison the platform performs on these opaque identifiers is the segregation-of-duties check on corrective-plan verification, which compares the verifier's `X-User-ID` against the plan's recorded `proposed_by_user_id` (see §3.9).

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return: when omitted it defaults to 10, its accepted minimum is 1, and its accepted maximum is 100. The `offset` parameter specifies how many items to skip from the beginning of the result set and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp (`created_at`) in ascending order.

List responses carry the following pagination fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Time-Driven Automation

Every timestamp the server assigns — submissions, filings, decisions, closures, offset applications, reversals — is read from a single server-side logical clock, never from the host wall clock. At server startup the logical clock stands at exactly `2026-08-01T00:00:00Z`, regardless of the real time of day.

A `RevenueCycleAdmin` may move the clock through an admin-only test-driving capability whose request carries the target instant in the `to_iso8601` field; the response reports the clock's new value in `current_utc`. Setting the clock is the trigger that evaluates every automatic transition in the system: the missed-records-deadline sweep with its auto-denial cascade (§3.2) and the claim-line finalization sweep (§3.5). Appeal expiry is deliberately not part of any clock sweep — a draft appeal past its deadline expires lazily, only when a filing attempt is made against it (§3.4).

### 2.5. Common Resource Properties

All primary resources — payers, issue codes, audit cases, claim lines, appeals, evidence packets, packet items, recoupment demands, remittances, offset transactions, and corrective action plans — carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification of the resource, including mutations driven by cascading side effects.

The case event trail is the single exception. An `AuditCaseEvent` is append-only: it carries `id` and `created_at`, and both `updated_at` and `version` are absent, because events are never modified after being written.

### 2.6. Monetary Values, Basis Points, and Rounding

All monetary amounts in this system are integers denominated in cents — field names ending in `_cents` — and no floating-point money ever appears in requests or responses. Interest and success rates are expressed as integer basis points. Whenever a calculation produces a fractional cent or fractional basis point, the rounding method is round half up.

Rounding order is pinned where it affects results. Net exposure rounds each claim line's weighted amount half up to whole cents before summing across lines (§3.9). The allocation waterfall rounds each demand's accrued interest half up to whole cents per demand before computing portions — fractional interest is never summed raw across demands and rounded once (§3.8). A demand's accrued interest is rounded half up once, after the interest cap is applied (§3.7). Success rates are rounded half up to integer basis points (§3.9).

### 2.7. Optimistic Concurrency Control

Two write endpoints in the API are guarded by optimistic concurrency control, and no other endpoint accepts a version field.

- `POST /audit-cases/{id}/records-submissions` requires the non-optional field `expected_audit_case_version`, carrying the audit case `version` the client last observed. If the case's version has advanced since that observation — because another submission, amendment, or automatic transition landed in between — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Initial submissions, late submissions, and manifest amendments are all legitimate from their respective states, so only the stale version distinguishes an unintended blind re-submission from a deliberate sequential one.
- `POST /recoupment-demands/{id}/adjustments` requires the non-optional field `expected_recoupment_demand_version`, carrying the recoupment demand `version` the client last observed. A mismatch with the demand's current version is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Adjustments are legitimate any number of times while the demand is `DEMANDED` or `PARTIALLY_RECOUPED`, so the version check is the only signal that the client is adjusting a demand it has not re-read.

Clients discover current versions through ordinary resource reads; every mutation response returns the updated resource including its new `version`.

### 2.8. Deadline Semantics and Inclusive Boundaries

All deadlines in the system are computed by adding a payer-configured whole number of days to a reference timestamp: the records deadline adds the payer's submission window to the audit's received timestamp, and each appeal level's filing deadline adds the payer's per-level window to the decision timestamp that opened that level (§3.2 and §3.4 give the exact pairings).

Every deadline in the system is inclusive. An action lands on time when the logical clock reads at or before the deadline instant: a submission whose logical timestamp equals `records_due_at` exactly is on time, and one second past it is late. The same inclusivity governs every appeal `filed_deadline_at`.

### 2.9. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order, and the earliest failing tier determines the error returned:

1. Header presence and well-formedness — failures return `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. Role authorization — the caller's role must appear in the endpoint's authorized set, else `ERR_FORBIDDEN_FOR_ROLE` (403).
3. Request-body well-formedness — required fields present, enums valid, amounts positive, and `service_end_date` after `service_start_date` on claim lines — else `ERR_INVALID_REQUEST` (400).
3.5. Analytics window sanity, evaluated only on the success-rate analytics read, immediately after body well-formedness and before existence — a window whose `from` is not before its `to` returns `ERR_ANALYTICS_WINDOW_INVALID` (422).
4. Existence — every path identifier and every foreign-key reference in the body must resolve, checked left to right, else `ERR_NOT_FOUND` (404).
5. `PayerAgent` ownership — `X-User-ID` must equal the payer of the target resource, else `ERR_PAYER_MISMATCH` (403).
6. State guards — the target must be in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (409); the domain-specialized state rejections `ERR_LINE_NOT_APPEALABLE`, `ERR_PACKET_ALREADY_EXISTS`, `ERR_PACKET_IMMUTABLE`, `ERR_DEMAND_ON_HOLD`, and `ERR_OPEN_APPEALS_EXIST` are raised at this same tier.
7. Segregation of duties and director authority — else `ERR_SEGREGATION_OF_DUTIES` (409) or `ERR_REQUIRES_DIRECTOR` (403).
8. Temporal checks — appeal filing deadlines and the corrective-plan effectiveness window — else `ERR_APPEAL_DEADLINE_PASSED` (409) or `ERR_CAP_WINDOW_NOT_ELAPSED` (409).
9. Uniqueness, overlap, capacity, and track constraints — `ERR_PAYER_SUSPENDED`, `ERR_CONCURRENT_AUDIT_CAP`, `ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT`, `ERR_APPEAL_LEVEL_NOT_AVAILABLE`, `ERR_EVIDENCE_PACKET_NOT_READY`, `ERR_DETERMINATION_INCOMPLETE`, `ERR_DETERMINATION_LINE_INVALID`, `ERR_DETERMINATION_AMOUNT_INVALID`, and `ERR_DUPLICATE_ISSUE_CODE` (409 or 422 per the catalogue in §5).
10. Cross-payer linkage on manual offsets — else `ERR_CROSS_PAYER_ALLOCATION` (409).
11. Money ceilings — demand principal bounds and offset amount bounds — else `ERR_DEMAND_EXCEEDS_DENIED` (409) or `ERR_OFFSET_EXCEEDS_OUTSTANDING` (409).

### 2.10. Nested Resource Retrieval

Requests that address nested resources — packet items beneath their evidence packet, offsets beneath a demand, collections beneath an audit case — are validated strictly left to right along the path. The server confirms the existence of the first identifier in the path before examining the second, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) naming the first segment that does not resolve. Item-level endpoints address their target through two path variables: the packet's `id` and the item's `itemId`, as in `/evidence-packets/{id}/items/{itemId}/attach`. A request addressed to an item under a nonexistent packet therefore fails on the packet before the item is ever considered.

### 2.11. The Append-Only Case Event Trail

Every material occurrence in an audit case's life appends an `AuditCaseEvent` to that case's trail. An event carries the owning `audit_case_id`; an `event_type` drawn from `CASE_CREATED`, `RECORDS_SUBMITTED`, `REVIEW_BEGAN`, `DETERMINATION_ISSUED`, `CASE_MISSED_DEADLINE`, `LINES_AUTO_DENIED`, `DEMAND_CREATED`, `OFFSET_APPLIED`, `OFFSET_REVERSED`, and `CASE_CLOSED`; the `actor_role` and `actor_user_id` that caused it (recorded as the system actor for automatic transitions); a `payload` object with event-specific details such as denied totals or offset identifiers; and `occurred_at`, the logical-clock timestamp of the occurrence. The trail for a case is readable through the case's events listing in chronological order. Events are never updated or deleted.

## 3. Business Logic & Workflows

This section walks the business processes of the platform from payer onboarding through corrective action, presenting rules in the context where they operate. Endpoint paths and mechanics live in §4; error identifiers are defined in §5.

### 3.1. Payer Configuration and the Denial Issue Taxonomy

Before any audit can be tracked, a `RevenueCycleAdmin` registers the payer. Payer creation captures the display `name`, the `payer_type` (`RAC` or `COMMERCIAL`), and the payer's full deadline configuration: `records_submission_days` (the window from audit receipt to the records deadline), `l1_deadline_days`, `l2_deadline_days`, `l3_deadline_days`, `l4_deadline_days`, and `l5_deadline_days` (the per-level appeal filing windows of the Medicare track), and `external_review_deadline_days` (the filing window for the commercial track's third level). The same registration carries the operational guardrails: `concurrent_audit_cap`, the maximum number of audit cases the payer may have open at once, and `hold_levels`, a subset of the appeal levels `LEVEL_1` and `LEVEL_2` during which the payer's recoupment demands are placed on hold once such an appeal reaches `PENDING_DECISION` (mechanics in §3.7). Finally, the payer's recoupment interest policy is fixed at registration: `interest_rate_bps_tier1` (basis points charged per thirty-day period for each of the first two periods), `interest_rate_bps_tier2` (basis points per period from the third period onward), and `interest_cap_pct` (the cap on accrued interest as a percent of the at-issue principal).

From `payer_type` the system derives the payer's `appeal_track`: an `RAC` payer follows the `MEDICARE` track, and a `COMMERCIAL` payer follows the `COMMERCIAL` track. The track fixes both the number of appeal levels and their labels. On the `MEDICARE` track, levels one through five are labeled `REDETERMINATION`, `RECONSIDERATION`, `ALJ`, `COUNCIL`, and `FEDERAL`, and the ladder tops out at `LEVEL_5`. On the `COMMERCIAL` track, levels one through three are labeled `INTERNAL_1`, `INTERNAL_2`, and `EXTERNAL_REVIEW`, and the ladder tops out at `LEVEL_3`.

A newly created payer starts with `status` `ACTIVE`. A `RevenueCycleAdmin` may suspend a payer — moving it from `ACTIVE` to `SUSPENDED` — which blocks the intake of any new audit case for that payer (`ERR_PAYER_SUSPENDED`, §3.2) while leaving existing cases untouched; reactivation returns the payer from `SUSPENDED` to `ACTIVE`. The payer roster can be listed with optional `payer_type` and `status` filters.

The denial taxonomy is administered as issue codes. A `RevenueCycleAdmin` creates each `IssueCode` with a short `code` (such as `MED_NECESSITY`, `AUTH_MISSING`, or `TIMELY_FILING`), a `category` of `CLINICAL` or `TECHNICAL`, and a free-text `description`. The `code` value must be unique across all issue codes; reusing an existing code is rejected with `ERR_DUPLICATE_ISSUE_CODE` (HTTP 409). Every issue code is created with `active` set to true, and the platform offers no deactivation endpoint — a code, once created, remains active permanently. Issue codes can be listed with an optional `category` filter.

### 3.2. Audit Intake and the Records Deadline

An audit case begins when a `HIMCoordinator` — or a `RevenueCycleAdmin` — intakes a payer's audit request, supplying the `payer_id`, the `audit_type` (one of `RAC_COMPLEX`, `RAC_AUTOMATED`, `COMMERCIAL_POSTPAY`, `COMMERCIAL_PREPAY`, or `TARGETED_PROBE`), the `received_at` timestamp recording when the audit request arrived, and optionally the payer's own reference as `external_audit_ref`. Intake is guarded in the order of §2.9: the payer must exist (`ERR_NOT_FOUND`), the payer must be `ACTIVE` (else `ERR_PAYER_SUSPENDED`), and the concurrent-audit capacity check must pass — the system counts the payer's cases whose status is anything other than `CLOSED`, and when that count is already greater than or equal to the payer's `concurrent_audit_cap`, intake is rejected with `ERR_CONCURRENT_AUDIT_CAP` (HTTP 409). The boundary is exact: a payer whose open-case count equals its cap is rejected, while a count one below the cap is allowed.

A successfully intaked case starts in `RECEIVED` with `late_submission` false, all monetary totals at zero, and a computed `records_due_at` equal to `received_at` plus the payer's `records_submission_days` days — an inclusive deadline per §2.8. The intake appends a `CASE_CREATED` event to the case's trail. The case register supports listing with optional `payer_id`, `status`, and `audit_type` filters.

Claim lines are added to the case by a `HIMCoordinator`, each carrying the payer-assigned `claim_number`, the provider's `patient_account_number`, a `service_start_date` and `service_end_date` describing the service interval, and the `billed_amount_cents`. The service interval is half-open — the start date inclusive, the end date exclusive — and the end must be strictly after the start; the billed amount must be positive. Malformed intervals or non-positive amounts fail with `ERR_INVALID_REQUEST` (HTTP 400). Each new line starts in `UNDER_AUDIT` with `denied_amount_cents` at zero, `denial_category` null, `issue_code_id` null, and `auto_denied` false, and records its owning `audit_case_id`.

A cross-case duplicate guard protects claim integrity. Adding a line is rejected with `ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT` (HTTP 409) when another claim line already exists that belongs to a different case of the same payer, whose case is not `CLOSED`, which carries the same `claim_number`, and whose service interval overlaps the new one. Under the half-open convention, overlap means the new start falls before the existing end and the existing start falls before the new end; pure adjacency — a new interval beginning exactly where an existing one ends — is not overlap and is permitted. Lines within the same case are exempt from this check entirely: a case may legitimately hold one line per claim. Every line addition recomputes the case's monetary totals (defined in §3.3). Claim lines can be listed beneath their case, or queried globally with optional `audit_case_id`, `issue_code_id`, and `status` filters.

Records submission is the `HIMCoordinator`'s response to the audit and carries a `manifest_ref` identifying the submitted manifest together with the OCC field `expected_audit_case_version` (§2.7). Its behavior depends on the case's state:

- From `RECEIVED`, an on-time submission — the logical clock reading at or before `records_due_at` — moves the case `RECEIVED → RECORDS_SUBMITTED`, stamps `records_submitted_at` with the current logical time, leaves `late_submission` false, increments the case `version` by one, and appends a `RECORDS_SUBMITTED` event. A submission attempted when the clock has already passed the deadline is not rejected; the case has by then been swept to `MISSED_DEADLINE` and the late path below applies.
- The missed-deadline sweep fires on any clock advance that pushes the logical time past `records_due_at` while the case is still `RECEIVED`. The case moves `RECEIVED → MISSED_DEADLINE`, and every claim line still `UNDER_AUDIT` is auto-denied: it moves to `DENIED` with `denied_amount_cents` set to its full `billed_amount_cents`, `denial_category` set to `TECHNICAL`, `issue_code_id` left null, and `auto_denied` set true. Case totals are recomputed, and two events are appended in order: `CASE_MISSED_DEADLINE`, then `LINES_AUTO_DENIED`.
- A late submission from `MISSED_DEADLINE` is accepted. It stamps `records_submitted_at` with the current logical time and sets `late_submission` true — a sticky flag that never returns to false. Every claim line whose `auto_denied` is true reverts `DENIED → UNDER_AUDIT`, with `denied_amount_cents` reset to zero, `denial_category` cleared to null, and `auto_denied` reset to false; lines denied by an actual payer determination are untouched. Case totals are recomputed, the case `version` increments by one, and a `RECORDS_SUBMITTED` event is appended.
- A manifest amendment from `RECORDS_SUBMITTED` is permitted any number of times. The amendment moves `RECORDS_SUBMITTED → RECORDS_SUBMITTED` and increments the case `version` by one; `records_submitted_at` and `late_submission` are left unchanged, and no event is appended.
- Submissions attempted while the case is `UNDER_PAYER_REVIEW`, `DETERMINATION_ISSUED`, or `CLOSED` are rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Any submission carrying a stale `expected_audit_case_version` is rejected with `ERR_STALE_VERSION` (HTTP 412) regardless of which of these paths would otherwise apply.

### 3.3. Payer Review and Determination

Once records are in, the payer's side of the workflow begins. A `PayerAgent` — whose `X-User-ID` must equal the case's `payer_id`, else the call fails with `ERR_PAYER_MISMATCH` (HTTP 403) — begins the review, moving the case `RECORDS_SUBMITTED → UNDER_PAYER_REVIEW` and appending a `REVIEW_BEGAN` event.

The determination itself is posted by a `PayerAgent` under the same ownership rule. Its payload is `outcomes`, a list with exactly one entry per claim line still `UNDER_AUDIT`; each entry identifies the line by its `claim_line_id`, names an outcome of `PAID_AS_BILLED`, `DENIED`, or `PARTIALLY_DENIED`, and — for the two denial outcomes — carries the denied amount in cents together with the `denial_category` (`CLINICAL` or `TECHNICAL`) and the `issue_code_id` classifying the denial. Three content checks guard the posting, evaluated after ownership and state per §2.9. Coverage: the outcomes must address every `UNDER_AUDIT` line of the case exactly once — a missed or duplicated line is rejected with `ERR_DETERMINATION_INCOMPLETE` (HTTP 422). Belonging: every entry's `claim_line_id` must reference a line of this case, else `ERR_DETERMINATION_LINE_INVALID` (HTTP 422). Amounts: a `DENIED` outcome must deny exactly the line's billed amount, and a `PARTIALLY_DENIED` outcome must carry a denied amount strictly greater than zero and strictly less than the billed amount — violations are rejected with `ERR_DETERMINATION_AMOUNT_INVALID` (HTTP 422).

A posted determination moves each covered line out of `UNDER_AUDIT`: a `PAID_AS_BILLED` outcome leaves the line's `denied_amount_cents` at zero; a `DENIED` outcome sets `denied_amount_cents` to the billed amount with the supplied category and issue; a `PARTIALLY_DENIED` outcome sets `denied_amount_cents` to the outcome's amount with the supplied category and issue. The case stamps `determination_issued_at` with the logical now, recomputes its totals, appends a `DETERMINATION_ISSUED` event, and moves `UNDER_PAYER_REVIEW → DETERMINATION_ISSUED`.

Five computed totals on the audit case track its financial posture, recomputed after every claim-line mutation — determination, auto-denial, late-submission revert, appeal decision, or finalization:

- `total_billed_cents` is the sum of `billed_amount_cents` over all lines of the case.
- `total_denied_active_cents` is the sum of `denied_amount_cents` over lines in `DENIED` or `PARTIALLY_DENIED` — the currently contested dollars.
- `total_final_denied_cents` is the sum of `denied_amount_cents` over lines in `FINAL` — denials whose appeal windows have closed.
- `total_upheld_cents` is the sum, over lines in `PAID_AS_BILLED`, `DENIED`, `PARTIALLY_DENIED`, `OVERTURNED`, or `FINAL`, of each line's billed amount minus its denied amount.
- `total_overturned_cents` is a cumulative, increment-only measure of denied cents reversed by appeal decisions; each line that is overturned contributes the denied amount it carried at decision time.

The platform maintains the conservation invariant that `total_billed_cents` equals the sum of `total_upheld_cents`, `total_denied_active_cents`, and `total_final_denied_cents`.

### 3.4. The Appeal Ladder: Opening, Filing, and Withdrawing Appeals

Appeals are the provider's instrument against denials, opened by an `AppealsSpecialist` against an individual claim line with an optional free-text `notes` field. Two gates guard creation. The line must currently be `DENIED` or `PARTIALLY_DENIED`, and no other appeal of the same line may be sitting in `DRAFT` or `PENDING_DECISION`; either violation is rejected with `ERR_LINE_NOT_APPEALABLE` (HTTP 409).

The ladder structure is derived, never chosen by the caller. The first appeal on a line opens at `LEVEL_1` with `prior_appeal_id` null. Each subsequent appeal opens at the previous appeal's level plus one, with `prior_appeal_id` referencing the appeal at the previous level whose decision opened this one. Opening the next level requires that prior appeal to be in a decided state — `DECIDED_FAVORABLE`, `DECIDED_PARTIAL`, or `DECIDED_UNFAVORABLE` — and requires the next level to exist within the payer's track: the `MEDICARE` track reaches `LEVEL_5`, while the `COMMERCIAL` track ends at `LEVEL_3`. Asking for a level beyond the track maximum, or for the next level while the prior appeal is undecided, is rejected with `ERR_APPEAL_LEVEL_NOT_AVAILABLE` (HTTP 409). The appeal's `level_label` is derived from the payer's `appeal_track`: on `MEDICARE`, `LEVEL_1` through `LEVEL_5` map to `REDETERMINATION`, `RECONSIDERATION`, `ALJ`, `COUNCIL`, and `FEDERAL`; on `COMMERCIAL`, `LEVEL_1` through `LEVEL_3` map to `INTERNAL_1`, `INTERNAL_2`, and `EXTERNAL_REVIEW`. At creation the appeal snapshots the line's current `denied_amount_cents` into `appealed_denied_cents`, opens in `DRAFT`, and records both `audit_claim_line_id` and the denormalized `audit_case_id` so appeals can be filtered at the case level.

Every appeal carries a computed `filed_deadline_at`, inclusive per §2.8. A `LEVEL_1` appeal's deadline is the case's `determination_issued_at` plus the payer's `l1_deadline_days` days. A `LEVEL_2` appeal's deadline is the prior appeal's `decided_at` plus `l2_deadline_days` days. A `LEVEL_3` appeal's deadline is the prior appeal's `decided_at` plus `l3_deadline_days` days on the `MEDICARE` track, or plus `external_review_deadline_days` days on the `COMMERCIAL` track. `LEVEL_4` and `LEVEL_5`, which exist only on `MEDICARE`, add `l4_deadline_days` and `l5_deadline_days` days respectively to the prior appeal's `decided_at`.

Filing is performed by an `AppealsSpecialist`. When the logical clock reads at or before `filed_deadline_at`, filing moves the appeal `DRAFT → PENDING_DECISION` and stamps `filed_at` with the logical now. A `LEVEL_3` filing — `ALJ` on the Medicare track, `EXTERNAL_REVIEW` on the commercial track — additionally requires the appeal's evidence packet to exist in `READY` or `SUBMITTED` status; filing a third-level appeal without a ready packet is rejected with `ERR_EVIDENCE_PACKET_NOT_READY` (HTTP 409). Filing has a monetary side effect: when the filed appeal's `level` is among the payer's `hold_levels`, every recoupment demand of the case currently `DEMANDED` or `PARTIALLY_RECOUPED` moves to `ON_HOLD` with `hold_started_at` stamped (§3.7).

When the clock has passed `filed_deadline_at`, the filing attempt is rejected with `ERR_APPEAL_DEADLINE_PASSED` (HTTP 409) — and the attempt itself moves the appeal `DRAFT → EXPIRED`. Expiry is lazy by design: no clock sweep expires appeals, a stale draft remains `DRAFT` until someone tries to file it, and such a stale draft blocks neither claim-line finalization nor case closure, because those predicates consider only `PENDING_DECISION` appeals and `DRAFT` appeals whose `filed_deadline_at` is still at or after the logical now.

An `AppealsSpecialist` may also withdraw an appeal. From `DRAFT`, withdrawal moves `DRAFT → WITHDRAWN` with no further effect. From `PENDING_DECISION`, withdrawal moves `PENDING_DECISION → WITHDRAWN` and releases the recoupment hold the filing created (§3.7). `DECIDED_FAVORABLE`, `DECIDED_PARTIAL`, `DECIDED_UNFAVORABLE`, `WITHDRAWN`, and `EXPIRED` are all terminal. The appeal register lists appeals with optional `audit_case_id`, `claim_line_id`, `prior_appeal_id`, `status`, and `level` filters.

### 3.5. Appeal Decisions, Claim-Line Outcomes, and Finalization

Decisions on pending appeals are posted by a `PayerAgent` acting for the payer that owns the appeal's case — an `X-User-ID` that does not match that payer is rejected with `ERR_PAYER_MISMATCH` (HTTP 403), and an appeal not in `PENDING_DECISION` is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The decision payload carries an `outcome` and an `upheld_cents` figure, and the two must agree:

- An `outcome` of `FAVORABLE` requires `upheld_cents` to be exactly zero. The appeal lands `DECIDED_FAVORABLE`; the claim line moves to `OVERTURNED`; the line's `denied_amount_cents` is added to the case's `total_overturned_cents` and then zeroed.
- An `outcome` of `PARTIAL` requires `upheld_cents` strictly greater than zero and strictly less than the appeal's `appealed_denied_cents`. The appeal lands `DECIDED_PARTIAL`; the difference between the line's `denied_amount_cents` and `upheld_cents` is added to `total_overturned_cents`, and the line's `denied_amount_cents` is set to `upheld_cents`. The line itself remains `DENIED` or `PARTIALLY_DENIED` — a partial decision never overturns a line outright.
- An `outcome` of `UNFAVORABLE` requires `upheld_cents` exactly equal to the appeal's `appealed_denied_cents`. The appeal lands `DECIDED_UNFAVORABLE`, and the line's denied amount is unchanged.

Any other pairing of outcome and amount is rejected with `ERR_DETERMINATION_AMOUNT_INVALID` (HTTP 422). All three successful decisions stamp `decided_at` with the logical now, release any `ON_HOLD` recoupment demands of the case exactly as a withdrawal does (§3.7), and trigger a recompute of the case totals.

A full-vindication cascade watches every decision. When a decision leaves the case's `total_denied_active_cents` at zero, every recoupment demand of the case in `DEMANDED`, `ON_HOLD`, `PARTIALLY_RECOUPED`, or `FULLY_RECOUPED` moves to `REVERSED` — the last of these modeling a post-recoupment refund. Each reversed demand's `APPLIED` offsets move to `REVERSED` with `reversed_at` stamped; each reversed offset credits its `amount_cents` back to its remittance's `available_cents` with the remittance's status recomputed; and each reversed demand's `outstanding_principal_cents` is restored to its `principal_cents` minus any `written_off_cents`.

Independently of decisions, the claim-line finalization sweep runs on every clock advance. A line in `DENIED` or `PARTIALLY_DENIED` moves to `FINAL` once its next appeal window has closed — concretely, when no appeal of the line is `PENDING_DECISION`, no `DRAFT` appeal of the line has a `filed_deadline_at` still at or after the logical now, and the logical now is past the `filed_deadline_at` the next appeal level would carry. Finalization recomputes the case's `total_final_denied_cents`. Because the predicate ignores drafts whose deadlines have already passed, a stale draft appeal never holds a line hostage. `PAID_AS_BILLED`, `OVERTURNED`, and `FINAL` are the terminal states of a claim line.

### 3.6. Evidence Packets and Level-Three Readiness

Third-level appeals — an `ALJ` hearing on the Medicare track or an `EXTERNAL_REVIEW` on the commercial track — demand a documented evidentiary record. An `AppealsSpecialist` creates the appeal's evidence packet; the relationship is strictly one packet per appeal, recorded through the packet's `appeal_id`, and a second creation attempt against the same appeal is rejected with `ERR_PACKET_ALREADY_EXISTS` (HTTP 409). A new packet starts in `ASSEMBLING`, and its readiness is evaluated immediately: with no required items yet, the required set is empty and the packet is `READY` at creation by vacuous truth.

Checklist items are added to the packet by an `AppealsSpecialist`, each with an `item_type` of `MEDICAL_RECORD`, `PHYSICIAN_LETTER`, `POLICY_CITATION`, `EXPERT_REVIEW`, or `PRIOR_AUTH_DOC`, and an optional `required` flag that defaults to true when omitted. Each item records its owning `evidence_packet_id` and starts in `PENDING`. Readiness is recomputed after every item mutation: the packet is `READY` exactly when every item with `required` true is in `ATTACHED` or `WAIVED`, and whenever a required item enters `PENDING` — newly added or detached — a `READY` packet reverts to `ASSEMBLING`. Once a packet is `SUBMITTED` it is sealed: creating items on it, or mutating any of its items, is rejected with `ERR_PACKET_IMMUTABLE` (HTTP 409).

Three item actions drive the checklist. An `AppealsSpecialist` attaches a document by supplying its `document_ref`, moving the item `PENDING → ATTACHED` and recording the reference. A `DepartmentDirector` may waive a pending item, moving it `PENDING → WAIVED` — director authority is required precisely because waiving lowers the evidentiary bar. An `AppealsSpecialist` may detach a previously attached document, returning the item `ATTACHED → PENDING` and clearing its `document_ref` to null; if the item is required, the packet's readiness reverts as described above. `ATTACHED` and `WAIVED` are the terminal states of an item.

Submission is performed by an `AppealsSpecialist` and requires the packet to be `READY` and the owning appeal to be in `DRAFT` or `PENDING_DECISION` — any other appeal state is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Submission moves the packet `READY → SUBMITTED` and stamps `submitted_at` with the logical now; `SUBMITTED` is terminal for the packet. Reading an appeal's packet returns a collection containing zero or one element, and a packet's items are listed beneath the packet.

### 3.7. Recoupment Demands and Interest Accrual

When a determination upholds denials, the payer claws the money back through recoupment demands. A `PayerAgent` issues a demand against a case — with the usual ownership rule against the case's payer — supplying the `principal_cents` demanded and, optionally, the `issued_at` timestamp, which defaults to the current logical clock reading when omitted. The principal must be positive (`ERR_INVALID_REQUEST`) and may not exceed the case's `total_denied_active_cents`; a demand that overreaches the actively denied dollars is rejected with `ERR_DEMAND_EXCEEDS_DENIED` (HTTP 409).

At creation the demand snapshots the payer's interest policy: `rate_bps_tier1_snapshot`, `rate_bps_tier2_snapshot`, and `interest_cap_pct_snapshot` are captured from the payer's `interest_rate_bps_tier1`, `interest_rate_bps_tier2`, and `interest_cap_pct`, so later edits to the payer's policy never retroactively reprice an issued demand. The demand opens in `DEMANDED` with its `payer_id` denormalized from the case, `written_off_cents` at zero, `accumulated_hold_seconds` at zero, and `hold_started_at` null, and a `DEMAND_CREATED` event is appended to the case trail. Two figures are derived rather than stored directly: `outstanding_principal_cents` is the `principal_cents` minus the principal portions of all `APPLIED` offsets minus `written_off_cents`, and `accrued_interest_cents` is recomputed from live state on every read of the demand and on every allocation that touches it. The demand register supports listing with optional `payer_id` and `status` filters.

Interest accrues on outstanding principal in thirty-day periods, on the portion of elapsed time the demand was not on hold. The eligible time is the interval from `issued_at` to the logical now, minus the `accumulated_hold_seconds` already banked, minus — while a hold is currently open — the interval from `hold_started_at` to now. The number of elapsed periods is the count of whole thirty-day periods inside the eligible time; a partial period counts for nothing, and zero periods means zero interest. When at least one period has elapsed, the raw interest is the outstanding principal multiplied by the summed per-period charge — the tier-one snapshot rate applied once for each of the first two periods, and the tier-two snapshot rate applied once for each period beyond the second — divided by ten thousand. That raw figure is then capped: the cap is the at-issue principal — the `principal_cents` recorded at creation, before any later adjustment — multiplied by the `interest_cap_pct_snapshot` and divided by one hundred, and the accrued interest is the smaller of the raw figure and the cap, rounded half up to whole cents.

Payment holds couple the appeal ladder to recoupment. When an appeal whose `level` appears in the payer's `hold_levels` reaches `PENDING_DECISION`, every demand of the case in `DEMANDED` or `PARTIALLY_RECOUPED` moves to `ON_HOLD` with `hold_started_at` stamped at the logical now. When that holding appeal is subsequently decided or withdrawn, each held demand returns to `DEMANDED` if it has no `APPLIED` offsets, or to `PARTIALLY_RECOUPED` if it has some; the just-ended hold interval is added into `accumulated_hold_seconds`; and `hold_started_at` is cleared to null. Because hold intervals are excluded from eligible time, a demand accrues no interest while its collection is frozen by a live appeal.

A `PayerAgent` may adjust a demand's principal in place — ownership is checked against the demand's `payer_id` — while the demand is `DEMANDED` or `PARTIALLY_RECOUPED`; adjustments against any other status are rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). The adjustment carries `new_principal_cents` and the OCC field `expected_recoupment_demand_version` (§2.7). The new principal must remain at or above the principal already consumed by `APPLIED` offsets and at or below the case's `total_denied_active_cents`; a violation either way is rejected with `ERR_DEMAND_EXCEEDS_DENIED` (HTTP 409). A successful adjustment recomputes `outstanding_principal_cents` and increments the demand's `version` by one; it never changes the demand's status.

Writing off a demand is available to a `PFSAccountant` or a `DepartmentDirector` while the demand is `DEMANDED` or `PARTIALLY_RECOUPED`, and is blocked while any appeal of the case is in `DRAFT` or `PENDING_DECISION` — rejected with `ERR_OPEN_APPEALS_EXIST` (HTTP 409). Note the asymmetry with case closure: here even a stale draft past its filing deadline blocks the write-off. The write-off sets `written_off_cents` to the outstanding principal, drives `outstanding_principal_cents` to zero, and lands the demand in `WRITTEN_OFF`.

Offsets drive demand status automatically. An applied offset that covers some but not all of what is owed moves `DEMANDED → PARTIALLY_RECOUPED`. One that drives the outstanding principal to zero — which, because interest is always satisfied before principal, means the accrued interest was covered in full at the same time — moves `DEMANDED` or `PARTIALLY_RECOUPED → FULLY_RECOUPED`. `REVERSED` and `WRITTEN_OFF` are terminal.

### 3.8. Remittances, Offsets, and the Allocation Waterfall

Payer remittances are the funds against which recoupment offsets draw. A `PayerAgent` registers a remittance with a `payer_id` — which must equal the caller's `X-User-ID`, else `ERR_PAYER_MISMATCH` (HTTP 403) — a positive `gross_amount_cents`, and an optional `external_ref` for the payer's own reference. A remittance's `available_cents` is derived as its gross amount minus the amounts of all `APPLIED` offsets drawn on it, and its status follows from that figure: equal to the gross amount means `RECEIVED`, exactly zero means `FULLY_ALLOCATED`, and anything in between means `PARTIALLY_ALLOCATED`. Reversals flow backward through the same derivation: a `FULLY_ALLOCATED` remittance whose offset is reversed returns to `PARTIALLY_ALLOCATED`, and a `PARTIALLY_ALLOCATED` remittance restored to its full gross returns to `RECEIVED`. Remittances can be listed with optional `payer_id` and `status` filters.

A `PFSAccountant` may direct a manual, targeted offset against a specific demand, naming the funding `remittance_id` and the `amount_cents` to apply. Three linkage and ceiling checks guard it, after the usual existence and state tiers: the remittance and the demand must belong to the same payer, else `ERR_CROSS_PAYER_ALLOCATION` (HTTP 409); the demand must be `DEMANDED` or `PARTIALLY_RECOUPED` — an `ON_HOLD` demand is rejected with the specialized `ERR_DEMAND_ON_HOLD` (HTTP 409) and any other status with `ERR_INVALID_STATE_TRANSITION`; and the amount may not exceed the smaller of the remittance's `available_cents` and the demand's outstanding principal plus its accrued interest, else `ERR_OFFSET_EXCEEDS_OUTSTANDING` (HTTP 409). Application is interest-first: `interest_portion_cents` takes as much of the amount as the demand's currently accrued interest requires, and `principal_portion_cents` takes the remainder up to the outstanding principal; the offset's `amount_cents` equals the sum of the two portions. The created offset records its `remittance_id` and `recoupment_demand_id`, carries `allocation_mode` `MANUAL`, starts `APPLIED` with `applied_at` stamped at the logical now, and triggers recomputation of the demand, the remittance, and an `OFFSET_APPLIED` event on the case trail.

The automatic waterfall lets a `PFSAccountant` spread a remittance across everything the payer owes. Candidate demands are those of the same payer in `DEMANDED` or `PARTIALLY_RECOUPED` — `ON_HOLD` demands are excluded — visited in `issued_at` ascending order with `created_at` ascending as the tie-break. Starting from a remainder equal to the remittance's `available_cents`, the waterfall visits each candidate while funds remain: it computes the demand's accrued interest and rounds it half up to whole cents for that demand before any portions are calculated; the interest portion takes the smaller of the remaining funds and that interest figure; the principal portion then takes the smaller of what is left and the demand's outstanding principal; and whenever the combined application is positive, an `APPLIED` offset with `allocation_mode` `AUTO_WATERFALL` is created and the remainder is reduced by the applied amount. The rounding order is pinned: raw fractional interest is never summed across demands and rounded once. Two demands each accruing a raw three hundred thirty-three and a third cents therefore contribute three hundred thirty-three cents each — six hundred sixty-six cents of interest in total, not six hundred sixty-seven. The waterfall returns the offsets it created; affected demands and the remittance are recomputed, and `OFFSET_APPLIED` events are appended.

Reversal unwinds an offset. A `PFSAccountant` — or the system itself, inside the full-vindication cascade of §3.5 — moves an `APPLIED` offset to `REVERSED`, its terminal state, stamping `reversed_at` with the logical now. The demand's `outstanding_principal_cents` is increased by the offset's `principal_portion_cents` and its status recomputed: reversed offsets are never counted, so a `FULLY_RECOUPED` demand falls back to `PARTIALLY_RECOUPED` or `DEMANDED` as the arithmetic dictates. The remittance's `available_cents` is increased by the offset's `amount_cents` and its status recomputed by the same derivation. An `OFFSET_REVERSED` event is appended to the case trail. Offsets are listable both per remittance and per demand.

### 3.9. Exposure Analytics, Case Closure, and Corrective Action Plans

The exposure read on a case is recomputed from live state on every call and answers four values: `gross_dollars_at_risk_cents`, `net_exposure_cents`, the case's `late_submission` flag, and `snapshot_quarter_start`, which identifies the snapshot window used for the net figure. Each claim line contributes an at-risk amount: its `denied_amount_cents` when the line is `DENIED`, `PARTIALLY_DENIED`, or `FINAL`; its full `billed_amount_cents` when the line is still `UNDER_AUDIT` on a case whose `late_submission` is true (a late records submission puts the entire billed value in jeopardy); and zero in every other case.

The GROSS variant is the unweighted sum of those at-risk amounts — the full contractual exposure. The NET variant applies a frozen vindication discount: each line's contribution is its at-risk amount multiplied by ten thousand minus the line's overturn basis points, divided by ten thousand, with each line rounded half up to whole cents before the summation. A line's overturn basis points come from a frozen snapshot: the dollar-weighted success rate described below, computed over appeals decided in the prior completed calendar quarter relative to the logical now, grouped by the case's payer and the line's issue code. Lines whose `issue_code_id` is null — auto-denied lines, for instance — and payer-issue groups with zero decided appeals in the snapshot window both fall back to a default of five thousand basis points, i.e. a fifty percent assumed overturn rate. Decisions from the current quarter never feed the snapshot, which keeps the exposure figure stable within a quarter and breaks the circularity between today's decisions and today's exposure.

The success-rate analytics themselves are served as `rows` grouped by payer and issue code. Optional filters narrow the set: `payer_id`, `issue_code_id`, and a decision window given by `from` and `to`. The window's lower bound is inclusive and its upper bound exclusive; either bound may be omitted to leave that side unbounded; supplying both with `from` not strictly before `to` is rejected with `ERR_ANALYTICS_WINDOW_INVALID` (HTTP 422), a check evaluated immediately after generic body validation (§2.9). Only decided appeals enter the calculation — `DECIDED_FAVORABLE`, `DECIDED_PARTIAL`, and `DECIDED_UNFAVORABLE`; `WITHDRAWN` and `EXPIRED` appeals are excluded. Appeals on lines whose `issue_code_id` is null form the null-issue group, which is omitted entirely when an `issue_code_id` filter is supplied, and any group with zero decided appeals is omitted from the response. Two variants are offered through the `variant` parameter. `SIMPLE`, the default when `variant` is omitted, counts appeals: the group's success rate in basis points is ten thousand times the count of favorable decisions plus one half the count of partial decisions, divided by the count of decided appeals, rounded half up to integer basis points. `DOLLAR_WEIGHTED` weights by recovered money: ten thousand times the sum over the group's decided appeals of `appealed_denied_cents` minus `upheld_cents`, divided by the sum of `appealed_denied_cents`, rounded half up to integer basis points. The two variants diverge whenever decided appeals carry heterogeneous denied amounts.

Case closure is the terminal act of the audit workflow, moving `DETERMINATION_ISSUED → CLOSED`, and is open to a `DepartmentDirector` or a `HIMCoordinator` subject to an authority gradient. Three resolution conditions must all hold, each enforced with `ERR_OPEN_APPEALS_EXIST` (HTTP 409): every claim line of the case must be in a terminal state — `PAID_AS_BILLED`, `OVERTURNED`, or `FINAL`; no appeal of the case may be `PENDING_DECISION`, and no `DRAFT` appeal whose `filed_deadline_at` is still at or after the logical now may exist (a stale draft past its deadline does not block closure); and every recoupment demand of the case must be `FULLY_RECOUPED`, `REVERSED`, or `WRITTEN_OFF`. On top of these, when the case's `net_exposure_cents` is at or above two million five hundred thousand cents — twenty-five thousand dollars — only a `DepartmentDirector` may perform the closure; a coordinator attempting it is rejected with `ERR_REQUIRES_DIRECTOR` (HTTP 403). A successful closure stamps `closed_at` with the logical now and appends a `CASE_CLOSED` event. `CLOSED` is the terminal state of an audit case.

Corrective action plans close the loop on the denial patterns the analytics surface. A `ComplianceOfficer` proposes a plan against a payer-issue root cause, supplying `payer_id`, `issue_code_id`, a `title`, and the `root_cause` narrative; the plan opens in `PROPOSED` with `proposed_by_user_id` set to the creator's `X-User-ID` and `cycle_count` at zero. A `DepartmentDirector` activates it, moving `PROPOSED → ACTIVE`. A `ComplianceOfficer` then begins the effectiveness check, moving `ACTIVE → EFFECTIVENESS_CHECK` and stamping `check_started_at` with the logical now; the plan rests in `EFFECTIVENESS_CHECK` while the window runs. Judgment belongs to an `InternalAuditor`, under two safeguards: segregation of duties forbids the plan's proposer from verifying it — a verifier whose `X-User-ID` equals the plan's `proposed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — and the effectiveness window must have elapsed, meaning the logical now must be at least fourteen days past `check_started_at`, else `ERR_CAP_WINDOW_NOT_ELAPSED` (HTTP 409). Verification moves the plan to `VERIFIED` and records the verifier in `verified_by_user_id`. Marking the plan ineffective instead increments `cycle_count` and loops the plan back to `ACTIVE` with `check_started_at` cleared to null — unless that increment brings `cycle_count` to three, the platform's maximum number of correction cycles, in which case the plan moves to `FAILED`. Both `VERIFIED` and `FAILED` are terminal. Plans can be listed with optional `payer_id`, `issue_code_id`, and `status` filters.

## 4. Endpoint Definitions

Operations that create a new resource — a payer, an issue code, an audit case, a claim line, an appeal, an evidence packet or packet item, a recoupment demand, a remittance, an offset transaction, or a corrective action plan — return `201 Created`. Operations that modify an existing resource without creating a new one — state transitions, submissions, determinations, decisions, adjustments, reversals, clock control — return `200 OK`. Request and response payloads for every endpoint follow §2 and the business rules of §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock; evaluates missed-deadline, auto-denial, and finalization sweeps | RevenueCycleAdmin |
| POST | `/payers` | Create a payer | RevenueCycleAdmin |
| GET | `/payers` | List payers | Any |
| GET | `/payers/{id}` | Get a payer | Any |
| POST | `/payers/{id}/suspend` | Suspend a payer (blocks new audit cases) | RevenueCycleAdmin |
| POST | `/payers/{id}/reactivate` | Reactivate a suspended payer | RevenueCycleAdmin |
| POST | `/issue-codes` | Create a denial issue code (clinical/technical taxonomy) | RevenueCycleAdmin |
| GET | `/issue-codes` | List issue codes | Any |
| GET | `/issue-codes/{id}` | Get an issue code | Any |
| POST | `/audit-cases` | Intake a payer audit request | HIMCoordinator, RevenueCycleAdmin |
| GET | `/audit-cases` | List audit cases | Any |
| GET | `/audit-cases/{id}` | Get an audit case | Any |
| POST | `/audit-cases/{id}/claim-lines` | Add a claim line under audit | HIMCoordinator |
| GET | `/audit-cases/{id}/claim-lines` | List claim lines of a case | Any |
| GET | `/claim-lines/{id}` | Get a claim line | Any |
| GET | `/claim-lines` | List claim lines (filtered) | Any |
| POST | `/audit-cases/{id}/records-submissions` | Submit or amend the records manifest; OCC-guarded; late submissions accepted | HIMCoordinator |
| POST | `/audit-cases/{id}/begin-payer-review` | Payer begins review after records submission | PayerAgent |
| POST | `/audit-cases/{id}/determination` | Payer posts per-line determination outcomes | PayerAgent |
| POST | `/audit-cases/{id}/close` | Close a fully-resolved audit case | DepartmentDirector, HIMCoordinator |
| GET | `/audit-cases/{id}/events` | Append-only audit trail of the case | Any |
| GET | `/audit-cases/{id}/exposure` | Computed GROSS and NET dollars at risk | Any |
| POST | `/claim-lines/{id}/appeals` | Open the next appeal level for a denied line | AppealsSpecialist |
| GET | `/claim-lines/{id}/appeals` | List appeals of a claim line | Any |
| GET | `/appeals` | List appeals (filtered) | Any |
| GET | `/appeals/{id}` | Get an appeal | Any |
| POST | `/appeals/{id}/file` | File an appeal (deadline-inclusive; LEVEL_3 requires a READY/SUBMITTED packet) | AppealsSpecialist |
| POST | `/appeals/{id}/withdraw` | Withdraw an appeal | AppealsSpecialist |
| POST | `/appeals/{id}/decision` | Payer posts the appeal decision | PayerAgent |
| POST | `/appeals/{id}/evidence-packet` | Create the LEVEL_3 evidence packet for an appeal (1:1) | AppealsSpecialist |
| GET | `/appeals/{id}/evidence-packet` | Get the packet of an appeal (0 or 1 element) | Any |
| GET | `/evidence-packets/{id}` | Get a packet | Any |
| POST | `/evidence-packets/{id}/items` | Add a checklist item to the packet | AppealsSpecialist |
| GET | `/evidence-packets/{id}/items` | List packet items | Any |
| POST | `/evidence-packets/{id}/items/{itemId}/attach` | Attach a document to a pending item | AppealsSpecialist |
| POST | `/evidence-packets/{id}/items/{itemId}/waive` | Waive a pending required item (director authority) | DepartmentDirector |
| POST | `/evidence-packets/{id}/items/{itemId}/detach` | Detach a document (returns the item to PENDING) | AppealsSpecialist |
| POST | `/evidence-packets/{id}/submit` | Submit a READY packet | AppealsSpecialist |
| POST | `/audit-cases/{id}/recoupment-demands` | Payer issues an overpayment recoupment demand | PayerAgent |
| GET | `/audit-cases/{id}/recoupment-demands` | List demands of a case | Any |
| GET | `/recoupment-demands` | List demands (filtered) | Any |
| GET | `/recoupment-demands/{id}` | Get a demand (accrued interest recomputed on read) | Any |
| POST | `/recoupment-demands/{id}/adjustments` | Adjust demand principal (OCC-guarded; allowed while DEMANDED or PARTIALLY_RECOUPED) | PayerAgent |
| POST | `/recoupment-demands/{id}/write-off` | Write off the outstanding principal | PFSAccountant, DepartmentDirector |
| POST | `/recoupment-demands/{id}/offsets` | Manual targeted offset allocation from a specific remittance | PFSAccountant |
| POST | `/remittances` | Register a payer remittance available for offset | PayerAgent |
| GET | `/remittances` | List remittances (filtered) | Any |
| GET | `/remittances/{id}` | Get a remittance | Any |
| POST | `/remittances/{id}/allocate` | Auto-waterfall allocation across the payer's eligible demands | PFSAccountant |
| GET | `/remittances/{id}/offset-transactions` | List offsets drawn on a remittance | Any |
| GET | `/recoupment-demands/{id}/offset-transactions` | List offsets applied to a demand | Any |
| POST | `/offset-transactions/{id}/reverse` | Reverse an applied offset | PFSAccountant |
| POST | `/corrective-action-plans` | Propose a corrective action plan for a payer-issue root cause | ComplianceOfficer |
| GET | `/corrective-action-plans` | List corrective action plans | Any |
| GET | `/corrective-action-plans/{id}` | Get a corrective action plan | Any |
| POST | `/corrective-action-plans/{id}/activate` | Activate a proposed plan | DepartmentDirector |
| POST | `/corrective-action-plans/{id}/begin-effectiveness-check` | Begin the effectiveness-check window | ComplianceOfficer |
| POST | `/corrective-action-plans/{id}/verify` | Verify plan effectiveness (segregation of duties enforced) | InternalAuditor |
| POST | `/corrective-action-plans/{id}/mark-ineffective` | Mark the plan ineffective (loops back to ACTIVE, or FAILED at the cycle limit) | InternalAuditor |
| GET | `/analytics/success-rates` | Overturn success-rate analytics grouped by payer and issue code; SIMPLE or DOLLAR_WEIGHTED variant | Any |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier the API can return. The conditions that trigger each error are defined in the narratives of §2 and §3; this table is the canonical mapping from identifier to HTTP status.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ANALYTICS_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_PAYER_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_REQUIRES_DIRECTOR` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CAP_WINDOW_NOT_ELAPSED` | 409 Conflict |
| `ERR_APPEAL_DEADLINE_PASSED` | 409 Conflict |
| `ERR_PAYER_SUSPENDED` | 409 Conflict |
| `ERR_DUPLICATE_ISSUE_CODE` | 409 Conflict |
| `ERR_CONCURRENT_AUDIT_CAP` | 409 Conflict |
| `ERR_DUPLICATE_CLAIM_IN_OPEN_AUDIT` | 409 Conflict |
| `ERR_LINE_NOT_APPEALABLE` | 409 Conflict |
| `ERR_APPEAL_LEVEL_NOT_AVAILABLE` | 409 Conflict |
| `ERR_EVIDENCE_PACKET_NOT_READY` | 409 Conflict |
| `ERR_PACKET_ALREADY_EXISTS` | 409 Conflict |
| `ERR_PACKET_IMMUTABLE` | 409 Conflict |
| `ERR_OPEN_APPEALS_EXIST` | 409 Conflict |
| `ERR_CROSS_PAYER_ALLOCATION` | 409 Conflict |
| `ERR_DEMAND_ON_HOLD` | 409 Conflict |
| `ERR_DEMAND_EXCEEDS_DENIED` | 409 Conflict |
| `ERR_OFFSET_EXCEEDS_OUTSTANDING` | 409 Conflict |
| `ERR_DETERMINATION_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_DETERMINATION_LINE_INVALID` | 422 Unprocessable Entity |
| `ERR_DETERMINATION_AMOUNT_INVALID` | 422 Unprocessable Entity |

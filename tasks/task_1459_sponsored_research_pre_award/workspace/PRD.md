# Sponsored Research Pre-Award API — Product Requirements Document

## 1. Introduction

A university Office of Sponsored Programs (OSP) lives in the space between a funding announcement and a signed award: opportunities must be intake-checked, budgets built under the correct facilities-and-administrative (F&A) rate, cost-share pledges gathered and approved, ancillary compliance reviews cleared, and the finished proposal submitted to the sponsor portal before an unforgiving internal deadline. After submission the work is not over — sponsors issue just-in-time requests, negotiate award amounts and rates, and the office must verify everything one final time before handing the award to the post-award setup team. This document specifies the Sponsored Research Pre-Award API, the system of record for that entire pipeline.

The design reflects two realities of pre-award administration. First, segregation of duties is not optional: the analyst who routes a proposal may not approve it institutionally, and the staff member who pledges cost-share may not approve their own pledge. Second, the record must be auditable and replayable — budgets are frozen into immutable snapshots, negotiation rounds supersede one another in the open, and a deterministic logical clock drives every deadline, expiry, and sweep so that compliance outcomes can be reconstructed exactly. Seven distinct operator roles share the read surface but hold disjoint write powers, and every mutation is versioned so that stale writers are refused rather than silently overwriting work they never observed.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. All resources are mounted under the `/pre-award` prefix.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `PI`, `PreAwardAnalyst`, `DepartmentChair`, `ComplianceOfficer`, `SubrecipientManager`, `OSPDirector`, and `OSPSystemAdmin`. A request with either header missing, or whose role value is not one of these seven, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). When the role is valid but not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Role identity is resolved in two ways. When `X-User-Role` is `PI`, `X-User-ID` is the `id` of the acting `PrincipalInvestigator`; ownership checks on any resource that references a `PrincipalInvestigator` compare the resource's `pi_id` field to `X-User-ID`. A PI may therefore only create proposals whose `pi_id` equals their own `X-User-ID`, and may only edit, respond on, or withdraw proposals they own — an ownership failure on an existing resource is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403) rather than the generic permission error. When `X-User-Role` is `PreAwardAnalyst`, `DepartmentChair`, `ComplianceOfficer`, `SubrecipientManager`, `OSPDirector`, or `OSPSystemAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `routed_by_user_id` on a proposal at routing time, `committed_by_user_id` on a cost-share pledge, or `approved_by_user_id` on an approved commitment) but does not compare it to any entity's `id`.

All seven roles share read access: every GET endpoint in this document is available to any authenticated role. Write operations are restricted per endpoint as described in §3 and summarized in §4.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Internal Deadline

All time-sensitive behavior — deadlines, review expirations, sweeps, recorded timestamps — is evaluated against a deterministic logical clock, never against wall-clock time. Before any administrative intervention, the logical clock reads exactly 2026-08-01T00:00:00Z. An `OSPSystemAdmin` may advance it through a test-driving capability that accepts a `to_iso8601` instant in its payload and answers with the resulting `current_utc`. Setting the clock fires the intake-closure and review-expiry sweeps described in §3.1 and §3.6, so a single clock call can transition many records at once.

Every funding opportunity derives its `internal_deadline_at` by subtracting `internal_lead_days` — five days unless the intake payload supplies a different count — from `sponsor_deadline_at`, using exact datetime arithmetic at second precision on ISO 8601 UTC values. Portal submission is permitted while the logical clock is at or before `internal_deadline_at`; a submission landing exactly on the deadline instant is allowed. A submission attempted after that instant is refused with `ERR_INTERNAL_DEADLINE_PASSED` (HTTP 422). The intake-closure sweep closes an opportunity strictly after its internal deadline — that is, once the internal deadline falls before the current logical time.

### 2.5. Common Resource Properties

All primary resources — FundingOpportunity, PrincipalInvestigator, Proposal, BudgetLine, BudgetSnapshot, FaRateAgreement, CostShareCommitment, ComplianceReview, SubrecipientOrg, SubrecipientCommitment, NegotiationOffer, and AwardHandoff — share one set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification, including modifications caused by cascading side effects rather than a direct client write.

The SubmissionPackage is the sole exception: it is created once and never mutated, so it carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

### 2.6. Money, Rates, and Rounding Discipline

All monetary quantities are carried as integer cents — line `amount_cents`, commitment `amount_cents`, `subaward_amount_cents`, `offered_total_cents`, and every computed total. Indirect cost is rounded half up to whole cents **per budget line first**, and only then are the per-line results summed into the proposal's indirect total; summing unrounded products and rounding once at the end yields a different number and is not the specification. The same round-half-up convention applies at each rounding step of the cost-share adequacy computation in §3.4. Effort percentages such as `pi_effort_pct` are compared at two-decimal precision, and rate figures (`rate_pct`, `fa_rate_cap_pct`, `offered_fa_rate_pct`, and their computed counterparts) are carried as percent numbers — a value of 54.5 means 54.5 percent.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control: finalizing a proposal's budget, and opening a negotiation round on a proposal. Each requires the request body to carry `expected_proposal_version`, a non-optional field holding the proposal `version` the client last observed. When the supplied value does not equal the proposal's current `version` — because some other accepted write has advanced it since the client read — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This guard exists because both operations legitimately supersede prior state: re-finalization replaces the `CURRENT` budget snapshot even from `BUDGET_LOCKED`, and a new negotiation offer voids the open offer even while the proposal remains `NEGOTIATING`. The version check is what prevents a writer holding a stale view from silently superseding work it has never seen. The check is evaluated after existence checks and before any state or business-rule checks. Endpoints other than these two do not accept a version field at all.

### 2.8. Validation Order and Error Precedence

Every request is validated in a fixed order, and the first failure short-circuits the rest. In evaluation sequence:

1. **User context.** Both headers are present and the role is one of the seven declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Authorization and ownership.** The role is listed for the endpoint, and entity-backed ownership holds for the PI role (`ERR_INSUFFICIENT_PERMISSIONS`, 403). When a PI reaches an existing resource they do not own, the rejection is `ERR_NOT_RESOURCE_OWNER` (403) instead.
3. **Existence.** Path identifiers are validated left to right, then body-referenced foreign keys such as `opportunity_id`, `pi_id`, `subrecipient_org_id`, and `subrecipient_commitment_id` (`ERR_NOT_FOUND`, 404).
4. **Optimistic concurrency.** Where §2.7 requires it, `expected_proposal_version` must equal the proposal's current `version` (`ERR_STALE_VERSION`, 412). This is deliberately placed after existence and before state or business logic, so a stale writer learns about the version conflict first.
5. **State eligibility.** The target resource must be in a status the operation allows; the rejection is the state error of the owning resource family — `ERR_PROPOSAL_INVALID_STATE`, `ERR_COMMITMENT_INVALID_STATE`, `ERR_REVIEW_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`, `ERR_HANDOFF_INVALID_STATE`, or `ERR_RATE_AGREEMENT_INVALID_STATE`, each HTTP 409.
6. **Segregation of duties.** The institutional approver must differ from the analyst who routed the proposal (`ERR_SELF_APPROVAL`, 403), and the cost-share approver must differ from the pledge's creator (`ERR_COST_SHARE_SELF_APPROVAL`, 403).
7. **Compliance gates.** No `DISAPPROVED` review at readiness (`ERR_COMPLIANCE_DISAPPROVED`, 409); disclosure complete before a conflict-of-interest approval (`ERR_COI_DISCLOSURE_INCOMPLETE`, 422); the PI eligible at proposal creation (`ERR_PI_NOT_ELIGIBLE`, 403).
8. **Referential usability.** The parent opportunity must still be `PUBLISHED` for proposal creation, institutional approval, and portal submission (`ERR_OPPORTUNITY_CLOSED`, 409).
9. **Temporal gates.** The submission clock must not have passed the internal deadline (`ERR_INTERNAL_DEADLINE_PASSED`, 422), and no approval may be lapsed at readiness (`ERR_COMPLIANCE_APPROVAL_EXPIRED`, 409).
10. **Structural constraints.** Activity-code membership, per-PI proposal caps, duplicate active reviews, FINAL rate-window overlap, PI effort capacity, a non-empty budget, an applicable rate, resolved reviews, a current pinned snapshot, a FINAL rate at handoff, subrecipient documents, high-risk acknowledgement, verified subrecipients, and UEI uniqueness — each with its own error code in §5.
11. **Fiscal checks last.** The sponsor request cap (`ERR_REQUEST_EXCEEDS_CAP`, 422) and cost-share adequacy (`ERR_COST_SHARE_INADEQUATE`, 422) are evaluated only after every earlier category has passed — so, for example, an empty budget surfaces before any cap violation.

Independently of this ladder, structurally malformed payloads — a missing required field, a type mismatch, an unknown enum member, a non-positive `amount_cents`, an end date earlier than its start date, or a `SUBAWARD` line without its `subrecipient_commitment_id` — are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Nested Paths and Referenced Existence

For any request whose path contains multiple resource identifiers — a budget line beneath a proposal, the commitment list beneath a subrecipient organization — the server validates existence strictly left to right and answers `ERR_NOT_FOUND` (HTTP 404) for the first identifier that does not resolve, without examining later segments. The same error answers a body-supplied reference that does not exist, whether `opportunity_id`, `pi_id`, `subrecipient_org_id`, or `subrecipient_commitment_id`.

### 2.10. Cascading State Consistency Across the Award Record

The proposal is the hub of the award record, and consistency flows in both directions. When a parent's transition invalidates its dependents — a withdrawal, a declined offer, an opportunity's intake closure — the server resolves every dependent record in the same write: open reviews are cancelled, pledges withdrawn, approved commitments released, subrecipient commitments voided, and any open negotiation offer voided. Conversely, child mutations that bear on parent state propagate upward automatically, with no separate client call: a disapproved review forces its proposal back to revision, a budget-line edit under a locked budget supersedes the current snapshot and drops the proposal back to drafting, and an expiring approval blocks a ready handoff. Every mutation of a proposal, including cascade-driven ones, refreshes its `updated_at` and increments its `version` by one; the same discipline holds for every other versioned resource in §2.5.

## 3. Business Logic & Workflows

### 3.1. Opportunity Intake and Investigator Eligibility

An `OSPSystemAdmin` intakes a **FundingOpportunity** by supplying the `sponsor_code` identifying the sponsor, a `title`, the `activity_codes_allowed` list drawn from the four recognized activity codes (`RESEARCH_ON_CAMPUS`, `RESEARCH_OFF_CAMPUS`, `INSTRUCTION`, `OTHER_SPONSORED`), and the `sponsor_deadline_at` portal deadline. Optional intake knobs shape everything downstream: `internal_lead_days` (defaulting to 5) drives the computed `internal_deadline_at` described in §2.4; `fa_rate_cap_pct` caps the applied F&A rate and is uncapped when omitted; `requires_cost_share` (default false) and `min_cost_share_pct_of_request` (default 0) arm the cost-share adequacy test of §3.4; `max_request_cents` caps the sponsor request and is uncapped when omitted; and `max_proposals_per_pi` limits how many non-terminal proposals one investigator may hold against this opportunity, with no limit when omitted. A newly intaken opportunity is `PUBLISHED`, its `internal_deadline_at` computed at creation.

Opportunities close on their own. When the logical clock is set, the sweep transitions every still-`PUBLISHED` opportunity whose `sponsor_deadline_at` has passed into `INTAKE_CLOSED`, its terminal state. The closure cascades: each of the opportunity's proposals in `DRAFT`, `BUDGET_LOCKED`, `ROUTED`, or `RETURNED_FOR_REVISION` is moved to `WITHDRAWN` — a proposal that already reached `INSTITUTIONALLY_APPROVED` survives the sweep, though its later submission will be stopped by `ERR_OPPORTUNITY_CLOSED` or `ERR_INTERNAL_DEADLINE_PASSED`. For every withdrawn proposal, its compliance reviews in `PENDING` or `INFO_REQUESTED` are `CANCELLED`, its cost-share commitments move from `PLEDGED` to `WITHDRAWN` and from `APPROVED` to `RELEASED`, and its subrecipient commitments in `DRAFT`, `VERIFIED`, or `STALE` are `VOIDED`; the withdrawn proposal's `total_approved_cost_share_cents` and `total_effective_cost_share_cents` are then recomputed and land on zero. The same clock sweep expires reviews per §3.6.

The **PrincipalInvestigator** registry is likewise maintained by an `OSPSystemAdmin`, recording `full_name`, `department_code`, academic `rank` (one of `ASSISTANT`, `ASSOCIATE`, `FULL`, `RESEARCH_SCIENTIST`), and an optional `delinquent_report_count` that defaults to zero. Two computed fields ride on the record. `is_eligible` holds exactly when the investigator has no delinquent prior-award reports, and it gates proposal creation — attempting to create a proposal for an investigator whose `delinquent_report_count` is greater than zero is refused with `ERR_PI_NOT_ELIGIBLE` (HTTP 403). `committed_effort_pct` reports the portfolio load: the sum of `pi_effort_pct` across that investigator's proposals in the effort-contributing states `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, `NEGOTIATING`, `AWARDED`, and `SETUP_COMPLETE`, taken regardless of whether their project windows overlap.

### 3.2. Rate Agreements and the Indirect-Cost Basis

F&A pricing is governed by **FaRateAgreement** records, which an `OSPDirector` authors with a `rate_type` of `ON_CAMPUS_RESEARCH`, `OFF_CAMPUS_RESEARCH`, `INSTRUCTION`, or `OTHER_SPONSORED`, a `rate_pct` greater than zero and at most 100, and a half-open effectiveness window: `effective_start_on` is inclusive, `effective_end_on` exclusive, so a project start date falling exactly on `effective_end_on` is not covered while one falling exactly on `effective_start_on` is. An optional `initial_status` at creation defaults to `PROVISIONAL`; an agreement created directly as `FINAL` runs the overlap check immediately. Finalization moves a `PROVISIONAL` agreement to `FINAL` — finalizing anything else is rejected with `ERR_RATE_AGREEMENT_INVALID_STATE` (HTTP 409). The overlap rule guards only FINAL-versus-FINAL pairs: a `FINAL` agreement whose half-open window overlaps another `FINAL` agreement of the same `rate_type` is rejected with `ERR_FA_RATE_WINDOW_OVERLAP` (HTTP 409), while mere adjacency — one window's `effective_end_on` equal to the other's `effective_start_on` — is allowed, and `PROVISIONAL` agreements never trigger the check.

A proposal's `activity_code` maps one-to-one onto a rate type: `RESEARCH_ON_CAMPUS` selects `ON_CAMPUS_RESEARCH`, `RESEARCH_OFF_CAMPUS` selects `OFF_CAMPUS_RESEARCH`, `INSTRUCTION` selects `INSTRUCTION`, and `OTHER_SPONSORED` selects `OTHER_SPONSORED`. Rate selection then depends on when it runs. At budget-finalization time (the provisional basis), the server prefers a `FINAL` agreement of the resolved type whose window contains `project_start_on`, falling back to a `PROVISIONAL` one; when neither covers the start date, finalization fails with `ERR_NO_APPLICABLE_RATE` (HTTP 422). At award-readiness time (the final basis), only `FINAL` agreements are eligible, and the absence of a covering one fails readiness with `ERR_RATE_NOT_FINAL` (HTTP 409). In both bases, once a rate is selected the applied rate is the lesser of the selected rate and the opportunity's `fa_rate_cap_pct` when a cap is set — a selected rate exactly equal to the cap is allowed — and is simply the selected rate when the opportunity is uncapped.

### 3.3. Proposal Drafting and Budget Construction

A `PI` opens a **Proposal** with a payload naming the target `opportunity_id`, the `pi_id` (which must equal the caller's `X-User-ID`, a permission failure otherwise), a `title`, an `activity_code`, the half-open project window `project_start_on` to `project_end_on` — an end earlier than the start is malformed — and the investigator's `pi_effort_pct`, which must be greater than zero and at most 100. An optional `fa_base_type` of `MTDC` or `TDC` defaults to `MTDC` and selects the indirect-cost variant of §3.3's finalization math. Creation enforces, beyond eligibility: the opportunity must still be `PUBLISHED` (`ERR_OPPORTUNITY_CLOSED`, 409); the `activity_code` must appear in the opportunity's `activity_codes_allowed` (`ERR_ACTIVITY_CODE_NOT_ALLOWED`, 422); and, when the opportunity sets `max_proposals_per_pi`, the investigator's count of proposals against this opportunity that have not reached a terminal state must leave room (`ERR_PI_PROPOSAL_LIMIT_EXCEEDED`, 409). A new proposal is `DRAFT` with `version` 1: `current_snapshot_id` and `pinned_budget_snapshot_id` are null, all three totals are zero, `fa_rate_pct_applied` and `applied_rate_source` are null until the first finalization, `total_approved_cost_share_cents` and `total_effective_cost_share_cents` are zero with `is_cost_share_adequate` false, `compliance_posture` reads `CLEAR`, `routed_by_user_id` is null, `budget_amended_since_approval` is false, `revision_count` is zero, and `submitted_at`, `jit_due_at`, and `awarded_total_cents` are all null. The proposal listing supports filters on `opportunity_id`, `pi_id`, `status`, `current_snapshot_id`, and `pinned_budget_snapshot_id`, alongside the standard `limit` and `offset`.

While the proposal is `DRAFT` or `RETURNED_FOR_REVISION`, the owning PI may edit the scalar fields `title`, `project_start_on`, `project_end_on`, `pi_effort_pct`, and `fa_base_type`. Editing from any other status is rejected with `ERR_PROPOSAL_INVALID_STATE`, and a caller other than the owning PI is rejected with `ERR_NOT_RESOURCE_OWNER`. A successful edit on a `RETURNED_FOR_REVISION` proposal resumes it to `DRAFT`; either way the proposal's `version` increments.

Budget construction belongs to the `PreAwardAnalyst`, who adds **BudgetLine** records carrying a `category` (`PERSONNEL`, `EQUIPMENT`, `TRAVEL`, `PARTICIPANT_SUPPORT`, `MATERIALS`, `PUBLICATION`, `CONSULTANT`, `SUBAWARD`, `TUITION`, or `OTHER_DIRECT`), a free-text `description`, the `fiscal_year` the cost falls in, and an `amount_cents` strictly greater than zero. A line flagged `is_cost_share` (default false) is institutional contribution rather than sponsor request: such lines are excluded from the direct-cost totals and from the indirect-cost base. A `SUBAWARD` line must name its `subrecipient_commitment_id`, tying it to a verified subrecipient plan; omitting it is malformed. Each line's `counts_toward_mtdc` is computed — false for `EQUIPMENT`, `TUITION`, and `PARTICIPANT_SUPPORT`; for `SUBAWARD`, true only while its commitment's cumulative allowance remains; true for every other category. Lines may be added or deleted only while the proposal is `DRAFT`, `BUDGET_LOCKED`, or `JIT_REQUESTED` — any other status is rejected with `ERR_PROPOSAL_INVALID_STATE`. Mutating lines under a locked budget has teeth: adding or deleting a line while `BUDGET_LOCKED` supersedes the `CURRENT` snapshot, nulls `current_snapshot_id`, and drops the proposal automatically back to `DRAFT`; the budget totals from the last snapshot remain readable but stale, and routing will demand a fresh lock. The same mutation while `JIT_REQUESTED` supersedes the snapshot and sets `budget_amended_since_approval` true while leaving the status itself untouched. Every line add or delete increments the proposal's `version`. Budget lines can be listed per proposal, or across the system filtered by `proposal_id`, `subrecipient_commitment_id`, or `category`.

Finalization freezes the budget into an immutable **BudgetSnapshot**. A `PreAwardAnalyst` may finalize from `DRAFT`, `BUDGET_LOCKED`, or `JIT_REQUESTED` — any other status yields `ERR_PROPOSAL_INVALID_STATE` — and the write is OCC-guarded per §2.7, so a stale `expected_proposal_version` is refused with `ERR_STALE_VERSION` (HTTP 412). Finalization requires at least one non-cost-share line (`ERR_EMPTY_BUDGET`, 422), a covering rate agreement per §3.2 (`ERR_NO_APPLICABLE_RATE`, 422), and — evaluated last among the business checks — a resulting `total_request_cents` that does not exceed the opportunity's `max_request_cents` when one is set (`ERR_REQUEST_EXCEEDS_CAP`, 422).

The snapshot captures everything needed to reproduce the numbers: a per-proposal `snapshot_index` ascending from 1; the `fa_base_type` copied from the proposal; the resolved `rate_type`; the `selected_rate_pct` before any cap; the `applied_rate_pct` after the cap; the `rate_source` of `FINAL_RATE` or `PROVISIONAL_RATE`; the `mtdc_base_cents` eligible base, which under `TDC` simply equals `total_direct_cents`; the `total_direct_cents`, `total_indirect_cents`, and `total_request_cents`; and `per_line_indirect`, an array of entries each naming a `budget_line_id`, its `base_portion_cents`, and its `indirect_cents`, recorded in the pinned processing order. Exactly one snapshot per proposal is `CURRENT` — finalization flips any prior `CURRENT` snapshot to `SUPERSEDED` — and the proposal copies the snapshot's totals onto itself: `total_direct_cents`, `total_indirect_cents`, `total_request_cents`, `fa_rate_pct_applied`, `applied_rate_source`, and `current_snapshot_id`. Cost-share adequacy is recomputed, and the proposal's `version` increments. From `DRAFT` the proposal becomes `BUDGET_LOCKED`; from `BUDGET_LOCKED` re-finalization keeps it `BUDGET_LOCKED`; from `JIT_REQUESTED` it stays `JIT_REQUESTED` with `budget_amended_since_approval` remaining true until re-approval.

The indirect-cost computation itself is order-sensitive and must not be rearranged. The input set is the proposal's budget lines with `is_cost_share` false. Under the `MTDC` variant, lines in `EQUIPMENT`, `TUITION`, or `PARTICIPANT_SUPPORT` contribute a base portion of zero; each `SUBAWARD` line contributes the lesser of its own `amount_cents` and the remaining MTDC allowance of its `subrecipient_commitment_id`, where each commitment's allowance is the first $25,000 (2500000 cents) of cumulative subaward amounts consumed in processing order; every other category contributes its full `amount_cents`. Under the `TDC` variant every non-cost-share line contributes its full `amount_cents` — no exclusions, no subaward cap. Lines are processed ordered by `fiscal_year` ascending, ties broken by `created_at` ascending, and never by identifier; this order matters precisely because the subaward allowance is consumed as processing proceeds. Each line's indirect is its base portion multiplied by the applied rate percent, divided by one hundred, and rounded half up to whole cents — and the proposal's `total_indirect_cents` is the sum of those already-rounded per-line amounts, per the rounding discipline of §2.6. `total_direct_cents` is the sum of the non-cost-share `amount_cents`, and `total_request_cents` is the direct total plus the indirect total.

### 3.4. Cost-Share Commitments and the Adequacy Test

Cost-share begins when a `PreAwardAnalyst` pledges a **CostShareCommitment** against a proposal, naming a `source_type` of `DEPARTMENT`, `COLLEGE`, `CENTRAL_OFFICE`, or `THIRD_PARTY_IN_KIND` and an `amount_cents` strictly greater than zero. The pledge starts `PLEDGED`, with `committed_by_user_id` captured from the caller's header and `approved_by_user_id` still null. Approval belongs to a `DepartmentChair` and is segregated: the approver's `X-User-ID` must differ from `committed_by_user_id`, or the attempt fails with `ERR_COST_SHARE_SELF_APPROVAL` (HTTP 403). Approval is possible only from `PLEDGED` (otherwise `ERR_COMMITMENT_INVALID_STATE`, 409) and only while the parent proposal sits in `DRAFT`, `BUDGET_LOCKED`, `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, `NEGOTIATING`, or `AWARDED` (otherwise `ERR_PROPOSAL_INVALID_STATE`, 409). On approval the commitment records `approved_by_user_id`, the proposal's `total_approved_cost_share_cents` grows by the commitment's `amount_cents`, the effective credit and adequacy are recomputed, and the proposal's `version` increments. A `DepartmentChair` may also release an `APPROVED` commitment — the compensating action — moving it to `RELEASED`, subtracting its amount from `total_approved_cost_share_cents`, recomputing the derived fields, and incrementing the proposal's `version` again; releasing anything not `APPROVED` is `ERR_COMMITMENT_INVALID_STATE`. A `PreAwardAnalyst` may withdraw a still-`PLEDGED` commitment to `WITHDRAWN` (the terminal cleanup cascade can do the same), and withdrawal from any other state is `ERR_COMMITMENT_INVALID_STATE`.

Adequacy is a pinned-order computation, because the third-party cap depends on the required minimum, which itself derives from the budget totals. First, the required minimum `required_min_cost_share_cents` is zero when the opportunity's `requires_cost_share` is false; otherwise it is the opportunity's `min_cost_share_pct_of_request` multiplied by the proposal's current `total_request_cents`, divided by one hundred, and rounded half up to whole cents. Second, the cash-approved total sums the `amount_cents` of the proposal's `APPROVED` commitments whose `source_type` is `DEPARTMENT`, `COLLEGE`, or `CENTRAL_OFFICE`. Third, the third-party-approved total sums the `APPROVED` `THIRD_PARTY_IN_KIND` commitments. Fourth, the effective third-party credit is the lesser of two quantities, each rounded half up to whole cents: one half of the third-party-approved total, and one quarter of the required minimum. Fifth, `total_effective_cost_share_cents` is the cash-approved total plus the effective third-party credit. Finally, `is_cost_share_adequate` holds exactly when `total_effective_cost_share_cents` is at least the required minimum — equality is adequate — and it holds vacuously, whatever the commitments look like, when the opportunity does not require cost share. Commitments in `PLEDGED`, `WITHDRAWN`, or `RELEASED` never contribute to any of these sums. The computation re-runs whenever a commitment is created, approved, released, or withdrawn, whenever the budget is finalized, and again at award readiness.

### 3.5. Routing, Effort Capacity, and the Institutional Decision

Routing sends a locked budget up for institutional sign-off. A `PreAwardAnalyst` may route only a proposal in `BUDGET_LOCKED` — anything else is `ERR_PROPOSAL_INVALID_STATE` — and two guards stand in the way. The effort-capacity guard aggregates the PI's commitments across overlapping half-open project windows: the contributor set is every *other* proposal of the same `pi_id` in `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, `NEGOTIATING`, `AWARDED`, or `SETUP_COMPLETE` whose window overlaps the candidate's, where two windows overlap when the candidate's start falls before the other's end and the other's start falls before the candidate's end — merely adjacent windows, one beginning exactly where the other ends, do not overlap. The candidate's own `pi_effort_pct` plus the sum of the contributors' `pi_effort_pct` must not exceed 100.00, with a total of exactly 100.00 passing; a breach is `ERR_PI_EFFORT_EXCEEDED` (HTTP 422). The second guard fires when the opportunity requires cost share: the proposal must currently be adequate per §3.4, else `ERR_COST_SHARE_INADEQUATE` (HTTP 422). A successful route records `routed_by_user_id` from the caller's header — this value anchors the segregation check at approval — and increments the proposal's `version` as it becomes `ROUTED`.

Institutional approval belongs to the `OSPDirector` and takes three distinct forms. From `ROUTED`, approval moves the proposal to `INSTITUTIONALLY_APPROVED`; the approver must not be the analyst who routed it — an `X-User-ID` equal to `routed_by_user_id` is refused with `ERR_SELF_APPROVAL` (HTTP 403) — and the opportunity must still be `PUBLISHED` (`ERR_OPPORTUNITY_CLOSED`, 409). Approval **pins the budget**: `pinned_budget_snapshot_id` is set to the proposal's `current_snapshot_id`, and handoff will later require the pin to still be current. From `JIT_REQUESTED`, the same approval action serves as re-approval after a just-in-time budget amendment: it is valid only when `budget_amended_since_approval` is true (otherwise `ERR_PROPOSAL_INVALID_STATE`), the opportunity must still be `PUBLISHED`, and it re-pins `pinned_budget_snapshot_id` to `current_snapshot_id` while clearing `budget_amended_since_approval` to false, leaving the proposal in `JIT_REQUESTED`. From `AWARDED`, the same action re-pins a snapshot whose budget was amended after the award carried through — again only when `budget_amended_since_approval` is true — re-pinning and clearing the flag while the proposal stays `AWARDED`. Every form increments the proposal's `version`.

When the budget or the science needs another pass, the `OSPDirector` returns a `ROUTED` proposal for revision, supplying a `reason`; any other status is `ERR_PROPOSAL_INVALID_STATE`. The proposal lands in `RETURNED_FOR_REVISION`, its `revision_count` increments by one, and the record compensates for work that can no longer be trusted: every `APPROVED` cost-share commitment of the proposal is `RELEASED`, every `VERIFIED` subrecipient commitment goes `STALE`, and `total_approved_cost_share_cents`, `total_effective_cost_share_cents`, and `is_cost_share_adequate` are recomputed. The proposal's `version` increments, and the PI resumes the cycle by editing per §3.3.

### 3.6. Ancillary Compliance Reviews

A `ComplianceOfficer` opens a **ComplianceReview** on a proposal by naming a `review_type` of `IRB`, `IACUC`, `EXPORT_CONTROL`, or `CONFLICT_OF_INTEREST`, optionally recording `disclosure_complete` (default false). At most one active review may exist per proposal and review type — active meaning `PENDING`, `INFO_REQUESTED`, or `APPROVED` — and a duplicate attempt is rejected with `ERR_DUPLICATE_ACTIVE_REVIEW` (HTTP 409). A new review starts `PENDING`, and its proposal's `compliance_posture` is recomputed: `BLOCKED` when any of the proposal's reviews is `DISAPPROVED`; otherwise `REVIEW_PENDING` when any review is `PENDING`, `INFO_REQUESTED`, or `EXPIRED`; otherwise `CLEAR`.

The review dialogue cycles between the office and the investigator. Requesting information moves a `PENDING` review to `INFO_REQUESTED` carrying the officer's `question`; any other starting state is `ERR_REVIEW_INVALID_STATE` (HTTP 409), and the posture stays `REVIEW_PENDING`. The owning PI — and only the owning PI, on pain of `ERR_NOT_RESOURCE_OWNER` — responds, optionally including a `response_note` and a `disclosure_complete` value that is applied when supplied. A response returns an `INFO_REQUESTED` review to `PENDING`; the same response action also renews an `EXPIRED` review, returning it to `PENDING` while clearing its `approved_until_at` and `validity_days` back to null so a fresh approval window can be granted.

Approval is the officer's again, from `PENDING` only (`ERR_REVIEW_INVALID_STATE` otherwise), with one hard gate: a `CONFLICT_OF_INTEREST` review cannot be approved while `disclosure_complete` is false — the attempt fails with `ERR_COI_DISCLOSURE_INCOMPLETE` (HTTP 422). Approval stamps the validity window: `validity_days` comes from the approval payload's override when supplied, else the type default — 365 days for `IRB`, 1095 for `IACUC`, 730 for `EXPORT_CONTROL`, 365 for `CONFLICT_OF_INTEREST` — and `approved_until_at` is set to the approval clock time plus those days. The proposal's posture is recomputed. Disapproval, accompanied by a `reason`, is available from `PENDING` or `INFO_REQUESTED` and is the heavy hammer of the system: the proposal's `compliance_posture` becomes `BLOCKED`; a proposal sitting in `ROUTED`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, or `NEGOTIATING` is forced back to `RETURNED_FOR_REVISION` with its `revision_count` incremented; that forced return then releases every `APPROVED` cost-share commitment and stales every `VERIFIED` subrecipient commitment, exactly as a director-initiated return would; the cost-share totals and adequacy are recomputed; and the proposal's `version` increments.

Approvals do not live forever. When the logical clock is set, any `APPROVED` review whose `approved_until_at` has fallen behind the current time becomes `EXPIRED`; the proposal's posture is recomputed — typically back to `REVIEW_PENDING` — and, per §3.9, a ready handoff of that proposal bubbles up to `BLOCKED`. Separately, the terminal cleanup cascade — proposal withdrawal, a declined offer, or opportunity intake closure — cancels every review still in `PENDING` or `INFO_REQUESTED`, moving it to `CANCELLED` with the posture recomputed; `DISAPPROVED` and `CANCELLED` are the review's terminal states.

### 3.7. Subrecipient Organizations, Risk Scoring, and Commitment Verification

Subrecipient due diligence starts in the org registry, maintained by the `SubrecipientManager`. Registering a **SubrecipientOrg** records its `legal_name`, its `uei` — the Unique Entity Identifier, which must be globally unique across the registry, a duplicate being refused with `ERR_UEI_NOT_UNIQUE` (HTTP 409) — an optional `is_foreign` flag (default false), a `single_audit_status` of `CURRENT`, `DELINQUENT`, `NOT_REQUIRED`, or `MISSING`, an optional `audit_finding_count` (default zero, never negative), and an optional `first_time_subrecipient` flag (default false) marking organizations that have never held a subaward with this institution. Registration computes the standard-variant `risk_score` and `risk_tier` on the spot.

The risk score is a weighted sum with a non-linear cap. The base depends on `single_audit_status`: 10 points for `CURRENT`, 20 for `NOT_REQUIRED`, 45 for `MISSING`, 60 for `DELINQUENT`. The findings term adds five points per audit finding, capped at 25 points no matter how many findings exist. A foreign organization adds 10 points, and a first-time subrecipient adds another 10. The tiering is fixed: a score below 25 is `LOW`, from 25 through 49 is `MEDIUM`, and 50 or more is `HIGH`. A second, **enhanced** variant exists for verification of large commitments: when the commitment's `subaward_amount_cents` is at least $250,000 (25000000 cents — an amount exactly equal selects the enhanced variant), the score is computed as the standard score plus a 15-point surcharge, then tiered by the same thresholds. The enhanced score lives only on the verification snapshot, so one and the same organization can read `MEDIUM` on its registry entry yet verify as `HIGH` for a large commitment.

A `PreAwardAnalyst` attaches a **SubrecipientCommitment** to a proposal by naming the `subrecipient_org_id`, the planned `subaward_amount_cents` (strictly greater than zero), and optional intake booleans `statement_of_work_received`, `budget_received`, and `enhanced_monitoring_acknowledged`, all defaulting to false. The commitment starts `DRAFT`. Verification, performed by the `SubrecipientManager`, is allowed from `DRAFT` or `STALE` — anything else is `ERR_COMMITMENT_INVALID_STATE` — and enforces two gates: both `statement_of_work_received` and `budget_received` must be true, else `ERR_SUBREC_DOCS_INCOMPLETE` (HTTP 422); and when the organization's risk tier is `HIGH`, `enhanced_monitoring_acknowledged` must be true, else `ERR_SUBREC_HIGH_RISK_NOT_ACKED` (HTTP 422). Successful verification pins `verified_risk_snapshot_score` to the risk score computed under the variant the amount selects, and sets `monitoring_level` to `ENHANCED` when the verified tier is `HIGH`, otherwise `STANDARD`. When the parent proposal is returned for revision, every `VERIFIED` commitment goes `STALE` automatically; the pinned score and monitoring level are retained as historical fact until a re-verification replaces them. A commitment may be voided by the `SubrecipientManager` from `DRAFT`, `VERIFIED`, or `STALE` — the terminal cleanup cascade can void them too — landing in `VOIDED`, the terminal state; voiding from any other state is `ERR_COMMITMENT_INVALID_STATE`.

### 3.8. Sponsor Submission, Just-In-Time Requests, and Award Negotiation

Submission is the point of no return for the pre-award record, and only an `OSPDirector` may perform it. The proposal must be `INSTITUTIONALLY_APPROVED` (else `ERR_PROPOSAL_INVALID_STATE`), the opportunity must still be `PUBLISHED` (else `ERR_OPPORTUNITY_CLOSED`), and the logical clock must be at or before the opportunity's `internal_deadline_at` — an exact tie with the deadline is allowed, and anything later is refused with `ERR_INTERNAL_DEADLINE_PASSED` (HTTP 422). The request carries an `idempotency_key` unique per proposal: replaying a submission with a key already used by one of this proposal's packages returns the original package rather than submitting twice. A successful submission mints a **SubmissionPackage** — a server-generated `portal_confirmation_code`, a `submitted_at` taken from the logical clock, and a `status` of `ACCEPTED_BY_PORTAL`, its only state — records the same `submitted_at` on the proposal, moves the proposal to `SUBMITTED`, and increments its `version`.

Sponsors frequently ask for just-in-time materials after submission. Recording a JIT notice — an `OSPDirector` action carrying a `sponsor_reference` and an optional `due_in_days` that defaults to 14 — moves a `SUBMITTED` proposal to `JIT_REQUESTED` and sets `jit_due_at` to the notice's clock time plus the given number of days; from any other status it is `ERR_PROPOSAL_INVALID_STATE`. Recording the JIT response, again with a `sponsor_reference`, returns a `JIT_REQUESTED` proposal to `SUBMITTED`. Both increments of the proposal's `version` apply. While `JIT_REQUESTED`, remember from §3.3 that budget lines may still change and budgets re-finalize — such amendment keeps the status, supersedes the snapshot, and leaves `budget_amended_since_approval` true until the re-approval path of §3.5 clears it.

Negotiation is offer-driven. An `OSPDirector` opens a round on a proposal in `SUBMITTED`, `JIT_REQUESTED`, or `NEGOTIATING` — any other status is `ERR_PROPOSAL_INVALID_STATE` — under the OCC guard of §2.7, so a stale `expected_proposal_version` is refused with `ERR_STALE_VERSION` (HTTP 412). The offer payload names an `origin` of `SPONSOR` or `INSTITUTION`, an `offered_total_cents` strictly greater than zero, and optionally an `offered_fa_rate_pct` and a free-text `note`. Each **NegotiationOffer** receives a per-proposal `round_index` ascending from 1 and starts `PROPOSED`; at most one offer per proposal may be `PROPOSED` at a time, so opening a new round voids any prior `PROPOSED` offer on the same proposal — supersession, recorded as `VOIDED`. Opening a round moves a `SUBMITTED` or `JIT_REQUESTED` proposal to `NEGOTIATING`; a proposal already `NEGOTIATING` stays there as rounds accumulate. Each opening increments the proposal's `version`.

Resolving the open offer ends the negotiation. Accepting — again an `OSPDirector` action — requires the offer to be `PROPOSED` (else `ERR_OFFER_INVALID_STATE`, 409) and its proposal to be `NEGOTIATING` (else `ERR_PROPOSAL_INVALID_STATE`). Acceptance moves the offer to `ACCEPTED`, the proposal to `AWARDED`, records the accepted amount as the proposal's `awarded_total_cents` taken from `offered_total_cents`, and — because an award demands setup — automatically creates the proposal's one and only **AwardHandoff**, starting `DRAFT` with `budget_verified`, `compliance_verified`, and `subrecipient_verified` all false and `final_indirect_cents`, `final_total_cents`, and `handoff_at` all null. The proposal's `version` increments. Declining requires the same `PROPOSED` offer state, moves the offer to `DECLINED`, and moves the proposal to `DECLINED` with the terminal cleanup cascade described below, recomputing the cost-share totals and incrementing the version.

Withdrawal is the manual escape hatch, available to the owning `PI` and to an `OSPDirector`. It is permitted from `DRAFT`, `BUDGET_LOCKED`, `ROUTED`, `RETURNED_FOR_REVISION`, `INSTITUTIONALLY_APPROVED`, `SUBMITTED`, `JIT_REQUESTED`, or `NEGOTIATING` — an `AWARDED` proposal and the terminal states `SETUP_COMPLETE`, `WITHDRAWN`, and `DECLINED` cannot be withdrawn, such attempts drawing `ERR_PROPOSAL_INVALID_STATE` — and a PI caller must own the proposal (`ERR_NOT_RESOURCE_OWNER` otherwise). The **terminal cleanup cascade**, shared by withdrawal, decline, and intake closure, resolves everything still open: compliance reviews in `PENDING` or `INFO_REQUESTED` become `CANCELLED`; cost-share commitments move `PLEDGED` to `WITHDRAWN` and `APPROVED` to `RELEASED`; subrecipient commitments in `DRAFT`, `VERIFIED`, or `STALE` become `VOIDED`; and any `PROPOSED` negotiation offer becomes `VOIDED`. The proposal's `total_approved_cost_share_cents` and `total_effective_cost_share_cents` are recomputed afterward, and its `version` increments.

### 3.9. Award Handoff and Setup Completion

Between `AWARDED` and the post-award team stands the **AwardHandoff** checklist. Marking readiness is an `OSPDirector` action allowed from `DRAFT` or `BLOCKED` — anything else is `ERR_HANDOFF_INVALID_STATE` (HTTP 409) — and only while the proposal itself is `AWARDED` (`ERR_PROPOSAL_INVALID_STATE` otherwise). Readiness re-runs every gate, in this order: no review of the proposal may be `DISAPPROVED` (`ERR_COMPLIANCE_DISAPPROVED`, 409); no review may be `EXPIRED` or past its `approved_until_at` (`ERR_COMPLIANCE_APPROVAL_EXPIRED`, 409); no review may remain `PENDING` or `INFO_REQUESTED` (`ERR_COMPLIANCE_REVIEW_PENDING`, 409); the proposal's `pinned_budget_snapshot_id` must equal its `current_snapshot_id`, catching budgets amended since approval (`ERR_STALE_BUDGET_SNAPSHOT`, 409); a `FINAL` rate agreement must cover `project_start_on` (`ERR_RATE_NOT_FINAL`, 409); every non-`VOIDED` subrecipient commitment must be `VERIFIED` (`ERR_SUBRECIPIENT_NOT_VERIFIED`, 409); and cost-share adequacy must hold against the final-basis totals (`ERR_COST_SHARE_INADEQUATE`, 422).

Success writes the final numbers. `final_indirect_cents` is the indirect cost recomputed under the final basis of §3.2 — the same base portions as the pinned snapshot, but only `FINAL` agreements eligible, so a different selected rate legitimately yields different cents than the snapshot shows — and `final_total_cents` is the proposal's `total_direct_cents` plus that `final_indirect_cents`. All three checklist flags, `budget_verified`, `compliance_verified`, and `subrecipient_verified`, are set true, and the handoff becomes `READY`.

Readiness is fragile by design: the moment any review of the proposal becomes `EXPIRED` or `DISAPPROVED`, a `READY` handoff automatically falls back to `BLOCKED` and its `compliance_verified` flag resets to false. Recovering requires a fresh mark-ready, which re-runs the full gate set from `BLOCKED` exactly as from `DRAFT`.

The final act is the handoff itself, performed by an `OSPDirector` and permitted only from `READY` (`ERR_HANDOFF_INVALID_STATE` otherwise). The handoff becomes `HANDED_OFF`, its `handoff_at` stamped from the logical clock, and the proposal reaches `SETUP_COMPLETE` — its terminal resting state — with the customary increment of the proposal's `version`.

## 4. Endpoint Definitions

Operations that create a new resource — an opportunity, an investigator, a rate agreement, an organization, a proposal, a budget line, a budget snapshot via finalization, a cost-share pledge, a compliance review, a subrecipient commitment, a negotiation offer, or a submission package — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. The single deletion operation, removing a budget line, returns `204 No Content`. Request and response payloads for every row are governed by the workflows in §3; this table is a navigational summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/pre-award/_clock/set_current_utc` | Set the logical clock; fires the intake-closure and review-expiry sweeps | OSPSystemAdmin |
| POST | `/pre-award/funding-opportunities` | Intake a funding opportunity; internal deadline computed | OSPSystemAdmin |
| GET | `/pre-award/funding-opportunities/{id}` | Get a funding opportunity | Any authenticated role |
| POST | `/pre-award/principal-investigators` | Register a principal investigator; eligibility computed | OSPSystemAdmin |
| GET | `/pre-award/principal-investigators/{id}` | Get a PI, including computed eligibility and committed effort | Any authenticated role |
| POST | `/pre-award/fa-rate-agreements` | Create a rate agreement (defaults to PROVISIONAL; FINAL at create runs the overlap check) | OSPDirector |
| POST | `/pre-award/fa-rate-agreements/{id}/finalize` | Finalize a PROVISIONAL agreement to FINAL with the overlap check | OSPDirector |
| GET | `/pre-award/fa-rate-agreements/{id}` | Get a rate agreement | Any authenticated role |
| POST | `/pre-award/subrecipient-orgs` | Register a subrecipient organization; risk score and tier computed | SubrecipientManager |
| GET | `/pre-award/subrecipient-orgs/{id}` | Get a subrecipient organization | Any authenticated role |
| GET | `/pre-award/subrecipient-orgs/{id}/subrecipient-commitments` | List commitments referencing this organization | Any authenticated role |
| POST | `/pre-award/proposals` | Create a proposal (eligibility, activity-code, and per-PI cap checks) | PI |
| GET | `/pre-award/proposals` | List proposals with filters and pagination | Any authenticated role |
| GET | `/pre-award/proposals/{id}` | Get a proposal with computed totals, posture, and adequacy | Any authenticated role |
| PATCH | `/pre-award/proposals/{id}` | Edit scalar fields while DRAFT or RETURNED_FOR_REVISION; a returned proposal resumes to DRAFT | PI |
| POST | `/pre-award/proposals/{id}/withdraw` | Withdraw a non-terminal, non-awarded proposal; terminal cleanup cascade | PI, OSPDirector |
| POST | `/pre-award/proposals/{id}/budget-lines` | Add a budget line (proposal DRAFT, BUDGET_LOCKED, or JIT_REQUESTED) | PreAwardAnalyst |
| GET | `/pre-award/proposals/{id}/budget-lines` | List a proposal's budget lines | Any authenticated role |
| GET | `/pre-award/budget-lines/{id}` | Get a budget line | Any authenticated role |
| GET | `/pre-award/budget-lines` | List budget lines filtered by foreign keys and category | Any authenticated role |
| DELETE | `/pre-award/budget-lines/{id}` | Delete a budget line (same state rules as add) | PreAwardAnalyst |
| POST | `/pre-award/proposals/{id}/budget-finalizations` | Finalize the budget into a new CURRENT snapshot; OCC-guarded | PreAwardAnalyst |
| GET | `/pre-award/proposals/{id}/budget-snapshots` | List a proposal's budget snapshots | Any authenticated role |
| POST | `/pre-award/proposals/{id}/route` | Route a locked budget for institutional approval (effort and cost-share guards) | PreAwardAnalyst |
| POST | `/pre-award/proposals/{id}/approve-institutional` | Institutional approval from ROUTED; re-approval after JIT amendment from JIT_REQUESTED or AWARDED | OSPDirector |
| POST | `/pre-award/proposals/{id}/return-for-revision` | Return a ROUTED proposal for revision; releases cost-share and stales subrecipient verifications | OSPDirector |
| POST | `/pre-award/proposals/{id}/submit` | Submit to the sponsor portal; idempotent on the client key | OSPDirector |
| GET | `/pre-award/proposals/{id}/submission-packages` | List a proposal's submission packages (zero or one) | Any authenticated role |
| POST | `/pre-award/proposals/{id}/jit-notices` | Record a sponsor JIT request; SUBMITTED to JIT_REQUESTED | OSPDirector |
| POST | `/pre-award/proposals/{id}/jit-responses` | Record a JIT response; JIT_REQUESTED back to SUBMITTED | OSPDirector |
| POST | `/pre-award/proposals/{id}/cost-share-commitments` | Pledge a cost-share commitment | PreAwardAnalyst |
| GET | `/pre-award/proposals/{id}/cost-share-commitments` | List a proposal's cost-share commitments | Any authenticated role |
| POST | `/pre-award/cost-share-commitments/{id}/approve` | Approve a pledge (approver must differ from committer) | DepartmentChair |
| POST | `/pre-award/cost-share-commitments/{id}/release` | Release an approved commitment (compensating action) | DepartmentChair |
| POST | `/pre-award/cost-share-commitments/{id}/withdraw` | Withdraw a pledge | PreAwardAnalyst |
| POST | `/pre-award/proposals/{id}/compliance-reviews` | Open an ancillary review; at most one active review per proposal and type | ComplianceOfficer |
| GET | `/pre-award/proposals/{id}/compliance-reviews` | List a proposal's compliance reviews | Any authenticated role |
| POST | `/pre-award/compliance-reviews/{id}/request-info` | Move a PENDING review to INFO_REQUESTED | ComplianceOfficer |
| POST | `/pre-award/compliance-reviews/{id}/respond` | PI responds; INFO_REQUESTED or EXPIRED back to PENDING | PI |
| POST | `/pre-award/compliance-reviews/{id}/approve` | Approve a PENDING review; stamps the validity window | ComplianceOfficer |
| POST | `/pre-award/compliance-reviews/{id}/disapprove` | Disapprove a PENDING or INFO_REQUESTED review; fires the return-for-revision cascade | ComplianceOfficer |
| POST | `/pre-award/proposals/{id}/subrecipient-commitments` | Attach a subrecipient commitment to a proposal | PreAwardAnalyst |
| GET | `/pre-award/proposals/{id}/subrecipient-commitments` | List a proposal's subrecipient commitments | Any authenticated role |
| POST | `/pre-award/subrecipient-commitments/{id}/verify` | Verify a DRAFT or STALE commitment; pins the risk snapshot and monitoring level | SubrecipientManager |
| POST | `/pre-award/subrecipient-commitments/{id}/void` | Void a commitment | SubrecipientManager |
| POST | `/pre-award/proposals/{id}/negotiation-offers` | Open a negotiation round (OCC-guarded); supersedes any open offer | OSPDirector |
| GET | `/pre-award/proposals/{id}/negotiation-offers` | List a proposal's negotiation offers | Any authenticated role |
| POST | `/pre-award/negotiation-offers/{id}/accept` | Accept the open offer; proposal becomes AWARDED and the handoff is auto-created | OSPDirector |
| POST | `/pre-award/negotiation-offers/{id}/decline` | Decline the open offer; proposal becomes DECLINED with terminal cleanup | OSPDirector |
| GET | `/pre-award/proposals/{id}/award-handoffs` | Get the proposal's award handoff (zero or one) | Any authenticated role |
| POST | `/pre-award/award-handoffs/{id}/mark-ready` | Run the full readiness gate and recompute final totals under the final basis | OSPDirector |
| POST | `/pre-award/award-handoffs/{id}/handoff` | Complete the handoff; proposal becomes SETUP_COMPLETE | OSPDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the identifier-to-status map only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_PROPOSAL_INVALID_STATE` | 409 Conflict |
| `ERR_COMMITMENT_INVALID_STATE` | 409 Conflict |
| `ERR_REVIEW_INVALID_STATE` | 409 Conflict |
| `ERR_OFFER_INVALID_STATE` | 409 Conflict |
| `ERR_HANDOFF_INVALID_STATE` | 409 Conflict |
| `ERR_RATE_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_SELF_APPROVAL` | 403 Forbidden |
| `ERR_COST_SHARE_SELF_APPROVAL` | 403 Forbidden |
| `ERR_PI_NOT_ELIGIBLE` | 403 Forbidden |
| `ERR_OPPORTUNITY_CLOSED` | 409 Conflict |
| `ERR_INTERNAL_DEADLINE_PASSED` | 422 Unprocessable Entity |
| `ERR_COMPLIANCE_DISAPPROVED` | 409 Conflict |
| `ERR_COMPLIANCE_APPROVAL_EXPIRED` | 409 Conflict |
| `ERR_COMPLIANCE_REVIEW_PENDING` | 409 Conflict |
| `ERR_COI_DISCLOSURE_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_ACTIVITY_CODE_NOT_ALLOWED` | 422 Unprocessable Entity |
| `ERR_PI_PROPOSAL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_REVIEW` | 409 Conflict |
| `ERR_FA_RATE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PI_EFFORT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_EMPTY_BUDGET` | 422 Unprocessable Entity |
| `ERR_NO_APPLICABLE_RATE` | 422 Unprocessable Entity |
| `ERR_RATE_NOT_FINAL` | 409 Conflict |
| `ERR_STALE_BUDGET_SNAPSHOT` | 409 Conflict |
| `ERR_SUBREC_DOCS_INCOMPLETE` | 422 Unprocessable Entity |
| `ERR_SUBREC_HIGH_RISK_NOT_ACKED` | 422 Unprocessable Entity |
| `ERR_SUBRECIPIENT_NOT_VERIFIED` | 409 Conflict |
| `ERR_UEI_NOT_UNIQUE` | 409 Conflict |
| `ERR_REQUEST_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_COST_SHARE_INADEQUATE` | 422 Unprocessable Entity |

# Grant-Writing & Proposal Service API — Product Requirements Document

## 1. Introduction

Grant-writing consultancies live and die by deadlines, eligibility, and the credibility of their win-rate. This API backs a professional grant-desk service that pairs nonprofit clients with funding opportunities, shepherds each pursuit from an initial match through narrative and budget development, tracks submissions against unforgiving portal deadlines, and then carries won proposals into the post-award world of compliance reporting. Along the way the consultancy must bill for its work under three very different commercial arrangements — a success fee taken as a slice of the award, an hourly model swept from logged time, or a flat monthly retainer with overage — and every dollar must reconcile.

The platform is built for four working perspectives and one operational harness. Account managers cultivate clients, opportunities, engagements, and matches, and they record the funder's verdict on each submission. Grant writers assemble the proposals, budgets, deliverables, and the reusable boilerplate library. The client's own reviewer signs off on deliverables and proposals, but only on work belonging to their own organization. A compliance officer owns the after-award lifecycle of reports and close-out. Because deadlines and reporting cadences are central to the domain, the system runs on a logical clock that an operator advances explicitly; opportunities close and overdue reports flip to late strictly as a consequence of clock movement, never from wall-clock drift. All resources are peer collections mounted under `/grant-desk`; relationships between them are carried as foreign-key fields rather than nested ownership paths.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `AccountManager`, `GrantWriter`, `ClientContact`, `ComplianceOfficer`, and `Ops`. The `AccountManager` cultivates clients, opportunities, engagements, matches, and invoices, and records submission decisions. The `GrantWriter` owns proposals, budget lines, deliverables, submission filing, time logging, and the boilerplate library. The `ClientContact` is the client-side reviewer who approves or returns proposals and deliverables and opens revision requests. The `ComplianceOfficer` owns the post-award world of awards, compliance reports, and close-out. The `Ops` role is the operational/test-harness capacity that drives the logical clock. All five roles may read any resource through the GET endpoints.

Four of the five roles carry an opaque identity. When `X-User-Role` is `AccountManager`, `GrantWriter`, `ComplianceOfficer`, or `Ops`, the `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The `ClientContact` role is different: it is entity-backed by `Client`. When `X-User-Role` is `ClientContact`, the `X-User-ID` is the `id` of the acting `Client`, and ownership checks compare the targeted resource's owning client to that `X-User-ID`. Specifically, a `ClientContact` may only request changes on a proposal, approve a proposal, approve a deliverable, or open a revision request when the resource ultimately rolls up to their own client; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER`. A proposal's client is reached through its engagement; a deliverable's and a revision request's client is reached through the deliverable's proposal and that proposal's engagement.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. A `limit` or `offset` outside these bounds is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise stated, every list endpoint returns its resources ordered by creation timestamp ascending. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Identifiers

Every resource is assigned a server-minted `id` that is a UUID with no type prefix. Every resource also records a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Because every entity in this service is configured with the full common-field set, every resource additionally carries an `updated_at` timestamp (same format) and an integer `version`. The `version` begins at its initial value of `1` when the resource is created and increments by one on each mutation of that resource, while `updated_at` is refreshed to the current logical instant on each such mutation. There are no version-free entities in this service; all of them participate in optimistic concurrency bookkeeping.

### 2.5. Validation Order and the Request Pipeline

When several checks could reject a request, they are evaluated in a fixed priority order so that the failure surfaced is deterministic. The pipeline runs as follows. First, header presence and well-formedness are confirmed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the role is checked against the endpoint's permitted set (`ERR_FORBIDDEN_FOR_ROLE`). Third, every resource named in the path and every foreign key referenced in the body is confirmed to exist, validated left to right (`ERR_NOT_FOUND`). Fourth, for the `ClientContact`-only review operations, ownership of the targeted resource's client is enforced (`ERR_NOT_RESOURCE_OWNER`). Fifth, on create and update endpoints, the body is checked for well-formedness — required fields present, quantities positive, enums valid, and the EIN and boilerplate `section_key` uniqueness rules satisfied (`ERR_INVALID_REQUEST`). Sixth, on a state-transition endpoint, the target resource must currently be in a state from which the transition is allowed (`ERR_INVALID_STATE`).

After those six come the domain-specific gates, in this order: seventh, cross-entity state gates that require a parent or related entity to be in a particular state (these surface as `ERR_ENGAGEMENT_NOT_ACTIVE`, `ERR_CLIENT_NOT_ACTIVE`, `ERR_AWARD_CLOSED`, or `ERR_OPPORTUNITY_CLOSED` depending on the relationship in play); eighth, the compliance and revision safety gates (`ERR_REPORTS_OUTSTANDING`, `ERR_OPEN_REVISIONS_BLOCK_APPROVAL`, `ERR_OPEN_REVISIONS_BLOCK_FINAL`); ninth, the submission/withdraw deadline gate (`ERR_OPPORTUNITY_CLOSED`); tenth, the aggregate and range gates on proposal readiness and the requested amount (`ERR_REQUEST_OUT_OF_RANGE`, `ERR_NO_NARRATIVE`, `ERR_EMPTY_BUDGET`, `ERR_DELIVERABLES_NOT_APPROVED`); eleventh, the fee-model fiscal gates on invoicing (`ERR_NO_AWARD_FOR_SUCCESS_FEE`, `ERR_NOTHING_TO_BILL`, `ERR_ENGAGEMENT_NOT_ACTIVE`); and twelfth, the optimistic-concurrency version checks (`ERR_STALE_PROPOSAL_VERSION`, `ERR_STALE_SUBMISSION_VERSION`). Earlier checks always mask later ones: a request that both targets a missing resource and carries a bad enum is reported as a not-found, not as an invalid request.

### 2.6. Optimistic Concurrency Control

Two write operations require the client to declare the version of a parent entity it last observed, so that it cannot blindly overwrite work it never saw.

Filing a submission carries `expected_proposal_version`, which must equal the targeted proposal's current `version`. Because filing a submission drives the proposal from `APPROVED` to `SUBMITTED` and is terminal for the proposal, it legitimately supersedes any prior view of that proposal. If another writer has advanced the proposal's `version` since the filing client last read it, the filing is rejected with `ERR_STALE_PROPOSAL_VERSION` (HTTP 412), forcing a re-read before the submission may proceed.

Creating an award carries `expected_submission_version`, which must equal the targeted submission's current `version`. A submission's `version` advances when its decision is recorded, so a writer whose view predates the recorded `ACCEPTED` decision is working from stale state; creating the award against that outdated version is rejected with `ERR_STALE_SUBMISSION_VERSION` (HTTP 412). No other endpoint accepts a version field, and none other performs this check.

### 2.7. Cross-Entity Cascades and Derived-Field Reconciliation

Many operations mutate more than one resource. Several derived fields are reconciled the moment their inputs change, and a few state transitions ripple into a related entity. Whenever such a cascade fires, each touched resource has its own `updated_at` refreshed and its own `version` incremented independently — the parent and the child each move forward on their own bookkeeping.

The derived fields maintained by reconciliation are: a client's `proposals_submitted_count`, `proposals_won_count`, and `win_rate_pct`; an engagement's `ytd_billed_cents`; a proposal's `budget_total_cents`; a deliverable's `open_revision_count`; an invoice's `line_count` and `total_cents`; an award's `compliance_status`; a match assessment's `score` and `eligible`; and a boilerplate snippet's `usage_count`. The precise inputs and formulas for each of these live in §3, near the workflow that drives them. The general rule is that these computed values are never supplied by a client and are always recomputed from their inputs whenever those inputs change or when the owning resource is read.

### 2.8. Precision, Rounding, and Monetary Conventions

All monetary amounts are stored and returned as integer cents; there is no fractional cent. Where a calculation can produce a fractional cent it is resolved by flooring to the whole cent unless a rule explicitly states otherwise — in particular, each indirect budget line and each invoice variant floors at the point its formula specifies, and the rounding order matters and is pinned per formula in §3. Two non-monetary computed values round differently: a match `score` is rounded half up to the nearest whole integer, and a client's `win_rate_pct` is rounded half up to one decimal place. Wherever a sum-then-convert-then-round order is called for, the sum is taken first, the unit conversion applied second, and the rounding applied last.

### 2.9. The Logical Clock and Scheduled Transitions

Time in this system is a logical clock, not the wall clock. At server startup the clock reads exactly `2026-03-01T00:00:00Z`, and until an operator sets it, the clock holds that default and never falls back to real time. An operator advances the clock by supplying the target instant as `to_iso8601`, an absolute ISO 8601 UTC time. Advancing the clock is the only event that closes opportunities and ages reports: any funding opportunity whose deadline is at or before the new clock instant transitions from `OPEN` to `CLOSED`, and any compliance report still awaiting filing whose due instant is at or before the new clock transitions to `LATE`, after which each affected award's compliance posture is recomputed. Operations that depend on "now" — stamping a submission's filing time, stamping a report's filing time, judging whether a deadline has passed — all read this logical clock.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clients and Cataloguing Opportunities

A client organization enters the system when an `AccountManager` registers it with its `org_name`, its `ein`, the `mission_areas` it funds work in (for example `EDUCATION` or `HEALTH`), its `annual_budget_cents`, and a primary `contact_email`. A new client opens in `ACTIVE` status with its three computed counters — `proposals_submitted_count`, `proposals_won_count`, and `win_rate_pct` — initialized to zero, the win rate specifically to `0.0`. The `ein` must be unique across all clients that are not `ARCHIVED`; a collision is a malformed-body condition reported as `ERR_INVALID_REQUEST`. A client's lifecycle runs `ACTIVE`, `SUSPENDED`, and `ARCHIVED`; an account manager may suspend a client, moving it from `ACTIVE` to `SUSPENDED`. Whether a client is currently `ACTIVE` gates downstream work, as later sections describe. Clients may be listed and optionally filtered by `status`.

In parallel, an `AccountManager` catalogues the funding landscape. A `FundingOpportunity` records the `funder_name`, a `title`, the eligible `focus_areas`, the `ceiling_amount_cents` it will fund up to, an optional `floor_amount_cents` (defaulting to zero) below which a request is too small, the `portal_name` through which submissions are filed (for example `GRANTS_GOV` or `FOUNDANT`), the hard `deadline_utc` by which a submission must be filed, and an optional `min_org_budget_cents` (defaulting to zero) that an applicant's annual budget must reach to be eligible. An opportunity opens in `OPEN` status and moves to `CLOSED` only by the clock crossing its deadline as described in §2.9. Opportunities may be listed and optionally filtered by `status` and by `portal_name`.

### 3.2. Engaging a Client and Choosing a Commercial Model

Before any billable work begins, an `AccountManager` opens an `Engagement` for a client. The engagement names its `client_id` and its `fee_model`, which is one of `SUCCESS_FEE`, `HOURLY`, or `RETAINER`. The fee model is chosen once at creation and is immutable thereafter — it is the spine of how this engagement is invoiced. The engagement also carries the fee parameters relevant to whichever model applies: `success_fee_pct` is the percentage of an award billed on a win; `hourly_rate_cents` is the cents billed per hour; `retainer_monthly_cents` is the flat monthly fee; `retainer_included_hours` is the number of hours folded into that monthly fee before overage applies; and `overage_rate_cents` is the per-hour cents charged beyond the included hours. Each of these defaults to zero when not supplied. An engagement also exposes a computed `ytd_billed_cents`, the sum of the `total_cents` of every issued invoice on the engagement in the current year.

A fresh engagement opens in `DRAFT`. An account manager activates it, moving `DRAFT` to `ACTIVE`, but only when two conditions hold. The owning client must currently be `ACTIVE`; if it is not, the activation is rejected with `ERR_CLIENT_NOT_ACTIVE`. And the fee field the chosen model requires must be present and positive: a `SUCCESS_FEE` engagement needs `success_fee_pct` greater than zero, an `HOURLY` engagement needs `hourly_rate_cents` greater than zero, and a `RETAINER` engagement needs `retainer_monthly_cents` greater than zero. A model missing its required fee field is rejected with `ERR_FEE_MODEL_INCOMPLETE`. An `ACTIVE` engagement may be paused, moving `ACTIVE` to `PAUSED`, with no further precondition. A `PAUSED` engagement may be reactivated, moving `PAUSED` back to `ACTIVE`, again only while the owning client is `ACTIVE` (otherwise `ERR_CLIENT_NOT_ACTIVE`). An engagement may be closed from either `ACTIVE` or `PAUSED`, moving it to the terminal `CLOSED` state, but only when no proposal under that engagement is still in `DRAFTING` or `IN_REVIEW`; open work blocks closure with `ERR_ENGAGEMENT_HAS_OPEN_WORK`. Engagements may be listed and filtered by `client_id` and `status`.

### 3.3. Scoring the Match and Deciding to Pursue

Matching is the bridge from a client and an opportunity to a concrete pursuit. When an `AccountManager` or `GrantWriter` creates a `MatchAssessment`, they supply only the `client_id` and the `opportunity_id`; the system computes the assessment's `score` and its `eligible` flag and opens it in `PROPOSED` status. A match may be listed and filtered by `client_id`, `opportunity_id`, and `status`.

Eligibility is a hard gate evaluated first. The client is eligible for the opportunity only when two things both hold: the intersection of the client's `mission_areas` with the opportunity's `focus_areas` contains at least one shared area, and the client's `annual_budget_cents` is at least the opportunity's `min_org_budget_cents`. If either fails, `eligible` is false and the `score` is zero.

When the client is eligible, the `score` is a weighted figure on a 0-to-100 scale built from three components, each a fraction between zero and one. The focus component is the count of shared focus areas divided by the number of the opportunity's focus areas — the fraction of the opportunity's areas the client covers. The budget-fit component is the client's `annual_budget_cents` divided by the larger of one and the opportunity's `ceiling_amount_cents`, capped at one. The capacity-headroom component reflects how stretched the client already is: it is one when the client has fewer than three concurrent pursuits, and otherwise it decays — it is the larger of zero and one minus one quarter for every pursuit beyond the second, where the count of concurrent pursuits is the number of this client's match assessments currently in `PURSUING` status. The raw score is fifty times the focus component plus thirty times the budget-fit component plus twenty times the headroom component; the stored `score` is that raw figure rounded half up to the nearest whole integer.

An `AccountManager` or `GrantWriter` may pursue a match, moving `PROPOSED` to `PURSUING`, but only while the client is `ACTIVE` (otherwise `ERR_CLIENT_NOT_ACTIVE`); pursuing is what makes the match attachable by a proposal. Either of those roles may also decline a match. Declining from `PROPOSED` to the terminal `DECLINED` state is unconditional. Declining from `PURSUING` to `DECLINED` is permitted only when no proposal under that match is in `DRAFTING`, `IN_REVIEW`, or `APPROVED`; if such a proposal exists, the decline is rejected with `ERR_INVALID_STATE`.

### 3.4. Building the Proposal, its Budget, and its Narrative

A `GrantWriter` opens a `Proposal` by naming its `engagement_id` (which supplies the client), its `match_id` (which supplies the opportunity being pursued), and the `requested_amount_cents` it will ask the funder for. The referenced match must be in `PURSUING` status at the time the proposal is created; attaching to a match that is not pursuing is rejected with `ERR_MATCH_NOT_PURSUING`. A new proposal opens in `DRAFTING` with its `revision_round` at zero and its computed `budget_total_cents` at zero. The `revision_round` increments by one each time the proposal returns from `IN_REVIEW` to `DRAFTING`. Proposals may be listed and filtered by `engagement_id`, `match_id`, and `status`.

The budget is assembled from `BudgetLine` rows, each created by a `GrantWriter` against a `proposal_id`. A line carries a `category` (one of `PERSONNEL`, `EQUIPMENT`, `TRAVEL`, `INDIRECT`, or `OTHER`), a `label` describing it, an `amount_cents` direct cost that is required and must be a non-negative integer for every non-`INDIRECT` category, and — for `INDIRECT` lines only — an `indirect_rate_pct` that defaults to zero. An `INDIRECT` line does not require an `amount_cents` in its body; any supplied `amount_cents` is ignored and its stored `amount_cents` is instead derived from the rate calculation below (seeded at zero until that recomputation runs). Adding a line recomputes the owning proposal's `budget_total_cents`, and the recomputation order is pinned. Direct lines are summed first: the modified direct base is the sum of `amount_cents` across the lines whose category is `PERSONNEL`, `TRAVEL`, or `OTHER`. Notably, `EQUIPMENT` is excluded from that indirect base even though it is included in the final total. Then, processing the `INDIRECT` lines in ascending creation order, each indirect line's own `amount_cents` is set to the direct base multiplied by that line's `indirect_rate_pct` divided by one hundred, floored to whole cents. Finally, `budget_total_cents` is the sum of `amount_cents` over every line of every category — direct lines, equipment, and the freshly computed indirect lines together. Each indirect line is floored individually before the final sum is taken, never floored once at the end. Budget lines may be listed and filtered by `proposal_id` and `category`.

The substance of a proposal lives in its deliverables. A `GrantWriter` creates a `Deliverable` against a `proposal_id`, choosing its `kind` (one of `NARRATIVE`, `BUDGET_JUSTIFICATION`, or `ATTACHMENT`), giving it a `title`, and optionally seeding its `body` text directly. A deliverable carries two genuinely independent state dimensions. Its `content_status` describes the maturity of the writing and runs `OUTLINE`, `DRAFTED`, `FINAL`; its `approval_status` describes the client's verdict and runs `UNREVIEWED`, `CHANGES_REQUESTED`, `APPROVED`. A deliverable also exposes a computed `open_revision_count`, the number of revision requests against it that are still open. A grant writer may edit a deliverable's `body` text at any time without disturbing either dimension. Deliverables may be listed and filtered by `proposal_id` and `kind`.

To reuse text the client has already approved elsewhere, a `GrantWriter` maintains a per-client boilerplate library. A `BoilerplateSnippet` records its `client_id`, a `section_key` slot label such as `ORG_HISTORY`, and the reusable `body`. Its `section_key` must be unique among that client's `ACTIVE` snippets; a duplicate is rejected as `ERR_INVALID_REQUEST`. A snippet opens `ACTIVE` with its computed `usage_count` at zero, and may be retired, moving `ACTIVE` to `RETIRED`, which frees its `section_key` for reuse by a new active snippet. When a grant writer creates a deliverable, they may pass an `import_snippet_id`; doing so seeds the new deliverable's `body` from that snippet and recomputes the snippet's `usage_count`, which counts the deliverables that imported it. Snippets may be listed and filtered by `client_id`, `section_key`, and `status`.

### 3.5. Review, Revision, and the Approval Cycle

The content of a deliverable advances along its own axis. A `GrantWriter` advances the content one step at a time. Moving `content_status` from `OUTLINE` to `DRAFTED` requires that the deliverable's `body` is non-empty; an empty body is rejected with `ERR_EMPTY_BODY`. Moving `content_status` from `DRAFTED` to `FINAL` requires that the deliverable has no open revision requests — its `open_revision_count` must be zero — otherwise the advance is rejected with `ERR_OPEN_REVISIONS_BLOCK_FINAL`.

Review is the client's axis and is driven by the `ClientContact` who owns the deliverable's client. To request changes, the contact opens a `RevisionRequest` against a `deliverable_id`, supplying a `note` describing the requested change and optionally a `supersedes_revision_id` pointing at a prior open request on the same deliverable that this one replaces. A deliverable can only be reviewed once its content has progressed past outline: opening a revision request requires the deliverable's `content_status` to be either `DRAFTED` or `FINAL`, and attempting to review an `OUTLINE` deliverable is rejected with `ERR_NOT_REVIEWABLE`. Opening a revision request creates it in `OPEN`, drives the deliverable's `approval_status` from `UNREVIEWED` to `CHANGES_REQUESTED`, and recomputes the deliverable's `open_revision_count`. When a `supersedes_revision_id` is given, the referenced open request transitions to `SUPERSEDED` as the new one is created; the superseded request no longer counts toward the open count while the new one does, and the deliverable's `open_revision_count` reflects that net change. Revision requests carry their own lifecycle of `OPEN`, `RESOLVED`, and `SUPERSEDED`, and may be listed and filtered by `deliverable_id`, `supersedes_revision_id`, and `status`.

A `GrantWriter` resolves an open revision request, moving it from `OPEN` to `RESOLVED` and recomputing the owning deliverable's `open_revision_count` downward. Once a deliverable's content is at least `DRAFTED` and it carries no open revisions, a `ClientContact` who owns its client may approve it. Approval drives `approval_status` to `APPROVED`. From `CHANGES_REQUESTED` this requires only that `open_revision_count` is zero — every revision request resolved or superseded — otherwise the approval is rejected with `ERR_OPEN_REVISIONS_BLOCK_APPROVAL`. Approving directly from `UNREVIEWED` is also allowed, but in that case both conditions are checked: the `content_status` must be `DRAFTED` or `FINAL` (otherwise `ERR_NOT_REVIEWABLE`) and `open_revision_count` must be zero (otherwise `ERR_OPEN_REVISIONS_BLOCK_APPROVAL`).

### 3.6. Submitting the Proposal for Review and Approval

When the writer believes a proposal is ready, a `GrantWriter` submits it for review, moving the proposal from `DRAFTING` to `IN_REVIEW`. Three conditions guard this transition. The owning engagement must currently be `ACTIVE`, or the request is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`. The proposal must have at least one deliverable whose `kind` is `NARRATIVE`, or it is rejected with `ERR_NO_NARRATIVE`. And the proposal's `budget_total_cents` must be greater than zero, or it is rejected with `ERR_EMPTY_BUDGET`.

Once a proposal is `IN_REVIEW`, the owning `ClientContact` decides its fate, and only the contact who owns the proposal's client may act — any other contact is rejected with `ERR_NOT_RESOURCE_OWNER`. The contact may request changes, returning the proposal from `IN_REVIEW` to `DRAFTING`. This is the revision-cycle edge and may repeat: a proposal can go `IN_REVIEW`, back to `DRAFTING`, and into `IN_REVIEW` again. Requesting changes increments the proposal's `revision_round` by one and, as a cascade, resets every deliverable under that proposal whose `approval_status` is `APPROVED` back to `CHANGES_REQUESTED`, so previously cleared work must be re-blessed after substantive changes. Alternatively, the owning contact may approve the proposal, moving it from `IN_REVIEW` to `APPROVED`, but only when every deliverable under the proposal has `approval_status` equal to `APPROVED`; if any deliverable is not approved, the request is rejected with `ERR_DELIVERABLES_NOT_APPROVED`. A `GrantWriter` may withdraw a proposal from either `DRAFTING` or `IN_REVIEW` to the terminal `WITHDRAWN` state at any time, with no further precondition.

### 3.7. Filing the Submission and Recording the Funder's Decision

Filing the submission is the act that sends an approved proposal to the funder. A `GrantWriter` files a `Submission` by naming the `proposal_id` and supplying the `expected_proposal_version` for the optimistic-concurrency check described in §2.6, plus an optional `decision_due_utc` recording when the funder is expected to decide, which defaults to null when not supplied. Filing requires the proposal to be in `APPROVED` status and drives it to the terminal `SUBMITTED` state. Two further gates apply. The opportunity behind the proposal must be `OPEN` with the logical clock strictly before its `deadline_utc`; a closed or past-deadline opportunity is rejected with `ERR_OPPORTUNITY_CLOSED`. And the proposal's `requested_amount_cents` must fall within the opportunity's band — at least the `floor_amount_cents` and at most the `ceiling_amount_cents` — otherwise the filing is rejected with `ERR_REQUEST_OUT_OF_RANGE`. A successful filing creates the submission in `FILED`, stamps it with the opportunity's `portal_name` copied at submission time and a `submitted_at_utc` set to the current logical clock, advances the proposal's `version` by one, and recomputes the client's `proposals_submitted_count`, which counts the client's proposals that ever reached `SUBMITTED` through a submission. Submissions may be listed and filtered by `proposal_id` and `status`.

A submission's status is `FILED`, `ACCEPTED`, `REJECTED`, or `WITHDRAWN`. An `AccountManager` records the funder's verdict on a filed submission via a `decision` of either `ACCEPTED` or `REJECTED`, and the two branches diverge. Recording `ACCEPTED` moves the submission from `FILED` to `ACCEPTED`, requires that the funding opportunity behind the proposal still exists (a missing one surfaces as `ERR_NOT_FOUND`), increments the submission's `version` by one, recomputes the client's `proposals_won_count` upward, recomputes the client's `win_rate_pct`, and makes an award creatable from this submission. Recording `REJECTED` moves the submission from `FILED` to `REJECTED`, has no precondition, increments the submission's `version` by one, and recomputes the client's `win_rate_pct` — here the denominator of decided submissions grows while the won numerator is unchanged. The win rate itself is computed over decided submissions only: the denominator is the count of this client's submissions in `ACCEPTED` or `REJECTED` status, with `FILED` and `WITHDRAWN` submissions excluded, and the numerator is the count in `ACCEPTED`. When the client has no decided submissions the `win_rate_pct` is exactly `0.0` rather than null; otherwise it is one hundred times the won count divided by the decided count, rounded half up to one decimal place.

A `GrantWriter` may withdraw a filed submission, moving it from `FILED` to the terminal `WITHDRAWN` state, but only while the clock is strictly before the opportunity's `deadline_utc`; a past-deadline withdrawal is rejected with `ERR_OPPORTUNITY_CLOSED`. Withdrawing a submission cascades: the owning proposal is also moved to `WITHDRAWN`, and the client's `proposals_submitted_count` is recomputed because this proposal no longer counts as submitted.

### 3.8. Booking Time and Issuing Invoices

Throughout an engagement, a `GrantWriter` or `AccountManager` logs effort as `TimeEntry` rows. A time entry names its `engagement_id`, optionally a `proposal_id` the work relates to, the `minutes` worked (which must be greater than zero), and the billing `period_yyyymm` in which it falls, written as a six-character year-and-month such as `202603`. A new time entry opens in `LOGGED` and becomes `BILLED` once an invoice sweeps it. Time entries may be listed and filtered by `engagement_id`, `proposal_id`, `period_yyyymm`, and `status`.

An `AccountManager` issues an `Invoice` against an `engagement_id`. The invoice's `kind` is derived from the engagement's fee model and the issue, and is `SUCCESS_FEE`, `HOURLY`, or `RETAINER`; its computed `line_count` and `total_cents` follow whichever variant applies; and it opens in `ISSUED` with the option to later be voided. The engagement must be `ACTIVE` to be billable, or the issue is rejected with `ERR_ENGAGEMENT_NOT_ACTIVE`. Invoices may be listed and filtered by `engagement_id`, `award_id`, and `status`.

For an `HOURLY` engagement, the issuing client supplies a `period_start_yyyymm` and an inclusive `period_end_yyyymm`, where the end month must not be earlier than the start month. The invoice sweeps every time entry on the engagement whose `status` is `LOGGED` and whose `period_yyyymm` lies in the closed month interval from the start month through the end month inclusive. The total is computed by summing the swept `minutes`, dividing that sum by sixty to convert to hours, multiplying by the engagement's `hourly_rate_cents`, and flooring to whole cents — the sum is taken first, then the conversion, then the rounding. The `line_count` is the number of time entries swept, and each swept entry transitions to `BILLED`. If no `LOGGED` time exists in the window to sweep, the issue is rejected with `ERR_NOTHING_TO_BILL`.

For a `RETAINER` engagement, the client likewise supplies a `period_start_yyyymm` and an inclusive `period_end_yyyymm` (typically a single month). The invoice sweeps the engagement's `LOGGED` time entries over that same closed month window, summing their `minutes` into billed minutes and dividing by sixty to obtain billed hours without rounding yet. Overage hours are the billed hours minus the engagement's `retainer_included_hours`, but never less than zero. The total is the engagement's `retainer_monthly_cents` plus the overage hours multiplied by `overage_rate_cents`, with that overage product floored to whole cents. The `line_count` for a retainer invoice is zero, and the swept entries still transition to `BILLED`.

For a `SUCCESS_FEE` engagement, the client supplies an `award_id` naming a won award rather than a billing period. The total is the award's `awarded_amount_cents` multiplied by the engagement's `success_fee_pct` divided by one hundred, floored to whole cents. The `line_count` is zero and no time entries are swept. A success-fee invoice issued without a valid won award is rejected with `ERR_NO_AWARD_FOR_SUCCESS_FEE`; the `period_start_yyyymm`, `period_end_yyyymm`, and `award_id` fields default to null on invoices, and only the success-fee variant uses `award_id`.

The billing calendar must not double-bill. Each `HOURLY` or `RETAINER` invoice claims the closed month interval running from its `period_start_yyyymm` through its `period_end_yyyymm`. A new such interval may not overlap the interval of any existing issued (non-void) invoice on the same engagement, where two closed month intervals overlap when each one's start is not after the other one's end — treating the YYYYMM values as month indices. Under these closed-interval semantics, two intervals that share even a single endpoint month overlap and the new invoice is rejected with `ERR_BILLING_PERIOD_OVERLAP`, whereas two consecutive but non-touching month intervals do not overlap and are both allowed. Void invoices are excluded from this check. Issuing any invoice recomputes the engagement's `ytd_billed_cents`.

An `AccountManager` may void an invoice, moving it from `ISSUED` to `VOID`. Voiding restores every time entry the invoice had swept back to `LOGGED` and recomputes the engagement's `ytd_billed_cents`.

### 3.9. Post-Award Compliance and Close-Out

When a submission is accepted, a `ComplianceOfficer` or `AccountManager` records the award. Creating an `Award` names the `submission_id`, supplies the `expected_submission_version` for the optimistic-concurrency check in §2.6, and records the `awarded_amount_cents` (which may differ from the requested amount), the `period_of_performance_months` over which the work runs, and an optional `report_cadence_months` (defaulting to three) giving the spacing between required reports. The underlying submission must be in `ACCEPTED` status, or the create is rejected with `ERR_SUBMISSION_NOT_ACCEPTED`. A successful create opens the award in `ACTIVE` with its computed `compliance_status` at `GREEN`, advances the submission's `version` by one, and generates the award's compliance report schedule. Awards may be listed and filtered by `submission_id` and `status`.

The schedule is generated deterministically at award creation. The number of scheduled reports is the period of performance in months divided by the report cadence in months, with any remainder discarded — so if the period of performance is shorter than a single cadence interval, no reports are generated at all. The reports are created in ascending order, the first carrying `sequence_index` one, the second two, and so on. Each scheduled report's `due_utc` is the award's creation instant advanced by its ordinal number of cadence-months — the first due one cadence after creation, the second two cadences after, and so forth — using calendar month arithmetic. Each report covers the window running from the prior report's due instant up to its own (with the very first report's window starting at the award's creation instant), recorded in `covers_window_start_utc`, and opens with `report_type` of `SCHEDULED` and `status` of `PENDING`.

A `ComplianceReport` therefore carries an `award_id`, a `due_utc` that is both its deadline and the inclusive end of its coverage window, the `covers_window_start_utc` marking the open start of that window, a `report_type` of either `SCHEDULED` or `SUPPLEMENTAL`, a `sequence_index` ordinal, a `submitted_at_utc` (null until filed), and a `status` of `PENDING`, `FILED`, or `LATE`. Reports may be listed and filtered by `award_id` and `status`. A `ComplianceOfficer` files a report, moving it from `PENDING` to `FILED`, or from `LATE` to `FILED`; either filing requires the owning award to still be `ACTIVE` (a closed-out award is rejected with `ERR_AWARD_CLOSED`), stamps `submitted_at_utc` to the current logical clock, and recomputes the award's `compliance_status`. As described in §2.9, the clock crossing a still-pending report's `due_utc` flips it to `LATE` and recomputes the award's posture. The compliance posture is a threshold over the count of this award's reports currently in `LATE` status: with zero late reports the status is `GREEN`; with exactly one late report it is `AT_RISK`; with two or more late reports it is `DELINQUENT`.

A `ComplianceOfficer` may also insert a supplemental report into an active award. Such a report names the `award_id`, the `covers_window_start_utc` and `due_utc` defining the window it covers, and a `sequence_index`; it is created with `report_type` `SUPPLEMENTAL` and `status` `PENDING`, and its creation recomputes the award's `compliance_status`. A supplemental report claims the half-open coverage window running from just after its `covers_window_start_utc` up to and including its `due_utc`. This window may not overlap any existing report window on the same award — scheduled or supplemental, in any status — where two half-open windows overlap when each one's start is strictly before the other one's end. Under these half-open semantics a window that begins exactly where another ends merely touches and does not overlap and is allowed, whereas any genuine interior overlap is rejected with `ERR_REPORT_WINDOW_OVERLAP`. This deliberately differs from the closed-interval billing rule of §3.8, which treats a shared endpoint month as an overlap.

Finally, a `ComplianceOfficer` closes out an award, moving it from `ACTIVE` to the terminal `CLOSED_OUT` state, but only when the award has no compliance report still in `PENDING` or `LATE`; any outstanding report blocks close-out with `ERR_REPORTS_OUTSTANDING`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/grant-desk` prefix. Creating a new resource returns HTTP 201; reads, list retrievals, and state-changing actions on an existing resource return HTTP 200. The clock endpoint returns 200. Request bodies, response bodies, and side effects for each endpoint are described in the §3 narratives above; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/grant-desk/_clock/set_current_utc` | Set the logical clock to an absolute instant; closes due opportunities and ages due reports | Ops |
| POST | `/grant-desk/clients` | Create a client | AccountManager |
| GET | `/grant-desk/clients/{id}` | Get a client with computed win-rate fields | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/clients` | List clients | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/clients/{id}/suspend` | Suspend a client | AccountManager |
| POST | `/grant-desk/opportunities` | Create a funding opportunity | AccountManager |
| GET | `/grant-desk/opportunities/{id}` | Get a funding opportunity | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/opportunities` | List funding opportunities | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/engagements` | Create an engagement | AccountManager |
| GET | `/grant-desk/engagements/{id}` | Get an engagement with year-to-date billing | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/engagements` | List engagements | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/engagements/{id}/activate` | Activate an engagement | AccountManager |
| POST | `/grant-desk/engagements/{id}/pause` | Pause an engagement | AccountManager |
| POST | `/grant-desk/engagements/{id}/close` | Close an engagement | AccountManager |
| POST | `/grant-desk/matches` | Create a match assessment | AccountManager, GrantWriter |
| GET | `/grant-desk/matches/{id}` | Get a match assessment | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/matches` | List match assessments | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/matches/{id}/pursue` | Mark a match pursuing | AccountManager, GrantWriter |
| POST | `/grant-desk/matches/{id}/decline` | Decline a match | AccountManager, GrantWriter |
| POST | `/grant-desk/proposals` | Create a proposal | GrantWriter |
| GET | `/grant-desk/proposals/{id}` | Get a proposal with budget total | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/proposals` | List proposals | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/proposals/{id}/submit-for-review` | Send a proposal into review | GrantWriter |
| POST | `/grant-desk/proposals/{id}/request-changes` | Return a proposal for changes | ClientContact |
| POST | `/grant-desk/proposals/{id}/approve` | Approve a proposal | ClientContact |
| POST | `/grant-desk/proposals/{id}/withdraw` | Withdraw a proposal | GrantWriter |
| POST | `/grant-desk/budget-lines` | Add a budget line | GrantWriter |
| GET | `/grant-desk/budget-lines/{id}` | Get a budget line | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/budget-lines` | List budget lines | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/deliverables` | Create a deliverable, optionally importing a snippet | GrantWriter |
| GET | `/grant-desk/deliverables/{id}` | Get a deliverable with both state dimensions | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/deliverables` | List deliverables | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| PATCH | `/grant-desk/deliverables/{id}` | Update a deliverable's body text | GrantWriter |
| POST | `/grant-desk/deliverables/{id}/advance-content` | Advance a deliverable's content dimension | GrantWriter |
| POST | `/grant-desk/deliverables/{id}/approve` | Approve a deliverable | ClientContact |
| POST | `/grant-desk/revision-requests` | Open a revision request | ClientContact |
| GET | `/grant-desk/revision-requests/{id}` | Get a revision request | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/revision-requests` | List revision requests | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/revision-requests/{id}/resolve` | Resolve a revision request | GrantWriter |
| POST | `/grant-desk/submissions` | File a submission for an approved proposal | GrantWriter |
| GET | `/grant-desk/submissions/{id}` | Get a submission | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/submissions` | List submissions | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/submissions/{id}/record-decision` | Record the funder's accept/reject decision | AccountManager |
| POST | `/grant-desk/submissions/{id}/withdraw` | Withdraw a submission | GrantWriter |
| POST | `/grant-desk/time-entries` | Log billable time | GrantWriter, AccountManager |
| GET | `/grant-desk/time-entries/{id}` | Get a time entry | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/time-entries` | List time entries | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/invoices` | Issue an invoice per the engagement's fee model | AccountManager |
| GET | `/grant-desk/invoices/{id}` | Get an invoice | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/invoices` | List invoices | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/invoices/{id}/void` | Void an invoice | AccountManager |
| POST | `/grant-desk/awards` | Create an award from an accepted submission | ComplianceOfficer, AccountManager |
| GET | `/grant-desk/awards/{id}` | Get an award with compliance status | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/awards` | List awards | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/awards/{id}/close-out` | Close out an award | ComplianceOfficer |
| POST | `/grant-desk/compliance-reports` | Insert a supplemental compliance report | ComplianceOfficer |
| GET | `/grant-desk/compliance-reports/{id}` | Get a compliance report | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/compliance-reports` | List compliance reports | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/compliance-reports/{id}/file` | File a compliance report | ComplianceOfficer |
| POST | `/grant-desk/boilerplate` | Create a boilerplate snippet | GrantWriter |
| GET | `/grant-desk/boilerplate/{id}` | Get a boilerplate snippet | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| GET | `/grant-desk/boilerplate` | List boilerplate snippets | AccountManager, GrantWriter, ClientContact, ComplianceOfficer, Ops |
| POST | `/grant-desk/boilerplate/{id}/retire` | Retire a boilerplate snippet | GrantWriter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_CLIENT_NOT_ACTIVE | 409 |
| ERR_ENGAGEMENT_NOT_ACTIVE | 409 |
| ERR_ENGAGEMENT_HAS_OPEN_WORK | 409 |
| ERR_AWARD_CLOSED | 409 |
| ERR_OPPORTUNITY_CLOSED | 409 |
| ERR_MATCH_NOT_PURSUING | 409 |
| ERR_NO_NARRATIVE | 409 |
| ERR_EMPTY_BUDGET | 409 |
| ERR_DELIVERABLES_NOT_APPROVED | 409 |
| ERR_REQUEST_OUT_OF_RANGE | 409 |
| ERR_EMPTY_BODY | 409 |
| ERR_NOT_REVIEWABLE | 409 |
| ERR_OPEN_REVISIONS_BLOCK_APPROVAL | 409 |
| ERR_OPEN_REVISIONS_BLOCK_FINAL | 409 |
| ERR_FEE_MODEL_INCOMPLETE | 409 |
| ERR_NO_AWARD_FOR_SUCCESS_FEE | 409 |
| ERR_NOTHING_TO_BILL | 409 |
| ERR_BILLING_PERIOD_OVERLAP | 409 |
| ERR_REPORTS_OUTSTANDING | 409 |
| ERR_SUBMISSION_NOT_ACCEPTED | 409 |
| ERR_REPORT_WINDOW_OVERLAP | 409 |
| ERR_STALE_PROPOSAL_VERSION | 412 |
| ERR_STALE_SUBMISSION_VERSION | 412 |
| ERR_INVALID_PAGINATION | 400 |

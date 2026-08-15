# Payment Integrity Editing API — Product Requirements Document

## 1. Introduction

Health plans have historically paid provider claims first and recovered overpayments later, an expensive "pay and chase" posture that strains provider relationships and depresses recovery rates. Payment integrity moves detection upstream of the check run: a governed library of clinical, coding, and policy edits screens every claim before payment, pends suspicious lines for human review, prices inpatient stays by diagnosis-related group rather than billed charges, and routes high-dollar claims to itemized bill audit. Because plans also license external edit catalogs, the same screening run must attribute savings without double-counting vendor edits that duplicate internal ones, and it must track how often edits turn out to be wrong — both to suspend underperforming edits automatically and to measure the abrasion the program inflicts on network providers.

This document specifies the API for that pre-pay payment integrity platform. It covers the edit library's draft-through-retirement lifecycle with segregation of duties between authors and approvers; claim intake and screening with DRG-based pricing, readmission detection, and high-dollar flagging; the reviewer task workflow with capacity limits and escalation; provider disputes with decision windows and adjudication segregation; provider abrasion scoring that can soften enforcement for over-abraded providers to a monitor-only posture; and monthly savings reconciliation that separates an optimistic pipeline view from an audited, finalized number. Business rules are stated where they naturally belong in the workflow narrative of Section 3, while structural contracts that must not diverge are collected in Section 2.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role under which that operator acts. A request missing either header, or carrying a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Eight roles are declared, with these exact spellings: `Provider`, `PlanAdmin`, `EditLibrarian`, `EditApprover`, `Reviewer`, `SeniorReviewer`, `DisputeAdjudicator`, and `PaymentIntegrityAnalyst`. All read endpoints are open to any authenticated role.

- A `Provider` is a network provider submitting claims, disputing denials, and supplying itemized bills and dispute information.
- A `PlanAdmin` is the health plan operator running screening, payment, savings periods, vendor edit ingestion, provider administration, and the logical clock.
- An `EditLibrarian` maintains the edit library, authoring edit versions and submitting them for approval.
- An `EditApprover` approves, rejects, suspends, reactivates, and retires edit versions; segregation of duties forbids approving a version they authored.
- A `Reviewer` is a pre-pay claim reviewer who decides assigned, non-escalated review tasks.
- A `SeniorReviewer` assigns tasks, decides escalated tasks, and runs itemized bill audits and inpatient reviews.
- A `DisputeAdjudicator` adjudicates provider disputes; segregation of duties forbids deciding a dispute on a hit they confirmed as a reviewer.
- A `PaymentIntegrityAnalyst` maps vendor edits against the internal library for duplication avoidance.

The two headers interact with resource ownership as follows. When `X-User-Role` is `Provider`, `X-User-ID` is the `id` of the acting Provider; ownership checks on any resource that references a provider compare the resource's foreign-key field (for example a claim's or dispute's `provider_id`) to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). When `X-User-Role` is `PlanAdmin`, `EditLibrarian`, `EditApprover`, `Reviewer`, `SeniorReviewer`, `DisputeAdjudicator`, or `PaymentIntegrityAnalyst`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `created_by_user_id` or `approved_by_user_id` on an edit version, as `assigned_reviewer_user_id` on a review task, as `confirmed_by_user_id` on an edit hit, as `adjudicated_by_user_id` on a dispute, or as `auditor_user_id` on an itemized bill review — but it is never compared to any entity's `id`. The one exception in spirit, though not in kind, is reviewer accountability: deciding or escalating a review task requires the caller's `X-User-ID` to equal the task's `assigned_reviewer_user_id`, and acting on a task assigned to someone else is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints accept `limit` and `offset` query parameters. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0. The `meta` object of every list response carries `limit`, `offset`, `total_count`, and `has_more` so a client can page deterministically through the full result set. Unless an endpoint states otherwise, every list endpoint returns rows ordered by `created_at` ascending — earliest-created first — and no id-based ordering is used anywhere.

### 2.4. Resource Identity, Timestamps, and Entity Versions

All thirteen resources in this system — Provider, EditRule, EditVersion, VendorEdit, Claim, ClaimLine, EditHit, ReviewTask, Dispute, ItemizedBillReview, InpatientReview, ProviderAbrasionProfile, and SavingsPeriod — share the same system-maintained properties. Each resource carries an `id` minted by the server as a UUID with no type prefix. Each carries `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with exactly three fractional digits; `updated_at` refreshes on every mutation of the resource. Each also carries a `version`, an integer the server increments by one on every mutation of that resource. The `version` is the observable heartbeat used by optimistic concurrency control (Section 2.7): clients read it, and certain write endpoints require the caller to present the value they last observed.

### 2.5. Monetary Representation and Rounding

All money is represented as integer cents — fields such as `total_billed_cents`, `billed_cents`, `allowed_amount_cents`, `denied_amount_cents`, `expected_savings_cents`, `attributed_savings_cents`, `released_cents`, `findings_cents`, and `repriced_total_cents` are whole numbers, never floats. Wherever a calculation produces a fractional cent — DRG base pricing, outlier caps, per-diem proration, itemized repricing, partial reductions — the result is rounded half-up to the nearest whole cent, and each calculation in Section 3 pins the exact step at which that rounding occurs, because rounding order changes results. Rates and indices that are not money — `fp_rate`, `standard_index`, and `regulatory_index` — are rounded half-up to four decimal places.

### 2.6. The Logical Clock

Every temporal rule in this document — effective windows, dispute windows, decision deadlines, document due dates, audit occupancy intervals, trailing-90-day abrasion windows, and readmission gaps — is evaluated against a logical server clock, never against wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to wall-clock time on its own. A `PlanAdmin` may advance or set the logical clock through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`; Section 4 gives the HTTP contract for that capability.

### 2.7. Optimistic Concurrency Control

Two write endpoints are version-gated; no other endpoint takes a version field.

First, `POST /payment-integrity/edit-versions/{id}/approve` requires a non-optional `expected_edit_rule_version` carrying the client's last observed `version` of the owning EditRule. Approving any version of a rule advances the EditRule's `version` by one (the set of active windows has changed), so a client acting on a previously read rule version holds a stale view of which windows are active. If `expected_edit_rule_version` does not equal the EditRule's current `version`, the approval is rejected with `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the rule before approving.

Second, `POST /payment-integrity/claims/{id}/disputes` requires a non-optional `expected_claim_version` carrying the client's last observed `version` of the claim. Disputes target individual hits of a shared claim, and every mutation that touches the claim's dollars — task decisions, other disputes, releases — advances the claim's `version`. If `expected_claim_version` does not equal the claim's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than adjudicating against dollar amounts the client never saw.

### 2.8. Request Validation Order and Error Precedence

When several things are wrong with one request, the response is not arbitrary: validation runs in a fixed order of precedence bands, and a failure in an earlier band masks every later check. The bands, earliest first, are:

1. **Authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is a declared role, else `ERR_UNAUTHENTICATED` (HTTP 401).
2. **Authorization.** The caller's role is listed for the endpoint, else `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Ownership.** A `Provider` caller acts only on resources carrying their own `provider_id` — claim creation, claim line addition, dispute creation, dispute info submission, and itemized-bill document receipt — and a reviewer acts only on tasks assigned to them, else `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
4. **Request shape.** Required fields are present, types are correct, and no unknown fields appear, else `ERR_INVALID_REQUEST` (HTTP 400); enum-typed fields carry a declared member, else `ERR_INVALID_ENUM` (HTTP 400).
5. **Reference existence.** Path and body references resolve left to right — the provider first, then the claim, the edit rule (the `ruleId` path parameter on version-creation URLs), the edit version, the edit hit (including the body-supplied `edit_hit_id` on dispute creation), the review task, the dispute, the itemized bill review, the inpatient review, the savings period, and finally the vendor edit — each unresolved reference producing its own 404: `ERR_PROVIDER_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EDIT_RULE_NOT_FOUND`, `ERR_EDIT_VERSION_NOT_FOUND`, `ERR_EDIT_HIT_NOT_FOUND`, `ERR_REVIEW_TASK_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_IBR_NOT_FOUND`, `ERR_INPATIENT_REVIEW_NOT_FOUND`, `ERR_SAVINGS_PERIOD_NOT_FOUND`, or `ERR_VENDOR_EDIT_NOT_FOUND`. On nested URLs the leftmost path parameter is validated before anything to its right.
6. **Optimistic concurrency.** The stale-version checks of Section 2.7, else `ERR_STALE_VERSION` (HTTP 412).
7. **State preconditions.** Each state machine's from-state requirement, surfacing the state-family errors (`ERR_CLAIM_NOT_SCREENABLE`, `ERR_CLAIM_NOT_PAYABLE`, `ERR_CLAIM_LINES_LOCKED`, `ERR_EDIT_VERSION_NOT_APPROVABLE`, `ERR_REVIEW_TASK_NOT_DECIDABLE`, `ERR_DISPUTE_NOT_DECIDABLE`, `ERR_DISPUTE_NOT_OPEN`, `ERR_IBR_NOT_COMPLETABLE`, `ERR_INPATIENT_REVIEW_NOT_DECIDABLE`, `ERR_PERIOD_NOT_FINALIZABLE`), all HTTP 409.
8. **Safety and segregation of duties.** Clinical attestation, author-versus-approver and reviewer-versus-adjudicator segregation, terminated-provider screening blocks, and senior-review requirements (`ERR_CLINICAL_ATTESTATION_REQUIRED`, `ERR_SOD_AUTHOR_APPROVAL`, `ERR_SOD_REVIEWER_ADJUDICATION`, `ERR_PROVIDER_TERMINATED`, `ERR_SENIOR_REVIEW_REQUIRED`).
9. **Business constraints.** Edit window overlap, one-open-dispute-per-hit, reviewer capacity, and savings-period key uniqueness (`ERR_EDIT_WINDOW_OVERLAP`, `ERR_DISPUTE_ALREADY_OPEN`, `ERR_REVIEWER_CAPACITY_EXCEEDED`, `ERR_DUPLICATE_PERIOD_KEY`).
10. **Temporal windows.** Dispute windows, decision deadlines, audit occupancy, and document-due expirability (`ERR_DISPUTE_WINDOW_EXPIRED`, `ERR_DECISION_DEADLINE_PASSED`, `ERR_PROVIDER_AUDIT_OVERLAP`, `ERR_IBR_NOT_YET_EXPIRABLE`).
11. **Referential integrity.** Retire-while-in-use, hit-belongs-to-claim, and known-DRG checks (`ERR_EDIT_VERSION_IN_USE`, `ERR_HIT_NOT_ON_CLAIM`, `ERR_DRG_CODE_UNKNOWN`).
12. **Fiscal reconciliation.** Line-sum equality, at-least-one-line, and partial-release bounds (`ERR_LINE_AMOUNT_MISMATCH`, `ERR_NO_CLAIM_LINES`, `ERR_INVALID_RELEASE_AMOUNT`).

Because the bands are ordered, a caller who fixes an early error may legitimately meet a different error on retry — that is the precedence working, not instability.

### 2.9. Segregation of Duties

Two segregation-of-duties walls are load-bearing. The edit library separates authorship from activation: the operator who approves an edit version must not be the operator recorded as that version's `created_by_user_id`, and a self-approval attempt is rejected with `ERR_SOD_AUTHOR_APPROVAL` (HTTP 403). Dispute adjudication separates confirmation from adjudication: the operator who decides a dispute must not be the operator recorded as the disputed hit's `confirmed_by_user_id`, and a violation is rejected with `ERR_SOD_REVIEWER_ADJUDICATION` (HTTP 403). Both walls compare the caller's `X-User-ID` against the recorded operator id; neither comparison involves any entity's `id`, because both roles are opaque-identity roles.

### 2.10. The Claim Ledger Invariant

Every claim behaves as a small two-column ledger. Screening establishes `initial_allowed_cents` — the DRG payment for an inpatient claim, the billed total otherwise — and from that moment the invariant `allowed_amount_cents` plus `denied_amount_cents` equals `initial_allowed_cents` holds without exception. Every operation that moves money on the claim — applying an edit hit, overriding or overturning a hit, superseding a hit on suspension, reassigning a DRG, denying a readmission, taking a partial reduction, or repricing through an itemized bill review — rebalances both columns so the invariant still holds afterward, and `allowed_amount_cents` is never driven below zero.

## 3. Business Logic & Workflows

### 3.1. Provider Enrollment and the Abrasion Profile

A `PlanAdmin` enrolls a network provider by supplying its `npi` — the National Provider Identifier, free-text with no uniqueness constraint — and a display `name`. A new provider's `status` defaults to `ACTIVE`; the plan may later patch that `status` to `TERMINATED`, after which the provider's claims can no longer pass screening (Section 3.4). Providers can be listed with an optional `status` filter.

Enrollment has a permanent side effect: the server auto-creates a ProviderAbrasionProfile, one-to-one with the provider, with every counter zeroed — `confirmed_count`, `overridden_count`, `fp_count`, `superseded_count`, `denied_cents_lifetime`, `released_cents_lifetime`, and `open_ibr_count` all start at zero, `standard_index` and `regulatory_index` start at zero, `tier` starts `LOW`, and `monitor_only` starts false. The profile exists so the plan can see, in one place, how often this provider's denied lines are overturned and how much money has flowed back.

The profile recomputes every time an edit hit on one of the provider's claims resolves, and whenever an itemized bill review for the provider opens or closes. The trailing-window counts — `confirmed_count`, `overridden_count`, `fp_count`, and `superseded_count` — tally the provider's hits whose `resolved_at` falls within the last 90 days, broken down by resolution status (`CONFIRMED`, `OVERRIDDEN`, `RELEASED_FALSE_POSITIVE`, and `SUPERSEDED` respectively). The lifetime columns `denied_cents_lifetime` and `released_cents_lifetime` sum `attributed_savings_cents` and `released_cents` across all of the provider's resolved hits with no time bound. The `open_ibr_count` tracks how many of the provider's itemized bill reviews currently sit in `REQUESTED`, `DOCUMENTS_RECEIVED`, or `IN_AUDIT`.

Two indices summarize the abrasion picture. The `standard_index` is count-weighted over the trailing 90-day resolved population: it blends the overturn rate — the share of resolved hits that ended `OVERRIDDEN` or `RELEASED_FALSE_POSITIVE` — at sixty percent weight with the false-positive rate — the share that ended `RELEASED_FALSE_POSITIVE` — at forty percent weight, and the blend is rounded half-up to four decimal places; when the provider has no resolved hits in the window, both rates and the index are zero. The `tier` keys on `standard_index` only: `HIGH` when the index reaches 0.50, `MEDIUM` when it reaches 0.25 but not 0.50, otherwise `LOW`. The `regulatory_index` is the dollar-weighted, lifetime reporting view: lifetime released cents divided by lifetime denied cents, substituting one for the lifetime denied total when that total is zero, rounded half-up to four decimal places; it is computed for regulatory reporting and never drives the tier. The `monitor_only` flag is true exactly when `tier` is `HIGH`, and — as Section 3.4 details — a `HIGH`-tier provider's new hits are recorded without denying dollars. Profiles can be listed, optionally filtered by `provider_id`.

### 3.2. Edit Library Governance: Authoring Through Retirement

The edit library is a set of rules, each versioned. An `EditLibrarian` creates a rule with a business `edit_code` (free-text, such as MU-UNIT-01), a `category` of `CLINICAL`, `CODING`, or `POLICY`, a `source` — `INTERNAL` for plan-authored edits, `VENDOR` for externally supplied edits mirrored into the library — and an optional `description` that defaults to empty. A new rule's `active_version_count` is zero. Rules can be listed with optional `category` and `source` filters.

Versions of a rule are drafted by an `EditLibrarian` through the rule's versions collection (the rule is identified by the URL's `ruleId`). Each version carries a `severity` — `DENY` for a full line denial, `SUSPEND` to pend the line for a reviewer, `MONITOR` to record only — a non-empty `applies_to_claim_types` list whose members each name one of `PROFESSIONAL`, `INSTITUTIONAL_INPATIENT`, or `INSTITUTIONAL_OUTPATIENT`, an opaque `logic_expression` text, and an effectiveness window: `effective_from` is the inclusive window start, and the optional `effective_to` is the exclusive window end, so the window is half-open and an omitted `effective_to` means the version is open-ended. A new version is born in `DRAFT`; the server assigns its `version_number` sequentially within the rule starting at 1 in creation order, and records the authoring librarian in `created_by_user_id`. Creating a version does not advance the rule's `version` — only approval does that. Individual versions can be fetched, and a cross-rule version list supports optional `edit_rule_id` and `status` filters, which is how a caller reaches versions without walking each rule.

Submission moves a version from `DRAFT` to `PENDING_APPROVAL`. Approval, rejection, suspension, reactivation, and retirement are all `EditApprover` actions, and every one of them is state-guarded: submission requires `DRAFT`, approval and rejection require `PENDING_APPROVAL`, suspension requires `ACTIVE`, reactivation requires `SUSPENDED`, and retirement requires `ACTIVE` or `SUSPENDED`; `RETIRED` is terminal and accepts no further action. Any edit-version action attempted from a status that does not permit it is rejected with `ERR_EDIT_VERSION_NOT_APPROVABLE` (HTTP 409).

Approval is the most guarded transition in the system, and its checks have a fixed surfacing order. The stale-version check of Section 2.7 runs first: the request must carry `expected_edit_rule_version` equal to the rule's current `version`, else `ERR_STALE_VERSION`. Next the version must actually be `PENDING_APPROVAL`. Then segregation of duties: the approver's `X-User-ID` must differ from the version's `created_by_user_id`, else `ERR_SOD_AUTHOR_APPROVAL`. Then clinical attestation: approving a `DENY` version whose `applies_to_claim_types` contains `INSTITUTIONAL_INPATIENT` requires the request's optional `clinical_review_attestation` to be true, else `ERR_CLINICAL_ATTESTATION_REQUIRED` (HTTP 422). Finally the window check: the version's half-open effectiveness window must not overlap the window of any other `ACTIVE` version of the same rule — adjacency, where one window's `effective_from` equals another's `effective_to`, is allowed because the end is exclusive — and an overlap is rejected with `ERR_EDIT_WINDOW_OVERLAP` (HTTP 409). A successful approval marks the version `ACTIVE`, records the approver in `approved_by_user_id` — null until the version is first approved — recomputes the rule's `active_version_count`, and increments the rule's `version` by one. Rejection returns a `PENDING_APPROVAL` version to `DRAFT` and accepts an optional `rejection_reason`.

Suspension comes in two flavors with identical consequences. An `EditApprover` may suspend an `ACTIVE` version manually, attaching an optional `note`. The system also suspends automatically: every time a hit pinned to a version resolves, and again at each savings-period finalization, the server recomputes the version's quality statistics — `resolved_hits_count` counts the version's pinned hits in `CONFIRMED` or `RELEASED_FALSE_POSITIVE` (hits that ended `OVERRIDDEN` or `SUPERSEDED` are excluded from this edit-quality rate), `fp_hits_count` counts those in `RELEASED_FALSE_POSITIVE`, and `fp_rate` is their quotient rounded half-up to four decimal places, or zero when nothing has resolved. When `fp_rate` reaches or exceeds 0.25 on a sample of at least four resolved hits — the boundary is inclusive, so a rate of exactly 0.2500 with exactly four resolved hits suspends — an `ACTIVE` version auto-suspends.

However a suspension happens, its cascade is the same: every review task still `PENDING` or `IN_REVIEW` whose hit is pinned to the suspended version is `CANCELLED`; each of those hits becomes `SUPERSEDED` with its `released_cents` set to the full `attributed_savings_cents`; each owning claim is rebalanced, adding the released amount back to `allowed_amount_cents` and subtracting it from `denied_amount_cents`; each affected claim re-evaluates its gate bubble-up (Section 3.5); and the rule's `active_version_count` is recomputed. Hits pinned to the version keep pointing at it — the pinning is permanent and is never re-pointed — so the audit trail of what fired under which version survives the suspension.

Reactivation returns a `SUSPENDED` version to `ACTIVE`, but only while its `fp_rate` is below 0.25; a version whose false-positive rate still meets the suspension threshold cannot be reactivated. Retirement moves an `ACTIVE` or `SUSPENDED` version to `RETIRED`, recomputing the rule's `active_version_count`; it is refused with `ERR_EDIT_VERSION_IN_USE` (HTTP 409) while any hit pinned to the version remains `FIRED`, because retiring a version with live pended work would orphan the review queue. The rule's `active_version_count` is maintained across all four lifecycle events — approval, suspension, reactivation, and retirement — so it always equals the number of the rule's versions currently `ACTIVE`.

### 3.3. Vendor Edit Intake and Duplication Control

Plans license external edit catalogs, and each licensed edit is ingested by a `PlanAdmin` with its `vendor_name`, the vendor's own `vendor_edit_key`, and an optional `description` defaulting to empty. An ingested vendor edit starts with `comparison_status` `UNMAPPED` and `mapped_edit_rule_id` null. A `PaymentIntegrityAnalyst` then performs the duplication comparison: mapping a vendor edit records the internal rule it relates to via `edit_rule_id` — stored as `mapped_edit_rule_id` — together with the analyst's verdict as `comparison_status`, either `DUPLICATE` (the vendor edit duplicates the internal rule) or `COMPLEMENTARY` (it adds genuinely new coverage). Vendor edits can be listed with optional `vendor_name`, `comparison_status`, and `mapped_edit_rule_id` filters, which is how an analyst works the unmapped queue.

Every vendor edit carries a `conflict_policy` fixed at `INTERNAL_FIRST`. Its meaning becomes concrete at screening time: when an internal edit and a vendor edit both fire on the same claim line, savings attribute to the internal hit first, and the vendor hit may be attributed zero — the duplication-avoidance mechanism described with the waterfall in Section 3.4.

### 3.4. Claim Submission and Pre-Payment Screening

A provider submits a claim under its own identity: the payload's `provider_id` must equal the caller's `X-User-ID`. The submission carries the provider-assigned `claim_number` (free-text), the `member_id` of the patient, the `claim_type` — `PROFESSIONAL`, `INSTITUTIONAL_INPATIENT`, or `INSTITUTIONAL_OUTPATIENT` — the header `total_billed_cents` (at least 1), and the service span `service_from` through `service_to`, where the end of the span may not precede its start. Inpatient claims — those of type `INSTITUTIONAL_INPATIENT` — additionally require `admission_date`, `discharge_date` (no earlier than the admission), and the provider-assigned `drg_code`; omitting any of them fails request validation with `ERR_INVALID_REQUEST`. The optional `discharge_disposition` defaults to `HOME`; a value of `TRANSFER` triggers the per-diem proration described below. A new claim is born `RECEIVED`.

While the claim is `RECEIVED`, its owning provider adds lines to it: each line carries a 1-based `line_number` unique within the claim, a `procedure_code` string (CPT, HCPCS, or revenue code), a `billed_cents` of at least 1, and an optional `units` defaulting to 1 and never less than 1. Once the claim has left `RECEIVED` its lines are locked, and adding another is rejected with `ERR_CLAIM_LINES_LOCKED` (HTTP 409).

Screening — the run-edits action, performed by a `PlanAdmin` — is the pivot of the whole workflow. Its preconditions are checked in the precedence order of Section 2.8, so when several fail at once the surfacing order is fixed: the claim must be `RECEIVED`, else `ERR_CLAIM_NOT_SCREENABLE` (HTTP 409); the provider must still be `ACTIVE`, else `ERR_PROVIDER_TERMINATED` (HTTP 422); for an inpatient claim the `drg_code` must be a known DRG weight key, else `ERR_DRG_CODE_UNKNOWN` (HTTP 422); and finally the fiscal checks — the claim must carry at least one line, else `ERR_NO_CLAIM_LINES` (HTTP 422), and the line `billed_cents` must sum exactly to the header `total_billed_cents`, else `ERR_LINE_AMOUNT_MISMATCH` (HTTP 422).

A successful screening first establishes the baseline allowed amount. For an inpatient claim this is a DRG payment, computed as follows. The length of stay is the number of whole days between `admission_date` and `discharge_date`. The base amount is 1,000,000 cents ($10,000.00) multiplied by the weight of the claim's `drg_code` — the weight table holds 1.5 for DRG 470, 0.95 for DRG 193, and 0.72 for DRG 392 — rounded half-up to whole cents. When the length of stay exceeds ten days, an outlier add-on applies: it is the lesser of 50,000 cents ($500.00) for each day beyond the tenth and twenty percent of the base amount, with that percentage cap itself rounded half-up to whole cents; a stay of ten days or fewer earns no add-on. The gross payment is the base plus the add-on. When `discharge_disposition` is `TRANSFER`, a per-diem is computed as the base amount divided by the DRG's mean length of stay — five days for DRG 470, four for 193, three for 392 — rounded half-up to whole cents, and the payment is the lesser of the gross payment and the per-diem multiplied by the length of stay; for `HOME` the payment is the gross amount. The rounding order is pinned: round the base first, then the outlier cap, then the per-diem, and the final payment is an exact integer lesser-of comparison with no further rounding. For non-inpatient claims the baseline is simply `total_billed_cents`. Either way, `initial_allowed_cents` is set to that baseline, `allowed_amount_cents` starts equal to it, and `denied_amount_cents` starts at zero.

Three evaluations then run before the edit engine. The high-dollar check flags the claim when `total_billed_cents` reaches 10,000,000 cents ($100,000.00) — the boundary is inclusive, so exactly 10,000,000 cents flags and 9,999,999 does not — and sets `high_dollar_flag` accordingly. A flagged claim immediately spawns an itemized bill review in `REQUESTED` with `due_at` set thirty days out, and that creation adds one to the provider's `open_ibr_count`. Readmission detection runs for inpatient claims: the candidates are the provider's other claims for the same `member_id`, of type `INSTITUTIONAL_INPATIENT`, already in `READY_TO_PAY`, `DENIED`, or `PAID`, and discharged on or before this claim's admission. Candidates are considered most-recent discharge first, ties broken by earliest creation; the first candidate's discharge date is subtracted from this claim's `admission_date` to give `gap_days` in whole days, and a gap from 0 to 30 days inclusive flags a readmission — 30 flags, 31 does not. A flag sets `readmission_flag` true and auto-creates an inpatient review of type `READMISSION` carrying the matched claim as `prior_claim_id` and the computed `gap_days`. Independently of the flag, every inpatient claim auto-creates an inpatient review of type `DRG_VALIDATION`, copying the claim's DRG into `provider_drg_code`.

Then the edit engine fires. One edit hit is created per eligible `ACTIVE` edit version per claim line, where eligible means the claim's `claim_type` appears in the version's `applies_to_claim_types`; the `logic_expression` is opaque to the engine and is not evaluated — any line of an eligible claim counts as the edit firing. Every hit is born `FIRED`, and a hit's `released_cents` stays zero while the hit is `FIRED` or `CONFIRMED` — it is set only when a release (override, dispute outcome, or supersede) returns money to the provider. Each hit pins its `edit_version_id` permanently at screening time, and when the firing entry is a mirrored vendor edit the hit records that `vendor_edit_id` as well (internal hits leave it null). For a `DENY` severity, the hit's `expected_savings_cents` is the full line `billed_cents` at fire time. The provider's abrasion posture is consulted next: when the provider's `tier` is `HIGH` at screening time, the hit is recorded with `applied` false — monitor-only — meaning no dollars move and no review task is created; otherwise `applied` is true.

Savings attribute per line through an internal-first waterfall. Monitor-only hits (those with `applied` false) are attributed zero and excluded from the waterfall entirely. The remaining hits on the line are ordered with hits from `INTERNAL` edits before hits from `VENDOR` edits, then by the firing version's `effective_from` earliest first, then by the hit's own creation timestamp earliest first. Walking that order with a running total starting at zero, each hit's `attributed_savings_cents` is the lesser of its `expected_savings_cents` and the line's `billed_cents` minus the running total, never below zero, and the running total grows by that attribution. A vendor hit on a line already fully denied by an internal edit is therefore attributed zero — savings are never double-counted, which is the `INTERNAL_FIRST` conflict policy in practice. Every applied hit then moves its attributed dollars out of the claim's `allowed_amount_cents` into `denied_amount_cents`, with the line's own `allowed_cents` and `denied_cents` rebalanced to match. One review task in `PENDING` is auto-created per applied hit; the provider's abrasion counters do not change while hits remain `FIRED`.

Screening lands the claim in one of two states. When the run produced any applied hit, any auto-created review, or a true `high_dollar_flag`, the claim becomes `PENDED`. When the run produced none of those, the claim goes straight to `READY_TO_PAY` and its `determined_at` — null until the claim is first determined — is stamped, anchoring the dispute window of Section 3.6. Either way the run increments the claim's `version` by one. Claims can be listed with optional `provider_id`, `status`, and `member_id` filters; a claim's lines and its edit hits are listed through the claim, and a cross-claim hit list supports optional `claim_line_id`, `edit_version_id`, `vendor_edit_id`, and `status` filters.

### 3.5. Review Task Assignment, Escalation, and Decision

Every applied edit hit spawns exactly one review task, born `PENDING`, linking the `claim_id` under review to the `edit_hit_id` that triggered it. A new task's `assigned_reviewer_user_id` is null, its `requires_senior` is false, its `outcome` is null until the task is decided, and its `decision_reason` defaults to empty. Tasks are listed with optional `claim_id`, `edit_hit_id`, `assigned_reviewer_user_id`, and `status` filters, which is how a reviewer builds a personal worklist.

Assignment is a `SeniorReviewer` action. The request names the assignee by `reviewer_user_id` and may carry an `assignee_role`. Three guards apply, surfacing in this order: the task must be `PENDING` or `ESCALATED`, else `ERR_REVIEW_TASK_NOT_DECIDABLE` (HTTP 409); an `ESCALATED` task may only be assigned to a `SeniorReviewer`, so the assignee's role must be `SeniorReviewer`, else `ERR_SENIOR_REVIEW_REQUIRED` (HTTP 403); and the assignee's current count of `IN_REVIEW` tasks must be fewer than three — a reviewer holding three in-flight tasks is at capacity, and the assignment is rejected with `ERR_REVIEWER_CAPACITY_EXCEEDED` (HTTP 409). A successful assignment records `assigned_reviewer_user_id` and moves the task to `IN_REVIEW`.

While a task is `IN_REVIEW`, the assigned reviewer — and only the assigned reviewer, by `X-User-ID` compared to `assigned_reviewer_user_id` — may do two things. Escalation, available to both `Reviewer` and `SeniorReviewer` callers with an optional `reason`, moves the task to `ESCALATED`, sets `requires_senior` true, and clears `assigned_reviewer_user_id`, returning the task to the pool with a seniority lock. Decision, with an `outcome` and an optional `decision_reason`, closes the task as `DECIDED`; a task whose `requires_senior` is true may only be decided by a `SeniorReviewer`, else `ERR_SENIOR_REVIEW_REQUIRED`. Deciding or escalating someone else's task is rejected with `ERR_NOT_RESOURCE_OWNER`, and deciding from any status other than `IN_REVIEW` is rejected with `ERR_REVIEW_TASK_NOT_DECIDABLE`.

The two outcomes diverge sharply. An `UPHOLD` — permitted only while the underlying hit is still `FIRED` and was applied — confirms the hit: the hit becomes `CONFIRMED`, the decider is recorded in the hit's `confirmed_by_user_id` (which later feeds dispute segregation of duties), `resolved_at` is stamped, and the claim's amounts stay exactly as screening left them. An `OVERRIDE` releases the hit: the hit becomes `OVERRIDDEN` with its `released_cents` set to the full `attributed_savings_cents`, the released amount is added back to the claim's `allowed_amount_cents` and subtracted from `denied_amount_cents`, and the line's `allowed_cents` and `denied_cents` are rebalanced to match. Either way the resolution ripples outward — the pinned edit version's `resolved_hits_count`, `fp_hits_count`, and `fp_rate` are recomputed, the provider's abrasion profile is recomputed, the claim re-evaluates its bubble-up, and the claim's `version` increments by one.

The bubble-up is what moves a pended claim forward. When the claim's last non-terminal review task becomes `DECIDED` or `CANCELLED` — that is, all of its tasks are in one of those two states — the claim leaves `PENDED` for `DETERMINED`, stamping `determined_at` if it was not already set, and immediately re-evaluates its remaining gates: if no itemized bill review of the claim sits in `REQUESTED`, `DOCUMENTS_RECEIVED`, or `IN_AUDIT`, and no inpatient review sits in `OPEN` or `FINDINGS_RECORDED`, the claim proceeds to `READY_TO_PAY` when `allowed_amount_cents` is greater than zero, or to `DENIED` when it is exactly zero. The same gate logic fires from `DETERMINED` whenever the last open itemized bill review reaches `COMPLETED` or `EXPIRED`, or the last open inpatient review reaches `DECIDED` — positive allowed means `READY_TO_PAY`, zero allowed means `DENIED`. A `DENIED` verdict is not necessarily final: when a later release — a task override, a dispute outcome, or a suspension supersede — lifts `allowed_amount_cents` above zero while all gates are terminal, the claim compensates back to `READY_TO_PAY`. From `READY_TO_PAY`, a `PlanAdmin` releases payment, moving the claim to its terminal `PAID` state and incrementing its `version` by one; paying from any other state is rejected with `ERR_CLAIM_NOT_PAYABLE` (HTTP 409).

### 3.6. Provider Disputes and Adjudication

Once a claim is finalized, its provider may dispute individual confirmed hits. Creating a dispute — a `Provider` action on the claim's dispute collection — takes the `edit_hit_id` being disputed, a free-text `reason`, and the `expected_claim_version` required by Section 2.7. The guards surface in precedence order: references resolve (an unknown claim or hit yields the corresponding 404), then the stale-version check rejects with `ERR_STALE_VERSION`; the claim must be in `DETERMINED`, `READY_TO_PAY`, `DENIED`, or `PAID` and the hit must be `CONFIRMED`, else `ERR_DISPUTE_NOT_OPEN` (HTTP 409); at most one dispute per hit may be open — a second dispute on a hit with a non-`DECIDED` dispute is rejected with `ERR_DISPUTE_ALREADY_OPEN` (HTTP 409); the dispute must be opened no later than 45 days after the claim's `determined_at`, an inclusive boundary where exactly 45 days after determination is still admissible, else `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422); and the `edit_hit_id` must actually belong to the claim in the path, else `ERR_HIT_NOT_ON_CLAIM` (HTTP 422). The dispute's `provider_id` must equal the claim's provider and the caller's identity. A new dispute is born `SUBMITTED`, with `outcome`, `decided_at`, and `adjudicated_by_user_id` all null until a decision is reached. Creation stamps `submitted_at` — the anchor for the decision deadline — and increments the claim's `version` by one. Disputes can be listed with optional `claim_id`, `edit_hit_id`, `provider_id`, and `status` filters.

Adjudication is a `DisputeAdjudicator` workflow with a provider round-trip in the middle. Starting review moves a `SUBMITTED` dispute to `UNDER_REVIEW`. Requesting information — with an optional `info_request_note` — moves it from `UNDER_REVIEW` to `AWAITING_PROVIDER_INFO`, and the dispute's own provider returns it to `UNDER_REVIEW` by submitting information with an optional `info_response`; that submission is ownership-checked against the dispute's provider. Any dispute action attempted from a status that does not permit it — deciding before review has started, requesting information outside `UNDER_REVIEW`, submitting information when none was requested — is rejected with `ERR_DISPUTE_NOT_DECIDABLE` (HTTP 409).

The decision is the heaviest adjudication action, and its guards surface in this order: the dispute must be `UNDER_REVIEW`, else `ERR_DISPUTE_NOT_DECIDABLE`; the adjudicator's `X-User-ID` must differ from the hit's `confirmed_by_user_id`, else `ERR_SOD_REVIEWER_ADJUDICATION` (HTTP 403); the decision must come no later than 60 days after `submitted_at`, an inclusive boundary where a decision exactly 60 days after submission is on time, else `ERR_DECISION_DEADLINE_PASSED` (HTTP 422); and for a `PARTIAL` outcome the supplied `released_cents` must be greater than zero and no more than the hit's `attributed_savings_cents`, else `ERR_INVALID_RELEASE_AMOUNT` (HTTP 422). The request carries the `outcome`, the optional `released_cents` used only by `PARTIAL`, and an optional `decision_note`.

Three outcomes, three cascades. `UPHELD` changes nothing about the hit or the claim's amounts. `OVERTURNED` declares the hit a false positive: the hit becomes `RELEASED_FALSE_POSITIVE` with `released_cents` set to the full `attributed_savings_cents`, the released amount returns to the claim's `allowed_amount_cents` and leaves `denied_amount_cents`, the line is rebalanced, and the pinned edit version's false-positive accounting is recomputed — which can trip the automatic suspension of Section 3.2 when the version is `ACTIVE` and its `fp_rate` reaches 0.25 on at least four resolved hits, cascading onward to cancel that version's open review tasks and supersede their hits with full release. `PARTIAL` moves the hit from `CONFIRMED` to `OVERRIDDEN` with `released_cents` equal to the dispute's `released_cents`, rebalancing claim and line accordingly. Every decision recomputes the provider's abrasion profile, stamps `decided_at`, records the adjudicator in `adjudicated_by_user_id`, increments the claim's `version` by one, and re-evaluates the claim's bubble-up — which is how a `DENIED` claim returns to `READY_TO_PAY` once a release lifts its allowed amount above zero with all gates terminal.

### 3.7. Itemized Bill Review of High-Dollar Claims

Itemized bill reviews arrive by two doors. The automatic door is the high-dollar flag of Section 3.4: screening a claim whose billed total reaches the threshold spawns a review in `REQUESTED`. The manual door is a `SeniorReviewer` opening a review on a screened claim, subject to an occupancy rule that keeps one provider out of overlapping audits: the provider must have no other itemized bill review whose occupancy interval contains the current instant. That interval runs from the review's `requested_at` through its `completed_at` plus a 14-day buffer, both ends inclusive; a review still open — one in `REQUESTED`, `DOCUMENTS_RECEIVED`, or `IN_AUDIT` — is treated as ending now. A collision is rejected with `ERR_PROVIDER_AUDIT_OVERLAP` (HTTP 409). Either way, creation stamps `requested_at`, sets `due_at` thirty days later, leaves `completed_at` and `auditor_user_id` null until completion and `repriced_total_cents` unset until the reprice runs, denormalizes the claim's provider onto the review's `provider_id` for the occupancy checks, and adds one to the provider's `open_ibr_count`; a manual creation on a `READY_TO_PAY` claim also reopens the claim to `PENDED`, since a new gate has appeared. Reviews are listed with optional `claim_id`, `provider_id`, and `status` filters.

The provider answers the request by delivering documents — an ownership-checked `Provider` action that moves the review from `REQUESTED` to `DOCUMENTS_RECEIVED`. A `SeniorReviewer` then opens the audit, moving it to `IN_AUDIT`. Completing the audit is the money move: the auditor supplies `findings_cents`, the improper amount identified (zero or more; informational only), and the server reprices the claim line by line — each line's repriced amount is its `billed_cents` reduced by the 6.5 percent contract discount, rounded half-up to whole cents per line first, and `repriced_total_cents` is the sum of those per-line results. The rounding order is pinned per-line-then-sum because summing first and rounding once can differ by cents; the per-line order is authoritative. The claim's `allowed_amount_cents` is then set to the lesser of its current value and `repriced_total_cents`, never below zero, and `denied_amount_cents` is reset so the ledger invariant of Section 2.10 holds. Completion stamps `completed_at`, records the auditor in `auditor_user_id`, subtracts one from the provider's `open_ibr_count`, re-evaluates the claim's bubble-up, and increments the claim's `version` by one.

A review that goes unanswered is not stuck forever. Once the logical clock passes `due_at`, a `PlanAdmin` may expire a `REQUESTED` review; expiring at or before the due instant is rejected with `ERR_IBR_NOT_YET_EXPIRABLE` (HTTP 422), so the boundary is strict — the review must be past due, not merely at its due instant. Expiration moves the review to `EXPIRED`, subtracts one from the provider's `open_ibr_count`, and re-evaluates the claim's bubble-up. Every itemized-bill action is state-guarded — documents only against `REQUESTED`, audit only against `DOCUMENTS_RECEIVED`, completion only against `IN_AUDIT`, expiration only against `REQUESTED` — and an out-of-state attempt is rejected with `ERR_IBR_NOT_COMPLETABLE` (HTTP 409). `COMPLETED` and `EXPIRED` are terminal.

### 3.8. Inpatient DRG Validation and Readmission Review

Screening an inpatient claim always opens a clinical review: a `DRG_VALIDATION` review for every inpatient claim, and a `READMISSION` review additionally when readmission detection flagged the claim. Each review is born `OPEN` with `outcome` null until decided and `payment_delta_cents` starting at zero; it records its `review_type`, and copies the claim's DRG into `provider_drg_code`; for readmission reviews the matched prior claim is recorded in `prior_claim_id` and the computed `gap_days` is stored, while validation reviews leave both null. Reviews can be listed with optional `claim_id`, `prior_claim_id`, `review_type`, and `status` filters.

A `SeniorReviewer` records findings first, moving the review from `OPEN` to `FINDINGS_RECORDED`. The request may supply an `audited_drg_code` — the auditor's view of the correct DRG, which must be a key of the DRG weight table when supplied, else `ERR_DRG_CODE_UNKNOWN` (HTTP 422) — and an optional `findings_note`. Acting on a review that is not `OPEN` is rejected with `ERR_INPATIENT_REVIEW_NOT_DECIDABLE` (HTTP 409).

The decision, also a `SeniorReviewer` action, requires `FINDINGS_RECORDED` and takes an `outcome` with an optional `decision_note`. Four outcomes exist. `NO_CHANGE` applies a `payment_delta_cents` of zero. `DRG_REASSIGNED` requires a recorded `audited_drg_code` that differs from `provider_drg_code`, else `ERR_INVALID_REQUEST`; the DRG payment of Section 3.4 is recomputed with the audited code, `payment_delta_cents` is the new payment minus the old baseline, the claim's `initial_allowed_cents` is updated to the new payment, its `allowed_amount_cents` becomes the greater of zero and the prior allowed plus the delta, and `denied_amount_cents` resets per the ledger invariant. `DENIED_READMISSION` is available only on a `READMISSION` review, else `ERR_INVALID_REQUEST`; it sets `payment_delta_cents` to the negative of the claim's current `allowed_amount_cents`, driving allowed to zero and denied to the full initial amount, which lands the claim in `DENIED` once its gates are terminal. `PARTIAL_REDUCTION` requires a recorded `audited_drg_code`; the reduction is the DRG payment under the provider's code minus the DRG payment under the audited code, halved and rounded half-up to whole cents, and `payment_delta_cents` is the negative of that reduction. Every decision re-evaluates the claim's bubble-up and increments the claim's `version` by one; deciding a review that has no recorded findings is rejected with `ERR_INPATIENT_REVIEW_NOT_DECIDABLE`. `DECIDED` is terminal.

### 3.9. Savings Periods and Reconciliation

Savings are booked monthly. A `PlanAdmin` opens a savings period by supplying its `period_key`, a calendar-month string in YYYY-MM format that must be unique across periods — a duplicate is rejected with `ERR_DUPLICATE_PERIOD_KEY` (HTTP 409). A new period is `OPEN`. When the month closes, the plan begins reconciliation, moving the period to `RECONCILING`, and later finalizes it, moving it to `FINALIZED`; beginning reconciliation requires `OPEN` and finalizing requires `RECONCILING`, with out-of-state attempts rejected as `ERR_PERIOD_NOT_FINALIZABLE` (HTTP 409). Periods can be listed with an optional `status` filter.

Finalization computes four figures from the month's hits and stamps `finalized_at`, which is null until the period is finalized. The `provisional_savings_cents` is the optimistic pipeline view: the sum of `attributed_savings_cents` over every hit created in the period month, regardless of status, counting still-unresolved `FIRED` hits at full attributed value and ignoring releases. The `finalized_savings_cents` is the audited view: over the hits resolved within the period month in `CONFIRMED`, `OVERRIDDEN`, `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`, the sum of each hit's attributed savings net of its `released_cents` — `FIRED` hits are excluded entirely, so the identical hit population yields a smaller finalized number whenever anything is still pending or has been released. The `pending_pipeline_cents` captures the in-flight remainder: the attributed sum over hits created in the period that are still `FIRED` at finalization time. The `reversed_cents` captures give-backs: the sum of `released_cents` over hits resolved within the period month in `OVERRIDDEN`, `RELEASED_FALSE_POSITIVE`, or `SUPERSEDED`. Because every hit's attributed amount is, by construction, its net amount plus its released amount, the provisional figure equals finalized plus pending plus reversed whenever all of the period's hits resolved inside the period — the reconciliation identity auditors check first. Finalization also serves as the operations checkpoint: the automatic-suspension test of Section 3.2 is re-evaluated for every `ACTIVE` edit version, so an edit that crossed the false-positive threshold late in the month is suspended at the monthly close even if no hit happened to resolve after the crossing.

## 4. Endpoint Definitions

Endpoints that create a new resource respond with 201 Created; all other successful endpoints — reads, modifications, and state-transition actions — respond with 200 OK. The table below is a navigational summary only: request bodies, response payloads, and side effects are defined by the workflow narratives of Section 3 and the contracts of Section 2, not repeated here.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /payment-integrity/providers | Create provider; auto-creates its abrasion profile | PlanAdmin |
| GET | /payment-integrity/providers | List providers (optional `status` filter) | Any authenticated role |
| GET | /payment-integrity/providers/{id} | Get provider | Any authenticated role |
| PATCH | /payment-integrity/providers/{id} | Update provider `status` (`ACTIVE`/`TERMINATED`) | PlanAdmin |
| POST | /payment-integrity/edit-rules | Create edit rule | EditLibrarian |
| GET | /payment-integrity/edit-rules | List edit rules (optional `category`, `source` filters) | Any authenticated role |
| GET | /payment-integrity/edit-rules/{id} | Get edit rule | Any authenticated role |
| POST | /payment-integrity/edit-rules/{ruleId}/versions | Create a `DRAFT` edit version; does not advance the rule's `version` | EditLibrarian |
| GET | /payment-integrity/edit-rules/{ruleId}/versions | List versions of a rule | Any authenticated role |
| GET | /payment-integrity/edit-versions/{id} | Get edit version | Any authenticated role |
| GET | /payment-integrity/edit-versions | List edit versions across rules (optional `edit_rule_id`, `status` filters) | Any authenticated role |
| POST | /payment-integrity/edit-versions/{id}/submit | `DRAFT` → `PENDING_APPROVAL` | EditLibrarian |
| POST | /payment-integrity/edit-versions/{id}/approve | `PENDING_APPROVAL` → `ACTIVE` (OCC on the rule, SoD, attestation, window overlap) | EditApprover |
| POST | /payment-integrity/edit-versions/{id}/reject | `PENDING_APPROVAL` → `DRAFT` | EditApprover |
| POST | /payment-integrity/edit-versions/{id}/suspend | `ACTIVE` → `SUSPENDED` (manual; cascade cancels open tasks and supersedes their hits) | EditApprover |
| POST | /payment-integrity/edit-versions/{id}/reactivate | `SUSPENDED` → `ACTIVE`; requires false-positive rate below threshold | EditApprover |
| POST | /payment-integrity/edit-versions/{id}/retire | `ACTIVE`/`SUSPENDED` → `RETIRED`; blocked while `FIRED` hits reference it | EditApprover |
| POST | /payment-integrity/vendor-edits | Ingest a vendor edit | PlanAdmin |
| GET | /payment-integrity/vendor-edits | List vendor edits (optional `vendor_name`, `comparison_status`, `mapped_edit_rule_id` filters) | Any authenticated role |
| GET | /payment-integrity/vendor-edits/{id} | Get vendor edit | Any authenticated role |
| POST | /payment-integrity/vendor-edits/{id}/map | Map vendor edit to an internal rule with a duplication verdict | PaymentIntegrityAnalyst |
| POST | /payment-integrity/claims | Submit claim (`provider_id` must equal the caller identity) | Provider |
| GET | /payment-integrity/claims | List claims (optional `provider_id`, `status`, `member_id` filters) | Any authenticated role |
| GET | /payment-integrity/claims/{id} | Get claim | Any authenticated role |
| POST | /payment-integrity/claims/{id}/lines | Add claim line (claim `RECEIVED`; caller owns the claim) | Provider |
| GET | /payment-integrity/claims/{id}/lines | List claim lines | Any authenticated role |
| GET | /payment-integrity/claims/{id}/edit-hits | List edit hits of a claim | Any authenticated role |
| POST | /payment-integrity/claims/{id}/run-edits | Screen claim: baseline pricing, high-dollar evaluation, readmission detection, edit engine, task creation | PlanAdmin |
| POST | /payment-integrity/claims/{id}/pay | `READY_TO_PAY` → `PAID` | PlanAdmin |
| GET | /payment-integrity/edit-hits | List edit hits (optional `claim_line_id`, `edit_version_id`, `vendor_edit_id`, `status` filters) | Any authenticated role |
| GET | /payment-integrity/edit-hits/{id} | Get edit hit | Any authenticated role |
| GET | /payment-integrity/review-tasks | List review tasks (optional `claim_id`, `edit_hit_id`, `assigned_reviewer_user_id`, `status` filters) | Any authenticated role |
| GET | /payment-integrity/review-tasks/{id} | Get review task | Any authenticated role |
| POST | /payment-integrity/review-tasks/{id}/assign | Assign task → `IN_REVIEW`; capacity and seniority checks | SeniorReviewer |
| POST | /payment-integrity/review-tasks/{id}/decide | `UPHOLD` confirms the hit; `OVERRIDE` releases it and rebalances the claim | Reviewer, SeniorReviewer |
| POST | /payment-integrity/review-tasks/{id}/escalate | `IN_REVIEW` → `ESCALATED`; requires senior reassignment | Reviewer, SeniorReviewer |
| POST | /payment-integrity/claims/{id}/disputes | Open a dispute on a `CONFIRMED` hit (OCC on the claim; 45-day window) | Provider |
| GET | /payment-integrity/disputes | List disputes (optional `claim_id`, `edit_hit_id`, `provider_id`, `status` filters) | Any authenticated role |
| GET | /payment-integrity/disputes/{id} | Get dispute | Any authenticated role |
| POST | /payment-integrity/disputes/{id}/start-review | `SUBMITTED` → `UNDER_REVIEW` | DisputeAdjudicator |
| POST | /payment-integrity/disputes/{id}/request-info | `UNDER_REVIEW` → `AWAITING_PROVIDER_INFO` | DisputeAdjudicator |
| POST | /payment-integrity/disputes/{id}/submit-info | `AWAITING_PROVIDER_INFO` → `UNDER_REVIEW` (provider owner only) | Provider |
| POST | /payment-integrity/disputes/{id}/decide | `UPHELD` / `OVERTURNED` / `PARTIAL`; overturn releases the hit as a false positive and may auto-suspend the edit version | DisputeAdjudicator |
| POST | /payment-integrity/claims/{id}/itemized-bill-reviews | Manual itemized bill review on a screened claim; provider occupancy enforced | SeniorReviewer |
| GET | /payment-integrity/itemized-bill-reviews | List itemized bill reviews (optional `claim_id`, `provider_id`, `status` filters) | Any authenticated role |
| GET | /payment-integrity/itemized-bill-reviews/{id} | Get itemized bill review | Any authenticated role |
| POST | /payment-integrity/itemized-bill-reviews/{id}/receive-documents | `REQUESTED` → `DOCUMENTS_RECEIVED` (provider owner) | Provider |
| POST | /payment-integrity/itemized-bill-reviews/{id}/start-audit | `DOCUMENTS_RECEIVED` → `IN_AUDIT` | SeniorReviewer |
| POST | /payment-integrity/itemized-bill-reviews/{id}/complete | `IN_AUDIT` → `COMPLETED`; reprices the claim and rebalances allowed/denied | SeniorReviewer |
| POST | /payment-integrity/itemized-bill-reviews/{id}/expire | `REQUESTED` → `EXPIRED` once past `due_at` | PlanAdmin |
| GET | /payment-integrity/inpatient-reviews | List inpatient reviews (optional `claim_id`, `prior_claim_id`, `review_type`, `status` filters) | Any authenticated role |
| GET | /payment-integrity/inpatient-reviews/{id} | Get inpatient review | Any authenticated role |
| POST | /payment-integrity/inpatient-reviews/{id}/record-findings | `OPEN` → `FINDINGS_RECORDED`; optional audited DRG | SeniorReviewer |
| POST | /payment-integrity/inpatient-reviews/{id}/decide | `FINDINGS_RECORDED` → `DECIDED`; applies DRG reassignment or readmission denial to the claim | SeniorReviewer |
| GET | /payment-integrity/abrasion-profiles | List abrasion profiles (optional `provider_id` filter) | Any authenticated role |
| GET | /payment-integrity/abrasion-profiles/{id} | Get abrasion profile | Any authenticated role |
| POST | /payment-integrity/savings-periods | Create savings period (unique `period_key`) | PlanAdmin |
| GET | /payment-integrity/savings-periods | List savings periods (optional `status` filter) | Any authenticated role |
| GET | /payment-integrity/savings-periods/{id} | Get savings period | Any authenticated role |
| POST | /payment-integrity/savings-periods/{id}/begin-reconciliation | `OPEN` → `RECONCILING` | PlanAdmin |
| POST | /payment-integrity/savings-periods/{id}/finalize | `RECONCILING` → `FINALIZED`; computes savings variants and runs the edit auto-suspension checkpoint | PlanAdmin |
| POST | /payment-integrity/_clock/set_current_utc | Set the logical clock; server startup default is exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time | PlanAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. Trigger conditions are intentionally not repeated here; they are defined in the narratives of Sections 2 and 3 next to the workflows they guard.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_ENUM | 400 |
| ERR_PROVIDER_NOT_FOUND | 404 |
| ERR_CLAIM_NOT_FOUND | 404 |
| ERR_EDIT_RULE_NOT_FOUND | 404 |
| ERR_EDIT_VERSION_NOT_FOUND | 404 |
| ERR_EDIT_HIT_NOT_FOUND | 404 |
| ERR_REVIEW_TASK_NOT_FOUND | 404 |
| ERR_DISPUTE_NOT_FOUND | 404 |
| ERR_IBR_NOT_FOUND | 404 |
| ERR_INPATIENT_REVIEW_NOT_FOUND | 404 |
| ERR_SAVINGS_PERIOD_NOT_FOUND | 404 |
| ERR_VENDOR_EDIT_NOT_FOUND | 404 |
| ERR_STALE_VERSION | 412 |
| ERR_CLAIM_NOT_SCREENABLE | 409 |
| ERR_CLAIM_NOT_PAYABLE | 409 |
| ERR_CLAIM_LINES_LOCKED | 409 |
| ERR_EDIT_VERSION_NOT_APPROVABLE | 409 |
| ERR_REVIEW_TASK_NOT_DECIDABLE | 409 |
| ERR_DISPUTE_NOT_DECIDABLE | 409 |
| ERR_DISPUTE_NOT_OPEN | 409 |
| ERR_IBR_NOT_COMPLETABLE | 409 |
| ERR_INPATIENT_REVIEW_NOT_DECIDABLE | 409 |
| ERR_PERIOD_NOT_FINALIZABLE | 409 |
| ERR_CLINICAL_ATTESTATION_REQUIRED | 422 |
| ERR_SOD_AUTHOR_APPROVAL | 403 |
| ERR_SOD_REVIEWER_ADJUDICATION | 403 |
| ERR_PROVIDER_TERMINATED | 422 |
| ERR_SENIOR_REVIEW_REQUIRED | 403 |
| ERR_EDIT_WINDOW_OVERLAP | 409 |
| ERR_DISPUTE_ALREADY_OPEN | 409 |
| ERR_REVIEWER_CAPACITY_EXCEEDED | 409 |
| ERR_DUPLICATE_PERIOD_KEY | 409 |
| ERR_DISPUTE_WINDOW_EXPIRED | 422 |
| ERR_DECISION_DEADLINE_PASSED | 422 |
| ERR_PROVIDER_AUDIT_OVERLAP | 409 |
| ERR_IBR_NOT_YET_EXPIRABLE | 422 |
| ERR_EDIT_VERSION_IN_USE | 409 |
| ERR_HIT_NOT_ON_CLAIM | 422 |
| ERR_DRG_CODE_UNKNOWN | 422 |
| ERR_LINE_AMOUNT_MISMATCH | 422 |
| ERR_NO_CLAIM_LINES | 422 |
| ERR_INVALID_RELEASE_AMOUNT | 422 |

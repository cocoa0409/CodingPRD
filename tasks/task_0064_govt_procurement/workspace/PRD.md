# Government Procurement API — Product Requirements Document

## 1. Introduction

Public-sector procurement sits at the intersection of fiscal discipline, regulatory oversight and competitive market pressure. Annual procurement plans must be drafted by line agencies, reviewed item-by-item, published to the open market, periodically amended as fiscal-year priorities shift, and finally executed through legally binding contracts whose payments must be reconcilable against the plan that authorised them. Around this skeleton sits an adjudicative ecosystem — tender-document version control, supplier pre-screening, randomised expert committees, lowest-price or comprehensive scoring, formal queries and complaints, and a regulator who can freeze a project mid-flight. The legacy of paper trails and email approvals leaves gaps that allow self-dealing, undisclosed conflicts of interest, and budgetary drift to escape notice.

This document specifies the API for a government procurement bidding platform that consolidates the full pipeline — plan publication, tender preparation, supplier qualification, bid opening and evaluation, award decisions, complaint adjudication, contract filing and execution monitoring — into a single regulatory-grade system of record. The design centres on three architectural commitments: segregation of duties between four mutually exclusive roles, a server-side virtual clock so that every time-gated transition is replayable and auditable, and an append-only audit log over polymorphic targets that captures every adjudicative action. All API paths in this document are mounted under the `/procurement` prefix.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry the `X-User-ID` and `X-User-Role` headers, both non-empty. A request missing either header is rejected with `ERR_AUTH_MISSING` (401). A request whose `X-User-Role` is not one of the four declared role names is rejected with `ERR_AUTH_INVALID_ROLE` (401). A request whose role is declared but is not authorised for the target endpoint is rejected with `ERR_FORBIDDEN` (403).

The four roles are spelled exactly: `ProcurementOfficer`, `Supplier`, `EvaluationExpert`, and `Regulator`.

`X-User-ID` is interpreted differently depending on the role:

- When `X-User-Role` is `Supplier`, `X-User-ID` is the `id` of the acting `Supplier`; ownership checks on any resource that references a `Supplier` (a `Bid`, `Query` or `Complaint`) compare the resource's `supplier_id` / `complainant_supplier_id` foreign-key to `X-User-ID`. Operations that mutate a supplier-owned resource (withdrawing a bid, withdrawing a complaint) require this comparison to hold.
- When `X-User-Role` is `ProcurementOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as the `actor_id` field on `AuditLog` entries it appends, but does not compare it to any entity's `id`.
- When `X-User-Role` is `EvaluationExpert`, `X-User-ID` is likewise an opaque operator identifier. The server compares it against the `expert_id` values held inside `EvaluationCommittee.members` when authorising bid evaluations, and records it as `actor_id` on the resulting `AuditLog` entry; it is not the `id` of any first-class entity.
- When `X-User-Role` is `Regulator`, `X-User-ID` is again an opaque operator identifier. It is snapshotted into `AuditLog.actor_id` on regulatory actions; it is not the `id` of any persisted entity.

A supplementary segregation-of-duties check governs four sensitive endpoints — recording a bid evaluation, forming an evaluation committee, upholding a complaint, and dismissing a complaint. A `ProcurementOfficer` acting on a project cannot also act as an `EvaluationExpert` on that same project, a `Supplier` cannot be a `Regulator`, and the same `X-User-ID` must not have appeared as both `ProcurementOfficer` and `EvaluationExpert` on a single project's audit history. Violations on those four endpoints are rejected with `ERR_CONFLICT_OF_INTEREST` (403).

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

Every list endpoint accepts two optional query parameters: `limit` and `offset`. `limit` defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0 and has no upper limit beyond the natural total of records. All list endpoints sort results by `created_at` ascending. The `meta` object on a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the request-tracing fields.

### 2.4. Common Resource Properties and the Server Virtual Clock

Every persisted entity carries a server-minted `id` field that is a freshly generated UUID with no type prefix, along with a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Entities marked as carrying common fields additionally carry `updated_at` (ISO 8601 UTC, three fractional digits, refreshed on every mutation) and `version` (a non-negative integer that starts at the value implied by the entity's initial creation and increments by one on every mutation). Three entities are intentionally lighter: `EvaluationCommittee`, `ContractAmendment`, `AuditLog`, and `ClockState` carry only `id` and `created_at` — neither `updated_at` nor `version` is exposed on these resources.

Time-gated transitions throughout the system read the server-side virtual clock rather than wall-clock time. The clock is exposed as a `ClockState` resource with a single `current_time` field (UTC, ISO 8601), initialised at first boot to `1970-01-01T00:00:00.000Z` and advanced only by an admin-only test-driving capability that accepts a `target_iso` parameter, moves `current_time` forward to that instant, expires any `Query` records whose `query_window_close_at` has now elapsed, and is idempotent on identical `target_iso` values. A separate test-driving capability emits external events from credit-information or regulatory systems given a `system` discriminator and an arbitrary `payload`; such events may update a supplier's `credit_score` or set its `blacklist_until`.

### 2.5. Optimistic Concurrency Control

Any `PATCH` endpoint accepts an optional `version` field in the request body. If supplied, the server compares it to the entity's current `version`; on mismatch the request is rejected with `ERR_VERSION_CONFLICT` (409). If the field is omitted from the request body, the OCC check is skipped and the mutation proceeds. Note: `TenderDocument.version` is a domain-specific document-version counter that increments only on amendment-cycle re-publish and does not coincide with the OCC `version` field used for optimistic concurrency on PATCH mutations.

### 2.6. Path Hierarchy and Reference Validation

Validation of every request proceeds in a priority order that the system honours mechanically. First the two authentication headers are verified, then the role's authorisation for the endpoint. Existence of every path identifier is verified next from left to right: a request such as one targeting `/procurement/projects/{project_id}/bids` first checks the project's existence and only then evaluates any nested identifier. A missing path id yields `ERR_NOT_FOUND` (404). After path ids resolve, every foreign-key id in the request body is resolved against its target entity; an unknown foreign key yields `ERR_REFERENCE_NOT_FOUND` (404). State-machine guards (the requested transition is one declared for the entity's current state) come next, returning `ERR_INVALID_STATE` (409). Business-safety rules — segregation of duties, blacklist filters — run before temporal and fiscal checks. Generic input-shape problems (missing required field, wrong type, value out of declared range) for which no more specific code applies use `ERR_VALIDATION` (422).

### 2.7. Precision and Rounding for Monetary and Score Quantities

All monetary amounts are stored and returned as integer cents (CNY convention is assumed throughout); plan-budget aggregations are performed in integer cents with no rounding because both inputs and outputs are integral. Scoring quantities are real-valued: every per-component sub-score under comprehensive scoring is computed to two decimal places using round-half-up, and the weighted-sum step that produces the final score is itself then rounded once more to two decimal places using the same rule.

### 2.8. Segregation of Duties, Audit, and the Polymorphic Audit Log

A standing `AuditLog` records every adjudicative action against the polymorphic target identifier composed of `target_type` (one of `EVALUATION`, `COMPLAINT`, `CONTRACT`, `TENDER`, `AWARD`) and a `target_id`. Each entry snapshots `actor_role` and `actor_id` from the request headers at the time of the action, the `action` verb, and an immutable `payload` object that captures the relevant state at the moment the action was recorded. The log is append-only; entries cannot be edited or deleted by any role. The Regulator role is the sole reader of the log.

Segregation of duties is the system's compliance backbone. A `ProcurementOfficer` cannot record an evaluation on a project they own; a `Supplier` cannot be a `Regulator`; an `EvaluationExpert` selected for a committee must not have a conflict-of-interest tie back to either the procuring agency or any of the project's bidders. Violations of any of these are flagged with `ERR_CONFLICT_OF_INTEREST` on the four guarded endpoints listed in §2.1.

### 2.9. Concurrency and Serialisation

Five concurrent-write scenarios are explicitly serialised:

- When two suppliers race to submit a bid for the same `(project_id, supplier_id)` pair while the deadline is approaching, at most one row exists at the level of (`project_id`, `supplier_id`, non-terminal `bid_status`). The first writer wins; the loser is rejected with `ERR_DUPLICATE_BID` (409).
- When a procurement officer publishes an award at the same instant the regulator upholds a complaint that freezes the same project, exactly one operation succeeds — first-writer-wins on the project's status transitioning out of `EVALUATING` or `AWARDED`. The loser receives `ERR_INVALID_STATE` (409).
- When two evaluation experts race to record a score for the same bid, the bid's status compare-and-swap from `OPENED` to `EVALUATED` serialises both. Exactly one score is persisted; the loser sees `ERR_BID_ALREADY_EVALUATED` (409).
- When a contract sign attempt races against a complaint upheld on the same project, first-writer-wins on the project's status transition out of `AWARDED`. If the complaint resolves first, the sign attempt is rejected with `ERR_PROJECT_FROZEN` (409); if the sign attempt resolves first, the complaint can still be upheld but its `corrective_action` is then restricted to those compatible with an active contract (termination class).
- When a plan amendment is started while a child plan item's `Project` is currently in `BIDDING_OPEN`, `EVALUATING`, `AWARDED`, or `CONTRACT_SIGNED`, the amendment is rejected with `ERR_PLAN_HAS_ACTIVE_PROJECT` (409). The serialisation point is a read-check on related `Project` rows before the parent plan's status transitions to `AMENDING`.

### 2.10. Cascading Side Effects and Version Bumps

Whenever a state transition mutates a parent or sibling entity, that entity's `updated_at` is refreshed and (if it carries common fields) its `version` is incremented by one. Plan-item status changes cascade upward into a recomputation of the parent plan's `total_budget_cents` whenever the plan is `PUBLISHED`. Tender-document amendment cycles cascade downward, forcing every `SUBMITTED` bid to `WITHDRAWN` and rolling the project's status back from `BIDDING_OPEN` to `PRESCREEN_OPEN`. Contract execution and amendment events cascade into the linked `PlanItem`'s `executed_amount_cents`. Complaint outcomes can revoke an award, freeze a project, or reopen pre-screening or evaluation depending on the chosen `corrective_action`.

### 2.11. Enumerated State and Category Values

State values are referenced as exact uppercase strings everywhere they appear. The complete enumerations are:

- `ProcurementPlan.status`: `DRAFT`, `UNDER_REVIEW`, `PUBLISHED`, `AMENDING`, `ARCHIVED`, `REJECTED`.
- `PlanItem.item_status`: `PROPOSED`, `APPROVED`, `REJECTED`, `PUBLISHED`, `EXECUTED`, `CANCELLED`.
- `PlanItem.category`: `GOODS`, `SERVICES`, `WORKS`.
- `Project.project_status`: `DRAFT`, `PRESCREEN_OPEN`, `BIDDING_OPEN`, `BIDDING_CLOSED`, `EVALUATING`, `AWARDED`, `CONTRACT_SIGNED`, `CANCELLED`, `FROZEN`.
- `Project.evaluation_method`: `LOWEST_PRICE`, `COMPREHENSIVE_SCORING`.
- `Project.frozen_reason`: `null`, `COMPLAINT_UPHELD`, `REGULATORY_HOLD`.
- `TenderDocument.doc_status`: `DRAFT`, `PUBLISHED`, `CLARIFYING`, `AMENDING`, `SUPERSEDED`.
- `Bid.bid_status`: `SUBMITTED`, `WITHDRAWN`, `OPENED`, `EVALUATED`, `AWARDED`, `LOST`, `DISQUALIFIED`.
- `EvaluationCommittee.committee_status`: `FORMED`, `EVALUATING`, `FINALIZED`, `DISSOLVED`.
- `Award.award_status`: `DECIDED`, `PUBLISHED`, `REVOKED`.
- `Contract.contract_status`: `PENDING_SIGNATURE`, `ACTIVE`, `AMENDING`, `EXECUTED`, `TERMINATED`.
- `Query.query_status`: `OPEN`, `ANSWERED`, `EXPIRED`.
- `Complaint.complaint_status`: `SUBMITTED`, `UNDER_REVIEW`, `UPHELD`, `DISMISSED`, `WITHDRAWN`.
- `Complaint.subject`: `PRESCREEN_RESULT`, `EVALUATION`, `AWARD`, `CONTRACT`.
- `Complaint.corrective_action`: `null`, `REOPEN_PRESCREEN`, `REOPEN_EVALUATION`, `REVOKE_AWARD`, `FREEZE_PROJECT`.
- `Supplier.registration_status`: `PENDING`, `VERIFIED`, `BLACKLISTED`, `REVOKED`.
- `AuditLog.target_type`: `EVALUATION`, `COMPLAINT`, `CONTRACT`, `TENDER`, `AWARD`.

## 3. Business Logic & Workflows

### 3.1. Plan Drafting, Item Composition and Budget Aggregation

A government agency begins the procurement cycle by creating a procurement plan tied to the agency's identifier (`agency_id`) and a target fiscal year (`fiscal_year`, an integer that must lie between 2000 and 2100 inclusive). The plan enters its `DRAFT` status with an `amendment_round` of zero and a `total_budget_cents` of zero, awaiting line items.

Each line item, a `PlanItem`, carries a `title` (non-empty), a `category` chosen from `GOODS`, `SERVICES`, or `WORKS`, and a `budget_cents` allocation in integer cents that must be strictly greater than zero. The item joins its parent plan via the `plan_id` foreign key and starts in `PROPOSED`. While the plan remains in `DRAFT`, items can be added freely. The plan's running `executed_amount_cents` on each child item starts at zero and is only ever moved by contract-execution side effects described later.

Submitting the plan for review, transitioning `DRAFT → UNDER_REVIEW`, requires that at least one item is in the `PROPOSED` status; a plan with no proposed items cannot be advanced. During `UNDER_REVIEW`, a `ProcurementOfficer` approves or rejects items one at a time — `PROPOSED → APPROVED` and `PROPOSED → REJECTED` are both reversible only by rejecting the plan as a whole. The plan officer then publishes the plan, transitioning `UNDER_REVIEW → PUBLISHED`. This transition has three preconditions: every plan item must already be in `APPROVED` or `REJECTED` status (no leftover `PROPOSED` items), at least one item must be `APPROVED`, and the transition itself cascades the approved items from `APPROVED` to `PUBLISHED`. On this first publish the plan's `published_at` is captured from the server clock; this timestamp is preserved across every later amendment cycle.

`total_budget_cents` is recomputed on every plan transition into `PUBLISHED` and on every plan-item status change while the parent plan is `PUBLISHED`. The aggregation sums each child plan item's `budget_cents` whose `item_status` is one of `APPROVED`, `PUBLISHED`, or `EXECUTED`; items in `CANCELLED` or `REJECTED` are excluded from the sum. The arithmetic is performed in integer cents with no rounding.

A regulator may instead reject the plan during review, transitioning `UNDER_REVIEW → REJECTED`. Every child item still in `PROPOSED` or `APPROVED` at that moment is forced to `REJECTED` as a side effect.

A published plan can be archived (`PUBLISHED → ARCHIVED`) only when every child item is in a terminal status — `EXECUTED`, `CANCELLED`, or `REJECTED`. `ARCHIVED` and `REJECTED` are the two terminal states of the plan lifecycle.

### 3.2. Plan Amendment, Active-Project Lockout and the Amendment Round Counter

Amending a published plan, transitioning `PUBLISHED → AMENDING`, requires that no plan item under the plan is currently referenced by any `Project` whose `project_status` is one of `BIDDING_OPEN`, `EVALUATING`, `AWARDED`, or `CONTRACT_SIGNED`. The intuition is that an in-flight competitive procurement cannot have its budget pulled out from under it; an officer who attempts the transition while any such project is live receives `ERR_PLAN_HAS_ACTIVE_PROJECT`. The serialisation point for this check is a serializable read of the related projects performed before the parent plan's status is written, so two concurrent amendment-initiation attempts always converge on a single answer.

Republishing an amended plan, transitioning `AMENDING → PUBLISHED`, requires that every plan item's `item_status` lies in `APPROVED`, `REJECTED`, `PUBLISHED`, `EXECUTED`, or `CANCELLED`. The cycle increments the plan's `amendment_round` by exactly one and recomputes `total_budget_cents` against the same aggregation rule. The plan's `published_at` is left untouched — it always reflects the first publication.

A `PUBLISHED` plan item may also be cancelled by the officer, transitioning `PUBLISHED → CANCELLED`, but only when no project has been created against it; this cancellation triggers a recomputation of the parent plan's `total_budget_cents`.

### 3.3. Suppliers, Registration and Pre-Screening Eligibility

A supplier registers itself (or is registered by an officer acting on its behalf) by providing a `legal_name` (non-empty and unique across all suppliers) and a `tax_id` (non-empty and unique), and optionally a list of `qualifications` strings such as `"ISO9001"` or `"CONSTRUCTION_GRADE_A"` that the supplier attests to holding. A newly created supplier starts in `PENDING` registration with a default `credit_score` of 600 (the credit score is later mirrored from an external credit-information system into the same field) and a `blacklist_until` of null. The score is constrained to the inclusive range 0 to 1000.

The procurement officer verifies the supplier by transitioning `PENDING → VERIFIED`; only a verified supplier can subsequently bid. A regulator may at any point blacklist the supplier — transitioning the registration to `BLACKLISTED` — supplying a `blacklist_until` UTC timestamp until which the supplier is treated as blacklisted. This action additionally disqualifies every `SUBMITTED` bid the supplier currently holds.

Pre-screening eligibility for a supplier against a particular project is computed as a single boolean: the supplier's `registration_status` must equal `VERIFIED`; either `blacklist_until` is null or it is less than or equal to the server clock's `current_time`; the supplier's `credit_score` must be at least `MIN_CREDIT_SCORE`, which is set to the integer 600 (so 600 passes and 599 fails); and the project's `required_qualifications` must be a subset of the supplier's `qualifications`. All four sub-checks must hold simultaneously for the supplier to be marked eligible.

A bid snapshots the supplier's eligibility at the moment of submission into `prescreen_passed` (a boolean stored on the bid). When the project's bidding is later closed, the eligibility check is re-run against the current clock — this catches suppliers blacklisted after they submitted — and any `SUBMITTED` bid that now fails is forced to `DISQUALIFIED` as a side effect of the close-bidding transition.

### 3.4. Project Creation, Time Windows and Tender Documents

A project is created against a `PlanItem` whose `item_status` is `PUBLISHED`; an attempt to create against any other item status yields `ERR_PLAN_ITEM_NOT_PUBLISHED`. The creation payload supplies the parent `plan_item_id`, a `title`, the chosen `evaluation_method` (one of `LOWEST_PRICE` or `COMPREHENSIVE_SCORING`), three UTC timestamps (`bid_submission_deadline`, `query_window_close_at`, and `bid_opening_at`), a strictly positive `estimated_value_cents` (the price ceiling), and a list of `required_qualifications` strings every bidder must hold. The three time windows are linked by a strict ordering invariant: `query_window_close_at` must lie strictly before `bid_submission_deadline`, and `bid_opening_at` must lie strictly after `bid_submission_deadline`. A project create or update that violates this invariant is rejected with `ERR_INVALID_TIME_WINDOW`. The project enters its `DRAFT` status.

Exactly one `TenderDocument` is then attached to the project. The officer supplies a `template_id` from the tender-template library, a non-empty `technical_spec`, a non-empty `commercial_spec` (which carries payment terms), and an `evaluation_criteria` object whose shape varies by evaluation method. For `LOWEST_PRICE`, the object takes the form `{ "tie_break": "earliest_bid" }`. For `COMPREHENSIVE_SCORING`, the object carries three weights — `weight_price`, `weight_technical`, `weight_qualification` — each strictly between 0 and 1, exclusive on both ends, and summing to one within a tolerance of `EPSILON` (1e-9); it also carries `max_technical_score` and `max_qualification_score`. A weight set that fails either the sum-tolerance or the per-weight range check is rejected with `ERR_WEIGHTS_INVALID` both at tender create time and at the document's later publish step. The document enters `DRAFT` with a domain-level `version` of 1.

Publishing the document, transitioning the tender from `DRAFT → PUBLISHED`, has three side effects: `pinned_at` is set to the server clock's `current_time`; `qualification_requirements` is snapshotted from the project's `required_qualifications` and pinned onto the document; and the project advances from `DRAFT → PRESCREEN_OPEN`. Bids may only be submitted against a `PUBLISHED` tender version whose `pinned_at` is less than or equal to the current clock.

### 3.5. Clarifications, Amendments and the Tender Version Pin

During `PRESCREEN_OPEN` or `BIDDING_OPEN`, the procurement officer can move the tender from `PUBLISHED → CLARIFYING`, supplying a `clarification_note` payload, provided the current clock is strictly before the project's `query_window_close_at`. Finalising the clarification transitions `CLARIFYING → PUBLISHED`; this refreshes `pinned_at` but does not change the document's `version`.

A heavier-weight amendment — beginning a new amendment cycle — moves the tender from `PUBLISHED → AMENDING`, provided the current clock is strictly before the bid submission deadline and the project status is `PRESCREEN_OPEN` or `BIDDING_OPEN`. If the project was in `BIDDING_OPEN`, it is reverted to `PRESCREEN_OPEN`. Every bid on the project whose `bid_status` is `SUBMITTED` is forced to `WITHDRAWN` so that suppliers may re-submit against the amended version. Republishing — transitioning `AMENDING → PUBLISHED` — requires the project to be in `PRESCREEN_OPEN`, increments the document's `version` by one, and resets `pinned_at` to the current clock. A tender is taken to `SUPERSEDED` by side effects: when the project is cancelled, or when an award against the project is revoked. `SUPERSEDED` is the document's only terminal state.

Bids submitted on a project must carry a `tender_document_version` matching the project's current `PUBLISHED` `TenderDocument.version` at submission time. A version mismatch yields `ERR_TENDER_VERSION_MISMATCH`.

### 3.6. Pre-Screening Open, Bidding Open, Bidding Closed

Once the tender is `PUBLISHED` and the project is in `PRESCREEN_OPEN`, the officer publishes the project-specific pre-screening list (returning a snapshot of qualifying suppliers) and then opens bidding, transitioning the project from `PRESCREEN_OPEN → BIDDING_OPEN`. This advance requires the tender document's `doc_status` to be `PUBLISHED` and the server clock's `current_time` to lie strictly before `bid_submission_deadline`.

A supplier submits a bid against a project. The submission payload carries `supplier_id`, the integer `tender_document_version` the bid was prepared against, the bid's `bid_price_cents` (a strictly positive integer), and an optional `technical_score_raw` (a self-declared technical score that defaults to 0 and is bounded by zero and `max_technical_score` from the tender document's evaluation criteria). The bid is rejected with `ERR_DEADLINE_PASSED` if the current clock is at or after `bid_submission_deadline`. It is rejected with `ERR_SUPPLIER_BLACKLISTED` if the supplier is currently blacklisted (`blacklist_until` is greater than `current_time`). It is rejected with `ERR_BID_EXCEEDS_CEILING` if `bid_price_cents` exceeds the project's `estimated_value_cents`. At submission, the system snapshots the supplier's `prescreen_passed` flag onto the bid using the eligibility calculation described in §3.3. The new bid enters `SUBMITTED`.

The system enforces that exactly one non-terminal bid exists per `(project_id, supplier_id)` pair: a second submission by the same supplier while the first is still in `SUBMITTED`, `OPENED`, `EVALUATED`, or `AWARDED` is rejected with `ERR_DUPLICATE_BID`. A supplier may withdraw their own bid, transitioning `SUBMITTED → WITHDRAWN`, but only while the clock is strictly before `bid_submission_deadline`; the supplier's identity (`X-User-ID`) must match the bid's `supplier_id`.

Closing bidding transitions the project from `BIDDING_OPEN → BIDDING_CLOSED`. This requires the current clock to be at or after `bid_submission_deadline`. As a side effect, every bid that is currently `SUBMITTED` is re-checked against the pre-screening calculation; bids that now fail (suppliers who have been blacklisted in the interim, for example) are forced to `DISQUALIFIED`.

A project may be cancelled by the officer while it sits in `PRESCREEN_OPEN` or `BIDDING_OPEN`, transitioning the project to `CANCELLED` and taking the tender document to `SUPERSEDED` as a side effect. If the cancellation occurs from `BIDDING_OPEN`, every `SUBMITTED` bid is forced to `WITHDRAWN` as well.

### 3.7. Queries, Committee Formation, and the Bid-Opening Ceremony

While the project is in pre-screening or bidding, suppliers may submit `Query` records to the procurement entity. The submission payload carries `supplier_id` and a non-empty `question`. The query is rejected with `ERR_QUERY_WINDOW_CLOSED` if the current clock is at or after `query_window_close_at`. The query enters `OPEN` and the procurement officer answers it via a `response` payload, transitioning `OPEN → ANSWERED`. When the clock advances past `query_window_close_at`, any still-`OPEN` query is moved to `EXPIRED` as part of the clock-advance side effects.

Before evaluation can begin, the officer forms an `EvaluationCommittee`. The form-committee payload supplies a `requested_size` and a caller-supplied opaque `selection_seed`. The committee size must be an odd integer between `MIN_SIZE` (3) and `MAX_SIZE` (9) inclusive, so the legal sizes are 3, 5, 7, and 9. The eligible pool of experts must be at least the requested size after excluding any expert who has a conflict of interest with the project — specifically, an expert whose id appears among any bidder's principal ids on the project, or among the procuring agency's own staff for the project. A size outside the allowed set, or a pool too small after the conflict-of-interest exclusion, is rejected with `ERR_COMMITTEE_SIZE_INVALID`.

Selection is deterministic given the seed: each remaining eligible expert is sorted by the lexicographic ordering, ascending, of the hex-encoded SHA-256 hash of the concatenation of the `selection_seed`, the literal pipe character `"|"`, and the expert's id, and the first `requested_size` are picked. For each picked expert, a member object is appended to `members` of the form `{"expert_id": <id>, "selected_at": <server clock current_time>, "conflict_cleared": true}`. The committee starts in `FORMED`.

When the clock has advanced to or past the project's `bid_opening_at` and the committee exists in `FORMED`, the officer opens the bid-opening ceremony, transitioning the project from `BIDDING_CLOSED → EVALUATING`. The transition requires at least three bids in `SUBMITTED` at the moment of the call. As side effects, every `SUBMITTED` bid that passed pre-screening is moved to `OPENED`, the committee advances from `FORMED → EVALUATING`, and an `AuditLog` entry is appended with `target_type` `EVALUATION` and `action` `"BID_CEREMONY_RECORDED"`.

### 3.8. Bid Evaluation and Final-Score Computation

Each `EvaluationExpert` whose `X-User-ID` matches one of the `expert_id` values inside `EvaluationCommittee.members` records an evaluation for one bid at a time, transitioning that bid from `OPENED → EVALUATED`. The endpoint accepts an optional `technical_score_raw` override; if absent the bid's stored value is used. The committee must be in `EVALUATING`. The transition computes `final_score` and appends an `AuditLog` entry with `target_type` `EVALUATION` and `action` `"EVALUATION_SCORE_RECORDED"`.

The `final_score` calculation has two variants pinned by the project's `evaluation_method`. Under `LOWEST_PRICE`, `final_score` is set equal to the bid's `bid_price_cents` (an integer); smaller is better, and ties are broken by the earliest `created_at` of the candidate bids.

Under `COMPREHENSIVE_SCORING`, the calculation proceeds in two pinned steps. In the first step, three per-component sub-scores are computed and each is rounded independently to two decimal places using round-half-up:

- The `price_sub_score` is one hundred multiplied by the ratio of the lowest bid price among bids on the project whose `bid_status` lies in `OPENED` or `EVALUATED` at the time the evaluation is recorded to this bid's own `bid_price_cents`, and the result is rounded half-up to two decimal places. Because the reference value is the minimum bid price among bids currently in `OPENED` or `EVALUATED`, it may evolve as further evaluations are recorded.
- The `technical_sub_score` is one hundred multiplied by the bid's `technical_score_raw` divided by the tender document's `max_technical_score`, rounded half-up to two decimal places.
- The `qualification_sub_score` is one hundred multiplied by the size of the intersection of the supplier's `qualifications` and the document's `qualification_requirements`, divided by the larger of one and the size of `qualification_requirements`, rounded half-up to two decimal places.

In the second step, the per-component scores are combined into the final weighted sum using the weights from `evaluation_criteria`: `weight_price` multiplied by `price_sub_score`, plus `weight_technical` multiplied by `technical_sub_score`, plus `weight_qualification` multiplied by `qualification_sub_score`, with the resulting sum then rounded once more to two decimal places using round-half-up. The order is binding: each component is rounded first, the weighted sum is taken second, and the sum is rounded once more at the end. Higher `final_score` is better under comprehensive scoring; ties are broken by the smaller `bid_price_cents` first and then by the earliest `created_at`.

Two evaluation experts who race to record a score for the same bid serialise on the bid's compare-and-swap from `OPENED` to `EVALUATED`. Exactly one wins; the loser receives `ERR_BID_ALREADY_EVALUATED`. The committee is then finalised, transitioning `EVALUATING → FINALIZED`, only when every bid on the project whose `bid_status` is in `OPENED` or `EVALUATED` has reached `EVALUATED`.

### 3.9. Award Decision, Publication, and Frozen Projects

With the committee in `FINALIZED` and at least one bid in `EVALUATED`, the officer triggers the award decision. The project transitions `EVALUATING → AWARDED`. An `Award` record is created in `DECIDED` status with `winning_bid_id` set to the bid selected by the evaluation method's tie-break rules from §3.8, and `award_amount_cents` snapshotted from the winning bid's `bid_price_cents` at this moment. As side effects, the winning bid moves to `AWARDED` and every other `EVALUATED` bid moves to `LOST`. An `AuditLog` entry with `target_type` `AWARD` and `action` `"AWARD_DECIDED"` is appended.

Publishing the award transitions the award from `DECIDED → PUBLISHED`, captures `published_at` from the server clock, and emits an external signal to the credit-information system. `REVOKED` is the third and terminal award status, reached only as a side effect of complaint-driven corrective action.

A complaint upheld with `corrective_action` of `REVOKE_AWARD` or `FREEZE_PROJECT` flips the project from `AWARDED → FROZEN` and sets `frozen_reason` to `COMPLAINT_UPHELD`. Under `REVOKE_AWARD`, the award is additionally moved to `REVOKED` and the winning bid is moved to `DISQUALIFIED`.

### 3.10. Complaints and Corrective Action

A supplier raises a `Complaint` against a project. The submission payload carries `complainant_supplier_id`, a `subject` chosen from `PRESCREEN_RESULT`, `EVALUATION`, `AWARD`, or `CONTRACT`, and a non-empty `narrative`. The complaint enters `SUBMITTED`. The complainant supplier may withdraw a `SUBMITTED` complaint themselves (the `X-User-ID` must match `complainant_supplier_id`), transitioning to `WITHDRAWN`.

The regulator accepts the complaint, transitioning `SUBMITTED → UNDER_REVIEW`, which appends an `AuditLog` entry with `target_type` `COMPLAINT` and `action` `"COMPLAINT_ACCEPTED"`. From `UNDER_REVIEW` the regulator may either uphold or dismiss the complaint. Dismissal — `UNDER_REVIEW → DISMISSED` — sets `decision_at` to the server clock and appends a `COMPLAINT_DECIDED` audit entry.

Upholding — `UNDER_REVIEW → UPHELD` — requires `corrective_action` to be non-null and one of `REOPEN_PRESCREEN`, `REOPEN_EVALUATION`, `REVOKE_AWARD`, or `FREEZE_PROJECT`. `decision_at` is set, and the corrective action is applied:

- `REOPEN_PRESCREEN` transitions the project back to `PRESCREEN_OPEN` and is valid only when the project is currently in `BIDDING_OPEN`, `BIDDING_CLOSED`, or `EVALUATING`.
- `REOPEN_EVALUATION` returns the evaluation committee to `EVALUATING` and is valid only when the project is currently in `EVALUATING`.
- `REVOKE_AWARD` flips the project to `FROZEN`, moves the award to `REVOKED`, moves the winning bid to `DISQUALIFIED`, and reverts the parent plan item's `EXECUTED` status because a contract is now precluded by the award revocation.
- `FREEZE_PROJECT` flips the project to `FROZEN` with no further cascades.

A `COMPLAINT_DECIDED` audit entry is appended, and its `payload` includes the chosen `corrective_action`.

### 3.11. Contract Filing, Signing, Consistency Check and the 20% Amendment Cap

A `Contract` is filed against a `PUBLISHED` award. The filing payload supplies `project_id`, `award_id`, `supplier_id`, `contract_amount_cents`, and `payment_terms`. The contract enters `PENDING_SIGNATURE`. Exactly one contract per project is allowed.

Signing the contract — transitioning `PENDING_SIGNATURE → ACTIVE` — runs a consistency check before any side effects fire. The check passes if and only if all three of the following hold: the contract's `contract_amount_cents` equals the award's `award_amount_cents`; the contract's `payment_terms` is byte-identical to the tender document's `commercial_spec` at the version pinned at the time of the award; and the contract's `supplier_id` equals the `supplier_id` of the bid the award references via `winning_bid_id`. If any of the three fail, the request is rejected with `ERR_CONTRACT_INCONSISTENT`. Two additional preconditions must also hold: the award's status must be `PUBLISHED`, and the supplier must be `VERIFIED` and not currently blacklisted; otherwise the sign is rejected with `ERR_PROJECT_FROZEN` if the project has already been frozen by a complaint, or `ERR_INVALID_STATE` for other state mismatches.

On a successful sign, `signature_ref` is set from the external e-signature system mock, the project transitions to `CONTRACT_SIGNED`, the parent plan item is moved to `EXECUTED` and its `executed_amount_cents` is increased by the contract's `contract_amount_cents`, and a `CONTRACT_SIGNED` audit entry is appended.

A signed contract may be amended. Beginning the amendment moves the contract from `ACTIVE → AMENDING`. Filing the amendment — transitioning `AMENDING → ACTIVE` — supplies a signed `delta_amount_cents` (positive or negative) and a non-empty `reason`. Two fiscal checks apply jointly: the resulting `contract_amount_cents` (the existing amount plus `delta_amount_cents`) must remain strictly greater than zero, and it must remain at most one hundred and twenty percent of the original `award_amount_cents` — i.e. the cumulative amendment ceiling is twenty percent above the original award. A breach of either bound is rejected with `ERR_AMENDMENT_EXCEEDS_CAP`. On success, the contract's `contract_amount_cents` is updated by the delta and the parent plan item's `executed_amount_cents` is updated by the same delta. A `ContractAmendment` row records `contract_id`, `delta_amount_cents`, `reason`, and a server-set `filed_at` timestamp.

Payments are mirrored from the external payment system onto the contract through a record-payment capability that accepts an `amount_cents` payload and increases `paid_amount_cents` by that amount. When `paid_amount_cents` reaches or exceeds `contract_amount_cents`, the officer marks the contract executed, transitioning `ACTIVE → EXECUTED`.

A regulator may terminate an `ACTIVE` contract with a `reason` payload, transitioning `ACTIVE → TERMINATED`. On termination, the parent plan item's `executed_amount_cents` is reduced by the unpaid balance — that is, by the contract's `contract_amount_cents` minus its `paid_amount_cents`.

## 4. Endpoint Definitions

All endpoints listed below are mounted under the `/procurement` prefix established in §1. Endpoints that create a new resource return status `201 Created`. Endpoints that mutate an existing resource return status `200 OK`. List and read endpoints return `200 OK`. Authentication and authorisation are handled per §2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /procurement/suppliers | Register a new supplier. | Supplier, ProcurementOfficer |
| POST | /procurement/suppliers/{id}/verify | Verify a supplier's qualifications. | ProcurementOfficer |
| POST | /procurement/suppliers/{id}/blacklist | Blacklist a supplier until a given UTC timestamp. | Regulator |
| GET | /procurement/suppliers/{id} | Get a supplier. | Supplier, ProcurementOfficer, Regulator |
| POST | /procurement/plans | Create a new procurement plan. | ProcurementOfficer |
| POST | /procurement/plans/{id}/items | Add a plan item to a draft plan. | ProcurementOfficer |
| POST | /procurement/plan-items/{id}/approve | Approve a proposed plan item. | ProcurementOfficer |
| POST | /procurement/plan-items/{id}/reject | Reject a proposed plan item. | ProcurementOfficer |
| POST | /procurement/plan-items/{id}/cancel | Cancel a published plan item with no project. | ProcurementOfficer |
| POST | /procurement/plans/{id}/submit-review | Submit a plan for review. | ProcurementOfficer |
| POST | /procurement/plans/{id}/publish | Publish (or republish from amendment) a plan. | ProcurementOfficer |
| POST | /procurement/plans/{id}/reject | Regulator rejects a plan under review. | Regulator |
| POST | /procurement/plans/{id}/begin-amendment | Begin the plan amendment cycle. | ProcurementOfficer |
| POST | /procurement/plans/{id}/archive | Archive a plan whose items are all terminal. | ProcurementOfficer |
| GET | /procurement/plans | List plans (paginated, filter by status and fiscal_year). | ProcurementOfficer, Regulator, Supplier |
| GET | /procurement/plans/{id} | Get a plan. | ProcurementOfficer, Regulator, Supplier |
| POST | /procurement/projects | Create a project for a published plan item. | ProcurementOfficer |
| POST | /procurement/projects/{id}/tender-document | Create the tender document for a draft project. | ProcurementOfficer |
| POST | /procurement/tender-documents/{id}/publish | Publish or republish the tender document. | ProcurementOfficer |
| POST | /procurement/tender-documents/{id}/clarify | Move tender from PUBLISHED to CLARIFYING. | ProcurementOfficer |
| POST | /procurement/tender-documents/{id}/finalize-clarification | Move tender from CLARIFYING back to PUBLISHED. | ProcurementOfficer |
| POST | /procurement/tender-documents/{id}/begin-amendment | Begin an amendment cycle (forces SUBMITTED bids to WITHDRAWN). | ProcurementOfficer |
| GET | /procurement/projects/{id} | Read project. | ProcurementOfficer, Regulator, Supplier |
| POST | /procurement/projects/{id}/open-bidding | Open bidding on the project. | ProcurementOfficer |
| POST | /procurement/projects/{id}/close-bidding | Close bidding past the submission deadline. | ProcurementOfficer |
| POST | /procurement/projects/{id}/cancel | Cancel a project from PRESCREEN_OPEN or BIDDING_OPEN. | ProcurementOfficer |
| POST | /procurement/projects/{id}/prescreen-results | Publish project-specific pre-screening results. | ProcurementOfficer |
| POST | /procurement/projects/{id}/bids | Submit a bid against the current published tender version. | Supplier |
| POST | /procurement/bids/{id}/withdraw | Supplier withdraws bid before deadline. | Supplier |
| POST | /procurement/bids/{id}/record-evaluation | Evaluation expert records a bid evaluation. | EvaluationExpert |
| GET | /procurement/projects/{id}/bids | List bids on a project. | ProcurementOfficer, Regulator, Supplier |
| POST | /procurement/projects/{id}/form-committee | Form an evaluation committee using a seed. | ProcurementOfficer |
| POST | /procurement/committees/{id}/finalize | Finalise the committee when every opened bid is evaluated. | ProcurementOfficer |
| POST | /procurement/projects/{id}/open-bid-ceremony | Open the bid-opening ceremony. | ProcurementOfficer |
| POST | /procurement/projects/{id}/decide-award | Decide the award and create the Award record. | ProcurementOfficer |
| POST | /procurement/awards/{id}/publish | Publish the award. | ProcurementOfficer |
| POST | /procurement/projects/{id}/queries | Submit a tender query within the query window. | Supplier |
| POST | /procurement/queries/{id}/respond | Procurement officer answers a query. | ProcurementOfficer |
| POST | /procurement/projects/{id}/complaints | File a complaint with the regulator. | Supplier |
| POST | /procurement/complaints/{id}/accept | Regulator accepts the complaint for review. | Regulator |
| POST | /procurement/complaints/{id}/uphold | Regulator upholds the complaint and applies corrective action. | Regulator |
| POST | /procurement/complaints/{id}/dismiss | Regulator dismisses the complaint. | Regulator |
| POST | /procurement/complaints/{id}/withdraw | Complainant supplier withdraws a submitted complaint. | Supplier |
| POST | /procurement/contracts | File a draft contract against a published award. | ProcurementOfficer |
| POST | /procurement/contracts/{id}/sign | Run consistency check and sign the contract. | ProcurementOfficer |
| POST | /procurement/contracts/{id}/begin-amendment | Move contract from ACTIVE to AMENDING. | ProcurementOfficer |
| POST | /procurement/contracts/{id}/file-amendment | File a contract amendment within the 20% cap. | ProcurementOfficer |
| POST | /procurement/contracts/{id}/record-payment | Mirror a payment event onto the contract. | ProcurementOfficer, Regulator |
| POST | /procurement/contracts/{id}/mark-executed | Mark the contract executed once fully paid. | ProcurementOfficer |
| POST | /procurement/contracts/{id}/terminate | Regulator terminates an active contract. | Regulator |
| GET | /procurement/audit-logs | List audit-log entries (paginated, filterable). | Regulator |
| POST | /_clock/advance | Test-driving capability: advance the virtual clock. | ProcurementOfficer, Regulator, Supplier, EvaluationExpert |
| POST | /_events/emit | Test-driving capability: emit an external event. | Regulator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_AUTH_MISSING | 401 |
| ERR_AUTH_INVALID_ROLE | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CONFLICT_OF_INTEREST | 403 |
| ERR_SUPPLIER_BLACKLISTED | 403 |
| ERR_DEADLINE_PASSED | 409 |
| ERR_QUERY_WINDOW_CLOSED | 409 |
| ERR_INVALID_TIME_WINDOW | 422 |
| ERR_PLAN_ITEM_NOT_PUBLISHED | 409 |
| ERR_WEIGHTS_INVALID | 422 |
| ERR_TENDER_VERSION_MISMATCH | 409 |
| ERR_COMMITTEE_SIZE_INVALID | 422 |
| ERR_CONTRACT_INCONSISTENT | 422 |
| ERR_AMENDMENT_EXCEEDS_CAP | 409 |
| ERR_BID_EXCEEDS_CEILING | 409 |
| ERR_VERSION_CONFLICT | 409 |
| ERR_DUPLICATE_BID | 409 |
| ERR_BID_ALREADY_EVALUATED | 409 |
| ERR_PROJECT_FROZEN | 409 |
| ERR_PLAN_HAS_ACTIVE_PROJECT | 409 |
| ERR_VALIDATION | 422 |

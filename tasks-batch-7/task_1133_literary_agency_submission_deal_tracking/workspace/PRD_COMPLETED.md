# Literary Agency Submission & Deal Tracking API — Product Requirements Document

## 1. Introduction

A literary agency lives or dies by pipeline discipline: unsolicited query letters arrive faster than agents can read them, promising manuscripts must be shepherded through evaluation and revision, signed clients must be shopped to editors under strict exclusivity etiquette, and every offer, auction, and contract must survive contact with the royalties desk. This document specifies the Literary Agency Submission & Deal Tracking API, a multi-tenant system that governs that entire pipeline — from slush-pile intake and reader evaluation, through client representation agreements and editor submission rounds, to offer negotiation, auction ranking, deal execution, advance payment schedules, and royalty statement reconciliation with audit.

The API serves four operator constituencies with deliberately segregated powers: agency administrators who bootstrap and maintain the roster, agents who triage queries and run submissions, contracts managers who accept offers and execute deals, and royalties accountants who reconcile publisher statements against expected terms. Because money flows through every stage — advances are scheduled against milestones, commissions are withheld at multiple events, and author earn-out is tracked against the advance — the system treats period bookkeeping, variance auditing, and optimistic concurrency as first-class concerns rather than afterthoughts.

## 2. Global Specifications & System-Wide Principles

This section defines the cross-cutting contracts that apply uniformly to every resource and every request.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying their operational capacity. A request in which either header is missing or malformed is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly four roles, spelled precisely as follows: `AgencyAdmin`, `Agent`, `ContractsManager`, and `RoyaltiesAccountant`. Each endpoint admits a defined subset of these roles (see §4); a caller whose role is not admitted is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The roles differ in how `X-User-ID` is interpreted. When `X-User-Role` is `Agent`, `X-User-ID` is the `id` of the acting `Agent` record; ownership and tenancy checks on any resource that references an `Agent` or an `Agency` compare the resource's agency linkage against the acting agent's own `agency_id`. If no `Agent` record matches the supplied id, the headers are still well-formed and no authentication error is raised; instead the caller is treated as belonging to no agency, so every agency-scoped lookup or write fails with `ERR_NOT_FOUND` and every list endpoint returns an empty result set. When `X-User-Role` is `AgencyAdmin`, `ContractsManager`, or `RoyaltiesAccountant`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for segregation-of-duties comparisons (for example, against a round's `agent_id` at offer-accept or deal-execute time) but never compares it to any entity's `id` for ownership purposes.

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

Requests to undefined paths, or to defined paths with an unsupported method, are rejected in the same envelope with `error_id` `ERR_NOT_FOUND` and HTTP status 404. An unexpected server failure is reported in the same envelope with `error_id` `ERR_INTERNAL` and HTTP status 500.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped, not rejected: a `limit` below 1 is treated as 1 and above 100 as 100. The `offset` parameter specifies how many items to skip, defaults to 0, and clamps a negative value to 0. A non-integer `limit` or `offset` fails with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns its resources sorted by `created_at` in ascending order, with ties broken by insertion order. The `meta` object of a list response carries four pagination fields: `limit` and `offset` echoing the effective values used, `total_count` counting all items that match the supplied filters before pagination, and `has_more`, which is true exactly when items remain beyond the returned page.

### 2.4. Multi-Tenancy and Agency Scoping

The resource topology is flat: every collection lives at the top level of the API and is addressed by a single resource identifier — there are no nested URL hierarchies. Tenancy is carried entirely by data rather than by path. Every operational resource (agents, authors, editors, query letters, manuscripts, client agreements, submission rounds, submissions, offers, deals, royalty statements, and advance installments) carries an `agency_id` field tying it to exactly one `Agency`. On derived records this foreign key is denormalized at creation time from the record's natural source — a query letter copies it from its author, a manuscript from its query letter, a submission from its round, an offer from its submission, a deal from its offer, and statements and installments from their deal.

Tenancy is enforced as an existence rule. When the caller's role is `Agent`, the target resource's agency must equal the acting agent's own agency; a reference to a resource of another agency is indistinguishable from a reference to a resource that does not exist and is rejected with `ERR_NOT_FOUND`. The same rule covers cross-referenced identifiers supplied in a request body — `author_id`, `editor_id`, `submission_round_id`, `manuscript_id`, `agent_id`, `deal_id`, `submission_id`, and the like must all belong to the same agency as the resource being created or acted upon, or the request fails with `ERR_NOT_FOUND`. List endpoints apply the same scoping: an `Agent`-role caller sees only records of their own agency, while callers of the other three roles see records across all agencies, narrowed only by any `agency_id` filter they supply.

### 2.5. Common Resource Properties

Every resource in the system carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix, assigned at creation.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): starts at 1 on creation and increments by one on every mutation, whether client-invoked or system-driven.

System-driven cascade mutations — a lapsed query letter declining its manuscript, a superseded offer passing its submission, a terminated deal waiving its installments — are full mutations of the affected resources: each one refreshes `updated_at` and increments `version` on every resource it touches. Derived-field recomputation (for example an agent's `open_query_count` or an agency's `posture`) likewise counts as mutation of the owning resource.

### 2.6. The Royalty Period Clock

Time inside an agency is measured in royalty periods, not wall-clock time. Each `Agency` carries a `period_index`, an integer counter initialized to 0 at agency creation, and a `books_closed_through_period_index`, initialized to null (meaning no period's books have been closed). Advancing the clock is an explicit, role-restricted capability: closing the current period increments `period_index` by one, increments the agency's `version` by one, and drives a family of sweeps — query lapse, installment due/late promotion, and a deal-activation backstop — described in the relevant workflow subsections of §3. Separately, closing the books for the most recently completed period sets `books_closed_through_period_index` to `period_index` minus one and increments the agency's `version` by one; closing the books is rejected with `ERR_INVALID_STATE` while `period_index` is still 0, because there is no completed period to close.

Several business rules compare a resource's stamped period against these two counters: statements may only be intaken for a period strictly after `books_closed_through_period_index` and no later than the current `period_index`; installments fall due and go late relative to their `due_period_index`; queries lapse relative to their `requested_period_index`; and editor exclusivity windows are measured against a submission's `sent_period_index`.

### 2.7. Slush Capacity and Intake Posture

An agency's appetite for unsolicited queries is finite. Each `Agency` declares a `slush_capacity`: the maximum number of `QueryLetter` records allowed to be in `RECEIVED` or `IN_REVIEW` status at any instant. The agency's `posture` is a computed field with two values, `NORMAL` and `INTAKE_PAUSED`. Whenever any intake leaves the open slush count equal to `slush_capacity`, the posture flips from `NORMAL` to `INTAKE_PAUSED`; while paused, every attempt to intake a new query letter is rejected with `ERR_INTAKE_PAUSED`. When a rejection, withdrawal, lapse, or manuscript request causes the open slush count to drop strictly below `slush_capacity`, the posture returns to `NORMAL`. The posture is re-evaluated after every operation that changes the open slush population — intake, assignment, request-manuscript, rejection, withdrawal, and the period-close lapse sweep.

### 2.8. Money, Cents, and Rounding Discipline

All monetary amounts in the system — advances, receipts, royalties, commissions, variances — are represented as integer cents. No floating-point money ever crosses the API. Wherever a calculation divides or multiplies, the result is floored to an integer number of cents, and the order in which flooring is applied is pinned by the individual calculation rules in §3: per-unit averages are floored first, each per-line multiplication is floored second, and summation happens last. Summing receipts first and flooring once at the end is non-conformant because it yields different cents. Royalty percentages and commission fractions are carried as plain decimal fractions (for example 0.15 for fifteen percent). The triage score and evaluation score are plain integers with no rounding.

### 2.9. Request Validation Pipeline

Every request is validated against an ordered pipeline; the first failing check determines the error response, so an earlier failure masks later ones. The order is:

1. **User context** — `X-User-ID` and `X-User-Role` must be present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400). Applies to all endpoints.
2. **Role admission** — the caller's role must be permitted for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`, 403). Applies to all endpoints.
3. **Body shape** — the body must be a JSON object (malformed JSON and non-object bodies fail here); required fields present; types strict (booleans must be JSON booleans, integers must be JSON integers and not booleans, strings must be non-empty); a field explicitly set to null is rejected unless the endpoint declares that field nullable; enums valid; ranges valid (`eval_score` between 0 and 100 inclusive, `word_count` greater than 0, monetary amounts greater than or equal to 0, royalty and commission fractions greater than or equal to 0, `max_editors` at least 1, statement `period_index` and expected-version fields at least 0); and no undeclared fields (`ERR_INVALID_REQUEST`, 400). Applies to every endpoint with a body; endpoints that declare no request fields reject any body field as undeclared.
4. **Existence and tenancy** — path and body identifiers must exist; for `Agent`-role callers the target resource's agency must equal the acting agent's agency, and cross-referenced body identifiers must belong to the same agency (`ERR_NOT_FOUND`, 404).
5. **Optimistic concurrency** — where an endpoint takes an expected-version field, it must match the parent's current `version` (`ERR_STALE_VERSION`, 412).
6. **State admissibility** — the target resource must be in a state that permits the requested transition (`ERR_INVALID_STATE`, 409).
7. **Segregation of duties** — offer acceptance and deal execution may not be performed by the round's agent (`ERR_SEGREGATION_OF_DUTIES`, 403).
8. **Assigned-agent binding** — the acting agent must be the assigned, reader, or signing agent on the target (`ERR_NOT_ASSIGNED_AGENT`, 403).
9. **Active counterparties** — a referenced agent or editor must be `ACTIVE` (`ERR_AGENT_INACTIVE` or `ERR_EDITOR_INACTIVE`, 409).
10. **Intake gate** — query intake while `posture` is `INTAKE_PAUSED` (`ERR_INTAKE_PAUSED`, 409).
11. **Manuscript lifecycle gates** — acceptance requires a score of at least 70; revision requires an unconsumed round budget (`ERR_SCORE_BELOW_THRESHOLD`, `ERR_REVISION_LIMIT_REACHED`, 409).
12. **Agreement gates** — offering requires an accepted manuscript; signing requires no other signed agreement for the manuscript (`ERR_MANUSCRIPT_NOT_ACCEPTED`, `ERR_AGREEMENT_ALREADY_SIGNED`, 409).
13. **Round gates** — opening requires a signed agreement, no other open round for the manuscript, and at least one queued submission; creating a submission requires the round to be in `DRAFT` or `OPEN` with live-submission capacity remaining (`ERR_AGREEMENT_NOT_SIGNED`, `ERR_ROUND_ALREADY_OPEN`, `ERR_EMPTY_ROUND`, `ERR_ROUND_CAPACITY_EXCEEDED`, 409).
14. **Submission conflicts** — no duplicate editor within a round; the editor exclusivity window must not be violated (`ERR_DUPLICATE_SUBMISSION`, `ERR_EDITOR_EXCLUSIVE_WINDOW`, 409).
15. **Auction gate** — in auction-mode rounds only the top-ranked offer may be accepted (`ERR_NOT_TOP_RANKED_OFFER`, 409).
16. **Deal-liveness and statement-period gates** — reconciliation and installment payment require a live deal; statement intake may not reference a future period (`ERR_DEAL_NOT_LIVE`, `ERR_FUTURE_STATEMENT`, 409).
17. **Books and variance gates** — statement intake and audit opening require the period to be past the closed books; audit opening requires out-of-tolerance variance; clearing requires within-tolerance variance (`ERR_BOOKS_CLOSED`, `ERR_VARIANCE_WITHIN_TOLERANCE`, `ERR_VARIANCE_UNRESOLVED`, 409).
18. **Termination gates** — deal termination is blocked by unresolved statements; agreement termination is blocked by open deals (`ERR_STATEMENTS_UNRESOLVED`, `ERR_DEAL_STILL_OPEN`, 409).
19. **Round-close and offer-liveness gates** — closing is blocked by live submissions or live offers; manually withdrawing an offer-extended submission is blocked while its offer is live (`ERR_ROUND_HAS_LIVE_SUBMISSIONS`, `ERR_ROUND_HAS_LIVE_OFFERS`, `ERR_OFFER_STILL_LIVE`, 409).

### 2.10. Optimistic Concurrency Control

Two write operations in the system are guarded by optimistic concurrency control, and only these two. Opening a submission round requires the request to carry `expected_submission_round_version`, holding the `version` of the `SubmissionRound` the client last observed. If the round's current `version` differs — because any mutation, including a previous successful open, has advanced it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412) before any state check runs. Executing a deal likewise requires `expected_deal_version` matching the deal's current `version`; a mismatch — for example because another writer amended the deal's terms between the client's read and the execute call — is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint accepts or requires a version field.

### 2.11. Cascading State Propagation

Many operations mutate more than one resource. The system's cascades are documented per workflow in §3 and follow three conventions. First, every cascade hop is a real mutation of the resource it touches, refreshing `updated_at` and incrementing `version` as stated in §2.5. Second, cascades are described in terms of counted links — a primary transition causes a secondary transition, which may itself cause a tertiary one — and each link's cause is attributed to the preceding link, not to the original trigger. Third, where a transition triggers a fan-out across a collection (for example, every losing offer in a round), the fan-out is not part of the counted chain but is applied atomically with it.

## 3. Business Logic & Workflows

### 3.1. Bootstrapping the Agency and Its Roster

An `AgencyAdmin` begins by creating the agency itself, supplying its legal `name`, the default `commission_pct` fraction the agency will withhold from author earnings (used whenever a client agreement does not lock an override), and the `slush_capacity` that bounds the query pile — `commission_pct` must be a number zero or greater and `slush_capacity` an integer zero or greater. A freshly created agency starts with `period_index` 0, `books_closed_through_period_index` null, and `posture` `NORMAL`.

Roster management is administrative. The administrator creates `Agent` records with `agency_id`, `display_name`, and `email` — each email unique within its agency, with a duplicate rejected as `ERR_INVALID_REQUEST` — and each new agent starts `ACTIVE` with an `open_query_count` of zero. Authors and editors can be registered by either an administrator or an agent: an `Author` carries `agency_id`, `display_name`, and `email` (unique within the agency, duplicates likewise `ERR_INVALID_REQUEST`) and begins life as a `PROSPECT`; an `Editor` carries `agency_id`, `display_name`, the publishing `imprint` they work for, and `email` (likewise unique within the agency), and begins `ACTIVE`. Administrators may deactivate and later reactivate agents and editors; deactivation moves the record from `ACTIVE` to `INACTIVE` and reactivation reverses it, each transition incrementing the record's `version` by one. Deactivation does not revoke the record's own calling privileges — an `INACTIVE` agent may still act in the `Agent` role; it only blocks new references to the record (`ERR_AGENT_INACTIVE` at assignment time, `ERR_EDITOR_INACTIVE` at send time). An author's `status` is never set directly — it is driven entirely by downstream events, moving from `PROSPECT` to `CLIENT` the first time one of their manuscripts is accepted or a representation agreement is signed, from `CLIENT` to `FORMER` when an agreement is terminated and no other `SIGNED` agreements remain for that author, and back from `FORMER` to `CLIENT` if a later manuscript acceptance or agreement signing occurs.

Two administrative capabilities drive the agency's calendar. Advancing the period — available to both `AgencyAdmin` and `RoyaltiesAccountant` — increments `period_index` by one, increments the agency's `version` by one, and sets off the lapse, due/late, and activation sweeps detailed in later subsections. Closing the books — likewise available to both roles — records that everything through the period just completed is final: it sets `books_closed_through_period_index` to the current `period_index` minus one, increments the agency's `version` by one, and is rejected with `ERR_INVALID_STATE` while `period_index` is still 0.

### 3.2. Query Intake and Slush Pile Triage

The slush pile is where every client relationship starts. An `Agent` intakes a query letter on behalf of a registered author by supplying the `author_id`, the claimed `genre` (one of `FICTION`, `NONFICTION`, `YA`, or `MEMOIR`), and the manuscript's claimed `word_count` (which must be greater than 0). Intake is refused with `ERR_INTAKE_PAUSED` whenever the agency's `posture` is `INTAKE_PAUSED` — that is, when the count of query letters sitting in `RECEIVED` or `IN_REVIEW` has already reached `slush_capacity`. A successful intake creates the letter in `RECEIVED` status with `agency_id` denormalized from the author, `assigned_agent_id` null, `requested_period_index` null, and a `triage_score` computed once, at this moment and never recomputed.

The triage score is a weighted sum of three factors, each an integer, producing a score between 15 and 100. The genre factor awards 40 points for `FICTION`, 30 for `NONFICTION`, 25 for `YA`, and 10 for `MEMOIR`. The length factor awards 40 points when `word_count` falls between 70,000 and 120,000 inclusive; 20 points when it falls between 50,000 and 69,999 inclusive or between 120,001 and 150,000 inclusive; and 5 points in every other case. The author factor reads the author's `status` at intake time and awards 20 points for a `CLIENT`, 10 for a `PROSPECT`, and 0 for a `FORMER`. The `triage_score` is the sum of the three factors.

An agent claims a letter from the pile by assigning it, moving it from `RECEIVED` to `IN_REVIEW`; the payload's `agent_id` must reference an `ACTIVE` agent of the same agency, or the request fails with `ERR_AGENT_INACTIVE`. Assignment writes `assigned_agent_id`, recomputes `open_query_count` for both the previously assigned agent (if any) and the newly assigned one, and re-evaluates the agency posture. An agent's `open_query_count` counts that agent's letters sitting in `RECEIVED` or `IN_REVIEW`.

From `IN_REVIEW`, the assigned agent — and only the assigned agent, with mismatches rejected as `ERR_NOT_ASSIGNED_AGENT` — may request the full manuscript, moving the letter from `IN_REVIEW` to `REQUESTED`. The request supplies the manuscript's `title` and has three effects beyond the status change: `requested_period_index` is stamped with the agency's current `period_index`; a `Manuscript` record is created in `SUBMITTED` status with its `query_letter_id` pointing back to the letter, its `author_id` and `agency_id` copied from the letter, and its `reader_agent_id` initialized to the assigned agent; and the letter leaves the open slush set, so the agent's `open_query_count` is recomputed and the agency posture re-evaluated. Alternatively, the assigned agent may reject the letter (`IN_REVIEW` → `REJECTED`, again guarded by `ERR_NOT_ASSIGNED_AGENT`, with the count and posture recomputed), and either the assigned agent or another agent may reject a letter still sitting unassigned in `RECEIVED` (`RECEIVED` → `REJECTED`, no assignment precondition, posture re-evaluated). Withdrawal is available from either `RECEIVED` or `IN_REVIEW` and lands the letter in `WITHDRAWN`, with `open_query_count` recomputed when the letter was in review and the posture re-evaluated in both cases. `REJECTED`, `WITHDRAWN`, and `LAPSED` are the terminal states of a query letter.

Lapse is the system-driven path out of `REQUESTED`. When the period closes and period N becomes the completed period, every letter still in `REQUESTED` whose `requested_period_index` is at or before N minus one lapses to `LAPSED` — but only while its linked manuscript is still early in its own pipeline, namely `SUBMITTED` or `READER_ASSIGNED`. The lapse then propagates: each lapsed letter's linked manuscript declines to `DECLINED`, a decline caused by the lapse rather than by the period close directly.

### 3.3. Manuscript Evaluation and the Revision Loop

A manuscript begins `SUBMITTED`, fresh from the query that spawned it, with `revision_round` 0 and `eval_score` null. An agent assigns or reassigns the reader, moving the manuscript from `SUBMITTED` to `READER_ASSIGNED`; as with query assignment, the payload's `agent_id` must reference an `ACTIVE` agent of the same agency (`ERR_AGENT_INACTIVE`), and the assignment writes `reader_agent_id`.

Evaluation is personal: only the agent named in `reader_agent_id` may record the score, and any other agent's attempt is rejected with `ERR_NOT_ASSIGNED_AGENT`. The evaluation payload carries an `eval_score` between 0 and 100 inclusive — anything outside that range fails body validation with `ERR_INVALID_REQUEST` — and recording it moves the manuscript from `READER_ASSIGNED` to `EVALUATED`.

Once `EVALUATED`, the manuscript faces a fork with one bounded loop. An agent may send it back to the author for revision (`EVALUATED` → `REVISION_REQUESTED`), which increments `revision_round` by one; the loop is capped, and requesting a revision when `revision_round` has already reached 2 is rejected with `ERR_REVISION_LIMIT_REACHED`. A resubmission returns the manuscript from `REVISION_REQUESTED` to `SUBMITTED` with no preconditions, ready for another reader assignment. Or the agency can dispose of the manuscript outright: acceptance (`EVALUATED` → `ACCEPTED`) requires an `eval_score` of at least 70 and is otherwise rejected with `ERR_SCORE_BELOW_THRESHOLD`; acceptance flips the author to `CLIENT`. Decline (`EVALUATED` → `DECLINED`) carries no precondition. `ACCEPTED` and `DECLINED` are terminal.

### 3.4. Signing the Client: Representation Agreements

An accepted manuscript becomes a client relationship through a `ClientAgreement`. An agent drafts one by supplying the `author_id`, the `manuscript_id` it covers, and the `agent_id` of the signing agent; two optional fields tune the economics: `commission_pct_override`, a per-agreement commission fraction that, when supplied and later locked at signing, displaces the agency default for all commission math on the resulting deals — it is the one nullable field in the API and may be omitted or set explicitly to null, both leaving it unset — and `exclusive`, a boolean defaulting to true that records whether the agency holds exclusive worldwide representation for the manuscript. A drafted agreement starts in `DRAFT` with `agency_id` copied from the manuscript and `signed_period_index` null.

Offering the agreement to the author (`DRAFT` → `OFFERED`) is guarded twice: the manuscript must be `ACCEPTED` (`ERR_MANUSCRIPT_NOT_ACCEPTED`), and the acting agent must be the agreement's own `agent_id` (`ERR_NOT_ASSIGNED_AGENT`). Once `OFFERED`, the author either signs or declines. Signing (`OFFERED` → `SIGNED`) requires that no other agreement covering the same manuscript is already `SIGNED` — a duplicate is rejected with `ERR_AGREEMENT_ALREADY_SIGNED` — and stamps `signed_period_index` with the agency's current `period_index` while flipping the author to `CLIENT`. Declining moves the agreement to `DECLINED_BY_AUTHOR`.

Termination is a contracts function. A `ContractsManager` may move a `SIGNED` agreement to `TERMINATED`, but only while no deal linked to that agreement is still in `NEGOTIATING`, `EXECUTED`, or `ACTIVE`; an open deal blocks termination with `ERR_DEAL_STILL_OPEN`. When the terminated agreement was the author's last remaining `SIGNED` agreement, the author's `status` falls back to `FORMER`. `DECLINED_BY_AUTHOR` and `TERMINATED` are terminal.

### 3.5. Submission Rounds and Editor-Facing Tracking

With a signed agreement in hand, the agent shops the manuscript through submission rounds. Creating a `SubmissionRound` takes the `manuscript_id`, the `agent_id` running the round, and a `max_editors` cap of at least 1 on the number of live submissions the round may hold. Two optional switches tune the round's economics: `auction_mode`, defaulting to false, which turns on rank-based offer selection, and `valuation_mode`, `FRONTLIST` by default or `BACKLIST`, which selects the ranking variant described in §3.6. A new round starts in `DRAFT`, copies `agency_id` from the manuscript, and numbers itself: `round_index` is one plus the count of prior rounds for the same manuscript.

Editors are lined up inside the round as submissions. Creating a `Submission` takes the `submission_round_id` and the `editor_id`; the round must be in `DRAFT` or `OPEN` (a `CLOSED` round rejects with `ERR_INVALID_STATE`), the round must not already contain a submission to the same editor (`ERR_DUPLICATE_SUBMISSION`), and the round's live population — submissions in `QUEUED`, `SENT`, `UNDER_CONSIDERATION`, or `OFFER_EXTENDED` — must still be below `max_editors`, else `ERR_ROUND_CAPACITY_EXCEEDED`. A new submission starts `QUEUED` with `agency_id` copied from the round and both `sent_period_index` and `response_period_index` null.

Opening the round (`DRAFT` → `OPEN`) is one of the system's two OCC-guarded writes: the request must carry `expected_submission_round_version` equal to the round's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` before anything else is examined (see §2.10). Beyond concurrency, three business gates apply: a `SIGNED` client agreement must exist for the manuscript (`ERR_AGREEMENT_NOT_SIGNED`); no other round for the same manuscript may already be `OPEN` (`ERR_ROUND_ALREADY_OPEN`); and the round must hold at least one `QUEUED` submission (`ERR_EMPTY_ROUND`). A successful open increments the round's `version` by one.

Sending is where etiquette becomes law. Marking a submission sent (`QUEUED` → `SENT`) requires the parent round to be `OPEN` (`ERR_ROUND_NOT_OPEN`), requires the editor to be `ACTIVE` (`ERR_EDITOR_INACTIVE`), and enforces an editor exclusivity window, with the gates evaluated in exactly this order — submission state (`ERR_INVALID_STATE`), round openness (`ERR_ROUND_NOT_OPEN`), editor status (`ERR_EDITOR_INACTIVE`), then the window (`ERR_EDITOR_EXCLUSIVE_WINDOW`): no other submission to the same editor — in any round, for any manuscript — may currently be in `SENT`, `UNDER_CONSIDERATION`, or `OFFER_EXTENDED` with a `sent_period_index` of p while the agency's current `period_index` is still less than p + 2. The window is half-open: a send landing exactly at p + 2 is allowed, while one at p + 1 is rejected with `ERR_EDITOR_EXCLUSIVE_WINDOW`. A successful send stamps `sent_period_index` with the current `period_index`.

From `SENT`, the agent records the editor's engagement: marking under consideration moves the submission to `UNDER_CONSIDERATION`, and a pass — from either `SENT` or `UNDER_CONSIDERATION` — lands it in `PASSED` with `response_period_index` stamped. When an offer is recorded against a submission (see §3.6), the submission moves from `SENT` or `UNDER_CONSIDERATION` to `OFFER_EXTENDED`; because an offer is not a terminal answer, a submission moving from `SENT` keeps `response_period_index` null. If that offer later dies — declined, withdrawn by the editor, or superseded in an auction — the submission cascades from `OFFER_EXTENDED` to `PASSED` and `response_period_index` is stamped at that moment.

Withdrawal (`QUEUED`, `SENT`, or `UNDER_CONSIDERATION` → `WITHDRAWN` at the agent's discretion) releases the slot. A submission in `OFFER_EXTENDED` may only be withdrawn manually once its offer has reached `DECLINED`, `WITHDRAWN_BY_EDITOR`, or `SUPERSEDED`; attempting it earlier fails with `ERR_OFFER_STILL_LIVE`. Closing the round (`OPEN` → `CLOSED`) refuses to strand live work: it is blocked while any submission in the round is `UNDER_CONSIDERATION` or `OFFER_EXTENDED` (`ERR_ROUND_HAS_LIVE_SUBMISSIONS`) and while any offer on the round's submissions is `RECEIVED` or `UNDER_NEGOTIATION` (`ERR_ROUND_HAS_LIVE_OFFERS`). A successful close sweeps every `QUEUED` and `SENT` submission in the round to `WITHDRAWN`, releasing any editor exclusivity window those submissions held. `PASSED` and `WITHDRAWN` are terminal for a submission; `CLOSED` is terminal for a round.

### 3.6. Offers, Auctions, and the Award Cascade

An offer arrives against a specific submission. Recording one takes the `submission_id` plus the deal points: `advance_cents`, the three royalty fractions `royalty_pct_hardcover`, `royalty_pct_trade`, and `royalty_pct_ebook`, an optional `royalty_basis` of `NET` (the default) or `RETAIL`, and three subsidiary-rights flags — `includes_film_rights`, `includes_foreign_rights`, and `includes_audio_rights` — each defaulting to false and each recording a right the publisher demands. The submission must be in `SENT` or `UNDER_CONSIDERATION` (any other state fails with `ERR_INVALID_STATE`); recording the offer flips that submission to `OFFER_EXTENDED` and starts the offer in `RECEIVED` with `agency_id` copied from the submission. In an auction-mode round, ranks are recomputed across the live offer set at this moment; otherwise `auction_rank` stays null.

Negotiation is a loop. Opening negotiation moves the offer from `RECEIVED` to `UNDER_NEGOTIATION`; when the editor returns revised terms, the agent records them, which moves the offer from `UNDER_NEGOTIATION` back to `RECEIVED` and overwrites `advance_cents`, the three royalty fractions, `royalty_basis`, and the three rights flags from the payload — `advance_cents` and the three fractions are required in the revision payload, while an omitted `royalty_basis` or rights flag retains its current value rather than resetting to the creation defaults — with auction ranks recomputed across the round's live offers when the round is in auction mode. Either party can kill the offer from either `RECEIVED` or `UNDER_NEGOTIATION`: the agency's decline lands it in `DECLINED`, and the editor's withdrawal lands it in `WITHDRAWN_BY_EDITOR`; both cascade the parent submission to `PASSED`.

Auction ranking, when `auction_mode` is true, assigns every live offer — those in `RECEIVED` or `UNDER_NEGOTIATION` — a 1-based, gapless `auction_rank`, recomputed whenever an offer is created, revised, or leaves the live set through acceptance, supersession, decline, or withdrawal; an offer that is not live carries `auction_rank` null, and leaving the live set clears the rank it held. Each offer's value in cents is its `advance_cents`, plus a royalty weight in cents multiplied by the sum of its three royalty fractions, minus a rights penalty in cents multiplied by the count of rights flags the publisher demands. The weights depend on the round's `valuation_mode`: under `FRONTLIST` the royalty weight is 100,000 cents and the rights penalty is 2,500,000 cents per demanded right, punishing subsidiary-rights grabs heavily; under `BACKLIST` the royalty weight is 60,000 cents and the penalty 1,000,000 cents. Offers sort by value descending, ties broken by earlier `created_at` and then by insertion order. Identical offers can therefore rank differently by mode: consider offer A with advance 2,600,000, royalty fractions summing to 0.20, and one demanded right, against offer B with advance 200,000, fractions summing to 0.10, and no demanded rights — under `FRONTLIST`, B ranks first (210,000 beats 120,000), while under `BACKLIST`, A ranks first (1,612,000 beats 206,000).

Accepting an offer — the exclusive power of a `ContractsManager` — is one of the system's two segregation-of-duties checkpoints: the acting `X-User-ID` must differ from the parent round's `agent_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`, because the agent who ran the round may not also award it. In an auction-mode round only the offer currently ranked `auction_rank` 1 among live offers may be accepted; any other acceptance fails with `ERR_NOT_TOP_RANKED_OFFER`. Acceptance (`RECEIVED` or `UNDER_NEGOTIATION` → `ACCEPTED`) fires the award cascade. Its first counted link creates the `Deal` in `NEGOTIATING` status: `offer_id` points at the winner, `submission_id` is denormalized from the offer, `client_agreement_id` is resolved by walking from the submission through its round to the manuscript and then to that manuscript's `SIGNED` agreement (null in the degenerate case that no `SIGNED` agreement exists at acceptance time), `advance_cents` and `royalty_basis` are copied from the offer, and the three retention flags are inverted from the demands — `retains_film_rights` starts true exactly when `includes_film_rights` was false, and likewise for `retains_foreign_rights` and `retains_audio_rights`. The second counted link supersedes the losers: every other offer in the round sitting in `RECEIVED` or `UNDER_NEGOTIATION` moves to `SUPERSEDED`, and each superseded offer's submission — still `OFFER_EXTENDED` — cascades to `PASSED`. Outside the counted chain, the award fans out across the rest of the round: every other submission still in `QUEUED`, `SENT`, or `UNDER_CONSIDERATION` moves to `WITHDRAWN`. `ACCEPTED`, `DECLINED`, `WITHDRAWN_BY_EDITOR`, and `SUPERSEDED` are terminal for an offer.

### 3.7. Deal Execution, Amendment, and the Advance Waterfall

A freshly awarded deal is negotiable, not final. While the deal is `NEGOTIATING`, a `ContractsManager` may amend it, changing `advance_cents` and any of `retains_film_rights`, `retains_foreign_rights`, or `retains_audio_rights`; each accepted amendment call increments the deal's `version` by one — even one that supplies no fields and changes nothing — and any amendment attempt outside `NEGOTIATING` is rejected with `ERR_INVALID_STATE`. The deal's `royalty_basis` — `NET` or `RETAIL`, copied from the winning offer — is immutable from creation onward, as are its linkages `offer_id`, `submission_id`, and `client_agreement_id`. The deal also carries `advance_earned_out_cents`, initialized to 0, which §3.8 shows growing as royalties reconcile.

Executing the deal (`NEGOTIATING` → `EXECUTED`) is the second OCC-guarded write and the second segregation checkpoint. The request must carry `expected_deal_version` equal to the deal's current `version`, with mismatches rejected as `ERR_STALE_VERSION` — this is what stops a contracts manager from executing terms that were amended since they last read the deal. The acting `X-User-ID` must differ from the parent round's `agent_id` (`ERR_SEGREGATION_OF_DUTIES`). A successful execution stamps `executed_period_index` with the current `period_index`, increments the deal's `version` by one, moves the winning submission — still `OFFER_EXTENDED` — to `WITHDRAWN`, and cuts the advance payment schedule.

The schedule is a fixed three-milestone waterfall over `advance_cents`, computed in a pinned order. The `ON_SIGNING` installment is the advance multiplied by one half, floored to whole cents. The `ON_DELIVERY` installment is the advance multiplied by one quarter, floored to whole cents. The `ON_PUBLICATION` installment is whatever remains — the advance minus the signing and delivery amounts — so the three installments always sum exactly to the advance; an advance of 100,001 cents, for instance, splits 50,000 / 25,000 / 25,001. Each `AdvanceInstallment` copies `agency_id` from the deal, records its `milestone` and computed `amount_cents`, and falls due on a schedule anchored to execution: `ON_SIGNING` is due in `executed_period_index` itself, `ON_DELIVERY` one period later, and `ON_PUBLICATION` two periods later, with `due_period_index` stamped accordingly and `paid_period_index` and `agency_commission_cents` null until payment. Each installment starts `SCHEDULED`.

Installments live and age with the period clock. Each period close advances every unpaid installment by at most one step: a `SCHEDULED` installment whose `due_period_index` is at or below the new `period_index` becomes `DUE` (even when the close overshoots the due period, as it does for `ON_SIGNING`, whose due period is the execution period itself), and a `DUE` installment whose `due_period_index` is strictly below the new `period_index` becomes `LATE`. A `RoyaltiesAccountant` records the publisher's payment by marking the installment paid — allowed from `SCHEDULED`, `DUE`, or `LATE` alike, but only while the deal is `EXECUTED` or `ACTIVE` (`ERR_DEAL_NOT_LIVE`). Payment stamps `paid_period_index` with the current `period_index` and withholds the agency's cut: the installment's `agency_commission_cents` is the installment's `amount_cents` multiplied by the applicable commission fraction, floored to whole cents, where the fraction is the signed agreement's locked `commission_pct_override` when one exists and otherwise the agency's `commission_pct` read at payment time (the agreement itself is resolved by walking from the deal through its offer, submission, round, and manuscript to the manuscript's `SIGNED` agreement). The first installment on a deal to reach `PAID` flips the deal from `EXECUTED` to `ACTIVE`; the period-close sweep re-checks this condition as a backstop.

Termination ends the money. A `ContractsManager` may terminate a deal from `EXECUTED` or `ACTIVE`, but only while no royalty statement for the deal sits in `RECEIVED` or `AUDIT_OPEN` — unresolved statements block termination with `ERR_STATEMENTS_UNRESOLVED`. The termination cascade has two counted links: the deal moves to `TERMINATED`, and every installment of the deal still in `SCHEDULED` or `DUE` is waived to `WAIVED` — a waiver caused by the termination. `LATE` installments are deliberately not waived, and `PAID` installments stay `PAID`. `TERMINATED` is the deal's only terminal state; `PAID` and `WAIVED` are terminal for installments.

### 3.8. Royalty Statements, Reconciliation, and Audit

Once a deal is live, the publisher's statements arrive. A `RoyaltiesAccountant` intakes a statement by supplying the `deal_id`, the `period_index` being reported, per-format unit counts `units_hardcover`, `units_trade`, and `units_ebook` (each zero or greater), the per-format receipts `net_receipts_hardcover_cents`, `net_receipts_trade_cents`, and `net_receipts_ebook_cents`, and the `publisher_reported_royalty_cents` printed on the statement. Two period gates apply at intake: a `period_index` beyond the agency's current `period_index` is a future statement and fails with `ERR_FUTURE_STATEMENT`, while a `period_index` at or before `books_closed_through_period_index` falls inside closed books and fails with `ERR_BOOKS_CLOSED`. Intake imposes no deal-state gate — a statement may be recorded against a deal in any status; only reconciliation requires the deal to be live. For a deal whose `royalty_basis` is `RETAIL`, the three receipts fields are interpreted as retail gross rather than publisher net. A new statement starts `RECEIVED` with `agency_id` copied from the deal and all four computed fields — `gross_royalty_cents`, `agency_commission_cents`, `author_net_cents`, and `variance_cents` — null.

Reconciliation (`RECEIVED` → `RECONCILED`) requires the deal to be `EXECUTED` or `ACTIVE` (`ERR_DEAL_NOT_LIVE`) and computes the author's true royalty from the winning offer's fractions and the deal's basis. Each tiered format is computed line by line with a pinned rounding order — floor the per-unit average first, floor each multiplication second, sum last. For hardcover, the average unit receipt is the hardcover receipts divided by `units_hardcover`, floored; the first 5,000 units (or all of them, if fewer sold) earn that floored average multiplied by the hardcover fraction, floored again, and every unit beyond 5,000 earns the floored average multiplied by the hardcover fraction plus the escalator, floored. Trade paperback works identically against a 7,500-unit threshold and the trade fraction. Ebook has no tier: its royalty is the ebook receipts multiplied by the ebook fraction, floored, as a single whole-format multiplication. The escalator depends on the deal's basis — 0.025 when the basis is `NET`, 0.0125 when it is `RETAIL` — and the escalated tier only applies to formats whose unit count exceeds their threshold; formats with zero units contribute nothing. The `gross_royalty_cents` is the sum of the three lines. To see how basis moves money: at 6,000 hardcover, 8,000 trade, and 10,000 ebook units with receipts of 6,000,000, 3,200,000, and 1,000,000 cents and fractions 0.10, 0.08, and 0.25, the gross comes to 1,136,000 cents under `NET` but 1,120,500 cents under `RETAIL`.

The commission split then divides the gross. The fraction is the signed agreement's `commission_pct_override` when one was locked at signing — the final variant, immutable even if the agency's rate has since moved — and otherwise the agency's `commission_pct` as it stands at reconciliation time, the provisional variant, which floats with the agency rate and never retro-adjusts already-reconciled statements. The statement's `agency_commission_cents` is the gross multiplied by that fraction, floored; `author_net_cents` is the gross minus the commission. For an identical underlying amount the variants diverge exactly as the fraction does: a 250,000-cent installment (or statement line) against an agency rate of 0.15 yields 37,500 cents of commission under the provisional variant, while a locked override of 0.10 yields 25,000. Finally, `variance_cents` is the `publisher_reported_royalty_cents` minus the freshly computed `gross_royalty_cents`, and the deal's `advance_earned_out_cents` grows by the statement's `author_net_cents`, capped so it can never exceed the deal's `advance_cents` — earnings beyond the advance belong to the author but do not move the earn-out field past its cap.

Statements whose numbers don't add up enter the audit loop. Opening an audit (`RECONCILED` → `AUDIT_OPEN`) requires the absolute value of `variance_cents` to exceed 500 cents — the audit tolerance — with anything at or under tolerance rejected as `ERR_VARIANCE_WITHIN_TOLERANCE`, and requires the statement's `period_index` to be strictly beyond `books_closed_through_period_index` (`ERR_BOOKS_CLOSED`); when both would fail, the tolerance check fires first. Resolving the audit (`AUDIT_OPEN` → `AUDIT_RESOLVED`) requires the payload to carry all three adjusted receipts fields — `net_receipts_hardcover_cents`, `net_receipts_trade_cents`, and `net_receipts_ebook_cents` — with any omission failing as `ERR_INVALID_REQUEST`; the receipts are overwritten and all four computed fields recomputed exactly as at reconciliation, and the deal's `advance_earned_out_cents` is adjusted by the difference between the new and old `author_net_cents`, clamped to stay between 0 and `advance_cents`. A resolution that re-submits identical receipts produces a zero difference and leaves the earn-out untouched. If the variance still exceeds tolerance after resolution, the accountant may re-open the audit (`AUDIT_RESOLVED` → `AUDIT_OPEN`) under the same two gates as the original opening; once the variance is at or under 500 cents, the statement may be cleared — from either `RECONCILED` or `AUDIT_RESOLVED` — into the terminal `CLEARED` state, with an out-of-tolerance clear rejected as `ERR_VARIANCE_UNRESOLVED`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state transitions, return `200 OK`. Three action endpoints both transition and spawn records and are classed as transitions returning `200 OK`: request-manuscript carries the spawned `Manuscript` in `data`, offer acceptance carries the accepted offer, and deal execution carries the executed deal. Error responses use the codes catalogued in §5. Request and response bodies follow the envelope of §2.2, pagination follows §2.3, and the complete business rules behind each row live in §3 — the table is a routing summary, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/agencies` | Create an agency | AgencyAdmin |
| GET | `/agencies/{agencyId}` | Get an agency | Any |
| POST | `/agencies/{agencyId}/close-period` | Advance the royalty period; drives lapse, due/late, and activation sweeps | AgencyAdmin, RoyaltiesAccountant |
| POST | `/agencies/{agencyId}/close-books` | Close the books for the most recently completed period | AgencyAdmin, RoyaltiesAccountant |
| POST | `/agents` | Create an agent | AgencyAdmin |
| GET | `/agents/{agentId}` | Get an agent | Any |
| GET | `/agents` | List agents | Any |
| POST | `/agents/{agentId}/deactivate` | Deactivate an agent | AgencyAdmin |
| POST | `/agents/{agentId}/activate` | Reactivate an agent | AgencyAdmin |
| POST | `/authors` | Create an author (starts PROSPECT) | AgencyAdmin, Agent |
| GET | `/authors/{authorId}` | Get an author | Any |
| GET | `/authors` | List authors | Any |
| POST | `/editors` | Create an editor rolodex entry | AgencyAdmin, Agent |
| GET | `/editors/{editorId}` | Get an editor | Any |
| GET | `/editors` | List editors | Any |
| POST | `/editors/{editorId}/deactivate` | Deactivate an editor | AgencyAdmin |
| POST | `/editors/{editorId}/activate` | Reactivate an editor | AgencyAdmin |
| POST | `/query-letters` | Intake a query letter into the slush pile | Agent |
| GET | `/query-letters/{queryLetterId}` | Get a query letter | Any |
| GET | `/query-letters` | List query letters (slush pile view) | Any |
| POST | `/query-letters/{queryLetterId}/assign` | Assign a query to an agent | Agent |
| POST | `/query-letters/{queryLetterId}/request-manuscript` | Request the full manuscript; spawns the Manuscript | Agent |
| POST | `/query-letters/{queryLetterId}/reject` | Reject a query | Agent |
| POST | `/query-letters/{queryLetterId}/withdraw` | Withdraw a query | Agent |
| GET | `/manuscripts/{manuscriptId}` | Get a manuscript | Any |
| GET | `/manuscripts` | List manuscripts | Any |
| POST | `/manuscripts/{manuscriptId}/assign-reader` | Assign or reassign the reader agent | Agent |
| POST | `/manuscripts/{manuscriptId}/evaluate` | Record the reader evaluation score | Agent |
| POST | `/manuscripts/{manuscriptId}/request-revision` | Send the manuscript back for revision | Agent |
| POST | `/manuscripts/{manuscriptId}/resubmit` | Author resubmits after revision | Agent |
| POST | `/manuscripts/{manuscriptId}/accept` | Accept the manuscript for representation | Agent |
| POST | `/manuscripts/{manuscriptId}/decline` | Decline the manuscript | Agent |
| POST | `/client-agreements` | Draft a representation agreement | Agent |
| GET | `/client-agreements/{agreementId}` | Get a client agreement | Any |
| GET | `/client-agreements` | List client agreements | Any |
| POST | `/client-agreements/{agreementId}/offer` | Offer the agreement to the author | Agent |
| POST | `/client-agreements/{agreementId}/sign` | Record author signature | Agent |
| POST | `/client-agreements/{agreementId}/decline` | Author declines the agreement | Agent |
| POST | `/client-agreements/{agreementId}/terminate` | Terminate a signed agreement | ContractsManager |
| POST | `/submission-rounds` | Create a submission round for a manuscript | Agent |
| GET | `/submission-rounds/{roundId}` | Get a submission round | Any |
| GET | `/submission-rounds` | List submission rounds | Any |
| POST | `/submission-rounds/{roundId}/open` | Open the round (OCC on the round's version) | Agent |
| POST | `/submission-rounds/{roundId}/close` | Close the round; queued and sent submissions withdraw | Agent |
| POST | `/submissions` | Queue a submission to an editor within a round | Agent |
| GET | `/submissions/{submissionId}` | Get a submission | Any |
| GET | `/submissions` | List submissions | Any |
| POST | `/submissions/{submissionId}/send` | Mark the submission sent; editor exclusivity window enforced | Agent |
| POST | `/submissions/{submissionId}/mark-under-consideration` | Editor is actively reading | Agent |
| POST | `/submissions/{submissionId}/pass` | Editor passes | Agent |
| POST | `/submissions/{submissionId}/withdraw` | Withdraw a submission | Agent |
| POST | `/offers` | Record an editor's offer against a submission | Agent |
| GET | `/offers/{offerId}` | Get an offer | Any |
| GET | `/offers` | List offers | Any |
| POST | `/offers/{offerId}/negotiate` | Open negotiation | Agent |
| POST | `/offers/{offerId}/revise` | Editor returns revised terms | Agent |
| POST | `/offers/{offerId}/accept` | Accept the winning offer; creates the Deal; supersedes losers | ContractsManager |
| POST | `/offers/{offerId}/decline` | Agency declines the offer | Agent |
| POST | `/offers/{offerId}/editor-withdraw` | Editor withdraws the offer | Agent |
| GET | `/deals/{dealId}` | Get a deal | Any |
| GET | `/deals` | List deals | Any |
| PATCH | `/deals/{dealId}` | Amend deal terms while NEGOTIATING | ContractsManager |
| POST | `/deals/{dealId}/execute` | Execute the contract (OCC on the deal's version); spawns advance installments | ContractsManager |
| POST | `/deals/{dealId}/terminate` | Terminate a deal | ContractsManager |
| POST | `/royalty-statements` | Intake a publisher royalty statement | RoyaltiesAccountant |
| GET | `/royalty-statements/{statementId}` | Get a royalty statement | Any |
| GET | `/royalty-statements` | List royalty statements | Any |
| POST | `/royalty-statements/{statementId}/reconcile` | Recompute royalties and variance | RoyaltiesAccountant |
| POST | `/royalty-statements/{statementId}/open-audit` | Open a royalty audit | RoyaltiesAccountant |
| POST | `/royalty-statements/{statementId}/resolve-audit` | Record audit-adjusted receipts | RoyaltiesAccountant |
| POST | `/royalty-statements/{statementId}/clear` | Clear a statement once variance is within tolerance | RoyaltiesAccountant |
| GET | `/advance-installments/{installmentId}` | Get an advance installment | Any |
| GET | `/advance-installments` | List advance installments | Any |
| POST | `/advance-installments/{installmentId}/mark-paid` | Record publisher advance payment | RoyaltiesAccountant |

List endpoints accept filter query parameters as described in §3's narratives — every list endpoint filters by `agency_id` and `status`; query letters additionally by `author_id` and `assigned_agent_id`; manuscripts additionally by `author_id`, `query_letter_id`, and `reader_agent_id`; client agreements by `author_id`, `manuscript_id`, and `agent_id`; submission rounds by `manuscript_id` and `agent_id`; submissions by `submission_round_id` and `editor_id`; offers by `submission_id`; deals by `offer_id`, `submission_id`, and `client_agreement_id`; royalty statements by `deal_id` and `period_index`; and advance installments by `deal_id` and `milestone` — in addition to the `limit` and `offset` pagination parameters of §2.3. Filters match field values exactly; `period_index` is compared as an integer, and a non-integer value for it fails with `ERR_INVALID_REQUEST`. Query parameters that are neither documented filters nor pagination parameters are ignored. "Any" in the table means any of the four roles of §2.1.

## 5. Error Code Catalogue

Trigger conditions for each error live in the workflow narratives of §2 and §3; this table is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_AGENT` | 403 Forbidden |
| `ERR_AGENT_INACTIVE` | 409 Conflict |
| `ERR_EDITOR_INACTIVE` | 409 Conflict |
| `ERR_INTAKE_PAUSED` | 409 Conflict |
| `ERR_SCORE_BELOW_THRESHOLD` | 409 Conflict |
| `ERR_REVISION_LIMIT_REACHED` | 409 Conflict |
| `ERR_MANUSCRIPT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_AGREEMENT_ALREADY_SIGNED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_SIGNED` | 409 Conflict |
| `ERR_DEAL_STILL_OPEN` | 409 Conflict |
| `ERR_ROUND_ALREADY_OPEN` | 409 Conflict |
| `ERR_EMPTY_ROUND` | 409 Conflict |
| `ERR_ROUND_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_ROUND_NOT_OPEN` | 409 Conflict |
| `ERR_DUPLICATE_SUBMISSION` | 409 Conflict |
| `ERR_EDITOR_EXCLUSIVE_WINDOW` | 409 Conflict |
| `ERR_ROUND_HAS_LIVE_SUBMISSIONS` | 409 Conflict |
| `ERR_ROUND_HAS_LIVE_OFFERS` | 409 Conflict |
| `ERR_OFFER_STILL_LIVE` | 409 Conflict |
| `ERR_NOT_TOP_RANKED_OFFER` | 409 Conflict |
| `ERR_DEAL_NOT_LIVE` | 409 Conflict |
| `ERR_STATEMENTS_UNRESOLVED` | 409 Conflict |
| `ERR_FUTURE_STATEMENT` | 409 Conflict |
| `ERR_BOOKS_CLOSED` | 409 Conflict |
| `ERR_VARIANCE_WITHIN_TOLERANCE` | 409 Conflict |
| `ERR_VARIANCE_UNRESOLVED` | 409 Conflict |
| `ERR_INTERNAL` | 500 Internal Server Error |

# Participatory Budgeting API — Product Requirements Document

## 1. Introduction

Participatory budgeting invites residents of a jurisdiction to decide directly how a slice of public money is spent. This document specifies the API that powers such a program end-to-end: it lets a community propose ideas, verify who is eligible to vote, develop and cost those ideas into fundable proposals, collect votes under either a ranked or a dollar-allocation method, select and fund the winners against a fixed budget, track the implementation of funded projects, and report the results back to the public in multiple languages.

The system is organized around a **budget cycle** — a single fiscal-year exercise that moves through a strict sequence of phases, from initial configuration through submission, development, voting, selection, implementation, and finally closure. Every child activity in the program is gated by the phase its owning cycle currently occupies, so the same operation may be permitted at one moment and rejected at another. Alongside this posture-driven gating, the platform enforces conservation of a fixed budget: awards are drawn down against both a program-wide total and per-category sub-caps, and every award or cancellation must leave the ledger internally consistent. Accessibility and multilingual rendering are first-class concerns throughout, so that participation is not limited by language or ability.

This specification is written for the engineers who will implement the service. It describes the domain rules first and the transport contract second; where a numeric threshold, rounding rule, or ordering matters to correctness, it is stated exactly.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply across every endpoint of the API. All resource paths are mounted under the service root.

### 2.1. User and Role-Based Access Control

Every request carries its caller identity in two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. The system recognizes four roles, spelled exactly as follows: `Anonymous`, `Resident`, `Reviewer`, and `BudgetAdmin`. If either header is missing, or `X-User-Role` is not one of these four known roles, the request is rejected with `ERR_UNAUTHENTICATED`. The `Anonymous` role is only accepted on endpoints that explicitly list it; using `Anonymous` anywhere else is likewise treated as an authentication failure and rejected with `ERR_UNAUTHENTICATED`. When the acting role is a known role but is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`.

The four roles map to identity as follows. When `X-User-Role` is `Resident`, `X-User-ID` is the `id` of the acting `Resident`; ownership checks on any resource that references a `Resident` compare the resource's foreign-key field to `X-User-ID`. Concretely, a proposal's `submitter_id` and a ballot's `voter_id` are the resident foreign keys used for these ownership comparisons. When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque public identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. When `X-User-Role` is `Reviewer`, `X-User-ID` is an opaque civic-staff operator identifier not tied to any persisted entity; the server may accept and record it but does not compare it to any entity's `id`. When `X-User-Role` is `BudgetAdmin`, `X-User-ID` is likewise an opaque administrator identifier not tied to any persisted entity and is not compared to any entity's `id`.

Roles carry distinct authority. A `Resident` is a civic participant who owns the proposals they submit and the ballots they cast. A `Reviewer` is civic staff who verify residents, review and cost proposals, and manage implementation milestones and report-backs. A `BudgetAdmin` is the program administrator who configures cycles and categories, advances phases, runs funding selection, and releases or cancels funding. `Anonymous` is the unauthenticated public actor who may self-register as a resident, submit a verification request, and read public cycle and proposal data.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items a response may contain; when omitted it defaults to 10, and callers may set it no lower than 1 and no higher than 100. A supplied `limit` outside that range is silently clamped to the nearest bound (below 1 becomes 1, above 100 becomes 100), and a non-integer or otherwise unparseable `limit` falls back to the default of 10. The `offset` parameter skips a number of leading items and defaults to 0; a negative or unparseable `offset` is treated as 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order.

Every list-based response reports its pagination state in the `meta` object of the envelope through the fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Cycle Phase Posture and Gated Operations

The budget cycle is the posture parent of the entire program. Its `phase` field is a system-managed enumeration that takes exactly one of the values `DRAFT`, `SUBMISSION`, `DEVELOPMENT`, `VOTING`, `SELECTION`, `IMPLEMENTATION`, or `CLOSED`, and a freshly created cycle begins in `DRAFT`. The phase advances only forward along the single pipeline `DRAFT → SUBMISSION → DEVELOPMENT → VOTING → SELECTION → IMPLEMENTATION → CLOSED`. Each advance is requested by a `BudgetAdmin` who names the phase they intend the cycle to move to in a `target_phase` field. The request is honored only when `target_phase` is exactly the single next phase in the pipeline; naming any other phase — whether a skip forward, a repeat, or a move backward — is rejected with `ERR_INVALID_PHASE_TRANSITION` (HTTP 409). Advancing out of `DRAFT` into `SUBMISSION` additionally requires that at least one `Category` already exist for the cycle; without one the advance cannot proceed. Advancing out of `SELECTION` into `IMPLEMENTATION` additionally requires that the cycle already have at least one selection run marked as the current run. A request whose `target_phase` is the correct next phase but that fails either of these preconditions is rejected with `ERR_INVALID_STATE` (HTTP 409). `CLOSED` is terminal. Every successful phase advance increments the cycle's `version` by one.

Because the phase gates all child work, most write operations on children carry a required-phase precondition, checked after authentication and existence but as its own concern: proposal creation and submission require the cycle to be in `SUBMISSION`; adding cost line items and finalizing cost require `DEVELOPMENT`; opening, casting, and withdrawing ballots require `VOTING`; running funding selection requires `SELECTION`; and releasing or cancelling funding requires the cycle to be in `IMPLEMENTATION` (cancellation is additionally permitted while the cycle is still in `SELECTION`). When an operation is attempted against a cycle that is not in the phase it requires, the request is rejected with `ERR_WRONG_PHASE` (HTTP 409).

One phase advance carries a cascade of its own. When a cycle moves from `DEVELOPMENT` into `VOTING`, the system automatically transitions every proposal in that cycle whose status is `COSTED` from `COSTED` to `ON_BALLOT`, and each such automatic transition increments that proposal's `version` by one. Proposals that have not reached `COSTED` by that moment are left where they are and can no longer be costed, because costing is only available while the cycle is in `DEVELOPMENT`. This is the sole path by which a proposal reaches `ON_BALLOT`: it happens as a side effect of its owning cycle entering `VOTING`, never by a direct request.

### 2.5. Common Resource Properties and Versioning

Most resources in the system carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification, and the `version` field is an integer that starts at its initial value and increments by one on every mutation, including mutations that only touch computed or system fields. These common fields are carried by the budget cycle, category, resident, proposal, cost line item, ballot, ballot entry, selection run, and milestone resources.

The report-back resource is the one exception: it is append-only and immutable after creation, so it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field. Any process that would otherwise "touch" a report-back does not exist — once published, a report-back is never modified.

Whenever a mutation changes a resource, both its `updated_at` and its `version` move together. This applies equally to cascade-driven changes: when a computed field such as a category's committed total or a cycle's uncommitted balance is recomputed as a downstream effect of some other operation, that recomputation is itself a mutation of the affected resource and advances its `updated_at` and `version`.

### 2.6. Budget Conservation and the Cycle Ledger

The program's money is tracked as a strict ledger anchored at the budget cycle and rolled up from its categories. A cycle is created with a fixed `total_budget_cents`, the total disbursable amount in integer cents, and each `Category` created under it carries its own `category_budget_cap_cents`, a per-category sub-cap that awards to that category may never exceed. All monetary amounts in this system are integer cents; there is no fractional-cent representation.

Four computed quantities keep the ledger consistent, and they are recomputed together on every event that changes a proposal's awarded amount — that is, on every award made during funding selection and on every cancellation that reverses an award. A category's `committed_cents` is the sum of `awarded_cents` over the proposals in that category whose status is `SELECTED`, `IN_IMPLEMENTATION`, or `COMPLETED`. That category's `remaining_cap_cents` is its `category_budget_cap_cents` minus its `committed_cents`. Rolling up one level, the cycle's `total_committed_cents` is the sum of `committed_cents` across all of that cycle's categories, and the cycle's `uncommitted_cents` — the conserved quantity of the whole program — is `total_budget_cents` minus `total_committed_cents`. When a proposal is cancelled, its `awarded_cents` is reset to zero and these same four quantities are recomputed, restoring the released money to the uncommitted pool.

Because every award equals a proposal's exact final estimate and every amount is already an integer number of cents, the ledger arithmetic requires no rounding; the funding step neither rounds nor truncates. Rounding does arise in cost estimation, and where it does the rule is fixed: amounts are rounded half up (a value exactly at the halfway point rounds away from zero, upward) to a whole number of integer cents at each pinned rounding step described in §3.

### 2.7. Multilingual Rendering and Accessibility

The platform is built for a multilingual public. Each cycle declares a `default_language`, and every resident declares a `preferred_language`; both are drawn from the same fixed set of language codes `en`, `es`, `zh`, `vi`, and `ar`, and both default to `en` when not supplied. Proposals and report-backs may additionally carry a `translations` map, keyed by language code, holding the translated content for that language — for a proposal, the translated `title` and `summary`; for a report-back, the translated narrative. When not provided, the `translations` map defaults to empty.

Accessibility accommodations travel with the resident. A resident may declare `accessibility_needs`, a list of accommodation codes (for example a screen-reader or large-print flag), which defaults to an empty list when not supplied. These preferences are recorded on the resident so that downstream rendering can honor them.

### 2.8. The Logical Clock and Temporal Windows

The service runs on a logical clock rather than real wall-clock time, so that age and window calculations are deterministic and testable. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and until it is explicitly moved it continues to read that default — it never falls back to real time. A `BudgetAdmin` may move the clock by supplying a target instant in the `to_iso8601` field; doing so affects every subsequent age derivation and window check.

A budget cycle defines two activity windows against this clock. The submission window runs from `submission_start` up to but not including `submission_end`, and the voting window runs from `voting_start` up to but not including `voting_end`; both are half-open intervals that include their start and exclude their end. At cycle creation these windows are validated: each window's start must be strictly before its own end, the two windows must not overlap, and submission must not run past the start of voting — specifically `submission_end` must be at or before `voting_start`, so exact adjacency (`submission_end` equal to `voting_start`) is allowed but any true overlap is not. A cycle whose windows violate any of these conditions is rejected with `ERR_PHASE_WINDOW_OVERLAP` (HTTP 422).

### 2.9. Nested Resource Retrieval and Validation Ordering

Many endpoints address a resource nested beneath a parent — a category or proposal or ballot under a cycle, a cost line item or milestone or report-back under a proposal, an entry under a ballot. For any such request, the system validates the path identifiers left-to-right and rejects at the first one that does not resolve to an existing resource, returning the not-found error specific to that resource type. After the path identifiers, any foreign-key references carried in the body — `budget_cycle_id`, `category_id`, `submitter_id`, `proposal_id`, `ballot_id`, and `voter_id` — are checked for existence as well. The specific codes are `ERR_BUDGET_CYCLE_NOT_FOUND`, `ERR_CATEGORY_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`, and `ERR_MILESTONE_NOT_FOUND`, each HTTP 404.

The validation concerns across the whole API are applied in a fixed priority order, so that when several would fail the same request, the earliest-listed one is the one the caller sees. The order is: first, authentication of the headers (`ERR_UNAUTHENTICATED`); then authorization of the role against the endpoint (`ERR_UNAUTHORIZED`); then request-shape validation — required fields present, enum values within their declared sets, constrained integers non-negative, and vote-method fields carrying the correct shape (`ERR_VALIDATION`); then existence of every referenced resource, path identifiers before body foreign keys (the not-found codes above); then the owning cycle's phase requirement (`ERR_WRONG_PHASE`); then the target entity's own-state requirement for a transition, including that a phase transition names exactly the next phase (`ERR_INVALID_STATE`, or `ERR_INVALID_PHASE_TRANSITION` for a non-adjacent target phase). Business rules specific to individual workflows — category-cycle matching, ballot eligibility, age, duplicate ballots, duplicate ranks, milestone spacing, allocation caps, ownership, and the stale-version check on selection — are evaluated after these system-wide gates, in the priority relationships called out where each rule is described in §3.

### 2.10. Optimistic Concurrency Control on Selection Runs

Funding selection is the one operation guarded by optimistic concurrency control. A `BudgetAdmin` who starts a selection run against a cycle must include `expected_budgetcycle_version`, carrying the `version` of the cycle they last observed. If that value does not equal the cycle's current `version`, the run is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412). Running selection a second time is itself a legitimate product operation — a newer run supersedes the prior current run, for example to re-tally after a corrected estimate — but the first run advances the cycle's `version`, so any writer still holding the pre-run version is working from a superseded view of the results and must re-read before running again. This guard is expressed purely in terms of the observed-versus-current version; it is not a matter of requests arriving at the same moment. No other endpoint takes a version field, and no other endpoint applies an optimistic-concurrency check.

## 3. Business Logic & Workflows

### 3.1. Resident Registration and Eligibility Verification

Participation begins with registration. Anyone from the public, and also a `BudgetAdmin` acting on someone's behalf, may register a resident by supplying the resident's `full_name`, their `date_of_birth` as an ISO date in `YYYY-MM-DD` form, a `residency_document_ref` pointing at their uploaded proof-of-residency document, and their claimed in-jurisdiction `residency_address`. The registration may also carry a `preferred_language` and a list of `accessibility_needs`; when either is omitted the defaults from §2.7 apply. A newly registered resident starts with `eligibility_status` equal to `UNVERIFIED`, and their `rejection_reason` is empty.

Verification is a small cyclic workflow. A resident (or the public actor acting for them) submits proof by requesting verification, which moves the resident from `UNVERIFIED` to `PENDING_VERIFICATION`; the request may include an updated `residency_document_ref`. A resident who was previously turned down may resubmit: requesting verification again while in `REJECTED` moves them back to `PENDING_VERIFICATION` and clears their `rejection_reason`. In both cases the resident's `version` increments by one. Only a resident currently in `UNVERIFIED` or `REJECTED` may enter `PENDING_VERIFICATION` this way; attempting the request from any other state is an invalid transition and is rejected with `ERR_INVALID_STATE`.

A `Reviewer` then adjudicates a pending resident by recording a decision. Approving a resident who is in `PENDING_VERIFICATION` moves them to `VERIFIED`. Rejecting a resident who is in `PENDING_VERIFICATION` moves them to `REJECTED` and stores the supplied `rejection_reason` on the resident; the approve path, by contrast, records no reason. The decision is carried in a `decision` field whose value selects approval or rejection, with an optional `rejection_reason` accompanying a rejection. Either decision increments the resident's `version` by one, and a decision is only valid against a resident currently in `PENDING_VERIFICATION`; otherwise it is rejected with `ERR_INVALID_STATE`.

A resident's `age` is not stored as a fact but derived on demand against the logical clock, in full completed years. It is computed as the difference between the clock's current year and the birth year, reduced by one when the current month-and-day falls before the birth month-and-day (that is, when the resident has not yet had their birthday this year). Age matters chiefly at voting time, where it is compared against the cycle's minimum voting age as described in §3.5.

### 3.2. Program Setup: Cycles and Categories

A `BudgetAdmin` establishes a participatory-budgeting exercise by creating a budget cycle. The creation payload gives the cycle a human `name`, the `fiscal_year` it funds, and its money and rules: `total_budget_cents` (the total disbursable budget, which must be greater than zero), `voting_method` (either `RANKED` or `ALLOCATION`), `per_project_cap_cents` (the ceiling on any single award, greater than zero), and `per_voter_allocation_cap_cents` (the most cents one voter may spread across a ballot under the allocation method, which must be zero or greater and is ignored entirely under the ranked method). The payload also sets the four window instants `submission_start`, `submission_end`, `voting_start`, and `voting_end`, validated as described in §2.8. Two further inputs are optional: `min_voter_age`, the minimum resident age in full years required to vote in this cycle, which must be zero or greater and defaults to 16 when omitted; and `default_language`, which defaults to `en`. A new cycle is born in `DRAFT` with its computed ledger fields `total_committed_cents` and `uncommitted_cents` at their opening values and `completed_project_count` at zero.

Within a cycle, the administrator defines spending categories. A category is created with a `name`, an optional `description` (empty by default), a `category_budget_cap_cents` sub-cap that must be greater than zero, and an optional `display_order`. The `display_order` is a UI sort index only and defaults to zero; it never serves as a business tie-break in any ranking or selection decision. Each category is bound to its owning cycle through `budget_cycle_id`, and its computed `committed_cents` and `remaining_cap_cents` follow the ledger rules of §2.6. Because moving a cycle out of `DRAFT` requires at least one category to exist, category creation is in practice the first configuration step after the cycle itself.

### 3.3. Idea Submission and Proposal Review

Once a cycle is open for submissions — that is, once it is in `SUBMISSION` — a `Resident` submits an idea, which is recorded as a proposal in `DRAFT` status. The submission names the target `category_id` and carries the idea's `title` and `summary`, and it may include a `translations` map for multilingual rendering. The proposal's `submitter_id` is set from the acting resident's `X-User-ID`, and its `budget_cycle_id` is the cycle it is filed under. Proposal and ballot list endpoints accept an optional `status` filter that narrows results to resources in a given lifecycle state, and the proposal list additionally accepts `budget_cycle_id`, `category_id`, and `submitter_id` filters while the ballot list accepts `voter_id` and `budget_cycle_id` filters. A proposal must be filed into a category that belongs to the very same cycle; if the named `category_id` resolves to a category under a different cycle than the proposal's `budget_cycle_id`, the request is rejected with `ERR_CATEGORY_CYCLE_MISMATCH` (HTTP 422).

The submitter advances their own draft: submitting a proposal moves it from `DRAFT` to `SUBMITTED`. This is permitted only while the proposal is still in `DRAFT`, only while the owning cycle is in `SUBMISSION`, and only when the acting resident is the proposal's submitter — the acting `Resident`'s id must equal the proposal's `submitter_id`, or the request is rejected with `ERR_NOT_OWNER`. The submit action increments the proposal's `version` by one.

A `Reviewer` then triages a submitted proposal by recording a review decision, which forks. Approving a `SUBMITTED` proposal moves it to `DEVELOPING`, opening it for costing. Rejecting a `SUBMITTED` proposal instead moves it to `REJECTED` and stores the supplied `rejection_reason` on the proposal; the approve branch records no reason, and that divergence is the only difference between the two branches' effects beyond the destination state. The decision travels in the same `decision`/`rejection_reason` shape used for resident verification. Both branches require the proposal to be in `SUBMITTED` and the cycle to be in `DEVELOPMENT`, and both increment the proposal's `version` by one. A review decision against a proposal not in `SUBMITTED` is rejected with `ERR_INVALID_STATE`.

### 3.4. Cost Estimation and Finalization

A proposal in `DEVELOPING` is costed up line by line. Both a `Reviewer` and the proposal's own submitting `Resident` may add cost line items; when the actor is a `Resident`, the ownership rule applies and the acting resident must be the proposal's submitter, otherwise the add is rejected with `ERR_NOT_OWNER`. Each line item is filed against its `proposal_id` and carries a `label`, a `unit_cost_cents` amount (zero or greater), a `quantity` (at least one), and an optional `contingency_pct`, a line-level contingency fraction expressed as a decimal — 0.10 meaning ten percent — that is zero or greater and defaults to zero. Adding a line item recomputes the proposal's provisional estimate and increments the proposal's `version` by one.

Each line has a gross amount equal to its `unit_cost_cents` multiplied by its `quantity`, an exact integer number of cents. The line's own recorded `line_provisional_cents` is that gross amount multiplied by one plus the greater of its `contingency_pct` and zero, then rounded half up to whole cents. The proposal's `provisional_estimate_cents` is the sum of these per-line provisional amounts: the rounding is pinned per line, so each line is rounded first and only then are the rounded lines summed. The provisional estimate applies each line's contingency exactly as entered and adds no overhead. It is recomputed on every line-item add while the proposal remains in `DEVELOPING`.

Finalizing the cost is a `Reviewer` action that moves the proposal from `DEVELOPING` to `COSTED`. It is permitted only while the proposal is in `DEVELOPING` and the cycle is in `DEVELOPMENT`, and it requires the proposal to have at least one cost line item; finalizing a proposal that has no line items is rejected with `ERR_NO_LINE_ITEMS` (HTTP 422). Finalizing computes the proposal's `estimated_cost_cents` and increments its `version` by one. The final estimate differs from the provisional one in two ways. First, each line's contingency is floored to a minimum of ten percent: the per-line amount is the line's gross multiplied by one plus the greater of the line's `contingency_pct` and 0.10, rounded half up to whole cents. Second, after these floored per-line amounts are summed into a subtotal (again rounding per line before summing), a single program overhead of five percent is applied to that subtotal — the subtotal multiplied by 1.05 — and that result is rounded half up to whole cents one final time. The final and provisional figures coincide only when every line already carries a contingency of at least ten percent and the overhead is zero; whenever any line's contingency is below ten percent, or the overhead applies, the final figure is the larger. This finalized `estimated_cost_cents` is the amount funding selection later uses.

### 3.5. Voting: Opening a Ballot and Adding Preferences

Voting opens when a cycle enters `VOTING`. A `Resident` opens their ballot in that cycle, and the new ballot is created in `DRAFT` with its `voter_id` set from the acting resident's `X-User-ID` and its `budget_cycle_id` set to the cycle. At creation the ballot snapshots the cycle's tally rule into its own `method` field — either `RANKED` or `ALLOCATION` — so that the ballot's behavior is fixed even if anything else changes. Its `cast_at` timestamp is empty until the ballot is first cast, and its computed `total_allocated_cents` begins at zero.

Opening a ballot is gated by several eligibility checks. The cycle must be in `VOTING`. The voter must be verified: a resident whose `eligibility_status` is anything other than `VERIFIED` is turned away with `ERR_RESIDENT_NOT_ELIGIBLE` (HTTP 403). The voter must also clear the age floor — the resident's derived `age` must be at least the cycle's `min_voter_age`, evaluated inclusively so that a resident whose age exactly equals the floor is eligible while one a single year short is not — and failing this yields `ERR_UNDER_AGE` (HTTP 422). Finally, a resident may hold at most one ballot per cycle that has not been withdrawn: if the resident already has a ballot in `DRAFT` or `CAST` status in this cycle, a second creation is a duplicate and is rejected with `ERR_DUPLICATE_BALLOT` (HTTP 409). A withdrawn ballot does not count against this limit.

Onto a `DRAFT` ballot the same `Resident` adds preference entries, one per proposal they wish to express a preference about. An entry names its `proposal_id` and, depending on the ballot's method, carries either a `rank` or an `allocated_cents` amount; each entry is bound to its owning ballot through `ballot_id`. The shapes are mutually exclusive and enforced: under the ranked method an entry must carry a `rank` and must not carry `allocated_cents`, while under the allocation method an entry must carry `allocated_cents` and must not carry a `rank`; a mismatched shape is a request-validation failure rejected with `ERR_VALIDATION`. Because this rule depends on the ballot's snapshotted `method`, the standalone range checks on `rank` and `allocated_cents` are applied up front (before the ballot is loaded), but the method-versus-shape mutual-exclusivity check is evaluated only after the ballot has been loaded and confirmed to be in `DRAFT`; a ballot that is not in `DRAFT` is therefore rejected with `ERR_INVALID_STATE` before its entry shape is examined. A `rank`, when present, is a one-based preference position between 1 and 10 inclusive; an `allocated_cents`, when present, is zero or greater. An entry may only reference a proposal that is actually on the ballot — its `proposal_id` must resolve to a proposal whose status is `ON_BALLOT`, and otherwise the entry is rejected with `ERR_PROPOSAL_NOT_ON_BALLOT` (HTTP 409). Adding an entry is an owner-scoped action, so the acting resident must be the ballot's voter or the request is rejected with `ERR_NOT_OWNER`; each successful add increments the ballot's `version` by one. Every entry begins `active` and carries a computed `points` value, both of which come into play at cast time.

### 3.6. Casting, Withdrawing, and Vote Tallying

Casting commits a ballot's preferences to the tally. A `Resident` casts their ballot, moving it from `DRAFT` to `CAST` (a withdrawn ballot may also be re-cast, moving it from `WITHDRAWN` back to `CAST`). Casting is permitted only while the cycle is in `VOTING` and only for the ballot's own voter, so the acting resident must be the ballot's voter or the request is rejected with `ERR_NOT_OWNER`. Under the ranked method, the ballot's active entries must all carry distinct ranks, each within 1 to 10; two active entries sharing a rank are rejected with `ERR_DUPLICATE_RANK` (HTTP 422). Under the allocation method, the sum of the active entries' `allocated_cents` must not exceed the cycle's `per_voter_allocation_cap_cents`, evaluated inclusively so that a total exactly equal to the cap is allowed; exceeding it is rejected with `ERR_ALLOCATION_CAP_EXCEEDED` (HTTP 422). Casting sets the ballot's `cast_at` to the logical clock's current instant, folds each entry's contribution into the referenced proposals' running scores, and increments the ballot's `version` by one.

Each referenced proposal keeps a running `vote_score` that is recomputed as ballots are cast and withdrawn, and the units depend on the ballot method. Under the ranked method the score is a Borda tally: an entry earns points equal to ten minus one less than its rank — equivalently, a first-choice entry (rank 1) earns 10 points, a rank-2 entry earns 9, and so on downward — with the floor that points never go below zero, so a rank beyond the tenth position contributes nothing. A proposal's ranked score is the sum of these `points` over all active entries on cast ballots that reference it. Under the allocation method the score is instead the sum of `allocated_cents` over all active entries on cast ballots that reference the proposal; ranks are ignored. In both methods only entries that are `active` and belong to a ballot currently in `CAST` count toward a proposal's `vote_score`. A ballot under the allocation method also maintains `total_allocated_cents`, the sum of `allocated_cents` across its active entries.

Withdrawing reverses a cast exactly. A `Resident` withdraws their own cast ballot while the cycle is in `VOTING`, moving it from `CAST` to `WITHDRAWN`. Withdrawal deactivates every entry — setting each entry's `active` flag off — and subtracts this ballot's contribution back out of every referenced proposal's `vote_score`, so that the reversal precisely undoes what the cast added. It also resets the ballot's `total_allocated_cents` to zero and increments the ballot's `version` by one. Because the machine is cyclic, a resident who withdrew may cast again: re-casting a `WITHDRAWN` ballot re-activates its entries, re-adds their contribution to the referenced proposals' scores, refreshes `cast_at`, and again increments the ballot's `version`. Any cast or re-cast is subject to the same distinct-rank and allocation-cap checks described above.

### 3.7. Funding Selection

When a cycle reaches `SELECTION`, a `BudgetAdmin` runs funding selection, which tallies the ballot slate and funds the winners. A selection run is filed against its `budget_cycle_id`, and the run must carry `expected_budgetcycle_version` matching the cycle's current `version`, subject to the optimistic-concurrency guard of §2.10 that rejects a stale run with `ERR_STALE_CYCLE_VERSION`. The run may only proceed while the cycle is in `SELECTION`. Each run records how many proposals it funded in `selected_count`, the sum it awarded in `total_awarded_cents`, and an `is_current` flag; a newly created run becomes the authoritative current run and supersedes any prior run by clearing that prior run's `is_current` to false. Completing a run increments the cycle's `version` by one.

The slate consists of the proposals in the cycle whose status is `ON_BALLOT`, and their inputs are the finalized `estimated_cost_cents` and the running `vote_score`. The run first orders the slate by `vote_score` from highest to lowest, breaking ties by `created_at` earliest-first — never by `id` and never by `display_order`. It then walks the slate in that order while maintaining two draw-down pools: a program-wide remaining total that begins at the cycle's `total_budget_cents`, and, for each category, a remaining category pool that begins at that category's `category_budget_cap_cents`.

For each proposal in turn, the candidate award is its own `estimated_cost_cents`, and one of three outcomes follows. If that cost exceeds the cycle's `per_project_cap_cents`, the proposal cannot be funded even in principle — proposals are never partially funded — so it moves from `ON_BALLOT` to `NOT_SELECTED` and its `awarded_cents` stays at zero. Otherwise, if the cost is less than or equal to the smaller of the remaining total pool and the remaining pool of the proposal's own category, the proposal is funded: it moves from `ON_BALLOT` to `SELECTED`, its `awarded_cents` is set to exactly its `estimated_cost_cents`, and that same amount is subtracted from both the remaining total pool and the proposal's category pool. This boundary is inclusive, so a proposal whose cost exactly equals the smaller remaining pool is funded. If neither holds — the cost is within the per-project cap but would overrun the remaining total or the remaining category pool — the proposal moves to `NOT_SELECTED` with `awarded_cents` left at zero, and the walk continues in a waterfall fashion: a cheaper, lower-ranked proposal further down the slate may still fit within what remains. All of these amounts are exact integer cents and no rounding occurs at this step.

Each proposal set to `SELECTED` triggers the ledger cascade of §2.6: its new award is now counted into its owning category's `committed_cents`, and that change rolls up to recompute the cycle's `total_committed_cents` and `uncommitted_cents`. Every proposal touched by the run — whether newly `SELECTED` or `NOT_SELECTED` — has its own `version` incremented by one for that transition.

### 3.8. Implementation Tracking and Report-Back

Once selection has produced a current run, the cycle can advance to `IMPLEMENTATION`, and funded work begins. A `BudgetAdmin` releases funding for a selected proposal, moving it from `SELECTED` to `IN_IMPLEMENTATION`; this is permitted only while the proposal is `SELECTED` and the cycle is in `IMPLEMENTATION`, and it increments the proposal's `version` by one. The administrator may also cancel a funded proposal, moving it to `CANCELLED`. Cancellation is allowed from `SELECTED` — permitted while the cycle is in either `SELECTION` or `IMPLEMENTATION` — and from `IN_IMPLEMENTATION` while the cycle is in `IMPLEMENTATION`. Cancellation is a compensating action: it resets the proposal's `awarded_cents` to zero, recomputes the owning category's `committed_cents`, and rolls that change up to restore the cycle's `total_committed_cents` and `uncommitted_cents`, returning the released money to the uncommitted pool; the proposal's `version` increments by one.

A `Reviewer` plans the delivery of an implementing proposal as a series of milestones. A milestone is filed against its `proposal_id` with a `title` and a planned window given by `scheduled_start` and `scheduled_end`, a closed interval that includes both endpoints, and it is created in `PLANNED` status with an empty `blocked_reason`. Creating a milestone is not itself gated by the cycle's phase or by the owning proposal's status — the only structural check at creation is the sibling-spacing rule below; the `IN_IMPLEMENTATION` requirement applies solely when starting a `PLANNED` milestone (see the `PLANNED`→`IN_PROGRESS` transition), and no milestone transition is gated by the cycle's phase. Milestones of the same proposal must not crowd one another: a new milestone's window must sit clear of every sibling milestone's window with at least a one-day buffer between them, meaning each milestone's start must fall strictly after the previous one's end with a gap of at least one day. A milestone whose schedule overlaps a sibling or violates that one-day buffer is rejected with `ERR_MILESTONE_OVERLAP` (HTTP 409).

The `Reviewer` drives each milestone through its states. Starting a `PLANNED` milestone moves it to `IN_PROGRESS`, permitted only when the owning proposal is `IN_IMPLEMENTATION`. Work in progress may hit a snag: moving an `IN_PROGRESS` milestone to `BLOCKED` records the supplied `blocked_reason`, and moving it back from `BLOCKED` to `IN_PROGRESS` clears that reason — a cyclic loop that may repeat. Finishing an `IN_PROGRESS` milestone moves it to `COMPLETED`. The requested destination travels in a `target_status` field, with `blocked_reason` accompanying a move into `BLOCKED`, and each transition increments the milestone's `version` by one. A requested transition that is not defined from the milestone's current state is rejected with `ERR_INVALID_STATE`.

Completing the last milestone completes the project. When a milestone reaches `COMPLETED`, the system checks whether every milestone of the owning proposal is now `COMPLETED`; if so — and provided the proposal has at least one milestone — it transitions the proposal from `IN_IMPLEMENTATION` to `COMPLETED` as a bubble-up side effect, incrementing the proposal's `version`. That project completion in turn increments the cycle's `completed_project_count` by one. The proposal's committed award is unchanged by completion, so the ledger totals do not move.

Throughout and after implementation, a `Reviewer` publishes report-backs to the public. Publishing a report-back is not gated by the cycle's phase or by the owning proposal's status; the proposal need only exist. A report-back is an append-only record filed against its `proposal_id` with a `period_label` naming the reporting period, a `narrative` in the default language, an optional `translations` map for other languages, and a `spent_cents` figure (zero or greater) for money spent in that period. Publishing stamps the report-back's `published_at` with the logical clock's current instant. As noted in §2.5, a report-back is immutable: it carries only `id` and `created_at`, has no `updated_at` or `version`, and is never modified once published.

## 4. Endpoint Definitions

Operations that create a new, distinct resource — a cycle, category, proposal, cost line item, ballot, ballot entry, selection run, milestone, or report-back — return `201 Created`. Operations that modify an existing resource, including state transitions and the phase advance, return `200 OK`. Read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/budget-cycles` | Create a budget cycle in DRAFT | BudgetAdmin |
| GET | `/budget-cycles/{id}` | Read a budget cycle including ledger fields | Anonymous, Resident, Reviewer, BudgetAdmin |
| POST | `/budget-cycles/{id}/phase-transitions` | Advance the cycle to the next phase | BudgetAdmin |
| POST | `/budget-cycles/{id}/categories` | Create a spending category | BudgetAdmin |
| GET | `/budget-cycles/{id}/categories` | List a cycle's categories | Anonymous, Resident, Reviewer, BudgetAdmin |
| GET | `/budget-cycles/{id}/proposals` | List a cycle's proposals | Anonymous, Resident, Reviewer, BudgetAdmin |
| GET | `/budget-cycles/{id}/selection-runs` | List a cycle's selection runs | Anonymous, Resident, Reviewer, BudgetAdmin |
| POST | `/budget-cycles/{id}/selection-runs` | Run funding selection over the ballot slate | BudgetAdmin |
| POST | `/residents` | Register a resident (UNVERIFIED) | Anonymous, BudgetAdmin |
| GET | `/residents/{id}` | Read a resident, including derived age | Resident, Reviewer, BudgetAdmin |
| POST | `/residents/{id}/verification-requests` | Submit or resubmit proof of residency | Anonymous, Resident |
| POST | `/residents/{id}/verification-decisions` | Approve or reject a pending verification | Reviewer |
| POST | `/budget-cycles/{id}/proposals` | Submit an idea as a DRAFT proposal | Resident |
| GET | `/proposals/{id}` | Read a proposal, including estimates and score | Anonymous, Resident, Reviewer, BudgetAdmin |
| GET | `/proposals` | Filtered proposal list | Anonymous, Resident, Reviewer, BudgetAdmin |
| POST | `/proposals/{id}/submit` | Submit a DRAFT proposal for review | Resident |
| POST | `/proposals/{id}/review-decisions` | Approve to development or reject | Reviewer |
| POST | `/proposals/{id}/cost-line-items` | Add a cost line item; recompute provisional estimate | Resident, Reviewer |
| GET | `/proposals/{id}/cost-line-items` | List a proposal's cost line items | Anonymous, Resident, Reviewer, BudgetAdmin |
| POST | `/proposals/{id}/finalize-cost` | Finalize costing; compute final estimate | Reviewer |
| POST | `/proposals/{id}/release-funding` | Release funding for a selected proposal | BudgetAdmin |
| POST | `/proposals/{id}/cancel-funding` | Cancel a funded proposal; restore budget | BudgetAdmin |
| GET | `/proposals/{id}/ballot-entries` | List ballot entries referencing this proposal | Anonymous, Resident, Reviewer, BudgetAdmin |
| GET | `/proposals/{id}/milestones` | List a proposal's milestones | Anonymous, Resident, Reviewer, BudgetAdmin |
| GET | `/proposals/{id}/report-backs` | List a proposal's report-backs | Anonymous, Resident, Reviewer, BudgetAdmin |
| POST | `/budget-cycles/{id}/ballots` | Open a DRAFT ballot for the acting resident | Resident |
| GET | `/ballots/{id}` | Read a ballot | Resident, Reviewer, BudgetAdmin |
| GET | `/ballots` | Filtered ballot list | Reviewer, BudgetAdmin |
| POST | `/ballots/{id}/entries` | Add a preference entry to a DRAFT ballot | Resident |
| POST | `/ballots/{id}/cast` | Cast the ballot; tally votes | Resident |
| POST | `/ballots/{id}/withdraw` | Withdraw a cast ballot; reverse its tally | Resident |
| GET | `/ballots/{id}/entries` | List a ballot's entries | Resident, Reviewer, BudgetAdmin |
| POST | `/proposals/{id}/milestones` | Create an implementation milestone | Reviewer |
| POST | `/milestones/{id}/transitions` | Advance a milestone's status | Reviewer |
| POST | `/proposals/{id}/report-backs` | Publish an append-only report-back | Reviewer |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | BudgetAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_BUDGET_CYCLE_NOT_FOUND` | 404 |
| `ERR_CATEGORY_NOT_FOUND` | 404 |
| `ERR_RESIDENT_NOT_FOUND` | 404 |
| `ERR_PROPOSAL_NOT_FOUND` | 404 |
| `ERR_BALLOT_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_WRONG_PHASE` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_INVALID_PHASE_TRANSITION` | 409 |
| `ERR_CATEGORY_CYCLE_MISMATCH` | 422 |
| `ERR_PROPOSAL_NOT_ON_BALLOT` | 409 |
| `ERR_NO_LINE_ITEMS` | 422 |
| `ERR_RESIDENT_NOT_ELIGIBLE` | 403 |
| `ERR_UNDER_AGE` | 422 |
| `ERR_DUPLICATE_BALLOT` | 409 |
| `ERR_DUPLICATE_RANK` | 422 |
| `ERR_PHASE_WINDOW_OVERLAP` | 422 |
| `ERR_MILESTONE_OVERLAP` | 409 |
| `ERR_ALLOCATION_CAP_EXCEEDED` | 422 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_STALE_CYCLE_VERSION` | 412 |

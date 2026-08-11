# Labor Relations Collective Bargaining API — Product Requirements Document

## 1. Introduction

The employer-side labor relations department operates at the intersection of contract administration, negotiation strategy, and regulatory compliance. Today the work is fragmented: contract clauses live in one document repository, bargaining notes in another, costing models in personal spreadsheets, and ratification tallies on paper. When a union files an information request, someone has to remember whether the governing agreement measures the response deadline in business days or calendar days; when a successor agreement is ratified, nobody is certain which side letters lapse, which clauses re-open for interpretation, or whether the year-one economic envelope still holds. The Labor Relations Collective Bargaining API exists to replace that patchwork with a single authoritative system of record for the entire employer-side bargaining cycle.

The platform covers the full arc of a contract from drafting to sunset: a clause repository with a formal interpretation workflow, a bargaining calendar with proposal exchange and counter-proposal chains, dual-variant costing of economic proposals with segregation of duties, ratification votes whose outcome triggers a depth-5 activation cascade, side letters and memoranda of agreement, past-practice documentation with paired legalistic and operational strength scores, union information requests with mode-aware deadline arithmetic, and expiration-planning tasks tied to a recomputed `expiration_date`. All time-dependent behavior is driven by a logical clock that the department administrator can advance, so overnight sweeps — expiry, overdue flagging, scheduled-session no-shows, side-letter lapse, past-practice abandonment, task misses, posture refresh — execute deterministically in a pinned order.

Throughout, the system enforces segregation of duties (the negotiator who computes a costing scenario may not review or lock it; the manager who drafts a side letter may not execute it), optimistic concurrency on the agreement's `version`, and side-based gating that distinguishes employer actions from union actions on every proposal transition.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting operator, and `X-User-Role` names the capacity in which they act. The recognized roles, spelled exactly as the server expects them, are `LRAdmin`, `LRManager`, `Negotiator`, `ChiefNegotiator`, `UnionRepresentative`, and `LegalCounsel`. A request whose headers are missing, blank, or carry an undeclared role is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Five of the six roles treat `X-User-ID` as an opaque operator identifier not tied to any persisted entity. For `LRAdmin`, `LRManager`, `Negotiator`, `ChiefNegotiator`, and `LegalCounsel`, the server may record the value on the resource being mutated — as `submitted_by_user_id` on a `Proposal`, `drafted_by_user_id` or `executed_by_user_id` on a `SideLetter`, `computed_by_user_id`, `reviewed_by_user_id`, or `locked_by_user_id` on a `CostingScenario`, `opened_by_user_id` on a `RatificationVote`, `asserted_by_user_id` on a `PastPractice`, or `assignee_user_id` on an `ExpirationTask` — but it never compares the identifier against any entity's `id`.

`UnionRepresentative` is the exception. When `X-User-Role` is `UnionRepresentative`, `X-User-ID` is the `id` of the acting `Union`; ownership checks on any resource that references a `Union` compare the resource's foreign-key field to `X-User-ID`. A `UnionRepresentative` filing an information request must pass a `union_id` equal to `X-User-ID`; tallying a ratification vote requires that `X-User-ID` equal the union of the vote's agreement; disputing a clause interpretation requires that `X-User-ID` equal the agreement's `union_id`; disputing a past practice requires that `X-User-ID` equal the practice's `union_id`. Any mismatch is rejected with `ERR_UNION_MISMATCH` (HTTP 403).

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by 20 random uppercase alphanumeric characters.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the server's logical clock (§2.12).
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

A request to an unknown path, or to a known path with an unsupported method, is answered in the same error envelope with `ERR_NOT_FOUND` (HTTP 404).

---

### 2.3. Pagination

List endpoints accept two optional query parameters. `limit` specifies the maximum number of items to return and defaults to 10, with a minimum of 1 and a maximum of 100. `offset` specifies the number of items to skip and defaults to 0. A `limit` outside the range 1 to 100, an `offset` below 0, or a non-integer value supplied for either, is rejected with `ERR_PAGINATION_INVALID` (HTTP 400).

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by insertion order. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset + limit` is less than `total_count`.

### 2.4. The Bargaining Calendar, Scheduling Buffers, and Interval Discipline

Bargaining sessions consume two scarce human resources — a mediator and an employer lead negotiator — and the system guards both with interval-conflict rules at scheduling time. Every session supplies `mediator_id` and `lead_negotiator_id`, both opaque operator identifiers. The mediator is governed by a half-open overlap rule: a new session conflicts with an existing one whenever they share `mediator_id`, both are in `SCHEDULED` or `IN_SESSION` status, and their `[start_at, end_at)` windows intersect. Adjacency is permitted — one session ending at exactly the moment another begins is not a conflict — and any such overlap is rejected with `ERR_MEDIATOR_CONFLICT` (HTTP 409). The lead negotiator is governed by a wider buffered rule: expand both candidate intervals by 45 minutes on each end, and if the two expanded intervals intersect for sessions that share `lead_negotiator_id` and are in `SCHEDULED` or `IN_SESSION` status — the expanded intervals are treated as closed, so touching expanded boundaries count as a conflict — the create is rejected with `ERR_NEGOTIATOR_BUFFER_CONFLICT` (HTTP 409).

Sessions themselves observe a scalar temporal rule. `start_at` must be strictly earlier than `end_at`, and the duration from `start_at` to `end_at` must not exceed 12 hours. A session that violates either bound is rejected with `ERR_INVALID_TIME_RANGE` (HTTP 422).

The system tracks, for each mediator, an aggregate of scheduled minutes — the sum of `(end_at - start_at)` over that mediator's sessions currently in `SCHEDULED` status. Scheduling a session increases the aggregate; cancelling a session, or having the clock sweep mark it `NO_SHOW`, releases exactly those minutes back.

### 2.5. Union Standing and Its Chilling Effect on Bargaining Activity

The standing of a `Union` constrains what bargaining activity may be initiated. A union begins in `ACTIVE` status; an `LRAdmin` may move it to `TRUSTEED` or `DECERTIFIED`, and a `TRUSTEED` union may be restored to `ACTIVE`. A union in `TRUSTEED` blocks two operations: tendering a proposal and scheduling a bargaining session. Both attempts are rejected with `ERR_UNION_TRUSTEED` (HTTP 409). A union in `DECERTIFIED` imposes a stricter freeze — drafting a proposal, tendering a proposal, scheduling a session, or filing an information request are all rejected with `ERR_UNION_DECERTIFIED` (HTTP 409).

Decertification is destructive in a controlled way. When a union transitions to `DECERTIFIED`, the system walks its agreements: every `CollectiveAgreement` of that union still in `DRAFT` becomes `ARCHIVED`, and every `BargainingSession` tied to one of those just-archived agreements — or belonging to this union — that is still `SCHEDULED` becomes `CANCELLED` with `cancel_reason` set to `UNION_DECERTIFIED`. The union's `version` increments, and each cascaded entity's `version` increments as well.

### 2.6. Agreement Posture and the Bargainable Predicate

A `CollectiveAgreement` carries, alongside its lifecycle `status`, a computed `posture` that captures how close the agreement is to expiration. Posture is recomputed by the clock sweep and after any transition that changes `status` or `expiration_date`; read paths may also recompute it lazily, but the stored value is refreshed by the sweep. The mapping is pinned. A `DRAFT` agreement has posture `NEGOTIATING`. An agreement in `REPLACED` or `ARCHIVED` has posture `CLOSED`. An agreement in `EXPIRED` has posture `UNCOVERED`. An agreement in `ACTIVE` or `EXTENDED` computes `days_left` as the whole calendar days between the current clock and `expiration_date`, then maps: more than 180 days left yields `OPEN`; more than 30 days left but no more than 180 yields `SUNSET`; 30 days or fewer yields `CRITICAL`.

Posture feeds back into a predicate used in two places — proposal tender and session scheduling. An agreement is **bargainable** when its `status` is `DRAFT`, `EXPIRED`, or `EXTENDED`, or when its `posture` is `SUNSET` or `CRITICAL`. Tendering a proposal or scheduling a session against a non-bargainable agreement is rejected with `ERR_AGREEMENT_NOT_BARGAINABLE` (HTTP 409).

### 2.7. Optimistic Concurrency Control on the Agreement

Two write operations — extending an agreement and locking a costing scenario — mutate state that legitimately supersedes a prior committed view, so both are guarded by optimistic concurrency against the parent `CollectiveAgreement`'s `version`.

Both operations require the request body to carry `expected_agreement_version`, populated with the agreement's `version` as the client last observed it. If the supplied value does not equal the agreement's current `version`, the request is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) and no state changes. Because locking a scenario legitimately supersedes the previously `LOCKED` scenario and bumps the agreement's `version`, and because extending legitimately re-extends an already `EXTENDED` agreement and also bumps `version`, a second lock or a second extend carrying the pre-mutation version is correctly identified as stale and is rejected deterministically. Endpoints not in this OCC list do not accept a version field.

### 2.8. Segregation of Duties Across Costing and Execution

The system enforces a strict segregation-of-duties discipline between the operator who produces an artifact and the operator who vouches for or executes it. On a `CostingScenario`, the `Negotiator` who runs the compute records their `X-User-ID` as `computed_by_user_id`; the subsequent review must be performed by a different `Negotiator`, and the subsequent lock by a `ChiefNegotiator` must also be performed by someone other than `computed_by_user_id`. On a `SideLetter`, the `LRManager` who drafts the letter records their `X-User-ID` as `drafted_by_user_id`; the `LegalCounsel` who executes the letter must be a different operator. Any attempt to review, lock, or execute with the same `X-User-ID` as the original producer is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

### 2.9. Monetary Precision, Weighted Scores, and Rounding Discipline

All monetary values are carried as integer cents. Per-proposal-per-year cost lines are rounded half-up to whole cents at the line level, before any summation across proposals or years; the contingency reserve is computed once, after the subtotal, and is itself rounded half-up to whole cents. The reserve is not part of its own base — this evaluation order is pinned and is not negotiable.

Past-practice strength scores are decimal numbers with 4 decimal places, rounded half-up. Date and time arithmetic — `due_at`, `due_date`, `abandon_effective_date`, the ballot window — operates at whole-second precision in UTC. Serialization follows the same discipline: every datetime-valued field carried on a resource other than `created_at` and `updated_at` — `effective_date`, `expiration_date`, `start_at`, `end_at`, `ballot_close_at`, `effective_start`, `effective_end`, `first_observed_date`, `last_observed_date`, `abandon_effective_date`, `received_at`, `due_at`, and `due_date` — is rendered as an ISO 8601 UTC timestamp at whole-second precision with no fractional digits (for example `2026-05-01T00:00:00Z`). The three-fractional-digit form is reserved for `created_at`, `updated_at`, and the meta `api_request_timestamp`.

### 2.10. Common Resource Properties

Every top-level resource — `Union`, `CollectiveAgreement`, `Clause`, `BargainingSession`, `Proposal`, `CostingScenario`, `RatificationVote`, `SideLetter`, `PastPractice`, `InformationRequest`, `ExpirationTask` — carries a standard set of system-managed fields:

- `id` (string): a server-generated UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation.
- `version` (integer): starts at 1 on creation and increments on every mutation, including mutations caused by cascading side effects from another entity's transition.

Any state transition or cross-entity cascade that touches an entity refreshes that entity's `updated_at` and increments its `version` — the same rule applies whether the trigger is a direct API call or a system sweep.

State-mutating endpoints that drive a resource's lifecycle — covering unions, sessions, proposals, costing scenarios, ratification votes, side letters, past practices, information requests, and expiration tasks — accept a `to_status` field naming the target state, plus any transition-specific supporting fields. The clause interpretation workflow instead dispatches on the `action` field described in §3.2, and the agreement's activate, extend, and archive operations, the proposal counter and void-implementation, the scenario lock, the vote tally, the information-request extend, and the logical clock advance each carry their own dedicated payload shape as narrated in §3. On every `to_status` endpoint, a value that is not a member of the resource's status set is rejected with `ERR_INVALID_REQUEST`, and a recognized status that the endpoint never sets is rejected with `ERR_INVALID_STATE`; the never-settable targets are: session `SCHEDULED` and `NO_SHOW`; proposal `DRAFT`, `COUNTERED`, `IMPLEMENTED`, and `VOID`; scenario `LOCKED` and `SUPERSEDED`; vote `SCHEDULED`, `RATIFIED`, and `REJECTED` (only `OPEN` is settable there); side letter `EXPIRED` and `SUPERSEDED`; past practice `ASSERTED` and `ABANDONED`; information request `RECEIVED`; and expiration task `PENDING` and `MISSED`. The operations narrated in §3 without a payload — activate, archive, and void-implementation — accept an optional JSON-object body, which is ignored.

### 2.11. Referenced-Identifier Resolution and Validation Ordering

For any endpoint whose path or body carries identifiers of related resources, the server resolves references in a left-to-right order — union, then agreement, then clause, then session, then proposal, then scenario, then vote, then letter, then practice, then request, then task — and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve. The identifier carried in the path is resolved immediately after authentication, before the request body is inspected.

Validation across the platform is priority-ordered so that earlier failures mask later ones. The authentication checks run first: header presence and role declaration (`ERR_UNAUTHENTICATED`), then role-permission for the endpoint (`ERR_UNAUTHORIZED_ROLE`), and then resolution of the path identifier (`ERR_NOT_FOUND`). Request shape comes next — the body must be a JSON object, required text fields must be non-blank strings, enum members must be valid, and numeric ranges must hold (`ERR_INVALID_REQUEST`, with `ERR_PAGINATION_INVALID` covering list-endpoint limit and offset violations); fields an endpoint does not recognize are ignored. Ownership, side, and per-action or per-transition role rules (`ERR_UNION_MISMATCH`, `ERR_WRONG_SIDE`, with clause-interpretation action gating and the per-transition role gates reported as `ERR_UNAUTHORIZED_ROLE`) are enforced as soon as the body fields and referenced entities they depend on have been parsed and resolved; remaining body-carried references are resolved in the order above (`ERR_NOT_FOUND`). State-machine validity comes after that (`ERR_INVALID_STATE`, `ERR_AGREEMENT_NOT_BARGAINABLE`, `ERR_SESSION_NOT_STARTED`, `ERR_BALLOT_STILL_OPEN`), then optimistic-concurrency (`ERR_STALE_AGREEMENT_VERSION`), then union-standing and segregation-of-duties checks (`ERR_UNION_TRUSTEED`, `ERR_UNION_DECERTIFIED`, `ERR_SOD_VIOLATION`), then scalar temporal rules (`ERR_INVALID_TIME_RANGE`, `ERR_INVALID_EFFECTIVE_RANGE`, `ERR_EXTENSION_NOT_FORWARD`), then interval conflicts (`ERR_MEDIATOR_CONFLICT`, `ERR_NEGOTIATOR_BUFFER_CONFLICT`, `ERR_SIDE_LETTER_OVERLAP`), then uniqueness and caps (`ERR_DUPLICATE_ARTICLE_REF`, `ERR_MAX_ROUNDS_EXCEEDED`, `ERR_EXTENSION_LIMIT_EXCEEDED`), then supporting-entity state gates (`ERR_RESOLUTION_REFERENCE_INVALID`, `ERR_COSTING_NOT_LOCKED`, `ERR_NO_LOCKED_SCENARIO`, `ERR_NO_ACCEPTED_PACKAGE`, `ERR_PRACTICE_NOT_VERIFIABLE`), and finally the economic-envelope check (`ERR_ENVELOPE_EXCEEDED`).

### 2.12. The Logical Clock and the Epoch Sweep

All time-dependent behavior — agreement expiry, overdue flagging, side-letter lapse, past-practice abandonment, task misses, posture refresh — is driven by a logical clock the server maintains. At startup, before any administrator call, the clock reads exactly 2026-05-01T00:00:00Z; it never falls back to wall-clock time.

Advancing the clock is an administrator-only capability invoked with a `to_iso8601` payload that runs an epoch sweep in a pinned order. Any well-formed `to_iso8601` is accepted — the new reading is not required to be later than the current one. The response reports the clock's new reading as `current_utc`, an ISO 8601 UTC timestamp at whole-second precision, alongside a `transitioned` object reporting how many entities each sweep step mutated: `agreements_expired`, `sessions_no_show`, `side_letters_expired`, `past_practices_abandoned`, `information_requests_overdue`, `expiration_tasks_missed`, and `agreements_posture_refreshed`. Step 1: agreements in `ACTIVE` or `EXTENDED` whose `expiration_date` is strictly earlier than the new clock become `EXPIRED`, with posture recomputed. Step 2: sessions still `SCHEDULED` whose `end_at` is strictly earlier than the new clock become `NO_SHOW`, with the mediator's scheduled-minutes released exactly as on cancellation. Step 3: side letters in `EXECUTED` whose `effective_end` is strictly earlier than the new clock become `EXPIRED`. Step 4: past practices in `NOTICE_GIVEN` whose `abandon_effective_date` has been reached or passed become `ABANDONED`, firing the clause ripple described in §3. Step 5: information requests past `due_at` have `is_overdue` set to true. Step 6: expiration tasks in `PENDING` or `IN_PROGRESS` whose `due_date` is strictly earlier than the new clock become `MISSED`. Step 7: posture is recomputed for any remaining `ACTIVE` or `EXTENDED` agreements. Every entity mutated by the sweep has its `version` incremented.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Union and Standing Up an Agreement

An `LRAdmin` onboards a union by supplying its `name` and a `union_code`; the code must be unique across all unions, and a duplicate is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The new union is born in `ACTIVE` status with `open_information_request_count` initialized to 0. From there the union's standing may evolve: `ACTIVE → TRUSTEED`, `TRUSTEED → ACTIVE`, or `ACTIVE → DECERTIFIED` and `TRUSTEED → DECERTIFIED` (both arms of the decertify cascade behave identically — DRAFT agreements of the union become `ARCHIVED`, and every still-`SCHEDULED` session belonging to the union becomes `CANCELLED` with `cancel_reason` of `UNION_DECERTIFIED`, per §2.5).

With a union in place, an `LRAdmin` stands up the successor agreement. The create call supplies `union_id`, a `title`, the `effective_date` and `expiration_date` (the expiration must be strictly later than the effective date, otherwise `ERR_INVALID_REQUEST`), the actual current bargaining-unit `headcount_baseline`, the projected `fte_projected` for the successor term, the `avg_loaded_wage_cents`, and the board-approved year-1 `costing_envelope_cents` (these four integer fields carry no range constraint). The optional `deadline_mode` selects whether linked information requests use `BUSINESS` or `CALENDAR` deadline arithmetic, defaults to `BUSINESS`, and any other value is rejected with `ERR_INVALID_REQUEST`. The union's standing is not checked at creation. The agreement is born `DRAFT` with posture `NEGOTIATING`, `envelope_committed_cents` at 0, and `extension_count` at 0.

Activation is the step that puts an agreement in force. An `LRAdmin` activates a `DRAFT` agreement provided its `expiration_date` is still in the future per the logical clock (otherwise `ERR_INVALID_STATE`) and its union is `ACTIVE` (a `TRUSTEED` union surfaces `ERR_UNION_TRUSTEED`; a `DECERTIFIED` union surfaces `ERR_UNION_DECERTIFIED`). Activation drives `DRAFT → ACTIVE`, recomputes posture, and — critically — any other agreement of the same union in `ACTIVE` or `EXTENDED` becomes `REPLACED` (posture `CLOSED`), which is how incumbent supersession is implemented. An agreement may also be `REPLACED` indirectly when a ratification vote on a successor activates that successor, per §3.6.

### 3.2. The Clause Repository and the Interpretation Workflow

Within an agreement, an `LRManager` builds the contract-term repository by creating clauses. Each clause carries `agreement_id`, an `article_ref` such as `12.1` (unique within its agreement — a duplicate is rejected with `ERR_DUPLICATE_ARTICLE_REF`), a `title`, the `body_text`, and an `is_economic` flag that defaults to false. A clause may not be created on an `ARCHIVED` or `REPLACED` agreement; the attempt is rejected with `ERR_INVALID_STATE`. A clause is born with `interpretation_status` of `UNINTERPRETED`, no `interpretation_text`, and no `resolved_by_ref`.

The interpretation workflow moves a clause through review, with the specific transition selected by the request's `action` field. An `LRManager` opens review (`UNINTERPRETED → UNDER_REVIEW`, action `OPEN_REVIEW`) and may close it back (`UNDER_REVIEW → UNINTERPRETED`, action `CLOSE_REVIEW`). A `LegalCounsel` records the ruling (`UNDER_REVIEW → INTERPRETED`, action `RECORD`), which requires the `interpretation_text` to be present — omitting it is rejected with `ERR_INVALID_REQUEST`. Either an `LRManager` or a `UnionRepresentative` may dispute an `INTERPRETED` clause (action `DISPUTE`), moving it to `DISPUTED`; a `UnionRepresentative` must match the agreement's `union_id` (else `ERR_UNION_MISMATCH`). A `LegalCounsel` resolves a `DISPUTED` clause (action `RESOLVE`) by citing exactly one of `side_letter_id` or `past_practice_id` — supplying both or neither is `ERR_INVALID_REQUEST` — and the cited side letter must be `EXECUTED` or the cited practice `VERIFIED`, otherwise `ERR_RESOLUTION_REFERENCE_INVALID` (HTTP 422). On a successful resolve, the clause becomes `RESOLVED` and `resolved_by_ref` is set to the cited id. The per-action role gating is fixed: `LRManager` performs `OPEN_REVIEW`, `CLOSE_REVIEW`, and `DISPUTE`; `LegalCounsel` performs `RECORD` and `RESOLVE`; `UnionRepresentative` performs `DISPUTE` only — any other action-per-role combination is rejected with `ERR_UNAUTHORIZED_ROLE`.

Two cyclic behaviors complete the picture. A `RESOLVED` clause may be disputed again (`RESOLVED → DISPUTE → DISPUTED`), and the re-dispute clears `resolved_by_ref`. And when an `EXECUTED` side letter on this clause is superseded — either because a ratified proposal referencing the clause is implemented with an overlapping effective window, per §3.6 — the clause cascades back to `UNDER_REVIEW` from any of `INTERPRETED`, `DISPUTED`, or `RESOLVED`, clearing `resolved_by_ref` when it referenced the superseded letter.

### 3.3. The Bargaining Calendar and Proposal Exchange

A `Negotiator` schedules a bargaining session against a bargainable agreement. The create supplies `agreement_id`, `mediator_id`, `lead_negotiator_id`, `location`, `start_at`, and `end_at`. The session is born `SCHEDULED`, and the mediator's scheduled-minutes aggregate increases by the session's duration in minutes. The session must satisfy the scalar temporal rule (strict ordering of `start_at` and `end_at`, duration at most 12 hours), the mediator half-open overlap rule, and the lead-negotiator 45-minute buffer rule from §2.4.

Once the logical clock reaches `start_at`, a `ChiefNegotiator` may move the session `SCHEDULED → IN_SESSION`; attempting this before `start_at` is rejected with `ERR_SESSION_NOT_STARTED`. From `IN_SESSION`, a `ChiefNegotiator` completes the session by supplying a `summary_note` — omitting it is `ERR_INVALID_REQUEST` — and the note is stored. Either a `Negotiator` or a `ChiefNegotiator` may cancel a `SCHEDULED` session by supplying a `cancel_reason`, which releases the session's minutes from the mediator's aggregate. If the clock sweeps past `end_at` while the session is still `SCHEDULED`, the sweep marks it `NO_SHOW` and releases the same minutes.

Proposals are the unit of bargaining. A `Negotiator` drafts an employer proposal, or a `UnionRepresentative` drafts a union proposal for an agreement of their own union — a cross-side draft is rejected with `ERR_WRONG_SIDE`, and drafting against an `ARCHIVED` or `REPLACED` agreement is rejected with `ERR_INVALID_STATE`. The draft carries `agreement_id`, `side` (`EMPLOYER` or `UNION`), `title`, `proposal_type` (`ECONOMIC` or `NON_ECONOMIC`), and optionally `clause_id`, `wage_increase_pct`, `affected_headcount`, `includes_benefits`, `one_time_cost_cents`, and `recurring_annual_cost_cents`. The optional `clause_id` is resolved for existence only; it is not required to belong to the same agreement. The `wage_increase_pct` is a decimal fraction in the range 0 to 0.25 inclusive and may be null; `one_time_cost_cents` and `recurring_annual_cost_cents` default to 0; `includes_benefits` defaults to false; `affected_headcount` may be null and drives the coverage-tier multiplier in §3.4. A new proposal is born `DRAFT` with `round_number` 1, `submitted_by_user_id` recorded from `X-User-ID`, and `session_id`, `supersedes_proposal_id`, `estimated_year1_cost_cents`, and `rejection_reason` all null.

Tendering a proposal is the act of formally placing it on the bargaining table. For an `EMPLOYER` proposal, a `ChiefNegotiator` tenders; for a `UNION` proposal, a `UnionRepresentative` whose `X-User-ID` equals the agreement's `union_id` tenders. Tendering is gated by several checks: the proposal must be `DRAFT`; the actor's side must match the proposal's `side` (otherwise `ERR_WRONG_SIDE`); the agreement must be bargainable per §2.6 (otherwise `ERR_AGREEMENT_NOT_BARGAINABLE`); and the union must be `ACTIVE` (otherwise `ERR_UNION_TRUSTEED` or `ERR_UNION_DECERTIFIED`). The tender may optionally carry a `session_id`; when present, the session's `agreement_id` must equal the proposal's and the session must be in `IN_SESSION` or `COMPLETED` — any other state is rejected with `ERR_INVALID_STATE`. On success, the proposal moves `DRAFT → TENDERED` and the supplied `session_id` is stored.

The receiving side then tables the proposal (`TENDERED → ON_TABLE`). For an `EMPLOYER` proposal, the receiver is a `UnionRepresentative`; for a `UNION` proposal, the receiver is a `ChiefNegotiator`. Tabling by the proposing side is rejected with `ERR_WRONG_SIDE`.

Once `ON_TABLE`, three resolutions and one counter are available. The receiving side may accept (`ON_TABLE → ACCEPTED`), reject (`ON_TABLE → REJECTED`, requiring a `reason` which is stored as `rejection_reason`), or counter (per §3.4's round mechanics); accept and reject, like tabling, are performed by the receiving side's designated role — a `UnionRepresentative` for an `EMPLOYER` proposal, a `ChiefNegotiator` for a `UNION` proposal. The proposing side may withdraw (`ON_TABLE → WITHDRAWN`), again through its designated role — a `ChiefNegotiator` for an `EMPLOYER` proposal, a `UnionRepresentative` for a `UNION` proposal; withdrawal by the receiving side is `ERR_WRONG_SIDE`.

Acceptance of an `ECONOMIC` proposal carries two additional gates. First, a `LOCKED` costing scenario for the agreement whose `proposal_ids` contains this proposal must exist (otherwise `ERR_COSTING_NOT_LOCKED`). Second, the agreement's `envelope_committed_cents` plus the proposal's `estimated_year1_cost_cents` must not exceed the agreement's `costing_envelope_cents` — equality is permitted; strictly exceeding is rejected with `ERR_ENVELOPE_EXCEEDED` (HTTP 422). Throughout, `envelope_committed_cents` is maintained as the sum of `estimated_year1_cost_cents` over the agreement's proposals in `ACCEPTED` or `IMPLEMENTED` status, with a null estimate contributing 0. On a successful accept, the agreement's `envelope_committed_cents` is recomputed to include this proposal and the agreement's `version` increments. Acceptance of a `NON_ECONOMIC` proposal skips both gates.

### 3.4. Counter-Proposals and Round Mechanics

When the receiving side wishes to counter rather than accept or reject, the counter operation consumes the `ON_TABLE` proposal and produces a new one. The counter is submitted by the receiving side (a `ChiefNegotiator` for a `UNION` proposal, a `UnionRepresentative` for an `EMPLOYER` proposal), and is gated by `round_number` — a proposal already at round 12 cannot be countered, and the attempt is rejected with `ERR_MAX_ROUNDS_EXCEEDED`. The original proposal becomes `COUNTERED`, and a new proposal is created in the same request with `side` flipped, `status` `ON_TABLE`, `round_number` equal to the original's `round_number` plus 1, `supersedes_proposal_id` set to the original's `id`, `agreement_id`, `clause_id`, and `proposal_type` carried over, and `submitted_by_user_id` recording the countering operator. The new proposal's payload supplies its own `title` and optionally `wage_increase_pct`, `affected_headcount`, `includes_benefits`, `one_time_cost_cents`, and `recurring_annual_cost_cents`. The create returns 201 with the new proposal.

### 3.5. Costing Scenarios: Compute, Review, Lock

A `Negotiator` builds a costing scenario by naming it, selecting a `scenario_mode` of `PROVISIONAL` or `FINAL`, fixing the `term_years` (an integer between 1 and 5 inclusive), and listing `proposal_ids` — the economic proposals to model; the list may be empty, and the ids are not resolved until compute. A scenario may not be created on an `ARCHIVED` or `REPLACED` agreement (`ERR_INVALID_STATE`). The scenario is born `DRAFT` with `computed_by_user_id`, `reviewed_by_user_id`, `locked_by_user_id`, `year_breakdown_cents`, `subtotal_cents`, `reserve_cents`, and `total_cost_cents` all null.

Compute is the heart of the costing pipeline. A `Negotiator` triggers it by transitioning the scenario to `COMPUTED`; the same transition is reused for a re-compute after rework, so the from-state may be `DRAFT` or `REVIEWED`. Compute first validates that every id in `proposal_ids` resolves to a proposal whose `agreement_id` equals the scenario's, whose `proposal_type` is `ECONOMIC`, and whose status is `ON_TABLE` or `ACCEPTED` — any miss is rejected with `ERR_INVALID_REQUEST`.

The calculation then proceeds as follows. The **basis** is the agreement's `fte_projected` when the scenario mode is `PROVISIONAL`, or the agreement's `headcount_baseline` when the mode is `FINAL`. The base payroll is the basis multiplied by `avg_loaded_wage_cents` multiplied by 2080 hours per year. For each listed proposal, the year-1 wage line starts as the base payroll multiplied by the proposal's `wage_increase_pct` (0 when the percentage is null), then is capped at 15 percent of the base payroll — that is, if the uncapped wage line exceeds the base payroll times 0.15, the wage line is set to the base payroll times 0.15 — before any benefits loading. If `includes_benefits` is true, the capped wage line is multiplied by 1.32. The coverage ratio `r` is the proposal's `affected_headcount` (or 0 when null) divided by the basis; the tiered multiplier is 1.10 when `r` is at least 0.80, 1.05 when `r` is at least 0.50 but less than 0.80, and 1.00 when `r` is less than 0.50. The wage line is multiplied by the tier multiplier and rounded half-up to whole cents. The one-time share depends on mode: under `PROVISIONAL` it is the proposal's `one_time_cost_cents` divided by `term_years`, rounded half-up to whole cents; under `FINAL` it is the full `one_time_cost_cents` charged to year 1 and 0 in every later year. The year-1 line for the proposal is the wage line plus `recurring_annual_cost_cents` plus the one-time share. For each later year `k` from 2 to `term_years`, the wage line is the year-1 wage line multiplied by (1 plus `wage_increase_pct`, or 1 plus 0 when null) raised to the power of `k` minus 1 — that is, the year-`k` wage is computed from the year-1 base, not recursively from the prior year — and the result is rounded half-up to whole cents; the year-`k` line is that wage plus `recurring_annual_cost_cents` plus the one-time share for that year (under `PROVISIONAL`, the same amortized share as year 1; under `FINAL`, 0). Each proposal's `estimated_year1_cost_cents` is overwritten with its year-1 line under this scenario's variant; the overwrite is silent — it does not refresh the proposal's `updated_at` or increment its `version`.

The scenario's `year_breakdown_cents` is an array of length `term_years`, where each entry is the sum across listed proposals of that year's line. The `subtotal_cents` is the sum of `year_breakdown_cents`. The `reserve_cents` is 5 percent of `subtotal_cents`, rounded half-up to whole cents — and the reserve is computed after the subtotal, never as part of its own base. The `total_cost_cents` is `subtotal_cents` plus `reserve_cents`. The compute records the acting `X-User-ID` as `computed_by_user_id` and increments the scenario's `version`.

Review enforces segregation of duties. A `Negotiator` transitions the scenario from `COMPUTED` to `REVIEWED`, but the acting `X-User-ID` must differ from `computed_by_user_id` — otherwise `ERR_SOD_VIOLATION`. The reviewer is recorded as `reviewed_by_user_id`. A scenario in `REVIEWED` may be sent back to `DRAFT` by a `Negotiator` (the rework loop); totals are retained but stale until the next compute.

Lock is the step that makes a scenario authoritative. A `ChiefNegotiator` locks a `REVIEWED` scenario by supplying `expected_agreement_version`; if that value does not match the agreement's current `version`, the lock is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412) per §2.7. The locker's `X-User-ID` must differ from `computed_by_user_id` (otherwise `ERR_SOD_VIOLATION`). On a successful lock, the scenario becomes `LOCKED` and any other scenario of the same agreement currently `LOCKED` becomes `SUPERSEDED` — the lock-supersede rule — while the agreement's `version` increments and `locked_by_user_id` is recorded.

### 3.6. Ratification and the Depth-5 Activation Cascade

Once a successor agreement's package is settled, a `ChiefNegotiator` creates a ratification vote by supplying `agreement_id`, the `eligible_voter_count` (at least 1), and the `ballot_close_at` — which is not validated against the clock at creation. A vote may not be created on an `ARCHIVED` or `REPLACED` agreement (`ERR_INVALID_STATE`). The vote is born `SCHEDULED`.

Opening the vote is a gated transition. The vote must be `SCHEDULED`; a `LOCKED` costing scenario must exist for the vote's agreement (otherwise `ERR_NO_LOCKED_SCENARIO`); at least one proposal of that agreement must be `ACCEPTED` (otherwise `ERR_NO_ACCEPTED_PACKAGE`, which is checked only after the locked-scenario gate passes); and `ballot_close_at` must still be in the future per the logical clock (otherwise `ERR_INVALID_STATE`) — the ballot-window check runs before the locked-scenario and accepted-package gates. On success the vote moves `SCHEDULED → OPEN` and `opened_by_user_id` is recorded.

Tallying is performed by a `UnionRepresentative` whose `X-User-ID` equals the agreement's `union_id` (otherwise `ERR_UNION_MISMATCH`). The tally submits `votes_for` and `votes_against`; a negative count is rejected with `ERR_INVALID_REQUEST`. It is rejected with `ERR_BALLOT_STILL_OPEN` if the logical clock has not yet reached `ballot_close_at`. The system then computes the outcome: `votes_cast` is `votes_for` plus `votes_against`; `quorum_met` is true when `votes_cast` is at least half of `eligible_voter_count` rounded up — exactly half is sufficient; `approved` is true when twice `votes_for` is strictly greater than `votes_cast` — an exact tie fails. When both quorum and approval hold, the vote becomes `RATIFIED`; otherwise it becomes `REJECTED`. Either way, `votes_for`, `votes_against`, `votes_cast`, and `quorum_met` are stored on the vote.

A `RATIFIED` outcome fires the depth-5 activation cascade. Link 1: the agreement moves `DRAFT → ACTIVE` and posture is recomputed. Link 2: the incumbent agreement of the same union in `ACTIVE` or `EXTENDED` becomes `REPLACED` (posture `CLOSED`) — this is the incumbent-supersession rule, applied here by cascade rather than by direct activation. Link 3: every `ACCEPTED` proposal of the ratified agreement becomes `IMPLEMENTED`, and the agreement's `envelope_committed_cents` is recomputed (the implemented proposals remain in the committed envelope). Link 4: every `EXECUTED` side letter whose `clause_id` equals an implemented proposal's `clause_id` and whose `[effective_start, effective_end]` closed interval overlaps the agreement's `[effective_date, expiration_date]` closed interval becomes `SUPERSEDED`. Link 5: each such supersession re-triggers the clause cascade — the affected clause moves from `INTERPRETED`, `DISPUTED`, or `RESOLVED` back to `UNDER_REVIEW`. The vote's `retro_payout_cents` is computed per §3.7.

A `REJECTED` outcome fires the compensation revert instead: every `ACCEPTED` proposal of the agreement reverts to `ON_TABLE`, `envelope_committed_cents` is recomputed (the accepts roll back), and `retro_payout_cents` is set to 0. The envelope-conservation invariant — that any matched accept-and-revert pair returns `envelope_committed_cents` exactly to its prior value — is preserved across both directions.

### 3.7. Retroactive Payout at Ratification

When a vote ratifies, the system computes a retroactive payout to cover the period between the agreement's `effective_date` and the tally date. The retro period count is the number of whole 30-day periods between the agreement's `effective_date` and the tally date — computed as the floor of the day difference divided by 30, and 0 when the `effective_date` is not in the past. For each proposal of the ratified agreement that becomes `IMPLEMENTED` and is `ECONOMIC`, the monthly line is the proposal's `recurring_annual_cost_cents` divided by 12, rounded half-up to whole cents — this monthly rounding is pinned and happens before any multiplication. The payout for that proposal is the monthly line multiplied by the retro period count. The vote's `retro_payout_cents` is the sum of these per-proposal payouts. When the agreement's `effective_date` is not in the past, `retro_payout_cents` is 0.

### 3.8. Implementation Voids and Envelope Conservation

An `IMPLEMENTED` proposal may later be found to have been adopted in error. An `LRAdmin` voids the implementation; the proposal moves `IMPLEMENTED → VOID`, the agreement's `envelope_committed_cents` is recomputed with this proposal removed, and both the proposal's and the agreement's `version` increment. Combined with the acceptance rule in §3.3 and the rejection-revert rule in §3.6, this gives the platform a strict conservation invariant on the envelope: after any matched accept-and-revert or implement-and-void pair, `envelope_committed_cents` returns exactly to its prior value.

### 3.9. Side Letters and Memoranda

An `LRManager` drafts a side letter, memorandum of agreement, or memorandum of understanding against a specific clause of an agreement. The create supplies `agreement_id`, `clause_id`, `letter_type` (one of `SIDE_LETTER`, `MOA`, `MOU`), a `title`, and the effective window `effective_start` and `effective_end`. The clause must belong to the named agreement — a mismatch is rejected with `ERR_INVALID_REQUEST` — and a letter may not be drafted on an `ARCHIVED` or `REPLACED` agreement (`ERR_INVALID_STATE`). The window is a closed interval — `effective_end` must be on or after `effective_start`, otherwise `ERR_INVALID_EFFECTIVE_RANGE` (HTTP 422). The letter is born `DRAFT` with `drafted_by_user_id` recorded.

From `DRAFT`, an `LRManager` submits the letter for legal review (`DRAFT → PENDING_LEGAL`). A `LegalCounsel` may return it for rework (`PENDING_LEGAL → DRAFT`) or execute it (`PENDING_LEGAL → EXECUTED`). Execution enforces three checks in addition to the state gate: the executor's `X-User-ID` must differ from `drafted_by_user_id` (otherwise `ERR_SOD_VIOLATION`); the letter's agreement must be `ACTIVE` or `EXTENDED` (otherwise `ERR_INVALID_STATE`); and the closed-interval overlap rule — no other `EXECUTED` letter on the same `clause_id` may have an effective window where the candidate's `effective_start` is on or before the other's `effective_end` and the other's `effective_start` is on or before the candidate's `effective_end`, with touching boundaries counted as a conflict — otherwise `ERR_SIDE_LETTER_OVERLAP`. On success, `executed_by_user_id` is recorded.

Two terminal paths exist. When the clock sweeps past `effective_end`, an `EXECUTED` letter becomes `EXPIRED`. And when a proposal referencing the letter's `clause_id` becomes `IMPLEMENTED` with an effective window overlapping the agreement's window, the `EXECUTED` letter becomes `SUPERSEDED`, firing the clause cascade from §3.2.

### 3.10. Past-Practice Documentation and Strength Scoring

A past practice is asserted by an `LRManager` (for any union) or by a `UnionRepresentative` for their own union. The create supplies `union_id`, optionally `clause_id` (resolved for existence only), a `title`, a `description`, `first_observed_date`, `last_observed_date` (which must be on or after `first_observed_date`, otherwise `ERR_INVALID_REQUEST`), and `occurrence_count` (at least 1). The practice is born `ASSERTED`, with both `strength_legalistic` and `strength_operational` null, and `asserted_by_user_id` recorded.

Documentation is the step that computes strength. An `LRManager` moves the practice `ASSERTED → DOCUMENTED`, and the same transition applies from `DISPUTED` to support a re-documentation cycle. On each documentation, both strength variants are computed against the current clock.

The recency in years is the day count between `last_observed_date` and the current clock date, divided by 365. The frequency is `occurrence_count` divided by 10, capped at 1.0. The **LEGALISTIC** variant takes the recency component as 0.85 raised to the power of the floor of the recency in years, then computes `strength_legalistic` as 0.6 times the recency component plus 0.4 times the frequency, rounded half-up to 4 decimal places. The **OPERATIONAL** variant uses a step decay — the recency component is 1.0 when the recency is less than 5 years, 0.5 otherwise — and computes `strength_operational` as 0.4 times the recency component plus 0.6 times the frequency, also rounded half-up to 4 decimal places. The LEGALISTIC variant is the verification gate; the OPERATIONAL variant is reported on reads for operational-leverage assessments.

Verification is gated on the legalistic score. A `LegalCounsel` moves a `DOCUMENTED` practice to `VERIFIED` only when `occurrence_count` is at least 3 and `strength_legalistic` is at least 0.5000 — otherwise `ERR_PRACTICE_NOT_VERIFIABLE` (HTTP 422). Disputing a documented practice (`DOCUMENTED → DISPUTED`) is open to an `LRManager` or to a `UnionRepresentative` whose `X-User-ID` equals the practice's `union_id` (otherwise `ERR_UNION_MISMATCH`).

Abandonment begins with notice. An `LRManager` moves a `VERIFIED` practice to `NOTICE_GIVEN`, which sets `abandon_effective_date` to the current clock plus 30 days. The notice may be rescinded before that instant — an `LRManager` moves `NOTICE_GIVEN → VERIFIED` provided the clock is still strictly before `abandon_effective_date` (otherwise `ERR_INVALID_STATE`) — which clears `abandon_effective_date`. When the clock reaches `abandon_effective_date`, the sweep moves the practice to `ABANDONED` and fires the cross-entity ripple: every clause whose `resolved_by_ref` equals this practice's `id` moves from `RESOLVED` back to `DISPUTED`, since its resolution support has been abandoned; the clause's `resolved_by_ref` is left intact.

### 3.11. Union Information Requests and Deadline Arithmetic

A `UnionRepresentative` files an information request by supplying `union_id` (which must equal `X-User-ID`, otherwise `ERR_UNION_MISMATCH`), an optional `agreement_id`, a `subject`, and the `received_at` instant; when `agreement_id` is present and names an `ARCHIVED` or `REPLACED` agreement, the filing is rejected with `ERR_INVALID_STATE`. The request is born `RECEIVED`, the union's `open_information_request_count` increments, and the union's `version` increments.

The `due_at` deadline is computed at create. The mode is the linked agreement's `deadline_mode` when `agreement_id` is present, and `BUSINESS` otherwise. Under `BUSINESS`, starting the day after `received_at`, the deadline advances 10 days counting only Monday through Friday; `due_at` is that date at 17:00:00Z. Under `CALENDAR`, the deadline advances 10 calendar days from the received date; `due_at` is that date at 17:00:00Z. The `is_overdue` flag becomes true when the clock is strictly later than `due_at` while the request is in `RECEIVED`, `ACKNOWLEDGED`, `IN_PROGRESS`, or `OBJECTED` — at the exact `due_at` instant the request is not yet overdue.

The response workflow is a managed pipeline. An `LRManager` acknowledges (`RECEIVED → ACKNOWLEDGED`) and starts work (`ACKNOWLEDGED → IN_PROGRESS`). A `LegalCounsel` may object (`IN_PROGRESS → OBJECTED`), supplying `objection_basis`, which is stored; if the objection is later withdrawn, a `LegalCounsel` moves the request back (`OBJECTED → IN_PROGRESS`) with the `objection_basis` retained for audit. An `LRManager` completes the response with `FULFILLED` (from `IN_PROGRESS` or from `PARTIALLY_FULFILLED`), or records a partial response with `PARTIALLY_FULFILLED` (from `IN_PROGRESS`); both require a `response_note` (otherwise `ERR_INVALID_REQUEST`). The union's `open_information_request_count` is maintained as the number of its requests in `RECEIVED`, `ACKNOWLEDGED`, `IN_PROGRESS`, or `OBJECTED`: each terminal or partial fulfillment — that is, every transition into `FULFILLED` or `PARTIALLY_FULFILLED` — recomputes the count and bumps the union's `version`, so a `PARTIALLY_FULFILLED → FULFILLED` move leaves the count unchanged.

An `LRManager` may extend the deadline by supplying `extra_business_days` (at least 1, otherwise `ERR_INVALID_REQUEST`); the extension is not gated on the request's status. The extension count is capped: a request may be extended at most twice, and each grant may add at most 5 days — violating either cap is rejected with `ERR_EXTENSION_LIMIT_EXCEEDED`. The recompute follows the request's mode: under `BUSINESS`, `due_at` advances by the granted number of business days, skipping Saturdays and Sundays, with the time held at 17:00:00Z; under `CALENDAR`, `due_at` advances by the granted number of calendar days, with the time likewise held at 17:00:00Z. Each granted extension increments `extension_count` and recomputes `is_overdue` against the new `due_at`.

### 3.12. Expiration Planning and the Extend Recompute Cascade

Expiration-planning tasks tie operational follow-ups to the agreement's `expiration_date`. An `LRManager` or `Negotiator` creates a task against an agreement that is `ACTIVE`, `EXPIRED`, or `EXTENDED` — task creation against a `DRAFT`, `REPLACED`, or `ARCHIVED` agreement is rejected with `ERR_INVALID_STATE`. The create supplies `agreement_id`, `title`, `task_type` (one of `NOTICE_DEADLINE`, `DATA_PREP`, `SUNSET_COMMUNICATION`, `STRIKE_CONTINGENCY`, `BUDGET_REOPENER`), `due_offset_days` (negative for before expiration), and `assignee_user_id`. The task is born `PENDING`, and its `due_date` is the agreement's `expiration_date` plus `due_offset_days` calendar days (the offset may be negative, zero, or positive; the computation uses the time-of-day of `expiration_date`).

Tasks follow a small workflow. From `PENDING` or `IN_PROGRESS`, an `LRManager` or `Negotiator` may mark the task `IN_PROGRESS` (only from `PENDING`) or `DONE`. A task may also reach `DONE` from `MISSED`. The `completed_late` flag is set to true when `DONE` is reached either after `due_date` per the current clock, or from a prior status of `MISSED`; in the `MISSED → DONE` case the flag is forced true regardless of the clock. Independently, the clock sweep moves any `PENDING` or `IN_PROGRESS` task whose `due_date` is strictly past to `MISSED`.

Extending the agreement is the cascade that ties expiration planning together. A `ChiefNegotiator` extends an agreement by supplying `new_expiration_date` and `expected_agreement_version`. The agreement must be in `ACTIVE`, `EXPIRED`, or `EXTENDED`; the new expiration must be strictly later than the current one (otherwise `ERR_EXTENSION_NOT_FORWARD`); and `expected_agreement_version` must equal the agreement's current `version` (otherwise `ERR_STALE_AGREEMENT_VERSION` per §2.7). On success, the agreement becomes `EXTENDED`, `expiration_date` is updated, `extension_count` increments, posture is recomputed, and the cascade fires: every expiration task of this agreement in `PENDING` or `IN_PROGRESS` recomputes its `due_date` from the new `expiration_date` plus its `due_offset_days`, and any task whose recomputed `due_date` is strictly earlier than the current clock becomes `MISSED` in the same request. The agreement's `version` increments, as does the `version` of each task the cascade touches.

Finally, an `LRAdmin` may archive an agreement in `EXPIRED` or `REPLACED`, moving it to `ARCHIVED` with posture `CLOSED` and incrementing its `version`.

## 4. Endpoint Definitions

All endpoints return the standard envelope from §2.2. Endpoints that create a new resource respond with HTTP 201; endpoints that modify an existing resource (state transitions, counters, extensions, tallies) respond with HTTP 200. List endpoints respond with HTTP 200 and honor the pagination contract from §2.3. List endpoints filter by exact match, combined conjunctively, on the following query parameters: unions — `status`; agreements — `union_id`, `status`, `posture`; clauses — `agreement_id`, `interpretation_status`; sessions — `agreement_id`, `mediator_id`, `status`; proposals — `agreement_id`, `clause_id`, `supersedes_proposal_id`, `side`, `status`; costing scenarios — `agreement_id`, `status`, `scenario_mode`; ratification votes — `agreement_id`, `status`; side letters — `agreement_id`, `clause_id`, `status`; past practices — `union_id`, `clause_id`, `status`; information requests — `union_id`, `agreement_id`, `status`, and `is_overdue` (only the value `true`, case-insensitive, selects overdue requests); expiration tasks — `agreement_id`, `status`, `task_type`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /labor-relations/unions | Create a union | LRAdmin |
| GET | /labor-relations/unions | List unions | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/unions/{id} | Get a union | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/unions/{id}/state | Transition union status with decertify cascade | LRAdmin |
| POST | /labor-relations/agreements | Create a collective agreement | LRAdmin |
| GET | /labor-relations/agreements | List agreements with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/agreements/{id} | Get an agreement | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/agreements/{id}/activate | Activate a DRAFT agreement; supersedes incumbent | LRAdmin |
| POST | /labor-relations/agreements/{id}/extend | Extend expiration; OCC-guarded; recomputes task due dates | ChiefNegotiator |
| POST | /labor-relations/agreements/{id}/archive | Archive an EXPIRED or REPLACED agreement | LRAdmin |
| POST | /labor-relations/clauses | Create a clause | LRManager |
| GET | /labor-relations/clauses | List clauses with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/clauses/{id} | Get a clause | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/clauses/{id}/interpretation | Drive the interpretation workflow with per-action role gating | LRManager, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/sessions | Schedule a bargaining session | Negotiator |
| GET | /labor-relations/sessions | List sessions with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/sessions/{id} | Get a session | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/sessions/{id}/state | Transition session | Negotiator, ChiefNegotiator |
| POST | /labor-relations/proposals | Draft a proposal | Negotiator, UnionRepresentative |
| GET | /labor-relations/proposals | List proposals with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/proposals/{id} | Get a proposal | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/proposals/{id}/state | Transition proposal with side gating and envelope checks | Negotiator, ChiefNegotiator, UnionRepresentative |
| POST | /labor-relations/proposals/{id}/counter | Counter an ON_TABLE proposal | ChiefNegotiator, UnionRepresentative |
| POST | /labor-relations/proposals/{id}/void-implementation | Void an IMPLEMENTED proposal | LRAdmin |
| POST | /labor-relations/costing-scenarios | Create a costing scenario | Negotiator |
| GET | /labor-relations/costing-scenarios | List costing scenarios with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/costing-scenarios/{id} | Get a costing scenario | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/costing-scenarios/{id}/state | Transition scenario (compute / review / rework) | Negotiator |
| POST | /labor-relations/costing-scenarios/{id}/lock | Lock a REVIEWED scenario; supersedes prior lock; OCC on the agreement | ChiefNegotiator |
| POST | /labor-relations/ratification-votes | Create a ratification vote | ChiefNegotiator |
| GET | /labor-relations/ratification-votes | List ratification votes with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/ratification-votes/{id} | Get a ratification vote | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/ratification-votes/{id}/state | Open a SCHEDULED vote | ChiefNegotiator |
| POST | /labor-relations/ratification-votes/{id}/tally | Submit union ballot tally | UnionRepresentative |
| POST | /labor-relations/side-letters | Draft a side letter / MOA / MOU | LRManager |
| GET | /labor-relations/side-letters | List side letters with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/side-letters/{id} | Get a side letter | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/side-letters/{id}/state | Transition side letter | LRManager, LegalCounsel |
| POST | /labor-relations/past-practices | Assert a past practice | LRManager, UnionRepresentative |
| GET | /labor-relations/past-practices | List past practices with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/past-practices/{id} | Get a past practice | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/past-practices/{id}/state | Transition past practice | LRManager, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/information-requests | File a union information request | UnionRepresentative |
| GET | /labor-relations/information-requests | List information requests with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/information-requests/{id} | Get an information request | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/information-requests/{id}/state | Transition information request | LRManager, LegalCounsel |
| POST | /labor-relations/information-requests/{id}/extend | Extend the response deadline | LRManager |
| POST | /labor-relations/expiration-tasks | Create an expiration-planning task | LRManager, Negotiator |
| GET | /labor-relations/expiration-tasks | List expiration tasks with FK filters | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| GET | /labor-relations/expiration-tasks/{id} | Get an expiration task | LRAdmin, LRManager, Negotiator, ChiefNegotiator, LegalCounsel, UnionRepresentative |
| POST | /labor-relations/expiration-tasks/{id}/state | Transition expiration task | LRManager, Negotiator |
| POST | /_clock/set_current_utc | Set the server's logical clock; runs the epoch sweep | LRAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_UNION_MISMATCH | 403 |
| ERR_WRONG_SIDE | 403 |
| ERR_INVALID_REQUEST | 400 |
| ERR_PAGINATION_INVALID | 400 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_AGREEMENT_NOT_BARGAINABLE | 409 |
| ERR_SESSION_NOT_STARTED | 409 |
| ERR_BALLOT_STILL_OPEN | 409 |
| ERR_STALE_AGREEMENT_VERSION | 412 |
| ERR_UNION_TRUSTEED | 409 |
| ERR_UNION_DECERTIFIED | 409 |
| ERR_SOD_VIOLATION | 403 |
| ERR_INVALID_TIME_RANGE | 422 |
| ERR_MEDIATOR_CONFLICT | 409 |
| ERR_NEGOTIATOR_BUFFER_CONFLICT | 409 |
| ERR_INVALID_EFFECTIVE_RANGE | 422 |
| ERR_SIDE_LETTER_OVERLAP | 409 |
| ERR_DUPLICATE_ARTICLE_REF | 409 |
| ERR_MAX_ROUNDS_EXCEEDED | 409 |
| ERR_EXTENSION_LIMIT_EXCEEDED | 409 |
| ERR_EXTENSION_NOT_FORWARD | 422 |
| ERR_COSTING_NOT_LOCKED | 409 |
| ERR_ENVELOPE_EXCEEDED | 422 |
| ERR_NO_LOCKED_SCENARIO | 409 |
| ERR_NO_ACCEPTED_PACKAGE | 409 |
| ERR_RESOLUTION_REFERENCE_INVALID | 422 |
| ERR_PRACTICE_NOT_VERIFIABLE | 422 |

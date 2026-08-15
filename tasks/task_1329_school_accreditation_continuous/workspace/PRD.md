# School Accreditation API — Product Requirements Document

## 1. Introduction

Accrediting bodies such as Cognia run a long-cycle, evidence-driven process: a member school system prepares a self-study against published standards, administers stakeholder surveys, hosts a visiting peer-review team, receives findings and required actions, and then lives out a multi-year accreditation term punctuated by interim reports until renewal. Each stage carries its own gatekeepers, deadlines, quorum rules, and fees, and a failure at any point — an under-quorum evidence base, an under-subscribed parent survey, a lapsed required action — has direct consequences for the institution's accredited standing.

This document specifies the School Accreditation API, which digitizes that end-to-end lifecycle. The API serves the accrediting body's staff (`AccreditationOfficer`), its decision-making commission (`AccreditationCommission`), member school leadership (`SchoolLeader`), peer reviewers (`Reviewer`), the body's finance office (`SystemBursar`), and anonymous survey respondents. It tracks institution systems and their campuses, the standards framework, accreditation terms from preparation through renewal, self-study ratings and evidence, survey windows and anonymous responses, improvement goals and progress indicators, visit events with their teams and findings, required action items, interim reports, and the fee schedule, invoices, and payments that fund the cycle.

Because accreditation decisions must withstand appeals and audits, the system is deliberately strict about ordering and provenance: state transitions are gated on explicit preconditions, sensitive operations carry optimistic-concurrency tokens, reviewers are barred from judging their own submissions, and every mutation is versioned. The sections that follow define the global contracts (§2), the business workflows (§3), the endpoint surface (§4), and the error catalogue (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles, spelled exactly as follows: `AccreditationOfficer`, `AccreditationCommission`, `SchoolLeader`, `Reviewer`, `SystemBursar`, and `Anonymous`.

A request that arrives without these headers, or whose role value is not one of the declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403). Authorization is checked only after authentication succeeds, so a request that is simultaneously unauthenticated and unauthorized always surfaces `ERR_UNAUTHENTICATED`.

The identity carried by `X-User-ID` differs by role. When `X-User-Role` is `Reviewer`, `X-User-ID` is the `id` of the acting `Reviewer` entity; ownership-style checks that reference a reviewer — such as confirming that the acting reviewer is the visit's `lead_reviewer_id`, or recording `verified_by_user_id` on a verified action item — compare the relevant field against `X-User-ID`. When `X-User-Role` is `AccreditationOfficer`, `AccreditationCommission`, `SchoolLeader`, `SystemBursar`, or `Anonymous`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `submitted_by_user_id` on an `EvidenceItem` when a `SchoolLeader` submits evidence) but never compares it to any entity's `id`. Segregation-of-duties checks compare these opaque identifiers against each other — an officer whose `X-User-ID` equals an evidence item's `submitted_by_user_id` is treated as the same individual.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

List responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most primary resources — `InstitutionSystem`, `Campus`, `AccreditationTerm`, `SelfStudyRating`, `EvidenceItem`, `SurveyInstrument`, `SurveyWindow`, `ImprovementGoal`, `ProgressIndicator`, `VisitEvent`, `Reviewer`, `VisitAssignment`, `VisitFinding`, `RequiredActionItem`, `InterimReport`, and `Invoice` — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits indicating the last modification; refreshed on every mutation.
- `version` (integer): a system-managed integer that starts at its initial value on creation and increments by exactly 1 on every modification, including modifications driven by side effects originating from other resources.

Three resource types are intentionally lighter. `Standard`, `SurveyResponse`, `Payment`, and `FeeSchedule` carry `id` and `created_at` only; both `updated_at` and `version` are absent on these entities, and no operation refreshes or increments them. This convention provides a consistent audit trail and unique addressability for every entity in the system.

### 2.5. Hierarchical Addressing and Validation Order

The API addresses many resources through nested paths (for example, a survey window under a term, or a campus under a system). For every request whose path contains multiple resource identifiers, the server validates existence in a strict left-to-right order: the system identifier first, then the campus, term, or other intermediate identifier, then the child identifier. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path segment that does not correspond to an existing resource within its parent's scope. Existence checking runs after authentication (`ERR_UNAUTHENTICATED`) and authorization (`ERR_FORBIDDEN`), and before any state, business, or fiscal rule is evaluated.

When a mutation would fail for several reasons at once, the server evaluates rule families in a fixed priority order so the surfaced error is deterministic: authentication first, then role authorization, then path-resource existence, then state-machine admissibility (`ERR_INVALID_STATE`), then segregation-of-duties (`ERR_SEGREGATION_OF_DUTIES`), then temporal-window rules (`ERR_TEMPORAL_WINDOW_VIOLATION`), then cross-entity referential integrity (`ERR_REFERENTIAL_INTEGRITY`), then uniqueness constraints (`ERR_DUPLICATE_RESOURCE`), then quorum and threshold constraints (`ERR_THRESHOLD_NOT_MET`), and finally fiscal constraints (`ERR_FISCAL_VIOLATION`). A failure at an earlier family masks every later family. Purely structural problems — a missing required field, an enum value outside its allowed set, an `enrollment` below 1, a `rating` outside 1 through 4, or a `closes_at` that is not strictly after `opens_at` — are reported as `ERR_VALIDATION` (HTTP 400).

### 2.6. Versioning, Cascading Mutation, and Optimistic Concurrency

Every state transition and every computed-field refresh mutates the resource: `updated_at` is set to the current instant and `version` increments by 1. When one operation touches several resources — for example, finalizing a rating also bumps the campus, and deciding a term also bumps the system — each touched resource's `version` increments independently, and each such resource's `updated_at` refreshes. Automatic transitions driven by the logical clock (§2.8) mutate their targets in exactly the same way as operator-driven transitions.

Three write endpoints are guarded by optimistic concurrency control, and each names its own token field:

- Creating a `SelfStudyRating` requires the request body to carry `expected_term_version`, the client-observed `version` of the target `AccreditationTerm`. If the term's current `version` no longer matches — because, for instance, another writer advanced the term from `PREPARATION` to `SELF_STUDY` after the client last read it — the create is rejected with `ERR_STALE_TERM_VERSION` (HTTP 412).
- Posting a `ProgressIndicator` to a goal requires the request body to carry `expected_goal_version`, the client-observed `version` of the target `ImprovementGoal`. If the goal's current `version` has advanced — because another writer posted an indicator that changed `current_value` and `attainment_pct` — the post is rejected with `ERR_STALE_GOAL_VERSION` (HTTP 412).
- Posting a `Payment` against an invoice requires the request body to carry `expected_invoice_version`, the client-observed `version` of the target `Invoice`. If the invoice's current `version` has advanced — because another payment changed its outstanding balance and status — the post is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412).

These three fields are non-optional on their respective endpoints. Endpoints not listed here do not accept a version field at all.

### 2.7. Standards, Weights, and Numeric Precision

The standards framework is configured as a flat catalogue of `Standard` records, each with a public `code` (unique across the catalogue, e.g. "L1" or "T3"), a `title`, a `domain` of `LEADERSHIP`, `LEARNING`, or `RESOURCES`, an integer `weight_pct` between 1 and 100 inclusive, and an `evidence_min_items` count that is zero or greater. Weights are normalized during composite computation, so the weights within one domain need not sum to 100.

Two quantities in the system are fractional and obey fixed precision rules. The campus composite index (`composite_index_pct`) and goal attainment (`attainment_pct`) are each rounded half-up to exactly 2 decimal places. All monetary quantities — fees, credits, invoice amounts, and payments — are integers expressed in cents with no rounding. Date arithmetic for due dates operates at day precision; survey participation thresholds are evaluated in integer space with no floating-point rounding.

### 2.8. The Logical Clock and Time-Driven Transitions

The server maintains a logical clock used for every temporal rule in this document. At startup the clock reads exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time. An `AccreditationOfficer` may advance it through an admin-only test-driving capability that accepts a `to_iso8601` instant and returns the resulting `current_utc`.

Each time the clock is set, the server re-evaluates every clock-driven transition in the system: a `SCHEDULED` survey window whose `opens_at` has been reached but whose `closes_at` has not yet been reached moves to `OPEN`; an `OPEN` window whose `closes_at` has been reached closes (or invalidates — see §3.4); a `CONFIRMED` visit whose `starts_on` has been reached moves to `IN_FIELD`; an `IN_FIELD` visit whose `ends_on` has been reached moves to `REPORT_DRAFT`; an `OPEN` required action item whose `due_date` has passed moves to `OVERDUE`; and a term in `INTERIM_MONITORING` whose renewal window has opened (current time at or after 180 days before `term_end`) moves to `RENEWAL`, issuing a renewal-fee invoice as it does so. Every such automatic transition increments the affected resource's `version` by 1 and refreshes its `updated_at`.

### 2.9. Segregation of Duties

Accreditation credibility depends on no individual judging their own work. Three operations enforce this. An `AccreditationOfficer` may not approve or reject an `EvidenceItem` whose `submitted_by_user_id` equals the officer's own `X-User-ID`. A `Reviewer` may not verify a required action item when the reviewer is the same individual who performed the upstream submission step. And a reviewer whose `conflict_system_ids` list contains the system that owns a visit may not be assigned to that visit's team. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Systems, Campuses, and the Shape of a Membership

An engagement begins when an `AccreditationOfficer` registers an `InstitutionSystem` with its legal `name` and a `system_type` of `DISTRICT`, `NETWORK`, or `SINGLE_SCHOOL`. The new system starts with `accreditation_status` of `CANDIDATE` and a `fee_credit_cents` ledger at 0; the ledger is debited by invoice issuance effects and credited by nothing directly — payments settle invoices rather than the credit ledger — and it can go negative (see §3.8). The system's `current_term_id` points at whichever of its terms is active and is null when none is. Every record owned by a system — campus, term, and invoice alike — carries a server-maintained `system_id` reference back to its owning `InstitutionSystem`, and each record's lifecycle is exposed through its `status` field.

Campuses are created under a system by an officer, each with a `name` and an integer `enrollment` of at least 1, which feeds fee tiering. A new campus starts `IN_SCOPE` and contributes to composite scoring and billing. A system whose `system_type` is `SINGLE_SCHOOL` may host exactly one campus: attempting to create a second campus under such a system is a fiscal-rule violation rejected with `ERR_FISCAL_VIOLATION`. Scope is managed deliberately. An officer may scope a campus out — moving `campus_status` from `IN_SCOPE` to `OUT_OF_SCOPE` — only when none of that campus's ratings under the system's current term has reached `FINALIZED`; the operation nulls the campus's `composite_index_pct`. Scoping back in (`OUT_OF_SCOPE` → `IN_SCOPE`) requires that the system has a non-null `current_term_id` whose term is in `PREPARATION` or `SELF_STUDY`. Withdrawal is the terminal path: an officer may withdraw a campus (`IN_SCOPE` → `WITHDRAWN`) only when the owning term is in `PREPARATION` or `CLOSED`, or when `current_term_id` is null; withdrawal deletes all `SelfStudyRating` rows for that campus under any non-closed term. A campus with `campus_status` of `OUT_OF_SCOPE` or `WITHDRAWN` is excluded from composite and billing counts.

A read-only dashboard projection aggregates a system's progress on demand: it reports `projected_index_pct`, `campus_count_in_scope`, and `finalized_rating_count`, computed across every campus with `campus_status` of `IN_SCOPE` using the same weighted-index rule as the per-campus composite (§3.3). This system-level projection is produced at read time and is never persisted.

### 3.2. Accreditation Terms: From Preparation to Renewal

The `AccreditationTerm` is the unit of accreditation life. An officer creates one under a system by supplying `term_start` (the inclusive ISO start date) and a `term_length_years` of either 5 or 6 — the standard five-year cycle or the extended six-year option. The server computes `term_end` as `term_start` advanced by `term_length_years` calendar years, exclusive. The term opens in `PREPARATION` with `decision_outcome` of `NONE`.

A system may have at most one term in flight at a time. Creating a second term while another term of the same system occupies any state in `SELF_STUDY`, `REVIEW`, `DECISION`, `TERM_ACTIVE`, `INTERIM_MONITORING`, or `RENEWAL` violates the uniqueness constraint and is rejected with `ERR_DUPLICATE_RESOURCE`; the same constraint guards the advance from `PREPARATION` to `SELF_STUDY`, which additionally requires that every `IN_SCOPE` campus of the owning system already has at least one `SelfStudyRating` row — in any status — for every `Standard` in the catalogue. When that advance succeeds, the term moves `PREPARATION` → `SELF_STUDY`, the system's `current_term_id` is set to this term, and both the term's and the system's `version` increment.

From `SELF_STUDY`, the officer advances the term to `REVIEW` only when every `SelfStudyRating` under the term is `FINALIZED` and every `SurveyWindow` under the term is `CLOSED` or `INVALIDATED`. From `REVIEW`, advancement to `DECISION` requires that at least one `VisitEvent` under the term has reached `REPORT_ISSUED` and that no visit under the term remains in `REQUESTED`, `CONFIRMED`, `IN_FIELD`, or `REPORT_DRAFT`.

The decision itself belongs to the `AccreditationCommission`, which posts an `outcome`. Three outcomes are possible. If `outcome` is `ACCREDITED` or `ACCREDITED_WITH_STIPULATIONS`, the term moves `DECISION` → `TERM_ACTIVE`: the term's `decision_outcome` records the payload outcome, the system's `accreditation_status` becomes `ACCREDITED` for an outright grant or `ON_PROBATION` when stipulations attach, and both versions increment. A stipulation-grant is only meaningful with teeth, so `ACCREDITED_WITH_STIPULATIONS` is admissible only when at least one `VisitFinding` with `severity` of `REQUIRED_ACTION` exists under the term's visits; otherwise the request fails. If `outcome` is `DENIED`, the term moves `DECISION` → `CLOSED`: `decision_outcome` becomes `DENIED`, the system's `accreditation_status` becomes `ACCREDITATION_WITHDRAWN`, and `current_term_id` is cleared to null.

During `TERM_ACTIVE`, the system lives out its cycle under monitoring (§3.5, §3.7). The term advances `TERM_ACTIVE` → `INTERIM_MONITORING` only when every `RequiredActionItem` arising from the term's visit findings is `VERIFIED` or `WAIVED` and at least one `InterimReport` under the term has been `ACCEPTED`. Thereafter the clock drives renewal: once the current time reaches 180 days before `term_end`, the term moves `INTERIM_MONITORING` → `RENEWAL` automatically, and entering `RENEWAL` issues a `RENEWAL_FEE` invoice for the owning system per the fee rules of §3.8. Finally, an officer closes the term (`RENEWAL` → `CLOSED`) only when that renewal-fee invoice has reached `PAID`; a close attempted before the renewal fee is settled is rejected with `ERR_FISCAL_VIOLATION`. Closing clears the system's `current_term_id` to null and increments both the term's and the system's `version`.

The `decide` and `close` operations drive the system-level machine as side effects: a grant moves a `CANDIDATE` system to `ACCREDITED` (or an `ON_PROBATION` system back to `ACCREDITED`), a stipulation-grant moves `CANDIDATE` to `ON_PROBATION`, a denial on a renewal decision moves `ACCREDITED` to `ACCREDITATION_WITHDRAWN`, and — as described in §3.6 — a late action-item verification also pushes an `ACCREDITED` system to `ON_PROBATION`.

### 3.3. Self-Study Ratings, Evidence, and the Composite Index

The heart of preparation is the self-study: one `SelfStudyRating` per campus per standard per term. A `SchoolLeader` creates a rating with a payload naming the `term_id`, the `campus_id` it scopes, the `standard_id`, and an integer `rating` from 1 to 4 on the rubric; the OCC token `expected_term_version` is mandatory as described in §2.6. The new rating starts in `DRAFT`. Uniqueness is enforced per (term, campus, standard) triple: a second rating for the same combination is rejected with `ERR_DUPLICATE_RESOURCE`. Referential integrity requires that the named campus belongs to the same system that owns the term and that the named standard exists; violations are rejected with `ERR_REFERENTIAL_INTEGRITY`.

Submission is the leader's act of testimony. Submitting moves a rating `DRAFT` → `SUBMITTED` (or `REOPENED` → `SUBMITTED`) and requires the rubric score to be within 1 to 4, the owning term to be in `SELF_STUDY`, and — for the initial submission from `DRAFT` — the campus to be `IN_SCOPE`. The resubmission path from `REOPENED` does not re-check campus scope, since a mid-flight scope change must not strand an already-finalized-once rating.

Evidence backs the rating. A `SchoolLeader` attaches an `EvidenceItem` to a rating — the server records the association in the item's `rating_id` — with a `title` and an `artifact_uri`; the item starts with `review_status` of `PENDING` and records the acting user's opaque identifier in `submitted_by_user_id`. An `AccreditationOfficer` then reviews each pending item, posting a `decision` that moves it `PENDING` → `APPROVED` or `PENDING` → `REJECTED`. Review is admissible only while the parent rating is `SUBMITTED` or `FINALIZED`, and segregation of duties bars the officer from reviewing an item they themselves submitted (`ERR_SEGREGATION_OF_DUTIES`). A rejected item is not dead: while its parent rating sits in `SUBMITTED` or `REOPENED`, the leader may resubmit it, moving it `REJECTED` → `PENDING` for fresh review.

Finalization is the officer's stamp. Finalizing moves a rating `SUBMITTED` → `FINALIZED`, but only once the evidence quorum is satisfied: the count of `EvidenceItem` rows with `review_status` of `APPROVED` under the rating must be at least the standard's `evidence_min_items`, otherwise the request fails with `ERR_THRESHOLD_NOT_MET`. On finalization the server stamps `finalized_at` with the current instant, increments the rating's `version`, and recomputes the campus composite index — which itself increments the campus's `version`. Reopening runs the same machinery in reverse: an officer may reopen a finalized rating (`FINALIZED` → `REOPENED`) only while the owning term is still in `SELF_STUDY`; the rating's `finalized_at` returns to null and the composite index is recomputed with this rating now excluded, again incrementing both versions.

The composite index, `composite_index_pct`, measures a campus's overall self-assessed standing. Consider the set of the campus's ratings under the system's current term that are `FINALIZED`. If that set is empty, `composite_index_pct` is null. Otherwise, take each such rating's `rating` multiplied by its standard's `weight_pct`, sum those products into a numerator, and sum the participating standards' `weight_pct` values into a denominator; divide the numerator by the denominator, multiply by 100 divided by the rubric maximum of 4, and round the result half-up to 2 decimal places. The index therefore runs from 0.00 to 100.00, weights are normalized automatically by the denominator, and any finalize or reopen on one of the campus's ratings triggers recomputation for that campus.

### 3.4. Stakeholder Surveys: Instruments, Windows, and Anonymous Responses

Survey content is configured as `SurveyInstrument` records, each targeting a `stakeholder_group` of `STUDENTS`, `PARENTS`, `STAFF`, or `BOARD`, carrying a `title` and an integer `min_participation_pct` between 1 and 100 — the response-rate threshold below which the survey administration is invalid.

Administration happens through `SurveyWindow` records scheduled by an officer under a term. Creating a window names the `campus_id`, the `instrument_id`, an inclusive `opens_at`, an exclusive `closes_at` that must be strictly after `opens_at`, and an `eligible_count` of at least 1 describing the population size. The window starts `SCHEDULED` with `response_count` at 0. Referential integrity — the campus must belong to the term's system, the instrument must exist — is enforced with `ERR_REFERENTIAL_INTEGRITY`, and only one window may exist per (term, campus, instrument) combination; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`.

The clock opens and closes windows. When the current time reaches `opens_at` but not yet `closes_at`, a `SCHEDULED` window moves to `OPEN`. When the current time reaches `closes_at`, an `OPEN` window closes — and at that moment its validity is decided by participation. The comparison is performed in integer space: the window passes if `response_count` multiplied by 100 is greater than or equal to `min_participation_pct` multiplied by `eligible_count`, in which case it lands in `CLOSED`; if the product of responses and 100 is strictly less than the threshold product, the window fails and lands in `INVALIDATED` instead. An officer may also close an `OPEN` window manually, provided the current time has reached `opens_at`; the same participation threshold check applies on manual close, so an under-subscribed window is forced to `INVALIDATED` exactly as on auto-close rather than landing in `CLOSED`. Separately, an officer may invalidate a `SCHEDULED` window outright (`SCHEDULED` → `INVALIDATED`) when an administration must be abandoned before it opens. `CLOSED` and `INVALIDATED` are both terminal.

Responses are anonymous. An unauthenticated caller — role `Anonymous` — submits a response to a window with a one-time `respondent_token`; the server records the submission against the window via `window_id`. The submission is accepted only while the window is `OPEN`; outside the window the request is rejected with `ERR_TEMPORAL_WINDOW_VIOLATION`. Each token may be used at most once per window: a repeated token is rejected with `ERR_DUPLICATE_RESOURCE`. A successful submission creates the `SurveyResponse` stamped with the server's `submitted_at`, increments the window's `response_count` by 1, and increments the window's `version`.

### 3.5. Improvement Goals and Progress Indicators

Once accredited, a system works its improvement plan. A `SchoolLeader` proposes an `ImprovementGoal` under a term, supplying an optional `campus_id` (null scopes the goal to the whole system), the `standard_id` the goal addresses, a `title`, a numeric `baseline_value`, a numeric `target_value`, and a `direction` of `INCREASE` or `DECREASE` declaring whether progress means the metric going up or down. The new goal starts `PROPOSED`, with `current_value` initialized to `baseline_value` and `attainment_pct` at 0.00. The named campus must belong to the same system as the term, else `ERR_REFERENTIAL_INTEGRITY`.

Adoption is the officer's gate. Adopting moves a goal `PROPOSED` → `ADOPTED` and enforces three conditions, reported as `ERR_THRESHOLD_NOT_MET` when they fail: the owning term must be in `TERM_ACTIVE` or `INTERIM_MONITORING`; `target_value` must differ from `baseline_value`; and `direction` must be consistent with the target-versus-baseline relationship — `INCREASE` requires `target_value` strictly greater than `baseline_value`, while `DECREASE` requires `target_value` strictly less than `baseline_value`. On adoption the server re-asserts `current_value` as `baseline_value` and `attainment_pct` as 0.00.

Progress is evidenced by `ProgressIndicator` entries posted by the leader against an adopted goal — each entry is tied to its goal through the server-maintained `goal_id` — with a `measured_at` date, a measured `value`, and an optional free-text `note` defaulting to an empty string; the OCC token `expected_goal_version` is mandatory per §2.6. The first indicator posted under an `ADOPTED` goal moves the goal `ADOPTED` → `MONITORING`. After every indicator is committed, the goal's `current_value` and `attainment_pct` are recomputed. The current value is taken from the latest indicator by `measured_at`; a tie on `measured_at` is broken by the earliest-created indicator winning (ascending `created_at`). Attainment expresses progress toward the target as a percentage: for an `INCREASE` goal, progress is the difference between `current_value` and `baseline_value` divided by the difference between `target_value` and `baseline_value`; for a `DECREASE` goal, progress is the difference between `baseline_value` and `current_value` divided by the difference between `baseline_value` and `target_value`. In both directions the progress fraction is clamped to the range from 0 to 1 inclusive, multiplied by 100, and rounded half-up to 2 decimal places.

An officer closes the loop. Marking a goal achieved (`MONITORING` → `ACHIEVED`) requires `attainment_pct` of at least 100.00, failing with `ERR_THRESHOLD_NOT_MET` below that bar. Abandonment (`ADOPTED` → `ABANDONED` or `MONITORING` → `ABANDONED`) carries no preconditions beyond the current state. `ACHIEVED` and `ABANDONED` are terminal.

### 3.6. Visiting Teams: Scheduling, Findings, and Required Actions

During `REVIEW`, the accreditor fields a peer-review team. Reviewers are registered by an officer with a `full_name`, a unique `email`, and an optional `conflict_system_ids` list (defaulting to empty) naming systems for which the reviewer has a conflict of interest; a new reviewer's `reviewer_status` starts at `AVAILABLE`. An officer may deactivate a reviewer (`reviewer_status` moving `AVAILABLE` → `INACTIVE`) only when the reviewer is not assigned to any visit in `REQUESTED`, `CONFIRMED`, `IN_FIELD`, or `REPORT_DRAFT`.

A visit is requested by an officer under a term, naming an optional `campus_id` (null indicates a system-level visit), the `lead_reviewer_id` designated as chair, an inclusive `starts_on`, and an exclusive `ends_on` strictly after `starts_on`; it begins `REQUESTED`. Team composition is built up through assignments, each naming a `reviewer_id` and a `role_on_team` of `CHAIR`, `MEMBER`, or `OBSERVER`, and each tied to its visit through the server-maintained `visit_id`. Assignment creation enforces conflict-of-interest segregation: a reviewer whose `conflict_system_ids` contains the visit's owning system cannot be assigned (`ERR_SEGREGATION_OF_DUTIES`), and the reviewer must exist and be `AVAILABLE`, else `ERR_REFERENTIAL_INTEGRITY`.

Confirming a visit (`REQUESTED` → `CONFIRMED`) is the officer's scheduling commitment, guarded by five preconditions evaluated together: the owning term must be in `REVIEW`; at least one assignment with `role_on_team` of `CHAIR` must exist; the reviewer named by `lead_reviewer_id` must be `AVAILABLE`; no other visit for the same campus may overlap the half-open date interval from `starts_on` (inclusive) to `ends_on` (exclusive) while holding status `CONFIRMED` or `IN_FIELD`; and no reviewer assigned to this visit may be assigned to another visit whose date interval overlaps this one while that visit is `CONFIRMED` or `IN_FIELD`. Overlap violations surface as `ERR_TEMPORAL_WINDOW_VIOLATION`. On confirmation, every assigned reviewer moves `AVAILABLE` → `ON_ASSIGNMENT`, and each assigned reviewer's `version` increments alongside the visit's.

Thereafter the clock moves the visit: reaching `starts_on` moves `CONFIRMED` → `IN_FIELD`; reaching `ends_on` moves `IN_FIELD` → `REPORT_DRAFT`. Cancellation is available to an officer from `REQUESTED` without condition, and from `CONFIRMED` only while the current time is still before `starts_on`; either path lands the visit in the terminal `CANCELLED` state, and cancelling a confirmed visit frees every assigned reviewer back to `AVAILABLE`.

Findings are the team's written record. A `Reviewer` drafts a `VisitFinding` on a visit — the server links it through `visit_id` — with a `standard_id`, a `severity` of `COMMENDATION`, `RECOMMENDATION`, or `REQUIRED_ACTION`, a free-text `narrative`, and — required exactly when `severity` is `REQUIRED_ACTION` — a `follow_up_months` of 6, 12, or 18 declaring how many months from visit end the resulting action item is allowed. Draft findings start `DRAFT`. The lead reviewer — and only the lead reviewer, matched by `X-User-ID` against the visit's `lead_reviewer_id` — may issue a draft finding (`DRAFT` → `ISSUED`) while the visit is `IN_FIELD` or `REPORT_DRAFT`, or supersede one (`DRAFT` → `SUPERSEDED`) while the visit is `REPORT_DRAFT`. `SUPERSEDED` is terminal.

Issuing the visit report is the lead reviewer's final act (`REPORT_DRAFT` → `REPORT_ISSUED`): it requires the acting reviewer to be the visit's `lead_reviewer_id`, at least one finding to exist, and every finding under the visit to be `ISSUED`. The issuance cascades: every assigned reviewer is freed to `AVAILABLE`, and for every finding with `severity` of `REQUIRED_ACTION` the server creates a `RequiredActionItem` in `OPEN` status, linked to its source finding through `finding_id` and carrying a free-text `description` of what must be done. The action item's `follow_up_months` is copied from its parent finding, and its `due_date` is computed by adding that many calendar months to the visit's `ends_on` — calendar-month addition preserves the day-of-month where possible and clamps to the last day of the target month when that month is shorter (so 2026-01-31 plus 1 month yields 2026-02-28).

A required action item then lives its own follow-up cycle. A `SchoolLeader` submits follow-up evidence with a free-text `narrative`, moving the item `OPEN` → `SUBMITTED` or `OVERDUE` → `SUBMITTED`. A `Reviewer` verifies a submitted item (`SUBMITTED` → `VERIFIED`) provided the current time is on or before `due_date`; a late verify against `SUBMITTED` is rejected with `ERR_TEMPORAL_WINDOW_VIOLATION`, and a reviewer who is the same individual who submitted the evidence is refused with `ERR_SEGREGATION_OF_DUTIES`. Verification stamps `verified_by_user_id` with the acting reviewer's id. A reviewer may instead return a submitted item (`SUBMITTED` → `OPEN`) for rework. If the clock passes `due_date` with the item still `OPEN`, it moves automatically to `OVERDUE`. An overdue item can still be rescued: the leader submits evidence against the `OVERDUE` item, moving it to `SUBMITTED`; a reviewer may then verify it on the normal path. In addition, a reviewer may verify directly from `OVERDUE` (`OVERDUE` → `VERIFIED`) provided the item currently has an evidence submission pending — that is, a submit-evidence act performed while the item was `OVERDUE` must precede the overdue verification. That late verification carries a consequence: the owning system's `accreditation_status` is set to `ON_PROBATION` if it is not already, and the system's `version` increments alongside the item's. Finally, the `AccreditationCommission` may waive an item (`OPEN` → `WAIVED`) only while the current time is on or before `due_date`; a late waive is rejected with `ERR_TEMPORAL_WINDOW_VIOLATION`. `VERIFIED` and `WAIVED` are terminal.

### 3.7. Interim Reporting

Accreditation is maintained between visits through interim reports. A `SchoolLeader` creates an `InterimReport` under a term by naming the `report_year` — an integer from 1 up to one less than the term's length in years — and a `narrative` body. Only one report may exist per (term, `report_year`) pair; a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. The server computes the report's `due_date` as the term's `term_start` advanced by `report_year` calendar years — calendar-year addition clamps February 29 to February 28 in non-leap years — and then moved earlier by 60 days of advance notice; the submission window closes at that due date. The report begins `DRAFT` with `submitted_at` null.

Submission moves the report `DRAFT` → `SUBMITTED`, or `RETURNED` → `SUBMITTED` after rework, and requires the owning term to be in `TERM_ACTIVE` or `INTERIM_MONITORING`. The server stamps `submitted_at` with the current instant, and if that instant is after the `due_date`, the report lands in `LATE` instead of `SUBMITTED`. An officer then dispositions the report: accepting moves `SUBMITTED` → `ACCEPTED` or `LATE` → `ACCEPTED` (the latter is terminal), while returning moves `SUBMITTED` → `RETURNED` for rework.

Accepting a late report is not free. When an officer accepts a report whose status is `LATE`, the system's `fee_credit_cents` ledger is debited by a flat late-report penalty of 25000 cents (250 dollars); the ledger may go negative, and the system's `version` increments alongside the report's. A negative credit balance is added onto the next annual-fee invoice, as described in §3.8.

### 3.8. Fees, Invoices, and Payments

The accreditor's revenue is configured through `FeeSchedule` records, each taking effect from an inclusive, unique `effective_from` date and declaring five integer-cent values: `base_system_fee_cents` (the annual per-system base), `per_campus_fee_cents` (the annual rate for campuses below the large threshold), `large_campus_fee_cents` (the annual rate for campuses at or above it), `large_campus_threshold` (the enrollment at which a campus is billed the large rate), and `visit_day_rate_cents` (the per-visit-day surcharge).

A `SystemBursar` issues an `Invoice` to a system by naming the `billing_year` and an `invoice_type` of `ANNUAL_FEE`, `VISIT_FEE`, or `RENEWAL_FEE`. Issuance stamps `issued_at` with the current instant, sets status `ISSUED`, and computes `amount_cents` from the fee schedule in effect — the schedule row with the greatest `effective_from` on or before the issuance date, with ties on `effective_from` broken by earliest creation; if no such schedule exists for the issuance date, issuance fails with `ERR_FISCAL_VIOLATION`.

For an `ANNUAL_FEE` invoice, the billable campus count is the number of the system's campuses with `campus_status` of `IN_SCOPE`. Those with `enrollment` at or above the schedule's `large_campus_threshold` are billed at `large_campus_fee_cents` each; the remainder at `per_campus_fee_cents` each; the `base_system_fee_cents` is added once. The system's credit ledger then adjusts the total: when `fee_credit_cents` is positive, the applied credit is the lesser of the ledger balance and the pre-credit amount, the invoice amount is reduced by that applied credit, and the ledger is debited by the same amount; when the ledger is negative (for instance, from a late-report penalty), the magnitude of the negative balance is added to the invoice amount and the ledger is reset to zero. Any issuance that moves the ledger increments the system's `version`.

For a `VISIT_FEE` invoice, the amount is the schedule's `visit_day_rate_cents` multiplied by the total billable visit-days of the term: for each visit under the term whose status is one of `CONFIRMED`, `IN_FIELD`, `REPORT_DRAFT`, or `REPORT_ISSUED`, the whole-day difference between the exclusive `ends_on` and the inclusive `starts_on` is summed. A read-time provisional projection, used while visits are still underway, counts only visits in `CONFIRMED`, `IN_FIELD`, or `REPORT_DRAFT` and excludes `REPORT_ISSUED`; the final settlement invoice, issued after a report is issued, counts visits in `REPORT_ISSUED` only, and the earlier provisional projection is discarded. The `RENEWAL_FEE` invoice issued automatically on entering `RENEWAL` (§3.2) follows the same issuance machinery.

Payments settle invoices without touching the credit ledger. A `SystemBursar` posts a `Payment` against an invoice — the server records the association in the payment's `invoice_id` — with an `amount_cents` greater than zero, a client-supplied `paid_at` timestamp, and the mandatory OCC token `expected_invoice_version` (§2.6). A payment that exceeds the invoice's outstanding balance is rejected with `ERR_FISCAL_VIOLATION`. The invoice's status tracks settlement: a partial payment moves `ISSUED` → `PARTIALLY_PAID`; cumulative payments reaching exactly `amount_cents` move `ISSUED` → `PAID` or `PARTIALLY_PAID` → `PAID`. An officer of the bursar's office may void an invoice (`ISSUED` → `VOID`) only when no payment rows exist for it. `PAID` and `VOID` are terminal.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources or add new, distinct resources to a collection return a `201 Created` status code. Operations that modify an existing resource's state or trigger a transition return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accreditation/_clock/set_current_utc` | Set the server's logical clock | AccreditationOfficer |
| POST | `/accreditation/systems` | Create an InstitutionSystem | AccreditationOfficer |
| GET | `/accreditation/systems` | List InstitutionSystems | AccreditationOfficer, AccreditationCommission, SystemBursar |
| GET | `/accreditation/systems/{id}` | Get an InstitutionSystem | AccreditationOfficer, AccreditationCommission, SchoolLeader, SystemBursar |
| GET | `/accreditation/systems/{id}/dashboard` | System-level projected composite index across campuses | AccreditationOfficer, AccreditationCommission |
| POST | `/accreditation/systems/{id}/campuses` | Create a Campus under a system | AccreditationOfficer |
| GET | `/accreditation/systems/{id}/campuses` | List campuses of a system | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/campuses/{id}` | Get a Campus | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/campuses/{id}/scope-out` | Move campus OUT_OF_SCOPE | AccreditationOfficer |
| POST | `/accreditation/campuses/{id}/scope-in` | Move campus back IN_SCOPE | AccreditationOfficer |
| POST | `/accreditation/campuses/{id}/withdraw` | Withdraw campus permanently | AccreditationOfficer |
| GET | `/accreditation/campuses/{id}/ratings` | List ratings for a campus | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/campuses/{id}/survey-windows` | List survey windows for a campus | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/campuses/{id}/goals` | List goals for a campus | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/campuses/{id}/visits` | List visits for a campus | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| POST | `/accreditation/standards` | Create a Standard (framework configuration) | AccreditationOfficer |
| GET | `/accreditation/standards` | List standards | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| GET | `/accreditation/standards/{id}` | Get a Standard | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| GET | `/accreditation/standards/{id}/ratings` | List ratings against a standard | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/standards/{id}/goals` | List goals against a standard | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/standards/{id}/findings` | List findings against a standard | AccreditationOfficer, AccreditationCommission, Reviewer |
| POST | `/accreditation/systems/{id}/terms` | Create an AccreditationTerm | AccreditationOfficer |
| GET | `/accreditation/systems/{id}/terms` | List terms of a system | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/terms/{id}` | Get an AccreditationTerm | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| POST | `/accreditation/terms/{id}/advance` | Advance term to next lifecycle state | AccreditationOfficer |
| POST | `/accreditation/terms/{id}/decide` | Commission decision on the term | AccreditationCommission |
| POST | `/accreditation/terms/{id}/close` | Close a RENEWAL-state term after renewal fee paid | AccreditationOfficer |
| POST | `/accreditation/ratings` | Create a SelfStudyRating (OCC-guarded on term version) | SchoolLeader |
| GET | `/accreditation/terms/{id}/ratings` | List ratings under a term | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/ratings/{id}` | Get a SelfStudyRating | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/ratings/{id}/submit` | Submit a rating (DRAFT or REOPENED → SUBMITTED) | SchoolLeader |
| POST | `/accreditation/ratings/{id}/finalize` | Finalize a submitted rating after evidence quorum | AccreditationOfficer |
| POST | `/accreditation/ratings/{id}/reopen` | Reopen a finalized rating | AccreditationOfficer |
| POST | `/accreditation/ratings/{id}/evidence` | Attach evidence to a rating | SchoolLeader |
| GET | `/accreditation/ratings/{id}/evidence` | List evidence under a rating | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/evidence/{id}/review` | Approve or reject an evidence item | AccreditationOfficer |
| POST | `/accreditation/evidence/{id}/resubmit` | Resubmit a rejected evidence item | SchoolLeader |
| POST | `/accreditation/survey-instruments` | Create a survey instrument | AccreditationOfficer |
| GET | `/accreditation/survey-instruments` | List survey instruments | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/survey-instruments/{id}` | Get a survey instrument | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/survey-instruments/{id}/survey-windows` | List survey windows using an instrument | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/terms/{id}/survey-windows` | Schedule a survey window | AccreditationOfficer |
| GET | `/accreditation/terms/{id}/survey-windows` | List survey windows under a term | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/survey-windows/{id}` | Get a survey window | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/survey-windows/{id}/responses` | Submit an anonymous survey response | Anonymous |
| GET | `/accreditation/survey-windows/{id}/responses` | List responses of a survey window | AccreditationOfficer, AccreditationCommission |
| POST | `/accreditation/survey-windows/{id}/close` | Manually close a survey window (threshold check applies) | AccreditationOfficer |
| POST | `/accreditation/survey-windows/{id}/invalidate` | Invalidate a scheduled window | AccreditationOfficer |
| POST | `/accreditation/terms/{id}/goals` | Create an improvement goal | SchoolLeader |
| GET | `/accreditation/terms/{id}/goals` | List goals under a term | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/goals/{id}` | Get an improvement goal | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/goals/{id}/adopt` | Adopt a proposed goal | AccreditationOfficer |
| POST | `/accreditation/goals/{id}/indicators` | Post a progress indicator (OCC-guarded on goal version) | SchoolLeader |
| GET | `/accreditation/goals/{id}/indicators` | List indicators of a goal | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/goals/{id}/mark-achieved` | Mark a goal achieved (requires attainment ≥ 100) | AccreditationOfficer |
| POST | `/accreditation/goals/{id}/abandon` | Abandon a goal | AccreditationOfficer |
| POST | `/accreditation/reviewers` | Register a reviewer | AccreditationOfficer |
| GET | `/accreditation/reviewers` | List reviewers | AccreditationOfficer, AccreditationCommission |
| GET | `/accreditation/reviewers/{id}` | Get a reviewer | AccreditationOfficer, AccreditationCommission, Reviewer |
| POST | `/accreditation/reviewers/{id}/deactivate` | Deactivate a reviewer | AccreditationOfficer |
| POST | `/accreditation/terms/{id}/visits` | Request a visit event | AccreditationOfficer |
| GET | `/accreditation/terms/{id}/visits` | List visits under a term | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| GET | `/accreditation/visits/{id}` | Get a visit | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| POST | `/accreditation/visits/{id}/assignments` | Assign a reviewer to a visit team | AccreditationOfficer |
| GET | `/accreditation/visits/{id}/assignments` | List assignments of a visit | AccreditationOfficer, AccreditationCommission, Reviewer |
| GET | `/accreditation/reviewers/{id}/assignments` | List assignments of a reviewer | AccreditationOfficer, AccreditationCommission, Reviewer |
| GET | `/accreditation/reviewers/{id}/visits` | List visits led by a reviewer | AccreditationOfficer, AccreditationCommission, Reviewer |
| POST | `/accreditation/visits/{id}/confirm` | Confirm a requested visit | AccreditationOfficer |
| POST | `/accreditation/visits/{id}/cancel` | Cancel a visit | AccreditationOfficer |
| POST | `/accreditation/visits/{id}/issue-report` | Issue the final visit report (lead reviewer only) | Reviewer |
| POST | `/accreditation/visits/{id}/findings` | Draft a finding on a visit | Reviewer |
| GET | `/accreditation/visits/{id}/findings` | List findings of a visit | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| GET | `/accreditation/findings/{id}` | Get a visit finding | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| POST | `/accreditation/findings/{id}/issue` | Issue a draft finding | Reviewer |
| POST | `/accreditation/findings/{id}/supersede` | Supersede a draft finding | Reviewer |
| GET | `/accreditation/findings/{id}/action-items` | List action items of a finding | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| GET | `/accreditation/terms/{id}/action-items` | List action items across a term | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| GET | `/accreditation/action-items/{id}` | Get an action item | AccreditationOfficer, AccreditationCommission, SchoolLeader, Reviewer |
| POST | `/accreditation/action-items/{id}/submit-evidence` | School submits follow-up evidence | SchoolLeader |
| POST | `/accreditation/action-items/{id}/verify` | Reviewer verifies an action item | Reviewer |
| POST | `/accreditation/action-items/{id}/return` | Reviewer returns a submitted item | Reviewer |
| POST | `/accreditation/action-items/{id}/waive` | Commission waives an action item | AccreditationCommission |
| POST | `/accreditation/terms/{id}/interim-reports` | Create an interim report | SchoolLeader |
| GET | `/accreditation/terms/{id}/interim-reports` | List interim reports of a term | AccreditationOfficer, AccreditationCommission, SchoolLeader |
| POST | `/accreditation/interim-reports/{id}/submit` | Submit an interim report | SchoolLeader |
| POST | `/accreditation/interim-reports/{id}/accept` | Accept a submitted report | AccreditationOfficer |
| POST | `/accreditation/interim-reports/{id}/return` | Return a submitted report for rework | AccreditationOfficer |
| POST | `/accreditation/fee-schedules` | Create a fee schedule | AccreditationOfficer |
| GET | `/accreditation/fee-schedules` | List fee schedules | AccreditationOfficer, SystemBursar |
| POST | `/accreditation/systems/{id}/invoices` | Issue an invoice (amount computed per fee schedule) | SystemBursar |
| GET | `/accreditation/systems/{id}/invoices` | List invoices of a system | AccreditationOfficer, SystemBursar |
| GET | `/accreditation/invoices/{id}` | Get an invoice | AccreditationOfficer, SystemBursar |
| POST | `/accreditation/invoices/{id}/payments` | Post a payment against an invoice (OCC-guarded) | SystemBursar |
| GET | `/accreditation/invoices/{id}/payments` | List payments of an invoice | AccreditationOfficer, SystemBursar |
| POST | `/accreditation/invoices/{id}/void` | Void an unpaid invoice | SystemBursar |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_TERM_VERSION` | 412 |
| `ERR_STALE_GOAL_VERSION` | 412 |
| `ERR_STALE_INVOICE_VERSION` | 412 |
| `ERR_SEGREGATION_OF_DUTIES` | 422 |
| `ERR_TEMPORAL_WINDOW_VIOLATION` | 422 |
| `ERR_REFERENTIAL_INTEGRITY` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_THRESHOLD_NOT_MET` | 422 |
| `ERR_FISCAL_VIOLATION` | 422 |
| `ERR_VALIDATION` | 400 |

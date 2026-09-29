# State Building Code Council API — Product Requirements Document

## 1. Introduction

Every three years the state building code council must decide which parts of a new model code edition the state will adopt as written, which parts it will amend, and when the amended edition begins to bind permit applicants. Today that work is spread across spreadsheets, mailing lists and paper hearing minutes: an industry association files a proposed amendment, technical staff prepare a cost-benefit memo, the public comments, a discipline committee votes, and a rulemaking order eventually issues with an effective date that nobody can reconstruct from first principles. When a committee member recuses themselves the day before a hearing, or when an approved amendment has to be pulled back for redrafting, the downstream consequences — a re-scored docket, a re-dated transition schedule, an obsolete cost certification — are worked out by hand and frequently missed.

This API replaces that manual chain with a single system of record for the whole adoption cycle. It carries a model-code review cycle from the seating of its discipline committees, through amendment intake from industry, the fire service and local jurisdictions, cost-benefit and energy impact analysis, public comment, hearings with recorded ballots, and finally adoption rulemaking with statutory notice periods and transition rules for projects already in review. It then continues past adoption into the operational life of the code: local jurisdictions filing their own amendments within their delegated authority, building officials asking for formal interpretations of the adopted text, and the training rollout that must reach the officials who will enforce the new edition before enforcement may legally begin.

Three properties drive most of the design. First, an amendment carries **two independent status dimensions** — where it sits in the review pipeline, and how complete its impact analysis is — and the two advance on different triggers. Second, the system is a **ledger system**: certified statewide costs, permit backlogs and training seats are conserved quantities that must reconcile exactly after every write, including after a compensating write that undoes an earlier approval. Third, the council is subject to **segregation of duties**: the staffer who prepares an analysis may not accept it, the administrator who files a rulemaking order may not publish it, and the technical writer who drafts a formal opinion may not publish it.

## 2. Global Specifications & System-Wide Principles

This section defines the contracts that hold for every endpoint in the API. Collections are mounted flat: each resource family occupies a top-level path segment, and nesting appears only where a child genuinely lives inside a parent.

### 2.1. Council Roles and Request Identity

Every request — including reads — must carry two headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which it is acting. If either header is absent or empty, the request is rejected with `ERR_UNAUTHENTICATED` (401) before the body is even parsed. If the declared role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE` (403).

Six roles exist, spelled exactly as follows:

- `CouncilAdmin` — council administrative staff. Runs the cycle, seats committees, manages comment periods, schedules hearings, drafts and advances rulemaking orders, registers jurisdictions, reviews local filings, and runs the training rollout.
- `TechnicalStaff` — council technical staff. Screens intake, prepares cost-benefit and energy analyses, drafts formal opinions.
- `CommitteeMember` — a seated committee member. Reads the docket and the analyses; records nothing.
- `CouncilChair` — the presiding chair of a discipline committee. Convenes hearings, records ballots, adjourns.
- `JurisdictionOfficial` — a local building department. Files local amendments, enrolls staff in training, appeals formal opinions.
- `Petitioner` — an industry or fire-service petitioner outside government. Proposes amendments, comments, asks for interpretations.

The meaning of `X-User-ID` depends on the declared role. When `X-User-Role` is `CommitteeMember`, `X-User-ID` is the `id` of the acting `CommitteeMember` row; ownership and eligibility checks compare that identifier against committee membership. When `X-User-Role` is `CouncilChair`, `X-User-ID` is likewise the `id` of a `CommitteeMember` row — the one that presides. When `X-User-Role` is `JurisdictionOfficial`, `X-User-ID` is the `id` of the acting `Jurisdiction`; ownership checks on any resource that references a jurisdiction compare that resource's jurisdiction foreign key to `X-User-ID`. For these three entity-backed roles, an `X-User-ID` that does not resolve to a live row of the backing entity — a `CommitteeMember` row for `CommitteeMember` and `CouncilChair`, a `Jurisdiction` row for `JurisdictionOfficial` — is an authorization failure reported as `ERR_IDENTITY_NOT_FOUND` (403), never a 404.

When `X-User-Role` is `CouncilAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow step demands accountability — as `filed_by_user_id` and `published_by_user_id` on a rulemaking order, as `reviewed_by_user_id` on an impact analysis or a local filing, as `published_by_user_id` on a formal opinion, as `enrolled_by_user_id` on a training enrollment — but never compares it to any entity's `id`. The same is true when `X-User-Role` is `TechnicalStaff`, whose identifier lands in `prepared_by_user_id` on an analysis and `drafted_by_user_id` on an opinion, and when `X-User-Role` is `Petitioner`, whose identifier lands in `submitted_by_user_id` on a proposal or a public comment and in `requested_by_user_id` on an interpretation request.

Two role gates go beyond the flat endpoint-level check. A `JurisdictionOfficial` may only act on resources belonging to its own jurisdiction: filing or resubmitting a local amendment, enrolling an attendee, cancelling an enrollment, or appealing an opinion on behalf of another jurisdiction is rejected with `ERR_JURISDICTION_MISMATCH` (403). A `CouncilChair` may only act at a hearing held by the committee it chairs: `X-User-ID` must resolve to a `CommitteeMember` whose `is_chair` is true, whose `status` is `ACTIVE`, and whose `committee_id` equals the hearing's committee; otherwise the convene, adjourn and vote-recording actions are rejected with `ERR_NOT_COMMITTEE_CHAIR` (403). The chair of a different committee holds the `CouncilChair` role but cannot preside here.

Finally, the formal-opinion action endpoint carries a role gate per action rather than per endpoint. `ASSIGN`, `PUBLISH` and `DECLINE` require `CouncilAdmin`; `ISSUE_OPINION` requires `TechnicalStaff`; `APPEAL` requires `JurisdictionOfficial`. A role that is authorized for the endpoint but not for the requested action is rejected with `ERR_FORBIDDEN_ROLE` at the same point in the ladder as any other role failure.

All read endpoints accept every one of the six roles.

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

### 2.3. Pagination and Docket Filtering

List endpoints are paginated through two query parameters. `limit` is the maximum number of rows returned; it defaults to 10 when omitted, and its accepted range is a minimum of 1 and a maximum of 100. `offset` is the number of rows skipped; it defaults to 0 when omitted, and must not be negative. A `limit` outside 1 through 100, or a negative `offset`, is rejected with `ERR_PAGINATION_INVALID` (400).

Unless a specific endpoint states otherwise, every list endpoint returns its rows sorted by `created_at` in ascending order. List responses populate `limit`, `offset`, `total_count` and `has_more` in the `meta` object of the envelope, where `total_count` counts every row matching the filters before pagination is applied.

Each collection also accepts optional equality filters, which combine conjunctively with each other and with pagination:

- Code cycles filter on `status` and `cycle_year`.
- Discipline committees filter on `code_cycle_id`, `discipline` and `status`.
- Committee members filter on `committee_id`, `sector` and `status`.
- Amendment proposals filter on `review_status`, `analysis_status`, `discipline`, `code_cycle_id` and `committee_id`.
- Impact analyses filter on `proposal_id`, `analysis_type` and `status`.
- Public comments filter on `proposal_id`, `position` and `commenter_sector`.
- Hearings filter on `status` and `committee_id`.
- Vote records filter on `hearing_id`, `proposal_id` and `outcome`.
- Adoption rules filter on `status` and `code_cycle_id`.
- Jurisdictions filter on `local_authority_level` and `enforcement_readiness`.
- Local amendments filter on `jurisdiction_id`, `adoption_rule_id` and `status`.
- Interpretation requests filter on `status`, `code_section`, `adoption_rule_id`, `jurisdiction_id`, `assigned_committee_id` and `supersedes_request_id`.
- Training sessions filter on `status`, `discipline`, `adoption_rule_id` and `host_jurisdiction_id`.
- Training enrollments filter on `training_session_id`, `jurisdiction_id` and `status`.

Sub-collection reads that hang off a parent identifier (the committees of a cycle, the comments on a proposal, the enrollments on a session, and so on) accept `limit` and `offset` only; the parent identifier in the path is itself the filter.

### 2.4. Common Record Properties and the Logical Clock

Every persisted record exposes a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`). Most records additionally expose `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that record — including mutations the server performs on its own initiative, such as recomputing a derived count or cascading a status change.

Two record families are append-only and therefore carry neither field: a `PublicComment` and a `VoteRecord` expose only `id` and `created_at`. Both `updated_at` and `version` are absent from those two record types entirely. A vote, once recorded, is never edited; a comment, once received, is never revised.

All temporal rules in this system read a **logical clock** rather than wall-clock time, so that notice periods, comment windows, effective dates and appeal deadlines can be exercised deterministically. Before any client sets it, the clock reads `2026-08-01T00:00:00Z`. Any of the six roles may reposition it by submitting `current_utc` to the clock endpoint (`POST /_clock/set_current_utc`), and every subsequent temporal comparison — including comparisons the server performs inside cascades — uses that instant. Timestamps the server stamps onto records, such as `received_at` on a comment, `convened_at` and `adjourned_at` on a hearing, and `published_at` on a rulemaking order or a formal opinion, are taken from this clock.

### 2.5. The Order in Which a Request Is Rejected

A request that violates several rules at once must produce a single, predictable error. The server therefore evaluates checks in strict ascending priority order and reports only the first violation it finds; later checks are never reached. The ladder is:

1. **Authentication** — both `X-User-ID` and `X-User-Role` present and non-empty, else `ERR_UNAUTHENTICATED` (401). This runs before the body is parsed.
2. **Role authorization** — the declared role is authorized for the endpoint and (on the formal-opinion action endpoint) for the requested action, else `ERR_FORBIDDEN_ROLE` (403). Because this precedes every existence check, an unauthorized role probing a randomly invented identifier receives 403, never 404.
3. **Identity resolution** — for the entity-backed roles `CommitteeMember`, `CouncilChair` and `JurisdictionOfficial`, `X-User-ID` resolves to a live backing row, else `ERR_IDENTITY_NOT_FOUND` (403).
4. **Request shape** — required fields present, types correct, enum members recognized, numeric ranges honored, datetimes well-formed ISO 8601 UTC, and every declared interval satisfying an end strictly later than its start, else `ERR_INVALID_REQUEST` (400). This step enforces `cycle_year` between 2020 and 2050 inclusive, `voting_seat_count` between 3 and 12 inclusive, `measure_life_years` between 1 and 40 inclusive, `seat_capacity` at least 1, `official_headcount` at least 1, `affected_permit_count` at least 0, `annual_cost_savings_cents` at least 0, occupancy-class keys drawn from the recognized set, and the per-analysis-type required-field sets described in §3.3.
5. **Pagination shape** — `limit` within 1 through 100 and `offset` at least 0, else `ERR_PAGINATION_INVALID` (400).
6. **Path existence** — every identifier in the URL path resolves to a live row, else the 404 error for that record family. Outer path segments resolve before inner ones: a cycle before its committee, a committee before its member.
7. **Body reference existence** — every foreign key supplied in the body resolves to a live row, and a child identifier supplied in a body belongs to the parent named in the path, else the corresponding 404. A referenced row that exists but sits at the wrong position in the graph is not a 404 — that is priority 15 below.
8. **Jurisdiction ownership** — for `JurisdictionOfficial`, `X-User-ID` equals the jurisdiction identifier of the resource being written, else `ERR_JURISDICTION_MISMATCH` (403).
9. **Chair ownership** — for `CouncilChair`, the acting member is the `ACTIVE` chair of the hearing's committee, else `ERR_NOT_COMMITTEE_CHAIR` (403).
10. **Stale-read protection** — the supplied expected parent version matches the parent's current `version`, else the relevant 412 error (§2.8).
11. **Own state** — the target record's own current state permits the requested transition, else the 409 state error for that record family. This also covers terminal-state lockdown and repeated attempts at an action that has already been taken.
12. **Depended-upon state** — the state of a *different* record that the operation depends on is acceptable, else a 409 cross-entity state error. Intake requires an open cycle; a hearing requires a seated committee; opening a comment window requires a complete analysis; local filings, training sessions and interpretation assignments require an in-force rulemaking order.
13. **Segregation of duties** — the acting `X-User-ID` differs from the user recorded for the paired earlier step, else `ERR_SEGREGATION_OF_DUTIES` (409). Evaluated after state, so a wrongly staged request reports the state problem first.
14. **Business safety** — the stringency floor on life-safety sections, the stringency limit on local amendments, and quorum, each yielding a 422.
15. **Business referential placement** — a referenced row exists but is attached to the wrong graph position, yielding a 409.
16. **Business temporal** — notice periods, window boundaries, overlap and capacity-in-time rules, each yielding a 409.
17. **Business constraint** — uniqueness, capacity and round-limit rules, each yielding a 409.
18. **Business fiscal and readiness** — benefit-cost floor, statewide training readiness, and the approved-amendment gates, each yielding a 422.

Three orderings inside this ladder are worth stating explicitly because they are easy to get backwards:

- A stale expected version on a proposal whose `review_status` *also* forbids filing an analysis is reported as `ERR_STALE_PROPOSAL_VERSION` (priority 10), not as the state error (priority 11). Conversely, attempting to convene a hearing that has been `CANCELLED` before its `scheduled_start` has been reached reports `ERR_HEARING_STATE_INVALID` (priority 11), not `ERR_HEARING_NOT_STARTED` (priority 16).
- A `LESS_STRINGENT` proposal touching a life-safety section whose final benefit-cost ratio is *also* below the floor reports `ERR_STRINGENCY_FLOOR_VIOLATION` (priority 14), not `ERR_BENEFIT_COST_BELOW_FLOOR` (priority 18).
- A duplicated ballot cast for a member who is not even on the committee reports `ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE` (priority 15), not `ERR_DUPLICATE_BALLOT` (priority 17). Likewise, a jurisdiction with no delegated authority attempting a filing that would also duplicate an existing section reports `ERR_LOCAL_AUTHORITY_ABSENT` (priority 15), not `ERR_DUPLICATE_LOCAL_AMENDMENT` (priority 17).

### 2.6. Nested Path Resolution and Referential Placement

Where a path carries more than one identifier — `/code-cycles/{code_cycle_id}/discipline-committees`, `/discipline-committees/{committee_id}/members`, `/amendment-proposals/{proposal_id}/impact-analyses`, `/training-sessions/{training_session_id}/enrollments` — the identifiers are resolved strictly left to right, and the first one that fails to resolve determines the 404 reported. A request for the members of a committee under a cycle that does not exist reports `ERR_CODE_CYCLE_NOT_FOUND` before the committee is even looked up.

Each record family has exactly one existence error, used both for an unresolvable path identifier and for an unresolvable foreign key supplied in a body: a code cycle reports `ERR_CODE_CYCLE_NOT_FOUND`, a discipline committee `ERR_COMMITTEE_NOT_FOUND`, a committee member `ERR_COMMITTEE_MEMBER_NOT_FOUND`, an amendment proposal `ERR_PROPOSAL_NOT_FOUND`, an impact analysis `ERR_ANALYSIS_NOT_FOUND`, a public comment `ERR_COMMENT_NOT_FOUND`, a hearing `ERR_HEARING_NOT_FOUND`, a vote record `ERR_VOTE_RECORD_NOT_FOUND`, an adoption rule `ERR_ADOPTION_RULE_NOT_FOUND`, a jurisdiction `ERR_JURISDICTION_NOT_FOUND`, a local amendment `ERR_LOCAL_AMENDMENT_NOT_FOUND`, an interpretation request `ERR_INTERPRETATION_REQUEST_NOT_FOUND`, a training session `ERR_TRAINING_SESSION_NOT_FOUND`, and a training enrollment `ERR_ENROLLMENT_NOT_FOUND`. All fourteen are 404 responses. The rule holds for body references too: a proposal naming a `code_cycle_id` that does not exist reports `ERR_CODE_CYCLE_NOT_FOUND`, a local amendment naming an unknown `adoption_rule_id` reports `ERR_ADOPTION_RULE_NOT_FOUND`, an interpretation request naming an unknown `supersedes_request_id` or `assigned_committee_id` reports `ERR_INTERPRETATION_REQUEST_NOT_FOUND` or `ERR_COMMITTEE_NOT_FOUND` respectively, a hearing naming an unknown `committee_id` reports `ERR_COMMITTEE_NOT_FOUND`, an enrollment naming an unknown `jurisdiction_id` reports `ERR_JURISDICTION_NOT_FOUND`, a training session naming an unknown `host_jurisdiction_id` reports `ERR_JURISDICTION_NOT_FOUND`, an attendance record naming an unknown `enrollment_id` reports `ERR_ENROLLMENT_NOT_FOUND`, and a ballot or agenda call naming an unknown `proposal_id` reports `ERR_PROPOSAL_NOT_FOUND`.

Path position is also authoritative for ownership. When a child record is created under a parent in the path, the parent link is taken from the path and any competing value in the body is ignored: `code_cycle_id` on a discipline committee, `committee_id` on a committee member, `proposal_id` on an impact analysis or a public comment, `hearing_id` on a vote record, and `training_session_id` on a training enrollment are all derived this way.

Resolving successfully is not the same as being correctly attached. A committee that exists but belongs to a different cycle than the rule under interpretation is reported as `ERR_COMMITTEE_CYCLE_MISMATCH`; a proposal that exists but is not on the hearing's agenda is `ERR_PROPOSAL_NOT_ON_AGENDA`; a ballot naming a member who is not an active voting member of the hearing's committee is `ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE`; an attendance record naming an enrollment that belongs to a different session is `ERR_ENROLLMENT_SESSION_MISMATCH`; and a proposal whose discipline has no live committee in its cycle is `ERR_NO_COMMITTEE_FOR_DISCIPLINE`. All five are 409 conflicts, not 404s.

### 2.7. Numeric Precision and Rounding

Money is carried as integer cents throughout; there is no floating-point currency anywhere in the system. The certified statewide first-cost of an amendment is an exact integer sum of integer products, and the ledger fields that aggregate it are exact integer sums. No money value is ever rounded.

Where a quotient or a weighted score must be stored, rounding is always **round half up**, and the number of decimal places is fixed per field:

- Benefit-cost ratios, both the preliminary and the final variant, are stored to 2 decimal places.
- The discount annuity factor used inside the final benefit-cost ratio is rounded to 6 decimal places *before* it is used as a multiplier — it is an intermediate that is rounded, not a full-precision intermediate.
- The support ratio inside the docket score is rounded to 4 decimal places; the cost points term is rounded to 6 decimal places; the resulting base and adjusted docket scores are rounded to 2 decimal places.
- Both jurisdiction training-compliance percentages, and the population-weighted statewide readiness percentage, are rounded to 2 decimal places.
- Permit counts split across occupancy classes are rounded to 0 decimal places — that is, to whole permits — because a permit is indivisible.

Two places use truncation rather than rounding, and are called out where they occur: the annualization of the approved permit backlog into a review window uses floor division, and both quorum thresholds and the supermajority threshold round *up* to the next whole ballot.

### 2.8. Stale-Read Protection on Two Filing Operations

Exactly two write operations are guarded against acting on a stale read of their parent record, and on each of them the guard field is a required input, not an optional one.

Filing an impact analysis against a proposal — `POST /amendment-proposals/{proposal_id}/impact-analyses` — requires `expected_proposal_version`, carrying the `version` of the `AmendmentProposal` as the client last observed it. If that value does not equal the proposal's current `version`, the request is rejected with `ERR_STALE_PROPOSAL_VERSION` (HTTP 412) and no analysis row is created. The guard matters because a newly accepted analysis of the same type legitimately supersedes the prior one and moves the proposal's analysis dimension; a writer holding an older view of the proposal must re-read before filing.

Filing a local amendment — `POST /local-amendments` — requires `expected_jurisdiction_version`, carrying the `version` of the target `Jurisdiction` as the client last observed it. If that value does not equal the jurisdiction's current `version`, the request is rejected with `ERR_STALE_JURISDICTION_VERSION` (HTTP 412). A jurisdiction's filing set legitimately changes whenever another of its filings is accepted, so the section-uniqueness decision has to be made against a current read.

No other endpoint in this API accepts an expected-version field, and no other endpoint performs a version comparison. Both checks sit at priority 10 of the ladder in §2.5: they outrank state checks on the same request.

### 2.9. Segregation of Duties

Three pairs of steps in this system may never be performed by the same `X-User-ID`, regardless of role. The user recorded in `prepared_by_user_id` when an impact analysis is filed may not be the user who accepts or returns that analysis. The user recorded in `filed_by_user_id` when a rulemaking order is filed may not be the user who publishes it. The user recorded in `drafted_by_user_id` when a formal opinion is drafted may not be the user who publishes it. Each violation is reported as `ERR_SEGREGATION_OF_DUTIES` (409). Switching roles does not launder the identifier: what is compared is `X-User-ID`, not `X-User-Role`.

### 2.10. Conserved Quantities and Cascading Consistency

Several fields in this system are **derived aggregates** rather than stored opinions, and the invariant they satisfy is exact at every instant — never reconciled after the fact, never eventually consistent. Two ledgers are stated as identities that must hold after *every* write that touches them, including every write performed inside a cascade.

The **cycle cost ledger** on a code cycle holds three identities at all times: `approved_incremental_cost_cents` equals the sum of `statewide_incremental_cost_cents` over the cycle's proposals whose `review_status` is `APPROVED`; `approved_permit_backlog_count` equals the sum of `affected_permit_count` over that same set; and `approved_proposal_count` equals the size of that set. When a proposal is approved, its certified figures are added. When an approved proposal is reopened, exactly the figures that were added are subtracted and then cleared on the proposal, leaving no residue — a cycle whose last remaining approval is reopened returns to zero cost, zero backlog and zero approved proposals.

The **session seat ledger** on a training session holds one identity: `seat_capacity` equals `seats_available` plus `enrolled_count` plus `attended_count` plus `no_show_count`. Enrolling adds one to `enrolled_count` and subtracts one from `seats_available`. Marking attendance moves one from `enrolled_count` to `attended_count` and leaves `seats_available` unchanged — the seat stays consumed. Marking a no-show moves one from `enrolled_count` to `no_show_count` and likewise leaves `seats_available` unchanged. Only cancellation releases a seat: it subtracts one from the bucket the enrollment occupied and adds one back to `seats_available`, restoring the identity exactly.

Beyond the ledgers, the system propagates state in both directions across the hierarchy without waiting to be asked. A parent may bubble *down*: abandoning a code cycle dissolves its discipline committees, and withdrawing a published rulemaking order cancels its training sessions, voids its local amendments and declines its pending interpretation requests. A child may bubble *up*: adding or recusing a committee member can seat or un-seat the committee, an approving vote advances the cycle's ledger, and a rulemaking order reaching enforcement adopts the cycle. Every one of these server-initiated mutations is a real mutation of the affected record: it refreshes `updated_at` and increments `version` by one on each record it touches, exactly as a client-initiated write would.

### 2.11. Interval and Boundary Semantics

This domain has several windows, and their boundary conventions deliberately differ. Getting them wrong is the single most common source of off-by-one behavior, so they are collected here.

- A hearing occupies the half-open interval from `scheduled_start` up to but excluding `scheduled_end`.
- A training session occupies the half-open interval from `starts_at` up to but excluding `ends_at`. A session that begins exactly when another ends does **not** overlap it.
- A public comment window runs from `comment_opens_at` inclusive up to `comment_closes_at` **exclusive**. A comment arriving at exactly the closing instant is too late.
- The transition cutoff for permit applications is **inclusive**: an application received at or before `transition_cutoff_date` may still complete under the prior edition.
- The minimum comment period, the hearing notice period, the appeal window and the local-filing window are all **inclusive** at their limit: exactly 30 days of comment period is acceptable, exactly 14 days of hearing notice is acceptable, an appeal arriving exactly 30 days after publication is accepted, and a filing created exactly 90 days after publication is inside the window.
- The buffer that separates two hearings of the same committee is 60 minutes on each side and the comparison is inclusive at 60: a gap of exactly 60 minutes is allowed, a gap of 59 minutes is not, and a back-to-back booking with no gap is not.

## 3. Business Logic & Workflows

### 3.1. Opening a Code Cycle and Seating the Discipline Committees

Work begins when a `CouncilAdmin` opens a **code cycle** for a model code edition. The creating payload carries `cycle_year`, `model_code_edition`, and the two informational dates `intake_opens_at` and `intake_closes_at` that the council publishes to the industry. The pair of `cycle_year` and `model_code_edition` must be unique across all cycles; a repeat is rejected with `ERR_DUPLICATE_CODE_CYCLE`. A new cycle begins in `DRAFT` with every ledger field initialised to zero: `proposal_count`, `approved_proposal_count`, `approved_incremental_cost_cents` and `approved_permit_backlog_count` all start at 0, as does `seated_committee_count`. Note that the declared intake dates are documentation only — the cycle's actual intake state is driven by operator action, not by the clock passing `intake_opens_at`.

A cycle's `status` walks the sequence `DRAFT` → `INTAKE_OPEN` → `INTAKE_CLOSED` → `DELIBERATION` → `RULEMAKING` → `ADOPTED`, with `ABANDONED` available as an early exit. A `CouncilAdmin` drives each step by supplying the desired `to_status`. `ADOPTED` and `ABANDONED` are terminal. Moving `DRAFT` → `INTAKE_OPEN` requires that `seated_committee_count` be at least 1 — that is, that at least one child discipline committee has reached `SEATED` — otherwise the move is refused with `ERR_COMMITTEE_NOT_SEATED`. The `INTAKE_OPEN` → `INTAKE_CLOSED` and `INTAKE_CLOSED` → `DELIBERATION` steps carry no preconditions of their own; closing intake specifically does *not* dispose of proposals still sitting in `SUBMITTED`, which remain `SUBMITTED` and remain screenable afterwards. Each of these status moves increments the cycle's `version` by one.

Entering `RULEMAKING` is a compound gate: every proposal belonging to the cycle must have reached one of `APPROVED`, `REJECTED` or `WITHDRAWN`. If any proposal is still open, the move is refused with `ERR_PROPOSALS_UNRESOLVED`. On success, the cycle recomputes `approved_incremental_cost_cents` and `approved_permit_backlog_count` from a fresh sum over its approved proposals. Abandoning a cycle is only permitted from `DRAFT` or `INTAKE_OPEN`, and only while `proposal_count` is exactly 0; otherwise the same `ERR_PROPOSALS_UNRESOLVED` is returned. Abandonment cascades downward: every child discipline committee, whether `FORMING` or `SEATED`, moves to `DISSOLVED`, and each dissolved committee's `version` increments by one alongside the cycle's.

The cycle can also move *backwards* out of `RULEMAKING`. Because the `RULEMAKING` gate is compound and derived, a proposal leaving `APPROVED` while the cycle sits in `RULEMAKING` invalidates the gate, and the cycle automatically reverts `RULEMAKING` → `DELIBERATION` with its `version` incremented. This is a server-initiated move, not an operator request; §3.6 describes the reopen that triggers it. The forward move `RULEMAKING` → `ADOPTED` is likewise server-initiated: it happens the moment a rulemaking order belonging to this cycle reaches enforcement, as described in §3.7.

Inside a cycle, a `CouncilAdmin` seats one **discipline committee** per technical discipline. The committee payload names the `discipline` — one of `BUILDING`, `STRUCTURAL`, `FIRE_AND_LIFE_SAFETY`, `ENERGY`, `MECHANICAL`, `PLUMBING`, `ELECTRICAL` or `ACCESSIBILITY` — and a `voting_seat_count` between 3 and 12 inclusive that caps how many voting seats the committee may hold. A cycle may hold at most one live committee per discipline; a second attempt is rejected with `ERR_DUPLICATE_COMMITTEE_DISCIPLINE`. A committee is created in `FORMING`, and while it holds no members its `quorum_required` reads 0. Its `status` is never set directly by an operator: `FORMING`, `SEATED` and `DISSOLVED` are all derived, with `DISSOLVED` terminal.

Members are then added one at a time. Each **committee member** carries a `full_name`, a `sector` drawn from `INDUSTRY`, `FIRE_SERVICE`, `LOCAL_JURISDICTION`, `DESIGN_PROFESSIONAL` and `PUBLIC`, an optional `voting_seat` flag that defaults to true, and an optional `is_chair` flag that defaults to false. A member's own `status` is `ACTIVE` on creation and may later become `RECUSED` or `RESIGNED`; the `recusal_reason` field records the reason captured on the most recent recusal and is null until one occurs. Adding a second member with `is_chair` set to true while an `ACTIVE` chair already holds the seat is rejected with `ERR_CHAIR_ALREADY_SEATED`. Adding a member that would push `active_voting_member_count` above the committee's `voting_seat_count` is rejected with `ERR_SEAT_LIMIT_EXCEEDED`.

Four derived fields on the committee are recomputed after every membership change. `active_voting_member_count` counts child members whose `voting_seat` is true and whose `status` is `ACTIVE`. `chair_member_count` counts child members whose `is_chair` is true and whose `status` is `ACTIVE`. `sector_coverage_complete` is true when the committee's `ACTIVE` members between them cover all three of the `INDUSTRY`, `FIRE_SERVICE` and `LOCAL_JURISDICTION` sectors. `quorum_required` is two thirds of `active_voting_member_count`, rounded up to the next whole member.

Those derived figures decide seating. A `FORMING` committee bubbles up to `SEATED` — on the addition of a member, or on the reinstatement of a recused one — as soon as three conditions hold together: `active_voting_member_count` is at least two thirds of `voting_seat_count` rounded up to a whole seat, `sector_coverage_complete` is true, and `chair_member_count` is exactly 1. The reverse is also automatic. A `CouncilAdmin` may recuse or reinstate a member by supplying an `action` of `RECUSE` or `REINSTATE` together with an optional `recusal_reason`; if, after a recusal, `active_voting_member_count` has fallen below two thirds of `voting_seat_count` rounded up, or `sector_coverage_complete` has become false, or `chair_member_count` is no longer exactly 1, the committee un-seats `SEATED` → `FORMING` and its `version` increments. While a committee is `FORMING`, no hearing may be scheduled for it — the attempt is refused with `ERR_COMMITTEE_NOT_SEATED` — and any hearing of that committee still in `SCHEDULED` is automatically `CANCELLED`, its `agenda_proposal_ids` emptied so that the proposals it listed become eligible for a later agenda. Recusal has one further consequence that surfaces much later: because quorum is measured against active voting seats, a recusal shrinks the quorum denominator for every subsequent ballot.

### 3.2. Amendment Intake, Routing and Staff Screening

Once a cycle is accepting intake, a proposed state amendment may be submitted by a `CouncilAdmin`, `TechnicalStaff`, a `JurisdictionOfficial` or a `Petitioner`. The payload names the `code_cycle_id` the amendment is proposed into, the `code_section` of the model code it edits (for example `C402.1.4`), the `discipline` it falls under, a short `title`, the verbatim `proposed_text`, a `stringency_direction` of `MORE_STRINGENT`, `LESS_STRINGENT`, `NEUTRAL` or `CLARIFYING`, and the `proposer_sector` identifying who is asking. The server records the submitter's identifier in `submitted_by_user_id` and increments the cycle's `proposal_count` by one. Intake requires the parent cycle to be in `INTAKE_OPEN`; a submission against a cycle in any other status is refused with `ERR_CYCLE_STATE_INVALID`.

Routing is server-side and not negotiable. The proposal's `committee_id` is resolved by finding the discipline committees of the named cycle whose own `discipline` equals the proposal's `discipline` and whose `status` is anything other than `DISSOLVED`. Because a cycle holds at most one live committee per discipline, that search yields at most one candidate, and its `id` becomes the proposal's `committee_id`. If no such committee exists, the submission is rejected outright with `ERR_NO_COMMITTEE_FOR_DISCIPLINE`. A `committee_id` supplied by the client is ignored entirely.

A proposal carries **two independent status dimensions on the same row**, and understanding their independence is essential. The first dimension, `review_status`, tracks the proposal's position in the review pipeline and takes the values `SUBMITTED`, `SCREENED`, `COMMENT_OPEN`, `COMMENT_CLOSED`, `APPROVED`, `REJECTED`, `RETURNED_FOR_REVISION` and `WITHDRAWN`, of which `REJECTED` and `WITHDRAWN` are terminal. The second dimension, `analysis_status`, tracks how complete the impact analysis is and takes the values `NOT_STARTED`, `PENDING`, `PARTIAL`, `COMPLETE` and `STALE`. A new proposal starts at `SUBMITTED` on the first dimension and `NOT_STARTED` on the second. The two dimensions advance on different triggers and are coupled at only two points: opening a comment window and recording an approving vote both require `analysis_status` to be `COMPLETE`.

Screening is the work of `TechnicalStaff`, who submit a `decision` of `ACCEPT_FOR_ANALYSIS`, `REJECT` or `WITHDRAW`. Accepting a `SUBMITTED` proposal for analysis advances `review_status` `SUBMITTED` → `SCREENED` and, in the same call, advances the second dimension `NOT_STARTED` → `PENDING`. The same call also fixes `energy_analysis_required`, which is true when the proposal's `discipline` is `ENERGY` or its `stringency_direction` is `MORE_STRINGENT`, and false otherwise. Rejecting at screening moves `review_status` `SUBMITTED` → `REJECTED` and leaves `analysis_status` at `NOT_STARTED`. Withdrawing moves `review_status` `SUBMITTED` → `WITHDRAWN`. Screening a `SUBMITTED` proposal requires the parent cycle to be in `INTAKE_OPEN` or `INTAKE_CLOSED`; withdrawal additionally tolerates a cycle in `DELIBERATION`. Screening a proposal that has come back around as `RETURNED_FOR_REVISION` — the revision loop — moves it `RETURNED_FOR_REVISION` → `SCREENED` and simultaneously moves the analysis dimension `STALE` → `PENDING`; that screening is permitted while the cycle is in `INTAKE_OPEN`, `INTAKE_CLOSED` or `DELIBERATION`. A cycle outside the permitted set for the requested decision yields `ERR_CYCLE_STATE_INVALID`; a proposal whose own `review_status` does not admit the decision — including any attempt on a terminal `REJECTED` or `WITHDRAWN` proposal, or a repeat of a decision already taken — yields `ERR_PROPOSAL_STATE_INVALID`. Every screening decision increments the proposal's `version` by one.

The proposal row also carries the certified and derived numbers that later stages fill in, all of them null or zero to start: `affected_permit_count`, `statewide_incremental_cost_cents`, `preliminary_benefit_cost_ratio` and `final_benefit_cost_ratio` begin null; `support_comment_count`, `oppose_comment_count`, `total_comment_count`, `comment_extension_count`, `comment_round` and `revision_round` begin at 0; `comment_window_status` begins at `NONE`; `comment_opens_at`, `comment_closes_at`, `base_docket_score`, `docket_queue_rank` and `docket_priority_score` begin null.

### 3.3. Impact Analysis: Certifying Cost and Energy Effect

Analysis is prepared by `TechnicalStaff` against a screened proposal and reviewed by a `CouncilAdmin`. Two kinds exist, distinguished by `analysis_type`: a `COST_BENEFIT` analysis and an `ENERGY_IMPACT` analysis.

A `COST_BENEFIT` filing must supply `incremental_cost_by_occupancy`, `affected_permit_count`, `annual_cost_savings_cents` and `measure_life_years`. The first is a map from occupancy class to the incremental first cost, in cents, that the amendment adds per permit in that class; its keys must be drawn from the four recognized occupancy classes `R3`, `R2`, `B` and `A2`, and an unrecognized key is a request-shape failure. `affected_permit_count` is the annual statewide count of permits the amendment touches and must be at least 0; `annual_cost_savings_cents` is the annual statewide operating saving in cents and must be at least 0; `measure_life_years` is the analyst's measure life and must fall between 1 and 40 inclusive. An `ENERGY_IMPACT` filing instead supplies `annual_energy_savings_kwh`, the annual statewide kilowatt-hours saved, and `energy_delta_pct`, the modelled whole-building energy change in percent where a negative number means savings. Omitting a field required for the declared `analysis_type` is rejected with `ERR_INVALID_REQUEST`. Every filing also carries `expected_proposal_version` as described in §2.8, and the filing increments the parent proposal's `version` by one on success.

Each analysis row records `prepared_by_user_id` from the filer's identifier, starts in `status` `SUBMITTED`, and leaves `reviewed_by_user_id` null until it is reviewed. An analysis row's `status` may become `ACCEPTED`, `RETURNED` or `SUPERSEDED`; `RETURNED` and `SUPERSEDED` are terminal. A `COST_BENEFIT` filing also computes its own `statewide_incremental_cost_cents` on the analysis row at filing time; that field stays null on an `ENERGY_IMPACT` row.

**Certifying the statewide first cost.** The rollup that produces `statewide_incremental_cost_cents` treats permits as indivisible, and the order of operations is what makes the number reproducible. The annual permit population is first split into whole permits per occupancy class, and only then multiplied by that class's per-permit cost. The four classes are visited in the fixed order `R3`, `R2`, `B`, `A2`, and each class has a fixed share of the statewide permit population: 62 percent for `R3`, 18 percent for `R2`, 12 percent for `B` and 8 percent for `A2`. For each class in that order, the class's whole-permit count is `affected_permit_count` multiplied by that class's share, rounded half up to a whole permit; the per-permit cost is the integer cents recorded for that class in `incremental_cost_by_occupancy`, taken as zero if the class is absent from the map; and the class's contribution is the exact integer product of the two. The certified total is the sum of the four contributions, expressed in integer cents with no further rounding. No residual reconciliation is performed: the four rounded per-class permit counts are allowed to sum to something other than `affected_permit_count`, and the certified cost is nonetheless the plain sum of the exact per-class products. Rounding the money instead of the permits, or leaving fractional permits in the multiplication, both produce a different and incorrect answer.

**Reviewing an analysis.** A `CouncilAdmin` submits a `decision` of `ACCEPT` or `RETURN`. Either way, the reviewer's identifier is stored in `reviewed_by_user_id` and the analysis's `version` increments. The reviewer may not be the preparer: an acting identifier equal to `prepared_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Review is only possible while the analysis is still `SUBMITTED`; an already accepted, returned or superseded row yields `ERR_ANALYSIS_STATE_INVALID`. Review also requires the parent proposal's `review_status` to be one of `SCREENED`, `COMMENT_OPEN` or `COMMENT_CLOSED`; anything else is `ERR_PROPOSAL_STAGE_INVALID`. Returning an analysis moves it `SUBMITTED` → `RETURNED` and leaves the parent's `analysis_status` untouched. Accepting moves it `SUBMITTED` → `ACCEPTED`, and any *other* analysis of the same proposal with the same `analysis_type` that was `ACCEPTED` moves `ACCEPTED` → `SUPERSEDED`, its own `version` incrementing as it goes.

Acceptance is what drives the second status dimension. The first accepted analysis moves the proposal `PENDING` → `PARTIAL`, except in one case: when `energy_analysis_required` is false and the accepted analysis is the `COST_BENEFIT` one, the proposal jumps straight to `COMPLETE`, because no energy analysis is owed. When a `COST_BENEFIT` analysis is accepted, the proposal absorbs its figures: `statewide_incremental_cost_cents` is computed onto the proposal, `affected_permit_count` is copied across from the analysis, and `preliminary_benefit_cost_ratio` is computed. The move `PARTIAL` → `COMPLETE` happens when the second required analysis type is accepted — formally, when an `ACCEPTED` `COST_BENEFIT` analysis exists and, if `energy_analysis_required` is true, an `ACCEPTED` `ENERGY_IMPACT` analysis exists as well. Each of these dimension-two moves increments the proposal's `version` by one and touches `review_status` not at all.

**The two benefit-cost ratios.** Both ratios are computed over the same stored data and differ only in how future savings are valued. The **preliminary** ratio, recorded on `preliminary_benefit_cost_ratio` at the moment the `COST_BENEFIT` analysis is accepted, uses a flat statutory horizon of 15 years with no discounting: it is `annual_cost_savings_cents` multiplied by 15, divided by the proposal's certified `statewide_incremental_cost_cents`, rounded half up to 2 decimal places. The discount rate and the analyst's measure life play no part in it, and it is never used as a gate. The **final** ratio, recorded on `final_benefit_cost_ratio`, discounts the savings stream over the analyst's own `measure_life_years` at the state discount rate of 3 percent per year. Its annuity factor is one minus the quantity one-plus-the-rate raised to the power of the negated `measure_life_years`, all divided by the rate, rounded half up to 6 decimal places; that rounded factor is then used as the multiplier. The final ratio is `annual_cost_savings_cents` multiplied by the rounded annuity factor, divided by `statewide_incremental_cost_cents`, rounded half up to 2 decimal places. Only the final ratio is ever tested against the statutory floor of 1.00, and the comparison is made on the rounded 2-decimal value, so a raw result of 0.995032 rounds to 1.00 and passes while 0.990021 rounds to 0.99 and fails. When the certified `statewide_incremental_cost_cents` is exactly 0, both ratios are null and the floor test is skipped entirely — a zero-cost amendment is never blocked on cost-effectiveness. The final ratio is recomputed fresh at the moment of the committee vote, as §3.5 describes.

### 3.4. Public Comment Periods and Docket Priority

A `CouncilAdmin` controls the public comment period for a screened proposal by submitting an `action` of `OPEN`, `EXTEND` or `CLOSE`, together with `opens_at` and `closes_at` when opening a window.

Opening a window advances `review_status` `SCREENED` → `COMMENT_OPEN`, and three preconditions guard it. The proposal's `analysis_status` must be `COMPLETE`, or the request is refused with `ERR_ANALYSIS_INCOMPLETE` — this is the first of the two couplings between the status dimensions. The parent cycle must be in `INTAKE_CLOSED` or `DELIBERATION`, or the request is refused with `ERR_CYCLE_STATE_INVALID`. And the requested window must span at least 30 days from `opens_at` to `closes_at`, inclusive at the boundary: exactly 30 days is accepted, 29 days and 23 hours 59 minutes 59 seconds is not, and a short window is refused with `ERR_COMMENT_PERIOD_TOO_SHORT`. On success the proposal's `comment_window_status` moves from `NONE` or `CLOSED` to `OPEN`, `comment_opens_at` and `comment_closes_at` are set from the request, `comment_round` increments by one, `comment_extension_count` resets to 0, and the three tallies `support_comment_count`, `oppose_comment_count` and `total_comment_count` reset to 0 for the fresh round.

An extension pushes `comment_closes_at` 30 days further out and increments `comment_extension_count` by one. At most two extensions may be granted in a round: an extension requested when `comment_extension_count` has already reached 2 is refused with `ERR_COMMENT_EXTENSIONS_EXHAUSTED`.

While the window is open, a comment may be submitted by a `CouncilAdmin`, `TechnicalStaff`, a `JurisdictionOfficial` or a `Petitioner`. The payload carries the `commenter_sector`, a `position` of `SUPPORT`, `OPPOSE` or `NEUTRAL`, and the `body` text. The server stamps `submitted_by_user_id`, sets `received_at` from the logical clock, and snapshots the proposal's current `comment_round` onto the comment so that later tallies can distinguish rounds. A comment is accepted only when the clock stands at or after `comment_opens_at` and strictly before `comment_closes_at`, and only while `comment_window_status` is `OPEN`; a comment arriving outside that half-open range — including one arriving at exactly `comment_closes_at` — or arriving when the window is not open, is refused with `ERR_COMMENT_WINDOW_CLOSED`. Each accepted comment refreshes the three tallies, which count only comments whose `comment_round` matches the proposal's current `comment_round`.

Closing the window advances `review_status` `COMMENT_OPEN` → `COMMENT_CLOSED` and may only be requested once the clock has reached `comment_closes_at`; an early close is refused with `ERR_COMMENT_WINDOW_STILL_OPEN`. On close, `comment_window_status` becomes `CLOSED`, the three tallies are recomputed for the current round, and the proposal's `base_docket_score` is computed and frozen.

**The base docket score.** The score is a weighted blend of three signals, each scaled to a 0-to-1 term, combined with fixed weights and expressed on a 100-point scale. The first term is the support ratio: the decisive comment count is `support_comment_count` plus `oppose_comment_count`, with `NEUTRAL` comments deliberately excluded; when that decisive count is 0 the support ratio takes the neutral default of 0.5000, and otherwise it is `support_comment_count` divided by the decisive count, rounded half up to 4 decimal places. The second term is a stringency award taken from a fixed table: 1.00 for `MORE_STRINGENT`, 0.60 for `NEUTRAL`, 0.40 for `CLARIFYING` and 0.20 for `LESS_STRINGENT`. The third term rewards cheapness: the cost ratio is 1 when `statewide_incremental_cost_cents` is null, and otherwise the lesser of 1 and `statewide_incremental_cost_cents` divided by the two-million-dollar cost cap of 200,000,000 cents; the cost points are 1 minus that ratio, rounded half up to 6 decimal places. `base_docket_score` is then 0.45 times the support ratio plus 0.35 times the stringency award plus 0.20 times the cost points, the whole sum multiplied by 100 and rounded half up to 2 decimal places. Once frozen at close, the base score does not move again unless a fresh comment round closes.

**The rank bonus.** The second half of the docket score is applied later, when a hearing agenda is built. The eligible pool is ordered by `base_docket_score` descending, ties broken by `created_at` ascending, and each selected proposal's 1-indexed position in that order becomes its `docket_queue_rank`. The rank adjustment is 5.00 for rank 1, 2.00 for rank 2, and 0.00 for every other rank; `docket_priority_score` is `base_docket_score` plus that adjustment, rounded half up to 2 decimal places. Critically, the ranking is always computed from the *base* score, never from an already-adjusted score, so the bonus can never feed back into the ordering.

### 3.5. Hearings: Agenda, Quorum and the Vote Record

A `CouncilAdmin` schedules a **hearing** for a committee by supplying the `committee_id` together with `scheduled_start` and `scheduled_end`. The end must be strictly later than the start. The committee must be `SEATED`, or scheduling is refused with `ERR_COMMITTEE_NOT_SEATED`. The hearing must be noticed at least 14 days ahead: `scheduled_start` must be at or after the clock's current instant plus 14 days, and exactly 14 days is acceptable; a shorter notice is refused with `ERR_HEARING_NOTICE_TOO_SHORT`. The requested interval, padded by 60 minutes on each side, must not overlap another `SCHEDULED` or `CONVENED` hearing of the same committee; an overlap is refused with `ERR_HEARING_TIME_CONFLICT`. A new hearing starts in `SCHEDULED` with an empty `agenda_proposal_ids`, and its `present_member_ids`, `present_voting_count`, `quorum_required_at_convene`, `convened_at` and `adjourned_at` all null. A hearing's `status` may reach `CONVENED`, `ADJOURNED` or `CANCELLED`, of which `ADJOURNED` and `CANCELLED` are terminal.

**Building the agenda.** A `CouncilAdmin` fills the agenda by supplying a `mode` of `AUTO_FILL`. The eligible pool consists of the proposals routed to this hearing's committee — those whose `committee_id` equals the hearing's committee and whose `code_cycle_id` equals that committee's own `code_cycle_id` — whose `review_status` is `COMMENT_CLOSED` and whose `analysis_status` is `COMPLETE`, and which are not already listed on the agenda of any *other* hearing whose `status` is `SCHEDULED` or `CONVENED`. A proposal may sit on only one live agenda at a time; a hearing that is `CANCELLED` or `ADJOURNED` releases its listed items back to the pool. If the pool comes up empty, the request is refused with `ERR_NO_ELIGIBLE_PROPOSALS`. Otherwise the pool is ordered by `base_docket_score` descending with `created_at` ascending as the tie-break, and the first 8 identifiers of that order become `agenda_proposal_ids`, preserving that order. The rank bonus described in §3.4 is then applied over the selected items only, setting each one's `docket_queue_rank` and `docket_priority_score`. Filling the agenda after a hearing has convened, or on a cancelled hearing, is refused with `ERR_HEARING_STATE_INVALID`.

**Convening.** The presiding `CouncilChair` convenes the hearing, supplying `present_member_ids` — the identifiers of the committee members recorded present. Four conditions must hold. The clock must stand at or after `scheduled_start`, or the attempt is refused with `ERR_HEARING_NOT_STARTED`. `agenda_proposal_ids` must be non-empty, or the attempt is refused with `ERR_AGENDA_EMPTY`. The count of supplied identifiers that are `ACTIVE` voting members of this hearing's committee — recorded as `present_voting_count` — must be at least the committee's current `quorum_required`, or the attempt is refused with `ERR_QUORUM_NOT_MET`. And the committee must still be `SEATED`, or the attempt is refused with `ERR_COMMITTEE_NOT_SEATED`. On success the hearing moves `SCHEDULED` → `CONVENED`, `present_voting_count` and a snapshot of the committee's `quorum_required` in `quorum_required_at_convene` are stored, `convened_at` is stamped from the clock, and `version` increments. Convening twice, or convening a cancelled hearing, is refused with `ERR_HEARING_STATE_INVALID`.

**Recording a ballot.** With the hearing `CONVENED`, the chair records one immutable **vote record** per agenda item, supplying the `proposal_id` being voted on and a `ballots` array. Each entry in `ballots` names a `member_id` and that member's `ballot`, one of `YES`, `NO` or `ABSTAIN`. The proposal must be listed in `agenda_proposal_ids`, or the call is refused with `ERR_PROPOSAL_NOT_ON_AGENDA`; the hearing must be `CONVENED`, or `ERR_HEARING_STATE_INVALID`; every `member_id` must be an `ACTIVE` voting member of the hearing's committee, or `ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE`; no `member_id` may appear twice in one `ballots` array, or `ERR_DUPLICATE_BALLOT`; and only one vote record may exist per hearing-and-proposal pairing, a repeat being refused with `ERR_DUPLICATE_VOTE_RECORD`. The proposal's `analysis_status` must still be `COMPLETE` — the second of the two dimension couplings — or the call is refused with `ERR_ANALYSIS_INCOMPLETE`.

Two substantive gates then apply, in this order. First, an approving vote may not relax a life-safety section: if the proposal's `stringency_direction` is `LESS_STRINGENT` and its `code_section` begins with either `9` or `10`, the call is refused with `ERR_STRINGENCY_FLOOR_VIOLATION`. Second, the final benefit-cost ratio is recomputed from scratch — by the discounted-annuity method of §3.3, on the proposal's currently certified figures — and if the rounded 2-decimal result is below 1.00 the call is refused with `ERR_BENEFIT_COST_BELOW_FLOOR`. When both apply, the life-safety refusal is the one reported. Recomputation happens *before* the outcome branches are evaluated, and the value that results is written both to the proposal's `final_benefit_cost_ratio` and to the vote record's `final_benefit_cost_ratio_at_vote`.

**Tallying.** The tally distinguishes two denominators, and conflating them is the classic error. Quorum is measured against *seats*: `voting_seats_at_call` is the committee's `active_voting_member_count` at the moment of the call, so members who are `RECUSED` or `RESIGNED` shrink that denominator. The vote record's own `quorum_required` is two thirds of `voting_seats_at_call`, rounded up to the next whole member. `yes_count`, `no_count` and `abstain_count` are the counts of `YES`, `NO` and `ABSTAIN` ballots; the cast total is their sum; and `absent_count` is `voting_seats_at_call` less that cast total. If the cast total falls short of the record's `quorum_required`, the call is refused with `ERR_QUORUM_NOT_MET` and **no vote record row is created at all**.

The supermajority, by contrast, is measured against *ballots cast for or against*: the decisive total is `yes_count` plus `no_count`, with abstentions excluded, even though abstentions did count toward quorum. The supermajority requirement is 60 percent of the decisive total, rounded up to the next whole ballot. The `outcome` and its `outcome_reason` are then decided by four ordered branches, the first matching branch winning:

1. If the proposal's `stringency_direction` is `LESS_STRINGENT` and at least one `NO` ballot was cast by a member whose `sector` is `FIRE_SERVICE`, the `outcome` is `REJECTED` with `outcome_reason` `FIRE_SERVICE_VETO`. The fire service holds this veto over any relaxation, whatever the arithmetic says.
2. Otherwise, if `yes_count` is less than or equal to `no_count`, the `outcome` is `REJECTED` with `outcome_reason` `SIMPLE_MAJORITY_FAILED`.
3. Otherwise, if `yes_count` is less than the supermajority requirement, the `outcome` is `REJECTED` with `outcome_reason` `SUPERMAJORITY_FAILED`.
4. Otherwise the `outcome` is `APPROVED` with `outcome_reason` `MAJORITY_APPROVED`.

The chair's identifier is stored in `recorded_by_user_id`. An `APPROVED` outcome advances the proposal `COMMENT_CLOSED` → `APPROVED` and synchronises the cycle ledger: the proposal's `statewide_incremental_cost_cents` is added to the cycle's `approved_incremental_cost_cents`, its `affected_permit_count` is added to the cycle's `approved_permit_backlog_count`, and the cycle's `approved_proposal_count` increases by one. Both the proposal's `version` and the cycle's `version` increment. A `REJECTED` outcome advances the proposal `COMMENT_CLOSED` → `REJECTED`, creates the vote record with one of the three failure reasons, leaves the cycle's `approved_incremental_cost_cents` untouched, and increments only the proposal's `version`.

**Adjourning.** The chair adjourns a `CONVENED` hearing, moving it `CONVENED` → `ADJOURNED` and stamping `adjourned_at`. Agenda items still sitting in `COMMENT_CLOSED` because they were never voted on are left exactly as they are and become eligible for a later hearing's agenda. Adjourning a hearing that is not `CONVENED` is refused with `ERR_HEARING_STATE_INVALID`.

### 3.6. Reopening an Amendment and the Compensating Cascade

Occasionally an amendment must go back for redrafting after its comment period has closed, or even after it has been approved. A `CouncilAdmin` reopens it by supplying a `reason`. This is the deepest cascade in the system, and it is worth walking through level by level, because every level is a real mutation that increments the `version` of the record it touches.

Reopening is permitted from `COMMENT_CLOSED` and from `APPROVED`, and in both cases the parent cycle must be in `DELIBERATION` or `RULEMAKING`, otherwise the request is refused with `ERR_CYCLE_STATE_INVALID`. Reopening from `APPROVED` carries one additional gate: no rulemaking order of the cycle may have reached `FILED`, `PUBLISHED` or `EFFECTIVE`, because those states have already pinned the approval; a reopen attempted against a filed, published or effective order is refused with `ERR_ADOPTION_RULE_STATE_INVALID`. Reopening a proposal whose `review_status` is anything else is refused with `ERR_PROPOSAL_STATE_INVALID`.

At the first level, the proposal moves to `RETURNED_FOR_REVISION`, `revision_round` increments by one, and the analysis dimension moves `COMPLETE` → `STALE`. At the second level, because the analysis has gone stale, every child analysis of that proposal whose `status` is `ACCEPTED` moves `ACCEPTED` → `SUPERSEDED`; an analysis still sitting in `SUBMITTED` when its parent is reopened likewise moves `SUBMITTED` → `SUPERSEDED`, since there is nothing left for it to describe. At the third level, because no `ACCEPTED` analysis remains, the proposal's `statewide_incremental_cost_cents`, `affected_permit_count`, `preliminary_benefit_cost_ratio` and `final_benefit_cost_ratio` are all cleared back to null.

A reopen from `COMMENT_CLOSED` stops there, because a proposal that was never approved never contributed to the cycle ledger. A reopen from `APPROVED` continues. At the fourth level, because the certified cost has been cleared, the cycle ledger is compensated by exactly the figures that were once added: the cleared `statewide_incremental_cost_cents` is subtracted from the cycle's `approved_incremental_cost_cents`, the cleared `affected_permit_count` is subtracted from `approved_permit_backlog_count`, and `approved_proposal_count` decreases by one. The compensation must leave no residue — a cycle whose last remaining approval is reopened reads zero on all three. At the fifth level, because the cycle's approved backlog has changed, every rulemaking order of that cycle still in `DRAFT` recomputes its whole schedule — `projected_permit_backlog`, `transition_grace_days`, `notice_days`, `effective_date`, `transition_cutoff_date` and `prior_code_expiry_date` — while its `base_date` stays exactly where it was. At the sixth level, because the compound gate that admitted the cycle to `RULEMAKING` no longer holds, the cycle reverts `RULEMAKING` → `DELIBERATION`.

The revision loop then closes: a screening decision of `ACCEPT_FOR_ANALYSIS` takes the proposal `RETURNED_FOR_REVISION` → `SCREENED` and its analysis dimension `STALE` → `PENDING`, and the proposal walks the pipeline again — fresh analyses, a fresh comment round, a fresh vote — potentially arriving back at `APPROVED`.

### 3.7. Adoption Rulemaking: Schedule, Publication, Enforcement and Withdrawal

Once a cycle's deliberation is finished, a `CouncilAdmin` drafts the **rulemaking order** that adopts the amended edition, supplying the `code_cycle_id` and a `title`. The order is created in `DRAFT`, and its entire calendar is computed immediately from the cycle's current approved permit backlog. Its `status` may later become `FILED`, `PUBLISHED`, `EFFECTIVE`, `WITHDRAWN` or `SUPERSEDED`; `WITHDRAWN` and `SUPERSEDED` are terminal.

**The transition schedule.** Three different families of arithmetic are chained here, and each has its own rounding discipline. First, `base_date` is the order's `created_at` truncated to midnight UTC, and it is never recomputed after creation — it is the fixed anchor for all schedule arithmetic. Second, the cycle's `approved_permit_backlog_count`, which is an annual figure, is annualized down to the statutory provisional review window of 60 days: `projected_permit_backlog` is the approved backlog multiplied by 60 and divided by 365, with the result taken down to the next lower whole permit by floor division. The annualization always uses the 60-day provisional window, never the notice period this same calculation goes on to produce. Third, `projected_permit_backlog` selects a transition grace tier by lookup: `transition_grace_days` is 90 days when the projected backlog is below 500, 180 days when it is below 5,000, and 365 days otherwise. Fourth, `notice_days` clamps that tier up to the statutory minimum of 120 days — it is the greater of 120 and `transition_grace_days` — so only a medium or large tier ever escapes the 120-day floor. `effective_date` is then `base_date` advanced by `notice_days` whole days, expressed at midnight UTC, and this is the instant enforcement begins. `transition_cutoff_date` equals `effective_date` exactly, and its boundary is inclusive: a permit application received at or before that instant may complete under the prior edition. `prior_code_expiry_date` is `effective_date` advanced by a further 365 whole days, and is the last day a project already in review may use the prior edition. Because a `DRAFT` order's schedule tracks the cycle, it is recomputed from scratch whenever the cycle's `approved_permit_backlog_count` changes — including under the reopen cascade of §3.6.

**Filing.** A `CouncilAdmin` files the order by supplying a `to_status` of `FILED`. The parent cycle must be in `RULEMAKING`, or the request is refused with `ERR_CYCLE_STATE_INVALID`, and the cycle's `approved_proposal_count` must be at least 1, or it is refused with `ERR_NO_APPROVED_AMENDMENTS`. Filing freezes the record against further drift in three ways. It pins versions: `pinned_amendment_versions` becomes a map from each `APPROVED` proposal's `id` to that proposal's `version` at this instant. It freezes money: `approved_incremental_cost_cents_at_filing` captures the cycle's `approved_incremental_cost_cents` as it stands. And the schedule fields stop recomputing — a filed order's dates never move again. The filer's identifier is stored in `filed_by_user_id`.

**Publication.** Publication moves the order `FILED` → `PUBLISHED` and requires a *different* `CouncilAdmin` identifier: an acting identifier equal to `filed_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. On success the publisher's identifier is stored in `published_by_user_id` and `published_at` is stamped from the logical clock. That instant is load-bearing downstream: it anchors both the 90-day local-filing window of §3.8 and the 30-day appeal window on formal opinions.

**Enforcement.** Moving `PUBLISHED` → `EFFECTIVE` is what actually begins enforcement, and it has two gates. The clock must have reached `effective_date`, or the request is refused with `ERR_EFFECTIVE_DATE_NOT_REACHED`. And statewide training readiness must have reached the threshold of 80.00 percent, or the request is refused with `ERR_TRAINING_READINESS_NOT_MET`. Statewide readiness is a population-weighted average computed over **every** registered jurisdiction with no filter whatsoever — including a jurisdiction registered moments earlier that has done no training at all — because enforcement begins statewide. Formally: if there are no jurisdictions, or the sum of their `population` values is 0, statewide readiness is 0.00; otherwise it is the sum over all jurisdictions of `population` multiplied by that jurisdiction's `compliance_pct_attendance_basis`, divided by the sum of all `population` values, rounded half up to 2 decimal places, with the individual products kept at full precision before the division. If the result is below 80.00 the transition fails; otherwise the value is snapshotted onto `statewide_readiness_pct_at_effective`. Going effective also supersedes rivals — every *other* rulemaking order of the same cycle whose `status` is `EFFECTIVE` moves `EFFECTIVE` → `SUPERSEDED` — and bubbles up to the cycle, taking it `RULEMAKING` → `ADOPTED`. Both the order's and the cycle's `version` increment.

**Withdrawal.** An order may be withdrawn from `FILED` or from `PUBLISHED`, with the reason captured in `withdrawal_reason`. Withdrawing a `FILED` order is quiet: it records the reason and increments `version`, and nothing else moves, because nothing downstream has yet attached to it. Withdrawing a `PUBLISHED` order is the most far-reaching operation in the system, because publication has already licensed local filings, interpretation requests and training delivery.

The training chain runs five levels deep. At level two, every training session whose `adoption_rule_id` is this order and whose `status` is `SCHEDULED`, `ENROLLMENT_OPEN`, `ENROLLMENT_CLOSED` or `DELIVERED` moves to `CANCELLED` — note that even a `DELIVERED` session is cancelled, because training delivered on an edition that was withdrawn no longer counts for anything. At level three, because those sessions were cancelled, every enrollment on them whose `status` is `ENROLLED`, `ATTENDED` or `NO_SHOW` moves to `CANCELLED`, each session's `seats_available` returns to its full `seat_capacity`, and `enrolled_count`, `attended_count` and `no_show_count` all return to 0. At level four, because those enrollments were cancelled, every jurisdiction that had an affected enrollment recomputes both `compliance_pct_enrollment_basis` and `compliance_pct_attendance_basis` — both falling to 0.00 when the withdrawn order carried all of that jurisdiction's training. At level five, because the recomputed `compliance_pct_attendance_basis` has fallen below 80.00, that jurisdiction's `enforcement_readiness` moves to `NOT_READY`.

Two further fan-outs run alongside that chain rather than inside it. Every local amendment whose `adoption_rule_id` is this order and whose `status` is `SUBMITTED`, `UNDER_REVIEW`, `RETURNED` or `FILED_EFFECTIVE` moves to `VOIDED`, and each affected jurisdiction's `effective_local_amendment_count` is recomputed. And every interpretation request whose `adoption_rule_id` is this order and whose `status` is `SUBMITTED`, `ASSIGNED` or `OPINION_DRAFTED` moves to `DECLINED` with `decline_reason` set to `underlying rule withdrawn`. The order's own `version` increments, as does the `version` of every child the withdrawal touched.

### 3.8. Local Amendment Authority and Formal Interpretations

**Registering a jurisdiction.** A `CouncilAdmin` registers each local building department with a `name` that must be unique statewide — a repeat is refused with `ERR_DUPLICATE_JURISDICTION` — a resident `population`, a `local_authority_level` of `FULL`, `LIMITED` or `NONE` describing how much local-amendment authority the state has delegated to it, a `host_seat_capacity` giving the total training seats it can host at any one instant, and an `official_headcount` of at least 1 giving the number of building officials who must be trained before enforcement. A new jurisdiction starts with both `compliance_pct_enrollment_basis` and `compliance_pct_attendance_basis` at 0, `enforcement_readiness` at `NOT_READY`, and `effective_local_amendment_count` at 0. Because statewide readiness is population-weighted over every jurisdiction with no filter, registering a large untrained jurisdiction immediately drags statewide readiness down and can block an otherwise-ready order from taking effect.

**Filing a local amendment.** A `JurisdictionOfficial` files a local amendment against a state rulemaking order, supplying `expected_jurisdiction_version` (see §2.8), the `jurisdiction_id` — which must equal the acting `X-User-ID`, or the filing is refused with `ERR_JURISDICTION_MISMATCH` — the `adoption_rule_id` being modified, the `code_section` amended locally, the `local_text`, a `stringency_direction` of `MORE_STRINGENT`, `NEUTRAL`, `CLARIFYING` or `LESS_STRINGENT`, and a `justification` recording the local findings. A jurisdiction whose `local_authority_level` is `NONE` cannot file at all: the attempt is refused with `ERR_LOCAL_AUTHORITY_ABSENT`, and that refusal outranks the duplicate-section check. Within one jurisdiction and one rulemaking order, a given `code_section` may be the subject of only one live filing: a second filing for the same triple is refused with `ERR_DUPLICATE_LOCAL_AMENDMENT`. The uniqueness scope is deliberately narrow — rows whose `status` is `REJECTED` or `VOIDED` do not occupy their section, so a rejected filing frees the section for another attempt. The filing starts in `SUBMITTED` with `revision_round` at 0, `reviewed_by_user_id` null, and `filed_within_window` evaluated on the spot: it is true when the filing's `created_at` is at or before the order's `published_at` plus 90 days, inclusive at the boundary. Filing increments the target jurisdiction's `version` by one. A local filing's `status` may reach `UNDER_REVIEW`, `RETURNED`, `FILED_EFFECTIVE`, `REJECTED` or `VOIDED`, of which the last three are terminal.

**Council review of a local filing.** A `CouncilAdmin` submits a `decision` of `START_REVIEW`, `ACCEPT`, `RETURN` or `REJECT`. Starting review moves the filing `SUBMITTED` → `UNDER_REVIEW`, stores `reviewed_by_user_id`, and requires the referenced rulemaking order to be `PUBLISHED` or `EFFECTIVE` — an order that is not in force yields `ERR_ADOPTION_RULE_NOT_IN_FORCE`. From `UNDER_REVIEW`, three outcomes are available. Accepting moves the filing `UNDER_REVIEW` → `FILED_EFFECTIVE` and increments the jurisdiction's `effective_local_amendment_count` by one along with the jurisdiction's `version`, but only if three conditions hold: the `stringency_direction` must not be `LESS_STRINGENT`, since delegated local authority may only tighten or clarify the state code and never relax it, or the acceptance is refused with `ERR_LOCAL_LESS_STRINGENT_FORBIDDEN`; `filed_within_window` must be true, or it is refused with `ERR_LOCAL_FILING_DEADLINE_PASSED`; and the jurisdiction's `local_authority_level` must be `FULL` or `LIMITED`, or it is refused with `ERR_LOCAL_AUTHORITY_ABSENT`. The stringency limit is checked at acceptance, not at intake — a `LESS_STRINGENT` filing is admitted into the queue and stopped at the decision point. Returning moves the filing `UNDER_REVIEW` → `RETURNED`; rejecting moves it `UNDER_REVIEW` → `REJECTED`, which is terminal and frees the section. A decision that the filing's own `status` does not admit is refused with `ERR_LOCAL_AMENDMENT_STATE_INVALID`.

**Resubmitting.** The owning `JurisdictionOfficial` — and only that one, or `ERR_JURISDICTION_MISMATCH` follows — may resubmit a `RETURNED` filing, supplying replacement `local_text`, `stringency_direction` and `justification`. Resubmission moves the filing `RETURNED` → `SUBMITTED`, increments `revision_round` by one, replaces the three supplied fields, and re-evaluates `filed_within_window` against the clock's *current* instant — so a filing that lingers in the return queue past the 90-day window will fail at the next acceptance rather than at resubmission. At most two revision rounds are allowed: a resubmission attempted when `revision_round` has already reached 2 is refused with `ERR_LOCAL_REVISION_ROUNDS_EXHAUSTED`.

**Asking for an interpretation.** A `CouncilAdmin`, a `JurisdictionOfficial` or a `Petitioner` may ask the council to interpret adopted text, supplying the `adoption_rule_id` whose text is in question, the `code_section` the question concerns, and the `question` itself. Two optional fields shape the request: `jurisdiction_id` names the requesting jurisdiction and is left null when an industry petitioner asks, and `supersedes_request_id` names a prior published opinion that this request is meant to replace. The requester's identifier is stored in `requested_by_user_id`, and the request begins in `SUBMITTED` with `assigned_committee_id`, `opinion_text`, `binding_scope`, `opinion_number`, `drafted_by_user_id`, `published_by_user_id`, `published_at` and `decline_reason` all null, and `appeal_round` at 0. A request's `status` may reach `ASSIGNED`, `OPINION_DRAFTED`, `PUBLISHED`, `DECLINED` or `SUPERSEDED`; `DECLINED` and `SUPERSEDED` are terminal.

**Working an interpretation.** All movement on a request is driven by a single `action` field taking one of `ASSIGN`, `ISSUE_OPINION`, `PUBLISH`, `APPEAL` or `DECLINE`, with the supporting fields `assigned_committee_id`, `opinion_text`, `binding_scope`, `appeal_reason` and `decline_reason` supplied as the action requires. A `status` that does not admit the requested action — publishing an unassigned request, appealing an unpublished one, or acting at all on a `DECLINED` or `SUPERSEDED` request — is refused with `ERR_INTERPRETATION_STATE_INVALID`.

A `CouncilAdmin` assigns a `SUBMITTED` request to a drafting committee, moving it `SUBMITTED` → `ASSIGNED` and storing `assigned_committee_id`. The named committee must belong to the same code cycle as the rulemaking order under interpretation, or the assignment is refused with `ERR_COMMITTEE_CYCLE_MISMATCH`, and the order itself must be `PUBLISHED` or `EFFECTIVE`, or it is refused with `ERR_ADOPTION_RULE_NOT_IN_FORCE`. `TechnicalStaff` then draft the opinion, moving the request `ASSIGNED` → `OPINION_DRAFTED` and storing `opinion_text`, a `binding_scope` of either `STATEWIDE` or `REQUESTING_JURISDICTION_ONLY`, and `drafted_by_user_id`; both `opinion_text` and `binding_scope` must be present, or the action is refused with `ERR_INVALID_REQUEST`.

A `CouncilAdmin` publishes the drafted opinion, moving it `OPINION_DRAFTED` → `PUBLISHED`, and may not be the drafter — an acting identifier equal to `drafted_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES`. Publication assigns `opinion_number`, which is monotonic per rulemaking order: it is one greater than the highest `opinion_number` ever assigned under the same `adoption_rule_id`, starting at 1 for the first opinion issued under that order. Numbers are never reused, so a republication after a successful appeal receives a fresh number even though the appeal cleared the old one. Publication also stores `published_by_user_id`, stamps `published_at` from the clock, and — when `supersedes_request_id` is set and the request it names is itself `PUBLISHED` — moves that prior request `PUBLISHED` → `SUPERSEDED`, incrementing its `version` alongside the publishing request's.

The owning `JurisdictionOfficial` may appeal a published opinion, which is what makes the interpretation lifecycle cyclic: the appeal moves the request `PUBLISHED` → `ASSIGNED` so that the opinion must be drafted and published again. Three conditions apply. The clock must stand at or before `published_at` plus 30 days, inclusive at the boundary, or the appeal is refused with `ERR_APPEAL_WINDOW_EXPIRED`. `appeal_round` must be below 2, or it is refused with `ERR_APPEAL_ROUNDS_EXHAUSTED`. And the request must name a jurisdiction, with the acting `X-User-ID` equal to that `jurisdiction_id`, or it is refused with `ERR_JURISDICTION_MISMATCH` — an opinion raised by an industry petitioner with no `jurisdiction_id` cannot be appealed. On success `appeal_round` increments by one and `opinion_text`, `binding_scope`, `drafted_by_user_id`, `published_by_user_id`, `published_at` and `opinion_number` are all cleared back to null.

Finally, a `CouncilAdmin` may decline to opine on a request that is `SUBMITTED` or `ASSIGNED`, moving it to `DECLINED`; `decline_reason` must be present, or the action is refused with `ERR_INVALID_REQUEST`. A request in `OPINION_DRAFTED` reaches `DECLINED` only through the withdrawal fan-out of §3.7, which supplies the reason itself.

### 3.9. Training Rollout and Statewide Readiness

Enforcement may not begin until the officials who will enforce the new edition have been trained, so the training rollout is a gate on the rulemaking calendar rather than an afterthought.

**Scheduling a session.** A `CouncilAdmin` schedules a **training session** naming the `adoption_rule_id` whose content is taught, the `host_jurisdiction_id` providing the room, the `discipline` covered, an `audience` of `BUILDING_OFFICIAL`, `DESIGN_PROFESSIONAL` or `BOTH`, a `seat_capacity` of at least 1, and the occupancy interval `starts_at` to `ends_at` where the end must be strictly later than the start. Sessions in the same host jurisdiction are allowed to share an instant, but the seats they commit are not allowed to exceed the room the jurisdiction actually has: summed across every non-`CANCELLED` session of that host whose interval overlaps the requested one, `seat_capacity` must not exceed the host's `host_seat_capacity`, and an excess is refused with `ERR_HOST_CAPACITY_EXCEEDED`. The overlap test uses the half-open convention with zero buffer — deliberately unlike the buffered hearing rule — so a session starting exactly when another ends does not overlap it and never consumes shared capacity. A new session starts in `SCHEDULED` with `seats_available` equal to `seat_capacity`, `enrolled_count`, `attended_count` and `no_show_count` all 0, and `cancellation_reason` null. Its `status` may reach `ENROLLMENT_OPEN`, `ENROLLMENT_CLOSED`, `DELIVERED` or `CANCELLED`, the last being terminal.

**Opening and closing enrollment.** A `CouncilAdmin` supplies a `to_status` to move the session along, and a `cancellation_reason` when cancelling. Opening enrollment moves the session `SCHEDULED` → `ENROLLMENT_OPEN` and requires the referenced rulemaking order to be `PUBLISHED` or `EFFECTIVE`, or the request is refused with `ERR_ADOPTION_RULE_NOT_IN_FORCE`. Closing enrollment moves it `ENROLLMENT_OPEN` → `ENROLLMENT_CLOSED` with no further precondition. Cancellation is available by operator request from `SCHEDULED`, `ENROLLMENT_OPEN` or `ENROLLMENT_CLOSED`: it cancels the session's `ENROLLED` enrollments, returns `seats_available` to the full `seat_capacity`, and makes every affected jurisdiction recompute its compliance percentages and `enforcement_readiness`. A `DELIVERED` session may **not** be cancelled by operator request — the attempt is refused with `ERR_SESSION_STATE_INVALID` — and reaches `CANCELLED` only through the rule-withdrawal cascade of §3.7. Any other status move a session's own `status` does not admit, including re-cancelling an already cancelled session, is likewise refused with `ERR_SESSION_STATE_INVALID`.

**Enrolling.** A `CouncilAdmin` or a `JurisdictionOfficial` enrolls an attendee, supplying the attendee's employer `jurisdiction_id`, the `attendee_name`, and an `attendee_role` of either `BUILDING_OFFICIAL` or `DESIGN_PROFESSIONAL`. A `JurisdictionOfficial` may only enrol its own staff, or `ERR_JURISDICTION_MISMATCH` follows. The enrollment records `enrolled_by_user_id` and starts in `ENROLLED`; its `status` may later become `ATTENDED`, `NO_SHOW` or `CANCELLED`, the last being terminal. Enrollment is only possible while the session is `ENROLLMENT_OPEN`, or `ERR_SESSION_STATE_INVALID` follows. A given `attendee_name` may hold only one live seat on a given session — a duplicate on a non-`CANCELLED` row is refused with `ERR_DUPLICATE_ENROLLMENT`, while a cancelled row frees the name again. A session with `seats_available` at 0 cannot take another enrollment: the attempt is refused with `ERR_SESSION_FULL`. On success the seat ledger of §2.10 moves: `enrolled_count` rises by one and `seats_available` falls by one, and both of the employer jurisdiction's compliance percentages are recomputed.

**Cancelling an enrollment.** A `CouncilAdmin` or the owning `JurisdictionOfficial` may cancel an `ENROLLED` seat with an optional `reason`, provided the session is in `SCHEDULED`, `ENROLLMENT_OPEN` or `ENROLLMENT_CLOSED`; any other session status yields `ERR_SESSION_STATE_INVALID`, and an enrollment that is no longer `ENROLLED` — already attended, already a no-show, already cancelled — yields `ERR_ENROLLMENT_STATE_INVALID`. Cancellation is a full compensation of the seat ledger: `enrolled_count` falls by one and `seats_available` rises by one, restoring the invariant exactly. Both compliance percentages for the attendee's jurisdiction are recomputed, and both the enrollment's and the session's `version` increment. When the system itself cancels enrollments as part of a session cancellation, the jurisdiction-ownership check is skipped — the cascade acts with the council's authority.

**Recording attendance.** After a session has finished, a `CouncilAdmin` records attendance by supplying `records`, an array in which each entry names an `enrollment_id` and that attendee's `outcome` of either `ATTENDED` or `NO_SHOW`. The clock must have reached the session's `ends_at`, or the request is refused with `ERR_SESSION_NOT_FINISHED`. The session must be `ENROLLMENT_CLOSED`, or `ERR_SESSION_STATE_INVALID`. Every referenced enrollment must belong to *this* session, or `ERR_ENROLLMENT_SESSION_MISMATCH`, and must currently be `ENROLLED`, or `ERR_ENROLLMENT_STATE_INVALID`. On success the session moves `ENROLLMENT_CLOSED` → `DELIVERED`; every listed enrollment moves `ENROLLED` → `ATTENDED` or `ENROLLED` → `NO_SHOW` as its `outcome` directs; and every enrollment still `ENROLLED` that was *not* listed is treated as a no-show and moves `ENROLLED` → `NO_SHOW`. Either move shifts a seat between buckets without releasing it: `enrolled_count` falls by one and `attended_count` or `no_show_count` rises by one, while `seats_available` is unchanged. The session then recomputes `enrolled_count`, `attended_count`, `no_show_count` and `seats_available`, and each affected jurisdiction recomputes both compliance percentages and its `enforcement_readiness`. The session's `version`, each touched enrollment's `version` and each affected jurisdiction's `version` all increment.

**The two compliance bases.** A jurisdiction's training coverage is reported on two bases computed over identical data, and only one of them gates anything. The relevant enrollment rows are those whose `jurisdiction_id` is this jurisdiction, whose `attendee_role` is `BUILDING_OFFICIAL` — design professionals are trained but do not count toward enforcement coverage — and whose session's `status` is anything other than `CANCELLED`. Over those rows, the enrollment-basis numerator is the count of *distinct* `attendee_name` values whose enrollment `status` is `ENROLLED`, `ATTENDED` or `NO_SHOW`; the attendance-basis numerator is the count of distinct `attendee_name` values whose enrollment `status` is `ATTENDED`. Enrollments in `CANCELLED` are excluded from both numerators. `compliance_pct_enrollment_basis` is 100 multiplied by the enrollment-basis numerator, divided by `official_headcount`, rounded half up to 2 decimal places and then capped at 100.00. `compliance_pct_attendance_basis` is the same arithmetic on the attendance-basis numerator, likewise rounded to 2 decimal places and capped at 100.00. The enrollment basis is a planning view — it credits every official who ever held a live seat, so a no-show still reads as covered — and it never gates anything. The attendance basis credits only officials who actually attended, and it is the only one that drives `enforcement_readiness`, which reads `READY` when `compliance_pct_attendance_basis` is at or above 80.00 and `NOT_READY` otherwise. Once no-shows exist, the two bases stay apart permanently, and the 80.00 threshold can easily sit between them: a jurisdiction needing 25 trained officials, with 21 distinct officials having held seats and 19 having actually attended, reads 84.00 on the enrollment basis but 76.00 on the attendance basis, and is therefore `NOT_READY`.

There is exactly one way a jurisdiction that has reached `READY` can fall back to `NOT_READY`: the withdrawal of a published rulemaking order, which cancels even `DELIVERED` sessions and so removes attendees from the attendance-basis numerator. That single path is what makes the enforcement gate on a rulemaking order meaningful rather than a one-way ratchet, and it is why the withdrawal cascade in §3.7 recomputes readiness on every affected jurisdiction.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — advancing a status, recording a decision, filling an agenda, recording attendance — return `200 OK`, as do all reads. Every endpoint requires the `X-User-ID` and `X-User-Role` headers described in §2.1. Where the Authorized Role(s) column reads "Any", all six roles are accepted.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock used by every temporal rule (default `2026-08-01T00:00:00Z`) | Any |
| POST | `/code-cycles` | Open a model-code review cycle | CouncilAdmin |
| GET | `/code-cycles` | List code cycles | Any |
| GET | `/code-cycles/{code_cycle_id}` | Fetch one code cycle | Any |
| POST | `/code-cycles/{code_cycle_id}/status` | Advance or abandon a code cycle | CouncilAdmin |
| POST | `/code-cycles/{code_cycle_id}/discipline-committees` | Seat a discipline committee on a cycle | CouncilAdmin |
| GET | `/code-cycles/{code_cycle_id}/discipline-committees` | Committees of a cycle | Any |
| GET | `/code-cycles/{code_cycle_id}/amendment-proposals` | Proposals of a cycle | Any |
| GET | `/code-cycles/{code_cycle_id}/adoption-rules` | Adoption rules of a cycle | Any |
| GET | `/discipline-committees` | List discipline committees | Any |
| GET | `/discipline-committees/{committee_id}` | Fetch one discipline committee | Any |
| POST | `/discipline-committees/{committee_id}/members` | Add a seat to a committee | CouncilAdmin |
| GET | `/discipline-committees/{committee_id}/members` | Seats of a committee | Any |
| GET | `/discipline-committees/{committee_id}/amendment-proposals` | Proposals routed to a committee | Any |
| GET | `/discipline-committees/{committee_id}/hearings` | Hearings of a committee | Any |
| GET | `/discipline-committees/{committee_id}/interpretation-requests` | Requests assigned to a committee | Any |
| GET | `/committee-members` | List committee members | Any |
| GET | `/committee-members/{member_id}` | Fetch one committee member | Any |
| POST | `/committee-members/{member_id}/recusal` | Recuse or reinstate a committee member | CouncilAdmin |
| POST | `/amendment-proposals` | Submit a proposed state amendment | CouncilAdmin, TechnicalStaff, JurisdictionOfficial, Petitioner |
| GET | `/amendment-proposals` | List amendment proposals | Any |
| GET | `/amendment-proposals/{proposal_id}` | Fetch one amendment proposal with both status dimensions | Any |
| POST | `/amendment-proposals/{proposal_id}/screening` | Staff screening decision on a submitted or returned proposal | TechnicalStaff |
| POST | `/amendment-proposals/{proposal_id}/impact-analyses` | File a cost-benefit or energy impact analysis | TechnicalStaff |
| GET | `/amendment-proposals/{proposal_id}/impact-analyses` | Analyses of a proposal | Any |
| POST | `/amendment-proposals/{proposal_id}/comment-window` | Open, extend or close the public comment period | CouncilAdmin |
| POST | `/amendment-proposals/{proposal_id}/comments` | Submit a public comment inside the open window | CouncilAdmin, TechnicalStaff, JurisdictionOfficial, Petitioner |
| GET | `/amendment-proposals/{proposal_id}/comments` | Public comments on a proposal | Any |
| GET | `/amendment-proposals/{proposal_id}/vote-records` | Votes taken on a proposal | Any |
| POST | `/amendment-proposals/{proposal_id}/reopen` | Return an approved or comment-closed proposal for revision | CouncilAdmin |
| GET | `/impact-analyses` | List impact analyses | Any |
| GET | `/impact-analyses/{analysis_id}` | Fetch one impact analysis | Any |
| POST | `/impact-analyses/{analysis_id}/review` | Accept or return a filed analysis | CouncilAdmin |
| GET | `/public-comments` | List public comments | Any |
| GET | `/public-comments/{comment_id}` | Fetch one public comment | Any |
| POST | `/hearings` | Schedule a committee hearing | CouncilAdmin |
| GET | `/hearings` | List hearings | Any |
| GET | `/hearings/{hearing_id}` | Fetch one hearing with its ordered agenda | Any |
| POST | `/hearings/{hearing_id}/agenda` | Fill the hearing agenda from the eligible docket | CouncilAdmin |
| POST | `/hearings/{hearing_id}/convene` | Convene the hearing and record attendance | CouncilChair |
| POST | `/hearings/{hearing_id}/adjourn` | Adjourn the hearing | CouncilChair |
| POST | `/hearings/{hearing_id}/votes` | Record a committee ballot on an agenda item | CouncilChair |
| GET | `/hearings/{hearing_id}/votes` | Votes recorded at a hearing | Any |
| GET | `/vote-records` | List vote records | Any |
| GET | `/vote-records/{vote_record_id}` | Fetch one immutable vote record | Any |
| POST | `/adoption-rules` | Draft the adoption rulemaking order and its transition schedule | CouncilAdmin |
| GET | `/adoption-rules` | List adoption rules | Any |
| GET | `/adoption-rules/{adoption_rule_id}` | Fetch one adoption rule with its schedule | Any |
| POST | `/adoption-rules/{adoption_rule_id}/status` | File, publish, make effective or withdraw the adoption rule | CouncilAdmin |
| GET | `/adoption-rules/{adoption_rule_id}/local-amendments` | Local filings against a rule | Any |
| GET | `/adoption-rules/{adoption_rule_id}/interpretation-requests` | Interpretation requests against a rule | Any |
| GET | `/adoption-rules/{adoption_rule_id}/training-sessions` | Training sessions for a rule | Any |
| POST | `/jurisdictions` | Register a local jurisdiction | CouncilAdmin |
| GET | `/jurisdictions` | List jurisdictions | Any |
| GET | `/jurisdictions/{jurisdiction_id}` | Fetch one jurisdiction with both compliance bases | Any |
| GET | `/jurisdictions/{jurisdiction_id}/local-amendments` | Filings by a jurisdiction | Any |
| GET | `/jurisdictions/{jurisdiction_id}/interpretation-requests` | Requests raised by a jurisdiction | Any |
| GET | `/jurisdictions/{jurisdiction_id}/hosted-training-sessions` | Sessions hosted by a jurisdiction | Any |
| GET | `/jurisdictions/{jurisdiction_id}/training-enrollments` | Enrollments of a jurisdiction's staff | Any |
| POST | `/local-amendments` | File a local amendment to the state rule | JurisdictionOfficial |
| GET | `/local-amendments` | List local amendments | Any |
| GET | `/local-amendments/{local_amendment_id}` | Fetch one local amendment | Any |
| POST | `/local-amendments/{local_amendment_id}/review` | Council review of a local filing against the stringency limit | CouncilAdmin |
| POST | `/local-amendments/{local_amendment_id}/resubmit` | Resubmit a returned local filing | JurisdictionOfficial |
| POST | `/interpretation-requests` | Request a formal code interpretation | CouncilAdmin, JurisdictionOfficial, Petitioner |
| GET | `/interpretation-requests` | List interpretation requests | Any |
| GET | `/interpretation-requests/{request_id}` | Fetch one interpretation request and its opinion | Any |
| POST | `/interpretation-requests/{request_id}/actions` | Assign, draft, publish, appeal or decline a formal opinion | CouncilAdmin, TechnicalStaff, JurisdictionOfficial |
| GET | `/interpretation-requests/{request_id}/superseding-requests` | Requests that supersede this one | Any |
| POST | `/training-sessions` | Schedule a training session for building officials and design professionals | CouncilAdmin |
| GET | `/training-sessions` | List training sessions | Any |
| GET | `/training-sessions/{training_session_id}` | Fetch one training session with its seat ledger | Any |
| POST | `/training-sessions/{training_session_id}/status` | Open, close or cancel enrollment on a session | CouncilAdmin |
| POST | `/training-sessions/{training_session_id}/enrollments` | Enroll an official or design professional in a session | CouncilAdmin, JurisdictionOfficial |
| GET | `/training-sessions/{training_session_id}/enrollments` | Enrollments on a session | Any |
| POST | `/training-sessions/{training_session_id}/attendance` | Record attendance and deliver the session | CouncilAdmin |
| GET | `/training-enrollments` | List training enrollments | Any |
| GET | `/training-enrollments/{enrollment_id}` | Fetch one training enrollment | Any |
| POST | `/training-enrollments/{enrollment_id}/cancel` | Cancel an enrollment and return the seat | CouncilAdmin, JurisdictionOfficial |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_IDENTITY_NOT_FOUND` | 403 Forbidden |
| `ERR_JURISDICTION_MISMATCH` | 403 Forbidden |
| `ERR_NOT_COMMITTEE_CHAIR` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PAGINATION_INVALID` | 400 Bad Request |
| `ERR_CODE_CYCLE_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITTEE_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITTEE_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_PROPOSAL_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYSIS_NOT_FOUND` | 404 Not Found |
| `ERR_COMMENT_NOT_FOUND` | 404 Not Found |
| `ERR_HEARING_NOT_FOUND` | 404 Not Found |
| `ERR_VOTE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_ADOPTION_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_JURISDICTION_NOT_FOUND` | 404 Not Found |
| `ERR_LOCAL_AMENDMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INTERPRETATION_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PROPOSAL_VERSION` | 412 Precondition Failed |
| `ERR_STALE_JURISDICTION_VERSION` | 412 Precondition Failed |
| `ERR_CYCLE_STATE_INVALID` | 409 Conflict |
| `ERR_PROPOSAL_STATE_INVALID` | 409 Conflict |
| `ERR_ANALYSIS_STATE_INVALID` | 409 Conflict |
| `ERR_HEARING_STATE_INVALID` | 409 Conflict |
| `ERR_ADOPTION_RULE_STATE_INVALID` | 409 Conflict |
| `ERR_LOCAL_AMENDMENT_STATE_INVALID` | 409 Conflict |
| `ERR_INTERPRETATION_STATE_INVALID` | 409 Conflict |
| `ERR_SESSION_STATE_INVALID` | 409 Conflict |
| `ERR_ENROLLMENT_STATE_INVALID` | 409 Conflict |
| `ERR_COMMITTEE_NOT_SEATED` | 409 Conflict |
| `ERR_ADOPTION_RULE_NOT_IN_FORCE` | 409 Conflict |
| `ERR_PROPOSAL_STAGE_INVALID` | 409 Conflict |
| `ERR_ANALYSIS_INCOMPLETE` | 409 Conflict |
| `ERR_LOCAL_AUTHORITY_ABSENT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_STRINGENCY_FLOOR_VIOLATION` | 422 Unprocessable Entity |
| `ERR_LOCAL_LESS_STRINGENT_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_QUORUM_NOT_MET` | 422 Unprocessable Entity |
| `ERR_PROPOSAL_NOT_ON_AGENDA` | 409 Conflict |
| `ERR_COMMITTEE_CYCLE_MISMATCH` | 409 Conflict |
| `ERR_BALLOT_MEMBER_NOT_ON_COMMITTEE` | 409 Conflict |
| `ERR_NO_COMMITTEE_FOR_DISCIPLINE` | 409 Conflict |
| `ERR_ENROLLMENT_SESSION_MISMATCH` | 409 Conflict |
| `ERR_COMMENT_PERIOD_TOO_SHORT` | 409 Conflict |
| `ERR_COMMENT_WINDOW_CLOSED` | 409 Conflict |
| `ERR_COMMENT_WINDOW_STILL_OPEN` | 409 Conflict |
| `ERR_HEARING_NOTICE_TOO_SHORT` | 409 Conflict |
| `ERR_HEARING_TIME_CONFLICT` | 409 Conflict |
| `ERR_HEARING_NOT_STARTED` | 409 Conflict |
| `ERR_EFFECTIVE_DATE_NOT_REACHED` | 409 Conflict |
| `ERR_SESSION_NOT_FINISHED` | 409 Conflict |
| `ERR_APPEAL_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_LOCAL_FILING_DEADLINE_PASSED` | 409 Conflict |
| `ERR_DUPLICATE_CODE_CYCLE` | 409 Conflict |
| `ERR_DUPLICATE_COMMITTEE_DISCIPLINE` | 409 Conflict |
| `ERR_DUPLICATE_JURISDICTION` | 409 Conflict |
| `ERR_DUPLICATE_LOCAL_AMENDMENT` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_BALLOT` | 409 Conflict |
| `ERR_DUPLICATE_VOTE_RECORD` | 409 Conflict |
| `ERR_SESSION_FULL` | 409 Conflict |
| `ERR_CHAIR_ALREADY_SEATED` | 409 Conflict |
| `ERR_SEAT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_COMMENT_EXTENSIONS_EXHAUSTED` | 409 Conflict |
| `ERR_APPEAL_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_LOCAL_REVISION_ROUNDS_EXHAUSTED` | 409 Conflict |
| `ERR_AGENDA_EMPTY` | 409 Conflict |
| `ERR_NO_ELIGIBLE_PROPOSALS` | 409 Conflict |
| `ERR_HOST_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_BENEFIT_COST_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_TRAINING_READINESS_NOT_MET` | 422 Unprocessable Entity |
| `ERR_NO_APPROVED_AMENDMENTS` | 422 Unprocessable Entity |
| `ERR_PROPOSALS_UNRESOLVED` | 422 Unprocessable Entity |

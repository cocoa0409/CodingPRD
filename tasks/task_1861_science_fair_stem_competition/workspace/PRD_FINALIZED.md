# Science Fair API — Product Requirements Document

## 1. Introduction

A regional science fair affiliate runs one edition of its fair per season, and every season repeats the same punishing arc: hundreds of student projects must be registered and routed into the right category, research plans involving human or animal subjects must clear an ethics committee before the fair, dozens of volunteer judges must be recruited, conflict-screened, and balanced across projects, raw rubric scores must be normalized so that a harsh judge and a generous judge contribute comparably, advancement slots to the state fair must be allocated by category quota, booths must pass a display-safety inspection at the venue, and scholarships must be distributed from a fixed pool without overspending it. Today this work lives in spreadsheets and email threads, and the two failure modes that actually hurt — a quota silently recomputed against a stale edition snapshot, and a judge's scores normalized against an out-of-date pool — are exactly the ones this API is designed to make impossible.

This document specifies the Science Fair API, the single backend through which fair directors, mentors, ethics reviewers, judges, venue operations, and safety inspectors run the entire season. All endpoints are mounted under the `/science-fair` prefix. The API governs the full lifecycle of a fair edition from initial setup through registration, ethics clearance, judging, advancement publication, awards finalization, and archival, and it does so under two cross-cutting disciplines: optimistic concurrency on any write whose correctness depends on the caller's last observed state, and an auditable, deterministic scoring pipeline in which every normalized score can be re-derived from raw inputs.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The system recognizes six authenticated roles: `FairDirector`, `Mentor`, `EthicsReviewer`, `Judge`, `OperationsLead`, and `SafetyInspector`. A request that omits either header, or carries a role outside this declared set, is an `Anonymous` call and is rejected with `ERR_UNAUTHENTICATED`. A request whose authenticated role is simply not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED`. When an entity-backed role attempts to act on a resource it does not own — a mentor touching another mentor's project, a judge scoring another judge's assignment — the rejection is `ERR_FORBIDDEN`.

Two roles are entity-backed. When `X-User-Role` is `Mentor`, `X-User-ID` is the `id` of the acting `Mentor`; ownership checks on any resource that references a mentor compare the resource's `mentor_id` foreign key (on a project directly, or on a research plan through its parent project) to `X-User-ID`. When `X-User-Role` is `Judge`, `X-User-ID` is the `id` of the acting `Judge`; ownership checks compare an assignment's `judge_id` to `X-User-ID`. The remaining roles — `FairDirector`, `EthicsReviewer`, `OperationsLead`, `SafetyInspector`, and the unauthenticated `Anonymous` caller — treat `X-User-ID` as an opaque operator identifier not tied to any persisted entity. The server may record such identifiers where a workflow captures an actor (for example, an ethics decision records its committee reviewer through an explicit payload field rather than through the header), but it never compares an opaque identifier against any entity's `id`.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10 when omitted, and accepts values from a minimum of 1 to a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier, formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource, and that anchors the optimistic concurrency checks described in §2.7.

Two record types are deliberately lighter: a judge-conflict record and a score sheet are immutable once written, so each carries only `id` and `created_at` among the standard fields — both `updated_at` and `version` are absent from them. Everywhere else, any mutation — including mutations caused by a cascade from another entity, such as a project whose version advances when an ethics approval lands on it — updates `updated_at` and increments `version`.

### 2.5. The Logical Clock

All timestamps the business logic reads — inspection windows, decision times, assignment times, submission times — come from a server-side logical clock, never from the host's wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and before any explicit set call it must continue to read exactly that value rather than falling back to real time. A `FairDirector`-only test-driving capability advances the clock: the caller supplies a `to_iso8601` instant, and the response echoes the clock's new reading as `current_utc`. Window-based rules throughout this document (§3.6 in particular) evaluate against this logical clock.

### 2.6. Numeric Precision and Rounding

Three numeric regimes coexist and must not be conflated. Per-sheet normalized scores are stored at exactly 3 decimal places, rounded half-up. Project-level aggregates — both the provisional and the final aggregate — are stored at exactly 2 decimal places, rounded half-up, and the rounding order is pinned system-wide: normalize each sheet to three decimals first, then average, then round the average to two decimals; raw scores are never averaged first and normalized second. Scholarship amounts are integer cents with no rounding whatsoever — no fractional cent ever appears. Advancement ranks and mentor recognition points are plain integers.

### 2.7. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent entity, by carrying the parent's last-seen `version` in the request body. The check is the same in all three cases: if the supplied value does not match the parent entity's current `version` — because another writer has legitimately mutated the parent since the client last read it — the request is rejected as stale.

- Publishing advancement requires `expected_fair_edition_version` to match the fair edition's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a category (including any quota edit) requires `expected_fair_edition_version` to match the parent edition's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Updating a project requires `expected_project_version` to match the project's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

The version field on these three operations is not optional. Endpoints not listed here take no version field at all; their writes are guarded by the state machine alone.

### 2.8. Validation Pipeline and Priority Ordering

Every request passes through a single ordered validation pipeline, and the first failing check determines the error response. The ordering is part of the contract:

1. **Priority 0 — request shape.** Required fields are present, types are correct, and enum values fall within their declared sets; failures report `ERR_INVALID_REQUEST` (400). This check is evaluated before authentication so malformed payloads fail fast. Range violations on intake fields fail here as well: a `team_size` outside the 1-to-3 range, a `max_judges_per_project` below 2, a `min_quorum_ratio_pct` outside 1 through 100, a negative `advancement_slots`, a `max_assignments` below 1, or a negative `total_cents`.
2. **Priority 1 — authentication.** The `X-User-Role` and `X-User-ID` headers are present and the role is declared; otherwise `ERR_UNAUTHENTICATED` (401).
3. **Priority 2 — authorization.** The acting role is permitted to invoke the endpoint; otherwise `ERR_UNAUTHORIZED` (403).
4. **Priority 3 — path existence.** Every resource named in the path exists, validated left to right; the first missing identifier yields `ERR_NOT_FOUND` (404).
5. **Priority 4 — state legality.** The target resource is in a state from which the requested transition is allowed; otherwise `ERR_INVALID_STATE` (409). Where a transition is aimed at a terminal source — a `WITHDRAWN` project, a `CONFERRED` or `REVOKED` award, an `ARCHIVED` edition — the rejection instead carries `ERR_ALREADY_TERMINAL` (409), which takes precedence over the generic state error for terminal sources.
6. **Priority 5 — segregation of duties.** An ethics reviewer must not be the project's own mentor, and a judge must not score a project against which a declared conflict exists; breaches report `ERR_SOD_VIOLATION` (422). This guard applies to recording an ethics decision, submitting a score sheet, and creating a judging assignment.
7. **Priority 6 — temporal validity.** An inverted booth inspection window reports `ERR_INVALID_WINDOW` (422); an inspection result recorded outside its scheduled window reports `ERR_OUTSIDE_WINDOW` (422); a score submission attempted while the edition is not in the `JUDGING` phase reports `ERR_NOT_JUDGING_PHASE` (409). Both window errors sit at this priority, ahead of the priority-7 uniqueness constraint — so on booth scheduling an inverted window surfaces as `ERR_INVALID_WINDOW` even when the requested booth happens to be taken as well.
8. **Priority 7 — uniqueness and capacity.** Booth uniqueness within the edition, judge capacity, team-size bounds, and duplicate non-terminal assignments are enforced here; the generic breach reports `ERR_CONSTRAINT_VIOLATION` (422), while an occupied booth carries the dedicated `ERR_BOOTH_TAKEN` (422). These checks guard booth scheduling, judge assignment, and project registration.
9. **Priority 8 — referential integrity.** A `category_id`, `mentor_id`, `judge_id`, or `project_id` referenced in a payload must exist and must belong to the same fair edition as the rest of the request; otherwise `ERR_REFERENTIAL_INTEGRITY` (422). This guard applies to project creation and update, judge recruitment, judge assignment, and conflict declaration.
10. **Priority 9 — fiscal preconditions.** Finalizing awards requires the edition's scholarship pool to exist; otherwise `ERR_SCHOLARSHIP_POOL_MISSING` (422). Slot and quota edits must likewise keep `advancement_slots` at zero or greater.

### 2.9. Nested Resource Retrieval

Requests that target a resource nested under another — a score sheet under a judging assignment, a booth assignment under a project, a conflict under a judge — are validated left to right along the path. The server confirms the existence of each path identifier in order and rejects the request with `ERR_NOT_FOUND` at the first identifier that does not resolve, without examining anything further to the right. A request aimed at a non-existent project therefore fails before the server even considers whether a particular assignment or booth exists beneath it.

### 2.10. Edition Phases, Freezes, and Cross-Entity Cascades

A fair edition moves through a fixed phase ladder — `SETUP`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, `JUDGING`, `ADVANCEMENT_PUBLISHED`, `AWARDS_FINALIZED`, and finally the terminal `ARCHIVED` — and every successful phase transition increments the edition's `version` by exactly 1 and refreshes its `updated_at`. Publishing advancement additionally sets the edition's `advancement_freeze` flag to true; from that moment, quota edits and score submissions are blocked, so the slot arithmetic that was published can never be silently recomputed underneath a reader.

Many operations deliberately mutate more than one entity at once, and all such cascades are atomic: the closing sweep that withdraws draft projects and confirms eligible ones, the ethics rejection that withdraws its parent project, the failed inspection that withdraws the exhibitor, the recusal that creates a conflict record and shrinks a judge's workload counter. Each entity touched by a cascade is independently mutated — its own `updated_at` refreshed and its own `version` (where it carries one) incremented — so an optimistic-concurrency reader of any one entity always sees a consistent per-entity history.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Fair Edition and Its Categories

A season begins when a `FairDirector` creates a fair edition with a human-readable `name`, a `normalization_algorithm` of either `Z_SCORE` or `MIN_MAX` (which fixes how every judge's scores will be normalized all season, per §3.5), a `max_judges_per_project` of at least 2 (the number of submitted score sheets a project needs before its aggregate becomes final), and a `min_quorum_ratio_pct` between 1 and 100 (the percentage of that judge count that must be submitted before a provisional aggregate is published). New editions are born in `SETUP` with `advancement_freeze` false.

Within an edition, the director defines the competition's categories. Each category carries a short `code` such as PHYS or BME, a display `name`, a `grade_band` of `JUNIOR` or `SENIOR`, and an `advancement_slots` quota — the number of advancement slots the category contributes to the regional/state pool, zero or greater. Categories are born `OPEN` and accept project registrations until the closing sweep locks them (§3.2). The director may later update a category — its display `name` or its `advancement_slots` — but only while the edition is in `SETUP`, `REGISTRATION_OPEN`, `REGISTRATION_CLOSED`, or `JUDGING`. Once advancement has been published and `advancement_freeze` is true, the same edit is rejected with `ERR_ADVANCEMENT_FROZEN` (409) rather than the generic state error, because freezing exists precisely to pin the quota base the waterfall already consumed. Note that the category's own `OPEN`/`LOCKED` status plays no part in this gate — the edition phase and the freeze flag do. Every category update must carry `expected_fair_edition_version` per §2.7, and a successful update increments both the category's `version` and the parent edition's `version` — which is exactly how a quota edit stales any publish-advancement request that was prepared against the pre-edit edition.

Opening registration is the first phase transition, `SETUP` → `REGISTRATION_OPEN`, and it is guarded: the edition must contain at least one category still in `OPEN` status, or the transition fails with `ERR_NO_OPEN_CATEGORY`. At the far end of the season, once awards have been finalized, the director archives the edition — `AWARDS_FINALIZED` → `ARCHIVED` — after which the edition is terminal and any further transition aimed at it is rejected with `ERR_ALREADY_TERMINAL`.

### 3.2. Project Registration and the Mentor's Path

Registration is the mentor's workflow. While the edition is in `REGISTRATION_OPEN`, a `Mentor` registers a project by supplying the `fair_edition_id`, the target `category_id`, a `title`, a `team_size` between 1 and 3 (anything outside that range fails fast as `ERR_INVALID_REQUEST`), and two declarations: `involves_human_subjects` and `involves_animal_subjects`. The mentor's own identity becomes the project's `mentor_id`. The referenced category and the mentor must both belong to the named edition — a cross-edition or dangling reference is `ERR_REFERENTIAL_INTEGRITY` — and the target category must still be `OPEN`; once the closing sweep has `LOCKED` it, a registration attempt into it is rejected with `ERR_INVALID_STATE`. A new project starts with `registration_status` `DRAFT`, a null `ethics_status`, `inspection_status` `NOT_SCHEDULED`, `judging_status` `UNASSIGNED`, `advancement_result` `PENDING`, a null `advancement_rank`, and both aggregates null.

While a project is in `DRAFT` or `SUBMITTED` and the edition's registration is still open, its mutable fields — `title`, `team_size`, and `category_id` — may be updated, either by the owning mentor or by a `FairDirector` exercising the category-reassignment override. Every such update must carry `expected_project_version` matching the project's current `version` (§2.7); because an ethics decision can cascade a mutation onto the project, a reassignment prepared before that decision is rejected with `ERR_STALE_VERSION` rather than applied against a snapshot the client never saw. A successful update increments the project's `version`.

Submitting moves a project `DRAFT` → `SUBMITTED`. The acting mentor must own the project (`ERR_FORBIDDEN` otherwise), the edition must still be in `REGISTRATION_OPEN`, and the team size must still sit within 1 to 3. The declaration fields drive an ethics gate: if `involves_human_subjects` or `involves_animal_subjects` is true, the project must already have a research plan in `SUBMITTED`, `UNDER_REVIEW`, or `APPROVED` status — otherwise the submission is rejected with `ERR_RESEARCH_PLAN_REQUIRED`. A successful submission stamps the project's `ethics_status`: `PENDING` when either subject flag is true, `NOT_REQUIRED` when neither is.

Withdrawal is the mentor's exit, available from either `DRAFT` or `SUBMITTED`, again ownership-checked. From `SUBMITTED` there is one extra guard: the project's `judging_status` must still be `UNASSIGNED`, because withdrawing a project that already has live judging assignments is rejected with `ERR_ALREADY_ASSIGNED`. Withdrawing from `SUBMITTED` also runs a compensation across the project's paper trail — any research plan sitting in `SUBMITTED`, `UNDER_REVIEW`, or `REVISION_REQUIRED` is pulled back to `DRAFT`. Any transition trigger aimed at an already-`WITHDRAWN` project is rejected with `ERR_ALREADY_TERMINAL` (409), which takes precedence over the generic `ERR_INVALID_STATE` for that terminal source.

The mentor-facing window closes when the `FairDirector` closes registration, moving the edition `REGISTRATION_OPEN` → `REGISTRATION_CLOSED`. This is a sweep, not a flip of one flag: every project still in `DRAFT` is withdrawn; every project in `SUBMITTED` whose `ethics_status` is `APPROVED` or `NOT_REQUIRED` at that moment is confirmed (`SUBMITTED` → `CONFIRMED`); projects still `SUBMITTED` with `ethics_status` `PENDING` are neither confirmed nor withdrawn — they can still be approved later, but they are not `CONFIRMED` and are therefore excluded from this edition's judging and advancement; and every category in the edition is locked (`OPEN` → `LOCKED`). Confirmation happens only inside this sweep — an ethics approval that lands while registration is still open does not, by itself, confirm anything.

### 3.3. Research Plans and the Ethics Committee

Any project can carry one active research plan, created by the owning mentor with the `project_id`, a free-text `plan_text`, and a declared `risk_level` of `LOW`, `MODERATE`, or `HIGH`. Plans are born in `DRAFT` with a `review_cycle_count` of 0 and no approved version pinned.

The mentor submits the plan (`DRAFT` → `SUBMITTED`), which increments the plan's `version`; submission is only possible while the parent project's `registration_status` is `DRAFT` or `SUBMITTED` — once the project has been confirmed, withdrawn, or otherwise locked, plan submission is rejected with `ERR_PROJECT_LOCKED`. An `EthicsReviewer` then takes the plan under review (`SUBMITTED` → `UNDER_REVIEW`), which increments `review_cycle_count` by 1 so the committee can see how many rounds a plan has been through.

Committee decisions are recorded per plan, and each decision creates an ethics-review record capturing the `research_plan_id`, the committee member's `reviewer_mentor_id`, the `decision` (`APPROVE`, `REJECT`, or `REQUEST_REVISION`), a free-text `rationale`, and a `decided_at` timestamp read from the logical clock. Two guards wrap every decision. Segregation of duties: the `reviewer_mentor_id` must differ from the parent project's `mentor_id`, or the decision is rejected with `ERR_SOD_VIOLATION`. And substantiation: for any `decision` other than `APPROVE`, the `rationale` must be non-empty, or the decision is rejected with `ERR_RATIONALE_REQUIRED`.

The three decision branches diverge sharply. An `APPROVE` moves the plan `UNDER_REVIEW` → `APPROVED`, pins `approved_plan_version` to the plan's current `version` — a snapshot that goes stale if the plan's version later advances — and cascades onto the parent project, setting its `ethics_status` to `APPROVED` and incrementing the project's `version`; confirmation to `CONFIRMED` still waits for the closing sweep, never the approval itself. A `REJECT` moves the plan to `REJECTED`, sets the project's `ethics_status` to `REJECTED`, and cascades the project's `registration_status` to `WITHDRAWN`. A `REQUEST_REVISION` moves the plan to `REVISION_REQUIRED` with no project-side mutation. `APPROVED` and `REJECTED` are terminal for the plan.

The revision loop closes through an ordinary plan edit. A mentor may update `plan_text` or `risk_level`; while the plan sits in `REVISION_REQUIRED`, any change to `plan_text` returns it to `DRAFT`, clears `approved_plan_version` to null, and increments the plan's `version` — ready to be submitted again for another cycle.

### 3.4. Judge Recruitment, Conflicts, and Assignment

Judging capacity is built deliberately. The `FairDirector` recruits each judge into an edition with the `fair_edition_id`, a `full_name`, an optional `expertise_category_ids` array naming the categories the judge is expert in (it may be empty, marking a generalist), and a `max_assignments` cap of at least 1. Judges are born `INVITED`, carry an `active_assignment_count` of 0, and become scoreable only when the director activates them (`INVITED` → `ACTIVE`) — allowed while the edition is in `SETUP`, `REGISTRATION_OPEN`, or `REGISTRATION_CLOSED`. Deactivation (`ACTIVE` → `INACTIVE`) is refused while the judge still carries live assignments: if `active_assignment_count` is above zero the request fails with `ERR_JUDGE_HAS_ASSIGNMENTS`.

Conflicts of interest are first-class records. A `FairDirector`, or a judge declaring their own conflict, records the `project_id` and a free-text `reason` (for example, a mentoring relationship at the same school), creating a conflict row keyed by the `judge_id`–`project_id` pair. Declared conflicts feed both the assignment-time segregation check (a judge may not be assigned or score a project they conflict with — `ERR_SOD_VIOLATION`) and the auto-assignment selector below.

Assigning a judge to a project is a `FairDirector` operation with two modes. In the explicit mode the director supplies a `judge_id`; in the auto mode the `judge_id` is omitted and the selector runs. Either way, the parent edition must be in `REGISTRATION_CLOSED` or `JUDGING` — pre-assignment before the judging phase opens is legitimate — the project must be `CONFIRMED`, and a successful creation sets the project's `judging_status` to `ASSIGNED`, increments the judge's `active_assignment_count` by 1, and stamps the assignment's `assigned_at` from the logical clock. Assignment creation enforces, in pipeline order, the segregation-of-duties conflict check at priority 5, then capacity and duplication at priority 7 — a judge at their `max_assignments` cap, or a duplicate non-terminal assignment for the same judge–project pair, is rejected with `ERR_CONSTRAINT_VIOLATION` — and referential integrity at priority 8.

The auto mode's selector is deterministic. A judge is eligible only when all of the following hold: the judge is `ACTIVE`; the judge belongs to the same edition as the project; `active_assignment_count` is strictly below `max_assignments`; no conflict row exists pairing the judge with the project; and no existing assignment for the pair sits in a non-terminal state. There is no requirement that the judge's id differ from the project's `mentor_id` — those are different entity spaces — but a conflict row auto-created by a prior recusal excludes the judge all the same. Eligible judges are ranked by expertise match first: a judge whose `expertise_category_ids` contains the project's `category_id` ranks above one without it. Ties break on the lower `active_assignment_count`, and any remaining tie breaks on the earlier judge `created_at`. If the eligible set is empty, the request fails with `ERR_NO_ELIGIBLE_JUDGE` (409). The selector assigns exactly one judge per call; the director repeats the call to seat additional judges on the same project.

### 3.5. Scoring, Normalization, and Project Aggregates

Scoring begins once the edition enters `JUDGING`. A judge submits a score sheet against one of their own assignments still in `ASSIGNED` — ownership is checked, so scoring someone else's assignment is `ERR_FORBIDDEN` — carrying a single integer `raw_score` from 0 to 100. The edition must be in `JUDGING` at that moment, or the submission is rejected with `ERR_NOT_JUDGING_PHASE`; because publishing advancement requires every confirmed project to be fully judged, a live `ASSIGNED` assignment on a confirmed project can never outlive the judging phase, which is why the freeze guard lives on quota edits rather than here. A successful submission moves the assignment `ASSIGNED` → `SUBMITTED`, creates the score sheet with its `judging_assignment_id`, the denormalized `project_id` and `judge_id` (so aggregation and normalization never have to walk back through the assignment), a `submitted_at` logical-clock timestamp, and a computed `normalized_score` — then fires the two recalculations below, decrements the judge's `active_assignment_count` by 1, and, if the project has now reached `max_judges_per_project` submitted sheets, flips its `judging_status` to `JUDGED`.

Normalization is per-judge and per-edition, and it is never incremental: every new submission re-derives the `normalized_score` of every sheet in the judge's current submitted pool, because the pool itself changed. Which formula applies is fixed by the edition's `normalization_algorithm`. Under `Z_SCORE`, the pool is every score sheet by this judge in this edition whose parent assignment is `SUBMITTED`; the system computes the arithmetic mean of the pool's `raw_score` values and the population standard deviation — the square root of the average of the squared deviations from that mean, dividing by the pool count, not the count minus one. If the standard deviation is zero, every sheet in the pool normalizes to 0.000; otherwise each sheet's `normalized_score` is its `raw_score` minus the pool mean, divided by the pool standard deviation, rounded half-up to three decimal places. Under `MIN_MAX`, the same pool is rescale-bounded: each sheet's `normalized_score` is its `raw_score` minus the pool's minimum raw score, divided by the spread between the pool's maximum and minimum, rounded half-up to three decimal places — and if the maximum equals the minimum (a single-sheet pool is the common case), every sheet maps to 0.500. The two variants are not interchangeable: identical judge pools with identical raw scores produce different normalized values under the two algorithms, most visibly where a one-score pool maps to 0.000 under `Z_SCORE` but 0.500 under `MIN_MAX`.

The project's aggregates recompute after every submission and its pool re-normalization. The system collects the `normalized_score` values across the project's own submitted sheets and takes their mean. The `provisional_aggregate` — that mean rounded half-up to two decimal places — is published only once the number of submitted sheets reaches the quorum, defined as `max_judges_per_project` multiplied by `min_quorum_ratio_pct`, divided by 100, and rounded up to a whole number; below quorum, `provisional_aggregate` stays null. When the submitted count reaches `max_judges_per_project` exactly, the same mean, rounded half-up to two decimals, is written to `final_aggregate`, and the provisional value is deliberately left unchanged as the historical snapshot. The rounding order is pinned: normalize each sheet to three decimals first, then average, then round to two — raw scores are never averaged first and normalized second.

Two exit ramps relieve assignments that should not complete. A judge may recuse from their own `ASSIGNED` assignment: the assignment moves to `RECUSED`, the judge's `active_assignment_count` drops by 1, a conflict row for the judge–project pair is created if none exists (feeding future selector runs), and if the project is left with zero remaining `ASSIGNED` assignments its `judging_status` falls back to `UNASSIGNED`. A `FairDirector` may instead release an assignment — the no-show case — which is only permitted while the edition is in `JUDGING`; release moves the assignment to `RELEASED` with the same workload decrement and the same possible fallback of the project to `UNASSIGNED`. `SUBMITTED`, `RECUSED`, and `RELEASED` are all terminal for the assignment.

### 3.6. Booths and Display-Safety Inspection

Logistics at the venue are scheduled against confirmed projects. An `OperationsLead` assigns each `CONFIRMED` project a booth by supplying the `hall`, the `booth_number` within that hall, and the inspection window bounds `inspection_window_start` and `inspection_window_end`. The project must still be `NOT_SCHEDULED`; the window must not be inverted — a start that is not strictly before the end is rejected with `ERR_INVALID_WINDOW`, a priority-6 temporal check that surfaces ahead of any uniqueness failure; and the (`hall`, `booth_number`) pair must be free within this edition, or the request fails with `ERR_BOOTH_TAKEN`. A successful assignment creates the booth record and moves the project's `inspection_status` from `NOT_SCHEDULED` to `SCHEDULED`.

Inspection itself belongs to the `SafetyInspector`, who records a `result` of `PASS` or `FAIL` against a `SCHEDULED` project. The logical clock must read within the scheduled window, both endpoints inclusive — `inspection_window_start` and `inspection_window_end` — or the result is rejected with `ERR_OUTSIDE_WINDOW`. A `PASS` moves the project to `PASSED`. A `FAIL` moves it to `FAILED` and cascades: the project's `registration_status` is withdrawn, ending its season on the spot.

The booth pipeline gates the judging phase. When the `FairDirector` begins judging — `REGISTRATION_CLOSED` → `JUDGING` — every `CONFIRMED` project must already have `inspection_status` `SCHEDULED` or `PASSED`; a single uninspected confirmed project blocks the transition with `ERR_PROJECTS_UNINSPECTED`.

### 3.7. Advancement Publication and Slot Allocation

Publishing advancement is the season's most heavily guarded write. Before the edition may move `JUDGING` → `ADVANCEMENT_PUBLISHED`, every `CONFIRMED` project must have reached `judging_status` `JUDGED` — otherwise the transition is rejected with `ERR_UNJUDGED_PROJECTS` — and the request must carry `expected_fair_edition_version` matching the edition's current `version` per §2.7, so a director who prepared the publication against an edition that has since been mutated (a quota edit, say, which also bumps the edition's version) is stopped with `ERR_STALE_VERSION` (412) rather than publishing over a base they never saw. Inside the same transaction, the publication runs the allocation waterfall, stamps every project's `advancement_result` and `advancement_rank`, sets `advancement_freeze` to true, and increments the edition's `version`.

The allocation waterfall works category by category over the eligible pool: projects whose `registration_status` is `CONFIRMED`, whose `judging_status` is `JUDGED`, and whose `inspection_status` is `PASSED`. Within each category, projects are ranked by `final_aggregate` from highest to lowest; ties break on the higher median of `raw_score` across the project's submitted sheets (with an even number of sheets the median is the mean of the two middle values — sheets of 80 and 82 yield a median of 81); further ties break on the greater count of submitted sheets; and any remaining tie breaks on the earlier project `created_at`, never on the project id. Ranks are 1-based per category, and each project's `advancement_rank` records its position.

Slot assignment follows the ranking. The first `advancement_slots` projects in a category are marked `ADVANCED`. The next tranche forms the waitlist: its depth is the category's slot count divided by two and rounded down, but never less than one, and those projects are marked `WAITLISTED`. Every remaining eligible project is marked `NOT_ADVANCED`. Categories rarely fill exactly, so unused slots — from any category whose eligible pool is smaller than its slot count — flow into a shared at-large pool, which is then distributed one extra slot at a time to the highest-`final_aggregate` `WAITLISTED` projects across all categories, using the same tie-break order, until the at-large pool is exhausted. Projects the publication does not touch retain `advancement_result` `PENDING` and a null `advancement_rank`.

### 3.8. Awards, Scholarships, and Mentor Recognition

Awards are proposed by the `FairDirector` against a project and an `award_type` of `CATEGORY_FIRST`, `CATEGORY_SECOND`, `GRAND_PRIZE`, or `SPECIAL_TOPIC`, and are born `PROPOSED` with no money attached — `scholarship_amount_cents` is computed later, by the waterfall. While the edition is in `JUDGING` or `ADVANCEMENT_PUBLISHED`, a proposed award may be revoked (`PROPOSED` → `REVOKED`); both conferral and any revocation recompute the affected mentor's recognition totals. `CONFERRED` and `REVOKED` are terminal.

The money lives in the edition's scholarship pool — exactly one pool per edition — created with the `fair_edition_id` and a `total_cents` of zero or more. The pool's `remaining_cents` starts at the total and is debited as awards are conferred.

Finalizing awards moves the edition `ADVANCEMENT_PUBLISHED` → `AWARDS_FINALIZED` and is refused outright when the edition has no scholarship pool — `ERR_SCHOLARSHIP_POOL_MISSING`. The waterfall then processes every `PROPOSED` award in the edition in a fixed precedence order: `GRAND_PRIZE` first, then `CATEGORY_FIRST`, then `CATEGORY_SECOND`, then `SPECIAL_TOPIC`. Each award receives the smaller of its tier cap and the pool's remaining balance at that moment — caps of 400000 cents for a grand prize, 300000 for a category first, 150000 for a category second, and 100000 for a special topic. Within a tier, awards are processed in order of the recipient project's `final_aggregate` from highest to lowest, breaking ties on the earlier project `created_at`, never on id. All amounts are integer cents: when the remaining pool is smaller than a cap, the award takes exactly the remaining amount and the pool drops to zero, with no fractional cents anywhere. Every processed award transitions `PROPOSED` → `CONFERRED` with its `scholarship_amount_cents` recorded — including awards that receive 0, which are still conferred — and the pool's `remaining_cents` reflects the total conferred.

Mentor recognition recomputes at finalization, and again on any later award revocation, under two deliberate variants over the same input set — the mentor's projects in the edition, by advancement result and conferred awards. The strict variant, `recognition_points`, drives official tier decisions: 5 points per project whose `advancement_result` is `ADVANCED`, nothing for a `WAITLISTED` project, plus 8 points for a conferred `GRAND_PRIZE`, 4 for a `CATEGORY_FIRST`, 2 for a `CATEGORY_SECOND`, and 1 for a `SPECIAL_TOPIC`. The inclusive variant, `leaderboard_points`, powers the public leaderboard readout: everything in the strict variant, plus 4 points per waitlisted project — the waitlist's 2-point base counted at double weight. Both variants start at 0 and are computed at the same trigger, so identical outcomes yield a leaderboard total strictly greater than the recognition total whenever the mentor has at least one `WAITLISTED` project. The `recognition_tier` derives from the strict total alone: below 10 points `NONE`, at least 10 `BRONZE`, at least 25 `SILVER`, and at least 50 `GOLD`. Mentor records carry all three readouts — `recognition_points`, `leaderboard_points`, and `recognition_tier` — alongside the `full_name` and `email` captured when the `FairDirector` registers each mentor before the season; no uniqueness constraint is enforced on mentor `email` values. A mentor readback exposes the current tier to every authenticated role.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Recording an ethics decision and submitting a score sheet return `201 Created` because each creates a new child record (an ethics review, a score sheet); booth scheduling, conflict declaration, assignment creation, and pool creation likewise return `201 Created`. In the table below, "All roles" means the six authenticated roles of §2.1 — `FairDirector`, `Mentor`, `EthicsReviewer`, `Judge`, `OperationsLead`, and `SafetyInspector`. Every list endpoint accepts `limit` and `offset`; list endpoints additionally accept the filters named in §3 narratives — editions by `status`; categories by `fair_edition_id`; projects by `fair_edition_id`, `category_id`, `mentor_id`, `registration_status`, `judging_status`, or `advancement_result`; research plans by `project_id` or `status`; ethics reviews by `research_plan_id` or `reviewer_mentor_id`; judges by `fair_edition_id` or `status`; judging assignments by `project_id`, `judge_id`, or `status`; score sheets by `project_id`, `judge_id`, or `judging_assignment_id`; booth assignments by `project_id` or `hall`; judge conflicts by `judge_id` or `project_id`; awards by `fair_edition_id`, `project_id`, or `status`; scholarship pools by `fair_edition_id`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/science-fair/_clock/set_current_utc` | Set the server's logical clock | FairDirector |
| POST | `/science-fair/fair-editions` | Create a fair edition | FairDirector |
| GET | `/science-fair/fair-editions` | List fair editions | All roles |
| GET | `/science-fair/fair-editions/{id}` | Get one fair edition | All roles |
| POST | `/science-fair/fair-editions/{id}/open-registration` | Open registration (SETUP → REGISTRATION_OPEN) | FairDirector |
| POST | `/science-fair/fair-editions/{id}/close-registration` | Close registration; run the confirmation/withdrawal sweep | FairDirector |
| POST | `/science-fair/fair-editions/{id}/begin-judging` | Begin the judging phase (REGISTRATION_CLOSED → JUDGING) | FairDirector |
| POST | `/science-fair/fair-editions/{id}/publish-advancement` | Publish advancement; run the allocation waterfall (OCC on edition) | FairDirector |
| POST | `/science-fair/fair-editions/{id}/finalize-awards` | Finalize awards; run the scholarship waterfall and mentor recognition | FairDirector |
| POST | `/science-fair/fair-editions/{id}/archive` | Archive the edition (AWARDS_FINALIZED → ARCHIVED) | FairDirector |
| POST | `/science-fair/categories` | Create a category in an edition | FairDirector |
| GET | `/science-fair/categories` | List categories | All roles |
| GET | `/science-fair/categories/{id}` | Get one category | All roles |
| PATCH | `/science-fair/categories/{id}` | Update category fields such as quota (OCC on parent edition) | FairDirector |
| POST | `/science-fair/mentors` | Register a mentor/teacher | FairDirector |
| GET | `/science-fair/mentors` | List mentors | All roles |
| GET | `/science-fair/mentors/{id}` | Get one mentor, including recognition totals and tier | All roles |
| POST | `/science-fair/projects` | Register a project (DRAFT) | Mentor |
| GET | `/science-fair/projects` | List projects | All roles |
| GET | `/science-fair/projects/{id}` | Get one project | All roles |
| PATCH | `/science-fair/projects/{id}` | Update title, team size, or category (OCC on project) | Mentor, FairDirector |
| POST | `/science-fair/projects/{id}/submit` | Submit a project (DRAFT → SUBMITTED) | Mentor |
| POST | `/science-fair/projects/{id}/withdraw` | Withdraw a project (DRAFT/SUBMITTED → WITHDRAWN) | Mentor |
| POST | `/science-fair/research-plans` | Create a research plan for a project (DRAFT) | Mentor |
| GET | `/science-fair/research-plans` | List research plans | FairDirector, EthicsReviewer, Mentor |
| GET | `/science-fair/research-plans/{id}` | Get one research plan | FairDirector, EthicsReviewer, Mentor |
| PUT | `/science-fair/research-plans/{id}` | Update plan text or risk level; revision loop returns plan to DRAFT | Mentor |
| POST | `/science-fair/research-plans/{id}/submit` | Submit a research plan (DRAFT → SUBMITTED) | Mentor |
| POST | `/science-fair/research-plans/{id}/begin-review` | Take a plan under review (SUBMITTED → UNDER_REVIEW) | EthicsReviewer |
| POST | `/science-fair/research-plans/{id}/decisions` | Record an ethics decision (APPROVE / REJECT / REQUEST_REVISION) | EthicsReviewer |
| GET | `/science-fair/ethics-reviews` | List ethics reviews | FairDirector, EthicsReviewer |
| GET | `/science-fair/ethics-reviews/{id}` | Get one ethics review | FairDirector, EthicsReviewer |
| POST | `/science-fair/judges` | Recruit a judge into an edition (INVITED) | FairDirector |
| GET | `/science-fair/judges` | List judges | All roles |
| GET | `/science-fair/judges/{id}` | Get one judge | All roles |
| POST | `/science-fair/judges/{id}/activate` | Activate a judge (INVITED → ACTIVE) | FairDirector |
| POST | `/science-fair/judges/{id}/deactivate` | Deactivate a judge with zero active assignments | FairDirector |
| POST | `/science-fair/judges/{id}/conflicts` | Declare a judge–project conflict | FairDirector, Judge |
| GET | `/science-fair/judges/{id}/conflicts` | List one judge's conflicts | FairDirector, Judge |
| GET | `/science-fair/judge-conflicts` | List judge conflicts across the edition | FairDirector, Judge |
| GET | `/science-fair/judge-conflicts/{id}` | Get one judge conflict | FairDirector, Judge |
| POST | `/science-fair/projects/{id}/judging-assignments` | Assign a judge to a project (explicit or auto-selector mode) | FairDirector |
| GET | `/science-fair/judging-assignments` | List judging assignments | FairDirector, Judge |
| GET | `/science-fair/judging-assignments/{id}` | Get one judging assignment | FairDirector, Judge |
| POST | `/science-fair/judging-assignments/{id}/score-sheets` | Submit a score sheet (ASSIGNED → SUBMITTED) | Judge |
| POST | `/science-fair/judging-assignments/{id}/recuse` | Recuse from an assignment; auto-declares a conflict | Judge |
| POST | `/science-fair/judging-assignments/{id}/release` | Release an assignment (judge no-show) | FairDirector |
| GET | `/science-fair/score-sheets` | List score sheets | FairDirector, Judge |
| GET | `/science-fair/score-sheets/{id}` | Get one score sheet | FairDirector, Judge |
| POST | `/science-fair/projects/{id}/booth-assignments` | Assign a booth and schedule the inspection window | OperationsLead |
| GET | `/science-fair/booth-assignments` | List booth assignments | FairDirector, OperationsLead, SafetyInspector, Mentor |
| GET | `/science-fair/booth-assignments/{id}` | Get one booth assignment | FairDirector, OperationsLead, SafetyInspector, Mentor |
| POST | `/science-fair/projects/{id}/inspection-result` | Record a display-safety inspection result (PASS / FAIL) | SafetyInspector |
| POST | `/science-fair/awards` | Propose an award for a project (PROPOSED) | FairDirector |
| GET | `/science-fair/awards` | List awards | FairDirector, Mentor, Judge |
| GET | `/science-fair/awards/{id}` | Get one award | FairDirector, Mentor, Judge |
| POST | `/science-fair/awards/{id}/revoke` | Revoke a proposed award | FairDirector |
| POST | `/science-fair/scholarship-pools` | Create the edition's scholarship pool | FairDirector |
| GET | `/science-fair/scholarship-pools` | List scholarship pools | FairDirector |
| GET | `/science-fair/scholarship-pools/{id}` | Get one scholarship pool | FairDirector |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue fixes only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 422 Unprocessable Entity |
| `ERR_RESEARCH_PLAN_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PROJECT_LOCKED` | 409 Conflict |
| `ERR_RATIONALE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_NO_OPEN_CATEGORY` | 409 Conflict |
| `ERR_PROJECTS_UNINSPECTED` | 409 Conflict |
| `ERR_UNJUDGED_PROJECTS` | 409 Conflict |
| `ERR_NOT_JUDGING_PHASE` | 409 Conflict |
| `ERR_ADVANCEMENT_FROZEN` | 409 Conflict |
| `ERR_ALREADY_ASSIGNED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_JUDGE` | 409 Conflict |
| `ERR_JUDGE_HAS_ASSIGNMENTS` | 409 Conflict |
| `ERR_BOOTH_TAKEN` | 422 Unprocessable Entity |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_WINDOW` | 422 Unprocessable Entity |
| `ERR_CONSTRAINT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_REFERENTIAL_INTEGRITY` | 422 Unprocessable Entity |
| `ERR_SCHOLARSHIP_POOL_MISSING` | 422 Unprocessable Entity |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |

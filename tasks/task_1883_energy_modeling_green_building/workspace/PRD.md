# Energy Modeling & Green Building Certification API — Product Requirements Document

## 1. Introduction

Green building certification is a multi-year, multi-party engagement. A consultancy shepherds a building project from early energy modeling through design-phase and construction-phase credit submissions, answers reviewer clarifications, coordinates independent commissioning, and — years after the plaque goes on the wall — reports measured performance to keep the certification alive. Every step carries money (submission fees, incentive programs), evidence (credit documentation), and accountability (who documented what, who reviewed it, who certified the building).

This document specifies an API that administers that engagement end to end for a LEED consulting practice. A project is registered under a rating system and a compliance path; energy modelers build and lock baseline and proposed models; administrators assemble a credit strategy from a catalog and assign documentation owners; phase packages are submitted against a fee budget; reviewers comment, award, or deny; independent commissioning agents complete prerequisite tasks; once the project is certified, incentive applications are approved against the achieved level and a cost premium analysis quantifies the green premium net of stacked incentives; performance reports then tile the years after certification and drive recertification or lapse.

Three themes cut across everything that follows: segregation of duties between the people who prepare evidence and the people who submit or review it; optimistic concurrency on the project record, so that a stale view of the strategy or the model inventory never silently overwrites newer work; and exact arithmetic — integer cents and half-up rounding — wherever money, percentages, or points are computed.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, formats, and evaluation orders that apply uniformly to the whole API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes six roles: `ProgramAdmin`, `ProjectAdministrator`, `EnergyModeler`, `DocumentationSpecialist`, `CommissioningAgent`, and `CertificationReviewer`; the label `Any` marks operations open to every authenticated context. Performing an operation outside one's role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

Four of the roles are entity-backed by the consultancy's roster. When `X-User-Role` is `ProjectAdministrator`, `EnergyModeler`, `DocumentationSpecialist`, or `CommissioningAgent`, `X-User-ID` is the `id` of the acting `TeamMember`; ownership checks on any resource that references a team member — a project's `administrator_id`, a model's `created_by`, an attempt's `documentation_owner_id`, a commissioning task's `agent_id` — compare that field to `X-User-ID`. When `X-User-Role` is `ProgramAdmin` or `CertificationReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records no ownership for it and never compares it to any entity's `id`. Read access is universal: every listing and detail endpoint accepts `Any` authenticated role.

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

List endpoints accept two query parameters. `limit` caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` skips a number of items before returning the page and defaults to 0. Unless otherwise specified, every list is sorted by `created_at` in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` object.

### 2.4. Common Resource Properties

Every resource in the system — team members, certification projects, credit library entries, energy models, credit attempts, review comments, commissioning tasks, incentive programs, project incentive applications, cost premium analyses, and performance reports — shares four system-managed properties:

- `id` — a server-minted UUID with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed whenever the resource changes.
- `version` — an integer beginning at 1 and incremented on every mutation.

A mutation is any change to the resource, including the recomputation of derived totals and automatic cascade effects: when the server recalculates a project's points totals or demotes an attempt whose pinned model was superseded, the touched resource's `updated_at` refreshes and its `version` increments.

### 2.5. Project Versioning and Optimistic Concurrency Control

The certification project is the consistency anchor of an engagement, and its `version` advances far more often than direct edits to the project record suggest. Locking the credit strategy, submitting or withdrawing a phase package, issuing the certification decision, entering recertification review, confirming recertification or lapse, creating or dropping a credit attempt, creating an energy model, and each automatic phase bubble-up all increment the project's `version` by one.

Two write operations are guarded against stale views of the project. Locking the credit strategy requires the request to carry `expected_project_version` holding the project's `version` as last observed by the client; if the project's current `version` no longer matches — for example because another writer created or dropped an attempt, so the strategy membership the client believes it is locking has changed — the lock is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). Creating an energy model carries the same requirement and the same rejection: a modeler whose last observed project version has been overtaken — for instance because another model create has already altered the project's model inventory — is working from a stale view, and the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412). `expected_project_version` is non-optional on both operations; no other endpoint accepts a version field.

### 2.6. Money, Percentages, and Rounding Discipline

All monetary values in the system — budgets, fees, modeled energy costs, incentive amounts, savings, premiums — are integer numbers of cents; fractional cents do not exist anywhere. Percentages, such as model improvement and performance gap figures, are numbers with exactly two decimal places, rounded half up. Payback periods are numbers with exactly one decimal place, also rounded half up.

One rounding rule deserves emphasis because it determines certification outcomes: credit points are rounded per attempt, to the nearest integer with halves rounded up, before any project-level summation. Rounding only the project total is a different, and forbidden, operation; §3.5 works through the exact rule and a concrete example.

### 2.7. Request Validation Order and Error Precedence

When a request violates several rules at once, the returned error is the one belonging to the earliest stage of a fixed evaluation ladder:

1. Header presence — a missing or empty `X-User-ID` or `X-User-Role` yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. Body conformance — required fields present, types valid, enum members valid, datetime ordering valid; violations yield `ERR_INVALID_REQUEST` (HTTP 400).
3. Role permission — an operation outside the caller's role yields `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).
4. Ownership on owner-restricted actions — the documentation-owner and assigned-agent checks yield `ERR_NOT_DOCUMENTATION_OWNER` or `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403).
5. Existence — path identifiers and body foreign keys must resolve, checked left to right, yielding the appropriate not-found code (HTTP 404; §2.8).
6. Stale project version — on the two OCC-guarded writes of §2.5, a version mismatch yields `ERR_STALE_PROJECT_VERSION` (HTTP 412).
7. State validity — the target resource must be in a from-state the requested transition allows, and the creation-time parent-state gates apply at this stage as well; violations yield the `ERR_INVALID_PROJECT_STATE` / `ERR_INVALID_CREDIT_ATTEMPT_STATE` / `ERR_INVALID_MODEL_STATE` / `ERR_INVALID_COMMENT_STATE` / `ERR_INVALID_TASK_STATE` / `ERR_INVALID_INCENTIVE_STATE` / `ERR_INVALID_REPORT_STATE` family (HTTP 409).
8. Compliance gates — segregation of duties, commissioning-agent independence, prerequisites awarded before certification, and the minimum modeled improvement (HTTP 403, 409, or 422 per gate).
9. Referential attribute checks — team-member specialty and attempt-phase compatibility, yielding `ERR_INVALID_TEAM_MEMBER_SPECIALTY` or `ERR_INVALID_REQUEST` (HTTP 422).
10. Uniqueness and structural constraints — duplicate attempts or applications, the one-analysis-per-project rule, schedule and period conflicts, empty packages, withdrawals after review has started, unresolved comments, report counts, and model lock order (HTTP 409; the empty-package, performance-tolerance, and points-floor cases answer HTTP 422).
11. Fiscal gates — submission funds and certification-gated incentive money (HTTP 402, 409, or 422).

### 2.8. Resource Existence and the Not-Found Family

Every identifier named in a request — path parameters first, left to right, then foreign keys in the body — must resolve to an existing resource. Each resource type carries its own not-found code: `ERR_PROJECT_NOT_FOUND`, `ERR_TEAM_MEMBER_NOT_FOUND`, `ERR_CREDIT_ENTRY_NOT_FOUND`, `ERR_ENERGY_MODEL_NOT_FOUND`, `ERR_CREDIT_ATTEMPT_NOT_FOUND`, `ERR_REVIEW_COMMENT_NOT_FOUND`, `ERR_COMMISSIONING_TASK_NOT_FOUND`, `ERR_INCENTIVE_PROGRAM_NOT_FOUND`, `ERR_PROJECT_INCENTIVE_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`, and `ERR_PERFORMANCE_REPORT_NOT_FOUND`, all HTTP 404. Where a path nests one resource beneath another — a project's performance reports or its cost premium analysis, an attempt's review comments — the parent identifier is validated before the child collection is consulted, so an unknown parent id fails with the parent's code.

### 2.9. Derived Totals, Cascades, and Automatic Reconciliation

A certification project carries derived fields — `fee_balance_cents`, `points_pursued_total`, `points_awarded_total`, `projected_level`, `conservative_level`, `prerequisites_satisfied` — that the server recomputes immediately whenever an input to them changes; consistency is immediate, never eventual. The server also transitions resources without an explicit client request on them: when the last in-flight attempt of a submitted phase resolves, the project bubbles up to its reviewed state on its own; when a newly locked energy model supersedes a pinned one, the attempts that pinned it are flagged stale and, if sitting ready for submittal, demoted back into documentation work. Each such automatic reconciliation is a real mutation on every resource it touches, refreshing `updated_at` and incrementing `version` exactly as §2.4 defines.

### 2.10. The Logical Clock

Certification timestamps come from a server-side logical clock, never from wall-clock time. A `ProgramAdmin` sets it via `POST /_clock/set_current_utc`, supplying `to_iso8601`; the response echoes the new clock value as `current_utc`. Before any such call the clock stands at exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time afterwards. The `certified_at` timestamp fixed at a certification decision, and its refresh on recertification, both read this clock.

## 3. Business Logic & Workflows

### 3.1. The Consultancy Roster and Project Registration

Before any project exists, a `ProgramAdmin` registers the consultancy's roster. Each **team member** is created with a `full_name`, a contact `email` that must be unique across members, a `specialty` of `MANAGEMENT`, `MODELING`, `DOCUMENTATION`, or `COMMISSIONING`, and an `is_independent` flag that defaults to false. Independence marks commissioning-capable members with no involvement in design work; it becomes a precondition for commissioning assignments in §3.6. The roster can be listed with `specialty` and `is_independent` filters.

A `ProjectAdministrator` then registers a **certification project** by supplying its `project_name`, the `rating_system` — `LEED_BD_C`, `LEED_ID_C`, or `LEED_O_M` — the `compliance_path`, the `gross_floor_area_sqft` (a positive whole number of square feet, since it drives the certification fee formula of §3.4), the `target_level` (`CERTIFIED`, `SILVER`, `GOLD`, or `PLATINUM`), and a non-negative `fee_budget_cents` that funds phase submissions. The server records the caller as the project's `administrator_id`, places the project in `REGISTERED`, and opens its fee ledger with `fee_balance_cents` equal to `fee_budget_cents`. The derived scoreboard starts empty: `points_pursued_total` and `points_awarded_total` at zero, `projected_level` and `conservative_level` at `NONE`, `prerequisites_satisfied` false, `certified_level` and `certified_at` null until a certification decision, and `plaque_marketing_rights_granted` false. Projects can be listed filtered by `status` or `administrator_id`, and a project detail read exposes every computed field.

The compliance path matters from day one. A `PRESCRIPTIVE` project never needs an energy model to submit a phase. A `PERFORMANCE` project, by contrast, enforces a minimum modeled energy improvement when its proposed model locks (§3.3) and cannot submit its design package without a locked proposed model (§3.4).

### 3.2. The Credit Catalog, the Ownership Matrix, and the Strategy Lock

A `ProgramAdmin` maintains the **credit library**. Each entry has a unique catalog `credit_code` (industry codes such as EAp1 or EAc1), a `title`, a `category` of `ENERGY_ATMOSPHERE`, `MATERIALS`, `INDOOR_ENVIRONMENT`, `WATER`, `SUSTAINABLE_SITES`, or `INTEGRATIVE`, the `points_possible` it can award (zero or more), an `is_prerequisite` flag, its `phase_eligibility` (`DESIGN`, `CONSTRUCTION`, or `BOTH`), and a `requires_energy_model` flag marking performance credits whose readiness pins a locked proposed model. Catalog entries can be browsed by `category`, `phase_eligibility`, or `is_prerequisite`. Prerequisite entries carry two obligations that echo through the lifecycle: each must be attempted before the strategy locks, and each must ultimately be awarded before the project can be certified.

Against that catalog, a `ProjectAdministrator` assembles the project's strategy by creating **credit attempts** — the rows of the documentation ownership matrix. Attempt creation requires the project to be `REGISTERED` or `STRATEGY_LOCKED`; at any other project state it fails with `ERR_INVALID_PROJECT_STATE`. The creation payload names the `project_id`, the `credit_library_entry_id`, the `phase` (`DESIGN` or `CONSTRUCTION`), and the `documentation_owner_id`. Three checks bind the selection. The phase must be compatible with the entry's `phase_eligibility` — a `DESIGN`-only entry cannot be attempted as a construction credit, a `CONSTRUCTION`-only entry cannot be attempted as a design credit, and `BOTH` accepts either — otherwise `ERR_INVALID_REQUEST`. The owner must be a team member whose `specialty` is `DOCUMENTATION`, otherwise `ERR_INVALID_TEAM_MEMBER_SPECIALTY` (HTTP 422). And the project may hold at most one attempt per `credit_code` among attempts not yet dropped, otherwise `ERR_DUPLICATE_CREDIT_ATTEMPT` (HTTP 409).

Creation snapshots the catalog: the attempt permanently pins the entry's `credit_code`, `points_possible`, and `is_prerequisite` at their creation-time values, so later catalog edits never rewrite a live strategy. The new attempt starts in `SELECTED` with its `submission_round` at zero, `pinned_proposed_model_id` null, `has_stale_model_pin` false, and `raw_points_earned` and `points_awarded` null until an award. Each creation recomputes the project's `points_pursued_total` — the sum of `points_possible` over every attempt not in `DROPPED` — and increments the project's `version` by one. Attempt listings filter by `project_id`, `credit_library_entry_id`, `documentation_owner_id`, `pinned_proposed_model_id`, `status`, or `phase`.

Assigning a documentation owner moves the attempt forward. From `SELECTED`, the assignment transitions the attempt `SELECTED → DOCUMENTATION_IN_PROGRESS`; performed while the attempt is already in `DOCUMENTATION_IN_PROGRESS`, the same operation simply replaces the owner and leaves the status unchanged. In both cases the new owner's `specialty` must be `DOCUMENTATION`, failing which the assignment is rejected with `ERR_INVALID_TEAM_MEMBER_SPECIALTY`.

When the owner judges the documentation complete, they mark the attempt ready, moving it `DOCUMENTATION_IN_PROGRESS → READY_FOR_SUBMITTAL`. Marking ready is owner-only: a caller whose `X-User-ID` does not equal the attempt's `documentation_owner_id` is rejected with `ERR_NOT_DOCUMENTATION_OWNER` (HTTP 403). For a credit whose catalog entry has `requires_energy_model` true, readiness additionally requires a `LOCKED` proposed model on the project — otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409) — and the mark-ready act pins that model: `pinned_proposed_model_id` is set to the locked proposed model's `id` and `has_stale_model_pin` to false, freezing the exact model version the documentation references. What a later re-lock does to this pin is the cascade of §3.3.

An attempt that has not yet been submitted can be dropped from the strategy: from `SELECTED`, `DOCUMENTATION_IN_PROGRESS`, or `READY_FOR_SUBMITTAL`, dropping moves the attempt to `DROPPED`. The drop recomputes `points_pursued_total` and increments the project's `version`; create and drop are exact compensating pairs, so selecting a credit and later dropping it leaves the pursued-points total precisely where it was.

When the strategy is complete, the administrator locks it. The lock is OCC-guarded per §2.5: the request must carry `expected_project_version`, and a stale value is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412) before any business check runs — the version check outranks the strategy checks, so a client locking an outdated membership sees the version error rather than a misleading completeness error. Two completeness gates then apply. At least one attempt not in `DROPPED` must exist, otherwise `ERR_EMPTY_CREDIT_STRATEGY` (HTTP 422). And every prerequisite catalog entry must have at least one attempt not in `DROPPED` on this project, otherwise `ERR_PREREQUISITE_CREDIT_MISSING` (HTTP 409). A successful lock moves the project `REGISTERED → STRATEGY_LOCKED` and increments its `version` by one.

### 3.3. Energy Models: Baseline, Proposed, and the Lock Cascade

An `EnergyModeler` builds the project's models. Creating a model requires the project to be `REGISTERED`, `STRATEGY_LOCKED`, `DESIGN_REVIEWED`, or `CONSTRUCTION_REVIEWED` — modeling is not accepted while a phase is in review or after certification, and the create otherwise fails with `ERR_INVALID_PROJECT_STATE`. The payload carries the `project_id`, the `model_type` (`BASELINE` or `PROPOSED`), the `modeling_standard` (`ASHRAE_90_1_2016` or `ASHRAE_90_1_2019`), two positive integer-cent figures — `annual_energy_cost_modeled_cents`, the modeled annual energy cost including all measures whether confirmed or not, and `annual_energy_cost_confirmed_only_cents`, the modeled cost counting only confirmed efficiency measures — and an `includes_unconfirmed_measures` flag, defaulting to false, recording whether the modeled figure reflects measures not yet confirmed. Because model creation mutates the project's inventory, it is OCC-guarded exactly as §2.5 describes: the request must carry `expected_project_version`, and a stale value fails with `ERR_STALE_PROJECT_VERSION` (HTTP 412).

Each new model receives a `version_index` that sequences per project and model type — the first baseline on a project is 1, the next baseline 2, independently of the proposed sequence — computed as one more than the largest existing index for that pair. The server stamps the model's `created_by` with the caller's `X-User-ID`, starts it in `DRAFT`, and increments the owning project's `version` by one. Models list filtered by `project_id`, `model_type`, `status`, or `created_by`.

Locking is the pivotal act, performed by an `EnergyModeler`. Only a `DRAFT` model can be locked; any other state fails with `ERR_INVALID_MODEL_STATE`. A proposed model cannot lock before its baseline: locking a `PROPOSED` model while the project has no `LOCKED` baseline is rejected with `ERR_BASELINE_MODEL_NOT_LOCKED` (HTTP 409). At most one model per project and model type may be `LOCKED` at any time.

When a `PROPOSED` model locks, two improvement percentages are computed against the project's `LOCKED` baseline, each rounded half up to two decimal places. `improvement_pct_provisional` is the difference between the baseline's and the proposed model's `annual_energy_cost_modeled_cents`, divided by the baseline's `annual_energy_cost_modeled_cents`, multiplied by one hundred. `improvement_pct_final` is the same ratio computed over the two models' `annual_energy_cost_confirmed_only_cents` figures. The provisional variant therefore reflects unconfirmed measures while the final variant excludes them; when no unconfirmed measures are included, the two coincide. Both fields remain null on baseline models and on proposed models that have not locked.

The final variant gates the performance path: on a `PERFORMANCE`-path project, a proposed model whose `improvement_pct_final` would fall below 5.00 cannot lock — the lock is rejected with `ERR_MINIMUM_IMPROVEMENT_NOT_MET` (HTTP 422), and the boundary is inclusive, so an improvement of exactly 5.00 passes.

Locking also supersedes. The previously `LOCKED` model of the same project and model type, if one exists, transitions to `SUPERSEDED`, the terminal state of every model. That supersession cascades into the credit strategy: every attempt whose `pinned_proposed_model_id` names the superseded model is flagged with `has_stale_model_pin` set to true, and among those, any attempt sitting in `READY_FOR_SUBMITTAL` is automatically demoted to `DOCUMENTATION_IN_PROGRESS` — its documentation can no longer truthfully reference the model it pinned. Attempts in other states keep their status but carry the stale flag until they are re-pinned by a fresh mark-ready.

### 3.4. Phase Packages: Submission Fees, Segregation of Duties, Withdrawal

Phase submission is a package operation: in one act, the administrator submits every attempt of the named `phase` (`DESIGN` or `CONSTRUCTION`) currently sitting in `READY_FOR_SUBMITTAL`. A package containing zero ready attempts is rejected with `ERR_EMPTY_SUBMISSION_PACKAGE` (HTTP 422); the zero-count boundary is enforced.

The package is paid from the project's fee ledger. The certification fee for a phase is its base — 250,000 cents for `DESIGN`, 350,000 cents for `CONSTRUCTION` — plus 5,000 cents for every whole-or-partial thousand square feet of `gross_floor_area_sqft`, the area being divided by one thousand and rounded up to a whole number before multiplying; the total is capped at 2,000,000 cents, so the charged fee is the smaller of the computed amount and the cap. Submission debits the fee from `fee_balance_cents`, and when the balance does not cover it the submission fails with `ERR_INSUFFICIENT_SUBMISSION_FUNDS` (HTTP 402).

Design submission moves the project `STRATEGY_LOCKED → DESIGN_SUBMITTED`. Beyond the non-empty package and the funds, two guards apply. On a `PERFORMANCE`-path project, a `LOCKED` proposed model must exist, otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409). And segregation of duties forbids the submitter from vouching for their own paperwork: if the calling administrator is the `documentation_owner_id` of any attempt included in the package, the submission is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403). On success, every included attempt transitions `READY_FOR_SUBMITTAL → SUBMITTED` with its `submission_round` incremented by one, the fee is debited, the projected and conservative levels are recomputed against the new input set, and the project's `version` increments by one.

Construction submission moves the project `DESIGN_REVIEWED → CONSTRUCTION_SUBMITTED` under the same package, funds, and segregation rules, plus the commissioning gate: every commissioning task flagged `is_prerequisite_linked` on the project must already be `PASSED`, otherwise the submission fails with `ERR_COMMISSIONING_INCOMPLETE` (HTTP 409). The tasks behind that gate are the subject of §3.6.

Either package can be withdrawn, but only before the review body has engaged with it. Withdrawing the design package returns the project `DESIGN_SUBMITTED → STRATEGY_LOCKED`; withdrawing the construction package returns it `CONSTRUCTION_SUBMITTED → DESIGN_REVIEWED`. If any review comment exists on any `SUBMITTED` attempt of that phase, withdrawal is rejected with `ERR_REVIEW_ALREADY_STARTED` (HTTP 409). A successful withdrawal moves every `SUBMITTED` attempt of the phase back to `READY_FOR_SUBMITTAL`, refunds the phase fee computed by the same formula from the same inputs — so a submission followed by a withdrawal leaves `fee_balance_cents` exactly where it started — recomputes the projected level, and increments the project's `version` by one.

### 3.5. The Review Loop: Comments, Clarification, Awards, and Appeals

Review begins per attempt. A `CertificationReviewer` can open review on an attempt in `SUBMITTED`, resume one in `RESUBMITTED`, or reopen one in `APPEALED`, each moving the attempt to `UNDER_REVIEW`; the parent project must be in `DESIGN_SUBMITTED` or `CONSTRUCTION_SUBMITTED`, otherwise the action fails with `ERR_INVALID_PROJECT_STATE`. Resuming a resubmitted attempt carries an extra gate: every review comment on the attempt must already be `ACCEPTED`, otherwise `ERR_UNRESOLVED_REVIEW_COMMENTS` (HTTP 409). Beginning review recomputes the projected level — the attempt remains inside, or re-enters, the optimistic input set defined below. Acting on an attempt in any other state is rejected with `ERR_INVALID_CREDIT_ATTEMPT_STATE` (HTTP 409).

While an attempt is `UNDER_REVIEW`, the reviewer posts comments, each carrying the `credit_attempt_id`, a `severity` of `CLARIFICATION` or `DEFICIENCY`, and the `comment_text`. Posting stamps the comment `OPEN`, copies the attempt's current `submission_round` into the comment's `round`, and moves the attempt `UNDER_REVIEW → CLARIFICATION_REQUESTED`; because a clarification-pending attempt no longer counts toward the optimistic projection, the projected level is recomputed at that moment. An attempt's comment thread is listed under the attempt itself.

Answering comments belongs to the documentation owner alone. Responding moves a comment `OPEN → ADDRESSED`, or, for a reopened thread, `REOPENED → ADDRESSED`, in the latter case overwriting the prior `response_text`; any caller other than the attempt's `documentation_owner_id` is rejected with `ERR_NOT_DOCUMENTATION_OWNER` (HTTP 403). When every comment on the attempt is `ADDRESSED`, the owner resubmits: the attempt moves `CLARIFICATION_REQUESTED → RESUBMITTED` and its `submission_round` increments again, while resubmitting with any comment still `OPEN` or `REOPENED` fails with `ERR_UNRESOLVED_REVIEW_COMMENTS` (HTTP 409). Review of a resubmitted attempt then arbitrates each thread: the reviewer accepts an `ADDRESSED` comment, moving it to the terminal `ACCEPTED`, or reopens it, moving it `ADDRESSED → REOPENED`. Both arbitration acts require the attempt to be `RESUBMITTED`, otherwise `ERR_INVALID_COMMENT_STATE` (HTTP 409), and the same code answers comment actions taken from any other wrong state.

The decisive acts are award and denial, both from `UNDER_REVIEW`. Awarding moves the attempt `UNDER_REVIEW → AWARDED`. The reviewer may supply `raw_points_earned`, a fractional figure that must lie between zero and the attempt's `points_possible`, both bounds inclusive — otherwise `ERR_INVALID_REQUEST`. For a `requires_energy_model` credit the reviewer may instead omit the figure, and the system derives it from the pinned proposed model's `improvement_pct_final` using the published buckets: at least 18 percent improvement earns 10 points, at least 14 earns 8, at least 10 earns 6, at least 8 earns 4, at least 5 earns 2, and anything below 5 earns zero, every boundary inclusive. Either way, the attempt's `points_awarded` is the raw figure rounded half up to an integer — per attempt, before any summation, so two credits earning 1.4 apiece contribute 1 and 1 to the project, never a rounded total of 3.

The award then cascades through the project. `points_awarded_total` becomes the sum of `points_awarded` over all `AWARDED` attempts, and `conservative_level` is recomputed from that total alone. `prerequisites_satisfied` is recomputed as well — it is true exactly when every prerequisite attempt not in `DROPPED` has been `AWARDED`, so the award of the last outstanding prerequisite flips it true. Denial moves the attempt `UNDER_REVIEW → DENIED`, with an optional `reason` the reviewer may record, and likewise recomputes `prerequisites_satisfied`.

Those totals feed two published levels through a single threshold table: 80 or more points is `PLATINUM`, 60 or more is `GOLD`, 50 or more is `SILVER`, 40 or more is `CERTIFIED`, and below 40 is `NONE`, all boundaries inclusive. The `projected_level` is the optimistic reading — attempts in `SUBMITTED`, `UNDER_REVIEW`, or `RESUBMITTED` count at face value (`points_possible`) on top of the awarded total — while the `conservative_level` counts awarded points only. Attempts in `SELECTED`, `DOCUMENTATION_IN_PROGRESS`, `READY_FOR_SUBMITTAL`, `CLARIFICATION_REQUESTED`, `DENIED`, `APPEALED`, or `DROPPED` enter neither reading. Any attempt status change or award recomputes both levels.

A denied attempt is not finished: the administrator may appeal it, supplying an `appeal_justification`, moving it `DENIED → APPEALED`. If the project had already advanced to its reviewed state, the appeal reopens the phase — the project reverts `DESIGN_REVIEWED → DESIGN_SUBMITTED` or `CONSTRUCTION_REVIEWED → CONSTRUCTION_SUBMITTED` as applicable — because the phase's verdict is no longer complete. An appealed attempt re-enters review through the same reviewer action that opens a submitted one.

That advancement is itself automatic: the moment no attempt of a submitted phase remains in any review-flight state — `SUBMITTED`, `UNDER_REVIEW`, `CLARIFICATION_REQUESTED`, `RESUBMITTED`, or `APPEALED` — the project bubbles up on its own, `DESIGN_SUBMITTED → DESIGN_REVIEWED` or `CONSTRUCTION_SUBMITTED → CONSTRUCTION_REVIEWED`, incrementing its `version` by one. Every award and every denial re-evaluates this bubble-up. The attempt's terminal states are `AWARDED` and `DROPPED`; `DENIED` remains open to appeal.

### 3.6. Commissioning: Independence, Scheduling, and the Prerequisite Gate

Fundamental commissioning is a certification prerequisite, and the system polices both who performs it and when. The administrator schedules each **commissioning task** with the `project_id`, a `task_type` of `OPR_DOCUMENT`, `CX_PLAN`, `FUNCTIONAL_TESTING`, `SYSTEMS_MANUAL`, or `CX_REPORT`, the `agent_id` of the assigned agent, a `scheduled_start` and `scheduled_end`, and an `is_prerequisite_linked` flag marking tasks that belong to the prerequisite gate of §3.4. The agent must be a team member whose `specialty` is `COMMISSIONING` — otherwise `ERR_INVALID_TEAM_MEMBER_SPECIALTY` (HTTP 422) — and must be independent: `is_independent` set to true, and not the person recorded as `created_by` on the project's `LOCKED` proposed model; either failure is rejected with `ERR_CX_AGENT_NOT_INDEPENDENT` (HTTP 403).

The schedule interval is half-open: a task occupies its window from `scheduled_start` up to but not including `scheduled_end`, and the end must be later than the start or creation fails with `ERR_INVALID_REQUEST`. A new task conflicts with any existing task on the same project in `SCHEDULED` or `IN_PROGRESS` whose window intersects it — the new start falling before the existing end while the existing start falls before the new end — and such a conflict is rejected with `ERR_CX_SCHEDULE_OVERLAP` (HTTP 409). Mere adjacency is not a conflict: a new task starting at exactly the moment an existing one ends schedules cleanly. Tasks in `PASSED` or `FAILED` never block anything. Task listings filter by `project_id`, `agent_id`, or `status`.

Execution belongs to the assigned agent and to nobody else. Starting moves a task `SCHEDULED → IN_PROGRESS`; completing it records an `outcome` of `PASSED` or `FAILED` — optionally accompanied by `result_notes` — and moves the task from `IN_PROGRESS` to the matching terminal state, with both `outcome` and `result_notes` null until that moment. A caller whose `X-User-ID` is not the task's `agent_id` fails with `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` (HTTP 403), and starting or completing from the wrong state fails with `ERR_INVALID_TASK_STATE` (HTTP 409). A failed task is never retried in place: a retest is simply a newly scheduled task, which is why failed tasks impose no schedule block. The prerequisite gate of §3.4 consults exactly the tasks flagged `is_prerequisite_linked`: construction submission cannot proceed while any of them has not yet `PASSED`.

### 3.7. The Certification Decision, Incentive Stacking, and the Cost Premium Analysis

Once the construction phase has bubbled up to `CONSTRUCTION_REVIEWED`, the `CertificationReviewer` issues the decision by supplying a `decision` of `CERTIFY` or `DENY`. Certification is gated twice: `prerequisites_satisfied` must be true, otherwise `ERR_PREREQUISITE_NOT_AWARDED` (HTTP 409); and `points_awarded_total` must reach the 40-point floor, otherwise `ERR_INSUFFICIENT_POINTS` (HTTP 422). A `CERTIFY` decision fixes `certified_level` from the threshold table of §3.5 applied to `points_awarded_total`, stamps `certified_at` from the logical clock, sets `plaque_marketing_rights_granted` to true — plaque and marketing rights, granted at this moment and never revoked, retained even if the certification later lapses — and moves the project to `CERTIFIED`. A `DENY` decision moves it to `DENIED`, a terminal state. Either decision increments the project's `version` by one.

Certification unlocks the money. A `ProgramAdmin` catalogs **incentive programs**, each with a unique `program_name`, an `incentive_type` of `TAX_CREDIT`, `GRANT`, or `UTILITY_REBATE`, a positive `benefit_amount_cents`, a `minimum_certification_level`, and an `is_combinable` flag; programs list with an `incentive_type` filter. The administrator then applies the project to a program by naming the `project_id` and the `incentive_program_id`; the application starts `APPLIED` with `claimed_amount_cents` at zero. A second live application — one in `APPLIED`, `APPROVED`, or `DISBURSED` — for the same program on the same project is rejected with `ERR_DUPLICATE_INCENTIVE_APPLICATION` (HTTP 409). Applications list filtered by `project_id`, `incentive_program_id`, or `status`.

Approval belongs to the `ProgramAdmin` and is certification-gated. The project must be `CERTIFIED`, otherwise `ERR_PROJECT_NOT_CERTIFIED` (HTTP 409), and its `certified_level` must be at least the program's `minimum_certification_level` on the ordering `CERTIFIED`, `SILVER`, `GOLD`, `PLATINUM` — a gold-level project qualifies for a silver-floor program but not for a platinum-floor one — otherwise `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` (HTTP 422). Approval moves the application `APPLIED → APPROVED` and sets `claimed_amount_cents` to the program's `benefit_amount_cents`. Disbursement moves an approved application `APPROVED → DISBURSED`, the application's terminal state. Approving or disbursing from the wrong state answers `ERR_INVALID_INCENTIVE_STATE` (HTTP 409).

The **cost premium analysis** quantifies what certification cost and what incentives recovered. It is one-to-one with the project — creating a second one is rejected with `ERR_ANALYSIS_EXISTS` (HTTP 409) — and it requires the project's `LOCKED` baseline and `LOCKED` proposed models to exist, otherwise `ERR_PROPOSED_MODEL_NOT_LOCKED` (HTTP 409). The administrator creates it with the `project_id` and the `incremental_construction_cost_cents`, the green premium over conventional construction as a positive integer of cents. Four quantities then compute in a pinned order, each feeding the next.

First, `annual_energy_savings_cents` is the locked baseline's `annual_energy_cost_confirmed_only_cents` minus the locked proposed model's `annual_energy_cost_confirmed_only_cents`. Second, `incentive_total_cents` runs the stacking waterfall: applications in `APPROVED` or `DISBURSED` are eligible while `APPLIED` ones contribute nothing; applications under combinable programs contribute their full claimed amounts; applications under non-combinable programs contribute, per `incentive_type`, only the largest claimed amount among that type's eligible applications — zero for a type with none; the raw total of the combinable sum plus those per-type maxima is then capped at forty percent of `incremental_construction_cost_cents`, the cap truncated down to a whole cent, and the incentive total is the smaller of the raw total and the cap. The cap's base is always the pre-incentive incremental cost, never the net premium — computing it from the net premium would be circular and is forbidden. Third, `net_cost_premium_cents` is `incremental_construction_cost_cents` minus `incentive_total_cents`. Fourth, `simple_payback_years` is `net_cost_premium_cents` divided by `annual_energy_savings_cents`, rounded half up to one decimal place, using the stored integer-cent operands of the preceding steps. The analysis carries an `analysis_version` starting at 1, and recalculating it — after new incentive approvals or a re-locked model — recomputes all four figures against current data and increments `analysis_version` by one. The analysis is readable on its own and as a sub-resource of the project, where the one-to-one collection returns an array of zero or one element.

### 3.8. Performance Reporting and the Recertification Cycle

Certification is not the end of the engagement: the building must perform. While the project is `CERTIFIED` or already in `PERFORMANCE_REPORTING`, the administrator files **performance reports**; filing at any other project state fails with `ERR_INVALID_PROJECT_STATE` (HTTP 409). The very first report created for a project moves it `CERTIFIED → PERFORMANCE_REPORTING` automatically, incrementing the project's `version` by one. Each report names the `project_id`, a `period_start` and `period_end`, and the measured `actual_annual_energy_cost_cents` as a positive integer of cents. Periods are closed day intervals — both endpoints are inclusive calendar days at UTC day granularity — and the end must fall after the start, otherwise `ERR_INVALID_REQUEST`.

Each report is measured against the project's `LOCKED` proposed model. `performance_gap_pct` is the difference between the report's `actual_annual_energy_cost_cents` and the model's `annual_energy_cost_confirmed_only_cents`, divided by that same confirmed-only figure and multiplied by one hundred, rounded half up to two decimal places. `within_tolerance` is true exactly when the absolute value of the gap is at most 15.00, the boundary inclusive — a gap of exactly 15.00 percent in either direction passes.

Reports must tile the performance era without seams or overlaps. The anchor is the `ACCEPTED` report with the latest `period_end`, if one exists. The required start of a new period is the calendar date of the project's `certified_at` when there is no anchor, and the day immediately after the anchor's `period_end` otherwise. A `period_start` earlier than the required start collides with tiled history and is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409) — a single shared day is a conflict. A `period_start` later than the required start leaves untiled days between periods and is rejected with `ERR_REPORT_PERIOD_GAP` (HTTP 409). Independently of the anchor arithmetic, a new period that shares any day with an existing report in `DRAFT`, `SUBMITTED`, or `ACCEPTED` is likewise rejected with `ERR_REPORT_PERIOD_OVERLAP`. Accepted periods never overlap by construction, so anchor selection needs no tie-break. A new report starts in `DRAFT` with `rejection_reason` null, and a project's reports are listed under the project itself.

Filing moves a report `DRAFT → SUBMITTED`. Verification then belongs to the `CertificationReviewer`, who supplies an `outcome` of `ACCEPT` or `REJECT`. Acceptance requires `within_tolerance` to be true — accepting a report whose absolute gap exceeds 15.00 percent fails with `ERR_PERFORMANCE_GAP_EXCEEDED` (HTTP 422). Rejection requires the reviewer to supply a `rejection_reason`, which is recorded on the report; omitting it fails with `ERR_INVALID_REQUEST`. Acceptance moves the report `SUBMITTED → ACCEPTED` (its terminal state), rejection moves it `SUBMITTED → REJECTED`, and a `REJECTED` report returns `REJECTED → DRAFT` when the administrator revises it for correction. Submitting, verifying, or revising from the wrong state answers `ERR_INVALID_REPORT_STATE` (HTTP 409).

With at least two `ACCEPTED` reports in hand, the administrator enters recertification review, moving the project `PERFORMANCE_REPORTING → RECERTIFICATION_REVIEW`; fewer than two accepted reports fails with `ERR_INSUFFICIENT_PERFORMANCE_REPORTS` (HTTP 409). The reviewer then confirms the cycle by supplying an `outcome` of `RECERTIFY` or `LAPSE`. Recertification returns the project `RECERTIFICATION_REVIEW → CERTIFIED`, refreshes `certified_at` to the logical clock's current instant, and restarts the reporting cycle — from `CERTIFIED` to `PERFORMANCE_REPORTING` to `RECERTIFICATION_REVIEW` and back again. Lapse moves the project to the terminal `LAPSED`; the plaque and marketing rights granted at certification survive it. Both confirmations increment the project's `version` by one. The project's other terminal state, `DENIED`, is reached only at the original decision of §3.7.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`: registering a team member, creating a credit library entry, registering a certification project, creating an energy model, creating a credit attempt, posting a review comment, scheduling a commissioning task, creating an incentive program, filing a project incentive application, creating a cost premium analysis, and creating a performance report. All other successful operations — state transitions, actions on existing resources, and reads — return `200 OK`. Request payloads and computed fields are specified by the narratives of §2 and §3; the table below is a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | ProgramAdmin |
| POST | `/team-members` | Register a team member | ProgramAdmin |
| GET | `/team-members` | List team members | Any |
| GET | `/team-members/{memberId}` | Get a team member | Any |
| POST | `/credit-library-entries` | Create a credit catalog entry | ProgramAdmin |
| GET | `/credit-library-entries` | List credit catalog entries | Any |
| GET | `/credit-library-entries/{entryId}` | Get a credit catalog entry | Any |
| POST | `/certification-projects` | Register a certification project | ProjectAdministrator |
| GET | `/certification-projects` | List certification projects | Any |
| GET | `/certification-projects/{projectId}` | Get a certification project (all computed fields) | Any |
| POST | `/certification-projects/{projectId}/lock-strategy` | Lock the credit strategy (OCC-guarded) | ProjectAdministrator |
| POST | `/certification-projects/{projectId}/submit-phase` | Submit all ready attempts of a phase as one review package; debits the phase fee | ProjectAdministrator |
| POST | `/certification-projects/{projectId}/withdraw-phase` | Withdraw a submitted phase before review starts; refunds the phase fee | ProjectAdministrator |
| POST | `/certification-projects/{projectId}/issue-decision` | Certification decision from CONSTRUCTION_REVIEWED; CERTIFY fixes the level and grants plaque/marketing rights | CertificationReviewer |
| POST | `/certification-projects/{projectId}/submit-recertification` | Enter recertification review after the performance period | ProjectAdministrator |
| POST | `/certification-projects/{projectId}/confirm-recertification` | Confirm recertification (cycle back to CERTIFIED) or lapse the certification | CertificationReviewer |
| GET | `/certification-projects/{id}/performance-reports` | List performance reports of a project | Any |
| GET | `/certification-projects/{id}/cost-premium-analysis` | Get the project's cost premium analysis (array of 0–1) | Any |
| POST | `/energy-models` | Create a BASELINE or PROPOSED energy model (OCC-guarded on the project version) | EnergyModeler |
| GET | `/energy-models` | List energy models | Any |
| GET | `/energy-models/{modelId}` | Get an energy model | Any |
| POST | `/energy-models/{modelId}/lock` | Lock a DRAFT model; supersedes the previously locked model of the same type and flags stale credit pins | EnergyModeler |
| POST | `/credit-attempts` | Select a credit into the project strategy (documentation ownership matrix row) | ProjectAdministrator |
| GET | `/credit-attempts` | List credit attempts | Any |
| GET | `/credit-attempts/{attemptId}` | Get a credit attempt | Any |
| POST | `/credit-attempts/{attemptId}/assign-owner` | Assign or reassign the documentation owner; from SELECTED starts documentation work | ProjectAdministrator |
| POST | `/credit-attempts/{attemptId}/mark-ready` | Owner marks documentation complete; model-linked credits pin the locked proposed model | DocumentationSpecialist |
| POST | `/credit-attempts/{attemptId}/drop` | Drop a not-yet-submitted attempt from the strategy | ProjectAdministrator |
| POST | `/credit-attempts/{attemptId}/begin-review` | Reviewer opens review on a SUBMITTED attempt, resumes a RESUBMITTED one, or reopens an APPEALED one | CertificationReviewer |
| POST | `/credit-attempts/{attemptId}/resubmit` | Owner resubmits after addressing all review comments | DocumentationSpecialist |
| POST | `/credit-attempts/{attemptId}/award` | Reviewer awards points (explicit raw value or bucket-computed for model-linked credits) | CertificationReviewer |
| POST | `/credit-attempts/{attemptId}/deny` | Reviewer denies the credit | CertificationReviewer |
| POST | `/credit-attempts/{attemptId}/appeal` | Appeal a denied credit; reopens the phase review | ProjectAdministrator |
| GET | `/credit-attempts/{id}/review-comments` | List review comments on an attempt | Any |
| POST | `/review-comments` | Reviewer posts a comment on an attempt under review; moves it to clarification-requested | CertificationReviewer |
| POST | `/review-comments/{commentId}/respond` | Documentation owner responds to an open or reopened comment | DocumentationSpecialist |
| POST | `/review-comments/{commentId}/accept` | Reviewer accepts a response (attempt must be resubmitted) | CertificationReviewer |
| POST | `/review-comments/{commentId}/reopen` | Reviewer reopens an addressed comment (attempt must be resubmitted) | CertificationReviewer |
| POST | `/commissioning-tasks` | Schedule a commissioning task (half-open overlap check, independence gate) | ProjectAdministrator |
| GET | `/commissioning-tasks` | List commissioning tasks | Any |
| GET | `/commissioning-tasks/{taskId}` | Get a commissioning task | Any |
| POST | `/commissioning-tasks/{taskId}/start` | Assigned agent starts the task | CommissioningAgent |
| POST | `/commissioning-tasks/{taskId}/complete` | Assigned agent records the outcome | CommissioningAgent |
| POST | `/incentive-programs` | Create an incentive program | ProgramAdmin |
| GET | `/incentive-programs` | List incentive programs | Any |
| GET | `/incentive-programs/{programId}` | Get an incentive program | Any |
| POST | `/project-incentives` | Apply a project to an incentive program | ProjectAdministrator |
| GET | `/project-incentives` | List project incentive applications | Any |
| GET | `/project-incentives/{projectIncentiveId}` | Get a project incentive application | Any |
| POST | `/project-incentives/{projectIncentiveId}/approve` | Approve an application (requires a certified project at sufficient level) | ProgramAdmin |
| POST | `/project-incentives/{projectIncentiveId}/disburse` | Disburse an approved incentive | ProgramAdmin |
| POST | `/cost-premium-analyses` | Create the project's cost premium analysis (1:1); requires locked baseline and proposed models | ProjectAdministrator |
| GET | `/cost-premium-analyses/{analysisId}` | Get a cost premium analysis | Any |
| POST | `/cost-premium-analyses/{analysisId}/recalculate` | Recompute savings, incentive total, net premium, and payback | ProjectAdministrator |
| POST | `/performance-reports` | Create a performance period report (closed-interval tiling against the accepted anchor) | ProjectAdministrator |
| GET | `/performance-reports/{reportId}` | Get a performance report | Any |
| POST | `/performance-reports/{reportId}/submit` | Submit a draft report for verification | ProjectAdministrator |
| POST | `/performance-reports/{reportId}/verify` | Reviewer accepts (requires within-tolerance) or rejects (requires a reason) | CertificationReviewer |
| POST | `/performance-reports/{reportId}/revise` | Send a rejected report back to draft for correction | ProjectAdministrator |

## 5. Error Code Catalogue

The catalogue below lists every error identifier and its HTTP status. Trigger conditions are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_DOCUMENTATION_OWNER` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_COMMISSIONING_AGENT` | 403 Forbidden |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_TEAM_MEMBER_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_ENERGY_MODEL_NOT_FOUND` | 404 Not Found |
| `ERR_CREDIT_ATTEMPT_NOT_FOUND` | 404 Not Found |
| `ERR_REVIEW_COMMENT_NOT_FOUND` | 404 Not Found |
| `ERR_COMMISSIONING_TASK_NOT_FOUND` | 404 Not Found |
| `ERR_INCENTIVE_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_PROJECT_INCENTIVE_NOT_FOUND` | 404 Not Found |
| `ERR_ANALYSIS_NOT_FOUND` | 404 Not Found |
| `ERR_PERFORMANCE_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PROJECT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_PROJECT_STATE` | 409 Conflict |
| `ERR_INVALID_CREDIT_ATTEMPT_STATE` | 409 Conflict |
| `ERR_INVALID_MODEL_STATE` | 409 Conflict |
| `ERR_INVALID_COMMENT_STATE` | 409 Conflict |
| `ERR_INVALID_TASK_STATE` | 409 Conflict |
| `ERR_INVALID_INCENTIVE_STATE` | 409 Conflict |
| `ERR_INVALID_REPORT_STATE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_COMMISSIONING_INCOMPLETE` | 409 Conflict |
| `ERR_CX_AGENT_NOT_INDEPENDENT` | 403 Forbidden |
| `ERR_PREREQUISITE_NOT_AWARDED` | 409 Conflict |
| `ERR_MINIMUM_IMPROVEMENT_NOT_MET` | 422 Unprocessable Entity |
| `ERR_INVALID_TEAM_MEMBER_SPECIALTY` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_CREDIT_ATTEMPT` | 409 Conflict |
| `ERR_DUPLICATE_INCENTIVE_APPLICATION` | 409 Conflict |
| `ERR_ANALYSIS_EXISTS` | 409 Conflict |
| `ERR_CX_SCHEDULE_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_REPORT_PERIOD_GAP` | 409 Conflict |
| `ERR_EMPTY_SUBMISSION_PACKAGE` | 422 Unprocessable Entity |
| `ERR_REVIEW_ALREADY_STARTED` | 409 Conflict |
| `ERR_EMPTY_CREDIT_STRATEGY` | 422 Unprocessable Entity |
| `ERR_PREREQUISITE_CREDIT_MISSING` | 409 Conflict |
| `ERR_UNRESOLVED_REVIEW_COMMENTS` | 409 Conflict |
| `ERR_INSUFFICIENT_PERFORMANCE_REPORTS` | 409 Conflict |
| `ERR_PERFORMANCE_GAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_BASELINE_MODEL_NOT_LOCKED` | 409 Conflict |
| `ERR_PROPOSED_MODEL_NOT_LOCKED` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_SUBMISSION_FUNDS` | 402 Payment Required |
| `ERR_PROJECT_NOT_CERTIFIED` | 409 Conflict |
| `ERR_CERTIFICATION_LEVEL_INSUFFICIENT` | 422 Unprocessable Entity |

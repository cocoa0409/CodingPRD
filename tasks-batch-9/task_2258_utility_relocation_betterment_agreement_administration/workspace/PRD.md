# Utility Relocation & Betterment Agreement Administration API — Product Requirements Document

## 1. Introduction

When a state transportation department widens a highway, the utilities already occupying the corridor have to move, and the question of who pays for that move is decided long before a shovel enters the ground. The utility coordination office lives inside that question. It identifies where the design conflicts with an existing gas main or buried electric duct, commissions subsurface investigation to find out whether the record is even true, adjudicates prior rights to establish whether the State or the owner bears the relocation cost, reviews the owner's relocation plan, separates genuine replacement from a self-serving capacity upgrade, commits the work to a window that fits construction phasing, executes a reimbursement agreement with audit rights attached, and finally settles that agreement against as-built documentation. Every one of those steps is currently tracked in spreadsheets that disagree with one another, and the disagreements surface as contractor delay claims nobody can allocate.

This document specifies the API that replaces those spreadsheets. The system is, at its core, a ledger reconciliation engine wearing the clothes of a compliance workflow: a project carries a programmed dollar authority, and every determination, plan revision, executed agreement and final settlement moves derived money figures that must reconcile exactly against that authority — and must return exactly to their prior values when an action is compensated. Layered on top is a segregation-of-duties regime: the officer who executes an agreement may not later question its costs, and the adjudicator who first issued a prior-rights determination may not re-issue it after the owner appeals.

Two design consequences run through the whole specification and should be read as constraints rather than aspirations. First, almost every money and status field of consequence is *derived*, not supplied: clients never write a state share, a betterment ratio or a clearance posture, they write cost estimates and cost documents and the server recomputes. Second, the cascades are deep — a single late completion report can strike an owner, place that owner on reimbursement hold, suspend the settlement of unrelated agreements, and freeze cost documents already under review. Implementations that treat these as independent updates will drift, and the reconciliation invariants described in section 2.8 are the acceptance criteria for having got it right.

## 2. Global Specifications & System-Wide Principles

The utility relocation surface is mounted under `/uro`; a single administrative test-driving endpoint sits outside that mount, as described in section 2.5. This section defines the rules that hold across every endpoint.

### 2.1. Roles, Identity and Segregation of Duties

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which the user acts. The system recognises exactly seven roles: `ProgramAdmin`, `UtilityCoordinator`, `RightOfWayAdjudicator`, `AgreementOfficer`, `ExternalAuditor`, `ConstructionEngineer`, and `UtilityOwnerRep`. If either header is absent, or if `X-User-Role` carries a string outside those seven, the request is rejected with `ERR_UNAUTHENTICATED` (401). If the role is one of the seven but is not among the roles authorised for the target endpoint in section 4, the request is rejected with `ERR_UNAUTHORIZED` (403).

Six of the seven roles are office roles whose identity is opaque. When `X-User-Role` is `ProgramAdmin`, `UtilityCoordinator`, `RightOfWayAdjudicator`, `AgreementOfficer`, `ExternalAuditor` or `ConstructionEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — it is stamped onto `first_issued_by_user_id` when an adjudicator issues a determination for the first time, onto `executed_by_user_id` when an agreement officer executes an agreement, and onto `auditor_user_id` when an auditor raises a finding — but it is never compared against any entity's `id`.

`UtilityOwnerRep` is different. When `X-User-Role` is `UtilityOwnerRep`, `X-User-ID` is the `id` of the acting `UtilityOwner`, and ownership checks on any resource that references a utility owner compare that resource's owner foreign key to `X-User-ID`. Concretely, the comparison target is `owner_id` on a schedule commitment, `owner_id` on a reimbursement agreement, the `owner_id` of the agreement behind a cost document, and — for a relocation plan or a prior-rights determination — the owner of the facility behind the conflict the plan or determination belongs to. A representative acting on a row belonging to a different owner is rejected with `ERR_OWNER_SCOPE_VIOLATION` (403). This scoping applies to every operation whose authorised-role list includes `UtilityOwnerRep`, reads included.

The two office-role identities that are recorded are recorded for one purpose: segregation of duties. An `ExternalAuditor` whose `X-User-ID` equals the `executed_by_user_id` of an agreement may not raise an audit finding against that agreement, and a `RightOfWayAdjudicator` whose `X-User-ID` equals a determination's `first_issued_by_user_id` may not issue that determination again once the owner has appealed it. Both violations return `ERR_SEGREGATION_OF_DUTIES` (403).

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

### 2.3. Pagination, Ordering and Collection Filters

Collection endpoints accept two pagination query parameters. `limit` sets the maximum number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100. `offset` sets how many rows to skip and defaults to 0; its minimum accepted value is 0. A `limit` outside the range from 1 to 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (400).

Unless a specific endpoint states otherwise, every list response is ordered by `created_at` ascending — oldest row first. List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether rows remain beyond the current page.

Collections also accept optional equality filters, and an unrecognised filter value for an enumerated field is a malformed request. The project collection filters on `status` and `clearance_posture`. The utility-owner collection filters on `utility_type` and `reimbursement_hold`. The investigation collection filters on `project_id`, `facility_id` and `quality_level`. The conflict collection filters on `project_id`, `facility_id`, `depends_on_conflict_id` and `status`. The plan listing for a conflict filters on `status`. The commitment collection filters on `plan_id`, `project_id`, `facility_id`, `owner_id`, `joint_trench_slot_id` and `status`. The agreement collection filters on `plan_id`, `project_id`, `owner_id`, `execution_status` and `settlement_status`. The cost-document listing of an agreement filters on `review_status`, the audit-finding listing of an agreement filters on `status`, and the delay-claim collection filters on `project_id`, `commitment_id` and `status`.

### 2.4. Record Identity, Timestamps and Version Counters

Every persisted resource carries an `id`: a server-minted UUID with no type prefix and no client control over its value. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was written.

All resources except one additionally carry `updated_at` — an ISO 8601 UTC timestamp, same format, refreshed on every mutation of the row — and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation, including mutations the server performs on its own initiative as part of a cascade. Recomputing a derived field is a mutation: when the server recalculates a project's money figures because a determination was issued elsewhere, that project's `updated_at` is refreshed and its `version` increments.

The single exception is the subsurface investigation record, which is immutable once written. It carries only `id` and `created_at`; both `updated_at` and `version` are absent from it, and no endpoint modifies it.

### 2.5. The Logical Clock

All time-dependent behaviour in this system reads a logical clock rather than the host's wall clock. The server's startup default for that clock is exactly `2026-08-01T00:00:00Z`, and until it is explicitly set the clock reads that instant — it never falls back to real time. A `ProgramAdmin` may move the clock with an administrative test-driving endpoint (`POST /_clock/set_current_utc`) that takes a single `current_utc` instant and echoes it back. Setting the clock changes no stored row, but every subsequent request that re-evaluates a clearance posture does so against the new instant.

The clock is the source for `performed_at` on an investigation, `applied_on` and `granted_on` on a permit record, `actual_complete_at` on a schedule commitment, all lateness arithmetic, and the forward-looking window in the clearance posture rules of section 2.11.

### 2.6. Money, Percentages and Rounding Discipline

Every monetary amount in this system is an integer number of cents, and no monetary field is ever expressed as a decimal. Cost-responsibility shares and participation tiers are integer percentages. The only non-integer stored quantities are the owner's audited indirect cost rate, which accepts at most 2 decimal places, the proposed capacity ratio of a relocation plan, which accepts at most 2 decimal places, and the derived betterment ratio, which is held to exactly 6 decimal places.

Wherever rounding is required, the method is round half up: a value exactly on the halfway mark rounds away from zero. Three rounding disciplines matter enough to state globally:

- **Round once, at the point the formula says.** Where a calculation applies two percentages in sequence, both are applied in a single expression and the result is rounded once at the end, not after each factor.
- **Round per line before summing, where the formula says so.** Where a figure is built from many cost documents or many conflicts, each contribution is rounded to whole cents before it enters the sum. Rounding the aggregate instead can differ by up to one cent per contribution, and the difference is treated as a defect.
- **Residuals are differences, never independent calculations.** Where two shares must sum to a total — an owner's residual against a net allowable, or the State's portion of a delay allocation against the gross — one share is computed and rounded, and the other is taken as the total minus that share.

Percentage shares that could fall outside their legal range are clamped rather than rounded: a prior-rights state share is held between 0 and 100 inclusive, and a betterment ratio is held between 0 and 1 inclusive.

### 2.7. Stale-Version Guards on Plan Submittal and Agreement Drafting

Two write operations legitimately retire work that other actors created, so both require the client to prove it has seen the parent's current state before it is allowed to proceed. The mechanism is optimistic concurrency control against the parent row's `version`, and it applies to exactly these two operations. No other endpoint in this system accepts a version field.

`POST /uro/relocation-plans` requires `expected_conflict_version` as a non-optional field of the request body, carrying the `version` of the target `UtilityConflict` as the client last observed it. If that value does not equal the conflict's current `version`, the submittal is rejected with `ERR_STALE_VERSION` (412). The guard exists because a newly created plan supersedes every earlier non-superseded plan on the same conflict; a submittal made on a stale view of the conflict would silently retire a plan revision the submitter never saw.

`POST /uro/agreements` requires `expected_plan_version` as a non-optional field of the request body, carrying the `version` of the target `RelocationPlan` as the client last observed it. If that value does not equal the plan's current `version`, the draft is rejected with `ERR_STALE_VERSION` (412). The guard exists because drafting a new agreement voids any earlier agreement on the same plan that is still in `DRAFT` or `PENDING_OWNER_SIGNATURE`; a stale view of the plan would retire cost terms the drafter never reviewed.

Both operations, when they succeed, increment the parent's `version` — the conflict's on plan submittal, the plan's on agreement drafting — so a client that submits twice from one read observes the second attempt rejected as stale.

### 2.8. Derived Figures, Conserved Ledgers and Cascade Propagation

Six figures in this system are derived and conserved. Derived means no client writes them: they are recomputed by the server from their inputs whenever any input changes. Conserved means an action that raises a figure and a compensating action that reverses it must leave the figure at exactly its prior value, not off by a single cent or a single rounding step.

The conserved figures are: a project's `estimated_state_liability_cents`, `total_committed_reimbursement_cents`, `open_conflict_count` and `aggregate_compensable_delay_days`; a utility owner's `open_commitment_days` and `assessed_delay_liability_cents`; and a joint trench slot's `occupant_count`. Their formulas appear with the workflows that move them in section 3. The compensating pairs to hold in mind are: creating a commitment against cancelling it, executing an agreement against voiding it, allocating a delay claim against withdrawing that allocation, and occupying a trench slot against releasing it.

Cascades in this system are multi-level and cross-entity, and each level is a real mutation of a real row with its own `updated_at` refresh and `version` increment. Three cascades deserve naming here because their later links are the ones implementations forget:

- **Issuing a prior-rights determination** copies the determined share onto the conflict and advances the conflict's status, which changes the project's forward liability estimate, which in turn re-evaluates the project's clearance posture — and that posture can land on `FUNDING_BLOCKED`, which blocks agreement execution on the project entirely.
- **Reporting a late completion** breaches the commitment, strikes the owner, can place the owner on reimbursement hold, moves that owner's agreements out of final billing into `HELD`, and moves the cost documents of those agreements out of `SUBMITTED` into `HELD`. Releasing the hold reverses the last two links.
- **Certifying a conflict cleared** locks the conflict's determination, reduces the project's open conflict count and forward liability, re-evaluates posture, and — when posture lands on `CLEAR` — advances the project's own status from `CLEARANCE_ACTIVE` to `LETTING_READY`.

The server performs these propagations without any client request naming the affected rows.

### 2.9. Rejection Order: the Validation Ladder

Validation is a strictly ordered ladder, not a set of independent checks. Rungs are evaluated in the order below, and **the first violated rung decides the response; no later rung is evaluated.** This ordering is observable and is part of the contract: a request that violates rungs 8 and 29 returns the rung-8 error, never the rung-29 one.

1. Both authentication headers are present and `X-User-Role` is one of the seven declared roles — otherwise `ERR_UNAUTHENTICATED`. Applies to every endpoint.
2. `X-User-Role` appears in the target endpoint's authorised-role list — otherwise `ERR_UNAUTHORIZED`. Applies to every endpoint.
3. The request body and query parameters are schema-valid — required fields present, types correct, enumerated values in range, integers non-negative where declared, and every declared interval and bound respected (a facility's `station_end` strictly greater than its `station_begin`; a project's `construction_end_date` strictly greater than its `construction_start_date`; a commitment's `window_end` strictly greater than its `window_start`; a slot's `trench_open_end` strictly greater than its `trench_open_start`; a plan's `replacement_in_kind_cost_cents` no greater than its `estimated_cost_cents`; a plan's `proposed_capacity_ratio` at least 1.0 and carrying at most 2 decimal places; an owner's `indirect_cost_rate_pct` between 0 and 35 inclusive with at most 2 decimal places; `limit` between 1 and 100 inclusive; `offset` not negative) — otherwise `ERR_INVALID_REQUEST`. Applies to every endpoint.
4. Every identifier in the URL path resolves to an existing row, checked left to right, with the leftmost unresolved segment deciding the error. Applies to every endpoint that has a path parameter. The error is the one naming the missing row type: `ERR_PROJECT_NOT_FOUND`, `ERR_OWNER_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`, `ERR_CONFLICT_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`, `ERR_COMMITMENT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` or `ERR_CLAIM_NOT_FOUND`, each carrying 404.
5. Every foreign key in the request body resolves to an existing row, checked in the order the endpoint declares its input fields. Applies to facility registration, investigation recording, conflict opening, determination opening, plan submittal, permit opening, trench-slot declaration, commitment creation, agreement drafting, cost-document submission, audit-finding creation and delay-claim lodging. The error is again the row-type-specific 404 — for example `ERR_SLOT_NOT_FOUND` for an unknown `joint_trench_slot_id`, and `ERR_CONFLICT_NOT_FOUND` for an unknown `depends_on_conflict_id`.
6. When the acting role is `UtilityOwnerRep`, `X-User-ID` equals the owner of the target row as described in section 2.1 — otherwise `ERR_OWNER_SCOPE_VIOLATION`. Applies to every endpoint whose authorised-role list includes `UtilityOwnerRep`.
7. Segregation of duties on the acting `X-User-ID` — otherwise `ERR_SEGREGATION_OF_DUTIES`. Applies to exactly two operations: raising an audit finding, and issuing a determination that has been through an appeal.
8. The target row is in a state from which the requested transition is declared, which also covers terminal-state lockdown and the rejection of a repeated trigger — otherwise `ERR_INVALID_STATE_TRANSITION` (409). Applies to every state-driving action endpoint under the relocation surface.
9. The agreement's `execution_status` permits the requested execution-dimension action: `DRAFT` for circulation, `PENDING_OWNER_SIGNATURE` for execution, `EXECUTED` before final billing may open, and not `VOIDED` for any settlement action — otherwise `ERR_AGREEMENT_NOT_EXECUTABLE`. Applies to agreement circulation, agreement execution, opening final billing and final settlement.
10. The agreement's `settlement_status` permits the requested settlement-dimension action: `NOT_STARTED` before final billing may open, and `PENDING_FINAL_INVOICE` for final settlement, for cost-document submission and for cost-document review; a `SETTLED` agreement accepts no further settlement action and cannot be voided — otherwise `ERR_SETTLEMENT_STATE_INVALID`. Applies to opening final billing, final settlement, voiding an agreement, cost-document submission and cost-document review.
11. The referenced schedule commitment is in a state that permits the action: `COMPLETE` or `BREACHED` before a delay claim may be analysed, and `COMMITTED` or `IN_PROGRESS` before work is started, completion is reported or the commitment is cancelled — otherwise `ERR_COMMITMENT_STATE_INVALID`. Applies to delay-claim analysis, work start, completion reporting and commitment cancellation.
12. The owning project's `status` is not `CLOSED` — otherwise `ERR_PROJECT_CLOSED`. Applies to every write operation under the relocation surface for which an owning project can be resolved, with three exemptions: project registration, utility-owner registration and the release of an owner's reimbursement hold.
13. The supplied `expected_conflict_version` or `expected_plan_version` equals the parent row's current `version` — otherwise `ERR_STALE_VERSION`, as specified in section 2.7. Applies to plan submittal and agreement drafting.
14. The owning project's `clearance_posture` is not `FUNDING_BLOCKED` — otherwise `ERR_CLEARANCE_POSTURE_BLOCKED`. Applies to three operations: agreement execution, commitment creation and project closure.
15. The counterparty owner's `reimbursement_hold` is false — otherwise `ERR_OWNER_ON_REIMBURSEMENT_HOLD`. Applies to agreement execution and final settlement.
16. The conflict behind the plan has a determination in status `ISSUED` or `FINAL` and the conflict's `state_share_pct` is not null — otherwise `ERR_PRIOR_RIGHTS_NOT_ISSUED`. Applies to plan approval.
17. Every permit record of the conflict is in status `GRANTED`, and at least one permit record exists — otherwise `ERR_PERMIT_NOT_GRANTED`. Applies to plan approval.
18. When the conflict's `depends_on_conflict_id` is not null, the referenced predecessor conflict is in status `CLEARED` — otherwise `ERR_DEPENDENCY_NOT_CLEARED`. Applies to certifying a conflict cleared.
19. No agreement of the plan that the submittal would supersede is in `execution_status` `EXECUTED` — otherwise `ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE`. Applies to plan submittal.
20. No audit finding of the agreement remains in status `OPEN` — otherwise `ERR_OPEN_AUDIT_FINDING`. Applies to final settlement.
21. At least one cost document of the agreement is in `review_status` `ACCEPTED` with a `doc_type` other than `CREDIT_SALVAGE` and `INDIRECT` — otherwise `ERR_NO_ELIGIBLE_COST_DOCUMENTATION` (422). Applies to final settlement.
22. The commitment window lies inside the project's construction window: `window_start` at or after `construction_start_date`, and `window_end` at or before `construction_end_date` — otherwise `ERR_WINDOW_OUTSIDE_CONSTRUCTION` (422). Applies to commitment creation.
23. The proposed window does not collide with another open window on the same facility, tested with the mobilisation buffer of section 3.7 — otherwise `ERR_FACILITY_WINDOW_CONFLICT`. Applies to commitment creation.
24. When a `joint_trench_slot_id` is supplied, the commitment window is fully contained in the slot's opening — otherwise `ERR_TRENCH_WINDOW_NOT_CONTAINED` (422). Applies to commitment creation.
25. When a `joint_trench_slot_id` is supplied, the slot's `occupant_count` is strictly below its `max_occupants` — otherwise `ERR_TRENCH_SLOT_AT_CAPACITY`. Applies to commitment creation.
26. The plan's `revision_round` is strictly below 3 — otherwise `ERR_REVISION_LIMIT_EXCEEDED`. Applies to plan resubmission.
27. The determination's `appeal_round` is strictly below 1 — otherwise `ERR_APPEAL_LIMIT_EXCEEDED`. Applies to owner appeal.
28. The agreement's `not_to_exceed_cents` is at least the indirect-loaded plan estimate described in section 3.8 — otherwise `ERR_NOT_TO_EXCEED_TOO_LOW` (422). Applies to agreement drafting.
29. The resulting committed ledger does not exceed the project's `reimbursement_authority_cents` — otherwise `ERR_AUTHORITY_EXCEEDED`. Applies to agreement execution and final settlement.
30. The analysed claim's `compensable_days` is greater than 0 — otherwise `ERR_DELAY_NOT_COMPENSABLE` (422). Applies to delay-claim allocation.
31. Every conflict of the project is `CLEARED`, every agreement of the project is in `settlement_status` `SETTLED` or `VOIDED_OUT`, and no delay claim of the project remains in status `SUBMITTED` or `UNDER_ANALYSIS` — otherwise `ERR_PROJECT_CLOSE_BLOCKED`. Applies to project closure.

### 2.10. Addressing Records and Reverse-Reachability Reads

Every resource is addressed by a single-segment collection path under the relocation surface, and relationships between resources are carried by explicit foreign-key fields in request bodies rather than by nested write paths. A relocation plan is created by naming its `conflict_id`, not by posting under the conflict.

Read access, however, is offered in both directions. Alongside the single-resource reads, the API exposes sub-resource listings that traverse a foreign key backwards: the joint trench slots of a project, the facilities of an owner, the determinations of a conflict, the relocation plans of a conflict, the permit records of a conflict, the cost documents of an agreement, and the audit findings of an agreement. For these two-segment reads the left-to-right existence rule of rung 4 is what matters: a request for the cost documents of a non-existent agreement returns `ERR_AGREEMENT_NOT_FOUND` and never an empty list.

Two further reads compute rather than retrieve. A project's clearance summary reports `clearance_posture`, `open_conflict_count`, `untriaged_conflict_count` (the number of the project's conflicts still in status `IDENTIFIED`), `overdue_commitment_count` (the number of its commitments in `COMMITTED` or `IN_PROGRESS` whose `window_end` is earlier than the logical clock), `at_risk_commitment_count` (the number of its commitments in `COMMITTED` or `IN_PROGRESS` whose `window_end` falls at or before the logical clock advanced by the 60-day warning look-ahead of section 2.11), `estimated_state_liability_cents`, `total_committed_reimbursement_cents`, `reimbursement_authority_cents` and `remaining_authority_cents`, the last being the programmed authority minus the committed ledger. An agreement's settlement preview re-runs the full settlement chain on the actual cost basis without mutating anything, reporting `cost_basis`, `eligible_cost_cents`, `indirect_cost_cents`, `betterment_credit_cents`, `net_allowable_cents`, `participation_tier_pct`, `state_share_cents`, `owner_share_cents`, and the `included_document_count` and `excluded_document_count` that the chronological not-to-exceed cutoff would produce.

### 2.11. Clearance Posture: the Project Readiness Gate

Each project carries a derived `clearance_posture` drawn from four values — `CLEARANCE_PENDING`, `AT_RISK`, `FUNDING_BLOCKED` and `CLEAR` — and re-evaluated whenever any conflict status, commitment status, or either of the project's two money figures changes, and whenever a later request reads the posture after the logical clock has moved. A newly registered project starts at `CLEARANCE_PENDING`.

The four rules are an ordered cascade, and **the first rule that matches sets the posture**; later rules are not consulted. This ordering is why a funding breach masks an untriaged conflict, and why an imminent relocation window masks ordinary pending clearance work.

1. Take the larger of `estimated_state_liability_cents` and `total_committed_reimbursement_cents`. If that larger figure is greater than `reimbursement_authority_cents`, the posture is `FUNDING_BLOCKED`. Because the comparison uses the larger of the two, an over-committed ledger blocks the project even when the forward estimate is small, and a forward estimate above authority blocks it even when nothing has been committed yet.
2. Otherwise, if any conflict of the project is in status `IDENTIFIED`, or any commitment of the project is in status `COMMITTED` or `IN_PROGRESS` with a `window_end` falling at or before the logical clock advanced by 60 days, the posture is `AT_RISK`. The look-ahead boundary is inclusive: a commitment whose `window_end` is exactly 60 days after the current clock instant already makes the project `AT_RISK`.
3. Otherwise, if the project has no conflicts at all, or any of its conflicts is in a status other than `CLEARED`, the posture is `CLEARANCE_PENDING`.
4. Otherwise the posture is `CLEAR`.

A `FUNDING_BLOCKED` posture is a hard gate rather than a warning: while it holds, no agreement on that project may be executed, no commitment may be created against it, and the project may not be closed. Each of those three rejections carries `ERR_CLEARANCE_POSTURE_BLOCKED`.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Project, Its Authority and Its Utility Owners

A `ProgramAdmin` registers a highway project with the `name` it carries on the letting schedule (1 to 160 characters, not blank), its `route_designation` (1 to 24 characters, for example the string for a state route), the `letting_date` at which the contract is scheduled to let, and the `construction_start_date` and `construction_end_date` that bound the construction window — the end instant must be strictly later than the start. Two further inputs carry the fiscal weight of the record. `row_acquisition_year` is the calendar year the State acquired the right-of-way at this location, accepted between 1850 and 2100, and it is the cutoff against which every prior-rights determination on the project is scored. `reimbursement_authority_cents` is the programmed dollar authority, in cents, available for state-share relocation reimbursement on this project, and it may be zero but never negative. `contract_daily_overhead_cents` is the contract-stipulated daily overhead ceiling, in cents per day, and it caps the daily rate of any contractor delay claim; it too may be zero but never negative.

A newly registered project opens in `status` `PLANNING` with `clearance_posture` `CLEARANCE_PENDING`, and its four derived figures — `open_conflict_count`, `estimated_state_liability_cents`, `total_committed_reimbursement_cents` and `aggregate_compensable_delay_days` — all start at 0. The administrator may afterwards revise `reimbursement_authority_cents`, `contract_daily_overhead_cents` or `letting_date` in place; any of the three may be supplied alone. Each such revision recomputes the posture and increments the project's `version`, and lowering `reimbursement_authority_cents` below either of the project's two money figures flips the posture straight to `FUNDING_BLOCKED`.

The project's own lifecycle is driven almost entirely by the server rather than by explicit requests. Opening the first conflict on a project advances it `PLANNING → CLEARANCE_ACTIVE`, recomputing `open_conflict_count`, `estimated_state_liability_cents` and `clearance_posture` on the way and incrementing `version`. Any posture recomputation that yields `CLEAR` while the project is in `CLEARANCE_ACTIVE` advances it `CLEARANCE_ACTIVE → LETTING_READY` — which, given rule 3 of the posture cascade, means every conflict is `CLEARED` and neither money figure exceeds authority. That edge runs backwards too: opening a newly identified conflict on a project already at `LETTING_READY` returns it `LETTING_READY → CLEARANCE_ACTIVE`, because the fresh conflict raises `open_conflict_count` to at least 1 and the posture necessarily leaves `CLEAR`. When the first commitment on the project reports that work has started, the project advances to `UNDER_CONSTRUCTION`, from either `CLEARANCE_ACTIVE` or `LETTING_READY`; only the project's first such report moves the status, and each of these system transitions increments `version` by 1.

Closure is the one project transition an administrator requests directly, optionally with a `closure_note`, and it is only available from `UNDER_CONSTRUCTION`. Three conditions must all hold, and any failure returns `ERR_PROJECT_CLOSE_BLOCKED`: every conflict of the project is `CLEARED`, every reimbursement agreement of the project has `settlement_status` `SETTLED` or `VOIDED_OUT`, and no delay claim of the project remains in `SUBMITTED` or `UNDER_ANALYSIS`. `CLOSED` is terminal, and thereafter every write that resolves to this project is refused with `ERR_PROJECT_CLOSED` — with the three exemptions named in rung 12, since registering a project or an owner, and relieving an owner's delinquency, are not project-scoped acts.

Utility owners are registered separately by the same administrator. An owner record carries a `legal_name` as it appears on the master agreement (1 to 160 characters, not blank), a `utility_type` drawn from `ELECTRIC`, `GAS`, `WATER`, `SEWER`, `TELECOM` and `FIBER`, an optional `is_public_agency` flag that defaults to false and marks municipalities and public districts eligible for relief in prior-rights scoring, and an `indirect_cost_rate_pct` — the owner's audited indirect cost rate as a percentage, between 0 and 35 inclusive with at most 2 decimal places, later applied to eligible direct cost at settlement. Its four derived fields all start empty: `delinquency_strikes` at 0, `reimbursement_hold` false, `open_commitment_days` at 0, and `assessed_delay_liability_cents` at 0.

`reimbursement_hold` is a punitive flag, not an input: it flips to true once the owner accumulates 2 breached commitments, as section 3.7 describes, and nothing but an explicit administrative release clears it. Releasing the hold requires a `release_note` and performs four things in one transaction: `reimbursement_hold` returns to false, `delinquency_strikes` resets to 0, every reimbursement agreement of this owner sitting in `settlement_status` `HELD` returns to `PENDING_FINAL_INVOICE`, and every cost document of those agreements sitting in `review_status` `HELD` returns to `SUBMITTED`. The owner's `version` increments, as does the `version` of every agreement and every cost document the release moves. Because release is not project-scoped, it remains available even for an owner whose projects have closed.

### 3.2. Facilities of Record and the Subsurface Truth

Before a conflict can be identified, the facility it conflicts with must exist as a record. A `ProgramAdmin` or a `UtilityCoordinator` writes one by naming the `owner_id` of the owner of record and describing the facility physically: a `facility_type` from `OVERHEAD_ELECTRIC`, `BURIED_ELECTRIC`, `GAS_MAIN`, `WATER_MAIN`, `SANITARY_SEWER` and `FIBER_CONDUIT`; the engineering stations in feet at which it enters and leaves the project limits, `station_begin` (not negative) and `station_end` (strictly greater than `station_begin`); its `offset_ft`, the lateral offset from centreline in feet, where a negative value means left of centreline; its `depth_in`, the depth of cover of record in inches, which is 0 for overhead facilities and never negative; its `material` of record as a short string of 1 to 40 characters; and its `installed_year`, the year the owner's records say it was installed, accepted between 1850 and 2100.

Two enumerated fields on the facility do the legal work. `occupancy_basis` states the documented legal basis on which the facility occupies the corridor and is one of `FEE_SIMPLE`, `PRIVATE_EASEMENT`, `FRANCHISE`, `PERMIT` or `UNDOCUMENTED`; it is the primary driver of who pays for relocation. `record_source` states the provenance of the data captured above and is one of `AS_BUILT`, `OWNER_ATLAS`, `FIELD_SURVEY` or `VERBAL`.

Records lie, which is why the coordinator commissions subsurface investigation. Each investigation is written against a `project_id` and a `facility_id` and records the `quality_level` of evidence produced — `QL_A`, `QL_B`, `QL_C` or `QL_D` — the `method` used, drawn from `VACUUM_TEST_HOLE`, `GEOPHYSICAL`, `SURFACE_MARKING` and `RECORD_RESEARCH`, the `measured_depth_in` found in the field in inches (not negative), and the `station_at_investigation` in feet at which the reading was taken (not negative). The server stamps `performed_at` from the logical clock. As section 2.4 notes, the investigation is immutable: it has no `version`, no `updated_at` and no update endpoint, and a mistaken reading is corrected by recording a further investigation rather than editing the old one.

The one derived field on an investigation is `contradicts_record`, and it is the hinge on which cost responsibility can swing by tens of percentage points. It is set to true when the investigation was taken at quality level `QL_A` and the absolute difference between its `measured_depth_in` and the facility's `depth_in` of record is greater than 6 inches — the depth tolerance. The comparison is strictly greater than the tolerance: a disagreement of exactly 6 inches does not contradict the record. Investigations recorded at `QL_B`, `QL_C` or `QL_D` never carry the flag, however large their depth disagreement, and it defaults to false.

### 3.3. Identifying, Sequencing and Certifying Conflicts

A `UtilityCoordinator` opens a **utility conflict** where the design collides with a facility of record, naming the `project_id` and the `facility_id`, the `conflict_station` in feet at which the collision occurs (not negative), and the `clearance_deficiency_in` — the shortfall against required clearance, in inches, which may be 0 but never negative. An optional `depends_on_conflict_id` points at another conflict that must be cleared first; it defaults to null and is how clearance sequencing is expressed when, for example, a gas main cannot be moved until the fibre duct above it has been relocated. A conflict opens in `status` `IDENTIFIED` with `state_share_pct` null, and its creation recomputes the project's `open_conflict_count` and posture — the posture landing on `AT_RISK` under rule 2 precisely because an `IDENTIFIED` conflict now exists.

The conflict's lifecycle runs `IDENTIFIED → RESOLUTION_SELECTED → RESPONSIBILITY_SET → RELOCATION_PLANNED → RELOCATION_SCHEDULED → CLEARED`, with one shortcut and one reverse edge. Selecting the engineering resolution moves it `IDENTIFIED → RESOLUTION_SELECTED` and writes `resolution_type` from the request body, one of `RELOCATE`, `PROTECT_IN_PLACE`, `ABANDON` or `NO_CONFLICT`; the field is null until then. The transition is available only from `IDENTIFIED`, requires the owning project not to be `CLOSED`, recomputes the project's posture, and increments the conflict's `version`.

From here the fork matters, and the two branches are genuinely different workflows rather than variations on one. On the `RELOCATE` branch the conflict must travel the full route: a determination is issued (which advances it `RESOLUTION_SELECTED → RESPONSIBILITY_SET` and copies the state share onto it), a plan is approved (`RESPONSIBILITY_SET → RELOCATION_PLANNED`), a commitment is created (`RELOCATION_PLANNED → RELOCATION_SCHEDULED`), and only then may it be certified. Certification from `RELOCATION_SCHEDULED` requires all of: the conflict's `resolution_type` is `RELOCATE`; at least one schedule commitment of the conflict has reached `COMPLETE`; and either `depends_on_conflict_id` is null or the conflict it references is already `CLEARED`, failing which the request is refused with `ERR_DEPENDENCY_NOT_CLEARED`. On success the conflict moves `RELOCATION_SCHEDULED → CLEARED`, the conflict's prior-rights determination is locked from `ISSUED` to `FINAL`, the project's `open_conflict_count` and `estimated_state_liability_cents` are recomputed (this conflict's contribution drops out of the estimate), the posture is re-evaluated, a resulting `CLEAR` posture bubbles the project `CLEARANCE_ACTIVE → LETTING_READY`, and the conflict's `version` increments.

The non-relocation branch is the shortcut. When `resolution_type` is `PROTECT_IN_PLACE`, `ABANDON` or `NO_CONFLICT`, the conflict is certified directly from `RESOLUTION_SELECTED → CLEARED`, and the same dependency rule applies: a non-null `depends_on_conflict_id` whose target is not `CLEARED` refuses the certification with `ERR_DEPENDENCY_NOT_CLEARED`. On this branch no determination, plan, commitment or agreement is required or touched, no determination is locked to `FINAL`, and `state_share_pct` remains null — which means the conflict contributes nothing to the project's forward liability estimate for as long as it exists. The certification still recomputes `open_conflict_count`, the liability estimate and the posture, still bubbles a `CLEAR` posture up to `LETTING_READY`, still increments the conflict's `version`, and may carry an optional `certification_note`. Certification from any other state, or a second certification of an already-`CLEARED` conflict, is refused with `ERR_INVALID_STATE_TRANSITION`; `CLEARED` is terminal.

The reverse edge sits between scheduling and planning. Cancelling the last remaining open commitment of a conflict returns it `RELOCATION_SCHEDULED → RELOCATION_PLANNED`, as section 3.7 describes.

### 3.4. Prior Rights: Adjudicating Who Bears the Cost

A `RightOfWayAdjudicator` opens a **prior-rights determination** on a conflict by naming the `conflict_id`, the `claimed_basis` the owner asserts in its submittal — the same five values as a facility's occupancy basis: `FEE_SIMPLE`, `PRIVATE_EASEMENT`, `FRANCHISE`, `PERMIT`, `UNDOCUMENTED` — and a supporting `narrative` of 1 to 2000 characters. The determination opens in `status` `DRAFT` with `appeal_round` 0, `first_issued_by_user_id` null, and `final_state_share_pct` null. At creation the server already computes `evidence_variant` and `provisional_state_share_pct`, the latter being the record-basis figure derived from record data alone, so that the reviewer can see the likely answer before review starts.

Review is a cycle. Submitting for review moves the determination `DRAFT → UNDER_REVIEW`. Returning it moves it `UNDER_REVIEW → RETURNED_FOR_REVISION` and records a `revision_note`. Revising moves it back to `DRAFT` — the same revise action serves both `RETURNED_FOR_REVISION → DRAFT` and `APPEALED → DRAFT` — overwriting `claimed_basis` and `narrative` from the request body, each of which may be supplied alone, and recomputing `evidence_variant` and `provisional_state_share_pct` under the record-basis variant. Every one of these transitions increments the determination's `version`, and each is available only from the state named; anything else is `ERR_INVALID_STATE_TRANSITION`.

Issuance is where the money is fixed. It runs `UNDER_REVIEW → ISSUED`, requires the determination to be in `UNDER_REVIEW` and the conflict to be in `RESOLUTION_SELECTED`, and — when `appeal_round` is at least 1, that is, on any re-issue that follows an appeal — requires the acting `X-User-ID` to differ from the recorded `first_issued_by_user_id`, failing which the request is refused with `ERR_SEGREGATION_OF_DUTIES`. On success the server recomputes the state share from *current* evidence and freezes it into `final_state_share_pct`, alongside the `evidence_variant` that produced it; a `QL_A` investigation recorded after the provisional figure was written can therefore change the answer at issuance. `first_issued_by_user_id` is stamped with `X-User-ID` only when it is still null, so it records the first issuer forever. Then the cascade fires: the conflict's `state_share_pct` is set to `final_state_share_pct` and the conflict advances `RESOLUTION_SELECTED → RESPONSIBILITY_SET`; the project's `estimated_state_liability_cents` is recomputed; the project's `clearance_posture` is recomputed and becomes `FUNDING_BLOCKED` when the new estimate exceeds `reimbursement_authority_cents`. The determination's `version` increments, as do those of the conflict and the project.

An owner may appeal once. A `UtilityOwnerRep` acting for the owner derived from the conflict's facility moves the determination `ISSUED → APPEALED` with an `appeal_note`, incrementing `appeal_round` by 1 and the `version` by 1. A representative of any other owner is refused with `ERR_OWNER_SCOPE_VIOLATION`, and an appeal against a determination whose `appeal_round` has already reached 1 is refused with `ERR_APPEAL_LIMIT_EXCEEDED`. An appealed determination re-enters the cycle through revision and can be issued again — by a different adjudicator. The terminal state is `FINAL`, reached only as the system lock applied when the determination's conflict is certified cleared on the relocate branch, and that lock too increments `version`.

**How the share is computed.** The determination answers one question — what percentage of relocation cost the State bears — and it answers it in two evidentiary variants, because a determination that can trust the record earns a credit that a determination contradicted by the field does not.

The variant is chosen first. If any `QL_A` investigation of the conflicting facility carries `contradicts_record` true, the variant is `FIELD_BASIS`; otherwise it is `RECORD_BASIS`. Investigations at the three lower quality levels never force the field basis.

Next comes the base entitlement, read from the facility's `occupancy_basis` of record — never from the owner's `claimed_basis`. A facility held in `FEE_SIMPLE` starts at 100 percent, and so does one held under a `PRIVATE_EASEMENT`. A `FRANCHISE` facility starts at 50 percent when its owner is not a public agency, and at 0 when it is. Facilities occupying the corridor by `PERMIT` or on an `UNDOCUMENTED` basis start at 0.

Five adjustments are then accumulated, in this order, against that base:

- If the variant is `RECORD_BASIS` and the facility's `installed_year` is strictly earlier than the project's `row_acquisition_year`, add 10 percentage points — the prior-occupancy credit, earned by having been there before the State took the corridor, and forfeited entirely under the field basis.
- If the facility's `installed_year` is the same as or later than `row_acquisition_year`, subtract 20 percentage points. This penalty applies under either variant.
- If the owner's `is_public_agency` is true, add 25 percentage points. This credit also applies under either variant.
- If the determination's `claimed_basis` differs from the facility's `occupancy_basis`, subtract 15 percentage points, because the owner's claim is not supported by the record.
- If the variant is `FIELD_BASIS`, subtract a further 45 percentage points, because the record could not be relied upon at all.

Finally the running total is clamped into the legal range: the result is the base plus the accumulated adjustments, floored at 0 and capped at 100. The figure is an integer percentage throughout and is never rounded, only clamped. The gap between the variants is deliberately large — a pre-acquisition `PRIVATE_EASEMENT` facility of a private owner lands at 100 under `RECORD_BASIS` and at 55 under `FIELD_BASIS` — because a field contradiction means the State is being asked to pay for an interest nobody can document where it actually is.

### 3.5. Relocation Plan Review and the Betterment Test

The utility owner's proposal for how the relocation will be done arrives as a **relocation plan**. Either a `UtilityCoordinator` or the owner's own `UtilityOwnerRep` may submit one, naming the `conflict_id` and, as section 2.7 requires, the `expected_conflict_version`. The substance of the submittal is four numbers and a flag: `estimated_cost_cents`, the owner's estimated total relocation cost in cents, which must be greater than 0; `replacement_in_kind_cost_cents`, the estimated cost of replacing the existing facility in kind, which must be greater than 0 and no greater than the total estimate; `proposed_capacity_ratio`, the ratio of proposed facility capacity to existing capacity, at least 1.0 and carrying at most 2 decimal places; `work_days`, the working days the owner estimates the relocation will take, greater than 0; and `joint_trench_requested`, an optional flag defaulting to false by which the owner asks to share a trench opening with other occupants. The plan's utility owner is not supplied — it is derived by following the plan's conflict to its facility and the facility to its owner, and that derived owner is what an owner-scope check compares against `X-User-ID`.

A submitted plan opens in `status` `SUBMITTED` with `revision_round` 0, and its two derived betterment fields are computed immediately. Submitting also supersedes history: every earlier relocation plan on the same conflict that is not already `SUPERSEDED` moves to `SUPERSEDED`, from whichever of `SUBMITTED`, `UNDER_REVIEW`, `REVISION_REQUESTED` or `APPROVED` it occupied, and each superseded plan's `version` increments. That retirement reaches into the agreement world: every reimbursement agreement of a superseded plan sitting in `execution_status` `DRAFT` or `PENDING_OWNER_SIGNATURE` moves to `execution_status` `VOIDED` and `settlement_status` `VOIDED_OUT`. It is precisely because that retirement is destructive that it is guarded twice — by the stale-version check, and by a refusal to proceed at all if any agreement of the plan being superseded has reached `execution_status` `EXECUTED`, which returns `ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE`. Finally the submittal recomputes the project's `estimated_state_liability_cents` from the new governing plan and re-evaluates the posture, and increments the conflict's `version` as the concurrency parent.

Plan review mirrors determination review as a cycle. A coordinator takes a plan `SUBMITTED → UNDER_REVIEW`, and may return it `UNDER_REVIEW → REVISION_REQUESTED` with a `revision_note`. Resubmission — open to the owner's representative and to a coordinator — moves it `REVISION_REQUESTED → SUBMITTED`, increments `revision_round` by 1, and overwrites all four substantive numbers (`estimated_cost_cents`, `replacement_in_kind_cost_cents`, `proposed_capacity_ratio` and `work_days`) from the request body, then recomputes `betterment_ratio` and `betterment_amount_cents` and, from the revised governing plan, the project's `estimated_state_liability_cents` and `clearance_posture`. A plan may be resubmitted only while `revision_round` is strictly below 3; the fourth attempt is refused with `ERR_REVISION_LIMIT_EXCEEDED`. Every one of these transitions increments the plan's `version`.

Approval is what unlocks scheduling, and it is gated on two other workstreams having finished. Moving a plan `UNDER_REVIEW → APPROVED` requires the conflict behind it to have a determination in status `ISSUED` or `FINAL` with a non-null `state_share_pct` — otherwise `ERR_PRIOR_RIGHTS_NOT_ISSUED` — and requires every permit record of that conflict to be in status `GRANTED`, with at least one permit record existing at all — otherwise `ERR_PERMIT_NOT_GRANTED`. On success the conflict cascades `RESPONSIBILITY_SET → RELOCATION_PLANNED`, the project's `estimated_state_liability_cents` and `clearance_posture` are recomputed, and both the plan's and the conflict's `version` increment. `SUPERSEDED` is the plan's terminal state; any action on a superseded plan is `ERR_INVALID_STATE_TRANSITION`.

**Betterment.** Replacement in kind is fully participating work — the State pays its determined share of it. Anything beyond replacement in kind, and any capacity the owner adds above what existed, is betterment, which the owner funds. The plan's `betterment_ratio` expresses what fraction of the plan cost is betterment, and it is built from two components that **nest rather than add**.

The scope component is the share of the estimate that goes beyond replacement in kind: the estimated cost minus the replacement-in-kind cost, divided by the estimated cost.

The capacity component depends on the betterment threshold, which is a capacity ratio of exactly 1.0. If `proposed_capacity_ratio` is at or below 1.0, the capacity component is 0 — replacing like with like, or slightly under, adds no capacity betterment. Above 1.0, the capacity component is the ratio minus 1.0, divided by the ratio itself. A facility rebuilt at twice its old capacity therefore carries a capacity component of one half.

The two are then combined by applying the capacity component only to the in-kind-comparable remainder — that is, to 1 minus the scope component — and adding the result to the scope component. That sum is rounded half up to exactly 6 decimal places, and the outcome is capped at 1.0. Rounding happens once, at the end. Adding the two components directly would double-count the upgraded portion of the already non-participating scope, and is the classic error here. The plan-level `betterment_amount_cents` is then the plan's `estimated_cost_cents` multiplied by the rounded `betterment_ratio`, rounded half up to whole cents. Both fields default to 0.

At final settlement the credit is re-derived from actual cost lines rather than reused, and it is derived **per line**. Taking the cost documents that the settlement accrual actually included, in the same chronological order, each document's contribution is its `amount_cents` multiplied by the plan's `betterment_ratio`, rounded half up to whole cents; the contribution is subtracted rather than added when the document's `doc_type` is `CREDIT_SALVAGE`, and added otherwise. The settlement credit is the sum of those signed, individually rounded contributions. Each line is rounded before summing — rounding the aggregate instead can differ by up to one cent per line, and lines of 12,345,678, 9,876,543 and a 1,000,000 salvage credit at a ratio of 0.360000 yield 4,444,444 plus 3,555,555 minus 360,000, which is 7,639,999 per line against 7,640,000 in aggregate.

**Forward liability.** The project's `estimated_state_liability_cents` is the forward-looking sum of what the State expects to owe, and it is rebuilt from scratch each time a plan is submitted, resubmitted or approved, a determination is issued, or a conflict is certified cleared. Only conflicts whose `status` is not `CLEARED` are considered. For each such conflict the *governing plan* is the plan of that conflict with the greatest `created_at` among those whose `status` is not `SUPERSEDED`; a conflict has at most one, and a conflict with none contributes 0. The conflict's contribution is its governing plan's `estimated_cost_cents` minus that plan's `betterment_amount_cents`, floored at 0, multiplied by the conflict's current `state_share_pct` divided by 100, and rounded half up to whole cents *per conflict* before it enters the sum. The total is the sum of those contributions. Plans still in `SUBMITTED`, `UNDER_REVIEW` or `REVISION_REQUESTED` count exactly like `APPROVED` ones, because the estimate is forward-looking and pending scope is still scope; and a conflict whose determination has not been issued still participates, at a `state_share_pct` that is 0 until issuance.

### 3.6. Permitting, Easements and Joint Trench Openings

Relocation work usually needs permission from someone. A `UtilityCoordinator` opens a **permit record** against a `conflict_id`, declaring the `permit_type` — `ENCROACHMENT_PERMIT`, `EASEMENT_ACQUISITION`, `RAILROAD_CROSSING` or `ENVIRONMENTAL_CLEARANCE` — and the `expires_on` instant intended for the instrument. The record opens in `status` `APPLIED` with `applied_on` stamped from the logical clock and `granted_on` null.

The decision is recorded with a `decision` of either `GRANT` or `DENY`, plus an optional `decision_note` of up to 500 characters. A grant moves the record `APPLIED → GRANTED`, stamps `granted_on` from the logical clock, and retains the recorded `expires_on` as the expiry of the granted instrument along with any `decision_note`. A denial moves it `APPLIED → DENIED`, records the `decision_note`, and leaves `granted_on` null — `expires_on` is meaningful only for a granted instrument. Both branches increment the record's `version`, and both target states are terminal, so a second decision on the same record is refused with `ERR_INVALID_STATE_TRANSITION`. The consequence of a denial is felt in section 3.5: a conflict with any permit record not in `GRANTED` cannot have its relocation plan approved.

Opening a trench once for several occupants saves money and road closures, so a `ConstructionEngineer` may declare a **joint trench slot** on a `project_id`, identified by a `segment_code` of 1 to 24 characters naming the corridor segment it serves, bounded by `trench_open_start` and `trench_open_end` — both inclusive boundaries of the opening, with the end strictly later than the start — and limited by `max_occupants`, the maximum number of concurrent occupants it can carry, which must be at least 1. A new slot starts with `occupant_count` 0 and `status` `OPEN`. Both of those fields are derived, never written by a client: `occupant_count` is the number of schedule commitments referencing the slot whose `status` is `COMMITTED` or `IN_PROGRESS`, and the slot's `status` is `OPEN` while `occupant_count` is below `max_occupants` and `FULL` once `occupant_count` has reached `max_occupants`. Both figures move in both directions as commitments are created, completed, breached and cancelled.

### 3.7. Committing Relocation Windows, and the Delinquency Cascade

With a plan approved, the owner commits to a window. Either the owner's `UtilityOwnerRep` or a `UtilityCoordinator` creates a **schedule commitment** against the approved plan's `plan_id`, supplying `window_start` and `window_end` (the end strictly later than the start), the `committed_work_days` the owner promises to work inside that window (greater than 0), and a `phase_dependency` drawn from `BEFORE_GRADING`, `AFTER_GRADING`, `BEFORE_PAVING` and `ANY_PHASE`, which records the construction phasing the relocation must respect. An optional `joint_trench_slot_id` asks to occupy a declared trench opening. Note the asymmetry of the window boundaries, which matters for the arithmetic below: `window_start` is the first instant of the committed window and is inclusive, while `window_end` is the exclusive end instant.

Three foreign keys on the commitment are derived rather than supplied, all denormalised at creation by following the plan to its conflict: `project_id` from the conflict's project, `facility_id` from the conflict's facility — this is the resource against which window collisions are tested — and `owner_id` from that facility's owner, which is what an owner-scope check compares against `X-User-ID`. The commitment opens in `status` `COMMITTED` with `actual_complete_at` null and `late_days` 0.

Four temporal and capacity rules guard creation, and they are evaluated in the ladder order of section 2.9 — construction-window containment first, then facility collision, then trench containment, then trench capacity. The window must lie inside the project's construction window: `window_start` at or after `construction_start_date` and `window_end` at or before `construction_end_date`, failing which the request is refused with `ERR_WINDOW_OUTSIDE_CONSTRUCTION`. The window must not collide with any other commitment on the same `facility_id` that is in `COMMITTED` or `IN_PROGRESS`, and collision is tested with a mobilisation buffer of 3 days added to each end: the proposal is rejected when the new window's start falls before the existing window's end advanced by 3 days *and* the existing window's start falls before the new window's end advanced by 3 days. That rejection is `ERR_FACILITY_WINDOW_CONFLICT`. When a `joint_trench_slot_id` is supplied, the commitment window must be fully contained in the slot's opening, tested inclusively at both ends — the slot's `trench_open_start` at or before `window_start`, and `window_end` at or before the slot's `trench_open_end` — failing which the request is refused with `ERR_TRENCH_WINDOW_NOT_CONTAINED`; and the slot's `occupant_count` must be strictly below its `max_occupants`, failing which it is refused with `ERR_TRENCH_SLOT_AT_CAPACITY`.

A successful creation ripples outward. The conflict advances `RELOCATION_PLANNED → RELOCATION_SCHEDULED`. The owner's `open_commitment_days` is recomputed. When a slot was named, the slot's `occupant_count` increments and its `status` becomes `FULL` at the moment `occupant_count` reaches `max_occupants`. The project's `clearance_posture` is recomputed — which, with a window inside the 60-day look-ahead, typically lands on `AT_RISK`.

The owner's `open_commitment_days` is a workload figure: the total calendar days of relocation work the owner currently owes across every project. It is the sum, over that owner's commitments whose `status` is `COMMITTED` or `IN_PROGRESS`, of the number of days between each commitment's `window_start` and `window_end`. Because `window_end` is exclusive, a window running from the first instant of 5 April 2027 to the first instant of 20 April 2027 contributes 15 days. Commitments in `COMPLETE`, `BREACHED` or `CANCELLED` contribute nothing, which is what makes the figure conserved: it returns to exactly its prior value when a commitment leaves the open set.

Only the owner's own representative may report that work has begun, moving the commitment `COMMITTED → IN_PROGRESS`; a representative of another owner is refused with `ERR_OWNER_SCOPE_VIOLATION`. If this is the first commitment on the project to enter `IN_PROGRESS`, the project advances to `UNDER_CONSTRUCTION` from `CLEARANCE_ACTIVE` or `LETTING_READY`. The commitment's `version` increments.

Reporting completion is the same action with two radically different outcomes, and both are available from either `COMMITTED` or `IN_PROGRESS` — work can be reported complete without having been reported started. The report may carry a `completion_note`, and in both branches `actual_complete_at` is stamped from the logical clock, the owner's `open_commitment_days` is recomputed because the commitment leaves the open set, any occupied slot's `occupant_count` and `status` are recomputed, the project's posture is recomputed, and the commitment's `version` increments.

If the clock instant is at or before `window_end` — the boundary is inclusive, so completing exactly at `window_end` is on time — the commitment moves to `COMPLETE` and `late_days` stays 0. Nothing else happens on this branch: the owner's `delinquency_strikes` is untouched, its `reimbursement_hold` stays as it was, no reimbursement agreement of that owner changes `settlement_status`, and no cost document changes `review_status`. `COMPLETE` is terminal, and it is the state a conflict's certification looks for on the relocate branch.

If the clock instant is later than `window_end`, the commitment moves to `BREACHED`, `late_days` is set to the difference between `actual_complete_at` and `window_end` expressed in days and rounded up to the next whole day (floored at 0), and a four-link cascade fires. First, the owner's `delinquency_strikes` increments by 1. Second, once `delinquency_strikes` reaches 2 — the delinquency hold threshold — the owner's `reimbursement_hold` flips from false to true. Third, because the owner is now on reimbursement hold, every reimbursement agreement of that owner whose `settlement_status` is `PENDING_FINAL_INVOICE` moves to `settlement_status` `HELD`. Fourth, because those agreements went on hold, every cost document of those agreements whose `review_status` is `SUBMITTED` moves to `review_status` `HELD`. Each row touched at each link is a real mutation with its own `version` increment, and only the third and fourth links are reversed by an administrative hold release; the strikes themselves are cleared only by that same release. `BREACHED` is terminal for the commitment, and it is what a contractor delay claim is lodged against.

Cancellation is the compensating action for creation. It may be requested with a `cancellation_reason` from either `COMMITTED` or `IN_PROGRESS`: the owner's own representative may cancel a commitment belonging to that owner, and a `UtilityCoordinator` may cancel one regardless of owner. The commitment moves to `CANCELLED`, which is terminal, and three compensating links restore what creation consumed: the owner's `open_commitment_days` returns to exactly its pre-creation value; any occupied slot's `occupant_count` decrements and its `status` returns to `OPEN` if it had become `FULL`; and the conflict returns `RELOCATION_SCHEDULED → RELOCATION_PLANNED` once no commitment of that conflict remains in `COMMITTED` or `IN_PROGRESS`. The project's posture is recomputed and the commitment's `version` increments. A commitment already `COMPLETE`, `BREACHED` or `CANCELLED` cannot be cancelled, started or completed again; such attempts are refused with `ERR_COMMITMENT_STATE_INVALID`.

### 3.8. Reimbursement Agreements: Drafting, Execution, Billing and Settlement

The **reimbursement agreement** is the instrument by which the State pays its share, and it is the only entity in the system carrying two independent state dimensions on the same row. `execution_status` tracks the contract — `DRAFT`, `PENDING_OWNER_SIGNATURE`, `EXECUTED`, `VOIDED` — while `settlement_status` tracks the money — `NOT_STARTED`, `PENDING_FINAL_INVOICE`, `HELD`, `AUDIT_IN_PROGRESS`, `SETTLED`, `VOIDED_OUT`. The two evolve independently, with one cross-dimension guard: the settlement dimension may leave `NOT_STARTED` only once the execution dimension has reached `EXECUTED`.

An `AgreementOfficer` drafts an agreement against an approved plan's `plan_id`, supplying the `expected_plan_version` demanded by section 2.7 and the `not_to_exceed_cents` ceiling — the contractual maximum, greater than 0, which caps both the chronological accrual of actual costs and the final state share. The ceiling is not accepted blindly: it must be at least the plan's `estimated_cost_cents` loaded with the owner's audited indirect rate, that is, at least the estimate multiplied by 1 plus `indirect_cost_rate_pct` divided by 100, rounded half up to whole cents. A lower ceiling is refused with `ERR_NOT_TO_EXCEED_TOO_LOW`. A drafted agreement opens with `execution_status` `DRAFT`, `settlement_status` `NOT_STARTED` and `cost_basis` `ESTIMATE_BASIS`; its `project_id` and `owner_id` are denormalised from the plan's conflict exactly as a commitment's are; `as_built_reference` and `executed_by_user_id` are null; and all nine settlement figures are computed immediately on the estimate basis. Drafting increments the plan's `version` as the concurrency parent.

Circulation moves the agreement `DRAFT → PENDING_OWNER_SIGNATURE` and nothing else. Execution moves it `PENDING_OWNER_SIGNATURE → EXECUTED` and is the most heavily gated action in the system: the agreement must be in `PENDING_OWNER_SIGNATURE` (otherwise `ERR_AGREEMENT_NOT_EXECUTABLE`); the project's `clearance_posture` must not be `FUNDING_BLOCKED` (otherwise `ERR_CLEARANCE_POSTURE_BLOCKED`); the counterparty owner's `reimbursement_hold` must be false (otherwise `ERR_OWNER_ON_REIMBURSEMENT_HOLD`); and the project's `total_committed_reimbursement_cents` plus this agreement's `state_share_cents` must be no greater than the project's `reimbursement_authority_cents` (otherwise `ERR_AUTHORITY_EXCEEDED`). On success `executed_by_user_id` is stamped with the acting `X-User-ID` — the stamp that later bars that same person from auditing this agreement — the project's committed ledger is recomputed, the posture is recomputed from the new ledger value, and the agreement's `version` increments.

That ledger, `total_committed_reimbursement_cents`, is the sum of `state_share_cents` over every agreement of the project whose `execution_status` is `EXECUTED`. Agreements in `DRAFT`, `PENDING_OWNER_SIGNATURE` or `VOIDED` contribute nothing. Because an agreement stays `EXECUTED` across its settlement, a final settlement that revises `state_share_cents` moves the ledger by exactly the revision delta.

Voiding is the compensating action for execution, requires a `void_reason`, and is available from `DRAFT`, `PENDING_OWNER_SIGNATURE` or `EXECUTED` provided `settlement_status` is not `SETTLED` — a settled agreement cannot be voided, and the attempt returns `ERR_SETTLEMENT_STATE_INVALID`. In every case `execution_status` becomes `VOIDED` and `settlement_status` becomes `VOIDED_OUT`, from whichever of `NOT_STARTED`, `PENDING_FINAL_INVOICE`, `HELD` or `AUDIT_IN_PROGRESS` it held. Voiding an agreement that had reached `EXECUTED` additionally reverses its ledger effect: the project's `total_committed_reimbursement_cents` drops by exactly this agreement's `state_share_cents` and returns to its pre-execution value, and the posture is recomputed from the restored ledger. Both `VOIDED` and `VOIDED_OUT` are terminal.

Opening final billing moves `settlement_status` `NOT_STARTED → PENDING_FINAL_INVOICE` and requires `execution_status` to be `EXECUTED`; attempted on an unexecuted agreement it returns `ERR_AGREEMENT_NOT_EXECUTABLE`, and attempted on an agreement whose settlement has already started it returns `ERR_SETTLEMENT_STATE_INVALID`.

**Cost documentation.** While the agreement sits in `PENDING_FINAL_INVOICE`, the owner's representative submits **cost documents** against its `agreement_id`. Each declares a `doc_type` from `LABOR`, `MATERIAL`, `EQUIPMENT`, `CONTRACT`, `INDIRECT` and `CREDIT_SALVAGE`; an `amount_cents` greater than 0, always an absolute magnitude, with `CREDIT_SALVAGE` rows subtracted rather than added; an `incurred_on` instant, which is the primary sort key of the accrual; and a `support_reference` naming the payroll register or invoice number behind it, up to 120 characters. A submitted document opens in `review_status` `SUBMITTED` with `disallowed_amount_cents` 0 and `exclusion_reason` null. Submission outside `PENDING_FINAL_INVOICE` is refused with `ERR_SETTLEMENT_STATE_INVALID`.

The agreement officer then dispositions each document with a `disposition` of `ACCEPT` or `DISALLOW`, and both branches require the parent agreement to be in `PENDING_FINAL_INVOICE` and the document to be in `SUBMITTED`. An acceptance moves it `SUBMITTED → ACCEPTED`, sets `disallowed_amount_cents` to 0 and clears `exclusion_reason` to null. A disallowance moves it `SUBMITTED → DISALLOWED`, sets `disallowed_amount_cents` to the document's full `amount_cents` — rows are excluded whole, never partially — and records the supplied `exclusion_reason`, which for a manual disallowance is either `NOT_SUPPORTED` or `SUSTAINED_AUDIT_FINDING`. Either disposition recomputes the agreement's nine settlement figures on its current `cost_basis` and increments the document's `version`. The third value of `exclusion_reason`, `EXCEEDS_NOT_TO_EXCEED_CAP`, is never supplied by a client; it is written only by the settlement cutoff described below. `DISALLOWED` is terminal for a document. The two hold transitions are the ones nobody requests: a `SUBMITTED` document moves to `HELD` when its agreement is swept into `HELD` by an owner's delinquency, and returns `HELD → SUBMITTED` when the hold is released.

**Audit rights.** An `ExternalAuditor` may question costs by raising an **audit finding** against an `agreement_id`, declaring a `finding_type` from `UNSUPPORTED_COST`, `INELIGIBLE_BETTERMENT`, `INDIRECT_RATE_ERROR` and `DUPLICATE_BILLING`, and a `questioned_cost_cents` greater than 0. The finding is stamped with `auditor_user_id` from `X-User-ID` and opens in `status` `OPEN` with `disposition` null. An auditor whose `X-User-ID` matches the agreement's `executed_by_user_id` is refused with `ERR_SEGREGATION_OF_DUTIES` — the officer who executed an agreement may not audit it. Raising a finding suspends settlement: an agreement in `PENDING_FINAL_INVOICE` moves to `AUDIT_IN_PROGRESS`, and its `version` increments. Resolving a finding moves it `OPEN → RESOLVED` with a `disposition` of `SUSTAINED` or `WITHDRAWN`, and once no finding of that agreement remains `OPEN`, the agreement returns `AUDIT_IN_PROGRESS → PENDING_FINAL_INVOICE`. `RESOLVED` is terminal, and a second resolution is `ERR_INVALID_STATE_TRANSITION`.

**Final settlement.** Settling moves `settlement_status` `PENDING_FINAL_INVOICE → SETTLED`, requires an `as_built_reference` in the request body, and is refused unless three conditions hold: the agreement is in `PENDING_FINAL_INVOICE` (otherwise `ERR_SETTLEMENT_STATE_INVALID`), no audit finding of the agreement is `OPEN` (otherwise `ERR_OPEN_AUDIT_FINDING`), and at least one cost document of the agreement is `ACCEPTED` with a `doc_type` other than `CREDIT_SALVAGE` and `INDIRECT` (otherwise `ERR_NO_ELIGIBLE_COST_DOCUMENTATION`). The owner must also be off reimbursement hold, and the resulting ledger must still fit within the project's authority. On success the `as_built_reference` is stamped, `cost_basis` switches `ESTIMATE_BASIS → ACTUAL_BASIS`, all nine money figures are recomputed on the actual basis, every previously `ACCEPTED` document that the chronological cutoff drops moves `ACCEPTED → DISALLOWED` with `exclusion_reason` `EXCEEDS_NOT_TO_EXCEED_CAP` and `disallowed_amount_cents` equal to its own `amount_cents`, the project's `total_committed_reimbursement_cents` is recomputed from the settled share, the posture is recomputed, and the agreement's `version` increments. `SETTLED` is terminal.

**Eligible direct cost, in two variants.** The agreement's `eligible_cost_cents` is the direct eligible cost, and which variant produces it is recorded in `cost_basis`.

Under `ESTIMATE_BASIS`, which holds from drafting until final settlement, `eligible_cost_cents` is simply the governing plan's `estimated_cost_cents`, taken verbatim. Cost documents and the not-to-exceed ceiling do not affect it at all.

Under `ACTUAL_BASIS`, set by final settlement, the figure is rebuilt from documentation. Only cost documents of the agreement whose `review_status` is `ACCEPTED` and whose `doc_type` is not `INDIRECT` are eligible to enter; documents in `SUBMITTED`, `HELD` or `DISALLOWED` never enter, and `INDIRECT` rows are excluded on principle because indirect cost is computed from the owner's audited rate rather than billed as a line. Those eligible rows are sorted by `incurred_on` ascending, with `created_at` ascending as the only tie-break — the record `id` is never used to order rows or to break ties. The accrual then walks the sorted rows in order, keeping a running total that starts at 0. For each row, its signed value is the negative of its `amount_cents` when its `doc_type` is `CREDIT_SALVAGE` and the positive `amount_cents` otherwise; the candidate total is the running total plus that signed value. If the candidate total would be greater than the agreement's `not_to_exceed_cents`, the document is excluded whole — marked with `exclusion_reason` `EXCEEDS_NOT_TO_EXCEED_CAP` — the running total is left untouched, and the walk **continues to the following documents**, so a later, smaller document can still be included after a large one was skipped. Otherwise the candidate total becomes the running total and the document is included. `eligible_cost_cents` is the running total at the end of the walk.

That per-document test is the point of the algorithm, and summing every eligible row and then clamping the total to the ceiling is a different and wrong answer whenever one document straddles the ceiling: rows of 12,345,678, then 9,876,543, then a 1,000,000 salvage credit, then 30,000,000, against a ceiling of 45,000,000, accrue to 21,222,221 under the rule above, while sum-then-clamp yields 45,000,000.

**The nine settlement figures.** From the eligible direct cost, the State's share and the owner's residual are derived in nine ordered steps, and the same chain runs at drafting, at each cost-document disposition while the agreement is in final billing, and at final settlement.

1. The direct eligible cost is `eligible_cost_cents`, produced by whichever variant the current `cost_basis` names.
2. The indirect allowance, `indirect_cost_cents`, is the direct eligible cost multiplied by the owner's `indirect_cost_rate_pct` divided by 100, rounded half up to whole cents. This rounding happens here, before the figure is used anywhere else.
3. The gross allowable is the direct eligible cost plus the indirect allowance. It is not stored on its own.
4. The betterment credit, `betterment_credit_cents`, is the credit withheld from the owner: the plan-level betterment amount under `ESTIMATE_BASIS`, and the per-line re-derivation of section 3.5 under `ACTUAL_BASIS`.
5. The net allowable, `net_allowable_cents`, is the gross allowable minus the betterment credit, floored at 0.
6. The `participation_tier_pct` is selected from the net allowable — never from the gross — and is applied to the whole net allowable as a single rate, never marginally. A net allowable at or below 5,000,000 cents (fifty thousand dollars) takes a tier of 100. A net allowable above that but at or below 50,000,000 cents (five hundred thousand dollars) takes a tier of 95. Anything larger takes a tier of 90.
7. The uncapped state share is the net allowable multiplied by the conflict's `state_share_pct` divided by 100 and by the `participation_tier_pct` divided by 100, with both percentages applied in one expression and the result rounded half up to whole cents exactly once.
8. `state_share_cents` is the lesser of that uncapped share and the agreement's `not_to_exceed_cents`.
9. `owner_share_cents` is the net allowable minus `state_share_cents`, taken as a difference so that the two shares always sum to the net allowable exactly.

Rounding in this chain occurs at step 2 and step 7 only; every other step is exact integer arithmetic on cents.

### 3.9. Contractor Delay Claims

When a relocation runs past its window, the prime contractor's costs do not stop, and the claim that follows has to be split between the utility owner who was late and the State that scheduled the work. A `ConstructionEngineer` lodges a **delay claim** naming the `project_id` and the `commitment_id` whose late performance is alleged to have caused the delay, the `contractor_name` (1 to 160 characters), the `claimed_days` of calendar delay asserted (greater than 0) and the `claimed_amount_cents` claimed in total (greater than 0). The claim opens in `status` `SUBMITTED` with `delay_cause` null and `compensable_days`, `daily_rate_cents`, `allocated_to_owner_cents` and `allocated_to_state_cents` all 0.

Analysis moves the claim `SUBMITTED → UNDER_ANALYSIS` and requires the referenced commitment to have reached `COMPLETE` or `BREACHED`; a claim against a commitment still in `COMMITTED` or `IN_PROGRESS` is refused with `ERR_COMMITMENT_STATE_INVALID`. The engineer supplies the adjudicated `delay_cause`, one of `UTILITY_OWNER`, `UTILITY_OWNER_PERMIT_WAIT`, `STATE_PERMIT_DELAY` or `THIRD_PARTY`, and the server computes the two figures that determine whether the claim is worth anything:

- **Compensable days.** Contracts carry float, and the first 5 days of lateness are absorbed by it. Take the commitment's `late_days`, subtract the 5 contractual float days, and floor the result at 0; then take the lesser of that figure and the claim's `claimed_days`. The result is `compensable_days`. A commitment 5 days late or less therefore yields nothing compensable however much the contractor claims.
- **Daily rate.** The contractor's implied rate is its `claimed_amount_cents` divided by its `claimed_days`, rounded half up to whole cents. `daily_rate_cents` is the lesser of that implied rate and the project's `contract_daily_overhead_cents` ceiling, so a contractor cannot claim a daily rate above the one its own contract stipulates.

Allocation moves the claim `UNDER_ANALYSIS → ALLOCATED` and requires `compensable_days` to be greater than 0; a claim with nothing compensable is refused with `ERR_DELAY_NOT_COMPENSABLE`. The gross compensable amount is `compensable_days` multiplied by `daily_rate_cents`, and the adjudicated `delay_cause` decides the owner's share of it: a cause of `UTILITY_OWNER` charges 100 percent to the owner; `UTILITY_OWNER_PERMIT_WAIT` charges 60 percent, on the reasoning that the owner bears most but not all of a wait it did not solely create; `THIRD_PARTY` charges 50 percent; and `STATE_PERMIT_DELAY` charges 0 percent, leaving the whole of it with the State. `allocated_to_owner_cents` is the gross multiplied by that percentage divided by 100, rounded half up to whole cents, and `allocated_to_state_cents` is the gross minus `allocated_to_owner_cents` — a residual, so the two always sum to the gross exactly and the State's portion is never independently rounded.

Allocation also moves two conserved figures. The project's `aggregate_compensable_delay_days` is the sum of `compensable_days` across the project's claims whose `status` is `ALLOCATED`. The owner's `assessed_delay_liability_cents` is the sum of `allocated_to_owner_cents` across all claims in `ALLOCATED` whose commitment belongs to that owner. Claims in `SUBMITTED`, `UNDER_ANALYSIS` or `DENIED` contribute nothing to either figure.

Withdrawing an allocation is the compensating action: with a `withdrawal_reason`, the claim returns `ALLOCATED → UNDER_ANALYSIS`, `allocated_to_owner_cents` and `allocated_to_state_cents` are both reset to 0, and both conserved figures return to exactly their pre-allocation values. The claim can then be re-analysed and allocated again, which is why the allocation cycle `UNDER_ANALYSIS → ALLOCATED → UNDER_ANALYSIS` is a genuine loop rather than a one-way street. Denial, with a `denial_reason`, is available from either `SUBMITTED` or `UNDER_ANALYSIS` and moves the claim to `DENIED`, which is terminal; a denied claim contributes nothing to either conserved figure and blocks nothing at project closure. Every one of these transitions increments the claim's `version`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including the state-driving action endpoints, the project revision endpoint and the administrative clock endpoint — return `200 OK`. Reads return `200 OK`. All authorised-role lists below are exhaustive: a role absent from a row cannot invoke that endpoint, and the attempt returns `ERR_UNAUTHORIZED`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| GET | `/uro/projects` | List highway projects | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ConstructionEngineer, ExternalAuditor |
| GET | `/uro/projects/{id}` | Fetch one project with its derived posture and money figures | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ConstructionEngineer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/projects/{id}/clearance-summary` | Computed read of the project's clearance posture inputs, including the warning look-ahead | ProgramAdmin, UtilityCoordinator, ConstructionEngineer |
| GET | `/uro/projects/{id}/joint-trench-slots` | List the joint trench openings declared on a project | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/utility-owners` | List utility owners | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ExternalAuditor |
| GET | `/uro/utility-owners/{id}` | Fetch one utility owner with its delinquency and hold posture | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/utility-owners/{id}/facilities` | List the facilities of record for one owner | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, UtilityOwnerRep |
| GET | `/uro/facilities/{id}` | Fetch one utility facility of record | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/investigations` | List subsurface investigations, filterable by project, facility and quality level | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, ConstructionEngineer |
| GET | `/uro/investigations/{id}` | Fetch one subsurface investigation record (immutable) | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, ConstructionEngineer |
| GET | `/uro/conflicts` | List utility conflicts, filterable by project, facility, predecessor conflict and status | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/conflicts/{id}` | Fetch one utility conflict, including its frozen state share and its version for optimistic concurrency | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/conflicts/{id}/prior-rights` | List the prior-rights determinations raised on one conflict | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, UtilityOwnerRep |
| GET | `/uro/conflicts/{id}/relocation-plans` | List the relocation plans submitted on one conflict, including superseded ones | ProgramAdmin, UtilityCoordinator, AgreementOfficer, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/conflicts/{id}/permits` | List the permits and easement acquisitions tracked for one conflict | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/prior-rights/{id}` | Fetch one prior-rights determination with its evidence variant and share percentages | ProgramAdmin, UtilityCoordinator, RightOfWayAdjudicator, AgreementOfficer, UtilityOwnerRep |
| GET | `/uro/relocation-plans/{id}` | Fetch one relocation plan, including its derived betterment ratio and its version for optimistic concurrency | ProgramAdmin, UtilityCoordinator, AgreementOfficer, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/permits/{id}` | Fetch one permit or easement acquisition record | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/joint-trench-slots/{id}` | Fetch one joint trench slot with its occupancy count | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, UtilityOwnerRep |
| GET | `/uro/commitments` | List schedule commitments, filterable by plan, project, facility, owner, trench slot and status | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, AgreementOfficer, UtilityOwnerRep |
| GET | `/uro/commitments/{id}` | Fetch one schedule commitment with its lateness figures | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, AgreementOfficer, UtilityOwnerRep |
| GET | `/uro/agreements` | List reimbursement agreements, filterable by plan, project, owner and either state dimension | ProgramAdmin, UtilityCoordinator, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/agreements/{id}` | Fetch one reimbursement agreement with all nine settlement figures and both state dimensions | ProgramAdmin, UtilityCoordinator, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/agreements/{id}/settlement-preview` | Computed read that re-runs the settlement chain on the actual cost basis without mutating the agreement, exposing which cost documents the chronological cutoff would exclude | ProgramAdmin, AgreementOfficer, ExternalAuditor |
| GET | `/uro/agreements/{id}/cost-documents` | List the cost documentation submitted under one agreement | ProgramAdmin, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/agreements/{id}/audit-findings` | List the audit findings raised against one agreement | ProgramAdmin, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/cost-documents/{id}` | Fetch one cost document with its disallowance figures | ProgramAdmin, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/audit-findings/{id}` | Fetch one audit finding | ProgramAdmin, AgreementOfficer, ExternalAuditor, UtilityOwnerRep |
| GET | `/uro/delay-claims` | List contractor delay claims, filterable by project, commitment and status | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, AgreementOfficer, UtilityOwnerRep |
| GET | `/uro/delay-claims/{id}` | Fetch one contractor delay claim with its compensability and allocation figures | ProgramAdmin, UtilityCoordinator, ConstructionEngineer, AgreementOfficer, UtilityOwnerRep |
| POST | `/uro/projects` | Register a highway project with its construction window, right-of-way acquisition year and reimbursement authority | ProgramAdmin |
| PATCH | `/uro/projects/{id}` | Revise a project's programmed authority, daily overhead ceiling or letting date | ProgramAdmin |
| POST | `/uro/projects/{id}/close` | Close a project once every conflict is cleared and every agreement is settled or voided out | ProgramAdmin |
| POST | `/uro/utility-owners` | Register a utility owner with its audited indirect cost rate | ProgramAdmin |
| POST | `/uro/utility-owners/{id}/release-hold` | Release a utility owner's reimbursement hold, reversing the hold cascade | ProgramAdmin |
| POST | `/uro/facilities` | Record a utility facility of record with its occupancy basis, depth and installation year | ProgramAdmin, UtilityCoordinator |
| POST | `/uro/investigations` | Record an immutable subsurface investigation result | UtilityCoordinator |
| POST | `/uro/conflicts` | Open a utility conflict between the design and a facility of record, optionally sequenced behind another conflict | UtilityCoordinator |
| POST | `/uro/conflicts/{id}/set-resolution` | Select the engineering resolution for a conflict | UtilityCoordinator |
| POST | `/uro/conflicts/{id}/certify-cleared` | Certify a conflict as cleared once its work is complete and any predecessor conflict is cleared | UtilityCoordinator |
| POST | `/uro/prior-rights` | Open a prior-rights determination on a conflict, asserting the occupancy basis claimed by the owner | RightOfWayAdjudicator |
| POST | `/uro/prior-rights/{id}/submit-for-review` | Move a drafted determination into adjudicative review | RightOfWayAdjudicator |
| POST | `/uro/prior-rights/{id}/return-for-revision` | Return a determination under review for revision of its claimed basis or narrative | RightOfWayAdjudicator |
| POST | `/uro/prior-rights/{id}/revise` | Revise a returned or appealed determination | RightOfWayAdjudicator |
| POST | `/uro/prior-rights/{id}/issue` | Issue the determination, freezing the state share the conflict will carry | RightOfWayAdjudicator |
| POST | `/uro/prior-rights/{id}/appeal` | Owner appeal of an issued determination, reopening it for one further round of adjudication | UtilityOwnerRep |
| POST | `/uro/permits` | Open a permit, easement acquisition, railroad crossing or environmental clearance record against a conflict | UtilityCoordinator |
| POST | `/uro/permits/{id}/decide` | Record the granting or denial of a permit or easement acquisition | UtilityCoordinator |
| POST | `/uro/joint-trench-slots` | Declare a joint trench opening on a project that several owners may share | ConstructionEngineer |
| POST | `/uro/relocation-plans` | Submit a relocation plan for a conflict, superseding any earlier non-superseded plan on the same conflict | UtilityCoordinator, UtilityOwnerRep |
| POST | `/uro/relocation-plans/{id}/start-review` | Take a submitted plan into utility-coordination review | UtilityCoordinator |
| POST | `/uro/relocation-plans/{id}/request-revision` | Return a plan under review to the owner for revision | UtilityCoordinator |
| POST | `/uro/relocation-plans/{id}/resubmit` | Resubmit a revised plan with new cost and capacity figures | UtilityOwnerRep, UtilityCoordinator |
| POST | `/uro/relocation-plans/{id}/approve` | Approve a plan for scheduling, once prior rights are issued and every permit of the conflict is granted | UtilityCoordinator |
| POST | `/uro/commitments` | Commit a relocation work window against an approved plan, optionally occupying a joint trench slot | UtilityOwnerRep, UtilityCoordinator |
| POST | `/uro/commitments/{id}/start-work` | Report that relocation work has started on a committed window | UtilityOwnerRep |
| POST | `/uro/commitments/{id}/report-complete` | Report relocation completion; a late report breaches the commitment and starts the delinquency cascade | UtilityOwnerRep |
| POST | `/uro/commitments/{id}/cancel` | Cancel a commitment that has not completed, releasing its window and trench occupancy | UtilityOwnerRep, UtilityCoordinator |
| POST | `/uro/agreements` | Draft a reimbursement agreement against an approved plan on an estimate basis | AgreementOfficer |
| POST | `/uro/agreements/{id}/circulate` | Circulate a drafted agreement for owner signature | AgreementOfficer |
| POST | `/uro/agreements/{id}/execute` | Execute a circulated agreement, committing its state share against the project's programmed authority | AgreementOfficer |
| POST | `/uro/agreements/{id}/void` | Void an agreement, reversing any ledger commitment it made | AgreementOfficer |
| POST | `/uro/agreements/{id}/open-final-billing` | Open final billing on an executed agreement so the owner may submit cost documentation | AgreementOfficer |
| POST | `/uro/agreements/{id}/final-settlement` | Settle the agreement on an actual cost basis against the as-built documentation | AgreementOfficer |
| POST | `/uro/cost-documents` | Submit a cost document under an agreement in final billing | UtilityOwnerRep |
| POST | `/uro/cost-documents/{id}/review` | Accept or disallow a submitted cost document | AgreementOfficer |
| POST | `/uro/audit-findings` | Raise an audit finding questioning costs on an agreement, which suspends its settlement | ExternalAuditor |
| POST | `/uro/audit-findings/{id}/resolve` | Resolve an audit finding as sustained or withdrawn | ExternalAuditor |
| POST | `/uro/delay-claims` | Lodge a contractor delay claim against a commitment whose relocation ran late | ConstructionEngineer |
| POST | `/uro/delay-claims/{id}/analyze` | Analyse a claim, adjudicating its delay cause and computing compensable days and the daily rate | ConstructionEngineer |
| POST | `/uro/delay-claims/{id}/allocate` | Allocate an analysed claim between the utility owner and the State | ConstructionEngineer |
| POST | `/uro/delay-claims/{id}/withdraw-allocation` | Withdraw an allocation and return the claim to analysis, reversing both conserved figures | ConstructionEngineer |
| POST | `/uro/delay-claims/{id}/deny` | Deny a claim outright | ConstructionEngineer |
| POST | `/_clock/set_current_utc` | Set the logical clock used for stamped instants, lateness arithmetic and the clearance look-ahead | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_OWNER_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROJECT_NOT_FOUND` | 404 Not Found |
| `ERR_OWNER_NOT_FOUND` | 404 Not Found |
| `ERR_FACILITY_NOT_FOUND` | 404 Not Found |
| `ERR_INVESTIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_CONFLICT_NOT_FOUND` | 404 Not Found |
| `ERR_DETERMINATION_NOT_FOUND` | 404 Not Found |
| `ERR_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_PERMIT_NOT_FOUND` | 404 Not Found |
| `ERR_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_COMMITMENT_NOT_FOUND` | 404 Not Found |
| `ERR_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_DOCUMENT_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_AGREEMENT_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_SETTLEMENT_STATE_INVALID` | 409 Conflict |
| `ERR_COMMITMENT_STATE_INVALID` | 409 Conflict |
| `ERR_PROJECT_CLOSED` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CLEARANCE_POSTURE_BLOCKED` | 409 Conflict |
| `ERR_OWNER_ON_REIMBURSEMENT_HOLD` | 409 Conflict |
| `ERR_PRIOR_RIGHTS_NOT_ISSUED` | 409 Conflict |
| `ERR_PERMIT_NOT_GRANTED` | 409 Conflict |
| `ERR_DEPENDENCY_NOT_CLEARED` | 409 Conflict |
| `ERR_EXECUTED_AGREEMENT_BLOCKS_SUPERSEDE` | 409 Conflict |
| `ERR_OPEN_AUDIT_FINDING` | 409 Conflict |
| `ERR_NO_ELIGIBLE_COST_DOCUMENTATION` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_CONSTRUCTION` | 422 Unprocessable Entity |
| `ERR_FACILITY_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TRENCH_WINDOW_NOT_CONTAINED` | 422 Unprocessable Entity |
| `ERR_TRENCH_SLOT_AT_CAPACITY` | 409 Conflict |
| `ERR_REVISION_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_APPEAL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NOT_TO_EXCEED_TOO_LOW` | 422 Unprocessable Entity |
| `ERR_AUTHORITY_EXCEEDED` | 409 Conflict |
| `ERR_DELAY_NOT_COMPENSABLE` | 422 Unprocessable Entity |
| `ERR_PROJECT_CLOSE_BLOCKED` | 409 Conflict |

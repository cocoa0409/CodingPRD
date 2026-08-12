# Owner's Representative & Program Management API — Product Requirements Document

## 1. Introduction

Owner organizations that run capital construction programs rarely manage them alone. They engage an owner's-representative firm to stand up the program charter, set the budget and schedule baseline, procure consultants and contractors, negotiate their contracts, report monthly on cost-to-complete, review change orders, manage a risk register and a contingency pool, coordinate stakeholder and user groups, plan occupancy and move-in, and finally drive closeout while capturing lessons learned. This API is the system of record for exactly that engagement: it models a capital **Program** from chartering through activation, execution, and closing, and it governs every artifact the owner's representative produces along the way.

Three governance themes shape the entire design. First, **segregation of duties**: the person who negotiates a contract may not execute it, the person who recommends a change order may not decide it, the person who submits a monthly report may not accept it, and the person who submits closeout evidence may not verify it. Second, **a conserved contingency pool**: every dollar of contingency is, at all times, exactly one of reserved, committed, drawn, or available, and the pool's remaining headroom drives a program-wide posture that can itself block new commitments. Third, **decision-time consistency**: because an owner may legitimately approve a second charter or baseline after a competing decision has landed, charter and baseline decisions carry an optimistic-concurrency token on the program itself, so a decision made against a stale view of the program is rejected rather than silently superseding work the decider never saw. The remainder of this document specifies the global contracts every endpoint honors, the business workflows entity by entity, the endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting operator and `X-User-Role` to specify their operational capacity. The system recognizes three distinct roles:

- `OwnerRepPM` — the owner's-representative project manager, who prepares and manages all program artifacts: programs, charters, baselines, contracts (including negotiation and counters), change-order submission and recommendation, the risk register, contingency drawdowns, owner reports, stakeholder coordination, occupancy planning, closeout preparation, and lessons learned.
- `OwnerRepExecutive` — the owner's-representative executive, who executes negotiated contracts and verifies or rejects closeout items, each strictly segregated from the preparer.
- `Owner` — the owner, who decides charters, baselines, and change orders, accepts or returns owner reports, and closes the program.

For all three roles — when `X-User-Role` is `OwnerRepPM`, when it is `OwnerRepExecutive`, and when it is `Owner` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as an audit trail on the artifacts the operator touches (for example, as `submitted_by_user_id` on a Charter, as `decided_by_user_id` on a ChangeOrder, or as `executed_by_user_id` on a Contract), but it never compares `X-User-ID` to any entity's `id`. What `X-User-ID` does anchor is the segregation-of-duties comparisons between two recorded actor fields described in §2.9.

If either header is missing or empty, or if `X-User-Role` is not one of the declared roles above, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). An authenticated role that is not in an endpoint's authorized set is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403). Every GET endpoint is shared: all three roles may call every list and retrieval endpoint.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Every list endpoint accepts these two optional parameters in addition to its resource-specific filters.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

All resources in this system — Programs, Charters, Baselines, Contracts, ChangeOrders, RiskEntries, ContingencyDrawdowns, OwnerReports, StakeholderGroups, EngagementItems, OccupancyPlans, MoveInWaves, and CloseoutItems — carry a standard set of system-managed fields:

- **`id` (string):** A unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** An ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`) indicating when the resource was first created.
- **`updated_at` (string):** An ISO 8601 UTC timestamp with three fractional digits indicating when the resource was last modified. It is refreshed upon any change to the resource.
- **`version` (integer):** A system-managed integer that starts at 1 at creation and increments by exactly 1 on every mutation of the resource. This field underpins the optimistic concurrency control described in §2.6.

Every mutation of an entity — whether driven directly by a client request or indirectly by a cascade from another entity — increments that entity's own `version` by 1 and refreshes its `updated_at`. One entity stands apart: the **LessonEntry** is an append-only log and carries only `id` and `created_at`. It has no `updated_at` and no `version`, and it supports no update or delete operation.

### 2.5. Request Validation Pipeline and Priority Ordering

Every request is evaluated against an ordered pipeline of checks, and the **first** failing check determines the rejection — a later rule can never mask an earlier failure with its own error code. The pipeline order is fixed:

1. **Authentication context.** The `X-User-Role` and `X-User-ID` headers must both be present and non-empty, and the role must be declared; failures surface `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400).
2. **Role authorization.** The role must be authorized for the endpoint per the access matrix; failures surface `ERR_UNAUTHORIZED_ROLE` (403).
3. **Request-body shape.** Required fields must be present, types must match, enum values must be valid members, amounts must be positive integers where required, and time ranges must have the end strictly after the start; failures surface `ERR_INVALID_REQUEST` (400).
4. **Resource existence.** Identifiers in the path are validated first, then body-supplied foreign-key ids; each missing resource surfaces its own 404 code from the `ERR_PROGRAM_NOT_FOUND` through `ERR_CLOSEOUT_ITEM_NOT_FOUND` family (see §2.10).
5. **State gates.** The target and parent entities must be in a state from which the requested transition exists, including program lifecycle gates (such as ACTIVE-only creation) and the posture gate on change-order submission; failures surface the 409 codes `ERR_INVALID_TRANSITION`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_NO_APPROVED_CHARTER`, `ERR_NO_APPROVED_BASELINE`, `ERR_CONTRACT_NOT_EXECUTED`, `ERR_OPEN_CHANGE_ORDERS_EXIST`, `ERR_PROGRAM_HAS_OPEN_ITEMS`, `ERR_CLOSEOUT_INCOMPLETE`, `ERR_LESSON_ENTRIES_REQUIRED`, `ERR_CONTINGENCY_POSTURE_CRITICAL`, `ERR_PLAN_NOT_READY`, `ERR_PLAN_NOT_ACCEPTING_WAVES`, or `ERR_OPEN_WAVES_EXIST`.
6. **Segregation of duties.** The four segregated handoffs of §2.9 are checked here; failures surface `ERR_SEGREGATION_OF_DUTIES` (403).
7. **Cross-program referential integrity.** Body-supplied foreign keys must be co-resident in the same program, and a change order's supersede target must be valid; failures surface `ERR_CROSS_PROGRAM_REFERENCE` or `ERR_SUPERSEDES_TARGET_INVALID` (409).
8. **Temporal interval occupation.** Dock overlap on wave creation and confirmation, and — for engagement scheduling — the closed-interval overlap check **first**, then the daily-cap check; failures surface `ERR_DOCK_OVERLAP`, `ERR_ENGAGEMENT_OVERLAP`, or `ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED` (409).
9. **Uniqueness.** At most one owner report per program and period; failures surface `ERR_DUPLICATE_REPORT_PERIOD` (409).
10. **Fiscal limits.** Award-within-budget, draw/reserve/loss-within-contingency, and rebaseline-undercut checks come last; failures surface `ERR_AWARD_EXCEEDS_BUDGET`, `ERR_CONTINGENCY_EXCEEDED`, or `ERR_BASELINE_UNDERCUTS_COMMITMENTS` (402).

Because of this ordering, a stale-state request also carrying a segregation-of-duties violation is rejected as a state error (step 5) rather than a duties error (step 6), and a fiscally impossible request whose body is malformed is rejected with `ERR_INVALID_REQUEST` long before any 402 is considered.

### 2.6. Optimistic Concurrency Control on Program Decisions

Two write operations — and only these two — are protected by optimistic concurrency control against the Program's `version`:

- The **charter decision** requires a non-optional `expected_program_version` field in the request body, carrying the client's last observed `version` of the program. If that value does not match the program's current `version`, the decision is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).
- The **baseline decision** likewise requires a non-optional `expected_program_version`, and a mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).

This protection exists because a charter or baseline decision itself advances `Program.version` (see §3.1): a second decision made against a view captured before an earlier decision landed must fail explicitly rather than supersede work the decider never observed. No other endpoint accepts a version field — endpoints not named above do not take `expected_program_version` or any other expected-version input.

### 2.7. The Contingency Pool: Conservation and Posture

Every program carries a single contingency pool, expressed through five fields on the Program resource. `contingency_total_cents` is the pool size carved out by the currently approved baseline (0 before any baseline has been approved). `contingency_reserved_cents`, `contingency_committed_cents`, and `contingency_drawn_cents` aggregate the program's drawdowns: the first sums `amount_cents` over the program's ContingencyDrawdowns in `RESERVED`, the second over those in `COMMITTED`, and the third over those in `DRAWN`. `contingency_available_cents` is the remainder — the pool total minus reserved, minus committed, minus drawn.

The pool obeys a **conservation invariant at all times**: the pool total is exactly the sum of reserved, committed, drawn, and available. No operation may create or destroy contingency; drawdown lifecycle transitions and the change-order and risk cascades merely move amounts among the four buckets.

Derived from the pool is the program's `contingency_posture`, recomputed on every pool change:

- If `contingency_total_cents` is 0, the posture is `CRITICAL` — which is why a brand-new program, before any baseline approval, already sits in `CRITICAL` posture.
- Otherwise, the ratio of `contingency_available_cents` to `contingency_total_cents` is compared against two inclusive floors: a ratio of at least 30 percent yields `NORMAL`; a ratio below 30 percent but at least 10 percent yields `WATCH`; anything below 10 percent yields `CRITICAL`. The floors are inclusive — a ratio of exactly 0.30 is `NORMAL`, and a ratio of exactly 0.10 is `WATCH`.
- The ratio comparison is performed in exact integer arithmetic — the available amount multiplied by one hundred is compared against the floor percentage multiplied by the pool total — with no floating-point rounding.

Posture is not merely informational: while posture is `CRITICAL`, change-order submission is refused (§3.3), and the trend-based cost forecast doubles its pending-change-order allowance (§3.6).

### 2.8. Monetary Precision, Rounding, and Calendar Conventions

All monetary values in this system are **integer cents** — amounts such as budgets, awards, exposures, and drawdowns are whole numbers of cents with no fractional part. Wherever a computation produces a fractional cent, the result is rounded **half-up** to a whole cent. Two quantities are not cents at all: the move-in readiness percentages, which are rounded half-up to **two decimal places**, and engagement durations, which are whole minutes.

Calendar conventions are uniform. The baseline's `target_finish_date` is a calendar date in `YYYY-MM-DD` form. The owner report's `period` and the occupancy plan's `target_move_month` are calendar months in `YYYY-MM` form. Engagement and wave times (`scheduled_start`, `scheduled_end`, `move_start`, `move_end`) are ISO 8601 UTC datetimes, and the daily-cap accounting in §3.7 keys on the **UTC calendar date** of an engagement's start.

### 2.9. Segregation of Duties

Four handoffs in this system are segregated: the operator on one side of the handoff must be a different person than the operator on the other side. A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), checked at priority 6 of the pipeline in §2.5.

- **Negotiator vs. executor.** The OwnerRepExecutive who executes a contract must not be the operator recorded as that contract's `negotiator_user_id`.
- **Recommender vs. decider.** The Owner who decides a change order must not be the operator recorded as that change order's `recommended_by_user_id`.
- **Submitter vs. accepter.** The Owner who accepts an owner report must not be the operator recorded as that report's `submitted_by_user_id`.
- **Submitter vs. verifier.** The OwnerRepExecutive who verifies a closeout item must not be the operator recorded as that item's `submitted_by_user_id`.

The comparison is always between the `X-User-ID` of the incoming request and the recorded actor field on the resource.

### 2.10. Path and Cross-Program Reference Resolution

This API uses a flat topology: every collection is mounted at the top level, and resources address one another through body-supplied identifiers rather than nested paths. When an endpoint path carries an `{id}` parameter, the referenced resource must exist; when a request body carries foreign-key identifiers (for example a `program_id`, `contract_id`, or `stakeholder_group_id`), each referenced resource must likewise exist. Existence failures surface the resource-specific 404 for the first identifier that cannot be resolved: `ERR_PROGRAM_NOT_FOUND`, `ERR_CHARTER_NOT_FOUND`, `ERR_BASELINE_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_CHANGE_ORDER_NOT_FOUND`, `ERR_RISK_ENTRY_NOT_FOUND`, `ERR_DRAWDOWN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_STAKEHOLDER_GROUP_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_OCCUPANCY_PLAN_NOT_FOUND`, `ERR_WAVE_NOT_FOUND`, or `ERR_CLOSEOUT_ITEM_NOT_FOUND`.

Body-supplied references must additionally be **co-resident in the same program** as the resource they attach to. A move-in wave whose `stakeholder_group_id` belongs to a different program than the occupancy plan's program is rejected with `ERR_CROSS_PROGRAM_REFERENCE` (409), as is any analogous cross-program linkage. Several child resources never take a `program_id` from the client at all: a change order derives its `program_id` from its contract, an engagement derives its `program_id` from its stakeholder group, and a move-in wave derives its `program_id` from its occupancy plan.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program: Charters, Baselines, and Activation

An OwnerRepPM opens an engagement by creating a **Program** with a `program_name` and an `owner_organization`. A new program is born in `CHARTERING` status with an empty financial posture: all four pool counters are 0, `contingency_posture` is `CRITICAL` (a zero-total pool is critical by definition, per §2.7), `current_budget_cents` is null until the first baseline approval lands, and `approved_charter_id`, `approved_baseline_id`, `baseline_version_no`, and `target_finish_date` are all null.

The **Charter** is the program's founding mandate. An OwnerRepPM drafts one by supplying the `program_id` together with `objectives` and a `scope_statement`; the program must be in `CHARTERING` or `ACTIVE` at creation time. Each charter receives a `version_no` that increases monotonically per program, starting at 1 — a newly created charter takes the highest existing charter version for that program plus one. A charter starts in `DRAFT`. Submission by an OwnerRepPM moves it `DRAFT → SUBMITTED`, records the acting operator in `submitted_by_user_id`, and — because submission is a program-relevant event — increments the parent `Program.version` by 1. Submission is only possible while the program is `CHARTERING` or `ACTIVE`; otherwise the request is rejected with `ERR_INVALID_TRANSITION`.

The Owner then decides the submitted charter. The decision payload carries `decision` (either APPROVE or RETURN), the OCC token `expected_program_version` governed by §2.6, and — for a return — a `return_note`. A stale `expected_program_version` is rejected with `ERR_STALE_PROGRAM_VERSION` (412) before anything else about the decision is applied. On APPROVE, the charter moves `SUBMITTED → APPROVED`; any previously `APPROVED` charter of the same program is automatically moved to `SUPERSEDED` by the system; the program's `approved_charter_id` is set to this charter's id; the Owner's identity is recorded in `decided_by_user_id`; and `Program.version` increments by 1. On RETURN, the charter moves `SUBMITTED → RETURNED`, the supplied note is recorded in `return_note`, `decided_by_user_id` is set, and `Program.version` increments by 1. A returned charter is not dead: an OwnerRepPM may revise it, moving `RETURNED → DRAFT` while replacing `objectives` and `scope_statement` with any values present in the revision payload, again incrementing `Program.version` by 1. The supersession transition `APPROVED → SUPERSEDED` is system-driven only — it fires automatically when another charter of the same program is approved, never through a direct client action.

The **Baseline** follows the same editorial rhythm but carries the program's money and schedule. Creation takes `program_id`, `total_budget_cents` (the total owner budget, integer cents, strictly greater than 0), `contingency_total_cents` (the contingency carve-out, integer cents, at least 0 and no more than the total budget), `target_finish_date` in `YYYY-MM-DD` form, and `lines` — the cost-code breakdown, an array of entries each pairing a `cost_code` string with a strictly positive integer `amount_cents`, where every `cost_code` is unique within the baseline and the line amounts must sum exactly to `total_budget_cents`. Malformed payloads in any of these respects fail at pipeline step 3 with `ERR_INVALID_REQUEST`. A baseline's `version_no` likewise starts at 1 and increases monotonically per program, and its lifecycle mirrors the charter's: `DRAFT → SUBMITTED` on submission (recording `submitted_by_user_id`, incrementing `Program.version`, and requiring the program to be `CHARTERING` or `ACTIVE`), an Owner decision on a submitted baseline with the same `expected_program_version` OCC discipline and the same RETURN path recording `return_note`, and revision moving `RETURNED → DRAFT` while replacing `total_budget_cents`, `contingency_total_cents`, `target_finish_date`, and `lines` with any values present in the payload.

Baseline **approval** is heavier than charter approval, because it rewrites the program's financial foundation. Beyond the OCC check, approval enforces one fiscal guard: the incoming `contingency_total_cents` must be at least the sum of the program's currently outstanding `contingency_reserved_cents` plus `contingency_committed_cents` plus `contingency_drawn_cents`; a rebaseline that would undercut those standing commitments is rejected with `ERR_BASELINE_UNDERCUTS_COMMITMENTS` (HTTP 402). On APPROVE, the previously `APPROVED` baseline (if any) moves to `SUPERSEDED`; the program's `approved_baseline_id` and `baseline_version_no` are set from this baseline; `current_budget_cents` becomes the baseline's `total_budget_cents`, `contingency_total_cents` becomes the baseline's carve-out, and `target_finish_date` becomes the baseline's date; the contingency pool is then recomputed per §2.7 (available, then posture); every OwnerReport still in `DRAFT` for this program has its forecast fields recomputed (§3.6); and `decided_by_user_id` is recorded while `Program.version` increments by 1.

Activation is the program's first irreversible-feeling step: an OwnerRepPM moves the program `CHARTERING → ACTIVE`, which requires that an `APPROVED` charter exists for the program (else `ERR_NO_APPROVED_CHARTER`, 409) and that an `APPROVED` baseline exists (else `ERR_NO_APPROVED_BASELINE`, 409). Only an `ACTIVE` program admits contracts, risk entries, stakeholder groups, and owner reports; attempts to create those against a non-`ACTIVE` program are rejected with `ERR_PROGRAM_NOT_ACTIVE`.

### 3.2. Procurement: Solicitation, Negotiation, and Contract Execution

Once the program is `ACTIVE`, an OwnerRepPM solicits vendors by creating a **Contract** with `program_id`, `vendor_name`, a `contract_type` of either `CONSULTANT` or `CONTRACTOR`, and a `solicitation_estimate_cents` pre-award estimate in strictly positive integer cents. A new contract starts in `SOLICITED`.

Negotiation is a person-attributed loop. Beginning negotiation moves the contract `SOLICITED → UNDER_NEGOTIATION` and captures the acting operator in `negotiator_user_id`. Each counter move records a round: from `UNDER_NEGOTIATION → COUNTERED` or from `COUNTERED → UNDER_NEGOTIATION`, with the payload's `counter_amount_cents` replacing `latest_counter_amount_cents` (null until the first counter) and `negotiation_rounds` (starting at 0) incrementing by 1 on every counter.

Execution is deliberately taken out of the negotiator's hands. An OwnerRepExecutive executes a contract from either `UNDER_NEGOTIATION → EXECUTED` or `COUNTERED → EXECUTED`, supplying the `awarded_amount_cents`. Two checks guard this step, in pipeline order: the segregation check requires the executor's `X-User-ID` to differ from the recorded `negotiator_user_id` (else `ERR_SEGREGATION_OF_DUTIES`, 403), and the fiscal check requires the award to fit within the program's uncommitted budget — `awarded_amount_cents` may not exceed `current_budget_cents` minus the sum of `current_commitment_cents` over the program's already-`EXECUTED` contracts (else `ERR_AWARD_EXCEEDS_BUDGET`, 402). On execution, `awarded_amount_cents` is recorded, `current_commitment_cents` is initialized to the awarded amount, and `executed_by_user_id` captures the executing executive.

A contract's `current_commitment_cents` — null until execution — thereafter follows a conserved rollup: it equals the `awarded_amount_cents` plus the sum of `amount_cents` over the contract's `APPROVED` change orders, minus the sum of `amount_cents` over its `VOID` change orders. Because a voided change order was necessarily approved first, each approve/void pair nets to zero, and an approval followed by its void leaves the commitment unchanged.

An OwnerRepPM finally moves a contract `EXECUTED → COMPLETED`, which is only possible when the contract has no open change orders — zero change orders in `DRAFT`, `UNDER_REVIEW`, `RECOMMEND_APPROVAL`, `RECOMMEND_REJECTION`, or `APPROVED` — otherwise the completion is rejected with `ERR_OPEN_CHANGE_ORDERS_EXIST`.

### 3.3. Change Orders: Review, Recommendation, and the Approval Cascade

A **ChangeOrder** modifies an executed contract. An OwnerRepPM creates one in `DRAFT` against a payload containing the `contract_id`, a `title`, a `reason`, and an `amount_cents` in strictly positive integer cents; the change order's `program_id` is derived from the contract, never supplied by the client. The payload may also carry an optional `supersedes_id` naming a predecessor change order this one replaces: the predecessor must currently be `UNDER_REVIEW` on the same contract, otherwise creation is rejected with `ERR_SUPERSEDES_TARGET_INVALID` (409). When a valid `supersedes_id` is given, the predecessor is automatically moved `UNDER_REVIEW → REJECTED` by the system at creation time, and the predecessor's `superseded_by_id` is set to the new change order's id — building a self-referential revision chain clients can walk in either direction through the `supersedes_id` and `superseded_by_id` list filters.

Submission moves a change order `DRAFT → UNDER_REVIEW` and enforces two state gates: the contract must be `EXECUTED` (else `ERR_CONTRACT_NOT_EXECUTED`, 409), and the program's `contingency_posture` must not be `CRITICAL` (else `ERR_CONTINGENCY_POSTURE_CRITICAL`, 409) — a program whose contingency is nearly exhausted does not accept new change business. Under review, an OwnerRepPM may send the change order back `UNDER_REVIEW → DRAFT` with a request-revision whose payload `revision_note` is recorded on the change order, supporting a reject-rework loop before any recommendation exists.

From `UNDER_REVIEW`, an OwnerRepPM records a formal recommendation. The payload carries `recommendation` — APPROVE moving the change order `UNDER_REVIEW → RECOMMEND_APPROVAL`, REJECT moving it `UNDER_REVIEW → RECOMMEND_REJECTION` — along with an `analysis_note` capturing the supporting rationale; either way, `recommended_by_user_id` records the recommending project manager.

The Owner decides from **either** recommendation state. All four decision paths share the segregation check at priority 6: the decider's `X-User-ID` must differ from `recommended_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`, 403). A decision to REJECT moves the change order `RECOMMEND_APPROVAL → REJECTED` or `RECOMMEND_REJECTION → REJECTED`, recording `decided_by_user_id`. A decision to APPROVE — whether from `RECOMMEND_APPROVAL → APPROVED` or as an owner override from `RECOMMEND_REJECTION → APPROVED` — additionally requires `amount_cents` to fit within `contingency_available_cents` (else `ERR_CONTINGENCY_EXCEEDED`, 402), and then runs a **four-link approval cascade**:

1. The contract's `current_commitment_cents` increases by the change order's `amount_cents`.
2. Triggered by link 1, the system auto-creates a ContingencyDrawdown whose `source` is `CHANGE_ORDER`, whose `change_order_id` is this change order, whose `amount_cents` equals the change order's amount, and whose initial status is `COMMITTED`; the new drawdown's id is written back to the change order's `linked_drawdown_id`.
3. Triggered by link 2's committed draw, the program pool moves: `contingency_committed_cents` increases by the amount, `contingency_available_cents` decreases by the amount, and `contingency_posture` is recomputed per §2.7.
4. Triggered by link 3's pool and posture change, the forecast fields of every OwnerReport in `DRAFT` for this program are recomputed (reports in `RETURNED` are **not** refreshed, and `SUBMITTED` or `ACCEPTED` reports remain frozen per §3.6).

Approval also computes the change order's `allocated_lines` — empty until approval — distributing `amount_cents` across the currently approved baseline's `lines` as an array of entries pairing each `cost_code` with an `allocated_cents` figure. The distribution is a waterfall with a pinned rounding order. Each baseline line's exact rational share is the change amount multiplied by that line's baseline amount and divided by the sum of all baseline line amounts. Each exact share is then rounded half-up to a whole cent — **per-line rounding happens first**. If the rounded shares do not sum to the change amount, the residual difference is assigned to a single line, chosen deterministically: when the residual is positive it goes to the line whose exact share has the largest fractional part; when negative, to the line whose exact share has the smallest fractional part; ties are broken by `cost_code` in ascending lexicographic order, never by id. Summing the partial allocations first and rounding once at the end is a different, forbidden order.

The Owner may also void an approved change order, moving `APPROVED → VOID` with a `void_reason` recorded on the change order. Voiding runs the mirror-image **compensation cascade**: the contract's `current_commitment_cents` decreases by the amount; the linked drawdown (found via `linked_drawdown_id`) moves to `RELEASED`; the pool releases it — `contingency_committed_cents` decreases by the amount, `contingency_available_cents` increases by the amount, and posture is recomputed; and the forecast fields of every `DRAFT` OwnerReport for the program are recomputed once more.

### 3.4. The Risk Register and the Escalation Threshold

An OwnerRepPM maintains the program's risk register by creating **RiskEntry** records — allowed only while the program is `ACTIVE` — with `program_id`, a `title`, a `category` of `SCHEDULE`, `COST`, `SCOPE`, `STAKEHOLDER`, or `SITE`, a `probability_pct` from 1 to 100, and an `impact_cents` of at least 0. The entry is born `IDENTIFIED`, and its `exposure_cents` is computed immediately — and recomputed on every subsequent assessment — as `probability_pct` multiplied by `impact_cents`, divided by 100, rounded half-up to whole cents.

Assessment is threshold-driven against a fixed escalation line of **$500,000.00 (50,000,000 cents)**. An OwnerRepPM assesses with new `probability_pct` and `impact_cents` values; the entry stores them, recomputes `exposure_cents`, and lands according to both the recomputed exposure and the entry's current state:

- From `IDENTIFIED`: exposure at or above the threshold lands `ESCALATED`; below it lands `ASSESSED`.
- From `ASSESSED`: exposure at or above the threshold moves to `ESCALATED`; below it the entry stays `ASSESSED` (a self-loop recompute).
- From `MONITORING`: exposure at or above the threshold moves back to `ESCALATED`; below it the entry stays `MONITORING` (a self-loop recompute).
- From `ESCALATED`: exposure at or above the threshold keeps the entry `ESCALATED` (a self-loop recompute); exposure dropping below the threshold **de-escalates** to `MONITORING`.

Mitigation and monitoring form the management loop: from `ASSESSED` or `ESCALATED`, an OwnerRepPM may begin mitigation, moving the entry to `MITIGATING` and recording the payload's `mitigation_plan` (null until mitigation is first reached); from `MITIGATING`, the entry moves to `MONITORING`. Closure is available from `ASSESSED`, `MITIGATING`, or `MONITORING`, moving the entry to `CLOSED` with no further effect.

Realization is the register's fiscal event. From `ESCALATED` or `MONITORING`, an OwnerRepPM may realize the risk by supplying `actual_loss_cents`; the loss must fit within `contingency_available_cents` (else `ERR_CONTINGENCY_EXCEEDED`, 402). Realization moves the entry to `REALIZED` and runs a three-link cascade: first, `realized_loss_cents` records the actual loss and the system auto-creates a ContingencyDrawdown whose `source` is `RISK_REALIZATION`, whose `risk_entry_id` is this entry, whose `amount_cents` equals the actual loss, and whose initial status is `COMMITTED`, writing the new drawdown's id to the entry's `linked_drawdown_id`; second, that committed draw moves the pool — `contingency_committed_cents` increases by the loss, `contingency_available_cents` decreases by the loss, and posture is recomputed; third, the forecast fields of every `DRAFT` OwnerReport for the program are recomputed (again, `RETURNED` reports are not refreshed). `REALIZED` and `CLOSED` are terminal.

### 3.5. Contingency Drawdowns: Reserve, Commit, Draw, Release

Beyond the system-created draws of §3.3 and §3.4, an OwnerRepPM may **manually reserve** contingency by creating a ContingencyDrawdown with `program_id`, a `purpose` note, and an `amount_cents` in strictly positive integer cents. A manual drawdown is created in `RESERVED` with `source` equal to `MANUAL_RESERVE`. The requested amount must not exceed `contingency_available_cents` — equality is allowed, so an exact drain of the pool to zero succeeds — otherwise creation is rejected with `ERR_CONTINGENCY_EXCEEDED` (402). Creation immediately moves the pool (reserved up, available down by the amount), recomputes posture, and refreshes every `DRAFT` OwnerReport for the program.

A drawdown then walks a one-way lifecycle, each step a pool movement with posture recompute and a `DRAFT`-report refresh:

- **Commit** moves `RESERVED → COMMITTED`: `contingency_reserved_cents` decreases and `contingency_committed_cents` increases by the amount.
- **Draw** moves `COMMITTED → DRAWN`: `contingency_committed_cents` decreases and `contingency_drawn_cents` increases by the amount.
- **Release** moves `RESERVED → RELEASED` or `COMMITTED → RELEASED`: the source bucket (reserved or committed, respectively) decreases and `contingency_available_cents` increases by the amount. Release also fires system-side as link 2 of the change-order void compensation cascade.

`DRAWN` and `RELEASED` are terminal. System-created drawdowns — those whose `source` is `RISK_REALIZATION` or `CHANGE_ORDER` — are initialized directly in `COMMITTED` at creation, carry a system-generated `purpose` text, and link back to their origin through `risk_entry_id` or `change_order_id` respectively (null otherwise). Clients can trace any drawdown to the risk or change order it funds, and vice versa, through the `risk_entry_id`, `change_order_id`, and `linked_drawdown_id` filters.

### 3.6. The Monthly Owner Report and Cost-to-Complete Forecasting

Once per month per program, an OwnerRepPM compiles the **OwnerReport** by supplying `program_id` and a `period` in `YYYY-MM` form; the program must be `ACTIVE`. At most one report may exist for a given (`program_id`, `period`) pair — a duplicate is rejected with `ERR_DUPLICATE_REPORT_PERIOD` (409). Creation computes the report's forecast fields immediately, and the report starts in `DRAFT`.

The heart of the report is the **cost-to-complete forecast**, computed in two variants. The evaluation order is pinned to resolve the apparent circularity among pool, posture, and forecast: first the contingency pool fields are recomputed from the program's drawdowns (this pool recompute excludes all pending change orders), then `contingency_posture` is derived from that pool per §2.7, and only then are both estimate-at-completion variants computed against that posture. Both variants share three building blocks:

- **Committed work**: the sum of `current_commitment_cents` over the program's `EXECUTED` contracts.
- **Estimated work**: the sum of `solicitation_estimate_cents` over contracts in `SOLICITED`, plus the sum of `solicitation_estimate_cents` over contracts in `UNDER_NEGOTIATION`, plus the sum of `latest_counter_amount_cents` over contracts in `COUNTERED`.
- **The risk set**: entries in `ASSESSED`, `MITIGATING`, `MONITORING`, or `ESCALATED`. `IDENTIFIED` entries are excluded as unassessed; `REALIZED` and `CLOSED` entries are excluded as resolved.

The **COMMITMENT_BASED** variant — the optimistic book of record, always computed into `eac_commitment_based_cents` — is committed plus estimated plus the full, unweighted sum of `exposure_cents` across the risk set (every considered status contributes at a multiplier of 1.0), with no pending-change-order allowance and no floor.

The **TREND_BASED** variant — risk-adjusted, always computed into `eac_trend_based_cents` — weights each considered risk's `exposure_cents` by status: 1.00 for `ESCALATED`, 0.50 for `MONITORING`, 0.35 for `MITIGATING`, and 0.25 for `ASSESSED`. It then adds a pending-change-order allowance: the sum of `amount_cents` over change orders in `UNDER_REVIEW`, `RECOMMEND_APPROVAL`, or `RECOMMEND_REJECTION` (change orders still in `DRAFT` are excluded as not yet submitted), taken in full when the program's posture is `CRITICAL` and halved otherwise. The raw trend estimate is committed plus estimated plus weighted exposure plus this allowance, and the final figure is the **greater** of the raw estimate and the committed total — the estimate at completion never falls below what is already committed. Multipliers are applied in exact rational arithmetic before the final figures are rounded half-up to integer cents.

Two variances complete the forecast: `budget_variance_commitment_cents` is `current_budget_cents` minus `eac_commitment_based_cents`, and `budget_variance_trend_cents` is `current_budget_cents` minus `eac_trend_based_cents`. Each (re)computation also stamps two snapshots onto the report: `contingency_posture_snapshot`, the program's posture at that moment, and `baseline_version_no_snapshot`, the program's `baseline_version_no` at that moment (null if no baseline has ever been approved).

The report lifecycle then governs when numbers move. While `DRAFT`, the report's forecast fields are **live**: they are recomputed on every pool, posture, or commitment cascade — baseline approval, drawdown creation/commit/draw/release, change-order approval or void, and risk realization all refresh `DRAFT` reports. Reports in `RETURNED` are deliberately **not** refreshed by these cascades. Submission — moving `DRAFT → SUBMITTED`, or `RETURNED → SUBMITTED` on resubmission — first recomputes every forecast field from current program state, then **freezes** them while the report is `SUBMITTED`, recording the operator in `submitted_by_user_id`. The Owner accepts, moving `SUBMITTED → ACCEPTED`, subject to the segregation check that the accepter's `X-User-ID` differs from `submitted_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`, 403); acceptance records `accepted_by_user_id` and the `accepted_at` timestamp and permanently freezes the snapshot. Alternatively the Owner returns the report, moving `SUBMITTED → RETURNED` and recording a `return_note`, which starts a revision loop resolved by resubmission. `ACCEPTED` is terminal.

### 3.7. Stakeholder Groups and Engagement Scheduling

Coordination begins with the **StakeholderGroup**. An OwnerRepPM creates one against an `ACTIVE` program with `program_id`, a `group_name`, a `group_type` of `USER_GROUP`, `AUTHORITIES`, `COMMUNITY`, or `OPERATIONS`, and a `contact_email`.

Against a group, an OwnerRepPM plans an **EngagementItem** by supplying the `stakeholder_group_id`, a `title`, and the `scheduled_start` and `scheduled_end` instants; the item's `program_id` is derived from the group. The end must be strictly after the start, else `ERR_INVALID_REQUEST`; from them the system computes `duration_minutes` as the whole minutes between start and end. A new engagement starts `PROPOSED` — and deliberately, **no** overlap check runs at creation time.

Scheduling is where the calendar guards bite, and they run in a fixed order. Moving `PROPOSED → SCHEDULED` first enforces a **closed-interval** overlap rule against every other `SCHEDULED` engagement of the same group: touching endpoints count as overlap, so an engagement starting at the exact moment another ends still conflicts — any such collision is rejected with `ERR_ENGAGEMENT_OVERLAP` (409). Only if the interval is clear does the **daily cap** apply: summing `duration_minutes` over the group's `SCHEDULED` engagements whose `scheduled_start` falls on the same UTC calendar date as the candidate's, then adding the candidate's own `duration_minutes`, the total must not exceed **360 minutes (six hours)** per group per UTC date. The cap is inclusive — a day landing on exactly 360 minutes is allowed — and a breach is rejected with `ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED` (409).

An engagement in `SCHEDULED` is marked `HELD` once it has taken place. Cancellation moves `PROPOSED → CANCELLED` or `SCHEDULED → CANCELLED`; cancelling a scheduled engagement frees the group's calendar slot and returns its minutes to the daily-cap budget. `HELD` and `CANCELLED` are terminal.

### 3.8. Occupancy Planning and Move-In Waves

An **OccupancyPlan** organizes the physical move. An OwnerRepPM creates one — permitted while the program is `CHARTERING` or `ACTIVE` — with `program_id`, a `plan_name`, and a `target_move_month` in `YYYY-MM` form. The plan starts in `PLANNING`, moves `PLANNING → COORDINATING` as logistics begin, and supports a re-plan loop from `READY → COORDINATING` when arrangements change. Marking the plan ready moves `COORDINATING → READY`, which requires an `APPROVED` baseline to exist for the program (else `ERR_NO_APPROVED_BASELINE`, 409) and triggers computation of both readiness variants; from `READY` the plan moves `READY → EXECUTING` as moves begin, and `EXECUTING → COMPLETE` once every wave of the plan is terminal — in `COMPLETE` or `CANCELLED` — otherwise completion is rejected with `ERR_OPEN_WAVES_EXIST`.

Readiness comes in two variants, both derived from the plan's waves in `SCHEDULED`, `CONFIRMED`, or `COMPLETE` (`CANCELLED` waves are excluded), with a wave counting as done exactly when it is `COMPLETE`. The **UNWEIGHTED** variant, `readiness_unweighted_pct`, is one hundred times the number of completed considered waves divided by the number of considered waves, rounded half-up to two decimal places, and is 0.00 when no waves are considered. The **WEIGHTED** variant, `readiness_weighted_pct`, replaces counts with `criticality_weight` sums: one hundred times the total weight of completed considered waves divided by the total weight of all considered waves, likewise rounded half-up to two decimal places, and 0.00 when empty. Both variants are recomputed at mark-ready, on wave completion, and on wave cancellation.

A **MoveInWave** books a shared loading dock for one group's move. Creation takes `occupancy_plan_id`, `stakeholder_group_id`, a `wave_name`, a `dock_resource` of `DOCK_A`, `DOCK_B`, or `DOCK_C`, the `move_start` and `move_end` instants (end strictly after start, else `ERR_INVALID_REQUEST`), and a `criticality_weight` of at least 1; the wave's `program_id` is derived from the plan. Three guards apply at creation, in pipeline order: the plan must be in `COORDINATING`, `READY`, or `EXECUTING` (else `ERR_PLAN_NOT_ACCEPTING_WAVES`, 409); the stakeholder group must belong to the same program as the plan (else `ERR_CROSS_PROGRAM_REFERENCE`, 409); and the dock must be free under the occupation rule below (else `ERR_DOCK_OVERLAP`, 409). A wave is born `SCHEDULED`.

Dock occupation uses **half-open intervals with a turnover buffer**. Only waves in `SCHEDULED` or `CONFIRMED` on the same `dock_resource` within the same program occupy a dock — `COMPLETE` waves no longer occupy it, and `CANCELLED` waves are excluded entirely. Each occupying wave blocks the interval from its `move_start` up to its `move_end` extended by a **two-hour turnover buffer**, with the buffered end itself excluded. A candidate wave conflicts when its `move_start` falls before another occupying wave's buffered end while that wave's own `move_start` falls before the candidate's buffered end. The boundary is strict: a candidate starting exactly at the prior wave's buffered end is allowed, while starting one minute earlier conflicts.

Confirmation moves a wave `SCHEDULED → CONFIRMED` and re-runs two checks: the plan must be `READY` or `EXECUTING` (else `ERR_PLAN_NOT_READY`, 409), and the dock overlap rule is re-checked against the current set of occupying waves (else `ERR_DOCK_OVERLAP`). Completion moves `CONFIRMED → COMPLETE`, frees the dock interval, and recomputes the parent plan's readiness. Cancellation from `SCHEDULED` or `CONFIRMED` moves the wave to `CANCELLED`, likewise frees the dock interval, and likewise recomputes the parent plan's readiness. `COMPLETE` and `CANCELLED` are terminal.

### 3.9. Closeout, Lessons Learned, and Program Wind-Down

Wind-down begins when an OwnerRepPM moves the program `ACTIVE → CLOSING`. This gate is deliberately strict — **five** open-item families must all be empty, any violation surfacing `ERR_PROGRAM_HAS_OPEN_ITEMS` (409): zero contracts in `SOLICITED`, `UNDER_NEGOTIATION`, `COUNTERED`, or `EXECUTED`; zero change orders in `DRAFT`, `UNDER_REVIEW`, `RECOMMEND_APPROVAL`, `RECOMMEND_REJECTION`, or `APPROVED`; zero risk entries in `IDENTIFIED`, `ASSESSED`, `MITIGATING`, `MONITORING`, or `ESCALATED`; zero drawdowns in `RESERVED` or `COMMITTED`; and zero owner reports in `DRAFT`, `SUBMITTED`, or `RETURNED`. Should closing prove premature, an OwnerRepPM may reopen the program `CLOSING → ACTIVE` with no further preconditions.

Closeout evidence is tracked through **CloseoutItem** records, created by an OwnerRepPM while the program is `ACTIVE` or `CLOSING`, with `program_id`, an `item_type` of `PUNCH_LIST`, `WARRANTY`, `AS_BUILT`, `FINAL_ACCOUNT`, or `TRAINING`, and a `title`. An item starts `OPEN`; an OwnerRepPM submits evidence moving `OPEN → SUBMITTED`, recording `submitted_by_user_id`. Verification is segregated: an OwnerRepExecutive moves `SUBMITTED → VERIFIED`, but only when the verifier's `X-User-ID` differs from `submitted_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`, 403), recording `verified_by_user_id`; alternatively the executive rejects, moving `SUBMITTED → OPEN` and recording a `rejection_note` for the rework loop. `VERIFIED` is terminal.

Institutional memory is captured in **LessonEntry** records, appended by an OwnerRepPM while the program is `ACTIVE` or `CLOSING` with `program_id`, a `category` of `SCHEDULE`, `COST`, `SCOPE`, `STAKEHOLDER`, `SITE`, or `PROCUREMENT`, a `lesson_text` narrative, and a `recommendation` for future programs. Lesson entries are immutable once written — there is no update or delete — consistent with their minimal property set in §2.4.

The Owner performs the final close, moving the program `CLOSING → CLOSED`, which requires every CloseoutItem of the program to be `VERIFIED` (else `ERR_CLOSEOUT_INCOMPLETE`, 409) and at least one LessonEntry to exist for the program (else `ERR_LESSON_ENTRIES_REQUIRED`, 409). `CLOSED` is terminal for the program.

## 4. Endpoint Definitions

All collections are mounted at the top level of the API. Operations that create new resources return a `201 Created` status code; operations that modify an existing resource — including all state transitions — return `200 OK`. Every GET endpoint is callable by all three roles ("All roles" in the table below means `OwnerRepPM`, `OwnerRepExecutive`, and `Owner`). List endpoints accept the optional `limit` and `offset` pagination parameters of §2.3 plus the resource-specific filters named in their descriptions — across the surface these filters are `status`, `program_id`, `contract_id`, `supersedes_id`, `superseded_by_id`, `linked_drawdown_id`, `risk_entry_id`, `change_order_id`, `stakeholder_group_id`, `occupancy_plan_id`, `group_type`, `item_type`, `category`, and `period`. Request payloads and per-endpoint preconditions are specified in §3; the table below is a navigational summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a program (CHARTERING; pool zeroed; posture CRITICAL until baseline approval) | OwnerRepPM |
| GET | `/programs` | List programs, filterable by `status` | All roles |
| GET | `/programs/{id}` | Get one program (pool fields, posture, version) | All roles |
| POST | `/programs/{id}/activate` | Move CHARTERING → ACTIVE; requires approved charter and baseline | OwnerRepPM |
| POST | `/programs/{id}/begin-closing` | Move ACTIVE → CLOSING; zero-open-items gate | OwnerRepPM |
| POST | `/programs/{id}/close` | Move CLOSING → CLOSED; closeout and lessons gates | Owner |
| POST | `/programs/{id}/reopen` | Move CLOSING → ACTIVE | OwnerRepPM |
| POST | `/charters` | Create a DRAFT charter (per-program `version_no`) for a CHARTERING or ACTIVE program | OwnerRepPM |
| GET | `/charters` | List charters, filterable by `program_id`, `status` | All roles |
| GET | `/charters/{id}` | Get one charter | All roles |
| POST | `/charters/{id}/submit` | Move DRAFT → SUBMITTED | OwnerRepPM |
| POST | `/charters/{id}/decide` | Owner decision: APPROVE (supersedes prior approved charter) or RETURN; OCC on program version | Owner |
| POST | `/charters/{id}/revise` | Move RETURNED → DRAFT with optional field replacement | OwnerRepPM |
| POST | `/baselines` | Create a DRAFT baseline; lines must sum to the budget | OwnerRepPM |
| GET | `/baselines` | List baselines, filterable by `program_id`, `status` | All roles |
| GET | `/baselines/{id}` | Get one baseline | All roles |
| POST | `/baselines/{id}/submit` | Move DRAFT → SUBMITTED | OwnerRepPM |
| POST | `/baselines/{id}/decide` | Owner decision: APPROVE (rewrites program budget and pool, refreshes DRAFT reports) or RETURN; OCC; undercut check | Owner |
| POST | `/baselines/{id}/revise` | Move RETURNED → DRAFT with optional field replacement | OwnerRepPM |
| POST | `/contracts` | Create a contract in SOLICITED for an ACTIVE program | OwnerRepPM |
| GET | `/contracts` | List contracts, filterable by `program_id`, `status` | All roles |
| GET | `/contracts/{id}` | Get one contract | All roles |
| POST | `/contracts/{id}/begin-negotiation` | Move SOLICITED → UNDER_NEGOTIATION; captures the negotiator | OwnerRepPM |
| POST | `/contracts/{id}/counter` | Record a negotiation round (UNDER_NEGOTIATION ↔ COUNTERED); increments `negotiation_rounds` | OwnerRepPM |
| POST | `/contracts/{id}/execute` | Move to EXECUTED; segregated from negotiator; award-within-budget check | OwnerRepExecutive |
| POST | `/contracts/{id}/complete` | Move EXECUTED → COMPLETED; requires no open change orders | OwnerRepPM |
| POST | `/change-orders` | Create a DRAFT change order; optional `supersedes_id` auto-rejects an UNDER_REVIEW predecessor on the same contract | OwnerRepPM |
| GET | `/change-orders` | List change orders, filterable by `program_id`, `contract_id`, `supersedes_id`, `superseded_by_id`, `linked_drawdown_id`, `status` | All roles |
| GET | `/change-orders/{id}` | Get one change order | All roles |
| POST | `/change-orders/{id}/submit` | Move DRAFT → UNDER_REVIEW; contract must be EXECUTED; posture must not be CRITICAL | OwnerRepPM |
| POST | `/change-orders/{id}/request-revision` | Move UNDER_REVIEW → DRAFT; records `revision_note` | OwnerRepPM |
| POST | `/change-orders/{id}/recommend` | Move UNDER_REVIEW → RECOMMEND_APPROVAL or RECOMMEND_REJECTION | OwnerRepPM |
| POST | `/change-orders/{id}/decide` | Owner decision from either recommendation state; APPROVE runs the four-link cascade and computes `allocated_lines`; segregated from recommender | Owner |
| POST | `/change-orders/{id}/void` | Move APPROVED → VOID; full compensation cascade | Owner |
| POST | `/risk-entries` | Create a risk in IDENTIFIED for an ACTIVE program; `exposure_cents` computed immediately | OwnerRepPM |
| GET | `/risk-entries` | List risk entries, filterable by `program_id`, `status`, `linked_drawdown_id` | All roles |
| GET | `/risk-entries/{id}` | Get one risk entry | All roles |
| POST | `/risk-entries/{id}/assess` | Assess or re-assess; recomputes exposure; lands ASSESSED / ESCALATED / MONITORING per threshold and current state | OwnerRepPM |
| POST | `/risk-entries/{id}/mitigate` | Move ASSESSED or ESCALATED → MITIGATING; records `mitigation_plan` | OwnerRepPM |
| POST | `/risk-entries/{id}/monitor` | Move MITIGATING → MONITORING | OwnerRepPM |
| POST | `/risk-entries/{id}/realize` | Move ESCALATED or MONITORING → REALIZED; fiscal check; auto-creates a COMMITTED drawdown | OwnerRepPM |
| POST | `/risk-entries/{id}/close` | Move ASSESSED, MITIGATING, or MONITORING → CLOSED | OwnerRepPM |
| POST | `/contingency-drawdowns` | Manually reserve contingency (RESERVED, `MANUAL_RESERVE`); amount must fit available pool (equality allowed) | OwnerRepPM |
| GET | `/contingency-drawdowns` | List drawdowns, filterable by `program_id`, `risk_entry_id`, `change_order_id`, `status` | All roles |
| GET | `/contingency-drawdowns/{id}` | Get one drawdown | All roles |
| POST | `/contingency-drawdowns/{id}/commit` | Move RESERVED → COMMITTED | OwnerRepPM |
| POST | `/contingency-drawdowns/{id}/draw` | Move COMMITTED → DRAWN | OwnerRepPM |
| POST | `/contingency-drawdowns/{id}/release` | Move RESERVED or COMMITTED → RELEASED; returns amount to available | OwnerRepPM |
| POST | `/owner-reports` | Create the monthly report for a period in DRAFT; computes both EAC variants and snapshots; unique per (program, period) | OwnerRepPM |
| GET | `/owner-reports` | List owner reports, filterable by `program_id`, `status`, `period` | All roles |
| GET | `/owner-reports/{id}` | Get one owner report | All roles |
| POST | `/owner-reports/{id}/submit` | Move DRAFT or RETURNED → SUBMITTED; recomputes then freezes forecast fields | OwnerRepPM |
| POST | `/owner-reports/{id}/accept` | Move SUBMITTED → ACCEPTED; segregated from submitter; snapshot permanently frozen | Owner |
| POST | `/owner-reports/{id}/return` | Move SUBMITTED → RETURNED; records `return_note` | Owner |
| POST | `/stakeholder-groups` | Create a stakeholder group for an ACTIVE program | OwnerRepPM |
| GET | `/stakeholder-groups` | List stakeholder groups, filterable by `program_id`, `group_type` | All roles |
| GET | `/stakeholder-groups/{id}` | Get one stakeholder group | All roles |
| POST | `/engagements` | Create an engagement in PROPOSED against a group; no overlap check until scheduling | OwnerRepPM |
| GET | `/engagements` | List engagements, filterable by `program_id`, `stakeholder_group_id`, `status` | All roles |
| GET | `/engagements/{id}` | Get one engagement | All roles |
| POST | `/engagements/{id}/schedule` | Move PROPOSED → SCHEDULED; closed-interval overlap then inclusive 360-minute daily cap | OwnerRepPM |
| POST | `/engagements/{id}/complete` | Move SCHEDULED → HELD | OwnerRepPM |
| POST | `/engagements/{id}/cancel` | Move PROPOSED or SCHEDULED → CANCELLED; frees slot and daily-cap minutes | OwnerRepPM |
| POST | `/occupancy-plans` | Create an occupancy plan in PLANNING for a CHARTERING or ACTIVE program | OwnerRepPM |
| GET | `/occupancy-plans` | List occupancy plans, filterable by `program_id`, `status` | All roles |
| GET | `/occupancy-plans/{id}` | Get one occupancy plan (includes readiness scores) | All roles |
| POST | `/occupancy-plans/{id}/coordinate` | Move PLANNING → COORDINATING; also READY → COORDINATING (re-plan loop) | OwnerRepPM |
| POST | `/occupancy-plans/{id}/mark-ready` | Move COORDINATING → READY; requires an approved baseline; computes both readiness variants | OwnerRepPM |
| POST | `/occupancy-plans/{id}/execute` | Move READY → EXECUTING | OwnerRepPM |
| POST | `/occupancy-plans/{id}/complete` | Move EXECUTING → COMPLETE; all waves must be terminal | OwnerRepPM |
| POST | `/move-in-waves` | Create a wave in SCHEDULED; plan must be COORDINATING, READY, or EXECUTING; same-program group; dock overlap check | OwnerRepPM |
| GET | `/move-in-waves` | List waves, filterable by `occupancy_plan_id`, `stakeholder_group_id`, `program_id`, `status` | All roles |
| GET | `/move-in-waves/{id}` | Get one wave | All roles |
| POST | `/move-in-waves/{id}/confirm` | Move SCHEDULED → CONFIRMED; plan must be READY or EXECUTING; dock overlap re-check | OwnerRepPM |
| POST | `/move-in-waves/{id}/complete` | Move CONFIRMED → COMPLETE; frees dock; recomputes plan readiness | OwnerRepPM |
| POST | `/move-in-waves/{id}/cancel` | Move SCHEDULED or CONFIRMED → CANCELLED; frees dock; recomputes plan readiness | OwnerRepPM |
| POST | `/closeout-items` | Create a closeout item in OPEN for an ACTIVE or CLOSING program | OwnerRepPM |
| GET | `/closeout-items` | List closeout items, filterable by `program_id`, `item_type`, `status` | All roles |
| GET | `/closeout-items/{id}` | Get one closeout item | All roles |
| POST | `/closeout-items/{id}/submit` | Move OPEN → SUBMITTED | OwnerRepPM |
| POST | `/closeout-items/{id}/verify` | Move SUBMITTED → VERIFIED; segregated from submitter | OwnerRepExecutive |
| POST | `/closeout-items/{id}/reject` | Move SUBMITTED → OPEN; records `rejection_note` | OwnerRepExecutive |
| POST | `/lesson-entries` | Append an immutable lessons-learned entry for an ACTIVE or CLOSING program | OwnerRepPM |
| GET | `/lesson-entries` | List lesson entries, filterable by `program_id`, `category` | All roles |
| GET | `/lesson-entries/{id}` | Get one lesson entry (read-only) | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the canonical index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_CHARTER_NOT_FOUND` | 404 Not Found |
| `ERR_BASELINE_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_RISK_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_DRAWDOWN_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_STAKEHOLDER_GROUP_NOT_FOUND` | 404 Not Found |
| `ERR_ENGAGEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_OCCUPANCY_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_WAVE_NOT_FOUND` | 404 Not Found |
| `ERR_CLOSEOUT_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_APPROVED_CHARTER` | 409 Conflict |
| `ERR_NO_APPROVED_BASELINE` | 409 Conflict |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 Conflict |
| `ERR_OPEN_CHANGE_ORDERS_EXIST` | 409 Conflict |
| `ERR_PROGRAM_HAS_OPEN_ITEMS` | 409 Conflict |
| `ERR_CLOSEOUT_INCOMPLETE` | 409 Conflict |
| `ERR_LESSON_ENTRIES_REQUIRED` | 409 Conflict |
| `ERR_CONTINGENCY_POSTURE_CRITICAL` | 409 Conflict |
| `ERR_PLAN_NOT_READY` | 409 Conflict |
| `ERR_PLAN_NOT_ACCEPTING_WAVES` | 409 Conflict |
| `ERR_OPEN_WAVES_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_REPORT_PERIOD` | 409 Conflict |
| `ERR_CROSS_PROGRAM_REFERENCE` | 409 Conflict |
| `ERR_SUPERSEDES_TARGET_INVALID` | 409 Conflict |
| `ERR_DOCK_OVERLAP` | 409 Conflict |
| `ERR_ENGAGEMENT_OVERLAP` | 409 Conflict |
| `ERR_ENGAGEMENT_DAILY_CAP_EXCEEDED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_AWARD_EXCEEDS_BUDGET` | 402 Payment Required |
| `ERR_CONTINGENCY_EXCEEDED` | 402 Payment Required |
| `ERR_BASELINE_UNDERCUTS_COMMITMENTS` | 402 Payment Required |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |

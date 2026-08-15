# Recognition Rewards Administration API — Product Requirements Document

## 1. Introduction

Employee recognition programs sit at an awkward intersection of culture and accounting. A peer shout-out is a social gesture, yet the points attached to it are a departmental budget liability, a taxable benefit for the recipient, and — when nomination patterns go unchecked — an abuse vector. Program administrators therefore need tooling that treats all three dimensions with equal seriousness: a nomination workflow with genuine review gates, a points economy kept honest by an immutable ledger, fulfillment that respects real vendor capacity, and finance outputs that survive an audit.

This document specifies the Recognition & Rewards Program Administration API, mounted under `/api`. It covers program design (peer and manager nominations, per-nomination point caps, service-milestone tables), point budget allocation with posture-driven gating, a review workflow defended by duplicate detection and velocity limits, points-to-catalog redemption through fulfillment vendors, tax treatment of non-cash awards including employer-paid gross-up, automated service-anniversary grants, monthly budget accrual with department chargeback, participation and inclusion analytics, and abuse detection with enforcement cascades. All time-dependent behavior — nomination expiry, award expiry, budget close, anniversary scans — is driven by a controllable logical clock so that scheduled transitions are deterministic and testable.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the role under which that user acts. A request missing either header, or carrying a malformed one, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Once the caller is identified, the role is checked against the endpoint's authorization rules; a role that is not permitted — or an entity-backed identity attempting to act on another user's resource — is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Six roles exist, spelled exactly as follows: `HRAdmin`, `FinanceAdmin`, `PayrollSpecialist`, `Manager`, `Employee`, and `VendorOps`.

- An `HRAdmin` is the program administrator: owns program configuration, departments, employee registration, anniversary scans, award revocation, vendor suspension, abuse-flag adjudication, and the logical clock. When `X-User-Role` is `HRAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it (for example, as `reviewer_id` on a decided nomination, or as `raised_by` / `resolved_by` on an abuse flag) but does not compare it to any entity's `id`.
- A `FinanceAdmin` owns point budgets and the monthly accrual-and-chargeback cycle. When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is never compared to an entity's `id`.
- A `PayrollSpecialist` owns compensation synchronization and tax-year finalization. When `X-User-Role` is `PayrollSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is never compared to an entity's `id`.
- A `Manager` is a people manager and is also an employee: they nominate, and they approve, reject, or return nominations within their own reporting chain. When `X-User-Role` is `Manager`, `X-User-ID` is the `id` of the acting `Employee`; ownership checks on any resource that references an `Employee` compare the resource's foreign-key field to `X-User-ID`.
- An `Employee` is the program participant: they nominate peers, resubmit or cancel their own nominations, redeem points, and manage their own returns. When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`, with the same ownership comparison rule as for `Manager`.
- A `VendorOps` operator manages fulfillment vendors and catalog items and advances order fulfillment. When `X-User-Role` is `VendorOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it is never compared to an entity's `id`.

Segregation of duties is deliberate. The `FinanceAdmin` runs accruals but cannot touch payroll compensation or tax-year finalization; the `PayrollSpecialist` finalizes tax years but cannot create or close accrual runs; and a nomination's approver is never its nominator. All six roles may call every read endpoint.

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

List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0. List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object. Unless a more specific ordering is stated for a particular resource, list endpoints return resources sorted by `created_at` in ascending order.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` — a server-minted UUID with no type prefix — and a `created_at` timestamp. Resources additionally carry `updated_at` and a `version` integer; both timestamps are ISO 8601 UTC with three fractional digits, and `version` increments by exactly one on every mutation of the resource. The `PointLedgerEntry` is the sole exception: as an immutable journal record it carries only `id` and `created_at`; `updated_at` and `version` are absent, because a ledger entry is never modified after it is written.

### 2.5. The Logical Clock and Scheduled Transitions

The server runs on a logical clock rather than wall-clock time. At startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must never fall back to wall-clock time. An `HRAdmin`-only test-driving capability advances the clock to a caller-supplied `to_iso8601` instant and answers with the resulting `current_utc`; the clock never moves backward, and a `to_iso8601` earlier than the current logical instant is rejected with `ERR_INVALID_REQUEST`.

Each clock advance fires an ordered sweep of scheduled transitions. First, nominations whose `review_deadline` falls before the new clock time auto-expire. Second, awards whose `expires_at` is at or before the new clock time are expired. Third, budgets whose `period_end_date` has been reached by the current logical date are closed. The ordering is load-bearing: expiring nominations release their budget reservations before budget closure runs, so a budget closing in the same advance settles its `reserved_points` to zero.

### 2.6. Points, Money, and Rounding Conventions

All monetary amounts are integer cents; all point quantities are integers. Wherever a rate or percentage produces a monetary amount, the result is rounded half-up to integer cents, and where a rule specifies a single rounding, no intermediate rounding is applied to any intermediate quantity. Utilization ratios and participation rates are expressed in basis points — ten-thousandths of a whole — computed with floor division. These conventions apply uniformly to gross-up math, chargeback math, accrual math, budget posture, and analytics; the individual rules in §3 restate them where they bite.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each taking a non-optional version field that carries the caller's last observed `version` of the target resource:

- Updating a program's configuration through `PATCH /api/programs/{programId}` requires `expected_program_version`, matching the program's current `version`.
- Approving a nomination through `POST /api/nominations/{nominationId}/approve` requires `expected_nomination_version`, matching the nomination's current `version`. An approver reviews a nomination as of a particular version; if the nominator resubmits with changed content in between — a resubmission legitimately succeeds and bumps the nomination's `version` — the approval no longer covers the current content and must be refused.
- Posting an allocation adjustment through `POST /api/budgets/{budgetId}/adjustments` requires `expected_budget_version`, matching the budget's current `version`. Another adjustment, or an approval-driven commit that moved the counters and advanced the version, invalidates the pool figures the adjustment decision was made against.

In all three cases, a mismatch between the supplied version and the resource's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here do not accept a version field.

### 2.8. Request Validation Pipeline

Incoming requests are validated against an ordered pipeline; when several checks would fail, the earliest one in this order wins, and its error is the one returned. The pipeline stages are:

1. **User context.** The `X-User-ID` and `X-User-Role` headers are present and well-formed, on every endpoint (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role and ownership.** The role is permitted for the endpoint, and ownership checks of the form "an `Employee` may only act on their own resource" hold — the caller's `X-User-ID` must equal the resource's employee or nominator identifier (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence.** Every path identifier resolves to an existing entity, resolved left to right along the path — the path parameters are `programId`, `departmentId`, `employeeId`, `id` on the short-form employee routes, `budgetId`, `nominationId`, `awardId`, `vendorId`, `catalogItemId`, `redemptionOrderId`, `taxRecordId`, `accrualRunId`, `abuseFlagId`, and `anniversaryEventId` — and every body-supplied foreign key (such as `nominee_id`, `catalog_item_id`, `department_id`, `vendor_id`, `program_id`, or `budget_id`) resolves to an existing entity (`ERR_NOT_FOUND`). A reference that exists but belongs to a different program is not a 404; it surfaces later as a scope failure under stage 11.
4. **Request schema.** Required fields are present, types are valid, enum members are valid, and integers are in range — including `points_requested` being at least 1 and at most the program's `max_points_per_nomination`, redemption `quantity` between 1 and 5 inclusive (`ERR_INVALID_QUANTITY`), `period_month` between 1 and 12 inclusive, and `tax_year` between 2000 and 2100 inclusive (`ERR_INVALID_TAX_YEAR`) — on all mutating endpoints (`ERR_INVALID_REQUEST` unless a more specific error applies).
5. **State permission.** The target resource's current state permits the requested transition — approval only from `PENDING_REVIEW`, shipping only from `SUBMITTED`, reconciliation only from `OPEN`, and so on (`ERR_INVALID_STATE_TRANSITION`).
6. **Optimistic concurrency.** On the three OCC-guarded writes of §2.7, the expected version equals the parent's current `version` (`ERR_STALE_VERSION`).
7. **Program gate.** The program's `status` is `ACTIVE` for nomination submission and resubmission, redemption creation, budget creation, anniversary scans, and catalog item creation (`ERR_PROGRAM_NOT_ACTIVE`).
8. **Employee standing.** The acting employee's `program_status` is `ELIGIBLE` when nominating as a nominator or redeeming (`ERR_EMPLOYEE_SUSPENDED`).
9. **Velocity.** The nominator has filed fewer than `velocity_limit_per_7_days` nominations in the trailing seven days (`ERR_VELOCITY_LIMIT_EXCEEDED`, and an `OPEN` abuse flag is raised).
10. **Self-dealing.** The `nominee_id` differs from the nominator on submission (`ERR_SELF_NOMINATION`, HTTP 422), and the approver differs from the nominator on approval, rejection, and return-for-revision (`ERR_SELF_APPROVAL`).
11. **Referential scope.** A `PEER` nomination stays within one department; a `MANAGER` nomination comes from within the nominee's manager chain; a `Manager`-role approver sits in the nominee's chain (`ERR_NOMINEE_NOT_IN_SCOPE`); order submission and catalog item creation require an `ACTIVE` vendor (`ERR_VENDOR_SUSPENDED`). At this same stage, a conflicting `employee_ref` on employee registration and a `manager_id` that would create a reporting cycle are rejected (`ERR_INVALID_REQUEST`).
12. **Duplicates.** An `idempotency_key` replay with an identical payload returns the original record; the same key with a different payload is `ERR_IDEMPOTENCY_CONFLICT`; a business duplicate nomination is `ERR_DUPLICATE_NOMINATION`.
13. **Temporal windows.** The catalog item's availability window contains the current logical time and the item is `ACTIVE` (`ERR_CATALOG_ITEM_UNAVAILABLE`); a new budget window does not overlap an existing one for the same program and department (`ERR_BUDGET_PERIOD_OVERLAP`); a return falls within fourteen days of delivery and the item is not a gift card (`ERR_RETURN_NOT_ALLOWED`); the requested nomination type is enabled in program configuration (`ERR_NOMINATION_TYPE_DISABLED`).
14. **Inventory.** The catalog item's `inventory_quantity` is either unlimited or at least the ordered `quantity` (`ERR_ITEM_OUT_OF_STOCK`).
15. **Restricted-posture policy cap.** When the selected budget's posture is `RESTRICTED`, `points_requested` is at most 500 (`ERR_BUDGET_RESTRICTED_AMOUNT`).
16. **Budget capacity.** Reserved plus committed plus requested points fit within `allocated_points`, and a budget window containing the relevant date exists at all (`ERR_BUDGET_EXHAUSTED`, `ERR_BUDGET_NOT_FOUND`).
17. **Points balance.** The redeeming employee's `available_points` cover the order's `points_total` (`ERR_INSUFFICIENT_POINTS`).
18. **Accrual and tax integrity.** No duplicate non-`VOIDED` accrual run exists for the period (`ERR_DUPLICATE_ACCRUAL_RUN`); reconciliation requires zero variance (`ERR_ACCRUAL_VARIANCE`); tax-year finalization requires every month closed or voided (`ERR_PERIODS_NOT_CLOSED`) and a year not already finalized (`ERR_TAX_YEAR_FINALIZED`); adjustments to a `CLOSED` budget are refused (`ERR_BUDGET_CLOSED`).

### 2.9. The Points Ledger and Derived Balances

Every movement of points is recorded as an immutable `PointLedgerEntry`. Each entry names its owning `employee_id`, an `entry_type`, a signed `points` movement, a polymorphic `reference_type` with its companion `reference_id`, an `idempotency_key`, and a human-readable derivation `note`. The `entry_type` is one of `GRANT_NOMINATION`, `GRANT_ANNIVERSARY`, `GRANT_ADJUSTMENT`, `HOLD`, `SETTLE_REDEEM`, `REFUND`, `RESTOCKING_FEE`, `EXPIRY`, or `CLAWBACK`. Direction conventions are fixed: a `HOLD` moves points from available to held; `SETTLE_REDEEM` and `RESTOCKING_FEE` move points out of held into spent; `CLAWBACK` and `EXPIRY` debit available points; grants and refunds credit available points. The `reference_type` is `AWARD`, `REDEMPTION_ORDER`, or `ABUSE_FLAG`; the `reference_id` is interpreted through it and is not a formal foreign key. Grant and expiry entries reference an award; hold, settle, refund, and restocking-fee entries reference a redemption order; cascade clawback entries reference an abuse flag. An entry's `idempotency_key` is derived from the originating request's key plus the entry's role, and the pair of `employee_id` and `idempotency_key` is unique. An employee's ledger is readable as a chronological list, filterable by `entry_type`.

Employee balances are derived from this journal, never stored as independent truths. `available_points` is the spendable sum of ledger movements and may go negative when a clawback reaches points already spent; `held_points` is the points escrowed by open redemption orders; `lifetime_granted_points` is the sum of grant entries minus clawback entries; `lifetime_redeemed_points` accumulates settled redemption points, including restocking-fee points; `lifetime_expired_points` accumulates points removed by award expiry. Any operation that changes these counters also refreshes the employee's `updated_at` and `version`, and any change to `lifetime_granted_points` triggers the tier recomputation of §3.4.

## 3. Business Logic & Workflows

### 3.1. Program Design and Organizational Enrollment

A recognition program begins life in `DRAFT` status. An `HRAdmin` creates it with a display `name` and the policy knobs that govern everything downstream. `max_points_per_nomination` caps the points any single nomination may request and must be strictly positive. `peer_nomination_enabled` and `manager_nomination_enabled`, both defaulting to true, decide which nomination types the program accepts; submitting a nomination of a disabled type is rejected with `ERR_NOMINATION_TYPE_DISABLED`. `nomination_review_sla_days`, defaulting to 14, sets how many days a nomination may sit in review before it auto-expires. `duplicate_window_days`, defaulting to 30, sets the look-back window for duplicate-nomination detection. `velocity_limit_per_7_days`, defaulting to 5, caps how many nominations one nominator may file in any trailing seven-day window. Three further configuration families are introduced where they bite: `point_cost_rate_cents` — the budgetary cents per point, strictly positive and possibly fractional, for example half a cent per point — drives chargeback and accrual math in §3.2 and §3.7; `state_rate_map` and `grossup_enabled` — the latter defaulting to false — drive tax treatment in §3.6; `anniversary_milestones`, defaulting to an empty table, drives service awards in §3.4; and `accrual_method`, defaulting to `STRAIGHT_LINE`, together with `fiscal_year_start_month` drives monthly accruals in §3.7.

Activation moves a program from `DRAFT` to `ACTIVE`, or back from `SUSPENDED` to `ACTIVE`, and is rejected with `ERR_INVALID_STATE_TRANSITION` from any other status. Activation from `DRAFT` is also guarded: the program must carry at least one `anniversary_milestones` entry or at least one enabled nomination mode, otherwise the activation is rejected with `ERR_INVALID_REQUEST`. Each activation or suspension increments the program's `version` by one. Suspending a program moves it from `ACTIVE` to `SUSPENDED`; while suspended — and equally while still in `DRAFT` — the program gate of §2.8 rejects nomination submission and resubmission, redemption creation, budget creation, anniversary scans, and catalog item creation with `ERR_PROGRAM_NOT_ACTIVE`.

Closing a program is deliberately unglamorous: there is no dedicated close action. Instead, an `HRAdmin` updates the program's configuration with `status` set to `CLOSED`, and the update endpoint enforces the close guards — no nomination of this program may remain in `PENDING_REVIEW` or `RETURNED_FOR_REVISION`, and no redemption order may remain with `fulfillment_status` of `PENDING_SUBMISSION`, `SUBMITTED`, `SHIPPED`, or `RETURN_REQUESTED`; violating either guard is `ERR_INVALID_STATE_TRANSITION`. `CLOSED` is terminal. Like every configuration update, the close travels under the optimistic-concurrency rule of §2.7.

Departments are registered by an `HRAdmin` with a `name` and a `chargeback_account_code`, the general-ledger account to which the department's monthly chargeback entries are attributed (§3.7).

Employees are registered by an `HRAdmin` with a unique external `employee_ref` (a conflict is `ERR_INVALID_REQUEST`), a `full_name`, a home `department_id` used for budget and chargeback attribution, a nullable `manager_id` pointing at another employee, a `hire_date` in year-month-day form that drives anniversary milestones, and a two-letter `state_code` used for supplemental state tax lookup. The `manager_id` must not equal the employee's own `id` and must not create a cycle in the reporting chain; either violation is rejected with `ERR_INVALID_REQUEST`. A newly registered employee starts with `program_status` `ELIGIBLE`, `recognition_tier` `BRONZE`, zero `available_points`, `held_points`, `lifetime_granted_points`, `lifetime_redeemed_points`, and `lifetime_expired_points`, and zero year-to-date tax accumulators. The employee roster can be listed with `department_id`, `manager_id`, and `program_status` filters.

### 3.2. Funding the Program: Budgets, Posture, and Adjustments

Before a single point can be granted, a `FinanceAdmin` funds the program by creating point budgets. A budget names its `program_id` and `department_id`, a half-open window from `period_start_date` (inclusive) to `period_end_date` (exclusive, and strictly later than the start), and a strictly positive `allocated_points` pool. Windows for the same program-and-department pair must not overlap: any intersection is rejected with `ERR_BUDGET_PERIOD_OVERLAP`, though pure adjacency — one window starting exactly where another ends — is allowed. A fresh budget starts with `reserved_points` and `committed_points` at zero and `posture` `OPEN`. The budget list can be filtered by `program_id`, `department_id`, and `posture`.

The `reserved_points` counter holds points locked by non-terminal nominations — those in `PENDING_REVIEW` or `RETURNED_FOR_REVISION` — while `committed_points` accumulates points granted through approved awards, net of revocations and expiries. From these counters the budget derives its `posture`, a stored column recomputed after every mutation of `reserved_points`, `committed_points`, or `allocated_points`, and on clock advance. Utilization is computed in basis points: ten thousand times the sum of `reserved_points` and `committed_points`, divided by `allocated_points`, with floor division. When the current logical date has reached `period_end_date`, the budget is `CLOSED` — terminal, and winning over any utilization reading. Otherwise, utilization at or above 10000 basis points makes the budget `EXHAUSTED`; at or above 8500 basis points, `RESTRICTED`; below that, `OPEN`. Boundaries are inclusive: exactly 85.00 percent utilization is `RESTRICTED`, and exactly 100.00 percent is `EXHAUSTED`.

Posture gates nomination submission without altering the stored counters. While `RESTRICTED`, a nomination may request at most 500 points; while `EXHAUSTED`, every new submission against the budget is rejected with `ERR_BUDGET_EXHAUSTED`. Posture moves freely in both directions as counters change: rejections, cancellations, and expiries release reservations and can walk a budget from `EXHAUSTED` back through `RESTRICTED` to `OPEN`, and an allocation increase can do the same in one step.

A `FinanceAdmin` adjusts a live budget by posting a signed `delta_allocated_points` together with a free-text `reason`. The adjustment adds the delta to `allocated_points`; the result must remain strictly positive and at least as large as the sum of `reserved_points` and `committed_points`, otherwise the adjustment is rejected with `ERR_INVALID_REQUEST`. Adjustments against a `CLOSED` budget are rejected with `ERR_BUDGET_CLOSED`. Every adjustment recomputes posture and increments the budget's `version` — and because adjustments ride the optimistic-concurrency rule of §2.7, a request carrying a stale `expected_budget_version` is refused with `ERR_STALE_VERSION` rather than silently overwriting pool figures the caller never observed.

When the logical clock reaches a budget's `period_end_date`, the auto-close runs — always after the nomination auto-expiry step of the same sweep, so expiring nominations release their reservations first. The closing budget's `reserved_points` settles to zero, its `version` increments by one, and from then on any nomination or grant whose selector would have picked this window receives `ERR_BUDGET_NOT_FOUND`, because the window no longer contains the current date.

### 3.3. The Nomination Lifecycle

Any `Employee` or `Manager` may submit a nomination, provided the acting employee is `ELIGIBLE` — a `SUSPENDED` nominator is refused with `ERR_EMPLOYEE_SUSPENDED`. The submission names the `program_id`, the `nominee_id`, the nomination `type` (`PEER` or `MANAGER`), the `points_requested` (at least 1 and at most the program's `max_points_per_nomination`), a `reason_code` drawn from `TEAMWORK`, `INNOVATION`, `CUSTOMER_SAVE`, `DELIVERY`, `MENTORSHIP`, or `OTHER`, a free-text justification `message`, and a client-supplied `idempotency_key` unique per nominator. The server records the submitter as `nominator_id`, taken from the caller's `X-User-ID`.

At submission the server selects the nomination's budget: the point budget belonging to the chosen program and to the nominee's home department whose half-open window contains the submission date, and records it as `budget_id`. When no such budget exists — or the only match is already `CLOSED` — the submission fails with `ERR_BUDGET_NOT_FOUND`. The selected budget then applies its two-stage gate, in order. First the posture policy cap: if the budget's posture is `RESTRICTED` and `points_requested` exceeds 500, the submission is rejected with `ERR_BUDGET_RESTRICTED_AMOUNT`. Second the capacity check: the sum of `reserved_points`, `committed_points`, and `points_requested` must not exceed `allocated_points` — a sum landing exactly on `allocated_points` is accepted, anything larger is rejected with `ERR_BUDGET_EXHAUSTED`. On success the submission reserves its points: `reserved_points` grows by `points_requested`, posture is recomputed, and the nomination lands in `PENDING_REVIEW` with a `review_deadline` of the submission instant plus the program's `nomination_review_sla_days`.

Scope and conduct rules run alongside the budget gate. A `PEER` nomination requires the nominee's `department_id` to equal the nominator's; a `MANAGER` nomination requires the nominator to appear in the nominee's manager chain, walking `manager_id` transitively upward; either violation is `ERR_NOMINEE_NOT_IN_SCOPE`. Nominating oneself — `nominee_id` equal to the caller — is rejected with `ERR_SELF_NOMINATION` (HTTP 422).

Two duplicate defenses apply. The idempotency defense is exact: a replay with the same nominator, the same `idempotency_key`, and an identical payload returns the original nomination with HTTP 201 and creates no new row, while the same key with a different payload is rejected with `ERR_IDEMPOTENCY_CONFLICT`. The business defense is fuzzier in intent but exact in rule: a nomination with the same nominator, the same nominee, and the same `reason_code` as an existing non-terminal nomination created within the program's `duplicate_window_days` is rejected with `ERR_DUPLICATE_NOMINATION`.

Velocity is enforced per nominator over a trailing seven-day window whose lower bound is inclusive: nominations created at or after the instant seven days before now are counted, in any status except `CANCELLED`. When the count already equals the program's `velocity_limit_per_7_days`, the next submission is rejected with `ERR_VELOCITY_LIMIT_EXCEEDED` and the system raises an `OPEN` abuse flag with `rule_code` `VELOCITY_EXCEEDED` — so the fifth submission under a default limit of 5 succeeds, and the sixth is rejected and flagged.

Review decisions belong to a `Manager` or an `HRAdmin`, with one asymmetry: a `Manager` approver must sit in the nominee's manager chain (`ERR_NOMINEE_NOT_IN_SCOPE` otherwise), while an `HRAdmin` is never scope-limited. Whatever the role, the approver must not be the nominator; self-approval on approval, rejection, or return-for-revision is `ERR_SELF_APPROVAL`. Every decision stamps `decided_at` with the logical timestamp and `reviewer_id` with the deciding manager's employee id — or the opaque `HRAdmin` identifier when an administrator decides — and increments the nomination's `version`.

Approval is the heaviest transition in the system, and it rides the optimistic-concurrency rule of §2.7: the request must carry `expected_nomination_version`, and a mismatch with the nomination's current `version` is `ERR_STALE_VERSION`. On success the nomination moves from `PENDING_REVIEW` to `APPROVED` and the server, in one logical step: creates an `Award` with `source` `NOMINATION`, `points` equal to `points_requested`, `employee_id` equal to the nominee, `nomination_id` pointing back at the nomination, `granted_at` at the current logical instant, `expires_at` twelve months later, and `points_remaining` equal to the granted points, then writes the award's id into the nomination's `award_id`; writes a `GRANT_NOMINATION` ledger entry crediting the nominee; moves the budget's `reserved_points` down and its `committed_points` up by `points_requested` and recomputes posture; and recomputes the nominee's `available_points`, `lifetime_granted_points`, and `recognition_tier` — a cascade that may promote the nominee through the tiers of §3.4.

Rejection moves a `PENDING_REVIEW` nomination to `REJECTED`, optionally carrying a free-text `reason`, and releases the reservation: the budget's `reserved_points` drops by `points_requested` and posture is recomputed. No award is created and no points move.

Returning a nomination for revision is a dual-outcome action that always answers HTTP 200. A nomination's `revision_count` starts at zero; while it is below 2, the return succeeds as a revision: the nomination moves to `RETURNED_FOR_REVISION`, `revision_count` increments by one, the request carries a `feedback` note for the nominator, and `review_deadline` resets to the current instant plus the review SLA. When `revision_count` is already 2, the same action auto-rejects instead: the nomination lands in `REJECTED`, `revision_count` stays at 2, the budget reservation is released with posture recomputed, and the response returns the rejected nomination — the third return is an outcome, not an error.

Resubmission belongs to the original nominator alone; anyone else is refused with `ERR_FORBIDDEN_FOR_ROLE`. A resubmission from `RETURNED_FOR_REVISION` moves the nomination back to `PENDING_REVIEW`, optionally changing `points_requested` or the `message`. When `points_requested` changes, the budget gate of submission reruns against the nomination's budget — the `RESTRICTED` cap first, then prospective capacity — failing with `ERR_BUDGET_RESTRICTED_AMOUNT` or `ERR_BUDGET_EXHAUSTED` (or `ERR_BUDGET_NOT_FOUND` when the window no longer applies) and releasing nothing on failure; on success the budget's `reserved_points` adjusts by the difference between the new and old amounts and posture is recomputed. Either way the `review_deadline` resets, and the nomination's `version` increments — which is exactly what invalidates an approver's previously observed `expected_nomination_version`.

Cancellation releases the reservation in the same way and may start from either `PENDING_REVIEW` or `RETURNED_FOR_REVISION`, but only the nominator may cancel. Finally, nominations that outlive their `review_deadline` — whether still `PENDING_REVIEW` or sitting `RETURNED_FOR_REVISION` — are moved to `EXPIRED` by the first step of the clock-advance sweep, releasing the reservation and recomputing posture. `APPROVED`, `REJECTED`, `CANCELLED`, and `EXPIRED` are terminal; the revision loop `PENDING_REVIEW` to `RETURNED_FOR_REVISION` and back is the only cycle, bounded at two returns. The nomination list can be filtered by `program_id`, `nominator_id`, `nominee_id`, `status`, `budget_id`, `award_id`, and `reviewer_id`.

### 3.4. Awards, Service Milestones, and Recognition Tiers

An `Award` is a dated bundle of granted points. Beyond its `program_id` and recipient `employee_id`, it records its `source` — `NOMINATION`, `ANNIVERSARY`, or `ADJUSTMENT` — a nullable `nomination_id` that stays empty for anniversary and adjustment grants, the granted `points`, the `points_remaining` still unspent and unexpired, a `granted_at` logical timestamp that drives both spending order and expiry, an `expires_at` exactly twelve months after the grant, and a nullable `revoked_by_flag_id` that names the abuse flag responsible when a revocation came from a confirmed flag. An award is `ACTIVE` on creation and ends its life `FULLY_REDEEMED`, `EXPIRED`, or `REVOKED`. The award list can be filtered by `employee_id`, `program_id`, `nomination_id`, `source`, `status`, and `revoked_by_flag_id`.

Spending consumes awards first-in-first-out. When a redemption settles, the employee's `ACTIVE` awards are consumed in `granted_at` ascending order, ties broken by `created_at` ascending — UUID `id` values are never used for ordering — taking up to each award's `points_remaining` until the order's `points_total` is satisfied; an award drained to zero becomes `FULLY_REDEEMED`. The expiry sweep of the clock advance walks the same order: each `ACTIVE` award whose `expires_at` is at or before the new clock time is expired, writing an `EXPIRY` ledger entry that debits `points_remaining` from `available_points` and adds it to `lifetime_expired_points`, releasing the same amount from the committed counter of the budget whose window contains the award's `granted_at` for the employee's department whenever that budget is not `CLOSED`, recomputing that budget's posture, and zeroing `points_remaining`. Determinism is a requirement: the same ledger history at the same logical clock always yields the same per-award remainders.

Revocation is the punitive sibling of expiry. An `HRAdmin` may revoke an `ACTIVE` award — optionally with a `reason` — and a confirmed abuse flag does the same by cascade (§3.8). Revocation writes a `CLAWBACK` ledger entry debiting the award's full `points_remaining` from `available_points`, which may drive the balance negative when some of the grant was already spent; releases the same amount from the originating budget's `committed_points` when that budget is not `CLOSED`, recomputing posture; recomputes the employee's `lifetime_granted_points` and `recognition_tier`, possibly demoting the tier; zeroes `points_remaining`; and stamps `revoked_by_flag_id` when the cascade drove it. Attempting to revoke an award that is not `ACTIVE` is `ERR_INVALID_STATE_TRANSITION`.

An `HRAdmin` may also grant points directly through a points adjustment, supplying `program_id`, `points`, and a `reason`. The adjustment creates an `Award` with `source` `ADJUSTMENT` and a null `nomination_id`, granted at the current instant and expiring twelve months later, writes a `GRANT_ADJUSTMENT` ledger entry, charges the budget selected exactly as a nomination would be — the employee's department budget whose window contains today, with `ERR_BUDGET_NOT_FOUND` and `ERR_BUDGET_EXHAUSTED` guarding as usual — by raising its `committed_points`, and recomputes the recipient's tier.

Service anniversaries automate the same machinery. An `HRAdmin` triggers an anniversary scan against the logical clock's current date — only for an `ACTIVE` program, per the program gate. The scan considers every employee whose department holds any budget in the program, any window and any posture, and matches anniversaries by the month and day of `hire_date` against the scan date, with February 29 hires observed on February 28 in non-leap years; the service years reached are the scan year minus the hire year. For each employee the scan evaluates, in this order: if an `AnniversaryEvent` already exists for the same program, employee, and `milestone_years`, the scan records `SKIPPED_DUPLICATE`; otherwise, if the employee is `SUSPENDED`, it records `SKIPPED_INELIGIBLE`; otherwise, if no row of the program's `anniversary_milestones` table — each row pairing a `years` integer with a `points` integer — matches the years reached, it records `SKIPPED_NO_MILESTONE`; otherwise, if the budget gate used for nominations, evaluated at the scan date, has no room for the milestone points, it records `SKIPPED_BUDGET_EXHAUSTED`; otherwise it records `PROCESSED`, creating an `Award` with `source` `ANNIVERSARY` and the milestone's points, writing a `GRANT_ANNIVERSARY` ledger entry, raising the budget's `committed_points` by the milestone points, and recomputing the employee's tier. Each `AnniversaryEvent` stores the `milestone_years` reached, the `scheduled_date` (the logical date the event was processed), its resulting `status`, and the `award_id` of the created award when one exists. Because duplicates resolve to `SKIPPED_DUPLICATE`, a scan is idempotent per employee and milestone; the event list can be filtered by `program_id`, `employee_id`, `award_id`, and `status`.

Recognition tiers distill an employee's grant history into a standing. After every change to `lifetime_granted_points` — grant or clawback — the tier is recomputed: at least 20000 lifetime points earns `PLATINUM`, at least 5000 earns `GOLD`, at least 1000 earns `SILVER`, and anything below that is `BRONZE`. The lower bounds are inclusive, so exactly 1000 lifetime points is already `SILVER`.

### 3.5. Catalog Redemption and Fulfillment

Fulfillment vendors are onboarded by a `VendorOps` operator with a `name`, a unique `vendor_code`, a `daily_ship_capacity` of at least 1, a `lead_time_business_days` of zero or more, a `restocking_fee_percent` integer between 0 and 100 inclusive that defaults to 20, and the list of `supported_categories` the vendor can fulfill. A vendor starts `ACTIVE`. An `HRAdmin` may suspend a vendor — only from `ACTIVE`, else `ERR_INVALID_STATE_TRANSITION` — which blocks two things while it lasts: submitting any of the vendor's `PENDING_SUBMISSION` orders, and creating new catalog items for it, both refused with `ERR_VENDOR_SUSPENDED`. Orders already `SUBMITTED` or `SHIPPED` keep progressing. Reactivation restores `ACTIVE`, only from `SUSPENDED`. Both transitions increment the vendor's `version`.

Catalog items are created by `VendorOps` under the program gate — the program must be `ACTIVE` — and only for an `ACTIVE` vendor. An item carries its `vendor_id`, a `sku` unique within that vendor, a `name`, a `category` that must appear in the vendor's `supported_categories`, a strictly positive `point_cost` per unit, a strictly positive `cash_value_cents` fair-market value per unit that becomes the taxable basis, a `taxable_class` of `MERCHANDISE`, `GIFT_CARD`, or `EXPERIENCE` — gift cards are never de-minimis eligible — a `de_minimis_eligible` flag defaulting to false, a half-open availability window from `active_window_start` (inclusive) to `active_window_end` (exclusive and strictly later), and an `inventory_quantity` that is either a non-negative count or null for unlimited stock. Items start `ACTIVE`; a `VendorOps` operator may later revise `point_cost`, `cash_value_cents`, the availability window, or `inventory_quantity`, or retire the item by setting `status` to `RETIRED`, each edit incrementing the item's `version`. The catalog can be listed with `vendor_id`, `category`, and `status` filters.

An `ELIGIBLE` employee redeems points by naming a `catalog_item_id`, an optional `quantity` defaulting to 1 and bounded between 1 and 5 inclusive (anything else is `ERR_INVALID_QUANTITY`), and an `idempotency_key` unique per employee. The item must be purchasable at the current logical instant — `status` `ACTIVE` and the instant inside the half-open window — or the order is rejected with `ERR_CATALOG_ITEM_UNAVAILABLE`. Stocked items must have at least `quantity` on hand, else `ERR_ITEM_OUT_OF_STOCK`, and the inventory count drops at order creation. The employee's `available_points` must cover the order's `points_total` — computed as the item's `point_cost` multiplied by `quantity` and snapshotted at creation — else `ERR_INSUFFICIENT_POINTS`. Idempotency mirrors nominations: a replay with the same key and an identical payload returns the original order with HTTP 201; the same key with a different payload is `ERR_IDEMPOTENCY_CONFLICT`.

A created order opens in `fulfillment_status` `PENDING_SUBMISSION` with `escrow_status` `HELD`: a `HOLD` ledger entry moves `points_total` from the employee's `available_points` into `held_points`. The order's `program_id` is resolved at creation — the catalog is program-global, so the single `ACTIVE` program at creation time is used, pinned to the program of the employee's department budget that granted the employee's oldest unexpired points. `ship_date` stays empty until submission, `tax_record_id` until delivery, and `restocking_fee_points` is zero unless a return later completes. One abuse guard runs quietly here: a single order whose `points_total` exceeds 50000 auto-creates an `OPEN` abuse flag with `rule_code` `REDEMPTION_ANOMALY` — but the order still succeeds. Orders can be listed with `employee_id`, `catalog_item_id`, `fulfillment_status`, `escrow_status`, and `program_id` filters.

Submission to the vendor is a `VendorOps` action that advances `fulfillment_status` from `PENDING_SUBMISSION` to `SUBMITTED` and assigns the `ship_date`. The selector starts from the candidate date obtained by adding the vendor's `lead_time_business_days` business days — Monday through Friday, skipping weekends — to the logical today. While the number of that vendor's orders in `SUBMITTED` or `SHIPPED` already assigned to the candidate date reaches the vendor's `daily_ship_capacity`, the candidate rolls forward to the next business day; each calendar day is a capacity bucket, with no adjacency or gap treatment. If the candidate lands beyond 45 calendar days from the logical today, submission is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`; a candidate exactly 45 days out is still assignable. Submission also requires the vendor to be `ACTIVE`, and increments the order's `version`.

From `SUBMITTED`, a `VendorOps` operator marks the order `SHIPPED`; from `SHIPPED`, they mark it `DELIVERED` — anything else is `ERR_INVALID_STATE_TRANSITION`. Delivery is the settlement point, and in one logical step it: flips `escrow_status` from `HELD` to `SETTLED`; writes a `SETTLE_REDEEM` ledger entry removing `points_total` from `held_points` and adding it to `lifetime_redeemed_points`; consumes the employee's awards first-in-first-order per §3.4; creates the delivery's `TaxRecord` in `ESTIMATED` status, applying the de-minimis rule and the provisional gross-up variant of §3.6, and writes its id into the order's `tax_record_id`; and stamps `delivered_at` with the logical timestamp, anchoring both the return window and the order's pick-up by the accrual run covering that calendar month.

Cancellation walks the escrow back. From `PENDING_SUBMISSION` or `SUBMITTED` — and only those states — the owning employee, or an `HRAdmin`, may cancel; an `Employee` acting on someone else's order is refused with `ERR_FORBIDDEN_FOR_ROLE`. Cancellation lands the order in `CANCELLED` with escrow `REFUNDED`, writes a `REFUND` ledger entry returning the full `points_total` from held back to available points, restores the catalog item's inventory by `quantity` when the item is stocked, and frees the vendor's `ship_date` capacity slot when the order had been `SUBMITTED`.

Returns fork from `DELIVERED`. The owning employee requests a return within fourteen days of `delivered_at`; gift cards are never returnable, and either violation is `ERR_RETURN_NOT_ALLOWED`. The request, optionally carrying a `reason`, moves the order to `RETURN_REQUESTED` with escrow still `SETTLED`. A `VendorOps` operator then completes the return, landing the order in `RETURNED` with the third escrow terminal, `SETTLED_WITH_FEE`. Completion computes `restocking_fee_points` as the order's `points_total` multiplied by the vendor's `restocking_fee_percent` and divided by 100, floored to whole points; it writes two ledger entries — a `REFUND` crediting the employee's `available_points` with `points_total` minus `restocking_fee_points`, and a `RESTOCKING_FEE` debiting the fee, which counts toward `lifetime_redeemed_points`. Refunded points land in `available_points` only: they are not added back to any award's `points_remaining`, because awards already consumed stay consumed, and the item's inventory is not restored on returns. The linked tax record is corrected too: still `ESTIMATED`, it is `VOIDED`; already `FINALIZED`, it becomes `AMENDED` — keeping both the original final figures and a compensating amendment note that reverses the taxable value to zero.

### 3.6. Tax Treatment of Awards

Every delivered order creates exactly one `TaxRecord`, linked to its `redemption_order_id` and retrievable through the tax-record list filtered by `redemption_order_id`, `employee_id`, `program_id`, `tax_year`, or `status`. The record's `tax_year` is the calendar year of the order's `delivered_at`, and its `status` walks from `ESTIMATED` to `FINALIZED`, with `VOIDED` or `AMENDED` as the return-driven terminals of §3.5.

The de-minimis exclusion runs first and is all-or-nothing. When the item is `de_minimis_eligible`, is not a `GIFT_CARD`, and the employee's `ytd_de_minimis_cents` plus the order value — the item's `cash_value_cents` multiplied by `quantity` — stays at or below the annual cap of 10000 cents (one hundred dollars), the award is excluded: `taxable_value_cents` records 0, `de_minimis_applied` records true, and the employee's `ytd_de_minimis_cents` grows by the order value. Reaching exactly the cap still excludes. Otherwise — ineligible item, gift card, or one cent over the cap — the order is fully taxable with no partial exclusion: `taxable_value_cents` is the whole order value.

The gross-up then compensates the employee for the tax on the award, and because the gross-up is itself taxable income, the circularity is resolved in closed form. The federal rate is 0.37 when the employee's `ytd_supplemental_wages_cents` exceeds 100000000 cents (one million dollars) and 0.22 otherwise; the state rate is the program's `state_rate_map` lookup for the employee's `state_code`, defaulting to 0.0 when the key is missing; the combined rate adds those two plus the FICA rate of 0.0765. The gross-up is the `taxable_value_cents` multiplied by the combined rate and divided by one minus the combined rate, rounded half-up to integer cents in a single rounding applied to the whole expression — no intermediate rounding of the rate. When the program's `grossup_enabled` is false, or the `taxable_value_cents` is zero, the gross-up is zero.

Two variants of this computation exist, differing only in when they read the wage accumulator. The provisional variant runs at delivery, uses the employee's `ytd_supplemental_wages_cents` as recorded at that moment, and stores its result in `estimated_gross_up_cents`, with the applied rates snapshotted into `federal_rate_applied` and `state_rate_applied`. The final variant reruns at tax-year finalization using the employee's final `ytd_supplemental_wages_cents` after all compensation adjustments, storing `final_gross_up_cents`; identical inputs would produce identical outputs, but intervening compensation adjustments make the results diverge, and `delta_cents` records `final_gross_up_cents` minus `estimated_gross_up_cents`. Both `final_gross_up_cents` and `delta_cents` stay empty until finalization. The delivery-period chargeback basis is `employer_cost_cents`, the sum of `taxable_value_cents` and `estimated_gross_up_cents`.

The wage accumulator itself is payroll-owned: a `PayrollSpecialist` posts compensation adjustments that set `ytd_supplemental_wages_cents` for the current calendar year, incrementing the employee's `version` — the only path by which that field changes.

Tax-year finalization belongs to the `PayrollSpecialist` and is gated hard. The request names a `tax_year` between 2000 and 2100 inclusive (`ERR_INVALID_TAX_YEAR` otherwise). Every month's accrual run for the program and that year — months 1 through 12 — must exist and be `CLOSED` or `VOIDED`; a missing, `OPEN`, or merely `RECONCILED` month fails the gate with `ERR_PERIODS_NOT_CLOSED`. Repeating a finalization for an already-finalized year is `ERR_TAX_YEAR_FINALIZED`. On success, every `ESTIMATED` record of that `tax_year` moves to `FINALIZED` with its final gross-up recomputed, and the response summarizes the run with `finalized_count`, the affected `records`, and `total_delta_cents`. A return completed after finalization does not rewrite history: the record moves to `AMENDED`, its `delta_cents` recomputed against a zeroed taxable value, keeping the audit of both figures.

### 3.7. Monthly Accruals and Department Chargeback

The finance cycle runs monthly, owned end to end by the `FinanceAdmin` — deliberately never by the `PayrollSpecialist`. Creating an accrual run for a program names the `program_id`, `period_year`, and `period_month` (1 through 12). Only one non-`VOIDED` run may exist for a given program, year, and month; a duplicate is rejected with `ERR_DUPLICATE_ACCRUAL_RUN`. The run snapshots the program's accrual method into `accrual_method_used` at creation — `STRAIGHT_LINE` or `UTILIZATION_WEIGHTED` — opens in `OPEN` status, and computes a `department_breakdown` with one entry per department holding employees in the program, each entry carrying the `department_id`, `accrual_cents`, `redemption_cost_cents`, `gross_up_expense_cents`, `forfeiture_credit_cents`, and `net_chargeback_cents`. Run-level `total_accrual_cents` and `total_net_chargeback_cents` sum the per-department figures, and the runs list can be filtered by `program_id`, `period_year`, and `status`.

The accrual side answers what the department should have expensed for the month, under the snapshotted variant. Both variants look forward at the same annual allocation: the sum, over the department's budgets whose windows intersect the period month, of each budget's `allocated_points` multiplied by the program's `point_cost_rate_cents`. `STRAIGHT_LINE` accrues one twelfth of that annual figure, rounded half-up to integer cents. `UTILIZATION_WEIGHTED` multiplies the annual figure by a redemption curve — 0.07 for each of months 1 through 11 and 0.23 for month 12, summing to exactly 1.00 — again rounded half-up. The two are equally valid amortizations that yield different monthly numbers; the program's `fiscal_year_start_month` (1 through 12, defaulting to 1) labels the year boundary only, because accrual periods are calendar months.

The chargeback side answers what the department actually consumed, summing three components over the input window — from the first instant of the period month to the first instant of the next month. Redemption cost sums, over orders settled by the department's employees in the window matched on `delivered_at`, each order's net settled points multiplied by `point_cost_rate_cents` and rounded half-up — where net settled points are the order's `points_total` when its escrow ended `SETTLED`, or only its `restocking_fee_points` when it ended `SETTLED_WITH_FEE`, because a returned order contributes only its fee. The per-line rounding order is pinned: round each settled order line first, then sum; summing first and rounding once produces a different number and is forbidden. Gross-up expense sums the `estimated_gross_up_cents` of tax records created in the window for the department's employees, matched on record creation time. Forfeiture credit returns half the value of points expired or clawed back in the window — the sum of `EXPIRY` and `CLAWBACK` ledger points created in the period, multiplied by `point_cost_rate_cents` and by the recovery rate 0.5, rounded half-up in a single rounding on the department aggregate. A department's `net_chargeback_cents` is its redemption cost plus its gross-up expense minus its forfeiture credit, attributed to the department's `chargeback_account_code`.

Reconciliation protects the posted figures from late-arriving truth. Reconciling an `OPEN` run recomputes the period's net chargeback from current data; when the recomputation differs from the posted `total_net_chargeback_cents` — for instance because an order settled into the period after the run was created — the nonzero difference is exposed as `variance_cents` and the reconcile is rejected with `ERR_ACCRUAL_VARIANCE`. When the recomputation matches, `variance_cents` settles to zero and the run moves to `RECONCILED`. From there, closing the run moves it to `CLOSED`, making the period eligible for the tax-year finalization gate of §3.6; closing is allowed only from `RECONCILED`. A run that can never reconcile — or was created in error — can instead be voided from `OPEN`: a `VOIDED` run no longer counts toward the period-uniqueness check nor toward the finalization gate. Every transition increments the run's `version`, and any transition attempted from the wrong status is `ERR_INVALID_STATE_TRANSITION`.

### 3.8. Abuse Detection and Enforcement

Abuse flags are the program's enforcement instrument. Some are raised by the system itself — a velocity breach raises an `OPEN` flag with `rule_code` `VELOCITY_EXCEEDED`, and an anomalous single-order redemption raises one with `rule_code` `REDEMPTION_ANOMALY` — while an `HRAdmin` raises the rest manually, supplying the subject `employee_id`, the `program_id`, a `rule_code`, and optional structured `details` carrying the evidence: counts, windows, related ids. The full `rule_code` vocabulary is `VELOCITY_EXCEEDED`, `DUPLICATE_ATTEMPT`, `SELF_NOMINATION`, `MANAGER_QUID_PRO_QUO`, `REDEMPTION_ANOMALY`, and `MANUAL_REVIEW`. Every flag records `raised_by` — the string "system" or the acting `HRAdmin` identifier — and opens in `OPEN` status; flags can be listed with `employee_id`, `program_id`, `rule_code`, and `status` filters.

Adjudication is an `HRAdmin` workflow. Reviewing moves a flag from `OPEN` to `UNDER_REVIEW`; anything else is `ERR_INVALID_STATE_TRANSITION`. Confirming works from either `OPEN` or `UNDER_REVIEW` and lands the flag in `CONFIRMED`; disclosing the same states, dismissing lands it in `DISMISSED`. Both decisions stamp `resolved_by` with the acting administrator's identifier and increment the flag's `version`, and both `CONFIRMED` and `DISMISSED` are terminal.

Confirmation is the point of no return, because it suspends the employee, and the cascade order is pinned. First, every one of the employee's redemption orders still in `PENDING_SUBMISSION` is cancelled with a full `REFUND` of its held points and its inventory restored. Second, every `ACTIVE` award of the employee is revoked in `granted_at` ascending order, ties broken by `created_at` ascending, each revocation firing its own clawback side effects per §3.4 — the `CLAWBACK` ledger entries reference the flag through `reference_type` `ABUSE_FLAG`, the employee's `available_points` may go negative, and the originating budgets release committed points when not `CLOSED`. Third, the employee's `recognition_tier` is recomputed against the reduced `lifetime_granted_points`. The employee's `program_status` lands in `SUSPENDED`, the employee's `version` increments, and suspension is sticky in both directions: a `SUSPENDED` employee cannot nominate or redeem (`ERR_EMPLOYEE_SUSPENDED`), and suspension never restores the revoked awards.

Reinstatement is possible but guarded. An `HRAdmin` may reinstate an employee only from `SUSPENDED`, and only while no abuse flag for that employee remains in `OPEN` or `UNDER_REVIEW`; either violation is `ERR_INVALID_STATE_TRANSITION`. A successful reinstatement returns the employee to `ELIGIBLE` and increments the employee's `version`, leaving the revocation history intact.

### 3.9. Participation and Inclusion Analytics

Participation analytics are computed on read from the logical clock — never stored — and are available to every role. The query accepts an optional `window_days`, defaulting to 90, and examines the window from that many days before now through now, inclusive at both ends. An eligible employee is any employee whose department holds at least one budget in the program, regardless of window or posture; a participating employee is any distinct employee with at least one of — a nomination submitted in a status other than `CANCELLED`, an award granted, or a redemption order created — inside the window.

Three headline measures come back. `participation_rate_bp` is the total participating employees times ten thousand, divided by the total eligible employees, floored to basis points — and defined as 0 when no one is eligible. Per-department rates are computed the same way within each department; departments with zero eligible employees are excluded from the disparity calculation. `inclusion_disparity_bp` is then the gap between the highest and lowest included department rates, and is 0 when fewer than two departments qualify. For concentration, employees are ranked by points granted inside the window, descending, ties broken by the employee's `created_at` ascending; the top-N count is the larger of 1 and five percent of the total eligible employees, floored; and `concentration_share_bp` is the points granted to that top group times ten thousand, divided by all points granted in the window, floored — 0 when no points were granted at all. The response rounds out the picture with the echoed `window_days`, the `eligible_employees` and `participating_employees` counts, and the per-department `department_breakdown`.

## 4. Endpoint Definitions

All endpoints are mounted under `/api`. Endpoints that create a new resource answer 201; reads, modifications, and action invocations answer 200. Two nuances are worth restating: an idempotent replay of a nomination or redemption-order creation returns the original resource with 201 and creates nothing new, and the dual-outcome return-for-revision action answers 200 whether the nomination lands in `RETURNED_FOR_REVISION` or is auto-rejected into `REJECTED`. Request and response bodies are deliberately omitted from this table — the narratives of §3 define them.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/api/programs` | Create a recognition program (status `DRAFT`) | HRAdmin |
| GET | `/api/programs/{programId}` | Get a program | All roles |
| PATCH | `/api/programs/{programId}` | Update program config under OCC; `status` `CLOSED` performs the guarded program close | HRAdmin |
| POST | `/api/programs/{programId}/activate` | Activate a `DRAFT` or `SUSPENDED` program | HRAdmin |
| POST | `/api/programs/{programId}/suspend` | Suspend an `ACTIVE` program (blocks new nominations, redemptions, budgets, scans) | HRAdmin |
| POST | `/api/programs/{programId}/anniversary-scans` | Run the service-anniversary scan for the logical clock's current date | HRAdmin |
| POST | `/api/programs/{programId}/finalize-tax-year` | Finalize all `ESTIMATED` tax records of a tax year with the final gross-up variant | PayrollSpecialist |
| GET | `/api/programs/{programId}/analytics/participation` | Participation and inclusion analytics computed on read | All roles |
| POST | `/api/departments` | Create a department | HRAdmin |
| GET | `/api/departments/{departmentId}` | Get a department | All roles |
| POST | `/api/employees` | Register an employee (`ELIGIBLE`, `BRONZE`, zero balances) | HRAdmin |
| GET | `/api/employees/{employeeId}` | Get an employee | All roles |
| GET | `/api/employees` | List employees with filters | All roles |
| POST | `/api/employees/{employeeId}/compensation-adjustments` | Set `ytd_supplemental_wages_cents` for the current calendar year | PayrollSpecialist |
| POST | `/api/employees/{employeeId}/reinstate` | Reinstate a `SUSPENDED` employee to `ELIGIBLE` | HRAdmin |
| GET | `/api/employees/{id}/ledger-entries` | List the employee's point ledger entries chronologically | All roles |
| POST | `/api/employees/{employeeId}/points-adjustments` | HR adjustment grant of points, charged to the selected budget | HRAdmin |
| POST | `/api/budgets` | Create a department point budget for a half-open window | FinanceAdmin |
| GET | `/api/budgets/{budgetId}` | Get a point budget | All roles |
| GET | `/api/budgets` | List point budgets with filters | All roles |
| POST | `/api/budgets/{budgetId}/adjustments` | Adjust `allocated_points` by a signed delta under OCC | FinanceAdmin |
| POST | `/api/nominations` | Submit a nomination; reserves points in the selected budget | Employee, Manager |
| GET | `/api/nominations/{nominationId}` | Get a nomination | All roles |
| GET | `/api/nominations` | List nominations with filters | All roles |
| POST | `/api/nominations/{nominationId}/approve` | Approve a `PENDING_REVIEW` nomination under OCC; creates the award and grants points | Manager, HRAdmin |
| POST | `/api/nominations/{nominationId}/reject` | Reject a `PENDING_REVIEW` nomination; releases the reservation | Manager, HRAdmin |
| POST | `/api/nominations/{nominationId}/return-for-revision` | Return for revision; the third return auto-rejects instead | Manager, HRAdmin |
| POST | `/api/nominations/{nominationId}/resubmit` | Nominator resubmits a `RETURNED_FOR_REVISION` nomination | Employee, Manager |
| POST | `/api/nominations/{nominationId}/cancel` | Nominator cancels a `PENDING_REVIEW` or `RETURNED_FOR_REVISION` nomination | Employee, Manager |
| GET | `/api/awards/{awardId}` | Get an award | All roles |
| GET | `/api/awards` | List awards with filters | All roles |
| POST | `/api/awards/{awardId}/revoke` | Revoke an `ACTIVE` award; claws back remaining points | HRAdmin |
| POST | `/api/vendors` | Create a fulfillment vendor | VendorOps |
| GET | `/api/vendors/{vendorId}` | Get a vendor | All roles |
| POST | `/api/vendors/{vendorId}/suspend` | Suspend a vendor; blocks order submission and catalog item creation for it | HRAdmin |
| POST | `/api/vendors/{vendorId}/reactivate` | Reactivate a suspended vendor | HRAdmin |
| POST | `/api/catalog-items` | Create a catalog item (program must be `ACTIVE`) | VendorOps |
| GET | `/api/catalog-items/{catalogItemId}` | Get a catalog item | All roles |
| GET | `/api/catalog-items` | List catalog items with filters | All roles |
| PATCH | `/api/catalog-items/{catalogItemId}` | Update window, pricing, or inventory; retire an item | VendorOps |
| POST | `/api/redemption-orders` | Redeem points for a catalog item; holds points in escrow | Employee |
| GET | `/api/redemption-orders/{redemptionOrderId}` | Get a redemption order | All roles |
| GET | `/api/redemption-orders` | List redemption orders with filters | All roles |
| POST | `/api/redemption-orders/{redemptionOrderId}/submit` | Submit the order to the vendor; assigns the ship date | VendorOps |
| POST | `/api/redemption-orders/{redemptionOrderId}/mark-shipped` | Mark a `SUBMITTED` order shipped | VendorOps |
| POST | `/api/redemption-orders/{redemptionOrderId}/mark-delivered` | Mark a `SHIPPED` order delivered; settles escrow, consumes awards, creates the tax record | VendorOps |
| POST | `/api/redemption-orders/{redemptionOrderId}/cancel` | Cancel a `PENDING_SUBMISSION` or `SUBMITTED` order; full refund and inventory restore | Employee, HRAdmin |
| POST | `/api/redemption-orders/{redemptionOrderId}/request-return` | Request return of a `DELIVERED` order within fourteen days | Employee |
| POST | `/api/redemption-orders/{redemptionOrderId}/complete-return` | Complete a requested return; refund minus restocking fee | VendorOps |
| GET | `/api/tax-records/{taxRecordId}` | Get a tax record | All roles |
| GET | `/api/tax-records` | List tax records with filters | All roles |
| POST | `/api/accrual-runs` | Create and execute the monthly accrual and chargeback run for a program | FinanceAdmin |
| GET | `/api/accrual-runs/{accrualRunId}` | Get an accrual run | All roles |
| GET | `/api/accrual-runs` | List accrual runs with filters | All roles |
| POST | `/api/accrual-runs/{accrualRunId}/reconcile` | Recompute the period's net chargeback and reconcile; variance must be zero | FinanceAdmin |
| POST | `/api/accrual-runs/{accrualRunId}/close` | Close a `RECONCILED` run | FinanceAdmin |
| POST | `/api/accrual-runs/{accrualRunId}/void` | Void an `OPEN` run so a corrected run can be created | FinanceAdmin |
| POST | `/api/abuse-flags` | Manually raise an abuse flag against an employee | HRAdmin |
| GET | `/api/abuse-flags/{abuseFlagId}` | Get an abuse flag | All roles |
| GET | `/api/abuse-flags` | List abuse flags with filters | All roles |
| POST | `/api/abuse-flags/{abuseFlagId}/review` | Move an `OPEN` flag to `UNDER_REVIEW` | HRAdmin |
| POST | `/api/abuse-flags/{abuseFlagId}/confirm` | Confirm a flag; cascades suspension, revocation, and clawback | HRAdmin |
| POST | `/api/abuse-flags/{abuseFlagId}/dismiss` | Dismiss an `OPEN` or `UNDER_REVIEW` flag (no cascade) | HRAdmin |
| GET | `/api/anniversary-events/{anniversaryEventId}` | Get an anniversary event | All roles |
| GET | `/api/anniversary-events` | List anniversary events with filters | All roles |
| POST | `/api/_clock/set_current_utc` | Set the server's logical clock; fires the ordered auto-transition sweep | HRAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live in the narratives of §2 and §3; this catalogue is the identifier-to-status map only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_QUANTITY` | 400 |
| `ERR_INVALID_TAX_YEAR` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_EMPLOYEE_SUSPENDED` | 409 |
| `ERR_VELOCITY_LIMIT_EXCEEDED` | 409 |
| `ERR_SELF_NOMINATION` | 422 |
| `ERR_SELF_APPROVAL` | 409 |
| `ERR_NOMINEE_NOT_IN_SCOPE` | 409 |
| `ERR_NOMINATION_TYPE_DISABLED` | 409 |
| `ERR_DUPLICATE_NOMINATION` | 409 |
| `ERR_IDEMPOTENCY_CONFLICT` | 409 |
| `ERR_BUDGET_NOT_FOUND` | 409 |
| `ERR_BUDGET_PERIOD_OVERLAP` | 409 |
| `ERR_BUDGET_RESTRICTED_AMOUNT` | 409 |
| `ERR_BUDGET_EXHAUSTED` | 409 |
| `ERR_BUDGET_CLOSED` | 409 |
| `ERR_INSUFFICIENT_POINTS` | 409 |
| `ERR_CATALOG_ITEM_UNAVAILABLE` | 409 |
| `ERR_ITEM_OUT_OF_STOCK` | 409 |
| `ERR_VENDOR_SUSPENDED` | 409 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 409 |
| `ERR_RETURN_NOT_ALLOWED` | 409 |
| `ERR_DUPLICATE_ACCRUAL_RUN` | 409 |
| `ERR_ACCRUAL_VARIANCE` | 409 |
| `ERR_PERIODS_NOT_CLOSED` | 409 |
| `ERR_TAX_YEAR_FINALIZED` | 409 |

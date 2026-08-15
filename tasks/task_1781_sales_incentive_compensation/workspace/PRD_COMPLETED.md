# Sales Incentive Compensation API — Product Requirements Document

## 1. Introduction

Sales compensation teams live and die by the accuracy of the payout file. When a plan document changes mid-quarter, when a manager override rolls up one hierarchy level too many, or when a cancelled deal claws money back out of a period that has already closed, the error surfaces as a rep's paycheck — and then as a dispute, an audit finding, or an attrition statistic. This document specifies the Sales Incentive Compensation API, a system that administers the full incentive cycle for a sales organization: plan design with quota-to-payout curves, plan document versioning and rep acceptance, transaction crediting with splits and one-level manager roll-ups, attainment and accelerator calculation, draws and guarantees with clawback on cancellation, dispute intake and adjustment adjudication, period close with statement generation, and payroll export with accrual accounting.

The API is built on a flat set of peer resources — programs, plans, reps, assignments, transactions, credit entries, adjustments, disputes, payout statements, and payroll exports — linked by identifiers carried in request bodies and query parameters rather than by deeply nested URLs. Three forces shape every workflow below. First, segregation of duties: the operator who drafts a plan or an adjustment is never the one who publishes or approves it. Second, period discipline: money settles only at period close, credits lock as periods roll forward, and yesterday's ledger is corrected through adjustments rather than rewritten. Third, optimistic concurrency: revising a plan document or closing a period requires the caller to prove they have observed the latest version of the record they intend to supersede.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes four distinct roles: `CompAdmin`, `CompAnalyst`, `CompManager`, and `Rep`. Failure to provide valid headers — a missing or malformed header, or a role value that is not one of the four declared roles — will result in an `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` error. Furthermore, access to specific operations is restricted by role; an attempt to perform an action outside of the caller's designated role will be rejected with an `ERR_FORBIDDEN_FOR_ROLE` error.

The identity carried by `X-User-ID` differs by role, and the distinction drives every ownership check in the system:

- When `X-User-Role` is `Rep`, `X-User-ID` is the `id` of the acting `Rep` entity; ownership checks on any resource that references a `Rep` — assignments, credit entries, disputes, payout statements — compare the resource's rep linkage to `X-User-ID`. A `Rep` caller who references a resource not linked to their own rep record receives `ERR_NOT_FOUND`, exactly as if the resource did not exist; the system never reveals that a foreign resource exists.
- When `X-User-Role` is `CompAdmin`, `CompAnalyst`, or `CompManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `created_by_user_id` on a `CompPlan` or on an `Adjustment`, where the scaffold of segregation-of-duties checks requires it — but it is never compared to any entity's `id`.

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

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with ties broken by the resource's `id` in ascending order.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Compensation Periods and the Program Accrual Ledger

Every compensation program is a self-contained fiscal calendar. A `CompProgram` is created with nothing more than a `name`, and from that moment it carries two system-maintained counters that govern the entire incentive cycle. The first, `current_period_index`, is the one-based index of the program's currently open compensation period; it starts at 1 when the program is created and advances by exactly one each time the period is closed — there is no other way to move it. The second, `accrued_balance_cents`, is the program's recognized-but-unpaid net payout liability: it starts at 0, grows at each period close by the sum of that period's `net_payable_cents` across all settled statements, and is relieved at payroll export by the export's `total_cents`.

Period attribution is deliberate and worth internalizing before reading §3. A `SalesTransaction` snapshots the program's open period into `booked_period_index` at creation, but that value is bookkeeping context only; `transaction_date` is likewise purely informational. The period a credit actually earns into is determined by `posted_period_index` on the credit entry — the period in which the entry transitioned to `POSTED` — never by the business date the sale occurred. Adjustments carry their own `period_index`, captured from the program's open period at the moment the adjustment is created, which fixes the period-close settlement that will absorb them.

### 2.5. Common Resource Properties

All primary resources — programs, plans, reps, assignments, transactions, credit entries, adjustments, disputes, and payout statements — include a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (e.g., `2025-05-24T10:30:00.123Z`), set when the resource is first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed upon any change to the resource's properties.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created and increments by 1 with every modification to the resource, and which backs the optimistic concurrency controls of §2.7.

The `PayrollExport` resource is the single exception to this convention. Because an export is an immutable, append-only record of a payout file, it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Integer-Cent Money and Basis-Point Arithmetic

All monetary values in the system — quotas, credits, draws, guarantees, adjustments, statement line items, export totals — are represented as integer cents. No fractional cents exist anywhere in the API, and all rounding decisions below are expressed in whole-cent terms.

Two rounding disciplines recur throughout the calculations of §3, and they must not be confused. **Round half up** is applied whenever a multiplication or division would otherwise produce a fractional cent: per-split credit allocation, per-band curve payouts, and roll-up amounts each round their own intermediate result half up to a whole cent before any summation takes place. **Integer floor** — fractions always discarded, never rounded up — is applied exclusively to basis-point attainment ratios, so that an attainment of 9999 out of 10000 basis points cannot be presented as quota achieved.

Rates and attainment are expressed in basis points against a fixed denominator of ten thousand: 10000 basis points is exactly 100 percent. Where a ratio must be converted to money or money to a ratio, the conversion multiplies by the basis-point figure and divides by ten thousand, applying the rounding discipline stated for that particular calculation.

### 2.7. Optimistic Concurrency Control

Two write operations in the system are protected by optimistic concurrency control, because each one supersedes a document lineage or a period boundary that the caller must have observed before acting. Endpoints not named in this section do not take a version field at all.

Revising a plan document requires the request to carry `expected_plan_version`, a non-optional field holding the client's last-observed `version` of the target `CompPlan`. If another writer has advanced the plan's version since the client last read it — whether through a publish or an earlier revision — the mismatch is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412), preventing the client from unknowingly superseding a document it has not seen. The version check is evaluated only after the state precondition passes: a revise attempted on a plan that is no longer `PUBLISHED` fails with `ERR_INVALID_STATE_TRANSITION` regardless of the version carried. The segregation-of-duties check of §2.8 is likewise evaluated only after the version check passes: the plan's own creator attempting a revise while carrying a stale version receives `ERR_STALE_PLAN_VERSION`, not `ERR_SEGREGATION_OF_DUTIES`.

Closing a compensation period requires the request to carry `expected_program_version`, a non-optional field holding the client's last-observed `version` of the target `CompProgram`. If the program's version no longer matches — because a period boundary the caller did not observe has already been crossed — the close is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Here too the ordering is pinned: the business guards of period close, in particular the open-dispute block that surfaces `ERR_OPEN_DISPUTES_EXIST`, are evaluated before the version check, so a close blocked on unresolved disputes reports that condition rather than a stale version.

### 2.8. Segregation of Duties

Compensation administration separates the drafter from the approver at two checkpoints, and the system enforces both mechanically by comparing `X-User-ID` against the recorded `created_by_user_id` of the target resource.

A `CompPlan` records the `X-User-ID` of its creator at creation time. Publishing the plan, and later revising its document, must each be performed by a different operator than the creator; an attempt by the creator to publish or revise their own plan is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The same wall stands between a manual adjustment and its adjudication: the `CompAnalyst` who drafted an `Adjustment` may not approve it, and an approval attempted by the drafting operator is rejected with `ERR_SEGREGATION_OF_DUTIES`. Rejection of an adjustment carries no such restriction — any `CompManager` may reject a pending adjustment, including one drafted by a user with the same identifier.

### 2.9. Validation Order, Resource Addressing, and Rep Visibility

Requests are validated against a fixed ladder of nine priority tiers, and the ordering is observable: when a request would fail checks in more than one tier, the error returned is always from the earliest tier that fails.

1. **User context** — both headers present, well-formed, and the role declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Role authorization** — the caller's role appears in the endpoint's authorized list (`ERR_FORBIDDEN_FOR_ROLE`).
3. **Existence and visibility** — path and body identifiers resolve to existing resources (`ERR_NOT_FOUND`). Where an endpoint path contains a resource identifier — `programId`, `planId`, `repId`, `assignmentId`, `transactionId`, `creditEntryId`, `adjustmentId`, `disputeId`, `statementId`, or the bare `id` used by a program's payroll-export listing — existence is validated left to right, and the request is rejected at the first identifier that does not resolve. For `Rep` callers this tier additionally performs ownership hiding: assignments, credit entries, disputes, and payout statements not linked to the caller's own rep record behave as absent and surface `ERR_NOT_FOUND`, indistinguishable from a genuinely missing resource.
4. **State preconditions** — the target resource is in a valid from-state for the requested transition. Where a dedicated code exists it is used — `ERR_PLAN_NOT_PUBLISHED` on assignment creation and acceptance, `ERR_TRANSACTION_ALREADY_CANCELLED` on a repeat cancel — and all other illegal transitions, including acting on terminal states, surface `ERR_INVALID_STATE_TRANSITION`.
5. **Segregation of duties** — the publish, revise, and adjustment-approval checks of §2.8 (`ERR_SEGREGATION_OF_DUTIES`).
6. **Temporal windows** — the dispute filing window (`ERR_DISPUTE_WINDOW_CLOSED`), the payroll export period discipline (`ERR_PAYROLL_PERIOD_NOT_CLOSED`), and basic date sanity such as an end date earlier than its start date (`ERR_INVALID_REQUEST`).
7. **Structural constraints** — split totals, curve tier well-formedness, uniqueness of `external_ref` and `employee_ref`, acyclic manager chains, plan and assignment window overlaps, the single-active-dispute rule, the one-export-per-period rule, the archive guard against active assignments, the open-dispute block on period close, and the all-approved guard on payroll export.
8. **Cross-reference coherence** — every split rep holding an active assignment in the program (`ERR_SPLIT_REP_INELIGIBLE`), the manager belonging to the same program (`ERR_MANAGER_PROGRAM_MISMATCH`) — with the referenced manager's own existence verified at this tier alongside the same-program check, a nonexistent manager surfacing `ERR_NOT_FOUND` here rather than at tier 3 — and a disputed credit entry belonging to the disputed assignment (`ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`), with a supplied `credit_entry_id` that resolves to no credit entry likewise surfacing `ERR_NOT_FOUND` at this tier.
9. **Money sanity** — a positive quota (`ERR_QUOTA_INVALID`), a nonzero adjustment amount (`ERR_ADJUSTMENT_AMOUNT_INVALID`), and dispute requested/approved amounts within their credited and requested bounds (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`).

A malformed body, a missing required field, or an invalid enum value is rejected with `ERR_INVALID_REQUEST` before any business rule is consulted.

## 3. Business Logic & Workflows

### 3.1. Designing and Governing Compensation Plans

Everything begins when a `CompAdmin` creates a program with a `name`; the program's period counter and accrual ledger come into existence at 1 and 0 respectively, as described in §2.4.

Within a program, a `CompAdmin` authors compensation plans. Plan creation takes the owning `program_id`, a plan `name`, and an effectiveness window given by `effective_start_date` and `effective_end_date`. The window is a **closed interval**: the end date is inclusive, the end must not fall before the start (an inverted window is rejected with `ERR_INVALID_REQUEST`), and two plans of the same program whose closed intervals touch at all — a shared boundary date already counts as a collision — cannot coexist unless one of them is `ARCHIVED`; a colliding creation is rejected with `ERR_PLAN_WINDOW_OVERLAP`.

The heart of the plan is `curve_tiers`, the quota-to-payout curve: a non-empty array of tiers, each pairing an `attainment_floor_bps` with a `rate_bps`. The first tier's floor must be exactly 0 basis points, floors must be strictly ascending across the array, and no rate may be negative; any violation is rejected with `ERR_CURVE_TIERS_INVALID`. Both the shape validation and the business validation of `curve_tiers` run as part of basic body validation, ahead of the owning program's existence check. Three further plan parameters tune the economics. `attainment_mode` selects which credits count toward attainment — `DIRECT_ONLY` or `INCLUDE_ROLLUP` — and defaults to `DIRECT_ONLY` when omitted. `rollup_rate_bps` is the fraction of a subordinate's posted credit, expressed in basis points, that rolls up to the direct manager; it defaults to 0 and may never be negative, a negative value rejected with `ERR_INVALID_REQUEST` in the same early validation pass, ahead of the program-existence check. `payout_cap_cents` is an optional per-period gross payout cap — positive when set, or null to leave payouts uncapped, with a non-positive non-null value likewise rejected with `ERR_INVALID_REQUEST` in that pass.

A new plan is born in `DRAFT` status with `document_version` 1 and its `created_by_user_id` stamped from the caller. Publishing is a deliberate second act by a different `CompAdmin`: the actor must differ from `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`), the curve tiers are re-validated at publish time (`ERR_CURVE_TIERS_INVALID`), and success moves the plan from `DRAFT` to `PUBLISHED`, incrementing the plan's `version` by 1. Only `PUBLISHED` plans can receive assignments.

Once published, a plan evolves by revision rather than mutation. A revising `CompAdmin` supplies `expected_plan_version` for the concurrency check of §2.7, may optionally supply replacement `curve_tiers` (re-validated when supplied), `payout_cap_cents`, `rollup_rate_bps`, or `attainment_mode`, and — as with publish — must not be the plan's creator. The replacement fields are validated only as they are applied, after the segregation-of-duties check, so a forbidden caller carrying invalid replacements is rejected with `ERR_SEGREGATION_OF_DUTIES` rather than a validation error. A successful revision leaves the plan in `PUBLISHED`, increments `document_version` by 1, increments the plan's `version` by 1, and triggers a document re-offer cascade: every assignment of the plan whose lifecycle `status` is `ACTIVE` has its `acceptance_status` returned to `OFFERED`, whether it was `ACCEPTED` or `DECLINED`, while each assignment's `accepted_document_version` is deliberately left unchanged as historical record. From that moment, new credits for the reverted assignments park in `PENDING` until the rep re-accepts; credits already `POSTED` or `LOCKED` are untouched by the revision.

Retirement is archival. A plan in either `DRAFT` or `PUBLISHED` may be archived, but only while no assignment of the plan has lifecycle `status` equal to `ACTIVE`; archiving with active assignments is rejected with `ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS`. Archival moves the plan to `ARCHIVED` — a terminal state — and increments the plan's `version` by 1. Plans may be listed with optional `program_id` and `status` filters, and retrieved individually by identifier.

### 3.2. Building the Sales Roster and Reporting Hierarchy

A `CompAdmin` maintains the roster. Creating a rep requires the owning `program_id`, a display `name`, and an `employee_ref` — an external employee reference that must be unique within the program, with duplicates rejected as `ERR_DUPLICATE_EMPLOYEE_REF`. The optional `manager_id` links the rep to another rep in a self-referential reporting chain, and two guards protect that chain: the manager must belong to the same program (`ERR_MANAGER_PROGRAM_MISMATCH`), and the chain must remain acyclic — a rep may not be their own manager, nor may they take a descendant as manager (`ERR_REP_HIERARCHY_CYCLE`).

A `CompAdmin` may subsequently update a rep's `name` or `manager_id` — an explicit null `manager_id` detaches the rep from their manager; manager changes re-run the same-program and acyclicity checks exactly as at creation. The rep's `version` increments by 1 only when the request actually changes a field: an update that leaves both `name` and `manager_id` unchanged is a no-op that does not increment the version. The roster can be listed with optional `program_id` and `manager_id` filters, and individual reps retrieved by identifier. The hierarchy matters beyond org charts: it is the wiring for the manager roll-up credits of §3.4, which flow exactly one level up this chain.

### 3.3. Assignments and Plan Document Acceptance

An assignment binds a rep to a plan for a span of periods, and is created by a `CompAdmin` supplying `program_id`, `rep_id`, `plan_id`, the per-period `quota_cents`, an `effective_start_date`, and optionally an `effective_end_date`, plus the draw and guarantee economics described below. Existence of the body identifiers is validated in the order `program_id`, then `rep_id`, then `plan_id`, the first unresolvable identifier surfacing `ERR_NOT_FOUND`. The remaining checks fire in the ladder order of §2.9: the plan must be `PUBLISHED` (`ERR_PLAN_NOT_PUBLISHED`); the rep's assignment windows must not collide — each assignment occupies a half-open interval in which the start date counts and the end date does not, a null `effective_end_date` means open-ended, the end when present must fall after the start (`ERR_INVALID_REQUEST`), and any intersection with another non-`TERMINATED` assignment of the same rep is rejected with `ERR_ASSIGNMENT_WINDOW_OVERLAP` (mere adjacency, one window's end equal to the other's start, is allowed); and the quota must be positive (`ERR_QUOTA_INVALID`).

Draws and guarantees shape the per-period cash flow. `draw_amount_cents_per_period` — default 0, with a negative value rejected as `ERR_INVALID_REQUEST` during basic body validation, before any existence check — is paid each closed period while the assignment remains `ACTIVE`. `draw_recoverable` — default true — decides whether paid draws accrue as debt into `draw_outstanding_cents` for later recovery out of gross payout, or are simply paid and never accrued. `guarantee_amount_cents_per_period` — default 0, likewise rejected as `ERR_INVALID_REQUEST` when negative — sets a minimum net payable floor per closed period, with 0 meaning no guarantee.

Every assignment carries two parallel status dimensions. The lifecycle dimension, `status`, begins at `ACTIVE` and ends at `TERMINATED`. The document dimension, `acceptance_status`, begins at `OFFERED` and moves among `OFFERED`, `ACCEPTED`, and `DECLINED`; the assignment's `accepted_document_version` — null until the first acceptance — records which plan `document_version` the rep last accepted. Every monetary counter on a new assignment — `draw_outstanding_cents`, `draw_forgiven_cents`, `current_period_earned_cents`, `lifetime_earned_cents`, and `lifetime_paid_cents` — and both live indicators of §3.4 begin at 0. Assignments may be listed with `program_id`, `rep_id`, `plan_id`, `status`, and `acceptance_status` filters, and retrieved individually (a `Rep` caller sees only their own).

Acceptance is the rep's signature on the current plan document. The owning `Rep` — identified per §2.1, with foreign assignments hidden as `ERR_NOT_FOUND` — accepts from either `OFFERED` or `DECLINED`, provided the plan is still `PUBLISHED` (`ERR_PLAN_NOT_PUBLISHED`). Acceptance moves `acceptance_status` to `ACCEPTED`, pins `accepted_document_version` to the plan's current `document_version`, and — critically — releases every held credit: each `PENDING` credit entry of the assignment transitions to `POSTED` with `posted_period_index` set to the program's current period, and each such posting runs the full posting side effects of §3.4, earned increment and roll-up spawn included. Declining is the quieter act: from `OFFERED`, the owning rep moves `acceptance_status` to `DECLINED`, with no credit movement.

Termination ends both dimensions at once. A `CompAdmin` may terminate an assignment from `ACTIVE` regardless of its acceptance state; the lifecycle `status` becomes `TERMINATED`, the acceptance dimension freezes, and the assignment's `version` increments by 1. Termination unwinds the open period: every `PENDING` credit of the assignment is `REVERSED`, every `POSTED` credit whose `posted_period_index` is the program's current open period is likewise `REVERSED` with `current_period_earned_cents` decremented by each entry's amount as compensation — while credits already `LOCKED` by an earlier period close survive termination untouched. Finally, if the assignment is `draw_recoverable`, its remaining draw debt is forgiven in full: `draw_forgiven_cents` increases by `draw_outstanding_cents`, which is then zeroed.

### 3.4. Booking Sales Transactions and Allocating Credit

A `CompAnalyst` books a sale by submitting the `program_id`, an `external_ref`, the total `amount_cents` to be credited, the business `transaction_date`, and a `splits` array pairing each credited `rep_id` with a `split_bps` share. The `external_ref` is the client-supplied idempotency anchor: it must be unique within the program **regardless of transaction status** — even a long-cancelled transaction's reference cannot be reused — and a collision is rejected with `ERR_DUPLICATE_TRANSACTION_REF`. The amount must be positive — a non-positive `amount_cents`, a non-integer or non-positive `split_bps`, and a missing or empty split `rep_id` are all rejected with `ERR_INVALID_REQUEST` during basic body validation, ahead of the program-existence check. Following the ladder of §2.9, booking evaluates the structural checks before the referential ones: first the `split_bps` values — each a positive integer — must total exactly ten thousand basis points (`ERR_SPLIT_TOTAL_INVALID`); the `external_ref` uniqueness is enforced; then every rep named in the splits must hold an assignment with lifecycle `status` equal to `ACTIVE` in this program (`ERR_SPLIT_REP_INELIGIBLE`). A booked transaction is born in `BOOKED` status, with `booked_period_index` snapshotting the program's open period at creation; recall from §2.4 that `transaction_date` and `booked_period_index` are informational, and period attribution belongs to the credits' `posted_period_index`. Transactions may be listed with `program_id` and `status` filters.

Booking explodes the transaction into credit entries — one `DIRECT` entry per split — each recording its `transaction_id`, the credited rep's `assignment_id` and `rep_id`, a `credit_type` of `DIRECT`, and a computed `credit_amount_cents`. Allocation follows a deterministic rounding contract: for each split in request array order, the raw share is `amount_cents` multiplied by the split's `split_bps` and divided by ten thousand, and the split's credit is that raw share rounded half up to a whole cent — per-split rounding first, before any summation. The remainder, the transaction amount minus the sum of the rounded credits, may be positive or negative; when it is nonzero, the entire remainder is added to (or, when negative, subtracted from) the split with the largest `split_bps`, with ties broken in favor of the lowest array index. The invariant is exact: the `DIRECT` credits of a transaction always sum to `amount_cents` to the cent.

Whether a newborn credit posts immediately depends on the credited assignment's document posture. When the assignment is `ACTIVE`, its `acceptance_status` is `ACCEPTED`, and the plan is `PUBLISHED`, the entry lands directly in `POSTED` with `posted_period_index` set to the program's current period; otherwise it parks in `PENDING` and waits for the acceptance cascade of §3.3. Every posting — at creation or via acceptance — runs the same side effects. The assignment's `current_period_earned_cents` increases by the credit amount, raw, for both credit types. Then, for `DIRECT` entries only, the roll-up cascade fires: when the credited rep's `manager_id` is set and that manager holds an assignment with lifecycle `status` equal to `ACTIVE` on the **same plan**, the system spawns a `ROLLUP` credit entry for the manager — `parent_credit_id` pointing back at the spawning entry, `credit_amount_cents` equal to the spawning entry's amount multiplied by the plan's `rollup_rate_bps` and divided by ten thousand, rounded half up to a whole cent. The roll-up lands `POSTED` with the current `posted_period_index` when the manager's assignment is `ACCEPTED`, else `PENDING`, to be posted later by the manager's own acceptance cascade, at which point it runs these same posting side effects for the manager's assignment. Roll-up reaches exactly one hierarchy level — the direct manager only; a missing manager or a manager without an active assignment on that plan means no roll-up at all.

Two live indicators on each assignment are recomputed on every credit change — every event that creates a credit entry or alters a credit entry's status. The birth of a credit recomputes its assignment's indicators whether the entry lands `POSTED` or parks `PENDING`, and a spawned `ROLLUP` recomputes the manager assignment's indicators in either landing state, so a held `PENDING` credit feeds the provisional estimate from the moment it exists; reversal of a `PENDING` credit likewise withdraws it from that estimate, even though the earned counter never moves. `current_attainment_bps` converts the mode-filtered earned amount into basis points: the earned amount multiplied by ten thousand and divided by `quota_cents`, the quotient rounded down to a whole number with fractions discarded, and zero whenever the earned amount is zero or negative. The mode filter is the plan's `attainment_mode`: under `DIRECT_ONLY` only `DIRECT` entries count and roll-ups are excluded entirely, while under `INCLUDE_ROLLUP` both types count — so identical raw credits yield strictly higher attainment under `INCLUDE_ROLLUP` whenever any roll-up exists. `provisional_period_payout_cents` is the forward-looking estimate: the curve of §3.7 applied to the mode-filtered sum of `current_period_earned_cents` **plus** the `PENDING` credits of the assignment, themselves mode-filtered — under `DIRECT_ONLY` a held `ROLLUP` credit is excluded from the estimate just as posted roll-ups are — assuming future acceptance, with the plan cap, draws, and guarantees all ignored, since the provisional figure is a gross-curve estimate only. Individual credit entries can be retrieved, and the ledger listed with `transaction_id`, `assignment_id`, `rep_id`, `parent_credit_id`, and `status` filters.

### 3.5. Cancellations, Clawbacks, and Manual Adjustments

When a booked deal falls through, a `CompAnalyst` cancels it. Cancellation requires the transaction to still be `BOOKED`; a repeat attempt on an already-`CANCELLED` transaction is rejected with `ERR_TRANSACTION_ALREADY_CANCELLED`. Cancellation is a deep reversal: every credit entry of the transaction in `PENDING`, `POSTED`, or `LOCKED` moves to `REVERSED`, roll-up children included — reversing any entry likewise reverses its own `ROLLUP` children still in `PENDING` or `POSTED` under the same rules. Reversing a `PENDING` entry has no earned impact, since it never posted. Reversing a `POSTED` entry whose `posted_period_index` is the current open period decrements its assignment's `current_period_earned_cents` by the entry's amount; posted entries from earlier periods cannot exist, because period close has already locked them. Reversing a `LOCKED` entry — which only transaction cancellation can do, since locked credits survive assignment termination — does not rewrite the closed period; instead it creates a **clawback adjustment** on that entry's assignment: an `Adjustment` with `source` equal to `CLAWBACK`, `amount_cents` equal to the negated credit amount, `status` already `APPROVED`, and `period_index` set to the current open period, where it will settle at the next close. The clawback's `dispute_id` is null, its `created_by_user_id` is recorded as the literal string `system`, and its `reason` is a system-generated note identifying the reversed credit entry.

Corrections that are not tied to a cancelled transaction enter as manual adjustments. A `CompAnalyst` drafts one with the target `assignment_id`, a signed `amount_cents` — positive for a top-up, negative for a clawback-style reduction, but never zero (`ERR_ADJUSTMENT_AMOUNT_INVALID`) — and a free-text `reason`. The draft is stamped with `source` equal to `MANUAL`, `status` equal to `PENDING_APPROVAL`, `period_index` captured from the program's current open period (the settlement it will enter), and `created_by_user_id` from the caller. A third source, `DISPUTE`, exists but is never analyst-created; §3.6 covers it. Adjustments may be listed with `assignment_id`, `dispute_id`, `period_index`, and `status` filters.

Adjudication belongs to a `CompManager`, and only ever moves `PENDING_APPROVAL` adjustments — acting on an adjustment in any other state is an invalid transition. Approval requires the approver to differ from the adjustment's `created_by_user_id` (`ERR_SEGREGATION_OF_DUTIES`, evaluated after the state check per §2.9), and an approved adjustment enters its assignment's next period-close settlement through the statement's `adjustments_cents`. Rejection moves the adjustment to `REJECTED` and it never settles. Adjustments born `APPROVED` — the `DISPUTE` and `CLAWBACK` sources — skip this queue entirely.

### 3.6. Dispute Intake and Resolution

Reps contest their compensation through disputes. The filing `Rep` supplies the `assignment_id` — which must be their own, with foreign assignments hidden as `ERR_NOT_FOUND` — a target `period_index`, an optional `credit_entry_id` pinpointing a specific entry, a `reason`, and the `requested_amount_cents` correction. The `reason` is one of `CREDIT_MISSING`, `CREDIT_AMOUNT`, `QUOTA_ERROR`, `CURVE_MISAPPLIED`, `DRAW_ERROR`, or `OTHER`. Filing checks fire in ladder order: ownership first; then the filing window — the target period may be no earlier than two periods before the program's current period and no later than the current period, anything older or in the future rejected with `ERR_DISPUTE_WINDOW_CLOSED`; then the single-active-dispute rule — another dispute of the same assignment and period in `SUBMITTED` or `UNDER_REVIEW` blocks the filing with `ERR_DISPUTE_ALREADY_ACTIVE`; then referential coherence — a supplied `credit_entry_id` must resolve to an existing credit entry (`ERR_NOT_FOUND`) and must belong to the disputed assignment (`ERR_DISPUTE_CREDIT_ENTRY_MISMATCH`); and finally the amount — `requested_amount_cents` must be positive and no greater than the credited amount for that period, computed as the sum of the assignment's `POSTED` and `LOCKED` credits whose `posted_period_index` equals the target period (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`). A filed dispute begins in `SUBMITTED`. Disputes may be listed with `assignment_id`, `credit_entry_id`, and `status` filters.

Review is a fork-join managed by a `CompManager`. Moving a `SUBMITTED` dispute into `UNDER_REVIEW` signals active investigation. Approval is possible only from `UNDER_REVIEW` and takes an `approved_amount_cents` that must be positive and no greater than the dispute's `requested_amount_cents` (`ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT`); approval sets `approved_amount_cents`, moves the dispute to `APPROVED`, and immediately creates the compensating adjustment — `source` equal to `DISPUTE`, `amount_cents` equal to the approved amount, `status` already `APPROVED`, `period_index` set to the current open period, `dispute_id` linking back to the dispute, `created_by_user_id` stamped from the approving manager, and a system-generated `reason` identifying the dispute. Rejection is available from either `SUBMITTED` or `UNDER_REVIEW`, moves the dispute to `REJECTED`, and creates no adjustment. The owning rep may withdraw their own dispute from either `SUBMITTED` or `UNDER_REVIEW` — again with ownership hiding as `ERR_NOT_FOUND` — moving it to `WITHDRAWN`, likewise with no adjustment. `APPROVED`, `REJECTED`, and `WITHDRAWN` are all terminal.

Disputes gate the fiscal calendar: as §3.7 details, any dispute of the program still in `SUBMITTED` or `UNDER_REVIEW` blocks period close outright.

### 3.7. Period Close and Statement Settlement

Period close is the system's ops-run checkpoint, executed by a `CompAdmin` against a program. The request must carry `expected_program_version` per §2.7. Before the version check runs, the close's business guard is evaluated: if any dispute of the program is in `SUBMITTED` or `UNDER_REVIEW`, the close is rejected with `ERR_OPEN_DISPUTES_EXIST`; only once that guard passes does the stale-version rejection (`ERR_STALE_PROGRAM_VERSION`) apply.

A successful close performs four movements, in lockstep. It generates one `DRAFT` payout statement per assignment whose lifecycle `status` is `ACTIVE` — unique per assignment and period. It sweeps every credit entry of the program whose `posted_period_index` equals the closing period from `POSTED` to `LOCKED`. It resets each settled assignment's `current_period_earned_cents` to 0 and recomputes both live indicators of §3.4 against the reset counter — `PENDING` credits are untouched by the close and keep feeding the provisional estimate, so the indicators are refreshed, never hard-zeroed. And it advances the program: `current_period_index` increases by 1, `accrued_balance_cents` increases by the sum of the period's `net_payable_cents`, and the program's `version` increments by 1.

Each statement's money fields are computed by the settlement pipeline, whose evaluation order is pinned — every step consumes only the outputs of earlier steps. First, `earned_credits_cents` captures the assignment's `current_period_earned_cents` filtered by the plan's `attainment_mode`, exactly as §3.4 defines the mode filter. Second, `adjustments_cents` sums the `amount_cents` of every `APPROVED` adjustment of this assignment whose `period_index` equals the closing period. Third, `earned_total_cents` is the sum of the two. Fourth, attainment and gross: when the earned total is zero or negative, `attainment_bps` is 0, `gross_payout_cents` is 0, `payout_cap_applied` is false, and `deficit_cents` is the negated earned total (zero when the earned total is exactly zero); otherwise `attainment_bps` is the earned total multiplied by ten thousand and divided by `quota_cents`, rounded down to a whole number, and the gross comes from the quota-to-payout curve with the plan cap applied, `deficit_cents` being zero.

The **quota-to-payout curve** deserves its own precise statement, since both this settlement and the provisional estimate of §3.4 share it. Each tier of `curve_tiers` covers a marginal band of attainment measured in basis points — from its own `attainment_floor_bps` up to but not including the next tier's floor, with the highest tier open-ended. A floor maps to a credit threshold of the floor multiplied by `quota_cents` and divided by ten thousand, rounded down to a whole cent when the quotient is not exact; each band's credit span runs from its lower threshold to the next tier's lower threshold. Within each band, in ascending floor order, the band credit is the portion of the earned amount that falls inside the band — nothing below the lower threshold, and nothing beyond the band's width — and the band payout is that band credit multiplied by the tier's `rate_bps` and divided by ten thousand, rounded half up to a whole cent. The uncapped gross is the sum of all band payouts in that pinned ascending order. When the plan's `payout_cap_cents` is set, `payout_cap_applied` records whether the uncapped gross exceeded the cap, and the final `gross_payout_cents` is the smaller of the two; when no cap is set, the flag is false and the uncapped figure stands. The cap is always applied last, after summation.

Settlement then handles draws and guarantees. `draw_paid_cents` equals the assignment's `draw_amount_cents_per_period`, since the assignment is `ACTIVE` at close. When the assignment is `draw_recoverable`, the paid draw first accrues: `draw_outstanding_cents` increases by the paid amount. Recovery comes before guarantee: `draw_recovered_cents` is the smaller of the gross payout and the post-accrual `draw_outstanding_cents`, and the outstanding balance is reduced by the recovered amount. The guarantee floor then applies: `guarantee_trueup_cents` is the greater of zero and the assignment's `guarantee_amount_cents_per_period` minus the gross-net-of-recovery (gross payout minus draw recovered). `net_payable_cents` is the gross payout minus the draw recovered plus the guarantee true-up. A positive deficit settles into the draw ledger by recoverability: for a recoverable assignment the deficit is added to `draw_outstanding_cents`, and for a non-recoverable one it is added to `draw_forgiven_cents` instead. Finally the ledger syncs: `lifetime_earned_cents` increases by the earned total, `lifetime_paid_cents` increases by the net payable, and the open-period earned counter resets as described above.

The draw ledger maintains one invariant at every observable instant: `draw_outstanding_cents` equals the recoverable draws paid across all of the assignment's closed statements, minus the `draw_recovered_cents` across those statements, minus the `draw_forgiven_cents` recorded against the assignment. Termination of a recoverable assignment folds the entire outstanding balance into `draw_forgiven_cents` and zeroes the outstanding amount, per §3.3. Draws on a non-recoverable assignment are paid but never enter this ledger at all.

Statements rest in `DRAFT` until a `CompManager` approves them — approval moves a statement from `DRAFT` to `APPROVED` and is the prerequisite for payroll export. Statements may be listed with `assignment_id`, `period_index`, and `status` filters, and retrieved individually (a `Rep` caller sees only their own).

### 3.8. Payroll Export and Accrual Relief

Exporting a payout file is the final act of a period, performed by a `CompAdmin` supplying the `program_id` and the closed `period_index`. The temporal guard fires first: the period must already be closed — a `period_index` that has reached or passed the program's `current_period_index` is rejected with `ERR_PAYROLL_PERIOD_NOT_CLOSED`, while any lower `period_index`, even one below 1 that names no real period, passes the guard. One export exists per program and period; a second attempt is rejected with `ERR_PAYROLL_EXPORT_EXISTS`. And every statement of that program and period must already be `APPROVED` — a single lingering `DRAFT` statement blocks the export with `ERR_STATEMENTS_NOT_APPROVED`.

A successful export transitions every approved statement of the program and period from `APPROVED` to `EXPORTED`, collects their identifiers into the export's `statement_ids` in the order the statements were created, records their number as `statement_count`, and sums their `net_payable_cents` into `total_cents` — a program and period with no statements at all still exports successfully, recording an empty `statement_ids`, a `statement_count` of 0, and a `total_cents` of 0. The export record also carries the `program_id` and `period_index` it was requested for. That total relieves the program's accrual: `accrued_balance_cents` decreases by `total_cents`, completing the liability cycle that period close began. Recall from §2.5 that a `PayrollExport` is immutable — it carries `id` and `created_at` only. The exports of a program may be listed at the program-scoped collection.

### 3.9. Plan Effectiveness Analytics

Compensation leadership reads plan health through the effectiveness report, computed on read for a given plan. The source set is every payout statement whose assignment's `plan_id` is the plan in question — statements of any status, `DRAFT`, `APPROVED`, or `EXPORTED`, across all closed periods. The report carries the `plan_id`; `assignments_count`, the count of all assignments of the plan regardless of status; `statements_count`, the size of the source set; `avg_attainment_bps`, the sum of the statements' `attainment_bps` divided by the statement count and rounded down to a whole number — zero when no statements exist; `total_earned_cents`, the sum of `earned_total_cents`; and `total_payout_cents`, the sum of `net_payable_cents`. A `distribution` object buckets statements by attainment with inclusive lower bounds and exclusive upper bounds: `LT_8000` counts attainment below 8000 basis points, `B8000_10000` counts attainment of at least 8000 and below 10000, and `GTE_10000` counts attainment of at least 10000 — quota achieved or better. Sums and counts are order-insensitive, so no tie-breaking applies.

## 4. Endpoint Definitions

Operations that create new resources — a program, plan, rep, assignment, transaction, manual adjustment, dispute, or payroll export — return a `201 Created` status code. Operations that modify an existing resource — publishing, revising, or archiving a plan, updating a rep, accepting, declining, or terminating an assignment, cancelling a transaction, approving or rejecting an adjustment, starting review on, approving, rejecting, or withdrawing a dispute, approving a statement, or closing a period — return a `200 OK` status code. All retrievals and listings return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/programs` | Create a compensation program (period counter starts at 1, accrual at 0) | CompAdmin |
| GET | `/programs/{programId}` | Get a program (period counter, accrual balance, version) | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/programs/{programId}/close-period` | Settle the current period: statements, credit lock, epoch advance; OCC-guarded | CompAdmin |
| GET | `/programs/{id}/payroll-exports` | List payroll exports of a program | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/plans` | Create a plan in DRAFT with curve tiers and document_version 1 | CompAdmin |
| GET | `/plans/{planId}` | Get a plan | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/plans` | List plans | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/plans/{planId}/publish` | Publish a DRAFT plan (publisher must differ from creator) | CompAdmin |
| POST | `/plans/{planId}/revise` | Issue a new plan document version (OCC); re-offers documents to active assignments | CompAdmin |
| POST | `/plans/{planId}/archive` | Archive a plan with no ACTIVE assignments | CompAdmin |
| GET | `/plans/{planId}/effectiveness` | Plan effectiveness analytics | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/reps` | Create a rep; manager must be same-program and the chain acyclic | CompAdmin |
| GET | `/reps/{repId}` | Get a rep | CompAdmin, CompAnalyst, CompManager, Rep |
| PUT | `/reps/{repId}` | Update a rep's name or manager; hierarchy checks re-run | CompAdmin |
| GET | `/reps` | List reps (program and manager filters) | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/assignments` | Assign a rep to a plan with quota/draw/guarantee; plan must be PUBLISHED | CompAdmin |
| GET | `/assignments/{assignmentId}` | Get an assignment (Rep callers: own only, else 404) | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/assignments` | List assignments | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/assignments/{assignmentId}/accept` | Owning rep accepts the current plan document; posts held PENDING credits | Rep |
| POST | `/assignments/{assignmentId}/decline` | Owning rep declines the offered plan document | Rep |
| POST | `/assignments/{assignmentId}/terminate` | Terminate an assignment; reverses unposted/current-period credits, forgives recoverable draw debt | CompAdmin |
| POST | `/transactions` | Book a sales transaction; allocates DIRECT credits per split rounding | CompAnalyst |
| GET | `/transactions/{transactionId}` | Get a transaction | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/transactions` | List transactions | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/transactions/{transactionId}/cancel` | Cancel a booked transaction; reverses all credits; locked credits spawn clawbacks | CompAnalyst |
| GET | `/credit-entries/{creditEntryId}` | Get a credit entry (Rep callers: own credits only) | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/credit-entries` | List credit entries with filters | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/adjustments` | Create a MANUAL adjustment (PENDING_APPROVAL) against the open period | CompAnalyst |
| GET | `/adjustments/{adjustmentId}` | Get an adjustment | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/adjustments` | List adjustments with filters | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/adjustments/{adjustmentId}/approve` | Approve a PENDING_APPROVAL manual adjustment (approver must differ from creator) | CompManager |
| POST | `/adjustments/{adjustmentId}/reject` | Reject a PENDING_APPROVAL manual adjustment | CompManager |
| POST | `/disputes` | Owning rep files a dispute for a period within the filing window | Rep |
| GET | `/disputes/{disputeId}` | Get a dispute (Rep callers: own disputes only) | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/disputes` | List disputes with filters | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/disputes/{disputeId}/start-review` | Move a submitted dispute into review | CompManager |
| POST | `/disputes/{disputeId}/approve` | Approve a dispute under review with an approved amount; spawns an APPROVED DISPUTE adjustment | CompManager |
| POST | `/disputes/{disputeId}/reject` | Reject a dispute (from SUBMITTED or UNDER_REVIEW); no adjustment | CompManager |
| POST | `/disputes/{disputeId}/withdraw` | Owning rep withdraws a dispute (from SUBMITTED or UNDER_REVIEW); no adjustment | Rep |
| GET | `/statements/{statementId}` | Get a payout statement (Rep callers: own statements only) | CompAdmin, CompAnalyst, CompManager, Rep |
| GET | `/statements` | List payout statements with filters | CompAdmin, CompAnalyst, CompManager, Rep |
| POST | `/statements/{statementId}/approve` | Approve a DRAFT statement (prerequisite for payroll export) | CompManager |
| POST | `/payroll-exports` | Export all APPROVED statements of a closed (program, period) to payroll; one export per program+period | CompAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_PLAN_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_PLAN_NOT_PUBLISHED` | 409 Conflict |
| `ERR_PLAN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_PLAN_HAS_ACTIVE_ASSIGNMENTS` | 409 Conflict |
| `ERR_CURVE_TIERS_INVALID` | 400 Bad Request |
| `ERR_DUPLICATE_EMPLOYEE_REF` | 409 Conflict |
| `ERR_REP_HIERARCHY_CYCLE` | 409 Conflict |
| `ERR_MANAGER_PROGRAM_MISMATCH` | 409 Conflict |
| `ERR_ASSIGNMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_QUOTA_INVALID` | 400 Bad Request |
| `ERR_SPLIT_TOTAL_INVALID` | 422 Unprocessable Entity |
| `ERR_SPLIT_REP_INELIGIBLE` | 409 Conflict |
| `ERR_DUPLICATE_TRANSACTION_REF` | 409 Conflict |
| `ERR_TRANSACTION_ALREADY_CANCELLED` | 409 Conflict |
| `ERR_DISPUTE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_DISPUTE_WINDOW_CLOSED` | 409 Conflict |
| `ERR_DISPUTE_AMOUNT_EXCEEDS_CREDIT` | 409 Conflict |
| `ERR_DISPUTE_CREDIT_ENTRY_MISMATCH` | 409 Conflict |
| `ERR_ADJUSTMENT_AMOUNT_INVALID` | 400 Bad Request |
| `ERR_OPEN_DISPUTES_EXIST` | 409 Conflict |
| `ERR_STATEMENTS_NOT_APPROVED` | 409 Conflict |
| `ERR_PAYROLL_EXPORT_EXISTS` | 409 Conflict |
| `ERR_PAYROLL_PERIOD_NOT_CLOSED` | 409 Conflict |

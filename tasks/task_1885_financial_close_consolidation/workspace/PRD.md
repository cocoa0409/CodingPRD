# Financial Close & Consolidation API — Product Requirements Document

## 1. Introduction

Every month-end, a corporate accounting department runs the same high-stakes relay: subledgers must be cut off on time, accruals estimated and trued up against actuals, journal entries documented and approved under segregation of duties, accounts reconciled with their unreconciled items aged, intercompany balances eliminated across legal entities, foreign-currency results translated into the group's reporting currency, and period-over-period movements explained before the books can be locked, reviewed, and finalized. When any link in that chain slips, the close slips with it — and nobody can say precisely which entity, task, or journal entry is holding the group up.

This document specifies the Financial Close & Consolidation API, the system of record for that process. The API orchestrates the close as a dependency graph of tasks fanning out across a consolidation tree of legal entities, enforces preparer/approver separation on every judgmental artifact, keeps a tamper-evident audit trail of every material event, and derives the period's lock posture from the state of its entity rows rather than from free-standing flags. It is written for the engineers who will implement the service: §2 states the system-wide contracts, §3 walks the business workflows in close-process order, §4 enumerates the HTTP surface, and §5 catalogs the error identifiers.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, representations, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Four roles exist, spelled exactly as follows: `Controller`, `Preparer`, `Approver`, and `Auditor`. A request with a missing or invalid role header — or, where a role requires it, a missing user header — is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The roles divide the close work along segregation-of-duties lines. A `Controller` is the corporate controller: owner of the close calendar, close periods, legal-entity registrations, FX rates, locks and reopens, finalization, flux adjudication, and task waivers, as well as the test-driving endpoints (the logical clock and the subledger feed). A `Preparer` is an entity accountant: runs subledger cutoffs, drafts journal entries and accrual estimates, performs reconciliations, works the close tasks assigned to them, proposes and matches intercompany elimination pairs, and writes flux explanations. An `Approver` is a senior accountant or manager who confirms cutoffs, approves or rejects journal entries, verifies or rejects supporting documents, and writes off reconciling items — and never performs the preparer step on the same artifact. An `Auditor` is a read-only post-close reviewer with access to the full read surface, including the audit event trail, and no mutation rights whatsoever.

Identity for all four roles is opaque. When `X-User-Role` is `Controller`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The same holds when `X-User-Role` is `Preparer`, when it is `Approver`, and when it is `Auditor`: in every case the header value is an opaque operator identifier, never the `id` of a stored resource. The server may record the value — for example as `assignee_user_id` on a close task, as `preparer_user_id` or `approver_user_id` on a journal entry, as `uploaded_by_user_id` or `verified_by_user_id` on a supporting document, as `reviewed_by_user_id` or `cleared_by_user_id` on a reconciliation, or as `actor_user_id` on an audit event — but it never compares the header against any entity's `id` for ownership.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter skips that many items before returning the page and defaults to 0.

Unless otherwise specified, every list endpoint returns its resources sorted by creation timestamp in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — close periods, entities, entity-periods, tasks, cutoffs, accrual estimates, journal entries and their lines, supporting documents, reconciliations and their items, elimination pairs, flux explanations, and FX rates — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted identifier formatted as a UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification; refreshed on any change to the resource, including changes driven by recomputed derived fields.
- **`version` (integer):** a system-managed integer that increments by one on every mutation, including mutations caused by cascade side effects originating on other resources.

One resource breaks this pattern deliberately. The audit-trail `CloseEvent` is append-only: it carries only `id` and `created_at`. Both `updated_at` and `version` are absent on `CloseEvent` — an event, once written, is never modified.

### 2.5. The Logical Clock

All time-dependent behavior in the system — period-open eligibility, reconciliation staleness, item aging, task lateness — reads a single server-side logical clock, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must not fall back to wall-clock time before any set call has been made. A `Controller`-only test-driving capability sets the clock to a caller-supplied `to_iso8601` instant and answers with the resulting `now_iso8601`. Each such set immediately re-evaluates the automatic staleness transition for reconciliations still `OPEN` and the `is_late` flags of close tasks against the new current instant.

### 2.6. Monetary Units, Precision, and Rounding

All monetary amounts are represented as integers in minor currency units — cents for USD and EUR, and the equivalent smallest unit elsewhere — which is why amount-bearing field names end in `_minor`. No monetary calculation ever rounds to a fractional result; where a division or a rate multiplication is required, the result is rounded half up to integer minor units. Percentage-valued results are the exception: they are rounded half up to exactly two decimal places, and any threshold comparison against such a percentage uses the rounded value.

Where a calculation has multiple components, rounding is applied per component before the components are summed — the temporal translation variant rounds the monetary and non-monetary legs separately, and intercompany matching rounds each side independently — never rounding only the final sum. Multi-hop consolidation rounds half up at each hop: full precision is carried within a single hop and rounding happens only when a hop's result is written.

### 2.7. Segregation of Duties

Judgmental artifacts in the close require a four-eyes discipline, and the API enforces it mechanically. Five actor-vs-recorder boundaries exist, and breaching any of them is rejected with `ERR_SOD_VIOLATION` (HTTP 409):

- The `Approver` who approves a journal entry must differ from the entry's recorded `preparer_user_id`.
- The `Preparer` who posts an approved journal entry must differ from its recorded `approver_user_id`.
- The `Approver` who confirms a subledger cutoff must differ from the `Preparer` who executed the cut.
- The `Preparer` who clears a reconciliation must differ from its recorded `reviewed_by_user_id`.
- The `Approver` who verifies a supporting document must differ from the document's `uploaded_by_user_id` whenever the uploader holds an approver-capable role.

A complementary ownership rule, not a segregation rule, governs rework: only the original preparer of a rejected journal entry may send it back to draft, so the rework actor's `X-User-ID` must equal the entry's `preparer_user_id`.

### 2.8. Optimistic Concurrency Control on Period-Level Mutations

Four `Controller` operations on a close period — soft-locking it, hard-locking it, reopening it, and finalizing it — each require a non-optional input field `expected_close_period_version` carrying the caller's last observed `version` of the period. If that value does not match the period's current `version`, the request is rejected with `ERR_STALE_PERIOD_VERSION` (HTTP 412). The rationale differs per operation, but the mechanism is identical: soft-locking against an advanced version is refused because a journal entry posted in the interim has bumped trial balances and the lock decision must be taken against the freshest aggregate; hard-locking is refused because the caller's snapshot of entity readiness stops being authoritative once any mutation, including a cascaded entity-period change, has advanced the period version; reopening is refused because a later soft-lock attempt or task waiver may already have changed the aggregate on which the reopen decision was based; and finalizing is refused because finalization snapshots close metrics computed from current aggregate state the caller has not observed. Endpoints other than these four do not accept a version field.

### 2.9. Validation Order and Nested Resource Retrieval

Requests targeting nested resources are validated strictly left to right along the path: the existence and parentage of each identifier is confirmed in path order — close period before entity-period, entity-period before its child collection — and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not exist or does not belong to the declared parent. Existence is never checked for a child before its ancestors.

On top of path resolution, every request passes a fixed, eleven-tier validation order, evaluated in this sequence so that earlier failures mask later ones deterministically:

1. Authentication of the headers — failures surface `ERR_UNAUTHENTICATED`.
2. Role authorization for the endpoint — `ERR_FORBIDDEN`.
3. Left-to-right existence and parentage of path identifiers — `ERR_NOT_FOUND`.
4. Optimistic-concurrency version match, on the four endpoints that declare it — `ERR_STALE_PERIOD_VERSION`.
5. State-machine legality: the requested transition must be permitted from the target resource's current state, on all action endpoints — `ERR_INVALID_STATE`.
6. Segregation of duties, on the approve, post, confirm, clear, and verify endpoints — `ERR_SOD_VIOLATION`.
7. Close-posture and period-lock gates: no journal drafting, submission, or posting, no reconciliation change, and no task start on a soft-locked, hard-locked, or finalized period or entity-period — `ERR_PERIOD_LOCKED`, with `ERR_PERIOD_HARD_LOCKED` where the hard-lock-specific rule applies.
8. Structural integrity: task dependencies must stay acyclic (`ERR_TASK_DEPENDENCY_CYCLE`), the entity hierarchy must stay acyclic (`ERR_ENTITY_HIERARCHY_CYCLE`), a submitted journal entry must balance (`ERR_JE_UNBALANCED`), an elimination pair must span two distinct entities (`ERR_ELIM_SAME_ENTITY`), and a document hash must not repeat on one entry (`ERR_DOC_DUPLICATE`).
9. Temporal windows: an entry date inside its period (`ERR_JE_OUT_OF_PERIOD`), a cutoff instant inside its allowed window (`ERR_CUTOFF_OUT_OF_PERIOD`), a period not opened before its start (`ERR_PERIOD_NOT_YET_OPEN`), and write-off aging gates (`ERR_WRITEOFF_TOO_YOUNG`).
10. Cross-entity prerequisites: a required FX rate present (`ERR_FX_RATE_MISSING`), a translation run existing and fresh (`ERR_TRANSLATION_NOT_RUN`, `ERR_TRANSLATION_STALE`), a linked reconciliation cleared before flux acceptance (`ERR_FLUX_RECON_NOT_CLEARED`), and task assignee matching (`ERR_NOT_TASK_ASSIGNEE`).
11. Aggregate and fiscal gates: reconciliations within tolerance or cleared (`ERR_RECON_OUTSTANDING`), material accrual true-ups posted (`ERR_ACCRUAL_MATERIAL_TRUEUP`), elimination residuals within tolerance (`ERR_ELIM_RESIDUAL_EXCEEDED`), write-offs below materiality (`ERR_WRITEOFF_ABOVE_MATERIALITY`), no open tasks at readiness (`ERR_OPEN_CLOSE_TASKS`), at least one subledger cutoff present (`ERR_NO_SUBLEDGER_CUTOFF`), no zero-delta accrual posting from the trued-up state (`ERR_ACCRUAL_ZERO_DELTA`), required narrative fields present (`ERR_EXPLANATION_REQUIRED`, `ERR_REJECTION_REASON_REQUIRED`, `ERR_REOPEN_REASON_REQUIRED`, `ERR_DOC_REQUIRED`, `ERR_DOC_NOT_VERIFIED`), and only one period open at a time (`ERR_PERIOD_ALREADY_OPEN`).

### 2.10. Close Posture, Locks, and Immutability

A close period carries two orthogonal state dimensions. Its `status` walks a linear lifecycle — `SCHEDULED`, then `IN_PROGRESS`, then `UNDER_REVIEW`, and finally the terminal `FINALIZED`. Its `close_posture` is a compound, derived dimension — `OPEN`, `SOFT_CLOSED`, `HARD_CLOSED`, or `REOPENED` — recomputed from the lock states of its entity rows and from explicit lock and reopen actions; the posture recomputes on every entity-period lock transition and on every reopen. A period may therefore be `IN_PROGRESS` under several different postures, and posture, not status, is what gates operational work such as task starts.

Entity-periods advance through `PREPARING`, `SUBLEDGER_CUT`, `RECONCILED`, `READY_FOR_CONSOL`, `SOFT_LOCKED`, and the terminal `HARD_LOCKED`. `REOPENED` is a sideways, non-terminal state reachable only from `SOFT_LOCKED` via a period reopen; from `REOPENED` an entity-period must re-walk `RECONCILED`, then `READY_FOR_CONSOL`, then `SOFT_LOCKED`. Once an entity-period reaches `HARD_LOCKED`, its row becomes immutable: every child-creation endpoint under it rejects with `ERR_PERIOD_HARD_LOCKED`. More broadly, any mutation of journal entries, reconciliations, tasks, or accruals against a soft-locked, hard-locked, or finalized period or entity-period is refused with `ERR_PERIOD_LOCKED`.

Two staleness flags guard the consolidation numbers. Posting a journal entry, and likewise reopening a period, marks the affected entity-period's `translated_balance_minor` and `cta_minor` as stale, and readiness gates will refuse to proceed until a fresh translation run has been executed.

### 2.11. The Append-Only Close Event Trail

Every material occurrence in the close is recorded as a `CloseEvent` row scoped to a close period via `close_period_id`, and optionally to one entity-period via `entity_period_id`, which is null for period-level events. The `event_kind` is one of exactly twelve values: `PERIOD_OPENED`, `SUBLEDGER_CUT`, `ACCRUAL_POSTED`, `JE_POSTED`, `RECON_CLEARED`, `TASK_DONE`, `TRANSLATION_RUN`, `ELIMINATION_RUN`, `SOFT_LOCK`, `HARD_LOCK`, `REOPENED`, and `REVIEW_FINALIZED`. Each event records the `actor_user_id` — the `X-User-ID` that caused the event, or the literal string `system` for machine-driven transitions — and a `detail` string carrying structured JSON of the before-and-after values. The trail is strictly append-only (see §2.4 for its reduced field set). The period-level audit listing is available to `Controller`, `Approver`, and `Auditor`; the entity-period-scoped listing is available to all four roles.

## 3. Business Logic & Workflows

### 3.1. Registering the Consolidation Tree and Opening the Close

Before any close can begin, a `Controller` registers the group's legal entities. Each entity is registered with a unique `entity_code` (such as US100 or EU200 — registering a duplicate code is refused), a display `name`, a `functional_currency` of `USD`, `EUR`, `GBP`, or `JPY`, an optional `parent_entity_id` pointing at another entity, an `ownership_pct` recording the parent's ownership percentage, and a `translation_method` of `CURRENT_RATE` or `TEMPORAL`. A null `parent_entity_id` marks the consolidation root; otherwise the references form a tree, and any registration whose parent chain would introduce a cycle is rejected with `ERR_ENTITY_HIERARCHY_CYCLE`. The ownership percentage must be greater than zero and no more than one hundred; anything below one hundred creates a non-controlling interest split downstream. The system derives `consolidation_tier` as the depth in the tree — the root sits at tier zero — and uses it later to order bottom-up translation chains. The optional `is_elimination_counterparty` flag, which defaults to true when omitted, marks whether the entity participates in intercompany eliminations. The entity listing can be filtered by `parent_entity_id` to walk the tree one level at a time.

With entities in place, a `Controller` creates a close period by supplying `fiscal_year` (for example 2026), `fiscal_period` (an integer from 1 through 13 within the year), `period_start` and `period_end` instants in UTC with the end strictly after the start, the consolidation `reporting_currency` (again one of `USD`, `EUR`, `GBP`, `JPY`), and `materiality_threshold_minor` — the materiality threshold expressed in reporting-currency minor units, at or above which flux explanations and accrual true-ups become mandatory throughout the period. A freshly created period starts in `SCHEDULED` status with its posture computed as `OPEN`.

Opening the period is a deliberate act. The logical clock must have reached `period_start`; an earlier attempt is rejected with `ERR_PERIOD_NOT_YET_OPEN`. Only one close may be open at a time: if any other period is currently `IN_PROGRESS` or `UNDER_REVIEW`, the open attempt is rejected with `ERR_PERIOD_ALREADY_OPEN`. A successful open moves the period from `SCHEDULED` to `IN_PROGRESS`, sets the posture to `OPEN`, increments the period's `version` by one, appends a `PERIOD_OPENED` audit event, and fans out one entity-period row per registered entity — every entity receives a row, elimination counterparty or not — each starting in `PREPARING` and recording both the `close_period_id` it belongs to and the `entity_id` it tracks. Entity-period listings can be filtered by `close_period_id`, `entity_id`, or `status` to slice the close workload.

FX rates are registered per period, scoped so that each close works against its own rate sheet. A `Controller` registers each rate with `from_currency`, `to_currency`, a `rate_kind` of `PERIOD_END`, `AVERAGE`, or `HISTORICAL`, a multiplicative `rate` that must be greater than zero (the target amount is the source amount multiplied by the rate), and an `effective_at` instant; historical rates are later selected by the latest `effective_at` on or before the transaction date in question. The period's rate listing can be filtered by `from_currency`, `to_currency`, or `rate_kind`.

### 3.2. Building the Close Calendar: Tasks and the Dependency DAG

A close is executed as a directed acyclic graph of tasks. A `Controller` creates each close task on a period with an optional `entity_period_id` (null marks a period-level task), a stable `task_key` such as `SL_CUTOFF`, `ACCRUALS`, `RECON_AR`, `TRANSLATE`, `ELIMINATE`, `CONSOLIDATE`, `FLUX`, or `REVIEW`, a human-readable `title`, an optional `depends_on_task_ids` array naming the tasks that must all finish first (defaulting to an empty array), the `assignee_user_id` of the accountable `Preparer`, and `due_offset_hours` — the number of hours after `period_start` at which the task comes due. Dependencies must form a DAG: any `depends_on_task_ids` set that introduces a cycle into the period's task graph is rejected with `ERR_TASK_DEPENDENCY_CYCLE`.

A task's initial `status` is `READY` when it declares no dependencies and `BLOCKED` otherwise. From then on the system maintains the `BLOCKED` → `READY` frontier automatically: the instant every task named in `depends_on_task_ids` has reached `DONE` or `WAIVED`, the waiting task flips to `READY` without any client action.

Only the accountable preparer may work a task. Starting a task moves it from `READY` to `IN_PROGRESS` and requires the caller's `X-User-ID` to equal the task's `assignee_user_id` — anyone else is rejected with `ERR_NOT_TASK_ASSIGNEE` — and requires the period's `close_posture` to be `OPEN` or `REOPENED`, since work must never begin under a lock (`ERR_POSTURE_NOT_OPEN`). A started task may be sent back from `IN_PROGRESS` to `READY` by its assignee as a rework loop, again assignee-gated.

Completing a task is likewise restricted to its assignee and carries task-key-specific completion gates: a task whose `task_key` begins with `RECON_` requires the linked reconciliation to be `CLEARED`; a `TRANSLATE` task requires that a translation run has occurred this period; an `ELIMINATE` task requires all elimination pairs to be resolved. A successful completion moves the task to `DONE`, stamps `completed_at` with the current instant (it remains null in every other state), recomputes `is_late`, appends a `TASK_DONE` event, and cascades down the graph: every dependent task whose dependencies are now entirely `DONE` or `WAIVED` flips from `BLOCKED` to `READY`, fanning out the next layer of work. A task's `is_late` flag is true when it reached `DONE` after the instant `due_offset_hours` hours past `period_start`, or when it is still open past that same instant.

Waiving is the `Controller`-only escape hatch for non-critical work, and it is audited. A `READY` task may be moved to `WAIVED` only while the posture is `OPEN` or `REOPENED`, and only when its `task_key` is not one of the critical-path keys `TRANSLATE`, `ELIMINATE`, or `CONSOLIDATE` — waiving a critical task is rejected with `ERR_TASK_NOT_WAIVABLE`. A waiver counts as satisfaction: dependents re-evaluate and unblock exactly as if the task had been completed. For monitoring, each entity-period surfaces `open_task_count`, the number of its tasks not yet in `DONE` or `WAIVED`, and the period's task listing can be filtered by `status`.

### 3.3. Subledger Cutoff and Boundary Accounting

Subledger transactions exist outside the business surface: they enter the system only through a declared, `Controller`-only seed feed carrying `entity_id`, `subledger`, `ts`, `amount_minor`, and `account_code`, and the feed answers with a `subledger_txn_id` for each injected transaction. There is no other way to create subledger transactions, so every cutoff computation is replayable from that feed.

Against each entity-period, a `Preparer` declares cutoff specifications. Each spec names the `subledger` being cut off — one of `AR`, `AP`, `INVENTORY`, `FIXED_ASSETS`, or `PAYROLL` — a `cutoff_at` instant, and a `cutoff_rule` of `INCLUSIVE` or `EXCLUSIVE_AT_END` governing transactions that land exactly on the boundary. A new cutoff starts in `OPEN`.

Executing the cut is allowed only while the parent entity-period is still `PREPARING`, and `cutoff_at` must fall strictly after `period_start` and no later than `period_end`; a cutoff instant outside that window is rejected with `ERR_CUTOFF_OUT_OF_PERIOD`. The execution computes two values. `pre_cutoff_total_minor` is the sum of transaction amounts belonging to the period under the declared rule, where period membership additionally requires a timestamp at or after `period_start`: under `INCLUSIVE`, transactions strictly before `cutoff_at` are included and a transaction exactly at `cutoff_at` is excluded, belonging to the next period; under `EXCLUSIVE_AT_END`, transactions at or before `cutoff_at` are included, so boundary transactions sit inside the total. `boundary_transaction_count` counts the transactions whose timestamp equals `cutoff_at` exactly — under both rules — so the two rules disagree on precisely the boundary set: identical subledger data yields totals differing by the sum of the boundary transactions. Ordering never affects the sum itself; it matters only for audit replay, which walks transactions by timestamp ascending with ties broken by creation timestamp ascending.

Confirmation is the approver's gate. An `Approver` confirms a `CUT` cutoff, and the confirming user must differ from the `Preparer` who executed the cut — a match is a segregation-of-duties breach rejected with `ERR_SOD_VIOLATION`. Confirmation carries a bubble-up cascade: the moment every cutoff of an entity-period has reached `CONFIRMED`, the entity-period itself advances from `PREPARING` to `SUBLEDGER_CUT`, every accrual estimate on it has its provisional amount computed (§3.4), and a `SUBLEDGER_CUT` audit event is appended. An entity-period with no cutoffs at all cannot leave `PREPARING`; any attempt to advance it in that state is rejected with `ERR_NO_SUBLEDGER_CUTOFF`.

### 3.4. Accrual Estimates and the Materiality True-Up Gate

Accrual estimates bridge the gap between subledger cutoff and known actuals. A `Preparer` creates each estimate against a cutoff by supplying the `subledger_cutoff_id` it is computed against, the target `account_code` (for example 6100-SALARIES), and a `basis` of `PRIOR_3M_AVG`, `PRIOR_PERIOD`, or `DAYS_OUTSTANDING`. The estimate starts in `PROVISIONAL`, and its `provisional_amount_minor` is computed in functional-currency minor units when the entity-period reaches `SUBLEDGER_CUT`. An estimate created after its entity-period has already entered `SUBLEDGER_CUT` is not stuck: while the estimate is still `PROVISIONAL`, a `Preparer` may ask the system to recompute `provisional_amount_minor` on demand.

The three bases compute the provisional differently. Under `PRIOR_3M_AVG`, the system sums the account's posted journal-entry net amounts across the three immediately preceding close periods, divides by three, and rounds half up once at the very end — the periods are summed first, then divided, then rounded, never rounded per period and then averaged. This basis requires exactly three prior periods; when fewer exist, it falls back to the single-prior-period computation. Under `PRIOR_PERIOD`, the provisional is simply the prior single period's posted net amount, with no division at all. Under `DAYS_OUTSTANDING`, a daily run rate is formed by dividing the cutoff's `pre_cutoff_total_minor` by the number of elapsed days in the period, and the provisional is that run rate multiplied by the number of days between `cutoff_at` and `period_end`, rounded half up.

True-up replaces the estimate with the actual. A `Preparer` supplies `final_amount_minor` — null until that moment — while the parent entity-period is in `SUBLEDGER_CUT`, `RECONCILED`, or `REOPENED`, moving the estimate from `PROVISIONAL` to `TRUED_UP`. The system computes `true_up_delta_minor` as the final amount minus the provisional amount, preserving sign. This delta is the materiality trip-wire: when its absolute value is at or above the period's `materiality_threshold_minor`, the entity-period is blocked from advancing to `RECONCILED` until a balancing journal entry posts, and the block surfaces at mark-reconciled time as `ERR_ACCRUAL_MATERIAL_TRUEUP`.

Posting closes the estimate. From `TRUED_UP`, posting requires a non-zero delta: posting a zero delta from that state is rejected with `ERR_ACCRUAL_ZERO_DELTA`, because a zero-delta accrual is meant to be closed directly from `PROVISIONAL`. A non-zero post creates a balancing journal entry of `je_type` `ACCRUAL` in `DRAFT` on the same entity-period, with a single `DEBIT` line and a single `CREDIT` line, each for the absolute delta, booked to the estimate's `account_code` and the accrual-contra account; an `ACCRUAL_POSTED` event is appended. From `PROVISIONAL`, posting with a zero delta — the final amount was never supplied, or equals the provisional — moves the estimate straight to the terminal `POSTED` state and creates no journal entry at all.

### 3.5. Journal Entries and Supporting Documentation

Journal entries are the ledger's raw material, drafted by a `Preparer` on an entity-period with a `je_type` of `MANUAL`, `ACCRUAL`, `RECLASS`, `ELIMINATION`, `CONSOLIDATION_ADJ`, or `TOP_SIDE`; an `entry_date`; the `functional_currency` the lines are denominated in; and inline `lines`. The `entry_date` must fall on or after `period_start` and on or before `period_end` of the parent close period — anything outside that window is rejected with `ERR_JE_OUT_OF_PERIOD` — and the entry's `functional_currency` must equal the entity's own functional currency, or the create is rejected with `ERR_JE_CCY_MISMATCH`. The creating user's header is captured into `preparer_user_id` at creation, the entry starts in `DRAFT`, its `doc_state` parallel dimension starts at `DOC_MISSING`, and `debit_total_minor` and `credit_total_minor` are computed from the lines.

Each line carries a 1-based `line_no` sequencing it within the entry, an `account_code`, a `direction` of `DEBIT` or `CREDIT`, an absolute `amount_minor` in functional-currency minor units that must be greater than zero (a non-positive line amount is rejected with `ERR_LINE_NOT_POSITIVE`), an optional `memo`, and a `counterparty_entity_id` that is set only on `ELIMINATION`-type lines to name the intercompany counterparty entity. Every line records the `journal_entry_id` of its parent entry; lines can be listed per journal entry, and the set of lines naming a given entity as intercompany counterparty can be listed from the entity side. Journal-entry listings on an entity-period can be filtered by `status` or by `je_type`.

Approval follows a strict chain with segregation at every link. Submission moves an entry from `DRAFT` to `SUBMITTED` and enforces three gates: `debit_total_minor` must equal `credit_total_minor` with both totals greater than zero, else `ERR_JE_UNBALANCED`; the parent entity-period must be in `PREPARING`, `SUBLEDGER_CUT`, `RECONCILED`, or `REOPENED`, else `ERR_PERIOD_LOCKED`; and for `MANUAL` and `TOP_SIDE` entries the `doc_state` must not be `DOC_MISSING` — at least one supporting document must be attached — else `ERR_DOC_REQUIRED`.

Documentation has its own mini-lifecycle that runs parallel to approval and never substitutes for it. A `Preparer` attaches a document with a `file_name`, a `content_hash` holding the SHA-256 hex of the attachment, and a `doc_category` of `INVOICE`, `CONTRACT`, `BANK_STATEMENT`, `SCHEDULE`, or `OTHER`; the uploader's header is captured into `uploaded_by_user_id`. Two documents on the same journal entry with an identical `content_hash` are duplicates, rejected with `ERR_DOC_DUPLICATE`. The first non-rejected attachment moves the entry's `doc_state` from `DOC_MISSING` to `DOC_ATTACHED`. An `Approver` then verifies or rejects each `ATTACHED` document — verification is allowed only while the parent entry is still `DRAFT` or `SUBMITTED`, and the verifier must differ from `uploaded_by_user_id` whenever the uploader holds an approver-capable role, per §2.7. Verification records `verified_by_user_id`, moves the document to the terminal `VERIFIED`, and bubbles upward: when every non-`REJECTED` document on the entry is `VERIFIED`, the entry's `doc_state` becomes `DOC_VERIFIED`. Rejecting a document moves it to `REJECTED` and recomputes the entry's `doc_state`, which may drop from `DOC_ATTACHED` back to `DOC_MISSING` if the rejected document was the only one.

Approval, posting, rejection, and rework complete the cycle. An `Approver` approves a `SUBMITTED` entry only when the approver differs from `preparer_user_id` (`ERR_SOD_VIOLATION`), the `doc_state` is exactly `DOC_VERIFIED` (`ERR_DOC_NOT_VERIFIED`), and the parent entity-period is neither `SOFT_LOCKED` nor `HARD_LOCKED`; approval records `approver_user_id` and moves the entry to `APPROVED`. Posting is a `Preparer` action whose actor must differ from `approver_user_id` — poster differs from approver — and whose parent entity-period must again be in `PREPARING`, `SUBLEDGER_CUT`, `RECONCILED`, or `REOPENED`. Posting stamps `posted_at`, which is immutable thereafter, moves the entry to the terminal `POSTED`, appends a `JE_POSTED` event, and triggers two downstream effects: the entity-period's `trial_balance_minor` is recomputed in full — never incrementally, so balances cannot drift — as the sum over all of the entity-period's `POSTED` entries of each entry's debit-line total minus its credit-line total, with `ELIMINATION`-type lines included and `DRAFT`, `SUBMITTED`, `APPROVED`, and `REJECTED` entries excluded; and the entity-period's `translated_balance_minor` and `cta_minor` are marked stale, so consolidation readiness will refuse with `ERR_TRANSLATION_STALE` until translation is re-run. Rejection moves a `SUBMITTED` entry to `REJECTED`, requires a non-empty `rejection_reason` (`ERR_REJECTION_REASON_REQUIRED`), and must come from an `Approver` other than the preparer. Rework finally returns a `REJECTED` entry to `DRAFT`, is permitted only to the original `preparer_user_id`, clears `rejection_reason`, and resets `doc_state` to `DOC_ATTACHED` when any `ATTACHED` documents remain, otherwise to `DOC_MISSING`.

### 3.6. Account Reconciliation and the Aging of Unreconciled Items

Reconciliation proves that the general ledger and its sources agree. A `Preparer` creates a reconciliation on an entity-period with the `account_code` being reconciled, a `recon_type` of `BANK`, `INTERCOMPANY`, `SUBLEDGER_GL`, or `SUSPENSE`, the `gl_balance_minor` carried by the general ledger at period end, and the independent `subledger_balance_minor` from the source system. The system computes `difference_minor` as the GL balance minus the subledger balance with sign preserved, and `is_within_tolerance`, which is true when the absolute difference is no more than five hundred minor units. Creation also bumps the entity-period's `unreconciled_count`, which counts reconciliation rows not yet in `CLEARED`; reconciliation listings on an entity-period can be filtered by `status`.

Review and clearance are deliberately split between two hands. A `Preparer` moves an `OPEN` reconciliation to `IN_REVIEW`, but only while the parent entity-period is in `SUBLEDGER_CUT` or `REOPENED`; the move records `reviewed_by_user_id`. A `Preparer` may also return an `IN_REVIEW` reconciliation to `OPEN` for rework, which clears `reviewed_by_user_id`. Clearing is the terminal approval: the clearing user's `X-User-ID` must differ from `reviewed_by_user_id` — a match is rejected with `ERR_SOD_VIOLATION` — and either `is_within_tolerance` must hold, or every reconciling item must be in `RESOLVED` or `WRITTEN_OFF` with the recomputed difference back within tolerance; a clear attempted with open items and an out-of-tolerance difference is rejected with `ERR_RECON_UNRESOLVED_ITEMS`. A successful clear records `cleared_by_user_id`, moves the reconciliation to `CLEARED`, recomputes `unreconciled_count`, and appends a `RECON_CLEARED` event.

Reconciling items explain a difference line by line. A `Preparer` adds each item with a free-text `description`, a signed `amount_minor` that may be negative, and the `item_date` on which the item originated; each item records its parent `reconciliation_id`. The system derives `aging_bucket` from whole 86,400-second days past the parent period's `period_end`, measured at the earlier of the current logical instant and the item's resolution instant — and for still-`OPEN` items, always at the current instant. An item whose `item_date` is on or before `period_end` and which is not yet past due lands in `CURRENT`; one through thirty days past lands in `AGE_1_30`; thirty-one through sixty in `AGE_31_60`; sixty-one through ninety in `AGE_61_90`; and ninety-one days past or more lands in `AGE_OVER_90`. The boundaries are exact: exactly thirty days past is `AGE_1_30`, exactly thirty-one is `AGE_31_60`, exactly ninety is `AGE_61_90`, and exactly ninety-one is `AGE_OVER_90`. The entity-period's `aged_over_30_count` counts open items in `AGE_31_60` and beyond — those aged strictly more than thirty days past `period_end`.

Items leave the open set in two ways. Resolving is a `Preparer` action on an item whose parent reconciliation is `OPEN` or `IN_REVIEW`: it stamps `resolved_at`, moves the item to `RESOLVED`, and recomputes the parent's `difference_minor` with the item removed from the open set. Writing off is an `Approver` action with two gates: the item's absolute `amount_minor` must be strictly below the period's `materiality_threshold_minor` — items at or above materiality cannot be written off and are rejected with `ERR_WRITEOFF_ABOVE_MATERIALITY` — and the item's `aging_bucket` must be `AGE_31_60`, `AGE_61_90`, or `AGE_OVER_90`, because `CURRENT` and `AGE_1_30` items are too young to write off (`ERR_WRITEOFF_TOO_YOUNG`). A write-off stamps `resolved_at`, recomputes the parent difference, and generates a write-off-style `MANUAL` journal entry in `DRAFT` on the same entity-period so the write-off lands in the ledger through the normal approval chain.

Time itself is a risk factor here. When the logical clock advances past thirty days beyond `period_end` while a reconciliation is still `OPEN`, the system moves it to the terminal `STALE` state and recomputes the entity-period's `aged_over_30_count`; a `STALE` reconciliation blocks the entity-period's advance to `RECONCILED` just as firmly as an out-of-tolerance one.

Advancing an entity-period to `RECONCILED` — the mark-reconciled action, performed by a `Preparer` from `SUBLEDGER_CUT`, or from `REOPENED` after a reopen — enforces two families of gates. First, every reconciliation on the entity-period must be `CLEARED`, or be sitting in `OPEN` or `IN_REVIEW` with `is_within_tolerance` true (auto-tolerated); any row outside tolerance and not cleared, and any `STALE` row, is rejected with `ERR_RECON_OUTSTANDING`. Second, every accrual estimate must be `POSTED`, or be `TRUED_UP` with an absolute `true_up_delta_minor` below materiality; an unposted true-up at or above materiality is rejected with `ERR_ACCRUAL_MATERIAL_TRUEUP`. When the advance happens from `REOPENED`, one more gate applies: a fresh translation run must have occurred after the reopen, or the attempt is rejected with `ERR_TRANSLATION_STALE`. A successful advance recomputes `unreconciled_count`.

### 3.7. Currency Translation and the Multi-Tier Consolidation Chain

Translation converts each entity-period's functional-currency trial balance into the period's reporting currency. A `Controller` triggers a translation run for one entity-period, and the run follows the owning entity's `translation_method`. Either variant requires the period's FX rates for the functional-to-reporting pair, and a missing required rate — whether period-end, average, or historical — is rejected with `ERR_FX_RATE_MISSING`. A successful run clears the translation-stale flag and appends a `TRANSLATION_RUN` event.

Under `CURRENT_RATE`, `translated_balance_minor` is the entity-period's `trial_balance_minor` multiplied by the period's `PERIOD_END` rate, rounded half up to integer minor units. The `cta_minor` is the cumulative translation adjustment plug booked to equity: the translated balance just computed minus the trial balance multiplied by the period's `AVERAGE` rate, that second product also rounded half up to integer minor units.

Under `TEMPORAL`, the balance splits into monetary and non-monetary legs. The monetary leg is the trial balance multiplied by the monetary fraction — a constant of 1.0 for the pure cash and intercompany populations the system models — rounded half up; the non-monetary leg is the remainder of the trial balance. Then `translated_balance_minor` is the monetary leg multiplied by the `PERIOD_END` rate, rounded half up, plus the non-monetary leg multiplied by the `HISTORICAL` rate, rounded half up — each leg rounded before they are summed, never the sum rounded once. The historical rate is the one with the latest `effective_at` on or before the close period's `period_end`. Under the temporal method `cta_minor` is forced to exactly zero, because temporal remeasurement hits profit and loss rather than equity; the difference versus what the current-rate method would have produced is surfaced instead as a remeasurement amount, `remeasurement_minor`. The two variants deliberately produce different `translated_balance_minor` and `cta_minor` for identical inputs whenever the period-end and average rates differ, or the historical and period-end rates differ.

Consolidation rolls the translated results up the entity tree. A `Controller` triggers the consolidation run on a period, which processes entity-periods in increasing `consolidation_tier` — children always before their parents — with ties within a tier broken by the entity's `created_at` ascending, never by its `id`. Only entity-periods at `RECONCILED` or beyond participate. Each entity-period is translated per its variant, then each child's translated balance is added into its parent's consolidated view. Chains of two or more hops apply rates hop by hop: a JPY grandchild under a EUR parent under a USD root translates JPY into EUR at the EUR-scoped rate, then the EUR aggregate into USD. Rounding is half up at each hop, with full precision carried within a hop and rounding applied only when a hop's result is written. Because hierarchy cycles are rejected at entity registration, this topological order always exists. The run recomputes each participating entity-period's `translated_balance_minor`, `cta_minor`, and `nci_share_minor`, and answers with `consolidated_balance_minor`, `consolidated_nci_minor`, `consolidated_cta_minor`, and `tiers_processed`.

Minority interest is computed per entity-period whenever it advances to `READY_FOR_CONSOL`, and again inside the consolidation run. The `nci_share_minor` is the `translated_balance_minor` multiplied by the percentage not owned — one hundred minus `ownership_pct`, divided by one hundred — rounded half up to integer minor units, and it is exactly zero when `ownership_pct` is one hundred. The parent's share is then the translated balance minus the already-rounded NCI share; the subtraction-after-rounding order is pinned so that parent share plus NCI share always re-adds to the translated balance exactly. When a tier consolidates, it sums its own translated balance plus only the parent-share portions of its children; the NCI portions aggregate into a separate consolidated NCI line.

### 3.8. Intercompany Elimination

Intercompany pairs cancel balances that two group entities carry against each other. A `Preparer` declares a pair on a close period by naming `entity_period_id_a` and `entity_period_id_b` — the two sides must differ and must belong to two different entities, otherwise the declaration is rejected with `ERR_ELIM_SAME_ENTITY` — the intercompany `account_code` being eliminated (for example 1500-IC_AR), `amount_a_minor` as side A's balance in side A's functional currency, and `amount_b_minor` as side B's balance in side B's functional currency, where a mirror sign between the two is expected. A new pair starts in `PROPOSED`. Pairs can be listed per period with a `status` filter, and per entity-period across either side.

Matching prices both sides into reporting currency. Both sides' entity-periods must be in `RECONCILED`, `READY_FOR_CONSOL`, or `REOPENED`, and FX rates must exist for any side whose functional currency is not the reporting currency — a missing rate is rejected with `ERR_FX_RATE_MISSING`, while a side already in reporting currency translates at the identity rate of 1.0. The recompute then works each side independently: side A's absolute amount is translated to reporting currency and rounded half up, side B's absolute amount likewise, and only then are the two rounded results compared — translating the minimum of the raw amounts is never correct. The `eliminated_amount_minor` is the smaller of the two rounded translated sides, because only the smaller absolute side can actually be eliminated. The `residual_minor` is side A's rounded translated absolute minus side B's, with sign preserved — a positive residual means side A is larger — and it represents the intercompany out-of-balance that must be investigated.

Elimination books the cancellation. Moving a `MATCHED` pair to `ELIMINATED` requires the absolute `residual_minor` to be no more than five hundred minor units of elimination tolerance; above that, the attempt is rejected with `ERR_ELIM_RESIDUAL_EXCEEDED`. A successful elimination creates an `ELIMINATION`-type journal entry, already `APPROVED` and auto-balanced, booking `eliminated_amount_minor` against the pair's `account_code` on both entity-periods, and appends an `ELIMINATION_RUN` event.

Dispute is the escape valve. A `Preparer` may move a `PROPOSED` pair to the terminal `DISPUTED` state without further preconditions, but the consequence is real: a `DISPUTED` pair whose absolute residual exceeds five hundred minor units blocks every entity-period it touches from advancing to `READY_FOR_CONSOL`. That readiness gate is enforced generally — advancing any entity-period to `READY_FOR_CONSOL` requires every pair touching it to be `MATCHED` or `ELIMINATED` with an absolute residual no greater than five hundred, or the advance is rejected with `ERR_ELIM_RESIDUAL_EXCEEDED`.

### 3.9. Flux Analysis, Period Locking, and Finalization

Flux analysis forces the story behind big movements. A `Preparer` creates a flux row on an entity-period with the `account_code` whose period-over-period movement is being explained, the `prior_balance_minor` and `current_balance_minor` in functional currency, and optionally an `explanation_text` and a `reconciliation_id` linking the reconciliation that evidences the variance. The system computes `variance_minor` as the current balance minus the prior balance, and `variance_pct` as the absolute variance divided by the larger of the absolute prior balance and one — the denominator is floored at one so a zero prior balance cannot divide by zero — multiplied by one hundred, rounded half up to two decimal places, with all threshold comparisons using that rounded value. The `requires_explanation` flag is true when the absolute variance is at or above the period's `materiality_threshold_minor`, or when `variance_pct` is at least 10.0: a variance exactly at materiality is mandatory, and a percentage of exactly 10.0 is mandatory. A zero prior balance with any non-zero current balance pushes the floored denominator to one, making the percentage effectively always at or above ten and the explanation mandatory. Flux rows can be listed per entity-period, and per linked reconciliation.

The flux lifecycle then runs `OPEN` → `EXPLAINED` → `ACCEPTED`, with a rework loop. A `Preparer` supplies the narrative by moving a row from `OPEN` to `EXPLAINED`; the `explanation_text` must be non-empty or the attempt is rejected with `ERR_EXPLANATION_REQUIRED`. A `Controller` accepts an `EXPLAINED` row — but when `reconciliation_id` is set, the linked reconciliation must already be `CLEARED`, otherwise acceptance is rejected with `ERR_FLUX_RECON_NOT_CLEARED`. A `Controller` may instead reject the row into `REJECTED`, and a `Preparer` may reopen a `REJECTED` row back to `OPEN`, which clears `explanation_text` so the narrative is rewritten from scratch.

Readiness for consolidation is the first period-level convergence. When a `Preparer` advances an entity-period from `RECONCILED` to `READY_FOR_CONSOL`, three gates hold: every close task on the entity-period must be `DONE` or `WAIVED` (`ERR_OPEN_CLOSE_TASKS`); every elimination pair touching it must satisfy the residual rule of §3.8; and translation must not only have run at least once for the period (`ERR_TRANSLATION_NOT_RUN`) but must be fresh — a run predating the latest journal posting or a reopen is stale, and readiness refuses with `ERR_TRANSLATION_STALE` until translation is re-run. A successful advance recomputes `nci_share_minor` per §3.7 and makes the period eligible to converge: once every sibling entity-period is `READY_FOR_CONSOL` or beyond, the period qualifies for soft-lock, a condition checked when the soft-lock call arrives.

Locking comes in two strengths. Soft-locking, a `Controller` action guarded by `expected_close_period_version` per §2.8, requires the posture to currently be `OPEN` or `REOPENED` and every entity-period to be `READY_FOR_CONSOL` or beyond; it moves each `READY_FOR_CONSOL` entity-period to `SOFT_LOCKED`, recomputes `locked_entity_count` — the count of entity-periods in `HARD_LOCKED`, here refreshed as the cascade lands — flips the posture to `SOFT_CLOSED`, appends a `SOFT_LOCK` event, and increments the period's `version` by one, all while `status` stays `IN_PROGRESS`: soft-lock is a posture-only transition. Hard-locking is the point of no return, equally OCC-guarded: it requires every entity-period to be `SOFT_LOCKED` — each transitions to `HARD_LOCKED` inside the same request — every elimination pair of the period to be `ELIMINATED` or `DISPUTED` with its residual within tolerance, and every flux row with `requires_explanation` true to be `ACCEPTED`. Hard-lock moves the period from `IN_PROGRESS` to `UNDER_REVIEW`, sets the posture to `HARD_CLOSED`, sets `locked_entity_count` equal to `total_entity_count` — the count of all of the period's entity-period rows — appends a `HARD_LOCK` event, and increments `version` by one. From that moment the hard-locked entity rows are immutable per §2.10.

Reopening unwinds a premature soft-lock, and only a soft-lock. A `Controller` reopens a period — OCC-guarded like the locks — only while its posture is `SOFT_CLOSED`; attempting to reopen a `HARD_CLOSED` or `UNDER_REVIEW` period is rejected with `ERR_PERIOD_HARD_LOCKED`, and an empty `reopened_reason` is rejected with `ERR_REOPEN_REASON_REQUIRED`. Reopening moves every `SOFT_LOCKED` entity-period to `REOPENED`, sets the posture to `REOPENED`, appends a `REOPENED` event whose `detail` carries the supplied reason, and increments `version` by one. History is preserved through the unwind: journal entries already `POSTED` stay `POSTED`, and new entries may be drafted again — but each reopened entity-period's `translated_balance_minor` and `cta_minor` are flagged stale, so a fresh translation run is required before it can reach `READY_FOR_CONSOL` again, and its path back runs through `RECONCILED` under the gates of §3.6.

Finalization closes the books for good. A `Controller` finalizes a period in `UNDER_REVIEW` — again OCC-guarded — provided no `REVIEW_FINALIZED` event exists yet for the period (finalization itself appends that event, so a second finalize is impossible) and no entity-period sits in `REOPENED`. The transition moves the period to the terminal `FINALIZED`, increments `version` by one, and computes the close metrics at the finalize instant, snapshotting them into the event's `detail`: `days_to_close`, the whole 86,400-second days between `period_end` and the finalize instant; `late_task_count`, the number of tasks whose `is_late` is true; `task_completion_pct`, the count of `DONE` plus `WAIVED` tasks divided by the total task count and multiplied by one hundred, rounded half up to two decimal places; `aged_item_count`, the sum of `aged_over_30_count` across the period's entity-periods; and `open_item_value_minor`, the sum of `amount_minor` over reconciling items still `OPEN`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource or add a new member to a collection return `201 Created`. Operations that modify an existing resource — including every state-transition action — return `200 OK`. The complete surface, mounted under `/close`, is:

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/close/_clock/set_current_utc` | Set the logical clock (test-driving) | Controller |
| POST | `/close/_subledger/seed` | Inject a raw subledger transaction (the declared feed) | Controller |
| POST | `/close/periods` | Create a close period | Controller |
| GET | `/close/periods` | List close periods | Controller, Preparer, Approver, Auditor |
| GET | `/close/periods/{id}` | Get one close period | Controller, Preparer, Approver, Auditor |
| POST | `/close/periods/{id}/open` | Open the period, fanning out one entity-period per entity | Controller |
| POST | `/close/periods/{id}/soft-lock` | Soft-lock: all ready entity-periods to SOFT_LOCKED | Controller |
| POST | `/close/periods/{id}/hard-lock` | Hard-lock: move the period to UNDER_REVIEW | Controller |
| POST | `/close/periods/{id}/reopen` | Reopen a soft-closed period | Controller |
| POST | `/close/periods/{id}/finalize` | Finalize the period with a close-metrics snapshot | Controller |
| POST | `/close/periods/{id}/consolidate` | Run the bottom-up translation chain and NCI roll-up | Controller |
| GET | `/close/periods/{id}/events` | List audit events of a period | Controller, Approver, Auditor |
| POST | `/close/entities` | Register a legal entity | Controller |
| GET | `/close/entities` | List entities | Controller, Preparer, Approver, Auditor |
| GET | `/close/entities/{id}` | Get one entity | Controller, Preparer, Approver, Auditor |
| GET | `/close/entities/{id}/journal-entry-lines` | List journal lines naming the entity as counterparty | Controller, Preparer, Approver, Auditor |
| GET | `/close/entity-periods` | List entity-periods | Controller, Preparer, Approver, Auditor |
| GET | `/close/entity-periods/{id}` | Get one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/translate` | Run currency translation for one entity-period | Controller |
| POST | `/close/entity-periods/{id}/mark-reconciled` | Advance to RECONCILED after reconciliation and accrual gates | Preparer |
| POST | `/close/entity-periods/{id}/ready` | Advance to READY_FOR_CONSOL after task, elimination, and translation gates | Preparer |
| GET | `/close/entity-periods/{id}/events` | List audit events scoped to one entity-period | Controller, Preparer, Approver, Auditor |
| GET | `/close/entity-periods/{id}/tasks` | List tasks of one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/subledger-cutoffs` | Create a subledger cutoff spec | Preparer |
| GET | `/close/entity-periods/{id}/subledger-cutoffs` | List cutoffs of one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/accruals` | Create an accrual estimate | Preparer |
| GET | `/close/entity-periods/{id}/accruals` | List accruals of one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/journal-entries` | Create a journal entry with inline lines | Preparer |
| GET | `/close/entity-periods/{id}/journal-entries` | List journal entries of one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/reconciliations` | Create a reconciliation for an account | Preparer |
| GET | `/close/entity-periods/{id}/reconciliations` | List reconciliations of one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/entity-periods/{id}/flux` | Create a flux explanation row | Preparer |
| GET | `/close/entity-periods/{id}/flux` | List flux rows of one entity-period | Controller, Preparer, Approver, Auditor |
| GET | `/close/entity-periods/{id}/elim-pairs` | List elimination pairs touching one entity-period | Controller, Preparer, Approver, Auditor |
| POST | `/close/periods/{id}/tasks` | Create a close task on the period | Controller |
| GET | `/close/periods/{id}/tasks` | List tasks of a period | Controller, Preparer, Approver, Auditor |
| GET | `/close/tasks/{id}` | Get one close task | Controller, Preparer, Approver, Auditor |
| POST | `/close/tasks/{id}/start` | Start a ready task | Preparer |
| POST | `/close/tasks/{id}/complete` | Complete an in-progress task | Preparer |
| POST | `/close/tasks/{id}/waive` | Waive a non-critical ready task | Controller |
| POST | `/close/tasks/{id}/unstart` | Send an in-progress task back to ready | Preparer |
| GET | `/close/subledger-cutoffs/{id}` | Get one subledger cutoff | Controller, Preparer, Approver, Auditor |
| GET | `/close/subledger-cutoffs/{id}/accruals` | List accruals computed against one cutoff | Controller, Preparer, Approver, Auditor |
| POST | `/close/subledger-cutoffs/{id}/cut` | Execute the cutoff, computing totals | Preparer |
| POST | `/close/subledger-cutoffs/{id}/confirm` | Confirm an executed cutoff | Approver |
| POST | `/close/accruals/{id}/true-up` | True up a provisional accrual to the final actual | Preparer |
| POST | `/close/accruals/{id}/recompute` | Recompute a provisional accrual amount | Preparer |
| POST | `/close/accruals/{id}/post` | Post an accrual, spawning a balancing entry when the delta is non-zero | Preparer |
| GET | `/close/journal-entries/{id}` | Get one journal entry | Controller, Preparer, Approver, Auditor |
| GET | `/close/journal-entries/{id}/lines` | List lines of one journal entry | Controller, Preparer, Approver, Auditor |
| POST | `/close/journal-entries/{id}/submit` | Submit a draft entry | Preparer |
| POST | `/close/journal-entries/{id}/approve` | Approve a submitted entry | Approver |
| POST | `/close/journal-entries/{id}/post` | Post an approved entry | Preparer |
| POST | `/close/journal-entries/{id}/reject` | Reject a submitted entry | Approver |
| POST | `/close/journal-entries/{id}/rework` | Return a rejected entry to draft | Preparer |
| POST | `/close/journal-entries/{id}/documents` | Attach a supporting document to an entry | Preparer |
| GET | `/close/journal-entries/{id}/documents` | List documents of one journal entry | Controller, Preparer, Approver, Auditor |
| POST | `/close/documents/{id}/verify` | Verify an attached document | Approver |
| POST | `/close/documents/{id}/reject` | Reject an attached document | Approver |
| GET | `/close/reconciliations/{id}` | Get one reconciliation | Controller, Preparer, Approver, Auditor |
| POST | `/close/reconciliations/{id}/review` | Move a reconciliation into review | Preparer |
| POST | `/close/reconciliations/{id}/clear` | Clear a reviewed reconciliation | Preparer |
| POST | `/close/reconciliations/{id}/return` | Return a reconciliation to open for rework | Preparer |
| POST | `/close/reconciliations/{id}/items` | Add a reconciling item | Preparer |
| GET | `/close/reconciliations/{id}/items` | List items of one reconciliation | Controller, Preparer, Approver, Auditor |
| GET | `/close/reconciliations/{id}/flux` | List flux rows linked to one reconciliation | Controller, Preparer, Approver, Auditor |
| POST | `/close/reconciling-items/{id}/resolve` | Resolve an open reconciling item | Preparer |
| POST | `/close/reconciling-items/{id}/write-off` | Write off an aged reconciling item | Approver |
| POST | `/close/periods/{id}/elim-pairs` | Declare an intercompany elimination pair | Preparer |
| GET | `/close/periods/{id}/elim-pairs` | List elimination pairs of a period | Controller, Preparer, Approver, Auditor |
| POST | `/close/elim-pairs/{id}/match` | Match a proposed pair, computing eliminated and residual amounts | Preparer |
| POST | `/close/elim-pairs/{id}/eliminate` | Eliminate a matched pair, auto-booking the elimination entry | Preparer |
| POST | `/close/elim-pairs/{id}/dispute` | Dispute a proposed pair | Preparer |
| POST | `/close/flux/{id}/explain` | Attach the variance narrative | Preparer |
| POST | `/close/flux/{id}/accept` | Accept an explained variance | Controller |
| POST | `/close/flux/{id}/reject` | Reject an explained variance | Controller |
| POST | `/close/flux/{id}/reopen` | Reopen a rejected flux row | Preparer |
| POST | `/close/periods/{id}/fx-rates` | Register an FX rate scoped to the period | Controller |
| GET | `/close/periods/{id}/fx-rates` | List FX rates of a period | Controller, Preparer, Approver, Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows they guard in §2 and §3; this table is the identifier-to-status index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_STALE_PERIOD_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_SOD_VIOLATION` | 409 |
| `ERR_PERIOD_LOCKED` | 409 |
| `ERR_PERIOD_HARD_LOCKED` | 409 |
| `ERR_PERIOD_ALREADY_OPEN` | 409 |
| `ERR_PERIOD_NOT_YET_OPEN` | 409 |
| `ERR_REOPEN_REASON_REQUIRED` | 409 |
| `ERR_TASK_DEPENDENCY_CYCLE` | 409 |
| `ERR_ENTITY_HIERARCHY_CYCLE` | 409 |
| `ERR_JE_UNBALANCED` | 409 |
| `ERR_JE_OUT_OF_PERIOD` | 409 |
| `ERR_JE_CCY_MISMATCH` | 409 |
| `ERR_LINE_NOT_POSITIVE` | 409 |
| `ERR_ELIM_SAME_ENTITY` | 409 |
| `ERR_ELIM_RESIDUAL_EXCEEDED` | 409 |
| `ERR_DOC_DUPLICATE` | 409 |
| `ERR_DOC_REQUIRED` | 409 |
| `ERR_DOC_NOT_VERIFIED` | 409 |
| `ERR_REJECTION_REASON_REQUIRED` | 409 |
| `ERR_CUTOFF_OUT_OF_PERIOD` | 409 |
| `ERR_NO_SUBLEDGER_CUTOFF` | 409 |
| `ERR_ACCRUAL_ZERO_DELTA` | 409 |
| `ERR_ACCRUAL_MATERIAL_TRUEUP` | 409 |
| `ERR_RECON_OUTSTANDING` | 409 |
| `ERR_RECON_UNRESOLVED_ITEMS` | 409 |
| `ERR_WRITEOFF_ABOVE_MATERIALITY` | 409 |
| `ERR_WRITEOFF_TOO_YOUNG` | 409 |
| `ERR_FX_RATE_MISSING` | 409 |
| `ERR_TRANSLATION_NOT_RUN` | 409 |
| `ERR_TRANSLATION_STALE` | 409 |
| `ERR_FLUX_RECON_NOT_CLEARED` | 409 |
| `ERR_EXPLANATION_REQUIRED` | 409 |
| `ERR_NOT_TASK_ASSIGNEE` | 409 |
| `ERR_POSTURE_NOT_OPEN` | 409 |
| `ERR_OPEN_CLOSE_TASKS` | 409 |
| `ERR_TASK_NOT_WAIVABLE` | 409 |

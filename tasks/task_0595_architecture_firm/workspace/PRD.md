# Architecture Firm API — Product Requirements Document

## 1. Introduction

An architecture practice earns its fee twice: once by producing drawings, and once by proving — to a client, an auditor and its own principals — that the fee it invoiced was actually earned. Today that proof lives in three disconnected places. Design progress sits in a phase spreadsheet (`SD`, `DD`, `CD`, `CA`, each with a milestone date somebody forgot to update). Labour sits in a timesheet tool that nobody reconciles against the project's cost budget until the month closes. And the fee ledger — what has been earned, what has been billed, and the work-in-progress gap between the two — sits in a principal's head. When a contractor's RFI turns into an additional service, or a consultant's structural submittal sits on a reviewer's desk past its due date, the firm discovers the consequence weeks later, in a number that no longer ties out.

This document specifies the REST API for a single system of record that closes those gaps. It covers the full arc of a commission: registering staff and consultant firms, opening a project, writing and executing its contract, allocating the fee across the four design phases, running the drawing / RFI / submittal logs, coordinating permit review with the authority having jurisdiction, capturing time and expense, negotiating change orders with the client, and finally issuing invoices with tiered retainage and recording payment against them. The system's governing ambition is that every derived number — a phase's earned value, a project's budget posture, a contract's WIP balance — is recomputed from its inputs at the moment those inputs move, and never drifts.

Two constraints shape the design throughout. First, **segregation of duties**: the person who logs an hour may not approve it, and the person who submits a change order may not execute it. Second, **fee integrity under concurrency**: the contract's total fee is the single most contested number in the firm, so any write that consumes it must prove it read the contract's current version. Both are enforced by the server, not by convention.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API — without exception, including read-only list and fetch calls — must carry two headers:

- `X-User-ID` — the identifier of the acting principal.
- `X-User-Role` — exactly one of the five role names below.

If either header is absent, or if `X-User-Role` is not one of the five declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the role is not among those authorised for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The five roles are `PrincipalArchitect`, `ProjectManager`, `StaffArchitect`, `ConsultantRep`, and `ClientRep`.

A `PrincipalArchitect` is a firm principal. They own the master data, the contract ledger and the entire money surface. When `X-User-Role` is `PrincipalArchitect`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it as an audit value — for example as `approved_by_user_id` on a `TimeEntry`, or as `submitted_by_user_id` / `executed_by_user_id` on a `ChangeOrder` — but it never compares it to any entity's `id`.

A `ProjectManager` is the staff member named on a project. When `X-User-Role` is `ProjectManager`, `X-User-ID` is the `id` of the acting `StaffMember`; ownership checks on any resource that references a `StaffMember` compare the resource's staff foreign-key field to `X-User-ID`. Concretely, every write a `ProjectManager` performs against a project — whether directly on the project or on any phase, drawing, time entry, expense, RFI, submittal, permit review, field report, change order or invoice belonging to it — is rejected with `ERR_NOT_PROJECT_MANAGER` (HTTP 403) unless that project's `project_manager_staff_id` equals the caller's `X-User-ID`.

A `StaffArchitect` is a staff member producing work: hours, expenses, drawings, RFIs and field reports. When `X-User-Role` is `StaffArchitect`, `X-User-ID` is likewise the `id` of the acting `StaffMember`. A `StaffArchitect` may only create a time entry, an expense or a field report whose `staff_member_id` equals their own `X-User-ID`; acting for another staff member is rejected with `ERR_NOT_OWNER` (HTTP 403).

A `ConsultantRep` speaks for an engineering consultancy. When `X-User-Role` is `ConsultantRep`, `X-User-ID` is the `id` of the acting `ConsultantFirm`; ownership checks compare a submittal's `consultant_firm_id` to `X-User-ID`, and a mismatch yields `ERR_NOT_OWNER`.

A `ClientRep` is the client's representative. When `X-User-Role` is `ClientRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server never compares it to any entity's `id`. It is compared instead to the `client_rep_user_id` recorded on the project, which is a free-form opaque string and never an entity id. A `ClientRep` rendering a decision on a change order whose project carries a different `client_rep_user_id` is rejected with `ERR_NOT_OWNER`.

Ownership scoping (the `ERR_NOT_PROJECT_MANAGER` / `ERR_NOT_OWNER` family) applies to every write endpoint except staff registration, consultant registration, project creation, and the logical-clock endpoint — those four are principal-only and have no owner to compare against.

Layered on top of ownership is **segregation of duties**, which is about the *same* actor performing two incompatible acts rather than the *wrong* actor performing one. Approving or rejecting a time entry whose `staff_member_id` equals the approver's `X-User-ID` is forbidden. Approving or rejecting an expense whose `staff_member_id` equals the approver's `X-User-ID` is forbidden. Executing a change order whose `submitted_by_user_id` equals the executor's `X-User-ID` is forbidden. All three are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A practical consequence: when a `ProjectManager` logs their own hours, only a `PrincipalArchitect` can approve them.

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

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A `limit` or `offset` outside those bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

List results are always ordered by `created_at` ascending. When a list endpoint responds, the `meta` block carries four pagination fields in addition to the two request-identification fields: `limit` (the effective page size), `offset` (the effective starting position), `total_count` (the number of records matching the filter *before* the page window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Auditing and the Logical Clock

Every persisted resource carries a server-minted `id`, which is a UUID string with no type prefix of any kind, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Clients never supply an `id`.

Most resources additionally carry an `updated_at` timestamp, in the same format, and an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation of that resource. `StaffMember`, `ConsultantFirm`, `Project`, `Contract`, `Phase`, `Drawing`, `TimeEntry`, `Expense`, `RFI`, `Submittal`, `ChangeOrder`, `Invoice` and `PermitReview` all behave this way.

`FieldReport` is the single exception. A field report is an append-only observation: once filed, it is never updated and never deleted. It therefore carries only `id` and `created_at` — it has **no** `updated_at` field and **no** `version` field, and neither key appears in its serialised representation.

The server keeps a **logical clock** rather than reading wall-clock time. Before the clock has ever been set, it reads exactly `2026-05-01T00:00:00Z`, and it never falls back to real time. Every instant the server itself stamps is read from this clock: a submittal's `review_started_at` and the `review_due_at` derived from it, an RFI's `answered_at`, an invoice's `issued_at`, a change order's `executed_at`, a permit review's `decided_at`, and the instant against which a phase's milestone is judged. A `PrincipalArchitect` may reposition the clock by supplying a `to_iso8601` instant; the response reports the new `current_utc`. Repositioning the clock mutates no entity — it only changes what future stamps will read.

### 2.5. Contract Version Guarding

The contract's `total_fee_cents` is the number every downstream money calculation leans on, and two operations consume it destructively. Both are therefore guarded by optimistic concurrency control against the `Contract`.

Drafting an invoice requires a non-optional `expected_contract_version` field in the request body, carrying the `version` of the target `Contract` as the client last observed it. A draft invoice claims the contract's entire unbilled work-in-progress; a second draft written from a stale view of the contract would legitimately claim that same WIP a second time. If `expected_contract_version` does not equal the contract's current `version`, the request is rejected with `ERR_STALE_CONTRACT_VERSION` and HTTP status 412.

Executing a client-approved change order likewise requires a non-optional `expected_contract_version` field carrying the client's last observed contract `version`. Execution rewrites `total_fee_cents` and re-allocates every phase's fee, so a writer holding a stale view of the contract would base its fee arithmetic on a superseded total. Again, a mismatch against the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412).

No other endpoint takes a version field. Issuing an invoice, voiding an invoice, approving a time entry, completing a phase and every other write proceed without any expected-version input, even though several of them do bump `Contract.version` as a side effect. Clients that intend to draft an invoice or execute a change order should therefore re-read the contract immediately beforehand, since the `version` they need is exposed on the contract fetch.

### 2.6. Money, Hours and Rounding Discipline

All monetary quantities in this system are integers denominated in **whole cents** — never floating-point currency. All rate and share quantities are integers denominated in **basis points**, where 10,000 basis points is one whole (so a 7.5% design fee is `fee_rate_bp` of 750, and a phase carrying one quarter of the fee has `weight_bp` of 2500).

Wherever a calculation divides, the result is rounded **half up** — a value exactly halfway between two representable results rounds away from zero, to the larger magnitude. Money is rounded half up to whole cents. Durations expressed in `hours` are rounded half up to two decimal places. There is exactly one place where rounding is *not* used: the retainage-tier ratio described in §3.9 is computed with integer floor division, deliberately truncating rather than rounding.

Every derived number in the system is recomputed from its inputs whenever those inputs move; none is maintained as an independent running total that could drift. The contract's `wip_balance_cents`, in particular, is never stored as an independent quantity — it is always the contract's `earned_to_date_cents` minus its `billed_fee_to_date_cents`, recomputed at every point either operand changes.

### 2.7. Rejection Precedence

When a single request violates more than one rule, the caller must receive a predictable error. Checks are therefore evaluated in a fixed order, and the **first** failing check determines the response. In order:

1. **Authentication** — the headers are present and `X-User-Role` names one of the five roles (`ERR_UNAUTHENTICATED`, 401).
2. **Authorisation** — the caller's role appears in the endpoint's authorised-role list (`ERR_UNAUTHORIZED`, 403).
3. **Path existence** — every resource named by a path parameter exists, validated left to right (the `..._NOT_FOUND` family, 404).
4. **Request shape** — required body fields are present, types are correct, enum members are valid, and numeric ranges hold (`ERR_INVALID_REQUEST`, 400).
5. **Body foreign keys** — every foreign key supplied in the request body resolves to an existing row (the `..._NOT_FOUND` family, 404).
6. **Ownership scoping** — the `ERR_NOT_PROJECT_MANAGER` / `ERR_NOT_OWNER` checks of §2.1 (403).
7. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403).
8. **Contract version guard** — `expected_contract_version` matches the contract's current `version` (`ERR_STALE_CONTRACT_VERSION`, 412).
9. **State-machine legality** — the requested transition is declared from the entity's current state (`ERR_INVALID_STATE`, 409).
10. **Cross-entity state gates** — `ERR_CONTRACT_NOT_EXECUTED`, `ERR_PROJECT_NOT_ACTIVE`, `ERR_CA_PHASE_NOT_ACTIVE`, `ERR_DRAWING_NOT_ISSUED`, `ERR_CONSULTANT_SUSPENDED` (409).
11. **Code and permit compliance** — `ERR_PERMIT_NOT_APPROVED`, `ERR_PERMIT_PHASE_NOT_READY` (409).
12. **Structural constraints** — `ERR_DUPLICATE_PROJECT_NUMBER`, `ERR_CONTRACT_ALREADY_EXISTS`, `ERR_DUPLICATE_PHASE_CODE`, `ERR_PHASE_WEIGHTS_INVALID`, `ERR_PHASE_ORDER_VIOLATION`, `ERR_DUPLICATE_SHEET_NUMBER`, `ERR_FEE_DELTA_SIGN`, `ERR_MAX_CLARIFICATION_ROUNDS` (409).
13. **The open-item gate** — `ERR_OPEN_RFIS_BLOCK_COMPLETION` (409).
14. **Interval occupancy** — `ERR_TIME_ENTRY_OVERLAP`, `ERR_CONSULTANT_REVIEW_CAPACITY` (409).
15. **Money gates** — `ERR_LABOR_BUDGET_EXCEEDED`, `ERR_BILLING_THRESHOLD_NOT_MET`, `ERR_ZERO_INVOICE_AMOUNT`, `ERR_OVERPAYMENT`, `ERR_INVOICE_ALREADY_PAID` (409).

Read this ordering literally. A `StaffArchitect` who attempts a principal-only operation on a project that does not exist receives the authorisation error, not the not-found error, because authorisation is checked before path existence. A phase-completion attempt on a phase that is already `COMPLETED` while the project has open RFIs receives `ERR_INVALID_STATE`, because state-machine legality (step 9) precedes the open-item gate (step 13). And on a change-order execution, segregation of duties (step 7) is evaluated *before* the version guard (step 8), so an executor who is also the submitter receives `ERR_SEGREGATION_OF_DUTIES` even when their `expected_contract_version` is stale as well.

### 2.8. Nested Paths and Reverse Links

Several read endpoints are nested beneath a parent resource in order to expose a reverse link — a project's phases, a project's contract, a contract's change orders, a contract's invoices, a phase's drawings, a phase's permit reviews. Path parameters on these endpoints are resolved strictly **left to right**: the parent must exist before the child collection is considered, and a missing parent yields that parent's own not-found error. A project's contract is returned as an array of length zero or one, never as a bare object, because a project may exist for some time before its contract is written.

Creation, by contrast, is flat. New resources are created against a top-level collection and carry their parent's identifier in the request body: `project_id` on a contract, a phase, an expense, an RFI, a submittal and a field report; `phase_id` on a drawing, a time entry and a permit review; `contract_id` on a change order and an invoice; `staff_member_id` on a time entry, an expense and a field report; `consultant_firm_id` on a submittal; and optionally `drawing_id` on an RFI. A body foreign key that does not resolve produces the corresponding not-found error at step 5 of §2.7.

Filtered list reads are the discovery channel for everything else. Projects may be filtered by `project_manager_staff_id` and by `status`. Time entries may be filtered by `phase_id`, `staff_member_id` and `status`. Expenses may be filtered by `project_id`, `staff_member_id`, `invoice_id` and `status`. RFIs may be filtered by `project_id`, `drawing_id`, `field_report_id` and `status`. Submittals may be filtered by `project_id`, `consultant_firm_id` and `status`. Field reports may be filtered by `project_id` and `staff_member_id`. Filtering RFIs by `field_report_id` deserves special mention: it is the *only* way to discover an RFI that the system created for you as a cascade, since no other surface returns it.

### 2.9. Cascade Discipline and the Fee Ledger

Every state transition described in §3 is requested the same way: the caller names the destination state in a `to_status` field on the request body, and the server checks that a transition from the resource's current state to that destination is declared in the resource's state machine. A destination that is not reachable from the current state — or is not a state of that resource at all — is rejected with `ERR_INVALID_STATE`. Some transitions carry an additional field alongside `to_status`; those are called out where they arise.

The system's derived quantities form a chain, and a mutation at one end propagates deterministically to the other. When a change order is executed, the contract's `total_fee_cents` moves; because it moved, every phase's `fee_allocation_cents` is re-allocated; because those moved, every phase's `earned_cents` is recomputed; because those moved, the contract's `earned_to_date_cents` is recomputed and `wip_balance_cents` follows. Each hop is a consequence of the previous one, and the whole chain settles before the response is written — the API's consistency model is immediate, never eventual.

Every cascade in this document has a mirror. A change order that is voided after execution reverses the fee cascade exactly. An invoice that is voided after issuance reverses the billing cascade exactly. A time entry reverted from `APPROVED` back to `SUBMITTED` reverses the labour rollup exactly. These compensating paths are not best-effort cleanups: they restore the ledger to precisely the state it would have held had the forward operation never run.

Whenever a cascade rewrites a resource, that resource's `updated_at` is refreshed and its `version` increments by one — this is true of resources the caller never named. In particular, a great many operations bump `Contract.version` as a *side* effect: executing the contract itself, completing a phase, patching a phase's percent complete, approving a time entry or reverting one, executing a change order, voiding an executed change order, drafting an invoice, issuing an invoice, and voiding an issued invoice. Any client holding a contract version across one of those events is holding a stale number, which is exactly what §2.5 exists to catch.

One invariant is load-bearing above all others and should be treated as a post-condition of every fee-touching operation: the contract's `total_fee_cents` always equals its `base_fee_cents` plus the sum of `fee_delta_cents` over that contract's change orders in status `EXECUTED`, and the four phases' `fee_allocation_cents` always sum to exactly `total_fee_cents`, with no cent lost to rounding.

---

## 3. Business Logic & Workflows

### 3.1. Firm Master Data: Staff and Consultants

Before any project can be opened, the firm's people and its consulting partners must exist in the system, and only a `PrincipalArchitect` may put them there.

Registering a staff member captures their `full_name` and their `title`, which is one of `PRINCIPAL`, `PROJECT_MANAGER`, `ARCHITECT` or `DESIGNER`. Two integer rates travel with the person: `billing_rate_cents_per_hour`, the rate the client is charged for their time, and `cost_rate_cents_per_hour`, the firm's internal loaded cost for the same hour. Both must be strictly greater than zero. A boolean `active` flag governs whether the person may be assigned new work; it defaults to `true` when omitted. The `id` returned by staff registration is significant beyond bookkeeping — it is the value a `ProjectManager` or `StaffArchitect` subsequently presents as their `X-User-ID`.

Consultant firms are registered in the same way. Each carries a `name`, a `discipline` drawn from `STRUCTURAL`, `MEP`, `CIVIL` and `LANDSCAPE`, and a `concurrent_review_capacity` — an integer of at least 1 that caps how many of that firm's submittals may hold overlapping review windows at any moment. A firm's `status` is either `ACTIVE` or `SUSPENDED`, defaulting to `ACTIVE`. A suspended firm may not have new submittals lodged against it; the attempt is rejected with `ERR_CONSULTANT_SUSPENDED`. As with staff, the returned `id` is the value a `ConsultantRep` authenticates with.

### 3.2. Opening a Commission: Project, Contract and Phase Structure

A `PrincipalArchitect` opens a project by supplying a `project_number` — which must be unique across the entire firm, on pain of `ERR_DUPLICATE_PROJECT_NUMBER` — a `name`, the opaque `client_rep_user_id` that will authorise the client's change-order decisions, the `project_manager_staff_id` of the `StaffMember` who will run the job, and a `labor_budget_cents` ceiling greater than zero for internal labour cost. The project is born in status `DRAFT`, with `labor_cost_cents` at 0, `approved_hours` at 0, `budget_posture` at `WITHIN_BUDGET`, `open_rfi_count` at 0 and `ca_posture` at `CLEAR`.

The contract is written next, and exactly one may exist per project — a second attempt is rejected with `ERR_CONTRACT_ALREADY_EXISTS`. Its `fee_basis` is either `PERCENT_OF_CONSTRUCTION` or `HOURLY`, and this single choice bifurcates almost every downstream fee number in the system. A percent-of-construction contract carries a `construction_cost_estimate_cents` and a `fee_rate_bp`; an hourly contract carries a `not_to_exceed_cents` ceiling. All three of those fields default to 0 when omitted. The contract also fixes the consultant review clock: `review_clock_basis` is either `CALENDAR_DAYS` or `BUSINESS_DAYS`, and `submittal_review_period_days` is an integer of at least 1, defaulting to 14 when the client did not negotiate otherwise. A freshly created contract sits in `DRAFT` with `base_fee_cents`, `total_fee_cents`, `earned_to_date_cents`, `billed_fee_to_date_cents` and `wip_balance_cents` all at 0.

Four design phases must then be added to the project, one per `phase_code` in `SD`, `DD`, `CD` and `CA`. A repeated code on the same project is rejected with `ERR_DUPLICATE_PHASE_CODE`. Each phase declares a `weight_bp` between 0 and 10000 inclusive — its share of the contract's total fee — together with a `milestone_name` naming the contractual milestone that closes it and a `milestone_due_at` instant by which that milestone must be met. An optional `is_billing_milestone` boolean, defaulting to `true`, marks whether the phase's earned value participates in fee billing at all; a phase created with it set to `false` is designed and completed like any other, but its earned value is silently excluded from every invoice. Phases begin `NOT_STARTED` with `percent_complete` at 0, `fee_allocation_cents` at 0, `earned_cents` at 0 and `milestone_status` at `PENDING`. Each phase's `phase_order` is not supplied by the caller — it is derived from the code, with `SD` ordering first, `DD` second, `CD` third and `CA` fourth.

**Contract execution** is the pivot of the whole commission, and a `PrincipalArchitect` performs it by driving the contract from `DRAFT` to `EXECUTED`. Two structural preconditions guard it. The project must have exactly four phases, one for each of the four codes; and those four phases' `weight_bp` values must sum to exactly 10000. A project with three phases, or five, or four whose weights sum to 9999, is rejected with `ERR_PHASE_WEIGHTS_INVALID`.

Execution then does five things in sequence. It sets the contract's status to `EXECUTED`. It freezes `base_fee_cents`: on a `PERCENT_OF_CONSTRUCTION` contract this is the `construction_cost_estimate_cents` multiplied by `fee_rate_bp`, divided by 10000, rounded half up to whole cents; on an `HOURLY` contract it is simply the `not_to_exceed_cents` ceiling. It sets `total_fee_cents` to `base_fee_cents` — no change order can have been executed yet, so there is nothing to add. It allocates that total across the four phases (§3.3). And it recomputes `earned_to_date_cents` and, from it, `wip_balance_cents`. The contract's `version` increments. Finally, execution cascades to the project itself: a project in `DRAFT` is driven to `ACTIVE` by the mere fact that its contract executed. No human calls for that transition, and it is the only way a project leaves `DRAFT`.

An executed contract may later be driven to `TERMINATED`, again by a `PrincipalArchitect`, but only when no invoice on that contract is still sitting in `DRAFT` — the firm may not walk away with an un-issued bill in flight. Termination bumps the contract's `version`.

A `PrincipalArchitect` also controls the project's own lifecycle. An `ACTIVE` project may be moved to `SUSPENDED`, and a `SUSPENDED` one back to `ACTIVE`. Suspension is deliberately shallow: it does **not** cascade to the phases, whose statuses are left exactly as they were. What it does do is close the billing window — issuing an invoice on a project that is not `ACTIVE` is rejected with `ERR_PROJECT_NOT_ACTIVE`. From either `ACTIVE` or `SUSPENDED`, a project may be driven to `CLOSED`, which is terminal, but only when every one of its phases has reached `COMPLETED` and its `open_rfi_count` stands at zero; an open RFI blocks closure with `ERR_OPEN_RFIS_BLOCK_COMPLETION`.

### 3.3. Fee Allocation, Phase Progression, Milestones and the Drawing Log

The allocation of fee across phases is the firm's most rounding-sensitive arithmetic, and its order of operations is pinned. Take the project's four phases in ascending `phase_order` — `SD`, then `DD`, then `CD`, then `CA`. For every phase **except the last**, set `fee_allocation_cents` to the contract's `total_fee_cents` multiplied by that phase's `weight_bp`, divided by 10000, rounded half up to whole cents, and keep a running total of the amounts so assigned. The last phase in the order — `CA` — is not computed from its own weight at all: it receives `total_fee_cents` minus that running total, absorbing whatever remainder rounding left behind. Summing the four unrounded shares and rounding the sum is a different and incorrect procedure; it can overshoot `total_fee_cents` by a cent, and it is not what this system does. After allocation, every phase's `earned_cents` is set to its `fee_allocation_cents` multiplied by its `percent_complete`, divided by 100, rounded half up. All four phases are re-allocated every time, regardless of status — a `COMPLETED` phase is re-allocated too, and its earned value recomputed at a percent complete of 100.

The four phases must be worked in order. A phase leaves `NOT_STARTED` for `ACTIVE` only when the project's contract is in `EXECUTED` — otherwise `ERR_CONTRACT_NOT_EXECUTED` — and only when the sibling phase immediately preceding it in `phase_order` has already reached `COMPLETED`. `DD` waits for `SD`; `CD` waits for `DD`; `CA` waits for `CD`. A violation is rejected with `ERR_PHASE_ORDER_VIOLATION`. `SD`, ordering first, has no predecessor and is exempt from that particular check. The `CA` phase carries one extra gate of its own, described in §3.6.

An `ACTIVE` phase may be parked at `ON_HOLD` and later returned to `ACTIVE` — the loop between the two may repeat as many times as the job demands — although returning from `ON_HOLD` re-checks that the contract is still `EXECUTED`. Progress on an active phase is recorded by a `ProjectManager` updating its `percent_complete`, an integer between 0 and 100 inclusive. Each such update immediately recomputes that phase's `earned_cents` from its `fee_allocation_cents` and the new percentage, then recomputes the contract's `earned_to_date_cents` and `wip_balance_cents`, bumping `Contract.version` by one.

Driving a phase from `ACTIVE` to `COMPLETED` is the milestone event. It is barred outright while the project's `ca_posture` is `DEFICIENT` — that is, while `open_rfi_count` is greater than zero — with `ERR_OPEN_RFIS_BLOCK_COMPLETION` (§3.4 explains why). When it succeeds, the phase's `percent_complete` is forced to 100 and its `earned_cents` consequently becomes its full `fee_allocation_cents`. The milestone is then judged: `milestone_status` becomes `MET` when the logical clock at the moment of completion is at or before `milestone_due_at`, and `MISSED` when the clock has passed it. A completion landing exactly on the due instant is `MET`, not `MISSED`. Completion finally cascades into the fee ledger, recomputing the contract's `earned_to_date_cents` and `wip_balance_cents` and incrementing `Contract.version`.

How much fee a contract has *earned* depends entirely on its `fee_basis`, and the two branches share no arithmetic. On a `PERCENT_OF_CONSTRUCTION` contract, `earned_to_date_cents` is the sum, across **all four** phases regardless of status, of each phase's `fee_allocation_cents` multiplied by its `percent_complete`, divided by 100, rounded half up. Approved labour is irrelevant to that number — hours on a percent contract drive only the project's cost tracking, never its fee. On an `HOURLY` contract, `earned_to_date_cents` is instead the sum of `billable_cents` across every time entry in status `APPROVED` whose phase belongs to this contract's project, capped at the contract's `not_to_exceed_cents`: whichever of the two is smaller wins. Phase completion is irrelevant to *that* number. Whichever branch produced it, `wip_balance_cents` immediately follows as `earned_to_date_cents` minus `billed_fee_to_date_cents`.

**The drawing log.** A sheet enters the drawing log against a phase, carrying a `sheet_number` that must be unique within that phase — a collision is rejected with `ERR_DUPLICATE_SHEET_NUMBER` — and a `title`. It begins `IN_PROGRESS` at `revision` 0. Either a `ProjectManager` or a `StaffArchitect` may maintain the log.

A sheet is released for construction by moving it from `IN_PROGRESS` to `ISSUED`, which is permitted only while the owning phase is itself `ACTIVE` or `COMPLETED`. Later, when the design changes, an issued sheet is marked `SUPERSEDED`. A superseded sheet may be re-issued — driven back from `SUPERSEDED` to `ISSUED` — and each such re-issue increments the sheet's `revision` by exactly 1. That loop between `ISSUED` and `SUPERSEDED` may run as many times as the project needs; the first release to `ISSUED` does *not* bump `revision`, only re-issues after supersession do. A drawing has no terminal state.

The log's `ISSUED` status matters outside the log itself: only an issued sheet may be cited by an RFI (§3.4).

### 3.4. Time, Expense, Budget Posture and the RFI Log

**Logging time.** A time entry is logged against a `phase_id` for a `staff_member_id`, bounded by `start_utc` (inclusive) and `end_utc` (exclusive), which must be strictly later than the start. A `billable` boolean, defaulting to `true`, says whether the client may be charged for it. The entry's project is resolved through its phase. On creation the system computes three frozen numbers: `hours` is the elapsed time between the two instants expressed in seconds, divided by 3600, rounded half up to two decimal places; `cost_cents` is those `hours` multiplied by the staff member's `cost_rate_cents_per_hour`, rounded half up to whole cents; and `billable_cents` is those `hours` multiplied by the staff member's `billing_rate_cents_per_hour`, rounded half up — except on a non-billable entry, where `billable_cents` is 0 outright. Entries start in `DRAFT`, with `approved_by_user_id` null.

Two gates guard creation. First, a staff member's timesheet has capacity for exactly one entry at a time, and the interval is **half-open**: a new entry is rejected when any other entry for the same `staff_member_id` in status `DRAFT`, `SUBMITTED` or `APPROVED` satisfies both that the new entry starts before the other ends and that the other starts before the new entry ends. Intervals that merely touch — a new entry starting at precisely the instant another ends — do **not** collide and are accepted. Entries in `REJECTED` release their interval and never collide with anything. A genuine overlap is rejected with `ERR_TIME_ENTRY_OVERLAP`. Second, no time may be logged against a project whose `budget_posture` has already flipped to `OVER_BUDGET`; that attempt is rejected with `ERR_LABOR_BUDGET_EXCEEDED`.

**Approving time.** A `StaffArchitect` moves their own entry from `DRAFT` to `SUBMITTED` — that is the only transition available to them on a time entry. From `SUBMITTED`, a `ProjectManager` or `PrincipalArchitect` may drive the entry to `APPROVED` or to `REJECTED`, and in either case the actor's `X-User-ID` may not equal the entry's `staff_member_id` (§2.1). `REJECTED` is terminal, and a rejected entry stops occupying its timesheet interval.

Approval is where the labour rollup fires. The project's `approved_hours` and `labor_cost_cents` are recomputed as the sums of `hours` and of `cost_cents` respectively across every time entry in status `APPROVED` whose phase belongs to that project — entries in `DRAFT`, `SUBMITTED` or `REJECTED` contribute nothing at all. The entry's `approved_by_user_id` records the approver's `X-User-ID`. Because `labor_cost_cents` moved, `budget_posture` is re-derived: it becomes `OVER_BUDGET` when `labor_cost_cents` is greater than **or equal to** `labor_budget_cents`, and `WITHIN_BUDGET` otherwise. Landing exactly on the budget flips the project to `OVER_BUDGET`. And because `approved_hours` moved, the contract's `earned_to_date_cents` is recomputed — on an `HOURLY` contract this genuinely changes the fee, since that branch reads approved entries; on a `PERCENT_OF_CONSTRUCTION` contract the recomputation is a no-op on the fee — followed by `wip_balance_cents`, and `Contract.version` increments.

An approval can be undone. A `ProjectManager` or `PrincipalArchitect` may drive an entry from `APPROVED` back to `SUBMITTED`, clearing `approved_by_user_id` to null and reversing all three cascade hops exactly: `approved_hours` and `labor_cost_cents` fall back, `budget_posture` is re-derived from the reduced cost, and the contract's `earned_to_date_cents`, `wip_balance_cents` and `version` are recomputed. The reversal is blocked, however, when the fee it would unwind has already been billed: it is allowed only when the contract's `fee_basis` is `PERCENT_OF_CONSTRUCTION` (where labour never fed the fee in the first place) or when the contract's `billed_fee_to_date_cents` still stands at 0. Otherwise the attempt is rejected with `ERR_INVALID_STATE`.

**Expenses.** An expense is logged against a `project_id` for a `staff_member_id`, with a `category` from `TRAVEL`, `PRINTING`, `PERMIT_FEE` and `MODEL`, and an `amount_cents` strictly greater than zero. A `reimbursable` boolean defaults to `true`, and a `markup_bp` — between 0 and 5000 basis points inclusive — defaults to 1000, i.e. a ten percent markup. The expense's `billable_cents` is computed at creation: on a reimbursable expense it is `amount_cents` multiplied by 10000 plus `markup_bp`, divided by 10000, rounded half up to whole cents; on a non-reimbursable expense it is 0. Expenses begin in `SUBMITTED` with `invoice_id` null. A `ProjectManager` or `PrincipalArchitect` drives them to `APPROVED` or `REJECTED`, subject to the same segregation rule as time: the approver's `X-User-ID` may not be the expense's `staff_member_id`. `REJECTED` is terminal. `APPROVED` puts the expense into the unbilled reimbursable pool that the next invoice will sweep (§3.9).

**The RFI log.** An RFI is opened against a `project_id` with a `subject`, optionally citing a `drawing_id` and optionally flagged `impacts_fee` (default `false`) to mark it as a candidate trigger for an additional-service change order. When a drawing is cited, that drawing must be in status `ISSUED`; citing an in-progress or superseded sheet is rejected with `ERR_DRAWING_NOT_ISSUED`. Each RFI receives an `rfi_number`, sequential per project starting at 1 and assigned in ascending `created_at` order of that project's RFIs. It opens in status `OPEN` with `origin` of `CONTRACTOR`, `clarification_rounds` at 0, `answer_text` null, `answered_at` null and `field_report_id` null.

The count of a project's RFIs whose status is `OPEN` or `RETURNED_FOR_CLARIFICATION` is maintained as `open_rfi_count`; RFIs that are `ANSWERED`, `CLOSED` or `VOID` are excluded from it. From that count comes the project's construction-administration posture: `ca_posture` is `DEFICIENT` whenever `open_rfi_count` is greater than 0, and `CLEAR` only when the count is exactly 0. A `CLEAR` posture is a hard precondition for completing any phase and for closing the project — which is the whole point: the firm does not let a phase close over an unanswered question.

A `ProjectManager` may return an `OPEN` RFI to the asker as `RETURNED_FOR_CLARIFICATION`, incrementing `clarification_rounds` by 1; a `StaffArchitect` (or the manager) then re-opens it, driving it back to `OPEN`. That loop is bounded: an RFI may be returned for clarification at most **twice**, and a third attempt — one made when `clarification_rounds` already equals 2 — is rejected with `ERR_MAX_CLARIFICATION_ROUNDS`. Crucially, an RFI sitting in `RETURNED_FOR_CLARIFICATION` still counts as open; the round trip does not move `open_rfi_count` at all.

Answering an `OPEN` RFI requires a non-empty `answer_text`; omitting it, or supplying an empty one, is rejected with `ERR_INVALID_REQUEST`. The answer is stored, `answered_at` is stamped from the logical clock, and the RFI moves to `ANSWERED` — at which point `open_rfi_count` drops by one and `ca_posture` is re-derived (returning to `CLEAR` only once the count reaches 0). An `ANSWERED` RFI may finally be moved to `CLOSED`, which is terminal and has no further effect on the count. Alternatively, an `OPEN` RFI may be voided outright, moving it to the terminal `VOID` state and likewise decrementing `open_rfi_count` and re-deriving `ca_posture`.

### 3.5. Construction Administration: Field Reports

Once construction is under way, a `StaffArchitect` or `ProjectManager` who visits the site files a field report against a `project_id` for a `staff_member_id`, recording the `visit_date` of the visit, the `weather` observed, a narrative of `observations`, and a `deficiency_count` of zero or more. Field reports are append-only: a filed report rests permanently in the single logical state `FILED`, it can be created, listed and fetched, and there is no surface anywhere in the API for updating or deleting one — nor any state transition to request on it.

Filing is gated twice. The project's `CA` phase must exist and be in status `ACTIVE` — a site visit before construction administration has begun is rejected with `ERR_CA_PHASE_NOT_ACTIVE` — and the project itself must be `ACTIVE`, failing which the filing is rejected with `ERR_PROJECT_NOT_ACTIVE`.

Consider a report filed with a `deficiency_count` of 3. The report row is written, and then the system, on the observer's behalf, opens exactly **one** RFI (not three — one per report, regardless of how many deficiencies it names). That RFI belongs to the same project, cites no drawing, carries `field_report_id` pointing back at the report that spawned it, has an `origin` of `FIELD_REPORT` rather than `CONTRACTOR`, has `impacts_fee` of `false`, has a `subject` of exactly `Field deficiency follow-up`, sits in status `OPEN`, and takes the next sequential `rfi_number` for the project. The project's `open_rfi_count` therefore rises by 1, its `ca_posture` flips to `DEFICIENT`, and — as a fourth consequence — every `ACTIVE` phase on that project is now barred from completing until that RFI is answered or voided. One site visit can freeze the phase schedule, which is precisely the escalation the firm wants. A report filed with a `deficiency_count` of 0 creates no RFI and moves no counter.

Because the auto-created RFI was never returned to the filer in the field-report response, the only way to find it is to list RFIs filtered by that report's `field_report_id`.

### 3.6. Code and Permit Review

A permit package is opened by a `ProjectManager` against a phase, and that phase must be the project's `CD` phase — pointing the package at `SD`, `DD` or `CA` is rejected with `ERR_PERMIT_PHASE_NOT_READY`. The package records the `jurisdiction_name` of the authority having jurisdiction and a `permit_type` of `BUILDING`, `ZONING` or `FIRE`. It begins in `PREPARING` with `submission_round` at 0, `comment_count` at 0 and `decided_at` null.

Lodging the package with the jurisdiction moves it from `PREPARING` to `SUBMITTED`, and this is allowed only once the `CD` phase it references has actually reached `COMPLETED` — a premature submission is rejected with the same `ERR_PERMIT_PHASE_NOT_READY`. Each entry into `SUBMITTED` increments `submission_round` by 1.

From `SUBMITTED`, the jurisdiction may come back with comments: the review moves to `COMMENTS_ISSUED`, and the number of comments must be supplied as `comment_count`, which is recorded on the review (omitting it is an `ERR_INVALID_REQUEST`). The firm answers the comments by driving the review to `RESUBMITTED`, which increments `submission_round` by 1 again. A resubmitted package may draw yet another round of `COMMENTS_ISSUED` — again carrying a `comment_count` — and the cycle between `COMMENTS_ISSUED` and `RESUBMITTED` may repeat for any number of rounds.

A decision arrives from either `SUBMITTED` or `RESUBMITTED`. Approval — `SUBMITTED → APPROVED` or `RESUBMITTED → APPROVED` — stamps `decided_at` from the logical clock and is terminal. Rejection is available only from `RESUBMITTED`: a package may be driven `RESUBMITTED → REJECTED`, also stamping `decided_at`, and that too is terminal. A first-round submission cannot be rejected outright; the jurisdiction must issue comments first.

The approval matters to the schedule, and this is the extra gate mentioned in §3.3. The `CA` phase may not be activated unless the project has at least one permit review, on any of its phases, sitting in status `APPROVED`. Attempting to start construction administration without an approved permit is rejected with `ERR_PERMIT_NOT_APPROVED`.

### 3.7. Consultant Submittals and the Review Desk

A `ConsultantRep` lodges a submittal against a `project_id` for their own `consultant_firm_id`, naming the `spec_section` under review. It arrives in status `RECEIVED` with `revision_number` at 0, `review_started_at` null, `review_due_at` null and `review_notes` null. A submittal may not be lodged against a firm whose `status` is `SUSPENDED` (`ERR_CONSULTANT_SUSPENDED`).

A `ProjectManager` starts the review, driving the submittal from `RECEIVED` to `UNDER_REVIEW`. Two things must hold. The project's contract must be `EXECUTED` (`ERR_CONTRACT_NOT_EXECUTED`). And the consultant's review desk must have room — see below. On success, `review_started_at` is stamped from the logical clock and `review_due_at` is computed from it.

That due date is where the contract's `review_clock_basis` earns its keep, because the two bases give materially different answers from the same start. Take the contract's `submittal_review_period_days` as the number of days allowed. On a `CALENDAR_DAYS` contract, `review_due_at` is simply the start instant advanced by that many periods of 24 hours, weekends included: a fourteen-day review begun on Monday 2026-06-01 at 09:00 UTC is due on 2026-06-15 at 09:00 UTC. On a `BUSINESS_DAYS` contract, the clock advances one 24-hour step at a time and only counts a step when the day it lands on is not a Saturday and not a Sunday, continuing until it has counted the required number of days; the time of day is carried through unchanged. The same fourteen-day review begun on Monday 2026-06-01 at 09:00 UTC is therefore due on 2026-06-19 at 09:00 UTC. Milliseconds are preserved from the start instant in both cases.

**The review desk.** From the moment its review starts until the moment a decision is rendered, a submittal occupies the **closed** interval between its `review_started_at` and its `review_due_at` on its consultant firm's desk. That desk holds at most `concurrent_review_capacity` submittals with overlapping windows. Starting a review is therefore rejected when the number of that firm's *other* submittals in status `UNDER_REVIEW` whose closed windows overlap the proposed one has already reached the firm's `concurrent_review_capacity`. Two windows overlap when the new window's start is at or before the other's due instant **and** the other's start is at or before the new window's due instant. Note the asymmetry with the timesheet rule of §3.4: here the interval is closed, so windows that merely touch — a new review starting at precisely the instant an existing review is due — **do** collide and count against capacity. A firm at capacity rejects the start with `ERR_CONSULTANT_REVIEW_CAPACITY`.

The `ProjectManager` renders one of four decisions on an `UNDER_REVIEW` submittal, each of which records the supplied `review_notes` and each of which releases the firm's review window: `APPROVED`, `APPROVED_AS_NOTED` and `REJECTED` are all terminal, while `REVISE_AND_RESUBMIT` is not. On `REVISE_AND_RESUBMIT` the window is released by clearing both `review_started_at` and `review_due_at` back to null, and the ball returns to the consultant: the owning `ConsultantRep` — and only the firm named by the submittal's `consultant_firm_id`, on pain of `ERR_NOT_OWNER` — drives the submittal from `REVISE_AND_RESUBMIT` back to `RECEIVED`, which increments `revision_number` by 1 and clears `review_notes` back to null. That loop from `RECEIVED` through `UNDER_REVIEW` to `REVISE_AND_RESUBMIT` and back to `RECEIVED` is unbounded; a stubborn spec section may go round it many times.

### 3.8. Change Orders and Additional Services

An RFI flagged `impacts_fee` is the usual prompt for a change order, and a `ProjectManager` or `PrincipalArchitect` drafts one against a `contract_id` with a `title`, a `co_type` of either `ADDITIONAL_SERVICE` or `SCOPE_REDUCTION`, a `fee_delta_cents` amount, and optionally the `source_rfi_number` that prompted it — the latter is informational only, a number copied from the RFI log rather than a reference the system resolves. The sign of the delta must agree with the type: `fee_delta_cents` must be strictly greater than zero for an `ADDITIONAL_SERVICE` and strictly less than zero for a `SCOPE_REDUCTION`. A mismatch — including a delta of exactly zero, which satisfies neither — is rejected with `ERR_FEE_DELTA_SIGN`. Change orders begin in `DRAFT` with `submitted_by_user_id`, `executed_by_user_id` and `executed_at` all null, and have no fee effect whatsoever.

Submitting a change order moves it from `DRAFT` to `SUBMITTED` and records the actor's `X-User-ID` as `submitted_by_user_id`. The contract must be `EXECUTED` (`ERR_CONTRACT_NOT_EXECUTED`).

The client then decides, and only the `ClientRep` whose `X-User-ID` matches the project's `client_rep_user_id` may do so. The fork is genuinely two-branched. Driving the order to `CLIENT_APPROVED` records nothing but the new status: no fee moves, `total_fee_cents` is untouched, and the contract's `version` does not change. Driving it instead to `CLIENT_REJECTED` is terminal and equally inert: the contract's `total_fee_cents`, every phase's `fee_allocation_cents`, and the contract's `version` are all left exactly as they were, and no fee cascade will ever fire for that order.

**Execution** is reserved for a `PrincipalArchitect` and is the only operation that actually moves the contract's fee. It applies only to a `CLIENT_APPROVED` order. It requires `expected_contract_version` to match the contract's current `version` (§2.5), and it requires the executor's `X-User-ID` to differ from the order's `submitted_by_user_id` — the principal who drafted and submitted an additional service may not also be the one who books it. On success the order becomes `EXECUTED`, `executed_by_user_id` records the actor and `executed_at` is stamped from the logical clock, and the fee cascade runs in four hops: the contract's `total_fee_cents` is recomputed as `base_fee_cents` plus the sum of `fee_delta_cents` over all of that contract's `EXECUTED` change orders (which, for this one order, means it moves by exactly this order's delta); every phase's `fee_allocation_cents` is re-allocated from the new total by the pinned procedure of §3.3; every phase's `earned_cents` is recomputed from its new allocation and its existing `percent_complete`; and the contract's `earned_to_date_cents` and `wip_balance_cents` are recomputed. `Contract.version` increments by one.

An executed order may be reversed. A `PrincipalArchitect` drives it from `EXECUTED` to the terminal `VOID` state, provided no invoice on the contract has been issued at or after the order's `executed_at` — voiding fee that a client has already been billed for is rejected with `ERR_INVALID_STATE`. The void runs the compensating cascade: the order's delta drops out of `total_fee_cents`, phase allocations and earned values are recomputed, and the contract's earned and WIP figures follow, with `Contract.version` incrementing again. The invariant of §2.9 survives untouched.

### 3.9. Invoicing, Retainage and Settlement

An invoice is drafted by a `ProjectManager` or `PrincipalArchitect` against a `contract_id` for a billing period ending at `period_end`, and carries the `expected_contract_version` guard of §2.5. It is born in status `DRAFT` and payment status `UNPAID`, with `amount_paid_cents` at 0 and `issued_at` null. Drafting recomputes the contract's `version`.

Seven numbers are computed on the invoice, and they must be evaluated **strictly in this order**, because the tier that determines the retainage is keyed on a figure that includes the very fee this invoice is billing.

**First, the fee portion.** On a `PERCENT_OF_CONSTRUCTION` contract, gather the project's phases that are marked `is_billing_milestone` **and** whose `percent_complete` has reached **at least 50** — exactly 50 qualifies; 49 does not. Sum their `earned_cents`. If no phase qualifies, the invoice is rejected outright with `ERR_BILLING_THRESHOLD_NOT_MET`. On an `HOURLY` contract, no threshold applies and the figure is simply the contract's `earned_to_date_cents`, already capped at the not-to-exceed ceiling. Either way, subtract the contract's `billed_fee_to_date_cents` from the figure to get `fee_billed_cents` — this invoice bills only what previous issued invoices did not. Should that subtraction come out negative, `fee_billed_cents` is clamped to 0.

**Second, the reimbursables.** Sum `billable_cents` across every expense on the same project that is in status `APPROVED`, is marked `reimbursable`, and has not yet been swept onto an invoice — that is, whose `invoice_id` is still null. That sum is `reimbursable_cents`.

**Third**, `gross_cents` is `fee_billed_cents` plus `reimbursable_cents`. An invoice whose `gross_cents` computes to 0 is rejected with `ERR_ZERO_INVOICE_AMOUNT` — a rejection applied both at drafting and again at issuance.

**Fourth**, compute the cumulative fee the contract will have billed *after* this invoice: the contract's `billed_fee_to_date_cents` plus this invoice's `fee_billed_cents`.

**Fifth**, select the retainage tier from that cumulative figure, using integer arithmetic only. Multiply the cumulative amount by 10000, divide by the contract's `total_fee_cents`, and take the **floor** of the quotient — no rounding — to obtain a ratio in basis points. If that ratio is at most 5000 basis points (the contract is at most half billed), `retainage_bp` is 1000, a ten percent hold-back. If the ratio is above 5000 but at most 9000, `retainage_bp` drops to 500, a five percent hold-back. Above 9000, `retainage_bp` is 0 and the firm holds nothing back — the retainage is being released as the job lands.

**Sixth**, `retainage_cents` is `gross_cents` multiplied by `retainage_bp`, divided by 10000, rounded half up. Note that retainage is taken on the **gross** — fee plus reimbursables together — and not on the fee alone.

**Seventh**, `net_due_cents` is `gross_cents` minus `retainage_cents`. That is what the client actually owes.

Draft invoices contribute nothing to any ledger; neither do voided ones. Only issued invoices count.

**Issuing.** A `ProjectManager` or `PrincipalArchitect` drives a `DRAFT` invoice to `ISSUED`, which is permitted only while the contract's project is `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE`). All seven numbers are recomputed from scratch against the state of the world at this moment — phases may have progressed and expenses may have been approved since the draft was cut — and only then are they frozen. If the recomputation lands on a `gross_cents` of 0, the issuance is rejected with `ERR_ZERO_INVOICE_AMOUNT`. On success, `issued_at` is stamped from the logical clock and two cascades run: every expense on the project that is `APPROVED`, `reimbursable`, and not yet attached to an invoice moves to `BILLED` with its `invoice_id` set to this invoice; and the contract's `billed_fee_to_date_cents` rises by this invoice's `fee_billed_cents`, after which `wip_balance_cents` is recomputed and `Contract.version` increments.

**Voiding.** A `PrincipalArchitect` may void an invoice, and the two source states behave very differently. Voiding a `DRAFT` invoice is pure bookkeeping — the draft never touched `billed_fee_to_date_cents`, so nothing is unwound. Voiding an `ISSUED` invoice runs the full compensating cascade: `billed_fee_to_date_cents` falls back by this invoice's `fee_billed_cents`, `wip_balance_cents` is recomputed, and `Contract.version` increments. The contract's `earned_to_date_cents` is emphatically **not** touched — voiding a bill does not un-earn the work. Every expense whose `invoice_id` points at the voided invoice reverts from `BILLED` to `APPROVED` with its `invoice_id` cleared to null, returning to the unbilled pool for the next invoice. An issued invoice may only be voided while its `payment_status` is still `UNPAID`; once money has arrived, the void is rejected with `ERR_INVOICE_ALREADY_PAID`.

**Payment.** The invoice's `payment_status` is a genuinely independent second dimension: it evolves on its own, and neither dimension ever moves the other. A `PrincipalArchitect` records a client payment by supplying an `amount_cents` greater than zero against an invoice that is in status `ISSUED` — recording payment against a `DRAFT` or `VOID` invoice is rejected with `ERR_INVALID_STATE`. The amount is added to the invoice's `amount_paid_cents`. If the resulting total would exceed `net_due_cents`, the payment is rejected with `ERR_OVERPAYMENT`; the client may not overpay, not even by a cent. When the new `amount_paid_cents` lands exactly on `net_due_cents`, `payment_status` becomes `PAID`, which is terminal — whether it arrives in one payment from `UNPAID` or as the last of several from `PARTIALLY_PAID`. When the new total is still short of `net_due_cents`, `payment_status` becomes `PARTIALLY_PAID` (from `UNPAID`) or stays `PARTIALLY_PAID` (when it was already there). Recording payment never changes the issuance dimension: a fully paid invoice remains `ISSUED`.

---

## 4. Endpoint Definitions

All endpoints are mounted at the root of the service. Creating a new resource returns HTTP 201 with the created resource in `data`; every other successful operation — fetches, lists, state transitions, patches, payments and the clock control — returns HTTP 200. All requests, including reads, require the `X-User-ID` and `X-User-Role` headers. The table below is deliberately minimal: request payloads, response payloads and side effects are specified in §2 and §3, not here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/staff` | Register a staff member; the returned id is the `X-User-ID` a ProjectManager or StaffArchitect authenticates with | PrincipalArchitect |
| POST | `/consultants` | Register a consultant firm; the returned id is the `X-User-ID` a ConsultantRep authenticates with | PrincipalArchitect |
| POST | `/projects` | Create a project in DRAFT | PrincipalArchitect |
| GET | `/projects` | List projects | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/projects/{projectId}` | Fetch a project including its computed counters and postures | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/projects/{projectId}/state` | Suspend, reactivate or close a project | PrincipalArchitect |
| GET | `/projects/{id}/phases` | List the project's phases | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/projects/{id}/contract` | The project's contract, as an array of length 0 or 1 | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/contracts` | Create the project's single contract in DRAFT | PrincipalArchitect |
| GET | `/contracts/{contractId}` | Fetch a contract, including its `version` and WIP ledger fields | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/contracts/{contractId}/state` | Execute or terminate a contract | PrincipalArchitect |
| GET | `/contracts/{id}/change-orders` | List the contract's change orders | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/contracts/{id}/invoices` | List the contract's invoices | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/phases` | Add one of the four design phases to a project | ProjectManager, PrincipalArchitect |
| GET | `/phases/{phaseId}` | Fetch a phase with its fee allocation and earned value | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| PATCH | `/phases/{phaseId}` | Update a phase's `percent_complete` | ProjectManager |
| POST | `/phases/{phaseId}/state` | Activate, hold or complete a phase | ProjectManager, PrincipalArchitect |
| GET | `/phases/{id}/drawings` | List the phase's drawings | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/phases/{id}/permit-reviews` | List the phase's permit reviews | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/drawings` | Add a sheet to the drawing log | ProjectManager, StaffArchitect |
| POST | `/drawings/{drawingId}/state` | Issue or supersede a drawing | ProjectManager, StaffArchitect |
| POST | `/time-entries` | Log time against a phase | StaffArchitect, ProjectManager |
| GET | `/time-entries` | List time entries | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/time-entries/{timeEntryId}` | Fetch a time entry | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/time-entries/{timeEntryId}/state` | Submit, approve, reject, or reverse a time entry | StaffArchitect, ProjectManager, PrincipalArchitect |
| POST | `/expenses` | Log a reimbursable or non-reimbursable expense | StaffArchitect, ProjectManager |
| GET | `/expenses` | List expenses | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/expenses/{expenseId}` | Fetch an expense | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/expenses/{expenseId}/state` | Approve or reject an expense | ProjectManager, PrincipalArchitect |
| POST | `/rfis` | Open an RFI against the project, optionally citing an issued drawing | StaffArchitect, ProjectManager |
| GET | `/rfis` | List RFIs; filtering by `field_report_id` is the only discovery channel for cascade-created RFIs | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/rfis/{rfiId}` | Fetch an RFI | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/rfis/{rfiId}/state` | Return for clarification, re-open, answer, close or void an RFI | ProjectManager, StaffArchitect |
| POST | `/submittals` | A consultant firm lodges a submittal for review | ConsultantRep |
| GET | `/submittals` | List submittals | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/submittals/{submittalId}` | Fetch a submittal, including its computed `review_due_at` | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/submittals/{submittalId}/state` | Start review, record a review decision, or resubmit after revision | ProjectManager, ConsultantRep |
| POST | `/change-orders` | Draft an additional service or scope reduction against the contract | ProjectManager, PrincipalArchitect |
| POST | `/change-orders/{changeOrderId}/state` | Submit a change order, record the client's decision, or void an executed one | ProjectManager, PrincipalArchitect, ClientRep |
| POST | `/change-orders/{changeOrderId}/execute` | Execute a client-approved change order | PrincipalArchitect |
| POST | `/invoices` | Draft an invoice against the contract's unbilled WIP | ProjectManager, PrincipalArchitect |
| POST | `/invoices/{invoiceId}/state` | Issue or void an invoice | ProjectManager, PrincipalArchitect |
| POST | `/invoices/{invoiceId}/payments` | Record a client payment; advances the payment dimension only | PrincipalArchitect |
| POST | `/permit-reviews` | Open a permit/code review package against the project's CD phase | ProjectManager |
| POST | `/permit-reviews/{permitReviewId}/state` | Submit, record comments, resubmit, approve or reject a permit review | ProjectManager |
| POST | `/field-reports` | File a construction-administration field report | StaffArchitect, ProjectManager |
| GET | `/field-reports` | List field reports | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| GET | `/field-reports/{fieldReportId}` | Fetch a field report; immutable, with no update or delete surface | PrincipalArchitect, ProjectManager, StaffArchitect, ConsultantRep, ClientRep |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | PrincipalArchitect |

---

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_PROJECT_MANAGER` | 403 |
| `ERR_NOT_OWNER` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PROJECT_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_PHASE_NOT_FOUND` | 404 |
| `ERR_STAFF_NOT_FOUND` | 404 |
| `ERR_CONSULTANT_NOT_FOUND` | 404 |
| `ERR_DRAWING_NOT_FOUND` | 404 |
| `ERR_TIME_ENTRY_NOT_FOUND` | 404 |
| `ERR_EXPENSE_NOT_FOUND` | 404 |
| `ERR_RFI_NOT_FOUND` | 404 |
| `ERR_SUBMITTAL_NOT_FOUND` | 404 |
| `ERR_CHANGE_ORDER_NOT_FOUND` | 404 |
| `ERR_INVOICE_NOT_FOUND` | 404 |
| `ERR_PERMIT_REVIEW_NOT_FOUND` | 404 |
| `ERR_FIELD_REPORT_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_CONTRACT_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CONTRACT_NOT_EXECUTED` | 409 |
| `ERR_PROJECT_NOT_ACTIVE` | 409 |
| `ERR_CA_PHASE_NOT_ACTIVE` | 409 |
| `ERR_DRAWING_NOT_ISSUED` | 409 |
| `ERR_CONSULTANT_SUSPENDED` | 409 |
| `ERR_PERMIT_NOT_APPROVED` | 409 |
| `ERR_PERMIT_PHASE_NOT_READY` | 409 |
| `ERR_DUPLICATE_PROJECT_NUMBER` | 409 |
| `ERR_CONTRACT_ALREADY_EXISTS` | 409 |
| `ERR_DUPLICATE_PHASE_CODE` | 409 |
| `ERR_PHASE_WEIGHTS_INVALID` | 409 |
| `ERR_PHASE_ORDER_VIOLATION` | 409 |
| `ERR_OPEN_RFIS_BLOCK_COMPLETION` | 409 |
| `ERR_MAX_CLARIFICATION_ROUNDS` | 409 |
| `ERR_DUPLICATE_SHEET_NUMBER` | 409 |
| `ERR_FEE_DELTA_SIGN` | 409 |
| `ERR_TIME_ENTRY_OVERLAP` | 409 |
| `ERR_CONSULTANT_REVIEW_CAPACITY` | 409 |
| `ERR_LABOR_BUDGET_EXCEEDED` | 409 |
| `ERR_ZERO_INVOICE_AMOUNT` | 409 |
| `ERR_BILLING_THRESHOLD_NOT_MET` | 409 |
| `ERR_OVERPAYMENT` | 409 |
| `ERR_INVOICE_ALREADY_PAID` | 409 |

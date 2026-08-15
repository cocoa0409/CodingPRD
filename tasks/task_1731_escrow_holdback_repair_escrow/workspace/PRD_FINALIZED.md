# Escrow Holdback Administration API — Product Requirements Document

## 1. Introduction

When a property sale closes with repairs still outstanding, the title/escrow company withholds funds in a repair escrow — a holdback — and becomes the referee of a delicate multi-party workflow. The withheld amount must be sized from a contractor estimate plus a contingency cushion; the terms must be approved by the lender and, where one is party to the file, the insurer; a contractor must be selected from competing bids; no dollar may move until an inspection verifies the work; the completion deadline must be policed, with extensions for weather-delayed exterior work; cost overruns must be funded by the responsible party before disbursements resume; disputes between buyer and seller must freeze the money until resolved; and at the end — whether the work completes or the deadline lapses — the trust account must be emptied exactly, to the cent, according to the agreed disposition rules.

This document specifies the API of the Escrow Holdback Administration service, mounted under the `/escrow` prefix. It is written for the engineers who will implement it. Section 2 fixes the system-wide contract every endpoint obeys: authentication, the response envelope, pagination, the logical clock, integer-cent arithmetic with pinned rounding orders, the trust ledger, optimistic concurrency, and the order in which validations fire. Section 3 narrates the business workflows — file opening, approval circuits, bidding, inspections, draws, shortfalls, extensions, disputes, expiration, and closing — and scatters the operative rules into the prose where they apply. Section 4 summarizes the endpoints and Section 5 catalogues the error codes.

## 2. Global Specifications & System-Wide Principles

This section defines the rules, principles, and boilerplate that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. The system recognizes exactly seven roles, spelled precisely as follows: `EscrowOfficer`, `Buyer`, `Seller`, `Lender`, `Insurer`, `Contractor`, and `Inspector`. A request whose `X-User-Role` header is missing or is not one of these seven values, or whose `X-User-ID` header is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A well-authenticated caller whose role is not in the target endpoint's allowed role list is rejected with `ERR_FORBIDDEN` (HTTP 403).

For each of the seven roles individually — `EscrowOfficer`, `Buyer`, `Seller`, `Lender`, `Insurer`, `Contractor`, and `Inspector` — `X-User-ID` is an opaque operator identifier not tied to the `id` of any persisted entity. The server records it on the resources the caller creates or decides (for example, as `buyer_user_id` on the escrow file, `contractor_user_id` on a bid, or `approver_user_id` on an approval), but it never compares `X-User-ID` to any resource's own `id`. Party-ownership checks instead compare `X-User-ID` against the stored user-id field reserved for the action being attempted: the escrow file's `buyer_user_id` for bid selection; the file's `lender_user_id` or `insurer_user_id` (matching the approval's role) for approval decisions; the engaged contractor's `contractor_user_id` for draw requests and completion submissions; the assigned `inspector_user_id` for inspection reports; and the file's `buyer_user_id` or `seller_user_id` for opening a dispute. A mismatch on any such check is rejected with `ERR_NOT_FILE_PARTY` (HTTP 403).

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

List endpoints paginate through the query parameters `limit` and `offset`. When `limit` is omitted it defaults to 10; its minimum is 1 and its maximum is 100. `offset` defaults to 0 and counts the number of items skipped. Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless a more specific rule applies, every list endpoint returns its resources ordered by `created_at` ascending; resources whose creation timestamps are equal keep their insertion (append) order. Two refinements exist. A holdback's approvals list orders by `created_at` ascending with ties broken by `approver_role` ascending. A holdback's ledger entries are listed in ascending `seq` order — which is the chronological append order of the ledger.

### 2.4. The Logical Clock and Calendar Semantics

The service runs on a logical clock, never on wall-clock time. Before any explicit set, the clock reads exactly 2026-08-01T00:00:00Z, and the server never falls back to the host's wall clock under any circumstances. An `EscrowOfficer`-only, test-driving capability advances the clock: it accepts a target instant in the `to_iso8601` field, moves the logical clock to that instant, and answers with the clock's new reading in the `current_utc` field with HTTP 200. Every deadline, expiry, and extension-window comparison in this document reads the UTC calendar date of this logical clock — not the request arrival time, not any client-supplied date.

Two time representations coexist. Calendar-date fields — `closing_date`, `work_deadline_date`, `hard_stop_date`, `effective_deadline_date`, and `completion_deadline_date` — are ISO `YYYY-MM-DD` dates. Timestamp fields — `created_at`, `updated_at`, `started_at`, `submitted_completion_at`, `reported_at`, `approved_at`, `paid_at`, `decided_at`, `resolved_at`, `deposited_at`, and the inspection scheduling bounds — are ISO 8601 UTC instants with three fractional digits.

### 2.5. Common Resource Properties

Every persisted resource carries an `id`, a server-minted UUID with no type prefix, and a `created_at` timestamp recording when the resource was created. Every resource except the trust ledger entry additionally carries `updated_at`, refreshed on any mutation of the resource, and `version`, an integer that increments by one on every mutation. The trust ledger entry is the single exception to this convention: because entries are immutable once appended, a ledger entry carries only `id` and `created_at`; both `updated_at` and `version` are absent from it.

### 2.6. Money, Integer Cents, and Pinned Rounding

All monetary values in the system — estimates, bids, holdback amounts, draw amounts, pledges, ledger entries, balances — are integer cents. Whenever a multiplication would produce a fractional cent, the result is rounded half-up to the nearest whole cent (a fractional part of exactly one half rounds up), and this rounding is applied at the final multiplication only, never to intermediate terms.

Where a sum of money must be split equally between buyer and seller, the rounding order is pinned — and it is deliberately different at the two split sites. In the shortfall-pledge split, the buyer's pledge is the half rounded half-up first, and the seller's pledge is the residual (the total minus the buyer's pledge). In the closing-waterfall split, the seller's share is the half rounded half-up first, and the buyer's share is the residual. Rounding both shares independently is forbidden: on odd cent amounts the two independently rounded halves drift apart from the total by a cent, and the residual rule is what keeps the trust account exactly balanced.

### 2.7. The Trust Ledger and Balance Invariants

Every movement of money into or out of a holdback's trust account is recorded as an immutable ledger entry carrying `holdback_id`, `seq`, `entry_type`, `amount_cents`, `running_balance_cents`, and `memo`. The `seq` field is a per-holdback monotonic sequence starting at 1 and assigned in append order; within a single request that posts several entries (the closing waterfall), `seq` fixes the entries' relative order. The `entry_type` is one of `FUNDING`, `DRAW_DEBIT`, `SHORTFALL_DEPOSIT`, `RETURN_TO_SELLER`, `RELEASE_TO_BUYER`, or `REFUND_TO_SOURCE`. The `amount_cents` of an entry is signed: credits into trust are positive and debits out of trust are negative. Each entry's `running_balance_cents` is the previous entry's `running_balance_cents` plus this entry's signed amount; the first entry's running balance equals its own amount. The `memo` is a human-readable provenance note describing why the entry exists.

Two invariants hold after every ledger mutation — funding at creation, an amendment delta, a shortfall deposit, a draw payment, or the closing waterfall. First, the holdback's `trust_balance_cents` always equals the sum of the signed `amount_cents` over all of its entries, which always equals the last entry's `running_balance_cents`. Second, the holdback's `reserved_cents` always equals the sum of the `amount_cents` of its draw requests currently in `APPROVED` (approved-but-unpaid) state. Two further aggregates derive from the ledger: `total_disbursed_cents` is the sum of the magnitudes of all `DRAW_DEBIT` entries, and `total_shortfall_deposited_cents` is the sum of all `SHORTFALL_DEPOSIT` entries.

### 2.8. Optimistic Concurrency Control on Amendment

Exactly one endpoint participates in optimistic concurrency control: the holdback amendment operation, `POST /escrow/holdbacks/{id}/amend`. A request to amend a holdback must carry `expected_holdback_version`, a non-optional field holding the `version` of the holdback as the client last observed it. If that value does not match the holdback's current `version` — because another writer has amended or submitted the agreement since the client last read it — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), so that the client cannot silently discard terms it never saw. No other endpoint in the API accepts or requires a version field.

### 2.9. Validation Order of Precedence

When several checks could fail on the same request, the server evaluates them in a fixed order and returns the error of the first check that fails; later checks are never evaluated once an earlier one has fired. The precedence ladder, from first to last, is:

1. Authentication: the `X-User-Role` header must be present and one of the seven declared roles, and `X-User-ID` must be present — otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to all endpoints.
2. Authorization: the caller's role must appear in the endpoint's allowed roles — otherwise `ERR_FORBIDDEN` (HTTP 403). Applies to all endpoints.
3. Existence: every identifier in the path must exist, and any sub-resource identifier must belong to the parent named in the path — otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints.
4. Input shape, on every creation or action request: required fields present, enum members valid, integer ranges honored (the contingency percentage between 10 and 25 inclusive, requested extension days between 1 and 45 inclusive, monetary amounts strictly positive, a disputed amount zero or positive), `work_deadline_date` on or before `hard_stop_date`, `scheduled_start` strictly before `scheduled_end`, and no unknown body fields — otherwise `ERR_VALIDATION` (HTTP 400).
5. Ownership: the caller's `X-User-ID` must match the stored party id reserved for the action (the file's buyer selects bids; the lender and insurer of record decide their own approvals; the engaged contractor owns its bids, draw requests, and the work order's completion submission; the assigned inspector reports the inspection; a dispute's initiator is the file's buyer or seller) — otherwise `ERR_NOT_FILE_PARTY` (HTTP 403). One nuance: when the engagement this check would consult does not exist — no bid has been selected on the holdback — the ownership check is skipped and the later state gates fire instead.
6. Stale version, on holdback amendment only: `expected_holdback_version` must equal the holdback's current `version` — otherwise `ERR_STALE_VERSION` (HTTP 412).
7. Generic state preconditions on action endpoints: the attempted transition's from-state must hold (no wrong-from-state transitions, no actions on terminal resources, no duplicate decide/report/resolve/deposit, no reinspection without a prior failed final inspection) — otherwise `ERR_INVALID_STATE` (HTTP 409).
8. Domain state gates, evaluated in this fixed internal order: `ERR_HOLDBACK_NOT_ACTIVE` first (required by bid creation, bid selection, draw creation, draw approval, draw payment, inspection scheduling, extension creation, and extension decision); then `ERR_NO_SELECTED_CONTRACTOR`; then `ERR_DRAW_NOT_APPROVED`; then `ERR_APPROVAL_NOT_PENDING`; then `ERR_BID_NOT_SELECTABLE`; then `ERR_INSPECTION_NOT_PLANNED`; then `ERR_WORK_NOT_SUBMITTED` — all HTTP 409.
9. Disbursement freeze: while the holdback is disbursement-frozen, draw approval and draw payment are rejected with `ERR_DISPUTE_FROZEN` (HTTP 409).
10. Cardinality and uniqueness on creation endpoints: one holdback per escrow file (`ERR_HOLDBACK_ALREADY_EXISTS`), one `SUBMITTED` bid per contractor per holdback (`ERR_BID_ALREADY_SUBMITTED`), no bid creation once a selection exists (`ERR_WORK_ORDER_EXISTS`), one `SUBMITTED` draw at a time (`ERR_DRAW_ALREADY_OPEN`), one `PENDING` extension at a time (`ERR_EXTENSION_ALREADY_PENDING`), one `OPEN` dispute at a time (`ERR_DISPUTE_ALREADY_OPEN`) — all HTTP 409.
11. Weather eligibility on extension creation: a `WEATHER_EXTERIOR` request requires the holdback's `exterior_work_flag` to be true — otherwise `ERR_EXTENSION_NOT_WEATHER_ELIGIBLE` (HTTP 409).
12. Interval occupation on inspection scheduling, in this order: first the inspector-calendar check, then the property-slot check — `ERR_INSPECTOR_SCHEDULE_CONFLICT` and `ERR_INSPECTION_SLOT_OCCUPIED` respectively (both HTTP 409).
13. Verifying-inspection existence on draw approval — otherwise `ERR_NO_VERIFYING_INSPECTION` (HTTP 409).
14. Temporal windows: extension creation requires the clock date on or before the effective deadline (`ERR_EXTENSION_WINDOW_CLOSED`); expiration requires the clock date strictly after the effective deadline (`ERR_NOT_EXPIRED`); an extension grant must yield at least one day (`ERR_EXTENSION_EXCEEDS_HARD_STOP`) — all HTTP 409.
15. Shortfall coverage on draw payment: no pledge of the holdback may remain `PLEDGED` — otherwise `ERR_SHORTFALL_UNFUNDED` (HTTP 409).
16. Closeout aggregate on closing — otherwise `ERR_CLOSE_NOT_READY` (HTTP 409).

### 2.10. Nested Resources and Hierarchical Consistency

Requests that target nested resources are validated left to right along the path: each identifier must exist before the next is examined, and a sub-resource identifier must actually belong to the parent named in the path. The first identifier that fails — missing resource, or a child that does not belong to the path parent — is rejected with `ERR_NOT_FOUND` (HTTP 404), and no later validation runs.

Derived state propagates immediately across the hierarchy. Child events recompute parent-level derived fields the moment they occur — an inspection verdict recomputes the holdback's `work_verified` and `closeout_status`, a dispute recomputes `disbursement_frozen`, a granted extension recomputes `effective_deadline_date` and mirrors it onto the work order's `completion_deadline_date`, and a holdback's close bubbles up to recompute the escrow file's `status`. Each such mutation refreshes `updated_at` and increments `version` on the resource actually mutated.

## 3. Business Logic & Workflows

### 3.1. Opening the Escrow File and Sizing the Holdback

An `EscrowOfficer` opens an escrow file for a property transaction by supplying the `property_address`, the `closing_date`, and the party identifiers `buyer_user_id`, `seller_user_id`, and `lender_user_id`; the `insurer_user_id` is optional. Lender approval is always required on the file's holdback — the holdback's `lender_approval_required` is always true — whereas `insurer_approval_required` is true exactly when the file carries an `insurer_user_id`, so omitting the insurer at file creation permanently relieves the holdback of insurer approval. The file's `status` is derived rather than set directly: it reads `OPEN` while the file has no holdback or its holdback is in any non-terminal state, and it reads `CLOSED` once the holdback reaches `CLOSED_COMPLETED` or `CLOSED_EXPIRED`.

A file carries at most one holdback; attempting to create a second one on the same file fails with `ERR_HOLDBACK_ALREADY_EXISTS`. Creating the holdback takes the owning `escrow_file_id` plus the agreement terms: `repair_scope`, a `repair_estimate_cents` that must be strictly positive, a `contingency_pct` that must be an integer between 10 and 25 inclusive, a `funding_source` of `SELLER_PROCEEDS`, `BUYER_DEPOSIT`, or `SPLIT_EQUAL` recording who funded the holdback, an `overrun_responsibility` of `BUYER`, `SELLER`, or `SPLIT_EQUAL` fixing who must deposit cost overruns, and `expiration_terms` of `RETURN_TO_SELLER`, `RELEASE_TO_BUYER`, or `SPLIT_EQUAL` fixing the default remainder disposition if the holdback expires. The schedule is fixed by `work_deadline_date` — which must be on or before `hard_stop_date`, the absolute latest completion date that no extension may ever push the effective deadline past — and `exterior_work_flag` marks scopes eligible for weather extensions. Violations of these shapes and ranges are `ERR_VALIDATION`.

Sizing happens at creation. The `holdback_amount_cents` is the repair estimate scaled up by the contingency — the estimate multiplied by one hundred plus `contingency_pct`, divided by one hundred, rounded half-up to whole cents at this final multiplication. This provisional, estimate-sized amount is the amount actually funded: creation immediately withholds the funds by appending a `FUNDING` entry for the positive holdback amount as the ledger's `seq` 1, so `trust_balance_cents` starts equal to `holdback_amount_cents`. The holdback is born in `DRAFT`. Its `commitment_basis_cents` — the same scaling applied later to the selected bid instead of the estimate — stays null until a bid is selected. `granted_extension_days` starts at 0, so `effective_deadline_date` initially equals `work_deadline_date`; `selected_bid_id` and `disposition_override` start null; `work_verified` is false while no work order exists; `disbursement_frozen` is false while no dispute is `OPEN`; and `closeout_status` reads `NOT_READY`.

### 3.2. The Approval Circuit: Submission, Amendment, and Activation

Submitting moves a holdback from `DRAFT` to `PENDING_APPROVALS`; submitting from any other state is rejected with `ERR_INVALID_STATE`. Submission creates the approval requests the terms demand: always one `Approval` with `approver_role` `LENDER`, and a second with `approver_role` `INSURER` when insurer approval is required. Each new approval begins in `REQUESTED` with `approver_user_id`, `holdback_version_at_decision`, and `decided_at` all null. Every submission creates a fresh set of `REQUESTED` approvals.

The lender and insurer of record decide their own approvals. The caller's role must match the approval's `approver_role` and the caller's user id must match the file's corresponding `lender_user_id` or `insurer_user_id`; anyone else is turned away with `ERR_NOT_FILE_PARTY`. Only a `REQUESTED` approval can be decided — deciding one already decided, staled, or cancelled fails with `ERR_APPROVAL_NOT_PENDING`. A `decision` of `APPROVED` records the decider in `approver_user_id`, stamps `decided_at`, and pins `holdback_version_at_decision` to the holdback's current `version` at the moment of decision; immediately after each decision the system re-evaluates the holdback, and when every required approval is `APPROVED` and none remain `REQUESTED`, the holdback activates — `PENDING_APPROVALS` → `ACTIVE` — without any further client action. A `decision` of `REJECTED`, optionally accompanied by a `rejection_reason`, does the opposite: the approval becomes `REJECTED`, the holdback falls back from `PENDING_APPROVALS` to `DRAFT`, and every sibling approval still `REQUESTED` is cancelled — the rejection loop that sends the agreement back to the drafting table.

Amendment is the agreement's edit operation, available only while the holdback is in `DRAFT` or `PENDING_APPROVALS`; attempting it in any other state is `ERR_INVALID_STATE`. The request must carry `expected_holdback_version` matching the holdback's current `version`, per §2.8; a mismatch is `ERR_STALE_VERSION`. Any subset of the term fields — `repair_scope`, `repair_estimate_cents`, `contingency_pct`, `funding_source`, `overrun_responsibility`, `expiration_terms`, `work_deadline_date`, `hard_stop_date`, `exterior_work_flag` — may be supplied; omitted fields keep their current values. The amendment recomputes `holdback_amount_cents` from the (possibly updated) estimate and contingency, increments the holdback's `version` by one, and posts a funding-delta ledger entry so the trust reflects the new amount: a `FUNDING` entry for the positive difference when the recomputed amount exceeds what has been funded, a `REFUND_TO_SOURCE` entry for the difference when it is lower. Amending a holdback that sits in `PENDING_APPROVALS` additionally stales the entire live approval set — every `REQUESTED` and every `APPROVED` approval becomes `STALE`, so re-approval is required after resubmission — and returns the holdback to `DRAFT`. This staling is the deliberate serialization point between editing terms and collecting approvals: an approval pinned to an older `holdback_version_at_decision` can never carry an amended agreement into activation.

### 3.3. Contractor Bidding, Selection, and the Work Order

Bidding opens once the holdback is `ACTIVE`; creating a bid on a holdback in any other state fails with `ERR_HOLDBACK_NOT_ACTIVE`. A `Contractor` submits a bid with the target `holdback_id`, an `amount_cents` that must be strictly positive, and a `scope_text` narrative; the server records the caller as the bid's `contractor_user_id` and the bid enters `SUBMITTED`. Each contractor may hold at most one `SUBMITTED` bid per holdback — a repeat attempt fails with `ERR_BID_ALREADY_SUBMITTED` — and once any bid of the holdback has been selected, further bid creation is closed off with `ERR_WORK_ORDER_EXISTS`.

Selection belongs to the buyer of record: the caller's user id must equal the file's `buyer_user_id`, failing which the attempt is `ERR_NOT_FILE_PARTY`. The holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`), the chosen bid must still be `SUBMITTED` (`ERR_BID_NOT_SELECTABLE`), and no other bid of the holdback may already be `SELECTED` (`ERR_WORK_ORDER_EXISTS`). Selection is a cascade. The chosen bid becomes `SELECTED`; every other `SUBMITTED` bid of the holdback becomes `REJECTED` by the system. A work order springs into existence in `IN_PROGRESS`, copying `contractor_user_id` and `agreed_amount_cents` from the selected bid, stamping `started_at` with its creation time, and starting with `failed_final_count` at 0 and `submitted_completion_at` null. The holdback records the choice in `selected_bid_id` and computes its `commitment_basis_cents` from the selected bid's amount scaled by the contingency — the bid amount multiplied by one hundred plus `contingency_pct`, divided by one hundred, rounded half-up to whole cents. Where the selected bid differs from the original estimate, the commitment basis diverges from the funded provisional amount and exposes the underfunding gap. Exactly one work order ever exists per holdback, and its `completion_deadline_date` always mirrors the holdback's `effective_deadline_date`, including after extensions.

When the work is done, the engaged contractor — the caller whose user id equals the work order's `contractor_user_id`, anyone else drawing `ERR_NOT_FILE_PARTY` — declares completion, moving the work order from `IN_PROGRESS` to `COMPLETION_SUBMITTED` and stamping `submitted_completion_at`. Declaring completion from any other state is `ERR_INVALID_STATE`.

### 3.4. Inspections, Scheduling Discipline, and the Rework Loop

An `EscrowOfficer` schedules inspections on an `ACTIVE` holdback (`ERR_HOLDBACK_NOT_ACTIVE` otherwise), supplying `holdback_id`, the assigned `inspector_user_id`, a `purpose` of `DRAW_VERIFICATION`, `FINAL_VERIFICATION`, or `REINSPECTION`, and a window from `scheduled_start` to `scheduled_end` in which the start must be strictly before the end (`ERR_VALIDATION`). A `REINSPECTION` presupposes a prior failed final: scheduling one while the work order's `failed_final_count` is still zero is rejected with `ERR_INVALID_STATE`. A scheduled inspection begins in `PLANNED`.

Scheduling enforces two distinct occupation regimes, checked in a fixed order — the inspector's calendar first, the property's slot second — and only `PLANNED` inspections occupy time in either regime. The inspector-calendar regime is half-open across the inspector's entire book of work: a new window conflicts with any `PLANNED` inspection of the same `inspector_user_id` on any holdback when the new window begins before the existing window ends and the existing window begins before the new window ends. Because the end instant itself is free, pure adjacency is allowed: a new window beginning exactly when an existing one ends, or ending exactly when one begins, does not conflict. A violation is `ERR_INSPECTOR_SCHEDULE_CONFLICT`. The property-slot regime is closed within the single holdback: a new window conflicts with any `PLANNED` inspection of the same holdback when it begins before or exactly when the existing window ends and the existing window begins before or exactly when the new window ends — so here adjacency does conflict. A violation is `ERR_INSPECTION_SLOT_OCCUPIED`.

Reporting belongs to the assigned inspector: the caller's user id must equal the inspection's `inspector_user_id` (`ERR_NOT_FILE_PARTY`), and the inspection must still be `PLANNED` (`ERR_INSPECTION_NOT_PLANNED`). The report carries a `result` of `PASSED` or `FAILED` plus optional `result_notes`, and stamps `reported_at`. What the verdict does depends on the purpose. A `DRAW_VERIFICATION` report merely records the outcome; it never moves the work order. A `FINAL_VERIFICATION` or `REINSPECTION` report requires the work order to be sitting in `COMPLETION_SUBMITTED` — reporting otherwise fails with `ERR_WORK_NOT_SUBMITTED` — and it drives the verification state machine: `PASSED` moves the work order from `COMPLETION_SUBMITTED` to its terminal `VERIFIED` state, recomputing the holdback's `work_verified` to true and recomputing `closeout_status`; `FAILED` loops the work order back from `COMPLETION_SUBMITTED` to `IN_PROGRESS`, increments `failed_final_count` by one, recomputes `work_verified` to false, and drops `closeout_status` back to `NOT_READY`. The rework loop is thus cyclic: after a failure the contractor works, declares completion again, and faces another final inspection or a reinspection.

### 3.5. Draw Requests, Verification, Reservation, and Shortfall Funding

The engaged contractor bills the trust through draw requests. Creating one takes `holdback_id`, a strictly positive `amount_cents`, a `description` of the work billed, and an optional `is_final` flag — defaulting to false — that marks the final billing; the request enters `SUBMITTED` with `contractor_user_id` set to the caller and `approved_at` and `paid_at` null. The holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`). Contractor identity is enforced through the selection: when no bid has been selected yet there is no engagement to check against, the ownership check is skipped, and the request fails later at the state gate with `ERR_NO_SELECTED_CONTRACTOR`; once a bid is selected, a caller other than the selected contractor is rejected with `ERR_NOT_FILE_PARTY`. Only one `SUBMITTED` draw may exist at a time on a holdback (`ERR_DRAW_ALREADY_OPEN`). Notably, the requested amount may exceed the cash available in trust — that is the intended shortfall path — and a draw whose amount is exactly equal to the available balance is allowed.

Approval is the `EscrowOfficer`'s act and carries the heaviest guard chain. The draw must be `SUBMITTED` (any other state is `ERR_INVALID_STATE`); the holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`); the holdback must not be disbursement-frozen (`ERR_DISPUTE_FROZEN`); and a verifying inspection must exist: one in `PASSED` state whose `purpose` is `DRAW_VERIFICATION` or `FINAL_VERIFICATION` and whose `reported_at` is on or after the draw's `created_at` — among qualifying inspections the one with the latest `reported_at` serves as the verification of record, ties broken by the earliest `created_at`. Without one, approval fails with `ERR_NO_VERIFYING_INSPECTION`. Approval stamps `approved_at` and adds the draw's amount to the holdback's `reserved_cents`, the running total of approved-but-unpaid commitments. When judging how much cash a draw can safely call on, the system's authoritative measure is the net payable cap: `trust_balance_cents` minus the amounts reserved for the other `APPROVED`-but-unpaid draws, excluding the draw under consideration. The gross reading that ignores approved-unpaid commitments is a rejected reading — it overcommits cash — and the two diverge exactly when at least one other approved-unpaid draw exists.

Approval also runs the shortfall assessment. The projected excess is the sum of `total_disbursed_cents` and `reserved_cents` including this newly approved draw, minus the sum of `holdback_amount_cents` and `total_shortfall_deposited_cents`. Only a projected excess strictly greater than zero creates obligations; a projected excess of exactly zero creates none. When positive, pledges are created per the holdback's `overrun_responsibility`: `BUYER` creates one pledge assigned to the buyer for the full excess; `SELLER` creates one assigned to the seller; `SPLIT_EQUAL` creates two — the buyer's pledge is half the excess rounded half-up to whole cents (the buyer's side is rounded first), and the seller's pledge is the residual, the excess minus the buyer's pledge. Each pledge records its `payer_role`, resolves `payer_user_id` from the file's buyer or seller id, carries its `amount_cents`, and sits in `PLEDGED` with `deposited_at` null. When the pledged funds arrive, an `EscrowOfficer` records the deposit: the pledge moves from `PLEDGED` to `DEPOSITED` (depositing one already deposited is `ERR_INVALID_STATE`), a `SHORTFALL_DEPOSIT` entry for the positive amount is appended, `trust_balance_cents` and `total_shortfall_deposited_cents` each grow by that amount, and `deposited_at` is stamped.

Payment disburses an approved draw. The draw must be `APPROVED`: paying a `SUBMITTED` draw fails with `ERR_DRAW_NOT_APPROVED`, while paying one already `PAID` or `CANCELLED` is `ERR_INVALID_STATE`. The holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`), must not be disbursement-frozen (`ERR_DISPUTE_FROZEN`), and must have no `PLEDGED` shortfall pledge outstanding — unfunded pledges block payment with `ERR_SHORTFALL_UNFUNDED` until every pledge is deposited. Payment appends a `DRAW_DEBIT` entry for the negative amount, reduces `trust_balance_cents` by the amount, grows `total_disbursed_cents` by the amount, releases the reservation by reducing `reserved_cents` by the amount, stamps `paid_at`, and moves the draw to `PAID`.

### 3.6. Deadline Extensions, Weather Eligibility, and the Hard Stop

Either party to the sale — a `Buyer` or a `Seller` — may ask for more time by creating an extension request with `holdback_id`, a `reason` of `WEATHER_EXTERIOR`, `SUPPLY_DELAY`, or `OTHER`, a `requested_days` integer between 1 and 45 inclusive, and an `evidence_ref` pointing at the supporting material such as a weather report. The request is born `PENDING`, records the caller as `requester_user_id`, and leaves `granted_days` null until granted and `decided_at` null until decided. The gates: the holdback must be `ACTIVE` (`ERR_HOLDBACK_NOT_ACTIVE`); the request must arrive while the clock date is on or before the `effective_deadline_date` — a request lodged on the deadline date itself is allowed, one lodged after it fails with `ERR_EXTENSION_WINDOW_CLOSED`; a `WEATHER_EXTERIOR` request requires the holdback's `exterior_work_flag` to be true, failing with `ERR_EXTENSION_NOT_WEATHER_ELIGIBLE` on interior-only scopes; and at most one `PENDING` request may exist at a time (`ERR_EXTENSION_ALREADY_PENDING`).

Decision belongs to the `EscrowOfficer`, and the holdback must still be `ACTIVE` whether the outcome is grant or deny. The request must be `PENDING`; re-deciding a decided or cancelled request is `ERR_INVALID_STATE`. The `decision` is `GRANTED` or `DENIED`, with an optional `decision_note` accepted alongside it. A grant is computed, never taken at face value: the granted days are the smallest of four quantities — the `requested_days`; a per-request cap of 21 days when the reason is `WEATHER_EXTERIOR` and 7 days for any other reason; the remaining lifetime allowance, which is 45 days minus the sum of granted days across all previously `GRANTED` requests of the holdback; and the hard-stop headroom, the number of whole days from the current `effective_deadline_date` to the `hard_stop_date`. If that computed grant is not at least one full day, the grant is rejected with `ERR_EXTENSION_EXCEEDS_HARD_STOP` and nothing changes. Otherwise the request stores its computed `granted_days`, stamps `decided_at`, and the holdback absorbs the extension: `granted_extension_days` grows by the granted amount, `effective_deadline_date` is recomputed as `work_deadline_date` plus the total granted days, and the work order's `completion_deadline_date` mirrors the new effective deadline. The hard stop is absolute — no sequence of grants may push the effective deadline past `hard_stop_date`. A `DENIED` decision stamps `decided_at` and adds no days.

### 3.7. Disputes and the Disbursement Freeze

A buyer or seller who believes the arrangement has gone wrong opens a dispute with `holdback_id`, a `category` of `WORK_QUALITY`, `DRAW_DENIAL`, `DEADLINE`, `EXPENSE_RESPONSIBILITY`, or `OTHER`, a `claimed_amount_cents` that may be zero or any positive amount, and a `statement` of their case. The server records `initiator_role` from the caller's role and `initiator_user_id` from the caller's id, which must match the file's `buyer_user_id` or `seller_user_id` — anyone else is `ERR_NOT_FILE_PARTY`. One `OPEN` dispute at a time per holdback: a second attempt fails with `ERR_DISPUTE_ALREADY_OPEN`. The moment a dispute stands `OPEN`, the holdback's `disbursement_frozen` recomputes to true, and while any dispute remains `OPEN` every draw approval and every draw payment is rejected with `ERR_DISPUTE_FROZEN` — the freeze is what protects the trust while the parties argue.

Resolution is the `EscrowOfficer`'s judgment call on an `OPEN` dispute (resolving one already resolved is `ERR_INVALID_STATE`). The `resolution` is `FOR_BUYER`, `FOR_SELLER`, or `SPLIT`, moving the dispute to `RESOLVED_BUYER`, `RESOLVED_SELLER`, or `RESOLVED_SPLIT` respectively; a `resolution_note` is recorded and `resolved_at` is stamped. Once no dispute of the holdback remains `OPEN`, the freeze recomputes to false and disbursements may resume. Resolution carries one further consequence with long reach: when the holdback is `EXPIRED` at resolve time, the resolution writes the holdback's `disposition_override` — `RELEASE_TO_BUYER` for `FOR_BUYER`, `RETURN_TO_SELLER` for `FOR_SELLER`, `SPLIT_EQUAL` for `SPLIT` — and that override, not the holdback's `expiration_terms`, will govern the remainder at the expiration close. Resolving a dispute while the holdback is in any other state sets no override.

### 3.8. Expiration and the Closing Waterfall

Expiration is an explicit officer action on an `ACTIVE` holdback, never an automatic system transition. Two preconditions guard it. The clock date must be strictly after the `effective_deadline_date` — expiring on the deadline date itself, or any earlier day, fails with `ERR_NOT_EXPIRED`, because equality on the deadline date does not expire. And the work must be unverified: a holdback whose work has been verified must be closed, not expired, so the attempt fails with `ERR_INVALID_STATE`. Expiration moves the holdback from `ACTIVE` to `EXPIRED` and cancels everything still open beneath it in one sweep: every `SUBMITTED` draw request becomes `CANCELLED`, every `PLANNED` inspection becomes `CANCELLED`, and every `PENDING` extension request becomes `CANCELLED`.

Closing is the terminal act, from either of two from-states with distinct readiness tests. From `ACTIVE`, closing requires the holdback's `closeout_status` to be `READY_TO_CLOSE` — which it is exactly when the holdback is `ACTIVE`, `work_verified` is true, no dispute is `OPEN`, and no shortfall pledge is `PLEDGED`; in every other configuration `closeout_status` reads `NOT_READY` and the close fails with `ERR_CLOSE_NOT_READY`. From `EXPIRED`, closing requires that no dispute is `OPEN` and no pledge is `PLEDGED`, failing otherwise with `ERR_CLOSE_NOT_READY`.

The close itself runs the disbursement waterfall. Step one pays every still-`APPROVED` draw in `approved_at` ascending order, ties broken by `created_at` ascending: each draw gets its `DRAW_DEBIT` entry for the negative amount, is stamped `paid_at`, and moves to `PAID`. Step two computes the remainder — the `trust_balance_cents` left after step one. Step three disposes of the remainder. On the completed path the disposition basis is the holdback's `funding_source`: `SELLER_PROCEEDS` returns the entire remainder to the seller through a single `RETURN_TO_SELLER` entry, `BUYER_DEPOSIT` releases it to the buyer through a single `RELEASE_TO_BUYER` entry, and `SPLIT_EQUAL` splits it. On the expired path the basis is the `disposition_override` when one was set by dispute resolution, otherwise the holdback's `expiration_terms`: `RETURN_TO_SELLER` sends the whole remainder to the seller, `RELEASE_TO_BUYER` sends it to the buyer, and `SPLIT_EQUAL` splits it. The split is pinned: the seller's share is half the remainder rounded half-up to whole cents — the seller's side is rounded first — and the buyer's share is the residual, the remainder minus the seller's share; the `RETURN_TO_SELLER` entry is appended before the `RELEASE_TO_BUYER` entry. When the waterfall finishes, the trust balance is exactly zero — that is the closing invariant — the holdback settles into `CLOSED_COMPLETED` or `CLOSED_EXPIRED` (both terminal), and the escrow file's `status` recomputes to `CLOSED` in the same breath.

## 4. Endpoint Definitions

Endpoints that create a new resource — the escrow file, the holdback, bids, inspections, draw requests, extension requests, and disputes — answer `201 Created`. Every other operation, including all reads, all state-changing actions on existing resources, and the clock capability, answers `200 OK` on success. Request payloads, derived fields, cascades, and guard chains are specified in §2 and §3; this table is only the routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/escrow/_clock/set_current_utc` | Set the logical clock (test-driving) | EscrowOfficer |
| POST | `/escrow/files` | Open an escrow file for a property transaction | EscrowOfficer |
| GET | `/escrow/files/{id}` | Get an escrow file | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| GET | `/escrow/files/{id}/holdbacks` | List the holdbacks of an escrow file | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/holdbacks` | Create a holdback agreement; funds are withheld at creation | EscrowOfficer |
| GET | `/escrow/holdbacks/{id}` | Get a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/holdbacks/{id}/submit` | Submit a DRAFT holdback for lender/insurer approval | EscrowOfficer |
| POST | `/escrow/holdbacks/{id}/amend` | Amend the terms of a DRAFT or PENDING_APPROVALS holdback (OCC-guarded) | EscrowOfficer |
| POST | `/escrow/holdbacks/{id}/expire` | Expire an ACTIVE holdback past its effective deadline with work unverified | EscrowOfficer |
| POST | `/escrow/holdbacks/{id}/close` | Close an ACTIVE (verified) or EXPIRED holdback; runs the disbursement waterfall | EscrowOfficer |
| GET | `/escrow/holdbacks/{id}/approvals` | List the approvals of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/approvals/{id}/decide` | Lender or insurer approves or rejects their approval request | Lender, Insurer |
| POST | `/escrow/bids` | Contractor submits a bid on an ACTIVE holdback | Contractor |
| GET | `/escrow/holdbacks/{id}/bids` | List the bids of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/bids/{id}/select` | Buyer of record selects a bid; creates the work order and rejects competing bids | Buyer |
| GET | `/escrow/holdbacks/{id}/work-orders` | List the work orders of a holdback (at most one) | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/work-orders/{id}/submit-completion` | Engaged contractor declares the work complete | Contractor |
| POST | `/escrow/inspections` | Schedule an inspection on an ACTIVE holdback | EscrowOfficer |
| GET | `/escrow/holdbacks/{id}/inspections` | List the inspections of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/inspections/{id}/report` | Assigned inspector reports PASSED or FAILED | Inspector |
| POST | `/escrow/draw-requests` | Engaged contractor requests a draw | Contractor |
| GET | `/escrow/holdbacks/{id}/draw-requests` | List the draw requests of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/draw-requests/{id}/approve` | Approve a draw after verification; reserves cash and assesses shortfall | EscrowOfficer |
| POST | `/escrow/draw-requests/{id}/pay` | Disburse an approved draw | EscrowOfficer |
| POST | `/escrow/extension-requests` | Buyer or seller requests a completion-deadline extension | Buyer, Seller |
| GET | `/escrow/holdbacks/{id}/extension-requests` | List the extension requests of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/extension-requests/{id}/decide` | Grant (possibly partially) or deny an extension request | EscrowOfficer |
| POST | `/escrow/disputes` | Buyer or seller opens a dispute, freezing disbursements | Buyer, Seller |
| GET | `/escrow/holdbacks/{id}/disputes` | List the disputes of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/disputes/{id}/resolve` | Resolve a dispute; on an EXPIRED holdback the resolution overrides expiration terms | EscrowOfficer |
| GET | `/escrow/holdbacks/{id}/shortfall-pledges` | List the shortfall pledges of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |
| POST | `/escrow/shortfall-pledges/{id}/deposit` | Record receipt of pledged shortfall funds | EscrowOfficer |
| GET | `/escrow/holdbacks/{id}/ledger-entries` | List the trust ledger entries of a holdback | EscrowOfficer, Buyer, Seller, Lender, Insurer, Contractor, Inspector |

## 5. Error Code Catalogue

The trigger condition for each error is specified where the corresponding rule lives in §2 and §3; this table is only the identifier-to-status mapping.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FILE_PARTY` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_HOLDBACK_ALREADY_EXISTS` | 409 |
| `ERR_HOLDBACK_NOT_ACTIVE` | 409 |
| `ERR_NO_SELECTED_CONTRACTOR` | 409 |
| `ERR_APPROVAL_NOT_PENDING` | 409 |
| `ERR_BID_ALREADY_SUBMITTED` | 409 |
| `ERR_BID_NOT_SELECTABLE` | 409 |
| `ERR_WORK_ORDER_EXISTS` | 409 |
| `ERR_DRAW_ALREADY_OPEN` | 409 |
| `ERR_DRAW_NOT_APPROVED` | 409 |
| `ERR_NO_VERIFYING_INSPECTION` | 409 |
| `ERR_DISPUTE_FROZEN` | 409 |
| `ERR_SHORTFALL_UNFUNDED` | 409 |
| `ERR_WORK_NOT_SUBMITTED` | 409 |
| `ERR_INSPECTOR_SCHEDULE_CONFLICT` | 409 |
| `ERR_INSPECTION_SLOT_OCCUPIED` | 409 |
| `ERR_INSPECTION_NOT_PLANNED` | 409 |
| `ERR_EXTENSION_ALREADY_PENDING` | 409 |
| `ERR_EXTENSION_WINDOW_CLOSED` | 409 |
| `ERR_EXTENSION_NOT_WEATHER_ELIGIBLE` | 409 |
| `ERR_EXTENSION_EXCEEDS_HARD_STOP` | 409 |
| `ERR_NOT_EXPIRED` | 409 |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 |
| `ERR_CLOSE_NOT_READY` | 409 |

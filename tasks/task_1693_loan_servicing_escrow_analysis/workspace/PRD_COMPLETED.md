# Loan Servicing Escrow Analysis API — Product Requirements Document

## 1. Introduction

A mortgage servicer's escrow department sits between two unforgiving masters: the calendar and the ledger. Property tax installments fall due on statutory dates, hazard and flood policies lapse at midnight on their coverage end, and RESPA Regulation X dictates exactly how quickly a servicer must acknowledge a borrower's notice of error, how large a cushion may be collected, and how soon a surplus must be refunded. Today these obligations are tracked across spreadsheets and inbox reminders, and the failure modes are expensive — a missed tax installment compounds penalties at county rates, a lapsed hazard policy that is not force-placed within the required notice windows leaves the collateral uninsured, and an escrow analysis computed against the wrong starting balance produces a payment-change notice the servicer cannot defend in an audit.

This document specifies an API for running the full escrow servicing lifecycle on a single deterministic ledger: onboarding loans and their escrow accounts, maintaining projected expense line items, verifying and paying third-party payees under segregation of duties, posting borrower deposits, monitoring insurance coverage and tax delinquency, running the annual escrow analysis with its shortage, deficiency, and surplus determination, issuing payment-change notices on RESPA-conformant timing, fronting corporate advances when the account runs short, and resolving borrower-asserted errors with a correction cascade that reopens the affected analysis. Every mutation is immediately visible, every balance is reconstructible from the ledger, and a controllable logical clock drives all date-sensitive transitions so the entire servicing year can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's role. A request missing either header, or carrying a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is well-formed but not on the endpoint's authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

Six roles exist, spelled exactly as follows: `ComplianceOfficer`, `EscrowAnalyst`, `DisbursementProcessor`, `PayeeVerifier`, `InsuranceSpecialist`, and `Borrower`.

When `X-User-Role` is `ComplianceOfficer`, `EscrowAnalyst`, `DisbursementProcessor`, `PayeeVerifier`, or `InsuranceSpecialist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires an audit anchor — for example `created_by_user_id` on a payee, `verified_by_user_id` on a verification, `scheduled_by_user_id` and `released_by_user_id` on a disbursement, `assigned_to_user_id` and `resolved_by_user_id` on an error case — and compares it against those recorded fields only where a segregation-of-duties rule says so; it is never compared to any entity's `id`.

When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the acting borrower's `Loan`; ownership checks on any borrower-accessible resource compare the `id` of the loan that owns the target resource — directly, or through the resource's escrow account and, for notices, through the analysis's escrow account — to `X-User-ID`. A borrower acting on a resource owned by a different loan is rejected with `ERR_BORROWER_NOT_OWNER` (HTTP 403).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the server's wall clock — unlike entity timestamps such as `created_at`, it does not follow the logical clock of §2.5.
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

List endpoints accept the query parameters `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0; a non-integer or out-of-range `limit` or `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List results are returned in creation order, which coincides with `created_at` ascending unless the logical clock has been moved backward. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource has an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. All resources except ledger entries additionally carry `updated_at`, refreshed to the current logical time on every mutation, and `version`, an integer that increments by exactly 1 on every mutation of that resource — including mutations caused by system cascades and sweeps, so a single logical event may advance the versions of several entities at once. A resource is created with `version` 1 and `updated_at` equal to its `created_at`. Escrow ledger entries are the exception: they are immutable once posted, and they carry only `id` and `created_at` — neither `updated_at` nor `version` exists on them.

### 2.5. The Logical Clock and the Scheduled Sweep

The server runs on a logical clock, not wall-clock time. Before any call to the clock-setting capability, the logical clock reads exactly 2026-08-01T00:00:00Z and never falls back to wall-clock time. A `ComplianceOfficer`-only capability moves the clock to a supplied `to_iso8601` instant — any well-formed ISO 8601 datetime is accepted, including one earlier than the current reading — and returns `previous_utc`, `current_utc`, and `transitions_applied`, the number of entities the sweep transitioned; a companion read capability open to all roles returns `current_utc`. Everywhere this document says "now", "today", or "current date", it means this logical clock.

Setting the clock runs a deterministic sweep over the portfolio, in which each transitioned entity's `version` increments by 1:

- A payee in `VERIFIED` flips to `EXPIRED` when the current date is strictly after its `verification_expires_at`, and every disbursement paying that payee that is sitting in `SCHEDULED` is cascaded to `BLOCKED`.
- Insurance lapse and expiry detection runs: a policy in `ACTIVE` whose `coverage_end_date` is before the current date becomes `LAPSED` when no other `ACTIVE` policy of the same `policy_type` on the same loan covers the current date, and becomes `EXPIRED_CLOSED` when another `ACTIVE` policy of the same `policy_type` on the same loan does cover the current date.
- Tax records advance through `DUE_SOON`, `DELINQUENT`, `PENALTY_ACCRUING`, and `REDEMPTION_RISK` as described in §3.6, with penalty accrual recomputed on each pass.

### 2.6. Monetary Representation, Precision, and Rounding

All money is represented as integer cents — no floats anywhere. Every division or proration that produces a fractional cent rounds half-up to the nearest whole cent, at the pinned step each calculation defines; several calculations deliberately round each component first and then sum, and the pinned order is part of the specification, not an implementation detail. The one exception is the monthly shortage spread, which divides by 12 using floor (round down) and loads the remainder onto the first month, as detailed in §3.7.

### 2.7. The Escrow Ledger and Balance Conservation

Each escrow account's `balance_cents` is never stored as an independent number that can drift: it always equals the sum of `amount_cents` over every ledger entry posted to that account. Ledger entries carry an `entry_type` drawn from `DEPOSIT`, `DISBURSEMENT`, `DISBURSEMENT_RETURN`, `ADVANCE_ISSUED`, `ADVANCE_RECOVERY`, `SURPLUS_REFUND`, `FORCE_PLACEMENT_CHARGE`, `FORCE_PLACEMENT_REFUND`, and `ERROR_CORRECTION`; credits are positive amounts and debits are negative. Each entry records the `escrow_account_id` it belongs to, an input-supplied `effective_date` that drives chronological replay, a computed `running_balance_cents` (the balance after this entry when the ledger is replayed ordered by `effective_date` ascending with ties broken by creation order), the `source_entity_type` and `source_entity_id` of the entity that caused it, and a free-text `note` that defaults to an empty string — no write endpoint accepts a client-supplied `note`, so every entry carries the empty-string default. The account's ledger listing is always chronological in that same order and may be filtered by `entry_type`. Whenever an operation posts an entry, the account's `balance_cents` is recomputed by replay and the account's `version` increments.

### 2.8. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and each requires a non-optional version field carrying the client’s last observed `version` of the parent entity:

- Opening an analysis cycle on an escrow account requires `expected_escrow_account_version` equal to the account's current `version`. Creating a cycle legitimately supersedes an existing draft cycle, so a writer whose view of the account predates another writer's create would otherwise supersede a cycle it never saw; if the account's version has advanced since the client last read it, the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Rescheduling or re-amounting a disbursement requires `expected_disbursement_version` equal to the disbursement's current `version`. Reschedules and amount changes are both legitimate when applied to the current row, so a writer carrying a stale version would silently overwrite another writer's reschedule; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field.

### 2.9. Validation Order and Request Hygiene

When several checks could reject the same request, they are evaluated in a fixed priority order so the surfaced error is deterministic: first the presence and well-formedness of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); then role authorization (`ERR_FORBIDDEN_FOR_ROLE`); then borrower ownership on borrower-accessible endpoints (`ERR_BORROWER_NOT_OWNER`) — on endpoints nested directly under `/servicing/loans/{id}` the ownership check compares `X-User-ID` against that path id before any existence lookup, while on borrower endpoints nested under other resources (deposits under an escrow account, reinstatement under a policy, acknowledgment under a notice) the enclosing resource is resolved first, so a nonexistent enclosing id yields `ERR_NOT_FOUND` before ownership can be evaluated; then path identifier existence, resolved left-to-right along the URL so the leftmost nonexistent id is the one reported (`ERR_NOT_FOUND`, HTTP 404); then body foreign-key references such as `payee_id`, `line_item_id`, and `disbursement_id` (`ERR_REFERENCE_NOT_FOUND`, HTTP 422); then request shape — required fields present, enum members valid, dates well-formed ISO (`ERR_INVALID_REQUEST`, HTTP 400), with unknown body fields ignored silently rather than rejected; then optimistic-concurrency version equality (`ERR_STALE_VERSION`); then terminal-state lockout (`ERR_ALREADY_TERMINAL`, HTTP 409); then from-state validity for the attempted transition (`ERR_INVALID_STATE_TRANSITION`, HTTP 409); then the compliance-hold gate (`ERR_ACCOUNT_ON_HOLD`); then the loan-active gate (`ERR_LOAN_NOT_ACTIVE`); then segregation of duties (`ERR_SOD_VIOLATION`); then the force-placement notice windows (`ERR_NOTICE_WINDOW_NOT_MET`, `ERR_REMINDER_TOO_EARLY`); then the active-coverage bar (`ERR_ACTIVE_COVERAGE_EXISTS`); then the remaining temporal gates (`ERR_RELEASE_TOO_EARLY`, `ERR_EFFECTIVE_DATE_NOT_REACHED`, `ERR_EXTENSION_WINDOW_PASSED`, `ERR_PROJECTION_START_INVALID`); then uniqueness and duplicate constraints; then cross-entity state requirements; and finally amount rules. Nested resources are always validated left-to-right: a request naming an escrow account that does not exist fails with `ERR_NOT_FOUND` before any check on a child resource beneath it.

### 2.10. Two-Dimensional Account State

An escrow account's lifecycle is split into two independent dimensions stored on the same row. The first, `account_status`, walks `SETUP` → `ACTIVE` → (`SUSPENDED` ↔ `ACTIVE`) → `CLOSED`. The second, `hold_status`, walks `NONE` ↔ `COMPLIANCE_HOLD`. The two evolve independently: a compliance hold never blocks deposits, line-item maintenance, or `account_status` moves, and suspension never blocks hold placement. Both dimensions live on one row, so a write to either increments the account's `version` by 1.

## 3. Business Logic & Workflows

### 3.1. Boarding and Activating a Loan

A `ComplianceOfficer` boards a loan by supplying `loan_number` (unique across all loans — a duplicate is rejected with `ERR_DUPLICATE_LOAN_NUMBER`), `borrower_name`, `principal_balance_cents`, `monthly_pi_cents` (the principal-plus-interest portion only, excluding escrow — both integer cent fields must be non-negative, else `ERR_INVALID_REQUEST`), `closing_date` as an ISO date, and optionally `escrow_required`, which defaults to true. A new loan starts in `ONBOARDING` and ends its life in either `PAID_OFF` or `TRANSFERRED_OUT`, both terminal.

Before an `ONBOARDING` loan can be activated, a loan flagged `escrow_required` must already have an escrow account in `account_status` `ACTIVE`; activation without one is rejected with `ERR_ESCROW_NOT_ACTIVE`. Account setup is therefore deliberately allowed while the loan is still in `ONBOARDING` — the loan-active gate does not apply to escrow-account activation — whereas disbursement release, insurance policy creation, reinstatement, force-placement charging, and borrower deposits all require the loan to be `ACTIVE` and are otherwise rejected with `ERR_LOAN_NOT_ACTIVE`. Loan activation moves `ONBOARDING` → `ACTIVE` and increments the loan's `version`.

An `EscrowAnalyst` creates the loan's single escrow account; a second attempt is rejected with `ERR_ESCROW_ACCOUNT_EXISTS`, and requesting an account for a loan whose `escrow_required` is false is rejected with `ERR_INVALID_REQUEST`. Account creation itself is not gated on the loan's status — only the duplicate and `escrow_required` checks apply. The account is born with `account_status` `SETUP`, `hold_status` `NONE`, `balance_cents` 0, and `target_cushion_cents` 0, and it references its owning loan through `loan_id`. Because accounts are peer resources rather than URL-nested children, the reverse lookup from loan to account is served by the account listing filtered with the `loan_id` query parameter. Account activation — an `EscrowAnalyst` action — requires at least one `ACTIVE` line item on the account, otherwise `ERR_INVALID_STATE_TRANSITION`. Upon activation the account's initial `monthly_escrow_cents` is set to the per-line monthly sum defined in §3.3, `target_cushion_cents` is recomputed, `next_analysis_due_date` is set to the loan's `closing_date` plus 12 months, and `last_analysis_year` remains null until the first analysis finalizes.

A `ComplianceOfficer` may suspend an `ACTIVE` account (`ACTIVE` → `SUSPENDED`) and later reinstate it (`SUSPENDED` → `ACTIVE`); each move increments the account's `version`. Independently, the same role may place a compliance hold (`NONE` → `COMPLIANCE_HOLD`) on any account that is not `CLOSED` — attempting it on a closed account is rejected with `ERR_ALREADY_TERMINAL` — and release the hold (`COMPLIANCE_HOLD` → `NONE`). While `hold_status` is `COMPLIANCE_HOLD`, three operations are blocked with `ERR_ACCOUNT_ON_HOLD`: releasing a disbursement, computing an analysis, and finalizing an analysis. Everything else — deposits, line-item maintenance, suspension and reinstatement — proceeds normally.

Two terminal exits exist for an `ACTIVE` loan. Payoff is rejected with `ERR_ADVANCE_OUTSTANDING` while any advance on the loan's escrow account is `OUTSTANDING` or `RECOVERING`. Transfer-out is rejected with `ERR_UNRESOLVED_ERROR_CASE` while any error case on the loan sits in `RECEIVED`, `ACKNOWLEDGED`, `INVESTIGATING`, or `EXTENDED`. Both transitions cascade identically: the escrow account moves to `CLOSED` (from either `ACTIVE` or `SUSPENDED`), any residual `balance_cents` greater than zero is returned to the borrower as a `SURPLUS_REFUND` ledger entry of negative the balance so the balance becomes exactly 0, every disbursement still `SCHEDULED` or `BLOCKED` moves to `CANCELLED`, and the loan's `version` increments. An account still in `SETUP` is left untouched by the cascade, and a loan with no escrow account at all simply transitions with no cascade.

### 3.2. Payee Onboarding and Verification Discipline

Every disbursement ultimately flows to a payee, and the servicer's first control is knowing the payee is real. A `DisbursementProcessor` registers a payee with its `payee_type` — one of `TAX_AUTHORITY`, `INSURANCE_CARRIER`, or `PMI_PROVIDER` — plus `legal_name`, `remit_to_address`, and `ach_routing_mask`. The payee is born `PENDING_VERIFICATION` with `created_by_user_id` anchored to the creator's `X-User-ID`, `verified_by_user_id` and `verified_at` null, and `verification_expires_at` null.

Verification is a `PayeeVerifier` action and is the system's first segregation-of-duties checkpoint: the verifier's `X-User-ID` must differ from `created_by_user_id`, and a self-verification attempt is rejected with `ERR_SOD_VIOLATION` (HTTP 409). A successful verify moves `PENDING_VERIFICATION` → `VERIFIED`, stamps `verified_by_user_id` and `verified_at`, and sets `verification_expires_at` to the calendar date exactly 365 days after the verification date. Rejection moves `PENDING_VERIFICATION` → `REJECTED`, which is terminal. Payees may be listed with the `verification_status` and `payee_type` filters.

A `VERIFIED` payee can be suspended — by a `PayeeVerifier` or a `ComplianceOfficer` — moving it to `SUSPENDED`, and the clock sweep moves it `VERIFIED` → `EXPIRED` once the current date passes `verification_expires_at`. Both moves carry the same conditional cascade: every disbursement paying this payee that is currently `SCHEDULED` flips to `BLOCKED`. Re-verification — from either `SUSPENDED` or `EXPIRED` back to `VERIFIED` — is the same verify action with the same segregation-of-duties precondition; it refreshes `verified_at` and `verification_expires_at`, and every disbursement of this payee sitting in `BLOCKED` returns to `SCHEDULED` (those whose account is under a compliance hold are not unblocked into releasability — the hold gate still applies at release time). The payee's `version` increments on each of these transitions, and each cascaded disbursement's `version` increments as well.

### 3.3. Projected Expenses: Line Items and the Cushion

An `EscrowAnalyst` builds the account's forward-looking expense picture one line item at a time. Creating a line item names the payee via `payee_id` (the payee must be `VERIFIED`, else `ERR_PAYEE_NOT_VERIFIED`), an `expense_type` of `PROPERTY_TAX`, `HAZARD_INSURANCE`, `FLOOD_INSURANCE`, or `PMI`, the `expected_annual_amount_cents` — which must be a positive integer, else `ERR_INVALID_AMOUNT` (HTTP 422) — the `installments_per_year` — which must be 1, 2, 4, or 12 — and the `first_due_date` of the first projected installment. Each installment's amount is the annual expectation divided by the number of installments, rounded half-up to whole cents; after the first due date, installments step forward by twelve divided by `installments_per_year` months each — month arithmetic clamps the day-of-month to the target month's length, each installment is computed from `first_due_date` so clamping never accumulates, and the same clamped month arithmetic applies wherever this document adds months to a date. At most one `ACTIVE` line item per `expense_type` may exist on an account; a duplicate is rejected with `ERR_DUPLICATE_LINE_ITEM_TYPE`. A new line item starts `ACTIVE`.

The RESPA cushion cap is derived continuously: `target_cushion_cents` is the sum of `expected_annual_amount_cents` over the account's `ACTIVE` line items (removed items never count), divided by 6 — the statutory maximum of one-sixth of annual disbursements — rounded half-up to whole cents. This cap is recomputed on every line-item write: creating a line item, patching an `ACTIVE` line item's `expected_annual_amount_cents`, `installments_per_year`, or `first_due_date`, and removing a line item (`ACTIVE` → `REMOVED`, which is terminal — patching or re-removing a `REMOVED` item is rejected with `ERR_ALREADY_TERMINAL`) each recompute the cushion and increment both the line item's and the account's `version`.

The initial monthly escrow requirement uses a pinned rounding order that matters to the cent: for each `ACTIVE` line item, divide its `expected_annual_amount_cents` by 12 and round that line's monthly share half-up to whole cents first; only then sum across lines. Rounding after summing is the wrong order — three lines of 100001 cents each yield 3 × 8333 = 24999 cents per month under the pinned order, versus 25000 if the annual total is divided first. This per-line-then-sum value becomes the account's `monthly_escrow_cents` at activation and stays fixed until a payment-change notice is applied.

### 3.4. Deposits, Disbursements, and Corporate Advances

Money enters the account through borrower escrow deposits, posted by an `EscrowAnalyst` or the `Borrower` (own loan only, enforced by the ownership check) with an `amount_cents` and an `effective_date`. The deposit posts a `DEPOSIT` ledger entry of positive `amount_cents`, then immediately runs the advance recovery waterfall described below, then recomputes `balance_cents` and increments the account's `version`. The endpoint returns HTTP 201 with the posted `DEPOSIT` entry as `data`; the entry's `source_entity_type` is `Deposit` and its `source_entity_id` is the entry's own `id`.

Money leaves through disbursements. A `DisbursementProcessor` schedules one by naming the `line_item_id` (which must be `ACTIVE` and belong to the same account — naming another account's line item is rejected with `ERR_INVALID_REQUEST`, HTTP 400), the `payee_id` (which must be `VERIFIED` at creation), the `amount_cents` (a positive integer), the obligation's `due_date`, and a `scheduled_release_date` before which release is refused. The new disbursement is `SCHEDULED`, with `scheduled_by_user_id` anchored to the creator, `released_by_user_id`, `released_at`, `cleared_at`, `returned_at`, and `ledger_entry_id` all null, and `late_release` false. While still `SCHEDULED`, a processor may revise its `amount_cents`, `due_date`, or `scheduled_release_date` — this is the OCC-guarded write of §2.8, so the request must carry `expected_disbursement_version`. Either the scheduler or a peer may cancel from `SCHEDULED` or `BLOCKED`, landing in the terminal `CANCELLED`.

Release is the second segregation-of-duties checkpoint and the most heavily gated action in the system. The releasing processor's `X-User-ID` must differ from `scheduled_by_user_id`, else `ERR_SOD_VIOLATION`. The account's `hold_status` must be `NONE` (`ERR_ACCOUNT_ON_HOLD`), its `account_status` must be `ACTIVE` (`ERR_INVALID_STATE_TRANSITION`), and the owning loan must be `ACTIVE` (`ERR_LOAN_NOT_ACTIVE`). The current date must be on or after `scheduled_release_date`, else `ERR_RELEASE_TOO_EARLY`. The payee must still be `VERIFIED` at release time, else `ERR_PAYEE_NOT_VERIFIED`. Finally, if the account's funds are insufficient and the advance the release would auto-create would push the account's total outstanding advances above the cap, the release is rejected with `ERR_ADVANCE_CAP_EXCEEDED`.

A successful release posts a `DISBURSEMENT` ledger entry of negative `amount_cents` effective today, sets `late_release` to true when the release date is strictly after `due_date`, and stamps `released_by_user_id`, `released_at`, and the `ledger_entry_id` of the posted entry. If the debit would drive the balance below zero, the system fronts the difference: it creates an `EscrowAdvance` with `reason` `DISBURSEMENT_SHORTFALL`, `disbursement_id` pointing at this disbursement, and an `amount_cents` equal to the disbursement amount reduced by any positive pre-release balance — when the pre-release balance is zero or negative, the advance covers the entire amount — and posts an `ADVANCE_ISSUED` entry of positive that amount, so the post-release balance never drops below 0. Release increments both the disbursement's and the account's `version`.

From `RELEASED`, a disbursement either clears (`mark-cleared` sets `cleared_at`, terminal `CLEARED`) or comes back. A disbursement marked `RETURNED` posts a compensating `DISBURSEMENT_RETURN` entry of positive `amount_cents` effective today, restoring ledger conservation; if an advance tied to this disbursement exists and is still `OUTSTANDING` or `RECOVERING`, its outstanding amount is reduced by the smaller of its outstanding amount and the returned amount, an `ADVANCE_RECOVERY` entry of that reduction is posted, and the advance becomes `RECOVERED` if its outstanding reaches zero. The account balance is recomputed, `returned_at` is stamped, and both versions increment. `RETURNED` is terminal in practice: the terminal lockout (`ERR_ALREADY_TERMINAL`) covers only `CLEARED` and `CANCELLED`, so any further action on a `RETURNED` disbursement fails the from-state check with `ERR_INVALID_STATE_TRANSITION`.

Corporate advances — the servicer's own money fronted to keep the account whole — decompose rigidly: `outstanding_cents` is always `amount_cents` minus `recovered_cents` minus `written_off_cents`. An advance is born `OUTSTANDING` (auto-created ones carry system-computed amounts; a `ComplianceOfficer` may also create a manual advance by supplying `amount_cents` and a `reason` of `MANUAL_CORRECTION` — any other `reason` is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a non-positive `amount_cents` with `ERR_INVALID_AMOUNT` (HTTP 422) — which posts an `ADVANCE_ISSUED` entry, recomputes the balance, and increments the account's `version`; `reason` values `DISBURSEMENT_SHORTFALL` and `FORCE_PLACEMENT_PREMIUM` mark system-created advances). The advance cap is $10,000.00 (1,000,000 cents): creating an advance, automatic or manual, that would push the sum of `outstanding_cents` over all non-terminal advances of the account above the cap is rejected with `ERR_ADVANCE_CAP_EXCEEDED` (HTTP 422).

Recovery follows a fixed waterfall. Whenever a deposit posts — or a force-placement refund lands, per §3.5 — the incoming amount is allocated to the account's `OUTSTANDING` and `RECOVERING` advances oldest-first by `created_at` ascending, ties broken by larger `outstanding_cents` first. Each advance in turn absorbs the smaller of the remaining amount and its own outstanding: an `ADVANCE_RECOVERY` ledger entry of negative that amount, carrying the triggering inflow's `effective_date` (the deposit's own `effective_date`, or the current date for a force-placement refund), is posted against the advance, `recovered_cents` grows by it, and the advance moves `OUTSTANDING` → `RECOVERING` on a partial recovery (strictly between zero and full) or straight to `RECOVERED` when the outstanding reaches zero in one step; a `RECOVERING` advance likewise becomes `RECOVERED` when its outstanding reaches zero. The deposit's net effect on the balance is therefore the deposit amount minus the total recovered. An `EscrowAnalyst` may also recover directly from the account balance with a chosen `amount_cents`; the amount may not exceed the advance's outstanding (`ERR_RECOVERY_EXCEEDS_OUTSTANDING`, HTTP 422) nor the account balance (`ERR_INVALID_AMOUNT`, HTTP 422), and it posts the same `ADVANCE_RECOVERY` entry while incrementing both versions. A `ComplianceOfficer` may write off an `OUTSTANDING` or `RECOVERING` advance, moving it to the terminal `WRITTEN_OFF` with `written_off_cents` set to the full outstanding and `outstanding_cents` zeroed. `RECOVERED` and `WRITTEN_OFF` are both terminal: recovery or write-off attempts on them are rejected with `ERR_ALREADY_TERMINAL`.

### 3.5. Insurance Tracking, Lapse, and Force-Placement

Every loan's hazard and flood coverage is tracked as insurance policies. An `InsuranceSpecialist` or the `Borrower` (own loan only) registers a policy with `policy_type` (`HAZARD` or `FLOOD`), `carrier_name`, `policy_number`, `coverage_start_date`, `coverage_end_date`, and `annual_premium_cents` (which must be a positive integer, else `ERR_INVALID_AMOUNT`, HTTP 422); the loan must be `ACTIVE`. Coverage is a half-open interval — the start date is covered, the end date is not — and the end date must be after the start date. Two `ACTIVE` policies of the same `policy_type` on the same loan may not overlap: a new policy whose half-open interval intersects another's is rejected with `ERR_COVERAGE_OVERLAP`, while pure adjacency — one policy's start date equal to the other's end date — is not an overlap. A new policy starts `ACTIVE`, and policies may be listed with the `policy_type` and `status` filters.

Lapse arrives by two paths. The clock sweep moves `ACTIVE` → `LAPSED` when the coverage end has passed and no other `ACTIVE` same-type policy on the loan covers the current date; if replacement coverage does exist, the expiring policy instead goes `ACTIVE` → `EXPIRED_CLOSED` (terminal). Separately, an `InsuranceSpecialist` may report a mid-term carrier cancellation, moving `ACTIVE` → `LAPSED` immediately via the report-lapse action.

Once `LAPSED`, the RESPA force-placement notice sequence begins. The first notice (`LAPSED` → `NOTICE_1_SENT`, stamping `notice_1_sent_at`) has no waiting period. The reminder (`NOTICE_1_SENT` → `NOTICE_2_SENT`, stamping `notice_2_sent_at`) may not be sent until the current date is at least 30 days after the date of `notice_1_sent_at`, else `ERR_REMINDER_TOO_EARLY`. Charging the force-placement premium (`NOTICE_2_SENT` → `FORCE_PLACED`) requires both windows to have elapsed — the current date must be at least 45 days after the first notice's date and at least 15 days after the reminder's date, else `ERR_NOTICE_WINDOW_NOT_MET` — and is barred while any other `ACTIVE` same-type policy exists on the loan (`ERR_ACTIVE_COVERAGE_EXISTS`). The charge action takes `fp_premium_cents` and an optional `day_count_convention` — `ACT_365` (the default) or `CONTRACT_30_360` — which is fixed at charge time and later drives refund proration. Charging posts a `FORCE_PLACEMENT_CHARGE` entry of negative `fp_premium_cents`; when the balance is insufficient, an advance with `reason` `FORCE_PLACEMENT_PREMIUM` is created (subject to the same advance cap, `ERR_ADVANCE_CAP_EXCEEDED`) and an `ADVANCE_ISSUED` entry covers the shortfall so the balance never goes negative. The charge stamps `force_placed_at` and sets `fp_coverage_end` to the force-placement date plus 365 days, incrementing both the policy's and the account's `version`. If the loan has no escrow account at all, the charge still transitions the policy and sets its stamps but posts no ledger entry, creates no advance, and touches no account; the same applies to the force-placement refund.

The borrower can cure at any point before placement: reinstatement — available to an `InsuranceSpecialist` or the `Borrower` from `LAPSED`, `NOTICE_1_SENT`, or `NOTICE_2_SENT` alike — takes `new_coverage_start_date`, `new_coverage_end_date`, and optionally `new_annual_premium_cents`. The new end date must be after the current date (`ERR_INVALID_REQUEST`) and must not half-open-overlap another `ACTIVE` same-type policy on the loan (`ERR_COVERAGE_OVERLAP`); no ordering of the new end date against the new start date is enforced, and a supplied `new_annual_premium_cents` is accepted as any integer without a positivity check. Reinstatement returns the policy to `ACTIVE`, replaces its coverage dates and — when supplied — its premium, and resets both notice timestamps to null. An `InsuranceSpecialist` may instead cancel a policy outright from `ACTIVE` or `LAPSED`, landing in terminal `CANCELLED`.

Once force-placed, the premium is refundable when the borrower produces evidence coverage: another `ACTIVE` policy of the same `policy_type` on the same loan whose half-open coverage interval contains the current date — with no qualifying policy, the refund is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). When several qualify, the evidence policy is the one with the earliest `coverage_start_date`, ties broken by `created_at` ascending. The refund prorates the premium over the 365-day force-placement term according to the policy's pinned `day_count_convention`. Under `ACT_365`, the used days are the calendar days from the force-placement date to the evidence policy's creation date, exclusive, and the refund is the premium multiplied by the remaining days out of 365 — that is, 365 minus the used days — rounded half-up to whole cents. Under `CONTRACT_30_360`, the used days are computed on the 30/360 convention over a 360-day term, and the refund is the premium multiplied by 360 minus the used days, divided by 360, rounded half-up; the two conventions yield different refunds for the same dates. The result lands in `fp_refund_cents`, a `FORCE_PLACEMENT_REFUND` entry of positive that amount is posted effective today, and the refund is applied to the account's outstanding advances first — oldest-first FIFO by advance `created_at` through `ADVANCE_RECOVERY` entries — with any remainder staying in the balance. `refund_processed_at` is stamped, and `refund_timeliness` is computed as `ON_TIME` when the refund date is on or before the evidence policy's creation date plus 15 days, else `LATE`. The policy ends `REFUNDED`, terminal; both versions increment.

### 3.6. Tax Installment Monitoring and Penalty Accrual

An `EscrowAnalyst` registers each property-tax installment as a monitoring record with `parcel_number`, `tax_year`, `installment_sequence`, `amount_due_cents`, `due_date`, `monthly_penalty_rate_bps` (basis points per month — 150 means 1.5%), a `penalty_method` of `SIMPLE` or `COMPOUND`, and optionally `grace_period_days`, defaulting to 0. The combination of parcel, tax year, and installment sequence must be unique among records of the same loan that are not in a terminal state; duplicates are rejected with `ERR_DUPLICATE_TAX_RECORD` (HTTP 409). `amount_due_cents` must be a positive integer, else `ERR_INVALID_AMOUNT` (HTTP 422); `monthly_penalty_rate_bps` and `grace_period_days` must be non-negative integers, else `ERR_INVALID_REQUEST`. A new record starts `MONITORING`, with `delinquent_since` null, `accrued_penalty_cents` 0, and `paid_via_disbursement_id` null.

From there the clock sweep drives the lifecycle. A record in `MONITORING` becomes `DUE_SOON` when the current date falls within the window from 30 days before `due_date` through `due_date` plus `grace_period_days`, both ends inclusive. From either `MONITORING` or `DUE_SOON`, once the current date passes `due_date` plus `grace_period_days`, the record becomes `DELINQUENT` and `delinquent_since` is fixed at `due_date` plus `grace_period_days` plus one day. On the first sweep pass after `delinquent_since` where the recomputed penalty comes out greater than zero, the record advances `DELINQUENT` → `PENALTY_ACCRUING`. And when the current date passes `delinquent_since` plus 730 days — two full years — a `PENALTY_ACCRUING` record escalates to `REDEMPTION_RISK`. The sweep recomputes `accrued_penalty_cents` on every pass while the record is `DELINQUENT`, `PENALTY_ACCRUING`, or `REDEMPTION_RISK`.

The penalty clock counts days on the 30/360 convention: from `delinquent_since` to the current date, the day count is 360 times the difference in years, plus 30 times the difference in months, plus the difference of the adjusted day-of-month values, where the start day is capped at 30 and an end day of the 31st is treated as 30 only when the start day is the 30th or 31st. Whole months elapsed are that day count divided by 30, rounded down. Under `SIMPLE`, the accrued penalty is `amount_due_cents` multiplied by the monthly rate (basis points over 10,000) multiplied by the whole months elapsed, rounded half-up once. Under `COMPOUND`, the balance starts at `amount_due_cents` and is iterated once per whole month elapsed, each iteration adding the balance times the monthly rate rounded half-up to whole cents before the next iteration begins — per-month rounding inside the loop is pinned, and the final penalty is the resulting balance minus `amount_due_cents`. Compounding is strictly more expensive than the simple variant once at least two whole months have elapsed.

Marking an installment paid is an `EscrowAnalyst` action that names a `disbursement_id`. The referenced disbursement must exist, be `RELEASED` or `CLEARED`, belong to an escrow account of the same loan, and cover the bill — its `amount_cents` must be at least `amount_due_cents` — with a disbursement that is not `RELEASED` or `CLEARED`, belongs to another loan's account, or falls short of the bill each rejected as `ERR_INVALID_AMOUNT` (HTTP 422). Timing decides the landing state: from `MONITORING` or `DUE_SOON`, payment on or before `due_date` plus `grace_period_days` lands in `PAID_CURRENT` with the penalty frozen at its current value of zero — but if the current date has already passed `due_date` plus `grace_period_days` while the record still sits in `MONITORING` or `DUE_SOON` (the sweep not having advanced it), the mark-paid is rejected with `ERR_INVALID_STATE_TRANSITION`; from `DELINQUENT`, `PENALTY_ACCRUING`, or `REDEMPTION_RISK`, payment lands in `PAID_DELINQUENT` with `accrued_penalty_cents` recomputed one final time as of today and then frozen permanently. Either way `paid_via_disbursement_id` is set, both paid states are terminal, and the record's `version` increments.

### 3.7. The Annual Escrow Analysis Cycle

Once a year per account — first due at `next_analysis_due_date`, set at activation to the closing date plus 12 months — an `EscrowAnalyst` opens an analysis cycle with an integer `analysis_year` label, a `projection_start_date`, and a `method` of `PROSPECTIVE` or `LEDGER_ACTUAL` — opening a cycle is not gated on `account_status` or `hold_status`, which bite only at compute and finalize. This create is the first OCC-guarded write of §2.8 and must carry `expected_escrow_account_version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The `projection_start_date` must be the first day of a month, else `ERR_PROJECTION_START_INVALID` (HTTP 422). The new cycle is born `DRAFT` with its computed fields null except `shortage_cents`, `deficiency_cents`, `surplus_cents`, `spread_monthly_cents`, and `spread_first_month_cents`, which start at 0; its projection window is the closed interval from `projection_start_date` through `window_end_date`, which is exactly 364 days later, both ends inclusive. That window may not overlap the window of any other non-terminal cycle of the account — a still-`DRAFT` predecessor is instead superseded by the creation — and an overlap is rejected with `ERR_ANALYSIS_WINDOW_OVERLAP`. Creating a cycle therefore has two side effects beyond the new row: any existing `DRAFT` cycle of the same account moves `DRAFT` → `SUPERSEDED`, and the account's `version` increments.

Computing the cycle — allowed from `DRAFT` and again from `REOPENED` — requires the account hold to be `NONE` (`ERR_ACCOUNT_ON_HOLD`, checked first here, ahead of the account-status gate, notwithstanding the generic priority of §2.9) and the account `ACTIVE` (`ERR_INVALID_STATE_TRANSITION`); a first compute additionally requires at least one `ACTIVE` line item. Compute runs the trial-balance projection and stamps `computed_at`.

The projection marches twelve months forward from `projection_start_date`'s month. Each `ACTIVE` line item contributes its installment amount — `expected_annual_amount_cents` divided by `installments_per_year`, rounded half-up — in the month of its `first_due_date` and every twelve-divided-by-`installments_per_year` months thereafter, counting an installment in whichever window month its due date falls. The sum of all installments landing inside the window is `projected_annual_disbursements_cents`, and `cushion_target_cents` is that total divided by 6, rounded half-up.

The opening balance depends on the method variant. Under `PROSPECTIVE`, `start_balance_cents` is the account's current posted `balance_cents` at compute time — every posted ledger entry counts, regardless of its `effective_date`, including forward-effective ones. Under `LEDGER_ACTUAL`, `start_balance_cents` is the chronological replay of only those entries whose `effective_date` is strictly before `projection_start_date`, replayed in `effective_date` ascending, `created_at` ascending order; forward-effective entries are excluded.

One evaluation order is pinned and non-negotiable: all twelve months are projected using the account's current `monthly_escrow_cents` — the old payment — for every month, including months after any notice effective date; only after the projection completes are the shortage, deficiency, and surplus derived; and only after those are derived is the new monthly payment computed. Using the new payment inside the projection is forbidden and produces different, wrong numbers. `lowest_projected_balance_cents` is the minimum of the twelve month-end running balances.

From the projection, the determinations fall out. `deficiency_cents` is the amount by which the lowest projected balance dips below zero — zero when it never does. `shortage_cents` applies when the lowest projected balance is below the cushion target: it is the target minus the lowest balance floored at zero, so a negative trough contributes only through the target, and it is zero when the trough meets or exceeds the target. `surplus_cents` is the amount by which `start_balance_cents` exceeds the cushion target, zero otherwise.

The new payment is assembled in pinned order. `base_monthly_escrow_cents` repeats the per-line-then-sum rule of §3.3: each `ACTIVE` line's annual amount divided by 12, rounded half-up per line, then summed. The total repayment spread is `shortage_cents` plus `deficiency_cents`; `spread_monthly_cents` is that total divided by 12 rounded down, and `spread_first_month_cents` is the total minus eleven times the monthly spread, so the remainder loads onto the first month. `new_monthly_escrow_cents` is the base plus the monthly spread under the spread-over-twelve assumption; the lump-sum alternative uses the base alone and is decided later, at notice acknowledgment.

Issuing the annual statement moves `COMPUTED` → `STATEMENT_ISSUED`, stamps `statement_issued_at`, sets `statement_due_date` to the date of `computed_at` plus 30 calendar days, and derives `statement_timeliness` as `ON_TIME` when the issue date is on or before the due date, else `LATE`.

Finalizing moves `STATEMENT_ISSUED` → `EFFECTIVE` and is blocked while the account is on hold (`ERR_ACCOUNT_ON_HOLD`). Finalize is a fan-out: it creates the cycle's `PaymentChangeNotice` in `DRAFT` carrying `old_monthly_escrow_cents` (the account's monthly escrow amount at finalize time) and `new_monthly_escrow_cents`; it derives the notice's `effective_date` as the first day of the second month after the finalize month — finalizing in September 2026 yields 2026-11-01 — and its `send_by_date` as 30 days before the effective date. It handles the surplus: a `surplus_cents` of 5000 cents ($50.00) or more posts a `SURPLUS_REFUND` ledger entry of negative `surplus_cents` refunding the borrower, while a surplus strictly between zero and 5000 cents posts nothing and stays credited in the account — the boundary is exact, 5000 refunds and 4999 does not. It moves any prior `EFFECTIVE` cycle of the account to `SUPERSEDED`. And it updates the account: `last_analysis_year` becomes this cycle's `analysis_year`, and `next_analysis_due_date` advances by another 12 months. Both the cycle's and the account's `version` increment.

An `EFFECTIVE` cycle can be reopened — by a `ComplianceOfficer` directly, or by the error-correction cascade of §3.9 — moving `EFFECTIVE` → `REOPENED` and voiding every one of its notices still in `DRAFT`, `SENT`, or `ACKNOWLEDGED`. A reopened cycle recomputes back to `COMPUTED` with all computed fields repopulated and `computed_at` refreshed. A `ComplianceOfficer` may also void a cycle from `DRAFT`, `COMPUTED`, or `REOPENED`; `SUPERSEDED` and `VOIDED` are terminal.

### 3.8. Payment Change Notices and the Borrower's Choice

The notice created at finalize is bound to its cycle through `analysis_id` and derives its `notice_type` from the analysis outcome: `DEFICIENCY` whenever `deficiency_cents` is positive; otherwise `SHORTAGE` when `shortage_cents` is positive; `SURPLUS` when `surplus_cents` is positive with shortage and deficiency both zero; and `PAYMENT_CHANGE` when shortage and deficiency are zero and there is no surplus. Its `shortage_option` starts null, `sent_at` and `timeliness` start null, and it lives in `DRAFT` until sent.

Sending — an `EscrowAnalyst` action, `DRAFT` → `SENT` — stamps `sent_at` and derives `timeliness` as `ON_TIME` when the sent date is on or before `send_by_date`, else `LATE`.

Acknowledgment belongs to the `Borrower`, and the ownership check requires `X-User-ID` to equal the `id` of the loan that owns the analysis's escrow account, else `ERR_BORROWER_NOT_OWNER`. The `shortage_option` field is required when the analysis's shortage plus deficiency is positive — omitting it is `ERR_SHORTAGE_OPTION_REQUIRED` (HTTP 422) — and forbidden when that sum is zero, where supplying it is `ERR_SHORTAGE_OPTION_NOT_APPLICABLE` (HTTP 422). One RESPA guardrail constrains the choice: `LUMP_SUM` is rejected with `ERR_DEFICIENCY_SPREAD_MANDATORY` (HTTP 422) when the analysis's `deficiency_cents` is at least one full month of escrow — measured against `old_monthly_escrow_cents`, the payment pinned at finalize time — because a deficiency that large must be spread over at least 12 months. Choosing `LUMP_SUM` recomputes the notice's `new_monthly_escrow_cents` down to `base_monthly_escrow_cents` alone, dropping the spread; `SPREAD_12` leaves the computed base-plus-spread in place. Acknowledgment moves `SENT` → `ACKNOWLEDGED`.

Applying the notice is an `EscrowAnalyst` action available from either `SENT` or `ACKNOWLEDGED`. The current date must be on or after the notice's `effective_date`, else `ERR_EFFECTIVE_DATE_NOT_REACHED`, and the underlying analysis must not be `REOPENED` or `VOIDED`, else `ERR_INVALID_STATE_TRANSITION`. Applying from `SENT` when shortage plus deficiency is positive and the borrower never chose an option treats the choice as a `SPREAD_12` default, and the notice's `shortage_option` remains null in that case. Applying from `ACKNOWLEDGED` under `LUMP_SUM` demands proof of the borrower's lump payment: the sum of `DEPOSIT` ledger entries with `effective_date` on or after the notice's sent date and on or before today must be at least the shortage plus deficiency, else `ERR_SHORTAGE_LUMP_SUM_MISSING` (HTTP 422). A successful apply moves the notice to the terminal `APPLIED` and replaces the account's `monthly_escrow_cents` with the notice's `new_monthly_escrow_cents`, incrementing both versions.

A `ComplianceOfficer` may void a notice from `DRAFT` or `SENT`; the analysis-reopen cascade voids notices in `DRAFT`, `SENT`, or `ACKNOWLEDGED`. `APPLIED` and `VOIDED` are terminal.

### 3.9. Notices of Error and the Correction Cascade

RESPA Regulation X gives the borrower a formal error-assertion channel. A `Borrower` files a notice of error on their own loan with an `error_type` — `DISBURSEMENT_FAILURE`, `DISBURSEMENT_AMOUNT_ERROR`, `UNTIMELY_DISBURSEMENT`, `FORCE_PLACEMENT_ERROR`, `ANALYSIS_ERROR`, `PAYMENT_APPLICATION_ERROR`, or `OTHER_COVERED` — a free-text `description`, and an optional `asserted_amount_cents`. A second non-terminal case with the same loan and `error_type` is rejected with `ERR_DUPLICATE_ACTIVE_CASE`. The case is born `RECEIVED` with `received_at` stamped.

Two deadlines are computed at receipt using business-day arithmetic, where business days are Monday through Friday excluding federal holidays: count forward one calendar day at a time, counting only business days, with the receipt day itself as day 0 and never counted. `ack_deadline` is five business days after receipt — so a case received Friday 2026-08-07 has an acknowledgment deadline of Friday 2026-08-14, and one received Friday 2026-09-04 lands on Monday 2026-09-14 because Labor Day is skipped. `resolution_deadline` is thirty business days after receipt, or forty-five once extended. The federal holiday calendar is fixed: 2026-09-07, 2026-10-12, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01, 2027-01-18, 2027-02-15, 2027-05-31, 2027-07-05, 2027-09-06, 2027-10-11, 2027-11-11, 2027-11-25, 2027-12-24, and 2027-12-31.

A `ComplianceOfficer` acknowledges the case (`RECEIVED` → `ACKNOWLEDGED`), stamping `acknowledged_at` and deriving `ack_timeliness` as `ON_TIME` when the acknowledgment date is on or before `ack_deadline`, else `LATE` — a late acknowledgment is flagged, never blocked. Assignment (`ACKNOWLEDGED` → `INVESTIGATING`) records `assigned_to_user_id`, the staff investigator who becomes the segregation anchor for resolution. Extension (`INVESTIGATING` → `EXTENDED`) must be requested on or before the original thirty-business-day deadline — afterwards it is `ERR_EXTENSION_WINDOW_PASSED` — and recomputes `resolution_deadline` to forty-five business days after receipt.

Resolution is the third segregation-of-duties checkpoint: the resolving `ComplianceOfficer`'s `X-User-ID` must differ from `assigned_to_user_id`, else `ERR_SOD_VIOLATION`. From `INVESTIGATING` or `EXTENDED`, resolution takes an `outcome` — which must be `CORRECTED` or `NO_ERROR`, else `ERR_INVALID_REQUEST` (HTTP 400) — an optional `correction_amount_cents`, and an optional `resolution_note` defaulting to an empty string. An `outcome` of `NO_ERROR` lands in `RESOLVED_NO_ERROR` with `resolved_at`, `resolved_by_user_id`, and `resolution_timeliness` — `ON_TIME` when the resolution date is on or before `resolution_deadline`, else `LATE` — and no ledger activity; a `correction_amount_cents` supplied alongside `NO_ERROR` is ignored and the field stays null. An `outcome` of `CORRECTED` requires `correction_amount_cents` to be present and positive (`ERR_INVALID_AMOUNT`) and requires the loan's escrow account to exist and not be `CLOSED` (`ERR_INVALID_STATE_TRANSITION`); it then fires the four-link correction cascade: an `ERROR_CORRECTION` ledger entry of positive `correction_amount_cents` posts effective today; the account's `balance_cents` is recomputed; any `EFFECTIVE` analysis cycle of the account moves to `REOPENED`; and each of that analysis's notices in `DRAFT`, `SENT`, or `ACKNOWLEDGED` moves to `VOIDED`. The case's and the account's `version` both increment. Finally, a case that asserts something outside the covered error types — or is duplicative — may be dismissed from `RECEIVED` or `ACKNOWLEDGED` with a `dismissal_reason`, landing in `DISMISSED_NOT_COVERED`; the `outcome` value `DISMISSED` is recorded when a case ends this way, and the `dismissal_reason` is stored into the case's `resolution_note` field. `RESOLVED_CORRECTED`, `RESOLVED_NO_ERROR`, and `DISMISSED_NOT_COVERED` are all terminal, and a loan with any case still in `RECEIVED`, `ACKNOWLEDGED`, `INVESTIGATING`, or `EXTENDED` cannot be transferred out.

## 4. Endpoint Definitions

All endpoints are mounted under two roots: the servicing API under `/servicing`, and the test-driving clock under `/_clock`. Creating a new resource returns HTTP 201; every other successful operation — reads, state transitions, patches — returns HTTP 200. List endpoints accept the pagination parameters of §2.3 plus the filters noted in §3 narratives: loans, line items, disbursements, tax records, analyses, notices, advances, and error cases filter by `status`; accounts filter by `loan_id` and `account_status`; the ledger filters by `entry_type`; payees filter by `verification_status` and `payee_type`; policies filter by `policy_type` and `status`. The table below is a navigation summary only — request fields, preconditions, and side effects are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /_clock/set_current_utc | Set the logical clock and run the deterministic sweep | ComplianceOfficer |
| GET | /_clock/current_utc | Read the logical clock | ComplianceOfficer, EscrowAnalyst, DisbursementProcessor, PayeeVerifier, InsuranceSpecialist, Borrower |
| POST | /servicing/loans | Board a loan | ComplianceOfficer |
| GET | /servicing/loans | List loans | All roles |
| GET | /servicing/loans/{id} | Get one loan | All roles |
| POST | /servicing/loans/{id}/activate | Activate an ONBOARDING loan | ComplianceOfficer |
| POST | /servicing/loans/{id}/payoff | Pay off an ACTIVE loan; closes escrow with surplus-refund cascade | ComplianceOfficer |
| POST | /servicing/loans/{id}/transfer-out | Transfer servicing out; blocked while any error case is open | ComplianceOfficer |
| POST | /servicing/loans/{id}/escrow-account | Create the loan's single escrow account | EscrowAnalyst |
| GET | /servicing/escrow-accounts | List escrow accounts; reverse lookup by loan | All roles |
| GET | /servicing/escrow-accounts/{id} | Get one escrow account | All roles |
| POST | /servicing/escrow-accounts/{id}/activate | Activate a SETUP account (requires at least one ACTIVE line item) | EscrowAnalyst |
| POST | /servicing/escrow-accounts/{id}/suspend | Suspend an ACTIVE account | ComplianceOfficer |
| POST | /servicing/escrow-accounts/{id}/reinstate | Reinstate a SUSPENDED account | ComplianceOfficer |
| POST | /servicing/escrow-accounts/{id}/hold | Place a compliance hold | ComplianceOfficer |
| POST | /servicing/escrow-accounts/{id}/release-hold | Release a compliance hold | ComplianceOfficer |
| POST | /servicing/escrow-accounts/{id}/deposits | Post a borrower escrow deposit; triggers the advance recovery waterfall | EscrowAnalyst, Borrower |
| GET | /servicing/escrow-accounts/{id}/ledger | List ledger entries chronologically | All roles |
| POST | /servicing/escrow-accounts/{id}/line-items | Add a projected expense line item | EscrowAnalyst |
| GET | /servicing/escrow-accounts/{id}/line-items | List line items of an account | All roles |
| GET | /servicing/escrow-line-items/{id} | Get one line item | All roles |
| PATCH | /servicing/escrow-line-items/{id} | Update amount or schedule of an ACTIVE line item | EscrowAnalyst |
| POST | /servicing/escrow-line-items/{id}/remove | Remove (deactivate) a line item | EscrowAnalyst |
| POST | /servicing/payees | Create a payee (PENDING_VERIFICATION; creator recorded for SoD) | DisbursementProcessor |
| GET | /servicing/payees | List payees | All roles |
| GET | /servicing/payees/{id} | Get one payee | All roles |
| POST | /servicing/payees/{id}/verify | Verify or re-verify a payee; verifier must differ from creator | PayeeVerifier |
| POST | /servicing/payees/{id}/reject | Reject a payee (terminal) | PayeeVerifier |
| POST | /servicing/payees/{id}/suspend | Suspend a VERIFIED payee; blocks its scheduled disbursements | PayeeVerifier, ComplianceOfficer |
| GET | /servicing/payees/{id}/disbursements | List disbursements paying this payee | All roles |
| GET | /servicing/payees/{id}/line-items | List line items paying this payee | All roles |
| POST | /servicing/escrow-accounts/{id}/disbursements | Schedule a disbursement | DisbursementProcessor |
| GET | /servicing/escrow-accounts/{id}/disbursements | List disbursements of an account | All roles |
| GET | /servicing/disbursements/{id} | Get one disbursement | All roles |
| PATCH | /servicing/disbursements/{id} | Reschedule or re-amount a SCHEDULED disbursement (OCC-guarded) | DisbursementProcessor |
| POST | /servicing/disbursements/{id}/release | Release funds; posts the ledger debit and may auto-create an advance | DisbursementProcessor |
| POST | /servicing/disbursements/{id}/cancel | Cancel a SCHEDULED or BLOCKED disbursement | DisbursementProcessor |
| POST | /servicing/disbursements/{id}/mark-cleared | Mark a RELEASED disbursement cleared | DisbursementProcessor |
| POST | /servicing/disbursements/{id}/mark-returned | Mark a RELEASED disbursement returned; compensating credit and advance reduction | DisbursementProcessor |
| GET | /servicing/disbursements/{id}/tax-monitoring-records | List tax records paid via this disbursement | All roles |
| GET | /servicing/disbursements/{id}/advances | List advances created for this disbursement | All roles |
| GET | /servicing/escrow-line-items/{id}/disbursements | List disbursements charged to this line item | All roles |
| POST | /servicing/loans/{id}/insurance-policies | Add a borrower insurance policy; half-open overlap rule per type | InsuranceSpecialist, Borrower |
| GET | /servicing/loans/{id}/insurance-policies | List insurance policies of a loan | All roles |
| GET | /servicing/insurance-policies/{id} | Get one insurance policy | All roles |
| POST | /servicing/insurance-policies/{id}/report-lapse | Report a mid-term carrier cancellation | InsuranceSpecialist |
| POST | /servicing/insurance-policies/{id}/send-first-notice | Send the first force-placement notice | InsuranceSpecialist |
| POST | /servicing/insurance-policies/{id}/send-reminder-notice | Send the reminder notice (at least 30 days after the first) | InsuranceSpecialist |
| POST | /servicing/insurance-policies/{id}/charge-force-placement | Charge the force-placement premium after notice windows elapse | InsuranceSpecialist |
| POST | /servicing/insurance-policies/{id}/reinstate | Accept borrower evidence; returns LAPSED/NOTICE_1_SENT/NOTICE_2_SENT to ACTIVE | InsuranceSpecialist, Borrower |
| POST | /servicing/insurance-policies/{id}/refund-force-placement | Refund the force-placement premium, prorated per day-count convention | InsuranceSpecialist |
| POST | /servicing/insurance-policies/{id}/cancel | Cancel an ACTIVE or LAPSED policy | InsuranceSpecialist |
| POST | /servicing/loans/{id}/tax-monitoring-records | Register a tax installment for delinquency monitoring | EscrowAnalyst |
| GET | /servicing/loans/{id}/tax-monitoring-records | List tax monitoring records of a loan | All roles |
| GET | /servicing/tax-monitoring-records/{id} | Get one tax monitoring record | All roles |
| POST | /servicing/tax-monitoring-records/{id}/mark-paid | Mark an installment paid via a released or cleared disbursement | EscrowAnalyst |
| POST | /servicing/escrow-accounts/{id}/analyses | Open an annual analysis cycle (OCC-guarded; supersedes an existing DRAFT) | EscrowAnalyst |
| GET | /servicing/escrow-accounts/{id}/analyses | List analysis cycles of an account | All roles |
| GET | /servicing/analyses/{id} | Get one analysis cycle | All roles |
| POST | /servicing/analyses/{id}/compute | Run the trial-balance projection and shortage/deficiency/surplus determination | EscrowAnalyst |
| POST | /servicing/analyses/{id}/issue-statement | Issue the annual escrow statement | EscrowAnalyst |
| POST | /servicing/analyses/{id}/finalize | Make the analysis EFFECTIVE; creates the payment-change notice and handles surplus | EscrowAnalyst |
| POST | /servicing/analyses/{id}/reopen | Reopen an EFFECTIVE analysis; voids its pending notices | ComplianceOfficer |
| POST | /servicing/analyses/{id}/void | Void a DRAFT, COMPUTED, or REOPENED analysis (terminal) | ComplianceOfficer |
| GET | /servicing/analyses/{id}/notices | List payment-change notices of an analysis | All roles |
| GET | /servicing/notices/{id} | Get one payment-change notice | All roles |
| POST | /servicing/notices/{id}/send | Send the notice; timeliness measured against the send-by date | EscrowAnalyst |
| POST | /servicing/notices/{id}/acknowledge | Borrower acknowledges and picks a shortage repayment option | Borrower |
| POST | /servicing/notices/{id}/apply | Apply the new payment on or after its effective date | EscrowAnalyst |
| POST | /servicing/notices/{id}/void | Void a DRAFT or SENT notice | ComplianceOfficer |
| POST | /servicing/escrow-accounts/{id}/advances | Create a manual corporate advance | ComplianceOfficer |
| GET | /servicing/escrow-accounts/{id}/advances | List advances of an account | All roles |
| GET | /servicing/advances/{id} | Get one advance | All roles |
| POST | /servicing/advances/{id}/recover | Recover an advance from the escrow balance | EscrowAnalyst |
| POST | /servicing/advances/{id}/write-off | Write off the remaining advance (terminal) | ComplianceOfficer |
| POST | /servicing/loans/{id}/error-cases | Borrower files a notice of error | Borrower |
| GET | /servicing/loans/{id}/error-cases | List error cases of a loan | All roles |
| GET | /servicing/error-cases/{id} | Get one error case | All roles |
| POST | /servicing/error-cases/{id}/acknowledge | Acknowledge a case; late acknowledgment is flagged, not blocked | ComplianceOfficer |
| POST | /servicing/error-cases/{id}/assign | Assign an investigator | ComplianceOfficer |
| POST | /servicing/error-cases/{id}/extend | Extend the resolution window to 45 business days | ComplianceOfficer |
| POST | /servicing/error-cases/{id}/resolve | Resolve a case; CORRECTED posts the correction credit and cascades | ComplianceOfficer |
| POST | /servicing/error-cases/{id}/dismiss | Dismiss a non-covered or duplicative assertion | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the identifier-to-status index.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_FORBIDDEN_FOR_ROLE | 403 |
| ERR_BORROWER_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_REFERENCE_NOT_FOUND | 422 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_AMOUNT | 422 |
| ERR_STALE_VERSION | 412 |
| ERR_ALREADY_TERMINAL | 409 |
| ERR_INVALID_STATE_TRANSITION | 409 |
| ERR_ACCOUNT_ON_HOLD | 409 |
| ERR_LOAN_NOT_ACTIVE | 409 |
| ERR_SOD_VIOLATION | 409 |
| ERR_NOTICE_WINDOW_NOT_MET | 409 |
| ERR_REMINDER_TOO_EARLY | 409 |
| ERR_ACTIVE_COVERAGE_EXISTS | 409 |
| ERR_RELEASE_TOO_EARLY | 409 |
| ERR_EFFECTIVE_DATE_NOT_REACHED | 409 |
| ERR_EXTENSION_WINDOW_PASSED | 409 |
| ERR_PROJECTION_START_INVALID | 422 |
| ERR_DUPLICATE_LOAN_NUMBER | 409 |
| ERR_ESCROW_ACCOUNT_EXISTS | 409 |
| ERR_DUPLICATE_LINE_ITEM_TYPE | 409 |
| ERR_DUPLICATE_ACTIVE_CASE | 409 |
| ERR_DUPLICATE_TAX_RECORD | 409 |
| ERR_COVERAGE_OVERLAP | 409 |
| ERR_ANALYSIS_WINDOW_OVERLAP | 409 |
| ERR_PAYEE_NOT_VERIFIED | 409 |
| ERR_UNRESOLVED_ERROR_CASE | 409 |
| ERR_ADVANCE_OUTSTANDING | 409 |
| ERR_ESCROW_NOT_ACTIVE | 409 |
| ERR_ADVANCE_CAP_EXCEEDED | 422 |
| ERR_RECOVERY_EXCEEDS_OUTSTANDING | 422 |
| ERR_SHORTAGE_OPTION_REQUIRED | 422 |
| ERR_SHORTAGE_OPTION_NOT_APPLICABLE | 422 |
| ERR_SHORTAGE_LUMP_SUM_MISSING | 422 |
| ERR_DEFICIENCY_SPREAD_MANDATORY | 422 |

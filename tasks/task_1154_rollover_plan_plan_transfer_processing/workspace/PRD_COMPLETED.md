# Rollover Plan Transfer API — Product Requirements Document

## 1. Introduction

Retirement plan recordkeepers sit at the intersection of participant trust and federal tax law. Every time a participant moves money out of one plan and into another — whether by a trustee-to-trustee direct rollover, a 60-day indirect rollover, a plan-to-plan transfer, or an in-plan Roth conversion — the recordkeeper must answer a series of questions with legal precision: Is this participant eligible to take a distribution right now? What documentation proves it? Does the receiving plan accept this kind of money? How much federal tax must be withheld, and on which portion? Where does the tax basis travel? What happens if the participant never completes the rollover? And which tax forms must be filed, with what values, when the dust settles?

This document specifies the Rollover Plan Transfer API, the system of record for processing those movements end to end. The API serves five operational constituencies at once: participants initiating elections, plan sponsor administrators configuring plans and blackout windows, recordkeeper processors adjudicating eligibility and moving money under segregation of duties, tax reporting officers finalizing 1099-R and 5498 forms, and an operations agent driving the daily sweep that catches lapsed 60-day windows. The system is built around a single aggregate — the rollover case — whose twelve-state lifecycle branches across five case types and interlocks with a document-review loop, a plan-verification workflow, a disbursement ledger, a redeposit tracker, a loan-offset mechanism, a scheduled follow-up-notice subsystem, and a self-referential tax-form correction chain.

Two structural commitments shape everything that follows. First, correctness of money and tax data is non-negotiable: every calculation is pinned to integer-cent arithmetic with mandated rounding order, every disbursement carries an exact compensating-reversal invariant, and every tax form that has already been issued can only be changed through a superseding correction revision — never silently edited. Second, no single operator may both approve a case's eligibility and move its money: the segregation-of-duties anchor recorded at decision time is enforced at every money-movement step thereafter. All processing is evaluated against a logical clock (not wall-clock time), which operations can set explicitly so that deadline behavior, age computations, and scheduled notices are fully deterministic.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes five distinct roles: `Participant`, `PlanSponsorAdmin`, `RolloverProcessor`, `TaxReportingOfficer`, and `OperationsAgent`. A request missing either header, or presenting a role string outside this declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the full role-to-endpoint mapping is given in §4.

The identity carried by `X-User-ID` differs by role, and the distinction is load-bearing for ownership scoping:

- When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Participant` entity. Ownership checks on any resource that references a `Participant` compare the resource's foreign-key field to `X-User-ID`. A participant may only read or act on rollover cases, accounts, required documents, disbursements, redeposits, follow-up notices, loans, and tax forms whose owning account belongs to that participant; any attempt to reach another participant's resource is answered with `ERR_CASE_NOT_FOUND` or `ERR_ACCOUNT_NOT_FOUND` (HTTP 404) rather than an authorization error, so that the API never leaks whether the target exists at all. Reading another participant's own record (for example, `GET /v1/participants/{participantId}` naming someone else) is likewise masked, answered with `ERR_PARTICIPANT_NOT_FOUND`.
- When `X-User-Role` is `PlanSponsorAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- When `X-User-Role` is `RolloverProcessor`, `X-User-ID` is likewise opaque, but the server records it wherever a processor takes a decision or action: as `eligibility_decided_by` on a `RolloverCase` at eligibility decision time, as `reviewed_by` on a `RequiredDocument` at review time, and as the actor compared against `eligibility_decided_by` at every money-movement step under the segregation-of-duties rule (§2.6).
- When `X-User-Role` is `TaxReportingOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- When `X-User-Role` is `OperationsAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit on the daily sweep and the logical-clock capability but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from wall-clock time — not from the logical clock of §2.4, which governs resource-level timestamps instead.
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
- Requests to undefined routes, or to defined routes with an unsupported method, are answered in the same envelope with `error_id` `ERR_VALIDATION` at the corresponding 404 or 405 status.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A `limit` or `offset` that does not parse as an integer, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order (oldest first), with ties on identical timestamps broken by insertion order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

Every time-dependent rule in this system — distribution eligibility by age, the 60-day rollover window, loan-offset deadlines, freeze-window membership, follow-up-notice scheduling, and tax-year assignment — is evaluated against a **logical clock** maintained by the server, never against wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`; it never silently falls back to wall-clock time. An `OperationsAgent` reassigns the clock through a test-driving capability that accepts a `to_iso8601` timestamp and moves the clock to that instant; the response echoes the new reading as `current_utc`. Age computations, deadline comparisons, and scheduled-action triggers all read this clock, which makes every time-gated behavior in §3 fully deterministic and reproducible.

### 2.5. Common Resource Properties

Every primary resource in the system — Plan, PlanFreezeWindow, Participant, Account, MoneySourceBalance, Loan, RolloverCase, RequiredDocument, SourcePlanVerification, Disbursement, Redeposit, FollowUpNotice, and TaxForm — carries a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-05-01T12:00:00.000Z`), set when the resource is first created and never changed thereafter.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed upon any mutation of the resource's properties. Both `created_at` and `updated_at` are stamped from the logical clock of §2.4, never from wall-clock time.
- `version` (integer): a system-managed integer starting at 1 on creation and incrementing by exactly 1 on every mutation. It is the optimistic-concurrency token described in §2.8.

Any mutation that recomputes a derived field on a resource — for example, recomputing `total_balance_cents` on an Account after a balance row moves — is itself a mutation and therefore refreshes `updated_at` and increments `version`.

### 2.6. Segregation of Duties

No operator may both adjudicate a case's eligibility and move that case's money. When a `RolloverProcessor` approves eligibility, the server records that operator's `X-User-ID` on the case as `eligibility_decided_by`. Thereafter, the four money-movement capabilities — assembling an outbound disbursement for an eligible case, executing a plan-to-plan transfer, executing an in-plan Roth conversion, and posting inbound rollover credit — each require that the acting operator's `X-User-ID` differ from the case's stored `eligibility_decided_by`. A violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403). This rule exists so that a single compromised or mistaken processor cannot both declare a participant eligible and push money out the door; two distinct operators must touch every completed movement.

### 2.7. Money, Precision, and Rounding

All monetary quantities in the system are integer cents — `balance_cents`, `basis_cents`, `gross_cents`, `net_cents`, and their siblings are whole numbers of cents, and no fractional cent ever appears in a stored value or API response. Where a computation produces a fractional cent, the rounding rule is part of the calculation's definition and is never left to the implementer's discretion. Three rounding disciplines recur throughout §3 and are stated here once:

- **Floor per row, then sum.** Vesting computations truncate each money-source row's vested cents down to a whole cent *before* summing; the system never sums exact fractional values and rounds the total.
- **Largest-remainder distribution.** When a gross amount is allocated across sources pro-rata, each source receives the floor of its exact rational share, and the leftover cents (the gross minus the sum of floors) are distributed one cent each to the sources with the largest fractional parts, with ties broken by a pinned source-type order.
- **Round half up.** Tax-basis shares and withholding amounts are rounded half-up to the nearest cent (a half cent rounds away from zero).

Ages are computed in whole calendar months and expressed in years by truncation; see §3.2. Dates are ISO calendar dates (`YYYY-MM-DD`) and deadline arithmetic counts whole calendar days.

### 2.8. Optimistic Concurrency Control

Two write operations require the caller to prove it has observed the current state of the resource it is about to mutate, by carrying an expected-version field that must equal the resource's current `version`:

- **Amending a DRAFT rollover case.** A case-amendment request must carry `expected_rollover_case_version` matching the case's current `version`. If another writer has amended the case since the client last read it — each successful amendment legitimately replaces the prior election set and advances the version by 1 — the stale amendment is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Filing a tax-form correction.** A correction request must carry `expected_tax_form_version` matching the form's current `version`. A correction supersedes the prior revision, so a writer holding a stale version must not silently supersede a revision it never saw; the mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412).

On both endpoints the expected-version field is mandatory and must be an integer — its absence or a non-integer value is a malformed-payload `ERR_VALIDATION` — and the resource's state guard (`DRAFT`-only for case amendments, `ISSUED`-only for corrections) is evaluated before the version comparison, so a state violation surfaces as `ERR_CASE_INVALID_STATE` or `ERR_TAX_FORM_INVALID_STATE` rather than `ERR_STALE_VERSION`.

Endpoints not listed here do not accept a version field and perform no such check.

### 2.9. Validation Order and Nested-Resource Resolution

When a request fails several rules at once, the API answers with exactly one error, and which error it is must be deterministic. The system therefore evaluates validations in a fixed priority order, from broadest to most specific:

1. **Authentication** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`).
2. **Authorization and ownership scoping** — role permission for the endpoint, and Participant ownership of the target (`ERR_UNAUTHORIZED_ROLE`, or the ownership-masking `ERR_CASE_NOT_FOUND` / `ERR_ACCOUNT_NOT_FOUND`).
3. **Existence** — every path identifier and body reference must resolve, validated left-to-right as it appears in the URL hierarchy: plan first, then participant, account, case, and finally the leaf resource (document, verification, disbursement, redeposit, loan, or tax form). A request naming a non-existent parent is rejected with that parent's not-found error before the child is ever looked up: `ERR_PLAN_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_VERIFICATION_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`, `ERR_REDEPOSIT_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, or `ERR_TAX_FORM_NOT_FOUND`.
4. **State** — the target must be in a state that permits the operation (`ERR_CASE_INVALID_STATE`, `ERR_PLAN_FROZEN`, `ERR_PLAN_TERMINATED`, `ERR_PLAN_NOT_FROZEN`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_DOCUMENT_INVALID_STATE`, `ERR_DISBURSEMENT_INVALID_STATE`, `ERR_REDEPOSIT_INVALID_STATE`, `ERR_VERIFICATION_INVALID_STATE`, `ERR_TAX_FORM_INVALID_STATE`, `ERR_LOAN_INVALID_STATE`).
5. **Segregation of duties** — the money-movement actor must differ from `eligibility_decided_by` (`ERR_SOD_VIOLATION`), evaluated before any business-rule check.
6. **Cross-reference consistency** — linked resources must belong to the same participant and the referenced plans (`ERR_ACCOUNT_PARTICIPANT_MISMATCH`, `ERR_SAME_PLAN_TRANSFER`, `ERR_ACCOUNT_ALREADY_EXISTS`).
7. **Temporal gates** — deadlines and freeze windows (`ERR_DEPOSIT_PAST_DEADLINE`, `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`, `ERR_FREEZE_WINDOW_OVERLAP`, `ERR_WINDOW_RANGE_INVALID`).
8. **Capability and uniqueness constraints** — plan capability flags, verification gates, outstanding loans, open-case exclusivity, withholding acknowledgement, and document completeness (`ERR_PLAN_CAPABILITY_REJECTED`, `ERR_VERIFICATION_NOT_VERIFIED`, `ERR_LOANS_OUTSTANDING`, `ERR_OPEN_CASE_EXISTS`, `ERR_WITHHOLDING_ACK_REQUIRED`, `ERR_DOCUMENTS_OUTSTANDING`, `ERR_DISBURSEMENT_ALREADY_EXISTS`).
9. **Amount checks, last** — only after every other gate has passed are magnitudes validated (`ERR_AMOUNT_EXCEEDS_VESTED`, `ERR_DEPOSIT_EXCEEDS_REMAINING`, and `ERR_VALIDATION` for non-positive amounts or malformed fields).

Amount checks deliberately come last so that a request which is, say, both ineligible and over-vested reports the eligibility failure — the more actionable error — first.

### 2.10. Plan Freeze Windows

A plan sponsor may declare **processing blackout periods** for a plan. Each `PlanFreezeWindow` carries a `start_date`, an `end_date`, and a free-text `reason`, and the window is a *closed interval*: both the start date and the end date are inside the blackout. Window creation is itself validated: the `start_date` must be on or before the `end_date` (otherwise `ERR_WINDOW_RANGE_INVALID`), and the new window must not overlap any existing window of the same plan under closed-interval collision semantics — windows that merely touch at a boundary date (one ends on the day another begins) do *not* overlap and are allowed; a true collision is rejected with `ERR_FREEZE_WINDOW_OVERLAP`. While a disbursement's issue date (read from the logical clock) falls inside any freeze window of the source plan, issuance is blocked with `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`. Freeze windows constrain issuance only; they do not suspend cases — the full-plan freeze described in §3.1 does that.

## 3. Business Logic & Workflows

### 3.1. Plans: Configuration, Freezing, and Termination

A **Plan** is the top of the hierarchy, onboarded by a `PlanSponsorAdmin` with a `plan_name` and a `plan_type` of `PLAN_401K`, `PLAN_403B`, `PLAN_457B`, or `IRA`. A plan's behavior is shaped by seven capability flags, each defaulting to `true` when omitted at creation: `accepts_incoming_rollovers` (whether the plan credits inbound rollovers), `accepts_incoming_transfers` (whether it accepts plan-to-plan transfers in), `accepts_loan_transfers` (whether it accepts loan notes moved with a transfer), `accepts_after_tax_basis` (whether it accepts after-tax, non-Roth basis on inbound money), `allows_in_plan_roth_conversion` (whether participants may convert in-plan balances to Roth), `requires_spousal_consent` (whether married participants need spousal consent for money leaving the plan), and `spousal_consent_threshold_cents` (the balance above which consent is required, defaulting to 500000 cents — the statutory five-thousand-dollar line — and rejected with `ERR_VALIDATION` when negative). These flags are consulted at case submit time and again at execution time, as described in §3.3 and §3.8.

A plan is created in `ACTIVE` status and may move `ACTIVE → FROZEN`, `FROZEN → ACTIVE`, or `ACTIVE → TERMINATED`, all at the hands of a `PlanSponsorAdmin`. Freezing a plan that is already `FROZEN` is rejected with `ERR_PLAN_FROZEN`; freezing a `TERMINATED` plan is rejected with `ERR_PLAN_TERMINATED`. Unfreezing a plan that is not `FROZEN` is rejected with `ERR_PLAN_NOT_FROZEN`. Terminating a plan that is already `TERMINATED` is likewise rejected with `ERR_PLAN_TERMINATED`. Terminating a `FROZEN` plan is rejected with `ERR_PLAN_FROZEN`: only an `ACTIVE` plan may be terminated.

Freezing is a heavy operation with a three-link cascade. **Link 1:** every rollover case whose source or receiving account sits at this plan and whose status is non-terminal — that is, in `DRAFT`, `DOCS_PENDING`, `ELIGIBILITY_REVIEW`, `ELIGIBLE`, `DISBURSED`, `AWAITING_REDEPOSIT`, or `ACCEPTANCE_PENDING` — records its current status into `prior_status` and transitions to `SUSPENDED`. **Link 2:** every disbursement pointing at a case that just became `SUSPENDED` and still in `PENDING` transitions to `CANCELLED`. **Link 3:** each disbursement cancelled this way restores the debited source balances exactly — every money-source row of the case's source account is credited back precisely the amount that source contributed at issuance, a full reversal of the issue-time debit, and the account's computed totals recompute. A case already `SUSPENDED` under a renewed freeze cascade stays `SUSPENDED` (the cascade is idempotent). Unfreezing reverses link 1 only: every `SUSPENDED` case with a `prior_status` recorded, resolving to this plan, returns to its `prior_status`, and `prior_status` is cleared.

Termination is deliberately gentler: it cascades nothing onto in-flight cases, which run to their natural conclusions. What termination does change is the future — a terminated plan grants every participant the `PLAN_TERMINATION` qualifying event for newly submitted cases (§3.3), so the eligible-population gate opens precisely because the plan is going away.

### 3.2. Participants, Accounts, and Money Sources

`PlanSponsorAdmin` registers a **Participant** with a `full_name`, a `date_of_birth`, an `employment_status` of `ACTIVE`, `SEPARATED`, `RETIRED`, or `DISABLED`, and a `marital_status` of `SINGLE`, `MARRIED`, `WIDOWED`, or `DIVORCED`. When `employment_status` is `SEPARATED` or `RETIRED`, a `separation_date` must accompany the registration; omitting it is a malformed-payload `ERR_VALIDATION`. Two read-only ages are derived from `date_of_birth` against the logical clock: `age_months`, the count of complete calendar months elapsed — computed as twelve times the year difference plus the month difference, minus one when the clock's day-of-month is earlier than the birth day-of-month — and `current_age_years`, which is `age_months` divided by twelve and truncated to two decimal places. A participant whose birthday has not yet occurred in the clock's current month is one month younger than the naive subtraction suggests; the minus-one correction is what makes the 59½-year boundary land exactly.

An **Account** joins a participant to a plan. A `PlanSponsorAdmin` opens one by naming the `participant_id` and `plan_id` and optionally seeding `initial_balances`, a list from which one **MoneySourceBalance** row is created per entry, each carrying a `source_type`, a `balance_cents`, and optionally a `basis_cents` and a `vested_pct`. The pair (`participant_id`, `plan_id`) is unique: a second account for the same participant at the same plan is rejected with `ERR_ACCOUNT_ALREADY_EXISTS`. Every money-source row obeys three invariants: `balance_cents` is never negative; `basis_cents` defaults to 0, is never negative, and never exceeds its row's `balance_cents` whenever it is positive; and `vested_pct` is an integer from 0 to 100, defaulting to 100 — non-employer sources are always fully vested at 100. The `source_type` is one of `PRE_TAX`, `EMPLOYER_PRETAX`, `ROTH`, or `AFTER_TAX`, and is unique per account: at most one row per (account, source type) pair.

Three computed totals ride on every account read. `total_balance_cents` is the plain sum of `balance_cents` across all of the account's money-source rows, regardless of any status. `vested_balance_cents` applies the floor-per-row-then-sum discipline of §2.7: for each row, truncate the product of `balance_cents` and `vested_pct` divided by 100 down to a whole cent, then sum the truncated values. `basis_cents` on the account is the sum of `basis_cents` across all rows — the participant's total tax-paid basis, after-tax contributions plus Roth tax-paid amounts. An account is `ACTIVE` on creation and auto-transitions to `CLOSED` the moment its `total_balance_cents` reaches zero on a case terminal transition (`COMPLETED` or `INCOMPLETE`) or on execution of a plan-to-plan transfer; operations requiring an `ACTIVE` account thereafter fail with `ERR_ACCOUNT_NOT_ACTIVE`.

### 3.3. Opening a Case: Types, Elections, and the Submit-Time Gate

All movement of money out of or between plans is organized as a **RolloverCase**. A `Participant` opens a case in `DRAFT` status (version 1) by naming a `case_type` — `DIRECT_ROLLOVER_OUT`, `INDIRECT_ROLLOVER_OUT`, `PLAN_TRANSFER`, `IN_PLAN_ROTH_CONVERSION`, or `ROLLOVER_IN` — plus the election fields appropriate to the type. `source_account_id` identifies where money leaves and is required for the three outbound-and-conversion types (`DIRECT_ROLLOVER_OUT`, `INDIRECT_ROLLOVER_OUT`, `PLAN_TRANSFER`, `IN_PLAN_ROTH_CONVERSION`); it is null for `ROLLOVER_IN`, whose source is external. `receiving_account_id` is required for `ROLLOVER_IN`, `PLAN_TRANSFER`, and `IN_PLAN_ROTH_CONVERSION` — for a conversion it is the very same account as the source — must be an `ACTIVE` account of the same participant, and for a transfer must sit at the receiving plan; it is null otherwise. The destination of an outbound rollover — `DIRECT_ROLLOVER_OUT` or `INDIRECT_ROLLOVER_OUT` — is polymorphic: exactly one of `receiving_plan_id` (an internal plan) or `receiving_institution_name` (a free-text external institution) must be set; a `PLAN_TRANSFER` always names `receiving_plan_id` and never an institution name. `requested_amount_cents` elects a partial amount; when null it means the full vested balance (for a plan-to-plan transfer, the full balance including unvested money, since a transfer is not a distribution — a `requested_amount_cents` elected on a `PLAN_TRANSFER` is recorded but ignored at execution, which always moves the full balance), and when present it must be positive. `withholding_acknowledged` records the participant's acknowledgement of mandatory federal withholding, defaulting to `false`. While a case is `DRAFT`, the participant may amend its elections — `requested_amount_cents`, `receiving_plan_id`, `receiving_institution_name`, and `withholding_acknowledged` — subject to the optimistic-concurrency check of §2.8; each successful amendment advances the case's `version` by 1 and wholly replaces the prior election set. Case creation applies no plan-state gate: a DRAFT case may be opened while the source or receiving plan is `FROZEN` (or otherwise not `ACTIVE`); the frozen-plan rejection (`ERR_PLAN_FROZEN`) is scoped to the submit flow described below. Creation does already enforce, however, the structural election rules above (`ERR_VALIDATION`), the cross-reference consistency of the elections — a conversion whose `receiving_account_id` differs from its `source_account_id`, a transfer whose receiving plan equals the source account's plan, or a receiving account belonging to another participant or not sitting at `receiving_plan_id` (`ERR_ACCOUNT_PARTICIPANT_MISMATCH`, `ERR_SAME_PLAN_TRANSFER`) — a non-positive `requested_amount_cents` (`ERR_VALIDATION`), and, where a source account exists and the type is not `PLAN_TRANSFER`, a `requested_amount_cents` above the source account's current `vested_balance_cents` (`ERR_AMOUNT_EXCEEDS_VESTED`). An amendment re-checks only the positivity of the amount; the vested comparison is left to submit.

A source account may host at most one non-terminal case at a time. The occupation interval is half-open — a case occupies its source account from creation until it reaches a terminal state — so a second case opened on the same account while the first is still in flight is rejected with `ERR_OPEN_CASE_EXISTS`, but a case opened the moment its predecessor completes is allowed.

Submitting a case is the pivotal moment at which the system takes its eligibility snapshot. The acting participant must own the source account (or the receiving account, for `ROLLOVER_IN`); an ownership violation is masked as `ERR_CASE_NOT_FOUND`. Only a `DRAFT` case may be submitted; from any other status the submit is rejected with `ERR_CASE_INVALID_STATE`. The submit then enforces its checks **in the fixed priority order of §2.9**, which here unfolds as: existence and ownership first; then state guards — the source plan must be `ACTIVE` (a `FROZEN` plan yields `ERR_PLAN_FROZEN`, while a `TERMINATED` plan notably does *not* block submission, because termination is itself a qualifying event) and the source account must be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), and for `ROLLOVER_IN`, which has no source account, these two guards apply to the receiving plan and the receiving account instead (a `FROZEN` receiving plan yields `ERR_PLAN_FROZEN`, a non-`ACTIVE` receiving account `ERR_ACCOUNT_NOT_ACTIVE`); then cross-reference consistency, including that a `PLAN_TRANSFER`'s receiving plan differs from the source account's plan (else `ERR_SAME_PLAN_TRANSFER`) and that any required `receiving_account_id` belongs to the same participant and sits at `receiving_plan_id` (else `ERR_ACCOUNT_PARTICIPANT_MISMATCH`); then the capability and eligibility gates; and only then the amount check.

The eligibility snapshot evaluates the participant's **qualifying event**, stored on the case as `qualifying_event`, with branch priority pinned top-down — the first matching branch wins:

1. If the source plan's `status` is `TERMINATED`, the event is `PLAN_TERMINATION`. Plan termination overrides every employment-based event.
2. Else if the participant's `employment_status` is `SEPARATED` or `RETIRED`, the event is `SEPARATION`.
3. Else if `employment_status` is `DISABLED`, the event is `DISABILITY`.
4. Else if the participant's `age_months` at the clock date is at least 714 — that is, exactly 59½ years, the age threshold pinned in whole months — the event is `AGE_59_HALF`. This is the fallback branch and the only one sensitive to the 59.50 boundary.
5. Otherwise the event is `NONE`, and the submit is rejected with `ERR_NOT_ELIGIBLE`.

`ROLLOVER_IN` and `IN_PLAN_ROTH_CONVERSION` cases are exempt from the qualifying-event requirement entirely — inbound money needs no distribution event, and a conversion is not a distribution — and their `qualifying_event` is stored as null. Alongside eligibility, submit enforces the remaining capability gates: an `INDIRECT_ROLLOVER_OUT` case must carry `withholding_acknowledged` as true (else `ERR_WITHHOLDING_ACK_REQUIRED`); a `PLAN_TRANSFER` requires the receiving plan's `accepts_incoming_transfers`, a `ROLLOVER_IN` requires `accepts_incoming_rollovers`, a conversion requires `allows_in_plan_roth_conversion`, the presence of after-tax basis in scope — the source account holding an `AFTER_TAX` row with `basis_cents` greater than zero — requires the destination plan's `accepts_after_tax_basis` (for a conversion the destination plan is the source plan itself; when the destination is an external institution named through `receiving_institution_name`, no internal plan is involved and this gate does not apply), and a loan-bearing transfer requires `accepts_loan_transfers` — any failure answered with `ERR_PLAN_CAPABILITY_REJECTED`. The open-case exclusivity rule (`ERR_OPEN_CASE_EXISTS`) guards here too. Finally, the amount check: a non-null `requested_amount_cents` must not exceed the source account's `vested_balance_cents` (else `ERR_AMOUNT_EXCEEDS_VESTED`); a `PLAN_TRANSFER` ignores this check because it moves the full balance by definition.

### 3.4. The Documentation Loop and the Eligibility Decision

Submit also computes the case's **required-document set** and routes the case within the same request: if the set is empty, the case lands directly in `ELIGIBILITY_REVIEW`; otherwise it lands in `DOCS_PENDING`. Documents are created in exactly the deterministic order listed below — the list order is part of the contract:

1. `SPOUSAL_CONSENT`, required when the source plan's `requires_spousal_consent` flag is set, the participant's `marital_status` is `MARRIED`, the account's `vested_balance_cents` is *strictly greater than* the plan's `spousal_consent_threshold_cents` — a vested balance exactly equal to the threshold does not trigger the requirement — and the case type is one of `DIRECT_ROLLOVER_OUT`, `INDIRECT_ROLLOVER_OUT`, or `PLAN_TRANSFER`.
2. `SEPARATION_VERIFICATION`, required when the qualifying event is `SEPARATION`.
3. `DISABILITY_PROOF`, required when the qualifying event is `DISABILITY`.
4. `IDENTITY_PROOF`, required for `INDIRECT_ROLLOVER_OUT` cases.
5. `RECEIVING_PLAN_ACCEPTANCE`, required for `DIRECT_ROLLOVER_OUT` and `PLAN_TRANSFER` cases.
6. `SOURCE_PLAN_STATEMENT`, required for `ROLLOVER_IN` cases.

Each document row starts in `REQUIRED` status, and there is at most one row per (case, `doc_type`) pair. The participant moves a document `REQUIRED → SUBMITTED` by submitting it, but only while the document is in `REQUIRED` or `REJECTED` (otherwise `ERR_DOCUMENT_INVALID_STATE`, evaluated first) and only while the owning case is in `DOCS_PENDING` (otherwise `ERR_CASE_INVALID_STATE`); submission records the participant's `X-User-ID` as `submitted_by` and clears any prior `reviewed_by`. A `RolloverProcessor` then reviews each `SUBMITTED` document with a `decision` of `ACCEPTED` or `REJECTED`; reviewing a document that is not `SUBMITTED` is rejected with `ERR_DOCUMENT_INVALID_STATE`. Acceptance records the reviewer's `X-User-ID` as `reviewed_by` and bubbles up. The bubble-up rule — evaluated on every document submission and on every accepting review — advances the case `DOCS_PENDING → ELIGIBILITY_REVIEW` as soon as no document row on the case remains in `REQUIRED` or `REJECTED` status, that is, when every row stands at `SUBMITTED` or `ACCEPTED`; a `REJECTED` sibling therefore blocks advancement until it is resubmitted. Rejection requires a `review_note` (its absence is a malformed-payload `ERR_VALIDATION`), records `reviewed_by`, stores the note, and cascades in the opposite direction — if the case had already reached `ELIGIBILITY_REVIEW`, it is reopened to `DOCS_PENDING`, restarting the loop. A rejected document may be resubmitted (`REJECTED → SUBMITTED`), which clears `reviewed_by` and sets `submitted_by` anew; the review may therefore cycle as many times as needed. `REQUIRED` and `SUBMITTED` document rows are never cascade-deleted — they persist for audit even when a case is cancelled.

Once a case sits in `ELIGIBILITY_REVIEW`, a `RolloverProcessor` renders one of three decisions, each expressed through the `decision` input. The precondition common to all three is that the case is currently in `ELIGIBILITY_REVIEW` (else `ERR_CASE_INVALID_STATE`).

- **APPROVE** requires that every `RequiredDocument` row on the case be in `ACCEPTED` status (else `ERR_DOCUMENTS_OUTSTANDING`). On approval the case records `eligibility_decided_by` as the deciding operator's `X-User-ID` — the segregation-of-duties anchor of §2.6 — and routes by type: outbound money types (`DIRECT_ROLLOVER_OUT`, `INDIRECT_ROLLOVER_OUT`) and conversions move to `ELIGIBLE`, while `PLAN_TRANSFER` and `ROLLOVER_IN` cases move directly to `ACCEPTANCE_PENDING`, since no disbursement is assembled for them.
- **DENY** requires a `denial_reason` (its absence is `ERR_VALIDATION`), stores the reason on the case, and moves the case to `DENIED`, a terminal state.
- **REQUEST_DOCS** reopens the documentation loop: the case returns to `DOCS_PENDING` and new `RequiredDocument` rows are inserted in `REQUIRED` status for exactly the document types named in the decision's `request_doc_types` input — which must be a non-empty list of valid document types (otherwise `ERR_VALIDATION`) — deduplicated by type, with a type that already has a row on the case skipped rather than duplicated. Review may demand more documents repeatedly.

A participant may abandon a case by cancelling it, but only from the pre-disbursement states `DRAFT`, `DOCS_PENDING`, or `ELIGIBILITY_REVIEW`; any other status — including every terminal state — rejects the cancellation with `ERR_CASE_INVALID_STATE`. Cancellation lands the case in `CANCELLED` and leaves its documents in place for audit.

### 3.5. Source and Receiving Plan Verification

Before money changes hands, the plans on either side of a movement must be verified. A `RolloverProcessor` opens a **SourcePlanVerification** on a case by naming its `direction` and its `method`. A verification may be opened while the case is in any status, and a case may carry multiple verifications; each consuming gate is satisfied by any verification of the required direction standing at `VERIFIED`. The direction is `OUTBOUND` when the system must verify that the receiving plan is qualified before funds are sent, or `INBOUND` when it must verify the source plan before inbound funds are credited. The method is one of `PLAN_LETTER`, `IRS_FORM_LOOKUP`, or `THIRD_PARTY_REGISTRY`. The verification is born `PENDING` and completes when a processor records an `outcome` of `VERIFIED` or `FAILED` — completing a verification that is no longer `PENDING` is rejected with `ERR_VERIFICATION_INVALID_STATE`. A `VERIFIED` completion stamps `verified_at` with the logical clock; `FAILED` stamps nothing. Both outcomes are terminal. The two gates that consume verifications are stated where they apply: assembling a direct-rollover disbursement demands an `OUTBOUND` verification at `VERIFIED` (§3.6), and posting inbound rollover credit demands an `INBOUND` one (§3.8) — each failing the gate with `ERR_VERIFICATION_NOT_VERIFIED`.

### 3.6. Assembling the Outbound Disbursement: Allocation, Withholding, and Forfeiture

For an `ELIGIBLE` case of type `DIRECT_ROLLOVER_OUT` or `INDIRECT_ROLLOVER_OUT`, a `RolloverProcessor` assembles the disbursement by naming a `method` of `CHECK`, `ACH`, `WIRE`, or `INTERNAL_BOOK_ENTRY`. Four preconditions guard the assembly, evaluated in §2.9 order: the case must be `ELIGIBLE` and of one of those two types (else `ERR_CASE_INVALID_STATE`); the segregation-of-duties rule must pass — the assembling operator's `X-User-ID` must differ from `eligibility_decided_by` (else `ERR_SOD_VIOLATION`); no non-`CANCELLED` disbursement may already exist for the case (else `ERR_DISBURSEMENT_ALREADY_EXISTS`); and for a `DIRECT_ROLLOVER_OUT` an `OUTBOUND` verification on the case must already stand at `VERIFIED` (else `ERR_VERIFICATION_NOT_VERIFIED`).

Assembly runs two pinned calculations in sequence and locks their outputs onto the case.

**Source allocation** distributes the elected gross across the account's money-source rows. The eligible source set is the rows with a positive `balance_cents` — all four source types for outbound cases. Per row, vested cents are computed by the floor rule of §2.7: the product of `balance_cents` and `vested_pct` divided by 100, truncated down to a whole cent. The gross is then the elected `requested_amount_cents` when present — a *partial* election — or, when null, the *full vested* sum of all rows' vested cents. Each source's raw share is the exact rational value gross times that source's vested cents, divided by the total vested cents. Each source's allocation is the floor of its raw share; the leftover cents — the gross minus the sum of the floors — are handed out one cent each to the sources with the largest fractional parts, ties broken by the pinned source-type order `AFTER_TAX`, then `EMPLOYER_PRETAX`, then `PRE_TAX`, then `ROTH`. Basis travels pro-rata with each allocation: each source's basis share is its allocated cents times its row's `basis_cents` divided by its row's `balance_cents`, rounded half-up to a whole cent (zero when the row's balance is zero). The pinned order matters: floor-then-remainder per source first, and only then per-source basis rounding. The case locks `gross_cents` as the gross, `basis_portion_cents` as the sum of the basis shares, and `taxable_cents` as the gross minus the basis portion.

**Withholding** then applies, and its evaluation order is pinned to break the apparent circle between net, withholding, and taxable: gross first, then basis portion, then taxable as gross minus basis, then withholding, then net as gross minus withholding. Net never feeds back into taxable — taxable depends only on gross and basis. For an `INDIRECT_ROLLOVER_OUT`, withholding is mandatory and cannot be waived or reduced: `withholding_cents` is 20 percent of `taxable_cents`, rounded half-up to a whole cent. For a `DIRECT_ROLLOVER_OUT` — trustee-to-trustee movement — withholding is zero, as it is for transfers and conversions. The case locks `withholding_cents` and `net_cents` (gross minus withholding).

Assembly then creates a **Disbursement** in `PENDING` status carrying a snapshot trio — `gross_cents`, `withholding_cents`, and `net_cents` — for which the invariant `gross_cents` equals `withholding_cents` plus `net_cents` always holds, and debits each money-source row of the source account by its allocated amount, with account totals recomputing. A *full-vested* election additionally forfeits the unvested employer remainder: `forfeiture_cents` is set to the unvested portion of the `EMPLOYER_PRETAX` rows (balance minus vested for those rows) and the unvested employer balance is zeroed. A *partial* election forfeits nothing. `forfeiture_cents` defaults to zero and stays zero whenever nothing is forfeited.

### 3.7. Issuance, the 60-Day Window, and the Follow-Up Notices

A `PENDING` disbursement becomes `ISSUED` when a `RolloverProcessor` issues it, provided the disbursement is `PENDING` (else `ERR_DISBURSEMENT_INVALID_STATE`), the owning case is `ELIGIBLE` (else `ERR_CASE_INVALID_STATE` — notably, a case `SUSPENDED` by a plan freeze blocks issuance), and the issue date read from the logical clock does not fall inside any freeze window of the source plan under the closed-interval rule of §2.10 (else `ERR_DISBURSEMENT_IN_FREEZE_WINDOW`). Issuance stamps the disbursement's `issued_date` with the clock date and drives the owning case forward by type: a `DIRECT_ROLLOVER_OUT` case moves `ELIGIBLE → DISBURSED`, while an `INDIRECT_ROLLOVER_OUT` case moves `ELIGIBLE → AWAITING_REDEPOSIT`.

On **first issuance only**, three things anchor themselves and are never re-anchored by later reissue. The case's `disbursement_issued_date` is set to the clock date — the basis of the 60-day deadline — and never overwritten. For indirect cases, `rollover_deadline_date` is computed as exactly 60 calendar days after `disbursement_issued_date`. And three **FollowUpNotice** rows are created for an indirect case, in `SCHEDULED` status: `notice_seq` 1 scheduled 30 days after the issue date, `notice_seq` 2 at 45 days, and `notice_seq` 3 at 55 days, each carrying its `scheduled_date`. A `DIRECT_ROLLOVER_OUT` issuance instead drafts its tax form immediately: a `DRAFT` 1099-R with `distribution_code` `CODE_G`, `gross_distribution_cents` equal to the case gross, `federal_withholding_cents` of zero, and `taxable_amount_cents` of zero, reflecting a non-taxable trustee-to-trustee movement. An `INDIRECT_ROLLOVER_OUT` issuance drafts the *provisional* 1099-R: `gross_distribution_cents` equal to the case gross, `federal_withholding_cents` equal to the withheld amount, and `taxable_amount_cents` equal to the full `taxable_cents`, on the conservative assumption that nothing will be redeposited.

The **60-day rule** governs indirect rollovers with an inclusive upper bound: a redeposit whose `received_date` is on or before `rollover_deadline_date` is timely — the deadline day itself counts — while a `received_date` of the day after the deadline or later is rejected with `ERR_DEPOSIT_PAST_DEADLINE`. If the logical clock's date passes `rollover_deadline_date` while the case's `credited_total_cents` is still less than its `gross_cents`, the daily sweep (§3.11) marks the case `INCOMPLETE`.

An issued disbursement may be marked `RETURNED` (a bounced check, a rejected wire) while it is `ISSUED` — otherwise `ERR_DISBURSEMENT_INVALID_STATE`. A `RETURNED` disbursement may be reissued, returning to `ISSUED` with `issued_date` refreshed to the current clock date (the freeze-window gate is not re-evaluated on reissue), provided the owning case is `DISBURSED` or `AWAITING_REDEPOSIT` (else `ERR_CASE_INVALID_STATE`); crucially, for indirect cases the 60-day deadline does **not** restart — `rollover_deadline_date` remains anchored to the first issuance. Finally, a disbursement in `PENDING` or `RETURNED` may be cancelled, transitioning to the terminal `CANCELLED` status with full compensation: every money-source row of the source account is credited back by exactly its issue-time allocation of balance and basis, any forfeited unvested employer remainder is likewise restored and the case's `forfeiture_cents` is reset to zero, so source balances return precisely to their pre-issue values.

For a direct rollover that has reached `DISBURSED`, the closing act is confirming receipt: a `RolloverProcessor` confirms that the receiving institution took the funds, moving the case `DISBURSED → COMPLETED`, provided the case is `DISBURSED` and of type `DIRECT_ROLLOVER_OUT` (else `ERR_CASE_INVALID_STATE`) and its disbursement stands at `ISSUED` (else `ERR_DISBURSEMENT_INVALID_STATE`).

### 3.8. Plan-to-Plan Transfers, Inbound Rollovers, and Loan Movement

A `PLAN_TRANSFER` or `ROLLOVER_IN` case that has been approved sits in `ACCEPTANCE_PENDING` waiting for a `RolloverProcessor` to execute it — under segregation of duties, never the same operator who approved it (`ERR_SOD_VIOLATION`); a case in any other status rejects execution with `ERR_CASE_INVALID_STATE`.

**Executing a plan-to-plan transfer** first requires that no `ACTIVE` loan remains on the source account (else `ERR_LOANS_OUTSTANDING`) — loans must be transferred or offset before the money moves. Execution then moves every money-source row book-entry to the receiving account, preserving each row's `balance_cents`, `basis_cents`, and `vested_pct` per source: basis tracking survives the move, and unvested employer money moves too — a transfer is not a distribution, so nothing is forfeited. Rows are copied in the pinned source-type order `AFTER_TAX`, `EMPLOYER_PRETAX`, `PRE_TAX`, `ROTH`. A source type the receiving account already carries is merged into its existing row — balances and basis summed, the receiving row's own `vested_pct` left unchanged — while a source type absent there is created fresh with the source row's `vested_pct` preserved; rows holding zero balance and zero basis are not copied at all. The source account's balances are zeroed and its status becomes `CLOSED`; the receiving account's computed totals recompute; no 1099-R is produced, because a transfer is non-taxable; and the case completes.

**Executing an in-plan Roth conversion** requires the case to be `ELIGIBLE` and of type `IN_PLAN_ROTH_CONVERSION` (else `ERR_CASE_INVALID_STATE`), under the same segregation-of-duties rule (`ERR_SOD_VIOLATION`). The source-allocation calculation of §3.6 runs with an eligible source set of the `PRE_TAX` and `AFTER_TAX` rows only: the gross is the elected `requested_amount_cents` or, when null, the full vested sum of those rows; basis travels pro-rata exactly as in §3.6, locking `gross_cents`, `basis_portion_cents`, and `taxable_cents` on the case. A conversion never withholds — `withholding_cents` is zero and `net_cents` equals the gross. The elected source rows are debited by their allocations, and the account's `ROTH` row — created if absent — is credited the full gross to both `balance_cents` and `basis_cents`, since converted amounts are tax-paid Roth basis. Execution immediately drafts a 1099-R for the logical clock's tax year with `gross_distribution_cents` equal to the gross, `federal_withholding_cents` zero, `taxable_amount_cents` equal to the gross minus the basis portion, and `distribution_code` `CODE_7` when the participant's `age_months` at execution is at least 714, else `CODE_1`. The case then moves directly to `COMPLETED` — a conversion is irrevocable — and the account auto-closes if its total balance reached zero.

**Posting inbound rollover credit** for a `ROLLOVER_IN` case requires an `INBOUND` verification on the case at `VERIFIED` (else `ERR_VERIFICATION_NOT_VERIFIED`) and, when the breakdown carries a positive `after_tax_basis_cents`, a receiving plan whose `accepts_after_tax_basis` is set (else `ERR_PLAN_CAPABILITY_REJECTED`). The processor posts the inbound breakdown — `pre_tax_cents`, `roth_cents`, `roth_basis_cents`, and `after_tax_basis_cents` — where all four fields are mandatory integers of zero or more, `roth_basis_cents` must not exceed `roth_cents`, and the three credit legs must total a positive amount (violations are `ERR_VALIDATION`). The receiving account's money-source rows are credited accordingly, each target row created with zero balance first if the account does not already carry that source type: `pre_tax_cents` into the `PRE_TAX` source, `roth_cents` into the `ROTH` source with `roth_basis_cents` as its tax-paid basis, and `after_tax_basis_cents` into the `AFTER_TAX` source, credited to both its balance and its basis. A `DRAFT` 5498 for the logical clock's current tax year is created or updated (§3.10), accumulating the total posted credit (`pre_tax_cents` + `roth_cents` + `after_tax_basis_cents`), and the case completes.

**Loans** ride along with transfers through two terminal paths out of `ACTIVE`. A `PlanSponsorAdmin` creates a loan on an account by naming `outstanding_balance_cents` (an integer greater than zero), `interest_rate_bp` (an integer from 0 to 5000), and `term_months` (an integer from 1 to 360); violations are `ERR_VALIDATION`, and the loan is born `ACTIVE` with `offset_repaid_cents` at zero. A `RolloverProcessor` may *transfer* a loan note by naming a `receiving_account_id`: the loan must be `ACTIVE` (else `ERR_LOAN_INVALID_STATE`); the receiving account must exist (else `ERR_ACCOUNT_NOT_FOUND`), be `ACTIVE`, and belong to the same participant as the current account (else `ERR_ACCOUNT_PARTICIPANT_MISMATCH`); the receiving account's plan must have `accepts_loan_transfers` set and be `ACTIVE` itself (else `ERR_LOAN_NOT_TRANSFERRABLE`); and a `PLAN_TRANSFER` case on the source account must sit in `ACCEPTANCE_PENDING` naming that receiving plan (else `ERR_CASE_INVALID_STATE`). The loan's `account_id` is reassigned across the aggregate boundary, its status becomes `TRANSFERRED`, and its `outstanding_balance_cents`, `interest_rate_bp`, and `term_months` are preserved untouched.

Alternatively, a processor may *offset* an `ACTIVE` loan (else `ERR_LOAN_INVALID_STATE`): the loan becomes `OFFSET`, `offset_at` is stamped with the logical clock, and the offset window is computed. The offset is a *qualified plan loan offset* — `offset_qualified` true — when, at offset time, the participant's `employment_status` is `SEPARATED` or `RETIRED`, or the holding plan's `status` is `TERMINATED`; otherwise it is a standard offset. The deadline variant follows: a standard offset sets `offset_rollover_deadline` to 60 calendar days after the offset date, inclusive, mirroring the indirect-rollover rule, while a qualified plan loan offset sets it to October 15 of the year following the offset's tax year — the participant's filing deadline including extensions — a materially later deadline for the same outstanding balance. Offset is a taxable event and immediately drafts a 1099-R: `gross_distribution_cents` and `taxable_amount_cents` both equal to the loan's `outstanding_balance_cents`, `federal_withholding_cents` zero, and `distribution_code` `CODE_7` when the participant's `age_months` at offset is at least 714, else `CODE_1`. The cumulative redeposits applied against the offset are tracked in `offset_repaid_cents`, starting at zero.

### 3.9. Redeposits: Completing the 60-Day Rollover

When rollover funds arrive, a `RolloverProcessor` records a **Redeposit** naming the `receiving_account_id`, the `amount_cents` (which must be positive), the `received_date` on which funds were received, and exactly one linkage: `rollover_case_id` when the deposit satisfies an indirect-rollover case, or `loan_id` when it rolls over a loan offset. A case-linked deposit requires the case to have its `rollover_deadline_date` anchored by a first issuance (§3.7) — otherwise `ERR_CASE_INVALID_STATE` — and a loan-linked deposit requires the loan to stand at `OFFSET` with its `offset_rollover_deadline` set, otherwise `ERR_LOAN_INVALID_STATE`. The receiving account must belong to the same participant as the linked case or loan (else `ERR_ACCOUNT_PARTICIPANT_MISMATCH`), and the amount must not exceed the remaining shortfall — the case's gross minus its `credited_total_cents`, or the loan's outstanding balance minus its `offset_repaid_cents` — else `ERR_DEPOSIT_EXCEEDS_REMAINING`. The deadline gate is evaluated at creation and re-checked at credit time: a case-linked deposit's `received_date` must be on or before the case's `rollover_deadline_date`, and a loan-linked deposit's `received_date` on or before the loan's `offset_rollover_deadline`; a late date is rejected with `ERR_DEPOSIT_PAST_DEADLINE`. A new redeposit stands at `PENDING_VERIFICATION`.

Crediting a redeposit requires it to still be `PENDING_VERIFICATION` (else `ERR_REDEPOSIT_INVALID_STATE`) and the receiving account to be `ACTIVE` (else `ERR_ACCOUNT_NOT_ACTIVE`), and re-checks the same deadline gate. The credit cascades by linkage. For a case-linked deposit, the case's `credited_total_cents` — always the sum of `amount_cents` over the case's `CREDITED` redeposits only, excluding `PENDING_VERIFICATION` and `REJECTED` rows — grows by the deposit amount; the receiving account's `PRE_TAX` money-source row — created if absent — is credited the full deposit amount with its basis unchanged; and a `DRAFT` 5498 for the receiving participant and the calendar year of the deposit's `received_date` is created or updated. When the credit lifts `credited_total_cents` to at least the case's `gross_cents` — equality completes — the case moves `AWAITING_REDEPOSIT → COMPLETED` with its own cascades: every still-`SCHEDULED` follow-up notice flips to `SKIPPED`, and the 1099-R recomputes to its *corrected* variant (§3.10). For a loan-linked deposit, the loan's `offset_repaid_cents` grows by the deposit amount. A processor may instead reject a `PENDING_VERIFICATION` redeposit, landing it in the terminal `REJECTED` status with no further effect.

### 3.10. Tax Forms: Drafting, Finalizing, and the Correction Chain

The system produces two form types, recorded on each form as `form_type`. **FORM_1099_R** is drafted per triggering event — one form per case or per loan offset — carrying `gross_distribution_cents` (the event's gross), `federal_withholding_cents` (the event's withholding), and a `distribution_code`: `CODE_G` for a direct rollover (taxable zero); otherwise `CODE_7` when the participant's `age_months` at the event is at least 714, or `CODE_1` when younger. Its `tax_year` is the issue year. **FORM_5498** is aggregated: one `DRAFT` per (`participant_id`, `tax_year`), its `rollover_contribution_cents` accumulating the sum of every `CREDITED` redeposit amount and every `ROLLOVER_IN` posted credit received in that tax year, and its `fair_market_value_cents` snapshotting the receiving account's `total_balance_cents` at the latest credit. Its `tax_year` is the credit year — the calendar year of the redeposit's `received_date` for redeposit credits, or of the logical-clock date for a `ROLLOVER_IN` posted credit — which may span a year-end boundary for indirect rollovers disbursed late in December and redeposited in January. Every form traces its origin through `rollover_case_id` or `loan_id` as applicable.

An indirect case's 1099-R lives in two variants. The **provisional** variant, drafted at issuance, assumes the worst: `taxable_amount_cents` equals the full `taxable_cents`. The **corrected** variant applies once the 60-day outcome is known — whether the case completed or the sweep marked it `INCOMPLETE`: credited dollars are applied to the taxable portion first, so the corrected taxable is the original `taxable_cents` minus the smaller of `credited_total_cents` and `taxable_cents`. Identical inputs therefore yield a smaller taxable amount under the corrected variant whenever anything was redeposited. While the form is still `DRAFT`, the recomputation simply rewrites the draft. If the form has already been `ISSUED`, the recomputation auto-files a correction: the old row becomes `SUPERSEDED`, and a new row appears already `ISSUED` with `revision` one greater than the old row's, its `supersedes_id` pointing back at the row it replaces.

A `TaxReportingOfficer` finalizes a `DRAFT` form, moving it to `ISSUED` and locking its amounts — draft recomputations stop applying from that moment; finalizing anything but a `DRAFT` is `ERR_TAX_FORM_INVALID_STATE`. A `TaxReportingOfficer` may also file a manual correction against an `ISSUED` form (anything else is `ERR_TAX_FORM_INVALID_STATE`), subject to the optimistic-concurrency check of §2.8 (`expected_tax_form_version` must match, else `ERR_STALE_VERSION`), optionally overriding `taxable_amount_cents`, `rollover_contribution_cents`, or `distribution_code`. The correction creates the same supersession chain as the automatic one: old row `SUPERSEDED` (its `version` incrementing by 1), new row `ISSUED` at the next `revision` with `supersedes_id` set. A form's `revision` is zero for the original and increments per correction. `SUPERSEDED` is terminal.

### 3.11. The Daily Sweep and Scheduled Notices

An `OperationsAgent` triggers the daily sweep, which performs two passes against the logical clock. First, it dispatches due follow-up notices: every `SCHEDULED` notice whose `scheduled_date` has been reached by the clock date and whose owning case still stands at `AWAITING_REDEPOSIT` transitions to `SENT`, recording `days_remaining` — the count of days from the send date to the case's `rollover_deadline_date` — and `outstanding_cents`, the case's `gross_cents` minus its `credited_total_cents` at send time. Notices whose case reached a terminal state before their scheduled date flip to `SKIPPED` instead. A due notice whose case stands in any other state — for example `SUSPENDED` under a plan freeze — is left `SCHEDULED`. Second, it catches lapsed windows: every indirect case whose clock date has passed its `rollover_deadline_date` with `credited_total_cents` still below `gross_cents` transitions `AWAITING_REDEPOSIT → INCOMPLETE`, cascading `SKIPPED` onto its remaining `SCHEDULED` notices and recomputing the 1099-R to the corrected variant — with the same auto-correction revision behavior of §3.10 when the form was already issued. The sweep reports a summary of its work: `notices_sent`, `notices_skipped`, and `cases_marked_incomplete`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new, distinct resource to a collection return a `201 Created` status code. Operations that modify an existing resource, drive a state transition, or execute a workflow step return a `200 OK` status code. All endpoints are mounted under the `/v1` prefix shown, except the logical-clock capability, which is mounted at the root. An unauthenticated `GET /v1/_health` liveness probe returning `{"status": "ok"}` also exists and is not part of the role mapping.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/plans` | Create a plan with capability flags | PlanSponsorAdmin |
| GET | `/v1/plans` | List plans; filterable by status | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/plans/{planId}` | Get a plan | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/plans/{planId}/freeze` | Freeze plan; cascades SUSPENDED onto open cases, CANCELLED onto their PENDING disbursements, and balance restoration onto source accounts | PlanSponsorAdmin |
| POST | `/v1/plans/{planId}/unfreeze` | Unfreeze plan; resumes SUSPENDED cases to prior status | PlanSponsorAdmin |
| POST | `/v1/plans/{planId}/terminate` | Terminate plan; grants the PLAN_TERMINATION qualifying event | PlanSponsorAdmin |
| POST | `/v1/plans/{planId}/freeze-windows` | Create a processing freeze window (closed interval) | PlanSponsorAdmin |
| GET | `/v1/plans/{id}/freeze-windows` | List freeze windows of a plan | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/participants` | Register a participant | PlanSponsorAdmin |
| GET | `/v1/participants/{participantId}` | Get a participant, with age computed against the logical clock | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/accounts` | Open an account with initial money-source balances | PlanSponsorAdmin |
| GET | `/v1/accounts` | List accounts; filterable by participant, plan, status | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/accounts/{accountId}` | Get an account with computed totals | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/accounts/{id}/source-balances` | List money-source balances of an account | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/accounts/{id}/redeposits` | List redeposits received by an account | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/accounts/{accountId}/loans` | Create an ACTIVE loan on an account | PlanSponsorAdmin |
| GET | `/v1/accounts/{id}/loans` | List loans currently held by an account; filterable by status | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/loans/{loanId}` | Get a loan | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/loans/{id}/redeposits` | List redeposits applied to a loan offset | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/loans/{loanId}/transfer` | Transfer a loan note to a receiving account within a plan-to-plan transfer | RolloverProcessor |
| POST | `/v1/loans/{loanId}/offset` | Offset a loan (taxable event); computes the qualified flag and offset deadline variant | RolloverProcessor |
| POST | `/v1/rollover-cases` | Create a rollover/transfer/conversion case (DRAFT) | Participant |
| GET | `/v1/rollover-cases` | List cases; filterable by source account, receiving account, receiving plan, status, case type | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/rollover-cases/{caseId}` | Get a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| PATCH | `/v1/rollover-cases/{caseId}` | Amend DRAFT case elections (optimistic concurrency on case version) | Participant |
| POST | `/v1/rollover-cases/{caseId}/submit` | Submit case: eligibility snapshot, required-document computation, auto-routing | Participant |
| POST | `/v1/rollover-cases/{caseId}/cancel` | Cancel a non-terminal case (pre-disbursement states only) | Participant |
| POST | `/v1/rollover-cases/{caseId}/decide-eligibility` | Processor decision: APPROVE, DENY, or REQUEST_DOCS | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/issue-disbursement` | Assemble the outbound disbursement: allocates sources, locks amounts, debits balances, creates a PENDING disbursement | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/confirm-receipt` | Confirm receiving institution receipt for a direct rollover | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/execute-transfer` | Execute the book-entry plan-to-plan transfer | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/execute-conversion` | Execute the irrevocable in-plan Roth conversion | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/post-credit` | Post inbound rollover funds with pre-tax/Roth/after-tax breakdown (basis tracking) | RolloverProcessor |
| POST | `/v1/rollover-cases/{caseId}/verifications` | Open a source/receiving plan verification | RolloverProcessor |
| GET | `/v1/rollover-cases/{id}/documents` | List required documents of a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/rollover-cases/{id}/disbursements` | List disbursements of a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/rollover-cases/{id}/redeposits` | List redeposits of a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/rollover-cases/{id}/verifications` | List verifications of a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/rollover-cases/{id}/notices` | List follow-up notices of a case | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/documents/{docId}/submit` | Participant submits (or resubmits) a required document | Participant |
| POST | `/v1/documents/{docId}/review` | Processor accepts or rejects a submitted document; bubble-up may advance the case | RolloverProcessor |
| POST | `/v1/verifications/{verId}/complete` | Complete a plan verification | RolloverProcessor |
| POST | `/v1/disbursements/{disbId}/issue` | Issue a PENDING disbursement: money leaves, case advances, tax form, notices, and deadline anchor on first issuance | RolloverProcessor |
| POST | `/v1/disbursements/{disbId}/cancel` | Cancel a PENDING or RETURNED disbursement; restores source balances exactly | RolloverProcessor |
| POST | `/v1/disbursements/{disbId}/return` | Mark an issued disbursement returned (e.g., check bounced) | RolloverProcessor |
| POST | `/v1/disbursements/{disbId}/reissue` | Reissue a returned disbursement; the 60-day deadline does not restart | RolloverProcessor |
| POST | `/v1/redeposits` | Record incoming rollover funds against a case or an offset loan | RolloverProcessor |
| POST | `/v1/redeposits/{redId}/credit` | Credit a redeposit; cascades completion and 5498 updates | RolloverProcessor |
| POST | `/v1/redeposits/{redId}/reject` | Reject a redeposit | RolloverProcessor |
| GET | `/v1/tax-forms` | List tax forms; filterable by participant, case, loan, supersedes, tax year, form type, status | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| GET | `/v1/tax-forms/{formId}` | Get a tax form | Participant, PlanSponsorAdmin, RolloverProcessor, TaxReportingOfficer, OperationsAgent |
| POST | `/v1/tax-forms/{formId}/finalize` | Finalize (issue) a DRAFT form; locks amounts | TaxReportingOfficer |
| POST | `/v1/tax-forms/{formId}/correct` | File a correction (optimistic concurrency on form version); supersedes the current ISSUED revision | TaxReportingOfficer |
| POST | `/v1/sweeps/daily` | Daily ops sweep: sends due follow-up notices, marks overdue indirect cases INCOMPLETE with tax-form recomputation | OperationsAgent |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving capability); startup default is exactly 2026-05-01T00:00:00Z | OperationsAgent |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API may return and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED_ROLE` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PLAN_NOT_FOUND` | 404 |
| `ERR_PARTICIPANT_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_CASE_NOT_FOUND` | 404 |
| `ERR_DOCUMENT_NOT_FOUND` | 404 |
| `ERR_VERIFICATION_NOT_FOUND` | 404 |
| `ERR_DISBURSEMENT_NOT_FOUND` | 404 |
| `ERR_REDEPOSIT_NOT_FOUND` | 404 |
| `ERR_LOAN_NOT_FOUND` | 404 |
| `ERR_TAX_FORM_NOT_FOUND` | 404 |
| `ERR_CASE_INVALID_STATE` | 409 |
| `ERR_PLAN_FROZEN` | 409 |
| `ERR_PLAN_TERMINATED` | 409 |
| `ERR_PLAN_NOT_FROZEN` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_DOCUMENT_INVALID_STATE` | 409 |
| `ERR_DISBURSEMENT_ALREADY_EXISTS` | 409 |
| `ERR_DISBURSEMENT_INVALID_STATE` | 409 |
| `ERR_REDEPOSIT_INVALID_STATE` | 409 |
| `ERR_VERIFICATION_INVALID_STATE` | 409 |
| `ERR_TAX_FORM_INVALID_STATE` | 409 |
| `ERR_LOAN_INVALID_STATE` | 409 |
| `ERR_SOD_VIOLATION` | 403 |
| `ERR_NOT_ELIGIBLE` | 422 |
| `ERR_WITHHOLDING_ACK_REQUIRED` | 422 |
| `ERR_PLAN_CAPABILITY_REJECTED` | 422 |
| `ERR_SAME_PLAN_TRANSFER` | 422 |
| `ERR_ACCOUNT_ALREADY_EXISTS` | 409 |
| `ERR_ACCOUNT_PARTICIPANT_MISMATCH` | 422 |
| `ERR_OPEN_CASE_EXISTS` | 409 |
| `ERR_VERIFICATION_NOT_VERIFIED` | 409 |
| `ERR_DOCUMENTS_OUTSTANDING` | 409 |
| `ERR_LOANS_OUTSTANDING` | 409 |
| `ERR_LOAN_NOT_TRANSFERRABLE` | 422 |
| `ERR_DISBURSEMENT_IN_FREEZE_WINDOW` | 422 |
| `ERR_FREEZE_WINDOW_OVERLAP` | 409 |
| `ERR_WINDOW_RANGE_INVALID` | 422 |
| `ERR_DEPOSIT_PAST_DEADLINE` | 422 |
| `ERR_DEPOSIT_EXCEEDS_REMAINING` | 422 |
| `ERR_AMOUNT_EXCEEDS_VESTED` | 422 |
| `ERR_STALE_VERSION` | 412 |

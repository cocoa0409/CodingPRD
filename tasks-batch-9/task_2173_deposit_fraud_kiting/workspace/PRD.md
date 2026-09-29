# Deposit Fraud & Kiting Detection API — Product Requirements Document

## 1. Introduction

A bank's deposit fraud unit lives at the intersection of two clocks. One is the availability clock the depositor sees: money arrives, some of it becomes spendable immediately, the rest matures on a published schedule. The other is the collection clock the bank sees: the item is still travelling, and it may come back unpaid days after the depositor has already withdrawn against it. Kiting is the deliberate exploitation of the gap between those two clocks — a ring of accounts circulating on-us checks so that each account is perpetually funded by float that never settles. Every workflow in this document exists because that gap has to be measured, priced, escalated, and eventually written off.

This service is the system of record for a deposit fraud unit's daily work. It scores new accounts before the first dollar arrives and rescores them whenever the picture changes; it verifies external funding sources by trial deposit; it prices availability holds and adjudicates requests to release them early; it traverses the on-us circulation graph looking for closed cycles; it tracks account-takeover indicators and drives step-up verification; it runs mule and kiting investigations through disposition to closure; it books deposit losses, refers them to recovery, and unwinds them if the decision is reversed; and it logs law-enforcement process with the record-preservation obligations that come attached. Six operating roles share the surface, and two of the sharpest controls in the system are duty separations that bite *inside* a single role rather than between roles.

Two design commitments run through everything that follows. First, arithmetic is exact: every monetary figure is an integer number of cents, every rate is expressed in basis points, and every rounding event is pinned to a specific step in a specific order — the difference between rounding each line and rounding the total is a real difference in the answer, and this specification always says which one applies. Second, time is explicit: the server keeps a logical clock that test harnesses and operators drive directly, and no window, deadline, hold maturity, or account age is ever computed from wall-clock time.

## 2. Global Specifications & System-Wide Principles

The API is mounted under `/deposit-fraud`. All request and response bodies are JSON.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not one of the six declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This is the very first thing evaluated on every endpoint without exception.

The six roles are `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel`, and `AccountHolder`.

- `OperationsAdmin` is the deposit-operations back office. It onboards depositors and opens accounts, declares and verifies external funding sources, takes deposits and posts their collection outcomes, books approved write-offs, posts recovery receipts, and controls the logical clock. It is also a reader on every listing and retrieval endpoint in the system.
- `FraudAnalyst` is the front-line investigator. Analysts run kiting scans, open cases manually, advance them into investigation, prepare early-release reviews, record takeover indicators, propose charge-offs, and draft and file suspicious-activity referrals.
- `FraudSupervisor` is the unit's second line. Supervisors decide and execute early-release reviews, dispose and close cases, approve and reverse charge-offs, and lift a locked access posture. A supervisor may also *prepare* an early-release review — which is precisely the situation the duty-separation rule is written for.
- `BsaOfficer` belongs to the Bank Secrecy Act unit and adjudicates the referrals the fraud unit files. It holds no write authority over accounts, holds, cases, or charge-offs; its only mutating capability is referral adjudication.
- `LegalCounsel` handles law-enforcement process end to end: logging incoming subpoenas, taking them under legal review, and signing the response.
- `AccountHolder` is the depositor acting on their own account. Its only mutating capability is answering a step-up challenge.

If the caller's role is present and well-formed but is not one of the roles authorised for the endpoint it is calling — the authorised set for each endpoint is listed in §4 — the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity is interpreted in one of two ways. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` to `X-User-ID`. Concretely, an `AccountHolder` reading a deposit account, or answering that account's step-up challenge, must have an `X-User-ID` equal to that account's `customer_id`; otherwise the request is rejected with `ERR_NOT_ACCOUNT_OWNER` (HTTP 403). When `X-User-Role` is `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, or `LegalCounsel`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it wherever a transition captures an actor — as `prepared_by_user_id` and `decided_by_user_id` on an override review, `approved_by_user_id` and `booked_by_user_id` on a charge-off, `drafted_by_user_id` and `adjudicated_by_user_id` on a referral, and `legal_reviewed_by_user_id` and `responded_by_user_id` on a subpoena — but it never compares that identifier to any entity's `id`.

Two of those recorded identifiers exist to support **segregation of duties**, and the rule is stated once here and enforced in two places. The operator who records a decision on an early-release review may not be the operator whose `X-User-ID` was captured as that review's `prepared_by_user_id`, and the counsel who signs a subpoena response may not be the counsel whose `X-User-ID` was captured as that subpoena's `legal_reviewed_by_user_id`. A violation of either is `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination and List Filtering

Every list endpoint accepts two optional query parameters. `limit` defaults to 10, has a minimum of 1 and a maximum of 100. `offset` defaults to 0 and has a minimum of 0. A `limit` or `offset` outside those bounds, or of the wrong type, is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Results are always ordered by `created_at` ascending. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside `meta`, where `total_count` is the number of rows matching the filter before pagination is applied and `has_more` is true exactly when rows remain beyond the current page.

Several listings accept an additional optional filter, and each filter narrows the result set before pagination and before `total_count` is computed. Accounts owned by a customer may be filtered by `lifecycle_status`. Funding sources on an account may be filtered by `verification_status`. Association edges on an account may be filtered by `link_type`. Deposits taken into an account may be filtered by `status` and, additionally, by `account_role`, which selects whether the account is being considered as the depositing side or the drawn-on side of the item. Subpoena, check-hold, override-review, referral, and charge-off listings all accept `status`; the fraud-case listing on an account accepts both `status` and `case_type`. A filter value that is not a declared member of the corresponding enumeration is `ERR_INVALID_REQUEST`.

### 2.4. Resource Identity, Timestamps and Versioning

Every stored resource in this system — depositors, deposit accounts, funding sources, association links, deposited items, check holds, override reviews, fraud cases, charge-offs, subpoena requests, and BSA referrals — carries the same four common properties. `id` is a server-minted UUID with no type prefix; clients never supply it. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits, taken from the logical clock described in §2.5. `version` is an integer that starts at 1 when the row is created and increases by exactly 1 on every mutation of that row. No entity in this system is exempt: all eleven resource kinds expose `id`, `created_at`, `updated_at`, and `version`.

Version increments are not decorative — they are the observable signal that a cascade actually touched a row. When one operation mutates several entities, each mutated entity's `version` advances by 1 and its `updated_at` is refreshed; entities a branch deliberately leaves alone do not advance. §2.8 describes the cascades themselves.

### 2.5. The Logical Clock

The server maintains a single logical clock, and every temporal value in the system reads from it: `opened_at` on an account, `deposit_at` on an item, `hold_start_at` and `hold_release_at` on a hold, `received_at` on a subpoena, the settlement, decision, execution, booking, submission and adjudication timestamps on every workflow entity, the account-age computation behind the new-account availability exception, the preservation-window and release-window comparisons, and the lateness test on a subpoena response. Before the clock is ever set, it reads exactly `2026-08-01T00:00:00Z`. It never falls back to real wall-clock time.

An `OperationsAdmin` may move the clock by supplying a `to_iso8601` instant; the response reports the clock's new value as `current_utc`. Moving the clock transitions nothing by itself: holds do not auto-release when they mature, subpoenas do not auto-expire when their deadline passes, and no account changes state. The new value is simply what every subsequent request reads.

### 2.6. Money, Basis Points and Rounding Discipline

All monetary amounts are integer cents. Every field whose name ends in `_cents` is an integer, never a decimal or a string, and a non-integer or out-of-range value in a request body is `ERR_INVALID_REQUEST`. Rates are expressed in basis points — hundredths of a percent — so applying a rate means multiplying by the basis-point figure and dividing by 10,000.

Wherever a monetary result of such a multiplication must be stored, it is rounded **half up to whole cents**: a fractional remainder of exactly one half cent rounds away from zero, upward. Two rules in this system round more than once, and in both the *order* of the rounding events is part of the specification, not an implementation detail. Early-release loss exposure rounds each contributing line first and then sums the already-rounded lines, and then rounds a second time after the risk-band multiplier is applied; summing raw products first and rounding once at the end is explicitly not the rule and produces a different figure whenever the discarded fractions accumulate past half a cent. The kiting score floors its uncollected-funds ratio to whole basis points and rounds its weighted contribution half up to a whole point. Both are described in full in §3.4 and §3.6 respectively.

Percentages and ratios that are not money are integers too: `confidence_bps` on an association link is a whole number of basis points from 0 through 10,000 inclusive, and `uncollected_ratio_bps` reported by a kiting scan is a whole number of basis points.

### 2.7. Stale-Version Protection on Contested Writes

Two creation endpoints in this system can silently discard work that the caller never saw, because each of them supersedes a predecessor. Both are therefore guarded by optimistic concurrency control against the *parent* resource's `version`.

Opening an early-release review against a check hold requires a non-optional `expected_check_hold_version` field in the request body, carrying the client's last observed `version` of that `CheckHold`. If it does not equal the hold's current `version`, the request is rejected with `ERR_STALE_CHECK_HOLD_VERSION` (HTTP 412) and nothing is created. The reason is that a newly created review supersedes every earlier non-terminal review on the same hold; a writer holding a stale view of the hold would be discarding reviews it has not observed. On success the hold's own `version` advances by 1.

Proposing a charge-off against a deposit account requires a non-optional `expected_account_version` field carrying the client's last observed `version` of that `DepositAccount`. If it does not equal the account's current `version`, the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) and nothing is created. A new proposal supersedes any existing proposed charge-off on the same account, and the loss figure is priced against balances the stale reader has not seen. On success the account's `version` advances by 1.

No other endpoint in this system takes a version field. Absence of `expected_check_hold_version` on a review creation, or of `expected_account_version` on a charge-off proposal, is a missing required field and is therefore `ERR_INVALID_REQUEST`.

### 2.8. Cascade Propagation Across Aggregates

Several operations here mutate more than one resource, and the secondary effects are as much part of the contract as the primary one. Four cascades in particular run more than two hops deep, and each is spelled out where its workflow lives: executing an approved early release (§3.4) walks review to hold to account to fraud case; substantiating a mule case (§3.7) walks case to account to every active hold on that account to every live override review against those holds; settling a deposited item (§3.3) walks item to holds to the depositing account, and on a cleared on-us item also to the drawn-on account; and booking or reversing a charge-off (§3.8) walks charge-off to account balances to account lifecycle.

Two derived aggregates are recomputed rather than stored as drifting counters. An account's `held_amount_cents` is always the live sum of `held_amount_cents` over every `CheckHold` in `ACTIVE` status whose parent deposited item belongs to that account. A fraud case's `exposure_at_risk_cents` is always the sum of `held_amount_cents` over the case's primary account plus every account named in the case's `cycle_account_ids`, deduplicated, and it is recomputed on every operation that changes any of those accounts' held totals.

### 2.9. The Funds Conservation Invariant

Two quantities are conserved on every deposit account, exactly, with zero tolerance.

The first is depositor funds: `available_balance_cents` plus `held_amount_cents` equals `ledger_balance_cents` at all times. This must hold as a postcondition of every operation that touches balances — taking a deposit, settling an item, executing an early release, booking a charge-off, and reversing a charge-off. It follows that a compensating sequence returns the ledger to where it started: taking a deposit, executing an early release against its hold, and then settling that item as returned leaves `ledger_balance_cents` at exactly its pre-deposit value.

The second is the bank's recognised loss position, defined as `ledger_balance_cents` minus `charged_off_amount_cents`. Booking a write-off adds the net loss to the ledger balance and simultaneously records the same figure as charged off, so the net position is unchanged; reversing that booking restores both terms to their pre-booking values, so the net position is again unchanged. `available_balance_cents` is allowed to go negative — a returned item whose hold had already been released early will do exactly that — but `outstanding_loss_cents` on a charge-off is never negative.

### 2.10. Order of Validation

When several checks could fail on the same request, exactly one error is returned, and which one is fully determined by the following ladder. Checks are evaluated in this order and the first failure wins.

1. **Authentication.** Both headers present and `X-User-Role` a declared role, else `ERR_UNAUTHENTICATED`.
2. **Role authorisation.** The caller's role appears in the endpoint's authorised set, else `ERR_FORBIDDEN_ROLE`.
3. **Path existence.** Every `id` appearing in the request path resolves to a stored row, validated left to right, so on a nested path the outer segment is resolved before the inner one. The failure carries the code for the resource kind that failed: `ERR_CUSTOMER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`, `ERR_FUNDING_SOURCE_NOT_FOUND`, `ERR_DEPOSIT_ITEM_NOT_FOUND`, `ERR_CHECK_HOLD_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_FRAUD_CASE_NOT_FOUND`, `ERR_CHARGE_OFF_NOT_FOUND`, `ERR_SUBPOENA_NOT_FOUND`, or `ERR_BSA_REFERRAL_NOT_FOUND` (all HTTP 404).
4. **Body shape.** Every required field present, every value of its declared type, every enumeration value a declared member, every `_cents` field an integer inside its stated range, every timestamp a valid ISO 8601 UTC instant, `release_window_end_at` strictly after `release_effective_at`, `preservation_end_at` strictly after `preservation_start_at`, `response_due_at` strictly after the logical clock at creation time, a `return_reason` present when a settlement outcome is a return, and a `return_reason` present when a referral adjudication is a return. Any failure is `ERR_INVALID_REQUEST` (HTTP 400).
5. **Body reference existence.** Every entity `id` supplied in the request *body* resolves to a stored row — `customer_id` when opening an account, `from_account_id` and `to_account_id` when recording an association link, `drawee_account_id` when taking a deposit, and `primary_account_id` when opening a case manually — failing with `ERR_CUSTOMER_NOT_FOUND` or `ERR_ACCOUNT_NOT_FOUND` (HTTP 404) as appropriate.
6. **Ownership.** When the caller is an `AccountHolder`, `X-User-ID` equals the `customer_id` of the account named in the path, else `ERR_NOT_ACCOUNT_OWNER`. This applies to reading a single deposit account and to answering a step-up challenge.
7. **Stale parent version.** The optimistic-concurrency checks of §2.7, yielding `ERR_STALE_CHECK_HOLD_VERSION` or `ERR_STALE_ACCOUNT_VERSION`.
8. **Uniqueness and structural business constraints,** in this relative order: an association edge may not join an account to itself (`ERR_SELF_LINK`), then no duplicate association edge may already exist (`ERR_DUPLICATE_LINK`), then no duplicate live case may already exist (`ERR_DUPLICATE_OPEN_CASE`).
9. **Entity state gates** — the "is this resource in a state that admits this operation" family, described alongside each workflow in §3 and reported as `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_FUNDING_INVALID_STATE`, `ERR_ITEM_ALREADY_SETTLED`, `ERR_HOLD_NOT_ACTIVE`, `ERR_REVIEW_NOT_SUBMITTED`, `ERR_REVIEW_NOT_APPROVED`, `ERR_CASE_INVALID_STATE`, `ERR_CASE_NOT_SUBSTANTIATED`, `ERR_REFERRAL_INVALID_STATE`, `ERR_CHARGE_OFF_INVALID_STATE`, or `ERR_SUBPOENA_INVALID_STATE`.
10. **Access posture — locked**, evaluated immediately after the state gates: `ERR_ACCOUNT_ACCESS_LOCKED`.
11. **Account closed before booking**, evaluated next: `ERR_ACCOUNT_NOT_CLOSED`.
12. **Access posture — step-up not required**, evaluated strictly after the locked check, so that a locked account answering a challenge reports `ERR_ACCOUNT_ACCESS_LOCKED` and never `ERR_STEP_UP_NOT_REQUIRED`.
13. **Duty separation and preservation holds,** at the same rank: `ERR_SEGREGATION_OF_DUTIES` and `ERR_PRESERVATION_HOLD_ACTIVE`.
14. **Recovery already posted:** `ERR_RECOVERY_ALREADY_POSTED`.
15. **Hold maturity:** `ERR_HOLD_ALREADY_MATURED`.
16. **Window conflicts,** at the same rank: `ERR_RELEASE_WINDOW_OVERLAP` and `ERR_PRESERVATION_WINDOW_CONFLICT`.
17. **Late response justification:** `ERR_LATE_JUSTIFICATION_REQUIRED`.
18. **Referral prerequisite for closure:** `ERR_BSA_REFERRAL_REQUIRED`.
19. **Fiscal limits,** last and at the same rank: `ERR_RELEASE_EXCEEDS_HOLD`, `ERR_EXPOSURE_EXCEEDS_AUTHORITY`, `ERR_NO_NET_LOSS`, and `ERR_RECOVERY_EXCEEDS_LOSS`.

One consequence of this ordering is deliberate and worth stating outright: the state gate for reversing a charge-off admits a charge-off that has already taken recovery postings, precisely so that the recovery guard at rank 14 — not the state gate at rank 9 — is the rule that reports the refusal.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Depositor, Opening an Account, and Scoring the Relationship

Registration of a depositor is an `OperationsAdmin` activity and captures very little: a `legal_name` of 1 to 120 characters that may not be blank, and a `tin_last4` consisting of exactly four ASCII digits — the last four digits of the taxpayer identification number, which later doubles as the shared secret behind step-up verification. Two further inputs are optional. `kyc_tier` records the know-your-customer diligence tier reached at onboarding and takes one of `TIER_1`, `TIER_2`, or `TIER_3`, where `TIER_1` is the most fully documented file and `TIER_3` the least; when the caller omits it, the depositor is recorded at `TIER_2`. `watchlist_hit` is a boolean asserting that onboarding screening returned a sanctions or negative-news hit, and defaults to false when omitted.

Two properties on a depositor are never supplied and never stored as a stale copy. `preservation_hold_active` is true exactly when at least one subpoena request naming this depositor is in `RECEIVED`, `UNDER_LEGAL_REVIEW`, or `PRODUCED` status *and* the logical clock is strictly before that subpoena's `preservation_end_at`; it is recomputed whenever the depositor is read and whenever any subpoena against them is mutated. `open_fraud_case_count` is the number of fraud cases whose primary account belongs to this depositor and whose status is `OPENED` or `INVESTIGATING`. A freshly registered depositor therefore reads back with `preservation_hold_active` false and `open_fraud_case_count` zero.

Opening a deposit account is likewise an `OperationsAdmin` activity, and the payload names the owning depositor through `customer_id`, the `product_type` opened — `CHECKING`, `SAVINGS`, or `MONEY_MARKET` — and the `open_channel` through which the relationship originated, one of `BRANCH`, `ONLINE`, or `MOBILE`. The server stamps `opened_at` from the logical clock; this instant, and not `created_at`, is the baseline for the new-account availability exception described in §3.3. A new account starts with `lifecycle_status` `PENDING_FUNDING` and `access_posture` `NORMAL`, with `ledger_balance_cents`, `available_balance_cents`, `held_amount_cents`, `charged_off_amount_cents`, `ato_score`, and `step_up_failure_count` all zero, `ato_indicator_codes` an empty array, and `closure_scheduled_at` and `closure_reason` both null.

**The two state dimensions.** A deposit account carries two independent state fields on the same row, and they never read or write one another. `lifecycle_status` is the deposit-relationship dimension and moves through `PENDING_FUNDING`, `ACTIVE`, `RESTRICTED`, `CLOSED`, and `CHARGED_OFF`; none of these is terminal, because a restricted account can be reinstated to `ACTIVE` and a charged-off account can be returned to `CLOSED` by a reversal. `access_posture` is the account-takeover dimension and moves among `NORMAL`, `STEP_UP_REQUIRED`, and `LOCKED`. An account may perfectly well be `RESTRICTED` and `NORMAL`, or `ACTIVE` and `LOCKED`; no lifecycle transition ever touches the posture and no posture transition ever touches the lifecycle.

**The new-account risk score.** Every account carries a `risk_score` in the range 0 through 100, a `risk_band` derived from it, and a `risk_score_basis` recording which variant of the scoring rule produced the current figure. The score is assembled additively from five terms.

The first term is the depositor's diligence tier: a `TIER_1` file contributes nothing, `TIER_2` contributes 15 points, and `TIER_3` contributes 35 points. The second is the account's funding posture, determined by inspecting the external funding sources attached to the account: if any of them has reached `VERIFIED`, the posture is verified and contributes nothing; otherwise, if any of them is in `DECLARED`, `MICRO_DEPOSIT_SENT`, or `FAILED_ATTEMPT`, the posture is pending and contributes 20 points; otherwise the posture is none and contributes 30 points. A source that has reached `BLOCKED` is in neither set — it counts as neither verified nor pending, so an account whose only funding source is blocked scores the full 30-point none-posture penalty unless some other source qualifies. The third term is the origination channel: `BRANCH` contributes nothing, `ONLINE` contributes 12 points, `MOBILE` contributes 18 points. The fourth term is a flat 40 points when the depositor's `watchlist_hit` is true, and nothing when it is false. The fifth term is the association-link contribution described below.

The five terms are added, and the sum is then clamped into the range 0 through 100 — no result may fall below zero or exceed 100 — and that clamped value is the stored `risk_score`. The band follows from the score with an inclusive comparison at both edges: a score of 60 or more is `HIGH`, a score of at least 35 but below 60 is `ELEVATED`, and anything below 35 is `STANDARD`.

**Association links and the link term.** A directed association edge between two deposit accounts is recorded by a `FraudAnalyst` or an `OperationsAdmin` and names a `from_account_id` at the tail, a `to_account_id` at the head, a `link_type` drawn from `SHARED_DEVICE`, `SHARED_ADDRESS`, `SHARED_PHONE`, and `TRANSFER_COUNTERPARTY`, and a detection `confidence_bps` expressed in basis points from 0 through 10,000 inclusive. The server derives `is_risk_bearing`, which is true exactly when the `link_type` is one of `SHARED_DEVICE`, `SHARED_ADDRESS`, or `SHARED_PHONE` **and** `confidence_bps` is at least 6,000 — that is, a detection confidence of 60 percent or better on an identity-sharing signal. A `TRANSFER_COUNTERPARTY` edge is never risk-bearing no matter how confident the detection.

The link term of the risk score counts every association edge that names the account being scored at *either* end — tail or head, in both directions — and that satisfies the same two conditions that make an edge risk-bearing. Each such edge contributes 5 points, and the total link contribution is capped at 25 points, so a sixth risk-bearing edge adds nothing. Association edges have no lifecycle of their own and are therefore counted with no status filter.

Two structural rules guard edge creation. An account may not be linked to itself: if `from_account_id` equals `to_account_id`, the request is refused with `ERR_SELF_LINK` (HTTP 422). And the same triple of tail, head, and `link_type` may exist only once; a repeat is refused with `ERR_DUPLICATE_LINK` (HTTP 409). Note that the pair is directional and the type discriminates, so an edge from A to B of type `SHARED_DEVICE`, an edge from B to A of type `SHARED_DEVICE`, and an edge from A to B of type `SHARED_PHONE` are three distinct, all-permitted rows.

**Provisional versus refreshed scoring.** The score is computed under one of two variants, and the difference is which inputs are read live. The `PROVISIONAL_AT_OPEN` variant runs inside account opening, before any funding source or association edge can possibly exist for the new account; it *forces* the funding posture to none — the full 30 points — and *forces* the risk-bearing link count to zero, regardless of what a later read would find, and it writes `risk_score_basis` as `PROVISIONAL_AT_OPEN`. The `REFRESHED` variant reads funding posture and risk-bearing link count from live rows and writes `risk_score_basis` as `REFRESHED`. It is re-evaluated for the affected account whenever a funding source is declared, whenever a verification attempt is submitted, whenever trial deposits are re-sent, and whenever an access review is recorded; and when an association edge is created it is re-evaluated for **both** endpoint accounts, rewriting `risk_score`, `risk_band`, and `risk_score_basis` on each of them. The practical consequence is that the same depositor and the same `open_channel` yield a strictly lower score once funding verifies, because the 30-point none-posture term drops away, and a strictly higher score once risk-bearing edges appear, at 5 points each up to the 25-point cap.

Reading a single deposit account returns both state dimensions, the live balances, and the current risk and takeover scores, with `held_amount_cents` recomputed from the account's `ACTIVE` holds for the response. Accounts owned by a depositor, association edges touching an account, funding sources on an account, deposits taken into an account, cases opened against an account, and charge-offs proposed against an account are each reachable through their own listing.

### 3.2. Verifying the Funding Source and Activating the Account

A newly opened account cannot take deposits: it sits in `PENDING_FUNDING` until an external funding source proves ownership by trial deposit. Declaring a funding source is an `OperationsAdmin` activity against a specific account, and the payload carries only a `source_type` — one of `EXTERNAL_ACH`, `WIRE`, or `CARD_PUSH` — and a `routing_last4` of exactly four ASCII digits. The account being funded is recorded on the row as `account_id`.

The row is born in `DECLARED` status with `attempt_count` and `total_attempt_count` both at 0 and `verified_at` null, but `DECLARED` is never observable through the API: within the same request the server mints `micro_deposit_cents`, an integer from 1 through 99 inclusive, and advances `verification_status` to `MICRO_DEPOSIT_SENT`. The minted amount is returned in the creation response and on subsequent reads of the source so that a client can complete verification; it is a credential to be echoed back, never an input to any business decision. Declaring the source also re-evaluates the account's risk under the `REFRESHED` variant, because the funding posture has just moved from none to pending, dropping the score by 10 points.

Verification is attempted by submitting a `micro_deposit_cents` value, which must be an integer from 0 through 99,999 — a deliberately wider band than the minted range, so that an out-of-range guess is a business mismatch rather than a malformed request, and note that 0 can never match a minted amount. Every attempt, matching or not, increments both `attempt_count` and `total_attempt_count` by 1. The two counters differ in what they survive: `attempt_count` counts attempts against the *currently* minted secret and is reset by a re-send, while `total_attempt_count` is the lifetime budget across all re-sends and is never reset.

A **matching** submission moves `verification_status` to `VERIFIED` and stamps `verified_at` from the logical clock, whether the source was in `MICRO_DEPOSIT_SENT` or in `FAILED_ATTEMPT` when the correct value finally arrived. Because a source has reached `VERIFIED`, the owning account transitions `PENDING_FUNDING → ACTIVE` — this transition fires only when the account is actually in `PENDING_FUNDING`, so a second source verifying later on an already-active account changes nothing about the lifecycle. Because the account has left `PENDING_FUNDING`, the risk score is re-evaluated under the `REFRESHED` variant and `risk_score`, `risk_band`, and `risk_score_basis` are rewritten; the funding posture is now verified, so a further 20 points fall away. The account's `version` advances by 1 and its `updated_at` is refreshed.

A **mismatched** submission is a state transition, not an error: it returns HTTP 200 with the updated funding source. If the lifetime budget still has room — that is, if the incremented `total_attempt_count` remains strictly below five — the status becomes `FAILED_ATTEMPT`, and a further mismatch from `FAILED_ATTEMPT` simply leaves it in `FAILED_ATTEMPT` with the counters advanced again. If instead the incremented `total_attempt_count` reaches five, the status becomes `BLOCKED`: the account stays in `PENDING_FUNDING`, and no further attempt and no re-send is ever accepted on that source.

Re-sending trial deposits is permitted only from `FAILED_ATTEMPT`, and only while `total_attempt_count` is still below the lifetime budget of five. A re-send mints a fresh `micro_deposit_cents` in the same 1-through-99 range, resets `attempt_count` to 0, leaves `total_attempt_count` untouched, and returns the status to `MICRO_DEPOSIT_SENT` — closing the retry loop `MICRO_DEPOSIT_SENT → FAILED_ATTEMPT → MICRO_DEPOSIT_SENT`. It also re-evaluates the account's risk under the `REFRESHED` variant.

Both funding operations share one state gate, reported as `ERR_FUNDING_INVALID_STATE` (HTTP 409). A verification attempt requires the source to be in `MICRO_DEPOSIT_SENT` or `FAILED_ATTEMPT`, so an attempt against a source that is `VERIFIED`, `BLOCKED`, or still nominally `DECLARED` is refused. A re-send requires the source to be in `FAILED_ATTEMPT` *and* its `total_attempt_count` to be below five, so a re-send against a `MICRO_DEPOSIT_SENT` source, or against a source whose budget is exhausted, is refused with the same code.

### 3.3. Taking Deposits, Pricing Availability, and Posting Collection Outcomes

Deposits are taken by an `OperationsAdmin` into a named account. The payload carries the `item_type` — `CHECK`, `ACH`, or `CASH` — an `amount_cents` face amount that must be an integer of at least 1, and, for an on-us check, an optional `drawee_account_id` naming the account the item is drawn on. A null or absent `drawee_account_id` marks the item as off-us; a non-null one must resolve to a stored account and creates a directed circulation edge from the drawn-on account to the depositing account, which is the edge the kiting detector traverses in §3.6. The server stamps `deposit_at` from the logical clock and records the item with `status` `PENDING`, `settled_at` null, and `return_reason` null.

Two gates guard the intake. The account named in the path must have `lifecycle_status` exactly `ACTIVE`, so a deposit into an account that is still `PENDING_FUNDING`, or that has been driven to `RESTRICTED`, `CLOSED`, or `CHARGED_OFF`, is refused with `ERR_ACCOUNT_NOT_ACTIVE` (HTTP 409). Immediately after that, the account's `access_posture` must not be `LOCKED`; a deposit into a locked account is refused with `ERR_ACCOUNT_ACCESS_LOCKED` (HTTP 409).

**The availability ladder.** Availability is priced immediately after the item row is written and before any balance is posted. Cash is special-cased first: a `CASH` item makes its whole `amount_cents` available at once, so `immediate_credit_cents` equals `amount_cents`, `held_cents` is zero, and no hold row is created at all. For every other instrument, `immediate_credit_cents` is the smaller of `amount_cents` and 22,500 cents — the first $225.00 of any deposited item is always released at once — and `held_cents` is `amount_cents` less that immediate credit. When `held_cents` works out to zero, again no hold row is created.

When `held_cents` is greater than zero, a hold is minted in `ACTIVE` status with its `held_amount_cents` set to the item's `held_cents`, its `hold_start_at` equal to the item's `deposit_at`, and its `deposit_item_id` naming the parent item. Its `hold_type` is chosen by a strictly top-to-bottom ladder, and the order of the tests is part of the specification because more than one branch can be true at once:

1. An `ACH` item is always `STANDARD`, whatever the account's age, the amount, or the risk band. This short-circuit is tested first.
2. Otherwise, if the account's age in whole days is *less than* 30, the hold is `EXCEPTION_NEW_ACCOUNT`. Age is computed by taking the elapsed time from the account's `opened_at` to the logical clock and flooring it to whole calendar days in UTC. The comparison is strict: an account that is exactly 30 days old is no longer new.
3. Otherwise, if `amount_cents` is *strictly greater than* 552,500 cents — that is, more than $5,525.00 — the hold is `EXCEPTION_LARGE_DEPOSIT`. This edge is strict too: an item of exactly 552,500 cents is not large.
4. Otherwise, if the account's `risk_band` is `HIGH`, the hold is `EXCEPTION_RISK`.
5. Otherwise the hold is `STANDARD`.

Because the ladder is ordered, a nine-day hold on a young account wins over the seven-day hold the same item would have attracted on a mature one. The `hold_release_at` is the item's `deposit_at` advanced by the number of calendar days the chosen class carries: two days for `STANDARD`, five for `EXCEPTION_RISK`, seven for `EXCEPTION_LARGE_DEPOSIT`, and nine for `EXCEPTION_NEW_ACCOUNT`. A fifth class, `EXCEPTION_FRAUD`, carries zero days and is never selected by this ladder — it is written only by the mule-substantiation cascade in §3.7, which also overwrites `hold_release_at` with the account's scheduled closure instant. Reaching `hold_release_at` does not transition the hold by itself; maturity only closes the window in which an early release may be requested.

**Posting the deposit.** Balances move in a fixed order once availability is priced: the full `amount_cents` is added to the account's `ledger_balance_cents`, the `immediate_credit_cents` is added to `available_balance_cents`, and `held_amount_cents` is then recomputed as the live sum over the account's `ACTIVE` holds. Because that held total changed, every fraud case in `OPENED` or `INVESTIGATING` status whose primary account is this account, or whose `cycle_account_ids` contains it, has its `exposure_at_risk_cents` recomputed.

**Settlement.** An `OperationsAdmin` posts the collection outcome by supplying an `outcome` of either `CLEARED` or `RETURNED`, together with a `return_reason` — one of `NSF`, `ACCOUNT_CLOSED`, `UNCOLLECTED_FUNDS`, or `STOP_PAYMENT` — which is mandatory on a return and rejected as a malformed body when missing. The item must be in `PENDING`; a second settlement of the same item is refused with `ERR_ITEM_ALREADY_SETTLED` (HTTP 409). Either outcome stamps `settled_at` from the logical clock, and both are terminal for the item.

A **cleared** item transitions `PENDING → CLEARED`. Every hold on that item still in `ACTIVE` transitions `ACTIVE → RELEASED` with `released_at` stamped. Because those holds left `ACTIVE`, the depositing account's `available_balance_cents` rises by the total `held_amount_cents` just released and its `held_amount_cents` is recomputed; `ledger_balance_cents` is unchanged, because the money was already on the ledger. If the item named a `drawee_account_id`, the drawn-on account now pays: both its `ledger_balance_cents` and its `available_balance_cents` fall by the item's `amount_cents`.

A **returned** item transitions `PENDING → RETURNED` and records its `return_reason`. Every hold on that item still in `ACTIVE` transitions `ACTIVE → CHARGED_BACK` with `released_at` stamped. The depositing account's `ledger_balance_cents` falls by the item's `amount_cents`, and its `available_balance_cents` falls by the item's `amount_cents` less the total `held_amount_cents` of the holds just charged back — which is exactly the portion the depositor could already spend, and which may drive `available_balance_cents` negative when an early release has already been executed against that hold. The drawn-on account, if any, is **not** adjusted on a return: an item that comes back was never paid.

After either outcome, every fraud case in `OPENED` or `INVESTIGATING` status covering any affected account has its `exposure_at_risk_cents` recomputed.

One detail of the deposit listing on an account is worth stating plainly: an item is returned there when *either* its `account_id` or its `drawee_account_id` names that account, so the drawn-on side of an on-us check is discoverable from the drawee's own listing. The `account_role` filter narrows that listing to one side or the other.

### 3.4. Releasing Held Funds Early: Review, Decision, and Execution

Depositors ask for their money before it matures, and branch staff ask on their behalf. The unit answers with a reviewed, priced, dual-controlled release. An early-release review is raised against one specific check hold by a `FraudAnalyst` or a `FraudSupervisor`, and it claims a window of time on the *account* during which that release is in play.

The creation payload names `requested_release_cents`, an integer of at least 1; a half-open release window bounded by `release_effective_at` inclusive and `release_window_end_at` exclusive, where the end must be strictly after the start; a `justification` of 1 to 500 non-blank characters recorded for audit; and the `expected_check_hold_version` demanded by §2.7. The server records `prepared_by_user_id` from `X-User-ID`, sets `status` to `DRAFT`, leaves `decided_by_user_id`, `decision_note`, `submitted_at`, `decided_at`, and `executed_at` null, sets `revision_count` to 0, and stores the hold's identity as `check_hold_id`.

Four business rules guard creation, and they are evaluated in the ladder order of §2.10. The hold must be in `ACTIVE` status, else `ERR_HOLD_NOT_ACTIVE` (HTTP 409). The logical clock must be strictly before the hold's `hold_release_at`, because a matured hold no longer admits an override; a request at or past that instant is refused with `ERR_HOLD_ALREADY_MATURED` (HTTP 422). The claimed window must not overlap the window of any other review on the **same deposit account** whose status is `DRAFT`, `SUBMITTED`, `RETURNED_FOR_INFO`, `APPROVED`, or `EXECUTED`; an overlap is `ERR_RELEASE_WINDOW_OVERLAP` (HTTP 409). Because the windows are half-open, touching endpoints do not overlap: an existing window ending at an instant and a new window starting at exactly that instant are both accepted. Finally, `requested_release_cents` must be less than or equal to the hold's current `held_amount_cents`, else `ERR_RELEASE_EXCEEDS_HOLD` (HTTP 422).

On success, every *other* review against the same hold whose status is `DRAFT`, `SUBMITTED`, `RETURNED_FOR_INFO`, or `APPROVED` is moved to `SUPERSEDED` — including one already approved but not yet executed, which can consequently never be executed — while their `decided_by_user_id` and `decision_note` are left exactly as they were. The hold's own `version` advances by 1.

**Pricing the exposure.** Both at creation and again on every submission, the review is priced by a two-stage aggregation whose rounding order is pinned. The scope is every check hold in `ACTIVE` status that belongs to the **same deposit account** as the review's hold — not merely the one hold under review — walked in the holds' `created_at` ascending order, ties broken by the parent deposited item's `created_at` ascending. Holds in `RELEASED`, `OVERRIDDEN`, or `CHARGED_BACK` are outside the scope entirely.

For each hold in scope, the return-risk of that line is its current `held_amount_cents` multiplied by the return rate for the parent item's instrument and divided by 10,000, and that line figure is **rounded half up to whole cents immediately**. The return rates are 275 basis points for a `CHECK`, 120 basis points for an `ACH`, and 0 basis points for `CASH`. `loss_exposure_cents` is then the sum of the already-rounded lines. Rounding once at the end over a raw sum is explicitly not the rule and gives a different answer whenever the discarded fractions add past half a cent.

`adjusted_exposure_cents` is `loss_exposure_cents` multiplied by the account's risk-band multiplier, divided by 10,000, and rounded half up to whole cents a second time. The multipliers are 10,000 basis points for a `STANDARD` band — that is, no adjustment — 12,500 basis points for `ELEVATED`, and 16,000 basis points for `HIGH`. It is `adjusted_exposure_cents`, and never `loss_exposure_cents`, that is compared against a supervisor's authority.

**Submission.** A review in `DRAFT` or in `RETURNED_FOR_INFO` is sent to the supervisor queue by a `FraudAnalyst` or a `FraudSupervisor`; both edges land in `SUBMITTED` and stamp `submitted_at` from the logical clock, and the edge out of `RETURNED_FOR_INFO` additionally increments `revision_count` by 1, closing the revision loop `SUBMITTED → RETURNED_FOR_INFO → SUBMITTED`. Either way the exposure figures are recomputed against the account's `ACTIVE` holds as they stand at that moment, so a hold that has been released or charged back in the meantime silently drops out of the total. A submit attempted from any other status is refused with `ERR_REVIEW_NOT_SUBMITTED` (HTTP 409), and a submit whose underlying hold is no longer `ACTIVE` is refused with `ERR_HOLD_NOT_ACTIVE`.

**Decision.** Only a `FraudSupervisor` records a decision, and only against a review in `SUBMITTED` — anything else is `ERR_REVIEW_NOT_SUBMITTED`. The underlying hold must still be `ACTIVE`. The deciding supervisor's `X-User-ID` must differ from the review's `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; this is the rule that bites inside a single role, because a supervisor is perfectly entitled to prepare a review and simply may not then decide their own. The payload carries a `decision` of `APPROVE`, `DENY`, or `RETURN_FOR_INFO`, and an optional `decision_note`. `APPROVE` moves the review to `APPROVED`, `DENY` to `DENIED`, and `RETURN_FOR_INFO` back to `RETURNED_FOR_INFO`; all three stamp `decided_by_user_id` from `X-User-ID`, `decided_at` from the logical clock, and the supplied `decision_note`. An approval carries one extra fiscal gate: `adjusted_exposure_cents` must be less than or equal to 500,000 cents — a supervisor's authority runs to $5,000.00 of adjusted exposure — and an approval above it is refused with `ERR_EXPOSURE_EXCEEDS_AUTHORITY` (HTTP 422). Denials and returns are not subject to that limit.

**Execution and its four-hop cascade.** A `FraudSupervisor` executes an approved release. The review must be in `APPROVED`, else `ERR_REVIEW_NOT_APPROVED` (HTTP 409); the hold must still be `ACTIVE`, else `ERR_HOLD_NOT_ACTIVE`; `requested_release_cents` must still be no greater than the hold's current `held_amount_cents`, else `ERR_RELEASE_EXCEEDS_HOLD`; and `adjusted_exposure_cents` must still be within the 500,000-cent authority, else `ERR_EXPOSURE_EXCEEDS_AUTHORITY`. The cascade then runs four hops, and every hop is observable:

- **Hop 1.** The review transitions `APPROVED → EXECUTED` and `executed_at` is stamped from the logical clock.
- **Hop 2.** Because the review executed, the referenced hold's `held_amount_cents` is reduced by `requested_release_cents`. If that reduction brings it to exactly 0, the hold transitions `ACTIVE → OVERRIDDEN` with `released_at` stamped. If the requested amount was strictly less than the hold's balance, the hold stays `ACTIVE` with a smaller `held_amount_cents`, and its `hold_type` and `hold_release_at` are left untouched.
- **Hop 3.** Because that hold's `held_amount_cents` changed, the owning account's `available_balance_cents` rises by `requested_release_cents` and its `held_amount_cents` is recomputed. `ledger_balance_cents` is unchanged — early release moves money between the held and available buckets, it does not create any.
- **Hop 4.** Because the account's held total changed, every fraud case in `OPENED` or `INVESTIGATING` status whose primary account is this account, or whose `cycle_account_ids` contains it, has `exposure_at_risk_cents` recomputed.

`version` advances by 1 on the review, on the hold, on the account, and on every fraud case whose exposure was recomputed.

### 3.5. Account-Takeover Indicators and Step-Up Verification

The second state dimension on a deposit account answers a different question from the first: not "is this relationship sound?" but "is the person operating this account still the depositor?" Indicators arrive from monitoring, are accumulated on the account, and drive the `access_posture` between `NORMAL`, `STEP_UP_REQUIRED`, and `LOCKED`.

An access review is recorded by a `FraudAnalyst` or a `FraudSupervisor` and carries `indicator_codes`, an array whose members are drawn from `NEW_DEVICE`, `GEO_VELOCITY`, `CREDENTIAL_STUFFING`, `PROFILE_CHANGE`, `DORMANT_REACTIVATION`, and `PAYEE_ADDED`, plus an optional boolean `reset_posture`. The submitted codes are merged into the account's `ato_indicator_codes`, which is maintained as a distinct set stored sorted ascending by code string. Submitting a code that is already present adds no second entry and, crucially, adds no weight — the score is a function of the distinct set, not of how many times a code was reported.

`ato_score` is the sum of the weights of the distinct codes currently stored, capped at 100. `NEW_DEVICE` weighs 15, `GEO_VELOCITY` 25, `CREDENTIAL_STUFFING` 30, `PROFILE_CHANGE` 20, `DORMANT_REACTIVATION` 18, and `PAYEE_ADDED` 12. Once the score is rewritten, the posture ladder is applied, with inclusive comparisons at both edges and one override on top:

- A supervisor reset wins over everything. When `reset_posture` is true and the account is currently `LOCKED`, the posture becomes `STEP_UP_REQUIRED` and `step_up_failure_count` is reset to 0, regardless of what the recomputed `ato_score` says. This override is honoured only for `FraudSupervisor`; from a `FraudAnalyst` it has no effect. Any submitted `indicator_codes` are still merged and the score still rewritten.
- Otherwise, an `ato_score` of 75 or more sets the posture to `LOCKED`. From `NORMAL` this is the transition `NORMAL → LOCKED`; from `STEP_UP_REQUIRED` it is `STEP_UP_REQUIRED → LOCKED`.
- Otherwise, an `ato_score` of at least 40 but below 75 sets the posture to `STEP_UP_REQUIRED`, which from `NORMAL` is the transition `NORMAL → STEP_UP_REQUIRED`.
- Otherwise the posture is left exactly as it was. The score ladder never de-escalates a posture on its own; only a successful step-up answer or a supervisor reset moves a posture down.

Every access review also re-evaluates the account's `risk_score`, `risk_band`, and `risk_score_basis` under the `REFRESHED` variant, and advances the account's `version` by 1 with `updated_at` refreshed.

**Answering the challenge.** Only the `AccountHolder` may answer, and only for their own account: `X-User-ID` must equal the account's `customer_id`, else `ERR_NOT_ACCOUNT_OWNER`. The correct `challenge_answer` is the owning depositor's `tin_last4`. Two posture gates apply in a fixed order — the locked check first, the step-up check second. An account whose `access_posture` is `LOCKED` is refused with `ERR_ACCOUNT_ACCESS_LOCKED` (HTTP 409); only then, an account whose posture is neither `LOCKED` nor `STEP_UP_REQUIRED` is refused with `ERR_STEP_UP_NOT_REQUIRED` (HTTP 409). Because of that ordering a locked account always reports the locked code and never the not-required one.

A **correct** answer transitions `STEP_UP_REQUIRED → NORMAL`, sets `step_up_failure_count` back to 0, clears `ato_indicator_codes` to the empty array, and rewrites `ato_score` to 0 — the account starts its indicator history over.

An **incorrect** answer increments `step_up_failure_count` by 1 first, and then looks at the result. If the incremented count reaches three, the account transitions `STEP_UP_REQUIRED → LOCKED`. If it is still below three, the posture stays `STEP_UP_REQUIRED` on a self-loop and only the counter has moved. Either way the account's `version` advances by 1. A locked account can be lifted back to `STEP_UP_REQUIRED` only by the supervisor reset described above, which is the transition `LOCKED → STEP_UP_REQUIRED`.

### 3.6. Detecting Kiting Across the On-Us Circulation Graph

Kiting shows up as circulation: account A deposits a check drawn on B, B deposits a check drawn on C, C deposits a check drawn on A, and every one of them is spending float that has not settled. A `FraudAnalyst` looks for exactly that shape by scanning outward from one account over a bounded time window.

The scan request names a `mode` of either `STRICT` or `INCLUSIVE` and a half-open window bounded by `window_start_at` inclusive and `window_end_at` exclusive. The scanned account must have `lifecycle_status` of either `ACTIVE` or `RESTRICTED`; a scan on an account outside that pair is refused with `ERR_ACCOUNT_NOT_ACTIVE`.

**Building the graph.** Only deposited items qualify as edges, and only those whose `item_type` is `CHECK`, whose `drawee_account_id` is not null, whose `deposit_at` falls at or after `window_start_at` and strictly before `window_end_at`, and whose `status` is in the mode's qualifying set. Each such item is a directed edge running from its drawn-on account to its depositing account — the direction in which value circulates. The qualifying-status set is the *entire* difference between the two modes: `STRICT` admits only items still in `PENDING`, the same-day float view; `INCLUSIVE` admits items in `PENDING`, `CLEARED`, and `RETURNED` alike, the historical-pattern view used for case building. On identical data the two modes produce different scores and can land on opposite sides of the detection threshold.

**Choosing the cycle.** The detector looks for directed cycles in that edge set which pass through the scanned account and contain at most four distinct accounts. If there are none, `cycle_length` is 0 and `cycle_account_ids` is empty. Otherwise it takes the cycles with the fewest distinct accounts; among those of equal length it breaks the tie by listing each candidate cycle's member accounts' `created_at` values in ascending order and choosing the candidate whose list is lexicographically smallest — account `id` values are never consulted for this. The chosen cycle is reported as `cycle_account_ids`, rotated so that it starts at the scanned account and then follows the directed edges, and `cycle_length` is its number of distinct accounts.

**Scoring.** `qualifying_item_count` is the number of qualifying items whose drawn-on-to-depositing pair is an edge of the chosen cycle, and `deposited_cents` is the sum of `amount_cents` over exactly those items; both are 0 when no cycle was found. `uncollected_cents` is the sum of `held_amount_cents` over every check hold in `ACTIVE` status whose parent item belongs to any account in `cycle_account_ids`, and it is taken from `ACTIVE` holds regardless of mode — so a cleared item drops out of `deposited_cents` *and* takes its hold out of `uncollected_cents` under `STRICT`, but under `INCLUSIVE` it stays in `deposited_cents` while its hold still drops out. `uncollected_ratio_bps` is 0 when `deposited_cents` is 0; otherwise it is `uncollected_cents` multiplied by 10,000, divided by `deposited_cents`, and floored to whole basis points.

The raw score adds three terms. The first is a base for the cycle's size: 40 points for a two-account cycle, 55 for a three-account cycle, 60 for a four-account cycle, and nothing at all when no cycle was found. The second is a velocity term of 6 points for each qualifying item on the chosen cycle. The third is an uncollected-funds term equal to 30 multiplied by `uncollected_ratio_bps`, divided by 10,000, and rounded half up to a whole point — so a fully uncollected cycle contributes the full 30 points and a half-uncollected one contributes 15. `kiting_score` is the raw total capped at 100, and `detected` is true exactly when `kiting_score` is 70 or more.

**What a detection does.** The scan always returns every intermediate figure — `kiting_score`, `cycle_length`, `cycle_account_ids`, `qualifying_item_count`, `deposited_cents`, `uncollected_cents`, `uncollected_ratio_bps`, `detected`, and `fraud_case_id` — so the analyst can see the arithmetic. When `detected` is false, nothing else happens: no case is created, no account is transitioned, and `fraud_case_id` comes back null. When `detected` is true, the server opens a fraud case with `case_type` `KITING`, `detection_source` `KITING_SCAN`, and `status` `OPENED`, copying the scan's `kiting_score`, the requested mode into `scan_mode`, and the chosen `cycle_account_ids` onto the case, and returns the new case's identifier as `fraud_case_id`. The scanned account then transitions `ACTIVE → RESTRICTED`; an account already `RESTRICTED` simply stays `RESTRICTED`, with no error. Duplicate suppression applies only on detection: when `detected` is true and a `KITING` case on this account already has status `OPENED`, `INVESTIGATING`, or `SUBSTANTIATED`, the whole scan is refused with `ERR_DUPLICATE_OPEN_CASE` (HTTP 409).

### 3.7. Working a Fraud Case: Investigation, Disposition Cascades, Referral, and Closure

A case is the unit of investigative work, and it can be born two ways. A kiting scan cascades one open, as described in §3.6. Alternatively a `FraudAnalyst` opens one directly, naming a `primary_account_id` and a `case_type` of either `KITING` or `MULE` — mule cases are always opened this way, since nothing detects them automatically. A manually opened case is recorded with `status` `OPENED` and `detection_source` `ANALYST_MANUAL`, its `kiting_score` and `scan_mode` stay null, and its `cycle_account_ids` stays empty. Its `exposure_at_risk_cents` is computed at once from the primary account's `held_amount_cents`, and the primary account transitions `ACTIVE → RESTRICTED`.

The account must be in `ACTIVE` or `RESTRICTED` to carry a new case; anything else is `ERR_ACCOUNT_NOT_ACTIVE`. Duplicate suppression is by type: no second case of the same `case_type` may be opened against the same account while an existing one is `OPENED`, `INVESTIGATING`, or `SUBSTANTIATED`, and an attempt is refused with `ERR_DUPLICATE_OPEN_CASE`. A `MULE` case and a `KITING` case may therefore be live on the same account simultaneously. When a second case opens on an account already in `RESTRICTED`, the account stays `RESTRICTED` with no error and with no version bump beyond the one the case opening itself performs.

Every operation on a case checks that the case is in the state that operation expects, and all such failures report `ERR_CASE_INVALID_STATE` (HTTP 409): advancing requires `OPENED`; a disposition of `SUBSTANTIATE` or `UNSUBSTANTIATE` requires `INVESTIGATING`; a disposition of `REOPEN` requires `UNSUBSTANTIATED`; and closing requires `SUBSTANTIATED` or `UNSUBSTANTIATED`.

**Advancing.** A `FraudAnalyst` moves a newly opened case into active investigation, the transition `OPENED → INVESTIGATING`, which also recomputes `exposure_at_risk_cents`.

**Disposition.** Only a `FraudSupervisor` disposes a case, supplying a `decision` of `SUBSTANTIATE`, `UNSUBSTANTIATE`, or `REOPEN` and an optional `disposition_note`. The three branches differ sharply, and the substantiation branch differs again by case type.

`SUBSTANTIATE` moves the case `INVESTIGATING → SUBSTANTIATED` and records `disposition_note`. For a `MULE` case the cascade then runs three further hops. The primary account is forced to `lifecycle_status` `RESTRICTED`; its `closure_scheduled_at` is set to the logical clock advanced by ten calendar days — the statutory notice period the depositor gets before the relationship is shut — and its `closure_reason` is set to `MULE_SUBSTANTIATED`. Because the account has acquired a scheduled closure, every check hold in `ACTIVE` status on that account's deposited items has its `hold_type` rewritten to `EXCEPTION_FRAUD` and its `hold_release_at` rewritten to that same `closure_scheduled_at`, while its `held_amount_cents` is left untouched — the funds stay held until the account closes. And because those holds were retyped, every early-release review against them whose status is `DRAFT`, `SUBMITTED`, `RETURNED_FOR_INFO`, or `APPROVED` is moved to `SUPERSEDED`, so no pending or approved release survives a mule substantiation. For a `KITING` case the cascade is deliberately narrower: the case becomes `SUBSTANTIATED` and the primary account is forced to `RESTRICTED`, and that is all — `closure_scheduled_at`, `closure_reason`, hold types, and override reviews are all left exactly as they were. `version` advances by 1 on the case and on every entity the branch actually mutated, and on nothing else.

`UNSUBSTANTIATE` moves the case `INVESTIGATING → UNSUBSTANTIATED` and records `disposition_note`. Because the case has been cleared, the primary account is reinstated `RESTRICTED → ACTIVE` with `closure_scheduled_at` and `closure_reason` cleared to null — but only when no *other* case on that account is in `OPENED`, `INVESTIGATING`, or `SUBSTANTIATED`. A second live case keeps the account restricted.

`REOPEN` moves the case `UNSUBSTANTIATED → INVESTIGATING`, increments `reopen_count` by 1, and, because the case is live again, drives the primary account `ACTIVE → RESTRICTED`. This closes the investigation loop `INVESTIGATING → UNSUBSTANTIATED → INVESTIGATING`.

**The referral gate.** A substantiated case cannot be closed until the Bank Secrecy Act unit has accepted a suspicious-activity referral drawn from it. A `FraudAnalyst` drafts the referral against a case whose `status` is `SUBSTANTIATED` — against any other status the draft is refused with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409) — supplying a `narrative` of 1 to 2,000 non-blank characters and a `suspected_activity_code` of `KITING`, `MULE_ACTIVITY`, `STRUCTURING`, or `ACCOUNT_TAKEOVER`. The referral is created in `DRAFT` with `drafted_by_user_id` taken from `X-User-ID`, `aggregate_amount_cents` 0, `revision_count` 0, and `adjudicated_by_user_id`, `return_reason`, `submitted_at`, and `adjudicated_at` all null. The case it belongs to is recorded as `fraud_case_id`.

Filing the referral is also a `FraudAnalyst` action and is permitted from `DRAFT` or from `RETURNED`; from any other status it is `ERR_REFERRAL_INVALID_STATE` (HTTP 409), and if the parent case is no longer `SUBSTANTIATED` it is `ERR_CASE_NOT_SUBSTANTIATED`. Both edges land in `SUBMITTED` and stamp `submitted_at`; the edge out of `RETURNED` additionally increments `revision_count` by 1, closing the loop `SUBMITTED → RETURNED → SUBMITTED`. Filing freezes `aggregate_amount_cents` onto the referral: it is the sum of `amount_cents` over every deposited item whose account is the case's primary account or appears in the case's `cycle_account_ids` — the account set deduplicated — and whose `status` is `PENDING` or `RETURNED`. Cleared items are excluded, on the reasoning that money which actually collected is not suspicious volume. The figure is captured at that instant and is not recomputed on adjudication, when a different referral is filed, or when any item settles later; only re-filing *this* referral re-freezes it.

A `BsaOfficer` adjudicates a filed referral, and only one in `SUBMITTED` — anything else is `ERR_REFERRAL_INVALID_STATE`. The payload carries a `decision` of `ACCEPT` or `RETURN`, and `RETURN` additionally requires a `return_reason`, whose absence is a malformed body. `ACCEPT` moves the referral `SUBMITTED → ACCEPTED`, stamping `adjudicated_by_user_id` and `adjudicated_at`, and makes the parent case eligible for closure. `RETURN` moves it `SUBMITTED → RETURNED` with the `return_reason` recorded, and the analyst may revise and re-file.

**Closure.** A `FraudSupervisor` closes a disposed case. Two gates apply beyond the state check. The owning depositor's `preservation_hold_active` must be false, else `ERR_PRESERVATION_HOLD_ACTIVE` (HTTP 409) — records under a live law-enforcement preservation obligation are not shut away. And when the case's status immediately before the call is `SUBSTANTIATED`, at least one referral drawn from it must be in `ACCEPTED`, else `ERR_BSA_REFERRAL_REQUIRED` (HTTP 409). No referral is required to close an unsubstantiated case.

Closure sets `status` to `CLOSED` and stamps `closed_at`. From `SUBSTANTIATED`, the closure runs the account-closure procedure: the primary account transitions `RESTRICTED → CLOSED` with `closure_reason` set to `MULE_SUBSTANTIATED` when the case's `case_type` is `MULE` and to `KITING_SUBSTANTIATED` when it is `KITING`. Those are the only two values that field ever takes, and the case-close cascade is the only writer of them. From `UNSUBSTANTIATED`, no account transition occurs at all — the account keeps whatever `lifecycle_status` the unsubstantiating disposition already produced.

### 3.8. Charging Off the Loss, Referring It to Recovery, and Unwinding a Mistake

When a closed account leaves the bank holding uncollected funds, the loss is priced, approved, booked against the ledger, and — above a threshold — handed to a recovery agency. A `FraudAnalyst` proposes the write-off against the account, supplying a `gross_loss_cents` of at least 1, an optional `collateral_offset_cents` of at least 0 that defaults to 0 and represents cents already recovered from pledged collateral or a sibling account, and the `expected_account_version` demanded by §2.7. Neither figure is derived from the account's balances; both are asserted by the proposer. Creating a proposal moves any existing charge-off on the same account whose `status` is `PROPOSED` to `SUPERSEDED`, and advances the account's `version` by 1.

**Pricing, once and only once.** The fee depends on the amount and the amount depends on the fee, so the evaluation order is pinned and the stored figures are never re-priced afterwards. First, `base_net_cents` is `gross_loss_cents` less `collateral_offset_cents`; if that is zero or negative there is nothing to write off and the proposal is refused with `ERR_NO_NET_LOSS` (HTTP 422). Second, the recovery-agency fee rate is selected **from `base_net_cents`, never from the final figure**, against two inclusive upper bounds: a `base_net_cents` of 100,000 cents or less takes 500 basis points, a `base_net_cents` above that but no more than 500,000 cents takes 350 basis points, and anything above 500,000 cents takes 200 basis points. Because the boundary comparison is inclusive, a `base_net_cents` of exactly 100,000 cents stays in the first tier even though the resulting total then exceeds that boundary. Third, `recovery_fee_cents` is `base_net_cents` multiplied by the selected rate, divided by 10,000, and rounded half up to whole cents — the single rounding event in this rule. Fourth, `net_charge_off_cents` is `base_net_cents` plus `recovery_fee_cents`; this is the figure actually written off and referred. Finally, `outstanding_loss_cents` is derived on every read as `net_charge_off_cents` less `principal_recovered_cents` less `fee_recovered_cents`, and it never goes negative. A fresh proposal has `principal_recovered_cents` and `fee_recovered_cents` at 0, `approved_by_user_id`, `booked_by_user_id`, `ledger_balance_before_book_cents`, `booked_at`, and `reversed_at` all null, and `status` `PROPOSED`.

Every charge-off operation checks the state it expects, reporting `ERR_CHARGE_OFF_INVALID_STATE` (HTTP 409) on a mismatch: approval requires `PROPOSED`; booking requires `APPROVED`; a recovery posting requires `REFERRED_TO_RECOVERY` or `RECOVERED_PARTIAL`; and a reversal requires `BOOKED`, `REFERRED_TO_RECOVERY`, `RECOVERED_PARTIAL`, or `RECOVERED_FULL`. That last set is wider than it looks like it should be, and deliberately so — see the reversal rules below.

**Approval** is a `FraudSupervisor` action and is the transition `PROPOSED → APPROVED`, stamping `approved_by_user_id` from `X-User-ID`.

**Booking** is an `OperationsAdmin` action and is the transition `APPROVED → BOOKED`, stamping `booked_by_user_id` and `booked_at`. The account must have `lifecycle_status` `CLOSED` before a write-off may be booked against it; otherwise the request is refused with `ERR_ACCOUNT_NOT_CLOSED` (HTTP 409). Booking snapshots the account's current `ledger_balance_cents` into `ledger_balance_before_book_cents` so that a later reversal can restore it exactly, then adds `net_charge_off_cents` to both `ledger_balance_cents` and `available_balance_cents`, sets the account's `charged_off_amount_cents` to `net_charge_off_cents`, and drives the account `CLOSED → CHARGED_OFF`. As §2.9 notes, the bank's net position is unchanged by this pair of moves. Within the very same request, a charge-off whose `net_charge_off_cents` is 25,000 cents or more — $250.00, the floor below which agency referral costs more than it recovers — transitions `BOOKED → REFERRED_TO_RECOVERY`. One strictly below that floor stays in `BOOKED` and never becomes eligible for a recovery posting at all.

**Recovery postings** are made by an `OperationsAdmin` and carry an `amount_cents` receipt, which is allocated through a two-bucket waterfall in fixed order: the recovery agency's fee is made whole before the bank recovers any principal. The fee bucket has room equal to `recovery_fee_cents` less `fee_recovered_cents`, and the posting fills it with the smaller of the receipt and that room. Whatever remains then goes to the principal bucket, whose room is `base_net_cents` less `principal_recovered_cents`, again taking the smaller of what remains and that room. If anything is still left over after both buckets are full, the posting does not fit and is rejected in its entirety with `ERR_RECOVERY_EXCEEDS_LOSS` (HTTP 422) — a posting is all-or-nothing and, when rejected, mutates no field anywhere. Otherwise `fee_recovered_cents` and `principal_recovered_cents` are increased by the amounts actually applied, the account's `charged_off_amount_cents` is reduced by the total applied, and the charge-off's status becomes `RECOVERED_FULL` when `outstanding_loss_cents` has reached exactly 0 and `RECOVERED_PARTIAL` while it is still greater than 0. A partial recovery can therefore self-loop `RECOVERED_PARTIAL → RECOVERED_PARTIAL` across successive receipts before finally landing on `RECOVERED_FULL`.

**Reversal** is a `FraudSupervisor` action carrying a `reversal_reason`. It is permitted only where nothing has been recovered: both `principal_recovered_cents` and `fee_recovered_cents` must be exactly 0, and a reversal attempted after any recovery posting is refused with `ERR_RECOVERY_ALREADY_POSTED` (HTTP 409). This is why the state gate above admits `RECOVERED_PARTIAL` and `RECOVERED_FULL`: those charge-offs pass the state check on purpose so that the recovery guard, and not a generic state error, is what reports the refusal. A permitted reversal — from `BOOKED` or from `REFERRED_TO_RECOVERY` — sets `status` to `REVERSED`, stamps `reversed_at`, restores the account's `ledger_balance_cents` to `ledger_balance_before_book_cents` exactly, subtracts `net_charge_off_cents` from its `available_balance_cents`, zeroes its `charged_off_amount_cents`, and drives the account `CHARGED_OFF → CLOSED`.

### 3.9. Law-Enforcement Process and the Preservation Obligation

Incoming legal process is logged by `LegalCounsel` against the depositor whose records are demanded. The payload names the `issuing_agency` in 1 to 120 non-blank characters, the `docket_number` in 1 to 64 non-blank characters, a `response_due_at` deadline that must be strictly after the logical clock at creation, and a closed record-preservation window bounded by `preservation_start_at` and `preservation_end_at` inclusive at both ends, where the end must be strictly after the start. The server stamps `received_at` from the logical clock, records `status` `RECEIVED`, and leaves `legal_reviewed_by_user_id`, `responded_by_user_id`, and `production_note` null with `is_late` false.

Preservation windows on one depositor must not crowd each other. A new window is accepted only when it is separated by at least three calendar days from the window of every other subpoena on the same depositor whose `status` is `RECEIVED`, `UNDER_LEGAL_REVIEW`, or `PRODUCED` — formally, the new window's start must be at or after the existing window's end plus three days, or the new window's end plus three days must be at or before the existing window's start. A gap of exactly three days is accepted; anything shorter, including windows that merely touch and windows nested inside one another, is refused with `ERR_PRESERVATION_WINDOW_CONFLICT` (HTTP 409). Subpoenas that have reached `OBJECTED` or `QUASHED` impose no such buffer.

Logging the process immediately makes the depositor's `preservation_hold_active` true, which is what blocks case closure in §3.7. That flag stays true while any subpoena on the depositor is in `RECEIVED`, `UNDER_LEGAL_REVIEW`, or `PRODUCED` *and* the logical clock has not yet reached that subpoena's `preservation_end_at`.

Handling runs in two steps, and the two steps must be performed by different people. First, counsel takes the process under review, the transition `RECEIVED → UNDER_LEGAL_REVIEW`, which records `legal_reviewed_by_user_id` from `X-User-ID`. Second, counsel signs the response, supplying a `disposition` of `PRODUCE`, `OBJECT`, or `QUASH`, an optional `production_note`, and an optional `late_justification`. The signer's `X-User-ID` must differ from `legal_reviewed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Both steps check the subpoena's state and report `ERR_SUBPOENA_INVALID_STATE` (HTTP 409) on a mismatch: review requires `RECEIVED`, response requires `UNDER_LEGAL_REVIEW`.

Lateness is measured at signing: `is_late` is true exactly when the logical clock is strictly greater than `response_due_at`. When it is, a non-blank `late_justification` must accompany the response; without one the request is refused with `ERR_LATE_JUSTIFICATION_REQUIRED` (HTTP 422). A response signed at or before the deadline needs no justification and records `is_late` false.

The three dispositions transition `UNDER_LEGAL_REVIEW` to `PRODUCED`, `OBJECTED`, and `QUASHED` respectively, and all three stamp `responded_by_user_id`, `production_note`, and `is_late`. They differ in what happens to the preservation obligation. `PRODUCED` remains inside the holding set, so the depositor's `preservation_hold_active` stays true until the logical clock passes that subpoena's `preservation_end_at`. `OBJECTED` and `QUASHED` fall outside the holding set immediately, so `preservation_hold_active` drops to false — unless another subpoena on the same depositor still holds it.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`; every other successful call returns HTTP 200 with the affected resource, the requested resource, or the requested list. The table below is a routing summary only: request payloads, response side effects, and the conditions under which each call is refused are specified in the narrative of §2 and §3, and must be read there.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/deposit-fraud/customers` | Register a depositor. | `OperationsAdmin` |
| GET | `/deposit-fraud/customers/{id}` | Read one depositor, with preservation_hold_active and open_fraud_case_count recomputed against the logical clock. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel` |
| GET | `/deposit-fraud/customers/{id}/accounts` | List every DepositAccount owned by this customer. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel` |
| GET | `/deposit-fraud/customers/{id}/subpoenas` | List every SubpoenaRequest against this customer. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel` |
| POST | `/deposit-fraud/customers/{id}/subpoenas` | Log incoming law-enforcement process against a customer and claim a record-preservation window. | `LegalCounsel` |
| POST | `/deposit-fraud/accounts` | Open a deposit account and score it with the PROVISIONAL_AT_OPEN variant of new_account_risk_score. | `OperationsAdmin` |
| GET | `/deposit-fraud/accounts/{id}` | Read one deposit account including both state dimensions, live balances and the current risk and takeover scores. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel`, `AccountHolder` |
| POST | `/deposit-fraud/accounts/{id}/funding-sources` | Declare an external funding source and send trial deposits. | `OperationsAdmin` |
| GET | `/deposit-fraud/accounts/{id}/funding-sources` | List funding sources declared for this account. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/funding-sources/{id}/verification-attempts` | Submit a trial-deposit amount. | `OperationsAdmin` |
| POST | `/deposit-fraud/funding-sources/{id}/resend` | Re-send trial deposits after a failed attempt, minting a fresh secret and resetting the per-secret attempt counter. | `OperationsAdmin` |
| POST | `/deposit-fraud/account-links` | Record a directed association edge between two deposit accounts. | `FraudAnalyst`, `OperationsAdmin` |
| GET | `/deposit-fraud/accounts/{id}/links` | List every AccountLink whose from_account_id or to_account_id is this account. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/accounts/{id}/deposit-items` | Take a deposit, run check_hold_schedule and post the resulting balances. | `OperationsAdmin` |
| GET | `/deposit-fraud/accounts/{id}/deposit-items` | List deposits taken into this account. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer` |
| GET | `/deposit-fraud/deposit-items/{id}` | Read one deposited item. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer` |
| POST | `/deposit-fraud/deposit-items/{id}/settle` | Post the collection outcome of a deposited item and unwind or charge back its hold. | `OperationsAdmin` |
| GET | `/deposit-fraud/deposit-items/{id}/holds` | List the check holds placed on this item. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| GET | `/deposit-fraud/check-holds/{id}` | Read one check hold, including its current held_amount_cents and version. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/check-holds/{id}/override-reviews` | Open an early-release review against a check hold, claiming a half-open release window on the account. | `FraudAnalyst`, `FraudSupervisor` |
| GET | `/deposit-fraud/check-holds/{id}/override-reviews` | List the override reviews raised against this hold. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| GET | `/deposit-fraud/hold-override-reviews/{id}` | Read one override review including both exposure figures. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/hold-override-reviews/{id}/submit` | Send a draft or returned review to the supervisor queue. | `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/hold-override-reviews/{id}/decide` | Record the supervisor decision: APPROVE, DENY or RETURN_FOR_INFO. | `FraudSupervisor` |
| POST | `/deposit-fraud/hold-override-reviews/{id}/execute` | Release the approved amount from the hold. | `FraudSupervisor` |
| POST | `/deposit-fraud/accounts/{id}/access-review` | Merge account-takeover indicator codes onto an account, rescore it and move the access posture. | `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/accounts/{id}/step-up-response` | Answer the step-up challenge. | `AccountHolder` |
| POST | `/deposit-fraud/accounts/{id}/kiting-scan` | Traverse the on-us circulation graph from this account over a half-open window and score the shortest cycle. | `FraudAnalyst` |
| POST | `/deposit-fraud/fraud-cases` | Open an investigation manually. | `FraudAnalyst` |
| GET | `/deposit-fraud/fraud-cases/{id}` | Read one fraud case. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer`, `LegalCounsel` |
| GET | `/deposit-fraud/accounts/{id}/fraud-cases` | List the fraud cases opened against this account. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer` |
| POST | `/deposit-fraud/fraud-cases/{id}/advance` | Move a newly opened case into active investigation. | `FraudAnalyst` |
| POST | `/deposit-fraud/fraud-cases/{id}/disposition` | Record the investigation outcome: SUBSTANTIATE, UNSUBSTANTIATE or REOPEN. | `FraudSupervisor` |
| POST | `/deposit-fraud/fraud-cases/{id}/close` | Close a disposed case and, when it was substantiated, run the account-closure procedure. | `FraudSupervisor` |
| POST | `/deposit-fraud/fraud-cases/{id}/bsa-referrals` | Draft a suspicious-activity referral against a substantiated case. | `FraudAnalyst` |
| GET | `/deposit-fraud/fraud-cases/{id}/bsa-referrals` | List the referrals raised from this case. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `BsaOfficer` |
| POST | `/deposit-fraud/bsa-referrals/{id}/submit` | File a drafted or returned referral with the BSA unit and freeze its aggregate amount. | `FraudAnalyst` |
| POST | `/deposit-fraud/bsa-referrals/{id}/adjudicate` | BSA unit accepts or returns a filed referral. | `BsaOfficer` |
| POST | `/deposit-fraud/accounts/{id}/charge-offs` | Propose a deposit-loss write-off. | `FraudAnalyst` |
| GET | `/deposit-fraud/accounts/{id}/charge-offs` | List the charge-offs proposed against this account. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| GET | `/deposit-fraud/charge-offs/{id}` | Read one charge-off including its recovery position. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor` |
| POST | `/deposit-fraud/charge-offs/{id}/approve` | Supervisor approves a proposed write-off. | `FraudSupervisor` |
| POST | `/deposit-fraud/charge-offs/{id}/book` | Book an approved write-off against a closed account and, above the referral threshold, refer it to recovery in the same request. | `OperationsAdmin` |
| POST | `/deposit-fraud/charge-offs/{id}/recovery-postings` | Post a recovery receipt through the fee-then-principal waterfall. | `OperationsAdmin` |
| POST | `/deposit-fraud/charge-offs/{id}/reverse` | Reverse a booked write-off that has attracted no recovery, restoring the account's ledger exactly. | `FraudSupervisor` |
| GET | `/deposit-fraud/subpoenas/{id}` | Read one subpoena request. | `OperationsAdmin`, `FraudAnalyst`, `FraudSupervisor`, `LegalCounsel` |
| POST | `/deposit-fraud/subpoenas/{id}/legal-review` | Counsel takes the process under legal review. | `LegalCounsel` |
| POST | `/deposit-fraud/subpoenas/{id}/respond` | Counsel signs the response: PRODUCE, OBJECT or QUASH. | `LegalCounsel` |
| POST | `/deposit-fraud/_clock/set_current_utc` | Set the server's logical clock, which every deposit_at, hold window, preservation window, due date and account-age computation reads. | `OperationsAdmin` |

## 5. Error Code Catalogue

Each error is returned in the standard error envelope of §2.2, with the identifier below in `error_id`. The conditions that trigger each code are stated in the §2 and §3 narratives, and the evaluation order when several could apply is fixed by §2.10.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_ACCOUNT_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_ACCOUNT_NOT_FOUND` | 404 |
| `ERR_FUNDING_SOURCE_NOT_FOUND` | 404 |
| `ERR_DEPOSIT_ITEM_NOT_FOUND` | 404 |
| `ERR_CHECK_HOLD_NOT_FOUND` | 404 |
| `ERR_REVIEW_NOT_FOUND` | 404 |
| `ERR_FRAUD_CASE_NOT_FOUND` | 404 |
| `ERR_CHARGE_OFF_NOT_FOUND` | 404 |
| `ERR_SUBPOENA_NOT_FOUND` | 404 |
| `ERR_BSA_REFERRAL_NOT_FOUND` | 404 |
| `ERR_STALE_CHECK_HOLD_VERSION` | 412 |
| `ERR_STALE_ACCOUNT_VERSION` | 412 |
| `ERR_SELF_LINK` | 422 |
| `ERR_DUPLICATE_LINK` | 409 |
| `ERR_DUPLICATE_OPEN_CASE` | 409 |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 |
| `ERR_ACCOUNT_ACCESS_LOCKED` | 409 |
| `ERR_STEP_UP_NOT_REQUIRED` | 409 |
| `ERR_FUNDING_INVALID_STATE` | 409 |
| `ERR_ITEM_ALREADY_SETTLED` | 409 |
| `ERR_HOLD_NOT_ACTIVE` | 409 |
| `ERR_HOLD_ALREADY_MATURED` | 422 |
| `ERR_RELEASE_WINDOW_OVERLAP` | 409 |
| `ERR_RELEASE_EXCEEDS_HOLD` | 422 |
| `ERR_REVIEW_NOT_SUBMITTED` | 409 |
| `ERR_REVIEW_NOT_APPROVED` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_EXPOSURE_EXCEEDS_AUTHORITY` | 422 |
| `ERR_CASE_INVALID_STATE` | 409 |
| `ERR_CASE_NOT_SUBSTANTIATED` | 409 |
| `ERR_PRESERVATION_HOLD_ACTIVE` | 409 |
| `ERR_BSA_REFERRAL_REQUIRED` | 409 |
| `ERR_REFERRAL_INVALID_STATE` | 409 |
| `ERR_PRESERVATION_WINDOW_CONFLICT` | 409 |
| `ERR_SUBPOENA_INVALID_STATE` | 409 |
| `ERR_LATE_JUSTIFICATION_REQUIRED` | 422 |
| `ERR_ACCOUNT_NOT_CLOSED` | 409 |
| `ERR_CHARGE_OFF_INVALID_STATE` | 409 |
| `ERR_NO_NET_LOSS` | 422 |
| `ERR_RECOVERY_EXCEEDS_LOSS` | 422 |
| `ERR_RECOVERY_ALREADY_POSTED` | 409 |

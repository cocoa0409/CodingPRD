# Rebate Incentive Program API — Product Requirements Document

## 1. Introduction

Manufacturers and distributors run rebate and incentive programs to move product through two very different channels — franchised dealers buying in volume, and end consumers buying one unit at a time — and the administrative burden of those programs is where the money quietly leaks. A claim arrives with a photographed receipt; someone has to decide whether the purchase fell inside the offer window, whether that serial number has already been paid once, whether the claimant is running a velocity scheme across three offers at once, how much the rebate is actually worth after per-line rounding and per-claim caps, whether the program still has budget left to honour it, and — months later — whether the check was ever cashed or must be surrendered to a state unclaimed-property office. Today that work is spread across spreadsheets, a check-printing queue, and a fraud analyst's inbox.

This document specifies a single back-office API that absorbs the whole lifecycle. It carries program budgets as an append-only ledger so that every commitment, release, payment and escheat reversal is reconstructable; it adjudicates claims through an explicit two-dimensional state machine that keeps adjudication and disbursement independent; it prices rebates through a tiered engine whose provisional and final valuations deliberately differ; it scores claimants for fraud in real time and escalates to a case-management workflow; and it disburses through either a printed check or a virtual card, tracking dormancy on both until an escheat sweep surrenders the balance.

Two design commitments run through everything that follows. First, **segregation of duties**: the operator who approves a claim may never be the operator who releases its money. Second, **fiscal determinism**: every amount is an integer number of cents, every rounding point is pinned, and every budget movement is a ledger row — the program's available balance is always derivable from the ledger rather than trusted as a stored number.

---

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the role that principal is acting under. If either header is absent, or if `X-User-Role` does not name one of the six roles defined below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not permitted to invoke the requested operation, the rejection is `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `ProgramAdmin`, `ClaimsProcessor`, `FinanceOfficer`, `FraudAnalyst`, `Dealer` and `Consumer`.

A `ProgramAdmin` owns the program catalogue: creating programs and offers, activating and closing them, adjusting budgets, registering claimants, running escheat sweeps, and driving the server's logical clock. A `ClaimsProcessor` adjudicates: validating receipts, taking claims into review, approving them and denying them. A `FinanceOfficer` disburses: scheduling payouts, releasing them, clearing cashed checks, voiding and reissuing. A `FraudAnalyst` opens fraud cases, drives them through investigation, and reinstates claimants once no case remains open.

For the four staff roles — `ProgramAdmin`, `ClaimsProcessor`, `FinanceOfficer` and `FraudAnalyst` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow demands an audit trail (as `approved_by_user_id` on a claim when a `ClaimsProcessor` approves it, and as `released_by_user_id` on a payout when a `FinanceOfficer` releases it) but never compares it to any entity's `id`.

For the two claimant-facing roles, the binding is different. When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the acting `Claimant`; likewise when `X-User-Role` is `Consumer`. Ownership checks on any claim, receipt, payout or virtual card compare the owning claim's `claimant_id` to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_CLAIM_OWNER` (HTTP 403). That ownership check guards seven operations: opening a claim, attaching a receipt to it, submitting it, withdrawing it, appealing its denial, activating a virtual card, and spending against a virtual card.

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

Every collection endpoint accepts two optional query parameters. `limit` defaults to 10, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and counts records to skip from the start of the ordered result set. Collections are ordered by `created_at` ascending unless a specific narrative below pins a different order.

The `meta` block of a list response reports `limit` and `offset` as applied, `total_count` as the number of records matching the filters before pagination, and `has_more` as true when records remain beyond the current page.

### 2.4. Resource Identity, Timestamps and Versioning

Every resource carries an `id` that is a server-minted UUID with no type prefix. Clients never supply identifiers.

Most resources also carry `created_at`, `updated_at` and `version`. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation of that resource; `updated_at` is refreshed on the same occasions. Programs, offers, claimants, claims, receipts, payouts, virtual cards and fraud cases all behave this way.

Two resources are deliberately immutable once written and therefore carry only `id` and `created_at` — no `updated_at` and no `version`. Those are the ledger row, `BudgetEntry`, and the unclaimed-property record, `EscheatRecord`. Both are append-only historical facts; once appended they are never edited.

### 2.5. The Logical Clock

All temporal reasoning in this system — offer windows, claim windows, grace periods, appeal deadlines, velocity counting and dormancy — reads a server-held **logical clock** rather than wall-clock time. At server startup the logical clock reads exactly `2026-07-01T00:00:00Z`, and it never falls back to real time. An administrative test-driving capability lets a `ProgramAdmin` move the clock to a supplied `to_iso8601` instant; the response reports the resulting `current_utc`. Every subsequent window, dormancy, velocity and appeal computation uses the new instant.

Wherever this document speaks of "whole days" between two instants, it means the number of complete 24-hour days that have elapsed — the elapsed interval truncated downward, so a difference of 89 hours is 3 whole days.

### 2.6. Money, Counts and Rounding

All monetary values are integer numbers of cents; no field carries a fractional currency amount. Where a computation produces a fractional intermediate, the rounding rule is **round half up**, and the point at which rounding happens is pinned by the narrative that defines the computation — moving a rounding step produces a different, and wrong, number of cents.

One value in the system is not an integer: `utilization_pct` on a program is a number rounded half up to four decimal places.

### 2.7. Optimistic Concurrency on Programs and Claims

Two write operations are guarded by optimistic concurrency control against a parent entity's `version`.

Scheduling a disbursement for an approved claim requires the request to carry `expected_claim_version`, a non-optional field holding the client's last observed `version` of the target claim. If that value does not equal the claim's current `version`, the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412). This matters because a claim may legitimately carry a succession of payouts — a voided payout is replaced by a fresh one — so no state precondition alone would block a second create; the version check is what makes the outcome deterministic and prevents a client from scheduling money against a claim it has not observed.

Adjusting a program's budget requires the request to carry `expected_program_version`, a non-optional field holding the client's last observed `version` of the target program. A mismatch with the program's current `version` is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412). Budget adjustments legitimately supersede one another, so an adjustment carrying an outdated version is rejected on the version check rather than on any status precondition.

No other endpoint accepts a version field, and none should be inferred.

### 2.8. Order of Evaluation for Rejections

When a single request could fail several checks, the checks are evaluated in a fixed order and the first failure is the one reported. The order is:

1. Authentication — both headers present and the role recognised, else `ERR_UNAUTHENTICATED`.
2. Authorization — the acting role is permitted on this operation, else `ERR_UNAUTHORIZED`.
3. Ownership — for `Dealer` and `Consumer` acting on a claim, receipt, payout or virtual card, `X-User-ID` must equal the owning claim's `claimant_id`, else `ERR_NOT_CLAIM_OWNER`.
4. Path existence — every resource named in the URL path must exist, resolved left to right, else the corresponding not-found error (`ERR_PROGRAM_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_CLAIMANT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND`, `ERR_PAYOUT_NOT_FOUND`, `ERR_CARD_NOT_FOUND` or `ERR_FRAUD_CASE_NOT_FOUND`, all HTTP 404).
5. Body foreign keys — every identifier supplied in a request body (`program_id`, `offer_id`, `claimant_id`, `claim_id`) must resolve to an existing row, else the corresponding not-found error. This applies when creating an offer, opening a claim, and opening a fraud case.
6. Shape validation — required fields present, enum values drawn from their declared sets, constrained integers positive, an offer's `effective_end_date` strictly later than its `effective_start_date`, and a receipt's `lines` a non-empty array each of whose entries carries `sku`, a `quantity` greater than zero and a `unit_price_cents` greater than zero. Any breach is `ERR_VALIDATION` (HTTP 400). This applies to every write endpoint.
7. Receipt line ceiling — a receipt's `lines` array may carry at most 20 entries; a longer array is `ERR_RECEIPT_LIMIT_EXCEEDED` (HTTP 422). This is checked after shape validation, so an empty array reports `ERR_VALIDATION` while a 21-entry array reports `ERR_RECEIPT_LIMIT_EXCEEDED`.
8. Optimistic concurrency — the version checks of §2.7.
9. State preconditions — the target resource must be in a state from which the requested transition is declared, else one of `ERR_PROGRAM_NOT_ACTIVE`, `ERR_OFFER_NOT_PUBLISHED`, `ERR_CLAIM_NOT_DRAFT`, `ERR_CLAIM_NOT_REVIEWABLE`, `ERR_CLAIM_ALREADY_TERMINAL`, `ERR_PAYOUT_NOT_RELEASABLE`, `ERR_CARD_NOT_ACTIVE` or `ERR_INVALID_TRANSITION` (all HTTP 409). This applies to every action endpoint.
10. Duplicate-payout guard — `ERR_PAYOUT_ALREADY_EXISTS`.
11. Claimant standing — `ERR_CLAIMANT_BLOCKED`.
12. Segregation of duties — `ERR_SEGREGATION_OF_DUTIES`.
13. Temporal windows, in this internal order: the claim window (`ERR_CLAIM_WINDOW_EXPIRED`), the offer purchase window (`ERR_PURCHASE_OUTSIDE_OFFER_WINDOW`), the offer grace window (`ERR_OFFER_WINDOW_CLOSED`), then the appeal window (`ERR_APPEAL_WINDOW_EXPIRED`).
14. Referential business checks, in this internal order: serial-number dedupe (`ERR_DUPLICATE_RECEIPT_SERIAL`), channel compatibility (`ERR_CHANNEL_MISMATCH`), then offer-window overlap (`ERR_OFFER_WINDOW_OVERLAP`).
15. Remaining business constraints, in this internal order: the per-offer claim cap (`ERR_CLAIM_CAP_EXCEEDED`), the validated-receipt requirement at approval (`ERR_NO_VALIDATED_RECEIPT`), the appeal ceiling (`ERR_APPEAL_LIMIT_REACHED`), then the card spend bound (`ERR_INSUFFICIENT_CARD_BALANCE`).
16. Fiscal gates, in this internal order: the budget gate at approval (`ERR_BUDGET_EXCEEDED`), the minimum payout floor (`ERR_BELOW_MIN_PAYOUT`), then the budget-adjustment floor (`ERR_BUDGET_ADJUSTMENT_INVALID`).
17. The check-only clearing rule (`ERR_NOT_CHECK_PAYOUT`).

Two consequences of this ordering are worth stating outright. A blocked claimant attempting to submit a claim whose receipts are also stale reports `ERR_CLAIMANT_BLOCKED`, not `ERR_CLAIM_WINDOW_EXPIRED`, because claimant standing is evaluated ahead of the temporal checks. And a submit that is both a duplicate serial and over the per-offer cap reports `ERR_DUPLICATE_RECEIPT_SERIAL`, because dedupe precedes the cap.

### 2.9. Cascade Discipline

Several operations in this system mutate more than one entity. Where that happens, the narrative in §3 enumerates every hop of the cascade, and all hops of a cascade are applied within the same request — there is no deferred or eventual settlement. A caller that reads a program immediately after an approval sees the committed budget already moved; a caller that reads a claimant immediately after a fraud substantiation sees the claimant blocked and its open claims already denied.

Whenever a cascade mutates a resource that carries `version`, that resource's `version` increases by 1 and its `updated_at` is refreshed, exactly as for a direct mutation.

---

## 3. Business Logic & Workflows

### 3.1. Standing Up a Program and Its Budget Ledger

A `ProgramAdmin` opens the fiscal year by creating a **program**, supplying a display `name`, the `fiscal_year` the budget belongs to, an `escheat_jurisdiction` (a two-letter state code used as the fallback destination for unclaimed funds), and a `budget_total_cents` figure that must be greater than zero. The program is born in `DRAFT` with `available_cents` equal to `budget_total_cents` and `utilization_pct` at 0.0. Activation moves it `DRAFT → ACTIVE`, and is permitted only from `DRAFT` and only while `budget_total_cents` is greater than zero; the budget position is recomputed as part of the transition.

Money never moves by direct assignment. Every fiscal event appends a **budget entry**, an immutable ledger row naming the `program_id` whose ledger it belongs to, the `claim_id` that caused it (null for a pure budget adjustment), an `entry_type` drawn from `ACCRUAL`, `COMMIT`, `RELEASE`, `PAYMENT`, `ESCHEAT_REVERSAL` and `BUDGET_ADJUSTMENT`, an `amount_cents` figure that is always written as a positive number (the sign convention lives in the `entry_type`, not in the amount), a `committed_after_cents` snapshot of the program's committed total immediately after the row was appended, and an optional human-readable `memo`.

From that ledger the program's live **budget position** is derived. The evaluation order is fixed and must be followed exactly. First, `committed_cents` is the sum of the amounts of all `COMMIT` entries, less the sum of all `RELEASE` entries, less the sum of all `ESCHEAT_REVERSAL` entries. Second, `pending_provisional_cents` is the sum of the provisional rebate figures of every claim funded by this program — that is, every claim whose offer belongs to the program — whose adjudication state is `SUBMITTED`, `UNDER_REVIEW` or `HELD`; when the recomputation happens inside an approval request, the claim being approved is excluded from this sum, and outside an approval there is no such exclusion. Third, `reserve_cents` is fifteen hundredths of `pending_provisional_cents`, rounded half up to whole cents. Fourth, `available_cents` is `budget_total_cents` less `committed_cents` less `reserve_cents`. Fifth, `utilization_pct` is the sum of `committed_cents` and `reserve_cents` divided by `budget_total_cents`, rounded half up to four decimal places. This position is recomputed at the end of every request that appends a ledger row, changes a claim's adjudication state, or adjusts the budget, and it is recomputed to serve a program read as well.

Two further program totals are also read straight off the ledger. `paid_cents` is the sum of the amounts of `PAYMENT` entries whose associated claim currently has a payment state of `PAID` or `ESCHEATED` — which is why voiding a released payout lowers `paid_cents` without any compensating ledger row being written. `escheat_recovered_cents` is the sum of the amounts of all `ESCHEAT_REVERSAL` entries.

The eighty-percent mark, a `utilization_pct` of 0.8000, is the program's warning level: it is reported but does not gate anything. The hundred-percent mark, a `utilization_pct` of 1.0000, is the hard level, and it is a genuine gate. Whenever a recomputation triggered by a `COMMIT` or `BUDGET_ADJUSTMENT` entry leaves an `ACTIVE` program at a `utilization_pct` of 1.0000 or above — the comparison is at-or-above, not strictly above — the program moves `ACTIVE → BUDGET_LOCKED` automatically inside the very request that appended the entry. That lock cascades: as hop two, every offer of the program currently `PUBLISHED` moves `PUBLISHED → SUSPENDED`; as hop three, for each offer so suspended, every claim on that offer still in `DRAFT` moves `DRAFT → VOIDED`. Conversely, whenever a recomputation triggered by a `RELEASE`, `ESCHEAT_REVERSAL` or `BUDGET_ADJUSTMENT` entry leaves a `BUDGET_LOCKED` program at a `utilization_pct` strictly below 1.0000, the program moves `BUDGET_LOCKED → ACTIVE`. Unlocking does not undo the cascade: offers suspended by the lock are not auto-republished, and a `ProgramAdmin` must republish them deliberately; voided claims are never resurrected.

Budget adjustments are the one route by which `budget_total_cents` changes after creation. The request carries a signed `delta_cents`, an explanatory `memo`, and the `expected_program_version` described in §2.7. The delta is added to `budget_total_cents`, a ledger row of type `BUDGET_ADJUSTMENT` is appended, and the budget position is recomputed — which may fire either the lock or the unlock transition. An adjustment that would drive `budget_total_cents` to zero or below is refused with `ERR_BUDGET_ADJUSTMENT_INVALID` (HTTP 422). Program listings may be narrowed by `status` and by `fiscal_year`.

Closing a program is permitted from `ACTIVE` and from `BUDGET_LOCKED`, and only when no claim funded by the program is still in `SUBMITTED`, `UNDER_REVIEW` or `HELD` — in-flight adjudication must be finished first. Closure moves the program to `CLOSED`, which is terminal, and cascades to the catalogue: every offer of the program in `DRAFT`, `PUBLISHED` or `SUSPENDED` moves to `CLOSED` with its `closed_at` stamped from the logical clock.

### 3.2. The Offer Catalogue

An **offer** is the funded promise a claim is made against. Creating one requires the `program_id` that funds it, a display `name`, a `channel` of `DEALER`, `CONSUMER` or `BOTH`, a `sku_scope` naming the SKU family covered, an `effective_start_date` and an `effective_end_date`, and a `max_rebate_cents_per_claim` ceiling greater than zero. An optional `dealer_tier_enabled` flag defaults to true; when it is false, dealer claims against this offer price at the lowest tier regardless of how many units they cover. Offers begin in `DRAFT`, carry `closed_at` as null until closure, and expose an `active_claim_count` that starts at zero.

The offer window is **half-open**: a purchase instant at or after `effective_start_date` and strictly before `effective_end_date` is inside the window, and a purchase falling exactly on `effective_end_date` is outside it. That interpretation also governs collision detection between sibling offers. No two offers sharing the same `program_id`, the same `sku_scope` and the same `channel`, and both in a live state (`DRAFT`, `PUBLISHED` or `SUSPENDED`), may have intersecting half-open windows; windows that merely touch — one ending exactly where the other begins — do not intersect and are permitted. A collision is refused with `ERR_OFFER_WINDOW_OVERLAP` (HTTP 409), and the check runs both when an offer is created and again when one is published.

Publication is permitted from `DRAFT` and from `SUSPENDED`, and requires the funding program to be `ACTIVE` — a program still in `DRAFT`, locked at `BUDGET_LOCKED`, or `CLOSED` cannot have offers published under it, and the attempt reports `ERR_PROGRAM_NOT_ACTIVE`. A published offer is the only kind of offer a new claim may be opened against. Suspension takes a `PUBLISHED` offer to `SUSPENDED`, and it is available both to a `ProgramAdmin` acting directly and to the system as hop two of a budget lock. Suspension has one cascade: every claim on the offer still in `DRAFT` moves `DRAFT → VOIDED`. Claims already `SUBMITTED`, `UNDER_REVIEW` or `HELD` are untouched by suspension and continue to adjudicate to completion. Republishing from `SUSPENDED` restores eligibility for new claims but does not resurrect the voided ones, and it re-runs the same window-overlap check and the same requirement that the program be `ACTIVE`; the `PUBLISHED → SUSPENDED → PUBLISHED` cycle may repeat indefinitely.

Closing an offer is permitted from `DRAFT`, `PUBLISHED` or `SUSPENDED` and stamps `closed_at` with the logical clock. `CLOSED` is terminal for an offer, but it is not immediately the end of claiming: submissions against a closed offer are still accepted for a grace period of 15 whole days measured from `closed_at`, inclusive of the fifteenth day. On day 16 the door shuts and a submission attempt reports `ERR_OFFER_WINDOW_CLOSED` (HTTP 422). Offer listings may be narrowed by `program_id`, by `status`, by `channel` and by `sku_scope`.

### 3.3. Claimants, Claim Intake and Proof of Purchase

A `ProgramAdmin` registers each **claimant** before it can claim, recording a `type` of either `DEALER` or `CONSUMER`, a `legal_name`, an `email`, and a `mailing_state` two-letter code that later determines where unclaimed funds are surrendered. New claimants start `ACTIVE` with a `fraud_score` of 0 and with `duplicate_attempt_count`, `denied_claim_count` and `open_claim_count` all at zero. Claimant listings may be narrowed by `type` and by `status`.

A claimant's `type` must be compatible with the `channel` of any offer it claims against: a `DEALER` claimant may claim only against a `DEALER` or `BOTH` offer, and a `CONSUMER` claimant only against a `CONSUMER` or `BOTH` offer. Incompatibility is reported as `ERR_CHANNEL_MISMATCH` (HTTP 422), and the check is enforced twice — once when the claim is opened and again when it is submitted, because the offer may have been re-scoped in between.

Opening a claim requires only the `offer_id` being claimed against and the `claimant_id` doing the claiming, and it is done by the claimant itself acting as `Dealer` or `Consumer`. The offer must be `PUBLISHED` at that moment, otherwise `ERR_OFFER_NOT_PUBLISHED` is returned. The new claim starts with `adjudication_status` of `DRAFT` and `payment_status` of `NONE`, with `total_units` and `provisional_rebate_cents` at zero, `final_rebate_cents`, `fraud_score_at_submit`, `submitted_at`, `approved_at`, `denied_at`, `approved_by_user_id` and `denial_reason_code` all null, and `appeal_count` at zero. Claim listings may be narrowed by `claimant_id`, by `offer_id`, by `adjudication_status` and by `payment_status`.

Proof of purchase is attached as **receipts**, and only while the claim is still `DRAFT` — attaching to a claim in any later state reports `ERR_CLAIM_NOT_DRAFT` (HTTP 409). Each receipt records the `claim_id` it belongs to, the manufacturer `serial_number` printed on it, a `purchase_date`, a `retailer_name`, and a `lines` array whose entries each carry a `sku` string, a `quantity` greater than zero and a `unit_price_cents` greater than zero. The array must hold at least one entry and at most 20; the evaluation order of the lines is the order in which the client submitted them, and that order matters to the rebate arithmetic of §3.5. On creation the server computes `line_count` as the number of entries in `lines`, `units` as the sum of the `quantity` values across those entries, and `gross_amount_cents` as the sum, over the entries, of `quantity` multiplied by `unit_price_cents`. The receipt begins with `validated` false and `validated_at` null.

Validation is a `ClaimsProcessor` act: marking a receipt verified sets `validated` to true and stamps `validated_at` from the logical clock. This is the gate that decides which receipts feed the final rebate valuation. Receipt listings scoped to a claim may be narrowed by `validated`.

### 3.4. The Submission Gate

Submission is what turns a private draft into an obligation the program has to price and reserve against, and it is the most heavily guarded operation in the system. It is performed by the claimant itself, and the claim must be in `DRAFT`; a submission attempt from any other adjudication state reports `ERR_CLAIM_NOT_DRAFT`. The acting `X-User-ID` must equal the claim's `claimant_id`.

Beyond the state and ownership checks, submission enforces the following, evaluated in the precedence of §2.8. The claimant must be `ACTIVE`; a `BLOCKED` claimant is refused with `ERR_CLAIMANT_BLOCKED` (HTTP 403). Every receipt's `purchase_date` must be recent enough: the whole days between a receipt's `purchase_date` and the logical clock must be at most 90, so a purchase exactly 90 days old is still claimable and one 91 days old is refused with `ERR_CLAIM_WINDOW_EXPIRED` (HTTP 422). Every receipt's `purchase_date` must also fall inside the offer's half-open window, and a purchase exactly at `effective_end_date` is refused with `ERR_PURCHASE_OUTSIDE_OFFER_WINDOW` (HTTP 422). The offer must be `PUBLISHED`, or else `CLOSED` with at most 15 whole days elapsed since `closed_at`, failing which the answer is `ERR_OFFER_WINDOW_CLOSED`. The claim must carry at least one receipt.

Serial-number dedupe is the referential guard. No receipt of the claim being submitted may share a `serial_number` with a receipt attached to a *different* claim that is currently in `SUBMITTED`, `UNDER_REVIEW`, `HELD` or `APPROVED`, when the two receipts' `purchase_date` values lie within 365 whole days of one another. That window is a closed interval measured in both directions — 365 days apart in either direction still collides, 366 days apart does not. A collision is refused with `ERR_DUPLICATE_RECEIPT_SERIAL` (HTTP 409), and the rejection carries a lasting consequence: before the error is returned, the claimant's `duplicate_attempt_count` is incremented, and that counter feeds the fraud score permanently.

A single claimant may hold at most three live claims against one offer. At submission, the count of this claimant's *other* claims on the same offer whose adjudication state is anything other than `DRAFT`, `WITHDRAWN` or `VOIDED` must be strictly less than 3; the claim being submitted is not itself counted. A fourth submission against the same offer is refused with `ERR_CLAIM_CAP_EXCEEDED` (HTTP 409), and withdrawing one of the three frees the slot again.

When all of that passes, submission moves the claim `DRAFT → SUBMITTED` and does seven things at once. It stamps `submitted_at` with the logical clock. It stamps `provisional_rebate_cents` with the provisional valuation of §3.5. It recomputes `total_units` over all receipts of the claim. It computes the real-time fraud heuristic of §3.7, writing it to the claim's `fraud_score_at_submit` and to the claimant's `fraud_score`. It appends a ledger row of type `ACCRUAL` whose `amount_cents` equals the claim's `provisional_rebate_cents`. It increments the claimant's `open_claim_count` by one and the offer's `active_claim_count` by one. And it recomputes the program's `pending_provisional_cents` and `reserve_cents`.

Then, still inside the same request, the fraud threshold is evaluated. If `fraud_score_at_submit` is 70 or above, the claim moves on immediately from `SUBMITTED` to `HELD` and a fraud case is opened automatically — so the response to a submission by a high-risk claimant already shows `HELD` rather than `SUBMITTED`. §3.7 describes what that case looks like.

Withdrawal is the compensating action. A claimant may withdraw its own claim from `DRAFT` or from `SUBMITTED`, moving it to the terminal `WITHDRAWN` state; the acting `X-User-ID` must equal the claim's `claimant_id`. Withdrawing a `DRAFT` claim changes no counters, because a draft was never counted. Withdrawing a `SUBMITTED` claim decrements the claimant's `open_claim_count` by one and the offer's `active_claim_count` by one, and recomputes the program's `pending_provisional_cents` and `reserve_cents` — restoring both conserved counters to exactly their pre-submission values.

### 3.5. How a Rebate Is Priced

The rebate a claim is worth is computed twice in its life, once provisionally at submission and once finally at approval, using the same five-step procedure over a different set of receipts. Understanding why the two results are not proportional is essential.

**Step one — choose the included receipts.** The provisional valuation includes *all* receipts attached to the claim, whether or not they have been validated; the tier it selects therefore reflects unverified units. The final valuation includes *only* receipts whose `validated` flag is true. Receipts attached to any other claim never contribute to either valuation.

**Step two — total the units and pick the rate once.** Sum the `quantity` values of every line of every included receipt to get the claim-level unit total. That total selects a single percentage for the whole claim; the rate is not re-selected per receipt or per line. For a claimant of type `CONSUMER` the rate is ten percent, regardless of units. For a claimant of type `DEALER` the rate depends on the offer's `dealer_tier_enabled` flag: when that flag is false the rate is five percent whatever the unit count; when it is true, a unit total of 9 or fewer earns five percent, a unit total from 10 through 49 earns eight percent, and a unit total of 50 or more earns twelve percent.

**Step three — round per line, then sum.** Walk the included receipts in ascending order of their `created_at`, and within each receipt walk its `lines` in the order the client submitted them. For each line, multiply its `quantity` by its `unit_price_cents` by the selected rate, round that single result half up to whole cents, and add it to a running total. The rounding order is pinned: rounding each line before summing is correct, and summing the unrounded line values before rounding once is wrong and yields a different number of cents.

**Step four — the consumer bonus.** If the claimant's `type` is `CONSUMER` and the running total from step three is greater than zero, add a flat 500 cents to it, once per claim. A dealer claim never receives this bonus, and a consumer claim whose step-three total came out at zero does not receive it either.

**Step five — the cap.** The rebate is the lesser of the step-four total and the offer's `max_rebate_cents_per_claim`. No rounding is performed at step four or step five; both operands are already whole cents.

The consequence of running this over two different receipt sets is that dropping unvalidated receipts at approval can pull a dealer claim's unit total down across a tier boundary — from 52 units at twelve percent to 40 units at eight percent, say — so the final figure is not a proportional shrink of the provisional figure but a genuinely different calculation. The provisional figure lands in `provisional_rebate_cents` at submission and drives the program's accrual reserve; the final figure lands in `final_rebate_cents` at approval and drives the program's hard commitment.

### 3.6. Adjudication, Denial and Appeal

A `ClaimsProcessor` takes a claim into review, moving it `SUBMITTED → UNDER_REVIEW`. Nothing else changes: no counter moves and the claim remains inside the set feeding `pending_provisional_cents`. A review attempt from a state that does not declare the transition is refused with `ERR_CLAIM_NOT_REVIEWABLE`, and any adjudication action attempted against a claim already resting in `APPROVED`, `REVOKED`, `WITHDRAWN` or `VOIDED` is refused with `ERR_CLAIM_ALREADY_TERMINAL`.

Approval is the moment the program's money is genuinely committed, and it carries five preconditions. The claim must be `UNDER_REVIEW`. The claimant must be `ACTIVE`, else `ERR_CLAIMANT_BLOCKED`. The funding program must be `ACTIVE` — a program that has locked at `BUDGET_LOCKED` cannot approve further claims, and the refusal is `ERR_PROGRAM_NOT_ACTIVE`. At least one receipt of the claim must have `validated` true, else `ERR_NO_VALIDATED_RECEIPT` (HTTP 422). And the final valuation of §3.5 must fit inside the program's `available_cents`, evaluated with this very claim excluded from `pending_provisional_cents` so that the claim's own accrual reserve does not block its own approval; a final rebate exceeding the available balance is refused with `ERR_BUDGET_EXCEEDED` (HTTP 409).

On approval the claim moves `UNDER_REVIEW → APPROVED`, which is terminal on the adjudication axis. `final_rebate_cents` is stamped with the final valuation and `total_units` is recomputed over validated receipts only. `approved_at` is stamped from the logical clock, and `approved_by_user_id` is set to the requesting `X-User-ID` — the segregation-of-duties key that §3.8 later enforces. As the first cascade hop, a ledger row of type `COMMIT` with `amount_cents` equal to `final_rebate_cents` is appended, raising the program's `committed_cents`. The claimant's `open_claim_count` is decremented by one, while the offer's `active_claim_count` is deliberately left unchanged, because `APPROVED` still counts as an active status on an offer. Finally the budget position is recomputed, and if `utilization_pct` has reached 1.0000 or above the program locks — which suspends its published offers, which in turn voids their `DRAFT` claims, all inside this same approval request.

Denial moves the claim `UNDER_REVIEW → DENIED` and requires a `reason_code` in the request, which is stored on the claim as `denial_reason_code`. `denied_at` is stamped from the logical clock, the claimant's `denied_claim_count` is incremented by one and its `open_claim_count` decremented by one, the offer's `active_claim_count` is decremented by one, and the program's `pending_provisional_cents` and `reserve_cents` are recomputed.

`DENIED` is not terminal. The claimant may appeal, supplying an `appeal_note`, and a successful appeal cycles the claim `DENIED → UNDER_REVIEW`. Four conditions gate it: the claim must be `DENIED`; its `denial_reason_code` must not be the string `FRAUD_SUBSTANTIATED`, because a fraud denial is not appealable; the claimant must be `ACTIVE`, else `ERR_CLAIMANT_BLOCKED`; the whole days between `denied_at` and the logical clock must be at most 30, so an appeal on day 30 is accepted and one on day 31 is refused with `ERR_APPEAL_WINDOW_EXPIRED` (HTTP 422); and `appeal_count` must be strictly less than 2, so a claim may be appealed twice in total and a third attempt is refused with `ERR_APPEAL_LIMIT_REACHED` (HTTP 409). A successful appeal increments `appeal_count` by one, decrements the claimant's `denied_claim_count` by one, increments its `open_claim_count` by one, increments the offer's `active_claim_count` by one, and recomputes the program's `pending_provisional_cents` and `reserve_cents` — the exact inverse of the denial bookkeeping.

### 3.7. Fraud Scoring and Case Management

Risk is expressed as an integer `fraud_score` between 0 and 100 held on each claimant, and it is produced by two different formulas depending on who is asking.

The **real-time heuristic** runs at every submission and is a pure weighted sum of four observable counters, with no analyst judgement in it. Take the claimant's `denied_claim_count` — the number of its claims currently sitting in `DENIED` — and weight it at 15 points each. Take the claimant's cumulative `duplicate_attempt_count` — the number of submissions it has had rejected for a duplicate serial number — and weight it at 25 points each. Count how many of this claimant's claims have a non-null `submitted_at` falling strictly less than 30 days before the logical clock, *including* the claim currently being submitted; subtract 2 from that count and take the larger of the result and zero, then weight what remains at 10 points each — so the first two claims in any 30-day window are free and each additional one costs 10. Finally, if the claim's `provisional_rebate_cents` is 50000 cents or more, add a flat 20 points; otherwise add nothing. Sum the four contributions, then clamp the total into the range 0 through 100 inclusive. Claims in `DRAFT`, `WITHDRAWN` or `VOIDED` never contribute to either the denied count or the recency count, and only this claimant's own claims are considered.

The resulting integer is written both to the claim's `fraud_score_at_submit` and to the claimant's `fraud_score`, and it is the value compared against the escalation threshold. A score of 70 or above — at or above, not strictly above — moves the freshly submitted claim `SUBMITTED → HELD` and opens a fraud case automatically. That auto-opened case starts with `status` `OPEN`, `opened_by` of `SYSTEM_AUTO`, its `claimant_id` set to the claim's claimant, its `claim_id` set to the claim, its `heuristic_score_at_open` set to the same `fraud_score_at_submit` value, its `opened_reason` set to the string `AUTO_THRESHOLD`, `final_score` null and `info_request_count` at zero.

A `FraudAnalyst` may also open a case deliberately, supplying the `claimant_id` under investigation, an `opened_reason` explaining why, and optionally a `claim_id` when a specific claim prompted it. An analyst-opened case starts in `OPEN` with `opened_by` of `ANALYST` and has its `heuristic_score_at_open` stamped from the real-time heuristic evaluated at that moment. Case listings may be narrowed by `claimant_id`, by `claim_id` and by `status`.

Cases are driven by a single transition capability that names the destination in a `to_status` field and accepts an optional `note`. From `OPEN` the case may move to `UNDER_INVESTIGATION`. From `UNDER_INVESTIGATION` it may move to `PENDING_INFO`, which increments `info_request_count` by one; from `PENDING_INFO` it may return to `UNDER_INVESTIGATION`, and this `UNDER_INVESTIGATION → PENDING_INFO → UNDER_INVESTIGATION` cycle is unbounded. From `UNDER_INVESTIGATION` the case may reach either of its two terminal states, `SUBSTANTIATED` or `CLEARED`. Any destination requested from a state that does not declare it is refused with `ERR_INVALID_TRANSITION` (HTTP 409).

Reaching a terminal state stamps the case's `final_score` using the **investigated** formula, which starts from the case's own `heuristic_score_at_open` rather than from live counters — so two cases with identical counter inputs end at two different scores depending on which branch was taken. On the `SUBSTANTIATED` branch, multiply `heuristic_score_at_open` by 1.5, round the product half up to a whole number of points, and take the lesser of that and 100. On the `CLEARED` branch, subtract 30 points from `heuristic_score_at_open` and take the greater of that and 0. In both branches the resulting `final_score` is also copied onto the claimant's `fraud_score`.

Clearing a case is the gentle branch: beyond stamping the scores, if the case's associated claim is currently `HELD` it moves `HELD → UNDER_REVIEW`, rejoining the normal adjudication queue with the claimant's `fraud_score` now set to the case's `final_score`.

Substantiating a case is the severe branch, and it fans out three hops deep. As hop one, the claimant moves `ACTIVE → BLOCKED`. As hop two, every claim of that claimant currently in `SUBMITTED`, `UNDER_REVIEW` or `HELD` moves to `DENIED`, with `denied_at` stamped from the logical clock and `denial_reason_code` set to the string `FRAUD_SUBSTANTIATED` — which, per §3.6, makes those denials permanently unappealable — and for each such claim the claimant's `denied_claim_count` rises by one, its `open_claim_count` falls by one, and the offer's `active_claim_count` falls by one. Also as hop two, every claim of that claimant in `APPROVED` whose payment state is `NONE` or `SCHEDULED` moves `APPROVED → REVOKED`, and each such revocation decrements its offer's `active_claim_count` by one. As hop three, each revoked claim appends a ledger row of type `RELEASE` whose `amount_cents` equals that claim's `final_rebate_cents`, lowering the program's `committed_cents`; and any payout of that claim in `PENDING` or `REISSUE_PENDING` moves to `VOIDED` with the claim's payment state reset to `NONE`. An approved claim whose money has already been paid out is *not* revoked — the revocation branch reaches only the unpaid ones.

Reinstatement returns a `BLOCKED` claimant to `ACTIVE`, and is a `FraudAnalyst` act carrying a `memo`. It requires the claimant to be `BLOCKED` and requires that none of that claimant's fraud cases is still in `OPEN`, `UNDER_INVESTIGATION` or `PENDING_INFO`. Reinstatement resets the claimant's `fraud_score` to 0. It does not resurrect anything: claims denied or revoked by the substantiation cascade stay where they are.

### 3.8. Disbursement: Checks, Cards and the Segregation Rule

A `FinanceOfficer` schedules a **payout** against an approved claim, and the request carries the `expected_claim_version` of §2.7 plus an optional `method`. The claim must be `APPROVED` on the adjudication axis and `NONE` on the payment axis. A claim that already has a payout in `PENDING`, `RELEASED` or `REISSUE_PENDING` cannot be given a second one, and the attempt is refused with `ERR_PAYOUT_ALREADY_EXISTS` (HTTP 409) — but a claim whose payout has been voided may be given a fresh one, which is precisely why the version guard exists.

The amounts on the payout are settled in a pinned order, because the method depends on an amount threshold while the fee — and therefore the amount actually disbursed — depends on the method. First, `gross_cents` is fixed as the claim's `final_rebate_cents` and never changes thereafter. Second, the `method` is selected *from the gross*, never from the net: if the request supplied a `method`, that value is used as given; otherwise, if the claimant's `type` is `CONSUMER` and `gross_cents` is 2500 cents or more, the method is `VIRTUAL_CARD`; otherwise the method is `CHECK`. Third, `fee_cents` follows the method — 150 cents for a `CHECK`, 50 cents for a `VIRTUAL_CARD`. Fourth, `net_cents` is `gross_cents` less `fee_cents`; the method is deliberately *not* re-selected even when subtracting the fee drops the net back below the 2500-cent card threshold. Fifth, if `net_cents` is below 100 cents the payout is refused with `ERR_BELOW_MIN_PAYOUT` (HTTP 422); the same floor is checked again at release. No rounding occurs anywhere in this computation, since every operand is already a whole number of cents.

A successful scheduling creates the payout in `PENDING` with `check_number`, `released_at`, `released_by_user_id` and `void_reason` all null and `reissue_count` at zero, moves the claim's payment state `NONE → SCHEDULED`, and increments the claim's `version` by one. Payout listings may be narrowed by `claim_id`, by `status` and by `method`.

Releasing a payout is the moment money leaves the building, and it is available from `PENDING` and from `REISSUE_PENDING`. The request may carry a `check_number`, which is only meaningful for a check. Three further conditions apply: the claimant must be `ACTIVE`, else `ERR_CLAIMANT_BLOCKED`; the payout's `net_cents` must be at least 100 cents, else `ERR_BELOW_MIN_PAYOUT`; and — the segregation-of-duties rule — the requesting `X-User-ID` must differ from the `approved_by_user_id` recorded on the claim when it was approved. An operator attempting to release money it itself approved is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). A release attempted from a payout state that does not declare it reports `ERR_PAYOUT_NOT_RELEASABLE` (HTTP 409).

On release the payout moves to `RELEASED`, `released_at` is stamped from the logical clock and `released_by_user_id` from the acting `X-User-ID`; the claim's payment state moves `SCHEDULED → PAID`; and a ledger row of type `PAYMENT` with `amount_cents` equal to the payout's `net_cents` is appended, raising the program's `paid_cents`. When the method is `VIRTUAL_CARD`, releasing also materialises a card. A release from `REISSUE_PENDING` re-stamps `released_at`, which restarts the dormancy clock of §3.9 from scratch.

Voiding is available from `PENDING`, `RELEASED` and `REISSUE_PENDING`, and requires a `void_reason`. Voiding a payout that was merely scheduled moves the claim's payment state `SCHEDULED → NONE`. Voiding one that was already released moves the claim's payment state `PAID → NONE`, which — because `paid_cents` is derived from the ledger by looking at each payment entry's claim — lowers the program's `paid_cents` by that payout's `net_cents` without any new ledger row being written. In neither case is a `RELEASE` row appended: voiding a payout does not release the underlying commitment, because the claim is still owed its rebate. A virtual card attached to a voided payout is left untouched rather than escheated, and further spends against it fail because its payout is no longer `RELEASED`.

Reissue is the recovery path for a lost check or a botched card, and it is available from `RELEASED` and from `VOIDED`, moving the payout to `REISSUE_PENDING` and incrementing `reissue_count` by one. Reissuing from `RELEASED` requires the claim's payment state to be `PAID` or `NONE`, clears `check_number`, and deliberately leaves the claim `PAID` — the claim does not fall back to unpaid merely because a replacement instrument is being cut; it stays `PAID` until the reissued payout is released again. Reissuing from `VOIDED` requires the claim to be `APPROVED` on the adjudication axis and moves the claim's payment state `NONE → SCHEDULED`. The `RELEASED → REISSUE_PENDING → RELEASED` cycle may repeat.

Clearing records that a released check was actually cashed, moving the payout `RELEASED → CLEARED`, which is terminal and takes the payout permanently out of escheat range. Clearing applies only to a payout whose `method` is `CHECK`; a `VIRTUAL_CARD` payout is cleared implicitly when its card is fully spent and may not be cleared by hand, and the attempt is refused with `ERR_NOT_CHECK_PAYOUT` (HTTP 409).

**Virtual cards.** A card is created in `ISSUED` at the moment its payout is released, recording the `payout_id` it materialises, an `initial_balance_cents` and a `remaining_balance_cents` both equal to the payout's `net_cents`, an `issued_at` stamped from the logical clock, a `last_activity_at`, and an `expires_at` falling 365 days after `issued_at`. The claimant activates its own card, moving it `ISSUED → ACTIVATED`; activation requires the card to be `ISSUED`, its payout to be `RELEASED`, and the acting `X-User-ID` to equal the claim's `claimant_id`, and it stamps `last_activity_at` with the logical clock, restarting the card dormancy clock. Spending is permitted from `ACTIVATED` and from `PARTIALLY_USED`, requires the payout to still be `RELEASED`, and carries an `amount_cents` together with a `merchant_name`. The amount must be greater than zero and at most the card's `remaining_balance_cents`; anything outside that range is refused with `ERR_INSUFFICIENT_CARD_BALANCE` (HTTP 422). A spend strictly less than the remaining balance reduces `remaining_balance_cents` by the spent amount, stamps `last_activity_at`, and leaves the card in `PARTIALLY_USED` — arriving there from `ACTIVATED` on the first partial spend and staying there on subsequent ones. A spend exactly equal to the remaining balance drives `remaining_balance_cents` to zero and moves the card to the terminal `EXHAUSTED` state, which in turn moves its parent payout `RELEASED → CLEARED`. Activation or spending attempted from a state that does not declare it, or against a payout that is not `RELEASED`, is refused with `ERR_CARD_NOT_ACTIVE` (HTTP 409). Card listings may be narrowed by `payout_id` and by `status`.

### 3.9. Dormancy, Escheat and Reporting

Money that is disbursed but never collected cannot sit on the books forever; after a statutory dormancy period it must be surrendered to the claimant's state. A `ProgramAdmin` runs an escheat sweep over a program, and the sweep returns the records it created — an empty array when nothing was dormant, which is a successful outcome and never an error.

The sweep walks the program's payouts in a single pass ordered by `released_at` ascending and then by `created_at` ascending, never by identifier, and considers only payouts currently in `RELEASED`. Payouts in `CLEARED`, `VOIDED`, `PENDING` or `REISSUE_PENDING` are never swept. For a payout whose `method` is `CHECK`, the dormancy anchor is its `released_at`, the dormancy limit is 180 days, and the amount at stake is the payout's `net_cents`. For a payout whose `method` is `VIRTUAL_CARD`, the anchor is instead the `last_activity_at` of the card carrying that payout's identifier, the limit is 90 days, and the amount at stake is the card's `remaining_balance_cents`. In both cases the elapsed whole days from the anchor to the logical clock are computed, and the payout is dormant when that figure is at or above its limit — at exactly the limit it is already dormant.

Each dormant payout produces an **escheat record**, an immutable row naming the `payout_id` swept, the `program_id` funding it, the `amount_cents` surrendered, the `dormancy_days` measured, the `jurisdiction` receiving it, and a `swept_at` stamp taken from the logical clock. The `jurisdiction` is the `mailing_state` of the claim's claimant, falling back to the program's `escheat_jurisdiction` when that `mailing_state` is an empty string. Escheat record listings may be narrowed by `payout_id`, by `program_id` and by `jurisdiction`.

The sweep then cascades. The payout moves `RELEASED → ESCHEATED`, which is terminal, and the claim's payment state moves `PAID → ESCHEATED`, also terminal on that axis. Any virtual card of that payout — in `ISSUED`, `ACTIVATED` or `PARTIALLY_USED` — moves to the terminal `ESCHEATED` state with its `remaining_balance_cents` set to zero. A ledger row of type `ESCHEAT_REVERSAL` is appended whose `amount_cents` is the claim's `final_rebate_cents`, which simultaneously lowers `committed_cents` and raises `escheat_recovered_cents`. Note the deliberate asymmetry here and honour it: the escheat record captures the *net* amount actually surrendered (or the card's remaining balance), while the ledger reversal returns the *gross* committed amount, so that the program's `available_cents` comes back to exactly its pre-commitment value. Finally the budget position is recomputed, and a program sitting at `BUDGET_LOCKED` whose `utilization_pct` has now fallen below 1.0000 moves `BUDGET_LOCKED → ACTIVE`.

Reporting closes the loop. A program's reporting snapshot echoes its `program_id` and reports, over every claim whose offer belongs to that program: `claims_submitted` as the count of claims with a non-null `submitted_at`; `claims_approved`, `claims_denied` and `claims_revoked` as the counts of claims currently in `APPROVED`, `DENIED` and `REVOKED` respectively; `dealer_claim_count` and `consumer_claim_count` as the counts of those submitted claims whose claimant's `type` is `DEALER` and `CONSUMER` respectively; `approved_rebate_cents` as the sum of `final_rebate_cents` over the approved claims; and `escheated_cents` as the sum of `amount_cents` over every escheat record belonging to the program. The snapshot also carries the live `committed_cents`, `available_cents` and `utilization_pct` from the budget position. Claims in `DRAFT`, `WITHDRAWN` or `VOIDED` are excluded from every count, and they fall out of `claims_submitted` naturally because their `submitted_at` is null. Finally, `offer_breakdown` carries one row per offer of the program, ordered by `effective_start_date` ascending and then by `created_at` ascending — never by identifier — each row carrying that offer's `offer_id`, its `active_claim_count` and its own `approved_rebate_cents`. All counts and cent figures in the snapshot are integers and no rounding is applied.

The ledger itself is readable: individual entries may be fetched, and entry listings may be narrowed by `program_id`, by `claim_id` and by `entry_type`, which together make every movement of program money auditable after the fact.

---

## 4. Endpoint Definitions

All endpoints are mounted under `/api`, except the clock-driving test hook. Creating a new resource returns HTTP 201; every other successful operation, including state transitions, budget adjustments and reads, returns HTTP 200. Request and response payloads are not repeated here — §2 and §3 define what each operation consumes and what it does.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/api/programs` | Create a rebate program in `DRAFT` | ProgramAdmin |
| GET | `/api/programs/{id}` | Read a program including its live budget position | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst |
| GET | `/api/programs` | List programs | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst |
| POST | `/api/programs/{id}/activate` | Move a program from `DRAFT` to `ACTIVE` | ProgramAdmin |
| POST | `/api/programs/{id}/close` | Close a program and cascade-close its offers | ProgramAdmin |
| POST | `/api/programs/{id}/budget-adjustments` | Apply a signed budget delta under optimistic concurrency | ProgramAdmin |
| GET | `/api/programs/{id}/report` | Computed reporting snapshot for the program | ProgramAdmin, ClaimsProcessor |
| POST | `/api/programs/{id}/escheat-sweep` | Sweep dormant released payouts into escheat records | ProgramAdmin |
| POST | `/api/offers` | Create an offer under a program, in `DRAFT` | ProgramAdmin |
| GET | `/api/offers/{id}` | Read an offer | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| GET | `/api/offers` | List offers, filterable by parent program | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| POST | `/api/offers/{id}/publish` | Publish an offer from `DRAFT` or `SUSPENDED` | ProgramAdmin |
| POST | `/api/offers/{id}/suspend` | Suspend a published offer | ProgramAdmin |
| POST | `/api/offers/{id}/close` | Close an offer and start its grace period | ProgramAdmin |
| POST | `/api/claimants` | Register a dealer or consumer claimant | ProgramAdmin |
| GET | `/api/claimants/{id}` | Read a claimant | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| GET | `/api/claimants` | List claimants | ProgramAdmin, ClaimsProcessor, FraudAnalyst |
| POST | `/api/claimants/{id}/reinstate` | Return a `BLOCKED` claimant to `ACTIVE` once no case is open | FraudAnalyst |
| POST | `/api/claims` | Open a claim in `DRAFT` against a published offer | Dealer, Consumer |
| GET | `/api/claims/{id}` | Read a claim with both state dimensions and both rebate variants | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| GET | `/api/claims` | List claims, filterable by offer or claimant | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| POST | `/api/claims/{id}/receipts` | Attach a proof-of-purchase receipt to a `DRAFT` claim | Dealer, Consumer |
| GET | `/api/claims/{id}/receipts` | List the receipts of a claim | ProgramAdmin, ClaimsProcessor, FinanceOfficer, FraudAnalyst, Dealer, Consumer |
| GET | `/api/receipts/{id}` | Read a single receipt | ProgramAdmin, ClaimsProcessor, Dealer, Consumer |
| POST | `/api/receipts/{id}/validate` | Mark a receipt verified so it enters the final rebate variant | ClaimsProcessor |
| POST | `/api/claims/{id}/submit` | Submit a `DRAFT` claim for adjudication | Dealer, Consumer |
| POST | `/api/claims/{id}/withdraw` | Withdraw a `DRAFT` or `SUBMITTED` claim | Dealer, Consumer |
| POST | `/api/claims/{id}/review` | Take a submitted claim into review | ClaimsProcessor |
| POST | `/api/claims/{id}/approve` | Approve a claim under review, committing budget | ClaimsProcessor |
| POST | `/api/claims/{id}/deny` | Deny a claim under review | ClaimsProcessor |
| POST | `/api/claims/{id}/appeal` | Appeal a denial, cycling the claim back into review | Dealer, Consumer |
| POST | `/api/claims/{id}/payouts` | Schedule a disbursement for an approved claim, under optimistic concurrency | FinanceOfficer |
| GET | `/api/payouts/{id}` | Read a payout | ProgramAdmin, ClaimsProcessor, FinanceOfficer, Dealer, Consumer |
| GET | `/api/payouts` | List payouts, filterable by claim | ProgramAdmin, ClaimsProcessor, FinanceOfficer, Dealer, Consumer |
| POST | `/api/payouts/{id}/release` | Release a pending or reissued payout | FinanceOfficer |
| POST | `/api/payouts/{id}/clear` | Record that a released check was cashed | FinanceOfficer |
| POST | `/api/payouts/{id}/void` | Void a payout without releasing the underlying commitment | FinanceOfficer |
| POST | `/api/payouts/{id}/reissue` | Cycle a released or voided payout back to `REISSUE_PENDING` | FinanceOfficer |
| GET | `/api/virtual-cards/{id}` | Read a virtual card | ProgramAdmin, FinanceOfficer, Dealer, Consumer |
| GET | `/api/virtual-cards` | List virtual cards, filterable by payout | ProgramAdmin, FinanceOfficer, Dealer, Consumer |
| POST | `/api/virtual-cards/{id}/activate` | Activate an issued card | Dealer, Consumer |
| POST | `/api/virtual-cards/{id}/spend` | Spend against an activated card | Dealer, Consumer |
| GET | `/api/escheat-records/{id}` | Read an escheat record | ProgramAdmin, FinanceOfficer |
| GET | `/api/escheat-records` | List escheat records, filterable by payout or program | ProgramAdmin, FinanceOfficer |
| GET | `/api/budget-entries/{id}` | Read a single ledger entry | ProgramAdmin, ClaimsProcessor, FinanceOfficer |
| GET | `/api/budget-entries` | List ledger entries, filterable by program or claim | ProgramAdmin, ClaimsProcessor, FinanceOfficer |
| POST | `/api/fraud-cases` | Open a fraud case against a claimant | FraudAnalyst |
| GET | `/api/fraud-cases/{id}` | Read a fraud case | ProgramAdmin, FraudAnalyst |
| GET | `/api/fraud-cases` | List fraud cases, filterable by claimant or claim | ProgramAdmin, FraudAnalyst, ClaimsProcessor |
| POST | `/api/fraud-cases/{id}/transition` | Drive the cyclic fraud-case machine to a supplied `to_status` | FraudAnalyst |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to a supplied instant | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_CLAIM_OWNER` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_PROGRAM_NOT_FOUND` | 404 |
| `ERR_OFFER_NOT_FOUND` | 404 |
| `ERR_CLAIMANT_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_RECEIPT_NOT_FOUND` | 404 |
| `ERR_PAYOUT_NOT_FOUND` | 404 |
| `ERR_CARD_NOT_FOUND` | 404 |
| `ERR_FRAUD_CASE_NOT_FOUND` | 404 |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 |
| `ERR_OFFER_NOT_PUBLISHED` | 409 |
| `ERR_OFFER_WINDOW_OVERLAP` | 409 |
| `ERR_CLAIM_NOT_DRAFT` | 409 |
| `ERR_CLAIM_NOT_REVIEWABLE` | 409 |
| `ERR_CLAIM_ALREADY_TERMINAL` | 409 |
| `ERR_INVALID_TRANSITION` | 409 |
| `ERR_PAYOUT_NOT_RELEASABLE` | 409 |
| `ERR_PAYOUT_ALREADY_EXISTS` | 409 |
| `ERR_NOT_CHECK_PAYOUT` | 409 |
| `ERR_CARD_NOT_ACTIVE` | 409 |
| `ERR_CLAIMANT_BLOCKED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 |
| `ERR_PURCHASE_OUTSIDE_OFFER_WINDOW` | 422 |
| `ERR_OFFER_WINDOW_CLOSED` | 422 |
| `ERR_DUPLICATE_RECEIPT_SERIAL` | 409 |
| `ERR_CHANNEL_MISMATCH` | 422 |
| `ERR_CLAIM_CAP_EXCEEDED` | 409 |
| `ERR_NO_VALIDATED_RECEIPT` | 422 |
| `ERR_RECEIPT_LIMIT_EXCEEDED` | 422 |
| `ERR_APPEAL_WINDOW_EXPIRED` | 422 |
| `ERR_APPEAL_LIMIT_REACHED` | 409 |
| `ERR_BUDGET_EXCEEDED` | 409 |
| `ERR_BUDGET_ADJUSTMENT_INVALID` | 422 |
| `ERR_BELOW_MIN_PAYOUT` | 422 |
| `ERR_INSUFFICIENT_CARD_BALANCE` | 422 |
| `ERR_STALE_CLAIM_VERSION` | 412 |
| `ERR_STALE_PROGRAM_VERSION` | 412 |

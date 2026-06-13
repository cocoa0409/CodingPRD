# Marketplace Seller Payouts API — Product Requirements Document

## 1. Introduction

This document specifies the back-office financial system that an online marketplace operates to move money from buyers to its third-party sellers. From the moment a seller registers, the platform must shepherd them through identity verification (KYC) and tax-document collection (a W-9), price every order they fulfil against a published fee schedule, hold a portion of their proceeds in a rolling reserve calibrated to their risk, mature those proceeds on a delay, and finally disburse what remains to a verified bank or wallet. Layered on top of this happy path are the messy realities of commerce: buyers request refunds, card issuers raise chargebacks, claimants file A-to-Z disputes, and any of these can claw money back from a seller after the platform has already recognised it. Every such movement must be recorded as an immutable ledger posting so that, at year end, the platform can issue an accurate 1099-K and a seller can be handed a defensible monthly balance statement.

The system therefore behaves as a double-entry ledger with a compliance overlay. Three classes of operator interact with it under strict segregation of duties: a compliance reviewer who vouches for a seller's identity, a finance operator who handles the money, and the seller themselves who can act only on their own records. Because balances, reserves, and order statuses all shift atomically as a single request cascades, and because two finance operators can legitimately attempt overlapping payout releases, the design leans heavily on derived-field reconciliation and optimistic concurrency. The remainder of this document fixes the API contract precisely (Section 2) and then describes the business workflows in narrative form (Section 3), with the endpoint and error catalogues consolidated at the end (Sections 4 and 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing or empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing; a present `X-User-Role` whose value is not one of the three recognised roles below is likewise rejected with `ERR_UNAUTHENTICATED` (HTTP 401), not `ERR_UNAUTHORIZED`. When the headers are present and the role is recognised but that role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `Seller`, `PlatformReviewer`, and `PlatformFinance`.

When `X-User-Role` is `Seller`, `X-User-ID` is the `id` of the acting seller — that is, the identifier is entity-backed by a `Seller` record. Ownership checks on any resource that references a seller compare that resource's `seller_id` to `X-User-ID`; a seller attempting to read or act on a resource whose `seller_id` differs from their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). This ownership rule governs the seller-scoped endpoints — a seller's own payout methods, refunds, representments, dispute responses, and read access to their own orders, payouts, reserves, ledger entries, tax forms, and balance statements.

When `X-User-Role` is `PlatformReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it on a seller's `kyc_reviewer_id` field when that reviewer decides KYC, but it is never compared to any entity's `id`. Likewise, when `X-User-Role` is `PlatformFinance`, `X-User-ID` is an opaque operator identifier; the server records it on a payout's `finance_user_id` field when that operator releases the payout, but otherwise does not match it against any entity `id`. These two recorded identifiers underpin the platform's segregation-of-duties control: the `PlatformFinance` operator who releases a seller's payout may not be the same person (same `X-User-ID`) who earlier approved that seller's KYC. A release that violates this separation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. The `offset` defaults to 0 and may not be negative. A request whose `limit` falls outside the range 1 through 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400). List results are ordered by `created_at` ascending. The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the number of records matching the filter before pagination and `has_more` indicates whether records remain beyond the current page.

### 2.4. Common Resource Properties

Every resource carries a server-minted `id` — a UUID with no type prefix — and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format) and an integer `version` that begins at 1 and increments by 1 on every mutation that changes the resource. Two resource types are append-only records of fact and therefore carry only `id` and `created_at`, with no `updated_at` and no `version`: a ledger entry and a balance statement. A ledger entry, once posted, is never edited in place; even a reversal is expressed as a new entry rather than a mutation of the old one (with the one documented exception that an original credit's `hold_state` flips to `REVERSED`, described in Section 3). A balance statement is a point-in-time snapshot and is likewise immutable once generated.

### 2.5. Monetary Values, Precision, and Rounding

All monetary amounts are expressed as integer cents; the API never transmits fractional currency. Wherever a rate or percentage produces a fractional cent, the result is rounded half-up to the nearest whole cent — that is, a value whose fractional part is exactly one-half rounds away from zero. The order-pricing calculation rounds each fee component to whole cents individually before any of them are summed (round-per-component, in the pinned order described in Section 3), rather than summing first and rounding once. The reserve calculation rounds only the withheld portion half-up; the disbursed amount is then taken as the exact remainder so that withheld plus disbursed equals the available pool with no rounding drift. The risk score, by contrast, is rounded exactly once, at the very end, after all weighted factors are summed. The flat chargeback fee and full-gross reversals are already whole-cent integers and require no rounding.

### 2.6. Reserve, Balance, and Ledger Reconciliation

The platform maintains, for each seller, three derived balances that are recomputed on every ledger posting and on every maturation. The `available_balance_cents` is the sum of that seller's ledger-entry amounts whose `hold_state` is `AVAILABLE`, less the seller's current `reserve_held_cents`; it may legitimately be negative. The `pending_balance_cents` is the sum of ledger-entry amounts whose `hold_state` is `PENDING` — proceeds that have not yet matured. The `reserve_held_cents` mirrors the seller's currently open reserve. Every ledger entry records a `seller_id`, a `source_type` describing the kind of posting, a `source_id` pointing at the originating record, a signed `amount_cents` (positive credits the seller, negative debits), a `hold_state`, and a human-readable `memo`. Because these balances are pure functions of the ledger, the implementation must reconcile them — recompute and persist them — inside the same atomic request that posts any entry.

### 2.7. Cascading Side Effects and Hierarchical Consistency

The marketplace's consistency model is immediate: when a single request triggers a chain of effects — a ledger posting, a balance recompute, a reserve adjustment, an order-status flip, a seller-activation recompute — all of those effects land atomically within that one request, or none of them do. Several operations deliberately mutate more than one entity. Releasing a payout, for example, posts ledger entries, withholds a reserve, flips every swept order's settlement status, advances the seller's `version`, and stamps the operator's identity; reversing a released payout undoes each of those in compensating fashion. Each such cascade is enumerated in full in Section 3, because the secondary effects — not just the primary status change — are part of the contract. Whenever a mutation changes a resource that carries `version` and `updated_at`, those two fields advance together as part of the same atomic write.

### 2.8. Nested and Reverse-Reachability Retrieval

Resources are addressed as flat, top-level collections; there is no single nesting prefix. Cross-references between aggregates travel as foreign-key fields in request bodies and as filter parameters on list endpoints rather than as nested URL segments. A handful of read paths are nested under a specific seller for reverse reachability — listing a seller's ledger entries or a seller's reserves, for instance. For any path that carries a resource identifier, path parameters are validated left to right: the seller named first in the path must exist before any further segment is considered, and a reference to a non-existent resource anywhere in the path or body yields `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Optimistic Concurrency on Payout Release

Releasing a payout is the one operation guarded by optimistic concurrency control, because it sweeps every available order into one disbursement and advances the seller's `version`. A release request must carry `expected_seller_version`, the integer `version` of the target seller that the client last observed. If another writer has advanced the seller's `version` since the client read it — for instance, an earlier release that already swept orders, or a clawback that re-reconciled balances — then the release's view of `available_balance_cents` is stale, and the request is rejected with `ERR_STALE_SELLER_VERSION` (HTTP 412). The rejection is framed as a stale-version mismatch rather than a state error precisely because, under marketplace semantics, a second release could legitimately sweep orders that became available in the interim; the client must re-read the seller and retry against the current `version`. No other endpoint accepts or requires a version field.

### 2.10. Segregation of Duties and Operator Standing

Two compliance principles cut across the money-movement workflows. First, the reviewer who vouches for a seller's identity and the finance operator who pays that seller out must be different people: the platform records the approving reviewer in `kyc_reviewer_id` and refuses a payout release whose acting `X-User-ID` equals that recorded reviewer, returning `ERR_SEGREGATION_OF_DUTIES`. Second, money only leaves the platform for a seller in good standing: a payout may be released only while the seller's `account_status` is `ACTIVE`. A suspended, onboarding, or closed seller cannot have funds disbursed, and an attempted release is rejected with `ERR_SELLER_NOT_ACTIVE` (HTTP 409). A suspended seller continues to accrue ledger postings; suspension freezes disbursement, not accounting.

### 2.11. Validation Ordering

When several checks could fail on a single request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication is checked first: the presence of `X-User-ID` and `X-User-Role` (`ERR_UNAUTHENTICATED`). Then role authorization against the operation (`ERR_UNAUTHORIZED`). Then, on a payout release only, the segregation-of-duties separation (`ERR_SEGREGATION_OF_DUTIES`). Then existence of every path- and body-referenced resource, left to right (`ERR_NOT_FOUND`). Then, for a seller acting on a resource, ownership (`ERR_NOT_RESOURCE_OWNER`). Then whether the target resource is in a state from which the requested transition is defined (`ERR_INVALID_STATE`). After these cross-cutting gates, operation-specific business rules apply, themselves ordered: for a payout release, seller-active standing (`ERR_SELLER_NOT_ACTIVE`) precedes the stale-version check (`ERR_STALE_SELLER_VERSION`), which precedes the verified-default-method check (`ERR_NO_VERIFIED_PAYOUT_METHOD`), which in turn precedes the nothing-to-pay floor (`ERR_NOTHING_TO_PAY`). Body well-formedness — required fields present, enums in range, amounts at least 1 (`ERR_INVALID_REQUEST`) — is the lowest-priority catch-all. The per-operation business checks (refund ceiling, already-clawed guard, representment window, dispute-round bound, micro-deposit match, open-balance close guard, 1099-K threshold gate) are described alongside the workflows they protect in Section 3.

## 3. Business Logic & Workflows

### 3.1. Seller Onboarding: Identity, Tax Documents, and Activation

A `PlatformReviewer` registers a seller by supplying the seller's `legal_name`, `email`, `country_code`, `tax_classification`, and `tin_last4`. The `email` must be non-empty and unique across all sellers. The `country_code` is one of `US`, `CA`, `GB`, `DE`, or `AU`; the `tax_classification`, taken from the W-9, is one of `INDIVIDUAL`, `SOLE_PROP`, `C_CORP`, `S_CORP`, `LLC`, or `PARTNERSHIP`; and `tin_last4` is exactly four digits, the last four of the taxpayer identification number. A newly registered seller starts with `kyc_status` of `PENDING`, `w9_status` of `NOT_SUBMITTED`, and an `account_status` of `ONBOARDING`. Its computed standing fields — `risk_tier` (`STANDARD`), `seller_risk_score` (0), `available_balance_cents`, `pending_balance_cents`, `reserve_held_cents`, `ytd_gross_cents`, and `ytd_transaction_count` (all 0) — and its `kyc_reviewer_id` (unset) all begin at their defaults.

Onboarding proceeds along two parallel tracks that must both complete. On the identity track, the seller first submits their KYC documents, which advances `kyc_status` from `PENDING` to `IN_REVIEW`. A reviewer then renders a decision supplying a `decision` value; an approval sets `kyc_status` to `APPROVED` and records the acting reviewer's `X-User-ID` into `kyc_reviewer_id`, while a rejection sets `kyc_status` to `REJECTED`. Approval requires that the seller's `kyc_status` is currently `IN_REVIEW`. Critically, KYC approval alone does not activate the account; the system recomputes `account_status`, which stays `ONBOARDING` until the W-9 is also approved and a verified payout method exists. On the tax track, the seller submits their W-9, moving `w9_status` from `NOT_SUBMITTED` to `SUBMITTED`; a reviewer then approves it. W-9 approval is permitted only when `kyc_status` is already `APPROVED`, `w9_status` is `SUBMITTED`, and the seller has at least one payout method whose `verification_status` is `VERIFIED`. On approval, `w9_status` becomes `APPROVED`.

The `account_status` is the derived posture that gates all child money operations, and it becomes `ACTIVE` precisely when all three onboarding gates are satisfied at once: `kyc_status` is `APPROVED`, `w9_status` is `APPROVED`, and a `VERIFIED` payout method exists. Whichever of the three gates is satisfied last is the one that flips the seller to `ACTIVE` — so if W-9 approval is the final gate, the recompute at W-9 approval moves the seller from `ONBOARDING` to `ACTIVE`; and as a cross-entity side effect of that activation, the platform opens the seller's initial reserve row, pinning `reserve_pct_applied` from the seller's current `risk_tier`. Equally, if a payout method's verification is the last gate to fall while KYC and W-9 are already approved, the verification itself recomputes the seller to `ACTIVE`.

### 3.2. Posture Transitions: Suspend, Reinstate, and Close

A reviewer can suspend an `ACTIVE` seller, moving `account_status` to `SUSPENDED`; this freezes payout release — no payout for that seller may be disbursed while suspended — but the seller keeps accruing ledger postings normally. A `SUSPENDED` seller can be reinstated back to `ACTIVE`. Closing a seller is terminal and is permitted from either `ACTIVE` or `SUSPENDED`, but only when the seller has no order in `settlement_status` `PENDING` or `AVAILABLE` — every order must already be `PAID`, or the seller must have no orders at all. An attempt to close a seller while any order's settlement is still `PENDING` or `AVAILABLE` is rejected with `ERR_OPEN_BALANCE_BLOCKS_CLOSE` (HTTP 409). When the close succeeds, `account_status` becomes `CLOSED` and, as a cascade, any open reserve is released: the reserve row moves from `OPEN` to `RELEASED` and a `RESERVE_RELEASE` ledger entry is posted. All four posture transitions are driven by a `PlatformReviewer`; requesting any of them from a state where the transition is undefined yields `ERR_INVALID_STATE`.

### 3.3. Payout Methods and Micro-Deposit Verification

A seller registers a disbursement destination by providing its `seller_id`, a `method_type` of `ACH`, `WIRE`, or `PAYPAL`, the `account_last4` (exactly four digits), and a settlement `currency` of `USD`, `CAD`, `GBP`, or `EUR`. The new method begins `UNVERIFIED`, and the server issues a `micro_deposit_code` — a six-digit numeric string — that the seller must later echo back. To verify, the seller submits a `micro_deposit_code`; if it matches the server-issued code and the method is currently `UNVERIFIED`, `verification_status` becomes `VERIFIED`. Verification then recomputes which of the seller's methods is the default: `is_default` is true for exactly one `VERIFIED` method per seller — the latest `VERIFIED` method by `created_at` ascending, last wins — and payouts always disburse to that default. If verifying this method completes the seller's third onboarding gate while KYC and W-9 are already approved, the same request recomputes the seller's `account_status` to `ACTIVE`.

A wrong code does not immediately fail the method. Only when a submitted `micro_deposit_code` does not match and the method already has two prior failed attempts does the third wrong attempt move `verification_status` to `FAILED`, which is terminal. Any non-matching submission is rejected with `ERR_BAD_MICRO_DEPOSIT_CODE` (HTTP 422); the transition to `FAILED` occurs on that third failure. A seller may read the `micro_deposit_code` on their own method through the fetch endpoint, since they own the record.

### 3.4. Fee Schedules and Order Pricing

Pricing is governed by per-category fee schedules created by a `PlatformFinance` operator. A schedule names a `category` (`ELECTRONICS`, `APPAREL`, `MEDIA`, `GROCERY`, or `HANDMADE`) and carries: `commission_bps`, the commission rate in basis points from 0 to 5000; `fixed_fee_cents`, a per-order flat platform fee of at least 0; `payment_processing_bps`, a processing rate in basis points from 0 to 1000; `payment_processing_fixed_cents`, a fixed processing fee of at least 0; three rolling-reserve percentages `reserve_pct_standard`, `reserve_pct_elevated`, and `reserve_pct_high`, each a whole percent from 0 to 100; and `maturation_days`, from 0 to 90, the number of days from settlement until proceeds mature. For each category, exactly one schedule is active — `is_active` is true for the latest schedule by `created_at` ascending, last wins — and every new order prices against the active schedule for its category, superseding any prior one.

When a finance operator creates an order, they supply the `seller_id`, the `category`, and the buyer-paid `gross_amount_cents` (at least 1 cent, item plus shipping). The platform pins the active schedule into the order's `fee_schedule_id` and prices the order immediately; if no active fee schedule exists for the supplied `category`, the order cannot be priced and the request is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The commission, stored in `commission_cents`, is the gross multiplied by the schedule's commission basis points divided by ten thousand, rounded half-up to whole cents. The `platform_fee_cents` is copied directly from the schedule's fixed fee. The `processing_fee_cents` is the gross multiplied by the processing basis points divided by ten thousand and rounded half-up, then added to the fixed processing fee. Each of these three components is rounded to whole cents before any summation. The provisional `net_earnings_cents` is then the gross minus the commission, minus the platform fee, minus the processing fee — with no refund yet considered. Order creation posts an `ORDER_PROCEEDS` ledger entry for that net amount in `PENDING` hold state, sets `settlement_status` to `PENDING` with `clawback_status` `NONE`, stamps `settled_at` with the current clock time, and reconciles the seller's balances and recomputes the risk score. The order's `refunded_amount_cents`, `matured_at`, and the final variant of `net_earnings_cents` are not yet determined.

### 3.5. Maturation: Pending Proceeds Becoming Available

Proceeds do not become payable the instant an order settles. A maturation sweep runs when the logical clock is advanced. An order matures — its `settlement_status` flips from `PENDING` to `AVAILABLE` — only when its settlement is still `PENDING`, the current UTC time is at or after the order's `settled_at` plus the active schedule's `maturation_days`, and the order has not been clawed (`clawback_status` is `NONE`, since a clawed order does not mature normally). At maturation, the platform recomputes `net_earnings_cents` in its final form, flips the order's `ORDER_PROCEEDS` ledger entry from `PENDING` to `AVAILABLE`, stamps `matured_at` with the current time, and reconciles `available_balance_cents` and `pending_balance_cents`.

The final earnings figure differs from the provisional one only by refunds. The final `net_earnings_cents` is the provisional net minus the seller's net share of any refund, where that share is the cumulative `refunded_amount_cents` minus the commission proportional to it — specifically the refunded amount minus (the refunded amount multiplied by the order's pinned commission basis points divided by ten thousand, rounded half-up). Processing and platform fees are never returned, so provisional and final differ by exactly the refunded gross less its proportional commission. If no refund touched the order, provisional and final coincide.

### 3.6. Refunds and Proportional Clawback

A refund can be created by a finance operator or by the seller, against a given `order_id`, with a `refund_amount_cents` of at least 1 (it may be partial) and a `reason` of `BUYER_REMORSE`, `NOT_AS_DESCRIBED`, `DAMAGED`, or `NOT_RECEIVED`. The refund copies its `seller_id` from the order and begins in `REQUESTED` status. A `REQUESTED` refund may be voided by a finance operator, moving `refund_status` to `VOIDED` with no ledger effect.

Applying a refund is where money moves, and it is a finance-operator action. It requires that the refund is `REQUESTED`, the linked order has not already been clawed (`clawback_status` is `NONE`), the refund amount does not exceed the order's remaining unrefunded gross (`gross_amount_cents` minus `refunded_amount_cents`), and the order's settlement is `PENDING` or `AVAILABLE`. A refund whose linked order's settlement is neither `PENDING` nor `AVAILABLE` is rejected with `ERR_INVALID_STATE` (HTTP 409), evaluated before the amount and clawback checks; a refund that would exceed the remaining unrefunded gross is rejected with `ERR_REFUND_EXCEEDS_REMAINING` (HTTP 422), and an attempt to apply against an already-clawed order is rejected with `ERR_ORDER_ALREADY_CLAWED` (HTTP 409), the ceiling check preceding the already-clawed guard. When the refund applies, the platform computes, in pinned order, the `commission_returned_cents` first — the refund amount multiplied by the order's commission basis points divided by ten thousand, rounded half-up — and then the `clawback_cents` as the refund amount minus that returned commission. A `REFUND_CLAWBACK` ledger entry is posted for the negative of the clawback amount, in the same `hold_state` bucket the order's proceeds currently occupy — `AVAILABLE` if the order has matured (settlement `AVAILABLE`), otherwise `PENDING` — so the debit nets against the original credit; if the refund is full (the refund amount equals the order's full `gross_amount_cents`), the order's original `ORDER_PROCEEDS` entry is marked `REVERSED`. The order's `clawback_status` moves from `NONE` to `REFUND_CLAWED`, its `refunded_amount_cents` increases and its `net_earnings_cents` is recomputed, the refund's `refund_status` becomes `APPLIED`, and the seller's balances and risk score are reconciled. The intuition: the platform returns to the seller only the commission proportional to the refunded fraction, keeping its processing and platform fees.

### 3.7. Chargebacks: Fees, Representment, and Full-Gross Reversal

A chargeback is harsher than a refund. A finance operator records an incoming chargeback against an `order_id`; the chargeback copies its `seller_id`, starts in `RECEIVED`, and immediately levies a flat, non-refundable fee. That `dispute_fee_cents` is fixed at fifteen hundred cents and is posted at once as a negative `CHARGEBACK_FEE` ledger entry in the `AVAILABLE` hold state, after which the seller's balances and risk score are reconciled and the `representment_due_at` deadline is set to seven days after the moment of receipt (the current clock time plus seven days). The seller may contest by submitting representment evidence, which moves `chargeback_status` from `RECEIVED` to `REPRESENTED` — but only if the current time is at or before `representment_due_at`. Representment submitted after that deadline is rejected with `ERR_REPRESENTMENT_WINDOW_CLOSED` (HTTP 422).

The issuer's decision, supplied as an `outcome` of `WON` or `LOST` on the decision request (any other value yields `ERR_INVALID_REQUEST`), resolves the chargeback. From `REPRESENTED`, an `outcome` of `WON` (in the seller's favour) moves it to `WON`: any previously posted full-gross clawback is reversed, but the `dispute_fee_cents` is not refunded. An `outcome` of `LOST` (against the seller) from `REPRESENTED` moves it to `LOST`. A chargeback can also go straight from `RECEIVED` to `LOST` when the representment deadline has passed (the current time is after `representment_due_at`) and no representment was filed. Either way of reaching `LOST` triggers the full reversal: the platform computes `clawback_cents` as the order's entire `gross_amount_cents` — no commission proportionality, unlike a refund — and posts a negative `CHARGEBACK_CLAWBACK` ledger entry for that full gross in the same `hold_state` bucket the order's proceeds occupy (`AVAILABLE` if matured, otherwise `PENDING`), drives the order's `clawback_status` from `NONE` to `CHARGEBACK_CLAWED`, and reconciles the seller's balances. This full-gross clawback is posted only if the order has not already been clawed (`clawback_status` is `NONE`). The total seller debit on a lost chargeback is therefore the fixed dispute fee plus the full gross, and the fee is never recovered even if a later representment had won. A representment, decision, or move out of an undefined state yields `ERR_INVALID_STATE`.

### 3.8. A-to-Z Disputes: A Cyclic Claim Process

An A-to-Z claim is filed by a reviewer or a finance operator against an `order_id`, naming a `claim_type` of `ITEM_NOT_RECEIVED`, `ITEM_NOT_AS_DESCRIBED`, or `RETURN_NOT_REFUNDED`. The dispute copies its `seller_id`, starts in `FILED` with `response_round` at 0, and its `granted_amount_cents` unset. A reviewer opens the claim for review, moving `dispute_status` from `FILED` to `UNDER_REVIEW`. The seller may then respond, which moves the status from `UNDER_REVIEW` to `SELLER_RESPONDED` and increments `response_round` by 1.

The process is deliberately cyclic. From `SELLER_RESPONDED`, a reviewer may request more information, moving the status back to `UNDER_REVIEW` — but only while `response_round` is below 3. Once `response_round` has reached 3, the cycle is exhausted and a further open-review request is rejected with `ERR_DISPUTE_ROUND_EXHAUSTED` (HTTP 422). Resolution comes from a reviewer's decision, whose `outcome` names the winner — `GRANTED` or `BUYER` for a buyer win, `DENIED` or `SELLER` for a seller win, any other value yielding `ERR_INVALID_REQUEST`. From `UNDER_REVIEW`, an `outcome` for the buyer moves the dispute to `GRANTED`: the platform sets `granted_amount_cents` to the order's full `gross_amount_cents`, and if the order has not already been clawed, posts a negative full-gross `REFUND_CLAWBACK` ledger entry in the same `hold_state` bucket the order's proceeds occupy (`AVAILABLE` if matured, otherwise `PENDING`), drives the order's `clawback_status` from `NONE` to `REFUND_CLAWED`, and reconciles the seller's balances. From `SELLER_RESPONDED`, an `outcome` for the seller moves the dispute to `DENIED` with no ledger posting. `GRANTED` and `DENIED` are terminal.

### 3.9. Payouts: Scheduling, Release, Failure, and Reversal

Disbursing money is a two-step finance workflow. First, a finance operator schedules a payout for a `seller_id`; the payout begins `SCHEDULED`, snapshots the seller's `available_balance_cents` into `gross_available_cents` as a pre-reserve view, and computes the sweep set `order_ids` — every order with `settlement_status` `AVAILABLE` and `clawback_status` `NONE`, in `created_at` ascending order. No money moves yet. The `payout_method_id`, `reserve_withheld_cents`, `payout_amount_cents`, and `finance_user_id` are filled in only at release.

Releasing the scheduled payout is the heavily-guarded step. The payout must be `SCHEDULED`; the seller's `account_status` must be `ACTIVE` (else `ERR_SELLER_NOT_ACTIVE`); the request's `expected_seller_version` must match the seller's current `version` (else `ERR_STALE_SELLER_VERSION`, as described in Section 2.9); the acting `PlatformFinance` `X-User-ID` must differ from the seller's `kyc_reviewer_id` (else `ERR_SEGREGATION_OF_DUTIES`); and the seller must have a `VERIFIED` default payout method (else `ERR_NO_VERIFIED_PAYOUT_METHOD`, HTTP 422). The release then runs a reserve waterfall over the available pool. The `gross_available_cents` is the sum of the seller's ledger-entry amounts in `AVAILABLE` hold state, already net of any available clawback debits. If that pool is not strictly above zero, the release is rejected with `ERR_NOTHING_TO_PAY` (HTTP 422). Otherwise the `reserve_withheld_cents` is the available pool multiplied by the applicable reserve percentage divided by one hundred, rounded half-up; the percentage is selected from the active fee schedule by the seller's `risk_tier` — `reserve_pct_standard` for a `STANDARD` seller, `reserve_pct_elevated` for an `ELEVATED` seller, `reserve_pct_high` for a `HIGH` seller. The `payout_amount_cents` is then the exact remainder, the available pool minus the withheld reserve.

On a successful release, the platform sets the `payout_method_id` to the seller's default verified method, posts a negative `PAYOUT` ledger entry in the `AVAILABLE` hold state for the disbursed amount, and — only when the withheld reserve is strictly above zero — posts a negative `RESERVE_HOLD` ledger entry for the withheld reserve and opens a fresh `OPEN` reserve row (it always opens a new row rather than mutating an existing one) holding that amount with `reserve_pct_applied` pinned from the seller's current `risk_tier`. The `RESERVE_HOLD` (and the later `RESERVE_RELEASE`) ledger entries are audit records posted in the `REVERSED` hold state so they never enter the `AVAILABLE` or `PENDING` ledger sums; the reserve's effect on `available_balance_cents` flows solely through `reserve_held_cents`, which mirrors the open reserve's `held_amount_cents`. The release also flips every swept order's `settlement_status` from `AVAILABLE` to `PAID`, increments the seller's `version` by 1, reconciles the seller's balances, and records the acting operator's `X-User-ID` into `finance_user_id`. A scheduled payout that never disburses can be marked failed by a finance operator, moving `payout_status` from `SCHEDULED` to `FAILED` with no ledger effect. A `RELEASED` payout whose disbursement is later clawed back by the bank can be reversed: the platform posts a positive `PAYOUT` reversal ledger entry in the `AVAILABLE` hold state restoring the available balance, flips the swept orders' `settlement_status` from `PAID` back to `AVAILABLE` as a compensating cascade, releases this payout's reserve — the `OPEN` reserve row whose `held_amount_cents` equals the payout's `reserve_withheld_cents` — by posting a `RESERVE_RELEASE` audit entry, zeroing that reserve's `held_amount_cents`, stamping `released_at`, and moving the reserve from `OPEN` to `RELEASED`, and reconciles balances such that the net effect on `available_balance_cents` is zero.

### 3.10. Rolling Reserves and Risk Tiering

A reserve withholds a percentage of a seller's proceeds against future clawbacks. A reserve row records its `seller_id`, a `reserve_status` of `OPEN` while withholding or `RELEASED` once the hold window elapses, the `held_amount_cents` currently withheld (zeroed when the reserve is released), the `reserve_pct_applied` pinned from the seller's `risk_tier` at the moment the reserve opens, a `release_due_at` clock timestamp at or after which the reserve may be released, and a `released_at` recorded when it is. In this implementation `release_due_at` is left null on every reserve that is opened (both the initial reserve and any reserve a payout withholds into), so the clock-advance sweep below — which acts only on `OPEN` reserves whose `release_due_at` is set and has elapsed — never auto-releases a reserve in practice; reserves move from `OPEN` to `RELEASED` only through the seller-close cascade (Section 3.2) and the payout-reversal cascade (Section 3.9). The clock-advance sweep that matures orders also attempts to release reserves whose hold window has elapsed. The percentage applied depends on the seller's risk band, and that band is itself derived from the seller's risk score.

The `seller_risk_score` is a weighted multi-factor score on a 0-to-100 scale, recomputed on every order, refund, chargeback, or dispute posting that affects the seller. It blends three rates, each a count divided by the greater of 1 and the seller's order count: the chargeback rate counts the seller's chargebacks in `RECEIVED`, `REPRESENTED`, or `LOST` status; the refund rate counts the seller's `APPLIED` refunds; the dispute rate counts the seller's `GRANTED` disputes. The raw score is one hundred multiplied by the sum of the chargeback rate weighted by sixty hundredths, the refund rate weighted by twenty-five hundredths, and the dispute rate weighted by fifteen hundredths. The score is the smaller of 100 and that raw value, rounded half-up exactly once at the end. The `risk_tier` follows from the score by threshold: a score below 20 is `STANDARD`; a score from 20 up to but not including 50 is `ELEVATED`; a score of 50 or above is `HIGH`. The tier in turn selects which reserve percentage the next payout withholds, as described in Section 3.9.

### 3.11. Tax Reporting: The 1099-K

At year end the platform issues a 1099-K. A finance operator first creates a draft form naming the `seller_id` and the `tax_year` (a calendar year from 2020 to 2030); the form begins in `DRAFT`. Issuing the form computes its figures and moves `form_status` from `DRAFT` to `ISSUED`. The `gross_reported_cents` is the sum of `gross_amount_cents` over the seller's orders whose `settled_at` year equals the `tax_year` and whose `settlement_status` is `AVAILABLE` or `PAID`; refunds and chargebacks do not reduce this gross, per the IRS gross-volume rule. The `transaction_count` is the count of those same orders. The form's `threshold_basis` is then selected by inclusive thresholds: if the reported gross is at least five hundred thousand cents (five thousand dollars), the basis is `FEDERAL_5000`; otherwise, if the reported gross is at least two million cents (twenty thousand dollars) and the transaction count is at least 200, the basis is `LEGACY_20K_200`; otherwise the basis is `NONE`.

Issuing a form whose computed `threshold_basis` is `NONE` is a below-threshold form and is blocked unless the request supplies `force` as true; a blocked issuance returns `ERR_BELOW_1099K_THRESHOLD` (HTTP 422). With `force` true, the form issues anyway with its basis recorded as `NONE`. An `ISSUED` form can later be corrected: correction recomputes `gross_reported_cents`, `transaction_count`, and `threshold_basis` from the current settled orders and moves `form_status` to `CORRECTED` (a below-threshold result does not block a correction). The seller's running `ytd_gross_cents` and `ytd_transaction_count` track this same year-to-date settled volume on the seller record for threshold testing.

### 3.12. Balance Statements and the Logical Clock

A monthly balance statement can be generated by any of the three roles (a seller only for itself) by supplying a `seller_id`, a `period_year` (2020 to 2030), and a `period_month` (1 to 12). The statement is computed entirely from the seller's ledger entries within that period: `opening_balance_cents` is the available balance at the start of the period (the sum of prior `AVAILABLE` postings), `closing_balance_cents` is the available balance at the period's end, `total_credits_cents` is the sum of positive ledger amounts posted in the period, `total_debits_cents` is the sum of negative ledger amounts posted in the period, and `total_payouts_cents` is the sum of `PAYOUT`-source debits posted in the period.

Because maturation, representment windows, and reserve release all hinge on time, the platform runs on a logical clock that operators can drive in tests. A finance operator or reviewer can set the simulated current UTC to a supplied `to_iso8601` instant, or advance the clock to a supplied `to_iso8601` instant and, in the same call, run the maturation sweep (maturing every eligible order with its final-net recompute and ledger flip) and the reserve-release sweep (releasing every due reserve), then reconcile balances.

## 4. Endpoint Definitions

All endpoints return their result inside the standard envelope of Section 2.2. Endpoints that create a new resource respond with HTTP 201; endpoints that fetch, list, or modify an existing resource respond with HTTP 200. The request body, response payload, and side effects of each endpoint are not restated here — they are specified in the Section 3 narratives — and the table below names only the HTTP contract.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/sellers` | Register a seller (KYC `PENDING`, W-9 `NOT_SUBMITTED`). | PlatformReviewer |
| GET | `/sellers/{id}` | Fetch a seller with all computed balances. | PlatformReviewer, PlatformFinance, Seller |
| GET | `/sellers` | List sellers (filter by account/KYC status). | PlatformReviewer, PlatformFinance |
| POST | `/sellers/{id}/kyc/submit` | Submit KYC documents (PENDING→IN_REVIEW). | Seller |
| POST | `/sellers/{id}/kyc/decision` | Decide KYC; records the reviewer. | PlatformReviewer |
| POST | `/sellers/{id}/w9/submit` | Submit the W-9 (NOT_SUBMITTED→SUBMITTED). | Seller |
| POST | `/sellers/{id}/w9/approve` | Approve the W-9; may activate the seller. | PlatformReviewer |
| POST | `/sellers/{id}/suspend` | Suspend an active seller. | PlatformReviewer |
| POST | `/sellers/{id}/reinstate` | Reinstate a suspended seller. | PlatformReviewer |
| POST | `/sellers/{id}/close` | Close a seller; blocked on open balances. | PlatformReviewer |
| GET | `/sellers/{id}/ledger-entries` | List a seller's ledger entries. | PlatformReviewer, PlatformFinance, Seller |
| GET | `/sellers/{id}/reserves` | List a seller's reserves. | PlatformReviewer, PlatformFinance, Seller |
| GET | `/ledger-entries/{id}` | Fetch a single ledger entry. | PlatformReviewer, PlatformFinance, Seller |
| GET | `/ledger-entries` | List ledger entries (filter by source/seller). | PlatformReviewer, PlatformFinance, Seller |
| POST | `/payout-methods` | Add a payout method; issues a micro-deposit code. | Seller |
| GET | `/payout-methods/{id}` | Fetch a payout method. | Seller, PlatformReviewer, PlatformFinance |
| GET | `/payout-methods` | List payout methods (filter by seller). | Seller, PlatformReviewer, PlatformFinance |
| POST | `/payout-methods/{id}/verify` | Verify a method by echoing its code. | Seller |
| POST | `/fee-schedules` | Create a category fee schedule (latest active). | PlatformFinance |
| GET | `/fee-schedules/{id}` | Fetch a fee schedule. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/fee-schedules` | List fee schedules (filter by category). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/orders` | Create an order; prices and posts provisional proceeds. | PlatformFinance |
| GET | `/orders/{id}` | Fetch an order. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/orders` | List orders (filter by seller/schedule/status). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/refunds` | Create a refund request against an order. | PlatformFinance, Seller |
| GET | `/refunds/{id}` | Fetch a refund. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/refunds` | List refunds (filter by order/seller). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/refunds/{id}/apply` | Apply a refund; posts clawback, flips order. | PlatformFinance |
| POST | `/refunds/{id}/void` | Void a requested refund. | PlatformFinance |
| POST | `/chargebacks` | Record a chargeback; posts the flat fee. | PlatformFinance |
| GET | `/chargebacks/{id}` | Fetch a chargeback. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/chargebacks` | List chargebacks (filter by order/seller). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/chargebacks/{id}/represent` | Submit representment evidence within the window. | Seller |
| POST | `/chargebacks/{id}/decision` | Issuer decision; LOST posts full-gross clawback. | PlatformFinance |
| POST | `/disputes` | File an A-to-Z claim against an order. | PlatformReviewer, PlatformFinance |
| GET | `/disputes/{id}` | Fetch a dispute. | PlatformReviewer, PlatformFinance, Seller |
| GET | `/disputes` | List disputes (filter by order/seller). | PlatformReviewer, PlatformFinance, Seller |
| POST | `/disputes/{id}/open-review` | Move a dispute into review (round-bounded). | PlatformReviewer |
| POST | `/disputes/{id}/respond` | Seller responds; increments the round. | Seller |
| POST | `/disputes/{id}/decision` | Resolve a dispute GRANTED or DENIED. | PlatformReviewer |
| POST | `/payouts` | Schedule a payout; snapshots available balance. | PlatformFinance |
| GET | `/payouts/{id}` | Fetch a payout. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/payouts` | List payouts (filter by seller/method/status). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/payouts/{id}/release` | Release a scheduled payout (OCC, reserve hold). | PlatformFinance |
| POST | `/payouts/{id}/mark-failed` | Mark a scheduled payout failed. | PlatformFinance |
| POST | `/payouts/{id}/reverse` | Reverse a released payout (compensating cascade). | PlatformFinance |
| POST | `/tax-forms` | Create a draft 1099-K for a seller and year. | PlatformFinance |
| GET | `/tax-forms/{id}` | Fetch a tax form. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/tax-forms` | List tax forms (filter by seller/year/status). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/tax-forms/{id}/issue` | Issue a 1099-K; below-threshold blocked unless forced. | PlatformFinance |
| POST | `/tax-forms/{id}/correct` | Correct an issued 1099-K. | PlatformFinance |
| POST | `/balance-statements` | Generate a monthly balance statement. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/balance-statements/{id}` | Fetch a balance statement. | PlatformFinance, PlatformReviewer, Seller |
| GET | `/balance-statements` | List balance statements (filter by seller/period). | PlatformFinance, PlatformReviewer, Seller |
| POST | `/_clock/set_current_utc` | Set the simulated current UTC clock. | PlatformFinance, PlatformReviewer |
| POST | `/_clock/advance` | Advance the clock; run maturation and reserve sweeps. | PlatformFinance, PlatformReviewer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_NOT_RESOURCE_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SELLER_NOT_ACTIVE | 409 |
| ERR_STALE_SELLER_VERSION | 412 |
| ERR_BELOW_1099K_THRESHOLD | 422 |
| ERR_REFUND_EXCEEDS_REMAINING | 422 |
| ERR_ORDER_ALREADY_CLAWED | 409 |
| ERR_REPRESENTMENT_WINDOW_CLOSED | 422 |
| ERR_DISPUTE_ROUND_EXHAUSTED | 422 |
| ERR_NOTHING_TO_PAY | 422 |
| ERR_BAD_MICRO_DEPOSIT_CODE | 422 |
| ERR_OPEN_BALANCE_BLOCKS_CLOSE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_NO_VERIFIED_PAYOUT_METHOD | 422 |
| ERR_VALIDATION_PAGINATION | 400 |

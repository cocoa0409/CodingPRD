# P2P Money Transfer API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a peer-to-peer money movement platform in the spirit of consumer wallets such as Venmo, Zelle, and Cash App. The product lets ordinary people hold a balance, link a bank account or debit card as a funding instrument, send money to one another, ask each other to pay, and split a shared bill across a group. Every dollar that moves is recorded as an immutable ledger movement, and every spendable balance is derived from that ledger rather than stored as a mutable counter — the platform never lets a balance drift away from the sum of its postings.

Because real money is in flight, the system is built around two competing obligations: speed for honest users and friction for risky ones. Most sends settle the instant they are submitted, but a configurable risk gate diverts suspicious payments into a manual review queue before the recipient ever sees the funds. Rolling daily and weekly send ceilings cap how much a single account can push out over a moving window. When a recipient claims a payment was unauthorized, never received, or duplicated, a dispute process can claw the money back through a reversal, adjusting both parties' ledgers and the offending party's risk profile. A compliance team adjudicates holds and disputes under a strict segregation-of-duties rule so that no one reviews a payment they were party to.

The audience for this document is the engineering team building the service. It is written domain-first: the business intent of each rule is stated, and the precise mechanics (field names, thresholds, evaluation order, rounding) are embedded in that narrative. The platform is operated by end users (account holders), a compliance team, and a platform operations team, each with sharply different capabilities described in detail below.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request other than account registration and the internal test-driving endpoints must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal and `X-User-Role` declares the capacity in which they act. A request that omits either header, or that supplies an `X-User-Role` that is not one of the recognized role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request that is authenticated but whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly four roles, spelled precisely as follows: `Anonymous`, `AccountHolder`, `ComplianceOfficer`, and `PlatformAdmin`.

`Anonymous` is the unauthenticated caller. It exists only to register a new account; account registration is the single operation that does not require authentication headers, and an `Anonymous` caller has no persisted identity.

`AccountHolder` is an end user acting as their own account. When `X-User-Role` is `AccountHolder`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, when an `AccountHolder` acts on a transfer, withdrawal, funding source, money request, split participation, or dispute, the resource's owning `Account.id` must equal `X-User-ID`, or the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). The exact ownership field differs per resource (for example, the sender for a transfer cancel, the account owner for a withdrawal or funding source, the payer or requester for a money-request action, the participant or organizer for a split action), and each such rule is described with its workflow in §3.

`ComplianceOfficer` is an operator who reviews risk holds and adjudicates disputes but never transacts on behalf of an account. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it — for example as `reviewer_user_id` on a `RiskHold` it resolves, or as `resolver_user_id` on a `Dispute` it resolves — but it does not compare it to any entity's `id` for the purpose of identity, only for the segregation-of-duties test described in §2.4.

`PlatformAdmin` is the operational superuser. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not treat it as an account identity. A `PlatformAdmin` may register accounts, freeze accounts, read every resource, settle or fail standard withdrawals at the payout rail, and operate the test-driving surface.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response includes the following fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties, Versioning, and the Segregation Principle

Most resources in this system are "primary" resources and carry a common set of system-managed fields. Every such resource has an `id` (a server-minted UUID with no type prefix), a `created_at` timestamp (ISO 8601 UTC with three fractional digits, fixed at creation), an `updated_at` timestamp (same format, refreshed on every mutation), and an integer `version` that begins at 1 (or 0) and increments by one on every mutation of that resource. The entities that carry this full common set are `Account`, `FundingSource`, `Transfer`, `MoneyRequest`, `SplitRequest`, `SplitParticipant`, `RiskHold`, `Dispute`, `Reversal`, and `Withdrawal`.

Two entities are deliberately leaner. A `RecipientVerification` and a `LedgerEntry` each carry only `id` and `created_at` — they have no `updated_at` and no `version`, because a ledger movement is immutable once posted and a verification record is driven entirely by its own lifecycle fields. Any time a derived value on a primary resource changes (for example, a recomputed balance, risk score, or split rollup), that counts as a mutation: the resource's `updated_at` is refreshed and its `version` is incremented.

The platform also enforces a **segregation of duties** principle that runs through every compliance action. A `ComplianceOfficer` may not adjudicate a payment they were party to. Specifically, when an officer attempts to clear or block a `RiskHold`, or to request information on, uphold, or deny a `Dispute`, the acting `X-User-ID` must not equal the sender or recipient `Account.id` of the underlying transfer (and, for disputes, must not equal the `opener_account_id`). A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This check is enforced on five operations: hold clear, hold block, dispute request-info, dispute uphold, and dispute deny.

### 2.5. Validation Ordering and Nested-Resource Resolution

When several validations could fire on a single request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. The order is: (1) authentication of the headers, surfacing `ERR_UNAUTHENTICATED`; (2) role permission for the operation, surfacing `ERR_FORBIDDEN_ROLE`; (3) existence of every referenced resource, surfacing `ERR_NOT_FOUND`; (4) ownership for account-holder-scoped mutations, surfacing `ERR_NOT_RESOURCE_OWNER`; (5) segregation of duties on compliance actions, surfacing `ERR_SEGREGATION_OF_DUTIES`; (6) the target being in a state from which the requested transition is defined, surfacing `ERR_INVALID_STATE`; (7) the account not being frozen, surfacing `ERR_ACCOUNT_FROZEN`; (8) the no-self-payment rule, surfacing `ERR_SELF_TRANSFER`; (9) verification-token correctness, surfacing `ERR_VERIFICATION_TOKEN_INVALID`; (10) the funding source being verified and owned, surfacing `ERR_FUNDING_SOURCE_NOT_VERIFIED`; (11) the non-overlapping-verification rule, surfacing `ERR_VERIFICATION_ALREADY_PENDING`; (12) the dispute eligibility window, surfacing `ERR_DISPUTE_WINDOW_CLOSED`; (13) the daily send limit, surfacing `ERR_DAILY_LIMIT_EXCEEDED`; (14) the weekly send limit, surfacing `ERR_WEEKLY_LIMIT_EXCEEDED`; (15) sufficiency of funds, surfacing `ERR_INSUFFICIENT_FUNDS`; (16) the optimistic-concurrency version check on withdrawals, surfacing `ERR_STALE_ACCOUNT_VERSION`; (17) split-participant validity, surfacing `ERR_SPLIT_PARTICIPANT_INVALID`; and finally (18) generic request well-formedness, surfacing `ERR_INVALID_REQUEST`. A check only applies on the endpoints to which it is relevant; the trigger conditions are described alongside the workflows in §3.

For requests whose path or body references resources, existence is validated left-to-right: path identifiers are resolved in the order they appear in the URL before any foreign-key field in the body is resolved, and the first identifier that does not resolve to an existing resource yields `ERR_NOT_FOUND`. For example, a request to act on a participant within a split resolves the split before the participant, and a transfer create resolves the referenced sender and recipient accounts before applying any business rule.

### 2.6. The Ledger and Balance Derivation Principle

The platform keeps an append-only ledger as its single source of financial truth. Each posting is a `LedgerEntry` recording the `account_id` it moves, a `direction` that is either `CREDIT` or `DEBIT`, an `amount_cents` (always a positive magnitude of at least 1 cent), a `source_kind` discriminator that is one of `TRANSFER`, `WITHDRAWAL`, `REVERSAL`, or `ADJUSTMENT`, a polymorphic `source_ref_id`, and a human-readable `memo`. The `source_ref_id` is typed by `source_kind`: it holds a `Transfer.id` when the kind is `TRANSFER`, a `Withdrawal.id` when `WITHDRAWAL`, a `Reversal.id` when `REVERSAL`, and is null when the kind is `ADJUSTMENT`. It is not a single-parent foreign key but a typed reference resolved through `source_kind`.

An account's spendable money, `available_balance_cents`, is computed as its settled credits minus its settled debits minus its held funds, and it may never be negative. Separately, `held_balance_cents` is the total reserved-but-not-spendable money for the account: the sum of the `amount_cents` of this account's transfers (as sender) that are currently in `HELD`, plus any of its withdrawals that have left the balance but are not yet paid out. Held funds are not spendable. Both balances default to 0 at account creation and are recomputed atomically whenever a posting touches the account. Every monetary value in this system is an integer number of cents; there is no fractional-cent representation and therefore no decimal rounding of stored balances.

### 2.7. Send Limits, Risk Tiers, and the Risk Gate

Each account carries a rolling **daily send ceiling**, `daily_send_limit_cents` (defaulting to 250000 cents, i.e. 2,500.00 USD), and a rolling **weekly send ceiling**, `weekly_send_limit_cents` (defaulting to 1000000 cents, i.e. 10,000.00 USD), both supplied optionally at registration. These ceilings constrain outbound sends over moving windows, and the precise accumulation arithmetic is described with the transfer workflow in §3.

Each account also carries a `risk_score`, an integer kept within the inclusive range from 0 to 100, and a derived `risk_tier`. The tier is recomputed from the score every time the score changes: the tier is `LOW` when the score is below 30, `ELEVATED` when the score is from 30 through 69 inclusive, and `HIGH` when the score is 70 or above. The score begins at 0 and the tier at `LOW`. The score rises when a payment the account was party to is blocked or charged back and falls when a dispute the account opened is denied; the exact deltas and clamping are given in §3.

The risk gate is the decision, made at send time, of whether a transfer settles immediately or is diverted to a hold; its evaluation order and thresholds are specified in §3 alongside the transfer lifecycle. The `is_recipient_verified` flag on an account participates in that gate: it is false by default and becomes true once the account has at least one `RecipientVerification` in `CONFIRMED` state, which raises the amount an unverified party may receive without triggering review.

### 2.8. Withdrawal Fees, Precision, and Rounding

Cashing out to a funding source may carry a fee depending on the requested `speed`. Fee computation is the one place where fractional arithmetic occurs, and it is pinned precisely. All fees and amounts are integer cents. The percentage component of an instant withdrawal fee is rounded **up** to the next whole cent (any fractional cent always rounds upward), and the order in which the floor and cap bounds are applied is fixed. The complete formula, its constants, and the standard (free) variant are described with the withdrawal workflow in §3.

### 2.9. Optimistic Concurrency Control on Withdrawals

Creating a withdrawal is guarded by optimistic concurrency control on the owning `Account`. A withdrawal-create request must carry `expected_account_version`, a non-optional field whose value is the client's last observed `version` of the target `Account`. If that value does not match the account's current `version` at the moment the create is processed, the request is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) before any ledger movement is made. The intent is that any prior balance-moving action — a previous withdrawal, a seeded credit, or any other mutation — advances the account's `version`, so a stale `expected_account_version` signals that the client would be debiting against an out-of-date balance view, and the system refuses it rather than overwrite the change it never observed. Every successful withdrawal-create increments the account's `version` by one, regardless of payout speed, so a client must re-read the account between consecutive withdrawals. No other endpoint takes a version field; only withdrawal creation is OCC-guarded.

### 2.10. Account Freezing

An account has a `status` that is either `ACTIVE` or `FROZEN`, beginning at `ACTIVE`. A compliance freeze is one-way and terminal: once an account is `FROZEN` it can never transition back. While an account is `FROZEN`, it cannot send money, cannot withdraw, cannot pay a money request or a split share, and cannot be credited as a recipient. Any such attempt against a frozen account is rejected with `ERR_ACCOUNT_FROZEN` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Accounts and Funding Sources

A new wallet is created by registering an `Account` with an `email` and a `display_name`; the registrant may optionally override `daily_send_limit_cents` and `weekly_send_limit_cents`, which otherwise take their defaults. The `email` must be non-empty and unique across all accounts on a case-insensitive basis. On creation the account opens in `ACTIVE` status with both `available_balance_cents` and `held_balance_cents` at 0, `risk_score` at 0, `risk_tier` at `LOW`, and `is_recipient_verified` false. The `display_name` is the human-readable name shown to counterparties. Registration is open to an `Anonymous` caller or to a `PlatformAdmin`. Anyone authenticated may read a specific account; listing accounts (optionally filtered by `status` or `risk_tier`) is restricted to compliance and platform operators. A compliance freeze drives the account from `ACTIVE` to `FROZEN` and is permitted only when it is currently `ACTIVE`; attempting to freeze an already-frozen account is rejected as an invalid state transition with `ERR_INVALID_STATE`.

To move real money in or out, an account holder links a funding instrument. Creating a `FundingSource` requires the owning `account_id`, the instrument `kind` (either `BANK` or `DEBIT`), and the `last4` display digits (exactly four digits). A newly linked source opens in `PENDING` status, and the server mints a four-character `micro_deposit_code` that the holder must later echo back. Verification advances the source from `PENDING` to `VERIFIED`: the holder submits a `code`, and the transition succeeds only when they own the parent account, the source is still `PENDING`, and the submitted `code` exactly equals the stored `micro_deposit_code`; a mismatch is rejected with `ERR_VERIFICATION_TOKEN_INVALID`. A funding source may be removed by its owner: a `VERIFIED` source moves to the terminal `REMOVED` state only when no withdrawal in `REQUESTED` status still references it (otherwise the removal is rejected with `ERR_FUNDING_SOURCE_IN_USE`), while a `PENDING` source may be removed unconditionally by its owner. `REMOVED` is terminal.

Whenever a funding source becomes `VERIFIED` or `REMOVED`, the system re-derives which source is the account's default payout destination, reflected by the `is_default_payout` flag. The candidate set is every `VERIFIED` funding source belonging to the account. If that set is empty, the account simply has no default payout source. Otherwise the chosen default is the earliest-verified source, selected as the minimum by `created_at` ascending — never by `id` — and exactly that one source has `is_default_payout` true while all others are set false.

### 3.2. Recipient Verification

An account becomes a verified recipient by completing a `RecipientVerification`. The holder starts one by supplying the `account_id` to verify and a `channel` that is either `EMAIL` or `SMS`. The new record opens in `PENDING` status; the server mints a single-use `confirm_token` and sets `expires_at` to the creation time plus 24 hours. Only one live verification may exist per account-and-channel pair: starting a new verification for the same `account_id` and `channel` while a prior one is still `PENDING` and the current time is before that prior record's `expires_at` is rejected with `ERR_VERIFICATION_ALREADY_PENDING`. These records are immutable in the common-fields sense — they carry only `id` and `created_at` — and their progression is captured entirely in `status`, `confirm_token`, and `expires_at`.

Confirmation echoes the token back. When the holder owns the parent account, the record is `PENDING`, the submitted `token` exactly matches the stored `confirm_token`, and the current time is strictly before `expires_at`, the record transitions to `CONFIRMED` and the parent account's `is_recipient_verified` becomes true. The boundary at expiry is decisive: if the submitted token is correct but the current time is at or after `expires_at`, the record instead transitions to the terminal `EXPIRED` state and the account's `is_recipient_verified` is left unchanged. A token that does not match is rejected with `ERR_VERIFICATION_TOKEN_INVALID`. Both `CONFIRMED` and `EXPIRED` are terminal.

### 3.3. Sending Money: Limits, the Risk Fork, and Settlement

A transfer is the core money movement. An account holder sends by supplying the `sender_account_id`, the `recipient_account_id`, an `amount_cents` of at least 1, and an optional `memo` (defaulting to the empty string). The caller must own the sending account, the recipient must be a different account than the sender (a self-send is rejected with `ERR_SELF_TRANSFER`), and neither a frozen sender nor a frozen recipient may participate. A transfer opens in `SENT` status and carries a `risk_flagged` flag (false unless routed to a hold), an optional `hold_id` back-reference, a `settled_at` timestamp (null until settlement), and a `source_money_request_id` that is null for a direct send and set when the transfer fulfills a money request.

**The send-limit pre-flight.** Before a transfer is routed, the system checks it against two rolling windows anchored on the request clock. The daily usage is the sum of `amount_cents` over the sender's transfers in `SENT`, `HELD`, or `SETTLED` status whose `created_at` falls within the last 24 hours; the weekly usage is the same sum over transfers within the last 7 days. Transfers that ended in `REVERSED` or `CANCELLED` are excluded from both sums, and a blocked-hold reversal rewinds prior usage as described in §3.5. The daily remaining headroom is `daily_send_limit_cents` minus daily usage, and the weekly remaining headroom is `weekly_send_limit_cents` minus weekly usage. The effective headroom is the smaller of the two. A send of an amount exactly equal to the effective headroom is allowed; a send of even one cent more is rejected. When the send is rejected, the reported error depends on which window is binding: if the daily remaining is less than or equal to the weekly remaining, the daily window is binding and the rejection is `ERR_DAILY_LIMIT_EXCEEDED`; if instead the weekly remaining is strictly less than the daily remaining, the weekly window is binding and the rejection is `ERR_WEEKLY_LIMIT_EXCEEDED`. The window boundaries are half-open, measured from the window start through the present instant. After the limit check, the sender must also have an `available_balance_cents` at least equal to `amount_cents`, or the send is rejected with `ERR_INSUFFICIENT_FUNDS`.

**The risk fork.** A transfer that clears the pre-flight passes through the risk gate, which decides between immediate settlement and a hold. The gate evaluates three rules strictly top-down and stops at the first match. First, if the sender's `risk_tier` is `HIGH`, the transfer is held with reason `HIGH_TIER`. Otherwise, if the `amount_cents` is at least 100000 cents (1,000.00 USD), the transfer is held with reason `LARGE_AMOUNT`; note this threshold is inclusive, so exactly 100000 cents holds. Otherwise, if the recipient's `is_recipient_verified` is false and the `amount_cents` is strictly greater than 5000 cents (50.00 USD), the transfer is held with reason `UNVERIFIED_RECIPIENT`; this cap is exclusive, so a send of exactly 5000 cents to an unverified recipient does not hold. If none of the three rules match, the transfer settles. The fixed precedence is `HIGH_TIER` first, then `LARGE_AMOUNT`, then `UNVERIFIED_RECIPIENT`.

**Settlement branch (`SENT → SETTLED`).** When the gate routes to settle and the sender is `ACTIVE`, the transfer's `settled_at` is stamped with the current time, a `CREDIT` ledger entry for `amount_cents` is posted to the recipient and a `DEBIT` ledger entry for `amount_cents` is posted to the sender (both with `source_kind` `TRANSFER`), the sender's daily and weekly limit usage is advanced by `amount_cents`, and both parties' `available_balance_cents` are recomputed. `SETTLED` is terminal.

**Hold branch (`SENT → HELD`).** When the gate routes to a hold, the transfer's `risk_flagged` is set true, a `RiskHold` is created referencing this transfer with the gate's `reason_code` and a `status` of `PENDING_REVIEW`, and the transfer's `hold_id` is set to it. A `DEBIT` ledger entry for `amount_cents` (source kind `TRANSFER`) is posted to the sender so the funds leave the spendable balance, but the recipient is **not** yet credited; the sender's `available_balance_cents` drops and `held_balance_cents` rises by `amount_cents`. The sender's daily and weekly usage is still advanced by `amount_cents`. The held transfer awaits compliance review.

**Cancellation (`SENT → CANCELLED`).** The sending holder may cancel a transfer only while it is in `SENT` and `risk_flagged` is false; any ledger movement that was recorded is reversed. `CANCELLED` is terminal. A held transfer cannot be cancelled by the holder — it is resolved only through compliance review.

Transfers can be fetched individually or listed and filtered by `sender_account_id`, `recipient_account_id`, `source_money_request_id`, or `status`.

### 3.4. Compliance Review of Held Transfers

A held transfer is resolved by a `ComplianceOfficer` acting on the owning `RiskHold`, which carries the `transfer_id` under review, a `reason_code` (one of `HIGH_TIER`, `LARGE_AMOUNT`, `UNVERIFIED_RECIPIENT`), a `status` that begins at `PENDING_REVIEW`, and a `reviewer_user_id` that is null until the hold is resolved. Both review actions require the hold to be in `PENDING_REVIEW` and require that the acting officer's `X-User-ID` is neither the sender nor the recipient `Account.id` of the held transfer; a party to the transfer is blocked by `ERR_SEGREGATION_OF_DUTIES`. Holds can be fetched individually or listed and filtered by `transfer_id` or `status`.

**Clearing (`PENDING_REVIEW → CLEARED`).** When the officer clears the hold, the `reviewer_user_id` is recorded and a cascade fires: the owning transfer moves from `HELD` to `SETTLED`. As part of that cascade the transfer's `settled_at` is stamped, a `CREDIT` ledger entry for `amount_cents` (source kind `TRANSFER`) is posted to the recipient, the sender's `held_balance_cents` drops by `amount_cents`, and the recipient's `available_balance_cents` is recomputed. `CLEARED` is terminal.

**Blocking (`PENDING_REVIEW → BLOCKED`).** When the officer blocks the hold, the `reviewer_user_id` is recorded and the opposite cascade fires: the owning transfer moves from `HELD` to `REVERSED`. A `CREDIT` ledger entry for `amount_cents` (source kind `REVERSAL`) is posted back to the sender to refund the earlier debit; the sender's `held_balance_cents` drops by `amount_cents` and `available_balance_cents` rises by `amount_cents`. The sender's `risk_score` is then raised by 20 points (and the `risk_tier` re-derived), and the sender's daily and weekly limit usage is rewound by `amount_cents` — the compensating inverse of the accumulation that the original hold performed. `BLOCKED` is terminal. The two review outcomes are mirror images: a clear credits the recipient and leaves usage standing, whereas a block refunds the sender, penalizes the sender's risk, and rewinds the usage.

### 3.5. Risk Scoring

The account `risk_score` is adjusted by additive deltas, each clamped so the result stays within 0 through 100 inclusive. The new score is the old score plus the event's delta, then bounded below at 0 and above at 100; the `risk_tier` is re-derived from the clamped score using the bands in §2.7. Three events move the score. When a risk hold on a sender is blocked, the sender's score rises by 20. When a dispute is upheld, the recipient who received the disputed funds has their score raised by 35 as a chargeback penalty. When a dispute is denied, the opener who raised it has their score lowered by 10, with the result floored at 0 so it never goes negative. Increases are capped at the 100 ceiling; the single decrease is floored at the 0 baseline.

### 3.6. Requesting Money

An account holder can ask another to pay by creating a `MoneyRequest` with the `requester_account_id` (the account asking to be paid), the `payer_account_id` (the account asked to pay), and an `amount_cents` of at least 1. The requester and payer must be distinct accounts, or the request is rejected with `ERR_SELF_TRANSFER`. A request opens in `PENDING` status. Requests can be fetched individually or listed and filtered by `requester_account_id`, `payer_account_id`, or `status`.

**Paying (`PENDING → FULFILLED`).** Only the payer may fulfill the request, and only while it is `PENDING`. Paying may include an optional `memo`. Fulfillment spawns a transfer from the payer to the requester for the request's amount, with the new transfer's `source_money_request_id` pointing back at this request; that spawned transfer runs the full send pathway of §3.3 — the limit pre-flight, the insufficient-funds check, the frozen-account check, and the risk fork all apply exactly as for a direct send. When the spawned transfer is created, the request moves to the terminal `FULFILLED` state.

**Declining (`PENDING → DECLINED`).** The payer may decline a `PENDING` request, which simply moves it to the terminal `DECLINED` state with no money movement.

**Cancelling (`PENDING → CANCELLED`).** The original requester may cancel their own `PENDING` request, moving it to the terminal `CANCELLED` state with no money movement.

### 3.7. Splitting a Bill

An organizer who fronted a bill collects shares through a `SplitRequest`, created with the `organizer_account_id`, the `total_amount_cents` to divide, a `split_mode` of either `EVEN` or `WEIGHTED`, and a list of `participants`. A split must have at least two participants, the `total_amount_cents` must be at least the participant count (so every share is at least 1 cent), no `participant_account_id` may appear twice, and on a `WEIGHTED` split every `weight` must be at least 1; any of these violations is rejected with `ERR_SPLIT_PARTICIPANT_INVALID`. A split opens in `OPEN` status with `collected_amount_cents` at 0. Each participant record carries the `split_request_id`, the `participant_account_id`, a `weight` (default 1, used only for `WEIGHTED` splits and ignored for `EVEN`), a computed `share_amount_cents`, a `status` beginning at `OWED`, and a `settled_transfer_id` back-reference that is null until the share is paid. Splits can be fetched with their `collected_amount_cents`, listed and filtered by `organizer_account_id` or `status`, and their participants listed (optionally filtered by `participant_account_id`).

**Share allocation at creation.** When the split is created, each participant's `share_amount_cents` is computed so the shares sum exactly to `total_amount_cents`. For an `EVEN` split, the base share is the total divided by the participant count, taking the whole-number (floor) quotient; the remainder is the total minus that base times the count, which is always at least zero and less than the participant count. The remaining cents are handed out one each to the earliest participants — the first however-many participants ordered by `created_at` ascending (never by `id`) receive one extra cent each until the remainder is exhausted. For a `WEIGHTED` split, the weighted raw share for each participant is `total_amount_cents` times that participant's `weight` divided by the sum of all weights; each raw share is floored to a whole cent, and the leftover cents (the total minus the sum of the floored shares) are distributed by the largest-remainder method: participants are ranked by the fractional part of their raw share in descending order, ties broken by `created_at` ascending, and the top-ranked participants each receive one extra cent until the leftover is exhausted. In both modes the sum of all `share_amount_cents` equals `total_amount_cents` exactly.

**Paying a share (`OWED → PAID`).** A participant pays their own share only while their record is `OWED` and the owning split is in `OPEN` or `PARTIALLY_SETTLED`. The payer must be the participant; an optional `memo` may accompany the payment. Paying spawns a transfer from the participant to the organizer for the participant's `share_amount_cents`, running the same send pathway of §3.3 (limits, funds, frozen-account, and risk fork), and the participant's `settled_transfer_id` is set to that transfer. The participant moves to `PAID`, then the split status is re-derived as described below.

**Forgiving a share (`OWED → FORGIVEN`).** The organizer may waive a participant's `OWED` share, moving it to the terminal `FORGIVEN` state with no money movement; the split status is then re-derived. Forgiven shares are excluded from the outstanding total. Both `PAID` and `FORGIVEN` are terminal participant states.

**Split status rollup.** Whenever a participant reaches `PAID` or `FORGIVEN`, the owning split re-derives its own state. The `collected_amount_cents` is recomputed as the sum of `share_amount_cents` over participants currently in `PAID`. Let the count of `PAID` participants and the count of participants in either `PAID` or `FORGIVEN` (the terminal count) be measured against the total participant count: if every participant is terminal and at least one has paid, the split is `SETTLED`; otherwise if at least one participant has paid, the split is `PARTIALLY_SETTLED`; otherwise it remains `OPEN`. The split therefore moves `OPEN → PARTIALLY_SETTLED` when its first participant pays while others remain `OWED`, advances `PARTIALLY_SETTLED → SETTLED` once all participants are terminal with at least one paid, and may go `OPEN → SETTLED` directly when the final outstanding shares resolve together. On reaching `SETTLED` the `collected_amount_cents` is frozen. Both `SETTLED` and `CANCELLED` are terminal split states.

**Cancelling a split (`OPEN → CANCELLED`).** The organizer may cancel a split only while it is `OPEN` and no participant has yet reached `PAID`; cancellation sets every still-`OWED` participant to `FORGIVEN`.

### 3.8. Disputes and Reversals

After a transfer settles, the sender who paid it can dispute it. A `Dispute` is opened with the `transfer_id`, the `opener_account_id` (the sender who is disputing), and a `reason` that is one of `UNAUTHORIZED`, `NOT_RECEIVED`, or `DUPLICATE`. A dispute may only be opened on a transfer that is `SETTLED` and only within 60 days of that transfer's `settled_at`: the current time must be at or before `settled_at` plus 60 days, inclusive. A dispute against a non-settled transfer, or one opened after the 60-day window has closed, is rejected with `ERR_DISPUTE_WINDOW_CLOSED`. A dispute opens in `OPEN` status and carries a `resolver_user_id` (null until it reaches a terminal state) and a `reversal_id` back-reference (null unless it is upheld). Disputes can be fetched individually or listed and filtered by `transfer_id`, `opener_account_id`, or `status`. Every compliance action on a dispute is subject to segregation of duties: the acting officer must not be the `opener_account_id` and must not be the recipient account of the disputed transfer, on pain of `ERR_SEGREGATION_OF_DUTIES`.

**The information loop (`OPEN ↔ NEEDS_INFO`).** A `ComplianceOfficer` may request more information on an `OPEN` dispute, moving it to `NEEDS_INFO`; this appends an audit memo and moves no money. The opener may then provide information on a `NEEDS_INFO` dispute, moving it back to `OPEN`; again only an audit memo is appended. This cycle may repeat, forming an `OPEN ↔ NEEDS_INFO` loop. Requesting information is a compliance action subject to segregation of duties; providing information may be done only by the opener.

**Upholding (`OPEN → UPHELD`).** A `ComplianceOfficer` upholds an `OPEN` dispute only when the underlying transfer is still `SETTLED` and the officer is not a party to it. Upholding fires a depth-three cascade: a `Reversal` is created carrying the `transfer_id`, the `dispute_id` that authorized it, an `amount_cents` equal to the original transfer's `amount_cents` (a full reversal — no partial claw-backs), and a `status` of `APPLIED`; the dispute's `reversal_id` is set to it. The disputed transfer is driven from `SETTLED` to `REVERSED`. A `DEBIT` ledger entry for `amount_cents` (source kind `REVERSAL`) is posted to the recipient to claw the funds back, and a matching `CREDIT` ledger entry for `amount_cents` (source kind `REVERSAL`) is posted to the opener/sender. The recipient's `risk_score` is raised by 35 (the chargeback penalty) and their `risk_tier` re-derived, and both the opener's and recipient's `available_balance_cents` are recomputed. The `Reversal` is created already-applied and atomic; `APPLIED` is its only state and it is terminal. Reversals can be fetched individually or listed and filtered by `transfer_id` or `dispute_id`.

**Denying (`OPEN → DENIED`).** A `ComplianceOfficer` denies an `OPEN` dispute when, on review, the claim does not hold. Denial moves no money but lowers the opener's `risk_score` by 10 (floored at 0) as a frivolous-dispute compensation, then re-derives the opener's `risk_tier`. Both `UPHELD` and `DENIED` are terminal dispute states.

### 3.9. Cashing Out

An account holder cashes out to a verified funding source by creating a `Withdrawal` with the owning `account_id`, the `funding_source_id` to pay out to, a `gross_amount_cents` of at least 1, a `speed` of either `INSTANT` or `STANDARD`, and the `expected_account_version` for the optimistic-concurrency check described in §2.9. The withdrawal also records a computed `fee_cents`, a computed `net_amount_cents`, and a `status` that begins at `REQUESTED`. The create succeeds only when the holder owns the account, the account is `ACTIVE`, the referenced funding source is `VERIFIED` and belongs to the account (otherwise `ERR_FUNDING_SOURCE_NOT_VERIFIED`), the account's `available_balance_cents` is at least `gross_amount_cents` (otherwise `ERR_INSUFFICIENT_FUNDS`), and the `expected_account_version` matches the account's current `version`.

**Fee computation.** The fee depends on `speed`. A `STANDARD` withdrawal is free: its `fee_cents` is 0 and its `net_amount_cents` equals `gross_amount_cents`. An `INSTANT` withdrawal charges a percentage with a floor and a cap. First the percentage component is `gross_amount_cents` multiplied by 175 basis points (1.75%) divided by 10000, with any fractional cent rounded up to the next whole cent. The fee is then taken as the larger of that percentage component and a 25-cent floor, and finally bounded by a 1500-cent cap — the floor is applied first (take the maximum against 25 cents) and the cap is applied after (take the minimum against 1500 cents). The `net_amount_cents` is `gross_amount_cents` minus `fee_cents`.

**Creation side effects, both speeds.** On every successful withdrawal-create the system performs the optimistic-concurrency check, computes `fee_cents` and `net_amount_cents`, posts a `DEBIT` ledger entry for the full `gross_amount_cents` (source kind `WITHDRAWAL`) against the account, recomputes the account's `available_balance_cents`, and increments the account's `version` by one. The version bump happens regardless of `speed`. The difference between the speeds is only the resulting `status`: an `INSTANT` withdrawal posts immediately, moving `REQUESTED → PAID` within the create request, while a `STANDARD` withdrawal remains in `REQUESTED` awaiting the payout batch.

**Standard payout settlement (`REQUESTED → PAID`).** A `PlatformAdmin` settles a `REQUESTED` withdrawal through the payout batch, moving it to `PAID`. No balance change occurs at settlement because the gross was already debited at creation; settlement simply marks the net as paid to the funding source.

**Payout failure (`REQUESTED → FAILED`).** A `PlatformAdmin` may mark a `REQUESTED` withdrawal as failed at the payout rail. This posts a compensating `CREDIT` ledger entry for the full `gross_amount_cents` (source kind `ADJUSTMENT`) to refund the debit taken at creation, then recomputes the account's `available_balance_cents`.

**Holder cancellation (`REQUESTED → CANCELLED`).** The owning holder may cancel a `REQUESTED` withdrawal before the payout posts. Like a failure, this posts a compensating `CREDIT` ledger entry for the full `gross_amount_cents` (source kind `ADJUSTMENT`) and recomputes the account's `available_balance_cents`. `PAID`, `FAILED`, and `CANCELLED` are all terminal. Withdrawals can be fetched with their fee and net, or listed and filtered by `account_id`, `funding_source_id`, or `status`.

### 3.10. Reading Activity and Test-Driving the Clock

Account holders can read their own activity: their account, their ledger, their funding sources, their recipient verifications, their split participations, and their transfers, money requests, disputes, holds, and reversals. Listing an account's ledger returns its `LedgerEntry` records, and the various reverse-lookup listings let a holder or operator trace relationships — for example, the transfers an account sent or received, the holds attached to a transfer, or the reversal that resolved a dispute — through filter parameters rather than through embedded foreign-key declarations.

For deterministic testing of the rolling windows and expiry boundaries, a `PlatformAdmin` can operate two internal capabilities that ordinary clients never touch. A clock capability pins the server's notion of "now" to a supplied instant via a `to_iso8601` value, so that 24-hour, 7-day, 24-hour-expiry, and 60-day-dispute windows can be exercised precisely. A ledger-seeding capability credits an account's balance directly to simulate an inbound external deposit, taking the `account_id`, an `amount_cents`, and an optional `memo`; it posts a `CREDIT` ledger entry with source kind `ADJUSTMENT`, recomputes the account's `available_balance_cents`, and increments the account's `version` by one (which, like any version bump, must be observed by a subsequent withdrawal's `expected_account_version`).

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify or transition an existing resource, including state-changing actions on a resource addressed by its identifier, return a `200 OK` status code. The complete request payloads, side effects, and resulting state changes for each endpoint are described in the §3 workflow narratives; the table below is only a routing and authorization summary.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Register a new account (wallet) | Anonymous, PlatformAdmin |
| GET | `/accounts/{id}` | Fetch an account with computed balances and risk | AccountHolder, ComplianceOfficer, PlatformAdmin |
| GET | `/accounts` | List accounts (filterable by status, risk_tier) | ComplianceOfficer, PlatformAdmin |
| GET | `/accounts/{id}/ledger` | List an account's ledger entries | AccountHolder, ComplianceOfficer, PlatformAdmin |
| GET | `/accounts/{id}/funding-sources` | List an account's funding sources | AccountHolder, PlatformAdmin |
| GET | `/accounts/{id}/recipient-verifications` | List an account's recipient verifications | AccountHolder, PlatformAdmin |
| GET | `/accounts/{id}/split-participations` | List the split shares this account owes/owns | AccountHolder, PlatformAdmin |
| POST | `/accounts/{id}/freeze` | Freeze an account (compliance action) | ComplianceOfficer, PlatformAdmin |
| POST | `/funding-sources` | Link a bank/debit funding source | AccountHolder |
| GET | `/funding-sources/{id}` | Fetch a funding source | AccountHolder, PlatformAdmin |
| POST | `/funding-sources/{id}/verify` | Verify a funding source via micro-deposit code | AccountHolder |
| DELETE | `/funding-sources/{id}` | Remove a funding source | AccountHolder |
| POST | `/recipient-verifications` | Start recipient verification | AccountHolder |
| POST | `/recipient-verifications/{id}/confirm` | Confirm recipient verification by token | AccountHolder |
| POST | `/transfers` | Send money (runs limit check and risk gate) | AccountHolder |
| GET | `/transfers/{id}` | Fetch a transfer | AccountHolder, ComplianceOfficer, PlatformAdmin |
| GET | `/transfers` | List/filter transfers | AccountHolder, ComplianceOfficer, PlatformAdmin |
| POST | `/transfers/{id}/cancel` | Cancel a not-yet-flagged SENT transfer | AccountHolder |
| POST | `/money-requests` | Request money from a payer | AccountHolder |
| GET | `/money-requests/{id}` | Fetch a money request | AccountHolder, PlatformAdmin |
| GET | `/money-requests` | List/filter money requests | AccountHolder, PlatformAdmin |
| POST | `/money-requests/{id}/pay` | Payer fulfills a request (spawns a transfer) | AccountHolder |
| POST | `/money-requests/{id}/decline` | Payer declines a request | AccountHolder |
| POST | `/money-requests/{id}/cancel` | Requester cancels their own request | AccountHolder |
| POST | `/split-requests` | Create a split bill with participants | AccountHolder |
| GET | `/split-requests/{id}` | Fetch a split request | AccountHolder, PlatformAdmin |
| GET | `/split-requests` | List/filter split requests | AccountHolder, PlatformAdmin |
| GET | `/split-requests/{id}/participants` | List a split's participants | AccountHolder, PlatformAdmin |
| POST | `/split-requests/{id}/participants/{pid}/pay` | Participant pays their share | AccountHolder |
| POST | `/split-requests/{id}/participants/{pid}/forgive` | Organizer forgives a share | AccountHolder |
| POST | `/split-requests/{id}/cancel` | Organizer cancels a split with no paid shares | AccountHolder |
| GET | `/risk-holds/{id}` | Fetch a risk hold | ComplianceOfficer, PlatformAdmin, AccountHolder |
| GET | `/risk-holds` | List/filter risk holds | ComplianceOfficer, PlatformAdmin |
| POST | `/risk-holds/{id}/clear` | Clear a hold (cascades transfer to SETTLED) | ComplianceOfficer |
| POST | `/risk-holds/{id}/block` | Block a hold (cascades transfer to REVERSED) | ComplianceOfficer |
| POST | `/disputes` | Open a dispute on a SETTLED transfer | AccountHolder |
| GET | `/disputes/{id}` | Fetch a dispute | AccountHolder, ComplianceOfficer, PlatformAdmin |
| GET | `/disputes` | List/filter disputes | AccountHolder, ComplianceOfficer, PlatformAdmin |
| POST | `/disputes/{id}/request-info` | Compliance requests more info | ComplianceOfficer |
| POST | `/disputes/{id}/provide-info` | Opener provides info | AccountHolder |
| POST | `/disputes/{id}/uphold` | Compliance upholds (creates reversal) | ComplianceOfficer |
| POST | `/disputes/{id}/deny` | Compliance denies (penalizes opener risk) | ComplianceOfficer |
| GET | `/reversals/{id}` | Fetch a reversal | ComplianceOfficer, PlatformAdmin, AccountHolder |
| GET | `/reversals` | List/filter reversals | ComplianceOfficer, PlatformAdmin |
| POST | `/withdrawals` | Cash out to a verified funding source (OCC-guarded) | AccountHolder |
| GET | `/withdrawals/{id}` | Fetch a withdrawal with fee/net | AccountHolder, PlatformAdmin |
| GET | `/withdrawals` | List/filter withdrawals | AccountHolder, PlatformAdmin |
| POST | `/withdrawals/{id}/settle` | Payout batch posts a REQUESTED withdrawal to PAID | PlatformAdmin |
| POST | `/withdrawals/{id}/cancel` | Holder cancels a REQUESTED withdrawal (refund) | AccountHolder |
| POST | `/withdrawals/{id}/fail` | Admin fails a withdrawal at the rail (refund) | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Test-driving: pin the server clock | PlatformAdmin |
| POST | `/_ledger/seed_credit` | Test-driving: credit a balance directly | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_FROZEN` | 409 Conflict |
| `ERR_SELF_TRANSFER` | 422 Unprocessable Entity |
| `ERR_VERIFICATION_TOKEN_INVALID` | 422 Unprocessable Entity |
| `ERR_FUNDING_SOURCE_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_DAILY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_WEEKLY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_FUNDS` | 422 Unprocessable Entity |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_SPLIT_PARTICIPANT_INVALID` | 422 Unprocessable Entity |
| `ERR_FUNDING_SOURCE_IN_USE` | 409 Conflict |
| `ERR_VERIFICATION_ALREADY_PENDING` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
</content>
</invoke>

# Credit Card Rewards API — Product Requirements Document

## 1. Introduction

The Credit Card Rewards & Redemption platform governs the end-to-end accounting of points earned, transferred, and redeemed against a portfolio of consumer credit-card accounts. Cardholders earn at category-dependent rates that flex with rotating quarterly promotions, fixed bonus merchant categories, and a baseline rate that floors all eligible spend. As a cardholder accumulates qualifying spend across the calendar year, the platform graduates the account through annual spending tiers that multiply earn rates and modulate the value rate at which points convert back into statement credit.

The system serves two stakeholder groups with very different operational needs. Cardholders post transactions, activate rotating categories, transfer points to airline and hotel partners, and redeem points back as statement credit. Platform operators provision categories and partners, supervise the lifecycle of each account from open to delinquency to close, simulate partner acknowledgements for transfers, and drive periodic sweeps that expire activations, unqualified signup bonuses, and dormant points balances. A pair of test-only endpoints — an advanceable clock and an explicit sweep trigger — exists so that an audit-grade implementation can be exercised deterministically across quarter rolls, year-end resets, and 90-day signup windows without depending on wall-clock time.

Because every rate change has accounting consequences that ripple backward through the same month's transactions and every state transition has cascading ledger effects, the platform is built around a single append-only ledger that is the source of truth for the points balance. The narrative that follows describes how each entity, calculation, and validation participates in keeping that ledger consistent.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID` identifying the acting principal, and `X-User-Role` identifying the role being exercised. The system recognises exactly two roles: `Cardholder` and `PlatformAdmin`. A request that omits either header, or that supplies a role string outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`. A request that is authenticated but targets an endpoint not permitted to the supplied role per §4 is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id` of the acting `Cardholder` entity; ownership checks on any resource that references a `Cardholder` compare the resource's `cardholder_id` foreign key (resolved either directly, as on an `Account`, or transitively through the `account_id` chain for `Transaction`, `PointsTransfer`, `StatementCredit`, `QuarterlyActivation`, and `PointsLedgerEntry`) to `X-User-ID`. A `Cardholder` attempting to operate on another cardholder's account — whether by closing it, posting a transaction against it, transferring its points, redeeming its points, or activating a category for it — is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit but does not compare it to any entity's `id`; a `PlatformAdmin` therefore acts across all accounts without ownership constraints.

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

List endpoints accept two query parameters: `limit`, which bounds the page size with a default of 10, a minimum of 1, and a maximum of 100; and `offset`, which skips a number of items from the head of the result set with a default of 0 and a minimum of 0. Unless explicitly overridden, every list endpoint sorts its results by the resource's `created_at` (or `occurred_at` for ledger entries, `posted_at` for transactions, `initiated_at` for transfers, `applied_at` for statement credits, `activated_at` for activations) in ascending order.

The `meta` object of a list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`. `total_count` reflects the full count of items matching any provided filters; `has_more` is true when `offset + limit < total_count`.

### 2.4. Common Resource Properties

Every primary resource — `Cardholder`, `Account`, `CashbackCategory`, `Transaction`, and `TransferPartner` — exposes the same four system-managed fields: an `id` formatted as a UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits captured at resource creation; an `updated_at` ISO 8601 UTC timestamp with three fractional digits refreshed on every mutation; and an integer `version` that starts at 1 on creation and increments by one with every mutation.

Four resources are append-only in this system and carry only `id` and `created_at`, with both `updated_at` and `version` absent from their JSON shape: `QuarterlyActivation`, `PointsTransfer`, `StatementCredit`, and `PointsLedgerEntry`. State transitions that close out one of these resources (a transfer reversing, a credit reversing, an activation expiring) update only the status-bearing field and any timestamps explicitly named by the transition; they do not bump a `version` because none exists.

When the system mutates a derived field on an `Account` — `points_balance`, `ytd_qualifying_spend_cents`, `spending_tier`, `lifecycle_state`, `signup_bonus_state`, `signup_bonus_qualifying_spend_cents`, or `last_qualifying_activity_at` — the mutation refreshes the account's `updated_at` and increments its `version` by one, exactly as if a client had submitted the change directly.

### 2.5. Nested Resource Retrieval

When an endpoint path includes more than one resource identifier — for example a request that lists transactions, activations, or ledger entries under an account, or that confirms a specific transfer — the system resolves identifiers strictly left-to-right. The first identifier that does not resolve produces `ERR_NOT_FOUND` immediately, before later segments or request bodies are examined. A request body that names a foreign key — `cardholder_id`, `account_id`, `category_id`, `partner_id`, or `original_transaction_id` — is checked after path resolution succeeds; if the referenced resource does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`.

### 2.6. Optimistic Concurrency Control

Endpoints that mutate a versioned resource (any resource that exposes a `version` field per §2.4) accept an optional `version` value in the request body. When the field is present, the server compares it to the current `version` of the targeted resource; on mismatch, the request is rejected with `ERR_INVALID_STATE` and no side effects are applied. When the field is omitted, the server processes the mutation without an OCC check. Resources without a `version` field — activations, transfers, credits, and ledger entries — do not participate in OCC.

### 2.7. Points Ledger as Single Source of Truth

The `points_balance` exposed on an `Account` is not stored as an independent counter. Every change to it is materialised by appending exactly one row to the `PointsLedgerEntry` ledger and then recomputing `points_balance` as the signed sum of `delta_points` over all entries for the account. Each ledger row carries an `account_id`, an `entry_type` drawn from the enumeration `EARN`, `EARN_ADJUST`, `SIGNUP_BONUS`, `TRANSFER_DEBIT`, `TRANSFER_REVERSE`, `REDEEM_DEBIT`, `REDEEM_REVERSE`, `EXPIRE`, and `FORFEIT`; a `source_entity_type` drawn from `Transaction`, `PointsTransfer`, `StatementCredit`, `Account`, and `System`; a `source_entity_id` linking back to the originating row (or null when `source_entity_type` is `System`); a signed integer `delta_points` where positive values credit the cardholder and negative values debit; and an `occurred_at` server-minted timestamp. The ledger is append-only; corrections are themselves new rows, never edits to prior entries. The `GET /accounts/{account_id}/ledger` endpoint exposes this ledger and supports filtering by `entry_type`.

### 2.8. Integer Arithmetic and Floor Discipline

All monetary amounts in the system are integer cents (`amount_cents`, `requested_amount_cents`, `credit_amount_cents`, `ytd_qualifying_spend_cents`, `signup_bonus_qualifying_spend_cents`, the `_THRESHOLD_CENTS` constants) and all rewards quantities are integer points (`points_balance`, `points_provisional`, `points_final`, `points_debited`, `delta_points`, `requested_points`). The system performs no floating-point arithmetic at any step. Where a calculation would yield a fractional intermediate value, the operative rounding mode is **floor** (truncate toward zero, since all intermediates are non-negative) at each step, except in the redemption calculation where the AMOUNT_FIRST mode uses **ceil** on the points side specifically to ensure the system never under-charges points. Each calculation in §3 names its rounding direction explicitly.

### 2.9. Validation Priority

When multiple validation failures could apply to the same request, they are evaluated in a fixed order so the response is deterministic. Header presence and role enumeration come first and produce `ERR_UNAUTHENTICATED`. Role-to-endpoint permission comes second and produces `ERR_FORBIDDEN`. Existence of path-segment resources comes third and produces `ERR_NOT_FOUND`, evaluated left-to-right per §2.5. Existence of body-supplied foreign keys comes fourth and produces `ERR_REFERENCE_NOT_FOUND`. Cardholder-to-account ownership checks come fifth and produce `ERR_FORBIDDEN` when a `Cardholder` operates on someone else's account. Lifecycle-state precondition checks against the target `Account` (closed for write attempts, refund of an already-`REVERSED` source) come next and produce `ERR_ACCOUNT_CLOSED` or `ERR_INVALID_STATE` as the transition specifies. Only after all of the above have passed does the system evaluate the business rules — category activatability, activation window timing, activation uniqueness, transfer-increment shape, partner active state, redemption minimums, redemption-body field exclusivity, balance sufficiency, refund linkage, and full-refund parity. Each of these business rules has its own dedicated `error_id` and the §3 narrative pairs every rule with the code it raises.

### 2.10. Tier Multipliers and Redemption Value Rates

Every `Account` carries a parallel state dimension `spending_tier` whose value is one of `STANDARD`, `GOLD`, or `PLATINUM`. The tier is materially distinct from the `lifecycle_state` dimension: a `DELINQUENT` account retains its tier, and a tier upgrade does not change the lifecycle. Tier participates in two unrelated calculations: it multiplies earn rates on purchases, and it sets the value rate at which points convert back into statement-credit cents. The narrative in §3 introduces both effects in context; the tier dimension itself is computed exclusively from `ytd_qualifying_spend_cents` thresholds during posting and is reset to `STANDARD` only by the year-rollover sweep on the first instant of each calendar year UTC.

### 2.11. Cascade Semantics on Lifecycle Transitions

Several lifecycle transitions on `Account` produce multi-step cascades through the ledger and into peer resources. The transition rule is that each cascade hop is its own ledger append, in order, before the response is returned: an outer mutation does not commit until every dependent recomputation has been materialised. Transitions whose cascades touch peer resources (the move from `ACTIVE` to `DELINQUENT` and any move into `CLOSED`) are described per peer in §3, including the exact ledger `entry_type` written for each hop. After every cascade the `points_balance` of the affected account is recomputed by re-summing `delta_points` over the ledger; the `updated_at` of the account refreshes and `version` increments once for the overall transition (not once per hop).

### 2.12. Calendar Anchors

Three calendar anchors govern temporal rules throughout the system, and all are evaluated in UTC. The **signup window** of an `Account` is the half-open interval beginning at `opened_at` (inclusive) and ending at `signup_bonus_deadline_at` (exclusive), where `signup_bonus_deadline_at` is precisely 90 days after `opened_at`. The **calendar quarter** of a `Transaction` is determined by `posted_at`: Q1 covers January through March, Q2 April through June, Q3 July through September, and Q4 October through December; a `QuarterlyActivation` references its quarter through `quarter_label` (formatted as four digits then the letter Q then a digit one through four, for example `2026Q2`) with `activation_window_start` set to UTC midnight on the first day of that quarter (inclusive) and `activation_window_end` set to UTC midnight on the first day of the following quarter (exclusive). The **calendar year** anchor governs the `ytd_qualifying_spend_cents` counter and the year-rollover sweep: at the instant the logical clock crosses January 1 at 00:00:00 UTC, every account's year-to-date counter and tier reset together.

## 3. Business Logic & Workflows

### 3.1. Cardholders, Accounts, and the Signup Bonus Clock

A `PlatformAdmin` provisions a `Cardholder` by supplying the cardholder's `email` (a lowercase, unique RFC 5322 address used for login lookup) and `display_name` (the human-readable name printed on receipts and statements). Email uniqueness is enforced at creation; a duplicate is rejected with `ERR_VALIDATION`. With a cardholder on file, the same operator opens an `Account` by supplying the `cardholder_id`. Account creation is a deterministic act: the server mints `opened_at` from its current logical clock, sets `signup_bonus_deadline_at` to exactly ninety days after `opened_at`, seeds `signup_bonus_state` to `PENDING`, seeds `signup_bonus_qualifying_spend_cents` to zero, seeds `points_balance` and `ytd_qualifying_spend_cents` to zero, seeds `spending_tier` to `STANDARD`, seeds `lifecycle_state` to `ACTIVE`, and primes `last_qualifying_activity_at` to the same value as `opened_at` so that the expiration clock is anchored from day one.

The one-time signup bonus is the platform's onboarding incentive, and it tracks five distinct positions: a brand-new account is `PENDING`; once the cardholder has crossed the qualifying spend threshold inside the window, the state advances briefly to `QUALIFIED` and then immediately to `AWARDED` in the same operation that books the bonus; if the window closes without qualification, the state advances to `EXPIRED`; if the account is closed before the bonus has been awarded, the state advances to `FORFEITED`. Awarding deposits sixty thousand points to the ledger as a single `SIGNUP_BONUS` entry whose `delta_points` is positive sixty thousand, and the `Account`'s `points_balance` recomputes accordingly.

Qualification is re-evaluated on every purchase post inside the window and on any logical-clock advance that crosses `signup_bonus_deadline_at`. The qualifying total is calculated as the sum of `amount_cents` over every `Transaction` belonging to this account whose `txn_type` is `PURCHASE`, whose `status` is `POSTED`, and whose `posted_at` is at or after `opened_at` and strictly before `signup_bonus_deadline_at`, minus the sum of `amount_cents` over every refund satisfying the same temporal window. That difference is written to `signup_bonus_qualifying_spend_cents`. When `signup_bonus_state` is `PENDING` and the qualifying total is at least three thousand dollars (three hundred thousand cents) — the comparison is at-or-greater-than, so exactly three thousand dollars triggers but two thousand nine hundred ninety-nine dollars and ninety-nine cents does not — the bonus is awarded immediately as described. When `signup_bonus_state` is `PENDING` and the current logical clock is at or beyond `signup_bonus_deadline_at` without the qualifying total having crossed three thousand dollars, the state advances to `EXPIRED` and no bonus is booked. Refunds posted inside the window deduct from qualifying spend and can therefore unwind a near-miss; refunds posted after the deadline never claw back an already-`AWARDED` bonus.

Account closure is initiated by either the cardholder themselves or by a `PlatformAdmin`, and it requires that the account's `lifecycle_state` is currently `ACTIVE` and that no `PointsTransfer` belonging to the account is in `PENDING` status. The transition from `ACTIVE` to `CLOSED` first appends a single `FORFEIT` ledger entry whose `delta_points` is the negation of the current `points_balance`, then recomputes `points_balance` to zero, and finally — if `signup_bonus_state` is anything other than `AWARDED` — advances `signup_bonus_state` to `FORFEITED`. After closure, every subsequent attempt to post a transaction, redeem a credit, transfer points, or activate a category against the same account is rejected with `ERR_ACCOUNT_CLOSED`; an attempt to close an already-closed account is rejected with `ERR_ACCOUNT_CLOSED` as well. A `PlatformAdmin` may also close an account whose `lifecycle_state` is `DELINQUENT`, and the forfeiture chain runs identically. When two concurrent attempts to operate on the same account collide — for example a close arriving simultaneously with a fresh statement-credit redemption — the system serialises on `Account.lifecycle_state`: exactly one transition wins, and if the close wins first the redemption is rejected with `ERR_ACCOUNT_CLOSED`. If instead the redemption commits first, the close still succeeds and the `FORFEIT` ledger entry sees the post-redemption balance; a second close attempt that arrives before the first one completes is rejected with `ERR_INVALID_STATE`.

A `PlatformAdmin` may also mark an `ACTIVE` account `DELINQUENT`. This transition reverses every `PointsTransfer` on the account whose status is `PENDING` (cascade hop one); for each reversal, a `TRANSFER_REVERSE` ledger entry is appended whose `delta_points` equals the positive `points_debited` of the original transfer (cascade hop two); the account's `points_balance` is then recomputed by re-summing the ledger (cascade hop three). While the account remains `DELINQUENT`, every purchase post earns zero points (see §3.4) but the account is otherwise readable. The matching `DELINQUENT`-to-`ACTIVE` clear-delinquency transition simply re-enables earn going forward; it never backfills earn for transactions posted while the account was delinquent.

### 3.2. Cashback Categories, Quarterly Activations, and the Activation Window

A `PlatformAdmin` registers a `CashbackCategory` by supplying a `code` (uppercase A-Z plus underscore, unique across the catalogue, for example `GROCERY`, `GAS`, `DINING`, or `BASE`), a `category_type` drawn from `BASELINE`, `FIXED_BONUS`, and `ROTATING_QUARTERLY`, and an integer `base_rate_bps` between zero and ten thousand inclusive that expresses the earn rate in basis points (one hundred basis points equals one percent; five hundred basis points equals five percent). On creation, the server sets `requires_activation` to true if and only if `category_type` is `ROTATING_QUARTERLY`; the field is therefore derived, not client-supplied. Categories of type `BASELINE` and `FIXED_BONUS` earn at their declared `base_rate_bps` for every eligible purchase without further ceremony. Categories of type `ROTATING_QUARTERLY` earn at `base_rate_bps` only inside a quarter for which the account has an active `QuarterlyActivation`; outside that window, they earn at the platform fallback rate of one hundred basis points, equivalent to one percent.

Activating a rotating category is a `Cardholder` action against their own account. The request supplies `category_id` and `quarter_label`; the server resolves both, then enforces — in this order — that the referenced category has `category_type` equal to `ROTATING_QUARTERLY` (otherwise `ERR_CATEGORY_NOT_ACTIVATABLE`); that the current logical clock is strictly before that quarter's `activation_window_end` and at-or-after a point fourteen days before `activation_window_start` (otherwise `ERR_ACTIVATION_WINDOW_CLOSED`, covering both an already-ended quarter and an activation attempt more than fourteen days in advance of the quarter's start); and that no `QuarterlyActivation` already exists with the same `account_id`, `category_id`, and `quarter_label` (otherwise `ERR_ACTIVATION_ALREADY_EXISTS`). Two concurrent activation requests for the identical triple serialise on the uniqueness key; exactly one wins, and the loser receives `ERR_ACTIVATION_ALREADY_EXISTS`. On success, the server creates the activation in `ACTIVATED` status, derives `activation_window_start` as UTC midnight of the first day of the named quarter, derives `activation_window_end` as UTC midnight of the first day of the following quarter, and records `activated_at` as the current clock instant.

An activation persists in `ACTIVATED` until the sweep transition fires: when the logical clock advances past `activation_window_end` and a `PlatformAdmin` runs the periodic sweep, every `QuarterlyActivation` whose `activation_window_end` is at-or-before the current clock advances to `EXPIRED`. Expiration is forward-only: it does not retroactively re-rate transactions that posted while the activation was live; it simply means that any further purchases against the same `(account, category)` revert to the fallback one-percent rate exactly as if no activation had ever existed for that quarter.

### 3.3. Transfer Partners

Transfer partners are domain anchors for shipping points off-platform. A `PlatformAdmin` registers a `TransferPartner` with a unique `code` (uppercase A-Z, digits, and underscore, for example `AIR_BLUE` or `HOTEL_PINE`), a `partner_type` of `AIRLINE` or `HOTEL`, an integer `conversion_ratio_points_per_unit` of at least one expressing how many cardholder points are required per one partner-currency unit (so `2` means two points buy one mile), an integer `min_transfer_increment` of at least one expressing the smallest atomic transfer denominated in partner-currency units, and an optional `is_active` boolean defaulting to true that gates whether the partner accepts new transfers. Partners may be listed and filtered by `partner_type` and `is_active`. The partner record itself participates in OCC because it carries a `version`.

### 3.4. Posting Purchases and Refunds, and the Earn Calculation

A `Cardholder` posts a transaction against their own account by supplying `account_id`, `category_id`, `txn_type` (one of `PURCHASE` or `REFUND`), an `amount_cents` of at least one (always non-negative; the sign is encoded in `txn_type`), and — only for refunds — an `original_transaction_id` naming the purchase being reversed. The server resolves all path and body identifiers per §2.5, then mints `posted_at` from the logical clock. Refunds carry an additional pair of checks: the referenced original must have `txn_type` equal to `PURCHASE` and must belong to the same `account_id`, otherwise `ERR_REFUND_MISMATCH`; the refund's `amount_cents` must equal the original's `amount_cents` (partial refunds are not supported), otherwise `ERR_PARTIAL_REFUND_DISALLOWED`; the original's `status` must be `POSTED` (an attempt to refund an already-`REVERSED` transaction is rejected with `ERR_INVALID_STATE`); and the acting account's `lifecycle_state` must not be `CLOSED`.

Every purchase post writes a `points_provisional` value into the transaction row according to a fixed, six-step evaluation order. Step one selects the **category rate in basis points**: if the category's `category_type` is `BASELINE` or `FIXED_BONUS`, it is `base_rate_bps`; if the category is `ROTATING_QUARTERLY`, the server looks for a `QuarterlyActivation` belonging to this `account_id` and `category_id` whose `quarter_label` matches the quarter of `posted_at`, whose `activation_window_start` is at-or-before `posted_at`, whose `activation_window_end` is strictly after `posted_at`, and whose status is `ACTIVATED` — if such an activation exists, the category rate is `base_rate_bps`, otherwise the category rate falls back to the platform fallback of one hundred basis points (one percent). Step two selects the **tier multiplier in basis points** by reading the account's `spending_tier` at `posted_at`: `STANDARD` yields ten thousand (one-times multiplier), `GOLD` yields twelve thousand five hundred (one-and-a-quarter times), and `PLATINUM` yields fifteen thousand (one-and-a-half times). Step three is a placeholder activation multiplier whose value is ten thousand (one-times); the rotating-quarterly fallback is already encoded in step one, so this multiplier never modulates the result. Step four collapses the category rate and tier multiplier into a single `combined_bps` by multiplying them together and dividing by ten thousand, taking the floor of the result before any cents are involved. Step five computes `points_provisional` as the product of `amount_cents` and `combined_bps`, divided by ten thousand, again with the floor taken. Step six is the lifecycle gate: if the account's `lifecycle_state` at `posted_at` is anything other than `ACTIVE`, `points_provisional` is forced to zero regardless of the earlier steps; otherwise the result of step five is the persisted `points_provisional`. The order matters: flooring is applied at the `combined_bps` step *before* multiplying by `amount_cents`, and again at the final cents-to-points step. No half-up rounding is ever applied to earn computation.

Posting a `PURCHASE` produces the following side effects in order: the server appends an `EARN` ledger entry whose `delta_points` equals the newly computed `points_provisional` (a zero-earn purchase still writes the row with `delta_points` zero so the audit trail is complete); the account's `ytd_qualifying_spend_cents` is increased by `amount_cents`; the account's `last_qualifying_activity_at` is set to the current clock instant (refunds do *not* update this anchor — only purchases reset the expiration clock); and finally, if the post brings the year-to-date counter across a tier threshold, the system also fires the tier-upgrade transition described in §3.5. A `REFUND` post does not earn its own row of points; instead it flips the original `Transaction.status` to `REVERSED`, appends an `EARN_ADJUST` ledger entry whose `delta_points` is the negation of the original transaction's `points_provisional`, decrements `ytd_qualifying_spend_cents` by the original `amount_cents`, and leaves `last_qualifying_activity_at` unchanged. Tier *downgrades* never fire on refund; the year-to-date counter may shrink, but tier itself is only ever reset by the year-rollover sweep described in §3.8.

After post, `points_final` is initialised to zero for new transactions and is only later populated by the tier-upgrade backfill (§3.5). Implementations must therefore treat `points_provisional` as the live earn for the transaction until a tier-upgrade backfill fires; only after backfill does `points_final` carry the authoritative figure.

### 3.5. Annual Spending Tiers and the Forward-Looking Backfill

Every purchase post evaluates whether `ytd_qualifying_spend_cents` has crossed a tier threshold and triggers a tier transition accordingly. The transition from `STANDARD` to `GOLD` fires when the post brings the counter to at-or-above six hundred thousand cents (six thousand dollars), provided the account's pre-post tier was `STANDARD` and `lifecycle_state` was `ACTIVE`. The transition from `GOLD` to `PLATINUM` fires when the post brings the counter to at-or-above one million five hundred thousand cents (fifteen thousand dollars), provided the pre-post tier was `GOLD` and `lifecycle_state` was `ACTIVE`. Both transitions update `spending_tier` on the account effective for *subsequent* posts and then trigger a current-month backfill cascade.

The backfill is **forward-looking**, and this rule is load-bearing: when a tier upgrade fires mid-month, every `Transaction` that posted in the *same* calendar month UTC (regardless of whether its `posted_at` is before or after the upgrade's clock instant) and whose `status` is `POSTED` is re-evaluated at the new tier. Transactions posted in any prior calendar month are *not* touched. For each affected transaction the server recomputes the earn formula of §3.4 with the new tier substituted into step two, computes the delta between the recomputed value and the existing `points_provisional`, and if the delta is non-zero appends a single `EARN_ADJUST` ledger entry whose `delta_points` equals that delta and whose `source_entity_type` and `source_entity_id` point at the affected transaction. The transaction's `points_final` is updated to the recomputed value; when the delta is zero, `points_final` is still written, taking the value of `points_provisional`. After all per-transaction adjustments are appended, the account's `points_balance` is recomputed by re-summing `delta_points` across the entire ledger.

There is a contrasting interpretation in which only transactions that posted strictly *after* the upgrade instant are re-rated. That interpretation is **not** the rule here; an implementation that omits same-month pre-upgrade transactions from the backfill is incorrect. For identical monthly purchase sequences, the forward-looking rule produces strictly more `EARN_ADJUST` rows than the contrasting interpretation.

### 3.6. Statement-Credit Redemption: Two Modes, Two Rounding Directions

A `Cardholder` redeems points as a statement credit against their own account by naming a `redemption_mode` of either `POINTS_FIRST` or `AMOUNT_FIRST`. The two modes are mutually exclusive in the request body: `POINTS_FIRST` requires `requested_points` to be present and `requested_amount_cents` to be absent; `AMOUNT_FIRST` requires `requested_amount_cents` to be present and `requested_points` to be absent. Any other combination is rejected with `ERR_INVALID_REDEMPTION_BODY`. The minimum redemption is the same numeric threshold of two thousand five hundred on each side: `POINTS_FIRST` requires `requested_points` to be at-or-above two thousand five hundred points, `AMOUNT_FIRST` requires `requested_amount_cents` to be at-or-above two thousand five hundred cents (twenty-five dollars); anything below is rejected with `ERR_BELOW_MINIMUM_REDEMPTION`.

The conversion rate depends on the account's `spending_tier` and is expressed as a *points-per-dollar* figure: `STANDARD` requires one hundred points per dollar (one cent per point); `GOLD` requires ninety points per dollar (approximately one and one ninth cents per point, when the system never speaks in approximate terms — the precise relationship is `floor(points * 100 / 90)` cents per `points`); `PLATINUM` requires eighty points per dollar (one and a quarter cents per point exactly). The system reads `points_balance` and `spending_tier` atomically when sizing the debit.

For `POINTS_FIRST`, the server records `points_debited` equal to `requested_points` and computes `credit_amount_cents` as `requested_points` multiplied by one hundred and divided by the tier's points-per-dollar figure, with the *floor* taken — the points are spent in full, the cents are the dependent value, and any sub-cent residue is forfeit to the system. For `AMOUNT_FIRST`, the server records `credit_amount_cents` equal to `requested_amount_cents` exactly and computes `points_debited` as `requested_amount_cents` multiplied by the tier's points-per-dollar figure and divided by one hundred, with the *ceiling* taken — the cents are exact, and any sub-point residue is rounded *up* so that the system is never under-charged points. Because the two modes round in opposite directions, they do not always round-trip: a thirty-dollar `AMOUNT_FIRST` redemption on `STANDARD` costs three thousand points and three thousand points `POINTS_FIRST` yields exactly thirty dollars, but the relation breaks at unaligned cent boundaries — a thirty-dollar-and-forty-nine-cent `AMOUNT_FIRST` on `PLATINUM` can debit a different number of points than the inverse `POINTS_FIRST` translation would.

Before the calculation is allowed to settle the ledger, the server verifies `points_debited` is at-or-below `points_balance`; if not, the request is rejected with `ERR_INSUFFICIENT_POINTS`. On success the server creates the `StatementCredit` in `APPLIED` status, mints `applied_at`, appends a `REDEEM_DEBIT` ledger entry whose `delta_points` is the negation of `points_debited`, recomputes `points_balance`, and sets `last_qualifying_activity_at` to the current clock instant. A `PlatformAdmin` may reverse an `APPLIED` credit (an attempt against an already-`REVERSED` credit, or against a credit on a `CLOSED` account, is rejected with `ERR_INVALID_STATE`); reversal appends a `REDEEM_REVERSE` ledger entry whose `delta_points` is the positive `points_debited`, recomputes `points_balance`, and advances `status` to `REVERSED`.

When two redemption attempts race against the same `points_balance` such that each independently fits but together they would drive the balance below zero, the system serialises on the balance check: exactly one wins and the loser is rejected with `ERR_INSUFFICIENT_POINTS`. The same serialisation applies when a redemption races a `points-transfer` initiation against the same balance.

### 3.7. Points Transfers to Partners

A `Cardholder` initiates a points transfer by supplying `account_id`, `partner_id`, and `requested_partner_units` — the number of partner-currency units (miles, hotel points) to deliver. The server first verifies the partner's `is_active` is true (otherwise `ERR_PARTNER_INACTIVE`), then verifies that `requested_partner_units` is strictly greater than zero and that the remainder of `requested_partner_units` divided by the partner's `min_transfer_increment` is zero — that is, the requested units must be a positive integer multiple of the partner's minimum increment (otherwise `ERR_INVALID_TRANSFER_INCREMENT`). The server then computes `points_debited` as `requested_partner_units` multiplied by the partner's `conversion_ratio_points_per_unit` using integer arithmetic only. If `points_debited` exceeds the account's `points_balance`, the request is rejected with `ERR_INSUFFICIENT_POINTS`.

On success the server creates the `PointsTransfer` in `PENDING` status, mints `initiated_at` and leaves `completed_at` null until acknowledgement, appends a `TRANSFER_DEBIT` ledger entry whose `delta_points` is the negation of `points_debited`, recomputes the account's `points_balance`, and sets `last_qualifying_activity_at` to the current clock instant. A `PlatformAdmin` confirms the transfer by acknowledging on behalf of the simulated partner, requiring the account's `lifecycle_state` to be `ACTIVE` and the transfer's status to be `PENDING`; on success the status advances to `COMPLETED`, `completed_at` is minted, and `last_qualifying_activity_at` is refreshed once more. A pending transfer may be reversed manually by either the cardholder themselves or a `PlatformAdmin`, or by cascade from the account moving to `DELINQUENT` or `CLOSED`; reversal appends a `TRANSFER_REVERSE` ledger entry whose `delta_points` is the positive `points_debited`, advances the transfer status to `REVERSED`, and recomputes the account's `points_balance` (the invariant is that the `TRANSFER_DEBIT` plus `TRANSFER_REVERSE` pair sums to a net delta of zero points).

### 3.8. Periodic Sweeps, Expiration, and the Year Rollover

The platform exposes two sweep-style operator capabilities and one clock capability, each restricted to `PlatformAdmin`. The clock capability accepts a single `to_timestamp` and advances the simulated clock to that ISO 8601 instant; advancing the clock does not by itself fire any state transitions — operators must then run a sweep to materialise the effects.

The general sweep walks three independent buckets in a single pass. First, every `QuarterlyActivation` whose status is `ACTIVATED` and whose `activation_window_end` is at-or-before the current clock instant transitions to `EXPIRED`, as described in §3.2. Second, every `Account` whose `signup_bonus_state` is `PENDING` and whose current clock is at-or-beyond `signup_bonus_deadline_at` transitions to `EXPIRED` for that bonus position, with no ledger entry written (no points were ever deposited). Third, `calc_points_expiration` runs on every account whose `lifecycle_state` is `ACTIVE` or `DELINQUENT` and whose `last_qualifying_activity_at` is older than the inactivity horizon. The horizon is exactly three hundred sixty-five days, measured as the floor of the difference between the current clock and `last_qualifying_activity_at` in whole days (one day equals eighty-six thousand four hundred seconds), and the comparison is at-or-greater-than — an account inactive for exactly three hundred sixty-five days expires, an account inactive for three hundred sixty-four days does not. When an account meets the horizon, the server appends a single `EXPIRE` ledger entry whose `delta_points` is the negation of the entire current `points_balance` (no FIFO by ledger row age — the entire positive balance forfeits at once), then recomputes `points_balance` to zero. Accounts whose `lifecycle_state` is `CLOSED` are skipped (their points have already forfeited). When `points_balance` is already zero, no ledger entry is written.

The year-rollover sweep is a separate operator action: at the instant the logical clock crosses January 1 at 00:00:00 UTC, the rollover sweep resets `ytd_qualifying_spend_cents` to zero on every account and resets `spending_tier` to `STANDARD` on every `GOLD` or `PLATINUM` account. The downgrade is **not** accompanied by any compensating ledger entry — points earned under the old tier are not clawed back; only the future earn rate is affected. There is no terminal state for the tier dimension; an account may upgrade again as soon as its post-rollover spend crosses the next threshold.

### 3.9. Ledger Audit and Read Endpoints

The points ledger is the primary audit surface. A `Cardholder` (for their own account) or a `PlatformAdmin` (for any account) may list `PointsLedgerEntry` rows for an account, optionally filtering by `entry_type`. Each row exposes `account_id`, `entry_type`, `source_entity_type`, `source_entity_id`, `delta_points`, and `occurred_at`, plus the `id` and `created_at` system fields. The same access pattern lets the cardholder or operator list `Transaction` rows for an account — filterable by `status` and `txn_type` — and list `QuarterlyActivation` rows for an account, filterable by `quarter_label`. Account and transaction reads expose the live `points_balance`, current `spending_tier`, current `lifecycle_state`, both `points_provisional` and `points_final` on transactions, and both `requested_points` and `requested_amount_cents` on credits (the unused field is null per the redemption-mode contract of §3.6).

## 4. Endpoint Definitions

Creating a new top-level resource (a `Cardholder`, an `Account`, a `CashbackCategory`, a `TransferPartner`, a `Transaction`, a `QuarterlyActivation`, a `PointsTransfer`, or a `StatementCredit`) returns `201 Created`. All other operations — lifecycle transitions, confirmations and reversals on transfers and credits, sweeps, the clock advance, and every list and fetch — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/cardholders` | Create a Cardholder | PlatformAdmin |
| GET    | `/cardholders/{cardholder_id}` | Fetch a Cardholder | Cardholder, PlatformAdmin |
| POST   | `/accounts` | Open an account for a cardholder | PlatformAdmin |
| GET    | `/accounts/{account_id}` | Fetch account snapshot | Cardholder, PlatformAdmin |
| POST   | `/accounts/{account_id}/mark-delinquent` | Move lifecycle from ACTIVE to DELINQUENT; cascade reverse pending transfers | PlatformAdmin |
| POST   | `/accounts/{account_id}/clear-delinquency` | Move lifecycle from DELINQUENT to ACTIVE | PlatformAdmin |
| POST   | `/accounts/{account_id}/close` | Close account; forfeit remaining points; expire unfinished signup bonus | Cardholder, PlatformAdmin |
| POST   | `/accounts/{account_id}/activate-category` | Activate a ROTATING_QUARTERLY category for a quarter | Cardholder |
| GET    | `/accounts/{account_id}/activations` | List activations for an account | Cardholder, PlatformAdmin |
| GET    | `/accounts/{account_id}/ledger` | List points-ledger entries for an account | Cardholder, PlatformAdmin |
| POST   | `/cashback-categories` | Register a cashback category | PlatformAdmin |
| GET    | `/cashback-categories` | List categories | Cardholder, PlatformAdmin |
| POST   | `/transactions` | Post a purchase or full refund | Cardholder |
| GET    | `/transactions/{transaction_id}` | Fetch a transaction | Cardholder, PlatformAdmin |
| GET    | `/accounts/{account_id}/transactions` | List transactions for an account | Cardholder, PlatformAdmin |
| POST   | `/transfer-partners` | Register a transfer partner | PlatformAdmin |
| GET    | `/transfer-partners` | List partners | Cardholder, PlatformAdmin |
| POST   | `/points-transfers` | Initiate a points transfer to a partner | Cardholder |
| POST   | `/points-transfers/{transfer_id}/confirm` | Simulated partner acknowledgement; PENDING to COMPLETED | PlatformAdmin |
| POST   | `/points-transfers/{transfer_id}/reverse` | Reverse a pending transfer | Cardholder, PlatformAdmin |
| POST   | `/statement-credits` | Redeem points as statement credit | Cardholder |
| POST   | `/statement-credits/{credit_id}/reverse` | Reverse an applied statement credit | PlatformAdmin |
| POST   | `/_clock/advance` | Advance the simulated clock to the supplied instant | PlatformAdmin |
| POST   | `/_sweep/run` | Run signup-bonus, activation, and points-expiration sweeps | PlatformAdmin |
| POST   | `/_sweep/year-rollover` | Reset annual tier counters and downgrade all GOLD/PLATINUM accounts to STANDARD | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 422 |
| `ERR_VALIDATION` | 422 |
| `ERR_ACCOUNT_CLOSED` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CATEGORY_NOT_ACTIVATABLE` | 422 |
| `ERR_ACTIVATION_WINDOW_CLOSED` | 422 |
| `ERR_ACTIVATION_ALREADY_EXISTS` | 409 |
| `ERR_INVALID_TRANSFER_INCREMENT` | 422 |
| `ERR_PARTNER_INACTIVE` | 422 |
| `ERR_INSUFFICIENT_POINTS` | 422 |
| `ERR_BELOW_MINIMUM_REDEMPTION` | 422 |
| `ERR_INVALID_REDEMPTION_BODY` | 422 |
| `ERR_REFUND_MISMATCH` | 422 |
| `ERR_PARTIAL_REFUND_DISALLOWED` | 422 |

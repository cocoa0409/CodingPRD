# Crypto Exchange Wallet API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Crypto Exchange Wallet API, a custodial trading and settlement platform that combines a spot order book with on-chain custody of customer assets. The platform serves account holders who deposit, trade, withdraw, and stake digital assets, and it serves the operational and compliance staff who keep the venue solvent and within its regulatory perimeter. Every customer holding is tracked on an internal ledger; every disposal of an asset is recorded for tax reporting under the 1099-DA regime; and every withdrawal is screened against travel-rule obligations before any value leaves the exchange.

The system is built around a small number of interacting concerns that must always reconcile within a single request. Customer balances are partitioned into spendable, reserved, and held buckets so that funds committed to open orders or pending withdrawals can never be double-spent. A continuous matching engine pairs incoming orders against resting liquidity using strict price-time priority, debiting maker and taker fees according to each account's rolling thirty-day taker volume. Disposals of an asset draw down acquisition lots according to the account's chosen cost-basis policy, producing the realized-gain figures that feed regulatory reporting. Because all of these effects are interdependent — a single fill simultaneously moves two balances, charges two fees, opens or depletes cost-basis lots, and recomputes fee tiers — the API treats each triggering request as an atomic transaction whose derived fields are reconciled before the response is returned.

This specification defines the entities, their state machines, the calculations that govern money movement, the validation rules that protect the ledger, and the role boundaries that enforce segregation of duties between trading, custody, and compliance functions.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply uniformly across the API. The business workflows in Section 3 build upon the guarantees established here.

### 2.1. User and Role-Based Access Control

Every request other than account registration must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares their operational capacity. The system recognizes four roles, spelled exactly as follows: `Anonymous`, `Trader`, `Operator`, and `ComplianceOfficer`. A request that omits either header, or that presents an `X-User-Role` value that is not one of these recognized roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized and authenticated but not permitted to perform the targeted operation under the access matrix in Section 4 is rejected with `ERR_FORBIDDEN_ROLE`.

The role identities map to resource ownership as follows:

- When `X-User-Role` is `Anonymous`, `X-User-ID` is an opaque caller identifier not tied to any persisted entity; the only operation available to this role is registering a new account, which is a public endpoint and is therefore exempt from the authentication requirement above.
- When `X-User-Role` is `Trader`, `X-User-ID` is the `id` of the acting `Account`. Ownership checks on any resource that references an account compare that resource's `account_id` to `X-User-ID`. A `Trader` acting on a resource whose `account_id` does not equal their `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`. Ownership is enforced on the trader-owned writes: placing, amending, and cancelling orders; submitting withdrawals; adding, activating, and removing withdrawal addresses; staking, claiming, unbonding, and releasing staking positions; and applying for KYC tier upgrades.
- When `X-User-Role` is `Operator`, `X-User-ID` is an opaque operational identifier not tied to any persisted entity. The server does not compare it to any entity's `id`. Operators manage assets, deposits and their confirmations, KYC decisions, account freezes, and withdrawal broadcasting.
- When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is likewise an opaque operational identifier not tied to any persisted entity, except that the server records it as `filed_by_user_id` on a `TravelRuleRecord` and uses the identifier of the officer who began a withdrawal's screening to enforce segregation of duties (see Section 3.6). It is never compared to any entity's `id` for ownership.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from real server wall-clock time rather than from the logical ledger clock of Section 2.4.
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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the range 1 to 100, or an out-of-range pagination parameter generally, is rejected with `ERR_VALIDATION`; a `limit` or `offset` that is present but cannot be parsed as an integer is likewise rejected with `ERR_VALIDATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Paginated list responses include the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties and the Ledger Clock

Most primary resources carry a standard set of system-managed fields. The `id` is a unique, server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the last modification, refreshed on every mutation. The `version` field is an integer that begins at 1 on creation and increments by one with every mutation; it underpins the optimistic concurrency mechanism described in Section 2.8.

Two entity types are configuration or append-only records and therefore carry only `id` and `created_at` — they have neither `updated_at` nor `version`. The `AssetConfig` entity is immutable configuration except for its one mutable price field, and the `Trade` entity is an append-only execution record; for both of these, `updated_at` and `version` are absent. The `FeeSchedule` entity is likewise configuration carrying only `id` and `created_at`.

Time in this system is supplied by a logical ledger clock rather than wall-clock time. An administrative test-driving capability sets the current clock to a supplied instant; this is the time used by every time-dependent calculation — deposit confirmation windows, the twenty-four-hour address security hold, the trailing thirty-day volume window, staking reward accrual, and the seven-day unbonding cooldown all read this clock. The supplied instant is provided as `to_iso8601`.

### 2.5. Hierarchical Consistency and Cascading Reconciliation

Many operations in this system mutate more than one entity. Whenever a request changes a derived or held quantity on one resource, every dependent resource is reconciled within the same atomic transaction, and each mutated resource independently refreshes its `updated_at` and increments its `version`. A single order fill, for example, appends a `Trade`, moves balances on two accounts, charges fees, opens and depletes cost-basis lots, and recomputes thirty-day volume and fee tier on both accounts — all before the response is returned. The detailed cascades are described in the workflows of Section 3; the governing principle is that no client ever observes a half-applied effect, and every derived field (`available_amount`, `realized` gain figures, `taker_volume_30d_usd`, `fee_tier`, and the like) is consistent with the ledger at the moment the response is produced.

When an account is frozen, the system cascades the freeze into the order book: every order belonging to that account that is still `OPEN` or `PARTIALLY_FILLED` is cancelled, and each such order's reserved funds are released back to spendable balance exactly as in an ordinary cancellation. This is a multi-entity cascade — the account changes state and each affected order changes state and restores its reserve — and all of it occurs within the single freeze request.

### 2.6. Balance Partitioning

Every account holds at most one `Balance` row per asset, keyed by the pair of `account_id` and `asset`. A balance partitions the account's holdings of that asset into named buckets. The `available_amount` is the spendable balance. The `reserved_amount` is the quantity locked behind open orders — for a sell order the reserve is held in the base asset, and for a buy order the reserve is held in the quote asset. The `held_amount` is the quantity locked behind unconfirmed deposits and behind withdrawals that are in the `SUBMITTED`, `SCREENING`, or `TRAVEL_RULE_HOLD` stages. The `total_amount` is the sum of `available_amount`, `reserved_amount`, and `held_amount`, and `available_amount` always equals `total_amount` minus `reserved_amount` minus `held_amount`. These four quantities are computed projections of the ledger, not independently writable fields.

### 2.7. Monetary Precision, Quantity Precision, and Rounding

All USD monetary amounts — notional values, realized gains, cost consumed, daily-ceiling usage — are carried to 2 decimal places and rounded half up. Asset quantities are carried and validated to the number of decimals declared by that asset's `decimals` configuration and are likewise rounded half up. Trade fees are computed in quote-asset units and rounded half up to the quote asset's `decimals`. Where a calculation reserves funds, residual amounts are rounded up to the reserve asset's precision so that the reserve is never short. Wherever a rounding order matters, the order is specified in the relevant workflow in Section 3 and must be followed exactly; in particular, the trailing thirty-day taker volume rounds each trade's notional to cents first and then sums the rounded values, rather than summing first and rounding once.

### 2.8. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control against a parent entity's `version`, so that a client cannot blindly overwrite state it has not observed.

Placing an order is guarded against the account's version. The placement request must carry `expected_account_version`, and the server compares it to the target account's current `version`. If another writer has advanced the account's version since the client last read it — for instance, a prior order placement or a fill cascade that already debited or reserved the account's balances — the placement is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412, because the client's view of spendable balance is stale and the placement would otherwise succeed against that stale view.

Adding a withdrawal address is likewise guarded against the account's version. The add request must carry `expected_account_version`, and a mismatch with the account's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412. Another writer may have just added a different address or changed account state, advancing the account's version; the add would otherwise create a second whitelist entry against the client's stale account view.

Amending a resting limit order is guarded against the order's own version. The amend request must carry `expected_order_version`, and a mismatch with the order's current `version` is rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412. Amend applies only to an `OPEN` or `PARTIALLY_FILLED` `LIMIT` order (any other order state or a non-`LIMIT` order is rejected with `ERR_INVALID_STATE`); it accepts an optional new `limit_price` and an optional new `quantity` — each, when supplied, must be greater than zero, respect its asset's decimal precision, and (for `quantity`) be at least the order's already-`filled_quantity`, otherwise the amend is rejected with `ERR_INVALID_ORDER`. A successful amend releases the order's current reserve, locks the worst-case reserve for the new unfilled remainder (rejecting with `ERR_INSUFFICIENT_AVAILABLE` when spendable balance is short), and then re-runs the matching cascade of Section 3.8 against the amended order. Operations that are not in this list of three do not take a version field, and supplying one elsewhere has no effect.

### 2.9. Nested and Filtered Resource Retrieval

Resources in this system are addressed at their own top-level collections and are linked to one another by foreign keys rather than by nested ownership URLs. When a request references resources by identifier — whether in the path or in the request body — the system validates each referenced resource left to right and rejects the first identifier that does not resolve to an existing resource with `ERR_NOT_FOUND`. This ordering means, for example, that a withdrawal referencing both a non-existent account and a non-existent address surfaces the account's absence first.

List endpoints accept filter query parameters that narrow results by the foreign keys and status fields relevant to each collection. Balances are listed by `account_id` and optionally filtered by `asset`. Cost-basis lots are listed by `account_id` and optionally filtered by `asset` and `status`. Deposits may be filtered by `account_id`, `asset`, and `status`. Withdrawal addresses are listed by `account_id` and optionally filtered by `asset` and `status`. Withdrawals may be filtered by `account_id`, `withdrawal_address_id`, `status`, and `replaces_withdrawal_id`. Orders may be filtered by `account_id`, `base_asset`, `quote_asset`, `lifecycle_status`, and `side`. Trades may be filtered by `maker_order_id`, `taker_order_id`, `base_asset`, and `quote_asset`. Travel-rule records may be filtered by `withdrawal_id`. Staking positions may be filtered by `account_id`, `asset`, and `status`. Accounts may be listed and filtered by `residence_country` and `kyc_tier`.

### 2.10. Validation Ordering

When several validation rules apply to one request, they are evaluated in a fixed priority so that the rejection a client sees is deterministic. Authentication is checked first, then role permission, then resource ownership for trader-owned writes, then the existence of every referenced resource, then whether the target resource is in a state from which the requested transition is defined (a transition attempted from a state where it is not defined is rejected with `ERR_INVALID_STATE`). Account-frozen checks follow, then the various business-safety, temporal, fiscal, and well-formedness checks specific to each endpoint. The precise ordering for each endpoint is described alongside the workflow it guards in Section 3; the general rule is that authentication, authorization, ownership, existence, and state-machine legality are always resolved before domain-specific business rules, and that the optimistic-concurrency check and the final body well-formedness check sit near the end of the chain. A malformed request body — a missing required field, an invalid enum value, or a negative number where one is forbidden — is rejected with `ERR_INVALID_REQUEST`.

## 3. Business Logic & Workflows

### 3.1. Account Onboarding and KYC Tier Progression

An account is created through a public registration endpoint that requires no authentication. The registrant supplies an `email` (unique across all accounts; a registration whose `email` is already in use is rejected with `ERR_INVALID_REQUEST`), a `full_name`, and a `residence_country` given as an ISO-3166 alpha-2 code such as US or GB. The registrant may also choose a cost-basis policy by supplying `cost_basis_method`; this is either `FIFO` or `HIFO`, defaults to `FIFO` when omitted, is fixed at creation, and is immutable thereafter. A newly created account starts at `kyc_tier` of `TIER_0`, `kyc_status` of `UNVERIFIED`, `account_status` of `ACTIVE`, and `version` of 1.

The `kyc_tier` field gates trading eligibility and the per-day withdrawal ceiling, and it advances only one step at a time through an application-and-decision loop. The `kyc_status` field tracks the review state of the most recent upgrade application and is one of `UNVERIFIED`, `PENDING`, `APPROVED`, or `REJECTED`. A `Trader` applies to upgrade by submitting a `requested_tier`. The application is permitted only when the account's `kyc_status` is `UNVERIFIED`, `REJECTED`, or `APPROVED`, when the account's `account_status` is `ACTIVE`, and when the requested tier is exactly one tier above the current `kyc_tier` — skipping a tier, or applying while a review is already `PENDING`, is rejected with `ERR_INVALID_TIER_PROGRESSION`. A successful application sets `kyc_status` to `PENDING` and records the requested tier in `pending_tier`; the `kyc_tier` itself does not move yet. The `pending_tier` field is null whenever `kyc_status` is not `PENDING`.

An `Operator` resolves a pending application with a `decision` of either `APPROVE` or `REJECT`, an operation defined only while `kyc_status` is `PENDING`. Approval moves the account along `PENDING → APPROVED`: `kyc_tier` is set to the value held in `pending_tier`, `kyc_status` becomes `APPROVED`, and `pending_tier` is cleared to null. Rejection moves the account along `PENDING → REJECTED`: `kyc_status` becomes `REJECTED` while `kyc_tier` is left unchanged, and `pending_tier` is cleared to null. Because a rejected account may re-apply, the pair of transitions forms a review loop in which `REJECTED` returns to `PENDING` on a fresh application.

### 3.2. Account Freezing and the Operational Status Axis

An account carries a second, independent status dimension in `account_status`, which is either `ACTIVE` or `FROZEN`. This axis evolves independently of the KYC axis. An `Operator` freezes an account — typically on a sanctions hit — moving it along `ACTIVE → FROZEN`; this is defined only when the account is currently `ACTIVE`. Freezing blocks all trading, withdrawal, and staking writes: any such attempt against a frozen account is rejected with `ERR_ACCOUNT_FROZEN`. As described in Section 2.5, freezing also cancels every `OPEN` or `PARTIALLY_FILLED` order on the account and releases each order's reserve. An `Operator` reverses the freeze, moving the account along `FROZEN → ACTIVE`; this is defined only when the account is currently `FROZEN`.

### 3.3. Asset and Fee Configuration

An `Operator` defines the tradable and settleable assets. Each `AssetConfig` is created with a `symbol` (a unique ticker such as BTC, ETH, or USD; a create whose `symbol` already exists is rejected with `ERR_INVALID_REQUEST`), a `decimals` value giving the on-chain precision to which amounts of that asset are stored and validated, a `required_confirmations` count giving how many network confirmations a deposit of that asset must reach before its funds become spendable, an optional `is_fiat` flag (defaulting to false) marking USD-style settlement assets that need no on-chain confirmation, a `min_withdrawal_amount` giving the smallest withdrawable amount in asset units, a `network_fee` giving the flat on-chain fee in asset units deducted when a withdrawal is settled, and a `spot_price_usd` giving the reference USD price of one unit. The spot price feeds notional valuation, the travel-rule threshold, and thirty-day volume; it is the one mutable field of an asset configuration and may be updated in place by an `Operator`.

An `Operator` also defines the fee schedule. Each `FeeSchedule` row names a `tier_name` — one of `TIER_BASE`, `TIER_1`, `TIER_2`, or `TIER_3`, unique across the schedule, with a create whose `tier_name` already exists rejected with `ERR_INVALID_REQUEST` — together with `min_taker_volume_30d_usd`, the inclusive lower bound of trailing thirty-day taker USD volume that qualifies an account for that tier, and the two rates `maker_fee_bps` and `taker_fee_bps`, each expressed in basis points. The maker rate is charged on the resting side's filled notional and the taker rate on the aggressing side's filled notional.

### 3.4. Deposits and the Network-Confirmation Hold

A deposit enters the system when an `Operator` records a detected inbound transfer, supplying the `account_id` to credit, the `asset`, the `amount` in asset units, and the `unit_cost_usd` — the acquisition USD cost per unit that will seed a cost-basis lot once the deposit credits. A new deposit begins with a `status` of `DETECTED` and a `confirmations` count of 0. The `status` field progresses through `DETECTED`, `CONFIRMING`, `CREDITED`, and `ORPHANED`.

Confirmations are advanced by an `Operator` supplying a `delta` to add to the running count. For a non-fiat asset, the first advance from `DETECTED` moves the deposit along `DETECTED → CONFIRMING`: it increments `confirmations` by the `delta` and credits the deposit's `amount` into the balance's `held_amount`, so the funds are visible but not yet spendable. A subsequent advance that still leaves the running count below the asset's `required_confirmations` keeps the deposit `CONFIRMING → CONFIRMING`, incrementing `confirmations` only. An advance that brings the count to at least `required_confirmations` moves the deposit along `CONFIRMING → CREDITED`: `confirmations` is set to its new total, the deposit's `amount` is moved from `held_amount` into `available_amount`, and a cost-basis lot is opened for the credited funds — with `origin_type` of `DEPOSIT`, `origin_id` set to the deposit's `id`, `original_quantity` and `remaining_quantity` both equal to the deposited amount, `unit_cost_usd` copied from the deposit, and `acquired_at` set to the current clock. A fiat asset short-circuits the hold: a confirmation advance on a `DETECTED` fiat deposit moves it directly along `DETECTED → CREDITED`, incrementing `confirmations` by the supplied `delta`, crediting `available_amount` immediately, and opening the same kind of cost-basis lot with `unit_cost_usd` taken from the deposit. An `Operator` may instead mark a still-`DETECTED` deposit as orphaned, moving it along `DETECTED → ORPHANED` with no balance change because nothing was credited. The terminal states for a deposit are `CREDITED` and `ORPHANED`.

### 3.5. The Withdrawal Whitelist

Before any value can leave the exchange it must target a whitelisted address that has cleared a security hold. A `Trader` adds an address by supplying the owning `account_id`, the `asset` the address can receive, the destination `chain_address` string, a human `label`, and the optimistic-concurrency token `expected_account_version`. A new address is created with a `status` of `PENDING_HOLD` and an `activates_at` set to its `created_at` plus twenty-four hours; the add increments the account's `version` by one. The `status` field is one of `PENDING_HOLD`, `ACTIVE`, or `REMOVED`.

To prevent rapid re-whitelisting of the same destination during a hold, adding an address for a triple of `account_id`, `asset`, and `chain_address` is rejected with `ERR_ADDRESS_HOLD_OVERLAP` while a non-removed row for that same triple is still inside its twenty-four-hour hold window. The hold window is half-open from the existing row's `created_at` up to but not including its `activates_at`: if the current clock falls at or after `created_at` and strictly before `activates_at`, the windows overlap and the add is rejected; once the current clock reaches `activates_at`, the window no longer overlaps and an add for the same triple is allowed.

A `Trader` activates an address once the hold has elapsed, moving it along `PENDING_HOLD → ACTIVE`; this is defined only when the address is `PENDING_HOLD` and the current clock is at or after the address's `activates_at`. A `Trader` may remove an address, moving it to `REMOVED`. Removal is permitted from `ACTIVE` or from `PENDING_HOLD`, but only when no withdrawal targeting that address is currently in `SUBMITTED`, `SCREENING`, `TRAVEL_RULE_HOLD`, `APPROVED`, or `BROADCAST`; an attempt to remove an address still backing a live withdrawal is rejected on the state check. `REMOVED` is terminal.

### 3.6. Submitting and Screening a Withdrawal

A `Trader` submits a withdrawal by supplying the `account_id`, the `withdrawal_address_id` identifying the destination, the `amount` requested in asset units, and optionally a `replaces_withdrawal_id`. The withdrawal copies its `asset` from the target address. At submission, the system computes `notional_usd` as the requested `amount` multiplied by the asset's `spot_price_usd`, and sets `requires_travel_rule` to true when that notional is at least the travel-rule threshold of 3,000 USD and false otherwise. A new withdrawal begins with a `status` of `SUBMITTED`, and submitting it moves the requested `amount` plus the asset's `network_fee` from `available_amount` into `held_amount`. The `status` field ranges over `SUBMITTED`, `SCREENING`, `TRAVEL_RULE_HOLD`, `APPROVED`, `BROADCAST`, `COMPLETED`, and `REJECTED`; `COMPLETED` and `REJECTED` are terminal.

Several checks guard submission, evaluated after authentication, authorization, ownership, and existence. The account must be `ACTIVE`, or the request is rejected with `ERR_ACCOUNT_FROZEN`. The target address must itself be `ACTIVE` and past its `activates_at`, or the request is rejected with `ERR_ADDRESS_NOT_ACTIVE`. The requested amount must be at least the asset's `min_withdrawal_amount`, or the request is rejected with `ERR_BELOW_MIN_WITHDRAWAL`. The withdrawal's asset must match the target address's asset, and when a `replaces_withdrawal_id` is supplied it must reference a `REJECTED` withdrawal of the same account and the same address; a mismatch on either count is rejected with `ERR_RESUBMIT_TARGET_INVALID`. The withdrawal must not breach the account's per-tier daily USD ceiling (see Section 3.7), or it is rejected with `ERR_DAILY_LIMIT_EXCEEDED`. Finally there must be enough spendable balance to cover the amount plus the network fee, or the request is rejected with `ERR_INSUFFICIENT_AVAILABLE`. When these checks pass in the order described — frozen, then address-active, then minimum, then resubmit/asset-match, then daily ceiling, then sufficient funds — the held funds are moved and the withdrawal is recorded.

A `ComplianceOfficer` begins review by screening a `SUBMITTED` withdrawal, moving it along `SUBMITTED → SCREENING`; the system records the screening officer's identity for the later segregation-of-duties check. The officer then resolves screening with a `result` of `CLEAR`, `HOLD`, or `REJECT`. A `CLEAR` result is permitted only when the withdrawal does not require travel-rule treatment, and it moves the withdrawal along `SCREENING → APPROVED`; attempting `CLEAR` on a withdrawal whose notional meets the travel-rule threshold is rejected with `ERR_TRAVEL_RULE_REQUIRED`, because such a withdrawal must route through a hold and a filed record instead. A `HOLD` result is permitted only when the withdrawal does require travel-rule treatment and moves it along `SCREENING → TRAVEL_RULE_HOLD`; attempting `HOLD` on a withdrawal that does not require travel-rule treatment is rejected with `ERR_INVALID_STATE`, and funds remain in `held_amount` throughout, with no balance movement at this step. A `REJECT` result is permitted while the withdrawal is in `SCREENING` or `TRAVEL_RULE_HOLD`, moves it to `REJECTED`, and releases the held funds by moving the `amount` plus `network_fee` from `held_amount` back to `available_amount`. A rejected withdrawal may be resubmitted through a fresh submission carrying `replaces_withdrawal_id`, producing a new `SUBMITTED` withdrawal and re-entering the cycle.

Clearing a travel-rule hold requires filing a record, and this is the segregation-of-duties control. A `ComplianceOfficer` files a `TravelRuleRecord` against a withdrawal that is in `TRAVEL_RULE_HOLD`, supplying the `originator_name`, the `beneficiary_name`, and the `beneficiary_vasp`; the record's `withdrawal_id` ties it to the withdrawal, its `filed_by_user_id` is recorded as the filing officer's `X-User-ID`, and its `status` is `FILED`, which is terminal — the presence of a filed record is what releases the hold. Filing is permitted only when the filing officer's `X-User-ID` differs from the `X-User-ID` of the officer who screened that same withdrawal; a maker-checker collision where the same user both screened and files is rejected with `ERR_SEGREGATION_OF_DUTIES`. A successful filing moves the withdrawal along `TRAVEL_RULE_HOLD → APPROVED`.

### 3.7. Withdrawal Settlement and the Daily Ceiling

The per-tier daily ceiling caps how much USD value an account may withdraw within a single UTC calendar day. The used amount is the sum of the `notional_usd` of every withdrawal for that account created on or after the current day's UTC midnight whose `status` is any of `SUBMITTED`, `SCREENING`, `TRAVEL_RULE_HOLD`, `APPROVED`, `BROADCAST`, or `COMPLETED` — rejected withdrawals do not count. A new withdrawal is admitted only when that running used total plus the new withdrawal's `notional_usd` is at most the ceiling for the account's tier. The ceilings are 0 USD at `TIER_0`, 1,000 USD at `TIER_1`, 50,000 USD at `TIER_2`, and 1,000,000 USD at `TIER_3`; because `TIER_0` permits no withdrawals at all, an unverified account is effectively withdrawal-locked. All USD figures here are taken to two decimal places, rounded half up.

Once a withdrawal is `APPROVED`, an `Operator` broadcasts it on-chain, moving it along `APPROVED → BROADCAST`. Broadcasting is the moment value leaves the exchange and it triggers two cascading effects within the one request. First, the requested `amount` plus the asset's `network_fee` is debited from `held_amount`, and the same total is debited from `total_amount`, so the funds are gone from the ledger. Second, a cost-basis disposal is run for the withdrawn `amount`: the account's cost-basis lots for that asset are consumed according to the account's `cost_basis_method`, decrementing each lot's `remaining_quantity` and flipping any lot whose remaining quantity reaches zero to `DEPLETED`. An `Operator` later confirms the on-chain settlement, moving the withdrawal along `BROADCAST → COMPLETED` with no further balance change; the record is then terminal.

### 3.8. Placing Orders, Reserving Funds, and the Matching Cascade

A `Trader` places an order by supplying the `account_id`, the `base_asset` being bought or sold, the `quote_asset` that prices and settles the trade, the `side` (`BUY` or `SELL`), the `order_type` (`MARKET` or `LIMIT`), the `quantity` of base units, optionally a `limit_price` in quote units per base unit, optionally a `time_in_force`, and the optimistic-concurrency token `expected_account_version`. A new order begins with a `lifecycle_status` of `OPEN`, a `filled_quantity` of 0, and a `time_in_force` defaulting to `GTC`. The `lifecycle_status` ranges over `OPEN`, `PARTIALLY_FILLED`, `FILLED`, and `CANCELLED`, with `FILLED` and `CANCELLED` terminal. The `time_in_force` is either `GTC` or `IOC`; an `IOC` order cancels any unfilled remainder immediately after the matching round rather than resting on the book.

Order placement is gated by a chain of checks. The account must be `ACTIVE`, or the placement is rejected with `ERR_ACCOUNT_FROZEN`. Trading requires the account's `kyc_tier` to be at least `TIER_1`; a `LIMIT` order requires `limit_price` to be present and greater than zero; a `MARKET` order must not carry a `limit_price`; and `quantity` must be greater than zero — any of these violations is rejected with `ERR_KYC_TIER_INSUFFICIENT` for the tier failure or, for the order-shape failures around price presence and positive quantity, with the order-shape rejection described next. The asset pair must be valid — `base_asset` and `quote_asset` must both exist and must differ from each other, and amounts must respect the assets' decimal precision — or the placement is rejected with `ERR_INVALID_ORDER`. A `MARKET` `BUY` requires a non-empty resting `SELL` book or it is rejected with `ERR_NO_LIQUIDITY`. The placement must carry an `expected_account_version` matching the account's current `version` (Section 2.8). Finally, there must be enough spendable balance to cover the computed reserve, or the placement is rejected with `ERR_INSUFFICIENT_AVAILABLE`.

Before matching, the system reserves the worst-case funds the order could consume and records that figure. For a `SELL`, the reserve asset is the `base_asset` and the reserved quantity is simply the order `quantity` of base units to deliver. For a `LIMIT` `BUY`, the reserve asset is the `quote_asset` and the reserved quantity is the gross cost — `quantity` multiplied by `limit_price` — scaled up by the worst-case taker fee, that is, multiplied by one plus thirty basis points expressed as a fraction (thirty divided by ten thousand). For a `MARKET` `BUY`, the system takes the best resting ask — the lowest `limit_price` among the `OPEN` or `PARTIALLY_FILLED` resting `SELL` `LIMIT` orders for that pair that still carry unfilled reserved quantity, rejecting with `ERR_NO_LIQUIDITY` if no such resting sell exists — and reserves `quantity` multiplied by that best ask, then scaled up by a five-percent slippage ceiling (one plus five hundredths) and again by one plus the worst-case taker fee fraction. The reserved quantity is rounded up to the reserve asset's decimal precision so the reserve is never short, and the system requires the reserve asset's `available_amount` to be at least the reserved quantity, rejecting otherwise with `ERR_INSUFFICIENT_AVAILABLE`. The locked figure is carried on the order as `reserved_remaining`, the units of the reserve asset still locked for the unfilled remainder.

After reserving, the matching engine chooses which resting orders the incoming order fills using strict price-time priority. The candidate set is the `OPEN` or `PARTIALLY_FILLED` resting orders on the same base-and-quote pair, on the opposite side, that cross the incoming order. An incoming `BUY` crosses a resting `SELL` when the incoming order is `MARKET` or when the incoming `limit_price` is greater than or equal to the resting order's `limit_price`; an incoming `SELL` crosses a resting `BUY` when the incoming order is `MARKET` or when the incoming `limit_price` is less than or equal to the resting order's `limit_price`. Among crossing candidates the engine ranks by best price first — for an incoming `BUY`, the lowest resting `SELL` price first; for an incoming `SELL`, the highest resting `BUY` price first — and breaks ties between equal prices by the oldest resting order first, ordered by `created_at` ascending, which is the only permitted final tie-break. Walking candidates in ranked order, the engine fills the smaller of the incoming order's remaining quantity and the resting order's remaining quantity at each step, always executing at the resting order's `limit_price`, and appends a `Trade` per fill until the incoming order has no remaining quantity or no further candidate crosses. Fill quantities are taken to the base asset's decimal precision, rounded half up, while the execution price is carried exactly from the resting order. An `IOC` order's leftover after the walk is cancelled; a `GTC` `LIMIT` order's leftover rests on the book as `OPEN` or `PARTIALLY_FILLED`; a `MARKET` order's leftover is cancelled regardless of `time_in_force`, since a market order has no posted price at which to rest.

Each fill produces a cascade. A `Trade` is appended recording the `maker_order_id` (the resting order), the `taker_order_id` (the incoming order), the `base_asset`, the `quote_asset`, the `price` (the resting maker's limit price), the `quantity` exchanged, the `notional_usd` (the quantity times the price times the quote asset's spot price), the `maker_fee`, the `taker_fee`, and the `executed_at` set to the current clock. Both orders have their `filled_quantity` incremented, their `avg_fill_price` recomputed as the notional-weighted average across their fills (null until the first fill), and their `reserved_remaining` decremented. The two accounts' balances are settled: base moves from seller to buyer and quote moves from buyer to seller, net of fees. The maker and taker fees are debited in the quote asset from each side's available balance. A cost-basis lot of `origin_type` `TRADE_BUY` is opened for the buyer's acquired base, its `unit_cost_usd` set to the fill's `notional_usd` divided by the filled base quantity (the USD cost per base unit acquired), and lots are consumed for the seller's disposed base according to the seller's `cost_basis_method`, with that fill's `notional_usd` as the disposal proceeds. Finally, both accounts' `taker_volume_30d_usd` and `fee_tier` are recomputed. An order that is partially filled moves `OPEN → PARTIALLY_FILLED`; an order filled completely in one round moves `OPEN → FILLED` and has its `reserved_remaining` set to zero; a resting order completed by a later incoming order moves `PARTIALLY_FILLED → FILLED`, likewise zeroing its `reserved_remaining`. Placing an order increments the placing account's `version` by one.

### 3.9. Order Fees and Rolling Taker Volume

Every trade charges two fees drawn from the same notional but at rates selected from each account's own fee tier. The trade's quote-denominated notional is its `quantity` multiplied by its `price`. The maker side pays this notional multiplied by the maker rate of the resting account's tier, divided by ten thousand to convert basis points to a fraction, then rounded half up to the quote asset's decimals; this becomes `maker_fee`. The taker side pays the same notional multiplied by the taker rate of the incoming account's tier, divided by ten thousand, rounded half up to the quote asset's decimals; this becomes `taker_fee`. The two sides pay from identical notional but generally different amounts, because the maker rate is the lower, rebate-like rate and the taker rate is the higher one, and because each side's rate is drawn from its own account's tier.

An account's fee tier follows from its trailing thirty-day taker volume. The `maker_volume_30d_usd` field is the sum of `notional_usd` across trades where the account was the resting maker side and the trade's `executed_at` falls within the trailing thirty days of the current clock; the `taker_volume_30d_usd` field is the analogous sum where the account was the aggressing taker side, and it is this taker figure that drives the fee tier. The thirty-day window is half-open: a trade counts when its `executed_at` is strictly after the instant thirty days before the current clock and at or before the current clock. The rounding order is pinned: each qualifying trade's notional is rounded to two USD decimals first, and the rounded per-trade values are then summed, rather than summing exact values and rounding once. The resulting `fee_tier` — one of `TIER_BASE`, `TIER_1`, `TIER_2`, or `TIER_3` — is the schedule tier whose `min_taker_volume_30d_usd` is the highest inclusive lower bound at or below the account's taker volume; when no configured schedule row qualifies (including when no fee schedule has been configured at all), the `fee_tier` falls back to `TIER_BASE` and the applicable maker and taker rates are treated as zero.

### 3.10. Cost Basis and Realized Gains for 1099-DA

Every acquisition of an asset opens a `CostBasisLot` so that later disposals can be matched to their acquisition cost. A lot records the owning `account_id`, the `asset`, the `origin_type` (`DEPOSIT`, `TRADE_BUY`, or `STAKING_REWARD`), the `origin_id` of the deposit, trade, or staking position that created it, the `acquired_at` clock instant, the `original_quantity` acquired, the `remaining_quantity` not yet disposed, the `unit_cost_usd` cost per unit, and a `status` of `OPEN` or `DEPLETED`. A lot becomes `DEPLETED` when its `remaining_quantity` reaches zero.

A disposal occurs on any base-asset sale — a `SELL`-side fill — and on a withdrawal broadcast. To dispose a given quantity of an asset for an account against a known USD proceeds figure, the system selects that account's `OPEN` lots for the asset whose `remaining_quantity` is greater than zero, excluding depleted lots, and orders them by the account's `cost_basis_method`. Under `FIFO` the lots are ordered oldest first — by `acquired_at` ascending, then `created_at` ascending. Under `HIFO` the lots are ordered most-expensive first — by `unit_cost_usd` descending, then `acquired_at` ascending. Walking the ordered lots, the system takes from each lot the smaller of its remaining quantity and the quantity still to dispose, adds that taken quantity multiplied by the lot's `unit_cost_usd` into a running consumed-cost total, decrements the lot's `remaining_quantity`, marks the lot `DEPLETED` if it reaches zero, and stops once the full disposal quantity has been drawn. The realized gain is the proceeds in USD minus the consumed cost in USD. Because the two policies consume lots in opposite orders, on a rising-price history `FIFO` consumes cheaper lots first and reports a higher realized gain, while `HIFO` consumes the most expensive lots first and reports a lower realized gain — this is the 1099-DA divergence the account's chosen method produces from identical disposals. USD amounts here are taken to two decimals and asset quantities to the asset's decimals, all rounded half up.

### 3.11. Staking, Reward Accrual, and Unbonding

A `Trader` opens a staking position by supplying the `account_id`, the `asset` to stake, the `principal_amount` of units, and the annual rate `apr_bps` in basis points. Staking moves the `principal_amount` from `available_amount` into `held_amount`, sets the position's `status` to `ACTIVE`, sets `last_accrual_at` to the current clock, and starts `accrued_rewards` at 0. The `status` field ranges over `ACTIVE`, `UNBONDING`, and `CLOSED`, with `CLOSED` terminal. Staking is blocked on a frozen account (`ERR_ACCOUNT_FROZEN`) and requires sufficient spendable balance to cover the principal (`ERR_INSUFFICIENT_AVAILABLE`).

To prevent a fresh stake from colliding with an in-flight cooldown on the same asset, opening a staking position for an account-and-asset pair is rejected with `ERR_STAKE_COOLDOWN_OVERLAP` when an existing `UNBONDING` position on that same account and asset has a cooldown interval that contains the current clock. This cooldown interval is closed on both endpoints — from `unbond_started_at` through `unbond_available_at` inclusive — so a stake attempted at exactly the `unbond_available_at` instant still collides, in contrast to the half-open address hold window of Section 3.5.

Rewards accrue linearly over the time the principal is staked. When rewards are brought current, the system measures the elapsed seconds from the position's `last_accrual_at` to the current clock, computes the reward increment as the `principal_amount` multiplied by the annual rate (`apr_bps` divided by ten thousand) multiplied by the elapsed seconds divided by the number of seconds in a year (31,536,000, that is 365 days), rounds that increment to the asset's decimals half up, and adds it to the running `accrued_rewards`.

A `Trader` claims rewards on an `ACTIVE` position, a self-transition `ACTIVE → ACTIVE`: the system first accrues rewards up to the current clock, and claiming is permitted only when the resulting `accrued_rewards` is strictly greater than zero — a claim that would yield exactly zero after accrual is rejected with `ERR_NOTHING_TO_CLAIM`. A successful claim credits the accrued rewards into `available_amount`, opens a cost-basis lot of `origin_type` `STAKING_REWARD` for the rewarded units with `unit_cost_usd` equal to the asset's spot price at the moment of claim, resets `accrued_rewards` to zero, and sets `last_accrual_at` to the current clock.

A `Trader` begins unbonding an `ACTIVE` position, moving it along `ACTIVE → UNBONDING`: the system accrues and credits outstanding rewards exactly as in a claim, sets the `status` to `UNBONDING`, records `unbond_started_at` as the current clock, and sets `unbond_available_at` to the current clock plus seven days, with the principal remaining in `held_amount` throughout the cooldown. A `Trader` releases the principal after the cooldown, moving the position along `UNBONDING → CLOSED`; release is permitted only when the current clock is at or after `unbond_available_at`, and an attempt to release before that instant is rejected with `ERR_NOTHING_TO_CLAIM`. A successful release moves the `principal_amount` from `held_amount` back to `available_amount` and closes the position.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including state transitions and configuration updates — return a `200 OK` status code, with the single exception that submitting a KYC upgrade application (`POST /accounts/{id}/kyc-applications`) returns `201 Created`. The clock-setting capability returns `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/accounts` | Register a new account | Anonymous |
| GET | `/accounts/{id}` | Fetch an account with computed volumes and fee tier | Trader, Operator, ComplianceOfficer |
| GET | `/accounts` | List accounts | Operator, ComplianceOfficer |
| POST | `/accounts/{id}/kyc-applications` | Apply to upgrade KYC tier | Trader |
| POST | `/accounts/{id}/kyc-decisions` | Approve or reject a pending KYC application | Operator |
| POST | `/accounts/{id}/freeze` | Freeze an account and cancel its open orders | Operator |
| POST | `/accounts/{id}/unfreeze` | Unfreeze an account | Operator |
| POST | `/assets` | Create an asset configuration | Operator |
| GET | `/assets/{id}` | Fetch an asset configuration | Trader, Operator, ComplianceOfficer |
| PATCH | `/assets/{id}` | Update the mutable spot price | Operator |
| POST | `/fee-schedules` | Create a fee-tier row | Operator |
| GET | `/fee-schedules` | List fee tiers | Trader, Operator |
| GET | `/balances` | List balances for an account | Trader, Operator |
| GET | `/balances/{id}` | Fetch one balance row | Trader, Operator |
| GET | `/cost-basis-lots` | List cost-basis lots for an account/asset | Trader, Operator |
| GET | `/cost-basis-lots/{id}` | Fetch one cost-basis lot | Trader, Operator |
| POST | `/deposits` | Record a detected deposit | Operator |
| GET | `/deposits` | List deposits | Trader, Operator |
| GET | `/deposits/{id}` | Fetch one deposit with confirmation progress | Trader, Operator |
| POST | `/deposits/{id}/confirmations` | Advance network confirmations | Operator |
| POST | `/deposits/{id}/orphan` | Mark a detected deposit orphaned | Operator |
| POST | `/withdrawal-addresses` | Add a whitelisted address | Trader |
| GET | `/withdrawal-addresses` | List whitelist addresses | Trader, Operator, ComplianceOfficer |
| GET | `/withdrawal-addresses/{id}` | Fetch one whitelist address | Trader, Operator, ComplianceOfficer |
| POST | `/withdrawal-addresses/{id}/activate` | Activate an address after the hold | Trader |
| DELETE | `/withdrawal-addresses/{id}` | Remove a whitelist address | Trader |
| POST | `/withdrawals` | Submit a withdrawal | Trader |
| GET | `/withdrawals` | List withdrawals | Trader, Operator, ComplianceOfficer |
| GET | `/withdrawals/{id}` | Fetch one withdrawal | Trader, Operator, ComplianceOfficer |
| POST | `/withdrawals/{id}/screen` | Begin compliance screening | ComplianceOfficer |
| POST | `/withdrawals/{id}/screen-result` | Resolve screening (CLEAR / HOLD / REJECT) | ComplianceOfficer |
| POST | `/withdrawals/{id}/travel-rule-records` | File a travel-rule record to release a hold | ComplianceOfficer |
| GET | `/travel-rule-records` | List travel-rule records | Operator, ComplianceOfficer |
| GET | `/travel-rule-records/{id}` | Fetch one travel-rule record | Operator, ComplianceOfficer |
| POST | `/withdrawals/{id}/broadcast` | Broadcast an approved withdrawal | Operator |
| POST | `/withdrawals/{id}/confirm-onchain` | Mark a broadcast withdrawal confirmed | Operator |
| POST | `/orders` | Place a market or limit order | Trader |
| GET | `/orders/{id}` | Fetch an order with fill progress | Trader, Operator |
| GET | `/orders` | List orders | Trader, Operator |
| PATCH | `/orders/{id}` | Amend a resting limit order | Trader |
| DELETE | `/orders/{id}` | Cancel an open or partially filled order | Trader |
| GET | `/trades` | List trades | Trader, Operator |
| GET | `/trades/{id}` | Fetch one trade execution record | Trader, Operator |
| POST | `/staking-positions` | Stake principal | Trader |
| GET | `/staking-positions` | List staking positions | Trader, Operator |
| GET | `/staking-positions/{id}` | Fetch one staking position | Trader, Operator |
| POST | `/staking-positions/{id}/claim` | Accrue and claim rewards | Trader |
| POST | `/staking-positions/{id}/unbond` | Begin unbonding | Trader |
| POST | `/staking-positions/{id}/release` | Release principal after cooldown | Trader |
| POST | `/_clock/set_current_utc` | Set the system clock (test-driving) | Operator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_FROZEN` | 409 Conflict |
| `ERR_ADDRESS_NOT_ACTIVE` | 409 Conflict |
| `ERR_ADDRESS_HOLD_OVERLAP` | 409 Conflict |
| `ERR_STAKE_COOLDOWN_OVERLAP` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_TRAVEL_RULE_REQUIRED` | 409 Conflict |
| `ERR_INVALID_TIER_PROGRESSION` | 422 Unprocessable Entity |
| `ERR_KYC_TIER_INSUFFICIENT` | 403 Forbidden |
| `ERR_INVALID_ORDER` | 422 Unprocessable Entity |
| `ERR_NO_LIQUIDITY` | 409 Conflict |
| `ERR_BELOW_MIN_WITHDRAWAL` | 422 Unprocessable Entity |
| `ERR_RESUBMIT_TARGET_INVALID` | 409 Conflict |
| `ERR_DAILY_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_INSUFFICIENT_AVAILABLE` | 402 Payment Required |
| `ERR_STALE_ACCOUNT_VERSION` | 412 Precondition Failed |
| `ERR_NOTHING_TO_CLAIM` | 409 Conflict |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_VALIDATION` | 422 Unprocessable Entity |

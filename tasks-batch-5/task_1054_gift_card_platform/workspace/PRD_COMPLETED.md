# Gift-Card Platform API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Gift-Card Program & Distribution Platform, a business-to-business system through which merchants design gift-card products, issue them across digital and physical channels, and reconcile the money that flows through them. The platform sits at the intersection of two hard problems: it is a **ledger-reconciliation** system, where every unit of stored value must be traceable to a signed, immutable accounting entry, and it is a **compliance-and-audit** system, where sensitive money-movements — confirming fraud, finalizing a merchant payout, remitting unclaimed property to a state — are guarded by segregation-of-duties controls that forbid a single operator from both initiating and completing a critical action.

The API governs the full life of stored value. A platform operator onboards a merchant; the merchant designs a card program and its pricing, safety, and incentive rules; issuance orders mint gift cards in bulk for retail sale, B2B distribution, or promotional incentives; point-of-sale clients activate, redeem, and reload cards and query balances; risk operators freeze suspect cards and, when fraud is confirmed, claw redemptions back through the ledger; and finance operators periodically settle a merchant's redeemed value net of interchange fees, recognize breakage on value customers never spend, and escheat the residue of expired cards. Because the system must produce deterministic, replayable financial outcomes, all time-dependent behavior is driven by an explicit server-controlled logical clock rather than wall-clock time, and all monetary quantities are represented as whole integer cents.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that every endpoint obeys.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational role under which the request is made. If either header is absent, or if `X-User-Role` is not one of the roles defined below, the request is rejected with `ERR_MISSING_USER_CONTEXT` (HTTP 400). When the headers are well-formed but the named role is not permitted to invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The platform recognizes six roles, spelled exactly as follows:

- **`PlatformAdmin`** — the platform operator. Manages the merchant lifecycle (create, activate, suspend, reactivate, close), drives the logical clock, and may run program maintenance. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- **`MerchantAdmin`** — acts on behalf of one specific merchant, designing card programs, incentive campaigns, issuance batches, and velocity rules. When `X-User-Role` is `MerchantAdmin`, `X-User-ID` is the `id` of the acting `Merchant`. Ownership checks on any merchant-scoped resource compare the resource's owning merchant to `X-User-ID`: directly against `merchant_id` for a `CardProgram`, and transitively via `card_program_id` → the program's `merchant_id` for a `CardBatch`, `IncentiveCampaign`, `VelocityRule`, or `GiftCard`. A `MerchantAdmin` write against a resource its merchant does not own is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- **`POSTerminal`** — a point-of-sale / acceptance client that activates, redeems, and reloads cards and reads balances. When `X-User-Role` is `POSTerminal`, `X-User-ID` is an opaque terminal identifier not tied to any persisted entity.
- **`FraudAnalyst`** — a risk operator who opens, clears, and confirms fraud holds. When `X-User-Role` is `FraudAnalyst`, `X-User-ID` is an opaque analyst identifier. The server records it (as `opened_by_user_id` when a hold is opened and as `resolved_by_user_id` when a hold is cleared or confirmed on the `FraudHold`) but does not compare it to any entity's `id`.
- **`SettlementOfficer`** — a finance operator who opens, finalizes, and cancels settlement batches and files escheat reports. When `X-User-Role` is `SettlementOfficer`, `X-User-ID` is an opaque officer identifier. The server records it (as `opened_by_user_id` when a batch is opened and as `finalized_by_user_id` when a batch is finalized on the `SettlementBatch`) but does not compare it to any entity's `id`.
- **`Any`** — denotes that any of the authenticated roles above may perform the operation. Every read (GET) endpoint is available to `Any` authenticated role. `Any` carries an opaque identifier and no ownership binding.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.4 (never the host machine's wall-clock time) at the moment the response is produced.
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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0, with a minimum of 0. Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending, with ties (resources sharing an identical `created_at`, as commonly happens because timestamps are stamped from the logical clock) broken by ascending creation order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock

All time-dependent behavior in the platform — card expiry, dormancy accrual, campaign windows, velocity trailing windows, escheat and settlement period bounds — reads a single server-controlled **logical clock** rather than real wall-clock time. At startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any client sets it, every time comparison uses that default (never the host machine's real time). A `PlatformAdmin`-only test-driving capability sets the clock to a supplied `to_iso8601` instant; the response echoes the new `current_utc`. Any datetime the system stamps onto a resource (activation, commit, last-activity, and similar) is taken from this clock at the moment of the operation.

### 2.5. Common Resource Properties

Every top-level resource carries a system-managed `id` — a server-minted UUID, with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits recording when the resource was first created. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by 1 on every mutation. `Merchant`, `CardProgram`, `IncentiveCampaign`, `CardBatch`, `GiftCard`, `FraudHold`, `VelocityRule`, `SettlementBatch`, and `EscheatReport` all carry `updated_at` and `version`.

The `LedgerEntry` resource is the sole exception: it is an immutable accounting record and carries only `id` and `created_at`. A `LedgerEntry` has no `updated_at` and no `version`. A ledger entry is never edited in place — the only change it can undergo is having its `status` flipped from `POSTED` to `REVERSED` during a fraud clawback, which is modeled as a status change on an otherwise fixed record and does not introduce `updated_at`/`version` onto the entry.

### 2.6. Monetary Values, Precision, and Rounding

All monetary values are stored and returned as whole **integer cents**; there are no fractional-cent amounts anywhere in the API. Balance projection and pure summation are exact. Where a calculation divides — recognizing estimated breakage, computing a tiered interchange fee, or computing an incentive bonus — the result is rounded to the nearest whole cent using the **round half up** convention (a value ending in exactly one-half cent rounds away from zero, upward). Any rounding that a multi-step formula requires is described inline with that formula in §3, and the point at which rounding is applied (for example, rounding each card's estimated breakage before summing, or rounding the interchange amount before the minimum-fee floor is applied) is significant and stated there.

### 2.7. The Ledger and Balance Projection

The single source of truth for a card's stored value is its stream of `LedgerEntry` rows. Each entry records the `gift_card_id` it posts against, an `entry_type`, a signed `amount_cents`, a `status`, an optional `settlement_batch_id`, and a human-readable `memo`. The `entry_type` is one of `ACTIVATION_LOAD`, `RELOAD`, `INCENTIVE_BONUS`, `REDEMPTION`, `DORMANCY_FEE`, `BREAKAGE`, or `ESCHEAT_REMIT`. By sign convention, `ACTIVATION_LOAD`, `RELOAD`, and `INCENTIVE_BONUS` carry a positive `amount_cents` that raises the balance, while `REDEMPTION`, `DORMANCY_FEE`, `BREAKAGE`, and `ESCHEAT_REMIT` carry a negative `amount_cents` that lowers it.

A card's `balance_cents` is defined as the sum of `amount_cents` over that card's ledger entries whose `status` is `POSTED`; entries whose `status` is `REVERSED` are excluded from the projection entirely. Because it is a pure sum, the balance is order-independent, and it is recomputed after every entry is posted or reversed. A card's balance is never observed as anything other than this projection.

### 2.8. Hierarchical Consistency and Aggregate Recomputation

Several fields are **computed aggregates** derived from the ledger and from child resources, and the system keeps them consistent immediately as underlying facts change. A `CardProgram` exposes `outstanding_balance_cents`, the sum of `balance_cents` over the `ACTIVE` cards in that program, and `breakage_recognized_cents`, the recognized-breakage figure described in §3.6. A `Merchant` exposes `unsettled_redemptions_cents`, the sum of the magnitudes of its cards' `POSTED` `REDEMPTION` entries whose `settlement_batch_id` is still null, and `lifetime_net_payout_cents`, the sum of `net_payout_cents` across that merchant's `FINALIZED` settlement batches.

When any operation directly mutates a resource — a state transition or other explicit change to one of its own stored fields — the resource's `updated_at` is refreshed and its `version` increments by 1. The computed aggregates named above (`outstanding_balance_cents`, `breakage_recognized_cents`, `unsettled_redemptions_cents`, `lifetime_net_payout_cents`) are, by contrast, projected on demand from the ledger and child resources, so a change to one of them does **not** by itself refresh `updated_at` or increment the `version` of the resource that exposes it: a merchant's `version`, for example, advances only on its own lifecycle transitions and on the settlement open that sweeps it, never merely because one of its cards posted or reversed a redemption, and a program's `version` does not advance merely because a card's balance moved or maintenance recomputed its estimated breakage. Cross-aggregate effects (a fraud confirm that reaches into an open settlement batch and a merchant's unsettled total, a settlement open that sweeps a merchant's redemptions and advances the merchant's version) are spelled out with the workflows that trigger them in §3; the governing principle here is that each such recomputation is applied immediately and durably, never deferred.

### 2.9. Optimistic Concurrency Control on Settlement Opening

Opening a settlement batch is guarded by optimistic concurrency control anchored on the target `Merchant`. A request to open a settlement batch must carry `expected_merchant_version`, and this value must equal the merchant's current `version` at the time the request is processed. Opening a batch sweeps the merchant's un-settled redemptions into it and then advances the merchant's `version`; a subsequent open request still carrying the pre-open value is therefore acting on a stale view — the redemptions it means to sweep were already claimed by the batch that advanced the version — and it is rejected with `ERR_STALE_MERCHANT_VERSION` (HTTP 412). This is the only endpoint that takes a version field; no other operation requires or accepts one.

### 2.10. Segregation of Duties

Two money-critical actions enforce segregation of duties, meaning the operator who completes the action must not be the operator who initiated it. Confirming a fraud hold requires that `X-User-ID` differ from the hold's `opened_by_user_id`; finalizing a settlement batch requires that `X-User-ID` differ from the batch's `opened_by_user_id`. In either case a match — the same operator attempting both sides — is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Clearing a hold and cancelling a batch carry no such restriction.

### 2.11. Validation Ordering and Nested-Resource Resolution

Every endpoint evaluates its guards in a fixed priority order so that the same failing request always produces the same error. The order is: (1) user-context headers present and role known (`ERR_MISSING_USER_CONTEXT`); (2) the role is permitted for the endpoint (`ERR_FORBIDDEN_FOR_ROLE`); (3) for a `MerchantAdmin` write, ownership of the merchant-scoped target (`ERR_NOT_RESOURCE_OWNER`); (4) existence of every referenced resource id, validated left-to-right so that the first path or body id that does not resolve yields `ERR_NOT_FOUND` (HTTP 404); (5) body well-formedness — required fields present, enums valid, amounts positive integers, `card_count` at least 1 — yielding `ERR_VALIDATION` (HTTP 400); (6) the generic state precondition of a transition (`ERR_INVALID_STATE`, HTTP 409); and only then the endpoint-specific business rules, which themselves are ordered by the priorities called out in their respective §3 workflows. When a path names several resources, existence is checked in path order, left to right, before any business rule runs.

## 3. Business Logic & Workflows

### 3.1. Merchant Onboarding and Lifecycle

A `PlatformAdmin` brings a merchant onto the platform by creating a `Merchant` with a `legal_name` and an optional `settlement_currency` (an ISO currency code that defaults to `USD` and governs where settlement payouts are denominated). A newly created merchant begins in `PENDING` status with `version` 1 and its computed aggregates (`unsettled_redemptions_cents`, `lifetime_net_payout_cents`) initialized to 0. The merchant `status` is one of `PENDING`, `ACTIVE`, `SUSPENDED`, or `CLOSED`.

The merchant lifecycle is a cycle with a terminal exit. Activation moves a merchant from `PENDING` to `ACTIVE`; it is permitted only while the merchant is `PENDING`, otherwise `ERR_INVALID_STATE`. Suspension moves an `ACTIVE` merchant to `SUSPENDED` (only from `ACTIVE`, else `ERR_INVALID_STATE`), and reactivation returns a `SUSPENDED` merchant to `ACTIVE` (only from `SUSPENDED`, else `ERR_INVALID_STATE`) — this suspend/reactivate pair is the merchant's revert cycle. Closing a merchant moves it from either `ACTIVE` or `SUSPENDED` to the terminal `CLOSED` state; closing requires that the merchant currently be `ACTIVE` or `SUSPENDED` and that the merchant have no settlement batch in `OPEN` status, otherwise the request is rejected with `ERR_INVALID_STATE`. Every one of these transitions increments the merchant's `version` by 1. Only a `PlatformAdmin` may drive any merchant transition.

### 3.2. Designing Card Programs and Their Rules

Acting as its merchant, a `MerchantAdmin` designs a `CardProgram` — the card-design record that dictates currency, expiry, load limits, and how unspent value is recognized. Creating a program takes the owning `merchant_id`, a `name`, and several optional design parameters: `currency` (defaults to `USD`), `breakage_method` (either `ESTIMATED` or `REMITTANCE`, defaulting to `REMITTANCE`), `expiry_months` (whole months from activation to expiry, at least 1, defaulting to 12), `max_balance_cents` (the ceiling a card's balance may reach after any load or reload, defaulting to 100000), and `min_load_cents` (the smallest permitted reload amount, defaulting to 500). A program is created in `DRAFT` status; its `status` is one of `DRAFT`, `ACTIVE`, `PAUSED`, or `RETIRED`, and it exposes the computed `outstanding_balance_cents` and `breakage_recognized_cents` aggregates described earlier.

A program's lifecycle mirrors the merchant's shape. Activation moves it from `DRAFT` to `ACTIVE`, permitted only while `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning merchant is `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`). Pausing moves an `ACTIVE` program to `PAUSED` (only from `ACTIVE`); resuming returns a `PAUSED` program to `ACTIVE` (only from `PAUSED`) — pause/resume is the program's revert cycle. Retirement moves a program from `ACTIVE` or `PAUSED` to the terminal `RETIRED` state (permitted only from `ACTIVE` or `PAUSED`, else `ERR_INVALID_STATE`); once retired, no new cards may be activated and reloads against the program's cards are rejected with `ERR_PROGRAM_NOT_ACTIVE`. Each program transition increments the program's `version` by 1, and only the owning `MerchantAdmin` may drive them.

A `MerchantAdmin` also configures a program's redemption safety limits by creating a `VelocityRule` bound to a `card_program_id`. A rule specifies a `window_hours` trailing window (at least 1, defaulting to 24), a `max_count` (the number of in-window redemptions that may not be exceeded, defaulting to 5), a `max_amount_cents` (the in-window redemption value that may not be exceeded, defaulting to 50000), and an `enabled` flag (defaulting to true) that, when false, disables the rule so it does not gate redemptions. The way this rule gates a redemption is detailed in §3.4.

Promotional periods are configured as an `IncentiveCampaign` on a `card_program_id`, with a `name`, a `bonus_bps` bonus expressed in basis points (at least 0; for example 1000 means a bonus of ten percent added to each qualifying reload), and an inclusive window bounded by `starts_at` and `ends_at` (UTC), where `ends_at` must be at or after `starts_at`, otherwise the request is rejected with `ERR_VALIDATION`. A campaign's `status` is derived from the logical clock rather than stored: it reads `SCHEDULED` while the clock is before `starts_at`, `RUNNING` while the clock is at or after `starts_at` and at or before `ends_at`, and `ENDED` once the clock is past `ends_at`. Two campaigns on the same program must be kept apart: the closed window `[starts_at, ends_at]` of a new campaign must be separated from every other campaign on that program by at least seven days of buffer, so any pair of campaign windows on one program that fall within seven days of each other is rejected with `ERR_CAMPAIGN_WINDOW_OVERLAP`.

### 3.3. Issuing Cards: Batches and Minting

Card issuance is ordered through a `CardBatch`, created by a `MerchantAdmin` against a `card_program_id`. A batch declares a `channel` (`DIGITAL` or `PHYSICAL`), a `card_count` (the number of cards to mint, at least 1), a `unit_load_cents` (the initial load minted onto each card at activation), and an optional `purpose` (`RETAIL`, `B2B_BULK`, or `INCENTIVE`, defaulting to `RETAIL`). A batch is created in `DRAFT`; its `status` is one of `DRAFT`, `COMMITTED`, or `CANCELLED`, and its `committed_at` timestamp is null while `DRAFT`.

Committing a batch mints the cards. The commit is permitted only while the batch is `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`); on commit the system mints `card_count` `GiftCard` rows, each in `INACTIVE` status, each with `initial_load_cents` set to the batch's `unit_load_cents` and `channel` inherited from the batch, and sets the batch's `committed_at` to the current clock as the batch moves to the terminal `COMMITTED` state. Cancelling a batch is permitted only while it is `DRAFT` (else `ERR_INVALID_STATE`), moves it to the terminal `CANCELLED` state, and has no minting effect.

Each minted `GiftCard` records the `card_program_id` and `card_batch_id` it descends from (copied from the batch), a system-minted `card_number` that is unique across all cards, its inherited `channel`, and an `incentive_campaign_id` that stays null until a bonus-bearing reload attaches it. A card's `status` is one of `INACTIVE`, `ACTIVE`, `SUSPENDED`, `EXPIRED`, `ESCHEATED`, or `CLOSED`. Its stored-value fields are the projected `balance_cents`, the `initial_load_cents` fixed at mint, and the timestamps `activated_at`, `expires_at`, and `last_activity_at` (all null while `INACTIVE`). A card also exposes a computed `dormant` flag, which reads true exactly when the card is `ACTIVE` and the elapsed time since `last_activity_at` is at least 365 days.

### 3.4. Activation, Redemption, Reload, and the Balance API

A card is brought to life by activation, which a `POSTerminal` or a `MerchantAdmin` may perform. Activation is permitted only while the card is `INACTIVE` (else `ERR_INVALID_STATE`) and only while the owning program is `ACTIVE` (else `ERR_PROGRAM_NOT_ACTIVE`). On activation the system posts an `ACTIVATION_LOAD` ledger entry whose `amount_cents` equals the positive `initial_load_cents`, sets `activated_at` to the current clock, sets `expires_at` to the activation instant plus the program's `expiry_months`, sets `last_activity_at` to the same instant, and moves the card to `ACTIVE`.

A `POSTerminal` redeems value by posting a `REDEMPTION` for a given `amount_cents`. The redemption path evaluates its guards in this order: first the card must itself be `ACTIVE` — an `INACTIVE`, `SUSPENDED`, `EXPIRED`, `ESCHEATED`, or `CLOSED` card is rejected with `ERR_CARD_NOT_ACTIVE`; next the velocity rule is checked, yielding `ERR_VELOCITY_EXCEEDED` if it trips; and finally the amount must not exceed the current `balance_cents`, otherwise `ERR_INSUFFICIENT_BALANCE`. The velocity check locates the card's program `VelocityRule` with `enabled` true (if there is none, or it is disabled, the check is skipped); it forms the trailing window as the current clock minus `window_hours`, gathers the card's `POSTED` `REDEMPTION` entries whose `created_at` falls at or after the window start, and computes the in-window count including this redemption (the number of prior in-window redemptions plus one) and the in-window amount including this redemption (the sum of the magnitudes of those prior redemptions plus this amount). The redemption is rejected with `ERR_VELOCITY_EXCEEDED` when the including-count exceeds `max_count` or the including-amount exceeds `max_amount_cents`; the boundary is strict, so a count or amount exactly equal to the cap is allowed. When all guards pass, a `REDEMPTION` entry is posted with a negative `amount_cents` equal to the redeemed amount, `last_activity_at` is set to the current clock, and if the redemption brings the card's `balance_cents` to exactly 0 the card auto-closes from `ACTIVE` to the terminal `CLOSED` state.

A `POSTerminal` or `MerchantAdmin` reloads value onto a card with an `amount_cents`. The reload path checks, in order: the card must be `ACTIVE` (else `ERR_CARD_NOT_ACTIVE`); the owning program must be `ACTIVE`, so a reference to a `PAUSED` or `RETIRED` program is rejected with `ERR_PROGRAM_NOT_ACTIVE` before any capacity check; the amount must be at least the program's `min_load_cents`, otherwise `ERR_BELOW_MIN_LOAD` (HTTP 422); and the projected post-load balance must not exceed the program's `max_balance_cents`, otherwise `ERR_MAX_BALANCE_EXCEEDED`. The projected post-load balance is the existing balance plus the reload amount plus any incentive bonus that would be granted. On success a `RELOAD` entry is posted with a positive `amount_cents`. If, at the reload instant, an `IncentiveCampaign` on the card's program is `RUNNING` (the clock is within its inclusive window), the system additionally posts an `INCENTIVE_BONUS` entry whose positive `amount_cents` is the reload amount multiplied by that campaign's `bonus_bps`, divided by 10000, rounded half up to a whole cent, and it stamps the card's `incentive_campaign_id` with that campaign. This `INCENTIVE_BONUS` posting and the `incentive_campaign_id` stamp happen only when the computed bonus is at least one whole cent; if the rounded bonus is 0 (for instance a campaign with `bonus_bps` 0, or a reload small enough that the bonus rounds to nothing) no `INCENTIVE_BONUS` entry is posted and `incentive_campaign_id` is left unchanged, even though the campaign is `RUNNING`. The reload sets `last_activity_at` to the current clock. Because campaign windows on a program are held seven days apart, at most one campaign is ever `RUNNING` for a given reload.

The balance API lets a `POSTerminal` (or any authenticated reader) look up a card's live standing without mutating it, returning the card's `card_number`, its `status`, its projected `balance_cents`, and the program `currency`.

### 3.5. Fraud Holds, Clearing, and Confirmation Clawback

A `FraudAnalyst` freezes a suspect card by opening a `FraudHold` with the `gift_card_id` and a `reason` (`VELOCITY`, `MANUAL`, or `CHARGEBACK`). Opening a hold is permitted only while the card is `ACTIVE` (else `ERR_INVALID_STATE`); it records the analyst's `X-User-ID` as `opened_by_user_id`, sets the hold's `resolved_by_user_id` null, starts the hold in `OPEN` status, and freezes the card by moving it from `ACTIVE` to `SUSPENDED`. While a card is `SUSPENDED`, redeem and reload are both rejected with `ERR_CARD_NOT_ACTIVE`. A hold's `status` is one of `OPEN`, `CLEARED`, or `CONFIRMED`, and it exposes a computed `reversed_redemption_count` that is 0 while the hold is `OPEN` or `CLEARED`.

An `OPEN` hold resolves down one of two branches, and the two branches differ sharply. **Clearing** (the benign branch) is permitted only while the hold is `OPEN` (else `ERR_INVALID_STATE`); it records the acting analyst's `X-User-ID` as `resolved_by_user_id`, moves the hold to the terminal `CLEARED` state, and unfreezes the card by returning it from `SUSPENDED` to `ACTIVE` with no change to the ledger. This open-hold/clear-hold pair is the card's `ACTIVE` ⇄ `SUSPENDED` revert cycle. **Confirming** (the clawback branch) is permitted only while the hold is `OPEN` (else `ERR_INVALID_STATE`) and, under segregation of duties, only when the acting `X-User-ID` differs from the hold's `opened_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`). On confirm the system records `resolved_by_user_id`, moves the hold to the terminal `CONFIRMED` state, and — this is the material effect — flips every `POSTED` `REDEMPTION` entry on the card to `REVERSED`, which restores the reversed value to the card's balance; the card itself stays `SUSPENDED` (though its own `updated_at` and `version` advance to record the balance restoration). The count of entries flipped is captured in the hold's `reversed_redemption_count`. Each reversed entry cascades according to where its value had gone: a reversed entry carrying a `settlement_batch_id` of a batch still in `OPEN` status is removed from that batch, which triggers the batch to recompute its `gross_redemptions_cents` and `net_payout_cents`; a reversed entry whose `settlement_batch_id` is null instead drives a recompute of the owning `Merchant`'s `unsettled_redemptions_cents`.

### 3.6. Program Maintenance: Expiry, Breakage, and Dormancy

Periodic housekeeping for a program is triggered by a `PlatformAdmin` or `MerchantAdmin` running maintenance, which performs three sweeps against the program's cards using the current clock. **Expiry:** any `ACTIVE` card whose `expires_at` is at or before the current clock transitions to `EXPIRED`. If the program's `breakage_method` is `REMITTANCE` and such a card still has a positive balance, the system posts a `BREAKAGE` ledger entry with a negative `amount_cents` equal to the full remaining balance, forfeiting it; that forfeited magnitude raises the program's `breakage_recognized_cents`. **Dormancy:** for each `ACTIVE` card whose inactivity since `last_activity_at` is at least 365 days and whose balance is positive, the system posts a `DORMANCY_FEE` entry with a negative `amount_cents` equal to the lesser of 200 cents and the card's current balance, so the fee never drives a balance below 0; the inactivity boundary is inclusive, meaning exactly 365 days of inactivity counts as dormant. **Estimated breakage recognition:** for a program whose `breakage_method` is `ESTIMATED`, maintenance recomputes `breakage_recognized_cents` as the sum, over the program's `ACTIVE` cards, of each card's balance multiplied by 1000 basis points divided by 10000 (that is, ten percent of the card's balance), rounded half up to a whole cent per card and then summed — value is recognized progressively this way without forfeiting any card's balance.

The two breakage methods therefore recognize the same underlying unspent value through different policies. Under `REMITTANCE`, `breakage_recognized_cents` is the sum of the magnitudes of the `BREAKAGE` entries created when cards actually expire with a positive balance, and an `ACTIVE`, un-expired card contributes nothing. Under `ESTIMATED`, `breakage_recognized_cents` is the per-card ten-percent figure computed over the currently `ACTIVE` cards at each maintenance run, recognized without forfeiture.

### 3.7. Settlement, Interchange, and the Provisional-versus-Final Split

A `SettlementOfficer` settles a merchant's redeemed value by opening a `SettlementBatch` for a `merchant_id` over a period bounded by an inclusive `period_start` and an exclusive `period_end` (UTC) where `period_end` must be strictly after `period_start` (otherwise `ERR_VALIDATION`), and carrying `expected_merchant_version` for the concurrency check of §2.9. A new period `[period_start, period_end)` must not overlap any other non-`CANCELLED` settlement batch of that merchant; overlap is rejected with `ERR_SETTLEMENT_PERIOD_OVERLAP`, while the half-open convention means two batches that merely touch at an endpoint do not overlap. When the overlap check passes and the version matches, opening the batch sweeps every one of the merchant's `POSTED` `REDEMPTION` entries whose `settlement_batch_id` is null into the batch (stamping that `settlement_batch_id` onto each), records the officer's `X-User-ID` as `opened_by_user_id`, starts the batch in `OPEN` status, computes the provisional payout, advances the merchant's `version` by 1, and recomputes the merchant's `unsettled_redemptions_cents`. A batch's `status` is one of `OPEN`, `FINALIZED`, or `CANCELLED`.

Interchange is a tiered fee on the batch's gross swept redemptions. Let the gross be the sum of the magnitudes of the batch's swept `REDEMPTION` entries. The fee rate is 300 basis points when the gross is at most 1,000,000 cents, 250 basis points when the gross is greater than that but at most 5,000,000 cents, and 200 basis points when the gross is above 5,000,000 cents. The raw fee is the gross multiplied by the selected rate in basis points, divided by 10000, rounded half up to a whole cent. The `interchange_fee_cents` is then 0 when the gross is 0, and otherwise the greater of 2500 cents and that raw fee — so a non-zero but small batch is floored at a 2500-cent minimum interchange charge. The `net_payout_cents` is the gross redemptions minus the interchange fee.

This calculation is evaluated twice with two different views of "gross," which is why the batch carries both a `provisional_net_payout_cents` and a `net_payout_cents`. At **open** (the provisional view), the gross includes *every* swept redemption, even ones that a later fraud confirm will flip to `REVERSED`; the resulting provisional net is stored in `provisional_net_payout_cents`, and `net_payout_cents` is also set to this provisional view at open, together with the provisional `gross_redemptions_cents` and `interchange_fee_cents`. At **finalize** (the final view), the gross includes *only* swept redemptions still in `POSTED` status, excluding any that were reversed in the interim, which lowers both the gross and the net. Finalizing a batch is permitted only while it is `OPEN` (else `ERR_INVALID_STATE`), only when the acting `X-User-ID` differs from the batch's `opened_by_user_id` (else `ERR_SEGREGATION_OF_DUTIES`), and only when the owning merchant is `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`); on finalize the system recomputes `gross_redemptions_cents`, `interchange_fee_cents`, and `net_payout_cents` under the final view, records the officer's `X-User-ID` as `finalized_by_user_id`, moves the batch to the terminal `FINALIZED` state, and recomputes the merchant's `lifetime_net_payout_cents`.

Cancelling a batch is permitted only while it is `OPEN` (else `ERR_INVALID_STATE`); it releases the sweep by clearing `settlement_batch_id` back to null on every swept `REDEMPTION` entry, restores the merchant's `unsettled_redemptions_cents` to its pre-open value, and moves the batch to the terminal `CANCELLED` state.

### 3.8. Escheat of Unclaimed Property

When a merchant's expired cards leave residual balances, a `SettlementOfficer` files an `EscheatReport` to remit that unclaimed property to a jurisdiction. A report is created for a `merchant_id`, a `jurisdiction` code (for example `CA` or `NY`), an inclusive `period_start`, and an exclusive `period_end` (UTC); the `period_end` must be at or before the current clock, and a report whose period_end lies in the open future is rejected with `ERR_ESCHEAT_PERIOD_OPEN`. At creation the report captures the eligible cards — the merchant's cards in `EXPIRED` status whose `expires_at` falls at or after `period_start` and strictly before `period_end` — and stores the computed `escheat_total_cents` (the sum of those captured cards' balances) and `card_count` (the number captured). A report's `status` is `DRAFT` or `REMITTED`.

Remitting a report is permitted only while it is `DRAFT` (else `ERR_INVALID_STATE`) and only while the owning merchant is `ACTIVE` (else `ERR_MERCHANT_NOT_ACTIVE`); on remit each captured `EXPIRED` card transitions to the terminal `ESCHEATED` state and the system posts an `ESCHEAT_REMIT` ledger entry for any residual balance on each captured card, moving the report to the terminal `REMITTED` state.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, and the logical-clock capability — return `200 OK`. All list and single-fetch reads return `200 OK`. Request bodies, response bodies, and side effects are not repeated here; they are specified in the §3 narratives above.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/merchants` | Create a Merchant (PENDING) | PlatformAdmin |
| GET | `/merchants/{merchantId}` | Get a Merchant | Any |
| POST | `/merchants/{merchantId}/activate` | Activate a Merchant (PENDING→ACTIVE) | PlatformAdmin |
| POST | `/merchants/{merchantId}/suspend` | Suspend a Merchant (ACTIVE→SUSPENDED) | PlatformAdmin |
| POST | `/merchants/{merchantId}/reactivate` | Reactivate a Merchant (SUSPENDED→ACTIVE) | PlatformAdmin |
| POST | `/merchants/{merchantId}/close` | Close a Merchant (terminal) | PlatformAdmin |
| POST | `/card-programs` | Create a CardProgram (DRAFT) | MerchantAdmin |
| GET | `/card-programs/{cardProgramId}` | Get a CardProgram | Any |
| GET | `/card-programs` | List CardPrograms (filtered) | Any |
| POST | `/card-programs/{cardProgramId}/activate` | Activate a CardProgram (DRAFT→ACTIVE) | MerchantAdmin |
| POST | `/card-programs/{cardProgramId}/pause` | Pause a CardProgram (ACTIVE→PAUSED) | MerchantAdmin |
| POST | `/card-programs/{cardProgramId}/resume` | Resume a CardProgram (PAUSED→ACTIVE) | MerchantAdmin |
| POST | `/card-programs/{cardProgramId}/retire` | Retire a CardProgram (terminal) | MerchantAdmin |
| POST | `/card-programs/{cardProgramId}/run-maintenance` | Run expiry, dormancy, and breakage maintenance | PlatformAdmin, MerchantAdmin |
| POST | `/incentive-campaigns` | Create an IncentiveCampaign | MerchantAdmin |
| GET | `/incentive-campaigns/{incentiveCampaignId}` | Get an IncentiveCampaign | Any |
| GET | `/incentive-campaigns` | List IncentiveCampaigns (filtered) | Any |
| POST | `/card-batches` | Create a CardBatch (DRAFT) | MerchantAdmin |
| GET | `/card-batches/{cardBatchId}` | Get a CardBatch | Any |
| GET | `/card-batches` | List CardBatches (filtered) | Any |
| POST | `/card-batches/{cardBatchId}/commit` | Commit a batch: mint the gift cards (DRAFT→COMMITTED) | MerchantAdmin |
| POST | `/card-batches/{cardBatchId}/cancel` | Cancel a DRAFT batch (DRAFT→CANCELLED) | MerchantAdmin |
| GET | `/gift-cards/{giftCardId}` | Get a GiftCard | Any |
| GET | `/gift-cards/{giftCardId}/balance` | Balance API for a card | Any, POSTerminal |
| GET | `/gift-cards` | List GiftCards (filtered) | Any |
| POST | `/gift-cards/{giftCardId}/activate` | Activate a card (INACTIVE→ACTIVE) | POSTerminal, MerchantAdmin |
| POST | `/gift-cards/{giftCardId}/redeem` | Redeem value from a card | POSTerminal |
| POST | `/gift-cards/{giftCardId}/reload` | Reload value onto a card | POSTerminal, MerchantAdmin |
| GET | `/ledger-entries/{ledgerEntryId}` | Get a LedgerEntry | Any |
| GET | `/ledger-entries` | List LedgerEntries (filtered) | Any |
| POST | `/fraud-holds` | Open a fraud hold on a card | FraudAnalyst |
| GET | `/fraud-holds/{fraudHoldId}` | Get a FraudHold | Any |
| GET | `/fraud-holds` | List FraudHolds (filtered) | Any |
| POST | `/fraud-holds/{fraudHoldId}/clear` | Clear a hold (OPEN→CLEARED) | FraudAnalyst |
| POST | `/fraud-holds/{fraudHoldId}/confirm` | Confirm fraud and claw back redemptions (OPEN→CONFIRMED) | FraudAnalyst |
| POST | `/velocity-rules` | Create a VelocityRule for a program | MerchantAdmin |
| GET | `/velocity-rules/{velocityRuleId}` | Get a VelocityRule | Any |
| GET | `/velocity-rules` | List VelocityRules (filtered) | Any |
| POST | `/settlement-batches` | Open a settlement batch (OCC on Merchant.version) | SettlementOfficer |
| GET | `/settlement-batches/{settlementBatchId}` | Get a SettlementBatch | Any |
| GET | `/settlement-batches` | List SettlementBatches (filtered) | Any |
| POST | `/settlement-batches/{settlementBatchId}/finalize` | Finalize a settlement batch (OPEN→FINALIZED) | SettlementOfficer |
| POST | `/settlement-batches/{settlementBatchId}/cancel` | Cancel an OPEN settlement batch | SettlementOfficer |
| POST | `/escheat-reports` | Create an escheat report (DRAFT) | SettlementOfficer |
| GET | `/escheat-reports/{escheatReportId}` | Get an EscheatReport | Any |
| GET | `/escheat-reports` | List EscheatReports (filtered) | Any |
| POST | `/escheat-reports/{escheatReportId}/remit` | Remit an escheat report (DRAFT→REMITTED) | SettlementOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_CARD_NOT_ACTIVE` | 409 Conflict |
| `ERR_PROGRAM_NOT_ACTIVE` | 409 Conflict |
| `ERR_MERCHANT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_VELOCITY_EXCEEDED` | 409 Conflict |
| `ERR_SETTLEMENT_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CAMPAIGN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_MAX_BALANCE_EXCEEDED` | 409 Conflict |
| `ERR_BELOW_MIN_LOAD` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_BALANCE` | 409 Conflict |
| `ERR_ESCHEAT_PERIOD_OPEN` | 409 Conflict |
| `ERR_STALE_MERCHANT_VERSION` | 412 Precondition Failed |

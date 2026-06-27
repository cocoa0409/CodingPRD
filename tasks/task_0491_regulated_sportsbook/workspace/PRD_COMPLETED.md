# Regulated Sportsbook API — Product Requirements Document

## 1. Introduction

This document specifies a regulated online sportsbook platform of the kind operated under state gaming licenses across multiple US jurisdictions. The platform must reconcile two competing pressures that define the regulated betting business: it must move money quickly and accurately as bettors deposit, stake, win, lose, and withdraw, while at the same time enforcing a thick layer of compliance controls — identity verification, age and location eligibility, responsible-gaming limits, and segregation of duties between the people who set the odds and the people who declare the official results.

The system is organized around a small number of cooperating actors. Bettors register accounts, pass identity checks, prove they are physically located in a permitted state, fund their wallets, and place wagers ranging from straight singles to multi-leg parlays and same-game parlays. A trading desk publishes events, opens betting markets, prices the lines, and manages the book's risk exposure. A settlement team posts the official scores once an event concludes, which triggers a cascade that grades every affected selection, every bet leg, every bet, and every downstream money movement and bonus obligation. A compliance team verifies identities and wields the responsible-gaming tools, up to and including permanent self-exclusion.

Because every balance-touching write must be serialized against a stale view of an account, and because a single settlement can fan out into dozens of ledger postings and bonus updates, correctness here is a matter of disciplined ordering and atomic cascades rather than isolated CRUD. The remainder of this document defines the global contract first, then the business workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response conventions, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request other than self-service account registration and the health probe must carry two HTTP headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, declaring the capacity in which they act. A request that omits either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted to perform the requested operation is rejected with `ERR_FORBIDDEN`.

The system recognizes five roles, spelled exactly as follows: `Anonymous`, `Bettor`, `TradingOps`, `SettlementAgent`, and `ComplianceOfficer`.

`Anonymous` is the unauthenticated self-service surface. It exists for one purpose only — registering a new account — and that single endpoint does not require the authentication headers.

When `X-User-Role` is `Bettor`, `X-User-ID` is the `id` of the acting `Account`; the principal is the account holder. Ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`. A `Bettor` may act only on their own account and their own bets, deposits, withdrawals, geo-checks, cooling-off and limit controls, and bonus claims; an attempt to act on another account's resources is rejected with `ERR_FORBIDDEN`.

When `X-User-Role` is `TradingOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `set_by` on each `Market` the operator creates or re-prices, but never compares it to any entity's `id`. When `X-User-Role` is `SettlementAgent`, `X-User-ID` is likewise an opaque operator identifier; the server records it as `result_posted_by` on the `Event` whose result the agent posts, but does not treat it as an entity key. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is again an opaque operator identifier; the server records it as `kyc_decided_by` on the `Account` whose KYC the officer decides, without comparing it to any entity's `id`. For all three operator roles, the recorded identifier supports the audit trail and the segregation-of-duties checks described later, not resource ownership.

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

List endpoints accept two pagination parameters, `limit` and `offset`. The `limit` defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` defaults to 0 and counts from the beginning of the result set. A request that supplies a `limit` outside the permitted band is treated as a malformed request.

Unless a specific endpoint states otherwise, list results are returned in ascending order of `created_at` — that is, oldest first. The `meta` block of every list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the full count of matching records before the page window is applied, and `has_more` is true when records beyond the current window remain.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource is assigned a server-minted `id`, a UUID with no type prefix, generated at creation and never reused. Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when it was created.

Most resources additionally carry `updated_at` and `version`. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and `version` is an integer that begins at 1 and increases by exactly 1 each time the resource is mutated. These two fields are present on `Account`, `RGControl`, `Event`, `Market`, `Selection`, `Bet`, `Promotion`, and `BonusGrant`.

Three entities are append-only event records and therefore carry only `id` and `created_at`; they have neither `updated_at` nor `version`. These are `GeoCheck` (an eligibility reading), `BetLeg` (an immutable leg snapshot, whose graded result is recorded but which is never versioned), and `LedgerEntry` (an immutable money movement). No client may mutate these records after creation, and no version field will appear on them.

### 2.5. The Logical Clock

All time-dependent behavior — age computation, geo-check expiry, cooling-off windows, rolling deposit/wager/loss windows, and market lock at event start — is evaluated against a server-controlled logical clock rather than wall-clock time. At server startup the clock reads exactly `2026-01-01T00:00:00Z`, and before any clock-setting call is made it remains at this default and never falls back to the host's real time. An operator may advance the clock by supplying a target instant in `to_iso8601`; the call responds with the new clock value as a single `now` field (an ISO 8601 UTC timestamp with three fractional digits) in the `data` object. Advancing the clock may, on the next read of an affected account, retire a lapsed cooling-off period as described in §3.

### 2.6. Optimistic Concurrency on Account Writes

Because an account's balance and status can be advanced by many independent writes, every balance-touching account write is guarded by optimistic concurrency control keyed on the account's `version`. The following operations require the caller to submit `expected_account_version` carrying the `version` of the `Account` the client last observed: posting a KYC decision, creating a responsible-gaming control, depositing, withdrawing, claiming a bonus, placing a bet, and cashing out a bet.

When a bet placement carries an `expected_account_version` that does not equal the target account's current `version`, the placement is rejected with `ERR_STALE_VERSION` (HTTP 412). The intent is concrete: a prior placement, cash-out, or KYC decision on the same account legitimately debited the balance and advanced the account version, so the current placement's view of the balance is stale, and the system refuses to debit against an out-of-date balance snapshot rather than silently overwrite it.

Likewise, when a cash-out request carries an `expected_account_version` that does not match the account's current `version`, the cash-out is rejected with `ERR_STALE_VERSION` (HTTP 412). Another balance-moving write — a settlement payout or a second placement — has advanced the account version since the client read it, so the cash-out credit would otherwise be computed against an out-of-date balance view. Every successful balance-touching account write increments the account's `version` by exactly 1, so a client must re-read the account after each such write before issuing the next. Endpoints that do not move money against an account do not take a version field.

### 2.7. Monetary Buckets, the Ledger, and Balance Derivation

All money is held in cents as signed integers and partitioned into two buckets: a withdrawable `CASH` bucket and a non-withdrawable `BONUS` bucket. Balances are never stored as authoritative scalars; they are derived from the append-only ledger. An account's `cash_balance_cents` is the sum of `amount_cents` across all of its `LedgerEntry` rows whose `bucket` is `CASH`, and its `bonus_balance_cents` is the equivalent sum over rows whose `bucket` is `BONUS`. A separate counter, `lifetime_deposits_cents`, is the sum of `amount_cents` across all `DEPOSIT` entries in the `CASH` bucket and is never decremented.

Each `LedgerEntry` records a signed `amount_cents` — negative for debits such as `STAKE` and `WITHDRAWAL`, positive for credits — and an `entry_type` drawn from `DEPOSIT`, `WITHDRAWAL`, `STAKE`, `PAYOUT`, `BONUS_GRANT`, `CASHOUT`, and `VOID_REFUND`. Entries are polymorphically linked through `ref_type`, one of `BET`, `BONUS_GRANT`, or `NONE`, and `ref_id`. When `ref_type` is `BET`, `ref_id` is the `id` of the originating `Bet` and is validated as a real bet; otherwise `ref_id` is null and only the `BET` arm of the reference is foreign-key validated.

### 2.8. Decimal Odds and Monetary Precision

American odds are converted to decimal odds with a fixed rule. For positive American odds, the decimal odds equal one plus the American odds divided by 100. For non-positive American odds (which always have magnitude at least 100), the decimal odds equal one plus 100 divided by the absolute value of the American odds. The resulting decimal odds are rounded half-up to four decimal places. This conversion runs whenever a `Selection` is created and whenever a leg snapshot is taken at placement.

Wherever the platform pays out, it computes the integer cents return by taking the floor of the product of stake and the applicable decimal odds — that is, it truncates any fractional cent rather than rounding up, so the book never rounds a potential return upward in the bettor's favor. Decimal-odds products are carried at four decimal places (round half-up) and monetary results are integer cents.

### 2.9. Nested Resource Resolution and State Preconditions

Several resources are addressed through a parent path — markets and selections under an event, deposits and controls under an account, legs under a bet. Path parameters are validated left to right: the parent must exist before the child is resolved, and any missing resource along the path yields `ERR_NOT_FOUND`. The same code covers a body that references an account, event, market, selection, bet, promotion, or grant that does not exist.

Where an operation drives a state machine, the target must already be in a valid originating state for that transition; otherwise the request is rejected with `ERR_INVALID_STATE`. The specific from-states and to-states for each lifecycle are detailed in §3.

### 2.10. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority so that the returned error is deterministic. Authentication is checked first: a missing header yields `ERR_UNAUTHENTICATED`. Role authorization is checked next, yielding `ERR_FORBIDDEN`. Resource existence is checked third (`ERR_NOT_FOUND`), and only after a referenced resource is known to exist is ownership enforced — a `Bettor` acting on an account or bet that is not their own is rejected with `ERR_FORBIDDEN`. State validity (`ERR_INVALID_STATE`) is checked fifth.

Beyond that point the responsible-gaming and compliance gates apply in this order: a permanent self-exclusion block (`ERR_RG_SELF_EXCLUDED`), then an active cooling-off block (`ERR_RG_COOLING_OFF`), then the requirement that identity be verified (`ERR_KYC_NOT_VERIFIED`), then for placement the geolocation eligibility gate (`ERR_GEO_INELIGIBLE`), then the market-open temporal gate (`ERR_MARKET_NOT_OPEN`), then parlay composition (`ERR_PARLAY_COMPOSITION_INVALID`), then duplicate-leg detection (`ERR_DUPLICATE_LEG`), then the wager limit (`ERR_WAGER_LIMIT_EXCEEDED`), then the net-loss limit (`ERR_NET_LOSS_LIMIT_EXCEEDED`), then the book risk cap (`ERR_RISK_LIMIT_EXCEEDED`), then for deposits the deposit limit (`ERR_DEPOSIT_LIMIT_EXCEEDED`), then funds availability (`ERR_INSUFFICIENT_FUNDS`), then the withdrawal wagering-requirement block (`ERR_WR_NOT_MET`), then promotion availability (`ERR_PROMO_UNAVAILABLE`). Field-level malformation — a missing required field, a bad enum member, a non-positive cents amount, or American odds whose magnitude is below 100 — is the lowest-priority structural check and surfaces as `ERR_INVALID_REQUEST`. This ordering matters: a compliance or state block must surface ahead of a later fiscal check so the bettor learns the governing reason rather than a downstream symptom.

## 3. Business Logic & Workflows

This section describes the operational workflows of the platform. The fields, thresholds, and side effects of each process are woven into the narrative of the workflow that owns them.

### 3.1. Account Onboarding, Identity, and the Parallel Account Machine

Anyone may register an account through the self-service surface by supplying a login `email`, a legal `full_name`, a `date_of_birth` as an ISO `YYYY-MM-DD` date, and a `residence_state`. The residence state must be one of the six permitted jurisdictions — `NJ`, `NY`, `PA`, `CO`, `AZ`, or `NV` — and the email must be unique and non-empty across the platform. A newly created account opens with `kyc_status` of `PENDING`, `rg_status` of `ACTIVE`, a `cash_balance_cents` and `bonus_balance_cents` of zero, and a `lifetime_deposits_cents` of zero.

An account carries two independent status dimensions that evolve on separate machines. The first is `kyc_status`, which begins `PENDING` and moves to either `VERIFIED` or `REJECTED`; `REJECTED` is terminal. The second is `rg_status`, the responsible-gaming dimension, which begins `ACTIVE` and may move to `COOLING_OFF` or to `SELF_EXCLUDED`, the latter being terminal and irreversible. The two dimensions advance without interfering with each other.

Identity verification is the exclusive province of the compliance team. When a `ComplianceOfficer` decides an account by submitting a `decision`, verifying advances `kyc_status` from `PENDING` to `VERIFIED` and rejecting advances it from `PENDING` to `REJECTED`; in both cases the officer's identifier is recorded in `kyc_decided_by` and the account's `version` increments by one. Verification additionally enforces the minimum-age rule: the account holder must be at least 21 years old, measured from `date_of_birth` against the current clock date, and an attempt to verify an underage account is rejected with `ERR_UNDERAGE`. Both the verify and reject paths require `expected_account_version` to match the account's current `version`, failing with `ERR_STALE_VERSION` otherwise. Anyone reading an account back — a `Bettor` reading their own, or compliance and trading operators reading any — sees the current derived balances and status.

### 3.2. Responsible Gaming: Limits, Cooling Off, and Self-Exclusion

The platform exposes a single control-creation workflow that backs five distinct responsible-gaming instruments, each captured as an `RGControl` row recording its owning `account_id`, its `control_type`, and bookkeeping `set_at` and `status`. The `control_type` is one of `DEPOSIT_LIMIT`, `WAGER_LIMIT`, `NET_LOSS_LIMIT`, `COOLING_OFF`, or `SELF_EXCLUSION`. For the three limit instruments the caller supplies a `period` of `DAILY` or `WEEKLY` (defaulting to `DAILY`) and a threshold `limit_cents`; the period and limit are ignored for cooling-off and self-exclusion. For a cooling-off the caller instead supplies `duration_days`. Only one control of a given type may be `ACTIVE` for an account at a time: creating a new control of a type that already has an `ACTIVE` control of the same type for that account transitions the prior control's `status` to `SUPERSEDED` and the new one opens `ACTIVE`. Every control creation increments the account's `version` by one and requires `expected_account_version` to match the current `version`, failing otherwise with `ERR_STALE_VERSION`. The created `RGControl` resource is returned with its `version` field carrying the owning account's post-increment `version` (so a client may thread it straight into the next account write), rather than the control row's own structural version.

A `Bettor` may set their own cooling-off and their own limit controls; only a `ComplianceOfficer` may impose self-exclusion. A cooling-off requires `duration_days` to be present and at least 1, rejected as `ERR_INVALID_REQUEST` otherwise. Setting a cooling-off on an `ACTIVE` account computes `cooling_off_until` as the current clock plus the supplied number of days and moves `rg_status` to `COOLING_OFF`; open bets are left untouched and only new placements are blocked. The freeze is self-clearing: when the clock reaches or passes `cooling_off_until`, the next read of the account — whether a direct account read or the implicit re-evaluation at a bet attempt — transitions `rg_status` from `COOLING_OFF` back to `ACTIVE` and clears `cooling_off_until` to null. While the freeze stands (the clock is before `cooling_off_until`), placement and deposit attempts are rejected with `ERR_RG_COOLING_OFF`.

Self-exclusion is the heaviest instrument and is permanent. A `ComplianceOfficer` may impose it on an account whether it is currently `ACTIVE` or `COOLING_OFF`; either way `rg_status` moves to `SELF_EXCLUDED` and never moves again. Imposing self-exclusion triggers a cascade in the same atomic request: every `Bet` of the account still in `PLACED` is moved to `VOIDED` and its stake is refunded by a `VOID_REFUND` `LedgerEntry` credited back to whichever bucket funded it; any `BonusGrant` of the account still `ACTIVE` is moved to `FORFEITED` and the corresponding bonus balance is zeroed via a single negative `BONUS` ledger entry whose `entry_type` is `VOID_REFUND` and whose magnitude equals the whole remaining bonus balance (so when several grants forfeit at once, only the first posts the zeroing entry and the rest post none). The account `version` increments by one. Once an account is `SELF_EXCLUDED`, any attempt to place a bet, deposit, or claim a bonus is permanently rejected with `ERR_RG_SELF_EXCLUDED`. An account's controls can be listed back by their owner or by compliance, filterable by `status`.

### 3.3. Funding the Wallet: Deposits and Withdrawals

Depositing cash requires a verified, active account. A `Bettor` deposits into their own account by supplying `amount_cents` and `expected_account_version`. The deposit is refused unless `kyc_status` is `VERIFIED` (otherwise `ERR_KYC_NOT_VERIFIED`) and the account's responsible-gaming status is genuinely active — a self-excluded account yields `ERR_RG_SELF_EXCLUDED` and a cooling-off account yields `ERR_RG_COOLING_OFF`, after the automatic cooling-off-to-active re-evaluation has had its chance to run. If the account carries an `ACTIVE` `DEPOSIT_LIMIT` control, the platform enforces a gross rolling-window check before accepting the funds: it sums the `amount_cents` of every `DEPOSIT` entry in the `CASH` bucket whose `created_at` falls after the window start and at or before the current clock, where the window start is the current clock minus the period length — 86,400 seconds for a `DAILY` period and 604,800 seconds for a `WEEKLY` period. If that windowed total plus the new deposit would exceed the control's `limit_cents`, the deposit is rejected with `ERR_DEPOSIT_LIMIT_EXCEEDED`; a total exactly equal to the limit is allowed, since the boundary is a strict greater-than. A successful deposit appends a positive `DEPOSIT` ledger entry to the `CASH` bucket, raising both `cash_balance_cents` and `lifetime_deposits_cents`, and increments the account `version` by one.

Withdrawals run the opposite direction but are gated more tightly. A withdrawal requires `kyc_status` of `VERIFIED` and draws only from the `CASH` bucket. The requested `amount_cents` may not exceed the available `cash_balance_cents`; an overdraft attempt is rejected with `ERR_INSUFFICIENT_FUNDS`. Crucially, a withdrawal is blocked while the account holds any `ACTIVE` `BonusGrant` whose wagering requirement is not yet met — funds cannot be withdrawn out from under an unmet bonus obligation — and such an attempt is rejected with `ERR_WR_NOT_MET`. A successful withdrawal appends a negative `WITHDRAWAL` ledger entry to the `CASH` bucket, lowering `cash_balance_cents`, and requires and consumes a matching `expected_account_version`, incrementing the account `version` by one. Both the per-account ledger and a cross-account ledger view are available to compliance and trading for audit; the per-account view filters by `entry_type` and `bucket`, while the global view filters by `ref_id` and `account_id` to trace a movement back to its originating bet.

### 3.4. Geolocation Eligibility

Before a bettor can wager, the platform must be satisfied that they are physically within a permitted jurisdiction. A `Bettor` self-submits a geolocation reading for their own account, supplying the `detected_state` the provider reported, the reported horizontal accuracy radius `accuracy_meters`, and an optional `is_vpn_suspected` flag that defaults to false. The detected state may be any of `NJ`, `NY`, `PA`, `CO`, `AZ`, `NV`, `FL`, `TX`, `CA`, or `INTL`, but only the first six are permitted for betting. The server computes two derived fields and stores them on the immutable `GeoCheck`: `eligible` is true only when the detected state is one of the permitted betting states, the accuracy radius is at most the maximum permitted accuracy, and the VPN-suspected flag is false; and `expires_at` is the reading's creation clock time plus the geo time-to-live. A geolocation reading is good for fifteen minutes — the geo time-to-live is 900 seconds — and the maximum tolerated accuracy radius is 100 meters; a reading whose accuracy radius exceeds 100 meters is not eligible.

At placement the system consults the account's most recent geo-check: betting requires that the latest reading is eligible and that its `expires_at` is still after the current clock. If no such unexpired, eligible reading exists, placement is rejected with `ERR_GEO_INELIGIBLE`. A bettor or compliance officer may list the geo-checks recorded for an account.

### 3.5. Building the Board: Events, Markets, Selections, and Lines

The trading desk constructs the betting board. A `TradingOps` operator creates an `Event` with a `sport` of `NFL`, `NBA`, `MLB`, or `SOCCER`, a `home_team`, an `away_team`, and a scheduled `starts_at` in UTC at which markets lock. A new event opens `SCHEDULED`, with `home_score`, `away_score`, and `result_posted_by` all unset. The same operator opens markets on an event by supplying a `market_type` of `MONEYLINE`, `SPREAD`, or `TOTAL`, an optional handicap or total `line` (for example -3.5 on a spread or 47.5 on a total; left null for moneyline), and a `liability_cap_cents` that bounds how much net exposure the book will carry on that market. A market is created against the event whose identifier becomes its `event_id`; it opens `OPEN`, records the creating operator's identifier in `set_by`, and starts with a `current_liability_cents` of zero. Onto each market the operator adds selections, each belonging to that market through its `market_id` and carrying an outcome `name` such as `HOME`, `AWAY`, `OVER`, or `UNDER` and a price expressed as `american_odds`; the American odds must be nonzero and have magnitude at least 100, and the server immediately derives the decimal form. A new `Selection` opens with `result` of `PENDING`.

Lines move. A `TradingOps` operator may re-price a selection by submitting new `american_odds` while the selection's market is `OPEN` and its event still `SCHEDULED`; the selection's stored American and decimal odds update, but any `BetLeg` already snapshotted at the old price keeps its captured odds untouched. The board is browsable: events, the markets on an event, the selections on a market, and individual markets, selections, and events can all be read back, with the market read recomputing `current_liability_cents` on the fly. Markets on an event and selections on a market are listed by their reverse foreign keys, the markets list filterable by `status`.

### 3.6. The Event Lifecycle and Manual Market Control

An event walks a four-state lifecycle: `SCHEDULED`, `LIVE`, `SETTLED`, and `VOIDED`, the latter two terminal. A `TradingOps` operator advances an event from `SCHEDULED` to `LIVE` by supplying the target `to` state; the clock reaching `starts_at` does not by itself flip the stored event or market status — the `starts_at` lock is enforced lazily at bet placement only (a leg on an event whose `starts_at` is at or before the current clock is rejected with `ERR_MARKET_NOT_OPEN`), while the event remains `SCHEDULED` and its markets `OPEN` until an operator explicitly transitions them. Going live suspends betting by moving every `OPEN` market on the event to `SUSPENDED` so that no new wagers land while play is underway. The operator may instead void an event from either `SCHEDULED` or `LIVE`: voiding cascades down, moving every market on the event to `VOIDED` and every selection to `VOID`, and moving every `PLACED` bet that has any leg on the event to `VOIDED` with its stake refunded through a `VOID_REFUND` entry to the funding bucket.

Markets also have their own four-state lifecycle — `OPEN`, `SUSPENDED`, `SETTLED`, `VOIDED` — and a `TradingOps` operator can suspend or reopen one manually by supplying the target `to` state. Suspending an `OPEN` market blocks new legs from referencing its selections; the same suspension happens automatically when the event goes live or when a market's running liability climbs above its cap. Reopening a `SUSPENDED` market back to `OPEN` is conditional: it is allowed only while the event is still `SCHEDULED` — otherwise the reopen is rejected with `ERR_EVENT_LOCKED` — and only while the market's `current_liability_cents` is at or below its `liability_cap_cents`, failing with `ERR_RISK_LIMIT_EXCEEDED` if exposure already exceeds the cap. The market transitions into `SETTLED` or `VOIDED` only as a consequence of the event settling or voiding, never by direct request; on settlement its selections are graded and its `current_liability_cents` is reset to zero, and on a void its selections are set to `VOID`.

### 3.7. Placing a Bet: Composition, Compliance, and Risk

Placing a bet is the most heavily guarded operation on the platform. A `Bettor` places a wager on their own account by submitting the `account_id`, a `bet_type`, a total `stake_cents`, an optional `stake_bucket` of `CASH` or `BONUS` (defaulting to `CASH`), the set of `legs` being combined, an optional `bonus_grant_id` tying the bet to a bonus's wagering requirement, and `expected_account_version`. The bet opens in status `PLACED`.

The composition of the legs must match the declared `bet_type`. A `SINGLE` carries exactly one leg. A `PARLAY` must span at least two distinct events — its legs reference selections whose markets belong to two or more different events. A `SAME_GAME_PARLAY` is the opposite: all of its legs must reference selections whose markets share a single event. A composition that contradicts the declared type is rejected with `ERR_PARLAY_COMPOSITION_INVALID`. No two legs may reference the same `Selection`, and for a same-game parlay no two legs may sit on the same market; a violation of either rule is rejected with `ERR_DUPLICATE_LEG`. Every leg's market must be `OPEN` and its event `SCHEDULED` with a `starts_at` still in the future relative to the clock; any leg failing this temporal gate yields `ERR_MARKET_NOT_OPEN`.

Before the stake is taken, the account-level gates run: the account must not be self-excluded (`ERR_RG_SELF_EXCLUDED`), must not be in an active cooling-off after re-evaluation (`ERR_RG_COOLING_OFF`), must be KYC-verified (`ERR_KYC_NOT_VERIFIED`), and must have a current eligible geo-check (`ERR_GEO_INELIGIBLE`). The responsible-gaming limits then apply. If the account holds an `ACTIVE` `WAGER_LIMIT` control, the platform sums the gross `stake_cents` of every bet placed within the rolling window — the same daily or weekly window length used elsewhere — and rejects the placement with `ERR_WAGER_LIMIT_EXCEEDED` if that gross window total plus the new stake would exceed the control's `limit_cents`. This gross wager tally ignores winnings entirely. If the account holds an `ACTIVE` `NET_LOSS_LIMIT` control, the platform instead computes a net figure: over every bet of the account that has reached a terminal status (`WON`, `LOST`, `PUSHED`, `CASHED_OUT`, or `VOIDED`) and whose `settled_at` falls within the window, it sums each bet's `stake_cents` minus its `actual_payout_cents` — a positive contribution for a net loss, a negative one for a net win, so a winning settled bet reduces the running loss — then adds the about-to-be-placed stake as worst-case prospective loss; if that projected total exceeds the control's `limit_cents`, the placement is rejected with `ERR_NET_LOSS_LIMIT_EXCEEDED`. Both limit boundaries are strict greater-than, so a figure exactly at the limit is allowed. These two checks deliberately differ in shape: the wager limit is a gross stake tally that ignores wins, while the net-loss limit nets payouts against stakes, so for the same betting history the gross wager figure is at least as large as the net loss.

The book protects its own exposure last. The platform recomputes the market liability that the new bet would create and rejects the placement with `ERR_RISK_LIMIT_EXCEEDED` if accepting it would push any touched market's `current_liability_cents` above that market's `liability_cap_cents`. Finally, the stake must be affordable: `stake_cents` may not exceed the available balance in the named bucket — `cash_balance_cents` for a cash stake, `bonus_balance_cents` for a bonus stake — and an overspend is rejected with `ERR_INSUFFICIENT_FUNDS`. The structural floor underneath all of this is that `stake_cents` and every cents amount must be strictly positive and all required fields and enum members must be well-formed, with malformed bodies rejected as `ERR_INVALID_REQUEST`.

When a placement passes every gate, the platform snapshots each leg into an immutable `BetLeg` carrying its `bet_id`, its `selection_id`, the `odds_at_placement` copied from the selection's current American odds (immune to later line moves), and the `decimal_odds_at_placement` derived from that snapshot to four decimal places; each leg's `leg_result` opens `PENDING`. It then computes the bet's `combined_decimal_odds`: for a single, this is simply the one leg's `decimal_odds_at_placement`; for a parlay or same-game parlay, it is the product of every leg's `decimal_odds_at_placement` taken in ascending `created_at` order, where each per-leg factor is already rounded to four places and only the final product is rounded half-up to four places — intermediate partial products are never re-rounded. The `potential_payout_cents` — the gross return if every leg wins — is the floor of `stake_cents` multiplied by `combined_decimal_odds`. The stake is debited by appending a negative `STAKE` `LedgerEntry` against the chosen bucket, the touched markets' `current_liability_cents` are recomputed (which may push a market to auto-`SUSPENDED`), and the account `version` increments by one. A placed bet's `actual_payout_cents` stays zero until it is graded or cashed out.

### 3.8. The Book's Liability and Risk Cap

The running liability on a market is the book's worst-case net exposure on it. It is computed as the sum, over every bet currently in `PLACED` status that includes at least one leg whose selection belongs to this market, of that bet's `potential_payout_cents` minus its `stake_cents`. The entire bet's potential net loss is attributed to each distinct market the bet touches, with no offsetting, because a parlay can hit on all of its legs at once and the book must reserve against that worst case. This figure is what each market's `current_liability_cents` holds, what is checked against `liability_cap_cents` at placement and at manual reopen, and what is recomputed whenever a bet is placed, cashed out, voided, or settled. When a market settles or voids, its liability is released back to zero.

### 3.9. Cashing Out an Open Ticket

A `Bettor` may close out a still-open bet early through cash-out, supplying `expected_account_version`. Cash-out is only offered while the ticket is genuinely live and unresolved: the bet must be in `PLACED` status (otherwise `ERR_INVALID_STATE`), no leg may yet be graded — every leg's selection must still be `PENDING`, and a leg that has already graded yields `ERR_LEG_ALREADY_GRADED` — and no leg's market may be `SUSPENDED` nor its event `LIVE` or `SETTLED`, any of which yields `ERR_CASHOUT_UNAVAILABLE`. The `expected_account_version` must match the account's current `version`, failing with `ERR_STALE_VERSION`.

The cash-out offer is valued against current prices, not the locked placement odds, which is what makes it a different number from a settlement payout on the same ticket. The platform recomputes a current decimal-odds product by taking each leg's selection's present `american_odds`, converting each to decimal, and multiplying them in ascending `created_at` leg order, rounding the product half-up to four places. It multiplies the `stake_cents` by that current product to get a gross expected value, then applies a book retention factor of 0.92 and takes the floor, yielding the cash-out value in integer cents. That amount becomes the bet's `actual_payout_cents`, credited by a positive `CASHOUT` `LedgerEntry` to the `CASH` bucket; the bet moves to `CASHED_OUT`, its `settled_at` is stamped with the clock, the market liability it held is released, and the account `version` increments by one. A cashed-out bet that was tied to a bonus does not advance that bonus's wagering progress — the cashed-out stake never counts toward a wagering requirement.

### 3.10. Settlement: Official Results and the Grading Cascade

Settlement is the province of the `SettlementAgent`, and it is governed by a segregation-of-duties rule: the agent who posts a result must not be any of the `TradingOps` operators who priced the markets on that event. The agent posts the official outcome by supplying `home_score` and `away_score`, which must be present and be integers at or above zero (otherwise `ERR_INVALID_REQUEST`); if the posting agent's identifier matches any `set_by` recorded on a market of that event, the post is rejected with `ERR_SOD_CONFLICT`. An event may be settled only from `LIVE`. On success the scores and the agent's identifier in `result_posted_by` are recorded and the event moves to `SETTLED`, which sets off the grading cascade in one atomic step.

The cascade runs in four stages. First, every market on the event moves to `SETTLED` and each of its selections is graded `WON`, `LOST`, or `PUSH` according to that market's `market_type` and `line` against the official scores. Second, that selection grade is mirrored into the `leg_result` of every `BetLeg` sitting on those selections. Third, each bet whose legs are now all terminal is graded by recomputing its payout over the graded legs, and the resulting payout or refund ledger entries are posted. Fourth, settled qualifying bets advance their associated `BonusGrant` wagering progress.

A bet's terminal status follows from its legs. If at least one leg is `LOST`, the bet is `LOST`: its `actual_payout_cents` is zero, no payout entry is posted, and `settled_at` is stamped. If every leg resolved to `WON`, `PUSH`, or `VOID` with at least one `WON`, the bet is `WON` and is paid. If every leg is `PUSH` or `VOID` with no `WON` and no `LOST`, the whole bet is `PUSHED`: `actual_payout_cents` equals the original `stake_cents`, refunded through a `VOID_REFUND` entry to the funding bucket. The winning payout is computed by first dropping the non-winning legs — each `PUSH` or `VOID` leg is treated as decimal 1.0 and effectively removed from the parlay while each `WON` leg keeps its `decimal_odds_at_placement` — multiplying the surviving factors in ascending `created_at` leg order, rounding that effective odds half-up to four places, and taking the floor of `stake_cents` multiplied by that effective figure as the `actual_payout_cents`, credited via a `PAYOUT` `LedgerEntry`. A bet pushed in whole returns only the stake. This settlement payout is deliberately distinct from a cash-out: settlement evaluates locked placement odds over the real graded results, whereas cash-out used live current odds and the retention discount, so the two produce different numbers on an identical stake.

### 3.11. Promotions, Bonus Claims, and Wagering Requirements

The trading desk authors promotions. A `TradingOps` operator creates a `Promotion` with a unique non-empty `code`, a `bonus_cents` amount, a `wagering_multiplier` of at least 1, an optional `min_odds_american` floor that defaults to -200, and a `max_claims` cap of at least 1 on how many grants the promotion may ever issue. A promotion opens `ACTIVE` with `claims_used` at zero; its `claims_used` equals the count of `BonusGrant` rows referencing it, and it flips to `EXHAUSTED` once `claims_used` reaches `max_claims`. A promotion may also be `ENDED`. Promotions are readable individually and as a filtered list.

A `Bettor` claims a promotion on their own account by supplying a `promotion_id` and `expected_account_version`. The claim requires the account to be verified and genuinely active — a self-excluded account is refused with `ERR_RG_SELF_EXCLUDED` and an unverified one with `ERR_KYC_NOT_VERIFIED` — and the promotion must be claimable: its `status` must be `ACTIVE`, its `claims_used` must be below `max_claims`, and the account must not already hold a grant for that promotion, any failure of which is rejected with `ERR_PROMO_UNAVAILABLE`. A successful claim creates a `BonusGrant` recording the claiming `account_id` and the `promotion_id`, snapshots the promotion's bonus into the grant's own `bonus_cents`, and sets the grant's `wagering_target_cents` to that bonus times the promotion's `wagering_multiplier`. The grant opens `ACTIVE` with `wagering_progress_cents` at zero. A positive `BONUS_GRANT` `LedgerEntry` credits the `BONUS` bucket, raising `bonus_balance_cents`; the promotion's `claims_used` increments and the promotion flips to `EXHAUSTED` if that brings it to `max_claims`; and the account `version` increments by one.

Wagering progress accrues only as qualifying bets settle. When a bet carrying a `bonus_grant_id` reaches a settled outcome, the platform decides its contribution to the grant. A bet that was cashed out contributes nothing, and a bet that was voided or pushed contributes nothing. Otherwise — a bet that settled to `WON` or `LOST` — it qualifies only if its `combined_decimal_odds` meets the promotion's minimum-odds floor: the `min_odds_american` is converted to its decimal form and the bet's combined decimal odds must be at or above that floor (the boundary is inclusive). A qualifying bet contributes its full `stake_cents`; a non-qualifying one contributes zero. Note that a settled losing qualifying bet still advances the requirement — it is the act of wagering at sufficient odds, not winning, that counts. The grant's `wagering_progress_cents` is the running sum of those contributions, clamped so it never exceeds `wagering_target_cents`. When progress reaches or passes the target, the grant moves from `ACTIVE` to `COMPLETED`, and the remaining bonus balance is converted to cash by a matched ledger pair — a `BONUS` debit with `entry_type` `BONUS_GRANT` and an equal-magnitude `CASH` credit with `entry_type` `PAYOUT`, posted only when that remaining balance is strictly positive — which finally makes those funds withdrawable. A grant moves to `FORFEITED` only through the self-exclusion cascade, which zeroes its bonus balance through a negative `BONUS` entry. Bettors and compliance may read a grant, whose progress is recomputed on read, and list grants filtered by `account_id`, `promotion_id`, or `status`.

### 3.12. Audit and Read Access

Compliance and trading operators have broad read visibility for oversight. Accounts can be listed and filtered by `kyc_status` and `rg_status`. Bets can be listed and filtered by `account_id`, `bonus_grant_id`, and `status`, and an individual bet's legs can be listed by its reverse key. Bet legs can also be enumerated globally and filtered by `selection_id` or `bet_id`, and read individually, supporting the trace from a graded selection back to every ticket it touched. Ledger entries can be read individually and listed both per account and globally, the latter filterable by `ref_id` and `account_id` to follow a single bet's full money trail. These read surfaces never mutate state, except where a read intentionally refreshes a derived figure — an account read may retire a lapsed cooling-off, a market read recomputes its liability, and a bonus-grant read recomputes its progress.

## 4. Endpoint Definitions

All endpoints return the standard envelope described in §2.2. Creating a new resource returns HTTP 201; reads, list operations, and in-place transitions that modify an existing resource return HTTP 200. Error responses carry the HTTP status listed in §5. The table below names each endpoint's method, path, purpose, and the roles permitted to call it; request and response bodies are reconstructed from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Set the server logical clock | TradingOps, SettlementAgent, ComplianceOfficer |
| POST | `/accounts` | Register a new account (self-service) | Anonymous |
| GET | `/accounts/{id}` | Read an account (re-evaluates cooling-off) | Bettor, ComplianceOfficer, TradingOps |
| GET | `/accounts` | List accounts | ComplianceOfficer, TradingOps |
| POST | `/accounts/{id}/kyc-decision` | Verify or reject KYC | ComplianceOfficer |
| POST | `/accounts/{id}/rg-controls` | Create a responsible-gaming control | Bettor, ComplianceOfficer |
| GET | `/accounts/{id}/rg-controls` | List an account's RG controls | Bettor, ComplianceOfficer |
| POST | `/accounts/{id}/deposits` | Deposit cash | Bettor |
| POST | `/accounts/{id}/withdrawals` | Withdraw cash | Bettor |
| GET | `/accounts/{id}/ledger` | List an account's ledger entries | Bettor, ComplianceOfficer |
| GET | `/ledger-entries` | List ledger entries (filterable) | ComplianceOfficer, TradingOps |
| GET | `/ledger-entries/{id}` | Read a single ledger entry | ComplianceOfficer, TradingOps |
| POST | `/accounts/{id}/geo-checks` | Submit a geolocation reading | Bettor |
| GET | `/accounts/{id}/geo-checks` | List an account's geo-checks | Bettor, ComplianceOfficer |
| POST | `/events` | Create an event | TradingOps |
| GET | `/events/{id}` | Read an event | TradingOps, SettlementAgent, Bettor |
| POST | `/events/{id}/status` | Transition an event to LIVE or VOIDED | TradingOps |
| POST | `/events/{id}/result` | Post official scores and settle the event | SettlementAgent |
| POST | `/events/{id}/markets` | Create a market on an event | TradingOps |
| GET | `/events/{id}/markets` | List markets on an event | TradingOps, SettlementAgent, Bettor |
| GET | `/markets/{id}` | Read a market | TradingOps, SettlementAgent, Bettor |
| POST | `/markets/{id}/status` | Suspend or reopen a market | TradingOps |
| POST | `/markets/{id}/selections` | Add a selection to a market | TradingOps |
| GET | `/markets/{id}/selections` | List selections on a market | TradingOps, SettlementAgent, Bettor |
| GET | `/selections/{id}` | Read a selection | TradingOps, SettlementAgent, Bettor |
| PATCH | `/selections/{id}` | Re-price a selection | TradingOps |
| POST | `/bets` | Place a bet | Bettor |
| GET | `/bets/{id}` | Read a bet | Bettor, ComplianceOfficer, TradingOps |
| GET | `/bets` | List bets (filterable) | Bettor, ComplianceOfficer, TradingOps |
| GET | `/bets/{id}/legs` | List the legs of a bet | Bettor, ComplianceOfficer, TradingOps |
| GET | `/bet-legs` | List bet legs (filterable) | ComplianceOfficer, TradingOps |
| GET | `/bet-legs/{id}` | Read a single bet leg | ComplianceOfficer, TradingOps |
| POST | `/bets/{id}/cash-out` | Cash out an open bet | Bettor |
| POST | `/promotions` | Create a promotion | TradingOps |
| GET | `/promotions/{id}` | Read a promotion | TradingOps, Bettor, ComplianceOfficer |
| GET | `/promotions` | List promotions | TradingOps, Bettor, ComplianceOfficer |
| POST | `/accounts/{id}/bonus-claims` | Claim a promotion | Bettor |
| GET | `/bonus-grants/{id}` | Read a bonus grant | Bettor, ComplianceOfficer |
| GET | `/bonus-grants` | List bonus grants (filterable) | Bettor, ComplianceOfficer, TradingOps |

## 5. Error Code Catalogue

The trigger conditions for each error are described in the relevant sections of §2 and §3. The following table lists each error identifier and the HTTP status it carries.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_UNDERAGE` | 403 |
| `ERR_KYC_NOT_VERIFIED` | 403 |
| `ERR_RG_SELF_EXCLUDED` | 403 |
| `ERR_RG_COOLING_OFF` | 403 |
| `ERR_GEO_INELIGIBLE` | 403 |
| `ERR_MARKET_NOT_OPEN` | 409 |
| `ERR_PARLAY_COMPOSITION_INVALID` | 422 |
| `ERR_DUPLICATE_LEG` | 422 |
| `ERR_WAGER_LIMIT_EXCEEDED` | 403 |
| `ERR_NET_LOSS_LIMIT_EXCEEDED` | 403 |
| `ERR_RISK_LIMIT_EXCEEDED` | 409 |
| `ERR_DEPOSIT_LIMIT_EXCEEDED` | 403 |
| `ERR_INSUFFICIENT_FUNDS` | 402 |
| `ERR_WR_NOT_MET` | 409 |
| `ERR_PROMO_UNAVAILABLE` | 409 |
| `ERR_CASHOUT_UNAVAILABLE` | 409 |
| `ERR_LEG_ALREADY_GRADED` | 409 |
| `ERR_EVENT_LOCKED` | 409 |
| `ERR_SOD_CONFLICT` | 403 |

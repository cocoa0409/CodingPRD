# Kids Allowance Chore Card API — Product Requirements Document

## 1. Introduction

Families increasingly want to give children real spending experience while keeping a parent firmly in control of where the money comes from and where it goes. This document specifies the API for a parent-managed allowance and debit-card platform in the spirit of products like Greenlight and GoHenry. A parent registers a household, opens a sub-account for each child, and from there orchestrates everything: funding a household wallet, automating chore rewards, splitting money across spend, save, and give jars, issuing a debit card with per-store and per-category controls, scheduling recurring allowance transfers, paying interest on savings out of the parent's own pocket, and — for older children — enabling a teen investing add-on.

The platform is built around a small number of money-movement invariants. Every cent a child receives originates in the parent's funding wallet and is only ever moved, never minted; every card authorization first reserves money as a hold before it is finally settled or reversed; and every safety lever — suspending a family, locking a card, blocking a merchant — takes effect immediately. Because several of these levers can race against an in-flight card authorization, the card is guarded by optimistic concurrency control so that a parent never locks or restricts a card view that an authorization has already advanced underneath them. The remainder of this document defines the global contract that every endpoint shares (Section 2) and then walks through each business workflow in detail (Section 3), before summarizing the endpoint surface (Section 4) and the error catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request other than the initial family registration must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. The platform recognizes exactly three roles, spelled precisely as `Parent`, `Child`, and `PlatformAdmin`. If either header is missing or carries an unrecognized value, the request is rejected with `ERR_UNAUTHENTICATED`. When the headers are valid but the role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`. When the role is permitted in general but the acting user does not own the targeted resource, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.

The three roles relate to persisted identity in different ways. When `X-User-Role` is `Parent`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server records it — for example, it is stored as the `primary_parent_id` of a `Family` at registration time — but it does not compare it to any entity's `id`. Ownership for a parent is established through the family they created: a parent may act on a `Family` whose `primary_parent_id` equals their `X-User-ID`, and transitively on every `ChildAccount`, `Jar`, `Chore`, `ChoreCompletion`, `DebitCard`, `CardControl`, `Transaction`, `AllowanceSchedule`, `AllowanceRun`, `InterestMatchConfig`, `InterestAccrual`, `InvestmentAccount`, and `InvestmentOrder` that descends from that family. When `X-User-Role` is `Child`, `X-User-ID` is the `id` of the acting `ChildAccount`; ownership checks on any resource that references a child compare that resource's `child_account_id` (directly, or via the parent chain such as a transaction's `debit_card_id` resolving to a card whose `child_account_id` must match) to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`, and an admin is not ownership-scoped to a particular family.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps how many items are returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless an endpoint explicitly states otherwise, list results are sorted by their `created_at` timestamp in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and the Logical Clock

Almost every resource in the system carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, set once at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation of the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation; it underpins the optimistic concurrency control described in Section 2.6. One entity is deliberately leaner: the `SpendAlert` is an immutable audit record and therefore carries only `id` and `created_at`; it has neither an `updated_at` nor a `version`.

Time in this system is driven by a logical clock rather than wall-clock time. On server startup the clock reads exactly `2026-01-01T00:00:00Z`, and until it is explicitly set it never falls back to real time. An administrator can advance the clock by supplying a target instant as `to_iso8601`; the response echoes the new value as `current_utc`. The logical clock is the sole time source for deciding whether a child `is_teen`, whether an allowance schedule's `next_run_at` is due, and the `accrued_at` and `ran_at` stamps written by accruals and allowance runs.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Resources form a strict hierarchy rooted at the `Family`, descending through `ChildAccount` to jars, chores, cards, schedules, interest configuration, and investing. Several operations in this system mutate more than one resource at once, and the secondary effects matter as much as the primary one. Whenever a chore reward is paid, an allowance run executes, an interest accrual posts, a card is funded, or a transaction settles, the money movement ripples through the funding wallet, a jar, and — when the spend jar is involved — the debit card's funding state and available balance. Each resource touched by such a ripple has its own `updated_at` refreshed and its own `version` incremented; the cascade is not a single shared bump but an independent mutation of every entity in the chain. Sections 3.3, 3.5, 3.6, and 3.7 describe the specific cascades; the principle here is that none of them may be applied partially.

For any request whose URL names nested resources, the server validates the path identifiers left to right, rejecting at the first identifier that does not resolve with `ERR_NOT_FOUND`. A transaction requested under a card that does not exist fails on the card before the transaction is ever looked up.

### 2.6. Optimistic Concurrency Control on the Debit Card

The debit card is the one resource where a parent's safety action can collide with an in-flight authorization, so it is protected by optimistic concurrency control. Three write operations on a card require the caller to supply `expected_debit_card_version` carrying the `version` of the `DebitCard` the client last observed: locking the card, unlocking the card, and creating a card control. When the supplied `expected_debit_card_version` does not match the card's current `version`, the request is rejected with `ERR_STALE_CARD_VERSION` (HTTP 412).

Concretely, locking a card whose `version` has advanced since the client read it is rejected with `ERR_STALE_CARD_VERSION`: this captures the case where an authorization has already placed a hold on the card — advancing its `version` and `held_cents` — after the client read the card, so the client's "lock at this version" view is stale and the lock must be re-issued against the current `version`. Creating a `CardControl` against a stale card view is likewise rejected with `ERR_STALE_CARD_VERSION`, because a control added against a card whose `version` has already moved could silently miss authorizations that advanced it; the writer must re-read the card and re-issue against the current `version`. No other endpoint takes a version field; operations not in this trio of card writes do not perform a version check.

### 2.7. Monetary Precision and Share Accounting

All money in this system is held and moved as integer cents — there are no fractional cents and no floating-point money. Jar balances, the funding wallet, holds, available balances, rewards, allowance amounts, interest matches, and order notionals are all integer-cent quantities. Where a calculation involves division (interest proration and investment-order notional), the single division is rounded half up to whole cents; the rounding happens exactly once, at the division, never per intermediate term. Shares in the investing add-on are tracked in milli-shares, where 1000 milli-shares equal one whole share, allowing fractional-share ownership without fractional-cent drift.

### 2.8. Money-Movement Gating: Family and Child Status

Two status guards sit in front of essentially every money movement. A `Family` is either `ACTIVE` or `SUSPENDED`; suspending a family freezes all child money movement, so any chore approval, allowance run, interest accrual, or card authorization for a child of a suspended family is rejected with `ERR_FAMILY_SUSPENDED`. A `ChildAccount` is either `ACTIVE` or `ARCHIVED`; an archived child cannot earn rewards, spend, or accrue interest, and any such attempt is rejected with `ERR_CHILD_ARCHIVED`. Reactivating a family lifts the family-level freeze; archiving is a one-way action on a child.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the same failure always surfaces the same error. Authentication comes first: the presence and recognition of the `X-User-Role` and `X-User-ID` headers (`ERR_UNAUTHENTICATED`) is checked before anything else, and this applies to every endpoint except family registration. Next the system confirms the acting role is permitted for the operation (`ERR_FORBIDDEN_ROLE`), then that the acting user owns the target resource (`ERR_NOT_RESOURCE_OWNER`). Existence of every resource named in the path is verified next, left to right (`ERR_NOT_FOUND`). Then the request body is checked for well-formedness — required fields present, enum members recognized, JSON types correct (`ERR_INVALID_REQUEST`) — before semantic field bounds are checked on an otherwise well-formed body (`ERR_VALIDATION`); the bound checks require that `amount_cents`, `reward_cents`, `shares_milli`, and `price_cents_per_share` are greater than zero, that `cadence_days` is at least one, that `annual_rate_bps` is at least zero, and that `monthly_cap_cents` is at least zero.

Only after those structural checks does the system evaluate state and business rules. The card optimistic-concurrency check (`ERR_STALE_CARD_VERSION`) is evaluated before the generic state-transition check (`ERR_INVALID_STATE`) on the lock, unlock, and control-create endpoints. State-specific guards — a duplicate investing add-on (`ERR_DUPLICATE_INVEST_ACCOUNT`), an order on a closed investing account (`ERR_ACCOUNT_CLOSED`), and an accrual on a disabled interest config (`ERR_INTEREST_DISABLED`) — follow. Then come the referential status gates: family suspension (`ERR_FAMILY_SUSPENDED`) before child archival (`ERR_CHILD_ARCHIVED`). The card-safety checks run in the order card-locked (`ERR_CARD_LOCKED`), then a matching block control (`ERR_CONTROL_BLOCKED`), then a matching limit control's cap (`ERR_CONTROL_LIMIT_EXCEEDED`). The remaining business checks — teen eligibility (`ERR_NOT_TEEN_ELIGIBLE`), schedule spacing (`ERR_SCHEDULE_WINDOW_CONFLICT`), accrual-period overlap (`ERR_ACCRUAL_PERIOD_OVERLAP`), investing cash (`ERR_INSUFFICIENT_INVEST_CASH`) and shares (`ERR_INSUFFICIENT_SHARES`), funding-wallet sufficiency (`ERR_INSUFFICIENT_FUNDING`), card available funds (`ERR_INSUFFICIENT_CARD_FUNDS`), settle-amount range (`ERR_INVALID_SETTLE_AMOUNT`), and non-empty holdings at close (`ERR_HOLDINGS_NOT_EMPTY`) — are evaluated within the workflow that owns each, as described in Section 3. The recurring principle is that a more fundamental failure is never masked by a later check: a suspended family surfaces as `ERR_FAMILY_SUSPENDED` rather than as an insufficient-funds error that a later step might have raised.

## 3. Business Logic & Workflows

### 3.1. Establishing a Household and Funding the Wallet

Everything begins when a parent registers a household. Registration is the only call that does not require authentication headers in the usual way, and it is exclusive to the `Parent` role; the caller supplies a `family_name`, and the server mints the family with its `primary_parent_id` set to the caller's `X-User-ID`, a `funding_balance_cents` of zero, a `status` of `ACTIVE`, and both `large_spend_threshold_cents` and `low_balance_threshold_cents` unconfigured (each `null`) until the parent sets them. The family's `funding_balance_cents` is the parent's wallet and the origin of every cent that reaches a child: it is debited by chore reward payouts, allowance runs, and interest accruals, and credited by external deposits. A parent tops it up by depositing external money, which credits `funding_balance_cents` by the supplied `amount_cents`.

A family can be frozen and thawed. Suspending it sets `status` to `SUSPENDED` and, per Section 2.8, blocks all downstream money movement; reactivating it returns `status` to `ACTIVE`. Suspension and reactivation may be performed by the owning parent or by a `PlatformAdmin`. The parent also configures the alert thresholds that govern spend notifications by supplying `large_spend_threshold_cents` and `low_balance_threshold_cents`; these values are stored on the family and consulted whenever a card authorization decides whether to emit a spend alert, as detailed in Section 3.6.

### 3.2. Opening a Child Sub-Account and Its Jars

A parent opens a child sub-account under the family by supplying the child's `display_name` and `birthdate`. The birthdate is an ISO date used to gate teen-investing eligibility, and from it the server derives `is_teen`, a boolean that is true once the difference between the logical clock's current instant and the `birthdate` is at least thirteen years; `is_teen` is recomputed every time the child is read and again whenever investing is enabled. A new child starts with `status` of `ACTIVE` and belongs to its family through `family_id`.

Creating a child is a generative act: the server simultaneously creates exactly three jars, exactly one debit card, and exactly one interest-match configuration. The three jars are one each of `jar_type` `SPEND`, `SAVE`, and `GIVE`, each linked to the child through `child_account_id`. Every jar tracks a `balance_cents` running balance that starts at zero and is never allowed to go negative, alongside a `lifetime_credited_cents` counter that records the cumulative cents ever credited to that jar and is never decremented — it exists for give-jar reporting and grows on every credit. The three jars play distinct roles: the `SPEND` jar funds the debit card, the `SAVE` jar earns the interest match and feeds investing, and the `GIVE` jar funds donations. The debit card created alongside the child begins `UNLOCKED` and `DRAINED`, and the interest-match configuration begins disabled until a parent configures it. Listing a family's children supports an optional `status` filter, and listing a child's jars supports an optional `jar_type` filter.

Beyond chore rewards and allowance runs, a parent can move money directly. Funding a jar names a `jar_type` and an `amount_cents`; the transfer is first subject to the money-movement gates of Section 2.8 (family suspension `ERR_FAMILY_SUSPENDED` before child archival `ERR_CHILD_ARCHIVED`), then the server debits the family's `funding_balance_cents` and credits the target jar's `balance_cents`, and if the target is the `SPEND` jar, the resulting balance change recomputes the linked debit card's `funding_state` and `available_cents`. A direct fund-jar transfer requires the family wallet to hold enough money; if `funding_balance_cents` is below the requested `amount_cents`, the transfer is rejected with `ERR_INSUFFICIENT_FUNDING`. Archiving a child sets its `status` to `ARCHIVED`, after which the child can no longer earn, spend, or accrue.

### 3.3. The Chore-to-Reward Pipeline

Chores are the engine of reward automation, and the pipeline deliberately separates the chore template from each attempt at it. A parent creates a `Chore` for a child by supplying a `title` and a `reward_cents`, optionally a `payout_jar_type` and an `is_recurring` flag. The `reward_cents` is the amount paid on approval and must be greater than zero. The `payout_jar_type` decides which jar the reward credits — one of `SPEND`, `SAVE`, or `GIVE` — and defaults to `SPEND` when omitted. The `is_recurring` flag defaults to false and decides the chore's fate after a completion is paid: a recurring chore returns to `AVAILABLE` to be done again, while a one-shot chore moves to `ARCHIVED`. A freshly created chore has `status` `AVAILABLE`. Listing a child's chores supports an optional `status` filter.

A chore moves through its own state machine. When a child submits a chore as done, it transitions from `AVAILABLE` to `SUBMITTED`, but only while the chore is `AVAILABLE` and the child account is `ACTIVE`; the chore-state guard is evaluated first, so a chore not in `AVAILABLE` is rejected with `ERR_INVALID_STATE` and an `AVAILABLE` chore belonging to an archived child is rejected with `ERR_CHILD_ARCHIVED`. Submission also creates a `ChoreCompletion` in `PENDING_REVIEW`. That completion captures a `reward_cents_snapshot` copied from the chore's `reward_cents` and a `payout_jar_type_snapshot` copied from the chore's `payout_jar_type` at submission time, so that the amount eventually paid is immune to any later edit of the chore. Each completion is linked to its chore through `chore_id` and carries a denormalized `child_account_id` equal to the chore's owning child; completions for a chore are discovered by listing that chore's completions. A completion also tracks a `revision_count` that starts at zero.

The completion is the unit a parent reviews, and it follows a cyclic state machine. A parent may kick a completion back for revision, moving it from `PENDING_REVIEW` to `NEEDS_REVISION`; this moves no money and is permitted only while the completion is `PENDING_REVIEW` and the acting parent owns the family of the completion's child. The child then resubmits, moving the completion from `NEEDS_REVISION` back to `PENDING_REVIEW`, permitted only while it is `NEEDS_REVISION` and the acting child is the completion's `child_account_id`; each resubmission increments `revision_count` by one. The kick-back and resubmit pair can repeat, and `revision_count` grows by one on every loop. A parent may instead deny a completion, moving it from `PENDING_REVIEW` to `DENIED`; denial moves no money and additionally transitions the parent chore to `REJECTED`. A rejected chore stays rejected until the parent reopens it, which returns the chore from `REJECTED` to `AVAILABLE`.

Approval is the payout event and the system's deepest cascade. A parent approves a completion only while it is `PENDING_REVIEW`; approval additionally requires that the family is `ACTIVE`, that the child account is `ACTIVE`, and that the family's `funding_balance_cents` is at least the completion's `reward_cents_snapshot`. If the family is suspended the approval fails with `ERR_FAMILY_SUSPENDED`; if the child is archived it fails with `ERR_CHILD_ARCHIVED`; if the wallet cannot cover the snapshot it fails with `ERR_INSUFFICIENT_FUNDING`; and a completion not in `PENDING_REVIEW` fails the state check with `ERR_INVALID_STATE`. When approval proceeds it pays the reward in three cascading steps: first the family's `funding_balance_cents` is reduced by `reward_cents_snapshot`; second the child's jar of the snapshot's `payout_jar_type_snapshot` has its `balance_cents` increased by `reward_cents_snapshot`, which is the step that actually mutates the jar; and third that jar credit raises the jar's `lifetime_credited_cents`, and if the credited jar is the `SPEND` jar the balance change recomputes the debit card's `funding_state` and `available_cents`. The completion's `status` becomes `PAID`, and the parent chore bubbles up automatically: a chore in `SUBMITTED` advances to a transient `APPROVED` state that resolves immediately, returning the chore to `AVAILABLE` if it is recurring, or moving it to `ARCHIVED` if it is not. (Symmetrically, when a completion is denied, the parent chore moves from `SUBMITTED` to `REJECTED`.) A parent may also delete a chore outright while it is `AVAILABLE` or `REJECTED`, which soft-archives it to `ARCHIVED` and excludes it from default chore lists.

### 3.4. Scheduled Allowance Transfers

A parent can automate recurring pocket money by creating an allowance schedule on a child. The schedule names an `amount_cents` to transfer each run, optionally a `payout_jar_type` that defaults to `SPEND`, a `cadence_days` of at least one that sets how far apart runs fall, and a `next_run_at` instant at which the first run becomes due. The schedule starts `ACTIVE`, and a run is considered due once the logical clock reaches or passes its `next_run_at`. To prevent overlapping pocket-money streams, a new active schedule must be spaced from every existing active schedule on the same child that shares the same `payout_jar_type`: the absolute gap between the new schedule's `next_run_at` and each such existing schedule's `next_run_at` must be at least seven days, measured as a closed buffer so that schedules positioned exactly seven days apart are accepted while anything tighter is rejected with `ERR_SCHEDULE_WINDOW_CONFLICT`. Listing a child's schedules supports an optional `status` filter.

A schedule can be paused, resumed, and cancelled. Pausing moves it from `ACTIVE` to `PAUSED`, and paused schedules are skipped by the run sweep. Resuming moves it from `PAUSED` back to `ACTIVE` and leaves `next_run_at` unchanged, making it eligible again. Cancelling moves it from either `ACTIVE` or `PAUSED` to `CANCELLED`, after which no further runs occur.

Runs are driven by a test-driving sweep that an administrator triggers. The sweep finds every schedule whose `status` is `ACTIVE` and whose `next_run_at` is at or before the current clock, and for each due schedule whose family is `ACTIVE` it records an `AllowanceRun`. Each run snapshots the schedule's `amount_cents`, stamps `ran_at` with the logical clock value, and links back to its schedule through `allowance_schedule_id`. The run's `outcome` depends on funds: if the family's `funding_balance_cents` is at least the schedule's `amount_cents`, the run debits the funding wallet, credits the schedule's payout jar, and records `EXECUTED`; otherwise it records `SKIPPED_INSUFFICIENT_FUNDS` and moves no money. Either way the schedule's `next_run_at` advances by `cadence_days`, so a skipped run does not stall the cadence. When the payout jar is the `SPEND` jar and the run executed, the card's funding state and available balance are recomputed. A due schedule whose family is not `ACTIVE` is silently skipped by the sweep, recording no run and surfacing no error. The sweep returns a `200 OK` array response whose `data` is the list of `AllowanceRun` records created in this sweep (empty when nothing was due), ordered by `created_at` ascending and paginated like any list endpoint. An executed run conserves money exactly: the family wallet plus the sum of all of a child's jar balances after the run equals the same total before the run — a run only moves money between the wallet and the jars and never creates it. The runs of a schedule can be listed for audit.

### 3.5. The Debit Card, Its Controls, and the Spend Lifecycle

Each child has exactly one debit card, created with the child and linked through `child_account_id`. The card carries two independent state dimensions that evolve separately. The `lock_state` dimension is `UNLOCKED` or `LOCKED` and gates spending outright: a locked card rejects every authorization regardless of funding. The `funding_state` dimension is `FUNDED` or `DRAINED` and is purely system-driven, flipping to `FUNDED` whenever the linked `SPEND` jar's `balance_cents` is greater than zero and to `DRAINED` whenever that balance becomes zero; it is recomputed on every spend-jar balance change and evolves independently of the lock, so even a locked card may flip between `FUNDED` and `DRAINED`. The card also exposes two computed money fields: `held_cents` is the sum of `amount_cents` across all pending authorization transactions on the card and represents money reserved but not yet spent, and `available_cents` is the linked spend jar's `balance_cents` minus `held_cents`, never allowed to go negative — it is the truly spendable amount.

Locking and unlocking are deliberate safety actions guarded by optimistic concurrency. Locking moves `lock_state` from `UNLOCKED` to `LOCKED` and may be performed by the owning parent or the child; unlocking moves it from `LOCKED` back to `UNLOCKED` and is reserved to the parent. Both require `expected_debit_card_version` to match the card's current `version`, both reject a mismatch with `ERR_STALE_CARD_VERSION`, and both increment the card's `version` by one on success. A lock attempt on an already-locked card, or an unlock on an already-unlocked card, fails the state check with `ERR_INVALID_STATE`.

A parent shapes where the card may be used through card controls. A control names a `control_kind` of either `STORE` or `CATEGORY`, a `match_value`, and a `rule` of either `BLOCK` or `LIMIT`. A `STORE` control matches a specific `merchant_id` and a `CATEGORY` control matches a merchant category code such as `GAMING` or `FOOD`, with the matched merchant or category supplied in `match_value`. A `BLOCK` rule denies any matching authorization outright. A `LIMIT` rule instead caps cumulative matching spend at a `per_period_cap_cents`, which is required when the rule is `LIMIT` and ignored when the rule is `BLOCK` (it defaults to zero). Creating a control requires `expected_debit_card_version` to match the card's current `version` and is rejected with `ERR_STALE_CARD_VERSION` on a mismatch; on success the control is created with `is_active` true and the card's `version` increments by one. Controls can be listed with an optional `is_active` filter and soft-deactivated by deletion, which sets `is_active` to false; inactive controls are skipped at authorization time.

Spending happens through an authorization. The child (or an administrator) authorizes a spend by supplying a `merchant_id`, a `category`, an `amount_cents` greater than zero, and optionally a `record_decline` flag. The authorization passes through a gauntlet of checks before it can place a hold. The card must be `UNLOCKED`, or the authorization is rejected with `ERR_CARD_LOCKED`. The family must be `ACTIVE`, or it is rejected with `ERR_FAMILY_SUSPENDED`. No active `BLOCK` control may match the transaction's `merchant_id` (for a `STORE` control) or `category` (for a `CATEGORY` control), or it is rejected with `ERR_CONTROL_BLOCKED`. For every active `LIMIT` control that matches, the cumulative spend already committed plus this `amount_cents` must not exceed that control's `per_period_cap_cents`, or it is rejected with `ERR_CONTROL_LIMIT_EXCEEDED`. The cumulative spend for a limit is the sum of `amount_cents` across all transactions on the card whose `status` is either `PENDING` or `SETTLED` and that match the control's dimension — a `STORE` control sums transactions whose `merchant_id` equals its `match_value`, and a `CATEGORY` control sums transactions whose `category` equals its `match_value`. A single transaction can be counted independently under both a matching `STORE` limit and a matching `CATEGORY` limit. Finally the card's `available_cents` must be at least the `amount_cents`, or the authorization is rejected with `ERR_INSUFFICIENT_CARD_FUNDS`.

When all checks pass, the authorization creates a `Transaction` in `PENDING` status and places a hold: the hold reserves the full `amount_cents`, so the card's `held_cents` is increased by `amount_cents`, the spend jar's `balance_cents` is not yet touched, and `available_cents` drops by `amount_cents`. The transaction records the `merchant_id`, `category`, and `amount_cents` supplied at authorization, carries a `settled_amount_cents` that starts at zero, and a denormalized `child_account_id` equal to the card's child. Each authorization increments the card's `version` by one. If an authorization precondition fails and the caller set `record_decline` to true, the system instead records a `Transaction` in `DECLINED` status with no hold and no jar movement; absent that flag, a failed precondition simply returns the relevant error without persisting a transaction row. Transactions on a card can be listed with an optional `status` filter.

Settlement and reversal are administrator actions that resolve a pending hold, and they differ precisely in their effect on the jar. Settling a pending transaction supplies a final `settled_amount_cents` that must be greater than zero and at most the original `amount_cents`; a value outside that range is rejected with `ERR_INVALID_SETTLE_AMOUNT`. Settlement cascades in three steps: first the hold is released, reducing the card's `held_cents` by the original `amount_cents`; second the spend jar's `balance_cents` is debited by the `settled_amount_cents`, which may be less than the original authorization; and third the resulting spend-jar balance change recomputes the card's `funding_state` and `available_cents`, possibly flipping `FUNDED` to `DRAINED`. The net effect on `available_cents` differs from the original reservation by exactly the gap between the authorized `amount_cents` and the settled `settled_amount_cents`. The transaction's `status` becomes `SETTLED` and the card's `version` increments by one. Reversing a pending transaction instead releases the hold — reducing `held_cents` by the original `amount_cents` — without ever debiting the spend jar, recomputes the card's `funding_state` and `available_cents`, sets `status` to `REVERSED`, and increments the card's `version` by one. Reversal is a true compensation: authorizing then reversing must leave the spend jar's `balance_cents` exactly as it was before the authorization and must leave the card's `held_cents` exactly as it was before the authorization, with no drift in either quantity. Both settle and reverse require the transaction to be `PENDING`; otherwise the state check rejects with `ERR_INVALID_STATE`.

### 3.6. Real-Time Spend Alerts

Spend alerts are emitted as a side effect of authorization and are immutable once written. At the moment a hold is placed, the system compares the authorization against the family's configured thresholds. If the `large_spend_threshold_cents` is configured and the `amount_cents` is at least that threshold, a spend alert of `alert_kind` `LARGE_SPEND` is emitted. If the `low_balance_threshold_cents` is configured and, after the hold is placed, the card's `available_cents` is below that threshold, a spend alert of `alert_kind` `LOW_BALANCE` is emitted. A threshold left unconfigured (`null`) emits no alert of its kind, so an authorization on a family that never set its thresholds produces no spend alerts at all. Each alert links to its transaction through `transaction_id`, carries a denormalized `child_account_id` equal to the transaction's child, records the triggering `amount_cents`, and stamps `created_at`. Because both conditions can hold at once, a single authorization may produce both a `LARGE_SPEND` and a `LOW_BALANCE` alert. The alerts emitted for a transaction can be listed for review by a parent or administrator.

### 3.7. Parent-Paid Savings Interest Match

The save jar earns interest that the parent pays out of the family wallet. Each child is created with exactly one interest-match configuration, which the parent activates by supplying an `annual_rate_bps` (a parent-paid annual rate in basis points, where 100 basis points equal one percent), a `monthly_cap_cents` (the maximum match credited per accrual period, where zero means uncapped), and an `accrual_method`. Configuring the interest match sets its `status` to `ENABLED`; an enabled configuration is required before any accrual, and accruing on a disabled configuration is rejected with `ERR_INTEREST_DISABLED`. The configuration links to its child through `child_account_id`.

Posting an accrual credits the save jar with a parent-paid match and debits the family wallet by the same amount. The accrual is computed from the save jar balance, the rate, and a `period_days` supplied in the accrue payload. The raw interest in cents is the base balance multiplied by `annual_rate_bps`, multiplied by `period_days`, divided by the product of ten thousand and three hundred sixty-five, with that single division rounded half up to whole cents. The matched amount equals that raw interest, except that when `monthly_cap_cents` is greater than zero the matched amount is the smaller of the raw interest and `monthly_cap_cents`. The resulting `matched_cents` is credited to the save jar's `balance_cents` and debited from the family's `funding_balance_cents`; if the wallet cannot cover the match, the accrual is rejected with `ERR_INSUFFICIENT_FUNDING`. The accrual records `period_days`, the `matched_cents` actually credited, an `accrued_at` stamp equal to the logical clock at posting time, and a computed `period_start_at` equal to `accrued_at` minus `period_days` days; the covered window is the half-open interval running from `period_start_at` (exclusive) to `accrued_at` (inclusive). Each accrual carries a denormalized `child_account_id` and links to its configuration through `interest_match_config_id`; accruals for a configuration can be listed.

The base balance the calculation uses depends on the configuration's `accrual_method`, which selects between two variants with equal force. Under `WHOLE_PERIOD`, the base is the save jar's `balance_cents` observed at accrual time — a period-end snapshot. Under `DAILY_AVERAGE`, the base is the time-weighted average save-jar balance across the period, supplied by the caller as `avg_balance_cents` in the accrue payload; this produces a different match than `WHOLE_PERIOD` for the same end balance whenever the jar grew mid-period. The `avg_balance_cents` field is read only under `DAILY_AVERAGE`, and when it is omitted (or `null`) the base falls back to the save jar's `balance_cents` observed at accrual time, exactly as under `WHOLE_PERIOD`. Both variants then apply the same rate proration and the same cap.

Accruals on a single configuration may not overlap in time. The new accrual's half-open window starts at the current clock minus `period_days` days and ends at the current clock. Against the latest prior accrual on the same configuration — the one with the greatest `accrued_at`, breaking ties by the greatest `created_at` — the new window's start must be at or after that prior accrual's `accrued_at`. If the new window's start falls strictly before the latest prior `accrued_at`, the accrual would back-date into an already-covered period and is rejected with `ERR_ACCRUAL_PERIOD_OVERLAP`; a new window whose start lands exactly on the prior accrual's `accrued_at` is adjacent and is allowed.

### 3.8. The Teen Investing Add-On

For older children, a parent can enable a teen investing add-on. Enabling it creates an `InvestmentAccount` for the child, but only when the child `is_teen` — that is, at least thirteen years old measured against the logical clock — the child account is `ACTIVE`, and no investing account already exists for the child. A child under thirteen is rejected with `ERR_NOT_TEEN_ELIGIBLE`, and a second attempt to enable investing for the same child is rejected with `ERR_DUPLICATE_INVEST_ACCOUNT`. A new account starts `ACTIVE` with `cash_cents` of zero and empty `holdings`; it links to its child through `child_account_id`. The `cash_cents` field is uninvested cash inside the account, funded from the save jar, drained by buys and credited by sells. The `holdings` field is a map from ticker symbol to a structure carrying `shares_milli`, the share count in thousandths of a share.

A parent funds the investing account by moving money from the save jar: the supplied `amount_cents` debits the save jar's `balance_cents` and credits the account's `cash_cents`; this intra-child transfer is not subject to the family-suspension or child-archival gates of Section 2.8, and it requires the save jar to hold enough money — a save jar balance below `amount_cents` is rejected with `ERR_INSUFFICIENT_FUNDING`. Orders are then placed by the parent or the child against an active account; an order on a closed account is rejected with `ERR_ACCOUNT_CLOSED`. An order names a `side` of `BUY` or `SELL`, a `symbol`, a `shares_milli` greater than zero, and a `price_cents_per_share` quoting the price per whole share in cents at order time. The order's notional, `gross_cents`, is computed by multiplying `shares_milli` by `price_cents_per_share`, dividing by one thousand, and rounding half up to whole cents; the rounding is done exactly once over the whole order, never per share and then summed. A `BUY` requires the account's `cash_cents` to be at least `gross_cents` — otherwise it is rejected with `ERR_INSUFFICIENT_INVEST_CASH` — and on success reduces `cash_cents` by `gross_cents` and increases the symbol's `shares_milli` in `holdings` by the ordered `shares_milli`. A `SELL` requires the symbol's held `shares_milli` to be at least the ordered `shares_milli` — otherwise it is rejected with `ERR_INSUFFICIENT_SHARES` — and on success reduces the symbol's `shares_milli` by the ordered amount and increases `cash_cents` by `gross_cents`. A filled order records `status` `FILLED`, links back to its account through `investment_account_id`, and exposes its computed `gross_cents`; orders can be listed with an optional `side` filter.

Closing the account is the terminal action. It is permitted only when the account is `ACTIVE` and every symbol in `holdings` is empty — that is, every symbol's `shares_milli` is zero; an attempt to close with any non-empty holding is rejected with `ERR_HOLDINGS_NOT_EMPTY`. On close the account's `status` becomes `CLOSED`, any remaining `cash_cents` is swept back into the child's save jar `balance_cents`, and because the save jar does not fund the card, nothing is recomputed on the card.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code; operations that read or modify an existing resource return a `200 OK` status code. All paths are mounted at the service root. The request body, response body, and side effects of each endpoint are described in Section 3 and are not repeated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/families` | Register a family | Parent |
| GET    | `/families/{id}` | Read a family | Parent, PlatformAdmin |
| POST   | `/families/{id}/deposit` | Deposit external money into the funding wallet | Parent |
| POST   | `/families/{id}/alert-thresholds` | Configure spend alert thresholds | Parent |
| POST   | `/families/{id}/suspend` | Suspend a family | Parent, PlatformAdmin |
| POST   | `/families/{id}/reactivate` | Reactivate a suspended family | Parent, PlatformAdmin |
| POST   | `/families/{id}/child-accounts` | Create a child sub-account | Parent |
| GET    | `/families/{id}/child-accounts` | List children of a family | Parent, PlatformAdmin |
| GET    | `/child-accounts/{id}` | Read a child account | Parent, Child, PlatformAdmin |
| POST   | `/child-accounts/{id}/archive` | Archive a child account | Parent |
| POST   | `/child-accounts/{id}/fund-jar` | Move money from the wallet into a jar | Parent |
| GET    | `/child-accounts/{id}/jars` | List the child's jars | Parent, Child, PlatformAdmin |
| GET    | `/jars/{id}` | Read a jar | Parent, Child, PlatformAdmin |
| POST   | `/child-accounts/{id}/chores` | Create a chore | Parent |
| GET    | `/child-accounts/{id}/chores` | List chores for a child | Parent, Child, PlatformAdmin |
| GET    | `/chores/{id}` | Read a chore | Parent, Child, PlatformAdmin |
| POST   | `/chores/{id}/submit` | Submit a chore as done | Child |
| POST   | `/chores/{id}/reopen` | Reopen a rejected chore | Parent |
| DELETE | `/chores/{id}` | Soft-archive a chore | Parent |
| GET    | `/chores/{id}/completions` | List completions for a chore | Parent, Child, PlatformAdmin |
| GET    | `/chore-completions/{id}` | Read a chore completion | Parent, Child, PlatformAdmin |
| POST   | `/chore-completions/{id}/approve` | Approve a completion and pay the reward | Parent |
| POST   | `/chore-completions/{id}/kick-back` | Kick a completion back for revision | Parent |
| POST   | `/chore-completions/{id}/resubmit` | Resubmit a kicked-back completion | Child |
| POST   | `/chore-completions/{id}/deny` | Deny a completion | Parent |
| GET    | `/child-accounts/{id}/debit-cards` | List the child's debit card(s) | Parent, Child, PlatformAdmin |
| GET    | `/debit-cards/{id}` | Read a debit card | Parent, Child, PlatformAdmin |
| POST   | `/debit-cards/{id}/lock` | Lock a card | Parent, Child |
| POST   | `/debit-cards/{id}/unlock` | Unlock a card | Parent |
| POST   | `/debit-cards/{id}/controls` | Add a store/category control | Parent |
| GET    | `/debit-cards/{id}/controls` | List controls on a card | Parent, Child, PlatformAdmin |
| DELETE | `/card-controls/{id}` | Soft-deactivate a card control | Parent |
| POST   | `/debit-cards/{id}/authorizations` | Authorize a card spend | Child, PlatformAdmin |
| GET    | `/debit-cards/{id}/transactions` | List transactions on a card | Parent, Child, PlatformAdmin |
| GET    | `/transactions/{id}` | Read a transaction | Parent, Child, PlatformAdmin |
| POST   | `/transactions/{id}/settle` | Settle a pending authorization | PlatformAdmin |
| POST   | `/transactions/{id}/reverse` | Reverse a pending authorization | PlatformAdmin |
| GET    | `/transactions/{id}/alerts` | List spend alerts for a transaction | Parent, PlatformAdmin |
| POST   | `/child-accounts/{id}/allowance-schedules` | Create a scheduled allowance transfer | Parent |
| GET    | `/child-accounts/{id}/allowance-schedules` | List allowance schedules for a child | Parent, Child, PlatformAdmin |
| GET    | `/allowance-schedules/{id}` | Read an allowance schedule | Parent, Child, PlatformAdmin |
| POST   | `/allowance-schedules/{id}/pause` | Pause a schedule | Parent |
| POST   | `/allowance-schedules/{id}/resume` | Resume a paused schedule | Parent |
| DELETE | `/allowance-schedules/{id}` | Cancel a schedule | Parent |
| GET    | `/allowance-schedules/{id}/runs` | List runs of a schedule | Parent, PlatformAdmin |
| POST   | `/_scheduler/run-due-allowances` | Run all due allowance schedules | PlatformAdmin |
| GET    | `/child-accounts/{id}/interest-match-config` | Read the child's interest match config | Parent, Child, PlatformAdmin |
| GET    | `/interest-match-configs/{id}` | Read an interest match config | Parent, Child, PlatformAdmin |
| PUT    | `/interest-match-configs/{id}` | Configure and enable the interest match | Parent |
| POST   | `/interest-match-configs/{id}/accrue` | Post one interest accrual | Parent, PlatformAdmin |
| GET    | `/interest-match-configs/{id}/accruals` | List accruals for a config | Parent, PlatformAdmin |
| POST   | `/child-accounts/{id}/investment-account` | Enable the teen investing add-on | Parent |
| GET    | `/child-accounts/{id}/investment-account` | Read the child's investment account | Parent, Child, PlatformAdmin |
| GET    | `/investment-accounts/{id}` | Read an investment account | Parent, Child, PlatformAdmin |
| POST   | `/investment-accounts/{id}/fund` | Move money from the save jar into investing cash | Parent |
| POST   | `/investment-accounts/{id}/orders` | Place a buy/sell order | Parent, Child |
| GET    | `/investment-accounts/{id}/orders` | List orders | Parent, Child, PlatformAdmin |
| POST   | `/investment-accounts/{id}/close` | Close the investing account | Parent |
| POST   | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_CARD_VERSION` | 412 Precondition Failed |
| `ERR_FAMILY_SUSPENDED` | 409 Conflict |
| `ERR_CHILD_ARCHIVED` | 409 Conflict |
| `ERR_CARD_LOCKED` | 409 Conflict |
| `ERR_CONTROL_BLOCKED` | 409 Conflict |
| `ERR_CONTROL_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_NOT_TEEN_ELIGIBLE` | 409 Conflict |
| `ERR_INSUFFICIENT_INVEST_CASH` | 409 Conflict |
| `ERR_INSUFFICIENT_SHARES` | 409 Conflict |
| `ERR_INSUFFICIENT_FUNDING` | 409 Conflict |
| `ERR_INSUFFICIENT_CARD_FUNDS` | 409 Conflict |
| `ERR_INVALID_SETTLE_AMOUNT` | 422 Unprocessable Entity |
| `ERR_HOLDINGS_NOT_EMPTY` | 409 Conflict |
| `ERR_ACCOUNT_CLOSED` | 409 Conflict |
| `ERR_DUPLICATE_INVEST_ACCOUNT` | 409 Conflict |
| `ERR_INTEREST_DISABLED` | 409 Conflict |
| `ERR_ACCRUAL_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SCHEDULE_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_VALIDATION` | 422 Unprocessable Entity |

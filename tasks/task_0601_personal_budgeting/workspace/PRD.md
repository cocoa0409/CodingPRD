# Personal Budgeting API — Product Requirements Document

## 1. Introduction

This document specifies the Personal Budgeting & Account Aggregation API, a backend platform in the tradition of tools such as Mint, YNAB, and Monarch Money. Households link their bank, credit, loan, and investment accounts through an aggregation provider; transactions flow in, are automatically categorized, and are tallied against zero-based envelope budgets. On top of that ledger the platform layers a recurring-bill calendar with cash-flow forecasting, goal and sinking-fund tracking, a household-wide net-worth rollup, and a shared multi-member ledger with overspend awareness and month-to-month category rollover.

The platform's defining tension is consistency. Every monetary figure the household sees — an envelope's remaining balance, the household's net worth, whether the budget is healthy or overspent — is a *derived* quantity reconciled from primary records. A single transaction post can ripple through an envelope's spent total, the owning account's balances, the household's two net-worth figures, and the household's overall posture. The API therefore treats reconciliation as a first-class concern: derived fields are recomputed immediately and deterministically after every mutating event, and the system refuses operations that would leave the ledger internally inconsistent. All monetary amounts in the system are integer minor units (cents) in the household's chosen currency; there is no floating-point money anywhere in the contract.

A second theme is *posture-driven gating*. A household that an owner has frozen, or that has an overspent envelope, is in a degraded posture, and certain spend-affecting writes are blocked accordingly. The sections that follow define the data model implicitly through the workflows that touch it, the reconciliation rules that keep derived state honest, and the access-control and concurrency rules that keep a shared, multi-actor ledger trustworthy.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contracts, and cross-cutting principles that apply across the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. If `X-User-Role` is missing or is not one of the recognized role names, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly three roles, spelled precisely as follows: `HouseholdOwner`, `HouseholdMember`, and `PlatformAdmin`. When a recognized user attempts an operation their role is not permitted to perform — or attempts to act on a household that is not their own — the request is rejected with `ERR_FORBIDDEN`.

The roles differ in how `X-User-ID` binds to persisted data. When `X-User-Role` is `HouseholdOwner`, `X-User-ID` is the `id` of the acting `Member` (the founding member, whose `role` is `OWNER`); ownership checks on any resource that references a household compare that resource's owning household against the household the member belongs to, and the request is forbidden if they differ. When `X-User-Role` is `HouseholdMember`, `X-User-ID` is likewise the `id` of the acting `Member` (an invited member whose `role` is `MEMBER`); the same own-household ownership check applies — a member may read and write only within the household they belong to. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; it represents the operational automation that runs aggregation sync and provisioning, and the server does not compare it to any entity's `id`. The `HouseholdOwner` has full control of their household — accounts, periods, goals, freezing — while a `HouseholdMember` may spend, categorize, allocate, and contribute within their household but cannot perform owner-exclusive operations. The `PlatformAdmin` ingests, posts, and removes transactions, provisions households, and drives the logical clock, but does not author budget decisions.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Currency, Money, and Precision

Each household chooses a `base_currency`, one of `USD`, `EUR`, or `GBP`, defaulting to `USD` when not supplied at creation. All monetary fields throughout the system — account balances, transaction amounts, envelope allocations and spends, goal targets, bill amounts, and the household net-worth figures — are stored and exchanged as integer minor units (cents) of that currency. Because every figure is an integer cent value, all reconciliation arithmetic is exact integer arithmetic: there is no rounding step and no fractional-cent intermediate anywhere in the contract. A `Transaction`'s `amount_cents` is a *signed* integer — negative for an outflow (spending) and positive for an inflow (income).

### 2.5. Common Resource Properties and Reconciliation Semantics

Most resources carry a standard system-managed property set: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits, fixed at creation; an `updated_at` ISO 8601 UTC timestamp refreshed on every mutation; and an integer `version` that starts at 1 and increments by one on every mutation. These four are present on `Household`, `Member`, `Account`, `Transaction`, `CategoryRule`, `BudgetPeriod`, `BudgetCategory`, `Goal`, and `RecurringBill`. The one exception is `GoalContribution`, which is an append-only event record: it carries only `id` and `created_at`, and has neither `updated_at` nor `version`.

Recomputation of a derived field counts as a mutation of the resource that owns it. When a transaction post drives an envelope's `spent_cents` to a new value, that `BudgetCategory` has its `updated_at` refreshed and its `version` incremented; the same holds when the household's net worth or posture is recomputed. This is the mechanism by which the optimistic-concurrency check in §2.9 detects that a household's allocation state has moved on. Reconciliation cascades are described workflow-by-workflow in §3; the principle here is that derived state is never stale relative to the primary records it summarizes.

### 2.6. Nested Resource Retrieval and Reference Integrity

Several paths name more than one resource — for example a transaction lives beneath an account, and a category beneath a budget period beneath a household. Path identifiers are validated left to right, in hierarchy order (household, then account, then transaction, and so on for each path shape). The first identifier in the path that does not name an existing resource causes the request to fail with `ERR_NOT_FOUND`, before any deeper identifier or body rule is considered.

Body-level references are validated separately and after path existence. When a request body names a foreign key — an `account_id`, a `budget_category_id`, a `funding_category_id`, or a `goal_id` — that referent must exist *and* belong to the same household as the operation; if it does not exist or belongs to another household, the request fails with `ERR_REFERENCE_NOT_FOUND`. This applies to the create, recategorize, and contribute endpoints that accept such references.

### 2.7. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the reported error is deterministic. Authentication comes first: a missing or unknown role yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation, or an entity-backed user acting outside their own household, yields `ERR_FORBIDDEN`. Third, path-resource existence is checked left-to-right, yielding `ERR_NOT_FOUND`. Fourth, body foreign-key existence-and-ownership is checked, yielding `ERR_REFERENCE_NOT_FOUND`. Fifth, for transition endpoints, the target must currently be in a state from which the requested transition is defined, otherwise `ERR_INVALID_STATE`. Sixth, for transaction create and post, the parent account must be `LINKED`, otherwise `ERR_ACCOUNT_ARCHIVED`. Seventh, the frozen-posture guard (`ERR_HOUSEHOLD_FROZEN`) applies to spend-affecting writes. Eighth, the recategorize/contribute current-period guard (`ERR_CATEGORY_PERIOD_MISMATCH`). Ninth, the account-archive pending-transactions guard (`ERR_PENDING_TRANSACTIONS_EXIST`). Tenth, uniqueness constraints (`ERR_DUPLICATE_RESOURCE`) and, at the same rank, the recurring-bill slot-conflict guard (`ERR_BILL_SLOT_CONFLICT`). Then the fiscal checks: insufficient envelope on contribution (`ERR_INSUFFICIENT_ENVELOPE`), the zero-based check on close (`ERR_BUDGET_NOT_ZERO_BASED`), and the optimistic-concurrency check on close (`ERR_STALE_HOUSEHOLD`). The goal-target constraint (`ERR_GOAL_TARGET_BELOW_FUNDED`) and the catch-all body well-formedness check (`ERR_INVALID_REQUEST`) sit after these. In short: authentication before authorization before existence before reference before state before account-status before frozen-posture before period-match before pending-transactions before uniqueness/slot before the fiscal and concurrency checks before generic request validation.

The catch-all `ERR_INVALID_REQUEST` (HTTP 400) covers a malformed body, a missing required field, a value of the wrong type, or an out-of-domain value — for example a `day_of_month` outside the 1-to-28 range, or a `target_cents` that is not greater than zero. The well-typedness check requires that body fields such as `amount_cents` be integers, `day_of_month` be an integer within 1 to 28, enum fields carry valid members, and `target_cents` be greater than zero; it applies to create and patch operations generally.

### 2.8. Household Posture and the Freeze Gate

Every household carries a computed `posture`, one of `HEALTHY`, `OVERSPENT`, or `FROZEN`. Posture is recomputed after every transaction post, recategorize, or remove; after every category allocation change; after every freeze or unfreeze; and on period rollover. The derivation is strictly ordered: the posture is `FROZEN` if and only if the owner has frozen the household (the system field `frozen_by_owner` is true); otherwise it is `OVERSPENT` if any `BudgetCategory` in the household's current period has an `envelope_state` of `OVER`; otherwise it is `HEALTHY`. The freeze flag therefore dominates overspend.

While a household's posture is `FROZEN`, every spend-affecting write is rejected with `ERR_HOUSEHOLD_FROZEN`. The spend-affecting writes are: creating a transaction, posting a transaction, recategorizing a transaction, allocating funds to an envelope, and contributing to a goal. Read operations and non-spend operations are unaffected by the freeze.

### 2.9. Optimistic Concurrency Control on Period Close

Closing the current budget period is the one operation guarded by optimistic concurrency, and the guarded resource is the `Household`. The close request must carry `expected_household_version`, which is the `version` of the household the client last observed. The server compares that value against the household's current `version`; if another writer has advanced the household's version since the client read it, the close is rejected with `ERR_STALE_HOUSEHOLD` at HTTP 412. This matters because closing a period legitimately supersedes the household's allocation state — it mints a new open period and bumps the household version — so a second close request still carrying the prior version is operating on a stale view of which period is current and must be turned away rather than allowed to act on superseded state. No other endpoint takes a version field; only period close performs this check.

### 2.10. Net-Worth Rollup and Account Balances

The household reports two net-worth figures, and they differ by exactly how pending money is treated. For each account, two running balances are maintained. The `cleared_balance_cents` is the account's `opening_balance_cents` plus the sum of the signed `amount_cents` of that account's `POSTED` (and not `REMOVED`) transactions. The `available_balance_cents` is the `opening_balance_cents` plus the sum of the signed `amount_cents` of that account's transactions that are either `POSTED` or `PENDING` and not `REMOVED`; it therefore includes pending money that the cleared figure excludes.

An account's contribution to net worth carries a sign determined by its `account_type`: a `DEPOSITORY` or `INVESTMENT` account is an asset and contributes with a positive sign, while a `CREDIT` or `LOAN` account is a liability and contributes with a negated sign. The household's `net_worth_cents` is the sum, across all accounts whose `status` is `LINKED`, of each account's signed `cleared_balance_cents`; the household's `projected_net_worth_cents` is the same sum but using each account's signed `available_balance_cents`. The cleared figure is the settled view and excludes pending transactions entirely; the projected figure is the forward-looking view and diverges from the cleared figure precisely when some linked account has open pending transactions. Both are integer cents with no rounding. Archived accounts (`status` of `ARCHIVED`) are excluded from both rollups and from aggregation sync.

### 2.11. Envelope Accounting

Each `BudgetCategory` is an envelope, and three of its figures are derived. Its `spent_cents` is the absolute magnitude of outflow spending charged to it: the sum of `-amount_cents` over every transaction whose `budget_category_id` is this category, whose `posted_period_id` is this category's `budget_period_id`, whose `status` is `POSTED`, and whose `amount_cents` is negative (outflows only). Because only negative amounts are counted and their sign is flipped, `spent_cents` is a non-negative magnitude.

The envelope's `available_cents` is its `allocated_cents` plus its `rollover_in_cents`, minus its `spent_cents`, minus the total of active goal contributions drawn from it — that is, minus the sum of `amount_cents` over every non-reversed `GoalContribution` whose goal names this category as its `funding_category_id`. The result may be negative. The envelope's `envelope_state` is `OVER` when `available_cents` is below zero; otherwise it is `DRAWN` when `available_cents` is at least zero and there has been activity (either `spent_cents` is greater than zero or contributions against the envelope are greater than zero); otherwise it is `FUNDED`. These figures are recomputed whenever a categorized transaction posts, on recategorize, on remove, on a goal contribution, on a contribution reversal, and on allocation. All three are integer cents with no rounding.

## 3. Business Logic & Workflows

### 3.1. Provisioning a Household and Its Members

A household comes into being when a `PlatformAdmin` provisions it, supplying the household `name`, the founding owner's `owner_email` and `owner_display_name`, and optionally a `base_currency` (defaulting to `USD`). The act creates the `Household` with an initial posture of `HEALTHY` and a `net_worth_cents` of zero, and simultaneously creates the founding `Member` with `role` of `OWNER`, recording that member's `id` on the household as `owner_member_id`. A household begins with no open period, so its `current_period_id` is null until the first period is opened.

The owner may grow the household by inviting additional members, supplying each invitee's `email` and `display_name`. An invited member is created with `role` of `MEMBER`. A member's `email` is unique within the household, and each member records the `household_id` of the household they belong to. Members can be retrieved individually or listed; the list view can be filtered by `household_id` so the membership of a given household is reverse-reachable.

### 3.2. Linking Accounts and the Net-Worth Picture

Accounts enter the household through aggregation. Linking an account — an action available to the owner and to the platform automation alike — records the `institution_name`, the `account_type` (`DEPOSITORY`, `CREDIT`, `LOAN`, or `INVESTMENT`), and an optional `opening_balance_cents` that defaults to zero and represents the balance at the moment of linking, before any tracked transaction. Each account stores the `household_id` of its owning household and begins life with a `status` of `LINKED`. Creating an account immediately recomputes the household's net-worth figures so the new account's opening balance is reflected at once.

An owner may archive an account, transitioning its `status` from `LINKED` to `ARCHIVED`. Archival is permitted only when the account has no `PENDING` transactions; an attempt while pending transactions remain is rejected with `ERR_PENDING_TRANSACTIONS_EXIST`. On archival the account drops out of the net-worth rollup, and both `net_worth_cents` and `projected_net_worth_cents` are recomputed. `ARCHIVED` is terminal. Accounts can be fetched by id or listed, and the listing can be filtered by `household_id` and by `status`, exposing each account with its computed `cleared_balance_cents` and `available_balance_cents`.

### 3.3. The Transaction Lifecycle: Ingest, Post, Recategorize, Remove

Transactions are ingested by the platform automation as aggregation discovers them. An ingest supplies the `amount_cents` (signed: negative outflow, positive inflow), the `merchant_name` used later for auto-categorization matching, and optionally a `budget_category_id` if the category is already known. The new `Transaction` is created on its `account_id` with a `status` of `PENDING`. Its `state` field is an alias view of `status` whose terminal value is `REMOVED`. Ingesting a pending transaction recomputes the owning account's `available_balance_cents` and the household's `projected_net_worth_cents` — pending money moves the forward view but not the settled one. A transaction may be created only on a `LINKED` account; an attempt on an archived account is rejected with `ERR_ACCOUNT_ARCHIVED`. Transactions can be fetched by id or listed, with the listing filterable by `account_id`, `status`, `budget_category_id`, and `posted_period_id`.

Posting clears a pending transaction, advancing its `status` from `PENDING` to `POSTED`. Posting is permitted only when the household is not frozen (otherwise `ERR_HOUSEHOLD_FROZEN`) and the parent account is `LINKED` (otherwise `ERR_ACCOUNT_ARCHIVED`). The post triggers a cascade. First, if the transaction is still uncategorized — its `budget_category_id` is null — auto-categorization runs (see §3.4). If the transaction is categorized after that step, its `posted_period_id` is set to the household's `current_period_id` and the owning envelope's `spent_cents`, `available_cents`, and `envelope_state` are recomputed. Next the parent account's `cleared_balance_cents` and `available_balance_cents` are recomputed. Then the household's `net_worth_cents` and `projected_net_worth_cents` are recomputed. Finally the household's `posture` is recomputed — if the post drives the envelope to `OVER`, the household cascades to `OVERSPENT`.

A categorized, posted transaction can be reassigned to a different envelope by an owner or member, who supplies the new `budget_category_id`. The recategorize is permitted only when the household is not frozen (otherwise `ERR_HOUSEHOLD_FROZEN`) and when the target category exists and belongs to the household's current period (otherwise `ERR_CATEGORY_PERIOD_MISMATCH`). The recategorize unwinds the old envelope and reapplies to the new one: from the old category (if any) this transaction's outflow is subtracted and that envelope's `spent_cents`, `available_cents`, and `envelope_state` are recomputed; then the transaction's `budget_category_id` is set to the target and its `posted_period_id` to the current period, and the new category's `spent_cents`, `available_cents`, and `envelope_state` are recomputed. Household `posture` is then recomputed, because the old envelope may leave `OVER` while the new one may newly enter `OVER`. Modeled as a state machine, a `POSTED` transaction enters `RECATEGORIZED` and then returns to `POSTED`, so the loop `POSTED → RECATEGORIZED → POSTED` is cyclic and a transaction can be recategorized repeatedly. Recategorizing requires the transaction to currently be in a state from which the transition is defined; otherwise `ERR_INVALID_STATE`.

Removal handles the case where aggregation reports a transaction deleted. Removal is permitted only when the household is not frozen (otherwise `ERR_HOUSEHOLD_FROZEN`), and a transaction may be removed from either `PENDING` or `POSTED`, landing in the terminal `REMOVED` state. Removing a `PENDING` transaction recomputes only the parent account's `available_balance_cents` and the household's `projected_net_worth_cents`, since a pending transaction was only ever in the available figure. Removing a `POSTED` transaction does more: if it was categorized, its outflow is subtracted from the owning envelope's `spent_cents` and that envelope's `available_cents` and `envelope_state` are recomputed; then the parent account's `cleared_balance_cents` and `available_balance_cents` are recomputed; then the household's `net_worth_cents` and `projected_net_worth_cents` are recomputed; then household `posture` is recomputed, which may carry an envelope out of `OVER` and the household back to `HEALTHY`.

### 3.4. Auto-Categorization Rules

Auto-categorization is the policy that assigns a category to a transaction at post time when none was supplied. The household's `CategoryRule` records drive it: each rule records the `household_id` whose transactions it categorizes, a `match_substring` matched case-insensitively against the transaction's `merchant_name`, the `budget_category_id` it assigns when it matches, an integer `priority`, and an `enabled` flag (default true) — disabled rules are skipped. Rules can be created by an owner or member, fetched by id, or listed with filters on `household_id` and `budget_category_id`.

When a transaction posts uncategorized, the system gathers the candidate rules: every rule in the same household that is enabled and whose `match_substring`, lowercased, occurs as a substring of the lowercased `merchant_name`. Among candidates the winner is the one with the lowest `priority` (a lower number wins); ties on priority are broken by earliest `created_at` (ascending), never by `id`. The winning rule's `budget_category_id` is assigned — but only if that category belongs to the household's current period; if the winning rule points at a category from a stale period, the transaction is left uncategorized instead. If no rule matches at all, the transaction posts uncategorized, leaving its `budget_category_id` null and producing no envelope impact.

### 3.5. The Budget Period: Opening, Allocating, Zero-Based Close, and Rollover

A budget period is the monthly container for envelopes. An owner opens a period by supplying its `month` as a `YYYY-MM` string (for example `2026-02`) and optionally an `income_expected_cents` (default zero), the planned income for the period. A period's `month` is unique within the household, and only one period per household may be `OPEN` at a time; a duplicate month or a second open period is rejected with `ERR_DUPLICATE_RESOURCE`. A newly opened period has `status` of `OPEN`. If the household had no current period, opening one sets the household's `current_period_id` to it and bumps the household `version`. A period exposes a computed `total_allocated_cents`, the sum of `allocated_cents` over the categories in that period. Periods can be fetched by id or listed, filterable by `household_id` and `status`. The owner may adjust a still-open period's planned income by patching `income_expected_cents`.

Within a period, an owner or member creates envelopes. A category is created with a `name` (unique within its period; a duplicate is `ERR_DUPLICATE_RESOURCE`), an optional `allocated_cents` (default zero), and an optional `rollover_enabled` flag (default true). The category records the `budget_period_id` of the period it belongs to and a denormalized `household_id` of the owning household. Creating a category recomputes the period's `total_allocated_cents`. Categories can be fetched by id — exposing computed `spent_cents`, `available_cents`, and `envelope_state` — or listed with filters on `household_id`, `budget_period_id`, and `envelope_state`. To practice zero-based budgeting, an owner or member allocates funds to an envelope by setting its `allocated_cents`; allocation is rejected while the household is frozen (`ERR_HOUSEHOLD_FROZEN`). Allocation recomputes that envelope's `available_cents` and `envelope_state`, the period's `total_allocated_cents`, and the household posture.

Closing the current period, an owner-only action, both finalizes the month and opens the next, transitioning the period's `status` from `OPEN` to `CLOSED`. Several preconditions guard it, evaluated per §2.7. The optimistic-concurrency check requires `expected_household_version` to match the household's current `version`, else `ERR_STALE_HOUSEHOLD` at HTTP 412 (see §2.9). The zero-based check requires the period's `total_allocated_cents` to equal its `income_expected_cents`; if every planned dollar has not been assigned to an envelope, the close is rejected with `ERR_BUDGET_NOT_ZERO_BASED`. The period being closed must be the household's current period, else `ERR_INVALID_STATE`. On a successful close, the period becomes `CLOSED`; a new `OPEN` period is minted for the next month; the household's `current_period_id` is repointed to it; and the household's `version` increments by one. Rollover then runs: for each category in the closing period whose `rollover_enabled` is true and whose `available_cents` is greater than zero, a same-named category is created in the new period with its `rollover_in_cents` set to that leftover `available_cents` — the positive leftover is carried forward. A category whose `rollover_enabled` is false forfeits its leftover instead of carrying it. Finally the household's `posture` is recomputed against the new period, becoming `HEALTHY` unless a rolled-forward category is already `OVER`.

### 3.6. Goals and Sinking Funds

A goal is a savings target funded from a specific envelope. An owner creates a goal with a `name`, a `target_cents` that must be greater than zero (otherwise `ERR_GOAL_TARGET_BELOW_FUNDED`), and a `funding_category_id` naming the envelope contributions are drawn from. The goal records its `household_id`, begins with `status` of `ACTIVE` and a computed `funded_cents` of zero, where `funded_cents` is the sum of `amount_cents` over the goal's non-reversed contributions. Goals can be fetched by id or listed, filterable by `household_id`, `status`, and `funding_category_id`.

An owner or member contributes to a goal, supplying a positive `amount_cents` drawn from the goal's funding envelope. The contribution is blocked while the household is frozen (`ERR_HOUSEHOLD_FROZEN`), and the funding category must belong to the household's current open period (`ERR_CATEGORY_PERIOD_MISMATCH`). Crucially, the contribution is rejected if, *before* the contribution is applied, the funding envelope's `available_cents` is less than the `amount_cents` requested — the envelope must be able to cover it — and that rejection is `ERR_INSUFFICIENT_ENVELOPE` at HTTP 422. A successful contribution creates a `GoalContribution` recording its `goal_id`, its `amount_cents`, and a `reversed` flag (default false); the funding envelope's `available_cents` decreases accordingly (contributions are subtracted in the envelope formula of §2.11); and the goal's funding is re-evaluated. The funding threshold is reached when `funded_cents` is at least `target_cents` — exactly hitting the target funds the goal, and falling short does not — at which point the goal transitions from `ACTIVE` to `FUNDED`. Contributions can be fetched by id or listed, filterable by `goal_id`.

An owner may raise a goal's `target_cents` by patching it. The new target must be strictly greater than the goal's current `funded_cents`; a target at or below the funded amount is rejected with `ERR_GOAL_TARGET_BELOW_FUNDED`. When a goal that had reached `FUNDED` has its target raised above its funded amount, it reopens from `FUNDED` back to `ACTIVE`, so the cycle `FUNDED → ACTIVE → FUNDED` is possible as targets are revised upward.

Abandoning a goal is an owner-only action that transitions it from `ACTIVE` to the terminal `ABANDONED` state. Abandonment reverses every one of the goal's non-reversed contributions: each reversal marks that contribution's `reversed` flag true and credits its `amount_cents` back to the funding envelope's available balance (so the reversed contributions drop out of both `funded_cents` and the envelope's contribution total, conserving the household's allocated funds). The funding category's `available_cents` and `envelope_state` are then recomputed, and the household `posture` is recomputed.

### 3.7. Recurring Bills and the Cash-Flow Forecast

A recurring bill models a predictable monthly obligation. An owner or member creates one with a `payee`, a positive `amount_cents` due each occurrence, a `day_of_month` between 1 and 28 inclusive (a value outside that range is `ERR_INVALID_REQUEST`), and a `funding_category_id` naming the envelope expected to cover it. The bill records its `household_id` and begins with `status` of `SCHEDULED`. Bills can be fetched by id or listed, filterable by `household_id`, `status`, and `funding_category_id`.

A bill may be paused by an owner or member, moving its `status` from `SCHEDULED` to `PAUSED`, which removes it from the cash-flow forecast; and it may be resumed, moving from `PAUSED` back to `SCHEDULED`, which returns it to the forecast. Resuming is guarded against slot collisions: a paused bill cannot resume if a `SCHEDULED` bill of the same `payee` already occupies the adjacent due-day slot. Specifically, a new or resuming `SCHEDULED` bill conflicts with an existing `SCHEDULED` bill in the household when they share the same `payee` and the existing bill's `day_of_month` falls within plus-or-minus two days of the new bill's `day_of_month`, with the day-of-month window cyclically clamped to the 1-to-28 domain; such a conflict is rejected with `ERR_BILL_SLOT_CONFLICT`. A `PAUSED` bill does not occupy a slot. This same slot-conflict rule is applied both when creating a bill and when resuming one.

The cash-flow forecast is a computed read over a horizon. The request supplies `horizon_days`, an integer between 1 and 90, and optionally `include_pending` (default false). The forecast starts from the household's current cash balance, defined as the sum of `cleared_balance_cents` across the household's `LINKED` `DEPOSITORY` accounts only; when `include_pending` is true, the conservative variant instead starts from the sum of `available_balance_cents` across those same accounts, so a pending outflow lowers the starting point and can flip a shortfall to true that the optimistic (default) variant reports as false. The forecast then walks the days from the day after the current logical-clock date through that date plus `horizon_days`, in chronological order, carrying a running balance that begins at the starting cash. On each day, every `SCHEDULED` bill whose `day_of_month` equals that calendar day's day-of-number has its `amount_cents` subtracted from the running balance, and a point recording that day's date and the resulting `projected_balance_cents` is appended. When several bills fall due on the same day, they are applied in ascending order of `day_of_month` and then earliest `created_at` (the tie-break is `created_at`, never `id`). Paused bills are excluded entirely. After the walk, `min_projected_balance_cents` is the minimum `projected_balance_cents` across all points, and `shortfall` is true exactly when that minimum is below zero. All figures are integer cents with no rounding.

The forecast depends on a logical clock rather than wall-clock time. The platform automation can advance that clock by supplying a `to_iso8601` instant; the clock then reads that instant for all subsequent forecast dating and period dating. At server startup the clock defaults to `2026-01-01T00:00:00Z`, and before any set call it reads exactly that default and never falls back to wall-clock time.

## 4. Endpoint Definitions

Operations that create a new, distinct resource (a household, a member, an account, a transaction, a category rule, a budget period, a category, a goal, or a goal contribution) return `201 Created`. Operations that modify an existing resource or drive a state transition — posting, recategorizing, removing, freezing, archiving, allocating, closing, abandoning, pausing, resuming, and the patch and clock operations — return `200 OK`. Reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock used by forecasting and period dating | PlatformAdmin |
| POST | `/households` | Create a household and its founding owner member | PlatformAdmin |
| GET | `/households/{household_id}` | Get a household with computed posture and net worth | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/freeze` | Freeze the household ledger | HouseholdOwner |
| POST | `/households/{household_id}/unfreeze` | Unfreeze the household ledger | HouseholdOwner |
| GET | `/households/{household_id}/cash-flow-forecast` | Cash-flow forecast over a horizon | HouseholdOwner, HouseholdMember |
| POST | `/households/{household_id}/members` | Invite a member into the household | HouseholdOwner |
| GET | `/households/members/{id}` | Get a member | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/members` | List members, filterable by household | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/accounts` | Link an account to the household | HouseholdOwner, PlatformAdmin |
| GET | `/households/accounts/{id}` | Get an account with computed balances | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/accounts` | List accounts, filterable by household and status | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/accounts/{id}/archive` | Archive an account | HouseholdOwner |
| POST | `/accounts/{account_id}/transactions` | Ingest a transaction in PENDING state | PlatformAdmin |
| GET | `/households/transactions/{id}` | Get a transaction | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/transactions` | List transactions, filterable by account, status, category, posted period | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/accounts/{account_id}/transactions/{id}/post` | Post a pending transaction | PlatformAdmin |
| POST | `/accounts/{account_id}/transactions/{id}/recategorize` | Reassign a posted transaction to a different category | HouseholdOwner, HouseholdMember |
| POST | `/accounts/{account_id}/transactions/{id}/remove` | Remove a transaction | PlatformAdmin |
| POST | `/households/{household_id}/category-rules` | Create an auto-categorization rule | HouseholdOwner, HouseholdMember |
| GET | `/households/category-rules/{id}` | Get a category rule | HouseholdOwner, HouseholdMember |
| GET | `/households/category-rules` | List category rules, filterable by household and target category | HouseholdOwner, HouseholdMember |
| POST | `/households/{household_id}/budget-periods` | Open the first or next budget period | HouseholdOwner |
| GET | `/households/budget-periods/{id}` | Get a budget period | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/budget-periods` | List budget periods, filterable by household and status | HouseholdOwner, HouseholdMember, PlatformAdmin |
| PATCH | `/households/{household_id}/budget-periods/{id}` | Update planned income for an open period | HouseholdOwner |
| POST | `/households/{household_id}/budget-periods/{id}/close` | Close the current period; opens next and rolls leftovers | HouseholdOwner |
| POST | `/households/{household_id}/budget-periods/{period_id}/categories` | Create an envelope in a period | HouseholdOwner, HouseholdMember |
| GET | `/households/budget-categories/{id}` | Get a category with computed spent/available/state | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/budget-categories` | List categories, filterable by household, period, envelope state | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/budget-categories/{id}/allocate` | Set an envelope's allocated amount | HouseholdOwner, HouseholdMember |
| POST | `/households/{household_id}/goals` | Create a goal or sinking fund | HouseholdOwner |
| GET | `/households/goals/{id}` | Get a goal with computed funded amount | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/goals` | List goals, filterable by household, status, funding category | HouseholdOwner, HouseholdMember, PlatformAdmin |
| PATCH | `/households/{household_id}/goals/{id}` | Update a goal's target | HouseholdOwner |
| POST | `/households/{household_id}/goals/{id}/contribute` | Contribute to a goal from its funding envelope | HouseholdOwner, HouseholdMember |
| POST | `/households/{household_id}/goals/{id}/abandon` | Abandon a goal; reverse all contributions | HouseholdOwner |
| GET | `/households/goal-contributions/{id}` | Get a goal contribution | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/goal-contributions` | List goal contributions, filterable by goal | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/recurring-bills` | Create a recurring bill | HouseholdOwner, HouseholdMember |
| GET | `/households/recurring-bills/{id}` | Get a recurring bill | HouseholdOwner, HouseholdMember, PlatformAdmin |
| GET | `/households/recurring-bills` | List recurring bills, filterable by household, status, funding category | HouseholdOwner, HouseholdMember, PlatformAdmin |
| POST | `/households/{household_id}/recurring-bills/{id}/pause` | Pause a recurring bill | HouseholdOwner, HouseholdMember |
| POST | `/households/{household_id}/recurring-bills/{id}/resume` | Resume a paused recurring bill | HouseholdOwner, HouseholdMember |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_ARCHIVED` | 409 Conflict |
| `ERR_HOUSEHOLD_FROZEN` | 409 Conflict |
| `ERR_CATEGORY_PERIOD_MISMATCH` | 409 Conflict |
| `ERR_PENDING_TRANSACTIONS_EXIST` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_BILL_SLOT_CONFLICT` | 409 Conflict |
| `ERR_INSUFFICIENT_ENVELOPE` | 422 Unprocessable Entity |
| `ERR_BUDGET_NOT_ZERO_BASED` | 422 Unprocessable Entity |
| `ERR_STALE_HOUSEHOLD` | 412 Precondition Failed |
| `ERR_GOAL_TARGET_BELOW_FUNDED` | 422 Unprocessable Entity |

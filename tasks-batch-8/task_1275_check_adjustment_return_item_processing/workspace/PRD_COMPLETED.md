# Check Adjustment Return Items API — Product Requirements Document

## 1. Introduction

Every business day, a bank's item-processing operation absorbs thousands of deposited checks captured across branch, ATM, mobile, and remote-deposit channels, presents them to clearing banks, and then lives with the consequences: items come back unpaid, amounts are mis-encoded on the MICR line, images fail quality standards, the same item is presented twice, and unusually large deposits demand human review before funds are released. Each of these events has money attached to it — provisional credits that must be reversed, fees that must be assessed, claims that must be filed against the clearing bank within strict deadline windows, and consumer recredit rights under Regulation CC that carry their own clocks and interest math.

This document specifies the Check Adjustment & Return Item Processing API, the system of record for that entire post-deposit lifecycle. It governs return reason coding and re-presentment eligibility, encoding-error and adjustment claims against clearing banks, image-warranty claim deadlines, duplicate presentment detection with automatic customer credit, large-item review holds, customer notification and fee assessment, expedited recredit, and the aging, escalation, and eventual write-off of unrecovered claims. Because the workflow spans item processors, adjustment analysts, compliance officers, customer service agents, and the depositors themselves, the API enforces a strict segregation-of-duties model, an append-only ledger from which every balance is derived, and a deterministic logical clock so that every deadline, aging count, and sweep decision is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles: `OperationsAdmin` (back-office administrator: master data, case assignment, claim acknowledgment, the operations-run checkpoint, and the logical clock), `ItemProcessor` (item-processing operator: deposit, presentment, payment, return recording and reason coding, re-presentment), `AdjustmentAnalyst` (hold decisions, case resolution, claim and warranty creation, submission, and settlement), `ComplianceOfficer` (account freezes, case reopen, write-offs, uncapped fee waivers), `CustomerService` (notification delivery, capped fee waivers, recredit intake and provisional credit), and `Customer` (a depositor account holder who reads their own resources and files recredit requests for their own account).

A request missing either header, or carrying a role that is not one of the six declared roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is authenticated but not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The `Customer` role is entity-backed: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `DepositorAccount`, and ownership checks on any resource that references a `DepositorAccount` compare the resource's `depositor_account_id` field to `X-User-ID`. A `Customer` may only access resources whose `depositor_account_id` equals their `X-User-ID`; any other access is rejected with `ERR_FORBIDDEN_OWNERSHIP` (HTTP 403). This ownership rule applies to the customer-accessible reads (account, item, case, notification, fee, recredit, ledger, and freeze reads) and to recredit-request creation. On the customer-accessible list endpoints that accept a `depositor_account_id` filter (notifications, fees, recredit requests, and ledger entries), a `Customer` who supplies a `depositor_account_id` filter unequal to their `X-User-ID` is rejected with `ERR_FORBIDDEN_OWNERSHIP`; otherwise the list is silently scoped to their own account — the effective `depositor_account_id` filter is forced to their `X-User-ID`.

The remaining five roles are opaque. When `X-User-Role` is `OperationsAdmin`, `ItemProcessor`, `AdjustmentAnalyst`, `ComplianceOfficer`, or `CustomerService`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `decided_by_user_id` on a decided hold, `assigned_analyst_id` on an assigned case, `created_by_user_id` on a created claim, or `waived_by_user_id` on a waived fee — but it does not compare it to any entity's `id`.

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

Requests that match no declared route (or fail at the HTTP layer before routing, e.g. a malformed request or wrong method) are answered in the same error envelope with `error_id` `ERR_NOT_FOUND` and the HTTP layer's status code; unexpected server failures are answered with `error_id` `ERR_INTERNAL` and HTTP 500.

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10; a supplied value is clamped into the inclusive range 1 to 100 (values below 1 become 1, values above 100 become 100). The `offset` parameter specifies the number of items to skip and defaults to 0; a negative supplied value is clamped to 0. A `limit` or `offset` that is not parseable as an integer is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by creation order in ascending order — by creation timestamp, with ties (resources created at the same logical instant) broken by insertion sequence.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock and Day Reckoning

Every timestamp the server records and every deadline, aging count, or window comparison it evaluates reads a single logical clock — never the host's wall-clock time. The logical clock starts at exactly `2026-05-01T00:00:00Z` (a Friday) when the server boots, and it advances only when an `OperationsAdmin` drives it forward through the test-driving capability `POST /_clock/set_current_utc`, which accepts a `to_iso8601` timestamp and echoes the resulting `current_utc`. The server must not consult wall-clock time before or after this call.

Two day-counting conventions recur throughout the system. A **calendar day** is any date, and a calendar-day span between two timestamps is measured as whole days from the earlier date to the later date. A **business day** is a Monday-through-Friday date; business-day spans count only Monday-through-Friday dates. Where this document says a window is measured "in business days" of an event, the count covers the business dates strictly after the event's date up to and including the current date.

### 2.5. Common Resource Properties

All primary resources — clearing banks, depositor accounts, account freezes, check items, hold decisions, return events, adjustment cases, adjustment claims, warranty claims, fee assessments, and recredit requests — carry a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, set when the resource is created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that increments by one with every modification to the resource; it is the basis for optimistic concurrency control.

Two resources are deliberately lighter. A `CustomerNotification` and a `LedgerEntry` each carry only `id` and `created_at`; both `updated_at` and `version` are absent from them, because notifications are delivered exactly once and ledger entries are immutable by design.

### 2.6. The Append-Only Item Ledger

Every movement of money against a depositor account is recorded as a `LedgerEntry`. The ledger is append-only: entries are created by system processes and workflow actions, and no update or delete capability exists for them anywhere in the API. Each entry carries the owning `depositor_account_id`, an `entry_type` drawn from exactly twelve values — `OPENING_CREDIT`, `DEPOSIT_CREDIT`, `PROVISIONAL_REVERSAL`, `SETTLEMENT_CREDIT`, `ITEM_RETURN_DEBIT`, `DUPLICATE_REVERSAL_CREDIT`, `FEE_DEBIT`, `FEE_WAIVER_CREDIT`, `RECREDIT_PROVISIONAL_CREDIT`, `RECREDIT_CLAWBACK_DEBIT`, `ADJUSTMENT_CREDIT`, and `ADJUSTMENT_DEBIT` — a signed `amount_cents` in which credits are positive and debits negative, a `provisional` flag, an optional human-readable `memo`, and nullable links back to the originating business objects: `check_item_id`, `adjustment_case_id`, `fee_assessment_id`, and `recredit_request_id`.

The `provisional` flag separates money that may still be reversed from money that has settled. Provisional entries — deposit credits awaiting presentment outcome, return debits, provisional reversals, and recredit provisional credits and clawbacks — move the customer's available funds immediately but are excluded from settled reporting.

### 2.7. Balance Derivation and Automatic Account Freezing

An account's balances are never stored; they are derived from the ledger on every read and re-derived after every ledger write. The `available_balance_cents` of a `DepositorAccount` is the sum of `amount_cents` over all of the account's ledger entries, provisional and non-provisional alike. The `settled_balance_cents` is the sum of `amount_cents` over only those entries whose `provisional` flag is false. The two variants serve different purposes: the available variant drives gating decisions (including the freeze check below) and the customer-facing balance, while the settled variant serves settlement reporting and audit reconciliation. A freshly deposited item therefore raises the available balance immediately but does not touch the settled balance until payment posts a `SETTLEMENT_CREDIT`.

Account freezing is fully automatic and cyclic. After any ledger write that leaves `available_balance_cents` below zero, the account's `status` transitions from `ACTIVE` to `FROZEN`; after any ledger write that leaves `available_balance_cents` at zero or above, a `FROZEN` account transitions back to `ACTIVE`. An account may thaw and refreeze any number of times over its life. While an account is `FROZEN`, new deposits into it are rejected with `ERR_ACCOUNT_FROZEN`.

### 2.8. Monetary Precision and Rounding

All monetary values in the system are integer cents. Two computations can produce fractional cents and pin their rounding behavior explicitly: the return-item fee multiplies a base fee by a risk multiplier and rounds that component half-up to whole cents before any surcharge is added, and the recredit interest accrues per elapsed calendar day with each day's interest rounded half-up to whole cents before the days are summed. No other rounding is permitted anywhere; balances and amounts are otherwise exact integer arithmetic.

### 2.9. Optimistic Concurrency Control

Two write operations carry optimistic concurrency control, each keyed to the parent entity's `version`:

- Updating a depositor account requires the request to carry `expected_depositor_account_version` holding the account `version` the client last observed. If the account's current `version` has advanced past that value, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), because the second writer's view of `risk_tier` and `reg_cc_eligible` is stale and must not silently overwrite newer state.
- Assigning or re-assigning an adjustment case requires the request to carry `expected_adjustment_case_version` holding the case `version` the client last observed. A mismatch with the case's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412); re-assignment legitimately supersedes the prior assignee, so a stale version means the client missed an intervening assignment or status change.

Both fields are non-optional on their respective endpoints. Endpoints not named in this section do not accept a version field at all.

### 2.10. Nested Resource Retrieval and Existence Ordering

Requests that target nested resources validate path identifiers sequentially, left to right — the account before the freeze, the item before the return event, the case before the claim, and so on. The request is rejected immediately with the not-found error corresponding to the first identifier in the path that does not resolve to an existing resource, before any later identifier or any business rule is examined. Each resource type has its own not-found error: `ERR_ACCOUNT_NOT_FOUND` for a depositor account, `ERR_CLEARING_BANK_NOT_FOUND` for a clearing bank, `ERR_ITEM_NOT_FOUND` for a check item, `ERR_CASE_NOT_FOUND` for an adjustment case, `ERR_CLAIM_NOT_FOUND` for an adjustment claim, `ERR_WARRANTY_NOT_FOUND` for a warranty claim, `ERR_RETURN_EVENT_NOT_FOUND` for a return event, `ERR_HOLD_NOT_FOUND` for a hold decision, `ERR_NOTIFICATION_NOT_FOUND` for a customer notification, `ERR_FEE_NOT_FOUND` for a fee assessment, `ERR_RECREDIT_NOT_FOUND` for a recredit request, and `ERR_LEDGER_ENTRY_NOT_FOUND` for a ledger entry. All twelve carry HTTP 404.

### 2.11. Validation Evaluation Order

When several checks could fail on the same request, the server evaluates them in a fixed order so the surfaced error is deterministic. The order is: first, authentication — the headers are present and the role is one of the six declared roles (`ERR_UNAUTHENTICATED`); second, role authorization against the endpoint's role list (`ERR_UNAUTHORIZED_ROLE`); third, `Customer` ownership scoping (`ERR_FORBIDDEN_OWNERSHIP`); fourth, left-to-right path-resource existence (the per-resource not-found errors of §2.10); fifth, optimistic-concurrency version match (`ERR_STALE_VERSION`); sixth, state-machine preconditions for the requested transition (`ERR_INVALID_STATE`, `ERR_ACCOUNT_FROZEN`, `ERR_CLEARING_BANK_SUSPENDED`, `ERR_MAX_PRESENTMENTS_EXCEEDED`, `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`); seventh, segregation-of-duties and authority checks (`ERR_SEGREGATION_OF_DUTIES`, `ERR_NOT_ASSIGNED_ANALYST`, `ERR_FEE_WAIVE_LIMIT_EXCEEDED`); eighth, temporal deadline windows (`ERR_CLAIM_WINDOW_EXPIRED`, `ERR_WARRANTY_WINDOW_EXPIRED`, `ERR_RECREDIT_WINDOW_EXPIRED`, `ERR_FINALIZE_WINDOW_EXPIRED`, `ERR_CLAIM_NOT_AGED_ENOUGH`); ninth, structural constraints (`ERR_FREEZE_WINDOW_OVERLAP`, `ERR_HOLD_WINDOW_OVERLAP`, `ERR_CASE_TYPE_MISMATCH`, `ERR_RECREDIT_ALREADY_OPEN`, `ERR_RECREDIT_NOT_ELIGIBLE`, `ERR_DUPLICATE_ACCOUNT_NUMBER`, `ERR_DUPLICATE_ROUTING_NUMBER`, `ERR_CASE_HAS_OPEN_CLAIMS`, `ERR_CLEARING_BANK_CAPACITY_EXCEEDED`); tenth, cross-reference coherence (`ERR_RECREDIT_ITEM_MISMATCH`); and eleventh, amount sanity and request shape (`ERR_INVALID_AMOUNT`, `ERR_INVALID_REQUEST`). A failure at any step masks every later step.

The third step's ownership check is evaluated as early as the needed `depositor_account_id` is known. Where that id is the path identifier itself or comes from the request body — the account read and freeze list, the account-scoped list filters of §2.1, and recredit-request creation — ownership is enforced before any lookup, so a `Customer` straying outside their own id gets `ERR_FORBIDDEN_OWNERSHIP` even when no such resource exists. Where ownership can only be known by loading the target resource — the item, case, notification, fee, recredit, and ledger-entry reads and the per-item return-event, hold-decision, and case lists — the step-four existence check necessarily resolves first, so an unknown identifier there surfaces the not-found error even to a `Customer` who would also fail ownership.

## 3. Business Logic & Workflows

### 3.1. Master Data: Clearing Banks, Depositor Accounts, and Freeze Windows

Before any item can flow, an `OperationsAdmin` registers the clearing banks the institution settles with. A clearing bank is created with a display `name`, a 9-digit `routing_number` that must be unique across all clearing banks (a duplicate is rejected with `ERR_DUPLICATE_ROUTING_NUMBER`), and three policy knobs with defaults: `claim_window_business_days` (default 3), the number of business days from an adjustment claim's `created_at` within which submission is allowed; `warranty_window_days` (default 7), the number of calendar days from an item's `presented_at` within which a warranty claim may be submitted; and `daily_claim_capacity` (default 10), the maximum number of adjustment-claim submissions the bank will accept from us per business day. A clearing bank's `status` is `ACTIVE` by default and may be `SUSPENDED`; a `SUSPENDED` bank blocks both presentment of items and submission of claims to it, each rejected with `ERR_CLEARING_BANK_SUSPENDED`.

Depositor accounts are likewise created by an `OperationsAdmin`, with a `customer_name`, an `account_number` that must be unique (duplicates are rejected with `ERR_DUPLICATE_ACCOUNT_NUMBER`), an optional `risk_tier` of `STANDARD` (the default) or `HIGH_RISK`, an optional `reg_cc_eligible` flag defaulting to true, and an optional `opening_balance_cents` defaulting to zero. When the opening balance is greater than zero, account creation posts exactly one `OPENING_CREDIT` ledger entry, non-provisional, for that amount. A new account starts in `ACTIVE` status with its `version` at 1. Reading an account returns the derived `available_balance_cents` and `settled_balance_cents` of §2.7 plus `returned_item_count_30d`, the count of that account's coded return events whose `coded_at` falls within the trailing thirty calendar days — the window from thirty days ago up to and including the current moment, inclusive of the event just coded. Later, an `OperationsAdmin` may update `risk_tier` and/or `reg_cc_eligible`; per §2.9 this write requires `expected_depositor_account_version` and increments the account's `version` by one on success.

A `ComplianceOfficer` may place a freeze window on an account by supplying `start_at`, `end_at`, and a `reason`; all three are required, the two timestamps must parse as ISO 8601, and an `end_at` earlier than `start_at` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Freeze windows are **closed intervals**, inclusive of both endpoints: the freeze's computed `status` is `ACTIVE` while the current logical time is on or after `start_at` and on or before `end_at`, and `EXPIRED` otherwise. A new freeze is rejected with `ERR_FREEZE_WINDOW_OVERLAP` whenever it overlaps an existing freeze on the same account — and under closed-interval semantics, two windows that merely touch at a single instant do overlap and are rejected. While any `ACTIVE` freeze window covers an account, deposits into that account are rejected with `ERR_ACCOUNT_FROZEN`, exactly as if the account itself were `FROZEN`. Each freeze record carries its owning `depositor_account_id` alongside the window and reason.

### 3.2. Depositing a Check Item and the Large-Item Review Path

An `ItemProcessor` deposits a check by supplying the `depositor_account_id`, the `clearing_bank_id`, an external `item_reference` used later for duplicate detection, the face `amount_cents`, the MICR `encoded_amount_cents`, an `image_quality_score` between 0 and 100 inclusive, and the `capture_channel` — one of `BRANCH`, `ATM`, `MOBILE`, or `RDC`. All seven fields are required; a missing or wrongly typed field, a non-positive `amount_cents`, a negative `encoded_amount_cents`, an out-of-range `image_quality_score`, or an unrecognized `capture_channel` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — shape checks the server evaluates after the account and clearing-bank existence lookups and the frozen-account gate. The deposit is refused with `ERR_ACCOUNT_FROZEN` when the target account is `FROZEN` or covered by an `ACTIVE` freeze window. On acceptance the item starts in `RECEIVED` status with `presentment_count` at zero, and the system immediately posts a `DEPOSIT_CREDIT` ledger entry for the full `amount_cents`, marked provisional: the customer sees the funds at once, but nothing has settled.

An item whose `amount_cents` is at least 500000 cents — the boundary is inclusive, so exactly 500000 qualifies — is classified `is_large_item` and never rests in `RECEIVED`. Creation cascades it straight into `UNDER_REVIEW` with three companions: a hold decision whose `source` is `AUTO_LARGE_ITEM`, in `PENDING` status, whose window runs from the item's `created_at` to that same time-of-day two business days later; an adjustment case of `case_type` `LARGE_ITEM_REVIEW` in `OPEN` status; and a customer notification of `notification_type` `LARGE_ITEM_HOLD_NOTICE` in `PENDING` status.

An `AdjustmentAnalyst` may also place a manual supplementary hold on any non-terminal item by supplying a `hold_until` and a `reason`. A manual hold's `source` is `MANUAL`, and its window is half-open: it begins at `window_start_at` (the moment of creation) and ends at, but does not include, `hold_until`. The new window is rejected with `ERR_HOLD_WINDOW_OVERLAP` when the same item already carries a hold whose `status` is not `EXPIRED` and whose `decision` is either still unset or anything other than `RELEASE_FUNDS`, and whose window intersects the new one; because the windows are half-open, two windows that merely touch — one ending exactly when the other begins — do not count as overlapping.

Deciding a `PENDING` hold records the `decision`, the `decided_at` timestamp, and the acting analyst's `decided_by_user_id`, and moves the hold to `DECIDED`. Three outcomes exist. `RELEASE_FUNDS` returns the item from `UNDER_REVIEW` to `RECEIVED` — permitted only when the decided hold is the item's latest `PENDING` hold — leaving the provisional deposit credit in place so the funds become presentable. `EXTEND_HOLD` moves `hold_until` to a supplied `extend_until`, which must be strictly later than the current `hold_until`; a missing or non-later `extend_until` is rejected with `ERR_INVALID_REQUEST`, and the item remains `UNDER_REVIEW`. `RETURN_ITEM` drives the item from `UNDER_REVIEW` to `DEPOSIT_REJECTED`: the system posts a `PROVISIONAL_REVERSAL` ledger entry for the negative of the item's `amount_cents`, marked provisional, which nets the item's ledger footprint to zero; it raises a `DEPOSIT_REJECTED_NOTICE` customer notification in `PENDING` status; and the linked `LARGE_ITEM_REVIEW` case auto-transitions from `OPEN` to `RESOLVED` with disposition `NO_ACTION`. A hold that is never decided does not strand the deposit — see §3.9 for how the daily sweep expires it.

### 3.3. Presentment: Duplicates, Encoding Errors, and Image Defects

Presenting a `RECEIVED` item sends it to its clearing bank. The bank must be `ACTIVE`; presenting against a `SUSPENDED` bank is rejected with `ERR_CLEARING_BANK_SUSPENDED`. Presentment then forks on duplicate detection.

When another check item with the same `item_reference` already exists in `PRESENTED` or `PAID` status, the new item transitions from `RECEIVED` to `DUPLICATE_REJECTED`. Its `duplicate_of_item_id` is set to the matching item — the one in `PRESENTED` or `PAID` status with the earliest `created_at` among same-reference items. To make the customer whole, the system posts a `DUPLICATE_REVERSAL_CREDIT` ledger entry for the negative of the item's `amount_cents`, marked provisional, reversing the provisional deposit credit posted at intake. It also opens an adjustment case of `case_type` `DUPLICATE_PRESENTMENT` in `OPEN` status and raises a `DUPLICATE_NOTICE` customer notification in `PENDING` status.

When no duplicate exists, the item transitions from `RECEIVED` to `PRESENTED`; `presented_at` is set to the current logical time and `presentment_count` increments by one. Two defect detectors then run automatically. If `encoded_amount_cents` differs from `amount_cents`, the system opens an `ENCODING_ERROR` adjustment case in `OPEN` status and, alongside it, a `DRAFT` adjustment claim whose `claimed_amount_cents` is the absolute difference between the encoded and face amounts and whose `created_by_user_id` is recorded as the literal string `system`. Independently, if the item's `image_quality_score` is below 60, the system opens an `IMAGE_WARRANTY` adjustment case in `OPEN` status — the foundation for the warranty claim workflow of §3.6.

### 3.4. Payment, Return Recording, Reason Coding, and the Return-Item Fee

A `PRESENTED` item that clears is marked paid: its status moves to `PAID`, `paid_at` records the logical time, and two ledger entries land together — a `PROVISIONAL_REVERSAL` for the negative of `amount_cents` (provisional) that withdraws the provisional deposit credit, and a `SETTLEMENT_CREDIT` for the positive `amount_cents` (non-provisional) that finally settles the funds. `PAID` is terminal.

A `PRESENTED` item that comes back unpaid instead moves to `RETURNED`. Recording the return creates a `ReturnEvent` in `PENDING_CODING` status with `received_at` set to the logical time, posts an `ITEM_RETURN_DEBIT` ledger entry for the negative of `amount_cents` (provisional), and opens an adjustment case of `case_type` `RETURN_ITEM` in `OPEN` status whose `return_event_id` links it to the new return event. Because the debit re-derives the account balances, an account driven below zero auto-freezes per §2.7.

Coding the return is the pivotal act. An `ItemProcessor` supplies a `reason_code` — one of `NSF`, `STOP_PAYMENT`, `CLOSED_ACCOUNT`, `MISSING_ENDORSEMENT`, `ALTERED_OR_FICTITIOUS`, `IMAGE_NONCONFORMING`, `DUPLICATE_PRESENTMENT`, or `REFER_TO_MAKER`; any other value is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — moving the return event from `PENDING_CODING` to `CODED` with `coded_at` recorded. Coding computes `re_presentment_eligible`: it is true exactly when the reason is `NSF`, `MISSING_ENDORSEMENT`, `IMAGE_NONCONFORMING`, or `REFER_TO_MAKER`, and false for `STOP_PAYMENT`, `CLOSED_ACCOUNT`, `ALTERED_OR_FICTITIOUS`, and `DUPLICATE_PRESENTMENT`. Coding also assesses the return-item fee immediately: a `FeeAssessment` of `fee_type` `RETURN_ITEM_FEE` is created in `POSTED` status, linked to the account, the `RETURN_ITEM` case, and the coded return event, and a `FEE_DEBIT` ledger entry for the negative of the fee's `amount_cents` (non-provisional) posts at once — which may itself tip the account into `FROZEN`. A `RETURN_NOTICE` customer notification is raised in `PENDING` status, its `due_at` set to the coding moment advanced to 17:00:00Z on the next business day strictly after the coding date.

The fee amount is computed as follows, with the per-component rounding pinned. Let the account's prior returns be its `returned_item_count_30d` minus one — the count is evaluated after the current event flips to `CODED`, so subtracting one removes the event being coded and leaves only the earlier ones. The base fee depends on the reason: 2500 cents for `NSF`, 3000 cents for `CLOSED_ACCOUNT`, 1500 cents for `REFER_TO_MAKER`, and zero for `STOP_PAYMENT`, `MISSING_ENDORSEMENT`, `ALTERED_OR_FICTITIOUS`, `IMAGE_NONCONFORMING`, and `DUPLICATE_PRESENTMENT`. The base is multiplied by the account's risk multiplier — 1.0 for `STANDARD`, 1.5 for `HIGH_RISK` — and that product is rounded half-up to whole cents first. A surcharge is then added: zero when there are no prior returns, 500 cents when there is one or two, and 1500 cents when there are three or more. The fee is the rounded base-times-multiplier component plus the surcharge.

A `RETURNED` item may be re-presented, cycling back to `PRESENTED`, but only under three gates: the item's latest return event (by `created_at`) must be `CODED` — otherwise `ERR_INVALID_STATE`; that return's `re_presentment_eligible` must be true — otherwise `ERR_RE_PRESENTMENT_NOT_ELIGIBLE`; and `presentment_count` must still be below 2 — a third presentment attempt is rejected with `ERR_MAX_PRESENTMENTS_EXCEEDED`. A successful re-presentment increments `presentment_count` by one and refreshes `presented_at`. The `PRESENTED` → `RETURNED` → `PRESENTED` cycle may repeat until the count reaches 2 total presentments.

### 3.5. Adjustment Case Work: Assignment, Resolution, Reopening, and Closure

Every exception the system detects — a returned item, an encoding mismatch, a warranty-grade image, a duplicate presentment, a large deposit — materializes as an adjustment case carrying its `case_type` (one of `RETURN_ITEM`, `ENCODING_ERROR`, `IMAGE_WARRANTY`, `DUPLICATE_PRESENTMENT`, `LARGE_ITEM_REVIEW`), the `check_item_id` it concerns, and for return cases the linked `return_event_id`. A case is born `OPEN` with `reopen_count` at zero and `assigned_analyst_id`, `disposition`, `resolution_amount_cents`, `escalated_at`, `resolved_at`, and `closed_at` all unset.

An `OperationsAdmin` assigns a case by supplying `assigned_analyst_id` and, per §2.9, `expected_adjustment_case_version`. Assignment is allowed from `OPEN`, `ASSIGNED`, `REOPENED`, and `ESCALATED`, always landing on `ASSIGNED`; from `ASSIGNED` it is a re-assignment that supersedes the prior assignee. Each successful assignment increments the case's `version` by one.

Resolution belongs to the assignee and no one else: an `AdjustmentAnalyst` resolving a case whose `assigned_analyst_id` differs from their `X-User-ID` is rejected with `ERR_NOT_ASSIGNED_ANALYST`. The resolver supplies a `disposition` of `CREDIT_CUSTOMER`, `DEBIT_CUSTOMER`, or `NO_ACTION`, and may attach a `resolution_note`. Unless the disposition is `NO_ACTION`, an `amount_cents` greater than zero is required — a missing or non-positive amount is rejected with `ERR_INVALID_REQUEST`. Resolving records `disposition`, `resolution_amount_cents`, and `resolved_at`, moves the case from `ASSIGNED` to `RESOLVED`, and posts the matching ledger entry: an `ADJUSTMENT_CREDIT` for the positive amount or an `ADJUSTMENT_DEBIT` for the negative amount, both non-provisional and linked via the case. Either posting re-derives the account balances, with the automatic freeze and thaw behavior of §2.7.

A resolved case is not necessarily finished. A `ComplianceOfficer` may reopen a `RESOLVED` case by supplying a `reopen_reason`; the case moves to `REOPENED`, `reopen_count` increments by one, and the prior `disposition`, `resolution_amount_cents`, and `resolved_at` are cleared. The cycle `RESOLVED` → `REOPENED` → `ASSIGNED` → `RESOLVED` may repeat as often as review demands.

Closure is gated on the case's financial children. An `AdjustmentAnalyst` or `ComplianceOfficer` may close a `RESOLVED` case only when every linked adjustment claim has reached `SETTLED` or `WRITTEN_OFF` and every linked warranty claim has reached `HONORED` or `WRITTEN_OFF`; otherwise the close is rejected with `ERR_CASE_HAS_OPEN_CLAIMS`. Closing records `closed_at` and raises a `CASE_CLOSED` customer notification in `PENDING` status. `CLOSED` is terminal. The same close also happens automatically, without a client request, the moment a linked claim or warranty reaches a terminal state and no non-terminal claims or warranties remain on a `RESOLVED` case — the bubble-up described in §3.6.

Cases also escalate. When a customer notification linked to a case breaches its delivery deadline (§3.7), a case sitting in `OPEN`, `ASSIGNED`, or `REOPENED` auto-transitions to `ESCALATED` with `escalated_at` recorded. An `ESCALATED` case can still be assigned — assignment from `ESCALATED` is one of the four permitted from-states.

### 3.6. Clearing-Bank Adjustment Claims and Image Warranty Claims

An adjustment claim pursues money from the clearing bank on a case. Claims are born `DRAFT`, either automatically at presentment (the encoding-error cascade of §3.3, created by `system`) or manually when an `AdjustmentAnalyst` creates one on a case with a `claimed_amount_cents` and an optional free-text `description`; at manual creation a missing or non-integer `claimed_amount_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) and a non-positive one with `ERR_INVALID_AMOUNT` (HTTP 422). Each claim carries its `adjustment_case_id`, the `clearing_bank_id` copied from the case's check item, the `created_by_user_id` of its creator, and its lifecycle timestamps: `submitted_at`, `settled_at`, and `written_off_at`, all unset at birth.

Both claim families expose two aging measures, recomputed against the logical clock on every read, on every daily sweep, and at write-off evaluation. `aging_calendar_days` is the whole number of calendar days from the claim's `created_at` date to the current date. `aging_business_days` counts only the Monday-through-Friday dates strictly after the creation date up to and including the current date. The two diverge quickly: a claim created on Friday 2026-05-01 and read on Monday 2026-05-11 has an `aging_calendar_days` of 10 but an `aging_business_days` of 6.

Submitting a `DRAFT` adjustment claim moves it to `SUBMITTED` and records `submitted_at`. Six preconditions guard the transition, evaluated in this order: the claim must be `DRAFT` (else `ERR_INVALID_STATE`); the linked case must be `ASSIGNED` (else `ERR_INVALID_STATE`); the submission must fall within the clearing bank's `claim_window_business_days` business days of the claim's `created_at` (else `ERR_CLAIM_WINDOW_EXPIRED`); the clearing bank must have fewer than `daily_claim_capacity` claims already submitted on the current business day (else `ERR_CLEARING_BANK_CAPACITY_EXCEEDED`); the clearing bank must be `ACTIVE` (else `ERR_CLEARING_BANK_SUSPENDED`); and `claimed_amount_cents` must be greater than zero (else `ERR_INVALID_AMOUNT`). Claims directed at a given bank can be listed per bank, so the capacity check is always auditable.

Acknowledgment is the clearing bank's handshake: an `OperationsAdmin` acknowledges a `SUBMITTED` claim, optionally recording the bank's `clearing_bank_ref`, moving it to `ACKNOWLEDGED`.

Settlement is segregated. An `AdjustmentAnalyst` settles an `ACKNOWLEDGED` or `ESCALATED` claim by supplying an `outcome` of `SETTLED` or `DENIED`; the acting analyst must not be the claim's `created_by_user_id`, on pain of `ERR_SEGREGATION_OF_DUTIES`. For an outcome of `SETTLED`, a `recovered_amount_cents` of zero or more is required (else `ERR_INVALID_REQUEST`) and is recorded alongside `settled_at`; for `DENIED`, only `settled_at` is recorded. Either way, settlement triggers the closure bubble-up: if the linked case is `RESOLVED` and no non-terminal claims or warranties remain attached to it, the case auto-transitions from `RESOLVED` to `CLOSED` and raises its `CASE_CLOSED` notification.

Claims that languish escalate and eventually die. When the daily sweep finds a `SUBMITTED` or `ACKNOWLEDGED` claim whose `aging_business_days` has reached at least 10, the claim moves to `ESCALATED`; settlement remains possible from `ESCALATED` under the same segregation rule. A `ComplianceOfficer` may write off a `DENIED` or `ESCALATED` claim — again never its creator, else `ERR_SEGREGATION_OF_DUTIES` — but only once `aging_business_days` has reached at least 30; earlier attempts are rejected with `ERR_CLAIM_NOT_AGED_ENOUGH`. Write-off records the supplied `write_off_reason` and `written_off_at`, lands the claim in the terminal `WRITTEN_OFF` state, and fires the same case-closure bubble-up.

Warranty claims run a parallel but leaner track. One may be created only on a case whose `case_type` is `IMAGE_WARRANTY` — any other case type is rejected with `ERR_CASE_TYPE_MISMATCH` — with a `claimed_amount_cents` and the creator's `created_by_user_id`; as with adjustment claims, a missing or non-integer `claimed_amount_cents` is rejected with `ERR_INVALID_REQUEST` (HTTP 400) and a non-positive one with `ERR_INVALID_AMOUNT` (HTTP 422). A warranty claim's `deadline_at` is computed at creation as the item's `presented_at` plus the clearing bank's `warranty_window_days` calendar days, and submission is allowed only while the current logical time is on or before `deadline_at`; a late submit is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`. From `SUBMITTED`, settlement by an `AdjustmentAnalyst` (never the creator, else `ERR_SEGREGATION_OF_DUTIES`) lands the claim `HONORED` — recording `recovered_amount_cents` and `settled_at` — or `REJECTED`, recording `settled_at` alone. A `SUBMITTED` warranty claim escalates to `ESCALATED` at an `aging_business_days` of at least 10, and settlement from `ESCALATED` follows the same honored-or-rejected split. Write-off by a `ComplianceOfficer` is permitted from `REJECTED` or `ESCALATED` once `aging_business_days` reaches at least 30 (else `ERR_CLAIM_NOT_AGED_ENOUGH`), never by the creator, recording `write_off_reason` and `written_off_at` and bubbling up to case closure exactly as adjustment claims do. A warranty claim's `aging_calendar_days` and `aging_business_days` follow the same algorithms as adjustment claims.

### 3.7. Customer Notifications and Fee Waivers

Every customer-facing event in this document — the large-item hold, the rejected deposit, the duplicate presentment, the coded return, the closed case — raises a `CustomerNotification`. A notification carries its `depositor_account_id`, an optional `adjustment_case_id`, a `notification_type` of `RETURN_NOTICE`, `CASE_CLOSED`, `DUPLICATE_NOTICE`, `DEPOSIT_REJECTED_NOTICE`, or `LARGE_ITEM_HOLD_NOTICE`, the rendered `message` text, and a computed `due_at`: its creation moment advanced to 17:00:00Z on the next business day strictly after the creation date. Notifications are born `PENDING`. A `CustomerService` agent delivers one, recording `delivered_at` and moving it to `DELIVERED`. If the daily sweep finds a `PENDING` notification whose `due_at` has passed, the notification moves to `BREACHED` — and, per §3.5, a linked case still in `OPEN`, `ASSIGNED`, or `REOPENED` escalates with it. Per §2.5, notifications carry no `updated_at` and no `version`.

Fee relief is deliberately two-tiered. A posted `RETURN_ITEM_FEE` assessment — carrying its `depositor_account_id`, the nullable `adjustment_case_id` and `return_event_id` that caused it, and its computed `amount_cents` — can be waived from `POSTED` to `WAIVED` by supplying a `waive_reason`. A `CustomerService` agent may waive only fees whose `amount_cents` is at most 2500 cents; anything larger is rejected with `ERR_FEE_WAIVE_LIMIT_EXCEEDED`. A `ComplianceOfficer` may waive any amount. Waiving records `waived_by_user_id`, `waive_reason`, and `waived_at`, and posts a compensating `FEE_WAIVER_CREDIT` ledger entry for the positive `amount_cents`, non-provisional and linked to the fee via `fee_assessment_id` — a credit that re-derives balances and may thaw (or, elsewhere, freeze) the account per §2.7.

### 3.8. Regulation CC Expedited Recredit

A depositor who believes a paid check was mishandled may claim expedited recredit. A `Customer` files a recredit request only against their own account (per the §2.1 ownership rule); a `CustomerService` agent may file on any account's behalf. The request names the `depositor_account_id`, the `check_item_id`, a `claimed_amount_cents`, and a `reason`, and it is born `SUBMITTED` with `submitted_at` set from the logical clock. Creation enforces a battery of guards: the referenced check item must belong to the named account (else `ERR_RECREDIT_ITEM_MISMATCH`); the item must be `PAID` (else `ERR_INVALID_STATE`); the request must be created no more than 40 calendar days after the item's `paid_at` (else `ERR_RECREDIT_WINDOW_EXPIRED`); the account's `reg_cc_eligible` must be true (else `ERR_RECREDIT_NOT_ELIGIBLE`); no other recredit request for the same item may be sitting in `SUBMITTED` or `PROVISIONALLY_CREDITED` (else `ERR_RECREDIT_ALREADY_OPEN`); and the claimed amount must be greater than zero and no more than the item's `amount_cents` (else `ERR_INVALID_AMOUNT`).

Granting provisional credit is a `CustomerService` act that moves the request to `PROVISIONALLY_CREDITED` and computes three amounts with pinned rounding. The `principal_amount_cents` is the lesser of `claimed_amount_cents` and the 250000-cent provisional cap. Interest then accrues per elapsed calendar day between the `submitted_at` date and the provisioning date: for each such day, the day's interest is the principal multiplied by the daily rate of 0.0002, rounded half-up to whole cents, and `interest_cents` is the sum of those per-day amounts. The per-day rounding order is mandatory — rounding each day first and then summing is required, and multiplying-then-rounding-once is forbidden; concretely, a principal of 133333 cents held for 5 days earns 27 cents per day and 135 cents in total, not 133. The `provisional_amount_cents` is the principal plus the interest. The system posts a `RECREDIT_PROVISIONAL_CREDIT` ledger entry for the positive provisional amount, marked provisional and linked via `recredit_request_id`, records `provisioned_at`, and computes `provisioned_late`: true when the credit posted more than 2 business days after `submitted_at`.

Finalization is an `AdjustmentAnalyst` decision with two branches. An `outcome` of `CONFIRMED` is allowed at any time: the provisional credit simply stands, `finalized_at` is recorded, and the request lands in the terminal `CONFIRMED` state. An `outcome` of `REVOKED` is allowed only while the current time is no later than 45 calendar days after `submitted_at` — later attempts are rejected with `ERR_FINALIZE_WINDOW_EXPIRED`. Revocation posts a `RECREDIT_CLAWBACK_DEBIT` ledger entry for the negative of `provisional_amount_cents`, marked provisional, which nets the recredit's ledger footprint for that request to zero; `finalized_at` is recorded; and the resulting balance re-derivation applies the freeze/thaw rules of §2.7 — a clawback can legitimately push an account negative and freeze it. `CONFIRMED` and `REVOKED` are both terminal.

Should a request sit in `SUBMITTED` for more than 2 business days without provisional credit, the daily sweep sets its `breach_flagged` boolean (initially false) to true, surfacing the missed regulatory clock.

### 3.9. The Daily Operations Sweep

Once per operating cycle, an `OperationsAdmin` triggers the daily operations checkpoint, a single sweep that advances every time-based rule in the system against the logical clock. The sweep performs four jobs and reports a count for each. First, it escalates every `SUBMITTED` or `ACKNOWLEDGED` adjustment claim and every `SUBMITTED` warranty claim whose `aging_business_days` has reached at least 10, moving them to `ESCALATED`. Second, it breaches every `PENDING` customer notification whose `due_at` has passed, moving it to `BREACHED` and cascading the escalation of §3.5 onto any linked case in `OPEN`, `ASSIGNED`, or `REOPENED`. Third, it expires every `PENDING` hold decision whose `hold_until` is at or before the current time, moving the hold to `EXPIRED`; when the expired hold's item is still `UNDER_REVIEW`, the item auto-transitions back to `RECEIVED` and its funds are released for presentment. Fourth, it flags every recredit request still `SUBMITTED` more than 2 business days after `submitted_at` by setting `breach_flagged` to true. The response reports `claims_escalated`, `warranties_escalated`, `notifications_breached`, `holds_expired`, and `recredits_flagged` so operators can reconcile exactly what the sweep touched.

## 4. Endpoint Definitions

Operations that create a new resource — an account, freeze, clearing bank, check item, return event, hold decision, claim, warranty claim, or recredit request — return `201 Created`. Operations that modify an existing resource — including state transitions such as present, pay, code, assign, resolve, settle, waive, deliver, and finalize — return `200 OK`. All resources are mounted under `/bank` except the logical-clock control, which lives at the root.

List endpoints accept the pagination parameters of §2.3 plus filters: the accounts list accepts `status`; the check-items list accepts `depositor_account_id`, `clearing_bank_id`, `duplicate_of_item_id`, and `status`; the adjustment-cases list accepts `check_item_id`, `return_event_id`, `case_type`, and `status`, while an item's own cases list accepts `case_type` and `status`; the claim lists (per case and per clearing bank) and the warranty-claims list accept `status`; the notifications list accepts `depositor_account_id`, `adjustment_case_id`, and `status`; the fees list accepts `depositor_account_id`, `adjustment_case_id`, `return_event_id`, and `status`; the recredit-requests list accepts `depositor_account_id`, `check_item_id`, and `status`; and the ledger-entries list accepts `depositor_account_id`, `check_item_id`, `adjustment_case_id`, `fee_assessment_id`, `recredit_request_id`, and `entry_type`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/bank/accounts` | Create a depositor account; a positive `opening_balance_cents` posts one non-provisional `OPENING_CREDIT` | OperationsAdmin |
| GET    | `/bank/accounts/{id}` | Read one account including computed balances and `returned_item_count_30d` | All roles |
| GET    | `/bank/accounts` | List accounts with pagination | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| PATCH  | `/bank/accounts/{id}` | Update `risk_tier` and/or `reg_cc_eligible` with OCC on the account version | OperationsAdmin |
| POST   | `/bank/accounts/{id}/freezes` | Place a closed-interval freeze window; overlapping (including touching) windows rejected | ComplianceOfficer |
| GET    | `/bank/accounts/{id}/freezes` | List freezes for an account | All roles |
| POST   | `/bank/clearing-banks` | Register a clearing bank with its deadline windows and daily claim capacity | OperationsAdmin |
| GET    | `/bank/clearing-banks/{id}` | Read one clearing bank | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| GET    | `/bank/clearing-banks/{id}/claims` | List adjustment claims directed at a clearing bank | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/check-items` | Deposit a check item; posts a provisional `DEPOSIT_CREDIT`; large items cascade into review | ItemProcessor |
| GET    | `/bank/check-items/{id}` | Read one check item | All roles |
| GET    | `/bank/check-items` | List check items with filters | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/check-items/{id}/present` | Present a `RECEIVED` item; branches to duplicate rejection or defect-case creation | ItemProcessor |
| POST   | `/bank/check-items/{id}/pay` | Mark a `PRESENTED` item paid; reverses the provisional credit and posts `SETTLEMENT_CREDIT` | ItemProcessor |
| POST   | `/bank/check-items/{id}/return-events` | Record a return from the clearing bank; item moves to `RETURNED` | ItemProcessor |
| GET    | `/bank/check-items/{id}/return-events` | List return events for an item | All roles |
| POST   | `/bank/return-events/{id}/code` | Code the return reason; assesses the fee and raises the return notice | ItemProcessor |
| POST   | `/bank/check-items/{id}/represent` | Re-present a `RETURNED` item whose latest coded return is eligible | ItemProcessor |
| POST   | `/bank/check-items/{id}/hold-decisions` | Place a manual half-open hold window on a non-terminal item | AdjustmentAnalyst |
| GET    | `/bank/check-items/{id}/hold-decisions` | List hold decisions for an item | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/hold-decisions/{id}/decide` | Decide a `PENDING` hold: release, extend, or return the item | AdjustmentAnalyst |
| GET    | `/bank/check-items/{id}/adjustment-cases` | List adjustment cases for an item | All roles |
| GET    | `/bank/adjustment-cases/{id}` | Read one adjustment case | All roles |
| GET    | `/bank/adjustment-cases` | List adjustment cases with filters | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/adjustment-cases/{id}/assign` | Assign or re-assign an analyst; OCC on the case version | OperationsAdmin |
| POST   | `/bank/adjustment-cases/{id}/resolve` | Resolve an `ASSIGNED` case; resolver must be the assignee | AdjustmentAnalyst |
| POST   | `/bank/adjustment-cases/{id}/reopen` | Reopen a `RESOLVED` case back to `REOPENED` | ComplianceOfficer |
| POST   | `/bank/adjustment-cases/{id}/close` | Manually close a `RESOLVED` case whose claims and warranties are all terminal | AdjustmentAnalyst, ComplianceOfficer |
| POST   | `/bank/adjustment-cases/{id}/claims` | Manually create a `DRAFT` adjustment claim on a case | AdjustmentAnalyst |
| GET    | `/bank/adjustment-cases/{id}/claims` | List adjustment claims for a case | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/adjustment-claims/{id}/submit` | Submit a `DRAFT` claim within the claim window and daily capacity | AdjustmentAnalyst |
| POST   | `/bank/adjustment-claims/{id}/acknowledge` | Record clearing-bank acknowledgment of a `SUBMITTED` claim | OperationsAdmin |
| POST   | `/bank/adjustment-claims/{id}/settle` | Settle an `ACKNOWLEDGED` or `ESCALATED` claim as `SETTLED` or `DENIED` | AdjustmentAnalyst |
| POST   | `/bank/adjustment-claims/{id}/write-off` | Write off a `DENIED` or `ESCALATED` claim aged at least 30 business days | ComplianceOfficer |
| POST   | `/bank/adjustment-cases/{id}/warranty-claims` | Create a `DRAFT` warranty claim on an `IMAGE_WARRANTY` case | AdjustmentAnalyst |
| GET    | `/bank/adjustment-cases/{id}/warranty-claims` | List warranty claims for a case | OperationsAdmin, ItemProcessor, AdjustmentAnalyst, ComplianceOfficer, CustomerService |
| POST   | `/bank/warranty-claims/{id}/submit` | Submit a `DRAFT` warranty claim by its `deadline_at` | AdjustmentAnalyst |
| POST   | `/bank/warranty-claims/{id}/settle` | Settle a `SUBMITTED` or `ESCALATED` warranty claim as `HONORED` or `REJECTED` | AdjustmentAnalyst |
| POST   | `/bank/warranty-claims/{id}/write-off` | Write off a `REJECTED` or `ESCALATED` warranty claim aged at least 30 business days | ComplianceOfficer |
| GET    | `/bank/notifications/{id}` | Read one customer notification | All roles |
| GET    | `/bank/notifications` | List notifications with filters | All roles |
| POST   | `/bank/notifications/{id}/deliver` | Mark a `PENDING` notification delivered | CustomerService |
| GET    | `/bank/fees/{id}` | Read one fee assessment | All roles |
| GET    | `/bank/fees` | List fee assessments with filters | All roles |
| POST   | `/bank/fees/{id}/waive` | Waive a `POSTED` fee; `CustomerService` capped at 2500 cents, `ComplianceOfficer` uncapped | CustomerService, ComplianceOfficer |
| POST   | `/bank/recredit-requests` | File a Reg CC expedited recredit request for a `PAID` item | Customer, CustomerService |
| GET    | `/bank/recredit-requests/{id}` | Read one recredit request | All roles |
| GET    | `/bank/recredit-requests` | List recredit requests with filters | All roles |
| POST   | `/bank/recredit-requests/{id}/provisional-credit` | Grant provisional recredit with per-day-rounded interest | CustomerService |
| POST   | `/bank/recredit-requests/{id}/finalize` | Finalize as `CONFIRMED` anytime or `REVOKED` within 45 days | AdjustmentAnalyst |
| GET    | `/bank/ledger-entries/{id}` | Read one ledger entry; the ledger is append-only | All roles |
| GET    | `/bank/ledger-entries` | List ledger entries with filters | All roles |
| POST   | `/bank/ops/run-daily` | Daily operations sweep: escalations, notification breaches, hold expirations, recredit flags | OperationsAdmin |
| POST   | `/_clock/set_current_utc` | Set the logical clock used by every timestamp, deadline, and aging computation | OperationsAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_ANALYST` | 403 Forbidden |
| `ERR_FEE_WAIVE_LIMIT_EXCEEDED` | 403 Forbidden |
| `ERR_ACCOUNT_NOT_FOUND` | 404 Not Found |
| `ERR_CLEARING_BANK_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_CASE_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_NOTIFICATION_NOT_FOUND` | 404 Not Found |
| `ERR_FEE_NOT_FOUND` | 404 Not Found |
| `ERR_RECREDIT_NOT_FOUND` | 404 Not Found |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ACCOUNT_FROZEN` | 409 Conflict |
| `ERR_CLEARING_BANK_SUSPENDED` | 409 Conflict |
| `ERR_MAX_PRESENTMENTS_EXCEEDED` | 409 Conflict |
| `ERR_RE_PRESENTMENT_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CLAIM_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_AGED_ENOUGH` | 422 Unprocessable Entity |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RECREDIT_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FINALIZE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_FREEZE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_HOLD_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CLEARING_BANK_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_CASE_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CASE_HAS_OPEN_CLAIMS` | 409 Conflict |
| `ERR_RECREDIT_ALREADY_OPEN` | 409 Conflict |
| `ERR_RECREDIT_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_RECREDIT_ITEM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ACCOUNT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_ROUTING_NUMBER` | 409 Conflict |
| `ERR_INVALID_AMOUNT` | 422 Unprocessable Entity |

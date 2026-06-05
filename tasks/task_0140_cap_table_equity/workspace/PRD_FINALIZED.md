# Cap Table & Equity Management API — Product Requirements Document

## 1. Introduction

Privately held companies maintain a capitalization table — a living ledger of who owns what, expressed across founder common stock, preferred investor classes, employee option grants, convertible instruments, and the reserves that back them. As a company raises money, hires, grants options, and ultimately exits, that ledger must stay internally consistent: shares issued can never exceed the charter's authorization, option pools can never be over-allocated, option strike prices must respect the most recent 409A appraisal, and a liquidity event must distribute proceeds in strict accordance with the seniority and participation terms negotiated into each preferred class. Errors here are not cosmetic; they translate directly into tax exposure for employees, securities-law violations for the company, and disputes among investors at the moment of exit.

This API is the system of record for that ledger. It governs the full lifecycle of every equity instrument: registering shareholders and defining security classes; issuing shares; recording 409A valuations and enforcing their safe-harbor windows; drafting, approving, exercising, and expiring option grants under cliff-and-graded vesting; capturing early exercises and the Section 83(b) elections that accompany them; converting SAFEs and convertible notes at the better of their cap or discount price; and computing the liquidation-preference waterfall at exit. Because many of these actions carry regulatory consequence — IRS Form 3921 filings, the 30-day 83(b) window, insider-trading blackout periods — the system enforces a strict separation between the operational staff who draft instruments and the board-level approvers who ratify them, and it reports a comprehensive catalogue of machine-readable error codes so that downstream tooling can react precisely to every rejected request.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract that governs every endpoint: authentication, the response envelope, pagination, shared resource semantics, numeric precision, concurrency control, and the cross-cutting consistency rules that hold the ledger together.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two headers identifying the caller. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they act. If either header is missing, or `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly four roles: `Administrator`, `BoardApprover`, `Stakeholder`, and `Auditor`. Their privileges follow a segregation-of-duties model. An `Administrator` is the operations team: it creates cap tables, security classes, shareholders, option pools, valuations, and liquidation events; drafts option grants and SAFE/note instruments; records share issuances; settles, reverses, and files paperwork for exercises; processes 83(b) elections; schedules and lifts blackout windows; and drives the test clock. A `BoardApprover` represents the board and legal counsel: it approves grants and valuations, locks/unlocks/dissolves the table, executes and converts and repays notes, refreshes pools, and runs and finalizes the liquidation waterfall. A `Stakeholder` is an individual shareholder acting on their own holdings: it exercises its own option grants and files 83(b) elections against its own exercises. An `Auditor` is a read-only compliance reviewer. All four roles may perform GET reads within the scope described below.

The `Administrator`, `BoardApprover`, and `Auditor` roles carry an **opaque** identity: for these roles, `X-User-ID` is an operator identifier that the server does not match against any persisted entity. The server may record such an identifier where a transition writes it — for example, when a `BoardApprover` approves a grant, the approver's `X-User-ID` is stored on that grant as `approved_by_user_id` — but it is never compared to any entity's `id`. The `Stakeholder` role is **entity-backed**: when `X-User-Role` is `Stakeholder`, `X-User-ID` is the `id` of the acting `Shareholder`, and ownership checks on any resource that references a shareholder compare the resource's `shareholder_id` foreign key to `X-User-ID`. A `Stakeholder` may exercise and file elections only against grants and exercises whose `shareholder_id` equals its own `X-User-ID`, and its reads are scoped to its own holdings.

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

List endpoints accept two query parameters to page through results. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the front of the result set and defaults to 0.

Unless explicitly stated otherwise, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` reflects the full size of the filtered collection and `has_more` indicates whether further pages remain.

### 2.4. Common Resource Properties and Computed-Field Freshness

Most entities in this system are mutable and carry a uniform set of system-managed fields: `id` (a server-minted UUID with no type prefix), `created_at` (an ISO 8601 UTC timestamp with three fractional digits, set once at creation), `updated_at` (an ISO 8601 UTC timestamp refreshed on every mutation), and `version` (an integer that starts at 1 on creation and increments by one on every mutation). Every stateful entity also exposes a `status` field carrying its current lifecycle state as one of the exact uppercase strings enumerated for that entity in §3. A request whose body is malformed, omits a required field, or supplies a value of the wrong type or an enum value outside the declared set is rejected with `ERR_VALIDATION` (HTTP 400). Any change to a resource's properties — including a change to a derived field such as a cap table's `issued_shares` or `fully_diluted_shares`, or a pool's `allocated_shares` — counts as a mutation and therefore refreshes `updated_at` and increments `version`.

Three entities are append-only audit records that are immutable after creation, and therefore carry only `id` and `created_at`; they have neither `updated_at` nor `version`. These are `ShareIssuance` (an immutable record of one issuance, stamped with `issued_at`), `Form3921` (the generated IRS form), and `WaterfallDistribution` (one per-class allocation row produced by the waterfall). A `ShareIssuance` records the `issued_at` server timestamp at the moment shares are minted.

Several fields are computed against live state rather than stored verbatim, and the read endpoints recompute them before responding. Fetching a cap table recomputes its `issued_shares` and `fully_diluted_shares` before returning. Fetching an option pool recomputes its `allocated_shares` and `available_shares`. Fetching an option grant recomputes its `vested_shares` against the current clock, so the same grant reports a larger vested figure as time advances. Because vesting and several compliance windows are time-dependent, an administrative test-driving capability sets the server's notion of "now" to a supplied `to_iso8601` instant; all `vested_shares` and temporal-window computations honor that clock.

### 2.5. Monetary, Share, and Precision Rules

Monetary quantities throughout the system are expressed in integer **cents** and are returned as integers, never as decimal dollars or strings; share counts are likewise integers. Where a calculation produces a fractional intermediate result, the rounding rule depends on the quantity:

- **Share counts** are always floored (rounded down) to whole shares. Vesting accrual, SAFE/note conversion share counts, and as-converted dilution figures each take the floor of their fractional result.
- **Accrued interest and waterfall allocations** are rounded half-up to whole cents. Where a half-up step appears inside a per-item loop (for instance, the waterfall's per-class allocations), the rounding is applied at each per-class step, and any residual cents left over from rounding are assigned to the most senior class in seniority order so that the per-class allocations always sum exactly to the proceeds distributed.
- **Exercise spread** is computed in exact integer cents with no rounding.

Configuration and rate inputs (such as `liquidation_pref_multiple`, `participation_cap_multiple`, `discount_pct`, and `interest_rate_pct`) are stored at the precision supplied by the client.

### 2.6. Optimistic Concurrency Control

Three mutating operations are guarded by optimistic concurrency control (OCC) and require the caller to declare the version of the parent entity it last observed. In each case the request body carries an `expected_<entity>_version` field that the server compares against the entity's current `version`; if they differ — meaning another writer advanced the entity since the caller read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and no state change occurs.

- Locking a cap table requires `expected_cap_table_version` to match the target cap table's current `version`. Any issuance, grant approval, or valuation approval bumps the table's version, so a lock carrying a stale value is acting on an outdated snapshot and is rejected.
- Refreshing an option pool requires `expected_pool_version` to match the pool's current `version`. A grant approval that exhausts the pool bumps its version, so a refresh carrying a stale value would top up against an outdated `available_shares` figure and is rejected.
- Converting a SAFE/note requires `expected_note_version` to match the note's current `version`. A revise or execute on the same note legitimately bumps its version, so a converter carrying a stale value is operating on outdated conversion terms and is rejected.

Operations not in this list do not take a version field and are not subject to an OCC check.

### 2.7. Referential Integrity and Path Resolution

Almost every entity hangs off a single `cap_table_id` foreign key and references its peers — security classes, shareholders, pools, grants, valuations, exercises, liquidation events — by id carried in the request body rather than through a nested URL path. Whenever a request names a resource by id, either in the path or in the body (for example `cap_table_id`, `security_class_id`, `shareholder_id`, `option_pool_id`, `option_grant_id`, `valuation_id`, `exercise_id`, or `liquidation_event_id`), the server resolves those ids left-to-right and rejects the first one that does not resolve to an existing entity with `ERR_NOT_FOUND` (HTTP 404). Relationships are never declared as schema in the request; they are expressed by supplying the relevant id in the payload of the action that creates or mutates the resource.

### 2.8. Cascading Consistency and the Ledger Totals

A single action frequently mutates several entities at once, and the system applies every such cascade immediately and atomically within the request. The two cap-table-level totals are the focal point of these cascades. `issued_shares` is defined as the sum of `shares_outstanding` across every security class on the cap table, and it is recomputed on every issuance, every exercise settlement or reversal, and every note conversion. `fully_diluted_shares` builds on that figure: it is `issued_shares`, plus the still-unexercised portion of every `ACTIVE` option grant (each grant's `share_count` minus its `exercised_shares`), plus the `available_shares` reserve of every `ACTIVE` option pool, plus the as-converted share equivalent of every `OUTSTANDING` SAFE/note evaluated at the latest `EFFECTIVE` valuation's implied price (each note's as-converted contribution is floored to whole shares before being summed). `fully_diluted_shares` is recomputed on grant approval, cancellation, and expiry; on valuation approval; on note execution and conversion; and on exercise settlement and reversal. Every recomputation of these totals is a mutation of the cap table and therefore bumps its `version` and `updated_at`.

Whenever a child mutation invalidates or satisfies the criteria for a parent's state, the parent is adjusted automatically without a separate client request — for instance, an option pool flips between `ACTIVE` and `EXHAUSTED` as grants consume or release its capacity, with no explicit pool-transition call. These automatic parent adjustments are described in the relevant workflows of §3.

## 3. Business Logic & Workflows

### 3.1. The Cap Table Container and Its Lifecycle

Everything begins with a **cap table**, created by an `Administrator` who supplies a `company_name` (a non-empty string of at most 200 characters) and the `authorized_shares` the corporate charter permits (a positive integer). A freshly created table opens in `OPEN` status with `issued_shares` and `fully_diluted_shares` both at zero and `locked_at` null.

A `BoardApprover` governs the table's lifecycle. Locking the table moves it from `OPEN` to `LOCKED` and stamps `locked_at` with the current time; unlocking returns it from `LOCKED` to `OPEN` and clears `locked_at` back to null. A `LOCKED` table freezes new issuances, grants, and note executions, but exercises and the liquidation waterfall may still proceed. Dissolution moves the table from `OPEN` to `DISSOLVED`, a terminal state, and is permitted only when no option grant on the table is in `ACTIVE` status. Each of these three transitions increments the cap table's `version`. A transition requested from the wrong starting state — for example, dissolving a table that is already `LOCKED`, or unlocking one that is `OPEN` — is rejected with `ERR_INVALID_STATE` (HTTP 409). Both the lock and unlock transitions require the table to be in the expected source state (`OPEN` for lock, `LOCKED` for unlock), and the lock transition additionally enforces the OCC check of §2.6.

### 3.2. Security Classes and the Preference Stack

An `Administrator` defines each **security class** against a cap table via `cap_table_id`, giving it a `name` (non-empty and unique within that cap table), a `class_type` of either `COMMON` or `PREFERRED`, and an `original_issue_price_cents` (a non-negative integer per-share issue price). A class begins with `shares_outstanding` at zero; that figure rises only as shares are issued into the class or as option exercises and note conversions mint shares into it.

Preferred classes carry the terms that govern an exit. The `liquidation_pref_multiple` (a non-negative number defaulting to 1.0) sets how many times the invested capital the class is entitled to before junior holders are paid; a `COMMON` class must carry a multiple of zero. The `participating` boolean (default false) marks whether the class double-dips — taking its preference and then also sharing in the residual — and `participation_cap_multiple` (a non-negative number, default 0, where 0 means uncapped) limits a participating class's total return as a multiple of its invested capital. The class's position in the liquidation stack is set by `seniority_below_class_id`, a self-referential reference to the class that sits immediately *above* it in the stack; the named class is paid before this one. A class whose `seniority_below_class_id` is null is the most senior. The chain must remain acyclic: if a supplied `seniority_below_class_id` would introduce a cycle in the preference stack, the creation is rejected with `ERR_SENIORITY_CYCLE` (HTTP 422). Security classes can be listed and filtered by `cap_table_id` or by `seniority_below_class_id`.

### 3.3. Shareholders and Share Issuance

A `Shareholder` is registered by an `Administrator` against a `cap_table_id` with a `legal_name` (non-empty), a `holder_type` of `FOUNDER`, `EMPLOYEE`, `INVESTOR`, or `ENTITY`, and an `email` that must be non-empty and unique within the cap table. The `is_us_taxpayer` boolean (default true) records whether the holder is subject to IRS reporting and therefore eligible for a Form 3921 on exercise.

Issuing shares is an append-only event recorded by an `Administrator`. A **share issuance** names the target `cap_table_id`, `security_class_id`, and recipient `shareholder_id`, the positive `share_count` to mint, and the total `price_paid_cents` (a non-negative integer) of consideration. The server stamps an `issued_at` timestamp and the record is immutable thereafter. Issuance carries two guards beyond existence checks: the cap table must be `OPEN` — issuing onto a `LOCKED` or `DISSOLVED` table is rejected with `ERR_TABLE_NOT_OPEN` (HTTP 409) — and the issuance must not overflow the charter, meaning the requested `share_count` added to the cap table's current `issued_shares` must not exceed the table's `authorized_shares`, otherwise the request is rejected with `ERR_AUTHORIZED_EXCEEDED` (HTTP 422). On success the named class's `shares_outstanding` rises by `share_count`, the cap table's `issued_shares` and `fully_diluted_shares` are recomputed, and the table's `version` is incremented. Issuances can be listed and filtered by `cap_table_id`, `security_class_id`, or `shareholder_id`.

### 3.4. 409A Valuations and the Safe-Harbor Window

A **valuation** is the 409A appraisal that anchors option strike prices. An `Administrator` records one against a `cap_table_id` with an `fmv_per_share_cents` (a positive integer fair-market value per common share), a `valuation_date` marking the start of the safe-harbor window, and an `expires_at` marking its end — typically twelve months after the valuation date. A new valuation is created in `DRAFT` status with `superseded_by_id` null.

The safe-harbor window `[valuation_date, expires_at]` is treated as **closed** on both ends: a new valuation is rejected with `ERR_VALUATION_WINDOW_OVERLAP` (HTTP 409) if its window overlaps the window of any non-`SUPERSEDED` valuation already on the same cap table, and because the interval is closed, two windows that merely touch at a shared endpoint — one ending exactly when the other begins — are considered to conflict. (This is deliberately stricter than the blackout-window rule of §3.11, whose intervals are half-open and permit adjacency.)

A `BoardApprover` makes a valuation `EFFECTIVE`, which is permitted only from `DRAFT` and only while the cap table is not `DISSOLVED`. Approval transitions the valuation `DRAFT → EFFECTIVE` and, as a cascade, supersedes the cap table's prior `EFFECTIVE` valuation if one exists: that earlier valuation transitions `EFFECTIVE → SUPERSEDED` and its `superseded_by_id` is set to the newly effective valuation's id, leaving at most one `EFFECTIVE` valuation per cap table at any time. Approval also recomputes `fully_diluted_shares` — outstanding SAFEs and notes re-price as-converted at the new fair-market value — and increments the cap table's `version`. Valuations can be listed and filtered by `cap_table_id` or by `superseded_by_id`.

### 3.5. Option Pools and Pool Refresh

An **option pool** reserves shares for future grants. An `Administrator` creates one against a `cap_table_id` with a positive `authorized_shares` reservation; it opens `ACTIVE` with `allocated_shares` at zero and `available_shares` equal to its authorized reservation. As grants draw on the pool, `allocated_shares` is the sum of `share_count` across the pool's grants in `ACTIVE` or `EXERCISED` status (grants that are `CANCELLED` or `EXPIRED` return their shares and are excluded), and `available_shares` is `authorized_shares` minus `allocated_shares`, floored at zero. When a grant approval drives `available_shares` to zero the pool flips `ACTIVE → EXHAUSTED` automatically, and when a later cancellation or expiry frees shares so that `available_shares` rises above zero the pool flips `EXHAUSTED → ACTIVE` automatically.

A `BoardApprover` can refresh a pool to top it up. Refreshing requires the pool to be `ACTIVE`, supplies a `refresh_increment_shares` top-up amount, and enforces the OCC check via `expected_pool_version`. For a pool refresh specifically, the OCC `expected_pool_version` check is evaluated before the `ACTIVE`-state gate: because the same grant approval that exhausts a pool both bumps its `version` and flips it out of `ACTIVE` (§2.6), a refresh carrying a stale `expected_pool_version` is rejected with `ERR_STALE_VERSION` even when the pool is no longer `ACTIVE`, and the not-`ACTIVE` gate (which otherwise yields `ERR_INVALID_STATE`) is reached only once the supplied version matches. On success the old pool transitions `ACTIVE → CLOSED`, its `version` is incremented, and a brand-new `ACTIVE` pool is created as a cascade whose `authorized_shares` equals the old pool's `available_shares` plus `refresh_increment_shares`; the new pool inherits no grants and starts its own allocation tally from zero. Pools can be listed and filtered by `cap_table_id`.

### 3.6. Drafting and Approving Option Grants

The grant is the heart of employee equity, and its lifecycle is deliberately a two-person process. An `Administrator` first drafts an **option grant** against a `cap_table_id`, naming the `option_pool_id` it draws from, the grantee `shareholder_id`, the `security_class_id` whose shares it will mint on exercise, and the `valuation_id` whose appraisal sets the strike. The draft supplies a positive `share_count`, a positive `strike_price_cents` per-share exercise price, a `grant_date` that is the vesting commencement date, a positive `vesting_months` total duration, and the vesting shape: `cliff_months` (a non-negative integer no greater than `vesting_months`, defaulting to 0 for no cliff), a `vesting_style` of `GRADED` or `CLIFF_ONLY` (default `GRADED`), and an `early_exercise_allowed` boolean (default false). A new grant opens in `DRAFT` with `vested_shares` and `exercised_shares` at zero and `approved_by_user_id` null.

Two compliance gates apply at draft time. The class named by `security_class_id` must be a `COMMON` class — naming a preferred class is rejected with `ERR_WRONG_CLASS_TYPE` (HTTP 422). And the strike must respect 409A: the `strike_price_cents` must be at least the `fmv_per_share_cents` of the grant's valuation, which itself must be `EFFECTIVE`; a strike below that fair-market value, or a valuation that is not effective, is rejected with `ERR_409A_NONCOMPLIANT` (HTTP 422). Separately, the chosen valuation must not be expired relative to the grant: the valuation's `expires_at` must be on or after the `grant_date`, otherwise the draft is rejected with `ERR_VALUATION_EXPIRED` (HTTP 422). Drafting onto a table that is not `OPEN` is rejected with `ERR_TABLE_NOT_OPEN`.

Approval is reserved to a `BoardApprover` and is the segregation-of-duties choke point. A grant may be approved only from `DRAFT` and only while the cap table is `OPEN`; approving onto a table that is not `OPEN` is rejected with `ERR_TABLE_NOT_OPEN`. The approving `BoardApprover`'s `X-User-ID` must differ from the `Administrator` who drafted the grant; an attempt by the same user to both draft and approve is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The 409A compliance check is re-evaluated at approval as well. The pool must have room — its `available_shares` must be at least the grant's `share_count`, otherwise the approval is rejected with `ERR_POOL_INSUFFICIENT` (HTTP 422). On a clean approval the grant moves `DRAFT → ACTIVE`, `approved_by_user_id` is set to the approver's `X-User-ID`, and as a cascade the pool's `allocated_shares` rises by `share_count` (which may push the pool to `EXHAUSTED`) and the cap table's `fully_diluted_shares` is recomputed. Grants can be listed and filtered by `cap_table_id`, `option_pool_id`, `shareholder_id`, `security_class_id`, or `valuation_id`.

An `Administrator` may cancel a grant. Cancelling a grant that is still `DRAFT` moves it `DRAFT → CANCELLED` with no pool effect, because a draft never drew on the pool. Cancelling a grant that is `ACTIVE` is permitted only when its `exercised_shares` is exactly zero; if any shares have already been exercised, the cancellation is rejected with `ERR_GRANT_HAS_EXERCISES` (HTTP 409). A valid `ACTIVE → CANCELLED` cancellation is a compensating action that returns the full grant to the pool: the pool's `allocated_shares` falls by `share_count`, its `available_shares` is recomputed, the pool flips `EXHAUSTED → ACTIVE` if shares were freed, and the cap table's `fully_diluted_shares` is recomputed. An `Administrator` may also expire a grant, which is permitted only from `ACTIVE` and only once the clock has advanced past the grant's `grant_date` plus its `vesting_months` plus a three-month post-termination exercise window. Expiry moves the grant `ACTIVE → EXPIRED` and returns its unexercised portion — `share_count` minus `exercised_shares` — to the pool, decrementing `allocated_shares`, recomputing `available_shares` (flipping the pool `EXHAUSTED → ACTIVE` if freed), and recomputing the cap table's `fully_diluted_shares`. Recall from §3.1 that a cap table cannot be dissolved while any grant remains `ACTIVE`.

### 3.7. Vesting Mechanics

A grant's `vested_shares` is derived live against the current clock from its `grant_date`, `cliff_months`, `vesting_months`, and `vesting_style`. The system first computes the number of whole months elapsed between the `grant_date` and "now", flooring any partial month down to a whole month count. If that elapsed-month count is below `cliff_months`, nothing has vested and `vested_shares` is zero. Once the cliff is reached or passed, the two vesting styles diverge: a `CLIFF_ONLY` grant vests its entire `share_count` in a single step at the cliff and holds there. A `GRADED` grant accrues linearly — the vested figure is the grant's `share_count` multiplied by the lesser of the elapsed whole-months and `vesting_months`, divided by `vesting_months`, with the result floored to whole shares. In all cases the computed figure is capped at `share_count`, so a grant can never report more vested shares than were granted.

### 3.8. Exercising Options and Settling

A `Stakeholder` (acting on its own grant) or an `Administrator` exercises options by creating an **exercise** against a `cap_table_id` and an `option_grant_id`, supplying the positive `share_count` to exercise. The exercise opens in `PENDING` status. The number exercisable depends on whether early exercise is permitted: if the grant's `early_exercise_allowed` is false, the exercise's `share_count` may not exceed the grant's currently `vested_shares` (net of shares already exercised); if early exercise is allowed, it may draw on unvested shares up to the full ungranted-but-unexercised balance, namely the grant's `share_count` minus its `exercised_shares`. A request that exceeds the exercisable amount is rejected with `ERR_EXCEEDS_EXERCISABLE` (HTTP 422). When an exercise reaches beyond the vested portion under an early-exercise grant, the system marks the exercise's `is_early_exercise` flag true (it is false otherwise). Exercises can be listed and filtered by `cap_table_id`, `option_grant_id`, or `filing_3921_id`.

Settlement, performed by an `Administrator`, is permitted only when the exercise is `PENDING` and its grant is `ACTIVE`. Settling moves the exercise `PENDING → SETTLED` and triggers a three-level cascade: the grant's `exercised_shares` rises by the exercise's `share_count`; the grant's target security class has its `shares_outstanding` raised by the same amount; and that in turn recomputes the cap table's `issued_shares` and `fully_diluted_shares`. Settlement also computes the exercise's `spread_cents` — the taxable bargain element — as the per-share difference between the grant's valuation `fmv_per_share_cents` and the grant's `strike_price_cents`, floored at zero, multiplied by the exercise's `share_count`, in exact cents. If, after settling, the grant's `exercised_shares` has reached its `share_count`, the grant transitions `ACTIVE → EXERCISED` automatically.

Reversal, also by an `Administrator`, unwinds an exercise. A `PENDING` exercise that was never settled is simply voided to `REVERSED` with no share movement to undo. A `SETTLED` exercise can be reversed only if no `ACCEPTED` 83(b) election references it; if one does, the reversal is rejected with `ERR_ELECTION_BLOCKS_REVERSE` (HTTP 409). When a settled exercise is reversed, the depth-three cascade runs in reverse as a compensating action: the grant's `exercised_shares` falls by the exercise's `share_count`, the class's `shares_outstanding` falls by the same amount, and the cap table's `issued_shares` and `fully_diluted_shares` are recomputed, so that the net effect on `issued_shares` is zero relative to the pre-exercise state. If the grant had been driven to `EXERCISED`, it reverts to `ACTIVE`, and any Form 3921 that had been generated for the exercise is voided and its linkage cleared.

### 3.9. Form 3921 and Section 83(b) Elections

When an employee subject to U.S. tax exercises incentive options, the company must file IRS Form 3921. An `Administrator` generates a **Form 3921** for a given exercise; generation requires the exercise to be `SETTLED` and the underlying `shareholder_id` to be a U.S. taxpayer (`is_us_taxpayer` true), otherwise it is rejected. The form is an immutable record derived from the exercise's grant and valuation: it captures the owning `cap_table_id`, the `exercise_id`, the reported `shareholder_id`, the `tax_year` (the calendar year of the exercise's settlement), the `exercise_fmv_cents` (the per-share fair-market value from the grant's valuation), the `strike_price_cents` copied from the grant, and the `shares_transferred` the exercise minted. Generating the form sets the exercise's `filing_3921_id` to point at it. Form 3921 records can be listed and filtered by `cap_table_id`, `exercise_id`, or `shareholder_id`. Note that the bargain element drives whether the form reports a positive spread: an exercise where the valuation fair-market value exceeds the strike reports a positive `spread_cents`, while an exercise at or under water reports a `spread_cents` floored to zero, yet the form is still issued.

An early exercise gives the holder the option to file a **Section 83(b) election** with the IRS, and the 30-day deadline for doing so is rigid. A `Stakeholder` (on its own exercise) or an `Administrator` files an election against a `cap_table_id` and an `exercise_id`, supplying the `filed_date` on which the election was postmarked. On filing, the election opens in `PENDING` status, and the server copies the anchoring `exercise_date` from the referenced exercise — this is the date from which the 30-day window runs. Elections can be listed and filtered by `cap_table_id` or `exercise_id`.

Adjudication is performed by an `Administrator` and forks on the 30-day boundary. From `PENDING`, if the `filed_date` is on or before the `exercise_date` plus 30 days — the boundary at exactly 30 days counts as on-time — the election transitions to `ACCEPTED`; if the `filed_date` falls strictly later than 30 days after the `exercise_date`, the same adjudication transitions it to `REJECTED_LATE`. A late filing is surfaced as `ERR_83B_WINDOW_MISSED` (HTTP 422). Both branches of this fork carry equal weight: the on-time branch and the late branch are governed by the same single boundary, evaluated inclusively at the 30-day mark.

### 3.10. SAFEs, Convertible Notes, and Conversion

A **SAFE or convertible note** is drafted by an `Administrator` against a `cap_table_id` and an investor `shareholder_id`, declaring its `instrument_type` of `SAFE` or `NOTE`, a positive `principal_cents`, an optional `valuation_cap_cents` (a non-negative post-money cap, 0 meaning no cap), an optional `discount_pct` (at least 0 and strictly below 1, where 0.20 means a 20% discount), an optional `interest_rate_pct` (a non-negative simple annual rate that must be 0 for a `SAFE` and may be positive only for a `NOTE`), and an `issue_date` from which interest accrues. The instrument opens in `DRAFT` with `converted_share_count` at zero and `converted_into_class_id` null.

Before binding, a note moves through a revision cycle driven by an `Administrator`: submitting terms advances it `DRAFT → NEGOTIATING`, and revising sends it back `NEGOTIATING → DRAFT` (a revise increments the note's `version`). A `BoardApprover` executes the note from `NEGOTIATING → OUTSTANDING`, which is allowed only while the cap table is `OPEN` (otherwise `ERR_TABLE_NOT_OPEN`) and which recomputes the cap table's `fully_diluted_shares` now that the note counts as-converted. From `OUTSTANDING`, a `BoardApprover` may either repay the note (`OUTSTANDING → REPAID`, the note-only path where principal and accrued interest are returned and no shares are minted) or convert it.

Conversion, by a `BoardApprover`, requires the note to be `OUTSTANDING`, a supplied `target_class_id` that must name an existing `PREFERRED` class on the same cap table (a non-preferred target is rejected with `ERR_WRONG_CLASS_TYPE`), and the OCC check via `expected_note_version`. The number of shares minted, `converted_share_count`, is computed to give the investor the more favorable of two prices. First the accrued amount is determined: for a `NOTE`, the accrued interest is the `principal_cents` multiplied by the `interest_rate_pct` and by the number of years elapsed — the day count between `issue_date` and now divided by 365 — with the accrued interest rounded half-up to whole cents; for a `SAFE` the accrued amount is zero. The invested base is `principal_cents` plus accrued interest. The priced-round per-share price is the target class's `original_issue_price_cents`. The discount price is that round price multiplied by one minus `discount_pct`. If `valuation_cap_cents` is greater than zero, a cap price is computed as `valuation_cap_cents` divided by the cap table's current `fully_diluted_shares`, and the effective conversion price is the lesser of the discount price and the cap price; if there is no cap, the discount price governs. The `converted_share_count` is the invested base divided by the effective price, floored to whole shares — so a binding cap yields more shares per dollar than the discount, and the discount governs whenever the discount price is at most the cap price or no cap exists. On conversion, `converted_into_class_id` is set to the target class, that class's `shares_outstanding` rises by `converted_share_count`, the cap table's `issued_shares` and `fully_diluted_shares` are recomputed, the note moves `OUTSTANDING → CONVERTED`, and the note's `version` is incremented. Notes can be listed and filtered by `cap_table_id`, `shareholder_id`, or `converted_into_class_id`.

### 3.11. Blackout Windows

To enforce insider-trading lockouts, an `Administrator` schedules a **blackout window** against a `cap_table_id` with a `reason` label (a non-empty string such as `PRE_EARNINGS` or `ACQUISITION`), a `starts_at`, and an `ends_at` that must be strictly after `starts_at`. The window opens `SCHEDULED`. Unlike the valuation safe-harbor window, a blackout interval `[starts_at, ends_at)` is **half-open**: a new window is rejected with `ERR_BLACKOUT_OVERLAP` (HTTP 409) only when it strictly overlaps a `SCHEDULED` window already on the same cap table, and two windows that merely abut — one ending exactly when the next begins — do *not* conflict. An `Administrator` may lift a scheduled window, transitioning it `SCHEDULED → LIFTED`; a lifted window no longer participates in overlap checks, freeing its interval. Blackout windows can be listed and filtered by `cap_table_id`.

### 3.12. The Liquidation-Preference Waterfall

At exit, an `Administrator` creates a **liquidation event** against a `cap_table_id` with the `total_proceeds_cents` to distribute (a non-negative integer). The event opens `DRAFT`. A `BoardApprover` computes the waterfall, which is permitted only from `DRAFT` and only when the cap table has at least one security class; computation produces one **waterfall distribution** row per security class and moves the event `DRAFT → COMPUTED`. From `COMPUTED`, the approver may recompute — which deletes every waterfall distribution row for the event and returns it to `DRAFT` so the allocation can be re-run — or finalize, which moves the event `COMPUTED → FINALIZED` and locks the allocations as immutable. The share counts used in the computation are pinned at compute time.

The waterfall runs in two passes over the security classes, all amounts in integer cents rounded half-up at each per-class allocation. **Pass one pays liquidation preferences in seniority order, most senior first.** Classes are ordered by walking the seniority chain top-down: a class whose `seniority_below_class_id` is null is most senior, and each class is paid after the class it points to; where two classes name the same parent, the tie is broken by `created_at` ascending. For each preferred class in that order, the invested capital is its `original_issue_price_cents` multiplied by its `shares_outstanding`, the preference owed is that invested figure multiplied by the class's `liquidation_pref_multiple` (rounded half-up), and the class is paid the lesser of its preference and the proceeds still remaining; the amount paid is recorded as that class's `preference_paid_cents` and subtracted from the remaining proceeds. **Pass two distributes the residual pro-rata.** A non-participating preferred class has already taken its preference and does not share in the residual at all; instead its economics are the *greater* of its preference or its as-converted pro-rata share, and it never takes both. The participating set — every `COMMON` class plus every participating preferred class — shares the residual in proportion to `shares_outstanding`: each such class's raw participation is the remaining proceeds multiplied by its `shares_outstanding` divided by the total participating shares (the summed `shares_outstanding` of all common and participating-preferred classes), rounded half-up. For a participating preferred class that carries a positive `participation_cap_multiple`, the total it may receive is capped: the cap total is its `participation_cap_multiple` times its invested capital (rounded half-up), the allowed participation is that cap total minus what it already received as `preference_paid_cents` (never below zero), and its `participation_paid_cents` is the lesser of its raw participation and that allowed amount. Every other participating class records its raw share as `participation_paid_cents`. Each class's `total_paid_cents` is its `preference_paid_cents` plus its `participation_paid_cents`. Any residual cents left by rounding across the per-class allocations are assigned to the most senior class so the distributed total is conserved. The per-class rows can be read back for an event, and waterfall distributions can be listed and filtered by `cap_table_id`, `liquidation_event_id`, or `security_class_id`.

## 4. Endpoint Definitions

Operations that create a new, distinct resource return a `201 Created` status code; operations that modify, transition, or read an existing resource return a `200 OK` status code. Every request must satisfy the authentication, authorization, and existence checks of §2 before any business rule is evaluated; the order in which the remaining validations fire is described alongside each workflow in §3. Request and response bodies are not repeated here — refer to the §3 narrative for the inputs each operation consumes and the side effects it triggers.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/cap-tables` | Create a cap table | Administrator |
| GET | `/cap-tables` | List cap tables | Administrator, BoardApprover, Auditor |
| GET | `/cap-tables/{id}` | Fetch a cap table with computed totals | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/cap-tables/{id}/lock` | Freeze new issuances and grants | BoardApprover |
| POST | `/cap-tables/{id}/unlock` | Re-open a locked table | BoardApprover |
| POST | `/cap-tables/{id}/dissolve` | Dissolve the cap table | BoardApprover |
| POST | `/security-classes` | Create a security class | Administrator |
| GET | `/security-classes` | List/filter security classes | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/security-classes/{id}` | Fetch a security class | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/shareholders` | Register a shareholder | Administrator |
| GET | `/shareholders` | List/filter shareholders | Administrator, BoardApprover, Auditor |
| GET | `/shareholders/{id}` | Fetch a shareholder | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/share-issuances` | Issue shares of a class to a shareholder | Administrator |
| GET | `/share-issuances` | List/filter issuances | Administrator, BoardApprover, Auditor |
| GET | `/share-issuances/{id}` | Fetch an issuance record | Administrator, BoardApprover, Auditor |
| POST | `/valuations` | Create a 409A valuation (DRAFT) | Administrator |
| GET | `/valuations` | List/filter valuations | Administrator, BoardApprover, Auditor |
| GET | `/valuations/{id}` | Fetch a valuation | Administrator, BoardApprover, Auditor |
| POST | `/valuations/{id}/approve` | Make a valuation effective; supersede the prior one | BoardApprover |
| POST | `/option-pools` | Create an option pool | Administrator |
| GET | `/option-pools` | List/filter pools | Administrator, BoardApprover, Auditor |
| GET | `/option-pools/{id}` | Fetch a pool with allocation totals | Administrator, BoardApprover, Auditor |
| POST | `/option-pools/{id}/refresh` | Retire a pool and open a topped-up replacement | BoardApprover |
| POST | `/option-grants` | Draft an option grant | Administrator |
| GET | `/option-grants` | List/filter grants | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/option-grants/{id}` | Fetch a grant with live vested shares | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/option-grants/{id}/approve` | Approve a grant (segregation of duties) | BoardApprover |
| POST | `/option-grants/{id}/cancel` | Cancel a grant; return shares to pool if active | Administrator |
| POST | `/option-grants/{id}/expire` | Expire a grant; return unexercised shares | Administrator |
| POST | `/exercises` | Exercise options on an active grant (PENDING) | Stakeholder, Administrator |
| GET | `/exercises` | List/filter exercises | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/exercises/{id}` | Fetch an exercise with computed spread | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/exercises/{id}/settle` | Settle an exercise; mint shares, compute spread | Administrator |
| POST | `/exercises/{id}/reverse` | Reverse an exercise; unwind share movement | Administrator |
| POST | `/exercises/{id}/form-3921` | Generate the Form 3921 for a settled exercise | Administrator |
| GET | `/forms-3921` | List/filter Form 3921 records | Administrator, Auditor |
| GET | `/forms-3921/{id}` | Fetch a generated Form 3921 | Administrator, Auditor, Stakeholder |
| POST | `/section-83b-elections` | File an 83(b) election against an early exercise | Stakeholder, Administrator |
| GET | `/section-83b-elections` | List/filter 83(b) elections | Administrator, Auditor, Stakeholder |
| GET | `/section-83b-elections/{id}` | Fetch an 83(b) election | Administrator, Auditor, Stakeholder |
| POST | `/section-83b-elections/{id}/process` | Adjudicate the 30-day window | Administrator |
| POST | `/safe-notes` | Draft a SAFE or convertible note | Administrator |
| GET | `/safe-notes` | List/filter notes | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/safe-notes/{id}` | Fetch a note | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/safe-notes/{id}/submit-terms` | Move a note into negotiation | Administrator |
| POST | `/safe-notes/{id}/revise` | Send a note back to draft | Administrator |
| POST | `/safe-notes/{id}/execute` | Bind a note as outstanding | BoardApprover |
| POST | `/safe-notes/{id}/convert` | Convert an outstanding note into a priced class | BoardApprover |
| POST | `/safe-notes/{id}/repay` | Repay an outstanding note | BoardApprover |
| POST | `/liquidation-events` | Create a liquidation event (DRAFT) | Administrator |
| GET | `/liquidation-events` | List/filter liquidation events | Administrator, BoardApprover, Auditor |
| GET | `/liquidation-events/{id}` | Fetch a liquidation event | Administrator, BoardApprover, Auditor |
| POST | `/liquidation-events/{id}/compute` | Run the liquidation-preference waterfall | BoardApprover |
| POST | `/liquidation-events/{id}/recompute` | Clear allocations and revert to draft | BoardApprover |
| POST | `/liquidation-events/{id}/finalize` | Lock the computed allocations | BoardApprover |
| GET | `/liquidation-events/{id}/distributions` | List per-class waterfall allocations for an event | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/waterfall-distributions` | List/filter waterfall distributions | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/waterfall-distributions/{id}` | Fetch a single waterfall distribution row | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/blackout-windows` | Schedule an insider-trading blackout window | Administrator |
| GET | `/blackout-windows` | List/filter blackout windows | Administrator, BoardApprover, Auditor, Stakeholder |
| GET | `/blackout-windows/{id}` | Fetch a blackout window | Administrator, BoardApprover, Auditor, Stakeholder |
| POST | `/blackout-windows/{id}/lift` | Lift a scheduled blackout window | Administrator |
| POST | `/_clock/set_current_utc` | Set the server clock for temporal tests | Administrator |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TABLE_NOT_OPEN` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_409A_NONCOMPLIANT` | 422 Unprocessable Entity |
| `ERR_VALUATION_EXPIRED` | 422 Unprocessable Entity |
| `ERR_WRONG_CLASS_TYPE` | 422 Unprocessable Entity |
| `ERR_SENIORITY_CYCLE` | 422 Unprocessable Entity |
| `ERR_83B_WINDOW_MISSED` | 422 Unprocessable Entity |
| `ERR_EXCEEDS_EXERCISABLE` | 422 Unprocessable Entity |
| `ERR_POOL_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_AUTHORIZED_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_GRANT_HAS_EXERCISES` | 409 Conflict |
| `ERR_ELECTION_BLOCKS_REVERSE` | 409 Conflict |
| `ERR_VALUATION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BLACKOUT_OVERLAP` | 409 Conflict |

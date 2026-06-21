# Pallet Pooling API — Product Requirements Document

## 1. Introduction

Returnable transport assets — pooled pallets, crates, and containers in the spirit of a CHEP-style program — circulate continuously between a pooling operator and its supply-chain participants. The same physical asset is issued to a manufacturer, shipped onward to a distributor, returned, repaired, and re-issued, and at every leg of that journey someone is accountable for it. This API is the system of record for that accountability. It tracks the chain of custody of every pooled asset, the per-location balance of physical units actually present versus the equity each site is obligated to return to the pool, the daily hire charge a participant accrues while assets sit on rental, and the financial reconciliation that follows loss, exchange, repair, and invoicing.

The platform serves three constituencies with overlapping but distinct concerns. The pooling operator's staff and administrators provision the program, mint assets, run physical audits, settle losses, and bill participants. Supply-chain participants — manufacturers, distributors, and retailers — open and close hires, move assets between sites, exchange equity obligations through vouchers, and forecast their own demand. Because money and physical custody are both at stake, the system holds two invariants above all others: equity must be conserved as it moves between locations, and every charge — provisional or finalized — must be reproducible from the underlying events. The remainder of this document specifies the global contract every endpoint honors, then the business logic that governs each asset's lifecycle from minting through final settlement.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. A request missing or malforming either header is rejected with `ERR_MISSING_AUTH`. When a well-authenticated caller attempts an operation their role is not permitted to perform, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly three roles: `PoolAdmin`, `PoolOperator`, and `Participant`. A `PoolAdmin` is the pooling-operator superuser, responsible for program and policy setup, asset-type and account lifecycle, all void/cancel/suspend/close overrides, and advancing the logical clock; the `PoolAdmin` capability set is a superset of `PoolOperator`. A `PoolOperator` is pooling-operator staff handling day-to-day logistics — hires, audits, vouchers, collections, repairs, and billing — but cannot void, suspend, close, cancel, or set the clock. A `Participant` is a supply-chain participant (a manufacturer, distributor, or retailer) who opens and closes hires, dispatches and receives transfers, issues and redeems vouchers, reports asset damage, and runs demand forecasts; a `Participant` may not mint assets, run audits, request collections, open repairs, or bill.

When `X-User-Role` is `PoolAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`. The same holds when `X-User-Role` is `PoolOperator`: `X-User-ID` is an opaque operator identifier, recorded if useful but never matched against an entity's `id`. When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the acting `Account`; ownership checks on any resource that references an `Account` compare the resource's account foreign key to `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and a supplied value must be at least 1 and at most 100. The `offset` parameter is the number of leading items to skip and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp in ascending order.

Each list response carries the pagination bookkeeping in the envelope's `meta` object, namely `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every top-level resource the system persists carries a system-managed `id`, a string formatted as a UUID with no type prefix. Each such resource also records a `created_at` timestamp — an ISO 8601 UTC instant with three fractional digits, fixed at creation. Mutable resources additionally carry an `updated_at` timestamp, refreshed on every change, and a `version`, an integer that starts at the resource's creation and increments by one on every mutation. In this domain every entity is mutable and therefore carries both `updated_at` and `version`; there are no creation-only resources that omit those two fields.

All time-dependent behavior — hire accrual, voucher expiry, audit windows, depreciation, and demand lookbacks — reads a single server-wide **logical clock** rather than wall-clock time. On startup the logical clock reads exactly `2026-01-01T00:00:00Z`, and until a `PoolAdmin` advances it the clock holds that default and never falls back to wall-clock. The administrative clock-setting capability accepts a `to_iso8601` instant and moves the logical clock to that value; thereafter every accrual, expiry, window, and forecast computation reads the current logical clock.

### 2.5. Equity, Physical Balance, and Conservation

Each `Location` tracks two distinct counts that the system recomputes from underlying movements rather than storing as free-standing inputs. The `physical_balance` is the count of assets whose `current_location_id` equals the location and whose `condition` is anything other than `LOST`; it is recomputed on every movement, hire, and audit side effect and whenever the location is read. The `equity_balance` is the net quantity of assets the location is accountable to return to the pool: assets issued in, minus assets returned out, minus voucher-transferred equity that left the site, plus declared losses. Equity may be negative, which means the pool owes the location.

A location's `equity_status` is derived from its `equity_balance` against the program threshold. The location is `SHORT` when its `equity_balance` is at or above the policy's `equity_warn_threshold`; it is `SURPLUS` when its `equity_balance` is strictly less than zero; otherwise it is `BALANCED`. The `equity_status` is recomputed whenever the location is read and after any equity-touching side effect.

Equity is conserved across the system. Issuance creates equity at the destination; return relieves equity at the origin; a participant-to-participant transfer moves equity from origin to destination so that the total is unchanged. The voucher mechanism likewise conserves equity across its issue-and-redeem pair, and an expired or cancelled voucher snaps the obligation back to its issuer. The specific debits and credits behind each of these movements are detailed in §3.

### 2.6. Hierarchical Consistency and Cascading Side Effects

All balance, equity, and charge mutations are immediate and atomic: every consequence of a triggering request lands within that same request, never deferred. When an operation touches more than one entity, every downstream effect is part of the same atomic write, and each mutated resource has its `updated_at` refreshed and its `version` incremented.

The most far-reaching cascade is audit finalization, which fans out across an asset, a location, and any stale vouchers in a single transaction; the second is invoice issue and payment, which advance the settlement standing of every hire the invoice references. These cascades are specified in full within the workflow narratives of §3. The governing rule here is only that they are atomic and that each touched resource's `updated_at` and `version` move together with the change.

### 2.7. Nested Resource Retrieval and Existence Ordering

Resources in this system are peers linked by foreign keys rather than deeply nested under one another, but several paths still address a child through its parent — for example an invoice's lines. For any request, the system validates resource identifiers left to right: every identifier in the path is checked first, in path order, and then any foreign-key identifiers in the request body. The first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any later identifier or business rule is evaluated.

### 2.8. Monetary Precision

Every monetary field in the system is stored and returned as an integer number of cents, denominated in the policy's `currency`. There are no fractional-cent amounts anywhere in a response. Where a calculation divides or applies a discount factor, the rounding direction is pinned per calculation and stated with that calculation in §3 — daily hire rates and per-victim depreciated values are floored, day counts are whole, and invoice totals sum already-rounded per-line integers rather than rounding a running sum. No monetary value is ever computed by summing fractional intermediates and rounding once at the end.

### 2.9. Optimistic Concurrency Control on Location

Two write operations gate themselves against a stale view of a `Location` using optimistic concurrency control. In each case the client must supply the `version` of the location it last observed, and the write is rejected if that version no longer matches the location's current `version`.

Opening a hire is the first such operation. A hire-open request must carry `expected_location_version` equal to the current `version` of the hire's target `Location`. A hire legitimately supersedes the location's prior equity and occupancy view — another writer may have opened a hire, dispatched a transfer, or finalized an audit on the same location since the client last read it — so if `expected_location_version` does not match the location's current `version`, the open is rejected with `ERR_STALE_VERSION` (HTTP 412). Issuing a voucher is the second. A voucher-issue request must carry `expected_from_location_version` equal to the current `version` of the `from_location_id` whose equity the voucher surrenders; because the issue debits that location's equity and thus supersedes its prior equity view, a mismatch with the location's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint takes a version field. Endpoints that are not hire-open or voucher-issue perform no OCC check.

### 2.10. Validation Ordering

When several checks could reject the same request, the system evaluates them in a fixed priority order so that the returned `error_id` is deterministic. Authentication of the headers comes first (`ERR_MISSING_AUTH`), then role authorization (`ERR_FORBIDDEN_FOR_ROLE`), then existence of every referenced resource validated left-to-right through the path and then the body foreign keys (`ERR_NOT_FOUND`), then request-body well-formedness — required fields present, types valid, enum values in range, and quantities or amounts meeting their declared minimums (`ERR_INVALID_REQUEST`). Only after those four gates does the system evaluate the optimistic-concurrency version check for hire-open and voucher-issue (`ERR_STALE_VERSION`), then the target resource's state eligibility for the requested transition (`ERR_INVALID_STATE`), and finally the domain-specific business preconditions described throughout §3. Where §3 describes several business preconditions on one endpoint, the order in which those domain checks fire is given in the relevant workflow narrative.

Regarding well-formedness specifically: the `asset_ids` list must be non-empty when opening a hire, requesting a collection, or opening a repair job; an empty `asset_ids` is rejected there with `ERR_INVALID_REQUEST`. A transfer order, by contrast, may be created with an empty `asset_ids` to record a zero-asset administrative move.

## 3. Business Logic & Workflows

### 3.1. Program Setup: Policy, Asset Types, Accounts, and Locations

The pooling program begins with a single **pool policy**, created by a `PoolAdmin` with a program `name` and an optional `currency` (defaulting to `USD`). The policy also fixes three program-wide governance constants, each with a default that applies when the field is omitted: `equity_warn_threshold` (default 200), the per-location net equity owed at or above which a location is flagged `SHORT`; `voucher_expiry_days` (default 90), the number of days from a voucher's issue after which an outstanding voucher auto-expires during an audit-finalize sweep; and `audit_min_interval_days` (default 28), the minimum number of days that must separate the end of one finalized audit window and the start of the next for the same location. A policy is created in `ACTIVE` `status`, and only one `ACTIVE` pool policy may exist at a time; attempting to create a second `ACTIVE` policy is rejected with `ERR_DUPLICATE_RESOURCE`. A policy may move to `RETIRED`.

A `PoolAdmin` defines each **asset type** with a `code`, a human label `name`, a `base_daily_rate_cents` (the base per-asset per-day hire rate before any tiered volume discount, which must be zero or greater), a `replacement_cost_cents` (the full replacement cost charged on a declared loss, zero or greater), and an optional `useful_life_days` (the straight-line depreciation horizon, defaulting to 1825 days and required to be at least 1). The `code` must be unique across all asset types regardless of `status`; a duplicate `code` is rejected with `ERR_DUPLICATE_RESOURCE`. An asset type is created `ACTIVE` and may be discontinued, moving its `status` to `DISCONTINUED`. Once discontinued, no new asset may be minted of that type; an attempt is rejected with `ERR_ASSET_TYPE_DISCONTINUED`.

A `PoolAdmin` registers each **account** with a `legal_name`, a `role_type` (one of `MANUFACTURER`, `DISTRIBUTOR`, or `RETAILER`), and a `credit_limit_cents` (the maximum unbilled-plus-outstanding charge exposure permitted before new hires are blocked, zero or greater). A new account starts `ACTIVE` with `outstanding_charge_cents` of 0. The account lifecycle is administrator-driven: an `ACTIVE` account may be suspended to `SUSPENDED` and a `SUSPENDED` account reactivated back to `ACTIVE`. While an account is `SUSPENDED`, no new hire may open for it. An `ACTIVE` account may be closed to `CLOSED`, but only when it has no hire whose `lifecycle_status` is `OPEN` (otherwise `ERR_ACCOUNT_HAS_OPEN_HIRE`) and its `outstanding_charge_cents` is exactly 0 (otherwise `ERR_ACCOUNT_NOT_SETTLED`); `CLOSED` is terminal.

Each **location** is created under an owning account by supplying its `account_id` and a site `name`; a `PoolAdmin` or `PoolOperator` may create one. It opens with `status` `OPEN` and both `physical_balance` and `equity_balance` at 0. Locations can be listed and filtered by `account_id`. A location may be closed only when both its `physical_balance` and its `equity_balance` equal 0; if either is non-zero the close is rejected with `ERR_INVALID_STATE`, and an accepted close moves `status` to `CLOSED`. Reading a location recomputes its `physical_balance` and `equity_status` before the response is returned.

### 3.2. Minting Assets and the Custody Lifecycle

A pooled **asset** is minted by a `PoolAdmin` or `PoolOperator` with an `asset_type_id`, a `serial` that must be unique within that asset type (a collision yields `ERR_DUPLICATE_RESOURCE`), an `in_service_at` datetime marking the date it entered the pool (the depreciation clock origin used by the net-book-value loss basis), and a `current_location_id` at which it first lands. A minted asset begins in `condition` `AVAILABLE`; minting increments the holding location's `physical_balance`. An asset minted against a `DISCONTINUED` asset type is refused with `ERR_ASSET_TYPE_DISCONTINUED`. Each asset also carries a `current_hire_id`, which is null while the asset is off-hire and points to the occupying hire while the asset is on rental. Assets can be listed and filtered by `asset_type_id`, `current_location_id`, `current_hire_id`, and `condition`.

An asset's `condition` moves through a cyclic state machine spanning `AVAILABLE`, `ON_HIRE`, `IN_TRANSIT`, `DAMAGED`, `IN_REPAIR`, and `LOST`. Placing an asset on a hire takes it `AVAILABLE → ON_HIRE`; closing that hire returns it `ON_HIRE → AVAILABLE`. Dispatching a transfer takes an `AVAILABLE` asset to `IN_TRANSIT`, and receiving that transfer brings it `IN_TRANSIT → AVAILABLE` at the destination. Reporting damage takes an asset to `DAMAGED` — from `ON_HIRE` or from `AVAILABLE`; when the damaged asset was on an `OPEN` hire, it is removed from that hire's occupancy and its `current_hire_id` is cleared to null. A `DAMAGED` asset enters `IN_REPAIR` when a repair job opens over it, and from `IN_REPAIR` it either returns `AVAILABLE` on repair completion or goes to `LOST` on scrap. An asset also reaches `LOST` directly from `AVAILABLE` when it is selected as a loss victim during audit finalization. While an asset is `IN_TRANSIT` or `LOST` its `current_location_id` is null.

Reporting damage is available to a `PoolAdmin`, `PoolOperator`, or `Participant` and simply records the `DAMAGED` `condition`, with the hire-occupancy removal noted above when the asset was on an open hire.

### 3.3. Chain of Custody: Transfer Orders

Asset movement between sites is recorded as a **transfer order**, the chain-of-custody manifest. A `PoolAdmin`, `PoolOperator`, or `Participant` drafts one by giving a `from_location_id` (the origin), a `to_location_id` (the destination), a `kind`, and `asset_ids` — the ordered manifest of `Asset.id` values being moved. The order also exposes a `quantity`, which is the manifest size, and the timestamps `dispatched_at` and `received_at`, both null until the corresponding step occurs. A draft order's `status` is `DRAFT`. Orders can be listed and filtered by `from_location_id`, `to_location_id`, and `status`.

The `kind` selects which equity movement the order performs on receipt and must be one of three values. An `ISSUANCE` moves assets from operator stock to a participant and creates equity at the destination. A `RETURN` moves assets from a participant back to operator stock and relieves equity at the origin. A `TRANSFER` moves assets participant-to-participant, with equity following the assets.

Dispatching a draft order advances it `DRAFT → DISPATCHED`. Dispatch requires that the origin location's `status` be `OPEN` (otherwise `ERR_LOCATION_CLOSED`) and that every asset in the manifest have `condition` `AVAILABLE` and a `current_location_id` equal to the `from_location_id` — an asset that is not `AVAILABLE` is rejected with `ERR_ASSET_NOT_AVAILABLE`, and one sitting elsewhere with `ERR_ASSET_WRONG_LOCATION`. On dispatch, each manifest asset becomes `IN_TRANSIT` with its `current_location_id` cleared to null, the origin's `physical_balance` drops by the manifest `quantity`, and `dispatched_at` is set to the current logical clock.

Receiving a dispatched order advances it `DISPATCHED → RECEIVED` and requires the destination location's `status` to be `OPEN` (otherwise `ERR_LOCATION_CLOSED`). On receipt, every manifest asset becomes `AVAILABLE` with its `current_location_id` set to the `to_location_id`, the destination's `physical_balance` rises by the manifest `quantity`, `received_at` is set to the current logical clock, and the equity movement keyed by `kind` is applied: for an `ISSUANCE` the destination's `equity_balance` increases by `quantity`; for a `RETURN` the origin's `equity_balance` decreases by `quantity`; for a `TRANSFER` the origin's `equity_balance` decreases by `quantity` and the destination's increases by `quantity`. The `equity_status` of every location touched by the receipt is recomputed. A draft order may instead be cancelled, moving `status` to `CANCELLED`; `RECEIVED` and `CANCELLED` are both terminal.

### 3.4. Hiring Assets and Accruing the Daily Charge

A **hire** places a set of assets on rental for a participant. It is opened with an `account_id` (the hiring participant, billed for the daily charge), a `location_id` (the site the hired assets sit at while on rental), an `asset_type_id` (all assets on one hire share a single type), the `asset_ids` to place on hire, and the `expected_location_version` described in §2.9. Every listed asset must be `AVAILABLE` (otherwise `ERR_ASSET_NOT_AVAILABLE`) and physically at the hire's `location_id` (otherwise `ERR_ASSET_WRONG_LOCATION`), and the hiring account must be `ACTIVE` — a `SUSPENDED` or `CLOSED` account is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. A hire opens with `lifecycle_status` `OPEN` and `settlement_status` `UNBILLED`; its `on_hire_at` is stamped to the current logical clock, each listed asset transitions `AVAILABLE → ON_HIRE` with its `current_hire_id` set to the new hire, the target `Location.version` is incremented by one, and the account's `outstanding_charge_cents` is recomputed. Hires can be listed and filtered by `account_id`, `location_id`, `asset_type_id`, `lifecycle_status`, and `settlement_status`.

These two status dimensions evolve independently. The `lifecycle_status` runs `OPEN → CLOSED` or `OPEN → VOIDED`; the `settlement_status` runs `UNBILLED → INVOICED → SETTLED`. A `CLOSED` hire remains `UNBILLED` until it is invoiced, and an `OPEN` hire can never be `INVOICED` — invoicing requires the hire to be `CLOSED` first.

While a hire is `OPEN` it carries a provisional, forward-looking accrual in `accrued_charge_cents`, recomputed when the hire is read and when the owning account's outstanding charge is recomputed. The accrual is the number of whole elapsed days from `on_hire_at` to the current logical clock, multiplied by the count of assets still `ON_HIRE` on this hire, multiplied by the effective tiered daily rate for that count. The elapsed day count is the difference between the current clock and `on_hire_at` measured in whole days (one day being 86400 seconds), floored, and never less than zero. The effective tiered rate is derived from the asset type's `base_daily_rate_cents` by the tiering rule given below. This provisional figure deliberately uses the current surviving on-hire asset count for the whole span and ignores any mid-hire damage history, so it is an estimate that can exceed the chronological finalized figure. The day-count flooring and the rate flooring both apply, and the result is integer cents.

The **tiered daily rate** for an asset count is computed from the base rate as follows. When the count is at least 50, the rate is the base rate multiplied by 0.80, floored to whole cents — the deepest discount. When the count is at least 10 but fewer than 50, the rate is the base rate multiplied by 0.90, floored to whole cents. When the count is fewer than 10, the rate is the base rate itself. The rate is floored once per tier; the per-day charge is that floored rate multiplied by the active asset count, not re-floored afterward.

Closing a hire advances its `lifecycle_status` `OPEN → CLOSED` and is permitted only from `OPEN` (otherwise `ERR_INVALID_STATE`). Close stamps `off_hire_at` to the current logical clock, pins `final_charge_cents` by the chronological replay described next, returns every asset still `ON_HIRE` on the hire to `AVAILABLE` with `current_hire_id` cleared to null, and recomputes the account's `outstanding_charge_cents` so that this hire now contributes its finalized unpaid charge rather than a provisional accrual. The location's `physical_balance` and equity are unaffected by close, since the assets were already at the location.

The **finalized hire charge** pinned at close is a chronological event replay over the half-open day interval from `on_hire_at` inclusive to `off_hire_at` exclusive. For each whole day in that interval, the system counts the assets still `ON_HIRE` (those not yet damaged as of that day), derives the tiered daily rate for that day's active count using the same tiering rule and the asset type's `base_daily_rate_cents`, and adds that day's active count multiplied by its tiered rate to the running total. A damaged asset stops accruing from its damage day onward (the damage day itself is excluded from its accrual). The pinned `final_charge_cents` is the sum across all days; the day count is whole half-open days and the tiered rate is floored once per tier. Because the replay honors each asset's actual damage day rather than the surviving count, a hire whose assets were damaged mid-term yields a smaller finalized total than its provisional accrual.

A hire may instead be voided by a `PoolAdmin`, but only while its `settlement_status` is `UNBILLED` (otherwise `ERR_HIRE_ALREADY_INVOICED`). Voiding advances `lifecycle_status` `OPEN → VOIDED`, returns every `ON_HIRE` asset to `AVAILABLE` with `current_hire_id` cleared, sets both `accrued_charge_cents` and `final_charge_cents` to 0 as a compensating reversal of the charge, and recomputes the account's `outstanding_charge_cents`. `CLOSED` and `VOIDED` are terminal lifecycle states.

A hire may be opened by a `PoolAdmin`, `PoolOperator`, or `Participant`; opening and closing are shared across those roles, while voiding is exclusive to `PoolAdmin`.

### 3.5. Credit Exposure and the Account's Outstanding Charge

An account's `outstanding_charge_cents` is the live measure of its credit exposure and is recomputed on every hire open, close, and void and on every invoice issue, payment, and void, as well as whenever the account is read. It is the sum of two parts: the provisional `accrued_charge_cents` of every hire belonging to the account whose `lifecycle_status` is `OPEN`, plus, for every invoice belonging to the account whose `status` is `ISSUED`, that invoice's `total_cents` minus its `paid_cents`. In other words it blends provisional open-hire accrual with the unpaid balance of issued invoices into one exposure figure.

That exposure gates new hires against the account's `credit_limit_cents`. Opening a hire must not push exposure strictly above the limit. The exposure considered at open is the account's `outstanding_charge_cents` before the open, plus a single day-one reservation for the new hire. That reservation is one day, multiplied by the number of assets in the new hire's `asset_ids`, multiplied by the tiered daily rate for that same count (computed from the asset type's `base_daily_rate_cents` by the tiering rule in §3.4). The open is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` only when this exposure is strictly greater than `credit_limit_cents`; an exposure exactly equal to `credit_limit_cents` is allowed.

### 3.6. Audit Reconciliation and Loss Declaration

Physical counts are recorded as an **audit reconciliation** over a closed time window. A `PoolAdmin` or `PoolOperator` drafts one for a `location_id` with a `window_start`, a `window_end` (which must be on or after `window_start`), a `counted_physical` (the physically counted asset quantity, which may be 0 and must be zero or greater), and an optional `loss_basis` (defaulting to `REPLACEMENT`). It is created in `status` `DRAFT`. The two computed outputs, `declared_loss_qty` and `declared_loss_cents`, both stay 0 until finalization. Audits can be listed and filtered by `location_id` and `status`.

Finalizing an audit advances it `DRAFT → FINALIZED` and is performed by a `PoolAdmin` or `PoolOperator`. Two preconditions guard finalize, evaluated in this order: first the audited location's `status` must be `OPEN` (otherwise `ERR_LOCATION_CLOSED`); then no other `FINALIZED` audit for the same location may have a window that overlaps this window, nor may any prior finalized window sit closer than `audit_min_interval_days` to this one — that is, the gap between this window's start and a prior finalized window's end (and vice versa) must respect the policy's `audit_min_interval_days` adjacency buffer, otherwise the finalize is rejected with `ERR_AUDIT_WINDOW_OVERLAP`.

Finalization then performs an atomic cascade. First it sets `declared_loss_qty` to the location's `equity_balance` minus `counted_physical`, floored at 0 — that is, the shortfall, or 0 when the count meets or exceeds expected equity. Next it values that shortfall into `declared_loss_cents` under the chosen `loss_basis` (detailed below). It then selects exactly `declared_loss_qty` loss victims from the `AVAILABLE` assets at the location, ordered by `in_service_at` ascending and then `created_at` ascending — oldest in service first — and marks each victim's `condition` `AVAILABLE → LOST` with its `current_location_id` cleared to null. The loss declaration does not change the location's `equity_balance`: a loss converts owed equity into a billable charge rather than relieving it, so equity is unchanged while `physical_balance` drops as the victims leave. As a parallel sweep, every `OUTSTANDING` voucher issued from this location whose `issued_at` plus the policy's `voucher_expiry_days` is on or before this audit's `window_end` is auto-expired to `EXPIRED` (with the equity restoration described in §3.7). Finally the location's `physical_balance` and `equity_status` are recomputed. A draft audit may instead be voided by a `PoolAdmin`, moving `status` to `VOIDED`; `FINALIZED` and `VOIDED` are terminal.

The **loss valuation** depends on `loss_basis`. Under `REPLACEMENT`, `declared_loss_cents` is `declared_loss_qty` multiplied by the asset type's `replacement_cost_cents`, ignoring asset age. Under `NET_BOOK`, the value is computed per victim and summed (not averaged): for each victim, the age in whole days is the difference between `window_end` and the victim's `in_service_at` measured in whole days (one day being 86400 seconds), floored; the remaining life is the asset type's `useful_life_days` minus that age, floored at 0; the victim's net book value is the asset type's `replacement_cost_cents` multiplied by remaining life divided by `useful_life_days`, floored to whole cents; and `declared_loss_cents` is the sum of those per-victim net book values. Each victim's value is floored before summing. Because an older asset depreciates lower, the same shortfall quantity yields a smaller `declared_loss_cents` under `NET_BOOK` than under `REPLACEMENT`.

### 3.7. Exchange via Vouchers

When a location settles an equity obligation without a physical exchange, it issues a **voucher**. A `PoolAdmin`, `PoolOperator`, or `Participant` issues one with a `from_location_id` (the location surrendering the equity obligation), a `to_account_id` (the account that will assume the obligation on redemption), an `asset_type_id`, a `quantity` of asset-equivalent equity units (which must be at least 1), and the `expected_from_location_version` described in §2.9. On issue the voucher's `status` is `OUTSTANDING`, `issued_at` is stamped to the current logical clock (the expiry-clock origin), the `from_location_id`'s `equity_balance` is reduced by `quantity`, that location's `version` is incremented by one, and its `equity_status` is recomputed. A voucher also carries a `redeem_location_id`, null until redemption sets it. Vouchers can be listed and filtered by `from_location_id`, `to_account_id`, `asset_type_id`, `redeem_location_id`, and `status`.

Redeeming a voucher advances it `OUTSTANDING → REDEEMED` and is performed by a `PoolAdmin`, `PoolOperator`, or `Participant`, who supplies the `redeem_location_id` at which the equity will land. Three preconditions guard redeem: the `to_account_id`'s account must be `ACTIVE` (otherwise `ERR_ACCOUNT_NOT_ACTIVE`); the supplied `redeem_location_id` must belong to the `to_account_id` and have `status` `OPEN` — a location that does not belong to that account is rejected with `ERR_VOUCHER_REDEEM_LOCATION_INVALID`, and a closed one with `ERR_LOCATION_CLOSED`; and the voucher must not be past expiry, meaning `issued_at` plus the policy's `voucher_expiry_days` must be strictly after the current logical clock (otherwise `ERR_VOUCHER_EXPIRED`). On redemption the redeem location's `equity_balance` increases by `quantity` (the redeemer assumes the obligation) and its `equity_status` is recomputed. Issue and redeem form a conserving pair: the `quantity` debited from the issuing location on issue is the same `quantity` credited to the redeeming location on redeem, so total system equity is unchanged.

A voucher leaves `OUTSTANDING` in two other ways, both of which restore the obligation to the issuer. The audit-finalize sweep of §3.6 expires an outstanding voucher to `EXPIRED` when its `issued_at` plus `voucher_expiry_days` is on or before the finalizing audit's `window_end`; expiry adds `quantity` back to the `from_location_id`'s `equity_balance` and recomputes that location's `equity_status`. A `PoolAdmin` may also cancel an outstanding voucher to `CANCELLED`, which likewise adds `quantity` back to the issuer's `equity_balance` and recomputes its `equity_status`. `REDEEMED`, `EXPIRED`, and `CANCELLED` are terminal.

### 3.8. Collection and Repair

Idle or damaged assets are recovered from a site through a **collection request**. A `PoolAdmin` or `PoolOperator` raises one with a `location_id` and the `asset_ids` to collect; each listed asset must currently sit at the `location_id` and be in `condition` `AVAILABLE` or `DAMAGED`. A new request is in `status` `REQUESTED`. Collection requests can be listed and filtered by `location_id` and `status`.

Collecting a request advances it `REQUESTED → COLLECTED`, requiring that every asset in `asset_ids` have a `current_location_id` equal to the request's `location_id` (otherwise `ERR_ASSET_WRONG_LOCATION`). On collection each asset leaves the location: an `AVAILABLE` asset becomes `IN_TRANSIT` with its `current_location_id` cleared to null, while a `DAMAGED` asset retains its `DAMAGED` condition but has its location cleared; the location's `physical_balance` is decremented accordingly. A collected request may then be closed to `CLOSED`, and a still-requested one cancelled to `CANCELLED`; `CLOSED` and `CANCELLED` are terminal.

Damaged assets feed a **repair job**, opened by a `PoolAdmin` or `PoolOperator` with a `collection_request_id` (the source collection that fed the damaged assets), the `asset_ids` under repair, and a `repair_cost_cents` (the total repair cost recorded at completion, zero or greater). Each listed asset must be `DAMAGED` at job creation (otherwise `ERR_ASSET_NOT_DAMAGED`), and opening the job moves each asset `DAMAGED → IN_REPAIR`. A new job is in `status` `OPEN`. Repair jobs can be listed and filtered by `collection_request_id` and `status`. Completing a repair advances it `OPEN → COMPLETED`, returning each asset `IN_REPAIR → AVAILABLE` at the source collection request's origin location (the repair depot) and incrementing that location's `physical_balance`. Scrapping a repair advances it `OPEN → SCRAPPED`, marking each asset `IN_REPAIR → LOST` for permanent removal from `physical_balance`. `COMPLETED` and `SCRAPPED` are terminal.

### 3.9. Billing: Invoices, Lines, and Settlement

Charges are billed through an **invoice**. A `PoolAdmin` or `PoolOperator` opens a draft invoice for an `account_id`; it starts in `status` `DRAFT` with `subtotal_cents`, `credit_cents`, `total_cents`, and `paid_cents` all 0. Invoices can be listed and filtered by `account_id` and `status`.

While the invoice is in draft, operators attach **invoice lines**. Each line is created with an `invoice_id` (its parent invoice), a `kind`, and an `amount_cents` (the per-line amount as a positive magnitude, already rounded to whole cents at line creation, zero or greater). The `kind` is one of four: `HIRE` for a finalized hire charge, `LOSS` for a declared-loss charge, `REPAIR` for a repair recovery, or `CREDIT` for a voucher or early-return credit whose magnitude is stored as a positive number. A line may carry a source pointer matching its kind: `source_hire_id` is populated when the kind is `HIRE`, `source_audit_id` when the kind is `LOSS`, and `source_voucher_id` when the kind is `CREDIT` and the credit originates from a voucher. An invoice's lines can be listed under the invoice, an individual line fetched on its own, and lines listed and filtered by `invoice_id`, `source_hire_id`, `source_audit_id`, and `source_voucher_id`.

Issuing an invoice advances it `DRAFT → ISSUED` and is restricted to a `PoolAdmin` or `PoolOperator`. Issue requires the invoice to have at least one line (otherwise `ERR_INVOICE_EMPTY`) and requires that every `HIRE` line's source hire be in `lifecycle_status` `CLOSED` (otherwise `ERR_HIRE_NOT_CLOSED`). On issue the invoice's totals are pinned: `subtotal_cents` is the sum of the `amount_cents` of all lines whose kind is `HIRE`, `LOSS`, or `REPAIR`; `credit_cents` is the sum of the `amount_cents` of all `CREDIT` lines (their positive magnitudes); and `total_cents` is `subtotal_cents` minus `credit_cents`, floored at 0. These totals are produced by summing the already-rounded per-line integers, never by rounding a running fractional sum. Issue also advances each referenced hire's `settlement_status` from `UNBILLED` to `INVOICED` and recomputes the account's `outstanding_charge_cents`.

Recording a payment against an issued invoice adds the request's `amount_cents` to the invoice's `paid_cents`; the supplied amount must be greater than 0 (otherwise `ERR_INVALID_REQUEST`). When cumulative `paid_cents` reaches or exceeds `total_cents`, the invoice advances `ISSUED → PAID`, every referenced hire's `settlement_status` moves from `INVOICED` to `SETTLED`, and the account's `outstanding_charge_cents` is recomputed. A draft invoice may instead be voided by a `PoolAdmin`, moving `status` to `VOID`; `PAID` and `VOID` are terminal. The settlement dimension of a hire is thus driven entirely by its invoice: a `CLOSED` hire becomes `INVOICED` when an invoice referencing it is issued and `SETTLED` when that invoice is fully paid, while its `lifecycle_status` stays `CLOSED` throughout.

### 3.10. Demand Forecasting

A **demand forecast** is a single-shot computed snapshot any role may request — `PoolAdmin`, `PoolOperator`, or `Participant`. It is computed for a `location_id`, an `asset_type_id`, and a forward `horizon_days` (at least 1), and is returned in `status` `COMPUTED`. Forecasts can be listed and filtered by `location_id` and `asset_type_id`.

The snapshot blends two demand signals over a fixed 30-day lookback and scales the blend to the requested horizon. The first signal, issuance velocity, is the total `quantity` across all `RECEIVED` transfer orders of `kind` `ISSUANCE` directed to this location within the last 30 days, divided by 30 to give a per-day rate. The second signal, open-hire run-rate, is the count of assets currently `ON_HIRE` at this location for this asset type, taken as a snapshot level. The blended per-day figure weights issuance velocity at 0.70 and weights the open-hire run-rate divided by 30 at 0.30 (the two weights sum to 1.0). The `projected_demand` is that blended per-day figure multiplied by `horizon_days`, rounded up to a whole number of assets. The `recommended_reposition` is the `projected_demand` minus the location's `physical_balance` at compute time, floored at 0 — the number of assets to move into the location to meet projected demand.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource (for example a hire, a transfer order, or an invoice line) return a `201 Created` status code. Operations that modify an existing resource, including state-transition actions and the logical-clock and forecast computations, return a `200 OK` status code, except for the demand-forecast computation, which mints a new snapshot resource and returns `201 Created`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PoolAdmin |
| POST | `/pool-policies` | Create the pooling program policy | PoolAdmin |
| GET | `/pool-policies/{poolPolicyId}` | Get a pool policy | PoolAdmin, PoolOperator, Participant |
| POST | `/asset-types` | Create an asset type | PoolAdmin |
| GET | `/asset-types/{assetTypeId}` | Get an asset type | PoolAdmin, PoolOperator, Participant |
| POST | `/asset-types/{assetTypeId}/discontinue` | Discontinue an asset type | PoolAdmin |
| POST | `/accounts` | Create a participant account | PoolAdmin |
| GET | `/accounts/{accountId}` | Get an account (recomputes outstanding charge) | PoolAdmin, PoolOperator, Participant |
| POST | `/accounts/{accountId}/suspend` | Suspend an account | PoolAdmin |
| POST | `/accounts/{accountId}/reactivate` | Reactivate a suspended account | PoolAdmin |
| POST | `/accounts/{accountId}/close` | Close an account | PoolAdmin |
| POST | `/locations` | Create a location under an account | PoolAdmin, PoolOperator |
| GET | `/locations/{locationId}` | Get a location (recomputes balances/equity status) | PoolAdmin, PoolOperator, Participant |
| GET | `/locations` | List locations, filterable by account | PoolAdmin, PoolOperator, Participant |
| POST | `/locations/{locationId}/close` | Close a location (requires zero balances) | PoolAdmin, PoolOperator |
| POST | `/assets` | Mint a pooled asset | PoolAdmin, PoolOperator |
| GET | `/assets/{assetId}` | Get an asset | PoolAdmin, PoolOperator, Participant |
| GET | `/assets` | List assets, filterable by type/location/hire/condition | PoolAdmin, PoolOperator, Participant |
| POST | `/assets/{assetId}/report-damage` | Report an asset as damaged | PoolAdmin, PoolOperator, Participant |
| POST | `/transfer-orders` | Create a transfer order manifest | PoolAdmin, PoolOperator, Participant |
| GET | `/transfer-orders/{transferOrderId}` | Get a transfer order | PoolAdmin, PoolOperator, Participant |
| GET | `/transfer-orders` | List transfer orders, filterable by origin/destination/status | PoolAdmin, PoolOperator, Participant |
| POST | `/transfer-orders/{transferOrderId}/dispatch` | Dispatch a transfer order | PoolAdmin, PoolOperator, Participant |
| POST | `/transfer-orders/{transferOrderId}/receive` | Receive a transfer order | PoolAdmin, PoolOperator, Participant |
| POST | `/transfer-orders/{transferOrderId}/cancel` | Cancel a draft transfer order | PoolAdmin, PoolOperator, Participant |
| POST | `/hires` | Open a hire | PoolAdmin, PoolOperator, Participant |
| GET | `/hires/{hireId}` | Get a hire (recomputes accrual while open) | PoolAdmin, PoolOperator, Participant |
| GET | `/hires` | List hires, filterable by account/location/type/statuses | PoolAdmin, PoolOperator, Participant |
| POST | `/hires/{hireId}/close` | Close a hire | PoolAdmin, PoolOperator, Participant |
| POST | `/hires/{hireId}/void` | Void an unbilled open hire | PoolAdmin |
| POST | `/audit-reconciliations` | Create a draft audit reconciliation | PoolAdmin, PoolOperator |
| GET | `/audit-reconciliations/{auditId}` | Get an audit reconciliation | PoolAdmin, PoolOperator, Participant |
| GET | `/audit-reconciliations` | List audit reconciliations, filterable by location/status | PoolAdmin, PoolOperator, Participant |
| POST | `/audit-reconciliations/{auditId}/finalize` | Finalize an audit (declare loss, mark lost, expire vouchers) | PoolAdmin, PoolOperator |
| POST | `/audit-reconciliations/{auditId}/void` | Void a draft audit reconciliation | PoolAdmin |
| POST | `/vouchers` | Issue a voucher | PoolAdmin, PoolOperator, Participant |
| GET | `/vouchers/{voucherId}` | Get a voucher | PoolAdmin, PoolOperator, Participant |
| GET | `/vouchers` | List vouchers, filterable by origin/account/type/redeem/status | PoolAdmin, PoolOperator, Participant |
| POST | `/vouchers/{voucherId}/redeem` | Redeem a voucher | PoolAdmin, PoolOperator, Participant |
| POST | `/vouchers/{voucherId}/cancel` | Cancel an outstanding voucher | PoolAdmin |
| POST | `/collection-requests` | Request collection of idle/damaged assets | PoolAdmin, PoolOperator |
| GET | `/collection-requests/{collectionRequestId}` | Get a collection request | PoolAdmin, PoolOperator, Participant |
| GET | `/collection-requests` | List collection requests, filterable by location/status | PoolAdmin, PoolOperator, Participant |
| POST | `/collection-requests/{collectionRequestId}/collect` | Mark a collection request collected | PoolAdmin, PoolOperator |
| POST | `/collection-requests/{collectionRequestId}/close` | Close a collected request | PoolAdmin, PoolOperator |
| POST | `/collection-requests/{collectionRequestId}/cancel` | Cancel a requested collection | PoolAdmin, PoolOperator |
| POST | `/repair-jobs` | Open a repair job over damaged assets | PoolAdmin, PoolOperator |
| GET | `/repair-jobs/{repairJobId}` | Get a repair job | PoolAdmin, PoolOperator, Participant |
| GET | `/repair-jobs` | List repair jobs, filterable by collection request/status | PoolAdmin, PoolOperator, Participant |
| POST | `/repair-jobs/{repairJobId}/complete` | Complete a repair | PoolAdmin, PoolOperator |
| POST | `/repair-jobs/{repairJobId}/scrap` | Scrap a repair | PoolAdmin, PoolOperator |
| POST | `/invoices` | Create a draft invoice | PoolAdmin, PoolOperator |
| GET | `/invoices/{invoiceId}` | Get an invoice | PoolAdmin, PoolOperator, Participant |
| GET | `/invoices` | List invoices, filterable by account/status | PoolAdmin, PoolOperator, Participant |
| POST | `/invoices/{invoiceId}/lines` | Add a line to a draft invoice | PoolAdmin, PoolOperator |
| GET | `/invoices/{invoiceId}/lines` | List lines of an invoice | PoolAdmin, PoolOperator, Participant |
| GET | `/invoice-lines/{invoiceLineId}` | Get a single invoice line | PoolAdmin, PoolOperator, Participant |
| GET | `/invoice-lines` | List invoice lines, filterable by invoice/source FKs | PoolAdmin, PoolOperator, Participant |
| POST | `/invoices/{invoiceId}/issue` | Issue an invoice | PoolAdmin, PoolOperator |
| POST | `/invoices/{invoiceId}/record-payment` | Record a payment against an issued invoice | PoolAdmin, PoolOperator |
| POST | `/invoices/{invoiceId}/void` | Void a draft invoice | PoolAdmin |
| POST | `/demand-forecasts` | Compute a demand-forecast snapshot | PoolAdmin, PoolOperator, Participant |
| GET | `/demand-forecasts/{demandForecastId}` | Get a demand-forecast snapshot | PoolAdmin, PoolOperator, Participant |
| GET | `/demand-forecasts` | List demand-forecast snapshots, filterable by location/type | PoolAdmin, PoolOperator, Participant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ACCOUNT_HAS_OPEN_HIRE` | 409 Conflict |
| `ERR_ACCOUNT_NOT_SETTLED` | 409 Conflict |
| `ERR_ASSET_NOT_AVAILABLE` | 409 Conflict |
| `ERR_ASSET_NOT_DAMAGED` | 409 Conflict |
| `ERR_ASSET_WRONG_LOCATION` | 409 Conflict |
| `ERR_LOCATION_CLOSED` | 409 Conflict |
| `ERR_AUDIT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_VOUCHER_EXPIRED` | 409 Conflict |
| `ERR_VOUCHER_REDEEM_LOCATION_INVALID` | 409 Conflict |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_HIRE_NOT_CLOSED` | 409 Conflict |
| `ERR_HIRE_ALREADY_INVOICED` | 409 Conflict |
| `ERR_INVOICE_EMPTY` | 409 Conflict |
| `ERR_ASSET_TYPE_DISCONTINUED` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |

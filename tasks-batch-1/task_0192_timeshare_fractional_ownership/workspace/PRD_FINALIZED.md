# Timeshare & Fractional Ownership API — Product Requirements Document

## 1. Introduction

This document specifies the product requirements for the Timeshare & Fractional Ownership API, a system that administers the full commercial and legal lifecycle of vacation-ownership inventory at a resort. The platform reconciles two competing realities that have historically lived in separate systems: the *inventory* reality, in which bookable weeks are denominated in points, banked forward, borrowed from the future, and exchanged into external networks; and the *fiscal-and-legal* reality, in which owners are billed annual maintenance fees and special assessments, fall delinquent, are escalated through liens, and ultimately have their contracts foreclosed or terminated.

The API is built around a resort that acts as the configuration and clock authority for everything beneath it. A resort fixes the points denomination of a standard week, the cooling-off period that protects buyers, the surcharge for pulling points forward, and the thresholds that govern when an unpaid invoice becomes delinquent and when continued delinquency becomes grounds for foreclosure. Because so many rules are time-sensitive — rescission windows, grace periods, escalation periods — the resort carries an explicit, test-drivable clock rather than relying on wall-clock time. Every downstream window is measured against that clock.

Five categories of actor collaborate through the system: resort operators who set up and bill inventory, owners who book and pay against their own contracts, resale agents who broker secondary-market transfers, compliance officers who drive delinquency enforcement, and an automation actor that performs clock-driven rollover and the cascading status changes that ripple outward from a single state transition. The remainder of this document defines the global contracts that all requests obey (§2), the business workflows where the substantive rules live (§3), the endpoint surface (§4), and the catalogue of error identifiers (§5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the header pair is well-formed but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The system recognizes exactly five roles, spelled precisely as follows: `ResortManager`, `Owner`, `ResaleAgent`, `ComplianceOfficer`, and `System`.

The way `X-User-ID` is interpreted depends on the role. When `X-User-Role` is `Owner`, `X-User-ID` is the `id` of the acting `Owner`; ownership checks on any resource that references an owner compare that resource's owning `owner_id` to `X-User-ID`. Concretely, an `Owner` may act only on resources that resolve back to a contract whose `owner_id` equals the caller's `X-User-ID` — this governs reservation creation, confirmation, cancellation, and exchange-deposit; contract rescission; exchange redemption and recall; resale rescission; and contract payment. When an `Owner` targets a resource that belongs to a contract held by a different owner, the request is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `ResortManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same is true when `X-User-Role` is `ResaleAgent`, when it is `ComplianceOfficer`, and when it is `System`: in each of these four cases `X-User-ID` is an opaque identifier that is not matched against any owner or other entity.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Resort Clock

All resources carry a system-generated `id` formatted as a UUID, with no type prefix, plus a `created_at` timestamp in ISO 8601 UTC with three fractional digits indicating when the resource was first created. Every resource in this system is mutable and therefore also carries an `updated_at` timestamp — an ISO 8601 UTC timestamp, likewise with three fractional digits, refreshed on any modification to the resource — and a `version`, a system-managed integer that begins at its initial value and increments by one with every mutation of that resource. No entity in this domain is created-only; all of them expose `updated_at` and `version`.

Time in this system is not wall-clock time. Each resort exposes a `current_utc` field that represents the authoritative clock against which every window is measured, and a `current_use_year` integer that names the active use-year epoch. A test-driving capability lets an operator set `current_utc` directly to a supplied instant, which is how rescission windows and delinquency windows are exercised. The clock value supplied to that capability is the `to_iso8601` instant, and the resort whose clock is being moved is named by `resort_id`. Reads of rescission and delinquency windows always consult the resort's `current_utc`, never the host machine's time.

### 2.5. Hierarchical Consistency and Cascading State Changes

A single operation in this system rarely touches a single resource. The defining characteristic of the domain is that state transitions cascade outward: confirming a reservation mutates an inventory unit and a points account; escalating a delinquency case suspends a contract; foreclosing a case writes off invoices. Whenever an operation causes a resource to change, that resource's `updated_at` is refreshed and its `version` increments by one. This holds for every mutation, including cascaded ones that the client did not directly request — when the system itself transitions a parent or child as a downstream consequence, that secondary resource's `version` and `updated_at` advance exactly as they would for a direct change.

The system reconciles parent and child status without requiring a separate client call. When a delinquency case escalates, the owning contract is driven to `SUSPENDED` automatically; when the same case is later cured, the contract returns to `ACTIVE` automatically; when a case forecloses or terminates, the contract is driven to its terminal legal state and its delinquent invoices are written off in the same transaction. Each such automatic transition is itself a mutation that bumps the affected resource's `version` and `updated_at`. The detailed direction of each cascade is specified in the workflow narratives of §3.

### 2.6. Nested Resource Retrieval and Referential Integrity

Although the top-level collections are flat — owners, contracts, reservations, invoices and the rest are each addressed directly rather than nested under a resort path — many operations reference resources by identifier inside the request body or the path. When a request names a path resource that does not exist, the system rejects it with `ERR_NOT_FOUND`; where more than one identifier participates, existence is validated left to right, and the first identifier that does not resolve produces the rejection before any later identifier is examined.

Referential integrity is also enforced across the body. The children of a resort all carry a `resort_id`, and cross-aggregate references must stay within one resort. When a referenced foreign key — an `owner_id`, `inventory_unit_id`, `contract_id`, `invoice_id`, `special_assessment_id`, or `fixed_unit_id` — resolves to a real resource that nevertheless belongs to a different resort, the request is rejected with `ERR_CROSS_RESORT_REFERENCE`. This check runs on contract creation, reservation creation, invoice creation, payment creation, and resale-transfer creation.

### 2.7. Request Validation and Evaluation Priority

Validation across the API follows a fixed priority order, so that a request which trips several rules at once is always rejected with the highest-priority applicable error. The order is: first, header authentication — a missing or invalid `X-User-ID`/`X-User-Role` pair yields `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. Second, role authorization against the endpoint, yielding `ERR_FORBIDDEN_FOR_ROLE`. Third, for `Owner`-actor endpoints, the ownership check yielding `ERR_NOT_RESOURCE_OWNER`. Fourth, existence of path resources, yielding `ERR_NOT_FOUND`. Fifth, well-formedness of the request body, yielding `ERR_INVALID_REQUEST`. Sixth, cross-resort referential integrity, yielding `ERR_CROSS_RESORT_REFERENCE`. Seventh, the target resource being in a legal from-state for the requested transition, yielding `ERR_INVALID_STATE`.

After those seven structural gates, the business gates apply, themselves ordered: rescission-window safety (`ERR_RESCISSION_WINDOW_OPEN` or `ERR_RESCISSION_WINDOW_CLOSED`); the owning-contract-active gate (`ERR_CONTRACT_NOT_ACTIVE`); inventory availability at confirm time (`ERR_UNIT_NOT_AVAILABLE`); the delinquency block on resale completion (`ERR_CONTRACT_DELINQUENT`); the delinquency grace gate on marking an invoice delinquent (`ERR_GRACE_PERIOD_ACTIVE`); foreclosure eligibility and ownership-type matching (`ERR_FORECLOSURE_NOT_ELIGIBLE` or `ERR_OWNERSHIP_TYPE_MISMATCH`); points sufficiency and borrow ceiling (`ERR_INSUFFICIENT_POINTS`); and finally, lowest in priority, the optimistic-concurrency version check (`ERR_STALE_VERSION`). The body well-formedness gate covers required fields being present, amounts and points being strictly greater than zero where the field requires it, enum values being drawn from their legal set, `week_number` being between 1 and 52 inclusive, and `transfer_day_of_year` being between 1 and 365 inclusive.

### 2.8. Points, Fees, and Rounding Precision

Two numeric domains coexist in this system, and each has its own precision rule. Inventory is denominated in *whole points*: every points quantity — allotments, banked and borrowed balances, committed points, reservation costs, exchange credits — is an integer. Where a points calculation produces a fractional intermediate, the rounding direction is part of the rule and is specified individually in §3: the seasonal base cost is rounded half up, the early-bird discount floors the result, and a borrow surcharge is rounded up to the next whole point. Money is denominated in *whole cents*: maintenance fees, special assessments, late charges, payments, and sale prices are all integer-cents fields, and the rounding direction (ceiling for an annual fee, floor for a seller's prorated share, floor for a late charge) is again specified with each formula. The system never carries fractional points or fractional cents on a stored field.

### 2.9. Optimistic Concurrency on Points Accounts

Two write operations against a points account require the client to prove it is acting on a current view of that account, because both can over-draw an account whose balance another writer has already moved. Creating a reservation requires the request to carry `expected_points_account_version`, which must equal the current `version` of the source-use-year `PointsAccount` the reservation will draw from. If another writer has advanced that account's `version` since the client last read it — for example, a competing booking that drew down or banked points and thereby legitimately reduced `available_points` — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read and re-price before booking. Banking points forward likewise requires `expected_points_account_version` to equal the targeted account's current `version`; if the account has moved since the client observed it, the bank is rejected with `ERR_STALE_VERSION` (HTTP 412), because the requested bank amount may no longer fit within `available_points`. No other endpoint takes a version field; only reservation creation and points-account banking are guarded this way.

## 3. Business Logic & Workflows

### 3.1. Standing Up a Resort and Its Inventory

A `ResortManager` brings a property online by creating a **Resort**, which is the configuration root for everything beneath it. The creation payload supplies the resort `name` and the inventory denomination `points_per_week_base` — the number of points a standard week costs before any seasonal adjustment. It also supplies `annual_fee_cents_per_1000_points`, the maintenance-fee rate expressed in cents per thousand allotted points. Several governance parameters may be supplied or left to default: `rescission_days`, the statutory cooling-off window measured in days, defaults to 7; `borrow_surcharge_pct`, the fraction of borrowed points added as a surcharge, defaults to 0.10; `delinquency_grace_days`, the number of days after an invoice's due date before it can be marked delinquent, defaults to 30; and `foreclosure_threshold_periods`, the number of escalation periods of continuous delinquency required before a case may proceed to foreclosure or termination, defaults to 2. On creation, the resort's `current_use_year` is initialized to 2026 and `current_utc` is initialized to an epoch instant that an operator can subsequently move with the clock-setting capability.

The bookable inventory of a resort is its set of **Inventory Units**. A `ResortManager` creates each unit with a `unit_label`, the ISO `week_number` of the year it is bookable for (an integer between 1 and 52 inclusive), and a `season` tier, which is one of `PLATINUM`, `GOLD`, or `SILVER`. A new unit begins life `AVAILABLE`, and its `points_value` is computed at creation: it is the resort's `points_per_week_base` multiplied by the season multiplier — 1.50 for `PLATINUM`, 1.00 for `GOLD`, and 0.60 for `SILVER` — with the product rounded half up to a whole number of points. Over its life a unit's `status` moves among `AVAILABLE`, `RESERVED`, and `DEPOSITED_TO_EXCHANGE` as reservations claim, confirm, and deposit it. Units can be listed and filtered by their resort or their `status`.

Owners are registered separately. A `ResortManager` creates an **Owner** with a `resort_id`, a `full_name`, and an `email`. Two of an owner's fields are not stored directly but are recomputed whenever any of that owner's invoices, payments, or delinquency cases change. The first, `open_balance_cents`, is the sum of `amount_due_cents` across all of that owner's invoices whose status is either `ISSUED` or `DELINQUENT`. The second, the owner's compound `status`, is derived as follows: if any delinquency case across the owner's contracts is in `LIEN`, `FORECLOSURE`, or `TERMINATION`, the owner is `SUSPENDED`; otherwise, if any of the owner's invoices is `DELINQUENT`, the owner is `DELINQUENT`; otherwise the owner is `GOOD_STANDING`. A freshly created owner therefore reports `GOOD_STANDING` with an `open_balance_cents` of 0. Owners may be listed and filtered by `resort_id`.

### 3.2. Contracts: Signing, the Cooling-Off Window, and Activation

A **Contract** is the legal instrument binding an owner to inventory. A `ResortManager` or a `ResaleAgent` creates one with a `resort_id`, the holding `owner_id`, an `ownership_type` of either `DEEDED` or `RIGHT_TO_USE`, and an `inventory_model` of either `POINTS` or `FIXED_WEEK`. A `POINTS` contract carries an `annual_points_allotment` granted each use-year; a `FIXED_WEEK` contract instead names a `fixed_unit_id` referencing the deeded week and leaves the allotment at its default of 0. A `RIGHT_TO_USE` contract may carry an `rtu_expiry_use_year` naming its last valid use-year, whereas a `DEEDED` contract is perpetual and leaves that field unset. On creation the contract's `signed_at` is stamped from the resort clock and the contract enters `PENDING_RESCISSION`. Its `superseded_by_contract_id` is unset until and unless a resale transfer replaces it.

The cooling-off window is the period of `rescission_days` after `signed_at`, measured against the resort's `current_utc`. A `ResortManager` activates a `PENDING_RESCISSION` contract, advancing it to `ACTIVE`, but only once the window has fully elapsed — that is, once `current_utc` is at or after `signed_at` plus `rescission_days` days. An attempt to activate while the window is still open is rejected with `ERR_RESCISSION_WINDOW_OPEN`. Activation has model-dependent side effects: for a `POINTS` contract, the system opens a `PointsAccount` for the resort's `current_use_year` if none exists, snapshotting `allotment_points` from the contract's `annual_points_allotment` so that `available_points` initially equals that allotment; for a `FIXED_WEEK` contract, the system sets the deeded fixed unit's `status` to `RESERVED`. The activation increments the contract's `version` by one.

The mirror-image action is rescission. An `Owner` or a `ComplianceOfficer` may rescind a `PENDING_RESCISSION` contract, moving it to `RESCINDED`, but only while still inside the cooling-off window — that is, while `current_utc` is at or before `signed_at` plus `rescission_days` days. An attempt to rescind after the window has closed is rejected with `ERR_RESCISSION_WINDOW_CLOSED`. Rescission voids the contract's invoices: every `DRAFT` and every `ISSUED` `MaintenanceFeeInvoice` for the contract transitions to `WRITTEN_OFF`. Rescission increments the contract's `version` by one. A contract's `status` ranges over `PENDING_RESCISSION`, `ACTIVE`, `SUSPENDED`, `RESCINDED`, `TERMINATED`, `FORECLOSED`, and `TRANSFERRED`; the latter four are terminal. Contracts may be listed and filtered by `resort_id`, `owner_id`, `status`, `fixed_unit_id`, or `superseded_by_contract_id`.

### 3.3. Points Accounts: Allotment, Banking, and Borrowing

Each `POINTS` contract keeps a per-use-year ledger called a **Points Account**, created by activation and by rollover. A points account names its `contract_id` and the `use_year` it tracks, and records the `allotment_points` granted for that year (a snapshot of the contract's `annual_points_allotment` taken when the account opens). It separately tracks `banked_in_points` carried into this year from last year's banking, `banked_out_points` banked forward out of this year into next year, `borrowed_out_points` pulled forward from this year into a prior year's reservations, and `committed_points` held by confirmed reservations that draw on this account. The reported `available_points` is a derived figure: it is `allotment_points` plus `banked_in_points`, minus `banked_out_points`, minus `borrowed_out_points`, minus `committed_points`. An account's own `status` is either `OPEN` or `ROLLED_OVER`. Accounts may be listed and filtered by `contract_id` or `use_year`.

Banking moves points from one year into the next. An `Owner` or a `ResortManager` banks a quantity of `points` out of a chosen account; the request must also carry `expected_points_account_version` matching that account's current `version`, per the concurrency rule in §2.9. The banked amount cannot exceed the account's `available_points`; a request to bank more than is available is rejected with `ERR_INSUFFICIENT_POINTS`. A successful bank increases the source account's `banked_out_points` by the banked `points` (which lowers its `available_points` by the same amount), and increases the next use-year account's `banked_in_points` by that same `points` quantity, creating the next-year account for the contract if it does not yet exist. The bank increments the source `PointsAccount`'s `version` by one.

### 3.4. Reservations: Pricing, Borrowing the Future, Holding, and Confirming

An `Owner` books inventory by creating a **Reservation**, supplying the reserving `contract_id`, the `inventory_unit_id` of the desired unit, the `use_year` whose account funds the booking, and `expected_points_account_version` for the funding account. A new reservation is created in `HELD` status, and its cost is priced immediately and pinned thereafter. Pricing proceeds in stages. The base cost starts from the unit's seasonal price: the resort's `points_per_week_base` multiplied by the season multiplier (1.50 for `PLATINUM`, 1.00 for `GOLD`, 0.60 for `SILVER`), rounded half up to a whole number — and this rounding happens before any discount is applied. Next, a lead-time discount is considered: the number of whole days between the resort's `current_utc` and the start of the target use-year is computed, and if that lead time is at least 180 days, the discounted cost is the base cost multiplied by 0.90 (a ten percent early-bird reduction) with the result floored to a whole number; otherwise the discounted cost is simply the base cost.

The discounted cost is then funded against the source account's `available_points`, and this is where the reservation's `points_cost` and `borrowed_points` are settled. If the discounted cost is less than or equal to the source account's `available_points`, then `borrowed_points` is 0 and `points_cost` equals the discounted cost; no surcharge applies and the next year's account is untouched. If instead the discounted cost exceeds available points, the shortfall — the discounted cost minus the available points — must be borrowed from the future: `borrowed_points` is set to that shortfall, a surcharge equal to the shortfall multiplied by the resort's `borrow_surcharge_pct` and rounded up to the next whole point is computed, and `points_cost` becomes the discounted cost plus that surcharge. The borrowed portion equals the shortfall alone — not the shortfall plus surcharge — and the surcharge is charged against the current use-year account, not the borrowed-from account. The borrow source is the contract's account for `use_year` plus one; the reservation records the funding account as `source_use_year_account_id` and, when borrowing occurs, the borrowed-from account as `borrow_source_account_id`. If the `use_year` plus one account does not yet exist it is created lazily during pricing, with its `allotment_points` snapshotted from the contract's `annual_points_allotment`, and crucially without advancing the clock. The borrowed amount may not exceed the borrow-source account's `available_points`; if it would, the reservation is rejected with `ERR_INSUFFICIENT_POINTS`. Creating the reservation increments the source use-year `PointsAccount`'s `version` by one. Reservations may be listed and filtered by `contract_id`, `inventory_unit_id`, `source_use_year_account_id`, `borrow_source_account_id`, `status`, or `use_year`.

When the holder is ready, an `Owner` confirms a `HELD` reservation, advancing it from `HELD` to `CONFIRMED`. Confirmation requires that the owning contract be `ACTIVE`; otherwise the request is rejected with `ERR_CONTRACT_NOT_ACTIVE`. It also requires the target `InventoryUnit` to be `AVAILABLE` at confirm time — many reservations may hold the same unit-week, but only one may confirm it, and a confirm against a unit that is already `RESERVED` or `DEPOSITED_TO_EXCHANGE` is rejected with `ERR_UNIT_NOT_AVAILABLE`. On confirmation the unit's `status` becomes `RESERVED`, the source points account's `committed_points` increases by the non-borrowed portion of the cost (the `points_cost` minus the `borrowed_points`), and when there is a borrowed portion the borrow-source account's `borrowed_out_points` increases by that `borrowed_points`. A reservation's `status` ranges over `HELD`, `CONFIRMED`, `CANCELLED`, `COMPLETED`, `DEPOSITED_TO_EXCHANGE`, and `EXPIRED`.

### 3.5. Reservation Endings: Cancellation, Completion, and Expiry

A reservation can be cancelled by an `Owner` or a `ResortManager`. Cancelling a `HELD` reservation simply marks it `CANCELLED`; because no points were committed at hold time, no points balances change. Cancelling a `CONFIRMED` reservation marks it `CANCELLED` and unwinds the commitments made at confirm: the unit's `status` returns to `AVAILABLE`, the source account's `committed_points` is reduced by the non-borrowed portion (the `points_cost` minus the `borrowed_points`) as compensation, and where a borrowed portion existed the borrow-source account's `borrowed_out_points` is reduced by the `borrowed_points` as compensation.

A `ResortManager` completes a `CONFIRMED` reservation when the stay has been consumed, moving it from `CONFIRMED` to `COMPLETED`. Completion returns the unit's `status` to `AVAILABLE` and reduces the source account's `committed_points` by the non-borrowed portion (the `points_cost` minus the `borrowed_points`) — but here the points are consumed rather than refunded; the reduction reflects that the held commitment has been spent, not released for reuse.

Reservations that never progress past `HELD` are reaped at use-year rollover. During rollover for the closing use-year, every still-`HELD` reservation on that year transitions from `HELD` to `EXPIRED`. The terminal reservation states are `CANCELLED`, `COMPLETED`, and `EXPIRED`.

### 3.6. The Exchange Network: Depositing, Redeeming, and Recalling

An `Owner` can place a confirmed week into an external exchange network. Depositing advances the reservation from `CONFIRMED` to `DEPOSITED_TO_EXCHANGE` and mints an **Exchange Deposit**. The deposit request names the `exchange_network`, which is either `RCI` or `II`. Depositing requires the owning contract to be `ACTIVE`, failing with `ERR_CONTRACT_NOT_ACTIVE` otherwise, and requires that the reservation does not already have an exchange deposit in `DEPOSITED` or `REDEEMED` status, failing with `ERR_ALREADY_DEPOSITED` otherwise. The deposit records the originating `reservation_id` and a snapshot of the owning `contract_id`. Its `exchange_credits` are granted by network: the reservation's `points_cost` is divided by the network's credit divisor — 100 for `RCI`, 120 for `II` — and floored to a whole number of credits. At the boundary, a `points_cost` exactly equal to the divisor yields exactly one credit, while one point below the divisor yields zero. Depositing also drives the inventory unit's `status` to `DEPOSITED_TO_EXCHANGE`, and the new exchange deposit opens in `DEPOSITED` status. Exchange deposits may be listed and filtered by `reservation_id`, `contract_id`, or `status`.

A `DEPOSITED` exchange deposit has two exits. An `Owner` may redeem it, moving it from `DEPOSITED` to `REDEEMED`, at which point the credits are considered consumed externally. Alternatively, an `Owner` may recall it, moving it from `DEPOSITED` to `RECALLED`; recall pulls the week back from the network, restoring the underlying reservation's `status` to `CONFIRMED` and the inventory unit's `status` to `RESERVED`. The terminal exchange-deposit states are `REDEEMED` and `RECALLED`.

### 3.7. Maintenance Fees, Special Assessments, and Payments

Maintenance billing flows through the **Maintenance Fee Invoice**. A `ResortManager` creates an invoice for a `contract_id` with a `source_type` of `ANNUAL`, the `use_year` the charge applies to, and a `due_date` measured against the resort clock; the owner billed is captured as `owner_id` from the contract at issue. Invoices carrying a `source_type` of `SPECIAL_ASSESSMENT` additionally reference the originating `special_assessment_id`. A new invoice begins as `DRAFT` with a provisionally computed `amount_cents`. The provisional full-year annual fee is computed as the contract's `annual_points_allotment` divided by 1000, multiplied by the resort's `annual_fee_cents_per_1000_points`, with the result taken as the ceiling to a whole number of cents; for a `FIXED_WEEK` contract the points basis is the fixed unit's `points_value` rather than the allotment. An invoice also carries a `late_charge_cents` accumulator (starting at 0), an `amount_paid_cents` accumulator (the sum of cleared payment allocations, starting at 0), and a derived `amount_due_cents` equal to `amount_cents` plus `late_charge_cents` minus `amount_paid_cents`.

A `ResortManager` issues a `DRAFT` invoice, moving it to `ISSUED` and finalizing its `amount_cents`; issuance is permitted only while the owning contract is `ACTIVE` or `SUSPENDED`, and is otherwise rejected with `ERR_CONTRACT_NOT_ACTIVE`. For an annual invoice issued before any resale touches the use-year, the finalized `amount_cents` is the full-year figure. The full-year figure is split only when a resale completes in the relevant use-year, as described in §3.9. A `ResortManager` may mark an `ISSUED` invoice `DELINQUENT`, but two conditions guard this: the invoice's `amount_due_cents` must be strictly greater than 0, otherwise the request is rejected with `ERR_INVOICE_NOT_PAYABLE`; and the resort's `current_utc` must be at or after the `due_date` plus `delinquency_grace_days` days, otherwise the request is rejected with `ERR_GRACE_PERIOD_ACTIVE`. Marking an invoice delinquent opens a delinquency case in `NOTICE` for the contract if none is open, recording the invoice as the case's trigger. An invoice's `status` ranges over `DRAFT`, `ISSUED`, `PAID`, `DELINQUENT`, and `WRITTEN_OFF`, the last being terminal. Invoices may be listed and filtered by `contract_id`, `owner_id`, `status`, `use_year`, or `special_assessment_id`.

Owners settle invoices with a **Payment**. A `ResortManager` or an `Owner` creates a payment against a `contract_id` for an `amount_cents` that must be strictly greater than 0, optionally naming a specific target `invoice_id`. A new payment starts `INITIATED`. A `ResortManager` clears an `INITIATED` payment, moving it to `CLEARED` and allocating its amount across invoices: if an explicit `invoice_id` was named, the allocation targets that invoice; otherwise the amount is auto-allocated across the contract's `ISSUED` and `DELINQUENT` invoices oldest first, ordered by `due_date` ascending and then by `created_at` ascending. Each invoice whose `amount_due_cents` reaches 0 transitions to `PAID` as a cascade. When clearing brings the contract's last `DELINQUENT` invoice to a zero `amount_due_cents`, the owning delinquency case is cured as described in §3.8. A `ResortManager` may instead fail an `INITIATED` payment, moving it to `FAILED`. A `ResortManager` may reverse a `CLEARED` payment, moving it to `REVERSED`: this undoes the allocations by reducing each previously-credited invoice's `amount_paid_cents`, reverting any `PAID` invoice back to `ISSUED` (or to `DELINQUENT` if it is now past grace), and, if a delinquency case had been cured by this very payment, re-opening that case to its prior `LIEN` or `NOTICE` state. A payment's `status` ranges over `INITIATED`, `CLEARED`, `FAILED`, and `REVERSED`. Payments may be listed and filtered by `contract_id`, `invoice_id`, or `status`.

Resort-wide capital costs are levied through the **Special Assessment**. A `ResortManager` creates one with a `resort_id`, a `reason`, a `total_amount_cents` that must be strictly greater than 0, and the `use_year` it is billed against; it begins as `DRAFT`. Levying it requires at least one `ACTIVE` contract at the resort, otherwise the request is rejected with `ERR_NO_ELIGIBLE_CONTRACTS`. The levy call carries a `due_date` for the invoices it spawns, moves the assessment to `LEVIED`, and creates one `SPECIAL_ASSESSMENT` `MaintenanceFeeInvoice` in `DRAFT` per `ACTIVE` contract. The assessment's `total_amount_cents` is distributed across those active contracts in proportion to each contract's points basis — its `annual_points_allotment` for a `POINTS` contract, or the fixed unit's `points_value` for a `FIXED_WEEK` contract. The distribution is computed by first summing every active contract's points basis, then for each contract taking the exact proportional share (the `total_amount_cents` multiplied by that contract's basis, divided by the total basis) and flooring it to whole cents. The cents left over after flooring — the `total_amount_cents` minus the sum of the floored shares — are then handed out one extra cent at a time to contracts ordered by the largest fractional remainder of their exact share first, with ties broken by the earlier contract `created_at`. This round-down-then-distribute order guarantees that the sum of the per-contract assessed amounts equals the assessment's `total_amount_cents` exactly, with no drift. A special assessment's `status` is either `DRAFT` or `LEVIED`, and assessments may be listed and filtered by `resort_id` or `status`.

### 3.8. Delinquency: Notice, Lien, Cure, and the Late-Charge Engine

When an invoice falls delinquent, a **Delinquency Case** tracks the enforcement against the contract. The case records the `contract_id`, a snapshot of the `owner_id`, and the `trigger_invoice_id` whose delinquency opened it. It carries an `escalation_periods` counter starting at 0 and a `late_charge_basis` that selects the late-charge formula, defaulting to `COMPOUNDING` but settable to `SIMPLE`. A case's `status` walks `NOTICE`, `LIEN`, `FORECLOSURE`, `TERMINATION`, and `CURED`; the last three are terminal. Cases may be listed and filtered by `contract_id`, `owner_id`, `trigger_invoice_id`, or `status`.

A `ComplianceOfficer` escalates a case. The first escalation moves it from `NOTICE` to `LIEN`; subsequent escalations keep it in `LIEN` (a self-loop). Either way, escalation requires that the contract still has a `DELINQUENT` invoice, otherwise it is rejected with `ERR_NO_DELINQUENT_INVOICE`. Each escalation increments `escalation_periods` by one and applies the late-charge engine to each of the contract's `DELINQUENT` invoices. The engine has two variants, chosen by the case's `late_charge_basis`. Under the `SIMPLE` basis, each period adds a flat charge equal to the invoice's original `amount_cents` multiplied by the late rate of 0.05, floored to whole cents, to the invoice's `late_charge_cents`. Under the `COMPOUNDING` basis, each period instead charges the late rate of 0.05 against the running balance — the invoice's `amount_cents` plus its already-accumulated `late_charge_cents` — again floored to whole cents and added to `late_charge_cents`. The two bases produce the same charge in the first period but diverge from the second escalation onward, with the compounding charge strictly larger thereafter for identical inputs. The first escalation to `LIEN` also cascades the owning contract from `ACTIVE` to `SUSPENDED`, and that suspension itself cancels every `HELD` reservation on the contract (each moving from `HELD` to `CANCELLED`).

Cure is automatic and is driven by payment. When a contract has no remaining `DELINQUENT` invoices, its delinquency case moves to `CURED` — from `NOTICE` directly, or from `LIEN`. A cure out of `LIEN` additionally cascades the owning contract from `SUSPENDED` back to `ACTIVE`. Because cure is the trigger for contract reactivation, the reversal of the very payment that caused a cure re-opens the case (as described in §3.7), which in turn re-suspends the contract.

### 3.9. Foreclosure, Termination, and the Resale Market

When delinquency persists, a `ComplianceOfficer` can foreclose a case. Foreclosure is gated on eligibility: the case must be in `LIEN` and its `escalation_periods` must be at least the resort's `foreclosure_threshold_periods`, otherwise the request is rejected with `ERR_FORECLOSURE_NOT_ELIGIBLE`. The legal branch then depends on the contract's `ownership_type`. A `DEEDED` contract is foreclosed: the case moves from `LIEN` to `FORECLOSURE` and the contract cascades from `SUSPENDED` to `FORECLOSED`. A `RIGHT_TO_USE` contract is instead terminated: the case moves from `LIEN` to `TERMINATION` and the contract cascades from `SUSPENDED` to `TERMINATED`. Invoking the foreclosure branch against the wrong ownership type — trying to foreclose a right-to-use contract or terminate a deeded one — is rejected with `ERR_OWNERSHIP_TYPE_MISMATCH`. In either branch the contract's terminal transition writes off its `DELINQUENT` invoices to `WRITTEN_OFF`, cancels all non-terminal reservations on the contract (releasing their committed points), and for a `FIXED_WEEK` deeded contract releases the fixed unit's `status` back to `AVAILABLE`. The contract `version` increments on its terminal transition.

The secondary market is handled by the **Resale Transfer**. A `ResaleAgent` initiates one with the `source_contract_id` being sold, the `buyer_owner_id`, a `sale_price_cents` that must be at least 0, the `transfer_use_year` in which the transfer takes effect, and the `transfer_day_of_year` (between 1 and 365 inclusive) used to prorate that year's annual fee. The resort is snapshotted as `resort_id`, the transfer's `signed_at` is stamped from the resort clock — starting the buyer's cooling-off window — and the transfer begins in `PENDING_RESCISSION`; its `new_contract_id` is unset until completion. Completing a transfer is a `ResaleAgent` action gated by three conditions: the resort's `current_utc` must be at or after `signed_at` plus `rescission_days` days, otherwise `ERR_RESCISSION_WINDOW_OPEN`; the source contract must be `ACTIVE`, otherwise `ERR_CONTRACT_NOT_ACTIVE`; and the source contract must have no open delinquency case in `NOTICE` or `LIEN`, otherwise `ERR_CONTRACT_DELINQUENT`. Completion moves the transfer to `COMPLETED`, cascades the source contract from `ACTIVE` to `TRANSFERRED`, and sets the source contract's `superseded_by_contract_id` to a freshly minted buyer contract. That new contract is created `ACTIVE` for the `buyer_owner_id` with the same `inventory_model` and allotment as the source, and is recorded back on the transfer as `new_contract_id`.

Completion also splits the `transfer_use_year` annual invoice between seller and buyer. Starting from the full-year annual fee figure for that use-year, the seller's share is the full-year figure multiplied by `transfer_day_of_year`, divided by 365, floored to whole cents; the buyer's share is the full-year figure minus the seller's share, so that the remainder absorbs any rounding and the two parts sum back exactly to the original full-year figure. The seller's existing `ANNUAL` invoice has its `amount_cents` reduced to the seller's share, and a new `ISSUED` buyer invoice is created carrying the buyer's share. A pending transfer can instead be rescinded by an `Owner` or a `ComplianceOfficer` while still inside the cooling-off window — that is, while `current_utc` is at or before `signed_at` plus `rescission_days` days — moving it to `RESCINDED`; an attempt to rescind after the window has closed is rejected with `ERR_RESCISSION_WINDOW_CLOSED`. A rescinded transfer leaves the source contract with its current owner, unchanged. A transfer's `status` is one of `PENDING_RESCISSION`, `COMPLETED`, or `RESCINDED`. Transfers may be listed and filtered by `source_contract_id`, `buyer_owner_id`, `new_contract_id`, `resort_id`, or `status`.

### 3.10. Use-Year Rollover

The passage of time at a resort is enacted by rollover, performed by a `ResortManager` or by the `System` automation actor. Rolling over advances the resort's `current_use_year` by one and performs three sweeps for the closing year. First, every `OPEN` `PointsAccount` in the closing year is moved to `ROLLED_OVER`, a next-year account is opened for its contract, and that account's `banked_in_points` is seeded by carrying forward the closing account's `banked_out_points`. Second, every still-`HELD` reservation on the closing year is expired, moving from `HELD` to `EXPIRED`. Third, any `ISSUED` invoice whose grace period has elapsed is marked `DELINQUENT` by the system and, where appropriate, has a delinquency case opened for it — the same grace condition that gates the manual mark-delinquent action applies here.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including the state-transition actions that drive the various lifecycles, and the clock and rollover capabilities — return a `200 OK` status code. The request and response payloads for each operation, including which fields are required and what side effects fire, are specified in the workflow narratives of §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/resorts` | Create a Resort | ResortManager |
| GET | `/resorts/{resortId}` | Get a Resort | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/resorts/{resortId}/rollover-use-year` | Advance the resort to the next use-year | ResortManager, System |
| POST | `/owners` | Create an Owner | ResortManager |
| GET | `/owners/{ownerId}` | Get an Owner | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/owners` | List Owners | ResortManager, ResaleAgent, ComplianceOfficer |
| POST | `/inventory-units` | Create an InventoryUnit | ResortManager |
| GET | `/inventory-units/{unitId}` | Get an InventoryUnit | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/inventory-units` | List InventoryUnits | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/contracts` | Create a Contract | ResortManager, ResaleAgent |
| GET | `/contracts/{contractId}` | Get a Contract | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/contracts` | List Contracts | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/contracts/{contractId}/activate` | Activate a contract after the rescission window has elapsed | ResortManager |
| POST | `/contracts/{contractId}/rescind` | Rescind a contract inside the cooling-off window | Owner, ComplianceOfficer |
| GET | `/points-accounts/{accountId}` | Get a PointsAccount | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/points-accounts` | List PointsAccounts | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/points-accounts/{accountId}/bank` | Bank points forward into the next use-year | Owner, ResortManager |
| POST | `/reservations` | Create a HELD reservation | Owner |
| GET | `/reservations/{reservationId}` | Get a Reservation | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/reservations` | List Reservations | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/reservations/{reservationId}/confirm` | Confirm a HELD reservation | Owner |
| POST | `/reservations/{reservationId}/cancel` | Cancel a HELD or CONFIRMED reservation | Owner, ResortManager |
| POST | `/reservations/{reservationId}/complete` | Mark a CONFIRMED reservation COMPLETED | ResortManager |
| POST | `/reservations/{reservationId}/deposit-exchange` | Deposit a CONFIRMED reservation into an external exchange | Owner |
| GET | `/exchange-deposits/{depositId}` | Get an ExchangeDeposit | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/exchange-deposits` | List ExchangeDeposits | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/exchange-deposits/{depositId}/redeem` | Redeem exchange credits | Owner |
| POST | `/exchange-deposits/{depositId}/recall` | Recall a deposited reservation from the exchange | Owner |
| POST | `/invoices` | Create a DRAFT MaintenanceFeeInvoice | ResortManager |
| GET | `/invoices/{invoiceId}` | Get a MaintenanceFeeInvoice | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/invoices` | List MaintenanceFeeInvoices | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/invoices/{invoiceId}/issue` | Issue a DRAFT invoice | ResortManager |
| POST | `/invoices/{invoiceId}/mark-delinquent` | Mark an ISSUED invoice DELINQUENT | ResortManager |
| POST | `/payments` | Create an INITIATED Payment | ResortManager, Owner |
| GET | `/payments/{paymentId}` | Get a Payment | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/payments` | List Payments | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/payments/{paymentId}/clear` | Clear a Payment and allocate to invoices | ResortManager |
| POST | `/payments/{paymentId}/fail` | Mark an INITIATED Payment FAILED | ResortManager |
| POST | `/payments/{paymentId}/reverse` | Reverse a CLEARED Payment | ResortManager |
| POST | `/special-assessments` | Create a DRAFT SpecialAssessment | ResortManager |
| GET | `/special-assessments/{assessmentId}` | Get a SpecialAssessment | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/special-assessments` | List SpecialAssessments | ResortManager, ResaleAgent, ComplianceOfficer |
| POST | `/special-assessments/{assessmentId}/levy` | Levy the assessment and create per-contract invoices | ResortManager |
| POST | `/resale-transfers` | Initiate a resale transfer of a contract | ResaleAgent |
| GET | `/resale-transfers/{transferId}` | Get a ResaleTransfer | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| GET | `/resale-transfers` | List ResaleTransfers | ResortManager, Owner, ResaleAgent, ComplianceOfficer |
| POST | `/resale-transfers/{transferId}/complete` | Complete a resale transfer | ResaleAgent |
| POST | `/resale-transfers/{transferId}/rescind` | Rescind a pending resale transfer inside the window | Owner, ComplianceOfficer |
| GET | `/delinquency-cases/{caseId}` | Get a DelinquencyCase | ResortManager, ComplianceOfficer, Owner |
| GET | `/delinquency-cases` | List DelinquencyCases | ResortManager, ComplianceOfficer, Owner |
| POST | `/delinquency-cases/{caseId}/escalate` | Escalate a case and apply late charges | ComplianceOfficer |
| POST | `/delinquency-cases/{caseId}/foreclose` | Foreclose (DEEDED) or terminate (RIGHT_TO_USE) a case | ComplianceOfficer |
| POST | `/_clock/set_current_utc` | Set the resort clock | ResortManager, System |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CROSS_RESORT_REFERENCE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_RESCISSION_WINDOW_OPEN` | 409 Conflict |
| `ERR_RESCISSION_WINDOW_CLOSED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CONTRACT_DELINQUENT` | 409 Conflict |
| `ERR_GRACE_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_FORECLOSURE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_OWNERSHIP_TYPE_MISMATCH` | 409 Conflict |
| `ERR_INSUFFICIENT_POINTS` | 409 Conflict |
| `ERR_ALREADY_DEPOSITED` | 409 Conflict |
| `ERR_NO_ELIGIBLE_CONTRACTS` | 409 Conflict |
| `ERR_NO_DELINQUENT_INVOICE` | 409 Conflict |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

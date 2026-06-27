# Grain Elevator Coop API — Product Requirements Document

## 1. Introduction

This document specifies the back-office API for a farmer-owned grain elevator and marketing cooperative. The cooperative receives grain from its member-patrons at the scale, grades each inbound load for moisture and foreign material, deposits the cleaned and shrunk bushels into a storage program, markets that grain through cash and futures-linked contracts, settles priced bushels into cash and equity proceeds, ships the grain off the elevator, hedges the elevator's own price exposure on the futures market, and at year end distributes a patronage dividend back to its members. Each of these stages is a small ledger of its own, and the whole system is fundamentally a reconciliation engine: bushels weighed in must equal bushels stored, priced, shipped, and paid out, and every dollar of proceeds, drying charge, storage charge, margin, and patronage must trace back to a deterministic calculation.

The platform serves a handful of specialized back-office operators — merchandisers, grade clerks, settlement officers, shipping clerks, and risk managers — who each own one slice of the grain's journey. Because grain prices, basis, and futures move continuously, many figures (cash bids, contract net prices, mark-to-market profit and loss, storage accruals) are recomputed on demand from the latest posted board and the server's logical clock rather than stored statically. The contracts in this document are therefore unusually precise about evaluation order, rounding, threshold inclusivity, and concurrency: a half-cent of drift in a drying charge, or a single day mis-counted in a storage accrual, multiplied across thousands of loads, is a real financial discrepancy the cooperative's auditors will surface.

All resources in this system are mounted under the `/commodities` API prefix. A small administrative test-driving facility for the server's logical clock is also provided so that day-sensitive accruals can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers identifying the caller: `X-User-ID`, an opaque operator identifier, and `X-User-Role`, naming the caller's role. If `X-User-Role` is missing or does not name one of the five known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to perform the requested operation under the access-control matrix below, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The five roles are `Merchandiser`, `GradeClerk`, `SettlementOfficer`, `ShippingClerk`, and `RiskManager`. These are peer roles: each owns an exclusive set of write operations, and all five share broad read access to the resources relevant to their work.

- A `Merchandiser` is the cooperative's commercial desk. This role exclusively sets up commodities, posts price boards, registers members, creates marketing contracts and fixes or cancels them, freezes and unfreezes storage accrual, issues warehouse receipts, creates load-out bays and dryer lines, opens and closes patronage periods, and operates the logical-clock test facility.
- A `GradeClerk` exclusively weighs in inbound loads, grades them into storage, voids weighed tickets, and reserves and releases drying windows on the dryer lines.
- A `SettlementOfficer` exclusively drafts settlements, posts them, and cancels them.
- A `ShippingClerk` exclusively schedules shipments and then loads, ships, or cancels them.
- A `RiskManager` exclusively opens hedge positions, applies marks, meets margin calls, and closes positions.

Every role in this system carries an **opaque** identity. For all five roles — `Merchandiser`, `GradeClerk`, `SettlementOfficer`, `ShippingClerk`, and `RiskManager` — the `X-User-ID` header is an opaque operator identifier that is not tied to any persisted entity. The server may record the value for audit but never compares it to any entity's `id`, and ownership of grain, contracts, or positions is never determined from `X-User-ID`. Members are independent `Member` records referenced by foreign key on the resources they own; no member ever authenticates as a member, so there is no entity-backed identity to reconcile.

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

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may be at most 100. The `offset` parameter defaults to 0 and must be at least 0. A `limit` or `offset` that is non-integer or outside these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 422). List results are always sorted by `created_at` in ascending order (oldest first), with records that share the same `created_at` ordered by their creation sequence (insertion order). The `meta` block of a list response carries the pagination fields `limit`, `offset`, `total_count` (the total number of matching records before the limit/offset window is applied), and `has_more` (true when records remain beyond the current window).

### 2.4. Resource Identity, Versioning, and Timestamps

Every resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded in ISO 8601 UTC with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that begins at 1 on creation and increments by exactly 1 on each mutation. The one exception is the `PatronageAllocation` record: an allocation is an append-only, immutable accounting entry that carries only `id` and `created_at` — it has no `updated_at` and no `version`, because it is never modified after it is posted. All other entities — `Commodity`, `PriceBoard`, `Member`, `ScaleTicket`, `StoragePosition`, `WarehouseReceipt`, `Contract`, `Settlement`, `LoadoutBay`, `DryerLine`, `DryingReservation`, `Shipment`, `HedgePosition`, and `PatronagePeriod` — carry the full set of common fields.

### 2.5. Nested Resource Retrieval and Referential Existence

Requests are validated from the outside in. Every identifier in the URL path and every foreign key in a request body must resolve to an existing resource, checked left to right; the first identifier that fails to resolve causes the request to be rejected with `ERR_NOT_FOUND` (HTTP 404). For a nested read such as the allocations posted under a patronage period, the `patronage_period_id` in the path is validated before its allocation list is gathered; likewise a member's allocation listing first resolves the `member_id`. Once existence is established, the request body itself is checked: required fields must be present and well-typed, every enum value must fall within its declared set, every weight, bushel count, and contract count must be non-negative, and on a scale ticket the `gross_weight_lbs` must be strictly greater than the `tare_weight_lbs`. Any of these failures yields `ERR_INVALID_REQUEST` (HTTP 422).

### 2.6. Validation Ordering

When several checks could fire on a single request, they are evaluated in a fixed precedence so that the returned error is deterministic. Authentication is checked first (`ERR_UNAUTHENTICATED`), then authorization against the role matrix (`ERR_FORBIDDEN`), then the existence of every path id and body foreign key (`ERR_NOT_FOUND`), then request-body shape and field constraints (`ERR_INVALID_REQUEST`). Only after those four universal gates pass does the system evaluate state-machine eligibility (`ERR_INVALID_STATE`) and then the operation-specific business rules. Among the business rules that can co-occur on a single endpoint, the relative orderings that matter are stated alongside the workflows in Section 3 — for example, a settlement post checks commodity/member coherence, contract pricing readiness, contract overfill, and bushel availability, and a margin-call meet checks state, the stale-version guard, and deposit sufficiency. Where a stale-version guard applies, it is treated as part of the same finalization that the workflow describes.

### 2.7. Monetary and Bushel Precision

Bushel quantities are computed and stored to 4 decimal places, rounded half up. Dollar amounts — drying charges, proceeds, storage charges, margin figures, and patronage allocations — are computed and stored to 2 decimal places, rounded half up, except where a calculation explicitly floors a value down to whole cents (the cash portion of a patronage allocation, described in Section 3). A contract's net price is carried to 4 decimal places, rounded half up. Datetime comparisons used for window conflicts and storage-day counting are exact, and the dryer cleanout buffer is expressed in whole minutes.

### 2.8. Hierarchical Consistency and Cascading Effects

Many operations in this system mutate more than one entity. When that happens, every affected resource has its `updated_at` refreshed and, where it carries a `version`, its `version` incremented by exactly 1. The detailed cascades — a graded ticket spawning a storage position, a posted settlement drawing down a position and filling a contract and crediting a member, a depletion cancelling a warehouse receipt, a patronage close crediting every participating member — are described with the workflows that drive them in Section 3. The governing principle is that these cascades are atomic with the triggering operation: a settlement post that fills a contract to its contracted quantity transitions both the settlement and the contract in the same action, and a draw that empties a position depletes it (and cancels its receipt) in the same action.

### 2.9. The Logical Clock

Storage accrual, drying-day math, and storage-start stamping are all driven by a server logical clock rather than wall-clock time. At startup the clock reads `2026-01-01T00:00:00Z`, and it never falls back to wall-clock time. A `Merchandiser` may advance the clock to a supplied `to_iso8601` instant for deterministic test-driving; the clock value at the moment a ticket is graded becomes that grain's `storage_start_date`, and the clock value at settlement time anchors the storage-charge day count.

### 2.10. Optimistic Concurrency on Guarded Writes

Two finalization operations are guarded against stale reads using optimistic concurrency control, because each depends on a figure that an unrelated earlier write may have moved.

The first guard protects settlement posting against a stale storage position. A post request must carry `expected_storage_position_version`, a non-optional field holding the `version` of the storage position the client last observed. The server compares it against the position's current `version`; if they do not match — because a prior settlement post or a shipment load already drew down that position's `bushels_available` and advanced its `version` since the client read it — the post is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a second post that still carries the old version from over-drawing a position whose available bushels it has not actually observed.

The second guard protects meeting a margin call against a stale hedge position. A meet-call request must carry `expected_hedge_position_version`, a non-optional field holding the `version` of the hedge position the client last observed. The server compares it against the position's current `version`; if they do not match — because a new mark moved the call amount (or cleared the call entirely) and advanced the position's `version` since the client read it — the meet-call is rejected with `ERR_STALE_VERSION` (HTTP 412), because it is acting on a stale call figure. No other endpoint takes a version field; only these two finalizations are version-guarded.

For both guarded writes the presence and integer-typedness of the version field are validated as a body-shape check (`ERR_INVALID_REQUEST`, HTTP 422) at the very start of the request, ahead of the path-id existence check — so a missing or non-integer version field on either endpoint yields `ERR_INVALID_REQUEST` even when the targeted settlement or hedge position does not exist. The stale-version *comparison* itself, by contrast, is the final guard of the settlement-post finalization: it is evaluated only after the commodity/member-coherence, contract-pricing-readiness, contract-overfill, and bushel-availability business checks have all passed. For the meet-call it is evaluated after the state check and before the deposit-sufficiency check, as Section 2.6 describes.

## 3. Business Logic & Workflows

### 3.1. Reference Setup: Commodities, Price Boards, and Members

Before any grain moves, a `Merchandiser` configures the reference data. A **commodity** captures the grading and marketing standards for a grain type. Its `symbol` is one of `CORN`, `SOYBEANS`, or `WHEAT`, and must be unique across all commodities; a symbol that duplicates an existing commodity is rejected with `ERR_INVALID_REQUEST` (HTTP 422). The `test_weight_lbs_per_bushel` is the reference pounds-per-bushel used to convert clean weight into bushels (corn, for instance, uses 56). The `base_moisture_pct` is the moisture threshold at or below which no shrink or drying applies; above it, two charges kick in. The `shrink_pct_per_point` is the percent of clean weight removed for each moisture point above base, and `drying_cents_per_point_per_bushel` is the drying charge expressed in cents per moisture point per dry bushel. Finally, `futures_contract_bushels` is the bushels per exchange futures contract used when hedging, supplied as a non-negative integer and defaulting to 5000 when omitted at creation.

A **price board** is the cooperative's posted bid for a commodity at a point in time. The merchandiser supplies the `commodity_id` it prices, the board `futures_price` in dollars per bushel, and the `cash_basis` in dollars per bushel (signed — a value of negative thirty cents means thirty cents under futures). On posting, the system computes the board's `cash_price` as the futures price plus the cash basis, and marks the new board's `is_current` flag. A board's `is_current` is true only when it is the board with the greatest `created_at` among all boards for its `commodity_id`; posting a new board for a commodity makes it the current board and supersedes whatever board was current before.

A **member** is a co-op patron. The merchandiser supplies only the member's `name`; the three ledger fields — `equity_credit_dollars` (accumulated non-cash patronage equity), `cash_paid_dollars` (lifetime cash settlement plus cash patronage paid out), and `net_priced_bushels` (the running total of priced bushels in the open patronage period) — all initialize to 0 and are maintained by the system as grain settles and patronage closes.

### 3.2. Inbound: Weighing, Grading, and Drying Reservations

When a truck arrives, a `GradeClerk` weighs in the load by creating a **scale ticket**, which is born in `WEIGHED` status. The clerk supplies the `member_id` delivering the load, the `commodity_id` delivered, the `gross_weight_lbs` of the loaded truck, the `tare_weight_lbs` of the empty truck, the measured `moisture_pct`, the `deposit_account_type` naming the storage program the grain will enter (`DELAYED_PRICE` or `WAREHOUSE_RECEIPT`), and optionally the `dockage_pct` (foreign material as a percent of net weight, defaulting to 0). The gross weight must exceed the tare weight or the ticket is refused with `ERR_INVALID_REQUEST`.

Grading a weighed ticket is the heart of the inbound flow and advances the ticket from `WEIGHED` to `GRADED`. A ticket may only be graded out of `WEIGHED`; attempting to grade a ticket in any other status is rejected with `ERR_INVALID_STATE`. (A current price board for the ticket's commodity is expected as an operational matter, but grading itself does not require one.) The grade computation derives, in a pinned evaluation order, every weight-and-bushel figure on the ticket. First the `net_weight_lbs` is the gross weight minus the tare weight. Then dockage is removed: the dockage pounds are the net weight multiplied by the dockage percent divided by 100, and the `clean_weight_lbs` is the net weight minus those dockage pounds — **dockage is removed first**. The `moisture_points` are the measured moisture percent minus the commodity's base moisture, but never less than zero (at or below base moisture, moisture points are 0, so neither shrink nor drying applies). The `wet_bushels` are the clean weight divided by the commodity's test weight per bushel, rounded to 4 decimal places. Moisture shrink is then applied to the already-dockage-reduced clean weight: the dry weight in pounds is the clean weight multiplied by the quantity (1 minus the commodity's shrink percent per point divided by 100, that result multiplied by the moisture points) — **shrink is applied after dockage**, on the clean weight. The `net_dry_bushels` are that dry weight divided by the test weight per bushel, rounded to 4 decimal places. The `drying_charge_dollars` are the net dry bushels multiplied by the moisture points, multiplied by the commodity's drying cents per point per bushel, divided by 100, rounded to 2 decimal places. The order is load-bearing: removing dockage first and then applying shrink to the clean weight yields a different `net_dry_bushels` than the reverse, and only this order is correct.

Grading does not merely fill in numbers; it creates the grain's home in storage. The same grade action creates a **storage position** whose `program` equals the ticket's deposit account type, whose `bushels` and `bushels_available` are both set to the computed net dry bushels, whose `status` is `STORED`, whose `storage_start_date` is the current logical-clock time, and whose `member_id`, `commodity_id`, and `scale_ticket_id` are copied from the ticket. The ticket's `storage_position_id` is set to the new position's id (it is null until grading), and the ticket moves to `GRADED`, bumping the ticket's version.

A weighed ticket that should not have been accepted can be voided by a `GradeClerk`, moving it from `WEIGHED` to `VOIDED`. Only a `WEIGHED` ticket may be voided — once a ticket is graded and a storage position exists, the ticket can no longer be voided and the attempt returns `ERR_INVALID_STATE`. (When a ticket is voided after a position somehow exists but before any position activity, the owning position is correspondingly carried to `VOIDED` by the system; in normal operation a void only happens in `WEIGHED`, before any position exists.)

Wet loads frequently need to pass through a continuous-flow dryer before grading. A **dryer line** is configured by a `Merchandiser` with a `name` and a `cleanout_buffer_minutes` (the mandatory turnaround between consecutive batches, defaulting to 30). A `GradeClerk` reserves a drying window by creating a **drying reservation** against a `dryer_line_id` for a particular wet load's `scale_ticket_id`, supplying the batch `window_start` and `window_end`. A reservation is born `RESERVED`. The dryer geometry is a **closed interval with a mandatory buffer**: let the buffer be the line's cleanout-buffer minutes. A new window conflicts with an existing reserved reservation on the same dryer line when the new window's start is at or before the existing window's end plus the buffer, and the new window's end plus the buffer is at or after the existing window's start. In plain terms, two batches on the same line must be separated by strictly more than the buffer; windows that merely touch, or that fall within the buffer of each other, are rejected with `ERR_RESOURCE_WINDOW_CONFLICT`. Only reservations in `RESERVED` status occupy the line; a released window is free. Releasing a reservation by a `GradeClerk` moves it from `RESERVED` to `RELEASED`, after which its window no longer occupies the line and stops conflicting with new reservations.

### 3.3. Storage Programs, Accrual Freezing, and Warehouse Receipts

Every graded load lands in one of two storage programs, recorded as the position's `program`. A `DELAYED_PRICE` position accrues a per-day storage charge against the grain held there; a `WAREHOUSE_RECEIPT` position is a flat-fee program that accrues no per-day storage. A position's lifecycle status runs `STORED` while grain is held, may pause at `CHARGE_FROZEN`, returns to `STORED`, reaches `DEPLETED` when its available bushels are fully drawn down, or is carried to `VOIDED` if its originating ticket is voided before any activity.

A `Merchandiser` may pause storage accrual on a delayed-price position by freezing its charge, moving the position from `STORED` to `CHARGE_FROZEN`. Two conditions gate the freeze: the position must currently be `STORED` (otherwise `ERR_INVALID_STATE`), and its program must be `DELAYED_PRICE`. A `WAREHOUSE_RECEIPT` position does not accrue per-day storage and cannot be charge-frozen; attempting to freeze it is rejected with `ERR_PROGRAM_MISMATCH`. While frozen, accrual pauses from the clock instant of the freeze. Unfreezing the charge moves the position from `CHARGE_FROZEN` back to `STORED`: the whole days the position spent frozen are added to its cumulative `frozen_days` counter, and accrual resumes. A position must be `CHARGE_FROZEN` to be unfrozen, else `ERR_INVALID_STATE`.

For warehouse-receipt grain, a `Merchandiser` issues a **warehouse receipt** — a negotiable document — by supplying the `storage_position_id`. On issue, the receipt records the holder's `member_id` and a snapshot of the position's `bushels` as its own `bushels`, takes status `ISSUED`, and the position's `receipt_id` is set to the new receipt. A receipt's status runs from `ISSUED` to `CANCELLED`; cancellation happens automatically when the documented position is fully loaded out or otherwise depleted, as described below. (A storage position's `receipt_id` is only ever populated for warehouse-receipt positions and stays null for delayed-price positions.)

### 3.4. Marketing Contracts and Price Fixing

A `Merchandiser` markets a member's grain by creating a **contract** that commits a quantity of bushels at a price, with the price assembled from two legs — a futures leg and a basis leg — whose timing depends on the `contract_type`. The merchandiser supplies the `member_id`, the `commodity_id`, the `contract_type` (`CASH`, `FORWARD`, `BASIS`, or `HTA`), and the `contracted_bushels` the member commits. Depending on type, one or both price legs may be supplied at create as `futures_leg` and `basis_leg`. A `FORWARD` contract requires both legs at create; a `BASIS` contract requires the `basis_leg` (the basis is locked early, the futures floats); an `HTA` contract requires the `futures_leg` (the futures is locked early, the basis floats); a `CASH` contract requires neither leg at create. A contract is born `OPEN`. For a `FORWARD`, because both legs are known at create, its `net_price` is computed immediately as the futures leg plus the basis leg, but it stays `OPEN` (it does not pass through price-fixing) until a settlement carries it forward. The `priced_bushels` field starts at 0 and accumulates as settlements are applied.

The remaining contract types reach their full price through a **fix-price** action by a `Merchandiser`, which moves the contract from `OPEN` to `PRICED`. Fix-price reads the missing leg(s) from the current price board for the contract's commodity, so a current board must exist or the action is rejected with `ERR_NO_CURRENT_PRICE`. Only the open leg for the contract's type may be fixed, and a leg already set cannot be fixed again — a double-fix is rejected with `ERR_LEG_ALREADY_FIXED`. For a `BASIS` contract, fixing sets the `futures_leg` from the board's futures price (the basis leg was locked at create); the member was exposed to futures moves, and the late leg is the futures leg taken from the board at fixing. For an `HTA` contract, fixing sets the `basis_leg` from the board's cash basis (the futures leg was locked at create); the member was exposed to basis moves, and the late leg is the basis leg taken from the board at fixing. For a `CASH` contract, fixing sets both legs from the current board — the futures leg from the board's futures price and the basis leg from the board's cash basis. In every case the `net_price` is then computed as the futures leg plus the basis leg, carried to 4 decimal places, and the contract becomes `PRICED`. Because a basis contract takes its late leg from futures while an HTA contract takes its late leg from basis, the very same board history applied to a `BASIS` contract and to an `HTA` contract produces different net prices. A contract may only be fixed out of `OPEN`; fixing a contract in any other status is rejected with `ERR_INVALID_STATE`. A `FORWARD` contract never passes through fix-price — though it is born `OPEN`, both its legs are already set at create, so a fix-price attempt against it is rejected with `ERR_LEG_ALREADY_FIXED`.

A `Merchandiser` may cancel a contract that has not yet had grain applied to it, moving it from `OPEN` or `PRICED` to `CANCELLED`. Cancellation requires that the contract's `priced_bushels` be exactly 0 — that no settled settlement has been applied. If applied settlement bushels exist, the cancel is refused with `ERR_CONTRACT_HAS_SETTLEMENTS`. A contract not in `OPEN` or `PRICED` cannot be cancelled (`ERR_INVALID_STATE`).

A contract reaches its terminal `SETTLED` status by accumulation, not by an explicit call: when settled settlements have filled the contract's `priced_bushels` up to its `contracted_bushels`, the contract is carried to `SETTLED` as part of that settlement's posting cascade. A forward contract, which lived in `OPEN` with both legs fixed, likewise reaches `SETTLED` when a settlement against it is posted that completes its quantity.

### 3.5. Settlement: Pricing Stored Bushels into Proceeds

A `SettlementOfficer` realizes value by **drafting a settlement** that applies bushels from a storage position to a contract. The draft supplies the `contract_id` being settled against, the `storage_position_id` supplying the bushels, the `priced_bushels` drawn and priced, and optionally the `storage_basis` (`ESTIMATE` or `ACTUAL`, defaulting to `ACTUAL`) selecting which storage-charge variant to apply. A settlement is born `DRAFT` and carries no ledger effects until it is posted. While a settlement is `DRAFT`, its three dollar figures — `gross_proceeds_dollars`, `storage_charge_dollars`, and `net_proceeds_dollars` — are not stored statically but are recomputed on demand whenever the settlement is read (on the create response, on a single-settlement get, and on each settlement in a list), using the same formulas the post applies (Section 3.5 / Section 3.6): from the contract's current `net_price`, the position, the settlement's chosen `storage_basis`, and the current logical-clock time. This recomputation only runs when the draft's contract has a non-null `net_price`; if the contract is not yet priced (its `net_price` is still null), the three figures read as null. Once a settlement is posted (`SETTLED`), these three figures are frozen at the values computed at post time and are read back as stored — they are not recomputed thereafter; a cancelled (`CANCELLED`) settlement, never posted, carries them as null. A draft may be cancelled by a `SettlementOfficer` while still `DRAFT`, moving it to `CANCELLED` with no ledger impact since none was ever applied.

**Posting** a draft settlement is the system's central reconciliation event and moves the settlement from `DRAFT` to `SETTLED`. The settlement must be `DRAFT` (`ERR_INVALID_STATE`). The post is optimistic-concurrency-guarded on the storage position, so the request carries `expected_storage_position_version` as described in Section 2.10. Several business checks guard the post. The contract and the storage position must share both `commodity_id` and `member_id`; if they do not, the post is rejected with `ERR_COMMODITY_MISMATCH`. The contract must be ready to settle — either `PRICED`, or a `FORWARD` contract with both legs fixed — otherwise `ERR_CONTRACT_NOT_PRICED`. The bushels drawn must not exceed the contract's remaining unfilled room, that is the contracted bushels minus the already-priced bushels; exceeding it yields `ERR_CONTRACT_OVERFILL`. And the bushels drawn must not exceed the position's `bushels_available`; exceeding it yields `ERR_INSUFFICIENT_BUSHELS`.

Once the guards pass, the post computes the proceeds and applies a cascade of ledger effects. The `gross_proceeds_dollars` are the priced bushels multiplied by the contract's net price, to 2 decimal places. The `storage_charge_dollars` are computed per the chosen storage-basis variant (detailed in Section 3.6), to 2 decimal places. The `net_proceeds_dollars` are the gross proceeds minus the storage charge, to 2 decimal places. The cascade then runs: the position's `bushels_available` is reduced by the priced bushels, and if that reaches 0 the position is carried to `DEPLETED` (which in turn cancels any issued warehouse receipt on that position); the contract's `priced_bushels` is increased by the priced bushels, and if that reaches the contracted bushels the contract is carried to `SETTLED`; if the position's owning scale ticket is still `GRADED`, it is advanced to `SETTLED_IN` (marking the grain accepted into the priced ledger); the member's `cash_paid_dollars` is increased by the net proceeds and the member's `net_priced_bushels` is increased by the priced bushels; the storage position's `version` is incremented by 1; and the settlement itself becomes `SETTLED`, incrementing its version. Each of these is part of the same atomic post.

### 3.6. Storage Charges: Estimate versus Actual

The storage charge a settlement deducts depends on the position's program and on the chosen `storage_basis` variant. The per-bushel-per-day storage rate is five hundredths of a cent — that is, $0.0005 per bushel per day — and grain enjoys a grace period of 30 days from its storage start before any storage charge accrues.

For a `WAREHOUSE_RECEIPT` position there is no per-day accrual at all: the storage charge is 0, because warehouse-receipt grain is a flat-fee program.

For a `DELAYED_PRICE` position, the charge counts chargeable days from the end of the grace period to today. The grace-end date is the position's `storage_start_date` plus 30 days, and "today" is the current logical-clock date. The chargeable calendar days are the whole days from grace-end to today, but never less than zero (grain still inside its grace window accrues nothing). The two variants then diverge in how they treat days the position spent frozen. The **estimate** variant is forward-looking: it charges the full grace-end-to-today span and ignores frozen days entirely, as if the position were never paused — its chargeable days equal the chargeable calendar days. The **actual** variant is chronological: it subtracts the position's accumulated `frozen_days` from the chargeable calendar days (never going below zero) — its chargeable days equal the chargeable calendar days minus the frozen days, floored at zero. In both variants the `storage_charge_dollars` are the settlement's priced bushels multiplied by the rate multiplied by the chargeable days, rounded to 2 decimal places. For a position that was frozen for part of its storage span, the estimate and actual variants therefore produce different charges; for a position never frozen they coincide.

### 3.7. Load-Out and Shipment

A `ShippingClerk` moves priced or redeemed grain off the elevator through a **shipment**. Scheduling a shipment reserves a load-out window on a physical bay. A **load-out bay** is created by a `Merchandiser` with just a `name` (for example, `BAY-1`). The shipping clerk schedules a shipment by supplying the `commodity_id` shipped, the `storage_position_id` loaded out, the `loadout_bay_id` reserved, the `bushels` loaded onto the shipment, and the bay reservation window `bay_window_start` and `bay_window_end`. A shipment is born `SCHEDULED`.

The bay geometry is a **half-open interval**, deliberately different from the dryer geometry. A new shipment window conflicts with an existing non-cancelled shipment window on the same bay when the new window's start is before the existing window's end and the new window's end is after the existing window's start. Because the window is half-open — the end is exclusive — windows that merely touch (a new window starting exactly when an existing one ends, or ending exactly when an existing one starts) do not conflict. Only shipments in `SCHEDULED`, `LOADED`, or `SHIPPED` status occupy the bay; a cancelled shipment's window is free. A conflicting window is rejected with `ERR_RESOURCE_WINDOW_CONFLICT`.

Loading a scheduled shipment moves it from `SCHEDULED` to `LOADED` and is when bushels actually leave storage. The shipment must be `SCHEDULED` (`ERR_INVALID_STATE`); the bushels must not exceed the position's `bushels_available` (`ERR_INSUFFICIENT_BUSHELS`); and the position must be in `STORED` or `CHARGE_FROZEN` status — a `DEPLETED` or `VOIDED` position cannot be loaded from and yields `ERR_INVALID_STATE`. On load, the position's `bushels_available` is reduced by the shipment's bushels, and if that reaches 0 the position is carried to `DEPLETED` (cascading any issued warehouse receipt on the position to `CANCELLED`); the shipment's version is incremented. Marking a loaded shipment shipped moves it from `LOADED` to `SHIPPED`; it must be `LOADED` to ship (`ERR_INVALID_STATE`).

A scheduled shipment may be cancelled by a `ShippingClerk`, moving it from `SCHEDULED` to `CANCELLED`; no bushels were drawn, so there is no ledger reversal, and the bay window the shipment was holding is released and no longer conflicts with new reservations. A `LOADED` shipment cannot be cancelled (`ERR_INVALID_STATE`).

### 3.8. Hedging: Marks, Margin Calls, and Mark-to-Market

A `RiskManager` manages the elevator's own price exposure through **hedge positions** on the futures market. Opening a position requires the `commodity_id` hedged, the `side` (`SHORT` or `LONG`), the number of `contracts` held (a non-negative integer), and the `entry_futures_price` at which the position is opened. On open, the `posted_margin_dollars` initialize to the initial margin total, which is two thousand dollars per contract — so $2,000 multiplied by the number of contracts — and the position takes status `OPEN`. The `mark_futures_price` starts null until the first mark, and the computed figures `unrealized_pnl_dollars`, `account_equity_dollars`, and `margin_call_dollars` start at 0.

Applying a **mark** to an open position records the latest `mark_futures_price` and recomputes the position's profit and loss. The contract size is the commodity's `futures_contract_bushels`. The initial margin total is $2,000 per contract times the number of contracts, and the maintenance margin total is $1,500 per contract times the number of contracts. For a `SHORT` position, the `unrealized_pnl_dollars` are the entry futures price minus the mark futures price, that difference multiplied by the contract size and by the number of contracts, rounded to 2 decimal places. For a `LONG` position, the unrealized profit and loss are the mark futures price minus the entry futures price, multiplied by the contract size and the number of contracts, rounded to 2 decimal places. The `account_equity_dollars` are the posted margin plus the unrealized profit and loss. A mark may only be applied to a position in `OPEN` status.

A margin call is triggered when, after applying the new mark, the account equity is strictly less than the maintenance margin total — the comparison is strict, so equity exactly equal to the maintenance total does not trigger a call. When the call triggers, the position moves from `OPEN` to `MARGIN_CALL`, and the `margin_call_dollars` are set to the initial margin total minus the account equity (the amount needed to restore the account to its initial margin). When the recomputed account equity is at or above the maintenance margin total, the position stays `OPEN`, and the `margin_call_dollars` remain 0. Either outcome bumps the position's version.

**Meeting a margin call** is performed by a `RiskManager` and moves the position from `MARGIN_CALL` back to `OPEN`. The request supplies a `deposit_dollars` amount and is optimistic-concurrency-guarded on the hedge position via `expected_hedge_position_version` as described in Section 2.10. The position must be in `MARGIN_CALL` (`ERR_INVALID_STATE`), and the deposit must be at least the outstanding `margin_call_dollars`; a deposit short of the call is rejected with `ERR_MARGIN_CALL_UNMET`. On a sufficient deposit, the deposit is added to `posted_margin_dollars`, the account equity is recomputed, the `margin_call_dollars` are reset to 0, the position returns to `OPEN`, and its version increments.

A `RiskManager` may **close** a position from either `OPEN` or `MARGIN_CALL`, moving it to the terminal `CLOSED` status (closing out of a margin call represents a liquidation under an unmet call).

### 3.9. Year-End Patronage Distribution

At fiscal year end, a `Merchandiser` distributes the cooperative's earnings back to its members in proportion to the grain each marketed. The merchandiser first opens a **patronage period** with a `label` (such as `FY2026`), a `pool_dollars` total to distribute, and a `qualified_cash_pct` naming the fraction of each member's allocation paid in cash with the remainder credited as equity (for example, 0.20). The period is born `OPEN`.

**Closing** the period moves it from `OPEN` to `CLOSED` and posts the allocations. The period must be `OPEN` (`ERR_INVALID_STATE`). The period's `total_bushels` is set to the sum of `net_priced_bushels` across all members, and this total must be strictly greater than 0 or the close is refused with `ERR_EMPTY_PATRONAGE_POOL`. The eligible members are those whose `net_priced_bushels` is greater than 0, ordered by `net_priced_bushels` descending, with ties broken by `created_at` ascending — the member's `id` is never used as a tie-break. For each eligible member, the system creates a `PatronageAllocation` recording the `patronage_period_id`, the `member_id`, the member's `member_bushels` (its net priced bushels at close), and three dollar figures. The `allocation_dollars` are the pool dollars multiplied by the member's bushels divided by the total bushels, rounded to 2 decimal places. The raw cash share is the allocation dollars multiplied by the qualified cash percent; the `cash_dollars` are that raw cash share **floored down to whole cents** (rounded down to 2 decimal places); and the `equity_dollars` are the allocation dollars minus the cash dollars, to 2 decimal places.

Because each member's cash share is floored, a small rounding residue accumulates across the membership. That residue — the **cash remainder** — is computed as the sum of all allocation dollars multiplied by the qualified cash percent and rounded to 2 decimal places, minus the sum of every member's floored cash dollars. The entire cash remainder is assigned to the first member in the eligible order (the member with the greatest net priced bushels, ties broken by earliest `created_at`): that lead member's `cash_dollars` is increased by the remainder and its `equity_dollars` is decreased by the remainder, so the allocation is conserved. As each allocation is posted, the owning member is credited — the member's `equity_credit_dollars` is increased by the allocation's equity dollars and the member's `cash_paid_dollars` is increased by the allocation's cash dollars. When the close completes, the period's version increments.

A member's posted allocations can be listed both under the member and under the period, supporting reconciliation from either side.

## 4. Endpoint Definitions

All endpoints are mounted under the `/commodities` prefix (the logical-clock facility under `/_clock`). Resource creation endpoints return HTTP 201 with the created resource; reads, list endpoints, and state-transition or mutation endpoints return HTTP 200 with the affected or retrieved resource. List endpoints return an array payload; all others return a single object (the clock-set facility returns no resource payload). Every request must carry the `X-User-ID` and `X-User-Role` headers.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/commodities` | Create a commodity reference (grade standards, shrink, drying, futures size) | Merchandiser |
| GET | `/commodities/{id}` | Get a commodity | Merchandiser, GradeClerk, SettlementOfficer, RiskManager, ShippingClerk |
| POST | `/commodities/price-boards` | Post a new price board; becomes the current board for its commodity | Merchandiser |
| GET | `/commodities/price-boards/{id}` | Get a price board | Merchandiser, GradeClerk, SettlementOfficer, RiskManager, ShippingClerk |
| GET | `/commodities/price-boards` | List price boards, optionally filtered by commodity (`commodity_id`) and/or by `is_current` | Merchandiser, GradeClerk, SettlementOfficer, RiskManager, ShippingClerk |
| POST | `/commodities/members` | Create a co-op member | Merchandiser |
| GET | `/commodities/members/{id}` | Get a member with patronage ledger fields | Merchandiser, GradeClerk, SettlementOfficer, RiskManager, ShippingClerk |
| GET | `/commodities/members/{id}/allocations` | List patronage allocations posted to a member | Merchandiser, SettlementOfficer |
| POST | `/commodities/scale-tickets` | Weigh in a load (create a scale ticket in WEIGHED) | GradeClerk |
| GET | `/commodities/scale-tickets/{id}` | Get a scale ticket with grade computations | Merchandiser, GradeClerk, SettlementOfficer |
| GET | `/commodities/scale-tickets` | List scale tickets, optionally filtered by member, commodity, or storage position | Merchandiser, GradeClerk, SettlementOfficer |
| POST | `/commodities/scale-tickets/{id}/grade` | Grade a WEIGHED ticket and create the storage position | GradeClerk |
| POST | `/commodities/scale-tickets/{id}/void` | Void a WEIGHED ticket | GradeClerk |
| GET | `/commodities/storage-positions/{id}` | Get a storage position | Merchandiser, GradeClerk, SettlementOfficer, ShippingClerk |
| GET | `/commodities/storage-positions` | List storage positions, optionally filtered by member, commodity, scale ticket, or receipt | Merchandiser, GradeClerk, SettlementOfficer, ShippingClerk |
| POST | `/commodities/storage-positions/{id}/freeze-charge` | Pause per-day storage accrual on a DELAYED_PRICE position | Merchandiser |
| POST | `/commodities/storage-positions/{id}/unfreeze-charge` | Resume accrual; bank frozen whole days | Merchandiser |
| POST | `/commodities/warehouse-receipts` | Issue a warehouse receipt for a WAREHOUSE_RECEIPT position | Merchandiser |
| GET | `/commodities/warehouse-receipts/{id}` | Get a warehouse receipt | Merchandiser, SettlementOfficer, ShippingClerk |
| GET | `/commodities/warehouse-receipts` | List warehouse receipts, optionally filtered by storage position or member | Merchandiser, SettlementOfficer, ShippingClerk |
| POST | `/commodities/contracts` | Create a marketing contract (CASH/FORWARD/BASIS/HTA) | Merchandiser |
| GET | `/commodities/contracts/{id}` | Get a contract | Merchandiser, SettlementOfficer |
| GET | `/commodities/contracts` | List contracts, optionally filtered by member or commodity | Merchandiser, SettlementOfficer |
| POST | `/commodities/contracts/{id}/fix-price` | Fix the open leg(s) from the current price board | Merchandiser |
| POST | `/commodities/contracts/{id}/cancel` | Cancel an OPEN or PRICED contract with no applied settlements | Merchandiser |
| POST | `/commodities/settlements` | Draft a settlement applying bushels from a position to a contract | SettlementOfficer |
| GET | `/commodities/settlements/{id}` | Get a settlement with computed proceeds and storage charge | Merchandiser, SettlementOfficer |
| GET | `/commodities/settlements` | List settlements, optionally filtered by contract or storage position | Merchandiser, SettlementOfficer |
| POST | `/commodities/settlements/{id}/post` | Post a DRAFT settlement; applies ledger cascades (OCC-guarded on the position) | SettlementOfficer |
| POST | `/commodities/settlements/{id}/cancel` | Cancel a DRAFT settlement | SettlementOfficer |
| POST | `/commodities/loadout-bays` | Create a physical load-out bay | Merchandiser |
| GET | `/commodities/loadout-bays/{id}` | Get a load-out bay | Merchandiser, ShippingClerk |
| GET | `/commodities/loadout-bays` | List load-out bays | Merchandiser, ShippingClerk |
| POST | `/commodities/dryer-lines` | Create a dryer line with its cleanout buffer | Merchandiser |
| GET | `/commodities/dryer-lines/{id}` | Get a dryer line | Merchandiser, GradeClerk |
| GET | `/commodities/dryer-lines` | List dryer lines | Merchandiser, GradeClerk |
| POST | `/commodities/drying-reservations` | Reserve a drying window on a dryer line for a wet load | GradeClerk |
| GET | `/commodities/drying-reservations/{id}` | Get a drying reservation | Merchandiser, GradeClerk |
| GET | `/commodities/drying-reservations` | List drying reservations, optionally filtered by dryer line or scale ticket | Merchandiser, GradeClerk |
| POST | `/commodities/drying-reservations/{id}/release` | Release a reserved drying window | GradeClerk |
| POST | `/commodities/shipments` | Schedule a load-out; reserves a half-open bay window | ShippingClerk |
| GET | `/commodities/shipments/{id}` | Get a shipment | Merchandiser, ShippingClerk |
| GET | `/commodities/shipments` | List shipments, optionally filtered by commodity, storage position, or loadout bay | Merchandiser, ShippingClerk |
| POST | `/commodities/shipments/{id}/load` | Load a scheduled shipment; draws bushels from the position | ShippingClerk |
| POST | `/commodities/shipments/{id}/ship` | Mark a loaded shipment shipped | ShippingClerk |
| POST | `/commodities/shipments/{id}/cancel` | Cancel a scheduled shipment | ShippingClerk |
| POST | `/commodities/hedge-positions` | Open a hedge (futures) position; posts initial margin | RiskManager |
| GET | `/commodities/hedge-positions/{id}` | Get a hedge position with margin figures | Merchandiser, RiskManager |
| GET | `/commodities/hedge-positions` | List hedge positions, optionally filtered by commodity | Merchandiser, RiskManager |
| POST | `/commodities/hedge-positions/{id}/mark` | Apply a mark-to-market price; may trigger a margin call | RiskManager |
| POST | `/commodities/hedge-positions/{id}/meet-call` | Deposit margin to cure a call (OCC-guarded on the position) | RiskManager |
| POST | `/commodities/hedge-positions/{id}/close` | Close a hedge position | RiskManager |
| POST | `/commodities/patronage-periods` | Open a patronage distribution period | Merchandiser |
| GET | `/commodities/patronage-periods/{id}` | Get a patronage period | Merchandiser, SettlementOfficer |
| GET | `/commodities/patronage-periods/{id}/allocations` | List allocations posted under a patronage period | Merchandiser, SettlementOfficer |
| POST | `/commodities/patronage-periods/{id}/close` | Close a period and post pro-rata patronage allocations | Merchandiser |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Merchandiser |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_COMMODITY_MISMATCH | 409 |
| ERR_LEG_ALREADY_FIXED | 409 |
| ERR_NO_CURRENT_PRICE | 409 |
| ERR_CONTRACT_NOT_PRICED | 409 |
| ERR_CONTRACT_OVERFILL | 409 |
| ERR_INSUFFICIENT_BUSHELS | 409 |
| ERR_PROGRAM_MISMATCH | 409 |
| ERR_MARGIN_CALL_UNMET | 409 |
| ERR_CONTRACT_HAS_SETTLEMENTS | 409 |
| ERR_EMPTY_PATRONAGE_POOL | 409 |
| ERR_RESOURCE_WINDOW_CONFLICT | 409 |
| ERR_STALE_VERSION | 412 |

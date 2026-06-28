# Scrap Metal Recycling API — Product Requirements Document

## 1. Introduction

A scrap metal recycling yard runs on a tight loop of physical material and financial settlement: a vehicle drives onto the inbound scale fully loaded, its material is sorted into ferrous and non-ferrous grades and valued against a published spot price, the empty vehicle is weighed out, and — provided nothing about the seller or the material trips a theft-prevention safeguard — the seller is paid in cash or by check. Each transaction is a small ledger event, but the yard's regulatory exposure is large: cumulative cash payouts to a single seller drive IRS 1099 reporting, suspected stolen material must be impounded and the seller frozen, and the people who clear a theft hold must not be the same people who release the money. Downstream, sorted material accumulates in roll-off containers that are dispatched to a mill, where the yard's estimated valuation is reconciled against the mill's actual settlement and, where the yard has hedged the commodity on the futures market, the hedge position is realized.

This document specifies the backend API that runs that operation end to end. It governs seven peer resources — sellers, commodity prices, scale tickets (with their material line items), payouts, containers, mill shipments, and hedge positions, plus the theft reports that freeze and unfreeze sellers — and the strict workflow, valuation, and compliance rules that bind them. The system serves a yard staff segregated by duty: scale operators, payout clerks, yard managers, settlement accountants, and compliance officers. The requirements below define the precise contract every client and every implementation must honor: response shapes, valuation arithmetic to the cent, state transitions, optimistic-concurrency guards on shared physical and financial resources, and the full catalogue of rejection codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request that mutates state, and every read other than the open list/detail GET endpoints, must carry two headers identifying the caller: `X-User-ID` and `X-User-Role`. `X-User-ID` is the caller's unique identifier; `X-User-Role` names the caller's role. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed and the role is recognized but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

There are exactly five roles, spelled precisely as follows:

- **`WeighMaster`** — operates the scale. Registers sellers, opens scale tickets, adds material line items, weighs material out, places and clears theft holds, releases tickets, and files ticket-driven theft reports.
- **`PayoutClerk`** — disburses funds. Creates, settles, and voids payouts. Bound by segregation of duties against whoever cleared a ticket's theft hold.
- **`YardManager`** — manages prices and containers. Publishes commodity prices, stages and dispatches roll-off containers, and may create mill shipments.
- **`SettlementAccountant`** — runs mill settlement and commodity hedging. Settles mill shipments, opens and closes hedge positions, and realizes hedge profit and loss. May also create mill shipments.
- **`ComplianceOfficer`** — the theft-prevention authority. Files and clears theft reports, bans sellers, and registers sellers.

For all five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it where a workflow demands it — for example, the `WeighMaster` who clears a theft hold has their `X-User-ID` written to the ticket's `theft_hold_released_by` field — but the server does not compare `X-User-ID` to any entity's `id` for ownership. The one place `X-User-ID` carries downstream meaning is the segregation-of-duties check on payout creation, described in §3.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1, and may be no larger than 100. `offset` defaults to 0 and may be no smaller than 0. A value outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Every list response orders its rows by `created_at` ascending — oldest first. The `meta` block of a list response carries, in addition to the standard request fields, the four pagination fields: `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filter before pagination, and `has_more` indicating whether rows remain beyond the returned page.

### 2.4. Common Resource Properties and Versioning

Every resource carries a server-minted `id`: a UUID with no type prefix, generated by the server and never supplied by the client. Resources also carry a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, set once at creation.

Most resources are mutable and additionally carry an `updated_at` timestamp (same format as `created_at`, refreshed on every mutation) and an integer `version` that begins at 1 and increments by exactly 1 on each mutation. These mutable resources are `Seller`, `CommodityPrice`, `ScaleTicket`, `Payout`, `Container`, `MillShipment`, `HedgePosition`, and `TheftReport`. The sole exception is `TicketLineItem`, which is append-only: once created it is never mutated. A `TicketLineItem` therefore carries only `id` and `created_at` — it has no `updated_at` and no `version` field.

Whenever a transition or write changes a mutable resource, `updated_at` is refreshed and `version` is incremented. Where a side effect of one operation mutates a *second* resource — for example, releasing a ticket adds weight to a container, or settling a payout advances a seller's cash ledger — that second resource's `updated_at` and `version` advance as well.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and computed as integer **cents**; there are no fractional-cent values in stored data. Weights are pounds and may be fractional. Wherever a weight is multiplied by a per-pound price, the product is rounded to a whole number of cents using **round-half-up** (a value of exactly one-half cent rounds away from zero, upward). The rounding discipline is strict about order: where a total spans several material lines, each line's cents value is rounded first and the rounded line values are then summed — never the reverse. The same per-line-round-then-sum order governs the mill-side estimate. Plain subtractions of two already-rounded cent amounts (such as a settlement variance) are exact integer arithmetic and involve no further rounding.

### 2.6. Resource Existence and Path Validation

Path parameters are validated left to right. A request that names a non-existent resource in its path — or that references, in its body, a foreign-key target that does not exist (a `seller_id`, `container_id`, `ticket_id`, `hedge_position_id`, or `commodity_price_id` pointing at nothing) — is rejected with `ERR_NOT_FOUND` (HTTP 404). Detail and list reads are available for every resource, including reverse lookups: the line items of a ticket and the line items referencing a given commodity price are both reachable, as are theft reports filtered by their `seller_id` or `ticket_id`.

### 2.7. Optimistic Concurrency on Shared Physical and Financial Resources

Two operations in this system act on a resource that other operations are simultaneously advancing, and both are guarded by optimistic concurrency control. In each case the client must submit the `version` it last observed for the parent resource, and the server rejects the write if that resource's `version` has moved on since.

**Container dispatch.** Dispatching a container requires the request to carry `expected_container_version`, holding the `version` the client last read from that container. Between a client reading a container and dispatching it, a ticket release can legitimately load additional net weight onto the same roll-off, which increments the container's `version`. A dispatch arriving with the pre-load version is therefore acting on a stale view of the container's capacity and is rejected with `ERR_STALE_CONTAINER_VERSION` (HTTP 412); the dispatch does not occur. Only when `expected_container_version` equals the container's current `version` does the dispatch proceed.

**Mill-shipment settlement against a hedge.** When a mill shipment is settled with a linked hedge position, the request must carry `expected_hedge_version`, holding the `version` the client last read from that hedge. Another shipment's settlement can legitimately realize weight against the same hedge in the interim, advancing the hedge's `version` (and possibly closing it). A settlement arriving with the stale hedge version is rejected with `ERR_STALE_HEDGE_VERSION` (HTTP 412), so it cannot over-realize a position whose capacity has already been consumed. A settlement with no linked hedge does not carry `expected_hedge_version` and is not subject to this check.

No other endpoint takes a version field.

### 2.8. Validation Ordering

When several conditions could reject the same request, they are evaluated in a fixed order so that the returned `error_id` is deterministic. Authentication is checked first: a missing or unknown-role caller yields `ERR_UNAUTHENTICATED` before anything else. Role authorization is checked next, yielding `ERR_FORBIDDEN_ROLE`. Resource existence is checked third — every path id and every foreign-key reference must resolve, or `ERR_NOT_FOUND` is returned. For a state-transition endpoint, the target's current state is checked fourth: if the requested transition is not defined from the resource's present state, `ERR_INVALID_STATE` (HTTP 409) is returned.

Only after those four gates pass are the domain-specific business rules evaluated. Their relative ordering, where two could fire on one endpoint, follows the priority sequence: segregation of duties, then seller-frozen checks, then container-category match, then grade-active check, then weight validity, then container capacity, then hedge over-realization, then the 1099 TIN gate, then optimistic-concurrency version match, and finally generic request well-formedness. The body-shape check (`ERR_INVALID_REQUEST`) is the lowest-priority business check and only surfaces when no higher-priority rule has already rejected the request. The specific trigger conditions for each of these business rules are described alongside the workflows they guard in §3.

## 3. Business Logic & Workflows

### 3.1. Sellers, Identity Capture, and the Theft-Prevention Lifecycle

Every transaction begins with a registered seller. A `WeighMaster` or a `ComplianceOfficer` registers one by supplying the seller's `legal_name` exactly as printed on a government ID, the `id_type` of that document — one of `DRIVERS_LICENSE`, `STATE_ID`, or `PASSPORT` — and the `id_number` from it, which the yard retains for theft-prevention reporting. A taxpayer identification number, `tin`, may be supplied at registration but is optional; when omitted it is stored as null and can be added later. A freshly registered seller starts in `status` `ACTIVE`, with its cumulative-cash ledger `ytd_cash_paid_cents` at 0, its `requires_1099` flag false, and its `open_theft_reports` count at 0.

A seller's `status` is one of `ACTIVE`, `FLAGGED`, or `BANNED`, and it governs whether the seller may transact. `ACTIVE` is the normal state. `FLAGGED` means there is at least one open theft report against the seller; a flagged seller cannot have a ticket released or a payout settled. `BANNED` is an administrative block applied by a `ComplianceOfficer` that prevents new weigh-outs and releases entirely. The `open_theft_reports` field is the live count of theft reports against the seller that remain in `OPEN` status; any positive value forces a weighed ticket down the reported branch rather than the release branch, and prevents a held ticket from being cleared.

Because a 1099-triggering payout may surprise a yard that registered a seller without a `tin`, a `WeighMaster` or `ComplianceOfficer` may add or correct a seller's `tin` after the fact through a dedicated patch operation that accepts only the `tin` field; this mutation increments the seller's `version`. A `ComplianceOfficer` alone may ban a seller, setting `status` to `BANNED`.

Theft prevention runs through `TheftReport` records. A `ComplianceOfficer` may file a proactive report against a seller independent of any ticket, supplying the target `seller_id`, a free-text `reason` describing the suspicion, and optionally a `ticket_id` tying the report to a specific weigh. Filing a report — whether proactively here or as the terminal outcome of a weighed ticket — creates the report in `OPEN` status, sets the seller's `status` to `FLAGGED`, and increments the seller's `open_theft_reports` by 1. A report stays `OPEN` until a `ComplianceOfficer` clears it. Clearing transitions the report from `OPEN` to `CLEARED`, decrements the seller's `open_theft_reports` by 1, and — if that count has fallen to 0 and the seller is not `BANNED` — restores the seller's `status` to `ACTIVE`. A report may only be cleared while it is `OPEN`; clearing an already-cleared report is an invalid state transition.

### 3.2. Material Grades and Spot/Mill Pricing

The yard buys and sells against a published price book of material grades, each held as a `CommodityPrice`. A `YardManager` publishes a price by supplying a `grade_code` — a material grade identifier such as `CU_BARE_BRIGHT`, `AL_CAST`, or `SHRED_STEEL` — a `category` classifying the grade as either `FERROUS` or `NON_FERROUS`, a `spot_price_cents_per_lb` (the buy price the yard pays sellers at intake, which must be at least 0), and a `mill_price_cents_per_lb` (the expected sell price to the mill, also at least 0, used later for settlement reconciliation). A newly published price has `status` `ACTIVE`.

Among all `CommodityPrice` rows whose `status` is `ACTIVE`, each `grade_code` is unique. Publishing a new price for a `grade_code` that already has an `ACTIVE` row supersedes the old one: the prior `ACTIVE` row's `status` becomes `SUPERSEDED`, and the new row becomes the live `ACTIVE` price. A `SUPERSEDED` price is retained for the historical tickets that referenced it but is rejected when a new line item tries to use it. This supersede mechanism is precisely why a line item pins the exact price row it resolved (described next): a ticket priced under last week's spot must not silently re-value when this week's price publishes.

### 3.3. The Scale Ticket: Inbound Weigh, Sorting, and Outbound Weigh

A scale ticket is the central document of a transaction and moves through `status` values `DRAFT`, `WEIGHED`, `HOLD`, `RELEASED`, `REPORTED`, and `PAID`. A `WeighMaster` opens a ticket at the inbound weigh by supplying the `seller_id` of the seller on the scale and the `gross_weight_lb` — the loaded-vehicle weight in pounds, which must be greater than 0. The ticket is created in `DRAFT` with `gross_valuation_cents` at 0. A `container_id` is not supplied here; it is associated only at release.

While the ticket is `DRAFT`, and only while it is `DRAFT`, the `WeighMaster` records the sort by adding material line items. Each line names a `grade_code` and a `weight_lb` (the pounds of that grade, which must be greater than 0). Adding a line resolves `grade_code` against the price book: it must match a `CommodityPrice` whose `status` is `ACTIVE`, otherwise the line is rejected with `ERR_GRADE_NOT_ACTIVE` (HTTP 409). On success the line is created as a `TicketLineItem` carrying its parent `ticket_id`, the supplied `grade_code` and `weight_lb`, and a system-set `commodity_price_id` pinning the exact `ACTIVE` price row resolved at this moment — the pin that protects the valuation against a later supersede. The line's `line_valuation_cents` is computed immediately as the line's `weight_lb` multiplied by that pinned row's `spot_price_cents_per_lb`, rounded half-up to whole cents. Each line is its own grade and thus its own ferrous/non-ferrous classification.

The outbound weigh finalizes the material. The `WeighMaster` weighs the empty vehicle and submits a `tare_weight_lb`. This weigh-out is only valid from `DRAFT` and only when the ticket has at least one line item; a weigh-out on a ticket with zero lines is rejected with `ERR_NO_LINE_ITEMS` (HTTP 409). The `tare_weight_lb` must be at least 0 and strictly less than the ticket's `gross_weight_lb` — the empty vehicle must weigh less than the loaded one — or the request is rejected with `ERR_INVALID_WEIGHT` (HTTP 422). The seller must additionally not be `BANNED`. On success the ticket advances `DRAFT → WEIGHED`: the system sets `net_weight_lb` to the `gross_weight_lb` minus the `tare_weight_lb` (the billable weight, null until now), and freezes `gross_valuation_cents`. The frozen gross valuation is the sum of the already-rounded `line_valuation_cents` across all the ticket's line items — each line rounded at line-creation time, then summed here — and this frozen figure is immune to any later price supersede. The weigh-out increments the ticket's `version` by 1.

### 3.4. The Theft Gate: Hold, Clear, Release, or Report

Once a ticket is `WEIGHED`, the `WeighMaster` decides its fate at the theft gate. Four transitions leave `WEIGHED`, and the choice among them is where theft prevention and segregation of duties take hold.

If the material looks suspicious but the `WeighMaster` is not yet ready to decide, a discretionary hold may be placed, moving the ticket `WEIGHED → HOLD`. A held ticket permits no payout while it remains on hold. The hold is later lifted by clearing it, which moves the ticket `HOLD → WEIGHED` — but only if the seller has zero open theft reports; if the seller still has any `OPEN` report (`open_theft_reports` greater than 0) the clear is refused with `ERR_SELLER_FROZEN` (HTTP 409). Clearing the hold records the acting `WeighMaster`'s `X-User-ID` into the ticket's `theft_hold_released_by` field. That recorded identity is the linchpin of segregation of duties: the same user who cleared a ticket's theft hold may not later approve that ticket's payout.

If the `WeighMaster` decides the material is legitimate, the ticket is released, moving `WEIGHED → RELEASED`. Release requires a `container_id` naming a roll-off the sorted material will be loaded into. The release is gated by a sequence of checks. The seller must be `ACTIVE` and free of any open theft reports; a `FLAGGED` or `BANNED` seller, or a seller with `open_theft_reports` greater than 0, blocks the release with `ERR_SELLER_FROZEN`. The named container must exist and be in `status` `STAGED`. The container's `category` must match the category of *every* line item on the ticket — a mixed-category ticket, or one whose grades do not all match the container, cannot be loaded, and the release is rejected with `ERR_CATEGORY_MISMATCH` (HTTP 409). Finally the load must fit: the container's current `loaded_weight_lb` plus the ticket's `net_weight_lb` must be at most the container's `capacity_lb`, or the release is rejected with `ERR_CONTAINER_CAPACITY_EXCEEDED` (HTTP 409). On a successful release the ticket is assigned to the container and the container's `loaded_weight_lb` increases by the ticket's `net_weight_lb`, advancing the container's `version`.

If instead the `WeighMaster` concludes the material is stolen, the ticket is reported, moving `WEIGHED → REPORTED` — a terminal state. Reporting requires a `reason` and impounds the material rather than paying for it. As a cross-entity cascade it creates a `TheftReport` in `OPEN` status for the ticket's `seller_id`, sets that seller's `status` to `FLAGGED`, and increments the seller's `open_theft_reports` by 1. A `REPORTED` ticket is never paid.

### 3.5. Payout: Disbursement, Segregation of Duties, and the 1099 Cash Ledger

A `PayoutClerk` pays a released ticket. Creating a payout takes the `ticket_id` of a `RELEASED` ticket and a `method` of either `CASH` or `CHECK`. Three conditions gate creation. The ticket must be `RELEASED`. There must be no existing payout for the ticket — exactly one payout per ticket, and a second attempt is rejected with `ERR_DUPLICATE_PAYOUT` (HTTP 409). And segregation of duties must hold: the acting `PayoutClerk`'s `X-User-ID` must differ from the value recorded in the ticket's `theft_hold_released_by`; if they are equal — the same person who cleared the theft hold is trying to approve the money — the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). On creation the payout is `PENDING`, its `amount_cents` is set to the ticket's frozen `gross_valuation_cents`, and the ticket's `seller_id` is copied onto the payout. The `method` is recorded but no funds move yet; the `form_1099_issued` flag is false at this point.

Settlement disburses the funds and moves the payout `PENDING → SETTLED`. Settling requires the payout to be `PENDING` and the seller to be `ACTIVE` (a seller who became frozen between creation and settlement blocks the settle with `ERR_SELLER_FROZEN`). The 1099 cash ledger is driven entirely at settlement and only by cash. When `method` is `CASH`, the seller's `ytd_cash_paid_cents` — the cumulative cash, not check, paid to that seller across the tax year — is increased by the payout's `amount_cents`. After that increment, if the seller's `ytd_cash_paid_cents` is at or above the cumulative cash threshold of $600.00 (that is, 60000 cents), the seller's `requires_1099` flag is set true and stays true for the remainder of the tax year (it never reverts within the year). The 1099 gate is enforced *before* the ledger moves: if the `method` is `CASH` and adding this payout would bring `ytd_cash_paid_cents` to at least 60000 cents, the seller must already have a non-null `tin` on file; if not, the settle is rejected with `ERR_TIN_REQUIRED_FOR_1099` (HTTP 422) and no funds are disbursed. The boundary is inclusive: a cumulative post-increment total of exactly 60000 cents triggers the requirement, while 59999 cents does not.

The payout's `form_1099_issued` flag is set as part of settlement: it becomes true exactly when the `method` is `CASH`, the seller's post-increment `ytd_cash_paid_cents` is at least 60000 cents, and the seller has a non-null `tin`; otherwise it is false. A `CHECK` payout never touches the cumulative cash ledger and always leaves `form_1099_issued` false. A successful cash settlement thus performs a coordinated ledger sync — incrementing `ytd_cash_paid_cents`, recomputing `requires_1099`, and setting `form_1099_issued` — and as its final cross-entity effect transitions the underlying ticket `RELEASED → PAID`, the ticket's terminal paid state.

A `PayoutClerk` may instead void a `PENDING` payout, moving it `PENDING → VOID`. Voiding closes the payout without disbursement; because no cash was ever added, there is no ledger movement to reverse, and the ticket stays `RELEASED`. A payout's `status` is therefore one of `PENDING`, `SETTLED`, or `VOID`, with `SETTLED` and `VOID` both terminal.

### 3.6. Containers: Staging, Loading, and Dispatch

Roll-off containers collect sorted material for shipment. A `YardManager` stages a container by supplying its `category` — `FERROUS` or `NON_FERROUS`, the class of material it accepts — and its `capacity_lb`, the maximum net pounds it can hold, which must be greater than 0. A new container is `STAGED` with `loaded_weight_lb` at 0. A container's `status` runs `STAGED → DISPATCHED → CLOSED`. While `STAGED` the container accepts loads: each released ticket assigned to it adds its `net_weight_lb` to the container's `loaded_weight_lb`, which is the running sum of the net weights of all released tickets assigned to the container.

A `YardManager` dispatches a non-empty staged container, moving it `STAGED → DISPATCHED`. Dispatch requires the container to be `STAGED` and its `loaded_weight_lb` to be greater than 0; dispatching a `STAGED` container whose `loaded_weight_lb` is 0 is rejected with `ERR_INVALID_REQUEST` (HTTP 422), the generic request-well-formedness code, since the empty-container precondition has no dedicated rejection code. Dispatch is also optimistic-concurrency-guarded: the request carries `expected_container_version`, which must match the container's current `version`, or the dispatch is rejected with `ERR_STALE_CONTAINER_VERSION` as described in §2.7. A successful dispatch takes the container off the staging line, makes it eligible for a mill shipment, and increments the container's `version`. A container moves from `DISPATCHED` to `CLOSED` when it is consumed by a mill shipment, described next; a dispatched container is shipped exactly once.

### 3.7. Mill Shipment, Settlement Reconciliation, and Hedge Realization

When a dispatched container's material goes to the mill, a `YardManager` or `SettlementAccountant` creates a mill shipment from it. Creation takes the `container_id` of a `DISPATCHED` container — unique across mill shipments, so a container ships once — and optionally a `hedge_position_id` linking an open hedge. The container must be `DISPATCHED` and must not already have a shipment. On creation the shipment is `SHIPPED`; it copies the container's `category` and copies the container's `loaded_weight_lb` into the shipment's `shipped_weight_lb`; and it consumes the container, moving it to `CLOSED`. At this moment the shipment also freezes its `expected_settlement_cents`, the forward-looking sell-side estimate. That estimate is computed over every `ScaleTicket` assigned to the shipment's container whose `status` is `RELEASED` or `PAID`: for each such ticket, and for each `TicketLineItem` on it, the line's `weight_lb` is multiplied by the `mill_price_cents_per_lb` of the line's pinned `commodity_price_id` row and rounded half-up to whole cents, and these rounded per-line amounts are accumulated into `expected_settlement_cents`. The mill prices are pinned via `commodity_price_id`, immune to any later supersede.

Settlement closes the loop. A `SettlementAccountant` settles a `SHIPPED` shipment by supplying the `final_settlement_cents` the mill actually remitted, which must be at least 0. The shipment moves `SHIPPED → SETTLED`. The system records the `settlement_variance_cents` as the `final_settlement_cents` minus the frozen `expected_settlement_cents` — a plain integer subtraction, positive when the actual exceeds the estimate (favorable to the yard) and negative when it falls short (unfavorable). Both `final_settlement_cents` and `settlement_variance_cents` are null until the shipment is settled.

Settlement is also where a linked hedge is realized, in one cascade. If the shipment was created with a `hedge_position_id`, the settle request must carry `expected_hedge_version`. The referenced hedge must be `OPEN`, its `category` must match the shipment's `category`, and its `version` must equal `expected_hedge_version` (or the settle is rejected with `ERR_STALE_HEDGE_VERSION`, per §2.7). The realization first derives the effective realized sell price per pound: the shipment's `final_settlement_cents` divided by its `shipped_weight_lb`, rounded half-up to whole cents. The pounds realized on this leg is the smaller of the shipment's `shipped_weight_lb` and the hedge's remaining capacity (its `hedged_weight_lb` minus its already-`realized_weight_lb`); the realization may not push `realized_weight_lb` past `hedged_weight_lb`, and a shipment whose weight would over-realize the position is rejected with `ERR_HEDGE_OVER_REALIZED` (HTTP 409). The leg's profit and loss is the realized pounds multiplied by the difference between the hedge's `locked_price_cents_per_lb` and that effective realized mill price, rounded half-up to whole cents — positive when the locked price exceeds the realized mill price (the hedge gained while spot fell), negative when the locked price is below it (the hedge lost while spot rose). The hedge's `realized_weight_lb` then increases by the realized pounds, its `realized_pnl_cents` increases by the leg's profit and loss, and the cascade increments the hedge's `version`. If the realization brings `realized_weight_lb` to at least `hedged_weight_lb`, the hedge auto-closes, moving `OPEN → CLOSED`.

### 3.8. Hedge Positions: Opening, Realizing, and Closing

A commodity hedge lets the yard lock a sell price ahead of shipment. A `SettlementAccountant` opens a hedge by supplying its `category` — `FERROUS` or `NON_FERROUS`, since only shipments of the matching category may realize against it — the `hedged_weight_lb` it locks (greater than 0), and the `locked_price_cents_per_lb` it locks for that weight (at least 0). A new hedge is `OPEN` with `realized_weight_lb` and `realized_pnl_cents` both at 0. As mill shipments settle against it, its `realized_weight_lb` and `realized_pnl_cents` accumulate per the realization cascade of §3.7, capped so realized pounds never exceed `hedged_weight_lb`.

A hedge's `status` is `OPEN` or `CLOSED`. It auto-closes when a settlement realizes it to full capacity, as just described. A `SettlementAccountant` may also close an `OPEN` hedge manually, moving it `OPEN → CLOSED`; once closed, no further shipments may realize against it. Closing is only valid from `OPEN`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/yard` prefix. Creating a new resource returns HTTP 201 with the created resource in `data`. Reads and state-changing operations that modify an existing resource return HTTP 200 with the affected resource. Errors carry the status codes catalogued in §5. List endpoints honor the pagination and ordering rules of §2.3; filter query parameters named below are optional.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/yard/sellers` | Register a seller with government ID; TIN optional | WeighMaster, ComplianceOfficer |
| GET | `/yard/sellers/{id}` | Fetch a seller including 1099 ledger and theft status | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/sellers` | List sellers (paginated); filter by `status` | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| PATCH | `/yard/sellers/{id}` | Add or correct a seller's TIN | WeighMaster, ComplianceOfficer |
| POST | `/yard/sellers/{id}/ban` | Ban a seller; blocks new weigh-outs and releases | ComplianceOfficer |
| POST | `/yard/commodity-prices` | Publish an ACTIVE spot/mill price; supersedes a prior ACTIVE row for the grade | YardManager |
| GET | `/yard/commodity-prices/{id}` | Fetch a single commodity price row | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/commodity-prices` | List commodity prices; filter by `grade_code`, `category`, `status` | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| POST | `/yard/tickets` | Open a DRAFT scale ticket at inbound weigh | WeighMaster |
| GET | `/yard/tickets/{id}` | Fetch a scale ticket with valuation and status | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/tickets` | List tickets; filter by `seller_id`, `container_id`, `status` | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| POST | `/yard/tickets/{id}/line-items` | Add a material grade line to a DRAFT ticket | WeighMaster |
| GET | `/yard/tickets/{id}/line-items` | List the line items of a ticket | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/line-items/{id}` | Fetch a single ticket line item | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/line-items` | List line items across tickets; filter by `ticket_id` or `commodity_price_id` | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| POST | `/yard/tickets/{id}/weigh-out` | Record outbound tare, compute net weight, freeze valuation → WEIGHED | WeighMaster |
| POST | `/yard/tickets/{id}/theft-hold` | Place a discretionary theft HOLD on a WEIGHED ticket | WeighMaster |
| POST | `/yard/tickets/{id}/clear-hold` | Clear a theft HOLD back to WEIGHED, recording the clearer | WeighMaster |
| POST | `/yard/tickets/{id}/release` | Release a WEIGHED ticket into a matching STAGED container → RELEASED | WeighMaster |
| POST | `/yard/tickets/{id}/report` | File a theft report on a WEIGHED ticket → REPORTED; freezes the seller | WeighMaster |
| POST | `/yard/payouts` | Create a PENDING payout for a RELEASED ticket; enforces segregation of duties | PayoutClerk |
| GET | `/yard/payouts/{id}` | Fetch a payout including 1099 flag and status | PayoutClerk, ComplianceOfficer, SettlementAccountant, YardManager |
| GET | `/yard/payouts` | List payouts; filter by `ticket_id`, `seller_id`, `method`, `status` | PayoutClerk, ComplianceOfficer, SettlementAccountant, YardManager |
| POST | `/yard/payouts/{id}/settle` | Disburse the payout → SETTLED; drives the 1099 ledger; ticket → PAID | PayoutClerk |
| POST | `/yard/payouts/{id}/void` | Void a PENDING payout without disbursing | PayoutClerk |
| POST | `/yard/containers` | Stage a roll-off container for a category and capacity | YardManager |
| GET | `/yard/containers/{id}` | Fetch a container including loaded weight and status | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| GET | `/yard/containers` | List containers; filter by `category`, `status` | WeighMaster, PayoutClerk, ComplianceOfficer, YardManager, SettlementAccountant |
| POST | `/yard/containers/{id}/dispatch` | Dispatch a STAGED non-empty container → DISPATCHED (OCC-guarded) | YardManager |
| POST | `/yard/mill-shipments` | Ship a DISPATCHED container to the mill; freezes expected settlement | YardManager, SettlementAccountant |
| GET | `/yard/mill-shipments/{id}` | Fetch a mill shipment including expected/final settlement and variance | YardManager, SettlementAccountant, ComplianceOfficer |
| GET | `/yard/mill-shipments` | List mill shipments; filter by `container_id`, `hedge_position_id`, `status` | YardManager, SettlementAccountant, ComplianceOfficer |
| POST | `/yard/mill-shipments/{id}/settle` | Record final settlement, compute variance, realize the linked hedge → SETTLED | SettlementAccountant |
| POST | `/yard/hedges` | Open a commodity hedge position locking a price for a weight | SettlementAccountant |
| GET | `/yard/hedges/{id}` | Fetch a hedge including realized weight and P&L | SettlementAccountant, YardManager, ComplianceOfficer |
| GET | `/yard/hedges` | List hedge positions; filter by `category`, `status` | SettlementAccountant, YardManager, ComplianceOfficer |
| POST | `/yard/hedges/{id}/close` | Manually close an OPEN hedge | SettlementAccountant |
| GET | `/yard/theft-reports/{id}` | Fetch a theft report | ComplianceOfficer, WeighMaster, YardManager |
| GET | `/yard/theft-reports` | List theft reports; filter by `seller_id`, `ticket_id`, `status` | ComplianceOfficer, WeighMaster, YardManager |
| POST | `/yard/theft-reports` | File a proactive theft report against a seller | ComplianceOfficer |
| POST | `/yard/theft-reports/{id}/clear` | Clear an OPEN theft report; may unfreeze the seller | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_SELLER_FROZEN | 409 |
| ERR_CATEGORY_MISMATCH | 409 |
| ERR_GRADE_NOT_ACTIVE | 409 |
| ERR_INVALID_WEIGHT | 422 |
| ERR_CONTAINER_CAPACITY_EXCEEDED | 409 |
| ERR_HEDGE_OVER_REALIZED | 409 |
| ERR_TIN_REQUIRED_FOR_1099 | 422 |
| ERR_STALE_CONTAINER_VERSION | 412 |
| ERR_STALE_HEDGE_VERSION | 412 |
| ERR_NO_LINE_ITEMS | 409 |
| ERR_DUPLICATE_PAYOUT | 409 |
| ERR_INVALID_REQUEST | 422 |

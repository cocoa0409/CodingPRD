# Salt Deicing Operations API — Product Requirements Document

## 1. Introduction

Rock salt is a commodity whose entire economics collapse into a single winter. An evaporation-and-mining producer must commit tonnage to municipalities, counties and states months before anyone knows whether the season will be mild or brutal, must have that tonnage already positioned in covered sheds near the markets that will scream for it, and must keep a room-and-pillar mine running safely enough that the shaft never stops hoisting at the exact moment the phones start ringing. The operators who run this business today do it across a mine-planning spreadsheet, a laboratory notebook, a depot whiteboard and a contract file cabinet, and the four never agree. When a roof-convergence reading suspends a panel on Tuesday, nobody recomputes the hoisting schedule; when a depot fills to the rafters on Thursday, nobody tells the allocator to stop routing storm orders there.

This document specifies the Salt Deicing Operations API, a single transactional system of record for the whole chain: room-and-pillar panel development and reserve estimation, shaft hoisting capacity under two independent derating dimensions, crushing/screening/treatment with anticaking and corrosion-inhibitor dosing, product-line quality adjudication across highway deicing, water conditioning, food grade and chemical feedstock, seasonal demand forecasting under winter-severity uncertainty, pre-season stockpile targets, municipal and state bid contracts with tonnage commitments and failure-to-supply penalties, rail/barge/truck logistics into market-positioned depots, covered and open-pad storage under storm posture, and the storm-aware allocation waterfall that turns a public body's phone call into reserved tonnage and an invoice.

Two design commitments run through every requirement below. First, **derived numbers are never stale**: a compliance citation on the mine does not merely set a flag, it reprices every panel's recoverable reserve, re-fits the hoisting schedule, and holds the runs that no longer fit — all inside the one request that recorded the citation. Second, **money and tonnage are conserved quantities**: a reservation that is released must return the pile to exactly the tonnage it held before, to the cent and to the hundredth of a ton, and a waived penalty must leave the contract's accrued ledger exactly where it stood before the shortfall. Every service is mounted under the `/salt` prefix, with the single exception of the logical-clock test hook described in §2.5.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that hold for every endpoint in the system. Where §3 describes what a workflow means, this section describes how every request is framed, screened, numbered and versioned.

### 2.1. Operator Identity and Role Authority

Every request — without exception, including reads and including the logical-clock hook — must carry two headers. `X-User-ID` identifies the acting operator and `X-User-Role` declares the capacity in which they are acting. If either header is absent or empty, or if `X-User-Role` is not exactly one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the declared role is not among the roles authorized for the endpoint being called (see the table in §4), the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The seven recognized roles are `MinePlanner`, `GroundControlEngineer`, `QualityLab`, `LogisticsPlanner`, `ContractAdministrator`, `ComplianceOfficer` and `DepotManager`.

- `MinePlanner` plans room-and-pillar development and the hoisting schedule; it owns mine and panel geometry and the production-run lifecycle.
- `GroundControlEngineer` runs the ground-control program: roof and convergence inspections, suspension of unsafe panels, and remediation sign-off.
- `QualityLab` crushes, screens and treats ore into product lines, doses additives, adjudicates batch quality control, and may quarantine a suspect pile.
- `LogisticsPlanner` positions inventory across depots, plans rail, barge and truck movements, and runs the allocation waterfall and invoicing.
- `ContractAdministrator` owns the bid lifecycle, tonnage commitments, price guarantees and season closeout.
- `ComplianceOfficer` records mine-safety compliance actions and waives failure-to-supply penalties.
- `DepotManager` operates one depot and only that depot.

Six of these roles carry an **opaque identity**. When `X-User-Role` is `MinePlanner`, `GroundControlEngineer`, `QualityLab`, `LogisticsPlanner`, `ContractAdministrator` or `ComplianceOfficer`, the `X-User-ID` value is an opaque operator identifier that is not tied to any persisted entity; the server never compares it to any resource's `id`. The server does, however, **record** it wherever a workflow demands an audit trail or a separation-of-duties comparand: as `inspector_user_id` on a ground-control inspection, as `suspended_by_user_id` on a suspended panel, as `created_by_user_id` and `qc_decided_by_user_id` on a treatment batch, as `submitted_by_user_id` and `decided_by_user_id` on a bid contract, and as `storm_state_set_by_user_id` on a depot whose posture was set by hand.

`DepotManager` is the one **entity-backed** role. When `X-User-Role` is `DepotManager`, `X-User-ID` is the `id` of the acting `Depot`; ownership checks on any resource that references a `Depot` compare the resource's depot foreign-key field to `X-User-ID`. A `DepotManager` may therefore patch only its own depot, set only its own depot's storm posture, plan or load a shipment only where the origin depot is itself, receive a shipment only where the destination depot is itself, and quarantine only lots sitting at its own depot. Any of these attempted against another depot is rejected with `ERR_DEPOT_NOT_OWNED` (HTTP 403).

Two **segregation-of-duties** rules override role membership. The `X-User-ID` deciding quality control on a treatment batch must differ from the `X-User-ID` recorded as that batch's creator, and the `X-User-ID` issuing a mine compliance action must differ from the `X-User-ID` recorded as the inspector on the ground-control inspection cited as evidence for that action. Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

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

### 2.3. Pagination and List Ordering

Every collection endpoint accepts two query parameters for windowing. `limit` caps the number of rows returned; it defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` is the number of rows to skip before the window begins and defaults to 0.

Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The one documented exception is the ground-control inspection list, which is ordered by `created_at` descending so that the newest reading on a panel is the first row — the same ordering the server itself uses when it decides whether a panel's latest finding leaves a defect open.

List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope. `total_count` counts the rows matching the filters before the window is applied; `has_more` is true when rows remain beyond the current window.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id`, formatted as a UUID with no type prefix, and a `created_at` timestamp rendered as an ISO 8601 UTC instant with exactly three fractional digits (for example `2026-08-01T00:00:00.000Z`).

Eleven of the twelve resource families additionally carry `updated_at`, an ISO 8601 UTC timestamp in the same format that is refreshed on every mutation, and `version`, an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation. These families are `Mine`, `Panel`, `ProductionRun`, `TreatmentBatch`, `Depot`, `StockpileLot`, `Shipment`, `SeasonForecast`, `BidContract`, `DeliveryOrder` and `Allocation`. A recomputation of a derived field counts as a mutation: when a compliance action reprices a panel's reserve, that panel's `updated_at` is refreshed and its `version` climbs, exactly as if a client had edited it directly.

`GroundControlInspection` is the exception. An inspection record is an immutable append-only observation: it carries only `id` and `created_at`. It has no `updated_at` field, no `version` field, and no update endpoint of any kind.

### 2.5. The Logical Clock

Every temporal comparison in this system — hoist windows, loadout-bay windows, the pre-season activation lock, and delivery deadlines — is evaluated against a server-held **logical clock**, never against real wall-clock time. Before any client moves it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to the host machine's real time.

Any of the seven roles may advance or rewind the clock by posting a `to_iso8601` instant to `POST /_clock/set_current_utc`, which returns 200 OK. Moving the clock mutates no entity and triggers no recomputation whatsoever; it only changes the instant against which subsequent comparisons are made. The `created_at`, `updated_at`, `last_compliance_action_at` and `delivered_at` stamps written by the server all read from this clock.

### 2.6. Rejection Precedence: How a Request Is Screened

A single malformed or ill-timed request routinely violates several rules at once. The screening order below is therefore **normative**: the checks are evaluated in the sequence given, the first violated check is the one whose `error_id` and HTTP status the client receives, and **no side effect of any later stage is applied**. A request that would both fail authorization and exceed a capacity ceiling reports the authorization failure only.

1. **Header validity** — `ERR_UNAUTHENTICATED` (401), on every endpoint.
2. **Role authority** — `ERR_UNAUTHORIZED` (403), on every endpoint.
3. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (403), on `POST /salt/treatment-batches/{id}/qc-decision` and `POST /salt/mines/{id}/compliance-action`.
4. **Depot ownership** — `ERR_DEPOT_NOT_OWNED` (403), on `PATCH /salt/depots/{id}`, `POST /salt/depots/{id}/posture`, `POST /salt/shipments`, `POST /salt/shipments/{id}/load`, `POST /salt/shipments/{id}/receive` and `POST /salt/stockpile-lots/{id}/quarantine-state`.
5. **Required inputs present** — every field the endpoint marks required must be present and non-null, else `ERR_INVALID_REQUEST` (422). Applies to every endpoint.
6. **Enum membership** — every enum-typed input value must be a member of the set declared for that field, else `ERR_INVALID_REQUEST` (422). Applies to every endpoint, and covers `product_line`, `screen_spec`, `storage_kind`, `destination_storage_kind`, `mode`, `storm_priority`, `method`, `finding`, `jurisdiction_level`, `hoist_state`, `depot_state`, `action`, `decision` and `outcome`.
7. **Numeric and temporal shape** — `ERR_INVALID_REQUEST` (422) when a tonnage, rate or price is negative, when a percentage field falls outside 0 through 100, when `severity_index` is not an integer between 0 and 100 inclusive, when `min_take_pct` is greater than `max_take_pct`, when a client attempts to set `rework_count` itself, when a window's start is not strictly earlier than its end (`hoist_window_start` must be strictly before `hoist_window_end`, and `load_window_start` strictly before `load_window_end`), or when `preseason_lock_date` or `required_by` is not a well-formed ISO 8601 instant. Applies to `POST /salt/mines`, `POST /salt/panels`, `POST /salt/production-runs`, `POST /salt/production-runs/{id}/hoist`, `POST /salt/treatment-batches`, `POST /salt/depots`, `PATCH /salt/depots/{id}`, `POST /salt/shipments`, `POST /salt/season-forecasts`, `PATCH /salt/season-forecasts/{id}`, `POST /salt/bid-contracts`, `POST /salt/delivery-orders`, `POST /salt/allocations` and `POST /_clock/set_current_utc`.
8. **Path resource existence** — each identifier in the URL path is resolved left to right, and the first one that does not resolve yields that entity's own 404: `ERR_MINE_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPOT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or `ERR_INSPECTION_NOT_FOUND` (all 404). Applies to every endpoint with a path parameter.
9. **Body reference existence** — every foreign key supplied in a request body must resolve, and an unresolved one yields the referenced entity's own 404 code. The referencing fields are `mine_id`, `panel_id`, `production_run_id`, `depot_id`, `origin_depot_id`, `destination_depot_id`, `treatment_batch_id`, `stockpile_lot_id`, `season_forecast_id`, `bid_contract_id`, `delivery_order_id` and `inspection_id`. Applies to `POST /salt/panels`, `POST /salt/ground-control-inspections`, `POST /salt/production-runs`, `POST /salt/treatment-batches`, `POST /salt/shipments`, `POST /salt/bid-contracts`, `POST /salt/delivery-orders`, `POST /salt/allocations` and `POST /salt/mines/{id}/compliance-action`.
10. **Stale parent version** — the optimistic-concurrency check of §2.8, yielding `ERR_STALE_MINE_VERSION`, `ERR_STALE_BID_CONTRACT_VERSION` or `ERR_STALE_STOCKPILE_LOT_VERSION` (all 412), on `POST /salt/production-runs`, `POST /salt/delivery-orders` and `POST /salt/allocations` respectively.
11. **Contract state** — `ERR_CONTRACT_INVALID_STATE` (409) when the bid contract is not in the state the operation requires. Applies to `POST /salt/bid-contracts/{id}/submit` (needs `DRAFT`), `POST /salt/bid-contracts/{id}/decision` (needs `SUBMITTED`), `POST /salt/bid-contracts/{id}/activate` (needs `AWARDED`), `POST /salt/bid-contracts/{id}/close-season` (needs `ACTIVE`) and `POST /salt/delivery-orders` (needs `ACTIVE`).
12. **Order state** — `ERR_ORDER_INVALID_STATE` (409). Applies to `POST /salt/delivery-orders/{id}/allocate` (needs `REQUESTED`), `POST /salt/delivery-orders/{id}/release-allocations` (needs `ALLOCATED` or `SHORTED`), `POST /salt/delivery-orders/{id}/deliver` (needs `ALLOCATED` or `SHORTED`) and `POST /salt/delivery-orders/{id}/waive-penalty` (needs `SHORTED`).
13. **Panel state** — `ERR_PANEL_INVALID_STATE` (409). Applies to `POST /salt/panels/{id}/develop` (needs `PLANNED`), `POST /salt/panels/{id}/start-production` (needs `DEVELOPED` or `SUSPENDED`), `POST /salt/panels/{id}/suspend` (needs `PRODUCING`), `POST /salt/panels/{id}/deplete` (needs `PRODUCING` or `SUSPENDED`), `POST /salt/panels/{id}/abandon` (needs `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED`) and `POST /salt/production-runs` (needs the target panel `PRODUCING`).
14. **Run state** — `ERR_RUN_INVALID_STATE` (409). Applies to `POST /salt/production-runs/{id}/hoist` (needs `SCHEDULED`), `POST /salt/production-runs/{id}/close` (needs `HOISTED`), `POST /salt/production-runs/{id}/reinstate` (needs `HELD`) and `POST /salt/treatment-batches` (needs the parent run `HOISTED` or `CLOSED`).
15. **Shipment state** — `ERR_SHIPMENT_INVALID_STATE` (409). Applies to `POST /salt/shipments/{id}/load` (needs `PLANNED`), `POST /salt/shipments/{id}/receive` (needs `LOADED`) and `POST /salt/shipments/{id}/cancel` (needs `PLANNED` or `LOADED`).
16. **Quality control already final** — `ERR_BATCH_QC_ALREADY_DECIDED` (409) on `POST /salt/treatment-batches/{id}/qc-decision` when the batch's `qc_state` is already `PASSED` or `FAILED`. The operation is not idempotent: repeating an identical decision on a finalized batch is rejected too.
17. **Rework ceiling** — `ERR_REWORK_LIMIT_EXCEEDED` (409) on `POST /salt/treatment-batches/{id}/qc-decision` when a rework is requested and `rework_count` already stands at 2.
18. **Allocation reservation state** — `ERR_ALLOCATION_NOT_RESERVED` (409) on `POST /salt/delivery-orders/{id}/release-allocations` and `POST /salt/allocations/{id}/release` when an allocation being released is not currently `RESERVED`.
19. **Lot state** — on `POST /salt/allocations`, `POST /salt/shipments` and `POST /salt/stockpile-lots/{id}/quarantine-state`. A reservation or a shipment requires the lot's `lot_state` to be `AVAILABLE`; a `QUARANTINED` lot is refused with `ERR_LOT_QUARANTINED` (409). A quarantine-state change requires `AVAILABLE` to quarantine or `QUARANTINED` to clear, so a `DEPLETED` lot — or an attempt to clear a lot that is already `AVAILABLE` — is refused with `ERR_LOT_STATE_INVALID` (409). A `DEPLETED` lot needs no separate reservation error: its available tonnage is zero and it falls to check 35 instead.
20. **Depot closed** — `ERR_DEPOT_CLOSED` (409). A `CLOSED` depot accepts no inbound treatment batch, mints no lot, ships nothing and takes no manual reservation. Applies to `POST /salt/treatment-batches`, `POST /salt/treatment-batches/{id}/qc-decision`, `POST /salt/shipments`, `POST /salt/shipments/{id}/receive`, `POST /salt/allocations` and `POST /salt/delivery-orders`.
21. **Penalty accrual state** — `ERR_PENALTY_NOT_ACCRUED` (409) on `POST /salt/delivery-orders/{id}/waive-penalty` when the order's `penalty_state` is `NONE` or already `WAIVED`.
22. **Withdrawal order** — `ERR_MINE_WITHDRAWAL_ORDER_ACTIVE` (409) when the mine's `compliance_state` is `WITHDRAWAL_ORDER`, regardless of hoist availability or remaining reserve. Applies to `POST /salt/production-runs`, `POST /salt/production-runs/{id}/hoist`, `POST /salt/production-runs/{id}/reinstate` and `POST /salt/panels/{id}/start-production`.
23. **Shaft availability** — `ERR_HOIST_UNAVAILABLE` (409) when the mine's `hoist_state` is `HOIST_DOWN`. Applies to `POST /salt/production-runs`, `POST /salt/production-runs/{id}/hoist` and `POST /salt/production-runs/{id}/reinstate`.
24. **Open ground-control defect** — `ERR_GROUND_CONTROL_DEFECT_OPEN` (409) when the panel's `open_defect` is true. Applies to `POST /salt/panels/{id}/start-production`, `POST /salt/production-runs` and `POST /salt/production-runs/{id}/reinstate`.
25. **Screen cut permitted for the product line** — `ERR_SCREEN_SPEC_NOT_ALLOWED` (422) on `POST /salt/treatment-batches`.
26. **Additive dosing window** — `ERR_ADDITIVE_DOSE_OUT_OF_SPEC` (422) on `POST /salt/treatment-batches`.
27. **Purity floor at pass** — `ERR_PURITY_BELOW_SPEC` (409) on `POST /salt/treatment-batches/{id}/qc-decision`.
28. **Covered-storage requirement** — `ERR_UNCOVERED_STORAGE_NOT_ALLOWED` (409). Applies to `POST /salt/treatment-batches`, `POST /salt/treatment-batches/{id}/qc-decision`, `POST /salt/shipments` and `POST /salt/shipments/{id}/receive`.
29. **Market-positioning agreement** — `ERR_PRODUCT_LINE_MISMATCH` (409) on `POST /salt/allocations` and `POST /salt/shipments`.
30. **Pre-season activation window** — `ERR_PRESEASON_WINDOW_CLOSED` (409) on `POST /salt/bid-contracts/{id}/activate`.
31. **Aggregate hoist capacity** — `ERR_HOIST_CAPACITY_EXCEEDED` (409) on `POST /salt/production-runs` and `POST /salt/production-runs/{id}/reinstate`.
32. **Loadout-bay exclusivity** — `ERR_LOADOUT_BAY_CONFLICT` (409) on `POST /salt/shipments`.
33. **Panel reserve** — `ERR_PANEL_RESERVE_EXCEEDED` (409) on `POST /salt/production-runs` and `POST /salt/production-runs/{id}/reinstate`.
34. **Storage capacity** — `ERR_COVERED_CAPACITY_EXCEEDED` (409) on `POST /salt/treatment-batches/{id}/qc-decision` and `POST /salt/shipments/{id}/receive`.
35. **Lot tonnage available** — `ERR_INSUFFICIENT_LOT_TONS` (409) on `POST /salt/allocations` and `POST /salt/shipments`.
36. **Empty waterfall pool** — `ERR_NO_ELIGIBLE_STOCKPILE` (409) on `POST /salt/delivery-orders/{id}/allocate`.
37. **Take band** — `ERR_TAKE_BAND_EXCEEDED` (409) on `POST /salt/delivery-orders`.
38. **Pre-season coverage floor** — `ERR_PRESEASON_COVERAGE_SHORT` (409) on `POST /salt/bid-contracts/{id}/activate`.

Two consequences of this ordering deserve emphasis, because they are easy to get backwards. A mine under a withdrawal order refuses a new run at stage 22, before the aggregate-capacity sweep of stage 31 ever runs, so the client sees the safety code rather than a capacity code even when the window is also oversubscribed. And a batch whose additive dose is out of spec is refused at stage 26, before the screen-cut check has any bearing on the outcome — but the screen-cut check at stage 25 comes first, so a batch that is wrong on both counts reports `ERR_SCREEN_SPEC_NOT_ALLOWED`.

### 2.7. Tonnage, Currency and Rounding Discipline

All tonnage and monetary arithmetic is performed in decimal, never in binary floating point. Unless a rule below names a different precision, every stored tonnage and every stored dollar figure is rounded to **2 decimal places using round-half-up**, and every comparison the system makes against a stored figure is made on that rounded value.

Four precision exceptions are load-bearing and must be honoured exactly:

- `planned_tons_per_hour` on a production run is carried at **4 decimal places**, round half up, and the aggregate hoist-capacity comparison is made on those 4-decimal rates.
- `purity_pct_nacl` on a treatment batch, and the copy of it carried onto a stockpile lot, is carried at **3 decimal places**, round half up.
- `convergence_rate_in_per_day` on an inspection accepts **3 decimal places**, and `outbound_freight_rate_per_ton` on a depot accepts **3 decimal places**.
- A mine's hourly capacity — its `effective_hoist_tons_per_day` divided by the 24 hours in a day — is **not rounded** before it is compared against a peak concurrent rate.

Two further comparisons are deliberately made on unrounded cross-multiplied products rather than on the rounded percentage fields that report them. The depot storm threshold compares stored covered tonnage multiplied by 100 against covered capacity multiplied by 90, so it is insensitive to the 2-decimal rounding of `covered_utilization_pct`; a shed holding 35,999 tons of a 40,000-ton capacity stays open, while 36,000 tons flips it. Likewise the breach-watch and take-band tests on a contract are made on unrounded products, not on the 2-decimal `take_pct`.

Invoice arithmetic pins its rounding order explicitly: each allocation line is rounded to cents **first**, and the rounded lines are then summed. Summing raw products and rounding once at the end is wrong and differs by whole cents on multi-line orders. §3.9 spells out the sequence.

### 2.8. Stale-Version Guards on Mine, Contract and Lot Writes

Three creation endpoints size their request against a parent resource whose derived numbers move underneath them, and the parent's state alone cannot tell a fresh reader from a stale one — the parent stays in the very same state while its numbers change. Each of these three endpoints therefore requires a **non-optional** expected-version field carrying the client's last observed `version` of the parent. If the supplied value does not equal the parent's current `version`, the write is rejected and nothing is persisted.

- `POST /salt/production-runs` requires `expected_mine_version`, matching the target `Mine`'s current `version`. A mismatch is rejected with `ERR_STALE_MINE_VERSION` (HTTP 412). The aggregate hoist-window check is evaluated against `effective_hoist_tons_per_day` and the live set of scheduled runs, both of which move with every hoist-status change, every compliance action, every cascade hop and every sibling run creation while the mine remains perfectly schedulable — so a planner working from a stale mine read has sized its window against capacity the server no longer offers.
- `POST /salt/delivery-orders` requires `expected_bid_contract_version`, matching the target `BidContract`'s current `version`. A mismatch is rejected with `ERR_STALE_BID_CONTRACT_VERSION` (HTTP 412). Every new release legitimately consumes take-band headroom that the previous reader still believes is free, and the contract remains `ACTIVE` throughout, so no state precondition distinguishes the two writes — only the version does.
- `POST /salt/allocations` requires `expected_stockpile_lot_version`, matching the target `StockpileLot`'s current `version`. A mismatch is rejected with `ERR_STALE_STOCKPILE_LOT_VERSION` (HTTP 412). A lot's available tonnage is a derived figure that any other reservation, release, load or receipt moves without changing `lot_state`, so a second reservation carrying a stale version has priced its tonnage against an availability figure the server no longer holds. The product semantics genuinely permit a second reservation against the same lot; the stale-version check, not a state precondition, is what separates the two writes.

No other endpoint in the system accepts an expected-version field, and none may be rejected for a version mismatch. Note that `ground_control_plan_version` on a mine is an operator-supplied document revision number and has nothing to do with the `version` used for concurrency control.

### 2.9. Cascade Discipline and Derived-Field Reconciliation

The system is **immediately consistent**. When one request changes a fact, every number derived from that fact is brought up to date inside the same request, and every entity whose stored values changed has its `updated_at` refreshed and its `version` incremented by exactly 1. There is no background sweep, no eventual convergence, and no endpoint that exists solely to reconcile.

Cascades in this domain are multi-hop, and each hop is a real mutation of a real resource. A single ground-control inspection with a defect finding can, in one request, flag the panel, suspend it, decrement the mine's producing-panel tally, derate or down the mine's shaft, reprice the mine's effective capacity, hold several scheduled runs for two different reasons, and pull the mine's open scheduled tonnage down by the exact sum of the held runs' planned tonnage. Every one of those rows bumps its own `version`. §3.3 walks the hops in order.

Cascades are also deliberately **asymmetric**: an automatic transition is not automatically undone when its trigger reverses. Restoring a mine's shaft from derated to available does not un-hold the runs the derate held; each must be reinstated explicitly. Returning a suspended panel to production does not restore the mine's shaft dimension and does not un-hold runs. Cancelling a loaded shipment returns the tonnage and reverses a lot's depletion, but a depot that was automatically pushed into storm posture by that tonnage is not pushed back out. Releasing a reservation restores the pile exactly, but does not un-suspend anything. Where a reversal *is* automatic, §3 says so explicitly; everywhere else it is not.

### 2.10. Path Resolution and Reverse Reachability

All business paths are flat: a collection lives at `/salt/<collection>`, a single row at `/salt/<collection>/{id}`, and an action on a row at `/salt/<collection>/{id}/<action>`. No resource is addressed through a parent path segment. Where a path carries more than one identifier, identifiers are resolved strictly left to right and the leftmost unresolved one determines the 404 that comes back (see stage 8 of §2.6).

Because parents are never in the path, every relationship is instead traversed by filtering the child collection. These filters are the only way to discover rows the server created on your behalf — a stockpile lot minted by a quality-control pass or a shipment receipt, or an allocation line minted by the waterfall, has no creation response of its own.

- Mines are filtered by `state_code`, `hoist_state` and `compliance_state`.
- Panels are filtered by `mine_id`, `status` and `open_defect`.
- Ground-control inspections are filtered by `panel_id`, `finding` and `caused_suspension`.
- Production runs are filtered by `mine_id`, `panel_id`, `status` and `held_reason`.
- Treatment batches are filtered by `production_run_id`, `depot_id`, `qc_state`, `product_line` and `screen_spec`.
- Depots are filtered by `state_code` and `depot_state`.
- Stockpile lots are filtered by `depot_id`, `treatment_batch_id`, `product_line` and `lot_state`.
- Shipments are filtered by `stockpile_lot_id`, `origin_depot_id`, `destination_depot_id`, `status` and `mode`.
- Season forecasts are filtered by `season_code`, `region_code` and `method`.
- Bid contracts are filtered by `season_forecast_id`, `status`, `product_line`, `state_code` and `jurisdiction_level`.
- Delivery orders are filtered by `bid_contract_id`, `depot_id`, `status`, `penalty_state` and `storm_priority`.
- Allocations are filtered by `delivery_order_id`, `stockpile_lot_id`, `state` and `origin`.

Alongside these, three read-only computed endpoints expose figures the system uses internally but does not store as fields. A mine's hoist-capacity view reports `rated_hoist_tons_per_day`, `hoist_factor`, `compliance_factor`, `effective_hoist_tons_per_day`, `mine_hourly_capacity`, `scheduled_hoist_tons_open` and `scheduled_run_count`. A depot's storage-posture view reports `depot_state`, `covered_capacity_tons`, `covered_stored_tons`, `open_pad_capacity_tons`, `open_pad_stored_tons`, `covered_utilization_pct`, `auto_surge_threshold_pct` (which is always 90) and `reserved_tons`, the total tonnage currently reserved across the depot's lots. A contract's ledger view reports `committed_tons`, `fulfilled_tons`, `open_committed_tons`, `take_pct`, `take_band_consumed_tons`, `take_band_limit_tons`, `penalty_accrued_usd`, `accrued_penalty_order_count`, `supply_reliability_score`, `breach_watch`, `preseason_coverage_tons` and `preseason_coverage_required_tons`. None of the three mutates anything or moves a `version`.

### 2.11. The Product-Line Specification Register

Four product lines run through this plant, and almost every quality rule in §3 is a lookup against this register. The lines are `HIGHWAY_DEICING`, `WATER_CONDITIONING`, `FOOD_GRADE` and `CHEMICAL_FEEDSTOCK`. For each line, four specifications are fixed, and **all dosing bounds are inclusive at both ends**:

| Product line | Minimum purity (percent NaCl) | Permitted screen cuts | `anticaking_ppm` window | `corrosion_inhibitor_pct` window |
| --- | --- | --- | --- | --- |
| `HIGHWAY_DEICING` | 92.0 | `COARSE`, `MEDIUM` | 0 through 60 | 0.0 through 1.5 |
| `WATER_CONDITIONING` | 99.5 | `COARSE` only | exactly 0 | exactly 0.0 |
| `FOOD_GRADE` | 99.6 | `FINE` only | 4 through 12 | exactly 0.0 |
| `CHEMICAL_FEEDSTOCK` | 96.0 | `MEDIUM`, `FINE` | 0 through 25 | exactly 0.0 |

Two of these lines are moisture-sensitive. Tonnage of `WATER_CONDITIONING` or `FOOD_GRADE` may never occupy open-pad storage: a batch declaring `OPEN_PAD` for one of those lines is refused, a lot may not be minted onto an open pad for one of those lines, and a shipment may not be planned or received onto an open pad for one of those lines. All four refusals carry `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`. The two storage kinds throughout the system are `COVERED` and `OPEN_PAD`.

## 3. Business Logic & Workflows

The narrative below follows salt from the seam to the invoice. Rules that guard a step are described where that step is described, and cross-references to §2 point back at the contract-level framing rather than repeating it.

### 3.1. The Mine and Its Two Independent Derating Dimensions

A `MinePlanner` registers a mine by supplying its `name`, the two-letter uppercase `state_code` of the jurisdiction it sits in, its nameplate shaft capacity as `rated_hoist_tons_per_day` (which must be strictly greater than zero), and optionally the `ground_control_plan_version` of the ground-control plan on file — an integer of at least 1, defaulting to 1 when omitted. The mine `name` must be between 1 and 120 characters. A newly registered mine opens with `hoist_state` at `HOIST_AVAILABLE`, `compliance_state` at `COMPLIANT`, `scheduled_hoist_tons_open` at 0, `producing_panel_count` at 0, `last_compliance_action_at` null, and `version` at 1.

What makes a mine unusual in this system is that it carries **two state dimensions on the same row**, and they are genuinely independent. `hoist_state` describes the shaft and takes one of `HOIST_AVAILABLE`, `HOIST_DERATED` or `HOIST_DOWN`. `compliance_state` describes the mine's standing with the safety regulator and takes one of `COMPLIANT`, `CITED` or `WITHDRAWAL_ORDER`. Neither dimension constrains the other's transitions; different operators drive them through different operations; and neither has a terminal value, so a mine can cycle through all combinations indefinitely.

The two dimensions **multiply** into one number. Each contributes a factor: the shaft contributes 1.00 while available, 0.55 while derated and 0.00 while down; compliance contributes 1.00 while compliant, 0.80 while cited and 0.00 under a withdrawal order. The mine's `effective_hoist_tons_per_day` is `rated_hoist_tons_per_day` multiplied by the shaft factor and then by the compliance factor, rounded half up to two decimal places. Because the product is taken over *both* dimensions, a mine that is simultaneously cited and derated offers 0.55 multiplied by 0.80 — that is, 0.44 — of nameplate, not the weaker of the two factors. The mine's hourly capacity, used by every scheduling check, is that effective daily figure divided by the 24 hours in a day, and it is compared unrounded. This recomputation runs at mine registration and again on every single mutation of either dimension, including every cascade hop that changes one.

A `MinePlanner` moves the shaft dimension by naming the target `hoist_state` and optionally a free-text `note`. The value named must differ from the value the mine currently holds. All six directed edges are supported: `HOIST_AVAILABLE → HOIST_DERATED`, `HOIST_DERATED → HOIST_AVAILABLE`, `HOIST_AVAILABLE → HOIST_DOWN`, `HOIST_DERATED → HOIST_DOWN`, `HOIST_DOWN → HOIST_AVAILABLE` and `HOIST_DOWN → HOIST_DERATED`. Each one recomputes `effective_hoist_tons_per_day` and increments the mine's `version` by 1.

Whenever the shaft dimension moves in the tightening direction, a **capacity re-fit cascade** follows. While the aggregate concurrent hourly rate of the mine's `SCHEDULED` runs exceeds the mine's new hourly capacity at any instant, the offending run whose window starts latest is moved to `HELD` with `held_reason` set to `CAPACITY` — candidates are scanned by hoist window start descending and, where two windows start together, by `created_at` descending — and the loop repeats until the remaining schedule fits. Each run pushed to `HELD` removes its own `planned_tons` from the mine's `scheduled_hoist_tons_open`, and each holds its own `version` bump. Moving the shaft to `HOIST_DOWN` is the degenerate case of the same rule: capacity becomes 0.00, any positive hourly rate exceeds it, so every `SCHEDULED` run on the mine is held for `CAPACITY` and `scheduled_hoist_tons_open` falls to 0. Relaxing the shaft in the other direction — a derated mine returning to available, or a downed mine returning to derated or available — recomputes capacity and nothing more: **there is no automatic un-hold.** Runs already `HELD` stay `HELD` until a planner reinstates them one at a time.

A `ComplianceOfficer` drives the compliance dimension by supplying an `action` of `CITE`, `WITHDRAW` or `CLEAR`, optionally the `inspection_id` of the ground-control inspection being cited as evidence, and optionally a `note`. `CITE` produces `CITED`, `WITHDRAW` produces `WITHDRAWAL_ORDER`, and `CLEAR` produces `COMPLIANT`; the action must produce a value different from the one currently held. When an `inspection_id` is supplied, the acting `X-User-ID` must differ from the inspector recorded on that inspection, per §2.1, and an unresolvable `inspection_id` yields `ERR_INSPECTION_NOT_FOUND`. Every compliance action stamps `last_compliance_action_at` from the logical clock, recomputes `effective_hoist_tons_per_day`, and increments the mine's `version` by 1. The five supported edges are `COMPLIANT → CITED`, `CITED → WITHDRAWAL_ORDER`, `COMPLIANT → WITHDRAWAL_ORDER`, `CITED → COMPLIANT` and `WITHDRAWAL_ORDER → COMPLIANT`.

Beyond capacity, a compliance action reaches into the panels. On **every** compliance action, the recoverable reserve of every panel on the mine whose `status` is one of `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED` is recomputed from scratch, because one term of that reserve formula is only granted while the mine is compliant (§3.2). Moving to `CITED` therefore strips the pillar-recovery bonus from those panels; moving to `WITHDRAWAL_ORDER` strips it too; and `CLEAR` restores it wherever the panel's `pillar_recovery_allowed` is true. Panels already `DEPLETED` or `ABANDONED` are never touched — their reserve is frozen for good.

The two tightening compliance edges differ in how they treat the schedule, and the difference matters. `COMPLIANT → CITED` runs the ordinary capacity re-fit cascade described above, holding only the runs that no longer fit and marking them `CAPACITY`. Either edge that lands on `WITHDRAWAL_ORDER` — from `COMPLIANT` or from `CITED` — is categorical: **every** `SCHEDULED` run on the mine moves to `HELD` with `held_reason` set to `GROUND_CONTROL`, and `scheduled_hoist_tons_open` falls to 0. Clearing back to `COMPLIANT` restores capacity and panel reserves but, again, un-holds nothing.

Planners and compliance officers read the derating story through the mine's computed capacity view described in §2.10, which decomposes the two factors and reports how much scheduled tonnage and how many scheduled runs are currently committed against the derived capacity.

### 3.2. Panel Layout and the Recoverable Reserve

A `MinePlanner` lays out a room-and-pillar panel inside a mine by supplying the `mine_id` it belongs to, an operator `panel_code` of 1 to 40 characters that must be unique among the panels of that mine, the `gross_tons_in_place` inside the panel outline (strictly greater than zero), the `extraction_ratio_pct` that first-pass room development will remove (strictly greater than zero and at most 75), the assayed `grade_pct_nacl` (at least 80 and at most 100, two decimals), the assayed `insolubles_pct` (at least 0 and at most 30, two decimals), and optionally `pillar_recovery_allowed`, a boolean that defaults to false and records whether the filed ground-control plan permits secondary pillar recovery here. A new panel opens with `status` at `PLANNED`, `mined_tons` at 0, `ground_control_defect_count` at 0, `open_defect` false, `suspended_by_user_id` null, and `version` at 1.

The panel's `recoverable_tons` is computed at creation and recomputed on every compliance action against its mine, in this pinned order:

1. **Base tonnage.** Multiply `gross_tons_in_place` by `extraction_ratio_pct` divided by 100.
2. **Grade tier.** Choose a single grade factor from the assayed `grade_pct_nacl`: 1.00 when the grade is at least 95.0; 0.96 when the grade is at least 90.0 but below 95.0; 0.88 when the grade is below 90.0.
3. **Insolubles penalty.** Take `insolubles_pct` minus 3.0, floor that difference at zero, multiply it by 0.012, and cap the result at 0.20. The first three percentage points of acid insolubles are free; each further point costs 1.2 percent of the reserve, up to a ceiling of 20 percent.
4. **Pillar bonus.** When `pillar_recovery_allowed` is true **and** the parent mine's `compliance_state` is `COMPLIANT` at the moment of evaluation, the bonus is 8 percent of the tonnage left behind by first-pass development, that is 8 percent of `gross_tons_in_place` minus the base tonnage. In every other case — the flag is false, or the mine is `CITED`, or the mine is under a `WITHDRAWAL_ORDER` — the bonus is zero.
5. **Combine.** Multiply the base tonnage by the grade factor, then by one minus the insolubles penalty, then add the pillar bonus.
6. **Hard cap, applied last.** Take the smaller of that combined figure and 72 percent of `gross_tons_in_place`, and round the winner half up to two decimal places.

Because the cap is applied **after** the bonus is added, the cap also clips the pillar bonus; a panel already near its geological ceiling gains nothing from being allowed secondary recovery. The panel's `status` has no influence on the value itself — it only decides whether a recomputation happens at all, and once a panel is `DEPLETED` or `ABANDONED` no recomputation ever happens again.

A panel walks a cyclic lifecycle through `PLANNED`, `DEVELOPED`, `PRODUCING` and `SUSPENDED`, ending in one of the two terminal values `DEPLETED` or `ABANDONED`. Completing development entries and pillars advances `PLANNED → DEVELOPED`; the mine must not be under a `WITHDRAWAL_ORDER` at that moment. Bringing a panel into production — the same planner operation serves both `DEVELOPED → PRODUCING` and the `SUSPENDED → PRODUCING` re-entry — requires that the panel carry no open defect, that the mine's `compliance_state` be exactly `COMPLIANT`, and that the mine's `hoist_state` not be `HOIST_DOWN`. Entering production increments the mine's `producing_panel_count` by 1, clears `suspended_by_user_id` back to null, and bumps both the panel's and the mine's `version`. Re-entry from suspension is the guarded case: it is the open-defect condition (§3.3) that distinguishes it from a first entry, and re-entry deliberately does **not** un-hold the production runs the suspension held, nor does it restore the mine's shaft dimension. Both must be put right explicitly.

Mining a panel out advances `PRODUCING → DEPLETED` or `SUSPENDED → DEPLETED`. When the panel was `PRODUCING`, the mine's `producing_panel_count` drops by 1. Every production run on the panel whose `status` is `SCHEDULED` or `HELD` moves to `VOIDED`, and each voided run's `planned_tons` leaves the mine's `scheduled_hoist_tons_open`. The panel's `recoverable_tons` is frozen at its current value and is never recomputed again, no matter how many compliance actions follow. Abandoning a panel — permitted from `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED`, and requiring a `reason` — has exactly the same consequences for runs, tallies and reserve freezing, and is available to both a `MinePlanner` and a `ComplianceOfficer`.

One depletion edge is not driven by any operator at all. When a hoist is recorded and the panel's cumulative `mined_tons` reaches or exceeds its `recoverable_tons`, the panel moves `PRODUCING → DEPLETED` by itself inside that same request, dropping the mine's `producing_panel_count`, voiding the panel's remaining `SCHEDULED` runs, and pulling their planned tonnage out of `scheduled_hoist_tons_open`.

### 3.3. The Ground Control Program and the Defect Cascade

A `GroundControlEngineer` files an inspection record by supplying the `panel_id` inspected, the unsupported `roof_span_ft` measured at the inspection point (strictly greater than zero and at most 120), the measured roof-to-floor `convergence_rate_in_per_day` in inches per day (at least zero, three decimals), and a `finding` of `PASS`, `ADVISORY` or `DEFECT`. The server stamps `inspector_user_id` with the filer's `X-User-ID`. These records are **append-only**: there is no way to edit or delete one, and as noted in §2.4 they carry neither `updated_at` nor `version`. Each record also carries `caused_suspension`, a computed boolean that is true only when filing this particular record was what moved its panel out of production.

A `PASS` or `ADVISORY` finding is recorded and nothing else happens — no flag, no suspension, no cascade. A `DEFECT` finding is the single most consequential write in the mining half of this system, and it fires a **four-hop cascade** inside one request.

**Hop 1 — the panel.** The panel's `ground_control_defect_count` increases by 1 and its `open_defect` becomes true. (`open_defect` is defined as: the panel's most recent inspection, taken by `created_at` descending, has a `finding` of `DEFECT`.) If the panel was `PRODUCING`, it moves `PRODUCING → SUSPENDED`, `suspended_by_user_id` is set to the filing engineer's `X-User-ID`, this record's `caused_suspension` becomes true, and the mine's `producing_panel_count` drops by 1.

**Hop 2 — the shaft.** Because a panel left production, the mine's shaft dimension tightens in the same breath. If the mine still has at least one `PRODUCING` panel after the suspension, `hoist_state` moves `HOIST_AVAILABLE → HOIST_DERATED` and the shaft factor becomes 0.55. If the suspended panel was the mine's last producing panel — `producing_panel_count` is 0 afterwards — `hoist_state` moves `HOIST_AVAILABLE → HOIST_DOWN` and effective capacity becomes 0.00. Where the mine had already been derated, the further tightening takes it to `HOIST_DOWN`. `effective_hoist_tons_per_day` is recomputed and the mine's `version` increments by 1. No endpoint drives these particular edges directly; they exist only as cascade hops.

**Hop 3 — the runs.** Because the shaft dimension changed, every production run on the suspended panel whose `status` is `SCHEDULED` moves to `HELD` with `held_reason` set to `GROUND_CONTROL`. The capacity re-fit rule of §3.1 then continues over the mine's *other* panels, holding further `SCHEDULED` runs until the aggregate concurrent hourly rate fits the mine's new hourly capacity; those runs are marked `CAPACITY`, not `GROUND_CONTROL`. When the mine went all the way to `HOIST_DOWN`, the practical effect is that every `SCHEDULED` run on the mine ends up held — the suspended panel's runs for `GROUND_CONTROL`, the rest for `CAPACITY`.

**Hop 4 — the mine's open tonnage.** Because those runs left `SCHEDULED`, the mine's `scheduled_hoist_tons_open` is recomputed downward by exactly the sum of the held runs' `planned_tons`; when every run was held, it reaches 0.

Filing the **third** defect on a single panel does more. Once the panel's `ground_control_defect_count` reaches 3, the panel moves `SUSPENDED → ABANDONED` in the same request: every run on it in `SCHEDULED` or `HELD` moves to `VOIDED`, each voided run's `planned_tons` leaves `scheduled_hoist_tons_open`, and the panel's `recoverable_tons` is frozen forever. In other words a panel may cycle out of and back into production twice; the third defect ends it.

A defect is cleared, not forgotten. A `GroundControlEngineer` records remediation by supplying a `remediation_note`, which sets the panel's `open_defect` back to false and bumps the panel's `version`. The `ground_control_defect_count` tally is **permanent and is never decremented** — it is what counts toward the third-defect abandonment. Until remediation is recorded, a panel with `open_defect` true may not re-enter production and may not host a new or reinstated run; all three refusals carry `ERR_GROUND_CONTROL_DEFECT_OPEN`.

Suspension is also available as a deliberate operator act, to a `GroundControlEngineer` or a `ComplianceOfficer`, on a panel that is `PRODUCING`, and it requires a `reason`. This manual `PRODUCING → SUSPENDED` edge sets `suspended_by_user_id` to the caller's `X-User-ID`, drops the mine's `producing_panel_count`, and fires hops 2 through 4 exactly as the defect path does — the shaft tightens, runs are held for `GROUND_CONTROL` and `CAPACITY` respectively, and `scheduled_hoist_tons_open` is recomputed. The one difference is decisive: a manual suspension does **not** set `open_defect`, because only a defect inspection does that. A manually suspended panel therefore needs no remediation before it can return to production.

### 3.4. Scheduling and Hoisting Production Runs

A production run is a reservation of shaft time. A `MinePlanner` schedules one against a `PRODUCING` panel by supplying the `mine_id` whose shaft will do the hoisting, the `panel_id` being mined, the `planned_tons` to bring up (strictly greater than zero), and the window the shaft is reserved for as `hoist_window_start` and `hoist_window_end`, both ISO 8601 UTC instants with the end strictly after the start. The `expected_mine_version` field required alongside them is described in §2.8. A new run opens with `status` at `SCHEDULED`, `hoisted_tons` at 0, `held_reason` null, `open_batch_count` at 0, and `version` at 1, and its `planned_tons` is added into the mine's `scheduled_hoist_tons_open`. Creating a run also increments the parent mine's `version` by 1.

From the window the server derives `planned_tons_per_hour`: the run's `planned_tons` divided by the exact length of the window in hours (which may be fractional), rounded half up to four decimal places.

The **aggregate hoist-window capacity check** then decides whether the schedule can absorb this run. Windows here are **half-open**: a window covers its start instant and every instant up to but not including its end, so two windows that merely touch — one ending exactly where the next begins — do not overlap. Overlap itself is not forbidden; what is forbidden is exceeding the shaft's throughput while overlapping. The check proceeds as follows:

1. Collect the peer set: every other production run on the same `mine_id` whose `status` is `SCHEDULED`. Runs that are `HELD`, `HOISTED`, `CLOSED` or `VOIDED` release their window and contribute nothing.
2. For the candidate window and for every peer window, emit two events: a rate-increase event at the window's start carrying that run's `planned_tons_per_hour`, and a rate-decrease event at the window's end carrying the same magnitude.
3. Sort the events by timestamp ascending. Where two events share a timestamp, apply every decrease before any increase — this tie-break is precisely what makes touching windows non-overlapping.
4. Sweep the sorted events, carrying a running total of the concurrent hourly rate, and take the maximum value that total reaches at any instant that lies inside the candidate's own window. That maximum is the peak concurrent rate.
5. Compare the peak concurrent rate against the mine's hourly capacity — its `effective_hoist_tons_per_day` divided by 24, unrounded. The request is refused with `ERR_HOIST_CAPACITY_EXCEEDED` only when the peak is **strictly greater** than the capacity. A peak exactly equal to capacity is accepted.

Alongside capacity, a **panel reserve** check protects the geology. Sum the `planned_tons` of every run already on the target panel whose `status` is `SCHEDULED`, `HELD`, `HOISTED` or `CLOSED`, add the new run's `planned_tons`, and refuse with `ERR_PANEL_RESERVE_EXCEEDED` when that total would exceed the panel's `recoverable_tons`. Note that held and closed runs still count against the reserve, while voided runs do not.

Recording the hoist advances `SCHEDULED → HOISTED`. The planner supplies the `hoisted_tons` actually brought to surface, which the server stores and adds into the panel's `mined_tons`. The mine may not be under a `WITHDRAWAL_ORDER`, its shaft must not be `HOIST_DOWN`, the panel must be `PRODUCING`, and the panel's existing `mined_tons` plus the tonnage being recorded must not exceed the panel's `recoverable_tons`. The run's window is released, so the mine's `scheduled_hoist_tons_open` is recomputed downward by the run's `planned_tons`. If the panel's `mined_tons` has now reached or exceeded its `recoverable_tons`, the panel depletes itself as described in §3.2. The run's `version`, the panel's `version` and the mine's `version` all increment by 1.

A `HELD` run — whether held for `GROUND_CONTROL` by a suspension or a withdrawal order, or for `CAPACITY` by a re-fit — is returned to the schedule by a planner reinstating it, moving `HELD → SCHEDULED` and clearing `held_reason` back to null. Reinstatement deliberately re-runs **every** guard the original creation ran: the mine must be `COMPLIANT`, its shaft must not be `HOIST_DOWN`, the panel must be `PRODUCING` with no open defect, the aggregate half-open window sweep must still fit the run's hourly rate inside the mine's current hourly capacity, and the panel reserve must still accommodate it. A run held because the underlying condition still holds therefore cannot be reinstated at all — the cascade cannot be undone by wishing. On success the run's `planned_tons` is added back into the mine's `scheduled_hoist_tons_open`, and both the run's and the mine's `version` increment by 1.

Closing a run — `HOISTED → CLOSED`, terminal — is where the run's **compound** nature shows. A run's `open_batch_count` counts the treatment batches on it whose quality control is still pending. The moment the **last** such batch leaves the pending state, the run closes itself automatically inside that same request. A run that has at least one batch therefore never needs a manual close. A run with **zero** batches, on the other hand, never auto-closes, because the automatic path requires that at least one batch exist; such a run is closed explicitly by a `MinePlanner`, and the explicit close requires `open_batch_count` to already stand at 0. Either way the run's `version` increments by 1.

Runs are also moved by the system rather than by their planner. `SCHEDULED → HELD` is never a client-driven edge: it fires as hop 3 of the ground-control defect cascade of §3.3, as a step of the capacity re-fit cascade of §3.1, or categorically when a compliance action lands the mine on `WITHDRAWAL_ORDER` — with `held_reason` set to `GROUND_CONTROL` in the defect and withdrawal cases and to `CAPACITY` in the re-fit case.

Two terminal voidings reach runs from outside. `SCHEDULED → VOIDED` fires when the run's panel reaches `ABANDONED` or `DEPLETED`, and the run's `planned_tons` leaves the mine's `scheduled_hoist_tons_open`. `HELD → VOIDED` fires when the run's panel reaches `ABANDONED`; because a held run's tonnage had already left the mine's open figure when it was held, no further tonnage adjustment is made. Both bump the run's `version`.

### 3.5. Crushing, Screening, Treatment and Quality Adjudication

Hoisted ore is turned into saleable product by the `QualityLab`. A batch is opened against a run that is `HOISTED` or already `CLOSED`, by supplying the `production_run_id` whose ore feeds it, the `depot_id` that will receive the resulting pile, the `product_line` being made, the `screen_spec` cut applied on the treatment line (`COARSE`, `MEDIUM` or `FINE`), the `anticaking_ppm` dose in parts per million (at least 0 and at most 200, two decimals), the `corrosion_inhibitor_pct` dose as a percentage of product mass (at least 0 and at most 5, two decimals), the `input_tons` of run ore fed in (strictly greater than zero), the free `moisture_pct` of the feed (at least 0 and at most 12, two decimals), and the `storage_kind` the resulting pile will occupy at that depot. The server stamps `created_by_user_id` with the creating `X-User-ID` — the comparand for the segregation-of-duties rule at stage 3 of §2.6 — and opens the batch with `qc_state` at `PENDING`, `rework_count` at 0, `qc_decided_by_user_id` null, and `version` at 1. The parent run's `open_batch_count` increases by 1. Batch creation is screened against the product-line register of §2.11 twice: an impermissible screen cut is refused with `ERR_SCREEN_SPEC_NOT_ALLOWED`, and a dose outside the line's inclusive window is refused with `ERR_ADDITIVE_DOSE_OUT_OF_SPEC`. A batch declaring `OPEN_PAD` for `WATER_CONDITIONING` or `FOOD_GRADE` is refused with `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`, and a batch aimed at a `CLOSED` depot is refused with `ERR_DEPOT_CLOSED`.

Two numbers are computed at creation. **Yield.** Each screen cut carries a yield factor — 0.94 for `COARSE`, 0.90 for `MEDIUM`, 0.82 for `FINE` — and a rework loss factor of 0.97 raised to the power of the current `rework_count`, which is exactly 1 while `rework_count` is 0. The batch's `yield_tons` is `input_tons` multiplied by the screen's yield factor, multiplied by one minus `moisture_pct` divided by 100, multiplied by the rework loss factor, rounded half up to two decimal places. **Purity.** Each screen cut also carries a purity upgrade in percentage points — 0.5 for `COARSE`, 1.2 for `MEDIUM`, 2.5 for `FINE`. The batch's `purity_pct_nacl` is the `grade_pct_nacl` of the panel behind the feeding run plus that upgrade, capped at a ceiling of 99.9, rounded half up to three decimal places. The panel is reached through the run: the run names a panel, and the panel carries the assayed grade. Purity is **frozen at creation** and is never recomputed, because reworking re-screens the very same ore.

Adjudication is a single operation carrying a `decision` of `PASS`, `FAIL` or `REWORK` and an optional `note`, and it is only ever accepted while `qc_state` is `PENDING`. A batch that has already landed on `PASSED` or `FAILED` refuses any further decision — including a verbatim repeat of the decision already recorded — with `ERR_BATCH_QC_ALREADY_DECIDED`; the operation is deliberately not idempotent. Every accepted decision stamps `qc_decided_by_user_id` with the deciding `X-User-ID` and bumps the batch's `version` by 1, and in all three branches the decider must not be the batch's creator.

**Rework** is the `PENDING → PENDING` self-loop, and it is bounded. It is accepted only while `rework_count` is strictly less than 2; a third attempt is refused with `ERR_REWORK_LIMIT_EXCEEDED` and the batch must then be passed or failed. Each accepted rework increases `rework_count` by 1 and recomputes `yield_tons` with the loss factor of 0.97 raised to the new `rework_count` — so a once-reworked batch keeps 97 percent of its original yield and a twice-reworked batch 94.09 percent of it, since the exponent grows with each loop. `purity_pct_nacl` is **not** recomputed, and the parent run's `open_batch_count` is left unchanged, because the batch is still pending.

**Fail** moves `PENDING → FAILED`, terminal. No stockpile lot is minted and the batch tonnage is scrapped. The parent run's `open_batch_count` decreases by 1, and if that count reaches 0 the run closes itself `HOISTED → CLOSED` per §3.4.

**Pass** moves `PENDING → PASSED`, terminal, and is the only operation in the system that creates tonnage. Four preconditions guard it, over and above the pending-state requirement. The batch's computed `purity_pct_nacl` must be at least the product line's minimum purity from §2.11, else `ERR_PURITY_BELOW_SPEC`. A batch of `FOOD_GRADE` or `WATER_CONDITIONING` must have `storage_kind` equal to `COVERED`, else `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`. The receiving depot must not be `CLOSED`, else `ERR_DEPOT_CLOSED`. And the tonnage must fit: for a `COVERED` batch, the depot's `covered_stored_tons` plus the batch's `yield_tons` must not exceed its `covered_capacity_tons`; for an `OPEN_PAD` batch, `open_pad_stored_tons` plus `yield_tons` must not exceed `open_pad_capacity_tons`. A breach is refused with `ERR_COVERED_CAPACITY_EXCEEDED`.

On a pass, the server mints a `StockpileLot` at the batch's `depot_id` with `tons_on_hand` and `tons_available` both equal to `yield_tons`, `tons_reserved` at 0, `lot_state` at `AVAILABLE`, and `product_line`, `purity_pct_nacl` and `storage_kind` copied from the batch. The new lot's `treatment_batch_id` records which batch minted it, and — since the mint has no response of its own — the lot is discoverable only through the lot list filtered by that batch (§2.10). The receiving depot's `covered_stored_tons` or `open_pad_stored_tons` grows by the yield according to the storage kind, `covered_utilization_pct` is recomputed, the depot is pushed `OPEN → SURGE` if the covered threshold of §3.6 is now met, and the depot's `version` increments by 1. The parent run's `open_batch_count` decreases by 1 and the run auto-closes if that brings it to 0.

### 3.6. Depots, Storm Posture and the Stockpile Ledger

A `LogisticsPlanner` opens a market-positioned depot by supplying its `name` (1 to 120 characters), the two-letter uppercase `state_code` of the market it serves, its `covered_capacity_tons` and `open_pad_capacity_tons` of enclosed and open storage (each at least 0), the sustained `loadout_rate_tons_per_hour` of its single loadout bay (strictly greater than zero), and the `outbound_freight_rate_per_ton` billed per ton shipped out to a customer (at least 0, three decimals). A new depot opens `OPEN`, with `covered_stored_tons`, `open_pad_stored_tons` and `covered_utilization_pct` all at 0, `storm_state_set_by_user_id` null, and `version` at 1.

Occupancy is derived, never posted. A depot's `covered_stored_tons` is the sum of `tons_on_hand` across the lots sitting at it whose `storage_kind` is `COVERED` and whose `lot_state` is `AVAILABLE` or `QUARANTINED`; `open_pad_stored_tons` is the same sum over `OPEN_PAD` lots. Quarantined tonnage still occupies the shed and still counts. `covered_utilization_pct` is `covered_stored_tons` multiplied by 100, divided by `covered_capacity_tons`, rounded half up to two decimal places — and it reads exactly 0 when `covered_capacity_tons` is 0, rather than erroring.

Capacities and rates can be revised in place by a `LogisticsPlanner`, or by the depot's own `DepotManager` under the ownership rule of §2.1, supplying any subset of `covered_capacity_tons`, `open_pad_capacity_tons`, `loadout_rate_tons_per_hour` and `outbound_freight_rate_per_ton`. The revision recomputes `covered_utilization_pct`, re-evaluates the storm threshold — shrinking `covered_capacity_tons` on a well-stocked depot can by itself push it `OPEN → SURGE` — and increments the depot's `version` by 1.

Storm posture is the depot's `depot_state`, one of `OPEN`, `SURGE` or `CLOSED`, and it cycles freely with no terminal value. A `DepotManager` or a `LogisticsPlanner` sets it explicitly by naming the target `depot_state` and optionally a `reason`; the value named must differ from the value currently held, and the manual call stamps `storm_state_set_by_user_id` with the caller's `X-User-ID`. All six manual edges are supported: `OPEN → SURGE`, `SURGE → OPEN`, `OPEN → CLOSED`, `SURGE → CLOSED`, `CLOSED → OPEN` and — reachable through `OPEN` — the return from closure. Each increments the depot's `version` by 1.

`SURGE` narrows rather than widens the depot's normal role: a depot in `SURGE` is a candidate for the allocation waterfall of `STORM_EMERGENCY` orders only, and drops out of the candidate pool for `ROUTINE` orders. `CLOSED` removes every lot at the depot from every future candidate pool for every class of order, and blocks batch intake, lot minting, shipments, receipts, manual reservations and new delivery orders against it. Existing `RESERVED` allocations at a depot that closes are **not** touched.

One posture edge fires by itself. Whenever tonnage lands at a depot — a quality-control pass minting a lot, or a shipment being received — the server tests the depot's `covered_stored_tons` multiplied by 100 against its `covered_capacity_tons` multiplied by 90, and a depot that is `OPEN` moves `OPEN → SURGE` when that product reaches or exceeds the threshold. The comparison is on the unrounded cross-multiplied ratio, not on the two-decimal `covered_utilization_pct` (see §2.7). An automatic move leaves `storm_state_set_by_user_id` untouched — it stays null when no manual call ever happened — and increments the depot's `version` by 1. The rule is one-directional and fires **only** when tonnage lands: a manual return `SURGE → OPEN` is permitted even while covered utilization is still at or above 90 percent, and tonnage leaving a depot never moves it back into `SURGE`.

A stockpile lot is never created directly by a client; it appears only as the product of a quality-control pass (§3.5) or a shipment receipt (§3.7). Its `depot_id` says where it physically sits and its `treatment_batch_id` traces the batch whose passing tonnage originated it, even after the tonnage has been moved between depots. A lot's `product_line`, `purity_pct_nacl` and `storage_kind` are all server-set copies: the first two from the minting batch (and preserved unchanged across every subsequent movement), and `storage_kind` from the batch at minting or from the shipment's declared destination storage at receipt.

Three tonnage figures live on each lot, and their relationship is a **conserved-quantity invariant** that must hold exactly, with zero drift at two decimal places, after every request that touches the lot: `tons_available` equals `tons_on_hand` minus the sum of `tons` across the lot's allocations whose `state` is `RESERVED`. Allocations that are `RELEASED` or `CONSUMED` contribute nothing to that sum, and `tons_reserved` is precisely that sum. The three operations that move these figures do so in three distinct shapes:

- **Reserving** tonnage raises `tons_reserved` and lowers `tons_available` by the reserved amount, and leaves `tons_on_hand` untouched. The salt has not moved; it has been promised.
- **Releasing** a reservation lowers `tons_reserved` and raises `tons_available` by the same amount, again leaving `tons_on_hand` untouched. A reservation followed by its release restores both `tons_available` and `tons_on_hand` to exactly their pre-reservation values.
- **Consuming** a reservation at delivery lowers `tons_reserved` and lowers `tons_on_hand` by the same amount, and leaves `tons_available` unchanged. Consumption moves the pile itself, so it is not compensable — there is no operation that un-delivers tonnage.

A lot's `lot_state` cycles between `AVAILABLE` and `QUARANTINED`, with `DEPLETED` as the one terminal value. A `QualityLab` operator, or the `DepotManager` of the depot holding the lot, quarantines or clears it with a boolean `quarantine` flag: true takes `AVAILABLE → QUARANTINED` and requires a `quarantine_reason`, which is stored as free text; false takes `QUARANTINED → AVAILABLE` and clears `quarantine_reason` back to null. Quarantine changes no tonnage at all — `tons_on_hand`, `tons_reserved` and `tons_available` all stand still, and the depot's stored-tonnage figures are unaffected, because quarantined salt still fills the shed. What quarantine does is make the lot invisible to every allocation waterfall and refuse every manual reservation against it with `ERR_LOT_QUARANTINED`. Existing `RESERVED` allocations on a quarantined lot are left alone. Each quarantine-state change bumps the lot's `version` by 1.

`DEPLETED` is reached in exactly one way: a shipment load drains the lot's `tons_on_hand` to exactly 0 while its `tons_reserved` also stands at 0. A depleted lot leaves every candidate set permanently. Because a depleted lot's available tonnage is 0, a reservation against it is refused for insufficient tonnage rather than for its state; a *quarantine-state change* against it, however, is refused with `ERR_LOT_STATE_INVALID`.

### 3.7. Repositioning Tonnage: Shipments and the Loadout Bay

Salt lands where it was treated, but storms arrive where they arrive, so tonnage is repositioned between depots. A `LogisticsPlanner`, or a `DepotManager`, books a shipment by naming the `stockpile_lot_id` being drawn down, the `origin_depot_id` holding it, the `destination_depot_id` receiving it, the `mode` of carriage (`RAIL`, `BARGE` or `TRUCK`), the `tons` to move (strictly greater than zero), the loadout bay window as `load_window_start` and `load_window_end` (the end strictly after the start), and the `destination_storage_kind` the tonnage will occupy on arrival. A new shipment opens with `status` at `PLANNED`, `received_lot_id` null, and `version` at 1. The `required_gap_minutes` field is server-set from the `mode` — 45 minutes for `RAIL`, 20 for `BARGE`, 0 for `TRUCK` — and records the switching or mooring separation that mode demands around its own window.

Booking is refused if the origin depot is `CLOSED` or the destination depot is `CLOSED`, both with `ERR_DEPOT_CLOSED`; if the source lot is not `AVAILABLE`, with `ERR_LOT_STATE_INVALID` (or `ERR_LOT_QUARANTINED` where the lot is specifically quarantined); if the lot's `tons_available` is less than the `tons` requested, with `ERR_INSUFFICIENT_LOT_TONS`; and if the declared `destination_storage_kind` is `OPEN_PAD` while the lot's `product_line` is `FOOD_GRADE` or `WATER_CONDITIONING`, with `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`.

The **loadout bay conflict** check then arbitrates shaft-like contention over the origin depot's single bay. Unlike the hoist windows of §3.4, bay windows are **closed** intervals — they include both endpoints — and the bay is strictly pairwise exclusive: no two shipments may share it at all, at any rate. Each mode also demands a buffer of clear time on both sides of its window: 45 minutes for `RAIL`, 20 minutes for `BARGE`, and 0 minutes for `TRUCK`. The check runs as follows:

1. Collect the peer set: every other shipment whose `origin_depot_id` is the same depot and whose `status` is either `PLANNED` or `LOADED`. Shipments that are `RECEIVED` or `CANCELLED` release the bay.
2. Order the peers by `load_window_start` ascending, and where two peers start at the same instant, by `created_at` ascending.
3. For each peer in that order, take the required gap as the **larger** of the new shipment's mode buffer and that peer's mode buffer. A truck booking beside a rail booking therefore still owes the full 45 minutes, because the rail move is the one that needs the room.
4. Expand the peer's window by that gap on both sides: the blocked region begins the gap's worth of minutes before the peer's `load_window_start` and ends the gap's worth of minutes after the peer's `load_window_end`.
5. The new shipment collides with that peer when its `load_window_start` is at or before the end of the blocked region **and** its `load_window_end` is at or after the beginning of the blocked region. Both comparisons are inclusive, so a window that merely grazes the blocked region's edge does collide.
6. The **first** peer that collides, in the order fixed at step 2, is the one reported, and the booking is refused with `ERR_LOADOUT_BAY_CONFLICT`.

Gaps are whole minutes and window instants are compared at second resolution, so a window starting one second after a 45-minute rail blocked region ends is clear, while one starting exactly at its final instant is not.

Loading advances `PLANNED → LOADED`. It is performed by the origin depot's own `DepotManager` — whose `X-User-ID` must equal the `origin_depot_id`, else `ERR_DEPOT_NOT_OWNED` — or by a `LogisticsPlanner`. The origin depot must not be `CLOSED`, the source lot must be `AVAILABLE`, and its `tons_available` must be at least the shipment's `tons`, else `ERR_INSUFFICIENT_LOT_TONS`. Loading takes the tonnage physically out of the origin pile: the lot's `tons_on_hand` and `tons_available` each fall by the shipment's `tons`, `tons_reserved` is untouched, the origin depot's stored-tonnage figures and `covered_utilization_pct` are recomputed, and a lot drained to exactly 0 `tons_on_hand` with 0 `tons_reserved` moves `AVAILABLE → DEPLETED`. The shipment's, the lot's and the origin depot's `version` each increment by 1.

Receipt advances `LOADED → RECEIVED`, terminal, and is performed by the destination depot's own `DepotManager` — whose `X-User-ID` must equal the `destination_depot_id` — or by a `LogisticsPlanner`. The destination must not be `CLOSED`; the `destination_storage_kind` must be `COVERED` when the tonnage's `product_line` is `FOOD_GRADE` or `WATER_CONDITIONING`; and the destination's free space in the declared storage kind — its capacity for that kind minus its stored tons for that kind — must be at least the shipment's `tons`, else `ERR_COVERED_CAPACITY_EXCEEDED`. Receipt **mints a new stockpile lot** at the destination with `tons_on_hand` and `tons_available` both equal to the shipment's `tons`, `tons_reserved` at 0, `lot_state` at `AVAILABLE`, `storage_kind` equal to the shipment's `destination_storage_kind`, and `treatment_batch_id`, `product_line` and `purity_pct_nacl` all copied from the source lot so that provenance and assay survive the move. The new lot's identifier is written into the shipment's `received_lot_id`. The destination depot's stored tonnage and `covered_utilization_pct` are recomputed and the automatic `OPEN → SURGE` test of §3.6 is applied. The shipment's and the destination depot's `version` each increment by 1.

Cancellation is terminal and reachable from both live states — `PLANNED → CANCELLED` and `LOADED → CANCELLED` — with a `reason` optionally supplied, and the two forms compensate differently. Cancelling a `PLANNED` shipment moves no tonnage at all — nothing has left the origin pile yet — and its only effect is to free the bay window, since a `CANCELLED` shipment drops out of the peer set at step 1 above. Cancelling a `LOADED` shipment must put the tonnage back: the source lot's `tons_on_hand` and `tons_available` each rise by the shipment's `tons`, a source lot that had gone `DEPLETED` on the load is restored to `AVAILABLE`, and the origin depot's stored tonnage and `covered_utilization_pct` are recomputed. That restoration is deliberately incomplete in one respect: a depot that was automatically moved `OPEN → SURGE` by tonnage landing is **not** moved back to `OPEN` when the tonnage is returned, because the automatic rule of §3.6 fires only when tonnage lands. Returning it requires a manual posture call. Cancelling a `LOADED` shipment also frees the bay window. Either form increments the shipment's `version` by 1, and the loaded form also increments the source lot's and origin depot's `version`.

### 3.8. Season Forecasting and the Bid Contract Lifecycle

Pre-season planning starts from a forecast. A `ContractAdministrator` or a `LogisticsPlanner` files one per market by supplying the `season_code` — a four-digit year, a hyphen, and a two-digit year, as in a winter spanning two calendar years — which must be unique per `region_code`; the `region_code` naming the sales region (1 to 30 characters); the `normal_season_tons` of a climatologically normal winter (strictly greater than zero); the `severity_index` for the coming winter as a whole number from 0 to 100 inclusive; the `prior_season_1_actual_tons`, `prior_season_2_actual_tons` and `prior_season_3_actual_tons` actually consumed in the three preceding winters, most recent first (each at least 0); the `method` selecting which stockpile target binds; and the `preseason_lock_date`, the instant after which contracts can no longer be activated for the season. A forecast's `severity_index`, `method` and `preseason_lock_date` may each be revised afterwards by a `ContractAdministrator`, and every such revision recomputes both targets and the spread between them.

The **pre-season stockpile target** is computed **twice** on every write, by two independent methods, and both results are always stored regardless of which one the forecast has selected.

The `target_tons_severity_weighted` variant treats the season as a probability mixture over three weather outcomes. The severe weight is the `severity_index` divided by 100. The mild weight is 100 minus the `severity_index`, divided by 100, and then multiplied by 0.40. The normal weight is whatever is left: one minus the severe weight minus the mild weight. Each weight is applied to a consumption scenario expressed as a multiple of `normal_season_tons` — 0.75 of normal in a mild winter, 1.00 in a normal winter, and 1.40 in a severe one — the three products are summed, that sum is multiplied by a safety-stock factor of 1.05, and the result is rounded half up to two decimal places.

The `target_tons_trailing_baseline` variant ignores the mixture and extrapolates from history. The three prior actuals are combined into a weighted trailing average that leans on recency: the most recent season's actual is weighted 3, the one before it 2, and the oldest 1, and the sum of those weighted actuals is divided by 6. That average is then multiplied by a severity uplift chosen by band — 1.00 when the `severity_index` is 40 or below, 1.10 when it falls anywhere from 41 through 70 inclusive, and 1.25 when it is 71 or above — multiplied by the same safety-stock factor of 1.05, and rounded half up to two decimal places. Note that the uplift is a step function, not an interpolation: an index of 70 and an index of 41 produce the identical 1.10 uplift, and an index of 71 jumps straight to 1.25.

The forecast's `binding_target_tons` is then set to whichever of the two the `method` names — the severity-weighted figure under `SEVERITY_WEIGHTED`, the trailing-baseline figure under `TRAILING_BASELINE`. The `variant_spread_tons` is the severity-weighted target minus the trailing-baseline target, rounded half up to two decimal places; it is **signed**, and a negative value is a meaningful and expected result whenever history runs hotter than the mixture model. Changing only the `method` on an existing forecast therefore leaves both `target_tons_severity_weighted` and `target_tons_trailing_baseline` and the `variant_spread_tons` exactly as they were and moves only the `binding_target_tons`.

A bid contract is the commercial commitment. A `ContractAdministrator` drafts one against a forecast by supplying the `season_forecast_id` that frames the season, the `customer_name` (1 to 120 characters), the `jurisdiction_level` of the buying authority (`MUNICIPAL`, `COUNTY` or `STATE`), the `state_code` of the market it will be served from, the `product_line` promised, the `committed_tons` promised for the season (strictly greater than zero), the `guaranteed_price_per_ton` at which every ton will be billed (strictly greater than zero, two decimals), the `min_take_pct` the customer must take to be in compliance (at least 50 and at most 100), the `max_take_pct` beyond which the customer may not draw (at least 100 and at most 200), the `failure_to_supply_penalty_per_ton` owed on tonnage not supplied (at least 0, two decimals), and the `price_guarantee_cap_pct` — the percentage above the guaranteed price at which the customer's exposure to market prices is capped (at least 0 and at most 50). A draft opens with `status` at `DRAFT`, `fulfilled_tons` at 0, `take_pct` at 0, `penalty_accrued_usd` at 0, `supply_reliability_score` at 100, `breach_watch` false, `contract_value_usd`, `season_penalty_usd`, `penalty_reconciliation_delta_usd`, `submitted_by_user_id` and `decided_by_user_id` all null, and `version` at 1.

Submitting a draft advances `DRAFT → SUBMITTED` and stamps `submitted_by_user_id` with the submitting `X-User-ID`. That stamp exists to be compared: the award or loss decision is a single operation carrying an `outcome` and an optional `note`, and the deciding `X-User-ID` must not equal the `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`. Either way the decider is recorded in `decided_by_user_id`.

The decision forks into two mutually exclusive branches, and the fork is genuine — neither branch is reachable from the other. An `outcome` of `AWARD` moves `SUBMITTED → AWARDED` and computes the contract's `contract_value_usd` as `committed_tons` multiplied by `guaranteed_price_per_ton`, rounded half up to two decimal places; the contract can then proceed to activation. An `outcome` of `LOSE` moves `SUBMITTED → LOST`, which is terminal: `contract_value_usd` stays null, because a lost bid has no value to compute, and no delivery order may ever reference a lost contract. Both branches increment the contract's `version` by 1.

Activation advances `AWARDED → ACTIVE` and is gated twice. First, the pre-season window must still be open: the logical clock must be at or before the forecast's `preseason_lock_date`, else `ERR_PRESEASON_WINDOW_CLOSED`. Second, the salt must actually be on the ground. The contract's pre-season coverage is the sum of `tons_available` across every stockpile lot whose `lot_state` is `AVAILABLE`, whose `product_line` matches the contract's `product_line`, and which sits at a depot whose `state_code` matches the contract's `state_code` and whose `depot_state` is `OPEN` or `SURGE`. Activation is refused with `ERR_PRESEASON_COVERAGE_SHORT` when that coverage is strictly less than `committed_tons` multiplied by `min_take_pct` divided by 100. Activation (re)initialises `supply_reliability_score` to 100 and `breach_watch` to false, and increments `version` by 1.

Closing the season is the second fork, and its branch is chosen by arithmetic rather than by the caller. A `ContractAdministrator` closes an `ACTIVE` contract with an optional `note`, and the server compares the contract's `take_pct` against its `min_take_pct`: a `take_pct` at or above the minimum takes `ACTIVE → CLOSED`, and a `take_pct` strictly below it takes `ACTIVE → FORFEITED`. Both branches are terminal and both do the same season-end accounting, described next; the forfeiture branch does one extra thing, deducting 25 points from the contract's `supply_reliability_score` with a floor of 0. Neither branch cascades to the contract's delivery orders: orders still sitting at `REQUESTED` or `SHORTED` keep exactly the status they held.

The season-end accounting computes the **aggregate** view of undersupply, which is a different calculation from the per-event penalty of §3.9 and coexists with it. The season shortfall is `committed_tons` minus `fulfilled_tons`, floored at 0. A tolerance band is then forgiven: `committed_tons` multiplied by the quantity 100 minus `min_take_pct`, divided by 100 — so a contract with a `min_take_pct` of 90 forgives the first 10 percent of its commitment outright. The billable shortfall is the season shortfall minus that tolerance, floored at 0, and the `season_penalty_usd` is the billable shortfall multiplied by `failure_to_supply_penalty_per_ton`, rounded half up to two decimal places. The aggregate variant deliberately applies **neither** the storm multiplier **nor** the per-order 15 percent cap that the per-event variant applies; conversely the per-event variant applies neither the tolerance band nor any notion of the season total. The `penalty_reconciliation_delta_usd` is then the `season_penalty_usd` minus the `penalty_accrued_usd` already booked event by event, rounded half up to two decimal places, and it is **signed** — negative whenever per-event accruals overshot the season view, which happens routinely because the per-event path forgives nothing.

Two derived figures on the contract are maintained continuously from the moment it becomes `ACTIVE`. `fulfilled_tons` is the sum of `allocated_tons` across the contract's delivery orders whose `status` is `DELIVERED` — only delivered orders count, so allocating tonnage moves nothing here. `open_committed_tons` is `committed_tons` minus `fulfilled_tons`, floored at 0, and `take_pct` is `fulfilled_tons` multiplied by 100, divided by `committed_tons`, rounded half up to two decimal places. `penalty_accrued_usd` is the sum of `shortfall_penalty_usd` across the contract's delivery orders whose `penalty_state` is `ACCRUED`, rounded half up to two decimal places, and `breach_watch` becomes true once that accrual reaches or exceeds 5 percent of `contract_value_usd` — the comparison being made against the unrounded product of `contract_value_usd` and 0.05, per §2.7.

The `supply_reliability_score` is a scorecard derived from the same ledger and never posted directly. Sum the `shorted_tons` across the contract's delivery orders whose `penalty_state` is `ACCRUED`; take that cumulative shortfall multiplied by 100, divided by `committed_tons`, rounded half up to two decimal places, and cap the resulting haircut at 40 points. Add a flat 25-point haircut when the contract's `status` is `FORFEITED`, and nothing otherwise. The score is 100 minus both haircuts, clamped to lie between 0 and 100 inclusive. Because the cumulative shortfall counts only orders still in the `ACCRUED` state, waiving a penalty removes that order's `shorted_tons` from the sum and lifts the score back up.

A last guard protects the upper edge of the take band. The tonnage a contract has already spoken for is the sum of `requested_tons` across its delivery orders whose `status` is `REQUESTED`, `ALLOCATED`, `SHORTED` or `DELIVERED` — every order that has not been withdrawn, whether or not it was ever filled. A new order is refused with `ERR_TAKE_BAND_EXCEEDED` when that consumed figure plus the new order's `requested_tons` would exceed `committed_tons` multiplied by `max_take_pct` divided by 100, the comparison again being made on the unrounded product.

### 3.9. Delivery Orders, the Storm Waterfall, Invoicing and Penalty Reconciliation

A delivery order is a customer's call on an `ACTIVE` contract. A `ContractAdministrator` or a `LogisticsPlanner` raises one by naming the `bid_contract_id` it draws against, the `depot_id` the customer would prefer to be served from, the `requested_tons` wanted (strictly greater than zero), the `required_by` instant by which the tonnage must be delivered (which must be strictly after the logical clock at the moment of creation), the `market_index_price_per_ton` prevailing when the order is raised (supplied by the caller, since the server has no market feed and it is needed for the price-guarantee credit), and optionally a `storm_priority` of `ROUTINE` or `STORM_EMERGENCY`, defaulting to `ROUTINE`. The `expected_bid_contract_version` required alongside them is described in §2.8. A new order opens with `status` at `REQUESTED`, `allocated_tons` and `shorted_tons` at 0, `penalty_state` at `NONE`, `shortfall_penalty_usd` at 0, `delivered_at` null, all five money fields — `product_subtotal_usd`, `freight_subtotal_usd`, `storm_surcharge_usd`, `guarantee_credit_usd` and `invoice_total_usd` — null until delivery, and `version` at 1. Creation is refused if the contract is not `ACTIVE` with `ERR_CONTRACT_INVALID_STATE`, if the named depot is `CLOSED` with `ERR_DEPOT_CLOSED`, and if the take band of §3.8 would be breached with `ERR_TAKE_BAND_EXCEEDED`. Creating an order also increments the parent contract's `version` by 1.

The **storm allocation waterfall** is the automatic fill, run by a `LogisticsPlanner` against a `REQUESTED` order. It selects candidate lots, ranks them deterministically, and draws them down in rank order until the request is satisfied or the candidates run out.

A lot is a candidate only when all of the following hold: its `product_line` equals the contract's `product_line`; its `lot_state` is `AVAILABLE`; its `tons_available` is strictly greater than 0; the `state_code` of the depot holding it equals the contract's `state_code`; and that depot's `depot_state` is admissible for the order's `storm_priority`. Admissibility is where storm priority bites: a `ROUTINE` order accepts only depots that are `OPEN`, while a `STORM_EMERGENCY` order accepts depots that are `OPEN` **or** `SURGE`. A `CLOSED` depot is admissible to neither. Surge depots are thus reserved for emergencies, and raising an order's priority genuinely widens the pool rather than merely reordering it.

Candidates are ranked by four keys applied in strict order, and the fourth is always sufficient to break any remaining tie:

1. Lots held at the order's own `depot_id` sort ahead of lots held anywhere else — the local shed is drawn down first.
2. Then by the holding depot's `outbound_freight_rate_per_ton`, ascending — the cheapest depot to ship out of comes next.
3. Then by the lot's `tons_available`, descending — bigger piles are consumed before smaller ones, so that fewer allocation rows are cut.
4. Then by the lot's `created_at`, ascending — the oldest pile of two otherwise identical lots goes first.

The lot's `id` is never a tie-break, so two lots that agree on all four keys must both be admissible answers only in the sense that the fourth key cannot in practice tie: `created_at` is the final arbiter and implementations must preserve creation ordering faithfully.

The fill then walks the ranked candidates. For each, the tonnage taken is the smaller of the tonnage still outstanding on the order and that lot's `tons_available`, and an allocation row is written with `tons` equal to that amount, `origin` set to `WATERFALL`, `state` set to `RESERVED`, and `rank_position` set to its position in the walk counting up from 1. Each write reserves against the lot per the invariant of §3.6 — `tons_reserved` up, `tons_available` down, `tons_on_hand` unchanged — and increments the lot's `version` by 1. The outstanding amount falls by the amount taken, and the walk stops when it reaches zero.

Three outcomes follow, and they are mutually exclusive:

- **Nothing allocated.** When no candidate lot exists at all, the request is refused with `ERR_NO_ELIGIBLE_STOCKPILE`. No allocation rows are written, no lot tonnage moves, and the order stays at `REQUESTED` — a failed waterfall leaves no trace and may be retried once salt arrives.
- **Fully allocated.** When the walk covers the whole `requested_tons`, the order moves `REQUESTED → ALLOCATED`, its `allocated_tons` is set to the `requested_tons`, its `shorted_tons` stays 0, and its `penalty_state` stays `NONE`.
- **Partially allocated.** When the walk allocates something but less than the whole `requested_tons`, the order moves `REQUESTED → SHORTED`, its `allocated_tons` is set to the amount actually reserved, and the penalty cascade below fires. The rows already written are kept — a short order is filled as far as the salt allowed.

The **per-event shortfall penalty** cascade runs in three hops on a short, and each hop is derived, not posted. Hop one, on the order: `shorted_tons` becomes `requested_tons` minus `allocated_tons`, and `shortfall_penalty_usd` is computed as the smaller of two quantities — the shortfall tonnage multiplied by the contract's `failure_to_supply_penalty_per_ton` multiplied by a storm multiplier of 2.00 for a `STORM_EMERGENCY` order or 1.00 for a `ROUTINE` one, and a cap of 15 percent of the order's own value, that value being `requested_tons` multiplied by `guaranteed_price_per_ton` rounded half up to two decimal places — with the chosen quantity rounded half up to two decimal places. The order's `penalty_state` becomes `ACCRUED`. Hop two, on the contract: `penalty_accrued_usd` and `supply_reliability_score` are both recomputed from the full ledger as described in §3.8, and the contract's `version` increments by 1. Hop three, still on the contract: `breach_watch` flips to true the moment the recomputed `penalty_accrued_usd` reaches or exceeds 5 percent of `contract_value_usd`. The third hop is reachable only through the second and the second only through the first, so a single short can move a field three entities' worth of derivation away from where the caller pointed.

Tonnage can also be reserved by hand, one row at a time, by a `LogisticsPlanner` naming the `delivery_order_id` to serve, the `stockpile_lot_id` to draw from, and the `tons` to take (strictly greater than zero), together with the `expected_stockpile_lot_version` described in §2.8. A manual row is written with `origin` set to `MANUAL`, `rank_position` at its default of 1, and `state` at `RESERVED`, and it reserves against the lot exactly as a waterfall row does. Manual reservation is refused when the order is not `REQUESTED`, `ALLOCATED` or `SHORTED` with `ERR_ORDER_INVALID_STATE`; when the lot is quarantined with `ERR_LOT_QUARANTINED` or otherwise not `AVAILABLE` with `ERR_LOT_STATE_INVALID`; when the lot's `product_line` differs from the contract's with `ERR_PRODUCT_LINE_MISMATCH`; when the lot's `tons_available` is less than the `tons` asked with `ERR_INSUFFICIENT_LOT_TONS`; and when the holding depot is `CLOSED` with `ERR_DEPOT_CLOSED`. A manual row updates the order's `allocated_tons` to the new sum of its reserved and consumed rows, and increments the order's, the lot's and the contract's `version` by 1.

Releasing is available at both granularities. A single allocation is released by a `LogisticsPlanner` with an optional `reason`, moving it `RESERVED → RELEASED`; it must be `RESERVED`, else `ERR_ALLOCATION_NOT_RESERVED`. Releasing returns the tonnage to the lot per the compensation rule of §3.6 — `tons_reserved` down, `tons_available` up, `tons_on_hand` unchanged — recomputes the order's `allocated_tons`, and increments the allocation's, the lot's and the order's `version` by 1. A `RELEASED` row is kept for audit; it is never deleted and never re-reserved.

Releasing an order's allocations wholesale, again by a `LogisticsPlanner` with an optional `reason`, moves every one of the order's `RESERVED` rows to `RELEASED`, returns each row's tonnage to its own lot, and walks the order back to `REQUESTED` — `ALLOCATED → REQUESTED` or `SHORTED → REQUESTED`. It resets the order's `allocated_tons` and `shorted_tons` to 0, returns its `penalty_state` to `NONE` and its `shortfall_penalty_usd` to 0, and recomputes the contract's `penalty_accrued_usd`, `supply_reliability_score` and `breach_watch` from the ledger that remains. Every touched lot's `version`, the order's `version` and the contract's `version` each increment by 1. The order is then a clean `REQUESTED` order again and may be re-allocated, possibly against a quite different set of lots.

Delivering is the terminal act on an order, performed by a `LogisticsPlanner` on an order that is `ALLOCATED` or `SHORTED` — a short order can indeed be delivered, for the tonnage it did secure. Delivery requires that the parent contract still be `ACTIVE`, else `ERR_CONTRACT_INVALID_STATE`, and that the logical clock be at or before the order's `required_by`; a late delivery is refused with `ERR_ORDER_INVALID_STATE`. Delivery takes every `RESERVED` allocation on the order through `RESERVED → CONSUMED`, drawing each row's tonnage out of its lot per the consumption rule of §3.6 — `tons_reserved` down, `tons_on_hand` down, `tons_available` unchanged — sets the order's `delivered_at` to the current logical clock, moves the order itself `ALLOCATED → DELIVERED` or `SHORTED → DELIVERED`, and recomputes the contract's `fulfilled_tons`, `open_committed_tons` and `take_pct`. An order that was `SHORTED` keeps its `shorted_tons`, its `shortfall_penalty_usd` and its `ACCRUED` `penalty_state` through delivery: the penalty was incurred by the short, not by the delivery.

Delivery is also when the invoice is computed, and the **order of rounding is pinned**. Each line is rounded to cents *first*, and only the already-rounded lines are summed; summing unrounded lines and rounding the total afterwards is wrong and will differ by cents on multi-line orders. The lines are the order's allocation rows whose `state` is `RESERVED` or `CONSUMED`, processed by `created_at` ascending; rows that are `RELEASED` are excluded entirely.

For each line, the product line amount is that row's `tons` multiplied by the contract's `guaranteed_price_per_ton`, rounded half up to two decimal places, and the freight line amount is that row's `tons` multiplied by the `outbound_freight_rate_per_ton` of the depot holding **that row's own lot** — the source depot, which is emphatically not necessarily the `depot_id` named on the order, since the waterfall may have drawn from several depots — again rounded half up to two decimal places. The order's `product_subtotal_usd` is the sum of the already-rounded product lines and its `freight_subtotal_usd` is the sum of the already-rounded freight lines.

The order's `storm_surcharge_usd` is 6 percent of the sum of those two subtotals, rounded half up to two decimal places, when the order's `storm_priority` is `STORM_EMERGENCY`, and is exactly 0.00 when it is `ROUTINE`.

The order's `guarantee_credit_usd` implements the price guarantee the contract sold. The guarantee ceiling per ton is the contract's `guaranteed_price_per_ton` multiplied by one plus its `price_guarantee_cap_pct` divided by 100, and that ceiling is **not** rounded. The credit is the amount by which the order's `market_index_price_per_ton` exceeds that ceiling — floored at 0, so a market at or below the ceiling yields no credit — multiplied by the order's total allocated tonnage, rounded half up to two decimal places.

The order's `invoice_total_usd` is then the `product_subtotal_usd` plus the `freight_subtotal_usd` plus the `storm_surcharge_usd` minus the `guarantee_credit_usd`, rounded half up to two decimal places. The credit is a subtraction, so a sufficiently high market index reduces the invoice; the total is not floored at zero by any separate rule.

Finally, an accrued penalty can be forgiven. A `ComplianceOfficer` or a `ContractAdministrator` waives one on an order whose `penalty_state` is `ACCRUED`, supplying a mandatory `waiver_reason`; an order whose `penalty_state` is `NONE` or already `WAIVED` refuses the request with `ERR_PENALTY_NOT_ACCRUED`. The waiver moves the order's `penalty_state` to `WAIVED` and **keeps** its `shortfall_penalty_usd` at the computed figure, because the audit record of what was forgiven is the point of the operation. What changes is the contract's ledger, and it changes by re-derivation rather than by subtraction: `penalty_accrued_usd` is recomputed as the sum over the orders that remain `ACCRUED`, and `breach_watch` and `supply_reliability_score` are recomputed from that same remaining set — so a waiver can flip `breach_watch` back to false and can lift the score. The order's `status` is untouched: a waived order that was `SHORTED` stays `SHORTED`, and a waived order that was `DELIVERED` stays `DELIVERED`. The order's and the contract's `version` each increment by 1.

This gives the penalty ledger a **second conserved-quantity invariant**, alongside the lot tonnage invariant of §3.6: at every moment, a contract's `penalty_accrued_usd` equals the sum of `shortfall_penalty_usd` over its orders whose `penalty_state` is `ACCRUED`, rounded half up to two decimal places. Accruing a penalty and then waiving it returns `penalty_accrued_usd` to exactly the value it held before the short, with no residue in cents, and returns `breach_watch` and `supply_reliability_score` to whatever the remaining ledger implies.

## 4. API Endpoints

Every endpoint below is served under the prefix shown and requires the `X-User-ID` and `X-User-Role` headers described in §2.1. Endpoints that create a resource answer with HTTP 201 and the created resource; endpoints that read, modify, transition or release answer with HTTP 200 and the resource as it stands after the call. Both shapes use the success envelope of §2.2, and list endpoints additionally populate the pagination fields of §2.3.

Where the authorization column reads "Any authenticated role", all seven roles of §2.1 may call the endpoint. Where it names roles, only those roles may call it; any other role is refused with `ERR_UNAUTHORIZED`, and role authorization is checked before the resource is looked up, per §2.6.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| `POST` | `/_clock/set_current_utc` | Set the server logical clock to the supplied instant (test-driving control). | Any authenticated role |
| `POST` | `/salt/mines` | Register a salt mine with its nameplate hoisting capacity. | `MinePlanner` |
| `GET` | `/salt/mines/{id}` | Read one mine, including both live state dimensions and derated capacity. | Any authenticated role |
| `GET` | `/salt/mines` | List mines, filterable by jurisdiction or by either state dimension. | Any authenticated role |
| `GET` | `/salt/mines/{id}/hoist-capacity` | Computed read: the derate factors behind the mine effective hoisting capacity, plus scheduled open tonnage. | `MinePlanner`, `GroundControlEngineer`, `LogisticsPlanner`, `ComplianceOfficer` |
| `POST` | `/salt/mines/{id}/hoist-status` | Set the shaft availability dimension of a mine. | `MinePlanner` |
| `POST` | `/salt/mines/{id}/compliance-action` | Record a regulatory action on the compliance dimension of a mine. | `ComplianceOfficer` |
| `POST` | `/salt/panels` | Lay out a room-and-pillar panel and compute its recoverable reserve. | `MinePlanner` |
| `GET` | `/salt/panels/{id}` | Read one panel with its computed reserve and ground-control flags. | Any authenticated role |
| `GET` | `/salt/panels` | List panels, filterable by parent mine and by panel state. | Any authenticated role |
| `POST` | `/salt/panels/{id}/develop` | Complete development entries and pillars on a planned panel. | `MinePlanner` |
| `POST` | `/salt/panels/{id}/start-production` | Bring a developed or suspended panel into production. | `MinePlanner` |
| `POST` | `/salt/panels/{id}/suspend` | Suspend an actively producing panel on ground-control grounds. | `GroundControlEngineer`, `ComplianceOfficer` |
| `POST` | `/salt/panels/{id}/remediate-defect` | Record remediation of the open ground-control defect on a panel. | `GroundControlEngineer` |
| `POST` | `/salt/panels/{id}/deplete` | Mine out a panel (terminal). | `MinePlanner` |
| `POST` | `/salt/panels/{id}/abandon` | Abandon a panel for ground-control or economic reasons (terminal). | `MinePlanner`, `ComplianceOfficer` |
| `POST` | `/salt/ground-control-inspections` | Append an immutable ground-control inspection record for a panel. | `GroundControlEngineer` |
| `GET` | `/salt/ground-control-inspections/{id}` | Read one inspection record. | Any authenticated role |
| `GET` | `/salt/ground-control-inspections` | List inspection records, filterable by panel and by result. | Any authenticated role |
| `POST` | `/salt/production-runs` | Schedule a hoisting run against a producing panel. | `MinePlanner` |
| `GET` | `/salt/production-runs/{id}` | Read one production run with its window and hold reason. | Any authenticated role |
| `GET` | `/salt/production-runs` | List production runs, filterable by mine, panel and status. | Any authenticated role |
| `POST` | `/salt/production-runs/{id}/hoist` | Record the tonnage actually brought to surface for a scheduled run. | `MinePlanner` |
| `POST` | `/salt/production-runs/{id}/close` | Close a hoisted run once no treatment batch on it is still pending. | `MinePlanner` |
| `POST` | `/salt/production-runs/{id}/reinstate` | Return a held run to the schedule, re-running every scheduling guard. | `MinePlanner` |
| `POST` | `/salt/treatment-batches` | Crush, screen and treat hoisted ore into a product-line batch and compute its yield and purity. | `QualityLab` |
| `GET` | `/salt/treatment-batches/{id}` | Read one treatment batch with its computed yield and purity. | Any authenticated role |
| `GET` | `/salt/treatment-batches` | List treatment batches, filterable by production run, depot, product line and quality state. | Any authenticated role |
| `POST` | `/salt/treatment-batches/{id}/qc-decision` | Decide a pending batch: pass it and mint a stockpile lot, fail it, or send it back for rework. | `QualityLab` |
| `POST` | `/salt/depots` | Open a market-positioned depot with covered and open-pad storage plus loadout and freight rates. | `LogisticsPlanner` |
| `GET` | `/salt/depots/{id}` | Read one depot with live storage occupancy and storm posture. | Any authenticated role |
| `GET` | `/salt/depots` | List depots, filterable by market state code and storm posture. | Any authenticated role |
| `GET` | `/salt/depots/{id}/storage-posture` | Computed read: covered and open-pad occupancy, utilization, free space and the automatic surge threshold. | `LogisticsPlanner`, `DepotManager`, `ContractAdministrator` |
| `PATCH` | `/salt/depots/{id}` | Adjust depot capacities and rates, re-evaluating utilization and the surge threshold. | `LogisticsPlanner`, `DepotManager` |
| `POST` | `/salt/depots/{id}/posture` | Set the storm posture of a depot explicitly. | `DepotManager`, `LogisticsPlanner` |
| `GET` | `/salt/stockpile-lots/{id}` | Read one stockpile lot with its three-way tonnage split. | Any authenticated role |
| `GET` | `/salt/stockpile-lots` | List stockpile lots, filterable by depot, minting batch, product line, storage kind and lot state. | Any authenticated role |
| `POST` | `/salt/stockpile-lots/{id}/quarantine-state` | Quarantine a lot or clear its quarantine. | `QualityLab`, `DepotManager` |
| `POST` | `/salt/shipments` | Plan a rail, barge or truck movement out of one depot loadout bay into another depot. | `LogisticsPlanner`, `DepotManager` |
| `GET` | `/salt/shipments/{id}` | Read one shipment with its bay window and required gap. | Any authenticated role |
| `GET` | `/salt/shipments` | List shipments, filterable by source lot, origin depot, destination depot, mode and status. | Any authenticated role |
| `POST` | `/salt/shipments/{id}/load` | Load a planned movement out of the origin bay, drawing down the source lot. | `DepotManager`, `LogisticsPlanner` |
| `POST` | `/salt/shipments/{id}/receive` | Receive a loaded movement at the destination depot, minting the destination lot. | `DepotManager`, `LogisticsPlanner` |
| `POST` | `/salt/shipments/{id}/cancel` | Cancel a planned or loaded movement, restoring tonnage where it had already left the origin pile (terminal). | `LogisticsPlanner`, `DepotManager` |
| `POST` | `/salt/season-forecasts` | Publish a season and region demand outlook, computing both pre-season stockpile targets and their spread. | `ContractAdministrator`, `LogisticsPlanner` |
| `GET` | `/salt/season-forecasts/{id}` | Read one forecast with both variant targets and their spread. | Any authenticated role |
| `GET` | `/salt/season-forecasts` | List forecasts, filterable by season code, region code and method. | Any authenticated role |
| `PATCH` | `/salt/season-forecasts/{id}` | Revise winter severity, switch the binding method, or move the pre-season lock date. | `ContractAdministrator` |
| `POST` | `/salt/bid-contracts` | Draft a deicing bid with a tonnage commitment, guaranteed price and take band. | `ContractAdministrator` |
| `GET` | `/salt/bid-contracts/{id}` | Read one contract with its live fulfillment and penalty ledger. | Any authenticated role |
| `GET` | `/salt/bid-contracts` | List contracts, filterable by forecast, state code, product line, jurisdiction level and status. | Any authenticated role |
| `GET` | `/salt/bid-contracts/{id}/ledger` | Computed read: the contract fulfillment ledger, take-band consumption, penalty ledger and reliability score. | `ContractAdministrator`, `ComplianceOfficer`, `LogisticsPlanner` |
| `POST` | `/salt/bid-contracts/{id}/submit` | Submit a drafted bid to the awarding jurisdiction. | `ContractAdministrator` |
| `POST` | `/salt/bid-contracts/{id}/decision` | Record the jurisdiction decision, awarding or losing the submitted bid. | `ContractAdministrator` |
| `POST` | `/salt/bid-contracts/{id}/activate` | Activate an awarded contract for the season, subject to the pre-season window and coverage gates. | `ContractAdministrator` |
| `POST` | `/salt/bid-contracts/{id}/close-season` | Close the season on an active contract, computing the aggregate penalty and reconciliation delta (terminal). | `ContractAdministrator` |
| `POST` | `/salt/delivery-orders` | Place a tonnage release against an active contract, routine or storm emergency. | `ContractAdministrator`, `LogisticsPlanner` |
| `GET` | `/salt/delivery-orders/{id}` | Read one delivery order with its allocation outcome, penalty state and invoice. | Any authenticated role |
| `GET` | `/salt/delivery-orders` | List delivery orders, filterable by contract, depot, status, storm priority and penalty state. | Any authenticated role |
| `POST` | `/salt/delivery-orders/{id}/allocate` | Run the storm-aware allocation waterfall over eligible stockpile lots. | `LogisticsPlanner` |
| `POST` | `/salt/delivery-orders/{id}/release-allocations` | Release every reserved allocation on the order and return it to the requested state. | `LogisticsPlanner` |
| `POST` | `/salt/delivery-orders/{id}/deliver` | Deliver the order, consume its reservations and compute its invoice (terminal). | `LogisticsPlanner` |
| `POST` | `/salt/delivery-orders/{id}/waive-penalty` | Waive the accrued failure-to-supply penalty on an order and re-derive the contract ledger. | `ComplianceOfficer`, `ContractAdministrator` |
| `POST` | `/salt/allocations` | Manually reserve tonnage from a named lot for a delivery order. | `LogisticsPlanner` |
| `GET` | `/salt/allocations/{id}` | Read one allocation line. | Any authenticated role |
| `GET` | `/salt/allocations` | List allocation lines, filterable by delivery order, lot, state and origin. | Any authenticated role |
| `POST` | `/salt/allocations/{id}/release` | Release a single reserved allocation line, returning its tonnage to the lot. | `LogisticsPlanner` |

## 5. Error Codes

Every rejection carries one of the identifiers below in the `error_id` field of the error envelope of §2.2, together with the HTTP status shown. When more than one condition holds on a single request, the identifier reported is the one whose stage comes first in the rejection precedence of §2.6.

| Error Code | HTTP Status |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_DEPOT_NOT_OWNED` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_MINE_NOT_FOUND` | 404 |
| `ERR_PANEL_NOT_FOUND` | 404 |
| `ERR_INSPECTION_NOT_FOUND` | 404 |
| `ERR_RUN_NOT_FOUND` | 404 |
| `ERR_BATCH_NOT_FOUND` | 404 |
| `ERR_DEPOT_NOT_FOUND` | 404 |
| `ERR_LOT_NOT_FOUND` | 404 |
| `ERR_SHIPMENT_NOT_FOUND` | 404 |
| `ERR_FORECAST_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_STALE_MINE_VERSION` | 412 |
| `ERR_STALE_BID_CONTRACT_VERSION` | 412 |
| `ERR_STALE_STOCKPILE_LOT_VERSION` | 412 |
| `ERR_CONTRACT_INVALID_STATE` | 409 |
| `ERR_ORDER_INVALID_STATE` | 409 |
| `ERR_PANEL_INVALID_STATE` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_SHIPMENT_INVALID_STATE` | 409 |
| `ERR_BATCH_QC_ALREADY_DECIDED` | 409 |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 |
| `ERR_ALLOCATION_NOT_RESERVED` | 409 |
| `ERR_LOT_QUARANTINED` | 409 |
| `ERR_LOT_STATE_INVALID` | 409 |
| `ERR_DEPOT_CLOSED` | 409 |
| `ERR_PENALTY_NOT_ACCRUED` | 409 |
| `ERR_MINE_WITHDRAWAL_ORDER_ACTIVE` | 409 |
| `ERR_HOIST_UNAVAILABLE` | 409 |
| `ERR_GROUND_CONTROL_DEFECT_OPEN` | 409 |
| `ERR_SCREEN_SPEC_NOT_ALLOWED` | 422 |
| `ERR_ADDITIVE_DOSE_OUT_OF_SPEC` | 422 |
| `ERR_PURITY_BELOW_SPEC` | 409 |
| `ERR_UNCOVERED_STORAGE_NOT_ALLOWED` | 409 |
| `ERR_PRODUCT_LINE_MISMATCH` | 409 |
| `ERR_PRESEASON_WINDOW_CLOSED` | 409 |
| `ERR_HOIST_CAPACITY_EXCEEDED` | 409 |
| `ERR_LOADOUT_BAY_CONFLICT` | 409 |
| `ERR_PANEL_RESERVE_EXCEEDED` | 409 |
| `ERR_COVERED_CAPACITY_EXCEEDED` | 409 |
| `ERR_INSUFFICIENT_LOT_TONS` | 409 |
| `ERR_NO_ELIGIBLE_STOCKPILE` | 409 |
| `ERR_TAKE_BAND_EXCEEDED` | 409 |
| `ERR_PRESEASON_COVERAGE_SHORT` | 409 |

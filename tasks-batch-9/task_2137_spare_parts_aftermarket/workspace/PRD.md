# Spare Parts Aftermarket API — Product Requirements Document

## 1. Introduction

An OEM aftermarket division lives or dies on a single unglamorous question: will the right part be on the right shelf on the day a machine stops working? Answering it well is not one problem but eight interlocking ones. Someone must know which parts fit which machines at which build revision. Someone must forecast demand from a thin, lumpy history of service jobs. Someone must decide which parts are worth stocking at all, and how deep. Someone must decide, in the middle of a breakdown, whether to fly a bracket across an ocean or let the customer wait. Someone must decide when a part is finished — and how many units to buy on the very last purchase order the supplier will ever accept. And someone must ration those last units fairly among dealers who all want more than exists. This document specifies the API that carries all eight decisions.

The service being specified is deliberately narrow in surface and deep in behaviour. It is not a warehouse management system and not an ERP; it holds no shipping documents, no invoices and no supplier contracts. What it does hold is the arithmetic and the state discipline that connect those eight decisions to one another. A demand forecast computed from closed work orders drives a criticality score; the criticality score selects a stocking policy and a pricing band; the pricing band determines what a dealer is charged when a technician fits the part; the amount charged determines what is credited back if the part comes home; and the stock movement that the return produces feeds back into the reorder point that triggers the next replenishment order. Every subsystem described below reads state written by at least two of the others, and the correctness of the whole rests on those hand-offs being exact.

Two design commitments shape everything that follows. First, **all time is logical time**: the service maintains a controllable clock rather than reading the host wall clock, so that forecast lookback windows, return-eligibility ages and campaign buy windows are reproducible. Second, **money is never approximated**: all monetary values are held as whole cents, all percentages are held to a fixed number of decimal places, and the order in which rounding is applied is pinned per consumer — because two defensible rounding orders on the same inputs produce two different prices, and the system must be unambiguous about which one a dealer is billed.

## 2. Global Specifications & System-Wide Principles

Every business resource in this service is mounted under the `/aftermarket` path prefix. The sole exception is the logical-clock control described in section 2.4, which is a test-driving facility rather than a business resource.

### 2.1. User and Role-Based Access Control

Authentication is header-based. Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is absent, or if `X-User-Role` is not one of the five role names below spelled exactly, the request is rejected with `ERR_UNAUTHENTICATED` and HTTP 401. If both headers are present and well-formed but the named role is not among the roles authorised for the requested operation in section 4, the request is rejected with `ERR_UNAUTHORIZED` and HTTP 403.

The five roles are:

- **`AftermarketPlanner`** — owns the part catalogue, the installed-base applicability map, forecasting, criticality classification, the obsolescence lifecycle and the returns desk.
- **`InventoryController`** — owns the money and the goods flow: authorises the lifetime buy, runs dealer allocation, and drives replenishment orders through both of their status dimensions.
- **`DealerUser`** — a dealer or distributor acting on its own machines: opens service work orders, requests and consumes parts, competes for last-time-buy allocation, and raises returns.
- **`PricingAnalyst`** — owns the aftermarket uplift and margin policy.
- **`PlatformAdmin`** — operational administrator for the registry side of the system: machine models, installed units, dealer master data, and the logical clock.

When `X-User-Role` is `DealerUser`, `X-User-ID` is the `id` of the acting `Dealer`; ownership checks on any resource that references a `Dealer` compare the resource's dealer foreign-key field to `X-User-ID`. Concretely, a `DealerUser` may act only where the `dealer_id` reachable from the target resource equals its own `X-User-ID` — directly on a service work order, indirectly through a part line's parent work order, directly on an allocation request, directly on a return authorization, or as the `dealer_id` supplied in a request body. A mismatch is rejected with `ERR_DEALER_SCOPE_VIOLATION` and HTTP 403. This scope check guards exactly eight operations: opening a work order, adding a part line to a work order, closing a work order, consuming a part line, cancelling a part line, creating an allocation request, withdrawing an allocation request, and creating a return authorization.

When `X-User-Role` is `AftermarketPlanner`, `InventoryController`, `PricingAnalyst` or `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `submitted_by_user_id` or `approved_by_user_id` on a `LastTimeBuyCampaign`, where the campaign workflow writes it — but it never compares such an identifier to any entity's `id`.

Recording those two operator identifiers exists for one reason: **segregation of duties**. The operator who submits a last-time-buy campaign for approval may not be the operator who approves or rejects it, even though both the `AftermarketPlanner` and the `InventoryController` role are permitted to submit. When the `X-User-ID` presented at approval or rejection equals the campaign's stored `submitted_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES` and HTTP 403.

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

Every collection-returning read accepts two optional query parameters. `limit` controls page size: it defaults to 10, may not be smaller than 1, and may not be larger than 100. `offset` controls the starting position: it defaults to 0 and may not be negative. A `limit` outside the range 1 to 100 inclusive is a malformed request and is rejected with `ERR_INVALID_REQUEST` and HTTP 400.

Unless a specific collection states otherwise, list results are ordered by `created_at` ascending — oldest first. Two collections override this default because their domain meaning demands it: the stock ledger of a part is returned oldest first ordered by `occurred_at` and then by `created_at` as a tie-break, and the forecast history of a part is returned newest first ordered by `computed_at` descending and then by `created_at` descending as a tie-break.

For every list response the `meta` object carries `limit` (the effective page size applied), `offset` (the effective starting position applied), `total_count` (the number of records matching the filter before pagination is applied), and `has_more` (true when records remain beyond the current page).

### 2.4. The Logical Clock

The service does not read the host wall clock. It maintains a single logical clock whose startup value is exactly `2026-08-01T00:00:00Z`; before any clock control call the logical clock reads that default, and it never falls back to real time. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant, and the response reports the new setting as `current_utc`. The clock is monotonic: a requested instant earlier than the current logical instant is rejected with `ERR_CLOCK_NOT_MONOTONIC` and HTTP 409, while an instant equal to the current one is accepted.

Every domain timestamp the service writes reads this clock — the `opened_at` and `closed_at` of a service work order, the `consumed_at` of a part line, the `occurred_at` of a stock ledger entry, and the `computed_at` of a demand forecast. Every age computation and every window computation — the forecast lookback window, the return-eligibility age, the last-time-buy window comparisons — likewise measures against this clock, not against real elapsed time.

### 2.5. Common Resource Properties and Path Resolution

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC format with three fractional digits. Almost every resource additionally carries an `updated_at` timestamp in the same format, refreshed on every mutation, and a `version`, an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation of that resource. The single exception is the stock ledger entry: because the ledger is append-only and a posted movement is never amended, a stock ledger entry carries only `id` and `created_at` — it has no `updated_at` field and no `version` field at all.

Path identifiers are resolved strictly left to right, and the first identifier that fails to resolve determines the error. A request addressing a forecast collection beneath a part fails with `ERR_PART_NOT_FOUND` when the part segment does not resolve, before anything else about the request is considered; a request addressing a part line collection beneath a work order fails with `ERR_WORK_ORDER_NOT_FOUND` when the work order segment does not resolve. Each resource family has its own not-found code, all carrying HTTP 404: `ERR_PART_NOT_FOUND`, `ERR_MODEL_NOT_FOUND`, `ERR_INSTALLED_UNIT_NOT_FOUND`, `ERR_DEALER_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_PART_LINE_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_ALLOCATION_REQUEST_NOT_FOUND`, `ERR_REPLENISHMENT_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND` and `ERR_APPLICABILITY_NOT_FOUND`. The same codes are used when a foreign key supplied in a request body fails to resolve; body foreign keys are validated in the order in which the endpoint's input list declares them.

### 2.6. Optimistic Concurrency on Parent Records

Two write operations in this system can silently destroy a record the caller never saw, so both are guarded by optimistic concurrency control against the `version` of a parent record. In both cases the version field is a required input, not an optional one, and a request that omits it is malformed.

A `POST /aftermarket/last-time-buy-campaigns` request must carry `expected_part_version`, holding the `version` of the target `Part` as the client last observed it. If that value does not equal the part's current `version`, the create is rejected with `ERR_STALE_PART_VERSION` and HTTP 412. The guard is necessary because a successful create legitimately supersedes any existing `DRAFT` campaign on the same part by moving it to `CANCELLED`; a client working from an out-of-date view of the part would otherwise destroy a draft it never read.

A `POST /aftermarket/allocation-requests` request must carry `expected_campaign_version`, holding the `version` of the target `LastTimeBuyCampaign` as the client last observed it. If that value does not equal the campaign's current `version`, the create is rejected with `ERR_STALE_CAMPAIGN_VERSION` and HTTP 412. Here too a successful create supersedes the same dealer's prior `PENDING` request on that campaign by moving it to `WITHDRAWN`, and the campaign's `version` also advances whenever the allocation waterfall runs or a grant is withdrawn — so a client holding an out-of-date view of the campaign must not be permitted to write.

No other endpoint takes a version field. Endpoints that are not named above must not require, and must not reject on, any expected-version input.

### 2.7. Rounding Discipline

All monetary amounts are integers denominated in whole cents; no field in this system holds a fractional cent. All percentages are decimal fractions where 0.15 means fifteen percent.

Wherever a value must be rounded, the method is round half up unless the specification for that value explicitly says ceiling or floor. Percentage-valued outputs are carried to four decimal places: `effective_uplift_pct`, `current_effective_uplift_pct`, `margin_pct`, `fee_pct` and `rebate_pct`. Score and rate outputs are carried to two decimal places: `criticality_score`, `annualized_wo_units` and `ib_rate_units`. Every cents-valued output is rounded to a whole integer.

The number of rounding steps matters as much as the method, and the specification for each calculation below pins both. Where a formula says a ceiling is applied "once, at the end", it means the intermediate value is carried unrounded up to that point. Where a formula rounds per unit and then multiplies, the result deliberately differs from multiplying first and rounding once; section 3.4 makes that divergence explicit and names which consumer gets which order.

### 2.8. Stock Position Arithmetic and the Append-Only Ledger

Each part carries four independently maintained physical counters plus one derived one. `on_hand_units` counts physically sellable units in the aftermarket warehouse. `allocated_units` counts units reserved against part lines currently in `RESERVED` status. `quarantine_units` counts units physically received back from dealers but not yet inspected. `in_transit_units` counts units on replenishment orders that have been approved and shipped but not yet received. The derived counter `available_units` is always `on_hand_units` minus `allocated_units`, and it is recomputed after every movement that touches either operand.

A part also carries `replenishment_status`, recomputed after every stock change and after every classification change. It is evaluated in this pinned order, and the first matching rule wins. First, if at least one replenishment order exists on this part whose approval dimension is anything other than `REJECTED` and whose logistics dimension is anything other than `RECEIVED`, the status reads `ON_ORDER`. Otherwise, if `reorder_point_units` is greater than zero and `available_units` is less than or equal to `reorder_point_units`, the status reads `BELOW_REORDER_POINT`. Otherwise the status reads `NORMAL`. A part that has never been classified has a `reorder_point_units` of 0 and therefore reads `NORMAL` regardless of how empty its shelf is.

Physical movements are recorded in an append-only stock ledger, one entry per movement. Each entry stores the `part_id` it belongs to, an `entry_type` of `RECEIPT`, `ISSUE`, `RETURN_RECEIPT` or `SCRAP`, a signed `delta_units` describing the change to the combined total of `on_hand_units` and `quarantine_units` — positive for `RECEIPT` and `RETURN_RECEIPT`, negative for `ISSUE` and `SCRAP` — and a `balance_after_units` recording the sum of `on_hand_units` and `quarantine_units` immediately after the entry is applied. Provenance is polymorphic and is deliberately not a declared foreign key: `source_ref_type` discriminates between `REPLENISHMENT_ORDER`, `WORK_ORDER_PART_LINE` and `RETURN_AUTHORIZATION`, and `source_ref_id` holds the identifier of the originating row, to be interpreted according to that discriminator. Finally `occurred_at` stamps the logical-clock instant of the movement.

One consequence of defining `delta_units` against the combined on-hand-plus-quarantine total deserves stating plainly: a movement that shifts units between quarantine and the sellable shelf changes neither total and therefore writes **no** ledger entry at all. Sections 3.8 spells out exactly which return outcome does and does not produce a ledger row.

### 2.9. Cascade Discipline

A single client request in this system routinely mutates more than one record. Where that happens, every affected record's `updated_at` is refreshed and every affected record's `version` increases by 1 — not only the record named in the request path. When a part line is consumed, for instance, the part's `version` advances even though the request addressed the line; when a last-time-buy campaign is approved, both the campaign's `version` and the part's `version` advance.

Cascades in this system are chained rather than parallel: one effect causes the next. Approving a lifetime buy sets the campaign's authorised quantity, which moves the part's lifecycle position, which changes the part's scarcity uplift, which re-quotes every open part line on that part. Each hop is a consequence of the previous hop, and all of them complete within the single request. There is no deferred or eventually-consistent settlement anywhere in this specification; when a request returns 2xx, every cascade it triggered is already durable.

### 2.10. Validation Precedence

When more than one rule could reject a request, the rules are evaluated strictly in the ascending priority order below and the **first** failing rule determines the response. This ordering is normative: a request that violates several rules always surfaces the lowest-numbered one, and a later rule can never mask an earlier one.

1. Both `X-User-ID` and `X-User-Role` are present, and `X-User-Role` is one of the five declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. The caller's role appears in the authorised-roles list for the endpoint — otherwise `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
3. Dealer scoping for a `DealerUser` as described in section 2.1 — otherwise `ERR_DEALER_SCOPE_VIOLATION` (403). Applies to the eight dealer-facing operations named there.
4. Segregation of duties on campaign approval and rejection — otherwise `ERR_SEGREGATION_OF_DUTIES` (403). Applies to campaign approve and campaign reject.
5. Every identifier in the URL path resolves, checked left to right — otherwise the matching not-found code (404). Applies to every endpoint with a path identifier.
6. Every foreign key in the request body resolves, checked in the order the endpoint declares its inputs — otherwise the matching not-found code (404). Applies to every creating endpoint carrying a foreign key.
7. The request body satisfies the endpoint's input schema: required fields present, enum members recognised, and integers inside their declared bounds — every quantity at least 1, `coverage_years` between 1 and 15 inclusive, `horizon_months` one of 12, 24 or 60, and `limit` between 1 and 100 inclusive. Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint.
8. The optimistic-concurrency version input matches the parent's current `version` as described in section 2.6 — otherwise `ERR_STALE_PART_VERSION` or `ERR_STALE_CAMPAIGN_VERSION` (412). Applies to campaign create and allocation-request create.
9. The target resource is in a state from which the requested transition is declared, including the cross-dimension guard on shipping a replenishment order and the cross-entity guards: submitting a campaign requires its part to be in `PHASE_OUT`; creating an allocation request requires the campaign to be in `APPROVED`; creating a return authorization requires the source line to be in `CONSUMED`; approving or receiving a replenishment order requires the part not to be `OBSOLETE`; and inspecting a return with a `RESTOCK` disposition requires the part not to be `OBSOLETE`. Otherwise the matching state code (409): `ERR_PART_LIFECYCLE_INVALID`, `ERR_CAMPAIGN_STATE_INVALID`, `ERR_ALLOCATION_STATE_INVALID`, `ERR_LINE_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`, `ERR_REPLENISHMENT_STATE_INVALID` or `ERR_RETURN_STATE_INVALID`. Applies to every action endpoint.
10. Part applicability to the machine being worked on — otherwise `ERR_PART_NOT_APPLICABLE` (422). Applies to adding a part line to a work order.
11. The air-freight decision did not resolve to air movement for a dangerous-goods part — otherwise `ERR_HAZMAT_AIR_PROHIBITED` (422). Applies to adding a part line to a work order and to creating a replenishment order.
12. The requested part is not in `SUPERSEDED` — otherwise `ERR_PART_SUPERSEDED` (422). Applies to adding a part line to a work order, creating a replenishment order, and creating a last-time-buy campaign.
13. The supersession chain stays acyclic — otherwise `ERR_SUPERSESSION_CYCLE` (409). Applies to superseding a part.
14. Exactly one active price rule exists for the part's criticality band — otherwise `ERR_PRICE_RULE_NOT_FOUND` (404). Applies to adding a part line to a work order, reading a price quote for a part, and classifying a part.
15. Build-revision applicability intervals do not overlap — otherwise `ERR_APPLICABILITY_REVISION_OVERLAP` (409). Applies to creating a part applicability row.
16. Last-time-buy windows do not intersect — otherwise `ERR_LTB_WINDOW_OVERLAP` (409). Applies to creating a campaign and to submitting a campaign.
17. Last-time-buy windows respect the cooldown buffer — otherwise `ERR_LTB_COOLDOWN_VIOLATION` (409). Applies to creating a campaign and to submitting a campaign.
18. The return is raised inside the return window — otherwise `ERR_RETURN_WINDOW_EXPIRED` (422). Applies to creating a return authorization.
19. The logical clock moves forward or stays put — otherwise `ERR_CLOCK_NOT_MONOTONIC` (409). Applies to the clock control.
20. An obsolete part with nothing available cannot go on a work order line — otherwise `ERR_PART_OBSOLETE_NO_SUPPLY` (422). Applies to adding a part line to a work order.
21. Cumulative returned quantity does not exceed the consumed quantity of the line — otherwise `ERR_RETURN_QTY_EXCEEDS_CONSUMED` (422). Applies to creating a return authorization.
22. Requested allocation does not exceed the campaign's remaining entitlement — otherwise `ERR_ALLOCATION_EXCEEDS_REMAINING` (409). Applies to creating an allocation request.
23. The allocation run has at least one eligible request — otherwise `ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS` (422). Applies to running the allocation waterfall.
24. The calculation has non-empty input — otherwise `ERR_FORECAST_INPUT_EMPTY` (422). Applies to computing a forecast, classifying a part, creating a campaign, and revising a campaign.
25. No unfinished line blocks the close — otherwise `ERR_OPEN_LINES_BLOCK_CLOSE` (409). Applies to closing a work order.
26. The base uplift does not exceed the maximum uplift on a rule being published — otherwise `ERR_UPLIFT_CAP_EXCEEDED` (422). Applies to creating a price rule.
27. The quoted margin clears the rule's floor — otherwise `ERR_MARGIN_FLOOR_BREACH` (422). Applies to adding a part line to a work order and to reading a price quote for a part.
28. An operator-raised emergency air replenishment order is justified by the stock position — otherwise `ERR_AIR_FREIGHT_NOT_JUSTIFIED` (422). Applies to creating a replenishment order.
29. The acting or referenced dealer is not on credit hold — otherwise `ERR_DEALER_CREDIT_HOLD` (402). Applies to adding a part line to a work order, consuming a part line, and creating an allocation request.

## 3. Business Logic & Workflows

### 3.1. The Registry: Machines, Dealers and the Installed Base

Before a single part can be planned, the service has to know what is out in the field. A `PlatformAdmin` registers each machine model with its `model_code`, which must be unique across all models, a marketing `name`, a `production_end_date` marking the instant serial production stopped, and a `support_end_date` marking the instant contractual aftermarket support ends. Both dates are ISO 8601 UTC instants.

Individual machines are then registered into the installed-base registry, again by a `PlatformAdmin`. Each installed unit names its `model_id`, the `dealer_id` of the dealer holding its service contract, a `serial_number` that must be unique across the whole registry, the `build_revision` stamped at assembly — a non-negative integer that turns out to be the pivot on which part applicability turns — the `commission_date` on which the machine entered service, and a `region` of `NA`, `EU`, `APAC` or `LATAM`. A newly registered unit has `status` `ACTIVE` and immediately enters the installed-base leg of every future forecast. When a machine leaves service it is decommissioned: its `status` becomes `DECOMMISSIONED`, its `version` advances, and from that moment it stops counting toward the installed-base population of any forecast and toward any dealer's installed-unit standing in the allocation waterfall. Installed machines can be listed and filtered by `model_id`, by `dealer_id` and by `status`.

Dealers are the commercial counterparties. A dealer is registered with a unique `dealer_code`, a commercial `tier` of `PLATINUM`, `GOLD` or `SILVER`, a primary service `region` drawn from the same four-value set as installed units, and a `credit_limit_cents` that may not be negative. At registration the dealer's `outstanding_balance_cents`, `lifetime_restocking_fee_cents` and `lifetime_rebate_cents` all start at 0, `credit_hold` is false and `status` is `ACTIVE`.

Two of those counters are cumulative ledgers that never decrease: `lifetime_restocking_fee_cents` accumulates every restocking fee retained from that dealer's returns, and `lifetime_rebate_cents` accumulates every loyalty rebate granted back. The receivable, `outstanding_balance_cents`, moves in both directions and is explicitly permitted to go negative when credits exceed charges. Derived from it is `credit_hold`, which is true exactly when `outstanding_balance_cents` is strictly greater than `credit_limit_cents`, and which is recomputed every single time the balance or the limit changes. A `PlatformAdmin` may post a manual movement to the receivable by supplying an `amount_cents` — positive for a debit, negative for a credit — together with a free-text `reason`; the amount is added to `outstanding_balance_cents`, `credit_hold` is recomputed against `credit_limit_cents`, and the dealer's `version` advances.

A dealer on credit hold is not merely flagged, it is blocked. Three operations refuse to proceed for a dealer whose `credit_hold` is true, each with `ERR_DEALER_CREDIT_HOLD` and HTTP 402: adding a part line to a work order, consuming a part line, and creating an allocation request. Separately, a `PlatformAdmin` may suspend a dealer outright, moving its `status` to `SUSPENDED` and advancing its `version`; a suspended dealer is excluded from the last-time-buy allocation candidate set entirely, which — as section 3.8 describes — is a different and harsher consequence than a credit hold.

### 3.2. The Part Catalogue and the Build-Revision Applicability Map

An `AftermarketPlanner` registers a spare part with its OEM `part_number`, which must be unique across the catalogue, a human-readable `description`, a `unit_cost_cents` landed acquisition cost of at least 1 cent, a `lead_time_days` standard non-air replenishment lead time of zero days or more, and a `weight_kg` shipping weight per unit that must be strictly greater than zero. Two further inputs are optional: `hazmat`, defaulting to false, marks the part as dangerous goods that may not move by air; and `max_stock_units`, defaulting to 0 and never negative, sets the target maximum on-hand position that the automatic replenishment cascade aims at.

Everything else about a newly registered part is derived. Its `lifecycle_state` is `ACTIVE` and its `superseded_by_part_id` is null — that self-referential successor pointer is non-null only while the part sits in `SUPERSEDED`. Its `criticality_score` is 0, its `criticality_class` is `DESIRABLE`, its `stocking_policy` is `MAKE_TO_ORDER`, and both `safety_stock_units` and `reorder_point_units` are 0. All four stock counters — `on_hand_units`, `allocated_units`, `quarantine_units` and `in_transit_units` — start at 0, `available_units` is therefore 0, and `replenishment_status` reads `NORMAL`. The two catalogue price fields, `current_effective_uplift_pct` and `current_list_unit_price_cents`, are computed immediately when an active price rule for the `DESIRABLE` band exists; when no such rule has been published yet, both simply stay at 0 and registration still succeeds.

Master data stays amendable. A planner may revise any subset of `description`, `unit_cost_cents`, `lead_time_days`, `weight_kg`, `hazmat` and `max_stock_units` on an existing part; every such amendment recomputes `current_effective_uplift_pct` and `current_list_unit_price_cents` and advances the part's `version`. The catalogue can be listed with filters on `lifecycle_state`, on `criticality_class`, and — this is the self-referential reverse lookup — on `superseded_by_part_id`, which returns every predecessor part that points at one nominated successor.

Applicability is the bridge between the catalogue and the fleet, and it is a genuine many-to-many relationship carrying its own data. A planner declares that a part fits a model over a range of build revisions by supplying the `part_id`, the `model_id`, an `effective_from_build_revision` giving the lowest revision the part fits (inclusive, and never negative), an optional `effective_to_build_revision` giving the highest revision it fits (also inclusive, with omission or null meaning unbounded above), and a `qty_per_unit` of at least 1 recording how many of the part are installed on one machine of that model. A newly declared row has `applicability_status` `ACTIVE`.

Overlapping declarations would make coverage ambiguous, so the service refuses them. The new build-revision range is treated as a **closed integer interval**, with a null upper bound treated as extending to positive infinity, and it must not intersect the range of any existing `ACTIVE` applicability row for the same part-and-model pair. Rows in `WITHDRAWN` are excluded from this check entirely. Note the integer geometry carefully: adjacency is permitted, so a new range whose lower bound is one greater than an existing row's upper bound is accepted, whereas a new range whose lower bound equals that existing upper bound is rejected with `ERR_APPLICABILITY_REVISION_OVERLAP`. Withdrawing an applicability row moves its `applicability_status` to `WITHDRAWN` and advances its `version`; from then on the row is ignored by the overlap check, ignored when validating whether a part may go on a work order line, and ignored by the installed-base leg of forecasting. Applicability rows can be listed and filtered by `part_id`, `model_id` and `applicability_status`.

### 3.3. Forecasting Demand from Service History and Fleet Size

A demand forecast is a computed snapshot, not an editable record. A planner asks for one on a specific part by naming a `horizon_months` — which must be 12, 24 or 60 — a `method`, and optionally a `lookback_days` window width that defaults to 365 days and must be at least 1. The forecast that comes back is stamped with `computed_at` from the logical clock and carries `forecast_status` `CURRENT`; creating it moves any prior forecast for the same part and the same `horizon_months` to `forecast_status` `SUPERSEDED`, so exactly one current row exists per part-and-horizon pair. Forecast history for a part can be filtered by `horizon_months` and by `forecast_status`.

The calculation has two independent legs, and both are always computed regardless of which `method` is selected.

The **work-order history leg** starts from a strictly defined input set. It considers only part lines whose part is the part being forecast, whose `line_status` is `CONSUMED`, whose parent work order has `status` `CLOSED`, and whose parent work order's `closed_at` falls inside a half-open window ending at the current logical instant. The window opens strictly after the instant that is `lookback_days` before now and closes at and including now — a work order closed at exactly the instant `lookback_days` before now is **excluded**, while one closed at exactly the current instant is included. Summing `qty_consumed` across that input set gives `wo_history_units`. Annualising it gives `annualized_wo_units`, which is `wo_history_units` multiplied by 365, divided by `lookback_days`, and rounded half up to two decimal places.

The **installed-base leg** counts machines rather than history. It considers installed units whose `status` is `ACTIVE` and whose `model_id` is covered by an `ACTIVE` applicability row for the part being forecast — covered meaning that the row's `effective_from_build_revision` is less than or equal to the machine's `build_revision`, and that either the row's `effective_to_build_revision` is null or the machine's `build_revision` is less than or equal to it. The size of that set is `installed_base_units`. Multiplying it by the `qty_per_unit` taken from the single covering `ACTIVE` applicability row, and then by an annual replacement rate of twenty percent of the installed population per year, and rounding the product half up to two decimal places, gives `ib_rate_units`. Because the create-time overlap rule already makes two active covering rows impossible for the same pair, exactly one `qty_per_unit` is ever in play.

The `method` then selects which leg to believe. Under `WORK_ORDER_HISTORY` the raw annual figure is `annualized_wo_units` alone — the installed base is ignored entirely, so a part with heavy field consumption against a small fleet forecasts high. Under `INSTALLED_BASE_RATE` the raw figure is `ib_rate_units` alone — consumption history is ignored entirely, so a newly launched part with no closed work orders at all still forecasts a non-zero number. Under `BLENDED` the raw figure weights the history leg at sixty percent and the installed-base leg at the remaining forty percent, and that weighted sum is itself rounded half up to two decimal places; for identical inputs it always lands strictly between the two single-leg variants. Whichever variant applies, `forecast_units` is the raw figure rounded **up** to the next whole unit, with that ceiling applied exactly once and only at the very end.

One guard applies at the input boundary. When the requested `method` is `WORK_ORDER_HISTORY` and the qualifying consumed-line input set is empty, the service refuses to manufacture a zero forecast and rejects the request with `ERR_FORECAST_INPUT_EMPTY`.

### 3.4. Criticality Classification and Stocking Policy

Classification is what turns a forecast into an inventory decision, and a planner triggers it on one part at a time. It reads exactly one forecast: the part's `CURRENT` forecast whose `horizon_months` is 12. If no such forecast exists, classification is refused with `ERR_FORECAST_INPUT_EMPTY` — a part must be forecast before it can be classified.

Four component scores are summed. The **demand component** is the forecast's `forecast_units` multiplied by two, capped so that it can never exceed 40 points however large the forecast grows. The **downtime component** measures how often this part is the reason a machine is on the floor: it looks at consumed part lines on this part whose parent work order is `CLOSED` and whose `closed_at` falls in the same half-open window used by the forecast, opening strictly after the instant that is the forecast's own `lookback_days` before now and closing at and including now. It counts **lines**, not units. When that set is empty the downtime component is 0; otherwise it is 30 points multiplied by the fraction of those lines whose parent work order has `downtime_priority` `MACHINE_DOWN`, rounded half up to two decimal places. The **lead-time component** is 20 points when the part's `lead_time_days` is 60 days or more, 12 points when it is at least 30 days but less than 60, and 5 points otherwise. The **coverage component** is 10 points when the forecast's `installed_base_units` is 4 or more, 6 points when it is at least 2 but fewer than 4, and 2 points otherwise. Adding all four and rounding half up to two decimal places yields `criticality_score`.

Banding is inclusive at both thresholds. A `criticality_score` of 70 or more makes the part `VITAL`; a score of at least 40 but below 70 makes it `ESSENTIAL`; anything below 40 makes it `DESIRABLE`. The boundary is exact — a score of exactly 70.00 is `VITAL`, and 69.99 is `ESSENTIAL`.

`stocking_policy` is then decided with the zero-demand case taking precedence over the band. When the forecast's `forecast_units` is 0 the policy is `NO_STOCK` no matter what the score said. Otherwise a `VITAL` part gets `STOCK_TO_MAX`, an `ESSENTIAL` part gets `MIN_MAX`, and a `DESIRABLE` part gets `MAKE_TO_ORDER`.

Buffer sizing follows, and its rounding order is pinned. Daily demand is the forecast's `forecast_units` divided by 365 and is **never** rounded — it is carried as an exact rational through both expressions below. A service factor is selected by band: 1.65 for `VITAL`, 1.28 for `ESSENTIAL`, and 0.84 for `DESIRABLE`. `safety_stock_units` is daily demand multiplied by the part's `lead_time_days` and then by that service factor, with a ceiling applied once at the end of that product. `reorder_point_units` is `safety_stock_units` plus a second, separately ceilinged quantity: daily demand multiplied by `lead_time_days`, rounded up once. To be unambiguous: the reorder point is safety stock plus the ceiling of cycle demand; it is **not** the ceiling of daily demand multiplied by lead time multiplied by one plus the service factor, and the two expressions genuinely differ.

Classification finishes by re-pricing and re-reading the stock position. `current_effective_uplift_pct` and `current_list_unit_price_cents` are recomputed against the active price rule for the **new** `criticality_class` — and if no active rule exists for that band, classification is refused with `ERR_PRICE_RULE_NOT_FOUND`. `replenishment_status` is then recomputed against the new `reorder_point_units`, which is frequently the moment a previously quiet part first reads `BELOW_REORDER_POINT`. The part's `version` advances.

### 3.5. Aftermarket Pricing: Uplift Bands and Two Rounding Variants

A `PricingAnalyst` publishes uplift policy one criticality band at a time. A price rule names the `criticality_class` it prices — `VITAL`, `ESSENTIAL` or `DESIRABLE` — a `base_uplift_pct` of zero or more carried to four decimal places, a `max_uplift_pct` acting as a hard ceiling, and a `min_margin_pct` that must be at least zero and strictly below 1. Publishing a rule whose `base_uplift_pct` is greater than its `max_uplift_pct` is refused with `ERR_UPLIFT_CAP_EXCEEDED`. A newly published rule has `rule_status` `ACTIVE`, and any rule previously `ACTIVE` for the same band is moved to `rule_status` `RETIRED` — so at most one active rule exists per band at any moment. Rules can be listed and filtered by `criticality_class` and by `rule_status`.

Pricing a part begins by selecting the single `ACTIVE` rule whose `criticality_class` matches the part's own. To that rule's `base_uplift_pct` the service adds a **scarcity uplift** determined solely by the part's `lifecycle_state`: nothing at all while the part is `ACTIVE`, four percentage points once it is in `PHASE_OUT`, eight points while a last-time buy is open in `LTB_OPEN`, fifteen points once that buy is closed in `LTB_CLOSED`, fifteen points again once the part is `OBSOLETE`, and nothing at all for a part in `SUPERSEDED`. The sum is then capped at the rule's `max_uplift_pct` — that is, the smaller of the cap and the sum is taken — and rounded half up to four decimal places to give `effective_uplift_pct`.

From that single uplift the service derives two deliberately different money figures, and the difference is a rounding-order difference, not a rate difference.

- The **LIST** variant rounds first and multiplies second. `list_unit_price_cents` is the part's `unit_cost_cents` multiplied by one plus `effective_uplift_pct`, rounded half up to a whole cent at the **unit** level. `list_line_total_cents` is then that already-rounded unit price multiplied by the quantity.
- The **QUOTE** variant multiplies first and rounds second. `quoted_line_total_cents` is the part's `unit_cost_cents` multiplied by the quantity and then by one plus `effective_uplift_pct`, with a single half-up rounding to a whole cent applied **once**, at line level.

`variant_delta_cents` records the divergence as `list_line_total_cents` minus `quoted_line_total_cents`. That divergence is real and its sign is not constant. With a `unit_cost_cents` of 1333, an `effective_uplift_pct` of 0.35 and a quantity of 7, the LIST variant yields a unit price of 1800 and a line total of 12600 while the QUOTE variant yields 12597 — a positive three-cent delta. With the same cost and quantity at an uplift of 0.43, LIST yields 13342 and QUOTE yields 13343, so the delta flips negative. Which figure governs is fixed and must never be swapped: **the catalogue price shown per unit is always the LIST variant, and the money a dealer is actually charged is always the QUOTE variant.**

`margin_pct` is computed off the QUOTE figure: it is `quoted_line_total_cents` minus the extended acquisition cost — that is, `unit_cost_cents` multiplied by the quantity — divided by `quoted_line_total_cents`, rounded half up to four decimal places. When `margin_pct` falls below the matched rule's `min_margin_pct`, the operation is refused with `ERR_MARGIN_FLOOR_BREACH`.

The part's own catalogue fields are simply this calculation evaluated at a quantity of one: `current_effective_uplift_pct` holds the `effective_uplift_pct` and `current_list_unit_price_cents` holds the LIST unit price. A `PricingAnalyst`, an `AftermarketPlanner` or a `DealerUser` may also ask for a hypothetical quote on a part by supplying a `qty`; the response returns `effective_uplift_pct`, `list_unit_price_cents`, `list_line_total_cents`, `quoted_line_total_cents`, `variant_delta_cents` and `margin_pct` side by side, and it is subject to both the missing-rule and the margin-floor rejections.

The missing-rule rejection has one important carve-out. `ERR_PRICE_RULE_NOT_FOUND` is raised only on the three client-facing operations that price on demand: adding a part line to a work order, reading a hypothetical price quote for a part, and classifying a part. A **cascaded** re-price — one triggered by a change of the part's `lifecycle_state` rather than by a client request — is a no-op when no active rule matches the band: `current_effective_uplift_pct` and `current_list_unit_price_cents` keep whatever values they already held, and no error is raised. A lifecycle transition must never fail because pricing policy happens to be unpublished.

### 3.6. Service Work Orders, Part Lines and the Air-Freight Decision

A `DealerUser` opens a service work order against one of its own machines by naming the `installed_unit_id`, the `work_type` — `SCHEDULED_MAINTENANCE`, `BREAKDOWN` or `CAMPAIGN` — and the `downtime_priority` of `MACHINE_DOWN`, `DEGRADED` or `PLANNED`, which classifies how badly the machine is impaired. The work order's `dealer_id` is not supplied by the caller; it is copied from the installed unit's own `dealer_id` at creation. The new work order has `status` `OPEN`, an `opened_at` stamped from the logical clock, and a `closed_at` of null. Work orders can be listed and filtered by `installed_unit_id`, by `dealer_id` and by `status`.

Adding a part line is the busiest single operation in the system: it runs an applicability gate, a fulfilment decision and both pricing variants inside one request. The caller supplies only a `part_id` and a `qty_requested` of at least 1. The work order must be `OPEN`; adding a line to a work order in any other status is refused with `ERR_WORK_ORDER_STATE_INVALID`. Before anything is computed, four business gates fire in the precedence order laid out in section 2.10. The part must be applicable to this exact machine — an `ACTIVE` applicability row must exist whose part matches, whose model matches the machine's `model_id`, and whose build-revision interval covers the machine's `build_revision` — or the line is refused with `ERR_PART_NOT_APPLICABLE`. A part in `SUPERSEDED` may not be ordered at all and must be ordered through the successor named by its `superseded_by_part_id` instead, giving `ERR_PART_SUPERSEDED`. A part in `OBSOLETE` whose `available_units` has reached 0 cannot be put on a line either, giving `ERR_PART_OBSOLETE_NO_SUPPLY`. And the dealer must not be on credit hold.

The **fulfilment decision** then weighs four inputs that interact non-linearly: the stock position, the downtime class of the job, the physical weight of the part, and the commercial tier of the dealer. First, an expected wait is established: zero days when `available_units` is at least `qty_requested`, and otherwise the part's full `lead_time_days`. A downtime cost is that wait multiplied by a daily rate keyed on the work order's `downtime_priority` — 250000 cents per day of downtime for a `MACHINE_DOWN` job, 60000 cents per day for a `DEGRADED` one, and nothing at all for a `PLANNED` one, which is why planned work never justifies expediting on cost grounds alone.

An air-freight cost is built in parallel. Billable weight is the part's `weight_kg` multiplied by the requested quantity and then rounded **up** to a whole kilogram. The raw charge is that billable weight at 2000 cents per kilogram plus a flat handling fee of 10000 cents; if the part's `hazmat` flag is true a dangerous-goods surcharge of 30000 cents is added on top. The final `air_freight_cost_cents` is the larger of that raw charge and a minimum charge of 45000 cents. Subtracting the air-freight cost from the downtime cost gives `decision_net_benefit_cents`, which is stored on the line.

`fulfillment_mode` is then resolved by walking four branches strictly top to bottom, where the first match wins and no later branch is evaluated:

1. If `available_units` is at least `qty_requested`, the mode is `STOCK`. Stock on the shelf always wins, whatever the arithmetic elsewhere says.
2. Otherwise, if the part's `lifecycle_state` is `OBSOLETE`, the mode is `BACKORDER`. An obsolete part is never expedited.
3. Otherwise, if the owning dealer's `tier` is `PLATINUM` **and** the work order's `downtime_priority` is `MACHINE_DOWN`, the mode is `AIR_FREIGHT`. This is a contractual override and is entirely independent of `decision_net_benefit_cents`.
4. Otherwise, if `decision_net_benefit_cents` is **strictly greater** than 100000 cents, the mode is `AIR_FREIGHT`. The comparison is strict: a net benefit of exactly 100000 does **not** expedite.
5. Failing all of those, the mode is `BACKORDER`.

`freight_cost_cents` on the line is the computed air-freight cost when the mode resolved to `AIR_FREIGHT`, and 0 in every other case. If the mode resolved to `AIR_FREIGHT` for a part whose `hazmat` is true, the request is refused with `ERR_HAZMAT_AIR_PROHIBITED`. Note the ordering carefully: the dangerous-goods surcharge is still added into the air cost **before** the decision is taken, because that surcharge can be exactly what pushes the net benefit below the threshold and causes the branch to resolve to `BACKORDER` instead — in which case no rejection occurs at all.

A part line is born in `line_status` `REQUESTED`, but that status is transient: the create request resolves it in the same call, and no client ever observes a line sitting in `REQUESTED` unless the system is mid-request. Pricing runs on the same request, writing `effective_uplift_pct`, `list_unit_price_cents`, `list_line_total_cents`, `quoted_line_total_cents`, `variant_delta_cents` and `margin_pct` onto the line using `qty_requested` as the quantity. The line's `qty_consumed` starts at 0, its `charged_amount_cents` starts at 0 and its `consumed_at` is null.

Where the line lands depends on the mode. A `STOCK` decision puts the line straight into `line_status` `RESERVED`, raises the part's `allocated_units` by `qty_requested`, recomputes `available_units`, and advances the part's `version`. An `AIR_FREIGHT` or `BACKORDER` decision instead puts the line into `line_status` `BACKORDERED` and moves the parent work order from `OPEN` to `PARTS_PENDING`. On the `AIR_FREIGHT` branch only, a replenishment order is additionally auto-created for the part with `order_type` `EMERGENCY_AIR`, a `qty` equal to `qty_requested`, `auto_generated` set to true, `approval_status` `PENDING`, `logistics_status` `NOT_STARTED`, and a `freight_cost_cents` equal to the line's own freight figure. Lines can be listed and filtered by `work_order_id`, by `part_id` and by `line_status`.

**Consuming** a line is where goods and money both move. A `DealerUser` supplies the `qty_consumed` actually fitted; it must be at least 1 and no more than `qty_requested`, the line must be in `RESERVED` — anything else is `ERR_LINE_STATE_INVALID` — the parent work order must still be `OPEN`, and the dealer must not be on credit hold. The consequences chain. `qty_consumed` is stored and `consumed_at` is stamped from the logical clock; the part's `allocated_units` falls by the full `qty_requested` (the whole reservation is released, not merely the fitted portion) while `on_hand_units` falls by `qty_consumed`; and one ledger entry is appended with `entry_type` `ISSUE` and a `delta_units` equal to the negative of `qty_consumed`. The dealer is then billed: `charged_amount_cents` is the part's `unit_cost_cents` multiplied by `qty_consumed` and then by one plus the line's `effective_uplift_pct`, rounded half up to a whole cent; that amount is added to the dealer's `outstanding_balance_cents`, and the dealer's `credit_hold` is recomputed.

The second hop follows from the first: `available_units` is recomputed, and if it has fallen to or below `reorder_point_units` the part's `replenishment_status` moves from `NORMAL` to `BELOW_REORDER_POINT`. The third hop follows from the second: when the part's `stocking_policy` is either `STOCK_TO_MAX` or `MIN_MAX` and the part is now `BELOW_REORDER_POINT`, a replenishment order is auto-created with `order_type` `STOCK`, `auto_generated` true, `approval_status` `PENDING` and `logistics_status` `NOT_STARTED`, and a `qty` equal to the part's `max_stock_units` less its `available_units` less its `in_transit_units`, floored at a minimum of 1 unit so that the order is never empty. Because that order now exists and is neither rejected nor received, the part's `replenishment_status` immediately reads `ON_ORDER` rather than `BELOW_REORDER_POINT`. The part's `version` advances once for the whole chain.

**Cancelling** a line is permitted from `REQUESTED`, from `RESERVED` and from `BACKORDERED`, and always lands in `CANCELLED`; attempting it on a line already `CONSUMED` or `CANCELLED` gives `ERR_LINE_STATE_INVALID`. The three source states behave differently and the differences matter. Cancelling from `REQUESTED` has no side effects at all. Cancelling from `RESERVED` releases the reservation — `allocated_units` falls by `qty_requested`, `available_units` is recomputed, and the part's `version` advances. Cancelling from `BACKORDERED` touches no stock counter but may unblock the parent work order: when the cancelled line was the last one on that work order in `BACKORDERED`, the work order moves from `PARTS_PENDING` back to `OPEN`. That return edge is general — a work order leaves `PARTS_PENDING` for `OPEN` whenever the count of its lines in `BACKORDERED` reaches zero, whether the last such line was cancelled or promoted into `RESERVED`.

**Closing** a work order requires it to be in `OPEN` and requires that no line on it sits in `REQUESTED`, `RESERVED` or `BACKORDERED`; an unfinished line blocks the close with `ERR_OPEN_LINES_BLOCK_CLOSE`, and closing a work order that is not `OPEN` gives `ERR_WORK_ORDER_STATE_INVALID`. On close, `closed_at` is stamped from the logical clock and the work order's `version` advances. Closing matters beyond bookkeeping: it is exactly the moment at which the work order's `CONSUMED` lines become eligible inputs to the forecasting history leg described in section 3.3.

### 3.7. Replenishment Orders and the Backorder Promotion Sweep

An `InventoryController` raises a replenishment order by naming the `part_id`, an `order_type` of either `STOCK` for the routine sea or ground buy or `EMERGENCY_AIR` for the expedited one, and a `qty` of at least 1. The part's `unit_cost_cents` is snapshotted onto the order at creation so that later master-data amendments cannot rewrite history. `freight_cost_cents` is 0 for a `STOCK` order; for an `EMERGENCY_AIR` order it is the air-freight cost computed exactly as in section 3.6 — billable weight being the part's `weight_kg` times the ordered quantity rounded up to whole kilograms, charged at 2000 cents per kilogram, plus the 10000-cent handling fee, plus the 30000-cent dangerous-goods surcharge where `hazmat` is true, and then floored at the 45000-cent minimum charge. `total_landed_cost_cents` is the snapshotted `unit_cost_cents` multiplied by `qty` plus `freight_cost_cents`. A newly raised order has `approval_status` `PENDING`, `logistics_status` `NOT_STARTED` and `auto_generated` false — the flag is true only for the two orders the system raises on its own behalf, described in section 3.6.

Two rules police operator-raised orders. Expediting must be justified by the stock position: an `EMERGENCY_AIR` order raised by an operator is accepted only when the part's `replenishment_status` is `BELOW_REORDER_POINT`, and otherwise refused with `ERR_AIR_FREIGHT_NOT_JUSTIFIED`. And dangerous goods may not fly: an `EMERGENCY_AIR` order on a part whose `hazmat` is true is refused with `ERR_HAZMAT_AIR_PROHIBITED`. A part in `SUPERSEDED` cannot be replenished either and gives `ERR_PART_SUPERSEDED`.

A replenishment order then advances along **two independent dimensions**. `approval_status` tracks the spend decision and `logistics_status` tracks the physical movement, and neither is a stage of the other. Approving moves `approval_status` from `PENDING` to `APPROVED` and deliberately leaves `logistics_status` untouched at `NOT_STARTED`; it requires the part not to be `OBSOLETE`, and it advances the order's `version`. Rejecting moves `approval_status` from `PENDING` to `REJECTED`, accepts an optional `rejection_reason`, and is permitted only while `logistics_status` is still `NOT_STARTED`; because a rejected order no longer counts as outstanding, the part's `replenishment_status` is recomputed afterwards and will fall back to `BELOW_REORDER_POINT` when `available_units` is at or below `reorder_point_units` and no other non-rejected order remains on the part. Any approve or reject attempted against a dimension that is not `PENDING` is refused with `ERR_REPLENISHMENT_STATE_INVALID`.

Shipping is the one place where the two dimensions touch. Moving `logistics_status` from `NOT_STARTED` to `IN_TRANSIT` requires `logistics_status` to be `NOT_STARTED` **and** `approval_status` to be `APPROVED`; shipping an unapproved order is refused with `ERR_REPLENISHMENT_STATE_INVALID`. On shipment the part's `in_transit_units` rises by the order's `qty`, the part's `replenishment_status` is set to `ON_ORDER`, and both the part's `version` and the order's `version` advance.

Receiving closes the loop. It requires `logistics_status` to be `IN_TRANSIT` and the part not to be `OBSOLETE`. The part's `in_transit_units` falls by `qty` while `on_hand_units` rises by the same `qty`; one ledger entry is appended with `entry_type` `RECEIPT`, a positive `delta_units` equal to `qty`, a `balance_after_units` equal to the part's `on_hand_units` plus `quarantine_units` immediately afterwards, and a `source_ref_type` of `REPLENISHMENT_ORDER` with the order's identifier in `source_ref_id`. `available_units` and `replenishment_status` are then recomputed, and both the part's `version` and the order's `version` advance.

Receiving also triggers the **backorder promotion sweep**, and the sweep's ordering is normative. The candidates are every part line on the received part whose `line_status` is `BACKORDERED`. They are sorted by three keys in this order: first by the downtime rank of their parent work order's `downtime_priority`, ascending, where `MACHINE_DOWN` ranks 0, `DEGRADED` ranks 1 and `PLANNED` ranks 2; then by `qty_requested` ascending, so that small jobs clear first; and finally by `created_at` ascending as the tie-break. No identifier is ever part of the sort key. The sweep is then a single greedy pass, **not** a best-fit search: the sorted list is walked exactly once, and a line is promoted from `BACKORDERED` to `RESERVED` only when the part's `available_units` is at least that line's `qty_requested` at the moment the line is considered. Each promotion raises `allocated_units` by that line's `qty_requested`, which immediately lowers `available_units` for every line still to be considered. A line that does not fit is simply skipped and the sweep continues to the next one — so a large `MACHINE_DOWN` line can be passed over while a smaller `DEGRADED` line behind it is promoted. An empty candidate set is a no-op, not an error. Once the sweep completes, any work order that no longer has a line in `BACKORDERED` moves from `PARTS_PENDING` back to `OPEN`.

Replenishment orders can be listed and filtered by `part_id`, by `order_type`, by `approval_status`, by `logistics_status` and by `auto_generated`. The stock ledger of a part can be read on its own and filtered by `entry_type`.

### 3.8. Obsolescence: Phase-Out, the Last-Time Buy and Dealer Allocation

The obsolescence lifecycle is the spine that connects pricing, planning and dealer politics, and it runs through six positions of `lifecycle_state`.

A planner opens the workflow by phasing a part out, moving `lifecycle_state` from `ACTIVE` to `PHASE_OUT`; a part in any other state gives `ERR_PART_LIFECYCLE_INVALID`. Phase-out immediately re-prices the part at the four-point `PHASE_OUT` scarcity uplift and **re-quotes every open line on that part** — every line whose `line_status` is `REQUESTED`, `RESERVED` or `BACKORDERED` has its `effective_uplift_pct`, `list_unit_price_cents`, `list_line_total_cents`, `quoted_line_total_cents`, `variant_delta_cents` and `margin_pct` recomputed. The part's `version` advances.

Phase-out is reversible while nothing has been committed. Reinstating a part moves it from `PHASE_OUT` back to `ACTIVE`, but only when no campaign on that part is currently `SUBMITTED`, `APPROVED` or `ALLOCATING`; a part not in `PHASE_OUT`, or one with a live campaign in any of those three states, gives `ERR_PART_LIFECYCLE_INVALID`. Reinstatement re-prices at a zero scarcity uplift, re-quotes the same set of open lines with the same six figures, and advances the part's `version`.

Supersession is a side branch out of the lifecycle rather than a step along it, and it can be taken from `ACTIVE` or from `PHASE_OUT`. The planner supplies a `successor_part_id`; the successor must exist and must not itself be `OBSOLETE`, though a successor that is itself `SUPERSEDED` is perfectly legal because catalogue chains from one part to a second to a third are ordinary practice. Precisely because such chains are legal, the chain must be checked: walking the successor's own `superseded_by_part_id` pointer transitively must never arrive back at the part being superseded, and a chain that closes on itself is refused with `ERR_SUPERSESSION_CYCLE`. On success the part's `superseded_by_part_id` is set to the nominated successor, its `lifecycle_state` becomes `SUPERSEDED`, and its `stocking_policy` becomes `NO_STOCK`. Its open lines are then wound up: every line in `REQUESTED` or `BACKORDERED` moves to `CANCELLED`, and every line in `RESERVED` also moves to `CANCELLED` and additionally releases the part's `allocated_units` by that line's `qty_requested`. The part's `version` advances. The `ACTIVE`-to-`SUPERSEDED` edge and the `PHASE_OUT`-to-`SUPERSEDED` edge carry an identical precondition set and an identical side-effect set; nothing about them differs except the starting state.

At the far end of the lifecycle, a part moves from `LTB_CLOSED` to `OBSOLETE`, and only from `LTB_CLOSED`. Obsoleting sets `stocking_policy` to `NO_STOCK` and zeroes both `safety_stock_units` and `reorder_point_units`; every replenishment order on the part whose `approval_status` is still `PENDING` is moved to `approval_status` `REJECTED`; `current_list_unit_price_cents` is recomputed at the fifteen-point `OBSOLETE` scarcity uplift; and the part's `version` advances. `OBSOLETE` and `SUPERSEDED` are both terminal — no transition leads out of either.

**The last-time-buy campaign.** A planner drafts a campaign by naming the `part_id`, the sizing `method` — either `DEMAND_DECAY` or `FLAT_RATE` — a `coverage_years` between 1 and 15 inclusive stating how many years of post-obsolescence demand the buy must cover, an inclusive `ltb_window_start` and an exclusive `ltb_window_end` bounding the supplier's buy window, and the `expected_part_version` demanded by section 2.6. The part must not be `SUPERSEDED`. The campaign snapshots `annual_demand_units` from the `forecast_units` of the part's `CURRENT` 12-month forecast, and refuses with `ERR_FORECAST_INPUT_EMPTY` when no such forecast exists. It starts with `status` `DRAFT`, a `revision_index` of 0, an `approved_qty` of 0, a `remaining_qty` of 0, and both `submitted_by_user_id` and `approved_by_user_id` null. Any campaign already in `DRAFT` on the same part is moved to `CANCELLED` — that superseded draft's `approved_qty` and `remaining_qty` both stay 0, because a draft never held an entitlement in the first place. The part's `version` advances. Campaigns can be listed and filtered by `part_id` and by `status`.

**Sizing the buy.** What the shelf already covers is the part's `on_hand_units` plus its `in_transit_units`. Under the `FLAT_RATE` variant the requirement is simply `annual_demand_units` multiplied by `coverage_years`, and `proposed_qty` is that requirement less the existing cover, floored at 0. Under the `DEMAND_DECAY` variant the fleet is assumed to retire, so each successive year's demand is `annual_demand_units` multiplied by a decay factor of 0.85 raised to the power of that year's index counted from zero — the first year is full demand, the second is 85 percent of it, the third is 85 percent of that, and so on for `coverage_years` years. Crucially, **each year's figure is rounded half up to a whole unit before it is added into the running total, and the total is never re-rounded afterwards.** `proposed_qty` is then that total less the existing cover, floored at 0. The two variants diverge sharply on identical inputs: with an annual demand of 10 units, a coverage of 5 years and an existing cover of 20 units, the decayed years are 10, 9, 7, 6 and 5 for a total of 37 and a `proposed_qty` of 17, whereas the flat-rate requirement is 50 for a `proposed_qty` of 30.

**Window geometry.** Two campaigns on the same part may not compete for the same supplier window, and the geometry is checked in two stages against every other campaign on that part whose `status` is `SUBMITTED`, `APPROVED` or `ALLOCATING`. The first stage treats the window as **half-open** — inclusive of `ltb_window_start`, exclusive of `ltb_window_end` — and refuses any new window that intersects an existing one with `ERR_LTB_WINDOW_OVERLAP`. Under half-open geometry two windows that merely touch, where the new window's start equals the other's end, do **not** intersect and pass this stage. The second stage then imposes a symmetric 30-day cooldown buffer on the windows that survived: the new window's start must be at least 30 days after the other window's end, **or** the new window's end plus 30 days must be at or before the other window's start. Anything falling inside that buffer is refused with `ERR_LTB_COOLDOWN_VIOLATION`. Note the deliberate contrast with the build-revision geometry of section 3.2: adjacency is accepted there and rejected here. Both stages are applied at draft creation and applied again at submission.

**The approval cycle.** Submitting moves the campaign from `DRAFT` to `SUBMITTED`, requires the part to be in `PHASE_OUT`, re-checks both window stages, and stamps `submitted_by_user_id` with the caller's `X-User-ID`. Submission is open to both an `AftermarketPlanner` and an `InventoryController`, which is precisely what gives segregation of duties its bite. Approving requires `status` `SUBMITTED`, an `approved_qty` of at least 1 supplied in the request, and an approver whose `X-User-ID` differs from `submitted_by_user_id`. Approval sets `approved_qty`, sets `remaining_qty` equal to it, and stamps `approved_by_user_id` — and that first hop causes a chain: the part moves from `PHASE_OUT` to `LTB_OPEN`, which causes the part to be re-priced at the eight-point `LTB_OPEN` scarcity uplift, which in turn causes every line on that part in `REQUESTED`, `RESERVED` or `BACKORDERED` to be re-quoted with all six pricing figures changing. Both the part's `version` and the campaign's `version` advance. Rejecting requires `status` `SUBMITTED` and the same non-self constraint; it stores the supplied `rejection_reason`, advances the campaign's `version`, and deliberately leaves the part where it was, in `PHASE_OUT`.

A rejected campaign is not dead. Revising it moves it from `REJECTED` back to `DRAFT`, increments `revision_index` by 1, clears both `submitted_by_user_id` and `rejection_reason` back to null, re-snapshots `annual_demand_units` from the part's `CURRENT` 12-month forecast (refusing with `ERR_FORECAST_INPUT_EMPTY` if that forecast has since disappeared) and recomputes `proposed_qty`. The revise request may optionally supply a replacement `method` or `coverage_years`. That draft-submit-reject-revise loop can run as many times as needed. Any of these transitions attempted from the wrong campaign state is refused with `ERR_CAMPAIGN_STATE_INVALID`.

**Dealer allocation.** While a campaign is `APPROVED`, dealers compete for its units. A `DealerUser` creates an allocation request naming the `campaign_id`, its own `dealer_id`, the `requested_units` it wants (at least 1), and the `expected_campaign_version` demanded by section 2.6. The campaign must be in `APPROVED`, the dealer must not be on credit hold, and `requested_units` may not exceed the campaign's current `remaining_qty` at the moment the request is created — an over-ask is refused with `ERR_ALLOCATION_EXCEEDS_REMAINING`. The new request starts with `status` `PENDING`, `granted_units` 0, `priority_score` 0 and `dealer_installed_units` 0, and it supersedes that same dealer's prior `PENDING` request on the same campaign by moving it to `WITHDRAWN`. The campaign's `version` advances. Requests can be listed and filtered by `campaign_id`, by `dealer_id` and by `status`.

Running the allocation moves the campaign from `APPROVED` to `ALLOCATING`, and it requires at least one request on the campaign that is `PENDING` and whose dealer's `status` is `ACTIVE`; with no such request the run is refused with `ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS` and the campaign stays in `APPROVED`. Requests belonging to a dealer whose `status` is `SUSPENDED` are not candidates at all — they are moved straight from `PENDING` to `DENIED` with `granted_units` left at 0.

Each candidate is ranked. Its `dealer_installed_units` is counted as the number of installed units belonging to that dealer whose `status` is `ACTIVE` and which are covered by an `ACTIVE` applicability row for the campaign's part, using exactly the same build-revision coverage predicate as the forecasting installed-base leg. Its `priority_score` is then a tier weight — 50 for `PLATINUM`, 30 for `GOLD`, 10 for `SILVER` — plus an installed-base weight, which is three points for every complete pair of covered machines the dealer owns (that is, the dealer's covered machine count halved and rounded down, then multiplied by three) capped at 30 points, minus a penalty of 20 points when the dealer's `credit_hold` is true, with the whole expression floored at 0. Both `priority_score` and `dealer_installed_units` are snapshotted onto the request at allocation time. Candidates are then ordered by `priority_score` descending, then by `requested_units` descending, then by `created_at` ascending; no identifier is ever part of the sort key.

The award itself runs in two passes. The first pass is an equal fair share, computed as half of the campaign's `approved_qty` divided by the number of candidates and rounded **down** to a whole unit; each candidate is granted the smaller of its `requested_units` and that fair share. Whatever of `approved_qty` is left after the first pass then flows down the sort order in a strict waterfall: each candidate in turn takes the smaller of its own unmet request and the units still unallocated, until either every request is satisfied or nothing remains. A candidate ending with a grant equal to its `requested_units` moves from `PENDING` to `GRANTED`; one ending with a grant above 0 but below its request moves to `PARTIALLY_GRANTED`; one ending with nothing moves to `DENIED`. The campaign's `remaining_qty` becomes whatever is still unallocated after the second pass, and the invariant to hold at all times is that `approved_qty` equals `remaining_qty` plus the sum of `granted_units` across every request now in `GRANTED` or `PARTIALLY_GRANTED`. The campaign's `version` advances.

Withdrawal is the compensating move that keeps that invariant true. A request still in `PENDING` may be withdrawn by its own `DealerUser` or by an `AftermarketPlanner`, moving it to `WITHDRAWN` with no change to the campaign's `remaining_qty` — its `granted_units` was 0 anyway. A request in `GRANTED` or `PARTIALLY_GRANTED` may also be withdrawn, but only while the campaign is still `ALLOCATING`; doing so adds that request's `granted_units` back to the campaign's `remaining_qty`, resets the request's `granted_units` to 0, moves it to `WITHDRAWN`, and advances the campaign's `version`. Withdrawing a request already in `DENIED` or `WITHDRAWN`, or withdrawing a granted request when the campaign is not `ALLOCATING`, is refused with `ERR_ALLOCATION_STATE_INVALID`.

Closing the campaign moves it from `ALLOCATING` to `CLOSED`. Every request on it still in `PENDING` is moved to `DENIED`, and the part moves from `LTB_OPEN` to `LTB_CLOSED` — which, being a lifecycle change, re-prices the part at the fifteen-point `LTB_CLOSED` scarcity uplift and re-quotes every open line on it, exactly as the earlier lifecycle hops did. Both the part's `version` and the campaign's `version` advance. `CLOSED` and `CANCELLED` are the campaign's terminal states.

### 3.9. Returns: Restocking Fees, Loyalty Rebates and the Inspection Fork

A return authorization is raised by a `DealerUser` against one specific consumed line, naming the `work_order_part_line_id`, the `qty_returned` of at least 1, and a `return_reason` of `WRONG_PART`, `UNUSED_SURPLUS`, `DEFECTIVE` or `CORE_RETURN`. The source line must be in `line_status` `CONSUMED`; anything else gives `ERR_LINE_STATE_INVALID`. The return's own `part_id` and `dealer_id` are copied from the line and its parent work order rather than supplied by the caller, and it starts in `status` `REQUESTED` with a `disposition` of null and a `credit_posted_cents` of 0. Returns can be listed and filtered by `part_id`, by `dealer_id`, by `work_order_part_line_id` and by `status`.

Two eligibility rules apply before any arithmetic. The return must be timely: `age_days`, the number of whole days from the line's `consumed_at` to the current logical instant with any partial day discarded, may not exceed 180 days, and an older return is refused with `ERR_RETURN_WINDOW_EXPIRED`. And the return must not over-return: the requested `qty_returned` plus the `qty_returned` of every return authorization already raised against the same line and not in `REJECTED` may not exceed that line's `qty_consumed`, or the request is refused with `ERR_RETURN_QTY_EXCEEDS_CONSUMED`.

The whole credit is computed at creation, in a **pinned five-step order** that is never re-entered.

1. `gross_credit_cents` is the pro-rated share of what the dealer was actually charged: the line's `charged_amount_cents` multiplied by `qty_returned`, divided by the line's `qty_consumed`, rounded half up to a whole cent.
2. `age_days` is established as described above.
3. `fee_pct` is assembled from three additive components and then capped. The base component depends on `return_reason`: fifteen percent for `UNUSED_SURPLUS`, and nothing at all for `WRONG_PART`, for `DEFECTIVE` and for `CORE_RETURN`. The age surcharge is nothing when `age_days` is 30 or fewer, ten percentage points when `age_days` is more than 30 but no more than 90, and twenty-five percentage points beyond that. The obsolescence surcharge is twenty percentage points when the part's `lifecycle_state` at the moment the return is raised is either `LTB_CLOSED` or `OBSOLETE`, and nothing otherwise. The three are added, the total is capped at fifty percent — that is, the smaller of the cap and the sum is taken — and the result is rounded half up to four decimal places to give `fee_pct`. `restocking_fee_cents` is then `gross_credit_cents` multiplied by `fee_pct`, rounded half up to a whole cent. Note that the fee is computed off the gross amount, before any rebate exists.
4. `net_before_rebate_cents` is `gross_credit_cents` less `restocking_fee_cents`, floored at 0.
5. `rebate_pct` is a loyalty tier keyed on `net_before_rebate_cents` — five percent when that net is 500000 cents or more, two percent when it is at least 200000 cents but below 500000, and nothing below that. `loyalty_rebate_cents` is `net_before_rebate_cents` multiplied by `rebate_pct`, rounded half up to a whole cent, and `final_credit_cents` is `net_before_rebate_cents` plus `loyalty_rebate_cents`.

The circularity in step 5 is only apparent, and the resolution is normative: the rebate tier is keyed on the step-4 value and **never** on the final credit that the rebate itself produces. Even when adding the rebate pushes `final_credit_cents` across a higher tier boundary, the tier is not re-opened.

None of that money moves yet. A newly raised return has computed `age_days`, `gross_credit_cents`, `fee_pct`, `restocking_fee_cents`, `net_before_rebate_cents`, `rebate_pct`, `loyalty_rebate_cents` and `final_credit_cents`, but no stock has moved, no ledger row exists and `credit_posted_cents` remains 0.

An `AftermarketPlanner` then works the return through its lifecycle. Approving moves it from `REQUESTED` to `APPROVED` with no side effects whatsoever. Rejecting moves it from `REQUESTED` to `REJECTED`, accepts an optional `rejection_reason`, and is explicitly inert: no stock movement, no ledger entry, and the dealer's `outstanding_balance_cents` unchanged. Receiving moves it from `APPROVED` to `RECEIVED`, raises the part's `quarantine_units` by `qty_returned`, and appends one ledger entry with `entry_type` `RETURN_RECEIPT`, a positive `delta_units` equal to `qty_returned` and a `source_ref_type` of `RETURN_AUTHORIZATION`; both the part's `version` and the return's `version` advance. Any of these attempted from the wrong return state is refused with `ERR_RETURN_STATE_INVALID`.

Inspection is the fork, and the caller states which branch by supplying a `disposition`. The two branches diverge in three separate respects — stock, ledger and money — and each must be implemented as specified.

On the **`RESTOCK`** branch the return's `disposition` is set to `RESTOCK` and its `status` becomes `CREDITED`. The part's `quarantine_units` falls by `qty_returned` and its `on_hand_units` rises by the same amount; because the combined on-hand-plus-quarantine total is unchanged by that move, **no ledger entry is appended at all**. The dealer is made whole: `credit_posted_cents` is set to `final_credit_cents`, the dealer's `outstanding_balance_cents` is reduced by `final_credit_cents`, the dealer's `lifetime_restocking_fee_cents` rises by `restocking_fee_cents`, the dealer's `lifetime_rebate_cents` rises by `loyalty_rebate_cents`, and the dealer's `credit_hold` is recomputed. The part's `available_units` and `replenishment_status` are then recomputed and the part's `version` advances. This branch additionally requires the part not to be `OBSOLETE`; restocking into an obsolete part is refused with `ERR_PART_LIFECYCLE_INVALID`.

On the **`SCRAP`** branch the return's `disposition` is set to `SCRAP` and its `status` becomes `SCRAPPED`. The part's `quarantine_units` falls by `qty_returned` and its `on_hand_units` is **not** increased; because the combined total has genuinely fallen, one ledger entry **is** appended, with `entry_type` `SCRAP`, a negative `delta_units` equal to `qty_returned`, and a `source_ref_type` of `RETURN_AUTHORIZATION`. Money is conditional on this branch and only on this branch: when `return_reason` is `DEFECTIVE` the dealer is still made whole exactly as on the restock branch — `credit_posted_cents` is set to `final_credit_cents` and `outstanding_balance_cents`, `lifetime_restocking_fee_cents`, `lifetime_rebate_cents` and `credit_hold` are all updated identically — whereas for `WRONG_PART`, `UNUSED_SURPLUS` and `CORE_RETURN` the scrap is at the dealer's expense: `credit_posted_cents` stays 0 and not one dealer field changes. The part's `version` advances on either outcome.

One invariant is worth stating as an acceptance property. For a consume followed by a full-quantity restock return of the same line, the dealer's `outstanding_balance_cents`, less its `lifetime_restocking_fee_cents`, plus its `lifetime_rebate_cents`, returns to exactly the value it held before the consume. Money is conserved across that pair.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; every other successful operation — reads, state transitions, amendments and computed reads — returns HTTP 200. Successful responses carry the created or updated resource in `data` as described in section 2.2. This table is intentionally minimal: request payloads, response payloads and side effects are specified in the narrative of section 3 and must be reconstructed from there.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/_clock/set_current_utc` | Test-driving endpoint | `PlatformAdmin` |
| POST | `/aftermarket/parts` | Register a spare part in the aftermarket catalogue | `AftermarketPlanner` |
| GET | `/aftermarket/parts/{id}` | Read one part with its live stock, criticality and catalogue-price fields | `AftermarketPlanner`, `InventoryController`, `PricingAnalyst`, `DealerUser`, `PlatformAdmin` |
| GET | `/aftermarket/parts` | List parts; superseded_by_part_id filters to the predecessors of one successor part (self-referential reverse lookup) | `AftermarketPlanner`, `InventoryController`, `PricingAnalyst`, `DealerUser`, `PlatformAdmin` |
| PATCH | `/aftermarket/parts/{id}` | Amend the mutable master data of a part | `AftermarketPlanner` |
| POST | `/aftermarket/parts/{id}/classify` | Run calculations.part_criticality_and_stocking_policy against the part's CURRENT 12-month forecast | `AftermarketPlanner` |
| POST | `/aftermarket/parts/{id}/phase-out` | Move a part ACTIVE -> PHASE_OUT, opening the obsolescence workflow | `AftermarketPlanner` |
| POST | `/aftermarket/parts/{id}/reinstate` | Revert a part PHASE_OUT -> ACTIVE when no campaign has been submitted | `AftermarketPlanner` |
| POST | `/aftermarket/parts/{id}/supersede` | Point a part at its successor and retire it | `AftermarketPlanner` |
| POST | `/aftermarket/parts/{id}/obsolete` | Move a part LTB_CLOSED -> OBSOLETE once the last-time buy is fully allocated | `AftermarketPlanner` |
| GET | `/aftermarket/parts/{id}/ledger-entries` | Append-only stock ledger for one part, oldest first by occurred_at then created_at | `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| POST | `/aftermarket/equipment-models` | Register a machine model | `PlatformAdmin` |
| GET | `/aftermarket/equipment-models/{id}` | Read one machine model | `PlatformAdmin`, `AftermarketPlanner`, `InventoryController`, `DealerUser`, `PricingAnalyst` |
| POST | `/aftermarket/installed-units` | Register a machine in the installed-base registry | `PlatformAdmin` |
| GET | `/aftermarket/installed-units/{id}` | Read one installed machine | `PlatformAdmin`, `AftermarketPlanner`, `InventoryController`, `DealerUser` |
| GET | `/aftermarket/installed-units` | List installed machines filtered by model, dealer or status | `PlatformAdmin`, `AftermarketPlanner`, `InventoryController`, `DealerUser` |
| POST | `/aftermarket/installed-units/{id}/decommission` | Retire a machine from the installed base | `PlatformAdmin` |
| POST | `/aftermarket/part-applicabilities` | Declare that a part fits a build-revision range of a model | `AftermarketPlanner` |
| GET | `/aftermarket/part-applicabilities/{id}` | Read one applicability row | `AftermarketPlanner`, `InventoryController`, `DealerUser`, `PlatformAdmin` |
| GET | `/aftermarket/part-applicabilities` | List applicability rows filtered by part, model or status | `AftermarketPlanner`, `InventoryController`, `DealerUser`, `PlatformAdmin` |
| POST | `/aftermarket/part-applicabilities/{id}/withdraw` | Withdraw an applicability row so it stops gating work-order lines and stops feeding the installed-base forecast | `AftermarketPlanner` |
| POST | `/aftermarket/dealers` | Register a dealer / distributor | `PlatformAdmin` |
| GET | `/aftermarket/dealers/{id}` | Read one dealer with its live receivable and credit-hold posture | `PlatformAdmin`, `AftermarketPlanner`, `InventoryController`, `DealerUser` |
| POST | `/aftermarket/dealers/{id}/balance-adjustments` | Post a manual debit (positive) or credit (negative) to a dealer's aftermarket receivable | `PlatformAdmin` |
| POST | `/aftermarket/dealers/{id}/suspend` | Suspend a dealer, removing it from the LTB allocation candidate set | `PlatformAdmin` |
| POST | `/aftermarket/work-orders` | Open a service work order against an installed machine | `DealerUser` |
| GET | `/aftermarket/work-orders/{id}` | Read one work order | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| GET | `/aftermarket/work-orders` | List work orders filtered by installed unit, dealer or status | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| POST | `/aftermarket/work-orders/{id}/part-lines` | Add a part line to a work order | `DealerUser` |
| POST | `/aftermarket/work-orders/{id}/close` | Close a work order, making its consumed lines eligible for the forecast lookback window | `DealerUser` |
| GET | `/aftermarket/work-order-part-lines/{id}` | Read one part line with both pricing variants and the freight decision | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PricingAnalyst`, `PlatformAdmin` |
| GET | `/aftermarket/work-order-part-lines` | List part lines filtered by work order, part or status | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PricingAnalyst`, `PlatformAdmin` |
| POST | `/aftermarket/work-order-part-lines/{id}/consume` | Fit the reserved units to the machine and bill the dealer | `DealerUser` |
| POST | `/aftermarket/work-order-part-lines/{id}/cancel` | Cancel an unfitted part line and release any reservation | `DealerUser` |
| POST | `/aftermarket/parts/{id}/forecasts` | Compute a demand forecast for a part from closed service work orders and the installed base | `AftermarketPlanner` |
| GET | `/aftermarket/parts/{id}/forecasts` | List the forecasts computed for one part, newest first by computed_at then created_at | `AftermarketPlanner`, `InventoryController`, `PricingAnalyst`, `PlatformAdmin` |
| POST | `/aftermarket/last-time-buy-campaigns` | Draft a last-time-buy campaign for a phasing-out part | `AftermarketPlanner` |
| GET | `/aftermarket/last-time-buy-campaigns/{id}` | Read one campaign | `AftermarketPlanner`, `InventoryController`, `DealerUser`, `PlatformAdmin` |
| GET | `/aftermarket/last-time-buy-campaigns` | List campaigns filtered by part or status | `AftermarketPlanner`, `InventoryController`, `DealerUser`, `PlatformAdmin` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/submit` | Submit a draft campaign for approval | `AftermarketPlanner`, `InventoryController` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/approve` | Authorise the lifetime buy | `InventoryController` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/reject` | Reject a submitted campaign | `InventoryController` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/revise` | Send a rejected campaign back to DRAFT for another round | `AftermarketPlanner` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/allocate` | Run the dealer allocation waterfall over the campaign's pending requests | `InventoryController` |
| POST | `/aftermarket/last-time-buy-campaigns/{id}/close` | Close the campaign, deny any leftovers and move the part to LTB_CLOSED | `InventoryController` |
| POST | `/aftermarket/allocation-requests` | A dealer asks for a share of an approved last-time buy | `DealerUser` |
| GET | `/aftermarket/allocation-requests/{id}` | Read one allocation request | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| GET | `/aftermarket/allocation-requests` | List allocation requests filtered by campaign, dealer or status | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| POST | `/aftermarket/allocation-requests/{id}/withdraw` | Withdraw a request; a granted request returns its units to the campaign | `DealerUser`, `AftermarketPlanner` |
| POST | `/aftermarket/price-rules` | Publish the uplift and margin rule for one criticality band | `PricingAnalyst` |
| GET | `/aftermarket/price-rules` | List price rules | `PricingAnalyst`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| GET | `/aftermarket/parts/{id}/price-quote` | Computed read returning both pricing variants side by side for a hypothetical quantity | `PricingAnalyst`, `AftermarketPlanner`, `DealerUser` |
| POST | `/aftermarket/replenishment-orders` | Raise a stock or emergency-air replenishment order | `InventoryController` |
| GET | `/aftermarket/replenishment-orders/{id}` | Read one replenishment order with both of its independent status dimensions | `InventoryController`, `AftermarketPlanner`, `PlatformAdmin` |
| GET | `/aftermarket/replenishment-orders` | List replenishment orders filtered by part or by either status dimension | `InventoryController`, `AftermarketPlanner`, `PlatformAdmin` |
| POST | `/aftermarket/replenishment-orders/{id}/approve` | Approve the spend dimension of a replenishment order | `InventoryController` |
| POST | `/aftermarket/replenishment-orders/{id}/reject` | Reject the spend dimension of a replenishment order | `InventoryController` |
| POST | `/aftermarket/replenishment-orders/{id}/ship` | Move the logistics dimension to IN_TRANSIT; guarded by the approval dimension | `InventoryController` |
| POST | `/aftermarket/replenishment-orders/{id}/receive` | Book the goods in, append a RECEIPT ledger entry and run the backorder promotion sweep | `InventoryController` |
| POST | `/aftermarket/return-authorizations` | Raise an RMA against a consumed part line; the restocking fee and credit are computed at creation | `DealerUser` |
| GET | `/aftermarket/return-authorizations/{id}` | Read one RMA with its fee breakdown | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| GET | `/aftermarket/return-authorizations` | List RMAs filtered by part, dealer, source line or status | `DealerUser`, `AftermarketPlanner`, `InventoryController`, `PlatformAdmin` |
| POST | `/aftermarket/return-authorizations/{id}/approve` | Authorise the physical return | `AftermarketPlanner` |
| POST | `/aftermarket/return-authorizations/{id}/reject` | Refuse the return; nothing moves | `AftermarketPlanner` |
| POST | `/aftermarket/return-authorizations/{id}/receive` | Book the returned units into quarantine | `AftermarketPlanner` |
| POST | `/aftermarket/return-authorizations/{id}/inspect` | Fork the RMA: RESTOCK puts the units back on the shelf and credits the dealer; SCRAP writes them off and credits only DEFECTIVE returns | `AftermarketPlanner` |

## 5. Error Code Catalogue

Every error response carries the envelope described in section 2.2, with the identifier below in `error_id`. Trigger conditions are not repeated here — each is specified alongside the workflow it guards in sections 2 and 3, and the precedence between them is fixed by section 2.10.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_DEALER_SCOPE_VIOLATION` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PART_NOT_FOUND` | 404 |
| `ERR_MODEL_NOT_FOUND` | 404 |
| `ERR_INSTALLED_UNIT_NOT_FOUND` | 404 |
| `ERR_DEALER_NOT_FOUND` | 404 |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 |
| `ERR_PART_LINE_NOT_FOUND` | 404 |
| `ERR_CAMPAIGN_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_REQUEST_NOT_FOUND` | 404 |
| `ERR_REPLENISHMENT_ORDER_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_APPLICABILITY_NOT_FOUND` | 404 |
| `ERR_PRICE_RULE_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_PART_VERSION` | 412 |
| `ERR_STALE_CAMPAIGN_VERSION` | 412 |
| `ERR_PART_LIFECYCLE_INVALID` | 409 |
| `ERR_CAMPAIGN_STATE_INVALID` | 409 |
| `ERR_ALLOCATION_STATE_INVALID` | 409 |
| `ERR_LINE_STATE_INVALID` | 409 |
| `ERR_WORK_ORDER_STATE_INVALID` | 409 |
| `ERR_REPLENISHMENT_STATE_INVALID` | 409 |
| `ERR_RETURN_STATE_INVALID` | 409 |
| `ERR_PART_NOT_APPLICABLE` | 422 |
| `ERR_HAZMAT_AIR_PROHIBITED` | 422 |
| `ERR_PART_SUPERSEDED` | 422 |
| `ERR_SUPERSESSION_CYCLE` | 409 |
| `ERR_APPLICABILITY_REVISION_OVERLAP` | 409 |
| `ERR_LTB_WINDOW_OVERLAP` | 409 |
| `ERR_LTB_COOLDOWN_VIOLATION` | 409 |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 |
| `ERR_CLOCK_NOT_MONOTONIC` | 409 |
| `ERR_PART_OBSOLETE_NO_SUPPLY` | 422 |
| `ERR_RETURN_QTY_EXCEEDS_CONSUMED` | 422 |
| `ERR_ALLOCATION_EXCEEDS_REMAINING` | 409 |
| `ERR_NO_ELIGIBLE_ALLOCATION_REQUESTS` | 422 |
| `ERR_FORECAST_INPUT_EMPTY` | 422 |
| `ERR_OPEN_LINES_BLOCK_CLOSE` | 409 |
| `ERR_UPLIFT_CAP_EXCEEDED` | 422 |
| `ERR_MARGIN_FLOOR_BREACH` | 422 |
| `ERR_AIR_FREIGHT_NOT_JUSTIFIED` | 422 |
| `ERR_DEALER_CREDIT_HOLD` | 402 |

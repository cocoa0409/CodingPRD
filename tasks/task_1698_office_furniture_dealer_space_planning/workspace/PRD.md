# Office Furniture Dealer & Space Planning API — Product Requirements Document

## 1. Introduction

This document defines the product requirements for the Office Furniture Dealer & Space Planning API, a system built to operate the full commercial lifecycle of a contract furniture dealership aligned with the two major manufacturers, Steelcase and MillerKnoll. The dealer's business runs from a customer's first conversation about a floor plate all the way to post-installation deficiency resolution, manufacturer claim negotiation, and the redemption of trade-in credit against new work. Along the way the system has to price orders against tiered purchasing contracts (state, co-operative, and negotiated), honor manufacturer lead-time conventions that differ by manufacturer, schedule install crews with mandatory turnover buffers, track warehouse staging capacity day-by-day, and maintain a strictly conserved customer credit ledger that both liquidation lots and settled damage claims feed into.

The audience for this document is the engineering team implementing the API. Several design constraints deserve explicit attention up front. First, pricing is dual-anchored: a customer's order bills against a specific pricing contract whose version is pinned at order submit, and that pin is re-validated when the manufacturer acknowledges the order — any intervening contract amendment forces a deliberate revise. Second, concurrency-sensitive writes (contract amendment, lot appraisal) use optimistic concurrency control so that a client acting on a stale view of a record cannot silently fork successors or overwrite fresher valuations. Third, segregation of duties is a first-class rule: the person who drafts a contract cannot activate it, and the person who appraises a used-furniture lot cannot issue its credit. Finally, time in this system is driven by a logical clock, not the wall clock, so that contract expiration and appraisal validity windows can be exercised deterministically.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. A request missing either header, or carrying an empty value for either, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). Beyond header presence, every endpoint carries an authorized role list, and a caller whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).

The system recognizes eleven roles, spelled exactly as follows: `DealerAdmin`, `AccountExecutive`, `ContractsOfficer`, `Designer`, `ClientApprover`, `ProjectManager`, `WarehouseLead`, `ClaimsCoordinator`, `ManufacturerRep`, `LiquidationAppraiser`, and `FinanceManager`. A `DealerAdmin` owns the dealership tenant itself, the product catalog, install crews, and the logical clock. An `AccountExecutive` is the seller-side account owner and drives customers, draft pricing contracts, project orders, order lines, asset tags, and liquidation offers. A `ContractsOfficer` activates, terminates, and amends pricing contracts but, by segregation of duties, may never activate a contract they personally created. A `Designer` authors space plans and typicals; a `ClientApprover` is the customer-side approver who signs off on submitted plans. A `ProjectManager` schedules and drives install events, staging reservations, and the punch-item workflow, and closes completed orders. A `WarehouseLead` receives units into staging and releases them to site. A `ClaimsCoordinator` verifies punch items and runs the manufacturer-claim negotiation from the dealer's desk; a `ManufacturerRep` is the external manufacturer-side counterpart who acknowledges orders and answers claims. A `LiquidationAppraiser` appraises used-furniture lots but, again by segregation of duties, may never issue credit on a lot they appraised; issuance belongs to the `FinanceManager`, who also redeems lots and applies credit to orders.

Every one of these eleven roles is **opaque**: `X-User-ID` is an operator identifier not tied to any persisted entity, and the server does not compare it against any resource's `id` field for ownership checks. The server does, however, record it in specific places where the business process requires attribution: the `created_by_user_id` and `activated_by_user_id` fields on a `PricingContract`, and the `appraised_by_user_id` and `issued_by_user_id` fields on a `LiquidationLot`. Those recorded values are what the segregation-of-duties checks compare against the incoming `X-User-ID`.

All list and single-resource read endpoints (`GET`) are readable by every one of the eleven roles; authorization restricts only writes.

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

List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, has a minimum of 1, and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. Unless otherwise specified, all list endpoints return resources sorted by `created_at` ascending.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every top-level resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- `updated_at` (string): an ISO 8601 UTC timestamp recording the most recent mutation of the resource.
- `version` (integer): a system-managed integer that increments by exactly one on every mutation of the resource, including mutations driven by cascades that originate on another entity (for example, a punch-item verification that flips a series' `quality_hold` increments that series' `version`). This field anchors optimistic concurrency control and version-pinning.

All sixteen entities in this system — Dealership, Customer, PricingContract, SpacePlan, Typical, ProductSeries, ProjectOrder, OrderLine, Crew, InstallEvent, StagingReservation, PunchItem, ManufacturerClaim, AssetTag, and LiquidationLot — carry this common set. Derived-field recomputation (for example, an order's `grand_total_cents` or a customer's `liquidation_credit_balance_cents`) is a mutation on the owning resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.5. Monetary Precision and Rounding

All monetary values in the system are integer cents. Every calculation that produces a monetary value rounds to zero decimal places using the "round half up" method, unless a specific rule states otherwise. Two rounding disciplines are pinned and must not be reordered. First, per-unit rounding precedes extension: the net unit price of an order line is rounded half-up to whole cents *before* it is multiplied by quantity, so `line_total_cents` is the rounded `unit_net_price_cents` times `quantity`. The alternative order — extending a fractional amount across quantity and rounding the line total — is explicitly rejected, because the two orders differ by cents whenever the per-unit product is fractional. Second, event-level labor is rounded once per install event at completion; project-level labor totals are sums of per-event rounded costs, never a re-rounding of the aggregate. Where a rule calls for a floor instead of a round — the credit-cap computation — the prose says so explicitly.

### 2.6. Optimistic Concurrency Control

Two write operations in the system are guarded by mandatory optimistic concurrency control, and no other endpoints accept a version field.

The first guards contract amendment. A request to create an amendment (a successor draft contract) against an existing `PricingContract` must carry `expected_contract_version` equal to the contract's current `version`. If another writer has advanced the contract's `version` since the client last read it, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), because amending legitimately supersedes the contract's terms and a client acting on a stale view would otherwise fork two divergent successors.

The second guards lot appraisal. A request to record (or re-record) an appraisal against a `LiquidationLot` must carry `expected_lot_version` equal to the lot's current `version`. If the lot's `version` has advanced since the client last observed it, the appraisal is rejected with `ERR_STALE_VERSION` (HTTP 412), because a new appraisal legitimately supersedes the previous one and a client pricing off a stale appraisal would silently overwrite fresher valuation data.

Distinct from OCC, the order workflow uses **version pinning**: an order captures `pinned_contract_version` and `pinned_plan_version` at submit time, and manufacturer acknowledgment re-validates those pins (see §3.4). Pins are validated against the parent resources' current state; they are not client-supplied version fields.

### 2.7. The Logical Clock and Automatic Sweeps

The system does not use wall-clock time. A logical clock, readable by every role and settable only by a `DealerAdmin`, determines the "current UTC date" used by every date-sensitive rule in this document (contract effectiveness windows, appraisal validity, appraisal timestamps). Before any call to set it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to wall-clock time. Setting the clock via the admin-only test-driving capability advances it to a supplied `to_iso8601` instant and triggers two automatic sweeps: any `PricingContract` in `ACTIVE` whose `effective_to` date is earlier than the new current UTC date transitions to `EXPIRED`; and any `LiquidationLot` in `APPRAISED` whose latest `appraised_at` date is more than thirty days before the new current UTC date transitions to `EXPIRED`, reflecting the thirty-day validity of an appraisal.

### 2.8. Validation Ordering

When a request violates several rules at once, checks are evaluated in a fixed priority order so that the surfaced error is deterministic. The order, from first to last, is: (1) presence of the `X-User-ID` and `X-User-Role` headers; (2) the caller's role being listed for the endpoint; (3) existence of every path identifier and every foreign-key identifier in the body; (4) the target resource being in a state from which the requested transition exists; (5) segregation-of-duties and safety holds — within this group the sub-order is (5a) segregation of duties, (5b) series quality hold blocking new order lines, (5c) crew suspension blocking event create/confirm, (5d) a `BLOCKED` install posture blocking event start; (6) contract effectiveness, including pinned-contract-version freshness at acknowledgment; (7) referenced-object freshness and linkage — within this group the sub-order is (7a) plan approval and plan-version freshness, (7b) typical-to-plan linkage, (7c) series not discontinued, (7d) order acknowledged before staging or event creation, (7e) punch verification before manual claim creation, (7f) order-close gating on install completion and then on open punch items, (7g) punch-close gating on linked claims reaching a terminal state; (8) structural constraints — within this group the sub-order is (8a) field shape, range, and enum validity, (8b) date-range ordering, (8c) uniqueness, (8d) crew overlap including the turnover buffer, (8e) staging aggregate capacity, (8f) over-receipt, (8g) asset movability; and (9) money rules — pricing compliance, the per-order credit cap, and sufficient customer credit balance. Auth, existence, and state failures surface before any business rule; fiscal failures surface last.

### 2.9. Warehouse Capacity as a Daily Aggregate

Staging space at the dealership warehouse is a finite, per-day resource. A dealership's `staging_capacity_units` is an aggregate occupancy ceiling: on any calendar date, the sum of `units` across all reservations whose occupancy window covers that date may not exceed the ceiling. Reservations in `RESERVED` or `OCCUPIED` status count toward occupancy; `CANCELLED` and `RELEASED` reservations do not. The capacity check is described precisely in §3.6; the principle here is that a reservation is validated against every day of its window, both bounds inclusive, and equality with the ceiling is permitted.

### 2.10. The Customer Credit Ledger

Each customer carries a redeemable credit ledger, exposed as `liquidation_credit_balance_cents`, which is a conserved quantity. Credits flow into the ledger from two sources: the `final_credit_cents` of liquidation lots in `CREDIT_ISSUED` or `REDEEMED` status, and the `settled_amount_cents` of settled manufacturer claims whose requested remedy was `CREDIT` and whose punch item belongs to an order of that customer. Funds flow out through `credit_applied_cents` on that customer's non-`CANCELLED` orders, and through forfeiture of the unredeemed remainder when a lot is manually redeemed before its credit is fully consumed. The conservation property is exact: applying credit to an order and then cancelling that order restores the customer's prior balance exactly.

## 3. Business Logic & Workflows

### 3.1. Dealership Setup, Catalog, and Crews

A `DealerAdmin` begins by creating the dealership tenant root, supplying its `name`, the warehouse's `staging_capacity_units`, and the `standard_labor_rate_cents_per_hour` used as the default install labor rate. Four further defaults may be overridden at creation: `after_hours_start_minute`, the minute-of-day (on a 0-to-1439 scale) at which premium billing begins, defaulting to 1080 (that is, 18:00); `after_hours_multiplier_bp`, the after-hours labor multiplier in basis points, defaulting to 15000 (a one-and-a-half-times premium); `turnover_buffer_minutes`, the mandatory turnover buffer between two confirmed install events on the same crew, defaulting to 30; and `credit_cap_pct`, the maximum percent of an order's net-plus-install-fee that may be paid by liquidation credit, defaulting to 25.

With a dealership in place, the `DealerAdmin` registers the product catalog one `ProductSeries` at a time. Each series is identified by a `series_code` that must be unique within the dealership — a duplicate is rejected with `ERR_DUPLICATE_REFERENCE` — and is characterized by its `manufacturer` (exactly one of `STEELCASE` or `MILLERKNOLL`), its `category` (one of `SEATING`, `SYSTEMS`, `CASEGOODS`, `TABLES`, or `STORAGE`), a `base_list_price_cents` for the unoptioned unit, a `base_lead_time_days`, and an `option_catalog`. The option catalog is an array of entries, each pairing an `option_code` with a `price_uplift_pct` and an `extra_lead_days`; these entries drive both configured pricing and lead-time computation later. A series starts `ACTIVE` with `quality_hold` false. A `DealerAdmin` may discontinue a series, moving it to `DISCONTINUED`, after which any attempt to add an order line referencing it is rejected with `ERR_SERIES_DISCONTINUED`. Independently of its status, a series may be flagged with `quality_hold` by the critical-punch cascade described in §3.7; while the flag is set, new order lines referencing the series are rejected with `ERR_SERIES_ON_QUALITY_HOLD`, and a `DealerAdmin` clears the flag through the clear-quality-hold capability. The flag and the status are orthogonal — setting or clearing `quality_hold` never changes the series' status.

Install crews are likewise `DealerAdmin`-managed. A crew carries a `name` and a headcount `size`, and starts `ACTIVE`. Suspending a crew moves it to `SUSPENDED`; while suspended, any attempt to create or confirm an install event on that crew is rejected with `ERR_CREW_NOT_ACTIVE`. Re-activation returns the crew to `ACTIVE`. Crew status has no terminal state — a crew may be suspended and re-activated indefinitely.

### 3.2. Customers and Their Standing

An `AccountExecutive` onboards each customer organization under a dealership, supplying the `dealership_id`, the organization `name`, and an `external_ref` that must be unique within that dealership (a collision is rejected with `ERR_DUPLICATE_REFERENCE`). A new customer starts `ACTIVE` with a `liquidation_credit_balance_cents` of zero.

An `AccountExecutive` may place a customer on credit hold, moving it from `ACTIVE` to `CREDIT_HOLD`, and later release the hold, returning it to `ACTIVE`. A customer that is not `ACTIVE` cannot have new orders created for it nor orders submitted — both reject with `ERR_CUSTOMER_NOT_ACTIVE`. Closing a customer is permitted only when the account is fully settled: the `liquidation_credit_balance_cents` must be zero and the customer must have no project order in `DRAFT`, `SUBMITTED`, `ACKNOWLEDGED`, `DELIVERED`, or `INSTALLED` status. A close attempt that violates either condition is rejected with `ERR_CUSTOMER_NOT_SETTLED`; a successful close moves the customer to its terminal `CLOSED` state.

### 3.3. Pricing Contracts and Space Plans

An `AccountExecutive` drafts a `PricingContract` for a customer, supplying the `customer_id`, a `contract_type` of `STATE`, `COOP`, or `NEGOTIATED`, the `pricing_tiers` array, a `default_discount_pct`, and the inclusive effectiveness window `effective_from` through `effective_to` (both dates in YYYY-MM-DD form; a window whose end precedes its start is rejected with `ERR_INVALID_DATE_RANGE`). Each entry of `pricing_tiers` names a `category`, a `min_qty`, and a `discount_pct`. Optional overrides `labor_rate_cents_per_hour` and `after_hours_multiplier_bp` let the contract supersede dealership labor defaults for install billing. A draft may optionally name a `supersedes_contract_id`, identifying the predecessor contract this amendment will replace upon activation. At creation the contract is `DRAFT` and the server records the creator's `X-User-ID` as `created_by_user_id`.

Activation is performed by a `ContractsOfficer` and is a three-check gate, evaluated under the priority rules of §2.8: the activator must differ from the creator recorded in `created_by_user_id` (a match is rejected with `ERR_SOD_VIOLATION`, enforcing segregation of duties); every tier's `discount_pct` and the `default_discount_pct` must each be at most the maximum permitted discount of 55 percent (any excess is rejected with `ERR_CONTRACT_PRICING_VIOLATION`); and the effectiveness window must be internally ordered. On activation the server records `activated_by_user_id`, the contract moves from `DRAFT` to `ACTIVE`, and — when the contract names a `supersedes_contract_id` whose predecessor is currently `ACTIVE` — that predecessor automatically transitions to `SUPERSEDED`. A `ContractsOfficer` may also terminate a contract from either `DRAFT` or `ACTIVE`, moving it to the terminal `TERMINATED` state. Contracts expire automatically through the clock sweep of §2.7.

Amendment is the OCC-guarded path described in §2.6: the request carries `expected_contract_version` and may carry replacement values for `pricing_tiers`, `default_discount_pct`, `labor_rate_cents_per_hour`, `after_hours_multiplier_bp`, `effective_from`, or `effective_to`. A stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amendment increments the amended contract's `version` by one and creates a successor contract in `DRAFT` whose `supersedes_contract_id` names the amended contract and whose unspecified fields are copied from it; the amended contract itself remains `ACTIVE` until that successor activates.

In parallel with contract drafting, a `Designer` builds the customer's space plan. A plan is created with a `customer_id`, a `name`, and optionally a `supersedes_plan_id` pointing at an earlier plan this revision will replace upon approval; it starts `DRAFT` with `revision_no` set to 1. The designer populates the plan with typicals — reusable furniture layouts — each carrying the `space_plan_id` of its plan, a `code` such as WS-A that must be unique within the plan (duplicates are rejected with `ERR_DUPLICATE_REFERENCE`), a `quantity` of at least 1, and a `target_budget_cents_per_instance`. Each typical's `extended_budget_cents` is computed as its `quantity` multiplied by its `target_budget_cents_per_instance`, and the plan's `budget_cents` is the sum of those extended budgets across all its typicals. Typicals may be added while the plan is `DRAFT` or `IN_REVISION`, and an existing typical's `quantity` or `target_budget_cents_per_instance` may be edited in those same states; every such edit recomputes the plan's `budget_cents` and increments the plan's `version`.

Submitting a plan (from either `DRAFT` or `IN_REVISION`) requires that at least one typical exist for the plan — otherwise the submit is rejected with `ERR_INVALID_STATE` — and moves the plan to `SUBMITTED`. Approval belongs to the `ClientApprover`: approving a `SUBMITTED` plan moves it to `APPROVED` and pins `approved_version` to the plan's current `version`, which becomes the version-pinning anchor for later order submit and acknowledgment. If the approved plan names a `supersedes_plan_id` whose predecessor is currently `APPROVED`, the predecessor automatically transitions to `SUPERSEDED`. A `Designer` may send an `APPROVED` plan back into `IN_REVISION` to start a new cycle: the `revision_no` increments by one, `approved_version` is cleared to null, and typicals become editable again. The plan then cycles back through submit and approval.

### 3.4. Ordering Against a Contract and an Approved Plan

An `AccountExecutive` creates a `ProjectOrder` by naming the `customer_id`, the `contract_id` of the pricing agreement the order will bill against, and the `space_plan_id` of the approved plan the order is drawn from. Creation requires the customer to be `ACTIVE` (`ERR_CUSTOMER_NOT_ACTIVE` otherwise) and produces an order in `DRAFT` whose `install_posture` starts at `NOT_SCHEDULED`. Lines are then added to the draft order one at a time, each naming its `order_id`, the `series_id` of a catalog series, a `quantity` of at least 1, and a `selected_options` array of option codes drawn from that series' option catalog; an option code that does not appear in the catalog is rejected with `ERR_INVALID_REQUEST`. A line may optionally name a `typical_id` identifying the plan typical it fulfills. Line creation enforces the safety and linkage gates in priority order: a series under quality hold is rejected with `ERR_SERIES_ON_QUALITY_HOLD`, a discontinued series with `ERR_SERIES_DISCONTINUED`, and a `typical_id` that does not belong to the order's space plan with `ERR_TYPICAL_PLAN_MISMATCH`.

Each line's configured list price, `unit_list_price_cents`, is the series' `base_list_price_cents` scaled by one plus the sum of the `price_uplift_pct` values of the selected options divided by one hundred, rounded half-up to whole cents. The contract-discounted `unit_net_price_cents` is then determined by tier resolution: among the contract's `pricing_tiers` entries whose `category` equals the series' category, the applicable tier is the one with the largest `min_qty` that is less than or equal to the line's `quantity` (the comparison is inclusive, so a `min_qty` equal to the quantity qualifies); that tier's `discount_pct` applies. When no tier in the line's category has a `min_qty` at or below the quantity, the contract's `default_discount_pct` applies instead. The net unit price is the list unit price multiplied by one hundred minus the applicable discount percent, divided by one hundred, rounded half-up to whole cents — and this per-unit rounding happens before the line total is extended, per the pinned rounding order of §2.5. The `line_total_cents` is then the rounded `unit_net_price_cents` multiplied by `quantity`. A new line starts `OPEN` and the order's totals are recomputed on each line addition.

Submitting the order runs the full validation gauntlet of §2.8 in order. At least one line must be `OPEN` (else `ERR_INVALID_STATE`); the customer must be `ACTIVE`; the contract must be `ACTIVE` with the current UTC date inside its inclusive effectiveness window, else `ERR_CONTRACT_NOT_EFFECTIVE`; the plan must be `APPROVED` with its `approved_version` equal to its current `version` — a plan that is not approved yields `ERR_PLAN_NOT_APPROVED`, while a stale approval anchor (for example because the plan was revised after approval, or superseded) yields `ERR_PLAN_SUPERSEDED`; every line's `typical_id`, when set, must belong to the order's plan; and pricing compliance is re-checked line by line, with any resolved discount above the 55-percent maximum rejected as `ERR_CONTRACT_PRICING_VIOLATION`. On a successful submit the order captures `pinned_contract_version` from the contract's current `version` and `pinned_plan_version` from the plan's `approved_version`; all line pricing is recomputed; provisional lead times are computed per line; order totals are recomputed per the rollup below; each `OPEN` line transitions to `PLACED`; and the order moves from `DRAFT` to `SUBMITTED`.

Provisional lead times follow a manufacturer-dependent rule at submit, and each line's resulting `provisional_lead_time_days` is recorded on the line. For a `STEELCASE` series, the `provisional_lead_time_days` is the series' `base_lead_time_days` plus the sum of the `extra_lead_days` of the selected options. For a `MILLERKNOLL` series, it is the base plus the maximum of the selected options' `extra_lead_days`, defaulting to zero when no options are selected. The `provisional_promise_date` is the submit date plus the `provisional_lead_time_days` counted in calendar days.

The order total rollup runs at submit and re-runs whenever line composition or applied credit changes — that is, on line cancel, on credit application, and on replacement-line creation. The evaluation order is pinned. First, `total_list_cents` is the sum of each non-`CANCELLED` line's `unit_list_price_cents` times its `quantity`. Second, per-line nets are computed as above. Third, `total_net_cents` sums the `line_total_cents` of non-`CANCELLED` lines. Fourth, the install fee band is chosen from `total_list_cents`: when the list total reaches or exceeds fifty thousand dollars (5,000,000 cents) the fee percentage is 8; otherwise it is 12. Fifth, `install_fee_cents` is the fee percentage applied to `total_net_cents`, rounded half-up to whole cents. Sixth, the credit cap is computed as the floor of the sum of `total_net_cents` and `install_fee_cents` multiplied by the dealership's `credit_cap_pct` and divided by one hundred. Seventh, `grand_total_cents` is `total_net_cents` plus `install_fee_cents` minus `credit_applied_cents`. Replacement lines — those with `is_replacement` true — are warranty-priced: their `unit_list_price_cents`, `unit_net_price_cents`, and `line_total_cents` are all zero, so they contribute nothing to any of the sums.

Should the `AccountExecutive` need to rework a submitted order, revising it returns the order from `SUBMITTED` to `DRAFT`: both pinned versions are cleared and every `PLACED` line returns to `OPEN`, allowing lines to be added, edited by cancellation, or reconfigured before a fresh submit. An individual line may be cancelled outright only while its parent order is `DRAFT`; cancelling it moves the line to `CANCELLED` and recomputes the order totals excluding that line.

Manufacturer acknowledgment is performed by a `ManufacturerRep` and re-validates both pins before confirming anything: the `pinned_contract_version` must equal the contract's current `version` and the contract must still be `ACTIVE`, else `ERR_CONTRACT_NOT_EFFECTIVE`; and the `pinned_plan_version` must equal the plan's `approved_version` with the plan still `APPROVED`, else `ERR_PLAN_SUPERSEDED`. On acknowledgment each `PLACED` line transitions to `ACKNOWLEDGED`, and its `confirmed_lead_time_days` is set to the same day-count as the provisional computation — base plus the manufacturer-mode option days — but the `confirmed_promise_date` re-anchors to the acknowledgment date and advances in business days: only Monday through Friday count, the count starts the day after the acknowledgment date, and holidays are not modeled. Identical configuration data therefore yields a different promise date in the confirmed variant than in the provisional variant. The order's `promised_date` is then recomputed as the latest `confirmed_promise_date` across non-`CANCELLED` lines, falling back to the latest `provisional_promise_date` when no confirmed dates exist, and is null when the order has no lines. The order moves from `SUBMITTED` to `ACKNOWLEDGED`.

### 3.5. Warehouse Receipt and Staging

Once an order is acknowledged, a `ProjectManager` may reserve staging space for individual order lines. Each reservation names its `order_line_id`, a `units` count of at least 1, and an inclusive occupancy window from `start_date` through `end_date`; a window whose end precedes its start is rejected with `ERR_INVALID_DATE_RANGE`. Reservation creation requires the referenced line to be `ACKNOWLEDGED` — with one exception: replacement lines (those with `is_replacement` true) may be staged while still `OPEN`. A reservation against a line in any other state is rejected with `ERR_ORDER_NOT_ACKNOWLEDGED`. The capacity rule of §2.9 is then enforced per day: for every calendar date in the requested window, both bounds inclusive, the server sums `units` across all of the dealership's `RESERVED` and `OCCUPIED` reservations whose own windows cover that date, adds the new reservation's `units`, and rejects the reservation with `ERR_CAPACITY_EXCEEDED` if the result would exceed the dealership's `staging_capacity_units` on any day. A result exactly equal to the ceiling is allowed. A successful reservation starts `RESERVED`.

Receiving units is a `WarehouseLead` action on a `RESERVED` reservation. The receive request carries the `received_units` being physically accepted and a `condition`. The receive is rejected with `ERR_OVER_RECEIPT` when the input `received_units` is less than 1, or when the reservation's already-received units plus the new receipt would exceed the reservation's `units`, or when it would exceed the line's remaining unreceived quantity — that is, the line's `quantity` minus its `received_units`. On a successful receive the reservation transitions to `OCCUPIED`, its `received_units` increases by the received amount, and the line's `received_units` is recomputed as the sum across the line's non-`CANCELLED` reservations. When the receipt's `condition` is `DAMAGED`, the system automatically opens a `PunchItem` attributed to the line's order and line, with `source` set to `WAREHOUSE`, `severity` `STANDARD`, and status `OPEN`. When a line's `received_units` reaches its `quantity`, the line transitions to `RECEIVED` — for an `ACKNOWLEDGED` line this is the normal receipt path, while for an `OPEN` replacement line the same bubble-up applies automatically. When every non-`CANCELLED` line of an acknowledged order has reached `RECEIVED`, the order itself transitions from `ACKNOWLEDGED` to `DELIVERED` without any explicit request.

A `WarehouseLead` releases an `OCCUPIED` reservation, moving it to `RELEASED` and freeing its units from staging occupancy. A `ProjectManager` may cancel a reservation that is still `RESERVED`, moving it to `CANCELLED` and likewise freeing occupancy; the same cancellation cascades automatically to `RESERVED` reservations when the parent order is cancelled from `ACKNOWLEDGED`.

### 3.6. Installation Scheduling and Execution

A `ProjectManager` schedules field work by creating install events against an acknowledged order. Each event names its `order_id` and `crew_id`, a `kind` of either `NEW_INSTALL` or `RECONFIGURATION`, a single-day `scheduled_date` in YYYY-MM-DD form, and a half-open time window from `start_minute` (0–1439) to `end_minute` (1–1440) — the window's end must be strictly greater than its start, else `ERR_INVALID_DATE_RANGE`. Optional `labor_hours_estimated` records the estimate, and for reconfiguration events an optional `asset_moves` array lists entries pairing an `asset_tag_id` with a `to_location`. Event creation requires the order to be `ACKNOWLEDGED` or `DELIVERED`, else `ERR_ORDER_NOT_ACKNOWLEDGED`; requires the crew to be `ACTIVE`, else `ERR_CREW_NOT_ACTIVE`; and enforces the crew's calendar exclusivity: the new event's window, widened on each side by the dealership's `turnover_buffer_minutes`, must not collide with any `CONFIRMED` or `IN_PROGRESS` event of the same crew on the same date, else `ERR_CREW_OVERLAP`. The `after_hours` flag is computed at creation: it is true when any billed minute of the window falls at or after the pricing `after_hours_start_minute`. A new event starts `TENTATIVE`, and the order's `install_posture` is recomputed.

Confirming a `TENTATIVE` event re-runs the same gates — crew `ACTIVE` and the overlap check including the turnover buffer against the crew's `CONFIRMED` and `IN_PROGRESS` events on that date — and moves the event to `CONFIRMED`. An event may be returned from `CONFIRMED` to `TENTATIVE` either explicitly by a `ProjectManager` or automatically by the promise-date cascade described in §3.7. Starting a `CONFIRMED` event moves it to `IN_PROGRESS`, but only when the order's `install_posture` is not `BLOCKED`; a start attempted against a blocked order is rejected with `ERR_ORDER_BLOCKED`. Any of these mutations, as well as cancellation of a `TENTATIVE` or `CONFIRMED` event, recomputes the order's `install_posture`.

Completing an `IN_PROGRESS` event requires the `labor_hours_actual` to be recorded and moves the event to `COMPLETED`. At completion the event's `labor_cost_cents` is computed once, per the pinned rule of §2.5: the hourly rate is the order's contract `labor_rate_cents_per_hour` when set, else the dealership's `standard_labor_rate_cents_per_hour`; the after-hours multiplier is the contract's `after_hours_multiplier_bp` when set, else the dealership's `after_hours_multiplier_bp`. The window's total minutes are the `end_minute` minus the `start_minute`; the premium minutes are the count of minutes within the half-open window that fall at or after the applicable `after_hours_start_minute` — equivalently, the greater of zero and the `end_minute` minus the later of the `start_minute` and the after-hours start minute; and the standard minutes are the total minus the premium. The labor cost is then the standard minutes times the rate, plus the premium minutes times the rate times the multiplier in basis points divided by ten thousand, the whole divided by sixty, rounded half-up to whole cents. For a `RECONFIGURATION` event, completion additionally applies each `asset_moves` entry by setting the referenced asset tag's `current_location` to the entry's `to_location`; an entry referencing a `DISPOSED` asset is rejected with `ERR_ASSET_NOT_MOVABLE`. Each move also drives the asset's service status: a move whose `to_location` is exactly `STORAGE` transitions an `IN_SERVICE` asset to `IN_STORAGE`, while a move to any other location transitions an `IN_STORAGE` asset back to `IN_SERVICE`. Finally, completion recomputes the order's `install_posture`, and if the posture becomes `COMPLETE` while the order is `DELIVERED`, the order automatically advances to `INSTALLED`.

The `install_posture` itself is a derived dimension of the order, recomputed on every install-event or punch-item mutation. When any punch item of the order has `severity` `CRITICAL` and is in `OPEN` or `READY_FOR_VERIFY`, the posture is `BLOCKED`. Otherwise, when the order has at least one non-`CANCELLED` install event and every such event is `COMPLETED`, the posture is `COMPLETE`. Otherwise, when any event is `IN_PROGRESS`, the posture is `IN_PROGRESS`; when any event is `CONFIRMED`, it is `SCHEDULED`; and when none of those hold, it is `NOT_SCHEDULED`. The commercial `status` lifecycle and the `install_posture` dimension evolve independently except where gated: posture blocks event start and order close, and posture completion drives the `DELIVERED`-to-`INSTALLED` advance.

Closing the order is a `ProjectManager` action available from either `DELIVERED` or `INSTALLED`, gated by two checks in order: the `install_posture` must be `COMPLETE`, else `ERR_INSTALL_NOT_COMPLETE`; and every punch item of the order must be `CLOSED`, else `ERR_ORDER_HAS_OPEN_PUNCH`. A successful close moves each `RECEIVED` line to `CLOSED` and the order to its terminal `CLOSED` state.

Cancelling the order is an `AccountExecutive` action available from `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED`. In every case the order's `credit_applied_cents` is returned to the customer's credit ledger and the order moves to `CANCELLED`. From `DRAFT` the `cancel_fee_cents` is zero. From `SUBMITTED` the fee is also zero, and each `PLACED` line transitions to `CANCELLED`. From `ACKNOWLEDGED` a restocking fee applies: the unreceived net is the sum of `line_total_cents` over lines that are `ACKNOWLEDGED` with `received_units` of zero; the `cancel_fee_cents` is the greater of a minimum fee of two hundred fifty dollars (25,000 cents) and twenty percent of that unreceived net, the latter rounded half-up to whole cents. The fee is debited from the customer's credit ledger first, and any remainder above the ledger balance stays recorded on the order as `cancel_fee_cents` due. Cancellation from `ACKNOWLEDGED` also moves each `ACKNOWLEDGED` line to `CANCELLED` and each `RESERVED` staging reservation for those lines to `CANCELLED`. Credit application and cancellation are exact inverses on the ledger, per the conservation rule of §2.10.

### 3.7. Punch Items, Manufacturer Claims, and Quality Holds

During or after installation, a `ProjectManager` may open a punch item on an order, supplying the `order_id`, a `severity` of `STANDARD` or `CRITICAL`, a `description`, and optionally the `order_line_id` the deficiency is attributed to, the `install_event_id` during which it was found, and an `affected_units` count defaulting to 1. Punch items cannot be opened on a `CANCELLED` or `CLOSED` order — the attempt is rejected with `ERR_INVALID_STATE`. A manually opened item starts `OPEN` with `source` `INSTALL`; recall from §3.5 that damaged warehouse receipts auto-create `STANDARD` items with `source` `WAREHOUSE`. Opening a `CRITICAL` item immediately recomputes the order's `install_posture`, typically driving it to `BLOCKED`.

When remediation work is done, a `ProjectManager` marks the item ready, moving it from `OPEN` to `READY_FOR_VERIFY`. Verification belongs to the `ClaimsCoordinator` and carries a `passed` flag. A failed verification returns the item to `OPEN`. A passed verification moves it to `VERIFIED` and — when the severity is `CRITICAL` and no manufacturer claim yet references the item — fires an automatic cascade: the system creates a `ManufacturerClaim` with `origin` `AUTO_CRITICAL_PUNCH`, `claim_type` `DEFECT`, `remedy_requested` `REPLACE`, a `claimed_amount_cents` equal to the order line's `unit_net_price_cents` times the punch item's `affected_units`, and status `DRAFT`; and that claim creation sets `quality_hold` true on the claim's series, bumping the series' `version` and refreshing its `updated_at`, which in turn blocks new order lines for that series with `ERR_SERIES_ON_QUALITY_HOLD` until a `DealerAdmin` clears the hold.

A verified punch item is closed by a `ProjectManager` once every manufacturer claim referencing it has reached `SETTLED`, `DENIED`, or `WITHDRAWN`; a close attempted while any linked claim is non-terminal is rejected with `ERR_CLAIM_NOT_SETTLED`. Closing moves the item to `CLOSED` and recomputes the order's `install_posture`.

Independent of the automatic cascade, a `ClaimsCoordinator` may file a manual claim against a `VERIFIED` punch item — filing against a punch item in any other state is rejected with `ERR_PUNCH_NOT_VERIFIED`. The claim names its `punch_item_id`, a `claim_type` of `DEFECT`, `FREIGHT_DAMAGE`, or `SHORTAGE`, a `remedy_requested` of `REPAIR`, `REPLACE`, or `CREDIT`, and a `claimed_amount_cents`. Its `series_id` is derived automatically from the punch item's order line, and it starts `DRAFT` with `origin` `MANUAL`.

The claim negotiation then proceeds as a cycle. The `ClaimsCoordinator` submits the claim (`DRAFT` → `SUBMITTED`); the `ManufacturerRep` acknowledges it (`SUBMITTED` → `ACKNOWLEDGED`) and then offers a settlement by supplying a `settlement_amount_cents` (`ACKNOWLEDGED` → `SETTLEMENT_OFFERED`). The `ClaimsCoordinator` may counter the offer, which clears the `settlement_amount_cents` and returns the claim to `SUBMITTED` for another round, or accept it. A claim may also be withdrawn by the `ClaimsCoordinator` from `DRAFT`, `SUBMITTED`, or `ACKNOWLEDGED`, moving it to `WITHDRAWN`; and the `ManufacturerRep` may deny an `ACKNOWLEDGED` claim outright, moving it to `DENIED`.

Accepting a settlement moves the claim to `SETTLED`, records the offered amount as `settled_amount_cents`, and then branches on the requested remedy. When the remedy is `REPLACE`, the system creates a replacement `OrderLine` on the punch item's order: it carries the same series as the deficient line, a `quantity` equal to the punch item's `affected_units`, `is_replacement` true, warranty-zero pricing on `unit_list_price_cents`, `unit_net_price_cents`, and `line_total_cents`, and starts `OPEN`; the claim's `replacement_order_line_id` records it. Replacement-line creation recomputes the order totals and the `promised_date`, and when the recomputed `promised_date` has advanced, every install event of the order that is `CONFIRMED` with a `scheduled_date` earlier than the new `promised_date` is demoted to `TENTATIVE`, requiring re-confirmation — each demotion recomputing the `install_posture`. When the remedy is `CREDIT`, the `settled_amount_cents` is added to the customer's `liquidation_credit_balance_cents`. When the remedy is `REPAIR`, no further cascade fires beyond settlement itself.

### 3.8. Credit Application to Orders

A `FinanceManager` applies customer credit to an order in `SUBMITTED` or `ACKNOWLEDGED` by supplying an `amount_cents`. Two fiscal gates guard the application, evaluated under §2.8's money-last ordering: the resulting `credit_applied_cents` must not exceed the order's credit cap — the floor of (`total_net_cents` plus `install_fee_cents`) times the dealership's `credit_cap_pct` divided by one hundred — else `ERR_CREDIT_CAP_EXCEEDED`; and the amount must not exceed the customer's available `liquidation_credit_balance_cents`, else `ERR_INSUFFICIENT_CREDIT`. A successful application increases the order's `credit_applied_cents` by the amount, recomputes the `grand_total_cents`, debits the customer's ledger, and consumes lot credit in first-in-first-out order by lot `created_at` ascending, updating each lot's `redeemed_cents` accordingly. A lot whose `redeemed_cents` reaches its `final_credit_cents` transitions automatically from `CREDIT_ISSUED` to `REDEEMED`.

### 3.9. Used-Furniture Liquidation and Trade-In Credit

An `AccountExecutive` registers a used-furniture lot offered by a customer, supplying the `customer_id`, a `description`, and an `item_count` of at least 1. The lot starts `OFFERED` and the system computes a provisional `estimated_credit_cents` that always assumes condition grade B: it is the `item_count` times the per-item catalog estimate of 75,000 cents, reduced by a twenty percent estimation haircut — that is, multiplied by eighty percent — rounded half-up to whole cents. The estimate deliberately ignores any actual appraised value; the catalog also holds per-item estimates of 120,000 cents for grade A and 30,000 cents for grade C, which the final variant uses indirectly through the refurbishment schedule below.

Appraisal belongs to the `LiquidationAppraiser` and is OCC-guarded per §2.6. The appraisal request carries the `condition_grade` (one of `A`, `B`, or `C`), the `appraised_value_cents`, and the `expected_lot_version` matching the lot's current `version`; a stale version is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful appraisal moves the lot from `OFFERED` to `APPRAISED`, records the grade and value, sets `appraised_at` to the current UTC date, records `appraised_by_user_id` from the caller's `X-User-ID`, and increments the lot's `version` by one. A lot already `APPRAISED` may be re-appraised — the transition is `APPRAISED` → `APPRAISED` — with the same OCC guard; the prior appraisal values are overwritten, `appraised_at` resets to the current UTC date, and the version increments again. Recall from §2.7 that an appraisal is valid for thirty days: the clock sweep moves an `APPRAISED` lot whose `appraised_at` is more than thirty days in the past to `EXPIRED`.

Credit issuance belongs to the `FinanceManager` and is segregation-of-duties gated: the issuer's `X-User-ID` must differ from the recorded `appraised_by_user_id`, else `ERR_SOD_VIOLATION`. Issuance computes the `final_credit_cents` by the final valuation variant: the `appraised_value_cents` is first reduced by a fifteen percent liquidation fee — multiplied by eighty-five percent and rounded half-up to whole cents — and then the per-item refurbishment deduction for the lot's actual `condition_grade` is subtracted once per item. The refurbishment deduction is 5,000 cents per item for grade A, 15,000 cents per item for grade B, and 25,000 cents per item for grade C; if the deductions would push the result below zero, the final credit floors at zero. The lot moves to `CREDIT_ISSUED`, the customer's `liquidation_credit_balance_cents` increases by the `final_credit_cents`, and the server records `issued_by_user_id`.

Redemption happens in two ways. Automatic redemption fires when the lot's `redeemed_cents` reaches its `final_credit_cents` through order credit applications, moving the lot to `REDEEMED`. A `FinanceManager` may also redeem a `CREDIT_ISSUED` lot manually, which forfeits any unredeemed remainder: the lot moves to `REDEEMED` and the forfeited remainder — the `final_credit_cents` minus the `redeemed_cents` — is debited from the customer's credit ledger. Before credit issuance, an `AccountExecutive` may decline the lot on the customer's behalf from either `OFFERED` or `APPRAISED`, moving it to the terminal `DECLINED` state.

### 3.10. Asset Inventory and Reconfiguration Service

An `AccountExecutive` registers tagged customer assets, supplying the `customer_id`, a `description`, a `condition` of `NEW`, `GOOD`, `FAIR`, or `POOR`, a free-form `current_location`, a `source` of `PURCHASED` or `TRADED_IN`, and optionally a `series_id` linking the asset to the catalog. The initial status depends on the source: a `PURCHASED` asset starts `IN_SERVICE`, while a `TRADED_IN` asset starts `IN_STORAGE`. Thereafter the asset's location and service status are driven by reconfiguration-event completion as described in §3.6 — a move to exactly `STORAGE` shelves the asset into `IN_STORAGE`, and a move to anywhere else returns it to `IN_SERVICE`. An `AccountExecutive` may dispose of an asset from either `IN_SERVICE` or `IN_STORAGE`, moving it to the terminal `DISPOSED` state; a disposed asset can no longer be referenced by a reconfiguration move, per the `ERR_ASSET_NOT_MOVABLE` guard.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource, including all state transitions, return `200 OK`. The API is mounted under `/api`. All endpoints are subject to the validation ordering of §2.8: header presence and role authorization first, then identifier existence, state validity, safety holds, temporal rules, linkage, structural constraints, and money rules last.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/dealerships` | Create a dealership (tenant root with warehouse capacity and labor pricing defaults) | DealerAdmin |
| GET | `/api/dealerships` | List dealerships | Any |
| GET | `/api/dealerships/{id}` | Get a dealership | Any |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (test-driving endpoint; triggers contract-expiry and appraisal-validity sweeps) | DealerAdmin |
| GET | `/api/_clock` | Read the logical clock | Any |
| POST | `/api/customers` | Create a customer | AccountExecutive |
| GET | `/api/customers` | List customers | Any |
| GET | `/api/customers/{id}` | Get a customer | Any |
| POST | `/api/customers/{id}/hold` | Place customer on credit hold | AccountExecutive |
| POST | `/api/customers/{id}/release_hold` | Release customer credit hold | AccountExecutive |
| POST | `/api/customers/{id}/close` | Close a fully settled customer | AccountExecutive |
| POST | `/api/pricing-contracts` | Create a pricing contract (state/co-op/negotiated) in DRAFT | AccountExecutive |
| GET | `/api/pricing-contracts` | List pricing contracts | Any |
| GET | `/api/pricing-contracts/{id}` | Get a pricing contract | Any |
| POST | `/api/pricing-contracts/{id}/activate` | Activate a DRAFT contract (activator must differ from creator) | ContractsOfficer |
| POST | `/api/pricing-contracts/{id}/terminate` | Terminate a contract | ContractsOfficer |
| POST | `/api/pricing-contracts/{id}/amend` | Create a successor DRAFT contract amending this one (OCC-guarded) | ContractsOfficer |
| POST | `/api/space-plans` | Create a space plan in DRAFT | Designer |
| GET | `/api/space-plans` | List space plans | Any |
| GET | `/api/space-plans/{id}` | Get a space plan | Any |
| POST | `/api/space-plans/{id}/submit` | Submit a plan for client approval (from DRAFT or IN_REVISION) | Designer |
| POST | `/api/space-plans/{id}/approve` | Client approves a plan; pins approved_version; supersedes predecessor | ClientApprover |
| POST | `/api/space-plans/{id}/revise` | Send an APPROVED plan back into revision | Designer |
| POST | `/api/typicals` | Add a typical to a plan (plan must be DRAFT or IN_REVISION) | Designer |
| GET | `/api/typicals` | List typicals | Any |
| GET | `/api/typicals/{id}` | Get a typical | Any |
| PATCH | `/api/typicals/{id}` | Edit a typical while its plan is DRAFT or IN_REVISION | Designer |
| POST | `/api/product-series` | Create a catalog product series | DealerAdmin |
| GET | `/api/product-series` | List product series | Any |
| GET | `/api/product-series/{id}` | Get a product series | Any |
| POST | `/api/product-series/{id}/discontinue` | Discontinue a series | DealerAdmin |
| POST | `/api/product-series/{id}/clear_quality_hold` | Clear the quality hold flag | DealerAdmin |
| POST | `/api/project-orders` | Create a project order in DRAFT | AccountExecutive |
| GET | `/api/project-orders` | List project orders | Any |
| GET | `/api/project-orders/{id}` | Get a project order | Any |
| POST | `/api/project-orders/{id}/submit` | Submit an order: validation gauntlet, version pins, line pricing | AccountExecutive |
| POST | `/api/project-orders/{id}/revise` | Return a SUBMITTED order to DRAFT for revision | AccountExecutive |
| POST | `/api/project-orders/{id}/acknowledge` | Manufacturer acknowledges the order; re-validates pins; sets confirmed lead times | ManufacturerRep |
| POST | `/api/project-orders/{id}/cancel` | Cancel an order; restocking fee applies from ACKNOWLEDGED | AccountExecutive |
| POST | `/api/project-orders/{id}/apply_credit` | Apply customer credit to a SUBMITTED or ACKNOWLEDGED order | FinanceManager |
| POST | `/api/project-orders/{id}/close` | Close an order whose installation is complete and punch items closed | ProjectManager |
| POST | `/api/order-lines` | Add a line to a DRAFT order | AccountExecutive |
| GET | `/api/order-lines` | List order lines | Any |
| GET | `/api/order-lines/{id}` | Get an order line | Any |
| POST | `/api/order-lines/{id}/cancel` | Cancel a line while its order is DRAFT | AccountExecutive |
| POST | `/api/crews` | Create an install crew | DealerAdmin |
| GET | `/api/crews` | List crews | Any |
| GET | `/api/crews/{id}` | Get a crew | Any |
| POST | `/api/crews/{id}/suspend` | Suspend a crew | DealerAdmin |
| POST | `/api/crews/{id}/activate` | Re-activate a crew | DealerAdmin |
| POST | `/api/install-events` | Schedule an install or reconfiguration event (TENTATIVE) | ProjectManager |
| GET | `/api/install-events` | List install events | Any |
| GET | `/api/install-events/{id}` | Get an install event | Any |
| POST | `/api/install-events/{id}/confirm` | Confirm a TENTATIVE event (re-checks crew overlap) | ProjectManager |
| POST | `/api/install-events/{id}/unconfirm` | Return a CONFIRMED event to TENTATIVE | ProjectManager |
| POST | `/api/install-events/{id}/start` | Start a CONFIRMED event | ProjectManager |
| POST | `/api/install-events/{id}/complete` | Complete an event; computes labor cost; applies asset moves | ProjectManager |
| POST | `/api/install-events/{id}/cancel` | Cancel a TENTATIVE or CONFIRMED event | ProjectManager |
| POST | `/api/staging-reservations` | Reserve staging space for an order line over an inclusive date range | ProjectManager |
| GET | `/api/staging-reservations` | List staging reservations | Any |
| GET | `/api/staging-reservations/{id}` | Get a staging reservation | Any |
| POST | `/api/staging-reservations/{id}/receive` | Receive units into staging; DAMAGED condition auto-creates a warehouse punch item | WarehouseLead |
| POST | `/api/staging-reservations/{id}/release` | Release staged units to the site | WarehouseLead |
| POST | `/api/staging-reservations/{id}/cancel` | Cancel a RESERVED reservation | ProjectManager |
| POST | `/api/punch-items` | Open a punch/deficiency item on an order | ProjectManager |
| GET | `/api/punch-items` | List punch items | Any |
| GET | `/api/punch-items/{id}` | Get a punch item | Any |
| POST | `/api/punch-items/{id}/ready_for_verify` | Mark remediation work ready for verification | ProjectManager |
| POST | `/api/punch-items/{id}/verify` | Verify remediation; failure reopens; CRITICAL pass auto-creates a claim and sets the series quality hold | ClaimsCoordinator |
| POST | `/api/punch-items/{id}/close` | Close a VERIFIED punch item once its claims are terminal | ProjectManager |
| POST | `/api/manufacturer-claims` | File a claim against the manufacturer for a VERIFIED punch item | ClaimsCoordinator |
| GET | `/api/manufacturer-claims` | List manufacturer claims | Any |
| GET | `/api/manufacturer-claims/{id}` | Get a manufacturer claim | Any |
| POST | `/api/manufacturer-claims/{id}/submit` | Submit a claim to the manufacturer | ClaimsCoordinator |
| POST | `/api/manufacturer-claims/{id}/acknowledge` | Manufacturer acknowledges a claim | ManufacturerRep |
| POST | `/api/manufacturer-claims/{id}/offer_settlement` | Manufacturer offers a settlement amount | ManufacturerRep |
| POST | `/api/manufacturer-claims/{id}/accept_settlement` | Accept the settlement; REPLACE spawns a replacement-line cascade; CREDIT credits the customer ledger | ClaimsCoordinator |
| POST | `/api/manufacturer-claims/{id}/counter` | Counter the offer; returns the claim to SUBMITTED | ClaimsCoordinator |
| POST | `/api/manufacturer-claims/{id}/deny` | Manufacturer denies the claim | ManufacturerRep |
| POST | `/api/manufacturer-claims/{id}/withdraw` | Withdraw a claim before settlement | ClaimsCoordinator |
| POST | `/api/asset-tags` | Register a tagged customer asset | AccountExecutive |
| GET | `/api/asset-tags` | List asset tags | Any |
| GET | `/api/asset-tags/{id}` | Get an asset tag | Any |
| POST | `/api/asset-tags/{id}/dispose` | Dispose of an asset | AccountExecutive |
| POST | `/api/liquidation-lots` | Offer a used-furniture lot; provisional credit estimate computed | AccountExecutive |
| GET | `/api/liquidation-lots` | List liquidation lots | Any |
| GET | `/api/liquidation-lots/{id}` | Get a liquidation lot | Any |
| POST | `/api/liquidation-lots/{id}/appraise` | Appraise (or re-appraise, superseding) a lot (OCC-guarded) | LiquidationAppraiser |
| POST | `/api/liquidation-lots/{id}/issue_credit` | Issue final credit for an APPRAISED lot (issuer must differ from appraiser) | FinanceManager |
| POST | `/api/liquidation-lots/{id}/redeem` | Administratively redeem a CREDIT_ISSUED lot; remainder forfeited | FinanceManager |
| POST | `/api/liquidation-lots/{id}/decline` | Customer declines the offer before credit issuance | AccountExecutive |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CUSTOMER_NOT_SETTLED` | 409 Conflict |
| `ERR_CONTRACT_NOT_EFFECTIVE` | 409 Conflict |
| `ERR_CONTRACT_PRICING_VIOLATION` | 422 Unprocessable Entity |
| `ERR_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_PLAN_SUPERSEDED` | 409 Conflict |
| `ERR_TYPICAL_PLAN_MISMATCH` | 409 Conflict |
| `ERR_SERIES_DISCONTINUED` | 409 Conflict |
| `ERR_SERIES_ON_QUALITY_HOLD` | 409 Conflict |
| `ERR_DUPLICATE_REFERENCE` | 409 Conflict |
| `ERR_ORDER_NOT_ACKNOWLEDGED` | 409 Conflict |
| `ERR_ORDER_BLOCKED` | 409 Conflict |
| `ERR_ORDER_HAS_OPEN_PUNCH` | 409 Conflict |
| `ERR_INSTALL_NOT_COMPLETE` | 409 Conflict |
| `ERR_CLAIM_NOT_SETTLED` | 409 Conflict |
| `ERR_PUNCH_NOT_VERIFIED` | 409 Conflict |
| `ERR_CREW_NOT_ACTIVE` | 409 Conflict |
| `ERR_CREW_OVERLAP` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_OVER_RECEIPT` | 409 Conflict |
| `ERR_ASSET_NOT_MOVABLE` | 409 Conflict |
| `ERR_CREDIT_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDIT` | 422 Unprocessable Entity |

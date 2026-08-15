# Rice Mill Drying Facility API — Product Requirements Document

## 1. Introduction

When harvest breaks, a Riceland-style rice mill lives or dies on two numbers: the moisture in the incoming paddy and the dry hundredweight it will settle at. Trucks queue at the scale, every load is probed for moisture, and the grower's final payment depends on laboratory grading that happens days after the scale ticket is written. Between those two moments the facility must dry the paddy, segregate it by variety in storage bins, mill it into head rice and byproducts, sell the bran and hull, and account for every hundredweight in between. This document specifies the API that runs that operation end to end.

The system covers the full chain of custody: paddy intake with provisional moisture readings, official grading that supersedes the scale-house numbers, drying-run planning against reserved bin capacity, milling with standard-yield estimates later reconciled to measured outputs, packaging and private-label runs, byproduct sale orders, fumigation and food-safety holds, and the grower settlement cycle that converts dry weight and grade into a check. Money moves twice — a provisional statement at draft time and a final, aggregate-rounded computation at approval — and the two are deliberately allowed to differ by cents. An input-financing advance issued to the grower at onboarding is repaid out of settlement proceeds.

Every resource in the API is scoped to a single harvest season, and the API is mounted under the `/mill` prefix. Time inside a season is governed by a logical clock rather than the wall clock, so that grading dates, fumigation clearances, and settlement periods are deterministic. Ten distinct operator roles share the floor, from the scale house to the settlement office, with segregation of duties enforced where money is approved.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes ten roles, spelled exactly as follows: `MillAdmin` (facility administrator: seasons, bins, the logical clock, and season lifecycle), `Merchandiser` (grain merchandiser: grower onboarding, delivery contracts, byproduct sales), `ScaleOperator` (weighmaster: scale-ticket intake and direct bin storage), `QualityLabTech` (grading laboratory: official grading, regrade, and quality rejection), `DryerOperator` (drying plant operator), `MillSupervisor` (mill and packaging floor supervisor), `SettlementClerk` (grower accounting and the settlement lifecycle), `GrowerRep` (an external grower representative who reads and disputes only their own records), `SafetyOfficer` (food-safety compliance: holds on bins and lots), and `FumigationTech` (licensed fumigation applicator). A request with a missing header or an unrecognized role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Role identity semantics differ by role. When `X-User-Role` is `GrowerRep`, `X-User-ID` is the `id` of the acting `Grower`; ownership checks on any resource that references a `Grower` compare the resource's `grower_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_IDENTITY_SCOPE_VIOLATION` (HTTP 403). For the other nine roles — `MillAdmin`, `Merchandiser`, `ScaleOperator`, `QualityLabTech`, `DryerOperator`, `MillSupervisor`, `SettlementClerk`, `SafetyOfficer`, and `FumigationTech` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `created_by_user_id` on a `Settlement`) but does not compare it to any entity's `id`. One further identity rule applies to settlement approval: the approving operator's `X-User-ID` must differ from the settlement's `created_by_user_id`, enforcing segregation of duties; a self-approval attempt is rejected with `ERR_SOD_APPROVER_IS_CREATOR` (HTTP 403).

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. List endpoints additionally accept resource-scoped filter parameters (for example `season_id`, `status`, or `grower_id`); the filters supported by each collection are named in the workflow narratives of §3.

### 2.4. Seasons, Tenancy, and the Logical Clock

A **HarvestSeason** is the tenancy boundary for the whole facility. Every grower account, contract, bin, lot, run, order, hold, and settlement carries a `season_id` tying it to exactly one season, and a reference that crosses seasons is treated as though the target does not exist (see §2.7). A season is created with a `name`, an `intake_start_date`, and an `intake_end_date` — the inclusive window of calendar dates on which lots may be scheduled — plus a `spot_daily_cap`, the maximum number of non-rejected spot lots admitted per calendar date.

Each season runs on its own logical clock, exposed as `current_clock_iso`. The clock starts at exactly `2026-08-01T00:00:00Z` when the season is created, advances only when a `MillAdmin` sets it to a supplied `to_iso8601` instant, and never falls back to wall-clock time. The clock stamps each lot's grading date and gates fumigation exposure and aeration milestones; nowhere does the server consult real time.

A season's `status` walks the path `SETUP` → `INTAKE_OPEN` → `INTAKE_CLOSED` → `SETTLEMENT_REVIEW` → `SETTLED`, with one deliberate loop: a disputed settlement drops the season from `SETTLEMENT_REVIEW` back to `INTAKE_CLOSED`, and intake may be reopened from `INTAKE_CLOSED` under the conditions described in §3.1. `SETTLED` is terminal.

### 2.5. Common Resource Properties

Every resource in the system — seasons, growers, contracts, bins, lots, drying runs, mill runs, packaging runs, byproduct orders, fumigation events, holds, and settlements — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp refreshed on every modification of the resource.
- **`version` (integer):** starts at 1 when the resource is created and increments by one on every mutation, including mutations caused by cascading side effects (for example, a bin whose stock changes because a lot was stored, or a contract whose fulfillment was recomputed by a grading).

No entity in this system is exempt: all twelve resource types carry all four fields. Cascaded mutations — a bin touched by a drying run, a grower touched by a settlement payment, a contract touched by a lot grading — each independently refresh `updated_at` and increment `version` on the affected resource, and every such cascade is visible in the same response that triggered it.

### 2.6. Units of Measure, Monetary Precision, and Rounding

Weights inside the system are expressed in hundredweight (cwt), where one hundredweight is exactly 100 pounds. Scale tickets capture `gross_weight_lbs` and `tare_weight_lbs` in whole pounds; all stored and computed cwt quantities (`net_wet_cwt`, `dry_weight_cwt`, bin stock, run inputs and outputs, order quantities) carry exactly 2 decimal places rounded half-up. Moisture and grading factor percentages (`moisture_pct_handheld`, `moisture_pct_official`, `foreign_matter_pct`, `damage_pct`, `broken_pct`) are recorded with 1 decimal place.

All monetary values are integer cents: prices are expressed as cents per cwt (`base_price_cents_per_cwt`, `spot_price_cents_per_cwt`, `price_cents_per_cwt`), charges and settlement amounts (`drying_charge_cents`, `line_value_cents`, the `provisional_*` and `final_*` families, advances) are whole cents. Where a calculation produces a fractional cent, the result is rounded half-up to the nearest whole cent. Two deliberate exceptions exist to rounding discipline: plug figures in milling yield accounting (`est_broken_cwt`, `est_hull_cwt`, and `act_loss_cwt`) are computed as exact remainders and are never independently rounded, so that outputs always conserve the input. Timestamps used in scheduling and fumigation windows are compared at minute and second precision respectively, as noted in the relevant workflows.

### 2.7. Request Validation Order

Every request is validated in a fixed order, and a request that fails several checks surfaces the error from the earliest failing category. The evaluation order is:

1. **Authentication headers.** `X-User-ID` and `X-User-Role` are present and the role is one of the ten declared roles (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400).
2. **Role authorization.** The role is permitted for the endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. **Identity scoping.** For a `GrowerRep`, the target resource's `grower_id` equals `X-User-ID` (`ERR_IDENTITY_SCOPE_VIOLATION`, 403); for settlement approval, approver differs from creator (`ERR_SOD_APPROVER_IS_CREATOR`, 403).
4. **Request shape.** Required fields are present, types and enum values are valid, `tare_weight_lbs` is less than `gross_weight_lbs`, a packaging run's `ends_at` is later than its `starts_at`, a contract-sourced lot carries its `contract_id` and `expected_contract_version` and matches the contract's grower and variety, a spot lot carries `spot_price_cents_per_cwt`, and a fumigation record's `started_at` is not in the future relative to the season clock (`ERR_INVALID_REQUEST`, 400).
5. **Existence, left to right.** Path identifiers are resolved first, in left-to-right order, then foreign keys in the body; every referenced resource must exist and belong to the same season as the operation's target. The not-found error is specific to the resource: `ERR_SEASON_NOT_FOUND`, `ERR_GROWER_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_BIN_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_DRYING_RUN_NOT_FOUND`, `ERR_MILL_RUN_NOT_FOUND`, `ERR_PACKAGING_RUN_NOT_FOUND`, `ERR_BYPRODUCT_ORDER_NOT_FOUND`, `ERR_FUMIGATION_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, or `ERR_SETTLEMENT_NOT_FOUND` (all 404).
6. **State-machine legality.** The target resource's current state permits the requested transition; the error id varies by entity (`ERR_INVALID_SEASON_STATE`, `ERR_INVALID_LOT_STATE`, `ERR_CONTRACT_NOT_OPEN`, `ERR_DRYING_RUN_NOT_PLANNED`, `ERR_MILL_RUN_INVALID_STATE`, `ERR_PACKAGING_RUN_INVALID_STATE`, `ERR_ORDER_INVALID_STATE`, `ERR_FUMIGATION_INVALID_STATE`, `ERR_HOLD_ALREADY_RELEASED`, `ERR_SETTLEMENT_INVALID_STATE`, and their kin, 409).
7. **Optimistic concurrency.** Where an endpoint is concurrency-guarded, the supplied expected version matches the resource's current `version` (`ERR_STALE_CONTRACT_VERSION`, 412 — see §2.8).
8. **Food-safety holds.** No `ACTIVE` hold on the lot or on an involved bin blocks the operation (`ERR_ACTIVE_HOLD_BLOCKS_OPERATION`, 422).
9. **Temporal rules.** Intake-window membership, fumigation clock gates, packaging line changeover overlap, and fumigation window overlap (`ERR_OUTSIDE_INTAKE_WINDOW`, `ERR_EXPOSURE_INCOMPLETE`, `ERR_AERATION_INCOMPLETE`, `ERR_LINE_SCHEDULE_CONFLICT`, `ERR_FUMIGATION_WINDOW_CONFLICT`, 409).
10. **Referential and uniqueness constraints.** `farm_code` and `bin_code` uniqueness within a season, bin variety-lock compatibility, lot exclusivity to a single non-terminal drying run, contract over-delivery tolerance, and settlement-period eligibility (`ERR_DUPLICATE_FARM_CODE`, `ERR_DUPLICATE_BIN_CODE`, `ERR_BIN_VARIETY_MISMATCH`, `ERR_LOT_ALREADY_IN_DRYING_RUN`, `ERR_OVERDELIVERY_BEYOND_TOLERANCE`, `ERR_SETTLEMENT_PERIOD_EMPTY`).
11. **Capacity, quota, and inventory.** Bin capacity, the spot daily cap, mill input versus bin stock, byproduct and milled-rice availability, and inventory non-negativity on adjustments (`ERR_BIN_CAPACITY_EXCEEDED`, `ERR_SPOT_CAP_REACHED`, `ERR_MILL_INPUT_EXCEEDS_BIN_STOCK`, `ERR_INSUFFICIENT_BYPRODUCT_INVENTORY`, `ERR_INSUFFICIENT_MILLED_RICE`, `ERR_INVENTORY_ADJUSTMENT_NEGATIVE`).

Because the order is fixed, a mid-flight hold surfaces as `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` in preference to any later capacity or inventory failure, and an authentication failure masks everything behind it.

### 2.8. Optimistic Concurrency Control

Delivery contracts are contended resources: a merchandiser amends terms while the scale house books deliveries against the same contract, and every grading that touches a linked lot advances the contract's `version`. To prevent lost updates, exactly two write operations are concurrency-guarded, both against the contract's version:

- Creating a contract-sourced paddy lot requires the request to carry `expected_contract_version`, the contract `version` the client last observed. If the contract's version has since advanced — because another delivery was booked, another lot was graded against it, or the contract was amended — the create is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412), and the client must re-read the contract and retry.
- Amending a contract's price or volume likewise requires `expected_contract_version`. A mismatch with the contract's current `version` is rejected with `ERR_STALE_CONTRACT_VERSION` (HTTP 412); both amendments may be individually legitimate, but the second must re-read the contract first.

Endpoints not listed above do not accept a version field, and no other resource participates in optimistic concurrency control.

### 2.9. Bin Capacity Accounting and Variety Locking

Storage bins are quota-managed containers. Each bin tracks `capacity_cwt` (its maximum dry hundredweight, 2 decimal places), `stock_cwt` (dry paddy physically in the bin), and `reserved_cwt` (dry hundredweight reserved by planned drying runs). The derived `available_cwt` is always the capacity minus the stock minus the reservation, carried at 2 decimal places. Capacity checks throughout the system compare against `available_cwt` with an at-most rule: an allocation that exactly fills the bin is allowed.

A bin also carries a `variety_lock`, one of `LONG_GRAIN`, `MEDIUM_GRAIN`, or null. The lock is null on an empty bin, is set to the incoming variety the first time stock is credited, and forbids subsequent credits of the other variety. The lock returns to null only when both `stock_cwt` and `reserved_cwt` have returned to zero — that is, when the bin is truly empty of both physical grain and commitments. Every mutation of these counters increments the bin's `version` and refreshes its `updated_at`, whether the mutation originates from a direct store, a drying-run reservation, completion, or cancellation, a mill draw, or a regrade that changes a binned lot's weight.

### 2.10. Milled-Product and Byproduct Inventory Accounting

Milling converts paddy into five tracked products — `HEAD_RICE`, `BROKEN`, `BREWERS`, `BRAN`, and `HULL` — and the system maintains a computed, season-scoped inventory for each. For every product, four ledger quantities are derived from operational history: **produced** is the sum of estimated outputs from mill runs in `COMPLETED` status plus the sum of actual measured outputs from runs in `VERIFIED` status (a verified run's actuals replace its estimates, which no longer count); **consumed** applies only to `HEAD_RICE` and accumulates the head rice drawn by completed packaging runs; **reserved** accumulates the quantities of byproduct sale orders in `RESERVED` status; **shipped** accumulates the quantities of orders in `SHIPPED` status. A product's **available** quantity is produced minus consumed minus reserved minus shipped. A read-only inventory capability on the season reports all five products with these components. Inventory guards are enforced where the ledger is touched: reserving more than the available quantity is refused, and any mill-run verification or voiding whose adjustments would drive any product's available quantity below zero is refused outright.

## 3. Business Logic & Workflows

### 3.1. The Harvest Season Lifecycle

A `MillAdmin` opens the year by creating a season with its `name`, `intake_start_date`, `intake_end_date`, and `spot_daily_cap`; the season is born in `SETUP` with its logical clock at `2026-08-01T00:00:00Z`. Nothing intake-related may happen until the administrator opens intake, moving the season `SETUP` → `INTAKE_OPEN`; invoking any season lifecycle action from a state that does not offer it is rejected with `ERR_INVALID_SEASON_STATE` (HTTP 409). While `INTAKE_OPEN`, the season's lifecycle is otherwise quiet — the action is at the scale house.

When harvest winds down, the administrator closes intake (`INTAKE_OPEN` → `INTAKE_CLOSED`). Should weather or late deliveries demand it, intake can be reopened, returning the season to `INTAKE_OPEN` — but only while no settlement in the season has advanced past draft: if any settlement stands in `PROVISIONAL_ISSUED`, `APPROVED`, or `PAID`, the reopen is refused with `ERR_SEASON_REOPEN_BLOCKED`. This guarantee keeps a published settlement statement from being undermined by freshly admitted grain.

Moving from intake to money requires a clean floor. Beginning settlement review (`INTAKE_CLOSED` → `SETTLEMENT_REVIEW`) is blocked with `ERR_UNRESOLVED_INTAKE_WORK` while any lot in the season still stands in `WEIGHED` or `GRADED`, while any drying run remains `PLANNED`, or while any mill run is `IN_PROCESS`. It is likewise blocked with `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` while any food-safety hold in the season is `ACTIVE`. The review state is not a point of no return: the moment any settlement in the season enters `DISPUTED` — whether by an explicit dispute or by the regrade cascade of §3.4 — the season automatically reverts to `INTAKE_CLOSED` so the disputed statement can be revised and re-approved.

Final settlement of the season (`SETTLEMENT_REVIEW` → `SETTLED`) is permitted only when every settlement in the season stands in `PAID` — otherwise `ERR_UNPAID_SETTLEMENTS_EXIST` — and when no byproduct sale order remains `OPEN` or `RESERVED` — otherwise `ERR_OPEN_BYPRODUCT_ORDERS`. Settling the season carries a consequential cascade: every delivery contract still `OPEN` or `PARTIALLY_FULFILLED` whose fulfilled volume falls short of its contracted volume is automatically moved to `DEFAULTED`. `SETTLED` is terminal; the season's books are closed.

### 3.2. Grower Onboarding and Delivery Contracts

Before the first truck arrives, a `Merchandiser` onboards each grower into the season with a `farm_code`, a `legal_name`, and optionally an `advance_issued_cents` amount representing input financing advanced against the crop (zero if omitted). The farm code must be unique within the season; a duplicate is rejected with `ERR_DUPLICATE_FARM_CODE`. Onboarding initializes the grower's `advance_outstanding_cents` to the issued advance and `cumulative_paid_cents` to zero; both are thereafter system-maintained — the former is debited as settlements repay the advance, the latter accumulates the net amounts of the grower's paid settlements. The grower list supports filters on `season_id` and `farm_code`.

A delivery contract binds a grower to deliver a variety — `LONG_GRAIN` or `MEDIUM_GRAIN` — at a `contracted_cwt` volume (2 decimal places) and a `base_price_cents_per_cwt`. Grade economics ride along in `grade_adjustments`, a map keyed by the six grade symbols `US_NO_1`, `US_NO_2`, `US_NO_3`, `US_NO_4`, `US_NO_5`, and `SAMPLE`, whose values are per-cwt cent deltas applied to the base price. A new contract stands `OPEN` with `fulfilled_cwt` at zero, a `delivery_count` of zero bookings, and `version` at 1. Contract collections are filterable by `season_id`, `grower_id`, `variety`, and `status`.

Terms can be renegotiated only before grain moves. Amending `contracted_cwt`, `base_price_cents_per_cwt`, or `grade_adjustments` is permitted only while the contract's fulfilled volume is still zero — otherwise `ERR_CONTRACT_HAS_DELIVERIES` — and is guarded by the optimistic-concurrency rule of §2.8 via `expected_contract_version`; a successful amendment increments the contract's `version`. Cancelling a contract requires it to stand in `OPEN` or `PARTIALLY_FULFILLED` — any other status yields `ERR_CONTRACT_NOT_OPEN` — and likewise requires zero fulfilled volume, since settled grain cannot be un-delivered; a fulfilled-tainted cancel attempt meets `ERR_CONTRACT_HAS_DELIVERIES`. Cancelled contracts are terminal.

Fulfillment itself is computed, never declared. Each time a linked lot is graded, `fulfilled_cwt` is recomputed as the total dry weight of the contract's lots standing in `GRADED`, `BINNED`, or `SETTLED`, and the contract's status re-derives itself: zero fulfilled leaves the contract `OPEN`; any positive amount short of the contracted volume moves it `OPEN` → `PARTIALLY_FULFILLED`; reaching or exceeding the contracted volume — an exact one-hundred-percent fill counts as fulfilled — moves it to `FULFILLED`, from `OPEN` or `PARTIALLY_FULFILLED` alike. Every such recompute increments the contract's `version`. Rejection of a previously graded lot removes its weight from the tally and can drop the contract's status back toward `OPEN`. And as §3.1 describes, a contract that closes the season under-delivered is stamped `DEFAULTED` at season settle.

### 3.3. Receiving: Scale-Ticket Intake of Paddy Lots

Intake is the weighmaster's craft. A `ScaleOperator` creates a **PaddyLot** for one truckload, capturing the `grower_id`, the `variety`, the `source` — `CONTRACT` or `SPOT` — the scale weights `gross_weight_lbs` and `tare_weight_lbs`, the appointment `scheduled_date`, and the handheld probe reading `moisture_pct_handheld`. Intake is possible only while the season stands in `INTAKE_OPEN`; a truck arriving against a closed season is turned away with `ERR_SEASON_INTAKE_NOT_OPEN`. The appointment date must lie within the season's intake window, both bounds inclusive; a date outside it is rejected with `ERR_OUTSIDE_INTAKE_WINDOW`. The tare must be strictly less than the gross, or the ticket fails shape validation with `ERR_INVALID_REQUEST`.

From the two scale weights the system derives the net wet weight: the difference between gross and tare in pounds, divided by one hundred to express it in hundredweight, rounded half-up to 2 decimal places and stored as `net_wet_cwt`. It then computes a **provisional dry weight**, stored on `provisional_dry_weight_cwt`, using the handheld moisture reading. The drying model is the one used everywhere in the system: moisture above the 13.0 percent base loses weight. The moisture-shrink percentage is one hundred times the amount by which the moisture reading exceeds the base, divided by eighty-seven (the span from the 13.0 base to one hundred); when the reading is above base, a flat 0.5 percent handling loss is added; at or below the base both components are zero. The provisional dry weight is the net wet hundredweight reduced by the combined shrink percentage, rounded half-up to 2 decimal places. This scale-house number is a courtesy estimate only — it is superseded at grading by the laboratory-based figure and never drives money.

A contract-sourced lot additionally carries `contract_id` and the OCC token `expected_contract_version`, and its grower and variety must match the contract's own — a mismatch fails shape validation with `ERR_INVALID_REQUEST`. The named contract must stand in `OPEN` or `PARTIALLY_FULFILLED`; booking against a cancelled, fulfilled, or defaulted contract is refused with `ERR_CONTRACT_NOT_OPEN`. A successful booking increments the contract's `delivery_count` by one and advances the contract's `version` — which is exactly why the OCC check exists. A spot-sourced lot instead carries the negotiated `spot_price_cents_per_cwt` and counts against the day's intake quota: the number of non-rejected spot lots already booked for the same `scheduled_date` must be strictly below the season's `spot_daily_cap`, so the truck that brings the count to exactly the cap is admitted and the next one is rejected with `ERR_SPOT_CAP_REACHED`. Contract lots never count against the cap and are never blocked by it.

A created lot stands in `WEIGHED`. Its `bin_id`, `drying_run_id`, and `settlement_id` are all null at this point — the bin assignment arrives when the lot is stored or dried into a bin, the drying-run reference while a non-terminal run holds it, and the settlement reference once a statement snapshots it. The lot collection is filterable by `season_id`, `grower_id`, `contract_id`, `bin_id`, `drying_run_id`, `settlement_id`, `variety`, `source`, `status`, and `scheduled_date`, so the scale house can always reconstruct a day's traffic.

### 3.4. Laboratory Grading, Regrade, and Quality Rejection

Grading converts a weighed truckload into a payable quantity. A `QualityLabTech` grades a `WEIGHED` lot — any other status yields `ERR_INVALID_LOT_STATE` — by supplying the laboratory readings `moisture_pct_official`, `foreign_matter_pct`, `damage_pct`, and `broken_pct`. No `ACTIVE` hold may target the lot, or the grading is refused with `ERR_ACTIVE_HOLD_BLOCKS_OPERATION`. Grading stamps the lot's `graded_date` with the calendar date of the season's logical clock, and that date becomes the key for settlement-period eligibility in §3.8.

The official moisture replaces the handheld figure and drives the **final dry weight**, stored on `dry_weight_cwt`, through the same drying model as the provisional variant: above the 13.0 percent base, the moisture-shrink percentage is one hundred times the excess over base divided by eighty-seven, plus the flat 0.5 percent handling loss; at or below base, nothing shrinks. The lot records the components as `moisture_shrink_cwt` and `handling_loss_cwt`, each the net wet hundredweight multiplied by its percentage and rounded half-up to 2 decimal places. Identical inputs can still produce a dry weight different from the provisional figure whenever the handheld and official readings disagree — the official number alone feeds contracts and settlements.

Quality becomes money through a weighted score. The lot's `grade_score` is twice the foreign-matter percentage plus three times the damage percentage plus the broken percentage, rounded half-up to 2 decimal places, and the `grade` is assigned by inclusive thresholds: a score of at most 2.0 earns `US_NO_1`; at most 5.0, `US_NO_2`; at most 10.0, `US_NO_3`; at most 15.0, `US_NO_4`; at most 20.0, `US_NO_5`; anything above 20.0 is `SAMPLE`. Wet paddy also pays for its drying: the lot's `drying_charge_cents` is a tiered charge on the net wet hundredweight, where the moisture points are the amount by which the official moisture exceeds the 13.0 base (never below zero). The first 3.0 points are billed at 4 cents per cwt per point, the next 3.0 points at 7 cents, and any points beyond 6.0 at 12 cents — so a reading of exactly 3.0 points lies entirely in the first tier and exactly 6.0 points fills the first two tiers precisely. The summed rate is multiplied by `net_wet_cwt` and the result rounded half-up to whole cents.

Pricing follows the lot's origin. For a contract lot, `price_cents_per_cwt` is the contract's base price plus the `grade_adjustments` delta for the assigned grade; for a spot lot it is simply the agreed `spot_price_cents_per_cwt`, unchanged by grade. Either way, `line_value_cents` is the dry hundredweight multiplied by the price, rounded half-up to whole cents. Grading a contract lot fires one more guard: if the contract's fulfilled volume before this grading plus the lot's new dry weight is strictly greater than one hundred and five percent of the contracted volume — the tolerance figure itself rounded half-up to 2 decimal places — the grading is refused for the whole lot with `ERR_OVERDELIVERY_BEYOND_TOLERANCE`. A tolerated grading recomputes the contract's fulfillment and may auto-advance its status, per §3.2. The lot itself stands `GRADED`.

Laboratories re-run samples, and the API follows. Regrading is permitted while a lot stands in `GRADED` or `BINNED`, takes the same four laboratory inputs, and recomputes every grading-derived field — dry weight, shrink and handling components, score, grade, drying charge, price, and line value — with a fresh `graded_date`. When the lot is already binned and its dry weight increases, the bin must have enough `available_cwt` to absorb the increase, or the regrade is refused with `ERR_BIN_CAPACITY_EXCEEDED`; on success the bin's `stock_cwt` is adjusted by exactly the weight delta. The regrade then cascades into the money trail: if the lot's `settlement_id` names a settlement still in `DRAFT`, that settlement's provisional amounts are recomputed; if it names one in `PROVISIONAL_ISSUED`, the settlement is thrown into `DISPUTED` with `dispute_reason` automatically set to `LOT_REGRADED`, and a season standing in `SETTLEMENT_REVIEW` reverts to `INTAKE_CLOSED` as §3.1 describes.

Quality refusal is the lab's other instrument. Rejecting a lot — permitted from `WEIGHED` or `GRADED`, never later — requires a `reject_reason` and moves the lot to the terminal `REJECTED` state. A lot rejected from `WEIGHED` never touched contract fulfillment, and its contract's `delivery_count` is left unchanged; one rejected from `GRADED` has its dry weight removed from the contract's fulfilled tally, and the contract's status is re-derived from what remains, which may drop it from `FULFILLED` or `PARTIALLY_FULFILLED` back toward `OPEN`.

### 3.5. Storage and Drying Operations

A `MillAdmin` commissions storage by creating bins with a `bin_code` (unique within the season — duplicates meet `ERR_DUPLICATE_BIN_CODE`) and a `capacity_cwt`. A new bin stands `AVAILABLE` with `variety_lock` null, `stock_cwt` and `reserved_cwt` at zero, and `available_cwt` equal to its full capacity. Bin collections filter by `season_id`, `status`, and `variety_lock`.

Graded paddy reaches a bin by one of two doors. The direct door is the store action by a `ScaleOperator`, which moves a lot `GRADED` → `BINNED` into a named bin. Five guards stand at that door: the lot must be `GRADED` (`ERR_INVALID_LOT_STATE`); it must not be held by any non-terminal drying run, meaning `drying_run_id` is null (`ERR_LOT_ALREADY_IN_DRYING_RUN`); the bin must be `AVAILABLE`, since a bin in `FUMIGATING` or `AERATING` can neither receive nor release grain (`ERR_BIN_NOT_RECEIVE_READY`); no `ACTIVE` hold may sit on the lot or the target bin (`ERR_ACTIVE_HOLD_BLOCKS_OPERATION`); the bin's `variety_lock` must be null or equal to the lot's variety (`ERR_BIN_VARIETY_MISMATCH`, HTTP 422); and the bin must have room — the lot's `dry_weight_cwt` must not exceed `available_cwt`, with an exact fit allowed (`ERR_BIN_CAPACITY_EXCEEDED`). A successful store adds the dry weight to `stock_cwt`, sets the variety lock if it was null, stamps the lot's `bin_id`, and increments the bin's `version`.

The second door is the dryer. A `DryerOperator` plans a **DryingRun** by naming a `destination_bin_id` and a set of `lot_ids`, each of which must stand in `GRADED` and be unclaimed by any other non-terminal run (`ERR_LOT_ALREADY_IN_DRYING_RUN`); an informational `fuel_cost_cents` may be recorded, defaulting to zero. Planning computes `expected_output_cwt` as the sum of the referenced lots' dry weights and reserves that amount against the destination bin — the reservation must fit within `available_cwt` (`ERR_BIN_CAPACITY_EXCEEDED`) and, per the hold rules of §3.7, a bin under an `ACTIVE` hold refuses new drying plans with `ERR_ACTIVE_HOLD_BLOCKS_OPERATION`. Each referenced lot's `drying_run_id` is set, the bin's `reserved_cwt` grows by the expected output, and the run stands `PLANNED`. Drying-run collections filter by `season_id`, `destination_bin_id`, and `status`.

Completing a run is the operator's report of reality: the run must stand `PLANNED` (`ERR_DRYING_RUN_NOT_PLANNED`), the destination bin must be `AVAILABLE` (`ERR_BIN_NOT_RECEIVE_READY`) and free of active holds, and the operator supplies `actual_output_cwt`, the measured dry output at 2 decimal places. Completion releases the reservation (the bin's `reserved_cwt` falls by `expected_output_cwt`), adds the actual output to `stock_cwt`, moves every referenced lot `GRADED` → `BINNED` with `bin_id` set to the destination, and keeps each lot's `drying_run_id` in place for traceability; the bin's `version` increments. Cancelling a `PLANNED` run instead releases the reservation, clears each lot's `drying_run_id` back to null, and leaves the lots in `GRADED`. Cancellation also arrives uninvited: §3.7 describes how a fumigation treatment on the destination bin automatically cancels every `PLANNED` run targeting it, with exactly these release semantics.

### 3.6. Milling, Packaging, and Byproduct Sales

The mill floor turns stored paddy into salable streams. A `MillSupervisor` schedules a **MillRun** with an `input_bin_id` and an `input_cwt`; the run copies its `variety` from the bin's current `variety_lock` and stands `SCHEDULED`. Starting the run requires `SCHEDULED` status (`ERR_MILL_RUN_INVALID_STATE`), an `AVAILABLE` input bin free of active holds (`ERR_BIN_NOT_RECEIVE_READY`, `ERR_ACTIVE_HOLD_BLOCKS_OPERATION`), and sufficient physical stock — `input_cwt` must not exceed the bin's `stock_cwt` (`ERR_MILL_INPUT_EXCEEDS_BIN_STOCK`). The draw debits `stock_cwt` by the input amount at start, increments the bin's `version`, and if the bin thereby empties completely — stock at zero with no reservation outstanding — its `variety_lock` returns to null. Mill-run collections filter by `season_id`, `input_bin_id`, `status`, and `variety`.

Completing an `IN_PROCESS` run (again `ERR_MILL_RUN_INVALID_STATE` from any other state) applies the published milling standards for the run's variety. Total rice is the input multiplied by 0.68 for `LONG_GRAIN` or 0.72 for `MEDIUM_GRAIN`, rounded half-up to 2 decimal places. From that total, estimated head rice `est_head_cwt` is total rice multiplied by 0.60 for long grain or 0.66 for medium grain, and estimated brewers `est_brewers_cwt` is total rice multiplied by 0.05 — both rounded half-up to 2 decimals — while estimated broken `est_broken_cwt` is whatever of the total rice remains after head and brewers, an unrounded plug. Estimated bran `est_bran_cwt` is the input multiplied by 0.08 and estimated loss `est_loss_cwt` the input multiplied by 0.02, each rounded half-up to 2 decimals; estimated hull `est_hull_cwt` is the global plug — whatever of the input remains after total rice, bran, and loss. The six estimates therefore always sum exactly to the input, and completion credits each product's inventory (§2.10) with its estimated quantity.

Verification reconciles estimates to the scale. Verifying a `COMPLETED` run takes the measured `act_head_cwt`, `act_broken_cwt`, `act_brewers_cwt`, `act_bran_cwt`, and `act_hull_cwt`; the system derives `act_loss_cwt` as the input minus those five actuals, another unrounded plug. Every product's inventory is then adjusted by the signed difference between actual and estimate, and the adjustment is refused outright — `ERR_INVENTORY_ADJUSTMENT_NEGATIVE` — if it would push any product's available quantity below zero. A verified run stands `VERIFIED`, terminal. Voiding is the emergency brake on a `COMPLETED` run: it removes the run's estimated outputs from inventory under the same non-negativity guard, moves the run to `VOIDED`, and pointedly does not restore the drawn paddy to the input bin.

Packaging sells the head rice. Scheduling a **PackagingRun** names a `line_id` — `LINE_1` or `LINE_2` — a `brand_label` for the brand or private-label customer, a `package_size_kg`, a `units_planned` count, and a window from `starts_at` to `ends_at` that must end after it begins (`ERR_INVALID_REQUEST`). The line is a serialized resource with a thirty-minute changeover buffer applied at both ends: a new run conflicts with any other `SCHEDULED` run on the same line in the same season when the new start falls before the existing run's end plus thirty minutes and the existing run's start falls before the new end plus thirty minutes — so a gap of exactly thirty minutes between windows is allowed, and `COMPLETED` or `CANCELLED` runs never conflict. A conflicting schedule is rejected with `ERR_LINE_SCHEDULE_CONFLICT`. Completing a scheduled run — from any other state, `ERR_PACKAGING_RUN_INVALID_STATE` — takes the `units_produced` count and converts it to consumed head rice: packages produced multiplied by kilograms per package, converted to pounds at 2.20462262 pounds per kilogram, divided by one hundred into hundredweight, and rounded half-up to 2 decimals as `head_rice_consumed_cwt`. The head-rice inventory must hold at least that much available, or completion fails with `ERR_INSUFFICIENT_MILLED_RICE`; otherwise the amount is debited and the run stands `COMPLETED`. Cancelling discards a `SCHEDULED` run to `CANCELLED`. Packaging collections filter by `season_id`, `line_id`, and `status`.

What the mill does not pack, the merchandiser sells in bulk. A `Merchandiser` writes a **ByproductSaleOrder** for a `product` — `BRAN`, `HULL`, `BROKEN`, or `BREWERS` — with a `quantity_cwt`, a `price_cents_per_cwt`, and a `buyer_name`; the order stands `OPEN`. Reserving an `OPEN` order requires the product's available inventory to cover the quantity (`ERR_INSUFFICIENT_BYPRODUCT_INVENTORY`) and moves it to `RESERVED`, adding the quantity to the product's reserved tally. A reserved order may be released back to `OPEN`, unwinding the reservation, or shipped, moving `RESERVED` → `SHIPPED` as the quantity leaves the reserved tally and lands in the shipped tally. Cancellation is allowed from `OPEN` or `RESERVED` — any other state draws `ERR_ORDER_INVALID_STATE` — and releases whatever reservation the order still held. Remember §3.1: orders still `OPEN` or `RESERVED` block the season's final settle. Order collections filter by `season_id`, `product`, and `status`.

### 3.7. Food Safety: Fumigation Treatments and Regulatory Holds

Infestation response is a licensed, timestamped affair. A `FumigationTech` logs a **FumigationEvent** against a bin with the `fumigant_code`, the `applicator_license` number, the `started_at` instant, the sealed `exposure_hours`, and the `aeration_hours` that follow. Treatments may be back-dated — `started_at` must be at or before the season's logical clock — but a future start fails shape validation with `ERR_INVALID_REQUEST`. From these inputs the system derives `exposure_ends_at` (the start plus the exposure hours) and `clearance_at` (the exposure end plus the aeration hours), defining a half-open treatment window that begins at `started_at` and ends at, but does not include, `clearance_at`.

Two guards precede the treatment. The bin must stand `AVAILABLE` — a bin already `FUMIGATING` or `AERATING` rejects the new record with `ERR_BIN_FUMIGATION_ACTIVE`. And the window must not overlap any other fumigation event ever recorded on the same bin in the same season, history included: an overlap exists when the new start falls before the other's clearance and the other's start falls before the new clearance, which means back-to-back treatments whose start exactly equals the predecessor's clearance are allowed. An overlapping record is rejected with `ERR_FUMIGATION_WINDOW_CONFLICT`. Recording the treatment moves the bin `AVAILABLE` → `FUMIGATING` with a version increment — and, critically, automatically cancels every `PLANNED` drying run destined for that bin, releasing its reservation and clearing its lots' `drying_run_id` references exactly as a manual cancellation would. Fumigation collections filter by `season_id`, `bin_id`, and `status`.

The treatment then advances on the season clock, never on the wall clock. Beginning aeration requires the event to stand `ACTIVE` (`ERR_FUMIGATION_INVALID_STATE`) and the season clock to have reached `exposure_ends_at` — an early attempt draws `ERR_EXPOSURE_INCOMPLETE`, though a clock reading exactly at the exposure end is sufficient. The event moves `ACTIVE` → `AERATING` and the bin follows from `FUMIGATING` to `AERATING` with a version increment. Clearing the treatment requires the event in `AERATING` and the clock at or past `clearance_at` (`ERR_AERATION_INCOMPLETE` otherwise); the event moves to the terminal `CLEARED` and the bin returns to `AVAILABLE`, ready to receive grain again.

Independent of fumigation, a `SafetyOfficer` may quarantine product in place. Creating a **FoodSafetyHold** names a `target_type` — `BIN` or `LOT` — which selects what `target_id` refers to: a bin's `id` or a lot's `id`. A `reason_code` such as `AFLATOXIN_SUSPECT` or `PEST_ACTIVITY` records the cause, and the hold stands `ACTIVE`. An active hold is a hard stop across the facility, always surfacing as `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` (HTTP 422): it blocks grading, regrading, or storing a held lot; it blocks storing into, drying-plan creation against, or drying completion into a held bin; it blocks starting a mill run that would draw from a held bin; and a single active hold anywhere in the season blocks the transition into settlement review. Releasing a hold requires it to stand `ACTIVE` — a second release meets `ERR_HOLD_ALREADY_RELEASED` — and records the officer's `resolution_note` as the hold moves to `RELEASED`. Hold collections filter by `season_id`, `target_type`, `target_id`, and `status`.

### 3.8. Grower Settlement and Payment

Settlement is where dry weight becomes a check, and it is built as a two-pass ledger. A `SettlementClerk` drafts a **Settlement** for a grower by naming the `season_id`, the `grower_id`, and an inclusive period from `period_start_date` to `period_end_date`. Drafting snapshots the eligible lots: lots standing in `BINNED`, belonging to that grower and season, whose `graded_date` falls within the period (both ends inclusive), and whose `settlement_id` is still null. The snapshot is frozen into the settlement's `lot_ids` — membership never changes thereafter — and each member lot's `settlement_id` is stamped, removing it from future eligibility. A period with no eligible lots is refused with `ERR_SETTLEMENT_PERIOD_EMPTY` (HTTP 422). The draft also records `created_by_user_id` from the acting clerk's `X-User-ID`, the seed of the segregation-of-duties check at approval. Settlement collections filter by `season_id`, `grower_id`, and `status`.

The draft's provisional statement follows a pinned evaluation order — gross, then drying, then checkoff, then advance repayment, then net — and the order is never rearranged, because the fee and the advance repayment would otherwise be circular. In the provisional (per-line rounding) variant, `provisional_gross_cents` is the sum of the member lots' individually rounded `line_value_cents`; `provisional_drying_cents` is the sum of their `drying_charge_cents`; `provisional_checkoff_cents` is the sum, over each line, of that line's value multiplied by the half-of-one-percent checkoff rate (0.005) and rounded half-up to whole cents per line; `provisional_advance_repay_cents` is the lesser of the grower's `advance_outstanding_cents` at computation time and whatever positive amount remains of gross after drying and checkoff — zero when nothing positive remains; and `provisional_net_cents` is gross minus drying, minus checkoff, minus advance repayment.

Issuing the provisional statement requires the settlement in `DRAFT` (`ERR_SETTLEMENT_INVALID_STATE`) and the season in `INTAKE_CLOSED` or `SETTLEMENT_REVIEW` (`ERR_INVALID_SEASON_STATE`); issuance moves the settlement to `PROVISIONAL_ISSUED` and locks the provisional snapshot as the figure shown to the grower.

Approval is a second pair of eyes over a different arithmetic. Approving requires the settlement in `PROVISIONAL_ISSUED`, the season squarely in `SETTLEMENT_REVIEW` (`ERR_SEASON_NOT_SETTLEMENT_REVIEW`), and an approver whose `X-User-ID` differs from `created_by_user_id` (`ERR_SOD_APPROVER_IS_CREATOR`). Approval computes the final statement with the **aggregate rounding** variant: `final_gross_cents` is the sum of the member lots' exact line values — dry weight times price, unrounded — rounded half-up to whole cents exactly once at the end; `final_drying_cents` again sums the drying charges; `final_checkoff_cents` applies the 0.005 rate to the exact aggregate gross and rounds half-up a single time; `final_advance_repay_cents` is the lesser of the outstanding advance at approval time and the positive remainder after drying and checkoff; and `final_net_cents` — the amount actually paid — is the remainder after all three deductions. Because the provisional variant rounds per line and the final variant rounds once on the aggregate, the two statements for the same lots can legitimately differ by cents. Approval also moves every member lot `BINNED` → `SETTLED`.

Payment closes the loop. Paying an `APPROVED` settlement moves it to the terminal `PAID` and touches the grower's account in the same breath: `advance_outstanding_cents` falls by `final_advance_repay_cents`, `cumulative_paid_cents` grows by `final_net_cents`, and the grower's `version` increments.

Disagreement has its own lane. A settlement in `PROVISIONAL_ISSUED` or `APPROVED` may be disputed — by a `SettlementClerk`, by the `GrowerRep` whose grower the settlement pays, or automatically by the regrade cascade of §3.4 — with a `dispute_reason` required on an explicit dispute (the cascade supplies `LOT_REGRADED` itself); disputing from any other state draws `ERR_SETTLEMENT_INVALID_STATE`. Disputing an `APPROVED` settlement returns every member lot from `SETTLED` to `BINNED`, unwinding the settlement's hold on the grain, and in either case a season standing in `SETTLEMENT_REVIEW` reverts to `INTAKE_CLOSED`. Revision then moves the settlement `DISPUTED` → `DRAFT`, recomputing the provisional amounts over the same frozen `lot_ids` with the lots' current values — so a regraded lot's new price and weight flow into the next issued statement. The cycle of issue, approve or dispute, and revise repeats until the statement stands `PAID`, and only a season whose settlements are all `PAID` may settle for good.

## 4. Endpoint Definitions

Operations that create a new resource (a season, grower, contract, bin, lot, run, order, fumigation event, hold, or settlement) return `201 Created`. Operations that read, modify, or transition an existing resource return `200 OK`. The complete request and response semantics of each endpoint — inputs, derived fields, guards, and cascades — are defined by the narratives in §2 and §3; the table below is an index, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mill/seasons` | Create a harvest season; logical clock starts at 2026-08-01T00:00:00Z | MillAdmin |
| GET | `/mill/seasons` | List seasons | Any |
| GET | `/mill/seasons/{id}` | Get one season | Any |
| POST | `/mill/seasons/{id}/open-intake` | Move season SETUP → INTAKE_OPEN | MillAdmin |
| POST | `/mill/seasons/{id}/close-intake` | Move season INTAKE_OPEN → INTAKE_CLOSED | MillAdmin |
| POST | `/mill/seasons/{id}/reopen-intake` | Reopen intake; blocked while any settlement is past DRAFT | MillAdmin |
| POST | `/mill/seasons/{id}/begin-settlement-review` | Enter settlement review; requires all intake work resolved and no active holds | MillAdmin |
| POST | `/mill/seasons/{id}/settle` | Settle the season; under-delivered contracts auto-DEFAULTED | MillAdmin |
| POST | `/mill/seasons/{id}/clock/set` | Advance the season logical clock | MillAdmin |
| GET | `/mill/seasons/{id}/byproduct-inventory` | Computed per-product inventory for the season | Any |
| POST | `/mill/growers` | Onboard a grower into a season | Merchandiser |
| GET | `/mill/growers` | List growers (filterable) | Any |
| GET | `/mill/growers/{id}` | Get one grower | Any |
| POST | `/mill/contracts` | Create a delivery contract (version 1, status OPEN) | Merchandiser |
| GET | `/mill/contracts` | List contracts (filterable) | Any |
| GET | `/mill/contracts/{id}` | Get one contract | Any |
| PUT | `/mill/contracts/{id}` | Amend price/volume of an undelivered contract; OCC-guarded | Merchandiser |
| POST | `/mill/contracts/{id}/cancel` | Cancel a contract with zero fulfilled volume | Merchandiser |
| POST | `/mill/bins` | Create a storage bin | MillAdmin |
| GET | `/mill/bins` | List bins (filterable) | Any |
| GET | `/mill/bins/{id}` | Get one bin | Any |
| POST | `/mill/lots` | Scale-ticket intake of one paddy truckload | ScaleOperator |
| GET | `/mill/lots` | List lots (filterable) | Any |
| GET | `/mill/lots/{id}` | Get one lot | Any |
| POST | `/mill/lots/{id}/grade` | Official grading: lab moisture and factor inputs | QualityLabTech |
| POST | `/mill/lots/{id}/regrade` | Re-grade a GRADED or BINNED lot | QualityLabTech |
| POST | `/mill/lots/{id}/reject` | Reject a WEIGHED or GRADED lot | QualityLabTech |
| POST | `/mill/lots/{id}/store` | Direct-bin a GRADED lot | ScaleOperator |
| POST | `/mill/drying-runs` | Plan a drying run over GRADED lots; reserves bin capacity | DryerOperator |
| GET | `/mill/drying-runs` | List drying runs (filterable) | Any |
| GET | `/mill/drying-runs/{id}` | Get one drying run | Any |
| POST | `/mill/drying-runs/{id}/complete` | Complete a PLANNED run; commits actual output to bin stock | DryerOperator |
| POST | `/mill/drying-runs/{id}/cancel` | Cancel a PLANNED run; releases the reservation | DryerOperator |
| POST | `/mill/mill-runs` | Schedule a mill run drawing paddy from a bin | MillSupervisor |
| GET | `/mill/mill-runs` | List mill runs (filterable) | Any |
| GET | `/mill/mill-runs/{id}` | Get one mill run | Any |
| POST | `/mill/mill-runs/{id}/start` | Start a SCHEDULED run; debits bin stock | MillSupervisor |
| POST | `/mill/mill-runs/{id}/complete` | Complete an IN_PROCESS run; credits standard-yield estimates | MillSupervisor |
| POST | `/mill/mill-runs/{id}/verify` | Verify a COMPLETED run with measured outputs | MillSupervisor |
| POST | `/mill/mill-runs/{id}/void` | Void a COMPLETED run; removes estimated outputs | MillSupervisor |
| POST | `/mill/packaging-runs` | Schedule a packaging/private-label run on a line | MillSupervisor |
| GET | `/mill/packaging-runs` | List packaging runs (filterable) | Any |
| GET | `/mill/packaging-runs/{id}` | Get one packaging run | Any |
| POST | `/mill/packaging-runs/{id}/complete` | Complete a SCHEDULED run; consumes head-rice inventory | MillSupervisor |
| POST | `/mill/packaging-runs/{id}/cancel` | Cancel a SCHEDULED run | MillSupervisor |
| POST | `/mill/byproduct-orders` | Create a byproduct sale order | Merchandiser |
| GET | `/mill/byproduct-orders` | List byproduct orders (filterable) | Any |
| GET | `/mill/byproduct-orders/{id}` | Get one byproduct order | Any |
| POST | `/mill/byproduct-orders/{id}/reserve` | Reserve inventory for an OPEN order | Merchandiser |
| POST | `/mill/byproduct-orders/{id}/release` | Release a RESERVED order back to OPEN | Merchandiser |
| POST | `/mill/byproduct-orders/{id}/ship` | Ship a RESERVED order | Merchandiser |
| POST | `/mill/byproduct-orders/{id}/cancel` | Cancel an OPEN or RESERVED order | Merchandiser |
| POST | `/mill/fumigation-events` | Log a fumigation treatment on a bin | FumigationTech |
| GET | `/mill/fumigation-events` | List fumigation events (filterable) | Any |
| GET | `/mill/fumigation-events/{id}` | Get one fumigation event | Any |
| POST | `/mill/fumigation-events/{id}/begin-aeration` | Begin aeration once exposure has elapsed on the season clock | FumigationTech |
| POST | `/mill/fumigation-events/{id}/clear` | Clear the treatment once clearance time is reached | FumigationTech |
| POST | `/mill/holds` | Place a food-safety hold on a bin or a lot | SafetyOfficer |
| GET | `/mill/holds` | List holds (filterable) | Any |
| GET | `/mill/holds/{id}` | Get one hold | Any |
| POST | `/mill/holds/{id}/release` | Release an ACTIVE hold | SafetyOfficer |
| POST | `/mill/settlements` | Draft a settlement; snapshots eligible BINNED lots | SettlementClerk |
| GET | `/mill/settlements` | List settlements (filterable) | Any |
| GET | `/mill/settlements/{id}` | Get one settlement | Any |
| POST | `/mill/settlements/{id}/issue-provisional` | Issue the provisional statement (locks the snapshot) | SettlementClerk |
| POST | `/mill/settlements/{id}/approve` | Approve with final aggregate-rounding computation; lots → SETTLED | SettlementClerk |
| POST | `/mill/settlements/{id}/pay` | Pay an APPROVED settlement; applies advance repayment | SettlementClerk |
| POST | `/mill/settlements/{id}/dispute` | Dispute a PROVISIONAL_ISSUED or APPROVED settlement | SettlementClerk, GrowerRep |
| POST | `/mill/settlements/{id}/revise` | Revise a DISPUTED settlement back to DRAFT | SettlementClerk |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. Trigger conditions are defined where each guard lives, in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_IDENTITY_SCOPE_VIOLATION` | 403 Forbidden |
| `ERR_SOD_APPROVER_IS_CREATOR` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SEASON_NOT_FOUND` | 404 Not Found |
| `ERR_GROWER_NOT_FOUND` | 404 Not Found |
| `ERR_CONTRACT_NOT_FOUND` | 404 Not Found |
| `ERR_BIN_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_DRYING_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_MILL_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_PACKAGING_RUN_NOT_FOUND` | 404 Not Found |
| `ERR_BYPRODUCT_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_FUMIGATION_NOT_FOUND` | 404 Not Found |
| `ERR_HOLD_NOT_FOUND` | 404 Not Found |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_SEASON_STATE` | 409 Conflict |
| `ERR_SEASON_INTAKE_NOT_OPEN` | 409 Conflict |
| `ERR_SEASON_NOT_SETTLEMENT_REVIEW` | 409 Conflict |
| `ERR_SEASON_REOPEN_BLOCKED` | 409 Conflict |
| `ERR_UNRESOLVED_INTAKE_WORK` | 409 Conflict |
| `ERR_UNPAID_SETTLEMENTS_EXIST` | 409 Conflict |
| `ERR_OPEN_BYPRODUCT_ORDERS` | 409 Conflict |
| `ERR_INVALID_LOT_STATE` | 409 Conflict |
| `ERR_CONTRACT_NOT_OPEN` | 409 Conflict |
| `ERR_CONTRACT_HAS_DELIVERIES` | 409 Conflict |
| `ERR_BIN_NOT_RECEIVE_READY` | 409 Conflict |
| `ERR_BIN_FUMIGATION_ACTIVE` | 409 Conflict |
| `ERR_DRYING_RUN_NOT_PLANNED` | 409 Conflict |
| `ERR_MILL_RUN_INVALID_STATE` | 409 Conflict |
| `ERR_PACKAGING_RUN_INVALID_STATE` | 409 Conflict |
| `ERR_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_FUMIGATION_INVALID_STATE` | 409 Conflict |
| `ERR_HOLD_ALREADY_RELEASED` | 409 Conflict |
| `ERR_SETTLEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_CONTRACT_VERSION` | 412 Precondition Failed |
| `ERR_ACTIVE_HOLD_BLOCKS_OPERATION` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_INTAKE_WINDOW` | 409 Conflict |
| `ERR_EXPOSURE_INCOMPLETE` | 409 Conflict |
| `ERR_AERATION_INCOMPLETE` | 409 Conflict |
| `ERR_LINE_SCHEDULE_CONFLICT` | 409 Conflict |
| `ERR_FUMIGATION_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_DUPLICATE_FARM_CODE` | 409 Conflict |
| `ERR_DUPLICATE_BIN_CODE` | 409 Conflict |
| `ERR_BIN_VARIETY_MISMATCH` | 422 Unprocessable Entity |
| `ERR_LOT_ALREADY_IN_DRYING_RUN` | 409 Conflict |
| `ERR_OVERDELIVERY_BEYOND_TOLERANCE` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_PERIOD_EMPTY` | 422 Unprocessable Entity |
| `ERR_BIN_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_SPOT_CAP_REACHED` | 409 Conflict |
| `ERR_MILL_INPUT_EXCEEDS_BIN_STOCK` | 409 Conflict |
| `ERR_INSUFFICIENT_BYPRODUCT_INVENTORY` | 409 Conflict |
| `ERR_INSUFFICIENT_MILLED_RICE` | 409 Conflict |
| `ERR_INVENTORY_ADJUSTMENT_NEGATIVE` | 409 Conflict |

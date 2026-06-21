# Powersports Dealer & Service API — Product Requirements Document

## 1. Introduction

This document specifies the Powersports Dealer & Service platform, a back-office API that runs a motorcycle, ATV, UTV, personal-watercraft, and snowmobile dealership end to end. A single store must simultaneously hold floored inventory whose carrying cost accrues by the day, close financed retail sales that fold trade-ins and lender payoffs into a single out-the-door figure, keep a flat-rate service shop scheduled around technician availability, manage parts reservations against finite shelf stock, run seasonal storage and winterization, capture liability for test rides, and submit warranty and recall claims to the manufacturer. These activities are not independent: a delivered sale pays off a floor-plan loan, an accepted trade mints a new unit into inventory, a completed repair order consumes reserved parts, and a paid warranty claim can settle the labor invoice that produced it. The platform's purpose is to make those couplings explicit and consistent so that money, inventory, and obligations never drift apart.

The system is organized as a flat collection of peer resources. There is no nested URL ownership; every relationship between a deal, a unit, a loan, a trade, a repair order, a part, or a storage agreement is expressed by an identifier carried in a request or response body and is discoverable through filtered list queries. Because several of these resources carry money that must reconcile against one another — floor-plan principal against curtailments, deal financing against trade equity, repair-order totals against parts inventory — the platform treats correctness of those ledgers, not merely the success of any single call, as its primary obligation. Many state changes therefore cascade automatically across resources without a separate client request, and the rules that govern those cascades are described throughout Section 3.

The intended operators are five dealership roles — a sales desk, a finance desk, a service desk, a parts counter, and the dealer principal who holds override authority over the fiscal gates. The remainder of this document defines the global contract every endpoint honors (Section 2), the business workflows and their scattered rules (Section 3), the endpoint surface (Section 4), and the catalogue of error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401). When the headers are well formed but the named role is not permitted to perform the requested operation under the access matrix in Section 4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly five roles, spelled precisely as follows: `SalesManager`, `FinanceManager`, `ServiceAdvisor`, `PartsClerk`, and `DealerPrincipal`. A `SalesManager` owns inventory intake, sales deals, trade-ins, and test rides. A `FinanceManager` owns the finance submission, approval, and decline steps of a deal. A `ServiceAdvisor` owns repair orders, service lines, storage agreements, and warranty submission. A `PartsClerk` owns parts inventory and part reservations. A `DealerPrincipal` owns floor-plan financing and warranty adjudication, and additionally holds override authority over the fiscal gates described later in this document.

For all five roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it for audit purposes, but it does not compare `X-User-ID` to any resource's `id` and performs no ownership matching based on it. Authorization is decided solely by whether `X-User-Role` is permitted for the requested operation; there is no per-record ownership check anywhere in this system. In particular, the `Technician` resource is a schedulable shop resource rather than a role, and its `id` is never expected to equal any caller's `X-User-ID`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with no upper bound.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Most resources in this system are full first-class records and carry a standard set of system-managed fields:

- `id` — a unique, server-minted identifier formatted as a UUID. It carries no type prefix and is used only for identity; it is never derived from any input field.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits indicating when the resource was first created.
- `updated_at` — an ISO 8601 UTC timestamp, also with three fractional digits, indicating when the resource was last modified. It is refreshed on every mutation, including mutations that occur as automatic cascades triggered by operations on other resources.
- `version` — an integer that starts at 1 when the resource is created and increases by exactly 1 on every mutation, including cascade mutations. It is the basis for the optimistic concurrency control described in Section 2.6.

Four resources are deliberate exceptions because they are append-only or immutable ledger lines rather than mutable records. A `Curtailment`, a `ServiceLine`, a `PartLine`, and a `Part`'s reservation lines are written once and never updated in place; specifically, `Curtailment`, `ServiceLine`, and `PartLine` carry only `id` and `created_at` — they have neither an `updated_at` field nor a `version` field. Where the narrative below refers to a line's `status` changing (for example a `PartLine` moving to `CONSUMED`), that change is modeled by the parent operation and does not give the line its own `version`.

### 2.5. Monetary Values, Precision, and Rounding

Every monetary amount in this system is stored and exchanged as an integer number of cents. Field names that end in `_cents` are whole-cent integers, and rates are expressed in basis points (a field ending in `_bps`, where 10000 basis points equals 100 percent). Because all stored money is integer cents, additions and subtractions of money never round. Rounding enters only where a rate is applied — a tax, an interest per-diem, a shop-supply percentage, or a curtailment percentage — and in every such case the platform uses the **round half up** method, meaning a fractional result of exactly one-half cent rounds away from zero to the next whole cent.

A rounding subtlety recurs across several calculations and is binding wherever it appears: when two or more rate-derived amounts are summed, each amount is rounded to whole cents **first**, and only then are the rounded amounts added. The platform never sums the unrounded fractional amounts and rounds the single total. This per-line-then-sum order is pinned for the two taxable lines of a deal and for the per-service-line labor of a repair order, and it can produce a cent total that differs from rounding once at the end.

### 2.6. Optimistic Concurrency Control on Shared Ledgers

Two create operations act against a parent ledger whose balance another writer may have already changed, and both therefore require the client to prove it is working from a current view of that parent. In each case the client supplies the parent's last-observed `version`, and a mismatch with the parent's actual current `version` is rejected before any write occurs.

When a curtailment is posted against a floor-plan loan, the request body must include `expected_floor_plan_loan_version` carrying the `version` of the target `FloorPlanLoan` as the client last read it. If that value does not equal the loan's current `version` — because another writer has, for example, already posted a curtailment that reduced the principal and thereby changed the basis for this paydown — the request is rejected with `ERR_STALE_LOAN_VERSION` (HTTP 412), and no curtailment is created.

When a part line is reserved against a part, the request body must include `expected_part_version` carrying the `version` of the target `Part` as the client last read it. If that value does not equal the part's current `version` — because another writer has already reserved or restocked the part, leaving the client's view of availability stale — the request is rejected with `ERR_STALE_PART_VERSION` (HTTP 412), and no reservation is created. These two operations are the only ones that take a version field; no other endpoint accepts or requires one.

### 2.7. Resource Existence and Left-to-Right Reference Validation

Because relationships are expressed through identifiers in paths and bodies rather than nested URLs, every write that names another resource must resolve those references. The platform validates them left to right: the identifier in the URL path is checked first, then the foreign-key identifiers in the request body in the order they are declared for that operation. The first identifier that does not resolve to an existing resource produces that resource's specific not-found error — `ERR_CUSTOMER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_TRADE_IN_NOT_FOUND`, `ERR_FLOOR_PLAN_LOAN_NOT_FOUND`, `ERR_REPAIR_ORDER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`, `ERR_STORAGE_AGREEMENT_NOT_FOUND`, `ERR_STORAGE_BAY_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`, or `ERR_WARRANTY_CLAIM_NOT_FOUND` — each at HTTP 404, and no further validation runs.

### 2.8. Order of Validation

When a single request could fail several checks, the platform evaluates them in a fixed priority so that the returned error is deterministic. Authentication of the headers comes first (`ERR_MISSING_OR_INVALID_USER_CONTEXT`), then role authorization (`ERR_FORBIDDEN_ROLE`), then existence of every referenced resource as described in Section 2.7. Only after those pass does the platform check that the request body is well formed — required fields present, enum values in range, and integer fields within their stated constraints — rejecting violations with `ERR_INVALID_REQUEST` (HTTP 422). Uniqueness of the unique fields is checked next, raising `ERR_DUPLICATE_RESOURCE` (HTTP 409). Where an operation requires optimistic concurrency (Section 2.6), the version match is checked next, raising the relevant stale-version error at HTTP 412. The state-machine from-state check follows: any transition attempted from a state that is not a legal predecessor is rejected, and where a more specific state error is not named for that transition the generic `ERR_INVALID_STATE` (HTTP 409) is returned. After the from-state check come any cross-entity precondition on a referenced sibling resource, then the domain-specific safety, temporal, stock, and fiscal rules described in Section 3. This ordering means, for example, that a malformed body is reported as `ERR_INVALID_REQUEST` before any state check, and that a stale-version rejection precedes a from-state rejection.

### 2.9. Automatic Cascades and Inventory Conservation

A defining characteristic of this platform is that one client action frequently mutates several resources. Delivering a deal, for example, drives the sold unit to `DELIVERED`, posts a payoff curtailment that retires the unit's floor-plan loan, and — when a trade was attached — titles the trade and mints a brand-new inventory unit, all in one transaction. Every resource touched by such a cascade independently has its `updated_at` refreshed and its `version` incremented, exactly as if it had been the direct target of a request; the precise cascade hops are described in Section 3.

A second invariant the platform never violates is parts conservation. For any `Part`, the quantity on hand always equals the quantity available plus the quantity reserved plus the quantity consumed. Reserving, releasing, and consuming part lines move quantity between the `available_qty`, `reserved_qty`, and `consumed_qty` buckets but never change `on_hand_qty` except through an explicit restock; the exact arithmetic is given in Section 3.

### 2.10. The Test-Driving Clock

Several rules in this system depend on the passage of time — floor-plan aging, interest accrual, and test-ride-waiver expiry all read the server's current UTC clock. To make those behaviors deterministic and testable, the server exposes an administrative capability, restricted to the `DealerPrincipal`, that sets the logical clock to a supplied instant. The request carries a single field, `to_iso8601`, an ISO 8601 timestamp, and the server adopts it as the current time. All aging, accrual, and expiry comparisons read this logical clock rather than wall-clock time.

## 3. Business Logic & Workflows

### 3.1. Customers, Units, and Floor-Plan Inventory

A `Customer` is the simplest record in the system, created with a `full_name`, an `email`, and a `phone`. The `email` is unique across the dealer; an attempt to create a second customer with the same email is rejected with `ERR_DUPLICATE_RESOURCE`.

Inventory is tracked as `Unit` records. A unit is created with a `vin`, a `category`, a `model_year`, an `msrp_cents`, a `dealer_cost_cents`, and optionally an `acquisition_kind`. The `vin` must be exactly 17 characters of uppercase alphanumerics and is unique across all units; a duplicate VIN is rejected with `ERR_DUPLICATE_RESOURCE`, and a VIN of any other length is a malformed body. The `category` is one of `MOTORCYCLE`, `ATV`, `UTV`, `PWC`, or `SNOWMOBILE`. The `model_year` must be at least 2000, and both `msrp_cents` and `dealer_cost_cents` must be zero or greater. The `acquisition_kind` is one of `NEW_FLOORED`, `TRADE_IN`, or `CASH_OWNED`; when omitted it defaults to `NEW_FLOORED`. Newly created units begin life in the `IN_TRANSIT` inventory status.

A unit's `status` moves through the inventory lifecycle `IN_TRANSIT`, `IN_STOCK`, `ON_HOLD`, `SOLD`, and finally the terminal `DELIVERED`. Receiving a unit advances it from `IN_TRANSIT` to `IN_STOCK`; this is the only manually triggered unit transition, performed by a `SalesManager` or a `DealerPrincipal`. Receiving a `NEW_FLOORED` unit does not open a floor plan automatically — even when `acquisition_kind` is `NEW_FLOORED` and `floor_plan_loan_id` is still null, the floor plan is opened as a separate step. Every later unit transition (`IN_STOCK` to `ON_HOLD`, `ON_HOLD` back to `IN_STOCK`, `ON_HOLD` to `SOLD`, and `SOLD` to `DELIVERED`) is driven automatically by the deal lifecycle and never requested directly on the unit. The two system-managed fields `floor_plan_loan_id` and `held_by_deal_id` carry, respectively, the floored loan for a `NEW_FLOORED` unit (otherwise null) and the deal currently holding the unit while its status is `ON_HOLD` (cleared otherwise).

A `FloorPlanLoan` finances the dealer's cost of carrying a `NEW_FLOORED` unit on the showroom floor. It is opened by a `DealerPrincipal` with three inputs: the `unit_id` of the floored unit, the `opened_on` date from which interest accrues, and the annual rate `apr_bps` in basis points. On open, the server sets `original_advance_cents` equal to that unit's `dealer_cost_cents`, sets `principal_outstanding_cents` equal to `original_advance_cents`, places the loan in `OPEN` status, and writes the new loan's id back onto the unit's `floor_plan_loan_id`. The loan's `cumulative_curtailment_cents` begins at zero. Each floored unit has exactly one loan.

### 3.2. Floor-Plan Aging, Curtailments, and Interest

A floor-plan loan ages toward a mandatory principal paydown. Running aging on a loan, an action reserved for the `DealerPrincipal`, advances it from `OPEN` to `CURTAILMENT_DUE` once the number of whole days between its `opened_on` date and the current clock reaches the curtailment-due threshold, which is 90 days; the comparison is inclusive, so the loan becomes due at exactly 90 days, not 91. If fewer than 90 days have elapsed, the loan stays `OPEN`.

A `Curtailment` is an append-only ledger line that pays principal down on a loan. It is posted by a `DealerPrincipal` and carries the `floor_plan_loan_id` of the loan being curtailed, a `principal_cents` amount that must be greater than zero, an optional `reason`, and the concurrency field `expected_floor_plan_loan_version` described in Section 2.6. The `reason` is one of `SCHEDULED`, `SALE_PAYOFF`, or `VOLUNTARY`, defaulting to `SCHEDULED`. Curtailments are always created in `POSTED` status; there is no reversal flow. Posting a curtailment reduces the loan's `principal_outstanding_cents` by the paid principal, increases `cumulative_curtailment_cents` by the same amount, and increments the loan's `version` by one.

A `SCHEDULED` curtailment that satisfies the required minimum brings a `CURTAILMENT_DUE` loan back to `OPEN`. The required minimum is ten percent of the loan's original advance: take `original_advance_cents`, multiply by the curtailment percentage of 1000 basis points, divide by 10000, and round half up. The posted `principal_cents` must be at least that required amount; a `SCHEDULED` curtailment below it is rejected with `ERR_CURTAILMENT_INSUFFICIENT` (HTTP 422). A curtailment with reason `SALE_PAYOFF` pays the loan off entirely and requires that `principal_cents` exactly equal the loan's current `principal_outstanding_cents`; if the amount is not the full outstanding balance, the payoff is rejected with `ERR_PAYOFF_NOT_FULL` (HTTP 422). A successful full payoff — whether posted directly with reason `SALE_PAYOFF` or generated as a cascade when a unit is delivered — drives the loan from either `OPEN` or `CURTAILMENT_DUE` to the terminal `PAID_OFF` status and sets `principal_outstanding_cents` to zero.

Interest on a floor-plan loan is reported in `accrued_interest_cents` and can be read two ways, selected by an `interest_basis` query parameter when fetching a loan; it is also recomputed when aging is run. The number of whole elapsed days is the floor of the seconds between `opened_on` and the current clock divided by 86400. Both variants use a 365-day year. The **simple** variant — the default presentation, and the basis used by the aging check — computes a per-diem by taking `original_advance_cents`, multiplying by `apr_bps`, dividing by 10000 and then by 365, and rounding that per-diem half up; the accrued interest is that per-diem multiplied by the number of elapsed days, and curtailments are ignored. The **declining** variant, requested with an `interest_basis` of `DECLINING`, instead walks the loan's `POSTED` curtailments in `created_at` ascending order (ties broken first by `created_at`, then by the lower `principal_cents`) and accrues per-diem on the principal outstanding within each segment between curtailment boundaries: for each segment it multiplies that segment's outstanding principal by `apr_bps`, divides by 10000 and by 365, rounds the per-diem half up, multiplies by the number of days in the segment, and sums across segments. Because the declining basis charges per-diem on a falling balance, the same loan and payments always yield a smaller number under `DECLINING` than under `SIMPLE`.

### 3.3. The Sales Deal Lifecycle

A `Deal` is the central sales workflow and ties together a buyer, a unit, and optionally a trade. It is created by a `SalesManager` in `DRAFT` status with the `customer_id` of the buyer, the `unit_id` being sold, an optional `trade_in_id`, the negotiated `sale_price_cents`, an optional `freight_setup_cents`, an optional `doc_fee_cents`, the `tax_rate_bps` to apply, an optional `down_payment_cents`, and an optional `approved_lender_payoff_cents`. The `freight_setup_cents` defaults to 0 and the `down_payment_cents` defaults to 0; the `doc_fee_cents` defaults to 39900 (that is, $399.00); the `approved_lender_payoff_cents` defaults to 0. Each of `sale_price_cents`, `freight_setup_cents`, `doc_fee_cents`, `tax_rate_bps`, `down_payment_cents`, and `approved_lender_payoff_cents` must be zero or greater. The deal's `status` progresses through `DRAFT`, `QUOTED`, `FINANCE_SUBMITTED`, `APPROVED`, `DELIVERED`, with the side branches `DECLINED` and `CANCELLED`; `DELIVERED` and `CANCELLED` are terminal.

Quoting a deal, performed by a `SalesManager`, advances it from `DRAFT` to `QUOTED`. The referenced unit must be `IN_STOCK`, otherwise the quote is rejected with `ERR_UNIT_NOT_AVAILABLE`; and if a `trade_in_id` is present, that trade must be in `APPRAISED` status, otherwise the quote is rejected with `ERR_TRADE_NOT_APPRAISED`. A successful quote moves the unit from `IN_STOCK` to `ON_HOLD` and stamps `held_by_deal_id` with this deal's id, and computes the deal's financial figures using the provisional variant described in Section 3.4. The same quote action is reused to re-quote a `DECLINED` deal: a deal may move from `DECLINED` back to `QUOTED`, which again requires the unit to be `IN_STOCK` (else `ERR_UNIT_NOT_AVAILABLE`), again places the unit `ON_HOLD` under this deal, and again recomputes the figures with the provisional variant. This re-quote path makes the deal lifecycle cyclic.

A `FinanceManager` carries the deal through its finance steps. Submitting to finance advances a `QUOTED` deal to `FINANCE_SUBMITTED` with no precondition beyond the from-state. From `FINANCE_SUBMITTED`, the finance manager may approve or decline. Approving requires that the referenced unit be `ON_HOLD` and held by this very deal (its `held_by_deal_id` equal to this deal's id), otherwise approval is rejected with `ERR_UNIT_NOT_AVAILABLE`. Approval recomputes `trade_allowance_cents`, `out_the_door_cents`, and `amount_financed_cents` using the final variant of Section 3.4 — the final lender-confirmed payoff changes trade equity, which flows through the trade tax credit into the out-the-door price and then into the financed amount — moves the unit from `ON_HOLD` to `SOLD`, and, if a trade is attached, advances that trade from `APPRAISED` to `ACCEPTED` (the first cascade hop). Declining a `FINANCE_SUBMITTED` deal moves it to `DECLINED`, returns the unit from `ON_HOLD` to `IN_STOCK`, and clears the unit's `held_by_deal_id`.

Delivering an `APPROVED` deal, performed by a `SalesManager`, is the settlement step and requires that the unit be `SOLD`, otherwise it is rejected with `ERR_UNIT_NOT_AVAILABLE`. Delivery drives a chain of cascades: the unit advances from `SOLD` to the terminal `DELIVERED`; if that unit has a `floor_plan_loan_id`, a `SALE_PAYOFF` curtailment for the loan's full `principal_outstanding_cents` is posted and the loan is driven to `PAID_OFF`; and if the deal carries a trade, that trade advances from `ACCEPTED` to the terminal `TITLED`, which in turn mints a new inventory unit as described in Section 3.5. A deal still in `DRAFT` or `QUOTED` may instead be cancelled by a `SalesManager`, moving it to the terminal `CANCELLED`; if the referenced unit is currently held by this deal, cancellation returns it from `ON_HOLD` to `IN_STOCK` and clears its `held_by_deal_id`.

### 3.4. Deal Pricing: Trade Equity, Out-the-Door, and Financing

Three computed amounts live on every quoted or approved deal — `trade_allowance_cents`, `out_the_door_cents`, and `amount_financed_cents` — and each is computed in one of two variants. The **provisional** variant is used when a deal is quoted (both the first `DRAFT`-to-`QUOTED` quote and any `DECLINED`-to-`QUOTED` re-quote). The **final** variant is used when a deal is approved. The two variants share identical formulas and differ only in which lien-payoff number feeds trade equity.

Trade equity, recorded in `trade_allowance_cents`, is the trade's appraised value minus the lien payoff on it. Concretely, `trade_allowance_cents` equals the trade's `appraised_value_cents` minus the payoff. Under the provisional variant the payoff is the trade's `estimated_payoff_cents`; under the final variant the payoff is the deal's `approved_lender_payoff_cents`. The result may be negative — negative equity is permitted and is rolled forward into financing. If the deal has no trade (no `trade_in_id`), the trade allowance is zero.

The out-the-door price, `out_the_door_cents`, aggregates two independently taxable lines plus a non-taxable documentation fee. The first taxable line is the unit sale net of any positive trade allowance: take `sale_price_cents`, subtract the trade allowance but only to the extent it is positive (a negative trade allowance does not increase the taxable sale), and floor the result at zero. The second taxable line is the freight-and-setup charge, `freight_setup_cents`, taxed in full as its own line. Tax on each line is that line's taxable base multiplied by `tax_rate_bps`, divided by 10000, then rounded half up; crucially, the two tax amounts are each rounded to whole cents **before** they are added, never summed as fractions and rounded once (see Section 2.5). The out-the-door price is then the sum of `sale_price_cents`, `freight_setup_cents`, the rounded tax on the sale line, the rounded tax on the freight line, and the documentation fee `doc_fee_cents`. The documentation fee is never taxed.

The amount sent to the lender, `amount_financed_cents`, is the out-the-door price minus the cash `down_payment_cents` minus the trade allowance counted only when it is positive: that is, `out_the_door_cents` less `down_payment_cents` less the greater of the trade allowance and zero. The result is floored at zero so the financed amount is never negative. Because the provisional and final variants feed a different payoff into trade equity, an identical deal yields a different `amount_financed_cents` at quote than at approval whenever a trade is attached and the estimated and lender-confirmed payoffs differ. All of these amounts are integer cents and involve no rounding beyond the per-line tax rounding above.

### 3.5. Trade-Ins

A `TradeIn` captures a unit a customer offers against a purchase. A `SalesManager` creates it with the `customer_id` of the trade owner, the trade unit's `vin` (17 characters), a `category` from the same enumeration as inventory units, an `appraised_value_cents`, and an optional `estimated_payoff_cents` that defaults to 0; both money fields must be zero or greater. A new trade begins in `APPRAISED` status. Its lifecycle is `APPRAISED`, then either `ACCEPTED` and onward to the terminal `TITLED`, or directly to the terminal `REJECTED`.

A `SalesManager` may reject an `APPRAISED` trade outright, moving it to `REJECTED`. Otherwise a trade advances only as a cascade of the deal it is attached to: when that deal is approved, the trade moves from `APPRAISED` to `ACCEPTED` (and this transition itself requires the trade to be in `APPRAISED`, failing with `ERR_TRADE_NOT_APPRAISED` if it is not); when that deal is delivered, the trade moves from `ACCEPTED` to `TITLED`. Titling a trade mints a new `Unit` into inventory: the new unit is created with `acquisition_kind` of `TRADE_IN`, status `IN_STOCK`, and `dealer_cost_cents` set equal to the trade's `appraised_value_cents`. The id of that minted unit is written back onto the trade's `resulting_unit_id`; until titling occurs, `resulting_unit_id` is null.

### 3.6. The Service Shop: Technicians and Repair Orders

A `Technician` is a schedulable shop resource, created by a `ServiceAdvisor` or `DealerPrincipal` with a `name`, an `hourly_cost_cents` internal labor cost rate, and an optional `cleanup_buffer_minutes` that defaults to 30. The cleanup buffer is a mandatory gap enforced after each of that technician's appointments before the next may begin.

A `RepairOrder` represents a service job and carries two independent state dimensions. A `ServiceAdvisor` opens one with the `unit_id` of the serviced unit, the paying `customer_id`, the assigned `technician_id`, an `appointment_start` and an `appointment_end` (the end must be strictly after the start), an optional `is_warranty` flag defaulting to false, and an optional `authorized_amount_cents` estimate ceiling defaulting to 0. On creation the repair order's `work_status` is `OPEN` and its `billing_status` is `UNBILLED`. Before the order is created, the platform checks the assigned technician's schedule: if the requested appointment window — taken as a closed interval and extended by that technician's `cleanup_buffer_minutes` gap — overlaps any existing repair-order window for the same technician, the request is rejected with `ERR_TECH_SCHEDULE_CONFLICT`.

The **work dimension**, `work_status`, runs `OPEN`, `IN_PROGRESS`, `WORK_COMPLETE`, with `CANCELLED` as its terminal state. Starting work advances `OPEN` to `IN_PROGRESS` and requires that at least one `ServiceLine` already exist on the order, otherwise it is rejected with `ERR_NO_SERVICE_LINES`. Completing work advances `IN_PROGRESS` to `WORK_COMPLETE`; on completion the platform finalizes `labor_total_cents`, `shop_supplies_cents`, `parts_total_cents`, and `ro_total_cents` (Section 3.7), and consumes every reserved part line on the order — each such `PartLine` moves from `RESERVED` to `CONSUMED`, and for its `Part` the `reserved_qty` is decreased by the line quantity while `consumed_qty` is increased by the same quantity, preserving conservation. Cancelling a repair order is permitted only while its `billing_status` is still `UNBILLED`, otherwise it is rejected with `ERR_RO_ALREADY_BILLED`; cancellation moves `work_status` from `OPEN` or `IN_PROGRESS` to the terminal `CANCELLED`, releases every `RESERVED` part line on the order (each line moves to `RELEASED` and its part's `reserved_qty` is decreased by the line quantity, restoring availability), and — as a coupled effect on the other dimension — voids the billing.

The **billing dimension**, `billing_status`, evolves independently of work and runs `UNBILLED`, `INVOICED`, `PAID`, with `VOID` as its terminal state. Invoicing moves `UNBILLED` to `INVOICED` but requires the work dimension to have reached `WORK_COMPLETE`, otherwise it is rejected with `ERR_WORK_NOT_COMPLETE`; the fiscal authorization gate on invoicing is described in Section 3.8. Paying moves `INVOICED` to `PAID`. When the work dimension is cancelled, the billing dimension is automatically driven from `UNBILLED` to the terminal `VOID` by the same operation. Although `INVOICED` depends on the work-state being `WORK_COMPLETE`, the two fields are otherwise separate and are reported separately.

### 3.7. Service Lines, Flat-Rate Labor, and Shop Supplies

A `ServiceLine` is a flat-rate operation added to an `OPEN` repair order by a `ServiceAdvisor`. It carries the `repair_order_id` of its parent order, an `operation_code` identifying the published operation, and the `flat_rate_hours` published for that operation, which must be greater than zero. A line records `extended_labor_cents`, the per-line labor figured as its flat-rate hours times the effective hourly labor rate, rounded per line. Service lines are append-only ledger lines ordered by `created_at`; at create time `extended_labor_cents` is figured against the current tier as a preview, but the binding figures are produced when the repair order is completed.

When a repair order is completed, labor is finalized as follows. First sum the `flat_rate_hours` of all service lines on the order to obtain the order's total flat hours. The effective hourly rate then depends on that total under a tiered schedule: if the total is at most 2.0 hours, the rate is the base retail rate of 12500 cents per hour ($125.00); if the total is greater than 2.0 hours but at most 6.0 hours, the rate is the base less a 1000-cent discount, that is 11500 cents per hour; if the total is greater than 6.0 hours, the rate is the base less a 2500-cent discount, that is 10000 cents per hour. However, if the repair order is a warranty order (`is_warranty` is true), the tiered retail rate is overridden entirely and the manufacturer reimbursement rate of 9000 cents per hour ($90.00) is used instead. With the effective rate chosen, `labor_total_cents` is the sum over service lines of each line's `flat_rate_hours` multiplied by the effective rate and rounded half up per line before summation.

The shop-supply fee, `shop_supplies_cents`, is waived entirely for a warranty order and is therefore zero when `is_warranty` is true. For a non-warranty order it is 800 basis points (8 percent) of `labor_total_cents`: multiply the labor total by 800, divide by 10000, round half up, and then cap the result at 5000 cents ($50.00) — the fee is the lesser of that rounded 8 percent and the 5000-cent cap. The parts subtotal, `parts_total_cents`, is the sum of the `extended_cents` of the part lines consumed on the order. The order total, `ro_total_cents`, is the sum of `labor_total_cents`, `parts_total_cents`, and `shop_supplies_cents`.

### 3.8. Authorization Ceiling and the Dealer Override

The `authorized_amount_cents` on a repair order is the customer-authorized estimate ceiling. At invoice time, for a non-warranty order, the platform compares the finalized `ro_total_cents` against this ceiling: if the total exceeds the authorized amount, the invoice is blocked with `ERR_OVER_AUTHORIZATION` (HTTP 402) unless the caller is a `DealerPrincipal`, who holds override authority and may invoice over the authorized amount. Warranty orders are exempt from this ceiling check entirely; the authorization gate applies only when `is_warranty` is false.

### 3.9. Parts Inventory and Reservations

A `Part` is a stocked SKU created by a `PartsClerk` or `DealerPrincipal` with a non-empty `sku`, a `description`, a `unit_price_cents` retail price, and an `on_hand_qty`; the price must be zero or greater and the on-hand quantity zero or greater. The `sku` is unique, and a duplicate is rejected with `ERR_DUPLICATE_RESOURCE`. On creation `reserved_qty` and `consumed_qty` are zero and `available_qty` equals `on_hand_qty`. The available quantity is always the on-hand quantity minus reserved minus consumed. Restocking a part — increasing its `on_hand_qty` — is done by submitting an `add_qty`; restocking increases both `on_hand_qty` and `available_qty` by that amount and increments the part's `version`.

A `PartLine` reserves part quantity for a repair order. It is created by a `PartsClerk` or `ServiceAdvisor` with the `repair_order_id` the part is reserved for, the `part_id`, a `quantity` greater than zero, and the `expected_part_version` concurrency field of Section 2.6. The requested quantity must not exceed the part's `available_qty`; an over-reservation is rejected with `ERR_PART_INSUFFICIENT_STOCK`. A successful reservation increases the part's `reserved_qty` by the quantity, decreases its `available_qty` by the quantity, increments the part's `version`, records the line's `extended_cents` as the quantity times the part's `unit_price_cents` at reservation time, and sets the line `status` to `RESERVED`. A part line begins `RESERVED`, becomes `CONSUMED` when its repair order completes, or becomes `RELEASED` when its repair order is cancelled or the line is released directly. Releasing a reserved line directly is permitted to a `PartsClerk` or `ServiceAdvisor` only while the parent order's `billing_status` is `UNBILLED`, otherwise it is rejected with `ERR_RO_ALREADY_BILLED`; releasing moves the line to `RELEASED`, decreases the part's `reserved_qty` by the quantity, and increases `available_qty` by the quantity.

### 3.10. Seasonal Storage and Winterization

A `StorageBay` is a physical storage location created by a `ServiceAdvisor` or `DealerPrincipal` with a unique `label`; a duplicate label is rejected with `ERR_DUPLICATE_RESOURCE`.

A `StorageAgreement` places a unit into a bay for a season. A `ServiceAdvisor` creates one with the `unit_id` to store, the paying `customer_id`, the assigned `storage_bay_id`, a `period_start` and a `period_end` (the end is exclusive and must be after the start), a `monthly_rate_cents`, and an optional `includes_winterization` flag defaulting to false. A new agreement starts in `RESERVED` status; its lifecycle is `RESERVED`, then `CHECKED_IN`, then the terminal `CHECKED_OUT`, or from `RESERVED` directly to the terminal `CANCELLED`. Checking in advances `RESERVED` to `CHECKED_IN` but only if no other `CHECKED_IN` agreement occupies the same `storage_bay_id` over an overlapping window; the storage window is half-open on `[period_start, period_end)`, so two agreements that merely touch at an endpoint do not overlap, while any true overlap is rejected with `ERR_BAY_DOUBLE_BOOKED`. If the agreement `includes_winterization`, checking in also mints a preparation repair order for the stored unit (a non-warranty order in `work_status` `OPEN`) and records its id on `prep_repair_order_id`.

Checking out advances `CHECKED_IN` to the terminal `CHECKED_OUT` and finalizes `storage_fee_cents`. If the agreement has a `prep_repair_order_id`, that preparation order's `work_status` must be `WORK_COMPLETE` or `CANCELLED` before check-out is allowed; otherwise check-out is rejected with `ERR_PREP_RO_OPEN`. A `RESERVED` agreement may instead be cancelled to the terminal `CANCELLED`. The storage fee is computed by months, rounding partial periods up: take the ceiling of the seconds between `period_start` and `period_end` divided by 86400 to get the span in whole days, then take the ceiling of that span divided by 30 to get the number of months (a partial month rounds up to a full month), and multiply the months by `monthly_rate_cents` to get the base. When `includes_winterization` is true, a winterization fee of 14900 cents ($149.00) is added to that base; otherwise the base alone is the `storage_fee_cents`.

### 3.11. Test-Ride Waivers

A `TestRideWaiver` captures liability before a customer rides a unit. A `SalesManager` creates one with the `customer_id` of the rider, the `unit_id` to be ridden, a `signed_at` signature timestamp, and a `valid_until` expiry timestamp that must be after the signing time. A new waiver is `SIGNED`; the lifecycle terminal states are `RIDE_LOGGED`, `EXPIRED`, and `VOID`.

Logging a completed ride is the safety-gated action. A ride may not be logged at all unless a `SIGNED`, unexpired waiver exists for that customer-and-unit pairing; an attempt to log a ride without one is rejected with `ERR_WAIVER_REQUIRED` (HTTP 403). When logging a ride against a `SIGNED` waiver, two further conditions are checked. If the current clock is at or after the waiver's `valid_until`, the waiver is moved to `EXPIRED` and the ride is rejected with `ERR_WAIVER_EXPIRED`; reaching the expiry instant exactly is treated as expired. If the waiver is still within its validity window, the referenced unit must be in `IN_STOCK` or `ON_HOLD` status to be ridden, otherwise the ride is rejected with `ERR_UNIT_NOT_RIDEABLE`. When both conditions are satisfied, the waiver advances from `SIGNED` to `RIDE_LOGGED`. A `SalesManager` may also void a `SIGNED` waiver outright, moving it to the terminal `VOID`.

### 3.12. Warranty and Recall Claims

A `WarrantyClaim` is submitted to the manufacturer for reimbursement. A `ServiceAdvisor` or `DealerPrincipal` submits one with the `unit_id` under claim, a `kind` of either `WARRANTY` (a defect repair) or `RECALL` (a campaign), and an optional `repair_order_id` naming the warranty repair order that carries the labor. A claim is polymorphic in its subject: a warranty claim is settled against a sold unit, while the labor it reimburses lives on a repair order. A new claim is `SUBMITTED`; its lifecycle is `SUBMITTED`, then either `APPROVED` and onward to the terminal `PAID`, or directly to the terminal `REJECTED`.

The amount claimed, `claim_amount_cents`, is computed when the claim is created and recomputed when it is approved. The referenced repair order is expected to be a warranty order; if there is no `repair_order_id`, the claimed amount is zero. For a `RECALL`, the manufacturer pays labor only, so the claimed amount is the referenced order's `labor_total_cents`. For a `WARRANTY` claim, the manufacturer pays labor plus parts, so the claimed amount is the order's `labor_total_cents` plus its `parts_total_cents`.

Adjudication is reserved for the `DealerPrincipal`. Approving a `SUBMITTED` claim requires that the referenced unit be in `DELIVERED` status, otherwise it is rejected with `ERR_UNIT_NOT_DELIVERED`; approval recomputes `claim_amount_cents`. A `SUBMITTED` claim may instead be rejected, moving it to the terminal `REJECTED`. Paying an `APPROVED` claim moves it to the terminal `PAID`; and if the claim names a repair order whose `billing_status` is `UNBILLED` and whose `work_status` is `WORK_COMPLETE`, paying the claim settles that order by moving its `billing_status` directly to `PAID` — the warranty payment pays the repair order.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including lifecycle transitions, restocks, and the administrative clock set — return `200 OK`. The complete request and response shape for each operation is reconstructed from the Section 3 narratives; the table below lists only the method, path, purpose, and which roles may call it.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set` | Set the server's current UTC clock (test-driving) | DealerPrincipal |
| POST | `/customers` | Create a customer | SalesManager, ServiceAdvisor |
| GET | `/customers` | List customers (filter by email) | SalesManager, ServiceAdvisor, FinanceManager, PartsClerk, DealerPrincipal |
| GET | `/customers/{id}` | Get a customer | SalesManager, ServiceAdvisor, FinanceManager, PartsClerk, DealerPrincipal |
| POST | `/units` | Create a unit (inventory intake) | SalesManager, DealerPrincipal |
| GET | `/units` | List units (filter by status, vin, floor_plan_loan_id, held_by_deal_id) | SalesManager, ServiceAdvisor, FinanceManager, PartsClerk, DealerPrincipal |
| GET | `/units/{id}` | Get a unit | SalesManager, ServiceAdvisor, FinanceManager, PartsClerk, DealerPrincipal |
| POST | `/units/{id}/receive` | Receive a unit into stock | SalesManager, DealerPrincipal |
| POST | `/floor-plan-loans` | Open a floor-plan loan | DealerPrincipal |
| GET | `/floor-plan-loans` | List floor-plan loans (filter by unit_id, status) | DealerPrincipal, FinanceManager, SalesManager |
| GET | `/floor-plan-loans/{id}` | Get a floor-plan loan (interest_basis selects accrual variant) | DealerPrincipal, FinanceManager, SalesManager |
| POST | `/floor-plan-loans/{id}/run-aging` | Run aging on a loan | DealerPrincipal |
| POST | `/curtailments` | Post a curtailment against a loan | DealerPrincipal |
| GET | `/curtailments` | List curtailments (filter by floor_plan_loan_id) | DealerPrincipal, FinanceManager |
| GET | `/curtailments/{id}` | Get a curtailment | DealerPrincipal, FinanceManager |
| POST | `/trade-ins` | Create a trade-in appraisal | SalesManager |
| GET | `/trade-ins` | List trade-ins (filter by customer_id, status, resulting_unit_id) | SalesManager, FinanceManager, DealerPrincipal |
| GET | `/trade-ins/{id}` | Get a trade-in | SalesManager, FinanceManager, DealerPrincipal |
| POST | `/trade-ins/{id}/reject` | Reject a trade-in | SalesManager |
| POST | `/deals` | Create a sales deal | SalesManager |
| GET | `/deals` | List deals (filter by customer_id, unit_id, trade_in_id, status) | SalesManager, FinanceManager, DealerPrincipal |
| GET | `/deals/{id}` | Get a deal | SalesManager, FinanceManager, DealerPrincipal |
| POST | `/deals/{id}/quote` | Quote or re-quote a deal | SalesManager |
| POST | `/deals/{id}/submit-finance` | Submit a deal to finance | FinanceManager |
| POST | `/deals/{id}/approve` | Approve financing | FinanceManager |
| POST | `/deals/{id}/decline` | Decline financing | FinanceManager |
| POST | `/deals/{id}/deliver` | Deliver the unit | SalesManager |
| POST | `/deals/{id}/cancel` | Cancel a deal | SalesManager |
| POST | `/technicians` | Create a technician | ServiceAdvisor, DealerPrincipal |
| GET | `/technicians` | List technicians | ServiceAdvisor, DealerPrincipal |
| GET | `/technicians/{id}` | Get a technician | ServiceAdvisor, DealerPrincipal |
| POST | `/repair-orders` | Open a repair order | ServiceAdvisor |
| GET | `/repair-orders` | List repair orders (filter by unit_id, customer_id, technician_id, work_status, billing_status) | ServiceAdvisor, PartsClerk, DealerPrincipal, SalesManager |
| GET | `/repair-orders/{id}` | Get a repair order | ServiceAdvisor, PartsClerk, DealerPrincipal, SalesManager |
| POST | `/repair-orders/{id}/start` | Begin work | ServiceAdvisor |
| POST | `/repair-orders/{id}/complete` | Complete work; finalize totals; consume parts | ServiceAdvisor |
| POST | `/repair-orders/{id}/invoice` | Invoice the repair order | ServiceAdvisor, DealerPrincipal |
| POST | `/repair-orders/{id}/pay` | Mark the repair order paid | ServiceAdvisor, DealerPrincipal |
| POST | `/repair-orders/{id}/cancel` | Cancel the repair order | ServiceAdvisor |
| POST | `/service-lines` | Add a flat-rate service line | ServiceAdvisor |
| GET | `/service-lines` | List service lines (filter by repair_order_id) | ServiceAdvisor, DealerPrincipal |
| GET | `/service-lines/{id}` | Get a service line | ServiceAdvisor, DealerPrincipal |
| POST | `/parts` | Create a part/accessory SKU | PartsClerk, DealerPrincipal |
| GET | `/parts` | List parts (filter by sku) | PartsClerk, ServiceAdvisor, DealerPrincipal |
| GET | `/parts/{id}` | Get a part | PartsClerk, ServiceAdvisor, DealerPrincipal |
| POST | `/parts/{id}/restock` | Increase a part's on-hand quantity | PartsClerk, DealerPrincipal |
| POST | `/part-lines` | Reserve parts for a repair order | PartsClerk, ServiceAdvisor |
| GET | `/part-lines` | List part lines (filter by repair_order_id, part_id) | PartsClerk, ServiceAdvisor, DealerPrincipal |
| GET | `/part-lines/{id}` | Get a part line | PartsClerk, ServiceAdvisor, DealerPrincipal |
| DELETE | `/part-lines/{id}` | Release a reserved part line | PartsClerk, ServiceAdvisor |
| POST | `/storage-bays` | Create a storage bay | ServiceAdvisor, DealerPrincipal |
| GET | `/storage-bays` | List storage bays (filter by label) | ServiceAdvisor, DealerPrincipal |
| GET | `/storage-bays/{id}` | Get a storage bay | ServiceAdvisor, DealerPrincipal |
| POST | `/storage-agreements` | Create a storage agreement | ServiceAdvisor |
| GET | `/storage-agreements` | List storage agreements (filter by unit_id, customer_id, storage_bay_id, status, prep_repair_order_id) | ServiceAdvisor, DealerPrincipal |
| GET | `/storage-agreements/{id}` | Get a storage agreement | ServiceAdvisor, DealerPrincipal |
| POST | `/storage-agreements/{id}/check-in` | Check a unit into its bay | ServiceAdvisor |
| POST | `/storage-agreements/{id}/check-out` | Check a unit out; finalize the storage fee | ServiceAdvisor |
| POST | `/storage-agreements/{id}/cancel` | Cancel a reserved storage agreement | ServiceAdvisor |
| POST | `/test-ride-waivers` | Create a signed test-ride waiver | SalesManager |
| GET | `/test-ride-waivers` | List waivers (filter by customer_id, unit_id, status) | SalesManager, DealerPrincipal |
| GET | `/test-ride-waivers/{id}` | Get a waiver | SalesManager, DealerPrincipal |
| POST | `/test-ride-waivers/{id}/log-ride` | Log a completed ride or mark expired | SalesManager |
| POST | `/test-ride-waivers/{id}/void` | Void a waiver | SalesManager |
| POST | `/warranty-claims` | Submit a warranty/recall claim | ServiceAdvisor, DealerPrincipal |
| GET | `/warranty-claims` | List warranty claims (filter by unit_id, repair_order_id, status) | ServiceAdvisor, DealerPrincipal |
| GET | `/warranty-claims/{id}` | Get a warranty claim | ServiceAdvisor, DealerPrincipal |
| POST | `/warranty-claims/{id}/approve` | Approve a claim | DealerPrincipal |
| POST | `/warranty-claims/{id}/reject` | Reject a claim | DealerPrincipal |
| POST | `/warranty-claims/{id}/pay` | Pay a claim; may settle the linked warranty order | DealerPrincipal |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_UNIT_NOT_FOUND` | 404 |
| `ERR_FLOOR_PLAN_LOAN_NOT_FOUND` | 404 |
| `ERR_DEAL_NOT_FOUND` | 404 |
| `ERR_TRADE_IN_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_REPAIR_ORDER_NOT_FOUND` | 404 |
| `ERR_PART_NOT_FOUND` | 404 |
| `ERR_STORAGE_BAY_NOT_FOUND` | 404 |
| `ERR_STORAGE_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_WAIVER_NOT_FOUND` | 404 |
| `ERR_WARRANTY_CLAIM_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_DUPLICATE_RESOURCE` | 409 |
| `ERR_STALE_LOAN_VERSION` | 412 |
| `ERR_STALE_PART_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_NO_SERVICE_LINES` | 409 |
| `ERR_WORK_NOT_COMPLETE` | 409 |
| `ERR_RO_ALREADY_BILLED` | 409 |
| `ERR_TRADE_NOT_APPRAISED` | 409 |
| `ERR_PREP_RO_OPEN` | 409 |
| `ERR_WAIVER_EXPIRED` | 409 |
| `ERR_UNIT_NOT_AVAILABLE` | 409 |
| `ERR_UNIT_NOT_DELIVERED` | 409 |
| `ERR_UNIT_NOT_RIDEABLE` | 409 |
| `ERR_WAIVER_REQUIRED` | 403 |
| `ERR_BAY_DOUBLE_BOOKED` | 409 |
| `ERR_TECH_SCHEDULE_CONFLICT` | 409 |
| `ERR_CURTAILMENT_INSUFFICIENT` | 422 |
| `ERR_PAYOFF_NOT_FULL` | 422 |
| `ERR_PART_INSUFFICIENT_STOCK` | 409 |
| `ERR_OVER_AUTHORIZATION` | 402 |

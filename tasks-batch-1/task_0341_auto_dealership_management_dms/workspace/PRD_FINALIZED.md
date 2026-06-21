# Auto Dealership Management System (DMS) API — Product Requirements Document

## 1. Introduction

A modern franchised automobile dealership runs several tightly coupled businesses under one roof: a used- and new-vehicle inventory desk, a sales-and-desking floor, a finance-and-insurance (F&I) office, a wholesale floor-plan credit line that funds the cars sitting on the lot, a service and parts department, and a title clerk who closes the loop with the state Department of Motor Vehicles (DMV). The Auto Dealership Management System (DMS) API is the system of record that ties these functions together. It tracks every vehicle from acquisition (including vehicles taken in on trade), drives a deal through desking, lender submission, contracting, funding, and post-sale title work, and reconciles the floor-plan credit line as vehicles are sold and — when a sale falls apart — unwound.

The system's defining challenge is that money, inventory state, and credit obligations must stay consistent across many peer entities at once. Reserving a vehicle for a deal, accepting a trade, funding a contract, or unwinding a funded deal each triggers a chain of cascading effects across the vehicle, its floor-plan line, the trade-in it brought in, the finance contract, and the eventual title submission. Pricing is computed two ways — a provisional desking estimate and a final contracted figure — and the dealership's gross profit is split into a front-end (vehicle department) figure and a back-end (F&I department) figure that draw on disjoint inputs. This document specifies the entities, their lifecycles, the calculation rules, and the validation and concurrency guarantees the API must enforce so that a deal jacket always reflects an internally consistent picture of the sale.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. There is no shared URL prefix: each entity type is reached as a top-level collection (for example, vehicles, deals, customers, floor-plan lines), and cross-entity relationships are expressed by foreign-key references in request and response bodies rather than by nested ownership paths.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. If `X-User-Role` is missing or names a role the system does not recognize, the request is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly six roles: `InventoryClerk`, `SalesManager`, `FinanceManager`, `ServiceAdvisor`, `TitleClerk`, and `Customer`. When a recognized role attempts an operation outside the set of operations granted to it, the request is rejected with `ERR_FORBIDDEN`.

Roles map to distinct areas of responsibility. An `InventoryClerk` manages the vehicle inventory, floor-plan financing, curtailments, trade acquisition, and reconditioning. A `SalesManager` owns the desking side: customers, deals, desking and re-desking, incentives, lender submission, and test drives. A `FinanceManager` owns the F&I office: lender programs, finance products, finance contracts, lender decisions, contracting, funding, and unwind. A `ServiceAdvisor` owns service and parts repair orders. A `TitleClerk` owns DMV title and registration submission for funded deals. Some operations are shared across roles — for example, attaching a trade-in is permitted to both `SalesManager` and `InventoryClerk`, applying an incentive and creating an OEM incentive program are permitted to both `SalesManager` and `FinanceManager`, and uploading deal-jacket documents is permitted to `SalesManager`, `FinanceManager`, and `TitleClerk`.

For five of the six roles — `InventoryClerk`, `SalesManager`, `FinanceManager`, `ServiceAdvisor`, and `TitleClerk` — `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may accept and log it, but it is not compared against any resource's `id`; these roles are gated purely by which operations their role is permitted to perform. The `Customer` role is different: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record. Ownership checks on any resource that references a `Customer` compare that resource's `customer_id` to `X-User-ID`. A `Customer` may book and cancel their own test drives (the booking's `customer_id` must equal `X-User-ID`), read their own customer record, and list their own test drives; an attempt by a `Customer` to act on another customer's resource is rejected with `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and accepted values range from a minimum of 1 to a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by their creation timestamp (`created_at`) in ascending order. Each list response carries the pagination bookkeeping in the `meta` object of the envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and System Fields

Almost every entity in this system is a mutable, versioned resource. Such resources carry four system-managed fields: an `id` that is a server-minted UUID with no type prefix; a `created_at` ISO 8601 UTC timestamp with three fractional digits, fixed at creation; an `updated_at` ISO 8601 UTC timestamp with the same format, refreshed on every mutation; and a `version`, an integer that begins at 1 on creation and increments by one on every mutation. The mutable, versioned entities are the Vehicle, FloorPlanLine, Customer, TradeIn, Deal, LenderProgram, FinanceProduct, DealProduct, FinanceContract, OEMIncentive, TestDrive, RepairOrder, and TitleRegistration.

The single exception is the deal-jacket document, which is an immutable, append-only record. A deal-jacket document carries only an `id` and a `created_at`; it has neither an `updated_at` nor a `version` field, because once written it is never modified.

### 2.5. Hierarchical Consistency and Cascading State

Many operations in this domain are not confined to a single entity. Reserving, selling, or releasing a vehicle ripples into its floor-plan line, its trade-in, its finance contract, and its title record. Whenever the system writes a derived or system-managed field on a resource as part of such a ripple, that write counts as a mutation: the affected resource's `updated_at` is refreshed and its `version` increments by one. The detailed cascades — vehicle reservation on desking, the trade-acceptance chain on contracting, the sale-and-payoff chain on funding, and the compensation chain on unwind — are specified entity-by-entity in §3, but the rule that every cascade touch bumps `updated_at` and `version` on each mutated resource is universal.

The system performs these reconciliations itself, without requiring a separate client request against each affected resource. A single funding request, for instance, advances the deal, the vehicle, the floor-plan line, and creates a title record in one logical operation, incrementing the version of each mutated resource exactly once for that operation.

### 2.6. Nested-Path and Reference Resolution

Some endpoints address a sub-resource through a path that contains more than one identifier — for example, voiding a particular product line on a particular deal. The system validates path identifiers left to right: the deal in the path must resolve before the product line under it is considered, and the first identifier that does not resolve produces `ERR_NOT_FOUND`. Separately, foreign keys supplied in a request body — such as `vehicle_id`, `customer_id`, `deal_id`, `finance_product_id`, or `lender_program_id` — must reference existing resources; a body foreign key that points at nothing is rejected with `ERR_FK_NOT_FOUND`. Because the topology is flat, child collections are reached through the parent's collection (for example, the floor-plan lines of a vehicle, the products, trade-ins, finance contracts, and documents of a deal), and these listing endpoints are the reverse-reachability path from a parent back to the children that carry its foreign key.

### 2.7. Monetary Precision and Rounding

All monetary amounts are integers denominated in cents. Wherever a calculation produces a fractional cent, the system rounds half up to the nearest whole cent. Several calculations pin the order in which rounding happens relative to summation — most importantly the sales-tax computation, which rounds each taxable line to a whole cent **before** the lines are summed, rather than summing first and rounding once. These ordering rules are stated with each calculation in §3 and must be followed exactly, because round-per-line and sum-then-round can differ by up to a cent. Rate fields expressed in basis points (such as `tax_rate_bps`, `buy_rate_bps`, and `annual_rate_bps`) and percentage thresholds are applied as documented and are not themselves rounded to cents.

### 2.8. Validation Order and Precedence

When several checks could fail on one request, the system evaluates them in a fixed precedence so the returned error is deterministic. Authentication comes first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization is next: a role not permitted for the operation — or a `Customer` reaching for another customer's resource — yields `ERR_FORBIDDEN`. Existence checks follow: each path identifier is resolved left to right, and an unresolved one yields `ERR_NOT_FOUND`; then body foreign keys are resolved, and an unresolved one yields `ERR_FK_NOT_FOUND`. Request well-formedness is checked next — required fields present, enum values valid, a VIN exactly 17 characters, and numeric fields within their declared ranges — with violations yielding `ERR_INVALID_REQUEST`. After these universal gates, resource-specific constraints apply (for example, VIN uniqueness on vehicle creation yields `ERR_VIN_DUPLICATE`), followed by state-transition legality (`ERR_INVALID_STATE` when the target is not in a state from which the requested transition is defined), then optimistic-concurrency checks (`ERR_STALE_VERSION`), and finally the domain-specific business rules described throughout §3. Where a single operation layers several domain rules, the per-operation narrative in §3 names the order among them.

### 2.9. Optimistic Concurrency Control on Create-with-Supersede

Two create operations in this system legitimately supersede an existing record, and both are guarded by optimistic concurrency control (OCC) against the parent resource. In each case the request must carry an expected-version field naming the parent's `version` as the client last observed it; if the parent's current `version` has moved on, the create is rejected.

Creating a finance contract against a deal supersedes whatever ACTIVE finance contract the deal already had. The request must include `expected_deal_version`, carrying the client's last-observed `version` of the target Deal. If another writer has advanced the deal's `version` since the client read it — for example, because a finance contract was already created, bumping the deal's version and superseding the prior contract — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412, forcing the client to re-read before it supersedes again.

Placing a vehicle on a new floor-plan line supersedes the vehicle's prior ACTIVE line. The request must include `expected_vehicle_version`, carrying the client's last-observed `version` of the target Vehicle. If the vehicle's `version` has advanced since the client read it — for example, because another re-floor already created a line and bumped the vehicle's version — the create is rejected with `ERR_STALE_VERSION` and HTTP status 412.

Apart from these two create-with-supersede endpoints, no endpoint takes an expected-version field, and the deal-fund operation's `expected_vehicle_version` (described in §3) is a distinct precondition guarding the vehicle being sold, not a generic OCC field.

## 3. Business Logic & Workflows

### 3.1. Building Inventory: Vehicles, Floor-Plan Lines, and Curtailments

Inventory begins with the vehicle. An `InventoryClerk` records a vehicle by supplying its `vin`, its `condition` (either `NEW` or `USED`), its `make`, `model`, and `model_year`, its `msrp_cents` (the manufacturer suggested retail price, relevant for new cars), and its `list_price_cents` (the dealer's asking price, which also serves as the collateral value for loan-to-value tests). A `vin` must be exactly 17 characters of uppercase alphanumerics excluding the letters I, O, and Q; a malformed VIN is an `ERR_INVALID_REQUEST`, and a VIN that already exists in inventory is rejected with `ERR_VIN_DUPLICATE`. A new vehicle is born in status `AVAILABLE`. Over its life a vehicle moves through `AVAILABLE`, `ON_DEAL`, `SOLD`, and `RECON`; the transitions are driven almost entirely by deal activity and trade acceptance, described later. Two further fields on a vehicle are system-maintained back-links: `acquired_from_trade_in_id`, which on a used car points back to the trade-in it came in on, and `active_floor_plan_line_id`, the `id` of the vehicle's current ACTIVE floor-plan line (the most recent ACTIVE line by `created_at`), or null when none is active.

Most cars on the lot are financed wholesale through a floor-plan credit line. When an `InventoryClerk` floors a vehicle, the system creates a floor-plan line capturing the `vehicle_id`, the `lender_name`, the `principal_cents` (the original floored principal, which must be greater than zero), the `annual_rate_bps` (the floor-plan annual rate in basis points), and `floored_on` (the date flooring began, which is the aging baseline). The new line opens in status `ACTIVE` with `principal_outstanding_cents` equal to `principal_cents` and `curtailments_applied` at zero. Flooring a vehicle that already has an ACTIVE line is a re-floor: the prior ACTIVE line transitions `ACTIVE → SUPERSEDED` with no principal change, the newly created line becomes the vehicle's active line, the vehicle's `active_floor_plan_line_id` is repointed to the new line, and the vehicle's `version` increments by one. Because re-flooring supersedes the prior line, this create requires `expected_vehicle_version` to match the vehicle's current `version`, as described in §2.9. A floor-plan line's lifecycle states are `ACTIVE`, `PAID_OFF`, `SUPERSEDED`, and `REINSTATED`; the paid-off and reinstated transitions are cascade-driven by deal funding and unwind and are covered in §3.6 and §3.7.

A floor-plan line accrues a curtailment obligation as it ages. An `InventoryClerk` records a curtailment by supplying an `as_of_date`; the system computes the line's age as the number of whole days from `floored_on` to that date. A curtailment is due only when the age in days is at least 90 days — the comparison is inclusive of exactly 90. If the line is younger than 90 days, the request is rejected with `ERR_CURTAILMENT_NOT_DUE`. When a curtailment is due, the reduction is ten percent of the original `principal_cents`, rounded half up to whole cents; that reduction is subtracted from `principal_outstanding_cents`, `curtailments_applied` increases by one, and the line's `version` increments by one. In other words, `principal_outstanding_cents` always equals the original `principal_cents` less the sum of all curtailment principal reductions recorded against the line.

The dealership can also quote what it would cost to pay a floor-plan line off as of some date. A payoff quote takes an `as_of_date` and returns a small report object containing the `floor_plan_line_id`, the `days_accrued`, the `interest_cents`, and the `payoff_cents`; it changes nothing on the line itself. The payoff is the current `principal_outstanding_cents` plus accrued interest, where the interest is the outstanding principal multiplied by the annual rate (the `annual_rate_bps` divided by ten thousand), divided by a 360-day year, multiplied by the number of days accrued, with the resulting interest rounded half up to whole cents. This quote serves two timing modes that differ only in which date supplies the day count. The ESTIMATE mode is forward-looking: at desk time the day count runs from `floored_on` forward to a projected funding date supplied at quote time, taking the whole number of days rounded up. The ACTUAL mode is chronological: at funding the day count is the actual elapsed whole days from `floored_on` through the real funding date. The same line quoted as of two different dates yields two different payoffs because the day count differs.

When a vehicle taken in on trade has been brought into inventory, it lands in status `RECON` for reconditioning. Once the work is done, an `InventoryClerk` marks reconditioning complete, transitioning the vehicle `RECON → AVAILABLE` and incrementing the vehicle's `version` by one, after which the car can be listed and sold like any other.

### 3.2. Customers, Configuration Catalogs, and Test Drives

A `SalesManager` enrolls a buyer as a customer, recording the `full_name`, the `email` (which is unique), the `monthly_income_cents` (gross monthly income, used for payment-to-income gating), the `credit_tier` (one of `TIER_A`, `TIER_B`, `TIER_C`, or `TIER_D`, which selects the lender buy rate), and `drivers_license_valid`, a boolean that gates test driving and defaults to false.

The F&I office maintains three configuration catalogs. A `FinanceManager` defines a lender program — a rate sheet keyed to a credit tier — with a `lender_name`, the `tier` it serves, the `buy_rate_bps` (the lender's wholesale rate), the `max_markup_bps` (the largest dealer markup permitted over buy rate), the `max_ltv_bps` (the maximum loan-to-value in basis points, e.g. 12500 for 125%), the `max_pti_bps` (the maximum payment-to-income in basis points), the `max_term_months`, and an `active` flag (default true) indicating whether the program is currently offered. A `FinanceManager` also defines the F&I product catalog: each finance product has a `code` (such as VSC or GAP, which is unique), a display `name`, a dealer `cost_cents`, a `max_retail_cents` ceiling on its sellable price, and a `taxable` flag (default false) controlling whether its price joins the taxable base. Finally, an OEM incentive program — which either a `SalesManager` or a `FinanceManager` may create — captures a unique `program_code`, the `rebate_cents` cash rebate, the `eligible_condition` it applies to (`NEW`, `USED`, or `ANY`), an optional `eligible_make` (when set, only vehicles of that make qualify; null means any make), an optional `min_model_year` (when set, the vehicle's model year must reach it), a `stackable_with_finance` flag (default true) governing whether the rebate may combine with a financed deal, and an `active` flag (default true).

Before a sale, a prospect typically test-drives a car. A test drive — bookable by a `SalesManager` or by the `Customer` themselves — records the `vehicle_id`, the `customer_id`, a `start_at` (inclusive start time) and an `end_at` (exclusive end time), and opens in status `SCHEDULED`. Booking is gated on safety and scheduling. First, the customer must hold a verified license: if the referenced customer's `drivers_license_valid` is not true, the booking is rejected with `ERR_LICENSE_INVALID`. Second, the requested interval must not collide with another SCHEDULED test drive on the same vehicle, where the collision check includes a turnaround buffer applied after each drive so that back-to-back drives are spaced apart; an overlap (buffer included) is rejected with `ERR_TESTDRIVE_OVERLAP`. A `SalesManager` may complete a scheduled drive, transitioning it `SCHEDULED → COMPLETED` and bumping its `version`. Either a `SalesManager` or the owning `Customer` may cancel a scheduled drive, transitioning it `SCHEDULED → CANCELLED`, which frees the vehicle's interval for re-booking and bumps the drive's `version`. A completion or cancellation attempted on a drive that is not `SCHEDULED` is an `ERR_INVALID_STATE`.

### 3.3. Opening and Desking a Deal

A deal is the central artifact of a sale. A `SalesManager` opens one by referencing the `vehicle_id` being sold and the `customer_id` buying, choosing a `deal_type` (`FINANCE` or `CASH`, default `FINANCE`), and supplying the pricing inputs: the `sale_price_cents`, the optional `accessories_cents` (taxable dealer-installed accessories, default 0), the optional `doc_fee_cents` (a taxable documentation fee, default 0), the optional `title_fee_cents` and `registration_fee_cents` (non-taxable government fees, each default 0), the `tax_rate_bps` (sales-tax rate in basis points), and the optional `cash_down_cents` (default 0). A deal opens in status `DRAFT`, with version 1 and all computed totals defaulting to zero. Over its life a deal walks the states `DRAFT`, `DESKING`, `SUBMITTED_TO_LENDER`, `APPROVED`, `CONTRACTED`, and `FUNDED`, with terminal outcomes `FUNDED`, `UNWOUND`, and `DEAD`.

Desking is where the numbers are worked. When a `SalesManager` desks a `DRAFT` deal, it advances `DRAFT → DESKING`. The act of desking also reserves the vehicle: the referenced vehicle must be `AVAILABLE` (or already `ON_DEAL` reserved to this very deal), otherwise the desk is rejected with `ERR_VEHICLE_NOT_AVAILABLE`; on a first desk an `AVAILABLE` vehicle transitions `AVAILABLE → ON_DEAL` and the vehicle's `version` increments by one. Each desk recomputes the full quote: the deal's taxes, amount financed, front and back gross, and the provisional estimated monthly payment (all of these calculations are detailed in §3.4). Re-desking is a legitimate idempotent self-loop: desking a deal already in `DESKING` advances `DESKING → DESKING`, re-quoting from the current inputs, products, trade, and incentive, requiring only that the vehicle is still `ON_DEAL` for this deal, and bumping the deal's `version`. Re-desking can also reopen a stalled negotiation: a deal in `APPROVED` may be desked back to `DESKING`, which invalidates the approval (the deal's `approved_lender_program_id` is cleared to null) and supersedes any ACTIVE finance contract on the deal (that contract transitions `ACTIVE → SUPERSEDED`), then re-quotes; again the vehicle must still be `ON_DEAL` for this deal. Every desk increments the deal's `version` by one.

Two negotiation tools attach to a deal during desking. A `SalesManager` or `FinanceManager` may apply a single OEM incentive to the deal by naming the `oem_incentive_id`. The incentive is checked for eligibility against the deal's vehicle and deal type (the eligibility rule is in §3.4); if it does not qualify, the request is rejected with `ERR_INCENTIVE_NOT_ELIGIBLE`. On success the deal's `applied_incentive_id` is set and its `rebate_cents` becomes the incentive's rebate amount, the amount financed is recomputed, and the deal's `version` increments. A trade-in may also be attached or replaced on a deal by a `SalesManager` or `InventoryClerk`, who supplies the trade's `vin`, the `acv_cents` (appraised actual cash value), the `allowance_cents` (the allowance shown to the customer, which drives the tax credit), and the `payoff_cents` (the lien payoff still owed). Attaching a trade releases any prior non-released trade on the deal — that earlier trade transitions to `RELEASED` — and the new trade opens in status `APPRAISED` with `gross_equity_cents` computed as `allowance_cents` minus `payoff_cents` (which may be negative). Attaching a trade recomputes the deal's `trade_allowance_cents`, `trade_equity_cents`, amount financed, and taxes, and bumps the deal's `version`. A deal may be killed from `DRAFT` (transitioning `DRAFT → DEAD` with only a version bump) or from `DESKING` (transitioning `DESKING → DEAD`); killing from `DESKING` releases the reservation, transitioning the vehicle `ON_DEAL → AVAILABLE`, and releases any attached `APPRAISED` trade to `RELEASED`.

F&I products are attached to the deal by a `FinanceManager`. Attaching a product names the `finance_product_id` from the catalog and a `sold_price_cents`; the product must exist (or the create is `ERR_FK_NOT_FOUND`) and the `sold_price_cents` must not exceed that product's `max_retail_cents`, otherwise the attach is rejected with `ERR_PRODUCT_PRICE_EXCEEDS_MAX`. A successful attach creates a product line in status `ACTIVE`, snapshots the catalog's cost into `product_cost_cents`, recomputes the deal's amount financed and back-end gross, and increments the deal's `version`. During a rehash a `FinanceManager` may void a product line, transitioning it `ACTIVE → VOID`; voiding likewise recomputes the deal's amount financed and back-end gross and bumps the deal's `version`. Throughout, the deal's `fi_products_total_cents` is the sum of `sold_price_cents` across the deal's product lines that are not VOID.

Deal-jacket documents are uploaded against the deal by a `SalesManager`, `FinanceManager`, or `TitleClerk`. Each document records the `deal_id`, a `doc_type` (one of `CREDIT_APP`, `PROOF_OF_INCOME`, `INSURANCE`, `BILL_OF_SALE`, or `ODOMETER`), and an opaque storage `uri`. Documents are append-only stipulations; the presence of particular document types gates later transitions, as the workflow below describes.

### 3.4. Deal Mathematics: Taxes, Amount Financed, Gross, Payment, and Reserve

Every desk re-runs the deal's core calculations. They are specified here once; the desking, contracting, and funding narratives reference them by name.

**Sales tax.** The taxable sale base is the `sale_price_cents` reduced by the deal's `trade_allowance_cents` (the allowance is a tax credit), floored at zero so a large trade allowance never produces a negative base. The effective tax rate is `tax_rate_bps` divided by ten thousand. Three taxable lines are taxed: the taxable sale base, the `accessories_cents`, and the `doc_fee_cents`. Each of these three lines is multiplied by the rate and rounded half up to a whole cent **independently**, and only then are the three rounded line taxes added together to form `total_tax_cents`. This per-line-then-sum order is authoritative and must not be replaced by summing the bases and rounding once. The government `title_fee_cents` and `registration_fee_cents` are not taxable and do not enter this computation.

**Amount financed.** The gross amount due is the sum of `sale_price_cents`, `accessories_cents`, `doc_fee_cents`, `title_fee_cents`, `registration_fee_cents`, the `total_tax_cents` just computed, and `fi_products_total_cents` (the sum of `sold_price_cents` over ACTIVE product lines on the deal). From that gross, three reductions are subtracted: the deal's `rebate_cents`, its `trade_equity_cents`, and its `cash_down_cents`. The result is `amount_financed_cents`. Because `trade_equity_cents` is the trade allowance less the trade payoff, a trade with negative equity (payoff exceeding allowance) is itself negative and therefore increases the amount financed rather than reducing it.

**Front and back gross.** The dealership's gross is reported two ways from disjoint inputs. The front-end gross (`front_gross_cents`, the vehicle department's figure) is the `sale_price_cents` plus `accessories_cents` minus the vehicle's cost basis, where the cost basis is the `principal_cents` of the vehicle's active floor-plan line if one exists, and otherwise the vehicle's `list_price_cents`. The back-end gross (`back_gross_cents`, the F&I department's figure) is the product markup plus the finance reserve: the product markup is the sum, over ACTIVE product lines, of each line's `sold_price_cents` minus its snapshotted `product_cost_cents`, and the finance reserve is zero until a finance contract exists on the deal and otherwise the contract's `finance_reserve_cents`.

**Monthly payment.** The monthly payment uses standard fixed-rate amortization with monthly compounding. Let the monthly rate be the annual rate (in basis points, divided by ten thousand) divided by twelve, and let the principal be `amount_financed_cents` expressed in dollars (divided by 100). When the monthly rate is zero, the monthly payment in dollars is the principal divided by the term in months; otherwise it is the principal multiplied by the monthly rate, divided by the quantity one minus the term-negative power of one plus the monthly rate. The dollar payment is converted to cents and rounded half up to a whole cent. This calculation has two variants that share the same amount financed but differ in rate and term. The ESTIMATE variant runs at every desk before any lender approval: it uses a provisional desking sell rate of 699 basis points (6.99%) and a provisional term of 72 months, and writes the result into the deal's `estimated_payment_cents`. The FINAL variant runs when a finance contract is created after lender approval: it uses the contract's sell rate (the lender program's `buy_rate_bps` plus the contract's `markup_bps`) and the contract's `term_months`, and writes the result into the contract's `monthly_payment_cents`.

**Finance reserve.** When a finance contract is created, the dealer's rate-spread participation — the finance reserve — is computed in a strictly pinned three-step order. First, the effective markup is the smaller of the contract's `markup_bps` and the lender program's `max_markup_bps`. Second, the reserve rate is chosen by tier: if the effective markup is at most 150 basis points, the reserve rate is one percent (0.01); if it is greater than 150 basis points, the reserve rate is two percent (0.02). Third, `finance_reserve_cents` is the snapshotted amount financed multiplied by the chosen reserve rate, rounded half up to whole cents.

**Incentive eligibility.** An OEM incentive is eligible for a deal only when all of the following hold: the incentive's `active` flag is true; the incentive's `eligible_condition` equals the vehicle's `condition` or the incentive's `eligible_condition` is `ANY`; the incentive's `eligible_make` is null or equals the vehicle's `make`; the incentive's `min_model_year` is null or the vehicle's `model_year` is at least that value; and either the deal's `deal_type` is not `FINANCE` or the incentive's `stackable_with_finance` flag is true. If the requested incentive fails any of these, it is not eligible and the apply is rejected with `ERR_INCENTIVE_NOT_ELIGIBLE`. When it passes, the deal's `applied_incentive_id` is set to the incentive's id and the deal's `rebate_cents` is set to the incentive's `rebate_cents`.

### 3.5. Lender Submission, Approval, and Contracting

Once a finance deal is desked, it goes to the lender. A `SalesManager` submits a desked deal to the lender, advancing `DESKING → SUBMITTED_TO_LENDER`. Submission is gated twice: the deal's `deal_type` must be `FINANCE`, or the request is rejected with `ERR_DEAL_TYPE_NOT_FINANCE`; and a deal-jacket document of type `CREDIT_APP` must already exist for the deal, or it is rejected with `ERR_CREDIT_APP_MISSING`. A successful submission bumps the deal's `version`.

A `FinanceManager` records the lender's decision, supplying a `decision` of either approve or decline. On an approval, the deal advances `SUBMITTED_TO_LENDER → APPROVED`; the request names a `lender_program_id`, and the referenced lender program must have `active` equal to true and a `tier` matching the customer's `credit_tier`, or the decision is rejected with `ERR_LENDER_TIER_MISMATCH`. On a successful approval the deal's `approved_lender_program_id` is set to the named program and the deal's `version` increments. On a decline, the deal reverts `SUBMITTED_TO_LENDER → DESKING`, the deal's `approved_lender_program_id` is cleared to null, and the deal's `version` increments — a decline sends the deal back to the desk for a rehash.

A `FinanceManager` builds the actual finance contract on an approved deal. The contract names the `lender_program_id` used (which must exist, or `ERR_FK_NOT_FOUND`), the dealer `markup_bps` over buy rate, and the `term_months`; the markup must not exceed the lender program's `max_markup_bps` and the term must not exceed its `max_term_months`, or the create is rejected with `ERR_MARKUP_EXCEEDS_MAX`. Creating a finance contract snapshots the deal's current amount financed into `amount_financed_snapshot_cents`, computes `sell_rate_bps` as the program's buy rate plus the contract markup, computes the FINAL monthly payment and the finance reserve as specified in §3.4, and opens the contract in status `ACTIVE`. Because a new contract supersedes the prior one during a rehash, any earlier ACTIVE contract on the deal transitions `ACTIVE → SUPERSEDED`, the deal's back-end gross is recomputed to fold in the new finance reserve, and the deal's `version` increments. This create is OCC-guarded: it must carry `expected_deal_version` matching the deal's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412), as detailed in §2.9.

Contracting moves an approved deal toward the sale. A `FinanceManager` contracts the deal, advancing `APPROVED → CONTRACTED`. Three preconditions guard contracting: the vehicle must be `ON_DEAL` for this deal, or `ERR_VEHICLE_NOT_AVAILABLE`; an ACTIVE finance contract must exist on the deal, or `ERR_NO_ACTIVE_CONTRACT`; and a deal-jacket document of type `INSURANCE` must exist for the deal, or `ERR_STIP_MISSING`. Contracting also fires the trade-acceptance cascade. If a trade-in is attached in status `APPRAISED`, it transitions `APPRAISED → ACCEPTED`; and as a direct consequence of that acceptance, the system creates a `USED` vehicle in status `RECON` carrying the trade's `vin`, sets the trade's `acquired_vehicle_id` to the new vehicle, and sets the new vehicle's `acquired_from_trade_in_id` back to the trade. That reconditioned vehicle is independently listable. Contracting increments the deal's `version`.

### 3.6. Funding the Deal and the Sale Cascade

Funding is the moment of sale, performed by a `FinanceManager` on a `CONTRACTED` deal, advancing `CONTRACTED → FUNDED`. The fund request carries `expected_vehicle_version`, the client's last-observed `version` of the vehicle being sold; if it does not match the vehicle's current `version`, funding is rejected with `ERR_STALE_VERSION` (HTTP 412). Funding then enforces several gates in turn. The vehicle must still be `ON_DEAL` for this deal, or `ERR_VEHICLE_NOT_AVAILABLE`. The loan-to-value cap must hold: the deal's `amount_financed_cents` must not exceed the lender program's `max_ltv_bps` divided by ten thousand, multiplied by the vehicle's `list_price_cents` — at most, never beyond — or funding is rejected with `ERR_LTV_EXCEEDED`. The payment-to-income cap must hold: the finance contract's `monthly_payment_cents` must not exceed the lender program's `max_pti_bps` divided by ten thousand, multiplied by the customer's `monthly_income_cents`, or funding is rejected with `ERR_PTI_EXCEEDED`.

When the gates pass, funding fires a three-link cascade. First, the vehicle is sold: it transitions `ON_DEAL → SOLD` and its `version` increments. Second, as a consequence of the sale, the vehicle's ACTIVE floor-plan line (if any) is paid off: it transitions `ACTIVE → PAID_OFF` and its `principal_outstanding_cents` is set to zero. Third, as a consequence of that payoff, the system auto-creates a title registration for this deal in status `PENDING`. Funding increments both the vehicle's `version` and the deal's `version`.

A funded deal can be unwound when a sale collapses, performed by a `FinanceManager`, advancing `FUNDED → UNWOUND`. Unwind is blocked if any title registration for the deal has reached `ACCEPTED`: in that case the request is rejected with `ERR_TITLE_ALREADY_ACCEPTED`, because the state has already perfected the title. When unwind is permitted, it runs the compensation chain that reverses the fund cascade so the dealership's global floor-plan principal outstanding returns to its pre-fund total. The vehicle is restored `SOLD → AVAILABLE`. As a consequence, the floor-plan line that this funding paid off is reinstated: it transitions `PAID_OFF → REINSTATED` and its `principal_outstanding_cents` is restored to the original `principal_cents` less the sum of any curtailment reductions previously recorded against it. Any ACTIVE finance contract on the deal is cancelled (`ACTIVE → CANCELLED`). Any `ACCEPTED` trade-in on the deal is released (`ACCEPTED → RELEASED`) and the used vehicle it had spawned is unlinked. A `PENDING` title registration for the deal is retained as a record but is not submitted to the DMV. Unwind increments both the vehicle's `version` and the deal's `version`.

### 3.7. DMV Title and Registration

The title clerk closes the deal with the state. A title registration is auto-created in status `PENDING` when its deal funds, referencing the `deal_id`. Before submitting it, a `TitleClerk` may set its `owner_name` and `plate_type` (either `NEW_PLATE` or `TRANSFER`) while it is still pending; this patch bumps the registration's `version`. A title registration carries a system-managed `rejection_reason` (set when the DMV rejects), a `resubmit_count` (the number of times it has been resubmitted after a rejection, starting at zero), and a `status` that walks `PENDING`, `SUBMITTED`, `ACCEPTED`, and `REJECTED`, with `ACCEPTED` terminal.

A `TitleClerk` submits the registration to the DMV. Submission is allowed from `PENDING` (advancing `PENDING → SUBMITTED`) and again from `REJECTED` as a resubmit (advancing `REJECTED → SUBMITTED`). Both submissions are gated identically: the referenced deal must be in `FUNDED`, or the submission is rejected with `ERR_DEAL_NOT_FUNDED`; and a deal-jacket document of type `ODOMETER` must exist for the deal, or it is rejected with `ERR_STIP_MISSING`. On a first submission from `PENDING`, only the `version` increments. On a resubmission from `REJECTED`, the `resubmit_count` increases by one, the `rejection_reason` is cleared, and the `version` increments — this branching revert reopens the DMV submission after a rejection.

A `TitleClerk` records the DMV's `result` on a submitted registration, supplying either accept or reject. An acceptance advances `SUBMITTED → ACCEPTED` and bumps the `version`. A rejection advances `SUBMITTED → REJECTED`: the request must carry a `rejection_reason`, or it is rejected with `ERR_REJECTION_REASON_REQUIRED`; on success the registration's `rejection_reason` is set from the request and its `version` increments. A result recorded on a registration that is not `SUBMITTED` is an `ERR_INVALID_STATE`.

### 3.8. Service and Parts Repair Orders

The service lane runs independently but links back to inventory and deals. A `ServiceAdvisor` opens a repair order naming the `vehicle_id` in service, an optional `deal_id` (linking we-owe or reconditioning work to a deal; null for ordinary retail service), the `ro_type` (`RECON`, `WE_OWE`, or `RETAIL`), the `bay` (`BAY_1`, `BAY_2`, or `BAY_3`), and a `scheduled_start_at` and `scheduled_end_at` for the bay slot, plus optional `parts_cents` and `labor_cents` (each default 0). A repair order opens in status `OPEN`, and its `total_cents` is the sum of `parts_cents` and `labor_cents`. The bay slot must not overlap another OPEN repair order in the same bay; the overlap test treats the slot as a closed interval with no buffer, and a collision is rejected with `ERR_BAY_OVERLAP`. A `ServiceAdvisor` may close an open order, advancing `OPEN → CLOSED`, which finalizes `total_cents` as `parts_cents` plus `labor_cents` and bumps the `version`; or cancel an open order, advancing `OPEN → CANCELLED`, which frees the bay interval and bumps the `version`. Closing or cancelling an order that is not `OPEN` is an `ERR_INVALID_STATE`.

### 3.9. Deterministic Time Control

Because curtailment aging, payoff accrual, and test-drive and bay scheduling all depend on the current moment, the system exposes an administrative time-control capability. Any of the operator roles may set the server's current UTC instant by supplying a `to_iso8601` timestamp; the capability replies with the new `now`. This exists so date-dependent math (such as a floor-plan line's age relative to its `floored_on`) can be exercised deterministically.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new distinct resource to a collection return `201 Created`. Operations that read a resource, drive a state transition on an existing resource, or otherwise modify an existing resource return `200 OK`. Request bodies, response bodies, and side effects for each endpoint are reconstructed from the workflow narratives in §3; the table below is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/vehicles` | Create an inventory vehicle (new or used) | InventoryClerk |
| GET | `/vehicles/{id}` | Get a vehicle | InventoryClerk, SalesManager, FinanceManager, ServiceAdvisor, TitleClerk |
| GET | `/vehicles` | List vehicles; filter by status or trade origin | InventoryClerk, SalesManager, FinanceManager, ServiceAdvisor, TitleClerk |
| POST | `/vehicles/{id}/recondition-complete` | Mark a RECON vehicle ready for sale | InventoryClerk |
| POST | `/vehicles/{id}/floor-plan-lines` | Place the vehicle on floor-plan financing (supersedes prior active line) | InventoryClerk |
| GET | `/vehicles/{id}/floor-plan-lines` | List floor-plan lines for a vehicle | InventoryClerk, FinanceManager |
| GET | `/floor-plan-lines/{id}` | Get a floor-plan line | InventoryClerk, FinanceManager |
| POST | `/floor-plan-lines/{id}/curtailments` | Record a curtailment principal reduction if aging threshold reached | InventoryClerk |
| POST | `/floor-plan-lines/{id}/payoff-quote` | Compute a floor-plan payoff quote as of a date | InventoryClerk, FinanceManager |
| POST | `/customers` | Create a customer | SalesManager |
| GET | `/customers/{id}` | Get a customer | SalesManager, FinanceManager, Customer |
| POST | `/lender-programs` | Create a lender program rate sheet | FinanceManager |
| GET | `/lender-programs/{id}` | Get a lender program | FinanceManager, SalesManager |
| POST | `/finance-products` | Create an F&I finance-product catalog entry | FinanceManager |
| GET | `/finance-products/{id}` | Get a finance product | FinanceManager, SalesManager |
| POST | `/oem-incentives` | Create an OEM incentive program | SalesManager, FinanceManager |
| GET | `/oem-incentives/{id}` | Get an OEM incentive | SalesManager, FinanceManager |
| POST | `/deals` | Create a deal in DRAFT | SalesManager |
| GET | `/deals/{id}` | Get a deal (jacket header with computed gross, taxes, amount financed) | SalesManager, FinanceManager, TitleClerk |
| GET | `/deals` | List deals; filter by vehicle, customer, or status | SalesManager, FinanceManager, TitleClerk |
| POST | `/deals/{id}/desk` | Desk / re-desk a deal; recomputes the quote | SalesManager |
| POST | `/deals/{id}/apply-incentive` | Apply a single OEM incentive/rebate to the deal | SalesManager, FinanceManager |
| POST | `/deals/{id}/submit-to-lender` | Submit a desked finance deal to the lender | SalesManager |
| POST | `/deals/{id}/lender-decision` | Record lender approve or decline | FinanceManager |
| POST | `/deals/{id}/contract` | Move an approved deal to CONTRACTED (trade-acceptance cascade) | FinanceManager |
| POST | `/deals/{id}/fund` | Fund a contracted deal (LTV/PTI gated; cascades sale, payoff, title) | FinanceManager |
| POST | `/deals/{id}/unwind` | Unwind a funded deal (compensation cascade) | FinanceManager |
| POST | `/deals/{id}/kill` | Kill a deal from DRAFT or DESKING | SalesManager |
| POST | `/deals/{id}/products` | Attach an F&I product to a deal | FinanceManager |
| GET | `/deals/{id}/products` | List deal products for a deal | FinanceManager, SalesManager |
| DELETE | `/deals/{id}/products/{deal_product_id}` | Void an F&I product on a deal during rehash | FinanceManager |
| POST | `/deals/{id}/trade-ins` | Attach (or replace) a trade-in appraisal on a deal | SalesManager, InventoryClerk |
| GET | `/deals/{id}/trade-ins` | List trade-ins for a deal | SalesManager, InventoryClerk, FinanceManager |
| GET | `/trade-ins/{id}` | Get a trade-in | SalesManager, InventoryClerk, FinanceManager |
| POST | `/deals/{id}/finance-contracts` | Create a finance contract on an approved deal (supersedes prior; OCC on deal) | FinanceManager |
| GET | `/deals/{id}/finance-contracts` | List finance contracts for a deal | FinanceManager, SalesManager |
| GET | `/finance-contracts/{id}` | Get a finance contract | FinanceManager, SalesManager |
| POST | `/deals/{id}/documents` | Upload a deal-jacket document/stipulation | SalesManager, FinanceManager, TitleClerk |
| GET | `/deals/{id}/documents` | List deal-jacket documents | SalesManager, FinanceManager, TitleClerk |
| POST | `/test-drives` | Book a test drive (license + interval-overlap + buffer checks) | SalesManager, Customer |
| GET | `/test-drives/{id}` | Get a test drive | SalesManager, Customer |
| GET | `/test-drives` | List test drives; filter by vehicle or customer | SalesManager, Customer |
| POST | `/test-drives/{id}/complete` | Complete a test drive | SalesManager |
| POST | `/test-drives/{id}/cancel` | Cancel a test drive (frees the interval) | SalesManager, Customer |
| POST | `/repair-orders` | Open a repair order (bay slot overlap checked) | ServiceAdvisor |
| GET | `/repair-orders/{id}` | Get a repair order | ServiceAdvisor, FinanceManager, SalesManager |
| GET | `/repair-orders` | List repair orders; filter by vehicle, deal, or bay | ServiceAdvisor, FinanceManager, SalesManager |
| POST | `/repair-orders/{id}/close` | Close a repair order | ServiceAdvisor |
| POST | `/repair-orders/{id}/cancel` | Cancel a repair order (frees the bay) | ServiceAdvisor |
| GET | `/title-registrations/{id}` | Get a title registration | TitleClerk, FinanceManager |
| GET | `/title-registrations` | List title registrations; filter by deal | TitleClerk, FinanceManager |
| PATCH | `/title-registrations/{id}` | Set owner/plate details on a pending title registration | TitleClerk |
| POST | `/title-registrations/{id}/submit` | Submit title/registration to the DMV | TitleClerk |
| POST | `/title-registrations/{id}/dmv-result` | Record DMV result (accept or reject) | TitleClerk |
| POST | `/_clock/set_current_utc` | Set the server's current UTC time (deterministic date math) | InventoryClerk, FinanceManager, SalesManager, ServiceAdvisor, TitleClerk |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_VIN_DUPLICATE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VEHICLE_NOT_AVAILABLE` | 409 Conflict |
| `ERR_DEAL_NOT_FUNDED` | 409 Conflict |
| `ERR_TESTDRIVE_OVERLAP` | 409 Conflict |
| `ERR_BAY_OVERLAP` | 409 Conflict |
| `ERR_LICENSE_INVALID` | 409 Conflict |
| `ERR_PRODUCT_PRICE_EXCEEDS_MAX` | 409 Conflict |
| `ERR_MARKUP_EXCEEDS_MAX` | 409 Conflict |
| `ERR_LTV_EXCEEDED` | 409 Conflict |
| `ERR_PTI_EXCEEDED` | 409 Conflict |
| `ERR_LENDER_TIER_MISMATCH` | 409 Conflict |
| `ERR_DEAL_TYPE_NOT_FINANCE` | 409 Conflict |
| `ERR_CREDIT_APP_MISSING` | 409 Conflict |
| `ERR_STIP_MISSING` | 409 Conflict |
| `ERR_NO_ACTIVE_CONTRACT` | 409 Conflict |
| `ERR_INCENTIVE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_CURTAILMENT_NOT_DUE` | 409 Conflict |
| `ERR_TITLE_ALREADY_ACCEPTED` | 409 Conflict |
| `ERR_REJECTION_REASON_REQUIRED` | 422 Unprocessable Entity |

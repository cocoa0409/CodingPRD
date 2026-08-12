# Piano Dealer & Institutional Instrument Sales API — Product Requirements Document

## 1. Introduction

A high-end piano dealership does far more than ring up retail sales. The showroom floor holds a mixture of new, used, and consigned instruments; a school district's fleet purchase travels through sealed-bid pricing, state-contract ceilings, and compliance sign-off; a sold concert grand sets off a chain of delivery crews, climate-controlled trucks, in-home installation, manufacturer warranty registration, and a multi-year tuning plan; and behind it all sit consignor ledgers, rent-to-own contracts, restoration referrals, and artist-series recitals that share the same rooms as the inventory. Each of these lines of business has its own economics and its own failure modes, and a single sloppy rule — a mis-priced bid tier, a double-booked technician, a consignor paid twice on a returned sale — is immediately visible in dollars.

This document specifies the API that runs that dealership end to end. All resources are mounted under `/piano-dealer`. The API covers instrument intake and consignment, trade-in appraisal with dealer evaluation, institutional bid preparation with segregation-of-duties compliance review, sales-order pricing with trade-in credits and delivery surcharges, payment collection and financing (including rent-to-own), delivery scheduling and installation, post-sale service plans and technician visits, warranty registration with the manufacturer, restoration-shop referrals, and showroom event management with artist settlement. A shared logical clock drives every time-dependent rule — offer expirations, return windows, warranty deadlines, missed-payment counting, and event settlement — so that behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The system recognizes nine roles. `PlatformAdmin` is a test-driving operator that controls the logical clock and nothing else. `StoreManager` is the dealer principal, owning inventory intake and lifecycle, consignor registration, trade-in evaluation, returns, warranty confirmation, restoration referrals, showroom events, and the staff rosters of crews and technicians. `SalesAssociate` is the retail salesperson, owning customer registration, order intake and amendment, payment posting, order cancellation, trade-in submission, warranty initiation, and event RSVPs. `InstitutionalBidOfficer` prepares, submits, revises, withdraws, and records outcomes on institutional bids. `ComplianceOfficer` reviews submitted bids and either approves them or returns them for revision, and is barred from approving a bid prepared under the same user identity. `ServiceCoordinator` schedules delivery crews and technicians and manages service plans and visits. `FinanceOfficer` owns the financing lifecycle from application through approval, payments, conversion, and default. `Customer` is the retail or institutional buyer with self-service rights on their own appraisals and visibility into their own orders, plans, and agreements. `Consignor` is an instrument consignor with read-only access to their own record and their consigned instruments.

Identity semantics differ by role. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is `Consignor`, `X-User-ID` is likewise the `id` of the acting `Consignor`; a consignor may read only their own record and their own consigned-instrument listing, and attempts against another consignor's identifiers are rejected with `ERR_UNAUTHORIZED_ROLE`. When `X-User-Role` is any of `PlatformAdmin`, `StoreManager`, `SalesAssociate`, `InstitutionalBidOfficer`, `ComplianceOfficer`, `ServiceCoordinator`, or `FinanceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `prepared_by_user_id` on a `BidPackage` at creation time, which later drives the segregation-of-duties check — but does not compare it to any entity's `id`.

Segregation of duties is enforced on bid approval: a `ComplianceOfficer` whose `X-User-ID` equals the bid's recorded `prepared_by_user_id` may not approve that bid, and the attempt is rejected with `ERR_SOD_SELF_APPROVAL` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter says how many items to skip and defaults to 0. Several list endpoints additionally accept domain filters — for example `customer_id`, `order_id`, `crew_id`, `plan_id`, `technician_id`, or `instrument_id` — which narrow the result set before pagination is applied.

Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every resource in this system — consignors, customers, instruments, trade-in appraisals, bid packages, sales orders, delivery crews, delivery jobs, technicians, service plans, service visits, financing agreements, warranty registrations, restoration referrals, and showroom events — carries the same four system-managed properties:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer beginning at 1 that increments by exactly one on every mutation, including mutations performed as side effects of another resource's workflow.

Because cascades and automatic reconciliations are themselves mutations, a resource whose state, derived fields, or ledger balances change as a consequence of another operation also refreshes its `updated_at` and increments its `version`.

### 2.5. The Dealer's Logical Clock

All time-dependent behavior in the system reads a single logical clock, never the wall clock. Before any call to set it, the logical clock reads exactly `2026-05-01T00:00:00Z`. A `PlatformAdmin` may advance the clock by supplying a `to_iso8601` instant through the admin-only clock capability, and the response reports the new `current_utc`. Every deadline in this document — the fourteen-day trade-in offer window, the sixty-day warranty registration window, the fourteen-day return window, the end-of-event settlement gate, missed-payment counting on financing agreements, and the age of a trade-in instrument (whose year is taken from the logical clock) — is evaluated against this logical clock.

Two expirations are lazy rather than scheduled. A trade-in offer flips to `EXPIRED` when an accept or counter is attempted after the offer window has closed. A registered warranty flips to `EXPIRED` on read when the logical clock has passed its `coverage_end`. Advancing the clock does not eagerly rewrite any record; the transition materializes on the next relevant access.

### 2.6. Monetary Precision and Rounding

All money is represented as integer cents. Fields named with the `_cents` suffix — prices, fees, credits, balances, payouts, principals, estimates — are integers, and every monetary calculation in this document produces integer cents. Where a calculation involves a multiplication or division that can yield a fractional cent, the result is rounded half-up to the nearest whole cent at the step the rule specifies; several rules pin a multi-step rounding order, and the pinned order is normative. Fractional rates and percentages (for example `tax_rate`, `commission_pct`, `split_pct`, `apr`, `market_adjustment_pct`, `tier_discount_pct`, `institution_multiplier`) are decimal fractions, so an eight percent tax rate arrives as 0.08. Date arithmetic for warranty coverage uses calendar months: adding a month advances the same day-of-month.

### 2.7. Optimistic Concurrency and Stale Versions

Two write operations in the system are legitimately superseding — each creates a new authoritative snapshot of a parent resource — and therefore require the client to prove it observed the parent's current version.

First, creating a new revision of a bid package requires the request to carry `expected_bid_version` holding the `version` of the `BidPackage` the client last read. If the package's current `version` has advanced beyond that value — because another writer revised or otherwise mutated the package in the meantime — the revision is rejected with `ERR_STALE_VERSION` (HTTP 412), since a new revision legitimately supersedes the prior one and a writer holding a stale view must be refused.

Second, amending a sales order requires the request to carry `expected_order_version` holding the `version` of the `SalesOrder` the client last read. If the order's current `version` has advanced since that read — each successful amendment legitimately supersedes the prior pricing snapshot — the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; optimistic concurrency applies to exactly these two operations.

### 2.8. The Order of Validation

When a request violates several rules at once, the rejection it receives is determined by a fixed priority order, evaluated as follows. First, authentication: the `X-User-ID` and `X-User-Role` headers must be present and the role must be a declared role, else `ERR_UNAUTHENTICATED`. Second, role authorization: the acting role must appear on the endpoint's authorized list, else `ERR_UNAUTHORIZED_ROLE`. Third, identity-level rules: segregation of duties on bid approval (`ERR_SOD_SELF_APPROVAL`) and self-service ownership for `Customer` and `Consignor` actors (`ERR_UNAUTHORIZED_ROLE`). Fourth, existence: every path identifier and every body foreign-key reference — instrument, customer, consignor, order, appraisal, bid, plan, agreement, warranty, referral, event, crew, technician, job, visit — must resolve to an existing record, validated left-to-right so the first missing identifier in the path is the one reported; any miss yields `ERR_NOT_FOUND` (HTTP 404).

Fifth, state preconditions: the target resource must be in a state that permits the operation, surfaced as the domain-specific state error for that workflow (`ERR_INSTRUMENT_NOT_AVAILABLE`, `ERR_ORDER_NOT_PAYABLE`, `ERR_APPRAISAL_NOT_OFFERED`, `ERR_BID_NOT_ACTIONABLE`, `ERR_PLAN_NOT_ACTIVE`, `ERR_DELIVERY_NOT_ACTIONABLE`, `ERR_EVENT_NOT_SETTLABLE`, `ERR_REFERRAL_NOT_ACTIONABLE`, or `ERR_AGREEMENT_NOT_CONVERTIBLE`, each HTTP 409). Sixth, physical safety: the climate-control requirement on delivery scheduling (`ERR_CLIMATE_REQUIREMENT_UNMET`, HTTP 422). Seventh, clock-driven windows: offer expiry (`ERR_APPRAISAL_EXPIRED`, 409), warranty registration windows (`ERR_WARRANTY_WINDOW_CLOSED`, 422), return windows (`ERR_RETURN_WINDOW_CLOSED`, 422), and event settlement timing (`ERR_EVENT_NOT_SETTLABLE`, 409). Eighth, uniqueness, overlap, and capacity: duplicate serials (`ERR_DUPLICATE_SERIAL`, 409), crew window conflicts (`ERR_CREW_WINDOW_CONFLICT`, 409), technician window and day-capacity conflicts (`ERR_TECHNICIAN_WINDOW_CONFLICT`, `ERR_TECHNICIAN_DAY_CAPACITY_REACHED`, 409), room conflicts (`ERR_ROOM_WINDOW_CONFLICT`, 409), event capacity (`ERR_EVENT_CAPACITY_EXCEEDED`, 409), and exhausted plans (`ERR_PLAN_EXHAUSTED`, 409). Ninth, referenced-object state: a referenced trade-in must be accepted and owned by the buyer (`ERR_TRADE_IN_NOT_ACCEPTED`, 422), a referenced bid must be awarded and owned by the buyer (`ERR_BID_NOT_ACTIONABLE`), and a warranty's instrument must appear in its order's items (`ERR_INVALID_REQUEST`, 400). Tenth and last, money rules: overpayment (`ERR_OVERPAYMENT`, 422), bid floor violations (`ERR_BID_BELOW_FLOOR`, 422), and credit-limit violations (`ERR_CREDIT_LIMIT_EXCEEDED`, 422). Malformed payloads, missing required fields, invalid enum values, inverted time windows, and principal mismatches are schema-level rejections under `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. Dual-Track Orders and Cascade Discipline

Every lifecycle resource except the sales order exposes its current machine position in a `status` field; the `SalesOrder` is the lone exception, carrying the dual pair described below instead.

A `SalesOrder` carries two independent status machines that advance in parallel. Its `payment_status` tracks money (`UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, `FINANCED_ACTIVE`, `COLLECTIONS`, `REFUNDED`), while its `fulfillment_status` tracks the physical instrument (`AWAITING_SCHEDULING`, `DELIVERY_SCHEDULED`, `OUT_FOR_DELIVERY`, `DELIVERED`, `INSTALLED`, `RETURNED`, `CANCELLED`). Many operations gate on one track and mutate the other — a delivery may only be scheduled once money has moved, and completing a return rewrites both tracks at once — so each workflow in §3 names the exact states it requires on each track.

State changes rarely stay confined to the entity that received the request. Posting the final payment or approving financing sells the order's instruments; completing a return voids warranties, moves instruments back to preparation, adjusts the customer's `risk_score`, and cancels any active financing; declaring a financing default repossesses delivered instruments and damages the customer's credit standing. Every such cascade is spelled out at its workflow in §3, and each cascaded mutation refreshes the affected resource's `updated_at` and increments its `version` per §2.4. The consignor payout ledger and the customer risk score obey strict reconciliation: a consignor's `outstanding_payout_cents` is increased by exactly the payout computed at the moment of sale and decreased by exactly the same amount if the sale is later unwound, and `risk_score` begins at 700, loses 25 points per warranty voided by a return and 150 points per financing default, and is clamped to the band from 300 to 850.

## 3. Business Logic & Workflows

### 3.1. Instrument Intake and the Consignment Ledger

The dealership's stock is a flat collection of instruments. A `StoreManager` intakes an instrument by providing its `serial_number`, `category` (one of `GRAND`, `UPRIGHT`, `DIGITAL`, or `HYBRID`), `manufacturer`, `model`, four-digit `year_built`, `condition_grade` (`EXCELLENT`, `GOOD`, `FAIR`, or `POOR`), and `acquisition_type` (`NEW`, `USED`, or `CONSIGNMENT`), together with the asking `list_price_cents` and a `floor_price_cents` floor below which the instrument may not be bid. Serial numbers are globally unique across all instruments; a duplicate submission is rejected with `ERR_DUPLICATE_SERIAL`. An instrument acquired as `CONSIGNMENT` must name its `consignor_id`; for `NEW` and `USED` stock the `consignor_id` stays null. Consignment instruments may also carry `recoverable_costs_cents` (defaulting to 0) — preparation and restoration costs the dealer recovers off the top before splitting proceeds. Every instrument begins life in `IN_PREP`.

Consignors are registered first: a `StoreManager` records the consignor's `full_name`, `email`, the dealer's `commission_pct` as a fraction (for example 0.20), the `split_mode` selecting the payout variant — `GROSS_SPLIT` computes commission on the full sale price while `NET_SPLIT` deducts recoverable costs before commission — and a `payout_method` of `CHECK`, `ACH`, or `WIRE`. The consignor's `outstanding_payout_cents` ledger starts at zero. A `StoreManager`, or the consignor acting under their own identity, may read the consignor record and list the instruments consigned under it.

Listing for sale moves an instrument from `IN_PREP` to `AVAILABLE`; only `IN_PREP` instruments are eligible (an instrument in `REPOSSESSION_HOLD` in particular is not eligible here), and an instrument in any other state is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`. The full instrument lifecycle also includes sales (`AVAILABLE` → `RESERVED` → `SOLD` → `DELIVERED`), returns (`DELIVERED` → `IN_PREP`), restoration (`AVAILABLE` → `RESTORATION_HOLD` → `IN_PREP`), repossession (`DELIVERED` → `REPOSSESSION_HOLD` → `AVAILABLE`), and consignment wind-down (`AVAILABLE` → `RETURNED_TO_CONSIGNOR`, the terminal state). Returning stock to its owner is permitted only for `CONSIGNMENT` instruments currently `AVAILABLE`; a non-consignment instrument is rejected with `ERR_INVALID_REQUEST`, and a consigned instrument not currently `AVAILABLE` is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`.

The consignment ledger moves at the moment a consigned instrument is sold. When an order line's instrument transitions from `RESERVED` to `SOLD` — whether by full payment or by financing approval — the system computes the consignor's payout from the order line's rounded sale total. Under `GROSS_SPLIT` the payout is that sale total multiplied by one minus the `commission_pct`, rounded half-up to whole cents. Under `NET_SPLIT` the instrument's `recoverable_costs_cents` is subtracted from the sale total first, and the remainder is multiplied by one minus the `commission_pct`, rounded half-up — a strictly lower payout for an identical sale price. The payout is added to the consignor's `outstanding_payout_cents`. If the underlying sale is later completed as a return, the same payout is subtracted again as a compensating reversal, so the ledger returns exactly to its pre-sale balance.

### 3.2. Trade-In Appraisals and the Offer Window

A trade-in begins as a customer-reported submission. A `SalesAssociate` records the `customer_id`, the instrument's `category`, `manufacturer`, `model`, `year_built`, and the customer-reported `condition_grade`. At creation the system computes a desktop estimate and stores it as `provisional_value_cents`. The estimate works from the instrument's age — the calendar year of the current logical clock minus the `year_built` — and from category base values: 2,800,000 cents for a `GRAND`, 900,000 for an `UPRIGHT`, 250,000 for a `DIGITAL`, and 600,000 for a `HYBRID`. An age factor of one minus three hundredths per year of age is applied, but it is never allowed to fall below 0.40 no matter how old the instrument is. The provisional value is the category base, multiplied by the age factor, multiplied by one minus a wear allowance — 0 percent for `EXCELLENT`, 5 percent for `GOOD`, 15 percent for `FAIR`, and 30 percent for `POOR` — rounded half-up to whole cents. The new appraisal sits in `SUBMITTED`.

The dealer's in-shop evaluation is performed by a `StoreManager`, who supplies a `reconditioning_cost_cents` estimate and a `market_adjustment_pct`. Evaluation is permitted from either `SUBMITTED` or `COUNTERED`; against any other state it is rejected with `ERR_APPRAISAL_NOT_OFFERED`. The final value takes the stored `provisional_value_cents`, subtracts the `reconditioning_cost_cents`, then multiplies by one plus the market adjustment after the adjustment has been clamped to the band from −0.15 to +0.15; a single round half-up to whole cents happens at the end, so the evaluation order — provisional first, then the reconditioning deduction, then the adjustment — is pinned. Because it deducts reconditioning and applies market judgment, the final value differs from the provisional estimate for identical instrument data. The result is stored as `final_value_cents`, the appraisal moves to `OFFERED`, and `offered_at` is stamped with the current logical clock. A re-evaluation after a counter-offer recomputes `final_value_cents` and re-stamps `offered_at`, restarting the offer window.

An offer lives for fourteen days from `offered_at`. The customer — and only that customer, matching `X-User-ID` to the appraisal's `customer_id` — may counter by submitting a `counter_value_cents`, moving the appraisal from `OFFERED` to `COUNTERED` so the dealer can evaluate again. The customer may instead accept, moving from `OFFERED` to `ACCEPTED`, or decline, moving to `DECLINED`. Any of these self-service actions attempted under another user's identity is rejected with `ERR_UNAUTHORIZED_ROLE`, and any of them attempted while the appraisal is not `OFFERED` is rejected with `ERR_APPRAISAL_NOT_OFFERED`. If an accept or counter arrives after the fourteenth day, the appraisal flips lazily to `EXPIRED` and the request fails with `ERR_APPRAISAL_EXPIRED` (HTTP 409). `ACCEPTED`, `DECLINED`, and `EXPIRED` are terminal; only an `ACCEPTED` appraisal can feed a sales order, as §3.4 describes.

### 3.3. Institutional Bid Packages and Compliance Review

Institutional sales run through bid packages prepared by an `InstitutionalBidOfficer` for a customer whose `customer_type` is `INSTITUTIONAL` (institutions also declare an `institution_type` of `EDUCATION`, `GOVERNMENT`, `NONPROFIT`, or `CORPORATE`; individual customers carry no institution type). The officer submits a payload containing the `customer_id` and the `lines`, each line pairing an `instrument_id` with a `unit_price_cents`. The server records the creating officer's header identity as `prepared_by_user_id`, stamps `revision_number` at 1, computes pricing, and parks the package in `DRAFT`.

Bid pricing is a three-step pipeline with a pinned evaluation order. First, quantity tiering: `quantity` is the count of `lines`, and `subtotal_cents` is the sum of the lines' `unit_price_cents`. A `tier_discount_pct` of 15 percent applies at eleven or more lines, 12 percent at six through ten lines, 8 percent at three through five lines, and no discount below three; the discounted amount is rounded half-up to whole cents. Second, an institution multiplier — 0.95 for `EDUCATION`, 0.93 for `GOVERNMENT`, 0.97 for `NONPROFIT`, and 1.00 for `CORPORATE` — is applied to the tiered amount and rounded half-up again; this multiplier is visible on the package as `institution_multiplier`. Third, a state-contract ceiling: when the customer carries a non-null `state_contract_ceiling_cents`, the final `total_cents` is the lesser of the multiplied amount and that ceiling, and the ceiling in force at pricing time is snapshotted onto the package as `ceiling_cents`; when the customer has no ceiling, the multiplied amount stands. Rounding half-up happens at each multiplication step.

From `DRAFT`, the officer submits the package — permitted only from `DRAFT`, else `ERR_BID_NOT_ACTIONABLE` — subject to a floor guard: the `total_cents` must be at least the sum of the `floor_price_cents` of every instrument named in the lines, else the submission is rejected with `ERR_BID_BELOW_FLOOR` (HTTP 422). A submitted package goes to compliance. A `ComplianceOfficer` may approve it (`SUBMITTED` → `APPROVED`) or return it for revision (`SUBMITTED` → `DRAFT`), each permitted only from `SUBMITTED`, else `ERR_BID_NOT_ACTIONABLE`. Approval carries the segregation-of-duties rule of §2.1: an officer whose identity matches the package's `prepared_by_user_id` is rejected with `ERR_SOD_SELF_APPROVAL`. Once `APPROVED`, the preparing officer records the outcome by supplying an `outcome` of `AWARDED` or `LOST`; both are terminal. The officer may also withdraw a package from either `DRAFT` or `SUBMITTED`, landing in the terminal `WITHDRAWN`.

A submitted package that needs new pricing is revised rather than edited in place: the officer posts a revision carrying fresh `lines` together with the `expected_bid_version` concurrency token of §2.7. The revision is created-with-supersede — it becomes the package's authoritative content — with pricing fully recomputed per the pipeline above, the `revision_number` advancing by one, and the package's `version` incrementing by one. A stale `expected_bid_version` is refused with `ERR_STALE_VERSION` (HTTP 412). Bids may be read back by both `InstitutionalBidOfficer` and `ComplianceOfficer`, with an optional `customer_id` filter on the list view.

### 3.4. Sales Order Composition, Pricing, and Reservation

Before any order can be composed, a `SalesAssociate` registers the buyer as a customer, recording `full_name`, `email`, and a `customer_type` of `INDIVIDUAL` or `INSTITUTIONAL`. Institutions additionally declare their `institution_type`, may carry the `tax_exempt` flag, the `state_contract_ceiling_cents` contract ceiling (null when no state contract applies), and a `credit_limit_cents` financing ceiling that defaults to zero; every new customer's `risk_score` starts at 700.

A `SalesAssociate` opens a sales order with the `customer_id`, an `items` array of at least one line — each line naming an `instrument_id`, a `unit_price_cents`, and a `discount_pct` — plus a `tax_rate`, the delivery attributes `distance_miles`, `stairs_count`, and `climate_controlled_required`, and optionally a `trade_in_appraisal_id` and a `bid_package_id`. Every instrument named in the lines must be `AVAILABLE`; any line naming an instrument that is not is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`. As the order is created, each line instrument is reserved: `AVAILABLE` → `RESERVED`. The new order opens with `payment_status` of `UNPAID` and `fulfillment_status` of `AWAITING_SCHEDULING`.

The two optional references are state-checked. A trade-in reference must point to an appraisal in `ACCEPTED` that belongs to the order's customer; anything else is rejected with `ERR_TRADE_IN_NOT_ACCEPTED` (HTTP 422). A bid reference must point to a package in `AWARDED` owned by that customer; otherwise the create is rejected with `ERR_BID_NOT_ACTIONABLE`.

Order pricing is computed as follows, and the rounding order is normative. Each line total is computed first as the line's `unit_price_cents` multiplied by one minus its `discount_pct`, rounded half-up to whole cents per line; the order's `subtotal_cents` is the sum of those rounded line totals. The trade-in credit `trade_in_credit_cents` is zero when no appraisal is attached, and otherwise the lesser of the appraisal's `final_value_cents` and forty percent of the subtotal rounded half-up — the cap is inclusive, so a credit exactly equal to the cap is allowed. The taxable base is the subtotal minus the trade-in credit. `tax_cents` is zero when the `tax_rate` is zero (the natural case for a `tax_exempt` institution), and otherwise the taxable base multiplied by the `tax_rate`, rounded half-up. The delivery fee `delivery_fee_cents` comes from the schedule in §3.6. The order's `total_cents` is the subtotal minus the trade-in credit plus the delivery fee plus the tax; `amount_paid_cents` starts at zero; and `balance_cents` is always the total minus the amount paid. While the order remains `UNPAID` the associate may amend it — replacing `items`, `tax_rate`, or the delivery attributes — by carrying the `expected_order_version` token of §2.7; a stale token is refused with `ERR_STALE_VERSION` (HTTP 412), pricing is fully recomputed, and the order's `version` increments by one. Once money has moved the pricing is locked: amendment after a deposit or financing is rejected with `ERR_ORDER_NOT_PAYABLE`. Orders can be listed with `customer_id`, `trade_in_appraisal_id`, or `bid_package_id` filters.

### 3.5. Payments, Financing, and Rent-to-Own

Payments are posted by a `SalesAssociate` with an `amount_cents` and a `method`. Posting is permitted only while the order is `UNPAID` or `DEPOSIT_PAID`; against any later payment state the posting is rejected with `ERR_ORDER_NOT_PAYABLE`. The amount may not exceed the `balance_cents` — an overpayment is rejected with `ERR_OVERPAYMENT` (HTTP 422). A payment smaller than the balance moves the order from `UNPAID` to `DEPOSIT_PAID` (or keeps it there), adding the amount to `amount_paid_cents` and recomputing `balance_cents`. A payment exactly equal to the balance settles the order: `payment_status` moves to `PAID_IN_FULL`, every reserved line instrument moves from `RESERVED` to `SOLD`, and the consignment payouts of §3.1 are posted to the consignor ledgers. A customer may abandon an unpaid order entirely: cancellation by a `SalesAssociate` requires `payment_status` of `UNPAID` and `fulfillment_status` of `AWAITING_SCHEDULING` — otherwise `ERR_ORDER_NOT_PAYABLE` or `ERR_DELIVERY_NOT_ACTIONABLE` as applicable — and moves fulfillment to `CANCELLED` while releasing every reserved instrument back to `AVAILABLE`.

Financing is an alternative to cash settlement. A `FinanceOfficer` applies for a financing agreement against an order whose `payment_status` is still `UNPAID`, supplying the `order_id`, a `program` of `STANDARD` or `RENT_TO_OWN`, a `principal_cents` that must equal the order's `total_cents` (a mismatch is rejected with `ERR_INVALID_REQUEST`), a `term_months` count, and — for `STANDARD` only — an `apr` as a fraction (the rate is ignored for `RENT_TO_OWN`). The agreement starts in `APPLIED`.

Approval requires the agreement to be `APPLIED` and the principal to be no more than the customer's `credit_limit_cents`; a principal above that limit is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422). Approval stamps `activated_at` with the logical clock, moves the agreement to `ACTIVE`, flips the order's `payment_status` from `UNPAID` to `FINANCED_ACTIVE`, and sells the line instruments — `RESERVED` → `SOLD` — posting consignment payouts exactly as a cash settlement would.

The monthly schedule depends on the program. Under `STANDARD`, the monthly rate is one twelfth of the `apr`, and the `monthly_amount_cents` is the principal multiplied by that monthly rate, divided by one minus the quantity one plus the monthly rate raised to the negative power of `term_months`, rounded half-up to whole cents — the classic annuity. Under `RENT_TO_OWN`, the monthly rent is a flat 1.2 percent of the principal, rounded half-up, and the agreement accrues a purchase credit: `purchase_credit_cents` is sixty percent of the monthly rent multiplied by the number of payments made, counting at most twenty-four payments, rounded half-up; converting early therefore costs the principal minus the accrued credit. Each posted payment must be exactly one `monthly_amount_cents` — any other `amount_cents` is rejected with `ERR_INVALID_REQUEST` — and increments `payments_made`; when `payments_made` reaches `term_months` the agreement moves to `PAID_OFF` and the order's `payment_status` advances from `FINANCED_ACTIVE` to `PAID_IN_FULL`.

Missed payments are derived, never stored directly: `missed_payments` is the number of whole calendar months elapsed between `activated_at` and the current logical clock — a month counting only once its day-of-month has been reached — minus `payments_made`, floored at zero, and it is recomputed on every read and write of the agreement. When an `ACTIVE` agreement shows at least three missed payments, a `FinanceOfficer` may declare default; fewer than three is rejected with `ERR_INVALID_REQUEST`. Default moves the agreement to `DEFAULTED`, flips the order from `FINANCED_ACTIVE` to `COLLECTIONS`, moves each delivered line instrument from `DELIVERED` to `REPOSSESSION_HOLD` (a `StoreManager` later releases such an instrument back to `AVAILABLE` via the release-hold action, which requires the instrument to be in `REPOSSESSION_HOLD`), and subtracts 150 from the customer's `risk_score`, subject to the 300 floor.

A `RENT_TO_OWN` agreement in `ACTIVE` may instead be converted to purchase by a `FinanceOfficer`. Conversion against an agreement that is not `ACTIVE`, or not `RENT_TO_OWN`, is rejected with `ERR_AGREEMENT_NOT_CONVERTIBLE`. On conversion the `purchase_credit_cents` is computed as above, the agreement moves to `CONVERTED_TO_PURCHASE`, and the order's `payment_status` advances from `FINANCED_ACTIVE` to `PAID_IN_FULL`. `PAID_OFF`, `DEFAULTED`, `CONVERTED_TO_PURCHASE`, and `CANCELLED` are terminal; the `CANCELLED` state is reached only as a cascade of a completed return, per §3.6.

### 3.6. Delivery, Installation, and Returns

Once money has moved, logistics begins. The dealership's `DeliveryCrew` roster is maintained by a `StoreManager`, recording a `crew_name` and whether the crew is `climate_certified` to operate climate-controlled trucks. A `ServiceCoordinator` schedules a delivery job by naming the `order_id`, the `crew_id`, and a `window_start` and `window_end` — the end must be strictly after the start, else `ERR_INVALID_REQUEST`. Scheduling requires the order's `fulfillment_status` to be `AWAITING_SCHEDULING` and its `payment_status` to be one of `DEPOSIT_PAID`, `PAID_IN_FULL`, or `FINANCED_ACTIVE`; otherwise the request is rejected with `ERR_DELIVERY_NOT_ACTIONABLE`. When the order's `climate_controlled_required` flag is set, the assigned crew must be `climate_certified`; a non-certified crew is rejected with `ERR_CLIMATE_REQUIREMENT_UNMET` (HTTP 422).

Crew time is protected against double-booking under half-open window semantics with a mandatory thirty-minute travel buffer: a new job conflicts when its window overlaps — after extending each committed job's window by thirty minutes beyond its end — another job of the same crew that is `SCHEDULED` or `EN_ROUTE`. A window that begins exactly when another job's buffered window ends is acceptable; anything tighter is rejected with `ERR_CREW_WINDOW_CONFLICT`. On successful scheduling the job is created in `SCHEDULED` and the order's fulfillment advances to `DELIVERY_SCHEDULED`. The same overlap and climate checks apply, unchanged, when a failed job is rescheduled with a fresh `window_start` and `window_end`.

The job itself walks `SCHEDULED` → `EN_ROUTE` → `COMPLETED`, with a `FAILED` detour. Starting a job requires it to be `SCHEDULED` and moves the order to `OUT_FOR_DELIVERY`. Failing a job requires `EN_ROUTE`, drops the job to `FAILED`, and returns the order to `DELIVERY_SCHEDULED` so the coordinator can reschedule. Completing a job requires `EN_ROUTE` and finishes the physical delivery: the job reaches its terminal `COMPLETED`, the order's fulfillment moves to `DELIVERED` with `delivered_at` stamped from the logical clock, and every line instrument moves from `SOLD` to `DELIVERED`. Any start, complete, fail, or reschedule attempted against a job in the wrong state is rejected with `ERR_DELIVERY_NOT_ACTIONABLE`. Delivery jobs may be listed filtered by `order_id` or `crew_id`.

The delivery fee that §3.4 folds into order pricing is built from the order's delivery attributes: a flat base of 15,000 cents, plus 2,500 cents per flight of stairs given in `stairs_count`, plus a distance band on `distance_miles` — nothing extra when the one-way distance is at most 25 miles, 12,000 cents when it is over 25 and at most 60 miles, and 24,000 cents beyond 60 — plus a 20,000-cent surcharge when `climate_controlled_required` is true. The fee is integer arithmetic throughout, with no rounding step needed.

Installation is confirmed on the order — by a `StoreManager`, or by the customer themselves when the order is theirs — moving fulfillment from `DELIVERED` to `INSTALLED` and stamping `installed_at` from the logical clock; an order not in `DELIVERED` is rejected with `ERR_DELIVERY_NOT_ACTIONABLE`. The `installed_at` stamp anchors the return window: a `StoreManager` may complete a return only while fulfillment is `INSTALLED`, the order is `PAID_IN_FULL`, and the logical clock is no later than fourteen days after `installed_at`. A return attempted against the wrong fulfillment state is `ERR_DELIVERY_NOT_ACTIONABLE`, against the wrong payment state is `ERR_ORDER_NOT_PAYABLE`, and after the window is `ERR_RETURN_WINDOW_CLOSED` (HTTP 422). A completed return is a full unwind: `payment_status` moves to `REFUNDED` and fulfillment to `RETURNED`; each line instrument moves from `DELIVERED` back to `IN_PREP`; every `REGISTERED` warranty covering one of those instruments is voided (`REGISTERED` → `VOID`), and each voided warranty subtracts 25 from the customer's `risk_score`, floored at 300; any `ACTIVE` financing agreement on the order is cancelled; and each consignment payout posted at sale is reversed out of `outstanding_payout_cents` by exactly the amount originally added.

### 3.7. Service Plans and Technician Visits

After installation, a `ServiceCoordinator` may attach a service plan to the order — the order must be `INSTALLED` — by naming the `order_id` and a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`. The plan's `price_cents` and `visits_total` come from the tier: `BASIC` costs 30,000 cents and carries 2 visits, `STANDARD` costs 55,000 cents with 4 visits, and `PREMIUM` costs 85,000 cents with 6 visits. Loyalty is rewarded: when the same customer already holds any other plan in `EXHAUSTED` or `CANCELLED`, the new plan's price is the tier price reduced by ten percent, rounded half-up to whole cents. The plan opens `ACTIVE` with `visits_used` and `visits_booked` at zero and `visits_available` equal to `visits_total`. The bookkeeping invariant never breaks: used plus booked plus available always equals `visits_total`.

Visits are booked against the plan by a `ServiceCoordinator` naming the `plan_id`, a `technician_id` from the roster (technicians carry a `full_name` and a `certification_level` of `STANDARD` or `MASTER`), and a `window_start` and `window_end` with the end strictly after the start. Booking requires the plan to be `ACTIVE` — otherwise `ERR_PLAN_NOT_ACTIVE` — and requires `visits_available` greater than zero, else `ERR_PLAN_EXHAUSTED`. Technicians are protected by two capacity rules. Their windows follow closed-interval semantics, so two `BOOKED` visits for the same technician conflict whenever their intervals touch, shared endpoints included (`ERR_TECHNICIAN_WINDOW_CONFLICT`). And no technician may hold more than four `BOOKED` visits on the same UTC calendar day (`ERR_TECHNICIAN_DAY_CAPACITY_REACHED`). A successfully booked visit starts in `BOOKED` and holds one plan credit: `visits_booked` increases by one.

Completing a visit requires it to be `BOOKED` and releases the credit into consumption: `visits_booked` decreases by one and `visits_used` increases by one. Cancelling a visit likewise requires `BOOKED`, moves the visit to `CANCELLED`, and hands the credit back — `visits_booked` decreases by one while `visits_used` is untouched. On every plan mutation the system re-evaluates exhaustion: when `visits_used` has reached `visits_total` with nothing left booked, the plan moves itself from `ACTIVE` to `EXHAUSTED`. A coordinator may suspend an `ACTIVE` plan (`ACTIVE` → `SUSPENDED`) and resume a suspended one (`SUSPENDED` → `ACTIVE`); each requires the matching source state, else `ERR_PLAN_NOT_ACTIVE`. Cancellation from either `ACTIVE` or `SUSPENDED` moves the plan to `CANCELLED`, cancels every still-`BOOKED` visit, and zeroes `visits_booked`. `EXHAUSTED` and `CANCELLED` are terminal.

### 3.8. Warranties and Restoration Referrals

Manufacturer warranty registration begins with a `SalesAssociate` naming an `order_id` and an `instrument_id`. The order must be `DELIVERED` or `INSTALLED`; the instrument must appear among the order's items, else `ERR_INVALID_REQUEST`; and registration must occur within sixty days of the order's `delivered_at` — later than that is rejected with `ERR_WARRANTY_WINDOW_CLOSED` (HTTP 422). The registration opens in `PENDING` carrying a base `term_months` of 24.

Confirmation by a `StoreManager` moves the registration from `PENDING` to `REGISTERED`, stamps `registered_at` from the logical clock, and computes `coverage_end`: the order's `delivered_at` plus 24 calendar months, extended by a further 12 months when the registration is confirmed no later than thirty days after delivery — prompt registration earns the longer coverage. From then on the warranty is read with a lazy expiry: any read made after the logical clock has passed `coverage_end` reports the warranty as `EXPIRED`. The only other exit from `REGISTERED` is voiding through the completed-return cascade of §3.6, which also levies the 25-point `risk_score` penalty per voided warranty. `VOID` and `EXPIRED` are terminal. Warranties may be listed filtered by `order_id` or `instrument_id`.

Instruments that need workshop attention beyond routine prep go out on referral. A `StoreManager` creates a referral with the `instrument_id` and the `shop_name` of the restoration shop; the referral opens in `REFERRED`. Assessment records a `condition_score` between 1 and 100 together with `estimate_low_cents` and `estimate_high_cents`, moving the referral to `ASSESSED`. A binding quote records `final_quote_cents`, moving to `QUOTED`. The decision step takes a `decision` of `COMMISSIONED` or `DECLINED`, both terminal. Commissioning requires the instrument to be `AVAILABLE` — it is placed into `RESTORATION_HOLD`, and an unavailable instrument is rejected with `ERR_INSTRUMENT_NOT_AVAILABLE`. Each step requires its exact source state, else `ERR_REFERRAL_NOT_ACTIONABLE`. When the workshop work is done, a `StoreManager` completes restoration, moving the instrument from `RESTORATION_HOLD` back to `IN_PREP` (only `RESTORATION_HOLD` is eligible), ready to be prepped and listed again per §3.1. Referrals may be listed filtered by `instrument_id`.

### 3.9. Showroom Events and Artist Settlement

The artist series runs in two bookable spaces, `MAIN_SHOWROOM` and `RECITAL_HALL`. A `StoreManager` plans an event with the `room`, a `title`, `start_at` and `end_at` (the end strictly after the start, else `ERR_INVALID_REQUEST`), a seat `capacity`, the `artist_guarantee_cents` minimum payout, and the artist's `split_pct` share of gross receipts as a fraction, for example 0.70. Room bookings use half-open overlap semantics: an event conflicts only with a non-`CANCELLED` event in the same room whose window strictly overlaps, so back-to-back scheduling — one event's `end_at` equal to the next's `start_at` — is allowed. An overlapping submission is rejected with `ERR_ROOM_WINDOW_CONFLICT`. The new event is `PLANNED` with `rsvp_count` at zero.

Opening RSVPs moves the event from `PLANNED` to `RSVP_OPEN`. While open, a `SalesAssociate` adds parties by supplying a `party_size` that defaults to 1; each addition must leave `rsvp_count` plus `party_size` no greater than `capacity`, else `ERR_EVENT_CAPACITY_EXCEEDED`, and a successful addition grows `rsvp_count` by the party size. After the event has ended — the logical clock at or past `end_at` — a `StoreManager` settles it by supplying the `gross_cents` ticket receipts. The artist's `payout_cents` is the greater of the `artist_guarantee_cents` and the `split_pct` share of the gross rounded half-up to whole cents, and the event reaches its terminal `SETTLED`. Settlement before `end_at`, or against an event not in `RSVP_OPEN`, is rejected with `ERR_EVENT_NOT_SETTLABLE` — the same code that guards opening RSVPs and cancellation against the wrong state. Cancelling from `PLANNED` or `RSVP_OPEN` moves the event to `CANCELLED`, and a cancelled event frees its window: it no longer participates in room-overlap checks.

## 4. Endpoint Definitions

Operations that create a new resource — registering a consignor, customer, instrument, crew, technician, appraisal, bid package, order, delivery job, plan, visit, agreement, warranty, referral, event, or adding an RSVP party — return `201 Created`. Operations that act on an existing resource, including all lifecycle transitions, evaluation, payment posting, settlement, and the clock-setting capability, return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/piano-dealer/_clock/set_current_utc` | Set the logical clock (default 2026-05-01T00:00:00Z) | PlatformAdmin |
| POST | `/piano-dealer/consignors` | Register a consignor | StoreManager |
| GET | `/piano-dealer/consignors/{id}` | Read a consignor (self or manager) | StoreManager, Consignor |
| GET | `/piano-dealer/consignors/{id}/instruments` | List instruments consigned by this consignor | StoreManager, Consignor |
| POST | `/piano-dealer/customers` | Register a customer or institution | SalesAssociate |
| GET | `/piano-dealer/customers/{id}` | Read a customer | SalesAssociate, StoreManager, FinanceOfficer, InstitutionalBidOfficer, Customer |
| POST | `/piano-dealer/instruments` | Intake an instrument; starts IN_PREP | StoreManager |
| GET | `/piano-dealer/instruments/{id}` | Read an instrument | StoreManager, SalesAssociate, InstitutionalBidOfficer, Consignor |
| POST | `/piano-dealer/instruments/{id}/list-for-sale` | Move IN_PREP to AVAILABLE | StoreManager |
| POST | `/piano-dealer/instruments/{id}/complete-restoration` | Move RESTORATION_HOLD to IN_PREP | StoreManager |
| POST | `/piano-dealer/instruments/{id}/release-hold` | Move REPOSSESSION_HOLD to AVAILABLE | StoreManager |
| POST | `/piano-dealer/instruments/{id}/return-to-consignor` | Return AVAILABLE consignment instrument to owner | StoreManager |
| POST | `/piano-dealer/trade-in-appraisals` | Submit a trade-in; computes provisional value | SalesAssociate |
| GET | `/piano-dealer/trade-in-appraisals/{id}` | Read an appraisal | SalesAssociate, Customer |
| GET | `/piano-dealer/trade-in-appraisals` | List appraisals, optional customer filter | SalesAssociate |
| POST | `/piano-dealer/trade-in-appraisals/{id}/evaluate` | In-shop evaluation; moves SUBMITTED or COUNTERED to OFFERED | StoreManager |
| POST | `/piano-dealer/trade-in-appraisals/{id}/counter` | Customer counter-offer; OFFERED to COUNTERED | Customer |
| POST | `/piano-dealer/trade-in-appraisals/{id}/accept` | Customer accepts offer; OFFERED to ACCEPTED | Customer |
| POST | `/piano-dealer/trade-in-appraisals/{id}/decline` | Customer declines offer; OFFERED to DECLINED | Customer |
| POST | `/piano-dealer/bid-packages` | Create DRAFT institutional bid with computed pricing | InstitutionalBidOfficer |
| GET | `/piano-dealer/bid-packages/{id}` | Read a bid package | InstitutionalBidOfficer, ComplianceOfficer |
| GET | `/piano-dealer/bid-packages` | List bid packages, optional customer filter | InstitutionalBidOfficer, ComplianceOfficer |
| POST | `/piano-dealer/bid-packages/{id}/submit` | Submit a DRAFT bid with floor guard | InstitutionalBidOfficer |
| POST | `/piano-dealer/bid-packages/{id}/compliance-approve` | Compliance approval with segregation of duties | ComplianceOfficer |
| POST | `/piano-dealer/bid-packages/{id}/return-for-revision` | Return a SUBMITTED bid to DRAFT | ComplianceOfficer |
| POST | `/piano-dealer/bid-packages/{id}/record-outcome` | Record APPROVED bid as AWARDED or LOST | InstitutionalBidOfficer |
| POST | `/piano-dealer/bid-packages/{id}/withdraw` | Withdraw a DRAFT or SUBMITTED bid | InstitutionalBidOfficer |
| POST | `/piano-dealer/bid-packages/{id}/revisions` | Create-with-supersede revision with OCC | InstitutionalBidOfficer |
| POST | `/piano-dealer/sales-orders` | Create order; prices and reserves instruments | SalesAssociate |
| GET | `/piano-dealer/sales-orders/{id}` | Read an order | SalesAssociate, StoreManager, FinanceOfficer, ServiceCoordinator, Customer |
| GET | `/piano-dealer/sales-orders` | List orders with optional filters | SalesAssociate, StoreManager, FinanceOfficer |
| PATCH | `/piano-dealer/sales-orders/{id}` | Amend an UNPAID order with OCC | SalesAssociate |
| POST | `/piano-dealer/sales-orders/{id}/payments` | Post a payment toward the balance | SalesAssociate |
| POST | `/piano-dealer/sales-orders/{id}/confirm-installation` | Confirm installation; DELIVERED to INSTALLED | StoreManager, Customer |
| POST | `/piano-dealer/sales-orders/{id}/complete-return` | Complete a return within the window; full cascade | StoreManager |
| POST | `/piano-dealer/sales-orders/{id}/cancel` | Cancel an unpaid, unscheduled order | SalesAssociate |
| POST | `/piano-dealer/delivery-crews` | Register a delivery crew | StoreManager |
| POST | `/piano-dealer/technicians` | Register a service technician | StoreManager |
| POST | `/piano-dealer/delivery-jobs` | Schedule a delivery with crew and climate checks | ServiceCoordinator |
| GET | `/piano-dealer/delivery-jobs/{id}` | Read a delivery job | ServiceCoordinator |
| GET | `/piano-dealer/delivery-jobs` | List delivery jobs with optional filters | ServiceCoordinator, StoreManager |
| POST | `/piano-dealer/delivery-jobs/{id}/start` | Start a scheduled job; order out for delivery | ServiceCoordinator |
| POST | `/piano-dealer/delivery-jobs/{id}/complete` | Complete an en-route job; order delivered | ServiceCoordinator |
| POST | `/piano-dealer/delivery-jobs/{id}/fail` | Fail an en-route job; order reschedulable | ServiceCoordinator |
| POST | `/piano-dealer/delivery-jobs/{id}/reschedule` | Reschedule a failed job with new window | ServiceCoordinator |
| POST | `/piano-dealer/service-plans` | Attach a service plan to an INSTALLED order | ServiceCoordinator |
| GET | `/piano-dealer/service-plans/{id}` | Read a service plan | ServiceCoordinator, Customer |
| GET | `/piano-dealer/service-plans` | List service plans, optional order filter | ServiceCoordinator |
| POST | `/piano-dealer/service-plans/{id}/suspend` | Suspend an ACTIVE plan | ServiceCoordinator |
| POST | `/piano-dealer/service-plans/{id}/resume` | Resume a SUSPENDED plan | ServiceCoordinator |
| POST | `/piano-dealer/service-plans/{id}/cancel` | Cancel a plan and its booked visits | ServiceCoordinator |
| POST | `/piano-dealer/service-visits` | Book a tuning/regulation visit | ServiceCoordinator |
| GET | `/piano-dealer/service-visits/{id}` | Read a visit | ServiceCoordinator |
| GET | `/piano-dealer/service-visits` | List visits with optional filters | ServiceCoordinator |
| POST | `/piano-dealer/service-visits/{id}/complete` | Complete a booked visit | ServiceCoordinator |
| POST | `/piano-dealer/service-visits/{id}/cancel` | Cancel a booked visit; releases credit | ServiceCoordinator |
| POST | `/piano-dealer/financing-agreements` | Apply for financing on an UNPAID order | FinanceOfficer |
| GET | `/piano-dealer/financing-agreements/{id}` | Read an agreement | FinanceOfficer, Customer |
| GET | `/piano-dealer/financing-agreements` | List agreements, optional order filter | FinanceOfficer |
| POST | `/piano-dealer/financing-agreements/{id}/approve` | Approve an APPLIED agreement with credit check | FinanceOfficer |
| POST | `/piano-dealer/financing-agreements/{id}/payments` | Post exactly one monthly payment | FinanceOfficer |
| POST | `/piano-dealer/financing-agreements/{id}/convert-to-purchase` | Convert a RENT_TO_OWN agreement to purchase | FinanceOfficer |
| POST | `/piano-dealer/financing-agreements/{id}/declare-default` | Declare default on a delinquent agreement | FinanceOfficer |
| POST | `/piano-dealer/warranty-registrations` | Start a manufacturer warranty registration | SalesAssociate |
| GET | `/piano-dealer/warranty-registrations/{id}` | Read a warranty (lazy expiry on read) | SalesAssociate, StoreManager |
| GET | `/piano-dealer/warranty-registrations` | List warranties with optional filters | SalesAssociate, StoreManager |
| POST | `/piano-dealer/warranty-registrations/{id}/confirm` | Confirm registration; computes coverage end | StoreManager |
| POST | `/piano-dealer/restoration-referrals` | Refer an instrument to a restoration shop | StoreManager |
| GET | `/piano-dealer/restoration-referrals/{id}` | Read a referral | StoreManager |
| GET | `/piano-dealer/restoration-referrals` | List referrals, optional instrument filter | StoreManager |
| POST | `/piano-dealer/restoration-referrals/{id}/assess` | Record assessment and estimates | StoreManager |
| POST | `/piano-dealer/restoration-referrals/{id}/quote` | Record binding quote | StoreManager |
| POST | `/piano-dealer/restoration-referrals/{id}/record-decision` | Record COMMISSIONED or DECLINED decision | StoreManager |
| POST | `/piano-dealer/showroom-events` | Create an event with room overlap check | StoreManager |
| GET | `/piano-dealer/showroom-events/{id}` | Read an event | StoreManager, SalesAssociate |
| POST | `/piano-dealer/showroom-events/{id}/open-rsvp` | Open RSVPs for a PLANNED event | StoreManager |
| POST | `/piano-dealer/showroom-events/{id}/rsvps` | Add a party to an open event | SalesAssociate |
| POST | `/piano-dealer/showroom-events/{id}/settle` | Settle artist payout after event end | StoreManager |
| POST | `/piano-dealer/showroom-events/{id}/cancel` | Cancel an event; frees the room window | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_SOD_SELF_APPROVAL` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INSTRUMENT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_ORDER_NOT_PAYABLE` | 409 Conflict |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_APPRAISAL_NOT_OFFERED` | 409 Conflict |
| `ERR_APPRAISAL_EXPIRED` | 409 Conflict |
| `ERR_TRADE_IN_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_BID_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_BID_BELOW_FLOOR` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREW_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_CLIMATE_REQUIREMENT_UNMET` | 422 Unprocessable Entity |
| `ERR_DELIVERY_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_TECHNICIAN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TECHNICIAN_DAY_CAPACITY_REACHED` | 409 Conflict |
| `ERR_PLAN_NOT_ACTIVE` | 409 Conflict |
| `ERR_PLAN_EXHAUSTED` | 409 Conflict |
| `ERR_AGREEMENT_NOT_CONVERTIBLE` | 409 Conflict |
| `ERR_WARRANTY_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_ROOM_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_EVENT_CAPACITY_EXCEEDED` | 409 Conflict |
| `ERR_EVENT_NOT_SETTLABLE` | 409 Conflict |
| `ERR_REFERRAL_NOT_ACTIONABLE` | 409 Conflict |

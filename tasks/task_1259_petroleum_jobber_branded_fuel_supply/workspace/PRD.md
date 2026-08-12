# Petroleum Jobber Branded Fuel Supply API — Product Requirements Document

## 1. Introduction

A branded petroleum jobber lives and dies by three ledgers that never stop moving: the fuel it sells to dealers against a branded volume commitment, the credit it extends while waiting for electronic drafts to settle, and the inventory it can prove is still in the ground. This document specifies the requirements for an API that manages that entire operating loop for a jobber supplying branded dealer stations — supply agreements with committed gallons and buyout economics, daily rack price postings to the dealer network, transport drop dispatch planned against tank levels, book-versus-physical inventory reconciliation, jurisdictional fuel tax remittance, and the brand image obligations that keep a dealer in the network.

The API is mounted under `/api` and is designed around a strict segregation of duties: the pricing desk never dispatches trucks, the credit desk never opens reconciliations, and the operator who opens an inventory reconciliation may never be the one who resolves it. A logical clock governs every date and datetime in the system, so renewals, late penalties, cure periods, and invoice aging are fully deterministic. All endpoints are flat, top-level resources joined by references; cross-entity consequences (a delivered drop creates an invoice, a verified loss shrinks a tank book, a failed brand audit cascades into agreement default) are applied immediately and are visible in the same request's response and in every subsequent read.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts and invariants that apply uniformly across the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, carrying a blank header, or naming a role the system does not declare is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The declared roles are `JobberAdmin`, `PricingDesk`, `Dispatcher`, `CreditManager`, `TaxAccountant`, `BrandInspector`, and `DealerOperator`. When the acting role is not listed among the roles permitted on an endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Role identity is interpreted as follows. When `X-User-Role` is `JobberAdmin`, `PricingDesk`, `Dispatcher`, `CreditManager`, `TaxAccountant`, or `BrandInspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `opener_user_id` on an inventory reconciliation) but does not compare it to any entity's `id`. When `X-User-Role` is `DealerOperator`, `X-User-ID` is the `id` of the acting `DealerStation`; ownership checks on any resource that references a `DealerStation` compare the resource's station reference to `X-User-ID`, so a dealer-side operator may gauge tanks and submit meter readings only for tanks whose station they are, and may report or dispute loss events only for their own station. A `DealerOperator` acting on a resource belonging to a different station is rejected with `ERR_STATION_OWNERSHIP_MISMATCH` (HTTP 403), and all of a dealer operator's read access is likewise scoped to their own station's resources.

The division of responsibility is: `JobberAdmin` owns stations, agreements, tanks, trucks, products, reconciliations, loss adjudication, and the logical clock; `PricingDesk` owns rack price postings; `Dispatcher` owns transport drops; `CreditManager` owns credit terms, invoice voiding, and EFT drafts; `TaxAccountant` owns tax remittances; `BrandInspector` records brand compliance audits. List and detail reads are shared across all seven roles, subject to the dealer scoping above.

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

List endpoints accept two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, and must lie between 1 and 100 inclusive. The `offset` parameter sets the number of items skipped and defaults to 0. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

Unless a list endpoint states otherwise, resources are returned sorted by `created_at` in ascending order. Meter readings are the single exception: they are returned ordered by `reading_at` ascending, with ties broken by `created_at` ascending, mirroring the chronological semantics of the totalizer.

List endpoints also expose filter query parameters matching their resource's natural keys. Products may be filtered by `category`; stations by `operating_status`, `credit_status`, `compliance_status`, or `state_code`; agreements by `station_id` and `status`; rack price postings by `terminal_code`, `product_id`, `effective_date`, and `status`; storage tanks by `station_id` and `product_id`; transport drops by `station_id`, `tank_id`, `truck_id`, `product_id`, `invoice_id`, and `status`; meter readings by `tank_id`; loss events by `station_id`, `tank_id`, `reconciliation_id`, and `status`; reconciliations by `station_id` and `status`; invoices by `station_id`, `drop_id`, `product_id`, and `status`; EFT drafts by `invoice_id`, `station_id`, and `status`; tax remittances by `state_code` and `status`; and brand compliance audits by `station_id` and `result`.

### 2.4. The Logical Clock

All date and datetime semantics in the system are governed by a logical clock, never by wall-clock time. At server startup the logical clock reads exactly `2026-05-01T00:00:00Z`. The clock advances only through an administrator-only test-driving capability: a `JobberAdmin` supplies a `to_iso8601` instant and the server moves the logical clock to it, returning the new `current_utc`. Nothing else moves the clock.

Setting the clock is never a silent operation. Whenever the clock advances, the server evaluates every time-based automatic transition: any invoice in `ISSUED` whose `due_date` falls before the new clock date moves to `OVERDUE`; any supply agreement in `ACTIVE` or `RENEWAL_PENDING` whose `term_end_date` falls before the new clock date moves to `EXPIRED`; and any station whose `compliance_status` is `CURE_PERIOD` and whose cure window has elapsed (the clock date has advanced past `cure_started_at` plus 30 days) falls into `DEFAULT`, triggering the agreement default cascade described in §3.4. These transitions are applied as part of the clock-setting request and are visible in its response and in all subsequent reads.

### 2.5. Units of Measure, Monetary Representation, and Rounding

All money is represented as integer cents in fields whose names end in `_cents` — there are no floating-point dollars anywhere in the API. All per-gallon prices and rates are represented as integer tenths-of-a-cent per gallon in fields whose names end in `_tc_per_gal`, so a value of 2000 means $2.000 per gallon; converting a per-gallon rate to a cent amount therefore involves multiplying by gallons and dividing by ten.

Every rounding in the system uses the round-half-up method. Where a money amount is assembled from named components (fuel, freight, and tax on an invoice; per-category lines on a tax remittance; base and penalty on a buyout), each named component is rounded to integer cents before the components are summed — summing first and rounding once is a different result and is not permitted. Gallon quantities are integer arithmetic throughout, with one exception: the temperature-corrected physical inventory used for reconciliation variance is rounded half-up to whole gallons per tank before the per-tank figures are summed (§3.7).

### 2.6. Rack Price Resolution

Drop pricing and drop estimation both depend on resolving a single "current rack price" for a product at a terminal on a given date. The current rack price for a product at a station's `home_terminal_code` on date D is the posting in `POSTED` status for that terminal and product whose `effective_date` is the greatest effective date on or before D; when several postings share that greatest effective date, the tie is broken in favor of the posting with the latest `created_at`. If no `POSTED` posting exists with an effective date on or before the relevant date, pricing fails with `ERR_PRICE_NOT_POSTED` (HTTP 422). For a delivered drop the relevant date is the delivery date; for an estimated amount at drop creation or replanning it is the current clock date.

### 2.7. Common Resource Properties

Every resource carries a standard set of system-managed fields, unless stated otherwise:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` (integer): starts at creation and increments by one on every mutation; it is the basis of optimistic concurrency control.

A mutation that fans out to other resources — a drop delivery that creates an invoice and shifts a station's credit band, a supersession that retires one posting and creates another — refreshes `updated_at` and increments `version` on each mutated resource that carries those fields. Two resource types are deliberately leaner: meter readings and brand compliance audits carry only `id` and `created_at`. Neither has `updated_at` nor `version`, and neither participates in optimistic concurrency control.

### 2.8. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control, and each names its guard field explicitly:

1. **Amending a supply agreement.** The amendment request must carry `expected_agreement_version`, a non-optional field holding the agreement `version` the client last observed. If the agreement's current `version` has advanced past that value, the amendment is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's terms were derived from a snapshot that no longer reflects the agreement.
2. **Superseding a rack price posting.** The supersession request must carry `expected_superseded_posting_version`, a non-optional field holding the `version` of the `POSTED` posting the client last observed. A mismatch with that posting's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412), since supersession creates a replacement for the same terminal, product, and effective date and a stale base version means the client is retiring a posting it never saw.
3. **Replanning a failed transport drop.** The replan request must carry `expected_drop_version`, a non-optional field holding the drop `version` the client last observed. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a dispatcher from writing a fresh window and truck onto a drop that has already been replanned and re-failed by someone else.

No other endpoint takes a version field. Endpoints not listed above process mutations without any optimistic-concurrency input.

### 2.9. Request Validation Pipeline

Every request is validated in a fixed pipeline order, and the stages are evaluated in the sequence below — the first failing stage determines the response, so an earlier failure masks every later check.

1. **User context.** `X-User-ID` and `X-User-Role` are present, non-blank, and the role is declared — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization.** The acting role appears in the endpoint's permitted roles — otherwise `ERR_UNAUTHORIZED_ROLE` (HTTP 403).
3. **Body shape.** All required fields are present, no unknown fields appear, types are valid, enum members are valid, `window_start` is strictly before `window_end`, `term_end_date` is strictly after `term_start_date`, `period_end` is on or after `period_start`, and audit `score` lies between 0 and 100 inclusive — otherwise `ERR_VALIDATION_FAILED` (HTTP 400). Duplicate `product_code` or `truck_code` values are also reported at this shape-and-integrity level as `ERR_VALIDATION_FAILED`.
4. **Existence.** Path identifiers are checked left to right, then body foreign keys (`station_id`, `tank_id`, `truck_id`, `product_id`, `invoice_id`). Each missing resource yields its resource-specific 404: `ERR_PRODUCT_NOT_FOUND`, `ERR_DEALER_STATION_NOT_FOUND`, `ERR_SUPPLY_AGREEMENT_NOT_FOUND`, `ERR_RACK_PRICE_POSTING_NOT_FOUND`, `ERR_STORAGE_TANK_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`, `ERR_TRANSPORT_DROP_NOT_FOUND`, `ERR_METER_READING_NOT_FOUND`, `ERR_LOSS_EVENT_NOT_FOUND`, `ERR_INVENTORY_RECONCILIATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, `ERR_EFT_DRAFT_NOT_FOUND`, `ERR_TAX_REMITTANCE_NOT_FOUND`, or `ERR_BRAND_AUDIT_NOT_FOUND`.
5. **Dealer ownership.** A `DealerOperator` may act only on resources of the station whose `id` equals `X-User-ID` — tanks and meter readings resolve ownership through the tank's station, loss events through their `station_id` — otherwise `ERR_STATION_OWNERSHIP_MISMATCH` (HTTP 403).
6. **State preconditions.** State-machine from-state guards and cross-entity state gates are evaluated — the generic failure is `ERR_INVALID_STATE` (HTTP 409), with the dedicated gates `ERR_STATION_NOT_ACTIVE` and `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409) on drop creation and the stale-version guard `ERR_STALE_VERSION` (HTTP 412) on the three optimistic-concurrency writes.
7. **Drop safety.** Truck capacity and tank safe-fill checks — `ERR_TRUCK_CAPACITY_EXCEEDED` and `ERR_SAFE_FILL_EXCEEDED` (HTTP 422).
8. **Temporal rules.** Truck window conflicts, tank settle windows, past-dated price effective dates, meter totalizer regressions, premature draft execution, and the renewal window — `ERR_TRUCK_WINDOW_CONFLICT` and `ERR_TANK_SETTLE_WINDOW` (HTTP 409), `ERR_EFFECTIVE_DATE_IN_PAST` and `ERR_METER_READING_REGRESSION` (HTTP 422), `ERR_DRAFT_NOT_EXECUTABLE` and `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409).
9. **Uniqueness and integrity.** One `POSTED` posting per terminal, product, and effective date (`ERR_PRICE_POSTING_CONFLICT`); one open reconciliation per station (`ERR_RECONCILIATION_OPEN_EXISTS`); one overlapping tax remittance per state and period (`ERR_TAX_PERIOD_ALREADY_FILED`); one scheduled draft per invoice (`ERR_DRAFT_ALREADY_SCHEDULED`); resolver distinct from opener (`ERR_SEGREGATION_OF_DUTIES`, HTTP 403); renewal blocked during cure (`ERR_CURE_PERIOD_ACTIVE`) or with overdue invoices (`ERR_OVERDUE_INVOICES_EXIST`); missing posted price (`ERR_PRICE_NOT_POSTED`, HTTP 422); unresolved linked losses (`ERR_LINKED_LOSS_NOT_WRITTEN_OFF`); open drops blocking agreement termination (`ERR_AGREEMENT_HAS_OPEN_DROPS`) — these are HTTP 409 unless noted.
10. **Projected credit.** The drop's estimated amount is tested against the station's remaining credit headroom — `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

### 2.10. Credit Exposure and the Station Credit Band

Each dealer station carries `current_exposure_cents`, the sum of `total_cents` over that station's invoices in `ISSUED` or `OVERDUE` status — paid and voided invoices never count. Exposure is recomputed whenever an invoice is created at delivery, whenever an invoice is voided, and whenever an EFT draft settles; every recompute is immediate and visible in the same request's reads.

On every recompute the station's credit band is re-evaluated against `credit_limit_cents`: exposure reaching at least 80 percent of the limit places the station in `WATCH` (the boundary is inclusive), and exposure below that line keeps or returns the station to `GOOD_STANDING`. The comparison is performed in exact integer arithmetic — the station is in `WATCH` precisely when five times the exposure is at least four times the limit — so no floating-point drift can move a boundary case. The third band state, `HOLD`, is never entered or exited by the exposure computation: `HOLD` is entered only when an EFT draft execution fails, and it is exited only through an explicit credit restoration, which then applies the exposure band to decide whether the station lands in `GOOD_STANDING` or `WATCH`.

## 3. Business Logic & Workflows

### 3.1. The Product Catalogue, Trucks, and Dealer Station Onboarding

The jobber's catalogue begins with products. A `JobberAdmin` registers each product with a unique `product_code` (such as `REGULAR_87`; attempting to reuse a code is rejected with `ERR_VALIDATION_FAILED`), a human-readable `display_name`, a `category` of either `GASOLINE` or `DIESEL`, the `federal_excise_tc_per_gal` applicable to that product (184 for gasoline, 244 for diesel, in tenths of a cent per gallon), and a `temp_coeff` — the thermal expansion coefficient per degree Fahrenheit (0.00065 for gasoline, 0.00040 for diesel) — which must be greater than zero. The category drives both federal excise grouping on invoices and the per-category tax lines on a remittance; the coefficient feeds the temperature-corrected reconciliation variance in §3.7. Trucks are registered with a unique `truck_code` and a `capacity_gallons` greater than zero, which later bounds drop planning.

Dealer stations are onboarded by a `JobberAdmin` with a `station_name`, a two-letter `state_code` that keys the station's tax jurisdiction, the `home_terminal_code` at which its drops are priced, the `state_excise_tc_per_gal` for its jurisdiction, and a `credit_limit_cents` of at least zero. Two optional fields carry defaults: `local_option_tc_per_gal` defaults to 0, and `credit_terms_days` defaults to 10 and must be at least 1. A new station begins with `operating_status` of `ONBOARDING`, `credit_status` of `GOOD_STANDING`, `compliance_status` of `COMPLIANT`, and zero exposure.

A station's three status dimensions evolve in parallel on one row. A `JobberAdmin` activates an `ONBOARDING` station to `ACTIVE`; suspends an `ACTIVE` station to `SUSPENDED`; reactivates a `SUSPENDED` station back to `ACTIVE`; and terminates a station from either `ACTIVE` or `SUSPENDED` into the terminal `TERMINATED` state. Each of these actions requires the stated from-state, failing with `ERR_INVALID_STATE` otherwise, and each increments the station's `version`. Termination carries a second guard: no supply agreement for the station may be in `DRAFT`, `ACTIVE`, `RENEWAL_PENDING`, `DEFAULT_NOTICE`, or `BUYOUT_PENDING` — a live agreement blocks termination with `ERR_INVALID_STATE`, so a station can only be wound down after every agreement has reached a terminal outcome. A `CreditManager` may separately update a station's `credit_limit_cents` or `credit_terms_days`; that update increments the station's `version` and, when the limit changed, re-evaluates the credit band of §2.10.

### 3.2. Supply Agreements: Terms, Amendment, and Activation

The commercial backbone of the jobber-dealer relationship is the supply agreement. A `JobberAdmin` drafts one by supplying the `station_id` of the branded dealer, an inclusive `term_start_date` and `term_end_date` (the end strictly after the start, failing `ERR_VALIDATION_FAILED` otherwise), the `committed_gallons` for the term (greater than zero), the `imaging_allowance_cents` advanced at signing for brand imaging (at least zero), the expected `margin_tc_per_gal` (at least zero), the `shortfall_penalty_tc_per_gal` charged on unfulfilled commitment (at least zero), and a `buyout_method` of either `UNAMORTIZED_DISCOUNT` or `LOST_MARGIN`. A new agreement is `DRAFT`, with `renewal_count` and `renewal_credit_cents` both 0 and `buyout_settlement_cents` null until a buyout is executed.

Fulfilment is measured continuously rather than stored: an agreement's `fulfilled_gallons` is computed on every read as the sum of `delivered_gallons` over the station's drops in `RECONCILED` status whose delivery clock-date falls within the agreement's term, both term dates inclusive. Activation moves an agreement from `DRAFT` to `ACTIVE` and requires the station's `operating_status` to be `ACTIVE`; activating against a station that is still onboarding, suspended, or terminated is rejected with `ERR_STATION_NOT_ACTIVE`, while an agreement that is not `DRAFT` fails with `ERR_INVALID_STATE`.

Terms may be amended by a `JobberAdmin` while the agreement is in `DRAFT` or `ACTIVE`; the amendable terms are `committed_gallons`, `imaging_allowance_cents`, `margin_tc_per_gal`, `shortfall_penalty_tc_per_gal`, and `buyout_method`. Amendment is one of the three optimistic-concurrency writes of §2.8: the request must carry `expected_agreement_version` matching the agreement's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful amendment increments the agreement's `version`.

### 3.3. Renewal, Volume Incentives, Buyout, and End-of-Term Outcomes

Renewal is a two-step dance with a hard window. A `JobberAdmin` may open renewal on an `ACTIVE` agreement only when the current clock date lies within the renewal window — from 90 days before `term_end_date` through `term_end_date` itself, both ends inclusive; outside that window the request is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN`. Opening renewal moves the agreement to `RENEWAL_PENDING`. Completing the renewal requires three preconditions, in order: the agreement is `RENEWAL_PENDING` (else `ERR_INVALID_STATE`), the station's `compliance_status` is `COMPLIANT` (a station in `CURE_PERIOD` or `DEFAULT` blocks renewal with `ERR_CURE_PERIOD_ACTIVE`), and the station has no invoice in `OVERDUE` (else `ERR_OVERDUE_INVOICES_EXIST`). The renewal payload carries `new_term_start_date` and `new_term_end_date`, which replace the agreement's term, and may carry `new_committed_gallons`, which replaces `committed_gallons` when supplied.

Completing a renewal also settles the volume incentive for the ending term. The system computes the fulfilment percentage over the ending term — one hundred times `fulfilled_gallons` divided by `committed_gallons`, rounded half-up to two decimal places — and when that percentage is at least 95.00 (exactly 95.00 qualifies), the station earns a `renewal_credit_cents` equal to one percent of `imaging_allowance_cents`, rounded half-up to integer cents; below the threshold the credit is 0. Every completed renewal increments `renewal_count` by one. If the logical clock advances past `term_end_date` while the agreement sits in `ACTIVE` or `RENEWAL_PENDING` — a renewal opened but never completed — the agreement moves to `EXPIRED`.

Buyout is the negotiated early exit. A `JobberAdmin` initiates a buyout on an `ACTIVE` agreement, which again requires the station itself to be `ACTIVE` (else `ERR_STATION_NOT_ACTIVE`), moving the agreement to `BUYOUT_PENDING`; cancelling the buyout returns the agreement to `ACTIVE`. Executing the buyout settles the economics and moves the agreement to the terminal `BOUGHT_OUT` state, recording the result in `buyout_settlement_cents`.

The settlement is computed in a pinned order. First the buyout base, which depends on the agreement's `buyout_method`. Under `UNAMORTIZED_DISCOUNT`, the base is the pro-rata unearned imaging allowance: `imaging_allowance_cents` multiplied by the remaining days — the larger of zero and the number of days from the current clock date to `term_end_date` — divided by the total term length in days from `term_start_date` to `term_end_date`, rounded half-up to integer cents; it ignores volume performance entirely. Under `LOST_MARGIN`, the base is the expected margin on the unfulfilled commitment: the unfulfilled gallons — the larger of zero and `committed_gallons` minus `fulfilled_gallons` — multiplied by `margin_tc_per_gal` and divided by ten, rounded half-up to integer cents; it ignores the allowance and the calendar. Second, the shortfall penalty: the same unfulfilled gallons multiplied by `shortfall_penalty_tc_per_gal` and divided by ten, rounded half-up to integer cents before any subtraction. Third, the net settlement: the base minus the penalty, floored at zero so the result is never negative. Before committing to either path, a `JobberAdmin` or `CreditManager` may read a computed buyout projection for the agreement, which returns the agreement's `method`, the method-selected `base_cents`, the `alternate_base_cents` computed under the other variant (so the divergence between the two methods is observable on one agreement), the `shortfall_penalty_cents`, and the `net_settlement_cents`.

An agreement under a default notice may be terminated: from `DEFAULT_NOTICE` a `JobberAdmin` moves it to `TERMINATED`, provided the station has no transport drops in `PLANNED`, `SCHEDULED`, or `EN_ROUTE` — open drops block the termination with `ERR_AGREEMENT_HAS_OPEN_DROPS`, forcing dispatch to be unwound before the agreement can be closed.

### 3.4. Brand Image Compliance and the Default Cascade

Branded dealers carry image obligations, audited by a `BrandInspector`. Recording an audit captures the `station_id`, the `audit_date` of the inspection, a `score` between 0 and 100 inclusive, and an optional `deficiencies` list of deficiency codes which defaults to an empty list. The audit's `result` is computed, not supplied: `PASS` when the score is at least 70, `FAIL` otherwise. Audits are immutable after recording and, like meter readings, carry only `id` and `created_at`.

Audit outcomes drive the station's compliance dimension. A `FAIL` recorded while the station is `COMPLIANT` moves it to `CURE_PERIOD` and stamps `cure_started_at` with the current logical clock instant. A `PASS` recorded while the station is in `CURE_PERIOD` restores it to `COMPLIANT` and clears `cure_started_at` to null. The cure window is 30 days: if the logical clock advances past `cure_started_at` plus 30 days without a passing audit, or if another `FAIL` is recorded while the station is already in `CURE_PERIOD`, the station falls into `DEFAULT`.

Falling into `DEFAULT` is the sharpest cascade in the system: at the same instant, every supply agreement of the station that is in `ACTIVE` moves to `DEFAULT_NOTICE`, and `cure_started_at` is cleared. From there the only agreement exits are termination (subject to the open-drops gate of §3.3) or, for the station, permanent `DEFAULT`, which is terminal for the compliance dimension. Renewal is also blocked while a station sits in `CURE_PERIOD` or `DEFAULT`, per §3.3.

### 3.5. Rack Price Postings and Daily Price Governance

The `PricingDesk` publishes the jobber's rack prices as postings. Creating a posting captures the `terminal_code`, the `product_id`, the `effective_date` on which the price takes effect, and the `price_tc_per_gal`, which must be greater than zero. A posting's `effective_date` may not be earlier than the current clock date at creation — back-dated prices are rejected with `ERR_EFFECTIVE_DATE_IN_PAST` (HTTP 422). New postings are `DRAFT`.

Posting a draft moves it to `POSTED` and makes it visible to price resolution (§2.6). At most one posting may be `POSTED` for a given combination of `terminal_code`, `product_id`, and `effective_date`: posting a draft when such a posting already exists is rejected with `ERR_PRICE_POSTING_CONFLICT`, and the correct path is supersession. Supersession retires a `POSTED` posting to `SUPERSEDED` and atomically creates its replacement: a brand-new posting in `POSTED` status for the same terminal, product, and effective date, priced at the request's `new_price_tc_per_gal`. The request must carry `expected_superseded_posting_version` per §2.8 — a stale base version fails with `ERR_STALE_VERSION` (HTTP 412) — and the request's `effective_date` must equal the superseded posting's own `effective_date`, failing `ERR_VALIDATION_FAILED` otherwise. The superseded posting's `version` increments by one as it retires; the replacement begins its own lifecycle. A draft that will never be posted may be discarded, moving it from `DRAFT` to `DISCARDED`; both `SUPERSEDED` and `DISCARDED` are terminal.

### 3.6. Transport Drops: Planning Gates and the Delivery Lifecycle

Drops are the physical fulfillment of the agreement. A `Dispatcher` plans a drop by supplying the `station_id`, the receiving `tank_id`, the `truck_id`, and the `product_id` — which must equal the product stored in the receiving tank — together with the `planned_gallons` (greater than zero) and a delivery window from `window_start` to `window_end`, the end strictly after the start. Planning is gated by a layered set of checks, applied in the pipeline order of §2.9:

- The station's `operating_status` must be `ACTIVE` — planning against an onboarding, suspended, or terminated station is rejected with `ERR_STATION_NOT_ACTIVE` — and the station must have a supply agreement in `ACTIVE` status, else `ERR_AGREEMENT_NOT_ACTIVE`.
- The `planned_gallons` must not exceed the truck's `capacity_gallons`, else `ERR_TRUCK_CAPACITY_EXCEEDED` (HTTP 422).
- The drop must respect the tank's safe-fill ceiling: `planned_gallons` plus the tank's current `physical_gallons` must not exceed the tank's `capacity_gallons` multiplied by its `safe_fill_pct` — a fill landing exactly on the ceiling is allowed — and a violation is rejected with `ERR_SAFE_FILL_EXCEEDED` (HTTP 422).
- The truck's schedule must stay coherent: among the truck's drops in `PLANNED`, `SCHEDULED`, or `EN_ROUTE`, the new half-open window — running from `window_start` up to but not including `window_end` — must not overlap any existing window; two windows that merely touch, one ending exactly when the other starts, are allowed. A true overlap is rejected with `ERR_TRUCK_WINDOW_CONFLICT` (HTTP 409).
- The receiving tank needs settle time: between any two drops into the same tank that are in `PLANNED`, `SCHEDULED`, or `EN_ROUTE`, the earlier window's end and the later window's start must be separated by at least 4 hours, else `ERR_TANK_SETTLE_WINDOW` (HTTP 409).
- Finally, the projected credit check of §2.10 extended forward: the station's `current_exposure_cents` plus this drop's `estimated_amount_cents` must not exceed `credit_limit_cents`, with equality allowed; a breach is rejected with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 422).

A planned drop is created in `PLANNED` with an `estimated_amount_cents` — the projected invoice total computed from `planned_gallons` and the current rack price (§2.6) at the current clock date, using the same three-component, per-component-rounded construction as a real invoice; when no posted price can be resolved the create fails with `ERR_PRICE_NOT_POSTED`. The drop also starts with `failure_count` 0 and null `delivered_gallons`, `delivered_at`, `invoice_id`, and `failure_reason`.

Execution walks a strict chain, each step performed by a `Dispatcher` and each requiring the exact from-state on pain of `ERR_INVALID_STATE`: scheduling moves `PLANNED` to `SCHEDULED`; dispatch moves `SCHEDULED` to `EN_ROUTE`. Delivery moves `EN_ROUTE` to `DELIVERED` and is the heaviest transition in the system. The request carries the actual `delivered_gallons`; the server stamps `delivered_at` with the current logical clock, then creates the drop's invoice in `ISSUED` status with `invoice_date` set to the clock date, priced at the `POSTED` posting for the drop's product at the station's `home_terminal_code` with the greatest `effective_date` on or before the delivery date (latest `created_at` breaking ties; none resolvable fails with `ERR_PRICE_NOT_POSTED`). The invoice's `fuel_amount_cents` is the delivered gallons multiplied by the applied `price_tc_per_gal`, divided by ten, rounded half-up; its `freight_amount_cents` is tiered — a flat 15000 cents (that is, $150.00) when the delivered gallons are at most 2000, 40 tenths-of-a-cent per gallon on all gallons when the delivery is between 2001 and 6000 gallons inclusive, and 32 tenths-of-a-cent per gallon on all gallons when the delivery exceeds 6000 gallons, with per-gallon tiers rounded half-up; its `tax_amount_cents` is the delivered gallons multiplied by the sum of the product's `federal_excise_tc_per_gal`, the station's `state_excise_tc_per_gal`, and the station's `local_option_tc_per_gal`, divided by ten, rounded half-up. Each component is rounded before they are summed into `total_cents`. The invoice's `due_date` is its `invoice_date` plus the station's `credit_terms_days`. Delivery then sets the drop's `invoice_id`, recomputes the station's `current_exposure_cents` to include the new invoice, and re-evaluates the station's credit band per §2.10.

Not every run reaches the rack. Failing a delivery moves `EN_ROUTE` to `DELIVERY_FAILED`, recording the supplied `reason` in `failure_reason` and incrementing `failure_count` by one. A failed drop can be replanned back to `PLANNED`: the replan request carries `expected_drop_version` per §2.8 (stale values rejected with `ERR_STALE_VERSION`, HTTP 412) plus a fresh `window_start`, `window_end`, and `truck_id`, which replace the prior values. Replanning re-runs the full planning gates — truck capacity, truck window conflict, tank settle buffer, safe fill, and the projected credit check — with the same error identifiers as creation, and recomputes `estimated_amount_cents` against the current posted price. A drop still in `PLANNED` or `SCHEDULED` may instead be cancelled outright into `CANCELLED`, which is terminal.

The last step is reconciliation: a delivered drop moves from `DELIVERED` to `RECONCILED`, folding the delivery into the station's inventory truth. Reconciliation cascades in four hops. First, the receiving tank's `book_inventory_gallons` is recomputed to include the drop's `delivered_gallons`. Second, any inventory reconciliation for the station in `OPEN` or `VARIANCE_FLAGGED` recomputes its book, physical, and variance figures. Third, that reconciliation flips between `OPEN` and `VARIANCE_FLAGGED` as its net variance crosses the threshold in either direction. Fourth, on every transition into `VARIANCE_FLAGGED`, an automatic shrinkage loss event is created, as detailed in §3.7.

### 3.7. Gauging, Metering, Losses, and Inventory Reconciliation

Physical truth enters the system through the dealer. A `DealerOperator` records a tank gauge by submitting `reading_gallons` and `observed_temp_f`; the gauge replaces the tank's `physical_gallons` and `physical_temp_f` (the latter null until the first gauge reading), increments the tank's `version`, and triggers a recompute of any open reconciliation for the station, including the variance flip and automatic loss creation described below. A tank is commissioned by a `JobberAdmin` with its `station_id`, `product_id`, `capacity_gallons` (greater than zero), and `opening_physical_gallons` (at least zero), which seeds both physical and book inventory; the optional `safe_fill_pct` defaults to 0.95 and must be greater than 0 and at most 1.

Dealers also submit meter readings with the `tank_id`, the `reading_at` instant the totalizer was read, and the cumulative `totalizer_gallons` (at least zero). Each reading's `metered_gallons` is the totalizer minus the chronological predecessor's totalizer for the same tank — readings are ordered by `reading_at` ascending with `created_at` ascending breaking ties — and zero for the tank's first reading. An out-of-order insert recomputes both its own delta and its chronological successor's delta, and a reading whose totalizer falls below its chronological predecessor's or above its chronological successor's is rejected with `ERR_METER_READING_REGRESSION` (HTTP 422). Every accepted reading recomputes the tank's book and any open reconciliation. Readings are immutable once recorded.

The tank's `book_inventory_gallons` is always derived, never written: the `opening_physical_gallons`, plus the `delivered_gallons` of every `RECONCILED` drop into the tank, minus the `metered_gallons` of all of the tank's meter readings, minus the `gallons` of the tank's loss events in `VERIFIED` or `WRITTEN_OFF`. Only tank-level losses — those with a `tank_id` — touch a tank's book; station-level losses such as drive-offs leave every tank's book untouched while still appearing in loss reports.

Loss events themselves are reported by the station's `DealerOperator` with a `station_id`, an optional `tank_id` (null for station-level events), a `loss_type` of `DRIVE_OFF`, `SHRINKAGE`, `SPILL`, or `THEFT`, the lost `gallons` (greater than zero), and the `occurred_at` instant. Manually reported events begin in `REPORTED` with `auto_generated` false and a null `reconciliation_id`. The dealer may dispute a `REPORTED` event for their own station — ownership is enforced, with `ERR_STATION_OWNERSHIP_MISMATCH` (HTTP 403) for another station's event — moving it to `DISPUTED`. Adjudication belongs to the `JobberAdmin`: verification moves an event from `REPORTED` or `DISPUTED` to `VERIFIED`, deducting its gallons from the tank's book when a `tank_id` is present and recomputing the station's open reconciliation; write-off moves a `VERIFIED` event to the terminal `WRITTEN_OFF`; voiding moves a `VERIFIED` event to the terminal `VOIDED` as the compensating action, restoring the deducted gallons to the tank's book and recomputing the open reconciliation again.

Reconciliation is where book meets physical. A `JobberAdmin` opens an `InventoryReconciliation` for a station and period by supplying `station_id`, an inclusive `period_start` and `period_end` (the end on or after the start), and an optional `threshold_gallons` that defaults to 130 and must be greater than zero. The opener's identity is recorded in `opener_user_id`, and a station may have only one reconciliation in `OPEN` or `VARIANCE_FLAGGED` at a time — opening a second is rejected with `ERR_RECONCILIATION_OPEN_EXISTS`. On creation and on every recompute, the reconciliation maintains `book_gallons` (the sum of `book_inventory_gallons` over the station's tanks), `physical_gross_gallons` (the sum of `physical_gallons` over those tanks), and two variance figures. The gross figure, `variance_gross_gallons`, is physical gross minus book — reported but never used for flagging. The net figure, `variance_net_gallons`, is temperature-corrected: for each tank, the physical gallons are multiplied by one plus the product's `temp_coeff` times the difference between the tank's `physical_temp_f` and the 60-degree reference (tanks never gauged use 60), each tank's corrected figure is rounded half-up to whole gallons, and the corrected sum minus `book_gallons` is the net variance. Gross and net diverge whenever an observed temperature differs from 60 degrees.

Flagging uses only the net figure: the reconciliation is `VARIANCE_FLAGGED` when the absolute value of `variance_net_gallons` is strictly greater than `threshold_gallons`, and `OPEN` otherwise — a net variance exactly equal to the threshold stays `OPEN`. A reconciliation may therefore open directly in `VARIANCE_FLAGGED`. Every transition into `VARIANCE_FLAGGED` — at creation or on any later recompute — automatically creates a loss event with `loss_type` `SHRINKAGE`, status `REPORTED`, `auto_generated` true, the triggering reconciliation's id in `reconciliation_id`, and `gallons` equal to the absolute value of the net variance rounded half-up to whole gallons. Transitions back to `OPEN` create nothing.

Resolution closes the loop and enforces segregation of duties. A `JobberAdmin` resolves a reconciliation from either `OPEN` or `VARIANCE_FLAGGED` by supplying a `resolution_note`; the resolver's `X-User-ID` must differ from `opener_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), and every loss event linked through `reconciliation_id` must already be `WRITTEN_OFF` or `VOIDED`, else `ERR_LINKED_LOSS_NOT_WRITTEN_OFF`. Resolution records the acting user in `resolver_user_id` and stores the note in `resolution_note` — both null until that moment — and moves the reconciliation to the terminal `RESOLVED` state.

### 3.8. Invoicing, EFT Settlement, and Fuel Tax Remittance

Invoices are born at delivery and nowhere else; each carries the `station_id`, the `drop_id` it was created from (one invoice per drop), the `product_id`, the `gallons_delivered`, and the applied `price_tc_per_gal`, alongside the computed `fuel_amount_cents`, `freight_amount_cents`, `tax_amount_cents`, and `total_cents` of §3.6. An invoice ages automatically: when the logical clock advances past its `due_date`, an `ISSUED` invoice becomes `OVERDUE`. Payment arrives through EFT; correction arrives through voiding. A `CreditManager` may void an invoice in `ISSUED` or `OVERDUE`, moving it to `VOID`: the station's `current_exposure_cents` is recomputed to remove the invoice, the credit band is re-evaluated, and any draft still `SCHEDULED` for that invoice is cancelled to `CANCELLED` in the same request.

EFT drafts are the collection instrument. A `CreditManager` schedules a draft against an `ISSUED` or `OVERDUE` invoice by supplying the `invoice_id` and a `scheduled_date`; the draft snapshots the invoice's `total_cents` into its `amount_cents` at schedule time and copies the `station_id` from the invoice, starting in `SCHEDULED` with `attempts` at 0. An invoice may have at most one `SCHEDULED` draft — a second attempt is rejected with `ERR_DRAFT_ALREADY_SCHEDULED`. Execution is also a `CreditManager` action and carries an `outcome`. The draft must be `SCHEDULED` (else `ERR_INVALID_STATE`) and the current clock date must be on or after its `scheduled_date` (else `ERR_DRAFT_NOT_EXECUTABLE`, HTTP 409). Either terminal outcome increments `attempts` by one. When the outcome is `SUCCEEDED`, the draft becomes `SETTLED`, the invoice moves from `ISSUED` or `OVERDUE` to `PAID`, the station's exposure is recomputed to remove the settled invoice, and the credit band is re-evaluated. When the outcome is `FAILED`, the draft becomes `FAILED`, the invoice remains `ISSUED` or `OVERDUE` with exposure unchanged, and the station's `credit_status` is driven to `HOLD` regardless of which band it occupied. A failed draft may be retried: the retry supplies a new `scheduled_date`, returning the draft to `SCHEDULED`. A draft still `SCHEDULED` may be cancelled to `CANCELLED`, whether directly by a `CreditManager` or automatically when its invoice is voided.

Exiting `HOLD` requires an explicit credit restoration by a `CreditManager`: it is permitted only from `HOLD` (else `ERR_INVALID_STATE`), and it applies the exposure band of §2.10 — landing the station in `GOOD_STANDING` when exposure is below 80 percent of the limit, or in `WATCH` when exposure has reached that line.

Fuel tax remittance closes the fiscal loop. A `TaxAccountant` opens a remittance for a jurisdiction by supplying the `state_code` and an inclusive `period_start` and `period_end`; the remittance begins in `ACCRUING` with a `due_date` of `period_end` plus 20 days. A state may not have two remittances whose periods overlap — overlap is judged on closed intervals and against existing remittances in any status — and a conflicting create is rejected with `ERR_TAX_PERIOD_ALREADY_FILED`. Filing the remittance computes its contents: the included invoices are those of stations whose `state_code` matches the remittance, in `ISSUED`, `OVERDUE`, or `PAID` status (voided invoices are excluded), with `invoice_date` falling within the period, both ends inclusive. `gasoline_gallons` is the sum of `gallons_delivered` over included invoices whose product category is `GASOLINE`, and `diesel_gallons` likewise for `DIESEL`. The `tax_amount_cents` is computed per category line — the line's gallons multiplied by the station's `state_excise_tc_per_gal`, divided by ten, rounded half-up to integer cents — and the remittance total is the sum of the rounded lines; the rounding order is pinned, per line first and then summed, because summing first and rounding once yields a different figure. When the clock date at filing is after the `due_date`, a `late_penalty_cents` of five percent of `tax_amount_cents`, rounded half-up, is added; on time it is 0. The `total_due_cents` is the tax plus the penalty. Filing stamps `filed_at` — null until that moment — with the current logical clock instant and moves the remittance to `FILED`; payment by a `TaxAccountant` moves it to the terminal `PAID`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify or transition an existing resource return `200 OK`. Error responses use the status codes catalogued in §5 and follow the error envelope of §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/products` | Create product | JobberAdmin |
| GET | `/api/products` | List products | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/dealer-stations` | Create dealer station (ONBOARDING, GOOD_STANDING, COMPLIANT, exposure 0) | JobberAdmin |
| GET | `/api/dealer-stations` | List stations | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/dealer-stations/{id}` | Get station (exposure, parallel statuses) | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| PATCH | `/api/dealer-stations/{id}` | Update credit terms | CreditManager |
| POST | `/api/dealer-stations/{id}/activate` | ONBOARDING to ACTIVE | JobberAdmin |
| POST | `/api/dealer-stations/{id}/suspend` | ACTIVE to SUSPENDED | JobberAdmin |
| POST | `/api/dealer-stations/{id}/reactivate` | SUSPENDED to ACTIVE | JobberAdmin |
| POST | `/api/dealer-stations/{id}/terminate` | ACTIVE/SUSPENDED to TERMINATED (all agreements terminal) | JobberAdmin |
| POST | `/api/dealer-stations/{id}/restore-credit` | Credit HOLD to GOOD_STANDING/WATCH per band | CreditManager |
| POST | `/api/supply-agreements` | Create agreement (DRAFT) | JobberAdmin |
| GET | `/api/supply-agreements` | List agreements | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/supply-agreements/{id}` | Get agreement (incl. fulfilled_gallons computed on read) | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| PATCH | `/api/supply-agreements/{id}` | Amend terms (OCC guarded; DRAFT or ACTIVE only) | JobberAdmin |
| POST | `/api/supply-agreements/{id}/activate` | DRAFT to ACTIVE | JobberAdmin |
| POST | `/api/supply-agreements/{id}/start-renewal` | ACTIVE to RENEWAL_PENDING (within renewal window) | JobberAdmin |
| POST | `/api/supply-agreements/{id}/renew` | RENEWAL_PENDING to ACTIVE with new term; fulfillment incentive | JobberAdmin |
| POST | `/api/supply-agreements/{id}/terminate` | DEFAULT_NOTICE to TERMINATED | JobberAdmin |
| GET | `/api/supply-agreements/{id}/buyout-quote` | Computed buyout projection (both base variants plus netting) | JobberAdmin, CreditManager |
| POST | `/api/supply-agreements/{id}/initiate-buyout` | ACTIVE to BUYOUT_PENDING | JobberAdmin |
| POST | `/api/supply-agreements/{id}/execute-buyout` | BUYOUT_PENDING to BOUGHT_OUT; records buyout_settlement_cents | JobberAdmin |
| POST | `/api/supply-agreements/{id}/cancel-buyout` | BUYOUT_PENDING to ACTIVE | JobberAdmin |
| POST | `/api/rack-price-postings` | Create posting (DRAFT); effective_date must not precede clock date | PricingDesk |
| GET | `/api/rack-price-postings` | List postings | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/rack-price-postings/{id}` | Get posting | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/rack-price-postings/{id}/post` | DRAFT to POSTED; conflicts with existing POSTED for same triple | PricingDesk |
| POST | `/api/rack-price-postings/{id}/supersede` | POSTED to SUPERSEDED, atomically creating replacement POSTED posting (OCC guarded) | PricingDesk |
| POST | `/api/rack-price-postings/{id}/discard` | DRAFT to DISCARDED | PricingDesk |
| POST | `/api/storage-tanks` | Create tank (physical equals book equals opening) | JobberAdmin |
| GET | `/api/storage-tanks` | List tanks | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/storage-tanks/{id}` | Get tank (physical, book) | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/storage-tanks/{id}/gauge` | Record physical gauge reading (sets physical_gallons, physical_temp_f; reconciliation recompute) | DealerOperator |
| POST | `/api/trucks` | Create truck | JobberAdmin |
| GET | `/api/trucks` | List trucks | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/transport-drops` | Create drop (PLANNED) with safety/temporal/credit gates; computes estimated_amount_cents | Dispatcher |
| GET | `/api/transport-drops` | List drops | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/transport-drops/{id}` | Get drop | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/transport-drops/{id}/schedule` | PLANNED to SCHEDULED | Dispatcher |
| POST | `/api/transport-drops/{id}/dispatch` | SCHEDULED to EN_ROUTE | Dispatcher |
| POST | `/api/transport-drops/{id}/deliver` | EN_ROUTE to DELIVERED; creates ISSUED invoice; exposure and credit band recompute | Dispatcher |
| POST | `/api/transport-drops/{id}/fail` | EN_ROUTE to DELIVERY_FAILED | Dispatcher |
| POST | `/api/transport-drops/{id}/replan` | DELIVERY_FAILED to PLANNED with new window/truck (OCC guarded; re-runs gates) | Dispatcher |
| POST | `/api/transport-drops/{id}/reconcile` | DELIVERED to RECONCILED; tank book recompute; open reconciliation cascade | Dispatcher |
| POST | `/api/transport-drops/{id}/cancel` | PLANNED/SCHEDULED to CANCELLED | Dispatcher |
| POST | `/api/meter-readings` | Submit totalizer reading (delta vs chronological predecessor; out-of-order recompute) | DealerOperator |
| GET | `/api/meter-readings` | List readings (sorted reading_at then created_at, ascending) | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/meter-readings/{id}` | Get reading | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/loss-events` | Report loss/drive-off (REPORTED) | DealerOperator |
| GET | `/api/loss-events` | List loss events | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/loss-events/{id}` | Get loss event | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/loss-events/{id}/verify` | REPORTED/DISPUTED to VERIFIED (deducts from tank book) | JobberAdmin |
| POST | `/api/loss-events/{id}/dispute` | REPORTED to DISPUTED (dealer, own station only) | DealerOperator |
| POST | `/api/loss-events/{id}/write-off` | VERIFIED to WRITTEN_OFF | JobberAdmin |
| POST | `/api/loss-events/{id}/void` | VERIFIED to VOIDED (restores tank book) | JobberAdmin |
| POST | `/api/inventory-reconciliations` | Open reconciliation for station and period; computes book/physical/variance; may open directly flagged | JobberAdmin |
| GET | `/api/inventory-reconciliations` | List reconciliations | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/inventory-reconciliations/{id}` | Get reconciliation | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/inventory-reconciliations/{id}/resolve` | OPEN/VARIANCE_FLAGGED to RESOLVED (resolver differs from opener; linked losses settled) | JobberAdmin |
| GET | `/api/invoices` | List invoices | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/invoices/{id}` | Get invoice | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/invoices/{id}/void` | ISSUED/OVERDUE to VOID (exposure compensation; cancels SCHEDULED drafts) | CreditManager |
| POST | `/api/eft-drafts` | Schedule EFT draft for an ISSUED/OVERDUE invoice (amount snapshot) | CreditManager |
| GET | `/api/eft-drafts` | List drafts | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/eft-drafts/{id}` | Get draft | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/eft-drafts/{id}/execute` | Execute scheduled draft; SUCCEEDED settles, FAILED holds credit | CreditManager |
| POST | `/api/eft-drafts/{id}/retry` | FAILED to SCHEDULED with new date | CreditManager |
| POST | `/api/eft-drafts/{id}/cancel` | SCHEDULED to CANCELLED | CreditManager |
| POST | `/api/tax-remittances` | Open remittance for state and period (ACCRUING); due_date is period_end plus 20 days | TaxAccountant |
| GET | `/api/tax-remittances` | List remittances | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/tax-remittances/{id}` | Get remittance | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/tax-remittances/{id}/file` | ACCRUING to FILED; computes gallons by category, per-line rounded tax, late penalty | TaxAccountant |
| POST | `/api/tax-remittances/{id}/pay` | FILED to PAID | TaxAccountant |
| POST | `/api/brand-compliance-audits` | Record audit; result is PASS at score 70 or higher; drives compliance dimension and DEFAULT cascade | BrandInspector |
| GET | `/api/brand-compliance-audits` | List audits | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| GET | `/api/brand-compliance-audits/{id}` | Get audit | JobberAdmin, PricingDesk, Dispatcher, CreditManager, TaxAccountant, BrandInspector, DealerOperator |
| POST | `/api/_clock/set_current_utc` | Set the logical clock (startup default 2026-05-01T00:00:00Z); evaluates time-based auto-transitions | JobberAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_STATION_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_VALIDATION_FAILED` | 400 Bad Request |
| `ERR_PRODUCT_NOT_FOUND` | 404 Not Found |
| `ERR_DEALER_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_SUPPLY_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_RACK_PRICE_POSTING_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_TANK_NOT_FOUND` | 404 Not Found |
| `ERR_TRUCK_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSPORT_DROP_NOT_FOUND` | 404 Not Found |
| `ERR_METER_READING_NOT_FOUND` | 404 Not Found |
| `ERR_LOSS_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVENTORY_RECONCILIATION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_EFT_DRAFT_NOT_FOUND` | 404 Not Found |
| `ERR_TAX_REMITTANCE_NOT_FOUND` | 404 Not Found |
| `ERR_BRAND_AUDIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STATION_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SAFE_FILL_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRUCK_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TRUCK_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_TANK_SETTLE_WINDOW` | 409 Conflict |
| `ERR_PRICE_POSTING_CONFLICT` | 409 Conflict |
| `ERR_PRICE_NOT_POSTED` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_TAX_PERIOD_ALREADY_FILED` | 409 Conflict |
| `ERR_RECONCILIATION_OPEN_EXISTS` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_RENEWAL_WINDOW_NOT_OPEN` | 409 Conflict |
| `ERR_CURE_PERIOD_ACTIVE` | 409 Conflict |
| `ERR_OVERDUE_INVOICES_EXIST` | 409 Conflict |
| `ERR_METER_READING_REGRESSION` | 422 Unprocessable Entity |
| `ERR_DRAFT_NOT_EXECUTABLE` | 409 Conflict |
| `ERR_DRAFT_ALREADY_SCHEDULED` | 409 Conflict |
| `ERR_LINKED_LOSS_NOT_WRITTEN_OFF` | 409 Conflict |
| `ERR_AGREEMENT_HAS_OPEN_DROPS` | 409 Conflict |

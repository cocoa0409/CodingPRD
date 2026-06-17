# RV Sales & Service API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the RV Sales & Service platform, a multi-tenant back-office system that unifies the two halves of a recreational-vehicle dealership: the showroom floor and the service drive. On the sales side, the platform tracks unit inventory across dealer-owned stock and third-party consignment, drives the negotiation-to-delivery pipeline (quoting, trade-in appraisal and lien payoff, financing, pre-delivery inspection, and the delivery walkthrough), and settles consignor proceeds at the moment of sale. On the service side, it manages repair-bay scheduling, parts stock and reservations, warranty and extended-plan claims, seasonal storage and winterization, and manufacturer recall campaigns with their per-unit remedies.

The platform exists because a dealership's sales desk and service department continually contend for the same physical and financial resources — a single coach is simultaneously a sellable unit, a candidate for storage, and a recall target, while a repair bay is a finite slot that both PDI walkthroughs and customer repairs compete for. The system therefore treats every consequential action as a guarded state transition with deterministic, immediately-consistent side effects: holds placed on units, parts decremented from stock, warranty caps consumed, and recall flags cleared all propagate the instant the triggering operation succeeds. To keep test scenarios reproducible, each dealership carries its own deterministic clock that advances only through an explicit administrative call rather than wall-clock time.

A central design tension this document addresses is the dual-variant nature of the dealership's money math. Trade-in equity is computed one way for the buyer's contract and another way for the dealer's margin book; a service order's total splits differently depending on whether the customer or a warranty plan pays. These distinctions, along with the precise ordering of tax, financing, and rounding steps, are spelled out in the business-logic sections that follow.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, conventions, and contracts that apply across every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting principal, and `X-User-Role` declares the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_AUTH`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `DealerManager`, `SalesAgent`, `ServiceAdvisor`, and `Customer`. A `DealerManager` is the override and approval authority — responsible for dealership setup, the deterministic clock, financing approvals and declines, recall campaign management, deal delivery and cancellation, and warranty-plan cancellation. A `SalesAgent` owns the sales surface: customer intake, unit intake, deal creation, quoting, finance requests, trade appraisal, and delivery. A `ServiceAdvisor` owns the service surface: service bays, service orders, parts, appointments, storage, PDI inspections, and recall remediation. A `Customer` has self-service read access only and may never mutate any resource.

The three operator roles — `DealerManager`, `SalesAgent`, and `ServiceAdvisor` — each carry an **opaque** identity. For these roles, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity; the server may record it where a workflow demands provenance (for example, as `sales_agent_user_id` on a Deal, `advisor_user_id` on a ServiceOrder, or `technician_user_id` on a PdiInspection, each captured from the acting operator's `X-User-ID`), but it is never compared against any entity's `id`. The `Customer` role is **entity-backed**: when `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record, and any ownership check on a resource that references a customer compares that resource's customer foreign key to `X-User-ID`. Customers are limited to reading their own deals, units, warranty plans, storage slots, dealership, and customer records.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; if not provided it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Deterministic Clock

Every primary resource in the system — Dealership, Customer, Unit, Deal, PdiInspection, ServiceBay, ServiceOrder, PartItem, PartReservation, WarrantyPlan, Appointment, StorageSlot, RecallCampaign, and RecallRemedy — carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created. The `updated_at` field is an ISO 8601 UTC timestamp recording the most recent modification. The `version` field is an integer that begins at its initial value on creation and increments by one on every mutation of the resource; it is the basis for optimistic concurrency control described in §2.7. All fourteen entity types in this system carry `updated_at` and `version` in addition to `id` and `created_at`.

Time in this system does not follow wall-clock time. Each Dealership owns a `current_utc` field — its own deterministic clock — which is initialized to the Unix epoch, `1970-01-01T00:00:00.000Z`, when the dealership is created. The clock advances only when a `DealerManager` explicitly sets it, supplying the target dealership via `dealership_id` and the new instant via `to_iso8601`; the supplied instant is written verbatim to that dealership's `current_utc`. Wherever the system needs "now" — for example, when judging whether a warranty certification is effective, or when stamping deterministic behavior — it reads the relevant dealership's `current_utc` rather than the host machine's clock.

### 2.5. Tenancy and Referential Integrity

The Dealership is the tenant root. Every other resource carries a `dealership_id` that binds it to exactly one dealership, and uniqueness constraints are always scoped per dealership rather than globally. A Unit's `vin` must be unique within its dealership; a duplicate is rejected with `ERR_DUPLICATE_VIN`. A Customer's `email` must be unique within its dealership; a duplicate is rejected with `ERR_DUPLICATE_EMAIL`. A PartItem's `sku` must be unique within its dealership; a duplicate is rejected with `ERR_DUPLICATE_SKU`. A RecallCampaign's `campaign_code` must be unique within its dealership; a duplicate is rejected with `ERR_DUPLICATE_CAMPAIGN`.

Reference checks are performed before business rules and are evaluated left-to-right: the resource named by the URL path is resolved first, then any foreign-key targets named in the request body, in the order they appear. The first reference that cannot be resolved produces the corresponding not-found error — `ERR_DEALERSHIP_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_DEAL_NOT_FOUND`, `ERR_SERVICE_BAY_NOT_FOUND`, `ERR_SERVICE_ORDER_NOT_FOUND`, `ERR_PART_ITEM_NOT_FOUND`, `ERR_WARRANTY_PLAN_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_STORAGE_SLOT_NOT_FOUND`, or `ERR_RECALL_CAMPAIGN_NOT_FOUND` — each returned with HTTP 404, and no later reference or business rule is evaluated once one fails.

### 2.6. The Order of Validation

When several conditions could each reject a request, they are evaluated in a fixed priority so that the failure a client sees is deterministic. Authentication comes first: a missing or malformed `X-User-ID`/`X-User-Role` pair yields `ERR_MISSING_AUTH` (HTTP 401) before anything else. Authorization comes second: a well-authenticated but disallowed role yields `ERR_FORBIDDEN_ROLE` (HTTP 403). Existence checks come third, as described in §2.5, yielding the appropriate 404. Fourth comes the optimistic-concurrency check described in §2.7, so a client acting on a stale unit fails fast before any business logic runs. Fifth comes the state-legality check — confirming the target resource is in a status from which the requested transition is permitted — which surfaces as the relevant `ERR_*_BAD_STATE`, `ERR_*_TERMINAL`, `ERR_FINANCE_NOT_SETTLED`, or `ERR_PDI_NOT_PASSED` conflict (HTTP 409). Sixth come business-referential checks such as consignor consistency and warranty-plan coverage. Seventh comes the stop-sale recall safety check on delivery. Eighth and ninth come the temporal-overlap checks for bays and storage. Tenth comes the parts-availability check on reservations. Eleventh and twelfth come the fiscal checks — loan-to-value on finance approval and warranty-cap headroom on completion. Last, at the lowest priority, come the field-level input validations: missing or wrong-typed fields, negative amounts, invalid enums, an out-of-range finance term, a documentation fee over the cap, the per-dealership uniqueness violations, and an inverted or non-positive interval. These surface as `ERR_INVALID_REQUEST`, the various `ERR_DUPLICATE_*`, `ERR_DOC_FEE_OVER_CAP`, `ERR_INVALID_TERM`, `ERR_INVALID_INTERVAL`, or `ERR_INVALID_RELEASE_TIME`, all carrying HTTP 400 except the duplicates, which carry HTTP 409.

### 2.7. Optimistic Concurrency on Units

Two operations in the system create a new resource whose validity depends on the current posture of a Unit, and both are therefore guarded by optimistic concurrency control keyed on the unit's `version`.

The first is deal creation. A request to create a Deal must carry an `expected_unit_version` field whose value equals the target unit's current `version`. If another writer has advanced the unit's version since the client last read it — for instance by placing or releasing a hold on the same unit, which legitimately changes the unit's status and bumps its version — the create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412), preventing the client from superseding a hold it never observed.

The second is storage booking. A request to book a StorageSlot must likewise carry `expected_unit_version` matching the target unit's current `version`; if the unit's version has advanced since the client last read it, the booking is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412). In both cases the OCC check runs before the business rules so that a stale writer fails fast. No other endpoint in the system takes a version field; only deal creation and storage booking are version-guarded, and both guard against the unit's version rather than their own.

### 2.8. Derived-Field Reconciliation and Cascade Consistency

A defining property of this platform is that several fields are not written directly by clients but are continuously reconciled from the state of related records, and the system keeps them consistent immediately. A Unit's `status` and `active_hold_deal_id` are derived from whatever deal currently holds it; a PartItem's `qty_reserved` is the sum of quantities across that part's reservations still in `RESERVED` state, and its `qty_available` is its on-hand count minus that reserved figure and is never negative; a WarrantyPlan's `consumed_cents` is the running sum of warranty-covered amounts across the completed orders billed to it; and a Unit's `open_recall_count` is the number of non-cleared remedies attached to it for open campaigns. Whenever an operation changes the underlying facts, these derived figures are recomputed as part of the same operation, and any entity whose stored fields change has its `updated_at` refreshed and its `version` incremented. Cascades that touch a second entity — releasing a hold when a deal is cancelled, returning reserved parts to stock when an order is cancelled, exhausting a warranty plan when its cap is reached — each independently mutate the affected entity and bump that entity's own `version`.

### 2.9. Monetary Values, Rounding, and Precision

All monetary amounts in this system are stored and exchanged as integer cents; field names ending in `_cents` always denote whole-cent integers. Where a calculation introduces a fractional cent — most notably sales tax, the amortized monthly payment, labor cost, and consignment commission — the result is rounded to a whole number of cents using the **round half up** convention. Rounding is applied at the specific step each calculation designates and at no other; the business-logic sections pin the exact rounding point for each formula, because the order in which rounding and summation occur changes the result. Basis-point fields such as `sales_tax_rate_bps`, `consignment_fee_bps`, and `apr_bps` express rates in hundredths of a percent (for example, a value of 725 means 7.25%), and loan-to-value figures are likewise reasoned about in basis points.

### 2.10. Temporal Resources: Bays and Storage

Two kinds of resource occupy intervals of the deterministic timeline and must not be over-committed. Service-bay appointments occupy a bay for a half-open interval running from `start_utc` inclusive to `end_utc` exclusive, and each bay further imposes a mandatory idle `cleanup_buffer_minutes` appended after every appointment before the bay is free again. A new appointment is rejected with `ERR_BAY_DOUBLE_BOOKED` if its interval — taken together with the trailing cleanup buffer of any neighboring appointment — would overlap any other non-cancelled appointment on the same bay. Storage occupancy works on the same half-open principle but per unit and without any buffer: a new StorageSlot is rejected with `ERR_STORAGE_OVERLAP` if its `start_utc`-to-`end_utc` interval overlaps any other non-cancelled storage slot for the same unit, where a slot ending exactly when another begins does not count as an overlap. For both resources the supplied interval must be well-formed, with `end_utc` strictly later than `start_utc`; an inverted or empty interval is rejected with `ERR_INVALID_INTERVAL`.

## 3. Business Logic & Workflows

### 3.1. Dealership Setup and the Sales Catalog

A dealership is brought into existence by a `DealerManager`, who supplies the dealership `name`, its two-letter `state_code`, a flat `doc_fee_cents` charged on every sale, and the `sales_tax_rate_bps` applied to the taxable base of each deal. The documentation fee is capped: a `doc_fee_cents` outside the range from zero up to and including the system documentation-fee cap is rejected with `ERR_DOC_FEE_OVER_CAP`. On creation the dealership's deterministic clock, exposed as `current_utc`, is initialized to the Unix epoch and thereafter moves only by explicit administrative advance.

Customers are created against a dealership with a `full_name`, an `email` unique within that dealership, and an optional `credit_tier`. The credit tier is one of `PRIME`, `STANDARD`, or `SUBPRIME` and defaults to `STANDARD` when omitted; it later governs both the financing rate band and the maximum loan-to-value the dealership will approve. Customer intake may be performed by a `SalesAgent`, a `ServiceAdvisor`, or a `DealerManager`.

Units are the heart of inventory. A unit is created with a `vin` unique within the dealership, a `model_year` between 1990 and 2100, a `class_type` drawn from `CLASS_A`, `CLASS_B`, `CLASS_C`, `TRAVEL_TRAILER`, or `FIFTH_WHEEL`, a `list_price_cents` of zero or more, and an `acquisition` mode that defaults to `STOCK`. The acquisition mode distinguishes dealer-owned `STOCK`, third-party `CONSIGNMENT`, and units taken in on a deal as `TRADE_IN`. Consignment intake carries extra obligations: when `acquisition` is `CONSIGNMENT`, the request must supply the `consignor_customer_id` identifying the consignor, the `consignment_floor_cents` naming the minimum net the consignor must receive, and the `consignment_fee_bps` setting the dealer's commission as basis points of sale price; omitting any of these for a consignment unit is rejected with `ERR_CONSIGNOR_REQUIRED`. Conversely, supplying a `consignor_customer_id` on a unit that is not a consignment is rejected with `ERR_CONSIGNOR_NOT_ALLOWED`. A newly created unit begins life with `status` of `AVAILABLE` and a `version` per the common conventions, and its `active_hold_deal_id` is empty until a deal holds it. At creation the system also scans existing open recall campaigns whose target class and model year match this unit, creating a `PENDING` remedy for each and setting the unit's `open_recall_count` accordingly. The `trade_in_origin_unit_id` field is reserved for trade units and is populated only by the appraisal flow described in §3.3. Unit creation is reserved to a `SalesAgent` or a `DealerManager`; the consignment-return action below is reserved to a `ServiceAdvisor` or a `DealerManager`.

A consigned unit that the dealership decides not to sell can be handed back to its consignor. Returning a consignment moves the unit from `AVAILABLE` to the terminal `CONSIGNMENT_RETURNED` status and increments its `version`. The action is permitted only when the unit's `acquisition` is `CONSIGNMENT` — a non-consignment unit is rejected with `ERR_NOT_CONSIGNMENT` — and only when the unit's `status` is `AVAILABLE`; a unit that is not available is rejected with `ERR_UNIT_NOT_AVAILABLE`.

### 3.2. The Unit Posture: Holds, Sale, and Recall Exposure

A unit's `status` is a posture derived from the deals and consignment actions that touch it, moving through `AVAILABLE`, `HELD`, and `SOLD`, with `CONSIGNMENT_RETURNED` as an alternative terminal state for returned consignments; `SOLD` and `CONSIGNMENT_RETURNED` are both terminal. When a deal is created on a unit, the unit must be `AVAILABLE` — otherwise the creation is rejected with `ERR_UNIT_NOT_AVAILABLE` — and the unit transitions from `AVAILABLE` to `HELD`, its `active_hold_deal_id` is set to the new deal's identifier, and its `version` increments. Releasing that hold by cancelling the deal carries the unit from `HELD` back to `AVAILABLE`, clears `active_hold_deal_id`, and again increments `version`; this release happens only for the deal that actually holds the unit. Delivering the deal carries the unit from `HELD` to the terminal `SOLD` status and increments `version`.

A unit's recall exposure is tracked by `open_recall_count`, the number of remedies on the unit that are not yet `CLEARED` for a campaign that is still `OPEN`. This count is recomputed whenever a relevant fact changes — when a campaign is opened against units in scope, when a remedy is cleared during service, or when a campaign is closed — and it is consulted both at PDI time and at delivery time, as the sections below describe.

### 3.3. Quoting, Trade Appraisal, and the Money Math

A `SalesAgent` opens a deal by naming the `dealership_id`, the `unit_id` being sold, the `customer_id` buying it, the negotiated `sale_price_cents`, and the `expected_unit_version` that satisfies the concurrency guard of §2.7; the agent may also supply an initial `down_payment_cents` (defaulting to zero) and, if financing is anticipated, a `term_months`. A freshly created deal opens with `sale_status` of `DRAFT` and `finance_status` of `NONE`, captures the creating agent's identifier into `sales_agent_user_id`, and — as a side effect — places the unit hold described in §3.2. These two status dimensions evolve independently: `sale_status` walks the delivery pipeline while `finance_status` walks the financing track, and the two are described separately below.

Before a deal can be quoted, the agent may appraise a trade-in. Appraising a trade intakes a brand-new `TRADE_IN` unit for the deal and links it: the agent supplies the trade's `vin`, `model_year`, `class_type`, and `list_price_cents`, together with the gross `trade_allowance_cents` credited to the buyer and the optional `trade_payoff_cents` (the lien the dealer must remit) and `trade_recon_cost_cents` (the estimated reconditioning expense). The system creates the trade unit with `acquisition` of `TRADE_IN`, `status` of `AVAILABLE`, and a `trade_in_origin_unit_id` pointing back at the unit being sold on this deal, and it records the trade on the deal by setting `trade_unit_id` and copying the three trade amounts onto the deal's `trade_allowance_cents`, `trade_payoff_cents`, and `trade_recon_cost_cents`. Trade appraisal may be performed by a `SalesAgent` or a `DealerManager`.

Quoting the deal is the moment the buyer-facing math is computed. Quoting is permitted only while `sale_status` is `DRAFT`; an attempt from any other sale state is rejected with `ERR_DEAL_BAD_SALE_STATE`. Quoting advances `sale_status` from `DRAFT` to `QUOTED`, recomputes the deal's money fields, and — when no `term_months` was supplied so the deal is a cash purchase — moves `finance_status` from `NONE` to `CASH`. The computation proceeds in a pinned order. First the deal's applied trade equity is determined: when a trade is present, the buyer's credit, stored as `net_trade_equity_cents`, equals the `trade_allowance_cents` minus the `trade_payoff_cents`, and this figure may be negative; reconditioning cost is the dealer's risk and is deliberately **not** subtracted from the buyer's credit. When no trade unit is linked, `net_trade_equity_cents` is zero. In parallel the deal also records `dealer_book_equity_cents`, the dealer's margin view of the same trade, which equals the `trade_allowance_cents` minus the `trade_payoff_cents` minus the `trade_recon_cost_cents`; with no trade it too is zero. The two equity figures differ by exactly the reconditioning cost. Next the deal snapshots the dealership's documentation fee into its own `doc_fee_cents`. Then the taxable base is the `sale_price_cents` reduced by the applied `net_trade_equity_cents`, floored at zero so it never goes negative. The `tax_cents` is that taxable base multiplied by the `sales_tax_rate_bps` and divided by ten thousand, rounded half up to whole cents — and the documentation fee is never taxed. The gross amount due is the `sale_price_cents` plus the snapshotted `doc_fee_cents` plus the `tax_cents`. Finally the `amount_financed_cents` is the gross amount due reduced by the applied `net_trade_equity_cents` and by the `down_payment_cents`, floored at zero. A separate computed read exposes the two equity views side by side — the applied buyer credit versus the dealer-book equity — for margin analysis, and may be retrieved by a `SalesAgent` or a `DealerManager`.

### 3.4. The Financing Track

Financing rides a dimension independent of the sale pipeline. The `finance_status` starts at `NONE`; a cash quote moves it to `CASH`; and a request for financing moves it through `REQUESTED`, then to either `APPROVED` or `DECLINED`, with a revision loop back from `DECLINED` to `REQUESTED`. A `SalesAgent` requests financing, optionally supplying or reusing the `term_months`. Requesting finance requires a term within the inclusive range of 12 to 240 months — a term outside that range is rejected with `ERR_INVALID_TERM` — and is permitted only while `sale_status` is either `DRAFT` or `QUOTED`; from any other sale state the request is rejected with `ERR_DEAL_BAD_SALE_STATE`. A fresh request moves `finance_status` from `NONE` to `REQUESTED`. A resubmission after a decline moves `finance_status` from `DECLINED` back to `REQUESTED` and clears any previously set `apr_bps`; resubmission requires the deal currently to be `DECLINED` (otherwise `ERR_FINANCE_BAD_STATE`) and again requires `sale_status` to be `DRAFT` or `QUOTED`. This decline-to-request-to-approve loop is a true cycle on the financing axis and does not disturb where the sale pipeline stands.

A `DealerManager` renders the financing decision, supplying a `decision` of approve or decline. The decision is legal only while `finance_status` is `REQUESTED`; from any other finance state it is rejected with `ERR_FINANCE_BAD_STATE`. A decline moves `finance_status` from `REQUESTED` to `DECLINED`. An approval first enforces the loan-to-value guard and then computes the payment. The loan-to-value, expressed in basis points, is the `amount_financed_cents` multiplied by ten thousand and divided by the unit's `list_price_cents`; it must be less than or equal to the maximum permitted for the customer's credit tier, where the ceilings are 13000 basis points (130%) for `PRIME`, 12000 basis points (120%) for `STANDARD`, and 11000 basis points (110%) for `SUBPRIME`, and the comparison is inclusive at the ceiling. A loan-to-value above the tier ceiling is rejected with `ERR_LTV_EXCEEDED`. When the guard passes, the approval selects the APR for the customer's credit tier — 599 basis points for `PRIME`, 899 basis points for `STANDARD`, and 1499 basis points for `SUBPRIME` — and records it as `apr_bps`, computes the amortized `monthly_payment_cents`, and moves `finance_status` to `APPROVED`. The monthly payment uses standard amortization: with the financed principal taken as `amount_financed_cents`, the number of payments as `term_months`, and a monthly rate equal to the `apr_bps` divided by ten thousand and then by twelve, the payment is the principal times the monthly rate times the quantity one-plus-the-monthly-rate raised to the number of payments, divided by that same quantity-raised-to-the-number-of-payments minus one, with the final figure rounded half up to whole cents.

### 3.5. Pre-Delivery Inspection and the Walkthrough

Once a deal is quoted and its financing is settled, the sale pipeline advances toward delivery. Moving a deal into pre-delivery inspection requires `sale_status` to be `QUOTED` (otherwise `ERR_DEAL_BAD_SALE_STATE`) and requires the financing to be settled — that is, `finance_status` must be either `CASH` or `APPROVED`; a deal whose financing is not settled is rejected with `ERR_FINANCE_NOT_SETTLED`. Starting pre-delivery inspection advances `sale_status` from `QUOTED` to `PDI_PENDING`. This action belongs to the `SalesAgent`.

A `ServiceAdvisor` records the inspection itself, supplying the `dealership_id`, the `deal_id` under inspection, and the integer count of `defects_found` (zero or more); the system copies the inspected unit's identifier into the inspection's `unit_id` and captures the advisor's identifier into `technician_user_id`. The inspection's `result` is computed: it is `PASS` only when `defects_found` equals zero and the deal's unit has an `open_recall_count` of zero at the moment of inspection, and `FAIL` otherwise. A `FAIL` leaves the deal in `PDI_PENDING` for re-inspection. A `PASS` is the trigger that advances the deal: it requires `sale_status` to be `PDI_PENDING`, sets the deal's `pdi_passed` flag to true, and moves `sale_status` from `PDI_PENDING` to `WALKTHROUGH`.

Delivery is the act that completes the sale. Delivery requires `sale_status` to be `WALKTHROUGH` (otherwise `ERR_DEAL_BAD_SALE_STATE`), requires `pdi_passed` to be true (otherwise `ERR_PDI_NOT_PASSED`), and requires financing to be settled in `CASH` or `APPROVED` (otherwise `ERR_FINANCE_NOT_SETTLED`). Delivery is further gated by recall safety: if the unit falls under an open `STOP_SALE` recall campaign with a remedy that is not yet `CLEARED`, delivery is blocked with `ERR_STOP_SALE_RECALL_OPEN`. When all gates pass, delivery advances `sale_status` from `WALKTHROUGH` to the terminal `DELIVERED`, cascades the unit from `HELD` to `SOLD` with a `version` bump, and — when the sold unit's `acquisition` is `CONSIGNMENT` — settles the consignor proceeds described in §3.6. Any trade unit that was appraised onto the deal stays in `AVAILABLE` inventory with its `acquisition` remaining `TRADE_IN`. Delivery may be performed by a `SalesAgent` or a `DealerManager`.

Cancelling a deal is permitted from any non-terminal sale state — that is, while `sale_status` is `DRAFT`, `QUOTED`, `PDI_PENDING`, or `WALKTHROUGH` — and is rejected with `ERR_DEAL_TERMINAL` once the deal is already `DELIVERED` or `CANCELLED`. Cancellation moves `sale_status` to the terminal `CANCELLED` and releases the unit hold as a cascade: the unit goes from `HELD` back to `AVAILABLE`, its `active_hold_deal_id` is cleared, and its `version` increments. Any trade unit that was appraised onto the deal is left in `AVAILABLE` inventory so it can be appraised again on a future deal. Cancellation may be performed by a `SalesAgent` or a `DealerManager`.

### 3.6. Consignment Settlement at Delivery

When a consignment unit is delivered, the dealer's commission and the consignor's floor are settled in a waterfall. The commission is computed first, off the top, as the `sale_price_cents` multiplied by the unit's `consignment_fee_bps` and divided by ten thousand, rounded half up to whole cents. The consignor's net is then the `sale_price_cents` minus that commission. The floor is honored next: if the consignor's net would fall below the unit's `consignment_floor_cents`, the consignor's net is raised to exactly the floor and the commission is recomputed as the `sale_price_cents` minus the floor — a figure that may be negative, in which case the dealer absorbs the shortfall. The dealer's margin on the consignment is the `sale_price_cents` minus the consignor's net. This settlement is recorded as a side effect of delivering a consignment unit and never runs for stock or trade-in units.

### 3.7. The Service Drive: Orders, Parts, and Warranty

The service department revolves around the **ServiceOrder**, opened by a `ServiceAdvisor` (or a `DealerManager`) against a `unit_id` and the paying `customer_id`, with an estimate of `labor_hours` greater than zero and a `labor_rate_cents` per hour of zero or more. An order may be billed to a warranty plan rather than the customer: when `is_warranty` is true the request must name the `warranty_plan_id`, and that plan must cover the order's unit — a plan that does not cover the unit is rejected with `ERR_WARRANTY_UNIT_MISMATCH`. A new order opens in `OPEN` status and captures the opening advisor's identifier into `advisor_user_id`. The order's `parts_subtotal_cents`, `total_cents`, and `covered_cents` all begin at zero and are finalized only at completion.

The order moves through a lifecycle that is cyclic in its middle. Starting work advances it from `OPEN` to `IN_PROGRESS`. Awaiting parts moves it from `IN_PROGRESS` to `AWAITING_PARTS`, and resuming moves it from `AWAITING_PARTS` back to `IN_PROGRESS`; a single order may bounce between `IN_PROGRESS` and `AWAITING_PARTS` many times as parts arrive. Each of these transitions requires the order to be in the appropriate originating state and is otherwise rejected with `ERR_SO_BAD_STATE`. These lifecycle actions — start, await-parts, resume, and complete — belong to the `ServiceAdvisor`.

Parts are drawn from inventory by reservation. A **PartItem** is created by a `ServiceAdvisor` or `DealerManager` with a `sku` unique within the dealership, a `name`, a `unit_price_cents` of zero or more, and an opening `qty_on_hand` of zero or more; its `qty_reserved` starts at zero and its `qty_available` starts equal to its on-hand count. A `ServiceAdvisor` reserves parts against an order by naming the `service_order_id`, the `part_item_id`, and the `quantity` (at least one). The reservation quantity must not exceed the part's current `qty_available`; a shortfall is rejected with `ERR_INSUFFICIENT_PARTS`. A successful reservation opens in `RESERVED` status, snapshots the part's price into the reservation's `unit_price_cents`, and as a cascade raises the part's `qty_reserved` by the reserved quantity and recomputes its `qty_available`.

Completing an order is the settlement event for both parts and money, and it advances the order from `IN_PROGRESS` to the terminal `COMPLETED`; completion from any other state is rejected with `ERR_SO_BAD_STATE`. The completion request may name a `remediates_campaign_id`. At completion the system finalizes the totals. Labor cost is the `labor_hours` multiplied by the `labor_rate_cents`, rounded half up to whole cents — and this labor figure is rounded first, before anything is summed. The parts portion, stored as `parts_subtotal_cents`, is the exact-integer sum over the order's `RESERVED` reservations of each reservation's `quantity` times its snapshotted `unit_price_cents`. The gross is the rounded labor plus the exact parts subtotal. For a non-warranty order, `covered_cents` is zero and `total_cents` — the customer-owed amount — equals the gross. For a warranty order, the plan's remaining headroom is its `coverage_cap_cents` minus its `consumed_cents`; the coverable portion is the gross minus the plan's `deductible_cents`, floored at zero; `covered_cents` is the smaller of that coverable portion and the remaining headroom; and `total_cents` is the gross minus `covered_cents`. A warranty completion is rejected with `ERR_WARRANTY_CAP_EXCEEDED` when the coverable portion would exceed the remaining headroom. As cascades of a successful completion, every `RESERVED` reservation for the order becomes `FULFILLED` and each backing part has its `qty_on_hand` and `qty_reserved` both reduced by the fulfilled quantity; for a warranty order the plan's `consumed_cents` rises by the `covered_cents`, and if that brings the consumed total to or above the cap the plan automatically moves to `EXHAUSTED`; and when a `remediates_campaign_id` is supplied the matching pending remedy on the unit is moved from `PENDING` to `CLEARED` and the unit's `open_recall_count` is recomputed.

An order can also be cancelled from any non-terminal state — that is, while it is `OPEN`, `IN_PROGRESS`, or `AWAITING_PARTS` — and is rejected with `ERR_SO_TERMINAL` once it is already `COMPLETED` or `CANCELLED`. Cancellation moves the order to the terminal `CANCELLED` and triggers two cascades: every `RESERVED` reservation for the order is moved to `RELEASED`, returning its quantity to stock by lowering each backing part's `qty_reserved` and recomputing `qty_available`; and every `SCHEDULED` or `CHECKED_IN` appointment for the order is moved to `CANCELLED`, freeing the bay interval. Cancellation may be performed by a `ServiceAdvisor` or a `DealerManager`.

### 3.8. Warranty Plans

A **WarrantyPlan** is created by a `SalesAgent` or `DealerManager` for a specific `unit_id` and `customer_id`, with a `plan_kind` of either `FACTORY` or `EXTENDED`, a lifetime `coverage_cap_cents` of zero or more, and an optional per-claim `deductible_cents` (defaulting to zero) that the customer pays before coverage applies. A new plan opens in `ACTIVE` status with `consumed_cents` at zero. As warranty orders complete against the plan, its `consumed_cents` accumulates the covered amounts; the plan transitions automatically to `EXHAUSTED` the moment its `consumed_cents` reaches or exceeds its `coverage_cap_cents`. A `DealerManager` may cancel a plan, moving its `status` to `CANCELLED`.

### 3.9. Bay Scheduling: Appointments

Service bays are the finite slots that both repair work and pre-delivery walkthroughs draw on. A **ServiceBay** is created by a `ServiceAdvisor` or `DealerManager` with a `name`, a `bay_kind` of either `REPAIR` or `WASH_PDI`, and an optional `cleanup_buffer_minutes` (defaulting to zero) that is appended as idle time after each appointment. A `ServiceAdvisor` schedules an **Appointment** by naming the `dealership_id`, the `service_bay_id`, the `appt_kind`, and the `start_utc` and `end_utc` of the slot. A `REPAIR` appointment must reference a `service_order_id` and use a `REPAIR` bay, while a `PDI` appointment must reference a `deal_id` and use a `WASH_PDI` bay. The interval must be well-formed with `end_utc` strictly after `start_utc`, and the slot is subject to the bay-overlap rule of §2.10, which folds in the bay's cleanup buffer and rejects collisions with `ERR_BAY_DOUBLE_BOOKED`. A new appointment opens in `SCHEDULED` status.

An appointment walks a short lifecycle. Checking in advances it from `SCHEDULED` to `CHECKED_IN`, and closing advances it from `CHECKED_IN` to `CLOSED`; each transition requires the appropriate originating state and is otherwise rejected with `ERR_APPT_BAD_STATE`. Check-in and close belong to the `ServiceAdvisor`. An appointment may be cancelled from either `SCHEDULED` or `CHECKED_IN`, which moves it to the terminal `CANCELLED` and frees the bay interval for future overlap checks; cancelling an appointment that is already `CLOSED` or `CANCELLED` is rejected with `ERR_APPT_TERMINAL`. Cancellation may be performed by a `ServiceAdvisor` or a `DealerManager`.

### 3.10. Seasonal Storage and Winterization

Off-season coaches are kept in storage slots. A **StorageSlot** is booked by a `ServiceAdvisor` or `DealerManager` for a `unit_id` belonging to a storage `customer_id`, with a `daily_rate_cents` of zero or more, the term's `start_utc` and `end_utc`, an optional `winterized` flag (defaulting to false), and the `expected_unit_version` that satisfies the concurrency guard of §2.7. The term must be well-formed with `end_utc` strictly after `start_utc`, and it must not overlap another non-cancelled storage slot for the same unit per the storage-overlap rule of §2.10, which rejects collisions with `ERR_STORAGE_OVERLAP`. A successful booking opens in `BOOKED` status and bumps the unit's `version` as part of the concurrency-guarded write.

A storage slot is activated from `BOOKED` to `ACTIVE` when the unit physically arrives, an action reserved to the `ServiceAdvisor`. Releasing the slot is the billing event: it is permitted only from `ACTIVE` (otherwise `ERR_STORAGE_BAD_STATE`) and requires the supplied `released_on_utc` to be no earlier than the slot's `start_utc`; an earlier release time is rejected with `ERR_INVALID_RELEASE_TIME`. Release moves the slot from `ACTIVE` to the terminal `RELEASED` and computes the `billed_cents`. The charge counts whole days on a half-open basis: the elapsed time is the `released_on_utc` minus the `start_utc`, and the billed day count is the elapsed seconds divided by the number of seconds in a day and rounded up to the next whole day, with a minimum of one day so that even a same-day release bills a full day. The base charge is that day count multiplied by the `daily_rate_cents`, and when the slot is `winterized` a flat winterization fee of 25000 cents is added on top. A booked slot may instead be cancelled, which is permitted only from `BOOKED` (otherwise `ERR_STORAGE_BAD_STATE`), moves the slot to the terminal `CANCELLED`, and frees the storage interval for future overlap checks. Activation and release belong to the `ServiceAdvisor`; cancellation may be performed by a `ServiceAdvisor` or a `DealerManager`.

### 3.11. Recall Campaigns and Per-Unit Remedies

Manufacturer recalls are modeled as campaigns with per-unit remedies. A `DealerManager` opens a **RecallCampaign** with a `campaign_code` unique within the dealership, a `target_class_type` and `target_model_year` that define the units in scope, and a `severity` of either `STOP_SALE`, which blocks delivery, or `ADVISORY`, which does not. A new campaign opens in `OPEN` status. As a side effect of opening, the system creates a `PENDING` **RecallRemedy** for each existing unit whose class and model year match the campaign's target, recording the remedy's `recall_campaign_id` and `unit_id`, and increments each matched unit's `open_recall_count`. A remedy is cleared in the field by completing a service order that names the campaign as the one it remediates, which carries the remedy's `status` from `PENDING` to `CLEARED` and refreshes the affected unit's `open_recall_count`.

Closing a campaign moves it from `OPEN` to the terminal `CLOSED` and is reserved to the `DealerManager`. A campaign may be closed only while it is `OPEN` — a campaign that is not open is rejected with `ERR_RECALL_BAD_STATE` — and only when every remedy belonging to it is already `CLEARED`; outstanding non-cleared remedies block the close with `ERR_REMEDIES_OUTSTANDING`. Closing a campaign recomputes the `open_recall_count` of each unit it targeted, since a closed campaign no longer contributes to a unit's open-recall exposure.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including every state-transition action and the deterministic clock advance — return a `200 OK` status code. All list and single-read operations return `200 OK`. Authorization for each endpoint is enforced per the roles named below; reads marked for `Customer` are restricted to the customer's own records as described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set a dealership's deterministic clock | DealerManager |
| POST | `/dealerships` | Create a dealership (tenant root) | DealerManager |
| GET | `/dealerships` | List dealerships | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/dealerships/{dealershipId}` | Get a dealership | DealerManager, SalesAgent, ServiceAdvisor, Customer |
| POST | `/customers` | Create a customer | SalesAgent, ServiceAdvisor, DealerManager |
| GET | `/customers` | List/filter customers | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/customers/{customerId}` | Get a customer | DealerManager, SalesAgent, ServiceAdvisor, Customer |
| POST | `/units` | Create a unit (STOCK or CONSIGNMENT) | SalesAgent, DealerManager |
| GET | `/units` | List/filter units | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/units/{unitId}` | Get a unit | DealerManager, SalesAgent, ServiceAdvisor, Customer |
| POST | `/units/{unitId}/return-consignment` | Return a consigned unit to its consignor | ServiceAdvisor, DealerManager |
| POST | `/deals` | Create a deal, placing a hold on the unit | SalesAgent |
| GET | `/deals` | List/filter deals | DealerManager, SalesAgent |
| GET | `/deals/{dealId}` | Get a deal | DealerManager, SalesAgent, Customer |
| GET | `/deals/{dealId}/equity-summary` | Computed read: applied vs dealer-book equity | DealerManager, SalesAgent |
| POST | `/deals/{dealId}/quote` | Quote the deal: compute tax, financed amount, applied trade equity | SalesAgent |
| POST | `/deals/{dealId}/request-finance` | Request financing for the deal | SalesAgent |
| POST | `/deals/{dealId}/finance-decision` | Approve or decline financing | DealerManager |
| POST | `/deals/{dealId}/start-pdi` | Move a quoted, finance-settled deal into PDI_PENDING | SalesAgent |
| POST | `/deals/{dealId}/deliver` | Deliver the unit: complete the sale, settle consignment/trade | SalesAgent, DealerManager |
| POST | `/deals/{dealId}/cancel` | Cancel a non-delivered deal; release the unit hold | SalesAgent, DealerManager |
| POST | `/deals/{dealId}/appraise-trade` | Appraise and intake a trade-in unit for this deal | SalesAgent, DealerManager |
| POST | `/pdi-inspections` | Record a PDI inspection for a deal | ServiceAdvisor |
| GET | `/pdi-inspections` | List/filter PDI inspections | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/pdi-inspections/{pdiId}` | Get a PDI inspection | DealerManager, SalesAgent, ServiceAdvisor |
| POST | `/service-bays` | Create a service bay | ServiceAdvisor, DealerManager |
| GET | `/service-bays` | List service bays | DealerManager, ServiceAdvisor, SalesAgent |
| GET | `/service-bays/{bayId}` | Get a service bay | DealerManager, ServiceAdvisor, SalesAgent |
| POST | `/service-orders` | Open a service order | ServiceAdvisor, DealerManager |
| GET | `/service-orders` | List/filter service orders | DealerManager, ServiceAdvisor |
| GET | `/service-orders/{soId}` | Get a service order | DealerManager, ServiceAdvisor, Customer |
| POST | `/service-orders/{soId}/start` | Start work | ServiceAdvisor |
| POST | `/service-orders/{soId}/await-parts` | Pause work pending parts | ServiceAdvisor |
| POST | `/service-orders/{soId}/resume` | Resume work | ServiceAdvisor |
| POST | `/service-orders/{soId}/complete` | Complete the order; settle parts, totals, warranty, recall | ServiceAdvisor |
| POST | `/service-orders/{soId}/cancel` | Cancel the order; release parts and appointments | ServiceAdvisor, DealerManager |
| POST | `/part-reservations` | Reserve parts against an order | ServiceAdvisor |
| GET | `/part-reservations` | List/filter part reservations | DealerManager, ServiceAdvisor |
| GET | `/part-reservations/{resId}` | Get a part reservation | DealerManager, ServiceAdvisor |
| POST | `/part-items` | Create a part item | ServiceAdvisor, DealerManager |
| GET | `/part-items` | List part items | DealerManager, ServiceAdvisor |
| GET | `/part-items/{partId}` | Get a part item | DealerManager, ServiceAdvisor |
| POST | `/warranty-plans` | Create a warranty plan for a unit+customer | SalesAgent, DealerManager |
| GET | `/warranty-plans` | List/filter warranty plans | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/warranty-plans/{planId}` | Get a warranty plan | DealerManager, SalesAgent, ServiceAdvisor, Customer |
| POST | `/warranty-plans/{planId}/cancel` | Cancel a warranty plan | DealerManager |
| POST | `/appointments` | Schedule a bay appointment (REPAIR or PDI) | ServiceAdvisor |
| GET | `/appointments` | List/filter appointments | DealerManager, ServiceAdvisor |
| GET | `/appointments/{apptId}` | Get an appointment | DealerManager, ServiceAdvisor |
| POST | `/appointments/{apptId}/check-in` | Check in an appointment | ServiceAdvisor |
| POST | `/appointments/{apptId}/close` | Close an appointment | ServiceAdvisor |
| POST | `/appointments/{apptId}/cancel` | Cancel an appointment, freeing the bay interval | ServiceAdvisor, DealerManager |
| POST | `/storage-slots` | Book a storage slot for a unit | ServiceAdvisor, DealerManager |
| GET | `/storage-slots` | List/filter storage slots | DealerManager, ServiceAdvisor |
| GET | `/storage-slots/{slotId}` | Get a storage slot | DealerManager, ServiceAdvisor, Customer |
| POST | `/storage-slots/{slotId}/activate` | Activate a booked storage slot | ServiceAdvisor |
| POST | `/storage-slots/{slotId}/release` | Release an active storage slot, billing the term | ServiceAdvisor, DealerManager |
| POST | `/storage-slots/{slotId}/cancel` | Cancel a booked storage slot | ServiceAdvisor, DealerManager |
| POST | `/recall-campaigns` | Open a recall campaign; auto-create pending remedies | DealerManager |
| GET | `/recall-campaigns` | List/filter recall campaigns | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/recall-campaigns/{rcId}` | Get a recall campaign | DealerManager, SalesAgent, ServiceAdvisor |
| POST | `/recall-campaigns/{rcId}/close` | Close a campaign once all remedies cleared | DealerManager |
| GET | `/recall-remedies` | List/filter recall remedies | DealerManager, SalesAgent, ServiceAdvisor |
| GET | `/recall-remedies/{remedyId}` | Get a recall remedy | DealerManager, SalesAgent, ServiceAdvisor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_DEALERSHIP_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_DEAL_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_BAY_NOT_FOUND` | 404 Not Found |
| `ERR_SERVICE_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_WARRANTY_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_STORAGE_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_RECALL_CAMPAIGN_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_UNIT_VERSION` | 412 Precondition Failed |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_DEAL_BAD_SALE_STATE` | 409 Conflict |
| `ERR_DEAL_TERMINAL` | 409 Conflict |
| `ERR_FINANCE_BAD_STATE` | 409 Conflict |
| `ERR_FINANCE_NOT_SETTLED` | 409 Conflict |
| `ERR_PDI_NOT_PASSED` | 409 Conflict |
| `ERR_SO_BAD_STATE` | 409 Conflict |
| `ERR_SO_TERMINAL` | 409 Conflict |
| `ERR_APPT_BAD_STATE` | 409 Conflict |
| `ERR_APPT_TERMINAL` | 409 Conflict |
| `ERR_STORAGE_BAD_STATE` | 409 Conflict |
| `ERR_RECALL_BAD_STATE` | 409 Conflict |
| `ERR_REMEDIES_OUTSTANDING` | 409 Conflict |
| `ERR_NOT_CONSIGNMENT` | 409 Conflict |
| `ERR_CONSIGNOR_REQUIRED` | 409 Conflict |
| `ERR_CONSIGNOR_NOT_ALLOWED` | 409 Conflict |
| `ERR_WARRANTY_UNIT_MISMATCH` | 409 Conflict |
| `ERR_STOP_SALE_RECALL_OPEN` | 409 Conflict |
| `ERR_BAY_DOUBLE_BOOKED` | 409 Conflict |
| `ERR_STORAGE_OVERLAP` | 409 Conflict |
| `ERR_INSUFFICIENT_PARTS` | 409 Conflict |
| `ERR_LTV_EXCEEDED` | 402 Payment Required |
| `ERR_WARRANTY_CAP_EXCEEDED` | 402 Payment Required |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_INTERVAL` | 400 Bad Request |
| `ERR_INVALID_RELEASE_TIME` | 400 Bad Request |
| `ERR_INVALID_TERM` | 400 Bad Request |
| `ERR_DOC_FEE_OVER_CAP` | 400 Bad Request |
| `ERR_DUPLICATE_VIN` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_SKU` | 409 Conflict |
| `ERR_DUPLICATE_CAMPAIGN` | 409 Conflict |

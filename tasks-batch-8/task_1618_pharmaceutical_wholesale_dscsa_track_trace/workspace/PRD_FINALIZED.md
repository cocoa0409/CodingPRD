# Pharma Wholesale DSCSA Track-and-Trace API — Product Requirements Document

## 1. Introduction

Pharmaceutical wholesale distribution in the United States operates under the Drug Supply Chain Security Act (DSCSA), which obliges every trading partner to exchange transaction information and transaction history for each serialized package that changes hands, to verify the licensure of counterparties before product moves, and to quarantine and investigate suspect product rather than letting it flow further downstream. Layered on top of the compliance burden are the commercial realities of the wholesale business: customers buy on credit against negotiated limits, covered entities purchase under 340B contract pricing that must later be reconciled with manufacturers through chargebacks, returns generate credits that decay with time and storage class, and products in shortage must be rationed across competing customers under explicit fairness policies rather than first-come-first-served.

This document specifies the API for a wholesale distribution platform that implements those obligations end to end. It covers trading-partner onboarding and state-license management, serialized case and unit commissioning with EPCIS event capture, purchase-order processing with license verification and credit enforcement, shortage allocation, suspect-product investigation under segregation of duties, chargeback reconciliation, and returns crediting. All resources are mounted under the `/wholesale` path prefix, with a single test-driving capability mounted outside it. The audience is the engineering team building the service; every rule stated here is normative.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, representations, and cross-cutting disciplines that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which that operator acts. The system recognizes exactly six roles, spelled precisely as follows: `OrderManager` (the customer-service and order desk — trading partners, products, orders, allocation policies, return requests and rejections), `ComplianceOfficer` (licensing and regulatory compliance — the state-license lifecycle), `WarehouseOperator` (the distribution-center floor — serialization, EPCIS capture, shipping, delivery, and returns receipt), `QualityAssuranceLead` (quality — suspect investigations, quarantine, release, and illegitimacy confirmation), `BillingClerk` (finance — payments against invoices and return credit issuance), and `ContractAdministrator` (contracts — the 340B chargeback claim lifecycle). A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose declared role is not permitted to invoke the target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403); the permission matrix itself is given by the Authorized Role(s) column of §4.

All six roles use opaque operator identities. When `X-User-Role` is `OrderManager`, when it is `ComplianceOfficer`, when it is `WarehouseOperator`, when it is `QualityAssuranceLead`, when it is `BillingClerk`, and when it is `ContractAdministrator`, `X-User-ID` is in every case an opaque operator identifier not tied to any persisted entity; the server never compares it against any resource's `id`. Exactly one field in the system records it: the quarantine action on a suspect investigation stamps `quarantined_by_user_id` with the caller's `X-User-ID`, and the segregation-of-duties checks on clearing or confirming that same investigation compare the new caller's header against the stored value (see §3.6).

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

List endpoints paginate through two query parameters. `limit` caps the number of items returned; when omitted it defaults to 10, and it accepts a minimum of 1 and a maximum of 100. `offset` skips that many items from the front of the result set and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity, Timestamps, and Version Semantics

Every primary resource — trading partners, state licenses, products, allocation policies, serialized cases, serialized units, purchase orders, order lines, suspect investigations, chargeback claims, and return authorizations — carries a standard set of system-managed properties:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits (for example, `2026-08-01T00:00:00.000Z`) indicating when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp in the same format, refreshed whenever the resource's properties change.
- `version` (integer): a system-managed counter that increments with every modification to the resource.

The `EpcisEvent` resource is the sole exception. As an immutable ledger entry it carries only `id` and `created_at`; both `updated_at` and `version` are absent from it entirely, because an event, once captured, is never modified.

State transitions and cascades described in §3 are mutations in this sense: wherever a transition's definition increments a resource's `version`, it does so by exactly one and refreshes `updated_at` — including cascaded mutations such as a quarantined case carrying its units with it, or a cancelled order releasing an allocation policy.

### 2.5. The Logical Clock

All temporal reasoning in the system — license validity windows, case expiry, EPCIS event admissibility, return windows, days-since-delivery — is evaluated against a server-side logical clock, never against real wall-clock time. Before any explicit setting, the logical clock reads exactly `2026-08-01T00:00:00Z`.

A test-driving capability, available to all six roles, advances the clock to a supplied target instant carried in the `to_iso8601` field and responds with the resulting `current_utc`. Once set, the clock holds the supplied value until it is set again; it must never fall back to wall-clock time.

### 2.6. Monetary Amounts, Units, and Rounding Discipline

All monetary values are represented as integer cents — list prices, 340B contract prices, invoice totals and balances, open receivables, credit limits, chargeback amounts, payment amounts, and return credits alike. Invoice pricing, chargeback computation, and the receivable ledger involve only integer arithmetic, so no rounding ever occurs in them. Where a computation can produce fractional results — shortage-allocation grants and the return-credit amount — the result is rounded down (floor) to a whole unit or a whole cent respectively, and allocation division is floor division to whole units. No monetary value is ever represented with decimal places, and no round-half-up step exists anywhere in the system.

### 2.7. Optimistic Concurrency Control on Allocation

Exactly one write operation in the API participates in optimistic concurrency control: running shortage allocation against a purchase order. That request must carry `expected_order_version`, a non-optional input field holding the order `version` the caller last observed. If the supplied value does not equal the order's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated — this captures the case where another writer has already re-priced and re-allocated the same lines under the current shortage epoch, leaving the caller's view of the order stale. The version check is evaluated before any state precondition and before all business rules on that endpoint, so a stale write can never masquerade as a state or validation failure. No other endpoint accepts a version field; clients must not send one anywhere else.

### 2.8. Hierarchical Retrieval and Referenced-Resource Existence

Endpoints whose paths nest one resource beneath another — order lines beneath purchase orders, units beneath serialized cases — validate path identifiers strictly left to right. The request is rejected immediately with `ERR_NOT_FOUND` (HTTP 404) at the first path identifier that does not correspond to an existing resource, before later identifiers or the request body are examined. A request for the lines of a purchase order that does not exist therefore fails on the order identifier before line-level concerns are considered at all.

Identifiers referenced inside a request body are resolved after path validation: `customer_id`, `product_id`, `case_id`, `order_id`, and the partner identifiers supplied on event capture must each name an existing resource, and an unknown body reference is rejected with `ERR_REFERENCE_NOT_FOUND` (HTTP 404). Requests that are malformed, that omit a required field, or that carry a value of the wrong type are rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.9. The Validation Ladder

When several rules could condemn the same request, the server evaluates them in a fixed order and reports only the first failure. The ladder runs as follows:

1. Identity headers present and well-formed (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorized for the endpoint (`ERR_UNAUTHORIZED_ROLE`).
3. Path-template identifiers exist, validated left to right (`ERR_NOT_FOUND`).
4. Body-referenced identifiers exist (`ERR_REFERENCE_NOT_FOUND`).
5. The optimistic-concurrency version check, where the endpoint declares one (`ERR_STALE_VERSION`) — deliberately ahead of state preconditions and every business rule, so a stale write surfaces as a version conflict rather than being masked by a later check.
6. State-machine admissibility: the target resource must be in a state from which the requested transition exists. Transitions that nominate a specific error (for example, `ERR_ORDER_NOT_DRAFT`) surface it; otherwise the rejection is `ERR_INVALID_STATE` (HTTP 409).
7. The business-rule family, in its own fixed sequence: license verification; the suspect-stock shipping interdiction; segregation of duties on investigation disposition; temporal freshness (lot expiry and event-time admissibility); EPCIS event sequencing; segregation-mode coverage; uniqueness of natural keys; chargeback referential checks; return-quantity limits; the cold-chain return window; the customer credit limit; and payment-amount validity.

Sections §3.1 through §3.8 attach each of these rules to the workflow it guards.

## 3. Business Logic & Workflows

### 3.1. Trading Partners, State Licensing, and the Credit Foundation

An `OrderManager` onboards a counterparty by registering a trading partner with its legal `partner_name`, a `partner_kind` of exactly `CUSTOMER` or `SUPPLIER`, and a non-negative `credit_limit_cents` capping the open receivable the partner may carry. A `dea_number` — the partner's DEA registration number — is required whenever the partner will order controlled substances. Two computed counters start at zero on every new partner. The first, `open_receivable_cents`, equals at any moment the sum of outstanding invoice balances across that partner's orders whose financial status is `INVOICED` or `PARTIALLY_PAID`; it is the single figure every credit decision in the system consults. The second, `allocation_watermark_units`, is a rolling historical-usage watermark consulted for shortage-allocation fairness and maintained per product through the allocation-policy machinery.

State licensure is managed separately, because it answers to regulators rather than to the order desk. A `ComplianceOfficer` registers each state license with the licensed `partner_id`, the two-letter `state_code`, the state-issued `license_number`, a `license_scope`, and the validity window `valid_from` through `valid_to`. The scope is one of `RX_ONLY`, `RX_AND_CONTROLLED`, `RX_AND_COLD_CHAIN`, or `FULL`. Both bounds are inclusive ISO 8601 instants, and `valid_to` must be strictly after `valid_from`. A new license's `license_status` begins `ACTIVE`.

From `ACTIVE`, a license can be suspended or revoked. Suspension moves `license_status` to `SUSPENDED`; attempting it on a license that is not `ACTIVE` is rejected with `ERR_LICENSE_NOT_ACTIVE`. Reinstatement returns a suspended license from `SUSPENDED` to `ACTIVE`, but only while the current logical clock has not passed `valid_to` — an expired license refuses reinstatement with `ERR_LICENSE_EXPIRED` (HTTP 403), and reinstating a license that is not `SUSPENDED` at all is rejected with `ERR_LICENSE_NOT_SUSPENDED`. Revocation is available from either `ACTIVE` or `SUSPENDED` and lands in the terminal `REVOKED` state; acting on an already-revoked license is rejected with `ERR_LICENSE_ALREADY_REVOKED`. Each of these three licensing actions increments the license's `version` by one.

### 3.2. Product Master Data and Shortage Governance

Products are registered by an `OrderManager` with an 11-digit canonical `ndc` that is unique across the catalog — a duplicate is rejected with `ERR_DUPLICATE_UNIQUE_FIELD` (HTTP 409) — along with the `product_name`, a non-negative `wholesale_acquisition_cost_cents` carrying the WAC list price per unit, and two handling flags. The `is_controlled` flag marks DEA schedule II–V items, which demand controlled-substance license scope and segregated handling; the `is_cold_chain` flag marks items requiring 2–8 °C storage, which demand cold-capable license scope and segregated handling. Where a 340B contract price exists for covered entities, `is_340b_contracted` is set true and `contract_340b_price_cents` must accompany it; otherwise `is_340b_contracted` defaults to false and `contract_340b_price_cents` is null. Every product begins life with `shortage_status` `NORMAL`.

When supply tightens, an `OrderManager` declares the shortage, moving `shortage_status` to `SHORTAGE` and incrementing the product's `version`. Declaring a shortage does not itself ration anything; rationing begins when the desk opens an allocation policy for the product. A policy is created with the shortage-managed `product_id`, a non-negative `pool_units` — the total allocatable units in the current shortage epoch — a `policy_mode` of `PRO_RATA` or `EQUAL_SHARE`, and an optional `min_guarantee_units`, defaulting to 0 and non-negative, expressing the per-customer floor granted before any pro-rata division. The policy's `remaining_units` initializes to `pool_units` and may never go negative, and its `policy_status` begins `OPEN`. At most one policy per product may be `OPEN` at a time; opening a second is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`.

A policy's lifecycle is partly automatic. When an allocation run drives `remaining_units` to zero, the policy flips from `OPEN` to `EXHAUSTED` on its own. When a confirmed order is later cancelled and its allocated units are released back, an `EXHAUSTED` policy whose `remaining_units` rises above zero flips back to `OPEN`, with the policy's `version` incrementing on that release. An `OrderManager` may also close a policy outright from either `OPEN` or `EXHAUSTED`, moving it to the terminal `CLOSED` state and incrementing `version`; closing from any other state is rejected with `ERR_POLICY_NOT_CLOSABLE`.

### 3.3. Serialization, Aggregation, and the EPCIS Event Ledger

Physical inventory enters the system as serialized packaging. A `WarehouseOperator` commissions a case by supplying its `sscc` — a Serialized Shipping Container Code, unique across all cases — together with the `product_id` of the contained product (cases are single-NDC only), the manufacturer `lot_number`, and the lot's `expiry_date`. The case's `case_status` starts `COMMISSIONED` and its `quarantine_link_id` is null. Units are then aggregated into the case: commissioning a unit takes its `sni` — a Serialized Numeric Identifier combining GTIN and serial, unique across all units — and the parent `case_id` that binds the unit into the case's aggregation tree, and the unit's `unit_status` starts `COMMISSIONED` as well. A duplicate `sscc` or `sni` is rejected with `ERR_DUPLICATE_UNIQUE_FIELD`.

Every subsequent physical movement is captured as an EPCIS event by a `WarehouseOperator` or a `QualityAssuranceLead`. Capture takes the `event_type` — one of `COMMISSION`, `AGGREGATE`, `SHIP`, `RECEIVE`, `QUARANTINE`, `RELEASE`, or `DECOMMISSION` — the `subject_case_id`, the business `event_time`, and the two counterparties of the transaction-information exchange, `sender_partner_id` and `recipient_partner_id`; an `order_id` is required on `SHIP` events and optional otherwise. The server stamps `recorded_at` from the current logical clock. An `event_time` later than the current logical clock is rejected with `ERR_EVENT_TIME_IN_FUTURE` (HTTP 422), and that freshness check is evaluated before event sequencing. Events are immutable ledger entries in the sense of §2.4.

Events both record and drive the case state machine. A `SHIP` event requires the case to be `COMMISSIONED` (otherwise `ERR_CASE_NOT_SHIPPABLE`) and its `expiry_date` to be strictly after the current logical clock (otherwise `ERR_PRODUCT_EXPIRED`, HTTP 422); on success the case moves `COMMISSIONED` → `SHIPPED`, every one of its units moves `COMMISSIONED` → `SHIPPED`, and the case's `version` increments. A `RECEIVE` event requires the case to be `SHIPPED` (otherwise `ERR_CASE_NOT_IN_TRANSIT`) and moves the case and its units `SHIPPED` → `RECEIVED`. A `DECOMMISSION` event requires `COMMISSIONED` (otherwise `ERR_CASE_NOT_SHIPPABLE`) and moves the case and its units `COMMISSIONED` → `DECOMMISSIONED`. Beyond these named transitions, event types must be admissible given the case's current status — an `AGGREGATE` event, for instance, is admissible only while the case is still `COMMISSIONED` — and an inadmissible type is rejected with `ERR_INVALID_EVENT_SEQUENCE` (HTTP 409). `QUARANTINE` and `RELEASE` events are not captured by hand; they are appended by the investigation machinery of §3.6.

Each event's `txn_history_hash` chains the case's transaction history. The first event recorded for a case carries an empty string. Thereafter the system locates the previous event for the same case — the one with the greatest `event_time`, ties broken by the greatest `recorded_at` — and computes a hex SHA-256-style digest over the concatenation of that previous event's `txn_history_hash`, the current `event_type`, and the current `event_time` rendered as an ISO 8601 string. The server rejects a second event bearing the same `event_time` and `recorded_at` for the same case, so no further tie is possible.

### 3.4. Ordering: Drafting, Line Capture, and Confirmation

An order begins when an `OrderManager` creates a purchase order naming the `customer_id` and the destination `ship_to_state`, with an optional `is_340b_order` flag, defaulting to false, marking purchases against a 340B contract. The customer reference must resolve to a registered partner whose `partner_kind` is `CUSTOMER`; an unknown reference is rejected with `ERR_REFERENCE_NOT_FOUND`. A new order's `fulfillment_status` is `DRAFT` and its `financial_status` is `UNBILLED` — the two dimensions evolve independently of one another — with `invoice_total_cents` and `invoice_balance_cents` both zero.

Lines are added to a `DRAFT` order one at a time, each carrying a `product_id` and a strictly positive `quantity_requested`, with the path binding the line's `order_id` to its parent order. Adding a line to an order that has left `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT`. A new line's `line_status` is `PENDING` and its `quantity_allocated` is zero; `unit_price_cents` and `extended_price_cents` remain unpriced until confirmation.

Confirmation is the pivotal checkpoint, performed by an `OrderManager`, and its gate evaluates checks in a fixed order. The order must be `DRAFT` (`ERR_ORDER_NOT_DRAFT`) and must contain at least one line (`ERR_ORDER_EMPTY`). License verification comes next, deliberately ahead of the credit check, so a customer lacking valid licensure hears about the license rather than the money: the customer must hold a state license covering the `ship_to_state` that is `ACTIVE` with `valid_to` at or beyond the current logical clock, failing which the confirm is rejected with `ERR_LICENSE_VERIFICATION_FAILED` (HTTP 403). If any line's product `is_controlled`, that license's `license_scope` must be `RX_AND_CONTROLLED` or `FULL`, failing which the confirm is rejected with `ERR_CONTROLLED_LICENSE_REQUIRED` (HTTP 403); if any line's product `is_cold_chain`, the scope must be `RX_AND_COLD_CHAIN` or `FULL`, failing which the rejection is `ERR_COLD_CHAIN_LICENSE_REQUIRED` (HTTP 403). Only then does the credit gate run: the customer's projected `open_receivable_cents` after booking this invoice must not exceed `credit_limit_cents`, or the confirm fails with `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402).

A successful confirm prices every line, regardless of line status. The `unit_price_cents` is the product's `contract_340b_price_cents` when the order `is_340b_order` and the product `is_340b_contracted`, and the product's `wholesale_acquisition_cost_cents` otherwise. Because nothing has been allocated yet, the provisional `extended_price_cents` for each line is the unit price times the requested quantity, and the provisional `invoice_total_cents` is the sum of those extended prices; `invoice_balance_cents` starts equal to the total. The same step moves the order `DRAFT` → `CONFIRMED` and `UNBILLED` → `INVOICED`, raises the customer's `open_receivable_cents` by the invoice total, and increments the order's `version`.

### 3.5. Shortage Allocation, Shipping, and Delivery

Allocation converts a confirmed order's requested quantities into granted ones. An `OrderManager` runs it against a `CONFIRMED` order (`ERR_ORDER_NOT_CONFIRMED` otherwise), and the run is the optimistic-concurrency-guarded write of §2.7: the request must carry `expected_order_version` matching the order's current `version`, with mismatches rejected as `ERR_STALE_VERSION` before any state precondition or business rule on the endpoint.

The run first establishes the competing set: all purchase orders in `CONFIRMED` or `ALLOCATED` that contain a line — of any line status — for the shortage product, evaluated at the start of the run. The total competing demand is the sum of `quantity_requested` across those lines, and the competing order count is the number of such orders. Lines are then processed in ascending `created_at` order with ties broken by ascending `quantity_requested`, considering lines whose `line_status` is `PENDING`, `PARTIALLY_ALLOCATED`, or `UNFULFILLABLE`. A line whose product is `NORMAL` is granted in full: its `quantity_allocated` becomes its `quantity_requested` and the line becomes `ALLOCATED`.

For a line whose product is in `SHORTAGE`, the run locates that product's `OPEN` allocation policy; if none exists, the line is granted zero and becomes `UNFULFILLABLE`. Under a `PRO_RATA` policy, the distributable remainder is the policy's `pool_units` less the per-customer floor multiplied by the competing order count; the line's grant is then `min_guarantee_units` plus the whole-unit floor of the remainder multiplied by the line's `quantity_requested` and divided by the total competing demand, and a grant never falls below its zero-unit floor. Under an `EQUAL_SHARE` policy, the grant is `pool_units` divided by the competing order count, rounded down to a whole unit. Either way, the granted `quantity_allocated` is the smallest of three values: the grant, the line's requested quantity, and the policy's `remaining_units`. Before the policy's `remaining_units` is decremented, any units the line already held from a previous allocation run are added back, so re-running allocation against an unchanged competing set reproduces the same result. The line then becomes `ALLOCATED` when the grant covers the full request, `PARTIALLY_ALLOCATED` when some but not all of the request is granted, and `UNFULFILLABLE` when nothing is granted; a policy whose `remaining_units` reaches zero flips to `EXHAUSTED`.

After the run, the invoice is finalized: each line's `extended_price_cents` is recomputed as the unit price times the allocated quantity, so the final total under shortage is strictly smaller than the provisional total priced on requested quantities. `invoice_total_cents` and `invoice_balance_cents` are restated to match, the customer's `open_receivable_cents` is adjusted by the delta, and when every line is fully allocated the order advances on its own from `CONFIRMED` to `ALLOCATED`. The order's `version` increments on the run.

Shipping is performed by a `WarehouseOperator` supplying a non-empty `case_ids` list and a `segregation_mode` declaration. The gate evaluates its checks in a fixed order: the order must be `CONFIRMED` or `ALLOCATED` (`ERR_ORDER_NOT_SHIPPABLE`); every line must have `quantity_allocated` greater than zero (`ERR_LINES_UNALLOCATED`); every listed case must be `COMMISSIONED` with a product matching some line's `product_id` (`ERR_CASE_NOT_SHIPPABLE`); then the suspect-stock interdiction — no listed case may be `QUARANTINED`, and no `OPEN` or `QUARANTINED` suspect investigation may exist for any listed case (`ERR_PRODUCT_UNDER_INVESTIGATION`, HTTP 403); then lot freshness — each listed case's `expiry_date` must be strictly after the current logical clock (`ERR_PRODUCT_EXPIRED`); and finally segregation coverage — controlled lines require the `CONTROLLED` declaration, cold-chain lines require `COLD_CHAIN`, and a shipment containing both classes is mixed and forbidden unless the declared `segregation_mode` is `SEGREGATED_COMBINED` (`ERR_SEGREGATION_REQUIRED`, HTTP 422). On success the order moves to `SHIPPED`, each listed case transitions `COMMISSIONED` → `SHIPPED` with its units following, a `SHIP` event binding each case to the order is appended to the event ledger, and the order's `version` increments.

Delivery by a `WarehouseOperator` moves a `SHIPPED` order to `DELIVERED` (`ERR_ORDER_NOT_SHIPPED` otherwise) and increments `version`; the delivery moment, as read from the logical clock, later anchors the return windows of §3.8.

Cancellation by an `OrderManager` is available while the order is `DRAFT` or `CONFIRMED` (`ERR_ORDER_NOT_CANCELLABLE` otherwise) and lands in the terminal `CANCELLED` state with a `version` increment. Cancelling a `DRAFT` order has no financial effect. Cancelling a `CONFIRMED` order unwinds it: if the financial dimension is `INVOICED`, it flips to `CREDITED`, the customer's `open_receivable_cents` falls by the outstanding `invoice_balance_cents`, and the balance is zeroed; any units the order held are released back to the allocation policy that granted them — whether that policy is `OPEN` or `EXHAUSTED`, with an `EXHAUSTED` policy flipping back to `OPEN` once its `remaining_units` rises above zero.

### 3.6. Suspect-Product Investigations and Quarantine

When product is flagged suspect, a `QualityAssuranceLead` opens an investigation naming the `case_id` and an `opened_reason`; the `investigation_status` starts `OPEN` with `reopen_count` zero. Opening the investigation changes nothing about the case itself — interdiction requires the quarantine step — but even an `OPEN` investigation is enough to block shipping, since any ship request listing the case in `case_ids` fails with `ERR_PRODUCT_UNDER_INVESTIGATION` while the investigation is `OPEN` or `QUARANTINED`.

Quarantine, also by a `QualityAssuranceLead`, requires the investigation to be `OPEN` (`ERR_INVESTIGATION_NOT_OPEN`) and stamps `quarantined_by_user_id` with the caller's `X-User-ID`. The cascade then moves the linked case to `QUARANTINED` — the case must be `COMMISSIONED`, `SHIPPED`, or `RECEIVED`, else `ERR_CASE_NOT_QUARANTINABLE` — sets the case's `quarantine_link_id` to the investigation's `id`, moves every unit of the case that is not already `DECOMMISSIONED` to `QUARANTINED`, appends a `QUARANTINE` event for the case, and increments both the investigation's `version` and the case's `version`.

Disposition comes in two forms, both guarded by segregation of duties: the acting lead's `X-User-ID` must differ from the stored `quarantined_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Clearing requires the investigation to be `QUARANTINED` (`ERR_INVESTIGATION_NOT_QUARANTINED`) and releases the case: the case's status is restored to what it was before quarantine — `RECEIVED` when it was quarantined from `RECEIVED`, otherwise `COMMISSIONED` — its `quarantine_link_id` returns to null, every `QUARANTINED` unit follows to the same restored status, a `RELEASE` event is appended, and the investigation becomes `CLEARED`. Confirming illegitimacy likewise requires `QUARANTINED` (`ERR_INVESTIGATION_NOT_QUARANTINED`) and destroys the product: the case moves to `DECOMMISSIONED`, every `QUARANTINED` unit moves to `DECOMMISSIONED`, a `DECOMMISSION` event is appended, and the investigation lands in the terminal `CONFIRMED_ILLEGITIMATE` state. Both cascades require the linked case to actually be `QUARANTINED`; a case in any other state surfaces `ERR_CASE_NOT_QUARANTINED`. Each disposition increments the investigation's `version`.

A cleared investigation is not necessarily dead. While `reopen_count` remains below three, a `QualityAssuranceLead` may reopen it, returning it from `CLEARED` to `OPEN`, incrementing `reopen_count` by one, and bumping the investigation's `version`. Reopening an investigation that is not `CLEARED` is rejected with `ERR_INVESTIGATION_NOT_CLEARED`; one that has already been reopened three times is rejected with `ERR_REOPEN_LIMIT_REACHED`.

### 3.7. Invoicing, Payments, and 340B Chargeback Reconciliation

The receivable ledger is the sum discipline of §3.1 applied continuously: a partner's `open_receivable_cents` always equals the outstanding invoice balances of that partner's orders in `INVOICED` or `PARTIALLY_PAID`, and every event that creates, reduces, or extinguishes a balance — order confirmation, payment posting, cancellation-with-credit, return credit — rebalances it immediately.

Payments are posted by a `BillingClerk` against orders whose `financial_status` is `INVOICED` or `PARTIALLY_PAID` (`ERR_INVOICE_NOT_OPEN` otherwise). The `amount_cents` must be strictly positive and no greater than the outstanding `invoice_balance_cents`, failing which the posting is rejected with `ERR_PAYMENT_AMOUNT_INVALID` (HTTP 422). A payment smaller than the balance moves the order to `PARTIALLY_PAID`; a payment exactly equal to the balance settles it — the balance becomes zero and the status becomes the terminal `PAID`. Either way, the posted amount reduces both the order's `invoice_balance_cents` and the customer's `open_receivable_cents` by the same figure.

Chargebacks reconcile 340B contract sales with the manufacturer. A `ContractAdministrator` submits a claim naming the `order_id` and a strictly positive `claimed_amount_cents`; at submission the server computes `computed_amount_cents`, and the `claim_status` starts `SUBMITTED`. The computed amount sums, over the referenced order's lines that are `ALLOCATED` or `PARTIALLY_ALLOCATED` and whose product `is_340b_contracted`, the difference between the product's `wholesale_acquisition_cost_cents` and its `contract_340b_price_cents`, multiplied by the line's allocated quantity. Two bases matter in practice: on a fully allocated order the allocated quantities equal the requested ones and the chargeback captures the full WAC-to-contract delta, while under shortage the allocated quantities shrink the chargeback proportionally — so the same claimed amount can match under one basis and mismatch under the other.

The claim must reference an order flagged `is_340b_order`, a check applied both at submission and at validation (`ERR_NOT_340B_ORDER`, HTTP 422). Validation by a `ContractAdministrator` requires the claim to be `SUBMITTED` (`ERR_CLAIM_NOT_SUBMITTED`), then re-verifies the 340B flag, then recomputes `computed_amount_cents` and requires it to equal `claimed_amount_cents` exactly (`ERR_CHARGEBACK_AMOUNT_MISMATCH`, HTTP 422); success moves the claim to `VALIDATED` and increments its `version`. Settlement by a `ContractAdministrator` requires `VALIDATED` (`ERR_CLAIM_NOT_VALIDATED`) and lands in the terminal `SETTLED` state. Denial is available from either `SUBMITTED` or `VALIDATED` (`ERR_CLAIM_NOT_DENIABLE` otherwise) and lands in the terminal `DENIED` state. Each claim action increments the claim's `version`.

### 3.8. Returns and Credit Issuance

An `OrderManager` lodges a return authorization against a prior sale by naming the `order_id`, the `product_id`, and a strictly positive `quantity_returned`; the `return_status` starts `REQUESTED`. Even at lodgement, the returned quantity may not exceed the `quantity_allocated` of the order's line for that product, or the request is rejected with `ERR_RETURN_QTY_EXCEEDS_ALLOCATED` (HTTP 422).

Physical receipt is a `WarehouseOperator` action with four gates: the return must be `REQUESTED` (`ERR_RETURN_NOT_REQUESTED`); the referenced order must be `SHIPPED` or `DELIVERED` (`ERR_ORDER_NOT_RETURNABLE`); the returned quantity must still fit within the line's allocated quantity (`ERR_RETURN_QTY_EXCEEDS_ALLOCATED`); and for cold-chain product the return must be lodged within 48 hours of the order's delivery as measured by the logical clock, failing which receipt is rejected with `ERR_COLD_RETURN_WINDOW_EXPIRED` (HTTP 422). A successful receipt moves the return to `RECEIVED` and increments its `version`.

Credit issuance is a `BillingClerk` action on a `RECEIVED` return (`ERR_RETURN_NOT_RECEIVED` otherwise) whose order's `financial_status` is `INVOICED`, `PARTIALLY_PAID`, or `PAID` (`ERR_INVOICE_NOT_CREDITABLE` otherwise). The `credit_amount_cents` is the returned quantity times the order line's `unit_price_cents` for that product times the applicable restock rate, rounded down to a whole cent. The rate turns on the days since delivery, measured in whole days with partial days discarded, between the delivery timestamp and the current logical clock. Cold-chain product earns half credit when no more than two days have elapsed and nothing afterward. Any other product earns full credit within thirty days of delivery, four-fifths credit from the thirty-first through the ninetieth day, and nothing afterward. The credit reduces the order's `invoice_balance_cents`, never below zero, and reduces the customer's `open_receivable_cents` by the credit amount, likewise clamped at zero; when the balance reaches zero on an order that was not already `PAID`, the financial dimension moves to `CREDITED`. The return becomes `CREDITED` — a terminal state — and its `version` increments.

Rejection by an `OrderManager` is available from `REQUESTED` or `RECEIVED` (`ERR_RETURN_NOT_REJECTABLE` otherwise) and lands in the terminal `REJECTED` state with a `version` increment.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources — registering partners, licenses, products, allocation policies, serialized cases and units, orders, order lines, investigations, claims, and return authorizations — return a `201 Created` status code; capturing an EPCIS event and posting a payment also return `201 Created`, since each appends a new record to the system. Operations that transition or otherwise modify an existing resource return a `200 OK` status code. All request and response bodies follow the envelope of §2.2, and list endpoints paginate per §2.3. Request fields, side effects, and error triggers are specified in the narratives of §2 and §3, which the table below intentionally does not repeat.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST   | `/wholesale/trading-partners` | Register a trading partner (customer or supplier) | OrderManager |
| GET    | `/wholesale/trading-partners` | List trading partners | All roles |
| GET    | `/wholesale/trading-partners/{partnerId}` | Get one trading partner | All roles |
| POST   | `/wholesale/partner-state-licenses` | Register a state license for a partner | ComplianceOfficer |
| GET    | `/wholesale/partner-state-licenses` | List state licenses (filterable by partner) | All roles |
| GET    | `/wholesale/partner-state-licenses/{licenseId}` | Get one state license | All roles |
| POST   | `/wholesale/partner-state-licenses/{licenseId}/suspend` | Suspend a license | ComplianceOfficer |
| POST   | `/wholesale/partner-state-licenses/{licenseId}/reinstate` | Reinstate a suspended license | ComplianceOfficer |
| POST   | `/wholesale/partner-state-licenses/{licenseId}/revoke` | Revoke a license (terminal) | ComplianceOfficer |
| POST   | `/wholesale/products` | Register a product (NDC master data) | OrderManager |
| GET    | `/wholesale/products` | List products | All roles |
| GET    | `/wholesale/products/{productId}` | Get one product | All roles |
| POST   | `/wholesale/products/{productId}/declare-shortage` | Declare a product in shortage, enabling allocation policies | OrderManager |
| POST   | `/wholesale/allocation-policies` | Open a shortage allocation policy for a product | OrderManager |
| GET    | `/wholesale/allocation-policies` | List allocation policies | All roles |
| GET    | `/wholesale/allocation-policies/{policyId}` | Get one allocation policy | All roles |
| POST   | `/wholesale/allocation-policies/{policyId}/close` | Close an allocation policy | OrderManager |
| POST   | `/wholesale/serialized-cases` | Commission a serialized case | WarehouseOperator |
| GET    | `/wholesale/serialized-cases` | List serialized cases | All roles |
| GET    | `/wholesale/serialized-cases/{caseId}` | Get one serialized case | All roles |
| GET    | `/wholesale/serialized-cases/{caseId}/units` | List units aggregated under a case | All roles |
| POST   | `/wholesale/serialized-units` | Commission a serialized unit into a case (aggregation) | WarehouseOperator |
| GET    | `/wholesale/serialized-units` | List serialized units | All roles |
| GET    | `/wholesale/serialized-units/{unitId}` | Get one serialized unit | All roles |
| POST   | `/wholesale/epcis-events` | Capture an EPCIS event (commission/aggregate/ship/receive/quarantine/release/decommission) | WarehouseOperator, QualityAssuranceLead |
| GET    | `/wholesale/epcis-events` | List EPCIS events (transaction history) | All roles |
| GET    | `/wholesale/epcis-events/{eventId}` | Get one EPCIS event | All roles |
| POST   | `/wholesale/purchase-orders` | Create a purchase order (DRAFT) | OrderManager |
| GET    | `/wholesale/purchase-orders` | List purchase orders | All roles |
| GET    | `/wholesale/purchase-orders/{orderId}` | Get one purchase order | All roles |
| GET    | `/wholesale/purchase-orders/{orderId}/lines` | List order lines | All roles |
| POST   | `/wholesale/purchase-orders/{orderId}/lines` | Add an order line (DRAFT orders only); path orderId binds the parent | OrderManager |
| GET    | `/wholesale/order-lines` | List order lines across orders (filterable) | All roles |
| GET    | `/wholesale/order-lines/{lineId}` | Get one order line | All roles |
| POST   | `/wholesale/purchase-orders/{orderId}/confirm` | Confirm an order: license verification, pricing, invoicing | OrderManager |
| POST   | `/wholesale/purchase-orders/{orderId}/allocate` | Run shortage allocation over the order's lines (OCC-guarded) | OrderManager |
| POST   | `/wholesale/purchase-orders/{orderId}/ship` | Ship an order, binding the listed serialized cases, with segregation-mode declaration | WarehouseOperator |
| POST   | `/wholesale/purchase-orders/{orderId}/deliver` | Mark a shipped order delivered | WarehouseOperator |
| POST   | `/wholesale/purchase-orders/{orderId}/cancel` | Cancel a DRAFT or CONFIRMED order | OrderManager |
| POST   | `/wholesale/purchase-orders/{orderId}/payments` | Post a payment against an open invoice | BillingClerk |
| POST   | `/wholesale/suspect-investigations` | Open a suspect-product investigation on a serialized case | QualityAssuranceLead |
| GET    | `/wholesale/suspect-investigations` | List suspect investigations | All roles |
| GET    | `/wholesale/suspect-investigations/{investigationId}` | Get one suspect investigation | All roles |
| POST   | `/wholesale/suspect-investigations/{investigationId}/quarantine` | Quarantine the suspect case | QualityAssuranceLead |
| POST   | `/wholesale/suspect-investigations/{investigationId}/clear` | Clear a quarantined investigation (segregation of duties applies) | QualityAssuranceLead |
| POST   | `/wholesale/suspect-investigations/{investigationId}/confirm-illegitimate` | Confirm product illegitimate (terminal; decommissions case) | QualityAssuranceLead |
| POST   | `/wholesale/suspect-investigations/{investigationId}/reopen` | Reopen a cleared investigation (max 3 reopens) | QualityAssuranceLead |
| POST   | `/wholesale/chargeback-claims` | Submit a 340B chargeback claim against an order | ContractAdministrator |
| GET    | `/wholesale/chargeback-claims` | List chargeback claims | All roles |
| GET    | `/wholesale/chargeback-claims/{claimId}` | Get one chargeback claim | All roles |
| POST   | `/wholesale/chargeback-claims/{claimId}/validate` | Validate a submitted claim against the computed amount | ContractAdministrator |
| POST   | `/wholesale/chargeback-claims/{claimId}/settle` | Settle a validated claim | ContractAdministrator |
| POST   | `/wholesale/chargeback-claims/{claimId}/deny` | Deny a claim | ContractAdministrator |
| POST   | `/wholesale/return-authorizations` | Request a return against a shipped/delivered order | OrderManager |
| GET    | `/wholesale/return-authorizations` | List return authorizations | All roles |
| GET    | `/wholesale/return-authorizations/{returnId}` | Get one return authorization | All roles |
| POST   | `/wholesale/return-authorizations/{returnId}/receive` | Receive returned goods (cold-chain window enforced) | WarehouseOperator |
| POST   | `/wholesale/return-authorizations/{returnId}/credit` | Issue credit for a received return | BillingClerk |
| POST   | `/wholesale/return-authorizations/{returnId}/reject` | Reject a return | OrderManager |
| POST   | `/_clock/set_current_utc` | Set the logical clock (test-driving endpoint) | All roles |

## 5. Error Code Catalogue

The table below enumerates every error identifier the API can return, with its HTTP status code. The conditions that trigger each error are specified in the narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_UNIQUE_FIELD` | 409 Conflict |
| `ERR_ORDER_NOT_DRAFT` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 409 Conflict |
| `ERR_ORDER_NOT_CONFIRMED` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_ORDER_NOT_SHIPPED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_LINES_UNALLOCATED` | 409 Conflict |
| `ERR_LICENSE_VERIFICATION_FAILED` | 403 Forbidden |
| `ERR_CONTROLLED_LICENSE_REQUIRED` | 403 Forbidden |
| `ERR_COLD_CHAIN_LICENSE_REQUIRED` | 403 Forbidden |
| `ERR_LICENSE_NOT_ACTIVE` | 409 Conflict |
| `ERR_LICENSE_NOT_SUSPENDED` | 409 Conflict |
| `ERR_LICENSE_ALREADY_REVOKED` | 409 Conflict |
| `ERR_LICENSE_EXPIRED` | 403 Forbidden |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_INVALID` | 422 Unprocessable Entity |
| `ERR_INVOICE_NOT_OPEN` | 409 Conflict |
| `ERR_INVOICE_NOT_CREDITABLE` | 409 Conflict |
| `ERR_PRODUCT_UNDER_INVESTIGATION` | 403 Forbidden |
| `ERR_SEGREGATION_REQUIRED` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVESTIGATION_NOT_OPEN` | 409 Conflict |
| `ERR_INVESTIGATION_NOT_QUARANTINED` | 409 Conflict |
| `ERR_INVESTIGATION_NOT_CLEARED` | 409 Conflict |
| `ERR_REOPEN_LIMIT_REACHED` | 409 Conflict |
| `ERR_CASE_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_CASE_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_CASE_NOT_QUARANTINABLE` | 409 Conflict |
| `ERR_CASE_NOT_QUARANTINED` | 409 Conflict |
| `ERR_PRODUCT_EXPIRED` | 422 Unprocessable Entity |
| `ERR_EVENT_TIME_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_INVALID_EVENT_SEQUENCE` | 409 Conflict |
| `ERR_NOT_340B_ORDER` | 422 Unprocessable Entity |
| `ERR_CHARGEBACK_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CLAIM_NOT_SUBMITTED` | 409 Conflict |
| `ERR_CLAIM_NOT_VALIDATED` | 409 Conflict |
| `ERR_CLAIM_NOT_DENIABLE` | 409 Conflict |
| `ERR_RETURN_NOT_REQUESTED` | 409 Conflict |
| `ERR_ORDER_NOT_RETURNABLE` | 409 Conflict |
| `ERR_RETURN_QTY_EXCEEDS_ALLOCATED` | 422 Unprocessable Entity |
| `ERR_COLD_RETURN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_RETURN_NOT_RECEIVED` | 409 Conflict |
| `ERR_RETURN_NOT_REJECTABLE` | 409 Conflict |
| `ERR_POLICY_NOT_CLOSABLE` | 409 Conflict |

# Aircraft Component MRO API — Product Requirements Document

## 1. Introduction

This document specifies the API for an FAA Part 145 repair station performing maintenance, repair, and overhaul (MRO) of serialized aircraft components. Operators and airlines induct rotable and non-rotable units for teardown, repair, and overhaul; the shop is simultaneously bound by airworthiness regulation — Component Maintenance Manual (CMM) work scopes, Airworthiness Directive (AD) and Service Bulletin (SB) compliance, Acceptance Test Procedure (ATP) records, 8130 release certification, and back-to-birth traceability — and by commercial guarantees, including door-to-door turnaround-time (TAT) commitments with penalty credits, warranty coverage on overhaul cycles, and customer credit exposure limits.

The API is the shop's system of record. It governs customer commercial terms, the part catalog and its directives, serialized component units carrying two parallel status dimensions, work orders from induction through release and closure, parts sourcing with OEM/PMA approval gates, test-cell scheduling, a rotable exchange pool with core settlement, lease units, warranty claims, and invoicing with payment. All resources are mounted under the `/mro` prefix. Segregation of duties is enforced throughout: the inspector who signs off test results or a release must never be the technician who performed the repair.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, specifying their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly six roles: `ShopManager`, `CustomerServiceRep`, `Technician`, `Inspector`, `PartsBuyer`, and `Customer`. Access to each operation is restricted by role per §4; an attempt to perform an action outside the caller's role is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

When `X-User-Role` is `ShopManager`, `CustomerServiceRep`, `Technician`, `Inspector`, or `PartsBuyer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `technician_user_id` or `inspector_user_id` on a work order, or as `signed_by` on a release certificate — but it never compares that value to any entity's `id`.

When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting Customer record; ownership checks on any resource that references a customer compare the resource's customer-reference field (for example `customer_id`, or `owner_customer_id` on a unit) to `X-User-ID`, and a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. One exception exists: a unit's traceability listing is ordered chronologically ascending by `event_at`, with ties broken by `created_at`.

List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits, recorded at creation.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits, refreshed on any modification.
- `version` (integer): a system-managed integer that increments by exactly 1 on every mutation of the resource.

Any mutation — including the recomputation or storage of a derived field — refreshes `updated_at` and increments `version`. Three resource families are immutable ledgers and carry only `id` and `created_at`: DirectiveRecord, ReleaseCertificate, and TraceabilityRecord. On those three, both `updated_at` and `version` are absent.

### 2.5. The Logical Clock

All timestamps the system writes — `received_at`, `quote_submitted_at`, `released_at`, `issued_at`, `paid_at`, `event_at`, and their kin — are read from a server-maintained logical clock, never from wall-clock time. At server startup the logical clock is exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time if the clock has not been set.

A `ShopManager`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant. Its response returns `current_utc` and `defaulted_exchange_agreement_ids`. Setting the clock also triggers the exchange-agreement default sweep described in §3.7, which can create settlement invoices and update customer exposure.

### 2.6. Monetary Precision and Per-Line Rounding

All monetary values in the system are integer cents. Wherever a computed cent value is produced, it is rounded half up to whole cents.

Aggregation order is pinned for the two per-line money sources on a work-order invoice: each parts requisition's `extended_price_cents` is rounded half up to whole cents at receive time, and each test-cell booking's `fee_cents` is rounded half up to whole cents at booking creation; invoice lines then sum the already-rounded per-line values. Summing first and rounding once at the end is forbidden, because the two orders can diverge by cents.

Elapsed-hour quantities used in turnaround-time calculations — elapsed hours and `accumulated_delay_hours` — are carried at two decimal places.

### 2.7. Optimistic Concurrency Control

Exactly two write operations participate in optimistic concurrency control; endpoints not named here do not take a version field.

Approving a quote requires the request to carry `expected_work_order_version`, the client asserting the work order `version` it last observed. If that value does not match the work order's current `version` — for example because a re-quote has superseded the quoted amounts and advanced the version — the request is rejected with `ERR_STALE_VERSION` (HTTP 412). This prevents a customer from approving amounts they have not observed: the work order may still be in `QUOTE_SUBMITTED`, so only the version check catches the staleness.

Creating a lease agreement requires the request to carry `expected_unit_version`, the client asserting the component unit `version` it last observed. If that value does not match the unit's current `version`, the creation is rejected with `ERR_STALE_VERSION` (HTTP 412). A prior lease creation legitimately moved the unit to `ON_LEASE`, and forward-dated non-overlapping leases remain legal, so no state precondition catches the stale writer — only the version check does.

On both operations the version check fires after resource-existence checks and before any business logic.

### 2.8. Resource Existence and Nested Path Validation

When an endpoint path contains one or more resource identifiers, existence is validated sequentially from left to right, and the request is rejected at the first identifier that does not resolve. Each resource family has its own 404 code: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_REQUISITION_NOT_FOUND`, `ERR_TEST_CELL_NOT_FOUND`, `ERR_EXCHANGE_NOT_FOUND`, and `ERR_LEASE_NOT_FOUND`. A request targeting a requisition under a non-existent work order therefore fails with `ERR_WORK_ORDER_NOT_FOUND` before the requisition is ever examined.

Reference identifiers supplied in request bodies — `customer_id`, `unit_id`, `part_id`, `core_unit_id`, `original_work_order_id`, and the `work_order_id` carried by a booking — are existence-checked the same way, using the corresponding family code where one exists. References with no family-specific code fall back to the generic `ERR_NOT_FOUND` (HTTP 404).

### 2.9. Validation Pipeline and Check Ordering

Every request passes through an ordered validation pipeline, and a failure at any stage short-circuits the rest:

1. Authentication headers (missing or empty headers → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. Role authorization for the endpoint (`ERR_FORBIDDEN_ROLE`).
3. Resource existence, paths validated left to right (§2.8).
4. Optimistic concurrency, where the endpoint participates (§2.7) — before any business logic.
5. State-machine from-state checks (the per-entity `ERR_*_INVALID_STATE` family, HTTP 409).
6. Business rules, evaluated in category order: safety rules (HTTP 403) first, then temporal rules (HTTP 409), then business constraints (HTTP 409 or 422), then referential rules such as ownership and part matching (HTTP 403 or 422), and fiscal rules (HTTP 402 or 422) last.

Where several checks guard one operation, the relative order is fixed and observable:

- Work-order induction checks unit custody availability first, then the work-scope reservation, then unit-ownership matching.
- Quote submission checks the from-state, then the BER scrap acknowledgement (safety), then the customer credit hold (fiscal) — so a BER quote from a credit-held customer surfaces `ERR_BER_SCRAP_ACK_REQUIRED` rather than being masked by the fiscal check.
- Quote approval checks `expected_work_order_version` before the from-state and ownership checks.
- Complete-repair checks the from-state, then mandatory-directive compliance (safety), then open discrepancy cards (constraint).
- Test results check the from-state, then segregation of duties (safety), then the active covering booking (temporal).
- Release checks the from-state before the segregation-of-duties check.
- Booking creation checks the work order's from-state, then window overlap (temporal), then ATA capability (constraint).
- Lease creation checks `expected_unit_version`, then day-interval overlap (temporal), then unit leasability (constraint).
- Exchange fulfillment checks the from-state, then pool emptiness (constraint), then the customer credit hold (fiscal).
- Core return checks the from-state, then core ownership matching, then core part matching.
- Quote decline checks the from-state, then the scrap-requires-BER rule when `disposition` is `SCRAP`, then customer ownership.
- Invoice payment checks the invoice from-state, then customer ownership, then the exact-amount rule.
- Warranty claim creation checks that the original work order is closed before evaluating the warranty limits.

### 2.10. Customer Credit Exposure and Credit Holds

Each customer carries `current_exposure_cents`, a stored running total of outstanding billed exposure. When an invoice is `ISSUED`, its `total_cents` is added to `current_exposure_cents`; when an invoice is `PAID`, its `total_cents` is subtracted as a compensating action. The invariant is that `current_exposure_cents` always equals the sum of `total_cents` across that customer's invoices in `ISSUED` status.

A customer's `credit_hold` flag is true exactly when `current_exposure_cents` is greater than or equal to `credit_limit_cents` — the boundary is inclusive. While `credit_hold` is true, two operations are blocked with `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402): submitting a quote on one of the customer's work orders, and fulfilling an exchange agreement for the customer.

### 2.11. Back-to-Birth Traceability

Every serialized unit accumulates an immutable sequence of TraceabilityRecord entries, beginning at registration (whose `manufactured_at` date anchors the back-to-birth history) and ending, at latest, at scrap. Each record carries `unit_id`, an `event_type`, `event_at` (the logical clock reading when the event was recorded), an optional `work_order_id` holding the originating work order as a plain reference when applicable, and optional `notes` for event detail such as a certificate number or agreement id.

The `event_type` vocabulary is exactly: `BIRTH`, `INDUCT`, `DISPOSITION`, `RELEASE_OVERHAUL`, `RELEASE_REPAIR`, `SCRAP`, `EXCHANGE_OUT`, `CORE_IN`, `LEASE_OUT`, `LEASE_RETURN`, and `WARRANTY_INDUCT`. The moments at which the system appends each event are described with their triggering workflows in §3. A unit's records are retrievable as a chronological list, ascending by `event_at` and then by `created_at`.

## 3. Business Logic & Workflows

### 3.1. Commercial Onboarding: Customers, the Part Catalog, and Airworthiness Directives

A `ShopManager` onboards each operator as a Customer with a `name` and a `certificate_number` — the air carrier certificate number, unique across customers; a duplicate submission is rejected with `ERR_INVALID_REQUEST`. The commercial contract is captured in four fields: `contract_tat_hours`, the guaranteed door-to-door turnaround in hours per work order; `tat_penalty_rate_cents_per_hour`, the penalty credit rate applied per excess adjusted hour; `tat_penalty_cap_pct`, the penalty cap expressed as a percent of the invoice subtotal (from 0 to 100); and `credit_limit_cents`, the maximum allowed outstanding exposure. An optional `penalty_delay_rule` selects the TAT penalty variant: it defaults to `ADJUSTED`, which excludes customer-delay hours from the penalty basis, while `CALENDAR` uses raw elapsed hours (§3.6). A new customer starts with `status` set to `ACTIVE` — the only value, suspension being out of scope — and `current_exposure_cents` at zero.

Catalog maintenance is likewise a `ShopManager` duty. Each part catalog entry records the manufacturer `part_number` (unique; duplicates rejected with `ERR_INVALID_REQUEST`), an `ata_chapter` code such as '32', an `is_rotable` flag marking eligibility for the exchange pool, the `cmm_reference` Component Maintenance Manual reference, and `replacement_value_cents`, the new-part replacement value that anchors both BER evaluation and core charges. An optional `ber_threshold_pct` defaults to 65 and sets the beyond-economic-repair threshold as a percent of `replacement_value_cents`. Warranty coverage ceilings are recorded as `warranty_cycle_limit` (cycles since overhaul, inclusive) and `warranty_month_limit` (months since release, inclusive), and `flat_overhaul_price_cents` holds the catalog flat-rate overhaul labor price used as a reference for quotes.

Against any catalog part, a `ShopManager` registers airworthiness directives by referencing the part through `part_id`. Each directive record carries a `directive_type` of `AD` (Airworthiness Directive, mandatory by nature) or `SB` (Service Bulletin), a `directive_number` unique per part (duplicates rejected with `ERR_INVALID_REQUEST`), a `mandatory` flag that is true for mandatory ADs, and a free-text `description` summarizing compliance. A part's directives are retrievable as a list, as are the units of a part. Mandatory directives gate the completion of repair work on every work order for that part, as described in §3.4.

### 3.2. Unit Registration and Work-Order Induction

A `CustomerServiceRep` registers each serialized unit — its birth record — with the catalog `part_id`, a globally unique `serial_number` (reuse rejected with `ERR_DUPLICATE_SERIAL`, HTTP 409), an `ownership` of `SHOP` (pool or lease stock) or `CUSTOMER`, and an `owner_customer_id` that is required exactly when `ownership` is `CUSTOMER` and must be null when `SHOP`. The unit's two parallel status dimensions are registered independently: `condition_status` as `SERVICEABLE`, `UNSERVICEABLE`, or `SCRAPPED`, and `custody_status` as `OFF_SITE`, `IN_SHOP`, `AWAITING_SHIPMENT`, `SHIPPED`, `IN_POOL`, or `ON_LEASE`. These dimensions evolve on the same row and never reset one another. Registration enforces the ownership/custody combination: a `CUSTOMER`-owned unit must register with custody `OFF_SITE`, while a `SHOP`-owned unit must register with custody `IN_POOL` or `IN_SHOP` and no owner; violations are rejected with `ERR_INVALID_REQUEST`. The unit's life counters are `total_cycles` (accumulated cycles since new, the backbone of back-to-birth accounting) and `cycles_since_overhaul`, and its `manufactured_at` date (YYYY-MM-DD) opens the traceability history. Registration appends a `BIRTH` traceability event. The unit list supports optional filters `part_id`, `owner_customer_id`, `ownership`, `custody_status`, and `condition_status`; a customer's owned units are also listable under the customer.

Induction begins when a `CustomerServiceRep` creates a work order with a `customer_id`, a `unit_id`, and a `work_scope` of `REPAIR` or `OVERHAUL`. Three checks apply, in order: the unit's `custody_status` must be `OFF_SITE` — a unit already inducted, leased, or pooled is rejected with `ERR_UNIT_NOT_AVAILABLE` (HTTP 409); the `WARRANTY_REWORK` scope is system-reserved and any manual creation with it is rejected with `ERR_INVALID_REQUEST`, since only warranty-claim acceptance may create such an order; and for a `CUSTOMER`-owned unit the owner must match the work order's customer, otherwise `ERR_UNIT_OWNER_MISMATCH` (HTTP 422).

A successful induction starts the work order in `TEARDOWN_IN_PROGRESS`, stamps `received_at` with the logical clock (this is the TAT start), moves the unit's custody `OFF_SITE → IN_SHOP`, appends an `INDUCT` traceability event, and creates one `PENDING` DirectiveCompliance record for every DirectiveRecord of the unit's part — each copying `directive_number`, `directive_type`, and `mandatory` from the directive as plain values, not as references. A work order's compliance records are retrievable as a list, and a customer's or a unit's work orders are likewise listable. The one exception to the induction flow is the warranty rework order, which claim acceptance creates directly in `REPAIR_IN_PROGRESS` (§3.9).

### 3.3. Teardown Findings and the Quoting Cycle

During teardown a `Technician` files discrepancy cards against the work order, each with a `finding_text` and a `severity` of `MINOR` or `MAJOR`. A card is created in `OPEN` status, and its creation increments the work order's `open_discrepancy_count` by 1. Dispositioning a card — a `Technician` supplying the corrective action as `disposition_text` — moves it `OPEN → DISPOSITIONED`, stores the text, and decrements `open_discrepancy_count` by 1; a card that is not `OPEN` rejects disposition with `ERR_DISCREPANCY_INVALID_STATE`. A work order's cards are retrievable as a list.

Once findings are resolved, the `Technician` declares teardown complete. This requires the work order to be in `TEARDOWN_IN_PROGRESS` (otherwise `ERR_WORK_ORDER_INVALID_STATE`) and no card of the work order to remain `OPEN` (otherwise `ERR_OPEN_DISCREPANCIES`, HTTP 409); success moves the work order to `AWAITING_QUOTE`.

A `CustomerServiceRep` then submits the quote with `labor_estimate_cents` and `parts_estimate_cents`, plus an optional `scrap_option_ack`. Submission recomputes the work order's beyond-economic-repair evaluation: the BER threshold in cents is `ber_threshold_pct` percent of the part's `replacement_value_cents`, rounded half up to whole cents, and `ber_flag` is true when the sum of the two estimates is at least that threshold — the boundary is inclusive, so an estimate exactly equal to the threshold is beyond economic repair. Three checks guard submission, in order: the work order must be in `AWAITING_QUOTE` (or `QUOTE_SUBMITTED` for a re-quote), otherwise `ERR_WORK_ORDER_INVALID_STATE`; if the recomputed `ber_flag` is true, `scrap_option_ack` must be true, otherwise `ERR_BER_SCRAP_ACK_REQUIRED` (HTTP 403); and the customer's `credit_hold` must be false, otherwise `ERR_CUSTOMER_CREDIT_HOLD`. A successful quote stamps `quote_submitted_at` with the clock, computes `promised_return_at` as `received_at` plus the customer's `contract_tat_hours`, fixes `labor_charge_cents` equal to `labor_estimate_cents` (the quoted labor is a fixed price), stores the recomputed `ber_flag`, increments the work order's `version` by 1, and moves the work order to `QUOTE_SUBMITTED`.

Re-quoting is a self-loop from `QUOTE_SUBMITTED` back to `QUOTE_SUBMITTED`: the same checks apply, and the new submission supersedes the prior quote — `quote_submitted_at` is re-stamped, and the estimates, `labor_charge_cents`, and `ber_flag` are overwritten. Because the re-quote again increments `version` by 1, any `expected_work_order_version` captured before it no longer matches, which is exactly what invalidates a stale quote approval.

The customer decides on the quote. Approval requires the caller to be the work order's customer (`ERR_NOT_RESOURCE_OWNER` otherwise), to present an `expected_work_order_version` matching the work order's current `version` per §2.7 (`ERR_STALE_VERSION`, HTTP 412, otherwise), and to find the work order in `QUOTE_SUBMITTED` (`ERR_WORK_ORDER_INVALID_STATE` otherwise). Approval adds the hours between `quote_submitted_at` and the current clock — at two decimal places — into `accumulated_delay_hours`, increments `version` by 1, and moves the work order `QUOTE_SUBMITTED → REPAIR_IN_PROGRESS`.

Decline carries a `disposition`. With `disposition` set to `RETURN_UNREPAIRED`, ownership and the `QUOTE_SUBMITTED` from-state are checked, the same delay hours are accumulated, the unit's `custody_status` moves to `AWAITING_SHIPMENT` with its `condition_status` unchanged, and the work order is `CANCELLED`. With `disposition` set to `SCRAP`, the additional rule is that `ber_flag` must be true, otherwise `ERR_SCRAP_REQUIRES_BER` (HTTP 409); on success the work order becomes `BER_SCRAPPED`, and a two-hop cascade follows: the unit's `condition_status` becomes `SCRAPPED` and its `custody_status` becomes `AWAITING_SHIPMENT`, and because the unit entered `SCRAPPED`, a `SCRAP` traceability event is appended for it. The delay hours are accumulated on this path as well.

### 3.4. Repair Execution, Directive Compliance, and Parts Sourcing

While the work order is under repair, a `Technician` records compliance with each directive by supplying the `directive_number`, a `result` of `COMPLIED` or `NOT_APPLICABLE`, and an optional `note` that is stored as the record's `compliance_note`. Each recording moves the addressed DirectiveCompliance record from `PENDING` to `COMPLIED` or to `NOT_APPLICABLE`; a record no longer in `PENDING` rejects the attempt with `ERR_INVALID_STATE`.

When the physical work is done, the `Technician` declares the repair complete. The checks, in order: the work order must be in `REPAIR_IN_PROGRESS` (`ERR_WORK_ORDER_INVALID_STATE`); every DirectiveCompliance of this work order with `mandatory` set true must be `COMPLIED` or `NOT_APPLICABLE`, otherwise `ERR_AD_COMPLIANCE_INCOMPLETE` (HTTP 403); and no discrepancy card of this work order may remain `OPEN`, otherwise `ERR_OPEN_DISCREPANCIES`. On success, every `DISPOSITIONED` card of the work order is closed automatically (`DISPOSITIONED → CLOSED`), the acting user's id is captured as `technician_user_id` — the segregation-of-duties anchor consulted again at test and release — the work order's `version` increments by 1, and the work order advances to `READY_FOR_TEST`.

Parts flow through requisitions. A `Technician` files one with a free-text `part_number` (shop stock, not a catalog reference), a `quantity` greater than zero, and a `requested_source` of `OEM` or `PMA`. An `OEM` request starts in `REQUESTED`; a `PMA` request starts in `PMA_PENDING_CUSTOMER`, because PMA usage requires the customer's gate. Filing a requisition while the work order is `REPAIR_IN_PROGRESS` automatically moves the work order to `AWAITING_PARTS`; filing one while it is already `AWAITING_PARTS` leaves it there. A work order's requisitions are retrievable as a list.

The `PartsBuyer` then rules on source approval by sending `approved` with an optional `source_override`. From `REQUESTED` or from `SOURCE_REJECTED` (any other status is rejected with `ERR_REQUISITION_INVALID_STATE`): approval moves the requisition to `APPROVED` and records `approved_source` as `OEM` — or as the supplied `source_override` value when re-approving after a rejection — while rejection moves it to `SOURCE_REJECTED`. Approval from `SOURCE_REJECTED` is what closes the reject/resubmit loop.

The PMA branch instead reaches the `Customer`, who sends `approved` from `PMA_PENDING_CUSTOMER` (other statuses rejected with `ERR_REQUISITION_INVALID_STATE`), with ownership enforced against the work order's customer (`ERR_NOT_RESOURCE_OWNER`). Approval moves the requisition to `APPROVED` and records `approved_source` as `PMA`; rejection moves it to `PMA_REJECTED`. From `PMA_REJECTED`, the `PartsBuyer` can rejoin the flow at `APPROVED` through source approval with `approved` true, but only when `source_override` is `OEM` — any other override is rejected with `ERR_INVALID_REQUEST` — and `approved_source` is recorded as `OEM`. The fork-join is deliberate: the PMA branch requires the customer gate, and the OEM fallback rejoins at `APPROVED`.

Receiving is a `PartsBuyer` action that records the actual `unit_cost_cents` and moves the requisition `APPROVED → RECEIVED` (other statuses rejected with `ERR_REQUISITION_INVALID_STATE`). At that moment the line's `extended_price_cents` is computed: `quantity` multiplied by `unit_cost_cents` multiplied by the applicable markup factor, rounded half up to whole cents as a per-line rounding. The markup tier is keyed on `unit_cost_cents`: a unit cost at or below $1,000.00 marks up 25 percent; a unit cost above $1,000.00 and at or below $10,000.00 marks up 15 percent; a unit cost above $10,000.00 marks up 10 percent.

Issuing the part to the work order is a `Technician` action from `RECEIVED` (otherwise `ERR_REQUISITION_INVALID_STATE`), and the work order must be in `REPAIR_IN_PROGRESS` or `AWAITING_PARTS` (otherwise `ERR_WORK_ORDER_INVALID_STATE`). The issue adds the line's `extended_price_cents` into the work order's `parts_charge_cents` — the ledger sync — and moves the requisition to `ISSUED`. If the work order was `AWAITING_PARTS` and this issue leaves no requisition of the work order in the active set of `REQUESTED`, `PMA_PENDING_CUSTOMER`, `APPROVED`, or `RECEIVED`, the work order automatically returns to `REPAIR_IN_PROGRESS`. Rejected requisitions (`SOURCE_REJECTED`, `PMA_REJECTED`) never block that return; only the active set gates it.

### 3.5. Test Cell Operations, ATP Results, and the 8130 Release

A `ShopManager` configures each test cell with a unique `name` (duplicates rejected with `ERR_INVALID_REQUEST`), the list of `supported_ata_chapters` the cell can test, and an `hourly_rate_cents`.

A `CustomerServiceRep` books a cell window by sending the `work_order_id` plus `start_time` and `end_time`; the booking is recorded against the cell through `test_cell_id`. The window is half-open: `start_time` is inclusive and `end_time` is exclusive, so two windows that merely touch are adjacent, not overlapping. Three checks apply in order: the work order must be in `READY_FOR_TEST` (otherwise `ERR_WORK_ORDER_INVALID_STATE`); the window must not overlap any existing `BOOKED` window on the same cell — adjacency is allowed — otherwise `ERR_TEST_CELL_OVERLAP` (HTTP 409); and the cell must support the ATA chapter of the work order's part, otherwise `ERR_CELL_ATA_UNSUPPORTED` (HTTP 422). At creation the booking's `fee_cents` is computed as the window's duration in hours multiplied by the cell's `hourly_rate_cents`, rounded half up to whole cents, and the booking starts `BOOKED`. A `CustomerServiceRep` may cancel a booking, moving it `BOOKED → CANCELLED`; a booking no longer `BOOKED` rejects cancellation with `ERR_INVALID_STATE`. Bookings are listable per cell and per work order.

An `Inspector` records the ATP result by sending a `result` of `PASS` or `FAIL` together with the `atp_reference`. The checks, in order: the work order must be in `READY_FOR_TEST` (`ERR_WORK_ORDER_INVALID_STATE`); segregation of duties forbids the caller from being the technician who performed the repair, so `X-User-ID` must differ from the work order's `technician_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403); and a `BOOKED` booking for this work order must cover the current clock — its `start_time` at or before the clock and the clock before its `end_time` — otherwise `ERR_NO_ACTIVE_TEST_BOOKING` (HTTP 409). Either outcome increments the work order's `test_attempt_count` by 1 and moves the covering booking to `COMPLETED`, consuming the slot.

On `PASS`, the work order advances to `TEST_PASSED`, and when the `work_scope` is `OVERHAUL` or `WARRANTY_REWORK` the unit's `cycles_since_overhaul` resets to 0. On `FAIL`, the work order returns to `REPAIR_IN_PROGRESS` and a two-hop cascade fires: a new discrepancy card is created in `OPEN` status with `finding_text` set to 'ATP FAILURE: <atp_reference>' and `severity` `MAJOR`, and because that card opened, the work order's `open_discrepancy_count` increments by 1. The retest cycle — `READY_FOR_TEST → REPAIR_IN_PROGRESS → READY_FOR_TEST → TEST_PASSED` — requires a fresh booking, since the failed attempt consumed its window.

Release is the `Inspector`'s signature act. The work order must be in `TEST_PASSED` — this from-state check fires before the safety check, so a release attempted in the wrong state yields `ERR_WORK_ORDER_INVALID_STATE` even when the caller would also violate segregation of duties — and the same segregation-of-duties rule applies (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`). Certificate uniqueness is enforced at write: at most one `ISSUED` ReleaseCertificate may exist per work order. On success the system creates the certificate with a sequential `cert_number` of the form '8130-<zero-padded sequence>', `signed_by` set to the caller's id, `issued_at` set to the clock, and status `ISSUED`; it stamps `released_at` with the clock (the TAT stop) and captures `inspector_user_id` from the caller; it moves the unit's `condition_status` to `SERVICEABLE` and its `custody_status` to `AWAITING_SHIPMENT` — or to `IN_POOL` when the unit is `SHOP`-owned; it appends a `RELEASE_OVERHAUL` traceability event when the `work_scope` is `OVERHAUL` or `WARRANTY_REWORK` and a `RELEASE_REPAIR` event when the scope is `REPAIR`; and it increments the work order's `version` by 1, leaving the work order `RELEASED`. A work order's certificate is retrievable as an array of zero or one element.

Closure belongs to the `CustomerServiceRep` and requires the work order to be `RELEASED` with a work-order invoice already generated; either failure is `ERR_WORK_ORDER_INVALID_STATE`. Closure moves the unit's custody to `SHIPPED` for a `CUSTOMER`-owned unit, while a `SHOP`-owned unit stays `IN_POOL`. When the closed work order is a warranty rework — `work_scope` equal to `WARRANTY_REWORK` — the warranty claim whose `rework_work_order_id` names this work order bubbles up from `ACCEPTED` to `SETTLED`.

### 3.6. Work-Order Invoicing, TAT Penalties, and Payment

A `CustomerServiceRep` generates the work-order invoice once the work order is `RELEASED` with `released_at` recorded; a request against a work order in any other status is rejected with `ERR_WORK_ORDER_INVALID_STATE`, and a second invoice for the same work order is rejected with `ERR_INVOICE_ALREADY_EXISTS` (HTTP 409). The invoice's `source_type` is `WORK_ORDER`, with `work_order_id` populated. Its money lines assemble in a pinned order — per-line sums first, credits after: `labor_cents` equals the work order's `labor_charge_cents`; `parts_cents` is the sum of the already-rounded `extended_price_cents` over the work order's `ISSUED` requisitions; and `test_fee_cents` is the sum of the already-rounded `fee_cents` over the work order's `COMPLETED` bookings.

The TAT penalty credit is computed next. Elapsed hours are the difference between `released_at` and `received_at`, expressed in hours at two decimal places. Under the `ADJUSTED` variant the penalty basis is the elapsed hours minus `accumulated_delay_hours`, so customer decision time is excluded; under the `CALENDAR` variant the basis is the raw elapsed hours with delay not excluded, yielding a strictly larger penalty for identical timestamps whenever any delay accumulated. The excess is the amount by which the basis exceeds the customer's `contract_tat_hours`, floored at zero; the raw penalty is the excess multiplied by `tat_penalty_rate_cents_per_hour`; and the cap is `tat_penalty_cap_pct` percent of the subtotal of `labor_cents`, `parts_cents`, and `test_fee_cents`, rounded half up to whole cents. The resulting `penalty_credit_cents` is the smaller of the raw penalty and the cap — the cap applies last, after the raw penalty — and the invoice's `penalty_variant` records `ADJUSTED` or `CALENDAR` accordingly.

For a `WARRANTY_REWORK` work order the penalty mechanics switch off entirely: `penalty_credit_cents` is 0 and `penalty_variant` is `NONE`, while `warranty_credit_applied_cents` carries the claim credit computed in §3.9. The invoice `total_cents` for `REPAIR` or `OVERHAUL` scope is the sum of labor, parts, and test fees minus the penalty credit, floored at zero; for `WARRANTY_REWORK` it is the same sum minus the warranty credit, floored at zero. The invoice is created in `ISSUED` status with `issued_at` set to the clock, and the customer's `current_exposure_cents` increases by `total_cents` per §2.10.

Exchange and lease activity invoices itself without any generation call: an invoice with `source_type` `EXCHANGE` carries the settlement in `other_charge_cents` with `total_cents` equal to `settlement_total_cents` (§3.7), and an invoice with `source_type` `LEASE` carries the lease charge in `other_charge_cents` with `total_cents` equal to `total_charge_cents` (§3.8). Exactly one of `work_order_id`, `exchange_agreement_id`, or `lease_agreement_id` is populated on an invoice, according to its `source_type`, and `customer_id` identifies the billed customer. The invoice list accepts optional filters `work_order_id`, `lease_agreement_id`, `exchange_agreement_id`, `customer_id`, and `status`.

Payment is the `Customer`'s act of sending `amount_cents` against an invoice. The checks, in order: the invoice must be `ISSUED`, otherwise `ERR_INVOICE_INVALID_STATE`; the caller must be the billed customer, otherwise `ERR_NOT_RESOURCE_OWNER`; and `amount_cents` must equal `total_cents` exactly, otherwise `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). Success moves the invoice `ISSUED → PAID`, stamps `paid_at` with the clock, and subtracts `total_cents` from the customer's `current_exposure_cents` as the compensating action.

### 3.7. The Rotable Exchange Pool

An exchange lets a customer take a serviceable pool unit immediately and return a core later. A `CustomerServiceRep` opens the agreement with a `customer_id` and a `part_id`; it starts in `OPEN`. The exchange list accepts optional filters `customer_id`, `part_id`, `pool_unit_id`, `core_unit_id`, and `status`.

Fulfillment is a `CustomerServiceRep` action guarded by three checks in order: the agreement must be `OPEN` (otherwise `ERR_EXCHANGE_INVALID_STATE`); the pool selector must find a candidate; and the customer's `credit_hold` must be false (otherwise `ERR_CUSTOMER_CREDIT_HOLD`). The selector's eligibility set is every unit whose `part_id` equals the agreement's part, with `ownership` `SHOP`, `custody_status` `IN_POOL`, and `condition_status` `SERVICEABLE`; candidates rank by `cycles_since_overhaul` ascending with ties broken by `created_at` ascending — never by id; and an empty eligible set rejects fulfillment with `ERR_POOL_EMPTY` (HTTP 422), there being no deferred queue. A successful fulfillment records the chosen unit as `pool_unit_id`, stamps `fulfilled_at` with the clock, sets `core_due_date` to the calendar date of `fulfilled_at` plus 15 days, moves the selected unit's custody `IN_POOL → SHIPPED`, and appends an `EXCHANGE_OUT` traceability event. The agreement is then `FULFILLED`.

Core return is a `Technician` action carrying the `core_unit_id` and the `core_teardown_estimate_cents` from the core's teardown. The checks, in order: the agreement must be `FULFILLED` (`ERR_EXCHANGE_INVALID_STATE`); the core unit must be `CUSTOMER`-owned with its `owner_customer_id` equal to the agreement's customer, otherwise `ERR_UNIT_OWNER_MISMATCH`; and the core unit's part must equal the agreement's part, otherwise `ERR_CORE_PART_MISMATCH` (HTTP 422). What follows is a four-hop cascade in causal order.

The first hop inducts the core: its ownership flips from `CUSTOMER` to `SHOP`, `core_received_at` is stamped with the clock, and a `CORE_IN` traceability event is appended. The induction evaluates the core's BER status: `core_ber_flag` is true when `core_teardown_estimate_cents` is at least the part's BER threshold in cents — computed exactly as in §3.3, inclusive boundary and all. A non-BER core moves to custody `IN_POOL` and its condition improves `UNSERVICEABLE → SERVICEABLE`; a BER core moves to custody `IN_SHOP` and its condition stays `UNSERVICEABLE`.

The second hop computes the settlement in a pinned five-step order. First the core status is fixed as BER or non-BER (a defaulted core counts as missing). Second, `core_charge_cents` is set: zero for a non-BER core; for a BER core, 80 percent of the part's `replacement_value_cents`, rounded half up to whole cents; for a missing core, the full `replacement_value_cents`. Third, the late days are the whole days between `core_due_date` and the return date, never below zero (the defaulted path instead counts the 5 grace days elapsed at the sweep). Fourth, `late_fee_cents` is the smaller of the late days multiplied by $500.00 per day and the remaining headroom of `replacement_value_cents` minus `core_charge_cents`, floored at zero — this cap referencing the core charge is what makes the pinned order load-bearing. Fifth, `settlement_total_cents` is the flat $250.00 `admin_fee_cents` plus `core_charge_cents` plus `late_fee_cents`. With settlement computed, an invoice with `source_type` `EXCHANGE` is created in `ISSUED` status with `total_cents` equal to `settlement_total_cents`.

The third hop adds `settlement_total_cents` to the customer's `current_exposure_cents`, re-deriving `credit_hold`. The fourth hop moves the agreement to `CLOSED`.

Default is a system sweep, not a call: whenever the logical clock is set (§2.5), every `FULFILLED` agreement whose `core_due_date` plus 5 grace days falls before the current date moves to `DEFAULTED`. The settlement follows the same pinned order with the missing-core branch: `core_charge_cents` is the full `replacement_value_cents`; the late-fee cap of `replacement_value_cents` minus that charge is zero, so `late_fee_cents` collapses to 0; and `settlement_total_cents` is $250.00 plus `replacement_value_cents`. An `EXCHANGE` invoice is created `ISSUED`, the customer's exposure rises by the settlement, and the pool unit's ownership flips from `SHOP` to `CUSTOMER` — the customer keeps the pool unit.

### 3.8. Lease Agreements

A `CustomerServiceRep` leases a shop unit by sending `customer_id`, `unit_id`, `start_date`, `end_date`, `daily_rate_cents`, and an `expected_unit_version` per §2.7 — a mismatch with the unit's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The remaining checks follow in order: the lease's day-closed interval — the inclusive day range from `start_date` through `end_date` — must not share any day with an `ACTIVE` lease on the same unit, and a shared boundary day is a conflict, otherwise `ERR_LEASE_PERIOD_OVERLAP` (HTTP 409); and the unit must be leasable — `SHOP`-owned, `SERVICEABLE`, in custody `IN_POOL` or `ON_LEASE`, with `end_date` on or after `start_date` — otherwise `ERR_UNIT_NOT_LEASABLE` (HTTP 422). Because a leased unit legally sits in `ON_LEASE` and forward-dated non-overlapping leases remain legal, the version field is the only guard against acting on a stale read of the unit.

Creation starts the agreement in `ACTIVE`, moves the unit's custody to `ON_LEASE`, appends a `LEASE_OUT` traceability event, and increments the unit's `version` by 1 — the OCC anchor for the next lease writer. The lease list accepts optional filters `customer_id`, `unit_id`, and `status`.

Return is a `CustomerServiceRep` action requiring the agreement to be `ACTIVE` and the current date to be on or after `start_date`; either failure is `ERR_LEASE_INVALID_STATE` (HTTP 409). The return stamps `returned_at` with the current calendar date and computes the accrual: `billed_days` is the inclusive day count from `start_date` through the earlier of the return date and `end_date`; `overage_days` is the number of whole days by which the return date falls after `end_date`, never below zero — a return exactly on `end_date` has zero overage days. The base charge is `billed_days` multiplied by `daily_rate_cents`; the overage charge is `overage_days` multiplied by `daily_rate_cents` multiplied by 1.5, rounded half up to whole cents; and `total_charge_cents` is the base plus the overage. Return then moves the unit's custody `ON_LEASE → IN_POOL`, appends a `LEASE_RETURN` traceability event, creates an invoice with `source_type` `LEASE` in `ISSUED` status whose `total_cents` equals `total_charge_cents`, adds `total_charge_cents` to the customer's `current_exposure_cents`, and leaves the agreement `RETURNED`.

### 3.9. Warranty Claims and Rework

A `Customer` files a warranty claim against a closed overhaul by sending `original_work_order_id`, `claim_cycles_used`, `claim_months_used`, and a `failure_description`. The claim's `customer_id` is set from the caller's `X-User-ID`, and its `unit_id` is copied from the original work order as a plain reference. Two checks apply in order: the original work order must be `CLOSED`, otherwise `ERR_WARRANTY_REQUIRES_CLOSED_WO` (HTTP 409); and the claim must lie within both coverage ceilings, inclusive — `claim_cycles_used` at most the part's `warranty_cycle_limit` and `claim_months_used` at most its `warranty_month_limit` — otherwise `ERR_WARRANTY_LIMIT_EXCEEDED` (HTTP 422). A filed claim starts `SUBMITTED`, and the claim list accepts optional filters `customer_id`, `original_work_order_id`, `rework_work_order_id`, and `status`.

Review belongs to the `ShopManager`, who sends a `decision` of `ACCEPT` or `DENY` against a claim in `SUBMITTED` (otherwise `ERR_CLAIM_INVALID_STATE`). A `DENY` decision requires `denial_reason` to be present, otherwise `ERR_INVALID_REQUEST`, and moves the claim to `DENIED`.

An `ACCEPT` decision first computes the credit. The base is the original work-order invoice's `labor_cents` plus its `parts_cents`. The `credit_variant` is `FULL` when twice `claim_cycles_used` is at most `warranty_cycle_limit` — the customer used no more than half the warranted cycles — and `credit_cents` then equals the base; identical claim data under the prorated policy would pay strictly less. Otherwise the variant is `PRORATED`: the remaining cycles are `warranty_cycle_limit` minus `claim_cycles_used`, floored at zero, and `credit_cents` is the base multiplied by the remaining cycles and divided by `warranty_cycle_limit`, rounded half up to whole cents. A three-hop cascade follows: the claim moves to `ACCEPTED`; because it was accepted, a rework work order is auto-created with `customer_id` set to the claimant, `unit_id` set to the claim's unit, `work_scope` set to `WARRANTY_REWORK`, and `labor_estimate_cents` equal to the original work order's labor, starting directly in `REPAIR_IN_PROGRESS` — its id recorded as the claim's `rework_work_order_id`; and because that induction engaged the unit, the unit's custody moves to `IN_SHOP`, its condition moves to `UNSERVICEABLE`, and a `WARRANTY_INDUCT` traceability event is appended.

From there the rework order flows through repair, test, and release like any other — its invoice applying `warranty_credit_applied_cents` against the sum of labor, parts, and test fees (§3.6) with no TAT penalty (`penalty_variant` `NONE`). When the rework work order finally closes, the claim bubbles up from `ACCEPTED` to `SETTLED`, closing the loop.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads. The complete request and response semantics of each operation — its inputs, checks, and side effects — are defined by the narratives of §2 and §3; this table is the address map.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mro/customers` | Create customer with TAT/penalty/credit contract | ShopManager |
| GET | `/mro/customers/{customerId}` | Get customer (exposure, credit_hold) | All roles |
| POST | `/mro/part-catalog` | Create catalog part | ShopManager |
| GET | `/mro/part-catalog/{partId}` | Get catalog part | All roles |
| POST | `/mro/part-catalog/{id}/directives` | Register AD/SB against a part | ShopManager |
| GET | `/mro/part-catalog/{id}/directives` | List directives for part | All roles |
| GET | `/mro/part-catalog/{id}/units` | List units of part | All roles |
| POST | `/mro/units` | Register serialized unit (birth record) | CustomerServiceRep |
| GET | `/mro/units/{unitId}` | Get unit (both parallel status dimensions, version) | All roles |
| GET | `/mro/units` | Filtered unit list | All roles |
| GET | `/mro/customers/{id}/units` | List units owned by customer | All roles |
| GET | `/mro/units/{id}/traceability` | Back-to-birth event list, chronological | All roles |
| POST | `/mro/work-orders` | Induct unit: create work order | CustomerServiceRep |
| GET | `/mro/work-orders/{workOrderId}` | Get work order | All roles |
| GET | `/mro/customers/{id}/work-orders` | List customer work orders | All roles |
| GET | `/mro/units/{id}/work-orders` | List unit work orders | All roles |
| POST | `/mro/work-orders/{workOrderId}/teardown-complete` | Finish teardown | Technician |
| POST | `/mro/work-orders/{id}/discrepancies` | File discrepancy card | Technician |
| GET | `/mro/work-orders/{id}/discrepancies` | List discrepancy cards | All roles |
| POST | `/mro/discrepancies/{discrepancyId}/disposition` | Disposition an OPEN card | Technician |
| POST | `/mro/work-orders/{workOrderId}/quote` | Submit or supersede quote | CustomerServiceRep |
| POST | `/mro/work-orders/{workOrderId}/quote-approval` | Customer approves quote (OCC) | Customer |
| POST | `/mro/work-orders/{workOrderId}/quote-decline` | Customer declines quote (return or scrap) | Customer |
| POST | `/mro/work-orders/{workOrderId}/complete-repair` | Repair complete; request test | Technician |
| POST | `/mro/work-orders/{workOrderId}/test-results` | Record ATP result (pass/fail) | Inspector |
| POST | `/mro/work-orders/{workOrderId}/release` | Issue 8130 release certificate | Inspector |
| POST | `/mro/work-orders/{workOrderId}/close` | Close after shipment; requires work-order invoice | CustomerServiceRep |
| POST | `/mro/work-orders/{workOrderId}/directive-compliance` | Record AD/SB compliance | Technician |
| GET | `/mro/work-orders/{id}/directive-compliances` | List compliance records | All roles |
| POST | `/mro/work-orders/{id}/parts-requisitions` | Request part (OEM or PMA) | Technician |
| GET | `/mro/work-orders/{id}/parts-requisitions` | List requisitions | All roles |
| POST | `/mro/parts-requisitions/{requisitionId}/source-approval` | Buyer approves/rejects source; OEM override from PMA_REJECTED | PartsBuyer |
| POST | `/mro/parts-requisitions/{requisitionId}/pma-approval` | Customer approves/rejects PMA usage | Customer |
| POST | `/mro/parts-requisitions/{requisitionId}/receive` | Receive part; record cost, compute extended price | PartsBuyer |
| POST | `/mro/parts-requisitions/{requisitionId}/issue` | Issue part to work order | Technician |
| POST | `/mro/test-cells` | Create test cell | ShopManager |
| GET | `/mro/test-cells/{testCellId}` | Get test cell | All roles |
| POST | `/mro/test-cells/{id}/bookings` | Book cell window (half-open) | CustomerServiceRep |
| GET | `/mro/test-cells/{id}/bookings` | List cell bookings | All roles |
| GET | `/mro/work-orders/{id}/bookings` | List work-order bookings | All roles |
| POST | `/mro/test-cell-bookings/{bookingId}/cancel` | Cancel a BOOKED booking | CustomerServiceRep |
| GET | `/mro/work-orders/{id}/certificate` | Get 8130 certificate (array of 0-1) | All roles |
| POST | `/mro/exchange-agreements` | Open exchange agreement | CustomerServiceRep |
| GET | `/mro/exchange-agreements/{agreementId}` | Get exchange agreement | All roles |
| GET | `/mro/exchange-agreements` | Filtered exchange list | All roles |
| POST | `/mro/exchange-agreements/{agreementId}/fulfill` | Ship pool unit via selector; set core due date | CustomerServiceRep |
| POST | `/mro/exchange-agreements/{agreementId}/core-return` | Receive core; BER eval; settlement cascade | Technician |
| POST | `/mro/lease-agreements` | Lease shop unit (OCC on unit version) | CustomerServiceRep |
| GET | `/mro/lease-agreements/{agreementId}` | Get lease agreement | All roles |
| GET | `/mro/lease-agreements` | Filtered lease list | All roles |
| POST | `/mro/lease-agreements/{agreementId}/return` | Return leased unit; accrual, overage, invoice | CustomerServiceRep |
| POST | `/mro/warranty-claims` | Customer files warranty claim against closed work order | Customer |
| GET | `/mro/warranty-claims/{claimId}` | Get claim | All roles |
| GET | `/mro/warranty-claims` | Filtered claim list | All roles |
| POST | `/mro/warranty-claims/{claimId}/review` | Accept (spawns rework cascade) or deny | ShopManager |
| POST | `/mro/work-orders/{workOrderId}/invoice` | Generate work-order invoice (TAT penalty, per-line rounding) | CustomerServiceRep |
| GET | `/mro/invoices/{invoiceId}` | Get invoice | All roles |
| GET | `/mro/invoices` | Filtered invoice list | All roles |
| POST | `/mro/invoices/{invoiceId}/pay` | Customer pays exact invoice total | Customer |
| POST | `/mro/_clock/set_current_utc` | Set logical clock; runs exchange default sweep | ShopManager |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REQUISITION_NOT_FOUND` | 404 Not Found |
| `ERR_TEST_CELL_NOT_FOUND` | 404 Not Found |
| `ERR_EXCHANGE_NOT_FOUND` | 404 Not Found |
| `ERR_LEASE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_WORK_ORDER_INVALID_STATE` | 409 Conflict |
| `ERR_REQUISITION_INVALID_STATE` | 409 Conflict |
| `ERR_EXCHANGE_INVALID_STATE` | 409 Conflict |
| `ERR_LEASE_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_INVOICE_INVALID_STATE` | 409 Conflict |
| `ERR_DISCREPANCY_INVALID_STATE` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_OPEN_DISCREPANCIES` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
| `ERR_AD_COMPLIANCE_INCOMPLETE` | 403 Forbidden |
| `ERR_BER_SCRAP_ACK_REQUIRED` | 403 Forbidden |
| `ERR_SCRAP_REQUIRES_BER` | 409 Conflict |
| `ERR_NO_ACTIVE_TEST_BOOKING` | 409 Conflict |
| `ERR_TEST_CELL_OVERLAP` | 409 Conflict |
| `ERR_LEASE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_CELL_ATA_UNSUPPORTED` | 422 Unprocessable Entity |
| `ERR_UNIT_NOT_LEASABLE` | 422 Unprocessable Entity |
| `ERR_POOL_EMPTY` | 422 Unprocessable Entity |
| `ERR_UNIT_OWNER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CORE_PART_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INVOICE_ALREADY_EXISTS` | 409 Conflict |
| `ERR_WARRANTY_REQUIRES_CLOSED_WO` | 409 Conflict |
| `ERR_WARRANTY_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 Payment Required |
| `ERR_STALE_VERSION` | 412 Precondition Failed |

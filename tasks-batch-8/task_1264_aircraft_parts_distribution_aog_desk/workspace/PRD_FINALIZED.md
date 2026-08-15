# Aircraft Parts AOG Desk API — Product Requirements Document

## 1. Introduction

When an aircraft is grounded for want of a part, every hour on the tarmac costs an airline tens of thousands of dollars and ripples through crew schedules, connections, and passenger goodwill. This document specifies the Aircraft Parts AOG Desk API: the system of record for a 24/7 aircraft-on-the-ground parts distribution operation. The API covers the full commercial arc of an AOG event — filing the request, searching serialized stock, quoting under a validity clock, fulfilling under hazmat and export-control gates, and settling the long tail of core returns, rotable loans and leases, warranty claims, and customer returns.

Two concerns shape every design decision here. First, regulatory exposure: parts move with trace documentation of varying strength, some shipments carry dangerous goods, and some destinations are flatly denied, so compliance screening is a first-class gate rather than an afterthought. Second, money: the desk extends credit to operators, holds core deposits, bills loans and leases on divergent schedules, and recomputes customer priority tiers from observed return behavior — all against an append-only ledger that never lies about how a balance came to be. All business resources are mounted under `/aog`; a small platform surface for the logical clock and the nightly-style operations sweep sits outside that prefix.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must carry `X-User-ID` to identify the acting party and `X-User-Role` to declare the operational capacity in which they act. The system recognizes eight roles, spelled exactly as follows: `AogDeskAgent`, `CustomerContact`, `WarehouseOperator`, `ComplianceOfficer`, `FinanceController`, `WarrantyAdjuster`, `WarrantyApprover`, and `PlatformOps`. A request missing either header, or presenting a role outside this declared set, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is not permitted for the targeted endpoint is rejected with `ERR_FORBIDDEN`.

Role identity semantics differ by role and are normative:

- When `X-User-Role` is `CustomerContact`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare the resource's `customer_id` field to `X-User-ID`. A contact may file or cancel their own AOG requests, accept or reject their own quotes, and file warranty claims and return authorizations only against their own account.
- When `X-User-Role` is `AogDeskAgent`, `WarehouseOperator`, `ComplianceOfficer`, `FinanceController`, `WarrantyAdjuster`, `WarrantyApprover`, or `PlatformOps`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example, as `reviewed_by` on a `WarrantyClaim` when an adjuster performs a review — but it is never compared to any entity's `id`.

Read access is deliberately broad: every business role may call every read endpoint, with one scoping rule — when the caller is a `CustomerContact`, list responses are filtered to rows whose `customer_id` equals the caller's `X-User-ID`. `PlatformOps` holds no business-surface permissions at all; it exists solely to operate the logical clock and the operations sweep described in §2.10 and §3.9.

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

List endpoints are paged with the `limit` and `offset` query parameters. `limit` is the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` is the number of items skipped and defaults to 0.

Unless a specific collection states otherwise, every list endpoint returns resources sorted by creation timestamp in ascending order. Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. Individual collections may expose additional resource-specific filters; those are introduced with each workflow in §3.

### 2.4. Common Resource Properties

Every primary business resource — Customer, PartMaster, InventoryUnit, AogRequest, Quote, SalesOrder, OrderLine, Shipment, CharterSlot, CoreReturn, LoanAgreement, WarrantyClaim, and ReturnAuthorization — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed counter that begins at 1 when the resource is created and increments by exactly one on every subsequent mutation. Any state transition, cascade, or recomputation that changes a resource is a mutation and therefore advances its `version` and refreshes `updated_at`.

The AccountLedgerEntry is the single exception: it is append-only and immutable, so it carries only `id` and `created_at`. Both `updated_at` and `version` are absent from ledger entries.

### 2.5. The Append-Only Account Ledger

Every monetary movement against a customer account is recorded as an AccountLedgerEntry. The ledger is the single source of truth for credit exposure: entries are never updated or deleted, only appended. Each entry carries a `customer_id` identifying the account owner, an `entry_type` drawn from `INVOICE_DEBIT`, `CORE_DEPOSIT_DEBIT`, `FREIGHT_DEBIT`, `LOAN_DEBIT`, `LEASE_DEBIT`, `CORE_REFUND_CREDIT`, `WARRANTY_CREDIT`, `RESTOCK_CREDIT`, `WAIVER_CREDIT`, `PAYMENT_CREDIT`, `MANUAL_DEBIT`, or `MANUAL_CREDIT`, a positive `amount_cents`, and a polymorphic reference pair — `reference_type` (one of `SALES_ORDER`, `SHIPMENT`, `CORE_RETURN`, `LOAN_AGREEMENT`, `WARRANTY_CLAIM`, `RETURN_AUTH`, or `CUSTOMER`) together with `reference_id`, the `id` of the referenced entity, resolved through `reference_type` rather than through a fixed foreign key. Manual entries may also carry a free-text `memo` supplied by the finance operator.

A customer's `outstanding_balance_cents` is a read-only computed field: it always equals the sum of `amount_cents` over the debit entry types (`INVOICE_DEBIT`, `CORE_DEPOSIT_DEBIT`, `FREIGHT_DEBIT`, `LOAN_DEBIT`, `LEASE_DEBIT`, `MANUAL_DEBIT`) minus the sum over the credit entry types (`CORE_REFUND_CREDIT`, `WARRANTY_CREDIT`, `RESTOCK_CREDIT`, `WAIVER_CREDIT`, `PAYMENT_CREDIT`, `MANUAL_CREDIT`). The balance is recomputed synchronously within the same request that posts any entry — the posting and the recomputation are atomic. Cascades that post several entries in one request recompute the balance after each posting, so a mid-cascade read never observes a torn balance.

### 2.6. Money, Precision, and Time Arithmetic

All monetary values are integer cents. Division-heavy rules round half-up to whole cents, and each calculation pins its own rounding point: per-line amounts are rounded half-up per line before any summation; freight is rounded half-up exactly once at the very end of its formula; the core-return penalty rounds its accrual half-up before the fixed late fee is added. No calculation rounds twice unless its prose in §3 says so.

Durations are computed on a fixed grid: one day is exactly 86,400 seconds and one month is exactly 30 days. Each rule in §3 states whether it rounds elapsed time up (ceiling) or down (floor) to whole days or months; the two directions are not interchangeable. All instants compared against business deadlines are read from the logical clock (§2.10), never from wall-clock time.

### 2.7. Part Condition and Trace Documentation Ranks

Serialized inventory is graded on two independent axes. The physical `condition` of a unit is one of `NEW`, `OVERHAULED`, `SERVICEABLE`, or `AS_REMOVED`. The strength of its paperwork is its `trace_doc_level`, one of `TRACE_MISSING`, `TEARDOWN_REPORT`, `FAA_8130`, `EASA_FORM1`, or `DUAL_RELEASE`. Trace levels form a strict rank order used everywhere a minimum documentation standard is enforced: `TRACE_MISSING` ranks 0, `TEARDOWN_REPORT` ranks 1, `FAA_8130` ranks 2, `EASA_FORM1` ranks 3, and `DUAL_RELEASE` ranks 4. A unit satisfies a minimum trace requirement exactly when its own rank is greater than or equal to the required rank — a request floor of `FAA_8130` admits `FAA_8130`, `EASA_FORM1`, and `DUAL_RELEASE` paperwork, and nothing weaker.

### 2.8. Hazmat, Export Control, and Compliance Segregation

Every catalog part declares a `hazmat_class` — `NONE`, `CLASS_2`, `CLASS_3`, or `CLASS_9` — and an `export_control_code` — `EAR99`, `EAR9X610`, or `ITAR`. Any part whose hazmat class is not `NONE` forces a dangerous-goods declaration reference onto the shipment at tender time; any part whose export code is not `EAR99` forces export screening and an export license reference at tender. Shipments whose destination country is one of `KP`, `CU`, `IR`, or `SY` are always refused at tender. These gates are enforced by the system at the moment of tender, and the screening decision itself belongs exclusively to the `ComplianceOfficer`, who is deliberately kept away from the physical flow of goods: a compliance officer can certify trace documentation and record screening outcomes but can never allocate, tender, or deliver.

### 2.9. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control; no other endpoint takes a version field.

- Accepting a quote requires the request body to carry `expected_quote_version`, holding the `version` of the quote as the customer last observed it. If the quote's current `version` no longer matches — for example because a revise cycle re-priced the quote after the customer read it — the acceptance is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412), so a customer is never bound to terms they never saw.
- Revising a quote likewise requires `expected_quote_version`. A revise whose expected version trails the quote's current `version` — another writer may already have revised it back to `DRAFT` and even re-issued it — is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412).
- Posting a manual or payment adjustment against a customer account requires `expected_customer_version`. Ledger cascades (invoices, deposit debits, waivers) advance the customer's `version`, so an adjustment carrying a stale expectation would apply to a balance the controller never observed; it is rejected with `ERR_STALE_CUSTOMER_VERSION` (HTTP 412).

Endpoints not named above perform no version check and accept no expected-version field.

### 2.10. The Logical Clock

The system runs on a logical clock, not wall-clock time. At startup the clock reads exactly `2026-05-01T00:00:00Z`, and it advances only when a `PlatformOps` operator sets it to a supplied `to_iso8601` instant. The clock is monotonic: an attempt to move it backwards is rejected with `ERR_CLOCK_REGRESSION`. Once set, the clock never falls back to wall-clock time. The clock-setting capability returns the resulting `current_utc`. Every deadline comparison in this document — quote expiry, core and loan due instants, warranty windows, return windows, sweep processing — reads this clock.

### 2.11. Validation Order

When several checks could reject the same request, the server evaluates them in a fixed priority order so the surfaced error is deterministic. Lower-numbered gates run first:

1. **Authentication.** `X-User-Role` and `X-User-ID` must be present and the role must be one of the eight declared roles; failures yield `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. **Authorization.** The role must be permitted for the endpoint, and a `CustomerContact` caller may act only on resources whose `customer_id` equals their `X-User-ID`; failures yield `ERR_FORBIDDEN` (403).
3. **Existence.** Path identifiers are validated left to right, then body foreign-key references; each missing resource surfaces its own not-found code: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PART_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_AOG_REQUEST_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_CORE_RETURN_NOT_FOUND`, `ERR_LOAN_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RMA_NOT_FOUND`, or `ERR_CHARTER_SLOT_NOT_FOUND` (all 404).
4. **State.** The target entity's status must permit the transition — including lazy quote expiry, under which an `ISSUED` quote whose `expires_at` has passed is treated as `EXPIRED` even if no sweep has run. Failures surface `ERR_INVALID_STATE`, `ERR_QUOTE_EXPIRED`, or `ERR_CUSTOMER_SUSPENDED` (all 409).
5. **Optimistic concurrency.** On the three OCC-guarded writes, the expected version must match; failures surface `ERR_STALE_QUOTE_VERSION` or `ERR_STALE_CUSTOMER_VERSION` (412).
6. **Segregation of duties.** Warranty approval or rejection must not come from the reviewer; failures surface `ERR_SEGREGATION_OF_DUTIES` (403).
7. **Business safety.** Hazmat declaration, export license, denied-destination, trace-rank, and condition requirements; failures surface `ERR_HAZMAT_DECLARATION_MISSING`, `ERR_EXPORT_LICENSE_REQUIRED`, `ERR_EXPORT_DESTINATION_DENIED`, `ERR_TRACE_DOC_INSUFFICIENT`, or `ERR_CONDITION_NOT_ACCEPTABLE` (all 422).
8. **Business temporal.** Future-dated deadlines, valid loan windows, warranty and return windows, and tier-capped validity; failures surface `ERR_NEEDED_BY_IN_PAST`, `ERR_LOAN_WINDOW_IN_PAST`, `ERR_WARRANTY_PERIOD_ELAPSED`, `ERR_RETURN_WINDOW_CLOSED`, or `ERR_VALIDITY_EXCEEDS_TIER_CAP` (all 422).
9. **Business constraint.** Uniqueness, overlap, and availability rules; failures surface `ERR_DUPLICATE_SERIAL`, `ERR_UNIT_NOT_AVAILABLE`, `ERR_LOAN_WINDOW_OVERLAP`, `ERR_CHARTER_WINDOW_OVERLAP`, `ERR_LINE_ALREADY_ALLOCATED`, or `ERR_DUPLICATE_ACTIVE_QUOTE` (all 409).
10. **Business fiscal.** Credit exposure, reactivation, and penalty-waiver caps; failures surface `ERR_CREDIT_LIMIT_EXCEEDED` or `ERR_WAIVER_EXCEEDS_PENALTY` (both 402).

Malformed payloads — a missing required field, an invalid enum value, a non-positive quantity, a malformed timestamp, or a forbidden field combination — are rejected with `ERR_INVALID_REQUEST` (400) before any business-rule evaluation begins.

## 3. Business Logic & Workflows

### 3.1. Customer Onboarding, Credit, and Account Standing

A `FinanceController` onboards an operator by supplying the legal `name`, the `country_code` of the operator's principal base, and a `credit_limit_cents` ceiling that must be zero or positive. The new account starts `ACTIVE` with `priority_tier` `STANDARD`, a zeroed `outstanding_balance_cents`, zeroed trailing-window counters (`core_returns_settled_180d`, `core_returns_on_time_180d`), zero `warranty_fraud_flags`, and `version` 1. The customer directory can be paged with `limit` and `offset` and narrowed with the `status` and `priority_tier` filters.

Account standing is enforced at two money-sensitive moments. A `SUSPENDED` customer cannot have a quote issued or accepted on its behalf, and cannot take out a new loan; any of those attempts is rejected with `ERR_CUSTOMER_SUSPENDED`. Suspension itself happens two ways: a `FinanceController` may suspend an `ACTIVE` account directly (any other starting state is `ERR_INVALID_STATE`), and the operations sweep suspends automatically — see §3.9 — whenever the outstanding balance is strictly greater than the credit limit; an account sitting exactly at its limit is not suspended. Either path transitions the customer from `ACTIVE` to `SUSPENDED` and increments `version` by 1. Reactivation moves a `SUSPENDED` account back to `ACTIVE` only while its balance is less than or equal to its limit; otherwise the reactivation is refused with `ERR_CREDIT_LIMIT_EXCEEDED`. Reactivation also increments `version` by 1.

Manual finance interventions flow through the credit-adjustment capability, which is OCC-guarded per §2.9: the controller supplies an `entry_type` of `PAYMENT_CREDIT`, `MANUAL_DEBIT`, or `MANUAL_CREDIT`, a positive `amount_cents`, their `expected_customer_version`, and optionally a `memo` and an `order_id`. Supplying `order_id` anchors the entry's reference to that sales order and is mandatory for `PAYMENT_CREDIT`; without it, the entry references the customer itself. The adjustment posts the ledger entry, recomputes `outstanding_balance_cents` in the same request, and increments the customer's `version` by 1. When cumulative `PAYMENT_CREDIT` entries referencing an invoiced order reach or exceed that order's `invoiced_cents`, the order's payment dimension flips from `INVOICED` to `PAID` automatically. The full ledger history of an account is readable through the customer ledger collection — paged by `limit` and `offset`, filterable by `entry_type`, and, as an explicit exception to the default ordering, sorted newest first. Note that this ledger collection is not exposed to the `CustomerContact` role.

### 3.2. Catalog Registration and Serialized Inventory

A `WarehouseOperator` registers a catalog part with its unique `part_number`, a free-text `description`, a positive `list_price_cents`, and a `rotable` flag marking whether the part is repairable and therefore eligible for `EXCHANGE`, `LOAN`, and `LEASE` commerce. Rotables must declare a positive `core_value_cents` deposit; for non-rotables the core value must be exactly zero, which is also its default when omitted. Optional registration fields include `hazmat_class` (defaulting to `NONE`), `export_control_code` (defaulting to `EAR99`), and `warranty_months` (defaulting to 12 and always positive). Each part exposes two read-only stock counters, `available_count` and `reserved_count`, both starting at zero; the parts collection supports `limit`, `offset`, and a `part_number` filter.

Serialized stock arrives as InventoryUnit records carrying the parent `part_id`, a `serial_number` unique within that part (a duplicate is refused with `ERR_DUPLICATE_SERIAL`), a `condition`, a `trace_doc_level`, and a `warehouse_code`. New units are born `AVAILABLE`, and registration raises the part's `available_count` by one. The unit lifecycle then spans `AVAILABLE`, `RESERVED`, `ALLOCATED`, `SHIPPED`, `SOLD`, `ON_LOAN`, `UNDER_INSPECTION`, `QUARANTINED`, and terminal `SCRAPPED`; while a unit is pinned by a sourcing search, its `reserved_by_request_id` points at the reserving request and is empty otherwise. The inventory collection pages with `limit` and `offset` and filters by `part_id`, `status`, `condition`, and `reserved_by_request_id`.

Paperwork can be strengthened after the fact. A `ComplianceOfficer` certifying a unit supplies a new `trace_doc_level`; the new level must rank at or above the current rank per §2.7 — a downgrade is rejected with `ERR_INVALID_REQUEST` — and a successful certification increments the unit's `version` by 1.

### 3.3. Filing and Sourcing an AOG Request

When an aircraft goes tech, an `AogDeskAgent` — or the stranded operator's own `CustomerContact` — files a request naming the `customer_id`, the grounded `aircraft_tail`, the `airport_code` where it sits, the needed `part_id`, and a `quantity` of at least one. The filer also declares which conditions are tolerable via `condition_acceptable` (a non-empty selection from the four condition grades), a minimum paperwork floor `min_trace_doc`, and a hard dispatch deadline `needed_by_utc` that must lie strictly after the current clock — a deadline in the past or at the present instant is rejected with `ERR_NEEDED_BY_IN_PAST`. A `CustomerContact` filing on someone else's account is rejected with `ERR_FORBIDDEN`. New requests are born `OPEN` with `escalated` false, no `reserved_unit_id`, and `last_search_candidate_count` zero; the collection filters by `customer_id`, `status`, `part_id`, and `reserved_unit_id` alongside the standard paging parameters.

Sourcing is a deliberate act. When a desk agent runs the sourcing search, the system considers only units of the requested part that are `AVAILABLE`, whose `condition` is in the request's acceptable set, and whose trace rank is at least the request's `min_trace_doc` rank. Eligible units are ranked oldest first by creation timestamp — first-in-first-out stock rotation, with no tie-break needed because creation timestamps are unique — and the first unit wins. If the request already pinned a unit from an earlier search, that pin is released first (the unit returns from `RESERVED` to `AVAILABLE`, its `reserved_by_request_id` is cleared, and the part's counters shift back). The winner then moves `AVAILABLE` → `RESERVED`, its `reserved_by_request_id` is set to the request, the request's `reserved_unit_id` points at the unit, and `last_search_candidate_count` records the size of the eligible pool. An empty pool changes nothing: the request stays `OPEN`, no reservation is made, the candidate count is recorded as zero, and the search answers `ERR_NO_SOURCE_AVAILABLE` (422).

Two further acts shape a live request. Escalation — a desk agent's signal that this airframe cannot wait for routine freight — sets `escalated` true and increments the request's `version`; from that moment on, every freight computation for the request carries the escalation multiplier described in §3.4. Cancellation ends a request: from `OPEN`, either a desk agent or the request's own customer contact may cancel (a contact canceling another operator's request draws `ERR_FORBIDDEN`), and any pinned unit is released back to `AVAILABLE` with `reserved_unit_id` nulled. From `QUOTED`, only a desk agent may cancel, and the cancellation cascades: every non-terminal quote on the request — anything in `DRAFT` or `ISSUED` — is cancelled in the same request, and the pinned unit is likewise released. `FULFILLED`, `CLOSED`, and `CANCELLED` are terminal; a fulfilled request closes automatically once every core return and loan derived from its order has settled.

### 3.4. Quoting, Pricing, and the Revision Cycle

A desk agent drafts a Quote against a live request by supplying the `aog_request_id` and `customer_id` (which must match the request's customer), the commercial `lines`, a `validity_hours` window of at least one hour, the routing facts `distance_km` and `chargeable_weight_kg` (both at least 1), the `destination_country`, and optionally a `freight_mode` that defaults to `STANDARD`. Each line in `lines` names a `part_id`, a `quantity`, a `sale_type` of `OUTRIGHT`, `EXCHANGE`, `LOAN`, or `LEASE`, a negotiated `unit_price_cents`, a `discount_pct` that is a fraction at least zero and strictly less than one, a `condition_required`, and — only when the sale type is `LEASE` — an integer `lease_periods` of at least 1. Lines selling by `EXCHANGE`, `LOAN`, or `LEASE` must target a rotable part, and `LOAN` and `LEASE` lines must have quantity exactly one; violations are rejected with `ERR_INVALID_REQUEST`. A request may carry at most one non-terminal quote: drafting while a `DRAFT` or `ISSUED` quote already exists for the request is refused with `ERR_DUPLICATE_ACTIVE_QUOTE`.

Pricing happens at three moments — drafting, revision, and issue — and follows a pinned order. Each line's total is the `unit_price_cents` multiplied by the line `quantity` and by one minus `discount_pct`, rounded half-up to whole cents per line; `subtotal_cents` is then the sum of those already-rounded line totals. Rounding each line first and only then summing is mandatory — summing unrounded products and rounding once is forbidden, because the two orders can differ by at least one cent. Next, the small-order handling fee is bracketed on the pre-fee subtotal alone: a subtotal strictly below 100,000 cents draws a `handling_fee_cents` of 9,500; a subtotal from 100,000 up to and including 1,000,000 cents draws 4,500; anything above 1,000,000 draws none. The bracket is never evaluated on a post-fee amount. Then `tier_fee_cents` is the subtotal plus the handling fee, multiplied by the tier percentage — six percent for `STANDARD`, three percent for `PRIORITY`, zero percent for `PLATINUM` — rounded half-up to whole cents. While the quote is in `DRAFT`, the customer's current `priority_tier` supplies the percentage; once issued, the `tier_at_issue` snapshot governs every later recomputation. Finally, `total_cents` is the subtotal plus the handling fee plus the tier fee — freight is never part of the total.

Freight is computed at the same three moments and stored on the quote as `freight_cost_cents`. The per-kilogram base rate follows the chargeable weight: 1,200 cents per kilogram at or below 5 kilograms, 900 above 5 and at most 20, 650 above 20 and at most 100, and 480 beyond 100. A distance multiplier applies: 1.0 when the route is strictly under 1,000 kilometers, 1.35 from 1,000 up to and including 4,000, and 1.8 beyond 4,000. For `STANDARD` freight the base is the per-kilogram rate times the chargeable weight times the distance multiplier, with no premium; `HOT_SHOT` adds a flat 250,000-cent premium to the same base; `CHARTER` ignores weight entirely and takes the greater of 750,000 cents or 2,900 cents per kilometer as its base, again with no premium. Base plus premium forms the freight subtotal, which is then multiplied by 1.25 when any line's part carries a hazmat class other than `NONE`, and multiplied by 1.25 again when the originating request has been escalated. The result is rounded half-up to whole cents exactly once, at the very end.

One more figure rides on every quote: `max_penalty_cents`, a provisional worst-case disclosure equal to the sum of each `EXCHANGE` line's core value multiplied by its quantity — the exposure the customer would face if every core were forfeited. This forward-looking number deliberately ignores the calendar; the chronological penalty actually charged at core receipt is a different calculation, described in §3.6.

Issue is the desk agent's act of putting the quote on the clock. Issuing requires the customer to be `ACTIVE` (`ERR_CUSTOMER_SUSPENDED` otherwise) and the `validity_hours` to fit the cap of the tier in effect at issue time — 24 hours for `STANDARD`, 48 for `PRIORITY`, 72 for `PLATINUM` — with an over-cap window refused as `ERR_VALIDITY_EXCEEDS_TIER_CAP`. A successful issue moves the quote `DRAFT` → `ISSUED`, snapshots `tier_at_issue` from the customer, stamps `issued_at` with the clock, sets `expires_at` exactly `validity_hours` hours later, recomputes every computed price field, cascades the request from `OPEN` to `QUOTED`, and increments the quote's `version`. While `DRAFT`, the fields `tier_at_issue`, `issued_at`, and `expires_at` are empty.

Acceptance belongs to the customer contact, who must own the quote (`ERR_FORBIDDEN` otherwise) and supply `expected_quote_version` per §2.9. The checks surface in the §2.11 order: a quote not in `ISSUED` is `ERR_INVALID_STATE`; an `ISSUED` quote whose `expires_at` has passed is treated as `EXPIRED` — lazily, even if no sweep has run — and refuses with `ERR_QUOTE_EXPIRED` (acceptance exactly at the expiry instant still succeeds); a suspended customer surfaces `ERR_CUSTOMER_SUSPENDED`; a stale `expected_quote_version` surfaces `ERR_STALE_QUOTE_VERSION`; and finally the fiscal gate — `ERR_CREDIT_LIMIT_EXCEEDED` when the customer's outstanding balance plus the quote's `total_cents` plus the core deposits over its `EXCHANGE` lines is strictly greater than `credit_limit_cents`. Equality at the credit limit passes. A clean acceptance is a large atomic cascade: a SalesOrder is created referencing the quote (one order per quote), carrying `fulfillment_status` `PENDING_ALLOCATION`, `compliance_status` `PENDING_SCREENING`, `payment_status` `UNBILLED`, and the quote's `freight_mode`, `distance_km`, `chargeable_weight_kg`, and `destination_country`; each quote line explodes into one OrderLine per unit — every OrderLine has `quantity` 1, its `line_total_cents` fixed at creation as the unit price times one minus the line discount rounded half-up, `allocation_status` `PENDING`, no `allocated_unit_id`, and `lease_periods` carried only on `LEASE` lines; a unit pinned on the request stays `RESERVED` awaiting allocation; the request moves `QUOTED` → `FULFILLING`; and the quote's `version` increments.

Rejection is the customer's other answer: an `ISSUED` quote moves to `REJECTED`, incrementing `version`. And the desk gets its loop back: a desk agent may revise a `REJECTED` or `EXPIRED` quote back to `DRAFT`, supplying `expected_quote_version` per §2.9 plus any overrides among `lines`, `validity_hours`, `freight_mode`, `distance_km`, `chargeable_weight_kg`, and `destination_country`. The revision increments `revision_count` — which starts at zero on a freshly drafted quote — by 1, clears `issued_at`, `expires_at`, and `tier_at_issue`, recomputes all price fields, and increments `version` — the cycle `DRAFT` → `ISSUED` → `REJECTED` → `DRAFT` may repeat as often as negotiation demands. A draft the desk abandons moves `DRAFT` → `CANCELLED`, incrementing `version`. Quotes and requests both expose their collections with paging plus filters — `customer_id`, `status`, and `aog_request_id` on quotes — and a request also exposes its quote history as a sub-collection.

### 3.5. Allocation, Compliance Screening, and Shipment

A SalesOrder tracks three independent dimensions in parallel: fulfillment (`PENDING_ALLOCATION`, `ALLOCATED`, `SHIPPED`, `DELIVERED`, `CLOSED`), compliance (`PENDING_SCREENING`, `CLEARED`, `EXPORT_HELD`, `BLOCKED`), and payment (`UNBILLED`, `INVOICED`, `PAID`). The orders collection filters by `quote_id`, `customer_id`, and `fulfillment_status`; order lines filter by `order_id`, `part_id`, `allocated_unit_id`, and `allocation_status`.

A `WarehouseOperator` allocates stock to a line either by naming an explicit `unit_id` or by letting the line claim the unit its originating request pinned. The chosen unit must be `AVAILABLE` — or `RESERVED` for this very request when claiming the pin; anything else is `ERR_UNIT_NOT_AVAILABLE`, as is a pin-claim when no unit is pinned. Two merchandise checks follow: the unit's `condition` must equal the line's `condition_required` (`ERR_CONDITION_NOT_ACCEPTABLE`), and its trace rank must meet the originating request's `min_trace_doc` rank (`ERR_TRACE_DOC_INSUFFICIENT`). Allocating a line already in `ALLOCATED` is `ERR_LINE_ALREADY_ALLOCATED`. A successful allocation moves the unit to `ALLOCATED` (from `RESERVED` or directly from `AVAILABLE`, adjusting the part's counters accordingly), sets the line's `allocated_unit_id` and flips `allocation_status` to `ALLOCATED`, and increments the line's `version`; when every line of the order is allocated, fulfillment flips `PENDING_ALLOCATION` → `ALLOCATED` and the order's `version` increments. Release is the compensating act: it returns the unit `ALLOCATED` → `AVAILABLE`, resets the line to `PENDING` with `allocated_unit_id` nulled, reverts an order that had flipped back to `PENDING_ALLOCATION`, and increments the line's `version`. Release is refused with `ERR_INVALID_STATE` once fulfillment has reached `SHIPPED`, `DELIVERED`, or `CLOSED`; before allocation, releasing simply returns the still-`RESERVED` pinned unit to `AVAILABLE`.

Compliance screening belongs to the `ComplianceOfficer`, who records a `decision` of `CLEARED`, `EXPORT_HELD`, or `BLOCKED`, optionally with a `decision_memo`. From `PENDING_SCREENING` an order may clear or be export-held; from `EXPORT_HELD` it may clear or be blocked. Each decision increments the order's `version`. `BLOCKED` is reserved for a denied destination or a denied export license — the grounds are recorded in the memo — and it is destructive: every allocated line is released (units `ALLOCATED` → `AVAILABLE`, lines back to `PENDING`), fulfillment reverts from `ALLOCATED` to `PENDING_ALLOCATION`, and the version increments.

When stock and paperwork are both in order, the warehouse creates the order's shipment — exactly one per order, a second attempt drawing `ERR_DUPLICATE_SHIPMENT` — supplying the `order_id` and, as the freight mode demands, `hazmat_declaration_ref`, `export_license_ref`, or the charter trio `depart_at`, `arrive_at`, and `charter_slot_id`. Charter fields are mandatory for `CHARTER` freight and forbidden otherwise (`ERR_INVALID_REQUEST`); `arrive_at` must be strictly after `depart_at`. A charter booking also checks the slot's diary: a new booking whose window comes within 120 minutes of another booking on the same slot is refused with `ERR_CHARTER_WINDOW_OVERLAP`, while a gap of at least 120 minutes is allowed. Declaration references may be supplied at creation or at tender; the effective reference at tender is the tender payload's value when present, otherwise the creation-time value. At creation the shipment is `DRAFT`, its `freight_cost_cents` is copied from the order's quote, and a `FREIGHT_DEBIT` for that amount posts immediately against the customer with the balance recomputed. Charter slots themselves are registered by desk agents with a unique `tail_number` and a `home_base`, born `OPEN`, listed with a `status` filter; shipments list with `order_id`, `charter_slot_id`, and `status` filters.

Tender is the point of no return and carries the §2.8 gates in the §2.11 order: the order's compliance must be `CLEARED` (`ERR_COMPLIANCE_NOT_CLEARED`) and fulfillment must be `ALLOCATED` (`ERR_INVALID_STATE`); then, when any line's part is hazmat-classed, a `hazmat_declaration_ref` must be present (`ERR_HAZMAT_DECLARATION_MISSING`); when any line's part is export-controlled, an `export_license_ref` must be present (`ERR_EXPORT_LICENSE_REQUIRED`); and a `destination_country` of `KP`, `CU`, `IR`, or `SY` is always refused with `ERR_EXPORT_DESTINATION_DENIED`. A clean tender moves the shipment `DRAFT` → `TENDERED`, every allocated unit to `SHIPPED`, the order's fulfillment `ALLOCATED` → `SHIPPED`, and — for charter freight — the slot `OPEN` → `BOOKED`; the shipment then falls through to `IN_TRANSIT` automatically. Delivery confirms arrival: the shipment moves `IN_TRANSIT` → `DELIVERED`, and the full delivery cascade fires in one request. Every unit on an `OUTRIGHT` or `EXCHANGE` line becomes `SOLD`; every unit on a `LOAN` or `LEASE` line becomes `ON_LOAN`. The order's fulfillment reaches `DELIVERED`, its payment flips `UNBILLED` → `INVOICED` with `invoiced_cents` set to the quote's `total_cents` (goods and fees only — freight and core deposits are excluded), an `INVOICE_DEBIT` for that amount posts against the customer, a `CORE_DEPOSIT_DEBIT` posts for each `EXCHANGE` line at the part's core value times the line quantity, and the balance recomputes after each posting. Every line's `delivered_at` stamps the clock. One CoreReturn springs up per `EXCHANGE` line with its due instant exactly 21 days after delivery, and one LoanAgreement per `LOAN` or `LEASE` line, born `ACTIVE` with `start_at` at the delivery clock — a loan falling due 30 days later, a lease after its contracted periods. Finally the request advances `FULFILLING` → `FULFILLED`, and a delivered charter releases its slot `BOOKED` → `OPEN`. If a charter shipment is still `TENDERED` more than 48 hours past its planned `arrive_at`, the sweep marks it `EXCEPTION`; a warehouse re-tender — subject to the same tender gates — carries it from `EXCEPTION` straight back to `IN_TRANSIT`. A slot may also be un-booked by a desk agent (`BOOKED` → `OPEN`) only while no `TENDERED` or `IN_TRANSIT` shipment references it — otherwise `ERR_INVALID_STATE` — and a slot never needed again moves `OPEN` → `RELEASED`.

Closure is earned, not declared: the closure condition — every core return and loan born of the order has settled — is evaluated automatically at the end of the delivery cascade itself and again whenever one of those core returns or loans settles. The moment the condition holds, the order's fulfillment moves `DELIVERED` → `CLOSED` and the originating request moves `FULFILLED` → `CLOSED`, both automatically and within the same request. An order that spawns no core returns and no loans — an all-`OUTRIGHT` order — satisfies the condition vacuously at delivery, so it closes, and its request closes, inside the delivery request itself.

### 3.6. Core Returns and the Deposit Waterfall

Each CoreReturn tracks one exploded `EXCHANGE` line: it carries the `order_line_id`, the denormalized `customer_id`, a `core_value_cents` snapshot of the part's core value times the line quantity taken at delivery, and a `due_at` exactly 21 days after delivery. The collection filters by `order_line_id`, `customer_id`, and `status`. While the core is out, the return sits `OPEN`; a sweep that finds the due instant passed flips it `OPEN` → `OVERDUE` and increments its `version`.

Physical receipt — from either `OPEN` or `OVERDUE` — is a warehouse act carrying the incoming `core_serial_number`. The return moves to `RECEIVED`, `received_at` stamps the clock, and the final penalty computes chronologically: `days_overdue` is zero when the core arrives on or before its due instant, otherwise the lateness in whole days rounded up. The accrual charges one-half of one percent of the core deposit for each of the first seven overdue days, plus one percent of the deposit for each additional day from day eight through day twenty-one. The final `penalty_cents` is the smaller of the full core deposit and the sum of a fixed 25,000-cent late fee — charged whenever the core is at least one day overdue — with the accrual rounded half-up to whole cents before the fee is added. Note this chronological figure can differ sharply from the provisional disclosure on the quote: the quote's worst case assumed total forfeiture regardless of the calendar, while receipt prices the actual lateness. Receipt also mints an inbound InventoryUnit for the same part, `AS_REMOVED`, born `UNDER_INSPECTION`, with the payload's serial.

Inspection settles the deposit waterfall, with the warehouse recording a `verdict` of `ACCEPTED`, `ACCEPTED_WITH_PENALTY`, or `REJECTED` — a `REJECTED` verdict requires a `reject_reason`, and `ACCEPTED_WITH_PENALTY` requires a positive `penalty_cents`, both else `ERR_INVALID_REQUEST`. On `ACCEPTED`, `refunded_cents` is the whole `core_value_cents`, `penalty_retained_cents` and `forfeited_cents` are zero, and the inbound unit moves `UNDER_INSPECTION` → `AVAILABLE`, raising the part's `available_count`. On `ACCEPTED_WITH_PENALTY`, `penalty_retained_cents` is the accrued penalty minus whatever has been waived, `refunded_cents` is the remainder of the deposit, `forfeited_cents` is zero, and the unit likewise returns to `AVAILABLE`. On `REJECTED`, the deposit minus any waiver is `forfeited_cents`, `refunded_cents` is zero, `penalty_retained_cents` keeps only the waived portion, and the unit is `QUARANTINED`. Whenever the refund is positive, a `CORE_REFUND_CREDIT` posts against the customer and the balance recomputes; the return then settles, and the settled return feeds the trailing-window tier metrics at the next sweep. One invariant holds at settlement: the deposit equals refund plus penalty retained plus forfeiture.

A `FinanceController` may soften a penalty while the return is `OVERDUE` or `RECEIVED` by waiving an `amount_cents` no greater than the penalty minus what has already been waived — an over-large waiver is refused with `ERR_WAIVER_EXCEEDS_PENALTY`. Waiving accumulates into `penalty_waived_cents` and posts a `WAIVER_CREDIT` with balance recompute; this capability is the only source of waiver credits — inspection never posts one implicitly.

### 3.7. Desk-Direct and Order-Derived Loans and Leases

Rotable units circulate under two contract shapes. A LoanAgreement — whether born of an order delivery (its `order_line_id` set) or struck at the desk — carries the borrowing `customer_id`, the `unit_id` going out, a `loan_type` of `LOAN` or `LEASE`, a positive `daily_rate_cents`, a `start_at` that must not lie in the past, and a `due_at` strictly after `start_at`. For a `LEASE`, `lease_periods` is required and `due_at` must equal `start_at` plus that many 30-day periods; for a `LOAN`, `lease_periods` is forbidden. Violations of these window rules — a past start, a due instant not after start, a mismatched lease horizon, or `lease_periods` on a loan — surface as `ERR_LOAN_WINDOW_IN_PAST` or `ERR_INVALID_REQUEST` as applicable.

Desk-direct lending is a desk agent's act with three guards beyond the window rules, surfacing in §2.11 order: a `SUSPENDED` customer is refused with `ERR_CUSTOMER_SUSPENDED`; the unit must not be `SOLD`, `SCRAPPED`, or `QUARANTINED` (`ERR_UNIT_NOT_AVAILABLE`); and the new window must not intersect another `ACTIVE` or `OVERDUE` loan of the same unit — the window is half-open, so an existing loan ending exactly when the new one starts is allowed, and any genuine overlap is `ERR_LOAN_WINDOW_OVERLAP`. The loan book is the unit's schedule: a desk-direct loan does not change the unit's status. A new lease bills forward from activation — the first period's `LEASE_DEBIT` of 30 days times the daily rate posts at activation with the balance recomputed — and the sweep posts further period debits as 30-day boundaries cross (§3.9). The loans collection filters by `customer_id`, `unit_id`, `order_line_id`, and `status`. A sweep that finds an `ACTIVE` loan past `due_at` flips it to `OVERDUE`, incrementing `version`.

Return settles the bill, with the warehouse recording a `damage_flag`. The actual days run from `start_at` to `returned_at` in whole days rounded up, minimum one. A `LOAN` bills chronologically at return: on-time days are the smaller of the actual days and the whole days between start and due, late days are the remainder, and `billed_cents` is the on-time days at the daily rate plus the late days at one and a half times the daily rate, the late portion rounded half-up to whole cents. A `LEASE` bills forward-looking whole periods: periods used are the actual days divided into 30-day periods rounded up, and `billed_cents` is the greater of contracted periods or periods used, times 30 days, times the daily rate — no late multiplier, and no credit for returning early, so identical dates can bill differently under the two shapes. At return, a `LOAN_DEBIT` or `LEASE_DEBIT` posts for whatever remainder brings cumulative debits to `billed_cents`, and the balance recomputes. With `damage_flag` false — from `ACTIVE` or `OVERDUE` alike — the loan moves to `RETURNED` and settles in the same request, while the unit passes `ON_LOAN` → `UNDER_INSPECTION` → `AVAILABLE` and the part's `available_count` rises. With `damage_flag` true, the bill still computes as normal — damage recovery itself is handled offline through warranty and claims channels — but the loan parks in `DAMAGE_REVIEW` and the unit is quarantined instead.

### 3.8. Warranty Claims and Customer Returns

After delivery, two after-market channels protect the customer. A warranty claim is filed by the owning `CustomerContact` (otherwise `ERR_FORBIDDEN`) against a delivered line, naming the `customer_id`, the `order_line_id`, a `fault_category` of `DOA`, `PREMATURE_FAILURE`, or `COSMETIC`, and a free-text `description`. Filing must land strictly before the warranty horizon — the line's `delivered_at` plus the part's `warranty_months` 30-day months; filing at or after that instant is `ERR_WARRANTY_PERIOD_ELAPSED`. The claim is born `FILED` with `months_in_service` computed as the whole 30-day months between delivery and filing, rounded down, and `reopen_count` zero. Claims filter by `customer_id`, `order_line_id`, and `status`.

Review is segregated by design. A `WarrantyAdjuster` takes a claim from `FILED` to `UNDER_REVIEW`, optionally with `review_notes`, and the system records their operator id in `reviewed_by`. The decision then belongs to a `WarrantyApprover` who must not be the reviewer — the same operator id attempting approval or rejection is `ERR_SEGREGATION_OF_DUTIES`. Approval recomputes the claim's coverage fraction `coverage_pct` from the calendar at the approval instant: months in service is the whole 30-day months from delivery to approval, and `coverage_pct` is one hundred percent at six months or fewer, seventy-five percent for months seven through twelve, fifty percent for months thirteen through twenty-four, and zero beyond twenty-four. The `credit_cents` is the line's `line_total_cents` times the coverage fraction, rounded half-up; a `WARRANTY_CREDIT` posts with balance recompute, and the claim flows `UNDER_REVIEW` → `APPROVED` → `CREDIT_ISSUED` in the one request. Rejection takes the claim `UNDER_REVIEW` → `REJECTED`; if the approver sets `fraud_flag` true, the customer's `warranty_fraud_flags` rises by one and feeds the next sweep's tier recompute. A rejected claim gets exactly one second look: an adjuster may reopen it to `UNDER_REVIEW`, incrementing `reopen_count` and re-stamping `reviewed_by`, but only while `reopen_count` is still zero — a second reopen is refused with `ERR_REOPEN_LIMIT_REACHED`.

The second channel is the return authorization, for `OUTRIGHT` lines only. The owning contact files it with `customer_id`, `order_line_id`, and a free-text `reason`; it is approved automatically as long as the request lands within 30 days of the line's delivery — later filings are `ERR_RETURN_WINDOW_CLOSED` — and lines that are not `OUTRIGHT` or have no `delivered_at` yet are `ERR_INVALID_REQUEST`. The authorization is born `APPROVED` with `days_since_delivery` computed from the filing clock as whole days since delivery. Physical receipt is a warehouse act carrying a `condition_grade`. For `RESALEABLE` goods, the days-since-delivery figure is recomputed at the receipt clock, the `restock_fee_cents` is ten percent of the line total when the return arrives within seven days of delivery or twenty percent when it arrives on days eight through thirty — rounded half-up either way — and `credit_cents` is the line total minus the fee; a `RESTOCK_CREDIT` posts with balance recompute, and the returned unit passes through `UNDER_INSPECTION` back to `AVAILABLE`. For `DAMAGED` goods there is no fee, no credit, and no ledger entry at all; the unit passes through inspection into `QUARANTINED` instead. Either way the authorization flows `APPROVED` → `RECEIVED` → `SETTLED` within the same request. The collection filters by `customer_id`, `order_line_id`, and `status`.

### 3.9. The Operations Sweep

A `PlatformOps` operator runs the operations checkpoint, which processes six steps in a pinned order. First, every `ISSUED` quote whose `expires_at` has passed moves to `EXPIRED`, incrementing its `version`; the request stays `QUOTED` rather than reverting, and any unit the expired quote's request had pinned is released from `RESERVED` back to `AVAILABLE` with its `reserved_by_request_id` cleared and the part's counters restored. Second, every `OPEN` core return past its `due_at` flips to `OVERDUE`, incrementing `version`. Third, every `ACTIVE` loan past its `due_at` flips to `OVERDUE`, incrementing `version`. Fourth, forward billing catches up: for each lease, a period debit of 30 days times the daily rate posts for every 30-day boundary crossed since the last posting, so that return-time billing only ever posts the remainder. Fifth, customer tiers are recomputed from the trailing window — the 180 days up to and including now, excluding the instant exactly 180 days earlier — counting each customer's returns that reached `SETTLED` with receipt inside the window into `core_returns_settled_180d`, and the subset received on or before their due instant into `core_returns_on_time_180d`. The on-time rate is the on-time count divided by the settled count, or zero when there are no settled returns. A customer with at least two settled returns, an on-time rate of at least 0.95, and zero `warranty_fraud_flags` earns `PLATINUM`; otherwise at least one settled return, an on-time rate of at least 0.90, and zero fraud flags earns `PRIORITY`; everyone else is `STANDARD`. The same step suspends any customer whose outstanding balance is strictly greater than their credit limit — a balance exactly equal to the limit is not suspended. Sixth, every `QUARANTINED` unit is written off to `SCRAPPED`. The sweep reports its work as `expired_quotes`, `overdue_core_returns`, `overdue_loans`, `lease_debits_posted`, `customers_suspended`, `tiers_updated`, and `units_scrapped`.

## 4. Endpoint Definitions

Endpoints that create a new resource return `201 Created`; endpoints that modify an existing resource, trigger a state transition, or run a read return `200 OK`. Request and response payloads for every operation are governed by the workflows in §3 and the envelope in §2.2.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/aog/customers` | Onboard an operator account | FinanceController |
| GET | `/aog/customers` | List customers | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/customers/{id}` | Get one customer | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/customers/{id}/credit-adjustments` | Post a manual or payment ledger adjustment (OCC-guarded) | FinanceController |
| POST | `/aog/customers/{id}/suspend` | Manually suspend an account | FinanceController |
| POST | `/aog/customers/{id}/reactivate` | Reactivate a suspended account when balance is within limit | FinanceController |
| GET | `/aog/customers/{id}/ledger-entries` | Ledger entries for a customer, newest first | AogDeskAgent, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/parts` | Register a catalog part | WarehouseOperator |
| GET | `/aog/parts` | List parts | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/parts/{id}` | Get one part | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/inventory-units` | Register a serialized unit | WarehouseOperator |
| GET | `/aog/inventory-units` | List units with filters | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/inventory-units/{id}` | Get one unit | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/inventory-units/{id}/certify-trace` | Upgrade a unit's trace documentation level | ComplianceOfficer |
| POST | `/aog/aog-requests` | File a 24/7 AOG request | AogDeskAgent, CustomerContact |
| GET | `/aog/aog-requests` | List AOG requests | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/aog-requests/{id}` | Get one AOG request | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/aog-requests/{id}/source-search` | Run the sourcing selector; reserves the winning unit | AogDeskAgent |
| POST | `/aog/aog-requests/{id}/escalate` | Escalate the request | AogDeskAgent |
| POST | `/aog/aog-requests/{id}/cancel` | Cancel an open or quoted request | AogDeskAgent, CustomerContact |
| GET | `/aog/aog-requests/{id}/quotes` | Quotes for a request | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/quotes` | Draft a quote against an AOG request | AogDeskAgent |
| GET | `/aog/quotes` | List quotes | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/quotes/{id}` | Get one quote | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/quotes/{id}/issue` | Issue the quote; starts the validity clock and snapshots the tier | AogDeskAgent |
| POST | `/aog/quotes/{id}/accept` | Customer accepts (OCC-guarded); creates the order cascade | CustomerContact |
| POST | `/aog/quotes/{id}/reject` | Customer rejects the issued quote | CustomerContact |
| POST | `/aog/quotes/{id}/revise` | Revise a rejected or expired quote back to draft (OCC-guarded) | AogDeskAgent |
| POST | `/aog/quotes/{id}/cancel` | Desk cancels a draft quote | AogDeskAgent |
| GET | `/aog/orders` | List orders | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/orders/{id}` | Get one order | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/orders/{id}/compliance-decision` | Record the compliance screening outcome | ComplianceOfficer |
| GET | `/aog/order-lines` | List order lines | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/order-lines/{id}` | Get one order line | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/order-lines/{id}/allocate` | Allocate a unit to a line | WarehouseOperator |
| POST | `/aog/order-lines/{id}/release` | Deallocate a line | WarehouseOperator |
| POST | `/aog/shipments` | Create the shipment for an order | WarehouseOperator |
| GET | `/aog/shipments` | List shipments | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/shipments/{id}` | Get one shipment | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/shipments/{id}/tender` | Tender to carrier after all compliance gates | WarehouseOperator |
| POST | `/aog/shipments/{id}/deliver` | Confirm delivery; fires the invoice, deposit, core, and loan cascade | WarehouseOperator |
| POST | `/aog/charter-slots` | Register a charter aircraft | AogDeskAgent |
| GET | `/aog/charter-slots` | List charter slots | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/charter-slots/{id}` | Get one charter slot | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/charter-slots/{id}/release` | Release a slot or un-book it while not yet delivered | AogDeskAgent |
| GET | `/aog/core-returns` | List core returns | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/core-returns/{id}` | Get one core return | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/core-returns/{id}/receive` | Record physical core receipt; computes the final penalty | WarehouseOperator |
| POST | `/aog/core-returns/{id}/inspect` | Inspect the core; settles the deposit waterfall | WarehouseOperator |
| POST | `/aog/core-returns/{id}/waive-penalty` | Waive part of the accrued penalty | FinanceController |
| POST | `/aog/loans` | Desk-direct loan or lease of a rotable unit | AogDeskAgent |
| GET | `/aog/loans` | List loans | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/loans/{id}` | Get one loan | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/loans/{id}/return` | Receive the unit back; settles billing per contract shape | WarehouseOperator |
| POST | `/aog/warranty-claims` | File a warranty claim against a delivered line | CustomerContact |
| GET | `/aog/warranty-claims` | List warranty claims | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/warranty-claims/{id}` | Get one warranty claim | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/warranty-claims/{id}/review` | Adjuster review; also reopens a rejected claim once | WarrantyAdjuster |
| POST | `/aog/warranty-claims/{id}/approve` | Approve credit; segregated from the reviewer | WarrantyApprover |
| POST | `/aog/warranty-claims/{id}/reject` | Reject the claim; segregated from the reviewer | WarrantyApprover |
| POST | `/aog/return-authorizations` | Request return of a delivered outright line | CustomerContact |
| GET | `/aog/return-authorizations` | List return authorizations | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| GET | `/aog/return-authorizations/{id}` | Get one return authorization | AogDeskAgent, CustomerContact, WarehouseOperator, ComplianceOfficer, FinanceController, WarrantyAdjuster, WarrantyApprover |
| POST | `/aog/return-authorizations/{id}/receive` | Receive the returned unit; computes restocking fee and credit | WarehouseOperator |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformOps |
| POST | `/_system/run-sweeps` | Run the operations checkpoint in pinned order | PlatformOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_PART_NOT_FOUND` | 404 Not Found |
| `ERR_UNIT_NOT_FOUND` | 404 Not Found |
| `ERR_AOG_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_QUOTE_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 Not Found |
| `ERR_SHIPMENT_NOT_FOUND` | 404 Not Found |
| `ERR_CORE_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_LOAN_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_RMA_NOT_FOUND` | 404 Not Found |
| `ERR_CHARTER_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_CLOCK_REGRESSION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_QUOTE_EXPIRED` | 409 Conflict |
| `ERR_CUSTOMER_SUSPENDED` | 409 Conflict |
| `ERR_COMPLIANCE_NOT_CLEARED` | 409 Conflict |
| `ERR_DUPLICATE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_ACTIVE_QUOTE` | 409 Conflict |
| `ERR_DUPLICATE_SHIPMENT` | 409 Conflict |
| `ERR_UNIT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_LINE_ALREADY_ALLOCATED` | 409 Conflict |
| `ERR_LOAN_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CHARTER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_STALE_QUOTE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_CUSTOMER_VERSION` | 412 Precondition Failed |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |
| `ERR_WAIVER_EXCEEDS_PENALTY` | 402 Payment Required |
| `ERR_NO_SOURCE_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_TRACE_DOC_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_CONDITION_NOT_ACCEPTABLE` | 422 Unprocessable Entity |
| `ERR_HAZMAT_DECLARATION_MISSING` | 422 Unprocessable Entity |
| `ERR_EXPORT_LICENSE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EXPORT_DESTINATION_DENIED` | 422 Unprocessable Entity |
| `ERR_NEEDED_BY_IN_PAST` | 422 Unprocessable Entity |
| `ERR_LOAN_WINDOW_IN_PAST` | 422 Unprocessable Entity |
| `ERR_VALIDITY_EXCEEDS_TIER_CAP` | 422 Unprocessable Entity |
| `ERR_WARRANTY_PERIOD_ELAPSED` | 422 Unprocessable Entity |
| `ERR_RETURN_WINDOW_CLOSED` | 422 Unprocessable Entity |
| `ERR_REOPEN_LIMIT_REACHED` | 409 Conflict |

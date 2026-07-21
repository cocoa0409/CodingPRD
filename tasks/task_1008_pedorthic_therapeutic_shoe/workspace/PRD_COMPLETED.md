# Pedorthic & Therapeutic Shoe Store API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the back-office API that runs a pedorthic and therapeutic-shoe practice. Unlike an ordinary footwear retailer, this business sits at the intersection of clinical fitting, medical-device dispensing, and third-party (Medicare) reimbursement, and every one of those threads carries its own compliance burden. A single visit may involve measuring a child's growing foot, running a gait analysis in a capacity-limited lab, dispensing a diabetic shoe that must be substantiated by a physician certification, and later billing that shoe to Medicare under strict annual limits and a shared deductible.

The API is therefore built around auditability and safety first. It tracks catalog products and their size/width/lot inventory, drives the appointment and sales lifecycles, adjudicates Medicare claims, processes returns and exchanges, manages special orders for out-of-stock configurations, runs a loyalty program, and — critically — propagates product recalls through inventory, open orders, and customer credit in a single cascading action. Because reimbursement math, restocking fees, and loyalty accrual must reconcile to the cent (and to the point), the specification below fixes calculation order, rounding, and precedence explicitly rather than leaving them to interpretation.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts, envelopes, and cross-cutting principles that govern every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two authentication headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they act. If either header is missing, or if `X-User-Role` is not one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are valid but the named role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `StoreManager`, `Fitter`, `BillingSpecialist`, and `Customer`.

- When `X-User-Role` is `Fitter`, `X-User-ID` is the `id` of the acting `Fitter` entity; ownership checks on any resource that references a `Fitter` compare the resource's fitter foreign-key field to `X-User-ID`. In the current endpoint surface, however, no operation actually applies a `Fitter` ownership restriction, so a `Fitter` may read and act on any resource regardless of its fitter foreign key; ownership scoping is enforced only for the `Customer` role.
- When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` entity; ownership checks on any resource that references a `Customer` (its customer foreign-key field) compare that field to `X-User-ID`, which is how self-service reads and requests are scoped to the caller's own records.
- When `X-User-Role` is `StoreManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `BillingSpecialist`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it but does not compare it to any entity's `id`.

Role authority is summarized here and made concrete in the endpoint table of §4. A `StoreManager` is the operational administrator: catalog and inventory creation, fitter and gait-lab setup, return adjudication, special-order placement and receipt, recall management, and manual loyalty adjustments are theirs. A `Fitter` records foot measurements, drives the appointment lifecycle through check-in and completion, and works sales. A `BillingSpecialist` owns Medicare certifications and the entire claim lifecycle. A `Customer` is self-service: they may request returns, cancel their own appointments, and read their own customer record, sales, appointments, returns, and loyalty ledger.

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

### 2.3. Pagination and List Filtering

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Because the server clock is logical and often static, several resources can share an identical `created_at`; such ties are broken by ascending creation order — the sequence in which the records were persisted.

Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope. In addition to pagination, list endpoints accept filter query parameters that mirror the attributes of the resource being listed — for example customers may be filtered by `medicare_beneficiary_id` or by `is_pediatric`, products by `category` or `is_recalled`, inventory by `product_id`, `status`, `size`, and `width`, appointments by `customer_id`, `fitter_id`, `gait_lab_id`, and `status`, sales by `customer_id`, `fitter_id`, `appointment_id`, `payment_status`, and `fulfillment_status`, sale lines by `sale_id` and `inventory_item_id`, claims by `customer_id`, `sale_id`, `certification_id`, `status`, and `calendar_year`, returns by `sale_id`, `sale_line_id`, `replacement_inventory_item_id`, and `status`, special orders by `customer_id`, `product_id`, `fulfilled_inventory_item_id`, and `status`, recalls by `product_id` and `status`, and loyalty ledger entries by `customer_id`, `sale_id`, and `reason`. A filter matches records whose corresponding attribute equals the supplied value.

### 2.4. Common Resource Properties and Auditability

Most resources carry a common set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp refreshed on every mutation, and `version` is an integer that starts at 1 and increments by one on every mutation of the resource. Whenever a computed or system field on a resource changes — a sale's `subtotal_cents`, a customer's loyalty or Medicare-benefit fields, an inventory item's reserved quantity — that change counts as a mutation and both refreshes `updated_at` and increments `version`.

Two entities are deliberate exceptions: a `FootMeasurement` and a `LoyaltyLedgerEntry` are immutable audit records. Each carries only `id` and `created_at`; neither has an `updated_at` field nor a `version` field, because once written they are never modified.

### 2.5. The Server Logical Clock

All time-dependent logic — appointment overlap windows, certification visit windows, return-window age, the `calendar_year` stamped onto claims, pediatric age classification, and the `measured_at` timestamp on a measurement — is evaluated against a server-controlled logical clock, never the wall clock. On startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to real time. An operator with a store role may advance or reset the clock by supplying a new instant as `to_iso8601`; from that point every deadline, window, and calendar-year evaluation uses the newly set value.

### 2.6. Monetary and Points Precision

Monetary amounts are integer cents throughout; there are no fractional cents. Where a calculation multiplies cents by a rate — the Medicare coinsurance, the restocking fee, provisional reimbursement — the product is rounded to the nearest whole cent using the round-half-up convention (a value exactly at the half rounds up). Loyalty points are whole integers; per-line accrual is likewise rounded half up before any summation. Each calculation section in §3 states exactly which quantity is rounded and in what order, and those orderings are contractual: rounding a sum where the specification rounds each addend, or vice versa, produces a different and incorrect result.

### 2.7. Optimistic Concurrency Control

Creating a certification for a customer is guarded by optimistic concurrency control against the parent `Customer`. The create request must carry `expected_customer_version`, a non-optional field holding the `version` of the `Customer` that the client last observed. If `expected_customer_version` does not equal the customer's current `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). This matters because creating a certification always bumps the customer's `version` (even the first certification, when there is no prior one to supersede), and a newer certification additionally supersedes the customer's prior `COMPLETE` certification; a client still carrying the pre-supersede version is working from stale data, and rejecting it prevents that client from writing a certification it never observed the precondition for. No other endpoint takes a version field, and no other endpoint performs a version check.

### 2.8. Referential Integrity and Nested-Path Resolution

Every foreign-key reference — whether supplied as a path identifier or inside a request body — must resolve to an existing resource. Path identifiers are validated first and strictly left to right, so that the first unresolved identifier determines the error. A request under a non-existent customer fails on the customer before the nested measurement or certification is examined. Each entity has its own not-found error at HTTP 404: `ERR_PRODUCT_NOT_FOUND`, `ERR_INVENTORY_ITEM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_FITTER_NOT_FOUND`, `ERR_GAIT_LAB_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, `ERR_SALE_LINE_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_SPECIAL_ORDER_NOT_FOUND`, `ERR_RECALL_NOT_FOUND`, and `ERR_LEDGER_ENTRY_NOT_FOUND`. Body foreign keys are resolved after the path resolves and raise the corresponding entity's not-found error.

### 2.9. Validation Precedence

When several checks could reject one request, they are evaluated in a fixed global order, and the first failing check determines the response. The order is: (1) authentication (`ERR_UNAUTHENTICATED`); (2) authorization (`ERR_UNAUTHORIZED`); (3) request-body well-formedness (`ERR_VALIDATION`) — required fields present, enums in range, integers non-negative where constrained, National Provider Identifiers exactly 10 digits, and `gait_lab_id` present when and only when `appointment_type` is `GAIT`; (4) the appointment time-range check (`ERR_INVALID_TIME_RANGE`); (5) existence of all path and body foreign keys (the 404 family above); (6) generic state validity of the target entity for the requested transition (`ERR_INVALID_STATE`); then the domain-specific checks in ascending priority: certification-incomplete (`ERR_CERTIFICATION_INCOMPLETE`), sale-not-fulfilled (`ERR_SALE_NOT_FULFILLED`), line-already-returned (`ERR_LINE_ALREADY_RETURNED`), exchange-type-mismatch (`ERR_EXCHANGE_TYPE_MISMATCH`), quarantined-item (`ERR_ITEM_QUARANTINED`), pediatric-size (`ERR_PEDIATRIC_SIZE_TOO_SMALL`), missing-measurement (`ERR_MISSING_MEASUREMENT`), fitter-double-booked (`ERR_FITTER_DOUBLE_BOOKED`), certification-visit-expired (`ERR_CERTIFICATION_VISIT_EXPIRED`), out-of-stock (`ERR_OUT_OF_STOCK`), gait-lab-capacity (`ERR_GAIT_LAB_AT_CAPACITY`), annual-pair-limit (`ERR_ANNUAL_PAIR_LIMIT_EXCEEDED`), annual-insert-limit (`ERR_ANNUAL_INSERT_LIMIT_EXCEEDED`); and finally the optimistic-concurrency version check (`ERR_STALE_VERSION`), which is evaluated last of all so that a stale version surfaces only once the request is otherwise entirely valid.

### 2.10. Inventory Reservation and Cascading Consistency

The system keeps inventory honest through a reserve-then-consume discipline and a set of automatic reconciliations. An inventory item tracks `quantity_on_hand` (physical units) and `quantity_reserved` (units held by active, unfulfilled sale lines); its `quantity_available` is always `quantity_on_hand` minus `quantity_reserved` and is never stored independently. Adding a sale line reserves stock; cancelling the sale releases that reservation; fulfilling the sale converts the reservation into a physical decrement. Returns and exchanges restock physical units. Whenever one operation changes several entities — a refund flips a sale line, restocks inventory, reverses loyalty, and recomputes the sale's fulfillment axis — every affected resource is mutated in the same operation, each refreshing its own `updated_at` and `version`. Recall issuance is the largest such cascade and is described in §3.1. The consistency model is immediate: all of these effects are visible as soon as the triggering request returns.

## 3. Business Logic & Workflows

### 3.1. Catalog, Inventory, and the Recall Safety Net

The catalog is built from **products**, each created by a `StoreManager` with a `name`, a `brand`, and a `category` — one of `THERAPEUTIC`, `DIABETIC`, `ORTHOTIC`, `REGULAR`, or `INSERT`. A product carries a `base_price_cents` (the retail unit price copied onto each sale line at add time) and, where it is billable, a `medicare_allowable_cents` (the fee-schedule allowable used as the cap in claim adjudication, defaulting to 0) and an `hcpcs_code` (defaulting to null for non-billable goods). The HCPCS code drives Medicare limits: `A5500` denotes a diabetic shoe that counts toward the annual pair limit, while `A5512` and `A5513` denote inserts that count toward the annual insert limit. A product also exposes a computed `is_recalled` flag, which reads true exactly when a product-wide `ISSUED` recall — one whose `lot_number` is null — references that product; a lot-scoped recall (one naming a specific `lot_number`) never sets this product-level flag, and instead surfaces only through the `QUARANTINED` status its cascade stamps onto the matching inventory items.

Physical stock lives in **inventory items**, each created against a product via `product_id` with a `size` (US shoe size at half-size granularity, greater than zero), a `width` — one of `AAA`, `AA`, `A`, `B`, `C`, `D`, `E`, `2E`, `4E`, or `6E` — a `lot_number` used as the recall matching key, and an opening `quantity_on_hand`. The item also holds a system `quantity_reserved` (starting at 0), the computed `quantity_available`, and a lifecycle `status` that begins `AVAILABLE` and may become `QUARANTINED` or `DISCONTINUED`.

A **recall** is drafted by a `StoreManager` against a `product_id` with a `reason` and an optional `lot_number`; when the lot is given only that lot is affected, and when it is null every lot of the product is affected. A recall begins in `DRAFT`. Issuing it advances `DRAFT` to `ISSUED` and fires a four-link cascade in order: first, every `AVAILABLE` inventory item matching the recalled product (and matching lot, if the recall is lot-scoped) transitions to `QUARANTINED`; second, as a consequence, every special order for that product currently in `ORDERED` or `RECEIVED` is cancelled, moving it to `CANCELLED`; third, each such cancelled special order whose `deposit_cents` is greater than zero mints a loyalty ledger entry (reason `ADJUST`) whose point value is the deposit in cents divided by 100 and rounded down to a whole number; and fourth, each affected customer's `loyalty_points_balance` recomputes to include those credits. Closing a recall advances `ISSUED` to `CLOSED`; quarantined items are not auto-restored, and a manager restocks them manually. Any recall action attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.2. Customers, Growth, and Foot Measurement

A **customer** is created by a `Fitter` or `StoreManager` with a `full_name`, a `date_of_birth`, and an optional `medicare_beneficiary_id` (defaulting to null; although it is the intended prerequisite for Medicare billing, its presence is not enforced anywhere — claim drafting and submission never check for it). Several customer attributes are computed on read. The customer is flagged `is_pediatric` when their age — the current clock date minus `date_of_birth` — is under 13 years. Their `loyalty_points_balance` is the sum of `points_delta` across all of their ledger entries, and their `loyalty_tier` follows from that balance: `BRONZE` for a balance from 0 up to but not including 500, `SILVER` from 500 up to but not including 2000, and `GOLD` at 2000 and above. Three Medicare-benefit fields are also computed and are explained in §3.6: `medicare_deductible_remaining_cents`, `medicare_pairs_claimed_ytd`, and `medicare_inserts_claimed_ytd`.

Recording a **foot measurement** is a `Fitter`-only action that captures four inputs — `foot_length_mm_left`, `foot_length_mm_right`, `foot_width_mm_left`, and `foot_width_mm_right`, each a positive number of millimetres — and stamps `measured_at` with the current clock time. Two fields are then computed. The `recommended_mondo_mm` is the fitting length rounded up to a whole shoe step: take the greater of the two foot lengths, add a toe allowance of 14 millimetres if the customer is pediatric or 12 millimetres otherwise, divide that fitting length by the 5-millimetre Mondopoint step, round up to the next whole step, and multiply back by 5. Because the pediatric growth allowance is 2 millimetres larger, the same foot can round up a whole 5-millimetre step for a child. The `length_change_mm_from_prior` is the growth delta: the greater of this measurement's two foot lengths minus the greater of the two foot lengths of the immediately prior measurement for the same customer (ordered by `created_at` ascending, ties broken by creation order), or 0 when this is the customer's first measurement; the resulting delta is rounded half up to a whole millimetre.

### 3.3. Scheduling: Fitters, Gait Labs, and Appointments

The practice's clinicians are **fitters**, each created by a `StoreManager` with a `full_name` and an optional `credential` such as C.Ped (defaulting to null). Gait analysis happens in a **gait lab**, created with a `name` and a `concurrent_capacity` of at least one, which caps how many `GAIT` appointment intervals may overlap in that room at any instant.

An **appointment** is booked by a `Fitter` or `StoreManager` with a `customer_id`, a `fitter_id`, an `appointment_type` — one of `FITTING`, `GAIT`, or `DIABETIC_FITTING` — a `start_time`, and an `end_time`. A `gait_lab_id` must be supplied when the type is `GAIT` and must be null otherwise; violating that pairing is a malformed body (`ERR_VALIDATION`). The `end_time` must be strictly after the `start_time`, or the booking is rejected with `ERR_INVALID_TIME_RANGE`. Two capacity rules then apply. The fitter must be free: treating each of the fitter's `SCHEDULED` or `CHECKED_IN` appointments as occupying its interval plus a 15-minute trailing cleanup buffer, the requested interval may not overlap any such occupied window, or the booking is rejected with `ERR_FITTER_DOUBLE_BOOKED`. For a `GAIT` booking, the number of `SCHEDULED` or `CHECKED_IN` `GAIT` appointments in the same lab whose intervals overlap the requested interval must remain below the lab's `concurrent_capacity`; reaching capacity yields `ERR_GAIT_LAB_AT_CAPACITY`. A successful booking occupies the fitter's interval (with its buffer) and, for gait visits, one lab slot.

An appointment starts `SCHEDULED`. A `Fitter` may check it in, advancing `SCHEDULED` to `CHECKED_IN`. Completing an appointment advances it from either `SCHEDULED` or `CHECKED_IN` to `COMPLETED` and records the recommendation fields supplied in the body — `recommended_mondo_mm`, `recommended_width` (a width from the same enumeration as inventory), `gait_findings` (free text), and `recommended_orthotic` — each of which is otherwise null. Cancelling an appointment, permitted from `SCHEDULED` or `CHECKED_IN` and available to a `Fitter`, a `StoreManager`, or the owning `Customer`, moves it to `CANCELLED` and frees the fitter and gait-lab intervals for future overlap checks. A `Fitter` or `StoreManager` may instead mark a `SCHEDULED` or `CHECKED_IN` appointment as a no-show, moving it to `NO_SHOW` and likewise freeing the intervals. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal; any transition attempted from an incompatible state is rejected with `ERR_INVALID_STATE`.

### 3.4. Sales: Lines, Fulfillment, Payment, and Loyalty Accrual

A **sale** is opened by a `Fitter` or `StoreManager` with a `customer_id`, a `fitter_id`, and an optional originating `appointment_id`. A sale carries two independent axes. Its `payment_status` evolves `UNPAID` → `PAID` → `REFUNDED`; its `fulfillment_status` evolves `PENDING` → `FULFILLED` and then, through returns, `PARTIALLY_RETURNED` and `RETURNED`, or from `PENDING` directly to `CANCELLED`. The two axes move independently. The sale also exposes a computed `subtotal_cents` (the sum of `line_total_cents` over its `ACTIVE` lines) and two loyalty fields set at fulfillment, `loyalty_tier_at_fulfill` and `loyalty_points_earned`.

Adding a **sale line** to a sale takes an `inventory_item_id`, a `quantity` of at least one, and an optional `requires_medicare` flag (default false). At add time the line's `unit_price_cents` is copied from the `base_price_cents` of the item's product, its `line_total_cents` is that unit price times the quantity, and the item's `quantity_reserved` increases by the quantity. Several safety checks guard the add, applied in this order. First, a `requires_medicare` line (a Medicare-billable diabetic dispense) must not reference a recalled product or a `QUARANTINED` item, else `ERR_ITEM_QUARANTINED`. Second, for a pediatric customer that has at least one recorded measurement, the item's US `size`, converted to its Mondopoint-equivalent length in millimetres by the fixed relation `round_half_up((size + 22) / 3 × 25.4)`, must not be below the customer's latest measurement's `recommended_mondo_mm`, else `ERR_PEDIATRIC_SIZE_TOO_SMALL`; a pediatric customer with no measurement on file skips this check entirely. Third, a `requires_medicare` line requires the sale to reference — for the same customer — an appointment of type `DIABETIC_FITTING` in status `COMPLETED`; absent that, the add is rejected with `ERR_MISSING_MEASUREMENT`. Finally, the item's `quantity_available` must be at least the requested `quantity`, else `ERR_OUT_OF_STOCK`. Each line has a `status` beginning `ACTIVE` and later becoming `RETURNED` or `EXCHANGED`.

Fulfilling a sale advances `fulfillment_status` from `PENDING` to `FULFILLED`. It requires that the sale be `PENDING`, that it have at least one `ACTIVE` line (a sale with no `ACTIVE` line is rejected with `ERR_INVALID_STATE`, HTTP 409), and that every `ACTIVE` line's inventory item be `AVAILABLE` — a `QUARANTINED` item blocks fulfillment with `ERR_ITEM_QUARANTINED`. On success, for each `ACTIVE` line both `quantity_on_hand` and `quantity_reserved` on its item decrease by the line's quantity; the customer's current `loyalty_tier` is snapshotted into `loyalty_tier_at_fulfill`; and loyalty accrual runs to set `loyalty_points_earned` and mint an `EARN` ledger entry carrying those points and the `sale_id`. Accrual works line by line with a multiplier frozen from the snapshot — 1.00 for `BRONZE`, 1.25 for `SILVER`, 1.50 for `GOLD`. For each `ACTIVE` line, its `line_total_cents` divided by 100 is multiplied by the multiplier and rounded half up to whole points; those per-line point values are then summed. The order is contractual: round each line, then sum — not sum then round. The minted `loyalty_points_earned` is set once at fulfill and is never mutated by later returns; the effect of a return on the customer's balance is handled separately in §3.5.

Cancelling a sale is permitted only while `fulfillment_status` is `PENDING`; it moves the sale to `CANCELLED` and, for each `ACTIVE` line, releases the reservation by decreasing the item's `quantity_reserved` while leaving `quantity_on_hand` untouched, restoring `quantity_available`. On the payment axis, paying a sale advances `payment_status` from `UNPAID` to `PAID` and requires that the body's `amount_tendered_cents` be at least the sale's `subtotal_cents`; a tender below the subtotal is rejected with `ERR_VALIDATION` (HTTP 422). Any of these transitions attempted from an incompatible state is rejected with `ERR_INVALID_STATE`.

### 3.5. Returns and Exchanges

A **return request** is opened by a `Customer`, `Fitter`, or `StoreManager` against a `sale_id` and the specific `sale_line_id` being handled, with a `return_type` of either `RETURN` (which drives a refund) or `EXCHANGE` (which drives a swap) and an optional free-text `reason`. It begins in `REQUESTED`. A `StoreManager` adjudicates it. Approval advances `REQUESTED` to `APPROVED` and requires that the underlying sale's `fulfillment_status` be either `FULFILLED` or `PARTIALLY_RETURNED` (else `ERR_SALE_NOT_FULFILLED`) and that the referenced sale line still be `ACTIVE` and not already `RETURNED` or `EXCHANGED` (else `ERR_LINE_ALREADY_RETURNED`). Rejection instead moves `REQUESTED` to `REJECTED`, optionally recording a `reason`.

From `APPROVED`, the path forks by type. A refund is valid only when `return_type` is `RETURN`; attempting it on an exchange yields `ERR_EXCHANGE_TYPE_MISMATCH`. The refund advances `APPROVED` to `REFUNDED` and computes the money owed: the restocking fee is zero if the sale is within the 30-day return window (an age of 30 days or fewer counts as within the window) and otherwise the `line_total_cents` times 0.15 rounded half up, where the sale's age is the whole number of days between the sale's creation date and the current clock date; the `refund_amount_cents` is then `line_total_cents` minus that `restocking_fee_cents`. The refund also flips the sale line from `ACTIVE` to `RETURNED`, restocks the item by increasing its `quantity_on_hand` by the line quantity, and reverses loyalty by minting a `REVERSAL` ledger entry whose `points_delta` is the negative of the line's earned points — the `line_total_cents` divided by 100, multiplied by the multiplier for the sale's `loyalty_tier_at_fulfill`, rounded half up. The sale's `fulfillment_status` then recomputes by bubble-up: it becomes `PARTIALLY_RETURNED` while at least one `ACTIVE` line remains, and `RETURNED` once the last `ACTIVE` line has flipped; when the sale becomes fully `RETURNED` and its `payment_status` was `PAID`, that axis moves to `REFUNDED`.

An exchange is valid only when `return_type` is `EXCHANGE` (else `ERR_EXCHANGE_TYPE_MISMATCH`) and requires a `replacement_inventory_item_id` whose item is `AVAILABLE` with `quantity_available` of at least one (else `ERR_OUT_OF_STOCK`). It advances `APPROVED` to `EXCHANGED`, sets `price_difference_cents` to the replacement product's `base_price_cents` minus the original line's `unit_price_cents` (which may be negative), flips the sale line from `ACTIVE` to `EXCHANGED`, restocks the original item by its quantity, and decrements the replacement item's `quantity_on_hand` by that quantity. An exchange carries no loyalty reversal, since the net kept amount is unchanged.

### 3.6. Medicare: Certifications and Claim Adjudication

A **certification** substantiates a diabetic-shoe dispense and is created by a `BillingSpecialist` under a customer, subject to the optimistic-concurrency rule of §2.7 via `expected_customer_version`. It records a `certifying_physician_npi` and a `prescribing_practitioner_npi` (each exactly 10 digits), a `statement_date`, and an `in_person_visit_date`. That visit date must fall within 6 calendar months before the current clock date; a staler visit is rejected with `ERR_CERTIFICATION_VISIT_EXPIRED`. A certification begins `COMPLETE`; creating a newer certification for the same customer supersedes the prior one, moving it from `COMPLETE` to `SUPERSEDED`, and (as noted in §2.7) bumps the customer's `version`.

A **Medicare claim** is drafted by a `BillingSpecialist` with a `customer_id`, the `sale_id` being billed, the substantiating `certification_id`, an `hcpcs_code`, and a `billed_amount_cents`. It begins `DRAFT` and holds a set of system fields — `calendar_year`, `allowed_amount_cents`, `provisional_reimbursement_cents`, `deductible_applied_cents`, `medicare_paid_cents`, and `patient_responsibility_cents` — populated as the claim advances. The customer's year-to-date counters follow directly from paid claims: `medicare_pairs_claimed_ytd` is the number of the customer's `PAID` claims whose `hcpcs_code` is `A5500` and whose `calendar_year` equals the current clock year; `medicare_inserts_claimed_ytd` is the number of their `PAID` claims whose `hcpcs_code` is `A5512` or `A5513` in that year; and `medicare_deductible_remaining_cents` is 25,700 cents minus the sum of `deductible_applied_cents` over those same-year `PAID` claims.

Submitting the claim advances `DRAFT` to `SUBMITTED`. It requires that the referenced sale's `fulfillment_status` be `FULFILLED` or `PARTIALLY_RETURNED` (else `ERR_SALE_NOT_FULFILLED`) and that the referenced certification be `COMPLETE` (else `ERR_CERTIFICATION_INCOMPLETE`). Annual limits are then enforced against the customer's year-to-date counts: an `A5500` shoe claim requires `medicare_pairs_claimed_ytd` below 1 (else `ERR_ANNUAL_PAIR_LIMIT_EXCEEDED`), and an `A5512` or `A5513` insert claim requires `medicare_inserts_claimed_ytd` below 3 (else `ERR_ANNUAL_INSERT_LIMIT_EXCEEDED`). On success, submission stamps `calendar_year` with the current clock year, sets `allowed_amount_cents` to the lesser of `billed_amount_cents` and the `medicare_allowable_cents` of the applicable product — resolved by scanning the billed sale's lines in creation order and taking the product of the first line whose product's `hcpcs_code` equals the claim's `hcpcs_code`, or, when no line's product matches, the product of the first line (falling back to an allowable of 0 if the sale has no resolvable line) — and computes the optimistic `provisional_reimbursement_cents` as `allowed_amount_cents` times 0.80 (that is, one minus the 20% coinsurance rate) rounded half up. This provisional figure assumes the annual deductible is already fully met and applies no deductible subtraction, so for any customer with deductible remaining it deliberately over-estimates what Medicare will pay.

Adjudicating a `SUBMITTED` claim carries a `payer_decision` of either `PAID` or `DENIED`. A denial advances `SUBMITTED` to `DENIED` and consumes no allowance. A payment advances `SUBMITTED` to `PAID` and computes the final reimbursement in cents. The deductible remaining at adjudication is the annual deductible of 25,700 cents minus the sum of `deductible_applied_cents` over the customer's already-`PAID` claims of the same `calendar_year` created before this adjudication (ordered by creation time). The `deductible_applied_cents` for this claim is the lesser of `allowed_amount_cents` and that remaining deductible. The amount after the deductible is `allowed_amount_cents` minus `deductible_applied_cents`; the coinsurance is that after-deductible amount times the 20% coinsurance rate, rounded half up; `medicare_paid_cents` is the after-deductible amount minus the coinsurance; and `patient_responsibility_cents` is `deductible_applied_cents` plus the coinsurance. By construction `medicare_paid_cents` plus `patient_responsibility_cents` equals `allowed_amount_cents`. Reaching `PAID` consumes the customer's annual allowance and deductible, so `medicare_pairs_claimed_ytd`, `medicare_inserts_claimed_ytd`, and `medicare_deductible_remaining_cents` all recompute to include this claim.

A `DENIED` claim may be resubmitted, cycling `DENIED` back to `SUBMITTED`. Resubmission re-checks the same annual-limit preconditions against the current counts and recomputes `calendar_year`, `allowed_amount_cents`, and `provisional_reimbursement_cents`; the `DENIED` → `SUBMITTED` → `DENIED` cycle may repeat. Finally, a `PAID` claim may be voided, advancing `PAID` to `VOIDED`; because the claim is no longer `PAID`, the customer's `medicare_pairs_claimed_ytd`, `medicare_inserts_claimed_ytd`, and `medicare_deductible_remaining_cents` restore to their pre-payment values. `VOIDED` is terminal. Any claim action attempted from an incompatible state is rejected with `ERR_INVALID_STATE`.

### 3.7. Special Orders for Out-of-Stock Configurations

When a customer needs a size or width not in stock, a `Fitter` or `StoreManager` opens a **special order** with a `customer_id`, a `product_id`, a `requested_size`, a `requested_width`, and a `deposit_cents` collected up front. It begins `DRAFT`. A `StoreManager` places it, advancing `DRAFT` to `ORDERED`, provided the product is not recalled — a recalled product blocks placement with `ERR_ITEM_QUARANTINED`. Receiving the order advances `ORDERED` to `RECEIVED` and creates the physical inventory item from the order (using the supplied `lot_number` and `quantity_on_hand`, at the requested size and width), recording its id as `fulfilled_inventory_item_id`. A `Fitter` or `StoreManager` then fulfills it, advancing `RECEIVED` to `FULFILLED`.

A special order may be cancelled from `DRAFT`, `ORDERED`, or `RECEIVED`, moving it to `CANCELLED`. Cancellation may be initiated explicitly by a `StoreManager` or `Fitter`, or automatically by the recall cascade of §3.1. On cancellation, if `deposit_cents` is greater than zero, the deposit is refunded as store credit by minting an `ADJUST` loyalty ledger entry whose points equal the deposit in cents divided by 100, rounded down to a whole number, after which the customer's `loyalty_points_balance` recomputes. `FULFILLED` and `CANCELLED` are terminal, and an action from an incompatible state is rejected with `ERR_INVALID_STATE`.

### 3.8. The Loyalty Program

Loyalty is a running ledger. Each **loyalty ledger entry** records a `customer_id`, an optional `sale_id` (null for manual adjustments), a signed `points_delta`, and a `reason` — one of `EARN`, `REVERSAL`, `REDEEM`, or `ADJUST`. Earning and adjusting are positive; reversals and redemptions are negative. As established in earlier sections, the system mints entries automatically: an `EARN` at sale fulfillment, a `REVERSAL` on a refund, and an `ADJUST` when a deposit is credited back on special-order cancellation. Beyond those, a `StoreManager` may post a manual ledger adjustment or redemption directly, supplying the `customer_id`, `points_delta`, `reason`, and optionally a `sale_id`. Every posting recomputes the owning customer's `loyalty_points_balance` (the sum of all their `points_delta` values) and, through it, their `loyalty_tier`.

## 4. Endpoint Definitions

Endpoints that create a new, stand-alone resource return `201 Created`; endpoints that modify an existing resource, including lifecycle transitions, return `200 OK`. Request and response bodies are intentionally omitted here — reconstruct them from the workflow narratives in §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/products` | Create a product | StoreManager |
| GET | `/products` | List products | StoreManager, BillingSpecialist, Fitter |
| GET | `/products/{product_id}` | Fetch a product | StoreManager, BillingSpecialist, Fitter |
| POST | `/inventory-items` | Create an inventory unit | StoreManager |
| GET | `/inventory-items` | List/filter inventory | StoreManager, Fitter |
| GET | `/inventory-items/{inventory_item_id}` | Fetch an inventory item | StoreManager, Fitter |
| POST | `/customers` | Create a customer | Fitter, StoreManager |
| GET | `/customers` | List/filter customers | Fitter, StoreManager, BillingSpecialist |
| GET | `/customers/{customer_id}` | Fetch a customer | Fitter, StoreManager, BillingSpecialist, Customer |
| POST | `/customers/{id}/measurements` | Record a foot measurement | Fitter |
| GET | `/customers/{id}/measurements` | List a customer's measurements | Fitter, StoreManager |
| POST | `/fitters` | Create a fitter | StoreManager |
| GET | `/fitters/{fitter_id}` | Fetch a fitter | StoreManager, Fitter |
| POST | `/gait-labs` | Create a gait lab | StoreManager |
| GET | `/gait-labs/{gait_lab_id}` | Fetch a gait lab | StoreManager, Fitter |
| POST | `/appointments` | Book an appointment | Fitter, StoreManager |
| GET | `/appointments` | List/filter appointments | Fitter, StoreManager |
| GET | `/appointments/{appointment_id}` | Fetch an appointment | Fitter, StoreManager, Customer |
| POST | `/appointments/{appointment_id}/check-in` | Check in an appointment | Fitter |
| POST | `/appointments/{appointment_id}/complete` | Complete an appointment; record recommendations | Fitter |
| POST | `/appointments/{appointment_id}/cancel` | Cancel an appointment | Fitter, StoreManager, Customer |
| POST | `/appointments/{appointment_id}/no-show` | Mark an appointment as no-show | Fitter, StoreManager |
| POST | `/sales` | Open a sale | Fitter, StoreManager |
| GET | `/sales` | List/filter sales | Fitter, StoreManager |
| GET | `/sales/{sale_id}` | Fetch a sale | Fitter, StoreManager, Customer |
| POST | `/sales/{sale_id}/lines` | Add a sale line | Fitter, StoreManager |
| GET | `/sale-lines` | List/filter sale lines | Fitter, StoreManager |
| GET | `/sale-lines/{sale_line_id}` | Fetch a sale line | Fitter, StoreManager |
| POST | `/sales/{sale_id}/fulfill` | Fulfill a sale | Fitter, StoreManager |
| POST | `/sales/{sale_id}/pay` | Pay a sale | Fitter, StoreManager |
| POST | `/sales/{sale_id}/cancel` | Cancel a sale | Fitter, StoreManager |
| POST | `/customers/{id}/certifications` | Create a certification | BillingSpecialist |
| GET | `/customers/{id}/certifications` | List a customer's certifications | BillingSpecialist, Fitter |
| POST | `/medicare-claims` | Draft a Medicare claim | BillingSpecialist |
| GET | `/medicare-claims` | List/filter claims | BillingSpecialist |
| GET | `/medicare-claims/{claim_id}` | Fetch a claim | BillingSpecialist |
| POST | `/medicare-claims/{claim_id}/submit` | Submit a claim | BillingSpecialist |
| POST | `/medicare-claims/{claim_id}/adjudicate` | Adjudicate a claim (PAID or DENIED) | BillingSpecialist |
| POST | `/medicare-claims/{claim_id}/resubmit` | Resubmit a denied claim | BillingSpecialist |
| POST | `/medicare-claims/{claim_id}/void` | Void a paid claim | BillingSpecialist |
| POST | `/returns` | Request a return/exchange | Customer, Fitter, StoreManager |
| GET | `/returns` | List/filter returns | Fitter, StoreManager, Customer |
| GET | `/returns/{return_id}` | Fetch a return | Fitter, StoreManager, Customer |
| POST | `/returns/{return_id}/approve` | Approve a return | StoreManager |
| POST | `/returns/{return_id}/reject` | Reject a return | StoreManager |
| POST | `/returns/{return_id}/refund` | Refund an approved return | StoreManager |
| POST | `/returns/{return_id}/exchange` | Exchange an approved return | StoreManager |
| POST | `/special-orders` | Create a special order | Fitter, StoreManager |
| GET | `/special-orders` | List/filter special orders | Fitter, StoreManager |
| GET | `/special-orders/{special_order_id}` | Fetch a special order | Fitter, StoreManager, Customer |
| POST | `/special-orders/{special_order_id}/place` | Place a special order | StoreManager |
| POST | `/special-orders/{special_order_id}/receive` | Receive a special order; create inventory | StoreManager |
| POST | `/special-orders/{special_order_id}/fulfill` | Fulfill a special order | Fitter, StoreManager |
| POST | `/special-orders/{special_order_id}/cancel` | Cancel a special order; refund deposit | StoreManager, Fitter |
| POST | `/recalls` | Draft a recall | StoreManager |
| GET | `/recalls` | List/filter recalls | StoreManager, Fitter |
| GET | `/recalls/{recall_id}` | Fetch a recall | StoreManager, Fitter |
| POST | `/recalls/{recall_id}/issue` | Issue a recall; run quarantine cascade | StoreManager |
| POST | `/recalls/{recall_id}/close` | Close a recall | StoreManager |
| POST | `/loyalty-ledger` | Post a manual ledger adjustment/redemption | StoreManager |
| GET | `/loyalty-ledger` | List/filter ledger entries | StoreManager, Fitter, Customer |
| GET | `/loyalty-ledger/{ledger_entry_id}` | Fetch a ledger entry | StoreManager, Fitter, Customer |
| POST | `/_clock/set_current_utc` | Set the server logical clock | StoreManager, BillingSpecialist, Fitter |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_TIME_RANGE` | 422 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_INVENTORY_ITEM_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_FITTER_NOT_FOUND` | 404 |
| `ERR_GAIT_LAB_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_SALE_NOT_FOUND` | 404 |
| `ERR_SALE_LINE_NOT_FOUND` | 404 |
| `ERR_CERTIFICATION_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_RETURN_NOT_FOUND` | 404 |
| `ERR_SPECIAL_ORDER_NOT_FOUND` | 404 |
| `ERR_RECALL_NOT_FOUND` | 404 |
| `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_CERTIFICATION_INCOMPLETE` | 409 |
| `ERR_SALE_NOT_FULFILLED` | 409 |
| `ERR_LINE_ALREADY_RETURNED` | 409 |
| `ERR_EXCHANGE_TYPE_MISMATCH` | 409 |
| `ERR_ITEM_QUARANTINED` | 409 |
| `ERR_PEDIATRIC_SIZE_TOO_SMALL` | 422 |
| `ERR_MISSING_MEASUREMENT` | 409 |
| `ERR_FITTER_DOUBLE_BOOKED` | 409 |
| `ERR_CERTIFICATION_VISIT_EXPIRED` | 422 |
| `ERR_OUT_OF_STOCK` | 409 |
| `ERR_GAIT_LAB_AT_CAPACITY` | 409 |
| `ERR_ANNUAL_PAIR_LIMIT_EXCEEDED` | 409 |
| `ERR_ANNUAL_INSERT_LIMIT_EXCEEDED` | 409 |
| `ERR_STALE_VERSION` | 412 |

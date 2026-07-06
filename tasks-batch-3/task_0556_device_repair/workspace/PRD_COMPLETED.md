# Device Repair Storefront API — Product Requirements Document

## 1. Introduction

This document specifies the Device Repair Storefront API, the back-office system that powers an electronics trade-in and device-repair shop of the kind consumers know as uBreakiFix or Geek Squad. A single storefront juggles several intertwined businesses at once: it diagnoses and repairs customer devices, it manages a physical parts inventory that must be reserved and depleted honestly, it buys back used devices for store credit, it certifies that customer data has been erased before a device changes hands, and it routes protection-plan claims to the correct adjudicator. Each of these flows carries its own money, its own paperwork, and its own safety obligations, and they frequently touch the same device or the same customer.

The core tension the API must resolve is that repair work is provisional until it is finished. A technician quotes an estimate before the bench work is done; a buyback is quoted from a customer's self-assessment before a technician physically grades the device; parts are reserved against stock that may not survive to installation. The system therefore maintains a strict separation between provisional figures produced up front and final figures computed at settlement, and it guarantees that every reserved part, every dollar of store credit, and every ticket state can be cleanly reversed when a workflow is cancelled. This document defines the entities, the state machines that move them, the money calculations that price them, and the validation and authorization rules that keep the storefront's books and its inventory conserved.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contracts that every endpoint honors: authentication, the response envelope, pagination, identifier and timestamp conventions, monetary precision, concurrency control, consistency guarantees, and the order in which validations fire.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. If either header is missing, or if `X-User-Role` is not one of the four recognized roles, the request is rejected with `ERR_MISSING_USER_CONTEXT`. The four roles are `Customer`, `Technician`, `ServiceAdvisor`, and `StoreManager`. When a role is present and valid but is not permitted to perform the requested operation — or when a `Customer` attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The two roles that represent real, persisted actors are identity-backed. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a `Customer` compare that resource's `customer_id` foreign key to `X-User-ID`. When `X-User-Role` is `Technician`, `X-User-ID` is the `id` of the acting `Technician`; it identifies a persisted technician even though bench actions are not gated on per-record ownership. The two operational roles are opaque: when `X-User-Role` is `ServiceAdvisor`, `X-User-ID` is an opaque front-desk operator identifier not tied to any persisted entity, and the same is true when `X-User-Role` is `StoreManager` — the server may record such an identifier but never compares it to any entity's `id`.

`Customer` is the device owner: this role exclusively approves and rejects the estimates on its own tickets and disputes, accepts, and declines the buyback offers on its own trade-ins. `Technician` is the bench operator: this role exclusively diagnoses tickets, posts estimates, orders parts, completes repairs, grades trade-ins into offers, and issues data-wipe certificates. `ServiceAdvisor` is the front desk: this role exclusively registers customers and devices, opens and cancels tickets, files warranty callbacks, submits and cancels trade-ins, and files and routes protection-plan claims. `StoreManager` is the store operator: this role exclusively provisions technicians, bays, and parts, receives and restocks inventory, issues buyback payouts, and approves or denies protection-plan claims. All four roles may read through the `GET` endpoints and may set the logical clock.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100 — a supplied `limit` below 1 is clamped up to 1 and one above 100 is clamped down to 100, rather than rejected. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is clamped to 0. A `limit` or `offset` that is not a parseable integer falls back to its default (10 and 0 respectively). Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order. Every list response reports `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource carries a server-managed `id` — a UUID with no type prefix — and a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits set when the resource is first created. Most resources additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that begins at 1 and increments by one on every mutation, supporting optimistic concurrency control.

There is one deliberate exception. A `DataWipeCertificate` is an immutable event record: it carries only `id` and `created_at`, and it has neither an `updated_at` nor a `version` field, because it is never modified after issuance. Beyond its `id`, a certificate also exposes a `certificate_number`, a server-minted human-readable certificate identifier distinct from the UUID `id`.

### 2.5. The Logical Clock and Temporal Semantics

The server keeps a single logical clock that stands in for wall-clock time throughout the system. On startup the clock reads exactly `2026-05-01T00:00:00Z`, and until a client advances it the clock stays at that default and never falls back to real-world time. Any role may move the clock by supplying a target instant in the `to_iso8601` field. Two things read this clock: a repair ticket's `completed_at` is stamped with the current clock instant at the moment the ticket completes, and the warranty-callback eligibility check compares the current clock against a computed expiry. Because `completed_at` anchors the warranty window, tests that exercise callbacks will typically set the clock forward to simulate the passage of days.

### 2.6. Monetary Precision and Rounding

All money is stored and returned as integer cents; there are no fractional cents anywhere in the system. Whenever a calculation multiplies a cent amount by a rate or a percentage, that intermediate product is rounded to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up) before it participates in any further addition or subtraction. The individual calculations in Section 3 state exactly which term is rounded and in what order; the governing rule is that rounding happens per component, at the point each calculation names, and never as a single rounding of a final floating sum. Quantities of physical parts are plain integers.

### 2.7. Optimistic Concurrency Control on Estimate Creation

Posting a new estimate against a repair ticket is guarded by optimistic concurrency control, because a new estimate legitimately supersedes the prior live estimate on that ticket and advances the ticket's `version`. The estimate-creation request must therefore carry `expected_repair_ticket_version`, a non-optional field holding the client's last observed `version` of the target `RepairTicket`. If `expected_repair_ticket_version` does not equal the ticket's current `version` — because another writer has already posted an estimate and advanced the version since the client last read the ticket — the creation is rejected with `ERR_STALE_TICKET_VERSION` and HTTP status 412. This prevents a client from overwriting an estimate it never observed. No other endpoint takes a version field; estimate creation is the only write protected this way.

### 2.8. Cascading State Consistency

Several operations mutate more than one resource in a single atomic step, and the API guarantees that every dependent effect lands together with the primary transition. When a ticket completes, the ticket's approved estimate is finalized and, driven by that same finalization, each reserved part order on the ticket is installed and the corresponding part's physical stock is drawn down. When a ticket is cancelled, each reserved part order on it is returned and its held stock is released, and any live estimate is superseded. When a trade-in is accepted or later cancelled, the customer's store-credit balance moves accordingly. Every resource touched by one of these cascades is itself a mutation: its `updated_at` is refreshed and its `version` is incremented. The Section 3 narratives specify each cascade in full; the principle here is that no secondary effect is optional or deferred.

### 2.9. Nested Resource Retrieval and Left-to-Right Validation

Some resources are addressed beneath a parent ticket — an estimate lives under its repair ticket, and a part order is created under its repair ticket. For any request whose path names more than one resource, the server validates existence from left to right and rejects on the first identifier that does not resolve. A request for an estimate under a non-existent ticket fails with `ERR_TICKET_NOT_FOUND` before the estimate is ever looked up; only once the ticket resolves does a missing estimate surface as `ERR_ESTIMATE_NOT_FOUND`. A missing part order named in the path yields `ERR_PART_ORDER_NOT_FOUND`, and a missing claim yields `ERR_CLAIM_NOT_FOUND`. The same ordering governs body references, evaluated after path identifiers: a referenced customer that does not exist yields `ERR_CUSTOMER_NOT_FOUND`, a missing technician `ERR_TECHNICIAN_NOT_FOUND`, a missing bay `ERR_BAY_NOT_FOUND`, a missing device `ERR_DEVICE_NOT_FOUND`, a missing part `ERR_PART_NOT_FOUND`, and a missing trade-in `ERR_TRADE_IN_NOT_FOUND`.

### 2.10. Inventory Conservation and the Store-Credit Ledger

Two quantities in this system are conserved and must always reconcile. The first is parts inventory. For every `Part`, the `available_qty` is defined as `on_hand_qty` minus `reserved_qty`, recomputed on every reservation, restock, install, or return; it is never stored independently of that identity. Reservations increase `reserved_qty`, installation draws down both `on_hand_qty` and `reserved_qty`, and a return releases `reserved_qty`. The second conserved quantity is a customer's `store_credit_balance_cents`, the buyback store-credit ledger. It starts at 0, is credited when a trade-in offer is accepted, and is debited by the same amount if that accepted trade-in is later cancelled, so that a full accept-then-cancel cycle leaves the balance exactly where it started. The exact arithmetic and the transitions that trigger it appear in Section 3.

### 2.11. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: absent or invalid user-context headers (`ERR_MISSING_USER_CONTEXT`) are caught before anything else. Authorization comes second: role permission and, for customer-owned actions, ownership of the resource (`ERR_UNAUTHORIZED`). Third, existence of every referenced resource is checked left to right, yielding the appropriate not-found error. Fourth, the request body is checked for well-formedness — required fields present, enum values in range, quantities at least 1, and an interval whose end is after its start — surfacing `ERR_VALIDATION`, `ERR_INVALID_QUANTITY`, or `ERR_INVALID_INTERVAL`. Fifth, the target resource's state is checked against the requested transition, yielding the relevant invalid-state error. Only after these five layers pass does the server evaluate the operation-specific business rules, which themselves have a defined order: the device-has-active-ticket referential check precedes the data-wipe safety check on a buyback payout; the technician and bay scheduling checks and the warranty-window check run at diagnose and callback time; the restock stock-availability check, the estimate spend-cap check, and the estimate optimistic-concurrency check each guard their own operation. Each of these business rules is described alongside the workflow it protects in Section 3.

## 3. Business Logic & Workflows

### 3.1. Provisioning the Storefront: Customers, Devices, and Bench Resources

A `ServiceAdvisor` seeds the storefront's customer-facing records. Registering a customer captures `full_name`, `email`, and `phone`; the new customer's `store_credit_balance_cents` starts at 0. Registering a device records which customer owns it via `customer_id`, along with the device `category` — one of `PHONE`, `LAPTOP`, `TABLET`, or `WEARABLE` — the `brand`, `model`, and `serial_number` (the IMEI or serial), and the device's `market_value_cents`, its current replacement-or-resale value in cents, which must be at least 0. Market value is load-bearing: it drives both the repair-vs-replace recommendation and every trade-in payout. Devices can be listed and filtered by `customer_id`.

Behind the bench, a `StoreManager` provisions the operational resources. Creating a technician records `full_name` and a `certification_level`, which is either `STANDARD` or `MASTER` and sets that technician's labor rate. Creating a repair bay records a `bay_name` identifying the physical bench. Creating a part records its `sku`, its display `name`, its `unit_price_cents` (at least 0), and an opening `on_hand_qty` (defaulting to 0, at least 0); a new part begins with `reserved_qty` of 0 and `available_qty` equal to its `on_hand_qty`. When additional units arrive, the store manager receives stock by supplying a `quantity`, which must be at least 1 or the request is rejected with `ERR_INVALID_QUANTITY`; the units are added to `on_hand_qty` and `available_qty` is recomputed.

### 3.2. Intake and Diagnosis

A repair engagement begins when a `ServiceAdvisor` opens a ticket. Opening a ticket records the `device_id` under repair and the owning `customer_id`, the `intake_channel` — `WALK_IN` or `MAIL_IN` — the customer's `reported_issue`, an optional `is_under_warranty` flag (defaulting to false, which when true waives the diagnostic fee), and the `spend_cap_cents`, the customer's pre-authorized maximum estimate total in cents (at least 0), which later acts as a fiscal ceiling on approval. A freshly opened ticket enters `INTAKE` with `is_callback` set to false. Tickets can be listed and filtered by `device_id`, `customer_id`, `assigned_technician_id`, `assigned_bay_id`, `original_ticket_id`, and `status`.

Diagnosis is the technician's move that advances a ticket from `INTAKE` to `DIAGNOSING`. The technician supplies the `assigned_technician_id`, the `assigned_bay_id`, and the bench window bounded by `scheduled_start_at` and `scheduled_end_at` (ISO 8601 UTC instants). The referenced technician must exist or the request fails with `ERR_TECHNICIAN_NOT_FOUND`, and the referenced bay must exist or it fails with `ERR_BAY_NOT_FOUND`. The window must be non-empty: `scheduled_end_at` must be strictly later than `scheduled_start_at`, otherwise `ERR_INVALID_INTERVAL`. Two scheduling-conflict checks then run against other non-terminal tickets. The assigned technician may not be double-booked: treating each technician's window as half-open — including its start instant but excluding its end instant — no other non-terminal ticket on that technician may overlap this window, or the request is rejected with `ERR_TECHNICIAN_DOUBLE_BOOKED`. The assigned bay carries a cleaning buffer: treating each bay's window as closed — including both endpoints — no other non-terminal ticket on that bay may fall within `CLEANING_BUFFER_MINUTES` minutes of this window, where `CLEANING_BUFFER_MINUTES` is 30, or the request is rejected with `ERR_BAY_UNAVAILABLE`. The buffer boundary is exclusive: overlapping windows are always rejected, a clear gap of exactly 30 minutes between the two windows is permitted, and only a gap strictly less than 30 minutes triggers `ERR_BAY_UNAVAILABLE`. On success the four assignment fields are written and the ticket sits in `DIAGNOSING`, ready for an estimate.

### 3.3. Estimation, the Repair-vs-Replace Recommendation, and the Approval Cycle

From `DIAGNOSING`, a `Technician` posts an estimate, which drives the ticket to `AWAITING_APPROVAL`. The request supplies the estimated `labor_hours` and the `expected_repair_ticket_version` described under optimistic concurrency in Section 2.7; a version mismatch is rejected with `ERR_STALE_TICKET_VERSION`. Each new estimate on a ticket takes the next `revision_number`, a 1-based counter that increments per estimate so that the newest revision is the live one, and it is created in status `SENT`. Creating it also supersedes history: any prior estimate on the ticket still in `SENT` or `REJECTED` transitions to `SUPERSEDED`. Finally the ticket's `version` is incremented by one as part of this operation, which is exactly why a second, stale creation attempt is caught by the concurrency check.

The provisional pricing is computed at creation. The labor component `labor_cost_cents` is the estimated `labor_hours` multiplied by the assigned technician's hourly rate — 5000 cents per hour for a `STANDARD` technician and 8000 cents per hour for a `MASTER` technician — with that product rounded half-up to whole cents. The parts component `parts_cost_cents` is the sum of the `line_cost_cents` of the ticket's active part orders, meaning those in `REQUESTED`, `RESERVED`, or `BACKORDERED` status at the time the estimate is created. The `diagnostic_fee_cents` is 4000 cents, except that it is 0 when the ticket's `is_under_warranty` is true. The `provisional_total_cents` is the sum of `labor_cost_cents`, `parts_cost_cents`, and `diagnostic_fee_cents`.

Each estimate also carries a `recommendation`, computed from the provisional total against the device's value. The system first computes 60 percent of the linked device's `market_value_cents`, rounded half-up to whole cents, as a replace threshold. If `provisional_total_cents` is greater than or equal to that threshold, the `recommendation` is `REPLACE`; otherwise it is `REPAIR`. The boundary is inclusive: a provisional total exactly equal to the threshold recommends `REPLACE`.

The customer, who must own the ticket, then decides. Approval and rejection are both permitted only while the target estimate is in `SENT` status — otherwise the action is rejected with `ERR_ESTIMATE_NOT_SENT` — and only while the parent ticket is in `AWAITING_APPROVAL`, otherwise `ERR_TICKET_INVALID_STATE`. A customer acting on a ticket whose `customer_id` is not their `X-User-ID` is rejected with `ERR_UNAUTHORIZED`. On approval, the system enforces the spend cap: the estimate's `provisional_total_cents` must not exceed the ticket's `spend_cap_cents`, or the approval is refused with `ERR_SPEND_CAP_EXCEEDED` and HTTP 402. When approval succeeds the estimate moves `SENT → APPROVED` and the ticket advances `AWAITING_APPROVAL → IN_REPAIR`; this estimate is now the ticket's approved estimate. Rejection instead moves the estimate `SENT → REJECTED` and sends the ticket back `AWAITING_APPROVAL → DIAGNOSING`, opening the revision cycle so the technician can post a fresh estimate — which will supersede the rejected one.

### 3.4. Ordering Parts and Reserving Inventory

While a ticket is open, a `Technician` orders parts against it, supplying the `part_id` and a `quantity` of at least 1. The order freezes its `line_cost_cents` at creation as the part's `unit_price_cents` multiplied by the ordered `quantity`. Whether the order reserves stock depends on availability at that instant: if the part's `available_qty` is greater than or equal to the ordered `quantity`, the order is created directly in `RESERVED` status and the part's `reserved_qty` is increased by the ordered quantity (with `available_qty` recomputed); if `available_qty` is less than the quantity, the order is instead created in `BACKORDERED` status and no stock is held. Part orders can be listed and filtered by `repair_ticket_id` and `part_id`.

A backordered line waits for stock. Once inventory has been received, a `StoreManager` restocks the order, moving it `BACKORDERED → RESERVED`. Restock is permitted only while the order is `BACKORDERED`, otherwise `ERR_PART_ORDER_INVALID_STATE`, and it requires that the part's `available_qty` now be at least the order's `quantity`, otherwise it is rejected with `ERR_PART_OUT_OF_STOCK`. On success the part's `reserved_qty` rises by the order's quantity and `available_qty` is recomputed. Reserved and backordered orders are what a fresh estimate sweeps into its provisional parts cost, tying the inventory workflow back to pricing.

### 3.5. Completing the Repair and Finalizing the Bill

A `Technician` completes a ticket from `IN_REPAIR`, supplying the `actual_labor_hours` that were really spent. Completion requires that the ticket has an estimate in `APPROVED` status, otherwise it is refused with `ERR_ESTIMATE_NOT_APPROVED`. On success the ticket's `completed_at` is stamped with the current logical-clock instant and the ticket moves `IN_REPAIR → COMPLETED`. The approved estimate is finalized, moving `APPROVED → FINALIZED`, and its `final_total_cents` is recomputed using the same formula as the provisional total but with two substitutions: labor is priced from `actual_labor_hours` rather than the estimated hours, and the parts component sums only the `line_cost_cents` of the ticket's part orders that are `INSTALLED`. Because the inputs differ, the final total may diverge from the provisional total. Driven by this finalization, each part order on the ticket in `RESERVED` status transitions `RESERVED → INSTALLED`, and for each such order the part's `on_hand_qty` and `reserved_qty` are both decreased by the order's quantity with `available_qty` recomputed. The ticket's `final_invoice_cents` is set to the estimate's `final_total_cents`.

### 3.6. Cancellations and Warranty Callbacks

A `ServiceAdvisor` may cancel a ticket while it is still in `INTAKE`, `DIAGNOSING`, or `AWAITING_APPROVAL`; any other state is rejected with `ERR_TICKET_INVALID_STATE`. Cancellation moves the ticket to `CANCELLED` and unwinds its commitments: each part order on the ticket in `RESERVED` status transitions `RESERVED → RETURNED`, releasing its held stock by decreasing the part's `reserved_qty` by the order's quantity and recomputing `available_qty`, and any live estimate still in `SENT` status is moved to `SUPERSEDED`.

Warranty callbacks let a completed repair be re-opened. A `ServiceAdvisor` files a callback against a completed ticket, supplying the new `reported_issue` and `intake_channel`. The original ticket must be in `COMPLETED` status; a callback filed against a ticket in any other status is rejected with `ERR_TICKET_INVALID_STATE`. The system validates the warranty window: the original ticket's `completed_at` plus 90 days defines an expiry instant, and the callback is eligible only if the current logical clock is at or before that expiry — the boundary is inclusive. A callback filed after the window has closed is rejected with `ERR_WARRANTY_EXPIRED`. When eligible, the system creates a new repair ticket whose `original_ticket_id` points at the completed ticket, with `is_callback` set to true, `is_under_warranty` set to true, `status` of `INTAKE`, and `spend_cap_cents` copied from the original ticket. The `original_ticket_id` is set only on callback tickets and forms a self-referential chain back to the ticket being re-opened.

### 3.7. Trade-In and Buyback

Buyback runs on its own state machine. A `ServiceAdvisor` submits a trade-in by supplying the seller's `customer_id`, the `device_id` being bought back, and the customer's own `declared_grade`, one of `A`, `B`, `C`, or `D`. Submission puts the trade-in in `SUBMITTED` and immediately computes a provisional `quoted_payout_cents` from the declared grade. Trade-ins can be listed and filtered by `customer_id` and `device_id`.

The payout math is anchored on the device's `market_value_cents` as the base. A graded value is the base multiplied by the grade multiplier — 0.90 for grade `A`, 0.70 for `B`, 0.45 for `C`, and 0.20 for `D` — rounded half-up to whole cents. An accessory bonus is the base multiplied by 0.05, rounded half-up, but only when the accessory flag is set, and 0 otherwise. A per-defect cosmetic deduction is the base multiplied by 0.03, rounded half-up, applied once for each counted cosmetic defect. The payout is the graded value plus the accessory bonus minus the cosmetic deduction multiplied by the defect count; each of the three components is rounded to whole cents before they are combined, not after. If that arithmetic would go below 0, the payout is floored at 0. For the submission quote, the grade is the `declared_grade`, no accessory bonus applies, and there are no cosmetic deductions, so `quoted_payout_cents` reflects grade alone.

A `Technician` then physically grades the device and makes an offer, moving the trade-in `SUBMITTED → OFFER_MADE`. The offer supplies the `assessed_grade` (one of `A`, `B`, `C`, `D`, else `ERR_VALIDATION`), an optional `has_accessories` flag used for the accessory bonus, and an optional `assessed_cosmetic_defect_count` (at least 0) used for the per-defect deductions. These three inputs are recorded on the trade-in, and `final_payout_cents` is computed by the same payout formula, now using the assessed grade with the accessory bonus and cosmetic deductions applied; the final payout may therefore diverge from the quoted one.

From `OFFER_MADE`, the owning customer chooses among three moves, and each requires that the acting customer's `X-User-ID` match the trade-in's `customer_id`, else `ERR_UNAUTHORIZED`. Disputing sends the trade-in back `OFFER_MADE → SUBMITTED` and clears the `assessed_grade` and `final_payout_cents`, re-opening the grading loop so the technician can re-offer. Declining moves it `OFFER_MADE → DECLINED`, a terminal outcome with no further effect. Accepting moves it `OFFER_MADE → ACCEPTED` and applies the money: the trade-in's `final_payout_cents` is added to the seller customer's `store_credit_balance_cents`.

Settlement and reversal close out the accepted trade-in. A `StoreManager` pays out an accepted trade-in, moving it `ACCEPTED → PAID`, but only after two guards pass. First, the trade-in's device must have no repair ticket in a non-terminal status — none in `INTAKE`, `DIAGNOSING`, `AWAITING_APPROVAL`, or `IN_REPAIR` — or the payout is blocked with `ERR_DEVICE_HAS_ACTIVE_TICKET`. Second, a `DataWipeCertificate` with `wipe_result` of `SUCCESS` must exist for that device, or the payout is blocked with `ERR_DATA_WIPE_REQUIRED`. Payment finalizes the buyback; the store credit already applied at acceptance is retained. Alternatively, a `ServiceAdvisor` may cancel an accepted trade-in before payout, permitted only while it is `ACCEPTED` (else `ERR_TRADE_IN_INVALID_STATE`); cancellation moves it `ACCEPTED → CANCELLED` and reverses the ledger by subtracting `final_payout_cents` from the customer's `store_credit_balance_cents`, restoring the balance.

Data-wipe certificates are the compliance artifact that unblocks payout. A `Technician` issues one for a device, supplying the `device_id`, an optional `trade_in_id` naming the buyback it supports, the wipe `method` — one of `CRYPTO_ERASE`, `FACTORY_RESET`, or `PHYSICAL_DESTRUCTION` — and the `wipe_result`, either `SUCCESS` or `FAILED`. The server mints the `certificate_number`. The record is immutable once created. Certificates can be listed and filtered by `device_id` and `trade_in_id`; a request to retrieve a certificate that does not exist yields `ERR_CERTIFICATE_NOT_FOUND`.

### 3.8. Protection-Plan Claims

Protection-plan claims fund a repair through a coverage program and fork at a routing decision. A `ServiceAdvisor` files a claim, supplying the `repair_ticket_id` the claim funds, the claimant's `customer_id`, and the `plan_type`, one of `ADH`, `EXTENDED_WARRANTY`, or `ACCESSORY`. Filing places the claim in `FILED` and sets its `deductible_cents` from the plan type: 7500 cents for `ADH`, 0 for `EXTENDED_WARRANTY`, and 2500 cents for `ACCESSORY`. Claims can be listed and filtered by `repair_ticket_id` and `customer_id`.

Routing is the advisor's next move, taking the claim `FILED → ROUTED` and setting its `routing_destination` from the plan type: an `ADH` plan routes `IN_STORE`, an `EXTENDED_WARRANTY` plan routes to the `MANUFACTURER`, and an `ACCESSORY` plan routes to the `THIRD_PARTY_ADMIN`. From `ROUTED`, a `StoreManager` adjudicates. Denial simply moves the claim `ROUTED → DENIED`. Approval moves it `ROUTED → APPROVED` but only if the claim's ticket has an estimate in `APPROVED` or `FINALIZED` status, otherwise `ERR_ESTIMATE_NOT_APPROVED`. Routing, approval, and denial each require the claim to be in the correct starting state, and a claim acted on from the wrong state is rejected with `ERR_CLAIM_INVALID_STATE`.

Approval computes the `covered_amount_cents`. The system takes the estimate total on the claim's ticket — the estimate's `final_total_cents` if that approved estimate is already `FINALIZED`, otherwise its `provisional_total_cents` — and subtracts the claim's `deductible_cents`. That difference is then capped at the coverage limit of 50000 cents by taking the smaller of the two, and the result is floored at 0 by taking the larger of it and 0. In other words, `covered_amount_cents` is the deductible-reduced estimate total, never more than 50000 cents and never less than 0.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`; operations that modify an existing resource — including every state-transition action — return `200 OK`. The exception among creates is the estimate posted under a ticket, which creates an `Estimate` and returns `201`, and the warranty callback, which creates a new `RepairTicket` and returns `201`. Request and response bodies are specified in the Section 3 narratives; the table below lists only the routing contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/customers` | Register a customer | ServiceAdvisor |
| GET | `/customers/{customerId}` | Get a customer | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/technicians` | Create a technician | StoreManager |
| POST | `/repair-bays` | Create a repair bay | StoreManager |
| POST | `/devices` | Register a device | ServiceAdvisor |
| GET | `/devices/{deviceId}` | Get a device | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/devices` | List/filter devices | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/repair-tickets` | Open a repair ticket | ServiceAdvisor |
| GET | `/repair-tickets/{ticketId}` | Get a repair ticket | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/repair-tickets` | List/filter repair tickets | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/repair-tickets/{ticketId}/diagnose` | Assign technician, bay, and schedule window | Technician |
| POST | `/repair-tickets/{ticketId}/estimates` | Post a new estimate (OCC-guarded) | Technician |
| GET | `/repair-tickets/{id}/estimates` | List estimates for a ticket | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/repair-tickets/{ticketId}/estimates/{estimateId}` | Get a specific estimate | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/repair-tickets/{ticketId}/estimates/{estimateId}/approve` | Approve an estimate | Customer |
| POST | `/repair-tickets/{ticketId}/estimates/{estimateId}/reject` | Reject an estimate | Customer |
| POST | `/repair-tickets/{ticketId}/complete` | Complete the repair | Technician |
| POST | `/repair-tickets/{ticketId}/cancel` | Cancel a non-terminal ticket | ServiceAdvisor |
| POST | `/repair-tickets/{ticketId}/callback` | Open a warranty-callback ticket | ServiceAdvisor |
| POST | `/parts` | Create a part with opening stock | StoreManager |
| GET | `/parts/{partId}` | Get a part | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/parts/{partId}/receive-stock` | Receive units into on-hand stock | StoreManager |
| POST | `/repair-tickets/{ticketId}/part-orders` | Order a part for a ticket | Technician |
| GET | `/part-orders/{partOrderId}` | Get a part order | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/part-orders` | List/filter part orders | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/part-orders/{partOrderId}/restock` | Reserve a backordered part order | StoreManager |
| POST | `/trade-ins` | Submit a device for buyback | ServiceAdvisor |
| GET | `/trade-ins/{tradeInId}` | Get a trade-in | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/trade-ins` | List/filter trade-ins | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/trade-ins/{tradeInId}/offer` | Grade the device and make an offer | Technician |
| POST | `/trade-ins/{tradeInId}/dispute` | Dispute the offer (re-grade) | Customer |
| POST | `/trade-ins/{tradeInId}/accept` | Accept the offer | Customer |
| POST | `/trade-ins/{tradeInId}/decline` | Decline the offer | Customer |
| POST | `/trade-ins/{tradeInId}/pay` | Issue the buyback payout | StoreManager |
| POST | `/trade-ins/{tradeInId}/cancel` | Cancel an accepted trade-in | ServiceAdvisor |
| POST | `/data-wipe-certificates` | Issue a data-wipe certificate | Technician |
| GET | `/data-wipe-certificates/{certificateId}` | Get a data-wipe certificate | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/data-wipe-certificates` | List/filter certificates | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/protection-plan-claims` | File a protection-plan claim | ServiceAdvisor |
| GET | `/protection-plan-claims/{claimId}` | Get a claim | Customer, Technician, ServiceAdvisor, StoreManager |
| GET | `/protection-plan-claims` | List/filter claims | Customer, Technician, ServiceAdvisor, StoreManager |
| POST | `/protection-plan-claims/{claimId}/route` | Route a filed claim | ServiceAdvisor |
| POST | `/protection-plan-claims/{claimId}/approve` | Approve a routed claim | StoreManager |
| POST | `/protection-plan-claims/{claimId}/deny` | Deny a routed claim | StoreManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_USER_CONTEXT` | 400 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_QUANTITY` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_TECHNICIAN_NOT_FOUND` | 404 |
| `ERR_BAY_NOT_FOUND` | 404 |
| `ERR_DEVICE_NOT_FOUND` | 404 |
| `ERR_TICKET_NOT_FOUND` | 404 |
| `ERR_ESTIMATE_NOT_FOUND` | 404 |
| `ERR_PART_NOT_FOUND` | 404 |
| `ERR_PART_ORDER_NOT_FOUND` | 404 |
| `ERR_TRADE_IN_NOT_FOUND` | 404 |
| `ERR_CLAIM_NOT_FOUND` | 404 |
| `ERR_CERTIFICATE_NOT_FOUND` | 404 |
| `ERR_TICKET_INVALID_STATE` | 409 |
| `ERR_ESTIMATE_NOT_SENT` | 409 |
| `ERR_ESTIMATE_NOT_APPROVED` | 409 |
| `ERR_TRADE_IN_INVALID_STATE` | 409 |
| `ERR_PART_ORDER_INVALID_STATE` | 409 |
| `ERR_CLAIM_INVALID_STATE` | 409 |
| `ERR_DEVICE_HAS_ACTIVE_TICKET` | 409 |
| `ERR_DATA_WIPE_REQUIRED` | 422 |
| `ERR_TECHNICIAN_DOUBLE_BOOKED` | 409 |
| `ERR_BAY_UNAVAILABLE` | 409 |
| `ERR_PART_OUT_OF_STOCK` | 409 |
| `ERR_SPEND_CAP_EXCEEDED` | 402 |
| `ERR_WARRANTY_EXPIRED` | 422 |
| `ERR_STALE_TICKET_VERSION` | 412 |

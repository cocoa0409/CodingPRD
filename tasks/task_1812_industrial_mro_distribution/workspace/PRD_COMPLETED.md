# Industrial MRO Distribution API — Product Requirements Document

## 1. Introduction

Distributors of maintenance, repair, and operations (MRO) supplies compete on two axes at once: contract pricing tailored to each customer tier, and a fulfillment promise that a contractor's crew can depend on at seven in the morning. This document specifies the Industrial MRO Distribution API, a system that backs a national distributor operating a network of branch counters supported by central distribution centers. The API governs the commercial heart of that business — a contract price matrix keyed by customer tier, national-account rebate agreements with end-of-period true-up, and credit exposure control — as well as its operational spine: stock allocation across branch and central warehouses, will-call and same-day delivery promises, vendor drop-ship fulfillment with margin reconciliation, and a returns policy that varies by item class.

Two constituencies use the system side by side. On the distributor side, administrators curate the catalog, the price matrix, rebate agreements, and the warehouse network, while branch managers run the readiness and fulfillment floor. On the customer side, buyers assemble punch-out requisition carts that route through an approval threshold before converting into orders, and drop-ship vendor representatives report actual costs against the lines they fulfill. All of this is mounted under the `/mro` URL prefix, with a test-driving logical clock alongside it so that every date-sensitive rule in the system — price windows, rebate periods, promise cutoffs, return windows — is reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold across every resource and every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or presenting a role the system does not declare, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. The system recognizes exactly five roles: `DistributionAdmin`, `CustomerBuyer`, `CustomerApprover`, `BranchManager`, and `VendorRep`. Each endpoint admits a specific set of roles (§4); a caller whose role is not permitted on the targeted endpoint is rejected with `ERR_FORBIDDEN_ROLE`.

The five roles fall into two identity families. `CustomerBuyer` and `CustomerApprover` are entity-backed: when `X-User-Role` is either of these, `X-User-ID` is the `id` of the acting `CustomerAccount`, and any ownership check on a resource that references a customer compares that resource's customer foreign key to `X-User-ID`. A buyer or approver who touches a cart, order, return, or customer record owned by a different account is rejected with `ERR_CUSTOMER_SCOPE_MISMATCH`; their reads are likewise confined to their own account's resources. `DistributionAdmin`, `BranchManager`, and `VendorRep` are opaque: for these roles `X-User-ID` is an operator identifier not tied to any persisted entity, and the server never compares it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, stamped from the logical clock of §2.4.
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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, and any value below 1 or above 100 is out of range. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A non-integer or out-of-range `limit`, and a non-integer or negative `offset`, are rejected with `ERR_VALIDATION`. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope, where `has_more` is true exactly when items remain beyond the returned page.

### 2.4. The Logical Clock and Calendar Semantics

All date- and minute-sensitive behavior in the system — contract price windows, rebate accrual periods, the same-day promise cutoff, return windows — reads a single logical clock rather than the host's wall clock. At server startup, before any explicit set, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it must never fall back to wall-clock time. A test-driving capability restricted to `DistributionAdmin` sets the logical clock to a supplied `to_iso8601` instant — a timestamp without an offset is read as UTC, an offset-bearing timestamp is converted to UTC, and a malformed or non-string value is rejected with `ERR_VALIDATION`; the response reports the new `current_utc`. Calendar-window fields such as `effective_from`, `effective_to`, `period_start`, `period_end`, and `promise_date` are ISO calendar dates in `YYYY-MM-DD` form, while the branch promise cutoff is expressed as a UTC minute-of-day.

### 2.5. Common Resource Properties

Every resource in this API — customer accounts, items, price rules, rebate agreements, locations, stock balances, carts, orders, order lines, and return authorizations — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted UUID, with no type prefix.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created; both timestamps are stamped from the logical clock of §2.4.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the most recent modification.
- **`version` (integer):** starts at 1 on creation and increments by exactly one on every mutation of the resource, including mutations the server applies to computed fields such as spend counters, stock quantities, or accrual figures.

### 2.6. Money, Units, and Rounding Discipline

All monetary amounts in the system are integer cents; the API never exchanges fractional currency. Where a calculation produces a fractional cent, it is rounded half up, and each calculation pins the exact step at which that rounding occurs: the unit-price resolution rounds once when a percentage discount is applied and again when a quantity-tier adjustment is applied, in that order; the return credit rounds each line before summing; the rebate accrual variants round once at the end of the computation. Quantities are whole units throughout — no fractional units exist anywhere in ordering, allocation, restocking, or returns.

### 2.7. Optimistic Concurrency Control

Two write endpoints in the API are guarded by optimistic concurrency control, and each takes a mandatory expected-version field.

Updating a customer account — `PUT /mro/customers/{id}`, which may change `price_tier`, `is_national_account`, `credit_limit_cents`, `approval_threshold_cents`, `primary_ship_to_state`, or `status` — requires a non-optional `expected_customer_version` carrying the client's last observed `version` of the account. If the supplied value does not match the account's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). Every successful update advances the account's `version` by one, so a client holding a previously observed version is writing from a stale view even when a sequential update would otherwise be legitimate.

Updating a price-matrix rule — `PUT /mro/price-rules/{id}` — likewise requires a non-optional `expected_price_rule_version` matching the rule's current `version`, with the same `ERR_STALE_VERSION` (HTTP 412) rejection on mismatch. A successful update advances the rule's `version` by one. No other endpoint in the API takes a version field.

### 2.8. Nested Retrieval and Existence Ordering

Requests that reference several resources at once are validated for existence in a strict left-to-right order, and the request is rejected with the not-found error corresponding to the first identifier that does not resolve. A request aimed at a rebate agreement beneath a customer validates the customer before the agreement: a missing customer yields `ERR_CUSTOMER_NOT_FOUND` before the agreement is ever examined, and a missing agreement under an existing customer yields `ERR_REBATE_AGREEMENT_NOT_FOUND`. The same discipline applies to every other resource kind — `ERR_ITEM_NOT_FOUND`, `ERR_PRICE_RULE_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`, `ERR_CART_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, and `ERR_RETURN_NOT_FOUND` each reports the first unresolvable identifier of its kind, whether the identifier appears in the URL path or is referenced in the request body.

### 2.9. Stock Integrity and the Available-Quantity Identity

Physical inventory is tracked per location and per item in a `StockBalance` carrying three quantities: `on_hand_qty`, `reserved_qty`, and `available_qty`. The identity `available_qty` equals `on_hand_qty` minus `reserved_qty` holds at all times and is recomputed on every mutation — restock, reservation, release, fulfillment, and return putaway alike. All three quantities are read-only to clients and change only as the side effect of the operations described in §3. A balance is unique per location-and-item pair and is created lazily by the first restock — or the first return putaway (§3.8) — of that item at that location; until it exists, reads and allocation logic treat the balance as having zero available units.

### 2.10. The Validation Cascade

When a request violates more than one rule, the system evaluates checks in a fixed global order so that an earlier failure always masks a later one. First, the identity headers are checked for presence and validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`). Second, the caller's role is checked against the endpoint (`ERR_FORBIDDEN_ROLE`). Third, for the entity-backed roles, customer-scope containment is enforced (`ERR_CUSTOMER_SCOPE_MISMATCH`); where the owning account is discovered only by loading the target resource — a cart, order, return, or rebate agreement — the target's existence is established first and the scope check immediately follows the load. Fourth, every referenced resource is checked for existence in the left-to-right order of §2.8 — with one exception: references to catalog items carried in the request body (cart and order lines, the restock `item_id`, a price rule's `item_id`) are resolved only after the fifth step's shape checks on their containing object pass. Fifth, the request shape is validated — where an endpoint reads a request body it must be a JSON object, required fields present, enum members valid, quantities at least one, amounts non-negative, windows well-formed — with any violation rejected as `ERR_VALIDATION`. Sixth, the state preconditions of the targeted transition are enforced, which is where stale-version rejections (`ERR_STALE_VERSION`) and invalid-transition rejections (`ERR_INVALID_STATE_TRANSITION`) surface alongside the state gates named in §3. Seventh, hazmat and region shipping restrictions are evaluated. Eighth, clock-relative temporal windows — rebate period bounds and return windows — are checked. Ninth, uniqueness and interval-overlap rules fire. Tenth, referential business rules (national-account eligibility, returnability, branch typing, line membership, vendor line coverage, cart ownership) are applied; two local inversions hold — at rebate-agreement creation the national-account gate fires before the ninth step's period-overlap check, and at vendor confirmation the line-coverage rule fires before the per-entry cost figures are shape-validated. Finally, the credit gate at order confirmation is evaluated, after every other confirm-time rule has passed.

## 3. Business Logic & Workflows

### 3.1. The Catalog and the Customer Account

A `DistributionAdmin` builds the sellable catalog one `Item` at a time. Each item carries a unique, non-empty `sku` — reusing an existing SKU is rejected with `ERR_SKU_ALREADY_EXISTS` — plus a free-text `description` (which may be empty) and a positive `list_price_cents`. The `item_class` of an item is one of `STOCKED`, `SPECIAL_ORDER`, or `NON_RETURNABLE`, and this classification later drives the returns policy: stocked items enjoy a sixty-day return window with no restocking fee, special-order items a thirty-day window with a twenty percent restocking fee, and non-returnable items are refused outright. Regulatory handling is described by `hazmat_restriction` — `NONE` by default, or `GROUND_ONLY` or `WILL_CALL_ONLY` — together with `restricted_states`, a list of state codes where delivery of the item is prohibited (defaulting to empty). Items intended for the vendor drop-ship channel are flagged `drop_ship_eligible` (default false) and carry planning figures `vendor_cost_estimate_cents` and `vendor_freight_estimate_cents`, both defaulting to zero.

Customer onboarding is likewise an administrator's task. A `CustomerAccount` is created with a unique, non-empty `account_number` (duplicates rejected with `ERR_ACCOUNT_NUMBER_EXISTS`), a non-empty `display_name`, a `credit_limit_cents` ceiling that may be zero but never negative, and a non-empty `primary_ship_to_state` used as the default destination for hazmat region checks. The account's `price_tier` — one of `STANDARD`, `SILVER`, `GOLD`, or `PLATINUM` — selects which row set of the contract price matrix applies and defaults to `STANDARD`. The `is_national_account` flag defaults to false and gates rebate eligibility later. The `approval_threshold_cents`, defaulting to zero, controls the punch-out approval fork described in §3.4. New accounts are born in `ACTIVE` status with both fiscal counters at zero: `net_spend_cents`, the read-only lifetime figure equal to the sum of `total_cents` over the account's `COMPLETED` orders minus the sum of `credit_cents` over its `CREDITED` returns, and `open_credit_exposure_cents`, the read-only sum of `total_cents` over orders currently in `CONFIRMED`, which is debited at confirmation and released at completion or cancellation.

An administrator may later place an account on `CREDIT_HOLD` or restore it to `ACTIVE` through the account update operation, which is OCC-guarded per §2.7: the request must carry `expected_customer_version` equal to the account's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. A credit hold touches nothing already in flight — open orders are unaffected — and bites only at order confirmation, as §3.6 describes.

### 3.2. The Contract Price Matrix

Contract pricing lives in `PriceMatrixRule` records administered by a `DistributionAdmin`. A rule names the `customer_tier` it prices for and a scope: exactly one of `item_id` (an item-specific rule) or `item_class` (a class-level rule over `STOCKED`, `SPECIAL_ORDER`, or `NON_RETURNABLE`) must be set — supplying both or neither is a shape violation rejected with `ERR_VALIDATION`. The rule's `rule_type` is `FIXED_PRICE` or `DISCOUNT_PCT`; a fixed-price rule must supply `contract_unit_price_cents`, while a discount rule must supply a `discount_pct` strictly between 0 and 100, and each must omit the other's value field. Every rule carries a half-open effectiveness window: `effective_from` is the inclusive start date and `effective_to` the exclusive end date, which must fall after `effective_from`.

Rules are born `DRAFT`, and drafts may overlap one another freely. The overlap gate fires only when an administrator activates a draft: if another `ACTIVE` rule with the same scope key — the same tier-and-item pair, or the same tier-and-class pair — has a window that shares any day with the candidate's window, activation is rejected with `ERR_PRICE_RULE_WINDOW_OVERLAP`. Because both windows are half-open, a rule whose `effective_from` equals an active rule's `effective_to` touches without overlapping and is allowed. Updating a rule is OCC-guarded via `expected_price_rule_version` (§2.7), and a window change on an already-`ACTIVE` rule re-runs the same overlap check against its peers. The update addresses only `rule_type`, the value fields, and the window — tier and scope are immutable — and switching `rule_type` requires the new type's value field to be supplied or already present, with the other type's value field cleared.

At order time the matrix resolves each line's unit price as follows. Candidate rules are those in `ACTIVE` status whose `customer_tier` matches the ordering account's `price_tier`, whose window contains the order-creation clock date — on or after `effective_from` and strictly before `effective_to` — and whose scope matches the line, either by naming the line's item or the item's class. An item-specific rule always beats a class-level rule, and since activation guarantees at most one active rule per scope key covering any date, at most one candidate survives at each specificity level and no further tie-break exists. The base price is the rule's `contract_unit_price_cents` for a fixed-price rule; for a discount rule it is the item's `list_price_cents` reduced by `discount_pct` percent, rounded half up to the cent — the first rounding step; with no candidate at all, the base is simply `list_price_cents`. A whole-quantity tier adjustment then applies to the base: quantities of at least 50 units earn five percent off, quantities of at least 10 but fewer than 50 earn three percent off, and smaller quantities earn no adjustment — the discount applies to the entire quantity as an average rate, never marginally, and the adjusted unit price is rounded half up as the second rounding step. Finally, the resolved `unit_price_cents` is capped so it never exceeds the item's `list_price_cents`, and the line's `line_total_cents` is exactly the ordered `qty` multiplied by that unit price. Administrators review the matrix through a filterable listing that accepts `customer_tier`, `item_id`, `item_class`, and `status` to narrow the rule set.

### 3.3. Stock Locations, Balances, and Replenishment

The fulfillment network is a flat set of `StockLocation` records, each with a unique, non-empty `location_code` — duplicates are rejected with `ERR_LOCATION_CODE_EXISTS` — a non-empty `region_state` naming the state where the site sits, and a `location_type` of `BRANCH` or `CENTRAL`. Branches make the customer-facing promise and therefore must declare `same_day_cutoff_minute`, a UTC minute-of-day from 0 through 1439; central depots must omit it. Supplying the cutoff for a `CENTRAL` site, or omitting it for a `BRANCH`, is a shape violation rejected with `ERR_VALIDATION`.

Replenishment is an administrator action against a location, naming an `item_id` and a `qty`. The restock increments `on_hand_qty` on the location-item balance — creating the `StockBalance` lazily on first use, its `location_id` taken from the restock path and its `item_id` from the request — and then immediately runs the backorder auto-fill chain against the freed availability, responding with the updated balance as it stands after the chain has run. That chain, which also fires on order cancellation and on return putaway, always works the same way: eligible backordered lines at the freed location are filled in a deterministic order, the parent order's `created_at` ascending first and the line's position within its order ascending second. A line is eligible when its `qty_backordered` is positive, its parent order is still `CONFIRMED`, and the freed stock sits at that order's fulfilling branch — or, for central stock, at the central depot already allocated to that line. Each fill decrements the line's `qty_backordered`, increments its `qty_branch` or `qty_central` as appropriate, re-derives the line's `fulfillment_source` from the resulting quantities per §3.6, and re-increments the touched balance's `reserved_qty` by the filled units. When a line's `qty_backordered` reaches zero and no other line of that order still awaits stock, the parent order's `fulfillment_status` recomputes from `PARTIALLY_ALLOCATED` to `ALLOCATED` automatically, with no client request on the order itself.

### 3.4. Punch-Out Requisition Carts and the Approval Threshold

A `CustomerBuyer` assembles a `RequisitionCart` for their own account, naming the owning account via `customer_id`, supplying `lines` — at least one line, each pairing an `item_id` with a `qty` of at least one — and optionally attaching a `punch_out_external_ref`, stored verbatim, tying the cart back to the buyer's external procurement session. Carts are born `OPEN`, with `estimated_total_cents` at zero and `rejection_reason` unset. A buyer may revise an open cart's lines at any time; revision replaces the `lines` wholesale, leaves the cart `OPEN`, and does not reprice — the estimate is recomputed only at submit.

Only an `OPEN` cart may be submitted — submitting from any other status is rejected with `ERR_INVALID_STATE_TRANSITION`. Submitting reprices the cart from scratch: each line is valued at the unit price the contract matrix of §3.2 would resolve for the account's tier at that moment, and `estimated_total_cents` becomes the sum of quantity times resolved price across all lines, with freight never included. The submission then forks on the account's `approval_threshold_cents`. An estimate strictly greater than the threshold routes the cart to `PENDING_APPROVAL`; an estimate less than or equal to the threshold — exact equality included — auto-approves, landing the cart directly in `APPROVED`. A submitted cart with no lines is a shape violation rejected with `ERR_VALIDATION`.

A `CustomerApprover` at the same account then decides pending carts. Approval moves `PENDING_APPROVAL` to `APPROVED`; rejection moves it to `REJECTED` and stores the supplied `reason` on the cart's `rejection_reason`. Either decision attempted on a cart that is not pending is rejected with `ERR_INVALID_STATE_TRANSITION`. Rejection is not terminal: when the buyer revises a rejected cart's lines, the cart reopens to `OPEN` and its `rejection_reason` clears, and the cycle of submit, decide, and revise may repeat without bound. Revision is possible only while a cart is `OPEN` or `REJECTED`.

Conversion happens at order capture: an order created with a payload containing `source_cart_id` must reference a cart in `APPROVED` status — any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — and the request's `customer_id` must equal the cart's owning `customer_id`, or the create is rejected with `ERR_CART_CUSTOMER_MISMATCH`. A successful conversion copies the cart's lines onto the new order, stamps the order's `source_cart_id`, and moves the cart to `CONVERTED`, its terminal state.

### 3.5. Order Capture and Commercial Pricing

An order is born when a `CustomerBuyer` (for their own account) or a `DistributionAdmin` creates a `SalesOrder`. The request names the account via `customer_id`, chooses the fulfilling branch through `fulfillment_branch_id` — which must reference a `BRANCH` location, a `CENTRAL` reference being rejected with `ERR_BRANCH_TYPE_REQUIRED` — and declares a `fulfillment_method` of `WILL_CALL`, `SAME_DAY`, or `STANDARD`. The merchandise comes from exactly one of two sources: an inline `lines` payload, or a `source_cart_id` referencing an approved cart per §3.4; supplying both or neither is rejected with `ERR_VALIDATION`. The request's references are resolved for existence in the order `customer_id`, `fulfillment_branch_id`, then `source_cart_id`.

Pricing is snapshotted at creation and never revisited. Each resulting `OrderLine` records its `order_id`, `item_id`, and `qty`, and carries the resolved `unit_price_cents` from §3.2 with `line_total_cents` as their product. The order's `subtotal_cents` is the sum of its line totals, computed before freight enters the picture. Freight follows a pinned order: `WILL_CALL` orders never carry base freight; for delivery methods, a `subtotal_cents` reaching 25,000 cents waives the base freight entirely; otherwise `SAME_DAY` carries 1,500 cents and `STANDARD` 795 cents. Independently of any waiver, when any line's item has a `hazmat_restriction` other than `NONE` and the order is not will-call, a 2,500-cent hazmat handling charge is added — even when the base freight was waived. The order's `freight_cents` is the base freight plus the handling charge, and `total_cents` is `subtotal_cents` plus `freight_cents`; the free-freight test always reads the pre-freight subtotal, never the total. New orders start with `status` `SUBMITTED` and `fulfillment_status` `UNALLOCATED`, with `promise_date`, `confirmed_at`, `fulfilled_at`, and `completed_at` all unset, `sla_breach` false, and every allocation quantity on every line at zero with `fulfillment_source` `UNRESOLVED`. The orders collection supports filtering by `customer_id`, `fulfillment_branch_id`, `source_cart_id`, and `status`, and an order's lines are always listed in creation order.

Cancellation is open to the buyer and the administrator alike. Cancelling a `SUBMITTED` order is trivially safe — no reservations exist yet — and simply moves the order to `CANCELLED`. Cancelling a `CONFIRMED` order is the multi-step unwinding described in §3.7.

### 3.6. Confirmation: Safety Gates, Credit, and the Allocation Waterfall

Confirmation is the administrator's commitment point, and it is gated by four families of checks in the cascade order of §2.10. First, the account must be `ACTIVE` — confirming for an account on `CREDIT_HOLD` is rejected with `ERR_CUSTOMER_NOT_ACTIVE`, while a `SUBMITTED` order awaiting confirmation is the only place customer status gates an in-flight order. Second, hazmat method restrictions: an order whose `fulfillment_method` is anything other than `WILL_CALL` may not contain an item marked `WILL_CALL_ONLY`, and a `SAME_DAY` order may not contain a `GROUND_ONLY` item — either violation is rejected with `ERR_HAZMAT_METHOD_RESTRICTED`. Third, hazmat region restrictions: on a delivery method, no line's item may list the customer's `primary_ship_to_state` among its `restricted_states`, on pain of `ERR_HAZMAT_REGION_RESTRICTED`; will-call pickup is exempt from both hazmat gates. Fourth and last, the fiscal gate: if the account's `open_credit_exposure_cents` plus the order's `total_cents` would exceed `credit_limit_cents`, confirmation is rejected with `ERR_CREDIT_LIMIT_EXCEEDED`; exact equality with the limit is allowed.

A confirmed order runs the allocation waterfall line by line, in request order. Each line begins with its full `qty` unallocated, and a balance that does not exist yet reads as zero available. The branch bucket takes first: up to the fulfilling branch's `available_qty` for the item is allocated into `qty_branch`, reserving those units on the branch balance. If units remain, exactly one central depot is chosen — eligible depots are `CENTRAL` locations whose balance for the item has positive availability, ranked by `available_qty` descending with ties broken by the location's `created_at` ascending (any residual same-millisecond tie broken by creation order), never by identifier — and the lesser of that depot's availability and the remainder is allocated into `qty_central` and reserved there; if no central qualifies, the line falls through with nothing taken. Any remainder then routes to the vendor drop-ship channel as `qty_drop_ship`, but only when the item is `drop_ship_eligible`; whatever still remains becomes `qty_backordered`. The line's `fulfillment_source` derives from the final quantities: `BRANCH_ONLY` when the branch alone covered the line, `DROP_SHIP_ONLY` when drop-ship alone covered it, `BACKORDER_ONLY` when nothing could be sourced, `SPLIT_STOCK` when branch plus central exactly covered it, and `MIXED` otherwise. Reservations land as `reserved_qty` increments on the branch and selected central balances, and the order's `fulfillment_status` becomes `ALLOCATED` when no line carries a backorder, else `PARTIALLY_ALLOCATED`.

Confirmation also fixes the customer-facing promise for the express methods. For `WILL_CALL` and `SAME_DAY` orders, the UTC minute-of-day of the logical clock at confirm is compared to the fulfilling branch's `same_day_cutoff_minute`: a minute no later than the cutoff — the boundary is inclusive — earns a `promise_date` of the confirm date itself, while a later minute rolls the promise to the next calendar day. `STANDARD` orders carry no promise and keep `promise_date` null. Lines with drop-shipped units receive their provisional economics at the same moment: `provisional_margin_cents` is the drop-shipped quantity times the snapshot `unit_price_cents`, minus the sum of that quantity times the item's `vendor_cost_estimate_cents` and the item's per-line `vendor_freight_estimate_cents`, and the line's `margin_status` moves from `NOT_APPLICABLE` to `PROVISIONAL`; lines without drop-ship keep a null margin. Confirmation then stamps `confirmed_at` from the logical clock and debits the account's `open_credit_exposure_cents` by the order's `total_cents`.

### 3.7. Branch Execution, Drop-Ship Settlement, and Order Completion

Once stock is allocated, the branch floor takes over. A `BranchManager` marks a `CONFIRMED` order ready: for `WILL_CALL` orders the `fulfillment_status` moves to `READY_FOR_WILL_CALL`, and for `SAME_DAY` or `STANDARD` orders to `SHIPPED`. Both moves are allowed from `ALLOCATED` and from `PARTIALLY_ALLOCATED` alike — partial orders may be readied with their backordered units left open — and both require the order's commercial `status` to still be `CONFIRMED`, failing with `ERR_INVALID_STATE_TRANSITION` otherwise. Marking ready also adjudicates the service promise: `sla_breach` becomes true exactly when a `promise_date` was set and the logical-clock date at mark-ready is later than that promise.

Drop-ship lines cannot close out on estimates. A `VendorRep` confirms the order's drop-ship lines by submitting `actual_costs`, which must cover exactly the order's not-yet-confirmed drop-ship lines — no more, no fewer — with any other coverage rejected as `ERR_VENDOR_LINES_MISMATCH`; coverage is judged as a set of `order_line_id` values, so duplicate entries for the same line neither add nor remove coverage, and a duplicate's last occurrence supplies the figures. Each listed line records the vendor-supplied `vendor_cost_actual_cents` and `freight_actual_cents`, sets `qty_vendor_confirmed` equal to its `qty_drop_ship`, and actualizes its economics: `final_margin_cents` is the drop-shipped quantity times `unit_price_cents`, minus the sum of that quantity times `vendor_cost_actual_cents` and the line's `freight_actual_cents`, with `margin_status` advancing to `FINALIZED`. For an unchanged sell price, the provisional and final figures differ exactly to the extent the vendor's actuals differ from the item's estimates.

Fulfillment is the physical hand-off, again a `BranchManager` action, moving `READY_FOR_WILL_CALL` or `SHIPPED` orders to `FULFILLED`. It is gated on vendor settlement: any line whose `qty_drop_ship` exceeds its `qty_vendor_confirmed` blocks fulfillment with `ERR_DROP_SHIP_UNCONFIRMED`. The side effects are physical: for every line, the branch balance's `on_hand_qty` and `reserved_qty` both fall by `qty_branch`, and the selected central balance's two quantities likewise fall by `qty_central`. The order's `fulfilled_at` stamps the logical clock, and — as §3.8 details — every return window later measures from this date.

Completion is the administrator's final commercial act: the order's commercial `status` must still be `CONFIRMED` — any other status is rejected with `ERR_INVALID_STATE_TRANSITION` — and its `fulfillment_status` must be `FULFILLED`, a `CONFIRMED` order not yet fulfilled being rejected with `ERR_ORDER_NOT_FULFILLED`. Completion moves the order to `COMPLETED`, stamps `completed_at`, credits the account's `net_spend_cents` with the order's `total_cents`, releases the same amount from `open_credit_exposure_cents`, and fires the rebate accrual cascade of §3.9 against the completion date. Cancellation of a `CONFIRMED` order runs the mirror image: each line releases its reservations — the branch balance's `reserved_qty` falls by `qty_branch`, the selected central's by `qty_central`, with `available_qty` recomputed on every touched balance — the freed availability immediately triggers the backorder auto-fill chain of §3.3, any line whose backorder thereby empties recomputes its parent order from `PARTIALLY_ALLOCATED` to `ALLOCATED`, and the account's `open_credit_exposure_cents` is released by the cancelled order's `total_cents`. Once an order has been readied — `READY_FOR_WILL_CALL`, `SHIPPED`, or `FULFILLED` — cancellation is no longer a valid transition and is rejected with `ERR_INVALID_STATE_TRANSITION`, as is any confirm attempted twice or a complete attempted out of order.

### 3.8. Returns and Restocking Policy by Item Class

A buyer or an administrator opens a `ReturnAuthorization` against an order, supplying the `order_id` and return `lines`, each naming an `order_line_id`, a `qty` of at least one, and a `condition` of `RESALEABLE` or `DAMAGED`. The order must be returnable — `COMPLETED`, or `CONFIRMED` with fulfillment already `FULFILLED` — and any other state is rejected with `ERR_ORDER_NOT_RETURNABLE`. Every line must belong to the referenced order, and the cumulative returned quantity across all of the order's non-rejected returns must never exceed the order line's purchased `qty`; violations are rejected with `ERR_RETURN_LINE_INVALID`. Item class gates the request further: a line whose item is `NON_RETURNABLE` is refused with `ERR_ITEM_NOT_RETURNABLE`, and the calendar window — sixty days for `STOCKED`, thirty for `SPECIAL_ORDER` — is enforced against the logical clock: a return created on a date later than the order's `fulfilled_at` date plus the class window is rejected with `ERR_RETURN_WINDOW_EXPIRED`, while a return dated exactly on the window's last day is admitted. A valid return is born `REQUESTED` with `credit_cents` and `restocking_fee_cents` unset.

The decision belongs to a `DistributionAdmin` and is a strict fork — a requested return is approved or rejected, never both, and either decision against a non-`REQUESTED` return is `ERR_INVALID_STATE_TRANSITION`. Rejection stores the supplied `reason` on `rejection_reason` and is terminal. Approval opens the physical leg: a `BranchManager` receives the goods, moving the return to `RECEIVED`. Putaway is selective — only lines whose `condition` is `RESALEABLE` and whose item is `STOCKED` return to the shelf, incrementing `on_hand_qty` at the order's fulfilling branch by the returned `qty`; damaged goods and special-order items are never restocked. The freed on-hand stock then triggers the same backorder auto-fill chain of §3.3, re-reserving units to the oldest eligible backordered lines and recomputing any parent order whose backorders thereby clear.

Crediting is the administrator's closing act on a `RECEIVED` return. The rounding order is pinned per line first, then summed: each line's gross is its returned `qty` multiplied by the order line's snapshot `unit_price_cents`; each line's credit is that gross reduced by the class restocking percentage — zero for `STOCKED`, twenty percent for `SPECIAL_ORDER` — rounded half up individually; `credit_cents` is the sum of those per-line credits, and `restocking_fee_cents` is the sum of the grosses minus `credit_cents`. The alternative of summing grosses first and rounding once is explicitly rejected: two `SPECIAL_ORDER` lines grossing 103 cents each yield credits of 82 plus 82 for a 164-cent total, not the 165 that a single rounding of 206 would produce. The credit then unwinds the fiscal record — the account's `net_spend_cents` falls by `credit_cents` — and fires the rebate decrement cascade of §3.9 against the credit date. Returns against an order are listable alongside the order, and the return itself carries its full lifecycle for audit.

### 3.9. National-Account Rebates: Accrual, True-Up, and Settlement

A `RebateAgreement` rewards a national-account customer's spend over a period. Creation is restricted to customers whose `is_national_account` flag is set — an agreement for any other customer is rejected with `ERR_CUSTOMER_NOT_NATIONAL_ACCOUNT` — and is an administrator action taken beneath the customer's record, so the agreement's `customer_id` comes from the creation path rather than the payload. The payload supplies `period_start` and `period_end`, both inclusive calendar dates forming a closed interval with the end strictly after the start, and a `tiers` array of at least one entry, each entry pairing a `threshold_cents` with a `rebate_bps` between 0 and 10,000 inclusive; the first threshold must be zero and thresholds must strictly ascend, with malformed tiers rejected as `ERR_VALIDATION`. Closed intervals make adjacency impossible: a new agreement whose period shares even a single day with another agreement of the same customer is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`, so a `period_start` equal to an existing agreement's `period_end` still overlaps, while starting the day after is allowed. New agreements are born `DRAFT` with `accrued_spend_cents`, `current_tier_index`, and `provisional_rebate_cents` all at zero.

Activation is permitted while the logical-clock date is on or before `period_end`; attempting it after the period has closed is rejected with `ERR_AGREEMENT_PERIOD_EXPIRED`. Early activation — before `period_start` — is perfectly legal, because accrual only ever counts events dated inside the closed period. While `ACTIVE`, every order completion dated inside the period adds that order's `total_cents` to `accrued_spend_cents`, and every return credit dated inside the period subtracts its `credit_cents`. After each movement the agreement re-evaluates `current_tier_index` as the highest tier whose `threshold_cents` is less than or equal to the accrued figure — spend exactly equal to a threshold reaches that tier, and should return credits drive the accrued figure negative the index falls back to 0 — and recomputes the provisional rebate on an average-rate basis: `accrued_spend_cents` multiplied by the reached tier's `rebate_bps`, divided by ten thousand, rounded half up to the cent, with the reached tier's rate applied to the entire accrued spend.

Closing is allowed only once the logical-clock date has moved strictly past `period_end`; closing on or before that date is rejected with `ERR_AGREEMENT_PERIOD_NOT_ENDED`. Close computes the final rebate on a marginal-band basis — each band of spend earning only its own tier's rate: for every tier, the band is the portion of `accrued_spend_cents` lying between that tier's threshold and the next tier's threshold, unbounded for the top tier and never below zero, and `final_rebate_cents` is the sum over tiers of each band times its tier's basis points divided by ten thousand, with a single round half up at the end. The true-up then reconciles the two views: `true_up_delta_cents` is `final_rebate_cents` minus the `provisional_rebate_cents` standing at close, and it may well be negative — a clawback. Consider an agreement whose tiers grant 100 basis points from zero and 200 basis points from 10,000,000 cents: with 15,000,000 cents accrued, the provisional average-rate figure stands at 300,000 cents while the final marginal figure is 200,000 cents, producing a true-up of negative 100,000 cents. Both figures, null until close, are then set. Settlement is the final step, moving a `CLOSED` agreement to `SETTLED` — the terminal state — and issuing the credit: `settled_credit_cents` is set equal to `final_rebate_cents`, null until that moment. Stakeholders review a customer's agreements through the customer's rebate-agreement listing.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify, transition, or act upon an existing resource return `200 OK`. Error responses use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mro/customers` | Create a customer account | DistributionAdmin |
| GET | `/mro/customers/{id}` | Get a customer account | All roles |
| PUT | `/mro/customers/{id}` | Update tier, limits, threshold, ship-to, or status; OCC-guarded | DistributionAdmin |
| GET | `/mro/customers/{id}/rebate-agreements` | List rebate agreements of a customer | All roles |
| GET | `/mro/customers/{id}/carts` | List requisition carts of a customer | All roles |
| POST | `/mro/items` | Create a catalog item | DistributionAdmin |
| GET | `/mro/items/{id}` | Get an item | All roles |
| GET | `/mro/items/{id}/stock-balances` | List stock balances of an item across locations | All roles |
| GET | `/mro/items/{id}/order-lines` | List order lines referencing an item | All roles |
| POST | `/mro/price-rules` | Create a contract price-matrix rule (DRAFT) | DistributionAdmin |
| GET | `/mro/price-rules` | List price rules with filters | All roles |
| GET | `/mro/price-rules/{id}` | Get a price rule | All roles |
| PUT | `/mro/price-rules/{id}` | Update a price rule's rule_type, value, or window; OCC-guarded; window change on an ACTIVE rule re-runs the overlap check | DistributionAdmin |
| POST | `/mro/price-rules/{id}/activate` | Activate a DRAFT price rule (fires the half-open window overlap gate) | DistributionAdmin |
| POST | `/mro/customers/{id}/rebate-agreements` | Create a rebate agreement (DRAFT) for a national-account customer; closed-interval overlap gate | DistributionAdmin |
| GET | `/mro/rebate-agreements/{id}` | Get a rebate agreement | All roles |
| POST | `/mro/rebate-agreements/{id}/activate` | Activate a DRAFT agreement (clock date must be on or before period end) | DistributionAdmin |
| POST | `/mro/rebate-agreements/{id}/close` | Close an ACTIVE agreement after period end; computes the final marginal rebate and true-up delta | DistributionAdmin |
| POST | `/mro/rebate-agreements/{id}/settle` | Settle a CLOSED agreement; issues the credit | DistributionAdmin |
| POST | `/mro/locations` | Create a branch or central DC | DistributionAdmin |
| GET | `/mro/locations/{id}` | Get a location | All roles |
| POST | `/mro/locations/{id}/restock` | Add on-hand stock of an item at a location (creates the StockBalance lazily); triggers the backorder auto-fill chain | DistributionAdmin |
| GET | `/mro/locations/{id}/stock-balances` | List stock balances at a location | All roles |
| POST | `/mro/carts` | Create a requisition cart (punch-out return); buyer must belong to the customer | CustomerBuyer |
| GET | `/mro/carts/{id}` | Get a cart | All roles |
| PUT | `/mro/carts/{id}` | Revise cart lines; allowed in OPEN, and from REJECTED it reopens the cart | CustomerBuyer |
| POST | `/mro/carts/{id}/submit` | Submit a cart; recomputes the estimate; forks to PENDING_APPROVAL or auto-APPROVED by the account's approval threshold | CustomerBuyer |
| POST | `/mro/carts/{id}/approve` | Approve a PENDING_APPROVAL cart | CustomerApprover |
| POST | `/mro/carts/{id}/reject` | Reject a PENDING_APPROVAL cart with a reason | CustomerApprover |
| POST | `/mro/orders` | Create an order directly (lines) or from an APPROVED cart (source_cart_id); exactly one of the two; pricing snapshotted at creation | CustomerBuyer, DistributionAdmin |
| GET | `/mro/orders` | List orders with filters | All roles |
| GET | `/mro/orders/{id}` | Get an order | All roles |
| POST | `/mro/orders/{id}/confirm` | Confirm a SUBMITTED order: hazmat and credit gates, the allocation waterfall, promise date, and provisional drop-ship margins | DistributionAdmin |
| POST | `/mro/orders/{id}/cancel` | Cancel a SUBMITTED or CONFIRMED order; CONFIRMED cancels release reservations and trigger the backorder auto-fill chain | CustomerBuyer, DistributionAdmin |
| POST | `/mro/orders/{id}/mark-ready` | Branch marks a confirmed order ready: READY_FOR_WILL_CALL (WILL_CALL) or SHIPPED (SAME_DAY/STANDARD); computes sla_breach | BranchManager |
| POST | `/mro/orders/{id}/mark-fulfilled` | Mark a ready/shipped order fulfilled; requires all drop-ship quantities vendor-confirmed; decrements on-hand and releases reservations | BranchManager |
| POST | `/mro/orders/{id}/vendor-confirm` | Vendor confirms drop-ship lines with actual unit costs and freight; must cover exactly the order's unconfirmed drop-ship lines | VendorRep |
| POST | `/mro/orders/{id}/complete` | Complete a fulfilled order; runs the spend-accrual cascade into customer and rebate agreements | DistributionAdmin |
| GET | `/mro/orders/{id}/lines` | List an order's lines in creation order | All roles |
| GET | `/mro/orders/{id}/returns` | List return authorizations against an order | All roles |
| POST | `/mro/returns` | Request a return against a fulfilled/completed order; enforces per-class window and returnability | CustomerBuyer, DistributionAdmin |
| GET | `/mro/returns/{id}` | Get a return authorization | All roles |
| POST | `/mro/returns/{id}/approve` | Approve a REQUESTED return | DistributionAdmin |
| POST | `/mro/returns/{id}/reject` | Reject a REQUESTED return with a reason | DistributionAdmin |
| POST | `/mro/returns/{id}/receive` | Receive an approved return at the branch; restocks RESALEABLE STOCKED lines and triggers the backorder auto-fill chain | BranchManager |
| POST | `/mro/returns/{id}/credit` | Credit a received return; computes the per-line-rounded credit and decrements spend accruals | DistributionAdmin |
| POST | `/_clock/set_current_utc` | Test-driving endpoint: set the logical clock; startup default is exactly 2026-08-01T00:00:00Z and never wall-clock time; all date/minute comparisons read this clock | DistributionAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_CUSTOMER_SCOPE_MISMATCH` | 403 Forbidden |
| `ERR_CUSTOMER_NOT_FOUND` | 404 Not Found |
| `ERR_ITEM_NOT_FOUND` | 404 Not Found |
| `ERR_PRICE_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_REBATE_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_LOCATION_NOT_FOUND` | 404 Not Found |
| `ERR_CART_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_RETURN_NOT_FOUND` | 404 Not Found |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CUSTOMER_NOT_ACTIVE` | 409 Conflict |
| `ERR_ORDER_NOT_FULFILLED` | 409 Conflict |
| `ERR_ORDER_NOT_RETURNABLE` | 409 Conflict |
| `ERR_DROP_SHIP_UNCONFIRMED` | 409 Conflict |
| `ERR_HAZMAT_METHOD_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_HAZMAT_REGION_RESTRICTED` | 422 Unprocessable Entity |
| `ERR_AGREEMENT_PERIOD_EXPIRED` | 409 Conflict |
| `ERR_AGREEMENT_PERIOD_NOT_ENDED` | 409 Conflict |
| `ERR_RETURN_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_SKU_ALREADY_EXISTS` | 409 Conflict |
| `ERR_ACCOUNT_NUMBER_EXISTS` | 409 Conflict |
| `ERR_LOCATION_CODE_EXISTS` | 409 Conflict |
| `ERR_PRICE_RULE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_AGREEMENT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_CUSTOMER_NOT_NATIONAL_ACCOUNT` | 422 Unprocessable Entity |
| `ERR_ITEM_NOT_RETURNABLE` | 422 Unprocessable Entity |
| `ERR_BRANCH_TYPE_REQUIRED` | 422 Unprocessable Entity |
| `ERR_RETURN_LINE_INVALID` | 422 Unprocessable Entity |
| `ERR_VENDOR_LINES_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CART_CUSTOMER_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 Payment Required |

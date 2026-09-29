# Wire & Cable Distribution API — Product Requirements Document

## 1. Introduction

A wire-and-cable distributor does not sell units off a shelf. It sells footage off reels, and the moment a reel is broached the business changes shape: what is left behind may be a saleable remnant, a scrap write-off, or nothing at all. Layered on top of that physical reality is a commodity market — the copper wound onto the reel is repriced every trading day — and a credit relationship with electrical contractors who take reels out to jobsites and are expected to bring the empty reels back. This platform is the transactional backbone for that business: it holds the reel inventory and its lineage, prices cut-to-length and full-put-up cable against a published copper settlement, converts quotes into orders, allocates reels under an explicit policy, schedules jobsite deliveries, and closes the loop when a reel comes home and its deposit is credited.

The operational pain the platform removes is coordination cost. Today a branch operator decides by hand which reel to broach, a sales rep re-quotes from a spreadsheet whenever copper moves, a credit desk discovers a customer is over their limit only after the truck has left, and a returned reel's deposit is credited from memory. Each of those decisions has a defensible rule behind it, and each rule interacts with the others: the reel the allocator picks decides whether a remnant is born or footage is scrapped; the copper index pinned at issue time decides whether a quote survives the next publication; the value invoiced at delivery decides whether the customer's next order is allocatable at all. The specification below fixes every one of those rules so that two branches, given the same inventory and the same order, reach the same reel.

This document is written for the engineers building the service. Section 2 defines the contract every endpoint shares — headers, envelopes, pagination, identity, rounding, and the order in which requests are admitted or rejected. Section 3 walks the business narrative from catalog setup through quoting, allocation, cutting, delivery, and return, and is where the domain rules live. Sections 4 and 5 summarise the HTTP surface and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. Operator Identity and Role-Based Access Control

Every request to the API must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the role that operator is acting under. If either header is absent, or if `X-User-Role` is not exactly one of the six role names below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well-formed but the named role is not authorised for the endpoint being called (see the endpoint table in Section 4), the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The six roles are `PlatformAdmin`, `SalesRep`, `BranchOps`, `Driver`, `CreditManager`, and `Customer`.

- `PlatformAdmin` is the catalog, network and market-data operator. It registers branches, trucks and catalog parts, publishes the daily copper settlement, and drives the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — a published copper index entry stores the publishing administrator's identifier in `published_by_user_id` — but it never compares it to any entity's `id`.
- `SalesRep` is the quoting desk. It builds, issues, reprices and converts quotes, and touches neither inventory nor delivery. When `X-User-Role` is `SalesRep`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it as `created_by_user_id` when a quote is opened and as `issued_by_user_id` when a quote is issued, and compares those two recorded values against each other for the segregation-of-duties rule, but never against any entity's `id`.
- `BranchOps` is the branch warehouse operator. When `X-User-Role` is `BranchOps`, `X-User-ID` is the `id` of the acting `Branch`; ownership checks on any resource that references a `Branch` compare the resource's branch foreign-key field to `X-User-ID`. Concretely, a `BranchOps` caller may only allocate or release a sales order whose `branch_id` equals `X-User-ID`, may only cut, pick or return a reel whose `branch_id` equals `X-User-ID`, and may only schedule a delivery run for an order at its own branch. A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- `Driver` is the delivery driver. When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the acting `Truck`; ownership checks on any resource that references a `Truck` compare the resource's `truck_id` to `X-User-ID`. A driver may dispatch and complete only those runs assigned to that truck, and any other run yields `ERR_NOT_RESOURCE_OWNER`.
- `CreditManager` is the credit control desk. It opens customer accounts and posts adjustments to limits and balances; it never quotes, allocates or delivers. When `X-User-Role` is `CreditManager`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity, and the server does not compare it to any entity's `id`.
- `Customer` is the contractor buying cable. When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting `Customer` record; ownership checks compare a quote's `customer_id` or an order's `customer_id` to `X-User-ID`. A `Customer` holds read access only, and reading another customer's quote or order is rejected with `ERR_NOT_RESOURCE_OWNER`.

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

### 2.3. Pagination and Result Ordering

Every list endpoint accepts two optional query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, has a minimum accepted value of 1 and a maximum accepted value of 100; a supplied `limit` outside the range from 1 to 100 inclusive is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422). `offset` defaults to 0 when omitted and has a minimum accepted value of 0. The `meta` block of a list response carries `limit`, `offset`, `total_count` (the number of rows matching the filter before the window is applied) and `has_more` (true when rows remain beyond the current window).

Unless a list endpoint states otherwise, results are ordered by `created_at` ascending. Three collections carry a domain-specific ordering instead. Published copper index entries are returned newest first, ordered by `effective_date` descending; because `effective_date` is unique across entries, no tie-break is reachable. Quote lines and order lines are ordered by `line_number` ascending when the listing is scoped to a single quote or order, and by `created_at` ascending otherwise. Allocations are ordered by `sequence_no` ascending when the listing is scoped to a single order line, and by `created_at` ascending otherwise.

### 2.4. Resource Identity, Timestamps and Version Counters

Every persisted resource carries a server-minted `id` — a UUID string with no type prefix — and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional-second digits (for example, `2026-08-01T00:00:00.000Z`). Most resources additionally carry an `updated_at` timestamp in the same format and an integer `version`. The `version` of a resource is 1 when the resource is created and increases by exactly 1 on every mutation of that resource; `updated_at` is refreshed to the current logical instant on the same mutations. Resources are mutated by cascades as well as by direct calls: when a delivery cascade moves a reel to a jobsite, or an index publication voids a quote, those resources' `version` and `updated_at` advance exactly as if they had been written directly.

There is one exception. A published copper index entry is an immutable market record: it carries only `id` and `created_at`. It has no `updated_at` field and no `version` field, and neither appears in its representation. Its `voided_quote_count` is written once, during the publication request that created it, and is frozen thereafter.

Nested paths are validated left to right. When a URL names a parent and then a child, the parent identifier is resolved first and its non-resolution is reported before the child is even looked up.

### 2.5. The Logical Clock

The service keeps a logical clock, and every deadline in this specification — quote validity, the deposit return window, cut-floor windows, delivery windows, and every `created_at`, `updated_at`, `issued_at`, `dispatched_at` or `delivered_at` stamp — is evaluated against it. Before any call to the clock-setting capability, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never falls back to real wall-clock time. A `PlatformAdmin` may move the clock by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc`. Setting the clock changes no entity state; it only changes what subsequent requests observe as "now".

### 2.6. Money, Footage and Rounding Discipline

All money in this system is carried in whole cents as integers, and every field name ending in `_cents` is an integer count of cents. Footage is carried in whole feet. Weights are carried in pounds to one decimal place. Percentages used internally — the rebate rate and the deposit credit rate — are decimal fractions, not integer percents.

Only two places in the system are allowed to hold a fractional value, and both are pinned exactly. The copper pass-through rate per foot is held at exactly four decimal places and is deliberately left unrounded at that precision. Every conversion of a fractional amount into cents uses round-half-up to zero decimal places, and each such conversion happens exactly once at the point this document names it — never twice, and never on an aggregate that has already been rounded. Concretely, the metal component of a line is rounded to whole cents once per line and the rounded per-line values are then summed; the volume rebate is rounded to whole cents once, on the whole-order basis; the deposit credit is rounded to whole cents once, on the single reel being returned. Summing unrounded intermediate values across lines and rounding the sum once is forbidden and produces different cents.

### 2.7. Request Admission Order

Several checks may be simultaneously violated by one request, and which error the caller sees is part of the contract, not an implementation detail. Checks are evaluated in the fixed order below; the first violated check determines the response, and no later check is evaluated. The lowest number wins.

1. Authentication. `X-User-Role` and `X-User-ID` are present and `X-User-Role` is one of the six declared roles — otherwise `ERR_UNAUTHENTICATED` (401). Applies to every endpoint.
2. Role authorisation. The acting role appears in the endpoint's authorised-role list in Section 4 — otherwise `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint.
3. Request shape. The body parses, every required field is present, every enum-typed value is a declared member of its enumeration, every numeric field lies inside its declared range, and any supplied pagination `limit` is between 1 and 100 inclusive — otherwise `ERR_INVALID_REQUEST` (422). Applies to every endpoint.
4. Existence. Path identifiers are resolved left to right, and then body foreign keys are resolved in this declaration order: `branch_id`, `customer_id`, `product_id`, `truck_id`, `reel_id`, `quote_id`, `sales_order_id`, `order_line_id`, and the allocation identifier. The unresolved reference determines which of `ERR_BRANCH_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`, `ERR_TRUCK_NOT_FOUND`, `ERR_REEL_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`, `ERR_QUOTE_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ORDER_LINE_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_DELIVERY_RUN_NOT_FOUND` or `ERR_COPPER_INDEX_NOT_FOUND` is returned, all with HTTP 404. Applies to every endpoint.
5. Resource ownership. For the entity-backed roles, the acting `X-User-ID` must own the target as described in Section 2.1 — otherwise `ERR_NOT_RESOURCE_OWNER` (403). This check guards ten operations: the order allocation run, the order allocation release, the allocation cut, the allocation pick, delivery-run creation, run dispatch, run completion, the order-line reel return, reading a single quote, and reading a single sales order.
6. Uniqueness. A catalog part's `part_number` is unique across the catalog and a copper index entry's `effective_date` is unique across entries — otherwise `ERR_DUPLICATE_PART_NUMBER` or `ERR_DUPLICATE_INDEX_DATE` (409). This check guards catalog part creation and copper index publication.
7. Transition admissibility. The target resource is in a state that admits the requested transition: a quote must be `DRAFT` for line-add and issue; `ISSUED` for reprice and convert; an order's `fulfillment_status` must be `PENDING_ALLOCATION` or `PARTIALLY_ALLOCATED` for the allocation run, and `PARTIALLY_ALLOCATED` or `ALLOCATED` for the release; an allocation's `status` must be `RESERVED` for cut and pick; a run's `status` must be `SCHEDULED` for dispatch and `DISPATCHED` for completion; an order's `fulfillment_status` must be `DELIVERED` for a reel return. The applicable rejection is `ERR_QUOTE_NOT_DRAFT`, `ERR_QUOTE_NOT_ISSUED`, `ERR_ORDER_NOT_ALLOCATABLE`, `ERR_ALLOCATION_NOT_RESERVED`, `ERR_RUN_INVALID_STATE` or `ERR_ORDER_NOT_DELIVERED`, all with HTTP 409. This check guards every action endpoint.
8. A quote carries at least one line before it may be issued — otherwise `ERR_QUOTE_HAS_NO_LINES` (409), on the quote issue endpoint.
9. A cut item is never returnable: the order line's `returnable` flag must be true — otherwise `ERR_CUT_ITEM_NON_RETURNABLE` (409), on the order-line return endpoint. This deliberately runs before the reel-identity check, because a `CUT` line never shipped a returnable reel and would otherwise always fail on identity instead.
10. Cross-entity references are mutually consistent: on delivery-run creation the truck's `branch_id` equals the order's `branch_id`, otherwise `ERR_TRUCK_BRANCH_MISMATCH`; every allocation's reel sits at the order's branch; and on a return the reel's `delivered_sales_order_id` equals the order line's `sales_order_id`, meaning the reel is one the order line actually shipped, otherwise `ERR_REEL_NOT_ON_ORDER_LINE`. Both are HTTP 409, and this check guards delivery-run creation and the order-line return.
11. The commit branch matches the line's put-up: a cut requires the order line's `put_up` to be `CUT` and a pick requires it to be `MASTER_REEL` — otherwise `ERR_PUT_UP_MISMATCH` (409), on the allocation cut and allocation pick endpoints.
12. A `CUT` line requests at least 25 feet per conductor — otherwise `ERR_BELOW_ABSOLUTE_MIN_CUT` (422), on the quote line-add endpoint.
13. The requested `put_up` appears in the part's `allowed_put_ups` — otherwise `ERR_PUT_UP_NOT_ALLOWED` (422), on the quote line-add endpoint.
14. A paralleled set can be filled completely from one lot — otherwise `ERR_PARALLEL_SET_INCOMPLETE` (409), on the order allocation run.
15. A run whose derived `reel_handling` is `BOOM_LIFT` is assigned a truck that carries one — otherwise `ERR_BOOM_LIFT_REQUIRED` (409), on delivery-run creation.
16. The conversion happens inside the quote's validity window — otherwise `ERR_QUOTE_EXPIRED` (409), on the quote conversion endpoint, and the same request moves the quote to `EXPIRED`.
17. `cut_window_end` is strictly after `cut_window_start` — otherwise `ERR_INVALID_CUT_WINDOW` (422), on the allocation cut endpoint.
18. The buffered cut window collides with fewer than the branch's `concurrent_cut_capacity` existing buffered windows at that branch — otherwise `ERR_CUT_BAY_CAPACITY_EXCEEDED` (409), on the allocation cut endpoint.
19. The half-open delivery window does not overlap any other run on the same truck — otherwise `ERR_TRUCK_WINDOW_CONFLICT` (409), on delivery-run creation.
20. The allocation run produced at least one allocation row across the whole order — otherwise `ERR_NO_ELIGIBLE_REEL` (409), on the order allocation run.
21. The reel being returned is currently `ON_JOBSITE` — otherwise `ERR_REEL_NOT_ON_JOBSITE` (409), on the order-line return endpoint.
22. The order does not already have a delivery run in `SCHEDULED` or `DISPATCHED` status — otherwise `ERR_ORDER_HAS_ACTIVE_RUN` (409), on delivery-run creation.
23. The run's order is `STAGED` before the truck may dispatch — otherwise `ERR_ORDER_NOT_STAGED` (409), on the run dispatch endpoint.
24. At least one copper index entry exists whose `effective_date` is on or before the current logical date — otherwise `ERR_NO_COPPER_INDEX` (409), on the quote issue endpoint.
25. Segregation of duties on issue: when the line subtotal computed by this very issue request is at or above 250,000 cents, the issuing `X-User-ID` must differ from the quote's `created_by_user_id` — otherwise `ERR_SEGREGATION_OF_DUTIES` (403), on the quote issue endpoint.
26. The customer's `credit_status` is `ACTIVE` — otherwise `ERR_CUSTOMER_CREDIT_HOLD` (402). This check guards two operations: quote conversion and the order allocation run.
27. The customer's `available_credit_cents` is at least the quote's `quoted_total_cents` at conversion time — otherwise `ERR_CREDIT_LIMIT_EXCEEDED` (402), on the quote conversion endpoint.
28. Optimistic concurrency: the supplied `expected_quote_version` matches the quote's current `version`, or the supplied `expected_sales_order_version` matches the order's current `version` — otherwise `ERR_STALE_QUOTE_VERSION` or `ERR_STALE_ORDER_VERSION` (412). This check guards the quote line-add endpoint and the order allocation run.

Note the consequence of this ladder at position 25 and 26: a segregation-of-duties failure surfaces before any credit consideration, and a credit hold surfaces before the credit-limit arithmetic. Note likewise at position 9: a return against a cut line is reported as non-returnable even when the caller also named a reel that belongs to a different order.

### 2.8. Optimistic Concurrency on Parent Versions

Two write endpoints are guarded by optimistic concurrency control against the current `version` of their parent resource. Neither guard depends on requests overlapping in time; both are stale-read guards.

Adding a line to a quote requires `expected_quote_version` as a non-optional field of the request body, carrying the client's last observed `version` of the target `Quote`. If that value does not equal the quote's current `version`, the request is rejected with `ERR_STALE_QUOTE_VERSION` (HTTP 412) and no line is created. Adding a second line to a `DRAFT` quote is otherwise a legitimate, repeatable operation — a draft quote accepts any number of lines — so a stale version is the only signal that the client priced its line against a pricing basis (the line set, the physical reel count driving freight, the rebate tier) that no longer holds.

Running the allocator over a sales order requires `expected_sales_order_version` as a non-optional field of the request body, carrying the client's last observed `version` of the target `SalesOrder`. If that value does not equal the order's current `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412) and no allocation row is created or altered. Re-running the allocator is likewise legitimate and repeatable — a `PARTIALLY_ALLOCATED` order is allocated again after restock, and the new run supersedes the shortage picture — so a stale version is the only signal that the reel reservations on which the client based its policy choice have already moved.

No other endpoint accepts a version field. Quote issue, reprice, convert, allocation release, cut, pick, delivery-run creation, dispatch, completion, reel return and credit adjustment all take no expected-version input.

### 2.9. Segregation of Duties and Branch Scoping

Two structural controls run across the whole system. The first is segregation of duties on the quoting desk: a quote of material value may not be authored and issued by the same operator. Materiality is judged on the line subtotal that the issue request itself computes under the index it is pinning in that same request — not on the quote's stored `line_subtotal_cents`, which is 0 for as long as the quote is `DRAFT`. When that freshly computed subtotal reaches 250,000 cents (2,500 dollars) or more, the issuing operator's `X-User-ID` must differ from the quote's `created_by_user_id`; below that threshold a rep may issue their own quote.

The second is branch scoping: physical work is done by the branch that holds the goods. Every inventory, allocation, cut, pick, delivery-scheduling and return action is scoped to the branch named by the acting `BranchOps` operator's `X-User-ID`, and drivers are scoped in the same way to their own truck.

### 2.10. Cascade Discipline

Several operations in this system reach far beyond the resource named in the URL. A delivery completion touches the run, the order on both of its status axes, every allocation on the order, every picked reel, and the customer's balance and credit posture — and, if that posture flips, every one of that customer's issued quotes and pending orders. A copper index publication touches quotes across the entire tenant, their orders, and the reel reservations those orders were holding. A reel return touches the reel, the order's deposit ledger, the customer's liability and balance, and possibly a set of held orders.

Three rules govern all of them. First, cascades are immediate and synchronous: by the time the response is written, every downstream resource already reflects its new state, and no background job is involved. Second, every resource a cascade touches has its `version` incremented and its `updated_at` refreshed, exactly as a direct write would. Third, cascades are described in this document as numbered links, and every link listed for an operation fires within the same request or none of them does.

## 3. Business Logic & Workflows

### 3.1. Standing Up the Network, the Fleet and the Catalog

Before any cable can be quoted, a `PlatformAdmin` registers the distribution network. A branch is created with a display `name` and a two-letter `region_code` that is used for reporting only and drives no logic. Two operational settings accompany it. `concurrent_cut_capacity` declares how many buffered cut windows may overlap on that branch's cut floor and defaults to 1 when omitted; it must be at least 1. `delivery_surcharge_cents` is a flat per-run surcharge folded into gross freight for every run out of that branch, defaults to 0 when omitted, and may not be negative. A new branch also starts with `scrap_ft_ytd` initialised to 0 — a running total of the footage its cuts have written off, which the branch record accumulates over its lifetime and which is visible whenever the branch is read.

Trucks belong to branches. Registering a truck records the `branch_id` it is domiciled at, the `truck_code` printed on the run sheet, whether the deck carries a boom lift in `has_boom_lift` (defaulting to false), and how many reel slots the deck physically has in `max_reel_slots` (defaulting to 6, and at least 1). The fleet can be listed in full or narrowed to one branch.

Customer accounts are opened by either a `PlatformAdmin` or a `CreditManager`, with the contractor's legal `name` and a `credit_limit_cents` that may not be negative. A freshly opened account starts with `open_balance_cents` at 0, `deposit_liability_cents` at 0, `available_credit_cents` equal to the credit limit, and `credit_status` at `ACTIVE`. Those four values are maintained by the system, never supplied by a caller. `open_balance_cents` is invoiced order value plus outstanding reel deposits, net of credits issued; `deposit_liability_cents` is the sum of the deposit values of every returnable reel the customer is currently holding on a jobsite; and `available_credit_cents` is always the credit limit less the open balance, a figure that is explicitly permitted to go negative. `credit_status` takes one of exactly two values, `ACTIVE` or `CREDIT_HOLD`.

The `CreditManager` desk can post an adjustment against an account at any time — a manual invoice, a write-off, or a limit review. An adjustment supplies an optional `delta_credit_limit_cents`, an optional `delta_open_balance_cents`, and a mandatory free-text `reason`. Both deltas are signed and are applied additively to `credit_limit_cents` and `open_balance_cents` respectively; the recomputation of `available_credit_cents` and the posture re-evaluation that follows are described in Section 3.9.

The cable catalog is the densest of the setup records, because every pricing and inventory rule downstream reads from it. A part carries a `part_number` unique across the catalog; a `conductor_metal` of either `COPPER` or `ALUMINUM`, which decides whether the copper index pass-through applies at all; `copper_lbs_per_1000ft`, the pounds of copper in a thousand feet of conductor, which defaults to 0, may not be negative and must be 0 whenever `conductor_metal` is `ALUMINUM`; and `base_price_cents_per_ft`, the non-metal component of price in whole cents per foot, which may not be negative. Four further attributes govern cutting and reel handling: `min_cut_length_ft` is both the billing minimum for a cut and the viability floor for a remnant, and may not be below the absolute safety floor of 25 feet; `cut_charge_cents` is the base cut charge per conductor before tier selection and may not be negative; `reel_deposit_cents` is the refundable deposit charged per returnable master reel shipped and may not be negative; `master_reel_length_ft` is the standard master put-up length for the part and must be greater than 0. Finally, `reel_weight_lbs` records the gross weight of one full master reel, must be greater than 0, and is what decides how a reel can be taken off a truck; and `allowed_put_ups` is a non-empty subset of the two put-up specs `MASTER_REEL` and `CUT`, restricting what may be quoted for the part.

### 3.2. The Copper Market Feed and the Index Shock Cascade

Copper is repriced daily, and the platform mirrors that by holding a series of published settlements. A `PlatformAdmin` publishes one by supplying an `effective_date` — a calendar date in `YYYY-MM-DD` form, interpreted in UTC, unique across all entries — and a `price_cents_per_lb`, the published COMEX settlement in whole cents per pound, which must be greater than 0. Publishing a date that already exists is rejected with `ERR_DUPLICATE_INDEX_DATE`. The entry records the publishing administrator in `published_by_user_id`, and the series can be read back either one entry at a time or as a list narrowed by `effective_date_from` and `effective_date_to`.

Publication is not a passive act of record-keeping. A large overnight move in copper invalidates the pricing basis of quotes that are already out with customers, and the platform reacts to that inside the publication request itself. For each candidate quote, the system compares the newly published settlement against the settlement the quote pinned when it was issued. The deviation is the absolute difference between the new entry's `price_cents_per_lb` and the pinned entry's `price_cents_per_lb`, divided by the pinned entry's `price_cents_per_lb`, computed as an exact ratio over integer cents. An index shock exists when two conditions both hold: the new entry's `effective_date` is later than the pinned entry's `effective_date`, and the deviation is strictly greater than the volatility tolerance of three percent. A deviation exactly equal to three percent is not a shock and leaves the quote alone.

Which quotes are candidates is deliberately narrow. Every quote in `ISSUED` status is evaluated. So is every quote in `CONVERTED` status whose sales order is still physically uncommitted — that is, whose `fulfillment_status` is `PENDING_ALLOCATION`, `PARTIALLY_ALLOCATED` or `HELD`. A `CONVERTED` quote whose order has already reached `ALLOCATED`, `STAGED`, `DELIVERED` or `CANCELLED` keeps its pricing and is never voided. Quotes in `DRAFT`, `EXPIRED` or `VOIDED` status are excluded outright. Candidates are evaluated in ascending order of the quote's `created_at`, and neither the quote's branch nor its customer restricts the sweep: every quote in the system is considered.

**Cascade link 1.** A quote that shocks moves `ISSUED → VOIDED`, or `CONVERTED → VOIDED` when the candidate was a converted quote whose order is still uncommitted, with `void_reason` set to `INDEX_SHOCK`, and the newly published entry's `voided_quote_count` is incremented by one for each quote it voids. That counter is the publication's permanent record of how much business the move invalidated.

**Cascade link 2.** Because those quotes became `VOIDED`, every sales order converted from one of them whose `fulfillment_status` is `PENDING_ALLOCATION`, `PARTIALLY_ALLOCATED` or `HELD` moves to `CANCELLED`, and its `billing_status` moves from `UNBILLED` to `VOIDED` in the same step. Orders further along the fulfilment axis are untouched.

**Cascade link 3.** Because those orders became `CANCELLED`, every allocation on their lines still in `RESERVED` status moves to `RELEASED`, decrementing the holding reel's `allocated_length_ft` by the released footage. A reel whose `allocated_length_ft` falls back to 0 as a result moves from `ALLOCATED_PARTIAL` back to `IN_STOCK`. No physical footage is consumed by this cascade — only reservations are unwound.

### 3.3. Composing a Quote

A `SalesRep` opens a quote against a `customer_id` and a `branch_id`. The branch matters twice over: it fixes the freight surcharge that will apply and it fixes the reel pool the eventual order will draw from. A new quote is born in `DRAFT` status with `created_by_user_id` set to the acting operator's identifier, `copper_index_entry_id` null, `issued_at`, `valid_until`, `issued_by_user_id` and `void_reason` all null, and every money field — `line_subtotal_cents`, `physical_reel_count`, `gross_freight_cents`, `rebate_pct`, `rebate_cents`, `freight_cents`, `quoted_total_cents` and `deposit_quoted_cents` — at 0. A quote's `status` takes one of `DRAFT`, `ISSUED`, `CONVERTED`, `EXPIRED` or `VOIDED`; the `void_reason`, when set, is either `INDEX_SHOCK` or `CREDIT_HOLD`.

Lines are then added to the draft one at a time, each naming a `product_id`, a `put_up`, a `requested_length_ft` greater than 0, an optional `parallel_set_size`, and the `expected_quote_version` guard described in Section 2.8. `parallel_set_size` defaults to 1 and may not exceed 4; it is the number of paralleled conductors making up one NEC paralleled circuit, and any value above 1 forces the same-lot, whole-conductor rule that Section 3.6 imposes on allocation. Each line receives a `line_number` assigned as one more than the count of lines already on the quote, so numbering is 1-based and follows creation order; that number is what fixes allocation processing order later. The line stores its own `quote_id`. A line whose requested `put_up` is not a member of the part's `allowed_put_ups` is rejected with `ERR_PUT_UP_NOT_ALLOWED`, and a `CUT` line asking for fewer than 25 feet per conductor is rejected with `ERR_BELOW_ABSOLUTE_MIN_CUT` — below that length a run cannot be safely terminated. Adding a line to a quote that is no longer `DRAFT` is rejected with `ERR_QUOTE_NOT_DRAFT`.

Adding a line immediately settles the part of the price that does not depend on the copper market: the billable footage, the reel count, the cut charge and the deposit. The rules are put-up dependent and are computed per conductor. For a `CUT` line, `billable_length_ft` is the greater of `requested_length_ft` and the part's `min_cut_length_ft` — a customer asking for less than the billing minimum is billed at the minimum — and `reel_count` is exactly 1, representing the single disposable shipping reel the cut travels on. For a `MASTER_REEL` line, `reel_count` is `requested_length_ft` divided by the part's `master_reel_length_ft`, rounded up to the next whole number, and `billable_length_ft` is that reel count multiplied by `master_reel_length_ft` — the customer buys whole put-ups.

The cut charge is then selected from a three-way tier, and the tier is keyed on the per-conductor `billable_length_ft`, never on the paralleled total. A `MASTER_REEL` line carries no cut charge at all: its per-conductor charge is 0. Otherwise, a per-conductor billable length below 100 feet carries twice the part's `cut_charge_cents`, because short cuts cost the same setup as long ones; a per-conductor billable length from 100 feet up to but not including 500 feet carries exactly one times `cut_charge_cents`; and a per-conductor billable length of 500 feet or more carries no cut charge, the cut being absorbed into the volume. Paralleling multiplies the resulting charge rather than the tier: `cut_charge_cents_total` is the per-conductor charge multiplied by `parallel_set_size`.

The reel deposit is calculated on the same request and kept strictly apart from the price. `deposit_cents_total` is the part's `reel_deposit_cents` multiplied by `reel_count` and again by `parallel_set_size` for a `MASTER_REEL` line, and is 0 for a `CUT` line — cut cable ships on a disposable reel and carries no refundable deposit. The deposit is refundable and never enters the quote's `quoted_total_cents`; it is accumulated separately into `deposit_quoted_cents`.

For as long as the quote remains `DRAFT`, the quote-level roll-up fields stay at 0 as well: `line_subtotal_cents`, `physical_reel_count`, `gross_freight_cents`, `rebate_pct`, `rebate_cents`, `freight_cents`, `quoted_total_cents` and `deposit_quoted_cents` are filled only when the quote is issued, which is why the segregation-of-duties test must use the subtotal the issue request computes rather than the stored one. Everything that depends on the copper market is likewise deliberately left unset while the quote is a draft. A newly added line has `copper_adder_cents_per_ft`, `metal_cents`, `base_cents` and `quoted_extended_cents` all sitting at 0 until the quote is issued. Lines can be read back individually or listed, narrowed by `quote_id` or by `product_id`.

### 3.4. Issuing a Quote: Pinning the Index and Rolling Up the Money

Issuing is the moment a draft becomes a commercial offer, and it takes no request body at all — everything it needs is already on the quote. It moves the quote `DRAFT → ISSUED` and is available only while the quote is `DRAFT`; an attempt against any other status is rejected with `ERR_QUOTE_NOT_DRAFT`. A quote with zero lines cannot be issued and is rejected with `ERR_QUOTE_HAS_NO_LINES`. Issue also requires a market to price against: if no copper index entry exists whose `effective_date` is on or before the current logical date, the request fails with `ERR_NO_COPPER_INDEX`.

Given a market, the quote pins one entry into `copper_index_entry_id`: the entry with the greatest `effective_date` that is on or before the current logical date. Because `effective_date` is unique across entries, no tie-break is needed. That pinned entry is the quote's pricing basis for as long as it stays issued.

**Per-line pricing, QUOTED variant.** With the index pinned, every line on the quote is repriced from scratch, in ascending `line_number`; ties are impossible because the number is unique within a quote. For a part whose `conductor_metal` is `ALUMINUM`, the copper pass-through `copper_adder_cents_per_ft` is exactly zero at four decimal places. For a `COPPER` part, `copper_adder_cents_per_ft` is the pinned entry's `price_cents_per_lb` multiplied by the part's `copper_lbs_per_1000ft` divided by one thousand — that is, cents per pound times pounds per foot. This value is held at exactly four decimal places and is deliberately left unrounded; it is the only place in the system where fractional cents are allowed to live.

The line's total billable footage is its per-conductor `billable_length_ft` multiplied by its `parallel_set_size`. From that, `metal_cents` is the `copper_adder_cents_per_ft` multiplied by the total billable footage and then rounded half up to whole cents — rounded once, on this line, before any summation. `base_cents` is the part's `base_price_cents_per_ft` multiplied by the same total billable footage, and being a product of integers it is exact. The line's `quoted_extended_cents` is then `base_cents` plus `metal_cents` plus the `cut_charge_cents_total` already fixed at line-add time; the deposit is excluded. It is forbidden to accumulate the unrounded pass-through across lines and round the sum once: two identical 137-foot lines of a part priced at 5.6250 cents per foot yield 771 plus 771, that is 1542 metal cents in total, not the 1541 that a single rounding of the sum would produce.

**The order money roll-up.** With every line priced, the quote's own money fields are computed. The freight and the rebate depend on one another in a way that looks circular — freight feeds the rebate tier, the rebate feeds the free-freight test, the free-freight test changes freight — so the dependency is broken by a pinned six-step evaluation order. The steps run exactly once each, in this sequence, and no step is re-run after step five.

First, `line_subtotal_cents` is the sum, across all lines, of the already-rounded per-line extended values. Second, `physical_reel_count` is the sum across lines of each line's `reel_count` multiplied by its `parallel_set_size`, and `gross_freight_cents` is a flat base of 8,500 cents, plus 2,500 cents for every physical reel counted, plus the shipping branch's `delivery_surcharge_cents`. Third, the volume rebate tier is selected on a basis equal to `line_subtotal_cents` plus `gross_freight_cents`: a basis below 200,000 cents (2,000 dollars) sets `rebate_pct` to 0.000; a basis of 200,000 cents or more but below 500,000 cents (5,000 dollars) sets `rebate_pct` to 0.015; a basis of 500,000 cents or more sets `rebate_pct` to 0.030. Fourth, `rebate_cents` is `line_subtotal_cents` multiplied by `rebate_pct`, rounded half up to whole cents — the rebate applies to the subtotal alone and never to freight. Fifth, the free-freight waiver is tested on the post-rebate net: take `line_subtotal_cents` plus `gross_freight_cents` less `rebate_cents`, and if that net is 500,000 cents or more — the comparison is inclusive of the threshold — then `freight_cents` is 0, otherwise `freight_cents` equals `gross_freight_cents`. Sixth, `quoted_total_cents` is `line_subtotal_cents` plus `freight_cents` less `rebate_cents`. The rebate tier is emphatically not recomputed after the waiver zeroes freight, even though the basis would now be lower. Deposits take no part in any of the six steps; `deposit_quoted_cents` is simply the sum of every line's `deposit_cents_total`.

**Segregation of duties.** The issue request also carries the control described in Section 2.9. The subtotal it tests is the one it has just computed in this very request under the index it is pinning, not the stored `line_subtotal_cents`, which is still 0 because the quote was `DRAFT` until a moment ago. When that computed subtotal is at or above 250,000 cents, the acting `X-User-ID` must differ from `created_by_user_id`, otherwise the issue is refused with `ERR_SEGREGATION_OF_DUTIES` and nothing is written. Below the threshold, a rep may issue their own work.

A successful issue stamps `issued_at` with the current logical instant, sets `valid_until` to twenty-four hours after `issued_at`, records the acting operator in `issued_by_user_id`, and advances the quote's `version`.

### 3.5. Revision, Expiry and Conversion into a Sales Order

Quotes go stale. A `SalesRep` facing a customer who took a week to decide reopens the offer by repricing it, which moves the quote `ISSUED → DRAFT` and is available only from `ISSUED`; from any other status it is refused with `ERR_QUOTE_NOT_ISSUED`. Repricing takes no request body and is a deliberate erasure: `copper_index_entry_id`, `issued_at`, `valid_until` and `issued_by_user_id` are all cleared back to null, and `line_subtotal_cents`, `gross_freight_cents`, `rebate_pct`, `rebate_cents`, `freight_cents`, `quoted_total_cents` and `deposit_quoted_cents` are all zeroed, as is every money field on every one of the quote's lines. The line structure survives; only its pricing is discarded. The rep may then add or leave the lines as they are and issue again against whatever index is current, which restarts the twenty-four-hour window from the new `issued_at`. This is the revision cycle, and the quote may go round it any number of times.

Conversion is the other exit from `ISSUED`. It takes no request body and, when it succeeds, moves the quote `ISSUED → CONVERTED` and creates the order. Four things are checked. The quote must be `ISSUED`, else `ERR_QUOTE_NOT_ISSUED`. The current logical instant must be at or before `valid_until` — the upper bound is inclusive, so a conversion at exactly the expiry instant still succeeds. The customer's `credit_status` must be `ACTIVE`, else `ERR_CUSTOMER_CREDIT_HOLD`. And the customer's `available_credit_cents` must be at least the quote's `quoted_total_cents`, else `ERR_CREDIT_LIMIT_EXCEEDED`.

Validity is enforced lazily, at conversion, so that expiry is observable without any background job. When a conversion arrives after `valid_until` has passed, the same request moves the quote `ISSUED → EXPIRED` and then fails with `ERR_QUOTE_EXPIRED`; no sales order is created, and the quote's `version` still advances because the quote itself changed. `EXPIRED` and `VOIDED` are terminal: nothing brings a quote back from either. `CONVERTED`, by contrast, is a settled rather than a terminal state — as Section 3.2 describes, an index shock can still reach a converted quote whose order has not yet been physically committed.

A successful conversion writes one sales order and one order line per quote line. The order starts with `fulfillment_status` at `PENDING_ALLOCATION` and `billing_status` at `UNBILLED`, and copies `customer_id`, `branch_id`, `line_subtotal_cents`, `freight_cents`, `rebate_cents` and `quoted_total_cents` from the quote, along with the originating `quote_id`. Each order line copies its `line_number`, `put_up`, `requested_length_ft`, `parallel_set_size`, `billable_length_ft` and `quoted_extended_cents` from the corresponding quote line, records its `sales_order_id` and `product_id`, and derives two further values: `required_length_ft` is `billable_length_ft` multiplied by `parallel_set_size`, the total footage the line must be given; and `returnable` is true exactly when `put_up` is `MASTER_REEL`, false for a `CUT` line, because cut cable ships on a disposable reel that never comes back. Each new line starts with `allocated_length_ft` at 0, `allocation_status` at `UNALLOCATED`, `lot_code` at null and `invoiced_extended_cents` at null.

The order also carries the money it has not yet earned. `invoiced_total_cents` and `metal_variance_cents` are null until delivery, `deposit_charged_cents` and `deposit_credited_cents` start at 0, `delivered_at` is null, and `allocation_policy` starts at `MINIMIZE_REMNANT`. The two status axes are genuinely independent: `fulfillment_status` moves through `PENDING_ALLOCATION`, `PARTIALLY_ALLOCATED`, `ALLOCATED`, `STAGED`, `DELIVERED`, `HELD` and `CANCELLED`, while `billing_status` moves through `UNBILLED`, `INVOICED`, `CREDITED` and `VOIDED`, and a movement on one axis never implies a movement on the other except where this document says so explicitly. `DELIVERED` and `CANCELLED` are terminal on the fulfilment axis; `CREDITED` and `VOIDED` are terminal on the money axis. Orders and their lines can be listed and narrowed by `customer_id`, `quote_id`, `branch_id`, `fulfillment_status`, `billing_status`, `sales_order_id`, `product_id` or `allocation_status`.

### 3.6. Reel Stock, Lineage and the Allocation Run

Physical stock is received one reel at a time by a `BranchOps` operator or a `PlatformAdmin`, naming the `product_id` wound on it, the `branch_id` where it will sit, the mill `lot_code` stamped on it, and the `nominal_length_ft` it carries, which must be greater than 0. A received reel is a master reel: its `reel_type` is `MASTER`, its `parent_reel_id` is null, its `current_length_ft` starts equal to `nominal_length_ft`, its `allocated_length_ft` starts at 0, its `scrap_ft` starts at 0, its `delivered_sales_order_id` and `delivered_at` start null, and its `status` starts at `IN_STOCK`. `nominal_length_ft` is never mutated afterwards — it is the historical record of what came off the mill — while `current_length_ft` tracks what is physically left. `available_length_ft` is always `current_length_ft` less `allocated_length_ft`, and `reel_type` is either `MASTER` or `REMNANT`, the latter reserved for reels spawned by a cut.

A reel's `status` moves through five values. `IN_STOCK` means idle and sellable. `ALLOCATED_PARTIAL` means at least one reservation is outstanding against it. `ON_JOBSITE` means the whole reel travelled to a customer's site and has not yet come back. `DEPLETED` and `SCRAPPED` are terminal: the first means the reel is physically empty, the second that its remaining footage was written off. Reels can be listed and narrowed by `branch_id`, `product_id`, `status`, `lot_code` and `reel_type`; filtering on `parent_reel_id` finds every remnant spawned from a given reel, and filtering on `delivered_sales_order_id` finds the reels a customer is currently holding at a jobsite.

Two invariants make the inventory auditable. The available footage a branch holds for a part is the sum, over every reel of that part at that branch whose `status` is `IN_STOCK` or `ALLOCATED_PARTIAL`, of that reel's `current_length_ft` less its `allocated_length_ft`; reels that are `ON_JOBSITE`, `DEPLETED` or `SCRAPPED` contribute nothing. Reserving footage and then releasing it must leave that figure exactly as it was before the reservation, and must leave every touched reel's `current_length_ft` untouched — reservations move numbers, not cable. Separately, footage is conserved across cutting: for any reel received into stock, its `nominal_length_ft` equals its own remaining `current_length_ft`, plus the `current_length_ft` of every descendant reel reachable through `parent_reel_id`, plus the `scrap_ft` recorded on it and on all of those descendants, plus the `length_ft` of every allocation in `COMMITTED` or `CONSUMED` status whose `commit_mode` is `CUT` and whose reel is that reel or one of its descendants.

**The allocation run.** A `BranchOps` operator running their own branch drives the allocator over one sales order, supplying an optional `allocation_policy` and the mandatory `expected_sales_order_version`. The order must be in `PENDING_ALLOCATION` or `PARTIALLY_ALLOCATED`, otherwise `ERR_ORDER_NOT_ALLOCATABLE`; the customer must not be on credit hold, otherwise `ERR_CUSTOMER_CREDIT_HOLD`; and the operator's `X-User-ID` must equal the order's `branch_id`, otherwise `ERR_NOT_RESOURCE_OWNER`. The order's `allocation_policy` is set to whatever policy this run used.

Lines are processed in ascending `line_number`. For each line the residual demand is `required_length_ft` less `allocated_length_ft`; a line whose residual is zero or below is skipped entirely, which is what makes a re-run after restock top up only the shortfall and leave existing reservations alone. The candidate pool for a line is every reel of that line's `product_id` sitting at the order's `branch_id`, in `status` `IN_STOCK` or `ALLOCATED_PARTIAL`, with available footage strictly greater than 0.

Three branches then decide what is picked. When `parallel_set_size` is greater than 1, the same-lot, whole-conductor rule applies and is all-or-nothing: each of the paralleled conductors must be one continuous run, so each needs its own reel holding at least `billable_length_ft` of available footage, and all of them must share one mill lot. Distinct `lot_code` values among the candidates are examined in ascending lexical order, and the first lot offering at least `parallel_set_size` qualifying reels is chosen; the line's `lot_code` is pinned to it. If no lot can furnish the whole set, the run fails with `ERR_PARALLEL_SET_INCOMPLETE` — a paralleled set is never partially filled. Within the chosen lot, reels are ranked by the active policy and the first `parallel_set_size` of them are taken, one allocation per reel, each for exactly `billable_length_ft`.

When `parallel_set_size` is 1 and the line's `put_up` is `MASTER_REEL`, the allocator performs a whole-reel pick: it considers only untouched full master reels, meaning candidates whose `reel_type` is `MASTER`, whose `allocated_length_ft` is 0, whose `current_length_ft` still equals their `nominal_length_ft`, and whose `nominal_length_ft` equals the part's `master_reel_length_ft`. Those are taken in ascending `created_at`, up to the line's `reel_count` or however many exist, whichever is fewer, and each yields one allocation whose `length_ft` is the whole reel's `current_length_ft`.

Otherwise — a single-conductor cut line — the allocator waterfalls, and splitting across reels is permitted. It repeatedly takes the highest-ranked candidate, allocates the lesser of the footage still outstanding and that reel's available footage, records the allocation, subtracts what it took from the outstanding amount, and drops that reel from the pool. It stops when the outstanding amount reaches zero or the pool runs dry.

Ranking is the only place the two policies differ, and both tie-break on ascending `created_at`, never on identifier. Under `MINIMIZE_REMNANT` — the policy used when `allocation_policy` is omitted — the allocator best-fits: among candidates whose available footage is at least the footage still needed for this pick, it chooses the one with the smallest available footage, so that the least usable cable is left behind. If no candidate is large enough, it falls through to ranking by available footage descending and splits. Under `FEWEST_REELS`, the allocator ranks by available footage descending unconditionally, so the largest reel is always broached first. The two policies genuinely diverge: for a 300-foot need against reels of 400, 1000 and 250 feet, `MINIMIZE_REMNANT` broaches the 400-foot reel and `FEWEST_REELS` broaches the 1000-foot reel — the same demand, a different reel, and a different remnant.

Each created allocation records the `order_line_id` it serves, the denormalised `sales_order_id`, the `reel_id` holding the footage, a 1-based `sequence_no` giving its position within the order line in the order the allocator picked reels, and the `length_ft` held. It is born in `status` `RESERVED` with `commit_mode`, `cut_window_start`, `cut_window_end` and `remnant_reel_id` all null and `cut_charge_applied_cents` and `scrap_ft` at 0. For each allocation created, the holding reel's `allocated_length_ft` rises by that allocation's `length_ft`; a reel whose `allocated_length_ft` becomes greater than 0 moves `IN_STOCK → ALLOCATED_PARTIAL`, and its `available_length_ft` is recomputed.

Afterwards each line's `allocated_length_ft` is recomputed as the sum of the `length_ft` of its allocations in `RESERVED`, `COMMITTED` or `CONSUMED` status, and its `allocation_status` becomes `FULLY_ALLOCATED` when that equals `required_length_ft`, `SHORT` when it is greater than 0 but less than `required_length_ft`, and `UNALLOCATED` when it is 0. The order then follows: if every line is `FULLY_ALLOCATED` the order moves to `ALLOCATED`; if at least one allocation was created but at least one line ends `SHORT` or `UNALLOCATED`, the order moves to `PARTIALLY_ALLOCATED`. This is allocation on shortage — the run takes what the branch has rather than failing. The re-run path is the same machinery: a `PARTIALLY_ALLOCATED` order re-allocated after restock moves `PARTIALLY_ALLOCATED → ALLOCATED` once every line is finally full. Only one outcome is fatal: if the entire run creates zero allocations across the whole order, the request fails with `ERR_NO_ELIGIBLE_REEL` and nothing whatsoever is persisted.

**Releasing.** The compensating action hands the footage back. Available from `PARTIALLY_ALLOCATED` or `ALLOCATED`, taking no request body, it requires that every allocation on the order is still `RESERVED` — a single committed allocation anywhere on the order makes the release impossible and yields `ERR_ALLOCATION_NOT_RESERVED` — and requires the acting operator to own the order's branch. Every `RESERVED` allocation moves `RESERVED → RELEASED`; each release decrements its reel's `allocated_length_ft` by the allocation's `length_ft`, and a reel whose `allocated_length_ft` returns to 0 moves `ALLOCATED_PARTIAL → IN_STOCK` provided it still carries physical footage. Every line is reset to `allocated_length_ft` 0 and `allocation_status` `UNALLOCATED`, and the order returns to `PENDING_ALLOCATION` from either starting state. Because nothing physical moved, the branch's available footage for the part is exactly what it was before the run.

Allocations can be read individually or listed, narrowed by `order_line_id`, `sales_order_id`, `reel_id`, `status`, or by `remnant_reel_id` to find the cut that produced a given remnant.

### 3.7. The Commit Fork: Cutting Footage and Picking Whole Reels

A reservation is only a promise; committing it is what puts cable on the loading dock. Every allocation leaves `RESERVED` by exactly one of two branches, and which branch is legal is decided by the order line's `put_up`. Both branches are driven by the `BranchOps` operator who owns the reel's `branch_id`, both require the allocation to still be `RESERVED` (otherwise `ERR_ALLOCATION_NOT_RESERVED`), and both move the allocation `RESERVED → COMMITTED` while recording which branch was taken in `commit_mode`, valued `CUT` or `PICK`. Choosing the wrong branch for the line is rejected with `ERR_PUT_UP_MISMATCH`: cutting is only for a `CUT` line, picking only for a `MASTER_REEL` line.

**The cut branch.** Cutting occupies the branch's cut floor, so the request supplies the two instants `cut_window_start` and `cut_window_end`. The end must be strictly after the start, otherwise `ERR_INVALID_CUT_WINDOW`. The window a cut actually consumes is not the window requested: a cleanup buffer of thirty minutes is appended to the end, and the cut is treated as occupying the closed interval from `cut_window_start` through `cut_window_end` plus thirty minutes. Occupancy is counted against every allocation at the same branch whose `commit_mode` is `CUT` and whose `status` is `COMMITTED` or `CONSUMED`; reservations and releases hold no window and are ignored. The requested interval collides with such an existing interval when the requested start is at or before the existing `cut_window_end` plus thirty minutes, and the existing `cut_window_start` is at or before the requested buffered end. Both comparisons are inclusive, so touching endpoints collide — a cut starting at exactly the instant a previous cut's buffered window ends is a collision, not an adjacency. If the number of colliding intervals reaches the branch's `concurrent_cut_capacity`, the request is refused with `ERR_CUT_BAY_CAPACITY_EXCEEDED`; a branch with capacity 1 therefore admits a cut only when nothing else overlaps it.

A permitted cut confirms the tiered charge into `cut_charge_applied_cents`, recomputing it from the order line's `billable_length_ft` and the part's `cut_charge_cents` under exactly the tier rules of Section 3.3, and stamps `cut_window_start` and `cut_window_end` onto the allocation. It then decrements the source reel's `current_length_ft` and its `allocated_length_ft`, both by the allocation's `length_ft`, and settles what is left on the reel.

That settlement is a five-way decision, evaluated in this exact order after the decrement, and only the first matching branch fires. One: if the reel's `current_length_ft` has reached 0, the reel moves to `DEPLETED`. Two: otherwise, if the reel's `allocated_length_ft` is still greater than 0, the reel is still carrying another reservation and settlement is deferred — the reel keeps its remainder, stays `ALLOCATED_PARTIAL`, spawns no remnant and scraps nothing, and the question is revisited when that other reservation commits. Three: otherwise, if the remaining `current_length_ft` is less than the part's `min_cut_length_ft`, the remainder is unsellable: the reel's `scrap_ft` is set to that remainder, its `current_length_ft` is set to 0, its `allocated_length_ft` is set to 0, the reel moves to `SCRAPPED`, the same footage is copied onto the allocation's own `scrap_ft`, and the branch's `scrap_ft_ytd` rises by that remainder with the branch's `version` advancing. Four: otherwise, if the reel's `reel_type` is `MASTER`, the viable remainder becomes a new reel — a fresh record with `reel_type` `REMNANT`, `parent_reel_id` pointing at the reel it came off, and `lot_code`, `product_id` and `branch_id` inherited from it, whose `nominal_length_ft` and `current_length_ft` both equal the remainder and whose `status` is `IN_STOCK`; the new reel's identifier is recorded on the cutting allocation as `remnant_reel_id`, and the source reel's `current_length_ft` is then set to 0 and the source reel moves to `DEPLETED`. Five: otherwise — a reel that is itself a `REMNANT` and still holds a viable remainder — the reel simply keeps its footage and returns to `IN_STOCK`, with no further remnant spawned. Remnants are therefore cut down in place rather than recursively spawning children.

Both terminal outcomes are reachable from either `IN_STOCK` or `ALLOCATED_PARTIAL`, depending on whether the committing reservation was the reel's only one: a reel with no other reservation goes `IN_STOCK → DEPLETED` or `IN_STOCK → SCRAPPED`, and a reel carrying the last of several goes `ALLOCATED_PARTIAL → DEPLETED` or `ALLOCATED_PARTIAL → SCRAPPED`.

**The pick branch.** Picking is the deliberately inert counterpart. It takes no request body. It sets `commit_mode` to `PICK` and leaves `cut_window_start`, `cut_window_end`, `cut_charge_applied_cents`, `scrap_ft` and `remnant_reel_id` at their defaults — there is no cut window to reserve, no cut-floor capacity to test, no cut charge to apply, no remnant to spawn and no footage to scrap. The reel's `current_length_ft`, `allocated_length_ft` and `status` are all left exactly as they are, because the whole reel travels intact and stays reserved to this order until it physically leaves. What the picked reel does carry, and the cut never does, is the refundable deposit that Section 3.9 credits back when it returns.

Both branches end the same way. When the commit that just happened was the last one — that is, when every allocation on the order has reached `COMMITTED` — the order bubbles up `ALLOCATED → STAGED` on its fulfilment axis, and the goods are ready for a truck. Until then the order stays `ALLOCATED`, and the allocation's own `version` advances on each commit.

### 3.8. Jobsite Delivery: Scheduling, Handling and the Delivery Cascade

A `BranchOps` operator schedules a run for one staged order on one truck, supplying the `sales_order_id`, the `truck_id`, a `window_start` and a `window_end` bounding the truck's occupation, the `jobsite_address` printed on the run sheet, and an optional `jobsite_has_forklift` flag declaring whether the site provides its own forklift, which defaults to false. The run copies its `branch_id` from the order and starts in `status` `SCHEDULED`, with `dispatched_at` and `delivered_at` null. Runs are addressed one at a time or listed, narrowed by `sales_order_id`, `truck_id`, `branch_id` or `status`.

Three admission rules guard the schedule. The truck must be domiciled at the order's branch, otherwise `ERR_TRUCK_BRANCH_MISMATCH`. The order must not already have a run in `SCHEDULED` or `DISPATCHED` status, otherwise `ERR_ORDER_HAS_ACTIVE_RUN` — a delivered run does not block a new one, but an open one does. And the truck must be free. Truck occupancy is deliberately the opposite of the cut floor: the requested window is half-open, running from `window_start` inclusive to `window_end` exclusive, and it conflicts with an existing run on the same truck when the requested start is strictly before that run's `window_end` and that run's `window_start` is strictly before the requested end. Both comparisons are strict, so a run beginning at exactly the instant another ends is accepted. Every run on the truck is considered regardless of `status`, including runs already delivered — runs are never deleted, so a historical window still blocks its slot. A conflict is refused with `ERR_TRUCK_WINDOW_CONFLICT`, and a truck's occupancy is exclusive: capacity is one, not a configured count.

Scheduling also derives how the reels come off the deck. `heaviest_reel_lbs` is the greatest `reel_weight_lbs` among the parts of the order's allocations that are `COMMITTED` with `commit_mode` `PICK`; an all-cut order has no such allocation and its `heaviest_reel_lbs` is 0, because cut cable rides on disposable reels and never drives handling. From that, `reel_handling` is derived as one of three values. If `jobsite_has_forklift` is true the method is `FORKLIFT`, and that branch wins outright — a site with its own forklift never demands a boom lift, however heavy the reel. Otherwise, if `heaviest_reel_lbs` is strictly greater than 250 pounds the method is `BOOM_LIFT`. Otherwise it is `TAILGATE`. A run whose derived method is `BOOM_LIFT` may only be assigned to a truck whose `has_boom_lift` is true; assigning it to a truck without one is refused with `ERR_BOOM_LIFT_REQUIRED`.

Dispatch belongs to the driver. A `Driver` whose `X-User-ID` is the run's `truck_id` moves the run `SCHEDULED → DISPATCHED` with no request body, stamping `dispatched_at` with the current logical instant. The run must be `SCHEDULED`, otherwise `ERR_RUN_INVALID_STATE`, and the order behind it must have reached `STAGED`, otherwise `ERR_ORDER_NOT_STAGED` — the truck does not leave until every allocation is committed.

Completing the run is the single largest cascade in the system. The driver, again owning the truck, moves the run `DISPATCHED → DELIVERED` with no request body; a run in any other state yields `ERR_RUN_INVALID_STATE`. The run's `delivered_at` is stamped, and then five links fire in order.

**Cascade link 1.** The order moves `STAGED → DELIVERED` on its fulfilment axis and its own `delivered_at` is stamped with the same instant.

**Cascade link 2.** Because the order was delivered, every allocation on it that is `COMMITTED` moves `COMMITTED → CONSUMED`. Each consumed allocation whose `commit_mode` is `PICK` sends its reel `ALLOCATED_PARTIAL → ON_JOBSITE`, sets that reel's `delivered_sales_order_id` to the order's identifier and its `delivered_at` to the current instant, and zeroes its `allocated_length_ft`; the reel is now out at the customer's site, contributing nothing to branch availability. Allocations committed under `CUT` move no reel — the cable already left the reel when it was cut. In the same link the order's `billing_status` moves `UNBILLED → INVOICED`.

**Cascade link 3.** Invoicing reprices the order under the second pricing variant. Every order line is repriced by exactly the same per-line arithmetic as Section 3.4 — the aluminium zero, the four-decimal pass-through, the once-per-line half-up rounding into whole cents, the exact integer base, and the unchanged cut charge — with one substitution: the index used is no longer the one pinned on the quote, but the copper index entry with the greatest `effective_date` on or before the calendar date of the order's `delivered_at`, which may well be a different entry. The result is written to each line's `invoiced_extended_cents`; `base_cents` and the cut charge are identical under both variants, so only the metal component moves. The order's `metal_variance_cents` is the sum across lines of `invoiced_extended_cents` less `quoted_extended_cents`. The order-level roll-up is then re-run over the invoiced line values in the same pinned six-step sequence — subtotal, gross freight from the physical reel count and the branch surcharge, rebate tier on subtotal plus gross freight, rebate on the subtotal alone, the inclusive free-freight waiver on the post-rebate net, and finally the total — writing `invoiced_total_cents`. Separately, `deposit_charged_cents` is set to the sum of the `reel_deposit_cents` of the parts behind every `PICK`-committed allocation on the order.

**Cascade link 4.** Because the order was invoiced, the customer's `open_balance_cents` rises by `invoiced_total_cents` plus `deposit_charged_cents`, and their `deposit_liability_cents` rises by `deposit_charged_cents`. `available_credit_cents` is recomputed as `credit_limit_cents` less `open_balance_cents`.

**Cascade link 5.** If that recomputation leaves `available_credit_cents` below 0 while the customer is `ACTIVE`, the customer moves `ACTIVE → CREDIT_HOLD`, and the consequences described in Section 3.9 follow within the same request: every one of that customer's quotes in `ISSUED` status is voided with `void_reason` `CREDIT_HOLD`, and every one of their orders in `PENDING_ALLOCATION` moves to `HELD`.

### 3.9. Reel Returns, Deposit Credits and Credit Posture

Empty master reels are the distributor's property, and the deposit is the lever that gets them back. A `BranchOps` operator owning the reel's `branch_id` records a return against the order line the reel shipped under, supplying the `reel_id` being handed back and the `condition` it came back in, which is either `GOOD` or `DAMAGED`. Four checks run in exactly this sequence, and the first failure is what the caller sees. The order must have reached `DELIVERED` on its fulfilment axis, otherwise `ERR_ORDER_NOT_DELIVERED`. The order line must be `returnable`, otherwise `ERR_CUT_ITEM_NON_RETURNABLE` — a cut item is never returnable, and this check deliberately precedes the identity check because a `CUT` line never shipped a returnable reel and would otherwise always fail on identity instead. The reel's `delivered_sales_order_id` must equal the order line's `sales_order_id`, otherwise `ERR_REEL_NOT_ON_ORDER_LINE`. And the reel must currently be `ON_JOBSITE`, otherwise `ERR_REEL_NOT_ON_JOBSITE`.

A valid return moves the reel `ON_JOBSITE → IN_STOCK` and clears its `delivered_at` back to null. Its `delivered_sales_order_id` is deliberately retained: that field is the permanent shipment record, not a flag for whether the reel is out, and keeping it is what causes a second return of the same reel to be caught by the jobsite-status check rather than by the identity check.

The credit is then computed on the elapsed time since the order was delivered. Elapsed days are the whole number of complete 86,400-second days between the order's `delivered_at` and the current logical instant, with any partial day discarded. Inside a sixty-day return window, a reel handed back in `GOOD` condition earns the full deposit — a credit rate of 1.00 — and a reel handed back `DAMAGED` earns half of it, a rate of 0.50. Beyond sixty elapsed days no credit is earned at all, whatever the condition, and the rate is 0.00. The window boundary is inclusive: a return at exactly sixty elapsed days still earns its full or half credit, and one at sixty-one earns nothing. The credited amount is the part's `reel_deposit_cents` multiplied by that rate and rounded half up to whole cents.

**Cascade link 1.** The order's `deposit_credited_cents` rises by the credited amount. The customer's `deposit_liability_cents` falls by the part's *full* `reel_deposit_cents` regardless of the credit rate — the reel is back, so the liability is discharged even when the customer is not paid for it — while the customer's `open_balance_cents` falls only by the credited amount. A customer who has returned every reel therefore sees `deposit_liability_cents` back at exactly the value it held before the delivery, since that figure is by definition the sum of the `reel_deposit_cents` of the parts on every reel still `ON_JOBSITE` against that customer's orders.

**Cascade link 2.** Because the balance moved, `available_credit_cents` is recomputed as `credit_limit_cents` less `open_balance_cents`. If the customer was on `CREDIT_HOLD` and the recomputed figure is now 0 or above — the release boundary is inclusive, so exactly zero available credit releases the hold — the customer moves `CREDIT_HOLD → ACTIVE`.

**Cascade link 3.** Because the customer returned to `ACTIVE`, every one of their orders sitting in `HELD` moves back to `PENDING_ALLOCATION` and becomes allocatable again. Quotes that were voided for `CREDIT_HOLD` are not un-voided; a voided quote stays voided and the rep must build a new one.

Separately from the credit cascade, the return also settles the money axis when the last reel comes home: if the reel just returned was the final reel of that order still `ON_JOBSITE`, the order moves `INVOICED → CREDITED` on its `billing_status`. A partial return leaves the order `INVOICED`; only the final reel flips the axis.

**Posture, generally.** The credit posture rule is one rule with several triggers. Whenever a customer's balance or limit changes — at delivery invoicing, at a reel return, or at a `CreditManager` adjustment — `available_credit_cents` is recomputed as `credit_limit_cents` less `open_balance_cents`. A customer who is `ACTIVE` and whose recomputed available credit is below 0 moves `ACTIVE → CREDIT_HOLD`. A customer who is on `CREDIT_HOLD` and whose recomputed available credit is 0 or above moves `CREDIT_HOLD → ACTIVE`. The open balance is maintained incrementally by the invoicing and credit cascades and is never recomputed from scratch.

Going on hold has two consequences that fire in the same request. Every quote of that customer in `ISSUED` status moves to `VOIDED` with `void_reason` `CREDIT_HOLD`, and every order of that customer whose `fulfillment_status` is `PENDING_ALLOCATION` moves to `HELD`. An order that is already `PARTIALLY_ALLOCATED` is treated differently on purpose: it keeps its reservations and its status, and is instead stopped at the next allocation attempt by `ERR_CUSTOMER_CREDIT_HOLD`. A `CreditManager` adjustment can push a customer either way — a positive `delta_open_balance_cents` or a negative `delta_credit_limit_cents` may put them on hold, while a write-off or a limit increase may take them off it — and both directions carry their full cascades, the hold direction voiding issued quotes and holding pending orders, the release direction returning `HELD` orders to `PENDING_ALLOCATION`.

## 4. Endpoint Definitions

Every endpoint in the table below is mounted at the root of the service. Endpoints that mint a new resource — a branch, a truck, a customer, a catalog part, a copper index entry, a reel, a quote, a quote line, a sales order produced by conversion, or a delivery run — answer with HTTP 201 and return the created resource in `data`. Every other successful call, including all reads, all state-advancing actions and the clock capability, answers with HTTP 200 and returns the resource it modified. Error responses carry the status codes listed in Section 5. The table names only the HTTP contract and the authorised roles; the request payload, the response payload and the side effects of each call are specified in the narrative of Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/branches` | Register a distribution branch, its cut-floor capacity and its freight surcharge. | `PlatformAdmin` |
| GET | `/branches/{branchId}` | Read one branch, including its running scrap total. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `CreditManager` |
| POST | `/trucks` | Register a delivery truck at a branch. | `PlatformAdmin` |
| GET | `/trucks/{truckId}` | Read one truck. | `PlatformAdmin`, `BranchOps`, `Driver` |
| GET | `/trucks` | List trucks, optionally filtered to one branch. Results are ordered by created_at ASC. | `PlatformAdmin`, `BranchOps`, `Driver` |
| POST | `/customers` | Open a customer account with a credit limit. | `PlatformAdmin`, `CreditManager` |
| GET | `/customers/{customerId}` | Read one customer including credit posture and deposit liability. | `PlatformAdmin`, `CreditManager`, `SalesRep`, `Customer` |
| POST | `/customers/{customerId}/credit-adjustments` | Operator adjustment to a customer's credit limit and/or open balance (manual invoice, write-off, limit review). | `CreditManager` |
| POST | `/products` | Add a part to the cable catalog. | `PlatformAdmin` |
| GET | `/products/{productId}` | Read one catalog part. | `PlatformAdmin`, `SalesRep`, `BranchOps` |
| POST | `/copper-index-entries` | Publish a daily copper settlement. Publishing re-evaluates every ISSUED quote for index shock. | `PlatformAdmin` |
| GET | `/copper-index-entries/{entryId}` | Read one published index entry. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `CreditManager` |
| GET | `/copper-index-entries` | List published index entries, ordered by effective_date DESC (effective_date is unique, so no tie-break is reachable). | `PlatformAdmin`, `SalesRep`, `BranchOps`, `CreditManager` |
| POST | `/reels` | Receive a master reel into a branch's stock. | `BranchOps`, `PlatformAdmin` |
| GET | `/reels/{reelId}` | Read one reel, including remaining, reserved and scrapped footage. | `PlatformAdmin`, `BranchOps`, `SalesRep` |
| GET | `/reels` | List reels. parent_reel_id finds the remnants spawned from a reel; delivered_sales_order_id finds the reels a customer is holding on a jobsite. Results are ordered by created_at ASC. | `PlatformAdmin`, `BranchOps`, `SalesRep` |
| POST | `/quotes` | Open a DRAFT quote for a customer out of a branch. | `SalesRep` |
| GET | `/quotes/{quoteId}` | Read one quote, including the pinned copper index, validity window and money roll-up. | `PlatformAdmin`, `SalesRep`, `Customer` |
| GET | `/quotes` | List quotes; copper_index_entry_id finds every quote pinned to a given published index. Results are ordered by created_at ASC. | `PlatformAdmin`, `SalesRep`, `Customer` |
| POST | `/quotes/{quoteId}/lines` | Add a line to a DRAFT quote. OCC-guarded on the quote's version. | `SalesRep` |
| GET | `/quote-lines/{quoteLineId}` | Read one quote line and its priced components. | `PlatformAdmin`, `SalesRep`, `Customer` |
| GET | `/quote-lines` | List quote lines, filtered by quote or by part. Results are ordered by line_number ASC within a quote, otherwise by created_at ASC. | `PlatformAdmin`, `SalesRep`, `Customer` |
| POST | `/quotes/{quoteId}/issue` | Issue a DRAFT quote: pin today's copper index, price every line, and open the validity window. | `SalesRep` |
| POST | `/quotes/{quoteId}/reprice` | Reopen an ISSUED quote to DRAFT, discarding the pinned index and all priced money so it can be re-issued against the current index. | `SalesRep` |
| POST | `/quotes/{quoteId}/convert` | Convert an in-validity ISSUED quote into a SalesOrder. Fails and expires the quote when the validity window has passed. | `SalesRep` |
| GET | `/sales-orders/{orderId}` | Read one order: both status axes, the quoted and invoiced money, deposits and metal variance. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `CreditManager`, `Customer` |
| GET | `/sales-orders` | List orders on either status axis. Results are ordered by created_at ASC. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `CreditManager`, `Customer` |
| GET | `/order-lines/{orderLineId}` | Read one order line, including allocation status and both priced variants. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `Customer` |
| GET | `/order-lines` | List order lines, filtered by order, part or allocation status. Results are ordered by line_number ASC within an order, otherwise by created_at ASC. | `PlatformAdmin`, `SalesRep`, `BranchOps`, `Customer` |
| POST | `/sales-orders/{orderId}/allocate` | Run the reel allocator over the order under the chosen policy. OCC-guarded on the order's version. Allocates what the branch has and leaves short lines SHORT. | `BranchOps` |
| POST | `/sales-orders/{orderId}/release-allocations` | Compensating action: release every RESERVED allocation on the order and hand the footage back to the branch pool. | `BranchOps` |
| GET | `/allocations/{allocationId}` | Read one allocation, including its commit branch, cut window and any remnant it spawned. | `PlatformAdmin`, `BranchOps`, `SalesRep` |
| GET | `/allocations` | List allocations; remnant_reel_id finds the cut that produced a given remnant. Results are ordered by sequence_no ASC within an order line, otherwise by created_at ASC. | `PlatformAdmin`, `BranchOps`, `SalesRep` |
| POST | `/allocations/{allocationId}/cut` | Cut branch of the commit fork: occupy a buffered cut-floor window, cut the footage, and settle the reel remainder into a remnant, scrap or depletion. | `BranchOps` |
| POST | `/allocations/{allocationId}/pick` | Pick branch of the commit fork: stage a whole master reel intact, with no footage mutation, no remnant and no cut charge. | `BranchOps` |
| POST | `/delivery-runs` | Schedule a jobsite delivery for one staged order on one truck, deriving the reel-handling method. | `BranchOps` |
| GET | `/delivery-runs/{runId}` | Read one delivery run, including derived reel handling. | `PlatformAdmin`, `BranchOps`, `Driver`, `Customer` |
| GET | `/delivery-runs` | List delivery runs by order, truck, branch or status. Results are ordered by created_at ASC. | `PlatformAdmin`, `BranchOps`, `Driver`, `Customer` |
| POST | `/delivery-runs/{runId}/dispatch` | Driver dispatches their own truck on a scheduled run. | `Driver` |
| POST | `/delivery-runs/{runId}/deliver` | Driver completes the run. Fires the delivery cascade: order delivered, allocations consumed, reels on jobsite, order invoiced at the delivery-day copper index, customer balance and credit posture updated. | `Driver` |
| POST | `/order-lines/{orderLineId}/return` | Return one returnable reel delivered under this order line and credit the deposit. Cut lines are non-returnable. | `BranchOps` |
| POST | `/_clock/set_current_utc` | Set the server's logical clock. Before any call to this endpoint the logical clock reads exactly 2026-08-01T00:00:00Z; it never falls back to real wall-clock time. Every deadline (quote validity, deposit return window) is evaluated against this clock. | `PlatformAdmin` |

## 5. Error Code Catalogue

The catalogue below lists every error identifier the service can return together with its HTTP status code. The conditions that trigger each one are specified in the narrative of Sections 2 and 3, and the order in which competing conditions are evaluated is fixed by the admission ladder in Section 2.7.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_NOT_RESOURCE_OWNER` | 403 |
| `ERR_INVALID_REQUEST` | 422 |
| `ERR_BRANCH_NOT_FOUND` | 404 |
| `ERR_CUSTOMER_NOT_FOUND` | 404 |
| `ERR_PRODUCT_NOT_FOUND` | 404 |
| `ERR_TRUCK_NOT_FOUND` | 404 |
| `ERR_REEL_NOT_FOUND` | 404 |
| `ERR_QUOTE_NOT_FOUND` | 404 |
| `ERR_QUOTE_LINE_NOT_FOUND` | 404 |
| `ERR_ORDER_NOT_FOUND` | 404 |
| `ERR_ORDER_LINE_NOT_FOUND` | 404 |
| `ERR_ALLOCATION_NOT_FOUND` | 404 |
| `ERR_DELIVERY_RUN_NOT_FOUND` | 404 |
| `ERR_COPPER_INDEX_NOT_FOUND` | 404 |
| `ERR_DUPLICATE_PART_NUMBER` | 409 |
| `ERR_DUPLICATE_INDEX_DATE` | 409 |
| `ERR_QUOTE_NOT_DRAFT` | 409 |
| `ERR_QUOTE_NOT_ISSUED` | 409 |
| `ERR_QUOTE_HAS_NO_LINES` | 409 |
| `ERR_QUOTE_EXPIRED` | 409 |
| `ERR_NO_COPPER_INDEX` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_PUT_UP_NOT_ALLOWED` | 422 |
| `ERR_BELOW_ABSOLUTE_MIN_CUT` | 422 |
| `ERR_ORDER_NOT_ALLOCATABLE` | 409 |
| `ERR_NO_ELIGIBLE_REEL` | 409 |
| `ERR_PARALLEL_SET_INCOMPLETE` | 409 |
| `ERR_ALLOCATION_NOT_RESERVED` | 409 |
| `ERR_PUT_UP_MISMATCH` | 409 |
| `ERR_INVALID_CUT_WINDOW` | 422 |
| `ERR_CUT_BAY_CAPACITY_EXCEEDED` | 409 |
| `ERR_TRUCK_BRANCH_MISMATCH` | 409 |
| `ERR_TRUCK_WINDOW_CONFLICT` | 409 |
| `ERR_BOOM_LIFT_REQUIRED` | 409 |
| `ERR_ORDER_HAS_ACTIVE_RUN` | 409 |
| `ERR_ORDER_NOT_STAGED` | 409 |
| `ERR_RUN_INVALID_STATE` | 409 |
| `ERR_CUT_ITEM_NON_RETURNABLE` | 409 |
| `ERR_REEL_NOT_ON_JOBSITE` | 409 |
| `ERR_REEL_NOT_ON_ORDER_LINE` | 409 |
| `ERR_ORDER_NOT_DELIVERED` | 409 |
| `ERR_CUSTOMER_CREDIT_HOLD` | 402 |
| `ERR_CREDIT_LIMIT_EXCEEDED` | 402 |
| `ERR_STALE_QUOTE_VERSION` | 412 |
| `ERR_STALE_ORDER_VERSION` | 412 |

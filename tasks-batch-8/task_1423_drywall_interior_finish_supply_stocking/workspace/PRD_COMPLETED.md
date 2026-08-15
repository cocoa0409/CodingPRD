# Drywall Stocking API — Product Requirements Document

## 1. Introduction

A drywall and interior-finish supply house does far more than sell board over a counter. Its estimators build sheet-by-sheet takeoffs from blueprints, pad them with a breakage and waste allowance negotiated per contractor, round the result up to whole factory bundles, and quote a price. Its dispatchers then reserve boom trucks in half-day windows and deliver the material not to a loading dock but to a specific floor and room of a building that is still being framed. Its credit desk extends job-account credit, bills progress draws as each drop is stocked, applies payments as they arrive, and takes back unopened bundles — for a fee — when the framers over-order. Every one of those steps has a rule attached: rated board cannot be promised before the framing has progressed far enough to absorb the lead time, a boom truck cannot be in two places in the same half-day, a draw cannot be overpaid, and an account that blows through its credit limit stops being able to order.

This document specifies the REST API that runs that operation, mounted under `/supply`. It covers contractor account and credit management, the product catalog and boom-truck fleet, jobsite projects gated on framing progress, takeoff drafting with dual (provisional and final) pricing, stocking orders with room-level drops and tiered freight surcharges, automatic draw issuance on stocking confirmation, payment application, and bundle returns with restocking fees. It is written for the engineer implementing the service: global response, pagination, identity, and concurrency contracts live in Section 2, the business workflows live in Section 3, and Sections 4 and 5 provide the endpoint and error-code summaries.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the calling operator, and `X-User-Role`, identifying the capacity in which they act. A request whose `X-User-Role` header is missing or does not match one of the declared roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401); a request whose role is recognized but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Seven roles are recognized, spelled exactly as follows: `CreditManager`, `EstimatorUser`, `DispatcherUser`, `Foreman`, `ContractorAdmin`, `AccountsReceivableUser`, and `WarehouseManager`.

- A `CreditManager` is the supply house's credit and receivables officer: they open, suspend, reinstate, and close contractor accounts, void draw requests, and are the only role permitted to drive the test clock.
- An `EstimatorUser` is an inside-sales estimator who builds takeoffs, adds and cancels takeoff lines, and submits, locks, and cancels takeoffs.
- A `DispatcherUser` runs the boom-truck fleet: they register and update trucks, create stocking orders, add room-level drops, and schedule, dispatch, and cancel orders.
- A `Foreman` is the contractor-side jobsite supervisor who reports framing progress, opens and closes the stocking window on a project, and confirms an order as stocked.
- A `ContractorAdmin` is a contractor-side administrator who may create projects (a capability shared with `EstimatorUser`) and cancel projects.
- An `AccountsReceivableUser` is the AR clerk who applies payments to draw requests.
- A `WarehouseManager` is the warehouse lead who registers and updates products and files, accepts, and rejects bundle returns.

For every one of these seven roles — `CreditManager`, `EstimatorUser`, `DispatcherUser`, `Foreman`, `ContractorAdmin`, `AccountsReceivableUser`, and `WarehouseManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it for audit purposes but never compares it to any resource's `id` field and never requires or validates it — a request carrying only `X-User-Role` is processed identically to one carrying both headers; all authorization decisions rest on `X-User-Role` alone. Read-only retrieval endpoints are broadly available to the roles listed against each endpoint in Section 4, while each mutating operation is restricted to the role named there.

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
- A request to an unknown path — or to a known path with an unsupported method — is rejected with `ERR_NOT_FOUND` (HTTP 404) in this same envelope.

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0. List responses include the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope. Unless a more specific ordering is stated, every list endpoint returns resources sorted by `created_at` ascending, oldest first, with ties broken by `id` ascending. A `limit` below 1 or above 100, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_VALIDATION` (HTTP 400). `has_more` is true exactly when `offset` + `limit` is less than `total_count`.

### 2.4. Resource Identity, Timestamps, and Versioning

Every persisted resource carries an `id` field: a server-minted UUID with no type prefix. With one exception noted below, every resource also carries `created_at` and `updated_at` timestamps in ISO 8601 UTC format with three fractional digits, and an integer `version` field that starts at 1 on creation and increments by one on every mutation of that resource. The exception is the `Payment` resource: payments are append-only ledger entries and carry only `id` and `created_at`; they have neither `updated_at` nor `version`, and no operation ever mutates a recorded payment.

### 2.5. Money, Basis Points, and Rounding Discipline

All monetary amounts in this API are integer cents — never floats, never decimal strings. Fields such as `credit_limit_cents`, `unit_price_cents_per_sheet`, `quoted_line_cents`, `freight_charge_cents`, `requested_cents`, `amount_cents`, `restock_fee_cents`, and `credit_cents` are all integers counting cents.

Percentage-style allowances are expressed in **basis points**, where 10,000 basis points equal 100%. A contractor's `default_waste_pct_bp` and a takeoff's `waste_pct_bp_override` both follow this convention and are confined to the range 0 through 2,000 (that is, a waste allowance of at most 20%). The restocking fee rates and the fuel surcharge described in Section 3 are likewise denominated in basis points against the same 10,000 denominator.

Three rounding rules recur throughout the document and must be applied exactly: (1) sheet-level waste and bundle counts always round **up** to the next whole unit — a fractional sheet of waste or a fractional bundle is always a full one; (2) where a monetary computation produces a fraction of a cent — the dispatch-day fuel surcharge and the restocking fee — the result is rounded **half up** to the nearest whole cent; (3) day counts derived from timestamps are whole days, computed by taking the floor of the elapsed time in days.

### 2.6. The Logical Clock

All date-dependent validation in the system — lead-time checks, dispatch-day checks, restocking windows — runs against a **logical clock**, never the host wall clock. At server startup the logical clock reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back to wall-clock time at any point. A test-driving capability restricted to the `CreditManager` role advances the clock: the caller supplies a `to_iso8601` timestamp and the server sets its logical clock to that instant, returning the new value as `current_utc`. A `to_iso8601` value without a timezone offset is read as UTC; any supplied offset is honored and the stored instant is normalized to UTC, so `current_utc` is always reported with a `Z` suffix. Whenever this document says "today," it means the calendar date of the logical clock.

### 2.7. Nested Resource Paths and Resolution Order

Several resources live beneath their parents in the URL hierarchy — a takeoff's lines beneath the takeoff, a stocking order's drops beneath the order, a draw's payments beneath the draw. On any nested path, path parameters are validated **left to right**: each `id` segment (and, where present, a trailing `line_id` segment) must resolve to an existing resource, and each child must actually belong to the parent named to its left. The first segment that fails to resolve — or a child found to belong to a different parent — yields `ERR_NOT_FOUND` (HTTP 404), and no business validation runs before path resolution completes. Identifiers supplied in the request body rather than the path — `account_id`, `project_id`, `takeoff_id`, `boom_truck_id`, `product_id`, `stocking_order_id` — resolve the same way: a missing, wrongly typed, or unknown identifier is rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.8. Validation Priority and Error Surface

When a request violates more than one rule, the error reported is determined by a fixed global priority order, not by whichever check happens to execute first. The order is: authentication (`ERR_UNAUTHENTICATED`) first, then authorization (`ERR_FORBIDDEN`), then path resolution (`ERR_NOT_FOUND`), then the account-posture guard (`ERR_ACCOUNT_SUSPENDED`), then generic state guards (`ERR_INVALID_STATE`), and only then the business rules. Among business rules on the stocking-order scheduling path, the order is: the locked-takeoff requirement (`ERR_TAKEOFF_NOT_LOCKED`), then the rated-product lead-time requirement (`ERR_LEAD_TIME_VIOLATION`), then the half-day slot double-booking check (`ERR_SHIFT_DOUBLE_BOOKED`), then bundle capacity (`ERR_CAPACITY_EXCEEDED`), then payload weight (`ERR_WEIGHT_EXCEEDED`); the empty-order check (`ERR_EMPTY_ORDER`) and the inactive-truck check (`ERR_TRUCK_INACTIVE`) rank below all of these. On takeoff submission, the special-order lead-time check (`ERR_SPECIAL_ORDER_LEAD_TIME`) outranks the empty-takeoff check (`ERR_EMPTY_TAKEOFF`). Elsewhere the same principle applies pairwise: the rated-product return bar (`ERR_RATED_NON_RETURNABLE`) is evaluated before the cumulative over-return check (`ERR_OVER_RETURN`), and overpayment (`ERR_OVERPAYMENT`) is evaluated before an account-close balance check (`ERR_ACCOUNT_BALANCE_OPEN`) would ever be reached on the same request. Two error surfaces sit outside this ladder. A malformed request body or an invalid field value — a missing required field, a non-integer or out-of-range numeric value, an unknown enum value, a malformed `scheduled_date`, a duplicate `sku` or `truck_code` — is rejected with `ERR_VALIDATION` (HTTP 400), raised at the point the handler examines the offending field. And any state-guard violation that Section 3 does not assign a more specific error — a transition attempted from a state that does not permit it — is rejected with the generic `ERR_INVALID_STATE` (HTTP 409).

### 2.9. Optimistic Concurrency on Takeoff Locking

Exactly one write operation in the system is guarded by optimistic concurrency control: locking a takeoff. A lock request must carry the field `expected_takeoff_version`, holding the value of the takeoff's `version` the client last observed. If that value does not equal the takeoff's current `version` — because another estimator has since edited or locked it — the lock is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing a client from finalizing a pricing snapshot it never saw. No other endpoint accepts or requires a version field.

## 3. Business Logic & Workflows

### 3.1. Contractor Accounts and Credit Posture

Everything begins with credit. A `CreditManager` opens a contractor account by supplying the `company_name`, a `credit_limit_cents` ceiling in integer cents (zero or more), and a `default_waste_pct_bp` — the breakage and waste allowance, in basis points, that will pad every takeoff built for this contractor unless an individual takeoff overrides it. A new account starts in `ACTIVE` status with `ar_outstanding_cents` equal to zero.

`ar_outstanding_cents` is a computed ledger figure, never written directly: it increases by a draw's `requested_cents` at the moment the draw is issued, decreases by each payment's `amount_cents` as payments are applied, decreases by the full `requested_cents` when a draw is voided, and decreases by an accepted return's `credit_cents` — though a return credit can never push the ledger below zero. Equivalently, it reflects the sum of `requested_cents` across the account's open draws net of the payments applied against them.

Accounts move through `ACTIVE`, `SUSPENDED`, and `CLOSED`, the last of which is terminal. Suspending an account is a `CreditManager` action legal only while the account is `ACTIVE`; attempting it in any other state is rejected with `ERR_ACCOUNT_NOT_ACTIVE`. Suspension has teeth: every takeoff still in `DRAFT` on any project of the account is immediately cancelled (releasing no stock, since drafts reserve none), and any subsequent attempt to submit a takeoff on one of the account's projects is rejected with `ERR_ACCOUNT_SUSPENDED`. The same `ERR_ACCOUNT_SUSPENDED` guard blocks creation of new projects, new takeoffs, and new stocking orders while the account is not `ACTIVE`. It does not block the automatic draw issued when an order is confirmed stocked (Section 3.7): that draw is issued regardless of the account's posture. Reinstatement, also a `CreditManager` action, is legal only from `SUSPENDED` — attempting it from any other state is rejected with `ERR_INVALID_STATE` — and only while `ar_outstanding_cents` is at or below `credit_limit_cents`, failing which it is rejected with `ERR_ACCOUNT_BALANCE_OPEN`; on success it returns the account to `ACTIVE` and unblocks takeoff submission. Note that an account can also land in `SUSPENDED` without any credit-desk action — the draw-issuance cascade in Section 3.7 pushes it there automatically when a freshly issued draw carries outstanding receivables past the credit limit.

Closing an account requires the ledger to be fully settled: `ar_outstanding_cents` must be exactly zero, or the close is rejected with `ERR_ACCOUNT_BALANCE_OPEN`. Closure is permitted from either `ACTIVE` or `SUSPENDED` — attempting it from `CLOSED` is rejected with `ERR_INVALID_STATE` — and it cascades hard: every non-terminal project on the account is cancelled, and every non-terminal takeoff and every non-terminal stocking order on those projects is cancelled with it.

The account list can be filtered by `status` using the standard pagination parameters.

### 3.2. The Board Catalog and the Boom-Truck Fleet

A `WarehouseManager` registers each board product with its manufacturer `sku` (unique across the catalog), a `board_kind` of `REGULAR`, `FIRE_RATED`, or `MOISTURE_RATED`, physical dimensions — `length_ft` restricted to 8, 10, 12, 14, or 16 feet, `width_ft` always 4 feet, and `thickness_in` one of `1/2`, `5/8`, or `3/4` — the `sheets_per_bundle` of the factory bundle (a positive integer), the `unit_price_cents_per_sheet` in integer cents (greater than zero), and the `lead_time_days` from special-order placement to warehouse receipt. Lead time is zero for `REGULAR` board and at least one day for either rated kind; the rated kinds are exactly the special-order products. Violations of these field constraints — an out-of-set dimension, a non-positive `sheets_per_bundle` or unit price, a lead time inconsistent with the board kind, or a duplicate `sku` — are rejected with `ERR_VALIDATION` (HTTP 400). A new product is born with `active` set to true. The warehouse may later patch a product's `unit_price_cents_per_sheet`, `lead_time_days`, or `active` flag — patching `lead_time_days` re-applies the board-kind lead-time rules above, price changes flow into future pricing computations as described in Sections 3.4 and 3.5, and deactivating a product bars it from appearing on any new takeoff line. The product list supports filtering by `board_kind` and by `active` (the `active` filter treats `true`, `1`, and `yes`, case-insensitively, as true and any other value as false).

The fleet is administered by a `DispatcherUser`, who registers each boom truck with a unique human-readable `truck_code` (registering a duplicate is rejected with `ERR_VALIDATION`, HTTP 400), a `max_bundle_capacity` in whole bundles, and a `max_weight_lbs` payload limit — both positive. Trucks are created with `active` true, and capacity figures or the `active` flag can be patched later; an inactive truck cannot be reserved for any new order. The truck list can be filtered by `active`, with the same value parsing as the product list.

### 3.3. Jobsite Projects and the Stocking Window

A project represents one jobsite under a contractor account. Either an `EstimatorUser` or a `ContractorAdmin` may create one, supplying the owning `account_id`, a human-readable `jobsite_name`, the one-way `distance_miles` from the warehouse to the site in whole miles (greater than zero — this figure drives the freight surcharge in Section 3.6), and the foreman's initial `framing_pct_complete`, an integer from 0 to 100. Creation is only permitted while the account is `ACTIVE`. A new project starts in `PLANNING`, and the project list can be filtered by `account_id` and `status`.

The foreman keeps `framing_pct_complete` current as framing proceeds; either a `Foreman` or a `ContractorAdmin` may also patch `distance_miles` if logistics change, and either field may be patched regardless of the project's status. Framing progress is not merely informational — it gates the stocking window. When the foreman judges the site ready, they open stocking, moving the project from `PLANNING` to `STOCKING_OPEN`. Three preconditions guard that transition: `framing_pct_complete` must be at least 50 (otherwise `ERR_FRAMING_NOT_READY`), the account must be `ACTIVE` (otherwise `ERR_ACCOUNT_SUSPENDED`), and the project must already have at least one takeoff in `LOCKED` status (otherwise `ERR_NO_LOCKED_TAKEOFF`). They are evaluated in a fixed order on this transition: the `PLANNING` state guard runs first — ahead of the account-posture guard, an exception to the global ranking of Section 2.8 — followed by the account-posture check, the framing threshold, and finally the locked-takeoff requirement. Opening stocking permits the project's stocking orders to be scheduled; stocking-order creation itself is not gated on project status.

Closing the window — `STOCKING_OPEN` to `STOCKING_CLOSED`, again a `Foreman` action — is refused while any of the project's stocking orders sits in `SCHEDULED` or `DISPATCHED` (`ERR_ORDERS_IN_FLIGHT`); a successful close cancels any orders still in `DRAFT`; because the project is then no longer `STOCKING_OPEN`, no order on it can subsequently be scheduled. A `ContractorAdmin` may instead cancel the project outright. From `PLANNING` the cancellation is unconditional and simply cancels every non-terminal takeoff on the project. From `STOCKING_OPEN` it is refused while any order is `DISPATCHED` (`ERR_ORDERS_IN_FLIGHT`); when allowed, it cancels all `DRAFT` and `SCHEDULED` stocking orders — releasing their boom-truck reservations — and every non-terminal takeoff alongside. Both `STOCKING_CLOSED` and `CANCELLED` are terminal for a project.

### 3.4. Building and Pricing a Takeoff

An `EstimatorUser` drafts a takeoff against a project by passing the `project_id` and, optionally, a `waste_pct_bp_override` — a per-takeoff waste allowance in basis points, either null or within 0 to 2,000. Creation requires the owning account to be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`); the project's own status is not checked. The draft begins in `DRAFT` status with `base_sheet_count`, `billable_sheet_count`, and `quoted_subtotal_cents` at zero and `final_subtotal_cents` null. The estimator then adds lines one at a time while the takeoff remains in `DRAFT`, each line naming a `product_id` and a net `sheet_count` greater than zero; only products whose `active` flag is true may be added — a deactivated product is rejected with `ERR_VALIDATION` (HTTP 400). A new line carries `waste_sheets`, `bundle_count`, and `quoted_line_cents` at zero and `final_line_cents` null until submission prices it. A line added in error is soft-cancelled — permitted only while the takeoff is still in `DRAFT` — which flips its `line_status` from `ACTIVE` to `CANCELLED` and excludes it from every aggregate. Line listings can be filtered by `takeoff_id`, `product_id`, and `line_status`, and takeoff listings by `project_id` and `status`.

Nothing is priced while the takeoff is drafted. Submission is the first pricing event: the takeoff moves from `DRAFT` to `SUBMITTED`, guarded by two checks — the owning account must be `ACTIVE` (`ERR_ACCOUNT_SUSPENDED`) and the takeoff must contain at least one line whose `line_status` is `ACTIVE` (`ERR_EMPTY_TAKEOFF`), with the special-order check described below ranking ahead of the empty-takeoff check in the global priority order. At submission the system prices every active line provisionally. The **effective waste allowance** for the takeoff is the `waste_pct_bp_override` when one was supplied, otherwise the account's `default_waste_pct_bp`. Each active line's `waste_sheets` is its `sheet_count` multiplied by that effective allowance and divided by the 10,000 basis-point denominator, rounded **up** to a whole sheet. Each active line's `bundle_count` is the sum of its `sheet_count` and `waste_sheets` divided by the product's `sheets_per_bundle`, again rounded up — bundles are never split at the takeoff stage. The line's `quoted_line_cents` is then its `bundle_count` multiplied by the product's `sheets_per_bundle` multiplied by the product's **current** `unit_price_cents_per_sheet` — the provisional variant snaps today's catalog prices. Rolling up across active lines, the takeoff's `base_sheet_count` is the plain sum of `sheet_count`, its `billable_sheet_count` is the sum of `sheet_count` plus `waste_sheets` per line (equivalently, the base count padded for waste and rounded up to whole sheets), and its `quoted_subtotal_cents` is the sum of the per-line `quoted_line_cents`.

Submission also enforces the special-order lead-time rule. For every active line whose product's `board_kind` is `FIRE_RATED` or `MOISTURE_RATED`, the parent project's `framing_pct_complete` must be at least 30 — a jobsite that has not framed at least 30 percent cannot absorb the rated board's procurement lead time, and the submission is rejected with `ERR_SPECIAL_ORDER_LEAD_TIME`. Takeoffs containing no rated lines pass this check unconditionally.

A takeoff may be cancelled instead. From `DRAFT` the cancellation is unconditional. From `SUBMITTED` it is refused while any stocking order referencing the takeoff sits in `SCHEDULED` or `DISPATCHED` (`ERR_TAKEOFF_IN_USE`). `LOCKED` and `CANCELLED` are terminal for a takeoff — cancellation attempted from either is rejected with `ERR_INVALID_STATE` — so "non-terminal takeoff" throughout this document means one in `DRAFT` or `SUBMITTED`.

### 3.5. Locking Final Prices

A submitted takeoff is still a quote, not a bill. Locking converts it: the estimator locks a takeoff from `SUBMITTED` to `LOCKED`, and at that instant every active line is repriced. The `final_line_cents` of each line is recomputed exactly as the quoted amount was — bundle arithmetic unchanged — but using the product's `unit_price_cents_per_sheet` **as it stands at lock time** and the effective waste allowance as it stands at lock time, so a catalog price change between submission and lock flows into the final figures. The takeoff's `final_subtotal_cents` is the sum of those per-line final amounts, while `quoted_subtotal_cents` is deliberately preserved untouched so the quote-to-final variance can be reported. `final_line_cents` and `final_subtotal_cents` are carried as null before the lock; they are populated only at this transition.

Two guards protect the lock. The takeoff must actually be in `SUBMITTED` — locking anything else is rejected with `ERR_TAKEOFF_NOT_SUBMITTED` — and the optimistic-concurrency rule of Section 2.9 applies: the request must carry `expected_takeoff_version` equal to the takeoff's current `version`, failing which the lock is rejected with `ERR_STALE_VERSION` (HTTP 412). A successful lock increments the takeoff's `version` by one, so a second lock attempt carrying the same expected version necessarily fails as stale.

### 3.6. Stocking Orders: Drops, Capacity, and the Half-Day Slot

A `DispatcherUser` builds a stocking order against a project, supplying the `project_id`, the `takeoff_id` of the locked takeoff the order is built from, the `scheduled_date` as an ISO 8601 calendar date in `YYYY-MM-DD` form, the `shift_window` — `AM` or `PM`, the half-day window the truck is reserved for — and the `boom_truck_id` of the truck being reserved. Creation requires the account to be `ACTIVE`; beyond that, the referenced project, takeoff, and boom truck need only exist — the project's `STOCKING_OPEN` status and the takeoff's `LOCKED` status are enforced at scheduling, not at creation. The order starts in `DRAFT` with `freight_charge_cents` at zero, and the dispatcher then adds room-level drops to it: each drop names a `floor_label` (identifiers like `L1` or `P2`), a `room_label` within that floor, a `product_id`, and a whole-bundle `bundle_count` greater than zero. As each drop is recorded the system computes its `sheet_weight_lbs` — the drop's `bundle_count` multiplied by the product's `sheets_per_bundle` multiplied by a per-sheet weight lookup for that board: 40 lbs per sheet for 1/2-inch, 50 lbs for 5/8-inch, and 60 lbs for 3/4-inch board — which feeds the boom-capacity check at scheduling. Order listings can be filtered by `project_id`, `boom_truck_id`, `scheduled_date`, `status`, and `takeoff_id`; drop listings by `stocking_order_id` and `product_id`.

Scheduling moves the order from `DRAFT` to `SCHEDULED` and is the most heavily guarded transition in the system. The project must be in `STOCKING_OPEN` (`ERR_PROJECT_NOT_STOCKING_OPEN`); the takeoff referenced by the order's `takeoff_id` must be `LOCKED` and must belong to the same project (`ERR_TAKEOFF_NOT_LOCKED`); the referenced truck must exist and be active (`ERR_TRUCK_INACTIVE`); the order must contain at least one drop (`ERR_EMPTY_ORDER`); the sum of `bundle_count` across all drops must not exceed the truck's `max_bundle_capacity` (`ERR_CAPACITY_EXCEEDED`); and the sum of `sheet_weight_lbs` across all drops must not exceed the truck's `max_weight_lbs` (`ERR_WEIGHT_EXCEEDED`). Section 2.8 fixes the order in which these checks report when several fail at once.

Two temporal rules complete the scheduling gate. First, the half-day slot must be free: no other stocking order in `SCHEDULED` or `DISPATCHED` may hold the same combination of `boom_truck_id`, `scheduled_date`, and `shift_window` — each reservation occupies the half-open interval from shift start to shift end, so back-to-back `AM` and `PM` bookings on one truck are legal but overlapping ones are rejected with `ERR_SHIFT_DOUBLE_BOOKED`. Second, the `scheduled_date` must respect procurement lead time: it must fall no earlier than today plus the maximum `lead_time_days` among the products on the order's drops that are `FIRE_RATED` or `MOISTURE_RATED`, while an order carrying only `REGULAR` product merely requires a `scheduled_date` of today or later — violations are rejected with `ERR_LEAD_TIME_VIOLATION`.

A successful schedule computes the order's `freight_charge_cents` provisionally and reserves the truck slot, blocking other orders from taking it. Freight is tiered on the project's `distance_miles`: a distance of at most 25 miles is charged a flat 9,500 cents; beyond 25 miles and up to 75 miles the charge is a flat 19,500 cents plus 320 cents for each mile beyond the 25th; beyond 75 miles the charge is that same 19,500-cent base plus 320 cents for each of the 50 miles from the 25th to the 75th, plus 480 cents for each mile beyond the 75th. The provisional figure applies no fuel surcharge.

Cancelling an order is a `DispatcherUser` action available from `DRAFT` or `SCHEDULED`. Cancelling a draft releases nothing — the reservation is a no-op because none exists yet — while cancelling a scheduled order releases its truck-date-shift reservation for others to claim. Both land the order in terminal `CANCELLED`.

### 3.7. Dispatch Day, Stocking Confirmation, and the Automatic Draw

On the morning of the job, dispatch moves the order from `SCHEDULED` to `DISPATCHED`. The order must be `SCHEDULED`, today per the logical clock must equal the order's `scheduled_date` (dispatching on any other date is rejected with `ERR_NOT_DISPATCH_DAY`), and the project must still be `STOCKING_OPEN` (`ERR_PROJECT_NOT_STOCKING_OPEN`). Dispatch re-quotes the freight: the tiered charge from Section 3.6 is recomputed from the current `distance_miles`, and a fuel surcharge of 750 basis points — seven and a half percent — is applied on top, with the result rounded half up to whole cents. This final `freight_charge_cents` replaces the provisional figure. Notably, dispatch itself does not move accounts receivable; only draws move AR.

When the boom operator finishes, the `Foreman` confirms the order stocked, moving it from `DISPATCHED` to terminal `STOCKED`. Confirmation records a `stocked_at` timestamp on the order — null until this point — taken from the logical clock; it later anchors the restocking window of Section 3.9. That confirmation automatically issues a draw request against the project for this order, regardless of the account's credit posture — no account-posture guard runs at confirmation. The draw's `requested_cents` is the sum of two parts: the material component, computed by taking the locked takeoff's lines that are still `ACTIVE`, keeping only those whose `product_id` actually appears among the distinct products in this order's drops, and summing their `final_line_cents`; plus the order's (final) `freight_charge_cents`. The new draw starts in `ISSUED` with `paid_cents` at zero, and the account's `ar_outstanding_cents` increases by `requested_cents` at once.

That increment can break the account's credit posture. If `ar_outstanding_cents` exceeds `credit_limit_cents` after the draw lands, an `ACTIVE` account cascades into `SUSPENDED` immediately — an account already `SUSPENDED` simply keeps that status with the higher ledger — blocking new projects, takeoffs, takeoff submissions, and stocking orders until the credit desk collects or raises the limit and reinstates it.

### 3.8. Payments, Voids, and the AR Ledger

An `AccountsReceivableUser` applies payments to draws that are `ISSUED` or `PARTIALLY_PAID`. Each payment is recorded against the draw it settles — its `draw_request_id` points back at that draw — and carries an `amount_cents` (a positive integer), a `method` of `ACH`, `CHECK`, or `CARD`, and a `received_at` ISO 8601 timestamp that is recorded verbatim on the payment; payments are applied in the order they are submitted, not in `received_at` order. The amount may never exceed the draw's remaining balance — `requested_cents` minus `paid_cents` — or the payment is rejected with `ERR_OVERPAYMENT`. A payment below the remaining balance moves an `ISSUED` draw to `PARTIALLY_PAID` (or leaves a `PARTIALLY_PAID` draw there) and adds to `paid_cents`; a payment exactly equal to the remaining balance moves the draw to terminal `PAID` and brings `paid_cents` up to `requested_cents`. Either way the account's `ar_outstanding_cents` decreases by `amount_cents`. Payments on a draw can be listed for audit; the draw list itself is filterable by `project_id`, `status`, and `stocking_order_id`.

A `CreditManager` may void a draw that has never received a payment — `paid_cents` must be zero, otherwise `ERR_DRAW_HAS_PAYMENTS`. Voiding moves an `ISSUED` draw to terminal `VOIDED` and backs its full `requested_cents` out of `ar_outstanding_cents`.

### 3.9. Bundle Returns and Restocking Credits

When a jobsite over-orders, a `WarehouseManager` files a bundle return against a stocked order, supplying the `stocking_order_id`, the `product_id` being returned, the whole `bundles_returned` (zero or more), and any `loose_sheets_returned` from a partially opened bundle — zero or more, and always strictly fewer than the product's `sheets_per_bundle`. The return is born in `PENDING_INSPECTION` with `restock_fee_cents` and `credit_cents` at zero until acceptance computes them; filing requires only that the referenced order and product exist — the order's `STOCKED` status is enforced at acceptance, not at filing — and the returns list is filterable by `stocking_order_id`, `product_id`, and `status`.

Two product-level bars apply both at filing and again at acceptance. Only `REGULAR` board is returnable: a return naming a `FIRE_RATED` or `MOISTURE_RATED` product is rejected with `ERR_RATED_NON_RETURNABLE`. And the cumulative quantity returned for a product on an order — counting every previously `ACCEPTED` return plus the one now requested, bundles and loose sheets together — must not exceed the quantity of that product actually delivered on the order, or the request is rejected with `ERR_OVER_RETURN`; per Section 2.8 the rated-product bar is evaluated first.

Acceptance, a `WarehouseManager` action, additionally requires the source stocking order to be `STOCKED` (`ERR_ORDER_NOT_STOCKED`). On acceptance the system computes the money. The returned **material value** is the total returned sheets — `bundles_returned` full bundles of `sheets_per_bundle` sheets each, plus the `loose_sheets_returned` — multiplied by the product's current `unit_price_cents_per_sheet`. The **restocking fee rate** depends on timing and bundle integrity: if the return is accepted no more than 7 whole days after the order was stocked (elapsed time measured in floored days), the rate is zero and the material is credited in full; otherwise, a return of intact bundles only — `loose_sheets_returned` equal to zero — is charged 1,500 basis points (15%), while a return containing loose sheets from an opened bundle is charged 2,500 basis points (25%). The `restock_fee_cents` is the material value multiplied by the applicable rate over the 10,000 basis-point denominator, rounded half up to whole cents, and the `credit_cents` granted to the account is the material value minus that fee. The account's `ar_outstanding_cents` then decreases by `credit_cents`, floored at zero so a credit can never drive the ledger negative. A return that fails inspection is instead rejected, moving from `PENDING_INSPECTION` to `REJECTED` with no financial effect. Both `ACCEPTED` and `REJECTED` are terminal.

## 4. Endpoint Definitions

Creating a new resource returns HTTP 201; operations that modify, transition, or fetch an existing resource return HTTP 200. All responses use the envelope of Section 2.2, all lists paginate per Section 2.3, and every endpoint enforces the role restrictions below via the headers of Section 2.1.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /supply/contractor-accounts | Open a new contractor account | CreditManager |
| GET | /supply/contractor-accounts/{id} | Fetch one contractor account | CreditManager, EstimatorUser, DispatcherUser, Foreman, AccountsReceivableUser, WarehouseManager |
| GET | /supply/contractor-accounts | List contractor accounts | CreditManager, AccountsReceivableUser |
| POST | /supply/contractor-accounts/{id}/suspend | Suspend an account (blocks new takeoffs and draws) | CreditManager |
| POST | /supply/contractor-accounts/{id}/reinstate | Reinstate a suspended account | CreditManager |
| POST | /supply/contractor-accounts/{id}/close | Close an account (requires zero AR) | CreditManager |
| POST | /supply/products | Register a board product SKU | WarehouseManager |
| GET | /supply/products/{id} | Fetch a product | CreditManager, EstimatorUser, DispatcherUser, Foreman, AccountsReceivableUser, WarehouseManager |
| GET | /supply/products | List products | CreditManager, EstimatorUser, DispatcherUser, Foreman, AccountsReceivableUser, WarehouseManager |
| PATCH | /supply/products/{id} | Update product price / lead time / active flag | WarehouseManager |
| POST | /supply/boom-trucks | Register a boom truck | DispatcherUser |
| GET | /supply/boom-trucks/{id} | Fetch a boom truck | DispatcherUser, Foreman, WarehouseManager |
| GET | /supply/boom-trucks | List boom trucks | DispatcherUser, Foreman, WarehouseManager |
| PATCH | /supply/boom-trucks/{id} | Update boom-truck capacity / active flag | DispatcherUser |
| POST | /supply/projects | Create a jobsite project under an account | EstimatorUser, ContractorAdmin |
| GET | /supply/projects/{id} | Fetch a project | CreditManager, EstimatorUser, DispatcherUser, Foreman, ContractorAdmin |
| GET | /supply/projects | List projects (filterable by account) | CreditManager, EstimatorUser, DispatcherUser, Foreman, ContractorAdmin |
| PATCH | /supply/projects/{id} | Update framing progress or distance | Foreman, ContractorAdmin |
| POST | /supply/projects/{id}/open-stocking | Move project PLANNING → STOCKING_OPEN | Foreman |
| POST | /supply/projects/{id}/close-stocking | Move project STOCKING_OPEN → STOCKING_CLOSED | Foreman |
| POST | /supply/projects/{id}/cancel | Cancel a project | ContractorAdmin |
| POST | /supply/takeoffs | Create a draft takeoff under a project | EstimatorUser |
| GET | /supply/takeoffs/{id} | Fetch a takeoff | EstimatorUser, Foreman, CreditManager, ContractorAdmin |
| GET | /supply/takeoffs | List takeoffs (filterable by project / status) | EstimatorUser, Foreman, CreditManager, ContractorAdmin |
| POST | /supply/takeoffs/{id}/lines | Add a line to a DRAFT takeoff | EstimatorUser |
| GET | /supply/takeoff-lines | List takeoff lines (filterable by takeoff / product) | EstimatorUser, Foreman, CreditManager, ContractorAdmin |
| GET | /supply/takeoff-lines/{id} | Fetch a single takeoff line | EstimatorUser, Foreman, CreditManager, ContractorAdmin |
| DELETE | /supply/takeoffs/{id}/lines/{line_id} | Soft-cancel a takeoff line (only while takeoff is DRAFT) | EstimatorUser |
| POST | /supply/takeoffs/{id}/submit | Submit a DRAFT takeoff (computes provisional pricing) | EstimatorUser |
| POST | /supply/takeoffs/{id}/lock | Lock a SUBMITTED takeoff (computes final pricing) | EstimatorUser |
| POST | /supply/takeoffs/{id}/cancel | Cancel a takeoff | EstimatorUser |
| POST | /supply/stocking-orders | Create a DRAFT stocking order against a LOCKED takeoff | DispatcherUser |
| GET | /supply/stocking-orders/{id} | Fetch a stocking order | DispatcherUser, Foreman, CreditManager, WarehouseManager, AccountsReceivableUser |
| GET | /supply/stocking-orders | List stocking orders (filterable by project / truck / date / takeoff) | DispatcherUser, Foreman, CreditManager, WarehouseManager, AccountsReceivableUser |
| GET | /supply/stocking-drops | List stocking drops (filterable by product / order) | DispatcherUser, Foreman, WarehouseManager |
| GET | /supply/stocking-drops/{id} | Fetch a single stocking drop | DispatcherUser, Foreman, WarehouseManager |
| POST | /supply/stocking-orders/{id}/drops | Add a room-level drop to a DRAFT stocking order | DispatcherUser |
| GET | /supply/stocking-orders/{id}/drops | List drops on an order | DispatcherUser, Foreman, WarehouseManager |
| POST | /supply/stocking-orders/{id}/schedule | Schedule the order; reserves the boom-truck slot and computes provisional freight | DispatcherUser |
| POST | /supply/stocking-orders/{id}/dispatch | Dispatch the order on its scheduled date; re-quotes freight with fuel surcharge | DispatcherUser |
| POST | /supply/stocking-orders/{id}/mark-stocked | Confirm stocked; auto-issues the draw request | Foreman |
| POST | /supply/stocking-orders/{id}/cancel | Cancel a DRAFT or SCHEDULED order (releases reservation) | DispatcherUser |
| GET | /supply/draw-requests/{id} | Fetch a draw request | CreditManager, AccountsReceivableUser, EstimatorUser |
| GET | /supply/draw-requests | List draw requests (filterable by project / status / order) | CreditManager, AccountsReceivableUser, EstimatorUser |
| POST | /supply/draw-requests/{id}/payments | Apply a payment to a draw (full or partial) | AccountsReceivableUser |
| GET | /supply/draw-requests/{id}/payments | List payments applied to a draw | CreditManager, AccountsReceivableUser |
| POST | /supply/draw-requests/{id}/void | Void an unpaid draw | CreditManager |
| POST | /supply/bundle-returns | File a return against a STOCKED order | WarehouseManager |
| GET | /supply/bundle-returns/{id} | Fetch a bundle return | WarehouseManager, CreditManager, AccountsReceivableUser |
| GET | /supply/bundle-returns | List returns (filterable by order / product / status) | WarehouseManager, CreditManager, AccountsReceivableUser |
| POST | /supply/bundle-returns/{id}/accept | Accept a return; computes restock fee and credits the account | WarehouseManager |
| POST | /supply/bundle-returns/{id}/reject | Reject a return | WarehouseManager |
| POST | /supply/_clock/set_current_utc | Set the server's logical clock | CreditManager |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of Sections 2 and 3; this table is the summary of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_ACCOUNT_SUSPENDED | 409 |
| ERR_ACCOUNT_BALANCE_OPEN | 409 |
| ERR_ACCOUNT_NOT_ACTIVE | 409 |
| ERR_FRAMING_NOT_READY | 422 |
| ERR_NO_LOCKED_TAKEOFF | 422 |
| ERR_ORDERS_IN_FLIGHT | 409 |
| ERR_EMPTY_TAKEOFF | 422 |
| ERR_TAKEOFF_NOT_SUBMITTED | 409 |
| ERR_TAKEOFF_IN_USE | 409 |
| ERR_TAKEOFF_NOT_LOCKED | 409 |
| ERR_SPECIAL_ORDER_LEAD_TIME | 422 |
| ERR_PROJECT_NOT_STOCKING_OPEN | 409 |
| ERR_TRUCK_INACTIVE | 422 |
| ERR_EMPTY_ORDER | 422 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_WEIGHT_EXCEEDED | 422 |
| ERR_SHIFT_DOUBLE_BOOKED | 409 |
| ERR_LEAD_TIME_VIOLATION | 422 |
| ERR_NOT_DISPATCH_DAY | 409 |
| ERR_ORDER_NOT_STOCKED | 409 |
| ERR_OVER_RETURN | 422 |
| ERR_RATED_NON_RETURNABLE | 422 |
| ERR_OVERPAYMENT | 422 |
| ERR_DRAW_HAS_PAYMENTS | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_VALIDATION | 400 |
